"""Auto-completion for the Text editor (no Qt here – the popup is in text_editor.py).

Candidates:
- after a dot: the attributes of the object before it – ``bpy.context.`` → ``object``, ``scene``…,
  ``qs.`` → the Qt Shell API. The object is found without running any code: names come from the
  script's namespace (when it has run), the modules it imports (only modules that are already loaded),
  simple assignments (``ob = bpy.context.object``) and for-loops over collections
  (``for ob in bpy.data.objects:`` → an object of that collection);
- otherwise: Python keywords, builtins, the names above and the words of the document.
"""
import builtins
import keyword
import re
import sys

_IDENT = re.compile(r"[A-Za-z_]\w*")
_TAIL = re.compile(r"([A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)*\.?|\.?)$")
_IMPORT = re.compile(r"^\s*import\s+(.+)$", re.M)
_FROM = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+\(?([^)#\n]+)", re.M)
_ASSIGN = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*([A-Za-z_][\w.]*)\s*(?:#.*)?$", re.M)
_FOR = re.compile(r"^\s*for\s+([A-Za-z_]\w*)\s+in\s+([A-Za-z_][\w.]*)\s*:", re.M)
_WITH = re.compile(r"^\s*with\s+([A-Za-z_][\w.]*)\s+as\s+([A-Za-z_]\w*)\s*:", re.M)

MAX_ITEMS = 2000           # never more candidates than this
_CALLABLE_CHECK_LIMIT = 400  # above this, don't getattr every name to mark callables


def split(line_before):
    """(base expression or None, prefix) of the text before the cursor.
    'bpy.context.ob' → ('bpy.context', 'ob');  'bpy.' → ('bpy', '');  'pri' → (None, 'pri')."""
    m = _TAIL.search(line_before)
    tail = m.group(1) if m else ""
    if tail.startswith(".") or (m and m.start(1) > 0 and line_before[m.start(1) - 1] in ")]\"'"):
        return None, ""                       # after a call / index / string – unknown object
    if "." in tail:
        base, _, prefix = tail.rpartition(".")
        return base, prefix
    return None, tail


def in_string_or_comment(line_before):
    """Rough check whether the cursor is inside a string or a comment on this line."""
    quote = None
    i = 0
    while i < len(line_before):
        ch = line_before[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if line_before.startswith(quote, i):
                i += len(quote)
                quote = None
                continue
        else:
            if ch == "#":
                return True
            for q in ('"""', "'''", '"', "'"):
                if line_before.startswith(q, i):
                    quote = q
                    i += len(q) - 1
                    break
        i += 1
    return quote is not None


def imports_namespace(source):
    """Names bound by the import statements of the source – only for modules that are already
    loaded (nothing is imported here, so no code runs)."""
    ns = {}
    for m in _IMPORT.finditer(source):
        for part in m.group(1).split("#")[0].split(","):
            part = part.strip()
            if not part:
                continue
            name, _, alias = part.partition(" as ")
            name, alias = name.strip(), alias.strip()
            mod = sys.modules.get(name)
            if alias:
                if mod is not None:
                    ns[alias] = mod
            else:
                top = name.split(".")[0]
                if top in sys.modules:
                    ns[top] = sys.modules[top]
    for m in _FROM.finditer(source):
        mod = sys.modules.get(m.group(1))
        if mod is None:
            continue
        for part in m.group(2).split(","):
            part = part.strip()
            if not part or part == "*":
                continue
            name, _, alias = part.partition(" as ")
            name, alias = name.strip(), alias.strip() or name.strip()
            try:
                ns[alias] = getattr(mod, name)
            except AttributeError:
                sub = sys.modules.get(f"{m.group(1)}.{name}")
                if sub is not None:
                    ns[alias] = sub
    return ns


def _first_item(obj):
    """An element of a collection, to complete a for-loop variable – only for collections that can
    be indexed without side effects (bpy collections, lists, tuples)."""
    try:
        tname = type(obj).__name__
        if tname == "bpy_prop_collection" or isinstance(obj, (list, tuple)):
            if len(obj):
                return obj[0]
    except Exception:
        pass
    return None


def _getattr_chain(obj, names):
    for n in names:
        try:
            obj = getattr(obj, n)
        except Exception:
            return None
        if obj is None:
            return None
    return obj


def resolve(expr, ns, source="", _depth=0):
    """Object for a dotted expression like 'bpy.context.object', or None. No code is run."""
    if _depth > 8 or not expr:
        return None
    names = expr.split(".")
    head = names[0]
    if head in ns:
        obj = ns[head]
    elif hasattr(builtins, head):
        obj = getattr(builtins, head)
    else:
        obj = _infer(head, ns, source, _depth)
        if obj is None:
            return None
    return _getattr_chain(obj, names[1:])


def _infer(name, ns, source, depth):
    """Value of a variable from the last assignment / for-loop / with in the source."""
    found = None
    for rx, kind in ((_ASSIGN, "="), (_FOR, "for"), (_WITH, "with")):
        for m in rx.finditer(source):
            var, expr = (m.group(2), m.group(1)) if kind == "with" else (m.group(1), m.group(2))
            if var == name and expr.split(".")[0] != name:
                if found is None or m.start() > found[0]:
                    found = (m.start(), kind, expr)
    if found is None:
        return None
    _pos, kind, expr = found
    obj = resolve(expr, ns, source, depth + 1)
    if obj is not None and kind == "for":
        obj = _first_item(obj)
    return obj


def _attr_names(obj):
    try:
        names = set(dir(obj))
    except Exception:
        names = set()
    # bpy collections: also the names of their items are useful after ["…"] – not here; but RNA
    # properties of a struct are in dir() already
    try:
        rna = getattr(obj, "bl_rna", None)
        if rna is not None:
            names.update(p.identifier for p in rna.properties)
            names.update(f.identifier for f in getattr(rna, "functions", ()))
    except Exception:
        pass
    return names


def candidates(base, prefix, ns, source=""):
    """Sorted list of (name, is_callable) completing `prefix` (case-insensitive, starts-with)."""
    low = prefix.lower()
    show_private = prefix.startswith("_")
    if base is not None:
        obj = resolve(base, ns, source)
        if obj is None:
            return []
        names = _attr_names(obj)
        names.discard("bl_rna") if not show_private else None
        pool = [n for n in names if n.lower().startswith(low) and (show_private or not n.startswith("_"))]
        pool.sort(key=lambda n: (n.lower() != low, n.startswith("_"), n.lower()))
        pool = pool[:MAX_ITEMS]
        check = len(pool) <= _CALLABLE_CHECK_LIMIT
        out = []
        for n in pool:
            is_call = False
            if check:
                try:
                    is_call = callable(getattr(obj, n))
                except Exception:
                    pass
            out.append((n, is_call))
        return out
    words = set(keyword.kwlist)
    words.update(n for n in dir(builtins) if not n.startswith("_"))
    words.update(ns)
    words.update(w for w in _IDENT.findall(source) if len(w) >= 3)
    for m in _ASSIGN.finditer(source):
        words.add(m.group(1))
    pool = [w for w in words if w.lower().startswith(low) and w != prefix and (show_private or not w.startswith("__"))]
    pool.sort(key=lambda n: (n.startswith("_"), n.lower()))
    out = []
    for n in pool[:MAX_ITEMS]:
        v = ns.get(n, getattr(builtins, n, None))
        out.append((n, callable(v) and not isinstance(v, type(sys))))
    return out

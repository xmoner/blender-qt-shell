"""Python tooltips (like Blender's Preferences → Interface → Python Tooltips).

Widgets and menu actions carry the Python command they run in the Qt property "qtshell_python".
When the option is on (Edit → Qt Preferences… → Interface → Python Tooltips), an application-wide
event filter adds that command to the tooltip:

    Add a cube mesh
    Python: bpy.ops.mesh.primitive_cube_add()

    Location
    Python: bpy.data.objects["Cube"].location

Shift + middle click on a button / field / menu item copies its command to the clipboard (always on).

Widgets whose parts are not widgets (tree rows, cells) define qtshell_python_at(widget, pos) and return
(tooltip, command) for the spot under the mouse – see outliner._Tree.

Usage in code:  pytips.tag(widget_or_action, "bpy.ops.object.delete()")
                pytips.tag_op(widget, "mesh.primitive_cube_add", {"size": 2})
                pytips.tag_prop(widget, data, "location", index=-1)
"""
import html

from PySide6 import QtCore, QtGui, QtWidgets

PROP = "qtshell_python"
KEY = "interface/python_tooltips"
_enabled = None
_filter = None


# ---------------------------------------------------------------- setting
def enabled():
    global _enabled
    if _enabled is None:
        _enabled = str(QtCore.QSettings("QtShell", "QtShell").value(KEY, "false")).lower() == "true"
    return _enabled


def set_enabled(on):
    global _enabled
    _enabled = bool(on)
    QtCore.QSettings("QtShell", "QtShell").setValue(KEY, "true" if on else "false")


# ---------------------------------------------------------------- python text
def _value(v):
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, set):
        return "{" + ", ".join(repr(x) for x in sorted(v)) + "}"
    try:
        if hasattr(v, "__len__") and not isinstance(v, (dict, bytes)):
            return "(" + ", ".join(_value(x) for x in v) + ("," if len(v) == 1 else "") + ")"
    except Exception:
        pass
    if isinstance(v, float):
        return f"{v:g}"
    return repr(v)


def op_text(idname, props=None):
    """bpy.ops.<module>.<name>(prop=value, …)"""
    args = ", ".join(f"{k}={_value(v)}" for k, v in (props or {}).items() if not isinstance(v, dict))
    return f"bpy.ops.{idname}({args})"


def data_path(data):
    """Python path of an RNA struct, e.g. bpy.data.objects["Cube"].modifiers["Subdivision"] – checked: the path
    must lead to the same struct (Blender's repr / path_from_id skip a level for some nested structs, e.g.
    animation_visualization.motion_path)."""
    p = _data_path(data)
    if p and p.startswith("bpy.") and not _same(p, data):
        found = _find_from_id(data)
        if found:
            return found
    return p


def _same(path, data):
    try:
        import bpy
        v = eval(path, {"bpy": bpy})
        return v.as_pointer() == data.as_pointer() and type(v) is type(data)
    except Exception:
        return True                          # can't check (no as_pointer …) – keep the path


def _data_path(data):
    try:
        r = repr(data)
        if r.startswith("bpy.") and "..." not in r:   # Blender shortens some paths with "..." – not runnable
            return r.replace("'", '"')
    except Exception:
        pass
    try:
        idd = data.id_data
        base = repr(idd).replace("'", '"') if idd is not None else ""
        sub = data.path_from_id()
        if base.startswith("bpy.") and "..." not in base:
            return f"{base}.{sub}" if sub else base
    except Exception:
        pass
    found = _find_from_id(data)
    if found:
        return found
    try:
        return f"bpy.types.{data.bl_rna.identifier}"
    except Exception:
        return "…"


def _find_from_id(data, depth=4):
    """Path of a nested struct Blender can't name itself (repr shortened with "...", path_from_id not
    supported – e.g. an object's animation_visualization.motion_path): searched from its ID through
    pointer properties, compared by pointer."""
    try:
        idd = data.id_data
        target = data.as_pointer()
        base = repr(idd).replace("'", '"')
    except Exception:
        return None
    if not base.startswith("bpy.") or "..." in base:
        return None
    seen = set()
    level = [(idd, base)]
    for _d in range(depth):
        nxt = []
        for obj, path in level:
            try:
                props = obj.bl_rna.properties
            except Exception:
                continue
            for p in props:
                if p.type != "POINTER" or p.identifier in ("rna_type", "id_data"):
                    continue
                try:
                    v = getattr(obj, p.identifier)
                except Exception:
                    continue
                if v is None or not hasattr(v, "as_pointer"):
                    continue
                try:
                    ptr = v.as_pointer()
                except Exception:
                    continue
                if ptr == target and type(v) is type(data):     # same memory can hold two RNA structs
                    return f"{path}.{p.identifier}"
                key = (ptr, type(v))
                if key in seen or isinstance(v, bpy_ID()):
                    continue
                seen.add(key)
                nxt.append((v, f"{path}.{p.identifier}"))
        level = nxt
    return None


def bpy_ID():
    import bpy
    return bpy.types.ID


def prop_text(data, prop, index=-1):
    t = f"{data_path(data)}.{prop}"
    if index is not None and index >= 0:
        t += f"[{index}]"
    return t


# ---------------------------------------------------------------- runnable code (since 0.127.0)
import ast as _ast
import io as _io
import re as _re
import tokenize as _tokenize

_IMPORTS = (("bpy", "import bpy"), ("qt_shell", "import qt_shell"),
            ("QtCore", "from PySide6 import QtCore"), ("QtWidgets", "from PySide6 import QtWidgets"),
            ("QtGui", "from PySide6 import QtGui"))
_PATH_RE = _re.compile(r"^((?:bpy|qt_shell\.api\.[a-z_0-9]+\(\))(?:\.[A-Za-z_]\w*|\[[^\]]+\])*?)"
                      r"\.([A-Za-z_]\w*)(\[\d+\])?$")
_ASSIGN_RE = _re.compile(r"^((?:bpy|qt_shell)\.[^=#]*?)\s*=\s*([^=#][^#]*?)(\s+#.*)?$")
_COMMENT_RE = _re.compile(r"^(\S[^#]*?)(\s+#.*)$")


def _split_statements(code):
    """'a; b  # c' → ['a', 'b  # c'] – only top-level semicolons (not inside strings)."""
    lines = []
    for line in code.split("\n"):
        try:
            toks = list(_tokenize.generate_tokens(_io.StringIO(line).readline))
        except Exception:
            lines.append(line)
            continue
        cuts = [t.start[1] for t in toks if t.type == _tokenize.OP and t.string == ";"]
        if not cuts:
            lines.append(line)
            continue
        start = 0
        for c in cuts:
            lines.append(line[start:c].strip())
            start = c + 1
        lines.append(line[start:].strip())
    return [x for x in lines if x.strip()]


def _defined_names(code):
    try:
        tree = _ast.parse(code)
    except SyntaxError:
        return set(), set()
    defined, used = set(), set()
    for n in _ast.walk(tree):
        if isinstance(n, _ast.Import):
            defined |= {a.asname or a.name.split(".")[0] for a in n.names}
        elif isinstance(n, _ast.ImportFrom):
            defined |= {a.asname or a.name for a in n.names}
        elif isinstance(n, _ast.Name):
            (defined if isinstance(n.ctx, _ast.Store) else used).add(n.id)
    return defined, used


def _resolve(path):
    """(owner struct, prop name, index, current value, RNA property) of a plain property path or None."""
    m = _PATH_RE.match(path.strip())
    if not m:
        return None
    try:
        import bpy
        import qt_shell
        owner = eval(m.group(1), {"bpy": bpy, "qt_shell": qt_shell})
        rp = owner.bl_rna.properties[m.group(2)]
        val = getattr(owner, m.group(2))
        idx = int(m.group(3)[1:-1]) if m.group(3) else None
        if idx is not None:
            val = val[idx]
        return owner, m.group(2), idx, val, rp
    except Exception:
        return None


_UNITS = {"DISTANCE": "metres", "DISTANCE_CAMERA": "metres", "ANGLE": "radians (degrees in the field)",
          "PERCENTAGE": "%", "FACTOR": "0–1", "PIXEL": "pixels", "TIME": "frames", "TIME_ABSOLUTE": "seconds",
          "COLOR": "linear RGB(A) 0–1", "COLOR_GAMMA": "RGB(A) 0–1", "TRANSLATION": "metres",
          "EULER": "radians", "QUATERNION": "quaternion W X Y Z", "XYZ": "X Y Z", "DIRECTION": "direction"}
_TYPES = {"FLOAT": "Float", "INT": "Integer", "BOOLEAN": "On / Off", "STRING": "Text", "ENUM": "Choice",
          "POINTER": "Data-block"}


def _value_text(v, rp=None):
    if rp is not None and rp.type == "POINTER":
        if v is None:
            return "None"
        try:
            coll = {"Object": "objects", "Material": "materials", "Image": "images", "Collection": "collections",
                    "World": "worlds", "Camera": "cameras", "NodeTree": "node_groups", "Texture": "textures",
                    "Mesh": "meshes", "Action": "actions", "Scene": "scenes"}.get(type(v).__mro__[1].__name__) \
                or {"Object": "objects"}.get(type(v).__name__)
            if hasattr(v, "name") and hasattr(v, "id_data") and v.id_data == v:
                return repr(v).replace("'", '"')
        except Exception:
            pass
        return repr(v).replace("'", '"')
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, set):
        return "{" + ", ".join(repr(x) for x in sorted(v)) + "}"
    try:
        if hasattr(v, "__len__"):
            return "(" + ", ".join(_value_text(x) for x in v) + ("," if len(v) == 1 else "") + ")"
    except Exception:
        pass
    return repr(v)


def _values_line(rp, idx, val):
    """'Float, metres · 0 … 10 · now 1.25' for the line under the code."""
    try:
        parts = [_TYPES.get(rp.type, rp.type.title())]
        sub = getattr(rp, "subtype", "NONE")
        if sub in _UNITS:
            parts[0] += ", " + _UNITS[sub]
        if rp.type in ("FLOAT", "INT"):
            lo, hi = rp.soft_min, rp.soft_max
            if abs(lo) < 1e9 and abs(hi) < 1e9:
                fmt = (lambda x: f"{x:g}") if rp.type == "FLOAT" else (lambda x: str(int(x)))
                parts.append(f"{fmt(lo)} … {fmt(hi)}")
        if rp.type == "FLOAT" and sub == "ANGLE" and isinstance(val, float):
            import math
            parts.append(f"now {val:.6g} ({math.degrees(val):.4g}°)")
        else:
            parts.append(f"now {_value_text(val, rp)}")
        return " · ".join(parts)
    except Exception:
        return ""


def _enum_comment(owner, prop, rp):
    if rp.type != "ENUM":
        return ""
    try:
        from . import rna_widgets
        items = [i[0] for i in rna_widgets.enum_items(owner, prop)]
    except Exception:
        items = [e.identifier for e in rp.enum_items]
    if not items:
        return ""
    shown = items[:8]
    return "   # " + ", ".join(repr(x) for x in shown) + (" …" if len(items) > 8 else "")


def _wrap_call(line, width=88):
    """A long call with several arguments → one argument per line (tooltips wrap long lines badly)."""
    if len(line) <= width:
        return line
    code, _sep, com = line.partition("   #")
    try:
        node = _ast.parse(code.strip()).body
        call = node[0].value if len(node) == 1 and isinstance(node[0], (_ast.Expr, _ast.Assign)) else None
        if not isinstance(call, _ast.Call) or len(call.args) + len(call.keywords) < 2:
            return line
        src = code.strip()
        head = src[:call.func.end_col_offset] if isinstance(node[0], _ast.Expr) else \
            src[:call.col_offset] + _ast.get_source_segment(src, call.func)
        parts = [_ast.get_source_segment(src, a) for a in call.args]
        parts += [(f"{k.arg}=" if k.arg else "**") + _ast.get_source_segment(src, k.value) for k in call.keywords]
        tail = src[call.end_col_offset:]
        out = head + "(\n" + ",\n".join("    " + x for x in parts) + ")" + tail
        _ast.parse(out)
        return out + (("   #" + com) if com else "")
    except Exception:
        return line


def _is_literal(text):
    """'3', "'SOLID'", '(1, 0, 0)', 'True' – an example value (replaced by the current one); not code."""
    try:
        _ast.literal_eval(text.strip())
        return True
    except Exception:
        return False


def runnable(code, keep_value=False):
    """(code, values) – the command as it runs by itself (Console, Text editor, a script): one statement per
    line, the imports it needs, a plain property path shown as an assignment of its current value, Blender's
    hidden menus / popovers opened as Qt Shell's. values: a short line about the property (type, range, now).
    keep_value: "path = value" keeps its value (a button / menu item that sets exactly that value); otherwise
    (a field) the example value is replaced by the current one."""
    code = (code or "").strip()
    values = ""
    if not code:
        return code, values
    # Blender's own menus / popovers live in the hidden window – open Qt Shell's instead
    code = _re.sub(r"bpy\.ops\.wm\.call_(menu|menu_pie|panel)\((name=[^)]*)\)",
                   lambda m: f'qt_shell.api.run_op("wm.call_{m.group(1)}", {m.group(2)})', code)
    lines = _split_statements(code)
    if len(lines) == 1:
        line, com = lines[0], ""
        mc = _COMMENT_RE.match(line)
        if mc and _resolve(mc.group(1)) is not None:      # "path   # a note"
            line, com = mc.group(1), mc.group(2)
        r = _resolve(line)
        if r is not None:                    # a property path: an assignment of its current value
            owner, prop, idx, val, rp = r
            if not rp.is_readonly and rp.type != "COLLECTION":
                lines = [f"{line} = {_value_text(val, rp)}" + (com or _enum_comment(owner, prop, rp))]
            values = _values_line(rp, idx, val)
        else:
            m = _ASSIGN_RE.match(lines[0])
            r = _resolve(m.group(1)) if m and _is_literal(m.group(2)) else None
            if r is not None and keep_value:
                values = _values_line(r[4], r[2], r[3])
                r = None
            if r is not None and r[4].type in ("POINTER", "COLLECTION"):
                r = None                     # "id = None", "x = y.copy()" – keep what the button does
            if r is not None:                # "path = example": the current value instead of the example
                owner, prop, idx, val, rp = r
                com = (m.group(3) or "").strip() or _enum_comment(owner, prop, rp).strip()
                lines = [f"{m.group(1)} = {_value_text(val, rp)}" + (f"   {com}" if com else "")]
                values = _values_line(rp, idx, val)
    lines = [_wrap_call(l) for l in lines]
    body = "\n".join(lines)
    defined, used = _defined_names(body)
    if not used and "bpy." in body:        # not parseable (a comment-only line …) – still add the import
        used = {"bpy"}
    heads = [imp for name, imp in _IMPORTS if name in used and name not in defined
             and imp not in body]
    return "\n".join(heads + lines), values


# ---------------------------------------------------------------- tagging
def tag(obj, text):
    """Store the Python command on a widget or QAction (no-op for None)."""
    if obj is None or not text:
        return obj
    try:
        obj.setProperty(PROP, text)
    except RuntimeError:
        pass
    return obj


def tag_op(obj, idname, props=None):
    return tag(obj, op_text(idname, props))


def tag_prop(obj, data, prop, index=-1):
    try:
        return tag(obj, prop_text(data, prop, index))
    except Exception:
        return obj


def _get(obj):
    try:
        v = obj.property(PROP)
    except RuntimeError:
        return None
    return v if isinstance(v, str) and v else None


def _hook_at(obj, pos):
    """(tooltip, command) from a widget that provides commands per position – e.g. the Outliner tree,
    whose rows and cells are not widgets. The widget (or one of its parents) defines
    qtshell_python_at(widget, pos) → (tooltip, command) or None; pos is in `widget` coordinates."""
    w, depth = obj, 0
    while w is not None and depth < 4:
        fn = getattr(w, "qtshell_python_at", None)
        if callable(fn):
            try:
                r = fn(obj, pos)
            except Exception:
                return None
            return r if r and r[1] else None
        if w.isWindow():
            return None
        w, depth = w.parentWidget(), depth + 1
    return None


# ---------------------------------------------------------------- tooltip filter
def _rich(text):
    try:
        return bool(QtGui.Qt.mightBeRichText(text))
    except Exception:
        return text.lstrip().startswith("<")


_MONO = "font-family:Consolas,'DejaVu Sans Mono',monospace"


def _code_html(code):
    out = []
    for line in code.split("\n"):
        cut = _comment_at(line)
        main, com = (line[:cut], line[cut:]) if cut is not None else (line, "")
        out.append(html.escape(main).replace(" ", "&nbsp;")
                   + (f"<span style='color:#8a8a8a'>{html.escape(com)}</span>" if com else ""))
    return "<br>".join(out)


def _comment_at(line):
    try:
        for t in _tokenize.generate_tokens(_io.StringIO(line).readline):
            if t.type == _tokenize.COMMENT:
                return t.start[1]
    except Exception:
        i = line.find("  #")
        return i if i >= 0 else None
    return None


def _split_tip(tip):
    """(title, description html) from a widget tooltip: the first line / bold part is the title."""
    tip = (tip or "").strip()
    if not tip:
        return "", ""
    if _rich(tip):
        m = _re.match(r"^\s*<b>(.*?)</b>\s*(?:<br\s*/?>)?(.*)$", tip, _re.S | _re.I)
        if m:
            return _re.sub("<[^>]+>", "", m.group(1)), m.group(2).strip()
        return "", tip
    first, _sep, rest = tip.partition("\n")
    if len(first) > 70 and not rest:
        return "", html.escape(first)
    return first, html.escape(rest.strip()).replace("\n", "<br>")


def _compose(tip, py, title=None, keep_value=False):
    code, values = runnable(py, keep_value)
    t, desc = _split_tip(tip)
    title = title or t
    parts = ["<div style='white-space:pre-wrap'>"]
    if title:
        parts.append(f"<b style='font-size:13px'>{html.escape(title)}</b>")
    if desc:
        parts.append(("<br>" if title else "") + desc)
    parts.append("<table cellspacing=0 cellpadding=6 width='100%' style='margin-top:6px;background:#1e1e1e;"
                 "border:1px solid #3a3a3a'><tr><td>"
                 "<span style='color:#7fd1a8;font-weight:bold'>Python</span><br>"
                 f"<span style=\"{_MONO}\">{_code_html(code)}</span></td></tr></table>")
    if values:
        parts.append(f"<span style='color:#b9b9b9'>{html.escape(values)}</span><br>")
    parts.append("<span style='font-size:small;color:#8a8a8a'><i>Shift + middle click: copy the code</i>"
                 "</span></div>")
    return "".join(parts)


def _menu_command(menu, act):
    """The command of a menu item: its own tag, else (an item of the menu bar built by Qt Shell)
    qt_shell.api.run_menu(<path>) – it does what the click does."""
    if act is None or act.isSeparator() or act.menu() is not None:
        return None
    py = _get(act)
    if py:
        return py
    try:
        from . import api
        path = api.menu_path(menu, act)
    except Exception:
        path = None
    if not path or not path[-1] or path[-1] in ("—", "-"):    # placeholder of an empty menu
        return None
    return "qt_shell.api.run_menu(" + ", ".join(repr(p) for p in path) + ")"


def handle(obj, ev):
    """Called by app._notify_with_context for QEvent.ToolTip when the option is on.
    Returns True when it showed the tooltip (the event is then consumed).

    No application-wide event filter on purpose: a Python eventFilter on the QApplication sees every
    event, and stale PySide wrappers of events once made notify() receive a QMoveEvent as the receiver
    (2026-10-20). The existing notify() override already runs for every event anyway."""
    try:
        if isinstance(obj, QtWidgets.QMenu):
            act = obj.actionAt(ev.pos())
            py = _menu_command(obj, act)
            if py is None:
                return False
            tip = act.toolTip()
            title = act.text().replace("&&", "\0").replace("&", "").replace("\0", "&").split("\t")[0].strip()
            if tip.replace("&", "") == title or tip == act.text():
                tip = ""                       # Qt's default tooltip of an action is its text
            if tip and _split_tip(tip)[0] == "":
                tip = title + "\n" + tip
            QtWidgets.QToolTip.showText(ev.globalPos(), _compose(tip or title, py, keep_value=True), obj,
                                        obj.actionGeometry(act))
            return True
        if not isinstance(obj, QtWidgets.QWidget):
            return False
        hooked = _hook_at(obj, ev.pos())
        if hooked is not None:
            QtWidgets.QToolTip.showText(ev.globalPos(), _compose(hooked[0], hooked[1]), obj)
            return True
        # the command may sit on the widget or on a parent (e.g. a field inside a vector row)
        w, py, depth = obj, None, 0
        while w is not None and depth < 4:
            py = _get(w)
            if py or w.isWindow():
                break
            w, depth = w.parentWidget(), depth + 1
        if not py:
            return False
        tip = obj.toolTip() or (w.toolTip() if w is not None else "")
        QtWidgets.QToolTip.showText(ev.globalPos(), _compose(tip, py, keep_value=_is_button(w)), obj)
        return True
    except Exception as ex:                    # never keep the event alive in a traceback
        msg = f"{type(ex).__name__}: {ex}"
    from . import bridge
    bridge.log("Python tooltip: " + msg, "WARNING")
    return False


def _is_button(w):
    """A button sets the value written in its command; a field (spin box, combo, slider …) shows the current one.
    Check boxes are fields: they show what they are now."""
    return isinstance(w, QtWidgets.QAbstractButton) and not isinstance(w, QtWidgets.QCheckBox)


def _command_at(obj, pos):
    """Python command of the widget / menu item at pos (widget coordinates), or None."""
    if isinstance(obj, QtWidgets.QMenu):
        return _menu_command(obj, obj.actionAt(pos))
    if not isinstance(obj, QtWidgets.QWidget):
        return None
    hooked = _hook_at(obj, pos)
    if hooked is not None:
        return hooked[1]
    w, depth = obj, 0
    while w is not None and depth < 4:
        py = _get(w)
        if py:
            return py
        if w.isWindow():
            return None
        w, depth = w.parentWidget(), depth + 1
    return None


def copy_on_click(obj, ev):
    """Shift + middle click copies the command (called by app._notify_with_context).
    Returns True when something was copied (the click is then consumed)."""
    try:
        py = _command_at(obj, ev.position().toPoint())
        if not py:
            return False
        w = obj.childAt(ev.position().toPoint()) if isinstance(obj, QtWidgets.QWidget) else None
        py = runnable(py, keep_value=isinstance(obj, QtWidgets.QMenu) or _is_button(w or obj))[0]
        QtWidgets.QApplication.clipboard().setText(py)
        short = py if len(py) < 90 else py[:87] + "…"
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), "Copied to the clipboard:\n" + short)
        try:
            from . import api
            api.status("Copied: " + short.replace("\n", "  "))
        except Exception:
            pass
        return True
    except Exception as ex:
        msg = f"{type(ex).__name__}: {ex}"
    from . import bridge
    bridge.log("Copy Python command: " + msg, "WARNING")
    return False


def install(app=None):
    """Removes the application event filter of the first version (tooltips now go through app.notify)."""
    app = app or QtWidgets.QApplication.instance()
    if app is None:
        return
    old = getattr(app, "_qtshell_pytips_filter", None)
    if old is not None:
        try:
            app.removeEventFilter(old)
        except RuntimeError:
            pass
        app._qtshell_pytips_filter = None

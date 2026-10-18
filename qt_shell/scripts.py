"""Script manager: runs scripts and keeps track of what they register, so they can be unloaded and
reloaded cleanly (inspired by Maya's Plug-in Manager, built on Blender's register()/unregister()).

A script is identified by a key:
    "text:<name>"  – a text in bpy.data.texts that has no file (saved in the .blend)
    "file:<path>"  – a .py file on disk (also a text opened from that file – its current content is run)

Running a script:
- runs it with ``__name__ == "__main__"`` (like Blender's Run Script), output goes to the Console,
- records everything it registers: Qt Shell API docks / menu items / overlays / events,
  bpy classes (bpy.utils.register_class) and bpy.app.handlers,
- running a loaded script again unloads it first (no duplicates).

Unloading calls the script's own ``unregister()`` if it has one and then removes whatever is left.

Auto-load: texts flagged in the .blend run when the file is opened (only if Blender is allowed to
auto-run Python scripts – Preferences ▸ Save & Load ▸ Auto Run Python Scripts); files in the
script list flagged auto-load run when Qt Shell starts.

This module does not import PySide6.
"""
import contextlib
import io
import json
import linecache
import os
import time
import traceback

import bpy

from . import api

TEXT_PROP = "qtshell_autoload"      # custom property on bpy.types.Text


# ---------------------------------------------------------------- state
def _state():
    st = api.state_store("scripts")
    st.setdefault("loaded", {})       # key → info dict
    st.setdefault("version", 0)
    st.setdefault("files_done", False)
    st.setdefault("blend_done", None)
    st.setdefault("blocked", [])
    return st


def version():
    """Changes whenever the state of a script changes (for UIs that refresh)."""
    return _state()["version"]


def _changed(key, status):
    st = _state()
    st["version"] += 1
    api.emit("script", key, status)


# ---------------------------------------------------------------- keys
def _norm(path):
    return os.path.normcase(os.path.abspath(bpy.path.abspath(path)))


def key_for_text(t):
    return f"file:{_norm(t.filepath)}" if t.filepath else f"text:{t.name}"


def text_for_key(key):
    kind, _, ident = key.partition(":")
    if kind == "text":
        t = bpy.data.texts.get(ident)
        return t if t is not None and not t.filepath else None
    for t in bpy.data.texts:
        if t.filepath and _norm(t.filepath) == ident:
            return t
    return None


def label(key):
    kind, _, ident = key.partition(":")
    if kind == "file":
        t = text_for_key(key)
        return t.name if t is not None else os.path.basename(ident)
    return ident


def location(key):
    kind, _, ident = key.partition(":")
    return ident if kind == "file" else "in the .blend"


def _source(key):
    """(source code, filename for tracebacks)."""
    t = text_for_key(key)
    kind, _, ident = key.partition(":")
    if t is not None:
        return t.as_string(), (ident if kind == "file" else t.name)
    if kind == "file":
        with open(ident, encoding="utf-8") as f:
            return f.read(), ident
    raise LookupError(f"script {label(key)!r} not found")


# ---------------------------------------------------------------- list / config
def _config_path():
    d = bpy.utils.user_resource("CONFIG", path="qt_shell", create=True)
    return os.path.join(d, "scripts.json")


def _load_config():
    try:
        with open(_config_path(), encoding="utf-8") as f:
            cfg = json.load(f)
        if isinstance(cfg, dict) and isinstance(cfg.get("files"), list):
            return cfg
    except Exception:
        pass
    return {"files": []}


def _save_config(cfg):
    try:
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        api._log(f"Scripts: cannot save {_config_path()}:\n{traceback.format_exc()}")


def managed_files():
    """[(key, autoload)] of the files in the script list."""
    return [(f"file:{_norm(e['path'])}", bool(e.get("autoload"))) for e in _load_config()["files"]
            if isinstance(e, dict) and e.get("path")]


def add_file(path):
    key = f"file:{_norm(path)}"
    cfg = _load_config()
    if not any(f"file:{_norm(e.get('path', ''))}" == key for e in cfg["files"]):
        cfg["files"].append({"path": os.path.abspath(path), "autoload": False})
        _save_config(cfg)
        _changed(key, "added")
    return key


def remove_file(key):
    cfg = _load_config()
    cfg["files"] = [e for e in cfg["files"] if f"file:{_norm(e.get('path', ''))}" != key]
    _save_config(cfg)
    _changed(key, "removed")


def is_managed(key):
    return any(k == key for k, _ in managed_files())


def all_keys():
    """Texts of the .blend, files in the script list and loaded scripts – in this order."""
    keys = []
    for t in bpy.data.texts:
        k = key_for_text(t)
        if k not in keys:
            keys.append(k)
    for k, _ in managed_files():
        if k not in keys:
            keys.append(k)
    for k in _state()["loaded"]:
        if k not in keys:
            keys.append(k)
    return keys


def autoload(key):
    if key.startswith("file:"):
        return any(k == key and a for k, a in managed_files())
    t = text_for_key(key)
    return bool(t is not None and t.get(TEXT_PROP))


def set_autoload(key, on):
    if key.startswith("file:"):
        cfg = _load_config()
        found = False
        for e in cfg["files"]:
            if f"file:{_norm(e.get('path', ''))}" == key:
                e["autoload"] = bool(on)
                found = True
        if not found and on:
            cfg["files"].append({"path": key[5:], "autoload": True})
        _save_config(cfg)
    else:
        t = text_for_key(key)
        if t is None:
            return
        if on:
            t[TEXT_PROP] = True
        elif TEXT_PROP in t:
            del t[TEXT_PROP]
    _changed(key, "autoload")


# ---------------------------------------------------------------- info
def info(key):
    """None or dict: status ('loaded' | 'ran' | 'error'), items, error_line, time."""
    i = _state()["loaded"].get(key)
    if i is None:
        return None
    return {"status": i["status"], "items": len(_items(key, i)), "error_line": i.get("error_line"),
            "time": i.get("time"), "has_unregister": callable(i["ns"].get("unregister"))}


def is_loaded(key):
    return key in _state()["loaded"]


def _items(key, i):
    """What the script has registered and is still registered."""
    items = [f"{kind} {ident}" for kind, ident in api.owned(key)]
    for name, fn in i["handlers"]:
        if fn in getattr(bpy.app.handlers, name, ()):
            items.append(f"handler {name}: {getattr(fn, '__name__', fn)}")
    for cls in i["classes"]:
        if getattr(cls, "is_registered", False):
            items.append(f"class {cls.__name__}")
    return items


def items(key):
    i = _state()["loaded"].get(key)
    return _items(key, i) if i is not None else []


# ---------------------------------------------------------------- running
def _snapshot():
    handlers = {}
    for name in dir(bpy.app.handlers):
        lst = getattr(bpy.app.handlers, name, None)
        if isinstance(lst, list):
            handlers[name] = list(lst)
    return handlers, set(dir(bpy.types))


def _record(i, before):
    h_before, t_before = before
    h_after, t_after = _snapshot()
    for name, lst in h_after.items():
        old = h_before.get(name, [])
        for fn in lst:
            if not any(fn is o for o in old) and (name, fn) not in i["handlers"]:
                i["handlers"].append((name, fn))
    for name in sorted(t_after - t_before):
        cls = getattr(bpy.types, name, None)
        if cls is not None and cls not in i["classes"]:
            i["classes"].append(cls)


class Result:
    def __init__(self, ok, output, error_line=None, removed=0):
        self.ok = ok
        self.output = output
        self.error_line = error_line
        self.removed = removed


def _format_error(ex, filename):
    out = io.StringIO()
    tb = ex.__traceback__
    while tb is not None and tb.tb_frame.f_code.co_filename != filename:   # skip Qt Shell's frames
        tb = tb.tb_next
    if isinstance(ex, SyntaxError) or tb is None:
        out.write("".join(traceback.format_exception_only(type(ex), ex)))
    else:
        out.write("Traceback (most recent call last):\n")
        out.write("".join(traceback.format_list(traceback.extract_tb(tb))))
        out.write("".join(traceback.format_exception_only(type(ex), ex)))
    line = None
    if isinstance(ex, SyntaxError) and ex.filename == filename:
        line = ex.lineno
    else:
        for fr in traceback.extract_tb(ex.__traceback__):
            if fr.filename == filename:
                line = fr.lineno
    return out.getvalue(), line


@contextlib.contextmanager
def _blender_context():
    try:
        from . import bridge
        cm = bridge.blender_context()
        cm.__enter__()
    except Exception:
        cm = None
    try:
        yield
    finally:
        if cm is not None:
            cm.__exit__(None, None, None)


def _execute(key, src, filename, ns, i, line_offset=0, interactive=False):
    """Runs src in ns, recording registrations into i. Returns (ok, output, error_line)."""
    out = io.StringIO()
    before = _snapshot()
    error_line = None
    ok = True
    try:
        if line_offset:
            src = "\n" * line_offset + src
        if not interactive:      # source lines in tracebacks also for texts without a file
            linecache.cache[filename] = (len(src), None, src.splitlines(True), filename)
        code = None
        if interactive:
            try:
                code = compile(src, filename, "eval")
            except SyntaxError:
                code = None
        is_expr = code is not None
        if code is None:
            code = compile(src, filename, "exec")
        with api.owner(key), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            with _blender_context():
                value = eval(code, ns) if is_expr else exec(code, ns)
            if is_expr and value is not None:
                print(repr(value))
    except Exception as ex:
        ok = False
        text, error_line = _format_error(ex, filename)
        out.write(text)
    finally:
        try:
            _record(i, before)
        except Exception:
            out.write(traceback.format_exc())
    return ok, out.getvalue(), error_line


def run(key):
    """Runs a script (unloading it first if it is loaded)."""
    removed = 0
    pre = ""
    if is_loaded(key):
        r = unload(key, _notify=False)
        removed, pre = r.removed, r.output
    try:
        src, filename = _source(key)
    except Exception as ex:
        return Result(False, pre + f"{ex}\n")
    ns = {"__name__": "__main__", "__file__": filename, "bpy": bpy}
    i = {"ns": ns, "handlers": [], "classes": [], "status": "ran", "time": time.time(),
         "filename": filename}
    _state()["loaded"][key] = i
    ok, output, error_line = _execute(key, src, filename, ns, i)
    i["error_line"] = error_line
    i["status"] = ("loaded" if _items(key, i) or callable(ns.get("unregister")) else "ran") if ok else "error"
    _changed(key, i["status"])
    return Result(ok, pre + output, error_line, removed)


def run_snippet(key, src, first_line=1):
    """Runs a piece of a script (selection / current line) in the script's namespace, like Maya's
    Execute Selected. A single expression prints its value. Registrations belong to the script."""
    st = _state()
    i = st["loaded"].get(key)
    if i is None:
        try:
            _, filename = _source(key)
        except Exception:
            filename = label(key)
        i = {"ns": {"__name__": "__main__", "__file__": filename, "bpy": bpy}, "handlers": [],
             "classes": [], "status": "ran", "time": time.time(), "filename": filename}
        st["loaded"][key] = i
    ok, output, error_line = _execute(key, src, i["filename"], i["ns"], i,
                                      line_offset=max(first_line - 1, 0), interactive=True)
    if i["status"] != "error":
        i["status"] = "loaded" if _items(key, i) or callable(i["ns"].get("unregister")) else "ran"
    _changed(key, i["status"])
    return Result(ok, output, error_line)


def unload(key, _notify=True):
    """Calls the script's unregister() and removes everything it left registered."""
    i = _state()["loaded"].pop(key, None)
    if i is None:
        return Result(True, "")
    out = io.StringIO()
    ok = True
    fn = i["ns"].get("unregister")
    if callable(fn):
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                with _blender_context():
                    fn()
        except Exception as ex:
            ok = False
            out.write("unregister() failed:\n" + _format_error(ex, i["filename"])[0])
    removed = api.cleanup(key)
    for name, h in i["handlers"]:
        lst = getattr(bpy.app.handlers, name, None)
        if lst is not None and h in lst:
            lst.remove(h)
            removed += 1
    for cls in reversed(i["classes"]):
        if getattr(cls, "is_registered", False):
            try:
                bpy.utils.unregister_class(cls)
                removed += 1
            except Exception as ex:
                out.write(f"Cannot unregister {cls.__name__}: {ex}\n")
    if _notify:
        _changed(key, "unloaded")
    return Result(ok, out.getvalue(), removed=removed)


def unload_all():
    for key in list(_state()["loaded"]):
        unload(key)


# ---------------------------------------------------------------- console output
def report(text, color=None):
    """Writes into the Console dock (and shows it)."""
    w = api.main_window()
    console = getattr(w, "console", None) if w is not None else None
    if console is None:
        print(text, end="")
        return
    try:
        console.write(text, color)
    except Exception:
        print(text, end="")


def show_console():
    w = api.main_window()
    if w is not None and "console" in getattr(w, "docks", {}):
        w.docks["console"].show()
        w.docks["console"].raise_()


def report_result(title, r):
    report(f"\n{title}\n", "#8fb3ff")
    if r.output:
        report(r.output if r.output.endswith("\n") else r.output + "\n", "#e5e5e5" if r.ok else "#ff7070")


# ---------------------------------------------------------------- auto-load
def _autorun_allowed():
    try:
        return bool(bpy.context.preferences.filepaths.use_scripts_auto_execute)
    except Exception:
        return False


def _autoload_texts():
    st = _state()
    if st["blend_done"] == bpy.data.filepath:
        return
    st["blend_done"] = bpy.data.filepath
    st["blocked"] = []
    for t in list(bpy.data.texts):
        if not t.get(TEXT_PROP):
            continue
        key = key_for_text(t)
        if is_loaded(key):
            continue
        if not _autorun_allowed():
            st["blocked"].append(key)
            continue
        report_result(f"▶ Auto-load: {t.name}", run(key))
    if st["blocked"]:
        report(f"\nAuto-load of {len(st['blocked'])} script(s) in this file was blocked – "
               "enable Preferences ▸ Save & Load ▸ Auto Run Python Scripts, or run them from the "
               "Scripts dock.\n", "#e0b050")
        _changed("", "blocked")


def startup():
    """Called when the Qt window has been built."""
    st = _state()
    if not st["files_done"]:
        st["files_done"] = True
        for key, auto in managed_files():
            if auto and not is_loaded(key):
                report_result(f"▶ Auto-load: {label(key)}", run(key))
    _autoload_texts()


def on_file_loaded():
    """Another .blend was opened: unload the scripts of the old file's texts, auto-load the new ones."""
    st = _state()
    for key in [k for k in st["loaded"] if k.startswith("text:")]:
        r = unload(key)
        if r.output or r.removed:
            report_result(f"■ Unloaded {label(key)} (file closed)", r)
    st["blend_done"] = None
    _autoload_texts()


def blocked():
    return list(_state()["blocked"])

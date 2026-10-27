"""Bridge between Qt and Blender with no dependency on Qt.

- context for operators (window/area/region of a 3D view, even when the Blender window is hidden)
- running operators (EXEC), deferring file loading outside the Qt call stack
- persistent handlers that set flags; the Qt side reads them in the pump
"""
import os
import traceback
from contextlib import contextmanager

import bpy

# ---------------------------------------------------------------- state shared with Qt
class Flags:
    depsgraph = False
    file_loaded = False
    undo = False
    render_done = False
    render_stats = ""
    edit_version = 0      # +1 on every scene edit / undo / load (not on frame changes) – playback cache


_log_listeners = []
# hooks set by the Qt layer
file_dialog_hook = None      # fn(idname, rna_props, props) -> bool
special_op_hook = None       # fn(idname, props, ctx) -> bool (True = handled in Qt)
after_op_hook = None         # fn(idname, props, result)


def add_log_listener(fn):
    _log_listeners.append(fn)


def remove_log_listener(fn):
    if fn in _log_listeners:
        _log_listeners.remove(fn)


def log_path():
    import tempfile
    return os.path.join(tempfile.gettempdir(), "qtshell.log")


def _log_to_file(msg, level):
    """Warnings and errors also go to <temp>/qtshell.log – Blender's console is hidden on Windows."""
    try:
        import time
        path = log_path()
        if os.path.exists(path) and os.path.getsize(path) > 512 * 1024:
            os.replace(path, path + ".old")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {level}: {msg}\n")
    except Exception:
        pass


def log(msg, level="INFO"):
    print(f"[QtShell] {level}: {msg}")
    if level in ("WARNING", "ERROR"):
        _log_to_file(msg, level)
    for fn in list(_log_listeners):
        try:
            fn(str(msg), level)
        except Exception:
            pass


def tr(text):
    """Translates UI text the same way Blender does (respects the language in Preferences)."""
    if not text:
        return text
    try:
        return bpy.app.translations.pgettext_iface(text)
    except Exception:
        return text


# ---------------------------------------------------------------- context
def find_view3d():
    wm = bpy.context.window_manager
    if wm is None:
        return None
    for win in wm.windows:
        screen = win.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        return win, area, region
    return None


def ensure_view3d():
    found = find_view3d()
    if found:
        return found
    wm = bpy.context.window_manager
    if wm is None or not wm.windows:
        return None
    win = wm.windows[0]
    if not win.screen.areas:
        return None
    area = max(win.screen.areas, key=lambda a: a.width * a.height)
    area.type = "VIEW_3D"
    return find_view3d()


@contextmanager
def blender_context(**extra):
    """temp_override onto a 3D view – bpy.context and bpy.ops then behave as in the editor."""
    found = ensure_view3d()
    kw = {}
    if found:
        win, area, region = found
        kw = dict(window=win, screen=win.screen, area=area, region=region)
    kw.update({k: v for k, v in extra.items() if v is not None})
    with bpy.context.temp_override(**kw):
        yield


def later(fn, delay=0.0):
    """Runs fn in a separate Blender timer – outside the Qt call stack."""
    def _run():
        try:
            fn()
        except Exception:
            log(traceback.format_exc(), "ERROR")
        return None
    bpy.app.timers.register(_run, first_interval=delay, persistent=True)


# ---------------------------------------------------------------- operators
# operators that replace the whole file (and with it windows/areas) → must not run inside the Qt pump temp_override
DEFER_OPS = {
    "wm.open_mainfile", "wm.read_homefile", "wm.read_factory_settings", "wm.revert_mainfile",
    "wm.recover_last_session", "wm.recover_auto_save", "wm.read_userpref",
}
# operators with 'filepath' that don't open a file dialog
NO_FILE_DIALOG = {"wm.read_homefile", "wm.read_factory_settings", "wm.revert_mainfile",
                  "wm.recover_last_session", "wm.url_open", "wm.path_open", "render.render",
                  "wm.save_homefile", "wm.read_userpref", "wm.save_userpref"}


def get_op(idname):
    mod, name = idname.split(".", 1)
    op = getattr(getattr(bpy.ops, mod), name)
    op.get_rna_type()  # KeyError if it doesn't exist
    return op


def op_exists(idname):
    try:
        get_op(idname)
        return True
    except Exception:
        return False


def op_rna_props(idname):
    try:
        return {p.identifier: p for p in get_op(idname).get_rna_type().properties
                if p.identifier != "rna_type"}
    except Exception:
        return {}


def op_label(idname):
    try:
        return tr(get_op(idname).get_rna_type().name) or idname
    except Exception:
        return idname


def op_poll(idname, ctx=None):
    try:
        op = get_op(idname)
        if ctx:
            with bpy.context.temp_override(**ctx):
                return op.poll()
        return op.poll()
    except Exception:
        return True


def run_op(idname, props=None, ctx=None, invoke=False):
    """Runs a Blender operator from Qt. Returns the result set (or {'CANCELLED'})."""
    props = dict(props or {})
    if "_OT_" in idname:   # C-style id from some menus ("WM_OT_search_single_menu" → "wm.search_single_menu")
        mod, name = idname.split("_OT_", 1)
        idname = f"{mod.lower()}.{name}"
    if special_op_hook is not None:
        try:
            try:
                handled = special_op_hook(idname, props, ctx)
            except TypeError:
                handled = special_op_hook(idname, props)
            if handled:
                return {"FINISHED"}
        except Exception:
            log(traceback.format_exc(), "ERROR")
    try:
        op = get_op(idname)
    except Exception:
        log(f"Operator '{idname}' does not exist.", "WARNING")
        return {"CANCELLED"}

    rna_props = op_rna_props(idname)
    wants_file = ("filepath" in rna_props or "directory" in rna_props) and idname not in NO_FILE_DIALOG
    if wants_file and not props.get("filepath") and not props.get("directory"):
        if idname == "wm.save_mainfile" and bpy.data.filepath:
            pass
        elif file_dialog_hook is not None:
            if not file_dialog_hook(idname, rna_props, props):
                return {"CANCELLED"}

    def _exec():
        mode = "INVOKE_DEFAULT" if invoke else "EXEC_DEFAULT"
        try:
            with blender_context(**(ctx or {})):
                res = op(mode, **props)
        except Exception as ex:
            log(f"{idname}: {ex}".strip(), "ERROR")
            res = {"CANCELLED"}
        # Operators called from Python don't push an undo step themselves → push it for them.
        if "FINISHED" in res and not idname.startswith("ed."):
            try:
                if "UNDO" in (op.bl_options or set()):
                    undo_push(op_label(idname))
            except Exception:
                pass
            try:
                from . import repeat                 # Repeat Last (Maya G / Blender Shift+R)
                repeat.record_op(idname, props, invoke)
            except Exception:
                pass
        if after_op_hook is not None:
            try:
                after_op_hook(idname, props, res)
            except Exception:
                log(traceback.format_exc(), "ERROR")
        return res

    if idname in DEFER_OPS:
        later(_exec)
        return {"RUNNING_MODAL"}
    return _exec()


_undo_pending = None


def undo_push(message="Qt Shell"):
    try:
        with blender_context():
            bpy.ops.ed.undo_push(message=message)
    except Exception as ex:
        log(f"undo_push: {ex}", "WARNING")


# ---------------------------------------------------------------- handlers
_quiet = 0      # > 0 while Qt Shell changes scene settings only for a moment (not an edit)


@contextmanager
def quiet_updates():
    """with bridge.quiet_updates(): … – depsgraph updates inside are not reported as scene edits
    (e.g. the viewport's temporary EEVEE sample count while navigating)."""
    global _quiet
    _quiet += 1
    try:
        yield
    finally:
        _quiet -= 1


@bpy.app.handlers.persistent
def _on_depsgraph(*_args):
    Flags.depsgraph = True


@bpy.app.handlers.persistent
def _on_depsgraph_edit(*_args):
    # depsgraph_update_post runs for edits, not for frame changes (those run frame_change_post)
    if _quiet:
        return
    Flags.depsgraph = True
    Flags.edit_version += 1


@bpy.app.handlers.persistent
def _on_load(*_args):
    Flags.file_loaded = True
    Flags.depsgraph = True
    Flags.edit_version += 1
    add_recent(bpy.data.filepath)


@bpy.app.handlers.persistent
def _on_save(*_args):
    add_recent(bpy.data.filepath)


@bpy.app.handlers.persistent
def _on_undo(*_args):
    Flags.undo = True
    Flags.depsgraph = True
    Flags.edit_version += 1


@bpy.app.handlers.persistent
def _on_render_done(*_args):
    Flags.render_done = True


@bpy.app.handlers.persistent
def _on_render_stats(*args):
    for a in args:
        if isinstance(a, str):
            Flags.render_stats = a


_HANDLERS = (
    ("depsgraph_update_post", _on_depsgraph_edit),
    ("frame_change_post", _on_depsgraph),
    ("load_post", _on_load),
    ("save_post", _on_save),
    ("undo_post", _on_undo),
    ("redo_post", _on_undo),
    # Render handlers (render_stats/complete/cancel) are called from the render thread;
    # render_stats with an empty string crashes Blender 5.x → the end of a render is detected
    # by polling bpy.app.is_job_running("RENDER") in the pump.
)
_OLD_HANDLERS = (("render_complete", "_on_render_done"), ("render_cancel", "_on_render_done"),
                 ("render_stats", "_on_render_stats"))


_gpu_hold_until = 0.0


def hold_gpu(seconds=0.25):
    """A Blender window was closed: Blender has no active GPU context until a window is made drawable
    again (native.repaint_blender_windows → GHOST WindowUpdate) – offscreen drawing (draw_view3d) would
    crash. is_rendering() is True meanwhile, which pauses the viewport like a render does."""
    global _gpu_hold_until
    import time
    _gpu_hold_until = time.monotonic() + seconds


def restore_gpu_context():
    """After a Blender window was closed no GPU context is active. wm_draw_update() makes a window drawable
    again when none is (it skips minimized windows, but has this fallback) – run it now through
    wm.redraw_timer (DRAW_WIN_SWAP = one wm_draw_update) instead of waiting for Blender's next loop."""
    try:
        wm = bpy.context.window_manager
        win = wm.windows[0]
        import contextlib, io
        with bpy.context.temp_override(window=win, screen=win.screen), \
                contextlib.redirect_stdout(io.StringIO()):          # its timing report is not for the user
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
        return True
    except Exception as ex:
        log(f"GPU context restore failed ({ex})", "WARNING")
        return False


def gpu_held():
    import time
    return time.monotonic() < _gpu_hold_until


def is_rendering():
    if gpu_held():
        return True
    try:
        return bpy.app.is_job_running("RENDER")
    except Exception:
        return False


def register_handlers():
    # remove handlers left over from an older version of the add-on
    for name, fname in _OLD_HANDLERS:
        lst = getattr(bpy.app.handlers, name, None)
        if lst is not None:
            for fn in list(lst):
                if getattr(fn, "__name__", "") == fname and "qt_shell" in getattr(fn, "__module__", ""):
                    lst.remove(fn)
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name, None)
        if lst is not None and fn not in lst:
            lst.append(fn)


def unregister_handlers():
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name, None)
        if lst is not None and fn in lst:
            lst.remove(fn)


# ---------------------------------------------------------------- misc
def user_modules_dir():
    return bpy.utils.user_resource("SCRIPTS", path="modules", create=True)


def recent_files():
    """Blender's own recent-files list (CONFIG/recent-files.txt)."""
    try:
        path = os.path.join(bpy.utils.user_resource("CONFIG"), "recent-files.txt")
        with open(path, encoding="utf-8") as fh:
            return [ln.strip() for ln in fh if ln.strip()]
    except Exception:
        return []


# Qt Shell keeps its own history too (CONFIG/qt_shell_recent.txt, newest first), so files opened or
# saved from Qt are listed even when Blender doesn't add them to recent-files.txt.
RECENT_MAX = 30


def _recent_store():
    return os.path.join(bpy.utils.user_resource("CONFIG", create=True), "qt_shell_recent.txt")


def _read_lines(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return [ln.strip() for ln in fh if ln.strip()]
    except Exception:
        return []


def _norm(p):
    return os.path.normcase(os.path.normpath(p))


def add_recent(path):
    if not path:
        return
    try:
        path = os.path.abspath(bpy.path.abspath(path))
        lst = [p for p in _read_lines(_recent_store()) if _norm(p) != _norm(path)]
        lst.insert(0, path)
        with open(_recent_store(), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lst[:RECENT_MAX]) + "\n")
    except Exception:
        log(traceback.format_exc(), "ERROR")


def recent_list(limit=20):
    """Recently opened / saved .blend files, newest first: Qt Shell's history, then the rest of
    Blender's list. Missing files are included (the menu shows them disabled)."""
    out, seen = [], set()
    for p in _read_lines(_recent_store()) + recent_files():
        k = _norm(p)
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out[:limit]


def clear_recent():
    try:
        with open(_recent_store(), "w", encoding="utf-8") as fh:
            fh.write("")
    except Exception:
        pass
    try:
        bpy.ops.wm.clear_recent_files("EXEC_DEFAULT")
    except Exception:
        try:
            path = os.path.join(bpy.utils.user_resource("CONFIG"), "recent-files.txt")
            open(path, "w", encoding="utf-8").close()
        except Exception:
            pass


def object_keyframes(ob):
    """Keyframed frames of the active object – works with both the old and the 'slotted' Action API (4.4+/5.x)."""
    ad = getattr(ob, "animation_data", None)
    act = ad.action if ad else None
    if act is None:
        return []
    fcurves = []
    try:
        fcurves = list(act.fcurves)
    except Exception:
        pass
    if not fcurves:
        try:
            from bpy_extras import anim_utils
            bag = anim_utils.action_get_channelbag_for_slot(act, ad.action_slot)
            if bag:
                fcurves = list(bag.fcurves)
        except Exception:
            pass
    frames = set()
    for fc in fcurves:
        for kp in fc.keyframe_points:
            frames.add(int(round(kp.co.x)))
    return sorted(frames)

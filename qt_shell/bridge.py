"""Most mezi Qt a Blenderem bez závislosti na Qt.

- kontext pro operátory (window/area/region z 3D view, i když je okno Blenderu skryté)
- spouštění operátorů (EXEC), odkládání načítání souborů mimo zásobník volání Qt
- persistentní handlery, které nastavují příznaky; Qt strana je čte v pumpě
"""
import os
import traceback
from contextlib import contextmanager

import bpy

# ---------------------------------------------------------------- stav sdílený s Qt
class Flags:
    depsgraph = False
    file_loaded = False
    undo = False
    render_done = False
    render_stats = ""


_log_listeners = []
# háčky, které nastaví Qt vrstva
file_dialog_hook = None      # fn(idname, rna_props, props) -> bool
special_op_hook = None       # fn(idname, props) -> bool (True = obslouženo v Qt)
after_op_hook = None         # fn(idname, props, result)


def add_log_listener(fn):
    _log_listeners.append(fn)


def remove_log_listener(fn):
    if fn in _log_listeners:
        _log_listeners.remove(fn)


def log(msg, level="INFO"):
    print(f"[QtShell] {level}: {msg}")
    for fn in list(_log_listeners):
        try:
            fn(str(msg), level)
        except Exception:
            pass


def tr(text):
    """Přeloží text rozhraní stejně jako Blender (respektuje jazyk v Preferences)."""
    if not text:
        return text
    try:
        return bpy.app.translations.pgettext_iface(text)
    except Exception:
        return text


# ---------------------------------------------------------------- kontext
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
    """temp_override na 3D view – bpy.context i bpy.ops se pak chovají jako v editoru."""
    found = ensure_view3d()
    kw = {}
    if found:
        win, area, region = found
        kw = dict(window=win, screen=win.screen, area=area, region=region)
    kw.update({k: v for k, v in extra.items() if v is not None})
    with bpy.context.temp_override(**kw):
        yield


def later(fn, delay=0.0):
    """Spustí fn v samostatném časovači Blenderu – mimo zásobník volání Qt."""
    def _run():
        try:
            fn()
        except Exception:
            log(traceback.format_exc(), "ERROR")
        return None
    bpy.app.timers.register(_run, first_interval=delay, persistent=True)


# ---------------------------------------------------------------- operátory
# operátory, které vymění celý soubor (a tím i okna/oblasti) → nesmí běžet uvnitř temp_override Qt pumpy
DEFER_OPS = {
    "wm.open_mainfile", "wm.read_homefile", "wm.read_factory_settings", "wm.revert_mainfile",
    "wm.recover_last_session", "wm.recover_auto_save", "wm.read_userpref",
}
# operátory s 'filepath', u kterých se dialog neotevírá
NO_FILE_DIALOG = {"wm.read_homefile", "wm.read_factory_settings", "wm.revert_mainfile",
                  "wm.recover_last_session", "wm.url_open", "wm.path_open", "render.render",
                  "wm.save_homefile", "wm.read_userpref", "wm.save_userpref"}


def get_op(idname):
    mod, name = idname.split(".", 1)
    op = getattr(getattr(bpy.ops, mod), name)
    op.get_rna_type()  # KeyError, pokud neexistuje
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
    """Spustí operátor Blenderu z Qt. Vrací množinu výsledků (nebo {'CANCELLED'})."""
    props = dict(props or {})
    if special_op_hook is not None:
        try:
            if special_op_hook(idname, props):
                return {"FINISHED"}
        except Exception:
            log(traceback.format_exc(), "ERROR")
    try:
        op = get_op(idname)
    except Exception:
        log(f"Operátor '{idname}' neexistuje.", "WARNING")
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
        # Operátory volané z Pythonu si samy krok undo neukládají → uložíme ho za ně.
        if "FINISHED" in res and not idname.startswith("ed."):
            try:
                if "UNDO" in (op.bl_options or set()):
                    undo_push(op_label(idname))
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


# ---------------------------------------------------------------- handlery
@bpy.app.handlers.persistent
def _on_depsgraph(*_args):
    Flags.depsgraph = True


@bpy.app.handlers.persistent
def _on_load(*_args):
    Flags.file_loaded = True
    Flags.depsgraph = True


@bpy.app.handlers.persistent
def _on_undo(*_args):
    Flags.undo = True
    Flags.depsgraph = True


@bpy.app.handlers.persistent
def _on_render_done(*_args):
    Flags.render_done = True


@bpy.app.handlers.persistent
def _on_render_stats(*args):
    for a in args:
        if isinstance(a, str):
            Flags.render_stats = a


_HANDLERS = (
    ("depsgraph_update_post", _on_depsgraph),
    ("frame_change_post", _on_depsgraph),
    ("load_post", _on_load),
    ("undo_post", _on_undo),
    ("redo_post", _on_undo),
    # Render handlery (render_stats/complete/cancel) se volají z renderovacího vlákna;
    # render_stats s prázdným řetězcem shodí Blender 5.x → konec renderu se zjišťuje
    # dotazem bpy.app.is_job_running("RENDER") v pumpě.
)
_OLD_HANDLERS = (("render_complete", "_on_render_done"), ("render_cancel", "_on_render_done"),
                 ("render_stats", "_on_render_stats"))


def is_rendering():
    try:
        return bpy.app.is_job_running("RENDER")
    except Exception:
        return False


def register_handlers():
    # odstraň případné handlery ze starší verze addonu
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


# ---------------------------------------------------------------- drobnosti
def user_modules_dir():
    return bpy.utils.user_resource("SCRIPTS", path="modules", create=True)


def recent_files():
    try:
        path = os.path.join(bpy.utils.user_resource("CONFIG"), "recent-files.txt")
        with open(path, encoding="utf-8") as fh:
            return [ln.strip() for ln in fh if ln.strip()]
    except Exception:
        return []


def object_keyframes(ob):
    """Snímky s klíči aktivního objektu – funguje se starým i 'slotted' Action API (4.4+/5.x)."""
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

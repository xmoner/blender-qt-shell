"""Public Python API of Qt Shell.

Use it from add-ons or scripts::

    import qt_shell.api as qs

    if qs.is_running():
        qs.status("Hello from my add-on")

Everything registered here (docks, menu actions, overlays, event handlers) is kept in a registry
that survives rebuilding the Qt window (Interface Size, add-on reload) and is installed again
automatically. Registering works also while Qt Shell is not running – it is applied when it starts.

All callbacks run on Blender's main thread inside a valid Blender context, so ``bpy`` and
``bpy.ops`` can be used in them. Exceptions in callbacks are caught and written to the Qt Shell
log (Console dock and ``%TEMP%/qtshell.log``).

Ownership: everything registered inside ``with owner("name"):`` (and everything a script registers
while it is run by Qt Shell – Text editor ▸ Run Script, Scripts dock) belongs to that owner and is
removed together by ``cleanup("name")``. Add-ons can use it in their ``unregister()``.

This module does not import PySide6 at load time, so it can be imported even when PySide6 is not
installed (``is_running()`` is then simply ``False``).
"""
import contextlib
import sys
import traceback
import types

import bpy

__all__ = [
    "API_VERSION", "is_running", "main_window", "viewport", "status",
    "add_dock", "remove_dock", "add_menu_action", "remove_menu_action",
    "get_view", "set_view", "frame_all", "frame_selected", "redraw",
    "view_matrix", "projection_matrix", "project", "viewport_size",
    "viewport_layout", "set_viewport_layout", "viewports", "status_history",
    "add_overlay", "remove_overlay", "on", "off", "EVENTS",
    "owner", "current_owner", "cleanup", "owned", "outliner", "graph_editor", "render_view",
    "active_tool", "set_tool", "TOOLS", "timeline", "image_editor",
]

API_VERSION = (1, 9)

# event name → Hub signal (None = emitted by Qt Shell itself)
EVENTS = {
    "data": "data_changed",            # fn()                         scene data changed (throttled)
    "selection": "selection_changed",  # fn()                         selection / active object changed
    "frame": "frame_changed",          # fn(frame: int)
    "mode": "mode_changed",            # fn(mode: str)                 'OBJECT', 'EDIT_MESH', …
    "file": "file_loaded",             # fn()                         a .blend file was loaded
    "undo": "undo_done",               # fn()                         undo / redo
    "render": "render_done",           # fn()                         F12 render finished
    "operator": "op_done",             # fn(idname, props, result)    operator run from Qt Shell
    "playback": None,                  # fn(playing: bool)            animation playback started/stopped
    "window": None,                    # fn(main_window)              Qt window (re)built
    "script": None,                    # fn(key: str, state: str)     a script was run / unloaded
}

_AREAS = {"left": "LeftDockWidgetArea", "right": "RightDockWidgetArea",
          "bottom": "BottomDockWidgetArea", "top": "TopDockWidgetArea"}


# ---------------------------------------------------------------- registry
def state_store(name):
    """A dict that lives for the whole Blender session: survives reloads of the add-on modules and
    loading other .blend files (kept in a module of its own in sys.modules)."""
    mod = sys.modules.get("_qt_shell_state")
    if mod is None:
        mod = sys.modules["_qt_shell_state"] = types.ModuleType("_qt_shell_state")
    d = getattr(mod, name, None)
    if not isinstance(d, dict):
        d = {}
        setattr(mod, name, d)
    return d


def _reg():
    """Registry of everything added through the API."""
    r = state_store("api")
    if not r:
        old = bpy.app.driver_namespace.get("_qt_shell_api")     # registry of version 1.0
        if isinstance(old, dict):
            r.update(old)
    for key in ("docks", "actions", "overlays", "events", "owners"):
        r.setdefault(key, {})
    r.setdefault("seq", 0)
    r.setdefault("owner_stack", [])
    return r


# ---------------------------------------------------------------- ownership
@contextlib.contextmanager
def owner(name):
    """Everything registered inside the block belongs to ``name`` (see cleanup())."""
    stack = _reg()["owner_stack"]
    stack.append(str(name))
    try:
        yield
    finally:
        if stack and stack[-1] == str(name):
            stack.pop()


def current_owner():
    stack = _reg()["owner_stack"]
    return stack[-1] if stack else None


def _disown(kind, item_id):
    for items in _reg()["owners"].values():
        items.discard((kind, item_id))


def _own(kind, item_id):
    r = _reg()
    _disown(kind, item_id)                       # an id re-registered by someone else changes owner
    o = current_owner()
    if o is not None:
        r["owners"].setdefault(o, set()).add((kind, item_id))


def owned(name):
    """List of (kind, id) registered by an owner – kind is 'dock', 'action', 'overlay' or 'event'."""
    return sorted(_reg()["owners"].get(str(name), ()))


def cleanup(name):
    """Removes everything registered by an owner. Returns the number of removed items."""
    items = _reg()["owners"].pop(str(name), set())
    remove = {"dock": remove_dock, "action": remove_menu_action,
              "overlay": remove_overlay, "event": off}
    for kind, item_id in items:
        try:
            remove[kind](item_id)
        except Exception:
            _log(f"cleanup of {kind} '{item_id}' failed:\n{traceback.format_exc()}")
    return len(items)


def _next_id(prefix):
    r = _reg()
    r["seq"] += 1
    return f"{prefix}{r['seq']}"


def _log(msg, level="ERROR"):
    b = sys.modules.get(__package__ + ".bridge")
    if b is not None:
        b.log(msg, level)
    else:
        print(f"[QtShell API] {level}: {msg}")


def _call(fn, *args, what="callback"):
    try:
        return fn(*args)
    except Exception:
        _log(f"Qt Shell API {what} failed:\n{traceback.format_exc()}")
        return None


# ---------------------------------------------------------------- window
def is_running():
    """True when the Qt Shell window exists."""
    return main_window() is not None


def main_window():
    """The Qt main window (QMainWindow) or None. Its internals are not part of the API."""
    app = sys.modules.get(__package__ + ".app")
    return getattr(app, "_win", None) if app is not None else None


def viewport():
    """The Qt 3D viewport widget (QWidget) or None. Use the view functions below instead of its
    attributes where possible – those are not part of the stable API."""
    w = main_window()
    return getattr(w, "viewport", None) if w is not None else None


def status_history():
    """The status bar messages of this Blender session: [(time 'HH:MM:SS', text), …], newest last."""
    return [(stamp, msg) for stamp, msg, _t in state_store("status").get("history", ())]


def viewports():
    """All 3D view widgets of the current layout (the view functions below act on the active one)."""
    w = main_window()
    area = getattr(w, "viewports", None) if w is not None else None
    return area.visible_views() if area is not None else []


def viewport_layout():
    """'single', 'side', 'stacked' or 'quad' (None when Qt Shell is not running)."""
    w = main_window()
    area = getattr(w, "viewports", None) if w is not None else None
    return area.mode if area is not None else None


def graph_editor():
    """The Graph editor of the Qt Shell window (None when Qt Shell is not open).

        import qt_shell
        ge = qt_shell.api.graph_editor()
        ge.set_snap(True)                 # snap key times to whole frames
        ge.set_tangents("LINEAR")         # AUTO, AUTO_CLAMPED, LINEAR, FLAT, CONSTANT
        ge.set_handle_type("FREE")        # FREE = break, ALIGNED = unify
        ge.set_infinity("REPEAT")         # CONSTANT, LINEAR, REPEAT, REPEAT_OFFSET, MIRROR
        ge.insert_keys(); ge.delete_keys(); ge.frame_all(); ge.frame_selected()

    Tangents / infinity apply to the selected keys, or to all shown curves when no key is selected."""
    w = main_window()
    return getattr(w, "graph_editor", None) if w is not None else None


def uv_editor():
    """The UV editor of the Qt Shell window (None when Qt Shell is not open).

        import qt_shell
        uv = qt_shell.api.uv_editor()
        uv.set_mode("FACE")                       # VERT, EDGE, FACE, ISLAND
        uv.tool("uv.pack_islands", {"margin": 0.01})   # any bpy.ops.uv operator, run in a UV editor context
        uv.mesh_tool("uv.smart_project")          # projections on the selected faces (all when none)
        uv.unwrap(); uv.layout_shells()
        uv.move_by(0.1, 0); uv.rotate_by(90); uv.flip(True); uv.align("UMIN"); uv.normalize()
        uv.texel_get(); uv.set_texel_density(512); uv.set_display("checker", True)
        uv.canvas.select_all("SELECT"); uv.canvas.frame_selected()"""
    w = main_window()
    return getattr(w, "uv_editor", None) if w is not None else None


def timeline():
    """The Timeline of the Qt Shell window (None when Qt Shell is not open).

        import qt_shell
        tl = qt_shell.api.timeline()
        tl.set_view_range(0, 120); tl.zoom(0.5); tl.frame_all()   # visible frames (zoom / pan)
        tl.play(); tl.play(reverse=True); tl.stop(); tl.step(1)
        tl.set_loop_mode("OSCILLATE")     # LOOP, ONCE, OSCILLATE (Maya)
        tl.set_preview_range(True, 10, 50); tl.set_preview_range(False)
        tl.set_fps(25); tl.set_show_seconds(True)
        tl.select_keys([10, 20]); tl.move_selected_keys(5); tl.selected_keys()
        tl.add_marker("Contact", 24)"""
    w = main_window()
    return getattr(w, "timeline", None) if w is not None else None


def render_view():
    """The Render View window of Qt Shell (Blender's render window), None when Qt Shell is not open.

        import qt_shell
        rv = qt_shell.api.render_view()
        rv.present()                      # show it (F11)
        rv.set_slot(1)                    # Slot 2 – the next render goes there (J / Alt+J cycle)
        rv.set_channel("ALPHA")           # COLOR_ALPHA, COLOR, ALPHA, RED, GREEN, BLUE
        rv.passes(); rv.set_pass("Depth")  # the passes enabled in View Layer Properties → Passes
        rv.zoom(1); rv.fit()              # 1:1, Frame All
        rv.save_as("C:/renders/frame.png")   # the format follows the extension
        rv.copy_to_clipboard()
        rv.set_tool("ANNOTATE", "LINE")   # SAMPLE / ANNOTATE (FREEHAND, LINE, POLYGON, ERASER)
        rv.add_annotation([(10, 10), (200, 120)], color="#ff4040", width=4)   # image pixels, top-left
        rv.annotations(); rv.clear_annotations(); rv.undo_annotation()
        rv.set_overlays(False); rv.set_gizmos(True); rv.set_toolbar(True)"""
    w = main_window()
    return getattr(w, "render_window", None) if w is not None else None


def image_editor():
    """The Image Editor of the Qt Shell window (compositor / render result / rendered animation), None when
    Qt Shell is not open.

        import qt_shell
        ie = qt_shell.api.image_editor()
        ie.set_source("COMPOSITOR")       # COMPOSITOR (the Viewer node), RENDER, ANIMATION or an image name
        ie.set_live(True)                 # follow every change of the compositor nodes
        ie.reload(); ie.fit(); ie.zoom(1)
        ie.set_channel("ALPHA")           # COLOR_ALPHA, COLOR, ALPHA, RED, GREEN, BLUE
        ie.set_frame(12); ie.play(); ie.pause()   # rendered animation
        ie.export_image("C:/renders/comp.exr")    # the format follows the extension
        ie.export_animation("C:/renders/anim.mp4", "MP4", 1, 120)   # MP4, PNG, JPEG, TIFF, COPY"""
    w = main_window()
    return getattr(w, "image_editor", None) if w is not None else None


# 3D viewport tools: tool → its variants (None = no variants)
TOOLS = {"SELECT": ("TWEAK", "BOX", "CIRCLE", "LASSO"), "CURSOR": None, "MOVE": None, "ROTATE": None,
         "SCALE": ("SCALE", "CAGE"), "TRANSFORM": None, "ANNOTATE": ("FREEHAND", "LINE", "POLYGON", "ERASER"),
         "MEASURE": None, "ADD": ("CUBE", "CONE", "CYLINDER", "UV_SPHERE", "ICO_SPHERE"),
         "BLUE_PENCIL": ("PENCIL", "BRUSH", "ERASER", "TEXT", "LINE", "ARROW", "ELLIPSE", "RECT", "TRANSFORM")}


def active_tool():
    """(tool, variant) of the 3D viewport's toolbar, e.g. ('SELECT', 'BOX') or ('MEASURE', None)."""
    w = main_window()
    if w is None:
        return None
    from . import gizmo
    st = gizmo.tool_state(w.hub)
    return st.tool, st.variant(st.tool)


def set_tool(tool, variant=None):
    """Activates a toolbar tool of the 3D viewport (shared by all views), see TOOLS:

        qt_shell.api.set_tool("ANNOTATE", "POLYGON")
        qt_shell.api.set_tool("ADD", "CYLINDER")    # Add tools only work in Object Mode
        qt_shell.api.set_tool("MEASURE")"""
    tool = str(tool).upper()
    if tool not in TOOLS:
        raise ValueError(f"Unknown tool {tool!r} – one of {', '.join(TOOLS)}")
    if variant is not None and variant not in (TOOLS[tool] or ()):
        raise ValueError(f"Tool {tool} has no variant {variant!r}")
    w = main_window()
    if w is None:
        return False
    from . import gizmo
    gizmo.tool_state(w.hub).set_tool(tool, variant)
    return True


def outliner():
    """The Outliner of the Qt Shell window (None when Qt Shell is not open).

        import qt_shell
        ol = qt_shell.api.outliner()
        ol.set_mode("BLENDER_FILE")       # VIEW_LAYER, BLENDER_FILE, ORPHAN
        ol.search("*foot*")               # wildcards * ?, "" clears
        ol.set_option("sort_alpha", False)  # keys: qt_shell.outliner.DEFAULTS
        ol.show_column("select", True)    # exclude, select, hide, viewport, render, holdout, indirect
        ol.show_selected(); ol.show_hierarchy(); ol.one_level(True); ol.expand_toggle()
        ol.new_collection(); ol.move_to(bpy.data.collections["Props"]); ol.parent_to_active(); ol.clear_parent()
        ol.hide_selected(); ol.unhide_all(); ol.isolate(("OBJECT", "Cube")); ol.delete(hierarchy=False)

    Commands that act on a selection use the Outliner's selected rows (or the selected objects)."""
    w = main_window()
    return getattr(w, "outliner", None) if w is not None else None


def set_viewport_layout(mode):
    """Splits the 3D view: 'single', 'side' (two views side by side), 'stacked' or 'quad'
    (Top / Perspective / Front / Right)."""
    w = main_window()
    area = getattr(w, "viewports", None) if w is not None else None
    if area is None:
        return False
    area.set_layout(mode)
    return True


def run_op(idname, invoke=False, **props):
    """Runs a Blender operator the way Qt Shell's menus do (3D view context, Qt Shell's own handling of
    e.g. render.render / transform.translate, an undo step). Returns the result set.

        import qt_shell
        qt_shell.api.run_op("mesh.primitive_cube_add", size=2)
        qt_shell.api.run_op("render.render")          # opens the Render View like F12"""
    from . import bridge
    return bridge.run_op(idname, props, invoke=invoke)


def status(text, timeout_ms=4000):
    """Shows a message in the status bar of the Qt window."""
    w = main_window()
    if w is not None:
        w.statusBar().showMessage(str(text), int(timeout_ms))


# ---------------------------------------------------------------- docks
def add_dock(dock_id, title, factory, area="right", visible=True):
    """Adds a dockable panel.

    factory: fn() -> QWidget – called every time the Qt window is built, must create a new widget.
    area: 'left' | 'right' | 'bottom' | 'top'. The position the user drags it to is remembered.
    The dock also appears in the Window menu. Calling it again with the same id replaces the dock.
    """
    if area not in _AREAS:
        raise ValueError(f"area must be one of {sorted(_AREAS)}")
    _reg()["docks"][dock_id] = {"title": title, "factory": factory, "area": area, "visible": visible}
    _own("dock", dock_id)
    w = main_window()
    if w is not None:
        _install_dock(w, dock_id)
    return dock_id


def remove_dock(dock_id):
    _disown("dock", dock_id)
    _reg()["docks"].pop(dock_id, None)
    w = main_window()
    if w is not None:
        _uninstall_dock(w, dock_id)


def _uninstall_dock(win, dock_id):
    d = getattr(win, "api_docks", {}).pop(dock_id, None)
    if d is not None:
        try:
            win.removeDockWidget(d)
            d.deleteLater()
        except Exception:
            pass


def _install_dock(win, dock_id):
    from PySide6 import QtCore, QtWidgets
    spec = _reg()["docks"].get(dock_id)
    if spec is None:
        return
    if not hasattr(win, "api_docks"):
        win.api_docks = {}
    _uninstall_dock(win, dock_id)
    widget = _call(spec["factory"], what=f"dock '{dock_id}' factory")
    if widget is None:
        return
    d = QtWidgets.QDockWidget(spec["title"], win)
    d.setObjectName(f"api_dock_{dock_id}")
    d.setWidget(widget)
    win.addDockWidget(getattr(QtCore.Qt, _AREAS[spec["area"]]), d)
    if not win.restoreDockWidget(d) and not spec["visible"]:   # no saved position → default
        d.hide()
    if d.isFloating():        # restoring a floating dock crashes Qt on Windows (see main_window)
        d.setFloating(False)
    win.api_docks[dock_id] = d
    wm = getattr(win, "window_menu", None)
    if wm is not None:
        wm.insertAction(getattr(win, "window_menu_docks_end", None), d.toggleViewAction())


# ---------------------------------------------------------------- menu actions
def add_menu_action(menu, text, callback, shortcut=None, tooltip=None, action_id=None):
    """Adds a menu item.

    menu: the title of a top-level menu – an existing one ('File', 'Edit', 'Add', 'Object',
          'Select', 'View', 'Render', 'Window', 'Help', …) or a new one, which is created before
          'Help' (e.g. 'Tools' or the name of your add-on).
    callback: fn() – runs in Blender's context.
    shortcut: e.g. 'Ctrl+Shift+T' – active in the whole Qt window.
    Returns the action id (for remove_menu_action).
    """
    aid = action_id or f"{menu}/{text}"
    _reg()["actions"][aid] = {"menu": menu, "text": text, "callback": callback,
                              "shortcut": shortcut, "tooltip": tooltip}
    _own("action", aid)
    w = main_window()
    if w is not None:
        _install_actions(w)
    return aid


def remove_menu_action(action_id):
    _disown("action", action_id)
    _reg()["actions"].pop(action_id, None)
    w = main_window()
    if w is not None:
        _install_actions(w)


def _menu_key(title):
    return str(title).replace("&", "").strip().lower()


def _make_action(parent, spec, with_shortcut):
    from PySide6 import QtCore, QtGui
    act = QtGui.QAction(spec["text"], parent)
    cb = spec["callback"]
    act.triggered.connect(lambda _c=False, cb=cb, t=spec["text"]: _call(cb, what=f"menu action '{t}'"))
    if spec.get("tooltip"):
        act.setToolTip(spec["tooltip"])
        act.setStatusTip(spec["tooltip"])
    if spec.get("shortcut"):
        act.setShortcut(QtGui.QKeySequence(spec["shortcut"]))
        if not with_shortcut:
            # only shows the key in the menu; the window-level action handles the shortcut
            act.setShortcutContext(QtCore.Qt.WidgetShortcut)
    return act


def _top_menus(win):
    menus = {}
    for act in win.menuBar().actions():
        m = act.menu()
        if m is not None:
            menus[_menu_key(m.property("qtshell_key") or m.title())] = m
    return menus


def _install_actions(win):
    """(Re)creates the API actions in non-generated menus and the window shortcuts.
    Menus generated from Blender (File, Add, …) get theirs through extend_menu() when they open."""
    from PySide6 import QtWidgets
    for act in getattr(win, "api_actions", []):
        try:
            act.deleteLater()
            for w in act.associatedObjects():
                if isinstance(w, QtWidgets.QWidget):
                    w.removeAction(act)
        except Exception:
            pass
    win.api_actions = []
    for m in getattr(win, "api_menus", []):
        try:
            win.menuBar().removeAction(m.menuAction())
            m.deleteLater()
        except Exception:
            pass
    win.api_menus = []

    specs = list(_reg()["actions"].values())
    menus = _top_menus(win)
    help_menu = menus.get("help")
    for spec in specs:
        key = _menu_key(spec["menu"])
        m = menus.get(key)
        if m is None:
            m = QtWidgets.QMenu(spec["menu"], win.menuBar())
            m.setProperty("qtshell_key", spec["menu"])
            win.menuBar().insertMenu(help_menu.menuAction() if help_menu else None, m)
            menus[key] = m
            win.api_menus.append(m)
        if not m.property("qtshell_generated"):
            if not any(a.property("qtshell_api") for a in m.actions()):
                sep = m.addSeparator()
                sep.setProperty("qtshell_api", True)
                win.api_actions.append(sep)
            act = _make_action(m, spec, with_shortcut=False)
            act.setProperty("qtshell_api", True)
            m.addAction(act)
            win.api_actions.append(act)
        if spec.get("shortcut"):
            sc = _make_action(win, spec, with_shortcut=True)
            win.addAction(sc)
            win.api_actions.append(sc)


def extend_menu(menu):
    """Called by menus generated from Blender after they are filled (internal)."""
    key = _menu_key(menu.property("qtshell_key") or menu.title())
    w = main_window()
    if w is not None and hasattr(w, "extend_builtin_menu"):
        try:
            w.extend_builtin_menu(menu, key)        # Qt Shell's own items (e.g. Edit → Qt Preferences…)
        except Exception:
            _log(traceback.format_exc())
    specs = [s for s in _reg()["actions"].values() if _menu_key(s["menu"]) == key]
    if not specs:
        return
    menu.addSeparator()
    for spec in specs:
        menu.addAction(_make_action(menu, spec, with_shortcut=False))


# ---------------------------------------------------------------- 3D view
def get_view():
    """Current view of the Qt viewport as a dict:
    target (x, y, z), distance, yaw, pitch (radians), ortho, camera_view, name."""
    vp = viewport()
    if vp is None:
        return None
    return {"target": tuple(vp.target), "distance": vp.dist, "yaw": vp.yaw, "pitch": vp.pitch,
            "ortho": vp.ortho, "camera_view": vp.camera_view, "name": vp.view_name}


def set_view(preset=None, target=None, distance=None, yaw=None, pitch=None, ortho=None):
    """Changes the view. preset: 'FRONT', 'BACK', 'LEFT', 'RIGHT', 'TOP', 'BOTTOM' or 'CAMERA'
    (toggles the camera view). The other arguments set the orbit view directly:
    target = point to orbit around, distance, yaw (around Z) and pitch (0 = from above, π = from below)."""
    import math
    from mathutils import Vector
    vp = viewport()
    if vp is None:
        return False
    if preset:
        vp.set_view(str(preset).upper())
    changed = any(v is not None for v in (target, distance, yaw, pitch))
    if changed:
        vp.leave_camera()
        if target is not None:
            vp.target = Vector(target)
        if distance is not None:
            vp.dist = max(float(distance), 1e-4)
        if yaw is not None:
            vp.yaw = float(yaw)
        if pitch is not None:
            vp.pitch = min(max(float(pitch), 0.0001), math.pi - 0.0001)
    if ortho is not None:
        vp.ortho = bool(ortho)
    if changed or ortho is not None:
        vp.view_name = "User Orthographic" if vp.ortho else "User Perspective"
    vp.request_redraw()
    vp.update()
    return True


def frame_all():
    vp = viewport()
    if vp is not None:
        vp.frame_all()


def frame_selected():
    vp = viewport()
    if vp is not None:
        vp.frame_selected()


def redraw():
    """Redraws the 3D views (scene and overlays)."""
    for vp in viewports() or ([viewport()] if viewport() is not None else []):
        vp.request_redraw()
        vp.update()


def viewport_size():
    """(width, height) of the viewport in Qt (logical) pixels."""
    vp = viewport()
    return (vp.width(), vp.height()) if vp is not None else None


def view_matrix():
    vp = viewport()
    return vp.matrices(vp.width(), vp.height())[0] if vp is not None else None


def projection_matrix():
    vp = viewport()
    return vp.matrices(vp.width(), vp.height())[1] if vp is not None else None


def project(co):
    """World coordinates → (x, y) pixel position in the viewport widget, or None if behind the view."""
    vp = viewport()
    if vp is None:
        return None
    p = vp.project(co)
    return (p.x(), p.y()) if p is not None else None


# ---------------------------------------------------------------- overlays
class OverlayContext:
    """Passed to overlay functions: size of the viewport and a project() helper."""

    def __init__(self, vp):
        self.width = vp.width()
        self.height = vp.height()
        self.view_matrix, self.projection_matrix = vp.matrices(self.width, self.height)
        self._vp = vp
        self._mats = (self.view_matrix, self.projection_matrix)

    def project(self, co):
        """World coordinates → QPointF in the viewport, or None if behind the view."""
        return self._vp.project(co, self._mats)


def add_overlay(overlay_id, fn):
    """Draws over the 3D viewport with Qt: fn(painter: QPainter, ctx: OverlayContext).

    Called on every repaint of the viewport, so keep it fast. Use ctx.project((x, y, z)) to get the
    screen position of a 3D point. Call redraw() when your overlay needs to change.
    """
    _reg()["overlays"][overlay_id] = fn
    _own("overlay", overlay_id)
    redraw()
    return overlay_id


def remove_overlay(overlay_id):
    _disown("overlay", overlay_id)
    _reg()["overlays"].pop(overlay_id, None)
    redraw()


def paint_overlays(vp, painter):
    """Called by the viewport (internal)."""
    overlays = _reg()["overlays"]
    if not overlays:
        return
    ctx = OverlayContext(vp)
    for oid, fn in list(overlays.items()):
        painter.save()
        try:
            fn(painter, ctx)
        except Exception:
            _log(f"Qt Shell overlay '{oid}' failed:\n{traceback.format_exc()}")
            overlays.pop(oid, None)   # a broken overlay would flood the log on every repaint
        finally:
            painter.restore()


# ---------------------------------------------------------------- events
def on(event, fn):
    """Calls fn when something happens (see EVENTS for the names and arguments).
    Returns a handle for off(). Handlers stay registered when the window is rebuilt."""
    if event not in EVENTS:
        raise ValueError(f"unknown event {event!r}, use one of {sorted(EVENTS)}")
    hid = _next_id("h")
    _reg()["events"][hid] = (event, fn)
    _own("event", hid)
    return hid


def off(handle):
    _disown("event", handle)
    _reg()["events"].pop(handle, None)


def emit(event, *args):
    """Calls the handlers of an event (internal; Qt Shell emits 'playback' and 'window' itself)."""
    for hid, (ev, fn) in list(_reg()["events"].items()):
        if ev == event:
            _call(fn, *args, what=f"'{event}' handler")


def _connect_events(hub):
    for event, signal in EVENTS.items():
        if signal:
            getattr(hub, signal).connect(lambda *a, e=event: emit(e, *a))


# ---------------------------------------------------------------- installation (internal)
def apply_to_window(win):
    """Installs everything registered so far into a newly built Qt window."""
    win.api_docks = {}
    win.api_actions = []
    win.api_menus = []
    try:
        _connect_events(win.hub)
    except Exception:
        _log(traceback.format_exc())
    # docks are added once the window is shown and laid out (adding them during construction,
    # after restoreState(), leaves them unplaced in the top-left corner)
    from PySide6 import QtCore

    def install_docks():
        if main_window() is not win:
            return
        for dock_id in list(_reg()["docks"]):
            try:
                _install_dock(win, dock_id)
            except Exception:
                _log(f"dock '{dock_id}':\n{traceback.format_exc()}")
    QtCore.QTimer.singleShot(0, install_docks)
    try:
        _install_actions(win)
    except Exception:
        _log(traceback.format_exc())
    emit("window", win)

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

This module does not import PySide6 at load time, so it can be imported even when PySide6 is not
installed (``is_running()`` is then simply ``False``).
"""
import sys
import traceback

import bpy

__all__ = [
    "API_VERSION", "is_running", "main_window", "viewport", "status",
    "add_dock", "remove_dock", "add_menu_action", "remove_menu_action",
    "get_view", "set_view", "frame_all", "frame_selected", "redraw",
    "view_matrix", "projection_matrix", "project", "viewport_size",
    "add_overlay", "remove_overlay", "on", "off", "EVENTS",
]

API_VERSION = (1, 0)

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
}

_AREAS = {"left": "LeftDockWidgetArea", "right": "RightDockWidgetArea",
          "bottom": "BottomDockWidgetArea", "top": "TopDockWidgetArea"}


# ---------------------------------------------------------------- registry
def _reg():
    """Registry kept in Blender's driver namespace, so it survives reloads of this module."""
    ns = bpy.app.driver_namespace
    r = ns.get("_qt_shell_api")
    if not isinstance(r, dict):
        r = ns["_qt_shell_api"] = {}
    for key in ("docks", "actions", "overlays", "events"):
        r.setdefault(key, {})
    r.setdefault("seq", 0)
    return r


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
    w = main_window()
    if w is not None:
        _install_dock(w, dock_id)
    return dock_id


def remove_dock(dock_id):
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
    w = main_window()
    if w is not None:
        _install_actions(w)
    return aid


def remove_menu_action(action_id):
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
    """Redraws the viewport (scene and overlays)."""
    vp = viewport()
    if vp is not None:
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
    redraw()
    return overlay_id


def remove_overlay(overlay_id):
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
    return hid


def off(handle):
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

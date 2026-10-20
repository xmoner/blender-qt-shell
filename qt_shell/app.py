"""Runs Qt inside the Blender process and 'pumps' Qt events from a Blender timer."""
import sys
import time
import traceback

import bpy
from PySide6 import QtCore, QtWidgets

from . import bridge, native, theme

_app = None
_win = None
_hub = None
_pump_on = False
_prefs = None


class Hub(QtCore.QObject):
    """Turns changes in Blender into Qt signals (called from the pump)."""
    data_changed = QtCore.Signal()
    selection_changed = QtCore.Signal()
    frame_changed = QtCore.Signal(int)
    mode_changed = QtCore.Signal(str)
    file_loaded = QtCore.Signal()
    undo_done = QtCore.Signal()
    render_done = QtCore.Signal()
    render_stats = QtCore.Signal(str)
    title_changed = QtCore.Signal()
    op_done = QtCore.Signal(str, dict, object)
    log = QtCore.Signal(str, str)

    def __init__(self):
        super().__init__()
        self._last_data = 0.0
        self._last_snap = 0.0
        self._snap = None
        self._title = None
        self._stats = ""
        self._was_rendering = False
        self.viewport = None     # set by the main window
        self.viewport_area = None   # all 3D views (ViewportArea); viewport is the active one
        self.playing = False     # animation playback in the timeline
        self.main_window = None

    def tick(self):
        now = time.monotonic()
        F = bridge.Flags
        if F.file_loaded:
            F.file_loaded = False
            self._snap = None
            self.file_loaded.emit()
        if F.undo:
            F.undo = False
            self.undo_done.emit()
        rendering = bridge.is_rendering()
        if self._was_rendering and not rendering:
            self.render_done.emit()
        self._was_rendering = rendering
        if rendering:
            return  # don't touch the scene while rendering
        # during playback the viewport is redrawn by the playback itself; the rest of the UI
        # (properties, outliner…) only needs an occasional refresh
        data_interval = 0.5 if self.playing else 0.06
        if F.depsgraph and now - self._last_data > data_interval:
            F.depsgraph = False
            self._last_data = now
            self.data_changed.emit()
        if now - self._last_snap > 0.05:
            self._last_snap = now
            self._check_snapshot()

    def _check_snapshot(self):
        ctx = bpy.context
        try:
            vl = ctx.view_layer
            active = vl.objects.active.name if vl.objects.active else ""
            sel = tuple(sorted(o.name for o in ctx.selected_objects))
            frame = ctx.scene.frame_current
            mode = ctx.mode
            bones = ()
            if mode == "POSE" and vl.objects.active is not None and vl.objects.active.pose is not None:
                ob = vl.objects.active
                ab = ob.data.bones.active
                bones = ((ab.name if ab else ""),
                         tuple(pb.name for pb in ob.pose.bones if pb.select))
        except Exception:
            return
        snap = (active, sel, frame, mode, bones)
        old = self._snap
        self._snap = snap
        if old is None or old[:2] != snap[:2] or old[4] != snap[4]:
            self.selection_changed.emit()
        if old is None or old[2] != frame:
            self.frame_changed.emit(frame)
        if old is None or old[3] != mode:
            self.mode_changed.emit(mode)
        title = (bpy.data.filepath, bpy.data.is_dirty)
        if title != self._title:
            self._title = title
            self.title_changed.emit()


def hub():
    return _hub


def prefs():
    return _prefs


def _notify_with_context(app, obj, ev):
    """Delivers a Qt event inside a Blender context when Blender's own loop dispatched it.

    Module-level on purpose: after an add-on reload the running QApplication is still an instance of the
    *old* ShellApp class, so this must not rely on super() or on the class – it looks up the current
    module state through sys.modules every time."""
    base = QtWidgets.QApplication.notify
    et = ev.type()
    if et == QtCore.QEvent.ToolTip:
        # Python tooltips (Edit → Qt Preferences… → Interface)
        pt = sys.modules.get(__name__.rsplit(".", 1)[0] + ".pytips")
        if pt is not None and pt.enabled() and pt.handle(obj, ev):
            return True
    elif et == QtCore.QEvent.MouseButtonPress and ev.button() == QtCore.Qt.MiddleButton \
            and ev.modifiers() & QtCore.Qt.ShiftModifier:
        # Shift + middle click: copy the Python command of a button / field / menu item
        pt = sys.modules.get(__name__.rsplit(".", 1)[0] + ".pytips")
        if pt is not None and pt.copy_on_click(obj, ev):
            return True
    mod = sys.modules.get(__name__)
    win = getattr(mod, "_win", None) if mod is not None else None
    if win is not None:
        try:
            need = bpy.context.area is None
        except Exception:
            need = False
        if need:
            try:
                cm = mod.bridge.blender_context()
                cm.__enter__()
            except Exception:
                return base(app, obj, ev)
            try:
                return base(app, obj, ev)
            finally:
                try:
                    cm.__exit__(None, None, None)
                except Exception:
                    pass
    return base(app, obj, ev)


class ShellApp(QtWidgets.QApplication):
    """QApplication that gives every event a Blender context.

    On Windows (and partly elsewhere) Blender's own event loop (GHOST) also dispatches
    messages to Qt windows, i.e. outside the temp_override of our pump. Without this wrapper
    a key press would see bpy.context without a 3D view (mode == 'OBJECT' even in edit mode,
    and operators would fail).
    """

    def notify(self, obj, ev):
        return _notify_with_context(self, obj, ev)


def _pump():
    global _pump_on
    if _win is None:
        _pump_on = False
        return None
    playing = False
    try:
        with bridge.blender_context():
            _hub.tick()
            playing = _hub.playing
            if playing:
                _win.timeline.playback_tick()
            _app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 4 if playing else 15)
            # Next frame due soon → keep Blender's loop from sleeping its idle 5 ms. Posted *after*
            # processEvents, otherwise Qt's dispatcher takes the message off the queue first.
            if playing and getattr(_win.timeline, "_next", 0.0) - time.perf_counter() < 0.0055:
                native.wake_event_loop()
    except Exception:
        traceback.print_exc()
    # while playing, run again on the next pass of Blender's event loop
    return 0.0 if playing else 0.01


def qt_window_ids():
    """Native ids of our own Qt windows (only needed on X11 to tell them apart from Blender's).

    Deliberately does not use QApplication.topLevelWidgets(): that also returns Qt's internal windows
    (combo box popups, …) which have no Python wrapper yet, and creating one from a Blender timer
    re-enters our notify() with a half-built object – a crash in Python."""
    ids = []
    if _win is None or not sys.platform.startswith("linux"):
        return ids
    wins = [_win] + [d for d in getattr(_win, "docks", {}).values() if d.isFloating()]
    for w in wins:
        try:
            if w.testAttribute(QtCore.Qt.WA_WState_Created):
                ids.append(int(w.winId()))
        except Exception:
            pass
    return ids


def set_blender_visible(visible):
    ok, msg = native.set_blender_windows_visible(visible, qt_window_ids())
    if not ok:
        bridge.log(f"Blender window: {msg}", "WARNING")
    return ok


_fault_file = None


def _enable_faulthandler():
    """On a hard crash, write the Python stack to <temp>/qtshell_crash.log (Blender's console is hidden)."""
    global _fault_file
    try:
        import faulthandler
        import tempfile
        import os
        if _fault_file is None or _fault_file.closed:
            _fault_file = open(os.path.join(tempfile.gettempdir(), "qtshell_crash.log"), "a", encoding="utf-8")
        faulthandler.enable(file=_fault_file, all_threads=True)
    except Exception:
        pass


def start(addon_prefs=None):
    global _app, _win, _hub, _pump_on, _prefs
    _enable_faulthandler()
    _prefs = addon_prefs
    if _win is not None:
        _win.show()
        _win.raise_()
        _win.activateWindow()
        return
    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
        QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    _app = QtWidgets.QApplication.instance() or ShellApp(["blender"])
    # NOTE: never reassign notify on the running QApplication's class after a reload. Shiboken caches
    # the Python override; replacing it frees the old function and the next event crashes Blender.
    # ShellApp.notify calls the module-level _notify_with_context by name, so the old class picks up
    # the reloaded code by itself.
    if type(_app).__name__ != "ShellApp":
        bridge.log("QApplication was created before Qt Shell – event context is not guaranteed "
                   "(restart Blender).", "WARNING")
    _app.setQuitOnLastWindowClosed(False)
    if addon_prefs is not None:
        theme.set_scale(getattr(addon_prefs, "ui_scale", 1.0), getattr(addon_prefs, "font_scale", 1.0))
    theme.apply(_app)

    _hub = Hub()
    bridge.add_log_listener(lambda m, lvl: _hub.log.emit(m, lvl))

    # safe start: a marker file exists while the window is being created and shown. If it is still
    # there on the next start, the previous start crashed Blender – the saved window layout is then
    # discarded (a broken layout is the usual cause) and the window starts with the default one.
    import os
    import tempfile
    marker = os.path.join(tempfile.gettempdir(), "qtshell_starting")
    safe = os.path.exists(marker)
    if safe:
        bridge.log("The previous start of Qt Shell did not finish – starting with the default window "
                   "layout.", "WARNING")
        try:
            st = QtCore.QSettings("QtShell", "QtShell")
            st.remove("state")
            st.remove("geometry")
            st.remove("floating_docks")
            st.sync()
        except Exception:
            pass
    try:
        with open(marker, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass

    def _started():
        try:
            os.remove(marker)
        except Exception:
            pass

    try:
        from .main_window import MainWindow
        with bridge.blender_context():
            _win = MainWindow(_hub)
            _win.show()
        bridge.later(_started, 3.0)
    except Exception:
        # never leave the user without a window: log the error and bring Blender back
        bridge.log("Qt Shell window could not be created:\n" + traceback.format_exc(), "ERROR")
        _started()
        _win = None
        set_blender_visible(True)
        return
    if not _pump_on:
        _pump_on = True
        bpy.app.timers.register(_pump, first_interval=0.0, persistent=True)
    if addon_prefs is None or addon_prefs.hide_blender:
        # wait a moment until the Qt window really exists (so it is excluded from the X11 search)
        bridge.later(lambda: set_blender_visible(False), 0.5)


_rebuild_pending = False


def preview_interface_size(ui, font):
    """Live preview: fonts and style sheet only (fixed widget sizes update on rebuild)."""
    if _app is None:
        return
    theme.set_scale(ui, font)
    theme.apply(_app)


def apply_interface_size():
    """Applies the size from the add-on preferences and rebuilds the Qt window (once per burst)."""
    global _rebuild_pending
    if _rebuild_pending or _win is None:
        return
    _rebuild_pending = True

    def run():
        global _rebuild_pending
        _rebuild_pending = False
        p = _prefs
        if p is not None:
            theme.set_scale(p.ui_scale, p.font_scale)
        stop(show_blender=False)
        start(p)

    bridge.later(run, 0.05)


def stop(show_blender=True):
    global _win, _hub
    if show_blender:
        set_blender_visible(True)
    if _win is not None:
        try:
            _win.shutdown()
            _win.hide()
            _win.deleteLater()
        except Exception:
            pass
    _win = None
    bridge.file_dialog_hook = None
    bridge.special_op_hook = None
    bridge.after_op_hook = None
    if _app is not None:
        _app.processEvents()

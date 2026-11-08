"""Blender's own 3D viewport inside the Qt view (Qt Preferences → Viewport → Blender's viewport).

The Qt view draws Blender's scene offscreen and adds its own overlays, gizmos and navigation. Sculpting
through it (sculpt.py) goes through Python and the offscreen drawing can't show Multires levels or Dynamic
Topology. For Blender's speed and behaviour a helper Blender window (`wm.window_new`) with one 3D view is
embedded into the Qt view (QWindow.fromWinId + createWindowContainer – the GHOST window becomes a child
window). Blender draws it and handles its mouse / keys itself (strokes, brush cursor, selection, tools,
navigation of the active keyconfig, undo). The camera goes over when entering and comes back when leaving;
then the window is closed.

When it is used – QSettings `viewport/blender_view`:
  "sculpt" (default)  in Sculpt Mode only
  "always"            in every mode
  "never"             never (Sculpt Mode then uses sculpt.py's Qt strokes)

While it is active, `bridge.find_view3d` returns its area, so the Qt header, menus and panels act on the
visible view; interactive operators (G / R / S, extrude …) run as Blender's own modal operators there.
"""
import math
import sys

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge

KEY = "viewport/blender_view"
CHOICES = (("sculpt", "Sculpt Mode only"), ("always", "Always (every mode)"), ("never", "Never (Qt Shell's view)"))
TAG = "qtshell_view"     # ID property on the helper window's screen: found again after a file is loaded

_view = None            # the NativeView in use
_timer = None
_watch = None           # checks for Blender's own playback started in the embedded view
_suspended = False      # cached playback: the Qt view shows the cache, Blender's view is hidden meanwhile


# ---------------------------------------------------------------- setting
def setting():
    v = str(QtCore.QSettings("QtShell", "QtShell").value(KEY, "sculpt") or "sculpt")
    return v if v in dict(CHOICES) else "sculpt"


def set_setting(value):
    if value not in dict(CHOICES):
        return
    QtCore.QSettings("QtShell", "QtShell").setValue(KEY, value)
    QtCore.QTimer.singleShot(0, sync)


def wanted(mode=None):
    s = setting()
    if s == "always":
        return True
    if s == "never":
        return False
    try:
        mode = mode or bpy.context.mode
    except Exception:
        return False
    return mode == "SCULPT"


# ---------------------------------------------------------------- state
def active(vp=None):
    return _view is not None and not _view.stale and (vp is None or _view.vp is vp)


def covers(vp=None):
    """Blender's view is embedded and shown over the Qt view (not while cached playback uses the Qt view)."""
    return active(vp) and not _suspended


# ---------------------------------------------------------------- cached playback
def playback(on):
    """Timeline playback started / stopped. With the playback cache on, the Qt view plays (from the cache –
    Blender's own view would evaluate the scene every frame): Blender's view is hidden meanwhile and comes back,
    with the camera of the Qt view, when playback stops."""
    global _suspended
    v = _view
    if v is None or v.stale:
        _suspended = False
        return
    from . import playcache
    try:
        if on and not _suspended and playcache.enabled():
            _suspended = True
            v.suspend()
        elif not on and _suspended:
            _suspended = False
            v.resume()
    except Exception as ex:
        bridge.log(f"Blender's viewport: playback switch failed ({ex})", "WARNING")


def _watch_playback():
    """Space pressed in Blender's view starts Blender's own playback (no cache) – with the playback cache on,
    it is handed to the Qt Timeline instead."""
    v = _view
    if v is None or v.stale or _suspended or bridge.op_depth:
        return
    from . import app, playcache
    if not playcache.enabled() or app._win is None:
        return
    try:
        playing = [w for w in bpy.context.window_manager.windows
                   if w.screen is not None and w.screen.is_animation_playing]
    except Exception:
        return
    if not playing:
        return
    w = playing[0]
    try:
        with bpy.context.temp_override(window=w, screen=w.screen):
            bpy.ops.screen.animation_cancel(restore_frame=False)
    except Exception as ex:
        bridge.log(f"Blender's viewport: stopping Blender's playback failed ({ex})", "WARNING")
        return
    tl = getattr(app._win, "timeline", None)
    if tl is not None and not tl.is_playing():
        tl.play()


def start(win):
    """Starts the check that keeps the embedded view in line with the setting, the mode, file loads."""
    global _timer
    if _timer is not None:
        try:
            _timer.stop()
        except RuntimeError:
            pass
    _timer = QtCore.QTimer(win)
    _timer.setInterval(1000)
    _timer.timeout.connect(sync)
    _timer.start()
    global _watch
    if _watch is not None:
        try:
            _watch.stop()
        except RuntimeError:
            pass
    _watch = QtCore.QTimer(win)
    _watch.setInterval(100)
    _watch.timeout.connect(_watch_playback)
    _watch.start()
    QtCore.QTimer.singleShot(0, sync)


def stop():
    global _timer, _watch
    for t in (_timer, _watch):
        if t is not None:
            try:
                t.stop()
            except RuntimeError:
                pass
    _timer = _watch = None
    leave()


def sync(vp=None):
    """Embeds / removes Blender's view as the setting and the mode want it."""
    from . import app
    win = app._win
    if win is None:
        return
    try:
        if bridge.op_depth or getattr(win, "_rendering", False) or getattr(win, "_render_win", None) is not None:
            return
        vp = vp or win.viewport
        if _view is not None and (_view.stale or not _view.alive() or _view.area() is None):
            leave(camera=_view.area() is not None and not _view.stale)   # a file was loaded: start over
        _close_stale_windows()
        want = wanted() and vp is not None and vp.isVisible()
        if want and not active(vp):
            enter(vp)
        elif not want and _view is not None:
            leave()
        elif _view is not None and not _suspended:
            _view.apply_regions()
    except Exception as ex:
        bridge.log(f"Blender's viewport: {ex}", "WARNING")


def enter(vp):
    """Embeds Blender's 3D view into `vp` (Qt view). False if it can't be done."""
    global _view
    if _view is not None:
        if _view.vp is vp and _view.alive() and not _view.stale:
            return True
        leave()
    try:
        _view = NativeView(vp)
        bridge.preferred_view3d = _preferred
        return True
    except Exception as ex:
        _view = None
        bridge.log(f"Blender's own 3D view could not be embedded ({ex}) – using the Qt view.", "WARNING")
        return False


def leave(camera=True):
    """The camera and the shading back to the Qt view, the Blender window closed."""
    global _view, _suspended
    v, _view = _view, None
    bridge.preferred_view3d = None
    if _suspended:
        camera = False                     # the Qt view already has the camera (cached playback)
        _suspended = False
    if v is not None:
        v.close(camera=camera)


def _preferred():
    v = _view
    if v is None or v.stale or not v.alive():
        return None
    area = v.area()
    if area is None:
        return None
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    return (v.window(), area, region) if region is not None else None


def _close_stale_windows():
    """Helper windows saved in a .blend (file saved while the view was embedded) – closed after loading."""
    from . import app
    wm = bpy.context.window_manager
    wins = list(wm.windows)
    mine = _view.ptr if _view is not None else None
    for i, w in enumerate(wins):
        if i == 0 or w.as_pointer() == mine:
            continue
        try:
            tagged = w.screen is not None and w.screen.get(TAG)
        except Exception:
            tagged = False
        if tagged and app._win is not None:
            app._win.close_blender_window(w)


@bpy.app.handlers.persistent
def _on_load_pre(*_args):
    if _view is not None:
        _view.stale = True                 # its area / window may be freed – touched again only by sync()
    bridge.preferred_view3d = None


def register_handlers():
    lst = bpy.app.handlers.load_pre
    for old in [f for f in lst if getattr(f, "__name__", "") == "_on_load_pre"
                and getattr(f, "__module__", "") == __name__]:
        lst.remove(old)
    lst.append(_on_load_pre)


def unregister_handlers():
    lst = bpy.app.handlers.load_pre
    for old in [f for f in lst if getattr(f, "__name__", "") == "_on_load_pre"
                and getattr(f, "__module__", "") == __name__]:
        lst.remove(old)


# ---------------------------------------------------------------- input
def qt_pressed(obj):
    """A mouse press on a Qt widget: Windows keeps the keyboard focus on the embedded Blender window (a
    native child) even when a Qt widget gets Qt's focus – give the Win32 focus back to the Qt window."""
    v = _view
    if v is None or sys.platform != "win32":
        return
    try:
        w = obj.window() if isinstance(obj, QtWidgets.QWidget) else None
    except Exception:
        w = None
    if w is None:
        return
    import ctypes
    user32 = ctypes.windll.user32
    try:
        f = user32.GetFocus()
        if f and (f == v.hwnd or user32.IsChild(v.hwnd, f)):
            user32.SetFocus(int(w.winId()))
    except Exception:
        pass


def focus_view():
    """Keyboard focus to the embedded Blender window (its modal operators read keys from there)."""
    v = _view
    if v is None:
        return
    try:
        v.container.setFocus()
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.SetFocus(v.hwnd)
    except Exception:
        pass


def invoke(idname, props):
    """Runs an interactive operator (G / R / S, extrude, bevel …) as Blender's own modal operator in the
    embedded view. False when it couldn't be started (the caller then uses Qt Shell's version)."""
    ctx = _preferred()
    if ctx is None:
        return False
    win, area, region = ctx
    try:
        mod, name = idname.split(".", 1)
        op = getattr(getattr(bpy.ops, mod), name)
        focus_view()
        with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
            res = op("INVOKE_DEFAULT", True, **(props or {}))
        return "CANCELLED" not in res
    except Exception as ex:
        bridge.log(f"{idname}: {ex}", "WARNING")
        return False


def resized(vp):
    if _view is not None and _view.vp is vp:
        _view.fit()


def _copy_props(src, dst):
    for p in src.bl_rna.properties:
        pid = p.identifier
        if pid == "rna_type" or p.is_readonly or p.type in ("POINTER", "COLLECTION"):
            continue
        try:
            v = getattr(src, pid)
            if getattr(dst, pid) != v:
                setattr(dst, pid, v)
        except Exception:
            pass


class NativeView:
    def __init__(self, vp):
        from . import native, app
        self.vp = vp
        self.stale = False
        wm = bpy.context.window_manager
        before = {w.as_pointer() for w in wm.windows}
        native_before = set(native.ghost_windows())
        main_sp = self._main_space()
        with bridge.blender_context():
            bpy.ops.wm.window_new()
        new = [w for w in wm.windows if w.as_pointer() not in before]
        if not new:
            raise RuntimeError("no new Blender window")
        self.ptr = new[0].as_pointer()
        hwnds = [h for h in native.ghost_windows() if h not in native_before]
        if not hwnds:
            self._close_window()
            raise RuntimeError("no native window handle")
        self.hwnd = hwnds[0]
        native.hide_windows(hwnds)                 # no flash as a separate window before it is embedded
        win = new[0]
        try:
            win.screen[TAG] = 1
        except Exception:
            pass
        area = max(win.screen.areas, key=lambda a: a.width * a.height)
        area.type = "VIEW_3D"
        self.area_ptr = area.as_pointer()
        self._setup_space(vp, main_sp)
        # embed
        self.qwin = QtGui.QWindow.fromWinId(self.hwnd)
        self.container = QtWidgets.QWidget.createWindowContainer(self.qwin, vp)
        self.container.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.fit()
        self.container.show()
        # Blender turns the tool header (and asset shelf) of a Sculpt Mode view back on while it sets up the
        # new window – hide them again once it has drawn (the Sculpt panel has those settings)
        for ms in (200, 800, 2000):
            QtCore.QTimer.singleShot(ms, self.apply_regions)
        try:
            if app._win is not None:
                app._win.activateWindow()
        except Exception:
            pass

    # ---- lookups (never keep Blender structs: a file load can free them)
    def window(self):
        for w in bpy.context.window_manager.windows:
            if w.as_pointer() == self.ptr:
                return w
        return None

    def alive(self):
        try:
            return self.window() is not None
        except Exception:
            return False

    def area(self):
        if self.stale:
            return None
        try:
            w = self.window()
            if w is None or w.screen is None:
                return None
            for a in w.screen.areas:
                if a.as_pointer() == self.area_ptr and a.type == "VIEW_3D":
                    return a
        except Exception:
            pass
        return None

    def space(self):
        a = self.area()
        return a.spaces.active if a is not None else None

    def _main_space(self):
        """The hidden 3D view the Qt view draws with (not this one)."""
        old, bridge.preferred_view3d = bridge.preferred_view3d, None
        try:
            sp, _r = self.vp.space()
            return sp
        except Exception:
            return None
        finally:
            bridge.preferred_view3d = old

    # ---- setup
    def apply_regions(self):
        """Blender's header, sidebar, HUD, asset shelf hidden (Qt Shell has them); its toolbar shown outside
        Sculpt Mode (Blender's tools work there), hidden in Sculpt Mode (the Sculpt panel has the brushes)."""
        sp = self.space()
        if sp is None:
            return
        try:
            sculpt = bpy.context.mode == "SCULPT"
        except Exception:
            sculpt = False
        want = {"show_region_header": False, "show_region_tool_header": False, "show_region_ui": False,
                "show_region_hud": False, "show_region_asset_shelf": False, "show_region_toolbar": not sculpt}
        todo = {a: on for a, on in want.items() if hasattr(sp, a) and getattr(sp, a) != on}
        if not todo:
            return
        with self.context():               # region updates use the context window (NULL → crash, 2026-11-08)
            for attr, on in todo.items():
                try:
                    setattr(sp, attr, on)
                except Exception:
                    pass

    def context(self):
        """temp_override onto the embedded window / area – RNA updates of its space need a context window."""
        w, a = self.window(), self.area()
        kw = {}
        if w is not None:
            kw = dict(window=w, screen=w.screen)
            if a is not None:
                kw["area"] = a
        return bpy.context.temp_override(**kw)

    def _setup_space(self, vp, main_sp):
        sp = self.space()
        self.apply_regions()
        with self.context():
            if main_sp is not None:
                _copy_props(main_sp.shading, sp.shading)
                _copy_props(main_sp.overlay, sp.overlay)
                sp.lens = main_sp.lens
                sp.clip_start = main_sp.clip_start
                sp.clip_end = main_sp.clip_end
            if hasattr(sp.overlay, "show_text"):
                sp.overlay.show_text = True
        self._camera_in()

    def _camera_in(self):
        """The camera of the Qt view → Blender's view."""
        sp, vp = self.space(), self.vp
        if sp is None:
            return
        with self.context():
            rv = sp.region_3d
            w, h = max(vp.width(), 2), max(vp.height(), 2)
            vm, _pm = vp.matrices(w, h)
            rv.view_perspective = "ORTHO" if getattr(vp, "ortho", False) else "PERSP"
            rv.view_distance = float(getattr(vp, "dist", 10.0))
            rv.view_matrix = vm

    # ---- cached playback: the Qt view for a while
    def suspend(self):
        self._back()                             # camera + shading → the Qt view
        bridge.preferred_view3d = None
        try:
            self.container.hide()
        except Exception:
            pass
        vp = self.vp
        try:
            vp.setFocus()                        # Space stops playback in Qt now
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.user32.SetFocus(int(vp.window().winId()))
        except Exception:
            pass
        vp.request_redraw()

    def resume(self):
        if not self.alive() or self.area() is None:
            return
        main_sp, sp = self._main_space(), self.space()
        if main_sp is not None:                  # shading changed from the Qt header during playback
            with self.context():
                _copy_props(main_sp.shading, sp.shading)
                _copy_props(main_sp.overlay, sp.overlay)
        self._camera_in()                        # the view may have been moved while playing
        bridge.preferred_view3d = _preferred
        self.fit()
        try:
            self.container.show()
        except Exception:
            pass
        self.apply_regions()

    def fit(self):
        try:
            self.container.setGeometry(self.vp.rect())
        except Exception:
            pass

    # ---- back to the Qt view
    def _back(self):
        sp = self.space()
        if sp is None:
            return
        try:
            rv = sp.region_3d
            vp = self.vp
            vp.target = rv.view_location.copy()
            vp.dist = float(rv.view_distance)
            # view_rotation / view_location / view_distance are current at once (view_matrix only after a draw)
            e = rv.view_rotation.to_euler("XYZ")
            vp.yaw, vp.pitch = e.z, min(max(e.x, 0.0001), math.pi - 0.0001)
            vp.ortho = rv.view_perspective == "ORTHO"
        except Exception as ex:
            bridge.log(f"Blender's viewport: view not taken over ({ex})", "WARNING")
        main_sp = self._main_space()             # shading / overlays changed from the Qt header meanwhile
        if main_sp is not None:
            try:
                with bridge.blender_context():
                    _copy_props(sp.shading, main_sp.shading)
                    _copy_props(sp.overlay, main_sp.overlay)
            except Exception as ex:
                bridge.log(f"Blender's viewport: shading not taken over ({ex})", "WARNING")
        try:
            vp.request_redraw()
        except Exception:
            pass

    def _hwnd_ok(self):
        if sys.platform != "win32":
            return True
        try:
            import ctypes
            return bool(ctypes.windll.user32.IsWindow(self.hwnd))
        except Exception:
            return True

    def _close_window(self):
        from . import app
        try:
            w = self.window()
            wins = list(bpy.context.window_manager.windows)
            # after a file load the pointer could belong to another window: only ours (its native window still
            # exists, never Blender's main window)
            if w is not None and app._win is not None and self._hwnd_ok() and wins and w != wins[0]:
                app._win.close_blender_window(w)
        except Exception as ex:
            bridge.log(f"Blender's viewport: closing its window failed ({ex})", "WARNING")

    def close(self, camera=True):
        if camera and not self.stale and self.alive():
            self._back()
        try:
            self.container.hide()
        except Exception:
            pass
        self._close_window()
        try:
            self.container.deleteLater()
        except Exception:
            pass

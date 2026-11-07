"""Native sculpt view: in Sculpt Mode the Qt 3D view shows Blender's own 3D viewport.

Sculpting through the offscreen view (sculpt.py) works, but every stroke goes through Python and the
offscreen drawing can't show Multires levels or Dynamic Topology. For Blender's speed and behaviour, a
helper Blender window (`wm.window_new`) with one 3D view is embedded into the Qt view while Sculpt Mode is
on (QWindow.fromWinId + createWindowContainer – the GHOST window becomes a child window). Blender draws it
and handles its mouse / keys itself (brush strokes, brush cursor, navigation of the active keyconfig,
undo). The camera goes over when entering and comes back when leaving; then the window is closed.
"""
import math
import sys

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge

_view = None            # the NativeView in use


def active(vp=None):
    return _view is not None and (vp is None or _view.vp is vp)


def enter(vp):
    """Sculpt Mode started: embed Blender's 3D view into `vp` (Qt view). False if it can't be done."""
    global _view
    if _view is not None:
        if _view.vp is vp and _view.alive():
            return True
        leave()
    try:
        _view = NativeView(vp)
        return True
    except Exception as ex:
        _view = None
        bridge.log(f"Sculpt: Blender's own 3D view could not be embedded ({ex}) – sculpting in the Qt view.",
                   "WARNING")
        return False


def leave():
    """Sculpt Mode ended: the camera back to the Qt view, the Blender window closed."""
    global _view
    v, _view = _view, None
    if v is not None:
        v.close()


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
        wm = bpy.context.window_manager
        before = {w.as_pointer() for w in wm.windows}
        native_before = set(native.ghost_windows())
        with bridge.blender_context():
            bpy.ops.wm.window_new()
        new = [w for w in wm.windows if w.as_pointer() not in before]
        if not new:
            raise RuntimeError("no new Blender window")
        self.win = new[0]
        self.ptr = self.win.as_pointer()
        hwnds = [h for h in native.ghost_windows() if h not in native_before]
        if not hwnds:
            self._close_window()
            raise RuntimeError("no native window handle")
        self.hwnd = hwnds[0]
        native.hide_windows(hwnds)                 # no flash as a separate window before it is embedded
        areas = list(self.win.screen.areas)
        self.area = max(areas, key=lambda a: a.width * a.height)
        self.area.type = "VIEW_3D"
        self._setup_space(vp)
        # embed
        self.qwin = QtGui.QWindow.fromWinId(self.hwnd)
        self.container = QtWidgets.QWidget.createWindowContainer(self.qwin, vp)
        self.container.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.fit()
        self.container.show()
        # Blender turns the tool header (and asset shelf) of a Sculpt Mode view back on while it sets up the
        # new window – hide them again once it has drawn (the Sculpt panel has those settings)
        for ms in (200, 800, 2000):
            QtCore.QTimer.singleShot(ms, self._hide_regions)
        try:
            if app._win is not None:
                app._win.activateWindow()
        except Exception:
            pass

    # ---- setup
    def _hide_regions(self):
        try:
            if not self.alive():
                return
            sp = self.area.spaces.active
        except Exception:
            return
        for attr in ("show_region_header", "show_region_tool_header", "show_region_toolbar", "show_region_ui",
                     "show_region_hud", "show_region_asset_shelf"):
            if getattr(sp, attr, False):
                try:
                    setattr(sp, attr, False)
                except Exception:
                    pass

    def _setup_space(self, vp):
        sp = self.area.spaces.active
        self._hide_regions()
        try:
            main_sp, _r = vp.space()
        except Exception:
            main_sp = None
        if main_sp is not None:
            _copy_props(main_sp.shading, sp.shading)
            _copy_props(main_sp.overlay, sp.overlay)
            sp.lens = main_sp.lens
            sp.clip_start = main_sp.clip_start
            sp.clip_end = main_sp.clip_end
        if hasattr(sp.overlay, "show_text"):
            sp.overlay.show_text = True
        # the camera of the Qt view
        rv = sp.region_3d
        w, h = max(vp.width(), 2), max(vp.height(), 2)
        vm, _pm = vp.matrices(w, h)
        rv.view_perspective = "ORTHO" if getattr(vp, "ortho", False) else "PERSP"
        rv.view_distance = float(getattr(vp, "dist", 10.0))
        rv.view_matrix = vm

    def alive(self):
        try:
            return any(w.as_pointer() == self.ptr for w in bpy.context.window_manager.windows)
        except Exception:
            return False

    def fit(self):
        try:
            self.container.setGeometry(self.vp.rect())
        except Exception:
            pass

    # ---- back to the Qt view
    def _camera_back(self):
        try:
            rv = self.area.spaces.active.region_3d
            vp = self.vp
            vp.target = rv.view_location.copy()
            vp.dist = float(rv.view_distance)
            cam = rv.view_matrix.inverted()
            e = cam.to_quaternion().to_euler("XYZ")
            vp.yaw, vp.pitch = e.z, min(max(e.x, 0.0001), math.pi - 0.0001)
            vp.ortho = rv.view_perspective == "ORTHO"
            vp.request_redraw()
        except Exception as ex:
            bridge.log(f"Sculpt: view not taken over ({ex})", "WARNING")

    def _close_window(self):
        from . import app
        try:
            if self.alive() and app._win is not None:
                app._win.close_blender_window(self.win)
        except Exception as ex:
            bridge.log(f"Sculpt: closing Blender's view failed ({ex})", "WARNING")

    def close(self):
        if self.alive():
            self._camera_back()
        try:
            self.container.hide()
        except Exception:
            pass
        self._close_window()
        try:
            self.container.deleteLater()
        except Exception:
            pass

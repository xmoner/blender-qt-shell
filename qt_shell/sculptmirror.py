"""Sculpt mirror: Blender's own 3D view drawing for Sculpt Mode cases the offscreen view can't show.

The Qt 3D view is drawn with GPUOffScreen.draw_view3d, which Blender treats as an image render: no draw
engine draws the sculpt tree then, only the evaluated mesh. That is fine for plain meshes, but Multires
levels (CCG grids – the evaluated mesh is the base mesh) and Dynamic Topology (BMesh) don't show at all.

For those, a hidden helper Blender window (hidden but not minimized) holds a 3D view that follows the Qt
view (size, view matrix, lens, shading); `screen.screenshot_area` draws that area the normal way – with
the sculpt tree – and the picture replaces the offscreen one. The helper is closed when Sculpt Mode ends.
"""
import os
import sys
import time
import tempfile

import bpy
from PySide6 import QtGui

from . import bridge

_mirror = None              # the Mirror in use (one helper window for the main 3D view)
_failed_t = 0.0             # last failure – don't retry every frame
MARGIN = 48                 # px around the picture in the helper view (cut away)


def wanted(vp):
    """True when the active sculpt object needs Blender's own drawing to be seen."""
    try:
        if bpy.context.mode != "SCULPT" or getattr(vp, "camera_view", False):
            return False
        ob = bpy.context.active_object
        if ob is None or ob.type != "MESH":
            return False
        if getattr(ob, "use_dynamic_topology_sculpting", False):
            return True
        for m in ob.modifiers:
            if m.type == "MULTIRES" and m.show_viewport and m.total_levels > 0 and m.sculpt_levels > 0:
                return True
    except Exception:
        return False
    return False


def frame(vp, w, h, vm, space):
    """The mirror's picture for this frame (QImage, w×h) or None (then the offscreen picture is used)."""
    global _mirror, _failed_t
    if not wanted(vp):
        return None
    if time.monotonic() - _failed_t < 5.0:
        return None
    try:
        if _mirror is not None and _mirror.vp is not vp and _mirror.alive():
            return None                       # one helper window: it serves the view that asked first
        if _mirror is None or not _mirror.alive():
            _mirror = Mirror(vp)
        img = _mirror.shot(vp, w, h, vm, space)
        if img is None:
            vp._dirty = True              # Blender takes the new window size in its next loop – try again
        return img
    except Exception as ex:
        _failed_t = time.monotonic()
        bridge.log(f"Sculpt view: Blender's drawing not available ({ex}) – the Qt view shows the base mesh.",
                   "WARNING")
        release()
        return None


def release():
    """Closes the helper window (leaving Sculpt Mode, Qt Shell closing)."""
    global _mirror
    m, _mirror = _mirror, None
    if m is not None:
        m.close()


class Mirror:
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
            raise RuntimeError("no helper window")
        self.win = new[0]
        self.ptr = self.win.as_pointer()
        self.hwnds = [h for h in native.ghost_windows() if h not in native_before]
        # hidden, not minimized: Blender skips minimized windows
        native.hide_windows(self.hwnds)
        try:
            if app._win is not None:
                app._win.activateWindow()          # the new Blender window took the focus
        except Exception:
            pass
        areas = list(self.win.screen.areas)
        self.area = max(areas, key=lambda a: a.width * a.height)
        self.area.type = "VIEW_3D"
        sp = self.area.spaces.active
        for attr in ("show_region_header", "show_region_tool_header", "show_region_toolbar", "show_region_ui",
                     "show_region_hud", "show_region_asset_shelf"):
            if hasattr(sp, attr):
                try:
                    setattr(sp, attr, False)
                except Exception:
                    pass
        sp.show_gizmo = False
        self.path = os.path.join(tempfile.gettempdir(), f"qtshell_sculptview_{os.getpid()}.png")
        self._size = None
        self.shots = 0

    def alive(self):
        try:
            return any(w.as_pointer() == self.ptr for w in bpy.context.window_manager.windows) and \
                self.area.type == "VIEW_3D"
        except Exception:
            return False

    def _resize(self, w, h):
        """Window client size = the Qt view's picture size (the area is the whole window)."""
        if self._size == (w, h) or sys.platform != "win32" or not self.hwnds:
            return
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_uint]
        for hwnd in self.hwnds:
            wr, cr = wintypes.RECT(), wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(wr))
            user32.GetClientRect(hwnd, ctypes.byref(cr))
            fw = (wr.right - wr.left) - (cr.right - cr.left)
            fh = (wr.bottom - wr.top) - (cr.bottom - cr.top)
            # SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE
            user32.SetWindowPos(hwnd, None, 0, 0, w + fw, h + fh, 0x0002 | 0x0004 | 0x0010)
        self._size = (w, h)

    def _sync(self, vp, vm, space):
        sp = self.area.spaces.active
        # shading and overlays like the Qt view's hidden 3D view
        for src, dst in ((space.shading, sp.shading), (space.overlay, sp.overlay)):
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
        ov = sp.overlay
        for attr, val in (("show_text", False), ("show_stats", False), ("show_cursor", False)):
            if hasattr(ov, attr):
                try:
                    setattr(ov, attr, val)
                except Exception:
                    pass
        sp.lens = space.lens
        sp.clip_start = space.clip_start
        sp.clip_end = space.clip_end
        rv = sp.region_3d
        ortho = bool(getattr(vp, "ortho", False))
        rv.view_perspective = "ORTHO" if ortho else "PERSP"
        rv.view_distance = float(getattr(vp, "dist", 10.0))
        rv.view_matrix = vm

    def shot(self, vp, w, h, vm, space):
        # the helper's view is MARGIN px bigger on every side and the middle is cut out: Blender draws
        # small tabs of hidden regions (toolbar / sidebar arrows) and maybe a tool header at the edges
        W, H = w + 2 * MARGIN, h + 2 * MARGIN
        self._resize(W, H)
        region = next((r for r in self.area.regions if r.type == "WINDOW"), None)
        if region is None:
            return None
        if abs(region.width - W) > 2 or abs(region.height - H) > 2:
            return None                       # Blender hasn't taken the new window size yet
        self._sync(vp, vm, space)
        sp = self.area.spaces.active
        # Blender's lens covers the larger side: the same view through a bigger region = a shorter lens
        sp.lens = space.lens * (w / W if w >= h else h / H)
        for attr in ("show_region_header", "show_region_tool_header", "show_region_toolbar", "show_region_ui"):
            if getattr(sp, attr, False):
                try:
                    setattr(sp, attr, False)
                except Exception:
                    pass
        # the screenshot redraws tagged windows, then reads the front buffer – one frame behind: tag the
        # area (strokes, the new view) and take two more pictures after it, so the picture catches up
        self.area.tag_redraw()
        try:
            vp._extra_frames = max(getattr(vp, "_extra_frames", 0), 2)
        except Exception:
            pass
        with bpy.context.temp_override(window=self.win, screen=self.win.screen, area=self.area, region=region):
            r = bpy.ops.screen.screenshot_area(filepath=self.path)
        if "FINISHED" not in r:
            return None
        img = QtGui.QImage(self.path)
        if img.isNull():
            return None
        # the screenshot redraws the window and reads its front buffer – one frame behind (double
        # buffering), and the first pictures of a new window are leftovers: skip those
        self.shots += 1
        if self.shots < 3:
            return None
        img = img.convertToFormat(QtGui.QImage.Format_RGBX8888)
        if img.width() < W - 2 or img.height() < H - 2:
            return None
        return img.copy(MARGIN, MARGIN, w, h)

    def close(self):
        try:
            if not self.alive():
                return
            from . import app
            if app._win is not None:
                app._win.close_blender_window(self.win)     # closes + restores the GPU context
        except Exception as ex:
            bridge.log(f"Sculpt view: closing the helper window failed ({ex})", "WARNING")
        try:
            os.remove(self.path)
        except Exception:
            pass

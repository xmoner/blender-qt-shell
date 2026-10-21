"""3D viewport in Qt.

Blender renders the scene into a GPUOffScreen (draw_view3d) with our camera matrices; the image is
read into numpy and shown as a QImage. Navigation, selection and G/R/S transforms run in Qt.
"""
import math
import time
from collections import deque

import bpy
import gpu
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, editmesh, gizmo, keying, keymap, playcache, posetransform, theme, wirepick
from . import icons

DEG = math.pi / 180.0

# on national keyboards (CZ/SK/DE/FR) the top number row types characters instead of digits
_LAYOUT_DIGITS = {"+": 1, "ě": 2, "š": 3, "č": 4, "ř": 5, "ž": 6, "ý": 7, "á": 8, "í": 9, "é": 0,
                  "ľ": 2, "ť": 5, "&": 1, "\"": 3, "'": 4, "(": 5, "à": 0, "ç": 9, "è": 7, "_": 8}


# names of the axis-aligned views (rotating from them switches to a "User" view)
_AXIS_VIEWS = ("Front", "Back", "Right", "Left", "Top", "Bottom")


def digit_of(ev):
    """Digit of the physical key (like Blender – independent of the keyboard layout), otherwise None."""
    k = ev.key()
    k0 = int(QtCore.Qt.Key_0)
    if k0 <= int(k) <= k0 + 9:
        return int(k) - k0
    vk = ev.nativeVirtualKey()
    if 0x30 <= vk <= 0x39 and QtCore.QSysInfo.productType() == "windows":
        return vk - 0x30
    if 0x60 <= vk <= 0x69 and QtCore.QSysInfo.productType() == "windows":
        return vk - 0x60   # VK_NUMPAD0..9
    t = ev.text().lower()
    return _LAYOUT_DIGITS.get(t)


def _clip_segment_view(a, b, near):
    """Clips a segment (in view space) by the plane z = -near. Returns (a, b) or None."""
    za, zb = -a.z, -b.z
    if za < near and zb < near:
        return None
    if za < near:
        t = (near - za) / (zb - za)
        a = a.lerp(b, t)
    elif zb < near:
        t = (near - zb) / (za - zb)
        b = b.lerp(a, t)
    return a, b


class Viewport(QtWidgets.QWidget):
    status = QtCore.Signal(str)
    selection_edited = QtCore.Signal()

    def __init__(self, hub, prefs=None):
        super().__init__()
        self.hub = hub
        self.prefs = prefs
        self.setMinimumSize(200, 150)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent)
        # view
        self.target = Vector((0.0, 0.0, 0.0))
        self.dist = 15.0
        self.yaw = 50 * DEG
        self.pitch = 65 * DEG
        self.ortho = False
        self.camera_view = False
        self.view_name = "User Perspective"
        # render
        self._off = None
        self._image = None
        self._dirty = True
        self._fps_samples = deque(maxlen=120)   # (time, frame) of each newly shown frame during playback
        self._fps_last_frame = None
        self._extra_frames = 0
        self._draw_kwargs = None
        self._failed = None
        self.show_boxes = False
        self.show_grid = False
        # interaction
        self._nav = None
        self._navg = None          # press on the navigation gizmo (axis ball / its buttons)
        self._nav_hover = None
        self._last = None
        self._press_pos = None
        self._box = None
        self._modal = None
        self._numeric = ""
        self.area = None            # ViewportArea when the viewport is one of several views
        # transform tools (toolbar + gizmo)
        self._gz_hover = None
        self._gizmo_pivot_cache = None
        self.tools = gizmo.tool_state(hub)
        self.toolbar = gizmo.Toolbar(self)
        self.tools.changed.connect(self.update)

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)
        hub.data_changed.connect(self.request_redraw)
        hub.frame_changed.connect(lambda _f: self.request_redraw())
        hub.selection_changed.connect(self.update)
        hub.selection_changed.connect(lambda: gizmo.invalidate(self))
        hub.data_changed.connect(lambda: gizmo.invalidate(self))
        self.selection_edited.connect(lambda: (gizmo.invalidate(self), self.update()))
        hub.file_loaded.connect(self._on_file_loaded)

    # ------------------------------------------------------------ helpers
    def space(self):
        found = bridge.ensure_view3d()
        if not found:
            return None, None
        _win, area, region = found
        return area.spaces.active, region

    def shading(self):
        sp, _r = self.space()
        return sp.shading.type if sp else "SOLID"

    def set_shading(self, kind):
        sp, _r = self.space()
        if sp:
            sp.shading.type = kind
            self.redraw_scene()          # the shading is shared by all views

    def request_redraw(self, extra=0):
        self._dirty = True
        self._extra_frames = max(self._extra_frames, extra)

    def redraw_scene(self):
        """The scene changed (not just this view's camera): redraws every view."""
        if self.area is not None:
            self.area.request_redraw()
        else:
            self.request_redraw()

    def _on_file_loaded(self):
        self.camera_view = False
        self.request_redraw()

    def view_rotation(self):
        return Quaternion((0, 0, 1), self.yaw) @ Quaternion((1, 0, 0), self.pitch)

    def fov(self, w, h):
        sp, _r = self.space()
        lens = sp.lens if sp else 50.0
        f_large = 2 * math.atan(36.0 / lens)
        if w >= h:
            return 2 * math.atan(math.tan(f_large / 2) * h / max(w, 1))  # vertical
        return f_large

    def clip(self):
        sp, _r = self.space()
        if sp:
            return max(sp.clip_start, 1e-4), sp.clip_end
        return 0.01, 1000.0

    def matrices(self, w, h):
        """(view_matrix, projection_matrix) for size w×h."""
        scene = bpy.context.scene
        if self.camera_view and scene.camera is not None:
            cam = scene.camera
            view = cam.matrix_world.normalized().inverted()
            try:
                proj = cam.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(), x=w, y=h)
                return view, proj
            except Exception:
                pass
        rot = self.view_rotation().to_matrix().to_4x4()
        near, far = self.clip()
        aspect = w / max(h, 1)
        fov_y = self.fov(w, h)
        if self.ortho:
            hh = self.dist * math.tan(fov_y / 2)
            hw = hh * aspect
            cam = Matrix.Translation(self.target) @ rot @ Matrix.Translation((0, 0, far / 2))
            n, f = 0.0, far
            proj = Matrix(((1 / hw, 0, 0, 0), (0, 1 / hh, 0, 0),
                           (0, 0, -2 / (f - n), -(f + n) / (f - n)), (0, 0, 0, 1)))
        else:
            cam = Matrix.Translation(self.target) @ rot @ Matrix.Translation((0, 0, self.dist))
            fy = 1 / math.tan(fov_y / 2)
            proj = Matrix(((fy / aspect, 0, 0, 0), (0, fy, 0, 0),
                           (0, 0, (far + near) / (near - far), 2 * far * near / (near - far)),
                           (0, 0, -1, 0)))
        return cam.inverted(), proj

    def project(self, co, mats=None):
        w, h = self.width(), self.height()
        vm, pm = mats or self.matrices(w, h)
        p = pm @ vm @ Vector((co[0], co[1], co[2], 1.0))
        if p.w <= 1e-6:
            return None
        return QtCore.QPointF((p.x / p.w + 1) * 0.5 * w, (1 - p.y / p.w) * 0.5 * h)

    def ray(self, x, y):
        w, h = self.width(), self.height()
        vm, pm = self.matrices(w, h)
        inv = (pm @ vm).inverted()
        nx, ny = 2 * x / w - 1, 1 - 2 * y / h
        a = inv @ Vector((nx, ny, -1, 1))
        b = inv @ Vector((nx, ny, 1, 1))
        a = a.xyz / a.w
        b = b.xyz / b.w
        return a, (b - a).normalized()

    def view_vectors(self):
        """(right, up, forward) of the camera in world space."""
        if self.camera_view and bpy.context.scene.camera:
            m = bpy.context.scene.camera.matrix_world.to_3x3().normalized()
        else:
            m = self.view_rotation().to_matrix()
        return m.col[0].normalized(), m.col[1].normalized(), -m.col[2].normalized()

    def pixel_size_at(self, point):
        w, h = self.width(), self.height()
        fov_y = self.fov(w, h)
        if self.ortho and not self.camera_view:
            return 2 * self.dist * math.tan(fov_y / 2) / max(h, 1)
        vm, _pm = self.matrices(w, h)
        depth = max(-(vm @ point).z, 1e-3)
        return 2 * depth * math.tan(fov_y / 2) / max(h, 1)

    def leave_camera(self):
        if self.camera_view:
            cam = bpy.context.scene.camera
            if cam:
                m = cam.matrix_world.normalized()
                fwd = -m.to_3x3().col[2]
                self.target = m.translation + fwd * self.dist
                e = m.to_quaternion().to_euler("XYZ")
                self.yaw, self.pitch = e.z, min(max(e.x, 0.0001), math.pi - 0.0001)
            self.camera_view = False
            self.view_name = "User Perspective"

    # ------------------------------------------------------------ render
    def _tick(self):
        if not self.isVisible() or bridge.is_rendering():
            return
        if getattr(self.hub, "playing", False):
            return   # during playback every frame is drawn by render_now()
        if self._dirty or self._extra_frames > 0:
            sh = self.shading()
            self._dirty = False
            if self._extra_frames > 0:
                self._extra_frames -= 1
            elif sh in ("MATERIAL", "RENDERED"):
                self._extra_frames = 16 if sh == "MATERIAL" else 64  # progressive refinement
            self.render_frame()
            self.update()

    def render_frame(self):
        scale = getattr(self.prefs, "viewport_scale", 1.0) if self.prefs else 1.0
        dpr = self.devicePixelRatioF() * scale
        w = max(2, min(4096, int(self.width() * dpr)))
        h = max(2, min(4096, int(self.height() * dpr)))
        space, region = self.space()
        if space is None:
            self._failed = "No 3D area found in Blender."
            return
        try:
            if self._off is None or self._off.width != w or self._off.height != h:
                if self._off is not None:
                    self._off.free()
                self._off = gpu.types.GPUOffScreen(w, h)
            vm, pm = self.matrices(w, h)
            ctx = bpy.context
            transparent = space.shading.type in ("SOLID", "WIREFRAME")
            self._draw(ctx.scene, ctx.view_layer, space, region, vm, pm, transparent)
            img = self._read_image(w, h, dpr, transparent)
            self._image = img
            self._geo_frame = False
            if getattr(self.hub, "playing", False):
                f = ctx.scene.frame_current
                if f != self._fps_last_frame:
                    self._fps_last_frame = f
                    self._fps_samples.append((time.perf_counter(), f))
            self._img_transparent = transparent and self._draw_kwargs.get("draw_background") is False
            self._failed = None
            if self._modal is None:
                playcache.store(self, ctx.scene.frame_current, img, self._img_transparent)
        except Exception as ex:
            self._failed = f"Viewport render failed: {ex}"

    def _offscreen_size(self):
        scale = getattr(self.prefs, "viewport_scale", 1.0) if self.prefs else 1.0
        dpr = self.devicePixelRatioF() * scale
        w = max(2, min(4096, int(self.width() * dpr)))
        h = max(2, min(4096, int(self.height() * dpr)))
        if self._off is None or self._off.width != w or self._off.height != h:
            if self._off is not None:
                self._off.free()
            self._off = gpu.types.GPUOffScreen(w, h)
        return w, h, dpr

    def _read_image(self, w, h, dpr, transparent):
        """The offscreen's pixels as a QImage."""
        with self._off.bind():
            fb = gpu.state.active_framebuffer_get()
            buf = fb.read_color(0, 0, w, h, 4, 0, "UBYTE")
        try:
            arr = np.frombuffer(buf, dtype=np.uint8)
        except TypeError:
            arr = np.asarray(buf.to_list(), dtype=np.uint8)
        fmt = QtGui.QImage.Format_RGBA8888_Premultiplied if transparent else QtGui.QImage.Format_RGBX8888
        # Qt owns the image memory; numpy flips the rows (GPU rows are bottom-up) while copying
        # straight into it – one copy per frame, and no Qt image pointing at freed numpy memory.
        img = QtGui.QImage(w, h, fmt)
        dst = np.frombuffer(img.bits(), dtype=np.uint8, count=h * img.bytesPerLine())
        dst = dst.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)
        dst[:] = arr.reshape(h, w, 4)[::-1]
        img.setDevicePixelRatio(dpr)
        return img

    def geo_cache_usable(self):
        """Geometry-cache playback draws solid shading only."""
        space, _r = self.space()
        return space is not None and space.shading.type == "SOLID"

    def show_geo(self, frame):
        """Cached playback from the geometry cache: draws the stored geometry from the current camera."""
        from . import geocache
        if not self.isVisible() or not self.geo_cache_usable():
            return False
        space, _r = self.space()
        try:
            w, h, dpr = self._offscreen_size()
            vm, pm = self.matrices(w, h)
            if not geocache.draw(self._off, frame, vm, pm, space, dpr):
                return False
            self._image = self._read_image(w, h, dpr, True)
            self._img_transparent = True
            self._geo_frame = True              # Blender's floor grid isn't in the picture → Qt draws it
        except Exception as ex:
            bridge.log(f"Geometry cache draw: {ex}", "WARNING")
            return False
        self._dirty = False
        self._extra_frames = 0
        if frame != self._fps_last_frame:
            self._fps_last_frame = frame
            self._fps_samples.append((time.perf_counter(), frame))
        self.repaint()
        return True

    def _draw(self, scene, view_layer, space, region, vm, pm, transparent):
        attempts = []
        if self._draw_kwargs is not None:
            kw = dict(self._draw_kwargs)
            if "draw_background" in kw:
                kw["draw_background"] = not transparent
            attempts.append(kw)
        attempts += [{"do_color_management": True, "draw_background": not transparent},
                     {"do_color_management": True}, {}]
        last = None
        for kw in attempts:
            try:
                self._off.draw_view3d(scene, view_layer, space, region, vm, pm, **kw)
                self._draw_kwargs = kw
                return
            except TypeError as ex:
                last = ex
        raise last

    # ------------------------------------------------------------ drawing in Qt
    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        r = self.rect()
        grad = QtGui.QLinearGradient(0, 0, 0, r.height())
        grad.setColorAt(0, QtGui.QColor("#454545"))
        grad.setColorAt(1, QtGui.QColor("#333333"))
        p.fillRect(r, QtGui.QBrush(grad))
        mats = self.matrices(self.width(), self.height())
        if ((self.show_grid or getattr(self, "_geo_frame", False)) and self._image is not None
                and getattr(self, "_img_transparent", False)):
            self._paint_grid(p, mats)
        if self._image is not None:
            p.drawImage(r, self._image)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        if self.show_boxes:
            self._paint_selection(p, mats)
        if self._modal is None and not getattr(self.hub, "playing", False):
            try:
                gizmo.paint(self, p, self.tools.tool, self._gz_hover)
            except Exception as ex:          # never break the viewport because of the gizmo
                bridge.log(f"Gizmo: {ex}", "WARNING")
        self._paint_gizmo(p)
        self._paint_text(p)
        try:
            from . import api
            api.paint_overlays(self, p)     # overlays registered through qt_shell.api
        except Exception:
            pass
        if self.area is not None and self.area.active is self and len(self.area.visible_views()) > 1:
            p.setBrush(QtCore.Qt.NoBrush)
            p.setPen(QtGui.QPen(QtGui.QColor("#5680c2"), 2))
            p.drawRect(QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1))
        if self._box:
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1, QtCore.Qt.DashLine))
            p.setBrush(QtGui.QColor(255, 255, 255, 20))
            p.drawRect(QtCore.QRectF(self._box[0], self._box[1]).normalized())
        p.end()

    def _paint_grid(self, p, mats):
        if self.camera_view:
            return
        vm, pm = mats
        near, _far = self.clip()
        w, h = self.width(), self.height()
        step = 10 ** math.floor(math.log10(max(self.dist, 0.1) / 2))
        n = 30
        cx = round(self.target.x / step) * step
        cy = round(self.target.y / step) * step

        def seg(a, b, color, width=1):
            va = vm @ a
            vb = vm @ b
            res = _clip_segment_view(va, vb, near * 1.5)
            if res is None:
                return
            pts = []
            for v in res:
                c = pm @ Vector((v.x, v.y, v.z, 1.0))
                if c.w <= 1e-6:
                    return
                pts.append(QtCore.QPointF((c.x / c.w + 1) * 0.5 * w, (1 - c.y / c.w) * 0.5 * h))
            p.setPen(QtGui.QPen(color, width))
            p.drawLine(pts[0], pts[1])

        # in front/side ortho views the grid is seen edge-on → skip it
        if self.ortho and abs(math.cos(self.pitch)) < 0.05:
            return
        minor = QtGui.QColor(255, 255, 255, 22)
        major = QtGui.QColor(255, 255, 255, 40)
        for i in range(-n, n + 1):
            x = cx + i * step
            y = cy + i * step
            col_x = major if abs(round(x / step)) % 10 == 0 else minor
            col_y = major if abs(round(y / step)) % 10 == 0 else minor
            if abs(x) > 1e-9:
                seg(Vector((x, cy - n * step, 0)), Vector((x, cy + n * step, 0)), col_x)
            if abs(y) > 1e-9:
                seg(Vector((cx - n * step, y, 0)), Vector((cx + n * step, y, 0)), col_y)
        seg(Vector((cx - n * step, 0, 0)), Vector((cx + n * step, 0, 0)), QtGui.QColor(220, 70, 80, 180), 1.5)
        seg(Vector((0, cy - n * step, 0)), Vector((0, cy + n * step, 0)), QtGui.QColor(120, 200, 60, 180), 1.5)

    def _paint_selection(self, p, mats):
        ctx = bpy.context
        try:
            active = ctx.view_layer.objects.active
            sel = list(ctx.selected_objects)
        except Exception:
            return
        edges = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7))
        for ob in sel:
            color = QtGui.QColor("#ffcc66") if ob == active else QtGui.QColor("#f08a24")
            mw = ob.matrix_world
            corners = [mw @ Vector(c) for c in ob.bound_box]
            pts = [self.project(c, mats) for c in corners]
            size = (corners[6] - corners[0]).length if len(corners) == 8 else 0
            if size > 1e-6 and all(pts):
                p.setPen(QtGui.QPen(color, 1.2))
                for a, b in edges:
                    p.drawLine(pts[a], pts[b])
            o = self.project(mw.translation, mats)
            if o:
                p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 1))
                p.setBrush(color)
                p.drawEllipse(o, 3.5, 3.5)
                p.setBrush(QtCore.Qt.NoBrush)

    # ------------------------------------------------------------ navigation gizmo (like Blender 5.2)
    # axis → view shown when the axis ball is clicked (Blender: click X = look from +X = Right)
    _AXIS_VIEW = {"X": "RIGHT", "-X": "LEFT", "Y": "BACK", "-Y": "FRONT", "Z": "TOP", "-Z": "BOTTOM"}
    _OPPOSITE = {"RIGHT": "LEFT", "LEFT": "RIGHT", "BACK": "FRONT", "FRONT": "BACK", "TOP": "BOTTOM",
                 "BOTTOM": "TOP"}

    def _nav_geom(self):
        R = theme.px(40)
        c = QtCore.QPointF(self.width() - R - theme.px(12), R + theme.px(10))
        return c, R

    def _nav_items(self):
        """[(kind, id, centre, radius, depth)] – axis balls (back to front) and the buttons below."""
        c, R = self._nav_geom()
        right, up, fwd = self.view_vectors()
        arm = R * 0.78
        items = []
        for name, v in (("X", Vector((1, 0, 0))), ("Y", Vector((0, 1, 0))), ("Z", Vector((0, 0, 1)))):
            for sign in (1, -1):
                w = v * sign
                pc = c + QtCore.QPointF(w.dot(right) * arm, -w.dot(up) * arm)
                key = name if sign > 0 else "-" + name
                items.append(("axis", key, pc, theme.px(9) if sign > 0 else theme.px(8), w.dot(fwd)))
        items.sort(key=lambda t: -t[4])            # farther first
        r = theme.px(12)
        y = c.y() + R + theme.px(8) + r
        for k in ("zoom", "pan", "camera", "persp"):
            items.append(("button", k, QtCore.QPointF(c.x(), y), r, 0.0))
            y += 2 * r + theme.px(5)
        return items

    def _nav_hit(self, pos):
        """('axis', 'X' | '-Y' …) / ('button', 'zoom' | 'pan' | 'camera' | 'persp') / ('ball', None) / None"""
        for kind, key, pc, r, _d in reversed(self._nav_items()):        # front-most first
            d = pc - pos
            if d.x() * d.x() + d.y() * d.y() <= (r * 1.25) ** 2:
                return kind, key
        c, R = self._nav_geom()
        d = pos - c
        if d.x() * d.x() + d.y() * d.y() <= (R + theme.px(4)) ** 2:
            return "ball", None
        return None

    def _paint_gizmo(self, p):
        c, R = self._nav_geom()
        hov = self._nav_hover
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        pressed = self._navg["hit"] if self._navg else None
        if (hov is not None and hov[0] in ("ball", "axis")) or (pressed and pressed[0] in ("ball", "axis")):
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(255, 255, 255, 38))       # Blender shows the circle on hover
            p.drawEllipse(c, R + theme.px(4), R + theme.px(4))
        colors = {"X": QtGui.QColor("#ff3352"), "Y": QtGui.QColor("#8bdc00"), "Z": QtGui.QColor("#2890ff")}
        f = p.font()
        f.setBold(True)
        f.setPixelSize(theme.fs(10))
        p.setFont(f)
        for kind, key, pc, r, _depth in self._nav_items():
            if kind == "axis":
                col = colors[key[-1]]
                neg = key.startswith("-")
                hot = hov == ("axis", key)
                if not neg:
                    p.setPen(QtGui.QPen(col, theme.px(2)))
                    p.drawLine(c, pc)
                p.setPen(QtGui.QPen(col.lighter(130) if hot else col, max(1, theme.px(1.5))))
                if neg:
                    fill = QtGui.QColor(col)
                    fill.setAlpha(170 if hot else 70)
                    p.setBrush(fill)
                else:
                    p.setBrush(col.lighter(125) if hot else col)
                p.drawEllipse(pc, r, r)
                if not neg or hot:                   # negative axes show their name on hover
                    p.setPen(QtGui.QColor("#000000") if not neg else QtGui.QColor("#ffffff"))
                    p.drawText(QtCore.QRectF(pc.x() - r - 4, pc.y() - r, 2 * r + 8, 2 * r),
                               QtCore.Qt.AlignCenter, key)
            else:
                hot = hov == ("button", key) or pressed == ("button", key)
                active = (key == "camera" and self.camera_view) or (key == "persp" and not self.ortho)
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(QtGui.QColor(255, 255, 255, 70) if hot else QtGui.QColor(0, 0, 0, 90))
                p.drawEllipse(pc, r, r)
                p.setPen(QtGui.QColor("#ffffff") if (hot or active) else QtGui.QColor("#cfcfcf"))
                iname = {"zoom": "zoom", "pan": "pan", "camera": "camera",
                         "persp": "orthographic" if self.ortho else "perspective"}[key]
                pm = icons.pixmap(iname, theme.px(14), color="#ffffff" if (hot or active) else "#d0d0d0")
                if pm is not None:
                    s_ = theme.px(14)
                    p.drawPixmap(QtCore.QRectF(pc.x() - s_ / 2, pc.y() - s_ / 2, s_, s_), pm, QtCore.QRectF(pm.rect()))
                    continue
                glyph = {"zoom": "🔍", "pan": "✋", "camera": "🎥", "persp": "▦" if self.ortho else "⬚"}[key]
                gf = QtGui.QFont(f)
                gf.setBold(False)
                gf.setPixelSize(theme.fs(12))
                p.setFont(gf)
                p.drawText(QtCore.QRectF(pc.x() - r, pc.y() - r, 2 * r, 2 * r), QtCore.Qt.AlignCenter, glyph)
                p.setFont(f)

    def _nav_tooltip(self, hit):
        if hit is None:
            return ""
        kind, key = hit
        if kind == "axis":
            return (f"Click: {self._AXIS_VIEW[key].title()} view (click the aligned axis again: opposite side)"
                    " · drag: orbit")
        if kind == "ball":
            return "Drag to orbit the view · click an axis to look along it"
        return keymap.render({"zoom": "Drag up / down to zoom", "pan": "Drag to pan the view",
                              "camera": "Toggle the camera view ({view3d.view_camera})",
                              "persp": "Toggle perspective / orthographic ({view3d.view_persp})"}[key])

    def _nav_click(self, hit):
        kind, key = hit
        if kind == "axis":
            view = self._AXIS_VIEW[key]
            cur = self.view_name.split(" ")[0].upper()
            if cur == view and not self.camera_view:
                view = self._OPPOSITE[view]          # like Blender: clicking the aligned axis flips the view
            self.set_view(view)
        elif key == "camera":
            self.set_view("CAMERA")
        elif key == "persp":
            self.toggle_ortho()
        self.update()

    # ------------------------------------------------------------ playback FPS (like Blender)
    def playback_changed(self, playing):
        self._fps_samples.clear()
        self._fps_last_frame = None
        if not playing:
            self.request_redraw()   # full quality (progressive refinement) again after playback
        self.update()

    def show_cached(self, frame):
        """Playback from the cache: shows the stored image of frame without evaluating the scene."""
        hit = playcache.lookup(self, frame)
        if hit is None:
            return False
        self._image, self._img_transparent = hit
        self._geo_frame = False
        self._dirty = False
        self._extra_frames = 0
        if frame != self._fps_last_frame:
            self._fps_last_frame = frame
            self._fps_samples.append((time.perf_counter(), frame))
        self.repaint()
        return True

    def render_now(self):
        """Draws the current frame immediately (used by playback)."""
        if not self.isVisible() or bridge.is_rendering():
            return
        self._dirty = False
        self._extra_frames = 0
        self.render_frame()
        self.repaint()

    def playback_fps(self):
        """Frames actually shown per second over the last second of playback, or None."""
        s = self._fps_samples
        if len(s) < 2:
            return None
        now = s[-1][0]
        recent = [t for t, _f in s if now - t <= 1.0]
        if len(recent) < 2 or recent[-1] - recent[0] <= 0:
            return None
        return (len(recent) - 1) / (recent[-1] - recent[0])

    def _paint_text(self, p):
        ctx = bpy.context
        p.setPen(QtGui.QColor("#e0e0e0"))
        f = p.font()
        f.setBold(False)
        f.setPixelSize(theme.fs(12))
        p.setFont(f)
        name = self.view_name
        if self.camera_view:
            name = "Camera Perspective"
        elif self.ortho and "ortho" not in name.lower():
            name = name.replace("Perspective", "Orthographic") if "Perspective" in name else name + " Orthographic"
        playing = getattr(self.hub, "playing", False)
        if playing:
            # like Blender: during playback the first line shows the real frame rate,
            # red when it is below the scene frame rate
            try:
                r = ctx.scene.render
                target = r.fps / (r.fps_base or 1.0)
            except Exception:
                target = 0.0
            fps = self.playback_fps()
            if fps is None:
                text = "fps: –"
            else:
                text = f"fps: {fps:.1f}" if fps < 100 else f"fps: {fps:.0f}"
            slow = fps is not None and target > 0 and fps < target * 0.95
            if slow:
                p.setPen(QtGui.QColor("#ff5a5a"))
            p.drawText(12, 20, f"{text}  (target {target:.4g})" if slow else text)
            p.setPen(QtGui.QColor("#e0e0e0"))
        else:
            p.drawText(12, 20, name)
        try:
            ob = ctx.view_layer.objects.active
            coll = ctx.view_layer.active_layer_collection.collection.name
            shown = getattr(self.hub, "display_frame", None)
            p.drawText(12, 38, f"({shown if shown is not None else ctx.scene.frame_current}) {coll} | "
                               f"{ob.name if ob else '—'}")
        except Exception:
            pass
        if self._modal:
            p.setPen(QtGui.QColor("#ffffff"))
            p.drawText(12, self.height() - 14, self._modal_text())
        if self._failed:
            p.setPen(QtGui.QColor("#ff7070"))
            p.drawText(QtCore.QRectF(self.rect()).adjusted(20, 50, -20, -20),
                       int(QtCore.Qt.AlignCenter.value) | int(QtCore.Qt.TextWordWrap.value), self._failed)

    # ------------------------------------------------------------ navigation
    def frame_objects(self, objs):
        pts = []
        for ob in objs:
            mw = ob.matrix_world
            pts.extend(mw @ Vector(c) for c in ob.bound_box)
            pts.append(mw.translation)
        self.frame_points(pts)

    def frame_points(self, pts):
        if not pts:
            return
        lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
        hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
        self.leave_camera()
        self.target = (lo + hi) / 2
        radius = max((hi - lo).length / 2, 0.5)
        fov_y = self.fov(self.width(), self.height())
        self.dist = radius / math.sin(fov_y / 2) * 1.1
        self.request_redraw()

    def frame_selected(self):
        if bpy.context.mode == "POSE":
            pts = posetransform.bounds_points()
            if pts:
                self.frame_points(pts)
                return
        sel = list(bpy.context.selected_objects)
        self.frame_objects(sel or list(bpy.context.visible_objects))

    def frame_all(self):
        self.frame_objects(list(bpy.context.visible_objects))

    def set_view(self, name):
        self.leave_camera()
        views = {
            "FRONT": (0.0, 90 * DEG, "Front"), "BACK": (180 * DEG, 90 * DEG, "Back"),
            "RIGHT": (90 * DEG, 90 * DEG, "Right"), "LEFT": (-90 * DEG, 90 * DEG, "Left"),
            "TOP": (0.0, 0.0001, "Top"), "BOTTOM": (0.0, 180 * DEG - 0.0001, "Bottom"),
        }
        if name == "CAMERA":
            if bpy.context.scene.camera is None:
                self.status.emit("The scene has no active camera.")
                return
            self.camera_view = not self.camera_view
            self.request_redraw()
            return
        yaw, pitch, label = views[name]
        self.yaw, self.pitch = yaw, pitch
        self.ortho = True
        self.view_name = f"{label} Orthographic"
        self.request_redraw()

    def toggle_ortho(self):
        self.leave_camera()
        self.ortho = not self.ortho
        self.view_name = "User Orthographic" if self.ortho else "User Perspective"
        self.request_redraw()

    def _orbit(self, dx, dy):
        self.leave_camera()
        if self.view_name.startswith(_AXIS_VIEWS):
            self.view_name = "User Orthographic" if self.ortho else "User Perspective"
        self.yaw -= dx * 0.008
        self.pitch = min(max(self.pitch - dy * 0.008, 0.0001), math.pi - 0.0001)
        self.request_redraw()

    def orbit_step(self, dyaw, dpitch):
        """Rotates the view by a fixed angle (numpad 2/4/6/8/9 like in Blender)."""
        self.leave_camera()
        if self.view_name.startswith(_AXIS_VIEWS):
            self.view_name = "User Orthographic" if self.ortho else "User Perspective"
        self.yaw += dyaw
        self.pitch = min(max(self.pitch + dpitch, 0.0001), math.pi - 0.0001)
        self.request_redraw()
        self.update()

    def _pan(self, dx, dy):
        self.leave_camera()
        right, up, _f = self.view_vectors()
        s = self.pixel_size_at(self.target)
        self.target += (-right * dx + up * dy) * s
        self.request_redraw()

    def _zoom(self, factor):
        self.leave_camera()
        self.dist = min(max(self.dist * factor, 0.01), 1e5)
        self.request_redraw()

    # ------------------------------------------------------------ selection
    def pick(self, x, y):
        ctx = bpy.context
        best, best_d = None, 14.0
        mats = self.matrices(self.width(), self.height())
        for ob in ctx.visible_objects:
            if ob.type in ("MESH", "CURVE", "ARMATURE") or ob.hide_select:
                continue
            sp = self.project(ob.matrix_world.translation, mats)
            if sp is None:
                continue
            d = math.hypot(sp.x() - x, sp.y() - y)
            if d < best_d:
                best, best_d = ob, d
        if best is not None:
            return best
        # curves and armatures (bone controls) are drawn as lines: hit them by their lines
        wire = wirepick.pick_object(self, x, y, mats)
        origin, direction = self.ray(x, y)
        surf = None
        try:
            hit, loc, _n, _i, ob, _m = ctx.scene.ray_cast(ctx.evaluated_depsgraph_get(), origin, direction)
            if hit and ob is not None and not ob.original.hide_select:
                surf = ((loc - origin).length, ob.original)
        except Exception:
            pass
        if wire is not None and (surf is None or wire[1] <= surf[0] + 1e-3):
            return wire[2]                       # the line is in front of the surface (or no surface)
        if surf is not None:
            return surf[1]
        for ob in ctx.visible_objects:           # origins of curves / armatures as a last resort
            if ob.type in ("CURVE", "ARMATURE") and not ob.hide_select:
                sp = self.project(ob.matrix_world.translation, mats)
                if sp is not None and math.hypot(sp.x() - x, sp.y() - y) < best_d:
                    return ob
        return None

    def _enter_pose_on(self, ob, pb):
        """Object mode → Pose mode on armature ob with only bone pb selected. True when it worked."""
        ctx = bpy.context
        vl = ctx.view_layer
        for o in ctx.selected_objects:
            o.select_set(False)
        ob.select_set(True)
        vl.objects.active = ob
        if "FINISHED" not in bridge.run_op("object.mode_set", {"mode": "POSE"}) or ob.mode != "POSE":
            return False
        for b in ob.pose.bones:
            b.select = False
        pb.select = True
        ob.data.bones.active = pb.bone
        ob.update_tag()
        self.status.emit(f"Pose mode – {pb.name} selected (clicking a rig control enters Pose mode; "
                         "Qt Preferences → Animation).")
        bridge.undo_push("Select")
        self.request_redraw()
        self.selection_edited.emit()
        self.update()
        return True

    def _pose_select_click(self, x, y, extend):
        ctx = bpy.context
        arms = wirepick.pose_armatures(ctx)
        hit = wirepick.pick_bone(self, x, y, arms)
        if not extend:
            for ob in arms:
                for pb in ob.pose.bones:
                    pb.select = False
        if hit is not None:
            ob, pb = hit
            if extend and pb.select and ob.data.bones.active == pb.bone:
                pb.select = False
            else:
                pb.select = True
                ob.data.bones.active = pb.bone
                if ctx.view_layer.objects.active != ob:
                    ctx.view_layer.objects.active = ob
        for ob in arms:
            ob.update_tag()
        bridge.undo_push("Select")
        self.request_redraw()
        self.selection_edited.emit()
        self.update()

    def _pose_select_box(self, rect, mode):
        ctx = bpy.context
        arms = wirepick.pose_armatures(ctx)
        if mode == "SET":
            for ob in arms:
                for pb in ob.pose.bones:
                    pb.select = False
        hits = wirepick.box_bones(self, rect, arms)
        for ob, pb in hits:
            pb.select = mode != "SUB"
        if hits and mode != "SUB":
            ob, pb = hits[0]
            if not (ob.data.bones.active and ob.pose.bones.get(ob.data.bones.active.name)
                    and ob.pose.bones[ob.data.bones.active.name].select):
                ob.data.bones.active = pb.bone
        for ob in arms:
            ob.update_tag()
        bridge.undo_push("Box Select")
        self.request_redraw()
        self.selection_edited.emit()
        self.update()

    def select_click(self, x, y, extend):
        ctx = bpy.context
        if ctx.mode == "EDIT_MESH":
            if editmesh.pick(self, x, y, extend):
                bridge.undo_push("Select")
                self.request_redraw()
                self.selection_edited.emit()
            return
        if ctx.mode == "POSE":
            self._pose_select_click(x, y, extend)
            return
        if ctx.mode != "OBJECT":
            self.status.emit("Click selection works in Object, Pose and Edit (mesh) mode.")
            return
        ob = self.pick(x, y)
        vl = ctx.view_layer
        if ob is not None and ob.type == "ARMATURE" and not extend and keying.click_control_enters_pose():
            # like Maya: clicking a rig control selects the control (Pose mode), not the whole rig
            hit = wirepick.pick_bone(self, x, y, [ob])
            if hit is not None and self._enter_pose_on(ob, hit[1]):
                return
        if not extend:
            for o in ctx.selected_objects:
                o.select_set(False)
        if ob is not None:
            if extend and ob.select_get() and vl.objects.active == ob:
                ob.select_set(False)
            else:
                ob.select_set(True)
                vl.objects.active = ob
        bridge.undo_push("Select")
        self.selection_edited.emit()
        self.update()

    def select_box(self, rect, mode):
        ctx = bpy.context
        if ctx.mode == "EDIT_MESH":
            if editmesh.box(self, rect, mode):
                bridge.undo_push("Box Select")
                self.request_redraw()
                self.selection_edited.emit()
            return
        if ctx.mode == "POSE":
            self._pose_select_box(rect, mode)
            return
        if ctx.mode != "OBJECT":
            return
        mats = self.matrices(self.width(), self.height())
        if mode == "SET":
            for o in ctx.selected_objects:
                o.select_set(False)
        for ob in ctx.visible_objects:
            sp = self.project(ob.matrix_world.translation, mats)
            if sp is not None and rect.contains(sp):
                ob.select_set(mode != "SUB")
        sel = ctx.selected_objects
        if sel and (ctx.view_layer.objects.active not in sel):
            ctx.view_layer.objects.active = sel[0]
        bridge.undo_push("Box Select")
        self.selection_edited.emit()
        self.update()

    # ------------------------------------------------------------ G / R / S
    def start_modal(self, kind):
        ctx = bpy.context
        edit = None
        if ctx.mode == "EDIT_MESH":
            try:
                edit = editmesh.TransformState()
            except ValueError as ex:
                self.status.emit(str(ex))
                return
            sel, pivot = [], edit.pivot
        elif ctx.mode == "OBJECT":
            sel = [o for o in ctx.selected_objects if o.parent is None or not o.parent.select_get()]
            if not sel:
                self.status.emit("Nothing is selected.")
                return
            pivot = sum((o.matrix_world.translation for o in sel), Vector()) / len(sel)
        elif ctx.mode == "POSE":
            try:
                pose = posetransform.TransformState(ctx)
            except ValueError as ex:
                self.status.emit(str(ex))
                return
            sel, pivot = [], pose.pivot
        else:
            self.status.emit("Interactive G/R/S works in Object, Pose and Edit (mesh) mode.")
            return
        pos = self.mapFromGlobal(QtGui.QCursor.pos())
        self._modal = {
            "kind": kind, "axis": None, "objs": [(o, o.matrix_world.copy()) for o in sel],
            "pivot": pivot, "start": QtCore.QPointF(pos), "value": None, "edit": edit,
            "pose": pose if ctx.mode == "POSE" else None,
        }
        self._numeric = ""
        self.setFocus()
        self.grabMouse()
        self.update()

    def _modal_text(self):
        m = self._modal
        names = {"G": "Move", "R": "Rotate", "S": "Scale"}
        axis = f" along {m['axis']}" if m["axis"] else ""
        val = m.get("value")
        if isinstance(val, Vector):
            val = f"{val.x:.3f}, {val.y:.3f}, {val.z:.3f}"
        elif isinstance(val, float):
            val = f"{math.degrees(val):.1f}°" if m["kind"] == "R" else f"{val:.3f}"
        num = f"   [{self._numeric}]" if self._numeric else ""
        return (f"{names[m['kind']]}{axis}: {val or ''}{num}   "
                "(X/Y/Z axis, number + Enter, LMB/Enter confirm, RMB/Esc cancel)")

    def _modal_update(self, pos):
        m = self._modal
        pivot = m["pivot"]
        axis_vec = {"X": Vector((1, 0, 0)), "Y": Vector((0, 1, 0)), "Z": Vector((0, 0, 1))}.get(m["axis"])
        num = None
        if self._numeric not in ("", "-", ".", "-."):
            try:
                num = float(self._numeric)
            except ValueError:
                num = None
        start = m["start"]
        if m["kind"] == "G":
            if num is not None:
                delta = (axis_vec or Vector((1, 0, 0))) * num
            else:
                right, up, _f = self.view_vectors()
                s = self.pixel_size_at(pivot)
                d = pos - start
                delta = (right * d.x() - up * d.y()) * s
                if axis_vec is not None:
                    # move along the axis so that the point follows the mouse along the axis'
                    # direction on screen (works also when the axis is foreshortened)
                    ps0 = self.project(pivot)
                    L = max(s * 80, 1e-6)
                    ps1 = self.project(pivot + axis_vec * L)
                    if ps0 is not None and ps1 is not None:
                        ax, ay = ps1.x() - ps0.x(), ps1.y() - ps0.y()
                        l2 = ax * ax + ay * ay
                        if l2 > 4:
                            delta = axis_vec * (L * (d.x() * ax + d.y() * ay) / l2)
                        else:
                            delta = axis_vec * delta.dot(axis_vec)
                    else:
                        delta = axis_vec * delta.dot(axis_vec)
            m["value"] = delta
            X = Matrix.Translation(delta)
        elif m["kind"] == "R":
            ps = self.project(pivot) or start
            if num is not None:
                angle = math.radians(num)
            else:
                a0 = math.atan2(-(start.y() - ps.y()), start.x() - ps.x())
                a1 = math.atan2(-(pos.y() - ps.y()), pos.x() - ps.x())
                angle = a1 - a0
            _r, _u, fwd = self.view_vectors()
            axis = axis_vec if axis_vec is not None else -fwd
            if axis_vec is not None and axis_vec.dot(-fwd) < 0 and num is None:
                angle = -angle
            m["value"] = angle
            X = Matrix.Translation(pivot) @ Matrix.Rotation(angle, 4, axis) @ Matrix.Translation(-pivot)
        else:
            ps = self.project(pivot) or start
            if num is not None:
                fac = num
            else:
                d0 = max(math.hypot(start.x() - ps.x(), start.y() - ps.y()), 1.0)
                fac = math.hypot(pos.x() - ps.x(), pos.y() - ps.y()) / d0
            m["value"] = fac
            S = Matrix.Scale(fac, 4, axis_vec) if axis_vec is not None else Matrix.Scale(fac, 4)
            X = Matrix.Translation(pivot) @ S @ Matrix.Translation(-pivot)
        if m.get("edit") is not None:
            m["edit"].apply(X)
        if m.get("pose") is not None:
            m["pose"].apply(X, m["kind"])
        for ob, init in m["objs"]:
            ob.matrix_world = X @ init
        self.redraw_scene()
        self.update()

    def _modal_end(self, confirm):
        m = self._modal
        self._modal = None
        gizmo.invalidate(self)
        self.releaseMouse()
        if not confirm:
            if m.get("pose") is not None:
                m["pose"].restore()
            if m.get("edit") is not None:
                m["edit"].restore()
            for ob, init in m["objs"]:
                ob.matrix_world = init
        elif m.get("edit") is not None:
            bridge.undo_push({"G": "Move", "R": "Rotate", "S": "Resize"}[m["kind"]])
        elif m.get("pose") is not None:
            m["pose"].finish(m["kind"])
            bridge.undo_push({"G": "Move", "R": "Rotate", "S": "Resize"}[m["kind"]])
        else:
            ts = bpy.context.scene.tool_settings
            if ts.use_keyframe_insert_auto:
                # like Blender's default key channels: location, rotation and scale (rotating / scaling
                # several objects about a pivot also moves them)
                for ob, _init in m["objs"]:
                    rot = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}.get(
                        ob.rotation_mode, "rotation_euler")
                    for path in ("location", rot, "scale"):
                        try:
                            ob.keyframe_insert(path)
                        except Exception:
                            pass
            bridge.undo_push({"G": "Move", "R": "Rotate", "S": "Resize"}[m["kind"]])
        self.redraw_scene()
        self.update()

    # ------------------------------------------------------------ events
    def focusInEvent(self, ev):
        if self.area is not None:
            self.area.set_active(self)
        super().focusInEvent(ev)
    def enterEvent(self, ev):
        # like Blender: keys go to the editor under the mouse (except a console being typed in)
        fw = QtWidgets.QApplication.focusWidget()
        typing = isinstance(fw, QtWidgets.QLineEdit) and fw.text() and not isinstance(
            fw.parent(), QtWidgets.QAbstractSpinBox)
        if not typing:
            self.setFocus()
            win = self.window()
            if not win.isActiveWindow():   # floating dock = separate window
                win.activateWindow()
        super().enterEvent(ev)

    def resizeEvent(self, ev):
        self.request_redraw()
        super().resizeEvent(ev)

    def mousePressEvent(self, ev):
        pos = ev.position()
        b = ev.button()
        mods = ev.modifiers()
        self.setFocus()
        if self._modal:
            self._modal_end(b == QtCore.Qt.LeftButton)
            return
        if keymap.nav_scheme() == "MAYA" and self._maya_press(ev, pos, b, mods):
            return
        if b == QtCore.Qt.LeftButton and not mods & QtCore.Qt.AltModifier:
            hit = self._nav_hit(pos)
            if hit is not None:
                self._navg = {"hit": hit, "start": pos, "moved": False}
                if hit[0] == "button" and hit[1] in ("zoom", "pan"):
                    self._nav = hit[1]
                    self._last = pos
                    self.setCursor(QtCore.Qt.SizeVerCursor if hit[1] == "zoom" else QtCore.Qt.ClosedHandCursor)
                self.update()
                return
        if b == QtCore.Qt.MiddleButton or (b == QtCore.Qt.LeftButton and mods & QtCore.Qt.AltModifier):
            if mods & QtCore.Qt.ShiftModifier:
                self._nav = "pan"
            elif mods & QtCore.Qt.ControlModifier:
                self._nav = "zoom"
            else:
                self._nav = "orbit"
            self._last = pos
            self.setCursor(QtCore.Qt.ClosedHandCursor)
        elif b == QtCore.Qt.LeftButton:
            tool = self.tools.tool
            if tool != "SELECT":
                hid = gizmo.hit(gizmo.handles(self, tool), pos)
                if hid is not None and gizmo.start_drag(self, hid, tool):
                    self._gz_hover = None
                    return
            self._press_pos = pos
        elif b == QtCore.Qt.RightButton:
            self._context_menu(ev.globalPosition().toPoint())

    # Maya navigation: Alt + LMB tumble, Alt + MMB track, Alt + RMB dolly, MMB = drag with the active tool
    _MAYA_TOOL_DRAG = {"MOVE": "G:FREE", "TRANSFORM": "G:FREE", "ROTATE": "R:VIEW", "SCALE": "S:UNIFORM"}

    def _maya_press(self, ev, pos, b, mods):
        """Mouse press with the Maya scheme. True when it was handled here."""
        alt = bool(mods & QtCore.Qt.AltModifier)
        if alt and b in (QtCore.Qt.LeftButton, QtCore.Qt.MiddleButton, QtCore.Qt.RightButton):
            self._nav = {QtCore.Qt.LeftButton: "orbit", QtCore.Qt.MiddleButton: "pan",
                         QtCore.Qt.RightButton: "dolly"}[b]
            self._last = pos
            self.setCursor(QtCore.Qt.ClosedHandCursor if self._nav != "dolly" else QtCore.Qt.SizeHorCursor)
            return True
        if b == QtCore.Qt.MiddleButton:
            hid = self._MAYA_TOOL_DRAG.get(self.tools.tool)
            if hid is not None and gizmo.start_drag(self, hid, self.tools.tool):
                self._modal["drag_button"] = QtCore.Qt.MiddleButton
                self._gz_hover = None
            return True                      # Maya: the middle button never navigates without Alt
        return False

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._modal:
            self._modal_update(pos)
            return
        g = self._navg
        if g is not None and not self._nav:
            if (pos - g["start"]).manhattanLength() > 3 and g["hit"][0] in ("axis", "ball"):
                g["moved"] = True                   # dragging the axis ball orbits (like Blender)
                self._nav = "orbit"
                self._last = pos
                self.setCursor(QtCore.Qt.ClosedHandCursor)
            return
        if self._nav and self._last is not None:
            d = pos - self._last
            self._last = pos
            if self._nav == "orbit":
                self._orbit(d.x(), d.y())
            elif self._nav == "pan":
                self._pan(d.x(), d.y())
            elif self._nav == "dolly":           # Maya Alt+RMB: right / up = closer
                self._zoom(1.01 ** (d.y() - d.x()))
            else:
                self._zoom(1.01 ** d.y())
            self.update()
        elif self._press_pos is not None:
            if (pos - self._press_pos).manhattanLength() > 5:
                self._box = (self._press_pos, pos)
                self.update()
        elif (nh := self._nav_hit(pos)) is not None or self._nav_hover is not None:
            if nh != self._nav_hover:
                self._nav_hover = nh
                self.setToolTip(self._nav_tooltip(nh))
                if nh is None:
                    self.unsetCursor()
                else:
                    self.setCursor(QtCore.Qt.PointingHandCursor if nh[0] != "ball" else QtCore.Qt.OpenHandCursor)
                self.update()
        elif self.tools.tool != "SELECT":
            hov = gizmo.hit(gizmo.handles(self, self.tools.tool), pos)
            if hov != self._gz_hover:
                self._gz_hover = hov
                self.update()

    def mouseReleaseEvent(self, ev):
        pos = ev.position()
        if self._modal and self._modal.get("drag") and ev.button() == self._modal.get(
                "drag_button", QtCore.Qt.LeftButton):
            self._modal_end(True)          # gizmo drag: releasing the button confirms
            return
        if self._navg is not None and ev.button() == QtCore.Qt.LeftButton:
            g, self._navg = self._navg, None
            self._nav = None
            self.unsetCursor()
            if not g["moved"] and g["hit"][0] in ("axis", "button") and g["hit"][1] not in ("zoom", "pan"):
                self._nav_click(g["hit"])
            self.update()
            return
        if self._nav:
            self._nav = None
            self.unsetCursor()
            return
        if ev.button() == QtCore.Qt.LeftButton and self._press_pos is not None:
            mods = ev.modifiers()
            if self._box:
                rect = QtCore.QRectF(self._box[0], self._box[1]).normalized()
                mode = "SUB" if mods & QtCore.Qt.ControlModifier else (
                    "ADD" if mods & QtCore.Qt.ShiftModifier else "SET")
                self._box = None
                self.select_box(rect, mode)
            else:
                self.select_click(pos.x(), pos.y(), bool(mods & QtCore.Qt.ShiftModifier))
            self._press_pos = None
            self.update()

    def wheelEvent(self, ev):
        mods = ev.modifiers()
        pd = ev.pixelDelta()
        trackpad = not pd.isNull()  # only touchpads send pixelDelta
        if trackpad and not (mods & QtCore.Qt.ControlModifier):
            if mods & QtCore.Qt.ShiftModifier:
                self._pan(-pd.x(), -pd.y())
            else:
                self._orbit(-pd.x(), -pd.y())
        else:
            steps = ev.angleDelta().y() / 120.0 or pd.y() / 30.0
            self._zoom(0.85 ** steps)
        self.update()

    def event(self, ev):
        if ev.type() == QtCore.QEvent.ShortcutOverride:
            # a key that is a 3D View shortcut belongs to the view, not to a window shortcut
            # (e.g. Shift+Space = tool menu here, not the window's Space = play)
            if self._modal or keymap.view_owns(ev, bpy.context.mode):
                ev.accept()
                return True
        if ev.type() == QtCore.QEvent.NativeGesture:
            if ev.gestureType() == QtCore.Qt.ZoomNativeGesture:
                self._zoom(1.0 - ev.value())
                self.update()
                return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        key = ev.key()
        mods = ev.modifiers()
        text = ev.text()
        if self._modal:
            if key in (QtCore.Qt.Key_Escape,):
                self._modal_end(False)
            elif key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                self._modal_end(True)
            elif key in (QtCore.Qt.Key_X, QtCore.Qt.Key_Y, QtCore.Qt.Key_Z):
                ax = chr(key)
                self._modal["axis"] = None if self._modal["axis"] == ax else ax
                self._modal_update(self.mapFromGlobal(QtGui.QCursor.pos()).toPointF())
            elif key == QtCore.Qt.Key_Backspace:
                self._numeric = self._numeric[:-1]
                self._modal_update(self.mapFromGlobal(QtGui.QCursor.pos()).toPointF())
            elif text and text in "0123456789.-":
                self._numeric += text
                self._modal_update(self.mapFromGlobal(QtGui.QCursor.pos()).toPointF())
            return
        keypad = bool(mods & QtCore.Qt.KeypadModifier)
        names = keymap.event_names(ev)

        def H(aid):
            return keymap.hit(aid, ev, names)

        mode = bpy.context.mode
        if H("view3d.tool_menu"):
            gizmo.show_tool_menu(self)       # like Blender: Shift+Space = tool menu
            return
        for aid, tool in (("view3d.tool_select", "SELECT"), ("view3d.tool_move", "MOVE"),
                          ("view3d.tool_rotate", "ROTATE"), ("view3d.tool_scale", "SCALE")):
            if H(aid):
                self.tools.set_tool(tool)    # Blender: W = select tool; Maya: Q / W / E / R
                return
        for aid, kind, label in (("view3d.key_location", "location", "Location"),
                                 ("view3d.key_rotation", "rotation", "Rotation"),
                                 ("view3d.key_scale", "scale", "Scale")):
            if H(aid) and bpy.context.mode in ("OBJECT", "POSE"):
                n = keying.insert(kinds=(kind,))     # Maya: Shift+W / E / R
                self.status.emit(keying.last_message.replace("Keyed", f"Keyed {label} of") if n
                                 else keying.last_message)
                if n:
                    bridge.undo_push(f"Insert {label} Keyframe")
                self.redraw_scene()
                return
        if H("view3d.toolbar"):
            self.tools.toggle_toolbar()      # like Blender: T shows/hides the toolbar
            return
        if H("view3d.sidebar"):
            mw = getattr(self.hub, "main_window", None)
            if mw is not None:
                mw.toggle_sidebar()      # like Blender: N shows/hides the sidebar
            return
        if mode == "POSE" and self._pose_key(H):
            self.update()
            return
        if mode == "EDIT_MESH" and self._mesh_key(H, keypad):
            return
        step = 15 * DEG
        views = (
            ("view3d.orbit_down", lambda: self.orbit_step(0, step)),
            ("view3d.orbit_up", lambda: self.orbit_step(0, -step)),
            ("view3d.orbit_left", lambda: self.orbit_step(-step, 0)),
            ("view3d.orbit_right", lambda: self.orbit_step(step, 0)),
            ("view3d.pan_down", lambda: self._pan(0, -60)),
            ("view3d.pan_up", lambda: self._pan(0, 60)),
            ("view3d.pan_left", lambda: self._pan(60, 0)),
            ("view3d.pan_right", lambda: self._pan(-60, 0)),
            ("view3d.view_flip", lambda: self.orbit_step(math.pi, math.pi - 2 * self.pitch)),
            ("view3d.view_front", lambda: self.set_view("FRONT")),
            ("view3d.view_back", lambda: self.set_view("BACK")),
            ("view3d.view_right", lambda: self.set_view("RIGHT")),
            ("view3d.view_left", lambda: self.set_view("LEFT")),
            ("view3d.view_top", lambda: self.set_view("TOP")),
            ("view3d.view_bottom", lambda: self.set_view("BOTTOM")),
            ("view3d.view_camera", lambda: self.set_view("CAMERA")),
            ("view3d.view_persp", self.toggle_ortho),
            ("view3d.frame_selected", self.frame_selected),
            ("view3d.frame_all", self.frame_all),
        )
        for aid, fn in views:
            if H(aid):
                fn()
                self.update()
                return
        # after the views: a numpad digit is a view key first, the number row may be shading (Maya 4/5/6)
        for aid, kind in (("view3d.shading_wire", "WIREFRAME"), ("view3d.shading_solid", "SOLID"),
                          ("view3d.shading_material", "MATERIAL")):
            if H(aid):
                self.set_shading(kind)       # Maya: 4 / 5 / 6
                return
        if mode in ("OBJECT", "POSE") and (H("view3d.insert_key") or H("view3d.delete_key")):
            if H("view3d.delete_key"):    # Alt+I: delete keys at the current frame
                n = keying.delete()
                self.status.emit(f"Deleted {n} keyframe(s)." if n else "No keyframes to delete here.")
                if n:
                    bridge.undo_push("Delete Keyframe")
            else:                         # I: insert location / rotation / scale keys
                n = keying.insert()
                self.status.emit(keying.last_message)
                if n:
                    bridge.undo_push("Insert Keyframe")
            self.redraw_scene()
        elif H("view3d.move"):
            self.start_modal("G")
        elif H("view3d.rotate"):
            self.start_modal("R")
        elif H("view3d.scale"):
            self.start_modal("S")
        elif H("view3d.duplicate"):
            if bridge.run_op("object.duplicate") == {"FINISHED"}:
                self.start_modal("G")
        elif H("view3d.delete"):
            bridge.run_op("object.delete" if mode == "OBJECT" else "mesh.delete")
        elif H("view3d.add_menu"):
            self._add_menu()
        elif H("view3d.deselect_all"):
            bridge.run_op("object.select_all" if mode == "OBJECT" else "mesh.select_all",
                          {"action": "DESELECT"})
        elif H("view3d.select_all"):
            bridge.run_op("object.select_all" if mode == "OBJECT" else "mesh.select_all",
                          {"action": "SELECT"})
        elif H("view3d.select_invert"):
            bridge.run_op("object.select_all", {"action": "INVERT"})
        elif H("view3d.reveal"):
            bridge.run_op("object.hide_view_clear")
        elif H("view3d.hide"):
            bridge.run_op("object.hide_view_set", {"unselected": False})
        elif H("view3d.hide_unselected"):
            bridge.run_op("object.hide_view_set", {"unselected": True})
        elif H("view3d.edit_toggle"):
            bridge.run_op("object.editmode_toggle")
        elif H("view3d.shading_pie"):
            self._shading_pie()
        else:
            super().keyPressEvent(ev)
            return
        self.update()

    def _mesh_key(self, H, keypad):
        """Edit Mesh shortcuts. True when the key was used."""
        if not keypad and (H("mesh.select_vert") or H("mesh.select_edge") or H("mesh.select_face")):
            editmesh.set_select_mode(H("mesh.select_vert"), H("mesh.select_edge"), H("mesh.select_face"))
            self.selection_edited.emit()
            self.request_redraw()
            return True
        from .qt_ui import LazyMenu
        if H("mesh.extrude"):
            if "FINISHED" in bridge.run_op("mesh.extrude_region"):
                self.start_modal("G")
        elif H("mesh.duplicate"):
            if "FINISHED" in bridge.run_op("mesh.duplicate"):
                self.start_modal("G")
        elif H("mesh.fill"):
            bridge.run_op("mesh.edge_face_add")
        elif H("mesh.select_linked"):
            bridge.run_op("mesh.select_linked")
        elif H("mesh.select_invert"):
            bridge.run_op("mesh.select_all", {"action": "INVERT"})
        elif H("mesh.reveal"):
            bridge.run_op("mesh.reveal")
        elif H("mesh.hide"):
            bridge.run_op("mesh.hide", {"unselected": False})
        elif H("mesh.hide_unselected"):
            bridge.run_op("mesh.hide", {"unselected": True})
        elif H("mesh.delete_menu"):
            LazyMenu("VIEW3D_MT_edit_mesh_delete", self).exec(QtGui.QCursor.pos())
        elif H("mesh.uv_menu"):
            LazyMenu("VIEW3D_MT_uv_map", self).exec(QtGui.QCursor.pos())
        else:
            return False
        return True

    def focusNextPrevChild(self, _next):
        return False  # Tab belongs to the viewport (edit mode)

    def _pose_key(self, H):
        """Pose-mode shortcuts like Blender. True when the key was used."""
        done = None
        for aid, kind in (("pose.clear_loc", "G"), ("pose.clear_rot", "R"), ("pose.clear_scale", "S")):
            if H(aid):
                if posetransform.clear(kind):
                    done = {"G": "Clear Location", "R": "Clear Rotation", "S": "Clear Scale"}[kind]
                else:
                    return True
                break
        else:
            if H("pose.deselect_all"):
                posetransform.select_all("DESELECT")
                done = "Deselect"
            elif H("pose.select_all"):
                posetransform.select_all("SELECT")
                done = "Select All"
            elif H("pose.select_invert"):
                posetransform.select_all("INVERT")
                done = "Select Inverse"
            elif H("pose.reveal"):
                posetransform.reveal()
                done = "Reveal Bones"
            elif H("pose.hide"):
                posetransform.hide(unselected=False)
                done = "Hide Bones"
            elif H("pose.hide_unselected"):
                posetransform.hide(unselected=True)
                done = "Hide Bones"
            elif H("view3d.delete") or H("view3d.duplicate") or H("view3d.add_menu"):
                return True            # object / mesh actions don't apply to bones
        if done is None:
            return False
        bridge.undo_push(done)
        gizmo.invalidate(self)
        self.redraw_scene()
        self.selection_edited.emit()
        return True

    # ------------------------------------------------------------ context menus
    def _context_menu(self, gpos):
        from .qt_ui import LazyMenu
        mid = {"OBJECT": "VIEW3D_MT_object_context_menu", "POSE": "VIEW3D_MT_pose_context_menu"}.get(
            bpy.context.mode, "VIEW3D_MT_edit_mesh_context_menu")
        LazyMenu(mid, self).exec(gpos)

    def _add_menu(self):
        from .qt_ui import LazyMenu
        mid = "VIEW3D_MT_add" if bpy.context.mode == "OBJECT" else "VIEW3D_MT_mesh_add"
        LazyMenu(mid, self).exec(QtGui.QCursor.pos())

    def _shading_pie(self):
        m = QtWidgets.QMenu(self)
        for kind, label in (("WIREFRAME", "Wireframe"), ("SOLID", "Solid"),
                            ("MATERIAL", "Material Preview"), ("RENDERED", "Rendered")):
            a = m.addAction(label)
            a.triggered.connect(lambda _=False, k=kind: self.set_shading(k))
        m.exec(QtGui.QCursor.pos())

    def shutdown(self):
        self._timer.stop()
        if self._off is not None:
            try:
                self._off.free()
            except Exception:
                pass
            self._off = None


# ---------------------------------------------------------------- several views
class ViewportArea(QtWidgets.QWidget):
    """The 3D view area: one viewport or several split views (like Blender's Quad View / Maya's
    four views). Each view has its own camera; the shading is Blender's (shared by all views).
    The active view (the one under the mouse / last clicked) is the one the header, the menus and
    the API control."""
    status = QtCore.Signal(str)
    selection_edited = QtCore.Signal()
    active_changed = QtCore.Signal(object)

    LAYOUTS = {"single": "Single View", "side": "Two Views Side by Side",
               "stacked": "Two Views Stacked", "quad": "Four Views"}
    # views 1–3 in Four Views; view 0 keeps its (perspective) camera
    _QUAD_PRESETS = ("TOP", "FRONT", "RIGHT")

    def __init__(self, hub, prefs=None, parent=None):
        super().__init__(parent)
        self.hub = hub
        self.prefs = prefs
        self.mode = "single"
        self._prev_mode = "single"
        self.views = []
        self._lay = QtWidgets.QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._root = None
        self.active = self._view(0)
        hub.viewport = self.active
        hub.viewport_area = self
        self.set_layout("single")

    # --- views
    def _view(self, i):
        while len(self.views) <= i:
            v = Viewport(self.hub, self.prefs)
            v.setParent(self)                  # always owned by Qt (never a parentless widget)
            v.area = self
            v.status.connect(self.status)
            v.selection_edited.connect(self.selection_edited)
            if self.views:                     # a new view starts as a copy of the first one
                src = self.views[0]
                v.target, v.dist, v.yaw, v.pitch = src.target.copy(), src.dist, src.yaw, src.pitch
                v.ortho, v.view_name = src.ortho, src.view_name
            v.hide()
            self.views.append(v)
        return self.views[i]

    def visible_views(self):
        return [v for v in self.views if v.isVisible()]

    def set_active(self, v):
        if v is self.active or v not in self.views:
            return
        old = self.active
        self.active = v
        self.hub.viewport = v
        old.update()
        v.update()
        self.active_changed.emit(v)

    # --- layout
    def set_layout(self, mode):
        if mode not in self.LAYOUTS:
            raise ValueError(f"layout must be one of {sorted(self.LAYOUTS)}")
        new_quad = mode == "quad" and self.mode != "quad"
        if mode != self.mode:
            self._prev_mode = self.mode
        self.mode = mode
        # take the views out of the old splitters before those are deleted
        for v in self.views:
            v.hide()
            v.setParent(self)
        if self._root is not None and self._root not in self.views:
            self._lay.removeWidget(self._root)
            self._root.hide()
            self._root.deleteLater()
        elif self._root is not None:
            self._lay.removeWidget(self._root)
        self._root = None

        V = QtCore.Qt.Vertical
        H = QtCore.Qt.Horizontal
        if mode == "single":
            used = [self._view(0)]
            root = used[0]
        elif mode in ("side", "stacked"):
            used = [self._view(0), self._view(1)]
            root = self._splitter(H if mode == "side" else V, self, used)
        else:
            used = [self._view(i) for i in range(4)]
            root = QtWidgets.QSplitter(V, self)
            root.setChildrenCollapsible(False)
            # Maya-like: Top | Perspective / Front | Right
            self._splitter(H, root, [used[1], used[0]])
            self._splitter(H, root, [used[2], used[3]])
            root.setSizes([10000, 10000])
            if new_quad:
                for v, preset in zip(used[1:], self._QUAD_PRESETS):
                    v.set_view(preset)
                    v.frame_all()
        self._root = root
        self._lay.addWidget(root)
        root.show()
        for v in used:
            v.show()
            v.request_redraw()
        if self.active not in used:
            self.active = used[0]
            self.hub.viewport = self.active
            self.active_changed.emit(self.active)
        for v in used:
            v.update()

    @staticmethod
    def _splitter(orientation, parent, widgets):
        sp = QtWidgets.QSplitter(orientation, parent)
        sp.setChildrenCollapsible(False)
        sp.setHandleWidth(theme.px(4))
        for w in widgets:
            sp.addWidget(w)
        sp.setSizes([10000] * len(widgets))
        return sp

    def toggle_quad(self):
        """Ctrl+Alt+Q like in Blender: Four Views ↔ the previous layout."""
        self.set_layout(self._prev_mode if self.mode == "quad" and self._prev_mode != "quad" else
                        ("single" if self.mode == "quad" else "quad"))

    # --- all views
    def request_redraw(self, extra=0):
        for v in self.views:
            v.request_redraw(extra)

    def update_all(self):
        for v in self.visible_views():
            v.update()

    def render_now(self):
        for v in self.visible_views():
            v.render_now()

    def playback_changed(self, playing):
        for v in self.views:
            v.playback_changed(playing)

    def shutdown(self):
        for v in self.views:
            v.shutdown()

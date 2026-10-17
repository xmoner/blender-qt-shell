"""3D viewport v Qt.

Blender vykreslí scénu do GPUOffScreen (draw_view3d) s našimi maticemi kamery, obraz se
přečte do numpy a zobrazí jako QImage. Navigace, výběr a G/R/S transformace běží v Qt.
"""
import math

import bpy
import gpu
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, editmesh

DEG = math.pi / 180.0

# horní číselná řada na národních klávesnicích (CZ/SK/DE/FR) píše znaky místo číslic
_LAYOUT_DIGITS = {"+": 1, "ě": 2, "š": 3, "č": 4, "ř": 5, "ž": 6, "ý": 7, "á": 8, "í": 9, "é": 0,
                  "ľ": 2, "ť": 5, "&": 1, "\"": 3, "'": 4, "(": 5, "à": 0, "ç": 9, "è": 7, "_": 8}


def digit_of(ev):
    """Číslice fyzické klávesy (jako Blender – nezávisle na rozložení klávesnice), jinak None."""
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
    """Ořízne úsečku (ve view space) rovinou z = -near. Vrací (a, b) nebo None."""
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
        # pohled
        self.target = Vector((0.0, 0.0, 0.0))
        self.dist = 15.0
        self.yaw = 50 * DEG
        self.pitch = 65 * DEG
        self.ortho = False
        self.camera_view = False
        self.view_name = "Uživatelská perspektiva"
        # render
        self._off = None
        self._image = None
        self._dirty = True
        self._extra_frames = 0
        self._draw_kwargs = None
        self._failed = None
        self.show_boxes = False
        self.show_grid = False
        # interakce
        self._nav = None
        self._last = None
        self._press_pos = None
        self._box = None
        self._modal = None
        self._numeric = ""

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)
        hub.data_changed.connect(self.request_redraw)
        hub.frame_changed.connect(lambda _f: self.request_redraw())
        hub.selection_changed.connect(self.update)
        hub.file_loaded.connect(self._on_file_loaded)

    # ------------------------------------------------------------ pomocné
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
            self.request_redraw()

    def request_redraw(self, extra=0):
        self._dirty = True
        self._extra_frames = max(self._extra_frames, extra)

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
            return 2 * math.atan(math.tan(f_large / 2) * h / max(w, 1))  # vertikální
        return f_large

    def clip(self):
        sp, _r = self.space()
        if sp:
            return max(sp.clip_start, 1e-4), sp.clip_end
        return 0.01, 1000.0

    def matrices(self, w, h):
        """(view_matrix, projection_matrix) pro velikost w×h."""
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
        """(right, up, forward) kamery ve světě."""
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
            self.view_name = "Uživatelská perspektiva"

    # ------------------------------------------------------------ render
    def _tick(self):
        if not self.isVisible() or bridge.is_rendering():
            return
        if self._dirty or self._extra_frames > 0:
            sh = self.shading()
            self._dirty = False
            if self._extra_frames > 0:
                self._extra_frames -= 1
            elif sh in ("MATERIAL", "RENDERED"):
                self._extra_frames = 16 if sh == "MATERIAL" else 64  # postupné zjemňování
            self.render_frame()
            self.update()

    def render_frame(self):
        scale = getattr(self.prefs, "viewport_scale", 1.0) if self.prefs else 1.0
        dpr = self.devicePixelRatioF() * scale
        w = max(2, min(4096, int(self.width() * dpr)))
        h = max(2, min(4096, int(self.height() * dpr)))
        space, region = self.space()
        if space is None:
            self._failed = "Nenalezena žádná 3D oblast v Blenderu."
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
            with self._off.bind():
                fb = gpu.state.active_framebuffer_get()
                buf = fb.read_color(0, 0, w, h, 4, 0, "UBYTE")
            try:
                arr = np.frombuffer(buf, dtype=np.uint8)
            except TypeError:
                arr = np.asarray(buf.to_list(), dtype=np.uint8)
            arr = np.ascontiguousarray(arr.reshape(h, w, 4)[::-1])
            fmt = QtGui.QImage.Format_RGBA8888_Premultiplied if transparent else QtGui.QImage.Format_RGBX8888
            img = QtGui.QImage(arr.data, w, h, w * 4, fmt).copy()
            img.setDevicePixelRatio(dpr)
            self._image = img
            self._img_transparent = transparent and self._draw_kwargs.get("draw_background") is False
            self._failed = None
        except Exception as ex:
            self._failed = f"Render viewportu selhal: {ex}"

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

    # ------------------------------------------------------------ kreslení v Qt
    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        r = self.rect()
        grad = QtGui.QLinearGradient(0, 0, 0, r.height())
        grad.setColorAt(0, QtGui.QColor("#454545"))
        grad.setColorAt(1, QtGui.QColor("#333333"))
        p.fillRect(r, QtGui.QBrush(grad))
        mats = self.matrices(self.width(), self.height())
        if self.show_grid and self._image is not None and getattr(self, "_img_transparent", False):
            self._paint_grid(p, mats)
        if self._image is not None:
            p.drawImage(r, self._image)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        if self.show_boxes:
            self._paint_selection(p, mats)
        self._paint_gizmo(p)
        self._paint_text(p)
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

        # v ortho pohledu zepředu/zboku je mřížka 'z hrany' → přeskočíme
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

    def _paint_gizmo(self, p):
        c = QtCore.QPointF(self.width() - 50, 50)
        right, up, fwd = self.view_vectors()
        axes = [(Vector((1, 0, 0)), "X", QtGui.QColor("#ff3352")),
                (Vector((0, 1, 0)), "Y", QtGui.QColor("#8bdc00")),
                (Vector((0, 0, 1)), "Z", QtGui.QColor("#2890ff"))]
        items = []
        for v, name, col in axes:
            sx, sy, depth = v.dot(right), -v.dot(up), v.dot(fwd)
            items.append((depth, sx, sy, name, col))
        items.sort(key=lambda t: -t[0])  # vzdálenější první
        p.setBrush(QtGui.QColor(0, 0, 0, 40))
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(c, 42, 42)
        f = p.font()
        f.setBold(True)
        f.setPixelSize(10)
        p.setFont(f)
        for _depth, sx, sy, name, col in items:
            end = c + QtCore.QPointF(sx * 32, sy * 32)
            p.setPen(QtGui.QPen(col, 2))
            p.drawLine(c, end)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(end, 8, 8)
            p.setPen(QtGui.QColor("#111"))
            p.drawText(QtCore.QRectF(end.x() - 8, end.y() - 8, 16, 16), QtCore.Qt.AlignCenter, name)

    def _paint_text(self, p):
        ctx = bpy.context
        p.setPen(QtGui.QColor("#e0e0e0"))
        f = p.font()
        f.setBold(False)
        f.setPixelSize(12)
        p.setFont(f)
        name = self.view_name
        if self.camera_view:
            name = "Pohled kamery"
        elif self.ortho and "ortho" not in name:
            name += " (ortho)"
        p.drawText(12, 20, name)
        try:
            ob = ctx.view_layer.objects.active
            coll = ctx.view_layer.active_layer_collection.collection.name
            p.drawText(12, 38, f"({ctx.scene.frame_current}) {coll} | {ob.name if ob else '—'}")
        except Exception:
            pass
        if self._modal:
            p.setPen(QtGui.QColor("#ffffff"))
            p.drawText(12, self.height() - 14, self._modal_text())
        if self._failed:
            p.setPen(QtGui.QColor("#ff7070"))
            p.drawText(QtCore.QRectF(self.rect()).adjusted(20, 50, -20, -20),
                       int(QtCore.Qt.AlignCenter.value) | int(QtCore.Qt.TextWordWrap.value), self._failed)

    # ------------------------------------------------------------ navigace
    def frame_objects(self, objs):
        pts = []
        for ob in objs:
            mw = ob.matrix_world
            pts.extend(mw @ Vector(c) for c in ob.bound_box)
            pts.append(mw.translation)
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
        sel = list(bpy.context.selected_objects)
        self.frame_objects(sel or list(bpy.context.visible_objects))

    def frame_all(self):
        self.frame_objects(list(bpy.context.visible_objects))

    def set_view(self, name):
        self.leave_camera()
        views = {
            "FRONT": (0.0, 90 * DEG, "Zepředu"), "BACK": (180 * DEG, 90 * DEG, "Zezadu"),
            "RIGHT": (90 * DEG, 90 * DEG, "Zprava"), "LEFT": (-90 * DEG, 90 * DEG, "Zleva"),
            "TOP": (0.0, 0.0001, "Shora"), "BOTTOM": (0.0, 180 * DEG - 0.0001, "Zespodu"),
        }
        if name == "CAMERA":
            if bpy.context.scene.camera is None:
                self.status.emit("Scéna nemá aktivní kameru.")
                return
            self.camera_view = not self.camera_view
            self.request_redraw()
            return
        yaw, pitch, label = views[name]
        self.yaw, self.pitch = yaw, pitch
        self.ortho = True
        self.view_name = f"{label} (ortho)"
        self.request_redraw()

    def toggle_ortho(self):
        self.leave_camera()
        self.ortho = not self.ortho
        self.view_name = "Uživatelská ortografie" if self.ortho else "Uživatelská perspektiva"
        self.request_redraw()

    def _orbit(self, dx, dy):
        self.leave_camera()
        if "ortho" in self.view_name and self.view_name.startswith(("Zep", "Zez", "Zpr", "Zle", "Sho", "Zes")):
            self.view_name = "Uživatelská ortografie" if self.ortho else "Uživatelská perspektiva"
        self.yaw -= dx * 0.008
        self.pitch = min(max(self.pitch - dy * 0.008, 0.0001), math.pi - 0.0001)
        self.request_redraw()

    def orbit_step(self, dyaw, dpitch):
        """Otočení pohledu o pevný úhel (numerická klávesnice 2/4/6/8/9 jako v Blenderu)."""
        self.leave_camera()
        if self.view_name.startswith(("Zep", "Zez", "Zpr", "Zle", "Sho", "Zes")):
            self.view_name = "Uživatelská ortografie" if self.ortho else "Uživatelská perspektiva"
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

    # ------------------------------------------------------------ výběr
    def pick(self, x, y):
        ctx = bpy.context
        best, best_d = None, 14.0
        mats = self.matrices(self.width(), self.height())
        for ob in ctx.visible_objects:
            if ob.type == "MESH":
                continue
            sp = self.project(ob.matrix_world.translation, mats)
            if sp is None:
                continue
            d = math.hypot(sp.x() - x, sp.y() - y)
            if d < best_d:
                best, best_d = ob, d
        if best is not None:
            return best
        origin, direction = self.ray(x, y)
        try:
            hit, _loc, _n, _i, ob, _m = ctx.scene.ray_cast(ctx.evaluated_depsgraph_get(), origin, direction)
        except Exception:
            return None
        if hit and ob is not None:
            return ob.original
        return None

    def select_click(self, x, y, extend):
        ctx = bpy.context
        if ctx.mode == "EDIT_MESH":
            if editmesh.pick(self, x, y, extend):
                bridge.undo_push("Select")
                self.request_redraw()
                self.selection_edited.emit()
            return
        if ctx.mode != "OBJECT":
            self.status.emit("Výběr kliknutím funguje v Object a Edit (mesh) módu.")
            return
        ob = self.pick(x, y)
        vl = ctx.view_layer
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
                self.status.emit("Nic není vybráno.")
                return
            pivot = sum((o.matrix_world.translation for o in sel), Vector()) / len(sel)
        else:
            self.status.emit("Interaktivní G/R/S funguje v Object a Edit (mesh) módu.")
            return
        pos = self.mapFromGlobal(QtGui.QCursor.pos())
        self._modal = {
            "kind": kind, "axis": None, "objs": [(o, o.matrix_world.copy()) for o in sel],
            "pivot": pivot, "start": QtCore.QPointF(pos), "value": None, "edit": edit,
        }
        self._numeric = ""
        self.setFocus()
        self.grabMouse()
        self.update()

    def _modal_text(self):
        m = self._modal
        names = {"G": "Posun", "R": "Rotace", "S": "Měřítko"}
        axis = f" podél {m['axis']}" if m["axis"] else ""
        val = m.get("value")
        if isinstance(val, Vector):
            val = f"{val.x:.3f}, {val.y:.3f}, {val.z:.3f}"
        elif isinstance(val, float):
            val = f"{math.degrees(val):.1f}°" if m["kind"] == "R" else f"{val:.3f}"
        num = f"   [{self._numeric}]" if self._numeric else ""
        return (f"{names[m['kind']]}{axis}: {val or ''}{num}   "
                "(X/Y/Z osa, číslo + Enter, LMB/Enter potvrdit, RMB/Esc zrušit)")

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
        for ob, init in m["objs"]:
            ob.matrix_world = X @ init
        self.request_redraw()
        self.update()

    def _modal_end(self, confirm):
        m = self._modal
        self._modal = None
        self.releaseMouse()
        if not confirm:
            if m.get("edit") is not None:
                m["edit"].restore()
            for ob, init in m["objs"]:
                ob.matrix_world = init
        elif m.get("edit") is not None:
            bridge.undo_push({"G": "Move", "R": "Rotate", "S": "Resize"}[m["kind"]])
        else:
            ts = bpy.context.scene.tool_settings
            if ts.use_keyframe_insert_auto:
                path = {"G": "location", "R": "rotation_euler", "S": "scale"}[m["kind"]]
                for ob, _init in m["objs"]:
                    try:
                        if path == "rotation_euler" and ob.rotation_mode == "QUATERNION":
                            path = "rotation_quaternion"
                        ob.keyframe_insert(path)
                    except Exception:
                        pass
            bridge.undo_push({"G": "Move", "R": "Rotate", "S": "Resize"}[m["kind"]])
        self.request_redraw()
        self.update()

    # ------------------------------------------------------------ události
    def enterEvent(self, ev):
        # jako Blender: klávesy patří editoru pod myší (kromě rozepsané konzole)
        fw = QtWidgets.QApplication.focusWidget()
        typing = isinstance(fw, QtWidgets.QLineEdit) and fw.text() and not isinstance(
            fw.parent(), QtWidgets.QAbstractSpinBox)
        if not typing:
            self.setFocus()
            win = self.window()
            if not win.isActiveWindow():   # plovoucí dock = samostatné okno
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
            self._press_pos = pos
        elif b == QtCore.Qt.RightButton:
            self._context_menu(ev.globalPosition().toPoint())

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._modal:
            self._modal_update(pos)
            return
        if self._nav and self._last is not None:
            d = pos - self._last
            self._last = pos
            if self._nav == "orbit":
                self._orbit(d.x(), d.y())
            elif self._nav == "pan":
                self._pan(d.x(), d.y())
            else:
                self._zoom(1.01 ** d.y())
            self.update()
        elif self._press_pos is not None:
            if (pos - self._press_pos).manhattanLength() > 5:
                self._box = (self._press_pos, pos)
                self.update()

    def mouseReleaseEvent(self, ev):
        pos = ev.position()
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
        trackpad = not pd.isNull()  # pixelDelta posílají jen touchpady
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
        ctrl = bool(mods & QtCore.Qt.ControlModifier)
        shift = bool(mods & QtCore.Qt.ShiftModifier)
        alt = bool(mods & QtCore.Qt.AltModifier)
        K = QtCore.Qt
        digit = digit_of(ev)
        if digit is not None:
            key = int(K.Key_0) + digit   # sjednotit s číselnou řadou
        edit_mesh = bpy.context.mode == "EDIT_MESH"
        if edit_mesh and not keypad and not ctrl and key in (K.Key_1, K.Key_2, K.Key_3):
            editmesh.set_select_mode(key == K.Key_1, key == K.Key_2, key == K.Key_3)
            self.selection_edited.emit()
            self.request_redraw()
            return
        if edit_mesh and key == K.Key_E and not ctrl:
            if "FINISHED" in bridge.run_op("mesh.extrude_region"):
                self.start_modal("G")
            return
        if edit_mesh and key == K.Key_D and shift:
            if "FINISHED" in bridge.run_op("mesh.duplicate"):
                self.start_modal("G")
            return
        if edit_mesh and key == K.Key_F and not ctrl:
            bridge.run_op("mesh.edge_face_add")
            return
        if edit_mesh and key == K.Key_L and ctrl:
            bridge.run_op("mesh.select_linked")
            return
        if edit_mesh and key == K.Key_I and ctrl:
            bridge.run_op("mesh.select_all", {"action": "INVERT"})
            return
        if edit_mesh and key == K.Key_H:
            bridge.run_op("mesh.reveal" if alt else "mesh.hide", {} if alt else {"unselected": shift})
            return
        if edit_mesh and key in (K.Key_X, K.Key_Delete) and not ctrl:
            from .qt_ui import LazyMenu
            LazyMenu("VIEW3D_MT_edit_mesh_delete", self).exec(QtGui.QCursor.pos())
            return
        if edit_mesh and key == K.Key_U and not ctrl:
            from .qt_ui import LazyMenu
            LazyMenu("VIEW3D_MT_uv_map", self).exec(QtGui.QCursor.pos())
            return
        # numerická klávesnice s vypnutým NumLockem posílá šipky
        if keypad and key in (K.Key_Down, K.Key_Left, K.Key_Right, K.Key_Up):
            key = {K.Key_Down: K.Key_2, K.Key_Left: K.Key_4, K.Key_Right: K.Key_6, K.Key_Up: K.Key_8}[key]
        step = 15 * DEG
        if key in (K.Key_2, K.Key_4, K.Key_6, K.Key_8) and (keypad or not shift):
            if ctrl:   # Ctrl + 2/4/6/8 = posun pohledu
                d = {K.Key_2: (0, -60), K.Key_8: (0, 60), K.Key_4: (60, 0), K.Key_6: (-60, 0)}[key]
                self._pan(*d)
                self.update()
            else:      # 2/8 = nahoru/dolů, 4/6 = doleva/doprava po 15°
                self.orbit_step(*{K.Key_2: (0, step), K.Key_8: (0, -step),
                                  K.Key_4: (-step, 0), K.Key_6: (step, 0)}[key])
            return
        if key == K.Key_9 and (keypad or not shift):   # pohled z opačné strany
            self.orbit_step(math.pi, math.pi - 2 * self.pitch)
            return
        if key == K.Key_1 and (keypad or not shift):
            self.set_view("BACK" if ctrl else "FRONT")
        elif key == K.Key_3 and (keypad or not shift):
            self.set_view("LEFT" if ctrl else "RIGHT")
        elif key == K.Key_7 and (keypad or not shift):
            self.set_view("BOTTOM" if ctrl else "TOP")
        elif key == K.Key_0 and (keypad or not shift):
            self.set_view("CAMERA")
        elif key == K.Key_5:
            self.toggle_ortho()
        elif key == K.Key_Period:
            self.frame_selected()
        elif key == K.Key_Home:
            self.frame_all()
        elif key == K.Key_G and not ctrl:
            self.start_modal("G")
        elif key == K.Key_R and not ctrl:
            self.start_modal("R")
        elif key == K.Key_S and not ctrl:
            self.start_modal("S")
        elif key == K.Key_D and shift:
            if bridge.run_op("object.duplicate") == {"FINISHED"}:
                self.start_modal("G")
        elif key in (K.Key_X, K.Key_Delete) and not ctrl:
            bridge.run_op("object.delete" if bpy.context.mode == "OBJECT" else "mesh.delete")
        elif key == K.Key_A and shift:
            self._add_menu()
        elif key == K.Key_A and alt:
            bridge.run_op("object.select_all" if bpy.context.mode == "OBJECT" else "mesh.select_all",
                          {"action": "DESELECT"})
        elif key == K.Key_A:
            bridge.run_op("object.select_all" if bpy.context.mode == "OBJECT" else "mesh.select_all",
                          {"action": "SELECT"})
        elif key == K.Key_I and ctrl:
            bridge.run_op("object.select_all", {"action": "INVERT"})
        elif key == K.Key_H and alt:
            bridge.run_op("object.hide_view_clear")
        elif key == K.Key_H:
            bridge.run_op("object.hide_view_set", {"unselected": shift})
        elif key == K.Key_Tab:
            bridge.run_op("object.editmode_toggle")
        elif key == K.Key_Z and not ctrl:
            self._shading_pie()
        else:
            super().keyPressEvent(ev)
            return
        self.update()

    def focusNextPrevChild(self, _next):
        return False  # Tab patří viewportu (edit mód)

    # ------------------------------------------------------------ kontextová menu
    def _context_menu(self, gpos):
        from .qt_ui import LazyMenu
        mid = "VIEW3D_MT_object_context_menu" if bpy.context.mode == "OBJECT" else "VIEW3D_MT_edit_mesh_context_menu"
        LazyMenu(mid, self).exec(gpos)

    def _add_menu(self):
        from .qt_ui import LazyMenu
        mid = "VIEW3D_MT_add" if bpy.context.mode == "OBJECT" else "VIEW3D_MT_mesh_add"
        LazyMenu(mid, self).exec(QtGui.QCursor.pos())

    def _shading_pie(self):
        m = QtWidgets.QMenu(self)
        for kind, label in (("WIREFRAME", "Drátový model"), ("SOLID", "Solid"),
                            ("MATERIAL", "Náhled materiálu"), ("RENDERED", "Renderovaný")):
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

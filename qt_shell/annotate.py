"""Annotate, Measure and Add tools of the 3D viewport (like Blender's toolbar in Object Mode).

- Annotate (variants Annotate / Annotate Line / Annotate Polygon / Annotate Eraser): notes drawn over
  the scene. They are stored like Blender stores them – in the scene's annotation data block
  (`scene.annotation`, layers → frames → strokes) – so they are saved with the .blend file and Blender
  shows them too. Placement (tool header): 3D Cursor (on the plane through the 3D cursor facing the
  view), View (fixed to the screen) or Surface (on the objects under the mouse).
  Blender's offscreen drawing doesn't include annotations, so Qt Shell draws them itself.
- Measure: drag to add a ruler (points snap onto surfaces under the mouse), drag an end to move it,
  drag from the middle of a ruler to measure an angle (protractor), Ctrl snaps to the nearest vertex,
  Delete / X removes the active ruler. Rulers live in the annotation layer "RulerData3D" like Blender's.
- Add Cube / Cone / Cylinder / UV Sphere / Ico Sphere: drag the base on a surface or the grid, release,
  move the mouse for the height, click to create (Shift: fixed aspect, Alt: from the centre; right click /
  Esc cancels).

The viewport calls `ViewTools.press / move / release / key / paint`; the tool header (`ToolHeader`)
shows the options of the active tool in the 3D header.
"""
import math

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, keymap, pytips, theme

RULER_LAYER = "RulerData3D"
NOTE_COLOR = (0.38, 0.61, 0.78)        # Blender's default colour of a new annotation layer
ERASER_RADIUS = 20                      # unscaled px
PRIMITIVES = {                          # variant → (object name, Blender operator)
    "CUBE": ("Cube", "mesh.primitive_cube_add"),
    "CONE": ("Cone", "mesh.primitive_cone_add"),
    "CYLINDER": ("Cylinder", "mesh.primitive_cylinder_add"),
    "UV_SPHERE": ("Sphere", "mesh.primitive_uv_sphere_add"),
    "ICO_SPHERE": ("Icosphere", "mesh.primitive_ico_sphere_add"),
}


def _settings():
    return QtCore.QSettings("QtShell", "QtShell")


def add_option(name, default):
    return str(_settings().value(f"viewport/add_{name}", default))


def set_add_option(name, value):
    _settings().setValue(f"viewport/add_{name}", value)


# ---------------------------------------------------------------- annotation data
def layer_name(layer):
    return getattr(layer, "info", None) or getattr(layer, "name", "") or ""


def scene_annotation(create=False):
    sc = bpy.context.scene
    an = getattr(sc, "annotation", None)
    if an is None and create:
        an = bpy.data.annotations.new("Annotations")
        sc.annotation = an
    return an


def note_layer(create=False):
    """The layer new annotation strokes go to (the active one; never the ruler layer)."""
    an = scene_annotation(create)
    if an is None:
        return None
    act = getattr(an.layers, "active", None)
    if act is not None and layer_name(act) != RULER_LAYER:
        return act
    for lay in reversed(list(an.layers)):
        if layer_name(lay) != RULER_LAYER:
            return lay
    if not create:
        return None
    try:
        lay = an.layers.new("Note", set_active=True)
    except TypeError:
        lay = an.layers.new("Note")
    try:
        lay.color = NOTE_COLOR
        lay.thickness = 3
    except Exception:
        pass
    return lay


def shown_frame(layer, frame=None):
    """The frame of a layer shown at the scene frame (the last one at or before it)."""
    cf = bpy.context.scene.frame_current if frame is None else frame
    best = None
    for f in layer.frames:
        if f.frame_number <= cf and (best is None or f.frame_number > best.frame_number):
            best = f
    return best


def draw_frame(layer):
    """The frame new strokes go to: the one at the current frame (created when missing, like Blender)."""
    cf = bpy.context.scene.frame_current
    f = shown_frame(layer, cf)
    if f is not None and (f.frame_number == cf or getattr(layer, "lock_frame", False)):
        return f
    return layer.frames.new(cf)


def _points(stroke):
    n = len(stroke.points)
    co = np.zeros(n * 3, dtype=np.float64)
    if n:
        stroke.points.foreach_get("co", co)
    return co.reshape(n, 3)


def _new_stroke(frame, coords, mode="3DSPACE"):
    st = frame.strokes.new()
    try:
        st.display_mode = mode
    except Exception:
        pass
    st.points.add(len(coords))
    for p, co in zip(st.points, coords):
        p.co = co
        if hasattr(p, "pressure"):
            p.pressure = 1.0
    return st


def add_stroke(coords, mode="3DSPACE"):
    lay = note_layer(create=True)
    st = _new_stroke(draw_frame(lay), coords, mode)
    return st


def _ruler_layer(create=False):
    an = scene_annotation(create)
    if an is None:
        return None
    for lay in an.layers:
        if layer_name(lay) == RULER_LAYER:
            return lay
    if not create:
        return None
    act = getattr(an.layers, "active", None)
    try:
        lay = an.layers.new(RULER_LAYER, set_active=False)
    except TypeError:
        lay = an.layers.new(RULER_LAYER)
    try:
        if act is not None:
            an.layers.active = act
    except Exception:
        pass
    return lay


def ruler_strokes(create=False):
    lay = _ruler_layer(create)
    if lay is None:
        return None, []
    fr = shown_frame(lay)
    if fr is None:
        if not create:
            return None, []
        fr = lay.frames.new(bpy.context.scene.frame_current)
    return fr, [s for s in fr.strokes if len(s.points) in (2, 3)]


# ---------------------------------------------------------------- units
def length_text(value):
    us = bpy.context.scene.unit_settings
    if us.system == "NONE":
        return f"{value:.4g}"
    try:
        return bpy.utils.units.to_string(us.system, "LENGTH", value * us.scale_length, precision=3,
                                         split_unit=us.use_separate, compatible_unit=False)
    except Exception:
        return f"{value * us.scale_length:.3f} m"


def angle_text(rad):
    us = bpy.context.scene.unit_settings
    if us.system_rotation == "RADIANS":
        return f"{rad:.4f} rad"
    return f"{math.degrees(rad):.2f}°"


# ---------------------------------------------------------------- placing points
def _project_np(vp, co, mats):
    """Screen positions of (n, 3) world points → (n, 2) array and a mask of the visible ones."""
    w, h = vp.width(), vp.height()
    vm, pm = mats
    m = np.array(pm @ vm, dtype=np.float64)
    hom = np.c_[co, np.ones(len(co))] @ m.T
    ok = hom[:, 3] > 1e-6
    wv = np.where(ok, hom[:, 3], 1.0)
    xy = np.c_[(hom[:, 0] / wv + 1) * 0.5 * w, (1 - hom[:, 1] / wv) * 0.5 * h]
    return xy, ok


def _plane_hit(origin, direction, p0, n):
    d = direction.dot(n)
    if abs(d) < 1e-9:
        return None
    t = (p0 - origin).dot(n) / d
    return origin + direction * t


def surface_hit(vp, pos):
    """(location, normal, object, matrix, face index) of the surface under pos, or None."""
    ctx = bpy.context
    origin, direction = vp.ray(pos.x(), pos.y())
    try:
        hit, loc, nor, idx, ob, mat = ctx.scene.ray_cast(ctx.evaluated_depsgraph_get(), origin, direction)
    except Exception:
        return None
    return (loc, nor, ob, mat, idx) if hit else None


def cursor_plane_point(vp, pos, through=None):
    """The point under pos on the plane through `through` (default: the 3D cursor) facing the view."""
    origin, direction = vp.ray(pos.x(), pos.y())
    p0 = Vector(through) if through is not None else bpy.context.scene.cursor.location.copy()
    _r, _u, fwd = vp.view_vectors()
    return _plane_hit(origin, direction, p0, fwd)


def snap_vertex(hit):
    """Ctrl: the vertex of the face under the mouse nearest to the hit point."""
    loc, _n, ob, mat, idx = hit
    try:
        ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
        me = ev.data
        if not hasattr(me, "polygons") or idx < 0 or idx >= len(me.polygons):
            return loc
        best = None
        for vi in me.polygons[idx].vertices:
            w = mat @ me.vertices[vi].co
            if best is None or (w - loc).length < (best - loc).length:
                best = w
        return best if best is not None else loc
    except Exception:
        return loc


def place_3d(vp, pos, snap=False, through=None):
    hit = surface_hit(vp, pos)
    if hit is not None:
        return snap_vertex(hit) if snap else hit[0]
    return cursor_plane_point(vp, pos, through)


# ---------------------------------------------------------------- drawing
def paint_annotations(vp, p, mats):
    an = scene_annotation()
    if an is None:
        return
    sp, _r = vp.space()
    if sp is not None:
        try:
            if not sp.overlay.show_overlays or not sp.overlay.show_annotation:
                return
        except Exception:
            pass
    w, h = vp.width(), vp.height()
    for lay in an.layers:
        if layer_name(lay) == RULER_LAYER or getattr(lay, "annotation_hide", False):
            continue
        fr = shown_frame(lay)
        if fr is None or not len(fr.strokes):
            continue
        c = lay.color
        col = QtGui.QColor.fromRgbF(c[0], c[1], c[2], max(0.0, min(1.0, getattr(lay, "annotation_opacity", 1.0))))
        pen = QtGui.QPen(col, max(1.0, lay.thickness * theme.ui_scale))
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        for st in fr.strokes:
            co = _points(st)
            if not len(co):
                continue
            mode = getattr(st, "display_mode", "3DSPACE")
            if mode == "SCREEN":
                xy = np.c_[co[:, 0] / 100.0 * w, h - co[:, 1] / 100.0 * h]
                ok = np.ones(len(co), dtype=bool)
            elif mode == "3DSPACE":
                xy, ok = _project_np(vp, co, mats)
            else:
                continue
            _polyline(p, xy, ok)


def _polyline(p, xy, ok):
    run = []
    for (x, y), good in zip(xy.tolist(), ok.tolist()):
        if good:
            run.append(QtCore.QPointF(x, y))
            continue
        if run:
            _draw_run(p, run)
        run = []
    if run:
        _draw_run(p, run)


def _draw_run(p, run):
    if len(run) == 1:
        p.drawPoint(run[0])
    else:
        p.drawPolyline(QtGui.QPolygonF(run))


def _label(p, at, text, active=False):
    f = p.font()
    f.setPixelSize(theme.fs(12))
    p.setFont(f)
    fm = p.fontMetrics()
    r = QtCore.QRectF(fm.boundingRect(text)).adjusted(-theme.px(4), -theme.px(2), theme.px(4), theme.px(2))
    r.moveCenter(at)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor(0, 0, 0, 170))
    p.drawRoundedRect(r, theme.px(3), theme.px(3))
    p.setPen(QtGui.QColor("#ffe066") if active else QtGui.QColor(240, 240, 240))
    p.drawText(r, QtCore.Qt.AlignCenter, text)


# ---------------------------------------------------------------- the tools
class ViewTools:
    """Mouse / key handling and drawing of Annotate, Measure and Add in one 3D view."""

    def __init__(self, vp):
        self.vp = vp
        self.stroke = None          # screen points of the annotation being drawn
        self.poly = None            # Annotate Polygon: screen points clicked so far
        self.erasing = False
        self.erased = False
        self.ruler_drag = None      # {"stroke": index, "point": index}
        self.ruler_active = None    # index of the active ruler stroke
        self.ruler_hover = None     # (stroke, point) under the mouse
        self.add = None             # the Add tool's interaction
        self.mouse = None

    # --- state
    @property
    def tools(self):
        return self.vp.tools

    def tool(self):
        t = self.tools.tool
        if t == "ADD" and bpy.context.mode != "OBJECT":
            return None
        return t if t in ("ANNOTATE", "MEASURE", "ADD") else None

    def busy(self):
        return bool(self.stroke is not None or self.poly or self.erasing or self.ruler_drag or self.add)

    def cancel(self):
        if self.add is not None or self.poly:
            self.add = None
            self.poly = None
            self.vp.update()
            return True
        return False

    def _mods(self, ev):
        m = ev.modifiers()
        return bool(m & QtCore.Qt.ShiftModifier), bool(m & QtCore.Qt.ControlModifier), bool(m & QtCore.Qt.AltModifier)

    # --- mouse
    def press(self, ev, pos):
        tool = self.tool()
        if tool is None:
            return False
        b = ev.button()
        if b == QtCore.Qt.RightButton:
            if self.poly:
                self._finish_polygon()
                return True
            return self.cancel()
        if b != QtCore.Qt.LeftButton:
            return False
        self.mouse = pos
        if tool == "ANNOTATE":
            v = self.tools.variant("ANNOTATE")
            if v == "ERASER":
                self.erasing = True
                self.erased = False
                self._erase(pos)
            elif v == "POLYGON":
                if self.poly is None:
                    self.poly = [QtCore.QPointF(pos)]
                else:
                    self.poly[-1] = QtCore.QPointF(pos)     # the point following the mouse becomes fixed
                self.poly.append(QtCore.QPointF(pos))
            else:
                self.stroke = [QtCore.QPointF(pos)]
            self.vp.update()
            return True
        if tool == "MEASURE":
            self._ruler_press(pos, self._mods(ev)[1])
            return True
        if tool == "ADD":
            self._add_press(ev, pos)
            return True
        return False

    def double_click(self, ev, pos):
        if self.poly and ev.button() == QtCore.Qt.LeftButton:
            self._finish_polygon()
            return True
        return False

    def move(self, ev, pos):
        tool = self.tool()
        if tool is None:
            return False
        self.mouse = pos
        if tool == "ANNOTATE":
            if self.erasing:
                self._erase(pos)
            elif self.stroke is not None:
                if self.tools.variant("ANNOTATE") == "LINE":
                    self.stroke[1:] = [QtCore.QPointF(pos)]
                else:
                    last = self.stroke[-1]
                    if abs(pos.x() - last.x()) + abs(pos.y() - last.y()) >= 2:
                        self.stroke.append(QtCore.QPointF(pos))
            elif self.poly:
                self.poly[-1] = QtCore.QPointF(pos)
            self.vp.update()
            return self.erasing or self.stroke is not None or bool(self.poly) or \
                self.tools.variant("ANNOTATE") == "ERASER"
        if tool == "MEASURE":
            if self.ruler_drag is not None:
                self._ruler_move(pos, self._mods(ev)[1])
            else:
                hov = self._ruler_at(pos)
                if hov != self.ruler_hover:
                    self.ruler_hover = hov
                    self.vp.update()
            return self.ruler_drag is not None
        if tool == "ADD":
            if self.add is not None:
                self._add_move(ev, pos)
                return True
            self.vp.update()
        return False

    def release(self, ev, pos):
        tool = self.tool()
        if tool is None or ev.button() != QtCore.Qt.LeftButton:
            return False
        if tool == "ANNOTATE":
            if self.erasing:
                self.erasing = False
                if self.erased:
                    bridge.undo_push("Annotation Erase")
                self.vp.update()
                return True
            if self.stroke is not None:
                pts, self.stroke = self.stroke, None
                if self.tools.variant("ANNOTATE") == "LINE" and len(pts) < 2:
                    pts = []
                self._commit(pts)
                return True
            return bool(self.poly)
        if tool == "MEASURE":
            if self.ruler_drag is not None:
                self.ruler_drag = None
                bridge.undo_push("Measure")
                self.vp.update()
            return True
        if tool == "ADD":
            if self.add is not None and self.add["phase"] == "BASE":
                self._add_base_done(pos)
            return True
        return False

    def key(self, ev, H):
        """Keys while a tool is busy (Enter / Esc) and the Measure tool's Delete."""
        k = ev.key()
        if self.poly and k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Escape,
                               QtCore.Qt.Key_Space):
            self._finish_polygon()
            return True
        if self.add is not None and k == QtCore.Qt.Key_Escape:
            return self.cancel()
        if self.add is not None and self.add["phase"] == "HEIGHT" and k in (QtCore.Qt.Key_Return,
                                                                          QtCore.Qt.Key_Enter):
            self._add_create()
            return True
        if self.tool() == "MEASURE" and H("view3d.ruler_remove"):
            self.remove_ruler()          # never falls through to deleting objects
            return True
        return False

    def wheel(self, ev):
        if self.tool() == "ANNOTATE" and self.tools.variant("ANNOTATE") == "ERASER" and \
                ev.modifiers() & QtCore.Qt.ControlModifier:
            self.tools.set_eraser_radius(self.tools.eraser_radius * (1.15 ** (ev.angleDelta().y() / 120.0)))
            self.vp.update()
            return True
        return False

    # --- annotate
    def _to_world(self, pts):
        """Screen points → (coords, display mode) by the placement setting."""
        vp = self.vp
        ts = bpy.context.scene.tool_settings
        place = getattr(ts, "annotation_stroke_placement_view3d", "CURSOR")
        if place == "VIEW":
            w, h = max(1, vp.width()), max(1, vp.height())
            return [(p.x() / w * 100.0, (h - p.y()) / h * 100.0, 0.0) for p in pts], "SCREEN"
        out = []
        for p in pts:
            q = place_3d(vp, p) if place == "SURFACE" else cursor_plane_point(vp, p)
            if q is not None:
                out.append(tuple(q))
        return out, "3DSPACE"

    def _commit(self, pts):
        if not pts:
            return
        if len(pts) == 1:
            pts = [pts[0], QtCore.QPointF(pts[0].x() + 0.5, pts[0].y())]   # a dot
        coords, mode = self._to_world(pts)
        if len(coords) < 2:
            return
        try:
            add_stroke(coords, mode)
            bridge.undo_push("Annotate")
        except Exception as ex:
            bridge.log(f"Annotate: {ex}", "ERROR")
        self.vp.update()

    def _finish_polygon(self):
        pts, self.poly = self.poly, None
        if pts and len(pts) > 2:
            self._commit(pts[:-1])         # the last point follows the mouse
        self.vp.update()

    def _erase(self, pos):
        an = scene_annotation()
        if an is None:
            return
        r = self.tools.eraser_radius * theme.ui_scale
        mats = self.vp.matrices(self.vp.width(), self.vp.height())
        w, h = self.vp.width(), self.vp.height()
        for lay in an.layers:
            if layer_name(lay) == RULER_LAYER or getattr(lay, "lock", False) or \
                    getattr(lay, "annotation_hide", False):
                continue
            fr = shown_frame(lay)
            if fr is None:
                continue
            for st in list(fr.strokes):
                co = _points(st)
                if not len(co):
                    continue
                mode = getattr(st, "display_mode", "3DSPACE")
                if mode == "SCREEN":
                    xy = np.c_[co[:, 0] / 100.0 * w, h - co[:, 1] / 100.0 * h]
                    ok = np.ones(len(co), dtype=bool)
                elif mode == "3DSPACE":
                    xy, ok = _project_np(self.vp, co, mats)
                else:
                    continue
                hit = ok & (((xy[:, 0] - pos.x()) ** 2 + (xy[:, 1] - pos.y()) ** 2) <= r * r)
                if not hit.any():
                    continue
                # split the stroke into the parts that stay
                parts, cur = [], []
                for i, gone in enumerate(hit.tolist()):
                    if gone:
                        if len(cur) > 1:
                            parts.append(cur)
                        cur = []
                    else:
                        cur.append(tuple(co[i]))
                if len(cur) > 1:
                    parts.append(cur)
                fr.strokes.remove(st)
                for part in parts:
                    _new_stroke(fr, part, mode)
                self.erased = True

    # --- measure
    def _ruler_screen(self, mats=None):
        _fr, strokes = ruler_strokes()
        mats = mats or self.vp.matrices(self.vp.width(), self.vp.height())
        out = []
        for st in strokes:
            pts = [Vector(p.co) for p in st.points]
            out.append((pts, [self.vp.project(q, mats) for q in pts]))
        return out

    def _ruler_at(self, pos):
        """(stroke, point) of the ruler point under pos; point 'MID' = the middle of a 2-point ruler."""
        d = theme.px(9)
        best = None
        for si, (_pts, sp) in enumerate(self._ruler_screen()):
            for pi, q in enumerate(sp):
                if q is not None:
                    dist = math.hypot(q.x() - pos.x(), q.y() - pos.y())
                    if dist <= d and (best is None or dist < best[0]):
                        best = (dist, (si, pi))
            if len(sp) == 2 and sp[0] is not None and sp[1] is not None:
                mid = (sp[0] + sp[1]) / 2
                dist = math.hypot(mid.x() - pos.x(), mid.y() - pos.y())
                if dist <= d and (best is None or dist < best[0]):
                    best = (dist, (si, "MID"))
        return best[1] if best else None

    def _ruler_press(self, pos, snap):
        hit = self._ruler_at(pos)
        fr, strokes = ruler_strokes(create=True)
        if hit is not None:
            si, pi = hit
            st = strokes[si]
            if pi == "MID":                     # 2-point ruler → protractor: [a, vertex, b]
                a, b = Vector(st.points[0].co), Vector(st.points[1].co)
                st.points.add(1)
                st.points[0].co = a
                st.points[1].co = (a + b) / 2
                st.points[2].co = b
                pi = 1
            self.ruler_drag = {"stroke": si, "point": pi}
            self.ruler_active = si
            self.vp.update()
            return
        q = place_3d(self.vp, pos, snap)
        if q is None:
            return
        _new_stroke(fr, [tuple(q), tuple(q)])
        self.ruler_active = len(strokes)
        self.ruler_drag = {"stroke": len(strokes), "point": 1}
        self.vp.update()

    def _ruler_move(self, pos, snap):
        _fr, strokes = ruler_strokes()
        d = self.ruler_drag
        if d["stroke"] >= len(strokes):
            self.ruler_drag = None
            return
        st = strokes[d["stroke"]]
        old = Vector(st.points[d["point"]].co)
        q = place_3d(self.vp, pos, snap, through=old)
        if q is not None:
            st.points[d["point"]].co = q
        self.vp.update()

    def remove_ruler(self):
        fr, strokes = ruler_strokes()
        i = self.ruler_active if self.ruler_active is not None else (len(strokes) - 1 if strokes else None)
        if fr is None or i is None or i >= len(strokes):
            return False
        fr.strokes.remove(strokes[i])
        self.ruler_active = None
        self.ruler_hover = None
        bridge.undo_push("Remove Ruler")
        self.vp.update()
        return True

    def _paint_rulers(self, p, mats):
        sc = theme.ui_scale
        for si, (pts, sp) in enumerate(self._ruler_screen(mats)):
            if any(q is None for q in sp):
                continue
            active = si == self.ruler_active
            col = QtGui.QColor("#ffffff") if not active else QtGui.QColor("#ffe066")
            p.setBrush(QtCore.Qt.NoBrush)
            for a, b in zip(sp, sp[1:]):
                p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 160), 3.2 * sc))
                p.drawLine(a, b)
                p.setPen(QtGui.QPen(col, 1.4 * sc))
                p.drawLine(a, b)
            for pi, q in enumerate(sp):
                hov = self.ruler_hover == (si, pi)
                p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 200), 1))
                p.setBrush(QtGui.QColor("#ffe066") if hov else col)
                r = (4.5 if hov else 3.5) * sc
                p.drawEllipse(q, r, r)
            if len(pts) == 2:
                _label(p, (sp[0] + sp[1]) / 2 + QtCore.QPointF(0, -theme.px(12)), length_text((pts[1] - pts[0]).length),
                       active)
                if self.ruler_hover == (si, "MID"):
                    p.setPen(QtGui.QPen(QtGui.QColor("#ffe066"), 1.2 * sc))
                    p.setBrush(QtCore.Qt.NoBrush)
                    p.drawEllipse((sp[0] + sp[1]) / 2, 5 * sc, 5 * sc)
            else:
                a, c, b = pts
                va, vb = a - c, b - c
                ang = va.angle(vb, 0.0) if va.length > 1e-9 and vb.length > 1e-9 else 0.0
                # the arc in screen space
                a2 = math.atan2(sp[0].y() - sp[1].y(), sp[0].x() - sp[1].x())
                b2 = math.atan2(sp[2].y() - sp[1].y(), sp[2].x() - sp[1].x())
                span = (b2 - a2 + math.pi) % (2 * math.pi) - math.pi
                R = theme.px(28)
                arc = QtGui.QPainterPath()
                rect = QtCore.QRectF(sp[1].x() - R, sp[1].y() - R, 2 * R, 2 * R)
                arc.arcMoveTo(rect, -math.degrees(a2))
                arc.arcTo(rect, -math.degrees(a2), -math.degrees(span))
                p.setBrush(QtCore.Qt.NoBrush)
                p.setPen(QtGui.QPen(col, 1.2 * sc))
                p.drawPath(arc)
                mid = a2 + span / 2
                _label(p, sp[1] + QtCore.QPointF(math.cos(mid), math.sin(mid)) * (R + theme.px(18)),
                       angle_text(ang), active)

    # --- add primitive
    def _base_plane(self, pos):
        """(origin, u, v, n) of the plane the base is drawn on."""
        vp = self.vp
        origin, direction = vp.ray(pos.x(), pos.y())
        right, _up, fwd = vp.view_vectors()
        if add_option("orientation", "SURFACE") == "SURFACE":
            hit = surface_hit(vp, pos)
            if hit is not None:
                loc, n = Vector(hit[0]), Vector(hit[1]).normalized()
                u = right - n * right.dot(n)
                if u.length < 1e-6:
                    u = n.orthogonal()
                u.normalize()
                return loc, u, n.cross(u).normalized(), n
        if abs(direction.z) > 0.02:             # the grid (ground plane)
            q = _plane_hit(origin, direction, Vector((0, 0, 0)), Vector((0, 0, 1)))
            if q is not None and (q - origin).dot(direction) > 0:
                return q, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
        q = cursor_plane_point(vp, pos)
        if q is None:
            return None
        n = -fwd.normalized()
        u = right.normalized()
        return q, u, n.cross(u).normalized(), n

    def _uv(self, pos):
        a = self.add
        origin, direction = self.vp.ray(pos.x(), pos.y())
        q = _plane_hit(origin, direction, a["o"], a["n"])
        if q is None:
            return None
        d = q - a["o"]
        return d.dot(a["u"]), d.dot(a["v"])

    def _add_press(self, ev, pos):
        if self.add is not None and self.add["phase"] == "HEIGHT":
            self._add_create()
            return
        plane = self._base_plane(pos)
        if plane is None:
            return
        o, u, v, n = plane
        self.add = {"phase": "BASE", "o": o, "u": u, "v": v, "n": n, "b": (0.0, 0.0), "h": 0.0,
                    "press": QtCore.QPointF(pos), "kind": self.tools.variant("ADD")}
        self._add_move(ev, pos)

    def _base_rect(self, ev=None):
        """(min u, min v, max u, max v) of the base in plane coordinates (Shift: fixed aspect, Alt: centre)."""
        a = self.add
        bu, bv = a["b"]
        shift, _ctrl, alt = self._mods(ev) if ev is not None else (a.get("shift"), False, a.get("alt"))
        fixed = shift != (add_option("aspect", "FREE") == "FIXED")
        center = alt != (add_option("base", "CORNER") == "CENTER")
        if fixed:
            m = max(abs(bu), abs(bv))
            bu, bv = math.copysign(m, bu or 1), math.copysign(m, bv or 1)
        if center:
            return -abs(bu), -abs(bv), abs(bu), abs(bv)
        return min(0, bu), min(0, bv), max(0, bu), max(0, bv)

    def _add_move(self, ev, pos):
        a = self.add
        if a["phase"] == "BASE":
            uv = self._uv(pos)
            if uv is not None:
                a["b"] = uv
            a["shift"], _c, a["alt"] = self._mods(ev)
            a["rect"] = self._base_rect(ev)
        else:
            # height: the point on the line through the base centre along the normal nearest to the mouse ray
            u0, v0, u1, v1 = a["rect"]
            c = a["o"] + a["u"] * ((u0 + u1) / 2) + a["v"] * ((v0 + v1) / 2)
            origin, d = self.vp.ray(pos.x(), pos.y())
            n = a["n"]
            w0 = c - origin
            b = n.dot(d)
            den = 1 - b * b
            if den > 1e-6:
                a["h"] = (b * d.dot(w0) - n.dot(w0)) / den
        self.vp.update()

    def _add_base_done(self, pos):
        a = self.add
        u0, v0, u1, v1 = a.get("rect", (0, 0, 0, 0))
        moved = (pos - a["press"]).manhattanLength() > 4
        if not moved or (u1 - u0) < 1e-5 or (v1 - v0) < 1e-5:
            self.add = None              # a click without a base: nothing
            self.vp.update()
            return
        a["phase"] = "HEIGHT"
        self.vp.status.emit("Move the mouse for the height, click to create (right click / Esc cancels)")

    def _box(self):
        """(centre, rotation matrix 3×3, size (x, y, z)) of the box being added."""
        a = self.add
        u0, v0, u1, v1 = a.get("rect", (0, 0, 0, 0))
        h = a["h"] if a["phase"] == "HEIGHT" else 0.0
        su, sv = u1 - u0, v1 - v0
        if a["phase"] == "HEIGHT" and abs(h) < 1e-6:
            h = 0.0
        u, v, n = a["u"], a["v"], a["n"]
        base_c = a["o"] + u * ((u0 + u1) / 2) + v * ((v0 + v1) / 2)
        if add_option("height", "CORNER") == "CENTER":
            center = base_c
            sz = abs(h) * 2
        else:
            center = base_c + n * (h / 2)
            sz = abs(h)
        if h < 0:
            v, n = -v, -n
        rot = Matrix((u, v, n)).transposed()
        return center, rot, (su, sv, sz)

    def _add_create(self):
        a, kind = self.add, self.add["kind"]
        center, rot, (sx, sy, sz) = self._box()
        self.add = None
        if sz < 1e-5:
            sz = min(sx, sy)
            center = center + rot.col[2] * (sz / 2)
        try:
            ob = create_primitive(kind, center, rot, (sx, sy, sz))
            self.vp.status.emit(f"Added {ob.name}")
            bridge.undo_push(f"Add {PRIMITIVES[kind][0]}")
        except Exception as ex:
            bridge.log(f"Add {kind}: {ex}", "ERROR")
        self.vp.selection_edited.emit()
        self.vp.request_redraw()
        self.vp.update()

    def _paint_add(self, p, mats):
        vp = self.vp
        sc = theme.ui_scale
        if self.add is None:
            if self.mouse is not None and vp.underMouse():     # a cross where the base will start
                p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 200), 1.2 * sc))
                r = theme.px(6)
                p.drawLine(self.mouse + QtCore.QPointF(-r, 0), self.mouse + QtCore.QPointF(r, 0))
                p.drawLine(self.mouse + QtCore.QPointF(0, -r), self.mouse + QtCore.QPointF(0, r))
            return
        center, rot, (sx, sy, sz) = self._box()
        corners = []
        for z in (-0.5, 0.5):
            for x, y in ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)):
                corners.append(vp.project(center + rot @ Vector((x * sx, y * sy, z * sz)), mats))
        edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
        p.setBrush(QtCore.Qt.NoBrush)
        for i, j in edges:
            if corners[i] is None or corners[j] is None:
                continue
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 150), 3 * sc))
            p.drawLine(corners[i], corners[j])
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1.3 * sc, QtCore.Qt.DashLine))
            p.drawLine(corners[i], corners[j])
        name = PRIMITIVES[self.add["kind"]][0]
        txt = f"{name}: {length_text(sx)} × {length_text(sy)}"
        if self.add["phase"] == "HEIGHT":
            txt += f" × {length_text(sz)}"
        c = vp.project(center, mats)
        if c is not None:
            _label(p, c, txt)

    # --- painting
    def paint(self, p, mats):
        try:
            paint_annotations(self.vp, p, mats)
        except Exception as ex:
            bridge.log(f"Annotations: {ex}", "WARNING")
        tool = self.tool()
        sc = theme.ui_scale
        if tool == "ANNOTATE":
            lay = note_layer()
            c = lay.color if lay is not None else NOTE_COLOR
            col = QtGui.QColor.fromRgbF(c[0], c[1], c[2], 1.0)
            pen = QtGui.QPen(col, max(1.0, (lay.thickness if lay is not None else 3) * sc))
            pen.setCapStyle(QtCore.Qt.RoundCap)
            pen.setJoinStyle(QtCore.Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(QtCore.Qt.NoBrush)
            if self.stroke and len(self.stroke) > 1:
                p.drawPolyline(QtGui.QPolygonF(self.stroke))
            if self.poly:
                p.drawPolyline(QtGui.QPolygonF(self.poly))
                p.setBrush(col)
                for q in self.poly[:-1]:
                    p.drawEllipse(q, 2.5 * sc, 2.5 * sc)
            if self.tools.variant("ANNOTATE") == "ERASER" and self.mouse is not None and self.vp.underMouse():
                r = self.tools.eraser_radius * sc
                p.setBrush(QtGui.QColor(255, 255, 255, 18 if self.erasing else 0))
                p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1, QtCore.Qt.DashLine))
                p.drawEllipse(self.mouse, r, r)
        elif tool == "MEASURE":
            try:
                self._paint_rulers(p, mats)
            except Exception as ex:
                bridge.log(f"Rulers: {ex}", "WARNING")
        elif tool == "ADD":
            self._paint_add(p, mats)


def create_primitive(kind, center, rot, size):
    """A new mesh object (like Blender's Add tools) with its mesh sized `size`, placed at center / rot."""
    ctx = bpy.context
    name = PRIMITIVES[kind][0]
    bm = bmesh.new()
    try:
        if kind == "CUBE":
            bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
        elif kind == "CONE":
            bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=32, radius1=0.5, radius2=0.0,
                                  depth=1.0, calc_uvs=True)
        elif kind == "CYLINDER":
            bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=32, radius1=0.5, radius2=0.5,
                                  depth=1.0, calc_uvs=True)
        elif kind == "UV_SPHERE":
            bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=0.5, calc_uvs=True)
        else:
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.5, calc_uvs=True)
        bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
    finally:
        bm.free()
    ob = bpy.data.objects.new(name, me)
    coll = ctx.view_layer.active_layer_collection.collection
    coll.objects.link(ob)
    ob.matrix_world = Matrix.Translation(center) @ rot.to_4x4()
    for o in ctx.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    ctx.view_layer.objects.active = ob
    return ob


# ---------------------------------------------------------------- tool header (3D header)
class ToolHeader(QtWidgets.QWidget):
    """Options of the active tool in the 3D header (Blender shows them in its tool header):
    Annotate – colour, thickness, placement (and the eraser radius); Add – orientation, base, aspect and
    height; Measure – a hint."""

    def __init__(self, mw, parent):
        super().__init__(parent)
        from . import gizmo
        self.mw = mw
        self.state = gizmo.tool_state(mw.hub)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(theme.px(6), 0, theme.px(6), 0)
        lay.setSpacing(theme.px(4))
        # annotate
        self.ann = QtWidgets.QWidget(self)
        a = QtWidgets.QHBoxLayout(self.ann)
        a.setContentsMargins(0, 0, 0, 0)
        a.setSpacing(theme.px(4))
        self.color_btn = QtWidgets.QToolButton(self.ann)
        self.color_btn.setAutoRaise(True)
        self.color_btn.setToolTip("Colour of the annotation layer")
        pytips.tag(self.color_btn, "bpy.context.scene.annotation.layers.active.color = (0.38, 0.61, 0.78)")
        self.color_btn.clicked.connect(self._pick_color)
        a.addWidget(self.color_btn)
        self.thick = QtWidgets.QSpinBox(self.ann)
        self.thick.setRange(1, 10)
        self.thick.setPrefix("Thickness ")
        self.thick.setToolTip("Thickness of the annotation layer's strokes (px)")
        pytips.tag(self.thick, "bpy.context.scene.annotation.layers.active.thickness = 3")
        self.thick.valueChanged.connect(self._set_thickness)
        a.addWidget(self.thick)
        self.place = QtWidgets.QComboBox(self.ann)
        for ident, name in (("CURSOR", "3D Cursor"), ("VIEW", "View"), ("SURFACE", "Surface")):
            self.place.addItem(name, ident)
        self.place.setToolTip("Placement – where new strokes go: on the plane through the 3D cursor, fixed to the "
                              "view (screen) or on the surface of the objects under the mouse")
        pytips.tag(self.place, "bpy.context.scene.tool_settings.annotation_stroke_placement_view3d = 'CURSOR'")
        self.place.activated.connect(self._set_place)
        a.addWidget(self.place)
        self.radius = QtWidgets.QSpinBox(self.ann)
        self.radius.setRange(2, 200)
        self.radius.setPrefix("Radius ")
        self.radius.setSuffix(" px")
        self.radius.setToolTip("Eraser radius (Ctrl + mouse wheel in the view)")
        self.radius.valueChanged.connect(lambda v: self.state.set_eraser_radius(v))
        a.addWidget(self.radius)
        lay.addWidget(self.ann)
        # add primitive
        self.addw = QtWidgets.QWidget(self)
        b = QtWidgets.QHBoxLayout(self.addw)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(theme.px(4))
        self.add_combos = {}
        for opt, label, items, default, tip in (
                ("orientation", "Orientation", (("SURFACE", "Surface"), ("DEFAULT", "Default")), "SURFACE",
                 "Surface: the base lies on the face under the mouse; Default: on the grid"),
                ("base", "Base", (("CORNER", "Corner"), ("CENTER", "Center")), "CORNER",
                 "Where dragging the base starts (Alt switches while dragging)"),
                ("aspect", "Aspect", (("FREE", "Free"), ("FIXED", "Fixed")), "FREE",
                 "Fixed: a square base (Shift switches while dragging)"),
                ("height", "Height", (("CORNER", "Corner"), ("CENTER", "Center")), "CORNER",
                 "Center: the height grows to both sides of the base")):
            lab = QtWidgets.QLabel(label, self.addw)
            lab.setProperty("dim", True)
            b.addWidget(lab)
            c = QtWidgets.QComboBox(self.addw)
            for ident, name in items:
                c.addItem(name, ident)
            c.setCurrentIndex(max(0, c.findData(add_option(opt, default))))
            c.setToolTip(tip)
            c.activated.connect(lambda _i, o=opt, cb=c: set_add_option(o, cb.currentData()))
            b.addWidget(c)
            self.add_combos[opt] = c
        lay.addWidget(self.addw)
        # measure
        self.hint = QtWidgets.QLabel(self)
        self.hint.setProperty("dim", True)
        lay.addWidget(self.hint)
        self.state.changed.connect(self.sync)
        keymap.notifier.changed.connect(self.sync)
        for sig in (mw.hub.mode_changed, mw.hub.file_loaded, mw.hub.undo_done):
            sig.connect(lambda *_a: self.sync())
        self.sync()

    def sync(self):
        try:
            tool = self.state.tool
            self.ann.setVisible(tool == "ANNOTATE")
            self.addw.setVisible(tool == "ADD" and bpy.context.mode == "OBJECT")
            self.hint.setVisible(tool == "MEASURE")
            if tool == "MEASURE":
                self.hint.setText(keymap.render(
                    "Drag: new ruler · drag from the middle: angle · Ctrl: snap to vertices · "
                    "{view3d.ruler_remove}: remove"))
            if tool == "ANNOTATE":
                lay = note_layer()
                c = lay.color if lay is not None else NOTE_COLOR
                pm = QtGui.QPixmap(theme.px(28), theme.px(14))
                pm.fill(QtGui.QColor.fromRgbF(c[0], c[1], c[2]))
                self.color_btn.setIcon(QtGui.QIcon(pm))
                self.color_btn.setIconSize(pm.size())
                self.thick.blockSignals(True)
                self.thick.setValue(int(lay.thickness) if lay is not None else 3)
                self.thick.blockSignals(False)
                ts = bpy.context.scene.tool_settings
                self.place.setCurrentIndex(max(0, self.place.findData(
                    getattr(ts, "annotation_stroke_placement_view3d", "CURSOR"))))
                self.radius.setVisible(self.state.variant("ANNOTATE") == "ERASER")
                self.radius.blockSignals(True)
                self.radius.setValue(int(self.state.eraser_radius))
                self.radius.blockSignals(False)
            self.setVisible(tool in ("ANNOTATE", "MEASURE") or (tool == "ADD" and bpy.context.mode == "OBJECT"))
        except RuntimeError:
            pass
        except Exception as ex:
            bridge.log(f"Tool header: {ex}", "WARNING")

    def _views_update(self):
        area = getattr(self.mw, "viewports", None)
        for v in (getattr(area, "views", None) or [self.mw.viewport]):
            v.update()

    def _pick_color(self):
        lay = note_layer()
        c = lay.color if lay is not None else NOTE_COLOR
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor.fromRgbF(c[0], c[1], c[2]), self, "Annotation Colour")
        if not col.isValid():
            return
        lay = note_layer(create=True)
        lay.color = (col.redF(), col.greenF(), col.blueF())
        bridge.undo_push("Annotation Colour")
        self.sync()
        self._views_update()

    def _set_thickness(self, v):
        lay = note_layer(create=True)
        lay.thickness = int(v)
        self._views_update()

    def _set_place(self, _i):
        bpy.context.scene.tool_settings.annotation_stroke_placement_view3d = self.place.currentData()

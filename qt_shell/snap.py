"""Snapping for the interactive G / R / S of the Qt viewport (and the gizmo drags), like Blender.

Uses the scene's snapping settings (header: Snap toggle + Snapping popover):
- use_snap – on / off; holding Ctrl during the transform inverts it,
- snap_elements – Increment, Grid (absolute grid), Vertex, Edge, Edge Center, Edge Perpendicular,
  Face (Project / Nearest), Face Center, Volume,
- snap_target (Snap With) – Closest, Center, Median, Active,
- Affect (use_snap_translate / rotate / scale) – geometry targets work for Move; increments for all three
  (Rotate: snap_angle_increment_3d, Scale: 0.1), Shift = finer steps,
- use_snap_self, use_snap_edit, use_snap_nonedit, use_snap_selectable.

Geometry is gathered once when the transform starts (evaluated meshes, without the moved objects / the
selected vertices), then projected with numpy on every mouse move.
"""
import math

import bpy
import numpy as np
from mathutils import Vector
from PySide6 import QtCore, QtWidgets

from . import theme

GEOMETRY = {"VERTEX", "EDGE", "EDGE_MIDPOINT", "EDGE_PERPENDICULAR", "FACE", "FACE_PROJECT", "FACE_NEAREST",
            "FACE_MIDPOINT", "VOLUME"}
FACES = {"FACE", "FACE_PROJECT", "FACE_NEAREST", "VOLUME", "FACE_MIDPOINT"}
MAX_VERTS = 2_000_000
SNAP_PX = 18                      # unscaled screen pixels


def _mods():
    return QtWidgets.QApplication.queryKeyboardModifiers()


def grid_step(vp):
    """Size of one increment, like Blender: the grid scale (Overlays → Scale, 1 unit) in perspective, the
    visible grid subdivision in orthographic views."""
    try:
        scale = bpy.context.scene.unit_settings.scale_length or 1.0
    except Exception:
        scale = 1.0
    try:
        sp, _r = vp.space()
        grid = sp.overlay.grid_scale or 1.0
    except Exception:
        grid = 1.0
    if vp.ortho and not vp.camera_view:
        return grid * 10 ** math.floor(math.log10(max(vp.dist / grid, 0.01) / 2)) / scale
    return grid / scale


def _mesh_world(ob, depsgraph):
    """(verts (n,3) world, edges (m,2)) of an object's evaluated mesh."""
    ev = ob.evaluated_get(depsgraph)
    try:
        me = ev.to_mesh()
    except Exception:
        return None, None
    try:
        n = len(me.vertices)
        if n == 0:
            return None, None
        co = np.empty(n * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        co = co.reshape(n, 3)
        m = len(me.edges)
        ed = np.empty(m * 2, dtype=np.int64)
        me.edges.foreach_get("vertices", ed)
        ed = ed.reshape(m, 2)
        mw = np.array(ob.matrix_world, dtype=np.float64)
        co = co @ mw[:3, :3].T + mw[:3, 3]
        return co, ed
    finally:
        try:
            ev.to_mesh_clear()
        except Exception:
            pass


class Snapper:
    def __init__(self, vp, modal):
        ctx = bpy.context
        ts = ctx.scene.tool_settings
        self.vp = vp
        self.use = bool(ts.use_snap)
        self.elements = set(ts.snap_elements)
        self.target_mode = getattr(ts, "snap_target", "CLOSEST")
        self.affect = {"G": getattr(ts, "use_snap_translate", True), "R": getattr(ts, "use_snap_rotate", False),
                       "S": getattr(ts, "use_snap_scale", False)}
        self.angle = getattr(ts, "snap_angle_increment_3d", math.radians(5))
        self.angle_fine = getattr(ts, "snap_angle_increment_3d_precision", math.radians(1))
        self.absolute = bool(getattr(ts, "use_snap_grid_absolute", False)) or "GRID" in self.elements
        self.step = grid_step(vp)
        self.point = None            # the snapped world point (drawn by the viewport)
        self.kind = None
        self._V = None               # candidate vertices (n,3), edges (m,2)
        self._E = None
        self._exclude = set()
        self._src_pts = None         # points of the selection (initial positions) – Snap With: Closest
        self._gathered = False
        self.modal = modal
        if self.elements & GEOMETRY and self.target_mode in ("CLOSEST", "CENTER"):
            try:
                self.source_points()          # now – before anything moves
            except Exception:
                self._src_pts = None

    # ---------------------------------------------------------------- state
    def enabled(self):
        """Snapping on: the header toggle, inverted while Ctrl is held."""
        ctrl = bool(_mods() & QtCore.Qt.ControlModifier)
        return self.use != ctrl

    def fine(self):
        return bool(_mods() & QtCore.Qt.ShiftModifier)

    def _gather(self):
        """Candidate geometry (once per transform)."""
        self._gathered = True
        if not (self.elements & GEOMETRY):
            return
        ctx = bpy.context
        ts = ctx.scene.tool_settings
        dg = ctx.evaluated_depsgraph_get()
        mode = ctx.mode
        moved = set()
        for ob, _init in self.modal.get("objs") or []:
            moved.add(ob.name)
            for ch in ob.children_recursive:
                moved.add(ch.name)
        edit_obs = {o.name for o in ctx.objects_in_mode} if mode.startswith("EDIT") else set()
        self._exclude = moved | edit_obs
        Vs, Es, n0 = [], [], 0
        if getattr(ts, "use_snap_nonedit", True) or mode == "OBJECT" or mode == "POSE":
            for ob in ctx.visible_objects:
                if ob.name in self._exclude or ob.type not in ("MESH", "CURVE", "SURFACE", "FONT", "META"):
                    continue
                if getattr(ts, "use_snap_selectable", False) and ob.hide_select:
                    continue
                co, ed = _mesh_world(ob, dg)
                if co is None:
                    continue
                if n0 + len(co) > MAX_VERTS:
                    break
                Vs.append(co)
                Es.append(ed + n0)
                n0 += len(co)
        # Edit Mesh: the unselected vertices of the edited mesh (Snap to Same Target / use_snap_self)
        if mode == "EDIT_MESH" and getattr(ts, "use_snap_self", True) and getattr(ts, "use_snap_edit", True):
            from . import editmesh
            r = editmesh.active()
            if r:
                ob, bm = r
                mw = ob.matrix_world
                bm.verts.ensure_lookup_table()
                idx = {}
                pts = []
                for v in bm.verts:
                    if not v.select and not v.hide:
                        idx[v.index] = len(pts) + n0
                        pts.append(mw @ v.co)
                if pts:
                    eds = [(idx[e.verts[0].index], idx[e.verts[1].index]) for e in bm.edges
                           if e.verts[0].index in idx and e.verts[1].index in idx]
                    Vs.append(np.array([tuple(p) for p in pts], dtype=np.float64))
                    Es.append(np.array(eds, dtype=np.int64).reshape(-1, 2))
                    n0 += len(pts)
        if Vs:
            self._V = np.concatenate(Vs)
            self._E = np.concatenate(Es) if Es else np.zeros((0, 2), dtype=np.int64)

    def source_points(self):
        """Points of the selection at the start (world) – for Snap With: Closest."""
        if self._src_pts is not None:
            return self._src_pts
        ctx = bpy.context
        pts = []
        m = self.modal
        if m.get("edit") is not None:
            from . import editmesh
            r = editmesh.active()
            if r:
                ob, bm = r
                mw = ob.matrix_world
                pts = [mw @ v.co for v in bm.verts if v.select and not v.hide][:20000]
        elif m.get("pose") is not None:
            from . import posetransform
            for ob, pb in posetransform.selected_bones(ctx):
                pts += [ob.matrix_world @ pb.head, ob.matrix_world @ pb.tail]
        else:
            dg = ctx.evaluated_depsgraph_get()
            for ob, init in m.get("objs") or []:
                co = None
                if ob.type == "MESH" and len(ob.data.vertices) <= 20000:
                    co, _e = _mesh_world(ob, dg)
                if co is not None:
                    pts += [Vector(p) for p in co]
                else:
                    pts += [init @ Vector(c) for c in ob.bound_box]
        self._src_pts = pts or [m["pivot"]]
        return self._src_pts

    def source(self, target=None):
        """The point that lands on the target (Snap With)."""
        m = self.modal
        pivot = m["pivot"]
        mode = self.target_mode
        if mode == "ACTIVE":
            ob = bpy.context.active_object
            if m.get("objs") and ob is not None:
                for o, init in m["objs"]:
                    if o == ob:
                        return init.translation.copy()
            return pivot
        if mode == "CENTER":
            pts = self.source_points()
            lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
            hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
            return (lo + hi) / 2
        if mode == "CLOSEST" and target is not None:
            return min(self.source_points(), key=lambda p: (p - target).length_squared)
        return pivot

    # ---------------------------------------------------------------- targets
    def _project(self, P):
        vp = self.vp
        w, h = vp.width(), vp.height()
        vm, pm = vp.matrices(w, h)
        M = np.array(pm @ vm, dtype=np.float64)
        hom = P @ M[:3, :3].T + M[:3, 3]
        wv = P @ M[3, :3] + M[3, 3]
        ok = wv > 1e-6
        wv = np.where(ok, wv, 1.0)
        x = (hom[:, 0] / wv + 1) * 0.5 * w
        y = (1 - hom[:, 1] / wv) * 0.5 * h
        return x, y, ok, wv

    def find_target(self, pos):
        """(world point, kind) of the geometry under the mouse, or (None, None)."""
        if not self._gathered:
            self._gather()
        els = self.elements
        mx, my = pos.x(), pos.y()
        lim = SNAP_PX * theme.ui_scale
        best = None                           # (screen distance, depth, point, kind)
        V = self._V
        if V is not None and len(V):
            x, y, ok, depth = self._project(V)
            d = np.hypot(x - mx, y - my)
            d = np.where(ok, d, np.inf)
            if "VERTEX" in els:
                i = int(np.argmin(d))
                if d[i] <= lim:
                    best = (d[i] - lim, depth[i], Vector(V[i]), "VERTEX")      # vertices win when close
            E = self._E
            if best is None and E is not None and len(E) and els & {"EDGE", "EDGE_MIDPOINT", "EDGE_PERPENDICULAR"}:
                a, b = E[:, 0], E[:, 1]
                okE = ok[a] & ok[b]
                ax, ay, bx, by = x[a], y[a], x[b], y[b]
                if "EDGE_MIDPOINT" in els:
                    cx, cy = (ax + bx) / 2, (ay + by) / 2
                    dm = np.where(okE, np.hypot(cx - mx, cy - my), np.inf)
                    j = int(np.argmin(dm))
                    if dm[j] <= lim:
                        best = (dm[j] - lim, 0.0, Vector((V[a[j]] + V[b[j]]) / 2), "EDGE_MIDPOINT")
                if best is None and els & {"EDGE", "EDGE_PERPENDICULAR"}:
                    dx, dy = bx - ax, by - ay
                    L2 = np.maximum(dx * dx + dy * dy, 1e-9)
                    t = np.clip(((mx - ax) * dx + (my - ay) * dy) / L2, 0.0, 1.0)
                    de = np.where(okE, np.hypot(ax + t * dx - mx, ay + t * dy - my), np.inf)
                    j = int(np.argmin(de))
                    if de[j] <= lim:
                        # perspective-correct parameter along the 3D edge
                        wa, wb = depth[a[j]], depth[b[j]]
                        tj = float(t[j])
                        t3 = tj * wa / max((1 - tj) * wb + tj * wa, 1e-9)
                        best = (de[j], 0.0, Vector(V[a[j]] + (V[b[j]] - V[a[j]]) * t3), "EDGE")
        if best is None and els & FACES:
            hit = self._ray_face(mx, my, "FACE_MIDPOINT" in els and not (els & (FACES - {"FACE_MIDPOINT"})))
            if hit is not None:
                return hit, "FACE"
        if best is None:
            return None, None
        return best[2], best[3]

    def _ray_face(self, mx, my, midpoint=False):
        ctx = bpy.context
        dg = ctx.evaluated_depsgraph_get()
        origin, direction = self.vp.ray(mx, my)
        for _i in range(16):                  # skip the moved objects
            hit, loc, _n, index, ob, _m = ctx.scene.ray_cast(dg, origin, direction)
            if not hit:
                return None
            if ob is not None and ob.name in self._exclude:
                origin = loc + direction * 1e-4
                continue
            if midpoint and ob is not None:
                try:
                    me = ob.evaluated_get(dg).data
                    return ob.matrix_world @ me.polygons[index].center
                except Exception:
                    pass
            return loc
        return None

    # ---------------------------------------------------------------- apply
    def move(self, delta, pos, axis_vec, orient):
        """Snapped translation (world) for a mouse move – delta is the unsnapped one."""
        self.point = self.kind = None
        if not self.enabled():
            return delta
        if self.elements & GEOMETRY and self.affect.get("G", True):
            tgt, kind = self.find_target(pos)
            if tgt is not None:
                src = self.source(tgt)
                d = tgt - src
                if axis_vec is not None:
                    d = axis_vec * d.dot(axis_vec)
                self.point, self.kind = tgt, kind
                return d
        if self.elements & {"INCREMENT", "GRID"}:
            step = self.step * (0.1 if self.fine() else 1.0)
            pivot = self.modal["pivot"]
            if axis_vec is not None:
                if self.absolute:
                    # the pivot lands on the grid along the axis
                    end = pivot + delta
                    k = axis_vec.dot(end)
                    return axis_vec * (round(k / step) * step - axis_vec.dot(pivot))
                return axis_vec * (round(delta.dot(axis_vec) / step) * step)
            cols = [Vector(orient.col[i]).normalized() for i in range(3)] if orient is not None else \
                [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]
            out = Vector()
            for c in cols:
                if self.absolute:
                    end = (pivot + delta).dot(c)
                    out += c * (round(end / step) * step - pivot.dot(c))
                else:
                    out += c * (round(delta.dot(c) / step) * step)
            return out
        return delta

    def rotate(self, angle):
        if not self.enabled() or not (self.elements & {"INCREMENT", "GRID"}):
            return angle
        inc = self.angle_fine if self.fine() else self.angle
        return round(angle / inc) * inc if inc > 0 else angle

    def scale(self, fac):
        if not self.enabled() or not (self.elements & {"INCREMENT", "GRID"}):
            return fac
        inc = 0.01 if self.fine() else 0.1
        return round(fac / inc) * inc


def paint(vp, p):
    """The snap marker while transforming."""
    m = vp._modal
    s = m.get("snapper") if m else None
    if s is None or s.point is None:
        return
    q = vp.project(s.point)
    if q is None:
        return
    from PySide6 import QtGui
    sc = theme.ui_scale
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1.6 * sc))
    p.setBrush(QtCore.Qt.NoBrush)
    r = 6 * sc
    if s.kind == "VERTEX":
        p.drawEllipse(q, r, r)
    elif s.kind in ("EDGE", "EDGE_MIDPOINT"):
        p.drawLine(QtCore.QPointF(q.x() - r, q.y() + r), QtCore.QPointF(q.x() + r, q.y() - r))
        p.drawEllipse(q, r * 0.5, r * 0.5)
    else:
        p.drawRect(QtCore.QRectF(q.x() - r, q.y() - r, 2 * r, 2 * r))
    p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1 * sc))
    p.drawLine(QtCore.QPointF(q.x() - 2 * r, q.y()), QtCore.QPointF(q.x() + 2 * r, q.y()))
    p.drawLine(QtCore.QPointF(q.x(), q.y() - 2 * r), QtCore.QPointF(q.x(), q.y() + 2 * r))
    p.restore()

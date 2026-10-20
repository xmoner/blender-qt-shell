"""Picking of things that are drawn as lines: pose bones (custom shapes = rig controls, or the bone
itself), armatures and curve objects in Object mode.

Blender selects these with its GPU select buffer; Qt Shell draws the viewport offscreen, so we project
the drawn geometry ourselves (numpy) and measure the distance from the cursor to the lines / faces.
"""
import bpy
import numpy as np
from mathutils import Matrix

PICK_PX = 10.0         # how far from a line a click still hits it (Blender uses a similar radius)

_shape_cache = {}      # mesh pointer → (verts, edges, tris)


# ---------------------------------------------------------------- geometry
def _arrays(me):
    key = (me.as_pointer(), len(me.vertices), len(me.edges), len(me.polygons))
    hit = _shape_cache.get(key)
    if hit is not None:
        return hit
    n = len(me.vertices)
    co = np.empty(n * 3, np.float64)
    me.vertices.foreach_get("co", co)
    ed = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ed)
    tris = np.zeros((0, 3), np.int64)
    if len(me.polygons):
        try:
            me.calc_loop_triangles()
            t = np.empty(len(me.loop_triangles) * 3, np.int64)
            me.loop_triangles.foreach_get("vertices", t)
            tris = t.reshape(-1, 3)
        except Exception:
            pass
    res = (co.reshape(-1, 3), ed.reshape(-1, 2), tris)
    if len(_shape_cache) > 512:
        _shape_cache.clear()
    _shape_cache[key] = res
    return res


def _screen(vp, mats, M, co):
    """Projects local coordinates co (N×3) with world matrix M → (sx, sy, depth, ok)."""
    vm, pm = mats
    w, h = vp.width(), vp.height()
    A = np.array(pm @ vm @ M, dtype=np.float64)
    V = np.array(vm @ M, dtype=np.float64)
    h4 = np.c_[co, np.ones(len(co))]
    clip = h4 @ A.T
    ww = clip[:, 3]
    ok = ww > 1e-6
    safe = np.where(ok, ww, 1.0)
    sx = (clip[:, 0] / safe + 1.0) * 0.5 * w
    sy = (1.0 - clip[:, 1] / safe) * 0.5 * h
    depth = -(h4 @ V.T)[:, 2]
    return sx, sy, depth, ok


def _hit(proj, edges, tris, x, y):
    """(distance_px, depth) of the closest drawn part to (x, y), or None."""
    sx, sy, depth, ok = proj
    best_d, best_z = None, None
    if len(tris):
        a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
        good = ok[a] & ok[b] & ok[c]
        x0, y0, x1, y1, x2, y2 = sx[a], sy[a], sx[b], sy[b], sx[c], sy[c]
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        nz = np.abs(den) > 1e-9
        den = np.where(nz, den, 1.0)
        l0 = ((y1 - y2) * (x - x2) + (x2 - x1) * (y - y2)) / den
        l1 = ((y2 - y0) * (x - x2) + (x0 - x2) * (y - y2)) / den
        l2 = 1.0 - l0 - l1
        inside = good & nz & (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if inside.any():
            z = (l0 * depth[a] + l1 * depth[b] + l2 * depth[c])[inside].min()
            best_d, best_z = 0.0, float(z)
    if len(edges):
        a, b = edges[:, 0], edges[:, 1]
        good = ok[a] & ok[b]
        if good.any():
            ax, ay, bx, by = sx[a], sy[a], sx[b], sy[b]
            dx, dy = bx - ax, by - ay
            ll = dx * dx + dy * dy
            t = np.clip(((x - ax) * dx + (y - ay) * dy) / np.where(ll > 1e-12, ll, 1.0), 0.0, 1.0)
            px, py = ax + t * dx, ay + t * dy
            d = np.hypot(px - x, py - y)
            d = np.where(good, d, np.inf)
            i = int(np.argmin(d))
            if d[i] <= PICK_PX and (best_d is None or d[i] < best_d):
                best_d = float(d[i])
                best_z = float(depth[a[i]] + t[i] * (depth[b[i]] - depth[a[i]]))
    elif not len(tris) and len(sx):
        d = np.where(ok, np.hypot(sx - x, sy - y), np.inf)
        i = int(np.argmin(d))
        if d[i] <= PICK_PX:
            best_d, best_z = float(d[i]), float(depth[i])
    if best_d is None:
        return None
    return best_d, best_z


def _in_rect(proj, rect):
    sx, sy, _z, ok = proj
    inside = ok & (sx >= rect.left()) & (sx <= rect.right()) & (sy >= rect.top()) & (sy <= rect.bottom())
    return bool(inside.any())


def _rank(hit):
    """Hits right under the cursor (inside a face or within 3 px) are ordered by depth, the rest by distance."""
    d, z = hit
    return (0, z) if d <= 3.0 else (1, d)


# ---------------------------------------------------------------- bones
def bone_visible(pb):
    if getattr(pb, "hide", False) or getattr(pb.bone, "hide", False):
        return False
    cols = getattr(pb.bone, "collections", None)
    if cols is None or len(cols) == 0:
        return True
    return any(getattr(c, "is_visible_effectively", getattr(c, "is_visible", True)) for c in cols)


def bone_selectable(pb):
    return bone_visible(pb) and not getattr(pb.bone, "hide_select", False)


def shape_matrix(ob, pb):
    """World matrix Blender uses to draw the custom shape of pose bone pb."""
    tx = pb.custom_shape_transform or pb
    m = ob.matrix_world @ tx.matrix
    m = m @ Matrix.Translation(pb.custom_shape_translation)
    m = m @ pb.custom_shape_rotation_euler.to_matrix().to_4x4()
    s = pb.custom_shape_scale_xyz.copy()
    if pb.use_custom_shape_bone_size:
        s *= tx.bone.length
    return m @ Matrix.Diagonal((s[0], s[1], s[2], 1.0))


def _bone_proj(vp, mats, ob, pb):
    """(projection, edges, tris) of what Blender draws for the bone."""
    shape = pb.custom_shape
    if shape is not None and shape.type == "MESH":
        co, ed, tris = _arrays(shape.data)
        return _screen(vp, mats, shape_matrix(ob, pb), co), ed, tris
    co = np.array([tuple(pb.head), tuple(pb.tail)], np.float64)
    return _screen(vp, mats, ob.matrix_world, co), np.array([[0, 1]], np.int64), np.zeros((0, 3), np.int64)


def pick_bone(vp, x, y, armatures, mats=None):
    """Closest selectable pose bone under (x, y) → (armature_object, pose_bone) or None."""
    mats = mats or vp.matrices(vp.width(), vp.height())
    best, best_key = None, None
    for ob in armatures:
        if ob.pose is None:
            continue
        for pb in ob.pose.bones:
            if not bone_selectable(pb):
                continue
            try:
                proj, ed, tris = _bone_proj(vp, mats, ob, pb)
            except Exception:
                continue
            h = _hit(proj, ed, tris, x, y)
            if h is None:
                continue
            k = _rank(h)
            if best_key is None or k < best_key:
                best, best_key = (ob, pb), k
    return best


def box_bones(vp, rect, armatures):
    """Pose bones with any drawn part inside rect → [(armature_object, pose_bone)]."""
    mats = vp.matrices(vp.width(), vp.height())
    out = []
    for ob in armatures:
        if ob.pose is None:
            continue
        for pb in ob.pose.bones:
            if not bone_selectable(pb):
                continue
            try:
                proj, _ed, _tris = _bone_proj(vp, mats, ob, pb)
            except Exception:
                continue
            if _in_rect(proj, rect):
                out.append((ob, pb))
    return out


def pose_armatures(ctx=None):
    ctx = ctx or bpy.context
    return [o for o in ctx.view_layer.objects
            if o.type == "ARMATURE" and o.mode == "POSE" and o.visible_get()]


# ---------------------------------------------------------------- objects drawn as lines
_WIRE_TYPES = {"CURVE", "ARMATURE"}


def pick_object(vp, x, y, mats=None):
    """Closest curve / armature object whose drawn lines are under (x, y) → (rank_key, depth, object) or None."""
    ctx = bpy.context
    mats = mats or vp.matrices(vp.width(), vp.height())
    dg = None
    best, best_key = None, None
    for ob in ctx.visible_objects:
        if ob.type not in _WIRE_TYPES or ob.hide_select:
            continue
        h = None
        try:
            if ob.type == "ARMATURE":
                for pb in ob.pose.bones:
                    if not bone_visible(pb):
                        continue
                    proj, ed, tris = _bone_proj(vp, mats, ob, pb)
                    hb = _hit(proj, ed, tris, x, y)
                    if hb is not None and (h is None or _rank(hb) < _rank(h)):
                        h = hb
            else:
                if dg is None:
                    dg = ctx.evaluated_depsgraph_get()
                ev = ob.evaluated_get(dg)
                me = ev.to_mesh()
                try:
                    if me is None:
                        continue
                    n = len(me.vertices)
                    co = np.empty(n * 3, np.float64)
                    me.vertices.foreach_get("co", co)
                    ed = np.empty(len(me.edges) * 2, np.int64)
                    me.edges.foreach_get("vertices", ed)
                    h = _hit(_screen(vp, mats, ob.matrix_world, co.reshape(-1, 3)),
                             ed.reshape(-1, 2), np.zeros((0, 3), np.int64), x, y)
                finally:
                    ev.to_mesh_clear()
        except Exception:
            continue
        if h is None:
            continue
        k = _rank(h)
        if best_key is None or k < best_key:
            best, best_key = (k, h[1], ob), k
    return best

"""Interactive G / R / S in the other Edit Modes: curves / surfaces, armatures and lattices.

Like editmesh.TransformState: the selected points are collected once, apply(world_matrix) places them,
restore() puts them back (right click / Esc). Several objects can be in Edit Mode together.

- Curve / Surface: Bézier points (a selected control point takes its handles along, a selected handle
  moves alone) and Poly / NURBS points (their w stays).
- Armature: edit bones – a fully selected bone moves head + tail (its roll follows a rotation), a selected
  head or tail moves alone; connected children follow their parent's tail.
- Lattice: the selected points (co_deform).
"""
import math

import bpy
from mathutils import Matrix, Vector

MODES = ("EDIT_CURVE", "EDIT_SURFACE", "EDIT_ARMATURE", "EDIT_LATTICE")


def supported(mode=None):
    return (mode or bpy.context.mode) in MODES


def _bone_visible(eb):
    """Not hidden and in at least one visible bone collection (Blender ignores the others)."""
    if eb.hide:
        return False
    cols = list(getattr(eb, "collections", []) or [])
    return not cols or any(getattr(c, "is_visible_effectively", getattr(c, "is_visible", True)) for c in cols)


def _objects(ctx, types):
    obs = [o for o in getattr(ctx, "objects_in_mode", []) or [] if o.type in types]
    if not obs and ctx.edit_object is not None and ctx.edit_object.type in types:
        obs = [ctx.edit_object]
    return obs


def _curve_items(ob):
    """[(getter, setter)] in object space for the selected curve points."""
    out = []
    for sp in ob.data.splines:
        if sp.type == "BEZIER":
            for bp in sp.bezier_points:
                if bp.hide:
                    continue
                if bp.select_control_point:
                    out += [(bp, "co"), (bp, "handle_left"), (bp, "handle_right")]
                else:
                    if bp.select_left_handle:
                        out.append((bp, "handle_left"))
                    if bp.select_right_handle:
                        out.append((bp, "handle_right"))
        else:
            for p in sp.points:
                if p.select and not p.hide:
                    out.append((p, "co4"))
    return out


def _get(item):
    el, attr = item
    if attr == "co4":
        return Vector(el.co[:3])
    return Vector(getattr(el, attr))


def _set(item, v):
    el, attr = item
    if attr == "co4":
        el.co = (v.x, v.y, v.z, el.co[3])
    else:
        setattr(el, attr, v)


def selected_points(ctx=None):
    """World positions of what G / R / S would move (gizmo pivot / cage)."""
    ctx = ctx or bpy.context
    mode = ctx.mode
    pts = []
    if mode in ("EDIT_CURVE", "EDIT_SURFACE"):
        for ob in _objects(ctx, {"CURVE", "SURFACE"}):
            mw = ob.matrix_world
            for sp in ob.data.splines:
                if sp.type == "BEZIER":
                    for bp in sp.bezier_points:
                        if bp.hide:
                            continue
                        if bp.select_control_point:
                            pts.append(mw @ bp.co)
                        else:
                            if bp.select_left_handle:
                                pts.append(mw @ bp.handle_left)
                            if bp.select_right_handle:
                                pts.append(mw @ bp.handle_right)
                else:
                    pts += [mw @ Vector(p.co[:3]) for p in sp.points if p.select and not p.hide]
    elif mode == "EDIT_ARMATURE":
        for ob in _objects(ctx, {"ARMATURE"}):
            mw = ob.matrix_world
            for eb in ob.data.edit_bones:
                if not _bone_visible(eb):
                    continue
                if eb.select or eb.select_head:
                    pts.append(mw @ eb.head)
                if eb.select or eb.select_tail:
                    pts.append(mw @ eb.tail)
    elif mode == "EDIT_LATTICE":
        for ob in _objects(ctx, {"LATTICE"}):
            mw = ob.matrix_world
            pts += [mw @ p.co_deform for p in ob.data.points if p.select]
    return pts


def pivot(ctx=None):
    pts = selected_points(ctx)
    return sum(pts, Vector()) / len(pts) if pts else None


class TransformState:
    """Transforms the selected points / bone ends of every object in the current Edit Mode."""

    def __init__(self, ctx=None):
        ctx = ctx or bpy.context
        self.mode = ctx.mode
        self.groups = []         # (object, matrix_world, inverse, kind, items, initial values)
        if self.mode in ("EDIT_CURVE", "EDIT_SURFACE"):
            for ob in _objects(ctx, {"CURVE", "SURFACE"}):
                items = _curve_items(ob)
                if items:
                    self.groups.append((ob, "CURVE", items, [_get(i) for i in items]))
        elif self.mode == "EDIT_ARMATURE":
            for ob in _objects(ctx, {"ARMATURE"}):
                bones = []
                for eb in ob.data.edit_bones:
                    if not _bone_visible(eb):
                        continue
                    full = eb.select or (eb.select_head and eb.select_tail)
                    head = full or eb.select_head
                    tail = full or eb.select_tail
                    if head or tail:
                        bones.append((eb, head, tail, full, eb.head.copy(), eb.tail.copy(), eb.z_axis.copy(),
                                      eb.roll))
                if bones:
                    self.groups.append((ob, "ARMATURE", bones, None))
        elif self.mode == "EDIT_LATTICE":
            for ob in _objects(ctx, {"LATTICE"}):
                pts = [p for p in ob.data.points if p.select]
                if pts:
                    self.groups.append((ob, "LATTICE", pts, [p.co_deform.copy() for p in pts]))
        else:
            raise ValueError("Unsupported mode.")
        if not self.groups:
            raise ValueError("Nothing is selected.")
        self.mats = {ob.name: (ob.matrix_world.copy(), ob.matrix_world.inverted()) for ob, *_r in self.groups}
        pts = []
        for ob, kind, items, init in self.groups:
            mw = self.mats[ob.name][0]
            if kind == "ARMATURE":
                for eb, h, t, _f, h0, t0, _z, _r in items:
                    if h:
                        pts.append(mw @ h0)
                    if t:
                        pts.append(mw @ t0)
            else:
                pts += [mw @ c for c in init]
        self.pivot = sum(pts, Vector()) / len(pts)

    def apply(self, world_matrix):
        for ob, kind, items, init in self.groups:
            mw, inv = self.mats[ob.name]
            A = inv @ world_matrix @ mw
            try:
                if kind == "CURVE":
                    for it, c in zip(items, init):
                        _set(it, A @ c)
                elif kind == "LATTICE":
                    for p, c in zip(items, init):
                        p.co_deform = A @ c
                else:
                    R = A.to_3x3()
                    moved_tails = {}
                    for eb, h, t, full, h0, t0, z0, roll in items:
                        if h:
                            eb.head = A @ h0
                        if t:
                            eb.tail = A @ t0
                            moved_tails[eb.name] = eb.tail.copy()
                        if full:
                            try:
                                eb.align_roll((R @ z0).normalized())     # the roll turns with the bone
                            except Exception:
                                pass
                    for eb in ob.data.edit_bones:                       # connected children follow
                        if eb.use_connect and eb.parent is not None and eb.parent.name in moved_tails:
                            eb.head = moved_tails[eb.parent.name]
                ob.data.update_tag()
            except ReferenceError:
                pass

    def restore(self):
        for ob, kind, items, init in self.groups:
            try:
                if kind == "CURVE":
                    for it, c in zip(items, init):
                        _set(it, c)
                elif kind == "LATTICE":
                    for p, c in zip(items, init):
                        p.co_deform = c
                else:
                    for eb, h, t, full, h0, t0, _z, roll in items:
                        eb.head, eb.tail = h0, t0
                        if full:
                            eb.roll = roll
                    for eb in ob.data.edit_bones:
                        if eb.use_connect and eb.parent is not None:
                            eb.head = eb.parent.tail
                ob.data.update_tag()
            except ReferenceError:
                pass


def extrude():
    """Extrude in the current Edit Mode and move the result with the mouse (Qt Shell's G): mesh – along the
    normal, curve – the selected end points, armature – new bones from the selected tails. Returns True when
    something was extruded."""
    from . import api, bridge
    mode = bpy.context.mode
    ops = {"EDIT_MESH": ("mesh.extrude_region", {}), "EDIT_CURVE": ("curve.extrude", {"mode": "TRANSLATION"}),
           "EDIT_SURFACE": ("curve.extrude", {"mode": "TRANSLATION"}),
           "EDIT_ARMATURE": ("armature.extrude", {"forked": False})}
    if mode == "OBJECT":
        ob = bpy.context.active_object
        if ob is None or ob.type not in ("MESH", "CURVE", "SURFACE", "ARMATURE"):
            bridge.log("Extrude: select a mesh, curve or armature.", "WARNING")
            return False
        bpy.ops.object.mode_set(mode="EDIT")
        mode = bpy.context.mode
    if mode not in ops:
        bridge.log(f"Extrude doesn't work in {mode.replace('_', ' ').title()}.", "WARNING")
        return False
    idname, props = ops[mode]
    res = bridge.run_op(idname, props)
    if "FINISHED" not in res:
        return False
    vp = api.viewport()
    if vp is None:
        return True
    vp.start_modal("G")
    m = vp._modal
    if m and mode == "EDIT_MESH":
        m["axis"] = "Z"                          # along the normal, like Blender's extrude
        vp._set_modal_orient("NORMAL")
    return True


# ---------------------------------------------------------------- selection (click / box / circle / lasso)
PICK_PX = 10          # how close (widget pixels) a click must be to a point / bone line


def _elements(vp, ctx=None, mats=None):
    """Selectable elements with their screen geometry: [(kind, ob, element, part, points)] where points are
    widget-space QPointFs (one for a point, two for a bone body)."""
    ctx = ctx or bpy.context
    mode = ctx.mode
    mats = mats or vp.matrices(vp.width(), vp.height())
    out = []

    def P(ob, co):
        return vp.project(ob.matrix_world @ Vector(co[:3]), mats)
    if mode in ("EDIT_CURVE", "EDIT_SURFACE"):
        show_handles = True
        try:
            sp3d = vp.space()[0]
            show_handles = getattr(sp3d.overlay, "display_handle", "SELECTED") != "NONE"
        except Exception:
            pass
        for ob in _objects(ctx, {"CURVE", "SURFACE"}):
            for sp in ob.data.splines:
                if sp.type == "BEZIER":
                    for bp in sp.bezier_points:
                        if bp.hide:
                            continue
                        out.append(("CURVE", ob, bp, "co", [P(ob, bp.co)]))
                        if show_handles:
                            out.append(("CURVE", ob, bp, "handle_left", [P(ob, bp.handle_left)]))
                            out.append(("CURVE", ob, bp, "handle_right", [P(ob, bp.handle_right)]))
                else:
                    for p in sp.points:
                        if not p.hide:
                            out.append(("POINT", ob, p, "co", [P(ob, p.co)]))
    elif mode == "EDIT_ARMATURE":
        for ob in _objects(ctx, {"ARMATURE"}):
            for eb in ob.data.edit_bones:
                if not _bone_visible(eb):
                    continue
                h, t = P(ob, eb.head), P(ob, eb.tail)
                out.append(("BONE", ob, eb, "head", [h]))
                out.append(("BONE", ob, eb, "tail", [t]))
                out.append(("BONE", ob, eb, "body", [h, t]))
    elif mode == "EDIT_LATTICE":
        for ob in _objects(ctx, {"LATTICE"}):
            for p in ob.data.points:
                out.append(("POINT", ob, p, "co_deform", [P(ob, p.co_deform)]))
    return [e for e in out if all(q is not None for q in e[4])]


def _dist(e, x, y):
    pts = e[4]
    if len(pts) == 1:
        return math.hypot(pts[0].x() - x, pts[0].y() - y)
    a, b = pts
    ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L < 1e-9 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L))
    return math.hypot(ax + t * dx - x, ay + t * dy - y)


def _is_selected(e):
    kind, ob, el, part, _p = e
    if kind == "CURVE":
        return {"co": el.select_control_point, "handle_left": el.select_left_handle,
                "handle_right": el.select_right_handle}[part]
    if kind == "BONE":
        return {"head": el.select_head, "tail": el.select_tail, "body": el.select}[part]
    return el.select


def _set_selected(e, state):
    kind, ob, el, part, _p = e
    if kind == "CURVE":
        if part == "co":                       # a control point takes its handles along (like Blender)
            el.select_control_point = el.select_left_handle = el.select_right_handle = state
        elif part == "handle_left":
            el.select_left_handle = state
        else:
            el.select_right_handle = state
    elif kind == "BONE":
        if part == "body":
            el.select = el.select_head = el.select_tail = state
            if state:
                ob.data.edit_bones.active = el
        else:
            setattr(el, "select_" + part, state)
            if state:
                ob.data.edit_bones.active = el
            el.select = el.select_head and el.select_tail
        if part in ("head", "body") and el.use_connect and el.parent is not None:
            el.parent.select_tail = el.select_head          # a connected head is the parent's tail
    else:
        el.select = state


def _deselect_all(ctx):
    mode = ctx.mode
    if mode in ("EDIT_CURVE", "EDIT_SURFACE"):
        for ob in _objects(ctx, {"CURVE", "SURFACE"}):
            for sp in ob.data.splines:
                for bp in sp.bezier_points:
                    bp.select_control_point = bp.select_left_handle = bp.select_right_handle = False
                for p in sp.points:
                    p.select = False
    elif mode == "EDIT_ARMATURE":
        for ob in _objects(ctx, {"ARMATURE"}):
            for eb in ob.data.edit_bones:
                eb.select = eb.select_head = eb.select_tail = False
    elif mode == "EDIT_LATTICE":
        for ob in _objects(ctx, {"LATTICE"}):
            for p in ob.data.points:
                p.select = False


def _touch(ctx):
    for ob in _objects(ctx, {"CURVE", "SURFACE", "ARMATURE", "LATTICE"}):
        try:
            ob.data.update_tag()
        except Exception:
            pass


def element_at(vp, x, y):
    """The element under (x, y) or None – points win over bone bodies, the nearest wins."""
    best = None
    for e in _elements(vp):
        d = _dist(e, x, y)
        if d > PICK_PX * theme_scale():
            continue
        rank = (1 if e[3] == "body" else 0, d)
        if best is None or rank < best[0]:
            best = (rank, e)
    return best[1] if best else None


def theme_scale():
    try:
        from . import theme
        return max(0.5, theme.ui_scale)
    except Exception:
        return 1.0


def pick(vp, x, y, extend):
    """Click selection; extend (Shift) toggles. Returns True when the selection changed."""
    ctx = bpy.context
    e = element_at(vp, x, y)
    if e is None and extend:
        return False
    if not extend:
        _deselect_all(ctx)
    if e is not None:
        _set_selected(e, not (extend and _is_selected(e)))
    _touch(ctx)
    return True


def box(vp, shape, mode):
    """Box / circle / lasso: points inside (bones: their heads / tails; a bone is selected when both ends are).
    mode SET / ADD / SUB."""
    from . import selshape
    ctx = bpy.context
    if mode == "SET":
        _deselect_all(ctx)
    state = mode != "SUB"
    for e in _elements(vp):
        if e[3] == "body":
            continue
        p = e[4][0]
        if selshape.contains(shape, p.x(), p.y()):
            _set_selected(e, state)
    _touch(ctx)
    return True

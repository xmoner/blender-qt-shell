"""Pose mode in Qt: interactive G / R / S of pose bones, Alt+G/R/S clear, select all / invert / hide.

The viewport computes a world-space transform X (move / rotate about the pivot / scale about the
pivot); TransformState turns X @ (bone's start world matrix) back into each bone's local channels
(location / rotation in its rotation mode / scale), keeps locked channels and connected bones' location,
and keeps Euler and quaternion values continuous with the start values (no 180° flips in the curves).
"""
import bpy
from mathutils import Matrix, Quaternion, Vector

from .wirepick import bone_visible, pose_armatures


# ---------------------------------------------------------------- selection helpers
def selected_bones(ctx=None, roots_only=False):
    """[(armature_object, pose_bone)] of selected visible pose bones. roots_only drops bones whose
    parent chain is selected too (they follow their parent, like in Blender)."""
    out = []
    for ob in pose_armatures(ctx):
        sel = [pb for pb in ob.pose.bones if pb.select and bone_visible(pb)]
        if roots_only:
            names = {pb.name for pb in sel}
            sel = [pb for pb in sel if not any(p.name in names for p in pb.parent_recursive)]
        out.extend((ob, pb) for pb in sel)
    return out


def pivot(ctx=None):
    """Median of the selected bones' heads (world) or None."""
    bones = selected_bones(ctx)
    if not bones:
        return None
    return sum(((ob.matrix_world @ pb.head) for ob, pb in bones), Vector()) / len(bones)


def bounds_points(ctx=None):
    """World points of the selected bones (heads and tails) – for View Selected."""
    pts = []
    for ob, pb in selected_bones(ctx):
        pts.append(ob.matrix_world @ pb.head)
        pts.append(ob.matrix_world @ pb.tail)
    return pts


def select_all(action="SELECT"):
    for ob in pose_armatures():
        for pb in ob.pose.bones:
            if not bone_visible(pb):
                continue
            if action == "SELECT":
                pb.select = True
            elif action == "DESELECT":
                pb.select = False
            else:
                pb.select = not pb.select
        ob.update_tag()


def hide(unselected=False):
    for ob in pose_armatures():
        for pb in ob.pose.bones:
            if bone_visible(pb) and pb.select != unselected:
                pb.hide = True
                pb.select = False
        ob.update_tag()


def reveal():
    for ob in pose_armatures():
        for pb in ob.pose.bones:
            if pb.hide:
                pb.hide = False
                pb.select = True
        ob.update_tag()


def clear(kind):
    """Alt+G / Alt+R / Alt+S: reset location / rotation / scale of the selected bones."""
    bones = selected_bones()
    for _ob, pb in bones:
        if kind == "G":
            pb.location = (0.0, 0.0, 0.0)
        elif kind == "R":
            pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pb.rotation_euler = (0.0, 0.0, 0.0)
            pb.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
        else:
            pb.scale = (1.0, 1.0, 1.0)
    for ob in {ob for ob, _pb in bones}:
        ob.update_tag()
    if bones:
        _autokey(bones, kind)
    return len(bones)


# ---------------------------------------------------------------- channels
def _basis(pb):
    return (pb.location.copy(), pb.rotation_quaternion.copy(), pb.rotation_euler.copy(),
            tuple(pb.rotation_axis_angle), pb.scale.copy())


def _set_basis(pb, b):
    pb.location, pb.rotation_quaternion, pb.rotation_euler = b[0], b[1], b[2]
    pb.rotation_axis_angle, pb.scale = b[3], b[4]


def _rot_path(pb):
    mode = pb.rotation_mode
    if mode == "QUATERNION":
        return "rotation_quaternion"
    if mode == "AXIS_ANGLE":
        return "rotation_axis_angle"
    return "rotation_euler"


def _autokey(bones, kind, moved_location=False):
    ts = bpy.context.scene.tool_settings
    if not ts.use_keyframe_insert_auto:
        return
    for _ob, pb in bones:
        paths = {"G": ["location"], "R": [_rot_path(pb)], "S": ["scale"]}[kind]
        if moved_location and kind != "G":
            paths.append("location")
        for path in paths:
            try:
                pb.keyframe_insert(path, group=pb.name)
            except Exception:
                pass


class TransformState:
    def __init__(self, ctx=None):
        self.items = []
        for ob, pb in selected_bones(ctx, roots_only=True):
            self.items.append((ob, pb, ob.matrix_world @ pb.matrix, _basis(pb)))
        if not self.items:
            raise ValueError("No bones are selected.")
        self.pivot = pivot(ctx)
        self.moved_location = False

    def apply(self, X, kind):
        for ob, pb, W0, b0 in self.items:
            pose_m = ob.matrix_world.inverted() @ X @ W0
            try:
                local = ob.convert_space(pose_bone=pb, matrix=pose_m, from_space="POSE", to_space="LOCAL")
            except Exception:
                continue
            loc, rot, sca = local.decompose()
            loc0, q0, e0, aa0, s0 = b0
            # location: locked channels and connected bones keep it
            if kind in ("R", "S") and len(self.items) == 1:     # about its own head: no move
                loc = loc0.copy()
            if pb.bone.use_connect:
                loc = loc0.copy()
            loc = Vector([loc0[i] if pb.lock_location[i] else loc[i] for i in range(3)])
            pb.location = loc
            if kind == "R":
                mode = pb.rotation_mode
                if mode == "QUATERNION":
                    q = rot.copy()
                    if q.dot(q0) < 0:
                        q.negate()
                    if getattr(pb, "lock_rotations_4d", False) or any(pb.lock_rotation):
                        e = q.to_euler("XYZ", q0.to_euler("XYZ"))
                        e0q = q0.to_euler("XYZ")
                        for i in range(3):
                            if pb.lock_rotation[i]:
                                e[i] = e0q[i]
                        q = e.to_quaternion()
                        if q.dot(q0) < 0:
                            q.negate()
                    pb.rotation_quaternion = q
                elif mode == "AXIS_ANGLE":
                    axis, angle = rot.to_axis_angle()
                    pb.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
                else:
                    e = rot.to_euler(mode, e0)            # compatible with the start value
                    for i in range(3):
                        if pb.lock_rotation[i]:
                            e[i] = e0[i]
                    pb.rotation_euler = e
            if kind == "S":
                pb.scale = Vector([s0[i] if pb.lock_scale[i] else sca[i] for i in range(3)])
            if (pb.location - loc0).length > 1e-9:
                self.moved_location = True
        for ob in {it[0] for it in self.items}:
            ob.update_tag()

    def restore(self):
        for ob, pb, _W0, b0 in self.items:
            _set_basis(pb, b0)
        for ob in {it[0] for it in self.items}:
            ob.update_tag()

    def finish(self, kind):
        _autokey([(ob, pb) for ob, pb, _w, _b in self.items], kind, self.moved_location)

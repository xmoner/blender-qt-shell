"""Keyframes for what is selected: objects in Object mode, pose bones (rig controls) in Pose mode.

Used by the viewport (I / Alt+I), the Timeline (+◆ Key / −◆) and the Graph editor (S, curve filter),
so all of them key and show the same thing – like Blender / Maya, where keys go to the selected controls.
"""
import re

import bpy

_BONE_RE = re.compile(r'^pose\.bones\["((?:[^"\\]|\\.)*)"\]\.(.+)$')


def bone_of_path(data_path):
    """('bone name', 'location') for 'pose.bones["bone name"].location', else (None, data_path)."""
    m = _BONE_RE.match(data_path)
    if not m:
        return None, data_path
    return m.group(1).replace('\\"', '"').replace("\\\\", "\\"), m.group(2)


def _rot_path(item):
    mode = item.rotation_mode
    if mode == "QUATERNION":
        return "rotation_quaternion"
    if mode == "AXIS_ANGLE":
        return "rotation_axis_angle"
    return "rotation_euler"


def pose_mode():
    try:
        return bpy.context.mode == "POSE"
    except Exception:
        return False


def selected_bone_names(ob):
    """Names of the selected (visible) pose bones of armature ob."""
    from .wirepick import bone_visible
    if ob is None or ob.type != "ARMATURE" or ob.pose is None:
        return set()
    return {pb.name for pb in ob.pose.bones if pb.select and bone_visible(pb)}


def targets():
    """[(owner_object, keyable_item)] – pose bones in Pose mode, objects otherwise."""
    ctx = bpy.context
    if pose_mode():
        from .wirepick import pose_armatures
        out = []
        for ob in pose_armatures(ctx):
            names = selected_bone_names(ob)
            out.extend((ob, pb) for pb in ob.pose.bones if pb.name in names)
        return out
    return [(ob, ob) for ob in ctx.selected_objects]


def insert(kinds=("location", "rotation", "scale")):
    """Inserts keys with the current values at the current frame. Returns the number of keyed items."""
    n = 0
    for ob, item in targets():
        group = item.name if item is not ob else None
        for k in kinds:
            path = _rot_path(item) if k == "rotation" else k
            try:
                if group:
                    item.keyframe_insert(path, group=group)
                else:
                    item.keyframe_insert(path)
                n += 1
            except Exception as ex:
                from .bridge import log
                log(f"Insert keyframe {item.name}.{path}: {ex}", "WARNING")
    return n


def delete(kinds=("location", "rotation", "scale")):
    """Deletes keys at the current frame. Returns the number of removed keys."""
    n = 0
    for _ob, item in targets():
        for k in kinds:
            path = _rot_path(item) if k == "rotation" else k
            try:
                if item.keyframe_delete(path):
                    n += 1
            except Exception:
                pass
    return n


def fcurve_visible(ob, fc, bone_names=None):
    """In Pose mode only the curves of the selected bones count (Blender's 'Only Show Selected')."""
    if ob.type != "ARMATURE" or ob.mode != "POSE":
        return True
    bone, _p = bone_of_path(fc.data_path)
    if bone is None:
        return False                 # object-level curves of the rig are not shown while posing
    names = selected_bone_names(ob) if bone_names is None else bone_names
    return bone in names


def key_frames(ob):
    """Keyed frames shown in the Timeline for ob (selected bones only in Pose mode)."""
    from .graph_editor import fcurves_of
    frames = set()
    names = selected_bone_names(ob) if ob is not None and ob.type == "ARMATURE" else None
    for fc in fcurves_of(ob) if ob is not None else []:
        if not fcurve_visible(ob, fc, names):
            continue
        for kp in fc.keyframe_points:
            frames.add(int(round(kp.co.x)))
    return sorted(frames)


def current_value(ob, fc):
    """The property's current value (what the user posed), not the curve's value."""
    try:
        v = ob.path_resolve(fc.data_path)
        if hasattr(v, "__len__"):
            v = v[fc.array_index]
        return float(v)
    except Exception:
        return fc.evaluate(bpy.context.scene.frame_current)

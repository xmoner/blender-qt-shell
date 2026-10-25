"""UV checker in the 3D viewport (Maya's Checker Map).

When the UV editor's *Checker* toggle is on, the edited meshes (or the active mesh in other modes) are
drawn with the same checker map as the UV editor (A1–H8 labels). Blender's offscreen draw doesn't run
SpaceView3D draw handlers, so this is our own GPU pass over Blender's finished picture:

- depth-tested against the depth Blender leaves in the offscreen (other objects still cover the mesh);
  the vertices are pulled a tiny bit towards the camera so they win over the same surface;
- blended with MULTIPLY: the checker multiplies Blender's shaded surface, so lighting, the edit-mode
  wires / vertices and the selection tint stay visible;
- nothing is written into the .blend (no material / image is added).
"""

import zlib

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from PySide6 import QtGui

from . import bridge

_VERT = """
void main()
{
    vec4 v = view * model * vec4(pos, 1.0);
    if (ortho == 0) {
        v.xyz *= 0.9995;                 /* towards the eye: same pixel, slightly smaller depth */
    }
    gl_Position = proj * v;
    if (ortho != 0) {
        gl_Position.z -= 0.00005 * gl_Position.w;
    }
    vUV = uv;
}
"""

_FRAG = """
void main()
{
    vec3 c = texture(tex, fract(vUV)).rgb;
    FragColor = vec4(mix(vec3(0.42), vec3(1.0), c), 1.0);   /* dark squares stay readable when multiplied */
}
"""

_shader = None
_shader_failed = False
_tex = None
_batches = {}          # object name -> (data key, batch)


def enabled():
    from .uv_editor import setting
    return setting("checker", False)


def shader():
    global _shader, _shader_failed
    if _shader is not None or _shader_failed:
        return _shader
    try:
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant("MAT4", "proj")
        info.push_constant("MAT4", "view")
        info.push_constant("MAT4", "model")
        info.push_constant("INT", "ortho")
        info.sampler(0, "FLOAT_2D", "tex")
        info.vertex_in(0, "VEC3", "pos")
        info.vertex_in(1, "VEC2", "uv")
        iface = gpu.types.GPUStageInterfaceInfo("qtshell_uvchecker_iface")
        iface.smooth("VEC2", "vUV")
        info.vertex_out(iface)
        info.fragment_out(0, "VEC4", "FragColor")
        info.vertex_source(_VERT)
        info.fragment_source(_FRAG)
        _shader = gpu.shader.create_from_info(info)
    except Exception as ex:
        _shader_failed = True
        bridge.log(f"UV checker shader: {ex}", "WARNING")
    return _shader


def texture():
    """The UV editor's checker image as a GPU texture (rows flipped: v = 0 is the bottom)."""
    global _tex
    if _tex is None:
        from .uv_editor import checker_image
        q = checker_image().convertToFormat(QtGui.QImage.Format_RGBA8888)
        w, h = q.width(), q.height()
        a = np.frombuffer(q.constBits(), np.uint8, count=h * q.bytesPerLine())
        a = a.reshape(h, q.bytesPerLine())[:, :w * 4].reshape(h, w, 4)[::-1]
        a = np.ascontiguousarray(a, np.float32).ravel() / 255.0
        try:
            buf = gpu.types.Buffer("FLOAT", a.size, a)
        except Exception:
            buf = gpu.types.Buffer("FLOAT", a.size, a.tolist())
        _tex = gpu.types.GPUTexture((w, h), format="RGBA8", data=buf)
    return _tex


def objects():
    """Meshes in Edit Mode, else the selected meshes (+ the active one)."""
    try:
        from .uv_editor import uv_objects          # the same objects the UV editor shows
        return [o for o in uv_objects() if o.visible_get()]
    except Exception:
        return []


def _arrays(ob_eval):
    """(corner positions (C,3), corner UVs (C,2), visible triangles (T,3)) of the evaluated mesh, or None."""
    from . import geocache
    me = ob_eval.to_mesh()
    try:
        if me is None or me.uv_layers.active is None or not len(me.loops):
            return None
        pos, _nor, tris, _cmat = geocache._corner_data(me)
        uv = geocache._corner_uv(me)
        if uv is None:
            return None
        npoly = len(me.polygons)
        if npoly and len(tris):
            hide = np.zeros(npoly, bool)
            me.polygons.foreach_get("hide", hide)
            if hide.any():
                tp = np.empty(len(me.loop_triangles), np.int32)
                me.loop_triangles.foreach_get("polygon_index", tp)
                tris = tris[~hide[tp]]
        return (np.ascontiguousarray(pos, np.float32), np.ascontiguousarray(uv, np.float32),
                np.ascontiguousarray(tris, np.int32))
    finally:
        ob_eval.to_mesh_clear()


def _batch(ob, ob_eval, sh):
    arrs = _arrays(ob_eval)
    if arrs is None:
        _batches.pop(ob.name, None)
        return None
    pos, uv, tris = arrs
    key = (len(pos), len(tris), zlib.crc32(pos.tobytes()), zlib.crc32(uv.tobytes()), zlib.crc32(tris.tobytes()))
    hit = _batches.get(ob.name)
    if hit is not None and hit[0] == key:
        return hit[1]
    b = batch_for_shader(sh, "TRIS", {"pos": pos, "uv": uv}, indices=tris)
    _batches[ob.name] = (key, b)
    return b


def draw(offscreen, vm, pm, space):
    """Draws the checker over Blender's picture in offscreen (after draw_view3d). True when it drew."""
    if not enabled() or space is None:
        return False
    shading = space.shading
    if shading.type not in ("SOLID", "MATERIAL") or (shading.type == "SOLID" and shading.show_xray):
        return False
    obs = objects()
    if not obs:
        return False
    sh = shader()
    if sh is None:
        return False
    dg = bpy.context.evaluated_depsgraph_get()
    tex = texture()
    ortho = abs(pm[3][3] - 1.0) < 1e-6 and abs(pm[3][2]) < 1e-6
    drew = False
    with offscreen.bind():
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(False)
        gpu.state.face_culling_set("NONE")
        gpu.state.blend_set("MULTIPLY")
        try:
            sh.bind()
            sh.uniform_float("proj", pm)
            sh.uniform_float("view", vm)
            sh.uniform_int("ortho", 1 if ortho else 0)
            sh.uniform_sampler("tex", tex)
            for ob in obs:
                ob_eval = ob.evaluated_get(dg)
                b = _batch(ob, ob_eval, sh)
                if b is None:
                    continue
                sh.uniform_float("model", ob_eval.matrix_world)
                b.draw(sh)
                drew = True
        finally:
            gpu.state.blend_set("NONE")
            gpu.state.depth_test_set("NONE")
    return drew


def free():
    """Drops the GPU resources (add-on unregister / reload)."""
    global _tex, _shader, _shader_failed
    _batches.clear()
    _tex = None
    _shader = None
    _shader_failed = False

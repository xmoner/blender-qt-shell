"""Geometry playback cache (like Maya's Cached Playback) – independent of the camera.

For every cached frame we keep what the evaluated scene looks like, not a picture of it:
- meshes (also curves / text converted to meshes): the object's world matrix, and – only when the
  object is deformed (armature, modifiers, shape keys) – its evaluated corner positions + normals;
  rigid objects share one copy of their geometry for all frames;
- rig controls: the world-space line segments of the visible pose bones' custom shapes (or the bone
  line when there is no shape), with their bone colours.

During cached playback the viewport draws this itself into its offscreen buffer (solid shading with
material / object / single / random colours and a simple studio-like light, rig controls as lines), so the
camera can move freely while the cache stays valid. Any scene edit (bridge.Flags.edit_version) drops it.
"""
import math
import zlib

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from . import bridge

GEOM_TYPES = {"MESH", "CURVE", "SURFACE", "FONT", "META"}

_version = None
_frames = {}         # frame → {"meshes": [(name, matrix(4x4 f32), deformed_or_None)], "lines": (pos, col, front)}
_static = {}         # object name → static mesh data (see _mesh_static)
_bytes = 0
_shader = None
_shader_failed = False
_batch_cache = {}    # (name, colour key) → GPUBatch for rigid geometry


# ---------------------------------------------------------------- bookkeeping
def _check_version():
    global _version
    from .playcache import scene_version
    v = scene_version()
    if v != _version:
        flush()
        _version = v


def flush():
    global _bytes
    _textures.clear()
    _frames.clear()
    _static.clear()
    _batch_cache.clear()
    _bytes = 0


def used_bytes():
    return _bytes


def has(frame):
    _check_version()
    return frame in _frames


def cached_frames():
    _check_version()
    return set(_frames)


def _nbytes(*arrays):
    return sum(a.nbytes for a in arrays if a is not None)


# ---------------------------------------------------------------- capture
def _corner_data(me):
    """(corner positions (C,3), corner normals (C,3), triangles (T,3) of corner indices, corner material (C,))."""
    nv, nl = len(me.vertices), len(me.loops)
    co = np.empty(nv * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    cv = np.empty(nl, np.int32)
    me.loops.foreach_get("vertex_index", cv)
    try:
        me.calc_loop_triangles()
    except Exception:
        pass
    nt = len(me.loop_triangles)
    tris = np.empty(nt * 3, np.int32)
    me.loop_triangles.foreach_get("loops", tris)
    tris = tris.reshape(-1, 3)
    tmat = np.empty(nt, np.int32)
    me.loop_triangles.foreach_get("material_index", tmat)
    nor = None
    try:
        cn = me.corner_normals                      # Blender 4.1+
        if len(cn) == nl:
            nor = np.empty(nl * 3, np.float32)
            cn.foreach_get("vector", nor)
            nor = nor.reshape(-1, 3)
    except Exception:
        nor = None
    if nor is None:
        vn = np.empty(nv * 3, np.float32)
        try:
            me.vertex_normals.foreach_get("vector", vn)
        except Exception:
            me.vertices.foreach_get("normal", vn)
        nor = vn.reshape(-1, 3)[cv]
    cmat = np.zeros(nl, np.int32)
    if nt:
        cmat[tris.ravel()] = np.repeat(tmat, 3)
    return co[cv], nor, tris, cmat


def _corner_uv(me):
    """Active UV map per corner (C,2) or None."""
    try:
        uvl = me.uv_layers.active
        if uvl is None:
            return None
        uv = np.empty(len(me.loops) * 2, np.float32)
        try:
            uvl.uv.foreach_get("vector", uv)          # Blender 3.5+
        except Exception:
            uvl.data.foreach_get("uv", uv)
        return uv.reshape(-1, 2)
    except Exception:
        return None


def _rigid(ob):
    """Objects whose evaluated geometry can't change between frames (only their matrix moves)."""
    if ob.type != "MESH":
        return False
    if len(ob.modifiers) or (ob.data.shape_keys is not None):
        return False
    return True


def _capture_mesh(ob, ev):
    """Static data on first sight; per frame the deformed corners when the object is not rigid."""
    global _bytes
    st = _static.get(ob.name)
    rigid = _rigid(ob)
    if st is not None and rigid:
        return None
    try:
        me = ev.to_mesh()
    except Exception:
        return False
    try:
        if me is None or not len(me.loops):
            return False
        pos, nor, tris, cmat = _corner_data(me)
        need_uv = st is None or len(st["pos"]) != len(pos) or not np.array_equal(st["tris"], tris)
        uv = _corner_uv(me) if need_uv else None
    finally:
        try:
            ev.to_mesh_clear()
        except Exception:
            pass
    if st is None:
        mats = [s.material for s in ob.material_slots]
        st = {"pos": pos, "nor": nor, "tris": tris, "cmat": cmat, "mats": mats, "uv": uv}
        _static[ob.name] = st
        _bytes += _nbytes(pos, nor, tris, cmat, uv)
        return None
    if len(st["pos"]) != len(pos) or not np.array_equal(st["tris"], tris):
        # the topology changes between frames (some modifiers do) – this frame keeps its own mesh;
        # the shared base must never be replaced, earlier frames refer to it
        _bytes += _nbytes(pos, nor, tris, cmat, uv)
        return (pos, nor, tris, cmat, uv)
    if rigid or np.allclose(pos, st["pos"], atol=1e-6):
        return None
    _bytes += _nbytes(pos, nor)
    return (pos, nor)


def _bone_color(ob, pb):
    """(normal, select, active) colours of a pose bone like Blender's bone colour sets."""
    default = ((0.0, 0.0, 0.0, 1.0), (0.35, 0.7, 1.0, 1.0), (0.6, 0.9, 1.0, 1.0))
    try:
        for c in (pb.color, pb.bone.color):
            pal = c.palette
            if pal == "DEFAULT":
                continue
            if pal == "CUSTOM":
                cs = c.custom
            else:
                cs = bpy.context.preferences.themes[0].bone_color_sets[int(pal[5:]) - 1]
            return (tuple(cs.normal) + (1.0,), tuple(cs.select) + (1.0,), tuple(cs.active) + (1.0,))
    except Exception:
        pass
    return default


def _capture_lines():
    """World-space line segments of the visible rig controls: (positions (N,3), colours (N,4), in_front)."""
    from .wirepick import _arrays, bone_visible, shape_matrix
    pos_all, col_all, front_all = [], [], []
    for ob in bpy.context.visible_objects:
        if ob.type != "ARMATURE" or ob.pose is None:
            continue
        act = ob.data.bones.active
        for pb in ob.pose.bones:
            if not bone_visible(pb):
                continue
            n, s, a = _bone_color(ob, pb)
            col = a if (pb.select and act is not None and act.name == pb.name) else (s if pb.select else n)
            shape = pb.custom_shape
            try:
                if shape is not None and shape.type == "MESH":
                    co, ed, _t = _arrays(shape.data)
                    if not len(ed):
                        continue
                    M = np.array(shape_matrix(ob, pb), np.float64)
                    w = (np.c_[co, np.ones(len(co))] @ M.T)[:, :3]
                    seg = w[ed.ravel()].astype(np.float32)
                else:
                    mw = ob.matrix_world
                    seg = np.array([tuple(mw @ pb.head), tuple(mw @ pb.tail)], np.float32)
            except Exception:
                continue
            pos_all.append(seg)
            col_all.append(np.tile(np.array(col, np.float32), (len(seg), 1)))
            front_all.append(np.full(len(seg), bool(ob.show_in_front)))
    if not pos_all:
        return None
    return np.concatenate(pos_all), np.concatenate(col_all), np.concatenate(front_all)


def capture(frame):
    """Stores the evaluated scene at the current frame (call right after frame_set)."""
    global _bytes
    _check_version()
    if frame in _frames:
        return
    from . import playcache
    if playcache.full_bytes(_bytes):
        return
    ctx = bpy.context
    dg = ctx.evaluated_depsgraph_get()
    meshes = []
    for ob in ctx.visible_objects:
        if ob.type not in GEOM_TYPES or ob.display_type in ("WIRE", "BOUNDS"):
            continue
        ev = ob.evaluated_get(dg)
        d = _capture_mesh(ob, ev)
        if d is False or ob.name not in _static:
            continue
        meshes.append((ob.name, np.array(ev.matrix_world, np.float32), d))
    lines = _capture_lines()
    if lines is not None:
        _bytes += _nbytes(*lines)
    _frames[frame] = {"meshes": meshes, "lines": lines}


# ---------------------------------------------------------------- drawing
_VERT = """
void main()
{
    vN = mat3(view) * mat3(model) * nor;
    vC = col;
    vUV = uv;
    gl_Position = viewProj * model * vec4(pos, 1.0);
}
"""
_FRAG = """
void main()
{
    vec3 n = normalize(vN);
    if (!gl_FrontFacing) n = -n;
    vec3 l1 = normalize(vec3(-0.35, 0.55, 0.75));
    vec3 l2 = normalize(vec3(0.6, -0.2, 0.5));
    float d = 0.30 + 0.62 * max(dot(n, l1), 0.0) + 0.22 * max(dot(n, l2), 0.0)
              + 0.10 * pow(1.0 - max(n.z, 0.0), 2.0);
    vec3 base = vC.rgb;
    if (useTex == 1) {
        base = texture(tex, vUV).rgb;
    }
    vec3 c = base * d;
    c = pow(clamp(c, 0.0, 1.0), vec3(1.0 / 2.2));
    FragColor = vec4(c, 1.0);
}
"""


def shader():
    global _shader, _shader_failed
    if _shader is not None or _shader_failed:
        return _shader
    try:
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant("MAT4", "viewProj")
        info.push_constant("MAT4", "view")
        info.push_constant("MAT4", "model")
        info.push_constant("INT", "useTex")
        info.sampler(0, "FLOAT_2D", "tex")
        info.vertex_in(0, "VEC3", "pos")
        info.vertex_in(1, "VEC3", "nor")
        info.vertex_in(2, "VEC4", "col")
        info.vertex_in(3, "VEC2", "uv")
        iface = gpu.types.GPUStageInterfaceInfo("qtshell_geocache_iface2")
        iface.smooth("VEC3", "vN")
        iface.smooth("VEC4", "vC")
        iface.smooth("VEC2", "vUV")
        info.vertex_out(iface)
        info.fragment_out(0, "VEC4", "FragColor")
        info.vertex_source(_VERT)
        info.fragment_source(_FRAG)
        _shader = gpu.shader.create_from_info(info)
    except Exception as ex:
        _shader_failed = True
        bridge.log(f"Geometry cache shader: {ex}", "WARNING")
    return _shader


def _srgb_to_lin(c):
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c[:3]]


_image_avg = {}


def _image_color(img):
    """Average colour of an image (linear), computed once per image – a texture's overall colour."""
    key = (img.name, img.size[0], img.size[1])
    hit = _image_avg.get(key)
    if hit is not None:
        return hit
    col = [0.8, 0.8, 0.8, 1.0]
    try:
        w, h = img.size
        if w and h:
            px = np.empty(w * h * img.channels, np.float32)
            img.pixels.foreach_get(px)
            px = px.reshape(-1, img.channels)
            step = max(1, len(px) // 65536)            # a sample is enough
            s = px[::step]
            rgb = s[:, :3].mean(axis=0) if img.channels >= 3 else np.repeat(s[:, :1].mean(), 3)
            col = [float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0]
            if not getattr(img, "is_float", False) and getattr(img.colorspace_settings, "name", "") == "sRGB":
                col = _srgb_to_lin(col) + [1.0]
    except Exception:
        pass
    _image_avg[key] = col
    return col


_textures = {}
_dummy_tex = None


def _dummy():
    """1×1 white texture bound when a part has no image (a sampler must always have a texture)."""
    global _dummy_tex
    if _dummy_tex is None:
        buf = gpu.types.Buffer("FLOAT", 4, [1.0, 1.0, 1.0, 1.0])
        _dummy_tex = gpu.types.GPUTexture((1, 1), format="RGBA8", data=buf)
    return _dummy_tex


def _upstream_image(node, depth=0, seen=None):
    """First colour Image Texture found walking the node links upstream from node."""
    seen = set() if seen is None else seen
    if node is None or depth > 12 or node.name in seen:
        return None
    seen.add(node.name)
    if node.type == "TEX_IMAGE":
        return node.image
    for inp in node.inputs:
        for link in inp.links:
            img = _upstream_image(link.from_node, depth + 1, seen)
            if img is not None:
                return img
    return None


def _is_color_image(img):
    return img is not None and getattr(img.colorspace_settings, "name", "") not in (
        "Non-Color", "Raw", "Linear Rec.709") or (img is not None and img.is_float is False
                                                  and img.colorspace_settings.name == "sRGB")


def _mat_image(m):
    """The image to show in Solid → Texture mode: the one feeding the shader's Base Color (through any
    nodes), else the active Image Texture node, else the first colour image; None when there is none."""
    if m is None or not m.use_nodes or m.node_tree is None:
        return None
    try:
        nodes = m.node_tree.nodes
        for node in nodes:
            if node.type == "BSDF_PRINCIPLED":
                inp = node.inputs.get("Base Color")
                if inp is not None and inp.is_linked:
                    img = _upstream_image(inp.links[0].from_node)
                    if img is not None:
                        return img
                break
        act = nodes.active
        if act is not None and act.type == "TEX_IMAGE" and _is_color_image(act.image):
            return act.image
        for node in nodes:
            if node.type == "TEX_IMAGE" and _is_color_image(node.image):
                return node.image
    except Exception:
        pass
    return None


def _texture(img):
    key = (img.name, img.size[0], img.size[1])
    tex = _textures.get(key)
    if tex is None:
        try:
            tex = gpu.texture.from_image(img)
        except Exception:
            tex = False
        _textures[key] = tex
    return tex or None


def _mat_color(m, mode):
    """Solid-mode colour of a material: its viewport display colour (Material mode, and Texture mode
    for materials without an image), the image's average colour as a fallback when textures can't be drawn."""
    if m is None:
        return [0.8, 0.8, 0.8, 1.0]
    return list(m.diffuse_color)


def _colors(name, st, space, cmat=None):
    """Linear RGBA per corner for the view's solid colour mode."""
    sh = space.shading if space is not None else None
    mode = getattr(sh, "color_type", "MATERIAL") if sh else "MATERIAL"
    ob = bpy.data.objects.get(name)
    if cmat is None:
        cmat = st["cmat"]
    n = len(cmat)
    if mode == "SINGLE":
        c = list(sh.single_color) + [1.0]
        return np.tile(np.array(c, np.float32), (n, 1)), ("SINGLE", tuple(c))
    if mode == "OBJECT" and ob is not None:
        c = list(ob.color)
        return np.tile(np.array(c, np.float32), (n, 1)), ("OBJECT", tuple(c))
    if mode == "RANDOM":
        h = zlib.crc32(name.encode()) / 0xFFFFFFFF
        c = [0.5 + 0.4 * math.cos(6.283 * (h + k / 3.0)) for k in range(3)] + [1.0]
        return np.tile(np.array(_srgb_to_lin(c) + [1.0], np.float32), (n, 1)), ("RANDOM",)
    pal = [_mat_color(m, mode) for m in st["mats"]] or [[0.8, 0.8, 0.8, 1.0]]
    pal = np.array(pal, np.float32)
    idx = np.clip(cmat, 0, len(pal) - 1)
    return pal[idx], (mode, pal.tobytes())


def _batch(sh, pos, nor, col, tris, uv=None):
    if uv is None:
        uv = np.zeros((len(pos), 2), np.float32)
    return batch_for_shader(sh, "TRIS", {"pos": pos, "nor": nor, "col": col, "uv": uv}, indices=tris)


def _parts(name, st, space, pos, nor, tris, cmat, uv, cache_key=None):
    """[(batch, texture or None)] – one batch per material, so textured materials can bind their image."""
    sh = shader()
    mode = getattr(space.shading, "color_type", "MATERIAL") if space is not None else "MATERIAL"
    col, ckey = _colors(name, st, space, cmat)
    if cache_key is not None:
        hit = _batch_cache.get((cache_key, ckey))
        if hit is not None:
            return hit
    out = []
    mats = st["mats"] or [None]
    tmat = cmat[tris[:, 0]] if len(tris) else np.zeros(0, np.int32)
    use_tex = mode == "TEXTURE" and uv is not None
    for mi in (np.unique(tmat) if len(tmat) else []):
        sel = tris[tmat == mi]
        m = mats[min(int(mi), len(mats) - 1)]
        img = _mat_image(m) if use_tex else None
        tex = _texture(img) if img is not None else None
        out.append((_batch(sh, pos, nor, col, sel, uv if tex is not None else None), tex))
    if cache_key is not None:
        _batch_cache[(cache_key, ckey)] = out
    return out


def draw(offscreen, frame, vm, pm, space, dpr):
    """Draws the cached frame into the offscreen (transparent background). True when it drew."""
    data = _frames.get(frame)
    sh = shader()
    if data is None or sh is None:
        return False
    show_overlays = bool(getattr(space.overlay, "show_overlays", True)) if space is not None else True
    show_bones = show_overlays and bool(getattr(space.overlay, "show_bones", True)) if space is not None else True
    with offscreen.bind():
        fb = gpu.state.active_framebuffer_get()
        fb.clear(color=(0.0, 0.0, 0.0, 0.0), depth=1.0)
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(True)
        gpu.state.face_culling_set("NONE")
        sh.bind()
        sh.uniform_float("viewProj", pm @ vm)
        sh.uniform_float("view", vm)
        for name, mat, deformed in data["meshes"]:
            st = _static.get(name)
            if st is None:
                continue
            sh.uniform_float("model", Matrix(mat.tolist()))
            if deformed is None:
                parts = _parts(name, st, space, st["pos"], st["nor"], st["tris"], st["cmat"], st["uv"],
                               cache_key=name)
            elif len(deformed) == 5:                    # own topology in this frame
                parts = _parts(name, st, space, *deformed)
            else:
                parts = _parts(name, st, space, deformed[0], deformed[1], st["tris"], st["cmat"], st["uv"])
            for b, tex in parts:
                if tex is not None:
                    sh.uniform_sampler("tex", tex)
                    sh.uniform_int("useTex", 1)
                else:
                    sh.uniform_sampler("tex", _dummy())
                    sh.uniform_int("useTex", 0)
                b.draw(sh)
        lines = data["lines"]
        if lines is not None and show_bones:
            pos, col, front = lines
            lsh = gpu.shader.from_builtin("POLYLINE_SMOOTH_COLOR")
            with gpu.matrix.push_pop():
                gpu.matrix.load_matrix(vm)
                gpu.matrix.load_projection_matrix(pm)
                lsh.bind()
                lsh.uniform_float("viewportSize", (offscreen.width, offscreen.height))
                lsh.uniform_float("lineWidth", 1.6 * dpr)
                gpu.state.blend_set("ALPHA")
                for in_front in (False, True):
                    sel = np.repeat(front.reshape(-1, 2)[:, 0] == in_front, 2)
                    if not sel.any():
                        continue
                    gpu.state.depth_test_set("NONE" if in_front else "LESS_EQUAL")
                    batch_for_shader(lsh, "LINES", {"pos": pos[sel], "color": col[sel]}).draw(lsh)
                gpu.state.blend_set("NONE")
        gpu.state.depth_test_set("NONE")
        gpu.state.depth_mask_set(False)
    return True

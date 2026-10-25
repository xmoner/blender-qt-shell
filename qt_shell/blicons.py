"""Icons for Blender's icon names (MESH_CUBE, MOD_ARRAY, OUTLINER_OB_CAMERA, …) – Qt Shell's own drawings
in the style of Blender's interface (16 × 16 grid). Used wherever Blender's UI code passes icon="…" to an
operator, menu item, tab or tree item. Unknown names return a null QIcon (callers keep their text).

    from . import blicons
    button.setIcon(blicons.icon("MESH_CUBE"))
"""
from PySide6 import QtCore, QtGui

try:
    from PySide6 import QtSvg
except Exception:
    QtSvg = None

W = "#d6d6d6"        # neutral
OB = "#f0a05a"       # objects (orange)
DA = "#86c86e"       # object data (green)
MO = "#7cb4f0"       # modifiers / constraints (blue)
LI = "#f2d061"       # lights (yellow)
RD = "#e86a6a"       # warnings / delete

_I = {}


def _s(c=W, w=1.2):
    return f'fill="none" stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"'


def add(names, body):
    for n in names.split():
        _I[n] = body


# ------------------------------------------------------------------ object type symbols
def mesh_tri(c):
    return f'<path {_s(c)} d="M8 2.5 L13.5 12.5 H2.5 Z"/><circle cx="8" cy="2.5" r="1.3" fill="{c}"/>' \
           f'<circle cx="13.5" cy="12.5" r="1.3" fill="{c}"/><circle cx="2.5" cy="12.5" r="1.3" fill="{c}"/>'


def camera(c):
    return f'<path {_s(c)} d="M2 5 H10 V12 H2 Z M10 7.5 L14 5.5 V11.5 L10 9.5"/>'


def bulb(c):
    return f'<path {_s(c)} d="M8 2 A4 4 0 0 1 10.5 9.2 V11 H5.5 V9.2 A4 4 0 0 1 8 2 Z M6 13 H10 M6.8 14.6 H9.2"/>'


def axes(c):
    return f'<path {_s(c)} d="M8 8 V2 M8 8 L13.5 11 M8 8 L2.5 11"/>'


def curve(c):
    return f'<path {_s(c, 1.4)} d="M2 12 C4 3 12 13 14 4"/><circle cx="2" cy="12" r="1.3" fill="{c}"/>' \
           f'<circle cx="14" cy="4" r="1.3" fill="{c}"/>'


def bone(c):
    return f'<path {_s(c)} d="M4 12 L11 5 M3 10.5 A1.6 1.6 0 1 0 5.5 13 M10.5 3 A1.6 1.6 0 1 1 13 5.5"/>'


def font(c):
    return f'<path {_s(c, 1.4)} d="M3 13 L8 3 L13 13 M5 9 H11"/>'


def lattice(c):
    return f'<path {_s(c)} d="M3 3 H13 V13 H3 Z M3 8 H13 M8 3 V13"/><circle cx="3" cy="3" r="1.2" fill="{c}"/>' \
           f'<circle cx="13" cy="13" r="1.2" fill="{c}"/>'


def surface(c):
    return f'<path {_s(c)} d="M2 10 C5 6 11 14 14 9 M2 6 C5 2 11 10 14 5 M4 4 V12 M8 6 V12 M12 4 V11"/>'


def meta(c):
    return f'<circle cx="6" cy="8" r="3.6" {_s(c)}/><circle cx="11" cy="7" r="2.6" {_s(c)}/>'


def gpencil(c):
    return f'<path {_s(c)} d="M11 2.5 L13.5 5 L6 12.5 L3 13 L3.5 10 Z"/><path {_s(c)} d="M2 15 C5 13 9 15 14 13"/>'


def speaker(c):
    return f'<path {_s(c)} d="M3 6 H6 L10 3 V13 L6 10 H3 Z M12 6 A3 3 0 0 1 12 10"/>'


def probe(c):
    return f'<circle cx="8" cy="8" r="5" {_s(c)}/><circle cx="8" cy="8" r="1.8" fill="{c}"/>'


def image(c):
    return f'<rect x="2" y="3" width="12" height="10" rx="1" {_s(c)}/><path {_s(c)} d="M3 12 L7 8 L10 11 L12 9 L14 11"/>' \
           f'<circle cx="11" cy="6" r="1.2" fill="{c}"/>'


def hair(c):
    return f'<path {_s(c)} d="M3 14 C3 9 5 5 4 2 M8 14 C8 9 9 5 8 2 M13 14 C13 9 11 5 12 2"/>'


def cloud(c):
    return "".join(f'<circle cx="{x}" cy="{y}" r="1.2" fill="{c}"/>' for x, y in
                   ((4, 5), (8, 3.5), (12, 5), (5.5, 9), (10, 8.5), (3.5, 12.5), (8, 12.5), (12.5, 12)))


def volume(c):
    return f'<path {_s(c)} d="M4 11 A3 3 0 0 1 4.5 5.2 A4 4 0 0 1 12 5 A3 3 0 0 1 12 11 Z"/>'


def force(c):
    return f'<circle cx="8" cy="8" r="1.6" fill="{c}"/><circle cx="8" cy="8" r="4" {_s(c)} stroke-dasharray="2 1.6"/>' \
           f'<circle cx="8" cy="8" r="6.4" {_s(c)} stroke-dasharray="2 2"/>'


def collection(c):
    return f'<rect x="2" y="3" width="12" height="10" rx="1.5" {_s(c)}/><path {_s(c)} d="M2 6 H14"/>'


def scene_data(c):
    return f'<path {_s(c)} d="M3 13 L8 3 L13 13 Z"/><circle cx="8" cy="10" r="1.6" fill="{c}"/>'


TYPES = {"MESH": mesh_tri, "CAMERA": camera, "LIGHT": bulb, "LAMP": bulb, "EMPTY": axes, "CURVE": curve,
         "ARMATURE": bone, "FONT": font, "LATTICE": lattice, "SURFACE": surface, "META": meta,
         "GREASEPENCIL": gpencil, "GPENCIL": gpencil, "SPEAKER": speaker, "LIGHTPROBE": probe,
         "LIGHT_PROBE": probe, "IMAGE": image, "CURVES": hair, "POINTCLOUD": cloud, "VOLUME": volume,
         "FORCE_FIELD": force}
for t, fn in TYPES.items():
    add(f"OUTLINER_OB_{t}", fn(OB))
    add(f"OUTLINER_DATA_{t}", fn(DA))
    add(f"{t}_DATA", fn(DA))
add("OBJECT_DATA OBJECT_DATAMODE", mesh_tri(OB))
add("OUTLINER_COLLECTION GROUP COLLECTION_NEW", collection(W))
add("SCENE_DATA", scene_data(W))
add("LIGHT LIGHT_DATA OUTLINER_OB_LIGHT", bulb(LI))
add("OUTLINER_DATA_LIGHT", bulb(DA))
add("FILE_IMAGE IMAGE_DATA", image(W))
add("FILE_FONT", font(W))

# ------------------------------------------------------------------ mesh primitives
add("MESH_PLANE", f'<path {_s()} d="M2 10 L8 6.5 L14 10 L8 13.5 Z"/>')
add("MESH_CUBE CUBE", f'<path {_s()} d="M8 2 L13.5 5 V11 L8 14 L2.5 11 V5 Z M2.5 5 L8 8 L13.5 5 M8 8 V14"/>')
add("MESH_CIRCLE", f'<circle cx="8" cy="8" r="5.6" {_s()}/>' + "".join(
    f'<circle cx="{8 + 5.6 * c:.1f}" cy="{8 + 5.6 * s:.1f}" r="1" fill="{W}"/>'
    for c, s in ((1, 0), (0.7, 0.7), (0, 1), (-0.7, 0.7), (-1, 0), (-0.7, -0.7), (0, -1), (0.7, -0.7))))
add("MESH_UVSPHERE SPHERE", f'<circle cx="8" cy="8" r="5.8" {_s()}/><ellipse cx="8" cy="8" rx="5.8" ry="2" {_s()}/>'
    f'<ellipse cx="8" cy="8" rx="2.4" ry="5.8" {_s()}/>')
add("MESH_ICOSPHERE", f'<path {_s()} d="M8 2 L13.4 5 V11 L8 14 L2.6 11 V5 Z M8 2 L5 8 L11 8 Z M2.6 5 L5 8 L2.6 11 M13.4 5 '
    f'L11 8 L13.4 11 M5 8 L8 14 L11 8"/>')
add("MESH_CYLINDER", f'<ellipse cx="8" cy="4" rx="5" ry="2" {_s()}/><path {_s()} d="M3 4 V12 A5 2 0 0 0 13 12 V4"/>')
add("MESH_CONE CONE", f'<path {_s()} d="M8 2 L3 12 M8 2 L13 12"/><ellipse cx="8" cy="12" rx="5" ry="2" {_s()}/>')
add("MESH_TORUS", f'<ellipse cx="8" cy="8.5" rx="6" ry="3.6" {_s()}/><ellipse cx="8" cy="8" rx="2.4" ry="1.2" {_s()}/>')
add("MESH_GRID", f'<path {_s()} d="M2.5 2.5 H13.5 V13.5 H2.5 Z M2.5 6.2 H13.5 M2.5 9.8 H13.5 M6.2 2.5 V13.5 M9.8 2.5 V13.5"/>')
add("MESH_MONKEY MONKEY", f'<circle cx="3.2" cy="7" r="2" {_s()}/><circle cx="12.8" cy="7" r="2" {_s()}/>'
    f'<path {_s()} d="M8 2.5 C11.5 2.5 12.2 5 12 8 C11.8 12 10 13.6 8 13.6 C6 13.6 4.2 12 4 8 C3.8 5 4.5 2.5 8 2.5 Z"/>'
    f'<ellipse cx="8" cy="10.5" rx="2.6" ry="1.6" {_s()}/><circle cx="6.5" cy="7" r=".9" fill="{W}"/>'
    f'<circle cx="9.5" cy="7" r=".9" fill="{W}"/>')

# ------------------------------------------------------------------ curves, empties, lights
add("CURVE_BEZCURVE CURVE_PATH CURVE_NCURVE", curve(W))
add("CURVE_BEZCIRCLE CURVE_NCIRCLE", f'<circle cx="8" cy="8" r="5.4" {_s(W, 1.4)}/><circle cx="8" cy="2.6" r="1.3" '
    f'fill="{W}"/><circle cx="13.4" cy="8" r="1.3" fill="{W}"/><circle cx="8" cy="13.4" r="1.3" fill="{W}"/>'
    f'<circle cx="2.6" cy="8" r="1.3" fill="{W}"/>')
add("EMPTY_AXIS", axes(W))
add("EMPTY_ARROWS", f'<path {_s()} d="M8 2 V14 M2 8 H14"/><path fill="{W}" d="M8 1 L9.6 3.6 H6.4 Z M15 8 L12.4 9.6 V6.4 Z"/>')
add("EMPTY_SINGLE_ARROW", f'<path {_s()} d="M8 14 V3"/><path fill="{W}" d="M8 1.5 L10 4.6 H6 Z"/>')
add("EMPTY_DATA", axes(DA))
add("LIGHT_POINT", f'<circle cx="8" cy="8" r="2.6" fill="{LI}"/>' + "".join(
    f'<path {_s(LI)} d="M{8 + 4.5 * c:.1f} {8 + 4.5 * s:.1f} L{8 + 6.2 * c:.1f} {8 + 6.2 * s:.1f}"/>'
    for c, s in ((1, 0), (0.7, 0.7), (0, 1), (-0.7, 0.7), (-1, 0), (-0.7, -0.7), (0, -1), (0.7, -0.7))))
add("LIGHT_SUN", f'<circle cx="8" cy="5.5" r="2.4" fill="{LI}"/><path {_s(LI)} d="M4 9.5 L3 13.5 M8 10 V14 M12 9.5 L13 13.5"/>')
add("LIGHT_SPOT", f'<path {_s(LI)} d="M8 2 L3 13 M8 2 L13 13"/><ellipse cx="8" cy="13" rx="5" ry="1.5" {_s(LI)}/>')
add("LIGHT_AREA", f'<rect x="3" y="2.5" width="10" height="5" {_s(LI)}/><path {_s(LI)} d="M4 9.5 V13.5 M8 9.5 V13.5 M12 9.5 V13.5"/>')
add("OUTLINER_OB_FORCE_FIELD FORCE_FORCE FORCE_WIND FORCE_VORTEX FORCE_MAGNETIC FORCE_TURBULENCE", force(OB))

# ------------------------------------------------------------------ properties tabs & data
add("TOOL_SETTINGS", f'<path {_s()} d="M10.5 2.5 A3 3 0 0 0 9 7 L3 13 L4.5 14.5 L10.5 8.5 A3 3 0 0 0 14 6 L12 6 L10 4 Z"/>')
add("SCENE RENDER_STILL", f'<rect x="2" y="4" width="10" height="8" rx="1" {_s()}/><path {_s()} d="M12 7 L14.5 5.5 V10.5 L12 9"/>'
    f'<circle cx="7" cy="8" r="2" {_s()}/>')
add("OUTPUT RENDER_ANIMATION", f'<rect x="2.5" y="2" width="11" height="12" rx="1" {_s()}/><path {_s()} d="M5 5 H11 M5 8 H11 M5 11 H9"/>')
add("RENDER_RESULT RENDERLAYERS", f'<rect x="2" y="2.5" width="12" height="11" rx="1" {_s()}/><path {_s()} d="M2 9 L6 6 L9 9 L11 7.5 L14 10"/>')
add("WORLD WORLD_DATA", f'<circle cx="8" cy="8" r="5.8" {_s()}/><path {_s()} d="M3.5 5.5 C6 7 6 9 4.5 12 M9 2.5 C8 5 11 6 13.5 6 M9 13.8 C9 11 11 10 13.6 10"/>')
add("MODIFIER MODIFIER_DATA", f'<path {_s(MO)} d="M10.5 2.5 A3 3 0 0 0 9 7 L3 13 L4.5 14.5 L10.5 8.5 A3 3 0 0 0 14 6 L12 6 L10 4 Z"/>')
add("PARTICLES PARTICLE_DATA", f'<circle cx="4" cy="11" r="2" fill="{W}"/>' + cloud(W)[:0] +
    f'<circle cx="9" cy="6" r="1.5" fill="{W}"/><circle cx="12.5" cy="3" r="1" fill="{W}"/>'
    f'<circle cx="12" cy="9.5" r="1.2" fill="{W}"/><circle cx="7.5" cy="12.5" r="1" fill="{W}"/>')
add("PHYSICS", f'<circle cx="8" cy="8" r="1.8" fill="{W}"/><ellipse cx="8" cy="8" rx="6" ry="2.4" {_s()}/>'
    f'<ellipse cx="8" cy="8" rx="6" ry="2.4" {_s()} transform="rotate(60 8 8)"/>'
    f'<ellipse cx="8" cy="8" rx="6" ry="2.4" {_s()} transform="rotate(-60 8 8)"/>')
add("CONSTRAINT CONSTRAINT_DATA CONSTRAINT_BONE", f'<path {_s(MO)} d="M6.5 9.5 L9.5 6.5 M7 4.5 L8.5 3 A2.5 2.5 0 0 1 13 7.5 L11.5 9 '
    f'M9 11.5 L7.5 13 A2.5 2.5 0 0 1 3 8.5 L4.5 7"/>')
add("MATERIAL MATERIAL_DATA SHADING_RENDERED", f'<circle cx="8" cy="8" r="5.8" fill="#c86a3a"/><circle cx="6" cy="6" r="2" fill="#ffffff" fill-opacity=".75"/>')
add("TEXTURE TEXTURE_DATA", f'<rect x="2.5" y="2.5" width="11" height="11" {_s()}/><path fill="{W}" d="M2.5 2.5 h3.7 v3.7 h-3.7z '
    f'M9.8 2.5 h3.7 v3.7 h-3.7z M6.2 6.2 h3.6 v3.6 h-3.6z M2.5 9.8 h3.7 v3.7 h-3.7z M9.8 9.8 h3.7 v3.7 h-3.7z"/>')
add("BONE_DATA", bone(DA))
add("GROUP_VERTEX", f'<path {_s(DA)} d="M3 13 L8 3 L13 13 Z"/><circle cx="3" cy="13" r="1.6" fill="{DA}"/>'
    f'<circle cx="8" cy="3" r="1.6" fill="{DA}"/><circle cx="13" cy="13" r="1.6" fill="{DA}"/>')
add("SHAPEKEY_DATA", f'<path {_s(DA)} d="M2 12 L8 3 L14 12 Z"/><path fill="{DA}" d="M8 8 L10 10 L8 12 L6 10 Z"/>')
add("UV UV_DATA GROUP_UVS", f'<path {_s(DA)} d="M3 13 V5 L11 3 L13 11 Z"/><path {_s(DA)} d="M3 5 L13 11 M11 3 L3 13" opacity=".6"/>')
add("NODETREE NODE NODE_MATERIAL", f'<rect x="1.5" y="3" width="5" height="4" rx="1" {_s()}/><rect x="9.5" y="9" width="5" height="4" rx="1" {_s()}/>'
    f'<path {_s()} d="M6.5 5 C9 5 7 11 9.5 11"/>')
add("GEOMETRY_NODES", f'<rect x="1.5" y="3" width="5" height="4" rx="1" {_s(MO)}/><rect x="9.5" y="9" width="5" height="4" rx="1" {_s(MO)}/>'
    f'<path {_s(MO)} d="M6.5 5 C9 5 7 11 9.5 11"/>')
add("BRUSH_DATA BRUSHES_ALL", f'<path {_s()} d="M10.5 2.5 L13.5 5.5 L7 12 L4 9 Z M4 9 L2.5 13.5 L7 12"/>')

# ------------------------------------------------------------------ modifiers (blue)
M = MO
add("MOD_ARRAY", f'<rect x="1.5" y="5.5" width="4" height="5" {_s(M)}/><rect x="6" y="5.5" width="4" height="5" {_s(M)}/>'
    f'<rect x="10.5" y="5.5" width="4" height="5" {_s(M)} opacity=".55"/>')
add("MOD_BEVEL", f'<path {_s(M)} d="M2 14 V7 L7 2 H14"/><path {_s(M, 2.2)} d="M2 7 L7 2"/>')
add("MOD_BOOLEAN", f'<rect x="2" y="2" width="8" height="8" {_s(M)}/><circle cx="10" cy="10" r="4.2" {_s(M)}/>')
add("MOD_MIRROR", f'<path {_s(M)} d="M8 1.5 V14.5" stroke-dasharray="1.6 1.4"/><path fill="{M}" d="M6.5 4 L2 8 L6.5 12 Z"/>'
    f'<path {_s(M)} d="M9.5 4 L14 8 L9.5 12 Z"/>')
add("MOD_SOLIDIFY", f'<path {_s(M)} d="M2 6 L8 3 L14 6 L8 9 Z M2 6 V10 L8 13 V9 M14 6 V10 L8 13"/>')
add("MOD_SUBSURF", f'<rect x="2.5" y="2.5" width="11" height="11" rx="1" {_s(M)} opacity=".5"/><circle cx="8" cy="8" r="5" {_s(M)}/>')
add("MOD_DECIM", f'<path {_s(M)} d="M2 13 L8 3 L14 13 Z M5 8 H11 M8 13 L5 8 M8 13 L11 8"/>')
add("MOD_REMESH", f'<path {_s(M)} d="M3 3 H13 V13 H3 Z M3 8 H13 M8 3 V13 M3 3 L13 13"/>')
add("MOD_SMOOTH", f'<path {_s(M, 1.5)} d="M1.5 10 C4 4 6 4 8 8 C10 12 12 12 14.5 6"/>')
add("MOD_SCREW", f'<path {_s(M)} d="M4 3 C12 3 12 6 4 6 C12 6 12 9 4 9 C12 9 12 12 4 12"/>')
add("MOD_SKIN", f'<circle cx="4" cy="11" r="2.4" {_s(M)}/><circle cx="11.5" cy="4.5" r="2.4" {_s(M)}/><path {_s(M)} d="M5.6 9.3 L9.8 6.2"/>')
add("MOD_TRIANGULATE", f'<path {_s(M)} d="M2.5 2.5 H13.5 V13.5 H2.5 Z M2.5 13.5 L13.5 2.5"/>')
add("MOD_WIREFRAME", f'<path {_s(M)} d="M2.5 2.5 H13.5 V13.5 H2.5 Z M5 5 H11 V11 H5 Z M2.5 2.5 L5 5 M13.5 2.5 L11 5 M13.5 13.5 L11 11 M2.5 13.5 L5 11"/>')
add("MOD_LATTICE", lattice(M))
add("MOD_CURVE", curve(M))
add("MOD_SHRINKWRAP", f'<circle cx="8" cy="8" r="3" fill="{M}"/><path {_s(M)} d="M2 2 L5.5 5.5 M14 2 L10.5 5.5 M14 14 L10.5 10.5 M2 14 L5.5 10.5"/>')
add("MOD_SIMPLEDEFORM", f'<path {_s(M)} d="M3 13 C3 6 13 10 13 3 M6 13.5 C6 8 14 11 14 5"/>')
add("MOD_DISPLACE", f'<path {_s(M)} d="M1.5 12 H4 L5.5 5 L7.5 10 L9 3 L11 9 L12 7 H14.5"/>')
add("MOD_WAVE MOD_OCEAN", f'<path {_s(M, 1.4)} d="M1.5 6 C3.5 3 5.5 3 7.5 6 C9.5 9 11.5 9 14.5 6 M1.5 11 C3.5 8 5.5 8 7.5 11 C9.5 14 11.5 14 14.5 11"/>')
add("MOD_ARMATURE", bone(M))
add("MOD_CLOTH", f'<path {_s(M)} d="M2 3 H14 C13 7 14 10 12 13 C9 11 6 14 3 12 C4 9 2 6 2 3 Z"/>')
add("MOD_PARTICLES MOD_PARTICLE_INSTANCE", f'<circle cx="4" cy="11" r="2" fill="{M}"/><circle cx="9" cy="6" r="1.5" fill="{M}"/>'
    f'<circle cx="12.5" cy="3" r="1" fill="{M}"/><circle cx="12" cy="10" r="1.2" fill="{M}"/>')
add("MOD_EDGESPLIT", f'<path {_s(M)} d="M2 13 L7 3 M9 3 L14 13 M2 13 H6.5 M9.5 13 H14"/>')
add("MOD_WEIGHTED_NORMAL MOD_NORMALEDIT", f'<path {_s(M)} d="M2 12 H14 M8 12 V3 M5 12 L3 6 M11 12 L13 6"/><path fill="{M}" d="M8 1.5 L9.6 4 H6.4 Z"/>')
add("MOD_CAST", f'<circle cx="8" cy="8" r="5.5" {_s(M)} stroke-dasharray="2 1.5"/><rect x="5" y="5" width="6" height="6" {_s(M)}/>')
add("MOD_HUE_SATURATION MOD_TINT", f'<circle cx="8" cy="8" r="5.6" fill="none" stroke="{M}" stroke-width="2.4"/>')
add("MOD_MASK", f'<path {_s(M)} d="M2 8 C4 4 12 4 14 8 C12 12 4 12 2 8 Z"/><circle cx="8" cy="8" r="2" fill="{M}"/>')
add("MOD_EXPLODE", f'<path {_s(M)} d="M8 6 L8 1.5 M10 7 L14 4 M10 9.5 L14.5 11 M6 9.5 L2 12 M6 7 L2 4"/><circle cx="8" cy="8" r="1.8" fill="{M}"/>')
add("MOD_FLUIDSIM MOD_FLUID", f'<path {_s(M)} d="M8 2 C8 2 3.5 7.5 3.5 10.3 A4.5 4.5 0 0 0 12.5 10.3 C12.5 7.5 8 2 8 2 Z"/>')
add("MOD_SOFT", f'<path {_s(M)} d="M3 6 C3 3 13 3 13 6 C14 9 12 13 8 13 C4 13 2 9 3 6 Z"/>')
add("MOD_DYNAMICPAINT", f'<path {_s(M)} d="M10.5 2.5 L13.5 5.5 L7 12 L4 9 Z M4 9 L2.5 13.5 L7 12"/>')
add("MOD_VERTEX_WEIGHT MOD_DATA_TRANSFER", f'<path {_s(M)} d="M3 13 L8 3 L13 13 Z"/><circle cx="8" cy="3" r="1.8" fill="{M}"/>')
add("MOD_LINEART MOD_LENGTH MOD_NOISE MOD_OFFSET MOD_OPACITY MOD_THICKNESS", f'<path {_s(M, 1.4)} d="M2 12 L6 5 L10 10 L14 3"/>')
add("MOD_MESHDEFORM MOD_WARP MOD_UVPROJECT MOD_HOOK HOOK MOD_INSTANCE MOD_BUILD MOD_MULTIRES MOD_SIMPLIFY "
    "MOD_TIME MOD_PHYSICS MOD_UVPROJECT MOD_VOLUME_DATA MOD_ENVELOPE MOD_DASH MOD_OUTLINE MOD_SUBDIVIDE",
    f'<path {_s(M)} d="M10.5 2.5 A3 3 0 0 0 9 7 L3 13 L4.5 14.5 L10.5 8.5 A3 3 0 0 0 14 6 L12 6 L10 4 Z"/>')

# ------------------------------------------------------------------ constraints (blue)
add("CON_LOCLIKE CON_LOCLIMIT", f'<path {_s(MO)} d="M8 1.5 V14.5 M1.5 8 H14.5"/><path fill="{MO}" d="M8 1 L9.6 3.6 H6.4 Z M15 8 L12.4 9.6 V6.4 Z"/>')
add("CON_ROTLIKE CON_ROTLIMIT", f'<path {_s(MO)} d="M13 8 A5 5 0 1 1 10.5 3.7"/><path fill="{MO}" d="M9.3 1.4 L13.2 3.6 L9.6 6 Z"/>')
add("CON_SIZELIKE CON_SIZELIMIT", f'<rect x="2" y="7" width="7" height="7" rx="1" {_s(MO)}/><path {_s(MO)} d="M7 9 L13.5 2.5"/>')
add("CON_TRACKTO CON_LOCKTRACK CON_DAMPTRACK", f'<circle cx="11" cy="5" r="2.6" {_s(MO)}/><path {_s(MO)} d="M2.5 13.5 L9 7"/>')
add("CON_FOLLOWPATH CON_CLAMPTO", curve(MO))
add("CON_CHILDOF CON_ARMATURE", f'<circle cx="4.5" cy="4.5" r="2.4" {_s(MO)}/><circle cx="11.5" cy="11.5" r="2.4" {_s(MO)}/><path {_s(MO)} d="M6.3 6.3 L9.7 9.7"/>')
add("CON_KINEMATIC CON_SPLINEIK", bone(MO))
add("CON_TRANSLIKE CON_TRANSFORM CON_ACTION CON_STRETCHTO CON_PIVOT CON_SHRINKWRAP CON_FLOOR CON_OBJECTSOLVER "
    "CON_CAMERASOLVER CON_FOLLOWTRACK CON_SAMEVOL CON_DISTLIMIT CON_TRANSFORM_CACHE",
    f'<path {_s(MO)} d="M6.5 9.5 L9.5 6.5 M7 4.5 L8.5 3 A2.5 2.5 0 0 1 13 7.5 L11.5 9 M9 11.5 L7.5 13 A2.5 2.5 0 0 1 3 8.5 L4.5 7"/>')

# ------------------------------------------------------------------ common buttons
add("ADD ZOOM_IN", f'<path {_s(W, 1.6)} d="M8 3 V13 M3 8 H13"/>')
add("REMOVE ZOOM_OUT", f'<path {_s(W, 1.6)} d="M3 8 H13"/>')
add("X PANEL_CLOSE CANCEL", f'<path {_s(W, 1.6)} d="M4 4 L12 12 M12 4 L4 12"/>')
add("TRIA_UP", f'<path fill="{W}" d="M8 5 L12.5 11 H3.5 Z"/>')
add("TRIA_DOWN DOWNARROW_HLT", f'<path fill="{W}" d="M8 11 L3.5 5 H12.5 Z"/>')
add("TRIA_RIGHT PLAY", f'<path fill="{W}" d="M5 3.5 L11 8 L5 12.5 Z"/>')
add("TRIA_LEFT PLAY_REVERSE", f'<path fill="{W}" d="M11 3.5 L5 8 L11 12.5 Z"/>')
add("PAUSE", f'<path fill="{W}" d="M4.5 3 H7 V13 H4.5 Z M9 3 H11.5 V13 H9 Z"/>')
add("CHECKMARK", f'<path {_s(W, 1.8)} d="M3 8.5 L6.5 12 L13 4.5"/>')
add("PRESET COLLAPSEMENU", f'<path {_s(W, 1.5)} d="M3 4 H13 M3 8 H13 M3 12 H13"/>')
add("DUPLICATE COPYDOWN", f'<rect x="2" y="4.5" width="8" height="9" rx="1" {_s()}/><path {_s()} d="M6 4.5 V2.5 H14 V11.5 H10"/>')
add("PASTEDOWN", f'<rect x="3" y="3" width="10" height="11" rx="1" {_s()}/><rect x="5.5" y="1.5" width="5" height="3" rx="1" {_s()}/>')
add("FILE_FOLDER FILEBROWSER", f'<path {_s()} d="M1.5 4 H6 L7.5 5.5 H14.5 V13 H1.5 Z"/>')
add("FILE_NEW FILE_BLANK", f'<path {_s()} d="M3.5 1.5 H9.5 L12.5 4.5 V14.5 H3.5 Z M9.5 1.5 V4.5 H12.5"/>')
add("FILE_TICK", f'<path {_s()} d="M3.5 1.5 H9.5 L12.5 4.5 V14.5 H3.5 Z"/><path {_s(W, 1.5)} d="M5.5 9 L7.5 11 L10.5 7"/>')
add("FILE_REFRESH", f'<path {_s()} d="M13 8 A5 5 0 1 1 10.5 3.7"/><path fill="{W}" d="M9.3 1.4 L13.2 3.6 L9.6 6 Z"/>')
add("LOCKED", f'<rect x="3.5" y="7" width="9" height="7" rx="1" {_s()}/><path {_s()} d="M5.5 7 V5 A2.5 2.5 0 0 1 10.5 5 V7"/>')
add("UNLOCKED", f'<rect x="3.5" y="7" width="9" height="7" rx="1" {_s()}/><path {_s()} d="M5.5 7 V5 A2.5 2.5 0 0 1 10.5 4"/>')
add("DECORATE_ANIMATE DECORATE_KEYFRAME KEY_HLT KEYFRAME_HLT", f'<path fill="#e8a33d" stroke="{W}" stroke-width="1" d="M8 2.5 L13.5 8 L8 13.5 L2.5 8 Z"/>')
add("DECORATE KEY_DEHLT KEYFRAME DECORATE_UNLOCKED", f'<path {_s()} d="M8 3 L13 8 L8 13 L3 8 Z"/>')
add("DECORATE_DRIVER DRIVER", f'<path {_s("#c38cff")} d="M3 13 C6 13 6 3 9 3 C11 3 12 5 13 7"/>')
add("KEYINGSET", f'<path {_s()} d="M6 3 L10 7 L6 11 L2 7 Z M10 5 L14 9 L10 13"/>')
add("EYEDROPPER", f'<path {_s()} d="M11.5 2 L14 4.5 L12 6.5 L9.5 4 Z M10.5 5.5 L4 12 L3 14 L5 13 L11.5 6.5"/>')
add("TRASH", f'<path {_s()} d="M3 4.5 H13 M6 4.5 V2.5 H10 V4.5 M4.5 4.5 L5.5 14 H10.5 L11.5 4.5 M7 7 V12 M9 7 V12"/>')
add("FAKE_USER_OFF", f'<path {_s()} d="M8 13.5 C3 10 1.5 7.5 2.5 5 C3.5 2.5 6.5 2.5 8 5 C9.5 2.5 12.5 2.5 13.5 5 C14.5 7.5 13 10 8 13.5 Z"/>')
add("FAKE_USER_ON", f'<path fill="#5aa0ff" d="M8 13.5 C3 10 1.5 7.5 2.5 5 C3.5 2.5 6.5 2.5 8 5 C9.5 2.5 12.5 2.5 13.5 5 C14.5 7.5 13 10 8 13.5 Z"/>')
add("LINKED LINK_BLEND", f'<path {_s()} d="M6.5 9.5 L9.5 6.5 M7 4.5 L8.5 3 A2.5 2.5 0 0 1 13 7.5 L11.5 9 M9 11.5 L7.5 13 A2.5 2.5 0 0 1 3 8.5 L4.5 7"/>')
add("ERROR", f'<path fill="#e8a33d" d="M8 1.5 L15 14 H1 Z"/><path stroke="#1a1a1a" stroke-width="1.6" stroke-linecap="round" d="M8 6 V9.5 M8 11.8 V11.9"/>')
add("INFO", f'<circle cx="8" cy="8" r="6" fill="#5aa0ff"/><path stroke="#ffffff" stroke-width="1.6" stroke-linecap="round" d="M8 7.5 V11.5 M8 4.8 V4.9"/>')
add("QUESTION HELP", f'<circle cx="8" cy="8" r="6" {_s()}/><path {_s(W, 1.4)} d="M6 6.2 A2 2 0 1 1 8.5 8 C8 8.3 8 8.7 8 9.5 M8 11.8 V11.9"/>')
add("SETTINGS PREFERENCES", f'<circle cx="8" cy="8" r="2.2" {_s()}/><path {_s()} d="M8 1.5 V3.5 M8 12.5 V14.5 M1.5 8 H3.5 M12.5 8 H14.5 M3.4 3.4 '
    f'L4.8 4.8 M11.2 11.2 L12.6 12.6 M12.6 3.4 L11.2 4.8 M4.8 11.2 L3.4 12.6"/><circle cx="8" cy="8" r="4.6" {_s()}/>')
add("HIDE_OFF RESTRICT_VIEW_OFF", f'<path {_s()} d="M1.5 8 C3.5 4.5 5.7 3.5 8 3.5 C10.3 3.5 12.5 4.5 14.5 8 C12.5 11.5 10.3 12.5 8 12.5 '
    f'C5.7 12.5 3.5 11.5 1.5 8 Z"/><circle cx="8" cy="8" r="2.2" fill="{W}"/>')
add("HIDE_ON RESTRICT_VIEW_ON", f'<path {_s(W)} opacity=".55" d="M1.5 8 C3.5 11 5.7 12 8 12 C10.3 12 12.5 11 14.5 8 M4 10.5 L3 12.5 M8 12 V14 M12 10.5 L13 12.5"/>')
add("RESTRICT_SELECT_OFF", f'<path fill="{W}" d="M4 2 L12 9 L8.3 9.4 L10.5 13.6 L9 14.4 L6.8 10.2 L4 12.6 Z"/>')
add("RESTRICT_SELECT_ON", f'<path {_s(W)} opacity=".55" d="M4 2 L12 9 L8.3 9.4 L10.5 13.6 L9 14.4 L6.8 10.2 L4 12.6 Z"/>')
add("RESTRICT_RENDER_OFF", f'<rect x="2" y="4" width="10" height="8" rx="1" {_s()}/><path {_s()} d="M12 7 L14.5 5.5 V10.5 L12 9"/>')
add("RESTRICT_RENDER_ON", f'<rect x="2" y="4" width="10" height="8" rx="1" {_s()} opacity=".5"/><path {_s(W)} d="M2 14 L14 2" opacity=".7"/>')
add("RESTRICT_VIEW_OFF_ALT VIS_SEL_11 MONITOR WINDOW", f'<rect x="1.5" y="2.5" width="13" height="9" rx="1" {_s()}/><path {_s()} d="M6 14 H10 M8 11.5 V14"/>')
add("CHECKBOX_HLT", f'<rect x="2.5" y="2.5" width="11" height="11" rx="2" fill="#4772b3"/><path {_s("#ffffff", 1.6)} d="M5 8 L7.2 10.2 L11 5.8"/>')
add("CHECKBOX_DEHLT", f'<rect x="2.5" y="2.5" width="11" height="11" rx="2" {_s()}/>')
add("SORTALPHA", f'<path {_s()} d="M2 13 L4.5 4 L7 13 M3 10 H6 M10 4 H14 L10 13 H14"/>')
add("SORTTIME TIME", f'<circle cx="8" cy="8" r="6" {_s()}/><path {_s()} d="M8 4.5 V8 L10.5 10"/>')
add("VIEWZOOM", f'<circle cx="6.8" cy="6.8" r="4.6" {_s()}/><path d="M10.3 10.3 L14.4 14.4" stroke="{W}" stroke-width="2.2" stroke-linecap="round"/>')
add("VIEW_PAN HAND", f'<path {_s()} d="M5 14 C3.2 12 2.6 10.4 3.2 9.6 C3.8 8.9 4.8 9.4 5.4 10.4 V3.6 A0.9 0.9 0 0 1 7.2 3.6 V8 '
    f'V2.6 A0.9 0.9 0 0 1 9 2.6 V8 V3.4 A0.9 0.9 0 0 1 10.8 3.4 V8.4 V5 A0.9 0.9 0 0 1 12.6 5 V10 C12.6 12.4 11.6 14 9.6 14 Z"/>')
add("VIEW_CAMERA OUTLINER_DATA_CAMERA CAMERA_DATA", camera(DA))
add("OUTLINER_OB_CAMERA", camera(OB))
add("SNAP_ON SNAP_OFF", f'<path {_s()} d="M4 2.5 V8.5 A4 4 0 0 0 12 8.5 V2.5 M9.6 2.5 V8.5 A1.6 1.6 0 0 1 6.4 8.5 V2.5"/>')
add("PROP_ON PROP_OFF PROP_CON PROP_PROJECTED", f'<circle cx="8" cy="8" r="6" {_s()} opacity=".45"/><circle cx="8" cy="8" r="3.8" {_s()}/>'
    f'<circle cx="8" cy="8" r="1.7" fill="{W}"/>')
add("PIVOT_MEDIAN PIVOT_BOUNDBOX PIVOT_CURSOR PIVOT_INDIVIDUAL PIVOT_ACTIVE", f'<circle cx="8" cy="8" r="5" {_s()}/>'
    f'<circle cx="8" cy="8" r="1.6" fill="#e8a33d"/>')
add("ORIENTATION_GLOBAL ORIENTATION_LOCAL ORIENTATION_NORMAL ORIENTATION_GIMBAL ORIENTATION_VIEW ORIENTATION_CURSOR "
    "ORIENTATION_PARENT OBJECT_ORIGIN", f'<circle cx="8" cy="8" r="5.6" {_s()}/><ellipse cx="8" cy="8" rx="2.4" ry="5.6" {_s()}/>'
    f'<path {_s()} d="M2.4 8 H13.6"/>')
add("XRAY", f'<rect x="2" y="2" width="9" height="9" rx="1" {_s()}/><rect x="5" y="5" width="9" height="9" rx="1" fill="{W}" fill-opacity=".35" stroke="{W}" stroke-width="1.2"/>')
add("OVERLAY", f'<circle cx="6" cy="8" r="4.2" {_s()}/><circle cx="10" cy="8" r="4.2" {_s()}/>')
add("SHADING_WIRE", f'<circle cx="8" cy="8" r="5.8" {_s()}/><ellipse cx="8" cy="8" rx="5.8" ry="2.2" {_s()}/><ellipse cx="8" cy="8" rx="2.2" ry="5.8" {_s()}/>')
add("SHADING_SOLID", f'<circle cx="8" cy="8" r="5.8" fill="{W}"/>')
add("SHADING_TEXTURE", f'<circle cx="8" cy="8" r="5.8" {_s()}/><path fill="{W}" d="M8 2.2 A5.8 5.8 0 0 1 8 13.8 Z"/>')
add("CURSOR PIVOT_CURSOR", f'<circle cx="8" cy="8" r="4.2" fill="none" stroke="#e05050" stroke-width="1.4" stroke-dasharray="2.2 2.2"/>'
    f'<path {_s()} d="M8 1.5 V4.5 M8 11.5 V14.5 M1.5 8 H4.5 M11.5 8 H14.5"/>')
add("EXPORT", f'<path {_s()} d="M8 10 V2 M5 5 L8 2 L11 5 M3 9 V14 H13 V9"/>')
add("IMPORT", f'<path {_s()} d="M8 2 V10 M5 7 L8 10 L11 7 M3 9 V14 H13 V9"/>')
add("APPEND_BLEND", f'<path {_s()} d="M8 2 V10 M5 7 L8 10 L11 7 M3 9 V14 H13 V9"/>')
add("RECOVER_LAST", f'<path {_s()} d="M3 8 A5 5 0 1 0 5.5 3.7"/><path fill="{W}" d="M6.7 1.4 L2.8 3.6 L6.4 6 Z"/>')
add("SCRIPT TEXT CONSOLE", f'<rect x="2" y="2.5" width="12" height="11" rx="1" {_s()}/><path {_s()} d="M4.5 6 L6.5 8 L4.5 10 M8 10.5 H11.5"/>')
add("WORKSPACE", f'<rect x="1.5" y="2.5" width="13" height="11" rx="1" {_s()}/><path {_s()} d="M1.5 5.5 H14.5 M6 5.5 V13.5"/>')
add("SNAP_FACE SNAP_VERTEX SNAP_EDGE SNAP_INCREMENT SNAP_GRID SNAP_VOLUME SNAP_MIDPOINT SNAP_PERPENDICULAR",
    f'<path {_s()} d="M3 13 V5 L11 3 L13 11 Z" opacity=".6"/><circle cx="11" cy="3" r="2" fill="#e8a33d"/>')
add("ANIM ANIM_DATA ACTION", f'<path {_s()} d="M2 12 L6 5 L10 10 L14 3"/><path fill="#e8a33d" d="M6 3 L8 5 L6 7 L4 5 Z"/>')
add("RENDER_RESULT_ALT RENDER RENDERLAYERS_ALT", f'<rect x="2" y="2.5" width="12" height="11" rx="1" {_s()}/><path {_s()} d="M2 9 L6 6 L9 9 L11 7.5 L14 10"/>')
add("OBJECT_HIDDEN", f'<path {_s()} d="M8 2 L13.5 5 V11 L8 14 L2.5 11 V5 Z" opacity=".5"/>')
add("PLUS", _I["ADD"])
add("OUTLINER_OB_GROUP_INSTANCE OUTLINER_OB_COLLECTION_INSTANCE", collection(OB))

# the rest of Blender 5.2's icon names (keys, colour sets, sockets, curves, editors, file browser, …)
try:
    from .blicons_more import extend as _extend
except ImportError:          # loaded outside the package (preview scripts)
    from blicons_more import extend as _extend
_extend(add, _I, _s, W, OB, DA, MO, LI, RD)

# ------------------------------------------------------------------ properties tabs (keys used by properties.py)
TAB_ICONS = {"tool": "TOOL_SETTINGS", "render": "SCENE", "output": "OUTPUT", "view_layer": "RENDER_RESULT",
             "scene": "SCENE_DATA", "world": "WORLD", "collection": "OUTLINER_COLLECTION", "object": "OBJECT_DATA",
             "modifier": "MODIFIER", "particle": "PARTICLES", "physics": "PHYSICS", "constraint": "CONSTRAINT",
             "data": "MESH_DATA", "bone": "BONE_DATA", "material": "MATERIAL", "texture": "TEXTURE"}
# object type → Properties "Data" tab icon
DATA_ICONS = {"MESH": "MESH_DATA", "CURVE": "CURVE_DATA", "SURFACE": "SURFACE_DATA", "META": "META_DATA",
              "FONT": "FONT_DATA", "ARMATURE": "ARMATURE_DATA", "LATTICE": "LATTICE_DATA", "EMPTY": "EMPTY_DATA",
              "CAMERA": "CAMERA_DATA", "LIGHT": "LIGHT_DATA", "SPEAKER": "SPEAKER_DATA",
              "LIGHT_PROBE": "LIGHTPROBE_DATA", "GREASEPENCIL": "GREASEPENCIL_DATA", "CURVES": "CURVES_DATA",
              "POINTCLOUD": "POINTCLOUD_DATA", "VOLUME": "VOLUME_DATA"}


def names():
    return sorted(_I)


def has(name):
    return bool(name) and name in _I and QtSvg is not None


def svg(name):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">{_I[name]}</svg>'


_pm_cache = {}
_icon_cache = {}


def _render(name, px):
    key = (name, px)
    img = _pm_cache.get(key)
    if img is None:
        img = QtGui.QImage(px, px, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.transparent)
        r = QtSvg.QSvgRenderer(QtCore.QByteArray(svg(name).encode()))
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r.render(p)
        p.end()
        _pm_cache[key] = img
    return img


def icon(name):
    """QIcon for a Blender icon name (null QIcon when Qt Shell has no drawing for it)."""
    if not has(name):
        return QtGui.QIcon()
    ic = _icon_cache.get(name)
    if ic is None:
        ic = QtGui.QIcon()
        for px in (16, 24, 32, 48):
            ic.addPixmap(QtGui.QPixmap.fromImage(_render(name, px)))
        _icon_cache[name] = ic
    return ic

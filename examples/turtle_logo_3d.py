"""Qt Shell logo (the turtle) as a coloured 3D model.

Run in Blender (Qt Shell: Text editor → Run Script, or Blender's Scripting workspace). It builds everything
in a new collection "Qt Shell Turtle": the app-icon base plate, the shell (dome with 7 raised hexagon
tiles), the orange cube in the middle, head with eyes and four flippers – with materials in the logo's
colours (docs/logo/qt_shell_logo.svg). Also adds a camera and lights when the scene has none.
Running it again replaces the collection.
"""
import math

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

S = 0.01                     # SVG pixel → metre
CX, CY = 256.0, 276.0        # SVG point that becomes the origin (centre of the shell)
COLL = "Qt Shell Turtle"

COLORS = {
    "Base": "#1b2723", "Shell": "#16201d", "Skin": "#9be08f", "Eye": "#16191f", "Center": "#2a3442",
    "Teal": "#2fbf9f", "Blue": "#3a8cff", "Purple": "#7b5cff",
    "CubeTop": "#ffc35a", "CubeLeft": "#f28a2e", "CubeRight": "#c9601d",
}
# hexagon tiles of the shell: SVG centre → colour
HEXES = [((256.0, 276.0), "Center"), ((357.5, 276.0), "Teal"), ((306.8, 363.9), "Blue"),
         ((205.3, 363.9), "Purple"), ((154.5, 276.0), "Teal"), ((205.2, 188.1), "Blue"),
         ((306.8, 188.1), "Purple")]
HEX_R = 55.7                 # circumradius in SVG pixels

# the shell: an ellipsoid (SVG rx 170, ry 168) flattened in Z
SHELL_A, SHELL_B, SHELL_C, SHELL_Z = 170 * S, 168 * S, 0.62, 0.12


def svg_xy(x, y):
    return Vector(((x - CX) * S, (CY - y) * S))


def lin(hexstr):
    """sRGB hex → linear RGBA (Blender's colour values)."""
    h = hexstr.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return (*out, 1.0)


def material(name, rough=0.45, emit=0.0):
    mname = f"QtTurtle {name}"
    m = bpy.data.materials.get(mname) or bpy.data.materials.new(mname)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    col = lin(COLORS[name])
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = col
        bsdf.inputs["Roughness"].default_value = rough
        if emit and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = col
            bsdf.inputs["Emission Strength"].default_value = emit
    m.diffuse_color = col             # solid view shows the colour too
    return m


def new_object(name, bm, coll, mats, smooth=False):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def add_bevel(ob, width, segments=3):
    mod = ob.modifiers.new("Bevel", "BEVEL")
    mod.width = width
    mod.segments = segments
    mod.limit_method = "ANGLE"
    return mod


def ellipsoid(name, coll, mat, center, radii, rot_z=0.0, segments=48, rings=24):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=1.0)
    bmesh.ops.scale(bm, vec=Vector(radii), verts=bm.verts)
    ob = new_object(name, bm, coll, [mat], smooth=True)
    ob.location = center
    ob.rotation_euler = Euler((0, 0, rot_z))
    return ob


def shell_point(x, y):
    """Point on the shell's top surface above (x, y) and its normal."""
    u = min((x / SHELL_A) ** 2 + (y / SHELL_B) ** 2, 0.98)
    z = SHELL_Z + SHELL_C * math.sqrt(1 - u)
    n = Vector((x / SHELL_A ** 2, y / SHELL_B ** 2, (z - SHELL_Z) / SHELL_C ** 2)).normalized()
    return Vector((x, y, z)), n


def hex_tile(name, coll, mat, xy, radius, height):
    bm = bmesh.new()
    verts = []
    for k in range(6):                       # pointy top like the logo
        a = math.radians(90 + 60 * k)
        verts.append(bm.verts.new((radius * math.cos(a), radius * math.sin(a), 0.0)))
    face = bm.faces.new(verts)
    ext = bmesh.ops.extrude_face_region(bm, geom=[face])
    top = [v for v in ext["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, 0, height), verts=top)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = new_object(name, bm, coll, [mat])
    p, n = shell_point(xy.x, xy.y)
    rot = Vector((0, 0, 1)).rotation_difference(n)
    ob.matrix_world = Matrix.Translation(p - n * (height * 0.45)) @ rot.to_matrix().to_4x4()
    add_bevel(ob, height * 0.25)
    return ob, p, n


def orange_cube(coll, center, normal, size):
    """The logo's isometric cube: light top, orange left, dark orange right."""
    mats = [material("CubeTop", 0.35), material("CubeLeft", 0.4), material("CubeRight", 0.4)]
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    for f in bm.faces:
        n = f.normal
        f.material_index = 0 if n.z > 0.5 else (1 if n.x - n.y < 0 else 2)
    ob = new_object("Turtle Cube", bm, coll, mats)
    rot = Vector((0, 0, 1)).rotation_difference(normal).to_matrix().to_4x4()
    ob.matrix_world = (Matrix.Translation(center + normal * (size * 0.5)) @ rot
                       @ Matrix.Rotation(math.radians(45), 4, "Z"))
    add_bevel(ob, size * 0.08)
    return ob


def build():
    old = bpy.data.collections.get(COLL)
    if old is not None:
        for ob in list(old.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.collections.remove(old)
    coll = bpy.data.collections.new(COLL)
    bpy.context.scene.collection.children.link(coll)

    # base plate: the rounded app-icon square (480 px, corner radius 108 px)
    bm = bmesh.new()
    half, r, seg = 240 * S, 108 * S, 12
    pts = []
    for cx, cy, a0 in ((half - r, half - r, 0), (-half + r, half - r, 90), (-half + r, -half + r, 180),
                       (half - r, -half + r, 270)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append(bm.verts.new((cx + r * math.cos(a), cy + r * math.sin(a), -0.16)))
    face = bm.faces.new(pts)
    ext = bmesh.ops.extrude_face_region(bm, geom=[face])
    bmesh.ops.translate(bm, vec=(0, 0, 0.16),
                        verts=[v for v in ext["geom"] if isinstance(v, bmesh.types.BMVert)])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    base = new_object("Turtle Base", bm, coll, [material("Base", 0.6)])
    c = svg_xy(256, 256)
    base.location = (c.x, c.y, 0.0)
    add_bevel(base, 0.03)

    skin = material("Skin", 0.5)
    # head + eyes
    head = svg_xy(256, 86)
    ellipsoid("Turtle Head", coll, skin, (head.x, head.y, 0.32), (40 * S, 46 * S, 0.3))
    eye = material("Eye", 0.2)
    for ex in (240, 272):
        p = svg_xy(ex, 74)
        ellipsoid("Turtle Eye", coll, eye, (p.x, p.y, 0.58), (7 * S, 7 * S, 0.05), segments=24, rings=12)
    # flippers (SVG ellipses with their rotation)
    for (x, y, rx, ry, ang) in ((118, 168, 42, 26, -35), (394, 168, 42, 26, 35),
                                (128, 400, 38, 24, 35), (384, 400, 38, 24, -35)):
        p = svg_xy(x, y)
        ellipsoid("Turtle Flipper", coll, skin, (p.x, p.y, 0.14), (rx * S, ry * S, 0.1),
                  rot_z=math.radians(-ang))
    # shell + tiles
    ellipsoid("Turtle Shell", coll, material("Shell", 0.55), (0, 0, SHELL_Z), (SHELL_A, SHELL_B, SHELL_C),
              segments=64, rings=32)
    center_top = None
    for (x, y), col in HEXES:
        xy = svg_xy(x, y)
        _ob, p, n = hex_tile(f"Turtle Hex {col}", coll, material(col, 0.35), xy, HEX_R * S * 0.93, 0.12)
        if col == "Center":
            center_top = (p + n * (0.12 * 0.55), n)
    orange_cube(coll, center_top[0], center_top[1], 0.36)
    return coll


def stage(coll):
    """Camera and lights for a nice view – only when the scene has no camera yet."""
    sc = bpy.context.scene
    if sc.camera is None:
        cam = bpy.data.objects.new("Turtle Camera", bpy.data.cameras.new("Turtle Camera"))
        coll.objects.link(cam)
        cam.location = (0, -7.2, 6.2)
        cam.rotation_euler = Euler((math.radians(48), 0, 0))
        cam.data.lens = 50
        sc.camera = cam
    if not any(o.type == "LIGHT" for o in sc.objects):
        sun = bpy.data.objects.new("Turtle Sun", bpy.data.lights.new("Turtle Sun", "SUN"))
        sun.data.energy = 3.0
        sun.rotation_euler = Euler((math.radians(40), math.radians(15), math.radians(30)))
        coll.objects.link(sun)
        fill = bpy.data.objects.new("Turtle Fill", bpy.data.lights.new("Turtle Fill", "AREA"))
        fill.data.energy = 400
        fill.data.size = 4
        fill.location = (-3, -3, 4)
        fill.rotation_euler = Euler((math.radians(45), 0, math.radians(-45)))
        coll.objects.link(fill)


if __name__ == "__main__":
    c = build()
    stage(c)
    print(f"Qt Shell turtle: {len(c.objects)} objects in collection '{COLL}'")

"""Built-in shelves (like Maya's Polygons / Poly Modeling / Rigging / Animation / Rendering shelves).

Each shelf is added once to the user's shelves.json (shelf.load → add_builtin_shelves); a built-in shelf
the user deletes or renames is not added again (names remembered in "builtin_added"). Buttons use
Blender icons ("bl:NAME", drawn by blicons.py), a short label, a tooltip and plain Python – the user can
edit them like any other shelf button. Shelf code runs in a 3D view context (shelf.run_button).
"""

_EDIT = ("import bpy\n"
         "if bpy.context.mode != 'EDIT_MESH':\n"
         "    bpy.ops.object.mode_set(mode='EDIT')\n")
_OBJ = ("import bpy\n"
        "if bpy.context.mode != 'OBJECT':\n"
        "    bpy.ops.object.mode_set(mode='OBJECT')\n")
_QS = "import qt_shell.api as qs\n"


def _b(label, icon, tooltip, command):
    return {"label": label, "icon": f"bl:{icon}", "tooltip": tooltip, "command": command}


def _prim(label, icon, op, what, extra=""):
    return _b(label, icon, f"Add {what} at the 3D cursor (Edit Mode: into the edited mesh)",
              f"import bpy\nbpy.ops.mesh.{op}({extra})\n")


def _edit(label, icon, tooltip, body):
    return _b(label, icon, tooltip + " (switches to Edit Mode)", _EDIT + body)


def _mod(label, icon, mtype, tooltip, setup=""):
    return _b(label, icon, tooltip,
              "import bpy\nob = bpy.context.active_object\n"
              f"m = ob.modifiers.new(\"{label}\", \"{mtype}\")\n{setup}")


SHELVES = [
    {"name": "Polygons", "buttons": [
        _prim("Cube", "MESH_CUBE", "primitive_cube_add", "a cube"),
        _prim("Sphere", "MESH_UVSPHERE", "primitive_uv_sphere_add", "a UV sphere"),
        _prim("Ico Sphere", "MESH_ICOSPHERE", "primitive_ico_sphere_add", "an ico sphere"),
        _prim("Cylinder", "MESH_CYLINDER", "primitive_cylinder_add", "a cylinder"),
        _prim("Cone", "MESH_CONE", "primitive_cone_add", "a cone"),
        _prim("Torus", "MESH_TORUS", "primitive_torus_add", "a torus"),
        _prim("Plane", "MESH_PLANE", "primitive_plane_add", "a plane"),
        _prim("Circle", "MESH_CIRCLE", "primitive_circle_add", "a circle (vertices only)"),
        _prim("Grid", "MESH_GRID", "primitive_grid_add", "a grid", "x_subdivisions=10, y_subdivisions=10"),
        _prim("Monkey", "MESH_MONKEY", "primitive_monkey_add", "Suzanne the monkey"),
    ]},
    {"name": "Modeling", "buttons": [
        _edit("Extrude", "FACESEL", "Extrude the selection and move it with the mouse",
              "bpy.ops.mesh.extrude_region_move()\n" + _QS + "qs.viewport().start_modal('G')\n"),
        _edit("Inset", "FACESEL", "Inset the selected faces – adjust Thickness in Adjust Last Operation",
              "bpy.ops.mesh.inset(thickness=0.1)\n"),
        _edit("Bevel", "MOD_BEVEL", "Bevel the selected edges – adjust Width / Segments in Adjust Last Operation",
              "bpy.ops.mesh.bevel(offset=0.1, segments=2)\n"),
        _edit("Subdivide", "MOD_SUBSURF", "Subdivide the selected edges / faces once",
              "bpy.ops.mesh.subdivide(number_cuts=1)\n"),
        _edit("Bridge", "EDGESEL", "Bridge two selected edge loops", "bpy.ops.mesh.bridge_edge_loops()\n"),
        _edit("Fill", "FACESEL", "Make an edge / face from the selected vertices (F)",
              "bpy.ops.mesh.edge_face_add()\n"),
        _edit("Merge", "AUTOMERGE_OFF", "Merge the selected vertices at their centre",
              "bpy.ops.mesh.merge(type='CENTER')\n"),
        _edit("Weld", "AUTOMERGE_ON", "Merge vertices closer than 0.0001 (Merge by Distance)",
              "bpy.ops.mesh.remove_doubles(threshold=0.0001)\n"),
        _edit("Dissolve", "VERTEXSEL", "Dissolve the selected vertices / edges / faces (keeps the surface)",
              "bpy.ops.mesh.dissolve_mode()\n"),
        _edit("Separate", "MOD_EXPLODE", "Move the selected faces into a new object",
              "bpy.ops.mesh.separate(type='SELECTED')\n"),
        _b("Combine", "AUTOMERGE_ON", "Join the selected objects into the active one (Object Mode)",
           _OBJ + "bpy.ops.object.join()\n"),
        _edit("Triangulate", "MOD_TRIANGULATE", "Split the selected faces into triangles",
              "bpy.ops.mesh.quads_convert_to_tris()\n"),
        _edit("Quadrangulate", "MESH_GRID", "Join the selected triangles into quads",
              "bpy.ops.mesh.tris_convert_to_quads()\n"),
        _edit("Normals", "NORMALS_FACE", "Recalculate the normals so they point outside",
              "bpy.ops.mesh.normals_make_consistent(inside=False)\n"),
        _edit("Flip", "NORMALS_FACE", "Flip the normals of the selected faces", "bpy.ops.mesh.flip_normals()\n"),
        _b("Smooth", "SHADING_SOLID", "Shade smooth (the selected faces in Edit Mode, else the selected objects)",
           "import bpy\nif bpy.context.mode == 'EDIT_MESH':\n    bpy.ops.mesh.faces_shade_smooth()\n"
           "else:\n    bpy.ops.object.shade_smooth()\n"),
        _b("Flat", "SHADING_WIRE", "Shade flat (the selected faces in Edit Mode, else the selected objects)",
           "import bpy\nif bpy.context.mode == 'EDIT_MESH':\n    bpy.ops.mesh.faces_shade_flat()\n"
           "else:\n    bpy.ops.object.shade_flat()\n"),
    ]},
    {"name": "Modifiers", "buttons": [
        _mod("Mirror", "MOD_MIRROR", "MIRROR", "Add a Mirror modifier (X axis, clipping on)",
             "m.use_clip = True\n"),
        _mod("Subdivision", "MOD_SUBSURF", "SUBSURF", "Add a Subdivision Surface modifier (level 2)",
             "m.levels = 2\nm.render_levels = 2\n"),
        _mod("Solidify", "MOD_SOLIDIFY", "SOLIDIFY", "Add a Solidify modifier (thickness 0.05)",
             "m.thickness = 0.05\n"),
        _mod("Bevel", "MOD_BEVEL", "BEVEL", "Add a Bevel modifier (width 0.02, 2 segments)",
             "m.width = 0.02\nm.segments = 2\n"),
        _mod("Array", "MOD_ARRAY", "ARRAY", "Add an Array modifier (3 copies along X)", "m.count = 3\n"),
        _mod("Boolean", "MOD_BOOLEAN", "BOOLEAN", "Add a Boolean modifier – the other selected object cuts",
             "cut = next((o for o in bpy.context.selected_objects if o != ob), None)\n"
             "if cut is not None:\n    m.object = cut\n    cut.display_type = 'WIRE'\n"),
        _mod("Weld", "AUTOMERGE_ON", "WELD", "Add a Weld modifier (merge by distance, non-destructive)"),
        _mod("Displace", "MOD_DISPLACE", "DISPLACE", "Add a Displace modifier"),
        _b("Apply All", "CHECKMARK", "Apply all modifiers of the selected objects (Object Mode)",
           _OBJ + "bpy.ops.object.convert(target='MESH')\n"),
    ]},
    {"name": "UV", "buttons": [
        _b("UV Editor", "UV", "Show the UV editor", _QS + "w = qs.main_window()\n"
           "w.docks['uv_editor'].show()\nw.docks['uv_editor'].raise_()\n"),
        _b("Smart UV", "UV", "Smart UV Project of the selected faces (all faces when none is selected)",
           _QS + "qs.uv_editor().mesh_tool('uv.smart_project')\n"),
        _b("Unwrap", "UV", "Unwrap along the seams (method from the UV Toolkit)", _QS + "qs.uv_editor().unwrap()\n"),
        _b("Cube Proj.", "MESH_CUBE", "Cube projection of the selected faces",
           _QS + "qs.uv_editor().mesh_tool('uv.cube_project')\n"),
        _b("Cyl. Proj.", "MESH_CYLINDER", "Cylinder projection of the selected faces",
           _QS + "qs.uv_editor().mesh_tool('uv.cylinder_project')\n"),
        _b("Sphere Proj.", "MESH_UVSPHERE", "Sphere projection of the selected faces",
           _QS + "qs.uv_editor().mesh_tool('uv.sphere_project')\n"),
        _edit("Mark Seam", "EDGESEL", "Mark the selected edges as UV seams", "bpy.ops.mesh.mark_seam(clear=False)\n"),
        _edit("Clear Seam", "EDGESEL", "Clear the UV seams of the selected edges",
              "bpy.ops.mesh.mark_seam(clear=True)\n"),
        _b("Layout", "UV", "Pack the UV shells into 0–1 (margin / rotate from the UV Toolkit)",
           _QS + "qs.uv_editor().layout_shells()\n"),
        _b("Checker", "TEXTURE", "Checker map on / off (UV editor and the mesh in the 3D view)",
           _QS + "from qt_shell import uv_editor\n"
                 "qs.uv_editor().set_display('checker', not uv_editor.setting('checker', False))\n"),
    ]},
    {"name": "Rigging", "buttons": [
        _b("Armature", "ARMATURE_DATA", "Add an armature with one bone at the 3D cursor",
           _OBJ + "bpy.ops.object.armature_add()\n"),
        _b("Empty", "EMPTY_AXIS", "Add an empty (plain axes) at the 3D cursor",
           _OBJ + "bpy.ops.object.empty_add(type='PLAIN_AXES')\n"),
        _b("Auto Weights", "MOD_ARMATURE", "Parent the selected meshes to the active armature with automatic "
           "weights", _OBJ + "bpy.ops.object.parent_set(type='ARMATURE_AUTO')\n"),
        _b("Empty Groups", "GROUP_VERTEX", "Parent the selected meshes to the active armature with empty "
           "vertex groups", _OBJ + "bpy.ops.object.parent_set(type='ARMATURE_NAME')\n"),
        _b("Parent", "LINKED", "Parent the selected objects to the active one (keep transform)",
           _OBJ + "bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)\n"),
        _b("Unparent", "UNLINKED", "Clear the parent of the selected objects (keep transform)",
           _OBJ + "bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')\n"),
        _b("Pose Mode", "POSE_HLT", "Pose Mode on / off for the active armature",
           "import bpy\nbpy.ops.object.posemode_toggle()\n"),
        _b("Weight Paint", "WPAINT_HLT", "Weight Paint Mode for the active mesh",
           "import bpy\nbpy.ops.object.mode_set(mode='WEIGHT_PAINT')\n"),
        _b("Rest Pose", "ARMATURE_DATA", "Clear location / rotation / scale of the selected bones (Pose Mode)",
           "import bpy\nif bpy.context.mode == 'POSE':\n    bpy.ops.pose.transforms_clear()\n"),
    ]},
    {"name": "Animation", "buttons": [
        _b("Key All", "KEY_HLT", "Insert keys on location, rotation and scale of the selection",
           "from qt_shell import keying\nkeying.insert()\n"),
        _b("Key Loc", "KEY_HLT", "Insert a location key", "from qt_shell import keying\nkeying.insert(('location',))\n"),
        _b("Key Rot", "KEY_HLT", "Insert a rotation key", "from qt_shell import keying\nkeying.insert(('rotation',))\n"),
        _b("Key Scale", "KEY_HLT", "Insert a scale key", "from qt_shell import keying\nkeying.insert(('scale',))\n"),
        _b("Delete Key", "KEY_DEHLT", "Delete the keys of the selection on the current frame",
           "from qt_shell import keying\nkeying.delete()\n"),
        _b("Prev Key", "PREV_KEYFRAME", "Jump to the previous keyframe",
           "import bpy\nbpy.ops.screen.keyframe_jump(next=False)\n"),
        _b("Play", "PLAY", "Play / stop the animation", _QS + "qs.timeline().toggle_play()\n"),
        _b("Next Key", "NEXT_KEYFRAME", "Jump to the next keyframe",
           "import bpy\nbpy.ops.screen.keyframe_jump(next=True)\n"),
        _b("Graph Editor", "GRAPH", "Show the Graph editor", _QS + "w = qs.main_window()\n"
           "w.docks['graph_editor'].show()\nw.docks['graph_editor'].raise_()\n"),
    ]},
    {"name": "Rendering", "buttons": [
        _b("Render", "RENDER_STILL", "Render the current frame (F12)", _QS + "qs.run_op('render.render')\n"),
        _b("Animation", "RENDER_ANIMATION", "Render the animation (Ctrl+F12)",
           _QS + "qs.run_op('render.render', animation=True)\n"),
        _b("Render View", "IMAGE_DATA", "Show the Render View window (F11)", _QS + "qs.run_op('render.view_show')\n"),
        _b("Camera", "OUTLINER_OB_CAMERA", "Add a camera at the 3D cursor and make it the scene camera",
           _OBJ + "bpy.ops.object.camera_add()\nbpy.context.scene.camera = bpy.context.active_object\n"),
        _b("Sun", "LIGHT_SUN", "Add a sun light", _OBJ + "bpy.ops.object.light_add(type='SUN')\n"),
        _b("Point", "LIGHT_POINT", "Add a point light", _OBJ + "bpy.ops.object.light_add(type='POINT')\n"),
        _b("Area", "LIGHT_AREA", "Add an area light", _OBJ + "bpy.ops.object.light_add(type='AREA')\n"),
        _b("Spot", "LIGHT_SPOT", "Add a spot light", _OBJ + "bpy.ops.object.light_add(type='SPOT')\n"),
        _b("EEVEE", "SHADING_RENDERED", "Render engine: EEVEE",
           "import bpy\nr = bpy.context.scene.render\ntry:\n    r.engine = 'BLENDER_EEVEE'\n"
           "except TypeError:\n    r.engine = 'BLENDER_EEVEE_NEXT'\n"),
        _b("Cycles", "SHADING_RENDERED", "Render engine: Cycles",
           "import bpy\nbpy.context.scene.render.engine = 'CYCLES'\n"),
    ]},
]


def add_builtin_shelves(data):
    """Adds the built-in shelves the user hasn't had yet (an existing empty shelf with the same name gets
    the buttons). True when data changed."""
    import copy
    done = data.setdefault("builtin_added", [])
    changed = False
    for s in SHELVES:
        if s["name"] in done:
            continue
        done.append(s["name"])
        changed = True
        own = next((x for x in data["shelves"] if x.get("name") == s["name"]), None)
        if own is None:
            data["shelves"].append(copy.deepcopy(s))
        elif not own.get("buttons"):
            own["buttons"] = copy.deepcopy(s["buttons"])
    return changed

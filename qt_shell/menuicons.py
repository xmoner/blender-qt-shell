"""Icons for the items of the 3D view's right-click menus (and their submenus).

Blender gives most context-menu items no icon. Qt Shell picks one for every item that has none:
1. the operator (+ the value of its enum / type property) – OPS,
2. a submenu by its Blender menu id – MENUS,
3. words of the item's label – LABEL_RULES,
4. the operator's family (mesh.*, curve.*, armature.* …) – FAMILY,
so no item is left without one. Items with Blender's own icon keep it; check-box items keep their check mark.

    from . import menuicons
    name = menuicons.for_operator("mesh.subdivide", {}, "Subdivide")     # → "MOD_SUBSURF"
"""
import re

from . import blicons

# operator → icon, or {value of one of its string properties: icon, None: default}
OPS = {
    # ---------------------------------------------------------------- object
    "object.shade_smooth": "MESH_UVSPHERE", "object.shade_auto_smooth": "MOD_SMOOTH",
    "object.shade_smooth_by_angle": "MOD_SMOOTH", "object.shade_flat": "MESH_ICOSPHERE",
    "object.join": "AUTOMERGE_ON",
    "object.origin_set": {"GEOMETRY_ORIGIN": "PIVOT_INDIVIDUAL", "ORIGIN_GEOMETRY": "PIVOT_BOUNDBOX",
                          "ORIGIN_CURSOR": "PIVOT_CURSOR", "ORIGIN_CENTER_OF_MASS": "PIVOT_MEDIAN",
                          "ORIGIN_CENTER_OF_VOLUME": "PIVOT_MEDIAN", None: "OBJECT_ORIGIN"},
    "object.duplicate_move": "DUPLICATE", "object.duplicate": "DUPLICATE",
    "object.duplicate_move_linked": "LINKED",
    "object.delete": "TRASH",
    "object.parent_set": {"OBJECT": "OBJECT_DATA", "ARMATURE": "ARMATURE_DATA", "ARMATURE_NAME": "GROUP_VERTEX",
                          "ARMATURE_AUTO": "MOD_ARMATURE", "ARMATURE_ENVELOPE": "MOD_ENVELOPE",
                          "BONE": "BONE_DATA", "BONE_RELATIVE": "GROUP_BONE", "CURVE": "MOD_CURVE",
                          "FOLLOW": "CON_FOLLOWPATH", "PATH_CONST": "CON_FOLLOWPATH", "LATTICE": "MOD_LATTICE",
                          "VERTEX": "VERTEXSEL", "VERTEX_TRI": "FACESEL", None: "CON_CHILDOF"},
    "object.parent_no_inverse_set": "CON_CHILDOF",
    "object.parent_clear": {"CLEAR": "UNLINKED", "CLEAR_KEEP_TRANSFORM": "UNLINKED", "CLEAR_INVERSE": "LOOP_BACK",
                            None: "UNLINKED"},
    "object.convert": {"MESH": "MESH_DATA", "CURVE": "CURVE_DATA", "CURVES": "CURVES_DATA",
                       "GREASEPENCIL": "GREASEPENCIL", "POINTCLOUD": "POINTCLOUD_DATA", None: "FILE_REFRESH"},
    "object.transform_axis_target": "ORIENTATION_NORMAL",
    "object.paths_update_visible": "FILE_REFRESH",
    "object.vertex_parent_set": "CON_CHILDOF",
    "object.hide_view_set": "HIDE_ON", "object.hide_view_clear": "HIDE_OFF",
    "object.select_all": "RESTRICT_SELECT_OFF", "object.move_to_collection": "OUTLINER_COLLECTION",
    "object.link_to_collection": "LINKED",
    "object.make_links_data": "LINKED", "object.make_single_user": "USER",
    "object.transform_apply": "CHECKMARK", "object.visual_transform_apply": "CHECKMARK",
    "object.location_clear": "X", "object.rotation_clear": "X", "object.scale_clear": "X",
    "object.origin_clear": "X",
    "view3d.object_as_camera": "VIEW_CAMERA",
    "anim.keyframe_insert": "KEY_HLT", "anim.keyframe_insert_menu": "KEYINGSET",
    "anim.keyframe_delete_v3d": "KEY_DEHLT", "anim.keyframe_clear_v3d": "KEY_DEHLT",
    "anim.keyframe_insert_by_name": "KEY_HLT",
    "wm.call_panel": {"TOPBAR_PT_name": "SORTALPHA", None: "MENU_PANEL"},
    # ---------------------------------------------------------------- transform
    "transform.mirror": "MOD_MIRROR", "transform.translate": "EMPTY_ARROWS", "transform.rotate": "FILE_REFRESH",
    "transform.resize": "FULLSCREEN_ENTER", "transform.push_pull": "ARROW_LEFTRIGHT",
    "transform.shrink_fatten": "MOD_THICKNESS", "transform.shear": "MOD_SIMPLEDEFORM",
    "transform.vert_slide": "SNAP_VERTEX", "transform.edge_slide": "SNAP_EDGE",
    "transform.vertex_random": "RNDCURVE", "transform.tosphere": "SPHERE", "transform.bend": "MOD_SIMPLEDEFORM",
    "transform.tilt": "ORIENTATION_GIMBAL", "transform.vertex_warp": "MOD_WARP",
    "transform.skin_resize": "MOD_SKIN", "transform.edge_crease": "EDGE_CREASE",
    "transform.edge_bevelweight": "EDGE_BEVEL",
    "transform.transform": {"CURVE_SHRINKFATTEN": "MOD_THICKNESS", "BONE_ROLL": "ORIENTATION_GIMBAL",
                            "BONE_SIZE": "FULLSCREEN_ENTER", "BONE_ENVELOPE": "MOD_ENVELOPE",
                            "GPENCIL_SHRINKFATTEN": "MOD_THICKNESS", "TILT": "ORIENTATION_GIMBAL",
                            None: "EMPTY_ARROWS"},
    # ---------------------------------------------------------------- snap / cursor
    "view3d.snap_selected_to_grid": "SNAP_GRID", "view3d.snap_selected_to_cursor": "PIVOT_CURSOR",
    "view3d.snap_selected_to_active": "PIVOT_ACTIVE", "view3d.snap_cursor_to_selected": "RESTRICT_SELECT_OFF",
    "view3d.snap_cursor_to_center": "WORLD", "view3d.snap_cursor_to_grid": "SNAP_GRID",
    "view3d.snap_cursor_to_active": "PIVOT_ACTIVE",
    "view3d.edit_mesh_extrude_move_normal": "NORMALS_FACE",
    "view3d.edit_mesh_extrude_move_shrink_fatten": "MOD_SOLIDIFY",
    "view3d.edit_mesh_extrude_individual_move": "FACESEL",
    # ---------------------------------------------------------------- mesh
    "mesh.subdivide": "MOD_SUBSURF", "mesh.unsubdivide": "MOD_DECIM",
    "mesh.extrude_vertices_move": "VERTEXSEL", "mesh.extrude_edges_move": "EDGESEL",
    "mesh.extrude_faces_move": "FACESEL", "mesh.extrude_region_move": "MOD_SOLIDIFY",
    "mesh.extrude_context_move": "MOD_SOLIDIFY", "mesh.extrude_region_shrink_fatten": "MOD_SOLIDIFY",
    "mesh.bevel": "MOD_BEVEL",
    "mesh.edge_face_add": "FACESEL", "mesh.vert_connect_path": "CURVE_PATH", "mesh.vert_connect": "LINKED",
    "mesh.vertices_smooth": "MOD_SMOOTH", "mesh.vertices_smooth_laplacian": "MOD_SMOOTH",
    "mesh.merge": {"CENTER": "PIVOT_MEDIAN", "CURSOR": "PIVOT_CURSOR", "COLLAPSE": "AUTOMERGE_ON",
                   "FIRST": "TRIA_LEFT_BAR", "LAST": "TRIA_RIGHT_BAR", None: "AUTOMERGE_ON"},
    "mesh.remove_doubles": "AUTOMERGE_ON",
    "mesh.split": "MOD_EDGESPLIT", "mesh.edge_split": "MOD_EDGESPLIT",
    "mesh.separate": {"SELECTED": "RESTRICT_SELECT_OFF", "MATERIAL": "MATERIAL", "LOOSE": "STICKY_UVS_DISABLE",
                      None: "MOD_EDGESPLIT"},
    "mesh.dissolve_verts": "VERTEXSEL", "mesh.dissolve_edges": "EDGESEL", "mesh.dissolve_faces": "FACESEL",
    "mesh.dissolve_limited": "MOD_DECIM", "mesh.dissolve_mode": "MOD_DECIM",
    "mesh.delete": {"VERT": "TRASH", "EDGE": "TRASH", "FACE": "TRASH", "ONLY_FACE": "TRASH",
                    "EDGE_FACE": "TRASH", None: "TRASH"},
    "mesh.delete_loose": "TRASH", "mesh.delete_edgeloop": "TRASH",
    "mesh.bridge_edge_loops": "MOD_SCREW", "mesh.fill": "FACESEL", "mesh.fill_grid": "MESH_GRID",
    "mesh.beautify_fill": "MOD_TRIANGULATE",
    "mesh.loopcut_slide": "MOD_ARRAY", "mesh.offset_edge_loops_slide": "MOD_OFFSET",
    "mesh.knife_tool": "SHARPCURVE", "mesh.bisect": "MOD_BOOLEAN",
    "mesh.edge_rotate": "FILE_REFRESH",
    "mesh.mark_seam": {"__clear": "X", None: "EDGE_SEAM"}, "mesh.mark_sharp": {"__clear": "X", None: "EDGE_SHARP"},
    "mesh.set_sharpness_by_angle": "EDGE_SHARP",
    "mesh.mark_freestyle_edge": {"__clear": "X", None: "LINE_DATA"},
    "mesh.mark_freestyle_face": {"__clear": "X", None: "LINE_DATA"},
    "mesh.inset": "MOD_THICKNESS", "mesh.poke": "MOD_TRIANGULATE",
    "mesh.quads_convert_to_tris": "MOD_TRIANGULATE", "mesh.tris_convert_to_quads": "MESH_PLANE",
    "mesh.faces_shade_smooth": "MESH_UVSPHERE", "mesh.faces_shade_flat": "MESH_ICOSPHERE",
    "mesh.normals_make_consistent": "NORMALS_FACE", "mesh.flip_normals": "NORMALS_FACE",
    "mesh.select_all": "RESTRICT_SELECT_OFF", "mesh.hide": "HIDE_ON", "mesh.reveal": "HIDE_OFF",
    "mesh.duplicate_move": "DUPLICATE", "mesh.spin": "MOD_SCREW", "mesh.rip_move": "MOD_EDGESPLIT",
    "mesh.symmetrize": "MOD_MIRROR", "mesh.sort_elements": "SORTSIZE", "mesh.blend_from_shape": "SHAPEKEY_DATA",
    "mesh.shape_propagate_to_all": "SHAPEKEY_DATA", "mesh.vertices_smooth_laplacian_": "MOD_SMOOTH",
    "mesh.edge_collapse": "AUTOMERGE_ON", "mesh.solidify": "MOD_SOLIDIFY", "mesh.wireframe": "MOD_WIREFRAME",
    "mesh.decimate": "MOD_DECIM", "mesh.mark_sharp_": "EDGE_SHARP",
    # ---------------------------------------------------------------- uv
    "uv.unwrap": "UV", "uv.smart_project": "UV_ISLANDSEL", "uv.lightmap_pack": "UV_FACESEL",
    "uv.follow_active_quads": "UV_FACESEL", "uv.cube_project": "MESH_CUBE", "uv.cylinder_project": "MESH_CYLINDER",
    "uv.sphere_project": "MESH_UVSPHERE", "uv.project_from_view": "VIEW_CAMERA_UNSELECTED", "uv.reset": "LOOP_BACK",
    "uv.mark_seam": "EDGE_SEAM",
    # ---------------------------------------------------------------- pose
    "pose.push": "TRIA_RIGHT_BAR", "pose.relax": "TRIA_LEFT_BAR", "pose.breakdown": "KEYTYPE_BREAKDOWN_VEC",
    "pose.blend_to_neighbor": "IPO_EASE_IN_OUT", "pose.paths_calculate": "CURVE_PATH",
    "pose.paths_clear": "X", "pose.paths_update": "FILE_REFRESH",
    "pose.hide": "HIDE_ON", "pose.reveal": "HIDE_OFF", "pose.user_transforms_clear": "LOOP_BACK",
    "pose.copy": "COPYDOWN", "pose.paste": {"__flipped": "PASTEFLIPDOWN", None: "PASTEDOWN"},
    "pose.transforms_clear": "X", "pose.loc_clear": "X", "pose.rot_clear": "X", "pose.scale_clear": "X",
    "pose.select_all": "RESTRICT_SELECT_OFF", "pose.armature_apply": "CHECKMARK",
    "pose.constraint_add_with_targets": "CONSTRAINT_BONE", "pose.ik_add": "CON_KINEMATIC", "pose.ik_clear": "X",
    "pose.flip_names": "ARROW_LEFTRIGHT", "pose.autoside_names": "SORTALPHA",
    "pose.propagate": "NEXT_KEYFRAME",
    # ---------------------------------------------------------------- armature (edit)
    "armature.subdivide": "MOD_SUBSURF", "armature.duplicate_move": "DUPLICATE",
    "armature.duplicate": "DUPLICATE", "armature.extrude_move": "BONE_DATA", "armature.extrude_forked": "BONE_DATA",
    "armature.fill": "LINKED", "armature.symmetrize": "MOD_MIRROR", "armature.switch_direction": "ARROW_LEFTRIGHT",
    "armature.autoside_names": {"XAXIS": "AXIS_SIDE", "YAXIS": "AXIS_FRONT", "ZAXIS": "AXIS_TOP",
                                None: "SORTALPHA"},
    "armature.flip_names": "ARROW_LEFTRIGHT",
    "armature.parent_set": {"CONNECTED": "LINKED", "OFFSET": "CON_CHILDOF", None: "CON_CHILDOF"},
    "armature.parent_clear": {"CLEAR": "UNLINKED", "DISCONNECT": "UNLINKED", None: "UNLINKED"},
    "armature.split": "MOD_EDGESPLIT", "armature.separate": "MOD_EDGESPLIT",
    "armature.dissolve": "BONE_DATA", "armature.delete": "TRASH",
    "armature.calculate_roll": "ORIENTATION_GIMBAL", "armature.roll_clear": "X",
    "armature.select_all": "RESTRICT_SELECT_OFF", "armature.hide": "HIDE_ON", "armature.reveal": "HIDE_OFF",
    "armature.bone_primitive_add": "BONE_DATA", "armature.align": "ALIGN_CENTER",
    "armature.move_to_collection": "GROUP_BONE", "armature.assign_to_collection": "GROUP_BONE",
    "armature.select_hierarchy": "CON_CHILDOF", "armature.select_similar": "RESTRICT_SELECT_OFF",
    # ---------------------------------------------------------------- curve / surface
    "curve.subdivide": "MOD_SUBSURF", "curve.extrude_move": "CURVE_BEZCURVE", "curve.extrude": "CURVE_BEZCURVE",
    "curve.make_segment": "LINKED", "curve.duplicate_move": "DUPLICATE", "curve.duplicate": "DUPLICATE",
    "curve.tilt_clear": "X", "curve.smooth": "MOD_SMOOTH", "curve.smooth_tilt": "ORIENTATION_GIMBAL",
    "curve.smooth_radius": "MOD_THICKNESS", "curve.smooth_weight": "MOD_SMOOTH",
    "curve.spline_type_set": {"POLY": "IPO_LINEAR", "BEZIER": "IPO_BEZIER", "NURBS": "CURVE_NCURVE",
                              "CATMULL_ROM": "SMOOTHCURVE", None: "CURVE_DATA"},
    "curve.handle_type_set": {"AUTOMATIC": "HANDLE_AUTO", "VECTOR": "HANDLE_VECTOR", "ALIGNED": "HANDLE_ALIGNED",
                              "FREE_ALIGN": "HANDLE_FREE", "TOGGLE_FREE_ALIGN": "HANDLETYPE_FREE_VEC",
                              None: "HANDLE_AUTO"},
    "curve.cyclic_toggle": "CURVE_BEZCIRCLE", "curve.switch_direction": "ARROW_LEFTRIGHT",
    "curve.normals_make_consistent": "HANDLE_AUTOCLAMPED", "curve.spline_weight_set": "MOD_VERTEX_WEIGHT",
    "curve.radius_set": "MOD_THICKNESS", "curve.split": "MOD_EDGESPLIT", "curve.decimate": "MOD_DECIM",
    "curve.separate": "MOD_EDGESPLIT", "curve.dissolve_verts": "VERTEXSEL",
    "curve.delete": {"SEGMENT": "TRASH", "VERT": "TRASH", None: "TRASH"},
    "curve.select_all": "RESTRICT_SELECT_OFF", "curve.hide": "HIDE_ON", "curve.reveal": "HIDE_OFF",
    # ---------------------------------------------------------------- text
    "font.text_cut": "X", "font.text_copy": "COPYDOWN", "font.text_paste": "PASTEDOWN",
    "font.select_all": "RESTRICT_SELECT_OFF", "font.text_paste_from_file": "FILE_TEXT",
    "font.case_set": {"UPPER": "TRIA_UP", "LOWER": "TRIA_DOWN", None: "SMALL_CAPS"},
    "font.text_insert": "FONT_DATA", "font.text_insert_unicode": "FONT_DATA",
    "font.change_spacing": "ARROW_LEFTRIGHT",
    "font.delete": {"PREVIOUS_CHARACTER": "TRIA_LEFT", "NEXT_CHARACTER": "TRIA_RIGHT",
                    "PREVIOUS_WORD": "TRIA_LEFT_BAR", "NEXT_WORD": "TRIA_RIGHT_BAR", None: "X"},
    "font.style_toggle": {"BOLD": "BOLD", "ITALIC": "ITALIC", "UNDERLINE": "UNDERLINE", "SMALL_CAPS": "SMALL_CAPS",
                          None: "FONT_DATA"},
    # ---------------------------------------------------------------- metaball / lattice
    "mball.duplicate_move": "DUPLICATE", "mball.delete_metaelems": "TRASH",
    "mball.select_all": "RESTRICT_SELECT_OFF", "mball.hide_metaelems": "HIDE_ON",
    "mball.reveal_metaelems": "HIDE_OFF",
    "lattice.flip": {"U": "AXIS_SIDE", "V": "AXIS_FRONT", "W": "AXIS_TOP", None: "MOD_MIRROR"},
    "lattice.make_regular": "MESH_GRID", "lattice.select_all": "RESTRICT_SELECT_OFF",
    # ---------------------------------------------------------------- grease pencil
    "grease_pencil.stroke_subdivide": "MOD_SUBSURF", "grease_pencil.stroke_subdivide_smooth": "MOD_SUBSURF",
    "grease_pencil.stroke_simplify": "MOD_SIMPLIFY", "grease_pencil.outline": "MOD_OUTLINE",
    "grease_pencil.stroke_smooth": "MOD_SMOOTH", "grease_pencil.set_start_point": "PLAY",
    "grease_pencil.set_corner_type": {"ROUND": "GP_CAPS_ROUND", "FLAT": "GP_CAPS_FLAT", "SHARP": "SHARPCURVE",
                                      None: "GP_CAPS_ROUND"},
    "grease_pencil.duplicate_move": "DUPLICATE", "grease_pencil.extrude_move": "STROKE",
    "grease_pencil.stroke_split": "MOD_EDGESPLIT", "grease_pencil.separate": "MOD_EDGESPLIT",
    "grease_pencil.dissolve": "GP_SELECT_POINTS",
    "grease_pencil.convert_curve_type": {"CATMULL_ROM": "SMOOTHCURVE", "POLY": "IPO_LINEAR",
                                         "BEZIER": "IPO_BEZIER", "NURBS": "CURVE_NCURVE", None: "CURVE_DATA"},
    "grease_pencil.set_curve_type": {"CATMULL_ROM": "SMOOTHCURVE", "POLY": "IPO_LINEAR",
                                     "BEZIER": "IPO_BEZIER", "NURBS": "CURVE_NCURVE", None: "CURVE_DATA"},
    "grease_pencil.cyclical_set": "CURVE_BEZCIRCLE", "grease_pencil.stroke_switch_direction": "ARROW_LEFTRIGHT",
    "grease_pencil.delete": "TRASH", "grease_pencil.select_all": "RESTRICT_SELECT_OFF",
    "grease_pencil.stroke_reorder": "SORT_ASC", "grease_pencil.stroke_material_set": "MATERIAL",
    "grease_pencil.set_uniform_thickness": "MOD_THICKNESS", "grease_pencil.set_uniform_opacity": "MOD_OPACITY",
    "grease_pencil.reset_uvs": "UV", "grease_pencil.stroke_merge_by_distance": "AUTOMERGE_ON",
    "grease_pencil.clean_loose": "TRASH", "grease_pencil.copy": "COPYDOWN", "grease_pencil.paste": "PASTEDOWN",
    # ---------------------------------------------------------------- curves (hair) / particles
    "curves.delete": "TRASH", "curves.select_all": "RESTRICT_SELECT_OFF", "curves.subdivide": "MOD_SUBSURF",
    "curves.duplicate_move": "DUPLICATE", "curves.extrude_move": "CURVES", "curves.set_selection_domain": "CURVES",
    "particle.delete": "TRASH", "particle.rekey": "PARTICLE_POINT", "particle.subdivide": "MOD_SUBSURF",
    "particle.remove_doubles": "AUTOMERGE_ON", "particle.weight_set": "MOD_VERTEX_WEIGHT",
    "particle.mirror": "MOD_MIRROR", "particle.unify_length": "MOD_LENGTH",
    "particle.select_all": "RESTRICT_SELECT_OFF", "particle.hide": "HIDE_ON", "particle.reveal": "HIDE_OFF",
}

# Blender menus (submenus / wm.call_menu) → icon
MENUS = {
    "VIEW3D_MT_mirror": "MOD_MIRROR", "VIEW3D_MT_snap": "SNAP_ON", "VIEW3D_MT_object_parent": "CON_CHILDOF",
    "VIEW3D_MT_edit_mesh_merge": "AUTOMERGE_ON", "VIEW3D_MT_uv_map": "UV",
    "VIEW3D_MT_edit_armature_names": "SORTALPHA", "VIEW3D_MT_edit_armature_parent": "CON_CHILDOF",
    "VIEW3D_MT_edit_font": "FONT_DATA", "VIEW3D_MT_edit_font_chars": "FONT_DATA",
    "VIEW3D_MT_edit_font_kerning": "ARROW_LEFTRIGHT", "VIEW3D_MT_edit_font_delete": "TRASH",
    "VIEW3D_MT_edit_mesh_delete": "TRASH", "VIEW3D_MT_edit_curve_delete": "TRASH",
    "VIEW3D_MT_edit_armature_delete": "TRASH", "VIEW3D_MT_object_apply": "CHECKMARK",
    "VIEW3D_MT_object_clear": "X", "VIEW3D_MT_pose_transform": "X", "VIEW3D_MT_object_convert": "FILE_REFRESH",
    "VIEW3D_MT_edit_mesh_normals": "NORMALS_FACE", "VIEW3D_MT_edit_mesh_shading": "SHADING_SOLID",
    "VIEW3D_MT_edit_mesh_clean": "BRUSH_DATA", "VIEW3D_MT_object_animation": "ANIM",
    "VIEW3D_MT_pose_motion": "CURVE_PATH", "VIEW3D_MT_object_motion_paths": "CURVE_PATH",
    "VIEW3D_MT_bone_options_toggle": "SETTINGS", "VIEW3D_MT_bone_options_enable": "CHECKBOX_HLT",
    "VIEW3D_MT_bone_options_disable": "CHECKBOX_DEHLT", "VIEW3D_MT_hook": "HOOK",
    "VIEW3D_MT_vertex_group": "GROUP_VERTEX", "VIEW3D_MT_edit_mesh_extrude": "MOD_SOLIDIFY",
    "VIEW3D_MT_object_collection": "OUTLINER_COLLECTION", "VIEW3D_MT_make_links": "LINKED",
    "VIEW3D_MT_make_single_user": "USER", "VIEW3D_MT_object_shading": "SHADING_SOLID",
    "VIEW3D_MT_object_quick_effects": "SHADERFX", "VIEW3D_MT_object_rigid_body": "RIGID_BODY",
    "VIEW3D_MT_object_constraints": "CONSTRAINT", "VIEW3D_MT_pose_constraints": "CONSTRAINT_BONE",
    "VIEW3D_MT_pose_ik": "CON_KINEMATIC", "VIEW3D_MT_pose_names": "SORTALPHA",
    "VIEW3D_MT_pose_slide": "IPO_EASE_IN_OUT", "VIEW3D_MT_pose_propagate": "NEXT_KEYFRAME",
    "VIEW3D_MT_object_showhide": "HIDE_OFF", "VIEW3D_MT_pose_showhide": "HIDE_OFF",
    "VIEW3D_MT_edit_curve_showhide": "HIDE_OFF", "VIEW3D_MT_armature_showhide": "HIDE_OFF",
    "VIEW3D_MT_edit_mesh_showhide": "HIDE_OFF", "VIEW3D_MT_edit_greasepencil_stroke": "STROKE",
    "VIEW3D_MT_edit_greasepencil_point": "GP_SELECT_POINTS",
}

# label words → icon (first match; for submenus Qt fills itself and anything not in the tables)
LABEL_RULES = [
    (r"\bdelete|\bremove\b", "TRASH"), (r"^clear\b|\bclear\b", "X"), (r"duplicat|\bcopy\b(?!.*paste)", "DUPLICATE"),
    (r"\bpaste\b", "PASTEDOWN"), (r"\bcut\b", "X"), (r"set origin|\borigin\b", "OBJECT_ORIGIN"),
    (r"convert", "FILE_REFRESH"), (r"separate|\bsplit\b", "MOD_EDGESPLIT"), (r"\bjoin\b|merge", "AUTOMERGE_ON"),
    (r"mirror|flip", "MOD_MIRROR"), (r"\bsnap\b", "SNAP_ON"), (r"parent", "CON_CHILDOF"),
    (r"\bhide\b", "HIDE_ON"), (r"reveal|\bshow\b|unhide", "HIDE_OFF"), (r"select", "RESTRICT_SELECT_OFF"),
    (r"keyframe|\bkey\b", "KEY_HLT"), (r"subdivid", "MOD_SUBSURF"), (r"smooth", "MOD_SMOOTH"),
    (r"extrude", "MOD_SOLIDIFY"), (r"bevel", "MOD_BEVEL"), (r"dissolve", "MOD_DECIM"), (r"decimate|simplif", "MOD_DECIM"),
    (r"spline type|curve type|stroke type|convert type", "CURVE_DATA"), (r"handle", "HANDLE_AUTO"),
    (r"corner", "SHARPCURVE"), (r"normal", "NORMALS_FACE"), (r"\buv\b|unwrap", "UV"), (r"shad(e|ing)", "SHADING_SOLID"),
    (r"motion path", "CURVE_PATH"), (r"\bnames?\b|rename", "SORTALPHA"), (r"kerning|spacing", "ARROW_LEFTRIGHT"),
    (r"character|text|font", "FONT_DATA"), (r"camera|focal|focus", "CAMERA_DATA"),
    (r"light (power|radius)|\blight\b|power", "LIGHT_DATA"), (r"empty", "EMPTY_DATA"), (r"extrusion", "MOD_SOLIDIFY"),
    (r"offset", "MOD_OFFSET"), (r"radius|thickness|fatten", "MOD_THICKNESS"), (r"tilt|roll", "ORIENTATION_GIMBAL"),
    (r"weight", "MOD_VERTEX_WEIGHT"), (r"collection", "OUTLINER_COLLECTION"), (r"constraint", "CONSTRAINT"),
    (r"modifier", "MODIFIER"), (r"material", "MATERIAL"), (r"vertex|vertices|point", "VERTEXSEL"),
    (r"edge", "EDGESEL"), (r"face", "FACESEL"), (r"bone", "BONE_DATA"), (r"apply", "CHECKMARK"),
    (r"cursor", "PIVOT_CURSOR"), (r"axis", "EMPTY_AXIS"), (r"animation|anim\b", "ANIM"), (r"options|settings", "SETTINGS"),
]

# operator family → icon (last resort before DOT)
FAMILY = {
    "object": "OBJECT_DATA", "mesh": "MESH_DATA", "curve": "CURVE_DATA", "surface": "SURFACE_DATA",
    "armature": "BONE_DATA", "pose": "POSE_HLT", "lattice": "LATTICE_DATA", "mball": "META_DATA",
    "font": "FONT_DATA", "grease_pencil": "GREASEPENCIL", "gpencil": "GREASEPENCIL", "curves": "CURVES_DATA",
    "particle": "PARTICLES", "uv": "UV", "anim": "ANIM", "transform": "EMPTY_ARROWS", "view3d": "VIEW3D",
    "sculpt": "SCULPTMODE_HLT", "paint": "TPAINT_HLT", "material": "MATERIAL", "constraint": "CONSTRAINT",
    "marker": "MARKER", "screen": "WINDOW", "wm": "DOT",
}
FALLBACK = "DOT"


def _ok(name):
    return name if name and blicons.has(name) else None


def _from_table(entry, props):
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, dict):
        return None
    props = props or {}
    for v in props.values():                       # value of an enum / type / mode … property
        if isinstance(v, str) and v in entry:
            return entry[v]
    if props.get("clear") and "__clear" in entry:
        return entry["__clear"]
    if props.get("flipped") and "__flipped" in entry:
        return entry["__flipped"]
    return entry.get(None)


def for_label(text):
    t = (text or "").strip().lower()
    for pat, name in LABEL_RULES:
        if re.search(pat, t) and blicons.has(name):
            return name
    return None


def for_menu(menu_id, text=""):
    return _ok(MENUS.get(menu_id)) or for_label(text) or FALLBACK


def for_operator(idname, props=None, text=""):
    """Icon name for a menu item that runs this operator (never None)."""
    props = props or {}
    if idname in ("wm.call_menu", "wm.call_menu_pie") and props.get("name"):
        return for_menu(props["name"], text)
    axis = props.get("constraint_axis")
    if idname == "transform.mirror" and isinstance(axis, (tuple, list)) and sum(bool(a) for a in axis) == 1:
        return ("EVENT_X", "EVENT_Y", "EVENT_Z")[[bool(a) for a in axis].index(True)]
    name = _ok(_from_table(OPS.get(idname), props))
    if name:
        return name
    if idname.startswith("wm.context_modal_mouse") or idname == "wm.context_modal_mouse":
        return for_label(text) or "MOUSE_MOVE"
    return for_label(text) or _ok(FAMILY.get(idname.split(".")[0])) or FALLBACK


def op_from_tag(tag):
    """(idname, props) from a Python tooltip tag like "bpy.ops.mesh.merge(type='CENTER')"."""
    import ast
    m = re.match(r"\s*bpy\.ops\.([\w]+\.[\w]+)\((.*)\)\s*$", tag or "", re.S)
    if not m:
        return None, {}
    props = {}
    try:
        call = ast.parse(f"f({m.group(2)})", mode="eval").body
        for kw in call.keywords:
            try:
                props[kw.arg] = ast.literal_eval(kw.value)
            except Exception:
                pass
    except SyntaxError:
        pass
    return m.group(1), props


def apply(menu):
    """Gives every action of a filled QMenu without an icon one (not check-box items, not headings).
    Submenus get theirs too; Lazy submenus are marked so they do the same when they open."""
    from PySide6 import QtWidgets
    from . import pytips
    for act in menu.actions():
        if act.isSeparator():
            continue
        sub = act.menu()
        if sub is not None:
            setattr(sub, "auto_icons", True)
            if not sub.actions() or type(sub).__name__ != "LazyMenu":
                if isinstance(sub, QtWidgets.QMenu) and type(sub).__name__ != "LazyMenu":
                    apply(sub)               # filled already (operator_menu_enum, enum props)
        if not act.icon().isNull() or act.isCheckable():
            continue
        if not act.isEnabled() and act.font().bold():
            continue                         # a label / heading
        name = None
        tag = pytips._get(act) or (pytips._get(sub.menuAction()) if sub is not None else None)
        if sub is not None and getattr(sub, "menu_id", None):
            name = for_menu(sub.menu_id, act.text())
        elif tag:
            idname, props = op_from_tag(tag)
            if idname:
                name = for_operator(idname, props, act.text())
        if name is None:
            name = for_label(act.text()) or FALLBACK
        if blicons.has(name):
            act.setIcon(blicons.icon(name))

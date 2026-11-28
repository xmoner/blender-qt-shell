"""Dragging datablocks (objects, collections, materials, images, worlds, node groups …) between Qt Shell's
editors, like Blender's ID drag & drop (since 0.129.0).

Sources: Outliner rows, ID fields of Properties (template_ID / pointer fields). Targets – what Blender does:
  3D view (Qt Shell's view and Blender's embedded view)
    Object       → moved under the mouse (object.transform_to_mouse – onto the surface under the mouse)
    Collection   → collection instance at the mouse (object.collection_instance_add)
    Object data  → an instance object of that data at the mouse (object.data_instance_add)
    Material     → assigned to the object under the mouse (its active slot – object.drop_named_material)
    Node group   → Geometry Nodes modifier on the object under the mouse (object.drop_geometry_nodes)
    Image        → image empty at the mouse (object.empty_image_add)
    World        → the scene's world (view3d.drop_world)
  Node editor
    Object → Object Info, Collection → Collection Info, Material → Material (Geometry Nodes),
    Image → Image / Image Texture / Image node, Node group of the same type → group node
  ID fields (Properties) → set to the dropped datablock when its type fits.
"""
import json

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge

MIME = "application/x-qtshell-ids"

# ID.id_type → bpy.data collection
COLLS = {
    "OBJECT": "objects", "COLLECTION": "collections", "MATERIAL": "materials", "IMAGE": "images",
    "WORLD": "worlds", "NODETREE": "node_groups", "MESH": "meshes", "CURVE": "curves", "CURVES": "hair_curves",
    "CAMERA": "cameras", "LIGHT": "lights", "ARMATURE": "armatures", "LATTICE": "lattices", "METABALL": "metaballs",
    "FONT": "curves", "GREASEPENCIL": "grease_pencils", "GREASEPENCIL_V3": "grease_pencils_v3",
    "POINTCLOUD": "pointclouds", "VOLUME": "volumes", "SPEAKER": "speakers", "LIGHT_PROBE": "lightprobes",
    "TEXT": "texts", "ACTION": "actions", "MASK": "masks", "MOVIECLIP": "movieclips", "SOUND": "sounds",
    "SCENE": "scenes", "TEXTURE": "textures", "BRUSH": "brushes", "PALETTE": "palettes",
}
# object data that Blender drops as an instance object (object.data_instance_add)
DATA_TYPES = {"MESH", "CURVE", "CURVES", "CAMERA", "LIGHT", "ARMATURE", "LATTICE", "METABALL", "FONT",
              "GREASEPENCIL", "GREASEPENCIL_V3", "POINTCLOUD", "VOLUME", "SPEAKER", "LIGHT_PROBE"}


# ---------------------------------------------------------------- data
def encode(ids):
    out = []
    for i in ids:
        if i is None:
            continue
        try:
            out.append([i.id_type, i.name, i.library.filepath if i.library else ""])
        except Exception:
            pass
    return out


def mime_data(ids, md=None):
    md = md or QtCore.QMimeData()
    md.setData(MIME, QtCore.QByteArray(json.dumps(encode(ids)).encode("utf-8")))
    return md


def lookup(id_type, name, lib=""):
    coll = getattr(bpy.data, COLLS.get(id_type, ""), None)
    if coll is None:
        return None
    for i in coll:
        if i.name == name and ((i.library.filepath if i.library else "") == lib):
            return i
    return None


def decode(md):
    """The datablocks in a drag (a QMimeData), [] when it carries none."""
    try:
        if md is None or not md.hasFormat(MIME):
            return []
        rows = json.loads(bytes(md.data(MIME)).decode("utf-8"))
    except Exception:
        return []
    out = []
    for row in rows:
        i = lookup(*row)
        if i is not None:
            out.append(i)
    return out


def drag_pixmap(ids):
    """A small label with the icon and name(s), like Blender's drag tooltip."""
    from . import blicons, theme
    names = ", ".join(i.name for i in ids[:3]) + (" …" if len(ids) > 3 else "")
    icon = {"OBJECT": "OBJECT_DATA", "COLLECTION": "OUTLINER_COLLECTION", "MATERIAL": "MATERIAL",
            "IMAGE": "IMAGE_DATA", "WORLD": "WORLD", "NODETREE": "NODETREE"}.get(ids[0].id_type, "BLANK1")
    f = QtWidgets.QApplication.font()
    fm = QtGui.QFontMetrics(f)
    s = theme.px(16)
    w, h = s + 10 + fm.horizontalAdvance(names), max(s, fm.height()) + 6
    pm = QtGui.QPixmap(w, h)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    try:
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setBrush(QtGui.QColor(40, 40, 40, 220))
        p.setPen(QtGui.QColor("#5a5a5a"))
        p.drawRoundedRect(QtCore.QRectF(0.5, 0.5, w - 1, h - 1), 4, 4)
        try:
            if blicons.has(icon):
                blicons.icon(icon).paint(p, QtCore.QRect(4, (h - s) // 2, s, s))
        except Exception:
            pass
        p.setPen(QtGui.QColor("#e6e6e6"))
        p.setFont(f)
        p.drawText(QtCore.QRect(s + 8, 0, w - s - 8, h), QtCore.Qt.AlignVCenter, names)
    finally:
        p.end()
    return pm


def start_drag(source, ids, md=None, actions=None):
    """Starts a Qt drag of the datablocks from `source`. A drop on Blender's embedded 3D view (a native window
    Qt can't drop on) is done here after the drag. Returns Qt's drop action."""
    ids = [i for i in ids if i is not None]
    if not ids:
        return QtCore.Qt.IgnoreAction
    drag = QtGui.QDrag(source)
    drag.setMimeData(mime_data(ids, md))
    try:
        pm = drag_pixmap(ids)
        drag.setPixmap(pm)
        drag.setHotSpot(QtCore.QPoint(-12, -12))
    except Exception:
        pass
    res = drag.exec(actions or (QtCore.Qt.CopyAction | QtCore.Qt.MoveAction | QtCore.Qt.LinkAction),
                    QtCore.Qt.CopyAction)
    # Blender's embedded view is a native window: Windows hands the drop to Blender's own (GHOST) drop target,
    # which takes it (Copy) without doing anything – the drop is done here when the mouse ended over that view
    gpos = QtGui.QCursor.pos()
    if native_view_at(gpos) is not None:
        try:
            drop_native(ids, gpos)
        except Exception:
            bridge.log("Drop on Blender's view: " + __import__("traceback").format_exc(), "WARNING")
    return res


# ---------------------------------------------------------------- 3D view
class _Target:
    """Where a drop lands in a 3D view: Blender's window / area / region and the mouse in window
    coordinates (Blender's drop_x / drop_y), plus the 3D ray under the mouse."""

    def __init__(self, window, area, region, rv3d, wx, wy, origin, direction):
        self.window, self.area, self.region, self.rv3d = window, area, region, rv3d
        self.wx, self.wy = int(wx), int(wy)
        self.origin, self.direction = origin, direction

    def context(self):
        return bpy.context.temp_override(window=self.window, screen=self.window.screen, area=self.area,
                                         region=self.region)


def _qt_view_target(vp, pos):
    """Qt Shell's own (offscreen) view: the hidden Blender 3D view gets the Qt view's camera; the mouse is
    mapped onto it through a point of the same ray (same eye → same ray in Blender's region)."""
    from . import sculpt
    found = bridge.ensure_view3d()
    if not found:
        return None
    win, area, _region = found
    sync = sculpt._sync_hidden(vp)
    if sync is None:
        return None
    region, rv = sync
    m = sculpt._to_hidden(vp, region, rv, pos.x(), pos.y(), 10.0)
    if m is None:
        return None
    o, d = vp.ray(pos.x(), pos.y())
    return _Target(win, area, region, rv, region.x + m[0], region.y + m[1], o, d)


def _native_target(nv, gpos):
    """Blender's embedded view: the drop point in its window's pixels (Blender counts y from the bottom)."""
    from bpy_extras import view3d_utils
    win, area = nv.window(), nv.area()
    if win is None or area is None:
        return None
    c = nv.container
    lp = c.mapFromGlobal(gpos)
    dpr = c.devicePixelRatioF() if hasattr(c, "devicePixelRatioF") else 1.0
    wx = lp.x() * dpr
    wy = win.height - lp.y() * dpr
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    if region is None:
        return None
    rv = area.spaces.active.region_3d
    co = (wx - region.x, wy - region.y)
    o = view3d_utils.region_2d_to_origin_3d(region, rv, co)
    d = view3d_utils.region_2d_to_vector_3d(region, rv, co)
    return _Target(win, area, region, rv, wx, wy, o, d)


def native_view_at(gpos):
    """The NativeView (Blender's embedded 3D view) under a global point, or None."""
    try:
        from . import sculptview
        for nv in list(sculptview._views.values()):
            c = getattr(nv, "container", None)
            if c is not None and c.isVisible() and c.rect().contains(c.mapFromGlobal(gpos)):
                return nv
    except Exception:
        pass
    return None


def drop_native(ids, gpos):
    nv = native_view_at(gpos)
    if nv is None:
        return False
    t = _native_target(nv, gpos)
    if t is None:
        return False
    ok = drop_view3d(t, ids)
    try:
        nv.area().tag_redraw()
    except Exception:
        pass
    return ok


def _object_under(t):
    """The object whose surface is under the mouse (evaluated mesh ray cast, as Blender does)."""
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        hit, _loc, _n, _i, ob, _m = bpy.context.scene.ray_cast(dg, t.origin, t.direction)
        return ob.original if hit and ob is not None else None
    except Exception:
        return None


def _location(t, exclude=()):
    """Like Blender's drop snapping: the surface under the mouse (skipping the dragged objects), else the
    ground plane (Z = 0), else the plane through the 3D cursor facing the view."""
    from mathutils import Vector, geometry
    skip = {o.name for o in exclude}
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        o = t.origin.copy()
        for _k in range(16):
            hit, loc, _n, _i, ob, _m = bpy.context.scene.ray_cast(dg, o, t.direction)
            if not hit:
                break
            if ob is None or ob.original.name not in skip:
                return loc
            o = loc + t.direction * 1e-4
    except Exception:
        pass
    if abs(t.direction.z) > 1e-4:
        p = geometry.intersect_line_plane(t.origin, t.origin + t.direction, Vector((0, 0, 0)), Vector((0, 0, 1)))
        if p is not None and (p - t.origin).dot(t.direction) > 0:
            return p
    cur = bpy.context.scene.cursor.location
    fwd = t.rv3d.view_rotation @ Vector((0, 0, -1))
    p = geometry.intersect_line_plane(t.origin, t.origin + t.direction, cur, fwd)
    return p if p is not None else cur.copy()


def _bottom(ob):
    """Lowest world Z of the object's bounding box (Blender sets dropped objects on the surface)."""
    from mathutils import Vector
    try:
        mw = ob.matrix_world
        return min((mw @ Vector(c)).z for c in ob.bound_box)
    except Exception:
        return ob.matrix_world.translation.z


def drop_view3d(t, ids):
    """Blender's 3D view drop of these datablocks at target t. Returns True when something happened."""
    done = []
    moved = []
    for i in ids:
        typ = i.id_type
        try:
            if typ == "OBJECT":
                moved.append(i)
            elif typ == "COLLECTION":
                loc = _location(t)
                with t.context():
                    bpy.ops.object.collection_instance_add(session_uid=i.session_uid, location=loc,
                                                           align="WORLD")
                done.append(f"instance of {i.name}")
            elif typ in DATA_TYPES:
                loc = _location(t)
                with t.context():
                    bpy.ops.object.data_instance_add(session_uid=i.session_uid, type=typ, location=loc,
                                                     align="WORLD")
                done.append(f"object with {i.name}")
            elif typ == "MATERIAL":
                ob = _object_under(t)
                if ob is not None and hasattr(ob.data, "materials"):
                    ob.active_material = i
                    done.append(f"{i.name} → {ob.name}")
            elif typ == "NODETREE" and getattr(i, "bl_idname", "") == "GeometryNodeTree":
                ob = _object_under(t)
                if ob is not None and ob.type in ("MESH", "CURVE", "CURVES", "POINTCLOUD", "VOLUME",
                                                  "GREASEPENCIL", "FONT", "SURFACE"):
                    mod = ob.modifiers.new(i.name, "NODES")
                    mod.node_group = i
                    done.append(f"{i.name} modifier → {ob.name}")
            elif typ == "IMAGE":
                loc = _location(t)
                with t.context():
                    bpy.ops.object.empty_image_add(session_uid=i.session_uid, align="VIEW", location=loc)
                done.append(f"image empty {i.name}")
            elif typ == "WORLD":
                bpy.context.scene.world = i
                done.append(f"world {i.name}")
        except Exception as ex:
            bridge.log(f"Drop {i.name}: {ex}", "WARNING")
    if moved:
        try:
            # like Blender: the first object lands on the surface under the mouse (its bounding box bottom on
            # it), the others keep their places to it; the dropped objects become the selection
            first = moved[0]
            loc = _location(t, exclude=moved)
            mw = first.matrix_world.copy()
            delta = loc - mw.translation
            delta.z += mw.translation.z - _bottom(first)
            vl = bpy.context.view_layer
            for o in vl.objects:
                if o.select_get(view_layer=vl) and o not in moved:
                    o.select_set(False, view_layer=vl)
            for ob in moved:
                if ob.parent is not None and ob.parent in moved:
                    continue                  # children follow their parent
                ob.matrix_world.translation = ob.matrix_world.translation + delta
                try:
                    ob.select_set(True, view_layer=vl)
                except Exception:
                    pass
            try:
                vl.objects.active = first
            except Exception:
                pass
            done.append(", ".join(o.name for o in moved[:3]) + " moved")
        except Exception as ex:
            bridge.log(f"Drop {moved[0].name}: {ex}", "WARNING")
    if done:
        bridge.undo_push("Drop " + ids[0].name)
        _status("Dropped: " + "; ".join(done))
    elif ids:
        _status(f"Nothing to drop {ids[0].name} on here.")
    return bool(done)


def drop_qt_view(vp, pos, ids):
    t = _qt_view_target(vp, pos)
    if t is None:
        return False
    ok = drop_view3d(t, ids)
    vp.request_redraw()
    vp.update()
    return ok


def view3d_accepts(ids):
    return any(i.id_type in ("OBJECT", "COLLECTION", "MATERIAL", "IMAGE", "WORLD") or i.id_type in DATA_TYPES
               or (i.id_type == "NODETREE" and getattr(i, "bl_idname", "") == "GeometryNodeTree") for i in ids)


# ---------------------------------------------------------------- node editor
def node_for(tree, i):
    """(node type, setup function) for dropping datablock i into tree, or None (like Blender's node dropboxes)."""
    tt = getattr(tree, "bl_idname", "")
    typ = i.id_type
    gn = tt == "GeometryNodeTree"
    if typ == "OBJECT" and gn:
        return "GeometryNodeObjectInfo", lambda n: setattr(n.inputs["Object"], "default_value", i)
    if typ == "COLLECTION" and gn:
        return "GeometryNodeCollectionInfo", lambda n: setattr(n.inputs["Collection"], "default_value", i)
    if typ == "MATERIAL" and gn:
        return "GeometryNodeInputMaterial", lambda n: setattr(n, "material", i)
    if typ == "IMAGE":
        if gn:
            return "GeometryNodeInputImage", lambda n: setattr(n, "image", i)
        if tt == "ShaderNodeTree":
            return "ShaderNodeTexImage", lambda n: setattr(n, "image", i)
        if tt == "CompositorNodeTree":
            return "CompositorNodeImage", lambda n: setattr(n, "image", i)
    if typ == "MASK" and tt == "CompositorNodeTree":
        return "CompositorNodeMask", lambda n: setattr(n, "mask", i)
    if typ == "NODETREE" and getattr(i, "bl_idname", "") == tt and i != tree:
        group = {"GeometryNodeTree": "GeometryNodeGroup", "ShaderNodeTree": "ShaderNodeGroup",
                 "CompositorNodeTree": "CompositorNodeGroup"}.get(tt)
        if group:
            return group, lambda n: setattr(n, "node_tree", i)
    return None


def node_editor_accepts(tree, ids):
    return tree is not None and any(node_for(tree, i) for i in ids)


def drop_node_editor(editor, scene_pos, ids):
    """Adds the nodes for the dropped datablocks at scene_pos (stacked), selects them, one undo step."""
    tree = editor.tree
    if tree is None:
        return []
    made = []
    x, y = scene_pos.x(), -scene_pos.y()
    for k, i in enumerate(ids):
        spec = node_for(tree, i)
        if spec is None:
            continue
        ident, setup = spec
        try:
            n = tree.nodes.new(ident)
            setup(n)
            n.location = (x, y - 160 * len(made))
            made.append(n.name)
        except Exception as ex:
            bridge.log(f"Drop {i.name}: {ex}", "WARNING")
    if made:
        for o in tree.nodes:
            o.select = o.name in made
        tree.nodes.active = tree.nodes[made[-1]]
        bridge.undo_push("Drop " + ids[0].name)
        _status("Added: " + ", ".join(made))
    else:
        _status(f"{ids[0].name} can't be dropped into this node tree." if ids else "")
    return made


# ---------------------------------------------------------------- ID fields
def field_accepts(rp, ids):
    """A pointer property (rp = RNA property) accepts the first dropped datablock of its type."""
    try:
        want = rp.fixed_type
    except Exception:
        return None
    cls = getattr(bpy.types, want.identifier, None)
    for i in ids:
        if cls is not None and isinstance(i, cls):
            return i
    return None


def _status(text):
    try:
        from . import app
        app._win.statusBar().showMessage(text, 4000)
    except Exception:
        pass

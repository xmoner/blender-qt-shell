"""Node editor in Qt (QGraphicsView): shader, world, Geometry Nodes, compositor.

Nodes, sockets and links are drawn from Blender's data (node_tree.nodes / links). Edits are written
straight back to RNA: moving (node.location), linking (links.new / remove), adding and deleting nodes,
values of unconnected inputs and node properties in the sidebar.
"""
import traceback

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, pytips, rna_widgets as rw, theme

NE_PY = "import qt_shell\nne = qt_shell.api.main_window().node_editor\nne."   # Python tooltips
from .bridge import tr

ROW_H = 22
HEADER_H = 24
SOCK_R = 5.0
MULTI_STEP = 10.0        # distance between the links of a multi-input socket (Blender: NODE_DYS)


def multi_links(sock):
    """Links into a multi-input socket in Blender's order: ascending multi_input_sort_id (the highest is drawn
    at the top)."""
    try:
        lks = list(sock.links)
    except Exception:
        return []
    return sorted(lks, key=lambda l: getattr(l, "multi_input_sort_id", 0))


def multi_offset(rank, total):
    """y offset (Qt, down = +) of link number rank of total from the socket's centre – Blender's
    node_link_calculate_multi_input_position: rank 0 at the bottom, the last one at the top."""
    return (total - 1) * MULTI_STEP / 2.0 - rank * MULTI_STEP

SOCKET_COLORS = {
    "SHADER": "#63c763", "RGBA": "#c7c729", "VALUE": "#a1a1a1", "VECTOR": "#6363c7",
    "GEOMETRY": "#00d6a3", "INT": "#598c5c", "BOOLEAN": "#cca6d6", "STRING": "#70b2ff",
    "OBJECT": "#ed9e5c", "MATERIAL": "#eb7582", "IMAGE": "#633863", "COLLECTION": "#f5f5f5",
    "TEXTURE": "#9e4fa3", "ROTATION": "#a663c7", "MENU": "#4d4d4d", "MATRIX": "#4a7a9c",
    "CUSTOM": "#888888",
}
HEADER_RULES = [
    (("Output", "Viewer", "Composite"), "#83314a"),
    (("Bsdf", "Emission", "Holdout", "VolumeAbsorption", "VolumeScatter", "VolumePrincipled",
      "Background", "AddShader", "MixShader", "Eevee", "SubsurfaceScattering", "Toon"), "#2b652b"),
    (("TexImage", "TexNoise", "TexVoronoi", "TexWave", "TexChecker", "TexBrick", "TexGradient",
      "TexMagic", "TexMusgrave", "TexSky", "TexEnvironment", "TexWhiteNoise", "TexGabor",
      "TexIES", "TexPointDensity"), "#79461d"),
    (("Mix", "RGBCurve", "HueSat", "BrightContrast", "Gamma", "Invert", "ValToRGB", "LightFalloff",
      "RGBToBW"), "#6c6c22"),
    (("Vector", "Mapping", "Normal", "Bump", "Displacement", "Tangent"), "#3b3b7a"),
    (("Math", "MapRange", "Clamp", "Separate", "Combine", "FloatCurve", "Compare", "Boolean",
      "Switch", "Random", "Integer", "Blackbody", "Wavelength"), "#246283"),
    (("Group",), "#3b5f3b"),
    (("GeometryNode", "Mesh", "Curve", "Points", "Instance", "Realize", "Join", "Transform",
      "SetPosition", "Store", "Capture"), "#1d6d5f"),
    (("Input", "Attribute", "TexCoord", "UVMap", "Value", "RGB", "ObjectInfo", "CameraData",
      "LightPath", "Fresnel", "LayerWeight", "Wireframe", "NewGeometry", "Object", "Collection",
      "Image"), "#83314a"),
]


def _qcolor(hexstr):
    return QtGui.QColor(hexstr)


def socket_color(sock):
    return _qcolor(SOCKET_COLORS.get(getattr(sock, "type", "VALUE"), "#888888"))


def header_color(node):
    if getattr(node, "use_custom_color", False):
        c = node.color
        return QtGui.QColor.fromRgbF(c[0], c[1], c[2])
    idn = node.bl_idname
    for keys, col in HEADER_RULES:
        if any(k in idn for k in keys):
            return _qcolor(col)
    return _qcolor("#3d3d3d")


def abs_location(node):
    x, y = node.location
    p = node.parent
    while p is not None:
        x += p.location[0]
        y += p.location[1]
        p = p.parent
    return x, y


def node_title(node):
    if node.label:
        return node.label
    if node.bl_idname.endswith("Group") and getattr(node, "node_tree", None) is not None:
        return node.node_tree.name
    return tr(node.bl_rna.name) or node.name


def value_text(sock):
    if not hasattr(sock, "default_value"):
        return ""
    v = sock.default_value
    try:
        if isinstance(v, bool):
            return "✓" if v else "✗"
        if isinstance(v, float):
            return f"{v:.3f}"
        if isinstance(v, int):
            return str(v)
        if isinstance(v, str):
            return v[:14]
        if hasattr(v, "name"):
            return v.name
        if hasattr(v, "__len__") and getattr(sock, "type", "") != "RGBA":
            return "(" + ", ".join(f"{x:.2g}" for x in list(v)[:4]) + ")"
    except Exception:
        return ""
    return ""


_BASE_NODE_PROPS = None


def base_node_props():
    global _BASE_NODE_PROPS
    if _BASE_NODE_PROPS is None:
        _BASE_NODE_PROPS = set(bpy.types.Node.bl_rna.properties.keys()) | {"rna_type"}
    return _BASE_NODE_PROPS


def node_buttons(node):
    """Editable node properties shown directly in the node (enums, ID pointers)."""
    out = []
    for p in node.bl_rna.properties:
        if p.identifier in base_node_props() or p.is_readonly:
            continue
        if p.type == "ENUM" or (p.type == "POINTER" and p.fixed_type is not None and rw.is_id_type(p.fixed_type)):
            out.append(p)
    return out


def socket_ptrs(node):
    """Pointers of the node's sockets. Blender rebuilds the sockets of many nodes when a property changes
    (Random Value / Math / Switch … Data Type): the old socket structs are freed and their Python objects are
    NOT invalidated – reading one (default_value, name …) reads freed memory and crashes Blender. A change of
    this tuple means: every kept socket object of this node is stale."""
    try:
        return (tuple(x.as_pointer() for x in node.inputs), tuple(x.as_pointer() for x in node.outputs))
    except Exception:
        return None


_TREE_UI = {"ShaderNodeTree": "ShaderNodeTree", "GeometryNodeTree": "GeometryNodeTree",
            "CompositorNodeTree": "CompositorNodeTree", "TextureNodeTree": "TextureNodeTree"}


class node_space_context:
    """A node editor area of a hidden Blender window showing (pinned) tree – for bpy.ops.node.* (an area is
    borrowed and switched back afterwards)."""

    def __init__(self, tree):
        self.tree = tree

    def __enter__(self):
        if not bridge.ensure_view3d():
            raise RuntimeError("No Blender window.")
        win, area = bridge.spare_area(("DOPESHEET_EDITOR", "GRAPH_EDITOR", "IMAGE_EDITOR"))
        if area is None:
            raise RuntimeError("No Blender editor area to borrow for node operators.")
        self.area, self.old = area, area.ui_type
        area.ui_type = _TREE_UI.get(self.tree.bl_idname, self.tree.bl_idname)
        sp = area.spaces.active
        self.old_pin = sp.pin
        sp.pin = True
        sp.node_tree = self.tree
        region = next(r for r in area.regions if r.type == "WINDOW")
        self._ov = bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region,
                                             space_data=sp)
        self._ov.__enter__()
        return self

    def __exit__(self, *exc):
        try:
            self._ov.__exit__(*exc)
        finally:
            try:
                sp = self.area.spaces.active
                sp.pin = self.old_pin
                self.area.ui_type = self.old
            except Exception:
                pass
        return False


def _copy_nodes(tree, names):
    """Fallback duplicate in Python (when Blender's operator can't run): node type, settings, input values,
    links between the copied nodes."""
    skip = set(base_node_props()) | {"name", "location", "select", "parent", "location_absolute"}
    made = {}
    for nm in names:
        src = tree.nodes.get(nm)
        if src is None:
            continue
        try:
            dst = tree.nodes.new(src.bl_idname)
        except Exception:
            continue
        for p in src.bl_rna.properties:
            if p.is_readonly or p.identifier in skip or p.type == "COLLECTION":
                continue
            try:
                setattr(dst, p.identifier, getattr(src, p.identifier))
            except Exception:
                pass
        for attr in ("label", "width", "hide", "mute", "use_custom_color", "color"):
            try:
                setattr(dst, attr, getattr(src, attr))
            except Exception:
                pass
        dst.location = (src.location[0] + 40, src.location[1] - 40)
        for a, b in zip(src.inputs, dst.inputs):
            if hasattr(a, "default_value") and hasattr(b, "default_value"):
                try:
                    b.default_value = a.default_value
                except Exception:
                    pass
        made[nm] = dst
    for lk in list(tree.links):
        a, b = made.get(lk.from_node.name), made.get(lk.to_node.name)
        if a is None or b is None:
            continue
        try:
            fo = next(x for x in a.outputs if x.identifier == lk.from_socket.identifier)
            ti = next(x for x in b.inputs if x.identifier == lk.to_socket.identifier)
            tree.links.new(fo, ti)
        except Exception:
            pass
    return bool(made)


def new_link(tree, out_s, in_s):
    """links.new like Blender's node editor: a link to the empty (virtual) socket of a Group Input / Group
    Output – or of a node with dynamic sockets (Bake, Capture Attribute, zones …) – adds the matching socket
    first (handle_dynamic_sockets, Blender 4.1+); without it the link goes to the virtual socket and is red."""
    try:
        return tree.links.new(out_s, in_s, handle_dynamic_sockets=True)
    except TypeError:
        return tree.links.new(out_s, in_s)


GROUP_ITEM_PROPS = ("name", "description", "default_value", "min_value", "max_value",
                    "default_attribute_name", "attribute_domain", "default_input", "hide_value", "hide_in_modifier",
                    "force_non_field", "optional_label", "default_closed")
# group socket types per tree type (socket_type's enum items need Blender's UI context – empty from Python)
GROUP_SOCKET_TYPES = {
    "GeometryNodeTree": ("Float", "Integer", "Boolean", "Vector", "Rotation", "Matrix", "Color", "String", "Menu",
                         "Object", "Collection", "Image", "Material", "Geometry"),
    "ShaderNodeTree": ("Float", "Integer", "Boolean", "Vector", "Color", "Shader"),
    "CompositorNodeTree": ("Float", "Integer", "Boolean", "Vector", "Color", "Menu"),
}
SOCKET_IDNAMES = {"Float": "NodeSocketFloat", "Integer": "NodeSocketInt", "Boolean": "NodeSocketBool",
                  "Vector": "NodeSocketVector", "Rotation": "NodeSocketRotation", "Matrix": "NodeSocketMatrix",
                  "Color": "NodeSocketColor", "String": "NodeSocketString", "Menu": "NodeSocketMenu",
                  "Object": "NodeSocketObject", "Collection": "NodeSocketCollection", "Image": "NodeSocketImage",
                  "Material": "NodeSocketMaterial", "Geometry": "NodeSocketGeometry", "Shader": "NodeSocketShader"}
_IFACE_TYPES = (("Float", "VALUE"), ("Int", "INT"), ("Bool", "BOOLEAN"), ("Vector", "VECTOR"), ("Color", "RGBA"),
                ("String", "STRING"), ("Geometry", "GEOMETRY"), ("Object", "OBJECT"), ("Collection", "COLLECTION"),
                ("Material", "MATERIAL"), ("Image", "IMAGE"), ("Texture", "TEXTURE"), ("Rotation", "ROTATION"),
                ("Matrix", "MATRIX"), ("Menu", "MENU"), ("Shader", "SHADER"))


def _iface_icon(item):
    """A socket-coloured dot for an interface item (by its socket type), arrow-ish for outputs."""
    st = getattr(item, "socket_type", "") or ""
    key = next((v for k, v in _IFACE_TYPES if k in st), "CUSTOM")
    size = theme.px(14)
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    try:
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setBrush(_qcolor(SOCKET_COLORS.get(key, "#888888")))
        p.setPen(QtGui.QPen(QtGui.QColor("#111111"), 1))
        r = size * 0.3
        c = QtCore.QPointF(size / 2, size / 2)
        p.drawEllipse(c, r, r)
        if getattr(item, "in_out", "") == "OUTPUT":
            p.setPen(QtGui.QPen(QtGui.QColor("#dddddd"), 1.2))
            p.drawLine(QtCore.QPointF(size - 2, size / 2 - 3), QtCore.QPointF(size - 2, size / 2 + 3))
    finally:
        p.end()
    return QtGui.QIcon(pm)


# ---------------------------------------------------------------- graphics items
class NodeItem(QtWidgets.QGraphicsItem):
    def __init__(self, editor, node):
        super().__init__()
        self.editor = editor
        self._node = node
        self.name = node.name
        self._ptr = node.as_pointer()
        self.kind = "reroute" if node.bl_idname == "NodeReroute" else (
            "frame" if node.bl_idname == "NodeFrame" else "node")
        self.setFlags(QtWidgets.QGraphicsItem.ItemIsMovable | QtWidgets.QGraphicsItem.ItemIsSelectable
                      | QtWidgets.QGraphicsItem.ItemSendsGeometryChanges)
        self.sockets = {}   # (is_output, identifier) -> (QPointF, socket)
        self.multi = {}     # identifier of a multi-input socket -> number of slots (its links, at least 1)
        self.rows = []
        self._build()
        x, y = abs_location(node)
        self.setPos(x, -y)
        self.setZValue(-10 if self.kind == "frame" else 0)
        self.setSelected(bool(node.select))

    def _build(self):
        node = self._node
        self.rows = []
        self.sockets = {}
        self.multi = {}
        self._sock_ptrs = socket_ptrs(node)
        if self.kind == "reroute":
            self.w, self.h = 16.0, 16.0
            c = QtCore.QPointF(8, 8)
            for s in node.inputs:
                self.sockets[(False, s.identifier)] = (c, s)
            for s in node.outputs:
                self.sockets[(True, s.identifier)] = (c, s)
            return
        if self.kind == "frame":
            self.w = max(float(node.width), 60.0)
            self.h = max(float(getattr(node, "height", 100.0)), 40.0)
            return
        self.w = max(float(node.width), 80.0)
        ins = [s for s in node.inputs if getattr(s, "enabled", True) and not s.hide]
        outs = [s for s in node.outputs if getattr(s, "enabled", True) and not s.hide]
        if node.hide:
            self.h = float(HEADER_H)
            for i, s in enumerate(outs):
                self.sockets[(True, s.identifier)] = (QtCore.QPointF(self.w, HEADER_H / 2 + i * 3), s)
            for i, s in enumerate(ins):
                self.sockets[(False, s.identifier)] = (QtCore.QPointF(0, HEADER_H / 2 + i * 3), s)
            return
        y = HEADER_H + 4
        for s in outs:
            self.rows.append(("out", s, y))
            self.sockets[(True, s.identifier)] = (QtCore.QPointF(self.w, y + ROW_H / 2), s)
            y += ROW_H
        for p in node_buttons(node):
            self.rows.append(("prop", p, y))
            y += ROW_H
        for s in ins:
            hh = ROW_H
            if getattr(s, "is_multi_input", False):
                # Blender: an oval that grows with every link, each link has its own place on it
                n = max(1, len(s.links))
                self.multi[s.identifier] = n
                hh = ROW_H + (n - 1) * MULTI_STEP
            self.rows.append(("in", s, y))
            self.sockets[(False, s.identifier)] = (QtCore.QPointF(0, y + hh / 2), s)
            y += hh
        self.h = y + 6

    def boundingRect(self):
        return QtCore.QRectF(-SOCK_R - 2, -2, self.w + 2 * SOCK_R + 4, self.h + 4)

    @property
    def node(self):
        """The Blender node – None once it was removed (never the stale Python object: reading or writing it
        crashes Blender)."""
        return self._node if self.alive() else None

    def sockets_ok(self):
        """True while the sockets kept in rows / sockets are still the node's (see socket_ptrs)."""
        return self.alive() and socket_ptrs(self._node) == self._sock_ptrs

    def alive(self):
        """False when the node was removed meanwhile (a script, undo, the Image editor's animation cache): node
        structs are no IDs, so the Python object of a removed node is not invalidated – reading it reads freed
        memory and crashes Blender. The tree (an ID) is asked by name and the pointer compared instead."""
        tree = self.editor.tree
        try:
            cur = tree.nodes.get(self.name) if tree is not None else None
            return cur is not None and cur.as_pointer() == self._ptr
        except ReferenceError:
            return False

    def paint(self, p, _opt, _w):
        node = self.node
        if node is None or (self.kind != "frame" and not self.sockets_ok()):
            # removed, or its sockets were rebuilt (Data Type changed …): never touch the old socket objects –
            # rebuild from the tree as it is now
            self.editor._timer.start()
            return
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        sel = self.isSelected()
        active = self.editor.active_name == self.name
        outline = QtGui.QColor("#ffffff") if active else (QtGui.QColor("#ffa033") if sel else QtGui.QColor("#111111"))
        if self.kind == "frame":
            c = header_color(node) if node.use_custom_color else QtGui.QColor(60, 60, 60)
            c.setAlpha(110)
            p.setPen(QtGui.QPen(outline, 1.5))
            p.setBrush(c)
            p.drawRoundedRect(QtCore.QRectF(0, 0, self.w, self.h), 4, 4)
            p.setPen(QtGui.QColor("#dddddd"))
            p.drawText(QtCore.QRectF(6, 2, self.w - 12, 20), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                       node.label or node.name)
            return
        if self.kind == "reroute":
            col = socket_color(node.outputs[0]) if len(node.outputs) else QtGui.QColor("#888")
            p.setPen(QtGui.QPen(outline, 1.5))
            p.setBrush(col)
            p.drawEllipse(QtCore.QPointF(8, 8), 6, 6)
            return
        body = QtCore.QRectF(0, 0, self.w, self.h)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#303030"))
        p.drawRoundedRect(body, 5, 5)
        head = header_color(node)
        if node.mute:
            head = QtGui.QColor("#5a2a2a")
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(0, 0, self.w, HEADER_H), 5, 5)
        if not node.hide:
            path.addRect(QtCore.QRectF(0, HEADER_H / 2, self.w, HEADER_H / 2))
        p.fillPath(path.simplified(), head)
        p.setPen(QtGui.QPen(outline, 2 if (sel or active) else 1))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(body, 5, 5)
        f = p.font()
        f.setPixelSize(12)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QtGui.QColor("#eeeeee"))
        title = ("▸ " if node.hide else "▾ ") + node_title(node)
        p.drawText(QtCore.QRectF(8, 0, self.w - 16, HEADER_H), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                   p.fontMetrics().elidedText(title, QtCore.Qt.ElideRight, int(self.w - 16)))
        f.setPixelSize(11)
        p.setFont(f)
        for kind, obj, y in self.rows:
            r = QtCore.QRectF(10, y, self.w - 20, ROW_H)
            if kind == "in" and obj.identifier in self.multi:
                r = QtCore.QRectF(10, y, self.w - 20, ROW_H + (self.multi[obj.identifier] - 1) * MULTI_STEP)
            try:
                if kind == "out":
                    p.setPen(QtGui.QColor("#dddddd"))
                    p.drawText(r, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, tr(obj.name))
                elif kind == "prop":
                    val = getattr(node, obj.identifier)
                    if hasattr(val, "name"):
                        val = val.name
                    elif obj.type == "ENUM" and not obj.is_enum_flag:
                        val = next((tr(e.name) for e in obj.enum_items if e.identifier == val), val)
                    box = QtCore.QRectF(8, y + 2, self.w - 16, ROW_H - 4)
                    p.setPen(QtCore.Qt.NoPen)
                    p.setBrush(QtGui.QColor("#545454"))
                    p.drawRoundedRect(box, 3, 3)
                    p.setPen(QtGui.QColor("#e0e0e0"))
                    p.drawText(box.adjusted(6, 0, -6, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                               p.fontMetrics().elidedText(str(val or "—"), QtCore.Qt.ElideRight, int(box.width() - 12)))
                else:
                    linked = obj.is_linked
                    p.setPen(QtGui.QColor("#dddddd"))
                    if not linked and hasattr(obj, "default_value") and not getattr(obj, "hide_value", False):
                        if getattr(obj, "type", "") == "RGBA":
                            c = obj.default_value
                            sw = QtCore.QRectF(self.w - 46, y + 4, 36, ROW_H - 8)
                            p.setBrush(QtGui.QColor.fromRgbF(min(max(rw.lin_to_srgb(c[0]), 0), 1),
                                                             min(max(rw.lin_to_srgb(c[1]), 0), 1),
                                                             min(max(rw.lin_to_srgb(c[2]), 0), 1)))
                            p.setPen(QtGui.QColor("#111"))
                            p.drawRoundedRect(sw, 3, 3)
                            p.setPen(QtGui.QColor("#dddddd"))
                            p.drawText(r.adjusted(0, 0, -44, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, tr(obj.name))
                        else:
                            box = QtCore.QRectF(8, y + 2, self.w - 16, ROW_H - 4)
                            p.setPen(QtCore.Qt.NoPen)
                            p.setBrush(QtGui.QColor("#4a4a4a"))
                            p.drawRoundedRect(box, 3, 3)
                            p.setPen(QtGui.QColor("#dddddd"))
                            p.drawText(box.adjusted(6, 0, -6, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, tr(obj.name))
                            p.drawText(box.adjusted(6, 0, -6, 0), QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, value_text(obj))
                    else:
                        p.drawText(r, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, tr(obj.name))
            except ReferenceError:
                return
        for (is_out, ident), (pt, s) in self.sockets.items():
            p.setPen(QtGui.QPen(QtGui.QColor("#111111"), 1))
            p.setBrush(socket_color(s))
            shape = str(getattr(s, "display_shape", "CIRCLE"))
            if not is_out and ident in self.multi:
                p.drawRoundedRect(self.multi_rect(ident, pt), SOCK_R, SOCK_R)
            elif shape.startswith("DIAMOND"):
                poly = QtGui.QPolygonF([pt + QtCore.QPointF(0, -SOCK_R - 1), pt + QtCore.QPointF(SOCK_R + 1, 0),
                                        pt + QtCore.QPointF(0, SOCK_R + 1), pt + QtCore.QPointF(-SOCK_R - 1, 0)])
                p.drawPolygon(poly)
            elif shape.startswith("SQUARE"):
                p.drawRect(QtCore.QRectF(pt.x() - SOCK_R, pt.y() - SOCK_R, 2 * SOCK_R, 2 * SOCK_R))
            else:
                p.drawEllipse(pt, SOCK_R, SOCK_R)
            if shape.endswith("_DOT"):
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(QtGui.QColor("#111111"))
                p.drawEllipse(pt, 1.6, 1.6)

    def multi_rect(self, ident, pt=None):
        """The oval of a multi-input socket (local coordinates): one slot per link, a bit taller than a round
        socket even with one link so it reads as 'more links fit here'."""
        if pt is None:
            pt = self.sockets[(False, ident)][0]
        n = self.multi.get(ident, 1)
        h = (n - 1) * MULTI_STEP + SOCK_R * 3.0
        return QtCore.QRectF(pt.x() - SOCK_R, pt.y() - h / 2, 2 * SOCK_R, h)

    def socket_at(self, scene_pos):
        if not self.sockets_ok():
            self.editor._timer.start()
            return None
        local = self.mapFromScene(scene_pos)
        for ident in self.multi:
            if self.multi_rect(ident).adjusted(-SOCK_R, -SOCK_R / 2, SOCK_R, SOCK_R / 2).contains(local):
                return False, self.sockets[(False, ident)][1]
        for (is_out, ident), (pt, s) in self.sockets.items():
            if (pt - local).manhattanLength() <= SOCK_R * 2.6:
                return is_out, s
        return None

    def socket_scene_pos(self, is_out, ident):
        item = self.sockets.get((is_out, ident))
        if item is None:
            return None
        return self.mapToScene(item[0])

    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.ItemPositionHasChanged:
            self.editor.update_links()
        return super().itemChange(change, value)


# ---------------------------------------------------------------- insert a node into a link (like Blender)
NUMERIC_SOCKETS = {"VALUE", "INT", "BOOLEAN", "VECTOR", "RGBA", "ROTATION"}


def _usable(sock):
    return (getattr(sock, "enabled", True) and not getattr(sock, "hide", False)
            and not getattr(sock, "is_unavailable", False) and getattr(sock, "type", "") != "CUSTOM")


def main_socket(sockets, stype):
    """The socket a link of type stype goes to when a node is dropped on it: the first visible socket of the
    same type, else (numbers, vectors, colours) the first visible socket that converts."""
    vis = [x for x in sockets if _usable(x)]
    for x in vis:
        if x.type == stype:
            return x
    if stype in NUMERIC_SOCKETS:
        for x in vis:
            if x.type in NUMERIC_SOCKETS:
                return x
    return None


def node_is_free(node):
    """Blender inserts only nodes that have no links yet."""
    try:
        return not any(x.is_linked for x in node.inputs) and not any(x.is_linked for x in node.outputs)
    except Exception:
        return False


class LinkItem(QtWidgets.QGraphicsPathItem):
    def __init__(self, link, a_item, b_item):
        super().__init__()
        self._key = (link.from_node.name, link.from_socket.identifier, link.to_node.name,
                     link.to_socket.identifier)
        self.a = (a_item, link.from_socket.identifier)
        self.b = (b_item, link.to_socket.identifier)
        self.slot = (0, 1)              # (rank, total) on a multi-input socket
        try:
            if getattr(link.to_socket, "is_multi_input", False):
                lks = multi_links(link.to_socket)
                key = (link.from_node.name, link.from_socket.identifier)
                rank = next((i for i, l in enumerate(lks)
                             if (l.from_node.name, l.from_socket.identifier) == key), 0)
                self.slot = (rank, max(1, len(lks)))
        except Exception:
            pass
        col = socket_color(link.from_socket)
        pen = QtGui.QPen(col, 2.2)
        if getattr(link, "is_muted", False):
            pen.setColor(QtGui.QColor("#aa4444"))
            pen.setStyle(QtCore.Qt.DashLine)
        elif not getattr(link, "is_valid", True):
            pen.setColor(QtGui.QColor("#ff3333"))
        self.setPen(pen)
        self._pen = QtGui.QPen(pen)
        self.setZValue(-1)
        self.update_path()

    @property
    def link(self):
        """The Blender link, looked up in the tree now (None when gone) – a kept link object can point at freed
        memory after its nodes rebuilt their sockets."""
        tree = self.a[0].editor.tree
        if tree is None:
            return None
        fn, fs, tn, ts = self._key
        for lk in tree.links:
            if (lk.from_node.name == fn and lk.to_node.name == tn and lk.from_socket.identifier == fs
                    and lk.to_socket.identifier == ts):
                return lk
        return None

    def set_highlight(self, on):
        """White and thicker while a dragged node would be inserted into this link (like Blender)."""
        if on:
            self.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 3.6))
            self.setZValue(1)
        else:
            self.setPen(self._pen)
            self.setZValue(-1)

    def update_path(self):
        p1 = self.a[0].socket_scene_pos(True, self.a[1])
        p2 = self.b[0].socket_scene_pos(False, self.b[1])
        if p2 is not None and self.slot[1] > 1:
            p2 = p2 + QtCore.QPointF(0, multi_offset(*self.slot))
        if p1 is None or p2 is None:
            self.setPath(QtGui.QPainterPath())
            return
        self.setPath(bezier(p1, p2))


def bezier(p1, p2):
    path = QtGui.QPainterPath(p1)
    dx = max(abs(p2.x() - p1.x()) * 0.5, 40)
    path.cubicTo(p1 + QtCore.QPointF(dx, 0), p2 - QtCore.QPointF(dx, 0), p2)
    return path


# ---------------------------------------------------------------- view
class NodeView(QtWidgets.QGraphicsView):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing)
        self.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setBackgroundBrush(QtGui.QColor("#1d1d1d"))
        self._pan = None
        self._drag_link = None   # (node name, is_out, socket identifier, temp_path_item) – never the socket object
        self._moving = False
        self._grab = None        # a new node following the mouse until a click (like Blender after Shift+A)
        self._insert_li = None   # the link a dragged node would be inserted into (highlighted)
        self.viewport().setMouseTracking(True)
        self.setAcceptDrops(True)          # datablocks from the Outliner / Properties → nodes (iddrop)

    def dragEnterEvent(self, ev):
        from . import iddrop
        if iddrop.node_editor_accepts(self.editor.tree, iddrop.decode(ev.mimeData())):
            ev.setDropAction(QtCore.Qt.CopyAction)
            ev.accept()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev):
        ev.setDropAction(QtCore.Qt.CopyAction)
        ev.accept()

    def dropEvent(self, ev):
        from . import iddrop
        ids = iddrop.decode(ev.mimeData())
        sp = self.mapToScene(ev.position().toPoint())
        ev.setDropAction(QtCore.Qt.CopyAction)
        ev.accept()
        QtCore.QTimer.singleShot(0, lambda: (iddrop.drop_node_editor(self.editor, sp, ids),
                                             self.editor.rebuild()))

    def drawBackground(self, p, rect):
        super().drawBackground(p, rect)
        step = 40
        left = int(rect.left()) - int(rect.left()) % step
        top = int(rect.top()) - int(rect.top()) % step
        p.setPen(QtGui.QPen(QtGui.QColor("#262626"), 1))
        x = left
        while x < rect.right():
            p.drawLine(QtCore.QLineF(x, rect.top(), x, rect.bottom()))
            x += step
        y = top
        while y < rect.bottom():
            p.drawLine(QtCore.QLineF(rect.left(), y, rect.right(), y))
            y += step

    def enterEvent(self, ev):
        fw = QtWidgets.QApplication.focusWidget()
        if not (isinstance(fw, QtWidgets.QLineEdit) and fw.text()):
            self.setFocus()
            from . import app as _app
            _app.hover_activate(self)      # floating dock = separate window; never over other windows
        super().enterEvent(ev)

    ZOOM_MIN, ZOOM_MAX = 0.03, 4.0

    def wheelEvent(self, ev):
        d = ev.angleDelta().y() or ev.angleDelta().x()
        if not d:
            d = ev.pixelDelta().y()           # touchpads
        if not d:
            return
        cur = self.transform().m11()
        # clamp instead of refusing: zooming always works, even from a view outside the range
        new = min(max(cur * 1.15 ** (d / 120.0), self.ZOOM_MIN), self.ZOOM_MAX)
        if abs(new / cur - 1.0) > 1e-4:
            self.scale(new / cur, new / cur)
        ev.accept()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if getattr(self.editor, "_frame_pending", False) and self._big_enough():
            self.editor._frame_pending = False
            QtCore.QTimer.singleShot(0, self.editor.frame_all)

    def showEvent(self, ev):
        super().showEvent(ev)
        if getattr(self.editor, "_frame_pending", False):
            QtCore.QTimer.singleShot(0, lambda: self._big_enough() and self.editor.frame_all())

    def _big_enough(self):
        return self.isVisible() and self.viewport().width() > 80 and self.viewport().height() > 60

    def _item_at(self, pos):
        for it in self.items(pos):
            if isinstance(it, NodeItem):
                return it
        return None

    # --- insert on link
    def _set_insert(self, li):
        if li is self._insert_li:
            return
        old = self._insert_li
        self._insert_li = li
        try:
            if old is not None:
                old.set_highlight(False)
        except RuntimeError:
            pass
        if li is not None:
            li.set_highlight(True)

    def insert_candidate(self, item, sp):
        """The link the node item would be inserted into at the cursor sp: links crossing the node's box whose
        types fit a free input and output of the node; the one nearest to the cursor."""
        node = item.node if item is not None else None
        if node is None or item.kind != "node" or not node_is_free(node):
            return None
        rect = item.sceneBoundingRect()
        stroker = QtGui.QPainterPathStroker()
        stroker.setWidth(6)
        best, best_d = None, None
        for li in self.editor.links:
            if li.a[0] is item or li.b[0] is item:
                continue
            path = li.path()
            if path.isEmpty() or not stroker.createStroke(path).intersects(rect):
                continue
            try:
                ft = li.link.from_socket.type
                tt = li.link.to_socket.type
            except Exception:
                continue
            if main_socket(node.inputs, ft) is None or main_socket(node.outputs, tt) is None:
                continue
            d = min(QtCore.QLineF(sp, path.pointAtPercent(i / 24.0)).length() for i in range(25))
            if best_d is None or d < best_d:
                best, best_d = li, d
        return best

    def _update_insert(self, item, sp, mods=None):
        if mods is not None and mods & QtCore.Qt.AltModifier:   # Alt: move without inserting (Blender)
            self._set_insert(None)
            return
        self._set_insert(self.insert_candidate(item, sp))

    # --- grab (a new node follows the mouse)
    def start_grab(self, item, items=None):
        """item (and the other items) follow the mouse until a click; only a single node is inserted into
        a link it is dropped on (like Blender)."""
        if item is None:
            return
        items = [x for x in (items or [item]) if x is not None]
        if item not in items:
            items.insert(0, item)
        off = QtCore.QPointF(item.boundingRect().width() / 2.0, 12)
        rel = [(x, QtCore.QPointF(x.pos() - item.pos())) for x in items]
        self._grab = {"item": item, "off": off, "rel": rel,
                      "orig": [(x, QtCore.QPointF(x.pos())) for x in items]}
        sp = self.mapToScene(self.mapFromGlobal(QtGui.QCursor.pos()))
        if self.viewport().rect().contains(self.mapFromGlobal(QtGui.QCursor.pos())):
            self._grab_place(sp)
        self._grab["start"] = [(x, QtCore.QPointF(x.pos())) for x in items]
        self.viewport().setCursor(QtCore.Qt.SizeAllCursor)
        self.setFocus()
        if len(items) == 1:
            self._update_insert(item, sp)

    def _grab_place(self, sp):
        base = sp - self._grab["off"]
        for x, r in self._grab["rel"]:
            x.setPos(base + r)

    def _grab_move(self, sp, mods=None):
        self._grab_place(sp)
        if len(self._grab["rel"]) == 1:
            self._update_insert(self._grab["item"], sp, mods)

    def end_grab(self, ok=True):
        g, self._grab = self._grab, None
        if g is None:
            return
        self.viewport().unsetCursor()
        item = g["item"]
        li = self._insert_li
        self._set_insert(None)
        if not ok:
            for x, pos in g["start"]:
                x.setPos(pos)
        self.editor.commit_positions()
        if ok and li is not None:
            self.editor.insert_on_link(item, li)

    def mousePressEvent(self, ev):
        if self._grab is not None:
            if ev.button() == QtCore.Qt.LeftButton:
                self.end_grab(True)
            elif ev.button() == QtCore.Qt.RightButton:
                self.end_grab(False)
            return
        if ev.button() == QtCore.Qt.MiddleButton:
            self._pan = ev.position()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            return
        if ev.button() == QtCore.Qt.LeftButton:
            sp = self.mapToScene(ev.position().toPoint())
            it = self._item_at(ev.position().toPoint())
            if it is not None:
                hit = it.socket_at(sp)
                if hit is not None:
                    self._start_link(it, hit[0], hit[1], sp)
                    return
                self.editor.set_active(it)
                self._moving = True
        super().mousePressEvent(ev)

    def _start_link(self, item, is_out, sock, sp):
        ntree = self.editor.tree
        if not is_out and sock.is_linked:
            # drag an existing link out of an input (a multi-input: the link nearest to the cursor)
            link = sock.links[0]
            if getattr(sock, "is_multi_input", False):
                lks = multi_links(sock)
                c = item.socket_scene_pos(False, sock.identifier)
                if lks and c is not None:
                    rank = min(range(len(lks)),
                               key=lambda i: abs(c.y() + multi_offset(i, len(lks)) - sp.y()))
                    link = lks[rank]
            # read everything needed BEFORE removing the link: removing it lets Blender update the nodes, and
            # socket / link objects kept from before may point to freed memory afterwards (crash)
            src_name, src_ident = link.from_node.name, link.from_socket.identifier
            color = socket_color(link.from_socket)
            ntree.links.remove(link)
            self.editor.dirty_structure()
            if self.editor.items.get(src_name) is None:
                return
            name, is_out, ident = src_name, True, src_ident
        else:
            name, ident, color = item.name, sock.identifier, socket_color(sock)
        path = QtWidgets.QGraphicsPathItem()
        path.setPen(QtGui.QPen(color, 2, QtCore.Qt.DashLine))
        path.setZValue(5)
        self.scene().addItem(path)
        self._drag_link = (name, is_out, ident, path)
        self._update_drag(sp)

    def _drag_socket(self, name, is_out, ident):
        """The socket a link drag started from, looked up again (never kept across Blender updates)."""
        tree = self.editor.tree
        node = tree.nodes.get(name) if tree is not None else None
        if node is None:
            return None
        return next((x for x in (node.outputs if is_out else node.inputs) if x.identifier == ident), None)

    def _update_drag(self, sp):
        name, is_out, ident, path = self._drag_link
        item = self.editor.items.get(name)
        a = None
        if item is not None:
            try:
                a = item.socket_scene_pos(is_out, ident)
            except RuntimeError:
                a = None
        a = a or sp
        path.setPath(bezier(a, sp) if is_out else bezier(sp, a))

    def mouseMoveEvent(self, ev):
        if self._pan is not None:
            d = ev.position() - self._pan
            self._pan = ev.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        if self._drag_link is not None:
            self._update_drag(self.mapToScene(ev.position().toPoint()))
            return
        if self._grab is not None:
            self._grab_move(self.mapToScene(ev.position().toPoint()), ev.modifiers())
            return
        super().mouseMoveEvent(ev)
        if self._moving and ev.buttons() & QtCore.Qt.LeftButton:
            sel = [it for it in self.scene().selectedItems() if isinstance(it, NodeItem)]
            if len(sel) == 1:
                self._update_insert(sel[0], self.mapToScene(ev.position().toPoint()), ev.modifiers())
            else:
                self._set_insert(None)

    def mouseReleaseEvent(self, ev):
        if self._pan is not None and ev.button() == QtCore.Qt.MiddleButton:
            self._pan = None
            self.unsetCursor()
            return
        if self._drag_link is not None:
            name, is_out, ident, path = self._drag_link
            self._drag_link = None
            self.scene().removeItem(path)
            sp = self.mapToScene(ev.position().toPoint())
            target = self._item_at(ev.position().toPoint())
            sock = self._drag_socket(name, is_out, ident)
            if target is not None and getattr(target, "name", None) != name and sock is not None:
                hit = target.socket_at(sp)
                if hit is not None and hit[0] != is_out:
                    out_s, in_s = (sock, hit[1]) if is_out else (hit[1], sock)
                    try:
                        new_link(self.editor.tree, out_s, in_s)
                    except Exception as ex:
                        bridge.log(str(ex), "ERROR")
            bridge.undo_push("Link")
            self.editor.rebuild()
            return
        super().mouseReleaseEvent(ev)
        li = self._insert_li
        self._set_insert(None)
        moved = None
        if self._moving:
            self._moving = False
            sel = [it for it in self.scene().selectedItems() if isinstance(it, NodeItem)]
            moved = sel[0] if len(sel) == 1 else None
            self.editor.commit_positions()
        self.editor.commit_selection()
        if li is not None and moved is not None:
            self.editor.insert_on_link(moved, li)

    def mouseDoubleClickEvent(self, ev):
        it = self._item_at(ev.position().toPoint())
        if it is not None and getattr(it.node, "node_tree", None) is not None and it.kind == "node":
            self.editor.enter_group(it.node)
            return
        super().mouseDoubleClickEvent(ev)

    def keyPressEvent(self, ev):
        if self._grab is not None:          # modal like Blender's grab: Enter / Space confirm, Esc cancels
            if ev.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Space):
                self.end_grab(True)
            elif ev.key() == QtCore.Qt.Key_Escape:
                self.end_grab(False)
            return
        from . import keymap
        names = keymap.event_names(ev)

        def H(aid):
            return keymap.hit(aid, ev, names)
        if H("node.delete"):
            self.editor.delete_selected()
        elif H("node.add"):
            self.editor.add_node_popup(QtGui.QCursor.pos(), self.mapToScene(self.mapFromGlobal(QtGui.QCursor.pos())))
        elif H("node.deselect_all"):
            for it in self.scene().selectedItems():
                it.setSelected(False)
            self.editor.commit_selection()
        elif H("node.select_all"):
            for it in self.editor.items.values():
                it.setSelected(True)
            self.editor.commit_selection()
        elif H("node.duplicate"):
            self.editor.duplicate_selected()
        elif H("node.mute"):
            self.editor.toggle("mute")
        elif H("node.hide"):
            self.editor.toggle("hide")
        elif H("node.frame_all"):
            self.editor.frame_all()           # Home like Blender, F as requested
        elif H("node.frame_selected"):
            self.editor.frame_selected()      # Numpad . like Blender
        elif H("node.search"):
            # node search at the mouse (like Shift+A)
            gpos = QtGui.QCursor.pos()
            self.editor.add_node_popup(gpos, self.mapToScene(self.mapFromGlobal(gpos)))
        elif H("node.group"):
            # Ctrl+Tab: into the selected group node / out of the group
            sel = [it for it in self.scene().selectedItems() if isinstance(it, NodeItem)]
            if sel and getattr(sel[0].node, "node_tree", None) is not None:
                self.editor.enter_group(sel[0].node)
            else:
                self.editor.exit_group()
        else:
            super().keyPressEvent(ev)

    def focusNextPrevChild(self, _n):
        return False

    def contextMenuEvent(self, ev):
        """Right-click menu: Duplicate, Delete, Mute, Collapse … – a node under the cursor that is not
        selected becomes the selection first."""
        if self._grab is not None or self.editor.tree is None:
            return
        it = self._item_at(ev.pos())
        if it is not None and not it.isSelected():
            for x in self.scene().selectedItems():
                x.setSelected(False)
            it.setSelected(True)
            self.editor.set_active(it)
            self.editor.commit_selection()
        self.build_context_menu(ev.globalPos()).exec(ev.globalPos())

    def build_context_menu(self, gpos=None):
        from . import keymap, blicons
        ed = self.editor
        m = QtWidgets.QMenu(self)
        sel = [x for x in self.scene().selectedItems() if isinstance(x, NodeItem)]
        n = len(sel)

        def act(text, aid, fn, icon=None, enabled=True):
            keys = keymap.keys(aid)
            a = m.addAction(text + ("\t" + " / ".join(keys) if keys else ""))
            if icon and blicons.has(icon):
                a.setIcon(blicons.icon(icon))
            a.setEnabled(enabled)
            a.triggered.connect(lambda _=False: fn())
            return a
        sp = self.mapToScene(self.mapFromGlobal(gpos or QtGui.QCursor.pos()))
        act("Duplicate Node" if n == 1 else f"Duplicate Nodes ({n})" if n else "Duplicate", "node.duplicate",
            ed.duplicate_selected, "DUPLICATE", n > 0)
        act("Delete", "node.delete", ed.delete_selected, "X", n > 0)
        m.addSeparator()
        act("Mute", "node.mute", lambda: ed.toggle("mute"), "MUTE_IPO_ON", n > 0)
        act("Collapse", "node.hide", lambda: ed.toggle("hide"), "HIDE_ON", n > 0)
        m.addSeparator()
        act("Add Node…", "node.add", lambda: ed.add_node_popup(gpos or QtGui.QCursor.pos(), sp), "ADD")
        act("Select All", "node.select_all", lambda: (
            [x.setSelected(True) for x in ed.items.values()], ed.commit_selection()), "SELECT_SET")
        act("Frame Selected", "node.frame_selected", ed.frame_selected, "ZOOM_SELECTED")
        m.addSeparator()
        pin = m.addAction("Pin Node Tree")
        pin.setCheckable(True)
        pin.setChecked(ed.pinned() is not None)
        pin.triggered.connect(lambda on: ed.set_pin(on))
        return m


# ---------------------------------------------------------------- node type search
_TYPE_CACHE = {}
_ABSTRACT = {"Node", "NodeInternal", "ShaderNode", "GeometryNode", "CompositorNode", "TextureNode",
             "FunctionNode", "NodeCustomGroup", "ShaderNodeCustomGroup", "GeometryNodeCustomGroup",
             "CompositorNodeCustomGroup", "NodeUndefined"}


def available_node_types(tree):
    key = tree.bl_idname
    if key in _TYPE_CACHE:
        return _TYPE_CACHE[key]
    cands = []
    for name in dir(bpy.types):
        if name in _ABSTRACT or name.startswith("_"):
            continue
        cls = getattr(bpy.types, name, None)
        try:
            if isinstance(cls, type) and issubclass(cls, bpy.types.Node):
                cands.append(name)
        except Exception:
            pass
    ok = []
    probe = bpy.data.node_groups.new("__qtshell_probe__", key)
    try:
        for name in cands:
            try:
                n = probe.nodes.new(name)
                label = tr(n.bl_rna.name) or name
                probe.nodes.remove(n)
                ok.append((label, name))
            except Exception:
                pass
    finally:
        bpy.data.node_groups.remove(probe)
    if key == "ShaderNodeTree":
        for name in ("ShaderNodeOutputMaterial", "ShaderNodeOutputWorld", "ShaderNodeOutputLight"):
            if name not in {n for _l, n in ok} and hasattr(bpy.types, name):
                ok.append((tr(getattr(bpy.types, name).bl_rna.name), name))
    ok.sort(key=lambda t: t[0].lower())
    _TYPE_CACHE[key] = ok
    return ok


class AddNodePopup(QtWidgets.QDialog):
    def __init__(self, parent, types, on_pick):
        super().__init__(parent, QtCore.Qt.Popup)
        self.resize(320, 380)
        self.types = types
        self.on_pick = on_pick
        lay = QtWidgets.QVBoxLayout(self)
        self.edit = QtWidgets.QLineEdit()
        self.edit.setPlaceholderText("Search node…  (Enter adds, Esc closes)")
        self.edit.textChanged.connect(self._filter)
        self.edit.returnPressed.connect(self._accept)
        lay.addWidget(self.edit)
        self.list = QtWidgets.QListWidget()
        self.list.itemActivated.connect(lambda _i: self._accept())
        lay.addWidget(self.list)
        self.edit.installEventFilter(self)
        self._filter("")

    def _filter(self, text):
        words = text.lower().split()
        self.list.clear()
        for label, ident in self.types:
            hay = f"{label} {ident}".lower()
            if all(w in hay for w in words):
                it = QtWidgets.QListWidgetItem(label)
                it.setToolTip(ident)
                it.setData(QtCore.Qt.UserRole, ident)
                self.list.addItem(it)
        self.list.setCurrentRow(0)

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.KeyPress and ev.key() in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down):
            row = self.list.currentRow() + (1 if ev.key() == QtCore.Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
            return True
        return False

    def _accept(self):
        it = self.list.currentItem()
        self.close()
        if it is not None:
            self.on_pick(it.data(QtCore.Qt.UserRole))


# ---------------------------------------------------------------- editor
SOURCES = [("SHADER", "Shader (material)"), ("WORLD", "World"), ("GEOMETRY", "Geometry Nodes"),
           ("COMPOSITOR", "Compositor")]


class NodeEditor(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.items = {}
        self.links = []
        self.group_stack = []
        self.active_name = None
        self._sig = None
        self.tree = None
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        self.source = rw.NoWheelCombo()
        for ident, label in SOURCES:
            self.source.addItem(label, ident)
        self.source.activated.connect(lambda _i: (self.set_pin(False), self._reset()))
        pytips.tag(self.source, NE_PY + 'set_source("SHADER")   # SHADER, WORLD, GEOMETRY, COMPOSITOR')
        bar.addWidget(self.source)
        # Pin like Blender: keep showing this node tree when another object / material becomes active
        self._pinned = None                   # (source, kind, id name) of the pinned tree
        self.pin_btn = QtWidgets.QToolButton()
        self.pin_btn.setCheckable(True)
        self.pin_btn.setAutoRaise(True)
        self._pin_icons()
        self.pin_btn.setToolTip("Pin – keep showing this node tree when another object or material "
                                "becomes active (like Blender's pin)")
        self.pin_btn.toggled.connect(lambda on: self.set_pin(on))
        pytips.tag(self.pin_btn, NE_PY + "set_pin(True)   # False = unpin")
        bar.addWidget(self.pin_btn)
        self.path_label = QtWidgets.QLabel("")
        self.path_label.setProperty("dim", True)
        bar.addWidget(self.path_label, 1)
        self.up_btn = QtWidgets.QToolButton()
        self.up_btn.setText("↑ Exit Group")
        from . import keymap
        keymap.tip(self.up_btn, "Exit the node group ({node.group}). {node.group} on a selected group node enters it.")
        self.up_btn.clicked.connect(self.exit_group)
        pytips.tag(self.up_btn, NE_PY + "exit_group()")
        bar.addWidget(self.up_btn)
        self.new_btn = QtWidgets.QToolButton()
        self.new_btn.setText("+ New Tree")
        self.new_btn.clicked.connect(self.new_tree)
        pytips.tag(self.new_btn, NE_PY + "new_tree()")
        bar.addWidget(self.new_btn)
        add = QtWidgets.QToolButton()
        keymap.tip(add, "+ Add Node ({node.search})", "setText")
        keymap.tip(add, "Search and add a node – {node.search} or {node.add} over the editor")
        add.clicked.connect(lambda: self.add_node_popup(QtGui.QCursor.pos(), self.view.mapToScene(
            self.view.viewport().rect().center())))
        bar.addWidget(add)
        pytips.tag(add, NE_PY + "add_node_popup(QtGui.QCursor.pos(), ne.view.mapToScene("
                            "ne.view.viewport().rect().center()))")
        fit = QtWidgets.QToolButton()
        fit.setText("⤢")
        keymap.tip(fit, "Frame All ({node.frame_all})\nFrame Selected: {node.frame_selected}")
        fit.clicked.connect(self.frame_all)
        pytips.tag(fit, NE_PY + "frame_all()")
        bar.addWidget(fit)
        lay.addLayout(bar)
        split = QtWidgets.QSplitter()
        self.scene = QtWidgets.QGraphicsScene(self)
        self.scene.setSceneRect(-20000, -20000, 40000, 40000)
        self.view = NodeView(self)
        self.view.setScene(self.scene)
        split.addWidget(self.view)
        # sidebar with tabs like Blender's N panel: Node (active node) / Group (the tree's inputs and outputs)
        self.side_tabs = QtWidgets.QTabWidget()
        self.side_tabs.setMinimumWidth(theme.px(220))
        self.side = QtWidgets.QScrollArea()
        self.side.setWidgetResizable(True)
        self.side_tabs.addTab(self.side, "Node")
        self.group_side = QtWidgets.QScrollArea()
        self.group_side.setWidgetResizable(True)
        self.group_side.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.side_tabs.addTab(self.group_side, "Group")
        pytips.tag(self.side_tabs, NE_PY + "side_tabs.setCurrentIndex(1)  # Group tab")
        split.addWidget(self.side_tabs)
        self.group_bindings = []
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)
        self.side_bindings = []
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.refresh)
        hub.data_changed.connect(lambda: self._timer.start())
        hub.selection_changed.connect(self._selection_changed)
        hub.file_loaded.connect(self._reset)
        hub.undo_done.connect(self._reset)
        self._first_frame = True
        self._reset()

    # --- tree
    # --- pin (like Blender)
    def _pin_icons(self):
        from . import blicons
        on = self.pin_btn.isChecked()
        name = "PINNED" if on else "UNPINNED"
        if blicons.has(name):
            self.pin_btn.setIcon(blicons.icon(name))
        else:
            self.pin_btn.setText("📌" if on else "Pin")

    def _owner_of(self, tree):
        """(kind, name) of the ID that holds the shown base tree – a material / world tree is embedded,
        so the material / world is remembered, a node group by its own name."""
        mode = self.source.currentData()
        if tree is None:
            return None
        if mode == "SHADER":
            ob = bpy.context.view_layer.objects.active
            mat = ob.active_material if ob is not None else None
            if mat is not None and mat.node_tree is not None and mat.node_tree.as_pointer() == tree.as_pointer():
                return ("MAT", mat.name)
            return None
        if mode == "WORLD":
            w = bpy.context.scene.world
            return ("WORLD", w.name) if w is not None else None
        if tree.name in bpy.data.node_groups and bpy.data.node_groups[tree.name].as_pointer() == tree.as_pointer():
            return ("NG", tree.name)
        return None

    def set_pin(self, on=True):
        """Pins (True) / unpins (False) the node tree shown now: it stays when the active object or material
        changes, like Blender's pin. Returns whether it is pinned."""
        on = bool(on)
        if on and self._pinned is None:
            owner = self._owner_of(self._unpinned_base())
            if owner is None:
                on = False
            else:
                self._pinned = (self.source.currentData(),) + owner
        elif not on:
            self._pinned = None
        self.pin_btn.blockSignals(True)
        self.pin_btn.setChecked(on)
        self.pin_btn.blockSignals(False)
        self._pin_icons()
        self._timer.start()
        return on

    def pinned(self):
        """The name of the pinned tree's owner (material / world / node group), or None."""
        return self._pinned[2] if self._pinned else None

    def _selection_changed(self):
        if self._pinned is None:              # pinned: stay inside the groups too
            self.group_stack.clear()
        self._timer.start()

    def base_tree(self):
        if self._pinned is not None:
            src, kind, name = self._pinned
            col = {"MAT": bpy.data.materials, "WORLD": bpy.data.worlds, "NG": bpy.data.node_groups}[kind]
            owner = col.get(name)
            if owner is not None:
                return owner if kind == "NG" else owner.node_tree
            self._pinned = None               # deleted / renamed: back to following the selection
            QtCore.QTimer.singleShot(0, lambda: self.set_pin(False))
        return self._unpinned_base()

    def _unpinned_base(self):
        mode = self.source.currentData()
        ctx = bpy.context
        ob = ctx.view_layer.objects.active
        scene = ctx.scene
        if mode == "SHADER":
            mat = ob.active_material if ob is not None else None
            return mat.node_tree if mat is not None and mat.node_tree is not None else None
        if mode == "WORLD":
            return scene.world.node_tree if scene.world is not None else None
        if mode == "GEOMETRY":
            if ob is None:
                return None
            mods = [m for m in ob.modifiers if m.type == "NODES"]
            act = ob.modifiers.active if hasattr(ob.modifiers, "active") else None
            if act is not None and act.type == "NODES":
                return act.node_group
            return mods[0].node_group if mods else None
        if mode == "COMPOSITOR":
            ng = getattr(scene, "compositing_node_group", None)
            if ng is not None:
                return ng
            # Blender 5.x keeps a deprecated Scene.use_nodes (can be True) but has no Scene.node_tree
        return getattr(scene, "node_tree", None) if getattr(scene, "use_nodes", False) else None
        return None

    def current_tree(self):
        while self.group_stack:
            try:
                return self.group_stack[-1].node_tree
            except ReferenceError:
                self.group_stack.pop()
        return self.base_tree()

    def set_source(self, mode):
        """SHADER, WORLD, GEOMETRY or COMPOSITOR."""
        i = self.source.findData(mode)
        if i >= 0:
            self.source.setCurrentIndex(i)
            self._reset()

    def _reset(self):
        self.group_stack.clear()
        self._sig = None
        self._first_frame = True
        self.refresh()

    def signature(self, tree):
        if tree is None:
            return None
        parts = [tree.name]
        for n in tree.nodes:
            loc = abs_location(n)
            parts.append((n.name, n.bl_idname, round(loc[0]), round(loc[1]), n.hide, n.mute,
                          round(n.width), n.label,
                          tuple(s.identifier for s in n.inputs if getattr(s, "enabled", True) and not s.hide),
                          tuple(s.identifier for s in n.outputs if getattr(s, "enabled", True) and not s.hide),
                          tuple(str(getattr(n, p.identifier)) for p in node_buttons(n)),
                          socket_ptrs(n)))
        for lk in tree.links:
            parts.append((lk.from_node.name, lk.from_socket.identifier, lk.to_node.name,
                          lk.to_socket.identifier, getattr(lk, "is_muted", False),
                          getattr(lk, "multi_input_sort_id", 0)))
        return hash(tuple(parts))

    def refresh(self):
        if self.view._drag_link is not None or self.view._moving or self.view._grab is not None \
                or QtWidgets.QApplication.mouseButtons():
            self._timer.start()
            return
        try:
            tree = self.current_tree()
            sig = self.signature(tree)
        except ReferenceError:
            self._reset()
            return
        if sig != self._sig or tree is not self.tree:
            self._sig = sig
            self.tree = tree
            self.rebuild(keep_sig=True)
        else:
            self.view.viewport().update()
            for b in self.side_bindings:
                try:
                    b.refresh()
                except Exception:
                    pass

    def rebuild(self, keep_sig=False):
        # the items are about to be replaced – a grab / highlight of the old ones ends here
        if getattr(self, "view", None) is not None:
            if self.view._grab is not None:
                self.view._grab = None
                self.view.viewport().unsetCursor()
            self.view._insert_li = None
        if not keep_sig:
            self._sig = None
            self.tree = self.current_tree()
        tree = self.tree
        self.scene.clear()
        self.items = {}
        self.links = []
        names = [g.node_tree.name for g in self.group_stack if getattr(g, "node_tree", None)]
        self.path_label.setText(" › ".join(([tree.name] if tree is not None and not names else [])
                                           + names) if tree is not None else "")
        self.up_btn.setVisible(bool(self.group_stack))
        self.new_btn.setVisible(tree is None and not self.group_stack)
        if tree is None:
            t = self.scene.addText("No node tree – pick a source above or click “+ New Tree”.")
            t.setDefaultTextColor(QtGui.QColor("#9a9a9a"))
            self._build_side()
            self._build_group_if_changed()
            return
        for n in tree.nodes:
            it = NodeItem(self, n)
            self.scene.addItem(it)
            self.items[n.name] = it
        act = tree.nodes.active
        self.active_name = act.name if act is not None else None
        for lk in tree.links:
            a = self.items.get(lk.from_node.name)
            b = self.items.get(lk.to_node.name)
            if a is None or b is None:
                continue
            li = LinkItem(lk, a, b)
            self.scene.addItem(li)
            self.links.append(li)
        if not keep_sig:
            self._sig = self.signature(tree)
        if self._first_frame:
            self._first_frame = False
            QtCore.QTimer.singleShot(0, self.frame_all)
        self._build_side()
        self._build_group_if_changed()

    def update_links(self):
        for li in self.links:
            li.update_path()

    def dirty_structure(self):
        self._sig = None

    # --- operations
    def set_active(self, item):
        if item.node is None:
            return
        try:
            self.tree.nodes.active = item.node
            self.active_name = item.name
        except Exception:
            pass
        self._build_side()

    def commit_selection(self):
        if self.tree is None:
            return
        for name, it in self.items.items():
            node = it.node                       # None: removed meanwhile (e.g. by the Image editor's cache)
            if node is None:
                continue
            try:
                node.select = it.isSelected()
            except ReferenceError:
                pass
        self.view.viewport().update()

    def commit_positions(self):
        changed = False
        for it in self.items.values():
            try:
                node = it.node
                if node is None:
                    continue
                px, py = it.pos().x(), -it.pos().y()
                ax, ay = abs_location(node)
                if abs(px - ax) > 0.01 or abs(py - ay) > 0.01:
                    node.location = (node.location[0] + px - ax, node.location[1] + py - ay)
                    changed = True
            except ReferenceError:
                pass
        if changed:
            bridge.undo_push("Move Node")
            self._sig = self.signature(self.tree)

    def delete_selected(self):
        if self.tree is None:
            return
        sel = [it for it in self.scene.selectedItems() if isinstance(it, NodeItem)]
        for it in sel:
            if it.node is None:
                continue
            try:
                self.tree.nodes.remove(it.node)
            except Exception as ex:
                bridge.log(str(ex), "ERROR")
        if sel:
            bridge.undo_push("Delete Nodes")
            self.rebuild()

    def duplicate_selected(self, grab=True):
        """Duplicates the selected nodes like Blender's Duplicate (links between them, zones and node items
        kept, inputs from unselected nodes not) – the copies are selected and follow the mouse until a
        click (Esc / right click: they stay where they were made). Returns the names of the new nodes."""
        tree = self.tree
        if tree is None:
            return []
        sel = [it.name for it in self.scene.selectedItems() if isinstance(it, NodeItem) and it.node is not None]
        if not sel:
            return []
        for n in tree.nodes:
            n.select = n.name in sel
        before = {n.name for n in tree.nodes}
        ok = False
        try:
            with node_space_context(tree):
                ok = "FINISHED" in bpy.ops.node.duplicate()
        except Exception as ex:
            bridge.log(f"Duplicate nodes: {ex}", "WARNING")
        if not ok:
            ok = _copy_nodes(tree, sel)
        new = [n.name for n in tree.nodes if n.name not in before]
        if not new:
            return []
        for n in tree.nodes:
            n.select = n.name in new
        act = tree.nodes.get(new[0])
        if act is not None:
            tree.nodes.active = act
        bridge.undo_push("Duplicate Nodes")
        self.rebuild()
        if grab:
            items = [self.items[n] for n in new if n in self.items]
            if items:
                self.view.start_grab(items[0], items)
        return new

    def toggle(self, attr):
        sel = [it for it in self.scene.selectedItems() if isinstance(it, NodeItem)]
        for it in sel:
            node = it.node
            if node is None:
                continue
            try:
                setattr(node, attr, not getattr(node, attr))
            except Exception:
                pass
        if sel:
            bridge.undo_push(f"Toggle {attr}")
            self.rebuild()

    def add_node_popup(self, gpos, scene_pos):
        if self.tree is None:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            types = available_node_types(self.tree)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        def pick(ident):
            try:
                n = self.tree.nodes.new(ident)
            except Exception as ex:
                bridge.log(f"{ident}: {ex}", "ERROR")
                return
            n.location = (scene_pos.x(), -scene_pos.y())
            for o in self.tree.nodes:
                o.select = False
            n.select = True
            self.tree.nodes.active = n
            bridge.undo_push("Add Node")
            name = n.name
            self.rebuild()
            # like Blender: the new node follows the mouse until a click – over a link it is inserted into it
            self.view.start_grab(self.items.get(name))
        dlg = AddNodePopup(self, types, pick)
        dlg.move(gpos)
        dlg.show()
        dlg.edit.setFocus()

    def insert_on_link(self, item, li):
        """Inserts the node of item into the link of li (from → node's main input, node's main output → to),
        like dropping a node on a link in Blender; nodes that would overlap are moved aside (auto-offset)."""
        tree = self.tree
        node = item.node if item is not None else None
        if tree is None or node is None or not node_is_free(node):
            return False
        (a_item, a_id), (b_item, b_id) = li.a, li.b
        lk = next((l for l in tree.links if l.from_node.name == a_item.name and l.from_socket.identifier == a_id
                   and l.to_node.name == b_item.name and l.to_socket.identifier == b_id), None)
        if lk is None:
            return False
        fs, ts = lk.from_socket, lk.to_socket
        ni, no = main_socket(node.inputs, fs.type), main_socket(node.outputs, ts.type)
        if ni is None or no is None:
            return False
        try:
            tree.links.remove(lk)
            tree.links.new(fs, ni)
            tree.links.new(no, ts)
        except Exception as ex:
            bridge.log(f"Insert node: {ex}", "ERROR")
            return False
        self._auto_offset(item, a_item, b_item)
        bridge.undo_push("Insert Node")
        self.rebuild()
        return True

    AUTO_OFFSET_MARGIN = 40

    def _auto_offset(self, item, a_item, b_item):
        """Blender's auto-offset: the nodes after the inserted one move right (before it: left) when it
        overlaps them."""
        tree = self.tree
        r = item.sceneBoundingRect()
        m = self.AUTO_OFFSET_MARGIN

        def chain(start, forward):
            seen, todo = set(), [start]
            while todo:
                nm = todo.pop()
                if nm in seen or nm == item.name:
                    continue
                seen.add(nm)
                for l in tree.links:
                    if forward and l.from_node.name == nm:
                        todo.append(l.to_node.name)
                    elif not forward and l.to_node.name == nm:
                        todo.append(l.from_node.name)
            return seen
        right = r.right() + m - b_item.sceneBoundingRect().left()
        if right > 0:
            for nm in chain(b_item.name, True):
                n = tree.nodes.get(nm)
                if n is not None and n.bl_idname != "NodeFrame":
                    n.location = (n.location[0] + right, n.location[1])
        left = a_item.sceneBoundingRect().right() + m - r.left()
        if left > 0:
            for nm in chain(a_item.name, False):
                n = tree.nodes.get(nm)
                if n is not None and n.bl_idname != "NodeFrame":
                    n.location = (n.location[0] - left, n.location[1])

    def enter_group(self, node):
        if getattr(node, "node_tree", None) is None:
            return
        self.group_stack.append(node)
        self._first_frame = True
        self.rebuild()

    def exit_group(self):
        if self.group_stack:
            self.group_stack.pop()
            self._first_frame = True
            self.rebuild()

    def frame_all(self):
        self._frame_items(list(self.items.values()))

    def frame_selected(self):
        sel = [it for it in self.view.scene().selectedItems() if isinstance(it, NodeItem)]
        self._frame_items(sel or list(self.items.values()))

    def _frame_items(self, items):
        rect = QtCore.QRectF()
        for it in items:
            rect = rect.united(it.sceneBoundingRect())
        if rect.isNull():
            return
        if not self.view._big_enough():
            # hidden or tiny (e.g. a dock behind another tab): fitting now would zoom far out –
            # frame when the editor gets its real size
            self._frame_pending = True
            return
        self._frame_pending = False
        self.view.fitInView(rect.adjusted(-60, -60, 60, 60), QtCore.Qt.KeepAspectRatio)
        m = self.view.transform().m11()
        target = min(max(m, NodeView.ZOOM_MIN), 1.2)
        if abs(target / m - 1.0) > 1e-4:
            self.view.scale(target / m, target / m)
        self.view.centerOn(rect.center())

    def new_tree(self):
        mode = self.source.currentData()
        ctx = bpy.context
        ob = ctx.view_layer.objects.active
        scene = ctx.scene
        try:
            if mode == "SHADER" and ob is not None:
                mat = bpy.data.materials.new("Material")
                mat.use_nodes = True
                ob.active_material = mat
            elif mode == "WORLD":
                w = scene.world or bpy.data.worlds.new("World")
                w.use_nodes = True
                scene.world = w
            elif mode == "GEOMETRY" and ob is not None:
                ng = bpy.data.node_groups.new("Geometry Nodes", "GeometryNodeTree")
                ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
                ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
                gi = ng.nodes.new("NodeGroupInput")
                go = ng.nodes.new("NodeGroupOutput")
                gi.location = (-250, 0)
                go.location = (150, 0)
                ng.links.new(gi.outputs[0], go.inputs[0])
                try:
                    ng.is_modifier = True
                except Exception:
                    pass
                mod = ob.modifiers.new("GeometryNodes", "NODES")
                mod.node_group = ng
            elif mode == "COMPOSITOR":
                # Render Layers → Group Output, and a Viewer (the Image Editor shows the Viewer's picture)
                from .image_editor import ensure_compositor
                ensure_compositor(viewer=True)
        except Exception as ex:
            bridge.log(str(ex), "ERROR")
        bridge.undo_push("New Node Tree")
        self._reset()

    # --- sidebar
    def _rebuild_now(self):
        """Rebuild items + sidebar from the tree now (sockets were rebuilt), keeping the view."""
        try:
            self._sig = None
            self.refresh()
        except Exception:
            bridge.log(traceback.format_exc(), "ERROR")

    # --- Group tab: the node group's interface (inputs / outputs) like Blender's N panel → Group
    def _iface(self):
        tree = self.tree
        if tree is None or getattr(tree, "is_embedded_data", False):
            return None
        return getattr(tree, "interface", None)

    def group_items(self):
        """The interface items of the shown node group (sockets and panels, Blender's order)."""
        iface = self._iface()
        return list(iface.items_tree) if iface is not None else []

    def _group_changed(self, label="Group Interface"):
        bridge.undo_push(label)
        self._sig = None
        QtCore.QTimer.singleShot(0, self._rebuild_now)

    def group_add(self, in_out="INPUT", socket_type="NodeSocketFloat", name=None):
        """Adds a group input / output (in_out 'INPUT' / 'OUTPUT') or a panel (in_out 'PANEL'); returns it."""
        iface = self._iface()
        if iface is None:
            return None
        try:
            if in_out == "PANEL":
                item = iface.new_panel(name or "Panel")
            else:
                item = iface.new_socket(name or ("Socket"), in_out=in_out, socket_type=socket_type)
            iface.active = item
        except Exception as ex:
            bridge.log(f"Group interface: {ex}", "ERROR")
            return None
        self._group_changed("Add Group Socket")
        return item

    def group_remove(self, index=None):
        """Removes the active (or index-th) interface item."""
        iface = self._iface()
        if iface is None:
            return False
        items = list(iface.items_tree)
        i = iface.active_index if index is None else index
        if not 0 <= i < len(items):
            return False
        try:
            iface.remove(items[i])
            iface.active_index = max(0, min(i, len(iface.items_tree) - 1))
        except Exception as ex:
            bridge.log(f"Group interface: {ex}", "ERROR")
            return False
        self._group_changed("Remove Group Socket")
        return True

    def group_move(self, step, index=None):
        """Moves the active (or index-th) interface item up (step -1) or down (step 1) within its parent."""
        iface = self._iface()
        if iface is None:
            return False
        items = list(iface.items_tree)
        i = iface.active_index if index is None else index
        if not 0 <= i < len(items):
            return False
        item = items[i]
        try:
            pos = item.position + step
            if pos < 0:
                return False
            # Blender's move() counts the item itself: moving down needs one more
            iface.move(item, pos + (1 if step > 0 else 0))
            iface.active = item
        except Exception as ex:
            bridge.log(f"Group interface: {ex}", "ERROR")
            return False
        self._group_changed("Move Group Socket")
        return True

    def group_rename(self, index, name):
        """Renames an interface item – the name the Group Input / Output nodes and the modifier show."""
        items = self.group_items()
        if not 0 <= index < len(items) or not name:
            return False
        try:
            items[index].name = name
        except Exception as ex:
            bridge.log(f"Group interface: {ex}", "ERROR")
            return False
        self._group_changed("Rename Group Socket")
        return True

    def _group_sig(self):
        iface = self._iface()
        if iface is None:
            return (self.tree.name if self.tree is not None else None,)
        try:
            return (self.tree.name, iface.active_index,
                    tuple((getattr(i, "identifier", ""), i.name, getattr(i, "socket_type", ""),
                           getattr(i, "in_out", ""), i.item_type, i.as_pointer()) for i in iface.items_tree))
        except Exception:
            return None

    def group_set_type(self, index, type_name):
        """Changes the type of an interface socket ('Float', 'Integer', … or a NodeSocket idname)."""
        items = self.group_items()
        if not 0 <= index < len(items) or items[index].item_type != "SOCKET":
            return False
        try:
            items[index].socket_type = SOCKET_IDNAMES.get(type_name, type_name)
        except Exception as ex:
            bridge.log(f"Group interface: {ex}", "ERROR")
            return False
        self._group_changed("Group Socket Type")
        return True

    def _socket_type_combo(self, item, parent):
        cb = rw.NoWheelCombo(parent)
        cur = getattr(item, "socket_type", "")
        names = list(GROUP_SOCKET_TYPES.get(getattr(self.tree, "bl_idname", ""), GROUP_SOCKET_TYPES["ShaderNodeTree"]))
        known = {v: k for k, v in SOCKET_IDNAMES.items()}
        if cur and known.get(cur) not in names:
            names.append(known.get(cur, cur))
        for n in names:
            cb.addItem(n, SOCKET_IDNAMES.get(n, n))
        cb.setCurrentIndex(max(0, cb.findData(cur)))
        idx = self.group_items().index(item) if item in self.group_items() else -1
        cb.activated.connect(lambda i, k=idx: self.group_set_type(k, cb.itemData(i)))
        pytips.tag(cb, NE_PY + f"group_set_type({idx}, 'Float')")
        return cb

    def _build_group_if_changed(self):
        """The Group tab is rebuilt only when the interface itself changed (not while a value is dragged)."""
        sig = self._group_sig()
        if sig is not None and sig == getattr(self, "_gsig", None):
            return
        self._build_group()

    def _build_group(self):
        self._gsig = self._group_sig()
        self.group_bindings = []
        host = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(host)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        iface = self._iface()
        if iface is None:
            lab = QtWidgets.QLabel("Inputs and outputs belong to node groups (Geometry Nodes, node groups). "
                                   "A material's or world's own tree has none.")
            lab.setWordWrap(True)
            lay.addWidget(lab)
            lay.addStretch(1)
            self.group_side.setWidget(host)
            return
        tree_name = self.tree.name
        items = list(iface.items_tree)
        lay.addWidget(QtWidgets.QLabel(f"<b>{tree_name}</b> – Interface"))
        lst = QtWidgets.QListWidget(host)
        lst.setObjectName("group_interface_list")
        for it in items:
            depth = 0
            par = getattr(it, "parent", None)
            while par is not None and getattr(par, "parent", None) is not None:
                depth += 1
                par = par.parent
            if it.item_type == "PANEL":
                text = "▾ " + it.name
                icon = QtGui.QIcon()
            else:
                text = it.name
                icon = _iface_icon(it)
            row = QtWidgets.QListWidgetItem(icon, "    " * depth + text)
            row.setFlags(row.flags() | QtCore.Qt.ItemIsEditable)
            if it.item_type == "SOCKET":
                row.setToolTip(("Input" if it.in_out == "INPUT" else "Output") + f" · {it.socket_type}"
                               "\nDouble-click to rename.")
                row.setData(QtCore.Qt.UserRole + 1, it.in_out)
            row.setData(QtCore.Qt.UserRole, it.name)
            lst.addItem(row)
        if items:
            lst.setCurrentRow(max(0, min(iface.active_index, len(items) - 1)))
        lst.setMinimumHeight(theme.px(120))
        pytips.tag(lst, NE_PY + "group_items()")

        def on_row(r):
            if 0 <= r < len(self.group_items()) and iface.active_index != r:
                try:
                    iface.active_index = r
                except Exception:
                    pass
                QtCore.QTimer.singleShot(0, self._build_group)
        lst.currentRowChanged.connect(on_row)

        def on_edit(row):
            r = lst.row(row)
            new = row.text().strip()
            if new and new != row.data(QtCore.Qt.UserRole):
                QtCore.QTimer.singleShot(0, lambda: self.group_rename(r, new))
        lst.itemChanged.connect(on_edit)
        lay.addWidget(lst)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(2)
        add = QtWidgets.QToolButton(host)          # Blender: one "+" with Input / Output / Panel
        add.setText("+ Add")
        add.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        add.setToolTip("Add a group input (shown in the modifier), output or panel")
        m = QtWidgets.QMenu(add)
        for label, kind in (("Input", "INPUT"), ("Output", "OUTPUT"), ("Panel", "PANEL")):
            act_ = m.addAction(label)
            act_.triggered.connect(lambda _=False, k=kind: self.group_add(k))
            pytips.tag(act_, NE_PY + (f"group_add('{kind}', 'NodeSocketFloat')" if kind != "PANEL"
                                      else "group_add('PANEL')"))
        add.setMenu(m)
        bar.addWidget(add)
        for text, tip, fn, py in (
                ("−", "Remove the selected item", lambda: self.group_remove(), "group_remove()"),
                ("▲", "Move up", lambda: self.group_move(-1), "group_move(-1)"),
                ("▼", "Move down", lambda: self.group_move(1), "group_move(1)")):
            b = QtWidgets.QToolButton(host)
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            pytips.tag(b, NE_PY + py)
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)

        act = items[iface.active_index] if 0 <= iface.active_index < len(items) else None
        if act is not None:
            def changed(*_a):
                # nodes / modifier follow through the normal refresh; the Group tab is rebuilt only when the
                # interface changed (name, type …) – never under a value being dragged
                self._sig = None
                self._timer.start()
                if not hasattr(self, "_gundo_t"):
                    self._gundo_t = QtCore.QTimer(self)
                    self._gundo_t.setSingleShot(True)
                    self._gundo_t.setInterval(400)
                    self._gundo_t.timeout.connect(lambda: bridge.undo_push("Group Socket Property"))
                self._gundo_t.start()
            # Blender's N panel → Group: the settings of the active item, in its order
            have = {p.identifier for p in act.bl_rna.properties if not p.is_readonly}
            props = [p for p in GROUP_ITEM_PROPS if p in have]
            lab = QtWidgets.QLabel(("Panel" if act.item_type == "PANEL" else
                                    ("Input" if act.in_out == "INPUT" else "Output")) + " settings")
            lab.setStyleSheet("font-weight:bold; margin-top:6px;")
            lay.addWidget(lab)
            if act.item_type == "SOCKET":
                lay.addWidget(rw.labeled_row("Type", self._socket_type_combo(act, host)))
            try:
                form, binds = rw.rna_form(act, changed, only=props)
                self.group_bindings.extend(binds)
                lay.addWidget(form)
            except Exception:
                bridge.log(traceback.format_exc(), "ERROR")
        lay.addStretch(1)
        self.group_side.setWidget(host)

    def _socket_resolver(self, node_name, ident):
        """Finds a node input again by node name + identifier (sockets are no IDs – never kept, see socket_ptrs)."""
        def resolve():
            tree = self.tree
            n = tree.nodes.get(node_name) if tree is not None else None
            return next((x for x in n.inputs if x.identifier == ident), None) if n is not None else None
        return resolve

    def _build_side(self):
        self.side_bindings = []
        host = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(host)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        node = None
        if self.tree is not None and self.active_name:
            node = self.tree.nodes.get(self.active_name)
        if node is None:
            lay.addWidget(QtWidgets.QLabel("Select a node."))
            lay.addStretch(1)
            self.side.setWidget(host)
            return
        title = QtWidgets.QLabel(f"<b>{node_title(node)}</b>")
        lay.addWidget(title)

        sock_sig = socket_ptrs(node)
        node_name = node.name

        def changed(*_a):
            self._timer.start()
            undo()
            try:
                cur = self.tree.nodes.get(node_name) if self.tree is not None else None
                stale = cur is None or socket_ptrs(cur) != sock_sig
            except Exception:
                stale = True
            if stale:
                # Data Type & co. rebuilt the sockets: the Inputs fields (and the node items) hold freed sockets –
                # rebuild right after this signal (not inside it: the combo that emitted it is deleted)
                keep = []
                for b in self.side_bindings:
                    if isinstance(getattr(b, "_data", None), bpy.types.NodeSocket):
                        try:
                            if b.widget_ok():
                                b.widget.setEnabled(False)      # its socket is gone
                        except Exception:
                            pass
                    else:
                        keep.append(b)
                self.side_bindings = keep
                QtCore.QTimer.singleShot(0, self._rebuild_now)
                return
            self.view.viewport().update()

        def undo():
            if not hasattr(self, "_undo_t"):
                self._undo_t = QtCore.QTimer(self)
                self._undo_t.setSingleShot(True)
                self._undo_t.setInterval(400)
                self._undo_t.timeout.connect(lambda: bridge.undo_push("Node Property"))
            self._undo_t.start()

        for pid in ("name", "label"):
            b, label = rw.make_binding(node, pid, on_change=changed)
            if b is not None:
                self.side_bindings.append(b)
                lay.addWidget(rw.labeled_row(label, b.widget))
        props = [p.identifier for p in node.bl_rna.properties
                 if p.identifier not in base_node_props() and not p.is_readonly]
        if props:
            form, binds = rw.rna_form(node, changed, only=props)
            self.side_bindings.extend(binds)
            lay.addWidget(form)
        ins = [s for s in node.inputs if getattr(s, "enabled", True) and not s.hide
               and not s.is_linked and hasattr(s, "default_value") and not getattr(s, "hide_value", False)]
        if ins:
            lab = QtWidgets.QLabel("Inputs")
            lab.setStyleSheet("font-weight:bold; margin-top:6px;")
            lay.addWidget(lab)
            for s in ins:
                b, label = rw.make_binding(s, "default_value", text=tr(s.name), on_change=changed)
                if b is not None:
                    b.resolve = self._socket_resolver(node_name, s.identifier)
                    self.side_bindings.append(b)
                    if isinstance(b, rw.BoolBinding):
                        b.widget.setText(label)
                        lay.addWidget(b.widget)
                    else:
                        lay.addWidget(rw.labeled_row(label, b.widget))
        lay.addStretch(1)
        self.side.setWidget(host)

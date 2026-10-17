"""Node editor v Qt (QGraphicsView): shader, svět, Geometry Nodes, compositor.

Uzly, sockety a spoje se kreslí z dat Blenderu (node_tree.nodes / links). Úpravy se zapisují
zpět přímo do RNA: posun (node.location), spojení (links.new / remove), přidání a mazání uzlů,
hodnoty nepřipojených vstupů a vlastnosti uzlu v postranním panelu.
"""
import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, rna_widgets as rw
from .bridge import tr

ROW_H = 22
HEADER_H = 24
SOCK_R = 5.0

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
    """Editovatelné vlastnosti uzlu zobrazené přímo v uzlu (enumy, ID ukazatele)."""
    out = []
    for p in node.bl_rna.properties:
        if p.identifier in base_node_props() or p.is_readonly:
            continue
        if p.type == "ENUM" or (p.type == "POINTER" and p.fixed_type is not None and rw.is_id_type(p.fixed_type)):
            out.append(p)
    return out


# ---------------------------------------------------------------- grafické položky
class NodeItem(QtWidgets.QGraphicsItem):
    def __init__(self, editor, node):
        super().__init__()
        self.editor = editor
        self.node = node
        self.name = node.name
        self.kind = "reroute" if node.bl_idname == "NodeReroute" else (
            "frame" if node.bl_idname == "NodeFrame" else "node")
        self.setFlags(QtWidgets.QGraphicsItem.ItemIsMovable | QtWidgets.QGraphicsItem.ItemIsSelectable
                      | QtWidgets.QGraphicsItem.ItemSendsGeometryChanges)
        self.sockets = {}   # (is_output, identifier) -> (QPointF, socket)
        self.rows = []
        self._build()
        x, y = abs_location(node)
        self.setPos(x, -y)
        self.setZValue(-10 if self.kind == "frame" else 0)
        self.setSelected(bool(node.select))

    def _build(self):
        node = self.node
        self.rows = []
        self.sockets = {}
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
            self.rows.append(("in", s, y))
            self.sockets[(False, s.identifier)] = (QtCore.QPointF(0, y + ROW_H / 2), s)
            y += ROW_H
        self.h = y + 6

    def boundingRect(self):
        return QtCore.QRectF(-SOCK_R - 2, -2, self.w + 2 * SOCK_R + 4, self.h + 4)

    def paint(self, p, _opt, _w):
        node = self.node
        try:
            node.name
        except ReferenceError:
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
        for (is_out, _ident), (pt, s) in self.sockets.items():
            p.setPen(QtGui.QPen(QtGui.QColor("#111111"), 1))
            p.setBrush(socket_color(s))
            if getattr(s, "display_shape", "CIRCLE").startswith("DIAMOND"):
                poly = QtGui.QPolygonF([pt + QtCore.QPointF(0, -SOCK_R - 1), pt + QtCore.QPointF(SOCK_R + 1, 0),
                                        pt + QtCore.QPointF(0, SOCK_R + 1), pt + QtCore.QPointF(-SOCK_R - 1, 0)])
                p.drawPolygon(poly)
            else:
                p.drawEllipse(pt, SOCK_R, SOCK_R)

    def socket_at(self, scene_pos):
        local = self.mapFromScene(scene_pos)
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


class LinkItem(QtWidgets.QGraphicsPathItem):
    def __init__(self, link, a_item, b_item):
        super().__init__()
        self.link = link
        self.a = (a_item, link.from_socket.identifier)
        self.b = (b_item, link.to_socket.identifier)
        col = socket_color(link.from_socket)
        pen = QtGui.QPen(col, 2.2)
        if getattr(link, "is_muted", False):
            pen.setColor(QtGui.QColor("#aa4444"))
            pen.setStyle(QtCore.Qt.DashLine)
        elif not getattr(link, "is_valid", True):
            pen.setColor(QtGui.QColor("#ff3333"))
        self.setPen(pen)
        self.setZValue(-1)
        self.update_path()

    def update_path(self):
        p1 = self.a[0].socket_scene_pos(True, self.a[1])
        p2 = self.b[0].socket_scene_pos(False, self.b[1])
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
        self._drag_link = None   # (from_item, is_out, socket, temp_path_item)
        self._moving = False

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
            win = self.window()
            if not win.isActiveWindow():   # plovoucí dock = samostatné okno
                win.activateWindow()
        super().enterEvent(ev)

    def wheelEvent(self, ev):
        f = 1.15 ** (ev.angleDelta().y() / 120.0)
        cur = self.transform().m11()
        if 0.1 < cur * f < 4:
            self.scale(f, f)

    def _item_at(self, pos):
        for it in self.items(pos):
            if isinstance(it, NodeItem):
                return it
        return None

    def mousePressEvent(self, ev):
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
            # vytáhnout existující spoj ze vstupu
            link = sock.links[0]
            src = link.from_socket
            src_item = self.editor.items.get(link.from_node.name)
            ntree.links.remove(link)
            self.editor.dirty_structure()
            if src_item is None:
                return
            item, is_out, sock = src_item, True, src
        path = QtWidgets.QGraphicsPathItem()
        path.setPen(QtGui.QPen(socket_color(sock), 2, QtCore.Qt.DashLine))
        path.setZValue(5)
        self.scene().addItem(path)
        self._drag_link = (item, is_out, sock, path)
        self._update_drag(sp)

    def _update_drag(self, sp):
        item, is_out, sock, path = self._drag_link
        a = item.socket_scene_pos(is_out, sock.identifier) or sp
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
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._pan is not None and ev.button() == QtCore.Qt.MiddleButton:
            self._pan = None
            self.unsetCursor()
            return
        if self._drag_link is not None:
            item, is_out, sock, path = self._drag_link
            self._drag_link = None
            self.scene().removeItem(path)
            sp = self.mapToScene(ev.position().toPoint())
            target = self._item_at(ev.position().toPoint())
            if target is not None and target is not item:
                hit = target.socket_at(sp)
                if hit is not None and hit[0] != is_out:
                    out_s, in_s = (sock, hit[1]) if is_out else (hit[1], sock)
                    try:
                        self.editor.tree.links.new(out_s, in_s)
                    except Exception as ex:
                        bridge.log(str(ex), "ERROR")
            bridge.undo_push("Link")
            self.editor.rebuild()
            return
        super().mouseReleaseEvent(ev)
        if self._moving:
            self._moving = False
            self.editor.commit_positions()
        self.editor.commit_selection()

    def mouseDoubleClickEvent(self, ev):
        it = self._item_at(ev.position().toPoint())
        if it is not None and getattr(it.node, "node_tree", None) is not None and it.kind == "node":
            self.editor.enter_group(it.node)
            return
        super().mouseDoubleClickEvent(ev)

    def keyPressEvent(self, ev):
        k = ev.key()
        mods = ev.modifiers()
        K = QtCore.Qt
        if k in (K.Key_X, K.Key_Delete):
            self.editor.delete_selected()
        elif k == K.Key_A and mods & K.ShiftModifier:
            self.editor.add_node_popup(QtGui.QCursor.pos(), self.mapToScene(self.mapFromGlobal(QtGui.QCursor.pos())))
        elif k == K.Key_A and mods & K.AltModifier:
            for it in self.scene().selectedItems():
                it.setSelected(False)
            self.editor.commit_selection()
        elif k == K.Key_A:
            for it in self.editor.items.values():
                it.setSelected(True)
            self.editor.commit_selection()
        elif k == K.Key_M:
            self.editor.toggle("mute")
        elif k == K.Key_H:
            self.editor.toggle("hide")
        elif k == K.Key_Home:
            self.editor.frame_all()
        elif k == K.Key_Tab:
            sel = [it for it in self.scene().selectedItems() if isinstance(it, NodeItem)]
            if sel and getattr(sel[0].node, "node_tree", None) is not None:
                self.editor.enter_group(sel[0].node)
            else:
                self.editor.exit_group()
        else:
            super().keyPressEvent(ev)

    def focusNextPrevChild(self, _n):
        return False


# ---------------------------------------------------------------- hledání typů uzlů
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
        self.edit.setPlaceholderText("Hledat uzel…")
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
SOURCES = [("SHADER", "Shader (materiál)"), ("WORLD", "Svět"), ("GEOMETRY", "Geometry Nodes"),
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
        self.source.activated.connect(lambda _i: self._reset())
        bar.addWidget(self.source)
        self.path_label = QtWidgets.QLabel("")
        self.path_label.setProperty("dim", True)
        bar.addWidget(self.path_label, 1)
        self.up_btn = QtWidgets.QToolButton()
        self.up_btn.setText("↑ Ze skupiny")
        self.up_btn.clicked.connect(self.exit_group)
        bar.addWidget(self.up_btn)
        self.new_btn = QtWidgets.QToolButton()
        self.new_btn.setText("+ Nový strom")
        self.new_btn.clicked.connect(self.new_tree)
        bar.addWidget(self.new_btn)
        add = QtWidgets.QToolButton()
        add.setText("+ Přidat uzel (Shift+A)")
        add.clicked.connect(lambda: self.add_node_popup(QtGui.QCursor.pos(), self.view.mapToScene(
            self.view.viewport().rect().center())))
        bar.addWidget(add)
        fit = QtWidgets.QToolButton()
        fit.setText("⤢")
        fit.setToolTip("Zobrazit vše (Home)")
        fit.clicked.connect(self.frame_all)
        bar.addWidget(fit)
        lay.addLayout(bar)
        split = QtWidgets.QSplitter()
        self.scene = QtWidgets.QGraphicsScene(self)
        self.scene.setSceneRect(-20000, -20000, 40000, 40000)
        self.view = NodeView(self)
        self.view.setScene(self.scene)
        split.addWidget(self.view)
        self.side = QtWidgets.QScrollArea()
        self.side.setWidgetResizable(True)
        self.side.setMinimumWidth(220)
        split.addWidget(self.side)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)
        self.side_bindings = []
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.refresh)
        hub.data_changed.connect(lambda: self._timer.start())
        hub.selection_changed.connect(lambda: (self.group_stack.clear(), self._timer.start()))
        hub.file_loaded.connect(self._reset)
        hub.undo_done.connect(self._reset)
        self._first_frame = True
        self._reset()

    # --- strom
    def base_tree(self):
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
            return scene.node_tree if getattr(scene, "use_nodes", False) else None
        return None

    def current_tree(self):
        while self.group_stack:
            try:
                return self.group_stack[-1].node_tree
            except ReferenceError:
                self.group_stack.pop()
        return self.base_tree()

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
                          tuple(str(getattr(n, p.identifier)) for p in node_buttons(n))))
        for lk in tree.links:
            parts.append((lk.from_node.name, lk.from_socket.identifier, lk.to_node.name,
                          lk.to_socket.identifier, getattr(lk, "is_muted", False)))
        return hash(tuple(parts))

    def refresh(self):
        if self.view._drag_link is not None or self.view._moving or QtWidgets.QApplication.mouseButtons():
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
            t = self.scene.addText("Žádný strom uzlů – vyber zdroj nahoře nebo klikni na „+ Nový strom“.")
            t.setDefaultTextColor(QtGui.QColor("#9a9a9a"))
            self._build_side()
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

    def update_links(self):
        for li in self.links:
            li.update_path()

    def dirty_structure(self):
        self._sig = None

    # --- operace
    def set_active(self, item):
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
            try:
                it.node.select = it.isSelected()
            except ReferenceError:
                pass
        self.view.viewport().update()

    def commit_positions(self):
        changed = False
        for it in self.items.values():
            try:
                node = it.node
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
            try:
                self.tree.nodes.remove(it.node)
            except Exception as ex:
                bridge.log(str(ex), "ERROR")
        if sel:
            bridge.undo_push("Delete Nodes")
            self.rebuild()

    def toggle(self, attr):
        sel = [it for it in self.scene.selectedItems() if isinstance(it, NodeItem)]
        for it in sel:
            try:
                setattr(it.node, attr, not getattr(it.node, attr))
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
            self.rebuild()
        dlg = AddNodePopup(self, types, pick)
        dlg.move(gpos)
        dlg.show()
        dlg.edit.setFocus()

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
        rect = QtCore.QRectF()
        for it in self.items.values():
            rect = rect.united(it.sceneBoundingRect())
        if rect.isNull():
            return
        self.view.fitInView(rect.adjusted(-60, -60, 60, 60), QtCore.Qt.KeepAspectRatio)
        if self.view.transform().m11() > 1.2:
            s = 1.2 / self.view.transform().m11()
            self.view.scale(s, s)

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
                if hasattr(scene, "compositing_node_group"):
                    ng = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
                    scene.compositing_node_group = ng
                    ng.nodes.new("CompositorNodeRLayers").location = (-300, 0)
                    try:
                        ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
                        ng.nodes.new("NodeGroupOutput").location = (200, 0)
                    except Exception:
                        pass
                else:
                    scene.use_nodes = True
        except Exception as ex:
            bridge.log(str(ex), "ERROR")
        bridge.undo_push("New Node Tree")
        self._reset()

    # --- postranní panel
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
            lay.addWidget(QtWidgets.QLabel("Vyber uzel."))
            lay.addStretch(1)
            self.side.setWidget(host)
            return
        title = QtWidgets.QLabel(f"<b>{node_title(node)}</b>")
        lay.addWidget(title)

        def changed(*_a):
            self._timer.start()
            self.view.viewport().update()
            undo()

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
            lab = QtWidgets.QLabel("Vstupy")
            lab.setStyleSheet("font-weight:bold; margin-top:6px;")
            lay.addWidget(lab)
            for s in ins:
                b, label = rw.make_binding(s, "default_value", text=tr(s.name), on_change=changed)
                if b is not None:
                    self.side_bindings.append(b)
                    if isinstance(b, rw.BoolBinding):
                        b.widget.setText(label)
                        lay.addWidget(b.widget)
                    else:
                        lay.addWidget(rw.labeled_row(label, b.widget))
        lay.addStretch(1)
        self.side.setWidget(host)

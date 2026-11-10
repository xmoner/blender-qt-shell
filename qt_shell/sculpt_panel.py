"""Sculpt panel (dock) – Blender's sculpt tools with Maya's Sculpt Tool Settings layout.

* Brushes: Blender's essentials sculpt brushes in four groups (Add / Subtract, Contrast, Transform, Mask &
  Face Sets) as icon buttons; tooltips name the Maya tool that does the same (Sculpt, Wax, Knife, Bulge …).
* Brush: radius (px) and strength with pen-pressure toggles, direction, falloff curve, hardness, auto smooth,
  spacing, front faces only, accumulate – the settings of the active brush, rebuilt when it changes.
* Symmetry: mirror X / Y / Z, Symmetrize.
* Topology: Dynamic Topology (+ detail), Voxel Remesh (voxel size), Multiresolution (add, subdivide, levels).
* Mask / Face Sets / Visibility / Mesh Filters: one-click buttons (Maya's "Freeze" tools and mesh-wide filters).
* Display: brush circle, mask and face set overlays.

Strokes themselves are drawn in the 3D view (sculpt.py). The panel opens the first time Sculpt Mode is entered
(Window menu: Sculpt).
"""
import math

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import blicons, bridge, sculpt, theme
from . import rna_widgets as rw

ADD, CONTRAST, TRANSFORM, GENERAL = "Add / Subtract", "Contrast", "Transform", "Mask · Face Sets"
GROUP_COLORS = {ADD: "#5b8fd6", CONTRAST: "#d6995b", TRANSFORM: "#62b072", GENERAL: "#a07ad0",
                "Paint": "#c9566f", "Blend": "#4fa3a8",      # the paint panels (paint_panel.py)
                "Erase": "#7d8696", "Tools": "#c08a32"}

# (Blender brush asset name, glyph, group, Maya equivalent / note)
BRUSHES = [
    ("Draw", "draw", ADD, "Maya: Sculpt"),
    ("Draw Sharp", "draw_sharp", ADD, "Maya: Knife"),
    ("Clay", "clay", ADD, "Maya: Wax"),
    ("Clay Strips", "clay_strips", ADD, "Maya: Wax (flat strips)"),
    ("Clay Thumb", "clay_thumb", ADD, "Maya: Foamy"),
    ("Layer", "layer", ADD, "Maya: Imprint (constant height)"),
    ("Inflate/Deflate", "inflate", ADD, "Maya: Bulge"),
    ("Blob", "blob", ADD, "Round bulges"),
    ("Crease Polish", "crease", ADD, "Maya: Knife (crease)"),
    ("Smooth", "smooth", CONTRAST, "Maya: Smooth"),
    ("Flatten/Contrast", "flatten", CONTRAST, "Maya: Flatten"),
    ("Fill/Deepen", "fill", CONTRAST, "Maya: Fill"),
    ("Scrape/Fill", "scrape", CONTRAST, "Maya: Scrape"),
    ("Plateau", "plateau", CONTRAST, "Flat tops"),
    ("Pinch/Magnify", "pinch", CONTRAST, "Maya: Pinch"),
    ("Relax Slide", "relax", CONTRAST, "Maya: Relax"),
    ("Sharpen", "sharpen", CONTRAST, "Maya: Amplify"),
    ("Grab", "grab", TRANSFORM, "Maya: Grab"),
    ("Elastic Grab", "elastic", TRANSFORM, "Soft, volume-keeping grab"),
    ("Snake Hook", "snake", TRANSFORM, "Pulls out long shapes"),
    ("Thumb", "thumb", TRANSFORM, "Maya: Smear"),
    ("Nudge", "nudge", TRANSFORM, "Maya: Smear (along the surface)"),
    ("Pose", "pose", TRANSFORM, "Bends parts like a bone"),
    ("Twist", "twist", TRANSFORM, "Rotates the surface under the brush"),
    ("Boundary", "boundary", TRANSFORM, "Deforms open borders"),
    ("Mask", "mask", GENERAL, "Maya: Freeze"),
    ("Face Set Paint", "faceset", GENERAL, "Paints face sets"),
    ("Erase Multires Displacement", "erase", GENERAL, "Removes multires detail"),
]


# ---------------------------------------------------------------- brush icons (drawn, 24 × 24 design grid)
def _glyph(p, kind, fg):
    pen = QtGui.QPen(fg, 1.8, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.NoBrush)
    P = QtGui.QPainterPath

    def surf(path_pts, fill=False):
        path = P()
        path.moveTo(*path_pts[0])
        for pt in path_pts[1:]:
            if len(pt) == 2:
                path.lineTo(*pt)
            else:
                path.cubicTo(*pt)
        if fill:
            path.lineTo(21, 21)
            path.lineTo(3, 21)
            path.closeSubpath()
            p.setBrush(QtGui.QColor(fg.red(), fg.green(), fg.blue(), 70))
            p.drawPath(path)
            p.setBrush(QtCore.Qt.NoBrush)
        else:
            p.drawPath(path)

    def arrow(x1, y1, x2, y2, head=3.0):
        p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))
        a = math.atan2(y2 - y1, x2 - x1)
        for s in (2.5, -2.5):
            p.drawLine(QtCore.QPointF(x2, y2),
                       QtCore.QPointF(x2 - head * math.cos(a + s * 0.25), y2 - head * math.sin(a + s * 0.25)))

    k = kind
    if k == "draw":
        surf([(3, 17), (8, 17, 9, 8, 12, 8), (15, 8, 16, 17, 21, 17)], fill=True)
    elif k == "draw_sharp":
        surf([(3, 17), (10, 17), (12, 6), (14, 17), (21, 17)], fill=True)
    elif k == "clay":
        surf([(3, 17), (6, 17, 7, 11, 10, 11), (14, 11), (17, 11, 18, 17, 21, 17)], fill=True)
    elif k == "clay_strips":
        surf([(3, 17), (6, 17), (6, 11), (18, 11), (18, 17), (21, 17)], fill=True)
    elif k == "clay_thumb":
        surf([(3, 17), (21, 17)])
        p.drawEllipse(QtCore.QRectF(7, 7, 10, 7))
    elif k == "layer":
        surf([(3, 18), (7, 18), (7, 12), (17, 12), (17, 18), (21, 18)], fill=True)
        p.drawLine(QtCore.QPointF(7, 9), QtCore.QPointF(17, 9))
    elif k == "inflate":
        p.drawEllipse(QtCore.QRectF(8, 8, 8, 8))
        for a in range(0, 360, 90):
            r = math.radians(a + 45)
            arrow(12 + 5 * math.cos(r), 12 + 5 * math.sin(r), 12 + 9.5 * math.cos(r), 12 + 9.5 * math.sin(r), 2.5)
    elif k == "blob":
        surf([(3, 18), (5, 18, 5, 7, 12, 7), (19, 7, 19, 18, 21, 18)], fill=True)
    elif k == "crease":
        surf([(3, 9), (10, 9), (12, 18), (14, 9), (21, 9)])
    elif k == "smooth":
        surf([(3, 10), (6, 4, 9, 16, 12, 10), (15, 4, 18, 16, 21, 10)])
        surf([(3, 17), (21, 17)])
    elif k == "flatten":
        surf([(3, 15), (6, 9, 9, 18, 12, 13), (15, 8, 18, 17, 21, 14)])
        p.drawLine(QtCore.QPointF(3, 19), QtCore.QPointF(21, 19))
        arrow(12, 3, 12, 8)
    elif k == "fill":
        surf([(3, 9), (8, 9, 9, 19, 12, 19), (15, 19, 16, 9, 21, 9)])
        p.setBrush(QtGui.QColor(fg.red(), fg.green(), fg.blue(), 90))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(7, 13), QtCore.QPointF(17, 13), QtCore.QPointF(15, 18),
                                       QtCore.QPointF(9, 18)]))
    elif k == "scrape":
        surf([(3, 17), (6, 9), (9, 17), (12, 9), (15, 17), (18, 9), (21, 17)])
        p.drawLine(QtCore.QPointF(2, 12), QtCore.QPointF(22, 12))
    elif k == "plateau":
        surf([(3, 18), (8, 9), (16, 9), (21, 18)], fill=True)
    elif k == "pinch":
        arrow(3, 12, 9, 12)
        arrow(21, 12, 15, 12)
        arrow(12, 3, 12, 9)
        arrow(12, 21, 12, 15)
    elif k == "relax":
        for y in (7, 12, 17):
            p.drawLine(QtCore.QPointF(4, y), QtCore.QPointF(20, y))
        for x in (7, 12, 17):
            p.drawLine(QtCore.QPointF(x, 4), QtCore.QPointF(x, 20))
    elif k == "sharpen":
        surf([(3, 17), (6, 7), (9, 17), (12, 4), (15, 17), (18, 7), (21, 17)])
    elif k == "grab":
        p.drawEllipse(QtCore.QRectF(4, 11, 8, 8))
        arrow(9, 14, 20, 5)
    elif k == "elastic":
        path = P()
        path.moveTo(4, 18)
        for i in range(6):
            path.lineTo(6 + i * 2.2, 15 if i % 2 else 19)
        p.drawPath(path)
        arrow(17, 17, 21, 6)
    elif k == "snake":
        path = P()
        path.moveTo(4, 19)
        path.cubicTo(10, 19, 6, 8, 13, 8)
        path.cubicTo(18, 8, 19, 13, 20, 5)
        p.drawPath(path)
        arrow(19.5, 9, 20, 4, 3)
    elif k == "thumb":
        surf([(3, 18), (21, 18)])
        p.drawEllipse(QtCore.QRectF(5, 9, 8, 6))
        arrow(12, 12, 21, 12)
    elif k == "nudge":
        surf([(3, 18), (9, 18, 10, 12, 13, 12), (16, 12, 17, 18, 21, 18)])
        arrow(5, 8, 19, 8)
    elif k == "pose":
        p.drawLine(QtCore.QPointF(5, 19), QtCore.QPointF(12, 12))
        p.drawLine(QtCore.QPointF(12, 12), QtCore.QPointF(19, 6))
        p.setBrush(fg)
        for c in ((5, 19), (12, 12), (19, 6)):
            p.drawEllipse(QtCore.QPointF(*c), 2.2, 2.2)
    elif k == "twist":
        p.drawArc(QtCore.QRectF(5, 5, 14, 14), 30 * 16, 290 * 16)
        arrow(16.5, 6.8, 18.6, 9.5, 3)
    elif k == "boundary":
        for (x1, y1, x2, y2, x3, y3) in ((4, 9, 4, 4, 9, 4), (15, 4, 20, 4, 20, 9), (20, 15, 20, 20, 15, 20),
                                         (9, 20, 4, 20, 4, 15)):
            path = P()
            path.moveTo(x1, y1)
            path.lineTo(x2, y2)
            path.lineTo(x3, y3)
            p.drawPath(path)
        arrow(12, 12, 18, 6, 2.5)
    elif k == "mask":
        p.drawEllipse(QtCore.QRectF(4, 4, 16, 16))
        path = P()
        path.moveTo(12, 4)
        path.arcTo(QtCore.QRectF(4, 4, 16, 16), 90, 180)
        path.closeSubpath()
        p.setBrush(QtGui.QColor(20, 20, 20, 200))
        p.drawPath(path)
    elif k == "faceset":
        p.setPen(QtCore.Qt.NoPen)
        for (x, y, c) in ((4, 4, "#e66b6b"), (12.5, 4, "#6bc06b"), (4, 12.5, "#6b9be6"), (12.5, 12.5, "#e6c86b")):
            p.setBrush(QtGui.QColor(c))
            p.drawRoundedRect(QtCore.QRectF(x, y, 7.5, 7.5), 1.5, 1.5)
    elif k == "erase":
        surf([(3, 18), (21, 18)])
        p.save()
        p.translate(12, 10)
        p.rotate(-30)
        p.drawRoundedRect(QtCore.QRectF(-6, -3.5, 12, 7), 1.5, 1.5)
        p.drawLine(QtCore.QPointF(0, -3.5), QtCore.QPointF(0, 3.5))
        p.restore()
    elif k in ("paint_hard", "paint_hard_p"):
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(fg)
        p.drawEllipse(QtCore.QRectF(5, 5, 14, 14))
    elif k in ("paint_soft", "paint_soft_p"):
        g = QtGui.QRadialGradient(QtCore.QPointF(12, 12), 8.5)
        g.setColorAt(0.0, fg)
        g.setColorAt(0.45, QtGui.QColor(fg.red(), fg.green(), fg.blue(), 200))
        g.setColorAt(1.0, QtGui.QColor(fg.red(), fg.green(), fg.blue(), 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QtCore.QRectF(3, 3, 18, 18))
    elif k == "airbrush":
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(fg)
        for (x, y, r) in ((12, 12, 1.6), (8, 9, 1.2), (15.5, 8, 1.1), (16, 14.5, 1.3), (9, 15.5, 1.2),
                          (12, 6, 0.9), (5.5, 12.5, 0.9), (18.5, 11, 0.9), (12.5, 18, 1.0), (6.5, 6.5, 0.7),
                          (17.5, 18, 0.8), (6, 18, 0.7), (18, 5.5, 0.7)):
            p.drawEllipse(QtCore.QPointF(x, y), r, r)
    elif k == "blur":
        p.setPen(QtCore.Qt.NoPen)
        for (x, a) in ((8, 110), (12, 150), (16, 110)):
            g = QtGui.QRadialGradient(QtCore.QPointF(x, 12), 6)
            g.setColorAt(0.0, QtGui.QColor(fg.red(), fg.green(), fg.blue(), a))
            g.setColorAt(1.0, QtGui.QColor(fg.red(), fg.green(), fg.blue(), 0))
            p.setBrush(g)
            p.drawEllipse(QtCore.QPointF(x, 12), 6, 6)
    elif k == "average":
        p.setBrush(fg)
        p.drawEllipse(QtCore.QPointF(12, 12), 2.2, 2.2)
        p.setBrush(QtCore.Qt.NoBrush)
        arrow(4, 4, 9, 9, 2.5)
        arrow(20, 4, 15, 9, 2.5)
        arrow(4, 20, 9, 15, 2.5)
        arrow(20, 20, 15, 15, 2.5)
    elif k == "smear":
        p.setPen(QtCore.Qt.NoPen)
        g = QtGui.QLinearGradient(3, 12, 17, 12)
        g.setColorAt(0.0, QtGui.QColor(fg.red(), fg.green(), fg.blue(), 0))
        g.setColorAt(1.0, fg)
        p.setBrush(g)
        p.drawRoundedRect(QtCore.QRectF(3, 8, 14, 8), 4, 4)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        arrow(15, 12, 21, 12, 2.5)
    elif k in ("pixel", "erase_pixel"):
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(fg)
        for (x, y) in ((8, 5), (12, 5), (4, 9), (8, 9), (12, 9), (16, 9), (4, 13), (8, 13), (12, 13),
                       (16, 13), (8, 17), (12, 17)):
            p.drawRect(QtCore.QRectF(x, y, 3.4, 3.4))
        if k == "erase_pixel":
            p.setPen(QtGui.QPen(QtGui.QColor(30, 30, 30, 230), 2.2))
            p.drawLine(QtCore.QPointF(4, 20), QtCore.QPointF(20, 4))
    elif k in ("erase_hard", "erase_soft", "erase_hard_p"):
        p.save()
        p.translate(12, 12)
        p.rotate(-35)
        if k == "erase_soft":
            g = QtGui.QLinearGradient(-8, 0, 8, 0)
            g.setColorAt(0, QtGui.QColor(fg.red(), fg.green(), fg.blue(), 60))
            g.setColorAt(1, fg)
            p.setBrush(g)
        else:
            p.setBrush(QtGui.QColor(fg.red(), fg.green(), fg.blue(), 70))
        p.drawRoundedRect(QtCore.QRectF(-8, -4.5, 16, 9), 1.8, 1.8)
        p.drawLine(QtCore.QPointF(-1, -4.5), QtCore.QPointF(-1, 4.5))
        p.restore()
    elif k == "bucket":
        p.save()
        p.translate(11, 13)
        p.rotate(-25)
        p.setBrush(QtGui.QColor(fg.red(), fg.green(), fg.blue(), 70))
        p.drawRoundedRect(QtCore.QRectF(-6, -5, 12, 11), 1.5, 1.5)
        p.restore()
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(fg)
        path = P()
        path.moveTo(19, 13)
        path.cubicTo(17, 17, 17.5, 20, 19, 20)
        path.cubicTo(20.5, 20, 21, 17, 19, 13)
        p.drawPath(path)
    elif k == "clone":
        p.drawEllipse(QtCore.QPointF(8, 9), 4.5, 4.5)
        p.setPen(QtGui.QPen(fg, 1.4, QtCore.Qt.DashLine))
        p.drawEllipse(QtCore.QPointF(16, 15), 4.5, 4.5)
        p.setPen(pen)
        arrow(10.5, 11.5, 14, 13.5, 2.2)
    else:
        p.drawEllipse(QtCore.QRectF(6, 6, 12, 12))
    if k.endswith("_p"):                      # pen pressure: a small pen in the corner
        p.setPen(QtGui.QPen(QtGui.QColor(30, 30, 30, 220), 1.0))
        p.setBrush(QtGui.QColor(255, 255, 255))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(14.5, 22.5), QtCore.QPointF(15.5, 18.5),
                                       QtCore.QPointF(22, 12), QtCore.QPointF(23.5, 13.5),
                                       QtCore.QPointF(17, 20)]))


_icon_cache = {}


def brush_icon(kind, group, size=None):
    key = (kind, group)
    ic = _icon_cache.get(key)
    if ic is not None:
        return ic
    ic = QtGui.QIcon()
    base = QtGui.QColor(GROUP_COLORS.get(group, "#888888"))
    for px in (24, 32, 48, 64, 96, 128):
        img = QtGui.QImage(px, px, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.scale(px / 24.0, px / 24.0)
        g = QtGui.QLinearGradient(0, 0, 0, 24)
        g.setColorAt(0, base.lighter(118))
        g.setColorAt(1, base.darker(135))
        p.setPen(QtGui.QPen(base.darker(170), 0.8))
        p.setBrush(g)
        p.drawRoundedRect(QtCore.QRectF(0.5, 0.5, 23, 23), 4.5, 4.5)
        _glyph(p, kind, QtGui.QColor("#ffffff"))
        p.end()
        ic.addPixmap(QtGui.QPixmap.fromImage(img))
    _icon_cache[key] = ic
    return ic


def brush_entry(name):
    for e in BRUSHES:
        if e[0] == name:
            return e
    return None


def _active_mesh_object():
    try:
        ob = bpy.context.view_layer.objects.active
        return ob if ob is not None and ob.type == "MESH" else None
    except (ReferenceError, AttributeError):
        return None


# ---------------------------------------------------------------- panel
def _ptr(data):
    try:
        return data.as_pointer()
    except Exception:
        return 0


class SculptPanel(QtWidgets.QScrollArea):
    def __init__(self, hub=None, parent=None):
        super().__init__(parent)
        self.hub = hub
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        body = QtWidgets.QWidget(self)
        self.setWidget(body)
        self.lay = QtWidgets.QVBoxLayout(body)
        self.lay.setContentsMargins(6, 6, 6, 6)
        self.lay.setSpacing(6)
        self._state = {}
        self._bindings = []
        self._brush_key = None
        self._ob_key = None

        # header: the active brush
        head = QtWidgets.QHBoxLayout()
        self.head_icon = QtWidgets.QLabel(body)
        self.head_icon.setFixedSize(theme.px(36), theme.px(36))
        head.addWidget(self.head_icon)
        hv = QtWidgets.QVBoxLayout()
        self.head_name = QtWidgets.QLabel("—", body)
        f = self.head_name.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.15)
        self.head_name.setFont(f)
        self.head_note = QtWidgets.QLabel("", body)
        self.head_note.setStyleSheet("color:#9a9a9a;")
        hv.addWidget(self.head_name)
        hv.addWidget(self.head_note)
        head.addLayout(hv, 1)
        self.lay.addLayout(head)
        self.hint = QtWidgets.QLabel("", body)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#c9a85b;")
        self.lay.addWidget(self.hint)

        # brushes
        self.brush_btns = {}
        grp = QtWidgets.QButtonGroup(body)
        grp.setExclusive(True)
        bsec = self._section("Brushes", "brushes")
        # icon size (QSettings sculpt/brush_icon_size) – the grids re-flow to the panel width
        srow = QtWidgets.QHBoxLayout()
        slab = QtWidgets.QLabel("Icon Size", body)
        slab.setStyleSheet("color:#9a9a9a;")
        srow.addWidget(slab)
        self.icon_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, body)
        self.icon_slider.setRange(16, 96)
        self.icon_slider.setValue(self._icon_size())
        self.icon_slider.setToolTip("Size of the brush icons")
        self.icon_slider.valueChanged.connect(self._set_icon_size)
        srow.addWidget(self.icon_slider, 1)
        self.icon_size_lab = QtWidgets.QLabel(f"{self._icon_size()} px", body)
        self.icon_size_lab.setMinimumWidth(theme.px(40))
        srow.addWidget(self.icon_size_lab)
        bsec.addLayout(srow)
        self._brush_grids = []                  # (grid, [buttons])
        for group in (ADD, CONTRAST, TRANSFORM, GENERAL):
            lab = QtWidgets.QLabel(group, body)
            lab.setStyleSheet(f"color:{GROUP_COLORS[group]}; font-weight:bold;")
            bsec.addWidget(lab)
            grid = QtWidgets.QGridLayout()
            grid.setSpacing(3)
            items = [b for b in BRUSHES if b[2] == group]
            for i, (name, glyph, g, note) in enumerate(items):
                b = QtWidgets.QToolButton(body)
                b.setIcon(brush_icon(glyph, g))
                b.setCheckable(True)
                b.setAutoRaise(True)
                b.setToolTip(f"<b>{name}</b><br>{note}")
                self._style_brush_btn(b, self._icon_size())
                b.clicked.connect(lambda _=False, n=name: self.pick_brush(n))
                grp.addButton(b)
                self.brush_btns[name] = b
            self._brush_grids.append((grid, [self.brush_btns[e[0]] for e in items]))
            bsec.addLayout(grid)
        self._cols = 0
        self._flow_brushes()

        # sections rebuilt with the brush / object
        self.brush_sec = self._section("Brush", "brush")
        self.sym_sec = self._section("Symmetry", "symmetry")
        self.topo_sec = self._section("Topology – Dyntopo · Remesh · Multires", "topology")
        msec = self._section("Mask", "mask", closed=False)
        self._buttons(msec, [
            ("Clear", "X", "paint.mask_flood_fill", {"mode": "VALUE", "value": 0.0}, "Clear the mask (nothing masked)"),
            ("Fill", "MOD_MASK", "paint.mask_flood_fill", {"mode": "VALUE", "value": 1.0}, "Mask everything"),
            ("Invert", "IMAGE_ALPHA", "paint.mask_flood_fill", {"mode": "INVERT"}, "Invert the mask"),
            ("Grow", "ADD", "sculpt.mask_filter", {"filter_type": "GROW"}, "Grow the mask"),
            ("Shrink", "REMOVE", "sculpt.mask_filter", {"filter_type": "SHRINK"}, "Shrink the mask"),
            ("Smooth", "MOD_SMOOTH", "sculpt.mask_filter", {"filter_type": "SMOOTH"}, "Soften the mask edge"),
            ("Sharpen", "SHARPCURVE", "sculpt.mask_filter", {"filter_type": "SHARPEN"}, "Sharpen the mask edge"),
            ("From Cavity", "MOD_MASK", "sculpt.mask_from_cavity", {"settings_source": "OPERATOR"},
             "Mask the cavities (creases, holes)"),
            ("Extract", "MOD_SOLIDIFY", "sculpt.paint_mask_extract", {}, "New object from the masked part"),
            ("Slice", "MOD_BOOLEAN", "sculpt.paint_mask_slice", {}, "Cut the masked part off"),
        ])
        fsec = self._section("Face Sets", "facesets", closed=True)
        self._buttons(fsec, [
            ("From Masked", "MOD_MASK", "sculpt.face_sets_create", {"mode": "MASKED"}, "Face set from the mask"),
            ("From Visible", "HIDE_OFF", "sculpt.face_sets_create", {"mode": "VISIBLE"}, "Face set from the visible part"),
            ("From Edit Selection", "RESTRICT_SELECT_OFF", "sculpt.face_sets_create", {"mode": "SELECTION"},
             "Face set from the faces selected in Edit Mode"),
            ("By Loose Parts", "STICKY_UVS_DISABLE", "sculpt.face_sets_init", {"mode": "LOOSE_PARTS"},
             "One face set per loose part"),
            ("Random Colours", "COLOR", "sculpt.face_sets_randomize_colors", {}, "New colours for the face sets"),
        ])
        vsec = self._section("Visibility", "visibility", closed=True)
        self._buttons(vsec, [
            ("Show All", "HIDE_OFF", "paint.hide_show_all", {"action": "SHOW"}, "Show all hidden faces"),
            ("Hide Masked", "HIDE_ON", "paint.hide_show_masked", {"action": "HIDE"}, "Hide the masked part"),
            ("Invert Visible", "SELECT_DIFFERENCE", "paint.visibility_invert", {}, "Hide what is shown and show the rest"),
        ])
        flt = self._section("Mesh Filters (whole mesh)", "filters", closed=True)
        self._buttons(flt, [
            ("Smooth", "MOD_SMOOTH", "sculpt.mesh_filter", {"type": "SMOOTH", "strength": 0.5}, "Smooth the whole mesh"),
            ("Inflate", "MOD_SOLIDIFY", "sculpt.mesh_filter", {"type": "INFLATE", "strength": 0.2}, "Inflate the whole mesh"),
            ("Relax", "MOD_SMOOTH", "sculpt.mesh_filter", {"type": "RELAX", "strength": 0.5}, "Relax the topology"),
            ("Sharpen", "SHARPCURVE", "sculpt.mesh_filter", {"type": "SHARPEN", "strength": 0.5}, "Sharpen details"),
            ("Randomize", "RNDCURVE", "sculpt.mesh_filter", {"type": "RANDOM", "strength": 0.1}, "Random noise"),
        ])
        self.disp_sec = self._section("Display", "display", closed=True)
        self.lay.addStretch(1)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.sync)
        sculpt.on_change(self.sync)
        self.sync()

    # ---- brush icon size
    ICON_KEY = "sculpt/brush_icon_size"     # QSettings key of the brush icon size
    STATE_PREFIX = "sculpt"                # QSettings prefix of the sections' open / closed state

    @classmethod
    def _icon_size(cls):
        try:
            v = int(QtCore.QSettings("QtShell", "QtShell").value(cls.ICON_KEY, 26))
        except (TypeError, ValueError):
            v = 26
        return max(16, min(96, v))

    @staticmethod
    def _style_brush_btn(b, size):
        """Icon size of a brush button. The app stylesheet sets qproperty-iconSize on every button when it is
        polished (first show), which undid setIconSize – the saved size was lost after a restart. The button's
        own stylesheet wins over the app one."""
        px = theme.px(int(size))
        b.setStyleSheet(f"QToolButton {{ qproperty-iconSize: {px}px {px}px; }}"
                        f"QToolButton:checked{{background:{theme.HOVER['bg']}; "
                        f"border:1px solid {theme.HOVER['border']}; border-radius:4px;}}")
        b.setIconSize(QtCore.QSize(px, px))

    def _set_icon_size(self, v):
        QtCore.QSettings("QtShell", "QtShell").setValue(self.ICON_KEY, int(v))
        self.icon_size_lab.setText(f"{int(v)} px")
        for _grid, btns in self._brush_grids:
            for b in btns:
                self._style_brush_btn(b, v)
        self._cols = 0
        self._flow_brushes()

    def _flow_brushes(self):
        """As many brush icons per row as fit the panel's width."""
        grids = getattr(self, "_brush_grids", None)
        if not grids:
            return
        grid0, btns0 = grids[0]
        # the button's real width (icon + its frame) + the grid spacing; the sections' frames / margins take ~40 px
        cell = btns0[0].sizeHint().width() + max(grid0.horizontalSpacing(), 0)
        avail = self.viewport().width() - theme.px(40)
        cols = max(1, avail // max(cell, 1))
        if cols == self._cols:
            return
        self._cols = cols
        for grid, btns in grids:
            for b in btns:
                grid.removeWidget(b)
            for c in range(grid.columnCount()):
                grid.setColumnStretch(c, 0)
            for i, b in enumerate(btns):
                grid.addWidget(b, i // cols, i % cols)
            grid.setColumnStretch(cols, 1)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._flow_brushes()

    # ---- building blocks
    def _section(self, title, key, closed=False):
        from .qt_ui import CollapsiblePanel
        panel = CollapsiblePanel(title, f"{self.STATE_PREFIX}/{key}", self._state, closed)
        self.lay.addWidget(panel)
        return panel.body_lay

    def _buttons(self, lay, items, cols=2):
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(3)
        for i, (label, icon, op, props, tip) in enumerate(items):
            b = QtWidgets.QPushButton(label, self.widget())
            if blicons.has(icon):
                b.setIcon(blicons.icon(icon))
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, o=op, pr=props: self._run(o, pr))
            grid.addWidget(b, i // cols, i % cols)
        lay.addLayout(grid)

    def _multires_subdivide(self, name):
        """Subdivide + keep the viewport level with the sculpt level (Object Mode shows the new level)."""
        self._run("object.multires_subdivide", {"modifier": name, "mode": "CATMULL_CLARK"})
        ob = _active_mesh_object()
        mr = ob.modifiers.get(name) if ob is not None else None
        if mr is not None and mr.levels < mr.sculpt_levels:
            mr.levels = mr.sculpt_levels
        self.sync(force=True)

    def _ensure_sculpt(self):
        """Brush / tool buttons used outside Sculpt Mode: the active mesh goes into Sculpt Mode (like
        picking a sculpt tool in Maya). False (with a status message) when there is no mesh to sculpt."""
        if sculpt.active():
            return True
        ob = _active_mesh_object()
        if ob is None:
            bridge.log("Select a mesh object to sculpt – the brushes work in Sculpt Mode.", "INFO")
            return False
        if bpy.context.mode != "OBJECT":
            bridge.run_op("object.mode_set", {"mode": "OBJECT"})
        bridge.run_op("object.mode_set", {"mode": "SCULPT"})
        if not sculpt.active():
            bridge.log(f"{ob.name} could not enter Sculpt Mode.", "INFO")
            return False
        return True

    def _run(self, op, props):
        if not self._ensure_sculpt():
            self.sync(force=True)
            return
        bridge.run_op(op, dict(props))
        self._redraw()
        self.sync(force=True)

    def _redraw(self):
        from . import api
        try:
            mw = api.main_window()
            for v in mw.viewports.views:
                v.request_redraw()
        except Exception:
            pass

    def _clear(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            elif it.layout() is not None:
                self._clear(it.layout())

    def _row(self, lay, label, data, prop, **kw):
        b, name = rw.make_binding(data, prop, on_change=lambda *_a: self._redraw(), **kw)
        if b is None:
            return None
        self._bindings.append(b)
        row = QtWidgets.QHBoxLayout()
        lab = QtWidgets.QLabel(label if label is not None else (name or prop), self.widget())
        lab.setMinimumWidth(theme.px(78))
        if kw.get("columns"):          # several rows of buttons: label at the first row
            row.addWidget(lab, 0, QtCore.Qt.AlignTop)
            lab.setMinimumHeight(b.widget.sizeHint().height() // max(1, b.widget.layout().rowCount()))
        else:
            row.addWidget(lab)
        row.addWidget(b.widget, 1)
        lay.addLayout(row)
        return b

    def _toggle(self, lay, text, data, prop, icon=None, row=None):
        b = rw.BoolBinding(data, prop, text, 1, False, lambda *_a: self._redraw())
        if icon and blicons.has(icon):
            b.widget.setIcon(blicons.icon(icon))
        try:
            rw.set_prop_tooltip(b.widget, rw.rna_prop(data, prop))
        except Exception:
            pass
        self._bindings.append(b)
        (row or lay).addWidget(b.widget)
        return b

    # ---- sections that follow the brush / object
    def _build_brush(self):
        lay = self.brush_sec
        self._clear(lay)
        self._bindings = [b for b in self._bindings if b.alive()]
        br = sculpt.brush()
        if br is None:
            lay.addWidget(QtWidgets.QLabel("No brush.", self.widget()))
            return
        size_owner = sculpt._size_owner()
        str_owner = sculpt._strength_owner()
        r = QtWidgets.QHBoxLayout()
        self._row_into(r, "Radius", size_owner, "size")
        self._toggle(None, "", br, "use_pressure_size", "STYLUS_PRESSURE", row=r).widget.setToolTip(
            "Pen pressure changes the radius")
        lay.addLayout(r)
        r = QtWidgets.QHBoxLayout()
        self._row_into(r, "Strength", str_owner, "strength")
        self._toggle(None, "", br, "use_pressure_strength", "STYLUS_PRESSURE", row=r).widget.setToolTip(
            "Pen pressure changes the strength")
        lay.addLayout(r)
        try:
            items = [e.identifier for e in br.bl_rna.properties["direction"].enum_items]
        except Exception:
            items = []
        if len(items) > 1:
            self._row(lay, "Direction", br, "direction", expand=True)
        for label, prop in (("Hardness", "hardness"), ("Auto Smooth", "auto_smooth_factor"),
                            ("Spacing %", "spacing")):
            if prop in br.bl_rna.properties:
                self._row(lay, label, br, prop)
        if "curve_distance_falloff_preset" in br.bl_rna.properties:
            self._row(lay, "Falloff", br, "curve_distance_falloff_preset", expand=True, columns=2)
        r = QtWidgets.QHBoxLayout()
        for text, prop, icon in (("Front Faces Only", "use_frontface", "FACESEL"),
                                 ("Accumulate", "use_accumulate", "ADD")):
            if prop in br.bl_rna.properties:
                self._toggle(None, text, br, prop, icon, row=r)
        lay.addLayout(r)
        u = sculpt.unified()
        if u is not None:
            r = QtWidgets.QHBoxLayout()
            self._toggle(None, "Same Radius for All Brushes", u, "use_unified_size", "LINKED", row=r)
            self._toggle(None, "Same Strength", u, "use_unified_strength", "LINKED", row=r)
            lay.addLayout(r)
        tip = QtWidgets.QLabel("Drag in the view to sculpt · Ctrl: subtract · Shift: smooth · "
                               + self._keys_hint(), self.widget())
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8a8a8a;")
        lay.addWidget(tip)

    def _keys_hint(self):
        from . import keymap
        return keymap.render("{sculpt.radius}: radius · {sculpt.strength}: strength · "
                             "{sculpt.radius_down} / {sculpt.radius_up}: smaller / bigger")

    def _row_into(self, row, label, data, prop):
        b, name = rw.make_binding(data, prop, on_change=lambda *_a: self._redraw())
        if b is None:
            return None
        self._bindings.append(b)
        lab = QtWidgets.QLabel(label, self.widget())
        lab.setMinimumWidth(theme.px(78))
        row.addWidget(lab)
        row.addWidget(b.widget, 1)
        return b

    def _build_object(self):
        ob = _active_mesh_object()
        for lay in (self.sym_sec, self.topo_sec, self.disp_sec):
            self._clear(lay)
        self._bindings = [b for b in self._bindings if b.alive()]
        if ob is None:
            self.sym_sec.addWidget(QtWidgets.QLabel("Select a mesh.", self.widget()))
            return
        me = ob.data
        s = sculpt.sculpt_settings()
        # symmetry
        r = QtWidgets.QHBoxLayout()
        for ax in "xyz":
            self._toggle(None, ax.upper(), me, f"use_mirror_{ax}", row=r).widget.setToolTip(
                f"Mirror the strokes across the {ax.upper()} axis")
        self.sym_sec.addLayout(r)
        if s is not None and "symmetrize_direction" in s.bl_rna.properties:
            self._row(self.sym_sec, "Direction", s, "symmetrize_direction")
            b = QtWidgets.QPushButton("Symmetrize", self.widget())
            if blicons.has("MOD_MIRROR"):
                b.setIcon(blicons.icon("MOD_MIRROR"))
            b.setToolTip("Make the mesh symmetrical in the chosen direction")
            b.clicked.connect(lambda _=False: self._run("sculpt.symmetrize", {}))
            self.sym_sec.addWidget(b)
        # dyntopo
        dyn = bool(getattr(ob, "use_dynamic_topology_sculpting", False))
        db = QtWidgets.QPushButton("Dynamic Topology", self.widget())
        db.setCheckable(True)
        db.setChecked(dyn)
        if blicons.has("MOD_REMESH"):
            db.setIcon(blicons.icon("MOD_REMESH"))
        db.setToolTip("Dyntopo: the brush adds and removes detail where it works")
        db.clicked.connect(lambda _=False: self._run("sculpt.dynamic_topology_toggle", {}))
        self.topo_sec.addWidget(db)
        if dyn and s is not None:
            self._row(self.topo_sec, "Detailing", s, "detail_type_method")
            method = getattr(s, "detail_type_method", "RELATIVE")
            prop = {"RELATIVE": "detail_size", "BRUSH": "detail_percent", "CONSTANT": "constant_detail_resolution",
                    "MANUAL": "constant_detail_resolution"}.get(method, "detail_size")
            self._row(self.topo_sec, "Detail", s, prop)
            self._row(self.topo_sec, "Refine", s, "detail_refine_method")
        # voxel remesh
        if "remesh_voxel_size" in me.bl_rna.properties:
            r = QtWidgets.QHBoxLayout()
            self._row_into(r, "Voxel Size", me, "remesh_voxel_size")
            rb = QtWidgets.QPushButton("Remesh", self.widget())
            if blicons.has("MOD_REMESH"):
                rb.setIcon(blicons.icon("MOD_REMESH"))
            rb.setToolTip("Voxel Remesh – even new topology with this voxel size")
            rb.clicked.connect(lambda _=False: self._run("object.voxel_remesh", {}))
            r.addWidget(rb)
            self.topo_sec.addLayout(r)
        # multires
        mr = next((m for m in ob.modifiers if m.type == "MULTIRES"), None)
        r = QtWidgets.QHBoxLayout()
        if mr is None:
            ab = QtWidgets.QPushButton("Add Multires", self.widget())
            if blicons.has("MOD_MULTIRES"):
                ab.setIcon(blicons.icon("MOD_MULTIRES"))
            ab.setToolTip("Add a Multiresolution modifier (sculpt on subdivision levels)")
            ab.clicked.connect(lambda _=False: self._run("object.modifier_add", {"type": "MULTIRES"}))
            r.addWidget(ab)
        else:
            sb = QtWidgets.QPushButton("Subdivide", self.widget())
            if blicons.has("MOD_SUBSURF"):
                sb.setIcon(blicons.icon("MOD_SUBSURF"))
            sb.clicked.connect(lambda _=False, n=mr.name: self._multires_subdivide(n))
            r.addWidget(sb)
            self.topo_sec.addLayout(r)
            r = QtWidgets.QHBoxLayout()
            self._row_into(r, "Sculpt Level", mr, "sculpt_levels")
            self.topo_sec.addLayout(r)
            r = None
        if r is not None:
            self.topo_sec.addLayout(r)
        # display
        sp = None
        try:
            from . import api
            sp, _rg = api.main_window().viewport.space()
        except Exception:
            pass
        if s is not None:
            self._toggle(self.disp_sec, "Brush Circle", s, "show_brush", "CURSOR")
        self._asset_shelf_button()
        ov = getattr(sp, "overlay", None) if sp is not None else None
        if ov is not None:
            for text, prop, op in (("Mask", "show_sculpt_mask", "sculpt_mode_mask_opacity"),
                                   ("Face Sets", "show_sculpt_face_sets", "sculpt_mode_face_sets_opacity")):
                if prop in ov.bl_rna.properties:
                    r = QtWidgets.QHBoxLayout()
                    self._toggle(None, text, ov, prop, row=r)
                    if op in ov.bl_rna.properties:
                        self._row_into(r, "", ov, op)
                    self.disp_sec.addLayout(r)

    def _asset_shelf_button(self):
        """Blender's asset shelf at the bottom of Blender's viewport (brushes) – shown / hidden."""
        from . import sculptview, keymap
        b = QtWidgets.QPushButton("Asset Shelf", self.widget())
        b.setCheckable(True)
        b.setChecked(sculptview.asset_shelf_on())
        if blicons.has("ASSET_MANAGER"):
            b.setIcon(blicons.icon("ASSET_MANAGER"))
        keymap.tip(b, "Brushes / assets shelf at the bottom of Blender's viewport ({view3d.asset_shelf})")
        b.toggled.connect(lambda on: sculptview.set_asset_shelf(on))
        sculptview.signals.asset_shelf.connect(b.setChecked)   # bound method: dropped with the button
        self.disp_sec.addWidget(b)

    # ---- sync
    def pick_brush(self, name):
        if not self._ensure_sculpt():
            self.sync(force=True)
            return
        sculpt.activate_brush(name)
        msg = sculpt.stroke_blocker()
        if msg:
            bridge.log(msg, "INFO")
        self.sync(force=True)

    def sync(self, force=False):
        if bridge.op_depth:          # a Qt timer fired inside an operator (undo swaps the data under us)
            return
        try:
            on = sculpt.active()
            self.hint.setVisible(not on)
            self.hint.setText("Sculpt Mode is off – switch to it in the 3D view header (or "
                              + self._mode_key() + ").")
            br = sculpt.brush() if on else None
            name = getattr(br, "name", "") if br is not None else ""
            e = brush_entry(name)
            self.head_name.setText(name or "—")
            self.head_note.setText((e[3] if e else (sculpt.brush_type().replace("_", " ").title()))
                                   if name else "")
            if e:
                self.head_icon.setPixmap(brush_icon(e[1], e[2]).pixmap(theme.px(36), theme.px(36)))
            else:
                self.head_icon.clear()
            for n, b in self.brush_btns.items():
                b.blockSignals(True)
                b.setChecked(n == name)
                b.blockSignals(False)
            # pointers, not id() of the Python wrappers – those are new objects on every call, so the brush
            # section was rebuilt now and then, even under a dragged Radius field (cursor left hidden)
            bkey = (br.as_pointer() if br is not None else 0, _ptr(sculpt._size_owner()),
                    _ptr(sculpt._strength_owner()))
            ob = _active_mesh_object()
            okey = (ob.as_pointer() if ob is not None else 0, on,
                    bool(getattr(ob, "use_dynamic_topology_sculpting", False)) if ob else False,
                    tuple(m.name for m in ob.modifiers if m.type == "MULTIRES") if ob is not None and ob.type == "MESH" else (),
                    getattr(sculpt.sculpt_settings(), "detail_type_method", None))
            if force or bkey != self._brush_key:
                self._brush_key = bkey
                if on:
                    self._build_brush()
                else:
                    self._clear(self.brush_sec)
            if force or okey != self._ob_key:
                self._ob_key = okey
                self._build_object()
            alive = []
            for b in self._bindings:
                try:
                    if b.alive():
                        b.refresh()
                        alive.append(b)
                except RuntimeError:              # its widget was rebuilt (deleted) meanwhile
                    pass
            self._bindings = alive
        except Exception as ex:
            bridge.log(f"Sculpt panel: {ex}", "WARNING")

    def _mode_key(self):
        from . import keymap
        return keymap.render("{view3d.mode_sculpt}")

    def showEvent(self, ev):
        self._timer.start()
        self.sync(force=True)
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

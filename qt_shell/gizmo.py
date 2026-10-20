"""Transform tools and gizmos in the 3D viewport (like Blender's toolbar: Select, Move, Rotate, Scale,
Transform).

- Toolbar: a column of tool buttons on the left of every 3D view (T shows / hides it).
- Gizmo: drawn at the pivot of the selection (median of the selected objects' origins, or of the
  selected vertices in Edit mode), in global orientation:
    Move   – X / Y / Z arrows, a circle in the middle = free move in the view plane
    Rotate – X / Y / Z rings, the outer white ring = rotate around the view axis
    Scale  – X / Y / Z handles with boxes, the outer white ring = uniform scale
    Transform – all in one: arrows move, rings rotate, boxes on the axes scale

Shortcuts: Shift+Space opens the tool menu (W Select, G Move, R Rotate, S Scale, T Transform),
W switches to Select, T shows / hides the toolbar.
- Dragging a handle runs the same interactive transform as G / R / S (with the axis set);
  releasing the mouse confirms, right click / Esc cancels.

The tool and the toolbar visibility are shared by all views and remembered (QSettings).
"""
import math

import bpy
from mathutils import Vector
from PySide6 import QtCore, QtGui, QtWidgets

from . import theme
from . import pytips

# (tool, glyph, tooltip, key in the Shift+Space tool menu)
TOOLS = [
    ("SELECT", "⬚", "Select Box – click / drag to select", "W"),
    ("MOVE", "✥", "Move – drag an arrow (X / Y / Z) or the centre (free)", "G"),
    ("ROTATE", "⟳", "Rotate – drag a ring (X / Y / Z) or the outer ring (view axis)", "R"),
    ("SCALE", "⤡", "Scale – drag a handle (X / Y / Z) or the outer ring (uniform)", "S"),
    ("TRANSFORM", "❖", "Transform – arrows move, rings rotate, boxes scale", "T"),
]
_KIND = {"MOVE": "G", "ROTATE": "R", "SCALE": "S", "TRANSFORM": "T"}
_BUILTIN = {"SELECT": "select_box", "MOVE": "move", "ROTATE": "rotate", "SCALE": "scale",
            "TRANSFORM": "transform"}
TOOL_NAMES = {"SELECT": "Select Box", "MOVE": "Move", "ROTATE": "Rotate", "SCALE": "Scale",
              "TRANSFORM": "Transform"}

AXES = (("X", Vector((1, 0, 0)), QtGui.QColor("#ff3352")),
        ("Y", Vector((0, 1, 0)), QtGui.QColor("#8bdc00")),
        ("Z", Vector((0, 0, 1)), QtGui.QColor("#2890ff")))
HOVER_COLOR = QtGui.QColor("#ffe066")

# sizes in (unscaled) screen pixels
ARROW_LEN = 78
RING_R = 70
VIEW_RING_R = 86
CENTER_R = 11
PICK_DIST = 7


# ---------------------------------------------------------------- shared tool state
class ToolState(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        s = QtCore.QSettings("QtShell", "QtShell")
        tool = str(s.value("viewport/tool", "SELECT"))
        self.tool = tool if tool in [t[0] for t in TOOLS] else "SELECT"
        self.toolbar_visible = str(s.value("viewport/toolbar", "true")).lower() == "true"
        # toolbar position shared by all views: (fx, fy) = fraction of the free space, None = default
        self.toolbar_pos = None
        self.toolbar_horizontal = False
        try:
            raw = str(s.value("viewport/toolbar_pos", "") or "")
            if raw:
                fx, fy, h = raw.split(",")
                self.toolbar_pos = (min(1.0, max(0.0, float(fx))), min(1.0, max(0.0, float(fy))))
                self.toolbar_horizontal = h == "h"
        except Exception:
            self.toolbar_pos = None

    def set_tool(self, tool):
        if tool not in [t[0] for t in TOOLS] or tool == self.tool:
            return
        self.tool = tool
        QtCore.QSettings("QtShell", "QtShell").setValue("viewport/tool", tool)
        self.changed.emit()

    def set_toolbar_pos(self, pos, horizontal=None):
        self.toolbar_pos = pos
        if horizontal is not None:
            self.toolbar_horizontal = bool(horizontal)
        val = "" if pos is None else \
            f"{pos[0]:.4f},{pos[1]:.4f},{'h' if self.toolbar_horizontal else 'v'}"
        if pos is None and self.toolbar_horizontal:
            val = "0,0.0,h"           # keep the orientation even at the default place
            self.toolbar_pos = (0.0, 0.0)
        QtCore.QSettings("QtShell", "QtShell").setValue("viewport/toolbar_pos", val)
        self.changed.emit()

    def toggle_toolbar(self):
        self.toolbar_visible = not self.toolbar_visible
        QtCore.QSettings("QtShell", "QtShell").setValue(
            "viewport/toolbar", "true" if self.toolbar_visible else "false")
        self.changed.emit()


def tool_state(hub):
    st = getattr(hub, "_tool_state", None)
    if st is None:
        st = hub._tool_state = ToolState(hub)
    return st


# ---------------------------------------------------------------- toolbar
class _Grip(QtWidgets.QWidget):
    """The dotted handle of the toolbar – drag it to move the toolbar."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setCursor(QtCore.Qt.SizeAllCursor)
        self.setToolTip("Drag to move the toolbar (it snaps to the edges of the view)\n"
                        "Double-click: back to the default place · Right click: more")
        self.horizontal = False

    def sizeHint(self):
        return QtCore.QSize(theme.px(10), theme.px(30)) if self.horizontal else \
            QtCore.QSize(theme.px(30), theme.px(10))

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(235, 235, 235) if self.underMouse() else QtGui.QColor(175, 175, 175))
        r = max(1.2, theme.px(1.6))
        c = QtCore.QPointF(self.rect().center())
        step = theme.px(5)
        for i in (-1, 0, 1):
            for j in (-0.5, 0.5):
                dx, dy = (j * step, i * step) if self.horizontal else (i * step, j * step)
                p.drawEllipse(c + QtCore.QPointF(dx, dy), r, r)

    def enterEvent(self, ev):
        self.update()

    def leaveEvent(self, ev):
        self.update()


class Toolbar(QtWidgets.QFrame):
    """Tool buttons floating over a 3D view – movable by its grip, snaps to the edges."""

    SNAP = 28          # unscaled px: closer than this to an edge → stick to it

    def __init__(self, viewport):
        super().__init__(viewport)
        self.vp = viewport
        self.state = tool_state(viewport.hub)
        self.setObjectName("qtshell_toolbar")
        self.setStyleSheet(
            "QFrame#qtshell_toolbar { background: rgba(40, 40, 40, 215); border: 1px solid #1a1a1a;"
            f" border-radius: {theme.px(5)}px; }}"
            "QToolButton { background: transparent; border: 1px solid transparent; }"
            f"QToolButton:checked {{ background: {theme.C['highlight']}; }}\n" + theme.hover_qss())
        lay = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.TopToBottom, self)
        m = theme.px(3)
        lay.setContentsMargins(m, m, m, m)
        lay.setSpacing(theme.px(2))
        self._lay = lay
        self._drag = None              # (press pos in the viewport, toolbar pos at press)
        self.grip = _Grip(self)
        self.grip.installEventFilter(self)
        lay.addWidget(self.grip, 0, QtCore.Qt.AlignCenter)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.buttons = {}
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        f = self.font()
        f.setPixelSize(theme.fs(17))
        for tool, glyph, tip, key in TOOLS:
            b = QtWidgets.QToolButton(self)
            b.setText(glyph)
            b.setFont(f)
            extra = "W, or " if tool == "SELECT" else ""
            b.setToolTip(f"{tip}\nShortcut: {extra}Shift+Space → {key}\nT shows / hides the toolbar")
            b.setCheckable(True)
            pytips.tag(b, f'bpy.ops.wm.tool_set_by_id(name="builtin.{_BUILTIN[tool]}")')
            b.setFixedSize(theme.px(30), theme.px(30))
            b.clicked.connect(lambda _c=False, t=tool: self.state.set_tool(t))
            group.addButton(b)
            lay.addWidget(b)
            self.buttons[tool] = b
        self.state.changed.connect(self.sync)
        viewport.installEventFilter(self)          # keep the place when the view is resized
        self.sync()

    # --- placement
    def _free(self):
        """Space the toolbar's top-left corner can move in (x0, y0, x1, y1)."""
        m = theme.px(4)
        top = theme.px(4)
        return m, top, max(m, self.vp.width() - self.width() - m), max(top, self.vp.height() - self.height() - m)

    def place(self):
        pos = self.state.toolbar_pos
        if pos is None:
            x, y = theme.px(6), theme.px(46)
        else:
            x0, y0, x1, y1 = self._free()
            x, y = x0 + pos[0] * (x1 - x0), y0 + pos[1] * (y1 - y0)
        x0, y0, x1, y1 = self._free()
        self.move(int(min(max(x, x0), x1)), int(min(max(y, y0), y1)))

    def _set_orientation(self, horizontal):
        self._lay.setDirection(QtWidgets.QBoxLayout.LeftToRight if horizontal
                               else QtWidgets.QBoxLayout.TopToBottom)
        self.grip.horizontal = horizontal
        self.grip.updateGeometry()
        self._lay.invalidate()
        self.adjustSize()

    def sync(self):
        try:
            for tool, b in self.buttons.items():
                b.setChecked(tool == self.state.tool)
            if self.grip.horizontal != self.state.toolbar_horizontal:
                self._set_orientation(self.state.toolbar_horizontal)
            self.setVisible(self.state.toolbar_visible)
            self.adjustSize()
            if self._drag is None:
                self.place()
            self.vp.update()
        except RuntimeError:          # deleted together with its viewport
            pass

    # --- dragging (grip or the toolbar's margins)
    def eventFilter(self, obj, ev):
        try:
            if obj is self.vp:
                if ev.type() == QtCore.QEvent.Resize and self._drag is None:
                    self.place()
                return False
            if obj is self.grip:
                t = ev.type()
                if t == QtCore.QEvent.MouseButtonDblClick and ev.button() == QtCore.Qt.LeftButton:
                    self.state.set_toolbar_pos(None, False)
                    return True
                if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove,
                         QtCore.QEvent.MouseButtonRelease):
                    return self._drag_event(ev)
        except RuntimeError:
            pass
        return False

    def mousePressEvent(self, ev):
        if not self._drag_event(ev):
            ev.accept()               # never let a click on the toolbar reach the 3D view

    def mouseMoveEvent(self, ev):
        self._drag_event(ev)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag_event(ev)
        ev.accept()

    def _drag_event(self, ev):
        t = ev.type()
        gp = self.vp.mapFromGlobal(ev.globalPosition().toPoint())
        if t == QtCore.QEvent.MouseButtonPress and ev.button() == QtCore.Qt.LeftButton:
            self._drag = (gp, self.pos())
            self.raise_()
            return True
        if self._drag is None:
            return False
        if t == QtCore.QEvent.MouseMove:
            start, orig = self._drag
            x0, y0, x1, y1 = self._free()
            p = orig + (gp - start)
            self.move(min(max(p.x(), x0), x1), min(max(p.y(), y0), y1))
            return True
        if t == QtCore.QEvent.MouseButtonRelease:
            self._drag = None
            self._drop()
            return True
        return False

    def _drop(self):
        """Snap to the nearest edges, pick the orientation, store the place for all views."""
        snap = theme.px(self.SNAP)
        x0, y0, x1, y1 = self._free()
        x, y = self.x(), self.y()
        left, right = x - x0 < snap, x1 - x < snap
        top, bottom = y - y0 < snap, y1 - y < snap
        horizontal = self.state.toolbar_horizontal
        if (top or bottom) and not (left or right):
            horizontal = True            # along the top / bottom edge
        elif (left or right) and not (top or bottom):
            horizontal = False           # along the left / right edge
        if horizontal != self.state.toolbar_horizontal:
            # keep the toolbar's centre where it was dropped while it turns
            c = self.geometry().center()
            self._set_orientation(horizontal)
            x0, y0, x1, y1 = self._free()
            x, y = c.x() - self.width() // 2, c.y() - self.height() // 2
            if left:
                x = x0
            if right:
                x = x1
            if top:
                y = y0
            if bottom:
                y = y1
        else:
            x = x0 if left else (x1 if right else x)
            y = y0 if top else (y1 if bottom else y)
        x, y = min(max(x, x0), x1), min(max(y, y0), y1)
        fx = (x - x0) / (x1 - x0) if x1 > x0 else 0.0
        fy = (y - y0) / (y1 - y0) if y1 > y0 else 0.0
        self.state.set_toolbar_pos((fx, fy), horizontal)

    def _menu(self, pos):
        m = QtWidgets.QMenu(self)
        h = self.state.toolbar_horizontal
        m.addAction("Vertical" if h else "Horizontal",
                    lambda: self.state.set_toolbar_pos(self.state.toolbar_pos or (0.0, 0.0), not h))
        m.addAction("Flip to Right" if (self.state.toolbar_pos or (0, 0))[0] < 0.5 else "Flip to Left",
                    self._flip)
        m.addAction("Reset Position", lambda: self.state.set_toolbar_pos(None, False))
        m.addSeparator()
        m.addAction("Hide Toolbar\tT", self.state.toggle_toolbar)
        m.exec(self.mapToGlobal(pos))
        m.deleteLater()

    def _flip(self):
        fx, fy = self.state.toolbar_pos or (0.0, 0.0)
        if self.state.toolbar_pos is None:
            x0, y0, x1, y1 = self._free()
            fy = (self.y() - y0) / (y1 - y0) if y1 > y0 else 0.0
        self.state.set_toolbar_pos((1.0 - fx if 0 < fx < 1 else (1.0 if fx < 0.5 else 0.0), fy))


# ---------------------------------------------------------------- Shift+Space tool menu
class ToolMenu(QtWidgets.QMenu):
    """Like Blender's Shift+Space: the tools with a key each (W / G / R / S / T)."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._keys = {}
        title = self.addAction("Tools")
        title.setEnabled(False)
        self.addSeparator()
        for tool, glyph, _tip, key in TOOLS:
            a = self.addAction(f"{glyph}  {TOOL_NAMES[tool]}\t{key}")
            a.setCheckable(True)
            a.setChecked(tool == state.tool)
            a.triggered.connect(lambda _c=False, t=tool: state.set_tool(t))
            self._keys[getattr(QtCore.Qt, f"Key_{key}")] = tool

    def keyPressEvent(self, ev):
        tool = self._keys.get(ev.key())
        if tool is not None and not ev.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier):
            self.state.set_tool(tool)
            self.close()
            return
        super().keyPressEvent(ev)


def show_tool_menu(vp):
    m = ToolMenu(tool_state(vp.hub), vp)
    m.exec(QtGui.QCursor.pos())
    m.deleteLater()


# ---------------------------------------------------------------- pivot
def pivot(vp):
    """World position of the gizmo or None (nothing selected / unsupported mode)."""
    ctx = bpy.context
    mode = ctx.mode
    if mode == "OBJECT":
        sel = [o for o in ctx.selected_objects if o.visible_get()]
        if not sel:
            return None
        return sum((o.matrix_world.translation for o in sel), Vector()) / len(sel)
    if mode == "EDIT_MESH":
        cache = getattr(vp, "_gizmo_pivot_cache", None)
        if cache is not None:
            return cache[0]
        p = None
        try:
            from . import editmesh
            r = editmesh.active()
            if r:
                ob, bm = r
                co = [v.co for v in bm.verts if v.select and not v.hide]
                if co:
                    p = ob.matrix_world @ (sum(co, Vector()) / len(co))
        except Exception:
            p = None
        vp._gizmo_pivot_cache = (p,)
        return p
    return None


def invalidate(vp):
    vp._gizmo_pivot_cache = None


# ---------------------------------------------------------------- geometry
def _perp(a):
    """Two unit vectors perpendicular to a."""
    t = Vector((0, 0, 1)) if abs(a.z) < 0.9 else Vector((1, 0, 0))
    u = a.cross(t).normalized()
    return u, a.cross(u).normalized()


def _ring(vp, pv, a, R, mats):
    u, v = _perp(a)
    pts = []
    for i in range(49):
        t = 2 * math.pi * i / 48
        q = vp.project(pv + (u * math.cos(t) + v * math.sin(t)) * R, mats)
        if q is None:
            return []
        pts.append(q)
    return pts


def handles(vp, tool):
    """List of handles. id = "<op>:<axis>" – op G (move) / R (rotate) / S (scale), axis X / Y / Z or
    FREE / VIEW / UNIFORM. kind: 'line' (pts, tip arrow|box), 'ring' (pts), 'circle' (center, r),
    'box' (center)."""
    if tool not in _KIND:
        return []
    pv = pivot(vp)
    if pv is None:
        return []
    mats = vp.matrices(vp.width(), vp.height())
    c = vp.project(pv, mats)
    if c is None:
        return []
    s = vp.pixel_size_at(pv)            # world units per screen pixel at the pivot
    sc = theme.ui_scale
    white = QtGui.QColor("#e8e8e8")
    out = []
    rotate = tool in ("ROTATE", "TRANSFORM")
    move = tool in ("MOVE", "TRANSFORM")
    if rotate:
        R = RING_R * sc * s * (0.82 if tool == "TRANSFORM" else 1.0)
        for name, a, col in AXES:
            pts = _ring(vp, pv, a, R, mats)
            if pts:
                out.append({"id": f"R:{name}", "kind": "ring", "pts": pts, "color": col})
        out.append({"id": "R:VIEW", "kind": "circle", "center": c, "r": VIEW_RING_R * sc,
                    "color": white, "ring_hit": True})
    if tool in ("MOVE", "SCALE", "TRANSFORM"):
        L = ARROW_LEN * sc * s * (1.12 if tool == "TRANSFORM" else 1.0)
        for name, a, col in AXES:
            end = vp.project(pv + a * L, mats)
            if end is None:
                continue
            d = end - c
            if math.hypot(d.x(), d.y()) < 10 * sc:      # axis points at the viewer – hide it
                continue
            if tool == "SCALE":
                out.append({"id": f"S:{name}", "kind": "line", "pts": [c, end], "color": col,
                            "tip": "box"})
                continue
            out.append({"id": f"G:{name}", "kind": "line", "pts": [c, end], "color": col,
                        "tip": "arrow"})
            if tool == "TRANSFORM":
                # scale box on the axis, between the centre and the arrow (like Blender's Transform)
                mid = vp.project(pv + a * (L * 0.55), mats)
                if mid is not None:
                    out.append({"id": f"S:{name}", "kind": "box", "center": mid, "color": col})
    if tool == "SCALE":
        # uniform scale: the outer ring (like Blender) – dragging from it scales by the ratio of
        # distances from the pivot, so it must not start right at the pivot
        out.append({"id": "S:UNIFORM", "kind": "circle", "center": c, "r": VIEW_RING_R * sc,
                    "color": white, "ring_hit": True})
    if move:
        out.append({"id": "G:FREE", "kind": "circle", "center": c, "r": CENTER_R * sc, "color": white})
    return out


def _seg_dist(p, a, b):
    ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p.x() - ax) * dx + (p.y() - ay) * dy) / L2))
    return math.hypot(p.x() - (ax + t * dx), p.y() - (ay + t * dy))


def hit(hs, pos):
    """id of the handle under pos (QPointF) or None. Boxes and axis handles win over the centre."""
    sc = theme.ui_scale
    pick = PICK_DIST * sc
    best, best_key = None, None
    for h in hs:
        kind = h["kind"]
        if kind == "circle":
            dc = math.hypot(pos.x() - h["center"].x(), pos.y() - h["center"].y())
            d = abs(dc - h["r"]) if h.get("ring_hit") else max(0.0, dc - h["r"])
        elif kind == "box":
            d = max(0.0, math.hypot(pos.x() - h["center"].x(), pos.y() - h["center"].y()) - 6 * sc)
        elif kind == "line":
            # skip the part inside the centre circle, so the centre stays easy to grab;
            # the arrow head / box at the end is a bit bigger than the line
            a, b = h["pts"]
            dx, dy = b.x() - a.x(), b.y() - a.y()
            ln = math.hypot(dx, dy) or 1.0
            k = min(0.9, (CENTER_R + 4) * sc / ln)
            a = QtCore.QPointF(a.x() + dx * k, a.y() + dy * k)
            d = min(_seg_dist(pos, a, b), math.hypot(pos.x() - b.x(), pos.y() - b.y()) - 4 * sc)
        else:
            pts = h["pts"]
            d = min(_seg_dist(pos, pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        if d > pick:
            continue
        rank = 0 if kind == "box" else (1 if h["id"].split(":")[1] in ("X", "Y", "Z") else 2)
        key = (rank, d)
        if best_key is None or key < best_key:
            best, best_key = h["id"], key
    return best


# ---------------------------------------------------------------- drawing
def paint(vp, p, tool, hover):
    hs = handles(vp, tool)
    if not hs:
        return hs
    sc = theme.ui_scale
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    for h in hs:
        col = HOVER_COLOR if h["id"] == hover else h["color"]
        width = (3.2 if h["id"] == hover else 2.2) * sc
        if h["kind"] == "ring":
            p.setPen(QtGui.QPen(col, width))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawPolyline(QtGui.QPolygonF(h["pts"]))
        elif h["kind"] == "box":
            r = (6.5 if h["id"] == hover else 5.5) * sc
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(col)
            ctr = h["center"]
            p.drawRect(QtCore.QRectF(ctr.x() - r, ctr.y() - r, 2 * r, 2 * r))
        elif h["kind"] == "circle":
            p.setPen(QtGui.QPen(col, width * 0.8))
            p.setBrush(QtGui.QColor(255, 255, 255, 40 if h["id"] == hover else 0))
            p.drawEllipse(h["center"], h["r"], h["r"])
        else:
            a, b = h["pts"]
            p.setPen(QtGui.QPen(col, width))
            p.drawLine(a, b)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(col)
            dx, dy = b.x() - a.x(), b.y() - a.y()
            ln = math.hypot(dx, dy) or 1.0
            ux, uy = dx / ln, dy / ln
            if h["tip"] == "arrow":
                size = 13 * sc
                base = QtCore.QPointF(b.x() - ux * size, b.y() - uy * size)
                tipp = QtCore.QPointF(b.x() + ux * 2 * sc, b.y() + uy * 2 * sc)
                w = size * 0.42
                p.drawPolygon(QtGui.QPolygonF([
                    tipp, QtCore.QPointF(base.x() - uy * w, base.y() + ux * w),
                    QtCore.QPointF(base.x() + uy * w, base.y() - ux * w)]))
            else:
                r = 5.5 * sc
                p.drawRect(QtCore.QRectF(b.x() - r, b.y() - r, 2 * r, 2 * r))
    p.restore()
    return hs


# ---------------------------------------------------------------- interaction
def start_drag(vp, handle_id, tool=None):
    """Starts the interactive transform for a handle ("G:X", "R:VIEW", …). True when it started."""
    op, _, axis = handle_id.partition(":")
    if op not in ("G", "R", "S"):
        return False
    vp.start_modal(op)
    m = vp._modal
    if not m:
        return False
    m["axis"] = axis if axis in ("X", "Y", "Z") else None
    m["drag"] = True                  # release of the mouse button confirms
    vp._modal_update(m["start"])
    return True

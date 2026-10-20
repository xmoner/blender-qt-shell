"""Transform tools and gizmos in the 3D viewport (like Blender's toolbar: Select, Move, Rotate, Scale).

- Toolbar: a column of tool buttons on the left of every 3D view (T shows / hides it).
- Gizmo: drawn at the pivot of the selection (median of the selected objects' origins, or of the
  selected vertices in Edit mode), in global orientation:
    Move   – X / Y / Z arrows, a circle in the middle = free move in the view plane
    Rotate – X / Y / Z rings, the outer white ring = rotate around the view axis
    Scale  – X / Y / Z handles with boxes, the outer white ring = uniform scale
- Dragging a handle runs the same interactive transform as G / R / S (with the axis set);
  releasing the mouse confirms, right click / Esc cancels.

The tool and the toolbar visibility are shared by all views and remembered (QSettings).
"""
import math

import bpy
from mathutils import Vector
from PySide6 import QtCore, QtGui, QtWidgets

from . import theme

TOOLS = [
    ("SELECT", "⬚", "Select Box – click / drag to select"),
    ("MOVE", "✥", "Move – drag an arrow (X / Y / Z) or the centre (free)"),
    ("ROTATE", "⟳", "Rotate – drag a ring (X / Y / Z) or the outer ring (view axis)"),
    ("SCALE", "⤡", "Scale – drag a handle (X / Y / Z) or the outer ring (uniform)"),
]
_KIND = {"MOVE": "G", "ROTATE": "R", "SCALE": "S"}

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
        self.tool = tool if tool in dict((t[0], t) for t in TOOLS) else "SELECT"
        self.toolbar_visible = str(s.value("viewport/toolbar", "true")).lower() == "true"

    def set_tool(self, tool):
        if tool not in [t[0] for t in TOOLS] or tool == self.tool:
            return
        self.tool = tool
        QtCore.QSettings("QtShell", "QtShell").setValue("viewport/tool", tool)
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
class Toolbar(QtWidgets.QFrame):
    """Column of tool buttons floating over the left side of a 3D view."""

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
        lay = QtWidgets.QVBoxLayout(self)
        m = theme.px(3)
        lay.setContentsMargins(m, m, m, m)
        lay.setSpacing(theme.px(2))
        self.buttons = {}
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        f = self.font()
        f.setPixelSize(theme.fs(17))
        for tool, glyph, tip in TOOLS:
            b = QtWidgets.QToolButton(self)
            b.setText(glyph)
            b.setFont(f)
            b.setToolTip(tip + "\n(T shows / hides the toolbar)")
            b.setCheckable(True)
            b.setFixedSize(theme.px(30), theme.px(30))
            b.clicked.connect(lambda _c=False, t=tool: self.state.set_tool(t))
            group.addButton(b)
            lay.addWidget(b)
            self.buttons[tool] = b
        self.state.changed.connect(self.sync)
        self.move(theme.px(6), theme.px(46))
        self.sync()

    def sync(self):
        try:
            for tool, b in self.buttons.items():
                b.setChecked(tool == self.state.tool)
            self.setVisible(self.state.toolbar_visible)
            self.adjustSize()
            self.vp.update()
        except RuntimeError:          # deleted together with its viewport
            pass


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


def handles(vp, tool):
    """List of handles: dict(id, kind 'line'|'ring'|'circle', pts|center+r, color)."""
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
    out = []
    if tool == "ROTATE":
        R = RING_R * sc * s
        for name, a, col in AXES:
            u, v = _perp(a)
            pts = []
            for i in range(49):
                t = 2 * math.pi * i / 48
                q = vp.project(pv + (u * math.cos(t) + v * math.sin(t)) * R, mats)
                if q is None:
                    pts = []
                    break
                pts.append(q)
            if pts:
                out.append({"id": name, "kind": "ring", "pts": pts, "color": col})
        out.append({"id": "VIEW", "kind": "circle", "center": c, "r": VIEW_RING_R * sc,
                    "color": QtGui.QColor("#e8e8e8"), "ring_hit": True})
        return out
    L = ARROW_LEN * sc * s
    for name, a, col in AXES:
        end = vp.project(pv + a * L, mats)
        if end is None:
            continue
        d = end - c
        if math.hypot(d.x(), d.y()) < 10 * sc:          # axis points at the viewer – hide it
            continue
        out.append({"id": name, "kind": "line", "pts": [c, end], "color": col,
                    "tip": "box" if tool == "SCALE" else "arrow"})
    if tool == "SCALE":
        # uniform scale: the outer ring (like Blender) – dragging from it scales by the ratio of
        # distances from the pivot, so it must not start right at the pivot
        out.append({"id": "UNIFORM", "kind": "circle", "center": c, "r": VIEW_RING_R * sc,
                    "color": QtGui.QColor("#e8e8e8"), "ring_hit": True})
    else:
        out.append({"id": "CENTER", "kind": "circle", "center": c, "r": CENTER_R * sc,
                    "color": QtGui.QColor("#e8e8e8")})
    return out


def _seg_dist(p, a, b):
    ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p.x() - ax) * dx + (p.y() - ay) * dy) / L2))
    return math.hypot(p.x() - (ax + t * dx), p.y() - (ay + t * dy))


def hit(hs, pos):
    """id of the handle under pos (QPointF) or None."""
    pick = PICK_DIST * theme.ui_scale
    best, best_d = None, pick
    for h in hs:
        if h["kind"] == "circle":
            dc = math.hypot(pos.x() - h["center"].x(), pos.y() - h["center"].y())
            d = abs(dc - h["r"]) if h.get("ring_hit") else max(0.0, dc - h["r"])
        else:
            pts = h["pts"]
            if h["kind"] == "line":
                # skip the part inside the centre circle, so the centre stays easy to grab;
                # the arrow head / box at the end is a bit bigger than the line
                a, b = pts
                dx, dy = b.x() - a.x(), b.y() - a.y()
                ln = math.hypot(dx, dy) or 1.0
                k = min(0.9, (CENTER_R + 4) * theme.ui_scale / ln)
                a = QtCore.QPointF(a.x() + dx * k, a.y() + dy * k)
                d = min(_seg_dist(pos, a, b),
                        math.hypot(pos.x() - b.x(), pos.y() - b.y()) - 4 * theme.ui_scale)
            else:
                d = min(_seg_dist(pos, pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        if d <= best_d:
            # axis handles win over the centre when both are close
            if best is None or d < best_d or h["id"] in ("X", "Y", "Z"):
                best, best_d = h["id"], d
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
def start_drag(vp, handle_id, tool):
    """Starts the interactive transform for a handle. Returns True when it started."""
    kind = _KIND.get(tool)
    if kind is None:
        return False
    vp.start_modal(kind)
    m = vp._modal
    if not m:
        return False
    m["axis"] = handle_id if handle_id in ("X", "Y", "Z") else None
    m["drag"] = True                  # release of the mouse button confirms
    vp._modal_update(m["start"])
    return True

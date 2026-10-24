"""Blue Pencil – 2D drawings over the camera or the view, keyed on frames (in the spirit of Chris Zurbrigg's
Blue Pencil 2 for Maya): thumbnails, blocking, arcs and review notes drawn right in the 3D viewport.

- Tool **Blue Pencil** in the viewport toolbar, its variants are the drawing tools: Pencil, Brush (tapered,
  tablet pressure), Eraser (cuts lines, removes shapes / text), Text, Line, Arrow, Ellipse, Rectangle and
  Transform (select a region → move, Shift: rotate, middle mouse: scale, Shift + middle: non-uniform;
  Enter applies, Backspace resets, Esc drops the selection; cut / copy / paste between frames and layers).
- **Layers** (Layer Manager in the Blue Pencil panel): top of the list = drawn on top; each layer belongs to
  a camera (shown when looking through it) or to the View (any view that isn't a camera view); visibility,
  opacity and a state – Animation (drawing creates a frame at the current time = autokey), Static (draws
  into the frame shown – backgrounds, arc tracking) or Locked.
- **Frames**: a drawing is held until the layer's next frame. Insert blank / duplicate previous / delete /
  cut / copy / paste, stepping to the previous / next frame, frame ticks in the Timeline (they can be
  dragged; a collision cancels the move), the **Retiming** tool (exactly 1–6 frames between keys, or
  ±1 / ±2 frames) and **ghosting** of previous / next frames (onion skin, colours, number of frames).
- Stored in the scene (ID property "qtshell_bluepencil", JSON) – saved with the .blend file; every edit is a
  Blender undo step (Ctrl+Z).

Coordinates are normalised to the frame: the camera frame (render size) in a camera view, the whole view
otherwise; x and y are both divided by the frame height so drawings keep their proportions. Sizes are px of
a frame REF_H px high.
"""
import json
import math

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, icons, keymap, pytips, theme

PROP = "qtshell_bluepencil"
REF_H = 800.0
STATES = ("ANIMATION", "STATIC", "LOCKED")
STATE_LETTER = {"ANIMATION": "A", "STATIC": "S", "LOCKED": "L"}
STATE_TIPS = {"ANIMATION": "Animation – drawing creates a frame at the current time (autokey)",
              "STATIC": "Static – drawing goes into the frame shown (backgrounds, arc tracking)",
              "LOCKED": "Locked – no drawing, no frame changes"}
# tool id → (name, icon, tooltip)
TOOLS = [
    ("PENCIL", "Pencil", "bp_pencil", "Free-hand line"),
    ("BRUSH", "Brush", "bp_brush", "Tapered free-hand stroke (tablet pressure when enabled)"),
    ("ERASER", "Eraser", "bp_eraser", "Drag over strokes: lines are cut, shapes and text removed"),
    ("TEXT", "Text", "bp_text", "Click to type a note (Enter: done, Esc: cancel)"),
    ("LINE", "Line", "bp_line", "Drag a straight line"),
    ("ARROW", "Arrow", "bp_arrow", "Drag an arrow (head at the end)"),
    ("ELLIPSE", "Ellipse", "bp_ellipse", "Drag an ellipse"),
    ("RECT", "Rectangle", "bp_rect", "Drag a rectangle"),
    ("TRANSFORM", "Transform", "bp_transform",
     "Drag a region to select; drag to move, Shift + drag: rotate, middle drag: scale (Shift: non-uniform); "
     "Enter applies, Backspace resets"),
]
TOOL_IDS = [t[0] for t in TOOLS]
PALETTE = ("#2f7bff", "#ff3b30", "#ffd60a", "#34c759", "#ff9500", "#bf5af2", "#ffffff", "#111111")
DEFAULT_SIZES = {"PENCIL": 3, "BRUSH": 8, "ERASER": 20, "TEXT": 24, "LINE": 3, "ARROW": 3, "ELLIPSE": 3,
                 "RECT": 3, "TRANSFORM": 3}
FREEHAND = ("PENCIL", "BRUSH")
SHAPES = ("LINE", "ARROW", "ELLIPSE", "RECT")


def _settings():
    return QtCore.QSettings("QtShell", "QtShell")


def _hub():
    from . import app
    return app.hub()


def _mw():
    h = _hub()
    return getattr(h, "main_window", None) if h is not None else None


def _status(text, ms=4000):
    mw = _mw()
    if mw is not None:
        mw.statusBar().showMessage(text, ms)


# ---------------------------------------------------------------- settings of the tools (shared)
class Settings(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        s = _settings()

        def val(key, default, kind=str):
            v = s.value(f"bluepencil/{key}", None)
            if v is None:
                return default
            try:
                if kind is bool:
                    return str(v).lower() == "true"
                return kind(v)
            except (TypeError, ValueError):
                return default
        self.color = val("color", PALETTE[0])
        self.sizes = {t: val(f"size_{t.lower()}", d, float) for t, d in DEFAULT_SIZES.items()}
        self.opacity = val("opacity", 1.0, float)
        self.pressure = val("pressure", True, bool)
        self.ghost_prev = val("ghost_prev", False, bool)
        self.ghost_next = val("ghost_next", False, bool)
        self.ghost_count_prev = val("ghost_count_prev", 2, int)
        self.ghost_count_next = val("ghost_count_next", 2, int)
        self.ghost_color_prev = val("ghost_color_prev", "#ff5a5a")
        self.ghost_color_next = val("ghost_color_next", "#4fd16a")
        self.ghost_playback = val("ghost_playback", False, bool)
        self.timeline_frames = val("timeline_frames", "ACTIVE")       # ALWAYS / ACTIVE / OFF
        self.move_next = val("move_next", False, bool)
        self.show = val("show", True, bool)

    def set(self, key, value):
        setattr(self, key, value)
        _settings().setValue(f"bluepencil/{key}", "true" if value is True else "false" if value is False else value)
        self.changed.emit()

    def size(self, tool):
        return float(self.sizes.get(tool, 3))

    def set_size(self, tool, v):
        v = max(1.0, min(200.0, float(v)))
        self.sizes[tool] = v
        _settings().setValue(f"bluepencil/size_{tool.lower()}", v)
        self.changed.emit()


_settings_obj = None


def settings():
    global _settings_obj
    if _settings_obj is None:
        _settings_obj = Settings()
    return _settings_obj


class _Signals(QtCore.QObject):
    changed = QtCore.Signal()          # the drawings / layers changed
    selection = QtCore.Signal()        # the Transform tool's selection changed


signals = _Signals()


def tool_state():
    from . import gizmo
    return gizmo.tool_state(_hub())


def current_tool():
    v = tool_state().variant("BLUE_PENCIL")
    return v if v in TOOL_IDS else "PENCIL"


def tool_active():
    try:
        return tool_state().tool == "BLUE_PENCIL"
    except Exception:
        return False


def set_tool(tool):
    """Activates Blue Pencil with a drawing tool (toolbar variant)."""
    tool_state().set_tool("BLUE_PENCIL", tool)


# ---------------------------------------------------------------- data (scene ID property, JSON)
_cache = {}            # scene pointer → (raw string, parsed data)


def _empty():
    return {"v": 1, "active": 0, "layers": []}


def data(scene=None):
    """The scene's Blue Pencil data (cached; re-read when the property changed – undo, file load)."""
    sc = scene or bpy.context.scene
    if sc is None:
        return _empty()
    try:
        raw = sc.get(PROP)
    except Exception:
        raw = None
    key = sc.as_pointer()
    c = _cache.get(key)
    if c is not None and c[0] == raw:
        return c[1]
    d = _empty()
    if isinstance(raw, str) and raw:
        try:
            got = json.loads(raw)
            if isinstance(got, dict) and isinstance(got.get("layers"), list):
                d = got
        except ValueError:
            bridge.log("Blue Pencil: the scene's drawings could not be read", "WARNING")
    for lay in d["layers"]:
        lay.setdefault("name", "Layer")
        lay.setdefault("camera", "")
        lay.setdefault("state", "ANIMATION")
        lay.setdefault("visible", True)
        lay.setdefault("opacity", 1.0)
        lay.setdefault("frames", {})
    _cache[key] = (raw, d)
    return d


def commit(message, scene=None):
    """Writes the (edited) data back to the scene: saved with the file, one Blender undo step."""
    sc = scene or bpy.context.scene
    d = data(sc)
    raw = json.dumps(d, separators=(",", ":"))
    sc[PROP] = raw
    _cache[sc.as_pointer()] = (raw, d)
    bridge.undo_push(f"Blue Pencil: {message}")
    signals.changed.emit()


def layers(d=None):
    return (d or data())["layers"]


def active_index(d=None):
    d = d or data()
    n = len(d["layers"])
    if not n:
        return -1
    return max(0, min(int(d.get("active", 0)), n - 1))


def active_layer(d=None):
    d = d or data()
    i = active_index(d)
    return d["layers"][i] if i >= 0 else None


def set_active(i):
    d = data()
    if 0 <= i < len(d["layers"]):
        d["active"] = i
        commit("Active Layer")


def unique_name(d, base="Layer"):
    names = {lay["name"] for lay in d["layers"]}
    n = 1
    while f"{base} {n}" in names:
        n += 1
    return f"{base} {n}"


def new_layer(name=None, camera=None, state="ANIMATION", do_commit=True):
    """A new layer on top of the list (active). camera: camera object name or "" = the View."""
    d = data()
    if camera is None:
        camera = view_camera_name()
    lay = {"name": name or unique_name(d), "camera": camera, "state": state, "visible": True, "opacity": 1.0,
           "frames": {}}
    d["layers"].insert(0, lay)
    d["active"] = 0
    if do_commit:
        commit("New Layer")
    return lay


def view_camera_name():
    """Camera of the active 3D view when it looks through one, else "" (the View)."""
    mw = _mw()
    vp = getattr(mw, "viewport", None) if mw is not None else None
    sc = bpy.context.scene
    if vp is not None and getattr(vp, "camera_view", False) and sc.camera is not None:
        return sc.camera.name
    return ""


def keys(layer):
    return sorted(int(k) for k in layer["frames"])


def held_key(layer, f):
    """The frame shown at f (the last key at or before f), or None."""
    best = None
    for k in layer["frames"]:
        k = int(k)
        if k <= f and (best is None or k > best):
            best = k
    return best


def strokes_at(layer, f):
    k = held_key(layer, f)
    return layer["frames"].get(str(k), []) if k is not None else []


def current_frame():
    h = _hub()
    f = getattr(h, "display_frame", None) if h is not None else None
    return int(f) if f is not None else int(bpy.context.scene.frame_current)


def target_key(layer, f):
    """Frame a new stroke goes to (creates it when needed) – None when the layer is locked."""
    st = layer.get("state", "ANIMATION")
    if st == "LOCKED":
        return None
    if st == "STATIC":
        k = held_key(layer, f)
        if k is None:
            k = f
    else:
        k = f                                # autokey
    layer["frames"].setdefault(str(k), [])
    return k


# ---------------------------------------------------------------- view geometry
def camera_rect(vp):
    """The camera frame (render size) of a camera view in widget coordinates."""
    sc = bpy.context.scene
    cam = sc.camera
    full = QtCore.QRectF(vp.rect())
    if cam is None or cam.type != "CAMERA":
        return full
    try:
        pts = [vp.project(cam.matrix_world @ v) for v in cam.data.view_frame(scene=sc)]
    except Exception:
        return full
    if any(q is None for q in pts):
        return full
    xs = [q.x() for q in pts]
    ys = [q.y() for q in pts]
    r = QtCore.QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    return r if r.height() > 4 and r.width() > 4 else full


def view_space(vp):
    """(camera name or "" for the View, frame rect in widget coordinates)."""
    sc = bpy.context.scene
    if getattr(vp, "camera_view", False) and sc.camera is not None:
        return sc.camera.name, camera_rect(vp)
    return "", QtCore.QRectF(vp.rect())


def to_norm(pt, rect):
    h = max(rect.height(), 1.0)
    return [round((pt.x() - rect.left()) / h, 5), round((pt.y() - rect.top()) / h, 5)]


def to_screen(xy, rect):
    h = rect.height()
    return QtCore.QPointF(rect.left() + xy[0] * h, rect.top() + xy[1] * h)


def frame_scale(rect):
    return max(rect.height(), 1.0) / REF_H


# ---------------------------------------------------------------- drawing strokes
def _color(stroke, alpha, tint=None):
    if tint is not None:
        c = QtGui.QColor(tint)
    else:
        rgb = stroke.get("c", [0.2, 0.5, 1.0])
        c = QtGui.QColor.fromRgbF(*[max(0.0, min(1.0, float(x))) for x in rgb[:3]])
    c.setAlphaF(max(0.0, min(1.0, float(stroke.get("o", 1.0)) * alpha)))
    return c


def _brush_outline(pts, widths):
    """Filled outline of a stroke with a width per point."""
    n = len(pts)
    left, right = [], []
    for i in range(n):
        a = pts[max(0, i - 1)]
        b = pts[min(n - 1, i + 1)]
        dx, dy = b.x() - a.x(), b.y() - a.y()
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        hw = widths[i] / 2
        left.append(QtCore.QPointF(pts[i].x() + nx * hw, pts[i].y() + ny * hw))
        right.append(QtCore.QPointF(pts[i].x() - nx * hw, pts[i].y() - ny * hw))
    return QtGui.QPolygonF(left + right[::-1])


def brush_widths(raw, w):
    """Widths along a brush stroke: pressure × a taper over the first / last 20 % of its length."""
    pts = [QtCore.QPointF(p[0], p[1]) if not isinstance(p, QtCore.QPointF) else p for p in raw]
    n = len(pts)
    acc = [0.0]
    for i in range(1, n):
        acc.append(acc[-1] + math.hypot(pts[i].x() - pts[i - 1].x(), pts[i].y() - pts[i - 1].y()))
    total = acc[-1] or 1.0
    out = []
    for i in range(n):
        t = acc[i] / total
        taper = min(1.0, t / 0.2, (1 - t) / 0.2) if total > 0 else 1.0
        taper = 0.25 + 0.75 * max(0.0, taper)
        pr = raw[i][2] if (not isinstance(raw[i], QtCore.QPointF) and len(raw[i]) > 2) else 1.0
        out.append(max(0.6, w * taper * max(0.15, pr)))
    return out


def draw_stroke(p, s, rect, alpha=1.0, tint=None):
    sc = frame_scale(rect)
    kind = s.get("k", "PENCIL")
    col = _color(s, alpha, tint)
    w = max(0.6, float(s.get("w", 3)) * sc)
    raw = s.get("p", [])
    pts = [to_screen(q, rect) for q in raw]
    if not pts:
        return
    if kind == "TEXT":
        f = QtGui.QFont(p.font())
        f.setPixelSize(max(4, int(float(s.get("fs", 24)) * sc)))
        p.setFont(f)
        p.setPen(col)
        fm = QtGui.QFontMetricsF(f)
        y = pts[0].y() + fm.ascent()
        for line in str(s.get("t", "")).split("\n"):
            p.drawText(QtCore.QPointF(pts[0].x(), y), line)
            y += fm.lineSpacing()
        return
    if kind == "BRUSH" and len(pts) > 1:
        widths = brush_widths([[q.x(), q.y(), (raw[i][2] if len(raw[i]) > 2 else 1.0)]
                               for i, q in enumerate(pts)], w)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(col)
        p.drawPolygon(_brush_outline(pts, widths), QtCore.Qt.WindingFill)
        p.drawEllipse(pts[0], widths[0] / 2, widths[0] / 2)
        p.drawEllipse(pts[-1], widths[-1] / 2, widths[-1] / 2)
        return
    pen = QtGui.QPen(col, w)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.NoBrush)
    if len(pts) == 1:
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(pts[0], w / 2, w / 2)
        return
    if kind in ("PENCIL", "BRUSH"):
        p.drawPolyline(QtGui.QPolygonF(pts))
    elif kind == "LINE":
        p.drawLine(pts[0], pts[-1])
    elif kind == "ARROW":
        a, b = pts[0], pts[-1]
        p.drawLine(a, b)
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        hl = max(9.0 * sc, w * 3.2)
        head = QtGui.QPolygonF([b,
                                QtCore.QPointF(b.x() - hl * math.cos(ang - 0.45), b.y() - hl * math.sin(ang - 0.45)),
                                QtCore.QPointF(b.x() - hl * math.cos(ang + 0.45), b.y() - hl * math.sin(ang + 0.45))])
        p.setBrush(col)
        p.drawPolygon(head)
    elif kind == "RECT":
        p.drawRect(QtCore.QRectF(pts[0], pts[-1]).normalized())
    elif kind == "ELLIPSE":
        p.drawEllipse(QtCore.QRectF(pts[0], pts[-1]).normalized())


def stroke_bounds(s, rect):
    """Bounding rect of a stroke in widget coordinates."""
    pts = [to_screen(q, rect) for q in s.get("p", [])]
    if not pts:
        return QtCore.QRectF()
    if s.get("k") == "TEXT":
        f = QtGui.QFont()
        f.setPixelSize(max(4, int(float(s.get("fs", 24)) * frame_scale(rect))))
        fm = QtGui.QFontMetricsF(f)
        lines = str(s.get("t", "")).split("\n")
        w = max([fm.horizontalAdvance(x) for x in lines] + [4.0])
        return QtCore.QRectF(pts[0].x(), pts[0].y(), w, fm.lineSpacing() * len(lines))
    xs = [q.x() for q in pts]
    ys = [q.y() for q in pts]
    hw = float(s.get("w", 3)) * frame_scale(rect) / 2
    return QtCore.QRectF(min(xs) - hw, min(ys) - hw, max(xs) - min(xs) + 2 * hw, max(ys) - min(ys) + 2 * hw)


def ghost_frames(layer, f, st=None):
    """[(key, colour, alpha)] of the ghosted frames around the frame shown at f."""
    st = st or settings()
    ks = keys(layer)
    k = held_key(layer, f)
    out = []
    if st.ghost_prev:
        before = [x for x in ks if (k is not None and x < k)]
        for j, x in enumerate(reversed(before[-max(1, st.ghost_count_prev):])):
            out.append((x, st.ghost_color_prev, 0.45 * (0.6 ** j)))
    if st.ghost_next:
        after = [x for x in ks if x > (k if k is not None else f)]
        for j, x in enumerate(after[:max(1, st.ghost_count_next)]):
            out.append((x, st.ghost_color_next, 0.45 * (0.6 ** j)))
    return out


def paint(vp, p):
    """All Blue Pencil drawings of a 3D view (called from its paintEvent)."""
    st = settings()
    tools = getattr(vp, "bp_tools", None)
    d = data()
    if st.show and d["layers"]:
        cam, rect = view_space(vp)
        f = current_frame()
        playing = bool(getattr(_hub(), "playing", False))
        act = active_index(d)
        hide = tools.hidden_strokes() if tools is not None else set()
        p.save()
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        for i in reversed(range(len(d["layers"]))):
            lay = d["layers"][i]
            if not lay.get("visible", True) or lay.get("camera", "") != cam:
                continue
            op = float(lay.get("opacity", 1.0))
            if i == act and (not playing or st.ghost_playback) and lay.get("state") != "STATIC":
                for k, colr, a in ghost_frames(lay, f, st):
                    for s in lay["frames"].get(str(k), []):
                        draw_stroke(p, s, rect, a * op, colr)
            k = held_key(lay, f)
            if k is None:
                continue
            for j, s in enumerate(lay["frames"].get(str(k), [])):
                if (i, k, j) in hide:
                    continue
                draw_stroke(p, s, rect, op)
        p.restore()
    if tools is not None:
        tools.paint(p)


# ---------------------------------------------------------------- erasing
def _seg_dist(p, a, b):
    ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    t = 0.0 if ll == 0 else max(0.0, min(1.0, ((p.x() - ax) * dx + (p.y() - ay) * dy) / ll))
    return math.hypot(p.x() - (ax + t * dx), p.y() - (ay + t * dy))


def _shape_outline(s, rect):
    pts = [to_screen(q, rect) for q in s.get("p", [])]
    k = s.get("k")
    if k in ("RECT", "ELLIPSE") and len(pts) >= 2:
        r = QtCore.QRectF(pts[0], pts[-1]).normalized()
        if k == "RECT":
            return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft(), r.topLeft()]
        c = r.center()
        return [QtCore.QPointF(c.x() + r.width() / 2 * math.cos(a * math.pi / 24),
                               c.y() + r.height() / 2 * math.sin(a * math.pi / 24)) for a in range(49)]
    return pts


def erase_at(strokes, pos, radius, rect):
    """Erases around pos (widget coordinates) – lines are cut, other strokes removed. True if changed."""
    changed = False
    out = []
    for s in strokes:
        k = s.get("k", "PENCIL")
        if k == "TEXT":
            if stroke_bounds(s, rect).adjusted(-radius, -radius, radius, radius).contains(pos):
                changed = True
                continue
            out.append(s)
            continue
        if k in FREEHAND:
            pts = [to_screen(q, rect) for q in s["p"]]
            keep = [math.hypot(q.x() - pos.x(), q.y() - pos.y()) > radius for q in pts]
            if all(keep):
                out.append(s)
                continue
            changed = True
            run = []
            for q, kp in zip(s["p"], keep):
                if kp:
                    run.append(q)
                else:
                    if len(run) > 1:
                        out.append(dict(s, p=run))
                    run = []
            if len(run) > 1:
                out.append(dict(s, p=run))
            continue
        pts = _shape_outline(s, rect)
        hit = any(_seg_dist(pos, pts[i], pts[i + 1]) <= radius for i in range(len(pts) - 1)) if len(pts) > 1 \
            else bool(pts and math.hypot(pts[0].x() - pos.x(), pts[0].y() - pos.y()) <= radius)
        if hit:
            changed = True
        else:
            out.append(s)
    if changed:
        strokes[:] = out
    return changed


# ---------------------------------------------------------------- frame operations (active layer)
_frame_clip = None       # strokes of a copied frame
_stroke_clip = None      # strokes copied with the Transform tool / Ctrl+C


def _editable(lay):
    if lay is None:
        _status("Blue Pencil: no layer – draw something or add a layer first")
        return False
    if lay.get("state") == "LOCKED":
        _status(f"Blue Pencil: layer '{lay['name']}' is locked")
        return False
    return True


def insert_frame(f=None):
    lay = active_layer()
    if not _editable(lay):
        return False
    f = current_frame() if f is None else f
    if str(f) in lay["frames"]:
        _status(f"Blue Pencil: frame {f} exists already")
        return False
    lay["frames"][str(f)] = []
    commit("Insert Frame")
    return True


def duplicate_frame(f=None):
    """Copies the frame shown before f to a new frame at f."""
    lay = active_layer()
    if not _editable(lay):
        return False
    f = current_frame() if f is None else f
    if str(f) in lay["frames"]:
        _status(f"Blue Pencil: frame {f} exists already")
        return False
    k = held_key(lay, f - 1)
    lay["frames"][str(f)] = json.loads(json.dumps(lay["frames"].get(str(k), []))) if k is not None else []
    commit("Duplicate Frame")
    return True


def delete_frame(f=None):
    lay = active_layer()
    if not _editable(lay):
        return False
    k = held_key(lay, current_frame() if f is None else f)
    if k is None:
        return False
    del lay["frames"][str(k)]
    commit("Delete Frame")
    return True


def copy_frame(f=None, cut=False):
    global _frame_clip
    lay = active_layer()
    if lay is None:
        return False
    k = held_key(lay, current_frame() if f is None else f)
    if k is None:
        _status("Blue Pencil: nothing to copy here")
        return False
    _frame_clip = json.loads(json.dumps(lay["frames"][str(k)]))
    if cut:
        if not _editable(lay):
            return False
        del lay["frames"][str(k)]
        commit("Cut Frame")
    _status(f"Blue Pencil: frame {k} {'cut' if cut else 'copied'} ({len(_frame_clip)} strokes)", 2500)
    return True


def paste_frame(f=None):
    lay = active_layer()
    if _frame_clip is None:
        _status("Blue Pencil: the frame clipboard is empty")
        return False
    if not _editable(lay):
        return False
    f = current_frame() if f is None else f
    lay["frames"][str(f)] = json.loads(json.dumps(_frame_clip))
    commit("Paste Frame")
    return True


def step(direction):
    """Previous / next frame of the active layer (Blue Pencil's frame stepping)."""
    lay = active_layer()
    if lay is None:
        return False
    f = current_frame()
    ks = keys(lay)
    cand = [k for k in ks if k > f] if direction > 0 else [k for k in ks if k < f]
    if not cand:
        return False
    go_to(cand[0] if direction > 0 else cand[-1])
    return True


def go_to(f):
    sc = bpy.context.scene
    sc.frame_set(int(f))
    mw = _mw()
    if mw is not None:
        try:
            mw.timeline.sync()
        except Exception:
            pass


def move_keys(layer, moves):
    """{old: new} for keys of a layer. False (nothing changed) when two frames would land on one time."""
    fr = layer["frames"]
    staying = {int(k) for k in fr} - set(moves)
    targets = list(moves.values())
    if len(set(targets)) != len(targets) or staying & set(targets):
        return False
    taken = {k: fr[str(k)] for k in moves}
    for k in moves:
        del fr[str(k)]
    for k, nk in moves.items():
        fr[str(nk)] = taken[k]
    return True


# ---------------------------------------------------------------- retiming
def retime(mode, n, selection=None):
    """Retiming tool. mode "ABS": exactly n frames between keys (1–6); "REL": ±n frames after the key.
    selection: selected keys (timeline) – None uses the key at the current time."""
    global _tl_sel
    lay = active_layer()
    if not _editable(lay):
        return False
    ks = keys(lay)
    if not ks:
        return False
    f = current_frame()
    sel = sorted(k for k in (selection or ()) if k in ks)
    moves = {}
    if mode == "ABS":
        if len(sel) >= 2:
            new = {}
            pos = sel[0]
            shift = 0
            for k in ks:
                if k <= sel[0]:
                    continue
                if k in sel:                 # each selected key n frames after the previous selected one
                    pos = pos + n
                    shift = pos - k
                new[k] = k + shift           # keys in between / after keep their offset
            moves = {k: v for k, v in new.items() if v != k}
        else:
            cur = held_key(lay, f)
            if cur is None:
                cur = ks[0]
            nxt = [k for k in ks if k > cur]
            if not nxt:
                return False
            delta = cur + n - nxt[0]
            moves = {k: k + delta for k in nxt} if delta else {}
    else:
        anchors = sel if sel else [held_key(lay, f) if held_key(lay, f) is not None else ks[0]]
        total = {}
        for a in anchors:
            nxt = [k for k in ks if k > a]
            if not nxt:
                continue
            gap = nxt[0] + total.get(nxt[0], 0) - (a + total.get(a, 0))
            if n < 0 and gap + n < 1:
                continue                     # removing frames only while the gap is bigger than one frame
            for k in nxt:
                total[k] = total.get(k, 0) + n
        moves = {k: k + d for k, d in total.items() if d}
    if not moves:
        return False
    if not move_keys(lay, moves):
        _status("Blue Pencil: retiming would put two frames on one time")
        return False
    commit("Retime")
    _tl_sel = {moves.get(k, k) for k in _tl_sel}
    if settings().move_next:
        cur = held_key(lay, f)
        nxt = [k for k in keys(lay) if cur is not None and k > cur]
        if nxt:
            go_to(nxt[0])
    return True


# ---------------------------------------------------------------- timeline (frame ticks, moving frames)
_tl_sel = set()          # selected Blue Pencil frames (active layer) in the Timeline


def timeline_visible():
    st = settings()
    if st.timeline_frames == "OFF" or not st.show:
        return False
    return st.timeline_frames == "ALWAYS" or tool_active()


def _tl_y(bar):
    return bar.ruler_h() + theme.px(7)


def timeline_key_at(bar, pos):
    lay = active_layer()
    if lay is None or not timeline_visible():
        return None
    if abs(pos.y() - _tl_y(bar)) > theme.px(6):
        return None
    best = None
    for k in keys(lay):
        dx = abs(bar.frame_to_x(k) - pos.x())
        if dx <= theme.px(6) and (best is None or dx < best[0]):
            best = (dx, k)
    return best[1] if best else None


def paint_timeline(bar, p):
    lay = active_layer()
    if lay is None or not timeline_visible():
        return
    drag = getattr(bar, "_bp_drag", None)
    ks = keys(lay)
    y = _tl_y(bar)
    hw, hh = theme.px(3), theme.px(5)
    moved = {}
    clash = set()
    if drag is not None and drag["delta"]:
        moved = {k: k + drag["delta"] for k in drag["keys"]}
        staying = set(ks) - set(moved)
        clash = {k for k, nk in moved.items() if nk in staying}
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor("#0d1a2e"), 1))
    for k in ks:
        x = bar.frame_to_x(moved.get(k, k))
        if x < -10 or x > bar.width() + 10:
            continue
        col = "#e04040" if k in clash else ("#ffffff" if k in _tl_sel else "#5aa0ff")
        p.setBrush(QtGui.QColor(col))
        p.drawRoundedRect(QtCore.QRectF(x - hw, y - hh, 2 * hw, 2 * hh), 1.5, 1.5)
    p.restore()


def timeline_press(bar, ev):
    """Left click on a Blue Pencil frame tick: select it (Shift: add) and start moving."""
    global _tl_sel
    if ev.button() != QtCore.Qt.LeftButton:
        return False
    k = timeline_key_at(bar, ev.position())
    if k is None:
        if not ev.modifiers() & QtCore.Qt.ShiftModifier and _tl_sel:
            _tl_sel = set()
        return False
    if ev.modifiers() & QtCore.Qt.ShiftModifier:
        _tl_sel ^= {k}
        if k not in _tl_sel:
            bar.update()
            return True
    elif k not in _tl_sel:
        _tl_sel = {k}
    bar._bp_drag = {"start": k, "delta": 0, "keys": sorted(_tl_sel)}
    bar.update()
    return True


def timeline_move(bar, ev):
    drag = getattr(bar, "_bp_drag", None)
    if drag is None:
        return False
    drag["delta"] = bar.x_to_frame(ev.position().x()) - drag["start"]
    bar.update()
    return True


def timeline_release(bar, ev):
    global _tl_sel
    drag = getattr(bar, "_bp_drag", None)
    if drag is None:
        return False
    bar._bp_drag = None
    lay = active_layer()
    if drag["delta"] and lay is not None and _editable(lay):
        moves = {k: k + drag["delta"] for k in drag["keys"]}
        if move_keys(lay, moves):
            _tl_sel = set(moves.values())
            commit("Move Frames")
        else:
            _status("Blue Pencil: two frames can't be on one time – the move was cancelled")
    bar.update()
    return True


def timeline_select_range(a, b):
    """Shift + drag in the Timeline also selects Blue Pencil frames in the range (frames a..b)."""
    global _tl_sel
    lay = active_layer()
    if lay is None or not timeline_visible():
        return
    _tl_sel |= {k for k in keys(lay) if a <= k <= b}


def selected_frames():
    return set(_tl_sel)


# ---------------------------------------------------------------- the interactive tool (one per 3D view)
class BPTools:
    """Mouse / key handling of the Blue Pencil tool in a 3D view."""

    @property
    def sel(self):
        return self._sel

    @sel.setter
    def sel(self, value):
        changed = value != getattr(self, "_sel", None)
        self._sel = value
        if changed:
            signals.selection.emit()

    def __init__(self, vp):
        self.vp = vp
        self.text_edit = None       # (layer, key, index) of the text being edited
        self.cur = None             # free-hand: [[x, y, pressure]] in widget coordinates
        self.shape = None           # [QPointF start, QPointF end]
        self.erasing = False
        self.erased = False
        self.mouse = None
        self.text = None            # QLineEdit while typing a note
        self.text_at = None
        self.sel = None             # {"layer": i, "key": k, "idx": [stroke indices]}
        self.xf = QtGui.QTransform()
        self.drag = None            # transform drag {"mode", "start", "base", "pivot"}
        self.rubber = None          # [QPointF, QPointF]
        self._prev_tool = None      # E toggles the eraser and back
        self._erase_last = None

    # --- state
    def active(self):
        return tool_active()

    def tool(self):
        return current_tool()

    def busy(self):
        return bool(self.cur is not None or self.shape is not None or self.erasing or self.drag or self.rubber
                    or self.text is not None)

    def hidden_strokes(self):
        """Strokes drawn by the tool itself (the transformed selection) or being edited (text)."""
        out = set()
        if self.sel is not None:
            out = {(self.sel["layer"], self.sel["key"], j) for j in self.sel["idx"]}
        if self.text_edit is not None and self.text is not None:
            out.add(tuple(self.text_edit))
        return out

    def note_at(self, pos):
        """(layer, key, index) of the text note under pos (frame shown, layers of this view; the active
        layer first, then from the top), or None."""
        cam, rect = self._space()
        d = data()
        f = current_frame()
        act = active_index(d)
        order = ([act] if act >= 0 else []) + [i for i in range(len(d["layers"])) if i != act]
        for i in order:
            lay = d["layers"][i]
            if lay.get("camera", "") != cam or not lay.get("visible", True):
                continue
            k = held_key(lay, f)
            if k is None:
                continue
            fr = lay["frames"][str(k)]
            for j in range(len(fr) - 1, -1, -1):
                if fr[j].get("k") == "TEXT" and stroke_bounds(fr[j], rect).adjusted(-4, -4, 4, 4).contains(pos):
                    return (i, k, j)
        return None

    def _stroke(self, ref):
        try:
            i, k, j = ref
            return data()["layers"][i]["frames"][str(k)][j]
        except (IndexError, KeyError, TypeError):
            return None

    def edit_text(self, ref):
        """Opens a text note for editing (Enter: done, Esc: cancel, emptied: deleted)."""
        s = self._stroke(ref)
        if s is None:
            return False
        lay = data()["layers"][ref[0]]
        if not _editable(lay):
            return False
        if self.sel is not None:
            self.apply_transform()
            self.sel = None
        _cam, rect = self._space()
        self._start_text(to_screen(s["p"][0], rect), edit=tuple(ref))
        return True

    def _space(self):
        return view_space(self.vp)

    def _layer_for_view(self, create=True):
        """The layer to draw into: the active one when it belongs to this view, else the first that does
        (made active), else a new one."""
        cam, _r = self._space()
        d = data()
        act = active_index(d)
        if act >= 0 and d["layers"][act].get("camera", "") == cam:
            return act, d["layers"][act]
        for i, lay in enumerate(d["layers"]):
            if lay.get("camera", "") == cam:
                d["active"] = i
                return i, lay
        if not create:
            return -1, None
        new_layer(camera=cam, do_commit=False)
        return 0, d["layers"][0]

    def _base_stroke(self, kind):
        st = settings()
        c = QtGui.QColor(st.color)
        return {"k": kind, "c": [round(c.redF(), 4), round(c.greenF(), 4), round(c.blueF(), 4)],
                "o": round(float(st.opacity), 3), "w": st.size(kind if kind != "TEXT" else "PENCIL")}

    def _add(self, stroke, message):
        i, lay = self._layer_for_view()
        if not _editable(lay):
            return False
        k = target_key(lay, current_frame())
        lay["frames"][str(k)].append(stroke)
        commit(message)
        return True

    # --- mouse
    def press(self, ev, pos):
        if not self.active():
            return False
        b = ev.button()
        mods = ev.modifiers()
        if mods & QtCore.Qt.AltModifier:
            return False                  # navigation
        tool = self.tool()
        if self.text is not None:
            self._finish_text(True)
            if b == QtCore.Qt.LeftButton and tool == "TEXT":
                return True
        if b == QtCore.Qt.RightButton:
            if self.busy():
                self.cancel()
                return True
            self.context_menu(ev.globalPosition().toPoint())
            return True
        if b == QtCore.Qt.MiddleButton:
            if tool == "TRANSFORM" and self.sel is not None:
                self._start_xf("SCALE_XY" if mods & QtCore.Qt.ShiftModifier else "SCALE", pos)
                return True
            return False
        if b != QtCore.Qt.LeftButton:
            return False
        self.mouse = pos
        if tool != "TRANSFORM" and tool != "ERASER":
            _i, lay = self._layer_for_view()
            if lay is not None and lay.get("state") == "LOCKED":
                _status(f"Blue Pencil: layer '{lay['name']}' is locked")
                return True
        if tool in FREEHAND:
            self.cur = [[pos.x(), pos.y(), self._pressure(ev)]]
        elif tool in SHAPES:
            self.shape = [QtCore.QPointF(pos), QtCore.QPointF(pos)]
        elif tool == "ERASER":
            self.erasing = True
            self.erased = False
            self._erase(pos)
        elif tool == "TEXT":
            hit = self.note_at(pos)
            if hit is not None:
                self.edit_text(hit)          # click on a note: edit it
            else:
                self._start_text(pos)
        elif tool == "TRANSFORM":
            if self.sel is not None and self._sel_rect().adjusted(-6, -6, 6, 6).contains(pos):
                self._start_xf("ROTATE" if mods & QtCore.Qt.ShiftModifier else "MOVE", pos)
            else:
                self.apply_transform()
                self.sel = None
                self.rubber = [QtCore.QPointF(pos), QtCore.QPointF(pos)]
        self.vp.update()
        return True

    def _pressure(self, ev):
        if not settings().pressure:
            return 1.0
        try:
            pts = ev.points()
            pr = float(pts[0].pressure()) if pts else 1.0
            return pr if 0.0 < pr <= 1.0 else 1.0
        except Exception:
            return 1.0

    def move(self, ev, pos):
        if not self.active():
            return False
        self.mouse = pos
        if self.cur is not None:
            last = self.cur[-1]
            if abs(pos.x() - last[0]) + abs(pos.y() - last[1]) >= 1.5:
                self.cur.append([pos.x(), pos.y(), self._pressure(ev)])
        elif self.shape is not None:
            self.shape[1] = QtCore.QPointF(pos)
            if ev.modifiers() & QtCore.Qt.ShiftModifier and self.tool() in ("RECT", "ELLIPSE"):
                d = self.shape[1] - self.shape[0]
                m = max(abs(d.x()), abs(d.y()))
                self.shape[1] = self.shape[0] + QtCore.QPointF(math.copysign(m, d.x() or 1), math.copysign(m, d.y() or 1))
        elif self.erasing:
            # sweep: erase along the way from the last position (fast mouse moves skip nothing)
            last = self._erase_last or pos
            r = max(2.0, settings().size("ERASER") * theme.ui_scale / 2)
            n = max(1, int(math.hypot(pos.x() - last.x(), pos.y() - last.y()) / r))
            for i in range(1, n + 1):
                self._erase(last + (pos - last) * (i / n))
        elif self.drag is not None:
            self._drag_xf(pos)
        elif self.rubber is not None:
            self.rubber[1] = QtCore.QPointF(pos)
        else:
            if self.tool() == "ERASER":
                self.vp.update()
            return False
        self.vp.update()
        return True

    def release(self, ev, pos):
        if not self.active():
            return False
        b = ev.button()
        if self.drag is not None and b in (QtCore.Qt.LeftButton, QtCore.Qt.MiddleButton):
            self.drag = None
            self.vp.update()
            return True
        if b != QtCore.Qt.LeftButton:
            return False
        if self.cur is not None:
            pts, self.cur = self.cur, None
            self._commit_freehand(pts)
            return True
        if self.shape is not None:
            a, bb = self.shape
            self.shape = None
            if (bb - a).manhattanLength() >= 3:
                _cam, rect = self._space()
                s = self._base_stroke(self.tool())
                s["p"] = [to_norm(a, rect), to_norm(bb, rect)]
                self._add(s, self.tool().title())
            self.vp.update()
            return True
        if self.erasing:
            self.erasing = False
            if self.erased:
                commit("Erase")
            self.vp.update()
            return True
        if self.rubber is not None:
            r = QtCore.QRectF(self.rubber[0], self.rubber[1]).normalized()
            self.rubber = None
            self._select_rect(r if r.width() > 2 or r.height() > 2 else None, click=pos)
            self.vp.update()
            return True
        return True                          # the press was ours (no click-select on release)

    def double_click(self, ev, pos):
        """Double-click on a text note (Text / Transform tool): edit it."""
        if not self.active() or ev.button() != QtCore.Qt.LeftButton or self.tool() not in ("TEXT", "TRANSFORM"):
            return False
        if self.text is not None:
            return True
        hit = self.note_at(pos)
        if hit is None:
            return False
        self.rubber = None
        self.drag = None
        return self.edit_text(hit)

    def wheel(self, ev):
        if not self.active() or not ev.modifiers() & QtCore.Qt.ControlModifier:
            return False
        if self.sel is not None:
            self.scale_selection_size(1.12 ** (ev.angleDelta().y() / 120.0))
            return True
        t = self.tool()
        st = settings()
        st.set_size(t, st.size(t) * (1.12 ** (ev.angleDelta().y() / 120.0)))
        _status(f"Blue Pencil: {t.title()} size {st.size(t):.0f}", 1500)
        self.vp.update()
        return True

    def _commit_freehand(self, pts):
        _cam, rect = self._space()
        kind = self.tool()
        s = self._base_stroke(kind)
        # light smoothing of the mouse path
        if len(pts) > 3:
            sm = [pts[0]]
            for i in range(1, len(pts) - 1):
                sm.append([(pts[i - 1][0] + 2 * pts[i][0] + pts[i + 1][0]) / 4,
                           (pts[i - 1][1] + 2 * pts[i][1] + pts[i + 1][1]) / 4, pts[i][2]])
            sm.append(pts[-1])
            pts = sm
        norm = []
        for x, y, pr in pts:
            q = to_norm(QtCore.QPointF(x, y), rect)
            norm.append(q + [round(pr, 3)] if kind == "BRUSH" else q)
        s["p"] = norm
        self._add(s, kind.title())
        self.vp.update()

    def _erase(self, pos):
        """Erases on the active layer (when it belongs to this view)."""
        self._erase_last = QtCore.QPointF(pos)
        cam, rect = self._space()
        lay = active_layer()
        if lay is None or lay.get("camera", "") != cam or not lay.get("visible", True) or \
                lay.get("state") == "LOCKED":
            return
        k = held_key(lay, current_frame())
        if k is None:
            return
        r = settings().size("ERASER") * theme.ui_scale
        if erase_at(lay["frames"][str(k)], pos, r, rect):
            self.erased = True

    # --- text
    def _start_text(self, pos, edit=None):
        st = settings()
        _cam, rect = self._space()
        old = self._stroke(edit) if edit is not None else None
        size = float(old.get("fs", 24)) if old else st.size("TEXT")
        color = _color(old, 1.0).name() if old else st.color
        ed = QtWidgets.QLineEdit(self.vp)
        f = ed.font()
        f.setPixelSize(max(8, int(size * frame_scale(rect))))
        ed.setFont(f)
        ed.setStyleSheet(f"QLineEdit {{ background: rgba(0,0,0,90); color: {color}; "
                         "border: 1px dashed #bbbbbb; padding: 0px; }")
        ed.setPlaceholderText("Note…")
        if old:
            ed.setText(str(old.get("t", "")))
            ed.selectAll()
        self.text_edit = edit
        ed.move(int(pos.x()), int(pos.y()))
        ed.resize(max(160, int(f.pixelSize() * (len(ed.text()) * 0.62 + 4))), int(f.pixelSize() * 1.6))
        ed.show()
        ed.setFocus()
        ed.returnPressed.connect(lambda: self._finish_text(True))
        self.text = ed
        self.text_at = QtCore.QPointF(pos)

    def _finish_text(self, keep):
        ed, self.text = self.text, None
        if ed is None:
            return
        txt = ed.text().strip()
        ed.hide()
        ed.deleteLater()
        self.vp.setFocus()
        edit, self.text_edit = self.text_edit, None
        if edit is not None:
            s = self._stroke(edit)
            if keep and s is not None and txt != s.get("t"):
                if txt:
                    s["t"] = txt
                else:                        # emptied: the note is deleted
                    del data()["layers"][edit[0]]["frames"][str(edit[1])][edit[2]]
                commit("Edit Text")
            self.vp.update()
            return
        if keep and txt:
            _cam, rect = self._space()
            s = self._base_stroke("TEXT")
            s["t"] = txt
            s["fs"] = settings().size("TEXT")
            s["p"] = [to_norm(self.text_at, rect)]
            self._add(s, "Text")
        self.vp.update()

    # --- transform tool
    def _sel_strokes(self):
        if self.sel is None:
            return []
        d = data()
        try:
            fr = d["layers"][self.sel["layer"]]["frames"][str(self.sel["key"])]
        except (IndexError, KeyError):
            self.sel = None
            return []
        return [fr[j] for j in self.sel["idx"] if j < len(fr)]

    def _sel_rect(self, transformed=True):
        _cam, rect = self._space()
        r = QtCore.QRectF()
        for s in self._sel_strokes():
            r = r.united(stroke_bounds(s, rect))
        return self.xf.mapRect(r) if transformed else r

    def _select_rect(self, r, click=None):
        """Selects the strokes of the active layer's frame shown that are inside / under r (or the click)."""
        cam, rect = self._space()
        d = data()
        i = active_index(d)
        if i < 0 or d["layers"][i].get("camera", "") != cam:
            i, _lay = self._layer_for_view(create=False)
        if i < 0:
            self.sel = None
            return
        lay = d["layers"][i]
        k = held_key(lay, current_frame())
        if k is None:
            self.sel = None
            return
        idx = []
        for j, s in enumerate(lay["frames"][str(k)]):
            b = stroke_bounds(s, rect)
            if r is not None:
                if r.intersects(b) and any(r.contains(to_screen(q, rect)) for q in s["p"]) or \
                        (s.get("k") == "TEXT" and r.intersects(b)):
                    idx.append(j)
            elif click is not None and b.adjusted(-4, -4, 4, 4).contains(click):
                idx.append(j)
        self.sel = {"layer": i, "key": k, "idx": idx} if idx else None
        self.xf = QtGui.QTransform()

    def select_all(self):
        self._select_rect(QtCore.QRectF(-1e6, -1e6, 2e6, 2e6))

    def _start_xf(self, mode, pos):
        r = self._sel_rect(transformed=False)
        self.drag = {"mode": mode, "start": QtCore.QPointF(pos), "base": QtGui.QTransform(self.xf),
                     "pivot": r.center()}

    def _drag_xf(self, pos):
        dg = self.drag
        base = dg["base"]
        pv = base.map(dg["pivot"])
        d = pos - dg["start"]
        op = QtGui.QTransform()
        if dg["mode"] == "MOVE":
            op.translate(d.x(), d.y())
        elif dg["mode"] == "ROTATE":
            a0 = math.atan2(dg["start"].y() - pv.y(), dg["start"].x() - pv.x())
            a1 = math.atan2(pos.y() - pv.y(), pos.x() - pv.x())
            op.translate(pv.x(), pv.y())
            op.rotateRadians(a1 - a0)
            op.translate(-pv.x(), -pv.y())
        else:
            sx = max(0.02, 1.0 + d.x() / 150.0)
            sy = max(0.02, 1.0 - d.y() / 150.0) if dg["mode"] == "SCALE_XY" else sx
            op.translate(pv.x(), pv.y())
            op.scale(sx, sy)
            op.translate(-pv.x(), -pv.y())
        self.xf = base * op

    def apply_transform(self):
        """Enter: the pending move / rotate / scale goes into the strokes."""
        if self.sel is None or self.xf.isIdentity():
            return False
        _cam, rect = self._space()
        det = abs(self.xf.determinant()) ** 0.5
        for s in self._sel_strokes():
            new = []
            for q in s["p"]:
                m = self.xf.map(to_screen(q, rect))
                nq = to_norm(m, rect)
                new.append(nq + list(q[2:]))
            s["p"] = new
            if s.get("k") == "TEXT":
                s["fs"] = round(float(s.get("fs", 24)) * det, 2)
        self.xf = QtGui.QTransform()
        commit("Transform")
        return True

    def scale_selection_size(self, factor):
        """[ / ] or Ctrl + wheel with a selection: font size of text, width of lines."""
        strokes = self._sel_strokes()
        for s in strokes:
            key = "fs" if s.get("k") == "TEXT" else "w"
            s[key] = round(max(1.0, min(400.0, float(s.get(key, 24 if key == "fs" else 3)) * factor)), 2)
        if strokes:
            commit("Size")
            signals.selection.emit()
            self.vp.update()

    def reset_transform(self):
        self.xf = QtGui.QTransform()
        self.vp.update()

    def delete_selected(self):
        if self.sel is None:
            return False
        d = data()
        lay = d["layers"][self.sel["layer"]]
        if not _editable(lay):
            return False
        fr = lay["frames"][str(self.sel["key"])]
        for j in sorted(self.sel["idx"], reverse=True):
            if j < len(fr):
                del fr[j]
        self.sel = None
        self.xf = QtGui.QTransform()
        commit("Delete Strokes")
        self.vp.update()
        return True

    def copy(self, cut=False):
        """Copies the selection (Transform tool) or the whole frame shown of the layer."""
        global _stroke_clip
        self.apply_transform()
        strokes = self._sel_strokes()
        if not strokes:
            _i, lay = self._layer_for_view(create=False)
            strokes = strokes_at(lay, current_frame()) if lay is not None else []
        if not strokes:
            _status("Blue Pencil: nothing to copy")
            return False
        _stroke_clip = json.loads(json.dumps(strokes))
        if cut:
            if self.sel is not None:
                self.delete_selected()
            else:
                _i, lay = self._layer_for_view(create=False)
                k = held_key(lay, current_frame()) if lay is not None else None
                if k is not None and _editable(lay):
                    lay["frames"][str(k)] = []
                    commit("Cut")
        _status(f"Blue Pencil: {len(_stroke_clip)} strokes {'cut' if cut else 'copied'}", 2500)
        return True

    def paste(self, transform=False):
        """Paste (applied at once) or Paste and Transform (selected; Enter applies)."""
        if not _stroke_clip:
            _status("Blue Pencil: the clipboard is empty")
            return False
        self.apply_transform()
        i, lay = self._layer_for_view()
        if not _editable(lay):
            return False
        k = target_key(lay, current_frame())
        fr = lay["frames"][str(k)]
        start = len(fr)
        fr.extend(json.loads(json.dumps(_stroke_clip)))
        commit("Paste")
        if transform:
            set_tool("TRANSFORM")
            self.sel = {"layer": i, "key": k, "idx": list(range(start, len(fr)))}
            self.xf = QtGui.QTransform()
        self.vp.update()
        return True

    # --- keys
    def owns_key(self, ev):
        if not self.active():
            return False
        if self.text is not None:
            return True
        names = keymap.event_names(ev)
        return any(k in names for aid in BP_ACTIONS for k in keymap.keys(aid))

    def key(self, ev, H):
        if not self.active():
            return False
        if self.text is not None:
            if ev.key() == QtCore.Qt.Key_Escape:
                self._finish_text(False)
                return True
            return False
        if H("bp.cancel"):
            if self.busy() or self.sel is not None:
                self.cancel()
                return True
            return False
        if H("bp.apply"):
            if self.tool() == "TRANSFORM":
                if self.sel is None:
                    self.select_all()
                else:
                    self.apply_transform()
                self.vp.update()
                return True
            return False
        if H("bp.reset"):
            if self.sel is not None:
                self.reset_transform()
                return True
            return False
        if H("bp.delete"):
            return self.delete_selected() or True
        if H("bp.copy"):
            return self.copy() or True
        if H("bp.cut"):
            return self.copy(cut=True) or True
        if H("bp.paste_transform"):
            return self.paste(transform=True) or True
        if H("bp.paste"):
            return self.paste() or True
        if H("bp.step_prev"):
            step(-1)
            return True
        if H("bp.step_next"):
            step(1)
            return True
        if (H("bp.size_up") or H("bp.size_down")) and self.sel is not None:
            self.scale_selection_size(1.25 if H("bp.size_up") else 0.8)
            return True
        if H("bp.size_up") or H("bp.size_down"):
            t = self.tool()
            st = settings()
            st.set_size(t, st.size(t) * (1.25 if H("bp.size_up") else 0.8))
            _status(f"Blue Pencil: {t.title()} size {st.size(t):.0f}", 1500)
            self.vp.update()
            return True
        if H("bp.eraser"):
            if self.tool() == "ERASER":
                set_tool(self._prev_tool or "PENCIL")
            else:
                self._prev_tool = self.tool()
                set_tool("ERASER")
            return True
        return False

    def cancel(self):
        if self.text is not None:
            self._finish_text(False)
        self.cur = None
        self.shape = None
        self.erasing = False
        self.rubber = None
        self.drag = None
        if self.sel is not None:
            self.sel = None
            self.xf = QtGui.QTransform()
        self.vp.update()
        return True

    def tool_changed(self):
        """Another tool / variant: an unapplied transform is applied, the rest dropped."""
        if self.sel is not None and (not self.active() or self.tool() != "TRANSFORM"):
            self.apply_transform()
            self.sel = None
        if not self.active():
            self.cancel()

    def context_menu(self, gpos):
        menu = QtWidgets.QMenu(self.vp)
        for tid, name, icon, tip in TOOLS:
            a = menu.addAction(icons.icon(icon), name, lambda t=tid: set_tool(t))
            a.setCheckable(True)
            a.setChecked(self.tool() == tid)
        menu.addSeparator()
        if self.tool() == "TRANSFORM":
            texts = [j for j, s in zip(self.sel["idx"], self._sel_strokes()) if s.get("k") == "TEXT"] \
                if self.sel is not None else []
            if texts:
                ref = (self.sel["layer"], self.sel["key"], texts[0])
                menu.addAction(icons.icon("bp_text"), "Edit Text…", lambda: self.edit_text(ref))
            menu.addAction(keymap.render("Apply Transform\t{bp.apply}"), self.apply_transform)
            menu.addAction(keymap.render("Reset Transform\t{bp.reset}"), self.reset_transform)
            menu.addAction(keymap.render("Delete Selected\t{bp.delete}"), self.delete_selected)
            menu.addSeparator()
        menu.addAction(icons.icon("bp_cut"), keymap.render("Cut\t{bp.cut}"), lambda: self.copy(cut=True))
        menu.addAction(icons.icon("bp_copy"), keymap.render("Copy\t{bp.copy}"), self.copy)
        menu.addAction(icons.icon("bp_paste"), keymap.render("Paste\t{bp.paste}"), self.paste)
        menu.addAction(keymap.render("Paste and Transform\t{bp.paste_transform}"), lambda: self.paste(True))
        menu.addSeparator()
        fm = menu.addMenu("Frame")
        fm.addAction(icons.icon("bp_frame_insert"), "Insert Blank Frame", insert_frame)
        fm.addAction(icons.icon("bp_frame_dup"), "Duplicate Previous Frame", duplicate_frame)
        fm.addAction(icons.icon("bp_frame_delete"), "Delete Frame", delete_frame)
        fm.addSeparator()
        fm.addAction("Cut Frame", lambda: copy_frame(cut=True))
        fm.addAction("Copy Frame", copy_frame)
        fm.addAction("Paste Frame", paste_frame)
        fm.addSeparator()
        fm.addAction(keymap.render("Previous Frame\t{bp.step_prev}"), lambda: step(-1))
        fm.addAction(keymap.render("Next Frame\t{bp.step_next}"), lambda: step(1))
        gm = menu.addMenu("Ghosting")
        st = settings()
        for key, label in (("ghost_prev", "Ghost Previous"), ("ghost_next", "Ghost Next")):
            a = gm.addAction(label)
            a.setCheckable(True)
            a.setChecked(getattr(st, key))
            a.toggled.connect(lambda on, k=key: (st.set(k, on), _views_update()))
        menu.addSeparator()
        a = menu.addAction("Show Drawings")
        a.setCheckable(True)
        a.setChecked(st.show)
        a.toggled.connect(lambda on: (st.set("show", on), _views_update()))
        menu.addAction("Blue Pencil Panel…", show_panel)
        menu.exec(gpos)

    # --- drawing of the tool itself
    def paint(self, p):
        if not self.active():
            return
        st = settings()
        cam, rect = self._space()
        p.save()
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        tool = self.tool()
        if self.cur is not None:
            c = QtGui.QColor(st.color)
            s = {"k": tool, "c": [c.redF(), c.greenF(), c.blueF()], "o": st.opacity, "w": st.size(tool),
                 "p": [to_norm(QtCore.QPointF(x, y), rect) + [pr] for x, y, pr in self.cur]}
            draw_stroke(p, s, rect)
        if self.shape is not None:
            c = QtGui.QColor(st.color)
            s = {"k": tool, "c": [c.redF(), c.greenF(), c.blueF()], "o": st.opacity, "w": st.size(tool),
                 "p": [to_norm(self.shape[0], rect), to_norm(self.shape[1], rect)]}
            draw_stroke(p, s, rect)
        if self.sel is not None:
            d = data()
            lay = d["layers"][self.sel["layer"]] if self.sel["layer"] < len(d["layers"]) else None
            op = float(lay.get("opacity", 1.0)) if lay else 1.0
            p.save()
            p.setTransform(self.xf, True)
            for s in self._sel_strokes():
                draw_stroke(p, s, rect, op)
            p.restore()
            p.setBrush(QtCore.Qt.NoBrush)
            p.setPen(QtGui.QPen(QtGui.QColor("#ffbe33"), 1, QtCore.Qt.DashLine))
            p.drawPolygon(self.xf.map(QtGui.QPolygonF(self._sel_rect(transformed=False))))
        if self.rubber is not None:
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1, QtCore.Qt.DashLine))
            p.setBrush(QtGui.QColor(255, 255, 255, 20))
            p.drawRect(QtCore.QRectF(self.rubber[0], self.rubber[1]).normalized())
        if tool == "ERASER" and self.mouse is not None and self.vp.underMouse():
            r = st.size("ERASER") * theme.ui_scale
            p.setBrush(QtGui.QColor(255, 255, 255, 18 if self.erasing else 0))
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1, QtCore.Qt.DashLine))
            p.drawEllipse(self.mouse, r, r)
        # what is drawn into: layer, frame, camera
        if st.show:
            d = data()
            i = active_index(d)
            lay = d["layers"][i] if i >= 0 else None
            f = current_frame()
            if lay is not None and lay.get("camera", "") == cam:
                k = held_key(lay, f)
                state = lay.get("state", "ANIMATION")
                where = ("new frame" if k != f else f"frame {k}") if state == "ANIMATION" else \
                    (f"frame {k}" if k is not None else "new frame") if state == "STATIC" else "locked"
                info = f"Blue Pencil · {lay['name']} [{STATE_LETTER.get(state, 'A')}] · {where}"
            else:
                info = "Blue Pencil · " + ("a new layer for this camera" if cam else "a new layer for the view")
            f2 = p.font()
            f2.setPixelSize(theme.fs(11))
            p.setFont(f2)
            p.setPen(QtGui.QColor(90, 160, 255, 220))
            p.drawText(QtCore.QPointF(theme.px(10), self.vp.height() - theme.px(10)), info)
            if cam:
                p.setBrush(QtCore.Qt.NoBrush)
                p.setPen(QtGui.QPen(QtGui.QColor(90, 160, 255, 90), 1))
                p.drawRect(rect)
        p.restore()


def _all_tools():
    mw = _mw()
    if mw is None:
        return []
    area = getattr(mw, "viewports", None)
    views = getattr(area, "views", None) or [getattr(mw, "viewport", None)]
    return [v.bp_tools for v in views if v is not None and getattr(v, "bp_tools", None) is not None]


def selected_strokes():
    """Strokes selected with the Transform tool (in any 3D view)."""
    out = []
    for t in _all_tools():
        if t.sel is not None:
            out += t._sel_strokes()
    return out


def apply_to_selection(prop, value, do_commit=True):
    """Colour ("color", "#rrggbb"), size ("size": font size of text, width of lines) or opacity ("opacity",
    0–1) of the strokes selected with the Transform tool. Returns the number of strokes changed."""
    strokes = selected_strokes()
    if not strokes:
        return 0
    for s in strokes:
        if prop == "color":
            c = QtGui.QColor(value)
            s["c"] = [round(c.redF(), 4), round(c.greenF(), 4), round(c.blueF(), 4)]
        elif prop == "size":
            if s.get("k") == "TEXT":
                s["fs"] = float(value)
            else:
                s["w"] = float(value)
        elif prop == "opacity":
            s["o"] = round(float(value), 3)
    if do_commit:
        commit({"color": "Colour", "size": "Size", "opacity": "Opacity"}.get(prop, prop))
    else:
        _views_update()
    return len(strokes)


def _views_update():
    mw = _mw()
    if mw is None:
        return
    area = getattr(mw, "viewports", None)
    for v in (getattr(area, "views", None) or [getattr(mw, "viewport", None)]):
        if v is not None:
            v.update()
    try:
        mw.timeline.bar.update()
    except Exception:
        pass


signals.changed.connect(_views_update)

# keymap actions of the tool (context "3D View · Blue Pencil" – active while the tool is)
BP_ACTIONS = ("bp.step_prev", "bp.step_next", "bp.copy", "bp.cut", "bp.paste", "bp.paste_transform", "bp.delete",
              "bp.apply", "bp.cancel", "bp.reset", "bp.size_up", "bp.size_down", "bp.eraser")


# ---------------------------------------------------------------- the panel (toolbox, ghosting, frames, retime, layers)
def show_panel():
    mw = _mw()
    if mw is None or "bluepencil" not in mw.docks:
        return
    d = mw.docks["bluepencil"]
    d.show()
    d.raise_()


MAX_CUSTOM = 10


def custom_colors():
    """The custom colours chosen last (newest first), kept in QSettings bluepencil/custom_colors."""
    raw = str(_settings().value("bluepencil/custom_colors", "") or "")
    return [c for c in raw.split(",") if QtGui.QColor(c).isValid()][:MAX_CUSTOM]


def set_custom_colors(cols):
    _settings().setValue("bluepencil/custom_colors", ",".join(cols[:MAX_CUSTOM]))
    settings().changed.emit()


def add_custom_color(col):
    col = QtGui.QColor(col).name()
    if col in PALETTE:
        return
    set_custom_colors([col] + [c for c in custom_colors() if c != col])


def remove_custom_color(col):
    set_custom_colors([c for c in custom_colors() if c != col])


def _swatch(color, size=None):
    size = size or theme.px(16)
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtGui.QColor(color))
    return QtGui.QIcon(pm)


class BluePencilPanel(QtWidgets.QScrollArea):
    """Toolbox, tool options, ghosting, frame keys, retiming and the layer manager in one dock."""

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget(self)
        self.setWidget(inner)
        v = QtWidgets.QVBoxLayout(inner)
        v.setContentsMargins(theme.px(6), theme.px(6), theme.px(6), theme.px(6))
        v.setSpacing(theme.px(4))
        st = settings()

        def head(text):
            lab = QtWidgets.QLabel(text, inner)
            f = lab.font()
            f.setBold(True)
            lab.setFont(f)
            v.addWidget(lab)
            return lab

        def tbtn(icon, tip, fn=None, checkable=False, text=None):
            b = QtWidgets.QToolButton(inner)
            if icon:
                icons.set_icon(b, icon)
            if text:
                b.setText(text)
                if not icon:
                    b.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.setCheckable(checkable)
            if fn is not None:
                (b.toggled if checkable else b.clicked).connect(fn)
            return b

        # top row: draw (activate the tool), show
        top = QtWidgets.QHBoxLayout()
        self.draw_btn = QtWidgets.QPushButton("Draw", inner)
        icons.set_icon(self.draw_btn, "tool_blue_pencil", "Draw")
        self.draw_btn.setCheckable(True)
        self.draw_btn.setToolTip("Blue Pencil tool in the 3D viewport (the toolbar's Blue Pencil)")
        pytips.tag(self.draw_btn, 'qt_shell.api.set_tool("BLUE_PENCIL", "PENCIL")')
        self.draw_btn.clicked.connect(self._toggle_draw)
        top.addWidget(self.draw_btn)
        self.show_chk = QtWidgets.QCheckBox("Show drawings", inner)
        self.show_chk.toggled.connect(lambda on: (st.set("show", on), _views_update()))
        top.addWidget(self.show_chk)
        top.addStretch(1)
        v.addLayout(top)

        # toolbox
        head("Toolbox")
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(theme.px(2))
        self.tool_btns = {}
        for n, (tid, name, icon, tip) in enumerate(TOOLS):
            b = tbtn(icon, f"{name} – {tip}", checkable=True)
            b.clicked.connect(lambda _c=False, t=tid: set_tool(t))
            pytips.tag(b, f'qt_shell.api.set_tool("BLUE_PENCIL", "{tid}")')
            grid.addWidget(b, n // 9, n % 9)
            self.tool_btns[tid] = b
        v.addLayout(grid)
        # colour
        crow = QtWidgets.QHBoxLayout()
        crow.setSpacing(theme.px(2))
        self.color_btn = tbtn(None, "Current drawing colour – click to choose a custom colour", self._pick_color)
        crow.addWidget(self.color_btn)
        for c in PALETTE:
            b = QtWidgets.QToolButton(inner)
            b.setIcon(_swatch(c, theme.px(12)))
            b.setAutoRaise(True)
            b.setToolTip(c)
            b.clicked.connect(lambda _c=False, col=c: self._set_color(col))
            crow.addWidget(b)
        self.custom_btn = QtWidgets.QToolButton(inner)
        icons.set_icon(self.custom_btn, "bp_color_custom", "Custom…")
        self.custom_btn.setAutoRaise(True)
        self.custom_btn.setToolTip("Choose any colour (colour wheel, RGB / HSV / HTML #hex, screen picker) – it is "
                                   "kept in the row of custom colours below")
        self.custom_btn.clicked.connect(self._pick_color)
        crow.addWidget(self.custom_btn)
        crow.addStretch(1)
        v.addLayout(crow)
        # custom colours (the last ones chosen, kept between sessions)
        self.custom_row = QtWidgets.QHBoxLayout()
        self.custom_row.setSpacing(theme.px(2))
        self.custom_lbl = QtWidgets.QLabel("Custom", inner)
        self.custom_lbl.setProperty("dim", True)
        self.custom_row.addWidget(self.custom_lbl)
        self.custom_btns = []
        for _n in range(MAX_CUSTOM):
            b = QtWidgets.QToolButton(inner)
            b.setAutoRaise(True)
            b.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            b.clicked.connect(lambda _c=False, n=_n: self._use_custom(n))
            b.customContextMenuRequested.connect(lambda _p, n=_n: self._custom_menu(n))
            self.custom_row.addWidget(b)
            self.custom_btns.append(b)
        self.custom_row.addStretch(1)
        v.addLayout(self.custom_row)
        # tool options
        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(theme.px(3))
        self.size_spin = QtWidgets.QDoubleSpinBox(inner)
        self.size_spin.setRange(1, 200)
        self.size_spin.setDecimals(0)
        self.size_spin.valueChanged.connect(self._size_changed)
        keymap.tip(self.size_spin, "Size of the active tool (px of a frame 800 px high; text: font size, eraser: "
                                   "radius in screen px) – {bp.size_down} / {bp.size_up} or Ctrl + wheel in the view")
        form.addRow("Size", self.size_spin)
        self.opacity = QtWidgets.QSlider(QtCore.Qt.Horizontal, inner)
        self.opacity.setRange(5, 100)
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.opacity.sliderReleased.connect(self._opacity_released)
        self.opacity.setToolTip("Opacity of new strokes (and of the strokes selected with Transform)")
        form.addRow("Opacity", self.opacity)
        self.pressure = QtWidgets.QCheckBox("Tablet pressure (Brush)", inner)
        self.pressure.toggled.connect(lambda on: st.set("pressure", on))
        form.addRow("", self.pressure)
        v.addLayout(form)
        self.sel_label = QtWidgets.QLabel(inner)
        self.sel_label.setWordWrap(True)
        self.sel_label.setStyleSheet("color: #ffbe33;")
        self.sel_label.hide()
        v.addWidget(self.sel_label)

        # ghosting
        head("Ghosting")
        g = QtWidgets.QGridLayout()
        g.setSpacing(theme.px(3))
        self.ghost = {}
        for row, (key, label, tip) in enumerate((("prev", "Previous", "Ghost the frames before the current one"),
                                                 ("next", "Next", "Ghost the frames after the current one"))):
            chk = QtWidgets.QCheckBox(label, inner)
            chk.setToolTip(tip)
            chk.toggled.connect(lambda on, k=key: (st.set(f"ghost_{k}", on), _views_update()))
            cnt = QtWidgets.QSpinBox(inner)
            cnt.setRange(1, 10)
            cnt.setSuffix(" fr")
            cnt.setToolTip("Number of ghosted frames")
            cnt.valueChanged.connect(lambda val, k=key: (st.set(f"ghost_count_{k}", int(val)), _views_update()))
            col = QtWidgets.QToolButton(inner)
            col.setAutoRaise(True)
            col.setToolTip("Ghost colour")
            col.clicked.connect(lambda _c=False, k=key: self._pick_ghost_color(k))
            g.addWidget(chk, row, 0)
            g.addWidget(cnt, row, 1)
            g.addWidget(col, row, 2)
            self.ghost[key] = (chk, cnt, col)
        self.ghost_play = QtWidgets.QCheckBox("During playback", inner)
        self.ghost_play.setToolTip("Ghosting is off during playback unless this is on")
        self.ghost_play.toggled.connect(lambda on: st.set("ghost_playback", on))
        g.addWidget(self.ghost_play, 2, 0, 1, 3)
        v.addLayout(g)

        # frames
        head("Frame")
        fr = QtWidgets.QHBoxLayout()
        fr.setSpacing(theme.px(1))
        for icon, tip, fn, py in (
                ("bp_frame_prev", "Previous Blue Pencil frame ({bp.step_prev})", lambda: step(-1), "step(-1)"),
                ("bp_frame_next", "Next Blue Pencil frame ({bp.step_next})", lambda: step(1), "step(1)"),
                ("bp_frame_insert", "Insert a blank frame at the current time", insert_frame, "insert_frame()"),
                ("bp_frame_dup", "Duplicate the previous frame at the current time", duplicate_frame,
                 "duplicate_frame()"),
                ("bp_frame_delete", "Delete the frame shown", delete_frame, "delete_frame()"),
                ("bp_cut", "Cut the frame shown", lambda: copy_frame(cut=True), "copy_frame(cut=True)"),
                ("bp_copy", "Copy the frame shown", copy_frame, "copy_frame()"),
                ("bp_paste", "Paste the copied frame at the current time", paste_frame, "paste_frame()")):
            b = tbtn(icon, "", fn)
            keymap.tip(b, tip)
            pytips.tag(b, f"qt_shell.bluepencil.{py}")
            fr.addWidget(b)
        fr.addStretch(1)
        v.addLayout(fr)

        # retiming
        head("Retiming")
        rt = QtWidgets.QHBoxLayout()
        rt.setSpacing(theme.px(1))
        for n in range(1, 7):
            b = tbtn(None, f"Exactly {n} frame{'s' if n > 1 else ''} between the current key and the next "
                           "(or between the keys selected in the Timeline)",
                     lambda _c=False, n=n: retime("ABS", n, selected_frames()), text=f"{n}f")
            pytips.tag(b, f'qt_shell.bluepencil.retime("ABS", {n})')
            rt.addWidget(b)
        v.addLayout(rt)
        rt2 = QtWidgets.QHBoxLayout()
        rt2.setSpacing(theme.px(1))
        for n in (-2, -1, 1, 2):
            b = tbtn(None, f"{'Add' if n > 0 else 'Remove'} {abs(n)} frame{'s' if abs(n) > 1 else ''} after the "
                           "current key (after each key selected in the Timeline)",
                     lambda _c=False, n=n: retime("REL", n, selected_frames()), text=f"{n:+d}f")
            pytips.tag(b, f'qt_shell.bluepencil.retime("REL", {n})')
            rt2.addWidget(b)
        self.move_next = QtWidgets.QCheckBox("Move to next key", inner)
        self.move_next.toggled.connect(lambda on: st.set("move_next", on))
        rt2.addWidget(self.move_next)
        rt2.addStretch(1)
        v.addLayout(rt2)

        # layers
        head("Layers")
        self.tree = QtWidgets.QTreeWidget(inner)
        self.tree.setHeaderLabels(["", "", "Layer", "Camera"])
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setMinimumHeight(theme.px(110))
        self.tree.header().setStretchLastSection(True)
        self.tree.setColumnWidth(0, theme.px(26))
        self.tree.setColumnWidth(1, theme.px(24))
        self.tree.setColumnWidth(2, theme.px(110))
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._layer_menu)
        self.tree.itemClicked.connect(self._layer_clicked)
        self.tree.itemChanged.connect(self._layer_renamed)
        self.tree.setToolTip("Top = drawn on top. Click the eye: visibility, the letter: state "
                             "(A animation / S static / L locked); double-click the name: rename; "
                             "right click: camera, properties")
        v.addWidget(self.tree)
        lb = QtWidgets.QHBoxLayout()
        lb.setSpacing(theme.px(1))
        for icon, text, tip, fn in (("bp_layer_new", "", "New layer (for the camera you look through, else the View)",
                                     lambda: new_layer()),
                                    ("trash", "", "Delete the active layer", self._delete_layer),
                                    (None, "▲", "Move the layer up (drawn on top)", lambda: self._move_layer(-1)),
                                    (None, "▼", "Move the layer down", lambda: self._move_layer(1))):
            lb.addWidget(tbtn(icon, tip, fn, text=text or None))
        lb.addWidget(QtWidgets.QLabel("Opacity", inner))
        self.layer_opacity = QtWidgets.QSlider(QtCore.Qt.Horizontal, inner)
        self.layer_opacity.setRange(5, 100)
        self.layer_opacity.setToolTip("Opacity of the active layer")
        self.layer_opacity.sliderReleased.connect(self._set_layer_opacity)
        self.layer_opacity.valueChanged.connect(self._preview_layer_opacity)
        lb.addWidget(self.layer_opacity, 1)
        v.addLayout(lb)

        # display / cleanup
        head("Display")
        dl = QtWidgets.QFormLayout()
        self.tl_combo = QtWidgets.QComboBox(inner)
        for ident, name in (("ACTIVE", "When the tool is active"), ("ALWAYS", "Always"), ("OFF", "Off")):
            self.tl_combo.addItem(name, ident)
        self.tl_combo.setToolTip("Frame ticks of the active layer in the Timeline (they can be dragged; Shift + "
                                 "drag in the Timeline selects them for retiming)")
        self.tl_combo.activated.connect(lambda _i: (st.set("timeline_frames", self.tl_combo.currentData()),
                                                    _views_update()))
        dl.addRow("Timeline frames", self.tl_combo)
        v.addLayout(dl)
        cl = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Clear Layer", inner)
        b.setToolTip("Delete all frames of the active layer")
        b.clicked.connect(self._clear_layer)
        cl.addWidget(b)
        b = QtWidgets.QPushButton("Remove All…", inner)
        b.setToolTip("Remove all Blue Pencil layers and drawings from the scene")
        b.clicked.connect(self._remove_all)
        cl.addWidget(b)
        v.addLayout(cl)
        v.addStretch(1)

        self._syncing = False
        signals.changed.connect(self.sync)
        signals.selection.connect(self.sync)
        st.changed.connect(self.sync)
        tool_state().changed.connect(self.sync)
        for sig in (hub.file_loaded, hub.undo_done, hub.frame_changed):
            sig.connect(lambda *_a: self.sync())
        self.sync()

    # --- actions
    def _toggle_draw(self):
        if tool_active():
            tool_state().set_tool("SELECT")
        else:
            set_tool(current_tool())

    def _pick_color(self):
        st = settings()
        sel = selected_strokes()
        cur = _color(sel[0], 1.0) if sel else QtGui.QColor(st.color)
        dlg = QtWidgets.QColorDialog(cur, self)
        dlg.setWindowTitle("Blue Pencil – Custom Colour")
        dlg.setOption(QtWidgets.QColorDialog.DontUseNativeDialog, True)   # wheel + screen picker
        for n, c in enumerate(custom_colors()[:16]):
            QtWidgets.QColorDialog.setCustomColor(n, QtGui.QColor(c))
        dlg.currentColorChanged.connect(lambda c: self.color_btn.setIcon(_swatch(c.name(), theme.px(22))))
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            self.sync()
            return
        c = dlg.selectedColor()
        if c.isValid():
            add_custom_color(c.name())
            self._set_color(c.name())

    def _use_custom(self, n):
        cols = custom_colors()
        if n < len(cols):
            self._set_color(cols[n])

    def _custom_menu(self, n):
        cols = custom_colors()
        if n >= len(cols):
            return
        m = QtWidgets.QMenu(self)
        m.addAction("Use", lambda: self._set_color(cols[n]))
        m.addAction("Remove from Custom Colours", lambda: (remove_custom_color(cols[n]), self.sync()))
        m.addAction("Clear All Custom Colours", lambda: (set_custom_colors([]), self.sync()))
        m.exec(QtGui.QCursor.pos())

    def _set_color(self, col):
        """Drawing colour – also of the strokes selected with Transform."""
        settings().set("color", col)
        apply_to_selection("color", col)
        self.sync()

    def _size_changed(self, val):
        if self._syncing:
            return
        if selected_strokes():
            apply_to_selection("size", val)
        else:
            settings().set_size(current_tool(), val)
            _views_update()

    def _opacity_changed(self, val):
        if self._syncing:
            return
        settings().set("opacity", val / 100.0)
        if selected_strokes():
            apply_to_selection("opacity", val / 100.0, do_commit=not self.opacity.isSliderDown())

    def _opacity_released(self):
        if selected_strokes():
            apply_to_selection("opacity", self.opacity.value() / 100.0)

    def _pick_ghost_color(self, key):
        st = settings()
        cur = getattr(st, f"ghost_color_{key}")
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(cur), self, "Ghost Colour")
        if c.isValid():
            st.set(f"ghost_color_{key}", c.name())
            _views_update()

    def _layer_clicked(self, item, col):
        i = item.data(0, QtCore.Qt.UserRole)
        d = data()
        if i is None or i >= len(d["layers"]):
            return
        lay = d["layers"][i]
        if col == 0:
            lay["visible"] = not lay.get("visible", True)
            d["active"] = i
            commit("Layer Visibility")
        elif col == 1:
            s = lay.get("state", "ANIMATION")
            lay["state"] = STATES[(STATES.index(s) + 1) % 3] if s in STATES else "ANIMATION"
            d["active"] = i
            commit("Layer State")
        elif i != active_index(d):
            set_active(i)

    def _layer_renamed(self, item, col):
        if self._syncing or col != 2:
            return
        i = item.data(0, QtCore.Qt.UserRole)
        d = data()
        if i is None or i >= len(d["layers"]):
            return
        name = item.text(2).strip()
        if name and name != d["layers"][i]["name"]:
            d["layers"][i]["name"] = name
            commit("Rename Layer")

    def _layer_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        i = item.data(0, QtCore.Qt.UserRole)
        d = data()
        lay = d["layers"][i]
        m = QtWidgets.QMenu(self)
        mv = m.addMenu("Move Layer to")
        cams = [o.name for o in bpy.context.scene.objects if o.type == "CAMERA"]
        for name, label in [("", "View (no camera)")] + [(c, c) for c in cams]:
            a = mv.addAction(label, lambda c=name: self._set_camera(i, c))
            a.setCheckable(True)
            a.setChecked(lay.get("camera", "") == name)
        if lay.get("camera"):
            allm = m.addMenu(f"Move all '{lay['camera']}' layers to")
            for name, label in [("", "View (no camera)")] + [(c, c) for c in cams if c != lay["camera"]]:
                allm.addAction(label, lambda c=name, src=lay["camera"]: self._move_all(src, c))
        sm = m.addMenu("State")
        for s in STATES:
            a = sm.addAction(STATE_TIPS[s], lambda s=s: self._set_state(i, s))
            a.setCheckable(True)
            a.setChecked(lay.get("state") == s)
        m.addAction("Rename", lambda: self.tree.editItem(item, 2))
        m.addAction("Clear Layer", self._clear_layer)
        m.addAction("Delete Layer", self._delete_layer)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _set_camera(self, i, cam):
        d = data()
        d["layers"][i]["camera"] = cam
        d["active"] = i
        commit("Layer Camera")

    def _move_all(self, src, cam):
        d = data()
        for lay in d["layers"]:
            if lay.get("camera", "") == src:
                lay["camera"] = cam
        commit("Layers Camera")

    def _set_state(self, i, s):
        d = data()
        d["layers"][i]["state"] = s
        commit("Layer State")

    def _delete_layer(self):
        d = data()
        i = active_index(d)
        if i < 0:
            return
        del d["layers"][i]
        d["active"] = max(0, min(i, len(d["layers"]) - 1))
        commit("Delete Layer")

    def _move_layer(self, delta):
        d = data()
        i = active_index(d)
        j = i + delta
        if i < 0 or not 0 <= j < len(d["layers"]):
            return
        d["layers"][i], d["layers"][j] = d["layers"][j], d["layers"][i]
        d["active"] = j
        commit("Move Layer")

    def _preview_layer_opacity(self, val):
        if self._syncing:
            return
        lay = active_layer()
        if lay is not None:
            lay["opacity"] = val / 100.0
            _views_update()
            if not self.layer_opacity.isSliderDown():
                commit("Layer Opacity")

    def _set_layer_opacity(self):
        if active_layer() is not None:
            commit("Layer Opacity")

    def _clear_layer(self):
        lay = active_layer()
        if not _editable(lay):
            return
        lay["frames"] = {}
        commit("Clear Layer")

    def _remove_all(self):
        r = QtWidgets.QMessageBox.question(self, "Blue Pencil", "Remove all Blue Pencil layers and drawings "
                                           "from this scene? (Ctrl+Z brings them back)")
        if r != QtWidgets.QMessageBox.Yes:
            return
        d = data()
        d["layers"] = []
        d["active"] = 0
        commit("Remove All")

    # --- refresh
    def showEvent(self, ev):
        super().showEvent(ev)
        self.sync()

    def sync(self):
        if self._syncing or not self.isVisible():
            return
        self._syncing = True
        try:
            st = settings()
            act = tool_active()
            tool = current_tool()
            self.draw_btn.setChecked(act)
            self.show_chk.setChecked(st.show)
            for tid, b in self.tool_btns.items():
                b.setChecked(act and tid == tool)
            sel = selected_strokes() if act else []
            if sel:
                first = sel[0]
                n_txt = sum(1 for x in sel if x.get("k") == "TEXT")
                self.sel_label.setText(f"Colour, size and opacity apply to the {len(sel)} selected stroke"
                                       f"{'s' if len(sel) > 1 else ''}" + (f" ({n_txt} text – size = font size)"
                                                                          if n_txt else "") +
                                       ". Double-click a text to edit it.")
                self.color_btn.setIcon(_swatch(_color(first, 1.0).name(), theme.px(22)))
                self.size_spin.setValue(float(first.get("fs", 24)) if first.get("k") == "TEXT"
                                        else float(first.get("w", 3)))
                self.opacity.setValue(int(round(float(first.get("o", 1.0)) * 100)))
            else:
                self.sel_label.setText("")
                self.color_btn.setIcon(_swatch(st.color, theme.px(22)))
                self.size_spin.setValue(st.size(tool))
                self.opacity.setValue(int(round(st.opacity * 100)))
            self.sel_label.setVisible(bool(sel))
            cols = custom_colors()
            self.custom_lbl.setVisible(bool(cols))
            for n, b in enumerate(self.custom_btns):
                if n < len(cols):
                    b.setIcon(_swatch(cols[n], theme.px(12)))
                    b.setToolTip(f"{cols[n]} – click: use, right click: remove")
                    b.show()
                else:
                    b.hide()
            self.pressure.setChecked(st.pressure)
            for key, (chk, cnt, col) in self.ghost.items():
                chk.setChecked(getattr(st, f"ghost_{key}"))
                cnt.setValue(getattr(st, f"ghost_count_{key}"))
                col.setIcon(_swatch(getattr(st, f"ghost_color_{key}")))
            self.ghost_play.setChecked(st.ghost_playback)
            self.move_next.setChecked(st.move_next)
            self.tl_combo.setCurrentIndex(max(0, self.tl_combo.findData(st.timeline_frames)))
            d = data()
            ai = active_index(d)
            self.tree.clear()
            f = current_frame()
            for i, lay in enumerate(d["layers"]):
                it = QtWidgets.QTreeWidgetItem()
                it.setData(0, QtCore.Qt.UserRole, i)
                it.setIcon(0, icons.icon("eye_on" if lay.get("visible", True) else "eye_off"))
                state = lay.get("state", "ANIMATION")
                it.setText(1, STATE_LETTER.get(state, "A"))
                it.setToolTip(1, STATE_TIPS.get(state, ""))
                k = held_key(lay, f)
                it.setText(2, lay["name"])
                it.setToolTip(2, f"{len(lay['frames'])} frames" + (f" · showing frame {k}" if k is not None else ""))
                it.setText(3, lay.get("camera") or "View")
                it.setFlags(it.flags() | QtCore.Qt.ItemIsEditable)
                self.tree.addTopLevelItem(it)
                if i == ai:
                    f2 = it.font(2)
                    f2.setBold(True)
                    it.setFont(2, f2)
                    self.tree.setCurrentItem(it)
            lay = active_layer(d)
            self.layer_opacity.setEnabled(lay is not None)
            if lay is not None and not self.layer_opacity.isSliderDown():
                self.layer_opacity.setValue(int(round(float(lay.get("opacity", 1.0)) * 100)))
        except RuntimeError:
            pass
        finally:
            self._syncing = False

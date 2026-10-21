"""Graph Editor – animation curves like Maya's Graph Editor.

Left: the animated selected objects and their channels (check box = show the curve, select channels to
show only those). Right: the curves over time, keys, tangents and the current frame.

Mouse (Maya style):
  LMB on a key / tangent        select (Shift toggles, Ctrl deselects) and drag it
  LMB drag on empty space       box select (Shift adds, Ctrl removes)
  MMB drag                      move the selected keys (Shift: only time or only value)
  Alt+MMB drag / MMB on empty   pan          Alt+RMB drag / wheel   zoom (Ctrl: time only, Shift: values only)
  LMB in the frame ruler        change the current frame
  RMB                           menu (tangents, infinity, keys, view)
Keys: F frame selected · A / Home frame all · S / I key the shown curves at the current frame ·
      Delete / Backspace delete the selected keys · Space play.

Selection is stored in Blender's own key flags (select_control_point / select_left_handle /
select_right_handle), so it survives re-sorting of the keys.
"""
import math
import traceback

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, theme
from . import pytips

AXIS_COLORS = ["#ff5a6e", "#7ddc3a", "#4aa3ff", "#f0c446"]          # X Y Z W
OTHER_COLORS = ["#e98bd8", "#5fd3c8", "#f29a52", "#b59cff", "#c8d65c", "#ff8f8f"]
PATH_NAMES = {
    "location": ("Location", "XYZ"), "rotation_euler": ("Rotation", "XYZ"),
    "rotation_quaternion": ("Quaternion Rotation", "WXYZ"), "rotation_axis_angle": ("Axis-Angle", "WXYZ"),
    "scale": ("Scale", "XYZ"), "delta_location": ("Delta Location", "XYZ"),
    "delta_rotation_euler": ("Delta Rotation", "XYZ"), "delta_scale": ("Delta Scale", "XYZ"),
}
RULER = 20          # unscaled px – frame numbers at the top
VALUE_W = 46        # unscaled px – value labels on the left
PICK = 7            # unscaled px


# ---------------------------------------------------------------- data helpers
def fcurves_of(idb):
    """F-curves of an ID's active action (Blender 4.4+ slotted actions, older API as a fallback)."""
    ad = getattr(idb, "animation_data", None)
    act = ad.action if ad else None
    if act is None:
        return []
    try:
        from bpy_extras import anim_utils
        cb = anim_utils.action_get_channelbag_for_slot(act, ad.action_slot)
        return list(cb.fcurves) if cb is not None else []
    except Exception:
        try:
            return list(act.fcurves)
        except Exception:
            return []


def unit_factor(fc):
    """Rotation curves are shown in degrees (like Maya / Blender's UI)."""
    p = fc.data_path
    if p.endswith("rotation_euler") or (p.endswith("rotation_axis_angle") and fc.array_index == 0):
        return 180.0 / math.pi
    return 1.0


def channel_name(fc):
    from .keying import bone_of_path
    bone, path = bone_of_path(fc.data_path)
    base, axes = PATH_NAMES.get(path, (None, None))
    if base:
        i = fc.array_index
        name = f"{axes[i] if i < len(axes) else i} {base}"
        return f"{bone}: {name}" if bone else name
    name = fc.data_path.rsplit(".", 1)[-1].replace("_", " ").title()
    if fc.data_path.endswith("]"):
        name = fc.data_path
    return f"{name} [{fc.array_index}]" if fc.array_index else name


def channel_color(fc, n):
    from .keying import bone_of_path
    if bone_of_path(fc.data_path)[1] in PATH_NAMES:
        return QtGui.QColor(AXIS_COLORS[fc.array_index % 4])
    return QtGui.QColor(OTHER_COLORS[n % len(OTHER_COLORS)])


def nice_step(units_per_px, min_px):
    """1 / 2 / 5 × 10ⁿ so that one step is at least min_px pixels."""
    raw = units_per_px * min_px
    if raw <= 0:
        return 1.0
    e = math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        s = m * 10 ** e
        if s >= raw:
            return s
    return 10 ** (e + 1)


def fmt(v):
    if abs(v) >= 100 or v == int(v):
        return f"{v:.0f}" if v == int(v) else f"{v:.1f}"
    return f"{v:.3f}".rstrip("0").rstrip(".")


class Curve:
    """One F-curve as shown: owner, curve, label, colour, unit factor."""

    def __init__(self, ob, fc, n):
        self.ob = ob
        self.fc = fc
        self.key = (ob.name, fc.data_path, fc.array_index)
        self.label = channel_name(fc)
        self.color = channel_color(fc, n)
        self.fac = unit_factor(fc)


# ---------------------------------------------------------------- graph view
class GraphView(QtWidgets.QWidget):
    edited = QtCore.Signal()          # keys changed by the user (stats / undo)

    def __init__(self, editor, parent=None):
        super().__init__(parent or editor)
        self.ed = editor
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(theme.px(120), theme.px(80))
        self.f0, self.v0 = -5.0, -2.0         # frame at x = 0, value at the bottom
        self.sx, self.sy = 8.0, 40.0          # px per frame, px per value unit
        self._drag = None
        self._hover = None
        self.snap_time = True
        self.frame_pending = True
        self._auto_view = True        # the view was framed automatically and not panned/zoomed since

    # --- coordinates
    def fx(self, f):
        return (f - self.f0) * self.sx

    def fy(self, v):
        return self.height() - (v - self.v0) * self.sy

    def xf(self, x):
        return self.f0 + x / self.sx

    def yv(self, y):
        return self.v0 + (self.height() - y) / self.sy

    def pt(self, c, co):
        return QtCore.QPointF(self.fx(co[0]), self.fy(co[1] * c.fac))

    # --- framing
    def _big_enough(self):
        return self.isVisible() and self.width() > theme.px(80) and self.height() > theme.px(60)

    def frame(self, selected_only=False, auto=False):
        self._auto_view = auto
        if not self._big_enough():
            self.frame_pending = True
            return
        self.frame_pending = False
        fs, vs = [], []
        for c in self.ed.shown():
            for kp in c.fc.keyframe_points:
                if selected_only and not (kp.select_control_point or kp.select_left_handle
                                          or kp.select_right_handle):
                    continue
                fs.append(kp.co[0])
                vs.append(kp.co[1] * c.fac)
                if not selected_only or kp.select_control_point:
                    for h in (kp.handle_left, kp.handle_right):
                        vs.append(h[1] * c.fac)
        if not fs:
            if selected_only:
                return self.frame(False, auto)
            sc = bpy.context.scene
            fs, vs = [sc.frame_start, sc.frame_end], [-1.0, 1.0]
        f_lo, f_hi = min(fs), max(fs)
        v_lo, v_hi = min(vs), max(vs)
        if f_hi - f_lo < 2:
            f_lo, f_hi = f_lo - 5, f_hi + 5
        if v_hi - v_lo < 1e-6:
            v_lo, v_hi = v_lo - 1, v_hi + 1
        w = max(self.width() - theme.px(VALUE_W) - theme.px(34), 10)
        h = max(self.height() - theme.px(RULER) - theme.px(24), 10)
        self.sx = w / (f_hi - f_lo)
        self.sy = h / (v_hi - v_lo)
        self.f0 = f_lo - (theme.px(VALUE_W) + theme.px(10)) / self.sx
        self.v0 = v_lo - theme.px(12) / self.sy
        self.update()

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.frame_pending or self._auto_view:
            QtCore.QTimer.singleShot(60, lambda: self.frame(auto=True))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # the dock gets its final size only after it is shown – re-frame until the user moves the view
        if (self.frame_pending or self._auto_view) and self._big_enough():
            QtCore.QTimer.singleShot(0, lambda: self.frame(auto=True))

    # --- painting
    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        try:
            self._paint(p)
        except Exception:
            bridge.log("Graph editor paint:\n" + traceback.format_exc(), "ERROR")
        finally:
            p.end()

    def _paint(self, p):
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), QtGui.QColor("#2b2b2b"))
        sc = bpy.context.scene
        # playback range
        x0, x1 = self.fx(sc.frame_start), self.fx(sc.frame_end)
        p.fillRect(QtCore.QRectF(x0, 0, x1 - x0, H), QtGui.QColor("#303030"))
        f = p.font()
        f.setPixelSize(theme.fs(10))
        p.setFont(f)
        # grid
        fstep = max(1.0, nice_step(1.0 / self.sx, theme.px(55)))
        vstep = nice_step(1.0 / self.sy, theme.px(36))
        grid = QtGui.QColor("#363636")
        fr = math.floor(self.xf(0) / fstep) * fstep
        while self.fx(fr) < W:
            x = self.fx(fr)
            p.setPen(QtGui.QColor("#474747") if fr == 0 else grid)
            p.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, H))
            fr += fstep
        v = math.floor(self.yv(H) / vstep) * vstep
        while self.fy(v) > 0:
            y = self.fy(v)
            p.setPen(QtGui.QColor("#4d4d4d") if abs(v) < vstep * 1e-6 else grid)
            p.drawLine(QtCore.QPointF(0, y), QtCore.QPointF(W, y))
            v += vstep
        # curves
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        shown = self.ed.shown()
        for c in shown:
            self._paint_curve(p, c)
        # value labels (left) and frame ruler (top)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        p.fillRect(QtCore.QRectF(0, 0, theme.px(VALUE_W), H), QtGui.QColor(36, 36, 36, 200))
        p.setPen(QtGui.QColor("#9a9a9a"))
        v = math.floor(self.yv(H) / vstep) * vstep
        while self.fy(v) > theme.px(RULER):
            p.drawText(QtCore.QPointF(theme.px(4), self.fy(v) - 2), fmt(round(v, 6)))
            v += vstep
        p.fillRect(QtCore.QRectF(0, 0, W, theme.px(RULER)), QtGui.QColor("#232323"))
        fr = math.floor(self.xf(0) / fstep) * fstep
        while self.fx(fr) < W:
            x = self.fx(fr)
            p.setPen(QtGui.QColor("#9a9a9a"))
            p.drawText(QtCore.QPointF(x + 2, theme.px(13)), fmt(fr))
            fr += fstep
        # current frame
        cur = sc.frame_current
        x = self.fx(cur)
        p.setPen(QtGui.QPen(QtGui.QColor("#e04a4a"), 2))
        p.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, H))
        lab = str(cur)
        fm = QtGui.QFontMetrics(p.font())
        r = QtCore.QRectF(x - fm.horizontalAdvance(lab) / 2 - 4, 1, fm.horizontalAdvance(lab) + 8, theme.px(RULER) - 2)
        p.fillRect(r, QtGui.QColor("#e04a4a"))
        p.setPen(QtGui.QColor("#ffffff"))
        p.drawText(r, QtCore.Qt.AlignCenter, lab)
        # box selection
        if self._drag and self._drag["mode"] == "box":
            rect = QtCore.QRectF(self._drag["start"], self._drag["cur"]).normalized()
            p.setPen(QtGui.QPen(QtGui.QColor("#dddddd"), 1, QtCore.Qt.DashLine))
            p.setBrush(QtGui.QColor(255, 255, 255, 20))
            p.drawRect(rect)
        if not shown:
            p.setPen(QtGui.QColor("#8a8a8a"))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter,
                       "No animation curves.\nSelect an animated object, or key one: S in this editor, "
                       "\"+◆ Key\" in the Timeline, or I in the 3D view.")

    def _paint_curve(self, p, c):
        fc = c.fc
        W = self.width()
        col = QtGui.QColor(c.color)
        selected_curve = any(kp.select_control_point for kp in fc.keyframe_points)
        if not selected_curve:
            col = col.darker(125)
        path = QtGui.QPainterPath()
        step = 2
        first = True
        x = 0
        while x <= W + step:
            fr = self.xf(x)
            try:
                y = self.fy(fc.evaluate(fr) * c.fac)
            except Exception:
                return
            y = max(-1e5, min(1e5, y))
            if first:
                path.moveTo(x, y)
                first = False
            else:
                path.lineTo(x, y)
            x += step
        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(col, theme.px(1.6) if selected_curve else theme.px(1.2)))
        p.drawPath(path)
        # keys + tangents of selected keys
        r = theme.px(3.2)
        kps = fc.keyframe_points
        for i, kp in enumerate(kps):
            pc = self.pt(c, kp.co)
            if -20 < pc.x() < W + 20 and kp.select_control_point:
                prev_interp = kps[i - 1].interpolation if i > 0 else "BEZIER"
                for side, h, sel, show in (("L", kp.handle_left, kp.select_left_handle, prev_interp == "BEZIER" and i > 0),
                                           ("R", kp.handle_right, kp.select_right_handle,
                                            kp.interpolation == "BEZIER" and i < len(kps) - 1)):
                    if not show:
                        continue
                    ph = self.pt(c, h)
                    p.setPen(QtGui.QPen(QtGui.QColor("#d8b84a"), 1))
                    p.drawLine(pc, ph)
                    p.setPen(QtGui.QPen(QtGui.QColor("#111111"), 1))
                    p.setBrush(QtGui.QColor("#ffe066") if sel else QtGui.QColor("#9b8a50"))
                    p.drawEllipse(ph, r * 0.9, r * 0.9)
        for kp in kps:
            pc = self.pt(c, kp.co)
            if not (-20 < pc.x() < W + 20):
                continue
            p.setPen(QtGui.QPen(QtGui.QColor("#111111"), 1))
            p.setBrush(QtGui.QColor("#ffe066") if kp.select_control_point else QtGui.QColor("#e6e6e6"))
            if self._hover == (c.key, round(kp.co[0], 4), "K"):
                p.setBrush(QtGui.QColor("#9fd3ff"))
            p.drawRect(QtCore.QRectF(pc.x() - r, pc.y() - r, 2 * r, 2 * r))

    # --- hit testing
    def hit(self, pos):
        """(curve, keyframe point, 'K' | 'L' | 'R') under the mouse, or None."""
        best, best_d = None, theme.px(PICK)
        for c in self.ed.shown():
            kps = c.fc.keyframe_points
            for i, kp in enumerate(kps):
                cands = [("K", kp.co)]
                if kp.select_control_point:
                    if i > 0 and kps[i - 1].interpolation == "BEZIER":
                        cands.append(("L", kp.handle_left))
                    if i < len(kps) - 1 and kp.interpolation == "BEZIER":
                        cands.append(("R", kp.handle_right))
                for part, co in cands:
                    d = (self.pt(c, co) - pos).manhattanLength()
                    if d < best_d or (d <= best_d and part != "K" and best and best[2] == "K"):
                        best, best_d = (c, kp, part), d
        return best

    # --- selection helpers
    @staticmethod
    def _set_sel(kp, part, on):
        if part == "K":
            kp.select_control_point = on
        elif part == "L":
            kp.select_left_handle = on
        else:
            kp.select_right_handle = on

    @staticmethod
    def _is_sel(kp, part):
        return {"K": kp.select_control_point, "L": kp.select_left_handle, "R": kp.select_right_handle}[part]

    def deselect_all(self):
        for c in self.ed.all_curves():
            for kp in c.fc.keyframe_points:
                kp.select_control_point = kp.select_left_handle = kp.select_right_handle = False

    def selected(self):
        """[(curve, kp)] with a selected control point among the shown curves."""
        return [(c, kp) for c in self.ed.shown() for kp in c.fc.keyframe_points if kp.select_control_point]

    # --- mouse
    def mousePressEvent(self, ev):
        self.setFocus()
        pos = ev.position()
        alt = ev.modifiers() & QtCore.Qt.AltModifier
        shift = ev.modifiers() & QtCore.Qt.ShiftModifier
        ctrl = ev.modifiers() & QtCore.Qt.ControlModifier
        btn = ev.button()
        if btn == QtCore.Qt.LeftButton and pos.y() < theme.px(RULER) and not alt:
            self._drag = {"mode": "scrub"}
            self._scrub(pos.x())
            return
        if btn == QtCore.Qt.MiddleButton and (alt or not self.selected()):
            self._auto_view = False
            self._drag = {"mode": "pan", "start": pos, "f0": self.f0, "v0": self.v0}
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            return
        if btn == QtCore.Qt.RightButton and alt:
            self._auto_view = False
            self._drag = {"mode": "zoom", "start": pos, "sx": self.sx, "sy": self.sy,
                          "anchor": (self.xf(pos.x()), self.yv(pos.y()))}
            return
        if btn == QtCore.Qt.MiddleButton:
            self._begin_move(pos)
            return
        if btn == QtCore.Qt.LeftButton:
            h = self.hit(pos)
            if h is not None:
                c, kp, part = h
                if shift:
                    self._set_sel(kp, part, not self._is_sel(kp, part))
                elif ctrl:
                    self._set_sel(kp, part, False)
                elif not self._is_sel(kp, part):
                    self.deselect_all()
                    self._set_sel(kp, part, True)
                self.update()
                self.edited.emit()
                if self._is_sel(kp, part) and not (shift or ctrl):
                    if part == "K":
                        self._begin_move(pos)
                    else:
                        self._begin_handle(pos, c, kp, part)
                return
            self._drag = {"mode": "box", "start": pos, "cur": pos,
                          "op": "add" if shift else ("sub" if ctrl else "set")}
            return

    def contextMenuEvent(self, ev):
        if ev.modifiers() & QtCore.Qt.AltModifier:
            return
        self.ed.context_menu(ev.globalPos())

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        d = self._drag
        if d is None:
            h = self.hit(pos)
            hk = (h[0].key, round(h[1].co[0], 4), h[2]) if h else None
            if hk != self._hover:
                self._hover = hk
                self.setCursor(QtCore.Qt.PointingHandCursor if h else QtCore.Qt.ArrowCursor)
                self.update()
            return
        m = d["mode"]
        if m == "scrub":
            self._scrub(pos.x())
        elif m == "pan":
            delta = pos - d["start"]
            self.f0 = d["f0"] - delta.x() / self.sx
            self.v0 = d["v0"] + delta.y() / self.sy
            self.update()
        elif m == "zoom":
            delta = pos - d["start"]
            self.sx = min(2000.0, max(0.02, d["sx"] * math.exp(delta.x() * 0.01)))
            self.sy = min(1e6, max(1e-4, d["sy"] * math.exp(-delta.y() * 0.01)))
            fa, va = d["anchor"]
            self.f0 = fa - d["start"].x() / self.sx
            self.v0 = va - (self.height() - d["start"].y()) / self.sy
            self.update()
        elif m == "box":
            d["cur"] = pos
            self.update()
        elif m == "move":
            self._do_move(pos, ev.modifiers() & QtCore.Qt.ShiftModifier)
        elif m == "handle":
            self._do_handle(pos)

    def mouseReleaseEvent(self, ev):
        d = self._drag
        self._drag = None
        self.unsetCursor()
        if d is None:
            return
        m = d["mode"]
        if m == "box":
            self._box_select(QtCore.QRectF(d["start"], d["cur"]).normalized(), d["op"])
        elif m in ("move", "handle"):
            if d.get("moved"):
                self._finish_edit("Move Keys" if m == "move" else "Move Tangent")
        self.update()

    def wheelEvent(self, ev):
        steps = ev.angleDelta().y() / 120.0
        if not steps:
            return
        k = 1.15 ** steps
        self._auto_view = False
        pos = ev.position()
        fa, va = self.xf(pos.x()), self.yv(pos.y())
        mods = ev.modifiers()
        if not mods & QtCore.Qt.ShiftModifier:
            self.sx = min(2000.0, max(0.02, self.sx * k))
        if not mods & QtCore.Qt.ControlModifier:
            self.sy = min(1e6, max(1e-4, self.sy * k))
        self.f0 = fa - pos.x() / self.sx
        self.v0 = va - (self.height() - pos.y()) / self.sy
        self.update()

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == QtCore.Qt.Key_F:
            self.frame(selected_only=True)
        elif k in (QtCore.Qt.Key_A, QtCore.Qt.Key_Home):
            self.frame(False)
        elif k in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            self.ed.delete_keys()
        elif k in (QtCore.Qt.Key_S, QtCore.Qt.Key_I):
            self.ed.insert_keys()
        else:
            super().keyPressEvent(ev)

    def _scrub(self, x):
        sc = bpy.context.scene
        f = int(round(self.xf(x)))
        if f != sc.frame_current:
            sc.frame_set(f)
        self.update()

    # --- editing
    def _begin_move(self, pos):
        items = [(c, kp, tuple(kp.co), tuple(kp.handle_left), tuple(kp.handle_right))
                 for c, kp in self.selected()]
        if items:
            self._drag = {"mode": "move", "start": pos, "items": items, "moved": False}

    def _do_move(self, pos, constrain):
        d = self._drag
        delta = pos - d["start"]
        if not d["moved"] and delta.manhattanLength() < theme.px(3):
            return
        d["moved"] = True
        df = delta.x() / self.sx
        dv = -delta.y() / self.sy
        if constrain:
            if "lock" not in d:
                d["lock"] = "time" if abs(delta.x()) >= abs(delta.y()) else "value"
            if d["lock"] == "time":
                dv = 0.0
            else:
                df = 0.0
        if self.snap_time:
            df = round(df)
        touched = set()
        for c, kp, co, hl, hr in d["items"]:
            dvr = dv / c.fac
            kp.co = (co[0] + df, co[1] + dvr)
            kp.handle_left = (hl[0] + df, hl[1] + dvr)
            kp.handle_right = (hr[0] + df, hr[1] + dvr)
            touched.add(c.fc)
        self._live_update(touched)

    def _begin_handle(self, pos, c, kp, part):
        if kp.handle_left_type in ("AUTO", "AUTO_CLAMPED", "VECTOR"):
            kp.handle_left_type = "ALIGNED"
        if kp.handle_right_type in ("AUTO", "AUTO_CLAMPED", "VECTOR"):
            kp.handle_right_type = "ALIGNED"
        self._drag = {"mode": "handle", "c": c, "kp": kp, "part": part, "moved": False}

    def _do_handle(self, pos):
        d = self._drag
        c, kp, part = d["c"], d["kp"], d["part"]
        d["moved"] = True
        f = self.xf(pos.x())
        v = self.yv(pos.y()) / c.fac
        co = kp.co
        # a tangent never crosses its key in time
        f = min(f, co[0] - 1e-3) if part == "L" else max(f, co[0] + 1e-3)
        if part == "L":
            kp.handle_left = (f, v)
            other, other_type = kp.handle_right, kp.handle_right_type
        else:
            kp.handle_right = (f, v)
            other, other_type = kp.handle_left, kp.handle_left_type
        own_type = kp.handle_left_type if part == "L" else kp.handle_right_type
        if own_type == "ALIGNED" and other_type == "ALIGNED":
            # keep the other tangent's length, opposite direction (in screen space, like Maya)
            a = self.pt(c, co)
            h = self.pt(c, (f, v))
            o = self.pt(c, other)
            length = math.hypot(o.x() - a.x(), o.y() - a.y())
            vx, vy = a.x() - h.x(), a.y() - h.y()
            n = math.hypot(vx, vy) or 1.0
            nx, ny = a.x() + vx / n * length, a.y() + vy / n * length
            new = (self.xf(nx), self.yv(ny) / c.fac)
            if part == "L":
                kp.handle_right = new
            else:
                kp.handle_left = new
        self._live_update({c.fc})

    def _live_update(self, fcs):
        for fc in fcs:
            try:
                fc.keyframe_points.handles_recalc()
            except Exception:
                pass
        self._reevaluate()
        self.update()

    @staticmethod
    def _reevaluate():
        sc = bpy.context.scene
        try:
            sc.frame_set(sc.frame_current)
        except Exception:
            pass

    def _finish_edit(self, message):
        for c in self.ed.all_curves():
            try:
                c.fc.update()                   # sort the keys + recalculate auto tangents
            except Exception:
                pass
        self._reevaluate()
        bridge.undo_push(message)
        self.edited.emit()

    def _box_select(self, rect, op):
        if op == "set":
            self.deselect_all()
        on = op != "sub"
        for c in self.ed.shown():
            for kp in c.fc.keyframe_points:
                if rect.contains(self.pt(c, kp.co)):
                    kp.select_control_point = on
                    if not on:
                        kp.select_left_handle = kp.select_right_handle = False
        self.edited.emit()


# ---------------------------------------------------------------- editor (channels + graph + tools)
class GraphEditor(QtWidgets.QWidget):
    TANGENTS = [
        ("Auto", "AUTO", "Smooth tangents, recalculated when keys move (Blender Auto)"),
        ("Spline", "AUTO_CLAMPED", "Smooth tangents that never overshoot (Blender Auto Clamped)"),
        ("Linear", "LINEAR", "Straight lines between keys"),
        ("Flat", "FLAT", "Horizontal tangents"),
        ("Stepped", "CONSTANT", "Hold the value until the next key"),
    ]
    # Python tooltips: commands that work from a script / the Console (they drive this Qt editor;
    # Blender's own bpy.ops.graph.* operators need a Blender Graph Editor area and fail from a script)
    PY = "import qt_shell; qt_shell.api.graph_editor()"
    TANGENT_PY = {
        'AUTO': "import qt_shell; qt_shell.api.graph_editor().set_tangents('AUTO')",
        'AUTO_CLAMPED': "import qt_shell; qt_shell.api.graph_editor().set_tangents('AUTO_CLAMPED')",
        'LINEAR': "import qt_shell; qt_shell.api.graph_editor().set_tangents('LINEAR')",
        'FLAT': "import qt_shell; qt_shell.api.graph_editor().set_tangents('FLAT')",
        'CONSTANT': "import qt_shell; qt_shell.api.graph_editor().set_tangents('CONSTANT')",
    }
    INFINITY_PY = {
        'CONSTANT': "import qt_shell; qt_shell.api.graph_editor().set_infinity('CONSTANT')",
        'LINEAR': "import qt_shell; qt_shell.api.graph_editor().set_infinity('LINEAR')",
        'REPEAT': "import qt_shell; qt_shell.api.graph_editor().set_infinity('REPEAT')",
        'REPEAT_OFFSET': "import qt_shell; qt_shell.api.graph_editor().set_infinity('REPEAT_OFFSET')",
        'MIRROR': "import qt_shell; qt_shell.api.graph_editor().set_infinity('MIRROR')",
    }
    INFINITY = [("Constant", "CONSTANT"), ("Linear", "LINEAR"), ("Cycle", "REPEAT"),
                ("Cycle with Offset", "REPEAT_OFFSET"), ("Oscillate", "MIRROR")]

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self._curves = []
        self._sig = None
        self._building = False
        self.setStyleSheet(theme.hover_qss() + theme.field_hover_qss())
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # --- tool row (in a scroll area so it never forces the window wider)
        bar_area = QtWidgets.QScrollArea(self)
        bar_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        bar_area.setWidgetResizable(True)
        bar_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        bar_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        bar = QtWidgets.QWidget(bar_area)
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(theme.px(4), theme.px(2), theme.px(4), theme.px(2))
        row.setSpacing(theme.px(3))

        def btn(text, tip, fn, checkable=False, py=None):
            b = QtWidgets.QToolButton(bar)
            b.setText(text)
            b.setToolTip(tip)
            pytips.tag(b, py)
            b.setCheckable(checkable)
            b.clicked.connect(fn)
            row.addWidget(b)
            return b

        def sep():
            f = QtWidgets.QFrame(bar)
            f.setFrameShape(QtWidgets.QFrame.VLine)
            f.setStyleSheet("color: #454545;")
            row.addWidget(f)

        btn("⤢ All", "Frame all curves (A)", lambda: self.view.frame(False), py=f"{self.PY}.frame_all()")
        btn("⤢ Sel", "Frame the selected keys (F)", lambda: self.view.frame(True), py=f"{self.PY}.frame_selected()")
        sep()
        for label, kind, tip in self.TANGENTS:
            btn(label, f"{label} tangents – {tip}", lambda _c=False, k=kind: self.set_tangents(k),
                py=self.TANGENT_PY[kind])
        btn("Break", "Break tangents – move the in and out tangent separately", lambda: self.set_handle_type("FREE"),
            py=f"{self.PY}.set_handle_type('FREE')")
        btn("Unify", "Unify tangents – in and out tangent stay in line", lambda: self.set_handle_type("ALIGNED"),
            py=f"{self.PY}.set_handle_type('ALIGNED')")
        sep()
        inf = QtWidgets.QToolButton(bar)
        inf.setText("Infinity")
        inf.setToolTip("What the curves do before the first and after the last key")
        inf.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        inf_menu = QtWidgets.QMenu(inf)
        for label, mode in self.INFINITY:
            a = inf_menu.addAction(label, lambda m=mode: self.set_infinity(m))
            pytips.tag(a, self.INFINITY_PY[mode])
        inf.setMenu(inf_menu)
        row.addWidget(inf)
        sep()
        btn("+◆", "Key the shown curves at the current frame (S)", self.insert_keys,
            py=f"{self.PY}.insert_keys()")
        btn("−◆", "Delete the selected keys (Delete)", self.delete_keys, py=f"{self.PY}.delete_keys()")
        self.snap_btn = btn("⌗ Snap", "Snap key times to whole frames while moving", self._toggle_snap, True,
                            py=f"{self.PY}.set_snap(True)")
        self.snap_btn.setChecked(True)
        sep()
        row.addWidget(QtWidgets.QLabel("Frame", bar))
        self.stat_frame = QtWidgets.QLineEdit(bar)
        self.stat_value = QtWidgets.QLineEdit(bar)
        for e in (self.stat_frame, self.stat_value):
            e.setFixedWidth(theme.px(70))
            e.setPlaceholderText("–")
            e.setValidator(QtGui.QDoubleValidator(e))
        self.stat_frame.setToolTip("Time of the selected keys")
        self.stat_value.setToolTip("Value of the selected keys (rotation in degrees)")
        self.stat_frame.editingFinished.connect(lambda: self._apply_stat(0))
        self.stat_value.editingFinished.connect(lambda: self._apply_stat(1))
        row.addWidget(self.stat_frame)
        row.addWidget(QtWidgets.QLabel("Value", bar))
        row.addWidget(self.stat_value)
        row.addStretch(1)
        bar_area.setWidget(bar)
        bar_area.setFixedHeight(bar.sizeHint().height() + theme.px(10))
        lay.addWidget(bar_area)

        # --- channels | graph
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        self.tree = QtWidgets.QTreeWidget(split)
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setToolTip("Animated channels of the selected objects.\n"
                             "Select channels to show only their curves · check box shows / hides a curve")
        self.tree.itemSelectionChanged.connect(self._tree_selection)
        self.tree.itemChanged.connect(self._tree_changed)
        self.view = GraphView(self, split)
        self.view.edited.connect(self.update_stats)
        split.addWidget(self.tree)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        split.setSizes([theme.px(170), theme.px(600)])
        lay.addWidget(split, 1)

        hub.frame_changed.connect(lambda _f: self.view.update())
        hub.selection_changed.connect(self.refresh)
        hub.data_changed.connect(self.refresh)
        hub.file_loaded.connect(lambda: self.refresh(force=True))
        self.refresh(force=True)

    # --- channels
    def all_curves(self):
        return self._curves

    def shown(self):
        out = []
        sel = self.tree.selectedItems()
        keys = None
        if sel:
            keys = set()
            for it in sel:
                d = it.data(0, QtCore.Qt.UserRole)
                if isinstance(d, str):                       # object row → all its curves
                    keys.update(c.key for c in self._curves if c.ob.name == d)
                elif d is not None:
                    keys.add(tuple(d))
        for c in self._curves:
            try:
                if c.fc.hide:
                    continue
            except ReferenceError:
                continue
            if keys is None or c.key in keys:
                out.append(c)
        return out

    def _collect(self):
        curves = []
        try:
            obs = list(bpy.context.selected_objects)
            act = bpy.context.view_layer.objects.active
            if act is not None and act not in obs:
                obs.insert(0, act)
        except Exception:
            obs = []
        from . import keying
        for ob in obs:
            # Pose mode: only the curves of the selected bones (rig controls), like Blender / Maya
            names = keying.selected_bone_names(ob) if ob.type == "ARMATURE" else None
            n = 0
            for fc in fcurves_of(ob):
                if not keying.fcurve_visible(ob, fc, names):
                    continue
                curves.append(Curve(ob, fc, n))
                n += 1
        return curves

    def refresh(self, force=False):
        try:
            curves = self._collect()
            sig = tuple((c.key, len(c.fc.keyframe_points)) for c in curves)
            names_changed = self._sig is None or [k for k, _n in sig] != [k for k, _n in self._sig]
            self._curves = curves
            if force or names_changed:
                self._rebuild_tree()
                if names_changed:
                    self.view.frame_pending = True
                    if self.view.isVisible():
                        QtCore.QTimer.singleShot(0, lambda: self.view.frame(auto=True))
            self._sig = sig
            self.update_stats()
            self.view.update()
        except Exception:
            bridge.log("Graph editor:\n" + traceback.format_exc(), "ERROR")

    def _rebuild_tree(self):
        sel = set()
        for it in self.tree.selectedItems():
            d = it.data(0, QtCore.Qt.UserRole)
            sel.add(d if isinstance(d, str) else tuple(d))
        self._building = True
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            bold = self.tree.font()
            bold.setBold(True)
            parents = {}
            for c in self._curves:
                top = parents.get(c.ob.name)
                if top is None:
                    top = QtWidgets.QTreeWidgetItem(self.tree, [c.ob.name])
                    top.setData(0, QtCore.Qt.UserRole, c.ob.name)
                    top.setFont(0, bold)
                    top.setExpanded(True)
                    parents[c.ob.name] = top
                    if c.ob.name in sel:
                        top.setSelected(True)
                it = QtWidgets.QTreeWidgetItem(top, [c.label])
                it.setData(0, QtCore.Qt.UserRole, list(c.key))
                it.setForeground(0, QtGui.QBrush(c.color))
                it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(0, QtCore.Qt.Unchecked if c.fc.hide else QtCore.Qt.Checked)
                if c.key in sel:
                    it.setSelected(True)
        finally:
            self.tree.blockSignals(False)
            self._building = False

    def _tree_selection(self):
        self.view.update()
        self.update_stats()

    def _tree_changed(self, it, _col):
        if self._building:
            return
        d = it.data(0, QtCore.Qt.UserRole)
        if isinstance(d, str) or d is None:
            return
        for c in self._curves:
            if c.key == tuple(d):
                c.fc.hide = it.checkState(0) != QtCore.Qt.Checked
        self.view.update()

    # --- stats (Maya's Frame / Value boxes)
    def update_stats(self):
        sel = self.view.selected()
        for e, vals in ((self.stat_frame, [kp.co[0] for _c, kp in sel]),
                        (self.stat_value, [kp.co[1] * c.fac for c, kp in sel])):
            if e.hasFocus():
                continue
            if vals and max(vals) - min(vals) < 1e-6:
                e.setText(fmt(round(vals[0], 4)))
            else:
                e.setText("")
            e.setEnabled(bool(vals))

    def _apply_stat(self, axis):
        e = self.stat_frame if axis == 0 else self.stat_value
        try:
            val = float(e.text().replace(",", "."))
        except ValueError:
            return
        sel = self.view.selected()
        if not sel:
            return
        for c, kp in sel:
            co = tuple(kp.co)
            new = val if axis == 0 else val / c.fac
            d = new - co[axis]
            if abs(d) < 1e-9:
                continue
            for attr in ("co", "handle_left", "handle_right"):
                v = list(getattr(kp, attr))
                v[axis] += d
                setattr(kp, attr, v)
        self.view._finish_edit("Set Key " + ("Frame" if axis == 0 else "Value"))
        self.view.update()

    # --- operations
    def _sel_or_shown_keys(self):
        """Selected keys; when none is selected, all keys of the shown curves (like Maya on a curve)."""
        sel = self.view.selected()
        if sel:
            return sel
        return [(c, kp) for c in self.shown() for kp in c.fc.keyframe_points]

    def set_tangents(self, kind):
        items = self._sel_or_shown_keys()
        if not items:
            return
        for c, kp in items:
            if kind == "CONSTANT":
                kp.interpolation = "CONSTANT"
            elif kind == "LINEAR":
                kp.interpolation = "LINEAR"
                kp.handle_left_type = kp.handle_right_type = "VECTOR"
            else:
                kp.interpolation = "BEZIER"
                if kind == "FLAT":
                    kp.handle_left_type = kp.handle_right_type = "ALIGNED"
                    co = kp.co
                    kp.handle_left = (kp.handle_left[0], co[1])
                    kp.handle_right = (kp.handle_right[0], co[1])
                else:
                    kp.handle_left_type = kp.handle_right_type = kind
        self.view._finish_edit("Tangents")
        if kind == "FLAT":       # update() recalculated nothing for aligned handles – make sure they stay flat
            for c, kp in items:
                kp.handle_left = (kp.handle_left[0], kp.co[1])
                kp.handle_right = (kp.handle_right[0], kp.co[1])
            self.view._reevaluate()
        self.view.update()
        bridge.log(f"Graph editor: {len(items)} key(s) → {kind.title().replace('_', ' ')} tangents", "INFO")

    def set_handle_type(self, kind):
        items = self._sel_or_shown_keys()
        for c, kp in items:
            kp.handle_left_type = kp.handle_right_type = kind
        if items:
            self.view._finish_edit("Break Tangents" if kind == "FREE" else "Unify Tangents")
            self.view.update()

    def set_infinity(self, mode):
        fcs = {c.fc for c, _kp in self.view.selected()} or {c.fc for c in self.shown()}
        for fc in fcs:
            for m in [m for m in fc.modifiers if m.type == "CYCLES"]:
                fc.modifiers.remove(m)
            if mode in ("CONSTANT", "LINEAR"):
                fc.extrapolation = mode
            else:
                fc.extrapolation = "CONSTANT"
                m = fc.modifiers.new("CYCLES")
                m.mode_before = m.mode_after = mode
        if fcs:
            self.view._finish_edit("Curve Infinity")
            self.view.update()

    def insert_keys(self):
        sc = bpy.context.scene
        f = sc.frame_current
        from . import keying
        curves = self.shown()
        if curves:
            for c in curves:
                try:
                    # the current (posed) value – the curve's own value would keep the key where it was
                    c.fc.keyframe_points.insert(f, keying.current_value(c.ob, c.fc))
                    c.fc.update()
                except Exception as ex:
                    bridge.log(f"Insert key: {ex}", "WARNING")
            for ob in {c.ob for c in curves}:
                ob.update_tag()
        else:
            keying.insert()
        self.view._finish_edit("Insert Keyframe")
        self.refresh()

    def delete_keys(self):
        sel = self.view.selected()
        if not sel:
            return
        by_fc = {}
        for c, kp in sel:
            by_fc.setdefault(c, []).append(kp)
        for c in by_fc:
            fc = c.fc
            # remove from the end so the indices of the remaining keys stay valid
            idx = [i for i, kp in enumerate(fc.keyframe_points) if kp.select_control_point]
            for i in reversed(idx):
                fc.keyframe_points.remove(fc.keyframe_points[i], fast=True)
            try:
                fc.update()
            except Exception:
                pass
        # curves without keys are removed, like in Blender
        for c in by_fc:
            if len(c.fc.keyframe_points) == 0:
                try:
                    ad = c.ob.animation_data
                    from bpy_extras import anim_utils
                    cb = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
                    cb.fcurves.remove(c.fc)
                except Exception:
                    try:
                        c.ob.animation_data.action.fcurves.remove(c.fc)
                    except Exception:
                        pass
        self.view._finish_edit("Delete Keyframes")
        self.refresh(force=True)

    def _toggle_snap(self, on):
        self.view.snap_time = bool(on)

    # --- scripting (qt_shell.api.graph_editor())
    def set_snap(self, on=True):
        """Snap key times to whole frames while moving keys (the ⌗ Snap button)."""
        self.snap_btn.setChecked(bool(on))
        self.view.snap_time = bool(on)

    def frame_all(self):
        self.view.frame(False)

    def frame_selected(self):
        self.view.frame(True)

    # --- RMB menu
    def context_menu(self, gpos):
        m = QtWidgets.QMenu(self)
        tm = m.addMenu("Tangents")
        for label, kind, _tip in self.TANGENTS:
            tm.addAction(label, lambda k=kind: self.set_tangents(k))
        tm.addSeparator()
        tm.addAction("Break Tangents", lambda: self.set_handle_type("FREE"))
        tm.addAction("Unify Tangents", lambda: self.set_handle_type("ALIGNED"))
        im = m.addMenu("Infinity")
        for label, mode in self.INFINITY:
            im.addAction(label, lambda md=mode: self.set_infinity(md))
        m.addSeparator()
        m.addAction("Insert Key\tS", self.insert_keys)
        m.addAction("Delete Keys\tDelete", self.delete_keys)
        m.addSeparator()
        m.addAction("Select All Keys", self._select_all)
        m.addAction("Frame All\tA", lambda: self.view.frame(False))
        m.addAction("Frame Selection\tF", lambda: self.view.frame(True))
        m.exec(gpos)
        m.deleteLater()

    def _select_all(self):
        for c in self.shown():
            for kp in c.fc.keyframe_points:
                kp.select_control_point = True
        self.view.update()
        self.update_stats()

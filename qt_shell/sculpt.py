"""Sculpt Mode (and Vertex / Weight / Texture Paint) in the Qt 3D view: brush strokes, brush cursor, radius /
strength keys, undo per stroke. The paint modes run their stroke operator (`paint.vertex_paint` …) the same way
– STROKE_MODES; `sculpt_settings()` / `brush()` / `radius()` follow the current mode.

Blender's sculpt stroke is a modal operator that reads the mouse of its own 3D view – that view is hidden in
Qt Shell. The stroke runs instead as `sculpt.brush_stroke` in EXEC mode with the path of the mouse:

* the hidden 3D view gets the Qt view's camera (view matrix, perspective / ortho – the lens is already
  shared, `Viewport.fov` uses it),
* every mouse sample becomes a point on the Qt view ray, projected into the hidden view's region
  (`override_location`: Blender ray-casts itself from those mouse positions),
* samples are spaced like Blender's stroke (brush Spacing % of the diameter),
* the brush radius is in Qt pixels; for the stroke it is converted to the hidden view's pixels (and back),
* the path goes to Blender in short chunks while the mouse moves, so the surface follows the brush live;
  `undo_steps()` lets Undo / Redo take a whole stroke back at once.

Keys (keymap.py, context "3D View · Sculpt"): radius (Blender F / Maya B), strength (Shift+F / M), [ / ] radius
steps; while stroking Ctrl inverts the brush (Subtract), Shift smooths. Pen pressure comes from tablet events.
"""
import math
import time

import bpy
from bpy_extras import view3d_utils
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, keymap, theme

CHUNK_MS = 33                       # a piece of the stroke goes to Blender this often
GRAB_TYPES = {"GRAB", "ELASTIC_DEFORM", "SNAKE_HOOK", "THUMB", "POSE", "NUDGE", "ROTATE", "BOUNDARY",
              "CLOTH"}

_undo_groups = []                   # chunks per stroke (newest last) – Undo takes the whole stroke back
_redo_groups = []


# ---------------------------------------------------------------- settings
# modes the Qt view strokes in: tool settings attribute, stroke operator
STROKE_MODES = {"SCULPT": ("sculpt", "sculpt.brush_stroke"),
                "PAINT_VERTEX": ("vertex_paint", "paint.vertex_paint"),
                "PAINT_WEIGHT": ("weight_paint", "paint.weight_paint"),
                "PAINT_TEXTURE": ("image_paint", "paint.image_paint")}


def active():
    """Sculpt Mode (the sculpt-only parts: Sculpt panel, mask / remesh keys)."""
    try:
        return bpy.context.mode == "SCULPT"
    except Exception:
        return False


def stroke_mode():
    """The current mode when the Qt view paints brush strokes in it (Sculpt, Vertex / Weight / Texture Paint)."""
    try:
        m = bpy.context.mode
    except Exception:
        return None
    return m if m in STROKE_MODES else None


def stroke_active():
    return stroke_mode() is not None


def sculpt_settings():
    """Paint settings of the current stroke mode (Sculpt's outside them) – brush, radius, strength."""
    attr = STROKE_MODES[stroke_mode() or "SCULPT"][0]
    return getattr(bpy.context.scene.tool_settings, attr, None)


def brush():
    s = sculpt_settings()
    return getattr(s, "brush", None) if s else None


def unified():
    s = sculpt_settings()
    return getattr(s, "unified_paint_settings", None) if s else None


def _size_owner():
    u = unified()
    return u if (u is not None and u.use_unified_size) else brush()


def _strength_owner():
    u = unified()
    return u if (u is not None and getattr(u, "use_unified_strength", False)) else brush()


def radius():
    o = _size_owner()
    return int(getattr(o, "size", 50)) if o is not None else 50


def set_radius(px):
    o = _size_owner()
    if o is not None:
        o.size = int(max(1, min(5000, round(px))))


def strength():
    o = _strength_owner()
    return float(getattr(o, "strength", 0.5)) if o is not None else 0.5


def set_strength(v):
    o = _strength_owner()
    if o is not None:
        o.strength = max(0.0, min(10.0, float(v)))


def brush_type():
    b = brush()
    return str(getattr(b, "sculpt_brush_type", "") or "") if b is not None else ""


# brushes that only work on a Multires modifier – Blender's own UI never lets them stroke without one, and a
# stroke run from Python on a plain mesh crashes Blender (do_displacement_eraser_brush reads missing grids)
MULTIRES_BRUSHES = {"DISPLACEMENT_ERASER": "Erase Multires Displacement",
                    "DISPLACEMENT_SMEAR": "Smear Multires Displacement"}


def stroke_blocker():
    """A message why the active brush can't stroke on the active object now, or None."""
    kind = brush_type()
    if kind in MULTIRES_BRUSHES:
        ob = bpy.context.active_object
        mr = next((m for m in getattr(ob, "modifiers", ()) if m.type == "MULTIRES"), None)
        if mr is None or not mr.show_viewport or mr.sculpt_levels < 1 or mr.total_levels < 1:
            return (f"{MULTIRES_BRUSHES[kind]} works only on a Multires modifier with subdivision levels – "
                    "add one in the Sculpt panel (Topology → Add Multires, then Subdivide).")
    return None


# ---------------------------------------------------------------- undo of whole strokes
def undo_steps():
    """How many Blender undo steps the next Undo should take back (1, or all chunks of the last stroke)."""
    if stroke_active() and _undo_groups:
        n = _undo_groups.pop()
        _redo_groups.append(n)
        return n
    forget()
    return 1


def redo_steps():
    if stroke_active() and _redo_groups:
        n = _redo_groups.pop()
        _undo_groups.append(n)
        return n
    return 1


def forget():
    """Anything else changed the undo history (another operator, mode change, file): strokes are single steps."""
    _undo_groups.clear()
    _redo_groups.clear()


def _op_ran(idname):
    if idname not in ("ed.undo", "ed.redo", "ed.undo_push", "ed.undo_history"):
        forget()


bridge.op_listeners.append(_op_ran)


# ---------------------------------------------------------------- the hidden view follows the Qt view
def _sync_hidden(vp):
    found = bridge.ensure_view3d()
    if not found:
        return None
    _win, area, region = found
    sp = area.spaces.active
    rv = sp.region_3d
    w, h = vp.width(), vp.height()
    view, _proj = vp.matrices(w, h)
    ortho = bool(getattr(vp, "ortho", False)) and not getattr(vp, "camera_view", False)
    rv.view_perspective = "ORTHO" if ortho else "PERSP"
    rv.view_matrix = view
    if ortho:
        rv.view_distance = max(rv.view_distance, float(getattr(vp, "dist", 10.0)) * 2.0)
    try:
        rv.update()
    except Exception:
        pass
    return region, rv


def _to_hidden(vp, region, rv, x, y, depth):
    o, d = vp.ray(x, y)
    p = o + d * depth
    m = view3d_utils.location_3d_to_region_2d(region, rv, p)
    return (m.x, m.y) if m is not None else None


def _scale(vp, region, rv, x, y, depth):
    """Hidden-view pixels per Qt pixel around (x, y)."""
    a = _to_hidden(vp, region, rv, x, y, depth)
    b = _to_hidden(vp, region, rv, x + 20, y, depth)
    if a is None or b is None:
        return 1.0
    return max(0.05, math.hypot(b[0] - a[0], b[1] - a[1]) / 20.0)


# ---------------------------------------------------------------- one stroke
class Stroke:
    def __init__(self, vp, pos, mods, pressure):
        self.vp = vp
        self.kind = stroke_mode() or "SCULPT"
        self.mode = "INVERT" if mods & QtCore.Qt.ControlModifier else "NORMAL"
        # Shift: sculpt smooths (brush toggle); the paint modes blur with mode SMOOTH
        self.toggle = "SMOOTH" if (mods & QtCore.Qt.ShiftModifier and self.kind == "SCULPT") else "None"
        if mods & QtCore.Qt.ShiftModifier and self.kind != "SCULPT":
            self.mode = "SMOOTH"
        self.pending = []            # (x, y, pressure, t)
        self.last = None
        self.started = False
        self.chunks = 0
        self.t0 = time.time()
        self.add(pos.x(), pos.y(), pressure, force=True)

    def spacing_px(self):
        b = brush()
        sp = float(getattr(b, "spacing", 10) or 10) if b is not None else 10.0
        return max(1.0, 2.0 * radius() * sp / 100.0)

    def add(self, x, y, pressure, force=False):
        t = time.time() - self.t0
        if self.last is None or force:
            self.pending.append((x, y, pressure, t))
            self.last = (x, y)
            return
        lx, ly = self.last
        dist = math.hypot(x - lx, y - ly)
        step = self.spacing_px()
        if dist < step:
            return
        n = int(dist // step)
        for i in range(1, n + 1):
            f = i * step / dist
            self.pending.append((lx + (x - lx) * f, ly + (y - ly) * f, pressure, t))
        self.last = self.pending[-1][:2]

    def flush(self):
        if not self.pending:
            return False
        pts, self.pending = self.pending, []
        vp = self.vp
        hv = _sync_hidden(vp)
        if hv is None:
            return False
        region, rv = hv
        depth = float(getattr(vp, "dist", 10.0)) or 10.0
        k = _scale(vp, region, rv, pts[0][0], pts[0][1], depth)
        els = []
        hit = _surface_hit if self.kind != "SCULPT" else None
        for (x, y, pr, t) in pts:
            m = _to_hidden(vp, region, rv, x, y, depth)
            if m is None:
                continue
            loc = (0.0, 0.0, 0.0)
            if hit is not None:
                # the paint operators take the dab position from the element (no override_location like
                # sculpt) – (0, 0, 0) painted nothing; off the mesh there is no dab (like Blender)
                loc = hit(vp, x, y)
                if loc is None:
                    continue
            els.append({"name": "", "location": loc, "mouse": m, "mouse_event": m,
                        "pressure": float(pr), "size": float(radius() * k), "x_tilt": 0.0, "y_tilt": 0.0,
                        "time": float(t), "is_start": not self.started and not els})
        if not els:
            return False
        owner = _size_owner()
        old = owner.size if owner is not None else None
        try:
            if owner is not None:
                owner.size = int(max(1, round(old * k)))
            with bridge.blender_context():
                # undo=True: called "like from the UI" – a Python call suppresses the sculpt undo push
                # (wm.op_undo_depth), so the chunk would not be undoable at all
                if self.kind == "SCULPT":
                    r = bpy.ops.sculpt.brush_stroke("EXEC_DEFAULT", True, stroke=els, mode=self.mode,
                                                    brush_toggle=self.toggle, override_location=True)
                else:                    # Vertex / Weight / Texture Paint: Blender projects from the mouse
                    mod, name = STROKE_MODES[self.kind][1].split(".")
                    r = getattr(getattr(bpy.ops, mod), name)("EXEC_DEFAULT", True, stroke=els, mode=self.mode)
            if "FINISHED" in r:
                self.started = True
                self.chunks += 1
                _show_changes()
        except Exception as ex:
            bridge.log(f"{'Sculpt' if self.kind == 'SCULPT' else 'Paint'} stroke: {ex}", "WARNING")
        finally:
            if owner is not None and old is not None:
                owner.size = old
        vp.request_redraw()
        return True


def _surface_hit(vp, x, y):
    """World position where the Qt view's ray through (x, y) meets the active object (evaluated), or None."""
    ob = bpy.context.active_object
    if ob is None:
        return None
    try:
        o, d = vp.ray(x, y)
        ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
        inv = ob.matrix_world.inverted()
        ok, loc, _n, _i = ev.ray_cast(inv @ o, (inv.to_3x3() @ d).normalized())
    except Exception:
        return None
    return tuple(ob.matrix_world @ loc) if ok else None


def _show_changes():
    """A stroke run from Python changes the mesh, but the offscreen 3D view keeps drawing the old sculpt
    batches until the object is tagged (Blender's own view is refreshed by the stroke's region redraw)."""
    ob = bpy.context.active_object
    if ob is not None:
        try:
            ob.update_tag(refresh={"DATA"})
        except Exception:
            pass


# ---------------------------------------------------------------- radius / strength by dragging (F / Shift+F)
class SizeModal:
    def __init__(self, vp, kind, key=None):
        self.vp = vp
        self.kind = kind                         # RADIUS / STRENGTH
        self.key = key
        self.center = vp.mapFromGlobal(QtGui.QCursor.pos()).toPointF()
        self.start = radius() if kind == "RADIUS" else strength()
        self.span = theme.px(220)                # strength: this many pixels = 1.0
        if kind == "RADIUS":
            self.center = QtCore.QPointF(self.center.x() - self.start, self.center.y())
        else:
            self.center = QtCore.QPointF(self.center.x() - self.start * self.span, self.center.y())
        self.value = self.start

    def move(self, pos):
        d = math.hypot(pos.x() - self.center.x(), pos.y() - self.center.y())
        if self.kind == "RADIUS":
            self.value = max(1, int(round(d)))
            set_radius(self.value)
        else:
            self.value = max(0.0, min(1.0, d / self.span))
            set_strength(self.value)
        self.vp.update()

    def cancel(self):
        if self.kind == "RADIUS":
            set_radius(self.start)
        else:
            set_strength(self.start)

    def paint(self, p):
        c = self.center
        r = radius()
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 160), 3))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(c, r, r)
        p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1.5))
        p.drawEllipse(c, r, r)
        if self.kind == "STRENGTH":
            a = int(40 + 160 * strength())
            p.setBrush(QtGui.QColor(255, 255, 255, a))
            p.setPen(QtCore.Qt.NoPen)
            rr = max(4.0, r * strength())
            p.drawEllipse(c, rr, rr)
        txt = f"Radius {radius()} px" if self.kind == "RADIUS" else f"Strength {strength():.3f}"
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.setPen(QtGui.QColor(0, 0, 0, 200))
        p.drawText(QtCore.QPointF(c.x() - 40 + 1, c.y() + 5 + 1), txt)
        p.setPen(QtGui.QColor("#ffffff"))
        p.drawText(QtCore.QPointF(c.x() - 40, c.y() + 5), txt)


# ---------------------------------------------------------------- per-view controller
class ViewSculpt:
    """Owned by a Viewport: strokes, the brush circle, radius / strength dragging."""

    def __init__(self, vp):
        self.vp = vp
        self.stroke = None
        self.modal = None
        self.pressure = 1.0
        self.tablet = False
        self.mouse = None
        self._timer = QtCore.QTimer(vp)
        self._timer.setInterval(CHUNK_MS)
        self._timer.timeout.connect(self._tick)

    # ---- input
    def press(self, ev, pos):
        if self.modal is not None:
            if ev.button() == QtCore.Qt.LeftButton:
                self.modal = None
            else:
                self.modal.cancel()
                self.modal = None
            self.vp.update()
            return True
        if not stroke_active() or ev.button() != QtCore.Qt.LeftButton:
            return False
        if ev.modifiers() & QtCore.Qt.AltModifier:          # Alt + LMB: navigation
            return False
        if bpy.context.active_object is None or bpy.context.active_object.type != "MESH":
            return False
        msg = stroke_blocker() if active() else None
        if msg:
            bridge.log(msg, "INFO")
            return True                      # eaten: no stroke, no selection click
        _redo_groups.clear()
        self.stroke = Stroke(self.vp, pos, ev.modifiers(), self.pressure if self.tablet else 1.0)
        self.stroke.flush()
        self._timer.start()
        return True

    def move(self, ev, pos):
        self.mouse = pos
        if self.modal is not None:
            self.modal.move(pos)
            return True
        if self.stroke is not None:
            self.stroke.add(pos.x(), pos.y(), self.pressure if self.tablet else 1.0)
            self.vp.update()
            return True
        if stroke_active():
            self.vp.update()                       # the brush circle follows the mouse
        return False

    def release(self, ev):
        if self.stroke is None or ev.button() != QtCore.Qt.LeftButton:
            return False
        self._timer.stop()
        s, self.stroke = self.stroke, None
        s.flush()
        if s.chunks:
            _undo_groups.append(s.chunks)
            del _undo_groups[:-64]
        try:
            self.vp.selection_edited.emit()
        except Exception:
            pass
        self.vp.update()
        return True

    def _tick(self):
        if self.stroke is None:
            self._timer.stop()
            return
        if bridge.op_depth:          # fired inside another operator
            return
        self.stroke.flush()

    def tablet_event(self, ev):
        self.tablet = ev.pointerType() != QtGui.QPointingDevice.PointerType.Eraser
        self.pressure = max(0.0, min(1.0, float(ev.pressure())))
        if ev.type() == QtCore.QEvent.TabletRelease:
            self.tablet = False

    def key(self, ev, H):
        """Sculpt keys (radius / strength / steps). True when used."""
        if self.modal is not None:
            k = ev.key()
            if k in (QtCore.Qt.Key_Escape,):
                self.modal.cancel()
                self.modal = None
            elif k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Space):
                self.modal = None
            self.vp.update()
            return True
        if not stroke_active():
            return False
        if H("sculpt.radius"):
            self.modal = SizeModal(self.vp, "RADIUS", ev.key())
        elif H("sculpt.strength"):
            self.modal = SizeModal(self.vp, "STRENGTH", ev.key())
        elif H("sculpt.radius_down"):
            set_radius(radius() / 1.1)
        elif H("sculpt.radius_up"):
            set_radius(max(radius() + 1, radius() * 1.1))
        elif not active():                   # the rest are Sculpt Mode keys
            return False
        elif H("sculpt.mask_invert"):
            bridge.run_op("paint.mask_flood_fill", {"mode": "INVERT"})
        elif H("sculpt.mask_clear"):
            bridge.run_op("paint.mask_flood_fill", {"mode": "VALUE", "value": 0.0})
        elif H("sculpt.remesh"):
            bridge.run_op("object.voxel_remesh")
        elif H("sculpt.dyntopo"):
            bridge.run_op("sculpt.dynamic_topology_toggle")
        else:
            return False
        self.vp.update()
        sculpt_changed()
        return True

    def key_release(self, ev):
        """Maya style: releasing the radius / strength key ends the drag."""
        if self.modal is not None and not ev.isAutoRepeat() and ev.key() == self.modal.key \
                and keymap.nav_scheme() == "MAYA":
            self.modal = None
            self.vp.update()
            return True
        return False

    # ---- drawing
    def paint(self, p):
        if bridge.op_depth:          # painted inside an operator (undo): don't read Blender data now
            return
        if self.modal is not None:
            self.modal.paint(p)
            return
        # the cursor position, not underMouse(): after a popup (the right-click menu's Radius / Strength)
        # Qt keeps underMouse() False until the mouse leaves and re-enters – the circle vanished
        if not stroke_active() or self.mouse is None or getattr(self.vp, "_nav", None):
            return
        cur = self.vp.mapFromGlobal(QtGui.QCursor.pos())
        if not self.vp.rect().contains(cur):
            return
        if QtWidgets.QApplication.activePopupWidget() is None:
            self.mouse = QtCore.QPointF(cur)
        s = sculpt_settings()
        if s is not None and not getattr(s, "show_brush", True):
            return
        r = radius()
        c = self.mouse
        mods = QtGui.QGuiApplication.keyboardModifiers()
        if self.stroke is not None:
            sub = self.stroke.mode == "INVERT"
            smooth = "SMOOTH" in (self.stroke.toggle, self.stroke.mode)
        else:
            sub = bool(mods & QtCore.Qt.ControlModifier)
            smooth = bool(mods & QtCore.Qt.ShiftModifier)
        col = QtGui.QColor("#7fb2ff") if smooth else (QtGui.QColor("#ff8f8f") if sub else QtGui.QColor("#ffffff"))
        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 140), 3))
        p.drawEllipse(c, r, r)
        p.setPen(QtGui.QPen(col, 1.4))
        p.drawEllipse(c, r, r)
        # strength as a faint inner ring
        st = max(0.0, min(1.0, strength()))
        if st > 0:
            p.setPen(QtGui.QPen(QtGui.QColor(col.red(), col.green(), col.blue(), 110), 1, QtCore.Qt.DotLine))
            p.drawEllipse(c, r * st, r * st)


# ---------------------------------------------------------------- notifications
_listeners = []


def on_change(fn):
    """fn() runs when radius / strength / brush change from the view (the Sculpt panel refreshes)."""
    _listeners.append(fn)


def sculpt_changed():
    for fn in list(_listeners):
        try:
            fn()
        except Exception:
            pass


# Blender sculpt brushes (essentials asset library) in the order of the panel
LIBRARY = "brushes/essentials_brushes-mesh_sculpt.blend/Brush/"


def activate_brush(name):
    """Makes an essentials sculpt brush (e.g. "Clay Strips") the active one."""
    try:
        with bridge.blender_context():
            r = bpy.ops.brush.asset_activate(asset_library_type="ESSENTIALS", asset_library_identifier="",
                                             relative_asset_identifier=LIBRARY + name)
    except Exception as ex:
        bridge.log(f"Brush {name}: {ex}", "WARNING")
        return False
    sculpt_changed()
    return "FINISHED" in r

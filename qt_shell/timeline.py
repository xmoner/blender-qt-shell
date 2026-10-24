"""Timeline – Blender's Timeline and Maya's Time Slider / Range Slider in one.

Header (like Blender): View, Marker, Playback and Keying menus; transport (jump to start / end, previous /
next key, step one frame, play backwards / forwards); Auto Key, Insert / Delete Key; cached playback;
current frame, Preview Range toggle (the clock – Start / End then edit the preview range), Start / End,
frame rate and the loop mode (Maya: Continuous Loop / Play Once / Oscillate).

Time bar:
- Zoom and pan like Blender: mouse wheel zooms around the mouse, Ctrl + wheel / middle mouse drag pans,
  Ctrl + middle mouse drag zooms, Alt + wheel steps the frame; {timeline.frame_all} frames the scene (or
  preview) range, {timeline.zoom_in} / {timeline.zoom_out} zoom, {timeline.view_current} centres the frame.
- Range slider below (Maya): the bar is the visible part of the timeline – drag its ends to zoom, drag its
  middle to pan, double-click it to frame everything.
- Keys of the selected objects (selected bones in Pose mode), drawn by keyframe type (Keyframe, Breakdown,
  Moving Hold, Extreme, Jitter – Blender's colours and sizes). Click a key to select it (Shift: add / remove),
  drag to move the selected keys by whole frames (a key landing on another key of the same curve replaces it,
  Esc / right click cancels), Shift + drag on empty space selects a range, {timeline.select_all} /
  {timeline.deselect_all} select / deselect all, {timeline.delete_keys} deletes, {timeline.copy_keys} /
  {timeline.paste_keys} copy / paste them (pasted at the current frame). Right click: key menu (interpolation,
  keyframe type, snap, copy / paste, preview range from the selected keys, markers).
- Markers (Blender, scene.timeline_markers) in the band at the bottom: {timeline.marker_add} adds one at the
  current frame, click selects (Shift: add), drag moves, double-click / {timeline.marker_rename} renames,
  {timeline.delete_keys} also deletes selected markers.
- {timeline.frame_prev} / {timeline.frame_next} step a frame, {timeline.jump_start} / {timeline.jump_end}
  jump to start / end, {timeline.key_prev} / {timeline.key_next} jump between keys (while the Timeline has the
  focus); {window.frame_prev} / {window.frame_next} (Maya) step a frame anywhere; {window.play_reverse}
  plays backwards. {timeline.show_seconds} switches frames / seconds; {timeline.preview_set} sets the preview
  range (selected keys, else the visible range), {timeline.preview_clear} clears it.
- Click elsewhere sets the current frame (scrubbing). Cached frames show as a green line.
"""
import time

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, geocache, keymap, playcache, theme
from . import icons
from . import pytips
from .rna_widgets import DragSpin

# Blender's frame rate presets: label → (fps, fps_base)
FPS_PRESETS = [("23.98", 24, 1.001), ("24", 24, 1.0), ("25", 25, 1.0), ("29.97", 30, 1.001), ("30", 30, 1.0),
               ("50", 50, 1.0), ("59.94", 60, 1.001), ("60", 60, 1.0), ("120", 120, 1.0), ("240", 240, 1.0)]
# Maya's loop modes
LOOP_MODES = [
    ("LOOP", "Continuous Loop", "loop_continuous", "Repeats the play range"),
    ("ONCE", "Play Once", "loop_once", "Plays the range once and stops at its end"),
    ("OSCILLATE", "Oscillate", "loop_oscillate", "Plays forwards and backwards (ping-pong)"),
]
# Blender's keyframe types: id → (label, size factor, colour, selected colour)
KEY_TYPES = {
    "KEYFRAME": ("Keyframe", 1.0, "#e8e8e8", "#ffbe33"),
    "BREAKDOWN": ("Breakdown", 0.8, "#b3dbe8", "#54bfed"),
    "MOVING_HOLD": ("Moving Hold", 0.75, "#5c5656", "#ffaf23"),
    "EXTREME": ("Extreme", 1.2, "#e8b3cc", "#f28080"),
    "JITTER": ("Jitter", 0.75, "#94e575", "#61c042"),
    "GENERATED": ("Generated", 0.75, "#585858", "#a28962"),
}
_KEY_PRIORITY = ("EXTREME", "KEYFRAME", "BREAKDOWN", "JITTER", "MOVING_HOLD", "GENERATED")
INTERPOLATIONS = [("CONSTANT", "Constant"), ("LINEAR", "Linear"), ("BEZIER", "Bézier")]
_COPY = []             # copied keys: {"ob", "path", "index", "offset", "value", "interp", "type"}


def _qs():
    return QtCore.QSettings("QtShell", "QtShell")


def setting(key, default):
    v = _qs().value(f"timeline/{key}", default)
    if isinstance(default, bool):
        return str(v).lower() == "true"
    return type(default)(v) if v is not None else default


def set_setting(key, value):
    _qs().setValue(f"timeline/{key}", ("true" if value else "false") if isinstance(value, bool) else value)


def play_range(scene=None):
    """(start, end) of playback: the preview range when it is on, else the scene range."""
    sc = scene or bpy.context.scene
    if sc.use_preview_range:
        return sc.frame_preview_start, sc.frame_preview_end
    return sc.frame_start, sc.frame_end


def _runs(frames):
    """[(first, last)] of consecutive frames."""
    out = []
    for f in frames:
        if out and f == out[-1][1] + 1:
            out[-1][1] = f
        else:
            out.append([f, f])
    return out


def fps_label(render=None):
    r = render or bpy.context.scene.render
    base = r.fps_base or 1.0
    if abs(base - 1.0) < 1e-6:
        return f"{r.fps} fps"
    v = r.fps / base
    return f"{v:.2f} fps" if abs(v - round(v)) > 1e-3 else f"{round(v)} fps"


def frame_text(frame, seconds=False):
    """A frame as Blender's timeline shows it: 25, or with Show Seconds 1+00 (seconds+frames)."""
    if not seconds:
        return str(int(frame))
    r = bpy.context.scene.render
    fps = max(r.fps / (r.fps_base or 1.0), 0.01)
    neg = frame < 0
    f = abs(frame)
    s = int(f // fps)
    rest = int(round(f - s * fps))
    return f"{'-' if neg else ''}{s}+{rest:02d}"


def timeline_curves():
    """(object, F-curve) pairs the Timeline shows: the selected objects (and the active one); in Pose mode
    only the curves of the selected bones (like Blender's Timeline with Only Show Selected)."""
    from .graph_editor import fcurves_of
    from . import keying
    ctx = bpy.context
    vl = ctx.view_layer
    obs = [o for o in vl.objects if o.select_get()]     # (ctx.selected_objects is missing in some contexts)
    act = vl.objects.active
    if act is not None and act not in obs:
        obs.append(act)
    out = []
    for ob in obs:
        names = keying.selected_bone_names(ob) if ob.type == "ARMATURE" else None
        for fc in fcurves_of(ob):
            if keying.fcurve_visible(ob, fc, names):
                out.append((ob, fc))
    return out


def _reevaluate():
    sc = bpy.context.scene
    try:
        sc.frame_set(sc.frame_current)      # the animation follows the moved / deleted keys
    except Exception:
        pass


# ---------------------------------------------------------------- time bar
class TimeBar(QtWidgets.QWidget):
    """Ruler, keys, markers, playhead – zoomable and pannable (Blender), keys movable."""

    view_changed = QtCore.Signal()

    def __init__(self, timeline):
        super().__init__(timeline)
        self.tl = timeline
        self.setMinimumHeight(theme.px(62))
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.keys = {}            # frame → keyframe type shown (the most important one on that frame)
        self.sel = set()          # selected key frames
        self.view = None          # visible frames (lo, hi) – None = the play range with a margin
        self._drag = None         # moving keys: {"start", "delta", "points", "sel"}
        self._mdrag = None        # moving markers: {"start", "delta", "orig"}
        self._range_sel = None    # Shift + drag on empty space: (x0, x1)
        self._nav = None          # middle mouse: ("pan" | "zoom", last x)
        self._scrubbing = False
        self._hover = None
        self._hover_marker = None
        keymap.tip(self, "Click a key to select it (Shift: add), drag keys to move them, Shift + drag: select a "
                         "range, right click: key menu · wheel: zoom, Ctrl + wheel / middle mouse: pan · "
                         "{timeline.marker_add}: add a marker · click elsewhere: set the frame")

    # --- geometry
    def ruler_h(self):
        return theme.px(18)

    def marker_h(self):
        return theme.px(16) if setting("show_markers", True) else 0

    def key_y(self):
        top, bottom = self.ruler_h(), self.height() - self.marker_h()
        return (top + bottom) / 2

    def default_view(self):
        a, b = play_range()
        pad = max(2, (b - a) // 20)
        return float(a - pad), float(b + pad)

    def view_range(self):
        return self.view if self.view is not None else self.default_view()

    def set_view(self, lo, hi):
        lo, hi = float(lo), float(hi)
        if hi - lo < 4:
            c = (lo + hi) / 2
            lo, hi = c - 2, c + 2
        if hi - lo > 1e6:
            c = (lo + hi) / 2
            lo, hi = c - 5e5, c + 5e5
        self.view = (lo, hi)
        self.update()
        self.view_changed.emit()

    def frame_all(self):
        self.view = None
        self.update()
        self.view_changed.emit()

    def zoom(self, factor, anchor_x=None):
        lo, hi = self.view_range()
        a = self.x_to_framef(anchor_x) if anchor_x is not None else (lo + hi) / 2
        self.set_view(a - (a - lo) * factor, a + (hi - a) * factor)

    def pan_frames(self, d):
        lo, hi = self.view_range()
        self.set_view(lo + d, hi + d)

    def view_current(self):
        lo, hi = self.view_range()
        f = self.tl.shown_frame()
        self.set_view(f - (hi - lo) / 2, f + (hi - lo) / 2)

    def follow(self, f):
        """Follow Current Frame during playback: page the view when the frame leaves it."""
        lo, hi = self.view_range()
        if self.view is None or lo <= f <= hi:
            return
        span = hi - lo
        self.set_view(f - span * 0.05, f + span * 0.95)

    def frame_to_x(self, f):
        lo, hi = self.view_range()
        return 10 + (f - lo) / max(hi - lo, 1e-6) * (self.width() - 20)

    def x_to_framef(self, x):
        lo, hi = self.view_range()
        return lo + (x - 10) / max(self.width() - 20, 1) * (hi - lo)

    def x_to_frame(self, x):
        return round(self.x_to_framef(x))

    # --- hit tests
    def key_at(self, pos):
        if abs(pos.y() - self.key_y()) > theme.px(9):
            return None
        best = None
        for k in self.keys:
            d = abs(self.frame_to_x(k) - pos.x())
            if d <= theme.px(7) and (best is None or d < best[0]):
                best = (d, k)
        return best[1] if best else None

    def in_marker_band(self, pos):
        mh = self.marker_h()
        return mh > 0 and pos.y() >= self.height() - mh

    def marker_at(self, pos):
        if not self.in_marker_band(pos):
            return None
        best = None
        for m in bpy.context.scene.timeline_markers:
            d = abs(self.frame_to_x(m.frame) - pos.x())
            if d <= theme.px(7) and (best is None or d < best[0]):
                best = (d, m)
        return best[1] if best else None

    # --- keys: move / delete / select
    def _selected_points(self):
        out = []
        for ob, fc in timeline_curves():
            for kp in fc.keyframe_points:
                if int(round(kp.co.x)) in self.sel:
                    out.append((ob, fc, kp))
        return out

    def _start_drag(self, frame):
        pts = [(ob, fc, kp, kp.co.x, kp.handle_left.x, kp.handle_right.x)
               for ob, fc, kp in self._selected_points()]
        self._drag = {"start": frame, "delta": 0, "points": pts, "sel": set(self.sel)}

    def _apply_drag(self, delta):
        d = self._drag
        if delta == d["delta"]:
            return
        d["delta"] = delta
        for _ob, _fc, kp, x, hl, hr in d["points"]:
            kp.co.x = x + delta
            kp.handle_left.x = hl + delta
            kp.handle_right.x = hr + delta
        self.sel = {f + delta for f in d["sel"]}
        for ob in {p[0] for p in d["points"]}:
            ob.update_tag()
        _reevaluate()
        self.tl.sync()

    def _end_drag(self, cancel=False):
        d, self._drag = self._drag, None
        if d is None:
            return
        if cancel:
            self._drag = d
            self._apply_drag(0)
            self._drag = None
            return
        if d["delta"] == 0:
            return
        moved = {}
        for _ob, fc, kp, *_r in d["points"]:
            moved.setdefault(fc, set()).add(kp.as_pointer())
        for fc, ptrs in moved.items():
            frames = {int(round(kp.co.x)) for kp in fc.keyframe_points if kp.as_pointer() in ptrs}
            # a moved key replaces a key of the same curve on its new frame (Blender merges them too)
            for kp in reversed(list(fc.keyframe_points)):
                if kp.as_pointer() not in ptrs and int(round(kp.co.x)) in frames:
                    fc.keyframe_points.remove(kp, fast=True)
            fc.update()
        _reevaluate()
        n = len(d["sel"])
        bridge.undo_push("Move Keyframes")
        self.tl.status(f"Moved {n} key frame{'s' if n != 1 else ''} by {d['delta']:+d}")
        self.tl.sync()

    def delete_selected(self):
        """Deletes the selected keys and the selected markers."""
        n = 0
        if self.sel:
            for ob, fc in timeline_curves():
                hit = False
                for kp in reversed(list(fc.keyframe_points)):
                    if int(round(kp.co.x)) in self.sel:
                        fc.keyframe_points.remove(kp, fast=True)
                        n += 1
                        hit = True
                if hit:
                    fc.update()
                    ob.update_tag()
            self.sel.clear()
        markers = [m for m in bpy.context.scene.timeline_markers if m.select]
        for m in markers:
            bpy.context.scene.timeline_markers.remove(m)
        if n or markers:
            if n:
                _reevaluate()
            bridge.undo_push("Delete Keyframes" if n else "Delete Markers")
            parts = ([f"{n} key{'s' if n != 1 else ''}"] if n else []) + (
                [f"{len(markers)} marker{'s' if len(markers) != 1 else ''}"] if markers else [])
            self.tl.status("Deleted " + " and ".join(parts))
        self.tl.sync()
        return n

    def select_all(self):
        """Like Blender's A: selects all keys (all selected already → deselects)."""
        self.sel = set() if self.keys and self.sel >= set(self.keys) else set(self.keys)
        self.update()

    def set_interpolation(self, mode):
        pts = self._selected_points()
        for _ob, _fc, kp in pts:
            kp.interpolation = mode
        self._after_key_edit(pts, f"Interpolation: {mode.title()}")

    def set_key_type(self, ktype):
        pts = self._selected_points()
        for _ob, _fc, kp in pts:
            kp.type = ktype
        self._after_key_edit(pts, f"Keyframe Type: {KEY_TYPES[ktype][0]}")

    def snap_keys(self):
        pts = self._selected_points()
        for _ob, _fc, kp in pts:
            d = round(kp.co.x) - kp.co.x
            kp.co.x += d
            kp.handle_left.x += d
            kp.handle_right.x += d
        self._after_key_edit(pts, "Snap Keys")

    def _after_key_edit(self, pts, message):
        if not pts:
            self.tl.status("No keys selected – click a key in the Timeline first")
            return
        for fc in {id(p[1]): p[1] for p in pts}.values():
            fc.update()
        for ob in {p[0] for p in pts}:
            ob.update_tag()
        _reevaluate()
        bridge.undo_push(message)
        self.tl.status(f"{message} ({len(pts)} key{'s' if len(pts) != 1 else ''})")
        self.tl.sync()

    def copy_keys(self):
        pts = self._selected_points()
        if not pts:
            self.tl.status("No keys selected to copy")
            return 0
        base = min(kp.co.x for _ob, _fc, kp in pts)
        _COPY[:] = [{"ob": ob.name, "path": fc.data_path, "index": fc.array_index, "offset": kp.co.x - base,
                     "value": kp.co.y, "interp": kp.interpolation, "type": kp.type} for ob, fc, kp in pts]
        self.tl.status(f"Copied {len(_COPY)} key{'s' if len(_COPY) != 1 else ''}")
        return len(_COPY)

    def paste_keys(self):
        """Pastes the copied keys at the current frame (to the same objects; with keys of one object copied,
        to the active object when that object isn't there)."""
        from .graph_editor import fcurves_of
        if not _COPY:
            self.tl.status("Nothing copied – select keys and copy them first")
            return 0
        f0 = bpy.context.scene.frame_current
        act = bpy.context.view_layer.objects.active
        single = len({c["ob"] for c in _COPY}) == 1
        n, touched = 0, set()
        for c in _COPY:
            ob = bpy.data.objects.get(c["ob"])
            if (ob is None or single) and act is not None and (ob is None or not ob.select_get()):
                ob = act
            if ob is None:
                continue
            fc = next((x for x in fcurves_of(ob) if x.data_path == c["path"] and x.array_index == c["index"]),
                      None)
            frame = f0 + c["offset"]
            if fc is None:
                try:
                    ob.keyframe_insert(c["path"], index=c["index"], frame=frame)
                except Exception as ex:
                    bridge.log(f"Paste keys: {c['path']}[{c['index']}]: {ex}", "WARNING")
                    continue
                fc = next((x for x in fcurves_of(ob) if x.data_path == c["path"] and x.array_index == c["index"]),
                          None)
                if fc is None:
                    continue
            kp = fc.keyframe_points.insert(frame, c["value"])
            if kp is None:
                continue
            kp.interpolation = c["interp"]
            kp.type = c["type"]
            fc.update()
            touched.add(ob)
            n += 1
        for ob in touched:
            ob.update_tag()
        if n:
            _reevaluate()
            bridge.undo_push("Paste Keyframes")
            self.sel = {int(round(f0 + c["offset"])) for c in _COPY}
        self.tl.status(f"Pasted {n} key{'s' if n != 1 else ''} at frame {f0}")
        self.tl.sync()
        return n

    # --- markers
    def add_marker(self, name=None, frame=None):
        sc = bpy.context.scene
        f = sc.frame_current if frame is None else int(frame)
        for m in sc.timeline_markers:
            m.select = False
        m = sc.timeline_markers.new(name or f"F_{f:02d}", frame=f)
        m.select = True
        bridge.undo_push("Add Marker")
        self.tl.status(f"Marker {m.name} at frame {f}")
        self.update()
        return m

    def rename_marker(self, marker=None):
        sc = bpy.context.scene
        m = marker or next((x for x in sc.timeline_markers if x.select), None)
        if m is None:
            self.tl.status("Select a marker first")
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Rename Marker", "Name:", text=m.name)
        if ok and name:
            m.name = name
            bridge.undo_push("Rename Marker")
            self.update()

    def jump_marker(self, step):
        sc = bpy.context.scene
        f = sc.frame_current
        frames = sorted({m.frame for m in sc.timeline_markers})
        cand = [x for x in frames if x > f] if step > 0 else [x for x in frames if x < f]
        if cand:
            sc.frame_set(cand[0] if step > 0 else cand[-1])
            self.tl.sync()

    # --- painting
    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        sc = bpy.context.scene
        W, H = self.width(), self.height()
        rh, mh = self.ruler_h(), self.marker_h()
        seconds = setting("show_seconds", False)
        p.fillRect(self.rect(), QtGui.QColor("#1f1f1f"))
        x0, x1 = self.frame_to_x(sc.frame_start), self.frame_to_x(sc.frame_end)
        p.fillRect(QtCore.QRectF(x0, 0, x1 - x0, H), QtGui.QColor("#2b2b2b"))
        if sc.use_preview_range:        # Blender darkens everything outside the preview range
            a, b = self.frame_to_x(sc.frame_preview_start), self.frame_to_x(sc.frame_preview_end)
            shade = QtGui.QColor(0, 0, 0, 110)
            p.fillRect(QtCore.QRectF(0, 0, max(0.0, a), H), shade)
            p.fillRect(QtCore.QRectF(b, 0, max(0.0, W - b), H), shade)
            p.setPen(QtGui.QPen(QtGui.QColor("#c8742b"), 1))
            p.drawLine(QtCore.QPointF(a, 0), QtCore.QPointF(a, H))
            p.drawLine(QtCore.QPointF(b, 0), QtCore.QPointF(b, H))
        # ruler
        p.fillRect(QtCore.QRectF(0, 0, W, rh), QtGui.QColor(0, 0, 0, 60))
        lo, hi = self.view_range()
        span = hi - lo
        fps = max(sc.render.fps / (sc.render.fps_base or 1.0), 0.01)
        steps = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 50000, 100000)
        if seconds:                     # whole seconds (and their multiples) like Blender
            r = max(int(round(fps)), 1)
            steps = tuple(sorted({max(1, r // 4), max(1, r // 2), r, 2 * r, 5 * r, 10 * r, 30 * r, 60 * r,
                                  300 * r, 600 * r, 3600 * r}))
        step = steps[-1]
        for s in steps:
            if span / s <= max(W, 1) / theme.px(52):
                step = s
                break
        f = p.font()
        f.setPixelSize(theme.fs(10))
        p.setFont(f)
        first = int(lo // step) * step
        fr = first
        while fr <= hi + step:
            x = self.frame_to_x(fr)
            p.setPen(QtGui.QColor("#353535"))
            p.drawLine(QtCore.QPointF(x, rh), QtCore.QPointF(x, H - mh))
            p.setPen(QtGui.QColor("#8c8c8c"))
            p.drawLine(QtCore.QPointF(x, rh - theme.px(5)), QtCore.QPointF(x, rh))
            p.drawText(QtCore.QPointF(x + 3, rh - theme.px(6)), frame_text(fr, seconds))
            fr += step
        # markers band
        if mh:
            p.fillRect(QtCore.QRectF(0, H - mh, W, mh), QtGui.QColor(0, 0, 0, 70))
        # cached frames – a green line along the bottom, like Maya's cache bar
        cached = self.tl.cached_frames()
        if cached:
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor("#4caf50"))
            hb = max(3, theme.px(3))
            half = max(self.frame_to_x(1) - self.frame_to_x(0), 1.0) / 2
            for a, b in _runs(sorted(cached)):
                xa, xb = self.frame_to_x(a) - half, self.frame_to_x(b) + half
                p.drawRect(QtCore.QRectF(xa, H - mh - hb, xb - xa, hb))
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        if self._range_sel is not None:
            a, b = sorted(self._range_sel)
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1, QtCore.Qt.DashLine))
            p.setBrush(QtGui.QColor(255, 255, 255, 25))
            p.drawRect(QtCore.QRectF(a, rh, b - a, H - rh - mh))
        # keys (Blender's keyframe type shapes and colours)
        y = self.key_y()
        base_r = theme.px(7)
        for k, kt in self.keys.items():
            x = self.frame_to_x(k)
            if x < -10 or x > W + 10:
                continue
            _label, size, col, scol = KEY_TYPES.get(kt, KEY_TYPES["KEYFRAME"])
            r = base_r * size * (1.15 if k == self._hover else 1.0)
            poly = QtGui.QPolygonF([QtCore.QPointF(x, y - r), QtCore.QPointF(x + r, y),
                                    QtCore.QPointF(x, y + r), QtCore.QPointF(x - r, y)])
            p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
            p.setBrush(QtGui.QColor(scol if k in self.sel else col))
            p.drawPolygon(poly)
        try:
            from . import bluepencil
            bluepencil.paint_timeline(self, p)      # Blue Pencil frame ticks (active layer)
        except Exception as ex:
            bridge.log(f"Blue Pencil timeline: {ex}", "WARNING")
        if self._drag is not None and self._drag["delta"]:
            f = p.font()
            f.setPixelSize(theme.fs(11))
            p.setFont(f)
            p.setPen(QtGui.QColor("#ffbe33"))
            k = min(self.sel) if self.sel else 0
            p.drawText(QtCore.QPointF(self.frame_to_x(k) + 8, y - 8), f"{self._drag['delta']:+d}")
        # markers
        if mh:
            f = p.font()
            f.setPixelSize(theme.fs(10))
            p.setFont(f)
            cur = sc.frame_current
            for m in sc.timeline_markers:
                x = self.frame_to_x(m.frame)
                if x < -60 or x > W + 10:
                    continue
                on = m.select or m == self._hover_marker
                col = QtGui.QColor("#ffffff") if on else QtGui.QColor("#a8a8a8")
                yb = H - mh
                tri = QtGui.QPolygonF([QtCore.QPointF(x - theme.px(5), yb + theme.px(2)),
                                       QtCore.QPointF(x + theme.px(5), yb + theme.px(2)),
                                       QtCore.QPointF(x, yb + theme.px(8))])
                p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
                p.setBrush(col)
                p.drawPolygon(tri)
                if m.select:
                    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 70), 1, QtCore.Qt.DashLine))
                    p.drawLine(QtCore.QPointF(x, rh), QtCore.QPointF(x, yb))
                p.setPen(col if m.frame != cur else QtGui.QColor("#ffbe33"))
                p.drawText(QtCore.QPointF(x + theme.px(6), H - theme.px(3)), m.name)
        # playhead with the frame box (Blender)
        fcur = self.tl.shown_frame()
        x = self.frame_to_x(fcur)
        blue = QtGui.QColor("#4772b3")
        p.setPen(QtGui.QPen(blue, 2))
        p.drawLine(QtCore.QPointF(x, rh), QtCore.QPointF(x, H))
        f = p.font()
        f.setPixelSize(theme.fs(11))
        f.setBold(True)
        p.setFont(f)
        txt = frame_text(fcur, seconds)
        tw = p.fontMetrics().horizontalAdvance(txt) + theme.px(10)
        box = QtCore.QRectF(x - tw / 2, 1, tw, rh - 2)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(blue)
        p.drawRoundedRect(box, theme.px(4), theme.px(4))
        p.setPen(QtGui.QColor("#ffffff"))
        p.drawText(box, QtCore.Qt.AlignCenter, txt)
        p.end()

    # --- mouse
    def mousePressEvent(self, ev):
        pos = ev.position()
        b = ev.button()
        if self._drag is not None or self._mdrag is not None:   # right click while moving: cancel
            if self._drag is not None:
                self._end_drag(cancel=b != QtCore.Qt.LeftButton)
            else:
                self._end_mdrag(cancel=b != QtCore.Qt.LeftButton)
            self.update()
            return
        if b == QtCore.Qt.MiddleButton:
            self._nav = ("zoom" if ev.modifiers() & QtCore.Qt.ControlModifier else "pan", pos.x())
            self.setCursor(QtCore.Qt.SizeHorCursor if self._nav[0] == "zoom" else QtCore.Qt.ClosedHandCursor)
            return
        if b == QtCore.Qt.RightButton:
            self._context_menu(pos, ev.globalPosition().toPoint())
            return
        if b != QtCore.Qt.LeftButton:
            return
        from . import bluepencil
        if bluepencil.timeline_press(self, ev):       # a Blue Pencil frame tick: select / move
            return
        shift = bool(ev.modifiers() & QtCore.Qt.ShiftModifier)
        sc = bpy.context.scene
        if self.in_marker_band(pos):
            m = self.marker_at(pos)
            if m is not None:
                if shift:
                    m.select = not m.select
                elif not m.select:
                    for x in sc.timeline_markers:
                        x.select = False
                    m.select = True
                if m.select:
                    self._mdrag = {"start": m.frame, "delta": 0,
                                   "orig": [(x, x.frame) for x in sc.timeline_markers if x.select]}
                self.update()
                return
            if not shift:
                for x in sc.timeline_markers:
                    x.select = False
        k = self.key_at(pos)
        if k is not None:
            if shift:
                self.sel ^= {k}
                self.update()
                if k not in self.sel:
                    return
            elif k not in self.sel:
                self.sel = {k}
            self._start_drag(k)
            self.update()
            return
        if shift:
            self._range_sel = (pos.x(), pos.x())
            self.update()
            return
        self.sel.clear()
        self._scrubbing = True
        self._scrub(pos.x())

    def mouseDoubleClickEvent(self, ev):
        m = self.marker_at(ev.position()) if ev.button() == QtCore.Qt.LeftButton else None
        if m is not None:
            self.rename_marker(m)
            return
        super().mouseDoubleClickEvent(ev)

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if getattr(self, "_bp_drag", None) is not None:
            from . import bluepencil
            bluepencil.timeline_move(self, ev)
            return
        if self._nav is not None:
            kind, last = self._nav
            self._nav = (kind, pos.x())
            lo, hi = self.view_range()
            if kind == "pan":
                self.pan_frames(-(pos.x() - last) / max(self.width() - 20, 1) * (hi - lo))
            else:
                self.zoom(1.01 ** (last - pos.x()))
            return
        if self._drag is not None:
            self._apply_drag(self.x_to_frame(pos.x()) - self._drag["start"])
            self.update()
        elif self._mdrag is not None:
            d = self.x_to_frame(pos.x()) - self._mdrag["start"]
            if d != self._mdrag["delta"]:
                self._mdrag["delta"] = d
                for m, f in self._mdrag["orig"]:
                    m.frame = f + d
                self.update()
        elif self._range_sel is not None:
            self._range_sel = (self._range_sel[0], pos.x())
            self.update()
        elif self._scrubbing and ev.buttons() & QtCore.Qt.LeftButton:
            self._scrub(pos.x())
        else:
            h = self.key_at(pos)
            hm = self.marker_at(pos)
            if h != self._hover or hm != self._hover_marker:
                self._hover = h
                self._hover_marker = hm
                self.setCursor(QtCore.Qt.SizeHorCursor if (h is not None or hm is not None)
                               else QtCore.Qt.ArrowCursor)
                self.update()

    def mouseReleaseEvent(self, ev):
        if self._nav is not None and ev.button() == QtCore.Qt.MiddleButton:
            self._nav = None
            self.unsetCursor()
            return
        if ev.button() != QtCore.Qt.LeftButton:
            return
        if getattr(self, "_bp_drag", None) is not None:
            from . import bluepencil
            bluepencil.timeline_release(self, ev)
            return
        if self._drag is not None:
            self._end_drag()
        elif self._mdrag is not None:
            self._end_mdrag()
        elif self._range_sel is not None:
            a, b = sorted(self._range_sel)
            self._range_sel = None
            self.sel |= {k for k in self.keys if a <= self.frame_to_x(k) <= b}
            from . import bluepencil
            bluepencil.timeline_select_range(self.x_to_framef(a), self.x_to_framef(b))
        self._scrubbing = False
        self.update()

    def _end_mdrag(self, cancel=False):
        d, self._mdrag = self._mdrag, None
        if d is None:
            return
        if cancel:
            for m, f in d["orig"]:
                m.frame = f
        elif d["delta"]:
            bridge.undo_push("Move Markers")
        self.update()

    def wheelEvent(self, ev):
        steps = ev.angleDelta().y() / 120.0 or ev.angleDelta().x() / 120.0
        if not steps:
            return
        mods = ev.modifiers()
        if mods & QtCore.Qt.AltModifier:           # Blender: Alt + wheel changes the frame
            self.tl.step(-1 if steps > 0 else 1)
        elif mods & (QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier):
            lo, hi = self.view_range()
            self.pan_frames(-steps * (hi - lo) * 0.1)
        else:
            self.zoom(0.85 ** steps, ev.position().x())
        ev.accept()

    def leaveEvent(self, ev):
        if self._hover is not None or self._hover_marker is not None:
            self._hover = self._hover_marker = None
            self.update()
        super().leaveEvent(ev)

    def _context_menu(self, pos, gpos):
        tl = self.tl
        m = QtWidgets.QMenu(self)
        m.setToolTipsVisible(True)
        k = self.key_at(pos)
        if k is not None and k not in self.sel:
            self.sel = {k}
            self.update()
        mk = self.marker_at(pos)
        if mk is not None:
            for x in bpy.context.scene.timeline_markers:
                x.select = x == mk
            self.update()
            tl.fill_marker_menu(m)
            m.exec(gpos)
            m.deleteLater()
            return
        tl.fill_key_menu(m)
        m.exec(gpos)
        m.deleteLater()

    # --- keys
    _KEYS = ("timeline.delete_keys", "timeline.select_all", "timeline.deselect_all", "timeline.copy_keys",
             "timeline.paste_keys", "timeline.frame_prev", "timeline.frame_next", "timeline.jump_start",
             "timeline.jump_end", "timeline.key_prev", "timeline.key_next", "timeline.frame_all",
             "timeline.view_current", "timeline.zoom_in", "timeline.zoom_out", "timeline.marker_add",
             "timeline.marker_rename", "timeline.show_seconds", "timeline.preview_set", "timeline.preview_clear")

    def keyPressEvent(self, ev):
        names = keymap.event_names(ev)
        if (self._drag is not None or self._mdrag is not None) and ev.key() == QtCore.Qt.Key_Escape:
            if self._drag is not None:
                self._end_drag(cancel=True)
            else:
                self._end_mdrag(cancel=True)
            self.update()
            ev.accept()
            return
        for aid in self._KEYS:
            if keymap.hit(aid, ev, names):
                self.tl.run_action(aid)
                self.update()
                ev.accept()
                return
        super().keyPressEvent(ev)

    def event(self, ev):
        # the Timeline's keys win over window shortcuts while it has the focus
        if ev.type() == QtCore.QEvent.ShortcutOverride:
            names = keymap.event_names(ev)
            if any(keymap.hit(a, ev, names) for a in self._KEYS) or (
                    (self._drag is not None or self._mdrag is not None) and ev.key() == QtCore.Qt.Key_Escape):
                ev.accept()
                return True
        return super().event(ev)

    def _scrub(self, x):
        bpy.context.scene.frame_set(self.x_to_frame(x))
        self.tl.sync()


# ---------------------------------------------------------------- range slider (Maya)
class RangeSlider(QtWidgets.QWidget):
    """Maya's Range Slider: the bar is the visible part of the timeline – drag its ends to zoom, its middle
    to pan; click outside the bar centres the view there; double-click frames everything."""

    def __init__(self, bar, parent):
        super().__init__(parent)
        self.bar = bar
        self.setFixedHeight(theme.px(16))
        self.setMouseTracking(True)
        self._drag = None          # (part, press x, view at press, extent at press)
        self._hover = None
        bar.view_changed.connect(self.update)
        self.setToolTip("Range slider (Maya): drag the ends of the bar to zoom the timeline, its middle to move "
                        "it; double-click: frame the scene range · wheel: zoom")

    def extent(self):
        sc = bpy.context.scene
        lo, hi = self.bar.view_range()
        a = min(sc.frame_start, lo, sc.frame_preview_start if sc.use_preview_range else sc.frame_start)
        b = max(sc.frame_end, hi, sc.frame_preview_end if sc.use_preview_range else sc.frame_end)
        return a, b

    def _x(self, f, ext=None):
        a, b = ext or self.extent()
        m = theme.px(6)
        return m + (f - a) / max(b - a, 1e-6) * (self.width() - 2 * m)

    def _f(self, x, ext=None):
        a, b = ext or self.extent()
        m = theme.px(6)
        return a + (x - m) / max(self.width() - 2 * m, 1) * (b - a)

    def _part(self, x):
        lo, hi = self.bar.view_range()
        xa, xb = self._x(lo), self._x(hi)
        g = theme.px(6)
        if abs(x - xa) <= g:
            return "lo"
        if abs(x - xb) <= g:
            return "hi"
        if xa < x < xb:
            return "move"
        return None

    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        H = self.height()
        p.fillRect(self.rect(), QtGui.QColor("#1b1b1b"))
        sc = bpy.context.scene
        ext = self.extent()
        a, b = self._x(sc.frame_start, ext), self._x(sc.frame_end, ext)
        p.fillRect(QtCore.QRectF(a, 3, b - a, H - 6), QtGui.QColor("#262626"))
        lo, hi = self.bar.view_range()
        xa, xb = self._x(lo, ext), self._x(hi, ext)
        r = QtCore.QRectF(xa, 2, max(xb - xa, theme.px(8)), H - 4)
        p.setPen(QtGui.QPen(QtGui.QColor("#151515"), 1))
        p.setBrush(QtGui.QColor("#5a5a5a" if self._hover or self._drag else "#4a4a4a"))
        p.drawRoundedRect(r, theme.px(4), theme.px(4))
        p.setBrush(QtGui.QColor("#8a8a8a"))
        p.setPen(QtCore.Qt.NoPen)
        for gx in (r.left() + theme.px(3), r.right() - theme.px(3)):
            p.drawRoundedRect(QtCore.QRectF(gx - 1.5, 4, 3, H - 8), 1.5, 1.5)
        f = p.font()
        f.setPixelSize(theme.fs(9))
        p.setFont(f)
        p.setPen(QtGui.QColor("#d0d0d0"))
        if r.width() > theme.px(70):
            p.drawText(r.adjusted(theme.px(7), 0, -theme.px(7), 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                       str(int(round(lo))))
            p.drawText(r.adjusted(theme.px(7), 0, -theme.px(7), 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight,
                       str(int(round(hi))))
        x = self._x(self.bar.tl.shown_frame(), ext)
        p.setPen(QtGui.QPen(QtGui.QColor("#4772b3"), 2))
        p.drawLine(QtCore.QPointF(x, 1), QtCore.QPointF(x, H - 1))
        p.end()

    def mousePressEvent(self, ev):
        if ev.button() != QtCore.Qt.LeftButton:
            return
        x = ev.position().x()
        part = self._part(x)
        ext = self.extent()
        if part is None:                     # click outside the bar: centre the view there
            lo, hi = self.bar.view_range()
            c = self._f(x, ext)
            self.bar.set_view(c - (hi - lo) / 2, c + (hi - lo) / 2)
            part = "move"
            ext = self.extent()
        self._drag = (part, x, self.bar.view_range(), ext)

    def mouseMoveEvent(self, ev):
        x = ev.position().x()
        if self._drag is None:
            h = self._part(x)
            if h != self._hover:
                self._hover = h
                self.setCursor(QtCore.Qt.SizeHorCursor if h in ("lo", "hi") else (
                    QtCore.Qt.OpenHandCursor if h == "move" else QtCore.Qt.ArrowCursor))
                self.update()
            return
        part, x0, (lo, hi), ext = self._drag
        d = self._f(x, ext) - self._f(x0, ext)
        if part == "move":
            self.bar.set_view(lo + d, hi + d)
        elif part == "lo":
            self.bar.set_view(min(lo + d, hi - 4), hi)
        else:
            self.bar.set_view(lo, max(hi + d, lo + 4))

    def mouseReleaseEvent(self, _ev):
        self._drag = None
        self.update()

    def mouseDoubleClickEvent(self, _ev):
        self.bar.frame_all()

    def wheelEvent(self, ev):
        steps = ev.angleDelta().y() / 120.0
        if steps:
            self.bar.zoom(0.85 ** steps)
        ev.accept()

    def leaveEvent(self, ev):
        self._hover = None
        self.update()
        super().leaveEvent(ev)


# ---------------------------------------------------------------- the Timeline
class Timeline(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.loop_mode = setting("loop_mode", "LOOP")
        if self.loop_mode not in [m[0] for m in LOOP_MODES]:
            self.loop_mode = "LOOP"
        self._dir = 1                     # playback direction (1 forwards, -1 backwards)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(2)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(3)

        def menu_btn(text, fill, tip):
            b = QtWidgets.QToolButton(self)
            b.setText(text)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            b.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
            m = QtWidgets.QMenu(b)
            m.setToolTipsVisible(True)
            m.aboutToShow.connect(lambda: fill(m))
            b.setMenu(m)
            row.addWidget(b)
            return b

        menu_btn("View", self.fill_view_menu, "View: zoom, seconds, markers, follow the frame")
        menu_btn("Marker", self.fill_marker_menu, "Markers: add, rename, delete, jump")
        menu_btn("Playback", self.fill_playback_menu, "Playback: loop, sync mode, follow current frame")
        menu_btn("Keying", self.fill_keying_menu, "Keying: auto keying mode, new keyframe type, key tools")
        row.addSpacing(8)

        def btn(icon, glyph, fn, py=None, checkable=False):
            b = QtWidgets.QToolButton(self)
            b.setText(glyph)
            icons.set_icon(b, icon)
            b.setCheckable(checkable)
            pytips.tag(b, py)
            b.clicked.connect(fn)
            row.addWidget(b)
            return b

        keymap.tip(btn("jump_start", "⏮", lambda: self._jump("start"), "bpy.ops.screen.frame_jump(end=False)"),
                   "Jump to Start ({timeline.jump_start})")
        keymap.tip(btn("key_prev", "◆◀", lambda: self._jump("prev_key"),
                       "bpy.ops.screen.keyframe_jump(next=False)"), "Previous Keyframe ({timeline.key_prev})")
        keymap.tip(btn("frame_prev", "◀|", lambda: self.step(-1), "bpy.context.scene.frame_current -= 1"),
                   "Previous Frame ({timeline.frame_prev} · {window.frame_prev})")
        self.rev_btn = btn("play_reverse", "◀", lambda: self.toggle_play(reverse=True),
                           "bpy.ops.screen.animation_play(reverse=True)")
        keymap.tip(self.rev_btn, "Play Backwards / Pause ({window.play_reverse})")
        self.play_btn = btn("play", "▶", lambda: self.toggle_play(), "bpy.ops.screen.animation_play()")
        keymap.tip(self.play_btn, "Play / Pause ({window.play})")
        keymap.tip(btn("frame_next", "|▶", lambda: self.step(1), "bpy.context.scene.frame_current += 1"),
                   "Next Frame ({timeline.frame_next} · {window.frame_next})")
        keymap.tip(btn("key_next", "▶◆", lambda: self._jump("next_key"),
                       "bpy.ops.screen.keyframe_jump(next=True)"), "Next Keyframe ({timeline.key_next})")
        keymap.tip(btn("jump_end", "⏭", lambda: self._jump("end"), "bpy.ops.screen.frame_jump(end=True)"),
                   "Jump to End ({timeline.jump_end})")
        self.loop_btn = btn("loop_continuous", "↻", self.cycle_loop_mode,
                            "import qt_shell; qt_shell.api.timeline().set_loop_mode('LOOP')")
        row.addSpacing(12)
        self.auto_key = QtWidgets.QToolButton(self)
        self.auto_key.setText("● Auto Key")
        icons.set_icon(self.auto_key, "record", "Auto Key")
        self.auto_key.setCheckable(True)
        self.auto_key.setToolTip("Auto Keying – changes in the 3D view are keyed automatically "
                                 "(mode: Keying menu)")
        pytips.tag(self.auto_key, "bpy.context.scene.tool_settings.use_keyframe_insert_auto = True")
        self.auto_key.toggled.connect(self._set_auto_key)
        row.addWidget(self.auto_key)
        b = QtWidgets.QToolButton(self)
        b.setText("+◆ Key")
        icons.set_icon(b, "keyframe", "Key")
        pytips.tag(b, "import qt_shell.keying; qt_shell.keying.insert()")
        b.clicked.connect(self.insert_key)
        keymap.tip(b, "Insert location / rotation / scale keys for the selection – selected bones in "
                      "Pose mode, selected objects otherwise ({view3d.insert_key} in the viewport)")
        row.addWidget(b)
        b = QtWidgets.QToolButton(self)
        b.setText("−◆")
        icons.set_icon(b, "key_delete")
        pytips.tag(b, "import qt_shell.keying; qt_shell.keying.delete()")
        b.clicked.connect(self.delete_key)
        keymap.tip(b, "Delete the keys of the selection on the current frame ({view3d.delete_key} in the "
                      "viewport)")
        row.addWidget(b)
        row.addSpacing(12)
        self.cache_btn = QtWidgets.QToolButton(self)
        self.cache_btn.setText("Cache")
        self.cache_btn.setCheckable(True)
        self.cache_btn.setChecked(playcache.enabled())
        self.cache_btn.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        self.cache_btn.setToolTip("Cached playback (like Maya): frames drawn once are kept and played back in "
                                  "real time; the green line in the timeline shows the cached frames. "
                                  "Any change to the scene or the view drops the cache.")
        pytips.tag(self.cache_btn, 'import qt_shell.playcache as pc; pc.set_enabled(True)')
        self.cache_btn.toggled.connect(self._set_cache)
        cm = QtWidgets.QMenu(self.cache_btn)
        cm.aboutToShow.connect(lambda: self._fill_cache_menu(cm))
        self.cache_btn.setMenu(cm)
        row.addWidget(self.cache_btn)
        self.auto_cache_btn = QtWidgets.QToolButton(self)
        self.auto_cache_btn.setText("Auto")
        self.auto_cache_btn.setCheckable(True)
        self.auto_cache_btn.setChecked(playcache.auto_enabled())
        self.auto_cache_btn.setToolTip("Background caching (like Maya): while you don't work in the scene, the "
                                       "frames of the scene range are cached automatically – no playback needed. "
                                       "Your view and current frame don't change.")
        pytips.tag(self.auto_cache_btn, 'import qt_shell.playcache as pc; pc.set_auto_enabled(True)')
        self.auto_cache_btn.toggled.connect(self._set_auto_cache)
        row.addWidget(self.auto_cache_btn)
        self._ac_key = None
        self._ac_since = 0.0
        self._ac_timer = QtCore.QTimer(self)
        self._ac_timer.setInterval(40)
        self._ac_timer.timeout.connect(self._auto_cache_step)
        self._ac_timer.start()
        row.addStretch(1)
        row.addWidget(QtWidgets.QLabel("Frame", self))
        self.cur = self._spin(-1048574, 1048574)
        pytips.tag(self.cur, "bpy.context.scene.frame_set(1)   # bpy.context.scene.frame_current")
        self.cur.valueChanged.connect(lambda v: (bpy.context.scene.frame_set(int(v)), self.bar.update(),
                                                 self.slider.update()))
        row.addWidget(self.cur)
        self.preview_btn = btn("preview_range", "◷", lambda on: self.set_preview_range(on),
                               "bpy.context.scene.use_preview_range = True", checkable=True)
        keymap.tip(self.preview_btn, "Preview Range – play / show only a part of the scene range (the render "
                                     "keeps the scene range); Start / End then edit it. Set from the selected "
                                     "keys: {timeline.preview_set}, clear: {timeline.preview_clear}")
        self.start_lbl = QtWidgets.QLabel("Start", self)
        row.addWidget(self.start_lbl)
        self.start = self._spin(-1048574, 1048574)
        pytips.tag(self.start, "bpy.context.scene.frame_start   # frame_preview_start with the preview range")
        self.start.valueChanged.connect(lambda v: self._set_range("start", v))
        self.start.editingFinished.connect(lambda: bridge.undo_push("Frame Range"))
        row.addWidget(self.start)
        self.end_lbl = QtWidgets.QLabel("End", self)
        row.addWidget(self.end_lbl)
        self.end = self._spin(-1048574, 1048574)
        pytips.tag(self.end, "bpy.context.scene.frame_end   # frame_preview_end with the preview range")
        self.end.valueChanged.connect(lambda v: self._set_range("end", v))
        self.end.editingFinished.connect(lambda: bridge.undo_push("Frame Range"))
        row.addWidget(self.end)
        row.addSpacing(6)
        self.fps_btn = QtWidgets.QToolButton(self)
        self.fps_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.fps_btn.setToolTip("Frame Rate – playback speed (frames per second), the same setting as "
                                "Properties → Output → Format → Frame Rate")
        pytips.tag(self.fps_btn, "bpy.context.scene.render.fps = 24; bpy.context.scene.render.fps_base = 1.0")
        fm = QtWidgets.QMenu(self.fps_btn)
        fm.setToolTipsVisible(True)
        fm.aboutToShow.connect(lambda: self._fill_fps_menu(fm))
        self.fps_btn.setMenu(fm)
        row.addWidget(self.fps_btn)
        lay.addLayout(row)
        self.bar = TimeBar(self)
        try:
            from . import bluepencil, gizmo
            bluepencil.settings().changed.connect(self.bar.update)
            gizmo.tool_state(hub).changed.connect(self.bar.update)     # Blue Pencil ticks follow the tool
        except Exception as ex:
            bridge.log(f"Timeline: {ex}", "WARNING")
        lay.addWidget(self.bar, 1)
        self.slider = RangeSlider(self.bar, self)
        lay.addWidget(self.slider)
        self.bar.view_changed.connect(self.slider.update)
        self._update_loop_btn()

        hub.frame_changed.connect(lambda _f: self.sync())
        hub.selection_changed.connect(self.sync)
        hub.data_changed.connect(self.sync)
        hub.file_loaded.connect(self._file_loaded)
        self.sync()

    def _file_loaded(self):
        self.bar.view = None
        self.bar.sel.clear()
        self.sync()

    # ------------------------------------------------------------ cached playback
    def _views(self):
        area = getattr(self.hub, "viewport_area", None)
        if area is not None:
            return area.visible_views()
        vp = getattr(self.hub, "viewport", None)
        return [vp] if vp is not None and vp.isVisible() else []

    def cached_frames(self):
        try:
            if not playcache.enabled():
                return set()
            if playcache.geometry_mode():
                return geocache.cached_frames()
            return playcache.cached_frames(self._views())
        except Exception:
            return set()

    def _cache_ready(self, views, f):
        if not playcache.enabled() or not views:
            return False
        if playcache.geometry_mode():
            return geocache.has(f) and all(v.geo_cache_usable() for v in views)
        return playcache.ready(views, f)

    def _cache_has(self, views, f):
        """Is frame f stored (independent of whether the views can show it right now)?"""
        if playcache.geometry_mode():
            return geocache.has(f)
        return playcache.ready(views, f)

    def _cache_show(self, views, f):
        if playcache.geometry_mode():
            return all([v.show_geo(f) for v in views])
        return all([v.show_cached(f) for v in views])

    def _cache_store(self, views, f):
        """Stores the scene's current frame f (after frame_set). Images need a render, geometry doesn't."""
        if not playcache.enabled():
            return
        if playcache.geometry_mode():
            geocache.capture(f)
        else:
            for v in views:
                v.render_frame()

    def shown_frame(self):
        f = getattr(self.hub, "display_frame", None)
        return bpy.context.scene.frame_current if f is None else f

    def _set_cache(self, on):
        playcache.set_enabled(on)
        self.bar.update()

    def _set_auto_cache(self, on):
        playcache.set_auto_enabled(on)
        if on and not playcache.enabled():
            self.cache_btn.setChecked(True)
        self._ac_key = None

    def _auto_cache_step(self):
        """Background caching: renders a few missing frames (≈35 ms of work) when the user is idle,
        then puts the scene back on its frame and the views back on their picture."""
        try:
            if not (playcache.auto_enabled() and playcache.enabled()) or playcache.full():
                return
            if self.is_playing() or bridge.is_rendering() or not self.isVisible():
                return
            app = QtWidgets.QApplication
            if (app.mouseButtons() != QtCore.Qt.NoButton or app.activePopupWidget() is not None
                    or app.activeModalWidget() is not None):
                return
            views = self._views()
            if not views:
                return
            geo = playcache.geometry_mode()
            for v in views:
                if getattr(v, "_modal", None) is not None or v._dirty or v._extra_frames > 0:
                    return                    # the user is transforming / the view isn't drawn yet
                space, _r = v.space()
                if not geo and space is not None and space.shading.type == "RENDERED":
                    return
            # geometry doesn't depend on the camera – only scene edits restart it
            key = (playcache.scene_version(),) if geo else (
                playcache.scene_version(), tuple(playcache.view_signature(v) for v in views))
            now = time.perf_counter()
            if key != self._ac_key:
                self._ac_key = key           # something changed – wait until things settle
                self._ac_since = now
                return
            if now - self._ac_since < 0.6:
                return
            sc = bpy.context.scene
            pkey = (key, sc.frame_current)
            if getattr(self, "_ac_pending_key", None) != pkey:
                self._ac_pending_key = pkey
                self._ac_pending = playcache.pending_edits()
            if self._ac_pending:
                return                         # unkeyed changes – a frame hop would reset them
            keep = sc.frame_current
            ps, pe = play_range(sc)
            rng = list(range(ps, pe + 1))
            if not rng:
                return
            i0 = rng.index(keep) if keep in rng else 0
            missing = [f for f in rng[i0:] + rng[:i0] if not self._cache_has(views, f)]
            if not missing:
                return
            saved = [(v._image, v._img_transparent) for v in views]
            dirty_flag = bridge.Flags.depsgraph
            t0 = time.perf_counter()
            try:
                for f in missing:
                    sc.frame_set(f)
                    self._cache_store(views, f)
                    if playcache.full() or time.perf_counter() - t0 > 0.035:
                        break
            finally:
                sc.frame_set(keep)
                for v, (img, tr) in zip(views, saved):
                    v._image, v._img_transparent = img, tr
                    v._dirty = False
                bridge.Flags.depsgraph = dirty_flag   # frame hops are not edits – no UI refresh storm
            self.bar.update()
        except Exception as ex:
            bridge.log(f"Background caching: {ex}", "WARNING")
            self._ac_since = time.perf_counter() + 5.0

    def _fill_cache_menu(self, m):
        m.clear()
        n = len(self.cached_frames())
        info = m.addAction(f"{n} frame(s) cached · {playcache.used_mb():.0f} MB of "
                           f"{playcache.limit_bytes() // (1024 * 1024)} MB")
        info.setEnabled(False)
        m.addSeparator()
        grp = QtGui.QActionGroup(m)
        for key, text, tip in (
                ("GEOMETRY", "Cache Geometry (camera can move)",
                 "Stores the animated geometry and rig controls; playback draws them from any camera in "
                 "solid shading. Moving the camera keeps the cache."),
                ("IMAGE", "Cache Images (exact look)",
                 "Stores finished viewport pictures – exact look incl. materials, but any camera move "
                 "drops the cache.")):
            act = m.addAction(text)
            act.setCheckable(True)
            act.setChecked(playcache.mode() == key)
            act.setToolTip(tip)
            grp.addAction(act)
            act.triggered.connect(lambda _=False, k=key: (playcache.set_mode(k), self.bar.update()))
        m.addSeparator()
        auto = m.addAction("Background Caching (Auto)")
        auto.setCheckable(True)
        auto.setChecked(playcache.auto_enabled())
        auto.toggled.connect(self.auto_cache_btn.setChecked)
        a = m.addAction("Cache All Frames")
        a.setToolTip("Draws every frame of the scene range once, so the next playback is real time")
        a.triggered.connect(self.cache_all)
        m.addAction("Flush Cache", self.flush_cache)
        lim = m.addMenu("Memory Limit")
        cur = playcache.limit_bytes() // (1024 * 1024)
        for mb in (256, 512, 1024, 2048, 4096, 8192):
            act = lim.addAction(f"{mb} MB" if mb < 1024 else f"{mb // 1024} GB")
            act.setCheckable(True)
            act.setChecked(mb == cur)
            act.triggered.connect(lambda _=False, mb=mb: QtCore.QSettings("QtShell", "QtShell").setValue(
                playcache.KEY_LIMIT, mb))

    def flush_cache(self):
        playcache.flush()
        geocache.flush()
        self.bar.update()

    def cache_all(self):
        """Fills the cache for the play range (scene or preview range (shows progress in the status bar; Esc stops)."""
        if not playcache.enabled():
            self.cache_btn.setChecked(True)
        if self.is_playing():
            self.toggle_play()
        sc = bpy.context.scene
        keep = sc.frame_current
        views = self._views()
        if not views:
            return
        mw = getattr(self.hub, "main_window", None)
        app = QtWidgets.QApplication.instance()
        ps, pe = play_range(sc)
        total = pe - ps + 1
        try:
            for i, f in enumerate(range(ps, pe + 1)):
                if self._cache_has(views, f):
                    continue
                sc.frame_set(f)
                if playcache.geometry_mode():
                    geocache.capture(f)
                else:
                    for v in views:
                        v.render_now()
                self.cur.blockSignals(True)
                self.cur.setValue(f)
                self.cur.blockSignals(False)
                self.bar.update()
                if mw is not None and i % 5 == 0:
                    mw.statusBar().showMessage(f"Caching frame {f} ({i + 1}/{total})…", 2000)
                app.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents)
        finally:
            sc.frame_set(keep)
            for v in views:
                v.render_now()
            self.sync()
            if mw is not None:
                mw.statusBar().showMessage(f"Cached {len(self.cached_frames())} frame(s) "
                                           f"({playcache.used_mb():.0f} MB).", 4000)


    # ------------------------------------------------------------ state → widgets
    def sync(self):
        sc = bpy.context.scene
        shown = self.shown_frame()
        prev = sc.use_preview_range
        a = sc.frame_preview_start if prev else sc.frame_start
        b = sc.frame_preview_end if prev else sc.frame_end
        for w, v in ((self.cur, shown), (self.start, a), (self.end, b)):
            if not (w._editing or w._dragging):
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)
        if self.preview_btn.isChecked() != prev:
            self.preview_btn.blockSignals(True)
            self.preview_btn.setChecked(prev)
            self.preview_btn.blockSignals(False)
        style = "color: #e0913a;" if prev else ""
        for lbl, text in ((self.start_lbl, "Start"), (self.end_lbl, "End")):
            lbl.setStyleSheet(style)
            lbl.setText(text)
        self.auto_key.blockSignals(True)
        self.auto_key.setChecked(sc.tool_settings.use_keyframe_insert_auto)
        self.auto_key.blockSignals(False)
        label = fps_label(sc.render)
        if self.fps_btn.text() != label:
            self.fps_btn.setText(label)
        keys = {}
        for _ob, fc in timeline_curves():
            for kp in fc.keyframe_points:
                f = int(round(kp.co.x))
                t = kp.type
                old = keys.get(f)
                if old is None or _KEY_PRIORITY.index(t if t in _KEY_PRIORITY else "KEYFRAME") < \
                        _KEY_PRIORITY.index(old):
                    keys[f] = t if t in KEY_TYPES else "KEYFRAME"
        self.bar.keys = keys
        if self.bar._drag is None:
            self.bar.sel &= set(keys)
        self.bar.update()
        self.slider.update()

    @staticmethod
    def _spin(lo, hi):
        """Integer field draggable with the mouse (like Blender), ~4 px per frame."""
        s = DragSpin(is_int=True)
        s.setRange(lo, hi)
        s.drag_step = 0.25
        s.setMinimumWidth(theme.px(64))
        return s

    def _set_range(self, which, v):
        sc = bpy.context.scene
        v = int(v)
        if sc.use_preview_range:
            if which == "start":
                sc.frame_preview_start = v
            else:
                sc.frame_preview_end = v
        else:
            setattr(sc, "frame_start" if which == "start" else "frame_end", max(0, v))
        self.bar.update()
        self.slider.update()

    def _set_auto_key(self, on):
        bpy.context.scene.tool_settings.use_keyframe_insert_auto = on

    def status(self, text):
        mw = getattr(self.hub, "main_window", None)
        if mw is not None:
            mw.statusBar().showMessage(text, 3000)

    # ------------------------------------------------------------ preview range
    def set_preview_range(self, on, start=None, end=None):
        """Preview range on / off (Blender's clock button); start / end set it too."""
        sc = bpy.context.scene
        if on and start is None and not sc.use_preview_range and \
                (sc.frame_preview_start, sc.frame_preview_end) == (0, 0):
            start, end = sc.frame_start, sc.frame_end
        sc.use_preview_range = bool(on)
        if start is not None and end is not None:
            # (Blender resets the other end when one is set while the preview range is off – set them after)
            a, b = sorted((int(start), int(end)))
            if not on:
                sc.use_preview_range = True
            sc.frame_preview_start = a
            sc.frame_preview_end = b
            sc.use_preview_range = bool(on)
        bridge.undo_push("Preview Range")
        self.sync()

    def preview_from_selection(self):
        """Ctrl+P: the preview range = the selected keys (two or more), else the visible part."""
        if len(self.bar.sel) >= 2:
            a, b = min(self.bar.sel), max(self.bar.sel)
        else:
            lo, hi = self.bar.view_range()
            a, b = int(round(lo)), int(round(hi))
        self.set_preview_range(True, a, b)
        self.status(f"Preview range {a} – {b}")

    # ------------------------------------------------------------ frame navigation
    def step(self, n):
        if self.is_playing():
            self.toggle_play()
        sc = bpy.context.scene
        sc.frame_set(sc.frame_current + int(n))
        self.bar.follow(sc.frame_current)
        self.sync()

    def _jump(self, where):
        sc = bpy.context.scene
        f = sc.frame_current
        start, end = play_range()
        if where == "start":
            f = start
        elif where == "end":
            f = end
        else:
            keys = sorted(self.bar.keys)
            if where == "prev_key":
                prev = [k for k in keys if k < f]
                f = prev[-1] if prev else f
            else:
                nxt = [k for k in keys if k > f]
                f = nxt[0] if nxt else f
        sc.frame_set(f)
        self.bar.follow(f)
        self.sync()

    def run_action(self, aid):
        """Timeline keymap actions (keys while the time bar has the focus, and the menus)."""
        bar = self.bar
        fn = {
            "timeline.delete_keys": bar.delete_selected,
            "timeline.select_all": bar.select_all,
            "timeline.deselect_all": lambda: bar.sel.clear(),
            "timeline.copy_keys": bar.copy_keys,
            "timeline.paste_keys": bar.paste_keys,
            "timeline.frame_prev": lambda: self.step(-1),
            "timeline.frame_next": lambda: self.step(1),
            "timeline.jump_start": lambda: self._jump("start"),
            "timeline.jump_end": lambda: self._jump("end"),
            "timeline.key_prev": lambda: self._jump("prev_key"),
            "timeline.key_next": lambda: self._jump("next_key"),
            "timeline.frame_all": bar.frame_all,
            "timeline.view_current": bar.view_current,
            "timeline.zoom_in": lambda: bar.zoom(0.8),
            "timeline.zoom_out": lambda: bar.zoom(1.25),
            "timeline.marker_add": bar.add_marker,
            "timeline.marker_rename": bar.rename_marker,
            "timeline.show_seconds": lambda: self.set_show_seconds(not setting("show_seconds", False)),
            "timeline.preview_set": self.preview_from_selection,
            "timeline.preview_clear": lambda: self.set_preview_range(False),
        }.get(aid)
        if fn is not None:
            fn()
            bar.update()

    def set_show_seconds(self, on):
        set_setting("show_seconds", bool(on))
        self.bar.update()

    # ------------------------------------------------------------ loop mode (Maya)
    def set_loop_mode(self, mode):
        """'LOOP' (continuous), 'ONCE' (stop at the end) or 'OSCILLATE' (ping-pong)."""
        mode = str(mode).upper()
        if mode not in [m[0] for m in LOOP_MODES]:
            raise ValueError(f"Unknown loop mode {mode!r} – LOOP, ONCE or OSCILLATE")
        self.loop_mode = mode
        set_setting("loop_mode", mode)
        self._update_loop_btn()

    def cycle_loop_mode(self):
        ids = [m[0] for m in LOOP_MODES]
        self.set_loop_mode(ids[(ids.index(self.loop_mode) + 1) % len(ids)])
        self.status(f"Loop: {dict((m[0], m[1]) for m in LOOP_MODES)[self.loop_mode]}")

    def _update_loop_btn(self):
        info = {m[0]: m for m in LOOP_MODES}[self.loop_mode]
        icons.set_icon(self.loop_btn, info[2])
        self.loop_btn.setToolTip(f"Loop: {info[1]} – {info[3]}\nClick: next mode (Continuous Loop → Play Once → "
                                 "Oscillate)")
        pytips.tag(self.loop_btn, f"import qt_shell; qt_shell.api.timeline().set_loop_mode('{self.loop_mode}')")

    # ------------------------------------------------------------ menus
    def _act(self, m, text, fn, aid=None, py=None, icon=None, checked=None, tip=None):
        label = f"{text}\t{keymap.text(aid)}" if aid and keymap.text(aid) != "—" else text
        a = m.addAction(icons.icon(icon), label) if icon else m.addAction(label)
        if checked is not None:
            a.setCheckable(True)
            a.setChecked(bool(checked))
        if tip:
            a.setToolTip(tip)
        if py:
            pytips.tag(a, py)
        a.triggered.connect(lambda _c=False: fn())
        return a

    def fill_view_menu(self, m):
        m.clear()
        api = "import qt_shell; qt_shell.api.timeline()."
        self._act(m, "Show Seconds", lambda: self.set_show_seconds(not setting("show_seconds", False)),
                  "timeline.show_seconds", api + "set_show_seconds(True)", checked=setting("show_seconds", False),
                  tip="Time in seconds+frames instead of frames")
        self._act(m, "Show Markers", lambda: (set_setting("show_markers", not setting("show_markers", True)),
                                              self.bar.update()),
                  checked=setting("show_markers", True))
        self._act(m, "Follow Current Frame", lambda: set_setting("follow", not setting("follow", True)),
                  checked=setting("follow", True), tip="While playing, the view moves along with the frame")
        m.addSeparator()
        self._act(m, "Frame All", self.bar.frame_all, "timeline.frame_all", api + "frame_all()",
                  tip="The scene (or preview) range fills the timeline")
        self._act(m, "Go to Current Frame", self.bar.view_current, "timeline.view_current",
                  api + "bar.view_current()")
        self._act(m, "Zoom In", lambda: self.bar.zoom(0.8), "timeline.zoom_in", api + "zoom(0.8)")
        self._act(m, "Zoom Out", lambda: self.bar.zoom(1.25), "timeline.zoom_out", api + "zoom(1.25)")
        m.addSeparator()
        self._act(m, "Set Preview Range", self.preview_from_selection, "timeline.preview_set",
                  api + "set_preview_range(True, 10, 50)", tip="From the selected keys, else the visible range")
        self._act(m, "Clear Preview Range", lambda: self.set_preview_range(False), "timeline.preview_clear",
                  api + "set_preview_range(False)")

    def fill_marker_menu(self, m):
        m.clear()
        sc = bpy.context.scene
        self._act(m, "Add Marker", self.bar.add_marker, "timeline.marker_add",
                  "bpy.context.scene.timeline_markers.new('F_01', frame=1)", "marker")
        has_sel = any(x.select for x in sc.timeline_markers)
        a = self._act(m, "Rename Marker…", self.bar.rename_marker, "timeline.marker_rename")
        a.setEnabled(has_sel)
        a = self._act(m, "Delete Selected Markers", self._delete_markers,
                      py="bpy.context.scene.timeline_markers.remove(marker)")
        a.setEnabled(has_sel)
        a = self._act(m, "Move Selected to Current Frame", self._markers_to_frame)
        a.setEnabled(has_sel)
        m.addSeparator()
        self._act(m, "Jump to Next Marker", lambda: self.bar.jump_marker(1))
        self._act(m, "Jump to Previous Marker", lambda: self.bar.jump_marker(-1))

    def _delete_markers(self):
        sc = bpy.context.scene
        ms = [x for x in sc.timeline_markers if x.select]
        for x in ms:
            sc.timeline_markers.remove(x)
        if ms:
            bridge.undo_push("Delete Markers")
        self.bar.update()

    def _markers_to_frame(self):
        sc = bpy.context.scene
        for x in sc.timeline_markers:
            if x.select:
                x.frame = sc.frame_current
        bridge.undo_push("Move Markers")
        self.bar.update()

    def fill_playback_menu(self, m):
        m.clear()
        sc = bpy.context.scene
        title = m.addAction("Loop")
        title.setEnabled(False)
        for mid, name, icon, tip in LOOP_MODES:
            self._act(m, name, lambda x=mid: self.set_loop_mode(x), icon=icon, checked=self.loop_mode == mid,
                      tip=tip, py=f"import qt_shell; qt_shell.api.timeline().set_loop_mode('{mid}')")
        m.addSeparator()
        title = m.addAction("Sync")
        title.setEnabled(False)
        for sid, name, tip in (("NONE", "Play Every Frame", "Never skips a frame (may play slower)"),
                               ("FRAME_DROP", "Frame Dropping", "Keeps real time, skips frames when needed"),
                               ("AUDIO_SYNC", "Sync to Audio", "Keeps real time like the sound")):
            self._act(m, name, lambda x=sid: setattr(bpy.context.scene, "sync_mode", x),
                      checked=getattr(sc, "sync_mode", "NONE") == sid, tip=tip,
                      py=f"bpy.context.scene.sync_mode = '{sid}'")
        m.addSeparator()
        self._act(m, "Follow Current Frame", lambda: set_setting("follow", not setting("follow", True)),
                  checked=setting("follow", True))
        self._act(m, "Mute Audio", lambda: setattr(bpy.context.scene, "use_audio", not sc.use_audio),
                  checked=sc.use_audio, py="bpy.context.scene.use_audio = True")
        self._act(m, "Audio Scrubbing", lambda: setattr(bpy.context.scene, "use_audio_scrub",
                                                        not sc.use_audio_scrub),
                  checked=sc.use_audio_scrub, py="bpy.context.scene.use_audio_scrub = True")
        m.addSeparator()
        self._act(m, "Play Backwards", lambda: self.toggle_play(reverse=True), "window.play_reverse", icon="play_reverse")

    def fill_keying_menu(self, m):
        m.clear()
        ts = bpy.context.scene.tool_settings
        title = m.addAction("Auto Keying")
        title.setEnabled(False)
        self._act(m, "Auto Keying", lambda: setattr(ts, "use_keyframe_insert_auto",
                                                    not ts.use_keyframe_insert_auto),
                  checked=ts.use_keyframe_insert_auto, icon="record",
                  py="bpy.context.scene.tool_settings.use_keyframe_insert_auto = True")
        for mid, name in (("ADD_REPLACE_KEYS", "Add & Replace"), ("REPLACE_KEYS", "Replace")):
            self._act(m, f"   {name}", lambda x=mid: setattr(ts, "auto_keying_mode", x),
                      checked=ts.auto_keying_mode == mid,
                      py=f"bpy.context.scene.tool_settings.auto_keying_mode = '{mid}'",
                      tip="Add & Replace: new keys and changed ones · Replace: only keys that exist")
        m.addSeparator()
        sub = m.addMenu("New Keyframe Type")
        for kid, (name, *_r) in KEY_TYPES.items():
            if kid == "GENERATED":
                continue
            self._act(sub, name, lambda x=kid: setattr(ts, "keyframe_type", x), checked=ts.keyframe_type == kid,
                      py=f"bpy.context.scene.tool_settings.keyframe_type = '{kid}'")
        m.addSeparator()
        self._act(m, "Insert Keyframe", self.insert_key, "view3d.insert_key", icon="keyframe")
        self._act(m, "Delete Keyframe (current frame)", self.delete_key, "view3d.delete_key", icon="key_delete")
        m.addSeparator()
        sel = m.addMenu("Selected Keys")
        self.fill_key_menu(sel, short=True)

    def fill_key_menu(self, m, short=False):
        bar = self.bar
        has = bool(bar.sel)
        if not short:
            self._act(m, "Insert Keyframe", self.insert_key, "view3d.insert_key", icon="keyframe")
        a = self._act(m, "Delete Selected Keys", bar.delete_selected, "timeline.delete_keys")
        a.setEnabled(has)
        a = self._act(m, "Copy Keys", bar.copy_keys, "timeline.copy_keys")
        a.setEnabled(has)
        a = self._act(m, "Paste Keys", bar.paste_keys, "timeline.paste_keys",
                      tip="At the current frame")
        a.setEnabled(bool(_COPY))
        m.addSeparator()
        sub = m.addMenu("Interpolation")
        sub.setEnabled(has)
        for iid, name in INTERPOLATIONS:
            self._act(sub, name, lambda x=iid: bar.set_interpolation(x),
                      py=f"keyframe_point.interpolation = '{iid}'")
        sub = m.addMenu("Keyframe Type")
        sub.setEnabled(has)
        for kid, (name, *_r) in KEY_TYPES.items():
            if kid != "GENERATED":
                self._act(sub, name, lambda x=kid: bar.set_key_type(x), py=f"keyframe_point.type = '{kid}'")
        a = self._act(m, "Snap to Nearest Frame", bar.snap_keys)
        a.setEnabled(has)
        m.addSeparator()
        self._act(m, "Select All", bar.select_all, "timeline.select_all")
        self._act(m, "Deselect All", lambda: (bar.sel.clear(), bar.update()), "timeline.deselect_all")
        if short:
            return
        m.addSeparator()
        self._act(m, "Set Preview Range", self.preview_from_selection, "timeline.preview_set")
        self._act(m, "Add Marker", bar.add_marker, "timeline.marker_add", icon="marker")
        m.addSeparator()
        self._act(m, "Frame All", bar.frame_all, "timeline.frame_all")

    # ------------------------------------------------------------ frame rate
    def _fill_fps_menu(self, m):
        m.clear()
        r = bpy.context.scene.render
        grp = QtGui.QActionGroup(m)
        found = False
        for label, fps, base in FPS_PRESETS:
            a = m.addAction(f"{label} fps")
            a.setCheckable(True)
            on = r.fps == fps and abs((r.fps_base or 1.0) - base) < 1e-4
            found |= on
            a.setChecked(on)
            grp.addAction(a)
            pytips.tag(a, f"bpy.context.scene.render.fps = {fps}; bpy.context.scene.render.fps_base = {base}")
            a.triggered.connect(lambda _c=False, f=fps, b=base: self.set_fps(f, b))
        m.addSeparator()
        a = m.addAction("Custom…" if found else f"Custom ({fps_label(r)})…")
        a.setCheckable(True)
        a.setChecked(not found)
        grp.addAction(a)
        a.setToolTip("Any frame rate: FPS and Base (fps / base = frames per second)")
        a.triggered.connect(self._custom_fps)

    def _custom_fps(self):
        r = bpy.context.scene.render
        v, ok = QtWidgets.QInputDialog.getDouble(self, "Custom Frame Rate", "Frames per second:",
                                                 r.fps / (r.fps_base or 1.0), 0.01, 1000.0, 3)
        if not ok:
            return
        fps = max(1, round(v))
        self.set_fps(fps, fps / v)

    def set_fps(self, fps, base=1.0):
        """Scene frame rate (Properties → Output → Frame Rate): fps / base frames per second."""
        r = bpy.context.scene.render
        r.fps = int(fps)
        r.fps_base = float(base)
        bridge.undo_push("Frame Rate")
        if self.is_playing():                 # keep playing at the new speed from the shown frame
            self._restart_clock(getattr(self, "_play_frame", bpy.context.scene.frame_current))
        mw = getattr(self.hub, "main_window", None)
        props = getattr(mw, "properties", None)
        if props is not None:
            try:
                props.refresh(force=True)     # Output → Frame Rate shows the new value
            except Exception:
                pass
        self.status(f"Frame rate: {fps_label(r)}")
        self.sync()

    # ------------------------------------------------------------ playback
    def _set_playing(self, on):
        was = bool(getattr(self.hub, "playing", False))
        self.hub.playing = on
        vp = getattr(self.hub, "viewport_area", None)
        if vp is None:
            vp = getattr(self.hub, "viewport", None)
        if vp is not None:
            vp.playback_changed(on)
        if was != bool(on):
            try:
                from . import api
                api.emit("playback", bool(on))
            except Exception:
                pass

    def is_playing(self):
        return bool(getattr(self.hub, "playing", False))

    def _end_cached_display(self):
        """After cached playback the scene is moved to the frame that was shown last."""
        f = getattr(self.hub, "display_frame", None)
        self.hub.display_frame = None
        sc = bpy.context.scene
        if f is not None and f != sc.frame_current:
            sc.frame_set(f)
            vp = getattr(self.hub, "viewport_area", None) or getattr(self.hub, "viewport", None)
            if vp is not None:
                vp.render_now()

    def _update_play_buttons(self):
        playing = self.is_playing()
        fwd = playing and self._dir > 0
        rev = playing and self._dir < 0
        if not icons.set_icon(self.play_btn, "pause" if fwd else "play"):
            self.play_btn.setText("⏸" if fwd else "▶")
        if not icons.set_icon(self.rev_btn, "pause" if rev else "play_reverse"):
            self.rev_btn.setText("⏸" if rev else "◀")

    def _restart_clock(self, frame):
        self._t0 = time.perf_counter()
        self._f0 = frame
        self._next = self._t0

    def toggle_play(self, reverse=False):
        """Play / pause (Space); reverse=True plays backwards (Shift+Ctrl+Space). Pressing the other direction
        while playing turns around."""
        d = -1 if reverse else 1
        if self.is_playing():
            if d != self._dir:                    # turn around without stopping
                self._dir = d
                self._restart_clock(getattr(self, "_play_frame", bpy.context.scene.frame_current))
                self._update_play_buttons()
                return
            self._set_playing(False)
            self._end_cached_display()
            self._update_play_buttons()
            self.sync()
            return
        sc = bpy.context.scene
        self.hub.display_frame = None
        self._dir = d
        start, end = play_range()
        f = sc.frame_current
        if self.loop_mode == "ONCE" and ((d > 0 and f >= end) or (d < 0 and f <= start)):
            f = start if d > 0 else end             # Play Once from the end: start over
            sc.frame_set(f)
        self._play_frame = f
        self._restart_clock(f)
        self._set_playing(True)
        self._update_play_buttons()

    def play(self, reverse=False):
        if not self.is_playing() or self._dir != (-1 if reverse else 1):
            self.toggle_play(reverse)

    def _fps(self):
        r = bpy.context.scene.render
        return max(r.fps / (r.fps_base or 1.0), 0.1)

    def _next_frame(self, shown):
        """The next frame of 'Play Every Frame' playback (None = Play Once has finished)."""
        start, end = play_range()
        f = shown + self._dir
        if start <= f <= end:
            return f
        if self.loop_mode == "ONCE":
            return None
        if self.loop_mode == "OSCILLATE" and end > start:
            self._dir = -self._dir
            self._update_play_buttons()
            return shown + self._dir
        return start if self._dir > 0 else end

    def _frame_at(self, n):
        """Frame n frames after the clock start (real-time playback); None = Play Once has finished."""
        start, end = play_range()
        length = max(end - start + 1, 1)
        p = (self._f0 - start) + self._dir * n
        if self.loop_mode == "ONCE":
            if p < 0 or p > length - 1:
                return None
            return start + p
        if self.loop_mode == "OSCILLATE" and length > 1:
            per = 2 * (length - 1)
            q = p % per
            return start + (q if q < length else per - q)
        return start + p % length

    def playback_tick(self):
        """Called from the event pump while playing: advances the frame when it is due and redraws the
        viewport right away. Follows the scene's Sync mode like Blender: 'Play Every Frame' never skips
        frames, 'Frame Dropping' / 'Sync to Audio' keep real time; loop mode and direction like Maya."""
        sc = bpy.context.scene
        fps = self._fps()
        period = 1.0 / fps
        now = time.perf_counter()
        wait = self._next - now
        if wait > 0.006:
            return                       # not due yet – let Blender and Qt handle events meanwhile
        if wait > 0:
            time.sleep(wait)             # short precise wait for smooth frame pacing
            now = time.perf_counter()
        shown = getattr(self, "_play_frame", sc.frame_current)
        if getattr(sc, "sync_mode", "NONE") == "NONE":
            f = self._next_frame(shown)
            self._next += period
            if self._next < now - 4 * period:      # far behind → don't try to catch up in a burst
                self._next = now + period
        else:
            n = int((now - self._t0) * fps)
            f = self._frame_at(n)
            self._next = self._t0 + (n + 1) / fps
            if f == shown:
                return
        if f is None:                    # Play Once: stop on the last frame
            QtCore.QTimer.singleShot(0, lambda: self.is_playing() and self.toggle_play(self._dir < 0))
            return
        self._play_frame = f
        views = self._views()
        if self._cache_ready(views, f) and self._cache_show(views, f):
            # cached playback: draw from the cache, the scene stays where it is (no evaluation)
            self.hub.display_frame = f
        else:
            self.hub.display_frame = None
            sc.frame_set(f)
            vp = getattr(self.hub, "viewport_area", None)
            if vp is None:
                vp = getattr(self.hub, "viewport", None)
            if vp is not None:
                vp.render_now()        # every visible view (image mode stores the frames here)
            if playcache.enabled() and playcache.geometry_mode():
                geocache.capture(f)
        self.cur.blockSignals(True)
        self.cur.setValue(f)
        self.cur.blockSignals(False)
        if setting("follow", True):
            self.bar.follow(f)
        self.bar.update()
        self.slider.update()

    # ------------------------------------------------------------ keys
    def insert_key(self):
        from . import keying
        if keying.insert():                  # selected bones in Pose mode, selected objects otherwise
            bridge.undo_push("Insert Keyframe")
        self.sync()

    def delete_key(self):
        from . import keying
        if keying.delete():
            bridge.undo_push("Delete Keyframe")
        self.sync()

    def stop(self):
        self._set_playing(False)
        self._end_cached_display()
        self._update_play_buttons()

    # ------------------------------------------------------------ API helpers
    def view_range(self):
        """(first, last) visible frame of the time bar."""
        return self.bar.view_range()

    def set_view_range(self, first, last):
        self.bar.set_view(first, last)

    def frame_all(self):
        self.bar.frame_all()

    def zoom(self, factor):
        """factor < 1 zooms in, > 1 out (around the middle)."""
        self.bar.zoom(float(factor))

    def selected_keys(self):
        return sorted(self.bar.sel)

    def select_keys(self, frames):
        self.bar.sel = {int(f) for f in frames} & set(self.bar.keys)
        self.bar.update()

    def move_selected_keys(self, delta):
        """Moves the selected keys by delta frames (like dragging them)."""
        if not self.bar.sel:
            return 0
        k = min(self.bar.sel)
        self.bar._start_drag(k)
        self.bar._apply_drag(int(delta))
        self.bar._end_drag()
        return len(self.bar.sel)

    def add_marker(self, name=None, frame=None):
        return self.bar.add_marker(name, frame)

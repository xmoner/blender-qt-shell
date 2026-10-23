"""Timeline: playback, frame range, frame rate, keyframes of the selection.

Keys (like Blender's Timeline): the diamonds are the keys of the selected objects (selected bones in Pose
mode). Click a key to select it (Shift: add / remove), drag a key to move the selected keys by whole frames
(a key landing on another key of the same curve replaces it), Shift + drag on empty space selects the keys
in a frame range, {timeline.select_all} selects all, {timeline.delete_keys} deletes the selected keys.
Esc / right click while dragging cancels. A click on empty space moves the current frame (scrub).

Frame rate: the fps button sets Blender's scene frame rate (Properties → Output → Frame Rate) – the same
presets as Blender (23.98 … 240) and Custom.
"""
import time

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, geocache, keymap, playcache, theme
from . import icons
from . import pytips
from .rna_widgets import DragSpin


def _runs(frames):
    """[(first, last)] of consecutive frames."""
    out = []
    for f in frames:
        if out and f == out[-1][1] + 1:
            out[-1][1] = f
        else:
            out.append([f, f])
    return out


# Blender's frame rate presets: label → (fps, fps_base)
FPS_PRESETS = [("23.98", 24, 1.001), ("24", 24, 1.0), ("25", 25, 1.0), ("29.97", 30, 1.001), ("30", 30, 1.0),
               ("50", 50, 1.0), ("59.94", 60, 1.001), ("60", 60, 1.0), ("120", 120, 1.0), ("240", 240, 1.0)]


def fps_label(render=None):
    r = render or bpy.context.scene.render
    base = r.fps_base or 1.0
    if abs(base - 1.0) < 1e-6:
        return f"{r.fps} fps"
    v = r.fps / base
    return f"{v:.2f} fps" if abs(v - round(v)) > 1e-3 else f"{round(v)} fps"


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


class TimeBar(QtWidgets.QWidget):
    def __init__(self, timeline):
        super().__init__()
        self.tl = timeline
        self.setMinimumHeight(theme.px(46))
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.keys = []
        self.sel = set()          # selected key frames
        self._drag = None         # moving keys: {"start", "delta", "points", "sel"}
        self._range_sel = None    # Shift + drag on empty space: (x0, x1)
        self._scrubbing = False
        self._hover = None
        keymap.tip(self, "Click a key to select it (Shift: add), drag keys to move them, Shift + drag on empty "
                         "space: select a range · {timeline.select_all}: select all · {timeline.delete_keys}: "
                         "delete the selected keys · click elsewhere: set the frame")

    # --- keys
    def key_y(self):
        return self.height() * 0.65

    def key_at(self, pos):
        if abs(pos.y() - self.key_y()) > theme.px(9):
            return None
        best = None
        for k in self.keys:
            d = abs(self.frame_to_x(k) - pos.x())
            if d <= theme.px(7) and (best is None or d < best[0]):
                best = (d, k)
        return best[1] if best else None

    def _start_drag(self, frame):
        pts = []
        for ob, fc in timeline_curves():
            for kp in fc.keyframe_points:
                if int(round(kp.co.x)) in self.sel:
                    pts.append((ob, fc, kp, kp.co.x, kp.handle_left.x, kp.handle_right.x))
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
        if not self.sel:
            return 0
        n = 0
        for ob, fc in timeline_curves():
            for kp in reversed(list(fc.keyframe_points)):
                if int(round(kp.co.x)) in self.sel:
                    fc.keyframe_points.remove(kp, fast=True)
                    n += 1
            fc.update()
            ob.update_tag()
        self.sel.clear()
        if n:
            _reevaluate()
            bridge.undo_push("Delete Keyframes")
            self.tl.status(f"Deleted {n} key{'s' if n != 1 else ''}")
        self.tl.sync()
        return n

    def select_all(self):
        self.sel = set() if self.sel >= set(self.keys) and self.keys else set(self.keys)
        self.update()

    def _range(self):
        sc = bpy.context.scene
        start, end = sc.frame_start, sc.frame_end
        pad = max(2, (end - start) // 20)
        return start - pad, end + pad

    def frame_to_x(self, f):
        lo, hi = self._range()
        return 10 + (f - lo) / max(hi - lo, 1) * (self.width() - 20)

    def x_to_frame(self, x):
        lo, hi = self._range()
        return round(lo + (x - 10) / max(self.width() - 20, 1) * (hi - lo))

    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#232323"))
        sc = bpy.context.scene
        lo, hi = self._range()
        # active range
        x0, x1 = self.frame_to_x(sc.frame_start), self.frame_to_x(sc.frame_end)
        p.fillRect(QtCore.QRectF(x0, 0, x1 - x0, self.height()), QtGui.QColor("#2c2c2c"))
        span = hi - lo
        step = 1
        for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
            if span / s <= self.width() / 45:
                step = s
                break
        f = p.font()
        f.setPixelSize(theme.fs(10))
        p.setFont(f)
        first = (lo // step) * step
        for fr in range(int(first), int(hi) + 1, step):
            x = self.frame_to_x(fr)
            p.setPen(QtGui.QColor("#3a3a3a"))
            p.drawLine(QtCore.QPointF(x, 14), QtCore.QPointF(x, self.height()))
            p.setPen(QtGui.QColor("#9a9a9a"))
            p.drawText(QtCore.QPointF(x + 2, 11), str(fr))
        # cached frames (cached playback) – a green line along the bottom, like Maya's cache bar
        cached = self.tl.cached_frames()
        if cached:
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor("#4caf50"))
            hb = max(3, theme.px(4))
            half = max(self.frame_to_x(1) - self.frame_to_x(0), 1.0) / 2
            for a, b in _runs(sorted(cached)):
                xa, xb = self.frame_to_x(a) - half, self.frame_to_x(b) + half
                p.drawRect(QtCore.QRectF(xa, self.height() - hb, xb - xa, hb))
        # keys
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        y = self.key_y()
        if self._range_sel is not None:
            a, b = sorted(self._range_sel)
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1, QtCore.Qt.DashLine))
            p.setBrush(QtGui.QColor(255, 255, 255, 25))
            p.drawRect(QtCore.QRectF(a, 14, b - a, self.height() - 18))
        for k in self.keys:
            x = self.frame_to_x(k)
            r = 6 if (k in self.sel or k == self._hover) else 5
            poly = QtGui.QPolygonF([QtCore.QPointF(x, y - r), QtCore.QPointF(x + r, y),
                                    QtCore.QPointF(x, y + r), QtCore.QPointF(x - r, y)])
            p.setPen(QtGui.QColor("#000"))
            p.setBrush(QtGui.QColor("#ffa13d" if k in self.sel else (
                "#ffffff" if k == self._hover else "#d0d0d0")))
            p.drawPolygon(poly)
        if self._drag is not None and self._drag["delta"]:
            f = p.font()
            f.setPixelSize(theme.fs(11))
            p.setFont(f)
            p.setPen(QtGui.QColor("#ffa13d"))
            k = min(self.sel) if self.sel else 0
            p.drawText(QtCore.QPointF(self.frame_to_x(k) + 8, y - 8), f"{self._drag['delta']:+d}")
        # current frame (the cached frame being shown during cached playback)
        x = self.frame_to_x(self.tl.shown_frame())
        p.setPen(QtGui.QPen(QtGui.QColor("#4772b3"), 2))
        p.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, self.height()))
        p.end()

    def mousePressEvent(self, ev):
        pos = ev.position()
        if self._drag is not None:            # right click while moving: cancel
            self._end_drag(cancel=ev.button() != QtCore.Qt.LeftButton)
            self.update()
            return
        if ev.button() != QtCore.Qt.LeftButton:
            return
        shift = bool(ev.modifiers() & QtCore.Qt.ShiftModifier)
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

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._drag is not None:
            self._apply_drag(self.x_to_frame(pos.x()) - self._drag["start"])
            self.update()
        elif self._range_sel is not None:
            self._range_sel = (self._range_sel[0], pos.x())
            self.update()
        elif self._scrubbing and ev.buttons() & QtCore.Qt.LeftButton:
            self._scrub(pos.x())
        else:
            h = self.key_at(pos)
            if h != self._hover:
                self._hover = h
                self.setCursor(QtCore.Qt.SizeHorCursor if h is not None else QtCore.Qt.ArrowCursor)
                self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() != QtCore.Qt.LeftButton:
            return
        if self._drag is not None:
            self._end_drag()
        elif self._range_sel is not None:
            a, b = sorted(self._range_sel)
            self._range_sel = None
            self.sel |= {k for k in self.keys if a <= self.frame_to_x(k) <= b}
        self._scrubbing = False
        self.update()

    def keyPressEvent(self, ev):
        names = keymap.event_names(ev)
        if self._drag is not None and ev.key() == QtCore.Qt.Key_Escape:
            self._end_drag(cancel=True)
        elif keymap.hit("timeline.delete_keys", ev, names):
            self.delete_selected()
        elif keymap.hit("timeline.select_all", ev, names):
            self.select_all()
        elif keymap.hit("timeline.deselect_all", ev, names):
            self.sel.clear()
        else:
            super().keyPressEvent(ev)
            return
        self.update()
        ev.accept()

    def event(self, ev):
        # the Timeline's keys win over window shortcuts while it has the focus
        if ev.type() == QtCore.QEvent.ShortcutOverride:
            names = keymap.event_names(ev)
            if any(keymap.hit(a, ev, names) for a in ("timeline.delete_keys", "timeline.select_all",
                                                      "timeline.deselect_all")) or (
                    self._drag is not None and ev.key() == QtCore.Qt.Key_Escape):
                ev.accept()
                return True
        return super().event(ev)

    def _scrub(self, x):
        bpy.context.scene.frame_set(self.x_to_frame(x))
        self.tl.sync()


class Timeline(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(2)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(3)

        glyph_icons = {"⏮": ("jump_start", None), "◆◀": ("key_prev", None), "▶": ("play", None),
                       "▶◆": ("key_next", None), "⏭": ("jump_end", None), "+◆ Key": ("keyframe", "Key"),
                       "−◆": ("key_delete", None)}

        def btn(text, tip, fn, py=None):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            if text in glyph_icons:
                icons.set_icon(b, *glyph_icons[text])
            pytips.tag(b, py)
            b.clicked.connect(fn)
            row.addWidget(b)
            return b

        btn("⏮", "Jump to Start", lambda: self._jump("start"), "bpy.ops.screen.frame_jump(end=False)")
        btn("◆◀", "Previous Keyframe", lambda: self._jump("prev_key"), "bpy.ops.screen.keyframe_jump(next=False)")
        self.play_btn = btn("▶", "", self.toggle_play, "bpy.ops.screen.animation_play()")
        from . import keymap
        keymap.tip(self.play_btn, "Play / Pause ({window.play})")
        btn("▶◆", "Next Keyframe", lambda: self._jump("next_key"), "bpy.ops.screen.keyframe_jump(next=True)")
        btn("⏭", "Jump to End", lambda: self._jump("end"), "bpy.ops.screen.frame_jump(end=True)")
        row.addSpacing(12)
        self.auto_key = QtWidgets.QToolButton()
        self.auto_key.setText("● Auto Key")
        icons.set_icon(self.auto_key, "record", "Auto Key")
        self.auto_key.setCheckable(True)
        pytips.tag(self.auto_key, "bpy.context.scene.tool_settings.use_keyframe_insert_auto = True")
        self.auto_key.toggled.connect(self._set_auto_key)
        row.addWidget(self.auto_key)
        keymap.tip(btn("+◆ Key", "", self.insert_key, "import qt_shell.keying; qt_shell.keying.insert()"),
                   "Insert location / rotation / scale keys for the selection – selected bones in "
                   "Pose mode, selected objects otherwise ({view3d.insert_key} in the viewport)")
        keymap.tip(btn("−◆", "", self.delete_key, "import qt_shell.keying; qt_shell.keying.delete()"),
                   "Delete the keys of the selection on the current frame ({view3d.delete_key} in the viewport)")
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
        row.addWidget(QtWidgets.QLabel("Frame"))
        self.cur = self._spin(-1048574, 1048574)
        pytips.tag(self.cur, "bpy.context.scene.frame_set(1)   # bpy.context.scene.frame_current")
        self.cur.valueChanged.connect(lambda v: (bpy.context.scene.frame_set(int(v)), self.bar.update()))
        row.addWidget(self.cur)
        row.addWidget(QtWidgets.QLabel("Start"))
        self.start = self._spin(0, 1048574)
        pytips.tag(self.start, "bpy.context.scene.frame_start")
        self.start.valueChanged.connect(lambda v: self._set("frame_start", v))
        self.start.editingFinished.connect(lambda: bridge.undo_push("Frame Range"))
        row.addWidget(self.start)
        row.addWidget(QtWidgets.QLabel("End"))
        self.end = self._spin(0, 1048574)
        pytips.tag(self.end, "bpy.context.scene.frame_end")
        self.end.valueChanged.connect(lambda v: self._set("frame_end", v))
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
        lay.addWidget(self.bar)

        hub.frame_changed.connect(lambda _f: self.sync())
        hub.selection_changed.connect(self.sync)
        hub.data_changed.connect(self.sync)
        hub.file_loaded.connect(self.sync)
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
            rng = list(range(sc.frame_start, sc.frame_end + 1))
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
        """Fills the cache for the scene range (shows progress in the status bar; Esc stops)."""
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
        total = sc.frame_end - sc.frame_start + 1
        try:
            for i, f in enumerate(range(sc.frame_start, sc.frame_end + 1)):
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

    def sync(self):
        sc = bpy.context.scene
        shown = self.shown_frame()
        for w, v in ((self.cur, shown), (self.start, sc.frame_start), (self.end, sc.frame_end)):
            if not (w._editing or w._dragging):
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)
        self.auto_key.blockSignals(True)
        self.auto_key.setChecked(sc.tool_settings.use_keyframe_insert_auto)
        self.auto_key.blockSignals(False)
        label = fps_label(sc.render)
        if self.fps_btn.text() != label:
            self.fps_btn.setText(label)
        frames = set()
        for _ob, fc in timeline_curves():
            for kp in fc.keyframe_points:
                frames.add(int(round(kp.co.x)))
        self.bar.keys = sorted(frames)
        if self.bar._drag is None:
            self.bar.sel &= frames
        self.bar.update()

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
            self._t0 = time.perf_counter()
            self._f0 = getattr(self, "_play_frame", bpy.context.scene.frame_current)
            self._next = self._t0
        mw = getattr(self.hub, "main_window", None)
        props = getattr(mw, "properties", None)
        if props is not None:
            try:
                props.refresh(force=True)     # Output → Frame Rate shows the new value
            except Exception:
                pass
        self.status(f"Frame rate: {fps_label(r)}")
        self.sync()

    def status(self, text):
        mw = getattr(self.hub, "main_window", None)
        if mw is not None:
            mw.statusBar().showMessage(text, 3000)

    @staticmethod
    def _spin(lo, hi):
        """Integer field draggable with the mouse (like Blender), ~4 px per frame."""
        s = DragSpin(is_int=True)
        s.setRange(lo, hi)
        s.drag_step = 0.25
        s.setMinimumWidth(theme.px(64))
        return s

    def _set(self, attr, v):
        setattr(bpy.context.scene, attr, int(v))
        self.bar.update()

    def _set_auto_key(self, on):
        bpy.context.scene.tool_settings.use_keyframe_insert_auto = on

    def _jump(self, where):
        sc = bpy.context.scene
        f = sc.frame_current
        if where == "start":
            f = sc.frame_start
        elif where == "end":
            f = sc.frame_end
        else:
            keys = self.bar.keys
            if where == "prev_key":
                prev = [k for k in keys if k < f]
                f = prev[-1] if prev else f
            else:
                nxt = [k for k in keys if k > f]
                f = nxt[0] if nxt else f
        sc.frame_set(f)
        self.sync()

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

    def toggle_play(self):
        if self.is_playing():
            self._set_playing(False)
            self._end_cached_display()
            if not icons.set_icon(self.play_btn, "play"):
                self.play_btn.setText("▶")
            self.sync()
        else:
            sc = bpy.context.scene
            self.hub.display_frame = None
            self._play_frame = sc.frame_current
            self._t0 = time.perf_counter()
            self._f0 = sc.frame_current
            self._next = self._t0
            self._set_playing(True)
            if not icons.set_icon(self.play_btn, "pause"):
                self.play_btn.setText("⏸")

    def _fps(self):
        r = bpy.context.scene.render
        return max(r.fps / (r.fps_base or 1.0), 0.1)

    def playback_tick(self):
        """Called from the event pump while playing: advances the frame when it is due and
        redraws the viewport right away. Follows the scene's Sync mode like Blender:
        'Play Every Frame' never skips frames, 'Frame Dropping' / 'Sync to Audio' keep real time."""
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
        start, end = sc.frame_start, sc.frame_end
        length = max(end - start + 1, 1)
        shown = getattr(self, "_play_frame", sc.frame_current)
        if getattr(sc, "sync_mode", "NONE") == "NONE":
            f = shown + 1
            if f > end or f < start:
                f = start
            self._next += period
            if self._next < now - 4 * period:      # far behind → don't try to catch up in a burst
                self._next = now + period
        else:
            n = int((now - self._t0) * fps)
            f = start + (self._f0 - start + n) % length
            if f == shown:
                self._next = self._t0 + (n + 1) / fps
                return
            self._next = self._t0 + (n + 1) / fps
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
        self.bar.update()

    def _paths(self, ob):
        rot = "rotation_quaternion" if ob.rotation_mode == "QUATERNION" else (
            "rotation_axis_angle" if ob.rotation_mode == "AXIS_ANGLE" else "rotation_euler")
        return ("location", rot, "scale")

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

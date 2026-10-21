"""Timeline: playback, frame range, keyframes of the active object."""
import time

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, geocache, playcache, theme
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


class TimeBar(QtWidgets.QWidget):
    def __init__(self, timeline):
        super().__init__()
        self.tl = timeline
        self.setMinimumHeight(theme.px(46))
        self.setMouseTracking(False)
        self.keys = []

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
        y = self.height() * 0.65
        for k in self.keys:
            x = self.frame_to_x(k)
            poly = QtGui.QPolygonF([QtCore.QPointF(x, y - 5), QtCore.QPointF(x + 5, y),
                                    QtCore.QPointF(x, y + 5), QtCore.QPointF(x - 5, y)])
            p.setPen(QtGui.QColor("#000"))
            p.setBrush(QtGui.QColor("#e9c44a" if k == sc.frame_current else "#d0d0d0"))
            p.drawPolygon(poly)
        # current frame (the cached frame being shown during cached playback)
        x = self.frame_to_x(self.tl.shown_frame())
        p.setPen(QtGui.QPen(QtGui.QColor("#4772b3"), 2))
        p.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, self.height()))
        p.end()

    def mousePressEvent(self, ev):
        self._scrub(ev.position().x())

    def mouseMoveEvent(self, ev):
        if ev.buttons() & QtCore.Qt.LeftButton:
            self._scrub(ev.position().x())

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
        self.play_btn = btn("▶", "Play / Pause (Space)", self.toggle_play, "bpy.ops.screen.animation_play()")
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
        btn("+◆ Key", "Insert location / rotation / scale keys for the selection – selected bones in "
            "Pose mode, selected objects otherwise (I in the viewport)", self.insert_key,
            "import qt_shell.keying; qt_shell.keying.insert()")
        btn("−◆", "Delete the keys of the selection on the current frame (Alt+I in the viewport)",
            self.delete_key, "import qt_shell.keying; qt_shell.keying.delete()")
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
        ob = bpy.context.view_layer.objects.active
        from . import keying
        self.bar.keys = keying.key_frames(ob) if ob else []
        self.bar.update()

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

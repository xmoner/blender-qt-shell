"""Animation Player – Blender's Render → View Animation (Ctrl+F11) in Qt, with a timeline.

Blender's own player is a separate window (another process) that disappears behind the Qt Shell window and
has no timeline. This one is a Qt window owned by the Qt Shell window (it always stays in front of it) and
plays the rendered animation of the scene:

- Image sequences (PNG, JPEG, TIFF, WebP, BMP … read by Qt; OpenEXR and others via OpenImageIO, bundled with
  Blender) from Output Properties → Output path, frames of the scene range (the preview range when it is on).
  Frames are loaded in the background and kept in memory (limit 1.5 GB) – the timeline shows them green.
- Movie files (FFmpeg output) with Qt Multimedia when it is available.

Synced (button): the player follows the Timeline – scrubbing or playing in the Timeline shows the same frame
here, and scrubbing / stepping here moves the scene's frame; play / pause then drives the Timeline's playback.

Timeline: click / drag to scrub, the wheel steps frames; transport (start, step back, play backwards, play,
step forwards, end), loop mode (Loop / Once / Ping-Pong), playback speed (the scene frame rate or another
one). Canvas: wheel zooms, middle mouse pans, {anim.fit} fits. Keys in the Keyboard Shortcuts window
(Animation Player).
"""
import os
import time

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, icons, keymap, pytips, theme
from .rna_widgets import DragSpin

LOOP_MODES = [("LOOP", "Loop", "loop_continuous"), ("ONCE", "Play Once", "loop_once"),
              ("PINGPONG", "Ping-Pong", "loop_oscillate")]
SPEEDS = [("Scene", None), ("12 fps", 12.0), ("23.98 fps", 24 / 1.001), ("24 fps", 24.0), ("25 fps", 25.0),
          ("29.97 fps", 30 / 1.001), ("30 fps", 30.0), ("50 fps", 50.0), ("60 fps", 60.0)]
CACHE_LIMIT = 1536 * 1024 * 1024


def _api(call):
    return f"import qt_shell; qt_shell.api.main_window().anim_player.{call}"


def scene_range(scene=None):
    """(start, end) View Animation plays by default: the preview range when it is on, else the scene range."""
    sc = scene or bpy.context.scene
    if sc.use_preview_range:
        return sc.frame_preview_start, sc.frame_preview_end
    return sc.frame_start, sc.frame_end


def output_info(scene=None, start=None, end=None):
    """What View Animation plays: {"movie": path or None, "frames": {frame: path}, "start", "end", "fps"}.
    start / end: another frame range than the scene's."""
    sc = scene or bpy.context.scene
    r = sc.render
    s0, e0 = scene_range(sc)
    start = s0 if start is None else int(start)
    end = e0 if end is None else int(end)
    end = max(end, start)
    fps = r.fps / (r.fps_base or 1.0)
    ims = r.image_settings
    movie = getattr(ims, "media_type", "") == "VIDEO" or ims.file_format in ("FFMPEG", "AVI_JPEG", "AVI_RAW")
    info = {"movie": None, "frames": {}, "start": start, "end": end, "fps": fps}
    if movie:
        try:
            p = bpy.path.abspath(r.frame_path(frame=start))
        except Exception:
            p = ""
        info["movie"] = p
        return info
    for f in range(start, end + 1):
        try:
            p = bpy.path.abspath(r.frame_path(frame=f))
        except Exception:
            continue
        info["frames"][f] = p
    return info


def load_image(path):
    """QImage of an image file (Qt formats directly, the rest – e.g. OpenEXR – via OpenImageIO)."""
    rd = QtGui.QImageReader(path)
    rd.setAutoTransform(True)
    img = rd.read()
    if not img.isNull():
        return img.convertToFormat(QtGui.QImage.Format_RGBA8888)
    try:
        import numpy as np
        import OpenImageIO as oiio
        inp = oiio.ImageInput.open(path)
        if inp is None:
            return None
        spec = inp.spec()
        px = inp.read_image(0, 0, 0, min(spec.nchannels, 4), "float")
        inp.close()
        a = np.asarray(px, dtype=np.float32).reshape(spec.height, spec.width, -1)
        rgb = a[:, :, :3] if a.shape[2] >= 3 else np.repeat(a[:, :, :1], 3, axis=2)
        rgb = np.clip(rgb, 0.0, 1.0)
        rgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1 / 2.4) - 0.055)   # linear → sRGB
        alpha = np.clip(a[:, :, 3:4], 0, 1) if a.shape[2] >= 4 else np.ones_like(rgb[:, :, :1])
        out = np.ascontiguousarray((np.concatenate([rgb, alpha], axis=2) * 255 + 0.5).astype(np.uint8))
        q = QtGui.QImage(out.data, spec.width, spec.height, 4 * spec.width, QtGui.QImage.Format_RGBA8888)
        return q.copy()
    except Exception as ex:
        bridge.log(f"Animation Player: can't read {path}: {ex}", "WARNING")
        return None


# ---------------------------------------------------------------- canvas
class _Canvas(QtWidgets.QWidget):
    def __init__(self, player):
        super().__init__(player)
        self.player = player
        self.image = None
        self.message = ""
        self.zoom = None              # None = fit
        self.offset = QtCore.QPointF(0, 0)
        self._pan = None
        self.setMinimumSize(theme.px(240), theme.px(160))
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        s = theme.px(8)
        self._checker = QtGui.QPixmap(2 * s, 2 * s)
        self._checker.fill(QtGui.QColor(102, 102, 102))
        p = QtGui.QPainter(self._checker)
        p.fillRect(0, 0, s, s, QtGui.QColor(153, 153, 153))
        p.fillRect(s, s, s, s, QtGui.QColor(153, 153, 153))
        p.end()

    def fit_zoom(self):
        if self.image is None:
            return 1.0
        dpr = self.devicePixelRatioF()
        return min(self.width() * dpr / max(self.image.width(), 1),
                   self.height() * dpr / max(self.image.height(), 1))

    def fit(self):
        self.zoom = None
        self.offset = QtCore.QPointF(0, 0)
        self.update()

    def image_rect(self):
        z = self.fit_zoom() if self.zoom is None else self.zoom
        dpr = self.devicePixelRatioF()
        w, h = self.image.width() * z / dpr, self.image.height() * z / dpr
        c = QtCore.QPointF(self.width() / 2, self.height() / 2) + self.offset
        return QtCore.QRectF(c.x() - w / 2, c.y() - h / 2, w, h)

    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(30, 30, 30))
        if self.image is not None:
            r = self.image_rect()
            if self.image.hasAlphaChannel():
                p.fillRect(r, QtGui.QBrush(self._checker))
            p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform,
                            (self.fit_zoom() if self.zoom is None else self.zoom) < 1.0)
            p.drawImage(r, self.image)
        if self.message:
            p.setPen(QtGui.QColor(170, 170, 170))
            p.drawText(self.rect().adjusted(20, 20, -20, -20), QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap,
                       self.message)
        p.end()

    def wheelEvent(self, ev):
        steps = ev.angleDelta().y() / 120.0
        if not steps or self.image is None:
            return
        old = self.fit_zoom() if self.zoom is None else self.zoom
        z = max(0.05, min(32.0, old * 1.25 ** steps))
        c = QtCore.QPointF(self.width() / 2, self.height() / 2) + self.offset
        self.offset += (ev.position() - c) * (1 - z / old)
        self.zoom = z
        self.update()

    def mousePressEvent(self, ev):
        self.setFocus()
        if ev.button() == QtCore.Qt.MiddleButton:
            self._pan = ev.position()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
        elif ev.button() == QtCore.Qt.LeftButton:
            self.player.toggle_play()

    def mouseMoveEvent(self, ev):
        if self._pan is not None:
            self.offset += ev.position() - self._pan
            self._pan = ev.position()
            self.update()

    def mouseReleaseEvent(self, _ev):
        if self._pan is not None:
            self._pan = None
            self.unsetCursor()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == QtCore.Qt.MiddleButton:
            self.fit()


# ---------------------------------------------------------------- timeline
class _FrameBar(QtWidgets.QWidget):
    """The player's timeline: ruler, loaded frames (green), current frame; click / drag scrubs."""

    def __init__(self, player):
        super().__init__(player)
        self.player = player
        self.setFixedHeight(theme.px(40))
        self.setMouseTracking(True)
        self._scrub = False
        self.setToolTip("Click or drag to show a frame · wheel: step frames")

    def _x(self, f):
        pl = self.player
        span = max(pl.end - pl.start, 1)
        return 10 + (f - pl.start) / span * (self.width() - 20)

    def _f(self, x):
        pl = self.player
        span = max(pl.end - pl.start, 1)
        return int(round(pl.start + (x - 10) / max(self.width() - 20, 1) * span))

    def paintEvent(self, _ev):
        pl = self.player
        p = QtGui.QPainter(self)
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), QtGui.QColor("#232323"))
        rh = theme.px(16)
        p.fillRect(QtCore.QRectF(0, 0, W, rh), QtGui.QColor("#1c1c1c"))
        span = max(pl.end - pl.start, 1)
        step = 1
        for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 5000):
            if span / s <= W / theme.px(48):
                step = s
                break
        f = p.font()
        f.setPixelSize(theme.fs(10))
        p.setFont(f)
        fr = (pl.start // step) * step
        while fr <= pl.end:
            if fr >= pl.start:
                x = self._x(fr)
                p.setPen(QtGui.QColor("#3a3a3a"))
                p.drawLine(QtCore.QPointF(x, rh), QtCore.QPointF(x, H))
                p.setPen(QtGui.QColor("#9a9a9a"))
                p.drawText(QtCore.QPointF(x + 3, rh - 4), str(fr))
            fr += step
        # loaded (green) / existing (grey) frames
        half = max((self._x(pl.start + 1) - self._x(pl.start)) / 2, 1.0)
        hb = theme.px(4)
        for fr in range(pl.start, pl.end + 1):
            x = self._x(fr)
            if fr in pl.cache:
                col = QtGui.QColor("#4caf50")
            elif fr in pl.paths and pl.exists.get(fr):
                col = QtGui.QColor("#555555")
            else:
                continue
            p.fillRect(QtCore.QRectF(x - half, H - hb, 2 * half, hb), col)
        # current frame
        x = self._x(pl.frame)
        blue = QtGui.QColor("#4772b3")
        p.setPen(QtGui.QPen(blue, 2))
        p.drawLine(QtCore.QPointF(x, rh), QtCore.QPointF(x, H))
        f.setBold(True)
        f.setPixelSize(theme.fs(11))
        p.setFont(f)
        txt = str(pl.frame)
        tw = p.fontMetrics().horizontalAdvance(txt) + theme.px(10)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(blue)
        box = QtCore.QRectF(x - tw / 2, 1, tw, rh - 2)
        p.drawRoundedRect(box, theme.px(4), theme.px(4))
        p.setPen(QtGui.QColor("#ffffff"))
        p.drawText(box, QtCore.Qt.AlignCenter, txt)
        p.end()

    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton:
            self._scrub = True
            self.player.pause()
            self.player.set_frame(self._f(ev.position().x()))

    def mouseMoveEvent(self, ev):
        if self._scrub:
            self.player.set_frame(self._f(ev.position().x()))

    def mouseReleaseEvent(self, _ev):
        self._scrub = False

    def wheelEvent(self, ev):
        steps = ev.angleDelta().y() / 120.0
        if steps:
            self.player.step(-1 if steps > 0 else 1)


# ---------------------------------------------------------------- window
class AnimPlayer(QtWidgets.QWidget):
    """Render → View Animation: plays the rendered frames with a timeline."""

    def __init__(self, main_window):
        super().__init__(main_window, QtCore.Qt.Window)     # owned by the Qt Shell window → always in front
        self.mw = main_window
        self.setObjectName("qtshell_anim_player")
        self.setWindowTitle("Animation Player")
        self.resize(theme.px(960), theme.px(640))
        self.start, self.end, self.frame = 1, 1, 1
        self.scene_fps = 24.0
        self.fps = None                  # None = the scene frame rate
        self.paths = {}
        self.exists = {}
        self.cache = {}                  # frame → QImage
        self._cache_bytes = 0
        self.movie = None
        self._media = None
        self.loop_mode = str(QtCore.QSettings("QtShell", "QtShell").value("anim_player/loop", "LOOP"))
        if self.loop_mode not in [m[0] for m in LOOP_MODES]:
            self.loop_mode = "LOOP"
        self._dir = 1
        self._playing = False
        self._clock = QtCore.QElapsedTimer()
        self._f0 = 1
        self._timer = QtCore.QTimer(self)
        self._timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._loader = QtCore.QTimer(self)
        self._loader.setInterval(15)
        self._loader.timeout.connect(self._preload)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = QtWidgets.QStackedWidget(self)
        self.canvas = _Canvas(self)
        self.stack.addWidget(self.canvas)
        self.video = None
        lay.addWidget(self.stack, 1)
        self.bar = _FrameBar(self)
        lay.addWidget(self.bar)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(theme.px(6), theme.px(3), theme.px(6), theme.px(3))
        row.setSpacing(theme.px(3))

        def btn(icon, glyph, fn, py=None):
            b = QtWidgets.QToolButton(self)
            b.setText(glyph)
            icons.set_icon(b, icon)
            b.setAutoRaise(True)
            pytips.tag(b, py)
            b.clicked.connect(lambda _c=False: fn())
            row.addWidget(b)
            return b

        keymap.tip(btn("jump_start", "⏮", lambda: self.set_frame(self.start), _api("set_frame(1)")),
                   "First Frame ({anim.jump_start})")
        keymap.tip(btn("frame_prev", "◀|", lambda: self.step(-1), _api("step(-1)")),
                   "Previous Frame ({anim.frame_prev})")
        self.rev_btn = btn("play_reverse", "◀", lambda: self.toggle_play(reverse=True), _api("play(reverse=True)"))
        keymap.tip(self.rev_btn, "Play Backwards / Pause ({anim.play_reverse})")
        self.play_btn = btn("play", "▶", lambda: self.toggle_play(), _api("play()"))
        keymap.tip(self.play_btn, "Play / Pause ({anim.play})")
        keymap.tip(btn("frame_next", "|▶", lambda: self.step(1), _api("step(1)")),
                   "Next Frame ({anim.frame_next})")
        keymap.tip(btn("jump_end", "⏭", lambda: self.set_frame(self.end), _api("set_frame(250)")),
                   "Last Frame ({anim.jump_end})")
        self.loop_btn = btn("loop_continuous", "↻", self.cycle_loop, _api("set_loop_mode('PINGPONG')"))
        self.sync_btn = QtWidgets.QToolButton(self)
        self.sync_btn.setText("Synced")
        self.sync_btn.setCheckable(True)
        self.sync_btn.setToolTip("Synced – connected to the Timeline: the player shows the Timeline's frame "
                                 "(scrubbing and playback), scrubbing / stepping here moves the scene's frame, "
                                 "Play / Pause controls the Timeline's playback")
        pytips.tag(self.sync_btn, _api("set_synced(True)"))
        self.sync_btn.toggled.connect(self.set_synced)
        row.addWidget(self.sync_btn)
        row.addSpacing(theme.px(10))
        self.frame_lbl = QtWidgets.QLabel(self)
        self.frame_lbl.setMinimumWidth(theme.px(120))
        row.addWidget(self.frame_lbl)
        row.addSpacing(theme.px(8))
        self.start_spin = self._range_spin("Start", "First frame to play")
        self.end_spin = self._range_spin("End", "Last frame to play")
        pytips.tag(self.start_spin, _api("set_range(1, 250)"))
        pytips.tag(self.end_spin, _api("set_range(1, 250)"))
        self.start_spin.valueChanged.connect(lambda v: self.set_range(v, max(int(v), self.end)))
        self.end_spin.valueChanged.connect(lambda v: self.set_range(min(int(v), self.start), v))
        for label, spin in (("Start", self.start_spin), ("End", self.end_spin)):
            lbl = QtWidgets.QLabel(label, self)      # the label next to the field (like the Timeline)
            lbl.setBuddy(spin)
            row.addSpacing(theme.px(4))
            row.addWidget(lbl)
            row.addWidget(spin)
        rs = btn("preview_range", "↺", self.reset_range, _api("reset_range()"))
        rs.setToolTip("Back to the scene range (the preview range when it is on)")
        row.addStretch(1)
        self.info_lbl = QtWidgets.QLabel(self)
        self.info_lbl.setProperty("dim", True)
        row.addWidget(self.info_lbl)
        row.addSpacing(theme.px(8))
        self.speed = QtWidgets.QComboBox(self)
        for label, v in SPEEDS:
            self.speed.addItem(label, v)
        self.speed.setToolTip("Playback speed – Scene = the scene frame rate (Output Properties)")
        self.speed.activated.connect(lambda _i: self.set_fps(self.speed.currentData()))
        pytips.tag(self.speed, _api("set_fps(25)   # None = the scene frame rate"))
        row.addWidget(self.speed)
        fit = btn("zoom", "⤢", lambda: self.canvas.fit(), _api("canvas.fit()"))
        keymap.tip(fit, "Fit the image in the window ({anim.fit}) · wheel: zoom · middle mouse: pan")
        rl = btn("render_on", "⟳", self.reload, _api("reload()"))
        rl.setToolTip("Reload – read the rendered frames again (after a new render)")
        lay.addLayout(row)
        self.synced = False
        self._scene_seen = None
        self._sync_timer = QtCore.QTimer(self)      # follows the Timeline (also its cached playback)
        self._sync_timer.setInterval(30)
        self._sync_timer.timeout.connect(self._follow_timeline)
        self._update_loop_btn()
        self._update_buttons()
        if str(QtCore.QSettings("QtShell", "QtShell").value("anim_player/synced", "false")).lower() == "true":
            self.sync_btn.setChecked(True)

    def _range_spin(self, label, tip):
        s = DragSpin(is_int=True)
        s.setParent(self)
        s.setRange(-1048574, 1048574)
        s.drag_step = 0.25
        s.setMinimumWidth(theme.px(64))
        s.setToolTip(f"{tip} – drag or type a frame")
        return s

    def _sync_range_spins(self):
        for w, v in ((self.start_spin, self.start), (self.end_spin, self.end)):
            if int(w.value()) != v:
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)

    # ------------------------------------------------------------ loading
    def set_range(self, start, end):
        """Frames to play (Start / End fields) – independent of the scene's frame range."""
        start, end = int(start), int(end)
        if end < start:
            start, end = end, start
        if (start, end) == (self.start, self.end):
            self._sync_range_spins()
            return
        playing = self._playing
        self.reload(start, end)
        if playing:
            self.play(self._dir < 0)

    def reset_range(self):
        """Start / End back to the scene range (preview range when it is on)."""
        a, b = scene_range()
        self.set_range(a, b)

    def reload(self, start=None, end=None):
        """Reads what Render → View Animation shows: the rendered frames (or movie) of start … end
        (default: the range shown now, at the first open the scene range)."""
        self.pause()
        range_change = start is not None
        if start is None and getattr(self, "_range_set", False):
            start, end = self.start, self.end
        info = output_info(start=start, end=end)
        self._range_set = True
        old_frame = self.frame
        self.start, self.end = info["start"], info["end"]
        self.scene_fps = info["fps"]
        old_paths = self.paths
        self.paths = info["frames"]
        self.exists = {f: os.path.isfile(p) for f, p in self.paths.items()}
        if range_change:                 # a new range: keep the frames already loaded (same files)
            self.cache = {f: img for f, img in self.cache.items() if old_paths.get(f) == self.paths.get(f)}
        else:                            # reload: read the files again (a new render)
            self.cache = {}
        self._cache_bytes = sum(img.sizeInBytes() for img in self.cache.values())
        self.movie = info["movie"] if info["movie"] and os.path.isfile(info["movie"]) else None
        self.frame = old_frame if self.start <= old_frame <= self.end else self.start
        self._sync_range_spins()
        if info["movie"] is not None:
            self._open_movie(info["movie"])
        else:
            self.stack.setCurrentWidget(self.canvas)
            n = sum(1 for v in self.exists.values() if v)
            if not n:
                self.canvas.image = None
                first = next(iter(self.paths.values()), "")
                self.canvas.message = (
                    "No rendered frames found.\n\nRender the animation first (Render → Render Animation, "
                    f"{keymap.text('window.render_anim')}).\nExpected files like:\n{first}")
            else:
                self.canvas.message = ""
                self._loader.start()
            self.info_lbl.setText(f"{n} / {len(self.paths)} frames rendered · "
                                  f"{os.path.dirname(next(iter(self.paths.values()), '')) or '—'}")
        self.set_frame(self.frame, push=False)
        self.bar.update()

    def _open_movie(self, path):
        if not os.path.isfile(path):
            self.canvas.image = None
            self.canvas.message = f"The movie file doesn't exist yet:\n{path}\n\nRender the animation first."
            self.stack.setCurrentWidget(self.canvas)
            self.info_lbl.setText("Movie")
            return
        try:
            from PySide6 import QtMultimedia, QtMultimediaWidgets
        except Exception:
            self.canvas.image = None
            self.canvas.message = (f"Qt Multimedia is not available to play the movie:\n{path}\n\n"
                                   "Render an image sequence (e.g. PNG) to view it here.")
            self.stack.setCurrentWidget(self.canvas)
            return
        if self.video is None:
            self.video = QtMultimediaWidgets.QVideoWidget(self)
            self.stack.addWidget(self.video)
            self._media = QtMultimedia.QMediaPlayer(self)
            self._media.setVideoOutput(self.video)
        self._media.setSource(QtCore.QUrl.fromLocalFile(path))
        self._media.pause()
        self.stack.setCurrentWidget(self.video)
        self.info_lbl.setText(os.path.basename(path))

    def _image(self, f):
        img = self.cache.get(f)
        if img is not None:
            return img
        if not self.exists.get(f):
            return None
        img = load_image(self.paths[f])
        if img is None:
            self.exists[f] = False
            return None
        self.cache[f] = img
        self._cache_bytes += img.sizeInBytes()
        # over the memory limit: drop the frames farthest from the current one
        while self._cache_bytes > CACHE_LIMIT and len(self.cache) > 1:
            far = max(self.cache, key=lambda k: abs(k - self.frame))
            if far == f:
                break
            self._cache_bytes -= self.cache.pop(far).sizeInBytes()
        return img

    def _preload(self):
        """Loads missing frames in the background (a few milliseconds per tick)."""
        if not self.isVisible():
            self._loader.stop()
            return
        t0 = time.perf_counter()
        order = list(range(self.frame, self.end + 1)) + list(range(self.start, self.frame))
        loaded = False
        for f in order:
            if f in self.cache or not self.exists.get(f):
                continue
            if self._cache_bytes > CACHE_LIMIT * 0.95:
                break
            self._image(f)
            loaded = True
            if time.perf_counter() - t0 > 0.012:
                break
        if not loaded:
            self._loader.stop()
        self.bar.update()

    # ------------------------------------------------------------ frames
    def _timeline(self):
        return getattr(self.mw, "timeline", None)

    def set_frame(self, f, push=True):
        """Shows frame f. Synced: push=True also moves the scene's frame (the Timeline follows)."""
        f = int(f)
        outside = not (self.start <= f <= self.end)
        if outside and not self.synced:
            f = max(self.start, min(self.end, f))
            outside = False
        self.frame = f
        if self.synced and push:
            tl = self._timeline()
            sc = bpy.context.scene
            if tl is not None and not tl.is_playing() and sc.frame_current != f:
                sc.frame_set(f)
                self._scene_seen = f
                tl.sync()
        if outside:
            self.canvas.image = None
            self.canvas.message = f"Frame {f} is outside Start – End ({self.start} – {self.end})"
            self.canvas.update()
            self.frame_lbl.setText(f"Frame {f}  (outside)")
            self.bar.update()
            return
        if self._media is not None and self.stack.currentWidget() is self.video:
            fps = self.fps or self.scene_fps
            self._media.setPosition(int((f - self.start) / fps * 1000))
        else:
            img = self._image(f)
            if img is not None:
                self.canvas.image = img
                self.canvas.message = ""
            elif any(self.exists.values()):
                self.canvas.image = None
                self.canvas.message = f"Frame {f} is not rendered"
            self.canvas.update()
        n = self.end - self.start + 1
        self.frame_lbl.setText(f"Frame {f}  ({f - self.start + 1} / {n})")
        self.bar.update()

    def step(self, n):
        self.pause()
        self.set_frame(self.frame + int(n))

    # ------------------------------------------------------------ synced with the Timeline
    def set_synced(self, on):
        """Synced: the player follows the Timeline (and scrubbing here moves the scene's frame)."""
        on = bool(on)
        if self.sync_btn.isChecked() != on:
            self.sync_btn.blockSignals(True)
            self.sync_btn.setChecked(on)
            self.sync_btn.blockSignals(False)
        self.synced = on
        QtCore.QSettings("QtShell", "QtShell").setValue("anim_player/synced", "true" if on else "false")
        if on:
            self.pause()
            self._scene_seen = None
            self._sync_timer.start()
            self._follow_timeline()
        else:
            self._sync_timer.stop()
        self._update_buttons()

    def _follow_timeline(self):
        if not self.synced or not self.isVisible():
            return
        tl = self._timeline()
        if tl is None:
            return
        try:
            f = int(tl.shown_frame())
        except Exception:
            return
        playing = tl.is_playing()
        if playing != getattr(self, "_tl_playing", None):
            self._tl_playing = playing
            self._update_buttons()
        if f != self._scene_seen:
            self._scene_seen = f
            if f != self.frame:
                self.set_frame(f, push=False)

    # ------------------------------------------------------------ playback
    def is_playing(self):
        return self._playing

    def play(self, reverse=False):
        d = -1 if reverse else 1
        if self._playing and self._dir == d:
            return
        self._dir = d
        if self.loop_mode == "ONCE" and ((d > 0 and self.frame >= self.end) or (d < 0 and self.frame <= self.start)):
            self.set_frame(self.start if d > 0 else self.end)
        self._f0 = self.frame
        self._clock.start()
        self._playing = True
        fps = self.fps or self.scene_fps
        self._timer.start(max(1, int(1000 / fps / 2)))
        self._update_buttons()

    def pause(self):
        if self._playing:
            self._playing = False
            self._timer.stop()
            self._update_buttons()

    def toggle_play(self, reverse=False):
        if self.synced:                       # the Timeline plays, the player follows
            tl = self._timeline()
            if tl is not None:
                tl.toggle_play(reverse=reverse)
                self._update_buttons()
            return
        if self._playing and self._dir == (-1 if reverse else 1):
            self.pause()
        else:
            self.play(reverse)

    def _tick(self):
        fps = self.fps or self.scene_fps
        n = int(self._clock.elapsed() / 1000.0 * fps)
        length = self.end - self.start + 1
        p = (self._f0 - self.start) + self._dir * n
        if self.loop_mode == "ONCE":
            if p < 0 or p > length - 1:
                self.set_frame(self.end if self._dir > 0 else self.start, push=False)
                self.pause()
                return
            f = self.start + p
        elif self.loop_mode == "PINGPONG" and length > 1:
            per = 2 * (length - 1)
            q = p % per
            f = self.start + (q if q < length else per - q)
        else:
            f = self.start + p % length
        if f != self.frame:
            self.set_frame(f, push=False)

    def set_fps(self, fps):
        """Playback speed in frames per second (None = the scene frame rate)."""
        self.fps = float(fps) if fps else None
        i = next((k for k in range(self.speed.count()) if self.speed.itemData(k) == fps), -1)
        if i >= 0:
            self.speed.setCurrentIndex(i)
        if self._playing:
            self._f0 = self.frame
            self._clock.start()
            self._timer.start(max(1, int(1000 / (self.fps or self.scene_fps) / 2)))

    def set_loop_mode(self, mode):
        """LOOP, ONCE or PINGPONG."""
        mode = str(mode).upper()
        if mode not in [m[0] for m in LOOP_MODES]:
            raise ValueError("Loop mode: LOOP, ONCE or PINGPONG")
        self.loop_mode = mode
        QtCore.QSettings("QtShell", "QtShell").setValue("anim_player/loop", mode)
        self._update_loop_btn()

    def cycle_loop(self):
        ids = [m[0] for m in LOOP_MODES]
        self.set_loop_mode(ids[(ids.index(self.loop_mode) + 1) % len(ids)])

    def _update_loop_btn(self):
        m = {x[0]: x for x in LOOP_MODES}[self.loop_mode]
        icons.set_icon(self.loop_btn, m[2])
        self.loop_btn.setToolTip(f"Loop: {m[1]} – click: Loop → Play Once → Ping-Pong")

    def _update_buttons(self):
        fwd = self._playing and self._dir > 0
        rev = self._playing and self._dir < 0
        tl = self._timeline() if getattr(self, "synced", False) else None
        if tl is not None and tl.is_playing():
            fwd, rev = tl._dir > 0, tl._dir < 0
        if not icons.set_icon(self.play_btn, "pause" if fwd else "play"):
            self.play_btn.setText("⏸" if fwd else "▶")
        if not icons.set_icon(self.rev_btn, "pause" if rev else "play_reverse"):
            self.rev_btn.setText("⏸" if rev else "◀")

    # ------------------------------------------------------------ window
    def present(self):
        """Opens the player (Render → View Animation) in front of the Qt Shell window and starts playing."""
        self._range_set = False         # a fresh open plays the scene range
        self.reload()
        if self.speed.currentData() is None:
            self.speed.setItemText(0, f"Scene ({self.scene_fps:.4g} fps)")
        self.show()
        self.raise_()
        self.activateWindow()
        self.canvas.setFocus()
        if self.synced:
            self._scene_seen = None
            self._sync_timer.start()
            self._follow_timeline()
        elif any(self.exists.values()) or self.movie:
            self.play()

    def closeEvent(self, ev):
        self.pause()
        self._sync_timer.stop()
        self._loader.stop()
        self.cache.clear()
        self._cache_bytes = 0
        if self._media is not None:
            self._media.stop()
        super().closeEvent(ev)

    def keyPressEvent(self, ev):
        names = keymap.event_names(ev)

        def H(aid):
            return keymap.hit(aid, ev, names)

        if H("anim.close"):
            self.close()
        elif H("anim.play"):
            self.toggle_play()
        elif H("anim.play_reverse"):
            self.toggle_play(reverse=True)
        elif H("anim.frame_prev"):
            self.step(-1)
        elif H("anim.frame_next"):
            self.step(1)
        elif H("anim.jump_start"):
            self.pause()
            self.set_frame(self.start)
        elif H("anim.jump_end"):
            self.pause()
            self.set_frame(self.end)
        elif H("anim.fit"):
            self.canvas.fit()
        else:
            super().keyPressEvent(ev)
            return
        ev.accept()

    def event(self, ev):
        # its keys win over the main window's shortcuts (Space = play here, not in the scene)
        if ev.type() == QtCore.QEvent.ShortcutOverride:
            names = keymap.event_names(ev)
            if any(keymap.hit(a, ev, names) for a in ("anim.play", "anim.play_reverse", "anim.frame_prev",
                                                       "anim.frame_next", "anim.jump_start", "anim.jump_end",
                                                       "anim.fit", "anim.close")):
                ev.accept()
                return True
        return super().event(ev)

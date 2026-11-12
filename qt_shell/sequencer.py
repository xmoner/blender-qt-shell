"""Video Sequencer – Blender's Video Sequence Editor (VSE) in Qt, with ideas from Maya's Camera Sequencer.

Layout (one dock):  [ Preview ] | [ strips on channels + frame ruler ] | [ properties of the active strip ]

- Preview: Blender's own sequencer preview embedded in the dock (a helper Blender window with a
  SEQUENCE_EDITOR area in PREVIEW mode – the same way sculptview embeds Blender's 3D view; Windows only).
  It shows exactly what Blender renders, plays with sound (Play ▶ with sound = Blender's own playback).
- Strips: drawn and edited in Qt. Channel 1 at the bottom (like Blender). Strips are coloured by type
  (or by their colour tag), muted ones faded, locked ones hatched.
- Camera Shots (Maya's Camera Sequencer): Add ▸ Camera Shot adds a scene strip of this scene seen through a
  camera, placed after the last shot – cutting between cameras like Maya's shots.
- Data is Blender's: scene.sequence_editor.strips (Blender 4.4+; .sequences before). Edits go through RNA
  (frame_start, channel, frame_final_start / _end, split(), new_*(), remove(), move_to_meta()), each with an
  undo step; only Separate Meta and Duplicate run Blender's operators (in a borrowed SEQUENCE_EDITOR area).

Mouse (Maya / Blender):
  LMB on a strip            select (Shift toggles, Ctrl deselects) and drag to move (time + channel)
  LMB on a strip's end      trim that end            LMB drag on empty space   box select
  LMB in the ruler          change the current frame
  MMB drag / Alt+MMB        pan                      wheel  zoom time (Ctrl: channel height, Shift: scroll channels)
  double-click a meta       open it ("⬑ Up" returns)  RMB    menu
  drop files from Explorer  movie / image / sound strips at that frame and channel
Keys: see Edit → Keyboard Shortcuts → Video Sequencer.
"""
import math
import os
import sys
import time
import traceback

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, theme
from . import rna_widgets as rw

TAG = "qtshell_seq_preview"   # ID property on the preview helper window's screen (found again after a load)
RULER = 22                    # unscaled px
HEADER_W = 118                # unscaled px – channel names on the left
ROW_H = 34                    # unscaled px – default channel height
EDGE = 7                      # unscaled px – grab zone of a strip's end
SNAP_PX = 9                   # unscaled px

TYPE_COLORS = {
    "MOVIE": "#4a6fb5", "IMAGE": "#8a5bb0", "SOUND": "#2f9b8e", "SCENE": "#7f9a3c", "META": "#6b5a8e",
    "TEXT": "#b0703e", "ADJUSTMENT": "#8d8d8d", "MOVIECLIP": "#c25a5a", "MASK": "#9a5a5a",
    "MULTICAM": "#b0973e", "COLOR": "#777777",
}
EFFECT_COLOR = "#b45a7a"
TAG_COLORS = {"COLOR_01": "#e2605b", "COLOR_02": "#f1a355", "COLOR_03": "#f1dc55", "COLOR_04": "#7bcc7b",
              "COLOR_05": "#5db6ea", "COLOR_06": "#8d59da", "COLOR_07": "#c673b8", "COLOR_08": "#7a5441",
              "COLOR_09": "#5b5a56"}
TAG_NAMES = {"NONE": "None", "COLOR_01": "Red", "COLOR_02": "Orange", "COLOR_03": "Yellow", "COLOR_04": "Green",
             "COLOR_05": "Blue", "COLOR_06": "Violet", "COLOR_07": "Pink", "COLOR_08": "Brown",
             "COLOR_09": "Gray"}
TYPE_ICONS = {"MOVIE": "FILE_MOVIE", "IMAGE": "FILE_IMAGE", "SOUND": "FILE_SOUND", "SCENE": "SCENE_DATA",
              "META": "SEQ_STRIP_META", "TEXT": "FONT_DATA", "COLOR": "COLOR", "ADJUSTMENT": "COLOR",
              "CROSS": "NODE_COMPOSITING", "GAMMA_CROSS": "NODE_COMPOSITING", "WIPE": "NODE_COMPOSITING"}
MOVIE_EXT = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mpg", ".mpeg", ".ogv", ".flv", ".wmv", ".mxf")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff", ".bmp", ".tga", ".webp", ".hdr", ".dpx", ".cin")
SOUND_EXT = (".wav", ".mp3", ".ogg", ".flac", ".aac", ".m4a", ".aif", ".aiff", ".opus", ".wma")
TRANSITIONS = (("CROSS", "Cross"), ("GAMMA_CROSS", "Gamma Cross"), ("WIPE", "Wipe"))


# ---------------------------------------------------------------- data helpers
def editor(create=False):
    sc = bpy.context.scene
    se = sc.sequence_editor
    if se is None and create:
        se = sc.sequence_editor_create()
    return se


def coll(owner):
    """The strips collection of the sequence editor or of a meta strip (Blender 4.4+: .strips)."""
    return owner.strips if hasattr(owner, "strips") else owner.sequences


def all_strips():
    se = editor()
    if se is None:
        return []
    return list(se.strips_all if hasattr(se, "strips_all") else se.sequences_all)


def fps():
    r = bpy.context.scene.render
    return max(r.fps / (r.fps_base or 1.0), 1.0)


def strip_color(s):
    tag = getattr(s, "color_tag", "NONE")
    if tag in TAG_COLORS:
        return QtGui.QColor(TAG_COLORS[tag])
    if s.type == "COLOR":
        try:
            c = s.color
            return QtGui.QColor.fromRgbF(min(1, c[0] ** (1 / 2.2)), min(1, c[1] ** (1 / 2.2)), min(1, c[2] ** (1 / 2.2)))
        except Exception:
            pass
    return QtGui.QColor(TYPE_COLORS.get(s.type, EFFECT_COLOR))


def strip_info(s):
    """Second line of a strip: what it shows."""
    t = s.type
    try:
        if t == "SCENE":
            cam = getattr(s, "scene_camera", None)
            scn = s.scene.name if s.scene else "—"
            return f"🎥 {cam.name}" if cam is not None else f"Scene {scn}"
        if t in ("MOVIE", "SOUND"):
            p = s.filepath if t == "MOVIE" else (s.sound.filepath if s.sound else "")
            return os.path.basename(bpy.path.abspath(p)) if p else ""
        if t == "IMAGE":
            n = len(s.elements)
            return f"{s.elements[0].filename}" + (f"  (+{n - 1})" if n > 1 else "")
        if t == "TEXT":
            return f"“{s.text}”"
        if t == "META":
            return f"{len(coll(s))} strips"
    except Exception:
        pass
    return t.replace("_", " ").title()


def free_channel(container, start, end, above=1, skip=()):
    """Lowest channel ≥ above where [start, end) is free."""
    taken = {}
    for s in coll(container):
        if s in skip:
            continue
        taken.setdefault(s.channel, []).append((s.frame_final_start, s.frame_final_end))
    ch = max(1, above)
    while ch < 128:
        if all(e <= start or b >= end for b, e in taken.get(ch, [])):
            return ch
        ch += 1
    return 128


def _effect_params():
    try:
        se = editor(True)
        return [p.identifier for p in coll(se).bl_rna.functions["new_effect"].parameters]
    except Exception:
        return []


def new_effect(container, name, etype, channel, start, length, inputs=()):
    """strips.new_effect across Blender versions (length / frame_end, input1 / seq1)."""
    params = _effect_params()
    kw = dict(name=name, type=etype, channel=channel, frame_start=start)
    if not inputs:
        if "length" in params:
            kw["length"] = length
        else:
            kw["frame_end"] = start + length
    for i, s in enumerate(inputs[:2]):
        key = f"input{i + 1}" if f"input{i + 1}" in params else f"seq{i + 1}"
        kw[key] = s
    return coll(container).new_effect(**kw)


# ---------------------------------------------------------------- Blender context for operators
class seq_context:
    """A SEQUENCE_EDITOR area for bpy.ops.sequencer.* – the preview helper's area (view switched to the
    sequencer for a moment), else an area of the hidden Blender window borrowed like uv_context does."""

    def __init__(self, view="SEQUENCER"):
        self.view = view
        self._restore = []
        self._ov = None

    def __enter__(self):
        host = PreviewHost.current
        win = area = None
        if host is not None:
            win, area = host.bl_window(), host.area()
        if area is None:
            found = bridge.ensure_view3d()
            if not found:
                raise RuntimeError("No Blender window.")
            win = found[0]
            area = next((a for a in win.screen.areas if a.type in ("DOPESHEET_EDITOR", "GRAPH_EDITOR",
                                                                   "IMAGE_EDITOR", "PROPERTIES")), None)
            if area is None:
                area = next(a for a in win.screen.areas if a.type != "VIEW_3D")
            old = area.ui_type
            area.ui_type = "SEQUENCE_EDITOR"
            self._restore.append(lambda a=area, o=old: setattr(a, "ui_type", o))
        follow_scene(win)
        sp = area.spaces.active
        old_view = sp.view_type
        if old_view != self.view:
            sp.view_type = self.view
            self._restore.append(lambda s=sp, o=old_view, a=area: (setattr(s, "view_type", o), a.tag_redraw()))
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        if region is None or region.width <= 1:
            init_regions(win, area)
        region = next((r for r in area.regions if r.type == "WINDOW"), None) or area.regions[-1]
        self._ov = bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region,
                                             space_data=sp)
        self._ov.__enter__()
        return self

    def __exit__(self, *exc):
        try:
            if self._ov is not None:
                self._ov.__exit__(*exc)
        finally:
            for fn in reversed(self._restore):
                try:
                    fn()
                except Exception:
                    pass
        return False


def follow_scene(win):
    """Blender 5.x: a Video Sequencer area shows the workspace's sequencer_scene (None = nothing, and every
    sequencer operator's poll fails) – keep it on the active scene, like the Qt strips view."""
    try:
        ws = win.workspace
        sc = bpy.context.scene
        if hasattr(ws, "sequencer_scene") and ws.sequencer_scene != sc:
            ws.sequencer_scene = sc
            return True
    except Exception:
        pass
    return False


def init_regions(win, area):
    """Regions of a just switched area are 1 × 1 px until it is drawn – draw it once."""
    try:
        with bpy.context.temp_override(window=win, screen=win.screen, area=area):
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
    except Exception:
        pass


def run_seq_op(idname, props=None, undo=None):
    mod, name = idname.split(".", 1)
    op = getattr(getattr(bpy.ops, mod), name)
    try:
        with seq_context():
            if not op.poll():
                return {"CANCELLED"}
            res = op("EXEC_DEFAULT", **(props or {}))
    except Exception as ex:
        bridge.log(f"{idname}: {ex}", "ERROR")
        return {"CANCELLED"}
    if "FINISHED" in res:
        bridge.undo_push(undo or idname)
    return res


# ---------------------------------------------------------------- Blender's preview, embedded
class PreviewHost(QtWidgets.QWidget):
    """Blender's sequencer preview (a helper Blender window) embedded in Qt. Windows only – elsewhere a note."""
    current = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ptr = None
        self.area_ptr = None
        self.hwnd = None
        self.container = None
        self.stale = False
        self._failed = False
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.note = QtWidgets.QLabel("Preview", self)
        self.note.setAlignment(QtCore.Qt.AlignCenter)
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#8a8a8a; background:#1b1b1b;")
        lay.addWidget(self.note)
        self.setMinimumWidth(theme.px(160))
        self._focus_timer = QtCore.QTimer(self)
        self._focus_timer.setInterval(400)
        self._focus_timer.timeout.connect(self._give_keys_back)

    # ---- lookups (never keep Blender structs: a file load can free them)
    def bl_window(self):
        if self.ptr is None or self.stale:
            return None
        for w in bpy.context.window_manager.windows:
            if w.as_pointer() == self.ptr:
                return w
        return None

    def area(self):
        w = self.bl_window()
        if w is None or w.screen is None:
            return None
        for a in w.screen.areas:
            if a.as_pointer() == self.area_ptr and a.type == "SEQUENCE_EDITOR":
                return a
        return None

    def alive(self):
        try:
            return self.area() is not None
        except Exception:
            return False

    # ---- create / close
    def ensure(self):
        if self.alive() or self._failed or not self.isVisible():
            return
        if sys.platform != "win32":
            self._failed = True
            self.note.setText("Blender's sequencer preview can be embedded on Windows only.\n"
                              "Window → Show Blender Window shows Blender's own Video Editing workspace.")
            return
        try:
            self._create()
            PreviewHost.current = self
            self.note.hide()
        except Exception as ex:
            self._failed = True
            self.note.setText(f"The preview could not be opened:\n{ex}")
            bridge.log(f"Video Sequencer: preview not embedded:\n{traceback.format_exc()}", "WARNING")

    def _create(self):
        from . import native, app
        wm = bpy.context.window_manager
        before = {w.as_pointer() for w in wm.windows}
        native_before = set(native.ghost_windows())
        with bridge.blender_context():
            bpy.ops.wm.window_new()
        new = [w for w in wm.windows if w.as_pointer() not in before]
        if not new:
            raise RuntimeError("no new Blender window")
        win = new[0]
        self.ptr = win.as_pointer()
        hwnds = [h for h in native.ghost_windows() if h not in native_before]
        if not hwnds:
            self.close_window()
            raise RuntimeError("no native window handle")
        self.hwnd = hwnds[0]
        native.hide_windows(hwnds)
        try:
            win.screen[TAG] = 1
        except Exception:
            pass
        area = max(win.screen.areas, key=lambda a: a.width * a.height)
        area.type = "SEQUENCE_EDITOR"
        follow_scene(win)
        self.area_ptr = area.as_pointer()
        sp = area.spaces.active
        with bpy.context.temp_override(window=win, screen=win.screen, area=area):
            sp.view_type = "PREVIEW"
            for attr in ("show_region_header", "show_region_ui", "show_region_toolbar",
                         "show_region_tool_header", "show_region_hud", "show_region_channels",
                         "show_region_footer"):
                if hasattr(sp, attr):
                    try:
                        setattr(sp, attr, False)
                    except Exception:
                        pass
            for attr, val in (("show_gizmo", False), ("show_overlays", True)):
                if hasattr(sp, attr):
                    try:
                        setattr(sp, attr, val)
                    except Exception:
                        pass
        self.container = QtWidgets.QWidget.createWindowContainer(QtGui.QWindow.fromWinId(self.hwnd), self)
        self.container.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout().addWidget(self.container)
        self.container.show()
        QtCore.QTimer.singleShot(300, self.fit_view)
        QtCore.QTimer.singleShot(1200, self.fit_view)
        self._focus_timer.start()
        try:
            if app._win is not None:
                app._win.activateWindow()
        except Exception:
            pass

    def fit_view(self):
        a, w = self.area(), self.bl_window()
        if a is None:
            return
        region = next((r for r in a.regions if r.type == "PREVIEW"), None)
        if region is None:
            return
        try:
            with bpy.context.temp_override(window=w, screen=w.screen, area=a, region=region):
                bpy.ops.sequencer.view_all_preview()
        except Exception:
            pass

    def redraw(self):
        a = self.area()
        if a is not None:
            a.tag_redraw()

    def close_window(self):
        from . import app
        self._focus_timer.stop()
        try:
            w = self.bl_window()
            wins = list(bpy.context.window_manager.windows)
            if w is not None and app._win is not None and wins and w != wins[0]:
                app._win.close_blender_window(w)
        except Exception as ex:
            bridge.log(f"Video Sequencer: closing the preview window failed ({ex})", "WARNING")
        if self.container is not None:
            try:
                self.container.hide()
                self.container.deleteLater()
            except Exception:
                pass
        self.container = None
        self.ptr = self.area_ptr = self.hwnd = None
        if PreviewHost.current is self:
            PreviewHost.current = None

    def reopen(self):
        """After a file load: Blender gave the helper window the file's screen – a new one."""
        self.close_window()
        self.stale = False
        self._failed = False
        close_stale_windows()
        self.note.show()
        QtCore.QTimer.singleShot(200, self.ensure)

    def showEvent(self, ev):
        super().showEvent(ev)
        QtCore.QTimer.singleShot(0, self.ensure)

    def _give_keys_back(self):
        """A click into Blender's preview gives it the keyboard (native child) – back to Qt when the mouse is up,
        so Qt Shell's keys keep working (like sculptview)."""
        if sys.platform != "win32" or self.hwnd is None:
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            if u.GetAsyncKeyState(0x01) & 0x8000 or u.GetAsyncKeyState(0x02) & 0x8000 \
                    or u.GetAsyncKeyState(0x04) & 0x8000:
                return
            if u.GetFocus() != self.hwnd:
                return
            top = self.window()                 # the Qt window holding the dock
            u.SetFocus(int(top.winId()))
            ed = self.parent()
            while ed is not None and not isinstance(ed, VideoSequencer):
                ed = ed.parent()
            if ed is not None:
                ed.view.setFocus()
        except Exception:
            pass


def close_stale_windows():
    """Preview helper windows saved in a .blend – closed after loading (they would open as real windows)."""
    from . import app
    host = PreviewHost.current
    mine = host.ptr if host is not None else None
    try:
        wins = list(bpy.context.window_manager.windows)
    except Exception:
        return
    for i, w in enumerate(wins):
        if i == 0 or w.as_pointer() == mine:
            continue
        try:
            tagged = w.screen is not None and w.screen.get(TAG)
        except Exception:
            tagged = False
        if tagged and app._win is not None:
            app._win.close_blender_window(w)


@bpy.app.handlers.persistent
def _on_load_pre(*_args):
    if PreviewHost.current is not None:
        PreviewHost.current.stale = True


def register_handlers():
    lst = bpy.app.handlers.load_pre
    for old in [f for f in lst if getattr(f, "__name__", "") == "_on_load_pre"
                and getattr(f, "__module__", "") == __name__]:
        lst.remove(old)
    lst.append(_on_load_pre)


def unregister_handlers():
    lst = bpy.app.handlers.load_pre
    for old in [f for f in lst if getattr(f, "__name__", "") == "_on_load_pre"
                and getattr(f, "__module__", "") == __name__]:
        lst.remove(old)


def blender_playing():
    try:
        return any(w.screen is not None and w.screen.is_animation_playing
                   for w in bpy.context.window_manager.windows)
    except Exception:
        return False


# ---------------------------------------------------------------- the strips view
class SeqView(QtWidgets.QWidget):
    def __init__(self, ed, parent=None):
        super().__init__(parent)
        self.ed = ed
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumHeight(theme.px(120))
        self.f0 = 0.0             # frame at the left edge of the strip area
        self.sx = 6.0             # px per frame (unscaled)
        self.c0 = 1.0             # channel at the bottom edge
        self.row = ROW_H          # unscaled px per channel
        self._drag = None
        self._hover = None
        self._framed = False

    # ---- geometry
    def hw(self):
        return theme.px(HEADER_W)

    def rh(self):
        return theme.px(self.row)

    def spx(self):
        """Screen px per frame (float – theme.px rounds to whole pixels)."""
        return self.sx * theme.ui_scale

    def x_of(self, f):
        return self.hw() + (f - self.f0) * self.spx()

    def f_of(self, x):
        return self.f0 + (x - self.hw()) / self.spx()

    def y_of(self, ch):
        """Top of channel ch (channel 1 at the bottom)."""
        return self.height() - (ch - self.c0 + 1) * self.rh()

    def ch_of(self, y):
        return int(math.floor((self.height() - y) / self.rh() + self.c0))

    def strip_rect(self, s):
        x0, x1 = self.x_of(s.frame_final_start), self.x_of(s.frame_final_end)
        y = self.y_of(s.channel)
        return QtCore.QRectF(x0, y + 2, max(2.0, x1 - x0), self.rh() - 4)

    def strips(self):
        c = self.ed.container()
        return list(coll(c)) if c is not None else []

    def strip_at(self, pos):
        for s in reversed(self.strips()):
            if self.strip_rect(s).contains(pos):
                return s
        return None

    def frame_all(self, selected=False):
        ss = [s for s in self.strips() if s.select] if selected else self.strips()
        sc = bpy.context.scene
        if ss:
            a = min(s.frame_final_start for s in ss)
            b = max(s.frame_final_end for s in ss)
            top = max(s.channel for s in ss)
            bottom = min(s.channel for s in ss)
        else:
            a, b, top, bottom = sc.frame_start, sc.frame_end + 1, 3, 1
        w = max(50, self.width() - self.hw() - theme.px(30))
        self.sx = max(0.02, min(200.0, w / theme.ui_scale / max(1.0, b - a)))
        self.f0 = a - theme.px(14) / self.spx()
        rows = max(1, (self.height() - theme.px(RULER)) / self.rh())
        need = top - bottom + 1
        if need > rows:
            self.row = max(18, int((self.height() - theme.px(RULER)) / theme.ui_scale / need))
        self.c0 = max(1.0, bottom - 0.0)
        self._framed = True
        self.update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if not self._framed and self.width() > 200:
            self.frame_all()

    # ---- painting
    def paintEvent(self, ev):
        try:
            self._paint()
        except Exception:
            bridge.log(f"Video Sequencer: drawing failed:\n{traceback.format_exc()}", "WARNING")

    def _paint(self):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        hw, rh, rul = self.hw(), self.rh(), theme.px(RULER)
        sc = bpy.context.scene
        p.fillRect(self.rect(), QtGui.QColor("#262626"))
        se = editor()
        # channel rows
        first = max(1, int(math.floor(self.c0)))
        last = self.ch_of(rul) + 1
        for ch in range(first, last + 1):
            y = self.y_of(ch)
            if ch % 2:
                p.fillRect(QtCore.QRectF(hw, y, w - hw, rh), QtGui.QColor("#2b2b2b"))
        # outside the scene range
        xa, xb = self.x_of(sc.frame_start), self.x_of(sc.frame_end + 1)
        shade = QtGui.QColor(0, 0, 0, 70)
        if xa > hw:
            p.fillRect(QtCore.QRectF(hw, rul, xa - hw, h - rul), shade)
        if xb < w:
            p.fillRect(QtCore.QRectF(max(hw, xb), rul, w - max(hw, xb), h - rul), shade)
        if sc.use_preview_range:
            for f in (sc.frame_preview_start, sc.frame_preview_end + 1):
                x = self.x_of(f)
                p.setPen(QtGui.QPen(QtGui.QColor("#d08a3a"), 1))
                p.drawLine(QtCore.QPointF(x, rul), QtCore.QPointF(x, h))
        # grid
        step = self._tick_step()
        f = math.floor(self.f_of(hw) / step) * step
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 14), 1))
        while True:
            x = self.x_of(f)
            if x > w:
                break
            if x >= hw:
                p.drawLine(QtCore.QPointF(x, rul), QtCore.QPointF(x, h))
            f += step
        # strips
        font = p.font()
        small = QtGui.QFont(font)
        small.setPointSizeF(max(6.5, font.pointSizeF() * 0.85))
        active = se.active_strip if se is not None else None
        drag = self._drag or {}
        moving = set(drag.get("strips", ())) if drag.get("mode") == "move" else set()
        for s in self.strips():
            r = self.strip_rect(s)
            if s in moving:
                r = r.translated(drag["dx_px"], -drag["dch"] * rh)
            elif drag.get("mode") in ("trim_l", "trim_r") and drag.get("strip") == s:
                if drag["mode"] == "trim_l":
                    r.setLeft(self.x_of(drag["new"]))
                else:
                    r.setRight(self.x_of(drag["new"]))
            if r.right() < hw or r.left() > w or r.bottom() < rul or r.top() > h:
                continue
            self._paint_strip(p, s, r, s == active, small)
        # box select
        if drag.get("mode") == "box":
            rr = QtCore.QRectF(drag["p0"], drag["p1"]).normalized()
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1, QtCore.Qt.DashLine))
            p.setBrush(QtGui.QColor(255, 255, 255, 25))
            p.drawRect(rr)
        # snap line
        if drag.get("snap_x") is not None:
            p.setPen(QtGui.QPen(QtGui.QColor("#ffd24a"), 1, QtCore.Qt.DashLine))
            p.drawLine(QtCore.QPointF(drag["snap_x"], rul), QtCore.QPointF(drag["snap_x"], h))
        # channel header
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        p.fillRect(QtCore.QRectF(0, rul, hw, h - rul), QtGui.QColor("#202020"))
        p.setPen(QtGui.QColor("#333333"))
        p.drawLine(hw, rul, hw, h)
        chans = getattr(se, "channels", None) if se is not None else None
        p.setFont(small)
        for ch in range(first, last + 1):
            y = self.y_of(ch)
            if y + rh < rul:
                continue
            cobj = chans[ch] if chans is not None and ch < len(chans) else None
            name = cobj.name if cobj is not None else f"Channel {ch}"
            p.setPen(QtGui.QColor("#3a3a3a"))
            p.drawLine(0, int(y + rh), hw, int(y + rh))
            p.setPen(QtGui.QColor("#bdbdbd") if not (cobj is not None and cobj.mute) else QtGui.QColor("#6b6b6b"))
            p.drawText(QtCore.QRectF(theme.px(6), y, hw - theme.px(48), rh), QtCore.Qt.AlignVCenter,
                       p.fontMetrics().elidedText(name, QtCore.Qt.ElideRight, int(hw - theme.px(50))))
            for i, (attr, on_txt, off_txt) in enumerate((("mute", "◌", "●"), ("lock", "🔒", "🔓"))):
                rr = self._chan_btn(ch, i)
                val = bool(getattr(cobj, attr, False)) if cobj is not None else False
                p.setPen(QtGui.QColor("#e0e0e0") if (val if attr == "lock" else not val) else QtGui.QColor("#5e5e5e"))
                p.drawText(rr, QtCore.Qt.AlignCenter, on_txt if val else off_txt)
        p.setFont(font)
        # ruler
        p.fillRect(QtCore.QRectF(0, 0, w, rul), QtGui.QColor("#1e1e1e"))
        p.setPen(QtGui.QColor("#3a3a3a"))
        p.drawLine(0, rul - 1, w, rul - 1)
        f = math.floor(self.f_of(hw) / step) * step
        p.setFont(small)
        while True:
            x = self.x_of(f)
            if x > w:
                break
            if x >= hw:
                p.setPen(QtGui.QColor("#5a5a5a"))
                p.drawLine(QtCore.QPointF(x, rul - theme.px(6)), QtCore.QPointF(x, rul - 1))
                p.setPen(QtGui.QColor("#a8a8a8"))
                p.drawText(QtCore.QPointF(x + 3, rul - theme.px(8)), self._time_label(f))
            f += step
        # current frame
        cur = getattr(self.ed.hub, "display_frame", None)
        cur = sc.frame_current if cur is None else cur
        x = self.x_of(cur)
        if x >= hw:
            p.setPen(QtGui.QPen(QtGui.QColor("#4f8ff7"), 2))
            p.drawLine(QtCore.QPointF(x, rul), QtCore.QPointF(x, h))
            lab = self._time_label(cur, exact=True)
            tw = p.fontMetrics().horizontalAdvance(lab) + theme.px(10)
            box = QtCore.QRectF(x - tw / 2, 1, tw, rul - 3)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor("#4f8ff7"))
            p.drawRoundedRect(box, 3, 3)
            p.setPen(QtGui.QColor("#ffffff"))
            p.drawText(box, QtCore.Qt.AlignCenter, lab)
        p.fillRect(QtCore.QRectF(0, 0, hw, rul), QtGui.QColor("#1e1e1e"))
        p.setPen(QtGui.QColor("#8a8a8a"))
        p.drawText(QtCore.QRectF(theme.px(6), 0, hw, rul), QtCore.Qt.AlignVCenter,
                   "Seconds" if self.ed.show_seconds else "Frames")
        if se is None or not self.strips():
            p.setFont(font)
            p.setPen(QtGui.QColor("#7d7d7d"))
            p.drawText(QtCore.QRectF(hw, rul, w - hw, h - rul), QtCore.Qt.AlignCenter,
                       "Add ▸ Movie / Image / Sound / Camera Shot …  or drop files here")
        p.end()

    def _chan_btn(self, ch, i):
        y = self.y_of(ch)
        s = theme.px(18)
        return QtCore.QRectF(self.hw() - (2 - i) * (s + theme.px(2)) - theme.px(2), y + (self.rh() - s) / 2, s, s)

    def _tick_step(self):
        px = self.spx()
        fr = fps()
        for st in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
            if self.ed.show_seconds and st >= fr and st % int(round(fr)):
                continue
            if st * px >= theme.px(60):
                return st
        return 10000

    def _time_label(self, f, exact=False):
        if not self.ed.show_seconds:
            return str(int(f))
        fr = fps()
        sec = int(f // fr)
        rest = int(round(f - sec * fr))
        m, s = divmod(sec, 60)
        return f"{m}:{s:02d}+{rest:02d}" if exact or rest else f"{m}:{s:02d}"

    def _paint_strip(self, p, s, r, is_active, small):
        col = strip_color(s)
        muted = s.mute
        fill = QtGui.QColor(col)
        fill.setAlpha(90 if muted else 225)
        p.setPen(QtCore.Qt.NoPen)
        g = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, fill.lighter(118))
        g.setColorAt(1, fill)
        p.setBrush(g)
        p.drawRoundedRect(r, 3, 3)
        if s.lock:
            p.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 90), QtCore.Qt.BDiagPattern))
            p.drawRoundedRect(r, 3, 3)
        if getattr(s, "input_count", 0) >= 2 or s.type in ("CROSS", "GAMMA_CROSS", "WIPE"):
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 120), 1))
            p.drawLine(r.bottomLeft(), r.topRight())
        # handles
        hv = self._hover
        if s.select or (hv is not None and hv[0] == s):
            hwid = min(theme.px(5), r.width() / 4)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(255, 255, 255, 70))
            p.drawRect(QtCore.QRectF(r.left(), r.top(), hwid, r.height()))
            p.drawRect(QtCore.QRectF(r.right() - hwid, r.top(), hwid, r.height()))
        # outline
        if is_active and s.select:
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2))
        elif s.select:
            p.setPen(QtGui.QPen(QtGui.QColor("#ffa43a"), 2))
        else:
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 150), 1))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        # text
        if r.width() < theme.px(18):
            return
        txt_r = r.adjusted(theme.px(6), 1, -theme.px(4), -1)
        p.setPen(QtGui.QColor(255, 255, 255, 150 if muted else 240))
        fm = p.fontMetrics()
        name = s.name + ("  (muted)" if muted else "")
        dur = s.frame_final_duration
        if r.height() >= theme.px(26):
            top = QtCore.QRectF(txt_r.left(), txt_r.top(), txt_r.width(), txt_r.height() / 2)
            bot = QtCore.QRectF(txt_r.left(), txt_r.top() + txt_r.height() / 2, txt_r.width(), txt_r.height() / 2)
            p.drawText(top, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                       fm.elidedText(name, QtCore.Qt.ElideRight, int(top.width())))
            old = p.font()
            p.setFont(small)
            info = f"{strip_info(s)}  ·  {dur} fr"
            p.setPen(QtGui.QColor(255, 255, 255, 110 if muted else 175))
            p.drawText(bot, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                       p.fontMetrics().elidedText(info, QtCore.Qt.ElideRight, int(bot.width())))
            p.setFont(old)
        else:
            p.drawText(txt_r, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                       fm.elidedText(name, QtCore.Qt.ElideRight, int(txt_r.width())))

    # ---- mouse
    def _hit(self, pos):
        """(strip, part) under pos: part = 'l' / 'r' (an end) or 'body'."""
        s = self.strip_at(pos)
        if s is None:
            return None
        r = self.strip_rect(s)
        e = min(theme.px(EDGE), r.width() / 3)
        if pos.x() - r.left() <= e:
            return s, "l"
        if r.right() - pos.x() <= e:
            return s, "r"
        return s, "body"

    def mousePressEvent(self, ev):
        self.setFocus()
        pos = ev.position()
        btn, mods = ev.button(), ev.modifiers()
        if btn == QtCore.Qt.MiddleButton or (btn == QtCore.Qt.LeftButton and mods & QtCore.Qt.AltModifier):
            self._drag = {"mode": "pan", "p0": pos, "f0": self.f0, "c0": self.c0}
            return
        if btn == QtCore.Qt.RightButton:
            hit = self._hit(pos)
            if hit is not None and not hit[0].select:
                self.ed.select([hit[0]], extend=False)
            self.ed.context_menu(ev.globalPosition().toPoint(), self.f_of(pos.x()), self.ch_of(pos.y()))
            return
        if btn != QtCore.Qt.LeftButton:
            return
        if pos.y() < theme.px(RULER) and pos.x() > self.hw():
            self._drag = {"mode": "scrub"}
            self._scrub(pos.x())
            return
        if pos.x() < self.hw():
            self._header_click(pos)
            return
        hit = self._hit(pos)
        if hit is None:
            if not mods & (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier):
                self.ed.select([], extend=False)
            self._drag = {"mode": "box", "p0": pos, "p1": pos, "mods": mods}
            return
        s, part = hit
        if mods & QtCore.Qt.ControlModifier:
            self.ed.select([s], extend=True, deselect=True)
            return
        if mods & QtCore.Qt.ShiftModifier:
            self.ed.select([s], extend=True, toggle=True)
            if not s.select:
                return
        elif not s.select:
            self.ed.select([s], extend=False)
        else:
            self.ed.set_active(s)
        if s.lock:
            self.ed.status(f"“{s.name}” is locked")
            return
        if part in ("l", "r"):
            self._drag = {"mode": "trim_" + part, "strip": s, "p0": pos,
                          "orig": s.frame_final_start if part == "l" else s.frame_final_end}
            self._drag["new"] = self._drag["orig"]
        else:
            sel = [x for x in self.strips() if x.select and not x.lock]
            self._drag = {"mode": "move", "strips": sel, "p0": pos, "df": 0, "dch": 0, "dx_px": 0.0,
                          "lo": min(x.frame_final_start for x in sel), "hi": max(x.frame_final_end for x in sel),
                          "chmin": min(x.channel for x in sel), "moved": False}

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        d = self._drag
        if d is None:
            hit = self._hit(pos) if pos.x() > self.hw() and pos.y() > theme.px(RULER) else None
            if hit != self._hover:
                self._hover = hit
                self.setCursor(QtCore.Qt.SizeHorCursor if hit is not None and hit[1] != "body"
                               else QtCore.Qt.ArrowCursor)
                self.update()
            return
        mode = d["mode"]
        if mode == "pan":
            self.f0 = d["f0"] - (pos.x() - d["p0"].x()) / self.spx()
            self.c0 = max(1.0, d["c0"] + (pos.y() - d["p0"].y()) / self.rh())
        elif mode == "scrub":
            self._scrub(pos.x())
        elif mode == "box":
            d["p1"] = pos
        elif mode == "move":
            df = int(round((pos.x() - d["p0"].x()) / self.spx()))
            dch = int(round(-(pos.y() - d["p0"].y()) / self.rh()))
            dch = max(dch, 1 - d["chmin"])
            df, snap_f = self._snap_move(d, df, ev.modifiers())
            d["df"], d["dch"] = df, dch
            d["dx_px"] = df * self.spx()
            d["snap_x"] = self.x_of(snap_f) if snap_f is not None else None
            d["moved"] = d["moved"] or df != 0 or dch != 0
        elif mode in ("trim_l", "trim_r"):
            s = d["strip"]
            f = int(round(self.f_of(pos.x())))
            snap_f = self._snap_frame(f, ev.modifiers(), skip={s})
            if snap_f is not None:
                f = snap_f
            if mode == "trim_l":
                f = min(f, s.frame_final_end - 1)
            else:
                f = max(f, s.frame_final_start + 1)
            d["new"] = f
            d["snap_x"] = self.x_of(snap_f) if snap_f is not None else None
            self.ed.status(f"{'Start' if mode == 'trim_l' else 'End'}: {f}  ({'+' if f >= d['orig'] else ''}"
                           f"{f - d['orig']})")
        self.update()

    def mouseReleaseEvent(self, ev):
        d, self._drag = self._drag, None
        if d is None:
            return
        mode = d["mode"]
        if mode == "box":
            rr = QtCore.QRectF(d["p0"], d["p1"]).normalized()
            if rr.width() > 3 or rr.height() > 3:
                hits = [s for s in self.strips() if self.strip_rect(s).intersects(rr)]
                if d["mods"] & QtCore.Qt.ControlModifier:
                    self.ed.select(hits, extend=True, deselect=True)
                else:
                    self.ed.select(hits, extend=True)
        elif mode == "move" and d["moved"]:
            self.ed.move_strips(d["strips"], d["df"], d["dch"])
        elif mode in ("trim_l", "trim_r") and d["new"] != d["orig"]:
            self.ed.trim(d["strip"], "l" if mode == "trim_l" else "r", d["new"])
        self.update()

    def mouseDoubleClickEvent(self, ev):
        pos = ev.position()
        if pos.x() < self.hw():
            ch = self.ch_of(pos.y())
            self.ed.rename_channel(ch)
            return
        s = self.strip_at(pos)
        if s is not None and s.type == "META":
            self.ed.enter_meta(s)
        elif s is not None:
            self.ed.props_focus()

    def _header_click(self, pos):
        ch = self.ch_of(pos.y())
        se = editor(True)
        chans = getattr(se, "channels", None)
        if chans is None or ch >= len(chans):
            return
        for i, attr in enumerate(("mute", "lock")):
            if self._chan_btn(ch, i).contains(pos):
                setattr(chans[ch], attr, not getattr(chans[ch], attr))
                bridge.undo_push(f"Channel {attr}")
                self.ed.after_edit()
                return

    def _scrub(self, x):
        sc = bpy.context.scene
        f = int(round(self.f_of(x)))
        if f != sc.frame_current:
            sc.frame_set(f)
        self.update()

    def wheelEvent(self, ev):
        steps = ev.angleDelta().y() / 120.0
        if not steps:
            return
        mods = ev.modifiers()
        if mods & QtCore.Qt.ShiftModifier:
            self.c0 = max(1.0, self.c0 + steps)
        elif mods & QtCore.Qt.ControlModifier:
            self.row = max(18, min(120, int(self.row * (1.12 ** steps))))
        else:
            fa = self.f_of(ev.position().x())
            self.sx = max(0.02, min(200.0, self.sx * (1.18 ** steps)))
            self.f0 = fa - (ev.position().x() - self.hw()) / self.spx()
        self.update()

    # ---- snapping
    def _snap_targets(self, skip):
        sc = bpy.context.scene
        t = {sc.frame_current, sc.frame_start, sc.frame_end + 1}
        for s in self.strips():
            if s in skip:
                continue
            t.add(s.frame_final_start)
            t.add(s.frame_final_end)
        return t

    def _snap_on(self, mods):
        on = self.ed.snap_on
        return not on if mods & QtCore.Qt.ControlModifier else on

    def _snap_frame(self, f, mods, skip=()):
        if not self._snap_on(mods):
            return None
        lim = theme.px(SNAP_PX) / self.spx()
        best = None
        for t in self._snap_targets(set(skip)):
            if abs(t - f) <= lim and (best is None or abs(t - f) < abs(best - f)):
                best = t
        return best

    def _snap_move(self, d, df, mods):
        if not self._snap_on(mods):
            return df, None
        lim = theme.px(SNAP_PX) / self.spx()
        best, snap_f = None, None
        for t in self._snap_targets(set(d["strips"])):
            for edge in (d["lo"], d["hi"]):
                cand = t - edge
                if abs(cand - df) <= lim and (best is None or abs(cand - df) < abs(best - df)):
                    best, snap_f = cand, t
        return (best, snap_f) if best is not None else (df, None)

    # ---- keys
    _KEYS = ("seq.cut", "seq.delete", "seq.ripple_delete", "seq.duplicate", "seq.select_all", "seq.deselect_all",
             "seq.mute", "seq.unmute", "seq.lock", "seq.unlock", "seq.meta", "seq.unmeta", "seq.frame_all",
             "seq.frame_selected", "seq.prev_cut", "seq.next_cut", "seq.play", "seq.snap")

    def event(self, ev):
        if ev.type() == QtCore.QEvent.ShortcutOverride:
            from . import keymap
            names = keymap.event_names(ev)
            if any(keymap.hit(a, ev, names) for a in self._KEYS) or (
                    self._drag is not None and ev.key() == QtCore.Qt.Key_Escape):
                ev.accept()
                return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        from . import keymap
        if self._drag is not None and ev.key() == QtCore.Qt.Key_Escape:
            self._drag = None
            self.update()
            return
        names = keymap.event_names(ev)
        for aid in self._KEYS:
            if keymap.hit(aid, ev, names):
                self.ed.run_action(aid)
                return
        super().keyPressEvent(ev)

    # ---- drop files
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        pos = ev.position()
        f = int(round(self.f_of(pos.x()))) if pos.x() > self.hw() else bpy.context.scene.frame_current
        ch = max(1, self.ch_of(pos.y()))
        self.ed.add_files(paths, frame=f, channel=ch)
        ev.acceptProposedAction()


# ---------------------------------------------------------------- properties of the active strip
class StripProps(QtWidgets.QScrollArea):
    def __init__(self, ed, parent=None):
        super().__init__(parent)
        self.ed = ed
        self.setWidgetResizable(True)
        self.setMinimumWidth(theme.px(230))
        self._key = None
        self._bindings = []
        self._build(None)

    def refresh(self, force=False):
        se = editor()
        s = se.active_strip if se is not None else None
        try:
            key = (s.as_pointer(), s.type) if s is not None else None
        except Exception:
            key = None
        if force or key != self._key:
            self._key = key
            self._build(s)
            return
        for b in list(self._bindings):
            try:
                if b.widget_ok():
                    b.refresh()
            except Exception:
                pass

    def _changed(self, *_a):
        self.ed.after_edit(props=False)

    def _build(self, s):
        self._bindings = []
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(theme.px(8), theme.px(6), theme.px(8), theme.px(8))
        lay.setSpacing(theme.px(4))
        self.setWidget(w)
        if s is None:
            lab = QtWidgets.QLabel("No active strip.\n\nClick a strip to see its settings here.", w)
            lab.setWordWrap(True)
            lab.setStyleSheet("color:#8a8a8a;")
            lay.addWidget(lab)
            lay.addStretch(1)
            return
        head = QtWidgets.QLabel(f"<b>{s.type.replace('_', ' ').title()}</b> strip", w)
        lay.addWidget(head)
        self._section(lay, "Strip")
        for prop, label in (("name", "Name"), ("channel", "Channel"),
                            ("frame_final_start", "In"), ("frame_final_end", "Out"),
                            ("frame_final_duration", "Duration"), ("color_tag", "Color Tag"),
                            ("mute", "Mute"), ("lock", "Lock")):
            self._row(lay, label, s, prop)
        t = s.type
        if t != "SOUND":
            self._section(lay, "Compositing")
            self._row(lay, "Blend", s, "blend_type")
            self._row(lay, "Opacity", s, "blend_alpha")
        if t == "SCENE":
            self._section(lay, "Shot (scene strip)")
            self._row(lay, "Scene", s, "scene")
            self._row(lay, "Camera", s, "scene_camera")
            self._row(lay, "Input", s, "scene_input")
            self._row(lay, "Volume", s, "volume")
        elif t == "MOVIE":
            self._section(lay, "Movie")
            self._row(lay, "File", s, "filepath")
            self._row(lay, "Stream", s, "stream_index")
            self._row(lay, "Reverse", s, "use_reverse_frames")
        elif t == "IMAGE":
            self._section(lay, "Image")
            self._row(lay, "Folder", s, "directory")
            self._row(lay, "Reverse", s, "use_reverse_frames")
        elif t == "SOUND":
            self._section(lay, "Sound")
            self._row(lay, "Volume", s, "volume")
            self._row(lay, "Pan", s, "pan")
            self._row(lay, "Pitch", s, "pitch")
            self._row(lay, "Waveform", s, "show_waveform")
            snd = getattr(s, "sound", None)
            if snd is not None:
                self._row(lay, "File", snd, "filepath")
        elif t == "TEXT":
            self._section(lay, "Text")
            for prop, label in (("text", "Text"), ("font_size", "Size"), ("color", "Color"),
                                ("use_shadow", "Shadow"), ("shadow_color", "Shadow Color"),
                                ("use_box", "Box"), ("box_color", "Box Color"), ("location", "Location"),
                                ("wrap_width", "Wrap Width"), ("anchor_x", "Align X"), ("anchor_y", "Align Y"),
                                ("alignment_x", "Align X"), ("use_bold", "Bold"), ("use_italic", "Italic"),
                                ("font", "Font")):
                self._row(lay, label, s, prop)
        elif t == "COLOR":
            self._section(lay, "Color")
            self._row(lay, "Color", s, "color")
        elif t in ("CROSS", "GAMMA_CROSS", "WIPE"):
            self._section(lay, "Transition")
            self._row(lay, "Default Fade", s, "use_default_fade")
            self._row(lay, "Fader", s, "effect_fader")
            if t == "WIPE":
                for prop in ("transition_type", "direction", "blur_width", "angle"):
                    self._row(lay, None, s, prop)
        if t not in ("SOUND",) and getattr(s, "transform", None) is not None:
            self._section(lay, "Transform")
            tr = s.transform
            for prop, label in (("offset_x", "Position X"), ("offset_y", "Position Y"), ("scale_x", "Scale X"),
                                ("scale_y", "Scale Y"), ("rotation", "Rotation")):
                self._row(lay, label, tr, prop)
            self._row(lay, "Flip X", s, "use_flip_x")
            self._row(lay, "Flip Y", s, "use_flip_y")
        if t not in ("SOUND",) and hasattr(s, "color_saturation"):
            self._section(lay, "Color")
            self._row(lay, "Saturation", s, "color_saturation")
            self._row(lay, "Multiply", s, "color_multiply")
        lay.addStretch(1)

    def _section(self, lay, text):
        lab = QtWidgets.QLabel(text, self.widget())
        f = lab.font()
        f.setBold(True)
        lab.setFont(f)
        lab.setStyleSheet("color:#d0d0d0; border-bottom:1px solid #444; padding-top:6px; padding-bottom:2px;")
        lay.addWidget(lab)

    def _row(self, lay, label, data, prop):
        if not hasattr(data, prop):
            return None
        try:
            b, name = rw.make_binding(data, prop, on_change=self._changed)
        except Exception:
            return None
        if b is None:
            return None
        self._bindings.append(b)
        row = QtWidgets.QHBoxLayout()
        lab = QtWidgets.QLabel(label or name or prop, self.widget())
        lab.setMinimumWidth(theme.px(78))
        row.addWidget(lab)
        row.addWidget(b.widget, 1)
        lay.addLayout(row)
        return b


# ---------------------------------------------------------------- the dock widget
class VideoSequencer(QtWidgets.QWidget):
    PY = "qt_shell.api.video_sequencer()"

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self.meta_path = []          # names of the open metas (Maya-like "groups")
        self.snap_on = QtCore.QSettings("QtShell", "QtShell").value("sequencer/snap", True) not in (False, "false")
        self.show_seconds = QtCore.QSettings("QtShell", "QtShell").value("sequencer/seconds", False) in (True, "true")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._toolbar())
        self.split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        self.preview = PreviewHost(self.split)
        self.view = SeqView(self, self.split)
        self.props = StripProps(self, self.split)
        self.split.addWidget(self.preview)
        self.split.addWidget(self.view)
        self.split.addWidget(self.props)
        self.split.setStretchFactor(0, 2)
        self.split.setStretchFactor(1, 5)
        self.split.setStretchFactor(2, 0)
        self.split.setSizes([theme.px(360), theme.px(700), theme.px(260)])
        lay.addWidget(self.split, 1)
        sv = QtCore.QSettings("QtShell", "QtShell").value("sequencer/splitter")
        if sv is not None:
            try:
                self.split.restoreState(sv)
            except Exception:
                pass
        self.split.splitterMoved.connect(
            lambda *_a: QtCore.QSettings("QtShell", "QtShell").setValue("sequencer/splitter", self.split.saveState()))
        for b, i in ((self.preview_btn, 0), (self.props_btn, 2)):
            b.blockSignals(True)
            b.setChecked(self.split.sizes()[i] != 0)
            b.blockSignals(False)
        hub.frame_changed.connect(lambda _f: self._frame())
        try:
            hub.play_frame.connect(lambda _f: self.isVisible() and self.view.update())
        except Exception:
            pass
        hub.data_changed.connect(self.refresh)
        hub.file_loaded.connect(self._file_loaded)
        self._tick = QtCore.QTimer(self)
        self._tick.setInterval(250)
        self._tick.timeout.connect(self._poll)
        self._tick.start()
        self._sig = None
        register_handlers()

    # ---- toolbar
    def _toolbar(self):
        from . import keymap, blicons
        bar = QtWidgets.QWidget(self)
        bar.setObjectName("seq_toolbar")
        h = QtWidgets.QHBoxLayout(bar)
        h.setContentsMargins(theme.px(4), theme.px(3), theme.px(4), theme.px(3))
        h.setSpacing(theme.px(3))

        def btn(text, tip, fn, icon=None, check=False, py=None):
            b = QtWidgets.QToolButton(bar)
            b.setText(text)
            if icon and blicons.has(icon):
                b.setIcon(blicons.icon(icon))
                b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon if text else QtCore.Qt.ToolButtonIconOnly)
            b.setAutoRaise(True)
            b.setCheckable(check)
            keymap.tip(b, tip)
            if check:
                b.toggled.connect(fn)
            else:
                b.clicked.connect(lambda _=False: fn())
            if py:
                try:
                    from . import pytips
                    pytips.tag(b, py)
                except Exception:
                    pass
            h.addWidget(b)
            return b

        add = QtWidgets.QToolButton(bar)
        add.setText("Add")
        if blicons.has("ADD"):
            add.setIcon(blicons.icon("ADD"))
        add.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        add.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        add.setAutoRaise(True)
        self.add_menu = QtWidgets.QMenu(add)
        self.add_menu.aboutToShow.connect(lambda: self._fill_add_menu(self.add_menu))
        add.setMenu(self.add_menu)
        add.setToolTip("Add a strip at the current frame")
        h.addWidget(add)
        self.up_btn = btn("Up", "Close the open meta strip and go back up", self.exit_meta, "FILE_PARENT")
        self.up_btn.hide()
        self.path_lab = QtWidgets.QLabel("", bar)
        self.path_lab.setStyleSheet("color:#c9a3ff;")
        h.addWidget(self.path_lab)
        self._sep(h, bar)
        btn("", "Cut the strips at the current frame ({seq.cut})", lambda: self.run_action("seq.cut"), "ALIGN_CENTER", py="qt_shell.api.video_sequencer().cut()")
        btn("", "Duplicate ({seq.duplicate})", lambda: self.run_action("seq.duplicate"), "DUPLICATE")
        btn("", "Delete ({seq.delete}) – Ripple Delete closes the gap ({seq.ripple_delete})",
            lambda: self.run_action("seq.delete"), "TRASH")
        btn("", "Mute / unmute ({seq.mute} / {seq.unmute})", lambda: self.toggle("mute"), "HIDE_OFF")
        btn("", "Lock / unlock ({seq.lock} / {seq.unlock})", lambda: self.toggle("lock"), "LOCKED")
        btn("", "Make a meta strip of the selection ({seq.meta}); Separate ({seq.unmeta})",
            lambda: self.run_action("seq.meta"), "SEQ_STRIP_META")
        self._sep(h, bar)
        self.snap_btn = btn("", "Snap to strip ends and the current frame ({seq.snap}; Ctrl while dragging inverts)",
                            self._set_snap, "SNAP_ON", check=True)
        self.snap_btn.setChecked(self.snap_on)
        btn("", "Frame All ({seq.frame_all}) – Frame Selected ({seq.frame_selected})", self.view_frame_all, "FULLSCREEN_ENTER")
        self.sec_btn = btn("s", "Show seconds instead of frames", self._set_seconds, check=True)
        self.sec_btn.setChecked(self.show_seconds)
        self._sep(h, bar)
        self.play_btn = btn("Play", "Play with sound – Blender's own playback in the preview ({seq.play})",
                            self.play_sound, "PLAY_SOUND" if blicons.has("PLAY_SOUND") else "PLAY")
        self.sync = QtWidgets.QComboBox(bar)
        for key, label in (("AUDIO_SYNC", "Sync to Audio"), ("FRAME_DROP", "Frame Dropping"), ("NONE", "Play Every Frame")):
            self.sync.addItem(label, key)
        self.sync.setToolTip("Playback sync (Blender's scene.sync_mode): Sync to Audio keeps picture and sound together")
        self.sync.activated.connect(self._set_sync)
        h.addWidget(self.sync)
        h.addStretch(1)
        self.render_chk = QtWidgets.QCheckBox("Render uses the Sequencer", bar)
        self.render_chk.setToolTip("Render → Render Animation renders the strips (scene.render.use_sequencer)\n"
                                   "– off: the 3D scene is rendered, the strips are ignored")
        self.render_chk.toggled.connect(self._set_use_seq)
        h.addWidget(self.render_chk)
        btn("", "Scene range = all strips", self.range_to_strips, "TIME")
        self._sep(h, bar)
        self.preview_btn = btn("Preview", "Show / hide the preview", lambda on: self._show_part(0, on), "SEQ_PREVIEW",
                               check=True)
        self.props_btn = btn("Properties", "Show / hide the strip properties", lambda on: self._show_part(2, on),
                             "PROPERTIES", check=True)
        return bar

    @staticmethod
    def _sep(h, bar):
        f = QtWidgets.QFrame(bar)
        f.setFrameShape(QtWidgets.QFrame.VLine)
        f.setStyleSheet("color:#444;")
        h.addWidget(f)

    def _show_part(self, i, on):
        sizes = self.split.sizes()
        if on and sizes[i] == 0:
            sizes[i] = theme.px(340 if i == 0 else 260)
        elif not on:
            sizes[i] = 0
        self.split.setSizes(sizes)
        QtCore.QSettings("QtShell", "QtShell").setValue("sequencer/splitter", self.split.saveState())

    def _set_snap(self, on):
        self.snap_on = bool(on)
        QtCore.QSettings("QtShell", "QtShell").setValue("sequencer/snap", self.snap_on)

    def _set_seconds(self, on):
        self.show_seconds = bool(on)
        QtCore.QSettings("QtShell", "QtShell").setValue("sequencer/seconds", self.show_seconds)
        self.view.update()

    def _set_sync(self, _i=None):
        try:
            bpy.context.scene.sync_mode = self.sync.currentData()
        except Exception:
            pass

    def _set_use_seq(self, on):
        r = bpy.context.scene.render
        if r.use_sequencer != bool(on):
            r.use_sequencer = bool(on)
            bridge.undo_push("Render uses the Sequencer")

    def status(self, text):
        try:
            from . import app
            app._win.statusBar().showMessage(text, 4000)
        except Exception:
            pass

    # ---- state
    def container(self):
        se = editor()
        if se is None:
            return None
        owner = se
        for n in self.meta_path:
            s = coll(owner).get(n)
            if s is None or s.type != "META":
                self.meta_path = []
                return se
            owner = s
        return owner

    def refresh(self):
        if not self.isVisible():
            return
        try:
            sc = bpy.context.scene
            self.render_chk.blockSignals(True)
            self.render_chk.setChecked(bool(sc.render.use_sequencer))
            self.render_chk.blockSignals(False)
            i = self.sync.findData(sc.sync_mode)
            if i >= 0 and i != self.sync.currentIndex():
                self.sync.setCurrentIndex(i)
        except Exception:
            pass
        self.up_btn.setVisible(bool(self.meta_path))
        self.path_lab.setText(" ▸ ".join(self.meta_path))
        self.props.refresh()
        self.view.update()

    def after_edit(self, props=True):
        if props:
            self.props.refresh(force=True)
        self.view.update()
        self.preview.redraw()

    def _frame(self):
        if self.isVisible():
            self.view.update()
            self.props.refresh()

    def _poll(self):
        """Strips changed elsewhere (Blender's operators, Python, undo) – a cheap signature check."""
        if not self.isVisible():
            return
        playing = blender_playing()
        w = self.preview.bl_window()
        if w is not None and follow_scene(w):
            self.preview.redraw()
        self.play_btn.setText("Stop" if playing else "Play")
        try:
            sig = tuple((s.as_pointer(), s.frame_final_start, s.frame_final_end, s.channel, s.select, s.mute,
                         s.lock, s.name) for s in self.view.strips())
            se = editor()
            sig = (sig, se.active_strip.as_pointer() if se is not None and se.active_strip else 0)
        except Exception:
            sig = None
        if sig != self._sig:
            self._sig = sig
            self.refresh()

    def _file_loaded(self):
        self.meta_path = []
        self.view._framed = False
        self.preview.reopen() if self.preview.ptr is not None or PreviewHost.current is self.preview \
            else close_stale_windows()
        QtCore.QTimer.singleShot(300, lambda: (self.view.frame_all(), self.refresh()))

    def showEvent(self, ev):
        super().showEvent(ev)
        QtCore.QTimer.singleShot(0, self.refresh)

    def shutdown(self):
        self.preview.close_window()
        unregister_handlers()

    # ---- selection
    def selected(self):
        return [s for s in self.view.strips() if s.select]

    def select(self, strips, extend=False, toggle=False, deselect=False):
        if not extend:
            for s in self.view.strips():
                s.select = False
        for s in strips:
            if deselect:
                s.select = False
            elif toggle:
                s.select = not s.select
            else:
                s.select = True
        se = editor()
        if se is not None:
            if strips and not deselect and strips[-1].select:
                se.active_strip = strips[-1]
            elif not any(s.select for s in self.view.strips()):
                se.active_strip = None
        self.after_edit()

    def set_active(self, s):
        se = editor()
        if se is not None and se.active_strip != s:
            se.active_strip = s
            self.after_edit()

    # ---- actions
    def run_action(self, aid):
        fn = {"seq.cut": self.cut, "seq.delete": self.delete, "seq.ripple_delete": lambda: self.delete(ripple=True),
              "seq.duplicate": self.duplicate, "seq.select_all": lambda: self.select(self.view.strips()),
              "seq.deselect_all": lambda: self.select([]), "seq.mute": lambda: self.set_flag("mute", True),
              "seq.unmute": lambda: self.set_flag("mute", False), "seq.lock": lambda: self.set_flag("lock", True),
              "seq.unlock": lambda: self.set_flag("lock", False), "seq.meta": self.make_meta,
              "seq.unmeta": self.separate_meta, "seq.frame_all": self.view_frame_all,
              "seq.frame_selected": lambda: self.view.frame_all(selected=True),
              "seq.prev_cut": lambda: self.jump(-1), "seq.next_cut": lambda: self.jump(1),
              "seq.play": self.play_sound, "seq.snap": lambda: self.snap_btn.toggle()}.get(aid)
        if fn is None:
            return
        try:
            fn()
        except Exception as ex:
            bridge.log(f"Video Sequencer: {aid} failed:\n{traceback.format_exc()}", "ERROR")
            self.status(f"{aid}: {ex}")

    def view_frame_all(self):
        self.view.frame_all()

    def cut(self, frame=None):
        """Splits the selected strips (none selected: all unlocked strips) at the frame – K in Blender."""
        f = bpy.context.scene.frame_current if frame is None else int(frame)
        pool = self.selected() or self.view.strips()
        todo = [s for s in pool if not s.lock and s.frame_final_start < f < s.frame_final_end]
        if not todo:
            self.status("Nothing to cut at the current frame")
            return 0
        n = 0
        for s in todo:
            try:
                s.split(frame=f, split_method="SOFT")
                n += 1
            except TypeError:
                s.split(f, "SOFT")
                n += 1
            except Exception as ex:
                bridge.log(f"Video Sequencer: cut of {s.name} failed ({ex})", "WARNING")
        bridge.undo_push("Cut Strips")
        self.status(f"Cut {n} strip(s) at frame {f}")
        self.after_edit()
        return n

    def delete(self, ripple=False):
        sel = [s for s in self.selected() if not s.lock]
        if not sel:
            return 0
        c = self.container()
        gaps = sorted(((s.channel, s.frame_final_start, s.frame_final_duration) for s in sel), reverse=True)
        names = [s.name for s in sel]
        for n in names:
            s = coll(c).get(n)
            if s is not None:
                try:
                    coll(c).remove(s)
                except Exception as ex:
                    bridge.log(f"Video Sequencer: delete {n} failed ({ex})", "WARNING")
        if ripple:
            for ch, start, dur in gaps:          # later strips on the channel move left (latest gap first)
                later = sorted((s for s in coll(c) if s.channel == ch and s.frame_final_start >= start and not s.lock),
                               key=lambda s: s.frame_final_start)
                for s in later:
                    s.frame_start -= dur
        bridge.undo_push("Ripple Delete" if ripple else "Delete Strips")
        self.after_edit()
        return len(names)

    def duplicate(self):
        sel = self.selected()
        if not sel:
            return 0
        if self.meta_path:
            self.status("Duplicate works at the top level (close the meta first)")
            return 0
        span = max(s.frame_final_end for s in sel) - min(s.frame_final_start for s in sel)
        before = {s.as_pointer() for s in self.view.strips()}
        res = run_seq_op("sequencer.duplicate", undo="Duplicate Strips")
        if "FINISHED" not in res:
            self.status("Duplicate failed")
            return 0
        new = [s for s in self.view.strips() if s.as_pointer() not in before]
        for s in sorted(new, key=lambda s: -s.frame_final_start):
            s.frame_start += span
        for s in new:
            s.channel = free_channel(self.container(), s.frame_final_start, s.frame_final_end, s.channel, skip={s})
        bridge.undo_push("Duplicate Strips")
        self.after_edit()
        return len(new)

    def set_flag(self, attr, on):
        sel = self.selected()
        for s in sel:
            setattr(s, attr, on)
        if sel:
            bridge.undo_push(f"{'' if on else 'Un'}{attr.title()} Strips")
        self.after_edit()

    def toggle(self, attr):
        sel = self.selected()
        if not sel:
            return
        on = not all(getattr(s, attr) for s in sel)
        self.set_flag(attr, on)

    def move_strips(self, strips, df, dch):
        """Moves strips by df frames and dch channels (later ones first, so they do not push each other)."""
        if not strips:
            return
        order = sorted(strips, key=lambda s: s.frame_final_start, reverse=df > 0)
        for s in order:
            if df:
                s.frame_start += df
        order = sorted(strips, key=lambda s: s.channel, reverse=dch > 0)
        for s in order:
            if dch:
                s.channel = max(1, s.channel + dch)
        bridge.undo_push("Move Strips")
        self.status(f"Moved {len(strips)} strip(s) {df:+d} frames" + (f", {dch:+d} channels" if dch else ""))
        self.after_edit()

    def trim(self, s, side, frame):
        if side == "l":
            s.frame_final_start = int(frame)
        else:
            s.frame_final_end = int(frame)
        bridge.undo_push("Trim Strip")
        self.after_edit()

    def jump(self, step):
        """To the previous / next strip start or end (like Blender's Jump to Strip)."""
        sc = bpy.context.scene
        f = sc.frame_current
        edges = sorted({e for s in self.view.strips() for e in (s.frame_final_start, s.frame_final_end)})
        cand = [e for e in edges if (e > f if step > 0 else e < f)]
        if cand:
            sc.frame_set(cand[0] if step > 0 else cand[-1])
        self.view.update()

    def make_meta(self):
        sel = [s for s in self.selected() if not s.lock]
        if not sel:
            return None
        c = self.container()
        start = min(s.frame_final_start for s in sel)
        ch = min(s.channel for s in sel)
        meta = coll(c).new_meta(name="Meta", channel=free_channel(c, start, start + 1, ch + 0), frame_start=start)
        for s in sel:
            s.move_to_meta(meta)
        inner = list(coll(meta))                 # the meta's range does not follow its strips by itself
        if inner:
            lo = min(s.frame_final_start for s in inner)
            hi = max(s.frame_final_end for s in inner)
            meta.frame_final_end = max(hi, meta.frame_final_start + 1)
            meta.frame_final_start = lo
            meta.frame_final_end = hi
        meta.channel = free_channel(c, meta.frame_final_start, meta.frame_final_end, ch, skip={meta})
        se = editor()
        for s in coll(c):
            s.select = s == meta
        se.active_strip = meta
        bridge.undo_push("Make Meta Strip")
        self.after_edit()
        return meta

    def separate_meta(self):
        metas = [s for s in self.selected() if s.type == "META"]
        if not metas:
            self.status("Select a meta strip to separate")
            return
        if self.meta_path:
            self.status("Separate works at the top level (close the meta first)")
            return
        run_seq_op("sequencer.meta_separate", undo="Separate Meta Strip")
        self.after_edit()

    def enter_meta(self, s):
        self.meta_path.append(s.name)
        self.view._framed = False
        self.view.frame_all()
        self.refresh()

    def exit_meta(self):
        if self.meta_path:
            self.meta_path.pop()
        self.view.frame_all()
        self.refresh()

    def rename_channel(self, ch):
        se = editor(True)
        chans = getattr(se, "channels", None)
        if chans is None or ch < 1 or ch >= len(chans):
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Channel Name", f"Name of channel {ch}:",
                                                  text=chans[ch].name)
        if ok and name.strip():
            chans[ch].name = name.strip()
            bridge.undo_push("Rename Channel")
            self.view.update()

    def props_focus(self):
        if self.split.sizes()[2] == 0:
            self.props_btn.setChecked(True)
        self.props.refresh(force=True)

    def range_to_strips(self):
        ss = self.view.strips() if not self.meta_path else list(coll(editor()))
        if not ss:
            return
        sc = bpy.context.scene
        sc.frame_start = min(s.frame_final_start for s in ss)
        sc.frame_end = max(s.frame_final_end for s in ss) - 1
        bridge.undo_push("Scene Range = Strips")
        self.status(f"Scene range {sc.frame_start} – {sc.frame_end}")
        self.view.update()

    # ---- playback with sound (Blender's own)
    def play_sound(self):
        host = PreviewHost.current
        if blender_playing():
            for w in bpy.context.window_manager.windows:
                if w.screen is not None and w.screen.is_animation_playing:
                    with bpy.context.temp_override(window=w, screen=w.screen):
                        bpy.ops.screen.animation_cancel(restore_frame=False)
            self.play_btn.setText("Play")
            return
        try:
            from . import app
            tl = getattr(app._win, "timeline", None)
            if tl is not None and tl.is_playing():
                tl.toggle_play()                 # the Qt Timeline's playback (no sound) stops first
        except Exception:
            pass
        w, a = (host.bl_window(), host.area()) if host is not None else (None, None)
        if w is None or a is None:
            try:                                 # no embedded preview: the Qt Timeline plays (no sound)
                from . import app
                app._win.timeline.toggle_play()
            except Exception:
                self.status("Open the Preview to play with sound")
            return
        with bpy.context.temp_override(window=w, screen=w.screen, area=a):
            bpy.ops.screen.animation_play()
        self.play_btn.setText("Stop")

    # ---- adding
    def _fill_add_menu(self, m):
        from . import blicons
        m.clear()

        def act(menu, text, fn, icon=None):
            a = menu.addAction(text)
            if icon and blicons.has(icon):
                a.setIcon(blicons.icon(icon))
            a.triggered.connect(lambda _=False: self._guard(fn))
            return a

        act(m, "Movie…", self.add_movie_dialog, "FILE_MOVIE")
        act(m, "Image / Sequence…", self.add_image_dialog, "FILE_IMAGE")
        act(m, "Sound…", self.add_sound_dialog, "FILE_SOUND")
        m.addSeparator()
        cams = [o for o in bpy.context.scene.objects if o.type == "CAMERA"]
        sm = m.addMenu("Camera Shot (Maya)")
        if blicons.has("CAMERA_DATA"):
            sm.setIcon(blicons.icon("CAMERA_DATA"))
        sm.setToolTipsVisible(True)
        if not cams:
            sm.addAction("No cameras in the scene").setEnabled(False)
        for cam in sorted(cams, key=lambda o: (o != bpy.context.scene.camera, o.name)):
            a = act(sm, cam.name + ("  (scene camera)" if cam == bpy.context.scene.camera else ""),
                    lambda c=cam: self.add_camera_shot(c), "OUTLINER_OB_CAMERA")
            a.setToolTip("A shot of this scene seen through the camera, after the last shot – like a shot in "
                         "Maya's Camera Sequencer.\nLength: the preview range if set, else the scene range.")
        scm = m.addMenu("Scene")
        if blicons.has("SCENE_DATA"):
            scm.setIcon(blicons.icon("SCENE_DATA"))
        for scn in bpy.data.scenes:
            act(scm, scn.name, lambda s=scn: self.add_scene(s), "SCENE_DATA")
        m.addSeparator()
        act(m, "Text", self.add_text, "FONT_DATA")
        act(m, "Color", self.add_color, "COLOR")
        act(m, "Adjustment Layer", self.add_adjustment, "COLOR")
        tm = m.addMenu("Transition (2 selected strips)")
        sel = self.selected()
        for key, label in TRANSITIONS:
            a = act(tm, label, lambda k=key: self.add_transition(k), "NODE_COMPOSITING")
            a.setEnabled(len(sel) == 2)

    def _guard(self, fn):
        try:
            fn()
        except Exception as ex:
            bridge.log(f"Video Sequencer: {traceback.format_exc()}", "ERROR")
            self.status(f"Add failed: {ex}")

    def _top(self):
        c = self.container()
        return c if c is not None else editor(True)

    def _place(self, strip, frame, channel=1):
        c = self._top()
        strip.channel = free_channel(c, strip.frame_final_start, strip.frame_final_end, channel, skip={strip})
        for s in coll(c):
            s.select = s == strip
        editor().active_strip = strip
        return strip

    def _dialog_dir(self):
        d = QtCore.QSettings("QtShell", "QtShell").value("sequencer/last_dir", "")
        return d or os.path.dirname(bpy.data.filepath) or os.path.expanduser("~")

    def _remember_dir(self, path):
        QtCore.QSettings("QtShell", "QtShell").setValue("sequencer/last_dir", os.path.dirname(path))

    def add_movie_dialog(self):
        pats = " ".join("*" + e for e in MOVIE_EXT)
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Add Movie", self._dialog_dir(),
                                                          f"Movies ({pats});;All files (*)")
        if paths:
            self.add_files(paths)

    def add_image_dialog(self):
        pats = " ".join("*" + e for e in IMAGE_EXT)
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add Image or Image Sequence (select several for a sequence)", self._dialog_dir(),
            f"Images ({pats});;All files (*)")
        if paths:
            self.add_images(sorted(paths))

    def add_sound_dialog(self):
        pats = " ".join("*" + e for e in SOUND_EXT)
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Add Sound", self._dialog_dir(),
                                                          f"Sounds ({pats});;All files (*)")
        if paths:
            self.add_files(paths)

    def add_files(self, paths, frame=None, channel=1):
        """Movies, sounds and images (several images of a folder = one image sequence) one after another."""
        f = bpy.context.scene.frame_current if frame is None else int(frame)
        images = [p for p in paths if p.lower().endswith(IMAGE_EXT)]
        added = []
        for p in paths:
            low = p.lower()
            try:
                if low.endswith(MOVIE_EXT):
                    added += self.add_movie(p, f, channel)
                elif low.endswith(SOUND_EXT):
                    added.append(self.add_sound(p, f, channel))
                else:
                    continue
            except Exception as ex:
                bridge.log(f"Video Sequencer: {os.path.basename(p)} not added ({ex})", "ERROR")
                continue
            if added:
                f = max(f, max(s.frame_final_end for s in added if s is not None))
        if images:
            added.append(self.add_images(sorted(images), f, channel))
        added = [s for s in added if s is not None]
        if added:
            self._remember_dir(paths[0])
            for s in coll(self._top()):
                s.select = s in added
            editor().active_strip = added[0]
            bridge.undo_push("Add Strips")
            self.view._framed = False
            self.view.frame_all()
            self.after_edit()
            self.status(f"Added {len(added)} strip(s)")
        return added

    def add_movie(self, path, frame=None, channel=1, with_sound=True):
        c = self._top()
        f = bpy.context.scene.frame_current if frame is None else int(frame)
        name = os.path.splitext(os.path.basename(path))[0]
        mv = coll(c).new_movie(name=name, filepath=path, channel=free_channel(c, f, f + 1, channel), frame_start=f)
        self._place(mv, f, channel)
        out = [mv]
        if with_sound:
            try:
                snd = coll(c).new_sound(name=name + " (sound)", filepath=path,
                                        channel=free_channel(c, f, mv.frame_final_end, mv.channel + 1), frame_start=f)
                if snd.frame_final_duration <= 1:
                    coll(c).remove(snd)
                else:
                    snd.channel = free_channel(c, snd.frame_final_start, snd.frame_final_end, mv.channel + 1,
                                               skip={snd})
                    out.append(snd)
            except Exception:
                pass                              # a movie without sound
        return out

    def add_sound(self, path, frame=None, channel=1):
        c = self._top()
        f = bpy.context.scene.frame_current if frame is None else int(frame)
        name = os.path.splitext(os.path.basename(path))[0]
        s = coll(c).new_sound(name=name, filepath=path, channel=free_channel(c, f, f + 1, channel), frame_start=f)
        return self._place(s, f, channel)

    def add_images(self, paths, frame=None, channel=1):
        if not paths:
            return None
        c = self._top()
        f = bpy.context.scene.frame_current if frame is None else int(frame)
        first = paths[0]
        name = os.path.splitext(os.path.basename(first))[0]
        s = coll(c).new_image(name=name, filepath=first, channel=free_channel(c, f, f + 1, channel), frame_start=f)
        d = os.path.dirname(first)
        for p in paths[1:]:
            if os.path.dirname(p) == d:
                s.elements.append(os.path.basename(p))
        if len(paths) == 1:
            s.frame_final_duration = int(round(fps() * 2))      # a still: 2 seconds
        self._remember_dir(first)
        self._place(s, f, channel)
        if frame is None:
            bridge.undo_push("Add Image Strip")
            self.after_edit()
        return s

    def add_scene(self, scn, frame=None, channel=1):
        c = self._top()
        f = bpy.context.scene.frame_current if frame is None else int(frame)
        s = coll(c).new_scene(name=scn.name, scene=scn, channel=free_channel(c, f, f + 1, channel), frame_start=f)
        self._place(s, f, channel)
        bridge.undo_push("Add Scene Strip")
        self.after_edit()
        return s

    def add_camera_shot(self, cam, start=None, end=None):
        """Maya's Camera Sequencer shot: this scene through cam for a range of the scene, placed after the last
        shot (a scene strip with a camera override). Range: preview range if on, else the scene range."""
        sc = bpy.context.scene
        c = self._top()
        if start is None or end is None:
            if sc.use_preview_range:
                start, end = sc.frame_preview_start, sc.frame_preview_end
            else:
                start, end = sc.frame_start, sc.frame_end
        shots = [s for s in coll(c) if s.type == "SCENE" and getattr(s, "scene_camera", None) is not None]
        at = max((s.frame_final_end for s in shots), default=sc.frame_start)
        ch = min((s.channel for s in shots), default=1)
        s = coll(c).new_scene(name=cam.name, scene=sc, channel=free_channel(c, at, at + 1, ch),
                              frame_start=at - (start - sc.frame_start))
        s.scene_camera = cam
        try:
            s.scene_input = "CAMERA"
        except Exception:
            pass
        s.frame_final_start = at
        s.frame_final_end = at + (end - start + 1)
        try:
            tags = ["COLOR_05", "COLOR_04", "COLOR_02", "COLOR_06", "COLOR_03", "COLOR_07", "COLOR_01"]
            s.color_tag = tags[len(shots) % len(tags)]
        except Exception:
            pass
        self._place(s, at, ch)
        bridge.undo_push("Add Camera Shot")
        self.view._framed = False
        self.view.frame_all()
        self.after_edit()
        self.status(f"Shot “{cam.name}”: scene frames {start}–{end} at {at}")
        return s

    def _effect(self, etype, name, length=None):
        c = self._top()
        f = bpy.context.scene.frame_current
        n = int(length or round(fps() * 4))
        s = new_effect(c, name, etype, free_channel(c, f, f + n, 1), f, n)
        self._place(s, f, s.channel)
        return s

    def add_text(self):
        s = self._effect("TEXT", "Text")
        try:
            s.text = "Text"
            s.font_size = 80
        except Exception:
            pass
        bridge.undo_push("Add Text Strip")
        self.after_edit()
        return s

    def add_color(self):
        s = self._effect("COLOR", "Color")
        bridge.undo_push("Add Color Strip")
        self.after_edit()
        return s

    def add_adjustment(self):
        s = self._effect("ADJUSTMENT", "Adjustment")
        bridge.undo_push("Add Adjustment Layer")
        self.after_edit()
        return s

    def add_transition(self, etype):
        sel = sorted(self.selected(), key=lambda s: s.frame_final_start)
        if len(sel) != 2:
            self.status("Select two strips for a transition")
            return None
        a, b = sel
        c = self._top()
        top = max(a.channel, b.channel) + 1
        s = new_effect(c, etype.replace("_", " ").title(), etype, top, max(a.frame_final_start, b.frame_final_start),
                       1, inputs=(a, b))
        s.channel = free_channel(c, s.frame_final_start, s.frame_final_end, top, skip={s})
        self._place(s, s.frame_final_start, s.channel)
        bridge.undo_push("Add Transition")
        self.after_edit()
        if s.frame_final_duration <= 1:
            self.status("The two strips do not overlap – move one over the other for a transition")
        return s

    # ---- right-click menu
    def context_menu(self, gpos, frame, channel):
        from . import blicons, keymap
        m = QtWidgets.QMenu(self)
        sel = self.selected()

        def act(text, fn, icon=None, enabled=True):
            a = m.addAction(keymap.render(text))
            if icon and blicons.has(icon):
                a.setIcon(blicons.icon(icon))
            a.setEnabled(enabled)
            a.triggered.connect(lambda _=False: self._guard(fn))
            return a

        add = m.addMenu("Add")
        if blicons.has("ADD"):
            add.setIcon(blicons.icon("ADD"))
        self._fill_add_menu(add)
        m.addSeparator()
        act("Cut at the Current Frame\t{seq.cut}", self.cut, "ALIGN_CENTER")
        act("Duplicate\t{seq.duplicate}", self.duplicate, "DUPLICATE", bool(sel))
        act("Delete\t{seq.delete}", self.delete, "TRASH", bool(sel))
        act("Ripple Delete (close the gap)\t{seq.ripple_delete}", lambda: self.delete(ripple=True), "TRASH", bool(sel))
        m.addSeparator()
        act("Mute / Unmute\t{seq.mute}", lambda: self.toggle("mute"), "HIDE_OFF", bool(sel))
        act("Lock / Unlock\t{seq.lock}", lambda: self.toggle("lock"), "LOCKED", bool(sel))
        tm = m.addMenu("Color Tag")
        for key, label in TAG_NAMES.items():
            a = tm.addAction(label)
            if key in TAG_COLORS:
                pm = QtGui.QPixmap(12, 12)
                pm.fill(QtGui.QColor(TAG_COLORS[key]))
                a.setIcon(QtGui.QIcon(pm))
            a.triggered.connect(lambda _=False, k=key: self._guard(lambda: self.set_tag(k)))
            a.setEnabled(bool(sel))
        m.addSeparator()
        act("Make Meta Strip\t{seq.meta}", self.make_meta, "SEQ_STRIP_META", bool(sel))
        act("Separate Meta Strip\t{seq.unmeta}", self.separate_meta, "SEQ_STRIP_META",
            any(s.type == "META" for s in sel))
        if sel and sel[-1].type == "META":
            act("Open Meta Strip (double-click)", lambda: self.enter_meta(sel[-1]), "SEQ_STRIP_META")
        if self.meta_path:
            act("Close Meta Strip (Up)", self.exit_meta, "FILE_PARENT")
        m.addSeparator()
        act("Set Preview Range to Selection", self.preview_range_to_selection, "PREVIEW_RANGE", bool(sel))
        act("Scene Range = All Strips", self.range_to_strips, "TIME")
        act("Frame All\t{seq.frame_all}", self.view_frame_all, "FULLSCREEN_ENTER")
        act("Frame Selected\t{seq.frame_selected}", lambda: self.view.frame_all(selected=True), "ZOOM_SELECTED",
            bool(sel))
        m.exec(gpos)

    def set_tag(self, key):
        for s in self.selected():
            s.color_tag = key
        bridge.undo_push("Color Tag")
        self.after_edit()

    def preview_range_to_selection(self):
        sel = self.selected()
        if not sel:
            return
        sc = bpy.context.scene
        sc.use_preview_range = True
        sc.frame_preview_start = min(s.frame_final_start for s in sel)
        sc.frame_preview_end = max(s.frame_final_end for s in sel) - 1
        bridge.undo_push("Set Preview Range")
        self.view.update()

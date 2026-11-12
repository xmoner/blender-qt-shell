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

TAG = "qtshell_seq_preview"
BP_PROP = "qtshell_bp_layer"         # Blue Pencil track strip → the layer it stands for
BP_START = "qtshell_bp_start"        # where the track started last time (moving it moves the drawings)
BP_COLOR = "#4f7fe0"
SLOT_NAME = "Qt Shell preview"      # render slot the Qt preview renders into (the user's slots stay)   # ID property on the preview helper window's screen (found again after a load)
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


def is_bp_track(s):
    try:
        return s.get(BP_PROP) is not None
    except Exception:
        return False


def strip_color(s):
    if is_bp_track(s):
        return QtGui.QColor(BP_COLOR)
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
    if is_bp_track(s):
        return "Blue Pencil drawings"
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


def inputs(s):
    """The input strips of an effect strip (Blender 4.4+: input_1 / input_2, before: seq1 / seq2)."""
    out = []
    for a in ("input_1", "input_2", "seq1", "seq2"):
        x = getattr(s, a, None)
        if x is not None and x not in out:
            out.append(x)
    return out


def time_locked(s):
    """Effect strips with inputs (Cross, Wipe, …) take their range from the inputs – frame_start /
    frame_final_start / _end are read-only; only the channel can change."""
    return getattr(s, "input_count", 0) > 0


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


def fit_kw(container, func):
    """fit_method='FIT' like Blender's Add Movie / Image (the RNA default is ORIGINAL – a small clip stays small
    in a large frame)."""
    try:
        params = [p.identifier for p in coll(container).bl_rna.functions[func].parameters]
        return {"fit_method": "FIT"} if "fit_method" in params else {}
    except Exception:
        return {}


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
    strip = coll(container).new_effect(**kw)
    fix_size(strip)
    return strip


def fix_size(strip):
    """Blender 5.x: generator strips (Color, …) made through RNA get a 1 × 1 px image (the Add menu operator
    sets the scene resolution) – they render as a single pixel, i.e. invisible. True when it was fixed."""
    try:
        if hasattr(strip, "width") and strip.width <= 1 and strip.height <= 1:
            r = bpy.context.scene.render
            strip.width, strip.height = r.resolution_x, r.resolution_y
            strip.invalidate_cache("COMPOSITE")
            return True
    except Exception:
        pass
    return False


def fix_all_sizes():
    """Repairs 1 × 1 generator strips made by earlier Qt Shell versions (0.102 – 0.104)."""
    n = 0
    for s in all_strips():
        n += fix_size(s)
    return n


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
                follows = not time_locked(s) or all(x in moving for x in inputs(s))
                r = r.translated(drag["dx_px"] if follows else 0, -drag["dch"] * rh)
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
        # frames cached by the Qt Shell preview (green, like the Timeline)
        cached = self.ed.qtprev.cache if self.ed.cache_on() else {}
        if cached:
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor("#3fbf5a"))
            spx = self.spx()
            for cf in cached:
                x = self.x_of(cf)
                if hw <= x <= w:
                    p.drawRect(QtCore.QRectF(x, rul - theme.px(3), max(1.0, spx), theme.px(3)))
        # current frame
        cur = self.ed.shown_frame()
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
        if is_bp_track(s):                       # its Blue Pencil keys as diamonds
            lay = bp_layer(s.get(BP_PROP))
            if lay is not None:
                from . import bluepencil
                p.setPen(QtGui.QPen(QtGui.QColor(20, 30, 60), 1))
                p.setBrush(QtGui.QColor(255, 255, 255, 120 if muted else 235))
                d = max(3.0, min(r.height() / 4, theme.px(5)))
                cy = r.bottom() - d - 2
                for k in bluepencil.keys(lay):
                    x = self.x_of(k)
                    if r.left() - d <= x <= r.right() + d:
                        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, cy - d), QtCore.QPointF(x + d, cy),
                                                       QtCore.QPointF(x, cy + d), QtCore.QPointF(x - d, cy)]))
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
        if time_locked(s):                       # no trim: their length comes from their inputs
            return s, "body"
        e = min(theme.px(EDGE), r.width() / 3)
        if pos.x() - r.left() <= e:
            return s, "l"
        if r.right() - pos.x() <= e:
            return s, "r"
        return s, "body"

    def mousePressEvent(self, ev):
        self.setFocus()
        if self.ed.cached_playing():
            self.ed.stop_cached_play()
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
             "seq.frame_selected", "seq.prev_cut", "seq.next_cut", "seq.play", "seq.snap",
             "seq.blue_pencil")

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


# ---------------------------------------------------------------- Blue Pencil tracks
def bp_layer(name):
    """The Video Editing Blue Pencil layer (the ones the sequencer draws into) called name, or None."""
    from . import bluepencil
    for lay in bluepencil.data()["layers"]:
        if lay.get("name") == name and lay.get("space", "VIEWPORT") == "VIDEO":
            return lay
    return None


def _bp_save(message=None):
    """Writes the Blue Pencil data back (message: with an undo step, None: quietly – bookkeeping only)."""
    from . import bluepencil
    if message:
        bluepencil.commit(message)
        return
    import json
    sc = bpy.context.scene
    d = bluepencil.data(sc)
    raw = json.dumps(d, separators=(",", ":"))
    sc[bluepencil.PROP] = raw
    bluepencil._cache[sc.as_pointer()] = (raw, d)
    bluepencil.signals.changed.emit()


def bp_track_range(lay):
    """(start, end) of a layer's track: first key → last key + its hold (the gap before it, at least 1 s)."""
    from . import bluepencil
    ks = bluepencil.keys(lay)
    if not ks:
        return None
    hold = max(int(round(fps())), ks[-1] - ks[-2] if len(ks) > 1 else 0)
    return ks[0], ks[-1] + hold


# ---------------------------------------------------------------- Qt Shell's own preview (with Blue Pencil)
def strips_at(frame):
    """Top-level strips Blender would show at a frame, bottom channel first (muted strips / channels left out)."""
    se = editor()
    if se is None:
        return []
    chans = getattr(se, "channels", None)
    out = []
    for s in coll(se):
        if s.mute or s.type == "SOUND" or not (s.frame_final_start <= frame < s.frame_final_end):
            continue
        try:
            if chans is not None and s.channel < len(chans) and chans[s.channel].mute:
                continue
        except Exception:
            pass
        out.append(s)
    return sorted(out, key=lambda s: s.channel)


def shot_at(frame):
    """The topmost scene strip (shot) at a frame, or None."""
    shots = [s for s in strips_at(frame) if s.type == "SCENE" and s.scene is not None]
    return shots[-1] if shots else None


_CHECKER = None
_CM = QtGui.QPainter
QT_BLEND = {     # Blender blend_type → the nearest QPainter composition (Qt Shell's own drawing only)
    "REPLACE": _CM.CompositionMode_Source, "ALPHA_OVER": _CM.CompositionMode_SourceOver,
    "ALPHA_UNDER": _CM.CompositionMode_DestinationOver, "CROSS": _CM.CompositionMode_SourceOver,
    "GAMMA_CROSS": _CM.CompositionMode_SourceOver, "ADD": _CM.CompositionMode_Plus,
    "MULTIPLY": _CM.CompositionMode_Multiply, "SCREEN": _CM.CompositionMode_Screen,
    "OVERLAY": _CM.CompositionMode_Overlay, "DARKEN": _CM.CompositionMode_Darken,
    "LIGHTEN": _CM.CompositionMode_Lighten, "DODGE": _CM.CompositionMode_ColorDodge,
    "BURN": _CM.CompositionMode_ColorBurn, "HARD_LIGHT": _CM.CompositionMode_HardLight,
    "SOFT_LIGHT": _CM.CompositionMode_SoftLight, "DIFFERENCE": _CM.CompositionMode_Difference,
    "EXCLUSION": _CM.CompositionMode_Exclusion,
}


def _checker():
    global _CHECKER
    if _CHECKER is None:
        n = 8
        pm = QtGui.QPixmap(2 * n, 2 * n)
        pm.fill(QtGui.QColor(92, 92, 92))
        q = QtGui.QPainter(pm)
        q.fillRect(0, 0, n, n, QtGui.QColor(64, 64, 64))
        q.fillRect(n, n, n, n, QtGui.QColor(64, 64, 64))
        q.end()
        _CHECKER = pm
    return _CHECKER


def _qcolor(c, alpha=1.0):
    g = [max(0.0, min(1.0, float(v))) ** (1 / 2.2) for v in c[:3]]
    a = float(c[3]) if len(c) > 3 else 1.0
    return QtGui.QColor.fromRgbF(g[0], g[1], g[2], max(0.0, min(1.0, a * alpha)))


class QtPreview(QtWidgets.QWidget):
    """The edit drawn by Qt Shell: shots (scene strips) through their cameras with Qt Shell's offscreen 3D
    drawing, colour, text and image strips, cross fades; movies are named only (Blender's preview shows them).
    Blue Pencil draws on it – into the 3D view's layers of the shot's camera, so the drawings are the same as
    in the 3D view through that camera and are burnt into renders."""
    MAX_W = 1280

    def __init__(self, ed, parent=None):
        super().__init__(parent)
        self.ed = ed
        self.image = None
        self.notes = []
        self._blender_ok = True                  # Blender renders the frame (else Qt's own drawing)
        self.cache = {}                          # frame → QImage (Cache / Auto in the preview header)
        self._fps_times = []                     # when the last frames were shown (fps while playing)
        self._fps_last_frame = None
        self._cache_key = None
        self._pan = None
        self._img_cache = {}
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(theme.px(160), theme.px(90))
        self._t = QtCore.QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(15)
        self._t.timeout.connect(self._render)
        from . import bluepencil
        self.bp = bluepencil.ImageBPTools(self, self.bp_camera, self.pic_rect, self.frame, step_fn=self._bp_step,
                                          space="VIDEO")

    # ---- frame / camera / geometry
    def frame(self):
        return self.ed.shown_frame()

    def show_cached(self, f):
        """Cached playback: the frame straight from the cache (no render, no scene frame change)."""
        img = self.cache.get(f)
        if img is None:
            return False
        self.image = img
        self._fps_tick(f)
        self.repaint()
        return True

    def bp_camera(self):
        """Video Editing layers belong to the edit, not to a camera."""
        return ""

    def shot_camera(self):
        s = shot_at(self.frame())
        cam = None
        if s is not None:
            cam = getattr(s, "scene_camera", None) or s.scene.camera
        return cam.name if cam is not None else ""

    def _bp_step(self, direction):
        from . import bluepencil
        bluepencil.step(direction)

    def out_size(self):
        r = bpy.context.scene.render
        rx = max(1.0, r.resolution_x * r.pixel_aspect_x)
        ry = max(1.0, r.resolution_y * r.pixel_aspect_y)
        dpr = self.devicePixelRatioF()
        w = int(min(self.MAX_W, max(64, self.width() * dpr)))
        h = int(round(w * ry / rx))
        hmax = max(36, int(self.height() * dpr))
        if h > hmax:
            h = hmax
            w = int(round(h * rx / ry))
        return max(16, w), max(16, h)

    def pic_rect(self):
        r = bpy.context.scene.render
        aspect = max(1.0, r.resolution_x * r.pixel_aspect_x) / max(1.0, r.resolution_y * r.pixel_aspect_y)
        m = theme.px(4)
        w, h = self.width() - 2 * m, self.height() - 2 * m
        if w / max(h, 1) > aspect:
            pw, ph = h * aspect, h
        else:
            pw, ph = w, w / aspect
        return QtCore.QRectF((self.width() - pw) / 2, (self.height() - ph) / 2, pw, ph)

    # ---- rendering
    def request(self):
        if self.isVisible():
            self._t.start()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.request()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.request()

    def _render(self):
        if not self.isVisible():
            return
        if getattr(bridge, "op_depth", 0):      # a Qt timer inside a running operator (Windows) – later
            self._t.start(50)
            return
        f = self.frame()
        img = None
        self.notes = []
        cache_on = self.ed.cache_on()
        if cache_on:
            self.check_cache()
            hit = self.cache.get(f)
            if hit is not None:
                self.image = hit
                self._fps_tick(f)
                self.update()
                return
        if self._blender_ok and f == bpy.context.scene.frame_current:
            try:
                img = self.blender_frame()
                if img is not None and cache_on:
                    self.store(f, img)
            except Exception:
                self._blender_ok = False         # fall back to Qt's own drawing for this session
                bridge.log(f"Video Sequencer: Blender's frame for the Qt preview failed – Qt drawing used:\n"
                           f"{traceback.format_exc()}", "WARNING")
        if img is None:
            try:
                img = self.compose(f)
            except Exception:
                bridge.log(f"Video Sequencer: Qt preview failed:\n{traceback.format_exc()}", "WARNING")
        if img is not None:
            self.image = img
            self._fps_tick(f)
        self.update()

    # ---- playback speed (fps shown while playing, like Blender's preview)
    def _fps_tick(self, f):
        if f == self._fps_last_frame:
            return
        self._fps_last_frame = f
        now = time.perf_counter()
        ts = self._fps_times
        if ts and now - ts[-1] > 0.5:            # a pause / a single step: start again
            ts.clear()
        ts.append(now)
        del ts[:-25]

    def playing(self):
        return bool(getattr(self.ed.hub, "playing", False)) or blender_playing() or self.ed.cached_playing()

    def fps_now(self):
        """Measured frames per second of the last frames shown (None when not enough or stale)."""
        ts = self._fps_times
        if len(ts) < 3 or time.perf_counter() - ts[-1] > 0.6:
            return None
        return (len(ts) - 1) / max(1e-6, ts[-1] - ts[0])

    # ---- playback cache (like the Timeline's Cache / Auto)
    def cache_key(self):
        """The cached frames stay valid while this is the same: the strips (what Blender composites), Qt Shell's
        strip edits, the animation and – when shots (scene strips) are in the edit – any scene edit, the size."""
        from . import playcache
        strips = all_strips()
        sig = []
        has_scene = False
        for x in strips:
            if is_bp_track(x):
                continue
            has_scene = has_scene or x.type == "SCENE"
            sig.append((x.as_pointer(), x.type, x.channel, x.frame_final_start, x.frame_final_end, x.mute,
                        getattr(x, "blend_type", ""), round(float(getattr(x, "blend_alpha", 1.0)), 4)))
        se = editor()
        chans = tuple(c.mute for c in se.channels) if se is not None and hasattr(se, "channels") else ()
        sc = bpy.context.scene
        r = sc.render
        return (tuple(sig), chans, self.ed.render_version, playcache.anim_signature(),
                bridge.Flags.edit_version if has_scene else 0, self.out_size(), r.resolution_x, r.resolution_y)

    def check_cache(self):
        key = self.cache_key()
        if key != self._cache_key:
            if self.cache:
                self.cache.clear()
                self.ed.view.update()
            self._cache_key = key

    def store(self, f, img):
        limit = self.ed.cache_limit_bytes()
        per = max(1, img.sizeInBytes())
        if (len(self.cache) + 1) * per > limit:
            return False
        self.cache[f] = img
        self.ed.view.update()
        return True

    def flush(self):
        self.cache.clear()
        self._cache_key = None
        self.ed.view.update()

    def cache_frames(self, frames, budget=None, progress=None):
        """Renders missing frames into the cache (frame hops, the current frame is put back). budget: seconds of
        work (background caching), None = all (Cache All Frames). Returns the number of frames rendered."""
        sc = bpy.context.scene
        keep = sc.frame_current
        self.check_cache()
        todo = [f for f in frames if f not in self.cache]
        if not todo:
            return 0
        n = 0
        t0 = time.perf_counter()
        flag = bridge.Flags.depsgraph
        try:
            for f in todo:
                sc.frame_set(f)
                img = self.blender_frame()
                if img is None or not self.store(f, img):
                    break
                n += 1
                if progress is not None and not progress(f, n, len(todo)):
                    break
                if budget is not None and time.perf_counter() - t0 > budget:
                    break
        finally:
            if sc.frame_current != keep:
                sc.frame_set(keep)
            bridge.Flags.depsgraph = flag        # frame hops are not edits
            self._cache_key = self.cache_key()   # our own hops / renders do not count as changes
        return n

    def blender_frame(self):
        """The current frame exactly as Blender's sequencer shows it (movies, effects, modifiers, shots), rendered
        by Blender at preview size (render.opengl with sequencer=True) into its own render slot – the user's render
        slots stay untouched – and read back through a temporary PNG."""
        import tempfile
        from . import image_editor
        sc = bpy.context.scene
        se = editor()
        if se is None or not len(coll(se)):
            return None
        r = sc.render
        w, _h = self.out_size()
        if not self.ed.cache_on() and (getattr(self.ed.hub, "playing", False) or blender_playing()):
            w = min(w, 640)                      # lighter frames while playing (the cache keeps full ones)
        pct = max(1, min(100, int(math.ceil(w * 100.0 / max(1, r.resolution_x)))))
        rr = bpy.data.images.get("Render Result")
        keep_slot = None
        if rr is not None:
            slots = rr.render_slots
            keep_slot = slots.active_index
            mine = next((i for i, sl in enumerate(slots) if sl.name == SLOT_NAME), None)
            if mine is None:
                slots.new(name=SLOT_NAME)
                mine = len(slots) - 1
            slots.active_index = mine
        keep_pct = r.resolution_percentage
        path = os.path.join(tempfile.gettempdir(), f"qtshell_seq_preview_{os.getpid()}.png")
        try:
            keep_prefetch = getattr(se, "use_prefetch", None)
            with bridge.quiet_updates():
                if keep_pct != pct:
                    r.resolution_percentage = pct
                if keep_prefetch:                # no background prefetch thread from our renders: it can
                    se.use_prefetch = False      # still be reading a strip that is removed next (crash)
                try:
                    with seq_context():
                        res = bpy.ops.render.opengl("EXEC_DEFAULT", sequencer=True)
                finally:
                    if r.resolution_percentage != keep_pct:
                        r.resolution_percentage = keep_pct
                    if keep_prefetch and not se.use_prefetch:
                        se.use_prefetch = True
            if "FINISHED" not in res:
                raise RuntimeError(f"render.opengl: {res}")
            out = bpy.data.images.get("Render Result")
            if rr is None and out is not None:      # the first one: put ours in its own slot next time
                rr = out
            image_editor.save_blender_image(out, path, "PNG", depth="8", fast=True)
        finally:
            if rr is not None and keep_slot is not None:
                try:
                    rr.render_slots.active_index = keep_slot
                except Exception:
                    pass
        img = QtGui.QImage(path)
        return None if img.isNull() else img.convertToFormat(QtGui.QImage.Format_ARGB32_Premultiplied)

    def compose(self, f, size=None):
        """The edit at frame f as a QImage (size: (w, h), default fits the widget)."""
        w, h = size or self.out_size()
        img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(QtGui.QColor(0, 0, 0))
        self.notes = []
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        try:
            for s in strips_at(f):
                layer = self.strip_image(s, f, w, h)
                if layer is None:
                    continue
                p.setOpacity(max(0.0, min(1.0, float(getattr(s, "blend_alpha", 1.0)))))
                p.setCompositionMode(QT_BLEND.get(getattr(s, "blend_type", "ALPHA_OVER"),
                                                  QtGui.QPainter.CompositionMode_SourceOver))
                p.drawImage(QtCore.QRect(0, 0, w, h), layer)
                p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
        finally:
            p.end()
        return img

    def strip_image(self, s, f, w, h, depth=0):
        t = s.type
        if depth > 4:
            return None
        if t == "SCENE":
            return self.scene_image(s, f, w, h)
        if t == "COLOR":
            img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32_Premultiplied)
            img.fill(_qcolor(s.color))
            return img
        if t == "TEXT":
            return self.text_image(s, w, h)
        if t == "IMAGE":
            return self.picture(s, f, w, h)
        if t in ("CROSS", "GAMMA_CROSS", "WIPE", "ALPHA_OVER", "ALPHA_UNDER", "ADD", "MULTIPLY", "SUBTRACT"):
            ins = inputs(s)
            imgs = [self.strip_image(x, f, w, h, depth + 1) if x.frame_final_start <= f < x.frame_final_end
                    else None for x in ins]
            out = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32_Premultiplied)
            out.fill(QtCore.Qt.transparent)
            p = QtGui.QPainter(out)
            fac = (f - s.frame_final_start + 1) / max(1, s.frame_final_duration + 1)
            if not getattr(s, "use_default_fade", True):
                fac = float(getattr(s, "effect_fader", fac))
            if imgs and imgs[0] is not None:
                p.drawImage(0, 0, imgs[0])
            if len(imgs) > 1 and imgs[1] is not None:
                if t in ("CROSS", "GAMMA_CROSS", "WIPE"):
                    p.setOpacity(max(0.0, min(1.0, fac)))
                p.drawImage(0, 0, imgs[1])
            p.end()
            return out
        if t == "MOVIE":
            self.notes.append(f"Movie “{s.name}” – shown in Blender's preview")
        return None

    def scene_image(self, s, f, w, h):
        import gpu
        import numpy as np
        from . import burnin
        from .viewport import eevee_samples
        sc = s.scene
        cam = getattr(s, "scene_camera", None) or sc.camera
        if cam is None:
            self.notes.append(f"“{s.name}”: no camera")
            return None
        local = int(sc.frame_start + (f - s.frame_start))
        if sc == bpy.context.scene and local != f:
            self.notes.append(f"{s.name}: scene frame {local} – shown at {f}")
        space, region = burnin._space()
        if space is None:
            return None
        view, proj = burnin.camera_mats(sc, cam, w, h)
        vl = bpy.context.view_layer if sc == bpy.context.scene else sc.view_layers[0]
        off = gpu.types.GPUOffScreen(w, h)
        ov = getattr(space, "overlay", None)
        keep = getattr(ov, "show_overlays", None)
        try:
            if ov is not None:
                ov.show_overlays = False
            with eevee_samples(1):
                try:
                    off.draw_view3d(sc, vl, space, region, view, proj, do_color_management=True,
                                    draw_background=True)
                except TypeError:
                    off.draw_view3d(sc, vl, space, region, view, proj)
            with off.bind():
                buf = gpu.state.active_framebuffer_get().read_color(0, 0, w, h, 4, 0, "UBYTE")
            try:
                arr = np.frombuffer(buf, dtype=np.uint8)
            except TypeError:
                arr = np.asarray(buf.to_list(), dtype=np.uint8)
        finally:
            off.free()
            if ov is not None and keep is not None:
                ov.show_overlays = keep
        img = QtGui.QImage(w, h, QtGui.QImage.Format_RGBX8888)
        dst = np.frombuffer(img.bits(), dtype=np.uint8, count=h * img.bytesPerLine())
        dst = dst.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)
        dst[:] = arr.reshape(h, w, 4)[::-1]
        return img.convertToFormat(QtGui.QImage.Format_ARGB32_Premultiplied)

    def text_image(self, s, w, h):
        img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing)
        rh = max(1, bpy.context.scene.render.resolution_y)
        font = QtGui.QFont()
        font.setPixelSize(max(4, int(float(getattr(s, "font_size", 60)) * h / rh)))
        font.setBold(bool(getattr(s, "use_bold", False)))
        font.setItalic(bool(getattr(s, "use_italic", False)))
        p.setFont(font)
        loc = getattr(s, "location", (0.5, 0.5))
        x, y = float(loc[0]) * w, (1.0 - float(loc[1])) * h
        fm = p.fontMetrics()
        lines = str(getattr(s, "text", "")).split("\n")
        tw = max((fm.horizontalAdvance(l) for l in lines), default=0)
        th = fm.height() * len(lines)
        ax = getattr(s, "anchor_x", "CENTER")
        ay = getattr(s, "anchor_y", "BOTTOM")
        left = x - (tw / 2 if ax == "CENTER" else tw if ax == "RIGHT" else 0)
        top = y - (th / 2 if ay == "CENTER" else th if ay == "BOTTOM" else 0)
        box = QtCore.QRectF(left, top, tw, th)
        if getattr(s, "use_box", False):
            m = float(getattr(s, "box_margin", 0.01)) * w
            p.fillRect(box.adjusted(-m, -m, m, m), _qcolor(getattr(s, "box_color", (0.2, 0.2, 0.2, 1))))
        if getattr(s, "use_shadow", False):
            p.setPen(_qcolor(getattr(s, "shadow_color", (0, 0, 0, 1))))
            p.drawText(box.translated(max(1, font.pixelSize() / 20), max(1, font.pixelSize() / 20)),
                       QtCore.Qt.AlignCenter, "\n".join(lines))
        p.setPen(_qcolor(getattr(s, "color", (1, 1, 1, 1))))
        p.drawText(box, QtCore.Qt.AlignCenter, "\n".join(lines))
        p.end()
        return img

    def picture(self, s, f, w, h):
        try:
            el = s.strip_elem_from_frame(f)
            path = bpy.path.abspath(os.path.join(s.directory, el.filename)) if el is not None else None
        except Exception:
            path = None
        if not path or not os.path.isfile(path):
            self.notes.append(f"Image “{s.name}”: file not found")
            return None
        src = self._img_cache.get(path)
        if src is None:
            src = QtGui.QImage(path)
            if src.isNull():
                self.notes.append(f"Image “{s.name}”: Qt cannot read it – see Blender's preview")
                return None
            if len(self._img_cache) > 64:
                self._img_cache.clear()
            self._img_cache[path] = src
        img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        sc = min(w / max(1, src.width()), h / max(1, src.height()))     # Blender's default: Scale to Fit
        dw, dh = src.width() * sc, src.height() * sc
        p.drawImage(QtCore.QRectF((w - dw) / 2, (h - dh) / 2, dw, dh), src)
        p.end()
        return img

    # ---- painting / input
    def video_opacity(self):
        """1.0 = the video as it is; less while 'Transparent' is on (0 = only the drawings on a checkerboard)."""
        pane = self.parent().parent() if self.parent() is not None else None
        if pane is None or not hasattr(pane, "transparent_on"):
            return 1.0
        return pane.video_opacity() if pane.transparent_on() else 1.0

    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(24, 24, 24))
        r = self.pic_rect()
        op = self.video_opacity()
        if op < 1.0:                             # transparent sheet: checkerboard under the faded video
            p.fillRect(r, QtGui.QBrush(_checker()))
        if self.image is not None and op > 0.0:
            p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            p.setOpacity(op)
            p.drawImage(r, self.image)
            p.setOpacity(1.0)
        p.setPen(QtGui.QColor(70, 70, 70))
        p.drawRect(r.adjusted(-0.5, -0.5, 0.5, 0.5))
        try:
            self.bp.paint_all(p)
        except Exception:
            pass
        lines = list(self.notes)
        s = shot_at(self.frame())
        if s is not None:
            lines.insert(0, f"{s.name}  ·  🎥 {self.shot_camera()}")
        if self.bp.enabled:
            lines.append("Blue Pencil – Video Editing layers")
        if lines:
            f = p.font()
            f.setPointSizeF(max(7.0, f.pointSizeF() * 0.85))
            p.setFont(f)
            y = r.top() + theme.px(4)
            for line in lines[:4]:
                br = p.fontMetrics().boundingRect(line)
                box = QtCore.QRectF(r.left() + theme.px(4), y, br.width() + theme.px(8), br.height() + theme.px(2))
                p.fillRect(box, QtGui.QColor(0, 0, 0, 140))
                p.setPen(QtGui.QColor(225, 225, 225))
                p.drawText(box, QtCore.Qt.AlignCenter, line)
                y += box.height() + 1
        rate = self.fps_now()
        if rate is not None and self.playing():
            target = fps()
            txt = f"fps: {rate:.1f} / {target:g}"
            f2 = QtGui.QFont(p.font())
            f2.setBold(True)
            p.setFont(f2)
            br = p.fontMetrics().boundingRect(txt)
            box = QtCore.QRectF(r.right() - br.width() - theme.px(14), r.top() + theme.px(4),
                                br.width() + theme.px(10), br.height() + theme.px(4))
            p.fillRect(box, QtGui.QColor(0, 0, 0, 160))
            p.setPen(QtGui.QColor("#ff6a5a") if rate < target * 0.9 else QtGui.QColor("#8fe388"))
            p.drawText(box, QtCore.Qt.AlignCenter, txt)
        p.end()

    def mousePressEvent(self, ev):
        self.setFocus()
        if self.bp.enabled:
            if blender_playing():
                self.ed.play_sound()
            if self.bp.press(ev, ev.position()):
                return
        if ev.button() == QtCore.Qt.LeftButton and not self.bp.enabled:
            self.ed.set_blue_pencil(True) if ev.modifiers() & QtCore.Qt.ShiftModifier else None

    def mouseMoveEvent(self, ev):
        if self.bp.enabled:
            self.bp.move(ev, ev.position())

    def mouseReleaseEvent(self, ev):
        if self.bp.enabled:
            self.bp.release(ev, ev.position())
            self.ed.mark_bp_layer()

    def mouseDoubleClickEvent(self, ev):
        if self.bp.enabled:
            self.bp.double_click(ev, ev.position())

    def wheelEvent(self, ev):
        if self.bp.enabled and self.bp.wheel(ev):
            return
        super().wheelEvent(ev)

    def event(self, ev):
        if ev.type() == QtCore.QEvent.ShortcutOverride and self.bp.enabled and self.bp.owns_key(ev):
            ev.accept()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        from . import keymap
        names = keymap.event_names(ev)
        if self.bp.enabled and self.bp.key(ev, lambda aid: keymap.hit(aid, ev, names)):
            self.update()
            return
        if keymap.hit("seq.blue_pencil", ev, names):
            self.ed.set_blue_pencil(not self.bp.enabled)
            return
        self.ed.view.keyPressEvent(ev)       # the strips view's keys (cut, play …) also work here


class PreviewPane(QtWidgets.QWidget):
    """Preview header (Blender / Qt Shell, Blue Pencil) above Blender's embedded preview or Qt Shell's own."""

    def __init__(self, ed, parent=None):
        super().__init__(parent)
        from . import icons, keymap
        self.ed = ed
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QtWidgets.QWidget(self)
        hl = QtWidgets.QHBoxLayout(head)
        hl.setContentsMargins(theme.px(4), theme.px(2), theme.px(4), theme.px(2))
        hl.setSpacing(theme.px(3))
        self.mode = QtWidgets.QComboBox(head)
        self.mode.addItem("Blender preview", "blender")
        self.mode.addItem("Qt Shell preview", "qt")
        self.mode.setToolTip("Blender preview: Blender's own sequencer preview – movies, effects and modifiers "
                             "exactly as rendered, playback with sound.\n"
                             "Qt Shell preview: drawn by Qt Shell – shots through their cameras, colour, text and "
                             "image strips, cross fades – with Blue Pencil on the shot camera.")
        hl.addWidget(self.mode)
        self.bp_btn = QtWidgets.QToolButton(head)
        self.bp_btn.setCheckable(True)
        self.bp_btn.setAutoRaise(True)
        icons.set_icon(self.bp_btn, "tool_blue_pencil")
        if self.bp_btn.icon().isNull():
            self.bp_btn.setText("✐")
        bpm = QtWidgets.QMenu(self.bp_btn)
        bpm.aboutToShow.connect(lambda m=bpm: self._fill_bp_menu(m))
        self.bp_btn.setMenu(bpm)
        self.bp_btn.setPopupMode(QtWidgets.QToolButton.DelayedPopup)
        self.bp_btn.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        keymap.tip(self.bp_btn, "Blue Pencil ({seq.blue_pencil}) – draw on the shot (Qt Shell preview): the drawings "
                                "go to the 3D view's layers of the shot camera, so you see them in the 3D view "
                                "through that camera and in renders. Hold for the drawing tools.")
        self.bp_btn.toggled.connect(lambda on: self.ed.set_blue_pencil(on))
        hl.addWidget(self.bp_btn)
        qs = QtCore.QSettings("QtShell", "QtShell")
        self.clear_btn = QtWidgets.QToolButton(head)
        self.clear_btn.setCheckable(True)
        self.clear_btn.setAutoRaise(True)
        self.clear_btn.setText("◫")
        self.clear_btn.setToolTip("Transparent – the video fades (slider) or disappears, so the Blue Pencil drawings "
                                  "stand alone on a transparent sheet (Qt Shell preview)")
        self.clear_btn.setChecked(qs.value("sequencer/transparent", False) in (True, "true"))
        hl.addWidget(self.clear_btn)
        self.op_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, head)
        self.op_slider.setRange(0, 100)
        self.op_slider.setFixedWidth(theme.px(80))
        try:
            self.op_slider.setValue(int(qs.value("sequencer/video_opacity", 25)))
        except (TypeError, ValueError):
            self.op_slider.setValue(25)
        self.op_slider.setToolTip("Video opacity while Transparent is on (0 % = only the drawings)")
        hl.addWidget(self.op_slider)
        self.op_label = QtWidgets.QLabel(head)
        self.op_label.setMinimumWidth(theme.px(30))
        hl.addWidget(self.op_label)
        self.clear_btn.toggled.connect(self._transparency_changed)
        self.op_slider.valueChanged.connect(self._transparency_changed)
        self.cache_btn = QtWidgets.QToolButton(head)
        self.cache_btn.setText("Cache")
        self.cache_btn.setCheckable(True)
        self.cache_btn.setChecked(qs.value("sequencer/cache", True) not in (False, "false"))
        self.cache_btn.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        self.cache_btn.setToolTip("Cached playback (like the Timeline's Cache): frames of the Qt Shell preview "
                                  "drawn once are kept and play back in real time – the green line above the "
                                  "strips. Any change to the strips (or to the scene, when shots are in the edit) "
                                  "drops the cache. Hold for Cache All Frames / Flush.")
        cmenu = QtWidgets.QMenu(self.cache_btn)
        cmenu.addAction("Cache All Frames", lambda: self.ed.cache_all())
        cmenu.addAction("Flush Cache", lambda: self.qt.flush())
        cmenu.addSeparator()
        busy = cmenu.addAction("Keep Caching While the Mouse Moves")
        busy.setCheckable(True)
        busy.setToolTip("Auto caching goes on while you move the mouse or type – also in Qt Preferences → Viewport")
        from . import playcache

        def sync_busy(b=busy):
            b.blockSignals(True)
            b.setChecked(playcache.while_moving())
            b.blockSignals(False)
        cmenu.aboutToShow.connect(sync_busy)
        busy.toggled.connect(playcache.set_while_moving)
        self.cache_btn.setMenu(cmenu)
        self.cache_btn.toggled.connect(self._cache_toggled)
        hl.addWidget(self.cache_btn)
        self.auto_btn = QtWidgets.QToolButton(head)
        self.auto_btn.setText("Auto")
        self.auto_btn.setCheckable(True)
        self.auto_btn.setChecked(qs.value("sequencer/auto_cache", False) in (True, "true"))
        self.auto_btn.setToolTip("Background caching (like the Timeline's Auto): while you don't work, the frames "
                                 "of the play range are cached for the Qt Shell preview – your current frame "
                                 "doesn't change.")
        self.auto_btn.toggled.connect(self._auto_toggled)
        hl.addWidget(self.auto_btn)
        hl.addStretch(1)
        lay.addWidget(head)
        self.stack = QtWidgets.QStackedWidget(self)
        self.host = PreviewHost(self.stack)
        self.qt = QtPreview(ed, self.stack)
        self.stack.addWidget(self.host)
        self.stack.addWidget(self.qt)
        lay.addWidget(self.stack, 1)
        self._transparency_changed(save=False)
        mode = QtCore.QSettings("QtShell", "QtShell").value("sequencer/preview_mode", "blender")
        self.set_mode(mode if mode in ("blender", "qt") else "blender", save=False)
        self.mode.activated.connect(lambda _i: self.set_mode(self.mode.currentData()))

    def is_qt(self):
        return self.stack.currentWidget() is self.qt

    def _cache_toggled(self, on):
        QtCore.QSettings("QtShell", "QtShell").setValue("sequencer/cache", bool(on))
        if not on:
            self.auto_btn.setChecked(False)
            if hasattr(self, "qt"):
                self.qt.flush()

    def _auto_toggled(self, on):
        QtCore.QSettings("QtShell", "QtShell").setValue("sequencer/auto_cache", bool(on))
        if on and not self.cache_btn.isChecked():
            self.cache_btn.setChecked(True)

    def transparent_on(self):
        return self.clear_btn.isChecked()

    def video_opacity(self):
        return self.op_slider.value() / 100.0

    def _transparency_changed(self, *_a, save=True):
        on = self.clear_btn.isChecked()
        self.op_slider.setEnabled(on)
        self.op_label.setText(f"{self.op_slider.value()} %")
        self.op_label.setEnabled(on)
        if save:
            qs = QtCore.QSettings("QtShell", "QtShell")
            qs.setValue("sequencer/transparent", on)
            qs.setValue("sequencer/video_opacity", self.op_slider.value())
        self.qt.update()

    def set_mode(self, mode, save=True):
        qt = mode == "qt"
        i = self.mode.findData(mode)
        if i >= 0 and i != self.mode.currentIndex():
            self.mode.setCurrentIndex(i)
        if not qt and self.qt.bp.enabled:
            self.ed.set_blue_pencil(False)
        self.stack.setCurrentWidget(self.qt if qt else self.host)
        self.bp_btn.setEnabled(qt)
        for w in (self.clear_btn, self.op_slider, self.op_label, self.cache_btn, self.auto_btn):
            w.setVisible(qt)
        if qt:
            self.qt.request()
        if save:
            QtCore.QSettings("QtShell", "QtShell").setValue("sequencer/preview_mode", mode)

    def _fill_bp_menu(self, m):
        from . import bluepencil, icons
        m.clear()
        cur = bluepencil.current_tool()
        for tid, name, icon, tip in bluepencil.TOOLS:
            a = m.addAction(icons.icon(icon), name)
            a.setToolTip(tip)
            if tid == cur:
                f = a.font()
                f.setBold(True)
                a.setFont(f)
            a.triggered.connect(lambda _c=False, t=tid: (bluepencil.set_variant(t), self.ed.set_blue_pencil(True)))


# ---------------------------------------------------------------- the dock widget
class VideoSequencer(QtWidgets.QWidget):
    PY = "qt_shell.api.video_sequencer()"

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self.meta_path = []          # names of the open metas (Maya-like "groups")
        self.render_version = 0      # +1 on every strip edit made here (drops the preview cache)
        self._cp_timer = None        # cached playback (Qt Shell preview, all frames cached)
        self._cp_frame = None
        self._audio = None
        self.snap_on = QtCore.QSettings("QtShell", "QtShell").value("sequencer/snap", True) not in (False, "false")
        self.show_seconds = QtCore.QSettings("QtShell", "QtShell").value("sequencer/seconds", False) in (True, "true")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._toolbar())
        self.split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        self.pane = PreviewPane(self, self.split)
        self.preview = self.pane.host
        self.qtprev = self.pane.qt
        self.view = SeqView(self, self.split)
        self.props = StripProps(self, self.split)
        self.split.addWidget(self.pane)
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
            hub.play_frame.connect(lambda _f: self.isVisible() and (self.view.update(), self.qtprev.request()))
        except Exception:
            pass
        hub.data_changed.connect(self.refresh)
        hub.file_loaded.connect(self._file_loaded)
        self._tick = QtCore.QTimer(self)
        self._tick.setInterval(250)
        self._tick.timeout.connect(self._poll)
        self._tick.start()
        self._sig = None
        self._ac_since = 0.0
        self._ac_key = None
        self._ac_next = 0.0
        self._ac_timer = QtCore.QTimer(self)
        self._ac_timer.setInterval(60)
        self._ac_timer.timeout.connect(self._auto_cache_step)
        self._ac_timer.start()
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
        if getattr(self, "_sizes_checked", None) != bpy.data.filepath + str(len(all_strips())):
            self._sizes_checked = bpy.data.filepath + str(len(all_strips()))
            try:
                n = fix_all_sizes()
                if n:
                    bridge.log(f"Video Sequencer: {n} colour strip(s) had a 1 × 1 px image – set to the scene size",
                               "INFO")
            except Exception:
                pass
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
        self.qtprev.request()

    def after_edit(self, props=True, edit=True):
        """edit=False: only the selection changed (the picture and its cache stay)."""
        if edit:
            self.render_version += 1
        if props:
            self.props.refresh(force=True)
        se = editor()
        if se is not None and edit:                       # Blender's frame cache does not always see RNA edits
            for s in {*(x for x in self.view.strips() if x.select), *([se.active_strip] if se.active_strip else [])}:
                try:
                    s.invalidate_cache("COMPOSITE")
                except Exception:
                    pass
        self.view.update()
        self.preview.redraw()
        self.qtprev.request()

    def _frame(self):
        if self.isVisible():
            self.view.update()
            self.props.refresh()
            self.qtprev.request()

    def _poll(self):
        """Strips changed elsewhere (Blender's operators, Python, undo) – a cheap signature check."""
        if not self.isVisible():
            return
        playing = blender_playing() or self.cached_playing()
        if not playing:
            try:
                self.sync_bp_tracks()
            except Exception:
                bridge.log(f"Video Sequencer: Blue Pencil tracks:\n{traceback.format_exc()}", "WARNING")
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
        self._bp_known = set()
        self.meta_path = []
        self.view._framed = False
        self.preview.reopen() if self.preview.ptr is not None or PreviewHost.current is self.preview \
            else close_stale_windows()
        QtCore.QTimer.singleShot(300, lambda: (self.view.frame_all(), self.refresh()))

    def showEvent(self, ev):
        super().showEvent(ev)
        QtCore.QTimer.singleShot(0, self.refresh)

    def shutdown(self):
        try:
            if self.cached_playing():
                self.stop_cached_play()
        except Exception:
            pass
        try:
            self.set_blue_pencil(False)
        except Exception:
            pass
        self.preview.close_window()
        unregister_handlers()

    # ---- playback cache of the Qt Shell preview (Cache / Auto, like the Timeline)
    def cache_on(self):
        return self.pane.is_qt() and self.pane.cache_btn.isChecked()

    def cache_limit_bytes(self):
        try:
            from . import playcache
            return min(int(playcache.limit_bytes()), 4 << 30)
        except Exception:
            return 2 << 30

    def _play_range(self):
        from .timeline import play_range
        a, b = play_range(bpy.context.scene)
        return list(range(a, b + 1))

    def cache_all(self):
        """Cache All Frames: renders the play range for the Qt Shell preview (Esc stops)."""
        from . import playcache
        if not self.pane.is_qt():
            self.pane.set_mode("qt")
        if not self.pane.cache_btn.isChecked():
            self.pane.cache_btn.setChecked(True)
        if playcache.pending_edits():
            self.status("Key or undo your unkeyed changes first – a frame change would reset them")
            return 0
        if blender_playing():
            self.play_sound()
        app_ = QtWidgets.QApplication.instance()

        def progress(f, n, total):
            self.status(f"Caching frame {f} ({n}/{total})…")
            app_.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents)
            return True

        n = self.qtprev.cache_frames(self._play_range(), progress=progress)
        self.qtprev.request()
        mb = sum(img.sizeInBytes() for img in self.qtprev.cache.values()) / 1048576
        self.status(f"Cached {len(self.qtprev.cache)} frame(s) of the Video Sequencer ({mb:.0f} MB)")
        return n

    def _auto_cache_step(self):
        """Background caching while the user is idle (a few frames per step, then a rest)."""
        try:
            if not (self.isVisible() and self.cache_on() and self.pane.auto_btn.isChecked()):
                return
            if (getattr(self.hub, "playing", False) or blender_playing() or self.cached_playing()
                    or bridge.is_rendering()):
                return
            if self.qtprev.bp.enabled and QtWidgets.QApplication.mouseButtons() != QtCore.Qt.NoButton:
                return
            now = time.perf_counter()
            if now < self._ac_next:
                return
            app_ = QtWidgets.QApplication
            if (app_.mouseButtons() != QtCore.Qt.NoButton or app_.activePopupWidget() is not None
                    or app_.activeModalWidget() is not None):
                return
            from . import playcache
            if not playcache.idle_enough(0.6):
                return
            key = self.qtprev.cache_key()
            if key != self._ac_key:
                self._ac_key = key                # something changed – wait until things settle
                self._ac_since = now
                return
            if now - self._ac_since < 0.6:
                return
            rng = self._play_range()
            keep = bpy.context.scene.frame_current
            i0 = rng.index(keep) if keep in rng else 0
            order = rng[i0:] + rng[:i0]
            if all(f in self.qtprev.cache for f in order):
                return
            if playcache.pending_edits():
                return
            t0 = time.perf_counter()
            self.qtprev.cache_frames(order, budget=0.03)
            self._ac_key = self.qtprev.cache_key()
            self._ac_next = time.perf_counter() + 2.0 * (time.perf_counter() - t0)
            self.view.update()
        except Exception as ex:
            bridge.log(f"Video Sequencer: background caching: {ex}", "WARNING")
            self._ac_next = time.perf_counter() + 5.0

    # ---- Blue Pencil tracks: layers drawn in the sequencer get their own strip ("pencil line")
    def mark_bp_layer(self):
        """After a stroke in the Qt Shell preview: the track follows at once."""
        self.sync_bp_tracks()

    def bp_tracks(self):
        se = editor()
        return [s for s in coll(se) if is_bp_track(s)] if se is not None else []

    def _migrate_bp_layers(self):
        """0.104.0 drew sequencer layers into the 3D view's layers (seq flag) – they become Video Editing layers."""
        from . import bluepencil
        moved = False
        for lay in bluepencil.data()["layers"]:
            if lay.pop("seq", None) and lay.get("space", "VIEWPORT") == "VIEWPORT":
                lay["space"] = "VIDEO"
                lay["camera"] = ""
                moved = True
        if moved:
            _bp_save()

    def sync_bp_tracks(self):
        """One track (strip) per Video Editing Blue Pencil layer: the layer's drawings are shown from the track's
        start to its end ("range" of the layer). Trim the track = change where the drawings show; move it = move
        the drawings with it; mute = hide; delete the track = delete the layer. Drawing outside the range extends
        it to the new key (+ hold)."""
        from . import bluepencil
        self._migrate_bp_layers()
        d = bluepencil.data()
        wanted = {lay["name"]: lay for lay in d["layers"] if lay.get("space", "VIEWPORT") == "VIDEO"}
        se = editor(bool(wanted))
        if se is None:
            return
        c = coll(se)
        changed = edited = False
        commit_msg = None
        known = getattr(self, "_bp_known", set())
        tracks = {}
        for s in list(c):
            if not is_bp_track(s):
                continue
            name = s.get(BP_PROP)
            if name not in wanted or name in tracks:
                c.remove(s)                      # its layer is gone (deleted / renamed) or a duplicate
                changed = True
                continue
            tracks[name] = s
        for name in list(known):                 # a track the user deleted: its layer goes too (like Blender)
            if name in wanted and name not in tracks:
                d["layers"].remove(wanted.pop(name))
                commit_msg = "Delete Layer (track deleted)"
        for name, lay in wanted.items():
            ks = bluepencil.keys(lay)
            rng = lay.get("range")
            if rng is None:
                auto = bp_track_range(lay)
                if auto is None:
                    continue                     # an empty layer: its track comes with the first drawing
                rng = list(auto)
                lay["range"] = rng
                edited = True
            a, b = int(rng[0]), int(rng[1])
            if ks and (ks[0] < a or ks[-1] >= b):        # drawn outside the track → it grows to the new key
                hold = max(int(round(fps())), 1)
                na = min(a, ks[0]) if ks[0] < a else a
                nb = max(b, ks[-1] + hold) if ks[-1] >= b else b
                if (na, nb) != (a, b):
                    a, b = na, nb
                    lay["range"] = [a, b]
                    edited = True
            s = tracks.get(name)
            if s is None:
                top = max((x.channel for x in c), default=0) + 1
                s = new_effect(se, "✎ " + name, "COLOR", free_channel(se, a, b, top), a, b - a)
                s.color = (0.31, 0.5, 0.88)
                s.blend_alpha = 0.0              # renders nothing – the drawings are Blue Pencil's
                s[BP_PROP] = name
                s[BP_START] = a
                s["qtshell_bp_end"] = b
                tracks[name] = s
                changed = True
                continue
            start = int(s.get(BP_START, a))
            end = int(s.get("qtshell_bp_end", b))
            fs, fe = s.frame_final_start, s.frame_final_end
            if (fs, fe) != (start, end) and not s.lock:
                if fe - fs == end - start:               # moved → the drawings move with it
                    delta = fs - start
                    if ks and not bluepencil.move_keys(lay, {k: k + delta for k in ks}):
                        delta = 0                        # keys would collide – the track goes back
                    if delta:
                        commit_msg = commit_msg or "Move drawings with the track"
                    a, b = a + delta, b + delta
                else:                                    # trimmed → the drawings show only in the new range
                    a, b = fs, fe
                    commit_msg = commit_msg or "Blue Pencil track range"
                lay["range"] = [a, b]
                changed = True
            vis = not s.mute
            if lay.get("visible", True) != vis:
                lay["visible"] = vis
                edited = True
            if (s.frame_final_start, s.frame_final_end) != (a, b):
                if b > s.frame_final_end:
                    s.frame_final_end = b
                    s.frame_final_start = a
                else:
                    s.frame_final_start = a
                    s.frame_final_end = b
                changed = True
            if int(s.get(BP_START, -10 ** 9)) != a:
                s[BP_START] = a
            if int(s.get("qtshell_bp_end", -10 ** 9)) != b:
                s["qtshell_bp_end"] = b
            label = "✎ " + name
            if s.name != label and not s.name.startswith(label):
                s.name = label
        self._bp_known = set(tracks)
        if commit_msg:
            bluepencil.commit(commit_msg)
        elif edited:
            _bp_save()
        if changed or edited or commit_msg:
            self.view.update()
            self.qtprev.update()

    # ---- Blue Pencil (Qt Shell preview)
    def set_blue_pencil(self, on):
        """Blue Pencil on the Qt Shell preview (switches the preview to Qt Shell's)."""
        on = bool(on)
        if on and not self.pane.is_qt():
            self.pane.set_mode("qt")
        if self.pane.bp_btn.isChecked() != on:
            self.pane.bp_btn.setChecked(on)        # toggled → here again
            return
        if on and blender_playing():
            self.play_sound()                      # stops Blender's playback
        if on and (self.split.sizes()[0] == 0):
            self.preview_btn.setChecked(True)
        self.qtprev.bp.set_enabled(on)
        self.qtprev.setCursor(QtCore.Qt.CrossCursor if on else QtCore.Qt.ArrowCursor)
        if on:
            self.qtprev.setFocus()
        self.qtprev.update()

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
        self.after_edit(edit=False)

    def set_active(self, s):
        se = editor()
        if se is not None and se.active_strip != s:
            se.active_strip = s
            self.after_edit(edit=False)

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
              "seq.play": self.play_sound, "seq.snap": lambda: self.snap_btn.toggle(),
              "seq.blue_pencil": lambda: self.set_blue_pencil(not self.qtprev.bp.enabled)}.get(aid)
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
        todo = [s for s in pool if not s.lock and not is_bp_track(s) and s.frame_final_start < f < s.frame_final_end]
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
            if df and not time_locked(s):        # effects with inputs follow their inputs
                s.frame_start += df
        order = sorted(strips, key=lambda s: s.channel, reverse=dch > 0)
        for s in order:
            if dch:
                s.channel = max(1, s.channel + dch)
        bridge.undo_push("Move Strips")
        timed = [s for s in strips if not time_locked(s)]
        msg = f"Moved {len(strips)} strip(s)"
        msg += f" {df:+d} frames" if df and timed else ""
        msg += f", {dch:+d} channels" if dch else ""
        if df and not timed:
            msg += " – effects follow their input strips"
        self.status(msg)
        self.after_edit()

    def trim(self, s, side, frame):
        if time_locked(s):
            self.status(f"“{s.name}” takes its length from its input strips – trim or move those")
            return
        try:
            if side == "l":
                s.frame_final_start = int(frame)
            else:
                s.frame_final_end = int(frame)
        except (AttributeError, TypeError, RuntimeError) as ex:
            self.status(f"“{s.name}” cannot be trimmed ({ex})")
            return
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
    def shown_frame(self):
        """The frame the sequencer shows: the cached playback's frame, else the Timeline's / the scene's."""
        if self._cp_frame is not None:
            return self._cp_frame
        f = getattr(self.hub, "display_frame", None)
        return int(bpy.context.scene.frame_current if f is None else f)

    # ---- cached playback: the Qt Shell preview plays straight from its cache in real time (like Blender's
    # preview) – no scene frame changes (the 3D views and Timeline are not redrawn per frame), sound via aud
    def cached_playing(self):
        return self._cp_timer is not None and self._cp_timer.isActive()

    def can_play_cached(self):
        if not (self.pane.is_qt() and self.cache_on()):
            return False
        self.qtprev.check_cache()
        rng = self._play_range()
        return bool(rng) and all(f in self.qtprev.cache for f in rng)

    def start_cached_play(self):
        rng = self._play_range()
        sc = bpy.context.scene
        self._cp_range = (rng[0], rng[-1])
        start = sc.frame_current if rng[0] <= sc.frame_current <= rng[-1] else rng[0]
        self._cp_start = start
        self._cp_t0 = time.perf_counter()
        self._cp_loop = -1
        self._cp_frame = start
        if self._cp_timer is None:
            self._cp_timer = QtCore.QTimer(self)
            self._cp_timer.setTimerType(QtCore.Qt.PreciseTimer)
            self._cp_timer.timeout.connect(self._cp_tick)
        self._cp_timer.setInterval(max(1, int(500 / fps())))
        self._cp_timer.start()
        self.play_btn.setText("Stop")
        self._cp_tick()

    def stop_cached_play(self):
        if self._cp_timer is not None:
            self._cp_timer.stop()
        self._audio_stop()
        f = self._cp_frame
        self._cp_frame = None
        self.play_btn.setText("Play")
        if f is not None and f != bpy.context.scene.frame_current:
            bpy.context.scene.frame_set(f)       # the scene follows to where playback stopped
        self.view.update()
        self.qtprev.request()

    def _cp_tick(self):
        a, b = self._cp_range
        span = b - a + 1
        n = int((time.perf_counter() - self._cp_t0) * fps())   # real time: late frames are skipped
        pos = (self._cp_start - a) + n
        loop = pos // span
        f = a + pos % span
        if loop != self._cp_loop:                # (re)start the sound at the start / each loop
            self._cp_loop = loop
            self._audio_play(f)
        if f == self._cp_frame and loop >= 0 and self.qtprev.image is not None and n:
            return
        self._cp_frame = f
        if not self.qtprev.show_cached(f):      # the cache changed under us – Blender plays instead
            self.stop_cached_play()
            self.play_sound()
            return
        self.view.update()

    def _audio_play(self, frame):
        """The sound strips from frame on, mixed with aud (Blender's audio library)."""
        self._audio_stop()
        try:
            import aud
            r = fps()
            mixed = None
            for s in all_strips():
                if s.type != "SOUND" or s.mute or s.sound is None or s.frame_final_end <= frame:
                    continue
                st = max(s.frame_final_start, frame)
                pos = (st - s.frame_start) / r + float(getattr(s, "sound_offset", 0.0) or 0.0)
                dur = (s.frame_final_end - st) / r
                snd = aud.Sound(bpy.path.abspath(s.sound.filepath)).limit(pos, pos + dur)
                vol = float(getattr(s, "volume", 1.0))
                if vol != 1.0:
                    snd = snd.volume(vol)
                if st > frame:
                    snd = snd.delay((st - frame) / r)
                mixed = snd if mixed is None else mixed.mix(snd)
            if mixed is not None:
                self._audio = aud.Device().play(mixed)
        except Exception as ex:
            bridge.log(f"Video Sequencer: cached playback without sound ({ex})", "WARNING")

    def _audio_stop(self):
        h, self._audio = getattr(self, "_audio", None), None
        if h is not None:
            try:
                h.stop()
            except Exception:
                pass

    def play_sound(self):
        if self.cached_playing():
            self.stop_cached_play()
            return
        if not blender_playing() and self.can_play_cached():
            self.start_cached_play()
            return
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
        try:
            if w is not None and a is not None:
                with bpy.context.temp_override(window=w, screen=w.screen, area=a):
                    bpy.ops.screen.animation_play()
            else:                                # Qt Shell preview: Blender's playback in its hidden window
                with bridge.blender_context():
                    bpy.ops.screen.animation_play()
        except Exception as ex:
            bridge.log(f"Video Sequencer: playback with sound failed ({ex}) – the Timeline plays", "WARNING")
            try:
                from . import app
                app._win.timeline.toggle_play()
            except Exception:
                pass
            return
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
        mv = coll(c).new_movie(name=name, filepath=path, channel=free_channel(c, f, f + 1, channel), frame_start=f,
                               **fit_kw(c, "new_movie"))
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
        s = coll(c).new_image(name=name, filepath=first, channel=free_channel(c, f, f + 1, channel), frame_start=f,
                              **fit_kw(c, "new_image"))
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

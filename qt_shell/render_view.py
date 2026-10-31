"""Render View – Blender's render window (Image Editor showing the Render Result) in Qt.

Header like Blender 5.2: View and Image menus, the Render Result image, render slots (Slot 1–8),
View Layer and Pass, Display Channels (Color & Alpha, Color, Alpha, Red, Green, Blue), zoom and the
sidebar toggle, Gizmos and Overlays toggles. The canvas: checkerboard behind transparent renders, mouse
wheel zooms around the mouse, middle mouse pans; the navigation gizmo (top right) zooms / pans by dragging.
Toolbar on the left (T) like Blender's Image Editor: Sample (left mouse shows the pixel under it – footer:
X / Y and R G B A) and Annotate (Annotate / Line / Polygon / Eraser – notes drawn over the render, one set
per render slot, colour and thickness in the header; Ctrl+Z removes the last change).
Top left: Frame | Time | Scene | View Layer | Camera like Blender's render stats. Sidebar (N): Image
and Metadata.

How the pixels get here (no image buffer of the Render Result is readable from Python):
- Combined: Image.save_render() to a PNG – with the scene's view transform, i.e. what Blender shows;
- View Layers / Passes: a multilayer OpenEXR written by save_render and read with OpenImageIO
  (bundled with Blender). Blender 5.x writes it as a multi-part file – one part per pass – so every
  part is read. The passes are the ones enabled in View Layer Properties → Passes.
- Render slots: Image.render_slots.active_index (save_render reads the active slot).

All keys live in keymap.py (area "Render View").
"""
import math
import os
import tempfile
import time

import bpy
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, icons, keymap, pytips, theme
from .dockable import Dockable

CHANNELS = [("COLOR_ALPHA", "Color & Alpha"), ("COLOR", "Color"), ("ALPHA", "Alpha"),
            ("RED", "Red"), ("GREEN", "Green"), ("BLUE", "Blue")]
TOOLS = [("SAMPLE", "Sample", "tool_sample",
          "Sample – hold the left mouse button to read the pixel under it (footer: X / Y, R G B A)"),
         ("ANNOTATE", "Annotate", "tool_annotate", "Annotate – draw notes over the render"),
         ("BLUE_PENCIL", "Blue Pencil", "tool_blue_pencil",
          "Blue Pencil – draw on the camera the picture was rendered with, at its frame: the same drawings the "
          "3D view shows through that camera (Blue Pencil panel: colour, size, layers)")]
ANNOTATE_VARIANTS = [
    ("FREEHAND", "Annotate", "tool_annotate", "Draw a free-hand note"),
    ("LINE", "Annotate Line", "tool_annotate_line", "Drag to draw a straight line"),
    ("POLYGON", "Annotate Polygon", "tool_annotate_polygon",
     "Click to add points; double-click, Enter or right click finishes"),
    ("ERASER", "Annotate Eraser", "tool_annotate_eraser", "Drag over strokes to erase them"),
]
NOTE_COLOR = "#619bc7"         # Blender's default annotation colour
ERASER_RADIUS = 20
ZOOM_RATIOS = [(8, "8:1"), (4, "4:1"), (2, "2:1"), (1, "1:1"), (0.5, "1:2"), (0.25, "1:4"), (0.125, "1:8")]
# Save As: filter → (media type, file format)
SAVE_FORMATS = [
    ("PNG (*.png)", "IMAGE", "PNG", ".png"),
    ("JPEG (*.jpg *.jpeg)", "IMAGE", "JPEG", ".jpg"),
    ("OpenEXR (*.exr)", "IMAGE", "OPEN_EXR", ".exr"),
    ("OpenEXR MultiLayer (*.exr)", "MULTI_LAYER_IMAGE", "OPEN_EXR_MULTILAYER", ".exr"),
    ("TIFF (*.tif *.tiff)", "IMAGE", "TIFF", ".tif"),
    ("WebP (*.webp)", "IMAGE", "WEBP", ".webp"),
    ("BMP (*.bmp)", "IMAGE", "BMP", ".bmp"),
]


def _api(call):
    return f"import qt_shell; qt_shell.api.render_view().{call}"


def _render_result():
    return bpy.data.images.get("Render Result")


def _tmp(name):
    return os.path.join(tempfile.gettempdir(), name)


# ---------------------------------------------------------------- image data
class _Layers:
    """Layers / passes of the multilayer EXR: {layer: {pass: [channel indices]}} + the float pixels."""

    def __init__(self):
        self.layers = {}
        self.pixels = None       # H × W × C float32
        self.names = []

    def load(self, path):
        import OpenImageIO as oiio
        inp = oiio.ImageInput.open(path)
        if inp is None:
            raise RuntimeError(oiio.geterror())
        # Blender 5.x writes multilayer OpenEXR as a multi-part file: every pass is its own part
        # (subimage) – reading only the first one gives just the Combined pass
        names, planes, size = [], [], None
        try:
            sub = 0
            while inp.seek_subimage(sub, 0):
                spec = inp.spec()
                part = spec.getattribute("oiio:subimagename") or spec.getattribute("name") or ""
                if size is None:
                    size = (spec.height, spec.width)
                px = inp.read_image("float")
                if px is not None and (spec.height, spec.width) == size:
                    px = np.asarray(px, dtype=np.float32).reshape(spec.height, spec.width, -1)
                    for c, ch in enumerate(spec.channelnames):
                        full = ch if ("." in ch or not part) else f"{part}.{ch}"
                        names.append(full)
                        planes.append(px[:, :, c])
                sub += 1
        finally:
            inp.close()
        self.names = names
        self.pixels = np.dstack(planes) if planes else None
        layers = {}
        for i, n in enumerate(self.names):
            parts = n.split(".")
            if len(parts) >= 3:
                layer, pas = ".".join(parts[:-2]), parts[-2]
            elif len(parts) == 2:
                layer, pas = "", parts[0]
            else:
                layer, pas = "", n
            layers.setdefault(layer, {}).setdefault(pas, []).append(i)
        self.layers = layers

    def image(self, layer, pas):
        """Pass as an 8-bit QImage for display (sRGB for colour passes, normalised for data passes)."""
        idx = self.layers.get(layer, {}).get(pas)
        if idx is None or self.pixels is None:
            return None
        px = self.pixels[:, :, idx].astype(np.float32)
        h, w = px.shape[:2]
        n = px.shape[2]
        low = pas.lower()
        if n == 1 or low in ("depth", "z", "mist"):
            v = px[:, :, 0]
            fin = np.isfinite(v) & (v < 1e9)
            if fin.any():
                lo, hi = float(v[fin].min()), float(v[fin].max())
                v = np.where(fin, (v - lo) / max(hi - lo, 1e-9), 1.0)
                if low in ("depth", "z"):
                    v = 1.0 - v               # near = bright
            rgb = np.repeat(np.clip(v, 0, 1)[:, :, None], 3, axis=2)
            a = np.ones((h, w), np.float32)
        else:
            rgb = px[:, :, :3] if n >= 3 else np.repeat(px[:, :, :1], 3, axis=2)
            a = px[:, :, 3] if n >= 4 else np.ones((h, w), np.float32)
            if low in ("normal", "vector", "position", "uv"):
                rgb = rgb * 0.5 + 0.5 if low == "normal" else rgb
                rgb = np.clip(rgb, 0, 1)
            else:                              # linear → sRGB
                c = np.clip(rgb, 0, None)
                rgb = np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)
        out = np.dstack([np.clip(rgb, 0, 1), np.clip(a, 0, 1)])
        out = np.ascontiguousarray((out * 255 + 0.5).astype(np.uint8))
        img = QtGui.QImage(out.data, w, h, 4 * w, QtGui.QImage.Format_RGBA8888)
        return img.mirrored(False, False).copy()

    def sample(self, layer, pas, x, y):
        idx = self.layers.get(layer, {}).get(pas)
        if idx is None or self.pixels is None:
            return None
        h, w = self.pixels.shape[:2]
        if not (0 <= x < w and 0 <= y < h):
            return None
        return [float(self.pixels[y, x, i]) for i in idx]


# ---------------------------------------------------------------- canvas
class _Canvas(QtWidgets.QWidget):
    """The image: checkerboard, zoom around the mouse, middle-mouse pan, left-mouse pixel sampling."""

    zoom_changed = QtCore.Signal(float)
    sampled = QtCore.Signal(object)      # (x, y) in image pixels or None

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.image = None                # QImage shown (after the channel filter)
        self.zoom = 1.0
        self.offset = QtCore.QPointF(0, 0)   # image centre relative to the widget centre (screen px)
        self._pan = None
        self._sampling = False
        self._stroke = None           # annotation being drawn (image coordinates)
        self._poly = None             # Annotate Polygon: points so far (the last follows the mouse)
        self._erasing = False
        self._nav = None              # navigation gizmo drag: ("zoom" | "pan", last mouse position)
        self._nav_hover = None
        self._mouse = None
        self.overlay = ""
        self.busy = ""
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMinimumSize(theme.px(200), theme.px(150))
        self._checker = self._make_checker()

    @staticmethod
    def _make_checker():
        s = theme.px(8)
        pm = QtGui.QPixmap(2 * s, 2 * s)
        pm.fill(QtGui.QColor(102, 102, 102))
        p = QtGui.QPainter(pm)
        p.fillRect(0, 0, s, s, QtGui.QColor(153, 153, 153))
        p.fillRect(s, s, s, s, QtGui.QColor(153, 153, 153))
        p.end()
        return pm

    def set_image(self, img, keep_view=True):
        first = self.image is None
        self.image = img
        if first or not keep_view:
            self.fit()
        self.update()

    def image_rect(self):
        if self.image is None:
            return QtCore.QRectF()
        dpr = self.devicePixelRatioF()
        w, h = self.image.width() * self.zoom / dpr, self.image.height() * self.zoom / dpr
        c = QtCore.QPointF(self.width() / 2, self.height() / 2) + self.offset
        return QtCore.QRectF(c.x() - w / 2, c.y() - h / 2, w, h)

    def fit(self):
        """Frame All (Home): the whole image in the view, never above 1:1 for small renders."""
        if self.image is None:
            return
        dpr = self.devicePixelRatioF()
        m = theme.px(24)
        z = min((self.width() - m) * dpr / max(self.image.width(), 1),
                (self.height() - m) * dpr / max(self.image.height(), 1))
        self.set_zoom(min(z, 1.0) if z > 0 else 1.0, reset_offset=True)

    def set_zoom(self, z, anchor=None, reset_offset=False):
        z = max(0.02, min(64.0, z))
        if reset_offset:
            self.offset = QtCore.QPointF(0, 0)
        elif anchor is not None and self.zoom > 0:
            c = QtCore.QPointF(self.width() / 2, self.height() / 2) + self.offset
            self.offset += (anchor - c) * (1 - z / self.zoom)
        self.zoom = z
        self.zoom_changed.emit(z)
        self.update()

    def zoom_step(self, factor, anchor=None):
        self.set_zoom(self.zoom * factor, anchor)

    def pixel_at(self, pos):
        r = self.image_rect()
        if self.image is None or r.width() <= 0:
            return None
        x = int(math.floor((pos.x() - r.x()) / r.width() * self.image.width()))
        y = int(math.floor((pos.y() - r.y()) / r.height() * self.image.height()))
        if 0 <= x < self.image.width() and 0 <= y < self.image.height():
            return x, y
        return None

    def to_image(self, pos):
        """Screen → image coordinates (float pixels from the top-left corner)."""
        r = self.image_rect()
        return ((pos.x() - r.x()) / r.width() * self.image.width(),
                (pos.y() - r.y()) / r.height() * self.image.height())

    def to_screen(self, x, y):
        r = self.image_rect()
        return QtCore.QPointF(r.x() + x / self.image.width() * r.width(),
                              r.y() + y / self.image.height() * r.height())

    def nav_buttons(self):
        """The navigation gizmo (top right): zoom and pan buttons (centre, radius)."""
        R = theme.px(14)
        x = self.width() - theme.px(24)
        return {"zoom": (QtCore.QPointF(x, theme.px(24)), R), "pan": (QtCore.QPointF(x, theme.px(58)), R)}

    def _nav_at(self, pos):
        if not self.view.show_gizmos:
            return None
        for k, (c, R) in self.nav_buttons().items():
            if math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= R:
                return k
        return None

    def _paint_notes(self, p):
        strokes = list(self.view.annotations())
        if self._stroke:
            strokes.append({"pts": self._stroke, "color": self.view.note_color, "width": self.view.note_width})
        if self._poly:
            strokes.append({"pts": self._poly, "color": self.view.note_color, "width": self.view.note_width})
        p.setBrush(QtCore.Qt.NoBrush)
        for st in strokes:
            pts = [self.to_screen(x, y) for x, y in st["pts"]]
            if not pts:
                continue
            pen = QtGui.QPen(QtGui.QColor(st["color"]), max(1.0, st["width"] * theme.ui_scale))
            pen.setCapStyle(QtCore.Qt.RoundCap)
            pen.setJoinStyle(QtCore.Qt.RoundJoin)
            p.setPen(pen)
            if len(pts) == 1:
                p.drawPoint(pts[0])
            else:
                p.drawPolyline(QtGui.QPolygonF(pts))

    def _paint_gizmo(self, p):
        for k, (c, R) in self.nav_buttons().items():
            hov = self._nav_hover == k or (self._nav is not None and self._nav[0] == k)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(255, 255, 255, 60) if hov else QtGui.QColor(0, 0, 0, 90))
            p.drawEllipse(c, R, R)
            pm = icons.pixmap("zoom" if k == "zoom" else "pan", theme.px(16))
            if not pm.isNull():
                p.drawPixmap(QtCore.QRectF(c.x() - theme.px(8), c.y() - theme.px(8), theme.px(16), theme.px(16)),
                             pm, QtCore.QRectF(pm.rect()))

    # --- painting
    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(48, 48, 48))
        if self.image is not None:
            r = self.image_rect()
            if self.view.channel in ("COLOR_ALPHA",):
                p.fillRect(r, QtGui.QBrush(self._checker))
            p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, self.zoom < 1.0)
            p.drawImage(r, self.image)
            p.setPen(QtGui.QPen(QtGui.QColor(20, 20, 20), 1))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawRect(r.adjusted(-0.5, -0.5, 0.5, 0.5))
            if self.view.show_overlays:
                p.setRenderHint(QtGui.QPainter.Antialiasing)
                self.view.bp.paint_all(p, layers=self.view.bp_layers_shown())
                self._paint_notes(p)
            elif self.view.bp.enabled:
                self.view.bp.paint_all(p, layers=False)
            if (self.view.tool == "ANNOTATE" and self.view.annotate_variant == "ERASER" and self._mouse is not None
                    and self.underMouse()):
                p.setRenderHint(QtGui.QPainter.Antialiasing)
                p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1, QtCore.Qt.DashLine))
                p.setBrush(QtGui.QColor(255, 255, 255, 18 if self._erasing else 0))
                rr = ERASER_RADIUS * theme.ui_scale
                p.drawEllipse(self._mouse, rr, rr)
        else:
            p.setPen(QtGui.QColor(150, 150, 150))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter,
                       keymap.render("Nothing rendered yet – Render Image ({window.render})"))
        if self.view.show_gizmos:
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            self._paint_gizmo(p)
        text = self.busy or (self.overlay if self.view.show_overlays else "")
        if text:
            f = p.font()
            f.setPixelSize(theme.fs(12))
            p.setFont(f)
            m = theme.px(8)
            br = p.fontMetrics().boundingRect(QtCore.QRect(m, m, self.width() - 2 * m, 200),
                                              QtCore.Qt.TextWordWrap, text)
            p.setPen(QtGui.QColor(0, 0, 0, 200))
            p.drawText(br.translated(1, 1), QtCore.Qt.TextWordWrap, text)
            p.setPen(QtGui.QColor(235, 235, 235))
            p.drawText(br, QtCore.Qt.TextWordWrap, text)
        p.end()

    # --- mouse
    def wheelEvent(self, ev):
        if self.view.bp.enabled and self.view.bp.wheel(ev):     # Ctrl + wheel: Blue Pencil size
            return
        steps = ev.angleDelta().y() / 120.0
        if steps:
            self.zoom_step(1.25 ** steps, ev.position())

    def mousePressEvent(self, ev):
        self.setFocus()
        pos = ev.position()
        nav = self._nav_at(pos) if ev.button() == QtCore.Qt.LeftButton else None
        if nav is not None:                   # navigation gizmo: drag to zoom / pan
            self._nav = (nav, pos)
            self.setCursor(QtCore.Qt.SizeVerCursor if nav == "zoom" else QtCore.Qt.ClosedHandCursor)
            self.update()
        elif self.view.bp.enabled and self.image is not None and self.view.bp.press(ev, pos):
            pass                              # Blue Pencil (Alt / middle mouse still navigate)
        elif ev.button() == QtCore.Qt.MiddleButton or (
                ev.button() == QtCore.Qt.LeftButton and ev.modifiers() & QtCore.Qt.AltModifier):
            self._pan = pos
            self.setCursor(QtCore.Qt.ClosedHandCursor)
        elif ev.button() == QtCore.Qt.LeftButton and self.view.tool == "ANNOTATE" and self.image is not None:
            v = self.view.annotate_variant
            if v == "ERASER":
                self._erasing = True
                self.view.annotation_snapshot()
                self._erase(pos)
            elif v == "POLYGON":
                if self._poly is None:
                    self._poly = [self.to_image(pos)]
                else:
                    self._poly[-1] = self.to_image(pos)     # the point following the mouse becomes fixed
                self._poly.append(self.to_image(pos))
            else:
                self._stroke = [self.to_image(pos)]
            self.update()
        elif ev.button() == QtCore.Qt.LeftButton:
            self._sampling = True             # Blender: left mouse samples the pixel
            self.sampled.emit(self.pixel_at(pos))
        elif ev.button() == QtCore.Qt.RightButton:
            if self._poly:
                self.finish_polygon()
                return
            self.view.context_menu(ev.globalPosition().toPoint())

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        self._mouse = pos
        if self._nav is not None:
            kind, last = self._nav
            d = pos - last
            self._nav = (kind, pos)
            if kind == "zoom":
                self.zoom_step(1.01 ** (-d.y() + d.x()), QtCore.QPointF(self.width() / 2, self.height() / 2))
            else:
                self.offset += d
                self.update()
        elif self._pan is not None:
            d = pos - self._pan
            self._pan = pos
            self.offset += d
            self.update()
        elif self.view.bp.enabled and self.view.bp.move(ev, pos):
            pass
        elif self._sampling:
            self.sampled.emit(self.pixel_at(pos))
        elif self._erasing:
            self._erase(pos)
        elif self._stroke is not None:
            q = self.to_image(pos)
            if self.view.annotate_variant == "LINE":
                self._stroke[1:] = [q]
            else:
                last = self.to_screen(*self._stroke[-1])
                if abs(pos.x() - last.x()) + abs(pos.y() - last.y()) >= 2:
                    self._stroke.append(q)
            self.update()
        elif self._poly:
            self._poly[-1] = self.to_image(pos)
            self.update()
        else:
            hov = self._nav_at(pos)
            if hov != self._nav_hover:
                self._nav_hover = hov
                self.setToolTip({"zoom": "Zoom – drag up / down", "pan": "Move the view – drag"}.get(hov, ""))
                self.update()
            if self.view.tool == "ANNOTATE" and self.view.annotate_variant == "ERASER":
                self.update()

    def mouseReleaseEvent(self, ev):
        if self._nav is not None:
            self._nav = None
            self.unsetCursor()
            self.update()
            return
        if self._pan is not None:
            self._pan = None
            self.unsetCursor()
            return
        if self.view.bp.enabled and self.view.bp.release(ev, ev.position()):
            return
        if ev.button() != QtCore.Qt.LeftButton:
            return
        if self._sampling:
            self._sampling = False
            self.sampled.emit(None)
        elif self._erasing:
            self._erasing = False
            self.update()
        elif self._stroke is not None:
            pts, self._stroke = self._stroke, None
            if self.view.annotate_variant == "LINE" and len(pts) < 2:
                pts = []
            if len(pts) == 1:
                pts = [pts[0], (pts[0][0] + 0.5, pts[0][1])]
            if pts:
                self.view.add_annotation(pts)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == QtCore.Qt.MiddleButton:
            self.fit()
        elif self.view.bp.enabled and self.view.bp.double_click(ev, ev.position()):
            pass
        elif ev.button() == QtCore.Qt.LeftButton and self._poly:
            self.finish_polygon()

    def leaveEvent(self, ev):
        self._nav_hover = None
        self.update()
        super().leaveEvent(ev)

    def finish_polygon(self):
        pts, self._poly = self._poly, None
        if pts and len(pts) > 2:
            self.view.add_annotation(pts[:-1])      # the last point follows the mouse
        self.update()

    def cancel_annotation(self):
        busy = bool(self._poly or self._stroke)
        self._poly = None
        self._stroke = None
        self.update()
        return busy

    def _erase(self, pos):
        notes = self.view.annotations()
        r = ERASER_RADIUS * theme.ui_scale
        out, changed = [], False
        for st in notes:
            cur, hit = [], False
            for x, y in st["pts"]:
                q = self.to_screen(x, y)
                if math.hypot(q.x() - pos.x(), q.y() - pos.y()) <= r:
                    hit = True
                    if len(cur) > 1:
                        out.append(dict(st, pts=cur))
                    cur = []
                else:
                    cur.append((x, y))
            if not hit:
                out.append(st)
                continue
            changed = True
            if len(cur) > 1:
                out.append(dict(st, pts=cur))
        if changed:
            self.view.set_annotations(out, snapshot=False)
        self._mouse = pos
        self.update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.update()


class _VariantButton(QtWidgets.QToolButton):
    """The Annotate button of the toolbar: hold or right click it for Annotate / Line / Polygon / Eraser."""

    def __init__(self, parent, view):
        super().__init__(parent)
        self.view = view
        m = QtWidgets.QMenu(self)
        m.setToolTipsVisible(True)
        m.aboutToShow.connect(self._fill)
        self.setMenu(m)
        self.setPopupMode(QtWidgets.QToolButton.DelayedPopup)

    tool_id = "ANNOTATE"

    def _variants(self):
        return ANNOTATE_VARIANTS, self.view.annotate_variant

    def _fill(self):
        m = self.menu()
        m.clear()
        variants, cur = self._variants()
        for vid, name, icon, tip in variants:
            a = m.addAction(icons.icon(icon), name)
            a.setToolTip(tip)
            if cur == vid:      # no check mark next to an icon: bold
                f = a.font()
                f.setBold(True)
                a.setFont(f)
            pytips.tag(a, _api(f"set_tool('{self.tool_id}', '{vid}')"))
            a.triggered.connect(lambda _c=False, v=vid: self.view.set_tool(self.tool_id, v))

    def contextMenuEvent(self, ev):
        self.showMenu()
        ev.accept()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(225, 225, 225, 200))
        r = self.rect()
        k = theme.px(5)
        x, y = r.right() - theme.px(2), r.bottom() - theme.px(2)
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, y - k), QtCore.QPointF(x, y), QtCore.QPointF(x - k, y)]))
        p.end()


class _BPButton(_VariantButton):
    """The Blue Pencil button: hold or right click it for Pencil, Brush, Eraser, Text, shapes, Transform."""
    tool_id = "BLUE_PENCIL"

    def _variants(self):
        from . import bluepencil
        return bluepencil.TOOLS, bluepencil.current_tool()


# ---------------------------------------------------------------- window
class RenderView(QtWidgets.QWidget, Dockable):
    """Blender's render window: shows the Render Result with the header, canvas, sidebar and footer."""

    def __init__(self, main_window):
        super().__init__(main_window, QtCore.Qt.Window)
        self._init_dockable(main_window, "render_view", "Render", QtCore.Qt.RightDockWidgetArea)
        self.mw = main_window
        self.setWindowTitle("Blender Render")
        self.setObjectName("qtshell_render_view")
        self.resize(theme.px(1000), theme.px(680))
        self.channel = "COLOR_ALPHA"
        self.layer = None
        self.pas = "Combined"
        self._combined = None             # QImage of the Combined pass (display transform)
        self._exr = _Layers()
        self._exr_ok = None               # None = not read yet, False = unavailable, True = read
        self._info = {}                   # metadata of the shown result
        self._slot_info = {}              # slot index → metadata of the render in that slot (like Blender)
        self._slot_burn = {}              # slot index → {frame, camera, mats} for the burn-in of drawings
        self._external = None             # a picture that isn't the Render Result (Viewport Render)
        self._render_start = None
        self._save_path = ""
        st = QtCore.QSettings("QtShell", "QtShell")
        self.tool = str(st.value("render_view/tool", "SAMPLE"))
        if self.tool not in [t[0] for t in TOOLS]:
            self.tool = "SAMPLE"
        self.annotate_variant = str(st.value("render_view/annotate_variant", "FREEHAND"))
        if self.annotate_variant not in [v[0] for v in ANNOTATE_VARIANTS]:
            self.annotate_variant = "FREEHAND"
        self.show_overlays = str(st.value("render_view/overlays", "true")).lower() == "true"
        self.show_gizmos = str(st.value("render_view/gizmos", "true")).lower() == "true"
        self.note_color = str(st.value("render_view/annotate_color", NOTE_COLOR))
        try:
            self.note_width = int(st.value("render_view/annotate_thickness", 3))
        except (TypeError, ValueError):
            self.note_width = 3
        self._notes = {}                  # render slot → annotation strokes {"pts", "color", "width"}
        self._notes_undo = {}             # render slot → earlier stroke lists (Ctrl+Z)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_header())
        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.toolbar = self._build_toolbar()
        body.addWidget(self.toolbar)
        self.canvas = _Canvas(self)
        from . import bluepencil
        self.bp = bluepencil.ImageBPTools(self.canvas, self.bp_camera, self.canvas.image_rect, self.bp_frame)
        bluepencil.signals.changed.connect(self._bp_changed)
        bluepencil.tool_state().changed.connect(self._sync_tools)
        self.canvas.zoom_changed.connect(self._zoom_changed)
        self.canvas.sampled.connect(self._sampled)
        body.addWidget(self.canvas, 1)
        self.sidebar = self._build_sidebar()
        body.addWidget(self.sidebar)
        lay.addLayout(body, 1)
        self.footer = QtWidgets.QLabel(self)
        self.footer.setContentsMargins(theme.px(8), theme.px(2), theme.px(8), theme.px(2))
        self.footer.setProperty("dim", True)
        lay.addWidget(self.footer)
        self.sidebar.setVisible(str(QtCore.QSettings("QtShell", "QtShell").value(
            "render_view/sidebar", "false")).lower() == "true")
        self.toolbar.setVisible(str(QtCore.QSettings("QtShell", "QtShell").value(
            "render_view/toolbar", "true")).lower() == "true")
        self._sync_tools()
        keymap.notifier.changed.connect(self._update_tips)
        self._update_tips()
        self._update_footer()

    # ------------------------------------------------------------ header
    def _tool(self, icon=None, text="", tip="", checkable=False):
        b = QtWidgets.QToolButton(self)
        if icon:
            icons.set_icon(b, icon)
        if text:
            b.setText(text)
            b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon if icon else QtCore.Qt.ToolButtonTextOnly)
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.setCheckable(checkable)
        return b

    def _build_header(self):
        bar = QtWidgets.QFrame(self)
        bar.setObjectName("qtshell_render_header")
        bar.setStyleSheet("QFrame#qtshell_render_header { background: #303030; border-bottom: 1px solid #1d1d1d; }")
        h = QtWidgets.QHBoxLayout(bar)
        h.setContentsMargins(theme.px(6), theme.px(3), theme.px(6), theme.px(3))
        h.setSpacing(theme.px(4))
        ed = QtWidgets.QLabel(bar)
        pm = icons.pixmap("image", theme.px(16))
        if not pm.isNull():
            ed.setPixmap(pm)
        ed.setToolTip("Image Editor – Render Result")
        h.addWidget(ed)
        self.view_menu = QtWidgets.QMenu("View", self)
        self.view_menu.aboutToShow.connect(self._fill_view_menu)
        self.image_menu = QtWidgets.QMenu("Image", self)
        self.image_menu.aboutToShow.connect(self._fill_image_menu)
        for m in (self.view_menu, self.image_menu):
            m.setToolTipsVisible(True)
            b = QtWidgets.QToolButton(bar)
            b.setText(m.title())
            b.setMenu(m)
            b.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            b.setAutoRaise(True)
            b.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
            h.addWidget(b)
        h.addSpacing(theme.px(8))
        img = QtWidgets.QComboBox(bar)
        img.addItem(icons.icon("render_on"), "Render Result")
        img.setToolTip("The image shown: Blender's Render Result")
        pytips.tag(img, 'bpy.data.images["Render Result"]')
        h.addWidget(img)
        self.slot_combo = QtWidgets.QComboBox(bar)
        self.slot_combo.setMinimumContentsLength(7)
        self.slot_combo.activated.connect(lambda i: self.set_slot(i))
        pytips.tag(self.slot_combo, 'bpy.data.images["Render Result"].render_slots.active_index = 0')
        h.addWidget(self.slot_combo)
        self.layer_combo = QtWidgets.QComboBox(bar)
        self.layer_combo.setMinimumContentsLength(9)
        self.layer_combo.activated.connect(lambda _i: self._pick_layer(self.layer_combo.currentData()))
        self.layer_combo.setToolTip("View Layer")
        h.addWidget(self.layer_combo)
        self.pass_combo = QtWidgets.QComboBox(bar)
        self.pass_combo.setMinimumContentsLength(9)
        self.pass_combo.activated.connect(lambda _i: self._pick_pass(self.pass_combo.currentData()))
        pytips.tag(self.pass_combo, _api('set_pass("Depth")   # passes(): what the result has'))
        h.addWidget(self.pass_combo)
        h.addSpacing(theme.px(8))
        # options of the Annotate tool (like Blender's tool header)
        self.note_opts = QtWidgets.QWidget(bar)
        no = QtWidgets.QHBoxLayout(self.note_opts)
        no.setContentsMargins(0, 0, 0, 0)
        no.setSpacing(theme.px(4))
        self.note_color_btn = QtWidgets.QToolButton(self.note_opts)
        self.note_color_btn.setAutoRaise(True)
        self.note_color_btn.setToolTip("Annotation colour")
        self.note_color_btn.clicked.connect(self._pick_note_color)
        pytips.tag(self.note_color_btn, _api('set_annotation_style(color="#619bc7", width=3)'))
        no.addWidget(self.note_color_btn)
        self.note_width_spin = QtWidgets.QSpinBox(self.note_opts)
        self.note_width_spin.setRange(1, 10)
        self.note_width_spin.setPrefix("Thickness ")
        self.note_width_spin.setValue(self.note_width)
        self.note_width_spin.setToolTip("Thickness of new annotation strokes (px)")
        self.note_width_spin.valueChanged.connect(lambda v: self.set_annotation_style(width=v))
        pytips.tag(self.note_width_spin, _api("set_annotation_style(width=3)"))
        no.addWidget(self.note_width_spin)
        clear = self._tool("trash", "", "Clear the annotations of this render slot")
        if clear.icon().isNull():
            clear.setText("✕")
        clear.clicked.connect(self.clear_annotations)
        pytips.tag(clear, _api("clear_annotations()"))
        no.addWidget(clear)
        h.addWidget(self.note_opts)
        h.addStretch(1)
        self.gizmo_btn = self._tool("gizmo", "", "", checkable=True)
        self.gizmo_btn.setChecked(self.show_gizmos)
        self.gizmo_btn.toggled.connect(self.set_gizmos)
        pytips.tag(self.gizmo_btn, _api("set_gizmos(True)"))
        h.addWidget(self.gizmo_btn)
        self.overlay_btn = self._tool("overlays", "", "", checkable=True)
        self.overlay_btn.setChecked(self.show_overlays)
        self.overlay_btn.toggled.connect(self.set_overlays)
        pytips.tag(self.overlay_btn, _api("set_overlays(True)"))
        h.addWidget(self.overlay_btn)
        self.burn_btn = self._tool("tool_blue_pencil", "", "", checkable=True)
        from . import burnin
        self.burn_btn.setChecked(burnin.enabled())
        self.burn_btn.setToolTip("Burn In – show (and save) the render with the Blue Pencil drawings of the camera "
                                 "and the annotations (Render → Burn In Blue Pencil / Annotations)")
        self.burn_btn.toggled.connect(lambda on: burnin.set_enabled(on))
        pytips.tag(self.burn_btn, "qt_shell.burnin.set_enabled(True)")
        burnin.signals.changed.connect(self._burn_changed)
        h.addWidget(self.burn_btn)
        h.addSpacing(theme.px(6))
        self.channel_combo = QtWidgets.QComboBox(bar)
        for cid, label in CHANNELS:
            self.channel_combo.addItem(label, cid)
        self.channel_combo.setToolTip("Display Channels")
        self.channel_combo.activated.connect(lambda _i: self.set_channel(self.channel_combo.currentData()))
        pytips.tag(self.channel_combo, _api("set_channel('COLOR_ALPHA')   # COLOR, ALPHA, RED, GREEN, BLUE"))
        h.addWidget(self.channel_combo)
        self.zoom_label = QtWidgets.QLabel("100%", bar)
        self.zoom_label.setMinimumWidth(theme.px(48))
        self.zoom_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.zoom_label.setToolTip("Zoom")
        h.addWidget(self.zoom_label)
        self.fit_btn = self._tool("zoom", "", "")
        self.fit_btn.clicked.connect(lambda: self.canvas.fit())
        pytips.tag(self.fit_btn, _api("fit()"))
        h.addWidget(self.fit_btn)
        self.sidebar_btn = self._tool("sidebar", "", "", checkable=True)
        if self.sidebar_btn.icon().isNull():
            self.sidebar_btn.setText("◨")
        self.sidebar_btn.toggled.connect(self.set_sidebar)
        pytips.tag(self.sidebar_btn, _api("set_sidebar(True)"))
        h.addWidget(self.sidebar_btn)
        self.cancel_btn = self._tool("render_cancel", "Cancel", "")
        keymap.tip(self.cancel_btn, "Cancel Render – stop the running render ({window.render_cancel})")
        self.cancel_btn.clicked.connect(lambda: self.mw.cancel_render())
        self.cancel_btn.hide()
        h.addWidget(self.cancel_btn)
        self.dock_btn = self._tool("dock", "", "Dock – put the render view into the Qt Shell window (drag its "
                                   "title to any side, tab it with other editors); off: a separate window",
                                   checkable=True)
        if self.dock_btn.icon().isNull():
            self.dock_btn.setText("⧉")
        self.dock_btn.setChecked(self.docked)
        self.dock_btn.toggled.connect(self.set_docked)
        pytips.tag(self.dock_btn, _api("set_docked(True)"))
        h.addWidget(self.dock_btn)
        return bar

    # ------------------------------------------------------------ toolbar (left)
    def _build_toolbar(self):
        w = QtWidgets.QFrame(self)
        w.setObjectName("qtshell_render_toolbar")
        w.setStyleSheet(
            "QFrame#qtshell_render_toolbar { background: #2b2b2b; border-right: 1px solid #1d1d1d; }"
            "QToolButton { background: transparent; border: 1px solid transparent; border-radius: 3px; }"
            "QToolButton::menu-indicator { image: none; width: 0px; }"
            f"QToolButton:checked {{ background: {theme.C['highlight']}; }}\n" + theme.hover_qss())
        v = QtWidgets.QVBoxLayout(w)
        m = theme.px(3)
        v.setContentsMargins(m, theme.px(6), m, m)
        v.setSpacing(theme.px(2))
        self.tool_buttons = {}
        group = QtWidgets.QButtonGroup(w)
        group.setExclusive(True)
        for tid, name, icon, tip in TOOLS:
            b = _VariantButton(w, self) if tid == "ANNOTATE" else _BPButton(w, self) if tid == "BLUE_PENCIL" \
                else QtWidgets.QToolButton(w)
            b.setCheckable(True)
            b.setFixedSize(theme.px(30), theme.px(30))
            icons.set_icon(b, icon)
            if b.icon().isNull():
                b.setText(name[0])
            b.clicked.connect(lambda _c=False, t=tid: self.set_tool(t))
            group.addButton(b)
            v.addWidget(b)
            self.tool_buttons[tid] = b
        v.addStretch(1)
        return w

    def _sync_tools(self):
        try:
            for tid, b in self.tool_buttons.items():
                b.setChecked(tid == self.tool)
            vinfo = dict((x[0], x) for x in ANNOTATE_VARIANTS)[self.annotate_variant]
            icons.set_icon(self.tool_buttons["ANNOTATE"], vinfo[2])
            from . import bluepencil
            binfo = dict((x[0], x) for x in bluepencil.TOOLS).get(bluepencil.current_tool())
            if binfo:
                icons.set_icon(self.tool_buttons["BLUE_PENCIL"], binfo[2])
            self.note_opts.setVisible(self.tool == "ANNOTATE")
            self.bp.set_enabled(self.tool == "BLUE_PENCIL")
            pm = QtGui.QPixmap(theme.px(28), theme.px(14))
            pm.fill(QtGui.QColor(self.note_color))
            self.note_color_btn.setIcon(QtGui.QIcon(pm))
            self.note_color_btn.setIconSize(pm.size())
            self.canvas.setCursor(QtCore.Qt.CrossCursor if self.tool in ("ANNOTATE", "BLUE_PENCIL")
                                  else QtCore.Qt.ArrowCursor)
            self._update_tips()
        except (RuntimeError, AttributeError):
            pass

    def set_tool(self, tool, variant=None):
        """Toolbar tool: 'SAMPLE', 'ANNOTATE' (variant FREEHAND, LINE, POLYGON or ERASER) or 'BLUE_PENCIL'
        (variant PENCIL, BRUSH, ERASER, TEXT, LINE, ARROW, ELLIPSE, RECT or TRANSFORM – shared with the 3D view)."""
        tool = str(tool).upper()
        if tool not in [t[0] for t in TOOLS]:
            raise ValueError(f"Unknown tool {tool!r} – SAMPLE, ANNOTATE or BLUE_PENCIL")
        st = QtCore.QSettings("QtShell", "QtShell")
        if tool == "BLUE_PENCIL" and variant is not None:
            from . import bluepencil
            variant = str(variant).upper()
            if variant not in bluepencil.TOOL_IDS:
                raise ValueError(f"Unknown Blue Pencil tool {variant!r} – {', '.join(bluepencil.TOOL_IDS)}")
            bluepencil.set_variant(variant)
            variant = None
        if variant is not None:
            variant = str(variant).upper()
            if variant not in [x[0] for x in ANNOTATE_VARIANTS]:
                raise ValueError(f"Unknown variant {variant!r} – FREEHAND, LINE, POLYGON or ERASER")
            self.annotate_variant = variant
            st.setValue("render_view/annotate_variant", variant)
        self.canvas.finish_polygon() if self.canvas._poly else None
        self.tool = tool
        st.setValue("render_view/tool", tool)
        self._sync_tools()
        self.canvas.update()

    def set_toolbar(self, on):
        self.toolbar.setVisible(bool(on))
        QtCore.QSettings("QtShell", "QtShell").setValue("render_view/toolbar", "true" if on else "false")

    def set_overlays(self, on):
        """Overlays: annotations and the render info text on the image."""
        self.show_overlays = bool(on)
        QtCore.QSettings("QtShell", "QtShell").setValue("render_view/overlays", "true" if on else "false")
        self._sync_toggle(self.overlay_btn, on)
        self.canvas.update()

    def set_gizmos(self, on):
        """Gizmos: the navigation gizmo (zoom / pan buttons) at the top right of the image."""
        self.show_gizmos = bool(on)
        QtCore.QSettings("QtShell", "QtShell").setValue("render_view/gizmos", "true" if on else "false")
        self._sync_toggle(self.gizmo_btn, on)
        self.canvas.update()

    @staticmethod
    def _sync_toggle(btn, on):
        if btn.isChecked() != bool(on):
            btn.blockSignals(True)
            btn.setChecked(bool(on))
            btn.blockSignals(False)

    # ------------------------------------------------------------ annotations
    def annotations(self, slot=None):
        """Annotation strokes of a render slot (default: the active one): [{"pts": [(x, y), …] in image
        pixels from the top-left corner, "color": "#rrggbb", "width": px}, …]."""
        return self._notes.get(self._active_slot() if slot is None else slot, [])

    def annotation_snapshot(self):
        slot = self._active_slot()
        stack = self._notes_undo.setdefault(slot, [])
        stack.append([dict(s) for s in self._notes.get(slot, [])])
        del stack[:-64]

    def set_annotations(self, strokes, snapshot=True):
        if snapshot:
            self.annotation_snapshot()
        self._notes[self._active_slot()] = list(strokes)
        self.canvas.update()

    def add_annotation(self, points, color=None, width=None):
        """Adds a stroke to the active slot's annotations (points in image pixels, top-left origin)."""
        pts = [(float(x), float(y)) for x, y in points]
        if not pts:
            return
        self.set_annotations(self.annotations() + [{"pts": pts, "color": str(color or self.note_color),
                                                    "width": int(width or self.note_width)}])

    def clear_annotations(self):
        if self.annotations():
            self.set_annotations([])

    def undo_annotation(self):
        stack = self._notes_undo.get(self._active_slot())
        if not stack:
            return False
        self._notes[self._active_slot()] = stack.pop()
        self.canvas.update()
        return True

    def set_annotation_style(self, color=None, width=None):
        """Colour ("#rrggbb") and thickness (px) of new annotation strokes."""
        st = QtCore.QSettings("QtShell", "QtShell")
        if color is not None:
            self.note_color = QtGui.QColor(color).name()
            st.setValue("render_view/annotate_color", self.note_color)
        if width is not None:
            self.note_width = max(1, min(10, int(width)))
            st.setValue("render_view/annotate_thickness", self.note_width)
            if self.note_width_spin.value() != self.note_width:
                self.note_width_spin.blockSignals(True)
                self.note_width_spin.setValue(self.note_width)
                self.note_width_spin.blockSignals(False)
        self._sync_tools()

    def _pick_note_color(self):
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.note_color), self, "Annotation Colour")
        if col.isValid():
            self.set_annotation_style(color=col.name())

    def _update_tips(self):
        try:
            for tid, name, icon, tip in TOOLS:
                b = self.tool_buttons[tid]
                aid = f"render.tool_{tid.lower()}"
                lines = [tip]
                if tid == "ANNOTATE":
                    vinfo = dict((x[0], x) for x in ANNOTATE_VARIANTS)[self.annotate_variant]
                    lines = [f"{vinfo[1]} – {vinfo[3]}",
                             "Hold or right click: " + ", ".join(x[1] for x in ANNOTATE_VARIANTS),
                             "Undo the last change: {window.undo}"]
                    pytips.tag(b, _api(f"set_tool('ANNOTATE', '{self.annotate_variant}')"))
                elif tid == "BLUE_PENCIL":
                    from . import bluepencil
                    lines = [tip, "Hold or right click: " + ", ".join(x[1] for x in bluepencil.TOOLS),
                             "Right click on the picture: the Blue Pencil menu (frames, ghosting, panel)"]
                    pytips.tag(b, _api(f"set_tool('BLUE_PENCIL', '{bluepencil.current_tool()}')"))
                else:
                    pytips.tag(b, _api("set_tool('SAMPLE')"))
                lines.append(f"Key: {{{aid}}}")
                lines.append("{render.toolbar} shows / hides the toolbar")
                b.setToolTip(keymap.render("\n".join(lines)))
            self.gizmo_btn.setToolTip("Show Gizmos – the navigation gizmo (zoom / pan) at the top right")
            self.overlay_btn.setToolTip("Show Overlays – annotations and the render info on the image")
            self.fit_btn.setToolTip(keymap.render("Frame All – the whole image in the view ({render.fit})"))
            self.sidebar_btn.setToolTip(keymap.render("Sidebar: Image and Metadata ({render.sidebar})"))
            self.slot_combo.setToolTip(keymap.render(
                "Render slot – the next render goes into the active slot.\n"
                "Next / previous slot: {render.next_slot} / {render.prev_slot}"))
            self.pass_combo.setToolTip(
                "Render pass of the view layer – the passes enabled in View Layer Properties → Passes.\n"
                "Data passes (Depth, Mist) are shown normalised, Normal as colours.")
        except RuntimeError:
            pass

    # ------------------------------------------------------------ menus
    def _act(self, menu, label, fn, aid=None, py=None, icon=None):
        text = f"{label}\t{keymap.text(aid)}" if aid else label
        a = menu.addAction(icons.icon(icon), text) if icon else menu.addAction(text)
        a.triggered.connect(fn)
        if py:
            pytips.tag(a, py)
        return a

    def _fill_view_menu(self):
        m = self.view_menu
        m.clear()
        a = self._act(m, "Sidebar", lambda: self.set_sidebar(not self.sidebar.isVisible()), "render.sidebar",
                      _api("set_sidebar(True)"))
        a.setCheckable(True)
        a.setChecked(self.sidebar.isVisible())
        a = self._act(m, "Toolbar", lambda: self.set_toolbar(not self.toolbar.isVisible()), "render.toolbar",
                      _api("set_toolbar(True)"), "toolbar")
        a.setCheckable(True)
        a.setChecked(self.toolbar.isVisible())
        for label, on, fn, py in (("Gizmos", self.show_gizmos, self.set_gizmos, "set_gizmos(True)"),
                                  ("Overlays", self.show_overlays, self.set_overlays, "set_overlays(True)")):
            a = self._act(m, label, lambda _c=False, f=fn, o=on: f(not o), None, _api(py))
            a.setCheckable(True)
            a.setChecked(on)
        m.addSeparator()
        tools = m.addMenu("Tools")
        for tid, name, icon, _tip in TOOLS[:1]:
            a = self._act(tools, name, lambda _c=False, t=tid: self.set_tool(t), f"render.tool_{tid.lower()}",
                          _api(f"set_tool('{tid}')"), icon)
            a.setCheckable(True)
            a.setChecked(self.tool == tid)
        for vid, name, icon, _tip in ANNOTATE_VARIANTS:
            a = self._act(tools, name, lambda _c=False, v=vid: self.set_tool("ANNOTATE", v), None,
                          _api(f"set_tool('ANNOTATE', '{vid}')"), icon)
            a.setCheckable(True)
            a.setChecked(self.tool == "ANNOTATE" and self.annotate_variant == vid)
        self._act(m, "Clear Annotations", self.clear_annotations, None, _api("clear_annotations()"))
        from . import burnin
        a = self._act(m, "Burn In Blue Pencil / Annotations", lambda: burnin.set_enabled(not burnin.enabled()), None,
                      "qt_shell.burnin.set_enabled(True)", "tool_blue_pencil")
        a.setCheckable(True)
        a.setChecked(burnin.enabled())
        m.addSeparator()
        self._act(m, "Zoom In", lambda: self.canvas.zoom_step(1.25), "render.zoom_in", _api("zoom(2.0)"))
        self._act(m, "Zoom Out", lambda: self.canvas.zoom_step(0.8), "render.zoom_out", _api("zoom(0.5)"))
        sub = m.addMenu("Fractional Zoom")
        for ratio, label in ZOOM_RATIOS:
            self._act(sub, f"Zoom {label}", lambda _c=False, r=ratio: self.zoom(r),
                      "render.zoom_1_1" if ratio == 1 else None, _api(f"zoom({ratio})"))
        m.addSeparator()
        self._act(m, "Frame All", lambda: self.canvas.fit(), "render.fit", _api("fit()"))
        m.addSeparator()
        self._act(m, "Next Slot", lambda: self.cycle_slot(1), "render.next_slot", _api("cycle_slot(1)"))
        self._act(m, "Previous Slot", lambda: self.cycle_slot(-1), "render.prev_slot", _api("cycle_slot(-1)"))
        m.addSeparator()
        self._act(m, "Close Render View", self.close, "render.close")

    def _fill_image_menu(self):
        m = self.image_menu
        m.clear()
        self._act(m, "Render Image", lambda: self.mw.render_image(False), "window.render",
                  "bpy.ops.render.render()", "render_on")
        a = self._act(m, "Cancel Render", self.mw.cancel_render, "window.render_cancel", None, "render_cancel")
        a.setEnabled(self.cancel_btn.isEnabled() and self.cancel_btn.isVisible())
        m.addSeparator()
        self._act(m, "Save", self.save, "render.save", _api("save()"))
        self._act(m, "Save As…", self.save_as, "render.save_as", _api('save_as("C:/renders/frame.png")'))
        self._act(m, "Save a Copy…", lambda: self.save_as(copy=True), None,
                  'bpy.data.images["Render Result"].save_render(filepath="C:/renders/copy.png")')
        m.addSeparator()
        self._act(m, "Copy to Clipboard", self.copy_to_clipboard, "render.copy", _api("copy_to_clipboard()"))
        self._act(m, "Edit Externally", self.edit_externally, None, _api("edit_externally()"))

    def context_menu(self, gpos):
        m = QtWidgets.QMenu(self)
        m.setToolTipsVisible(True)
        self._act(m, "Frame All", lambda: self.canvas.fit(), "render.fit", _api("fit()"))
        self._act(m, "Zoom 1:1", lambda: self.zoom(1), "render.zoom_1_1", _api("zoom(1)"))
        m.addSeparator()
        self._act(m, "Save As…", self.save_as, "render.save_as", _api('save_as("C:/renders/frame.png")'))
        self._act(m, "Copy to Clipboard", self.copy_to_clipboard, "render.copy", _api("copy_to_clipboard()"))
        m.exec(gpos)
        m.deleteLater()

    # ------------------------------------------------------------ sidebar
    def _build_sidebar(self):
        w = QtWidgets.QFrame(self)
        w.setObjectName("qtshell_render_sidebar")
        w.setStyleSheet("QFrame#qtshell_render_sidebar { background: #2b2b2b; border-left: 1px solid #1d1d1d; }")
        w.setFixedWidth(theme.px(260))
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(theme.px(8), theme.px(6), theme.px(8), theme.px(6))
        v.setSpacing(theme.px(4))
        self._side = {}
        for title, rows in (("Image", ("Name", "Slot", "Resolution", "View Layer", "Pass", "Channels")),
                            ("Metadata", ("Frame", "Render Time", "Date", "Scene", "Camera", "Lens",
                                          "Engine", "Samples", "File"))):
            t = QtWidgets.QLabel(title, w)
            t.setStyleSheet("font-weight: bold; padding-top: 4px;")
            v.addWidget(t)
            form = QtWidgets.QFormLayout()
            form.setHorizontalSpacing(theme.px(8))
            form.setVerticalSpacing(theme.px(2))
            for r in rows:
                val = QtWidgets.QLabel("—", w)
                val.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                val.setWordWrap(True)
                lab = QtWidgets.QLabel(r, w)
                lab.setProperty("dim", True)
                form.addRow(lab, val)
                self._side[r] = val
            v.addLayout(form)
        v.addStretch(1)
        return w

    def set_sidebar(self, on):
        on = bool(on)
        self.sidebar.setVisible(on)
        if self.sidebar_btn.isChecked() != on:
            self.sidebar_btn.blockSignals(True)
            self.sidebar_btn.setChecked(on)
            self.sidebar_btn.blockSignals(False)
        QtCore.QSettings("QtShell", "QtShell").setValue("render_view/sidebar", "true" if on else "false")

    def _update_sidebar(self):
        i = self._info
        img = self.canvas.image
        vals = {
            "Name": "Render Result",
            "Slot": self.slot_combo.currentText() or "—",
            "Resolution": f"{img.width()} × {img.height()} px" if img is not None else "—",
            "View Layer": self.layer or i.get("view_layer", "—"),
            "Pass": self.pas,
            "Channels": dict(CHANNELS).get(self.channel, self.channel),
            "Frame": str(i.get("frame", "—")),
            "Render Time": i.get("time", "—"),
            "Date": i.get("date", "—"),
            "Scene": i.get("scene", "—"),
            "Camera": i.get("camera", "—"),
            "Lens": i.get("lens", "—"),
            "Engine": i.get("engine", "—"),
            "Samples": str(i.get("samples", "—")),
            "File": i.get("file", "—"),
        }
        for k, v in vals.items():
            lab = self._side.get(k)
            if lab is not None:
                lab.setText(str(v))

    # ------------------------------------------------------------ slots / layers / passes / channels
    def _fill_slots(self):
        img = _render_result()
        self.slot_combo.blockSignals(True)
        self.slot_combo.clear()
        names = [s.name for s in img.render_slots] if img is not None else [f"Slot {i + 1}" for i in range(8)]
        for n in names:
            self.slot_combo.addItem(n)
        if img is not None:
            self.slot_combo.setCurrentIndex(max(0, img.render_slots.active_index))
        self.slot_combo.blockSignals(False)

    def set_slot(self, index):
        img = _render_result()
        if img is None:
            return
        n = len(img.render_slots)
        if not n:
            return
        img.render_slots.active_index = index % n
        self._fill_slots()
        self.load_result(keep_view=True)
        self.mw.statusBar().showMessage(f"Render slot: {self.slot_combo.currentText()}", 3000)

    def cycle_slot(self, step):
        img = _render_result()
        if img is not None and len(img.render_slots):
            self.set_slot(img.render_slots.active_index + step)

    def _fill_layers(self):
        self.layer_combo.blockSignals(True)
        self.pass_combo.blockSignals(True)
        self.layer_combo.clear()
        self.pass_combo.clear()
        if self._exr_ok:
            for name in self._exr.layers:
                self.layer_combo.addItem(name or "(layer)", name)
            if self.layer not in self._exr.layers:
                self.layer = next(iter(self._exr.layers), None)
            self.layer_combo.setCurrentIndex(max(0, self.layer_combo.findData(self.layer)))
            for pas in self._exr.layers.get(self.layer, {}):
                self.pass_combo.addItem(pas, pas)
            if self.pass_combo.findData(self.pas) < 0:
                self.pas = "Combined" if self.pass_combo.findData("Combined") >= 0 else self.pass_combo.itemData(0)
            self.pass_combo.setCurrentIndex(max(0, self.pass_combo.findData(self.pas)))
        else:
            vl = bpy.context.view_layer.name
            self.layer_combo.addItem(vl, None)
            self.pass_combo.addItem("Combined", "Combined")
            self.layer = None
            self.pas = "Combined"
        tip_l = "View Layer" if self._exr_ok else "View Layer (only the shown one – OpenImageIO is not available)"
        self.layer_combo.setToolTip(tip_l)
        self.layer_combo.blockSignals(False)
        self.pass_combo.blockSignals(False)

    def _pick_layer(self, layer):
        self.layer = layer
        self._fill_layers()
        self._show()

    def _pick_pass(self, pas):
        self.pas = pas
        i = self.pass_combo.findData(pas)
        if i >= 0 and i != self.pass_combo.currentIndex():
            self.pass_combo.blockSignals(True)
            self.pass_combo.setCurrentIndex(i)
            self.pass_combo.blockSignals(False)
        self._show()

    def passes(self):
        """{view layer: [passes]} of the shown result (the passes enabled in View Layer Properties)."""
        if self._exr_ok:
            return {k: list(v) for k, v in self._exr.layers.items()}
        return {bpy.context.view_layer.name: ["Combined"]}

    def set_layer(self, layer):
        if self._exr_ok and layer not in self._exr.layers:
            raise KeyError(f"no view layer {layer!r} – one of {', '.join(self._exr.layers)}")
        self._pick_layer(layer)

    def set_pass(self, pas):
        """Show a render pass of the current view layer, e.g. set_pass("Depth")."""
        avail = self.passes().get(self.layer, ["Combined"]) if self._exr_ok else ["Combined"]
        if pas not in avail:
            raise KeyError(f"no pass {pas!r} – one of {', '.join(avail)}")
        self._pick_pass(pas)

    def set_channel(self, channel):
        if channel not in dict(CHANNELS):
            raise KeyError(f"unknown channel {channel!r} – one of {', '.join(dict(CHANNELS))}")
        self.channel = channel
        self.channel_combo.setCurrentIndex(max(0, self.channel_combo.findData(channel)))
        self._show()

    # ------------------------------------------------------------ loading
    def _collect_info(self):
        sc = bpy.context.scene
        r = sc.render
        cam = sc.camera
        info = {"frame": sc.frame_current, "scene": sc.name, "view_layer": bpy.context.view_layer.name,
                "camera": cam.name if cam else "—", "engine": r.engine.replace("BLENDER_", "").title(),
                "date": time.strftime("%Y/%m/%d %H:%M:%S"), "file": os.path.basename(bpy.data.filepath) or "(unsaved)"}
        try:
            info["lens"] = f"{cam.data.lens:.0f} mm" if cam is not None and cam.type == "CAMERA" else "—"
        except Exception:
            info["lens"] = "—"
        try:
            if r.engine == "CYCLES":
                info["samples"] = sc.cycles.samples
            elif hasattr(sc, "eevee"):
                info["samples"] = getattr(sc.eevee, "taa_render_samples", "—")
        except Exception:
            pass
        return info

    def load_result(self, keep_view=False):
        """Reads the Render Result (active slot) and shows it. False when there is nothing to show."""
        self._external = None
        img = _render_result()
        self._fill_slots()
        if img is None:
            self._combined = None
            self.canvas.set_image(None)
            self.canvas.overlay = ""
            self._update_footer()
            return False
        path = _tmp("qtshell_render.png")
        try:
            if os.path.exists(path):
                os.remove(path)
            img.save_render(filepath=path)
            q = QtGui.QImage(path)
        except Exception as ex:
            q = QtGui.QImage()
            bridge.log(f"Render View: cannot read the Render Result ({ex})", "WARNING")
        if q.isNull():
            self._combined = None
            self.canvas.set_image(None)
            self.canvas.overlay = f"{self.slot_combo.currentText()} is empty"
            self.canvas.update()
            self._update_footer()
            return False
        self._combined = q.convertToFormat(QtGui.QImage.Format_RGBA8888)
        if self._render_start is None:
            # metadata of the render in this slot (a slot rendered before Qt Shell knew: only what is known now)
            self._info = self._slot_info.get(self._active_slot()) or {
                k: v for k, v in self._collect_info().items() if k in ("scene", "view_layer", "camera", "file")}
        self._exr_ok = None
        self._read_layers(img)
        self._fill_layers()
        self._show(keep_view)
        return True

    def _read_layers(self, img):
        """Multilayer OpenEXR copy of the result → view layers / passes (float values for sampling)."""
        sc = bpy.context.scene
        s = sc.render.image_settings
        path = _tmp("qtshell_render_layers.exr")
        keep = (getattr(s, "media_type", None), s.file_format, s.color_depth)
        try:
            import OpenImageIO  # noqa: F401 – bundled with Blender 3.5+
        except Exception:
            self._exr_ok = False
            return
        try:
            if hasattr(s, "media_type"):
                s.media_type = "MULTI_LAYER_IMAGE"
            else:
                s.file_format = "OPEN_EXR_MULTILAYER"
            s.color_depth = "32"
            img.save_render(filepath=path, scene=sc)
            self._exr.load(path)
            self._exr_ok = True
        except Exception as ex:
            bridge.log(f"Render View: layers not available ({ex})", "WARNING")
            self._exr_ok = False
        finally:
            try:
                if keep[0] is not None:
                    s.media_type = keep[0]
                s.file_format, s.color_depth = keep[1], keep[2]
            except Exception:
                pass

    def _base_image(self):
        if self._external is not None:
            return self._external
        if self.pas == "Combined" or not self._exr_ok:
            base = self._combined
            burn = self._slot_burn.get(self._active_slot())
            if base is not None and burn is not None:
                from . import burnin
                if burnin.enabled():
                    try:
                        return burnin.burn(base, bpy.context.scene, burn["frame"], burn["camera"], burn["mats"])
                    except Exception as ex:
                        bridge.log(f"Render View burn-in: {ex}", "WARNING")
            return base
        return self._exr.image(self.layer, self.pas) or self._combined

    # --- Blue Pencil over the render
    def bp_camera(self):
        """Camera the picture was rendered with (its Blue Pencil layers are drawn / drawn into)."""
        burn = self._slot_burn.get(self._active_slot())
        if burn and burn.get("camera"):
            return burn["camera"]
        cam = bpy.context.scene.camera
        return cam.name if cam is not None else ""

    def bp_frame(self):
        burn = self._slot_burn.get(self._active_slot())
        return int(burn["frame"]) if burn else int(bpy.context.scene.frame_current)

    def bp_layers_shown(self):
        """The Blue Pencil layers are painted over the picture (not when they are burnt into it already)."""
        return (self.show_overlays and self._external is None and self.canvas.image is not None
                and not self.burnt_in())

    def _bp_changed(self):
        try:
            if self.burnt_in() and self._combined is not None:
                self._show(True)               # the burnt-in picture gets the new strokes
            self.canvas.update()
        except RuntimeError:
            pass

    def _bp_has_strokes(self):
        from . import bluepencil
        if not bluepencil.settings().show:
            return False
        cam, f = self.bp_camera(), self.bp_frame()
        return any(lay.get("visible", True) and lay.get("camera", "") == cam and bluepencil.strokes_at(lay, f)
                   for lay in bluepencil.layers())

    @staticmethod
    def note_width_px(width, img_h):
        """Stroke width in image pixels for a saved picture (screen thickness scaled to the render size)."""
        return max(1.0, float(width) * max(1.0, img_h / 720.0))

    def picture(self):
        """The picture as shown – the render (with burnt-in Blue Pencil / scene annotations when Burn In is
        on) plus the Render View's own annotations of the active slot – as a QImage; None when empty."""
        base = self._base_image()
        if base is None:
            return None
        notes = [st for st in self.annotations() if st.get("pts")]
        bp = self._external is None and not self.burnt_in() and self.show_overlays and self._bp_has_strokes()
        if (not notes and not bp) or not self.show_overlays:
            return base
        q = base.convertToFormat(QtGui.QImage.Format_RGBA8888)
        p = QtGui.QPainter(q)
        try:
            if bp:                               # Blue Pencil of the render's camera, like on the screen
                from . import bluepencil
                bluepencil.paint_layers(p, self.bp_camera(), QtCore.QRectF(0, 0, q.width(), q.height()),
                                        self.bp_frame(), ghosts=False)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            p.setBrush(QtCore.Qt.NoBrush)
            for st in notes:
                pen = QtGui.QPen(QtGui.QColor(st["color"]), self.note_width_px(st.get("width", 3), q.height()))
                pen.setCapStyle(QtCore.Qt.RoundCap)
                pen.setJoinStyle(QtCore.Qt.RoundJoin)
                p.setPen(pen)
                pts = [QtCore.QPointF(x, y) for x, y in st["pts"]]
                if len(pts) == 1:
                    p.drawPoint(pts[0])
                else:
                    p.drawPolyline(QtGui.QPolygonF(pts))
        finally:
            p.end()
        return q

    def has_drawings(self):
        """True when Save writes the picture with drawings (burnt-in or Render View annotations)."""
        return self.burnt_in() or (self.show_overlays and (any(st.get("pts") for st in self.annotations()) or
                                                           (self._external is None and self._bp_has_strokes())))

    def burnt_in(self):
        """True when the picture shown has the drawings burnt in (Save then saves that picture)."""
        from . import burnin
        return self._external is None and burnin.enabled() and (self.pas == "Combined" or not self._exr_ok) and \
            self._slot_burn.get(self._active_slot()) is not None

    def _burn_changed(self):
        from . import burnin
        if self.burn_btn.isChecked() != burnin.enabled():
            self.burn_btn.blockSignals(True)
            self.burn_btn.setChecked(burnin.enabled())
            self.burn_btn.blockSignals(False)
        if self._combined is not None:
            self._show(True)

    def show_external(self, img, info=None):
        """Shows a picture that isn't the Render Result (Viewport Render); Save saves it."""
        self._external = img.convertToFormat(QtGui.QImage.Format_RGBA8888)
        self._exr_ok = False
        if info:
            self._info = info
        self._show(False)
        QtCore.QTimer.singleShot(0, self.canvas.fit)     # after the window got its size

    def _show(self, keep_view=True):
        base = self._base_image()
        if base is None:
            self.canvas.set_image(None)
            self._update_footer()
            return
        img = self._apply_channel(base)
        self.canvas.set_image(img, keep_view)
        i = self._info
        parts = [f"Frame:{i.get('frame', '')}"]
        if i.get("time"):
            parts.append(f"Time:{i['time']}")
        parts += [f"{i.get('scene', '')} | {self.layer or i.get('view_layer', '')}", f"{self.pas}"]
        if i.get("camera"):
            parts.append(f"Camera:{i['camera']}")
        self.canvas.overlay = " | ".join(p for p in parts if p)
        self._update_sidebar()
        self._update_footer()

    def _apply_channel(self, base):
        ch = self.channel
        if ch == "COLOR_ALPHA":
            return base
        arr = np.frombuffer(base.constBits(), dtype=np.uint8).reshape(base.height(), base.bytesPerLine())
        arr = arr[:, :base.width() * 4].reshape(base.height(), base.width(), 4)
        out = np.empty_like(arr)
        if ch == "COLOR":
            out[:, :, :3] = arr[:, :, :3]
        else:
            k = {"ALPHA": 3, "RED": 0, "GREEN": 1, "BLUE": 2}[ch]
            out[:, :, 0] = out[:, :, 1] = out[:, :, 2] = arr[:, :, k]
        out[:, :, 3] = 255
        out = np.ascontiguousarray(out)
        q = QtGui.QImage(out.data, base.width(), base.height(), 4 * base.width(), QtGui.QImage.Format_RGBA8888)
        return q.copy()

    # ------------------------------------------------------------ footer / sampling
    def _zoom_changed(self, z):
        self.zoom_label.setText(f"{z * 100:.0f}%")
        self._update_footer()

    def _update_footer(self, sample=None):
        img = self.canvas.image
        if img is None:
            self.footer.setText(keymap.render("Render Result – nothing to show · {window.render}: Render Image"))
            return
        if sample:
            self.footer.setText(sample)
            return
        self.footer.setText(keymap.render(
            f"{img.width()} × {img.height()} px · {self.slot_combo.currentText()} · zoom {self.canvas.zoom * 100:.0f}%"
            " · left mouse: sample · middle mouse: pan · wheel: zoom · {render.fit}: frame all"))

    def _sampled(self, xy):
        if xy is None:
            self._update_footer()
            return
        x, y = xy
        base = self._combined if (self.pas == "Combined" or not self._exr_ok) else None
        vals = None
        if self._exr_ok:
            vals = self._exr.sample(self.layer, self.pas, x, y)
        if vals is None and base is not None:
            c = base.pixelColor(x, y)
            vals = [c.redF(), c.greenF(), c.blueF(), c.alphaF()]
        names = "RGBA" if vals and len(vals) >= 3 else ("V",)
        txt = "  ".join(f"{n}:{v:.4f}" for n, v in zip(names, vals or []))
        disp = self._combined.pixelColor(x, y) if self._combined is not None else None
        extra = f"   |  CM  R:{disp.red()} G:{disp.green()} B:{disp.blue()}" if disp is not None else ""
        # Blender: X / Y from the bottom-left corner
        h = self.canvas.image.height()
        self._update_footer(f"X:{x}  Y:{h - 1 - y}  |  {txt}{extra}")

    # ------------------------------------------------------------ actions
    def zoom(self, ratio):
        """Zoom ratio like Blender's View → Fractional Zoom (1 = 1:1, 2 = 2:1, 0.5 = 1:2 …)."""
        self.canvas.set_zoom(float(ratio))     # zoom 1 = one image pixel per screen pixel

    def fit(self):
        self.canvas.fit()

    def _format_for(self, path, chosen=None):
        if chosen is not None:
            return chosen
        ext = os.path.splitext(path)[1].lower()
        for f in SAVE_FORMATS:
            if f[3] == ext or (ext in (".jpeg",) and f[2] == "JPEG") or (ext == ".tiff" and f[2] == "TIFF"):
                return f
        return SAVE_FORMATS[0]

    def save_as(self, path=None, copy=False):
        """Saves the Render Result (active slot) – the format follows the file type. A picture with burnt-in
        drawings or a Viewport Render is saved as shown (PNG, JPEG, TIFF, WebP, BMP)."""
        img = _render_result()
        if img is None and self._external is None:
            return False
        fmt = None
        if not path:
            start = self._save_path or os.path.join(
                os.path.dirname(bpy.data.filepath) or os.path.expanduser("~"), "render.png")
            filters = ";;".join(f[0] for f in SAVE_FORMATS)
            path, flt = QtWidgets.QFileDialog.getSaveFileName(self, "Save a Copy" if copy else "Save As", start,
                                                              filters)
            if not path:
                return False
            fmt = next((f for f in SAVE_FORMATS if f[0] == flt), None)
            if fmt is not None and not os.path.splitext(path)[1]:
                path += fmt[3]
        fmt = self._format_for(path, fmt)
        if (self._external is not None or self.has_drawings()) and fmt[2] in ("PNG", "JPEG", "TIFF", "WEBP", "BMP"):
            q = self.picture()
            if q is not None:
                if fmt[2] in ("JPEG", "BMP"):
                    q = q.convertToFormat(QtGui.QImage.Format_RGB32)
                if os.path.dirname(path):
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                if not q.save(path):
                    QtWidgets.QMessageBox.warning(self, "Save Render", f"Cannot save the image:\n{path}")
                    return False
                if not copy:
                    self._save_path = path
                self.mw.statusBar().showMessage(f"Saved {path} (with the drawings)"
                                                if self.has_drawings() else f"Saved {path}", 5000)
                return True
        if img is None:
            return False
        if self.has_drawings() or self._external is not None:
            self.mw.statusBar().showMessage("OpenEXR keeps the clean render (drawings only in PNG / JPEG / TIFF / "
                                            "WebP / BMP)", 6000)
        sc = bpy.context.scene
        s = sc.render.image_settings
        keep = (getattr(s, "media_type", None), s.file_format, s.color_depth)
        try:
            if hasattr(s, "media_type"):
                s.media_type = fmt[1]
            if fmt[1] != "MULTI_LAYER_IMAGE":
                s.file_format = fmt[2]
            img.save_render(filepath=path, scene=sc)
        except Exception as ex:
            QtWidgets.QMessageBox.warning(self, "Save Render", f"Cannot save the image:\n{ex}")
            return False
        finally:
            try:
                if keep[0] is not None:
                    s.media_type = keep[0]
                s.file_format, s.color_depth = keep[1], keep[2]
            except Exception:
                pass
        if not copy:
            self._save_path = path
        self.mw.statusBar().showMessage(f"Saved {path}", 5000)
        return True

    def save(self):
        """Save (to the last Save As path) – the first time it asks for a file like Blender."""
        return self.save_as(self._save_path or None)

    def copy_to_clipboard(self):
        q = self.picture()
        if q is not None:
            QtWidgets.QApplication.clipboard().setImage(q)
            self.mw.statusBar().showMessage("Render copied to the clipboard", 3000)

    def edit_externally(self):
        path = _tmp("qtshell_render_external.png")
        if self.has_drawings() or self._external is not None:      # the picture as shown, with the drawings
            q = self.picture()
            if q is not None and q.save(path):
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
            return
        img = _render_result()
        if img is None:
            return
        try:
            img.save_render(filepath=path)
        except Exception as ex:
            QtWidgets.QMessageBox.warning(self, "Edit Externally", str(ex))
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    # ------------------------------------------------------------ rendering progress
    def _active_slot(self):
        img = _render_result()
        try:
            return img.render_slots.active_index if img is not None else 0
        except Exception:
            return 0

    def render_started(self):
        self._render_start = time.time()
        self._info = self._collect_info()
        self._slot_info[self._active_slot()] = self._info
        self._fill_slots()
        self.canvas.busy = "Rendering…"
        self._timer.start()
        self.canvas.update()

    def _tick(self):
        if self._render_start is None:
            self._timer.stop()
            return
        t = time.time() - self._render_start
        slot = self.slot_combo.currentText()
        self.canvas.busy = f"Rendering… {int(t // 60):02d}:{t % 60:05.2f}  |  {slot}  |  {self._info.get('engine', '')}"
        self.canvas.update()

    def show_live(self, q):
        """The picture of a render in progress (a QImage; main window, about once a second)."""
        if q is None or q.isNull() or self._render_start is None:
            return False
        q = q.convertToFormat(QtGui.QImage.Format_RGBA8888)
        self.canvas.set_image(self._apply_channel(q), True)
        return True

    def set_rendering(self, on, cancellable=True):
        """Main window: a render started / ended – the Cancel button is shown while rendering."""
        self.cancel_btn.setVisible(bool(on))
        self.cancel_btn.setEnabled(bool(on and cancellable))

    def render_finished(self):
        if self._render_start is not None:
            t = time.time() - self._render_start
            self._info["time"] = f"{int(t // 60):02d}:{t % 60:05.2f}"
        self._render_start = None
        self._timer.stop()
        self.canvas.busy = ""
        if not self._info:
            self._info = self._collect_info()
        self._slot_info[self._active_slot()] = self._info
        self._external = None
        self._remember_burn()
        self.load_result(keep_view=self.isVisible())

    def _remember_burn(self):
        """Frame, camera and its matrices of the render just finished – for the burn-in of the drawings."""
        from . import burnin
        sc = bpy.context.scene
        cam = sc.camera
        try:
            w, h = burnin.render_size(sc)
            mats = burnin.camera_mats(sc, cam, w, h) if cam is not None else None
        except Exception:
            mats = None
        self._slot_burn[self._active_slot()] = {"frame": sc.frame_current, "camera": cam.name if cam else "",
                                                "mats": mats}

    def present(self):
        self.present_window()          # a window in front of Qt Shell, or its dock (Dock button)
        self.canvas.setFocus()

    def close(self):
        """Esc / F11: hides the window (or its dock)."""
        self.hide_window()
        return True

    # ------------------------------------------------------------ keys
    def event(self, ev):
        # Blue Pencil keys (Ctrl+C / Ctrl+V, Enter, Delete …) win over window shortcuts while it draws here
        if ev.type() == QtCore.QEvent.ShortcutOverride and getattr(self, "bp", None) is not None \
                and self.bp.enabled and self.bp.owns_key(ev):
            ev.accept()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        names = keymap.event_names(ev)

        def H(aid):
            return keymap.hit(aid, ev, names)

        if self.bp.enabled and self.bp.key(ev, H):      # Blue Pencil keys first (copy / paste, Enter, Esc …)
            self.canvas.update()
        elif self.canvas._poly and ev.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Escape):
            self.canvas.finish_polygon()
        elif H("window.render_cancel") and self.mw.is_rendering():
            self.mw.cancel_render()
        elif H("render.close") or H("window.show_render"):
            self.close()
        elif H("render.toolbar"):
            self.set_toolbar(not self.toolbar.isVisible())
        elif H("render.tool_sample"):
            self.set_tool("SAMPLE")
        elif H("render.tool_blue_pencil"):
            if self.tool == "BLUE_PENCIL":           # again: the next drawing tool
                from . import bluepencil
                ids = bluepencil.TOOL_IDS
                self.set_tool("BLUE_PENCIL", ids[(ids.index(bluepencil.current_tool()) + 1) % len(ids)])
            else:
                self.set_tool("BLUE_PENCIL")
        elif H("render.tool_annotate"):
            if self.tool == "ANNOTATE":          # again: next variant (like the 3D view's tools)
                ids = [x[0] for x in ANNOTATE_VARIANTS]
                self.set_tool("ANNOTATE", ids[(ids.index(self.annotate_variant) + 1) % len(ids)])
            else:
                self.set_tool("ANNOTATE")
        elif H("window.undo"):
            if not self.undo_annotation():
                self.mw.statusBar().showMessage("Render View: nothing to undo", 2000)
        elif H("render.fit"):
            self.canvas.fit()
        elif H("render.zoom_in"):
            self.canvas.zoom_step(1.25)
        elif H("render.zoom_out"):
            self.canvas.zoom_step(0.8)
        elif H("render.zoom_1_1"):
            self.zoom(1)
        elif H("render.next_slot"):
            self.cycle_slot(1)
        elif H("render.prev_slot"):
            self.cycle_slot(-1)
        elif H("render.sidebar"):
            self.set_sidebar(not self.sidebar.isVisible())
        elif H("render.save_as"):
            self.save_as()
        elif H("render.save"):
            self.save()
        elif H("render.copy"):
            self.copy_to_clipboard()
        elif H("window.render"):
            self.mw.render_image(False)
        else:
            super().keyPressEvent(ev)
            return
        ev.accept()

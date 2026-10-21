"""Render View – Blender's render window (Image Editor showing the Render Result) in Qt.

Header like Blender 5.2: View and Image menus, the Render Result image, render slots (Slot 1–8),
View Layer and Pass, Display Channels (Color & Alpha, Color, Alpha, Red, Green, Blue), zoom and the
sidebar toggle. The canvas: checkerboard behind transparent renders, mouse wheel zooms around the
mouse, middle mouse pans, left mouse samples the pixel under it (footer: X / Y and R G B A).
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

CHANNELS = [("COLOR_ALPHA", "Color & Alpha"), ("COLOR", "Color"), ("ALPHA", "Alpha"),
            ("RED", "Red"), ("GREEN", "Green"), ("BLUE", "Blue")]
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
        else:
            p.setPen(QtGui.QColor(150, 150, 150))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter,
                       keymap.render("Nothing rendered yet – Render Image ({window.render})"))
        text = self.busy or self.overlay
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
        steps = ev.angleDelta().y() / 120.0
        if steps:
            self.zoom_step(1.25 ** steps, ev.position())

    def mousePressEvent(self, ev):
        self.setFocus()
        if ev.button() == QtCore.Qt.MiddleButton or (
                ev.button() == QtCore.Qt.LeftButton and ev.modifiers() & QtCore.Qt.AltModifier):
            self._pan = ev.position()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
        elif ev.button() == QtCore.Qt.LeftButton:
            self._sampling = True             # Blender: left mouse samples the pixel
            self.sampled.emit(self.pixel_at(ev.position()))
        elif ev.button() == QtCore.Qt.RightButton:
            self.view.context_menu(ev.globalPosition().toPoint())

    def mouseMoveEvent(self, ev):
        if self._pan is not None:
            d = ev.position() - self._pan
            self._pan = ev.position()
            self.offset += d
            self.update()
        elif self._sampling:
            self.sampled.emit(self.pixel_at(ev.position()))

    def mouseReleaseEvent(self, ev):
        if self._pan is not None:
            self._pan = None
            self.unsetCursor()
        if ev.button() == QtCore.Qt.LeftButton and self._sampling:
            self._sampling = False
            self.sampled.emit(None)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == QtCore.Qt.MiddleButton:
            self.fit()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.update()


# ---------------------------------------------------------------- window
class RenderView(QtWidgets.QWidget):
    """Blender's render window: shows the Render Result with the header, canvas, sidebar and footer."""

    def __init__(self, main_window):
        super().__init__(main_window, QtCore.Qt.Window)
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
        self._render_start = None
        self._save_path = ""
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
        self.canvas = _Canvas(self)
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
        h.addStretch(1)
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
        return bar

    def _update_tips(self):
        try:
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
        if self.pas == "Combined" or not self._exr_ok:
            return self._combined
        return self._exr.image(self.layer, self.pas) or self._combined

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
        """Saves the Render Result (active slot) – the format follows the file type."""
        img = _render_result()
        if img is None:
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
        if self.canvas.image is not None:
            QtWidgets.QApplication.clipboard().setImage(self.canvas.image)
            self.mw.statusBar().showMessage("Render copied to the clipboard", 3000)

    def edit_externally(self):
        path = _tmp("qtshell_render_external.png")
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
        self.load_result(keep_view=self.isVisible())

    def present(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.canvas.setFocus()

    # ------------------------------------------------------------ keys
    def keyPressEvent(self, ev):
        names = keymap.event_names(ev)

        def H(aid):
            return keymap.hit(aid, ev, names)

        if H("render.close") or H("window.show_render"):
            self.close()
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

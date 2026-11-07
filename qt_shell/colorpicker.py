"""Colour tool – one picker for every colour button of Qt Shell.

Click any colour swatch (Properties colour fields, Blue Pencil colour / ghost colours, annotation colour in the 3D
view and the Render View …) and this window opens next to it:

* hue / saturation disc + value bar (like Blender's), colour square markers follow the mouse,
* RGB or HSV sliders with gradient tracks and number fields (RGB of linear colour properties shown linear, like
  Blender's own fields; the disc and Hex are display colours),
* alpha slider when the property has one, Hex field (#RRGGBB / #RRGGBBAA, also short #RGB),
* eyedropper – pick any pixel on the screen (magnifier, live preview, Esc cancels),
* old / new swatch (click the old half to go back), recent colours, own palette (+ adds, right click removes),
  basic colours,
* every change is applied at once – the button and the scene follow the picker. OK / Enter keeps it,
  Cancel / Esc puts the colour back as it was.

    from . import colorpicker
    colorpicker.pick(button, QtGui.QColor("#ff8800"), on_change=lambda c: ..., title="Colour", alpha=False)
"""
import math

from PySide6 import QtCore, QtGui, QtWidgets

from . import theme

KEY_RECENT = "colorpicker/recent"
KEY_PALETTE = "colorpicker/palette"
KEY_MODE = "colorpicker/mode"
MAX_RECENT = 12
MAX_PALETTE = 24
BASIC = ["#000000", "#555555", "#aaaaaa", "#ffffff", "#e63c3c", "#f08c28", "#f2d23c", "#5ac85a",
         "#3cb4c8", "#3c78e6", "#9b5ae6", "#e65aaa"]
ACCENT = "#6d9ad4"

_current = None                      # the open picker (one at a time)


def _settings():
    return QtCore.QSettings("QtShell", "QtShell")


def _list(key):
    v = _settings().value(key, [])
    if isinstance(v, str):
        v = [v] if v else []
    return [str(c) for c in (v or []) if QtGui.QColor(str(c)).isValid()]


def _save_list(key, cols):
    _settings().setValue(key, list(cols))


def recent_colors():
    return _list(KEY_RECENT)


def add_recent(col):
    name = QtGui.QColor(col).name(QtGui.QColor.HexArgb if QtGui.QColor(col).alpha() < 255 else QtGui.QColor.HexRgb)
    cols = [c for c in recent_colors() if c.lower() != name.lower()]
    _save_list(KEY_RECENT, ([name] + cols)[:MAX_RECENT])


def palette_colors():
    return _list(KEY_PALETTE)


def lin_to_srgb(c):
    c = max(0.0, c)
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _checker(p, rect, size=None):
    size = size or theme.px(5)
    p.save()
    p.setClipRect(rect)
    p.fillRect(rect, QtGui.QColor("#9a9a9a"))
    y = rect.top()
    row = 0
    while y < rect.bottom() + 1:
        x = rect.left() + (size if row % 2 else 0)
        while x < rect.right() + 1:
            p.fillRect(QtCore.QRectF(x, y, size, size), QtGui.QColor("#cfcfcf"))
            x += 2 * size
        y += size
        row += 1
    p.restore()


# ---------------------------------------------------------------- widgets
class HSDisc(QtWidgets.QWidget):
    """Hue (angle) / saturation (distance from the centre) disc at a fixed value."""
    changed = QtCore.Signal(float, float)        # h, s
    released = QtCore.Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.h, self.s, self.v = 0.0, 0.0, 1.0
        self._cache = None
        self.setMinimumSize(theme.px(170), theme.px(170))
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.setCursor(QtCore.Qt.CrossCursor)

    def set_hsv(self, h, s, v):
        if abs(v - self.v) > 1e-4:
            self._cache = None
        self.h, self.s, self.v = h, s, v
        self.update()

    def _geom(self):
        side = min(self.width(), self.height()) - theme.px(8)
        r = side / 2.0
        c = QtCore.QPointF(self.width() / 2.0, self.height() / 2.0)
        return c, r

    def _disc(self, r):
        dpr = self.devicePixelRatioF()
        key = (int(r), round(self.v, 3), dpr)
        if self._cache is not None and self._cache[0] == key:
            return self._cache[1]
        d = int(2 * r * dpr) + 2
        img = QtGui.QImage(d, d, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        cc = QtCore.QPointF(d / 2.0, d / 2.0)
        rr = r * dpr
        path = QtGui.QPainterPath()
        path.addEllipse(cc, rr, rr)
        con = QtGui.QConicalGradient(cc, 0)
        for i in range(13):
            con.setColorAt(i / 12.0, QtGui.QColor.fromHsvF((i / 12.0) % 1.0, 1, 1))
        p.fillPath(path, con)
        rad = QtGui.QRadialGradient(cc, rr)
        rad.setColorAt(0, QtGui.QColor(255, 255, 255, 255))
        rad.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.fillPath(path, rad)
        if self.v < 1.0:
            p.fillPath(path, QtGui.QColor(0, 0, 0, int(round((1 - self.v) * 255))))
        p.end()
        img.setDevicePixelRatio(dpr)
        self._cache = (key, img)
        return img

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        c, r = self._geom()
        img = self._disc(r)
        p.drawImage(QtCore.QPointF(c.x() - r, c.y() - r), img)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 120), 1))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(c, r, r)
        a = self.h * 2 * math.pi
        m = QtCore.QPointF(c.x() + math.cos(a) * self.s * r, c.y() - math.sin(a) * self.s * r)
        rm = theme.px(6)
        p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 3))
        p.drawEllipse(m, rm, rm)
        p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1.5))
        p.drawEllipse(m, rm, rm)

    def _pick(self, pos):
        c, r = self._geom()
        dx, dy = pos.x() - c.x(), c.y() - pos.y()
        h = (math.atan2(dy, dx) / (2 * math.pi)) % 1.0
        s = min(1.0, math.hypot(dx, dy) / max(1.0, r))
        if s < 1e-4:
            h = self.h
        self.h, self.s = h, s
        self.update()
        self.changed.emit(h, s)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._pick(e.position())

    def mouseMoveEvent(self, e):
        if e.buttons() & QtCore.Qt.LeftButton:
            self._pick(e.position())

    def mouseReleaseEvent(self, e):
        self.released.emit()


class GradientSlider(QtWidgets.QWidget):
    """A value 0…1 on a gradient track (horizontal or vertical) with a handle."""
    changed = QtCore.Signal(float)
    released = QtCore.Signal()

    def __init__(self, parent, vertical=False, checker=False):
        super().__init__(parent)
        self.vertical = vertical
        self.checker = checker
        self.value = 0.0
        self.stops = [(0.0, QtGui.QColor("black")), (1.0, QtGui.QColor("white"))]
        if vertical:
            self.setFixedWidth(theme.px(18))
            self.setMinimumHeight(theme.px(120))
        else:
            self.setFixedHeight(theme.px(16))
            self.setMinimumWidth(theme.px(110))
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def set_stops(self, stops):
        self.stops = stops
        self.update()

    def set_value(self, v):
        self.value = max(0.0, min(1.0, v))
        self.update()

    def _track(self):
        m = theme.px(5)
        r = QtCore.QRectF(self.rect()).adjusted(m if not self.vertical else 2, 2 if not self.vertical else m,
                                                -(m if not self.vertical else 2), -(2 if not self.vertical else m))
        return r

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = self._track()
        if self.checker:
            _checker(p, r.toRect())
        if self.vertical:
            g = QtGui.QLinearGradient(r.bottomLeft(), r.topLeft())
        else:
            g = QtGui.QLinearGradient(r.topLeft(), r.topRight())
        for pos, col in self.stops:
            g.setColorAt(pos, col)
        path = QtGui.QPainterPath()
        path.addRoundedRect(r, 3, 3)
        p.fillPath(path, g)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 140), 1))
        p.drawPath(path)
        if self.vertical:
            y = r.bottom() - self.value * r.height()
            h = QtCore.QRectF(r.left() - 2, y - 3, r.width() + 4, 6)
        else:
            x = r.left() + self.value * r.width()
            h = QtCore.QRectF(x - 3, r.top() - 2, 6, r.height() + 4)
        p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 1))
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawRoundedRect(h, 2, 2)

    def _pick(self, pos):
        r = self._track()
        if self.vertical:
            v = (r.bottom() - pos.y()) / max(1.0, r.height())
        else:
            v = (pos.x() - r.left()) / max(1.0, r.width())
        self.set_value(v)
        self.changed.emit(self.value)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._pick(e.position())

    def mouseMoveEvent(self, e):
        if e.buttons() & QtCore.Qt.LeftButton:
            self._pick(e.position())

    def mouseReleaseEvent(self, e):
        self.released.emit()

    def wheelEvent(self, e):
        step = 0.01 if e.modifiers() & QtCore.Qt.ShiftModifier else 0.05
        self.set_value(self.value + (step if e.angleDelta().y() > 0 else -step))
        self.changed.emit(self.value)


class OldNewSwatch(QtWidgets.QWidget):
    """Left: the colour before the picker opened (click = back to it); right: the current colour."""
    revert = QtCore.Signal()

    def __init__(self, parent, old):
        super().__init__(parent)
        self.old = QtGui.QColor(old)
        self.new = QtGui.QColor(old)
        self.setFixedHeight(theme.px(30))
        self.setMinimumWidth(theme.px(90))
        self.setToolTip("Left: the colour before – click it to go back · Right: the new colour")

    def set_new(self, c):
        self.new = QtGui.QColor(c)
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        _checker(p, r.toRect())
        half = r.width() / 2
        p.fillRect(QtCore.QRectF(r.left(), r.top(), half, r.height()), self.old)
        p.fillRect(QtCore.QRectF(r.left() + half, r.top(), r.width() - half, r.height()), self.new)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 160), 1))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(r, 3, 3)

    def mousePressEvent(self, e):
        if e.position().x() < self.width() / 2:
            self.revert.emit()


class SwatchButton(QtWidgets.QToolButton):
    def __init__(self, parent, color, tip=""):
        super().__init__(parent)
        self.color = QtGui.QColor(color)
        s = theme.px(18)
        self.setFixedSize(s, s)
        self.setToolTip(tip or self.color.name().upper())
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        if self.color.alpha() < 255:
            _checker(p, r.toRect(), theme.px(3))
        p.setBrush(self.color)
        hover = self.underMouse()
        p.setPen(QtGui.QPen(QtGui.QColor(ACCENT if hover else "#151515"), 2 if hover else 1))
        p.drawRoundedRect(r, 3, 3)


class ScreenPicker(QtWidgets.QWidget):
    """Eyedropper: a small magnifier window that follows the mouse (the mouse is grabbed, the screen stays live –
    the colour tool keeps showing the colour under the mouse). Click picks the pixel, right click / Esc cancels."""
    hovered = QtCore.Signal(QtGui.QColor)
    picked = QtCore.Signal(QtGui.QColor)
    cancelled = QtCore.Signal()
    N = 11                                    # pixels across the magnifier

    def __init__(self, parent):
        super().__init__(parent, QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
                         | QtCore.Qt.Tool | QtCore.Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.cell = theme.px(9)
        self.img = QtGui.QImage()
        self.color = QtGui.QColor()
        self._done = False
        self._pending = None
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)                       # one screen grab per ~frame while the mouse moves
        self._timer.timeout.connect(self._sample_pending)
        fm = self.fontMetrics()
        self.label_w = fm.horizontalAdvance("#FFFFFF    click: take · Esc: cancel") + theme.px(40)
        side = self.N * self.cell
        self.setFixedSize(max(side, self.label_w) + 4, side + theme.px(28))

    def start(self):
        self.show()
        self._sample(QtGui.QCursor.pos())
        self.grabMouse(QtCore.Qt.CrossCursor)
        self.grabKeyboard()

    def _sample(self, gp):
        screen = QtGui.QGuiApplication.screenAt(gp) or QtGui.QGuiApplication.primaryScreen()
        geo = screen.geometry()
        n = self.N
        # the whole screen (a rectangle of grabWindow is in different units with display scaling on Windows),
        # mapped by the real size of the picture
        full = screen.grabWindow(0).toImage()
        sx = full.width() / max(1, geo.width())
        sy = full.height() / max(1, geo.height())
        px = int((gp.x() - geo.x()) * sx)
        py = int((gp.y() - geo.y()) * sy)
        step = max(1, int(round(sx)))
        img = QtGui.QImage(n, n, QtGui.QImage.Format_RGB32)
        img.fill(QtGui.QColor("black"))
        for j in range(n):
            yy = py + (j - n // 2) * step
            if not 0 <= yy < full.height():
                continue
            for i in range(n):
                xx = px + (i - n // 2) * step
                if 0 <= xx < full.width():
                    img.setPixel(i, j, full.pixel(xx, yy))
        self.img = img
        self.color = QtGui.QColor(full.pixel(px, py)) if 0 <= px < full.width() and 0 <= py < full.height() \
            else QtGui.QColor()
        # the magnifier sits beside the mouse, inside the screen
        off = theme.px(22)
        x, y = gp.x() + off, gp.y() + off
        if x + self.width() > geo.right():
            x = gp.x() - off - self.width()
        if y + self.height() > geo.bottom():
            y = gp.y() - off - self.height()
        self.move(x, y)
        self.update()
        if self.color.isValid():
            self.hovered.emit(self.color)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(30, 30, 30, 240))
        side = self.N * self.cell
        frame = QtCore.QRect(2, 2, side, side)
        if not self.img.isNull():
            p.drawImage(frame, self.img)
        p.setPen(QtGui.QPen(QtGui.QColor(ACCENT), 2))
        p.drawRect(QtCore.QRect(2 + (self.N // 2) * self.cell, 2 + (self.N // 2) * self.cell, self.cell, self.cell))
        sw = QtCore.QRect(4, side + theme.px(7), theme.px(16), theme.px(16))
        p.fillRect(sw, self.color if self.color.isValid() else QtGui.QColor("black"))
        p.setPen(QtGui.QColor("#e8e8e8"))
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        name = self.color.name().upper() if self.color.isValid() else "—"
        p.drawText(QtCore.QRect(sw.right() + theme.px(6), sw.top() - 2, self.label_w, sw.height() + 4),
                   QtCore.Qt.AlignVCenter, f"{name}    click: take · Esc: cancel")

    def _finish(self, ok):
        if self._done:
            return
        self._done = True
        self.releaseMouse()
        self.releaseKeyboard()
        if ok and self.color.isValid():
            self.picked.emit(QtGui.QColor(self.color))
        else:
            self.cancelled.emit()
        self.close()

    def color_at_global(self, gp):
        self._sample(gp)
        return QtGui.QColor(self.color)

    def mouseMoveEvent(self, e):
        self._pending = e.globalPosition().toPoint()
        if not self._timer.isActive():
            self._timer.start()

    def _sample_pending(self):
        if self._pending is not None and not self._done:
            self._sample(self._pending)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._sample(e.globalPosition().toPoint())
            self._finish(True)
        else:
            self._finish(False)

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self._finish(False)
        elif e.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Space):
            self._finish(True)

    def closeEvent(self, e):
        if not self._done:
            self._done = True
            self.releaseMouse()
            self.releaseKeyboard()
            self.cancelled.emit()
        super().closeEvent(e)


# ---------------------------------------------------------------- the tool
class ColorPicker(QtWidgets.QDialog):
    """The colour tool. Emits colorChanged live; finished(True) after OK, finished(False) after Cancel."""
    colorChanged = QtCore.Signal(QtGui.QColor)
    done_ = QtCore.Signal(bool)

    def __init__(self, parent, color, title="Colour", alpha=False, linear=False):
        super().__init__(parent, QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        self.setWindowTitle(title)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.alpha = alpha
        self.linear = linear
        c = QtGui.QColor(color)
        if not alpha:
            c.setAlpha(255)
        self.original = QtGui.QColor(c)
        h, s, v, a = c.getHsvF()
        self.h = h if h >= 0 else 0.0
        self.s, self.v, self.a = s, v, a
        self._syncing = False
        self._closing = False
        self._dirty = False                                # anything changed since it opened
        self._emit_timer = QtCore.QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.setInterval(15)                   # many mouse moves → one update per frame
        self._emit_timer.timeout.connect(lambda: self.colorChanged.emit(self.color()))
        self._build()
        self._sync()

    # ---- state
    def color(self):
        c = QtGui.QColor.fromHsvF(self.h % 1.0, max(0.0, min(1.0, self.s)), max(0.0, min(1.0, self.v)),
                                  max(0.0, min(1.0, self.a)) if self.alpha else 1.0)
        return c

    def set_color(self, c, emit=True):
        c = QtGui.QColor(c)
        if not c.isValid():
            return
        h, s, v, a = c.getHsvF()
        if h >= 0 and s > 1e-4 and v > 1e-4:
            self.h = h
        self.s, self.v = s, v
        if self.alpha:
            self.a = a
        self._sync()
        if emit:
            self._emit()

    def _emit(self):
        self._dirty = True
        if not self._emit_timer.isActive():
            self._emit_timer.start()

    # ---- UI
    def _build(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(theme.px(10), theme.px(10), theme.px(10), theme.px(10))
        lay.setSpacing(theme.px(8))

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(theme.px(8))
        self.disc = HSDisc(self)
        self.disc.changed.connect(self._disc_changed)
        top.addWidget(self.disc, 1)
        self.vbar = GradientSlider(self, vertical=True)
        self.vbar.setToolTip("Value (brightness)")
        self.vbar.changed.connect(self._v_changed)
        top.addWidget(self.vbar)
        lay.addLayout(top, 1)

        row = QtWidgets.QHBoxLayout()
        self.swatch = OldNewSwatch(self, self.original)
        self.swatch.revert.connect(lambda: self.set_color(self.original))
        row.addWidget(self.swatch, 1)
        self.hex = QtWidgets.QLineEdit(self)
        self.hex.setMaxLength(9)
        self.hex.setFixedWidth(theme.px(86))
        self.hex.setToolTip("Hex colour (display / sRGB): #RRGGBB" + (", #RRGGBBAA" if self.alpha else "")
                            + " or #RGB – Enter applies")
        self._hex_typing = False                           # the user is typing: don't overwrite the text
        self.hex.textEdited.connect(lambda _t: setattr(self, "_hex_typing", True))
        self.hex.editingFinished.connect(self._hex_edited)
        row.addWidget(self.hex)
        self.dropper = QtWidgets.QToolButton(self)
        from . import blicons
        if blicons.has("EYEDROPPER"):
            self.dropper.setIcon(blicons.icon("EYEDROPPER"))
        else:
            self.dropper.setText("◉")
        self.dropper.setToolTip("Eyedropper – pick a colour anywhere on the screen (click: take it, Esc: cancel)")
        self.dropper.clicked.connect(self._eyedropper)
        row.addWidget(self.dropper)
        lay.addLayout(row)

        # mode switch RGB / HSV
        mode_row = QtWidgets.QHBoxLayout()
        mode_row.setSpacing(0)
        self.mode_btns = {}
        grp = QtWidgets.QButtonGroup(self)
        for m in ("RGB", "HSV"):
            b = QtWidgets.QToolButton(self)
            b.setText(m)
            b.setCheckable(True)
            b.setAutoRaise(False)
            b.setMinimumWidth(theme.px(48))
            b.setStyleSheet(f"QToolButton:checked{{background:{ACCENT}; color:#fff;}}")
            grp.addButton(b)
            mode_row.addWidget(b)
            self.mode_btns[m] = b
            b.clicked.connect(lambda _=False, m=m: self._set_mode(m))
        mode_row.addStretch(1)
        if self.linear:
            lbl = QtWidgets.QLabel("linear RGB", self)
            lbl.setStyleSheet("color:#8a8a8a;")
            lbl.setToolTip("This property stores scene-linear colour: the RGB numbers are linear like in "
                           "Blender's fields, the disc, swatches and Hex show the display colour")
            mode_row.addWidget(lbl)
        lay.addLayout(mode_row)

        self.grid = QtWidgets.QGridLayout()
        self.grid.setHorizontalSpacing(theme.px(6))
        self.grid.setVerticalSpacing(theme.px(4))
        self.rows = {}
        for i, (key, label, rng, dec, suffix) in enumerate((
                ("R", "R", 1.0, 3, ""), ("G", "G", 1.0, 3, ""), ("B", "B", 1.0, 3, ""),
                ("H", "H", 360.0, 1, "°"), ("S", "S", 1.0, 3, ""), ("V", "V", 1.0, 3, ""),
                ("A", "A", 1.0, 3, ""))):
            lab = QtWidgets.QLabel(label, self)
            lab.setFixedWidth(theme.px(12))
            sl = GradientSlider(self, checker=(key == "A"))
            sp = QtWidgets.QDoubleSpinBox(self)
            sp.setRange(0.0, rng)
            sp.setDecimals(dec)
            sp.setSingleStep(1.0 if rng > 1 else 0.01)
            sp.setSuffix(suffix)
            sp.setFixedWidth(theme.px(70))
            sp.setKeyboardTracking(False)
            sl.changed.connect(lambda v, k=key: self._channel(k, v, display=True))
            sp.valueChanged.connect(lambda v, k=key, rr=rng: self._channel(k, v / rr))
            self.grid.addWidget(lab, i, 0)
            self.grid.addWidget(sl, i, 1)
            self.grid.addWidget(sp, i, 2)
            self.rows[key] = (lab, sl, sp, rng)
        lay.addLayout(self.grid)

        # swatches
        self.sw_box = QtWidgets.QWidget(self)
        sl_ = QtWidgets.QVBoxLayout(self.sw_box)
        sl_.setContentsMargins(0, 0, 0, 0)
        sl_.setSpacing(theme.px(3))
        lay.addWidget(self.sw_box)
        self._fill_swatches()

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        cancel = QtWidgets.QPushButton("Cancel", self)
        cancel.setToolTip("Put the colour back as it was (Esc)")
        cancel.clicked.connect(self.cancel)
        ok = QtWidgets.QPushButton("OK", self)
        ok.setDefault(True)
        ok.setToolTip("Keep the colour (Enter)")
        ok.clicked.connect(self.accept_color)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        mode = str(_settings().value(KEY_MODE, "RGB"))
        self._set_mode(mode if mode in self.mode_btns else "RGB", save=False)
        self.setMinimumWidth(theme.px(300))

    def _swatch_row(self, title, cols, kind):
        box = QtWidgets.QWidget(self.sw_box)
        v = QtWidgets.QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.px(2))
        head = QtWidgets.QHBoxLayout()
        lab = QtWidgets.QLabel(title, box)
        lab.setStyleSheet("color:#9a9a9a;")
        head.addWidget(lab)
        head.addStretch(1)
        if kind == "palette":
            add = QtWidgets.QToolButton(box)
            add.setText("+")
            add.setAutoRaise(True)
            add.setToolTip("Add the current colour to the palette")
            add.clicked.connect(self._add_to_palette)
            head.addWidget(add)
        v.addLayout(head)
        flow = QtWidgets.QGridLayout()
        flow.setSpacing(theme.px(3))
        per_row = 12
        for i, c in enumerate(cols):
            b = SwatchButton(box, c, (QtGui.QColor(c).name().upper()
                                      + ("\nRight click: remove" if kind == "palette" else "")))
            b.clicked.connect(lambda _=False, c=c: self.set_color(QtGui.QColor(c)))
            if kind == "palette":
                b.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
                b.customContextMenuRequested.connect(lambda _p, c=c: self._remove_from_palette(c))
            flow.addWidget(b, i // per_row, i % per_row)
        if not cols:
            empty = QtWidgets.QLabel("Empty – “+” adds the current colour" if kind == "palette" else "—", box)
            empty.setStyleSheet("color:#6f6f6f;")
            flow.addWidget(empty, 0, 0, 1, per_row)
        flow.setColumnStretch(per_row, 1)
        v.addLayout(flow)
        return box

    def _fill_swatches(self):
        lay = self.sw_box.layout()
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        rec = recent_colors()
        if rec:
            lay.addWidget(self._swatch_row("Recent", rec, "recent"))
        lay.addWidget(self._swatch_row("Palette", palette_colors(), "palette"))
        lay.addWidget(self._swatch_row("Basic", BASIC, "basic"))

    def _add_to_palette(self):
        c = self.color()
        name = c.name(QtGui.QColor.HexArgb if self.alpha and c.alpha() < 255 else QtGui.QColor.HexRgb)
        cols = [x for x in palette_colors() if x.lower() != name.lower()]
        _save_list(KEY_PALETTE, (cols + [name])[-MAX_PALETTE:])
        self._fill_swatches()

    def _remove_from_palette(self, col):
        _save_list(KEY_PALETTE, [x for x in palette_colors() if x.lower() != col.lower()])
        self._fill_swatches()

    def _set_mode(self, m, save=True):
        for k, b in self.mode_btns.items():
            b.setChecked(k == m)
        for key, (lab, sl, sp, _r) in self.rows.items():
            show = (key in "RGB" and m == "RGB") or (key in "HSV" and m == "HSV") or (key == "A" and self.alpha)
            for w in (lab, sl, sp):
                w.setVisible(show)
        if save:
            _settings().setValue(KEY_MODE, m)
        self.adjustSize()

    # ---- changes from the widgets
    def _disc_changed(self, h, s):
        self.h, self.s = h, s
        self._sync(skip="disc")
        self._emit()

    def _v_changed(self, v):
        self.v = v
        self._sync(skip="vbar")
        self._emit()

    def _channel(self, key, val, display=False):
        """display: the value comes from a slider (display colour); else from a number field (linear RGB for
        linear properties)."""
        if self._syncing:
            return
        val = max(0.0, min(1.0, val))
        if key in "RGB":
            c = self.color()
            rgb = [c.redF(), c.greenF(), c.blueF()]
            lin = self.linear and not display
            if lin:
                rgb = [srgb_to_lin(x) for x in rgb]
            rgb["RGB".index(key)] = val
            if lin:
                rgb = [lin_to_srgb(x) for x in rgb]
            nc = QtGui.QColor.fromRgbF(*[max(0.0, min(1.0, x)) for x in rgb], self.a if self.alpha else 1.0)
            h, s, v, _a = nc.getHsvF()
            if h >= 0 and s > 1e-4 and v > 1e-4:
                self.h = h
            self.s, self.v = s, v
        elif key == "H":
            self.h = val % 1.0 if val < 1.0 else 0.0
        elif key == "S":
            self.s = val
        elif key == "V":
            self.v = val
        elif key == "A":
            self.a = val
        self._sync()
        self._emit()

    def _hex_edited(self):
        if not self._hex_typing:            # focus left the field without typing: nothing to apply
            return
        self._hex_typing = False
        t = self.hex.text().strip()
        if not t.startswith("#"):
            t = "#" + t
        body = t[1:]
        if len(body) == 3:
            body = "".join(ch * 2 for ch in body)
        c = QtGui.QColor("#" + body[:6])
        if not c.isValid():
            self._sync()
            return
        if len(body) == 8 and self.alpha:
            try:
                c.setAlpha(int(body[6:8], 16))
            except ValueError:
                pass
        elif self.alpha:
            c.setAlphaF(self.a)
        self.set_color(c)

    def _eyedropper(self):
        before = self.color()
        sp = ScreenPicker(self)
        sp.hovered.connect(lambda c: self.set_color(c) if c.isValid() else None)
        sp.picked.connect(lambda c: self.set_color(c) if c.isValid() else self.set_color(before))
        sp.cancelled.connect(lambda: self.set_color(before))
        sp.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        sp.start()

    # ---- showing the state
    def _sync(self, skip=None):
        self._syncing = True
        try:
            c = self.color()
            if skip != "disc":
                self.disc.set_hsv(self.h, self.s, self.v)
            else:
                self.disc.v = self.v
            self.vbar.set_value(self.v)
            self.vbar.set_stops([(0.0, QtGui.QColor("black")), (1.0, QtGui.QColor.fromHsvF(self.h % 1.0, self.s, 1))])
            rgb = [c.redF(), c.greenF(), c.blueF()]
            nums = [srgb_to_lin(x) for x in rgb] if self.linear else rgb
            for i, key in enumerate("RGB"):
                lo = QtGui.QColor(c)
                hi = QtGui.QColor(c)
                vals_lo = list(rgb)
                vals_hi = list(rgb)
                vals_lo[i], vals_hi[i] = 0.0, 1.0
                lo.setRgbF(*vals_lo, 1.0)
                hi.setRgbF(*vals_hi, 1.0)
                self.rows[key][1].set_stops([(0.0, lo), (1.0, hi)])
                self.rows[key][1].set_value(rgb[i])
                self._set_spin(key, nums[i])
            hue_stops = [(i / 6.0, QtGui.QColor.fromHsvF((i / 6.0) % 1.0, max(self.s, 0.6), max(self.v, 0.6)))
                         for i in range(7)]
            self.rows["H"][1].set_stops(hue_stops)
            self.rows["H"][1].set_value(self.h)
            self._set_spin("H", self.h)
            self.rows["S"][1].set_stops([(0.0, QtGui.QColor.fromHsvF(self.h % 1.0, 0, self.v)),
                                         (1.0, QtGui.QColor.fromHsvF(self.h % 1.0, 1, self.v))])
            self.rows["S"][1].set_value(self.s)
            self._set_spin("S", self.s)
            self.rows["V"][1].set_stops([(0.0, QtGui.QColor("black")),
                                         (1.0, QtGui.QColor.fromHsvF(self.h % 1.0, self.s, 1))])
            self.rows["V"][1].set_value(self.v)
            self._set_spin("V", self.v)
            ca = QtGui.QColor(c)
            ca.setAlpha(0)
            cb = QtGui.QColor(c)
            cb.setAlpha(255)
            self.rows["A"][1].set_stops([(0.0, ca), (1.0, cb)])
            self.rows["A"][1].set_value(self.a)
            self._set_spin("A", self.a)
            fmt = QtGui.QColor.HexRgb
            name = c.name(fmt).upper()
            if self.alpha and c.alpha() < 255:
                name += f"{c.alpha():02X}"
            if not self._hex_typing:
                self.hex.setText(name)
            self.swatch.set_new(c)
        finally:
            self._syncing = False

    def _set_spin(self, key, val):
        sp, rng = self.rows[key][2], self.rows[key][3]
        sp.blockSignals(True)
        sp.setValue(val * rng)
        sp.blockSignals(False)

    # ---- closing
    def accept_color(self, close=True):
        if self._closing:
            return
        self._closing = True
        if self._emit_timer.isActive():
            self._emit_timer.stop()
        c = self.color()
        if self._dirty:                     # untouched: leave the exact original value alone
            self.colorChanged.emit(c)
            add_recent(c)
        self.done_.emit(True)
        if close:
            self.close()

    def cancel(self):
        if self._closing:
            return
        self._closing = True
        self._emit_timer.stop()
        if self._dirty:
            self.colorChanged.emit(QtGui.QColor(self.original))
        self.done_.emit(False)
        self.close()

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self.cancel()
            return
        if e.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if self.hex.hasFocus():
                self._hex_edited()
                self.hex.clearFocus()
                return
            self.accept_color()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        global _current
        if not self._closing:                     # window X / another picker: keep the colour (like Blender)
            self.accept_color(close=False)
        if _current is self:
            _current = None
        super().closeEvent(e)

    def place_near(self, anchor):
        self.adjustSize()
        size = self.sizeHint()
        try:
            if anchor.height() > theme.px(80):          # not a button (a whole view …): at the mouse
                raise ValueError
            g = anchor.mapToGlobal(QtCore.QPoint(0, anchor.height() + theme.px(4)))
        except Exception:
            g = QtGui.QCursor.pos()
            anchor = None
        screen = QtGui.QGuiApplication.screenAt(g) or QtGui.QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        x = min(max(avail.left(), g.x()), avail.right() - size.width())
        y = g.y()
        if y + size.height() > avail.bottom():
            y = max(avail.top(), g.y() - (anchor.height() if anchor is not None else 0) - size.height()
                    - theme.px(8))
        self.move(x, y)


def pick(anchor, color, on_change, title="Colour", alpha=False, linear=False, on_done=None):
    """Opens the colour tool next to `anchor` (the clicked button). on_change(QColor) runs live on every
    change (also with the original colour after Cancel); on_done(ok: bool) when it closes. Returns the window."""
    global _current
    if _current is not None:
        try:
            _current.accept_color()
        except RuntimeError:
            pass
        _current = None
    parent = anchor.window() if anchor is not None else QtWidgets.QApplication.activeWindow()
    dlg = ColorPicker(parent, color, title=title, alpha=alpha, linear=linear)

    def _changed(c):
        try:
            on_change(QtGui.QColor(c))
        except Exception:
            import traceback
            from .bridge import log
            log("Colour tool: " + traceback.format_exc(), "ERROR")
    dlg.colorChanged.connect(_changed)
    if on_done is not None:
        dlg.done_.connect(lambda ok: on_done(ok))
    dlg.place_near(anchor)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    _current = dlg
    return dlg


def current():
    return _current

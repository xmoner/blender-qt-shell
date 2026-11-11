"""Startup banner: when Qt Shell starts, the Qt Shell banner (banner.png) appears in the middle of the screen
and goes away as soon as the mouse moves (or on a click / key, at the latest after TIMEOUT seconds). Help → Show Qt Shell Banner shows it again.

Shown once per Blender session (not again after a dev reload or when the window is reopened).
QSettings "splash/show" (Qt Preferences → Window → Startup) switches it off.
No app-level event filter: mouse movement is detected by polling the cursor position.
"""
import os

from PySide6 import QtCore, QtGui, QtWidgets

from . import theme

BANNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banner.png")
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qt_shell_icon.png")   # Help menu item
WIDTH = 720              # logical width of the banner on screen (smaller on small screens)
MOVE_PX = 4              # cursor movement (logical px) that dismisses it
POLL_MS = 40
TIMEOUT = 30.0           # safety: gone after this many seconds even without movement
KEY = "splash/show"
_ENV = "QTSHELL_SPLASH_SHOWN"     # survives module reloads within one Blender process

_current = None


def enabled():
    v = QtCore.QSettings("QtShell", "QtShell").value(KEY, True)
    return str(v).lower() not in ("false", "0", "no")


def set_enabled(on):
    QtCore.QSettings("QtShell", "QtShell").setValue(KEY, bool(on))


class Splash(QtWidgets.QWidget):
    def __init__(self, parent=None):
        flags = (QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
                 | QtCore.Qt.WindowDoesNotAcceptFocus)
        super().__init__(parent, flags)
        self.setObjectName("qtshell_splash")
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.pix = QtGui.QPixmap(BANNER)
        try:
            from . import bl_info
            self.version = "Qt Shell " + ".".join(str(v) for v in bl_info["version"])
        except Exception:
            self.version = "Qt Shell"
        scr = (parent.screen() if parent is not None and parent.isVisible() else None) \
            or QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) or QtGui.QGuiApplication.primaryScreen()
        area = scr.availableGeometry()
        w = min(theme.px(WIDTH), int(area.width() * 0.6))
        ratio = (self.pix.height() / self.pix.width()) if not self.pix.isNull() and self.pix.width() else 0.5
        h = int(w * ratio)
        self.setFixedSize(w, h)
        self.move(area.center().x() - w // 2, area.center().y() - h // 2)
        self._start = QtGui.QCursor.pos()
        self._elapsed = QtCore.QElapsedTimer()
        self._elapsed.start()
        self._closing = False
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.setToolTip("")

    def showEvent(self, ev):
        super().showEvent(ev)
        self._start = QtGui.QCursor.pos()     # movement counts from the moment it is visible
        self._timer.start()

    def _poll(self):
        try:
            d = QtGui.QCursor.pos() - self._start
            moved = max(abs(d.x()), abs(d.y())) >= MOVE_PX
        except Exception:
            moved = True
        if moved or self._elapsed.elapsed() > TIMEOUT * 1000:
            self.dismiss()

    def dismiss(self):
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        anim = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(160)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.finished.connect(self.close)
        anim.start()
        self._anim = anim

    def mousePressEvent(self, ev):
        self.dismiss()

    def keyPressEvent(self, ev):
        self.dismiss()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = theme.px(14)
        path = QtGui.QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.setClipPath(path)
        if self.pix.isNull():
            p.fillRect(r, QtGui.QColor("#16201c"))
            f = p.font()
            f.setPointSizeF(f.pointSizeF() * 3)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QtGui.QColor("#ffffff"))
            p.drawText(r, QtCore.Qt.AlignCenter, "Qt Shell")
        else:
            p.drawPixmap(r, self.pix, QtCore.QRectF(self.pix.rect()))
        p.setClipping(False)
        f = p.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() * 0.9))
        p.setFont(f)
        p.setPen(QtGui.QColor(255, 255, 255, 120))
        m = theme.px(12)
        p.drawText(r.adjusted(m, m, -m, -m), QtCore.Qt.AlignRight | QtCore.Qt.AlignBottom, self.version)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 40), 1.0))
        p.drawPath(path)
        p.end()

    def closeEvent(self, ev):
        global _current
        self._timer.stop()
        if _current is self:
            _current = None
        super().closeEvent(ev)


def show(parent=None, force=False):
    """Shows the banner (once per Blender session unless force=True). Returns the widget or None."""
    global _current
    if not force and (os.environ.get(_ENV) or not enabled()):
        return None
    os.environ[_ENV] = "1"
    try:
        if _current is not None:
            _current.close()
    except RuntimeError:
        pass
    _current = Splash(parent)
    _current.show()
    _current.raise_()
    return _current


def current():
    try:
        return _current if _current is not None and _current.isVisible() else None
    except RuntimeError:
        return None

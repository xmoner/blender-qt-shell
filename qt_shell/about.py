"""About the author + ways to donate: the "Do not touch it." button at the bottom right of the status bar
(with a colourful heart) and Help → About the Author… open the same window.
The "Sponsors" button next to it (a palm holding coins – coins.svg) and Help → Sponsors… open the Sponsor window;
its contact is SPONSOR_CONTACT below (plain text or simple HTML, e.g. an e-mail as a mailto: link).

The texts are placeholders – fill in AUTHOR and DONATE below (no other code needs to change):
  AUTHOR["name"], AUTHOR["text"] (plain text or simple HTML, paragraphs separated by blank lines),
  DONATE = [(label, url, note), …] – each becomes a button that opens the link in the browser.
"""
import os

from PySide6 import QtCore, QtGui, QtWidgets

from . import theme

AUTHOR = {
    "name": "",                     # e.g. "Lukáš …"
    "text": "",                     # a few words about the author / the project
}
DONATE = [
    # ("PayPal", "https://paypal.me/…", "One-off donation"),
    # ("Ko-fi", "https://ko-fi.com/…", "Buy me a coffee"),
    # ("GitHub Sponsors", "https://github.com/sponsors/…", "Monthly support"),
]
BUTTON_TEXT = "Do not touch it."
SPONSOR_BUTTON_TEXT = "Sponsors"
SPONSOR_CONTACT = ""                # e.g. '<a href="mailto:…">…</a>' – shown after "please contact:"
HEART = ("#ff4d6d", "#ff9f1c", "#ffd60a", "#2ec4b6", "#3a86ff", "#8338ec")   # the heart's colours


# ---------------------------------------------------------------- the heart
def _heart_path(size):
    s = float(size)
    p = QtGui.QPainterPath()
    p.moveTo(0.5 * s, 0.92 * s)
    p.cubicTo(0.08 * s, 0.62 * s, -0.04 * s, 0.30 * s, 0.20 * s, 0.14 * s)
    p.cubicTo(0.34 * s, 0.05 * s, 0.46 * s, 0.12 * s, 0.5 * s, 0.26 * s)
    p.cubicTo(0.54 * s, 0.12 * s, 0.66 * s, 0.05 * s, 0.80 * s, 0.14 * s)
    p.cubicTo(1.04 * s, 0.30 * s, 0.92 * s, 0.62 * s, 0.5 * s, 0.92 * s)
    p.closeSubpath()
    return p


HEART_SVG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heart.svg")   # colour-wheel heart
_svg_renderer = None


def _svg():
    global _svg_renderer
    if _svg_renderer is None:
        try:
            from PySide6 import QtSvg
            r = QtSvg.QSvgRenderer(HEART_SVG)
            _svg_renderer = r if r.isValid() else False
        except Exception:
            _svg_renderer = False
    return _svg_renderer or None


def heart_pixmap(size=16, dpr=2.0):
    """The heart (heart.svg – vector, sharp at any size); the painted rainbow heart if QtSvg is missing."""
    px = max(8, int(round(size * dpr)))
    r = _svg()
    if r is not None:
        img = QtGui.QImage(px, px, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        r.render(p, QtCore.QRectF(0, 0, px, px))
        p.end()
        pm = QtGui.QPixmap.fromImage(img)
        pm.setDevicePixelRatio(dpr)
        return pm
    return _painted_heart(px, dpr)


def _painted_heart(px, dpr):
    img = QtGui.QImage(px, px, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    g = QtGui.QLinearGradient(0.10 * px, 0.25 * px, 0.90 * px, 0.75 * px)   # every colour across the heart
    for i, c in enumerate(HEART):
        g.setColorAt(i / (len(HEART) - 1), QtGui.QColor(c))
    path = _heart_path(px)
    p.fillPath(path, g)
    hl = QtGui.QRadialGradient(QtCore.QPointF(px * 0.32, px * 0.30), px * 0.28)   # a soft shine
    hl.setColorAt(0, QtGui.QColor(255, 255, 255, 140))
    hl.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
    p.fillPath(path, hl)
    p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 90), max(1.0, px / 32)))
    p.drawPath(path)
    p.end()
    pm = QtGui.QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def heart_icon(size=16):
    ic = QtGui.QIcon()
    for d in (1.0, 1.25, 1.5, 2.0):
        ic.addPixmap(heart_pixmap(size, d))
    return ic


# ---------------------------------------------------------------- the coins (Sponsors)
COINS_SVG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coins.svg")   # palm holding coins
_coins_renderer = None


def _coins_svg():
    global _coins_renderer
    if _coins_renderer is None:
        try:
            from PySide6 import QtSvg
            r = QtSvg.QSvgRenderer(COINS_SVG)
            _coins_renderer = r if r.isValid() else False
        except Exception:
            _coins_renderer = False
    return _coins_renderer or None


def coins_pixmap(size=16, dpr=2.0):
    """A palm holding gold coins (coins.svg); plain painted coins if QtSvg is missing."""
    px = max(8, int(round(size * dpr)))
    img = QtGui.QImage(px, px, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    r = _coins_svg()
    if r is not None:
        r.render(p, QtCore.QRectF(0, 0, px, px))
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#8a6414"), max(1.0, px / 32)))
        p.setBrush(QtGui.QColor("#f5c542"))
        for i in range(3):
            p.drawEllipse(QtCore.QRectF(px * 0.15, px * (0.62 - i * 0.18), px * 0.7, px * 0.24))
    p.end()
    pm = QtGui.QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def coins_icon(size=16):
    ic = QtGui.QIcon()
    for d in (1.0, 1.25, 1.5, 2.0):
        ic.addPixmap(coins_pixmap(size, d))
    return ic


# ---------------------------------------------------------------- status bar buttons
def _status_button(parent, text, icon, tip, on_click):
    b = QtWidgets.QToolButton(parent)
    b.setText(text)
    b.setIcon(icon)
    b.setIconSize(QtCore.QSize(theme.px(16), theme.px(16)))
    b.setStyleSheet(f"QToolButton {{ qproperty-iconSize: {theme.px(16)}px {theme.px(16)}px; }}")
    b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    b.setAutoRaise(True)
    b.setToolTip(tip)
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.clicked.connect(lambda _=False: on_click())
    return b


def make_button(parent, on_click):
    return _status_button(parent, BUTTON_TEXT, heart_icon(16),
                          "About the author – and how to support Qt Shell", on_click)


def make_sponsor_button(parent, on_click):
    return _status_button(parent, SPONSOR_BUTTON_TEXT, coins_icon(16),
                          "Become a sponsor of Qt Shell", on_click)


# ---------------------------------------------------------------- the window
class AboutDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("qtshell_about")
        self.setWindowTitle("About the Author")
        self.setMinimumWidth(theme.px(420))
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(theme.px(18), theme.px(16), theme.px(18), theme.px(14))
        lay.setSpacing(theme.px(10))

        head = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel(self)
        icon.setPixmap(heart_pixmap(48, self.devicePixelRatioF() or 1.0))
        head.addWidget(icon, 0, QtCore.Qt.AlignTop)
        hv = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("About the Author", self)
        f = title.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.5)
        title.setFont(f)
        hv.addWidget(title)
        try:
            from . import bl_info
            ver = ".".join(str(v) for v in bl_info["version"])
        except Exception:
            ver = ""
        sub = QtWidgets.QLabel(f"Qt Shell {ver}" + (f" · {AUTHOR['name']}" if AUTHOR.get("name") else ""), self)
        sub.setStyleSheet("color:#9a9a9a;")
        hv.addWidget(sub)
        head.addLayout(hv, 1)
        lay.addLayout(head)

        lay.addWidget(self._section("About"))
        text = AUTHOR.get("text") or "<i>Coming soon – a few words about the author will be here.</i>"
        about = QtWidgets.QLabel(text.replace("\n\n", "<br><br>"), self)
        about.setWordWrap(True)
        about.setTextFormat(QtCore.Qt.RichText)
        about.setOpenExternalLinks(True)
        about.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        lay.addWidget(about)

        lay.addWidget(self._section("Donate"))
        if DONATE:
            note = QtWidgets.QLabel("If Qt Shell saves you time, you can support its development:", self)
            note.setWordWrap(True)
            lay.addWidget(note)
            for label, url, tip in DONATE:
                b = QtWidgets.QPushButton(heart_icon(16), label, self)
                b.setToolTip(f"{tip}\n{url}" if tip else url)
                b.setCursor(QtCore.Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, u=url: QtGui.QDesktopServices.openUrl(QtCore.QUrl(u)))
                lay.addWidget(b)
        else:
            soon = QtWidgets.QLabel("<i>Coming soon – ways to support Qt Shell will be listed here.</i>", self)
            soon.setWordWrap(True)
            lay.addWidget(soon)

        lay.addStretch(1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        close = QtWidgets.QPushButton("Close", self)
        close.setDefault(True)
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)

    def _section(self, text):
        lab = QtWidgets.QLabel(text, self)
        f = lab.font()
        f.setBold(True)
        lab.setFont(f)
        lab.setStyleSheet("color:#d0d0d0; border-bottom:1px solid #4a4a4a; padding-bottom:2px;")
        return lab


class SponsorDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("qtshell_sponsor")
        self.setWindowTitle("Sponsor")
        self.setMinimumWidth(theme.px(440))
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(theme.px(18), theme.px(16), theme.px(18), theme.px(14))
        lay.setSpacing(theme.px(12))

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(theme.px(14))
        icon = QtWidgets.QLabel(self)
        icon.setPixmap(coins_pixmap(64, self.devicePixelRatioF() or 1.0))
        head.addWidget(icon, 0, QtCore.Qt.AlignTop)
        hv = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("Sponsor", self)
        f = title.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.5)
        title.setFont(f)
        hv.addWidget(title)
        try:
            from . import bl_info
            ver = ".".join(str(v) for v in bl_info["version"])
        except Exception:
            ver = ""
        sub = QtWidgets.QLabel(f"Qt Shell {ver}", self)
        sub.setStyleSheet("color:#9a9a9a;")
        hv.addWidget(sub)
        hv.addStretch(1)
        head.addLayout(hv, 1)
        lay.addLayout(head)

        contact = SPONSOR_CONTACT or "<i>(contact coming soon)</i>"
        self.text = QtWidgets.QLabel(
            "Would you like to become a sponsor of <b>Qt Shell GUI</b> and support the people who develop it?"
            f"<br><br>If so, please contact: {contact}", self)
        self.text.setWordWrap(True)
        self.text.setTextFormat(QtCore.Qt.RichText)
        self.text.setOpenExternalLinks(True)
        self.text.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        lay.addWidget(self.text)

        lay.addStretch(1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        close = QtWidgets.QPushButton("Close", self)
        close.setDefault(True)
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)


def _open(cls, holder, parent):
    dlg = holder.get("dlg")
    try:
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return dlg
    except RuntimeError:
        pass
    dlg = cls(parent)
    dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    holder["dlg"] = dlg
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg


_sponsor = {}


def show_sponsor(parent=None):
    """Opens (or raises) the Sponsor window."""
    return _open(SponsorDialog, _sponsor, parent)


_dialog = None


def show(parent=None):
    """Opens (or raises) the About the Author window."""
    global _dialog
    try:
        if _dialog is not None and _dialog.isVisible():
            _dialog.raise_()
            _dialog.activateWindow()
            return _dialog
    except RuntimeError:
        _dialog = None
    _dialog = AboutDialog(parent)
    _dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog

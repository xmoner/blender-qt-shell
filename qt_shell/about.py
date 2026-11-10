"""About the author + ways to donate: the "Do not touch it." button at the bottom right of the status bar
(with a colourful heart) and Help → About the Author… open the same window.

The texts are placeholders – fill in AUTHOR and DONATE below (no other code needs to change):
  AUTHOR["name"], AUTHOR["text"] (plain text or simple HTML, paragraphs separated by blank lines),
  DONATE = [(label, url, note), …] – each becomes a button that opens the link in the browser.
"""
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


def heart_pixmap(size=16, dpr=2.0):
    px = max(8, int(round(size * dpr)))
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


# ---------------------------------------------------------------- status bar button
def make_button(parent, on_click):
    b = QtWidgets.QToolButton(parent)
    b.setText(BUTTON_TEXT)
    b.setIcon(heart_icon(16))
    b.setIconSize(QtCore.QSize(theme.px(16), theme.px(16)))
    b.setStyleSheet(f"QToolButton {{ qproperty-iconSize: {theme.px(16)}px {theme.px(16)}px; }}")
    b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    b.setAutoRaise(True)
    b.setToolTip("About the author – and how to support Qt Shell")
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.clicked.connect(lambda _=False: on_click())
    return b


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

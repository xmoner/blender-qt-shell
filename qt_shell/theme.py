"""Tmavé téma podobné Blenderu (Fusion + paleta)."""
from PySide6 import QtGui, QtWidgets

C = {
    "window": "#2b2b2b", "base": "#1d1d1d", "alt": "#262626", "button": "#3a3a3a",
    "text": "#e5e5e5", "dim": "#8c8c8c", "highlight": "#4772b3", "accent": "#ffa033",
    "border": "#151515", "header": "#303030", "viewport": "#3d3d3d",
}

QSS = f"""
QMainWindow::separator {{ background: {C['border']}; width: 3px; height: 3px; }}
QDockWidget::title {{ background: {C['header']}; padding: 4px 6px; }}
QToolButton, QPushButton {{ background: {C['button']}; border: 1px solid {C['border']};
    border-radius: 4px; padding: 3px 8px; }}
QToolButton:hover, QPushButton:hover {{ background: #474747; }}
QToolButton:checked, QPushButton:checked {{ background: {C['highlight']}; }}
QAbstractSpinBox, QLineEdit, QComboBox {{ background: #545454; border: 1px solid {C['border']};
    border-radius: 4px; padding: 2px 4px; min-height: 18px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0px; border: none; }}
QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow {{ width: 0px; height: 0px; }}
QAbstractSpinBox:focus, QLineEdit:focus {{ background: #222; }}
QComboBox QAbstractItemView {{ background: {C['alt']}; selection-background-color: {C['highlight']}; }}
QGroupBox {{ border: 1px solid {C['border']}; border-radius: 5px; margin-top: 6px; }}
QFrame#qtshell_panel {{ background: #303030; border: 1px solid {C['border']}; border-radius: 5px; }}
QFrame#qtshell_box {{ background: #2a2a2a; border: 1px solid #202020; border-radius: 4px; }}
QToolButton#qtshell_panel_header {{ background: transparent; border: none; font-weight: bold;
    text-align: left; padding: 3px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: {C['alt']}; padding: 6px; border: none; }}
QTabBar::tab:selected {{ background: {C['highlight']}; }}
QTreeWidget, QListWidget, QPlainTextEdit {{ background: {C['alt']}; border: none; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {C['highlight']}; }}
QStatusBar {{ background: {C['header']}; color: {C['dim']}; }}
QLabel[dim="true"] {{ color: {C['dim']}; }}
"""


def apply(app):
    app.setStyle(QtWidgets.QStyleFactory.create("Fusion"))
    pal = QtGui.QPalette()
    col = QtGui.QColor
    pal.setColor(QtGui.QPalette.Window, col(C["window"]))
    pal.setColor(QtGui.QPalette.WindowText, col(C["text"]))
    pal.setColor(QtGui.QPalette.Base, col(C["base"]))
    pal.setColor(QtGui.QPalette.AlternateBase, col(C["alt"]))
    pal.setColor(QtGui.QPalette.Text, col(C["text"]))
    pal.setColor(QtGui.QPalette.Button, col(C["button"]))
    pal.setColor(QtGui.QPalette.ButtonText, col(C["text"]))
    pal.setColor(QtGui.QPalette.Highlight, col(C["highlight"]))
    pal.setColor(QtGui.QPalette.HighlightedText, col("#ffffff"))
    pal.setColor(QtGui.QPalette.ToolTipBase, col(C["base"]))
    pal.setColor(QtGui.QPalette.ToolTipText, col(C["text"]))
    pal.setColor(QtGui.QPalette.PlaceholderText, col(C["dim"]))
    for role in (QtGui.QPalette.WindowText, QtGui.QPalette.Text, QtGui.QPalette.ButtonText):
        pal.setColor(QtGui.QPalette.Disabled, role, col("#6a6a6a"))
    app.setPalette(pal)
    app.setStyleSheet(QSS)


_icon_cache = {}


def type_icon(kind):
    """Malá kulatá ikonka s písmenem (bez externích obrázků)."""
    if kind in _icon_cache:
        return _icon_cache[kind]
    table = {
        "MESH": ("M", "#e8a04c"), "CURVE": ("C", "#7fc77f"), "SURFACE": ("S", "#7fc77f"),
        "FONT": ("T", "#7fc77f"), "META": ("B", "#7fc77f"), "ARMATURE": ("A", "#6fb5e8"),
        "LATTICE": ("L", "#b58fe8"), "EMPTY": ("E", "#aaaaaa"), "CAMERA": ("K", "#c0c0c0"),
        "LIGHT": ("☀", "#f0d060"), "SPEAKER": ("♪", "#aaaaaa"), "LIGHT_PROBE": ("P", "#aaaaaa"),
        "GREASEPENCIL": ("G", "#7fc77f"), "GPENCIL": ("G", "#7fc77f"), "CURVES": ("H", "#7fc77f"),
        "POINTCLOUD": ("·", "#7fc77f"), "VOLUME": ("V", "#7fc77f"), "COLLECTION": ("▣", "#e0e0e0"),
        "SCENE": ("◆", "#e0e0e0"),
    }
    letter, color = table.get(kind, ("?", "#999999"))
    pm = QtGui.QPixmap(32, 32)
    pm.fill(QtGui.QColor(0, 0, 0, 0))
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setBrush(QtGui.QColor(color))
    p.setPen(QtGui.QColor(0, 0, 0, 0))
    p.drawEllipse(2, 2, 28, 28)
    f = p.font()
    f.setPixelSize(18)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QtGui.QColor("#1a1a1a"))
    from PySide6.QtCore import Qt
    p.drawText(pm.rect(), Qt.AlignCenter, letter)
    p.end()
    icon = QtGui.QIcon(pm)
    _icon_cache[kind] = icon
    return icon

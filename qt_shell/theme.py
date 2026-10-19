"""Dark theme similar to Blender (Fusion + palette)."""
from PySide6 import QtGui, QtWidgets

C = {
    "window": "#2b2b2b", "base": "#1d1d1d", "alt": "#262626", "button": "#3a3a3a",
    "text": "#e5e5e5", "dim": "#8c8c8c", "highlight": "#4772b3", "accent": "#ffa033",
    "border": "#151515", "header": "#303030", "viewport": "#3d3d3d",
}

# buttons "light up" light blue under the mouse and when pressed
HOVER = {"bg": "#46658c", "border": "#6d9ad4", "press_bg": "#5b84b8", "press_border": "#9cc3f0",
         "checked_hover": "#5683c4"}


def hover_qss(sel="QToolButton, QPushButton"):
    """Hover / pressed rules for buttons – add them to widget style sheets that set a button
    background, otherwise those would hide the effect."""
    h = HOVER
    hov = ", ".join(f"{s.strip()}:hover" for s in sel.split(","))
    prs = ", ".join(f"{s.strip()}:pressed" for s in sel.split(","))
    chk = ", ".join(f"{s.strip()}:checked:hover" for s in sel.split(","))
    return (f"{hov} {{ background: {h['bg']}; border: 1px solid {h['border']}; }}\n"
            f"{prs} {{ background: {h['press_bg']}; border: 1px solid {h['press_border']}; }}\n"
            f"{chk} {{ background: {h['checked_hover']}; }}\n")


# Interface size (set from the add-on preferences / Window → Interface Size…)
ui_scale = 1.0      # buttons, fields, spacing, icons and text
font_scale = 1.0    # extra multiplier for text only
_base_pt = None     # system default font size in points (captured once)


def px(n):
    """Scales a size in pixels by the interface scale."""
    return max(1, int(round(n * ui_scale)))


def fs(n):
    """Scales a font pixel size by the interface and text scale."""
    return max(6, int(round(n * ui_scale * font_scale)))


def set_scale(ui=None, font=None):
    global ui_scale, font_scale
    if ui is not None:
        ui_scale = min(max(float(ui), 0.5), 3.0)
    if font is not None:
        font_scale = min(max(float(font), 0.5), 2.5)


def qss():
    p = px
    icon = p(16)
    return f"""
QMainWindow::separator {{ background: {C['border']}; width: {p(3)}px; height: {p(3)}px; }}
QDockWidget::title {{ background: {C['header']}; padding: {p(4)}px {p(6)}px; }}
QToolButton, QPushButton {{ background: {C['button']}; border: 1px solid {C['border']};
    border-radius: {p(4)}px; padding: {p(3)}px {p(8)}px; }}
QToolButton:checked, QPushButton:checked {{ background: {C['highlight']}; }}
{hover_qss()}QAbstractButton {{ qproperty-iconSize: {icon}px {icon}px; }}
QAbstractSpinBox, QLineEdit, QComboBox {{ background: #545454; border: 1px solid {C['border']};
    border-radius: {p(4)}px; padding: {p(2)}px {p(4)}px; min-height: {p(18)}px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0px; border: none; }}
QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow {{ width: 0px; height: 0px; }}
QAbstractSpinBox:focus, QLineEdit:focus {{ background: #222; }}
QComboBox QAbstractItemView {{ background: {C['alt']}; selection-background-color: {C['highlight']}; }}
QCheckBox::indicator {{ width: {p(13)}px; height: {p(13)}px; }}
QGroupBox {{ border: 1px solid {C['border']}; border-radius: {p(5)}px; margin-top: {p(6)}px; }}
QFrame#qtshell_panel {{ background: #303030; border: 1px solid {C['border']}; border-radius: {p(5)}px; }}
QFrame#qtshell_box {{ background: #2a2a2a; border: 1px solid #202020; border-radius: {p(4)}px; }}
QToolButton#qtshell_panel_header {{ background: transparent; border: none; font-weight: bold;
    text-align: left; padding: {p(3)}px; }}
QToolButton#qtshell_panel_header:hover {{ background: rgba(109, 154, 212, 45); border: none; }}
QTabBar::tab:hover:!selected {{ background: {HOVER['bg']}; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: {C['alt']}; padding: {p(6)}px; border: none; }}
QTabBar::tab:selected {{ background: {C['highlight']}; }}
QTreeWidget, QListWidget, QPlainTextEdit {{ background: {C['alt']}; border: none; }}
QTreeWidget, QListWidget {{ qproperty-iconSize: {icon}px {icon}px; }}
QTreeWidget::item, QListWidget::item {{ min-height: {p(18)}px; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {C['highlight']}; }}
QMenu::item {{ padding: {p(4)}px {p(20)}px {p(4)}px {p(10)}px; }}
QMenu::separator {{ height: 1px; margin: {p(3)}px {p(6)}px; background: {C['border']}; }}
QScrollBar:vertical {{ width: {p(12)}px; }}
QScrollBar:horizontal {{ height: {p(12)}px; }}
QStatusBar {{ background: {C['header']}; color: {C['dim']}; }}
QLabel[dim="true"] {{ color: {C['dim']}; }}
"""


def apply(app):
    global _base_pt
    if _base_pt is None:
        # stored on the QApplication so it survives add-on reloads (the app font is already scaled then)
        stored = app.property("qtshell_base_pt")
        if stored:
            _base_pt = float(stored)
        else:
            _base_pt = app.font().pointSizeF() if app.font().pointSizeF() > 0 else 9.0
            app.setProperty("qtshell_base_pt", _base_pt)
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
    font = app.font()
    font.setPointSizeF(_base_pt * ui_scale * font_scale)
    app.setFont(font)
    app.setStyleSheet(qss())


_icon_cache = {}


def type_icon(kind):
    """Small round icon with a letter (no external images)."""
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

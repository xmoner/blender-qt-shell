"""Dark theme similar to Blender (Fusion + palette)."""
from PySide6 import QtCore, QtGui, QtWidgets

C = {
    "window": "#2b2b2b", "base": "#1d1d1d", "alt": "#262626", "button": "#3a3a3a",
    "text": "#e5e5e5", "dim": "#8c8c8c", "highlight": "#4772b3", "accent": "#ffa033",
    "border": "#151515", "header": "#303030", "viewport": "#3d3d3d",
}

# buttons "light up" light blue under the mouse and when pressed
HOVER = {"bg": "#46658c", "border": "#6d9ad4", "press_bg": "#5b84b8", "press_border": "#9cc3f0",
         "checked_hover": "#5683c4"}


# tooltip colours (Qt Preferences → Tooltips; QSettings tooltips/color_<key>; since 0.128.0)
TOOLTIP_COLORS = [
    ("background", "Background", "#2b2b2b", "Background of every tooltip"),
    ("text", "Text", "#e5e5e5", "Text of every tooltip (the description)"),
    ("title", "Title", "#ffffff", "Bold title of the Python tooltips"),
    ("python", "Python heading", "#7fd1a8", "The word 'Python' above the code"),
    ("code", "Code", "#e5e5e5", "The Python code"),
    ("code_bg", "Code background", "#1e1e1e", "Background of the code block"),
    ("code_border", "Code border", "#3a3a3a", "Frame of the code block"),
    ("comment", "Comment", "#8a8a8a", "Comments in the code (# possible values …)"),
    ("values", "Values line", "#b9b9b9", "Type · range · current value under the code"),
    ("hint", "Hint", "#8a8a8a", "'Shift + middle click: copy the code'"),
]


def tooltip_style():
    """{'background': '#rrggbb', 'text': …, 'title': …, 'python': …, 'code': …, 'code_bg': …, 'code_border': …,
    'comment': …, 'values': …, 'hint': …} – the tooltip colours."""
    st = QtCore.QSettings("QtShell", "QtShell")
    out = {}
    for key, _label, default, _tip in TOOLTIP_COLORS:
        c = str(st.value(f"tooltips/color_{key}", default))
        out[key] = c if QtGui.QColor(c).isValid() else default
    return out


def set_tooltip_style(**colors):
    """Sets tooltip colours by key (see TOOLTIP_COLORS), e.g. set_tooltip_style(background='#202830',
    code='#ffd27f'); None keeps a colour. Applies at once to every tooltip shown after it."""
    keys = {k for k, _l, _d, _t in TOOLTIP_COLORS}
    st = QtCore.QSettings("QtShell", "QtShell")
    for key, c in colors.items():
        if key not in keys:
            raise ValueError(f"unknown tooltip colour {key!r} – one of {sorted(keys)}")
        if c is None:
            continue
        q = QtGui.QColor(c)
        if not q.isValid():
            raise ValueError(f"not a colour: {c!r}")
        st.setValue(f"tooltips/color_{key}", q.name())
    apply_tooltip_palette()


def reset_tooltip_style():
    """All tooltip colours back to the defaults."""
    st = QtCore.QSettings("QtShell", "QtShell")
    for key, _l, _d, _t in TOOLTIP_COLORS:
        st.remove(f"tooltips/color_{key}")
    apply_tooltip_palette()


def apply_tooltip_palette():
    """QToolTip keeps its own palette (Windows: light yellow) – background / text from tooltip_style()."""
    ts = tooltip_style()
    app = QtWidgets.QApplication.instance()
    tip = QtGui.QPalette(app.palette() if app is not None else QtGui.QPalette())
    for role, key in ((QtGui.QPalette.Window, "background"), (QtGui.QPalette.ToolTipBase, "background"),
                      (QtGui.QPalette.WindowText, "text"), (QtGui.QPalette.ToolTipText, "text"),
                      (QtGui.QPalette.Text, "text")):
        tip.setColor(role, QtGui.QColor(ts[key]))
    QtWidgets.QToolTip.setPalette(tip)


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


def checked_qss(sel="QToolButton, QPushButton"):
    """Checked buttons in blue – add it to widget style sheets that set a background for all widgets
    (e.g. "QWidget { background: … }" of a header), otherwise checked buttons there would not light up."""
    chk = ", ".join(f"{s.strip()}:checked" for s in sel.split(","))
    return f"{chk} {{ background: {C['highlight']}; }}\n"


def field_hover_qss():
    """Hover for fields (numbers, text, drop-downs): light blue frame, slightly lighter background."""
    h = HOVER
    return (f"QAbstractSpinBox:hover, QLineEdit:hover, QComboBox:hover {{ background: #5b6470; "
            f"border: 1px solid {h['border']}; }}\n")


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
{field_hover_qss()}QAbstractSpinBox:focus, QLineEdit:focus {{ background: #222; border: 1px solid {HOVER['border']}; }}
QComboBox QAbstractItemView {{ background: {C['alt']}; selection-background-color: {C['highlight']}; }}
QCheckBox::indicator {{ width: {p(13)}px; height: {p(13)}px; }}
QGroupBox {{ border: 1px solid {C['border']}; border-radius: {p(5)}px; margin-top: {p(6)}px; }}
QFrame#qtshell_panel {{ background: #303030; border: 1px solid {C['border']}; border-radius: {p(5)}px; }}
QFrame#qtshell_box {{ background: #2a2a2a; border: 1px solid #202020; border-radius: {p(4)}px; }}
QToolButton#qtshell_panel_header {{ background: transparent; border: none; font-weight: bold;
    text-align: left; padding: {p(3)}px; }}
QToolButton#qtshell_panel_header:hover {{ background: rgba(109, 154, 212, 70); border: none; }}
QCheckBox:hover, QRadioButton:hover {{ background: rgba(109, 154, 212, 55); border-radius: {p(3)}px; }}
QMenuBar::item {{ padding: {p(3)}px {p(8)}px; background: transparent; border-radius: {p(3)}px; }}
QMenuBar::item:selected {{ background: {HOVER['bg']}; }}
QMenuBar::item:pressed {{ background: {HOVER['press_bg']}; }}
QMenu {{ background: {C['alt']}; border: 1px solid {C['border']}; }}
QMenu::item {{ border: 1px solid transparent; border-radius: {p(3)}px; margin: 0px {p(2)}px; }}
QMenu::item:selected {{ background: {HOVER['bg']}; border: 1px solid {HOVER['border']}; color: #ffffff; }}
QMenu::item:disabled {{ color: {C['dim']}; }}
QMenu::item:disabled:selected {{ background: transparent; border: 1px solid transparent; }}
QTreeView::item:hover:!selected, QListView::item:hover:!selected {{ background: rgba(109, 154, 212, 60); }}
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
    pal.setColor(QtGui.QPalette.ToolTipBase, col(C["window"]))
    pal.setColor(QtGui.QPalette.ToolTipText, col(C["text"]))
    pal.setColor(QtGui.QPalette.PlaceholderText, col(C["dim"]))
    for role in (QtGui.QPalette.WindowText, QtGui.QPalette.Text, QtGui.QPalette.ButtonText):
        pal.setColor(QtGui.QPalette.Disabled, role, col("#6a6a6a"))
    app.setPalette(pal)
    apply_tooltip_palette()                  # tooltips keep their own palette – colours from Qt Preferences
    font = app.font()
    font.setPointSizeF(_base_pt * ui_scale * font_scale)
    app.setFont(font)
    app.setStyleSheet(qss())
    _dock_title_fonts(font)          # after the style sheet: re-polishing would put the old widget fonts back


def _dock_title_fonts(font):
    """Dock titles (Console, Graph editor, Outliner …) follow the text size too.

    QDockWidget draws its title with a font taken once, when the dock is created, from
    QApplication.font("QDockWidgetTitle") (the system's fixed title font) – unless the dock's own font differs
    from the class font. So: the class font for new docks, and for the existing ones an explicit font that is
    marked (style strategy) so it never compares equal and the dock paints its title with it."""
    QtWidgets.QApplication.setFont(font, "QDockWidgetTitle")
    marked = QtGui.QFont(font)
    marked.setStyleStrategy(QtGui.QFont.PreferAntialias)
    for w in QtWidgets.QApplication.allWidgets():
        if isinstance(w, QtWidgets.QDockWidget):
            w.setFont(marked)
            if w.layout() is not None:
                w.layout().invalidate()          # the title bar height follows the font
            w.updateGeometry()
            w.update()


_icon_cache = {}


def type_icon(kind):
    """Small round icon with a letter (no external images)."""
    if kind in _icon_cache:
        return _icon_cache[kind]
    try:
        from . import blicons
        name = {"COLLECTION": "OUTLINER_COLLECTION", "SCENE": "SCENE_DATA",
                "LIGHT_PROBE": "OUTLINER_OB_LIGHTPROBE"}.get(kind, f"OUTLINER_OB_{kind}")
        if blicons.has(name):
            _icon_cache[kind] = blicons.icon(name)
            return _icon_cache[kind]
    except Exception:
        pass
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

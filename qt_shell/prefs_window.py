"""Edit → Qt Preferences…: the settings of Qt Shell in one window (Blender's own settings stay in
Edit → Preferences…). Categories on the left like Blender's Preferences; every change applies right away.

Settings live in two places: the add-on preferences (saved with Blender's preferences) and QSettings
("QtShell", "QtShell") for the Qt-only ones (tool, toolbar, layout, auto-complete).
"""
import os
import sys
import tempfile

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import api, gizmo, scripts, theme
from . import app as shell_app


def _safe(fn):
    """Slot for a signal of a longer-living object: does nothing once the dialog's widgets are gone."""
    def run(*args):
        try:
            fn(*args)
        except RuntimeError:
            pass
    return run


def _section(parent_lay, title, parent):
    lab = QtWidgets.QLabel(title, parent)
    f = lab.font()
    f.setBold(True)
    lab.setFont(f)
    parent_lay.addWidget(lab)


def _hint(parent_lay, text, parent):
    lab = QtWidgets.QLabel(text, parent)
    lab.setWordWrap(True)
    lab.setProperty("dim", True)
    parent_lay.addWidget(lab)
    return lab


class QtPreferences(QtWidgets.QDialog):
    PAGES = ("Interface", "Window", "Viewport", "Text Editor", "Scripts", "System")

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Qt Preferences")
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.resize(theme.px(720), theme.px(500))
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.nav = QtWidgets.QListWidget(self)
        self.nav.setFixedWidth(theme.px(140))
        self.nav.setStyleSheet("QListWidget{background:#232323;} "
                               f"QListWidget::item{{padding:{theme.px(6)}px {theme.px(8)}px;}}")
        self.stack = QtWidgets.QStackedWidget(self)
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        self._builders = {"Interface": self._page_interface, "Window": self._page_window,
                          "Viewport": self._page_viewport, "Text Editor": self._page_text,
                          "Scripts": self._page_scripts, "System": self._page_system}
        for name in self.PAGES:
            self.nav.addItem(name)
            page = QtWidgets.QWidget(self.stack)
            pl = QtWidgets.QVBoxLayout(page)
            m = theme.px(14)
            pl.setContentsMargins(m, m, m, m)
            pl.setSpacing(theme.px(8))
            self._builders[name](page, pl)
            pl.addStretch(1)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

    # --- helpers
    @staticmethod
    def _prefs():
        return shell_app.prefs()

    def _check(self, page, lay, text, value, on_toggle, tip=None):
        c = QtWidgets.QCheckBox(text, page)
        c.setChecked(bool(value))
        if tip:
            c.setToolTip(tip)
        c.toggled.connect(on_toggle)
        lay.addWidget(c)
        return c

    def _set_pref(self, name, value):
        p = self._prefs()
        if p is not None:
            setattr(p, name, value)

    # --- pages
    def _page_interface(self, page, lay):
        _section(lay, "Interface size", page)
        p = self._prefs()
        ui = getattr(p, "ui_scale", theme.ui_scale)
        font = getattr(p, "font_scale", theme.font_scale)
        self.size_label = QtWidgets.QLabel(page)
        self.size_label.setText(f"Interface scale: {ui * 100:.0f} %    Text size: {font * 100:.0f} %")
        lay.addWidget(self.size_label)
        b = QtWidgets.QPushButton("Interface Size…", page)
        b.setToolTip("Scale of buttons, fields, icons and text – with a live preview")
        b.clicked.connect(self._interface_size)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        _hint(lay, "Also in Window → Interface Size… and in the add-on preferences. Applying a new size "
                   "rebuilds the Qt window.", page)

    def _interface_size(self):
        self.close()                          # the window is rebuilt after a size change
        QtCore.QTimer.singleShot(0, self.win._interface_size)

    def _page_window(self, page, lay):
        _section(lay, "Startup", page)
        p = self._prefs()
        self._check(page, lay, "Start Qt Shell when Blender starts", getattr(p, "auto_start", False),
                    lambda on: self._set_pref("auto_start", on))
        _section(lay, "Blender window", page)
        self._check(page, lay, "Hide the Blender window while Qt Shell is running",
                    getattr(p, "hide_blender", True), lambda on: self._set_pref("hide_blender", on))
        act = getattr(self.win, "blender_visible_act", None)
        if act is not None:
            c = self._check(page, lay, "Show the Blender window now", act.isChecked(), act.setChecked)
            act.toggled.connect(_safe(lambda on, c=c: c.isChecked() != on and c.setChecked(on)))
        bar = getattr(self.win, "docks", {}).get("shelf")
        if bar is not None:
            _section(lay, "Shelf", page)
            sc = self._check(page, lay, "Show the Shelf (script buttons; double-click its title to float it)",
                             not bar.isHidden(),
                             bar.setVisible)
            bar.visibilityChanged.connect(_safe(lambda on, c=sc: c.isChecked() != on and c.setChecked(on)))
        _section(lay, "Window layout", page)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Reset Window Layout", page)
        b.setToolTip("Puts all panels back to their default places and forgets the saved layout")
        b.clicked.connect(self._reset_layout)
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        _hint(lay, "Floating windows are docked again when Qt Shell closes – double-click a panel title "
                   "to float it.", page)

    def _reset_layout(self):
        try:
            s = QtCore.QSettings("QtShell", "QtShell")
            s.remove("state")
            s.remove("geometry")
            self.win._reset_layout()
            api.status("Window layout reset")
        except Exception as ex:
            api.status(f"Reset failed: {ex}")

    def _page_viewport(self, page, lay):
        _section(lay, "Rendering", page)
        p = self._prefs()
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Viewport resolution", page))
        sp = QtWidgets.QDoubleSpinBox(page)
        sp.setRange(25, 200)
        sp.setSingleStep(25)
        sp.setDecimals(0)
        sp.setSuffix(" %")
        sp.setValue(getattr(p, "viewport_scale", 1.0) * 100)
        sp.setToolTip("Lower = faster viewport, higher = sharper")
        sp.valueChanged.connect(self._viewport_scale)
        row.addWidget(sp)
        row.addStretch(1)
        lay.addLayout(row)

        _section(lay, "Layout", page)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("3D views", page))
        combo = QtWidgets.QComboBox(page)
        area = getattr(self.win, "viewports", None)
        from .viewport import ViewportArea
        for key, label in ViewportArea.LAYOUTS.items():
            combo.addItem(label, key)
        if area is not None:
            combo.setCurrentIndex(max(0, combo.findData(area.mode)))
        combo.activated.connect(lambda _i: api.set_viewport_layout(combo.currentData()))
        row.addWidget(combo)
        row.addStretch(1)
        lay.addLayout(row)

        _section(lay, "Tools", page)
        st = gizmo.tool_state(self.win.hub)
        c = self._check(page, lay, "Show the toolbar (T)", st.toolbar_visible,
                        lambda on: on != st.toolbar_visible and st.toggle_toolbar())
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Active tool", page))
        tools = QtWidgets.QComboBox(page)
        for tool, glyph, _tip, key in gizmo.TOOLS:
            tools.addItem(f"{glyph}  {gizmo.TOOL_NAMES[tool]}   ({key})", tool)
        tools.setCurrentIndex(max(0, tools.findData(st.tool)))
        tools.activated.connect(lambda _i: st.set_tool(tools.currentData()))
        row.addWidget(tools)
        row.addStretch(1)
        lay.addLayout(row)

        def sync():
            c.blockSignals(True)
            c.setChecked(st.toolbar_visible)
            c.blockSignals(False)
            tools.setCurrentIndex(max(0, tools.findData(st.tool)))
        st.changed.connect(_safe(sync))
        _hint(lay, "Shift+Space over a 3D view opens the tool menu (W Select, G Move, R Rotate, S Scale, "
                   "T Transform).", page)

    def _viewport_scale(self, percent):
        self._set_pref("viewport_scale", percent / 100.0)
        area = getattr(self.win, "viewports", None)
        if area is not None:
            for v in area.views:
                v.prefs = self._prefs()
            area.request_redraw()

    def _page_text(self, page, lay):
        _section(lay, "Text editor", page)
        ed = getattr(self.win, "text_editor", None)
        on = ed.editor.auto_complete if ed is not None else True
        c = self._check(page, lay, "Auto-complete (suggest names after \".\" and while typing)", on,
                        self._auto_complete)
        if ed is not None:
            ed.ac_check.toggled.connect(_safe(lambda v, c=c: c.isChecked() != v and c.setChecked(v)))
        _hint(lay, "Ctrl+Space shows the suggestions any time, also when this is off.", page)

    def _auto_complete(self, on):
        ed = getattr(self.win, "text_editor", None)
        if ed is not None:
            ed.ac_check.setChecked(on)        # also saves the setting
        else:
            QtCore.QSettings("QtShell", "QtShell").setValue("text_editor/autocomplete",
                                                            "true" if on else "false")

    def _page_scripts(self, page, lay):
        _section(lay, "Run on startup", page)
        _hint(lay, "Python files in this list run when Qt Shell starts (once per Blender session) "
                   "when they are ticked.", page)
        self.files = QtWidgets.QListWidget(page)
        self.files.setMinimumHeight(theme.px(160))
        self.files.itemChanged.connect(self._file_toggled)
        lay.addWidget(self.files)
        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("Add File…", page)
        add.clicked.connect(self._add_file)
        rem = QtWidgets.QPushButton("Remove", page)
        rem.setToolTip("Remove from the list (unloads the script; the file itself is kept)")
        rem.clicked.connect(self._remove_file)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        lay.addLayout(row)
        self._fill_files()
        _section(lay, "Scripts in the .blend file", page)
        _hint(lay, "A text runs when its .blend is opened when it has the custom property "
                   "qtshell_autoload (Text editor → Console: bpy.data.texts[\"Text\"][\"qtshell_autoload\"] "
                   "= True). Needs Preferences ▸ Save & Load ▸ Auto Run Python Scripts.", page)

    def _fill_files(self):
        self.files.blockSignals(True)
        self.files.clear()
        for key, auto in scripts.managed_files():
            it = QtWidgets.QListWidgetItem(key[5:])
            it.setData(QtCore.Qt.UserRole, key)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if auto else QtCore.Qt.Unchecked)
            info = scripts.info(key)
            it.setToolTip("loaded" if info and info["status"] == "loaded" else
                          (info["status"] if info else "not run in this session"))
            self.files.addItem(it)
        if not self.files.count():
            it = QtWidgets.QListWidgetItem("(no files – click Add File…)")
            it.setFlags(QtCore.Qt.NoItemFlags)
            self.files.addItem(it)
        self.files.blockSignals(False)

    def _file_toggled(self, it):
        key = it.data(QtCore.Qt.UserRole)
        if key:
            scripts.set_autoload(key, it.checkState() == QtCore.Qt.Checked)

    def _add_file(self):
        start = os.path.dirname(bpy.data.filepath) or os.path.expanduser("~")
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Add Startup Scripts", start, "Python (*.py)")
        for p in paths:
            scripts.set_autoload(scripts.add_file(p), True)
        self._fill_files()

    def _remove_file(self):
        it = self.files.currentItem()
        key = it.data(QtCore.Qt.UserRole) if it is not None else None
        if not key:
            return
        if scripts.is_loaded(key):
            scripts.unload(key)
        scripts.remove_file(key)
        self._fill_files()

    def _page_system(self, page, lay):
        _section(lay, "Versions", page)
        try:
            import PySide6
            pyside = PySide6.__version__
            qt = QtCore.qVersion()
        except Exception:
            pyside = qt = "?"
        pkg = sys.modules.get(__package__)
        ver = ".".join(str(v) for v in getattr(pkg, "bl_info", {}).get("version", ()))
        for line in (f"Qt Shell {ver}   ·   Python API {'.'.join(map(str, api.API_VERSION))}",
                     f"Blender {bpy.app.version_string}",
                     f"PySide6 {pyside}   ·   Qt {qt}   ·   Python {sys.version.split()[0]}"):
            lab = QtWidgets.QLabel(line, page)
            lab.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            lay.addWidget(lab)
        _section(lay, "Logs", page)
        folder = tempfile.gettempdir()
        lab = QtWidgets.QLabel(f"{os.path.join(folder, 'qtshell.log')}\n{os.path.join(folder, 'qtshell_crash.log')}",
                               page)
        lab.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lay.addWidget(lab)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Open Log Folder", page)
        b.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder)))
        row.addWidget(b)
        h = QtWidgets.QPushButton("Status History…", page)
        h.clicked.connect(self.win.show_status_history)
        row.addWidget(h)
        row.addStretch(1)
        lay.addLayout(row)
        _section(lay, "Documentation", page)
        row = QtWidgets.QHBoxLayout()
        for text, url in (("Python API", "https://github.com/xmoner/blender-qt-shell/blob/main/docs/API.md"),
                          ("GitHub", "https://github.com/xmoner/blender-qt-shell")):
            d = QtWidgets.QPushButton(text, page)
            d.clicked.connect(lambda _c=False, u=url: QtGui.QDesktopServices.openUrl(QtCore.QUrl(u)))
            row.addWidget(d)
        row.addStretch(1)
        lay.addLayout(row)


def show(win):
    dlg = getattr(win, "_qt_prefs", None)
    try:
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return dlg
    except RuntimeError:            # closed (deleted on close)
        pass
    dlg = win._qt_prefs = QtPreferences(win)
    dlg.show()
    return dlg

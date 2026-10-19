"""Scripts dock – the script manager UI (like Maya's Plug-in Manager).

Lists the texts of the .blend and the script files added to the list, shows which are loaded and
what they registered, and runs / reloads / unloads them. The Auto-load checkbox runs a text when the
.blend is opened, or a file when Qt Shell starts.
"""
import os

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import scripts, theme

COL_NAME, COL_STATUS, COL_AUTO, COL_WHERE = range(4)


class ScriptsPanel(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)

        # every widget gets its parent when it is created: widgets added to a layout that is not yet
        # installed on a widget can be freed by Python, which crashes Qt when the window is shown
        barw = QtWidgets.QWidget(self)
        bar = QtWidgets.QHBoxLayout(barw)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(3)
        lay.addWidget(barw)

        def tool(text, tip, fn):
            b = QtWidgets.QToolButton(barw)
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
            return b

        self.run_btn = tool("▶ Run", "Run the script; a loaded script is unloaded first (= Reload)", self.run)
        self.run_btn.setStyleSheet(
            "QToolButton{background:#3d6b3d;} "
            "QToolButton:hover{background:#4f8f4f; border:1px solid #8fd08f;} "
            "QToolButton:pressed{background:#62a862; border:1px solid #b0e8b0;}")
        self.unload_btn = tool("■ Unload", "Call unregister() and remove everything the script registered",
                               self.unload)
        self.edit_btn = tool("Edit", "Open in the Text editor (double-click)", self.edit)
        self.add_btn = tool("Add File…", "Add a .py file to the list (it stays there for every .blend)",
                            self.add_file)
        self.remove_btn = tool("Remove", "Remove the file from the list (the file itself is kept)",
                               self.remove_file)
        bar.addStretch(1)
        self.unload_all_btn = tool("Unload All", "Unload every loaded script", self.unload_all)

        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setHeaderLabels(["Script", "Status", "Auto-load", "Location"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        h = self.tree.header()
        h.setStretchLastSection(True)
        self.tree.setColumnWidth(COL_NAME, theme.px(180))
        self.tree.setColumnWidth(COL_STATUS, theme.px(140))
        self.tree.setColumnWidth(COL_AUTO, theme.px(75))
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit())
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        lay.addWidget(self.tree, 3)

        self.details = QtWidgets.QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(theme.px(110))
        self.details.setPlaceholderText("What the selected script has registered.")
        lay.addWidget(self.details, 1)

        self.note = QtWidgets.QLabel(self)
        self.note.setProperty("dim", True)
        lay.addWidget(self.note)

        self._sig = None
        self._filling = False
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self.refresh()

    # --- list
    def _signature(self):
        return (scripts.version(), tuple((t.name, t.filepath, bool(t.get(scripts.TEXT_PROP)))
                                         for t in bpy.data.texts))

    def _poll(self):
        if not self.isVisible():
            return
        try:
            sig = self._signature()
        except Exception:
            return
        if sig != self._sig:
            self.refresh()

    def _current_key(self):
        it = self.tree.currentItem()
        return it.data(COL_NAME, QtCore.Qt.UserRole) if it is not None else None

    def refresh(self):
        self._sig = self._signature()
        cur = self._current_key()
        self._filling = True
        self.tree.clear()
        green, red, grey = QtGui.QColor("#7fcf7f"), QtGui.QColor("#ff7070"), QtGui.QColor("#9a9a9a")
        blocked = set(scripts.blocked())
        select = None
        for key in scripts.all_keys():
            it = QtWidgets.QTreeWidgetItem()
            it.setData(COL_NAME, QtCore.Qt.UserRole, key)
            it.setText(COL_NAME, scripts.label(key))
            it.setText(COL_WHERE, scripts.location(key))
            it.setToolTip(COL_WHERE, scripts.location(key))
            i = scripts.info(key)
            if i is None:
                status, color = ("auto-load blocked", QtGui.QColor("#e0b050")) if key in blocked else ("", grey)
            elif i["status"] == "loaded":
                status, color = f"● loaded · {i['items']} item{'s' if i['items'] != 1 else ''}", green
            elif i["status"] == "error":
                status, color = "● error", red
            else:
                status, color = "ran", grey
            it.setText(COL_STATUS, status)
            it.setForeground(COL_STATUS, color)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(COL_AUTO, QtCore.Qt.Checked if scripts.autoload(key) else QtCore.Qt.Unchecked)
            it.setToolTip(COL_AUTO, "Run when Qt Shell starts" if key.startswith("file:")
                          else "Run when this .blend is opened (needs Auto Run Python Scripts)")
            self.tree.addTopLevelItem(it)
            if key == cur:
                select = it
        self._filling = False
        if select is None and self.tree.topLevelItemCount():
            select = self.tree.topLevelItem(0)
        if select is not None:
            self.tree.setCurrentItem(select)
        self._selection_changed()
        n = sum(1 for k in scripts.all_keys() if (scripts.info(k) or {}).get("status") == "loaded")
        self.note.setText(f"{n} script{'s' if n != 1 else ''} loaded." + (
            "  Auto-load of scripts in this file was blocked – enable Preferences ▸ Save & Load ▸ "
            "Auto Run Python Scripts, or run them here." if blocked else ""))

    def _selection_changed(self):
        key = self._current_key()
        i = scripts.info(key) if key else None
        self.unload_btn.setEnabled(i is not None)
        self.run_btn.setEnabled(key is not None)
        self.edit_btn.setEnabled(key is not None)
        self.run_btn.setText("⟳ Reload" if i is not None and i["status"] == "loaded" else "▶ Run")
        self.remove_btn.setEnabled(bool(key) and scripts.is_managed(key))
        if key is None:
            self.details.setPlainText("")
            return
        lines = []
        if i is not None:
            lines += scripts.items(key)
            if i["has_unregister"]:
                lines.append("unregister() – called on Unload")
            if not lines:
                lines.append("The script ran and registered nothing.")
        else:
            lines.append("Not loaded.")
        self.details.setPlainText("\n".join(lines))

    def _item_changed(self, it, col):
        if self._filling or col != COL_AUTO:
            return
        key = it.data(COL_NAME, QtCore.Qt.UserRole)
        scripts.set_autoload(key, it.checkState(COL_AUTO) == QtCore.Qt.Checked)

    def _context_menu(self, pos):
        it = self.tree.itemAt(pos)
        if it is None:
            return
        self.tree.setCurrentItem(it)
        m = QtWidgets.QMenu(self)
        m.addAction(self.run_btn.text(), self.run)
        a = m.addAction("■ Unload", self.unload)
        a.setEnabled(self.unload_btn.isEnabled())
        m.addAction("Edit", self.edit)
        if self.remove_btn.isEnabled():
            m.addSeparator()
            m.addAction("Remove from the list", self.remove_file)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    # --- actions
    def _editor(self):
        mw = getattr(self.hub, "main_window", None)
        return getattr(mw, "text_editor", None), mw

    def run(self):
        key = self._current_key()
        if not key:
            return
        ed, _ = self._editor()
        if ed is not None:
            ed._write_back()           # run what is typed in the editor
        was = scripts.is_loaded(key)
        scripts.show_console()
        r = scripts.run(key)
        title = f"{'⟳ Reload' if was else '▶ Run'}: {scripts.label(key)}"
        if r.removed:
            title += f"  (removed {r.removed} item{'s' if r.removed != 1 else ''} of the previous run)"
        scripts.report_result(title, r)
        self._status(f"{scripts.label(key)}: " + ("done" if r.ok else "error – see the Console"))
        self.refresh()

    def unload(self):
        key = self._current_key()
        if not key or not scripts.is_loaded(key):
            return
        r = scripts.unload(key)
        scripts.report_result(f"■ Unload: {scripts.label(key)}  (removed {r.removed} item"
                              f"{'s' if r.removed != 1 else ''})", r)
        self._status(f"Unloaded {scripts.label(key)}")
        self.refresh()

    def unload_all(self):
        n = 0
        for key in scripts.all_keys():
            if scripts.is_loaded(key):
                r = scripts.unload(key)
                n += 1
                if r.output:
                    scripts.report_result(f"■ Unload: {scripts.label(key)}", r)
        self._status(f"Unloaded {n} script{'s' if n != 1 else ''}")
        self.refresh()

    def edit(self):
        key = self._current_key()
        if not key:
            return
        ed, mw = self._editor()
        if ed is None:
            return
        t = scripts.text_for_key(key)
        if t is None and key.startswith("file:"):
            try:
                t = bpy.data.texts.load(key[5:])
            except Exception as ex:
                QtWidgets.QMessageBox.warning(self, "Edit Script", str(ex))
                return
        if t is None:
            return
        ed.show_text(t.name)
        d = mw.docks.get("text_editor")
        if d is not None:
            d.show()
            d.raise_()
        ed.editor.setFocus()

    def add_file(self):
        start = os.path.dirname(bpy.data.filepath) or os.path.expanduser("~")
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Add Scripts", start, "Python (*.py)")
        key = None
        for p in paths:
            key = scripts.add_file(p)
        self.refresh()
        if key:
            for idx in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(idx)
                if it.data(COL_NAME, QtCore.Qt.UserRole) == key:
                    self.tree.setCurrentItem(it)

    def remove_file(self):
        key = self._current_key()
        if not key or not scripts.is_managed(key):
            return
        if scripts.is_loaded(key):
            scripts.report_result(f"■ Unload: {scripts.label(key)}", scripts.unload(key))
        scripts.remove_file(key)
        self.refresh()

    def _status(self, msg):
        mw = getattr(self.hub, "main_window", None)
        if mw is not None:
            mw.statusBar().showMessage(msg, 5000)

"""Edit → Keyboard Shortcuts…: every Qt Shell shortcut in one window, searchable and editable.

Double-click (or Change…) records a new key, Add Alternative… adds a second key, Clear removes the keys,
Reset restores the default. Conflicts in the same area are shown with ⚠. Tooltips and menu hints follow
the changes immediately (keymap templates). The mouse navigation scheme (Blender / Maya) is chosen here too.
"""
from PySide6 import QtCore, QtGui, QtWidgets

from . import keymap, theme

AID = QtCore.Qt.UserRole


class KeyCapture(QtWidgets.QDialog):
    """Small dialog that records one key combination. Esc cancels, Backspace alone clears."""

    def __init__(self, parent, label):
        super().__init__(parent)
        self.setWindowTitle("Press a Shortcut")
        self.key = None
        lay = QtWidgets.QVBoxLayout(self)
        t = QtWidgets.QLabel(f"<b>{label}</b><br>Press the new key combination…<br>"
                             "<span style='color:#999'>Esc = cancel · numpad keys are kept apart "
                             "from the number row</span>", self)
        t.setTextFormat(QtCore.Qt.RichText)
        lay.addWidget(t)
        self.shown = QtWidgets.QLabel("", self)
        f = self.shown.font()
        f.setPointSizeF(f.pointSizeF() * 1.6)
        f.setBold(True)
        self.shown.setFont(f)
        self.shown.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self.shown)
        self.setMinimumWidth(theme.px(320))

    def event(self, ev):
        if ev.type() == QtCore.QEvent.ShortcutOverride:
            ev.accept()                          # no window shortcut may fire while recording
            return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        if ev.key() == QtCore.Qt.Key_Escape and not ev.modifiers():
            self.reject()
            return
        k = keymap.event_to_key(ev)
        if not k:
            return                               # a modifier alone – wait for the key
        self.key = k
        self.shown.setText(keymap.display(k))
        QtCore.QTimer.singleShot(250, self.accept)


class ShortcutsPanel(QtWidgets.QWidget):
    """The shortcut list and editor – used in the Keyboard Shortcuts window and in Qt Preferences.

    The 3D View areas have two key sets, Blender and Maya. "Use" switches the active controls (mouse
    navigation + 3D View keys); "Edit set" chooses which set the list shows and edits (both can be edited
    at any time). Window and editor shortcuts are shared by both sets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Use controls:", self))
        self.use = QtWidgets.QComboBox(self)
        for key, name in keymap.PROFILES.items():
            self.use.addItem(name, key)
        self.use.setToolTip("Active 3D View controls: mouse navigation and the 3D View key set "
                            "(also Qt Preferences → Interface → Navigation & Shortcuts)")
        self.use.currentIndexChanged.connect(self._use_changed)
        top.addWidget(self.use)
        top.addSpacing(16)
        top.addWidget(QtWidgets.QLabel("Edit 3D View keys of:", self))
        self.edit_set = QtWidgets.QComboBox(self)
        for key, name in keymap.PROFILES.items():
            self.edit_set.addItem(name, key)
        self.edit_set.setToolTip("Which 3D View key set the list shows and changes – the Blender and the Maya "
                                 "set are kept separately")
        self.edit_set.currentIndexChanged.connect(lambda _i: self._rebuild())
        top.addWidget(self.edit_set)
        top.addStretch(1)
        lay.addLayout(top)

        self.search = QtWidgets.QLineEdit(self)
        self.search.setPlaceholderText("Search by name or key (e.g. \"frame\" or \"Ctrl+S\")…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)

        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Action", "Shortcut", ""])
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        self.tree.setColumnWidth(2, theme.px(28))
        self.tree.setUniformRowHeights(True)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._change(it))
        self.tree.currentItemChanged.connect(lambda *_a: self._update_buttons())
        lay.addWidget(self.tree, 1)

        self.buttons = row = QtWidgets.QHBoxLayout()
        self.b_change = QtWidgets.QPushButton("Change…", self)
        self.b_change.setToolTip("Record a new key for the action (replaces its keys) – or double-click the row")
        self.b_change.clicked.connect(lambda: self._change(self.tree.currentItem()))
        self.b_add = QtWidgets.QPushButton("Add Alternative…", self)
        self.b_add.setToolTip("Record an additional key – the action then has several")
        self.b_add.clicked.connect(lambda: self._change(self.tree.currentItem(), add=True))
        self.b_clear = QtWidgets.QPushButton("Clear", self)
        self.b_clear.setToolTip("Remove all keys of the action")
        self.b_clear.clicked.connect(self._clear)
        self.b_reset = QtWidgets.QPushButton("Reset", self)
        self.b_reset.setToolTip("Default keys of the action (in the edited set)")
        self.b_reset.clicked.connect(self._reset)
        for b in (self.b_change, self.b_add, self.b_clear, self.b_reset):
            row.addWidget(b)
        row.addStretch(1)
        b_all = QtWidgets.QPushButton("Reset All…", self)
        b_all.setToolTip("Defaults for all shared shortcuts and the edited 3D View set")
        b_all.clicked.connect(self._reset_all)
        row.addWidget(b_all)
        lay.addLayout(row)
        hint = QtWidgets.QLabel("Bold = changed from the default. ⚠ = the key is also used by another action in "
                                "the same area. \"1\" means the number row and the numpad, \"Numpad 1\" only "
                                "the numpad. Tooltips and menus show the new keys right away.", self)
        hint.setWordWrap(True)
        hint.setProperty("dim", True)
        lay.addWidget(hint)
        self._syncing = False
        self._sync_use()
        self.edit_set.setCurrentIndex(self.use.currentIndex())
        keymap.notifier.changed.connect(self._external_change)
        self._rebuild()

    # ------------------------------------------------------------ sets
    def profile(self):
        return self.edit_set.currentData()

    def _sync_use(self):
        self._syncing = True
        self.use.setCurrentIndex(list(keymap.PROFILES).index(keymap.nav_scheme()))
        self._syncing = False

    def _use_changed(self, _i):
        if self._syncing:
            return
        keymap.set_nav_scheme(self.use.currentData())
        self.edit_set.setCurrentIndex(self.use.currentIndex())   # edit what is used

    def _external_change(self):
        try:
            if self.use.currentData() != keymap.nav_scheme():
                self._sync_use()
                self.edit_set.setCurrentIndex(self.use.currentIndex())
            self._rebuild()
        except RuntimeError:                   # panel already deleted
            pass

    # ------------------------------------------------------------ tree
    def _rebuild(self):
        prof = self.profile()
        cur = self.tree.currentItem()
        cur_aid = cur.data(0, AID) if cur is not None else None
        self.tree.clear()
        bold = self.tree.font()
        bold.setBold(True)
        groups = {}
        for ctx in keymap.CONTEXTS:
            title = f"{ctx}   ({keymap.PROFILES[prof]} set)" if ctx in keymap.PROFILED else ctx
            g = QtWidgets.QTreeWidgetItem(self.tree, [title])
            g.setFont(0, bold)
            g.setFlags(g.flags() & ~QtCore.Qt.ItemIsSelectable)
            g.setExpanded(True)
            groups[ctx] = g
        select = None
        for aid, a in keymap.ACTIONS.items():
            it = QtWidgets.QTreeWidgetItem(groups[a["context"]], [a["label"], keymap.text(aid, profile=prof), ""])
            it.setData(0, AID, aid)
            default = ", ".join(keymap.display(k) for k in keymap.default_keys(aid, prof)) or "—"
            it.setToolTip(0, f"{aid}\nDefault: {default}")
            it.setToolTip(1, f"Default: {default}")
            if not keymap.is_default(aid, prof):
                it.setFont(0, bold)
                it.setFont(1, bold)
            clash = set()
            for k in keymap.keys(aid, prof):
                clash.update(keymap.conflicts(aid, k, prof))
            if clash:
                names = ", ".join(f"{keymap.ACTIONS[o]['label']} ({keymap.ACTIONS[o]['context']})"
                                  for o in sorted(clash))
                it.setText(2, "⚠")
                it.setForeground(2, QtGui.QBrush(QtGui.QColor("#e0a040")))
                it.setToolTip(2, "Same key as: " + names)
            if aid == cur_aid:
                select = it
        # mouse navigation of the edited set (read only)
        m = QtWidgets.QTreeWidgetItem(self.tree, [f"Mouse · 3D View   ({keymap.PROFILES[prof]})"])
        m.setFont(0, bold)
        m.setFlags(m.flags() & ~QtCore.Qt.ItemIsSelectable)
        m.setExpanded(True)
        for label, how in keymap.NAV_SCHEMES[prof]:
            it = QtWidgets.QTreeWidgetItem(m, [label, how, ""])
            it.setFlags(it.flags() & ~QtCore.Qt.ItemIsSelectable)
            it.setForeground(1, QtGui.QBrush(QtGui.QColor("#9a9a9a")))
        if select is not None:
            self.tree.setCurrentItem(select)
        self._filter(self.search.text())
        self._update_buttons()

    def _filter(self, text):
        t = text.strip().lower()
        nk = keymap.normalize(text.strip()).lower() if text.strip() else ""
        prof = self.profile()
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            any_shown = False
            for j in range(g.childCount()):
                it = g.child(j)
                aid = it.data(0, AID)
                hay = f"{it.text(0)} {it.text(1)} {aid or ''} {g.text(0)}".lower()
                keys = [k.lower() for k in keymap.keys(aid, prof)] if aid else []
                show = not t or t in hay or (nk and nk in keys)
                it.setHidden(not show)
                any_shown = any_shown or show
            g.setHidden(not any_shown)

    def _update_buttons(self):
        it = self.tree.currentItem()
        ok = it is not None and it.data(0, AID) is not None
        for b in (self.b_change, self.b_add, self.b_clear, self.b_reset):
            b.setEnabled(ok)

    # ------------------------------------------------------------ editing
    def _change(self, it, add=False):
        if it is None or it.data(0, AID) is None:
            return
        aid = it.data(0, AID)
        prof = self.profile()
        dlg = KeyCapture(self, keymap.ACTIONS[aid]["label"])
        if dlg.exec() != QtWidgets.QDialog.Accepted or not dlg.key:
            return
        k = dlg.key
        clash = keymap.conflicts(aid, k, prof)
        if clash:
            names = "\n".join(f"• {keymap.ACTIONS[o]['label']} ({keymap.ACTIONS[o]['context']})" for o in clash)
            box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, "Shortcut in Use",
                                        f"{keymap.display(k)} is already used by:\n{names}", parent=self)
            take = box.addButton("Assign and remove it there", QtWidgets.QMessageBox.AcceptRole)
            both = box.addButton("Assign (keep both)", QtWidgets.QMessageBox.YesRole)
            box.addButton(QtWidgets.QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() not in (take, both):
                return
            if box.clickedButton() is take:
                for o in clash:
                    keymap.set_keys(o, [x for x in keymap.keys(o, prof) if x != keymap.normalize(k)], prof)
        new = list(keymap.keys(aid, prof)) + [k] if add else [k]
        keymap.set_keys(aid, list(dict.fromkeys(new)), prof)
        self._rebuild()

    def _clear(self):
        it = self.tree.currentItem()
        if it is not None and it.data(0, AID):
            keymap.set_keys(it.data(0, AID), [], self.profile())
            self._rebuild()

    def _reset(self):
        it = self.tree.currentItem()
        if it is not None and it.data(0, AID):
            keymap.reset(it.data(0, AID), self.profile())
            self._rebuild()

    def _reset_all(self):
        name = keymap.PROFILES[self.profile()]
        r = QtWidgets.QMessageBox.question(self, "Reset All Shortcuts",
                                           f"Set the shared shortcuts and the {name} 3D View set back to "
                                           "their defaults?")
        if r == QtWidgets.QMessageBox.Yes:
            keymap.reset_all(self.profile())
            self._rebuild()


class ShortcutsWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(theme.px(760), theme.px(660))
        lay = QtWidgets.QVBoxLayout(self)
        self.panel = ShortcutsPanel(self)
        lay.addWidget(self.panel, 1)
        close = QtWidgets.QPushButton("Close", self)
        close.clicked.connect(self.close)
        self.panel.buttons.addWidget(close)


_win = None


def show(parent=None):
    """Opens (or raises) the Keyboard Shortcuts window."""
    global _win
    try:
        if _win is not None and _win.isVisible():
            _win.raise_()
            _win.activateWindow()
            return _win
    except RuntimeError:
        _win = None
    _win = ShortcutsWindow(parent)
    _win.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
    _win.show()
    return _win

"""Help → Search (like Maya's Help search / Find Menu): finds menu items, buttons, tabs and operators of the
whole Qt Shell window by a word and runs the chosen one.

Sources (in this order of the results):
- every menu of the menu bar with all its submenus (Blender menus are generated on the fly – LazyMenu – so they
  are filled first, for the current mode),
- workspace tabs and other tab bars, the Properties editor tabs,
- visible buttons of the window (3D header, toolbar, docks …): their text or the first tooltip line,
- Blender operators (F3 search).

Matching ignores case and doubled letters ("Modelling" finds "Modeling"); all words must match.
"""
import re

from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, theme

MENU, TAB, BUTTON, OPERATOR = "Menu", "Tab", "Button", "Operator"
_MAX_MENUS = 600          # safety: Blender menus are generated recursively
_MAX_RESULTS = 400


def _norm(text):
    """lower case, '&' removed, doubled letters collapsed (modelling = modeling)."""
    return re.sub(r"(.)\1+", r"\1", text.replace("&", "").lower())


class Entry:
    __slots__ = ("name", "where", "kind", "shortcut", "icon", "run", "enabled", "hay", "key")

    def __init__(self, name, where, kind, run, shortcut="", icon=None, enabled=True):
        self.name = name
        self.where = where
        self.kind = kind
        self.run = run
        self.shortcut = shortcut
        self.icon = icon
        self.enabled = enabled
        self.key = _norm(name)
        self.hay = _norm(f"{name} {where}")


def _split_text(text):
    """'Frame Selected\tF' → ('Frame Selected', 'F')."""
    text = text.replace("&&", "\0").replace("&", "").replace("\0", "&")
    name, _sep, sc = text.partition("\t")
    return name.rstrip("…").replace("...", "").strip(), sc.strip()


# ---------------------------------------------------------------- collecting
def _collect_menu(menu, path, out, seen):
    if id(menu) in seen or len(seen) > _MAX_MENUS:
        return
    seen.add(id(menu))
    try:
        menu.aboutToShow.emit()                 # LazyMenu / PopoverMenu fill themselves when shown
    except Exception:
        pass
    for act in menu.actions():
        try:
            if act.isSeparator() or isinstance(act, QtWidgets.QWidgetAction):
                continue
            name, sc = _split_text(act.text())
            sub = act.menu()
            if sub is not None:
                if name:
                    _collect_menu(sub, f"{path} ▸ {name}" if path else name, out, seen)
                continue
            if not name or name in ("—",) or not act.isVisible():
                continue
            if not sc and not act.shortcut().isEmpty():
                sc = act.shortcut().toString(QtGui.QKeySequence.NativeText)
            out.append(Entry(name, path, MENU, act.trigger, sc, act.icon(), act.isEnabled()))
        except RuntimeError:                    # an action deleted while its menu was refilled
            continue


def _dock_of(w):
    while w is not None:
        if isinstance(w, QtWidgets.QDockWidget):
            return w
        w = w.parentWidget()
    return None


def _where(w, window):
    dock = _dock_of(w)
    if dock is not None:
        return dock.windowTitle() or "Panel"
    if window.menuBar().isAncestorOf(w):
        return "Menu bar"
    return "Window"


def _show_dock(w):
    dock = _dock_of(w)
    if dock is not None:
        dock.show()
        dock.raise_()


def collect(window):
    out = []
    seen = set()
    mb = window.menuBar()
    for act in mb.actions():
        m = act.menu()
        if m is None:
            continue
        title, _sc = _split_text(act.text() or m.title())
        _collect_menu(m, title, out, seen)
    # tab bars (workspaces …)
    for bar in window.findChildren(QtWidgets.QTabBar):
        if not bar.isVisible():
            continue
        where = "Workspaces" if mb.isAncestorOf(bar) else f"{_where(bar, window)} tabs"
        for i in range(bar.count()):
            text = bar.tabText(i).replace("&", "")
            if not text:
                continue

            def run(bar=bar, i=i):
                _show_dock(bar)
                bar.tabBarClicked.emit(i)
                bar.setCurrentIndex(i)
            out.append(Entry(text, where, TAB, run, icon=bar.tabIcon(i), enabled=bar.isTabEnabled(i)))
    # tab columns of the Properties editor (QListWidget in a TabColumn)
    for lw in window.findChildren(QtWidgets.QListWidget):
        owner = lw.parentWidget()
        while owner is not None and type(owner).__name__ != "TabColumn":
            owner = owner.parentWidget()
        if owner is None or not lw.isVisible():
            continue
        where = f"{_where(lw, window)} tabs"
        for i in range(lw.count()):
            it = lw.item(i)
            if it.isHidden():
                continue

            def run(lw=lw, i=i):
                _show_dock(lw)
                lw.setCurrentRow(i)
            out.append(Entry(it.text(), where, TAB, run, icon=it.icon()))
    # visible buttons
    names = set()
    for b in window.findChildren(QtWidgets.QAbstractButton):
        try:
            if not b.isVisible() or isinstance(b.parentWidget(), QtWidgets.QTabBar):
                continue
            text, _sc = _split_text(b.text())
            tip = (b.toolTip() or "").strip()
            tip = re.sub(r"<[^>]+>", "", tip.splitlines()[0]) if tip else ""
            name = text if len(text) > 1 else tip      # icon buttons: the tooltip names them
            if not name or len(name) > 80:
                continue
            where = _where(b, window)
            if (name, where) in names:
                continue
            names.add((name, where))
            if text and tip and tip != text and len(tip) < 60:
                where = f"{where} – {tip}"
            out.append(Entry(name, where, BUTTON, b.click, icon=b.icon(), enabled=b.isEnabled()))
        except RuntimeError:
            continue
    # operators (F3)
    try:
        from .main_window import OperatorSearch
        for name, idname in OperatorSearch.items():
            out.append(Entry(name, idname, OPERATOR, lambda i=idname: bridge.run_op(i)))
    except Exception:
        pass
    return out


def search(entries, text):
    words = [_norm(w) for w in text.split()]
    if not words:
        return []
    hits = []
    order = {MENU: 0, TAB: 1, BUTTON: 2, OPERATOR: 3}
    for e in entries:
        if all(w in e.hay for w in words):
            first = words[0]
            rank = 0 if e.key.startswith(first) else (1 if f" {first}" in f" {e.key}" else 2)
            if not any(w in e.key for w in words):
                rank += 3                       # only the location matches
            hits.append((rank, order[e.kind], e.name.lower(), e))
    hits.sort(key=lambda h: h[:3])
    return [h[3] for h in hits[:_MAX_RESULTS]]


# ---------------------------------------------------------------- popup
class FindPopup(QtWidgets.QDialog):
    """Search field + results (name, where, shortcut); Enter / double click runs the item."""

    def __init__(self, window, text=""):
        super().__init__(window, QtCore.Qt.Popup)
        self.window_ = window
        self.resize(theme.px(640), theme.px(460))
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(theme.px(6), theme.px(6), theme.px(6), theme.px(6))
        self.edit = QtWidgets.QLineEdit(self)
        self.edit.setPlaceholderText("Search menus, buttons, tabs and operators…")
        self.edit.setClearButtonEnabled(True)
        lay.addWidget(self.edit)
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Name", "Where", "Shortcut"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        self.tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.tree.setColumnWidth(0, theme.px(230))
        self.tree.itemActivated.connect(lambda _it, _c: self._accept())
        lay.addWidget(self.tree)
        self.info = QtWidgets.QLabel(self)
        self.info.setStyleSheet("color: #909090;")
        lay.addWidget(self.info)
        self.entries = collect(window)
        self.edit.textChanged.connect(self._filter)
        self.edit.returnPressed.connect(self._accept)
        self.edit.installEventFilter(self)
        self.edit.setText(text)
        self._filter(text)

    def _filter(self, text):
        self.tree.clear()
        hits = search(self.entries, text)
        grey = QtGui.QBrush(QtGui.QColor("#808080"))
        for e in hits:
            it = QtWidgets.QTreeWidgetItem([e.name, f"{e.kind}: {e.where}" if e.where else e.kind, e.shortcut])
            if e.icon is not None and not e.icon.isNull():
                it.setIcon(0, e.icon)
            it.setToolTip(0, f"{e.name}\n{e.kind}: {e.where}")
            it.setToolTip(1, f"{e.kind}: {e.where}")
            it.setForeground(1, grey)
            if not e.enabled:
                it.setDisabled(True)
            it.setData(0, QtCore.Qt.UserRole, e)
            self.tree.addTopLevelItem(it)
        for i in range(self.tree.topLevelItemCount()):
            if not self.tree.topLevelItem(i).isDisabled():
                self.tree.setCurrentItem(self.tree.topLevelItem(i))
                break
        if not text.strip():
            self.info.setText(f"{len(self.entries)} items – type a word, e.g. modeling, keyframe, render")
        else:
            self.info.setText(f"{len(hits)} found" + (" (first shown)" if len(hits) >= _MAX_RESULTS else ""))

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.KeyPress and ev.key() in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down,
                                                                QtCore.Qt.Key_PageUp, QtCore.Qt.Key_PageDown):
            QtWidgets.QApplication.sendEvent(self.tree, ev)
            return True
        return False

    def _accept(self):
        it = self.tree.currentItem()
        if it is None or it.isDisabled():
            return
        e = it.data(0, QtCore.Qt.UserRole)
        self.close()
        # run after the popup is gone (menus / dialogs opened by the item need the focus)
        QtCore.QTimer.singleShot(0, lambda: _run(e))


def _run(e):
    try:
        e.run()
    except Exception as ex:
        bridge.log(f"Search: {e.name} failed: {ex}", "ERROR")


def open_popup(window, text="", anchor=None):
    dlg = FindPopup(window, text)
    if anchor is not None:
        pos = anchor
    else:
        pos = window.mapToGlobal(QtCore.QPoint(window.width() // 2 - dlg.width() // 2, theme.px(60)))
    scr = QtGui.QGuiApplication.screenAt(pos) or QtGui.QGuiApplication.primaryScreen()
    r = scr.availableGeometry()
    pos.setX(max(r.left(), min(pos.x(), r.right() - dlg.width())))
    pos.setY(max(r.top(), min(pos.y(), r.bottom() - dlg.height())))
    dlg.move(pos)
    dlg.show()
    dlg.edit.setFocus()
    dlg.edit.end(False)
    return dlg


def add_to_menu(menu, window):
    """A search field at the top of a menu (Help); typing opens the results popup."""
    first = menu.actions()[0] if menu.actions() else None
    wa = QtWidgets.QWidgetAction(menu)
    box = QtWidgets.QWidget(menu)
    lay = QtWidgets.QHBoxLayout(box)
    lay.setContentsMargins(theme.px(6), theme.px(3), theme.px(6), theme.px(3))
    edit = QtWidgets.QLineEdit(box)
    edit.setPlaceholderText("Search…")
    edit.setToolTip("Search menus, buttons, tabs and operators by a word (like Maya's Help search)")
    edit.setMinimumWidth(theme.px(200))
    lay.addWidget(edit)
    wa.setDefaultWidget(box)

    def go(_text=None):
        text = edit.text()
        pos = menu.mapToGlobal(QtCore.QPoint(0, 0))
        menu.close()
        QtCore.QTimer.singleShot(0, lambda: open_popup(window, text, pos))
    edit.textEdited.connect(go)
    edit.returnPressed.connect(go)
    menu.insertAction(first, wa)
    sep = menu.insertSeparator(first) if first is not None else menu.addSeparator()
    act = QtGui.QAction("Search All…", menu)
    act.triggered.connect(lambda: QtCore.QTimer.singleShot(0, lambda: open_popup(window)))
    menu.insertAction(sep, act)
    # with the field as the context: the timer is dropped when the menu is refilled (the field deleted)
    QtCore.QTimer.singleShot(0, edit, lambda: edit.setFocus(QtCore.Qt.PopupFocusReason))
    return wa

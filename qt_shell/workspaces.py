"""Workspaces like Blender's: tabs (Layout, Modeling, Shading, …) that each remember a window layout.

A workspace stores which panels are shown, where and how big (QMainWindow state), the floating
windows, the 3D view layout (single / quad …) and the viewport shading. Switching saves the current
workspace first, so changes made in a workspace stay there.

- Tabs on the right side of the menu bar; + adds a workspace (copy of the current one or a template
  like Blender's General: Layout, Modeling, Shading, Animation, Scripting, UV Editing).
- Right click a tab: Rename…, Duplicate, Move Left / Right, Delete; double-click renames.
- Stored in Blender's config folder: config/qt_shell/workspaces.json.

Floating docks are never stored inside the Qt state (restoring them crashes Qt on Windows) – their
geometry is stored separately and they float again right after the switch.
"""
import base64
import copy
import json
import os
import traceback

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import api, bridge, theme

BOTTOM = QtCore.Qt.BottomDockWidgetArea
LEFT = QtCore.Qt.LeftDockWidgetArea
RIGHT = QtCore.Qt.RightDockWidgetArea

# template → (shading, viewport layout)
TEMPLATES = ["Layout", "Modeling", "Shading", "Animation", "Scripting", "UV Editing"]
DEFAULT_NAMES = ["Layout", "Modeling", "Shading", "Animation", "Scripting"]


# ---------------------------------------------------------------- storage
def _path():
    d = bpy.utils.user_resource("CONFIG", path="qt_shell", create=True)
    return os.path.join(d, "workspaces.json")


def load():
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("workspaces"), list) and data["workspaces"]:
            return data
    except FileNotFoundError:
        pass
    except Exception:
        bridge.log(f"Workspaces: cannot read {_path()}:\n{traceback.format_exc()}", "WARNING")
    return {"current": "Layout",
            "workspaces": [{"name": n, "template": n} for n in DEFAULT_NAMES]}


def save(data):
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
    except Exception:
        bridge.log(f"Workspaces: cannot save {_path()}:\n{traceback.format_exc()}", "ERROR")


# ---------------------------------------------------------------- templates
def apply_template(win, name):
    """Arranges the panels like Blender's workspace of that name."""
    win._reset_layout()
    d = win.docks
    # sensible widths – re-added docks otherwise end up a few pixels wide
    try:
        win.resizeDocks([d["outliner"]], [theme.px(300)], QtCore.Qt.Horizontal)
        win.resizeDocks([d["outliner"], d["properties"]], [theme.px(220), theme.px(600)], QtCore.Qt.Vertical)
    except Exception:
        pass
    show = lambda *keys: [d[k].show() for k in keys if k in d]
    hide = lambda *keys: [d[k].hide() for k in keys if k in d]
    shading, layout = "SOLID", "single"
    if name != "Animation":
        hide("graph_editor")
    if name == "Layout":
        hide("sidebar")
        d["timeline"].raise_()
        win.resizeDocks([d["timeline"]], [theme.px(190)], QtCore.Qt.Vertical)
    elif name == "Modeling":
        hide("sidebar", "timeline", "console", "node_editor", "uv_editor", "text_editor")
        show("last_op")                               # Adjust Last Operation – handy while modeling
    elif name == "Shading":
        shading = "MATERIAL"
        hide("sidebar", "timeline", "console", "uv_editor", "text_editor", "last_op")
        show("node_editor")
        d["node_editor"].raise_()
        win.resizeDocks([d["node_editor"]], [theme.px(330)], QtCore.Qt.Vertical)
    elif name == "Animation":
        hide("sidebar", "console", "node_editor", "uv_editor", "text_editor", "last_op")
        # like Maya: the Graph Editor above the Timeline
        ge, tl = d["graph_editor"], d["timeline"]
        win.addDockWidget(BOTTOM, ge)
        win.splitDockWidget(ge, tl, QtCore.Qt.Vertical)
        ge.show()
        tl.show()
        win.resizeDocks([ge, tl], [theme.px(330), theme.px(120)], QtCore.Qt.Vertical)
    elif name == "Scripting":
        hide("sidebar", "timeline", "node_editor", "uv_editor", "last_op")
        # Text editor on the left, Console at the bottom (like Blender's Scripting workspace)
        te = d["text_editor"]
        win.addDockWidget(LEFT, te)
        te.show()
        show("console")
        d["console"].raise_()
        win.resizeDocks([te], [theme.px(520)], QtCore.Qt.Horizontal)
        win.resizeDocks([d["console"]], [theme.px(200)], QtCore.Qt.Vertical)
    elif name == "UV Editing":
        hide("sidebar", "timeline", "console", "node_editor", "text_editor", "last_op")
        uv = d["uv_editor"]
        win.addDockWidget(LEFT, uv)
        uv.show()
        win.resizeDocks([uv], [theme.px(560)], QtCore.Qt.Horizontal)
    left = [d[k] for k in ("sidebar", "last_op") if k in d and d[k].isVisible() and not d[k].isFloating()]
    if left and name != "Scripting":
        win.resizeDocks(left, [theme.px(270)] * len(left), QtCore.Qt.Horizontal)
    return shading, layout


def fit_to_screen(win, old_geometry=None):
    """Re-arranging docks can grow the window (even past the screen edge) – put it back."""
    try:
        scr = (win.screen() or QtGui.QGuiApplication.primaryScreen()).availableGeometry()
        if old_geometry is not None and not win.isMaximized() and not win.isFullScreen() \
                and win.geometry() != old_geometry:
            win.setGeometry(old_geometry)
        g = win.geometry()                    # client area (a maximized frame is a bit larger than the screen)
        if not win.isVisible() or (g.width() <= scr.width() + 2 and g.height() <= scr.height() + 2):
            return
        if win.isMaximized():
            win.showNormal()
            win.showMaximized()
        else:
            win.resize(min(win.width(), scr.width() - 16), min(win.height(), scr.height() - 40))
            win.move(max(scr.x(), min(win.x(), scr.right() - win.width())), max(scr.y(), win.y()))
    except Exception:
        bridge.log(traceback.format_exc(), "WARNING")


# ---------------------------------------------------------------- manager
class Workspaces(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.data = load()
        if self.current() is None:
            self.data["current"] = self.data["workspaces"][0]["name"]

    # --- data
    def names(self):
        return [w["name"] for w in self.data["workspaces"]]

    def current(self):
        for w in self.data["workspaces"]:
            if w["name"] == self.data.get("current"):
                return w
        return None

    def _get(self, name):
        for w in self.data["workspaces"]:
            if w["name"] == name:
                return w
        return None

    def _unique(self, base):
        names = set(self.names())
        if base not in names:
            return base
        i = 1
        while f"{base}.{i:03d}" in names:
            i += 1
        return f"{base}.{i:03d}"

    def save(self):
        save(self.data)

    # --- window state
    def capture(self, ws=None):
        """Stores the current window layout into a workspace (the current one by default)."""
        ws = ws or self.current()
        if ws is None:
            return
        win = self.win
        floating = {}
        for key, d in win.docks.items():
            try:
                if d.isFloating() and not d.isHidden():
                    g = d.geometry()
                    floating[key] = [g.x(), g.y(), g.width(), g.height()]
                    d.setFloating(False)
            except RuntimeError:
                pass
        try:
            ws["state"] = base64.b64encode(bytes(win.saveState())).decode("ascii")
        finally:
            self._float(floating)
        ws["floating"] = floating
        try:
            ws["viewport_layout"] = win.viewports.mode
            ws["shading"] = win.viewport.shading()
        except Exception:
            pass

    def _float(self, floating):
        for key, geo in (floating or {}).items():
            d = self.win.docks.get(key)
            if d is None:
                continue
            try:
                d.setFloating(True)
                d.setGeometry(*[int(v) for v in geo])
                d.show()
            except (RuntimeError, TypeError):
                pass

    def _apply(self, ws):
        win = self.win
        old_geo = None if (win.isMaximized() or win.isFullScreen()) else QtCore.QRect(win.geometry())
        for d in win.docks.values():
            try:
                if d.isFloating():
                    d.setFloating(False)
            except RuntimeError:
                pass
        shading = ws.get("shading")
        layout = ws.get("viewport_layout")
        state = ws.get("state")
        if state:
            try:
                win.restoreState(QtCore.QByteArray(base64.b64decode(state)))
            except Exception:
                bridge.log(f"Workspace '{ws['name']}': cannot restore the layout:\n{traceback.format_exc()}",
                           "WARNING")
                state = None
        if not state:
            t_shading, t_layout = apply_template(win, ws.get("template") or "Layout")
            shading = shading or t_shading
            layout = layout or t_layout
        try:
            if layout:
                win.viewports.set_layout(layout)
            if shading:
                win.viewport.set_shading(shading)
                win._sync_shading()
        except Exception:
            bridge.log(traceback.format_exc(), "WARNING")
        QtCore.QTimer.singleShot(0, lambda: fit_to_screen(win, old_geo))
        floating = ws.get("floating") or {}
        if floating:
            # float right after the switch has been laid out (never inside restoreState)
            QtCore.QTimer.singleShot(50, lambda f=floating: self._float(f))

    # --- operations
    def switch(self, name):
        ws = self._get(name)
        cur = self.current()
        if ws is None or ws is cur:
            return
        if cur is not None:
            self.capture(cur)
        self.data["current"] = name
        self._apply(ws)
        self.save()
        self.changed.emit()
        api.status(f"Workspace: {name}")

    def add(self, template=None):
        """New workspace from a template, or a copy of the current one (template=None)."""
        cur = self.current()
        if cur is not None:
            self.capture(cur)
        if template:
            ws = {"name": self._unique(template), "template": template}
        else:
            ws = copy.deepcopy(cur) if cur else {"template": "Layout"}
            ws["name"] = self._unique(cur["name"] if cur else "Workspace")
        idx = self.data["workspaces"].index(cur) + 1 if cur in self.data["workspaces"] else len(self.data["workspaces"])
        self.data["workspaces"].insert(idx, ws)
        self.data["current"] = ws["name"]
        self._apply(ws)
        self.save()
        self.changed.emit()

    def rename(self, name, new):
        new = new.strip()
        ws = self._get(name)
        if ws is None or not new or new == name:
            return
        new = self._unique(new)
        if self.data.get("current") == name:
            self.data["current"] = new
        ws["name"] = new
        self.save()
        self.changed.emit()

    def delete(self, name):
        ws = self._get(name)
        if ws is None or len(self.data["workspaces"]) <= 1:
            return
        i = self.data["workspaces"].index(ws)
        self.data["workspaces"].remove(ws)
        if self.data.get("current") == name:
            nxt = self.data["workspaces"][max(0, i - 1)]
            self.data["current"] = nxt["name"]
            self._apply(nxt)
        self.save()
        self.changed.emit()

    def move(self, name, step):
        ws = self._get(name)
        lst = self.data["workspaces"]
        i = lst.index(ws)
        j = i + step
        if 0 <= j < len(lst):
            lst.insert(j, lst.pop(i))
            self.save()
            self.changed.emit()

    def reset(self, name):
        """Back to the template's layout."""
        ws = self._get(name)
        if ws is None:
            return
        for k in ("state", "floating", "viewport_layout", "shading"):
            ws.pop(k, None)
        if self.data.get("current") == name:
            self._apply(ws)
        self.save()

    def shutdown(self):
        self.capture()
        self.save()


# ---------------------------------------------------------------- tab bar
class WorkspaceTabs(QtWidgets.QWidget):
    """The workspace tabs + "+" in the menu bar."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.m = manager
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, theme.px(4), 0)
        lay.setSpacing(theme.px(2))
        self.tabs = QtWidgets.QTabBar(self)
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setStyleSheet(f"QTabBar::tab {{ padding: {theme.px(2)}px {theme.px(10)}px; }}")
        self.tabs.setToolTip("Workspaces – right click: rename, duplicate, delete…")
        self.tabs.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._menu)
        self.tabs.tabBarClicked.connect(self._clicked)
        self.tabs.tabBarDoubleClicked.connect(lambda i: i >= 0 and self._rename(self.tabs.tabText(i)))
        lay.addWidget(self.tabs)
        plus = QtWidgets.QToolButton(self)
        plus.setText("+")
        plus.setAutoRaise(True)
        plus.setToolTip("Add a workspace")
        plus.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        add_menu = QtWidgets.QMenu(plus)
        add_menu.addAction("Duplicate Current", lambda: self.m.add(None))
        add_menu.addSeparator()
        sec = add_menu.addAction("General")
        sec.setEnabled(False)
        for t in TEMPLATES:
            add_menu.addAction(t, lambda t=t: self.m.add(t))
        plus.setMenu(add_menu)
        lay.addWidget(plus)
        self.m.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        try:
            names = self.m.names()
            self.tabs.blockSignals(True)
            if [self.tabs.tabText(i) for i in range(self.tabs.count())] != names:
                while self.tabs.count():
                    self.tabs.removeTab(0)
                for n in names:
                    self.tabs.addTab(n)
            cur = self.m.data.get("current")
            if cur in names:
                self.tabs.setCurrentIndex(names.index(cur))
            self.tabs.blockSignals(False)
            self._relayout()
        except RuntimeError:
            pass

    def _relayout(self):
        """QMenuBar does not re-place its corner widget when the widget's size changes."""
        self.adjustSize()
        mb = self.parentWidget()
        if isinstance(mb, QtWidgets.QMenuBar):
            self.show()
            QtCore.QCoreApplication.sendEvent(mb, QtGui.QResizeEvent(mb.size(), mb.size()))
            mb.update()

    def _clicked(self, i):
        if i >= 0:
            # switch after the click has been handled (the switch rebuilds the window layout)
            QtCore.QTimer.singleShot(0, lambda n=self.tabs.tabText(i): self._switch(n))

    def _switch(self, name):
        try:
            self.m.switch(name)
        except Exception:
            bridge.log(f"Workspace switch failed:\n{traceback.format_exc()}", "ERROR")
        self.refresh()

    def _rename(self, name):
        new, ok = QtWidgets.QInputDialog.getText(self.window(), "Rename Workspace", "Name:", text=name)
        if ok:
            self.m.rename(name, new)

    def _menu(self, pos):
        i = self.tabs.tabAt(pos)
        if i < 0:
            return
        name = self.tabs.tabText(i)
        menu = QtWidgets.QMenu(self)
        menu.addAction("Rename…", lambda: self._rename(name))
        menu.addAction("Duplicate", lambda: (self.m.switch(name), self.m.add(None)))
        menu.addAction("Reset to Template", lambda: self.m.reset(name))
        menu.addSeparator()
        a = menu.addAction("Move Left", lambda: self.m.move(name, -1))
        a.setEnabled(i > 0)
        a = menu.addAction("Move Right", lambda: self.m.move(name, 1))
        a.setEnabled(i < self.tabs.count() - 1)
        menu.addSeparator()
        a = menu.addAction("Delete", lambda: self._delete(name))
        a.setEnabled(self.tabs.count() > 1)
        menu.exec(self.tabs.mapToGlobal(pos))

    def _delete(self, name):
        r = QtWidgets.QMessageBox.question(self.window(), "Delete Workspace", f"Delete the workspace “{name}”?")
        if r == QtWidgets.QMessageBox.Yes:
            self.m.delete(name)

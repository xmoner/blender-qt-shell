"""3D viewport sidebar (N panel) in Qt.

Shows the VIEW_3D / UI panels of Blender and of add-ons, one tab per bl_category, built with the
same machinery as the Properties editor (fake_ui → qt_ui). Panels are drawn with the real context
of the hidden 3D view, so add-on panels work without changes.
"""
import bpy
from PySide6 import QtCore, QtWidgets

from . import bridge, fake_ui, qt_ui, rna_widgets as rw
from .bridge import tr
from .properties import PanelPage, TabColumn, UndoDebouncer

# Blender's own tabs first, add-on tabs after them (alphabetically), like in Blender
_BUILTIN_ORDER = ["Item", "Tool", "View", "Edit", "Create", "Animation", "Misc"]


_ROT_PROPS = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}


class SidebarPage(PanelPage):
    """One sidebar tab (bl_category)."""

    def __init__(self, category, sidebar, on_change, state):
        super().__init__("sidebar:" + category, on_change, state)
        self.category = category
        self.sidebar = sidebar

    # --- Item ▸ Transform: drawn in C in Blender, so Qt Shell has its own version
    @staticmethod
    def _active():
        try:
            return bpy.context.view_layer.objects.active
        except Exception:
            return None

    def signature(self, recorded):
        sig = PanelPage.signature(recorded)
        if self.category == "Item":
            ob = self._active()
            sig += f"|item:{ob.name if ob else ''}:{ob.rotation_mode if ob else ''}"
        return sig

    def _build(self, recorded):
        super()._build(recorded)
        if self.category != "Item":
            return
        ob = self._active()
        if ob is None:
            return
        try:
            builder = qt_ui.Builder(self.on_change, self.state)
            panel = qt_ui.CollapsiblePanel(tr("Transform"), "qt:item_transform", self.state)
            rows = [("location", "Location"), (_ROT_PROPS.get(ob.rotation_mode, "rotation_euler"), "Rotation"),
                    ("rotation_mode", "Mode"), ("scale", "Scale"), ("dimensions", "Dimensions")]
            for prop, label in rows:
                b, _lab = rw.make_binding(ob, prop, text="", on_change=self.on_change)
                if b is None:
                    continue
                builder.bindings.append(b)
                panel.body_lay.addWidget(rw.labeled_row(tr(label), b.widget, True))
            self.builders.insert(0, builder)
            self.widget().layout().insertWidget(0, panel)
        except Exception as ex:
            bridge.log(f"Sidebar Item/Transform: {ex}", "ERROR")

    def record(self):
        ctx = bpy.context
        out = []

        def rec(tree):
            res = []
            for cls, children in tree:
                r = fake_ui.record_panel(cls, ctx)
                if r is None:
                    continue
                res.append((cls, r[0], r[1], rec(children)))
            return res
        return rec(self.sidebar.tree.get(self.category, []))


class Sidebar(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.state = {}
        self.undo = UndoDebouncer()
        self.tree = {}
        self.pages = {}
        self._cats = []
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = TabColumn()
        self.tabs.currentChanged.connect(lambda _i: self.refresh(force=True))
        lay.addWidget(self.tabs)
        self._throttle = QtCore.QTimer(self)
        self._throttle.setSingleShot(True)
        self._throttle.setInterval(150)
        self._throttle.timeout.connect(lambda: self.refresh())
        hub.data_changed.connect(self._schedule)
        hub.op_done.connect(lambda *_a: self._schedule())
        hub.selection_changed.connect(lambda: self.refresh(force=True))
        hub.file_loaded.connect(lambda: self.refresh(force=True))
        hub.undo_done.connect(lambda: self.refresh(force=True))
        hub.mode_changed.connect(lambda _m: self.refresh(force=True))
        self.refresh(force=True)

    def _changed(self, data, prop):
        self.undo(data, prop)
        self._schedule()

    def _schedule(self):
        if not self._throttle.isActive():
            self._throttle.start()

    @staticmethod
    def _order(cats):
        builtin = [c for c in _BUILTIN_ORDER if c in cats]
        return builtin + sorted(c for c in cats if c not in _BUILTIN_ORDER)

    def _sync_tabs(self):
        """Rebuilds the tab list when the set of categories changes (mode change, add-on enabled…)."""
        cats = self._order(list(self.tree))
        if cats == self._cats:
            return
        current = self._cats[self.tabs.currentIndex()] if self._cats else None
        self._cats = cats
        self.tabs.blockSignals(True)
        self.tabs.clear()
        for c in cats:
            page = self.pages.get(c)
            if page is None:
                page = self.pages[c] = SidebarPage(c, self, self._changed, self.state)
            self.tabs.addTab(page, c)
        if current in cats:
            self.tabs.setCurrentIndex(cats.index(current))
        elif cats:
            self.tabs.setCurrentIndex(0)
        self.tabs.blockSignals(False)

    def refresh(self, force=False):
        if not self.isVisible():
            return
        try:
            self.tree = fake_ui.sidebar_panels()
        except Exception as ex:
            bridge.log(f"Sidebar: {ex}", "ERROR")
            return
        try:
            if bpy.context.view_layer.objects.active is not None:
                self.tree.setdefault("Item", [])     # holds the Qt Transform panel
        except Exception:
            pass
        self._sync_tabs()
        if not self._cats:
            return
        page = self.pages[self._cats[max(0, self.tabs.currentIndex())]]
        fw = QtWidgets.QApplication.focusWidget()
        if not force and fw is not None and page.isAncestorOf(fw) and isinstance(
                fw, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox)):
            for b in page.builders:
                b.refresh()
            return
        page.refresh(force=force)

    def showEvent(self, ev):
        super().showEvent(ev)
        QtCore.QTimer.singleShot(0, lambda: self.refresh(force=True))

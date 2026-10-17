"""Outliner: kolekce a objekty scény, výběr, viditelnost, přejmenování."""
import bpy
from PySide6 import QtCore, QtWidgets

from . import bridge, theme

ROLE = QtCore.Qt.UserRole


class Outliner(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("Hledat…")
        self.filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Název", "👁", "📷"])
        self.tree.setColumnCount(3)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        hdr.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        self.tree.setColumnWidth(1, 28)
        self.tree.setColumnWidth(2, 28)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked |
                                  QtWidgets.QAbstractItemView.EditKeyPressed)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemClicked.connect(self._on_clicked)
        lay.addWidget(self.tree)
        self._sig = None
        self._items = {}
        self._updating = False
        hub.data_changed.connect(self.refresh)
        hub.selection_changed.connect(self.sync_selection)
        hub.file_loaded.connect(lambda: self.refresh(force=True))
        hub.undo_done.connect(lambda: self.refresh(force=True))
        self.refresh(force=True)

    # ------------------------------------------------------------ struktura
    def _signature(self):
        scene = bpy.context.scene

        def coll_sig(c):
            return (c.name, tuple(o.name for o in c.objects),
                    tuple((o.name, o.parent.name if o.parent else "") for o in c.objects),
                    tuple(coll_sig(ch) for ch in c.children))
        return (scene.name, coll_sig(scene.collection))

    def refresh(self, force=False):
        try:
            sig = self._signature()
        except Exception:
            return
        if force or sig != self._sig:
            self._sig = sig
            self._rebuild()
        else:
            self._update_states()

    def _rebuild(self):
        self._updating = True
        expanded = {k for k, it in self._items.items() if _alive(it) and it.isExpanded()}
        first = not self._items
        self.tree.clear()
        self._items = {}
        scene = bpy.context.scene
        root = QtWidgets.QTreeWidgetItem([scene.name])
        root.setIcon(0, theme.type_icon("SCENE"))
        root.setData(0, ROLE, ("COLLECTION", scene.collection.name, True))
        self.tree.addTopLevelItem(root)
        self._items[("COLLECTION", scene.collection.name)] = root
        self._add_collection(root, scene.collection)
        for key, it in self._items.items():
            if first or key in expanded or key[0] == "COLLECTION":
                it.setExpanded(True)
        self._updating = False
        self._update_states()
        self.sync_selection()
        self._apply_filter(self.filter.text())

    def _add_collection(self, parent_item, coll):
        for ch in coll.children:
            it = QtWidgets.QTreeWidgetItem([ch.name])
            it.setIcon(0, theme.type_icon("COLLECTION"))
            it.setData(0, ROLE, ("COLLECTION", ch.name, False))
            it.setFlags(it.flags() | QtCore.Qt.ItemIsEditable)
            parent_item.addChild(it)
            self._items[("COLLECTION", ch.name)] = it
            self._add_collection(it, ch)
        objs = list(coll.objects)
        in_coll = set(o.name for o in objs)
        for ob in sorted(objs, key=lambda o: o.name.lower()):
            if ob.parent is not None and ob.parent.name in in_coll:
                continue
            self._add_object(parent_item, ob, in_coll)

    def _add_object(self, parent_item, ob, in_coll):
        it = QtWidgets.QTreeWidgetItem([ob.name])
        it.setIcon(0, theme.type_icon(ob.type))
        it.setData(0, ROLE, ("OBJECT", ob.name, False))
        it.setFlags(it.flags() | QtCore.Qt.ItemIsEditable)
        parent_item.addChild(it)
        self._items.setdefault(("OBJECT", ob.name), it)
        for ch in sorted(ob.children, key=lambda o: o.name.lower()):
            if ch.name in in_coll:
                self._add_object(it, ch, in_coll)

    def _update_states(self):
        self._updating = True
        try:
            for (kind, name), it in self._items.items():
                if kind == "OBJECT":
                    ob = bpy.data.objects.get(name)
                    if ob is None:
                        continue
                    vis = not ob.hide_get()
                    ren = not ob.hide_render
                else:
                    c = bpy.data.collections.get(name)
                    if c is None:
                        continue
                    vis = not c.hide_viewport
                    ren = not c.hide_render
                it.setText(1, "👁" if vis else "·")
                it.setText(2, "◉" if ren else "·")
                it.setTextAlignment(1, QtCore.Qt.AlignCenter)
                it.setTextAlignment(2, QtCore.Qt.AlignCenter)
        finally:
            self._updating = False

    def _apply_filter(self, text):
        text = text.lower().strip()
        for (kind, name), it in self._items.items():
            if kind == "OBJECT":
                it.setHidden(bool(text) and text not in name.lower())

    # ------------------------------------------------------------ výběr
    def sync_selection(self):
        if self._updating:
            return
        self._updating = True
        try:
            ctx = bpy.context
            sel = {o.name for o in ctx.selected_objects}
            active = ctx.view_layer.objects.active
            self.tree.blockSignals(True)
            for (kind, name), it in self._items.items():
                if kind == "OBJECT":
                    it.setSelected(name in sel)
            if active is not None and ("OBJECT", active.name) in self._items:
                self.tree.setCurrentItem(self._items[("OBJECT", active.name)], 0,
                                         QtCore.QItemSelectionModel.NoUpdate)
            self.tree.blockSignals(False)
        finally:
            self._updating = False

    def _on_tree_selection(self):
        if self._updating:
            return
        ctx = bpy.context
        if ctx.mode != "OBJECT":
            return
        names = []
        for it in self.tree.selectedItems():
            kind, name, _root = it.data(0, ROLE)
            if kind == "OBJECT":
                names.append(name)
            elif kind == "COLLECTION":
                self._activate_collection(name)
        for o in ctx.view_layer.objects:
            o.select_set(o.name in names)
        cur = self.tree.currentItem()
        if cur is not None:
            kind, name, _r = cur.data(0, ROLE)
            if kind == "OBJECT" and name in names:
                ctx.view_layer.objects.active = bpy.data.objects.get(name)
        elif names:
            ctx.view_layer.objects.active = bpy.data.objects.get(names[-1])
        bridge.undo_push("Outliner Select")

    def _activate_collection(self, name):
        def find(lc):
            if lc.collection.name == name:
                return lc
            for ch in lc.children:
                r = find(ch)
                if r:
                    return r
            return None
        vl = bpy.context.view_layer
        lc = find(vl.layer_collection)
        if lc is not None:
            vl.active_layer_collection = lc

    def _on_clicked(self, it, col):
        if col not in (1, 2):
            return
        kind, name, _root = it.data(0, ROLE)
        if kind == "OBJECT":
            ob = bpy.data.objects.get(name)
            if ob is None:
                return
            if col == 1:
                ob.hide_set(not ob.hide_get())
            else:
                ob.hide_render = not ob.hide_render
        else:
            c = bpy.data.collections.get(name)
            if c is None:
                return
            if col == 1:
                c.hide_viewport = not c.hide_viewport
            else:
                c.hide_render = not c.hide_render
        bridge.undo_push("Toggle Visibility")
        self._update_states()

    def _on_item_changed(self, it, col):
        if self._updating or col != 0:
            return
        kind, name, root = it.data(0, ROLE)
        new = it.text(0).strip()
        if not new or new == name or root:
            return
        data = bpy.data.objects.get(name) if kind == "OBJECT" else bpy.data.collections.get(name)
        if data is None:
            return
        data.name = new
        bridge.undo_push("Rename")
        self.refresh(force=True)

    # ------------------------------------------------------------ kontextové menu
    def _context_menu(self, pos):
        it = self.tree.itemAt(pos)
        m = QtWidgets.QMenu(self)
        m.addAction("Nová kolekce", self._new_collection)
        if it is not None:
            kind, name, root = it.data(0, ROLE)
            if kind == "OBJECT":
                m.addAction("Duplikovat", lambda: bridge.run_op("object.duplicate"))
                m.addAction("Smazat", lambda: bridge.run_op("object.delete"))
                m.addAction("Zaměřit ve viewportu", self._frame)
                move = m.addMenu("Přesunout do kolekce")
                scene = bpy.context.scene
                targets = [scene.collection] + list(scene.collection.children_recursive)
                for c in targets:
                    label = scene.name if c == scene.collection else c.name
                    move.addAction(label, lambda c=c: self._move_selected(c))
            elif kind == "COLLECTION" and not root:
                m.addAction("Smazat kolekci", lambda: self._delete_collection(name))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _frame(self):
        vp = self.hub.viewport
        if vp is not None:
            vp.frame_selected()

    def _new_collection(self):
        ctx = bpy.context
        parent = ctx.view_layer.active_layer_collection.collection
        c = bpy.data.collections.new("Collection")
        parent.children.link(c)
        bridge.undo_push("New Collection")
        self.refresh(force=True)

    def _delete_collection(self, name):
        c = bpy.data.collections.get(name)
        if c is not None:
            bpy.data.collections.remove(c)
            bridge.undo_push("Delete Collection")
            self.refresh(force=True)

    def _move_selected(self, target):
        for ob in bpy.context.selected_objects:
            for c in list(ob.users_collection):
                c.objects.unlink(ob)
            target.objects.link(ob)
        bridge.undo_push("Move to Collection")
        self.refresh(force=True)


def _alive(item):
    try:
        item.text(0)
        return True
    except RuntimeError:
        return False

"""Outliner: scene collections and objects like Blender's View Layer mode.

Objects show their children (also children that live in another collection – greyed, like Blender),
and, when expanded, their contents: object data (armature data with the bone hierarchy, materials),
modifiers, constraints and vertex groups. The contents are filled lazily on first expand, so big rigs
stay fast.
"""
import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, theme

KEY = QtCore.Qt.UserRole          # item key tuple: ("OBJECT", name), ("BONE", ob, bone), …
ROOT = QtCore.Qt.UserRole + 1     # True for the scene collection row
LAZY = ("LAZY",)

_DATA_ICONS = {
    "MESH": "MESH_DATA", "CURVE": "CURVE_DATA", "SURFACE": "SURFACE_DATA", "FONT": "FONT_DATA",
    "META": "META_DATA", "ARMATURE": "ARMATURE_DATA", "LATTICE": "LATTICE_DATA", "CAMERA": "CAMERA_DATA",
    "LIGHT": "LIGHT_DATA", "SPEAKER": "SPEAKER", "CURVES": "CURVES_DATA", "POINTCLOUD": "POINTCLOUD_DATA",
    "VOLUME": "VOLUME_DATA", "GREASEPENCIL": "OUTLINER_DATA_GREASEPENCIL", "LIGHT_PROBE": "LIGHTPROBE_SPHERE",
}


def _icon(*names):
    try:
        from . import blicons
        for n in names:
            if n and blicons.has(n):
                return blicons.icon(n)
    except Exception:
        pass
    return QtGui.QIcon()


def _enum_icon(item, prop="type"):
    try:
        rp = item.bl_rna.properties[prop]
        ident = getattr(item, prop)
        for e in rp.enum_items:
            if e.identifier == ident:
                return e.icon
    except Exception:
        pass
    return ""


class Outliner(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("Search…")
        self.filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Name", "👁", "📷"])
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
        self.tree.itemExpanded.connect(self._on_expanded)
        lay.addWidget(self.tree)
        self._sig = None
        self._items = {}          # key → item (first occurrence)
        self._all = []            # (key, item) for every row, duplicates included
        self._expanded = set()
        self._updating = False
        self._last_active = None        # active row key last revealed (sync_selection)
        hub.data_changed.connect(self.refresh)
        hub.selection_changed.connect(self.sync_selection)
        hub.file_loaded.connect(lambda: self.refresh(force=True))
        hub.undo_done.connect(lambda: self.refresh(force=True))
        self.refresh(force=True)

    # ------------------------------------------------------------ structure
    def _signature(self):
        scene = bpy.context.scene

        def ob_sig(o):
            d = o.data
            return (o.name, o.parent.name if o.parent else "", o.type, d.name if d else "",
                    tuple(m.name for m in o.modifiers), tuple(c.name for c in o.constraints),
                    len(o.vertex_groups), len(d.bones) if o.type == "ARMATURE" and d else 0,
                    tuple(s.material.name if s.material else "" for s in o.material_slots))

        def coll_sig(c):
            return (c.name, tuple(ob_sig(o) for o in c.objects), tuple(coll_sig(ch) for ch in c.children))
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

    def _remember_expanded(self):
        for key, it in self._all:
            if _alive(it):
                if it.isExpanded():
                    self._expanded.add(key)
                elif key in self._expanded and it.childCount():
                    self._expanded.discard(key)

    def _rebuild(self):
        self._updating = True
        first = not self._all
        self._remember_expanded()
        scroll = self.tree.verticalScrollBar().value()
        self.tree.clear()
        self._items = {}
        self._all = []
        scene = bpy.context.scene
        root = self._new(None, scene.name, ("COLLECTION", scene.collection.name), theme.type_icon("SCENE"))
        root.setData(0, ROOT, True)
        self.tree.addTopLevelItem(root)
        self._add_collection(root, scene.collection)
        for key, it in list(self._all):
            if key[0] == "COLLECTION" or (not first and key in self._expanded):
                it.setExpanded(True)          # also fills lazy rows (itemExpanded)
        self._updating = False
        self._update_states()
        self.sync_selection()
        self._apply_filter(self.filter.text())
        QtCore.QTimer.singleShot(0, lambda: self.tree.verticalScrollBar().setValue(scroll))

    def _new(self, parent_item, text, key, icon=None, editable=False, dim=False):
        it = QtWidgets.QTreeWidgetItem([text])
        if icon is not None:
            it.setIcon(0, icon)
        it.setData(0, KEY, key)
        it.setData(0, ROOT, False)
        if editable:
            it.setFlags(it.flags() | QtCore.Qt.ItemIsEditable)
        if dim:
            it.setForeground(0, QtGui.QBrush(QtGui.QColor(140, 140, 140)))
            f = it.font(0)
            f.setItalic(True)
            it.setFont(0, f)
        if parent_item is not None:
            parent_item.addChild(it)
        self._items.setdefault(key, it)
        self._all.append((key, it))
        return it

    def _add_collection(self, parent_item, coll):
        for ch in coll.children:
            it = self._new(parent_item, ch.name, ("COLLECTION", ch.name), theme.type_icon("COLLECTION"),
                           editable=True)
            self._add_collection(it, ch)
        objs = list(coll.objects)
        in_coll = set(o.name for o in objs)
        for ob in sorted(objs, key=lambda o: o.name.lower()):
            if ob.parent is not None and ob.parent.name in in_coll:
                continue
            self._add_object(parent_item, ob, in_coll, set())

    def _add_object(self, parent_item, ob, in_coll, chain, dim=False):
        it = self._new(parent_item, ob.name, ("OBJECT", ob.name), theme.type_icon(ob.type),
                       editable=True, dim=dim)
        chain = chain | {ob.name}
        for ch in sorted(ob.children, key=lambda o: o.name.lower()):
            if ch.name in chain:
                continue
            # children from another collection are shown greyed under their parent, like Blender
            self._add_object(it, ch, in_coll, chain, dim=dim or ch.name not in in_coll)
        if self._has_contents(ob):
            lazy = QtWidgets.QTreeWidgetItem(["…"])
            lazy.setData(0, KEY, LAZY + (ob.name,))
            it.addChild(lazy)

    @staticmethod
    def _has_contents(ob):
        return bool(ob.data is not None or len(ob.modifiers) or len(ob.constraints)
                    or len(ob.vertex_groups))

    def _on_expanded(self, it):
        if it.childCount() == 0:
            return
        last = it.child(it.childCount() - 1)
        key = last.data(0, KEY)
        if not key or key[0] != "LAZY":
            return
        it.removeChild(last)
        ob = bpy.data.objects.get(key[1])
        if ob is None:
            return
        was = self._updating
        self._updating = True
        try:
            self._fill_contents(it, ob)
            for k, child in list(self._all):
                if k in self._expanded and _alive(child) and child.childCount() and _is_under(child, it):
                    child.setExpanded(True)
        finally:
            self._updating = was
        if not was:
            self.sync_selection()

    def _fill_contents(self, it, ob):
        """Blender order: object data first, then modifiers, constraints, vertex groups."""
        n = ob.name
        d = ob.data
        if d is not None:
            dit = self._new(None, d.name, ("DATA", n), _icon(_DATA_ICONS.get(ob.type), "OUTLINER_DATA_" + ob.type))
            it.insertChild(0, dit)
            if ob.type == "ARMATURE":
                for b in d.bones:
                    if b.parent is None:
                        self._add_bone(dit, ob, b)
            for i, slot in enumerate(ob.material_slots):
                if slot.material is not None:
                    self._new(dit, slot.material.name, ("MAT", n, i), _icon("MATERIAL_DATA", "MATERIAL"))
        if len(ob.modifiers):
            g = self._new(it, "Modifiers", ("MODS", n), _icon("MODIFIER"))
            for m in ob.modifiers:
                self._new(g, m.name, ("MOD", n, m.name), _icon(_enum_icon(m), "MODIFIER"))
        if len(ob.constraints):
            g = self._new(it, "Constraints", ("CONS", n), _icon("CONSTRAINT"))
            for c in ob.constraints:
                self._new(g, c.name, ("CON", n, c.name), _icon(_enum_icon(c), "CONSTRAINT"))
        if len(ob.vertex_groups):
            g = self._new(it, "Vertex Groups", ("VGROUPS", n), _icon("GROUP_VERTEX"))
            for vg in ob.vertex_groups:
                self._new(g, vg.name, ("VGROUP", n, vg.name), _icon("GROUP_VERTEX"))

    def _add_bone(self, parent_item, ob, bone):
        it = self._new(parent_item, bone.name, ("BONE", ob.name, bone.name), _icon("BONE_DATA"))
        for ch in bone.children:
            self._add_bone(it, ob, ch)

    def _update_states(self):
        self._updating = True
        try:
            for key, it in self._all:
                if not _alive(it):
                    continue
                kind = key[0]
                if kind == "OBJECT":
                    ob = bpy.data.objects.get(key[1])
                    if ob is None:
                        continue
                    try:
                        vis = not ob.hide_get()
                    except RuntimeError:          # object not in the view layer
                        vis = not ob.hide_viewport
                    ren = not ob.hide_render
                elif kind == "COLLECTION":
                    c = bpy.data.collections.get(key[1])
                    if c is None:
                        continue
                    vis = not c.hide_viewport
                    ren = not c.hide_render
                elif kind == "BONE":
                    ob = bpy.data.objects.get(key[1])
                    pb = ob.pose.bones.get(key[2]) if ob is not None and ob.pose is not None else None
                    if pb is None:
                        continue
                    vis = not getattr(pb, "hide", False)
                    it.setText(1, "👁" if vis else "·")
                    it.setTextAlignment(1, QtCore.Qt.AlignCenter)
                    continue
                elif kind == "MOD":
                    ob = bpy.data.objects.get(key[1])
                    m = ob.modifiers.get(key[2]) if ob is not None else None
                    if m is None:
                        continue
                    vis, ren = m.show_viewport, m.show_render
                else:
                    continue
                it.setText(1, "👁" if vis else "·")
                it.setText(2, "◉" if ren else "·")
                it.setTextAlignment(1, QtCore.Qt.AlignCenter)
                it.setTextAlignment(2, QtCore.Qt.AlignCenter)
        finally:
            self._updating = False

    def _apply_filter(self, text):
        text = text.lower().strip()
        for key, it in self._all:
            if not _alive(it) or key[0] == "COLLECTION":
                continue
            if key[0] in ("OBJECT", "BONE"):
                it.setHidden(bool(text) and text not in it.text(0).lower() and not _child_matches(it, text))

    # ------------------------------------------------------------ selection
    def sync_selection(self):
        if self._updating:
            return
        self._updating = True
        try:
            ctx = bpy.context
            sel = {o.name for o in ctx.selected_objects}
            active = ctx.view_layer.objects.active
            pose = ctx.mode == "POSE"
            sel_bones = set()
            if pose:
                for o in ctx.view_layer.objects:
                    if o.type == "ARMATURE" and o.mode == "POSE" and o.pose is not None:
                        sel_bones.update((o.name, pb.name) for pb in o.pose.bones if pb.select)
            act_key = None
            if pose and active is not None and active.type == "ARMATURE" and active.data.bones.active:
                act_key = ("BONE", active.name, active.data.bones.active.name)
            elif active is not None:
                act_key = ("OBJECT", active.name)
            if act_key != self._last_active:
                # a new active object / bone (picked in the viewport…): open the rows down to it,
                # like Blender's Show Active – only once per change, so it can be collapsed again
                self._last_active = act_key
                if act_key is not None:
                    self._reveal(act_key)
            self.tree.blockSignals(True)
            for key, it in self._all:
                if not _alive(it):
                    continue
                if key[0] == "OBJECT":
                    # in Pose mode the armature stays selected too (as in Blender)
                    it.setSelected(key[1] in sel)
                elif key[0] == "BONE":
                    it.setSelected((key[1], key[2]) in sel_bones)
            cur = self._items.get(act_key) if act_key is not None else None
            if cur is None and active is not None:
                cur = self._items.get(("OBJECT", active.name))
            if cur is not None and _alive(cur) and _shown(cur):
                # only when its parents are open: making a hidden row current makes Qt scroll to it,
                # which expands every parent (a whole bone chain)
                idx = self.tree.indexFromItem(cur, 0)
                self.tree.selectionModel().setCurrentIndex(idx, QtCore.QItemSelectionModel.NoUpdate)
            self.tree.blockSignals(False)
        finally:
            self._updating = False

    def _reveal(self, key):
        """Expand the parents of the row for `key` (filling lazy object contents for bones)
        and scroll to it. Signals must not be blocked: expanding fills lazy rows."""
        if key[0] == "BONE":
            obit = self._items.get(("OBJECT", key[1]))
            if obit is None or not _alive(obit):
                return
            if self._items.get(key) is None or not _alive(self._items.get(key)):
                obit.setExpanded(True)              # fills the armature's data + bones (itemExpanded)
        it = self._items.get(key)
        if it is None or not _alive(it):
            return
        p = it.parent()
        while p is not None:
            if not p.isExpanded():
                p.setExpanded(True)
            p = p.parent()
        self.tree.scrollToItem(it, QtWidgets.QAbstractItemView.EnsureVisible)

    def _on_tree_selection(self):
        if self._updating:
            return
        ctx = bpy.context
        items = self.tree.selectedItems()
        keys = [it.data(0, KEY) for it in items if it.data(0, KEY)]
        cur = self.tree.currentItem()
        cur_key = cur.data(0, KEY) if cur is not None else None
        if ctx.mode == "POSE":
            self._select_bones(keys, cur_key)
            return
        if ctx.mode != "OBJECT":
            return
        names = []
        for key in keys:
            if key[0] == "COLLECTION":
                self._activate_collection(key[1])
            elif key[0] != "LAZY" and len(key) > 1:
                names.append(key[1])            # contents (data, bones, modifiers…) select their object
        for o in ctx.view_layer.objects:
            o.select_set(o.name in names)
        act = None
        if cur_key and cur_key[0] not in ("COLLECTION", "LAZY") and cur_key[1] in names:
            act = bpy.data.objects.get(cur_key[1])
        elif names:
            act = bpy.data.objects.get(names[-1])
        if act is not None:
            ctx.view_layer.objects.active = act
            if cur_key:
                self._activate_content(act, cur_key)
        bridge.undo_push("Outliner Select")

    def _select_bones(self, keys, cur_key):
        bones = {(k[1], k[2]) for k in keys if k[0] == "BONE"}
        if not bones:
            return
        for o in bpy.context.view_layer.objects:
            if o.type == "ARMATURE" and o.mode == "POSE" and o.pose is not None:
                for pb in o.pose.bones:
                    pb.select = (o.name, pb.name) in bones
                o.update_tag()
        if cur_key and cur_key[0] == "BONE" and (cur_key[1], cur_key[2]) in bones:
            ob = bpy.data.objects.get(cur_key[1])
            if ob is not None:
                ob.data.bones.active = ob.data.bones.get(cur_key[2])
        bridge.undo_push("Outliner Select")
        vp = getattr(self.hub, "viewport", None)
        if vp is not None:
            vp.request_redraw()

    @staticmethod
    def _activate_content(ob, key):
        try:
            if key[0] == "BONE" and ob.type == "ARMATURE":
                ob.data.bones.active = ob.data.bones.get(key[2])
            elif key[0] == "MOD":
                ob.modifiers.active = ob.modifiers.get(key[2])
            elif key[0] == "CON":
                c = ob.constraints.get(key[2])
                if c is not None:
                    c.active = True
            elif key[0] == "VGROUP":
                i = ob.vertex_groups.find(key[2])
                if i >= 0:
                    ob.vertex_groups.active_index = i
            elif key[0] == "MAT":
                ob.active_material_index = key[2]
        except Exception:
            pass

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
        key = it.data(0, KEY)
        if not key:
            return
        kind = key[0]
        if kind == "OBJECT":
            ob = bpy.data.objects.get(key[1])
            if ob is None:
                return
            if col == 1:
                try:
                    ob.hide_set(not ob.hide_get())
                except RuntimeError:
                    ob.hide_viewport = not ob.hide_viewport
            else:
                ob.hide_render = not ob.hide_render
        elif kind == "COLLECTION":
            c = bpy.data.collections.get(key[1])
            if c is None:
                return
            if col == 1:
                c.hide_viewport = not c.hide_viewport
            else:
                c.hide_render = not c.hide_render
        elif kind == "BONE" and col == 1:
            ob = bpy.data.objects.get(key[1])
            pb = ob.pose.bones.get(key[2]) if ob is not None and ob.pose is not None else None
            if pb is None:
                return
            pb.hide = not pb.hide
        elif kind == "MOD":
            ob = bpy.data.objects.get(key[1])
            m = ob.modifiers.get(key[2]) if ob is not None else None
            if m is None:
                return
            if col == 1:
                m.show_viewport = not m.show_viewport
            else:
                m.show_render = not m.show_render
        else:
            return
        bridge.undo_push("Toggle Visibility")
        self._update_states()
        vp = getattr(self.hub, "viewport", None)
        if vp is not None:
            vp.request_redraw()

    def _on_item_changed(self, it, col):
        if self._updating or col != 0:
            return
        key = it.data(0, KEY)
        if not key or it.data(0, ROOT):
            return
        new = it.text(0).strip()
        if not new or new == key[1] or key[0] not in ("OBJECT", "COLLECTION"):
            return
        data = bpy.data.objects.get(key[1]) if key[0] == "OBJECT" else bpy.data.collections.get(key[1])
        if data is None:
            return
        data.name = new
        bridge.undo_push("Rename")
        self.refresh(force=True)

    # ------------------------------------------------------------ context menu
    def _context_menu(self, pos):
        it = self.tree.itemAt(pos)
        m = QtWidgets.QMenu(self)
        m.addAction("New Collection", self._new_collection)
        if it is not None:
            key = it.data(0, KEY) or ("",)
            kind = key[0]
            if kind == "OBJECT":
                m.addAction("Duplicate", lambda: bridge.run_op("object.duplicate"))
                m.addAction("Delete", lambda: bridge.run_op("object.delete"))
                m.addAction("Frame in Viewport", self._frame)
                move = m.addMenu("Move to Collection")
                scene = bpy.context.scene
                targets = [scene.collection] + list(scene.collection.children_recursive)
                for c in targets:
                    label = scene.name if c == scene.collection else c.name
                    move.addAction(label, lambda c=c: self._move_selected(c))
            elif kind == "COLLECTION" and not it.data(0, ROOT):
                m.addAction("Delete Collection", lambda: self._delete_collection(key[1]))
            if it.childCount():
                m.addSeparator()
                m.addAction("Expand All Children", lambda: self._expand_all(it, True))
                m.addAction("Collapse All Children", lambda: self._expand_all(it, False))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _expand_all(self, it, on):
        it.setExpanded(on)
        for i in range(it.childCount()):
            self._expand_all(it.child(i), on)

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


def _shown(item):
    p = item.parent()
    while p is not None:
        if not p.isExpanded():
            return False
        p = p.parent()
    return True


def _is_under(item, ancestor):
    p = item.parent()
    while p is not None:
        if p is ancestor:
            return True
        p = p.parent()
    return False


def _child_matches(item, text):
    for i in range(item.childCount()):
        ch = item.child(i)
        if text in ch.text(0).lower() or _child_matches(ch, text):
            return True
    return False

"""Builds Qt widgets and menus from the tree recorded with fake_ui.FakeLayout."""
import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import fake_ui, rna_widgets as rw, theme
from . import blicons
from . import pytips
from .bridge import op_label, op_poll, op_rna_props, run_op, tr
from .bridge import undo_push as bridge_undo

ICON_GLYPHS = {
    "ADD": "+", "REMOVE": "−", "X": "✕", "PANEL_CLOSE": "✕", "CANCEL": "✕", "TRIA_UP": "▲",
    "TRIA_DOWN": "▼", "TRIA_RIGHT": "▶", "TRIA_LEFT": "◀", "DOWNARROW_HLT": "▾",
    "PRESET": "☰", "DUPLICATE": "⧉", "FILE_FOLDER": "…", "FILEBROWSER": "…",
    "CHECKMARK": "✓", "PLAY": "▶", "PAUSE": "⏸", "HIDE_OFF": "👁", "RESTRICT_RENDER_OFF": "◉",
    "COPYDOWN": "⧉", "PASTEDOWN": "⎘", "COLLAPSEMENU": "≡", "LOCKED": "🔒", "UNLOCKED": "🔓",
    "FILE_REFRESH": "↻", "DECORATE_ANIMATE": "◆", "KEY_HLT": "◆", "ZOOM_IN": "+", "ZOOM_OUT": "−",
    "SORTALPHA": "AZ", "UV": "UV", "MATERIAL": "●", "DOT": "·",
}
SILENT_UNSUPPORTED = {"template_preview", "template_header", "template_icon", "introspect",
                      "template_running_jobs", "template_reports_banner", "template_input_status",
                      "template_status_info"}


def _glyph(icon, text):
    if text:
        return text
    return ICON_GLYPHS.get(icon, "•")


# ---------------------------------------------------------------- special bindings
class EnumValueButton(rw.Binding):
    def __init__(self, data, prop_id, value, text, on_change):
        super().__init__(data, prop_id, on_change)
        self.value = value
        if text is None:
            text = next((n for i, n, _d in rw.enum_items(data, prop_id) if i == value), value)
        b = QtWidgets.QPushButton(text)
        b.setCheckable(True)
        b.clicked.connect(self._click)
        pytips.tag(b, f"{pytips.prop_text(data, prop_id)} = {value!r}")
        self.widget = b
        self.refresh()

    def _click(self):
        try:
            cur = getattr(self.data, self.prop_id)
            if isinstance(cur, set):
                setattr(self.data, self.prop_id, cur ^ {self.value})
            else:
                setattr(self.data, self.prop_id, self.value)
            self.changed()
        except Exception:
            pass
        self.refresh()

    def refresh(self):
        cur = getattr(self.data, self.prop_id)
        on = self.value in cur if isinstance(cur, set) else cur == self.value
        self.widget.blockSignals(True)
        self.widget.setChecked(on)
        self.widget.blockSignals(False)


class TemplateListBinding(rw.Binding):
    def __init__(self, data, prop_id, active_data, active_prop, rows, on_change):
        super().__init__(data, prop_id, on_change)
        self.active_data = active_data
        self.active_prop = active_prop
        w = QtWidgets.QListWidget()
        w.setMinimumHeight(max(3, min(rows, 8)) * theme.px(22))
        w.setMaximumHeight(max(3, min(rows, 8)) * theme.px(22) + 6)
        w.currentRowChanged.connect(self._select)
        w.itemChanged.connect(self._renamed)
        self.widget = w
        self._names = None
        self.refresh()

    def _coll(self):
        return getattr(self.data, self.prop_id)

    def _select(self, row):
        if row < 0 or self.active_data is None:
            return
        try:
            setattr(self.active_data, self.active_prop, row)
            self.changed()
        except Exception:
            pass

    def _renamed(self, item):
        row = self.widget.row(item)
        try:
            el = self._coll()[row]
            if hasattr(el, "name") and el.name != item.text():
                el.name = item.text()
                self.changed()
        except Exception:
            pass

    def refresh(self):
        coll = self._coll()
        names = [getattr(el, "name", "") or str(i) for i, el in enumerate(coll)]
        w = self.widget
        w.blockSignals(True)
        if names != self._names:
            self._names = names
            w.clear()
            for i, n in enumerate(names):
                it = QtWidgets.QListWidgetItem(n)
                if hasattr(coll[i], "name"):
                    it.setFlags(it.flags() | QtCore.Qt.ItemIsEditable)
                w.addItem(it)
        try:
            w.setCurrentRow(getattr(self.active_data, self.active_prop))
        except Exception:
            pass
        w.blockSignals(False)


class TemplateIDBinding(rw.Binding):
    def __init__(self, data, prop_id, new_op, unlink_op, on_change):
        super().__init__(data, prop_id, on_change)
        self.rp = rw.rna_prop(data, prop_id)
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.combo = rw.IDBinding(data, prop_id, self.rp, on_change) if self.rp is not None else None
        if self.combo:
            lay.addWidget(self.combo.widget, 1)
            if self.rp.is_readonly:
                self.combo.widget.setEnabled(False)
        self.new_op = new_op
        b_new = QtWidgets.QToolButton()
        b_new.setText("+ " + tr("New"))
        b_new.clicked.connect(self._new)
        lay.addWidget(b_new)
        if self.rp is not None and not self.rp.is_readonly:
            b_x = QtWidgets.QToolButton()
            b_x.setText("✕")
            b_x.setToolTip(tr("Unlink"))
            b_x.clicked.connect(self._unlink)
            lay.addWidget(b_x)
        self.widget = w

    def _new(self):
        """Like the New button in Blender: copies the current datablock, otherwise creates a new one,
        and assigns it right away (operators such as material.new only assign via the UI button)."""
        new_id = None
        try:
            cur = getattr(self.data, self.prop_id)
            if cur is not None and hasattr(cur, "copy"):
                new_id = cur.copy()
            elif self.rp is not None:
                type_id = self.rp.fixed_type.identifier
                coll = rw.id_collection_for(type_id)
                name = tr(self.rp.fixed_type.name) or type_id
                attempts = {
                    "Texture": lambda: coll.new(name, "IMAGE"),
                    "NodeTree": lambda: coll.new(name, "GeometryNodeTree"),
                    "Image": lambda: coll.new(name, 1024, 1024),
                }
                new_id = attempts.get(type_id, lambda: coll.new(name))()
                if type_id in ("Material", "World") and hasattr(new_id, "use_nodes"):
                    try:
                        new_id.use_nodes = True
                    except Exception:
                        pass
        except Exception:
            new_id = None
        if new_id is not None:
            try:
                setattr(self.data, self.prop_id, new_id)
            except Exception as ex:
                from .bridge import log
                log(f"{self.prop_id}: {ex}", "ERROR")
        elif self.new_op:
            run_op(self.new_op)
        bridge_undo("New")
        self.changed()

    def _unlink(self):
        try:
            setattr(self.data, self.prop_id, None)
            self.changed()
        except Exception:
            pass

    def refresh(self):
        if self.combo:
            self.combo.refresh()


# ---------------------------------------------------------------- collapsible panel
class CollapsiblePanel(QtWidgets.QFrame):
    def __init__(self, title, key, state, default_closed=False, header_widget=None, flat=False):
        super().__init__()
        self.setObjectName("" if flat else "qtshell_panel")
        self.key = key
        self.state = state
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 4)
        lay.setSpacing(2)
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(4)
        self.btn = QtWidgets.QToolButton()
        self.btn.setObjectName("qtshell_panel_header")
        self.btn.setText(title)
        self.btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.btn.setCheckable(True)
        opened = state.get(key, not default_closed)
        self.btn.setChecked(opened)
        self.btn.setArrowType(QtCore.Qt.DownArrow if opened else QtCore.Qt.RightArrow)
        self.btn.toggled.connect(self._toggle)
        if header_widget is not None:
            head.addWidget(header_widget)
        head.addWidget(self.btn, 1)
        lay.addLayout(head)
        self.body = QtWidgets.QWidget()
        self.body_lay = QtWidgets.QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(6, 0, 0, 0)
        self.body_lay.setSpacing(3)
        lay.addWidget(self.body)
        self.body.setVisible(opened)

    def _toggle(self, on):
        self.state[self.key] = on
        self.btn.setArrowType(QtCore.Qt.DownArrow if on else QtCore.Qt.RightArrow)
        self.body.setVisible(on)


# ---------------------------------------------------------------- builder
class Builder:
    def __init__(self, on_change=None, panel_state=None):
        self.bindings = []
        self.on_change = on_change
        self.state = panel_state if panel_state is not None else {}

    def refresh(self):
        """Refreshes values; returns False if some data no longer exists."""
        ok = True
        for b in self.bindings:
            try:
                b.refresh()
            except ReferenceError:
                ok = False
            except Exception:
                pass
        return ok

    # --- containers
    def build(self, node, parent_kind="column"):
        k = node.kind
        if k in ("column", "row", "box", "split", "flow", "unsupported_layout"):
            return self._container(node)
        if k == "lpanel":
            return self._layout_panel(node)
        return self._item(node, parent_kind)

    def _container(self, node):
        k = node.kind
        f = node.flags
        if k == "box":
            w = QtWidgets.QFrame()
            w.setObjectName("qtshell_box")
        else:
            w = QtWidgets.QWidget()
        align = node.args.get("align", False)
        if k in ("row", "split"):
            lay = QtWidgets.QHBoxLayout(w)
        elif k == "flow":
            lay = QtWidgets.QGridLayout(w)
        else:
            lay = QtWidgets.QVBoxLayout(w)
        m = 4 if k == "box" else 0
        lay.setContentsMargins(m, m, m, m)
        lay.setSpacing(1 if align else 4)
        heading = node.args.get("heading")
        split_heading = bool(heading) and f.get("use_property_split", False) and k in ("row", "column")
        n_items = 0
        if heading and not split_heading:
            lab = QtWidgets.QLabel(heading)
            if isinstance(lay, QtWidgets.QGridLayout):
                lay.addWidget(lab, 0, 0)
            else:
                lay.addWidget(lab)
        first_child = None
        children = node.children
        factor = node.args.get("factor", 0.0) if k == "split" else 0.0
        cols = node.args.get("columns", 0) if k == "flow" else 0
        if k == "flow" and cols <= 0:
            cols = 1
        for i, ch in enumerate(children):
            if ch.kind == "spacer":
                if isinstance(lay, QtWidgets.QBoxLayout):
                    lay.addStretch(1)
                continue
            if ch.kind == "separator":
                if isinstance(lay, QtWidgets.QHBoxLayout):
                    lay.addSpacing(int(8 * ch.args.get("factor", 1.0)))
                elif isinstance(lay, QtWidgets.QVBoxLayout):
                    lay.addSpacing(int(6 * ch.args.get("factor", 1.0)))
                continue
            cw = self.build(ch, k)
            if cw is None:
                continue
            if first_child is None:
                first_child = cw
            if k == "flow":
                lay.addWidget(cw, n_items // cols + (1 if heading else 0), n_items % cols)
            elif k == "split":
                if 0.0 < factor < 1.0 and len(children) > 1:
                    stretch = int(factor * 100) if i == 0 else int((1 - factor) * 100 / (len(children) - 1))
                else:
                    stretch = 1
                lay.addWidget(cw, max(1, stretch))
            elif k == "row":
                lay.addWidget(cw, 0 if cw.maximumWidth() < 400 else 1)
            else:
                lay.addWidget(cw)
            n_items += 1
        if n_items == 0 and not heading:
            return None
        if split_heading:
            # Blender puts a heading into the label column of the first row ("Show In  ☑ Viewports")
            placed = False
            if k == "column" and first_child is not None:
                lab = first_child.findChild(QtWidgets.QLabel, "qtshell_split_label")
                if lab is not None and not lab.text():
                    lab.setText(heading)
                    placed = True
            if not placed:
                w = rw.labeled_row(heading, w, True)
        if not f.get("enabled", True):
            w.setEnabled(False)
        if not f.get("active", True):
            _dim(w)
        return w

    def _layout_panel(self, node):
        header, body = (node.children + [None, None])[:2]
        title = ""
        hw = None
        if header is not None:
            labels = [c for c in header.children if c.kind == "label"]
            if labels and len(header.children) == 1:
                title = labels[0].args.get("text", "")
            else:
                hw = self.build(header, "row")
        key = "lp:" + node.args.get("idname", "")
        p = CollapsiblePanel(title, key, self.state, node.args.get("default_closed", False), hw, flat=True)
        if body is not None:
            bw = self.build(body)
            if bw is not None:
                p.body_lay.addWidget(bw)
        return p

    # --- items
    def _item(self, node, parent_kind):
        k = node.kind
        a = node.args
        f = node.flags
        w = None
        if k == "label":
            text = a.get("text", "")
            w = QtWidgets.QLabel(text)
            w.setWordWrap(len(text) > 60)
            if f.get("alert"):
                w.setStyleSheet("color:#ff6060;")
        elif k == "prop":
            w = self._prop(node, parent_kind)
        elif k == "prop_enum":
            b = EnumValueButton(a["data"], a["prop"], a["value"], a.get("text"), self.on_change)
            self.bindings.append(b)
            w = b.widget
        elif k == "prop_search":
            b, label = rw.make_binding(a["data"], a["prop"], text=a.get("text"), on_change=self.on_change,
                                       search=(a["search_data"], a["search_prop"]))
            if b is not None:
                self.bindings.append(b)
                w = self._wrap_label(b.widget, label, f, parent_kind)
        elif k == "operator":
            w = self._operator_button(node)
        elif k == "operator_enum":
            w = QtWidgets.QWidget()
            lay = QtWidgets.QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(1)
            rp = op_rna_props(a["idname"]).get(a["prop"])
            for e in (rp.enum_items if rp else []):
                b = QtWidgets.QPushButton(tr(e.name))
                pytips.tag_op(b, a["idname"], {a["prop"]: e.identifier})
                b.clicked.connect(lambda _=False, i=e.identifier: run_op(a["idname"], {a["prop"]: i},
                                                                           f.get("ctx_ptrs")))
                lay.addWidget(b)
        elif k == "operator_menu_enum":
            btn = QtWidgets.QToolButton()
            btn.setText((a.get("text") or op_label(a["idname"])) + " ▾")
            btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            m = QtWidgets.QMenu(btn)
            fill_operator_enum_menu(m, a["idname"], a["prop"], a.get("props"), f.get("ctx_ptrs"))
            btn.setMenu(m)
            w = btn
        elif k == "menu":
            btn = QtWidgets.QToolButton()
            cls = fake_ui.find_menu_class(a["menu"])
            text = a.get("text")
            if text is None:
                text = tr(getattr(cls, "bl_label", a["menu"])) if cls else a["menu"]
            btn.setText((text or "") + " ▾")
            btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            btn.setMenu(LazyMenu(a["menu"], btn))
            if blicons.has(a.get("icon")):
                btn.setIcon(blicons.icon(a["icon"]))
                btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            pytips.tag(btn, f'bpy.ops.wm.call_menu(name="{a["menu"]}")')
            w = btn
        elif k == "popover":
            btn = QtWidgets.QToolButton()
            cls = fake_ui.find_panel_class(a["panel"])
            text = a.get("text") or (tr(getattr(cls, "bl_label", "")) if cls else a["panel"])
            btn.setText((text or "") + " ▾")
            btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            btn.setMenu(PopoverMenu(a["panel"], btn, self.on_change))
            if blicons.has(a.get("icon")):
                btn.setIcon(blicons.icon(a["icon"]))
                btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            pytips.tag(btn, f'bpy.ops.wm.call_panel(name="{a["panel"]}")')
            w = btn
        elif k == "template_list":
            try:
                b = TemplateListBinding(a["data"], a["prop"], a["active_data"], a["active_prop"],
                                        a.get("rows", 5), self.on_change)
                self.bindings.append(b)
                w = b.widget
            except Exception:
                w = None
        elif k == "template_id":
            b = TemplateIDBinding(a["data"], a["prop"], a.get("new"), a.get("unlink"), self.on_change)
            self.bindings.append(b)
            w = b.widget
            if a.get("text"):
                w = rw.labeled_row(a["text"], w, f.get("use_property_split", False))
        elif k == "node_view":
            w = self._node_view(a["ntree"], a["node"], a["socket"])
        elif k == "struct":
            if a.get("data") is not None:
                w, binds = rw.rna_form(a["data"], self.on_change)
                self.bindings.extend(binds)
        elif k == "unsupported":
            name = a.get("name", "")
            if name in SILENT_UNSUPPORTED:
                return None
            w = QtWidgets.QLabel(f"‹{name}›")
            w.setProperty("dim", True)
            w.setToolTip("Qt Shell cannot display this Blender UI element yet.")
        if w is None:
            return None
        if not f.get("enabled", True):
            w.setEnabled(False)
        if not f.get("active", True):
            _dim(w)
        return w

    def _wrap_label(self, widget, label, flags, parent_kind):
        split = flags.get("use_property_split", False)
        if not label:
            return widget
        if split:
            return rw.labeled_row(label, widget, True)
        return rw.labeled_row(label, widget, False)

    def _prop(self, node, parent_kind):
        a = node.args
        f = node.flags
        data, pid = a["data"], a["prop"]
        rp = rw.rna_prop(data, pid)
        if rp is None:
            return None
        b, label = rw.make_binding(data, pid, text=a.get("text"), expand=a.get("expand", False),
                                   toggle=a.get("toggle", -1), index=a.get("index", -1),
                                   invert=a.get("invert", False), on_change=self.on_change)
        if b is None:
            return None
        self.bindings.append(b)
        if a.get("icon_only") and isinstance(b, rw.BoolBinding):
            label = ""
        if blicons.has(a.get("icon")) and isinstance(getattr(b, "widget", None), QtWidgets.QAbstractButton):
            b.widget.setIcon(blicons.icon(a["icon"]))
        split = f.get("use_property_split", False) and bool(label)
        if isinstance(b, rw.BoolBinding):
            if label:
                b.widget.setText(label)
            if split and isinstance(b.widget, QtWidgets.QCheckBox):
                # like Blender: the label column stays empty (or gets the column heading),
                # the checkbox carries its own text in the value column
                return rw.labeled_row("", b.widget, True)
            return b.widget
        if isinstance(b, rw.NumberBinding) and not split:
            if label:
                b.widget.setPrefix(label + ": ")
            return b.widget
        if isinstance(b, rw.VectorBinding) and not split and label:
            w = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(1)
            lab = QtWidgets.QLabel(label + ":")
            lab.setToolTip(b.widget.toolTip())
            lay.addWidget(lab)
            lay.addWidget(b.widget)
            return w
        if isinstance(b, rw.EnumBinding) and b.expand and not split:
            return b.widget
        return self._wrap_label(b.widget, label, f, parent_kind)

    def _operator_button(self, node):
        a = node.args
        f = node.flags
        idname = a["idname"]
        text = a.get("text")
        label = op_label(idname)
        btn = QtWidgets.QPushButton(_glyph(a.get("icon"), text if text is not None else label))
        if blicons.has(a.get("icon")):
            btn.setIcon(blicons.icon(a["icon"]))
            if text == "":
                btn.setText("")
        desc = _op_desc(idname)
        btn.setToolTip(f"{label}\n{desc}" if desc and desc != label else label)
        pytips.tag_op(btn, idname, a.get("props") or {})
        if a.get("depress"):
            btn.setCheckable(True)
            btn.setChecked(True)
        props = a.get("props") or {}
        ctx = f.get("ctx_ptrs")
        btn.setEnabled(op_poll(idname, ctx))
        btn.clicked.connect(lambda: (run_op(idname, dict(props), ctx), self.on_change and self.on_change(None, idname)))
        if text == "" or (text is None and a.get("icon") in ICON_GLYPHS and len(label) > 18):
            btn.setMaximumWidth(theme.px(34))
        return btn

    # --- node view (materials, world)
    _BASE_NODE_PROPS = None

    def _node_view(self, ntree, node, socket, depth=0):
        if Builder._BASE_NODE_PROPS is None:
            Builder._BASE_NODE_PROPS = set(bpy.types.ShaderNode.bl_rna.properties.keys()) | {"rna_type"}
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(8 if depth else 0, 0, 0, 0)
        lay.setSpacing(2)
        if socket is None:
            return None
        if socket.is_linked and socket.links:
            src = socket.links[0].from_node
            head = QtWidgets.QLabel(f"<b>{tr(socket.name)}</b>: {src.name}")
            lay.addWidget(head)
            for p in src.bl_rna.properties:
                if p.identifier in Builder._BASE_NODE_PROPS or p.is_readonly:
                    continue
                if p.type == "ENUM" or (p.type == "POINTER" and p.fixed_type is not None
                                        and rw.is_id_type(p.fixed_type)):
                    b, label = rw.make_binding(src, p.identifier, on_change=self.on_change)
                    if b is not None:
                        self.bindings.append(b)
                        lay.addWidget(rw.labeled_row(label, b.widget))
            for inp in src.inputs:
                if not getattr(inp, "enabled", True) or getattr(inp, "hide", False):
                    continue
                if inp.is_linked:
                    if depth < 3:
                        sub = self._node_view(ntree, src, inp, depth + 1)
                        if sub is not None:
                            lay.addWidget(sub)
                    continue
                if getattr(inp, "hide_value", False) or not hasattr(inp, "default_value"):
                    continue
                b, label = rw.make_binding(inp, "default_value", text=tr(inp.name), on_change=self.on_change)
                if b is not None:
                    self.bindings.append(b)
                    lay.addWidget(rw.labeled_row(label, b.widget))
        elif hasattr(socket, "default_value"):
            b, label = rw.make_binding(socket, "default_value", text=tr(socket.name), on_change=self.on_change)
            if b is not None:
                self.bindings.append(b)
                lay.addWidget(rw.labeled_row(label, b.widget))
        else:
            lay.addWidget(QtWidgets.QLabel(f"{tr(socket.name)}: —"))
        return w


def _op_desc(idname):
    try:
        mod, name = idname.split(".", 1)
        return getattr(getattr(bpy.ops, mod), name).get_rna_type().description or ""
    except Exception:
        return ""


def _dim(w):
    """Inactive element (layout.active = False): only dimmed text, still editable."""
    w.setStyleSheet(w.styleSheet() + "color:#8a8a8a;")


# ---------------------------------------------------------------- menu
def fill_operator_enum_menu(menu, idname, prop, base_props=None, ctx=None):
    rp = op_rna_props(idname).get(prop)
    items = list(rp.enum_items) if rp else []
    if not items:
        act = menu.addAction("—")
        act.setEnabled(False)
        return
    for e in items:
        act = menu.addAction(tr(e.name))
        if blicons.has(getattr(e, "icon", None)):
            act.setIcon(blicons.icon(e.icon))
        act.setToolTip(e.description)
        props = dict(base_props or {})
        props[prop] = e.identifier
        pytips.tag_op(act, idname, props)
        act.triggered.connect(lambda _=False, p=props: run_op(idname, p, ctx))


# operators Qt Shell runs itself (main_window.special_op) – Blender's poll would test its hidden 3D view
QT_HANDLED_OPS = {"view3d.view_center_camera", "view3d.zoom_camera_1_to_1"}


def fill_menu(menu, node):
    """Fills a QMenu from the recorded tree of a Blender menu."""
    _fill(menu, node, top=True)
    # remove trailing separators
    acts = menu.actions()
    while acts and acts[-1].isSeparator():
        menu.removeAction(acts.pop())


def _fill(menu, node, top=False):
    k = node.kind
    a = node.args
    f = node.flags
    if k in ("column", "row", "box", "split", "flow", "lpanel"):
        for i, ch in enumerate(node.children):
            if k == "split" and i > 0:
                menu.addSeparator()
            _fill(menu, ch)
        return
    enabled = f.get("enabled", True)
    act = None
    if k == "separator":
        if menu.actions() and not menu.actions()[-1].isSeparator():
            menu.addSeparator()
    elif k == "label":
        if a.get("text"):
            act = menu.addAction(a["text"])
            f2 = act.font()
            f2.setBold(True)
            act.setFont(f2)
            act.setEnabled(False)
    elif k == "operator":
        idname = a["idname"]
        text = a.get("text")
        act = menu.addAction(text if text else op_label(idname))
        if blicons.has(a.get("icon")):
            act.setIcon(blicons.icon(a["icon"]))
        props = dict(a.get("props") or {})
        pytips.tag_op(act, idname, props)
        ctx = f.get("ctx_ptrs")
        act.triggered.connect(lambda _=False: run_op(idname, dict(props), ctx))
        if idname not in QT_HANDLED_OPS and not op_poll(idname, ctx):
            act.setEnabled(False)
    elif k == "operator_enum":
        fill_operator_enum_menu(menu, a["idname"], a["prop"], None, f.get("ctx_ptrs"))
    elif k == "operator_menu_enum":
        sub = menu.addMenu(a.get("text") or op_label(a["idname"]))
        if blicons.has(a.get("icon")):
            sub.setIcon(blicons.icon(a["icon"]))
        fill_operator_enum_menu(sub, a["idname"], a["prop"], a.get("props"), f.get("ctx_ptrs"))
    elif k == "menu":
        cls = fake_ui.find_menu_class(a["menu"])
        if a["menu"] in QT_MENUS:          # filled by Qt (Blender defines some of these in C only)
            if cls is not None and not fake_ui.safe_poll(cls, bpy.context):
                return
            text = a.get("text") or tr(getattr(cls, "bl_label", None) or QT_MENU_LABELS.get(a["menu"], a["menu"]))
        else:
            if cls is None or not fake_ui.safe_poll(cls, bpy.context):
                return
            text = a.get("text") or tr(getattr(cls, "bl_label", a["menu"]))
        sub = LazyMenu(a["menu"], menu, title=text)
        if blicons.has(a.get("icon")):
            sub.setIcon(blicons.icon(a["icon"]))
        menu.addMenu(sub)
        pytips.tag(sub.menuAction(), f'bpy.ops.wm.call_menu(name="{a["menu"]}")')
    elif k == "prop":
        data, pid = a["data"], a["prop"]
        rp = rw.rna_prop(data, pid)
        if rp is None:
            return
        label = a.get("text") if a.get("text") else tr(rp.name)
        if rp.type == "BOOLEAN" and not getattr(rp, "array_length", 0):
            act = menu.addAction(label)
            pytips.tag_prop(act, data, pid)
            act.setCheckable(True)
            act.setChecked(bool(getattr(data, pid)))
            act.toggled.connect(lambda on, d=data, p=pid: _set_quiet(d, p, on))
        elif rp.type == "ENUM":
            target = menu if a.get("expand") else menu.addMenu(label)
            grp = QtGui.QActionGroup(target)
            cur = getattr(data, pid)
            for ident, name, _desc in rw.enum_items(data, pid):
                ea = target.addAction(name)
                pytips.tag(ea, f"{pytips.prop_text(data, pid)} = {ident!r}")
                ea.setCheckable(True)
                ea.setChecked(ident == cur or (isinstance(cur, set) and ident in cur))
                if not rp.is_enum_flag:
                    grp.addAction(ea)
                ea.triggered.connect(lambda _=False, d=data, p=pid, v=ident: _set_quiet(d, p, v))
    elif k == "prop_enum":
        data, pid, value = a["data"], a["prop"], a["value"]
        act = menu.addAction(a.get("text") or value)
        pytips.tag(act, f"{pytips.prop_text(data, pid)} = {value!r}")
        act.setCheckable(True)
        act.setChecked(getattr(data, pid) == value)
        act.triggered.connect(lambda _=False: _set_quiet(data, pid, value))
    elif k == "popover":
        sub = PopoverMenu(a["panel"], menu)
        cls = fake_ui.find_panel_class(a["panel"])
        sub.setTitle(a.get("text") or (tr(getattr(cls, "bl_label", "")) if cls else a["panel"]))
        menu.addMenu(sub)
    if act is not None and not enabled:
        act.setEnabled(False)


def _set_quiet(data, pid, value):
    try:
        setattr(data, pid, value)
    except Exception as ex:
        from .bridge import log
        log(f"{pid}: {ex}", "ERROR")


class LazyMenu(QtWidgets.QMenu):
    """QMenu that is regenerated from a Blender Menu class every time it opens."""

    def __init__(self, menu_id, parent=None, title=None, resolver=None):
        super().__init__(parent)
        self.menu_id = menu_id
        self.resolver = resolver  # fn() -> menu_id (e.g. depending on the mode)
        if title:
            self.setTitle(title)
        self.aboutToShow.connect(self._populate)

    def _populate(self):
        self.clear()
        for child in self.findChildren(QtWidgets.QMenu, options=QtCore.Qt.FindDirectChildrenOnly):
            child.deleteLater()
        mid = self.resolver() if self.resolver else self.menu_id
        if mid in QT_MENUS:                 # menus Blender draws in C – filled by Qt
            QT_MENUS[mid](self)
            return
        node, _label = fake_ui.record_menu(mid)
        if node is None:
            act = self.addAction("—")
            act.setEnabled(False)
        else:
            fill_menu(self, node)
        try:
            from . import api
            api.extend_menu(self)    # items added by add-ons through qt_shell.api
        except Exception:
            pass


def fill_recent_menu(menu, limit=20):
    """File → Open Recent (like Maya's Recent Files): numbered list of recently opened / saved files,
    newest first; missing files are greyed out; Clear Recent Files List at the bottom."""
    import os
    from . import bridge
    menu.setToolTipsVisible(True)
    files = bridge.recent_list(limit)
    if not files:
        act = menu.addAction("No recent files")
        act.setEnabled(False)
    fm = menu.fontMetrics()
    names = [os.path.basename(p) for p in files]
    for i, path in enumerate(files):
        name = names[i]
        folder = os.path.dirname(path)
        # same file name in several folders → show the folder too
        label = name if names.count(name) == 1 else f"{name}  ({os.path.basename(folder)})"
        label = fm.elidedText(label, QtCore.Qt.ElideMiddle, theme.px(420))
        prefix = f"&{i + 1}  " if i < 9 else ("1&0  " if i == 9 else f"{i + 1}  ")
        act = menu.addAction(prefix + label)
        act.setToolTip(path)
        act.setStatusTip(path)
        if blicons.has("FILE_BLEND"):
            act.setIcon(blicons.icon("FILE_BLEND"))
        if not os.path.exists(path):
            act.setEnabled(False)
            act.setToolTip(path + "\n(file not found)")
        act.triggered.connect(lambda _=False, p=path: run_op("wm.open_mainfile", {"filepath": p}))
    menu.addSeparator()
    clear = menu.addAction("Clear Recent Files List")
    clear.setEnabled(bool(files))
    clear.triggered.connect(lambda: bridge.clear_recent())


QT_MENUS = {"TOPBAR_MT_file_open_recent": fill_recent_menu}
QT_MENU_LABELS = {"TOPBAR_MT_file_open_recent": "Open Recent"}


class PopoverMenu(QtWidgets.QMenu):
    """Blender popover panel shown as a widget inside a QMenu."""

    _open_state = {}           # sub-panel open / closed, shared by all popovers (like Blender remembers it)

    def __init__(self, panel_id, parent=None, on_change=None):
        super().__init__(parent)
        self.panel_id = panel_id
        self.on_change = on_change
        self.aboutToShow.connect(self._populate)

    def _add_children(self, builder, parent_cls, lay, depth=0):
        """Sub-panels (bl_parent_id) as collapsible sections – e.g. Overlays: Guides, Objects, Geometry …"""
        for ch in fake_ui.child_panels(fake_ui.class_id(parent_cls)):
            rec = fake_ui.record_panel(ch, bpy.context)
            if rec is None:
                continue
            header, body = rec
            hw = builder.build(header) if header is not None and header.children else None
            closed = "DEFAULT_CLOSED" in getattr(ch, "bl_options", set())
            key = fake_ui.class_id(ch)
            title = "" if "HIDE_HEADER" in getattr(ch, "bl_options", set()) or hw is not None else \
                tr(getattr(ch, "bl_label", ""))       # a header with its own widgets names itself
            panel = CollapsiblePanel(title, key, PopoverMenu._open_state, closed, hw, flat=True)
            panel.btn.toggled.connect(lambda _on: QtCore.QTimer.singleShot(0, self.adjustSize))
            bw = builder.build(body)
            if bw is not None:
                panel.body_lay.addWidget(bw)
            self._add_children(builder, ch, panel.body_lay, depth + 1)
            lay.addWidget(panel)

    def _populate(self):
        self.clear()
        cls = fake_ui.find_panel_class(self.panel_id)
        if cls is None:
            return
        rec = fake_ui.record_panel(cls, bpy.context)
        if rec is None:
            return
        _header, body = rec
        builder = Builder(self.on_change)
        self._builder = builder                 # keeps the bindings alive while the popover is open
        box = QtWidgets.QWidget(self)
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.px(2))
        w = builder.build(body)
        if w is not None:
            lay.addWidget(w)
        try:
            self._add_children(builder, cls, lay)
        except Exception as ex:
            from . import bridge
            bridge.log(f"Popover {self.panel_id}: {ex}", "WARNING")
        if lay.count() == 0:
            return
        box.setMinimumWidth(theme.px(260))
        widget = box
        scr = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) or QtGui.QGuiApplication.primaryScreen()
        max_h = int(scr.availableGeometry().height() * 0.85)
        if box.sizeHint().height() > max_h:       # long popovers (Overlays) scroll instead of leaving the screen
            sa = QtWidgets.QScrollArea(self)
            sa.setWidget(box)
            sa.setWidgetResizable(True)
            sa.setFrameShape(QtWidgets.QFrame.NoFrame)
            sa.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            sa.setMinimumWidth(box.sizeHint().width() + sa.verticalScrollBar().sizeHint().width() + 4)
            sa.setFixedHeight(max_h)
            widget = sa
        wa = QtWidgets.QWidgetAction(self)
        wa.setDefaultWidget(widget)
        self.addAction(wa)

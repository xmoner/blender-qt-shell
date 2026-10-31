"""Properties editor in Qt.

Most tabs are generated from Blender's original Python panels (bl_ui + add-ons)
via fake_ui → qt_ui. Modifiers and constraints (drawn in C in Blender) have their own Qt version.
"""
import re

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, fake_ui, qt_ui, rna_widgets as rw, theme
from . import blicons
from .bridge import tr

TABS = [
    ("render", "Render"), ("output", "Output"), ("view_layer", "View Layer"), ("scene", "Scene"),
    ("world", "World"), ("collection", "Collection"), ("object", "Object"), ("modifier", "Modifiers"),
    ("particle", "Particles"), ("physics", "Physics"), ("constraint", "Constraints"), ("data", "Data"),
    ("bone", "Bone"), ("material", "Material"), ("texture", "Texture"),
]
MATERIAL_TYPES = {"MESH", "CURVE", "SURFACE", "FONT", "META", "VOLUME", "POINTCLOUD", "CURVES",
                  "GREASEPENCIL", "GPENCIL"}


class UndoDebouncer(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self._t = QtCore.QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(400)
        self._t.timeout.connect(self._push)
        self._msg = "Change Property"

    def __call__(self, data=None, prop=None):
        if prop:
            self._msg = f"Change {prop}"
        if data is None and prop and "." in str(prop):
            return  # the operator pushes undo itself
        self._t.start()

    def _push(self):
        bridge.undo_push(self._msg)


class PanelPage(QtWidgets.QScrollArea):
    """One tab built from Blender panels."""

    def __init__(self, ctx_name, on_change, state):
        super().__init__()
        self.ctx_name = ctx_name
        self.on_change = on_change
        self.state = state
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.builders = []
        self._sig = None

    def record(self):
        ctx = fake_ui.properties_context(self.ctx_name)
        out = []

        def rec(tree):
            res = []
            for cls, children in tree:
                r = fake_ui.record_panel(cls, ctx)
                if r is None:
                    continue
                res.append((cls, r[0], r[1], rec(children)))
            return res
        out = rec(fake_ui.properties_panels(self.ctx_name))
        return out

    @staticmethod
    def signature(recorded):
        parts = []
        for cls, header, body, children in recorded:
            parts.append(cls.__name__)
            parts.append(header.signature() if header else "")
            parts.append(body.signature())
            parts.append(PanelPage.signature(children))
        return "|".join(parts)

    def refresh(self, force=False):
        try:
            recorded = self.record()
        except Exception as ex:
            bridge.log(f"Properties/{self.ctx_name}: {ex}", "ERROR")
            return
        sig = self.signature(recorded)
        if force or sig != self._sig:
            self._sig = sig
            self._build(recorded)
        else:
            ok = all(b.refresh() for b in self.builders)
            if not ok:
                self._sig = None

    def _build(self, recorded):
        """Builds the whole page into a new widget and only then swaps it in, together with its
        bindings. (A half-built page used to leave old widgets on screen whose bindings were already
        gone – their checkboxes toggled but changed nothing.)"""
        scroll = self.verticalScrollBar().value()
        builders = []
        host = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(host)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        self._add_panels(lay, recorded, builders)
        lay.addStretch(1)
        self.builders = builders
        self.setWidget(host)
        QtCore.QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(scroll))

    def _add_panels(self, lay, recorded, builders):
        for cls, header, body, children in recorded:
            try:
                self._add_panel(lay, cls, header, body, children, builders)
            except Exception as ex:
                # one broken panel must not take the whole tab down
                bridge.log(f"Panel {cls.__name__}: {ex}", "ERROR")
                err = QtWidgets.QLabel(f"⚠ {tr(getattr(cls, 'bl_label', cls.__name__))}: {ex}")
                err.setWordWrap(True)
                err.setStyleSheet("color:#ff8080;")
                lay.addWidget(err)

    def _add_panel(self, lay, cls, header, body, children, builders):
        b = qt_ui.Builder(self.on_change, self.state)
        builders.append(b)
        opts = getattr(cls, "bl_options", set()) or set()
        hw = b.build(header, "row") if header is not None else None
        if "HIDE_HEADER" in opts:
            w = b.build(body)
            if w is not None:
                lay.addWidget(w)
            return
        title = tr(getattr(cls, "bl_label", cls.__name__))
        panel = qt_ui.CollapsiblePanel(title, fake_ui.class_id(cls), self.state,
                                       "DEFAULT_CLOSED" in opts, hw)
        w = b.build(body)
        if w is not None:
            panel.body_lay.addWidget(w)
        if children:
            self._add_panels(panel.body_lay, children, builders)
        lay.addWidget(panel)


class StackPage(QtWidgets.QScrollArea):
    """Modifiers or constraints (stack with adding, reordering, applying)."""

    def __init__(self, kind, on_change, state):
        super().__init__()
        self.kind = kind  # "modifier" | "constraint"
        self.on_change = on_change
        self.state = state
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.bindings = []
        self._sig = None

    def _stack(self, ob):
        return ob.modifiers if self.kind == "modifier" else ob.constraints

    def refresh(self, force=False):
        btn = getattr(self, "_add_btn", None)
        try:
            if btn is not None and btn.menu() is not None and btn.menu().isVisible():
                return      # a rebuild now would delete the open Add menu under the cursor
        except RuntimeError:
            pass
        ob = bpy.context.view_layer.objects.active
        try:
            sig = (ob.name if ob else None,
                   tuple((m.name, m.type, m.show_expanded,
                          getattr(m, "node_group", None) and m.node_group.name)
                         for m in self._stack(ob)) if ob else ())
        except Exception:
            sig = None
        if force or sig != self._sig:
            self._sig = sig
            self._build(ob)
        else:
            for b in self.bindings:
                try:
                    b.refresh()
                except Exception:
                    self._sig = None

    def _build(self, ob):
        scroll = self.verticalScrollBar().value()
        self.bindings = []
        host = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(host)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        if ob is None:
            lay.addWidget(QtWidgets.QLabel("No active object."))
            lay.addStretch(1)
            self.setWidget(host)
            return
        add = QtWidgets.QToolButton(host)
        self._add_btn = add
        add.setText("+ " + (tr("Add Modifier") if self.kind == "modifier" else tr("Add Object Constraint")))
        add.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        if self.kind == "modifier" and fake_ui.find_menu_class("OBJECT_MT_modifier_add") is not None:
            add.setMenu(qt_ui.LazyMenu("OBJECT_MT_modifier_add", add))
        else:
            add.setMenu(self._add_menu(ob, add))
        add.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        lay.addWidget(add)
        stack = self._stack(ob)
        for i, item in enumerate(stack):
            lay.addWidget(self._item_widget(ob, item, i, len(stack)))
        lay.addStretch(1)
        self.setWidget(host)
        QtCore.QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(scroll))

    def _add_menu(self, ob, parent):
        base = bpy.types.Modifier if self.kind == "modifier" else bpy.types.Constraint
        m = QtWidgets.QMenu(parent)
        for e in base.bl_rna.properties["type"].enum_items:
            a = m.addAction(tr(e.name))
            a.setToolTip(e.description)
            if e.icon and e.icon != "NONE" and blicons.has(e.icon):
                a.setIcon(blicons.icon(e.icon))
            a.triggered.connect(lambda _=False, ident=e.identifier, name=e.name: self._add(ob, ident, name))
        return m

    def _add(self, ob, ident, name):
        try:
            if self.kind == "modifier":
                ob.modifiers.new(name=name, type=ident)
            else:
                ob.constraints.new(type=ident)
        except Exception as ex:
            bridge.log(str(ex), "ERROR")
            return
        bridge.undo_push(f"Add {name}")
        self.refresh(force=True)

    def _item_widget(self, ob, item, index, count):
        head = QtWidgets.QWidget()
        hl = QtWidgets.QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(2)
        name = QtWidgets.QLineEdit(item.name)
        name.editingFinished.connect(lambda: self._rename(item, name.text()))
        hl.addWidget(name, 1)
        for prop, txt, tip in (("show_viewport", "👁", "Viewport"), ("show_render", "◉", "Render")) \
                if self.kind == "modifier" else (("enabled", "👁", "Enabled"),):
            if hasattr(item, prop):
                b = rw.BoolBinding(item, prop, txt, 1, False, self.on_change)
                b.widget.setStyleSheet("padding:2px;")
                b.widget.setToolTip(tr(tip))
                b.widget.setMaximumWidth(theme.px(30))
                self.bindings.append(b)
                hl.addWidget(b.widget)
        for txt, tip, fn, en in (("▲", "Move Up", lambda: self._move(ob, index, -1), index > 0),
                                 ("▼", "Move Down", lambda: self._move(ob, index, +1), index < count - 1),
                                 ("✓", "Apply", lambda: self._apply(ob, item), True),
                                 ("✕", "Remove", lambda: self._remove(ob, item), True)):
            b = QtWidgets.QToolButton()
            b.setText(txt)
            b.setToolTip(tip)
            b.setEnabled(en)
            b.setStyleSheet("padding:2px 4px;")
            b.clicked.connect(fn)
            hl.addWidget(b)
        key = f"{self.kind}:{ob.name}:{item.name}"
        panel = qt_ui.CollapsiblePanel("", key, self.state, False, head)
        name.setToolTip(tr(item.bl_rna.name))
        form, binds = rw.rna_form(item, self.on_change)
        self.bindings.extend(binds)
        panel.body_lay.addWidget(form)
        if self.kind == "modifier" and item.type == "NODES":
            panel.body_lay.addWidget(self._geonodes_inputs(ob, item))
        return panel

    def _geonodes_inputs(self, ob, mod):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        ng = mod.node_group
        if ng is None:
            return w
        try:
            items = [it for it in ng.interface.items_tree
                     if it.item_type == "SOCKET" and it.in_out == "INPUT"]
        except Exception:
            items = []
        for it in items:
            ident = it.identifier
            if ident not in mod.keys():
                continue
            val = mod[ident]
            if isinstance(val, bool):
                ed = QtWidgets.QCheckBox()
                ed.setChecked(val)
                ed.toggled.connect(lambda v, i=ident: self._set_idprop(ob, mod, i, bool(v)))
            elif isinstance(val, int):
                ed = rw.DragSpin(True)
                ed.setRange(-2**31, 2**31 - 1)
                ed.setValue(val)
                ed.valueChanged.connect(lambda v, i=ident: self._set_idprop(ob, mod, i, int(v)))
            elif isinstance(val, float):
                ed = rw.DragSpin(False)
                ed.setRange(-1e9, 1e9)
                ed.setDecimals(3)
                ed.setValue(val)
                ed.valueChanged.connect(lambda v, i=ident: self._set_idprop(ob, mod, i, float(v)))
            elif hasattr(val, "__len__") and not isinstance(val, str) and len(val) in (2, 3, 4):
                ed = QtWidgets.QWidget()
                hl = QtWidgets.QHBoxLayout(ed)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.setSpacing(1)
                for k in range(len(val)):
                    s = rw.DragSpin(False)
                    s.setRange(-1e9, 1e9)
                    s.setDecimals(3)
                    s.setValue(float(val[k]))
                    s.valueChanged.connect(lambda v, i=ident, k=k: self._set_idprop_index(ob, mod, i, k, v))
                    hl.addWidget(s)
            else:
                ed = QtWidgets.QLabel(str(type(val).__name__))
                ed.setProperty("dim", True)
            lay.addWidget(rw.labeled_row(it.name, ed))
        return w

    def _set_idprop(self, ob, mod, ident, value):
        try:
            mod[ident] = value
            ob.update_tag()
            self.on_change(mod, ident)
        except Exception as ex:
            bridge.log(str(ex), "ERROR")

    def _set_idprop_index(self, ob, mod, ident, k, value):
        try:
            arr = list(mod[ident])
            arr[k] = value
            mod[ident] = arr
            ob.update_tag()
            self.on_change(mod, ident)
        except Exception as ex:
            bridge.log(str(ex), "ERROR")

    def _rename(self, item, text):
        if text and text != item.name:
            item.name = text
            bridge.undo_push("Rename")
            self.refresh(force=True)

    def _move(self, ob, index, delta):
        try:
            self._stack(ob).move(index, index + delta)
        except Exception as ex:
            bridge.log(str(ex), "ERROR")
            return
        bridge.undo_push("Move")
        self.refresh(force=True)

    def _apply(self, ob, item):
        if self.kind == "modifier":
            bridge.run_op("object.modifier_apply", {"modifier": item.name}, {"object": ob, "active_object": ob})
        else:
            bridge.run_op("constraint.apply", {"constraint": item.name, "owner": "OBJECT"},
                          {"object": ob, "active_object": ob})
        self.refresh(force=True)

    def _remove(self, ob, item):
        try:
            self._stack(ob).remove(item)
        except Exception as ex:
            bridge.log(str(ex), "ERROR")
            return
        bridge.undo_push("Remove")
        self.refresh(force=True)


class TabColumn(QtWidgets.QWidget):
    """Vertical column of tabs + QStackedWidget (replacement for QTabWidget with the API we use)."""
    currentChanged = QtCore.Signal(int)

    WIDTH_KEY = "properties/tab_width"

    def __init__(self):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        # the tab column and the page are in a splitter: drag the border to make the names fit;
        # when the column is narrower than a name (or the dock is short) scroll bars appear
        self.split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(theme.px(4))
        self.nav = QtWidgets.QListWidget(self.split)
        self.nav.setMinimumWidth(theme.px(34))            # icons only
        self.nav.setTextElideMode(QtCore.Qt.ElideNone)    # full names – scroll instead of "Constrai…"
        self.nav.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.nav.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.nav.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.nav.setStyleSheet("QListWidget{background:#232323;} "
                               f"QListWidget::item{{padding:{theme.px(5)}px {theme.px(4)}px;}}")
        self.nav.setToolTip("Drag the border on the right to make the names fit")
        self.stack = QtWidgets.QStackedWidget(self.split)
        self.split.addWidget(self.nav)
        self.split.addWidget(self.stack)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        lay.addWidget(self.split)
        self._want = None                 # wanted width of the tab column (px), None = fit the names
        self._applying = False
        self.split.splitterMoved.connect(self._moved)
        self.nav.currentRowChanged.connect(self._row)

    def _fit_width(self):
        """Width that shows the longest name (icon + text + padding + a possible scroll bar)."""
        fm = self.nav.fontMetrics()
        names = [self.nav.item(i).text() for i in range(self.nav.count())]
        text = max((fm.horizontalAdvance(t) for t in names), default=theme.px(60))
        return text + self.nav.iconSize().width() + theme.px(30) + self.nav.verticalScrollBar().sizeHint().width()

    def _wanted(self):
        if self._want is None:
            try:
                v = float(QtCore.QSettings("QtShell", "QtShell").value(self.WIDTH_KEY, 0) or 0)
            except (TypeError, ValueError):
                v = 0
            self._want = theme.px(v) if v > 0 else min(self._fit_width(), theme.px(150))
        return self._want

    def _apply_width(self):
        """Keeps the tab column at its width when the panel is resized (the page gets the rest)."""
        total = sum(self.split.sizes())
        if total <= 0 or not self.nav.count():
            return
        w = max(self.nav.minimumWidth(), min(self._wanted(), total - theme.px(80)))
        if self.split.sizes()[0] != w:
            self._applying = True
            try:
                self.split.setSizes([w, max(1, total - w)])
            finally:
                self._applying = False

    def _moved(self, *_a):
        """The user dragged the border: remember the width (for all Properties panels)."""
        if self._applying:
            return
        w = self.split.sizes()[0]
        if w > 0:
            self._want = w
            QtCore.QSettings("QtShell", "QtShell").setValue(self.WIDTH_KEY, round(w / theme.ui_scale, 1))

    def showEvent(self, ev):
        super().showEvent(ev)
        QtCore.QTimer.singleShot(0, self._apply_width)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._apply_width()

    def _row(self, row):
        if row >= 0:
            self.stack.setCurrentIndex(row)
            self.currentChanged.emit(row)

    def addTab(self, widget, label, icon=None):
        self.stack.addWidget(widget)
        self.nav.addItem(label)
        self.nav.item(self.nav.count() - 1).setToolTip(label)   # names are cut off in the narrow column
        if icon is not None and not icon.isNull():
            self.nav.item(self.nav.count() - 1).setIcon(icon)

    def clear(self):
        """Removes all tabs; the page widgets are kept (not deleted) so they can be added again."""
        self.nav.clear()
        while self.stack.count():
            self.stack.removeWidget(self.stack.widget(0))

    def count(self):
        return self.nav.count()

    def currentIndex(self):
        return max(0, self.nav.currentRow())

    def setCurrentIndex(self, i):
        self.nav.setCurrentRow(i)

    def setTabVisible(self, i, visible):
        self.nav.item(i).setHidden(not visible)

    def isTabVisible(self, i):
        return not self.nav.item(i).isHidden()


# ---------------------------------------------------------------- search (like Blender's Ctrl+F)
_HIT_STYLE = "color: #ffb347; font-weight: bold;"
_HIT_LABEL = "color: #ffb347; font-weight: bold;"


def _norm(text):
    """lower case, '&' removed, doubled letters collapsed (like Help → Search)."""
    return re.sub(r"(.)\1+", r"\1", (text or "").replace("&", "").lower())


def _widget_texts(w):
    """Texts a person sees on a widget (+ the name in its tooltip for icon-only buttons)."""
    out = []
    try:
        if isinstance(w, QtWidgets.QLabel):
            out.append(re.sub(r"<[^>]+>", "", w.text()))
        elif isinstance(w, QtWidgets.QAbstractButton):
            out.append(w.text())
        elif isinstance(w, QtWidgets.QComboBox):
            out.append(w.currentText())
        elif isinstance(w, QtWidgets.QAbstractSpinBox):
            out.append(getattr(w, "prefix", lambda: "")())
            out.append(w.specialValueText())
        elif isinstance(w, QtWidgets.QLineEdit):
            out.append(w.placeholderText())
        else:
            return out
        tip = (w.toolTip() or "").strip()
        if tip:
            out.append(re.sub(r"<[^>]+>", "", tip.splitlines()[0]))
    except RuntimeError:
        pass
    return [t for t in out if t]


class _Search:
    """Filters the built widgets of a page: panels without a match are hidden, panels with a match are
    opened (without changing their remembered state) and the matching widgets are highlighted."""

    def __init__(self, text):
        self.words = [_norm(w) for w in text.split()]

    def match(self, text):
        t = _norm(text)
        return bool(self.words) and all(w in t for w in self.words)

    def _own(self, panel):
        """Widgets that belong to this panel, not to a nested panel."""
        for d in panel.findChildren(QtWidgets.QWidget):
            p = d.parentWidget()
            while p is not None and p is not panel and not isinstance(p, qt_ui.CollapsiblePanel):
                p = p.parentWidget()
            if p is panel and not isinstance(d, qt_ui.CollapsiblePanel) and d is not getattr(panel, "btn", None):
                yield d

    def _nested(self, w):
        for d in w.findChildren(qt_ui.CollapsiblePanel):
            p = d.parentWidget()
            while p is not None and p is not w and not isinstance(p, qt_ui.CollapsiblePanel):
                p = p.parentWidget()
            if p is w:
                yield d

    def _hit(self, d):
        if not any(self.match(t) for t in _widget_texts(d)):
            return False
        # mark only text widgets – a style sheet on spin boxes / combo boxes changes their size and look
        if isinstance(d, QtWidgets.QLabel):
            d.setStyleSheet(_HIT_LABEL)
        elif isinstance(d, (QtWidgets.QCheckBox, QtWidgets.QRadioButton)):
            d.setStyleSheet(f"{type(d).__name__} {{ {_HIT_LABEL} }}")
        elif isinstance(d, QtWidgets.QAbstractButton) and d.text():
            d.setStyleSheet(f"{type(d).__name__} {{ color: #ffb347; }}")
        return True

    def block(self, w, show_all=False):
        """Filters one block (a panel or a plain widget); returns the number of matches in it."""
        if isinstance(w, qt_ui.CollapsiblePanel):
            title = self.match(w.btn.text())
            if title:
                w.btn.setStyleSheet(_HIT_STYLE)
            hits = sum(1 for d in self._own(w) if self._hit(d))
            sub = sum(self.block(c, show_all or title) for c in self._nested(w))
            n = hits + sub + (1 if title else 0)
            w.setVisible(bool(n) or show_all)
            if n:
                w.body.setVisible(True)          # opened for the search only (state unchanged)
            return n
        hits = sum(1 for d in list(self._own(w)) + [w] if self._hit(d))
        hits += sum(self.block(c, show_all) for c in self._nested(w))
        w.setVisible(bool(hits) or show_all)
        return hits

    def page(self, page):
        host = page.widget()
        if host is None or host.layout() is None:
            return 0
        n = 0
        lay = host.layout()
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if w is not None:
                n += self.block(w)
        # panels opened just now (closed ones never had a size) – lay the page out at once
        for pnl in host.findChildren(qt_ui.CollapsiblePanel):
            if pnl.layout() is not None:
                pnl.layout().activate()
        lay.activate()
        host.adjustSize()
        return n


class PropertiesEditor(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.state = {}
        self.undo = UndoDebouncer()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = TabColumn()
        self.pages = {}
        for key, label in TABS:
            if key in ("modifier", "constraint"):
                page = StackPage(key, self._changed, self.state)
            else:
                page = PanelPage(key, self._changed, self.state)
            self.pages[key] = page
            self.tabs.addTab(page, label, blicons.icon(blicons.TAB_ICONS.get(key, "")))
        self.tabs.setCurrentIndex([k for k, _ in TABS].index("object"))
        self.tabs.currentChanged.connect(lambda _i: self.refresh(force=True))
        # search (like Blender's Ctrl+F in the Properties editor): text, buttons, property names of all tabs
        self.search = QtWidgets.QLineEdit(self)
        self.search.setClearButtonEnabled(True)
        from . import keymap
        keymap.tip(self.search, "Search properties, buttons and texts of all tabs ({properties.search}) – "
                                "panels without a match are hidden, tabs without one are greyed out")
        keymap.tip(self.search, "Search… ({properties.search})", "setPlaceholderText")
        self.search.addAction(blicons.icon("VIEWZOOM"), QtWidgets.QLineEdit.LeadingPosition)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.search.installEventFilter(self)
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._run_search)
        self._search_counts = {}
        act = QtGui.QAction(self)
        act.setShortcutContext(QtCore.Qt.WidgetWithChildrenShortcut)
        act.triggered.connect(lambda: (self.search.setFocus(), self.search.selectAll()))
        keymap.bind_action(act, "properties.search")
        self.addAction(act)
        lay.addWidget(self.search)
        lay.addWidget(self.tabs)
        self._pending = False
        self._throttle = QtCore.QTimer(self)
        self._throttle.setSingleShot(True)
        self._throttle.setInterval(150)
        self._throttle.timeout.connect(self._throttled)
        # while an operator is redone again and again (dragging a value in Adjust Last Operation) each
        # redo is an undo + a new run – a new object, a selection change – and rebuilding every page
        # (~100 ms) made the drag stutter: wait until the redos settle, then refresh once
        self._hub = hub
        self._force_later = False
        self._settle = QtCore.QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(100)
        self._settle.timeout.connect(self._settled)
        hub.data_changed.connect(self._schedule)
        # operators can change what panels show without touching scene data (e.g. a "Custom" preset)
        hub.op_done.connect(lambda *_a: self._schedule())
        hub.selection_changed.connect(self._force_refresh)
        hub.file_loaded.connect(lambda: self.refresh(force=True))
        hub.undo_done.connect(self._force_refresh)
        hub.mode_changed.connect(lambda _m: self._force_refresh())
        self.refresh(force=True)

    def _force_refresh(self):
        if self._hub.in_redo():
            self._force_later = True
            self._settle.start()
            return
        self.refresh(force=True)

    def _throttled(self):
        if self._hub.in_redo():
            self._settle.start()
            return
        self.refresh()

    def _settled(self):
        if self._hub.in_redo():
            self._settle.start()
            return
        force, self._force_later = self._force_later, False
        self.refresh(force=force)

    def eventFilter(self, obj, ev):
        if obj is self.search and ev.type() == QtCore.QEvent.KeyPress and ev.key() == QtCore.Qt.Key_Escape:
            self.search.clear()
            return True
        return super().eventFilter(obj, ev)

    def search_text(self):
        try:
            return self.search.text().strip()
        except (AttributeError, RuntimeError):
            return ""

    def _run_search(self):
        """Builds every visible tab, filters it and greys out the tabs without a match."""
        text = self.search_text()
        keys = [k for k, _ in TABS]
        try:
            vis = self._visible_tabs()
        except Exception:
            vis = set(keys)
        if not text:
            self._search_counts = {}
            for i, (key, label) in enumerate(TABS):
                it = self.tabs.nav.item(i)
                it.setForeground(QtGui.QBrush())
                it.setToolTip(label)
            self.refresh(force=True)             # fresh widgets without the search marks
            return
        s = _Search(text)
        counts = {}
        for key in keys:
            if key not in vis:
                continue
            page = self.pages[key]
            try:
                page.refresh(force=True)
                counts[key] = s.page(page)
            except Exception as ex:
                bridge.log(f"Properties search/{key}: {ex}", "WARNING")
                counts[key] = 0
        self._search_counts = counts
        for i, (key, label) in enumerate(TABS):
            it = self.tabs.nav.item(i)
            n = counts.get(key, 0)
            it.setForeground(QtGui.QBrush() if n else QtGui.QBrush(QtGui.QColor("#6a6a6a")))
            it.setToolTip(f"{label} – {n} match{'es' if n != 1 else ''}" if n else f"{label} – no match")
        cur = keys[self.tabs.currentIndex()]
        if not counts.get(cur):
            best = next((k for k in keys if counts.get(k)), None)
            if best is not None:
                self.tabs.nav.blockSignals(True)
                self.tabs.setCurrentIndex(keys.index(best))
                self.tabs.stack.setCurrentIndex(keys.index(best))
                self.tabs.nav.blockSignals(False)

    def _changed(self, data, prop):
        self.undo(data, prop)
        self._schedule()

    def _schedule(self):
        if not self._throttle.isActive():
            self._throttle.start()

    def _visible_tabs(self):
        ctx = bpy.context
        ob = ctx.view_layer.objects.active
        scene = ctx.scene
        vis = {"render", "output", "view_layer", "scene"}
        if scene.world is not None:
            vis.add("world")
        try:
            if ctx.view_layer.active_layer_collection.collection != scene.collection:
                vis.add("collection")
        except Exception:
            pass
        if ob is not None:
            vis |= {"object", "constraint", "physics"}
            if ob.type in {"MESH", "CURVE", "SURFACE", "FONT", "LATTICE", "VOLUME", "POINTCLOUD",
                           "CURVES", "GREASEPENCIL", "GPENCIL"}:
                vis.add("modifier")
            if ob.data is not None:
                vis.add("data")
            if ob.type in MATERIAL_TYPES:
                vis.add("material")
            if ob.type == "MESH":
                vis.add("particle")
            if ob.type == "ARMATURE":
                vis.add("bone")
        vis.add("texture")
        return vis

    def refresh(self, force=False):
        try:
            vis = self._visible_tabs()
        except Exception:
            return
        for i, (key, _label) in enumerate(TABS):
            self.tabs.setTabVisible(i, key in vis)
        try:   # the Data tab shows the active object's data type (mesh, camera, light, …) like Blender
            ob = bpy.context.view_layer.objects.active
            name = blicons.DATA_ICONS.get(ob.type if ob else "", "MESH_DATA")
            if name != getattr(self, "_data_icon", None):
                self._data_icon = name
                self.tabs.nav.item([k for k, _ in TABS].index("data")).setIcon(blicons.icon(name))
        except Exception:
            pass
        cur = TABS[self.tabs.currentIndex()][0]
        if cur not in vis:
            self.tabs.setCurrentIndex([k for k, _ in TABS].index("object" if "object" in vis else "render"))
            return  # currentChanged triggers a refresh
        page = self.pages[cur]
        fw = QtWidgets.QApplication.focusWidget()
        if not force and fw is not None and page.isAncestorOf(fw) and isinstance(
                fw, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox)):
            # the user is typing – only refresh values, don't rebuild
            for b in getattr(page, "builders", []):
                b.refresh()
            return
        old = page.widget()
        page.refresh(force=force)
        text = self.search_text()
        if text and page.widget() is not old:        # rebuilt → apply the search again
            try:
                _Search(text).page(page)
            except Exception as ex:
                bridge.log(f"Properties search: {ex}", "WARNING")

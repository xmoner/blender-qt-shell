# SPDX-License-Identifier: GPL-3.0-or-later
"""Annotations panel – a dock like the Blue Pencil panel for Blender's annotations.

Two places, one tab each:
  · 3D Viewport  – the scene's annotations (`scene.annotation`), drawn in the 3D views (annotate.py)
  · Video Sequencer – the notes over Blender's sequencer preview (`sequencer.video_annotation()`; every layer has
    its own track in the channels)
Each tab: Draw (the Annotate tool on / off), the four tools (Annotate, Line, Polygon, Eraser), colour (palette,
custom colour), thickness, placement (3D), the layer manager (active, show / hide, rename, new, delete, order) and
the drawings of the active layer (jump to the previous / next one, delete the one on this frame, clear the layer).
"""

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, icons, pytips, theme

SPACES = (("VIEW3D", "3D Viewport"), ("VIDEO", "Video Sequencer"))
TOOL_ICONS = ("tool_annotate", "tool_annotate_line", "tool_annotate_polygon", "tool_annotate_eraser")
TOOL_NAMES = ("Annotate", "Annotate Line", "Annotate Polygon", "Annotate Eraser")
TOOL_TIPS = ("Draw free-hand notes", "Drag to draw a straight line",
             "Click points of a polygon, double-click / Enter to finish", "Drag over strokes to erase them")
VIEW3D_VARIANTS = ("FREEHAND", "LINE", "POLYGON", "ERASER")
NOTE_BLUE = (0.38, 0.61, 0.78)


def _settings():
    return QtCore.QSettings("QtShell", "QtShell")


def _mw():
    from . import app
    return getattr(app, "_win", None)


def layer_name(lay):
    return getattr(lay, "info", None) or getattr(lay, "name", "") or ""


def keys(lay):
    """Frames with a drawing on a layer (empty keys – a track's end key – left out), sorted."""
    try:
        return sorted(int(f.frame_number) for f in lay.frames if len(f.strokes))
    except Exception:
        return []


# ---------------------------------------------------------------- one place's annotations
class Place:
    """Data and tool of the annotations of one place (VIEW3D / VIDEO)."""

    def __init__(self, space):
        self.space = space

    # -- data
    def data(self, create=False):
        if self.space == "VIDEO":
            from . import sequencer
            return sequencer.video_annotation(create)
        from . import annotate
        return annotate.scene_annotation(create)

    def layers(self):
        an = self.data()
        if an is None:
            return []
        from . import annotate
        return [l for l in an.layers if layer_name(l) != annotate.RULER_LAYER]

    def active(self):
        from . import sequencer
        an = self.data()
        lay = sequencer.active_annotation_layer(an) if an is not None else None
        if lay is not None and lay in self.layers():
            return lay
        lays = self.layers()
        return lays[-1] if lays else None

    def set_active(self, lay):
        from . import sequencer
        an = self.data()
        if an is not None and lay is not None:
            sequencer.set_active_annotation_layer(an, lay)
            self.redraw()

    def _vs(self):
        mw = _mw()
        return getattr(mw, "sequencer", None)

    def add_layer(self, name=None):
        if self.space == "VIDEO":
            vs = self._vs()
            if vs is not None:
                return vs.add_annotation_layer(name)
            return None
        from . import sequencer
        an = self.data(create=True)
        base = name or "Note"
        names = {layer_name(l) for l in an.layers}
        nm, n = base, 1
        while nm in names:
            n += 1
            nm = f"{base} {n}"
        try:
            lay = an.layers.new(nm, set_active=True)
        except TypeError:
            lay = an.layers.new(nm)
        sequencer.set_active_annotation_layer(an, lay)
        try:
            lay.color = NOTE_BLUE                  # Blender's annotation blue (RNA-made layers are dark grey)
            lay.thickness = 3
        except Exception:
            pass
        bridge.undo_push("Add Annotation Layer")
        self.redraw()
        return layer_name(lay)

    def remove_layer(self, lay):
        if lay is None:
            return
        if self.space == "VIDEO" and self._vs() is not None:
            self._vs().remove_annotation_layer(layer_name(lay))
            return
        an = self.data()
        an.layers.remove(lay)
        bridge.undo_push("Delete Annotation Layer")
        self.redraw()

    def rename_layer(self, lay, new):
        new = (new or "").strip()
        old = layer_name(lay)
        if not new or new == old:
            return
        names = {layer_name(l) for l in self.data().layers}
        if new in names:
            raise ValueError(f"a layer {new!r} exists already")
        lay.info = new
        if self.space == "VIDEO":                  # its track follows the name
            from . import sequencer
            for s in sequencer.ann_tracks():
                if s.get(sequencer.ANN_PROP) == old:
                    s[sequencer.ANN_PROP] = new
            vs = self._vs()
            if vs is not None:
                vs.sync_ann_tracks()
        bridge.undo_push("Rename Annotation Layer")
        self.redraw()

    def move_layer(self, lay, step):
        """Moves the layer up (step = 1, drawn above) or down (-1) in the stack."""
        an = self.data()
        lays = list(an.layers)
        i = lays.index(lay)
        j = i + step
        if not (0 <= j < len(lays)):
            return
        try:
            an.layers.move(lay, "UP" if step > 0 else "DOWN")
        except Exception:
            self.set_active(lay)
            with bridge.blender_context():
                bpy.ops.gpencil.layer_annotation_move(type="UP" if step > 0 else "DOWN")
        bridge.undo_push("Move Annotation Layer")
        self.redraw()

    def hidden(self, lay):
        if self.space == "VIDEO" and self._vs() is not None:
            return self._vs().annotation_layer_hidden(layer_name(lay))
        return bool(getattr(lay, "annotation_hide", False))

    def set_hidden(self, lay, hidden):
        if self.space == "VIDEO" and self._vs() is not None:
            self._vs().set_annotation_layer_hidden(hidden, layer_name(lay))   # mutes its track
        else:
            lay.annotation_hide = bool(hidden)
            self.redraw()
        bridge.undo_push("Hide Annotation Layer" if hidden else "Show Annotation Layer")

    def set_color(self, lay, rgb):
        lay.color = tuple(rgb)[:3]
        self.redraw()

    def set_thickness(self, lay, px):
        lay.thickness = int(px)
        self.redraw()

    # -- drawings of the active layer
    def delete_drawing(self, lay):
        """Deletes the drawing shown on the current frame (the last key at or before it)."""
        if lay is None:
            return False
        if self.space == "VIDEO" and self._vs() is not None:
            return self._vs().clear_annotation_frame(layer_name(lay))
        f = bpy.context.scene.frame_current
        key = None
        for fr in lay.frames:
            if len(fr.strokes) and fr.frame_number <= f and (key is None or fr.frame_number > key.frame_number):
                key = fr
        if key is None:
            return False
        lay.frames.remove(key)
        bridge.undo_push("Delete Annotation Drawing")
        self.redraw()
        return True

    def clear_layer(self, lay):
        if lay is None:
            return
        for fr in list(lay.frames):
            lay.frames.remove(fr)
        if self.space == "VIDEO" and self._vs() is not None:
            self._vs().sync_ann_tracks()
        bridge.undo_push("Clear Annotation Layer")
        self.redraw()

    # -- tool
    def tool_on(self):
        if self.space == "VIDEO":
            vs = self._vs()
            return bool(vs is not None and vs.annotate_on())
        from . import gizmo
        mw = _mw()
        return mw is not None and gizmo.tool_state(mw.hub).tool == "ANNOTATE"

    def tool_index(self):
        if self.space == "VIDEO":
            from . import sequencer
            vs = self._vs()
            ids = [t[0] for t in sequencer.ANNOTATE_TOOLS]
            t = vs.annotate_tool() if vs is not None else ids[0]
            return ids.index(t) if t in ids else 0
        from . import gizmo
        mw = _mw()
        v = gizmo.tool_state(mw.hub).variant("ANNOTATE") if mw is not None else "FREEHAND"
        return VIEW3D_VARIANTS.index(v) if v in VIEW3D_VARIANTS else 0

    def set_tool(self, on, index=None):
        if self.space == "VIDEO":
            from . import sequencer
            vs = self._vs()
            if vs is None:
                return
            if on:
                mw = _mw()
                if mw is not None and "sequencer" in mw.docks:
                    mw.docks["sequencer"].show()
                    mw.docks["sequencer"].raise_()
            tool = sequencer.ANNOTATE_TOOLS[index][0] if index is not None else None
            vs.set_annotate(on, tool)
            return
        from . import gizmo
        mw = _mw()
        if mw is None:
            return
        st = gizmo.tool_state(mw.hub)
        if on:
            st.set_tool("ANNOTATE", VIEW3D_VARIANTS[index] if index is not None else None)
        elif st.tool == "ANNOTATE":
            st.set_tool("SELECT")

    # -- 3D only: placement, show
    def placement(self):
        return getattr(bpy.context.scene.tool_settings, "annotation_stroke_placement_view3d", "CURSOR")

    def set_placement(self, ident):
        bpy.context.scene.tool_settings.annotation_stroke_placement_view3d = ident

    def shown(self):
        found = bridge.find_view3d()
        if not found:
            return True
        try:
            return bool(found[1].spaces.active.overlay.show_annotation)
        except Exception:
            return True

    def set_shown(self, on):
        wm = bpy.context.window_manager
        for w in wm.windows:                       # every 3D view (Qt's hidden one and Blender's embedded ones)
            for a in w.screen.areas:
                if a.type == "VIEW_3D":
                    try:
                        a.spaces.active.overlay.show_annotation = bool(on)
                        a.tag_redraw()
                    except Exception:
                        pass
        self.redraw()

    def redraw(self):
        mw = _mw()
        if mw is None:
            return
        if self.space == "VIDEO":
            vs = self._vs()
            if vs is not None:
                try:
                    vs._annot_redraw()
                except Exception:
                    pass
            return
        area = getattr(mw, "viewports", None)
        for v in (getattr(area, "views", None) or [mw.viewport]):
            try:
                v.update()
            except Exception:
                pass
        try:
            from . import sculptview
            for nv in getattr(sculptview, "_views", {}).values() if isinstance(
                    getattr(sculptview, "_views", None), dict) else []:
                nv.redraw() if hasattr(nv, "redraw") else None
        except Exception:
            pass


PLACES = {k: Place(k) for k, _n in SPACES}


def show_panel(space=None):
    """Opens the Annotations dock (on the tab of space = 'VIEW3D' / 'VIDEO' when given)."""
    mw = _mw()
    if mw is None or "annotations" not in mw.docks:
        return
    if space:
        mw.annotations.set_space(space)
    d = mw.docks["annotations"]
    d.show()
    d.raise_()


def _swatch(color, size):
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtGui.QColor(color))
    return QtGui.QIcon(pm)


# ---------------------------------------------------------------- the panel
class AnnotationPanel(QtWidgets.QScrollArea):
    """Tabs 3D Viewport / Video Sequencer; Draw + tools, colour, thickness, placement, layers, drawings."""

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        from .bluepencil import PALETTE
        self.hub = hub
        self._sig = None
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget(self)
        self.setWidget(inner)
        v = QtWidgets.QVBoxLayout(inner)
        v.setContentsMargins(theme.px(6), theme.px(6), theme.px(6), theme.px(6))
        v.setSpacing(theme.px(4))

        def head(text):
            lab = QtWidgets.QLabel(text, inner)
            f = lab.font()
            f.setBold(True)
            lab.setFont(f)
            v.addWidget(lab)
            return lab

        # place tabs
        self.tabs = QtWidgets.QTabBar(inner)
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        for ident, name in SPACES:
            self.tabs.addTab(name)
        self.tabs.setTabToolTip(0, "Notes in the 3D views (the scene's annotations, saved with the file)")
        self.tabs.setTabToolTip(1, "Notes over Blender's preview of the Video Sequencer – every layer has its "
                                   "own track in the channels")
        start = str(_settings().value("annotations/space", "VIEW3D"))
        self.tabs.setCurrentIndex(1 if start == "VIDEO" else 0)
        self.tabs.currentChanged.connect(self._tab_changed)
        v.addWidget(self.tabs)

        # draw + show
        top = QtWidgets.QHBoxLayout()
        self.draw_btn = QtWidgets.QPushButton("Draw", inner)
        icons.set_icon(self.draw_btn, "tool_annotate", "Draw")
        self.draw_btn.setCheckable(True)
        self.draw_btn.setToolTip("The Annotate tool on / off in this place")
        self.draw_btn.clicked.connect(self._toggle_draw)
        top.addWidget(self.draw_btn)
        self.show_chk = QtWidgets.QCheckBox("Show annotations", inner)
        self.show_chk.setToolTip("Show the annotations in the 3D views (overlay)")
        pytips.tag(self.show_chk, "space.overlay.show_annotation = True")
        self.show_chk.toggled.connect(lambda on: (self.place().set_shown(on), self.sync(force=True)))
        top.addWidget(self.show_chk)
        top.addStretch(1)
        v.addLayout(top)

        # tools
        head("Tools")
        trow = QtWidgets.QGridLayout()          # 2 × 2 – fits a narrow dock
        trow.setSpacing(theme.px(2))
        self.tool_btns = []
        for n, (ic, name, tip) in enumerate(zip(TOOL_ICONS, TOOL_NAMES, TOOL_TIPS)):
            b = QtWidgets.QToolButton(inner)
            icons.set_icon(b, ic, name)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setToolTip(f"{name} – {tip}")
            b.clicked.connect(lambda _c=False, i=n: (self.place().set_tool(True, i), self.sync(force=True)))
            b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            trow.addWidget(b, n // 2, n % 2)
            self.tool_btns.append(b)
        v.addLayout(trow)

        # colour, thickness, placement
        crow = QtWidgets.QGridLayout()          # colour + palette in two rows
        crow.setSpacing(theme.px(2))
        per_row = (len(PALETTE) + 2) // 2
        self.color_btn = QtWidgets.QToolButton(inner)
        self.color_btn.setAutoRaise(True)
        self.color_btn.setToolTip("Colour of the active layer – click to choose any colour")
        pytips.tag(self.color_btn, "layer.color = (0.38, 0.61, 0.78)")
        self.color_btn.clicked.connect(self._pick_color)
        crow.addWidget(self.color_btn, 0, 0)
        for n, c in enumerate(PALETTE, 1):
            b = QtWidgets.QToolButton(inner)
            b.setIcon(_swatch(c, theme.px(12)))
            b.setAutoRaise(True)
            b.setToolTip(c)
            b.clicked.connect(lambda _c=False, col=c: self._set_color(QtGui.QColor(col)))
            crow.addWidget(b, n // per_row, n % per_row)
        crow.setColumnStretch(per_row, 1)
        v.addLayout(crow)
        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(theme.px(3))
        self.thick = QtWidgets.QSpinBox(inner)
        self.thick.setRange(1, 10)
        self.thick.setSuffix(" px")
        self.thick.setToolTip("Thickness of the active layer's strokes")
        pytips.tag(self.thick, "layer.thickness = 3")
        self.thick.valueChanged.connect(self._thickness)
        form.addRow("Thickness", self.thick)
        self.place_combo = QtWidgets.QComboBox(inner)
        for ident, name in (("CURSOR", "3D Cursor"), ("VIEW", "View"), ("SURFACE", "Surface")):
            self.place_combo.addItem(name, ident)
        self.place_combo.setToolTip("Placement – where new strokes go: on the plane through the 3D cursor, fixed "
                                    "to the view (screen) or on the surface of the objects under the mouse")
        pytips.tag(self.place_combo, "bpy.context.scene.tool_settings.annotation_stroke_placement_view3d = 'CURSOR'")
        self.place_combo.activated.connect(
            lambda _i: self.place().set_placement(self.place_combo.currentData()))
        self.place_lbl = QtWidgets.QLabel("Placement", inner)
        form.addRow(self.place_lbl, self.place_combo)
        v.addLayout(form)

        # layers
        head("Layers")
        self.layer_list = QtWidgets.QListWidget(inner)
        self.layer_list.setMinimumHeight(theme.px(110))
        self.layer_list.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked
                                        | QtWidgets.QAbstractItemView.EditKeyPressed)
        self.layer_list.setToolTip("Click: active layer (new strokes go there) · checkbox: show / hide · "
                                   "double-click: rename · top of the list is drawn on top")
        self.layer_list.currentRowChanged.connect(self._layer_picked)
        self.layer_list.itemChanged.connect(self._layer_edited)
        v.addWidget(self.layer_list)
        lrow = QtWidgets.QHBoxLayout()
        lrow.setSpacing(theme.px(2))

        def lbtn(icon, text, tip, fn):
            b = QtWidgets.QToolButton(inner)
            if not (icon and icons.set_icon(b, icon)):
                b.setText(text)
            b.setAutoRaise(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False: fn())
            lrow.addWidget(b)
            return b
        self.new_btn = lbtn("bp_layer_new", "New", "New annotation layer (made the active one)", self._new_layer)
        self.del_btn = lbtn("trash", "Delete", "Delete the active layer", self._delete_layer)
        self.up_btn = lbtn(None, "▲", "Move the active layer up (drawn above)", lambda: self._move(1))
        self.down_btn = lbtn(None, "▼", "Move the active layer down", lambda: self._move(-1))
        lrow.addStretch(1)
        v.addLayout(lrow)

        # drawings
        head("Drawings")
        self.keys_lbl = QtWidgets.QLabel(inner)
        self.keys_lbl.setWordWrap(True)
        self.keys_lbl.setProperty("dim", True)
        v.addWidget(self.keys_lbl)
        drow = QtWidgets.QHBoxLayout()
        drow.setSpacing(theme.px(2))
        self.prev_btn = QtWidgets.QPushButton("◀ Previous", inner)
        self.prev_btn.setToolTip("Go to the previous drawing of the active layer")
        self.prev_btn.clicked.connect(lambda _c=False: self._jump(-1))
        drow.addWidget(self.prev_btn)
        self.next_btn = QtWidgets.QPushButton("Next ▶", inner)
        self.next_btn.setToolTip("Go to the next drawing of the active layer")
        self.next_btn.clicked.connect(lambda _c=False: self._jump(1))
        drow.addWidget(self.next_btn)
        drow.addStretch(1)
        v.addLayout(drow)
        drow2 = QtWidgets.QHBoxLayout()
        drow2.setSpacing(theme.px(2))
        self.del_draw_btn = QtWidgets.QPushButton("Delete Drawing on This Frame", inner)
        self.del_draw_btn.setToolTip("Deletes the active layer's drawing shown on the current frame")
        self.del_draw_btn.clicked.connect(lambda _c=False: self._delete_drawing())
        drow2.addWidget(self.del_draw_btn)
        self.clear_btn = QtWidgets.QPushButton("Clear Layer", inner)
        self.clear_btn.setToolTip("Deletes every drawing of the active layer (the layer stays)")
        self.clear_btn.clicked.connect(lambda _c=False: self._clear_layer())
        drow2.addWidget(self.clear_btn)
        drow2.addStretch(1)
        v.addLayout(drow2)
        self.hint = QtWidgets.QLabel(inner)
        self.hint.setWordWrap(True)
        self.hint.setProperty("dim", True)
        v.addWidget(self.hint)
        v.addStretch(1)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        for name in ("frame_changed", "undo_done", "file_loaded", "mode_changed"):
            sig = getattr(hub, name, None)
            if sig is not None:
                sig.connect(lambda *_a: self.sync())
        self.sync(force=True)

    # ---- helpers
    def space(self):
        return SPACES[max(0, self.tabs.currentIndex())][0]

    def place(self):
        return PLACES[self.space()]

    def set_space(self, space):
        i = [k for k, _n in SPACES].index(space)
        if self.tabs.currentIndex() != i:
            self.tabs.setCurrentIndex(i)

    def _tab_changed(self, _i):
        _settings().setValue("annotations/space", self.space())
        self.sync(force=True)

    def _poll(self):
        if self.isVisible():
            self.sync()

    def _signature(self):
        pl = self.place()
        lays = pl.layers()
        act = pl.active()
        return (self.space(), pl.tool_on(), pl.tool_index(), bpy.context.scene.frame_current,
                tuple((layer_name(l), pl.hidden(l), tuple(round(c, 3) for c in l.color), int(l.thickness),
                       tuple(keys(l))) for l in lays),
                layer_name(act) if act is not None else None,
                pl.placement() if self.space() == "VIEW3D" else None,
                pl.shown() if self.space() == "VIEW3D" else None)

    # ---- refresh
    def sync(self, force=False):
        try:
            sig = self._signature()
        except Exception:
            return
        if sig == self._sig and not force:
            return
        self._sig = sig
        pl = self.place()
        is3d = self.space() == "VIEW3D"
        on = pl.tool_on()
        self.draw_btn.blockSignals(True)
        self.draw_btn.setChecked(on)
        self.draw_btn.blockSignals(False)
        pytips.tag(self.draw_btn, 'qt_shell.api.set_tool("ANNOTATE", "FREEHAND")' if is3d else
                   "qt_shell.app._win.sequencer.set_annotate(True)")
        ti = pl.tool_index()
        for n, b in enumerate(self.tool_btns):
            b.setChecked(on and n == ti)
            pytips.tag(b, f'qt_shell.api.set_tool("ANNOTATE", "{VIEW3D_VARIANTS[n]}")' if is3d else
                       f'qt_shell.app._win.sequencer.set_annotate(True, "{TOOL_ICONS[n].replace("tool_", "builtin.")}")')
        self.show_chk.setVisible(is3d)
        self.place_lbl.setVisible(is3d)
        self.place_combo.setVisible(is3d)
        if is3d:
            self.show_chk.blockSignals(True)
            self.show_chk.setChecked(pl.shown())
            self.show_chk.blockSignals(False)
            self.place_combo.setCurrentIndex(max(0, self.place_combo.findData(pl.placement())))
        lays = pl.layers()
        act = pl.active()
        # layer list – top of the list = top of the stack (drawn last)
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        row_act = -1
        for n, lay in enumerate(reversed(lays)):
            it = QtWidgets.QListWidgetItem(layer_name(lay))
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEditable)
            it.setCheckState(QtCore.Qt.Unchecked if pl.hidden(lay) else QtCore.Qt.Checked)
            it.setIcon(_swatch(QtGui.QColor.fromRgbF(*tuple(lay.color)[:3]).name(), theme.px(12)))
            it.setData(QtCore.Qt.UserRole, layer_name(lay))
            n_keys = len(keys(lay))
            it.setToolTip(f"{layer_name(lay)} – {n_keys} drawing(s)" +
                          (" · hidden (its track is muted)" if pl.hidden(lay) and not is3d else ""))
            self.layer_list.addItem(it)
            if act is not None and layer_name(lay) == layer_name(act):
                row_act = n
        self.layer_list.setCurrentRow(row_act)
        self.layer_list.blockSignals(False)
        has = act is not None
        for w in (self.del_btn, self.up_btn, self.down_btn, self.color_btn, self.thick, self.prev_btn,
                  self.next_btn, self.del_draw_btn, self.clear_btn):
            w.setEnabled(has)
        c = tuple(act.color)[:3] if has else NOTE_BLUE
        pm = QtGui.QPixmap(theme.px(28), theme.px(14))
        pm.fill(QtGui.QColor.fromRgbF(*c))
        self.color_btn.setIcon(QtGui.QIcon(pm))
        self.color_btn.setIconSize(pm.size())
        self.thick.blockSignals(True)
        self.thick.setValue(int(act.thickness) if has else 3)
        self.thick.blockSignals(False)
        ks = keys(act) if has else []
        f = bpy.context.scene.frame_current
        if not has:
            self.keys_lbl.setText("No layer yet – New makes one (drawing makes one too).")
        elif not ks:
            self.keys_lbl.setText("No drawings on this layer yet.")
        else:
            txt = ", ".join(f"[{k}]" if k == f else str(k) for k in ks[:40])
            self.keys_lbl.setText(f"On frames: {txt}{' …' if len(ks) > 40 else ''}")
        self.prev_btn.setEnabled(has and any(k < f for k in ks))
        self.next_btn.setEnabled(has and any(k > f for k in ks))
        self.hint.setText("Notes over Blender's preview – the Video Sequencer switches to Blender preview to draw; "
                          "each layer shows only where its track is." if not is3d else
                          "Draw in the 3D view with the Annotate tool. Notes are saved with the file.")

    # ---- actions
    def _toggle_draw(self, on):
        pl = self.place()
        pl.set_tool(bool(on), pl.tool_index())
        self.sync(force=True)

    def _layer_picked(self, row):
        if row < 0:
            return
        it = self.layer_list.item(row)
        lay = next((l for l in self.place().layers() if layer_name(l) == it.data(QtCore.Qt.UserRole)), None)
        if lay is not None:
            self.place().set_active(lay)
            self.sync(force=True)

    def _layer_edited(self, it):
        pl = self.place()
        old = it.data(QtCore.Qt.UserRole)
        lay = next((l for l in pl.layers() if layer_name(l) == old), None)
        if lay is None:
            return
        try:
            hidden = it.checkState() != QtCore.Qt.Checked
            if hidden != pl.hidden(lay):
                pl.set_hidden(lay, hidden)
            if it.text() != old:
                pl.rename_layer(lay, it.text())
        except Exception as ex:
            mw = _mw()
            if mw is not None:
                mw.statusBar().showMessage(f"Annotations: {ex}", 5000)
        QtCore.QTimer.singleShot(0, lambda: self.sync(force=True))

    def _new_layer(self):
        self.place().add_layer()
        self.sync(force=True)

    def _delete_layer(self):
        self.place().remove_layer(self.place().active())
        self.sync(force=True)

    def _move(self, step):
        lay = self.place().active()
        if lay is not None:
            self.place().move_layer(lay, step)
            self.sync(force=True)

    def _set_color(self, col):
        pl = self.place()
        lay = pl.active() or (pl.add_layer() and pl.active())
        if lay is None:
            return
        pl.set_color(lay, (col.redF(), col.greenF(), col.blueF()))
        bridge.undo_push("Annotation Colour")
        self.sync(force=True)

    def _pick_color(self):
        from . import colorpicker
        pl = self.place()
        lay = pl.active()
        if lay is None:
            return
        old = tuple(lay.color)[:3]

        def live(col):
            l2 = pl.active()
            if l2 is not None:
                pl.set_color(l2, (col.redF(), col.greenF(), col.blueF()))
                self.sync(force=True)

        def done(ok):
            l2 = pl.active()
            if not ok and l2 is not None:
                pl.set_color(l2, old)
            elif ok:
                bridge.undo_push("Annotation Colour")
            self.sync(force=True)
        colorpicker.pick(self.color_btn, QtGui.QColor.fromRgbF(*old), live, title="Annotation Colour",
                         on_done=done)

    def _thickness(self, v):
        pl = self.place()
        lay = pl.active()
        if lay is not None:
            pl.set_thickness(lay, v)

    def _jump(self, direction):
        lay = self.place().active()
        if lay is None:
            return
        f = bpy.context.scene.frame_current
        ks = keys(lay)
        tgt = max((k for k in ks if k < f), default=None) if direction < 0 else \
            min((k for k in ks if k > f), default=None)
        if tgt is not None:
            from . import bluepencil
            bluepencil.go_to(tgt)
            self.sync(force=True)

    def _delete_drawing(self):
        if not self.place().delete_drawing(self.place().active()):
            mw = _mw()
            if mw is not None:
                mw.statusBar().showMessage("Annotations: no drawing on this frame", 4000)
        self.sync(force=True)

    def _clear_layer(self):
        lay = self.place().active()
        if lay is None:
            return
        if QtWidgets.QMessageBox.question(self, "Clear Layer",
                                          f"Delete every drawing of the layer “{layer_name(lay)}”?") != \
                QtWidgets.QMessageBox.Yes:
            return
        self.place().clear_layer(lay)
        self.sync(force=True)

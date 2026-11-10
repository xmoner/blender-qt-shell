"""Vertex Paint panel (dock) – Blender's vertex paint tools with Maya's Paint Vertex Color Tool layout.

* Brushes: Blender's essentials vertex paint brushes (Paint Hard / Soft, with pen pressure, Airbrush; Blur,
  Average, Smear) as icon buttons with an Icon Size slider (QSettings `vpaint/brush_icon_size`).
* Colour: the paint colour and the secondary colour (the colour tool), Swap, Fill (Maya: Flood) – the whole
  mesh, or the selected faces / vertices with a selection mask.
* Brush: radius and strength with pen-pressure toggles, blend mode, falloff, spacing, front faces only,
  accumulate, alpha; same radius / strength / colour for all brushes.
* Colour Attributes: the mesh's colour layers – active one, add, remove.
* Masking (face / vertex selection), Symmetry (X / Y / Z), Adjust Colours (smooth, dirty, invert,
  brightness / contrast, hue / saturation / value, levels, from weights – values in Adjust Last Operation),
  Display (brush circle, asset shelf).

Painting happens in the Qt view (sculpt.py strokes run `paint.vertex_paint`) or – with Qt Preferences →
Viewport → Sculpt and Paint modes – in Blender's own embedded viewport (sculptview). The panel opens the first time Vertex Paint is
entered (Window menu: Vertex Paint).
"""
import bpy
from PySide6 import QtCore, QtWidgets

from . import blicons, bridge, theme
from .sculpt_panel import SculptPanel, brush_icon, _active_mesh_object, _ptr

PAINT, BLEND = "Paint", "Blend"
LIBRARY = "brushes/essentials_brushes-mesh_vertex.blend/Brush/"

# (Blender brush asset name, glyph, group, Maya equivalent / note)
BRUSHES = [
    ("Paint Hard", "paint_hard", PAINT, "Maya: Paint, hard edge"),
    ("Paint Soft", "paint_soft", PAINT, "Maya: Paint, soft edge"),
    ("Paint Hard Pressure", "paint_hard_p", PAINT, "Hard edge – pen pressure sets the strength"),
    ("Paint Soft Pressure", "paint_soft_p", PAINT, "Soft edge – pen pressure sets the strength"),
    ("Airbrush", "airbrush", PAINT, "Keeps adding colour while the button is held"),
    ("Blur", "blur", BLEND, "Maya: Smooth – blurs the colours under the brush"),
    ("Average", "average", BLEND, "Paints the average colour under the brush"),
    ("Smear", "smear", BLEND, "Maya: Smear – drags the colours along the stroke"),
]


def brush_entry(name):
    for e in BRUSHES:
        if e[0] == name:
            return e
    return None


# ---------------------------------------------------------------- settings
def active():
    try:
        return bpy.context.mode == "PAINT_VERTEX"
    except Exception:
        return False


def paint_settings():
    try:
        return bpy.context.scene.tool_settings.vertex_paint
    except AttributeError:
        return None


def brush():
    s = paint_settings()
    return getattr(s, "brush", None) if s is not None else None


def unified():
    s = paint_settings()
    u = getattr(s, "unified_paint_settings", None) if s is not None else None
    if u is None:                                   # Blender < 5: one set for all paint modes
        u = getattr(bpy.context.scene.tool_settings, "unified_paint_settings", None)
    return u


def _owner(flag):
    u = unified()
    return u if (u is not None and getattr(u, flag, False)) else brush()


def size_owner():
    return _owner("use_unified_size")


def strength_owner():
    return _owner("use_unified_strength")


def color_owner():
    return _owner("use_unified_color")


def activate_brush(name):
    """Makes an essentials vertex paint brush (e.g. "Paint Soft") the active one."""
    try:
        with bridge.blender_context():
            r = bpy.ops.brush.asset_activate(asset_library_type="ESSENTIALS", asset_library_identifier="",
                                             relative_asset_identifier=LIBRARY + name)
    except Exception as ex:
        bridge.log(f"Brush {name}: {ex}", "WARNING")
        return False
    return "FINISHED" in r


# ---------------------------------------------------------------- panel
class VertexPaintPanel(SculptPanel):
    ICON_KEY = "vpaint/brush_icon_size"
    STATE_PREFIX = "vpaint"

    def __init__(self, hub=None, parent=None):          # noqa: C901 – one layout
        QtWidgets.QScrollArea.__init__(self, parent)
        self.hub = hub
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        body = QtWidgets.QWidget(self)
        self.setWidget(body)
        self.lay = QtWidgets.QVBoxLayout(body)
        self.lay.setContentsMargins(6, 6, 6, 6)
        self.lay.setSpacing(6)
        self._state = {}
        self._bindings = []
        self._brush_key = None
        self._ob_key = None

        # header: the active brush
        head = QtWidgets.QHBoxLayout()
        self.head_icon = QtWidgets.QLabel(body)
        self.head_icon.setFixedSize(theme.px(36), theme.px(36))
        head.addWidget(self.head_icon)
        hv = QtWidgets.QVBoxLayout()
        self.head_name = QtWidgets.QLabel("—", body)
        f = self.head_name.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.15)
        self.head_name.setFont(f)
        self.head_note = QtWidgets.QLabel("", body)
        self.head_note.setStyleSheet("color:#9a9a9a;")
        hv.addWidget(self.head_name)
        hv.addWidget(self.head_note)
        head.addLayout(hv, 1)
        self.lay.addLayout(head)
        self.hint = QtWidgets.QLabel("", body)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#c9a85b;")
        self.lay.addWidget(self.hint)

        # brushes
        self.brush_btns = {}
        grp = QtWidgets.QButtonGroup(body)
        grp.setExclusive(True)
        bsec = self._section("Brushes", "brushes")
        srow = QtWidgets.QHBoxLayout()
        slab = QtWidgets.QLabel("Icon Size", body)
        slab.setStyleSheet("color:#9a9a9a;")
        srow.addWidget(slab)
        self.icon_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, body)
        self.icon_slider.setRange(16, 96)
        self.icon_slider.setValue(self._icon_size())
        self.icon_slider.setToolTip("Size of the brush icons")
        self.icon_slider.valueChanged.connect(self._set_icon_size)
        srow.addWidget(self.icon_slider, 1)
        self.icon_size_lab = QtWidgets.QLabel(f"{self._icon_size()} px", body)
        self.icon_size_lab.setMinimumWidth(theme.px(40))
        srow.addWidget(self.icon_size_lab)
        bsec.addLayout(srow)
        self._brush_grids = []
        for group in (PAINT, BLEND):
            lab = QtWidgets.QLabel(group, body)
            from .sculpt_panel import GROUP_COLORS
            lab.setStyleSheet(f"color:{GROUP_COLORS[group]}; font-weight:bold;")
            bsec.addWidget(lab)
            grid = QtWidgets.QGridLayout()
            grid.setSpacing(3)
            items = [b for b in BRUSHES if b[2] == group]
            for name, glyph, g, note in items:
                b = QtWidgets.QToolButton(body)
                b.setIcon(brush_icon(glyph, g))
                b.setCheckable(True)
                b.setAutoRaise(True)
                b.setToolTip(f"<b>{name}</b><br>{note}")
                self._style_brush_btn(b, self._icon_size())
                b.clicked.connect(lambda _=False, n=name: self.pick_brush(n))
                grp.addButton(b)
                self.brush_btns[name] = b
            self._brush_grids.append((grid, [self.brush_btns[e[0]] for e in items]))
            bsec.addLayout(grid)
        self._cols = 0
        self._flow_brushes()

        # sections rebuilt with the brush / object
        self.color_sec = self._section("Colour", "color")
        self.brush_sec = self._section("Brush", "brush")
        self.attr_sec = self._section("Colour Attributes", "attributes")
        self.mask_sec = self._section("Masking · Symmetry", "masking")
        asec = self._section("Adjust Colours (whole mesh / masked part)", "adjust", closed=True)
        self._buttons(asec, [
            ("Smooth", "MOD_SMOOTH", "paint.vertex_color_smooth", {}, "Smooth the colours"),
            ("Dirty Colours", "SHADING_SOLID", "paint.vertex_color_dirt", {},
             "Darken the cavities, lighten the edges (ambient-occlusion look)"),
            ("Invert", "IMAGE_ALPHA", "paint.vertex_color_invert", {}, "Invert the colours"),
            ("Brightness / Contrast", "LIGHT_SUN", "paint.vertex_color_brightness_contrast",
             {"brightness": 10.0, "contrast": 0.0}, "Brighter / more contrast – values in Adjust Last Operation"),
            ("Hue / Saturation / Value", "COLOR", "paint.vertex_color_hsv", {"h": 0.5, "s": 1.0, "v": 1.0},
             "Shift the hue, saturation and value – values in Adjust Last Operation"),
            ("Levels", "SEQ_HISTOGRAM", "paint.vertex_color_levels", {"offset": 0.0, "gain": 1.0},
             "Offset and gain of the colours – values in Adjust Last Operation"),
            ("From Weights", "GROUP_VERTEX", "paint.vertex_color_from_weight", {},
             "Colours from the active vertex group's weights"),
        ])
        self.disp_sec = self._section("Display", "display", closed=True)
        self.lay.addStretch(1)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.sync)
        self.sync()

    # ---- actions
    def _ensure_sculpt(self):
        """Brush / tool buttons used outside Vertex Paint: the active mesh goes into Vertex Paint (like picking
        Maya's Paint Vertex Color Tool). False (with a status message) when there is no mesh."""
        if active():
            return True
        ob = _active_mesh_object()
        if ob is None:
            bridge.log("Select a mesh object to paint – the brushes work in Vertex Paint.", "INFO")
            return False
        if bpy.context.mode != "OBJECT":
            bridge.run_op("object.mode_set", {"mode": "OBJECT"})
        bridge.run_op("object.mode_set", {"mode": "VERTEX_PAINT"})
        if not active():
            bridge.log(f"{ob.name} could not enter Vertex Paint.", "INFO")
            return False
        return True

    def _run(self, op, props):
        if not self._ensure_sculpt():
            self.sync(force=True)
            return
        bridge.run_op(op, dict(props))
        self._redraw()
        self.sync(force=True)
        if op.startswith("paint.vertex_color_") and op != "paint.vertex_color_set":
            self._show_last_op()

    def _show_last_op(self):
        """The filters' values (brightness, hue …) are set in Adjust Last Operation."""
        try:
            from . import api
            d = api.main_window().docks.get("last_op")
            if d is not None:
                d.show()
                d.raise_()
        except Exception:
            pass

    def _redraw(self):
        super()._redraw()
        try:
            from . import sculptview
            for v in list(sculptview._views.values()):
                a = v.area()
                if a is not None:
                    a.tag_redraw()
        except Exception:
            pass

    def pick_brush(self, name):
        if not self._ensure_sculpt():
            self.sync(force=True)
            return
        activate_brush(name)
        self.sync(force=True)

    def _fill(self):
        """Maya: Flood – the paint colour on the whole mesh (or the masked faces / vertices)."""
        self._run("paint.vertex_color_set", {})

    def _swap(self):
        self._run("paint.brush_colors_flip", {})

    # ---- sections
    def _build_brush(self):
        lay = self.brush_sec
        self._clear(lay)
        self._clear(self.color_sec)
        self._bindings = [b for b in self._bindings if b.alive()]
        br = brush()
        if br is None:
            lay.addWidget(QtWidgets.QLabel("No brush.", self.widget()))
            return
        # colour
        co = color_owner()
        r = QtWidgets.QHBoxLayout()
        c1 = self._row_into(r, "Colour", co, "color")
        if c1 is not None:
            c1.widget.setToolTip("Paint colour – click for the colour tool")
            c1.widget.setMinimumWidth(theme.px(60))
        c2, _n = None, None
        from . import rna_widgets as rw
        c2, _n = rw.make_binding(co, "secondary_color", on_change=lambda *_a: self._redraw())
        if c2 is not None:
            self._bindings.append(c2)
            c2.widget.setToolTip("Secondary colour (Swap makes it the paint colour)")
            c2.widget.setMaximumWidth(theme.px(36))
            r.addWidget(c2.widget)
        sw = QtWidgets.QToolButton(self.widget())
        if blicons.has("ARROW_LEFTRIGHT"):
            sw.setIcon(blicons.icon("ARROW_LEFTRIGHT"))
        sw.setToolTip("Swap the paint and the secondary colour")
        sw.clicked.connect(lambda _=False: self._swap())
        r.addWidget(sw)
        self.color_sec.addLayout(r)
        r = QtWidgets.QHBoxLayout()
        fb = QtWidgets.QPushButton("Fill", self.widget())
        if blicons.has("VPAINT_HLT"):
            fb.setIcon(blicons.icon("VPAINT_HLT"))
        fb.setToolTip("Maya: Flood – fill the whole mesh with the paint colour (only the selected faces / "
                      "vertices while a selection mask is on)")
        fb.clicked.connect(lambda _=False: self._fill())
        r.addWidget(fb, 1)
        u = unified()
        if u is not None and "use_unified_color" in u.bl_rna.properties:
            self._toggle(None, "Same Colour for All Brushes", u, "use_unified_color", "LINKED", row=r)
        self.color_sec.addLayout(r)
        # brush
        r = QtWidgets.QHBoxLayout()
        self._row_into(r, "Radius", size_owner(), "size")
        self._toggle(None, "", br, "use_pressure_size", "STYLUS_PRESSURE", row=r).widget.setToolTip(
            "Pen pressure changes the radius")
        lay.addLayout(r)
        r = QtWidgets.QHBoxLayout()
        self._row_into(r, "Strength", strength_owner(), "strength")
        self._toggle(None, "", br, "use_pressure_strength", "STYLUS_PRESSURE", row=r).widget.setToolTip(
            "Pen pressure changes the strength")
        lay.addLayout(r)
        if "blend" in br.bl_rna.properties and getattr(br, "vertex_brush_type", "DRAW") == "DRAW":
            self._row(lay, "Blend", br, "blend")
        for label, prop in (("Hardness", "hardness"), ("Spacing %", "spacing")):
            if prop in br.bl_rna.properties:
                self._row(lay, label, br, prop)
        if "curve_distance_falloff_preset" in br.bl_rna.properties:
            self._row(lay, "Falloff", br, "curve_distance_falloff_preset", expand=True, columns=2)
        r = QtWidgets.QHBoxLayout()
        for text, prop, icon in (("Front Faces Only", "use_frontface", "FACESEL"),
                                 ("Accumulate", "use_accumulate", "ADD"),
                                 ("Affect Alpha", "use_alpha", "IMAGE_ALPHA")):
            if prop in br.bl_rna.properties:
                self._toggle(None, text, br, prop, icon, row=r)
        lay.addLayout(r)
        if u is not None:
            r = QtWidgets.QHBoxLayout()
            self._toggle(None, "Same Radius for All Brushes", u, "use_unified_size", "LINKED", row=r)
            self._toggle(None, "Same Strength", u, "use_unified_strength", "LINKED", row=r)
            lay.addLayout(r)
        from . import keymap
        tip = QtWidgets.QLabel(keymap.render(
            "Drag in the view to paint · Ctrl: secondary colour · Shift: blur · {sculpt.radius}: radius · "
            "{sculpt.strength}: strength · {sculpt.radius_down} / {sculpt.radius_up}: smaller / bigger. "
            "In Blender's viewport (Qt Preferences → Viewport) Blender's own brush keys apply."), self.widget())
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8a8a8a;")
        lay.addWidget(tip)

    def _build_object(self):
        ob = _active_mesh_object()
        for lay in (self.attr_sec, self.mask_sec, self.disp_sec):
            self._clear(lay)
        self._bindings = [b for b in self._bindings if b.alive()]
        if ob is None:
            self.attr_sec.addWidget(QtWidgets.QLabel("Select a mesh.", self.widget()))
            return
        me = ob.data
        # colour attributes
        ca = getattr(me, "color_attributes", None)
        if ca is not None:
            r = QtWidgets.QHBoxLayout()
            combo = QtWidgets.QComboBox(self.widget())
            names = [a.name for a in ca]
            combo.addItems(names)
            act = getattr(ca, "active_color", None)
            if act is not None and act.name in names:
                combo.setCurrentIndex(names.index(act.name))
            combo.setToolTip("The colour attribute you paint on")
            combo.setEnabled(bool(names))
            combo.activated.connect(lambda i, m=me: self._set_active_attr(m, i))
            r.addWidget(combo, 1)
            ab = QtWidgets.QToolButton(self.widget())
            if blicons.has("ADD"):
                ab.setIcon(blicons.icon("ADD"))
            ab.setToolTip("Add a colour attribute (white)")
            ab.clicked.connect(lambda _=False: self._add_attr())
            r.addWidget(ab)
            rb = QtWidgets.QToolButton(self.widget())
            if blicons.has("REMOVE"):
                rb.setIcon(blicons.icon("REMOVE"))
            rb.setToolTip("Remove the active colour attribute")
            rb.setEnabled(bool(names))
            rb.clicked.connect(lambda _=False: self._run("geometry.color_attribute_remove", {}))
            r.addWidget(rb)
            self.attr_sec.addLayout(r)
            if not names:
                lab = QtWidgets.QLabel("No colour attribute – painting adds one.", self.widget())
                lab.setStyleSheet("color:#8a8a8a;")
                self.attr_sec.addWidget(lab)
        # masking
        r = QtWidgets.QHBoxLayout()
        lab = QtWidgets.QLabel("Selection", self.widget())
        lab.setMinimumWidth(theme.px(78))
        r.addWidget(lab)
        for text, prop, icon, tip in (
                ("Faces", "use_paint_mask", "FACESEL", "Paint only the selected faces (select them in the view)"),
                ("Vertices", "use_paint_mask_vertex", "VERTEXSEL", "Paint only the selected vertices")):
            if prop in me.bl_rna.properties:
                self._toggle(None, text, me, prop, icon, row=r).widget.setToolTip(tip)
        self.mask_sec.addLayout(r)
        r = QtWidgets.QHBoxLayout()
        lab = QtWidgets.QLabel("Mirror", self.widget())
        lab.setMinimumWidth(theme.px(78))
        r.addWidget(lab)
        for ax in "xyz":
            self._toggle(None, ax.upper(), me, f"use_mirror_{ax}", row=r).widget.setToolTip(
                f"Mirror the strokes across the {ax.upper()} axis")
        self.mask_sec.addLayout(r)
        # display
        s = paint_settings()
        if s is not None and "show_brush" in s.bl_rna.properties:
            self._toggle(self.disp_sec, "Brush Circle", s, "show_brush", "CURSOR")
        self._asset_shelf_button()

    def _set_active_attr(self, me, i):
        try:
            me.color_attributes.active_color_index = i
        except Exception:
            try:
                me.color_attributes.active_color = me.color_attributes[i]
            except Exception as ex:
                bridge.log(f"Colour attribute: {ex}", "WARNING")
        self._redraw()
        self.sync(force=True)

    def _add_attr(self):
        ob = _active_mesh_object()
        n = 1
        names = {a.name for a in ob.data.color_attributes} if ob is not None else set()
        name = "Color"
        while name in names:
            n += 1
            name = f"Color.{n:03d}"
        self._run("geometry.color_attribute_add", {"name": name, "domain": "POINT", "data_type": "BYTE_COLOR",
                                                   "color": (1.0, 1.0, 1.0, 1.0)})

    # ---- sync
    def sync(self, force=False):
        if bridge.op_depth or (not force and not self.isVisible()):
            return                    # (a Qt timer fired inside an operator – undo swaps the data under us)
        try:
            on = active()
            self.hint.setVisible(not on)
            self.hint.setText("Vertex Paint is off – switch to it in the 3D view header (or "
                              + self._mode_key() + "); a brush button switches too.")
            br = brush() if on else None
            name = getattr(br, "name", "") if br is not None else ""
            e = brush_entry(name)
            self.head_name.setText(name or "—")
            self.head_note.setText(e[3] if e else (str(getattr(br, "vertex_brush_type", "")).title()
                                                   if br is not None else ""))
            if e:
                self.head_icon.setPixmap(brush_icon(e[1], e[2]).pixmap(theme.px(36), theme.px(36)))
            else:
                self.head_icon.clear()
            for n, b in self.brush_btns.items():
                b.blockSignals(True)
                b.setChecked(n == name)
                b.blockSignals(False)
            bkey = (_ptr(br), _ptr(size_owner()) if on else 0, _ptr(strength_owner()) if on else 0,
                    _ptr(color_owner()) if on else 0, str(getattr(br, "vertex_brush_type", "")) if br else "")
            ob = _active_mesh_object()
            ca = getattr(ob.data, "color_attributes", None) if ob is not None else None
            okey = (_ptr(ob), on, tuple(a.name for a in ca) if ca is not None else (),
                    getattr(getattr(ca, "active_color", None), "name", None) if ca is not None else None)
            if force or bkey != self._brush_key:
                self._brush_key = bkey
                if on:
                    self._build_brush()
                else:
                    self._clear(self.brush_sec)
                    self._clear(self.color_sec)
            if force or okey != self._ob_key:
                self._ob_key = okey
                self._build_object()
            alive = []
            for b in self._bindings:
                try:
                    if b.alive():
                        b.refresh()
                        alive.append(b)
                except RuntimeError:
                    pass
            self._bindings = alive
        except Exception as ex:
            bridge.log(f"Vertex Paint panel: {ex}", "WARNING")

    def _mode_key(self):
        from . import keymap
        return keymap.render("{view3d.mode_vertex_paint}")

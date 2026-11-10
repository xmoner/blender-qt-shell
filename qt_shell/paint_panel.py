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


def brush_entry(name, brushes=None):
    for e in (brushes or BRUSHES):
        if e[0] == name:
            return e
    return None


# ---------------------------------------------------------------- settings (attr = tool settings attribute)
def active(mode="PAINT_VERTEX"):
    try:
        return bpy.context.mode == mode
    except Exception:
        return False


def paint_settings(attr="vertex_paint"):
    try:
        return getattr(bpy.context.scene.tool_settings, attr)
    except AttributeError:
        return None


def brush(attr="vertex_paint"):
    s = paint_settings(attr)
    return getattr(s, "brush", None) if s is not None else None


def unified(attr="vertex_paint"):
    s = paint_settings(attr)
    u = getattr(s, "unified_paint_settings", None) if s is not None else None
    if u is None:                                   # Blender < 5: one set for all paint modes
        u = getattr(bpy.context.scene.tool_settings, "unified_paint_settings", None)
    return u


def _owner(flag, attr="vertex_paint"):
    u = unified(attr)
    return u if (u is not None and getattr(u, flag, False)) else brush(attr)


def size_owner(attr="vertex_paint"):
    return _owner("use_unified_size", attr)


def strength_owner(attr="vertex_paint"):
    return _owner("use_unified_strength", attr)


def color_owner(attr="vertex_paint"):
    return _owner("use_unified_color", attr)


def activate_brush(name, library=LIBRARY):
    """Makes an essentials paint brush (e.g. "Paint Soft") the active one."""
    try:
        with bridge.blender_context():
            r = bpy.ops.brush.asset_activate(asset_library_type="ESSENTIALS", asset_library_identifier="",
                                             relative_asset_identifier=library + name)
    except Exception as ex:
        bridge.log(f"Brush {name}: {ex}", "WARNING")
        return False
    return "FINISHED" in r


# ---------------------------------------------------------------- panel
class VertexPaintPanel(SculptPanel):
    ICON_KEY = "vpaint/brush_icon_size"
    STATE_PREFIX = "vpaint"
    MODE = "PAINT_VERTEX"            # bpy.context.mode
    MODE_SET = "VERTEX_PAINT"        # object.mode_set
    SETTINGS = "vertex_paint"        # tool settings attribute
    TITLE = "Vertex Paint"
    MODE_ACTION = "view3d.mode_vertex_paint"
    LIBRARY = LIBRARY
    BRUSHES = BRUSHES
    GROUPS = (PAINT, BLEND)
    TYPE_PROP = "vertex_brush_type"

    # settings of this panel's mode
    def active(self):
        return active(self.MODE)

    def settings(self):
        return paint_settings(self.SETTINGS)

    def brush(self):
        return brush(self.SETTINGS)

    def unified(self):
        return unified(self.SETTINGS)

    def size_owner(self):
        return size_owner(self.SETTINGS)

    def strength_owner(self):
        return strength_owner(self.SETTINGS)

    def color_owner(self):
        return color_owner(self.SETTINGS)

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
        for group in self.GROUPS:
            lab = QtWidgets.QLabel(group, body)
            from .sculpt_panel import GROUP_COLORS
            lab.setStyleSheet(f"color:{GROUP_COLORS[group]}; font-weight:bold;")
            bsec.addWidget(lab)
            grid = QtWidgets.QGridLayout()
            grid.setSpacing(3)
            items = [b for b in self.BRUSHES if b[2] == group]
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
        self._mode_sections()
        self.disp_sec = self._section("Display", "display", closed=True)
        self.lay.addStretch(1)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.sync)
        self.sync()

    def _mode_sections(self):
        """The sections between Brush and Display (this mode's own)."""
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

    # ---- actions
    def _ensure_sculpt(self):
        """Brush / tool buttons used outside this paint mode: the active mesh goes into it (like picking
        Maya's Paint Vertex Color / 3D Paint Tool). False (with a status message) when there is no mesh."""
        if self.active():
            return True
        ob = _active_mesh_object()
        if ob is None:
            bridge.log(f"Select a mesh object to paint – the brushes work in {self.TITLE}.", "INFO")
            return False
        if bpy.context.mode != "OBJECT":
            bridge.run_op("object.mode_set", {"mode": "OBJECT"})
        bridge.run_op("object.mode_set", {"mode": self.MODE_SET})
        if not self.active():
            bridge.log(f"{ob.name} could not enter {self.TITLE}.", "INFO")
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
        activate_brush(name, self.LIBRARY)
        self.sync(force=True)

    def _fill(self):
        """Maya: Flood – the paint colour on the whole mesh (or the masked faces / vertices)."""
        self._run("paint.vertex_color_set", {})

    def _fill_button(self, row):
        fb = QtWidgets.QPushButton("Fill", self.widget())
        if blicons.has("VPAINT_HLT"):
            fb.setIcon(blicons.icon("VPAINT_HLT"))
        fb.setToolTip("Maya: Flood – fill the whole mesh with the paint colour (only the selected faces / "
                      "vertices while a selection mask is on)")
        fb.clicked.connect(lambda _=False: self._fill())
        row.addWidget(fb, 1)

    def _swap(self):
        self._run("paint.brush_colors_flip", {})

    # ---- sections
    def _build_brush(self):
        lay = self.brush_sec
        self._clear(lay)
        self._clear(self.color_sec)
        self._bindings = [b for b in self._bindings if b.alive()]
        br = self.brush()
        if br is None:
            lay.addWidget(QtWidgets.QLabel("No brush.", self.widget()))
            return
        # colour
        co = self.color_owner()
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
        self._fill_button(r)
        u = self.unified()
        if u is not None and "use_unified_color" in u.bl_rna.properties:
            self._toggle(None, "Same Colour for All Brushes", u, "use_unified_color", "LINKED", row=r)
        self.color_sec.addLayout(r)
        # brush
        r = QtWidgets.QHBoxLayout()
        self._row_into(r, "Radius", self.size_owner(), "size")
        self._toggle(None, "", br, "use_pressure_size", "STYLUS_PRESSURE", row=r).widget.setToolTip(
            "Pen pressure changes the radius")
        lay.addLayout(r)
        r = QtWidgets.QHBoxLayout()
        self._row_into(r, "Strength", self.strength_owner(), "strength")
        self._toggle(None, "", br, "use_pressure_strength", "STYLUS_PRESSURE", row=r).widget.setToolTip(
            "Pen pressure changes the strength")
        lay.addLayout(r)
        if "blend" in br.bl_rna.properties and getattr(br, self.TYPE_PROP, "DRAW") == "DRAW":
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
            "Drag in the view to paint · Ctrl: secondary colour / invert · {sculpt.radius}: radius · "
            "{sculpt.strength}: strength · {sculpt.radius_down} / {sculpt.radius_up}: smaller / bigger. "
            "In Blender's viewport (Qt Preferences → Viewport) Blender's own brush keys apply."), self.widget())
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8a8a8a;")
        lay.addWidget(tip)

    def _object_sections(self):
        return (self.attr_sec, self.mask_sec, self.disp_sec)

    def _build_object(self):
        ob = _active_mesh_object()
        for lay in self._object_sections():
            self._clear(lay)
        self._bindings = [b for b in self._bindings if b.alive()]
        if ob is None:
            self._object_sections()[0].addWidget(QtWidgets.QLabel("Select a mesh.", self.widget()))
            return
        self._build_mode_object(ob)
        self._mirror_row(ob.data)
        # display
        s = self.settings()
        if s is not None and "show_brush" in s.bl_rna.properties:
            self._toggle(self.disp_sec, "Brush Circle", s, "show_brush", "CURSOR")
        self._asset_shelf_button()

    def _mirror_row(self, me):
        r = QtWidgets.QHBoxLayout()
        lab = QtWidgets.QLabel("Mirror", self.widget())
        lab.setMinimumWidth(theme.px(78))
        r.addWidget(lab)
        for ax in "xyz":
            self._toggle(None, ax.upper(), me, f"use_mirror_{ax}", row=r).widget.setToolTip(
                f"Mirror the strokes across the {ax.upper()} axis")
        self.mask_sec.addLayout(r)

    def _build_mode_object(self, ob):
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
            on = self.active()
            msg = self._mode_hint() if on else (f"{self.TITLE} is off – switch to it in the 3D view header (or "
                                               + self._mode_key() + "); a brush button switches too.")
            self.hint.setVisible(bool(msg))
            self.hint.setText(msg or "")
            br = self.brush() if on else None
            name = getattr(br, "name", "") if br is not None else ""
            e = brush_entry(name, self.BRUSHES)
            self.head_name.setText(name or "—")
            self.head_note.setText(e[3] if e else (str(getattr(br, self.TYPE_PROP, "")).title()
                                                   if br is not None else ""))
            if e:
                self.head_icon.setPixmap(brush_icon(e[1], e[2]).pixmap(theme.px(36), theme.px(36)))
            else:
                self.head_icon.clear()
            for n, b in self.brush_btns.items():
                b.blockSignals(True)
                b.setChecked(n == name)
                b.blockSignals(False)
            bkey = (_ptr(br), _ptr(self.size_owner()) if on else 0, _ptr(self.strength_owner()) if on else 0,
                    _ptr(self.color_owner()) if on else 0, str(getattr(br, self.TYPE_PROP, "")) if br else "")
            ob = _active_mesh_object()
            okey = (_ptr(ob), on) + self._object_key(ob)
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
            bridge.log(f"{self.TITLE} panel: {ex}", "WARNING")

    def _object_key(self, ob):
        """What rebuilds the object sections when it changes."""
        ca = getattr(ob.data, "color_attributes", None) if ob is not None else None
        return (tuple(a.name for a in ca) if ca is not None else (),
                getattr(getattr(ca, "active_color", None), "name", None) if ca is not None else None)

    def _mode_hint(self):
        """A warning while the mode is on (e.g. nothing to paint on), or None."""
        return None

    def _mode_key(self):
        from . import keymap
        return keymap.render("{%s}" % self.MODE_ACTION)


# ---------------------------------------------------------------- Texture Paint
ERASE, TOOLS = "Erase", "Tools"
TEX_LIBRARY = "brushes/essentials_brushes-mesh_texture.blend/Brush/"
TEX_BRUSHES = [
    ("Paint Hard", "paint_hard", PAINT, "Maya 3D Paint: Paint, hard edge"),
    ("Paint Soft", "paint_soft", PAINT, "Maya 3D Paint: Paint, soft edge"),
    ("Paint Hard Pressure", "paint_hard_p", PAINT, "Hard edge – pen pressure sets the strength"),
    ("Paint Soft Pressure", "paint_soft_p", PAINT, "Soft edge – pen pressure sets the strength"),
    ("Airbrush", "airbrush", PAINT, "Keeps adding colour while the button is held"),
    ("Paint Pixel Art", "pixel", PAINT, "Hard square pixels, no smoothing (pixel art)"),
    ("Erase Hard", "erase_hard", ERASE, "Maya 3D Paint: Erase – removes paint (alpha), hard edge"),
    ("Erase Soft", "erase_soft", ERASE, "Erases with a soft edge"),
    ("Erase Hard Pressure", "erase_hard_p", ERASE, "Hard edge – pen pressure sets how much is erased"),
    ("Erase Pixel Art", "erase_pixel", ERASE, "Erases square pixels"),
    ("Blur", "blur", TOOLS, "Maya 3D Paint: Smear / Blur – softens the texture under the brush"),
    ("Smear", "smear", TOOLS, "Maya 3D Paint: Smear – drags the colours along the stroke"),
    ("Fill", "bucket", TOOLS, "Maya 3D Paint: Flood – fills the area under the click (gradient in the brush)"),
    ("Clone", "clone", TOOLS, "Maya 3D Paint: Clone – copies from another place (Ctrl+click sets the source "
                              "in Blender's viewport) or another image"),
    ("Mask", "mask", TOOLS, "Paints a stencil mask (needs a stencil image)"),
]


class TexturePaintPanel(VertexPaintPanel):
    """Texture Paint panel – Blender's texture paint tools with Maya's 3D Paint Tool layout: brushes, colour,
    brush, Texture Slots (material slots or a single image, new slot / image, save), Projection, Masking ·
    Symmetry, Display."""
    ICON_KEY = "tpaint/brush_icon_size"
    STATE_PREFIX = "tpaint"
    MODE = "PAINT_TEXTURE"
    MODE_SET = "TEXTURE_PAINT"
    SETTINGS = "image_paint"
    TITLE = "Texture Paint"
    MODE_ACTION = "view3d.mode_texture_paint"
    LIBRARY = TEX_LIBRARY
    BRUSHES = TEX_BRUSHES
    GROUPS = (PAINT, ERASE, TOOLS)
    TYPE_PROP = "image_brush_type"

    def _mode_sections(self):
        self.slot_sec = self._section("Texture Slots", "slots")
        self.proj_sec = self._section("Projection", "projection", closed=True)
        self.mask_sec = self._section("Masking · Symmetry", "masking")

    def _object_sections(self):
        return (self.slot_sec, self.proj_sec, self.mask_sec, self.disp_sec)

    def _fill_button(self, row):
        fb = QtWidgets.QPushButton("Fill Brush", self.widget())
        if blicons.has("TPAINT_HLT"):
            fb.setIcon(blicons.icon("TPAINT_HLT"))
        fb.setToolTip("Maya: Flood – picks the Fill brush: click in the view fills the area with the colour")
        fb.clicked.connect(lambda _=False: self.pick_brush("Fill"))
        row.addWidget(fb, 1)

    def _swap(self):
        self._run("paint.brush_colors_flip", {})

    def _object_key(self, ob):
        ip = self.settings()
        mat = ob.active_material if ob is not None else None
        slots = tuple(getattr(s, "name", "") for s in getattr(mat, "texture_paint_slots", ()) or ()) if mat else ()
        return (getattr(ip, "mode", ""), _ptr(getattr(ip, "canvas", None)), _ptr(mat), slots,
                getattr(mat, "paint_active_slot", 0) if mat else 0, len(bpy.data.images),
                len(ob.material_slots) if ob is not None else 0)

    def _mode_hint(self):
        ip = self.settings()
        if ip is None:
            return None
        if getattr(ip, "missing_uvs", False):
            return "The mesh has no UV map – unwrap it first (UV editor → Create)."
        if getattr(ip, "mode", "") == "IMAGE" and getattr(ip, "canvas", None) is None:
            return "No image to paint on – pick one or press New Image under Texture Slots."
        if getattr(ip, "mode", "") == "MATERIAL" and (getattr(ip, "missing_materials", False)
                                                      or getattr(ip, "missing_texture", False)):
            return "Nothing to paint on – add a texture slot under Texture Slots (Add Slot)."
        return None

    def _build_mode_object(self, ob):
        ip = self.settings()
        lay = self.slot_sec
        if ip is None:
            return
        self._row(lay, "Mode", ip, "mode", expand=True)
        if ip.mode == "MATERIAL":
            mat = ob.active_material
            r = QtWidgets.QHBoxLayout()
            combo = QtWidgets.QComboBox(self.widget())
            slots = list(getattr(mat, "texture_paint_slots", ()) or ()) if mat is not None else []
            names = [getattr(s, "name", "") or f"Slot {i + 1}" for i, s in enumerate(slots)]
            combo.addItems(names)
            if mat is not None and names:
                combo.setCurrentIndex(max(0, min(len(names) - 1, mat.paint_active_slot)))
            combo.setEnabled(bool(names))
            combo.setToolTip("The texture you paint on (the material's image textures)")
            combo.activated.connect(lambda i, m=mat: self._set_slot(m, i))
            r.addWidget(combo, 1)
            ab = QtWidgets.QPushButton("Add Slot", self.widget())
            if blicons.has("ADD"):
                ab.setIcon(blicons.icon("ADD"))
            ab.setToolTip("New image texture in the material (Base Color, 1024 × 1024) – adds a material when "
                          "there is none")
            ab.clicked.connect(lambda _=False: self._add_slot())
            r.addWidget(ab)
            lay.addLayout(r)
            if mat is None:
                lab = QtWidgets.QLabel("No material – Add Slot creates one.", self.widget())
                lab.setStyleSheet("color:#8a8a8a;")
                lay.addWidget(lab)
        else:
            r = QtWidgets.QHBoxLayout()
            combo = QtWidgets.QComboBox(self.widget())
            imgs = [im for im in bpy.data.images if im.type not in ("RENDER_RESULT", "COMPOSITING")]
            combo.addItem("—", None)
            for im in imgs:
                combo.addItem(im.name, im.name)
            cur = getattr(ip.canvas, "name", None) if ip.canvas is not None else None
            combo.setCurrentIndex(max(0, combo.findData(cur)))
            combo.setToolTip("The image you paint on (Single Image mode – the active UV map)")
            combo.activated.connect(lambda i, c=combo: self._set_canvas(c.itemData(i)))
            r.addWidget(combo, 1)
            nb = QtWidgets.QPushButton("New Image", self.widget())
            if blicons.has("IMAGE_DATA"):
                nb.setIcon(blicons.icon("IMAGE_DATA"))
            nb.setToolTip("New white image (1024 × 1024) to paint on")
            nb.clicked.connect(lambda _=False: self._new_canvas())
            r.addWidget(nb)
            lay.addLayout(r)
        sb = QtWidgets.QPushButton("Save All Images", self.widget())
        if blicons.has("FILE_TICK"):
            sb.setIcon(blicons.icon("FILE_TICK"))
        sb.setToolTip("Save every painted (modified) image to its file – new images need a file first "
                      "(Image editor → Save As)")
        sb.clicked.connect(lambda _=False: self._run("image.save_all_modified", {}))
        lay.addWidget(sb)
        # projection
        for text, prop, icon, tip in (
                ("Occlude", "use_occlude", "HIDE_OFF", "Only paint the surface you see (not through the mesh)"),
                ("Backface Culling", "use_backface_culling", "FACESEL", "Don't paint faces pointing away"),
                ("Normal Falloff", "use_normal_falloff", "NORMALS_FACE", "Paint less on faces turned away")):
            if prop in ip.bl_rna.properties:
                self._toggle(self.proj_sec, text, ip, prop, icon).widget.setToolTip(tip)
        for label, prop in (("Normal Angle", "normal_angle"), ("Bleed", "seam_bleed"), ("Dither", "dither")):
            if prop in ip.bl_rna.properties:
                self._row(self.proj_sec, label, ip, prop)
        # masking
        me = ob.data
        r = QtWidgets.QHBoxLayout()
        lab = QtWidgets.QLabel("Selection", self.widget())
        lab.setMinimumWidth(theme.px(78))
        r.addWidget(lab)
        if "use_paint_mask" in me.bl_rna.properties:
            self._toggle(None, "Faces", me, "use_paint_mask", "FACESEL", row=r).widget.setToolTip(
                "Paint only the selected faces")
        self.mask_sec.addLayout(r)

    def _set_slot(self, mat, i):
        if mat is not None:
            try:
                mat.paint_active_slot = i
            except Exception as ex:
                bridge.log(f"Texture slot: {ex}", "WARNING")
        self._redraw()
        self.sync(force=True)

    def _set_canvas(self, name):
        ip = self.settings()
        if ip is not None:
            ip.canvas = bpy.data.images.get(name) if name else None
        self._redraw()
        self.sync(force=True)

    def _new_canvas(self):
        n, name = 1, "Texture"
        while name in bpy.data.images:
            n += 1
            name = f"Texture.{n:03d}"
        img = bpy.data.images.new(name, 1024, 1024)
        img.generated_color = (1.0, 1.0, 1.0, 1.0)
        self._set_canvas(img.name)
        bridge.undo_push("New Image")

    def _add_slot(self):
        if not self._ensure_sculpt():
            return
        bridge.run_op("paint.add_texture_paint_slot", {"type": "BASE_COLOR", "slot_type": "IMAGE",
                                                       "width": 1024, "height": 1024,
                                                       "color": (1.0, 1.0, 1.0, 1.0)})
        self._redraw()
        self.sync(force=True)

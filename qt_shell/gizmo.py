"""Tools and gizmos in the 3D viewport (like Blender's toolbar: Select – Tweak / Box / Circle / Lasso,
Cursor, Move, Rotate, Scale – Scale / Scale Cage, Transform, Annotate – Annotate / Line / Polygon / Eraser,
Measure, Add – Cube / Cone / Cylinder / UV Sphere / Ico Sphere (Object Mode only)). The Annotate, Measure and
Add tools live in annotate.py.

- Toolbar: a column of tool buttons on the left of every 3D view (T shows / hides it).
- Gizmo: drawn at the pivot of the selection (median of the selected objects' origins, or of the
  selected vertices in Edit mode), in the transform orientation of the header (Global, Local, Normal,
  Gimbal, View, Cursor, Parent or a custom one – orientation_matrix()):
    Move   – X / Y / Z arrows, a circle in the middle = free move in the view plane
    Rotate – X / Y / Z rings, the outer white ring = rotate around the view axis
    Scale  – X / Y / Z handles with boxes, the outer white ring = uniform scale
    Transform – all in one: arrows move, rings rotate, boxes on the axes scale
    Scale Cage – a box around the selection: drag a side (one axis) or a corner (all axes);
                 the opposite side / corner stays where it is
- Tool buttons with variants (Select, Scale) show a small triangle: hold the button or right click it
  to choose the variant; pressing the tool's key again cycles the variants (like Blender).

Shortcuts: Shift+Space opens the tool menu (W Select, Space Cursor, G Move, R Rotate, S Scale,
T Transform, D Annotate, M Measure, A Add – the key of the active tool again: next variant), W switches to Select (again: next select
variant), T shows / hides the toolbar. All keys live in keymap.py.
- Dragging a handle runs the same interactive transform as G / R / S (with the axis set);
  releasing the mouse confirms, right click / Esc cancels.

The tool and the toolbar visibility are shared by all views and remembered (QSettings).
"""
import math

import bpy
from mathutils import Matrix, Vector
from PySide6 import QtCore, QtGui, QtWidgets

from . import theme
from . import icons
from . import keymap
from . import pytips

# (tool, glyph, tooltip, key in the Shift+Space tool menu)
TOOLS = [
    ("SELECT", "⬚", "Select – click to select; drag: Tweak moves, Box / Circle / Lasso select", "W"),
    ("CURSOR", "⊕", "Cursor – click to place the 3D cursor on the surface under the mouse, drag to move it",
     "Space"),
    ("MOVE", "✥", "Move – drag an arrow (X / Y / Z) or the centre (free)", "G"),
    ("ROTATE", "⟳", "Rotate – drag a ring (X / Y / Z) or the outer ring (view axis)", "R"),
    ("SCALE", "⤡", "Scale – drag a handle (X / Y / Z) or the outer ring (uniform)", "S"),
    ("TRANSFORM", "❖", "Transform – arrows move, rings rotate, boxes scale", "T"),
    ("ANNOTATE", "✎", "Annotate – draw notes over the scene", "D"),
    ("BLUE_PENCIL", "✐", "Blue Pencil – 2D drawings over the camera / view, keyed on frames (thumbnails, "
                        "blocking, arcs, review notes)", "P"),
    ("MEASURE", "📏", "Measure – drag to measure distances, from the middle of a ruler: angles", "M"),
    ("ADD", "＋", "Add – drag the base, then the height of a new object", "A"),
]
# a gap in the toolbar before these tools (groups like Blender's toolbar)
GROUP_START = ("ANNOTATE", "ADD")
OBJECT_ONLY = ("ADD",)          # tools shown only in Object Mode
_KIND = {"MOVE": "G", "ROTATE": "R", "SCALE": "S", "TRANSFORM": "T"}
_BUILTIN = {"SELECT": "select_box", "CURSOR": "cursor", "MOVE": "move", "ROTATE": "rotate", "SCALE": "scale",
            "TRANSFORM": "transform", "MEASURE": "measure"}
TOOL_NAMES = {"SELECT": "Select", "CURSOR": "Cursor", "MOVE": "Move", "ROTATE": "Rotate", "SCALE": "Scale",
              "TRANSFORM": "Transform", "ANNOTATE": "Annotate", "BLUE_PENCIL": "Blue Pencil", "MEASURE": "Measure",
              "ADD": "Add"}

# variants: tool → [(variant, name, icon, Blender tool id, tooltip)]
VARIANTS = {
    "SELECT": [
        ("TWEAK", "Tweak", "tool_tweak", "select",
         "Click to select; drag what is under the mouse to move it"),
        ("BOX", "Select Box", "tool_select", "select_box",
         "Drag a rectangle to select (Shift adds, Ctrl removes)"),
        ("CIRCLE", "Select Circle", "tool_select_circle", "select_circle",
         "Paint the selection with a circle (Shift adds, Ctrl removes); mouse wheel while dragging changes "
         "its size"),
        ("LASSO", "Select Lasso", "tool_select_lasso", "select_lasso",
         "Draw a free shape around what to select (Shift adds, Ctrl removes)"),
    ],
    "SCALE": [
        ("SCALE", "Scale", "tool_scale", "scale",
         "Drag a handle (X / Y / Z) or the outer ring (uniform)"),
        ("CAGE", "Scale Cage", "tool_scale_cage", "scale_cage",
         "Drag a side of the box around the selection (one axis) or a corner (all axes) – the opposite "
         "side stays"),
    ],
    "ANNOTATE": [
        ("FREEHAND", "Annotate", "tool_annotate", "annotate",
         "Draw a free-hand note (stored in the scene's annotations, saved with the file)"),
        ("LINE", "Annotate Line", "tool_annotate_line", "annotate_line", "Drag to draw a straight line"),
        ("POLYGON", "Annotate Polygon", "tool_annotate_polygon", "annotate_polygon",
         "Click to add points; double-click, Enter or right click finishes"),
        ("ERASER", "Annotate Eraser", "tool_annotate_eraser", "annotate_eraser",
         "Drag over strokes to erase them (Ctrl + mouse wheel: radius)"),
    ],
    # Qt Shell's own tool (bluepencil.py) – "qtshell:" ids are not Blender tools
    "BLUE_PENCIL": [
        ("PENCIL", "Pencil", "bp_pencil", "qtshell:PENCIL", "Blue Pencil: free-hand line"),
        ("BRUSH", "Brush", "bp_brush", "qtshell:BRUSH", "Blue Pencil: tapered stroke (tablet pressure)"),
        ("ERASER", "Eraser", "bp_eraser", "qtshell:ERASER",
         "Blue Pencil: drag over strokes – lines are cut, shapes and text removed"),
        ("TEXT", "Text", "bp_text", "qtshell:TEXT", "Blue Pencil: click to type a note"),
        ("LINE", "Line", "bp_line", "qtshell:LINE", "Blue Pencil: drag a straight line"),
        ("ARROW", "Arrow", "bp_arrow", "qtshell:ARROW", "Blue Pencil: drag an arrow"),
        ("ELLIPSE", "Ellipse", "bp_ellipse", "qtshell:ELLIPSE", "Blue Pencil: drag an ellipse (Shift: circle)"),
        ("RECT", "Rectangle", "bp_rect", "qtshell:RECT", "Blue Pencil: drag a rectangle (Shift: square)"),
        ("TRANSFORM", "Transform", "bp_transform", "qtshell:TRANSFORM",
         "Blue Pencil: select a region, then drag to move (Shift: rotate, middle mouse: scale); Enter applies"),
    ],
    "ADD": [
        ("CUBE", "Add Cube", "tool_add_cube", "primitive_cube_add",
         "Drag the base, release, move the mouse for the height, click to create"),
        ("CONE", "Add Cone", "tool_add_cone", "primitive_cone_add",
         "Drag the base, release, move the mouse for the height, click to create"),
        ("CYLINDER", "Add Cylinder", "tool_add_cylinder", "primitive_cylinder_add",
         "Drag the base, release, move the mouse for the height, click to create"),
        ("UV_SPHERE", "Add UV Sphere", "tool_add_uvsphere", "primitive_uv_sphere_add",
         "Drag the base, release, move the mouse for the height, click to create"),
        ("ICO_SPHERE", "Add Ico Sphere", "tool_add_icosphere", "primitive_ico_sphere_add",
         "Drag the base, release, move the mouse for the height, click to create"),
    ],
}
_DEFAULT_VARIANT = {"SELECT": "BOX", "SCALE": "SCALE", "ANNOTATE": "FREEHAND", "BLUE_PENCIL": "PENCIL", "ADD": "CUBE"}
# keymap actions of the tools (their keys are shown in tooltips; pressing again cycles the variants)
TOOL_ACTIONS = {"SELECT": "view3d.tool_select", "CURSOR": "view3d.tool_cursor", "MOVE": "view3d.tool_move",
                "ROTATE": "view3d.tool_rotate", "SCALE": "view3d.tool_scale", "ANNOTATE": "view3d.tool_annotate",
                "MEASURE": "view3d.tool_measure", "ADD": "view3d.tool_add",
                "BLUE_PENCIL": "view3d.tool_blue_pencil"}
CIRCLE_RADIUS = 25          # default Select Circle radius (unscaled px)


def tool_command(bid):
    """Python command of a tool (Blender's tool ids; the Add tools are Blender's "builtin.primitive_*")."""
    if str(bid).startswith("qtshell:"):           # Qt Shell's own tools (Blue Pencil)
        return f'qt_shell.api.set_tool("BLUE_PENCIL", "{bid.split(":", 1)[1]}")'
    return f'bpy.ops.wm.tool_set_by_id(name="builtin.{bid}")'


def variant_info(tool, variant):
    for v in VARIANTS.get(tool, []):
        if v[0] == variant:
            return v
    return None

AXES = (("X", Vector((1, 0, 0)), QtGui.QColor("#ff3352")),
        ("Y", Vector((0, 1, 0)), QtGui.QColor("#8bdc00")),
        ("Z", Vector((0, 0, 1)), QtGui.QColor("#2890ff")))
HOVER_COLOR = QtGui.QColor("#ffe066")


# ---------------------------------------------------------------- transform orientation
ORIENT_NAMES = {"GLOBAL": "Global", "LOCAL": "Local", "NORMAL": "Normal", "GIMBAL": "Gimbal", "VIEW": "View",
                "CURSOR": "Cursor", "PARENT": "Parent"}


def orientation_type(ctx=None):
    """The scene's transform orientation (header: Transform Orientation) – 'GLOBAL', 'LOCAL' … or the name
    of a custom orientation."""
    ctx = ctx or bpy.context
    try:
        return ctx.scene.transform_orientation_slots[0].type
    except Exception:
        return "GLOBAL"


def orientation_label(kind):
    return ORIENT_NAMES.get(kind, kind)


def _rot3(m):
    """Rotation part of a matrix (scale / shear removed), columns = axes."""
    m3 = m.to_3x3()
    try:
        return m3.to_quaternion().to_matrix()
    except Exception:
        return Matrix.Identity(3)


def _ortho(z, hint):
    """3x3 with Z = z and X as close to hint as possible."""
    z = z.normalized()
    x = hint - z * hint.dot(z)
    if x.length < 1e-6:
        x = _perp(z)[0]
    x.normalize()
    y = z.cross(x).normalized()
    return Matrix((x, y, z)).transposed()


def _gimbal(ob_world_parent, euler):
    """Gimbal axes of an Euler rotation: the axis applied last is fixed, the others follow it."""
    order = euler.order
    P = _rot3(ob_world_parent)
    unit = {"X": Vector((1, 0, 0)), "Y": Vector((0, 1, 0)), "Z": Vector((0, 0, 1))}
    ang = {"X": euler.x, "Y": euler.y, "Z": euler.z}
    o0, o1, o2 = order[0], order[1], order[2]
    R2 = Matrix.Rotation(ang[o2], 3, o2)
    R1 = Matrix.Rotation(ang[o1], 3, o1)
    axes = {o2: P @ unit[o2], o1: P @ R2 @ unit[o1], o0: P @ R2 @ R1 @ unit[o0]}
    return Matrix((axes["X"].normalized(), axes["Y"].normalized(), axes["Z"].normalized())).transposed()


def _active_bone(ctx):
    from . import posetransform
    pb = ctx.active_pose_bone
    if pb is not None and pb.select:
        return ctx.active_object, pb
    bones = posetransform.selected_bones(ctx)
    return bones[0] if bones else (None, None)


def _edit_normal(ob, bm):
    """(normal, tangent) of the selection in world space (selected faces, else vertex normals)."""
    mw = ob.matrix_world
    nm = mw.to_3x3().inverted_safe().transposed()
    faces = [f for f in bm.faces if f.select and not f.hide]
    n = Vector()
    t = Vector()
    if faces:
        for f in faces:
            n += f.normal
            # the longest edge of the face – like Blender's tangent of a face
            e = max(f.edges, key=lambda e: e.calc_length())
            t += mw.to_3x3() @ (e.verts[1].co - e.verts[0].co)
    else:
        verts = [v for v in bm.verts if v.select and not v.hide]
        for v in verts:
            n += v.normal
        edges = [e for e in bm.edges if e.select and not e.hide]
        if edges:
            t = mw.to_3x3() @ (edges[0].verts[1].co - edges[0].verts[0].co)
    n = nm @ n
    return (n if n.length > 1e-9 else None), t


def orientation_matrix(vp=None, kind=None, ctx=None):
    """3x3 matrix whose columns are the X / Y / Z axes of the transform orientation (world space)."""
    ctx = ctx or bpy.context
    kind = kind or orientation_type(ctx)
    I = Matrix.Identity(3)
    try:
        mode = ctx.mode
        if kind == "GLOBAL":
            return I
        if kind == "VIEW":
            if vp is None:
                return I
            r, u, f = vp.view_vectors()
            return Matrix((r, u, -f)).transposed()
        if kind == "CURSOR":
            return _rot3(ctx.scene.cursor.matrix)
        if kind in ORIENT_NAMES:              # LOCAL / NORMAL / GIMBAL / PARENT
            if mode == "POSE":
                ob, pb = _active_bone(ctx)
                if pb is None:
                    return I
                if kind == "PARENT":
                    return _rot3(ob.matrix_world @ pb.parent.matrix) if pb.parent else _rot3(ob.matrix_world)
                if kind == "GIMBAL" and pb.rotation_mode not in ("QUATERNION", "AXIS_ANGLE"):
                    parent = ob.matrix_world @ pb.matrix @ pb.matrix_basis.inverted_safe()
                    return _gimbal(parent, pb.rotation_euler)
                return _rot3(ob.matrix_world @ pb.matrix)
            ob = ctx.edit_object if mode.startswith("EDIT") else (ctx.active_object or
                                                                 (ctx.selected_objects or [None])[0])
            if ob is None:
                return I
            if mode == "EDIT_MESH" and kind == "NORMAL":
                from . import editmesh
                r = editmesh.active()
                if r:
                    n, t = _edit_normal(*r)
                    if n is not None:
                        return _ortho(n, t if t.length > 1e-9 else _rot3(ob.matrix_world).col[0])
                return _rot3(ob.matrix_world)
            if kind == "PARENT":
                return _rot3(ob.parent.matrix_world) if ob.parent else I
            if kind == "GIMBAL" and ob.rotation_mode not in ("QUATERNION", "AXIS_ANGLE"):
                parent = ob.matrix_world @ ob.matrix_basis.inverted_safe()
                return _gimbal(parent, ob.rotation_euler)
            return _rot3(ob.matrix_world)          # LOCAL, NORMAL (object mode), Gimbal of quaternions
        # a custom orientation (Transform Orientations → +)
        co = ctx.scene.transform_orientation_slots[0].custom_orientation
        if co is not None:
            return _rot3(co.matrix.to_4x4())
    except Exception:
        pass
    return I


def axes(vp=None, kind=None):
    """AXES in the current transform orientation: (name, world direction, color)."""
    kind = kind or orientation_type()
    if vp is not None and kind != "VIEW" and bpy.context.mode == "EDIT_MESH":
        cache = getattr(vp, "_gizmo_orient_cache", None)    # Normal walks the mesh – once per change
        if cache is not None and cache[0] == kind:
            m = cache[1]
        else:
            m = orientation_matrix(vp, kind)
            vp._gizmo_orient_cache = (kind, m)
    else:
        m = orientation_matrix(vp, kind)
    return tuple((name, m.col[i].normalized(), col) for i, (name, _a, col) in enumerate(AXES))

# sizes in (unscaled) screen pixels
ARROW_LEN = 78
RING_R = 70
VIEW_RING_R = 86
CENTER_R = 11
PICK_DIST = 7


# ---------------------------------------------------------------- shared tool state
class ToolState(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        s = QtCore.QSettings("QtShell", "QtShell")
        tool = str(s.value("viewport/tool", "SELECT"))
        self.tool = tool if tool in [t[0] for t in TOOLS] else "SELECT"
        self.variants = {}
        for t, vs in VARIANTS.items():
            v = str(s.value(f"viewport/tool_variant_{t.lower()}", _DEFAULT_VARIANT[t]))
            self.variants[t] = v if v in [x[0] for x in vs] else _DEFAULT_VARIANT[t]
        try:
            self.circle_radius = float(s.value("viewport/select_circle_radius", CIRCLE_RADIUS))
        except (TypeError, ValueError):
            self.circle_radius = float(CIRCLE_RADIUS)
        try:
            self.eraser_radius = float(s.value("viewport/eraser_radius", 20))
        except (TypeError, ValueError):
            self.eraser_radius = 20.0
        self.toolbar_visible = str(s.value("viewport/toolbar", "true")).lower() == "true"
        # toolbar position shared by all views: (fx, fy) = fraction of the free space, None = default
        self.toolbar_pos = None
        self.toolbar_horizontal = False
        try:
            raw = str(s.value("viewport/toolbar_pos", "") or "")
            if raw:
                fx, fy, h = raw.split(",")
                self.toolbar_pos = (min(1.0, max(0.0, float(fx))), min(1.0, max(0.0, float(fy))))
                self.toolbar_horizontal = h == "h"
        except Exception:
            self.toolbar_pos = None

    def set_tool(self, tool, variant=None):
        if tool not in [t[0] for t in TOOLS]:
            return
        changed = False
        if variant is not None and variant != self.variants.get(tool) and variant_info(tool, variant):
            self.variants[tool] = variant
            QtCore.QSettings("QtShell", "QtShell").setValue(f"viewport/tool_variant_{tool.lower()}", variant)
            changed = True
        if tool != self.tool:
            self.tool = tool
            QtCore.QSettings("QtShell", "QtShell").setValue("viewport/tool", tool)
            changed = True
        if changed:
            self.changed.emit()

    def variant(self, tool=None):
        """Current variant of a tool with variants (SELECT: TWEAK / BOX / CIRCLE / LASSO, SCALE: SCALE / CAGE)."""
        return self.variants.get(tool or self.tool)

    def activate(self, tool):
        """A tool key / button: switch to the tool, or – when it is already active – to its next variant."""
        vs = VARIANTS.get(tool)
        if tool == self.tool and vs:
            ids = [v[0] for v in vs]
            cur = self.variants.get(tool, ids[0])
            self.set_tool(tool, ids[(ids.index(cur) + 1) % len(ids)] if cur in ids else ids[0])
        else:
            self.set_tool(tool)

    def set_circle_radius(self, r):
        self.circle_radius = max(4.0, min(400.0, float(r)))
        QtCore.QSettings("QtShell", "QtShell").setValue("viewport/select_circle_radius", self.circle_radius)

    def set_eraser_radius(self, r):
        self.eraser_radius = max(2.0, min(200.0, float(r)))
        QtCore.QSettings("QtShell", "QtShell").setValue("viewport/eraser_radius", self.eraser_radius)
        self.changed.emit()

    def set_toolbar_pos(self, pos, horizontal=None):
        self.toolbar_pos = pos
        if horizontal is not None:
            self.toolbar_horizontal = bool(horizontal)
        val = "" if pos is None else \
            f"{pos[0]:.4f},{pos[1]:.4f},{'h' if self.toolbar_horizontal else 'v'}"
        if pos is None and self.toolbar_horizontal:
            val = "0,0.0,h"           # keep the orientation even at the default place
            self.toolbar_pos = (0.0, 0.0)
        QtCore.QSettings("QtShell", "QtShell").setValue("viewport/toolbar_pos", val)
        self.changed.emit()

    def toggle_toolbar(self):
        self.toolbar_visible = not self.toolbar_visible
        QtCore.QSettings("QtShell", "QtShell").setValue(
            "viewport/toolbar", "true" if self.toolbar_visible else "false")
        self.changed.emit()


def tool_state(hub):
    st = getattr(hub, "_tool_state", None)
    if st is None:
        st = hub._tool_state = ToolState(hub)
    return st


# ---------------------------------------------------------------- toolbar
class _Grip(QtWidgets.QWidget):
    """The dotted handle of the toolbar – drag it to move the toolbar."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setCursor(QtCore.Qt.SizeAllCursor)
        self.setToolTip("Drag to move the toolbar (it snaps to the edges of the view)\n"
                        "Double-click: back to the default place · Right click: more")
        self.horizontal = False

    def sizeHint(self):
        return QtCore.QSize(theme.px(10), theme.px(30)) if self.horizontal else \
            QtCore.QSize(theme.px(30), theme.px(10))

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(235, 235, 235) if self.underMouse() else QtGui.QColor(175, 175, 175))
        r = max(1.2, theme.px(1.6))
        c = QtCore.QPointF(self.rect().center())
        step = theme.px(5)
        for i in (-1, 0, 1):
            for j in (-0.5, 0.5):
                dx, dy = (j * step, i * step) if self.horizontal else (i * step, j * step)
                p.drawEllipse(c + QtCore.QPointF(dx, dy), r, r)

    def enterEvent(self, ev):
        self.update()

    def leaveEvent(self, ev):
        self.update()


class _ToolButton(QtWidgets.QToolButton):
    """A tool button. Tools with variants (Select, Scale) show a small triangle in the corner; holding the
    button or a right click opens the variants (like Blender's toolbar)."""

    def __init__(self, toolbar, tool):
        super().__init__(toolbar)
        self.toolbar = toolbar
        self.tool = tool
        self.has_variants = tool in VARIANTS
        if self.has_variants:
            m = QtWidgets.QMenu(self)
            m.setToolTipsVisible(True)
            m.aboutToShow.connect(self._fill)
            self.setMenu(m)
            self.setPopupMode(QtWidgets.QToolButton.DelayedPopup)

    def _fill(self):
        m = self.menu()
        m.clear()
        st = self.toolbar.state
        for vid, name, icon, bid, tip in VARIANTS[self.tool]:
            a = m.addAction(icons.icon(icon), name)
            a.setCheckable(True)
            cur = st.variant(self.tool) == vid
            a.setChecked(st.tool == self.tool and cur)
            if cur:                       # Qt shows no check mark next to an icon: the current one is bold
                fnt = a.font()
                fnt.setBold(True)
                a.setFont(fnt)
            a.setToolTip(tip)
            pytips.tag(a, tool_command(bid))
            a.triggered.connect(lambda _c=False, v=vid: st.set_tool(self.tool, v))

    def contextMenuEvent(self, ev):
        if self.has_variants:
            self.showMenu()
            ev.accept()
            return
        super().contextMenuEvent(ev)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if not self.has_variants:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(225, 225, 225, 200))
        r = self.rect()
        k = theme.px(5)
        x, y = r.right() - theme.px(2), r.bottom() - theme.px(2)
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, y - k), QtCore.QPointF(x, y), QtCore.QPointF(x - k, y)]))
        p.end()


def _style_gap(gap, horizontal):
    """The thin line between groups of tool buttons."""
    if horizontal:
        gap.setFixedSize(theme.px(5), theme.px(22))
        gap.setStyleSheet(f"background: transparent; border: none; border-left: 1px solid #555; "
                          f"margin-left: {theme.px(2)}px;")
    else:
        gap.setFixedSize(theme.px(22), theme.px(5))
        gap.setStyleSheet(f"background: transparent; border: none; border-top: 1px solid #555; "
                          f"margin-top: {theme.px(2)}px;")


class Toolbar(QtWidgets.QFrame):
    """Tool buttons floating over a 3D view – movable by its grip, snaps to the edges."""

    SNAP = 28          # unscaled px: closer than this to an edge → stick to it

    def __init__(self, viewport):
        super().__init__(viewport)
        self.vp = viewport
        self.state = tool_state(viewport.hub)
        self.setObjectName("qtshell_toolbar")
        self.setStyleSheet(
            "QFrame#qtshell_toolbar { background: rgba(40, 40, 40, 215); border: 1px solid #1a1a1a;"
            f" border-radius: {theme.px(5)}px; }}"
            "QToolButton { background: transparent; border: 1px solid transparent; }"
            "QToolButton::menu-indicator { image: none; width: 0px; }"
            f"QToolButton:checked {{ background: {theme.C['highlight']}; }}\n" + theme.hover_qss())
        lay = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.TopToBottom, self)
        m = theme.px(3)
        lay.setContentsMargins(m, m, m, m)
        lay.setSpacing(theme.px(2))
        self._lay = lay
        self._drag = None              # (press pos in the viewport, toolbar pos at press)
        self.grip = _Grip(self)
        self.grip.installEventFilter(self)
        lay.addWidget(self.grip, 0, QtCore.Qt.AlignCenter)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.buttons = {}
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        f = self.font()
        f.setPixelSize(theme.fs(17))
        self.gaps = {}
        for tool, glyph, tip, key in TOOLS:
            if tool in GROUP_START:            # a thin line between the groups of tools
                gap = QtWidgets.QFrame(self)
                _style_gap(gap, False)
                lay.addWidget(gap, 0, QtCore.Qt.AlignCenter)
                self.gaps[tool] = gap
            b = _ToolButton(self, tool)
            b.setText(glyph)
            b.setFont(f)
            b.setCheckable(True)
            b.setFixedSize(theme.px(30), theme.px(30))
            b.clicked.connect(lambda _c=False, t=tool: self.state.set_tool(t))
            group.addButton(b)
            lay.addWidget(b)
            self.buttons[tool] = b
        self.state.changed.connect(self.sync)
        viewport.hub.mode_changed.connect(lambda _m: self.sync())   # Add only in Object Mode
        keymap.notifier.changed.connect(self._update_buttons)     # tooltips follow key changes
        viewport.installEventFilter(self)          # keep the place when the view is resized
        self.sync()

    # --- placement
    def _free(self):
        """Space the toolbar's top-left corner can move in (x0, y0, x1, y1)."""
        m = theme.px(4)
        top = theme.px(4)
        return m, top, max(m, self.vp.width() - self.width() - m), max(top, self.vp.height() - self.height() - m)

    def place(self):
        pos = self.state.toolbar_pos
        if pos is None:
            x, y = theme.px(6), theme.px(46)
        else:
            x0, y0, x1, y1 = self._free()
            x, y = x0 + pos[0] * (x1 - x0), y0 + pos[1] * (y1 - y0)
        x0, y0, x1, y1 = self._free()
        self.move(int(min(max(x, x0), x1)), int(min(max(y, y0), y1)))

    def _set_orientation(self, horizontal):
        self._lay.setDirection(QtWidgets.QBoxLayout.LeftToRight if horizontal
                               else QtWidgets.QBoxLayout.TopToBottom)
        self.grip.horizontal = horizontal
        self.grip.updateGeometry()
        for gap in self.gaps.values():
            _style_gap(gap, horizontal)
        self._lay.invalidate()
        self.adjustSize()

    def _update_buttons(self):
        """Icon (current variant), tooltip with the current keys and the Python command of each button."""
        try:
            for tool, glyph, tip, key in TOOLS:
                b = self.buttons[tool]
                v = variant_info(tool, self.state.variant(tool)) if tool in VARIANTS else None
                icons.set_icon(b, v[2] if v else f"tool_{tool.lower()}")
                name = v[1] if v else TOOL_NAMES[tool]
                text = f"{name} – {v[4]}" if v else tip
                aid = TOOL_ACTIONS.get(tool)
                lines = [text]
                if aid:
                    lines.append(f"Key: {{{aid}}}" + (" (again: next variant)" if v else ""))
                lines.append(f"Tool menu: {{view3d.tool_menu}} → {key}")
                if v:
                    lines.append("Hold or right click: " + ", ".join(x[1] for x in VARIANTS[tool]))
                lines.append("{view3d.toolbar} shows / hides the toolbar")
                b.setToolTip(keymap.render("\n".join(lines)))
                pytips.tag(b, tool_command(v[3] if v else _BUILTIN[tool]))
        except RuntimeError:          # deleted together with its viewport
            pass

    def sync(self):
        try:
            self._update_buttons()
            obj = bpy.context.mode == "OBJECT"
            for tool, b in self.buttons.items():
                b.setChecked(tool == self.state.tool)
                b.setVisible(obj or tool not in OBJECT_ONLY)
            for tool, gap in self.gaps.items():
                gap.setVisible(obj or tool not in OBJECT_ONLY)
            if self.grip.horizontal != self.state.toolbar_horizontal:
                self._set_orientation(self.state.toolbar_horizontal)
            self.setVisible(self.state.toolbar_visible)
            self.adjustSize()
            if self._drag is None:
                self.place()
            self.vp.update()
        except RuntimeError:          # deleted together with its viewport
            pass

    # --- dragging (grip or the toolbar's margins)
    def eventFilter(self, obj, ev):
        try:
            if obj is self.vp:
                if ev.type() == QtCore.QEvent.Resize and self._drag is None:
                    self.place()
                return False
            if obj is self.grip:
                t = ev.type()
                if t == QtCore.QEvent.MouseButtonDblClick and ev.button() == QtCore.Qt.LeftButton:
                    self.state.set_toolbar_pos(None, False)
                    return True
                if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove,
                         QtCore.QEvent.MouseButtonRelease):
                    return self._drag_event(ev)
        except RuntimeError:
            pass
        return False

    def mousePressEvent(self, ev):
        if not self._drag_event(ev):
            ev.accept()               # never let a click on the toolbar reach the 3D view

    def mouseMoveEvent(self, ev):
        self._drag_event(ev)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag_event(ev)
        ev.accept()

    def _drag_event(self, ev):
        t = ev.type()
        gp = self.vp.mapFromGlobal(ev.globalPosition().toPoint())
        if t == QtCore.QEvent.MouseButtonPress and ev.button() == QtCore.Qt.LeftButton:
            self._drag = (gp, self.pos())
            self.raise_()
            return True
        if self._drag is None:
            return False
        if t == QtCore.QEvent.MouseMove:
            start, orig = self._drag
            x0, y0, x1, y1 = self._free()
            p = orig + (gp - start)
            self.move(min(max(p.x(), x0), x1), min(max(p.y(), y0), y1))
            return True
        if t == QtCore.QEvent.MouseButtonRelease:
            self._drag = None
            self._drop()
            return True
        return False

    def _drop(self):
        """Snap to the nearest edges, pick the orientation, store the place for all views."""
        snap = theme.px(self.SNAP)
        x0, y0, x1, y1 = self._free()
        x, y = self.x(), self.y()
        left, right = x - x0 < snap, x1 - x < snap
        top, bottom = y - y0 < snap, y1 - y < snap
        horizontal = self.state.toolbar_horizontal
        if (top or bottom) and not (left or right):
            horizontal = True            # along the top / bottom edge
        elif (left or right) and not (top or bottom):
            horizontal = False           # along the left / right edge
        if horizontal != self.state.toolbar_horizontal:
            # keep the toolbar's centre where it was dropped while it turns
            c = self.geometry().center()
            self._set_orientation(horizontal)
            x0, y0, x1, y1 = self._free()
            x, y = c.x() - self.width() // 2, c.y() - self.height() // 2
            if left:
                x = x0
            if right:
                x = x1
            if top:
                y = y0
            if bottom:
                y = y1
        else:
            x = x0 if left else (x1 if right else x)
            y = y0 if top else (y1 if bottom else y)
        x, y = min(max(x, x0), x1), min(max(y, y0), y1)
        fx = (x - x0) / (x1 - x0) if x1 > x0 else 0.0
        fy = (y - y0) / (y1 - y0) if y1 > y0 else 0.0
        self.state.set_toolbar_pos((fx, fy), horizontal)

    def _menu(self, pos):
        m = QtWidgets.QMenu(self)
        h = self.state.toolbar_horizontal
        m.addAction("Vertical" if h else "Horizontal",
                    lambda: self.state.set_toolbar_pos(self.state.toolbar_pos or (0.0, 0.0), not h))
        m.addAction("Flip to Right" if (self.state.toolbar_pos or (0, 0))[0] < 0.5 else "Flip to Left",
                    self._flip)
        m.addAction("Reset Position", lambda: self.state.set_toolbar_pos(None, False))
        m.addSeparator()
        m.addAction("Hide Toolbar\tT", self.state.toggle_toolbar)
        m.exec(self.mapToGlobal(pos))
        m.deleteLater()

    def _flip(self):
        fx, fy = self.state.toolbar_pos or (0.0, 0.0)
        if self.state.toolbar_pos is None:
            x0, y0, x1, y1 = self._free()
            fy = (self.y() - y0) / (y1 - y0) if y1 > y0 else 0.0
        self.state.set_toolbar_pos((1.0 - fx if 0 < fx < 1 else (1.0 if fx < 0.5 else 0.0), fy))


# ---------------------------------------------------------------- Shift+Space tool menu
class ToolMenu(QtWidgets.QMenu):
    """Like Blender's Shift+Space: the tools with a key each (W / Space / G / R / S / T); pressing the key
    of the active tool again switches to its next variant."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._keys = {}
        title = self.addAction("Tools")
        title.setEnabled(False)
        self.addSeparator()
        obj = bpy.context.mode == "OBJECT"
        for tool, glyph, _tip, key in TOOLS:
            if tool in OBJECT_ONLY and not obj:
                continue
            if tool in GROUP_START:
                self.addSeparator()
            vs = VARIANTS.get(tool)
            entries = [(v[0], v[1], v[2]) for v in vs] if vs else [(None, TOOL_NAMES[tool], f"tool_{tool.lower()}")]
            for i, (vid, name, icon) in enumerate(entries):
                ic = icons.icon(icon)
                label = f"{name}\t{key}" if i == 0 else name
                a = self.addAction(ic, label) if not ic.isNull() else self.addAction(f"{glyph}  {label}")
                a.setCheckable(True)
                a.setChecked(tool == state.tool and (vid is None or vid == state.variant(tool)))
                if a.isChecked():
                    fnt = a.font()
                    fnt.setBold(True)
                    a.setFont(fnt)
                a.triggered.connect(lambda _c=False, t=tool, v=vid: state.set_tool(t, v))
            self._keys[getattr(QtCore.Qt, f"Key_{key}")] = tool

    def keyPressEvent(self, ev):
        tool = self._keys.get(ev.key())
        if tool is not None and not ev.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier):
            self.state.activate(tool)          # the key again: next variant (W: Tweak → Box → Circle → Lasso)
            self.close()
            return
        super().keyPressEvent(ev)


def show_tool_menu(vp):
    m = ToolMenu(tool_state(vp.hub), vp)
    m.exec(QtGui.QCursor.pos())
    m.deleteLater()


# ---------------------------------------------------------------- pivot
def pivot(vp):
    """World position of the gizmo or None (nothing selected / unsupported mode)."""
    ctx = bpy.context
    mode = ctx.mode
    if mode == "OBJECT":
        sel = [o for o in ctx.selected_objects if o.visible_get()]
        if not sel:
            return None
        return sum((o.matrix_world.translation for o in sel), Vector()) / len(sel)
    if mode == "EDIT_MESH":
        cache = getattr(vp, "_gizmo_pivot_cache", None)
        if cache is not None:
            return cache[0]
        p = None
        try:
            from . import editmesh
            r = editmesh.active()
            if r:
                ob, bm = r
                co = [v.co for v in bm.verts if v.select and not v.hide]
                if co:
                    p = ob.matrix_world @ (sum(co, Vector()) / len(co))
        except Exception:
            p = None
        vp._gizmo_pivot_cache = (p,)
        return p
    if mode == "POSE":
        from . import posetransform
        return posetransform.pivot(ctx)
    return None


def invalidate(vp):
    vp._gizmo_pivot_cache = None
    vp._gizmo_orient_cache = None
    vp._gizmo_cage_cache = None


def _selection_points(ctx):
    """World points that span the selection: bounding boxes of objects, selected vertices, bone ends."""
    mode = ctx.mode
    if mode == "OBJECT":
        pts = []
        for o in ctx.selected_objects:
            if o.visible_get():
                mw = o.matrix_world
                pts.extend(mw @ Vector(c) for c in o.bound_box)
        return pts
    if mode == "EDIT_MESH":
        from . import editmesh
        r = editmesh.active()
        if not r:
            return []
        ob, bm = r
        mw = ob.matrix_world
        return [mw @ v.co for v in bm.verts if v.select and not v.hide]
    if mode == "POSE":
        pts = []
        for ob in ctx.view_layer.objects:
            if ob.type == "ARMATURE" and ob.mode == "POSE" and ob.pose is not None:
                mw = ob.matrix_world
                for pb in ob.pose.bones:
                    if pb.select:
                        pts += [mw @ pb.head, mw @ pb.tail]
        return pts
    return []


def cage_bounds(vp):
    """(min, max) world corners of the box around the selection (Scale Cage), or None."""
    cache = getattr(vp, "_gizmo_cage_cache", None)
    if cache is not None:
        return cache[0]
    res = None
    try:
        pts = _selection_points(bpy.context)
        if pts:
            lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
            hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
            res = (lo, hi)
    except Exception:
        res = None
    vp._gizmo_cage_cache = (res,)
    return res


def _cage_point(lo, hi, signs):
    """Point of the cage: signs per axis '+' (max), '-' (min) or '0' (middle)."""
    return Vector([hi[i] if s == "+" else lo[i] if s == "-" else (lo[i] + hi[i]) / 2 for i, s in enumerate(signs)])


def _cage_handles(vp):
    b = cage_bounds(vp)
    if b is None:
        return []
    lo, hi = b
    mats = vp.matrices(vp.width(), vp.height())
    sc = theme.ui_scale
    size = hi - lo
    eps = max(size.length, 1e-6) * 1e-4
    flat = [size[i] <= eps for i in range(3)]
    corners = {}
    for sx in "-+":
        for sy in "-+":
            for sz in "-+":
                q = vp.project(_cage_point(lo, hi, sx + sy + sz), mats)
                if q is None:
                    return []
                corners[sx + sy + sz] = q
    segs = []
    for k, q in corners.items():
        for i in range(3):
            if k[i] == "-":
                k2 = k[:i] + "+" + k[i + 1:]
                segs.append((q, corners[k2]))
    out = [{"id": None, "kind": "cage", "segs": segs, "color": QtGui.QColor("#e8e8e8")}]
    for i, (name, _a, col) in enumerate(AXES):
        if flat[i]:
            continue
        for sgn in "-+":
            signs = ["0", "0", "0"]
            signs[i] = sgn
            q = vp.project(_cage_point(lo, hi, signs), mats)
            signs[i] = "+" if sgn == "-" else "-"
            o = vp.project(_cage_point(lo, hi, signs), mats)
            if q is None or o is None or math.hypot(q.x() - o.x(), q.y() - o.y()) < 12 * sc:
                continue                 # the axis points at the viewer – this side can't be dragged
            out.append({"id": f"C:{sgn}{name}", "kind": "box", "center": q, "color": col})
    if not all(flat):
        for k, q in corners.items():
            out.append({"id": f"C:c{k}", "kind": "box", "center": q, "color": QtGui.QColor("#e8e8e8")})
    return out


# ---------------------------------------------------------------- geometry
def _perp(a):
    """Two unit vectors perpendicular to a."""
    t = Vector((0, 0, 1)) if abs(a.z) < 0.9 else Vector((1, 0, 0))
    u = a.cross(t).normalized()
    return u, a.cross(u).normalized()


def _ring(vp, pv, a, R, mats):
    u, v = _perp(a)
    pts = []
    for i in range(49):
        t = 2 * math.pi * i / 48
        q = vp.project(pv + (u * math.cos(t) + v * math.sin(t)) * R, mats)
        if q is None:
            return []
        pts.append(q)
    return pts


def handles(vp, tool):
    """List of handles. id = "<op>:<axis>" – op G (move) / R (rotate) / S (scale), axis X / Y / Z or
    FREE / VIEW / UNIFORM. kind: 'line' (pts, tip arrow|box), 'ring' (pts), 'circle' (center, r),
    'box' (center)."""
    if tool not in _KIND:
        return []
    if tool == "SCALE" and tool_state(vp.hub).variant("SCALE") == "CAGE":
        return _cage_handles(vp)
    pv = pivot(vp)
    if pv is None:
        return []
    mats = vp.matrices(vp.width(), vp.height())
    oaxes = axes(vp)                    # in the transform orientation (header)
    c = vp.project(pv, mats)
    if c is None:
        return []
    s = vp.pixel_size_at(pv)            # world units per screen pixel at the pivot
    sc = theme.ui_scale
    white = QtGui.QColor("#e8e8e8")
    out = []
    rotate = tool in ("ROTATE", "TRANSFORM")
    move = tool in ("MOVE", "TRANSFORM")
    if rotate:
        R = RING_R * sc * s * (0.82 if tool == "TRANSFORM" else 1.0)
        for name, a, col in oaxes:
            pts = _ring(vp, pv, a, R, mats)
            if pts:
                out.append({"id": f"R:{name}", "kind": "ring", "pts": pts, "color": col})
        out.append({"id": "R:VIEW", "kind": "circle", "center": c, "r": VIEW_RING_R * sc,
                    "color": white, "ring_hit": True})
    if tool in ("MOVE", "SCALE", "TRANSFORM"):
        L = ARROW_LEN * sc * s * (1.12 if tool == "TRANSFORM" else 1.0)
        for name, a, col in oaxes:
            end = vp.project(pv + a * L, mats)
            if end is None:
                continue
            d = end - c
            if math.hypot(d.x(), d.y()) < 10 * sc:      # axis points at the viewer – hide it
                continue
            if tool == "SCALE":
                out.append({"id": f"S:{name}", "kind": "line", "pts": [c, end], "color": col,
                            "tip": "box"})
                continue
            out.append({"id": f"G:{name}", "kind": "line", "pts": [c, end], "color": col,
                        "tip": "arrow"})
            if tool == "TRANSFORM":
                # scale box on the axis, between the centre and the arrow (like Blender's Transform)
                mid = vp.project(pv + a * (L * 0.55), mats)
                if mid is not None:
                    out.append({"id": f"S:{name}", "kind": "box", "center": mid, "color": col})
    if tool == "SCALE":
        # uniform scale: the outer ring (like Blender) – dragging from it scales by the ratio of
        # distances from the pivot, so it must not start right at the pivot
        out.append({"id": "S:UNIFORM", "kind": "circle", "center": c, "r": VIEW_RING_R * sc,
                    "color": white, "ring_hit": True})
    if move:
        out.append({"id": "G:FREE", "kind": "circle", "center": c, "r": CENTER_R * sc, "color": white})
    return out


def _seg_dist(p, a, b):
    ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p.x() - ax) * dx + (p.y() - ay) * dy) / L2))
    return math.hypot(p.x() - (ax + t * dx), p.y() - (ay + t * dy))


def hit(hs, pos):
    """id of the handle under pos (QPointF) or None. Boxes and axis handles win over the centre."""
    sc = theme.ui_scale
    pick = PICK_DIST * sc
    best, best_key = None, None
    for h in hs:
        kind = h["kind"]
        if h["id"] is None:               # drawing only (the scale cage's box)
            continue
        if kind == "circle":
            dc = math.hypot(pos.x() - h["center"].x(), pos.y() - h["center"].y())
            d = abs(dc - h["r"]) if h.get("ring_hit") else max(0.0, dc - h["r"])
        elif kind == "box":
            d = max(0.0, math.hypot(pos.x() - h["center"].x(), pos.y() - h["center"].y()) - 6 * sc)
        elif kind == "line":
            # skip the part inside the centre circle, so the centre stays easy to grab;
            # the arrow head / box at the end is a bit bigger than the line
            a, b = h["pts"]
            dx, dy = b.x() - a.x(), b.y() - a.y()
            ln = math.hypot(dx, dy) or 1.0
            k = min(0.9, (CENTER_R + 4) * sc / ln)
            a = QtCore.QPointF(a.x() + dx * k, a.y() + dy * k)
            d = min(_seg_dist(pos, a, b), math.hypot(pos.x() - b.x(), pos.y() - b.y()) - 4 * sc)
        else:
            pts = h["pts"]
            d = min(_seg_dist(pos, pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        if d > pick:
            continue
        rank = 0 if kind == "box" else (1 if h["id"].split(":")[1] in ("X", "Y", "Z") else 2)
        key = (rank, d)
        if best_key is None or key < best_key:
            best, best_key = h["id"], key
    return best


# ---------------------------------------------------------------- drawing
def paint(vp, p, tool, hover):
    hs = handles(vp, tool)
    if not hs:
        return hs
    sc = theme.ui_scale
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    for h in hs:
        col = HOVER_COLOR if h["id"] == hover else h["color"]
        width = (3.2 if h["id"] == hover else 2.2) * sc
        if h["kind"] == "cage":
            pen = QtGui.QPen(col, 1.2 * sc, QtCore.Qt.DashLine)
            p.setPen(pen)
            p.setBrush(QtCore.Qt.NoBrush)
            for a, b in h["segs"]:
                p.drawLine(a, b)
            continue
        if h["kind"] == "ring":
            p.setPen(QtGui.QPen(col, width))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawPolyline(QtGui.QPolygonF(h["pts"]))
        elif h["kind"] == "box":
            r = (6.5 if h["id"] == hover else 5.5) * sc
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(col)
            ctr = h["center"]
            p.drawRect(QtCore.QRectF(ctr.x() - r, ctr.y() - r, 2 * r, 2 * r))
        elif h["kind"] == "circle":
            p.setPen(QtGui.QPen(col, width * 0.8))
            p.setBrush(QtGui.QColor(255, 255, 255, 40 if h["id"] == hover else 0))
            p.drawEllipse(h["center"], h["r"], h["r"])
        else:
            a, b = h["pts"]
            p.setPen(QtGui.QPen(col, width))
            p.drawLine(a, b)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(col)
            dx, dy = b.x() - a.x(), b.y() - a.y()
            ln = math.hypot(dx, dy) or 1.0
            ux, uy = dx / ln, dy / ln
            if h["tip"] == "arrow":
                size = 13 * sc
                base = QtCore.QPointF(b.x() - ux * size, b.y() - uy * size)
                tipp = QtCore.QPointF(b.x() + ux * 2 * sc, b.y() + uy * 2 * sc)
                w = size * 0.42
                p.drawPolygon(QtGui.QPolygonF([
                    tipp, QtCore.QPointF(base.x() - uy * w, base.y() + ux * w),
                    QtCore.QPointF(base.x() + uy * w, base.y() - ux * w)]))
            else:
                r = 5.5 * sc
                p.drawRect(QtCore.QRectF(b.x() - r, b.y() - r, 2 * r, 2 * r))
    p.restore()
    return hs


# ---------------------------------------------------------------- interaction
def start_drag(vp, handle_id, tool=None):
    """Starts the interactive transform for a handle ("G:X", "R:VIEW", …). True when it started."""
    op, _, axis = handle_id.partition(":")
    if op == "C":
        return _start_cage_drag(vp, axis)
    if op not in ("G", "R", "S"):
        return False
    vp.start_modal(op)
    m = vp._modal
    if not m:
        return False
    m["axis"] = axis if axis in ("X", "Y", "Z") else None
    m["drag"] = True                  # release of the mouse button confirms
    vp._modal_update(m["start"])
    return True


def _start_cage_drag(vp, handle):
    """Scale Cage: scale from the opposite side ("+X" … a side, one axis) or corner ("c+-+", all axes)."""
    b = cage_bounds(vp)
    if b is None:
        return False
    lo, hi = b
    flip = {"+": "-", "-": "+"}
    if handle.startswith("c"):
        signs = handle[1:4]
        pivot_pt = _cage_point(lo, hi, [flip[c] for c in signs])
        axis = None
    else:
        sgn, name = handle[0], handle[1]
        i = "XYZ".index(name)
        signs = ["0", "0", "0"]
        signs[i] = flip[sgn]
        pivot_pt = _cage_point(lo, hi, signs)
        axis = name
    vp.start_modal("S")
    m = vp._modal
    if not m:
        return False
    m["pivot"] = pivot_pt
    m["axis"] = axis
    m["orient_kind"], m["orient"] = "GLOBAL", Matrix.Identity(3)     # the cage is axis-aligned
    m["cage"] = True                  # factor = mouse movement along the handle's direction
    m["drag"] = True
    vp._modal_update(m["start"])
    return True

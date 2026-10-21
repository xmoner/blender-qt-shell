"""Outliner – Blender's View Layer outliner with the Maya Outliner's conveniences.

From Blender: display modes (View Layer, Blender File, Orphan Data), restriction columns (Exclude,
Selectable, Hide in Viewport, Disable in Viewports / Renders, Holdout, Indirect Only) with Ctrl+click to
isolate, Shift+click to apply to the children and drag across a column to set many rows; the filter
popover (collections, objects, contents, children, object types, object state, sort, sync selection);
object contents (animation, data with the bone hierarchy, materials, modifiers, constraints, vertex
groups, filled lazily so big rigs stay fast); collection colour tags; the Outliner key map.

From Maya: wildcard search (* ?), names of hidden objects greyed, F reveals the selection, middle-mouse
drag to re-parent (left-drag works too), drop on empty space to unparent, P / Shift+P parent / unparent,
Shift+click on an arrow opens or closes all levels, a filter menu that stays open while ticking options.

All keys live in keymap.py (area "Outliner") and are listed in the Keyboard Shortcuts window.
"""
import fnmatch

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, icons, keymap, pytips, theme

KEY = QtCore.Qt.UserRole          # item key tuple: ("OBJECT", name), ("BONE", ob, bone), …
ROOT = QtCore.Qt.UserRole + 1     # True for the scene collection row
STATE = QtCore.Qt.UserRole + 2    # per column: last drawn state (avoids redundant setIcon)
LOOK = QtCore.Qt.UserRole + 3     # col 0: (icon shape, tint, italic) of the row
LAZY = ("LAZY",)

# icon tints by role (Blender theme colours)
T_OBJECT, T_DATA, T_MOD, T_CON, T_MAT = "#ffaf29", "#00d4a3", "#84b8ff", "#a7a0ff", "#ea7581"
T_FG, T_DIM, T_TOGGLE_OFF = "#d6d6d6", "#7a7a7a", "#6a6a6a"
COLOR_TAGS = [("NONE", "None", T_FG), ("COLOR_01", "Red", "#e96a6a"), ("COLOR_02", "Orange", "#f0a040"),
              ("COLOR_03", "Yellow", "#e8d250"), ("COLOR_04", "Green", "#78c25a"), ("COLOR_05", "Blue", "#5a9ef0"),
              ("COLOR_06", "Violet", "#a776e0"), ("COLOR_07", "Pink", "#e07ab8"), ("COLOR_08", "Brown", "#a8865c")]
_TAG_COLOR = {k: c for k, _l, c in COLOR_TAGS}

_OB_SHAPE = {"MESH": "mesh", "CURVE": "curve", "SURFACE": "surface", "FONT": "font", "META": "meta",
             "ARMATURE": "armature", "LATTICE": "lattice", "EMPTY": "empty", "CAMERA": "camera_ob", "LIGHT": "light",
             "SPEAKER": "speaker", "LIGHT_PROBE": "lightprobe", "GREASEPENCIL": "gpencil", "GPENCIL": "gpencil",
             "CURVES": "hair", "POINTCLOUD": "pointcloud", "VOLUME": "volume"}

# restriction columns: id, label, icon base (…_on / …_off), tooltip
COLUMNS = [
    ("exclude", "Exclude", "chk", "Exclude from View Layer (collections)"),
    ("select", "Selectable", "select", "Selectable"),
    ("hide", "Hide in Viewport", "eye", "Hide in Viewport (this view layer)"),
    ("viewport", "Disable in Viewports", "monitor", "Disable in Viewports (all view layers)"),
    ("render", "Disable in Renders", "render", "Disable in Renders"),
    ("holdout", "Holdout", "holdout", "Holdout (collections and objects)"),
    ("indirect", "Indirect Only", "indirect", "Indirect Only – Cycles (collections)"),
]
_COL_INFO = {c[0]: c for c in COLUMNS}
DEFAULT_COLS = ("exclude", "hide", "render")
# columns whose normal state is "off" (the icon lights up when the option is set)
_SET_WHEN_ON = {"holdout", "indirect"}

# Blender File / Orphan Data: bpy.data collections shown, with label, icon shape and tint
ID_TYPES = [
    ("actions", "Actions", "action", T_FG), ("armatures", "Armatures", "armature", T_DATA),
    ("brushes", "Brushes", "brush", T_FG), ("cameras", "Cameras", "camera_ob", T_DATA),
    ("collections", "Collections", "collection", T_FG), ("curves", "Curves", "curve", T_DATA),
    ("fonts", "Fonts", "font", T_DATA), ("grease_pencils", "Grease Pencil", "gpencil", T_DATA),
    ("hair_curves", "Hair Curves", "hair", T_DATA), ("images", "Images", "image", T_FG),
    ("lattices", "Lattices", "lattice", T_DATA), ("libraries", "Libraries", "library", T_FG),
    ("lightprobes", "Light Probes", "lightprobe", T_DATA), ("lights", "Lights", "light", T_DATA),
    ("linestyles", "Line Styles", "datablock", T_FG), ("masks", "Masks", "datablock", T_FG),
    ("materials", "Materials", "material", T_MAT), ("meshes", "Meshes", "mesh", T_DATA),
    ("metaballs", "Metaballs", "meta", T_DATA), ("movieclips", "Movie Clips", "movieclip", T_FG),
    ("node_groups", "Node Groups", "nodetree", T_MOD), ("objects", "Objects", "mesh", T_OBJECT),
    ("paint_curves", "Paint Curves", "datablock", T_FG), ("palettes", "Palettes", "datablock", T_FG),
    ("particles", "Particles", "pointcloud", T_FG), ("pointclouds", "Point Clouds", "pointcloud", T_DATA),
    ("scenes", "Scenes", "scene", T_FG), ("sounds", "Sounds", "sound", T_FG),
    ("speakers", "Speakers", "speaker", T_DATA), ("texts", "Texts", "text", T_FG),
    ("textures", "Textures", "texture", T_FG), ("volumes", "Volumes", "volume", T_DATA),
    ("workspaces", "Workspaces", "workspace", T_FG), ("worlds", "Worlds", "world", T_FG),
]

MODES = [("VIEW_LAYER", "View Layer", "view_layer", "Collections and objects of the view layer"),
         ("BLENDER_FILE", "Blender File", "blend_file", "All data-blocks of the file, by type"),
         ("ORPHAN", "Orphan Data", "orphan", "Data-blocks without users – lost when the file is saved and reopened")]

# object type filters: setting key, label, icon, object types (None = all the others)
TYPE_FILTERS = [("t_mesh", "Meshes", "mesh", {"MESH"}), ("t_armature", "Armatures", "armature", {"ARMATURE"}),
                ("t_empty", "Empties", "empty", {"EMPTY"}), ("t_light", "Lights", "light", {"LIGHT"}),
                ("t_camera", "Cameras", "camera_ob", {"CAMERA"}),
                ("t_gpencil", "Grease Pencil", "gpencil", {"GREASEPENCIL", "GPENCIL"}),
                ("t_others", "Others", "curve", None)]
_TYPED = set().union(*(t[3] for t in TYPE_FILTERS if t[3]))

STATES = [("ALL", "All"), ("VISIBLE", "Visible"), ("SELECTED", "Selected"), ("ACTIVE", "Active"),
          ("SELECTABLE", "Selectable")]

# settings (QSettings "outliner/<key>"), with defaults
DEFAULTS = {
    "mode": "VIEW_LAYER", "cols": ",".join(DEFAULT_COLS), "sort_alpha": True, "sync": True, "scroll_active": True,
    "exact": False, "case": False, "collections": True, "objects": True, "contents": True, "children": True,
    "state": "ALL", "invert": False,
    **{t[0]: True for t in TYPE_FILTERS},
}
# the keys that make the filter button light up when changed
_FILTER_KEYS = ("collections", "objects", "contents", "children", "state", "invert") + tuple(t[0] for t in TYPE_FILTERS)

_icon_cache = {}


def _ic(shape, color=T_FG):
    k = (shape, color)
    ic = _icon_cache.get(k)
    if ic is None:
        ic = icons.tinted(shape, color)
        _icon_cache[k] = ic
    return ic


def _toggle_icon(cid, on):
    if cid == "fake":
        return _ic("fake_on" if on else "fake_off", T_FG if on else T_TOGGLE_OFF)
    base = _COL_INFO[cid][2]
    return _ic(f"{base}_on" if on else f"{base}_off", T_FG if on else T_TOGGLE_OFF)


class _StayMenu(QtWidgets.QMenu):
    """Menu that stays open while checkable options are ticked (like Maya's Ctrl+click in Show)."""

    def mouseReleaseEvent(self, ev):
        a = self.activeAction()
        if a is not None and a.isEnabled() and a.isCheckable() and a.menu() is None:
            a.trigger()
            return
        super().mouseReleaseEvent(ev)


def _evpos(ev):
    return ev.position().toPoint() if hasattr(ev, "position") else ev.pos()


def _api(call):
    """Python command for Python tooltips: Qt Shell's Outliner from a script (Blender's bpy.ops.outliner.*
    operators need a Blender Outliner area and fail from a script in Qt Shell)."""
    return f"import qt_shell; qt_shell.api.outliner().{call}"


def _path(data):
    return pytips.data_path(data) if data is not None else ""


def _section(menu, text):
    """Menu section title (QMenu.addSection draws only a line in the Fusion style)."""
    lab = QtWidgets.QLabel(text, menu)
    lab.setFont(menu.font())
    lab.setStyleSheet(f"color: {T_DIM}; font-weight: bold; padding: {theme.px(4)}px {theme.px(8)}px "
                      f"{theme.px(1)}px {theme.px(8)}px;")
    wa = QtWidgets.QWidgetAction(menu)
    wa.setDefaultWidget(lab)
    wa.setEnabled(False)
    menu.addAction(wa)
    return wa


def _check_item(menu, label, icon, checked, on_toggle, tip=None, py=None):
    """Menu row with an icon and a real checkbox – Qt hides the check mark of checkable actions that have
    an icon, so the state would not be visible. Ticking it keeps the menu open (like Maya's Show menu)."""
    w = QtWidgets.QWidget(menu)
    lay = QtWidgets.QHBoxLayout(w)
    lay.setContentsMargins(theme.px(8), theme.px(1), theme.px(10), theme.px(1))
    cb = QtWidgets.QCheckBox(label, w)
    cb.setFont(menu.font())                     # same size as the menu's own rows
    if icon:
        cb.setIcon(_ic(icon))
        cb.setIconSize(QtCore.QSize(theme.px(16), theme.px(16)))
    cb.setChecked(bool(checked))
    if tip:
        cb.setToolTip(tip)
    cb.toggled.connect(on_toggle)
    if py:
        pytips.tag(cb, py)
    lay.addWidget(cb)
    wa = QtWidgets.QWidgetAction(menu)
    wa.setDefaultWidget(w)
    menu.addAction(wa)
    return cb


class _Tree(QtWidgets.QTreeWidget):
    """Tree with restriction-column clicks / drags, Shift+click on arrows, left or middle drag to re-parent."""

    def __init__(self, outliner):
        super().__init__(outliner)
        self.o = outliner
        self._mmb = None
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDrop)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)

    def mousePressEvent(self, ev):
        pos = _evpos(ev)
        it = self.itemAt(pos)
        col = self.columnAt(pos.x())
        if ev.button() == QtCore.Qt.LeftButton and it is not None and col > 0:
            if self.o._restrict_press(it, col, ev.modifiers()):
                ev.accept()
                return
        if ev.button() == QtCore.Qt.LeftButton and it is not None and (ev.modifiers() & QtCore.Qt.ShiftModifier):
            x0 = self.visualRect(self.indexFromItem(it, 0)).x()
            if x0 - self.indentation() <= pos.x() < x0 and it.childCount():
                self.o._expand_all(it, not it.isExpanded())      # Shift+click arrow: all levels
                ev.accept()
                return
        if ev.button() == QtCore.Qt.MiddleButton:
            self._mmb = (pos, it)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        pos = _evpos(ev)
        if self.o._restrict_drag_active():
            if ev.buttons() & QtCore.Qt.LeftButton:
                self.o._restrict_drag(self.itemAt(pos))
            return
        if self._mmb is not None and (ev.buttons() & QtCore.Qt.MiddleButton):
            p0, it = self._mmb
            if it is not None and (pos - p0).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                self._mmb = None
                if not it.isSelected():
                    self.setCurrentItem(it)          # selects it (and the object) like a click
                if it.flags() & QtCore.Qt.ItemIsDragEnabled:
                    self.startDrag(QtCore.Qt.MoveAction | QtCore.Qt.CopyAction)
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self.o._restrict_drag_active():
            self.o._restrict_release()
            return
        if ev.button() == QtCore.Qt.MiddleButton:
            self._mmb = None
        else:
            super().mouseReleaseEvent(ev)
        if self.o._sync_pending:
            QtCore.QTimer.singleShot(0, self.o.sync_selection)

    # drag and drop: only the gesture is read here, the Outliner rebuilds itself afterwards
    def _drop_target(self, ev):
        pos = _evpos(ev)
        it = self.itemAt(pos)
        if it is None:
            return None, "EMPTY"
        r = self.visualItemRect(it)
        y = pos.y() - r.y()
        where = "ABOVE" if y < r.height() * 0.25 else "BELOW" if y > r.height() * 0.75 else "ON"
        if where != "ON":
            it = it.parent()                     # between rows: drop into the row's parent
            if it is None:
                return None, "EMPTY"
        return it, where

    def qtshell_python_at(self, w, pos):
        """Python tooltip of the row / cell under the mouse (pytips hook)."""
        if w is not self.viewport():
            return None
        it = self.itemAt(pos)
        if it is None:
            return None
        col = self.columnAt(pos.x())
        return it.toolTip(col), self.o.cell_python(it, col)

    def dragEnterEvent(self, ev):
        if ev.source() is self:
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev):
        super().dragMoveEvent(ev)
        if ev.source() is not self:
            ev.ignore()
            return
        it, _where = self._drop_target(ev)
        if self.o._drop_allowed(it):
            ev.setDropAction(QtCore.Qt.CopyAction if ev.modifiers() & QtCore.Qt.ControlModifier
                             else QtCore.Qt.MoveAction)
            ev.accept()
        else:
            ev.ignore()

    def dropEvent(self, ev):
        self.o._sync_pending = True             # the release after a drop doesn't reach mouseReleaseEvent
        it, where = self._drop_target(ev)
        link = bool(ev.modifiers() & QtCore.Qt.ControlModifier)
        ev.setDropAction(QtCore.Qt.IgnoreAction)      # never let Qt move the rows itself
        ev.accept()
        QtCore.QTimer.singleShot(0, lambda: (self.o._drop(it, where, link), self.o.sync_selection()))


class Outliner(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.st = {k: self._load(k, v) for k, v in DEFAULTS.items()}
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addLayout(self._build_header())
        self.tree = _Tree(self)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked |
                                  QtWidgets.QAbstractItemView.EditKeyPressed)
        self.tree.setIconSize(QtCore.QSize(theme.px(16), theme.px(16)))
        self.tree.setUniformRowHeights(True)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.itemCollapsed.connect(self._on_collapsed)
        self.tree.installEventFilter(self)       # own keys (before the tree's type-to-search)
        lay.addWidget(self.tree)
        self._sig = None
        self._items = {}          # key → item (first occurrence)
        self._all = []            # (key, item) for every row, duplicates included
        self._expanded = set()    # rows the user opened (kept over rebuilds)
        self._collapsed = set()   # rows the user closed (collections stay closed over rebuilds)
        self._updating = False
        self._last_active = None  # active row key last revealed (sync_selection)
        self._active_item = None
        self._lcs = {}            # collection name → LayerCollection (view layer mode)
        self._cols = []           # restriction / data columns shown, in order
        self._sync_pending = False  # selection sync postponed while a mouse button is down in the tree
        self._rdrag = None        # restriction drag: (column id, new value, set of touched keys)
        hub.data_changed.connect(self.refresh)
        hub.selection_changed.connect(self._on_selection_changed)
        hub.file_loaded.connect(lambda: self.refresh(force=True))
        hub.undo_done.connect(lambda: self.refresh(force=True))
        # hints that mention keys are keymap templates: they follow the user's key changes
        keymap.tip(self.filter, "Search by name – wildcards * and ? work (Maya style).\n"
                                "Focus: {outliner.search} · Clear: {outliner.clear_search}\n"
                                "Show Selected: {outliner.show_selected} · Object Hierarchy: {outliner.show_hierarchy}")
        keymap.tip(self.new_btn, "New Collection inside the active one ({outliner.new_collection})")
        self.refresh(force=True)

    # ------------------------------------------------------------ settings
    @staticmethod
    def _load(key, default):
        try:
            v = QtCore.QSettings("QtShell", "QtShell").value("outliner/" + key, default)
        except Exception:
            return default
        if isinstance(default, bool):
            return v in (True, "true", "1", 1)
        return str(v) if v is not None else default

    def _set_opt(self, key, value, rebuild=True):
        self.st[key] = value
        QtCore.QSettings("QtShell", "QtShell").setValue("outliner/" + key, value)
        self._sync_header()
        if rebuild:
            self.refresh(force=True)

    def _cols_setting(self):
        return [c for c in self.st["cols"].split(",") if c in _COL_INFO]

    def reset_filters(self):
        s = QtCore.QSettings("QtShell", "QtShell")
        for k in _FILTER_KEYS + ("exact", "case"):
            self.st[k] = DEFAULTS[k]
            s.setValue("outliner/" + k, DEFAULTS[k])
        self._sync_header()
        self.refresh(force=True)

    # ------------------------------------------------------------ header
    def _build_header(self):
        h = QtWidgets.QHBoxLayout()
        h.setContentsMargins(2, 2, 2, 0)
        h.setSpacing(2)
        self.mode_btn = QtWidgets.QToolButton(self)
        self.mode_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.mode_btn.setAutoRaise(True)
        self.mode_menu = QtWidgets.QMenu(self.mode_btn)
        self._mode_group = QtGui.QActionGroup(self.mode_menu)
        for mid, label, icon, tip in MODES:
            a = self.mode_menu.addAction(_ic(icon), label)
            a.setCheckable(True)
            a.setToolTip(tip)
            a.setData(mid)
            self._mode_group.addAction(a)
            a.triggered.connect(lambda _c=False, m=mid: self.set_mode(m))
            pytips.tag(a, _api(f"set_mode({mid!r})"))
        self.mode_menu.setToolTipsVisible(True)
        self.mode_btn.setMenu(self.mode_menu)
        h.addWidget(self.mode_btn)
        self.filter = QtWidgets.QLineEdit(self)
        self.filter.setClearButtonEnabled(True)
        self.filter.setPlaceholderText("Search…")
        zi = icons.icon("zoom")
        if not zi.isNull():
            self.filter.addAction(zi, QtWidgets.QLineEdit.LeadingPosition)
        self.filter.textChanged.connect(lambda _t: self._apply_filter())
        pytips.tag(self.filter, _api('search("*name*")   # wildcards * ?, "" clears'))
        h.addWidget(self.filter, 1)
        self.filter_btn = QtWidgets.QToolButton(self)
        self.filter_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.filter_btn.setAutoRaise(True)
        self.filter_menu = _StayMenu(self.filter_btn)
        self.filter_menu.setToolTipsVisible(True)
        self.filter_menu.aboutToShow.connect(self._fill_filter_menu)
        self.filter_btn.setMenu(self.filter_menu)
        self.filter_btn.setToolTip("Filter: restriction columns, sorting, search options, what to show")
        pytips.tag(self.filter_btn, _api("set_option('sort_alpha', True)   # keys: Outliner.DEFAULTS") + "\n"
                   + _api("show_column('select', True)   # exclude, select, hide, viewport, render, holdout, indirect"))
        h.addWidget(self.filter_btn)
        self.new_btn = QtWidgets.QToolButton(self)
        self.new_btn.setAutoRaise(True)
        self.new_btn.setIcon(_ic("collection_new"))
        self.new_btn.clicked.connect(self.new_collection)
        pytips.tag(self.new_btn, _api("new_collection()"))
        h.addWidget(self.new_btn)
        self.purge_btn = QtWidgets.QToolButton(self)
        self.purge_btn.setAutoRaise(True)
        self.purge_btn.setIcon(_ic("trash"))
        self.purge_btn.setText("Purge")
        self.purge_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.purge_btn.setToolTip("Delete all data-blocks without users (and the ones that become unused)")
        self.purge_btn.clicked.connect(self.purge_orphans)
        pytips.tag(self.purge_btn, "bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)")
        h.addWidget(self.purge_btn)
        for b in (self.mode_btn, self.filter_btn, self.new_btn, self.purge_btn):
            b.setIconSize(QtCore.QSize(theme.px(16), theme.px(16)))
        self._sync_header()
        return h

    def _sync_header(self):
        mode = self.st["mode"]
        info = next((m for m in MODES if m[0] == mode), MODES[0])
        self.mode_btn.setIcon(_ic(info[2]))
        self.mode_btn.setToolTip(f"Display Mode: {info[1]} – {info[3]}")
        pytips.tag(self.mode_btn, _api(f"set_mode({mode!r})   # VIEW_LAYER, BLENDER_FILE, ORPHAN"))
        for a in self._mode_group.actions():
            a.setChecked(a.data() == mode)
        changed = any(self.st[k] != DEFAULTS[k] for k in _FILTER_KEYS)
        self.filter_btn.setIcon(_ic("filter_on") if changed else _ic("filter"))
        self.new_btn.setVisible(mode == "VIEW_LAYER")
        self.purge_btn.setVisible(mode == "ORPHAN")

    def set_mode(self, mode):
        if mode == self.st["mode"]:
            return
        self._expanded.clear()
        self._collapsed.clear()
        self._last_active = None
        self._set_opt("mode", mode)

    def _fill_filter_menu(self):
        m = self.filter_menu
        m.clear()
        mode = self.st["mode"]

        def check(menu, label, key, icon=None, rebuild=True, after=None):
            def toggled(on, k=key, r=rebuild):
                self._set_opt(k, on, r)
                if after is not None:
                    after()
            return _check_item(menu, label, icon, self.st[key], toggled,
                               py=_api(f"set_option({key!r}, {not self.st[key]!r})"))

        if mode == "VIEW_LAYER":
            _section(m, "Restriction Toggles")
            cols = self._cols_setting()
            for cid, label, base, tip in COLUMNS:
                _check_item(m, label, base + "_on", cid in cols,
                            lambda on, c=cid: self._toggle_column(c, on), tip,
                            py=_api(f"show_column({cid!r}, {cid not in cols!r})"))
        _section(m, "Options")
        check(m, "Sort Alphabetically", "sort_alpha", "sort_alpha")
        check(m, "Sync Selection", "sync", "sync", rebuild=False)
        check(m, "Scroll to Active", "scroll_active", "hierarchy", rebuild=False)
        _section(m, "Search")
        check(m, "Exact Match", "exact", rebuild=False, after=self._apply_filter)
        check(m, "Case Sensitive", "case", rebuild=False, after=self._apply_filter)
        if mode == "VIEW_LAYER":
            _section(m, "Filter")
            check(m, "Collections", "collections", "collection")
            check(m, "Objects", "objects", "mesh")
            sm = _StayMenu("Object State", m)
            g = QtGui.QActionGroup(sm)
            for sid, label in STATES:
                a = sm.addAction(label)
                a.setCheckable(True)
                a.setChecked(self.st["state"] == sid)
                g.addAction(a)
                a.triggered.connect(lambda _c=False, s=sid: self._set_opt("state", s))
                pytips.tag(a, _api(f"set_option('state', {sid!r})"))
            sm.addSeparator()
            check(sm, "Invert", "invert")
            m.addMenu(sm)
            check(m, "Object Contents", "contents")
            check(m, "Object Children", "children", "hierarchy")
            for key, label, icon, _types in TYPE_FILTERS:
                check(m, label, key, icon)
        m.addSeparator()
        pytips.tag(m.addAction("Reset Filters", self.reset_filters), _api("reset_filters()"))

    def _toggle_column(self, cid, on):
        cols = self._cols_setting()
        if on and cid not in cols:
            cols.append(cid)
        elif not on and cid in cols:
            cols.remove(cid)
        order = [c[0] for c in COLUMNS]
        cols.sort(key=order.index)
        self._set_opt("cols", ",".join(cols))

    # ------------------------------------------------------------ structure
    def _signature(self):
        mode = self.st["mode"]
        if mode != "VIEW_LAYER":
            sig = [mode]
            for attr, *_r in ID_TYPES:
                coll = getattr(bpy.data, attr, None)
                if coll is None:
                    continue
                if mode == "ORPHAN":
                    sig.append((attr, tuple(sorted(i.name for i in coll if self._is_orphan(i)))))
                else:
                    sig.append((attr, len(coll), tuple(i.name for i in coll) if len(coll) < 400 else ()))
            return tuple(sig)
        scene = bpy.context.scene
        vl = bpy.context.view_layer

        def ob_sig(o):
            d = o.data
            ad = o.animation_data
            return (o.name, o.parent.name if o.parent else "", o.type, d.name if d else "",
                    tuple(m.name for m in o.modifiers), tuple(c.name for c in o.constraints),
                    len(o.vertex_groups), len(d.bones) if o.type == "ARMATURE" and d else 0,
                    tuple(s.material.name if s.material else "" for s in o.material_slots),
                    ad.action.name if ad is not None and ad.action is not None else "")

        def coll_sig(c):
            return (c.name, c.color_tag, tuple(coll_sig(ch) for ch in c.children), tuple(ob_sig(o) for o in c.objects))

        state = ()
        if self.st["state"] != "ALL":       # the state filter depends on selection / visibility
            state = tuple(sorted(self._object_filter()))
        return (mode, scene.name, vl.name, coll_sig(scene.collection), state)

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

    def _on_selection_changed(self):
        if self.st["state"] != "ALL":
            self.refresh()
        self.sync_selection()

    def _remember_expanded(self):
        for key, it in self._all:
            if _alive(it) and it.isExpanded():
                self._expanded.add(key)

    def _setup_columns(self):
        mode = self.st["mode"]
        self._cols = self._cols_setting() if mode == "VIEW_LAYER" else ["users", "fake"]
        n = 1 + len(self._cols)
        self.tree.setColumnCount(n)
        hi = QtWidgets.QTreeWidgetItem()
        hi.setText(0, "Name")
        for i, cid in enumerate(self._cols, 1):
            if cid == "users":
                hi.setText(i, "#")
                hi.setToolTip(i, "Users")
            elif cid == "fake":
                hi.setIcon(i, _ic("fake_on"))
                hi.setToolTip(i, "Fake User – keep the data-block even without users")
            else:
                hi.setIcon(i, _toggle_icon(cid, True))
                hi.setToolTip(i, _COL_INFO[cid][3] + "\nClick: toggle · Ctrl+click: isolate · "
                                                      "Shift+click: with children · drag: set many rows")
        self.tree.setHeaderItem(hi)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for i in range(1, n):
            hdr.setSectionResizeMode(i, QtWidgets.QHeaderView.Fixed)
            self.tree.setColumnWidth(i, theme.px(30 if self._cols[i - 1] == "users" else 22))

    def _rebuild(self):
        self._updating = True
        self._remember_expanded()
        scroll = self.tree.verticalScrollBar().value()
        self.tree.clear()
        self._items = {}
        self._all = []
        self._active_item = None
        self._setup_columns()
        mode = self.st["mode"]
        if mode == "VIEW_LAYER":
            self._build_view_layer()
        else:
            self._build_data(orphan=(mode == "ORPHAN"))
        for key, it in list(self._all):
            if key in self._collapsed:
                continue
            if (key[0] == "COLLECTION" and mode == "VIEW_LAYER") or key in self._expanded:
                it.setExpanded(True)          # also fills lazy rows (itemExpanded)
        self._updating = False
        self._update_states()
        self.sync_selection()
        self._apply_filter()
        QtCore.QTimer.singleShot(0, lambda: self.tree.verticalScrollBar().setValue(scroll))

    def _new(self, parent_item, text, key, shape=None, tint=T_FG, editable=False, dim=False):
        it = QtWidgets.QTreeWidgetItem([text])
        if shape:
            it.setIcon(0, _ic(shape, tint))
        it.setData(0, KEY, key)
        it.setData(0, ROOT, False)
        it.setData(0, LOOK, (shape, tint, dim))
        flags = QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled
        if editable:
            flags |= QtCore.Qt.ItemIsEditable
        if key[0] in ("OBJECT", "COLLECTION"):
            flags |= QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled
        it.setFlags(flags)
        if dim:
            f = it.font(0)
            f.setItalic(True)
            it.setFont(0, f)
        if parent_item is not None:
            parent_item.addChild(it)
        self._items.setdefault(key, it)
        self._all.append((key, it))
        return it

    # --- view layer
    def _object_filter(self):
        """Names of the view layer's objects that pass the object type / state filters."""
        st = self.st
        vl = bpy.context.view_layer
        types_on = set()
        for key, _l, _i, types in TYPE_FILTERS:
            if types and st[key]:
                types_on |= types
        others = st["t_others"]
        state = st["state"]
        active = vl.objects.active
        out = set()
        for ob in vl.objects:
            if not (ob.type in types_on or (ob.type not in _TYPED and others)):
                continue
            if state == "ALL":
                ok = True
            elif state == "VISIBLE":
                ok = ob.visible_get()
            elif state == "SELECTED":
                ok = ob.select_get()
            elif state == "ACTIVE":
                ok = ob == active
            else:
                ok = ob.visible_get() and not ob.hide_select
            if st["invert"] and state != "ALL":
                ok = not ok
            if ok:
                out.add(ob.name)
        return out

    def _build_view_layer(self):
        ctx = bpy.context
        scene = ctx.scene
        vl = ctx.view_layer
        self._lcs = {}

        def walk(lc):
            self._lcs[lc.collection.name] = lc
            for ch in lc.children:
                walk(ch)
        walk(vl.layer_collection)
        root = self._new(None, scene.name, ("COLLECTION", scene.collection.name), "scene", T_FG)
        root.setData(0, ROOT, True)
        root.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsDropEnabled)
        self.tree.addTopLevelItem(root)
        ok = self._object_filter() if self.st["objects"] else set()
        if self.st["collections"]:
            self._add_layer_collection(root, vl.layer_collection, ok)
        else:
            objs = list(vl.objects)
            self._add_objects(root, objs, {o.name for o in objs}, ok, flat=not self.st["children"])

    def _add_layer_collection(self, parent_item, lc, ok):
        for ch in lc.children:
            c = ch.collection
            it = self._new(parent_item, c.name, ("COLLECTION", c.name), "collection",
                           _TAG_COLOR.get(c.color_tag, T_FG), editable=True)
            self._add_layer_collection(it, ch, ok)
        if self.st["objects"]:
            objs = list(lc.collection.objects)
            self._add_objects(parent_item, objs, {o.name for o in objs}, ok, flat=not self.st["children"])

    def _sorted(self, obs):
        return sorted(obs, key=lambda o: o.name.lower()) if self.st["sort_alpha"] else list(obs)

    def _add_objects(self, parent_item, objs, in_coll, ok, flat):
        if flat:
            for ob in self._sorted(objs):
                if ob.name in ok:
                    self._add_object(parent_item, ob, in_coll, set(), ok, recurse=False)
            return
        for ob in self._sorted(objs):
            if ob.parent is not None and ob.parent.name in in_coll:
                continue
            self._add_object(parent_item, ob, in_coll, set(), ok)

    def _add_object(self, parent_item, ob, in_coll, chain, ok, dim=False, recurse=True):
        container = parent_item
        if ob.name in ok:
            container = self._new(parent_item, ob.name, ("OBJECT", ob.name), _OB_SHAPE.get(ob.type, "datablock"),
                                  T_OBJECT, editable=True, dim=dim)
        if recurse:
            chain = chain | {ob.name}
            for ch in self._sorted(ob.children):
                if ch.name in chain:
                    continue
                # children from another collection are shown greyed under their parent, like Blender;
                # children of a filtered-out object move up to the nearest shown row
                self._add_object(container, ch, in_coll, chain, ok, dim=dim or ch.name not in in_coll)
        if container is not parent_item and self.st["contents"] and self._has_contents(ob):
            lazy = QtWidgets.QTreeWidgetItem(["…"])
            lazy.setData(0, KEY, LAZY + (ob.name,))
            lazy.setFlags(QtCore.Qt.ItemIsEnabled)
            container.addChild(lazy)

    @staticmethod
    def _has_contents(ob):
        return bool(ob.data is not None or len(ob.modifiers) or len(ob.constraints)
                    or len(ob.vertex_groups) or (ob.animation_data is not None and ob.animation_data.action))

    def _on_collapsed(self, it):
        if self._updating:
            return
        k = it.data(0, KEY)
        if k:
            self._collapsed.add(k)
            self._expanded.discard(k)

    def _on_expanded(self, it):
        if not self._updating:
            k = it.data(0, KEY)
            if k:
                self._collapsed.discard(k)
                self._expanded.add(k)
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
                if k in self._expanded and k not in self._collapsed and _alive(child) and child.childCount() \
                        and _is_under(child, it):
                    child.setExpanded(True)
        finally:
            self._updating = was
        self._update_states()
        if not was:
            self.sync_selection()
            self._apply_filter()

    def _fill_contents(self, it, ob):
        """Blender order: animation, object data (bones, materials), modifiers, constraints, vertex groups."""
        n = ob.name
        pos = 0
        ad = ob.animation_data
        if ad is not None and ad.action is not None:
            ait = self._new(None, ad.action.name, ("ACTION", n), "action", T_FG, editable=True)
            ait.setToolTip(0, "Animation – the object's action")
            it.insertChild(pos, ait)
            pos += 1
        d = ob.data
        if d is not None:
            dit = self._new(None, d.name, ("DATA", n), _OB_SHAPE.get(ob.type, "datablock"), T_DATA, editable=True)
            it.insertChild(pos, dit)
            if ob.type == "ARMATURE":
                for b in d.bones:
                    if b.parent is None:
                        self._add_bone(dit, ob, b)
            for i, slot in enumerate(ob.material_slots):
                if slot.material is not None:
                    self._new(dit, slot.material.name, ("MAT", n, i), "material", T_MAT, editable=True)
        if len(ob.modifiers):
            g = self._new(it, "Modifiers", ("MODS", n), "modifier", T_MOD)
            for m in ob.modifiers:
                self._new(g, m.name, ("MOD", n, m.name), "modifier", T_MOD, editable=True)
        if len(ob.constraints):
            g = self._new(it, "Constraints", ("CONS", n), "constraint", T_CON)
            for c in ob.constraints:
                self._new(g, c.name, ("CON", n, c.name), "constraint", T_CON, editable=True)
        if len(ob.vertex_groups):
            g = self._new(it, "Vertex Groups", ("VGROUPS", n), "vgroup", T_DATA)
            for vg in ob.vertex_groups:
                self._new(g, vg.name, ("VGROUP", n, vg.name), "vgroup", T_DATA, editable=True)

    def _add_bone(self, parent_item, ob, bone):
        it = self._new(parent_item, bone.name, ("BONE", ob.name, bone.name), "bone", T_DATA, editable=True)
        for ch in bone.children:
            self._add_bone(it, ob, ch)

    def _fill_armatures(self):
        """Fill the lazy contents of armatures (so a search finds bones / rig controls)."""
        for key, it in list(self._all):
            if key[0] != "OBJECT" or not _alive(it) or not it.childCount():
                continue
            last = it.child(it.childCount() - 1)
            lk = last.data(0, KEY)
            ob = bpy.data.objects.get(key[1])
            if lk and lk[0] == "LAZY" and ob is not None and ob.type == "ARMATURE":
                was = self._updating
                self._updating = True
                try:
                    it.removeChild(last)
                    self._fill_contents(it, ob)
                finally:
                    self._updating = was
                self._update_states()

    # --- blender file / orphan data
    @staticmethod
    def _is_orphan(idb):
        try:
            return idb.users == 0 or (idb.use_fake_user and idb.users == 1)
        except Exception:
            return False

    def _build_data(self, orphan):
        for attr, label, shape, tint in ID_TYPES:
            coll = getattr(bpy.data, attr, None)
            if coll is None or not len(coll):
                continue
            ids = [i for i in coll if not orphan or self._is_orphan(i)]
            if not ids:
                continue
            cat = self._new(None, label, ("IDTYPE", attr), shape, tint)
            cat.setText(1, str(len(ids)))
            cat.setTextAlignment(1, QtCore.Qt.AlignCenter)
            cat.setForeground(1, QtGui.QBrush(QtGui.QColor(T_DIM)))
            self.tree.addTopLevelItem(cat)
            if self.st["sort_alpha"]:
                ids.sort(key=lambda i: i.name.lower())
            for idb in ids:
                s = _OB_SHAPE.get(idb.type, "datablock") if attr == "objects" else shape
                it = self._new(cat, idb.name, ("ID", attr, idb.name), s, tint, editable=idb.library is None,
                               dim=idb.library is not None)
                if idb.library is not None:
                    it.setToolTip(0, f"Linked from {idb.library.filepath}")

    # ------------------------------------------------------------ restriction state
    def _lc(self, name):
        lc = self._lcs.get(name)
        if lc is not None:
            try:
                lc.name
                return lc
            except ReferenceError:
                pass

        def find(l):
            if l.collection.name == name:
                return l
            for ch in l.children:
                r = find(ch)
                if r:
                    return r
            return None
        lc = find(bpy.context.view_layer.layer_collection)
        if lc is not None:
            self._lcs[name] = lc
        return lc

    @staticmethod
    def _pbone(key):
        ob = bpy.data.objects.get(key[1])
        if ob is None or ob.type != "ARMATURE":
            return None, None, None
        b = ob.data.bones.get(key[2])
        pb = ob.pose.bones.get(key[2]) if ob.pose is not None else None
        return ob, b, pb

    @staticmethod
    def _bone_hide_target(b, pb):
        return pb if pb is not None and hasattr(pb, "hide") else b

    @staticmethod
    def _id(key):
        coll = getattr(bpy.data, key[1], None)
        return coll.get(key[2]) if coll is not None else None

    def _get(self, key, cid):
        """(supported, on) of restriction column cid for the row key; on = visible / enabled
        (holdout / indirect: on = the option is set)."""
        kind = key[0]
        try:
            if kind == "COLLECTION":
                c = bpy.data.collections.get(key[1])
                if c is None:                         # the scene collection
                    return False, False
                lc = self._lc(key[1])
                if cid == "exclude":
                    return lc is not None, lc is not None and not lc.exclude
                if cid == "select":
                    return True, not c.hide_select
                if cid == "hide":
                    return lc is not None, lc is not None and not lc.hide_viewport
                if cid == "viewport":
                    return True, not c.hide_viewport
                if cid == "render":
                    return True, not c.hide_render
                if cid == "holdout":
                    return lc is not None, lc is not None and lc.holdout
                if cid == "indirect":
                    return lc is not None, lc is not None and lc.indirect_only
            elif kind == "OBJECT":
                ob = bpy.data.objects.get(key[1])
                if ob is None:
                    return False, False
                if cid == "select":
                    return True, not ob.hide_select
                if cid == "hide":
                    try:
                        return True, not ob.hide_get()
                    except RuntimeError:
                        return False, False
                if cid == "viewport":
                    return True, not ob.hide_viewport
                if cid == "render":
                    return True, not ob.hide_render
                if cid == "holdout":
                    return hasattr(ob, "is_holdout"), bool(getattr(ob, "is_holdout", False))
            elif kind == "BONE":
                _ob, b, pb = self._pbone(key)
                if b is None:
                    return False, False
                if cid == "select":
                    return hasattr(b, "hide_select"), not getattr(b, "hide_select", False)
                if cid == "hide":
                    return True, not self._bone_hide_target(b, pb).hide
            elif kind == "MOD":
                ob = bpy.data.objects.get(key[1])
                m = ob.modifiers.get(key[2]) if ob is not None else None
                if m is None:
                    return False, False
                if cid == "viewport":
                    return True, m.show_viewport
                if cid == "render":
                    return True, m.show_render
            elif kind == "CON":
                ob = bpy.data.objects.get(key[1])
                c = ob.constraints.get(key[2]) if ob is not None else None
                if c is not None and cid in ("hide", "viewport"):
                    return True, c.enabled
            elif kind == "ID" and cid == "fake":
                idb = self._id(key)
                if idb is not None:
                    return idb.library is None, idb.use_fake_user
        except (ReferenceError, AttributeError):
            pass
        return False, False

    def _set(self, key, cid, on):
        kind = key[0]
        try:
            if kind == "COLLECTION":
                c = bpy.data.collections.get(key[1])
                if c is None:
                    return
                lc = self._lc(key[1])
                if cid == "exclude" and lc is not None:
                    lc.exclude = not on
                elif cid == "select":
                    c.hide_select = not on
                elif cid == "hide" and lc is not None:
                    lc.hide_viewport = not on
                elif cid == "viewport":
                    c.hide_viewport = not on
                elif cid == "render":
                    c.hide_render = not on
                elif cid == "holdout" and lc is not None:
                    lc.holdout = on
                elif cid == "indirect" and lc is not None:
                    lc.indirect_only = on
            elif kind == "OBJECT":
                ob = bpy.data.objects.get(key[1])
                if ob is None:
                    return
                if cid == "select":
                    ob.hide_select = not on
                    if not on:
                        ob.select_set(False)
                elif cid == "hide":
                    ob.hide_set(not on)
                elif cid == "viewport":
                    ob.hide_viewport = not on
                elif cid == "render":
                    ob.hide_render = not on
                elif cid == "holdout" and hasattr(ob, "is_holdout"):
                    ob.is_holdout = on
            elif kind == "BONE":
                _ob, b, pb = self._pbone(key)
                if b is None:
                    return
                if cid == "select" and hasattr(b, "hide_select"):
                    b.hide_select = not on
                elif cid == "hide":
                    self._bone_hide_target(b, pb).hide = not on
            elif kind == "MOD":
                ob = bpy.data.objects.get(key[1])
                m = ob.modifiers.get(key[2]) if ob is not None else None
                if m is not None:
                    if cid == "viewport":
                        m.show_viewport = on
                    elif cid == "render":
                        m.show_render = on
            elif kind == "CON":
                ob = bpy.data.objects.get(key[1])
                c = ob.constraints.get(key[2]) if ob is not None else None
                if c is not None and cid in ("hide", "viewport"):
                    c.enabled = on
            elif kind == "ID" and cid == "fake":
                idb = self._id(key)
                if idb is not None and idb.library is None:
                    idb.use_fake_user = on
        except (RuntimeError, ReferenceError, AttributeError) as e:
            bridge.log(f"Outliner: {e}", "WARNING")

    def _update_states(self):
        self._updating = True
        try:
            vl = bpy.context.view_layer
            for key, it in self._all:
                if not _alive(it):
                    continue
                kind = key[0]
                for i, cid in enumerate(self._cols, 1):
                    if cid == "users":
                        if kind == "ID":
                            idb = self._id(key)
                            txt = str(idb.users) if idb is not None else ""
                            if it.text(i) != txt:
                                it.setText(i, txt)
                                it.setTextAlignment(i, QtCore.Qt.AlignCenter)
                        continue
                    state = self._get(key, cid)
                    if it.data(i, STATE) == state:
                        continue
                    it.setData(i, STATE, state)
                    ok, on = state
                    it.setIcon(i, _toggle_icon(cid, on) if ok else QtGui.QIcon())
                    it.setToolTip(i, (_COL_INFO[cid][1] if cid in _COL_INFO else "Fake User") if ok else "")
                look = it.data(0, LOOK)
                if not look:
                    continue
                # greyed names / icons: hidden objects (Maya), excluded / hidden collections (Blender)
                shape, tint, italic = look
                dim = False
                if kind == "OBJECT":
                    ob = bpy.data.objects.get(key[1])
                    if ob is not None:
                        try:
                            dim = not ob.visible_get(view_layer=vl)
                        except Exception:
                            dim = ob.hide_viewport
                elif kind == "COLLECTION" and not it.data(0, ROOT):
                    lc = self._lc(key[1])
                    c = bpy.data.collections.get(key[1])
                    dim = bool((lc is not None and (lc.exclude or lc.hide_viewport)) or (c is not None and c.hide_viewport))
                    if c is not None:
                        tint = _TAG_COLOR.get(c.color_tag, T_FG)
                elif kind == "BONE":
                    _ob, b, pb = self._pbone(key)
                    dim = bool(b is not None and self._bone_hide_target(b, pb).hide)
                elif kind == "MOD":
                    ob = bpy.data.objects.get(key[1])
                    m = ob.modifiers.get(key[2]) if ob is not None else None
                    dim = m is not None and not m.show_viewport
                elif kind == "CON":
                    ob = bpy.data.objects.get(key[1])
                    c = ob.constraints.get(key[2]) if ob is not None else None
                    dim = c is not None and not c.enabled
                state = (dim, tint)
                if it.data(0, STATE) == state:
                    continue
                it.setData(0, STATE, state)
                if shape:
                    it.setIcon(0, _ic(shape, T_DIM if dim else tint))
                it.setForeground(0, QtGui.QBrush(QtGui.QColor(T_DIM)) if dim or italic else QtGui.QBrush())
        finally:
            self._updating = False

    # ------------------------------------------------------------ restriction clicks
    def _restrict_press(self, it, col, mods):
        """Left press in a restriction column. True when handled (no row selection)."""
        if col - 1 >= len(self._cols):
            return False
        cid = self._cols[col - 1]
        key = it.data(0, KEY)
        if cid == "users" or not key:
            return True
        ok, on = self._get(key, cid)
        if not ok:
            return True
        new = not on
        if mods & QtCore.Qt.ControlModifier:
            self._isolate(key, cid)
        elif mods & QtCore.Qt.ShiftModifier:
            self._set(key, cid, new)
            for k in self._descendant_keys(it):
                if self._get(k, cid)[0]:
                    self._set(k, cid, new)
            self._after_toggle("Toggle Visibility")
        else:
            self._set(key, cid, new)
            self._rdrag = (cid, new, {key}, it)
            self._update_states()
            self._redraw_viewport()
        return True

    def _restrict_drag_active(self):
        return self._rdrag is not None

    def _restrict_drag(self, it):
        if it is None or self._rdrag is None:
            return
        cid, new, done, last = self._rdrag
        # a fast mouse skips rows: walk every visible row between the last one and this one
        rows = [it]
        if last is not None and _alive(last) and last is not it:
            t = self.tree
            down = t.visualItemRect(it).y() > t.visualItemRect(last).y()
            step = t.itemBelow if down else t.itemAbove
            rows, cur = [], step(last)
            while cur is not None and len(rows) < 10000:
                rows.append(cur)
                if cur is it:
                    break
                cur = step(cur)
            else:
                rows = [it]
        self._rdrag = (cid, new, done, it)
        changed = False
        for row in rows:
            key = row.data(0, KEY)
            if not key or key in done:
                continue
            done.add(key)
            ok, on = self._get(key, cid)
            if ok and on != new:
                self._set(key, cid, new)
                changed = True
        if changed:
            self._update_states()
            self._redraw_viewport()

    def _restrict_release(self):
        if self._rdrag is not None:
            self._rdrag = None
            self._after_toggle("Toggle Visibility")

    def _after_toggle(self, msg):
        bridge.undo_push(msg)
        self._update_states()
        self._redraw_viewport()
        if self.st["state"] != "ALL":
            self.refresh()

    def _redraw_viewport(self):
        vp = getattr(self.hub, "viewport", None)
        if vp is not None:
            vp.request_redraw()

    def _descendant_keys(self, it):
        out = []
        for i in range(it.childCount()):
            ch = it.child(i)
            k = ch.data(0, KEY)
            if k and k[0] != "LAZY":
                out.append(k)
            out += self._descendant_keys(ch)
        return out

    def _isolate(self, key, cid):
        """Ctrl+click (Blender): only this row – with its parents and children – stays on;
        Ctrl+click again on the isolated row turns all rows of its kind back on."""
        it = self._items.get(key)
        if it is None:
            return
        if cid in _SET_WHEN_ON:                     # holdout / indirect: nothing to isolate
            self._set(key, cid, not self._get(key, cid)[1])
            self._after_toggle("Toggle")
            return
        keep = {key}
        p = it.parent()
        while p is not None:
            k = p.data(0, KEY)
            if k:
                keep.add(k)
            p = p.parent()
        keep |= set(self._descendant_keys(it))
        same = list(dict.fromkeys(k for k, _i in self._all if k[0] == key[0] and self._get(k, cid)[0]))
        others = [k for k in same if k not in keep]
        isolated = self._get(key, cid)[1] and all(not self._get(k, cid)[1] for k in others)
        for k in same:
            self._set(k, cid, True if isolated else k in keep)
        self._after_toggle("Isolate")

    # ------------------------------------------------------------ search
    def _matcher(self):
        text = self.filter.text().strip()
        if not text:
            return None
        case = self.st["case"]
        exact = self.st["exact"]
        pat = text if case else text.lower()
        if any(ch in pat for ch in "*?["):          # Maya-style wildcards
            if not exact:
                pat = ("" if pat.startswith("*") else "*") + pat + ("" if pat.endswith("*") else "*")

            def match(name):
                return fnmatch.fnmatchcase(name if case else name.lower(), pat)
            return match

        def match(name):
            n = name if case else name.lower()
            return n == pat if exact else pat in n
        return match

    def _apply_filter(self):
        match = self._matcher()
        if match is not None and self.st["mode"] == "VIEW_LAYER":
            self._fill_armatures()
        hl = QtGui.QBrush(QtGui.QColor(255, 160, 51, 50))
        none = QtGui.QBrush()

        def visit(it):
            key = it.data(0, KEY) or ("",)
            if key[0] == "LAZY":
                it.setHidden(match is not None)
                return False
            hit = match is not None and not it.data(0, ROOT) and key[0] != "IDTYPE" and match(it.text(0))
            child_hit = False
            for i in range(it.childCount()):
                if visit(it.child(i)):
                    child_hit = True
            it.setBackground(0, hl if hit else none)
            it.setHidden(not (match is None or hit or child_hit or it.data(0, ROOT)))
            if match is not None and child_hit and not it.isExpanded():
                it.setExpanded(True)
            return hit or child_hit

        was = self._updating
        self._updating = True
        try:
            for i in range(self.tree.topLevelItemCount()):
                visit(self.tree.topLevelItem(i))
        finally:
            self._updating = was

    # ------------------------------------------------------------ selection
    def _active_key(self):
        ctx = bpy.context
        active = ctx.view_layer.objects.active
        if active is None:
            return None
        if self.st["mode"] != "VIEW_LAYER":
            return ("ID", "objects", active.name)
        if ctx.mode == "POSE" and active.type == "ARMATURE" and active.data.bones.active:
            return ("BONE", active.name, active.data.bones.active.name)
        return ("OBJECT", active.name)

    def sync_selection(self):
        if self._updating:
            return
        if QtWidgets.QApplication.mouseButtons() != QtCore.Qt.NoButton and self.tree.viewport().underMouse():
            # a press / drag in the tree is in progress: re-syncing now would replace the rows just
            # pressed (e.g. an unselectable object) and Qt would have nothing to drag – sync on release
            self._sync_pending = True
            return
        self._sync_pending = False
        self._updating = True
        try:
            ctx = bpy.context
            sel = {o.name for o in ctx.selected_objects}
            active = ctx.view_layer.objects.active
            pose = ctx.mode == "POSE"
            sync = self.st["sync"]
            sel_bones = set()
            if pose:
                for o in ctx.view_layer.objects:
                    if o.type == "ARMATURE" and o.mode == "POSE" and o.pose is not None:
                        sel_bones.update((o.name, pb.name) for pb in o.pose.bones if pb.select)
            act_key = self._active_key()
            if act_key != self._last_active:
                # a new active object / bone (picked in the viewport…): open the rows down to it,
                # like Blender's Scroll to Active – once per change, so it can be collapsed again
                self._last_active = act_key
                if act_key is not None and sync and self.st["scroll_active"]:
                    self._reveal(act_key)
            self.tree.blockSignals(True)
            if sync:
                for key, it in self._all:
                    if not _alive(it):
                        continue
                    if key[0] == "OBJECT":
                        # in Pose mode the armature stays selected too (as in Blender)
                        it.setSelected(key[1] in sel)
                    elif key[0] == "BONE":
                        it.setSelected((key[1], key[2]) in sel_bones)
                    elif key[0] == "ID" and key[1] == "objects":
                        it.setSelected(key[2] in sel)
            # the active row is drawn bold (Blender draws it brighter)
            cur = self._items.get(act_key) if act_key is not None else None
            if cur is None and active is not None:
                cur = self._items.get(("OBJECT", active.name))
            if self._active_item is not cur:
                for it, bold in ((self._active_item, False), (cur, True)):
                    if it is not None and _alive(it):
                        f = it.font(0)
                        f.setBold(bold)
                        it.setFont(0, f)
                self._active_item = cur
            if sync and cur is not None and _alive(cur) and _shown(cur):
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
            k = p.data(0, KEY)
            if k:
                self._collapsed.discard(k)
            p = p.parent()
        self.tree.scrollToItem(it, QtWidgets.QAbstractItemView.EnsureVisible)

    def _on_tree_selection(self):
        if self._updating or not self.st["sync"]:
            return
        ctx = bpy.context
        items = self.tree.selectedItems()
        keys = [it.data(0, KEY) for it in items if it.data(0, KEY)]
        cur = self.tree.currentItem()
        cur_key = cur.data(0, KEY) if cur is not None else None
        if ctx.mode == "POSE":
            if any(k[0] == "BONE" for k in keys):
                self._select_bones(keys, cur_key)
            return
        if ctx.mode != "OBJECT":
            return
        names = []
        for key in keys:
            if key[0] == "COLLECTION":
                self._activate_collection(key[1])
            elif key[0] == "ID":
                if key[1] == "objects":
                    names.append(key[2])
            elif key[0] not in ("LAZY", "IDTYPE") and len(key) > 1:
                names.append(key[1])            # contents (data, bones, modifiers…) select their object
        for o in ctx.view_layer.objects:
            try:
                o.select_set(o.name in names and not o.hide_select)
            except RuntimeError:
                pass
        act = None
        if cur_key and cur_key[0] == "ID" and cur_key[1] == "objects":
            act = bpy.data.objects.get(cur_key[2])
        elif cur_key and cur_key[0] not in ("COLLECTION", "LAZY", "IDTYPE", "ID") and cur_key[1] in names:
            act = bpy.data.objects.get(cur_key[1])
        elif names:
            act = bpy.data.objects.get(names[-1])
        if act is not None and act.name in ctx.view_layer.objects:
            ctx.view_layer.objects.active = act
            if cur_key:
                self._activate_content(act, cur_key)
        bridge.undo_push("Outliner Select")

    def _select_bones(self, keys, cur_key):
        bones = {(k[1], k[2]) for k in keys if k[0] == "BONE"}
        for o in bpy.context.view_layer.objects:
            if o.type == "ARMATURE" and o.mode == "POSE" and o.pose is not None:
                for pb in o.pose.bones:
                    pb.select = (o.name, pb.name) in bones
        if cur_key and cur_key[0] == "BONE":
            ob = bpy.data.objects.get(cur_key[1])
            if ob is not None:
                b = ob.data.bones.get(cur_key[2])
                if b is not None:
                    ob.data.bones.active = b
        bridge.undo_push("Select Bones")

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
        lc = self._lc(name)
        if lc is not None:
            bpy.context.view_layer.active_layer_collection = lc

    # ------------------------------------------------------------ rename
    def _on_item_changed(self, it, col):
        if self._updating or col != 0:
            return
        key = it.data(0, KEY)
        if not key or it.data(0, ROOT):
            return
        new = it.text(0).strip()
        target = self._rename_target(key)
        if target is None or not new or new == target.name:
            return
        try:
            target.name = new
        except Exception as e:
            bridge.log(f"Rename: {e}", "WARNING")
            return
        bridge.undo_push("Rename")
        self.refresh(force=True)

    def _rename_target(self, key):
        kind = key[0]
        try:
            if kind == "ID":
                return self._id(key)
            if kind == "COLLECTION":
                return bpy.data.collections.get(key[1])
            ob = bpy.data.objects.get(key[1]) if len(key) > 1 else None
            if ob is None:
                return None
            if kind == "OBJECT":
                return ob
            if kind == "DATA":
                return ob.data
            if kind == "BONE":
                return ob.data.bones.get(key[2])
            if kind == "MAT":
                return ob.material_slots[key[2]].material
            if kind == "MOD":
                return ob.modifiers.get(key[2])
            if kind == "CON":
                return ob.constraints.get(key[2])
            if kind == "VGROUP":
                return ob.vertex_groups.get(key[2])
            if kind == "ACTION":
                return ob.animation_data.action if ob.animation_data is not None else None
        except Exception:
            return None
        return None

    def rename(self):
        it = self.tree.currentItem()
        if it is not None and it.flags() & QtCore.Qt.ItemIsEditable:
            self.tree.editItem(it, 0)

    # ------------------------------------------------------------ keys
    def _actions(self):
        return (("outliner.show_selected", self.show_selected),
                ("outliner.show_hierarchy", self.show_hierarchy),
                ("outliner.show_one_level", lambda: self.one_level(True)),
                ("outliner.hide_one_level", lambda: self.one_level(False)),
                ("outliner.expand_all", self.expand_toggle),
                ("outliner.select_all", lambda: self.select_all("SELECT")),
                ("outliner.deselect_all", lambda: self.select_all("DESELECT")),
                ("outliner.select_invert", lambda: self.select_all("INVERT")),
                ("outliner.rename", self.rename),
                ("outliner.delete", lambda: self.delete(False)),
                ("outliner.hide", self.hide_selected),
                ("outliner.unhide_all", self.unhide_all),
                ("outliner.search", self.focus_search),
                ("outliner.clear_search", self.filter.clear),
                ("outliner.new_collection", self.new_collection),
                ("outliner.move_to_collection", lambda: self.collection_menu(link=False)),
                ("outliner.link_to_collection", lambda: self.collection_menu(link=True)),
                ("outliner.exclude", lambda: self.set_exclude(True)),
                ("outliner.include", lambda: self.set_exclude(False)),
                ("outliner.parent", self.parent_to_active),
                ("outliner.unparent", self.clear_parent))

    def eventFilter(self, obj, ev):
        if obj is self.tree:
            t = ev.type()
            if t in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress) and \
                    self.tree.state() != QtWidgets.QAbstractItemView.EditingState:
                names = keymap.event_names(ev)
                for aid, fn in self._actions():
                    if keymap.hit(aid, ev, names):
                        if t == QtCore.QEvent.KeyPress:
                            fn()
                        ev.accept()
                        return True
        return super().eventFilter(obj, ev)

    def focus_search(self):
        self.filter.setFocus()
        self.filter.selectAll()

    # ------------------------------------------------------------ view operations
    def _selected_keys(self):
        """Row keys of the current selection: bones in Pose mode, objects otherwise; active first."""
        ctx = bpy.context
        active = ctx.view_layer.objects.active
        keys = []
        if ctx.mode == "POSE":
            for o in ctx.view_layer.objects:
                if o.type == "ARMATURE" and o.mode == "POSE" and o.pose is not None:
                    keys += [("BONE", o.name, pb.name) for pb in o.pose.bones if pb.select]
            if active is not None and active.type == "ARMATURE" and active.data.bones.active:
                act = ("BONE", active.name, active.data.bones.active.name)
                if act in keys:
                    keys.remove(act)
                keys.insert(0, act)
        if not keys:
            kind = ("ID", "objects") if self.st["mode"] != "VIEW_LAYER" else ("OBJECT",)
            keys = [kind + (o.name,) for o in ctx.selected_objects]
            if active is not None and kind + (active.name,) in keys:
                keys.remove(kind + (active.name,))
                keys.insert(0, kind + (active.name,))
        return keys

    def show_selected(self):
        """Open the rows down to every selected object / bone and centre the active one
        (Blender: Show Active, Maya: F / Reveal Selected)."""
        keys = self._selected_keys()
        if not keys:
            return
        self._updating = True
        try:
            for key in reversed(keys):          # the active one last, so the scroll ends on it
                self._reveal(key)
        finally:
            self._updating = False
        self.sync_selection()
        first = self._items.get(keys[0])
        if first is not None and _alive(first):
            self.tree.scrollToItem(first, QtWidgets.QAbstractItemView.PositionAtCenter)

    def show_hierarchy(self):
        """Blender: open all object entries (collections and objects with children), close the rest."""
        for key, it in list(self._all):
            if not _alive(it):
                continue
            if key[0] in ("COLLECTION", "IDTYPE") or it.data(0, ROOT):
                it.setExpanded(True)
            elif key[0] == "OBJECT":
                it.setExpanded(any((it.child(i).data(0, KEY) or ("",))[0] == "OBJECT"
                                   for i in range(it.childCount())))
            elif it.isExpanded():
                it.setExpanded(False)
        self.tree.scrollToTop()

    def collapse_to_collections(self):
        for key, it in self._all:
            if _alive(it) and key[0] != "COLLECTION" and it.isExpanded():
                it.setExpanded(False)
        self.tree.scrollToTop()

    def _shown_rows(self):
        out = []

        def walk(it, depth):
            out.append((it, depth))
            if it.isExpanded():
                for i in range(it.childCount()):
                    ch = it.child(i)
                    if not ch.isHidden():
                        walk(ch, depth + 1)
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i), 0)
        return out

    def one_level(self, open_):
        """Numpad +/-: open the shallowest closed level / close the deepest open level."""
        rows = self._shown_rows()
        if open_:
            closed = [(it, d) for it, d in rows if it.childCount() and not it.isExpanded()]
            if closed:
                depth = min(d for _it, d in closed)
                for it, d in closed:
                    if d == depth:
                        it.setExpanded(True)
        else:
            opened = [(it, d) for it, d in rows if it.childCount() and it.isExpanded() and not it.data(0, ROOT)]
            if opened:
                depth = max(d for _it, d in opened)
                for it, d in opened:
                    if d == depth:
                        it.setExpanded(False)

    def expand_toggle(self):
        """Shift+A: expand all collections and objects, or collapse when something is open."""
        if any(_alive(it) and it.isExpanded() and k[0] != "COLLECTION" and not it.data(0, ROOT)
               for k, it in self._all):
            self.collapse_to_collections()
            return
        for k, it in list(self._all):
            if _alive(it) and k[0] in ("COLLECTION", "OBJECT", "IDTYPE") and it.childCount():
                it.setExpanded(True)

    def _expand_all(self, it, on):
        it.setExpanded(on)
        for i in range(it.childCount()):
            self._expand_all(it.child(i), on)

    # ------------------------------------------------------------ edit operations
    def _sel_rows(self, kinds=None):
        out = []
        for it in self.tree.selectedItems():
            k = it.data(0, KEY)
            if k and (kinds is None or k[0] in kinds):
                out.append(k)
        cur = self.tree.currentItem()
        if not out and cur is not None:
            k = cur.data(0, KEY)
            if k and (kinds is None or k[0] in kinds):
                out.append(k)
        return out

    def _sel_objects(self):
        names = [k[1] for k in self._sel_rows(("OBJECT",))]
        names += [k[2] for k in self._sel_rows(("ID",)) if k[1] == "objects"]
        if not names:
            names = [o.name for o in bpy.context.selected_objects]
        return [bpy.data.objects[n] for n in dict.fromkeys(names) if n in bpy.data.objects]

    def _sel_collections(self):
        out = []
        for k in self._sel_rows(("COLLECTION",)):
            c = bpy.data.collections.get(k[1])
            if c is not None:
                out.append(c)
        return out

    @staticmethod
    def _ensure_object_mode():
        if bpy.context.mode != "OBJECT":
            bridge.run_op("object.mode_set", {"mode": "OBJECT"})

    def select_all(self, action):
        ctx = bpy.context

        def new(cur):
            return True if action == "SELECT" else False if action == "DESELECT" else not cur
        if ctx.mode == "POSE":
            ob = ctx.view_layer.objects.active
            if ob is not None and ob.pose is not None:
                for pb in ob.pose.bones:
                    hidden = self._bone_hide_target(pb.bone, pb).hide
                    pb.select = (not hidden) and new(pb.select)
        else:
            for o in ctx.view_layer.objects:
                try:
                    o.select_set(o.visible_get() and not o.hide_select and new(o.select_get()))
                except RuntimeError:
                    pass
        bridge.undo_push("Select All")
        self._redraw_viewport()

    def hide_selected(self):
        root_lc = bpy.context.view_layer.layer_collection
        for k in self._sel_rows():
            if k[0] == "OBJECT":
                ob = bpy.data.objects.get(k[1])
                if ob is not None:
                    try:
                        ob.hide_set(True)
                        ob.select_set(False)
                    except RuntimeError:
                        pass
            elif k[0] == "COLLECTION":
                lc = self._lc(k[1])
                if lc is not None and lc != root_lc:
                    lc.hide_viewport = True
            elif k[0] == "BONE":
                _ob, b, pb = self._pbone(k)
                if b is not None:
                    self._bone_hide_target(b, pb).hide = True
        self._after_toggle("Hide")

    def unhide_all(self):
        ctx = bpy.context
        for o in ctx.view_layer.objects:
            try:
                o.hide_set(False)
            except RuntimeError:
                pass

        def walk(lc):
            lc.hide_viewport = False
            for ch in lc.children:
                walk(ch)
        for ch in ctx.view_layer.layer_collection.children:
            walk(ch)
        if ctx.mode == "POSE":
            ob = ctx.view_layer.objects.active
            if ob is not None and ob.pose is not None:
                for pb in ob.pose.bones:
                    self._bone_hide_target(pb.bone, pb).hide = False
        self._after_toggle("Unhide All")

    def delete(self, hierarchy=False):
        rows = self._sel_rows()
        if self.st["mode"] != "VIEW_LAYER":
            ids = [i for i in (self._id(k) for k in rows if k[0] == "ID") if i is not None]
            if ids:
                bpy.data.batch_remove(ids)
                bridge.undo_push("Delete")
                self.refresh(force=True)
            return
        obs = [o for o in (bpy.data.objects.get(k[1]) for k in rows if k[0] == "OBJECT") if o is not None]
        colls = self._sel_collections()
        if not obs and not colls:
            return
        if obs:
            self._ensure_object_mode()
            if hierarchy:
                obs = list({o.name: o for o in obs + [c for o in obs for c in o.children_recursive]}.values())
            for o in obs:
                try:
                    bpy.data.objects.remove(o, do_unlink=True)
                except ReferenceError:
                    pass
        for c in colls:
            self._delete_collection(c, hierarchy)
        bridge.undo_push("Delete Hierarchy" if hierarchy else "Delete")
        self.refresh(force=True)
        self._redraw_viewport()

    def _coll_parents(self, c):
        scene = bpy.context.scene
        out = [p for p in [scene.collection] + list(scene.collection.children_recursive) if c.name in p.children]
        return out or [scene.collection]

    def _delete_collection(self, c, hierarchy):
        try:
            name = c.name
        except ReferenceError:
            return
        if hierarchy:
            inside = {c.name} | {x.name for x in c.children_recursive}
            for o in list(c.all_objects):
                if all(uc.name in inside for uc in o.users_collection):
                    try:
                        bpy.data.objects.remove(o, do_unlink=True)
                    except ReferenceError:
                        pass
            for ch in list(c.children_recursive):
                try:
                    bpy.data.collections.remove(ch)
                except ReferenceError:
                    pass
        else:
            # Blender: the contents move up to the parent collection
            parent = self._coll_parents(c)[0]
            for o in list(c.objects):
                if o.name not in parent.objects:
                    parent.objects.link(o)
            for ch in list(c.children):
                if ch.name not in parent.children:
                    parent.children.link(ch)
        c = bpy.data.collections.get(name)
        if c is not None:
            bpy.data.collections.remove(c)

    def new_collection(self):
        ctx = bpy.context
        sel = self._sel_collections() if self.st["mode"] == "VIEW_LAYER" else []
        parent = sel[0] if sel else ctx.view_layer.active_layer_collection.collection
        c = bpy.data.collections.new("Collection")
        parent.children.link(c)
        bridge.undo_push("New Collection")
        self.refresh(force=True)
        key = ("COLLECTION", c.name)
        it = self._items.get(key)
        if it is not None:
            self._reveal(key)
            self.tree.setCurrentItem(it)

    def collection_menu(self, link=False, pos=None):
        """M / Shift+M: menu of collections to move (link) the selected objects / collections to."""
        if self.st["mode"] != "VIEW_LAYER":
            return
        if not self._sel_objects() and not self._sel_collections():
            return
        m = QtWidgets.QMenu(self)
        _section(m, "Link to Collection" if link else "Move to Collection")
        scene = bpy.context.scene

        def add(c, depth):
            root = c == scene.collection
            label = scene.name if root else c.name
            a = m.addAction(_ic("scene" if root else "collection", T_FG if root else _TAG_COLOR.get(c.color_tag, T_FG)),
                            "    " * depth + label)
            a.triggered.connect(lambda _c=False, t=c: self.move_to(t, link))
            for ch in c.children:
                add(ch, depth + 1)
        add(scene.collection, 0)
        m.addSeparator()
        m.addAction(_ic("collection_new"), "New Collection", lambda: self._move_to_new(link))
        m.exec(pos or QtGui.QCursor.pos())

    def _move_to_new(self, link):
        c = bpy.data.collections.new("Collection")
        bpy.context.scene.collection.children.link(c)
        self.move_to(c, link)

    def move_to(self, target, link=False, objs=None, colls=None):
        objs = self._sel_objects() if objs is None else objs
        colls = self._sel_collections() if colls is None else colls
        for ob in objs:
            if not link:
                for c in list(ob.users_collection):
                    if c != target:
                        c.objects.unlink(ob)
            if ob.name not in target.objects:
                target.objects.link(ob)
        for c in colls:
            if c == target or target.name in {x.name for x in c.children_recursive}:
                continue                          # into itself: would make a loop
            if not link:
                for p in self._coll_parents(c):
                    if p != target and c.name in p.children:
                        p.children.unlink(c)
            if c.name not in target.children:
                target.children.link(c)
        bridge.undo_push("Link to Collection" if link else "Move to Collection")
        self.refresh(force=True)
        self._redraw_viewport()

    def set_exclude(self, on):
        for c in self._sel_collections():
            lc = self._lc(c.name)
            if lc is not None:
                lc.exclude = on
        bridge.undo_push("Exclude" if on else "Include")
        self.refresh(force=True)
        self._redraw_viewport()

    @staticmethod
    def _parent_keep(ob, parent):
        """Parent / unparent keeping the world transform (Blender: Object, Keep Transform)."""
        mw = ob.matrix_world.copy()
        ob.parent = parent
        if parent is not None:
            ob.parent_type = "OBJECT"           # an old bone / vertex parent would no longer fit
            ob.parent_bone = ""
            ob.matrix_parent_inverse = parent.matrix_world.inverted()
        ob.matrix_world = mw

    def parent_to_active(self, target=None, objs=None):
        ctx = bpy.context
        target = target or ctx.view_layer.objects.active
        objs = [o for o in (objs if objs is not None else self._sel_objects()) if o != target]
        if target is None or not objs:
            return
        done = 0
        for ob in objs:
            if target in ob.children_recursive:
                continue                      # would make a loop
            self._parent_keep(ob, target)
            done += 1
        if done:
            bridge.undo_push("Parent")
            self.refresh(force=True)
            self._redraw_viewport()

    def clear_parent(self, objs=None):
        objs = [o for o in (objs if objs is not None else self._sel_objects()) if o.parent is not None]
        for ob in objs:
            self._parent_keep(ob, None)
        if objs:
            bridge.undo_push("Clear Parent")
            self.refresh(force=True)
            self._redraw_viewport()

    def purge_orphans(self):
        n = sum(1 for attr, *_r in ID_TYPES for i in (getattr(bpy.data, attr, None) or []) if i.users == 0)
        if not n:
            QtWidgets.QMessageBox.information(self, "Purge", "No unused data-blocks.")
            return
        r = QtWidgets.QMessageBox.question(
            self, "Purge Unused Data",
            f"Delete {n} data-block(s) without users (and the ones that become unused)?\n"
            "Data with a fake user is kept.")
        if r != QtWidgets.QMessageBox.Yes:
            return
        try:
            bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
        except TypeError:
            bpy.data.orphans_purge()
        bridge.undo_push("Purge Unused Data")
        self.refresh(force=True)

    # ------------------------------------------------------------ drag and drop
    def _drag_keys(self):
        return [k for k in (it.data(0, KEY) for it in self.tree.selectedItems() if not it.data(0, ROOT))
                if k and k[0] in ("OBJECT", "COLLECTION")]

    def _drop_allowed(self, it):
        if self.st["mode"] != "VIEW_LAYER":
            return False
        if it is None:
            return True
        k = it.data(0, KEY)
        return bool(k) and k[0] in ("OBJECT", "COLLECTION")

    def _drop(self, target_item, where, link):
        if self.st["mode"] != "VIEW_LAYER":
            return
        keys = self._drag_keys()
        objs = [o for o in (bpy.data.objects.get(k[1]) for k in keys if k[0] == "OBJECT") if o is not None]
        colls = [c for c in (bpy.data.collections.get(k[1]) for k in keys if k[0] == "COLLECTION") if c is not None]
        if not objs and not colls:
            return
        tk = target_item.data(0, KEY) if target_item is not None and _alive(target_item) else None
        if tk is None:
            # empty space (Maya): unparent; collections go to the scene collection
            if objs:
                self.clear_parent(objs)
            if colls:
                self.move_to(bpy.context.scene.collection, False, [], colls)
            return
        if tk[0] == "OBJECT":
            target = bpy.data.objects.get(tk[1])
            if target is not None and objs:
                self.parent_to_active(target, objs)
            return
        if tk[0] == "COLLECTION":
            if target_item.data(0, ROOT):
                target = bpy.context.scene.collection
            else:
                target = bpy.data.collections.get(tk[1])
            if target is None:
                return
            if where != "ON":
                for o in objs:                  # dropped between rows: also leave the parent object
                    if o.parent is not None:
                        self._parent_keep(o, None)
            self.move_to(target, link, objs, colls)

    # ------------------------------------------------------------ public API (qt_shell.api.outliner())
    def set_option(self, key, value):
        """Filter / display option, e.g. set_option("sort_alpha", False). Keys: Outliner.DEFAULTS."""
        if key not in DEFAULTS:
            raise KeyError(f"unknown Outliner option {key!r} – one of {', '.join(DEFAULTS)}")
        self._set_opt(key, value)

    def show_column(self, cid, on=True):
        """Show / hide a restriction column: exclude, select, hide, viewport, render, holdout, indirect."""
        if cid not in _COL_INFO:
            raise KeyError(f"unknown column {cid!r} – one of {', '.join(_COL_INFO)}")
        self._toggle_column(cid, bool(on))

    def search(self, text=""):
        """Filter the rows by name (wildcards * and ?); "" clears the search."""
        self.filter.setText(text)

    def isolate(self, key, cid="hide"):
        """Like Ctrl+click in a restriction column, e.g. isolate(("OBJECT", "Cube"))."""
        self._isolate(tuple(key), cid)

    def duplicate_collection(self, c):
        self._duplicate_collection(c)

    def instance_collection(self, c):
        self._instance_collection(c)

    def collection_visibility(self, c, hide, inside=False):
        """Hide / show a collection in this view layer (inside=True: also everything in it)."""
        self._coll_hide(c, hide, inside)

    # ------------------------------------------------------------ python tooltips
    def _row_data(self, key):
        """RNA struct shown by a row (for its Python path), or None."""
        kind = key[0]
        try:
            if kind == "COLLECTION":
                return bpy.data.collections.get(key[1]) or bpy.context.scene.collection
            if kind == "IDTYPE":
                return None
            if kind == "ID":
                return self._id(key)
            ob = bpy.data.objects.get(key[1])
            if ob is None:
                return None
            if kind == "OBJECT":
                return ob
            if kind == "DATA":
                return ob.data
            if kind == "ACTION":
                ad = ob.animation_data
                return ad.action if ad is not None else None
            if kind == "MAT":
                return ob.material_slots[key[2]].material
            if kind == "MOD":
                return ob.modifiers.get(key[2])
            if kind == "CON":
                return ob.constraints.get(key[2])
            if kind == "VGROUP":
                return ob.vertex_groups.get(key[2])
            if kind == "BONE":
                _ob, b, pb = self._pbone(key)
                return pb if pb is not None else b
        except (ReferenceError, IndexError, AttributeError, TypeError):
            pass
        return None

    def _lc_path(self, name):
        """Python path of a collection's LayerCollection in the current view layer."""
        def find(l, path):
            if l.collection.name == name:
                return path
            for ch in l.children:
                r = find(ch, f'{path}.children["{ch.collection.name}"]')
                if r:
                    return r
            return None
        try:
            return find(bpy.context.view_layer.layer_collection, "bpy.context.view_layer.layer_collection") or ""
        except Exception:
            return ""

    def _row_path(self, key):
        kind = key[0]
        if kind == "IDTYPE":
            return f"bpy.data.{key[1]}"
        if kind in ("MODS", "CONS", "VGROUPS"):
            ob = bpy.data.objects.get(key[1])
            attr = {"MODS": "modifiers", "CONS": "constraints", "VGROUPS": "vertex_groups"}[kind]
            return f"{_path(ob)}.{attr}" if ob is not None else ""
        return _path(self._row_data(key))

    def cell_python(self, it, col):
        """Python path of a row (column 0) or the command a click in a restriction column runs."""
        key = it.data(0, KEY)
        if not key or key[0] == "LAZY":
            return None
        if col <= 0 or col - 1 >= len(self._cols):
            return self._row_path(key) or None
        cid = self._cols[col - 1]
        if cid == "users":
            return f"{self._row_path(key)}.users"
        ok, on = self._get(key, cid)
        if not ok:
            return None
        new = not on                              # what a click sets
        kind = key[0]
        if cid == "fake":
            return f"{self._row_path(key)}.use_fake_user = {new}"
        if kind == "COLLECTION":
            c = bpy.data.collections.get(key[1])
            lcp = self._lc_path(key[1])
            cp = _path(c)
            return {"exclude": f"{lcp}.exclude = {not new}", "select": f"{cp}.hide_select = {not new}",
                    "hide": f"{lcp}.hide_viewport = {not new}", "viewport": f"{cp}.hide_viewport = {not new}",
                    "render": f"{cp}.hide_render = {not new}", "holdout": f"{lcp}.holdout = {new}",
                    "indirect": f"{lcp}.indirect_only = {new}"}.get(cid)
        p = self._row_path(key)
        if kind == "OBJECT":
            return {"select": f"{p}.hide_select = {not new}", "hide": f"{p}.hide_set({not new})",
                    "viewport": f"{p}.hide_viewport = {not new}", "render": f"{p}.hide_render = {not new}",
                    "holdout": f"{p}.is_holdout = {new}"}.get(cid)
        if kind == "BONE":
            _ob, b, pb = self._pbone(key)
            if cid == "select":
                return f"{_path(b)}.hide_select = {not new}"
            if cid == "hide":
                return f"{_path(self._bone_hide_target(b, pb))}.hide = {not new}"
        if kind == "MOD":
            return f"{p}.show_{'viewport' if cid == 'viewport' else 'render'} = {new}"
        if kind == "CON":
            return f"{p}.enabled = {new}"
        return None

    def _tag_menu(self, menu, key):
        """Python tooltips for every action of the context menu (also in submenus)."""
        kind = key[0] if key else ""
        p = self._row_path(key) if key else ""
        is_coll = kind == "COLLECTION" and bpy.data.collections.get(key[1]) is not None
        coll = _path(bpy.data.collections.get(key[1])) if is_coll else ""
        lcp = self._lc_path(key[1]) if is_coll else ""
        T = {
            "Show Selected": _api("show_selected()"),
            "Show Object Hierarchy": _api("show_hierarchy()"),
            "Show One Level": _api("one_level(True)"),
            "Hide One Level": _api("one_level(False)"),
            "Expand / Collapse All": _api("expand_toggle()"),
            "New Collection": _api("new_collection()"),
            "Unhide All": _api("unhide_all()"),
            "Delete Hierarchy": _api("delete(hierarchy=True)"),
            "Purge Unused Data": "bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)",
        }
        if p:
            T["Rename"] = f'{p}.name = "New Name"'
        if kind == "ID" and p:
            T["Delete"] = f"bpy.data.{key[1]}.remove({p})"
            T["Fake User"] = f"{p}.use_fake_user = True"
        elif kind == "OBJECT" and p:
            T.update({
                "Select": f"{p}.select_set(True)",
                "Select Hierarchy": f"[o.select_set(True) for o in ({p}, *{p}.children_recursive)]",
                "Deselect": f"{p}.select_set(False)",
                "Duplicate": "bpy.ops.object.duplicate()",
                "Delete": f"bpy.data.objects.remove({p})",
                "Parent to Active": _api("parent_to_active()   # keeps the world transform"),
                "Clear Parent": _api("clear_parent()   # keeps the world transform"),
                "Move to Collection": _api('move_to(bpy.data.collections["Target"])'),
                "Link to Collection": f'bpy.data.collections["Target"].objects.link({p})',
                "Hide": f"{p}.hide_set(True)",
                "Frame in Viewport": "import qt_shell; qt_shell.api.frame_selected()",
            })
        elif kind == "BONE" and p:
            T["Hide"] = f"{p}.hide = True"
        elif is_coll:
            T.update({
                "Delete": _api("delete()   # its objects move to the parent collection"),
                "Duplicate Collection": _api(f"duplicate_collection({coll})"),
                "Select Objects": f"[o.select_set(True) for o in {coll}.all_objects]",
                "Deselect Objects": f"[o.select_set(False) for o in {coll}.all_objects]",
                "Instance to Scene": _api(f"instance_collection({coll})"),
                "Move to Collection": _api('move_to(bpy.data.collections["Target"])'),
                "Isolate": _api(f"isolate({tuple(key)!r})"),
                "Show": f"{lcp}.hide_viewport = False",
                "Hide": f"{lcp}.hide_viewport = True",
                "Show All Inside": _api(f"collection_visibility({coll}, hide=False, inside=True)"),
                "Hide All Inside": _api(f"collection_visibility({coll}, hide=True, inside=True)"),
                "Enable in Viewports": f"{coll}.hide_viewport = False",
                "Disable in Viewports": f"{coll}.hide_viewport = True",
                "Enable in Render": f"{coll}.hide_render = False",
                "Disable in Render": f"{coll}.hide_render = True",
                "Exclude": f"{lcp}.exclude = True",
                "Include": f"{lcp}.exclude = False",
                "Set Holdout": f"{lcp}.holdout = True",
                "Clear Holdout": f"{lcp}.holdout = False",
                "Set Indirect Only": f"{lcp}.indirect_only = True",
                "Clear Indirect Only": f"{lcp}.indirect_only = False",
            })
            for tid, label, _color in COLOR_TAGS:
                T[label] = f"{coll}.color_tag = {tid!r}"

        def walk(m):
            for a in m.actions():
                if a.menu() is not None:
                    walk(a.menu())
                    continue
                label = a.text().split("\t")[0].replace("&", "").rstrip("…").strip()
                py = T.get(label)
                if py:
                    pytips.tag(a, py)
        walk(menu)

    # ------------------------------------------------------------ context menu
    @staticmethod
    def _kl(label, aid):
        """Menu label with the action's current key in the shortcut column."""
        return f"{label}\t{keymap.text(aid)}"

    def _context_menu(self, pos):
        it = self.tree.itemAt(pos)
        m = QtWidgets.QMenu(self)
        key = it.data(0, KEY) if it is not None else None
        kind = key[0] if key else ""
        mode = self.st["mode"]
        K = self._kl
        if it is not None and not it.isSelected():
            self.tree.setCurrentItem(it)
        if mode != "VIEW_LAYER":
            if kind == "ID":
                idb = self._id(key)
                m.addAction(_ic("rename"), K("Rename", "outliner.rename"), self.rename)
                if idb is not None and idb.library is None:
                    a = m.addAction(_ic("fake_on"), "Fake User")
                    a.setCheckable(True)
                    a.setChecked(idb.use_fake_user)
                    a.toggled.connect(lambda on, k=key: (self._set(k, "fake", on), self._after_toggle("Fake User")))
                m.addSeparator()
                m.addAction(_ic("trash"), K("Delete", "outliner.delete"), lambda: self.delete(False))
            if mode == "ORPHAN":
                m.addSeparator()
                m.addAction(_ic("trash"), "Purge Unused Data…", self.purge_orphans)
            m.addSeparator()
            self._view_menu(m, it)
            self._tag_menu(m, key)
            m.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if kind == "OBJECT":
            m.addAction(_ic("select_on"), "Select", lambda: self._select_objects(self._sel_objects(), False))
            m.addAction(_ic("hierarchy"), "Select Hierarchy", lambda: self._select_objects(self._sel_objects(), True))
            m.addAction("Deselect", lambda: self._deselect(self._sel_objects()))
            m.addSeparator()
            m.addAction(_ic("rename"), K("Rename", "outliner.rename"), self.rename)
            m.addAction("Duplicate", lambda: bridge.run_op("object.duplicate"))
            m.addAction(_ic("trash"), K("Delete", "outliner.delete"), lambda: self.delete(False))
            m.addAction("Delete Hierarchy", lambda: self.delete(True))
            m.addSeparator()
            m.addAction(_ic("parent"), K("Parent to Active", "outliner.parent"), self.parent_to_active)
            m.addAction(_ic("unparent"), K("Clear Parent", "outliner.unparent"), self.clear_parent)
            m.addAction(_ic("collection"), K("Move to Collection…", "outliner.move_to_collection"),
                        lambda: self.collection_menu(False))
            m.addAction(K("Link to Collection…", "outliner.link_to_collection"), lambda: self.collection_menu(True))
            m.addAction(_ic("collection_new"), K("New Collection", "outliner.new_collection"), self.new_collection)
            m.addSeparator()
            m.addAction(_ic("eye_off"), K("Hide", "outliner.hide"), self.hide_selected)
            m.addAction(_ic("eye_on"), K("Unhide All", "outliner.unhide_all"), self.unhide_all)
            m.addAction(_ic("zoom"), "Frame in Viewport", self._frame)
        elif kind == "COLLECTION" and not it.data(0, ROOT):
            c = bpy.data.collections.get(key[1])
            if c is not None:
                self._collection_menu_items(m, key, c)
        elif kind == "BONE":
            m.addAction(_ic("rename"), K("Rename", "outliner.rename"), self.rename)
            m.addAction(_ic("eye_off"), K("Hide", "outliner.hide"), self.hide_selected)
            m.addAction(_ic("eye_on"), K("Unhide All", "outliner.unhide_all"), self.unhide_all)
        elif it is not None and it.flags() & QtCore.Qt.ItemIsEditable:
            m.addAction(_ic("rename"), K("Rename", "outliner.rename"), self.rename)
        if it is None or it.data(0, ROOT):
            m.addAction(_ic("collection_new"), K("New Collection", "outliner.new_collection"), self.new_collection)
            m.addAction(_ic("eye_on"), K("Unhide All", "outliner.unhide_all"), self.unhide_all)
        m.addSeparator()
        self._view_menu(m, it)
        self._tag_menu(m, key)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _collection_menu_items(self, m, key, c):
        K = self._kl
        m.addAction(_ic("collection_new"), K("New Collection", "outliner.new_collection"), self.new_collection)
        m.addAction("Duplicate Collection", lambda: self._duplicate_collection(c))
        m.addAction(_ic("rename"), K("Rename", "outliner.rename"), self.rename)
        m.addAction(_ic("trash"), K("Delete", "outliner.delete"), lambda: self.delete(False))
        m.addAction("Delete Hierarchy", lambda: self.delete(True))
        m.addSeparator()
        m.addAction(_ic("select_on"), "Select Objects", lambda: self._select_objects(list(c.all_objects), False))
        m.addAction("Deselect Objects", lambda: self._deselect(list(c.all_objects)))
        m.addAction("Instance to Scene", lambda: self._instance_collection(c))
        m.addAction(_ic("collection"), K("Move to Collection…", "outliner.move_to_collection"),
                    lambda: self.collection_menu(False))
        m.addSeparator()
        vis = m.addMenu(_ic("eye_on"), "Visibility")
        vis.addAction(_ic("isolate"), "Isolate", lambda: self._isolate(key, "hide"))
        vis.addSeparator()
        vis.addAction(_ic("eye_on"), "Show", lambda: self._coll_hide(c, False, False))
        vis.addAction("Show All Inside", lambda: self._coll_hide(c, False, True))
        vis.addAction(_ic("eye_off"), "Hide", lambda: self._coll_hide(c, True, False))
        vis.addAction("Hide All Inside", lambda: self._coll_hide(c, True, True))
        vis.addSeparator()
        vis.addAction(_ic("monitor_on"), "Enable in Viewports", lambda: self._coll_flag(c, "hide_viewport", False))
        vis.addAction(_ic("monitor_off"), "Disable in Viewports", lambda: self._coll_flag(c, "hide_viewport", True))
        vis.addSeparator()
        vis.addAction(_ic("render_on"), "Enable in Render", lambda: self._coll_flag(c, "hide_render", False))
        vis.addAction(_ic("render_off"), "Disable in Render", lambda: self._coll_flag(c, "hide_render", True))
        vl = m.addMenu(_ic("view_layer"), "View Layer")
        vl.addAction(_ic("chk_off"), K("Exclude", "outliner.exclude"), lambda: self.set_exclude(True))
        vl.addAction(_ic("chk_on"), K("Include", "outliner.include"), lambda: self.set_exclude(False))
        vl.addSeparator()
        vl.addAction(_ic("holdout_on"), "Set Holdout", lambda: self._lc_flag(c, "holdout", True))
        vl.addAction(_ic("holdout_off"), "Clear Holdout", lambda: self._lc_flag(c, "holdout", False))
        vl.addAction(_ic("indirect_on"), "Set Indirect Only", lambda: self._lc_flag(c, "indirect_only", True))
        vl.addAction(_ic("indirect_off"), "Clear Indirect Only", lambda: self._lc_flag(c, "indirect_only", False))
        tag = m.addMenu(_ic("collection", _TAG_COLOR.get(c.color_tag, T_FG)), "Color Tag")
        for tid, label, color in COLOR_TAGS:
            a = tag.addAction(_ic("collection", color), label)
            a.setCheckable(True)
            a.setChecked(c.color_tag == tid)
            a.triggered.connect(lambda _c=False, t=tid: self._color_tag(t))

    def _view_menu(self, m, it):
        K = self._kl
        view = m.addMenu("View")
        view.addAction(_ic("zoom"), K("Show Selected", "outliner.show_selected"), self.show_selected)
        view.addAction(_ic("hierarchy"), K("Show Object Hierarchy", "outliner.show_hierarchy"), self.show_hierarchy)
        view.addAction(K("Show One Level", "outliner.show_one_level"), lambda: self.one_level(True))
        view.addAction(K("Hide One Level", "outliner.hide_one_level"), lambda: self.one_level(False))
        view.addAction(K("Expand / Collapse All", "outliner.expand_all"), self.expand_toggle)
        if it is not None and it.childCount():
            view.addSeparator()
            view.addAction("Expand All Children", lambda: self._expand_all(it, True))
            view.addAction("Collapse All Children", lambda: self._expand_all(it, False))

    def _frame(self):
        vp = self.hub.viewport
        if vp is not None:
            vp.frame_selected()

    def _select_objects(self, objs, hierarchy):
        self._ensure_object_mode()
        if hierarchy:
            objs = list({o.name: o for o in objs + [c for o in objs for c in o.children_recursive]}.values())
        vl = bpy.context.view_layer
        for o in objs:
            try:
                if o.visible_get() and not o.hide_select:
                    o.select_set(True)
            except RuntimeError:
                pass
        if objs and vl.objects.active not in objs and objs[0].name in vl.objects:
            vl.objects.active = objs[0]
        bridge.undo_push("Select")
        self._redraw_viewport()

    def _deselect(self, objs):
        for o in objs:
            try:
                o.select_set(False)
            except RuntimeError:
                pass
        bridge.undo_push("Deselect")
        self._redraw_viewport()

    def _instance_collection(self, c):
        e = bpy.data.objects.new(c.name, None)
        e.instance_type = "COLLECTION"
        e.instance_collection = c
        bpy.context.scene.collection.objects.link(e)
        bridge.undo_push("Instance to Scene")
        self.refresh(force=True)

    def _duplicate_collection(self, c):
        mapping = {}

        def dup(src, parent):
            n = bpy.data.collections.new(src.name)
            n.color_tag = src.color_tag
            parent.children.link(n)
            for ob in src.objects:
                nob = mapping.get(ob.name)
                if nob is None:
                    nob = ob.copy()
                    if ob.data is not None:
                        nob.data = ob.data.copy()
                    mapping[ob.name] = nob
                n.objects.link(nob)
            for ch in src.children:
                dup(ch, n)
        dup(c, self._coll_parents(c)[0])
        for old, new in mapping.items():
            p = bpy.data.objects[old].parent
            if p is not None and p.name in mapping:
                new.parent = mapping[p.name]
        bridge.undo_push("Duplicate Collection")
        self.refresh(force=True)

    def _coll_hide(self, c, hide, inside):
        lc = self._lc(c.name)
        if lc is None:
            return

        def objs_hide(l):
            for o in l.collection.objects:
                try:
                    o.hide_set(hide)
                except RuntimeError:
                    pass

        def walk(l):
            l.hide_viewport = hide
            objs_hide(l)
            for ch in l.children:
                walk(ch)
        if inside:
            objs_hide(lc)
            for ch in lc.children:
                walk(ch)
        else:
            lc.hide_viewport = hide
        self._after_toggle("Hide" if hide else "Show")

    def _coll_flag(self, c, attr, value):
        setattr(c, attr, value)
        self._after_toggle("Collection Visibility")

    def _lc_flag(self, c, attr, value):
        for cc in self._sel_collections() or [c]:
            lc = self._lc(cc.name)
            if lc is not None:
                setattr(lc, attr, value)
        self._after_toggle("View Layer")

    def _color_tag(self, tag):
        for c in self._sel_collections():
            c.color_tag = tag
        bridge.undo_push("Color Tag")
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

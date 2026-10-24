"""Qt Shell main window: menus, docks, viewport, render, last operation, search."""
import math
import os
import time
import tempfile

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import app as shell_app
from . import icons, keymap
from . import pytips
from . import annotate, api, bridge, fake_ui, rna_widgets as rw, theme
from .bridge import run_op, tr
from .console import Console
from .node_editor import NodeEditor
from .uv_editor import UVEditor
from .outliner import Outliner
from .properties import PropertiesEditor
from .sidebar import Sidebar
from .text_editor import TextEditor
from . import scripts
from .qt_ui import LazyMenu, PopoverMenu
from .timeline import Timeline
from .graph_editor import GraphEditor
from .viewport import ViewportArea
from .render_view import RenderView

MODE_MENUS = {
    "add": {"OBJECT": "VIEW3D_MT_add", "EDIT_MESH": "VIEW3D_MT_mesh_add",
            "EDIT_CURVE": "VIEW3D_MT_curve_add", "EDIT_ARMATURE": "VIEW3D_MT_armature_add"},
    "object": {"OBJECT": "VIEW3D_MT_object", "EDIT_MESH": "VIEW3D_MT_edit_mesh",
               "EDIT_CURVE": "VIEW3D_MT_edit_curve", "POSE": "VIEW3D_MT_pose",
               "SCULPT": "VIEW3D_MT_sculpt", "EDIT_ARMATURE": "VIEW3D_MT_edit_armature"},
    "select": {"OBJECT": "VIEW3D_MT_select_object", "EDIT_MESH": "VIEW3D_MT_select_edit_mesh",
               "EDIT_CURVE": "VIEW3D_MT_select_edit_curve", "POSE": "VIEW3D_MT_select_pose",
               "EDIT_ARMATURE": "VIEW3D_MT_select_edit_armature"},
}
MODE_ICONS = {"OBJECT": "object_mode", "EDIT": "edit_mode", "SCULPT": "sculpt_mode", "VERTEX_PAINT": "vertex_paint",
              "WEIGHT_PAINT": "weight_paint", "TEXTURE_PAINT": "texture_paint", "POSE": "pose_mode"}
MODES = [("OBJECT", "Object Mode"), ("EDIT", "Edit Mode"), ("SCULPT", "Sculpt Mode"),
         ("VERTEX_PAINT", "Vertex Paint"), ("WEIGHT_PAINT", "Weight Paint"),
         ("TEXTURE_PAINT", "Texture Paint"), ("POSE", "Pose Mode")]
try:
    from . import bl_info as _bl_info
    _QT_SHELL_VERSION = ".".join(str(v) for v in _bl_info["version"])
except Exception:
    _QT_SHELL_VERSION = "?"

DISCARDING_OPS = {"wm.open_mainfile", "wm.read_homefile", "wm.revert_mainfile",
                  "wm.recover_last_session", "wm.recover_auto_save", "wm.read_factory_settings"}


def _mode_menu(kind):
    def resolve():
        mode = bpy.context.mode
        table = MODE_MENUS[kind]
        return table.get(mode, table["OBJECT"])
    return resolve


class _HeaderScroll(QtWidgets.QScrollArea):
    """The 3D view header: when it is wider than the view, the mouse wheel scrolls it (like Blender)."""

    def wheelEvent(self, ev):
        sb = self.horizontalScrollBar()
        if sb.maximum() <= 0:
            return super().wheelEvent(ev)
        d = ev.angleDelta()
        step = d.y() if abs(d.y()) >= abs(d.x()) else d.x()
        sb.setValue(sb.value() - int(step / 2))
        ev.accept()


# ---------------------------------------------------------------- last operation (redo)
class LastOperatorPanel(QtWidgets.QWidget):
    """Redo panel. Blender does not register operators called from Python in wm.operators,
    so we keep the parameters ourselves (dict) and build the widgets from the operator's RNA definitions."""

    SKIP = {"filepath", "directory", "files", "filter_glob", "filename", "check_existing"}

    def __init__(self, hub):
        super().__init__()
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(4, 4, 4, 4)
        self.title = QtWidgets.QLabel("No operation")
        self.title.setStyleSheet("font-weight:bold;")
        self.lay.addWidget(self.title)
        self.lay.addStretch(1)
        self.form = None
        self.idname = None
        self.values = {}
        self._redoing = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._redo)
        hub.op_done.connect(self.on_op)
        hub.file_loaded.connect(self.clear)

    def clear(self):
        if self.form is not None:
            self.form.deleteLater()
            self.form = None
        self.title.setText("No operation")
        self.idname = None

    def on_op(self, idname, props, result):
        if self._redoing or idname.startswith(("ed.", "wm.", "screen.", "qtshell.")):
            return
        if "FINISHED" not in (result or set()):
            return
        try:
            op = bridge.get_op(idname)
            rna = op.get_rna_type()
            opts = set(getattr(op, "bl_options", None) or getattr(rna, "bl_options", None) or {"UNDO"})
        except Exception:
            return
        if "UNDO" not in opts:
            return
        defs = [p for p in rna.properties
                if p.identifier != "rna_type" and p.identifier not in self.SKIP
                and not getattr(p, "is_hidden", False) and p.type not in ("POINTER", "COLLECTION")]
        self.clear()
        if not defs:
            return
        self.idname = idname
        self.values = dict(props)
        self.title.setText(tr(rna.name))
        self.form = QtWidgets.QWidget()
        fl = QtWidgets.QVBoxLayout(self.form)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(3)
        for p in defs:
            w = self._widget(p)
            if w is None:
                continue
            if p.type == "BOOLEAN" and not getattr(p, "array_length", 0):
                fl.addWidget(w)
            else:
                fl.addWidget(rw.labeled_row(tr(p.name), w))
        self.lay.insertWidget(1, self.form)

    def _default(self, p):
        if p.identifier in self.values:
            return self.values[p.identifier]
        if p.type == "ENUM":
            return set(p.default_flag) if p.is_enum_flag else p.default
        if getattr(p, "array_length", 0) and p.type in ("INT", "FLOAT", "BOOLEAN"):
            return tuple(p.default_array)
        return p.default

    def _set(self, ident, value):
        self.values[ident] = value
        self._timer.start()

    def _widget(self, p):
        ident = p.identifier
        val = self._default(p)
        if p.type == "BOOLEAN" and not getattr(p, "array_length", 0):
            w = QtWidgets.QCheckBox(tr(p.name))
            w.setChecked(bool(val))
            w.toggled.connect(lambda v, i=ident: self._set(i, bool(v)))
            return w
        if p.type in ("INT", "FLOAT"):
            n = getattr(p, "array_length", 0)
            vals = list(val) if n else [val]
            box = QtWidgets.QWidget()
            bl = QtWidgets.QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(1)
            angle = p.subtype == "ANGLE"
            spins = []
            for k, v in enumerate(vals):
                s = rw.DragSpin(p.type == "INT")
                s.setRange(max(p.hard_min, -1e9) if not angle else -1e6, min(p.hard_max, 1e9) if not angle else 1e6)
                if p.type == "FLOAT":
                    s.setDecimals(3)
                    s.drag_step = 1.0 if angle else max((p.step or 3) / 100.0, 0.001)
                if angle:
                    s.setSuffix("°")
                    v = math.degrees(v)
                elif p.subtype in ("DISTANCE",):
                    s.setSuffix(" m")
                if n:
                    s.setPrefix(rw.AXES[k] + ": " if k < 4 else "")
                s.setValue(v)
                spins.append(s)
                bl.addWidget(s)

            def changed(_v=None, spins=spins, ident=ident, n=n, angle=angle, is_int=p.type == "INT"):
                out = []
                for s in spins:
                    x = s.value()
                    x = math.radians(x) if angle else x
                    out.append(int(round(x)) if is_int else x)
                self._set(ident, tuple(out) if n else out[0])
            for s in spins:
                s.valueChanged.connect(changed)
            return box
        if p.type == "ENUM" and not p.is_enum_flag:
            w = rw.NoWheelCombo()
            for e in p.enum_items:
                w.addItem(tr(e.name), e.identifier)
            w.setCurrentIndex(max(0, w.findData(val)))
            w.activated.connect(lambda i, w=w, ident=ident: self._set(ident, w.itemData(i)))
            return w
        if p.type == "STRING":
            w = QtWidgets.QLineEdit(str(val or ""))
            w.editingFinished.connect(lambda w=w, ident=ident: self._set(ident, w.text()))
            return w
        return None

    def _redo(self):
        if not self.idname:
            return
        # undo and the re-run must happen in different ticks of Blender's loop,
        # otherwise the depsgraph works with data that undo has just freed (crash).
        self._redoing = True
        idname, values = self.idname, dict(self.values)
        run_op("ed.undo")

        def again():
            try:
                run_op(idname, values)
            finally:
                self._redoing = False
        bridge.later(again, 0.05)


# ---------------------------------------------------------------- F3 search
class OperatorSearch(QtWidgets.QDialog):
    _cache = None

    def __init__(self, parent):
        super().__init__(parent, QtCore.Qt.Popup)
        self.resize(520, 420)
        lay = QtWidgets.QVBoxLayout(self)
        self.edit = QtWidgets.QLineEdit()
        self.edit.setPlaceholderText("Search operator…")
        self.edit.textChanged.connect(self._filter)
        self.edit.returnPressed.connect(self._accept)
        lay.addWidget(self.edit)
        self.list = QtWidgets.QListWidget()
        self.list.itemActivated.connect(lambda _i: self._accept())
        lay.addWidget(self.list)
        self.edit.installEventFilter(self)
        self._filter("")

    @classmethod
    def items(cls):
        if cls._cache is None:
            out = []
            for mod_name in dir(bpy.ops):
                if mod_name.startswith("_"):
                    continue
                mod = getattr(bpy.ops, mod_name)
                for op_name in dir(mod):
                    if op_name.startswith("_"):
                        continue
                    idname = f"{mod_name}.{op_name}"
                    try:
                        name = tr(getattr(mod, op_name).get_rna_type().name)
                    except Exception:
                        continue
                    out.append((name or idname, idname))
            out.sort(key=lambda t: t[0].lower())
            cls._cache = out
        return cls._cache

    def _filter(self, text):
        words = text.lower().split()
        self.list.clear()
        n = 0
        for name, idname in self.items():
            hay = f"{name} {idname}".lower()
            if all(w in hay for w in words):
                it = QtWidgets.QListWidgetItem(f"{name}    —  {idname}")
                it.setData(QtCore.Qt.UserRole, idname)
                self.list.addItem(it)
                n += 1
                if n > 300:
                    break
        self.list.setCurrentRow(0)

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.KeyPress and ev.key() in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down):
            row = self.list.currentRow() + (1 if ev.key() == QtCore.Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
            return True
        return False

    def _accept(self):
        it = self.list.currentItem()
        self.close()
        if it is not None:
            run_op(it.data(QtCore.Qt.UserRole))


class MenuSearch(OperatorSearch):
    """Search inside one Blender menu and its submenus (wm.search_single_menu), e.g. Add Modifier → Search…"""

    def __init__(self, parent, menu_id):
        self._menu = LazyMenu(menu_id)          # kept alive: the found actions belong to it
        self._entries = []
        self._collect(self._menu, "", set())
        super().__init__(parent)
        self.edit.setPlaceholderText("Search…")

    def _collect(self, menu, path, seen):
        if id(menu) in seen or len(seen) > 200:
            return
        seen.add(id(menu))
        menu.aboutToShow.emit()                 # LazyMenu / PopoverMenu fill themselves on show
        for act in menu.actions():
            if act.isSeparator():
                continue
            text = act.text().replace("&", "").rstrip("…").strip()
            sub = act.menu()
            if sub is not None:
                self._collect(sub, f"{path}{text} ▸ ", seen)
            elif text and act.isEnabled() and not text.startswith("Search"):
                self._entries.append((path + text, act))

    def items(self):
        return [(label, i) for i, (label, _a) in enumerate(self._entries)]

    def _filter(self, text):
        words = text.lower().split()
        self.list.clear()
        for label, act in self._entries:
            if all(w in label.lower() for w in words):
                it = QtWidgets.QListWidgetItem(act.icon(), label)
                it.setData(QtCore.Qt.UserRole, act)
                self.list.addItem(it)
        self.list.setCurrentRow(0)

    def _accept(self):
        it = self.list.currentItem()
        self.close()
        if it is not None:
            it.data(QtCore.Qt.UserRole).trigger()


# ---------------------------------------------------------------- interface size
class InterfaceSizeDialog(QtWidgets.QDialog):
    """Window → Interface Size…: scale of the whole Qt UI and of the text.

    Moving a slider previews the change right away (text, buttons, fields, spacing);
    OK saves it to the add-on preferences and rebuilds the window so every fixed size follows.
    """
    PRESETS = (0.8, 1.0, 1.25, 1.5, 2.0)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Interface Size")
        self._orig = (theme.ui_scale, theme.font_scale)
        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.ui = self._slider(50, 300, theme.ui_scale)
        self.font = self._slider(50, 250, theme.font_scale)
        form.addRow("Interface scale", self.ui[0])
        form.addRow("Text size", self.font[0])
        lay.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Presets:"))
        for v in self.PRESETS:
            b = QtWidgets.QPushButton(f"{int(v * 100)} %")
            b.clicked.connect(lambda _=False, v=v: (self.ui[2].setValue(int(v * 100)),
                                                    self.font[2].setValue(100)))
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        hint = QtWidgets.QLabel("Interface scale changes buttons, fields, icons, spacing and text. "
                                "Text size changes only the text. OK rebuilds the window.")
        hint.setWordWrap(True)
        hint.setProperty("dim", True)
        lay.addWidget(hint)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
                                        | QtWidgets.QDialogButtonBox.Reset)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QtWidgets.QDialogButtonBox.Reset).clicked.connect(
            lambda: (self.ui[2].setValue(100), self.font[2].setValue(100)))
        lay.addWidget(bb)
        self.setMinimumWidth(theme.px(440))

    def _slider(self, lo, hi, value):
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        sl = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setSingleStep(5)
        sl.setPageStep(25)
        sp = QtWidgets.QSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(5)
        sp.setSuffix(" %")
        sp.setMinimumWidth(theme.px(70))
        sl.valueChanged.connect(sp.setValue)
        sp.valueChanged.connect(sl.setValue)
        sp.valueChanged.connect(lambda _v: self._preview())
        sp.setValue(int(round(value * 100)))
        h.addWidget(sl, 1)
        h.addWidget(sp)
        return w, sl, sp

    def values(self):
        return self.ui[2].value() / 100.0, self.font[2].value() / 100.0

    def _preview(self):
        if hasattr(self, "font"):
            shell_app.preview_interface_size(*self.values())
            QtCore.QTimer.singleShot(0, self.adjustSize)

    def reject(self):
        shell_app.preview_interface_size(*self._orig)
        super().reject()

    def accept(self):
        ui, font = self.values()
        super().accept()
        p = shell_app.prefs()
        if p is None:
            shell_app.preview_interface_size(ui, font)
            return
        if abs(p.ui_scale - ui) < 1e-4 and abs(p.font_scale - font) < 1e-4:
            shell_app.apply_interface_size()   # values unchanged in prefs – still rebuild after preview
        else:
            p.ui_scale = ui          # the update callback rebuilds the window
            p.font_scale = font
        try:
            if not bpy.context.preferences.use_preferences_save:
                bpy.ops.wm.save_userpref()
        except Exception:
            pass


# ---------------------------------------------------------------- main window
def status_history():
    """Messages shown in the status bar: deque of (time 'HH:MM:SS', text, timestamp), newest last.
    Kept for the whole Blender session (survives rebuilding the window)."""
    from collections import deque
    st = api.state_store("status")
    h = st.get("history")
    if not isinstance(h, deque):
        h = st["history"] = deque(maxlen=200)
    return h


class StatusHistoryDialog(QtWidgets.QDialog):
    """List of the status bar messages, newest first."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Status History")
        self.resize(theme.px(560), theme.px(360))
        lay = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget(self)
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.setWordWrap(True)
        lay.addWidget(self.list, 1)
        row = QtWidgets.QHBoxLayout()
        lay.addLayout(row)
        info = QtWidgets.QLabel("Newest first · the last 200 messages of this Blender session", self)
        info.setProperty("dim", True)
        row.addWidget(info, 1)
        copy = QtWidgets.QPushButton("Copy", self)
        copy.setToolTip("Copy the selected messages (all when nothing is selected)")
        copy.clicked.connect(self.copy)
        row.addWidget(copy)
        clear = QtWidgets.QPushButton("Clear", self)
        clear.clicked.connect(self.clear)
        row.addWidget(clear)
        close = QtWidgets.QPushButton("Close", self)
        close.clicked.connect(self.close)
        row.addWidget(close)

    def refresh(self):
        self.list.clear()
        for stamp, msg, _t in reversed(status_history()):
            self.list.addItem(f"{stamp}   {msg}")

    def copy(self):
        items = self.list.selectedItems() or [self.list.item(i) for i in range(self.list.count())]
        QtWidgets.QApplication.clipboard().setText("\n".join(it.text() for it in items))

    def clear(self):
        status_history().clear()
        self.refresh()


def _render_result_image():
    return bpy.data.images.get("Render Result")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        hub.main_window = self
        self.setWindowTitle("Qt Shell")
        self.resize(1500, 920)
        self.setDockOptions(QtWidgets.QMainWindow.AnimatedDocks | QtWidgets.QMainWindow.AllowTabbedDocks)

        # viewport + header
        center = QtWidgets.QWidget(self)
        # one or several 3D views (View ▸ Viewport Layout); self.viewport is the active view
        self.viewports = ViewportArea(hub, shell_app.prefs(), center)
        cl = QtWidgets.QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._viewport_header())
        cl.addWidget(self.viewports, 1)
        self.setCentralWidget(center)

        # docks
        self.outliner = Outliner(hub)
        self.properties = PropertiesEditor(hub)
        self.timeline = Timeline(hub)
        self.console = Console(hub)
        self.last_op = LastOperatorPanel(hub)
        self.node_editor = NodeEditor(hub)
        self.uv_editor = UVEditor(hub)
        self.sidebar = Sidebar(hub)
        self.text_editor = TextEditor(hub)
        self.graph_editor = GraphEditor(hub, self)
        self.uv_editor.canvas.status.connect(lambda s: self.statusBar().showMessage(s, 4000))
        self.docks = {}
        self._dock("outliner", "Outliner", self.outliner, QtCore.Qt.RightDockWidgetArea)
        self._dock("properties", "Properties", self.properties, QtCore.Qt.RightDockWidgetArea)
        self._dock("timeline", "Timeline", self.timeline, QtCore.Qt.BottomDockWidgetArea)
        self._dock("console", "Console", self.console, QtCore.Qt.BottomDockWidgetArea)
        self._dock("last_op", "Adjust Last Operation", self.last_op, QtCore.Qt.LeftDockWidgetArea)
        self._dock("node_editor", "Node editor", self.node_editor, QtCore.Qt.BottomDockWidgetArea)
        self._dock("uv_editor", "UV editor", self.uv_editor, QtCore.Qt.BottomDockWidgetArea)
        self._dock("text_editor", "Text editor", self.text_editor, QtCore.Qt.BottomDockWidgetArea)
        self._dock("graph_editor", "Graph editor", self.graph_editor, QtCore.Qt.BottomDockWidgetArea)
        # 3D viewport sidebar (N panel): next to the viewport, hidden by default like in Blender
        self._dock("sidebar", "Sidebar", self.sidebar, QtCore.Qt.RightDockWidgetArea)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.docks["sidebar"], QtCore.Qt.Horizontal)
        self.docks["sidebar"].hide()
        self.tabifyDockWidget(self.docks["timeline"], self.docks["console"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["node_editor"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["uv_editor"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["text_editor"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["graph_editor"])
        self.docks["timeline"].raise_()
        self.resizeDocks([self.docks["outliner"], self.docks["properties"]], [260, 560], QtCore.Qt.Vertical)
        self.resizeDocks([self.docks["properties"]], [400], QtCore.Qt.Horizontal)
        self.resizeDocks([self.docks["last_op"]], [230], QtCore.Qt.Horizontal)

        # Shelf (like Maya): script buttons; a dock at the top – can float as its own window
        from .shelf import ShelfBar
        self.shelf = ShelfBar(hub)
        self._dock("shelf", "Shelf", self.shelf, QtCore.Qt.TopDockWidgetArea)

        self.render_window = RenderView(self)      # Blender's render window (Render Result)
        self._build_menus()
        self._build_shortcuts()
        self.status_right = QtWidgets.QLabel(self.statusBar())
        self.statusBar().addPermanentWidget(self.status_right)
        # shown while rendering: Cancel Render (also Esc, Render → Cancel Render)
        self.render_cancel_btn = QtWidgets.QToolButton(self.statusBar())
        icons.set_icon(self.render_cancel_btn, "render_cancel")
        self.render_cancel_btn.setText("Cancel Render")
        self.render_cancel_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.render_cancel_btn.setAutoRaise(True)
        keymap.tip(self.render_cancel_btn, "Stop the running render ({window.render_cancel})")
        self.render_cancel_btn.clicked.connect(self.cancel_render)
        self.render_cancel_btn.hide()
        self.statusBar().addPermanentWidget(self.render_cancel_btn)
        # status history: every message is kept (newest 200) and also written to the Console
        self._last_log_line = None
        hist_btn = QtWidgets.QToolButton(self.statusBar())
        hist_btn.setText("🕘")
        hist_btn.setAutoRaise(True)
        hist_btn.setToolTip("Status history (or click the status bar)")
        hist_btn.clicked.connect(self.show_status_history)
        self.statusBar().addPermanentWidget(hist_btn)
        self.statusBar().messageChanged.connect(self._on_status_message)
        self.statusBar().installEventFilter(self)
        self._status_dialog = None

        # hooks in bridge
        bridge.file_dialog_hook = self.file_dialog
        bridge.special_op_hook = self.special_op
        bridge.after_op_hook = lambda i, p, r: hub.op_done.emit(i, p, r)
        hub.log.connect(self._on_log)
        hub.title_changed.connect(self._update_title)
        hub.selection_changed.connect(self._update_status)
        hub.data_changed.connect(self._update_status)
        hub.data_changed.connect(self._sync_shading)
        hub.selection_changed.connect(lambda: self._sync_selmode())
        hub.selection_changed.connect(lambda: self._sync_mode_combo())
        self.viewports.selection_edited.connect(self._sync_selmode)
        hub.mode_changed.connect(self._on_mode)
        hub.render_done.connect(self._on_render_done)
        hub.render_frame.connect(self._on_render_frame)
        hub.file_loaded.connect(self._on_file_loaded)
        self.viewports.status.connect(lambda s: self.statusBar().showMessage(s, 4000))
        self._rendering = False
        self._render_win = None             # hidden Blender window the running render was started from
        self._render_cancelled = False
        # while rendering: end of the render (a render shorter than one hub tick was missed before) and the
        # live preview of an image render
        self._render_poll = QtCore.QTimer(self)
        self._render_poll.setInterval(250)
        self._render_poll.timeout.connect(self._poll_render)

        pytips.install()        # Python tooltips (Edit → Qt Preferences… → Interface)
        # window icon (the Hex Turtle logo, docs/logo/)
        try:
            icon = QtGui.QIcon(os.path.join(os.path.dirname(__file__), "qt_shell_icon.png"))
            if not icon.isNull():
                self.setWindowIcon(icon)
                QtWidgets.QApplication.instance().setWindowIcon(icon)
        except Exception:
            pass
        self._settings = QtCore.QSettings("QtShell", "QtShell")
        st = None
        try:
            geo = self._settings.value("geometry")
            st = self._settings.value("state")
            if geo is not None:
                self.restoreGeometry(geo)
            old = float(self._settings.value("size_factor", 1.0) or 1.0)
        except Exception:
            old = 1.0
        mode = self._settings.value("viewport_layout", "single")
        if mode in ViewportArea.LAYOUTS and mode != "single":
            try:
                self.viewports.set_layout(mode)
            except Exception:
                bridge.log("Viewport layout: " + __import__("traceback").format_exc(), "ERROR")
        # The saved dock layout is restored only AFTER the window has been shown. Restoring it before the
        # first show() crashed Qt on Windows again and again (access violation in show(), 2026-10-18…20 –
        # also without floating docks), while the same restoreState() at run time (workspace switch)
        # never crashed. The window therefore appears with the default layout for a moment.
        if st is not None:
            QtCore.QTimer.singleShot(0, lambda s=st: self._restore_saved_layout(s))
        # windows that were floating when Qt Shell closed float again a moment after the start
        # (shutdown() docks them before saving the layout and remembers them here)
        try:
            import json
            self._float_later = json.loads(self._settings.value("floating_docks", "{}") or "{}")
        except Exception:
            self._float_later = {}
        if self._float_later:
            QtCore.QTimer.singleShot(1500, self._float_saved_docks)
        # dock sizes are stored in pixels → follow a change of the interface size
        self._size_factor = theme.ui_scale * theme.font_scale ** 0.5
        ratio = self._size_factor / old if old > 0 else 1.0
        if abs(ratio - 1.0) > 0.01:
            QtCore.QTimer.singleShot(0, lambda r=ratio: self._scale_docks(r))
        self._update_title()
        self._update_status()
        self._on_mode(bpy.context.mode)
        self.viewport.frame_all()
        # workspaces (like Blender): tabs on the right of the menu bar, each with its own layout
        try:
            from .workspaces import Workspaces, WorkspaceTabs
            self.workspaces = Workspaces(self)
            self.workspace_tabs = WorkspaceTabs(self.workspaces, self.menuBar())
            self.menuBar().setCornerWidget(self.workspace_tabs, QtCore.Qt.TopRightCorner)
            if st is None:
                # no saved window layout (first start / safe start): use the current workspace's one
                QtCore.QTimer.singleShot(0, lambda: self.workspaces.current() and
                                         self.workspaces._apply(self.workspaces.current()))
        except Exception:
            self.workspaces = None
            bridge.log("Workspaces: " + __import__("traceback").format_exc(), "ERROR")
        # docks, menu items, overlays and event handlers registered by add-ons (qt_shell.api)
        try:
            api.apply_to_window(self)
        except Exception:
            bridge.log("Qt Shell API: " + __import__("traceback").format_exc(), "ERROR")
        # auto-load scripts (files: once per session, texts of the .blend: once per file)
        QtCore.QTimer.singleShot(0, self._scripts_startup)

    def _float_saved_docks(self):
        for key, geo in getattr(self, "_float_later", {}).items():
            d = self.docks.get(key)
            if d is None or d.isHidden():
                continue
            try:
                d.setFloating(True)
                if isinstance(geo, list) and len(geo) == 4:
                    d.setGeometry(*[int(v) for v in geo])
            except RuntimeError:
                pass
        self._float_later = {}

    def _scripts_startup(self):
        try:
            scripts.startup()
        except Exception:
            bridge.log("Scripts: " + __import__("traceback").format_exc(), "ERROR")

    # ------------------------------------------------------------ building the UI
    def _dock(self, key, title, widget, area):
        d = QtWidgets.QDockWidget(title, self)
        d.setObjectName(f"dock_{key}")
        d.setWidget(widget)
        self.addDockWidget(area, d)
        self.docks[key] = d
        return d

    def _viewport_header(self):
        bar = QtWidgets.QWidget()
        bar.setStyleSheet("QWidget { background: #303030; }\n" + theme.hover_qss() + theme.field_hover_qss())
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(3)
        self.mode_combo = rw.NoWheelCombo()
        for ident, label in MODES:
            self.mode_combo.addItem(icons.icon(MODE_ICONS.get(ident, "")), tr(label), ident)
        self.mode_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.mode_combo.setMinimumContentsLength(11)
        self.mode_combo.activated.connect(self._set_mode)
        lay.addWidget(self.mode_combo)
        # the menus Blender shows for the current mode (View, Select, Add, Object / Mesh, Vertex, Edge, …)
        self.menu_box = QtWidgets.QWidget(bar)
        mb = QtWidgets.QHBoxLayout(self.menu_box)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.setSpacing(0)
        lay.addWidget(self.menu_box)
        self._menus_mode = None
        # options of the active tool (Annotate: colour / thickness / placement, Add: base and height, Measure)
        self.tool_header = annotate.ToolHeader(self, bar)
        lay.addWidget(self.tool_header)
        self.selmode_buttons = []
        for i, (txt, tip) in enumerate((("•", "Vertices (1)"), ("╱", "Edges (2)"), ("■", "Faces (3)"))):
            b = QtWidgets.QToolButton()
            b.setText(txt)
            b.setToolTip(tip)
            icons.set_icon(b, ("select_vert", "select_edge", "select_face")[i])
            pytips.tag(b, f"bpy.ops.mesh.select_mode(type={('VERT', 'EDGE', 'FACE')[i]!r})")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self._set_selmode(i))
            lay.addWidget(b)
            self.selmode_buttons.append(b)
        lay.addStretch(1)
        self._hdr_syncs = []
        self._build_tool_settings(bar, lay)          # orientation, pivot, snapping, proportional editing
        lay.addStretch(1)
        self._build_view_toggles(bar, lay)           # object types, gizmos, overlays, X-ray
        lay.addSpacing(theme.px(6))
        self.shading_group = QtWidgets.QButtonGroup(bar)
        self.shading_buttons = {}
        for kind, txt, tip in (("WIREFRAME", "◇", "Wireframe"), ("SOLID", "●", "Solid"),
                               ("MATERIAL", "◐", "Material Preview"), ("RENDERED", "☀", "Rendered")):
            b = QtWidgets.QToolButton()
            b.setText(txt)
            b.setToolTip(tip)
            icons.set_icon(b, {"WIREFRAME": "shading_wire", "SOLID": "shading_solid", "MATERIAL": "shading_material",
                               "RENDERED": "shading_rendered"}[kind])
            pytips.tag(b, f"bpy.context.space_data.shading.type = {kind!r}")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=kind: self.viewport.set_shading(k))
            self.shading_group.addButton(b)
            self.shading_buttons[kind] = b
            lay.addWidget(b)
        sb = QtWidgets.QToolButton()
        sb.setText("▾")
        sb.setToolTip("Shading settings")
        sb.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        sb.setMenu(PopoverMenu("VIEW3D_PT_shading", sb))
        pytips.tag(sb, 'bpy.ops.wm.call_panel(name="VIEW3D_PT_shading")')
        lay.addWidget(sb)
        lb = QtWidgets.QToolButton(bar)
        lb.setText("▦ Layout ▾")
        icons.set_icon(lb, "layout", "Layout ▾")
        from . import keymap
        keymap.tip(lb, "Split the 3D view: one, two or four views ({window.quad} = Four Views)")
        lb.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        lb.setMenu(self._layout_menu(lb))
        pytips.tag(lb, 'import qt_shell\nqt_shell.api.set_viewport_layout("quad")   # "single", "side", "stacked", "quad"')
        lay.addWidget(lb)
        QtCore.QTimer.singleShot(0, self._sync_shading)
        QtCore.QTimer.singleShot(0, self._rebuild_editor_menus)
        QtCore.QTimer.singleShot(0, self._sync_header)
        # like Blender's header: scrolls instead of making the window wider
        area = _HeaderScroll()
        area.setToolTip("")
        area.setFrameShape(QtWidgets.QFrame.NoFrame)
        area.setWidgetResizable(True)
        area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        area.setWidget(bar)
        area.setFixedHeight(bar.sizeHint().height())
        area.setStyleSheet("QScrollArea { background: #303030; border: none; }")
        return area

    # ------------------------------------------------------------ 3D view header (like Blender 5.2)
    # glyph at the start of a header button's text → icon (the rest of the text stays beside it)
    _HDR_ICONS = {"⤧": "orientation", "⊙": "pivot", "🧲": "snap", "◎": "proportional", "👁": "visibility",
                  "✥": "gizmo", "◫": "overlays", "▣": "xray"}

    def _hdr_button(self, parent, text, tip, py=None, checkable=False):
        b = QtWidgets.QToolButton(parent)
        b.setText(text)
        for g, name in self._HDR_ICONS.items():
            if text.startswith(g):
                icons.set_icon(b, name, text[len(g):].strip() or None)
                break
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.setCheckable(checkable)
        pytips.tag(b, py)
        return b

    def _hdr_popover(self, parent, lay, text, panel, tip):
        b = self._hdr_button(parent, text, tip, f'bpy.ops.wm.call_panel(name="{panel}")')
        b.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        b.setMenu(PopoverMenu(panel, b))
        b.menu().aboutToHide.connect(self._sync_header)
        lay.addWidget(b)
        return b

    def _hdr_toggle(self, parent, lay, text, tip, get, put, py):
        """Checkable button bound to a Blender setting (get() / put(on))."""
        b = self._hdr_button(parent, text, tip, py, checkable=True)

        def clicked(on):
            try:
                put(bool(on))
            except Exception as ex:
                bridge.log(f"{tip.splitlines()[0]}: {ex}", "ERROR")
            self._after_header_change()

        def sync():
            try:
                b.setChecked(bool(get()))
                b.setEnabled(True)
            except Exception:
                b.setEnabled(False)
        b.clicked.connect(clicked)
        self._hdr_syncs.append(sync)
        lay.addWidget(b)
        return b

    def _after_header_change(self):
        try:
            self.viewport.redraw_scene()
        except Exception:
            pass
        self._sync_header()

    def _space3d(self):
        sp, _r = self.viewport.space()
        return sp

    def _build_tool_settings(self, bar, lay):
        ts = lambda: bpy.context.scene.tool_settings
        # Transform orientation
        self.orient_btn = self._hdr_popover(bar, lay, "⤧ Global ▾", "VIEW3D_PT_transform_orientations",
                                            "Transform Orientation")
        pytips.tag(self.orient_btn, "bpy.context.scene.transform_orientation_slots[0].type = 'GLOBAL'")
        self._hdr_syncs.append(lambda: self.orient_btn.setText(
            ("" if not self.orient_btn.icon().isNull() else "⤧ ")
            + tr(bpy.context.scene.transform_orientation_slots[0].type.title().replace("_", " ")) + " ▾"))
        # Pivot point
        self.pivot_btn = self._hdr_button(bar, "⊙ ▾", "Transform Pivot Point",
                                          "bpy.context.scene.tool_settings.transform_pivot_point = 'MEDIAN_POINT'")
        self.pivot_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        pm = QtWidgets.QMenu(self.pivot_btn)
        pm.aboutToShow.connect(lambda m=pm: self._fill_enum_menu(m, ts(), "transform_pivot_point"))
        self.pivot_btn.setMenu(pm)
        lay.addWidget(self.pivot_btn)
        lay.addSpacing(theme.px(4))
        # Snapping
        self._hdr_toggle(bar, lay, "🧲", "Snap (Shift+Tab)", lambda: ts().use_snap,
                         lambda on: setattr(ts(), "use_snap", on),
                         "bpy.context.scene.tool_settings.use_snap = True")
        self._hdr_popover(bar, lay, "▾", "VIEW3D_PT_snapping", "Snapping")
        lay.addSpacing(theme.px(4))
        # Proportional editing (objects in Object Mode, elements in Edit Mode – like Blender)
        def prop_attr():
            return "use_proportional_edit_objects" if bpy.context.mode == "OBJECT" else "use_proportional_edit"
        self._hdr_toggle(bar, lay, "◎", "Proportional Editing (O)", lambda: getattr(ts(), prop_attr()),
                         lambda on: setattr(ts(), prop_attr(), on),
                         "bpy.context.scene.tool_settings.use_proportional_edit_objects = True   "
                         "# use_proportional_edit in Edit Mode")
        self._hdr_popover(bar, lay, "▾", "VIEW3D_PT_proportional_edit", "Proportional Editing Falloff")

    def _build_view_toggles(self, bar, lay):
        sp = self._space3d
        self._hdr_popover(bar, lay, "👁 ▾", "VIEW3D_PT_object_type_visibility",
                          "Selectability & Visibility of object types")
        lay.addSpacing(theme.px(4))
        self._hdr_toggle(bar, lay, "✥", "Show Gizmo", lambda: sp().show_gizmo,
                         lambda on: setattr(sp(), "show_gizmo", on),
                         "bpy.context.space_data.show_gizmo = True")
        self._hdr_popover(bar, lay, "▾", "VIEW3D_PT_gizmo_display", "Gizmos")
        lay.addSpacing(theme.px(4))
        self._hdr_toggle(bar, lay, "◫", "Show Overlays (Shift+Alt+Z)", lambda: sp().overlay.show_overlays,
                         lambda on: setattr(sp().overlay, "show_overlays", on),
                         "bpy.context.space_data.overlay.show_overlays = True")
        self._hdr_popover(bar, lay, "Overlays ▾", "VIEW3D_PT_overlay", "Overlays")
        lay.addSpacing(theme.px(4))

        def xray_attr():
            return "show_xray_wireframe" if sp().shading.type == "WIREFRAME" else "show_xray"
        self._hdr_toggle(bar, lay, "▣", "Toggle X-Ray (Alt+Z)", lambda: getattr(sp().shading, xray_attr()),
                         lambda on: setattr(sp().shading, xray_attr(), on),
                         "bpy.ops.view3d.toggle_xray()   # bpy.context.space_data.shading.show_xray = True")

    def _fill_enum_menu(self, menu, data, prop):
        menu.clear()
        grp = QtGui.QActionGroup(menu)
        cur = getattr(data, prop)
        for ident, name, desc in rw.enum_items(data, prop):
            a = menu.addAction(name)
            a.setCheckable(True)
            a.setChecked(ident == cur)
            a.setToolTip(desc)
            pytips.tag(a, f"{pytips.prop_text(data, prop)} = {ident!r}")
            grp.addAction(a)
            a.triggered.connect(lambda _c=False, i=ident: (setattr(data, prop, i), self._after_header_change()))

    def _sync_header(self):
        for fn in getattr(self, "_hdr_syncs", []):
            try:
                fn()
            except Exception:
                pass

    def _rebuild_editor_menus(self):
        """Fills the header with the menus Blender's VIEW3D_MT_editor_menus draws for the current mode."""
        mode = bpy.context.mode
        if mode == self._menus_mode:
            return
        self._menus_mode = mode
        lay = self.menu_box.layout()
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        menus = []
        try:
            with bridge.blender_context():
                node, _label = fake_ui.record_menu("VIEW3D_MT_editor_menus")

            def walk(n):
                if n is None:
                    return
                if n.kind == "menu" and n.args.get("menu"):
                    menus.append((n.args["menu"], n.args.get("text")))
                for ch in getattr(n, "children", []):
                    walk(ch)
            walk(node)
        except Exception:
            bridge.log("3D view header menus:\n" + __import__("traceback").format_exc(), "WARNING")
        if not menus:
            menus = [("VIEW3D_MT_view", None), (_mode_menu("select")(), None), (_mode_menu("add")(), None),
                     (_mode_menu("object")(), None)]
        for mid, text in menus:
            cls = fake_ui.find_menu_class(mid)
            label = text if text else tr(getattr(cls, "bl_label", mid)) if cls else mid
            b = QtWidgets.QToolButton(self.menu_box)
            b.setText(label)
            b.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            b.setAutoRaise(True)
            # View keeps Qt Shell's own menu: Blender's view3d.* operators would move the hidden Blender view
            b.setMenu(self._view_menu(b) if mid == "VIEW3D_MT_view" else LazyMenu(mid, b))
            pytips.tag(b, f'bpy.ops.wm.call_menu(name="{mid}")')
            lay.addWidget(b)

    @property
    def viewport(self):
        """The active 3D view."""
        return self.viewports.active

    def _layout_menu(self, parent):
        m = QtWidgets.QMenu("Viewport Layout", parent)
        group = QtGui.QActionGroup(m)
        acts = {}
        for key, label in ViewportArea.LAYOUTS.items():
            a = m.addAction(label + ("   Ctrl+Alt+Q" if key == "quad" else ""),
                            lambda k=key: self.viewports.set_layout(k))
            a.setCheckable(True)
            pytips.tag(a, f"import qt_shell; qt_shell.api.set_viewport_layout({key!r})")
            group.addAction(a)
            acts[key] = a
        m.aboutToShow.connect(lambda: acts[self.viewports.mode].setChecked(True))
        return m

    def _view_menu(self, parent):
        m = QtWidgets.QMenu(parent)
        vp = lambda: self.viewport        # the active view at the time the item is used
        from . import keymap
        keymap.tip(m.addAction("", lambda: vp().frame_selected()), "Frame Selected\t{view3d.frame_selected}",
                   "setText")
        keymap.tip(m.addAction("", lambda: vp().frame_all()), "Frame All\t{view3d.frame_all}", "setText")
        m.addSeparator()
        for key, label in (("FRONT", "Front"), ("BACK", "Back"), ("RIGHT", "Right"), ("LEFT", "Left"),
                           ("TOP", "Top"), ("BOTTOM", "Bottom"), ("CAMERA", "Camera")):
            keymap.tip(m.addAction("", lambda k=key: vp().set_view(k)),
                       f"{label}\t{{view3d.view_{key.lower()}}}", "setText")
        keymap.tip(m.addAction("", lambda: vp().toggle_ortho()),
                   "Perspective / Orthographic\t{view3d.view_persp}", "setText")
        m.addSeparator()
        m.addMenu(self._layout_menu(m))
        m.addSeparator()
        a = m.addAction("Selection boxes in Qt")
        a.setCheckable(True)
        a.setChecked(False)

        def boxes(on):
            for v in self.viewports.views:
                v.show_boxes = on
            self.viewports.update_all()
        a.toggled.connect(boxes)
        m.addAction("Camera to View", self._camera_to_view)
        return m

    def _build_menus(self):
        mb = self.menuBar()
        mb.clear()

        def blender_menu(title, menu_id=None, resolver=None):
            m = LazyMenu(menu_id, mb, title=tr(title), resolver=resolver)
            m.setProperty("qtshell_key", title)        # untranslated name for qt_shell.api
            m.setProperty("qtshell_generated", True)   # filled on open → api.extend_menu()
            mb.addMenu(m)
            return m

        blender_menu("File", "TOPBAR_MT_file")
        blender_menu("Edit", "TOPBAR_MT_edit")
        blender_menu("Add", resolver=_mode_menu("add"))
        blender_menu("Object", resolver=_mode_menu("object"))
        blender_menu("Select", resolver=_mode_menu("select"))
        self.mesh_menus = [blender_menu(t, mid) for t, mid in (
            ("Vertex", "VIEW3D_MT_edit_mesh_vertices"), ("Edge", "VIEW3D_MT_edit_mesh_edges"),
            ("Face", "VIEW3D_MT_edit_mesh_faces"), ("UV", "VIEW3D_MT_uv_map"))]
        view = mb.addMenu(tr("View"))
        view.setProperty("qtshell_key", "View")
        for a in self._view_menu(view).actions():
            view.addAction(a)
        render_menu = blender_menu("Render", "TOPBAR_MT_render")
        render_menu.aboutToShow.connect(lambda m=render_menu: self._extend_render_menu(m))   # after it is filled

        win = mb.addMenu(tr("Window"))
        win.setProperty("qtshell_key", "Window")
        for key, d in self.docks.items():
            act = d.toggleViewAction()
            if key == "sidebar":
                from . import keymap
                keymap.tip(act, "Sidebar\t{view3d.sidebar}", "setText")
            win.addAction(act)
        self.window_menu = win
        self.window_menu_docks_end = win.addSeparator()
        self.blender_visible_act = win.addAction("Show Blender Window")
        self.blender_visible_act.setCheckable(True)
        self.blender_visible_act.toggled.connect(lambda on: shell_app.set_blender_visible(on))
        win.addAction("Return to the Blender UI (close Qt Shell)",
                      lambda: QtCore.QTimer.singleShot(0, shell_app.stop))
        win.addAction("Reset Window Layout", self._reset_layout)
        win.addAction("Interface Size…", self._interface_size)
        blender_menu("Help", "TOPBAR_MT_help")

    def _build_shortcuts(self):
        """Window shortcuts – their keys come from the keymap (Edit → Keyboard Shortcuts…)."""
        from . import keymap

        def sc(aid, fn):
            a = QtGui.QAction(self)
            a.setShortcutContext(QtCore.Qt.WindowShortcut)
            a.triggered.connect(fn)
            keymap.bind_action(a, aid)
            self.addAction(a)
        sc("window.new", lambda: run_op("wm.read_homefile", {"app_template": ""}))
        sc("window.open", lambda: run_op("wm.open_mainfile"))
        sc("window.open_recent", lambda: LazyMenu("TOPBAR_MT_file_open_recent", self).exec(QtGui.QCursor.pos()))
        sc("window.save", lambda: run_op("wm.save_mainfile"))
        sc("window.save_as", lambda: run_op("wm.save_as_mainfile"))
        sc("window.undo", lambda: run_op("ed.undo"))
        sc("window.redo", lambda: run_op("ed.redo"))
        sc("window.search", self.search)
        sc("window.render", lambda: self.render_image(False))
        sc("window.render_anim", lambda: self.render_image(True))
        # Esc cancels a running render; enabled only while rendering, so Esc keeps its other uses
        self.render_cancel_act = QtGui.QAction(self)
        self.render_cancel_act.setShortcutContext(QtCore.Qt.WindowShortcut)
        self.render_cancel_act.triggered.connect(self.cancel_render)
        keymap.bind_action(self.render_cancel_act, "window.render_cancel")
        self.render_cancel_act.setEnabled(False)
        self.addAction(self.render_cancel_act)
        sc("window.show_render", self.show_render)
        sc("window.view_anim", self.view_animation)
        sc("window.quit", self.close)
        sc("window.play", lambda: self.timeline.toggle_play())
        sc("window.play_reverse", lambda: self.timeline.toggle_play(reverse=True))
        sc("window.frame_prev", lambda: self.timeline.step(-1))
        sc("window.frame_next", lambda: self.timeline.step(1))
        sc("window.maximize", self._toggle_maximize_viewport)
        sc("window.quad", self.viewports.toggle_quad)

    # ------------------------------------------------------------ operator handling
    def special_op(self, idname, props):
        vp = self.viewport
        if idname in ("transform.translate", "transform.rotate", "transform.resize"):
            vp.start_modal({"transform.translate": "G", "transform.rotate": "R", "transform.resize": "S"}[idname])
            return True
        if idname in ("object.duplicate_move", "object.duplicate_move_linked"):
            res = run_op("object.duplicate", {"linked": idname.endswith("linked")})
            if "FINISHED" in res:
                vp.start_modal("G")
            return True
        # "<operator>_move" macros (extrude, duplicate, …): run the operator, then an interactive G
        if idname.endswith("_move") and bridge.op_exists(idname[:-5]):
            mod, name = idname[:-5].split(".", 1)
            base_props = props.get(f"{mod.upper()}_OT_{name}", None)
            res = run_op(idname[:-5], dict(base_props) if isinstance(base_props, dict) else {})
            if "FINISHED" in res:
                vp.start_modal("G")
            return True
        if idname == "render.render":
            self.render_image(bool(props.get("animation")))
            return True
        if idname == "render.view_show":
            self.show_render()
            return True
        if idname == "render.play_rendered_anim":
            self.view_animation()       # Qt player with a timeline instead of Blender's separate window
            return True
        if idname == "wm.quit_blender":
            self.close()
            return True
        if idname == "wm.search_single_menu" and props.get("menu_idname"):
            dlg = MenuSearch(self, props["menu_idname"])
            dlg.move(QtGui.QCursor.pos() - QtCore.QPoint(20, 10))
            dlg.show()
            dlg.edit.setFocus()
            return True
        if idname in ("wm.search_menu", "wm.search_operator", "wm.search_single_menu"):
            self.search()
            return True
        if idname == "wm.call_menu" and props.get("name"):
            LazyMenu(props["name"], self).exec(QtGui.QCursor.pos())
            return True
        if idname == "wm.call_panel" and props.get("name"):
            PopoverMenu(props["name"], self).exec(QtGui.QCursor.pos())
            return True
        if idname in ("wm.append", "wm.link"):
            self.append_dialog(link=idname == "wm.link")
            return True
        if idname == "view3d.view_selected":
            vp.frame_selected()
            return True
        if idname == "view3d.view_all":
            vp.frame_all()
            return True
        if idname in DISCARDING_OPS and bpy.data.is_dirty:
            if not self._confirm_discard():
                return True
        return False

    def _confirm_discard(self):
        r = QtWidgets.QMessageBox.question(
            self, "Unsaved Changes", "The file has unsaved changes. Save?",
            QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel)
        if r == QtWidgets.QMessageBox.Cancel:
            return False
        if r == QtWidgets.QMessageBox.Save:
            res = run_op("wm.save_mainfile")
            return "FINISHED" in res
        return True

    def file_dialog(self, idname, rna_props, props):
        start_dir = os.path.dirname(bpy.data.filepath) or os.path.expanduser("~")
        title = bridge.op_label(idname)
        globs = ""
        if "filter_glob" in rna_props:
            globs = rna_props["filter_glob"].default or ""
        if "filter_blender" in rna_props and not globs:
            globs = "*.blend"
        patterns = " ".join(g for g in globs.replace(",", ";").split(";") if g)
        filt = f"{title} ({patterns});;All files (*)" if patterns else "All files (*)"
        save = any(s in idname for s in ("export", "save", "write")) or idname.endswith("_as")
        multi = "files" in rna_props and not save
        if "directory" in rna_props and "filepath" not in rna_props and "files" not in rna_props:
            d = QtWidgets.QFileDialog.getExistingDirectory(self, title, start_dir)
            if not d:
                return False
            props["directory"] = d
            return True
        if save:
            stem = bpy.path.display_name_from_filepath(bpy.data.filepath) or "untitled"
            ext = ""
            if patterns:
                first = patterns.split()[0]
                if first.startswith("*."):
                    ext = first[1:]
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, title, os.path.join(start_dir, stem + ext), filt)
            if not path:
                return False
            if ext and not os.path.splitext(path)[1]:
                path += ext
            props["filepath"] = path
            return True
        if multi:
            paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, title, start_dir, filt)
            if not paths:
                return False
            props["filepath"] = paths[0]
            props["directory"] = os.path.dirname(paths[0])
            props["files"] = [{"name": os.path.basename(p)} for p in paths]
            return True
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, title, start_dir, filt)
        if not path:
            return False
        if "filepath" in rna_props:
            props["filepath"] = path
        if "directory" in rna_props:
            props["directory"] = os.path.dirname(path)
        if "filename" in rna_props:
            props["filename"] = os.path.basename(path)
        return True

    def append_dialog(self, link=False):
        start = os.path.dirname(bpy.data.filepath) or os.path.expanduser("~")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Link" if link else "Append", start, "Blender (*.blend)")
        if not path:
            return
        try:
            with bpy.data.libraries.load(path) as (data_from, _data_to):
                cats = {a: list(getattr(data_from, a)) for a in dir(data_from)
                        if not a.startswith("_") and isinstance(getattr(data_from, a), list)
                        and getattr(data_from, a)}
        except Exception as ex:
            QtWidgets.QMessageBox.warning(self, "Error", str(ex))
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(os.path.basename(path))
        dlg.resize(420, 480)
        lay = QtWidgets.QVBoxLayout(dlg)
        combo = QtWidgets.QComboBox()
        for a in sorted(cats):
            combo.addItem(a, a)
        lst = QtWidgets.QListWidget()
        lst.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        combo.currentIndexChanged.connect(lambda _i: (lst.clear(), lst.addItems(cats[combo.currentData()])))
        lay.addWidget(combo)
        lay.addWidget(lst)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if "objects" in cats:
            combo.setCurrentIndex(combo.findData("objects"))
        if combo.count():
            lst.addItems(cats[combo.currentData()])
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        attr = combo.currentData()
        names = [i.text() for i in lst.selectedItems()]
        if not names:
            return
        with bpy.data.libraries.load(path, link=link) as (_df, data_to):
            setattr(data_to, attr, names)
        ctx = bpy.context
        target = ctx.view_layer.active_layer_collection.collection
        for item in getattr(data_to, attr):
            if item is None:
                continue
            if attr == "objects":
                target.objects.link(item)
            elif attr == "collections":
                ctx.scene.collection.children.link(item)
        bridge.undo_push("Append")

    # ------------------------------------------------------------ render
    def render_image(self, animation=False):
        if self._rendering:
            return
        view = bpy.context.preferences.view
        old = view.render_display_type
        try:
            view.render_display_type = "NONE"
            # The render runs in a hidden helper window: Blender's render operator waits for Esc in the
            # window it was started from and stops the render job when that window closes – closing the
            # helper is the only way to cancel a render from Python (Esc can't be sent to Blender).
            win = self._render_helper_window()
            ctx = self._window_context(win) if win is not None else None
            if ctx is not None:
                with bpy.context.temp_override(**ctx):
                    res = bpy.ops.render.render("INVOKE_DEFAULT", animation=animation)
                sp = ctx["area"].spaces.active
                if getattr(sp, "image", 1) is None and _render_result_image() is not None:
                    sp.image = _render_result_image()    # created by the render operator on the first render
            else:
                with bridge.blender_context():
                    res = bpy.ops.render.render("INVOKE_DEFAULT", animation=animation)
            if "RUNNING_MODAL" in res:
                self._render_win = win if ctx is not None else None
                self._set_rendering(True, animation)
                if not animation:
                    self.render_window.render_started()     # like Blender: the render window opens
                    self.render_window.present()
                return
            self._close_render_helper(win)
        except Exception as ex:
            bridge.log(f"Asynchronous render failed ({ex}), rendering in blocking mode.", "WARNING")
            self._close_render_helper(getattr(self, "_render_win", None))
        finally:
            view.render_display_type = old
        # fallback: blocking render
        if not animation:
            self.render_window.render_started()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            with bridge.blender_context():
                bpy.ops.render.render(animation=animation, write_still=False)
        except Exception as ex:
            bridge.log(str(ex), "ERROR")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._render_anim = animation
        self._rendering = True
        self._on_render_done()

    # --- render helper window (for cancelling)
    def _render_helper_window(self):
        """A new (hidden) Blender window to start the render from; None if it can't be made."""
        wm = bpy.context.window_manager
        from . import native
        try:
            before = {w.as_pointer() for w in wm.windows}
            native_before = set(native.ghost_windows())
            with bridge.blender_context():
                bpy.ops.wm.window_new()
            new = [w for w in wm.windows if w.as_pointer() not in before]
        except Exception as ex:
            bridge.log(f"Render: no helper window ({ex}) – the render can't be cancelled.", "WARNING")
            return None
        if not new:
            return None
        win = new[0]
        active = self.isActiveWindow()
        act = getattr(self, "blender_visible_act", None)
        if act is None or not act.isChecked():
            # hidden but not minimized: Blender keeps drawing it, so its Image Editor (below) follows the
            # render – that is what the live preview reads (Blender skips minimized windows)
            native.hide_windows([h for h in native.ghost_windows() if h not in native_before])
        if active:
            self.activateWindow()                      # the new Blender window took the focus
        try:
            areas = list(win.screen.areas)
            area = max(areas, key=lambda a: a.width * a.height)
            area.type = "IMAGE_EDITOR"
            sp = area.spaces.active
            img = _render_result_image()
            if img is not None:
                sp.image = img
            for attr in ("show_region_header", "show_region_tool_header", "show_region_toolbar", "show_region_ui"):
                if hasattr(sp, attr):
                    setattr(sp, attr, False)        # the editor is only the picture (live preview capture)
            if hasattr(sp, "overlay"):
                sp.overlay.show_overlays = False
        except Exception as ex:
            bridge.log(f"Render: helper window has no Image Editor ({ex})", "WARNING")
        return win

    def _hide_blender_windows(self):
        act = getattr(self, "blender_visible_act", None)
        if act is None or not act.isChecked():          # Window → Show Blender Window keeps them visible
            shell_app.set_blender_visible(False)       # also refreshes the list of Blender's native windows

    @staticmethod
    def _window_context(win):
        try:
            areas = list(win.screen.areas)
        except Exception:
            return None
        if not areas:
            return None
        area = next((a for a in areas if a.type == "IMAGE_EDITOR"), None) or \
            max(areas, key=lambda a: a.width * a.height)
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        ctx = dict(window=win, screen=win.screen, area=area)
        if region is not None:
            ctx["region"] = region
        return ctx

    def _close_render_helper(self, win):
        self._render_win = None
        if win is None:
            return False
        try:
            if win.as_pointer() not in {w.as_pointer() for w in bpy.context.window_manager.windows}:
                return False
            with bpy.context.temp_override(window=win, screen=win.screen):
                bpy.ops.wm.window_close()
        except Exception as ex:
            bridge.log(f"Render: closing the helper window failed ({ex})", "WARNING")
            return False
        # Closing a Blender window leaves no GPU context active: pause offscreen drawing until Blender has
        # made the main window drawable again (WM_PAINT → GHOST WindowUpdate), otherwise draw_view3d crashes.
        bridge.hold_gpu()
        self._hide_blender_windows()            # also refreshes the list of Blender's native windows
        bridge.restore_gpu_context()
        from . import native
        native.repaint_blender_windows()
        return True

    def _set_rendering(self, on, animation=False):
        self._rendering = on
        self._render_anim = animation
        if on:
            self._render_t0 = time.monotonic()
            self._live_t = 0.0
            self._render_poll.start()
        else:
            self._render_poll.stop()
        cancellable = on and getattr(self, "_render_win", None) is not None
        self.render_cancel_btn.setVisible(on)
        self.render_cancel_btn.setEnabled(cancellable)
        self.render_cancel_act.setEnabled(cancellable)
        if on:
            self.statusBar().showMessage("Rendering… (" + keymap.text("window.render_cancel") + " to cancel)"
                                         if cancellable else "Rendering…")
        rv = getattr(self, "render_window", None)
        if rv is not None and hasattr(rv, "set_rendering"):
            rv.set_rendering(on, cancellable)

    def is_rendering(self):
        return bool(self._rendering)

    def _poll_render(self):
        if not self._rendering:
            self._render_poll.stop()
            return
        if not bridge.is_rendering():
            self._on_render_done()
            return
        if getattr(self, "_render_anim", False):
            return
        now = time.monotonic()
        rv = self.render_window
        if now - self._live_t >= 1.0 and rv.is_shown():
            self._live_t = now
            self._live_preview()
            self._live_t = time.monotonic()          # the next one a second after this one finished

    def _live_preview(self):
        """Image render in progress: the picture so far, about once a second (like Blender's render window).

        Python can't read the Render Result while rendering (Image.pixels / save_render / image.save_as all
        refuse), so the hidden helper window shows it in an Image Editor (hidden, not minimized → Blender
        draws it) and its area is captured with screen.screenshot_area, then cropped to the picture."""
        win = getattr(self, "_render_win", None)
        if win is None:
            return False
        ctx = self._window_context(win)
        if ctx is None or ctx["area"].type != "IMAGE_EDITOR" or "region" not in ctx:
            return False
        area, region = ctx["area"], ctx["region"]
        sp = area.spaces.active
        path = os.path.join(tempfile.gettempdir(), "qtshell_render_live.png")
        import contextlib
        import io
        try:
            if sp.image is None and _render_result_image() is not None:
                sp.image = _render_result_image()
            r = bpy.context.scene.render
            iw, ih = r.resolution_x * r.resolution_percentage / 100.0, r.resolution_y * r.resolution_percentage / 100.0
            # centred with a margin: the editor draws its render info text over the top of its region
            margin = 90
            ratio = min((region.width - 2 * margin) / max(1.0, iw), (region.height - 2 * margin) / max(1.0, ih))
            with contextlib.redirect_stdout(io.StringIO()):
                with bpy.context.temp_override(**ctx):
                    bpy.ops.image.view_all(fit_view=True)
                    if ratio > 0:
                        bpy.ops.image.view_zoom_ratio(ratio=ratio)
                with bpy.context.temp_override(window=win, screen=win.screen):
                    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)      # draw the helper now
                if os.path.exists(path):
                    os.remove(path)
                with bpy.context.temp_override(**ctx):
                    bpy.ops.screen.screenshot_area(filepath=path, check_existing=False)
            zx, zy = tuple(sp.zoom)
            rx, ry, rw, rh = region.x - area.x, region.y - area.y, region.width, region.height
            ah = area.height
        except Exception as ex:
            bridge.log(f"Render: live preview failed ({ex})", "WARNING")
            return False
        from .anim_player import load_image
        shot = load_image(path)
        if shot is None or shot.isNull():
            return False
        # the screenshot is the whole area (pixels, origin top-left); the picture is centred in the region
        sx = shot.width() / max(1, area.width)
        sy = shot.height() / max(1, ah)
        dw, dh = iw * zx * sx, ih * zy * sy
        cx = (rx + rw / 2.0) * sx
        cy = (ah - (ry + rh / 2.0)) * sy
        rect = QtCore.QRect(int(round(cx - dw / 2)) + 1, int(round(cy - dh / 2)) + 1,
                            int(round(dw)) - 2, int(round(dh)) - 2)        # without the editor's image frame
        rect = rect.intersected(shot.rect())
        if rect.width() < 2 or rect.height() < 2:
            return False
        return self.render_window.show_live(shot.copy(rect))

    def cancel_render(self):
        """Render → Cancel Render, Esc, the Cancel Render button: stops the running render (image or animation)."""
        if not self._rendering:
            return False
        win = getattr(self, "_render_win", None)
        if win is None or not self._close_render_helper(win):
            self.statusBar().showMessage("This render can't be cancelled from Qt Shell.", 4000)
            return False
        self._render_cancelled = True
        self.statusBar().showMessage("Cancelling render…")
        if not bridge.is_rendering():
            shell_app.hub().render_done.emit()         # the job is gone already
        return True

    def _on_render_frame(self, frame):
        """While an animation renders: the Timeline playhead follows the frame being rendered."""
        if not (self._rendering and getattr(self, "_render_anim", False)):
            return
        sc = bpy.context.scene
        try:
            self.timeline.sync()
        except Exception:
            pass
        n = sc.frame_end - sc.frame_start + 1
        self.statusBar().showMessage(f"Rendering frame {frame} ({frame - sc.frame_start + 1} / {n})… "
                                     f"{keymap.text('window.render_cancel')} to cancel")

    def _extend_render_menu(self, menu):
        """Render menu: Cancel Render under Render Animation (enabled while rendering)."""
        acts = menu.actions()
        after = next((a for a in acts if a.text().replace("&", "").startswith("Render Animation")), None)
        idx = acts.index(after) + 1 if after is not None else 0
        before = acts[idx] if idx < len(acts) else None
        act = QtGui.QAction(icons.icon("render_cancel"), "Cancel Render", menu)
        act.setText(keymap.render("Cancel Render\t{window.render_cancel}"))   # the window action has the key
        act.setEnabled(self._rendering and getattr(self, "_render_win", None) is not None)
        act.setToolTip("Stop the running render (image or animation)")
        act.triggered.connect(self.cancel_render)
        if before is not None:
            menu.insertAction(before, act)
        else:
            menu.addAction(act)

    def _on_render_done(self):
        if not self._rendering:
            return
        win = getattr(self, "_render_win", None)
        if win is not None:
            self._close_render_helper(win)
        cancelled = getattr(self, "_render_cancelled", False)
        self._render_cancelled = False
        anim = getattr(self, "_render_anim", False)
        self._set_rendering(False, anim)
        if anim:
            try:
                self.timeline.sync()            # Blender puts the scene frame back after the render
            except Exception:
                pass
            if cancelled:
                self.statusBar().showMessage("Animation render cancelled.", 6000)
            else:
                self.statusBar().showMessage(f"Animation rendered to {bpy.context.scene.render.filepath}", 8000)
            ap = getattr(self, "anim_player", None)
            if ap is not None and ap.is_shown():
                ap.update_animation()          # an open player shows the new frames right away
            return
        self.statusBar().showMessage("Render cancelled." if cancelled else "Render finished.", 4000)
        self.render_window.render_finished()
        self.render_window.present()

    def view_animation(self):
        """Render → View Animation (Ctrl+F11): the Animation Player (rendered frames + timeline)."""
        from .anim_player import AnimPlayer
        if getattr(self, "anim_player", None) is None:
            self.anim_player = AnimPlayer(self)
        self.anim_player.present()

    def show_render(self):
        """View Render (F11): opens the render window with the last result; F11 again closes it."""
        rv = self.render_window
        if rv.isVisible() and rv.isActiveWindow():
            rv.close()
            return
        rv.load_result(keep_view=rv.isVisible())
        rv.present()

    # ------------------------------------------------------------ misc
    def search(self):
        dlg = OperatorSearch(self)
        dlg.move(self.mapToGlobal(QtCore.QPoint(self.width() // 2 - 260, 80)))
        dlg.show()
        dlg.edit.setFocus()

    def _set_mode(self, idx):
        mode = self.mode_combo.itemData(idx)
        run_op("object.mode_set", {"mode": mode})
        self._on_mode(bpy.context.mode)

    def _set_selmode(self, i):
        from . import editmesh
        shift = QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier
        cur = list(editmesh.select_mode())
        if shift:
            cur[i] = not cur[i]
            if not any(cur):
                cur[i] = True
        else:
            cur = [k == i for k in range(3)]
        editmesh.set_select_mode(*cur)
        self._sync_selmode()
        self.viewports.request_redraw()

    def _sync_selmode(self):
        try:
            mode = tuple(bpy.context.tool_settings.mesh_select_mode)
        except Exception:
            return
        edit = bpy.context.mode == "EDIT_MESH"
        for b, on in zip(self.selmode_buttons, mode):
            b.setVisible(edit)
            b.setChecked(bool(on))

    def _on_mode(self, mode):
        ob = bpy.context.view_layer.objects.active
        cur = ob.mode if ob else "OBJECT"
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(cur)))
        self.mode_combo.blockSignals(False)
        for m in getattr(self, "mesh_menus", []):
            m.menuAction().setVisible(mode == "EDIT_MESH")
        self._sync_selmode()
        self._sync_mode_combo()
        try:
            self._rebuild_editor_menus()
            self._sync_header()
        except Exception:
            bridge.log("3D view header:\n" + __import__("traceback").format_exc(), "WARNING")
        self.viewports.request_redraw()

    # modes offered by the mode menu, per object type (like Blender)
    _TYPE_MODES = {
        "MESH": ("OBJECT", "EDIT", "SCULPT", "VERTEX_PAINT", "WEIGHT_PAINT", "TEXTURE_PAINT"),
        "ARMATURE": ("OBJECT", "EDIT", "POSE"),
        "CURVE": ("OBJECT", "EDIT"), "SURFACE": ("OBJECT", "EDIT"), "META": ("OBJECT", "EDIT"),
        "FONT": ("OBJECT", "EDIT"), "LATTICE": ("OBJECT", "EDIT"),
        "CURVES": ("OBJECT", "EDIT", "SCULPT_CURVES"),
        "GREASEPENCIL": ("OBJECT", "EDIT", "SCULPT_GREASE_PENCIL", "PAINT_GREASE_PENCIL",
                         "WEIGHT_GREASE_PENCIL", "VERTEX_GREASE_PENCIL"),
    }

    def _sync_mode_combo(self):
        ob = bpy.context.view_layer.objects.active
        modes = self._TYPE_MODES.get(ob.type if ob else "", ("OBJECT",))
        if tuple(self.mode_combo.itemData(i) for i in range(self.mode_combo.count())) != modes:
            items = bpy.types.Object.bl_rna.properties["mode"].enum_items
            self.mode_combo.blockSignals(True)
            self.mode_combo.clear()
            for m in modes:
                it = items.get(m)
                self.mode_combo.addItem(icons.icon(MODE_ICONS.get(m, "")), tr(it.name) if it else m.title(), m)
            self.mode_combo.blockSignals(False)
        cur = ob.mode if ob else "OBJECT"
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(cur)))
        self.mode_combo.blockSignals(False)

    def _sync_shading(self):
        b = self.shading_buttons.get(self.viewport.shading())
        if b:
            b.setChecked(True)
        self._sync_header()

    def _camera_to_view(self):
        cam = bpy.context.scene.camera
        if cam is None:
            return
        vp = self.viewport
        vm, _pm = vp.matrices(vp.width(), vp.height())
        cam.matrix_world = vm.inverted()
        bridge.undo_push("Camera to View")

    def _toggle_maximize_viewport(self):
        vis = any(d.isVisible() for d in self.docks.values())
        if vis:
            self._hidden_docks = [d for d in self.docks.values() if d.isVisible()]
            for d in self._hidden_docks:
                d.hide()
        else:
            for d in getattr(self, "_hidden_docks", []):
                d.show()

    def _scale_docks(self, ratio):
        """Side docks get wider/narrower with the interface size; the viewport keeps ≥ 40 % of the width."""
        side = {}
        for d in self.docks.values():
            if d.isFloating() or not d.isVisible():
                continue
            area = self.dockWidgetArea(d)
            if area in (QtCore.Qt.LeftDockWidgetArea, QtCore.Qt.RightDockWidgetArea):
                side.setdefault(area, []).append(d)
        if not side:
            return
        # one width per side (docks stacked on one side share it)
        widths = {a: max(d.width() for d in ds) * ratio for a, ds in side.items()}
        limit = self.width() * 0.6
        total = sum(widths.values())
        if total > limit:
            widths = {a: w * limit / total for a, w in widths.items()}
        docks = [ds[0] for ds in side.values()]
        self.resizeDocks(docks, [int(widths[a]) for a in side], QtCore.Qt.Horizontal)

    def toggle_sidebar(self):
        d = self.docks["sidebar"]
        d.setVisible(not d.isVisible())
        if d.isVisible():
            d.raise_()
            if not d.isFloating() and d.width() < theme.px(180):
                self.resizeDocks([d], [theme.px(260)], QtCore.Qt.Horizontal)

    def show_qt_preferences(self):
        from . import prefs_window
        prefs_window.show(self)

    def extend_builtin_menu(self, menu, key):
        """Adds Qt Shell's own items to menus generated from Blender (called when they open)."""
        if key != "edit":
            return
        act = QtGui.QAction("Qt Preferences…", menu)
        act.setToolTip("Settings of Qt Shell (Blender's own settings: Preferences…)")
        act.triggered.connect(self.show_qt_preferences)
        keys = QtGui.QAction("Keyboard Shortcuts…", menu)
        keys.setToolTip("All Qt Shell shortcuts in one window – search and change them; "
                        "mouse navigation Blender / Maya")
        keys.triggered.connect(self.show_shortcuts)
        after = None
        acts = menu.actions()
        for i, a in enumerate(acts):
            if a.text().replace("&", "").strip().lower().startswith("preferences"):
                after = acts[i + 1] if i + 1 < len(acts) else None
                for x in (act, keys):
                    menu.insertAction(after, x) if after is not None else menu.addAction(x)
                return
        menu.addSeparator()
        menu.addAction(act)
        menu.addAction(keys)

    def show_shortcuts(self):
        from . import shortcuts_window
        shortcuts_window.show(self)

    def _interface_size(self):
        InterfaceSizeDialog(self).exec()

    def _restore_saved_layout(self, st):
        try:
            self.restoreState(st)
        except Exception:
            bridge.log("Saved window layout: " + __import__("traceback").format_exc(), "WARNING")
        try:
            # a layout saved before the Shelf dock existed: put it at the top
            if not self.restoreDockWidget(self.docks["shelf"]):
                self.addDockWidget(QtCore.Qt.TopDockWidgetArea, self.docks["shelf"])
                self.docks["shelf"].show()
            # a layout saved before the sidebar existed: give it its own full-height column
            sb = self.docks["sidebar"]
            if not self.restoreDockWidget(sb):
                self.addDockWidget(QtCore.Qt.RightDockWidgetArea, sb, QtCore.Qt.Horizontal)
                sb.hide()
            # never float from a restored state (floating docks float again later, see _float_saved_docks)
            for d in self.docks.values():
                if d.isFloating():
                    d.setFloating(False)
        except RuntimeError:
            pass

    def _reset_layout(self):
        for key, area in (("outliner", QtCore.Qt.RightDockWidgetArea), ("properties", QtCore.Qt.RightDockWidgetArea),
                          ("timeline", QtCore.Qt.BottomDockWidgetArea), ("console", QtCore.Qt.BottomDockWidgetArea),
                          ("last_op", QtCore.Qt.LeftDockWidgetArea),
                          ("node_editor", QtCore.Qt.BottomDockWidgetArea),
                          ("uv_editor", QtCore.Qt.BottomDockWidgetArea),
                          ("text_editor", QtCore.Qt.BottomDockWidgetArea),
                          ("graph_editor", QtCore.Qt.BottomDockWidgetArea),
                          ("shelf", QtCore.Qt.TopDockWidgetArea)):
            d = self.docks[key]
            d.setFloating(False)
            self.addDockWidget(area, d)
            d.show()
        self.tabifyDockWidget(self.docks["timeline"], self.docks["console"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["node_editor"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["uv_editor"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["text_editor"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["graph_editor"])

    def _on_log(self, msg, level):
        if level in ("ERROR", "WARNING"):
            line = msg.splitlines()[-1] if msg else msg
            self._last_log_line = line          # already in the Console as a log message
            self.statusBar().showMessage(line, 6000)

    # ------------------------------------------------------------ status history
    def _on_status_message(self, msg):
        if not msg:
            return                               # the message timed out / was cleared
        hist = status_history()
        stamp = time.strftime("%H:%M:%S")
        if hist and hist[-1][1] == msg and time.time() - hist[-1][2] < 0.5:
            return                               # the same message set twice in a row
        hist.append((stamp, msg, time.time()))
        if msg != self._last_log_line:
            try:
                self.console.write(f"[status {stamp}] {msg}\n", "#8a8a8a")
            except Exception:
                pass
        self._last_log_line = None
        if self._status_dialog is not None and self._status_dialog.isVisible():
            self._status_dialog.refresh()

    def show_status_history(self):
        if self._status_dialog is None:
            self._status_dialog = StatusHistoryDialog(self)
        self._status_dialog.refresh()
        self._status_dialog.show()
        self._status_dialog.raise_()
        self._status_dialog.activateWindow()

    def eventFilter(self, obj, ev):
        if obj is self.statusBar() and ev.type() == QtCore.QEvent.MouseButtonRelease \
                and ev.button() == QtCore.Qt.LeftButton:
            self.show_status_history()
            return True
        return super().eventFilter(obj, ev)

    def _on_file_loaded(self):
        try:
            scripts.on_file_loaded()
        except Exception:
            bridge.log("Scripts: " + __import__("traceback").format_exc(), "ERROR")
        self._update_title()
        self._sync_shading()
        for v in self.viewports.visible_views():
            v.frame_all()
        p = shell_app.prefs()
        if (p is None or p.hide_blender) and not self.blender_visible_act.isChecked():
            bridge.later(lambda: shell_app.set_blender_visible(False), 0.3)

    def _update_title(self):
        path = bpy.data.filepath
        name = os.path.basename(path) if path else "(unsaved)"
        dirty = "*" if bpy.data.is_dirty else ""
        self.setWindowTitle(f"Qt Shell · {name}{dirty}")

    def _update_status(self):
        try:
            ctx = bpy.context
            sel = len(ctx.selected_objects)
            total = len(ctx.view_layer.objects)
            self.status_right.setText(f"Objects {sel}/{total}  |  Blender {bpy.app.version_string}  |  "
                                      f"Qt Shell {_QT_SHELL_VERSION}")
        except Exception:
            pass

    def closeEvent(self, ev):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Close Qt Shell")
        box.setText("What do you want to do?")
        quit_b = box.addButton("Quit Blender", QtWidgets.QMessageBox.DestructiveRole)
        back_b = box.addButton("Return to the Blender UI", QtWidgets.QMessageBox.AcceptRole)
        box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is quit_b:
            if bpy.data.is_dirty and not self._confirm_discard():
                ev.ignore()
                return
            ev.ignore()
            shell_app.stop()

            def _quit():
                with bridge.blender_context():
                    bpy.ops.wm.quit_blender()
            bridge.later(_quit, 0.1)
            return
        if clicked is back_b:
            ev.ignore()
            QtCore.QTimer.singleShot(0, shell_app.stop)
            return
        ev.ignore()

    def shutdown(self):
        # A saved layout with a floating dock crashes Qt on Windows on the next start (access
        # violation in show(), even when the dock is docked again before that). Floating works at
        # run time, so floating docks are docked before the layout is saved.
        floating = {}
        for key, d in self.docks.items():
            try:
                if d.isFloating() and not d.isHidden():
                    g = d.geometry()
                    floating[key] = [g.x(), g.y(), g.width(), g.height()]
            except RuntimeError:
                pass
        try:
            if getattr(self, "workspaces", None) is not None:
                # the current workspace keeps the layout it was left with (docks are not re-floated here)
                self.workspaces.shutdown(floating)
        except Exception:
            pass
        try:
            import json
            self._settings.setValue("floating_docks", json.dumps(floating))
        except Exception:
            pass
        # Render View / Animation Player docks are never part of the saved layout (see dockable.py)
        for w in (self.render_window, getattr(self, "anim_player", None)):
            try:
                if w is not None:
                    w.release_dock()
            except Exception:
                pass
        for d in list(self.docks.values()) + list(getattr(self, "api_docks", {}).values()):
            try:
                if d.isFloating():
                    d.setFloating(False)
            except RuntimeError:
                pass
        try:
            self._settings.setValue("geometry", self.saveGeometry())
            self._settings.setValue("state", self.saveState())
            self._settings.setValue("size_factor", self._size_factor)
        except Exception:
            pass
        try:
            self._settings.setValue("viewport_layout", self.viewports.mode)
        except Exception:
            pass
        self.viewports.shutdown()
        self.timeline.stop()
        try:
            self.text_editor.shutdown()   # keep the last typed text in bpy.data.texts
        except Exception:
            pass
        self.render_window.close()
        if getattr(self, "anim_player", None) is not None:
            self.anim_player.close()

"""Qt Shell main window: menus, docks, viewport, render, last operation, search."""
import math
import os
import tempfile

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import app as shell_app
from . import api, bridge, rna_widgets as rw, theme
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
from .viewport import Viewport

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
MODES = [("OBJECT", "Object Mode"), ("EDIT", "Edit Mode"), ("SCULPT", "Sculpt Mode"),
         ("VERTEX_PAINT", "Vertex Paint"), ("WEIGHT_PAINT", "Weight Paint"),
         ("TEXTURE_PAINT", "Texture Paint"), ("POSE", "Pose Mode")]
DISCARDING_OPS = {"wm.open_mainfile", "wm.read_homefile", "wm.revert_mainfile",
                  "wm.recover_last_session", "wm.recover_auto_save", "wm.read_factory_settings"}


def _mode_menu(kind):
    def resolve():
        mode = bpy.context.mode
        table = MODE_MENUS[kind]
        return table.get(mode, table["OBJECT"])
    return resolve


# ---------------------------------------------------------------- render window
class RenderWindow(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Render")
        self.resize(960, 600)
        lay = QtWidgets.QVBoxLayout(self)
        self.label = QtWidgets.QLabel("Nothing rendered yet.")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setMinimumSize(1, 1)
        self.label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        lay.addWidget(self.label, 1)
        row = QtWidgets.QHBoxLayout()
        self.info = QtWidgets.QLabel("")
        self.info.setProperty("dim", True)
        row.addWidget(self.info, 1)
        save = QtWidgets.QPushButton("Save Image…")
        save.clicked.connect(self.save)
        row.addWidget(save)
        lay.addLayout(row)
        self.pixmap = None

    def load_result(self):
        img = bpy.data.images.get("Render Result")
        if img is None:
            self.label.setText("Render Result does not exist.")
            return False
        path = os.path.join(tempfile.gettempdir(), "qtshell_render.png")
        try:
            img.save_render(filepath=path)
        except Exception as ex:
            self.label.setText(f"Cannot load the result: {ex}")
            return False
        self.pixmap = QtGui.QPixmap(path)
        self._fit()
        self.info.setText(f"{self.pixmap.width()} × {self.pixmap.height()} px")
        return True

    def _fit(self):
        if self.pixmap is not None and not self.pixmap.isNull():
            self.label.setPixmap(self.pixmap.scaled(self.label.size(), QtCore.Qt.KeepAspectRatio,
                                                    QtCore.Qt.SmoothTransformation))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit()

    def save(self):
        if self.pixmap is None:
            return
        start = os.path.join(os.path.dirname(bpy.data.filepath) or os.path.expanduser("~"), "render.png")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Render", start,
                                                        "Images (*.png *.jpg *.exr *.tif)")
        if not path:
            return
        img = bpy.data.images.get("Render Result")
        try:
            img.save_render(filepath=path)
        except Exception as ex:
            QtWidgets.QMessageBox.warning(self, "Error", str(ex))


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
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        hub.main_window = self
        self.setWindowTitle("Qt Shell")
        self.resize(1500, 920)
        self.setDockOptions(QtWidgets.QMainWindow.AnimatedDocks | QtWidgets.QMainWindow.AllowTabbedDocks)

        # viewport + header
        self.viewport = Viewport(hub, shell_app.prefs())
        hub.viewport = self.viewport
        center = QtWidgets.QWidget()
        cl = QtWidgets.QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._viewport_header())
        cl.addWidget(self.viewport, 1)
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
        # 3D viewport sidebar (N panel): next to the viewport, hidden by default like in Blender
        self._dock("sidebar", "Sidebar", self.sidebar, QtCore.Qt.RightDockWidgetArea)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.docks["sidebar"], QtCore.Qt.Horizontal)
        self.docks["sidebar"].hide()
        self.tabifyDockWidget(self.docks["timeline"], self.docks["console"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["node_editor"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["uv_editor"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["text_editor"])
        self.docks["timeline"].raise_()
        self.resizeDocks([self.docks["outliner"], self.docks["properties"]], [260, 560], QtCore.Qt.Vertical)
        self.resizeDocks([self.docks["properties"]], [400], QtCore.Qt.Horizontal)
        self.resizeDocks([self.docks["last_op"]], [230], QtCore.Qt.Horizontal)

        self.render_window = RenderWindow(self)
        self._build_menus()
        self._build_shortcuts()
        self.status_right = QtWidgets.QLabel()
        self.statusBar().addPermanentWidget(self.status_right)

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
        self.viewport.selection_edited.connect(self._sync_selmode)
        hub.mode_changed.connect(self._on_mode)
        hub.render_done.connect(self._on_render_done)
        hub.file_loaded.connect(self._on_file_loaded)
        self.viewport.status.connect(lambda s: self.statusBar().showMessage(s, 4000))
        self._rendering = False

        self._settings = QtCore.QSettings("QtShell", "QtShell")
        try:
            geo = self._settings.value("geometry")
            st = self._settings.value("state")
            if geo is not None:
                self.restoreGeometry(geo)
            if st is not None:
                self.restoreState(st)
            old = float(self._settings.value("size_factor", 1.0) or 1.0)
        except Exception:
            old = 1.0
        # a layout saved before the sidebar existed: give it its own full-height column
        sb = self.docks["sidebar"]
        if not self.restoreDockWidget(sb):
            self.addDockWidget(QtCore.Qt.RightDockWidgetArea, sb, QtCore.Qt.Horizontal)
            sb.hide()
        # dock sizes are stored in pixels → follow a change of the interface size
        self._size_factor = theme.ui_scale * theme.font_scale ** 0.5
        ratio = self._size_factor / old if old > 0 else 1.0
        if abs(ratio - 1.0) > 0.01:
            QtCore.QTimer.singleShot(0, lambda r=ratio: self._scale_docks(r))
        self._update_title()
        self._update_status()
        self._on_mode(bpy.context.mode)
        self.viewport.frame_all()
        # docks, menu items, overlays and event handlers registered by add-ons (qt_shell.api)
        try:
            api.apply_to_window(self)
        except Exception:
            bridge.log("Qt Shell API: " + __import__("traceback").format_exc(), "ERROR")
        # auto-load scripts (files: once per session, texts of the .blend: once per file)
        QtCore.QTimer.singleShot(0, self._scripts_startup)

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
        bar.setStyleSheet("background:#303030;")
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(3)
        self.mode_combo = rw.NoWheelCombo()
        for ident, label in MODES:
            self.mode_combo.addItem(tr(label), ident)
        self.mode_combo.activated.connect(self._set_mode)
        lay.addWidget(self.mode_combo)
        for title, kind in (("View", None), ("Select", "select"), ("Add", "add"), ("Object", "object")):
            b = QtWidgets.QToolButton()
            b.setText(tr(title))
            b.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            b.setAutoRaise(True)
            b.setMenu(self._view_menu(b) if kind is None else LazyMenu(None, b, resolver=_mode_menu(kind)))
            lay.addWidget(b)
        self.selmode_buttons = []
        for i, (txt, tip) in enumerate((("•", "Vertices (1)"), ("╱", "Edges (2)"), ("■", "Faces (3)"))):
            b = QtWidgets.QToolButton()
            b.setText(txt)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self._set_selmode(i))
            lay.addWidget(b)
            self.selmode_buttons.append(b)
        lay.addStretch(1)
        for txt, tip, kind in (("G", "Move (G)", "G"), ("R", "Rotate (R)", "R"), ("S", "Scale (S)", "S")):
            b = QtWidgets.QToolButton()
            b.setText(txt)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=kind: self.viewport.start_modal(k))
            lay.addWidget(b)
        lay.addSpacing(10)
        self.shading_group = QtWidgets.QButtonGroup(bar)
        self.shading_buttons = {}
        for kind, txt, tip in (("WIREFRAME", "◇", "Wireframe"), ("SOLID", "●", "Solid"),
                               ("MATERIAL", "◐", "Material Preview"), ("RENDERED", "☀", "Rendered")):
            b = QtWidgets.QToolButton()
            b.setText(txt)
            b.setToolTip(tip)
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
        lay.addWidget(sb)
        ov = QtWidgets.QToolButton()
        ov.setText("Overlays ▾")
        ov.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        ov.setMenu(PopoverMenu("VIEW3D_PT_overlay", ov))
        lay.addWidget(ov)
        QtCore.QTimer.singleShot(0, self._sync_shading)
        return bar

    def _view_menu(self, parent):
        m = QtWidgets.QMenu(parent)
        vp = self.viewport
        m.addAction("Frame Selected (Num .)", vp.frame_selected)
        m.addAction("Frame All (Home)", vp.frame_all)
        m.addSeparator()
        for key, label in (("FRONT", "Front (1)"), ("BACK", "Back (Ctrl+1)"), ("RIGHT", "Right (3)"),
                           ("LEFT", "Left (Ctrl+3)"), ("TOP", "Top (7)"), ("BOTTOM", "Bottom (Ctrl+7)"),
                           ("CAMERA", "Camera (0)")):
            m.addAction(label, lambda k=key: vp.set_view(k))
        m.addAction("Perspective / Orthographic (5)", vp.toggle_ortho)
        m.addSeparator()
        a = m.addAction("Selection boxes in Qt")
        a.setCheckable(True)
        a.setChecked(False)
        a.toggled.connect(lambda on: (setattr(vp, "show_boxes", on), vp.update()))
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
        blender_menu("Render", "TOPBAR_MT_render")

        win = mb.addMenu(tr("Window"))
        win.setProperty("qtshell_key", "Window")
        for key, d in self.docks.items():
            act = d.toggleViewAction()
            if key == "sidebar":
                act.setText("Sidebar (N)")
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
        def sc(keys, fn):
            for k in keys if isinstance(keys, (list, tuple)) else [keys]:
                a = QtGui.QAction(self)
                a.setShortcut(QtGui.QKeySequence(k))
                a.setShortcutContext(QtCore.Qt.WindowShortcut)
                a.triggered.connect(fn)
                self.addAction(a)
        sc("Ctrl+N", lambda: run_op("wm.read_homefile", {"app_template": ""}))
        sc("Ctrl+O", lambda: run_op("wm.open_mainfile"))
        sc("Ctrl+S", lambda: run_op("wm.save_mainfile"))
        sc("Ctrl+Shift+S", lambda: run_op("wm.save_as_mainfile"))
        sc("Ctrl+Z", lambda: run_op("ed.undo"))
        sc(["Ctrl+Shift+Z", "Ctrl+Y"], lambda: run_op("ed.redo"))
        sc("F3", self.search)
        sc("F12", lambda: self.render_image(False))
        sc("Ctrl+F12", lambda: self.render_image(True))
        sc("F11", self.show_render)
        sc("Ctrl+Q", self.close)
        sc("Space", self.timeline.toggle_play)
        sc("Ctrl+Space", self._toggle_maximize_viewport)

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
        if idname == "wm.quit_blender":
            self.close()
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
            with bridge.blender_context():
                res = bpy.ops.render.render("INVOKE_DEFAULT", animation=animation)
            if "RUNNING_MODAL" in res:
                self._rendering = True
                self._render_anim = animation
                self.statusBar().showMessage("Renderuji…")
                return
        except Exception as ex:
            bridge.log(f"Asynchronous render failed ({ex}), rendering in blocking mode.", "WARNING")
        finally:
            view.render_display_type = old
        # fallback: blocking render
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

    def _on_render_done(self):
        if not self._rendering:
            return
        self._rendering = False
        if getattr(self, "_render_anim", False):
            self.statusBar().showMessage(f"Animation rendered to {bpy.context.scene.render.filepath}", 8000)
            return
        self.statusBar().showMessage("Render finished.", 4000)
        self.show_render()

    def show_render(self):
        self.render_window.load_result()
        self.render_window.show()
        self.render_window.raise_()

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
        self.viewport.request_redraw()

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
        self.viewport.request_redraw()

    def _sync_shading(self):
        b = self.shading_buttons.get(self.viewport.shading())
        if b:
            b.setChecked(True)

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

    def _interface_size(self):
        InterfaceSizeDialog(self).exec()

    def _reset_layout(self):
        for key, area in (("outliner", QtCore.Qt.RightDockWidgetArea), ("properties", QtCore.Qt.RightDockWidgetArea),
                          ("timeline", QtCore.Qt.BottomDockWidgetArea), ("console", QtCore.Qt.BottomDockWidgetArea),
                          ("last_op", QtCore.Qt.LeftDockWidgetArea),
                          ("node_editor", QtCore.Qt.BottomDockWidgetArea),
                          ("uv_editor", QtCore.Qt.BottomDockWidgetArea),
                          ("text_editor", QtCore.Qt.BottomDockWidgetArea)):
            d = self.docks[key]
            d.setFloating(False)
            self.addDockWidget(area, d)
            d.show()
        self.tabifyDockWidget(self.docks["timeline"], self.docks["console"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["node_editor"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["uv_editor"])
        self.tabifyDockWidget(self.docks["timeline"], self.docks["text_editor"])

    def _on_log(self, msg, level):
        if level in ("ERROR", "WARNING"):
            self.statusBar().showMessage(msg.splitlines()[-1] if msg else msg, 6000)

    def _on_file_loaded(self):
        try:
            scripts.on_file_loaded()
        except Exception:
            bridge.log("Scripts: " + __import__("traceback").format_exc(), "ERROR")
        self._update_title()
        self._sync_shading()
        self.viewport.frame_all()
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
            self.status_right.setText(f"Objects {sel}/{total}  |  Blender {bpy.app.version_string}")
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
        try:
            self._settings.setValue("geometry", self.saveGeometry())
            self._settings.setValue("state", self.saveState())
            self._settings.setValue("size_factor", self._size_factor)
        except Exception:
            pass
        self.viewport.shutdown()
        self.timeline.stop()
        try:
            self.text_editor.shutdown()   # keep the last typed text in bpy.data.texts
        except Exception:
            pass
        self.render_window.close()

"""Shelf – a bar of script buttons like Maya's shelf.

- Tabs (shelves) with buttons; a button runs Python code (or a .py file) with one click.
- Add buttons: drag selected code from the Text editor onto the shelf, "→ Shelf" in the Text editor,
  drop a .py file from the file manager, or right click → New Button….
- Right click a button: Edit… (label, icon, tooltip, code), Duplicate, Move Left / Right, Delete.
- Right click the tabs / empty space: New Shelf…, Rename Shelf…, Delete Shelf.
- Stored in Blender's config folder: config/qt_shell/shelves.json.
- Built-in shelves (Polygons, Modeling, Modifiers, UV, Rigging, Animation, Rendering) come from
  shelf_presets.py – added once, then they are the user's like any other shelf.
- Icon: an emoji / symbol, an image file, or "bl:NAME" – a Blender icon (MESH_CUBE, MOD_MIRROR, …).
- Button code runs in a 3D view context, so bpy.ops work as in Blender's 3D view.
"""
import copy
import json
import os
import re
import time
import traceback

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import api, bridge, scripts, theme
from . import pytips

DEFAULT = {
    "current": 0,
    "shelves": [{
        "name": "Custom",
        "buttons": [
            {"label": "Cube", "icon": "🧊", "tooltip": "Add a cube at the 3D cursor",
             "command": "import bpy\nbpy.ops.mesh.primitive_cube_add("
                        "location=bpy.context.scene.cursor.location)\n"},
            {"label": "Smooth", "icon": "◍", "tooltip": "Shade the selected objects smooth",
             "command": "import bpy\nbpy.ops.object.shade_smooth()\n"},
            {"label": "Views", "icon": "▦", "tooltip": "Four views ↔ one view",
             "command": "import qt_shell.api as qs\n"
                        "qs.set_viewport_layout('single' if qs.viewport_layout() == 'quad' else 'quad')\n"},
        ],
    }],
}


# ---------------------------------------------------------------- storage
def _path():
    d = bpy.utils.user_resource("CONFIG", path="qt_shell", create=True)
    return os.path.join(d, "shelves.json")


def load():
    data = None
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        if not (isinstance(data, dict) and isinstance(data.get("shelves"), list) and data["shelves"]):
            data = None
    except FileNotFoundError:
        pass
    except Exception:
        bridge.log(f"Shelf: cannot read {_path()}:\n{traceback.format_exc()}", "WARNING")
        return copy.deepcopy(DEFAULT)           # never overwrite a file we couldn't read
    if data is None:
        data = copy.deepcopy(DEFAULT)
    try:
        from . import shelf_presets
        if shelf_presets.add_builtin_shelves(data):
            save(data)
    except Exception:
        bridge.log(f"Shelf: built-in shelves:\n{traceback.format_exc()}", "WARNING")
    return data


STYLE_DEFAULTS = {"show_icons": True, "icon_size": 22, "show_labels": True, "label_size": 10}


def style():
    """Shelf look (Qt Preferences → Shelf): icons on / size, labels on / size – QSettings shelf/*."""
    st = QtCore.QSettings("QtShell", "QtShell")
    out = {}
    for k, d in STYLE_DEFAULTS.items():
        v = st.value(f"shelf/{k}", d)
        if isinstance(d, bool):
            out[k] = v in (True, "true", "1", 1)
        else:
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                out[k] = d
    out["icon_size"] = max(12, min(96, out["icon_size"]))
    out["label_size"] = max(6, min(24, out["label_size"]))
    return out


def set_style(**kw):
    st = QtCore.QSettings("QtShell", "QtShell")
    for k, v in kw.items():
        if k in STYLE_DEFAULTS:
            st.setValue(f"shelf/{k}", ("true" if v else "false") if isinstance(STYLE_DEFAULTS[k], bool) else int(v))


def button_icon(spec, px=None):
    """QIcon for a button's icon field: "bl:NAME" (Blender icon) or an image file; None otherwise."""
    if not spec:
        return None
    if spec.startswith("bl:"):
        from . import blicons
        name = spec[3:].strip()
        if not blicons.has(name):
            return None
        if px:                                   # sharp at any shelf icon size (blicons' set ends at 48 px)
            ic = QtGui.QIcon()
            for k in (1, 2):
                ic.addPixmap(QtGui.QPixmap.fromImage(blicons._render(name, int(px * k))))
            return ic
        return blicons.icon(name)
    if os.path.isfile(spec):
        return QtGui.QIcon(spec)
    return None


def save(data):
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        bridge.log(f"Shelf: cannot save {_path()}:\n{traceback.format_exc()}", "ERROR")


# ---------------------------------------------------------------- running
def run_button(btn):
    """Runs the code / file of a button in Blender's context; output goes to the Console."""
    label = btn.get("label") or "Button"
    path = btn.get("file")
    try:
        if path:
            with open(path, encoding="utf-8") as f:
                src = f.read()
            filename = path
        else:
            src = btn.get("command", "")
            filename = f"<shelf {label}>"
    except Exception as ex:
        scripts.show_console()
        scripts.report(f"\n▶ Shelf: {label}\n{ex}\n", "#ff7070")
        api.status(f"Shelf '{label}': {ex}")
        return
    ns = {"__name__": "__main__", "__file__": filename, "bpy": bpy}
    info = {"ns": ns, "handlers": [], "classes": [], "status": "ran", "time": time.time(),
            "filename": filename}
    try:
        with bridge.blender_context():          # bpy.ops behave as in Blender's 3D view
            ok, output, line = scripts._execute(f"shelf:{label}", src, filename, ns, info)
    except Exception as ex:                     # no 3D view to override – run as before
        bridge.log(f"Shelf '{label}': context: {ex}", "WARNING")
        ok, output, line = scripts._execute(f"shelf:{label}", src, filename, ns, info)
    if output:
        scripts.report(f"\n▶ Shelf: {label}\n", "#8fb3ff")
        scripts.report(output if output.endswith("\n") else output + "\n", "#e5e5e5" if ok else "#ff7070")
    if not ok:
        scripts.show_console()
        api.status(f"Shelf '{label}': error{f' on line {line}' if line else ''} – see the Console")
    else:
        api.status(f"Shelf: {label}")
    # show the result right away, also while Blender's own loop is not running (e.g. from a dialog)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    api.redraw()
    bridge.undo_push(f"Shelf: {label}")


def label_for_code(code, fallback="Script"):
    """A short button label from code: first def / class name, or the first word of a comment."""
    m = re.search(r"^\s*(?:def|class)\s+(\w+)", code, re.M)
    if m and m.group(1) not in ("register", "unregister", "main"):
        return m.group(1)[:12]
    m = re.search(r"^\s*#\s*(\w[\w ]{0,20})", code, re.M)
    if m:
        return m.group(1).strip()[:12]
    return fallback[:12]


def _alive(w):
    try:
        w.isVisible()
        return True
    except RuntimeError:
        return False


# ---------------------------------------------------------------- edit dialog
class ButtonDialog(QtWidgets.QDialog):
    def __init__(self, parent, btn, title="Edit Shelf Button"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(theme.px(620), theme.px(460))
        self.btn = dict(btn)
        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        lay.addLayout(form)
        self.label = QtWidgets.QLineEdit(self.btn.get("label", ""), self)
        self.label.setPlaceholderText("Text on the button")
        form.addRow("Label", self.label)
        icon_row = QtWidgets.QHBoxLayout()
        self.icon = QtWidgets.QLineEdit(self.btn.get("icon", ""), self)
        self.icon.setPlaceholderText("emoji / symbol (🧊 ◍ ★), bl:MESH_CUBE (Blender icon) or an image file")
        icon_row.addWidget(self.icon, 1)
        browse = QtWidgets.QPushButton("Image…", self)
        browse.clicked.connect(self._browse_icon)
        icon_row.addWidget(browse)
        form.addRow("Icon", icon_row)
        self.tip = QtWidgets.QLineEdit(self.btn.get("tooltip", ""), self)
        self.tip.setPlaceholderText("Shown when the mouse is over the button")
        form.addRow("Tooltip", self.tip)
        file_row = QtWidgets.QHBoxLayout()
        self.file = QtWidgets.QLineEdit(self.btn.get("file", "") or "", self)
        self.file.setPlaceholderText("optional – run this .py file instead of the code below")
        file_row.addWidget(self.file, 1)
        fb = QtWidgets.QPushButton("File…", self)
        fb.clicked.connect(self._browse_file)
        file_row.addWidget(fb)
        form.addRow("Script file", file_row)
        from .text_editor import CodeEditor
        self.code = CodeEditor(self)
        self.code.setPlainText(self.btn.get("command", ""))
        self.code.setPlaceholderText("Python code, e.g.\nimport bpy\nbpy.ops.mesh.primitive_monkey_add()")
        lay.addWidget(QtWidgets.QLabel("Command (Python)", self))
        lay.addWidget(self.code, 1)
        row = QtWidgets.QHBoxLayout()
        test = QtWidgets.QPushButton("▶ Test", self)
        test.setToolTip("Run the command now")
        test.clicked.connect(lambda: run_button(self.result_button()))
        row.addWidget(test)
        row.addStretch(1)
        ok = QtWidgets.QPushButton("Save", self)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QtWidgets.QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _browse_icon(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Button Image", os.path.expanduser("~"),
                                                        "Images (*.png *.svg *.jpg *.ico)")
        if path:
            self.icon.setText(path)

    def _browse_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Script File", os.path.expanduser("~"),
                                                        "Python (*.py)")
        if path:
            self.file.setText(path)

    def result_button(self):
        b = dict(self.btn)
        b["label"] = self.label.text().strip() or "Button"
        b["icon"] = self.icon.text().strip()
        b["tooltip"] = self.tip.text().strip()
        b["command"] = self.code.toPlainText()
        f = self.file.text().strip()
        if f:
            b["file"] = f
        else:
            b.pop("file", None)
        return b


# ---------------------------------------------------------------- the bar
class ShelfBar(QtWidgets.QWidget):
    """Tabs + a row of buttons. Lives in a QToolBar at the top of the main window."""

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self.data = load()
        self.setAcceptDrops(True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(theme.px(2), 0, theme.px(2), theme.px(2))
        lay.setSpacing(0)
        self.tabs = QtWidgets.QTabBar(self)
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setStyleSheet(f"QTabBar::tab {{ padding: {theme.px(2)}px {theme.px(10)}px; }}")
        self.tabs.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(lambda pos: self._shelf_menu(self.tabs.mapToGlobal(pos)))
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabBarDoubleClicked.connect(lambda i: i >= 0 and self._rename_shelf())
        self.tabs.setToolTip("Double-click to rename, right click for more")
        tab_row = QtWidgets.QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(theme.px(2))
        tab_row.addWidget(self.tabs)
        plus = QtWidgets.QToolButton(self)
        plus.setText("+")
        plus.setAutoRaise(True)
        plus.setToolTip("New shelf tab")
        plus.clicked.connect(self._new_shelf)
        tab_row.addWidget(plus)
        tab_row.addStretch(1)
        lay.addLayout(tab_row)
        # buttons in a horizontally scrolling row (the shelf can be a narrow floating window)
        self.scroll = QtWidgets.QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.row_widget = QtWidgets.QWidget(self.scroll)
        self.row = QtWidgets.QHBoxLayout(self.row_widget)
        self.row.setContentsMargins(0, theme.px(2), 0, 0)
        self.row.setSpacing(theme.px(3))
        self.row_widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.row_widget.customContextMenuRequested.connect(
            lambda pos: self._shelf_menu(self.row_widget.mapToGlobal(pos)))
        self.scroll.setWidget(self.row_widget)
        self.scroll.setFixedHeight(theme.px(44) + theme.px(4) + theme.px(14))
        lay.addWidget(self.scroll)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self._fill_tabs()

    # --- data helpers
    def _shelf(self):
        i = max(0, min(self.data.get("current", 0), len(self.data["shelves"]) - 1))
        return self.data["shelves"][i]

    def _save(self):
        save(self.data)

    # --- building
    def _fill_tabs(self):
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for s in self.data["shelves"]:
            self.tabs.addTab(s.get("name", "Shelf"))
        self.tabs.setCurrentIndex(max(0, min(self.data.get("current", 0), self.tabs.count() - 1)))
        self.tabs.blockSignals(False)
        self._fill_buttons()

    def _tab_changed(self, i):
        self.data["current"] = i
        self._save()
        self._fill_buttons()

    def _fill_buttons(self):
        while self.row.count():
            it = self.row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        st = style()
        icon_px = theme.px(st["icon_size"])
        btn_h = 0
        for idx, b in enumerate(self._shelf().get("buttons", [])):
            tb = QtWidgets.QToolButton(self.row_widget)
            icon = b.get("icon", "")
            label = b.get("label", "")
            qicon = button_icon(icon, icon_px) if st["show_icons"] else None
            # an emoji / symbol icon is text – shown like an icon when icons are on
            emoji = icon if st["show_icons"] and icon and button_icon(icon) is None \
                and not icon.startswith("bl:") and not os.path.isfile(icon) else ""
            # never an empty button: no icon to show → the label stays
            show_label = st["show_labels"] or (qicon is None and not emoji)
            f = tb.font()
            f.setPixelSize(theme.fs(st["label_size"]))
            tb.setFont(f)
            fm = QtGui.QFontMetrics(f)
            if qicon is not None:
                tb.setIcon(qicon)
                # the app stylesheet sets qproperty-iconSize on every button when it is polished, which
                # would undo setIconSize – the button's own stylesheet wins over it
                tb.setStyleSheet(f"QToolButton {{ qproperty-iconSize: {icon_px}px {icon_px}px; }}")
                tb.setIconSize(QtCore.QSize(icon_px, icon_px))
                tb.setText(label)
                tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon if show_label
                                      else QtCore.Qt.ToolButtonIconOnly)
                text_w = fm.horizontalAdvance(label) if show_label else 0
                h = icon_px + (fm.height() + theme.px(2) if show_label else 0) + theme.px(10)
            else:
                if emoji and not show_label:
                    f.setPixelSize(max(theme.fs(8), int(icon_px * 0.8)))
                    tb.setFont(f)
                    fm = QtGui.QFontMetrics(f)
                tb.setText("\n".join(t for t in (emoji, label if show_label else "") if t))
                tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
                text_w = max((fm.horizontalAdvance(t) for t in tb.text().split("\n")), default=0)
                h = fm.height() * len(tb.text().split("\n")) + theme.px(12)
                if emoji and show_label:
                    h = max(h, icon_px + fm.height() + theme.px(12))
            # wide enough for the whole label (no "Su…de"); QToolButton needs ~26 px of margins
            w = max(icon_px + theme.px(14), (text_w + theme.px(26)) if text_w else 0,
                    theme.px(52) if show_label else 0)
            h = max(h, theme.px(24))
            tb.setFixedSize(w, h)
            btn_h = max(btn_h, h)
            tip = b.get("tooltip") or label
            tb.setToolTip(f"<b>{label}</b><br>{tip}<br><i>Right click: edit, duplicate, delete…</i>")
            if b.get("file"):
                pytips.tag(tb, f'exec(open(r"{b["file"]}").read())')
            else:
                code = (b.get("command") or "").strip().splitlines()
                pytips.tag(tb, "\n".join(code[:12]) + ("\n…" if len(code) > 12 else ""))
            tb.clicked.connect(lambda _c=False, i=idx: self._run(i))
            tb.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            tb.customContextMenuRequested.connect(
                lambda pos, i=idx, w=tb: self._button_menu(i, w.mapToGlobal(pos)))
            self.row.addWidget(tb)
        if not self._shelf().get("buttons"):
            hint = QtWidgets.QLabel("Drag code from the Text editor here, or right click → New Button…",
                                    self.row_widget)
            hint.setProperty("dim", True)
            self.row.addWidget(hint)
        self.row.addStretch(1)
        # the row grows / shrinks with the icon and label size (+ room for the horizontal scroll bar)
        self.scroll.setFixedHeight(max(btn_h, theme.px(28)) + theme.px(4) + theme.px(14))

    def apply_style(self):
        """Qt Preferences → Shelf changed: rebuild the buttons with the new sizes."""
        self._fill_buttons()

    # --- actions
    def _run(self, i):
        btns = self._shelf().get("buttons", [])
        if 0 <= i < len(btns):
            run_button(btns[i])

    def _open_dialog(self, btn, title, on_save):
        """Non-modal edit dialog – Blender keeps running, so ▶ Test shows its result right away."""
        dlg = ButtonDialog(self.window(), btn, title)
        dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        dlg.accepted.connect(lambda d=dlg: on_save(d.result_button()))
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        self._dialogs = [d for d in getattr(self, "_dialogs", []) if _alive(d)] + [dlg]
        return dlg

    def add_button(self, btn, edit=False):
        """Adds a button to the current shelf (edit=True opens the edit dialog first)."""
        if edit:
            self._open_dialog(btn, "New Shelf Button", lambda b: self.add_button(b))
            return
        self._shelf().setdefault("buttons", []).append(btn)
        self._save()
        self._fill_buttons()
        api.status(f"Added '{btn.get('label', '')}' to the shelf '{self._shelf().get('name', '')}'")

    def add_code(self, code, label=None):
        if not code.strip():
            return
        self.add_button({"label": label or label_for_code(code), "icon": "", "tooltip": "",
                         "command": code if code.endswith("\n") else code + "\n"}, edit=True)

    def _edit(self, i):
        btns = self._shelf()["buttons"]
        original = btns[i]

        def save_edit(new):
            for s in self.data["shelves"]:          # the button may have moved meanwhile
                bl = s.get("buttons", [])
                for k, b in enumerate(bl):
                    if b is original:
                        bl[k] = new
                        self._changed()
                        return
            self.add_button(new)                    # deleted meanwhile – add it again
        self._open_dialog(original, "Edit Shelf Button", save_edit)

    def _button_menu(self, i, gpos):
        btns = self._shelf()["buttons"]
        m = QtWidgets.QMenu(self)
        m.addAction("Edit…", lambda: self._edit(i))
        m.addAction("Duplicate", lambda: (btns.insert(i + 1, copy.deepcopy(btns[i])), self._changed()))
        m.addSeparator()
        a = m.addAction("Move Left", lambda: (btns.insert(i - 1, btns.pop(i)), self._changed()))
        a.setEnabled(i > 0)
        a = m.addAction("Move Right", lambda: (btns.insert(i + 1, btns.pop(i)), self._changed()))
        a.setEnabled(i < len(btns) - 1)
        if len(self.data["shelves"]) > 1:
            mv = m.addMenu("Move to Shelf")
            for j, s in enumerate(self.data["shelves"]):
                if s is not self._shelf():
                    mv.addAction(s.get("name", "Shelf"),
                                 lambda s=s: (s.setdefault("buttons", []).append(btns.pop(i)), self._changed()))
        m.addSeparator()
        m.addAction("Delete", lambda: self._delete(i))
        m.exec(gpos)

    def _delete(self, i):
        btns = self._shelf()["buttons"]
        r = QtWidgets.QMessageBox.question(self.window(), "Delete Shelf Button",
                                           f"Delete the button “{btns[i].get('label', '')}”?")
        if r == QtWidgets.QMessageBox.Yes:
            btns.pop(i)
            self._changed()

    def _changed(self):
        self._save()
        self._fill_buttons()

    def _shelf_menu(self, gpos):
        m = QtWidgets.QMenu(self)
        m.addAction("New Button…", lambda: self.add_button(
            {"label": "Button", "icon": "", "tooltip": "", "command": "import bpy\n"}, edit=True))
        m.addSeparator()
        m.addAction("New Shelf…", self._new_shelf)
        m.addAction("Rename Shelf…", self._rename_shelf)
        a = m.addAction("Delete Shelf", self._delete_shelf)
        a.setEnabled(len(self.data["shelves"]) > 1)
        m.addSeparator()
        m.addAction("Open the Shelf File Folder",
                    lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(_path()))))
        m.exec(gpos)

    def _new_shelf(self):
        name, ok = QtWidgets.QInputDialog.getText(self.window(), "New Shelf", "Name:")
        if ok and name.strip():
            self.data["shelves"].append({"name": name.strip(), "buttons": []})
            self.data["current"] = len(self.data["shelves"]) - 1
            self._save()
            self._fill_tabs()

    def _rename_shelf(self):
        s = self._shelf()
        name, ok = QtWidgets.QInputDialog.getText(self.window(), "Rename Shelf", "Name:", text=s.get("name", ""))
        if ok and name.strip():
            s["name"] = name.strip()
            self._save()
            self._fill_tabs()

    def _delete_shelf(self):
        s = self._shelf()
        r = QtWidgets.QMessageBox.question(
            self.window(), "Delete Shelf",
            f"Delete the shelf “{s.get('name', '')}” with {len(s.get('buttons', []))} button(s)?")
        if r == QtWidgets.QMessageBox.Yes:
            self.data["shelves"].remove(s)
            self.data["current"] = 0
            self._save()
            self._fill_tabs()

    # --- drag & drop (code from the Text editor, .py files)
    @staticmethod
    def _accept_copy(ev):
        # always copy: the default for text dragged out of an editor is "move", which would
        # delete the code from the Text editor
        ev.setDropAction(QtCore.Qt.CopyAction)
        ev.accept()

    def dragEnterEvent(self, ev):
        md = ev.mimeData()
        if md.hasUrls() and any(u.toLocalFile().lower().endswith(".py") for u in md.urls()):
            self._accept_copy(ev)
        elif md.hasText() and md.text().strip():
            self._accept_copy(ev)
        else:
            ev.ignore()

    def dragMoveEvent(self, ev):
        self._accept_copy(ev)

    def dropEvent(self, ev):
        md = ev.mimeData()
        files = [u.toLocalFile() for u in md.urls()] if md.hasUrls() else []
        files = [f for f in files if f.lower().endswith(".py")]
        self._accept_copy(ev)
        # the edit dialog is modal – open it after the drop has finished
        if files:
            def add_files():
                for f in files:
                    self.add_button({"label": os.path.splitext(os.path.basename(f))[0][:12], "icon": "",
                                     "tooltip": f, "file": f, "command": ""})
            QtCore.QTimer.singleShot(0, add_files)
        else:
            code = md.text().replace(" ", "\n")
            QtCore.QTimer.singleShot(0, lambda: self.add_code(code))

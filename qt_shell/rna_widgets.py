"""Qt widgets for Blender RNA properties (bool, int, float, vectors, colors, enums, IDs, strings).

Every widget has `refresh()` – it reads the value from Blender without emitting signals.
"""
import math
import os
import re

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import theme
from .bridge import log, tr

AXES = "XYZW"
RGBA = "RGBA"


# ---------------------------------------------------------------- helpers
def rna_prop(data, prop_id):
    try:
        return data.bl_rna.properties[prop_id]
    except Exception:
        return None


_ID_COLLECTIONS = None


def id_collection_for(fixed_type_id):
    """'Material' → bpy.data.materials (by RNA type)."""
    global _ID_COLLECTIONS
    if _ID_COLLECTIONS is None:
        _ID_COLLECTIONS = {}
        for p in bpy.types.BlendData.bl_rna.properties:
            if p.type == "COLLECTION" and p.fixed_type is not None:
                _ID_COLLECTIONS.setdefault(p.fixed_type.identifier, p.identifier)
    attr = _ID_COLLECTIONS.get(fixed_type_id)
    if attr is None:
        # subtypes (e.g. ShaderNodeTree → node_groups)
        try:
            base = getattr(bpy.types, fixed_type_id)
            for ident, a in _ID_COLLECTIONS.items():
                t = getattr(bpy.types, ident, None)
                if t is not None and issubclass(base, t):
                    attr = a
                    break
        except Exception:
            pass
    return getattr(bpy.data, attr, None) if attr else None


def is_id_type(rna_struct):
    try:
        return issubclass(getattr(bpy.types, rna_struct.identifier), bpy.types.ID)
    except Exception:
        return False


_ENUM_ERR = re.compile(r"not found in \((.*)\)")


def enum_items(data, prop_id):
    """[(identifier, name, description)] – also for dynamic enums."""
    p = rna_prop(data, prop_id)
    if p is None:
        return []
    items = [(e.identifier, tr(e.name), e.description) for e in p.enum_items]
    if items:
        return items
    # dynamic enum: read the valid values from the error message
    try:
        setattr(data, prop_id, "__qtshell_invalid__")
    except TypeError as ex:
        m = _ENUM_ERR.search(str(ex))
        if m:
            idents = re.findall(r"'([^']*)'", m.group(1))
            out = []
            for ident in idents:
                try:
                    name = bpy.types.UILayout.enum_item_name(data, prop_id, ident)
                except Exception:
                    name = ""
                out.append((ident, tr(name) or ident.replace("_", " ").title(), ""))
            return out
    except Exception:
        pass
    return []


def lin_to_srgb(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _safe_set(data, prop_id, value, index=-1):
    try:
        if index >= 0:
            arr = getattr(data, prop_id)
            arr[index] = value
        else:
            setattr(data, prop_id, value)
        return True
    except Exception as ex:
        log(f"{prop_id}: {ex}", "ERROR")
        return False


# ---------------------------------------------------------------- draggable spinbox
class DragSpin(QtWidgets.QDoubleSpinBox):
    """Number field like in Blender: dragging left/right changes the value, click = edit as text.

    While dragging the cursor is hidden and kept in place (like Blender), so the drag never
    stops at the edge of the screen. Shift = fine, Ctrl = snap to whole steps,
    Esc during the drag = cancel. Enter / Esc / clicking elsewhere ends text editing.
    """

    def __init__(self, is_int=False, parent=None):
        super().__init__(parent)
        self.is_int = is_int
        self.drag_step = 1.0 if is_int else 0.01
        self._press = None          # global position of the press (anchor for the hidden cursor)
        self._start_val = 0.0
        self._accum = 0.0           # accumulated horizontal movement in pixels
        self._dragging = False
        self._editing = False       # text editing mode (after a click without dragging)
        self.setKeyboardTracking(False)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        le = self.lineEdit()
        le.installEventFilter(self)
        le.setCursor(QtCore.Qt.SizeHorCursor)
        self.editingFinished.connect(self._end_edit)
        if is_int:
            self.setDecimals(0)

    # --- appearance
    def wheelEvent(self, ev):
        if self.hasFocus():
            super().wheelEvent(ev)
        else:
            ev.ignore()  # let the scroll area receive the wheel event

    def _fix_edit(self):
        le = self.lineEdit()
        if le.width() < self.width() - 16:
            le.setGeometry(self.rect().adjusted(3, 2, -3, -2))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fix_edit()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._fix_edit()

    # --- text editing
    def _start_edit(self):
        self._editing = True
        le = self.lineEdit()
        le.setCursor(QtCore.Qt.IBeamCursor)
        self.setFocus(QtCore.Qt.MouseFocusReason)
        le.selectAll()

    def _end_edit(self):
        if not self._editing:
            return
        self._editing = False
        self.lineEdit().setCursor(QtCore.Qt.SizeHorCursor)
        self.lineEdit().deselect()
        if self.hasFocus():
            self.clearFocus()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        if self._editing:
            self._editing = False
            self.lineEdit().setCursor(QtCore.Qt.SizeHorCursor)

    def keyPressEvent(self, ev):
        if self._press is not None and ev.key() == QtCore.Qt.Key_Escape:
            self._cancel_drag()
            return
        if self._editing and ev.key() == QtCore.Qt.Key_Escape:
            self.lineEdit().undo()
            self._editing = False
            self.clearFocus()
            return
        super().keyPressEvent(ev)

    # --- dragging
    def _drag_value(self, mods):
        speed = 0.1 if mods & QtCore.Qt.ShiftModifier else 1.0
        val = self._start_val + self._accum * self.drag_step * speed
        if mods & QtCore.Qt.ControlModifier:
            snap = 1.0 if (self.is_int or self.drag_step >= 0.05) else 0.1
            val = round(val / snap) * snap
        if self.is_int:
            val = round(val)
        return val

    def _finish_drag(self):
        QtWidgets.QApplication.restoreOverrideCursor()
        if self._press is not None:
            QtGui.QCursor.setPos(self._press)
        self._press = None
        self._dragging = False
        self.lineEdit().releaseMouse()
        if self.hasFocus():
            self.clearFocus()

    def _cancel_drag(self):
        was = self._dragging
        start = self._start_val
        self._finish_drag()
        if was:
            self.setValue(start)
            self.editingFinished.emit()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if self._editing:
            return False  # normal text editing in the line edit
        if t == QtCore.QEvent.MouseButtonDblClick:
            self._start_edit()
            return True
        if t == QtCore.QEvent.MouseButtonPress and ev.button() == QtCore.Qt.LeftButton:
            self._press = ev.globalPosition().toPoint()
            self._start_val = self.value()
            self._accum = 0.0
            self._dragging = False
            return True
        if t == QtCore.QEvent.MouseMove and self._press is not None:
            if not (ev.buttons() & QtCore.Qt.LeftButton):
                self._finish_drag()
                return True
            dx = ev.globalPosition().x() - self._press.x()
            if not self._dragging:
                if abs(dx) <= 3:
                    return True
                self._dragging = True
                self.lineEdit().grabMouse()
                QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.BlankCursor)
            if dx:
                self._accum += dx
                QtGui.QCursor.setPos(self._press)   # keep the hidden cursor in place
            self.setValue(self._drag_value(ev.modifiers()))
            return True
        if t == QtCore.QEvent.MouseButtonRelease and ev.button() == QtCore.Qt.LeftButton \
                and self._press is not None:
            dragged = self._dragging
            self._finish_drag()
            if dragged:
                self.editingFinished.emit()
            else:
                self._start_edit()
            return True
        return False


class NoWheelCombo(QtWidgets.QComboBox):
    """Combo box that does not change its value when the panel is scrolled."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(6)

    def wheelEvent(self, ev):
        if self.hasFocus():
            super().wheelEvent(ev)
        else:
            ev.ignore()


# ---------------------------------------------------------------- binding base
class Binding:
    """Connects one widget to an RNA property."""

    def __init__(self, data, prop_id, on_change=None):
        self.data = data
        self.prop_id = prop_id
        self.on_change = on_change
        self.widget = None

    def changed(self):
        if self.on_change:
            self.on_change(self.data, self.prop_id)

    def refresh(self):
        pass

    def alive(self):
        try:
            self.data.bl_rna  # ReferenceError if the data was deleted
            return self.widget is not None
        except Exception:
            return False


class BoolBinding(Binding):
    def __init__(self, data, prop_id, text, toggle, invert, on_change, index=-1):
        super().__init__(data, prop_id, on_change)
        self.index = index
        self.invert = invert
        if toggle == 1:
            w = QtWidgets.QPushButton(text or "")
            w.setCheckable(True)
            w.toggled.connect(self._set)
        else:
            w = QtWidgets.QCheckBox(text or "")
            w.toggled.connect(self._set)
        self.widget = w
        self.refresh()

    def _get(self):
        v = getattr(self.data, self.prop_id)
        if self.index >= 0:
            v = v[self.index]
        return bool(v) != self.invert

    def _set(self, state):
        if _safe_set(self.data, self.prop_id, bool(state) != self.invert, self.index):
            self.changed()

    def refresh(self):
        self.widget.blockSignals(True)
        self.widget.setChecked(self._get())
        self.widget.blockSignals(False)


class NumberBinding(Binding):
    def __init__(self, data, prop_id, rp, prefix, on_change, index=-1):
        super().__init__(data, prop_id, on_change)
        self.index = index
        self.is_int = rp.type == "INT"
        self.angle = rp.subtype == "ANGLE"
        w = DragSpin(self.is_int)
        lo = max(rp.hard_min, -1e12)
        hi = min(rp.hard_max, 1e12)
        if self.angle:
            lo, hi = math.degrees(lo), math.degrees(hi)
            w.setSuffix("°")
        elif rp.subtype in ("DISTANCE", "DISTANCE_CAMERA"):
            w.setSuffix(" m")
        elif rp.subtype == "PERCENTAGE":
            w.setSuffix(" %")
        elif rp.subtype == "PIXEL":
            w.setSuffix(" px")
        elif rp.subtype == "TIME" and not self.is_int:
            w.setSuffix(" s")
        w.setRange(lo, hi)
        if not self.is_int:
            prec = getattr(rp, "precision", 3) or 3
            w.setDecimals(max(2, min(prec, 6)))
            step = (getattr(rp, "step", 3) or 3) / 100.0
            if self.angle:
                step = 1.0
            soft = rp.soft_max - rp.soft_min
            if 0 < soft <= 2:
                step = soft / 200.0
            w.drag_step = step
            w.setSingleStep(step * 10)
        else:
            soft = rp.soft_max - rp.soft_min
            w.drag_step = 0.2 if soft < 1e6 else 0.5
        if prefix:
            w.setPrefix(prefix + ": ")
        w.valueChanged.connect(self._set)
        w.setMinimumWidth(theme.px(60))
        self.widget = w
        self.refresh()

    def _get(self):
        v = getattr(self.data, self.prop_id)
        if self.index >= 0:
            v = v[self.index]
        return math.degrees(v) if self.angle else v

    def _set(self, v):
        if self.angle:
            v = math.radians(v)
        if self.is_int:
            v = int(round(v))
        if _safe_set(self.data, self.prop_id, v, self.index):
            self.changed()

    def refresh(self):
        w = self.widget
        if w._editing or w._dragging:
            return
        self.widget.blockSignals(True)
        self.widget.setValue(self._get())
        self.widget.blockSignals(False)


class ColorBinding(Binding):
    def __init__(self, data, prop_id, rp, on_change):
        super().__init__(data, prop_id, on_change)
        self.size = rp.array_length
        self.linear = rp.subtype == "COLOR"
        w = QtWidgets.QPushButton()
        w.setMinimumHeight(theme.px(20))
        w.clicked.connect(self._pick)
        self.widget = w
        self.refresh()

    def _qcolor(self):
        vals = list(getattr(self.data, self.prop_id))
        rgb = vals[:3]
        if self.linear:
            rgb = [lin_to_srgb(max(0.0, c)) for c in rgb]
        a = vals[3] if self.size > 3 else 1.0
        clamp = lambda c: max(0.0, min(1.0, c))  # noqa: E731
        return QtGui.QColor.fromRgbF(clamp(rgb[0]), clamp(rgb[1]), clamp(rgb[2]), clamp(a))

    def _pick(self):
        if self.size > 3:
            col = QtWidgets.QColorDialog.getColor(self._qcolor(), self.widget, tr("Color"),
                                                  QtWidgets.QColorDialog.ShowAlphaChannel)
        else:
            col = QtWidgets.QColorDialog.getColor(self._qcolor(), self.widget, tr("Color"))
        if not col.isValid():
            return
        rgb = [col.redF(), col.greenF(), col.blueF()]
        if self.linear:
            rgb = [srgb_to_lin(c) for c in rgb]
        vals = rgb + ([col.alphaF()] if self.size > 3 else [])
        if _safe_set(self.data, self.prop_id, vals[: self.size]):
            self.changed()
            self.refresh()

    def refresh(self):
        c = self._qcolor()
        txt = "#000" if c.lightnessF() > 0.55 else "#fff"
        self.widget.setStyleSheet(f"background:{c.name()}; color:{txt}; border:1px solid #111;")


class VectorBinding(Binding):
    def __init__(self, data, prop_id, rp, on_change, align_row=False):
        super().__init__(data, prop_id, on_change)
        self.parts = []
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w) if align_row else QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        labels = RGBA if rp.subtype in ("COLOR", "COLOR_GAMMA") else AXES
        for i in range(rp.array_length):
            if rp.type == "BOOLEAN":
                b = BoolBinding(data, prop_id, labels[i] if i < 4 else str(i), 1, False, on_change, index=i)
                b.widget.setMaximumWidth(theme.px(28))
            else:
                b = NumberBinding(data, prop_id, rp, labels[i] if i < 4 else str(i), on_change, index=i)
            self.parts.append(b)
            lay.addWidget(b.widget)
        if rp.type == "BOOLEAN":
            w.setMaximumWidth(theme.px(30) * rp.array_length)
        self.widget = w

    def refresh(self):
        for p in self.parts:
            p.refresh()


class StringBinding(Binding):
    def __init__(self, data, prop_id, rp, on_change):
        super().__init__(data, prop_id, on_change)
        self.subtype = rp.subtype
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.edit = QtWidgets.QLineEdit()
        self.edit.editingFinished.connect(self._set)
        lay.addWidget(self.edit)
        if rp.subtype in ("FILE_PATH", "DIR_PATH", "FILE_NAME"):
            b = QtWidgets.QToolButton()
            b.setText("…")
            b.clicked.connect(self._browse)
            lay.addWidget(b)
        if getattr(rp, "is_readonly", False):
            self.edit.setReadOnly(True)
        self.widget = w
        self.refresh()

    def _browse(self):
        cur = bpy.path.abspath(self.edit.text()) if self.edit.text() else os.path.expanduser("~")
        if self.subtype == "DIR_PATH":
            path = QtWidgets.QFileDialog.getExistingDirectory(self.widget, "", cur)
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self.widget, "", cur)
        if path:
            self.edit.setText(path)
            self._set()

    def _set(self):
        if self.edit.text() != getattr(self.data, self.prop_id):
            if _safe_set(self.data, self.prop_id, self.edit.text()):
                self.changed()

    def refresh(self):
        if self.edit.hasFocus():
            return
        self.edit.setText(str(getattr(self.data, self.prop_id) or ""))


class EnumBinding(Binding):
    def __init__(self, data, prop_id, rp, expand, on_change):
        super().__init__(data, prop_id, on_change)
        self.flag = rp.is_enum_flag
        self.items = enum_items(data, prop_id)
        self.expand = expand or self.flag
        if self.expand:
            w = QtWidgets.QWidget()
            lay = QtWidgets.QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(1)
            self.buttons = {}
            group = None if self.flag else QtWidgets.QButtonGroup(w)
            for ident, name, desc in self.items:
                b = QtWidgets.QPushButton(name)
                b.setCheckable(True)
                b.setToolTip(desc)
                if group is not None:
                    group.addButton(b)
                b.clicked.connect(lambda _=False, i=ident: self._clicked(i))
                lay.addWidget(b)
                self.buttons[ident] = b
            self._group = group
        else:
            w = NoWheelCombo()
            for ident, name, desc in self.items:
                w.addItem(name, ident)
                w.setItemData(w.count() - 1, desc, QtCore.Qt.ToolTipRole)
            w.activated.connect(self._activated)
        self.widget = w
        self.refresh()

    def _clicked(self, ident):
        if self.flag:
            cur = set(getattr(self.data, self.prop_id))
            cur ^= {ident}
            ok = _safe_set(self.data, self.prop_id, cur)
        else:
            ok = _safe_set(self.data, self.prop_id, ident)
        if ok:
            self.changed()
        self.refresh()

    def _activated(self, idx):
        ident = self.widget.itemData(idx)
        if _safe_set(self.data, self.prop_id, ident):
            self.changed()

    def refresh(self):
        val = getattr(self.data, self.prop_id)
        if self.expand:
            sel = set(val) if self.flag else {val}
            for ident, b in self.buttons.items():
                b.blockSignals(True)
                b.setChecked(ident in sel)
                b.blockSignals(False)
        else:
            w = self.widget
            idx = w.findData(val)
            if idx < 0:  # the dynamic enum changed
                w.blockSignals(True)
                w.clear()
                self.items = enum_items(self.data, self.prop_id)
                for ident, name, _d in self.items:
                    w.addItem(name, ident)
                w.blockSignals(False)
                idx = w.findData(val)
            w.blockSignals(True)
            w.setCurrentIndex(idx)
            w.blockSignals(False)


class IDBinding(Binding):
    def __init__(self, data, prop_id, rp, on_change, search_data=None, search_prop=None):
        super().__init__(data, prop_id, on_change)
        self.search = (search_data, search_prop) if search_data is not None else None
        self.coll = None if self.search else id_collection_for(rp.fixed_type.identifier)
        self.is_string = rp.type == "STRING"
        w = NoWheelCombo()
        w.activated.connect(self._activated)
        self.widget = w
        self._names = None
        self.refresh()

    def _source(self):
        if self.search:
            return list(getattr(self.search[0], self.search[1]))
        return list(self.coll) if self.coll is not None else []

    def _activated(self, idx):
        name = self.widget.itemData(idx)
        if self.is_string:
            value = name or ""
        else:
            value = None
            if name:
                for item in self._source():
                    if getattr(item, "name", None) == name:
                        value = item
                        break
        if _safe_set(self.data, self.prop_id, value):
            self.changed()

    def refresh(self):
        names = [getattr(i, "name", str(i)) for i in self._source()]
        cur = getattr(self.data, self.prop_id)
        cur_name = cur if self.is_string else (cur.name if cur is not None else "")
        w = self.widget
        w.blockSignals(True)
        if names != self._names:
            self._names = names
            w.clear()
            w.addItem("—", "")
            for n in names:
                w.addItem(n, n)
        w.setCurrentIndex(max(0, w.findData(cur_name)))
        w.blockSignals(False)


class ReadOnlyBinding(Binding):
    def __init__(self, data, prop_id, on_change=None):
        super().__init__(data, prop_id, on_change)
        self.widget = QtWidgets.QLabel()
        self.widget.setProperty("dim", True)
        self.refresh()

    def refresh(self):
        try:
            v = getattr(self.data, self.prop_id)
            if hasattr(v, "name"):
                v = v.name
            elif hasattr(v, "__len__") and not isinstance(v, str):
                v = ", ".join(f"{x:.3g}" if isinstance(x, float) else str(x) for x in v)
            elif isinstance(v, float):
                v = f"{v:.4g}"
            self.widget.setText(str(v))
        except Exception:
            self.widget.setText("?")


# ---------------------------------------------------------------- factory
def make_binding(data, prop_id, text=None, expand=False, toggle=-1, index=-1, invert=False,
                 on_change=None, search=None):
    """Returns (binding, label_text). label_text is None if the widget carries its own label."""
    rp = rna_prop(data, prop_id)
    if rp is None:
        return None, None
    name = tr(rp.name) if text is None else text
    t = rp.type
    if search is not None:
        return IDBinding(data, prop_id, rp, on_change, *search), name
    if rp.is_readonly and t != "POINTER":
        return ReadOnlyBinding(data, prop_id), name
    arr = getattr(rp, "array_length", 0) if t in ("BOOLEAN", "INT", "FLOAT") else 0
    if arr and getattr(rp, "array_dimensions", (arr, 0, 0))[1] not in (0,):
        return ReadOnlyBinding(data, prop_id), name  # matrix
    if t == "BOOLEAN":
        if arr and index < 0:
            return VectorBinding(data, prop_id, rp, on_change, align_row=True), name
        return BoolBinding(data, prop_id, None, toggle, invert, on_change, index), name
    if t in ("INT", "FLOAT"):
        if arr and index < 0:
            if rp.subtype in ("COLOR", "COLOR_GAMMA"):
                return ColorBinding(data, prop_id, rp, on_change), name
            return VectorBinding(data, prop_id, rp, on_change), name
        return NumberBinding(data, prop_id, rp, None, on_change, index), name
    if t == "STRING":
        return StringBinding(data, prop_id, rp, on_change), name
    if t == "ENUM":
        return EnumBinding(data, prop_id, rp, expand, on_change), name
    if t == "POINTER":
        if rp.fixed_type is not None and is_id_type(rp.fixed_type) and not rp.is_readonly:
            return IDBinding(data, prop_id, rp, on_change), name
        return ReadOnlyBinding(data, prop_id), name
    return ReadOnlyBinding(data, prop_id), name


def labeled_row(label, widget, split=True):
    """A 'label | widget' row like in Blender with use_property_split."""
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    lab = QtWidgets.QLabel(label or "")
    lab.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignTop if split else QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
    lab.setContentsMargins(0, 3, 0, 0)
    lay.addWidget(lab, 2 if split else 0)
    lay.addWidget(widget, 3 if split else 1)
    return w


# properties we don't show in the generic form
_SKIP = {"rna_type", "name", "type", "is_override_data", "is_active", "persistent_uid",
         "execution_time", "is_valid", "show_expanded", "show_in_editmode", "show_on_cage",
         "show_viewport", "show_render", "use_apply_on_spline", "is_override_data_editable",
         "use_pin_to_last", "is_proxy_local", "active", "error_location", "error_rotation",
         "influence"}


def rna_form(data, on_change=None, skip=(), only=None):
    """Generic form for any RNA struct (for modifiers, constraints, operators…)."""
    w = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(4, 4, 4, 4)
    lay.setSpacing(3)
    bindings = []
    skipset = _SKIP | set(skip)
    props = list(data.bl_rna.properties)
    if only:
        order = {k: i for i, k in enumerate(only)}
        props = sorted((p for p in props if p.identifier in order), key=lambda p: order[p.identifier])
    for p in props:
        if (p.identifier in skipset or p.identifier.startswith("open_")) and not only:
            continue
        if getattr(p, "is_hidden", False):
            continue
        if p.type == "COLLECTION":
            continue
        if p.type == "POINTER" and (p.fixed_type is None or not is_id_type(p.fixed_type)):
            continue
        if p.is_readonly and not only:
            continue
        b, label = make_binding(data, p.identifier, on_change=on_change)
        if b is None:
            continue
        bindings.append(b)
        if isinstance(b, BoolBinding):
            b.widget.setText(label)
            lay.addWidget(labeled_row("", b.widget))
        else:
            lay.addWidget(labeled_row(label, b.widget))
    return w, bindings

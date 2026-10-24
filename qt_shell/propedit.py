"""Edit Property (wm.properties_edit) – Blender's custom property dialog as a Qt dialog.

Blender's operator only works when invoked (its invoke stores the old name and fills the fields; a direct
execution is refused), and its dialog is drawn by Blender – so Qt Shell shows its own dialog and runs the
operator's own Python code (fill from the property, check, execute) on a stand-in object that carries the
operator's settings. Renaming, changing the type, default / min / max / soft limits / step / precision /
subtype, description, the Python value and Library Overridable work like in Blender, including the
F-Curve / driver path fixes Blender does on a rename.
"""
import types

import bpy
from PySide6 import QtCore, QtWidgets

from . import bridge, theme

TYPES = [("FLOAT", "Float"), ("FLOAT_ARRAY", "Float Array"), ("INT", "Integer"), ("INT_ARRAY", "Integer Array"),
         ("BOOL", "Boolean"), ("BOOL_ARRAY", "Boolean Array"), ("STRING", "String"),
         ("DATA_BLOCK", "Data-Block"), ("PYTHON", "Python")]
SUBTYPES = {
    "FLOAT": [("NONE", "Plain Data"), ("PIXEL", "Pixel"), ("PERCENTAGE", "Percentage"), ("FACTOR", "Factor"),
              ("ANGLE", "Angle"), ("TIME_ABSOLUTE", "Time"), ("DISTANCE", "Distance"), ("POWER", "Power"),
              ("TEMPERATURE", "Temperature")],
    "FLOAT_ARRAY": [("NONE", "Plain Data"), ("COLOR", "Linear Color"), ("COLOR_GAMMA", "Gamma-Corrected Color"),
                    ("TRANSLATION", "Translation"), ("DIRECTION", "Direction"), ("VELOCITY", "Velocity"),
                    ("ACCELERATION", "Acceleration"), ("EULER", "Euler Angles"), ("QUATERNION", "Quaternion"),
                    ("AXISANGLE", "Axis-Angle"), ("XYZ", "XYZ")],
}


def _op_class():
    return getattr(bpy.types, "WM_OT_properties_edit", None)


class _OpProxy:
    """Carries the operator's settings; the operator class's methods run on it as if it were the operator."""

    def __init__(self, cls):
        self._reports = []
        self.enum_items = None
        props = list(cls.bl_rna.properties)
        try:                                          # the operator's full settings (class RNA may lack some)
            props = list(bpy.ops.wm.properties_edit.get_rna_type().properties) + props
        except Exception:
            pass
        for p in props:
            if p.identifier == "rna_type" or hasattr(self, p.identifier):
                continue
            default = getattr(p, "default_array", None) if getattr(p, "is_array", False) else \
                getattr(p, "default", None)
            if getattr(p, "is_array", False):
                default = list(default)
            setattr(self, p.identifier, default if default is not None else "")
        # settings that are only class annotations (not all of them show up in bl_rna.properties)
        for klass in cls.__mro__:
            for name, ann in getattr(klass, "__annotations__", {}).items():
                if hasattr(self, name) or not hasattr(ann, "keywords"):
                    continue
                kw = ann.keywords
                fn = getattr(getattr(ann, "function", None), "__name__", "")
                default = kw.get("default")
                if default is None:
                    default = {"IntProperty": 0, "FloatProperty": 0.0, "BoolProperty": False}.get(fn, "")
                    if fn.endswith("VectorProperty"):
                        base = 0.0 if fn.startswith("Float") else (False if fn.startswith("Bool") else 0)
                        default = [base] * int(kw.get("size", 3) if isinstance(kw.get("size", 3), int) else 3)
                elif fn.endswith("VectorProperty"):
                    default = list(default)
                setattr(self, name, default)
        for klass in reversed(cls.__mro__):           # also helpers of base classes
            if klass.__module__ in ("builtins",) or klass.__module__.startswith("bpy"):
                continue
            for name, fn in vars(klass).items():
                if isinstance(fn, staticmethod):
                    setattr(self, name, fn.__func__)
                elif isinstance(fn, classmethod):
                    setattr(self, name, types.MethodType(fn.__func__, cls))
                elif isinstance(fn, types.FunctionType):
                    setattr(self, name, types.MethodType(fn, self))

    def report(self, kind, message):
        self._reports.append((set(kind), message))


def _helper(cls, name):
    """A function the operator uses – a method of its class or a function of its module (bl_operators.wm)."""
    import sys
    fn = getattr(cls, name, None)
    if fn is None:
        fn = getattr(sys.modules.get(cls.__module__), name, None)
    if fn is None:
        raise RuntimeError(f"Blender's Edit Property has no {name}()")
    return fn


def _resolve(data_path):
    try:
        return eval("bpy.context." + data_path) if data_path else None
    except Exception:
        return None


def edit_property(parent, props, ctx=None):
    """Opens the dialog for {data_path, property_name}; True when handled (also when cancelled)."""
    cls = _op_class()
    if cls is None or not props.get("data_path"):
        return False
    try:
        dlg = PropertyEditDialog(parent, cls, props["data_path"], props.get("property_name", ""), ctx)
    except Exception as ex:
        bridge.log(f"Edit Property: {ex}", "ERROR")
        return True                 # Blender's operator can't run without its own dialog either
    dlg.exec()
    return True


class PropertyEditDialog(QtWidgets.QDialog):
    def __init__(self, parent, cls, data_path, name, ctx=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Property")
        self.cls = cls
        self.ctx = dict(ctx or {})
        self.data_path = data_path
        p = self.p = _OpProxy(cls)
        p.data_path = data_path
        p.property_name = name
        with bridge.blender_context(**self.ctx):
            item = _resolve(data_path)
            if item is None:
                raise RuntimeError(f"Data path not found: {data_path}")
            if name not in item.keys():
                raise RuntimeError(f"No custom property '{name}'")
            # what the operator's invoke does (without its Blender dialog)
            p._old_prop_name = [name]
            old_type = _helper(cls, "get_property_type")(item, name)
            p.property_type = old_type
            p.last_property_type = old_type
            try:
                p.eval_string = _helper(cls, "convert_custom_property_to_string")(item, name)
            except Exception:
                try:
                    p.eval_string = repr(item[name])
                except Exception:
                    p.eval_string = ""
            if old_type != "PYTHON":
                p._fill_old_ui_data(item, name)
        lay = QtWidgets.QVBoxLayout(self)
        self.form = QtWidgets.QFormLayout()
        self.form.setLabelAlignment(QtCore.Qt.AlignRight)
        lay.addLayout(self.form)
        self.msg = QtWidgets.QLabel(self)
        self.msg.setStyleSheet("color: #ff7070;")
        self.msg.setWordWrap(True)
        self.msg.hide()
        lay.addWidget(self.msg)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.setMinimumWidth(theme.px(380))
        self._build()

    # --- widgets
    def _spin_f(self, value, lo=-1e9, hi=1e9, dec=None):
        s = QtWidgets.QDoubleSpinBox(self)
        s.setRange(lo, hi)
        s.setDecimals(dec if dec is not None else max(3, int(getattr(self.p, "precision", 3) or 3)))
        s.setValue(float(value))
        return s

    def _spin_i(self, value, lo=-2 ** 31 + 1, hi=2 ** 31 - 1):
        s = QtWidgets.QSpinBox(self)
        s.setRange(lo, hi)
        s.setValue(int(value))
        return s

    def _clear(self):
        while self.form.rowCount():
            self.form.removeRow(0)

    def _build(self):
        """Rows like Blender's dialog for the current type."""
        self._clear()
        p = self.p
        t = p.property_type
        self.w = {}
        tc = QtWidgets.QComboBox(self)
        for ident, label in TYPES:
            tc.addItem(label, ident)
        tc.setCurrentIndex(max(0, tc.findData(t)))
        tc.activated.connect(lambda _i: self._type_changed(tc.currentData()))
        self.form.addRow("Type", tc)
        ne = QtWidgets.QLineEdit(str(p.property_name), self)
        ne.setMaxLength(63)
        self.w["property_name"] = ne
        self.form.addRow("Property Name", ne)
        is_array = t.endswith("_ARRAY")
        if t in ("FLOAT", "FLOAT_ARRAY", "INT", "INT_ARRAY", "BOOL", "BOOL_ARRAY"):
            if is_array:
                al = self._spin_i(p.array_length, 1, 32)
                al.valueChanged.connect(lambda v: (self._collect(), setattr(self.p, "array_length", int(v)),
                                                   self._build()))
                self.w["array_length"] = al
                self.form.addRow("Array Length", al)
            n = int(p.array_length) if is_array else 1
            kind = t.split("_")[0]
            defaults = []
            for i in range(n):
                if kind == "FLOAT":
                    d = self._spin_f(p.default_float[i])
                elif kind == "INT":
                    d = self._spin_i(p.default_int[i])
                else:
                    d = QtWidgets.QCheckBox(self)
                    d.setChecked(bool(p.default_bool[i]))
                defaults.append(d)
                self.form.addRow("Default" if i == 0 else "", d)
            self.w["defaults"] = defaults
            if kind in ("FLOAT", "INT"):
                sfx = "float" if kind == "FLOAT" else "int"
                mk = self._spin_f if kind == "FLOAT" else self._spin_i
                for attr, label in (("min", "Min"), ("max", "Max")):
                    s = mk(getattr(p, f"{attr}_{sfx}"))
                    self.w[f"{attr}_{sfx}"] = s
                    self.form.addRow(label, s)
                soft = QtWidgets.QCheckBox("Soft Limits", self)
                soft.setChecked(bool(p.use_soft_limits))
                self.w["use_soft_limits"] = soft
                self.form.addRow("", soft)
                for attr, label in (("soft_min", "Soft Min"), ("soft_max", "Max")):
                    s = mk(getattr(p, f"{attr}_{sfx}"))
                    s.setEnabled(soft.isChecked())
                    soft.toggled.connect(s.setEnabled)
                    self.w[f"{attr}_{sfx}"] = s
                    self.form.addRow(label, s)
                if kind == "FLOAT":
                    if hasattr(p, "step_float"):
                        st = self._spin_f(p.step_float, 0.001, 1e6)
                        self.w["step_float"] = st
                        self.form.addRow("Step", st)
                    if hasattr(p, "precision"):
                        pr = self._spin_i(p.precision, 0, 8)
                        self.w["precision"] = pr
                        self.form.addRow("Precision", pr)
                    sc = QtWidgets.QComboBox(self)
                    for ident, label in SUBTYPES.get(t, [("NONE", "Plain Data")]):
                        sc.addItem(label, ident)
                    sc.setCurrentIndex(max(0, sc.findData(p.subtype or "NONE")))
                    self.w["subtype"] = sc
                    self.form.addRow("Subtype", sc)
                elif hasattr(p, "step_int"):               # not in every Blender version
                    st = self._spin_i(p.step_int, 1, 1000000)
                    self.w["step_int"] = st
                    self.form.addRow("Step", st)
        elif t == "STRING":
            ds = QtWidgets.QLineEdit(str(p.default_string or ""), self)
            self.w["default_string"] = ds
            self.form.addRow("Default", ds)
        elif t == "DATA_BLOCK":
            ic = QtWidgets.QComboBox(self)
            for e in self.cls.bl_rna.properties["id_type"].enum_items:
                ic.addItem(e.name, e.identifier)
            ic.setCurrentIndex(max(0, ic.findData(p.id_type)))
            self.w["id_type"] = ic
            self.form.addRow("ID Type", ic)
        if t == "PYTHON":
            ev = QtWidgets.QLineEdit(str(p.eval_string or ""), self)
            self.w["eval_string"] = ev
            self.form.addRow("Value", ev)
        else:
            de = QtWidgets.QLineEdit(str(p.description or ""), self)
            self.w["description"] = de
            self.form.addRow("Description", de)
        if not hasattr(p, "is_overridable_library"):
            self.adjustSize()
            return
        ov = QtWidgets.QCheckBox("Library Overridable", self)
        ov.setChecked(bool(p.is_overridable_library))
        self.w["is_overridable_library"] = ov
        self.form.addRow("", ov)
        self.adjustSize()

    def _collect(self):
        """Dialog → the stand-in's settings."""
        p = self.p
        w = self.w
        p.property_name = w["property_name"].text()
        t = p.property_type
        if "array_length" in w:
            p.array_length = int(w["array_length"].value())
        if "defaults" in w:
            kind = t.split("_")[0]
            key = {"FLOAT": "default_float", "INT": "default_int", "BOOL": "default_bool"}[kind]
            arr = list(getattr(p, key))
            for i, d in enumerate(w["defaults"]):
                arr[i] = d.isChecked() if kind == "BOOL" else d.value()
            setattr(p, key, arr)
        for k in ("min_float", "max_float", "soft_min_float", "soft_max_float", "step_float", "min_int", "max_int",
                  "soft_min_int", "soft_max_int", "step_int", "precision"):
            if k in w:
                setattr(p, k, w[k].value())
        if "use_soft_limits" in w:
            p.use_soft_limits = w["use_soft_limits"].isChecked()
        if "subtype" in w:
            p.subtype = w["subtype"].currentData()
        for k in ("default_string", "eval_string", "description"):
            if k in w:
                setattr(p, k, w[k].text())
        if "id_type" in w:
            p.id_type = w["id_type"].currentData()
        if "is_overridable_library" in w:
            p.is_overridable_library = w["is_overridable_library"].isChecked()

    def _type_changed(self, t):
        self._collect()
        self.p.property_type = t
        self.p.subtype = "NONE"
        try:
            with bridge.blender_context(**self.ctx):
                self.p.check(bpy.context)          # Blender converts min / max / defaults to the new type
        except Exception as ex:
            bridge.log(f"Edit Property (type): {ex}", "WARNING")
        self._build()

    def _ok(self):
        self._collect()
        p = self.p
        name = p.property_name.strip()
        if not name:
            self._error("The property needs a name.")
            return
        p.property_name = name
        try:
            with bridge.blender_context(**self.ctx):
                p.check(bpy.context)
                res = p.execute(bpy.context)
        except Exception as ex:
            self._error(str(ex))
            return
        errs = [m for kind, m in p._reports if kind & {"ERROR", "WARNING"}]
        if "FINISHED" not in res:
            self._error("; ".join(errs) or "The property could not be changed.")
            return
        bridge.undo_push("Edit Property")
        self.accept()

    def _error(self, text):
        self.msg.setText(text)
        self.msg.show()

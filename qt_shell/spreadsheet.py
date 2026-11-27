"""Spreadsheet – Blender's Spreadsheet editor and Maya's Attribute Spread Sheet / Component Editor in one dock.

Two modes (toolbar):

* **Geometry** (Blender's Spreadsheet + Maya's Component Editor): the active object's geometry – Mesh (Vertex,
  Edge, Face, Face Corner), Curves (Control Point, Spline), Point Cloud and Instances – picked in the data set
  list on the left with the element counts. Columns = attributes (vectors split into X / Y / Z like Maya),
  vertex groups (weights, like Maya's Component Editor) and a few computed columns (normals, face corners).
  *Evaluated* shows the result of the modifiers / Geometry Nodes (`Object.evaluated_geometry()`, read-only),
  *Original* the object's own data – editable, also in Edit Mode. *Selected Only* (Edit Mode) shows only the
  selected elements, row filters (left, like Blender) keep the rows that match.
* **Objects** (Maya's Attribute Spread Sheet): the selected objects (Pose Mode: the selected bones) as rows,
  attribute tabs Keyable / Translate / Rotate / Scale / Transform / Render / Display / Custom / All. Keyed
  cells are red, driven ones purple, locked ones grey (like Maya).

Both: click a header to sort, select cells and type a value → it goes into every selected cell (Maya);
`+=1`, `-=0.5`, `*=2`, `/=2` change the values relatively, plain expressions (`2*pi`) work too.
Copy / Paste (tab separated, Excel compatible), Export CSV, column filter, Python tooltips per cell.

Never keeps bpy references between events: everything is read into numpy arrays on refresh, writes look the
data up again by name.
"""
import csv
import math
import re
import time
import traceback

import bpy
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, hscroll, keymap, pytips, theme

SS_PY = "import qt_shell; ss = qt_shell.api.spreadsheet(); ss."
SETTINGS = "spreadsheet/"

MODES = ("GEOMETRY", "OBJECTS")
COMPONENTS = {               # component → (label, [(domain, label)])
    "MESH": ("Mesh", [("POINT", "Vertex"), ("EDGE", "Edge"), ("FACE", "Face"), ("CORNER", "Face Corner")]),
    "CURVES": ("Curves", [("POINT", "Control Point"), ("CURVE", "Spline")]),
    "POINTCLOUD": ("Point Cloud", [("POINT", "Point")]),
    "INSTANCES": ("Instances", [("INSTANCE", "Instance")]),
}
COMPONENT_ICONS = {"MESH": "MESH_DATA", "CURVES": "CURVES_DATA", "POINTCLOUD": "POINTCLOUD_DATA",
                   "INSTANCES": "OUTLINER_OB_GROUP_INSTANCE"}
DOMAIN_ICONS = {"POINT": "VERTEXSEL", "EDGE": "EDGESEL", "FACE": "FACESEL", "CORNER": "FACE_CORNER",
                "CURVE": "CURVE_PATH", "INSTANCE": "EMPTY_AXIS"}
TABS = ("Keyable", "Translate", "Rotate", "Scale", "Transform", "Render", "Display", "Custom", "All")
OPS = ("=", "≠", ">", "<", "≥", "≤", "contains")
KEYED_BG = QtGui.QColor("#7a3436")       # Maya: keyed channels red
DRIVEN_BG = QtGui.QColor("#5a3d78")      # driven: purple
LOCKED_FG = QtGui.QColor("#7c7c7c")
COMPUTED_FG = QtGui.QColor("#9fb4c8")
AXES = {2: "XY", 3: "XYZ", 4: "XYZW"}
_EVAL_NAMES = {"pi": math.pi, "e": math.e, "tau": math.tau, "sqrt": math.sqrt, "sin": math.sin,
               "cos": math.cos, "tan": math.tan, "radians": math.radians, "degrees": math.degrees,
               "abs": abs, "min": min, "max": max, "round": round, "floor": math.floor, "ceil": math.ceil}


def _settings():
    return QtCore.QSettings("QtShell", "QtShell")


def _setting(key, default):
    v = _settings().value(SETTINGS + key, default)
    if isinstance(default, bool):
        return str(v).lower() in ("true", "1")
    if isinstance(default, int):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default
    return v if v is not None else default


def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


# ================================================================== columns
class Column:
    """One spreadsheet column. values: numpy array / list over the *source* rows (all elements, unfiltered).
    kind: 'f' float, 'i' int, 'b' bool, 's' string, 'e' enum. write(rows, values) writes source rows.
    state: optional list per row – 'key' / 'drv' / 'lock' (Objects mode cell colours)."""

    def __init__(self, name, values, kind="f", write=None, python=None, tip="", computed=False, state=None,
                 enum_items=None, editable=None):
        self.name = name
        self.values = values
        self.kind = kind
        self.write = write
        self.python = python
        self.tip = tip
        self.computed = computed
        self.state = state
        self.enum_items = enum_items or []
        self.editable = (write is not None) if editable is None else editable

    def value(self, r):
        v = self.values[r]
        return v.item() if hasattr(v, "item") else v

    def text(self, r, decimals):
        v = self.value(r)
        if v is None:
            return ""
        k = self.kind
        if k == "f":
            try:
                return f"{v:.{decimals}f}"
            except (TypeError, ValueError):
                return str(v)
        if k == "b":
            return ""
        if k == "e":
            for ident, label in self.enum_items:
                if ident == v:
                    return label
        return str(v)

    def sort_key(self):
        v = self.values
        if isinstance(v, np.ndarray) and v.dtype != object:
            return v
        if self.kind in ("f", "i", "b"):
            return np.array([(-math.inf if x is None else float(x)) for x in v])
        return np.array(["" if x is None else str(x).lower() for x in v])


def _rna_elem_prop(attr):
    """(property name, component count) of an attribute's data elements (vector / color / value)."""
    try:
        fixed = attr.bl_rna.properties["data"].fixed_type
        props = {p.identifier: p for p in fixed.properties if p.identifier != "rna_type"}
    except Exception:
        props = {}
    for name in ("vector", "color", "value"):
        p = props.get(name)
        if p is not None:
            n = 1
            try:
                dims = [d for d in p.array_dimensions if d]
                n = int(np.prod(dims)) if dims else max(1, p.array_length)
            except Exception:
                n = max(1, getattr(p, "array_length", 0) or 1)
            return name, n, p.type
    return None, 0, None


def read_attribute(attr, size):
    """Values of an attribute as an (size, n) numpy array (strings: list), with its RNA element prop name."""
    prop, n, ptype = _rna_elem_prop(attr)
    if prop is None or size == 0:
        return None, prop, n
    if ptype == "STRING":
        return [d.value for d in attr.data], prop, 1
    dtype = {"FLOAT": np.float32, "INT": np.int32, "BOOLEAN": bool}.get(ptype, np.float32)
    arr = np.zeros(size * n, dtype=dtype)
    attr.data.foreach_get(prop, arr)
    return arr.reshape(size, n), prop, n


def _labels_for(attr_name, data_type, domain, n):
    if data_type in ("FLOAT_COLOR", "BYTE_COLOR"):
        return "RGBA"[:n]
    if data_type == "QUATERNION":
        return "WXYZ"
    if data_type == "FLOAT2" and domain == "CORNER":
        return "UV"
    if data_type in ("INT32_2D", "INT16_2D"):
        return "01"
    return AXES.get(n, "".join(str(i) for i in range(n)))


# ================================================================== data sources
def _domain_size(data, comp, domain):
    try:
        if comp == "INSTANCES":
            return len(data.points)
        if comp == "MESH":
            return {"POINT": len(data.vertices), "EDGE": len(data.edges), "FACE": len(data.polygons),
                    "CORNER": len(data.loops)}[domain]
        return int(data.attributes.domain_size(domain))
    except Exception:
        return 0


def _noop():
    pass


SCRATCH = "~Qt Shell Spreadsheet"


def _scratch_mesh():
    """A mesh no object uses – the edit BMesh is copied into it for reading. Object.update_from_editmode()
    would tag the edited mesh, the depsgraph update refreshes the Spreadsheet, which reads again … (endless).
    An unused mesh is in no depsgraph, so writing it causes no update; with no users it is not saved."""
    me = bpy.data.meshes.get(SCRATCH)
    if me is None or me.users or me.library is not None:
        me = bpy.data.meshes.new(SCRATCH)
    me.use_fake_user = False
    return me


def geometry_components(ob, evaluated):
    """(cleanup, [(component, data)]) of an object – evaluated: the GeometrySet's parts (they live while the
    set does – call cleanup() after reading), original: the object's own data. In Edit Mode the mesh's
    attributes point to the edit BMesh and have no data: the edit mesh is written back
    copied into a scratch mesh (`_scratch_mesh`) and read from there."""
    if ob is None:
        return _noop, []
    out = []
    if evaluated:
        try:
            dg = bpy.context.evaluated_depsgraph_get()
            gs = ob.evaluated_get(dg).evaluated_geometry()
        except Exception:
            return _noop, []
        for comp, getter in (("MESH", lambda: gs.mesh), ("CURVES", lambda: gs.curves),
                             ("POINTCLOUD", lambda: gs.pointcloud), ("INSTANCES", gs.instances_pointcloud)):
            try:
                d = getter()
            except Exception:
                d = None
            if d is not None:
                out.append((comp, d))
        return (lambda gs=gs: None), out
    data = getattr(ob, "data", None)
    if ob.type == "MESH" and data is not None:
        if ob.mode == "EDIT":
            try:
                import bmesh
                me = _scratch_mesh()
                bridge.mute_empty_updates(0.5)
                bmesh.from_edit_mesh(data).to_mesh(me)
            except Exception:
                bridge.log(f"Spreadsheet: {traceback.format_exc()}", "WARNING")
                return _noop, []
            return _noop, [("MESH", me)]
        out.append(("MESH", data))
    elif ob.type == "CURVES" and data is not None:
        out.append(("CURVES", data))
    elif ob.type == "POINTCLOUD" and data is not None:
        out.append(("POINTCLOUD", data))
    return _noop, out


def _data_python(ob_name, comp, evaluated):
    o = f"bpy.data.objects[{_q(ob_name)}]"
    if not evaluated:
        return f"{o}.data"
    gs = f"{o}.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()"
    return {"MESH": f"{gs}.mesh", "CURVES": f"{gs}.curves", "POINTCLOUD": f"{gs}.pointcloud",
            "INSTANCES": f"{gs}.instances_pointcloud()"}[comp]


# ================================================================== writes (geometry, original data)
# attribute type → BMesh layer collection (Edit Mode writes go into the edit BMesh)
BM_LAYER = {"FLOAT": "float", "INT": "int", "FLOAT_VECTOR": "float_vector", "FLOAT_COLOR": "float_color",
            "STRING": "string", "BOOLEAN": "bool"}


def bm_writable(ob, name, data_type, domain):
    """Can this attribute be written in Edit Mode (through the edit BMesh)?"""
    if name == "position":
        return True
    if data_type == "FLOAT2" and domain == "CORNER":
        try:
            return name in ob.data.uv_layers
        except Exception:
            return False
    return data_type in BM_LAYER and domain in ("POINT", "EDGE", "FACE", "CORNER")


def _bm_write(ob, attr_name, data_type, domain, n, c, rows, vals):
    import bmesh
    me = ob.data
    bm = bmesh.from_edit_mesh(me)
    if attr_name == "position":
        bm.verts.ensure_lookup_table()
        for r, v in zip(rows, vals):
            bm.verts[int(r)].co[c] = float(v)
        bmesh.update_edit_mesh(me, loop_triangles=True, destructive=False)
        return
    if domain == "CORNER":
        layers = bm.loops.layers
        elems = [lp for f in bm.faces for lp in f.loops]
    else:
        seq = {"POINT": bm.verts, "EDGE": bm.edges, "FACE": bm.faces}[domain]
        seq.ensure_lookup_table()
        layers, elems = seq.layers, seq
    if data_type == "FLOAT2":
        layer = layers.uv.get(attr_name)
        if layer is None:
            raise ValueError(f"no UV map {attr_name!r} in the edit mesh")
        for r, v in zip(rows, vals):
            elems[int(r)][layer].uv[c] = float(v)
    else:
        layer = getattr(layers, BM_LAYER[data_type]).get(attr_name)
        if layer is None:
            raise ValueError(f"no layer {attr_name!r} in the edit mesh")
        for r, v in zip(rows, vals):
            e = elems[int(r)]
            if n > 1:
                cur = list(e[layer])
                cur[c] = float(v)
                e[layer] = cur
            elif data_type == "STRING":
                e[layer] = str(v).encode("utf-8")
            elif data_type == "BOOLEAN":
                e[layer] = bool(v)
            elif data_type == "INT":
                e[layer] = int(v)
            else:
                e[layer] = float(v)
    bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)


def _attr_writer(ob_name, comp, attr_name, prop, n, c, kind, data_type="", domain=""):
    def write(rows, vals):
        ob = bpy.data.objects.get(ob_name)
        if ob is None:
            return
        if ob.mode == "EDIT" and ob.type == "MESH":
            if not bm_writable(ob, attr_name, data_type, domain):
                raise ValueError(f"{attr_name} can't be edited in Edit Mode")
            _bm_write(ob, attr_name, data_type, domain, n, c, rows, vals)
            return
        data = ob.data
        attr = data.attributes.get(attr_name)
        if attr is None:
            return
        size = _domain_size(data, comp, attr.domain)
        if kind == "s":
            for r, v in zip(rows, vals):
                attr.data[int(r)].value = str(v)
        else:
            dtype = {"f": np.float32, "i": np.int32, "b": bool}[kind]
            arr = np.zeros(size * n, dtype=dtype)
            attr.data.foreach_get(prop, arr)
            arr = arr.reshape(size, n)
            arr[np.asarray(rows, dtype=np.int64), c] = np.asarray(vals).astype(dtype)
            attr.data.foreach_set(prop, arr.ravel())
        data.update()
    return write


def _weight_writer(ob_name, group_name):
    def write(rows, vals):
        ob = bpy.data.objects.get(ob_name)
        if ob is None:
            return
        vg = ob.vertex_groups.get(group_name)
        if vg is None:
            return
        if ob.mode == "EDIT":
            import bmesh
            bm = bmesh.from_edit_mesh(ob.data)
            dl = bm.verts.layers.deform.verify()
            bm.verts.ensure_lookup_table()
            for r, v in zip(rows, vals):
                bm.verts[int(r)][dl][vg.index] = max(0.0, min(1.0, float(v)))
            bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
            return
        for r, v in zip(rows, vals):
            vg.add([int(r)], max(0.0, min(1.0, float(v))), "REPLACE")
        ob.data.update()
    return write


def _vertex_weights(me, vg_index, n):
    w = np.zeros(n, dtype=np.float32)
    if n > 300000:
        return None
    for v in me.vertices:
        for g in v.groups:
            if g.group == vg_index:
                w[v.index] = g.weight
                break
    return w


# ================================================================== geometry columns
def geometry_columns(ob, comp, data, domain, evaluated, internal=False, extras=True):
    """Columns of one domain. Returns (columns, size)."""
    size = _domain_size(data, comp, domain)
    cols = []
    ob_name = ob.name
    base = _data_python(ob_name, comp, evaluated)
    attr_domain = "POINT" if comp == "INSTANCES" else domain
    special = {".edge_verts": ("vertices", "Vertex indices of the edge"),
               ".corner_vert": ("vertex", "Vertex of the face corner"),
               ".corner_edge": ("edge", "Edge after the face corner"),
               ".reference_index": ("instance", "Index of the instanced geometry")}
    attrs = []
    try:
        attrs = [a for a in data.attributes if a.domain == attr_domain]
    except Exception:
        pass
    attrs.sort(key=lambda a: (a.name != "position", 0))
    refs = None
    for a in attrs:
        name = a.name
        spec = special.get(name)
        if name.startswith(".") and spec is None and not internal:
            continue
        if comp == "INSTANCES" and name.startswith(".") and name != ".reference_index" and not internal:
            continue
        try:
            arr, prop, n = read_attribute(a, size)
        except Exception:
            bridge.log(f"Spreadsheet: {name}: {traceback.format_exc()}", "WARNING")
            continue
        if arr is None or prop is None:
            continue
        label = spec[0] if spec else name
        tip = spec[1] if spec else f"{name} · {a.data_type} · {a.domain}"
        apath = f"{base}.attributes[{_q(name)}].data"
        if a.data_type == "FLOAT4X4" and n == 16:
            cols += _matrix_columns(label, arr, apath, tip)
            continue
        if comp == "INSTANCES" and name == ".reference_index":
            if refs is None:
                try:
                    refs = [getattr(r, "name", "") or str(r) for r in _instance_refs(ob)]
                except Exception:
                    refs = []
            idx = arr[:, 0]
            names = [refs[i] if 0 <= i < len(refs) else str(i) for i in idx.tolist()]
            cols.append(Column(label, names, "s", tip=tip,
                               python=lambda r, p=apath: f"{p}[{r}].value"))
            continue
        kind = "s" if isinstance(arr, list) else ("b" if arr.dtype == bool else
                                                   ("i" if arr.dtype.kind == "i" else "f"))
        editable = not evaluated and not name.startswith(".") and kind in "fibs"
        if editable and comp == "MESH" and ob.mode == "EDIT" and ob.type == "MESH":
            editable = bm_writable(ob, name, a.data_type, a.domain)
        if isinstance(arr, list):
            w = _attr_writer(ob_name, comp, name, prop, 1, 0, "s", a.data_type, a.domain) if editable else None
            cols.append(Column(label, arr, "s", write=w, tip=tip,
                               python=lambda r, p=apath, pr=prop: f"{p}[{r}].{pr}"))
            continue
        axes = _labels_for(name, a.data_type, a.domain, n) if n > 1 else ""
        for c in range(n):
            cname = f"{label} {axes[c]}" if n > 1 else label
            w = _attr_writer(ob_name, comp, name, prop, n, c, kind, a.data_type, a.domain) if editable else None
            py = (lambda r, p=apath, pr=prop, c=c: f"{p}[{r}].{pr}[{c}]") if n > 1 else \
                (lambda r, p=apath, pr=prop: f"{p}[{r}].{pr}")
            cols.append(Column(cname, arr[:, c], kind, write=w, tip=tip, python=py))
    # vertex groups (Maya's Component Editor: weights) – original meshes
    if comp == "MESH" and domain == "POINT" and not evaluated and ob.type == "MESH" and ob.vertex_groups:
        for vg in ob.vertex_groups:
            w = _vertex_weights(data, vg.index, size)
            if w is None:
                break
            cols.append(Column(vg.name, w, "f", write=_weight_writer(ob_name, vg.name),
                               tip=f"Vertex group weight · {vg.name}",
                               python=lambda r, o=ob_name, g=vg.name:
                               f"bpy.data.objects[{_q(o)}].vertex_groups[{_q(g)}].weight({r})"))
    if extras and comp == "MESH":
        cols += _mesh_extras(data, domain, size, base)
    return cols, size


def _instance_refs(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    gs = ob.evaluated_get(dg).evaluated_geometry()
    return list(gs.instance_references())


def _matrix_columns(label, arr, apath, tip):
    """A 4×4 matrix attribute (instance_transform) as location / rotation (degrees) / scale."""
    n = len(arr)
    m = arr.reshape(n, 4, 4).transpose(0, 2, 1)          # Blender stores matrices column by column
    loc = m[:, :3, 3]
    basis = m[:, :3, :3]
    scale = np.linalg.norm(basis, axis=1)
    rot = np.zeros((n, 3), dtype=np.float32)
    if n <= 200000:
        from mathutils import Matrix
        safe = np.where(scale > 1e-12, scale, 1.0)
        for i in range(n):
            r = Matrix((basis[i] / safe[i]).tolist()).to_euler()
            rot[i] = (math.degrees(r.x), math.degrees(r.y), math.degrees(r.z))
    cols = []
    for part, vals, unit in (("location", loc, ""), ("rotation", rot, "°"), ("scale", scale, "")):
        for c, ax in enumerate("XYZ"):
            cols.append(Column(f"{part} {ax}", vals[:, c], "f", computed=True,
                               tip=f"{label} ({tip}) – {part}{' in degrees' if unit else ''}",
                               python=lambda r, p=apath: f"{p}[{r}].value"))
    return cols


def _mesh_extras(me, domain, size, base):
    cols = []
    try:
        if domain == "POINT" and size:
            nv = np.zeros(size * 3, dtype=np.float32)
            me.vertex_normals.foreach_get("vector", nv)
            nv = nv.reshape(size, 3)
            for c, ax in enumerate("XYZ"):
                cols.append(Column(f"normal {ax}", nv[:, c], "f", computed=True, tip="Vertex normal (computed)",
                                   python=lambda r, c=c: f"{base}.vertex_normals[{r}].vector[{c}]"))
        elif domain == "FACE" and size:
            nf = np.zeros(size * 3, dtype=np.float32)
            me.polygon_normals.foreach_get("vector", nf)
            nf = nf.reshape(size, 3)
            tot = np.zeros(size, dtype=np.int32)
            me.polygons.foreach_get("loop_total", tot)
            area = np.zeros(size, dtype=np.float32)
            me.polygons.foreach_get("area", area)
            cols.append(Column("corners", tot, "i", computed=True, tip="Number of face corners (computed)",
                               python=lambda r: f"{base}.polygons[{r}].loop_total"))
            cols.append(Column("area", area, "f", computed=True, tip="Face area (computed)",
                               python=lambda r: f"{base}.polygons[{r}].area"))
            for c, ax in enumerate("XYZ"):
                cols.append(Column(f"normal {ax}", nf[:, c], "f", computed=True, tip="Face normal (computed)",
                                   python=lambda r, c=c: f"{base}.polygon_normals[{r}].vector[{c}]"))
    except Exception:
        bridge.log(f"Spreadsheet extras: {traceback.format_exc()}", "WARNING")
    return cols


def selection_mask(ob, comp, data, domain):
    """Selected elements (Edit Mode) as a bool array, or None."""
    try:
        if comp == "MESH" and ob.type == "MESH":
            me = data
            if domain == "POINT":
                a = np.zeros(len(me.vertices), dtype=bool)
                me.vertices.foreach_get("select", a)
            elif domain == "EDGE":
                a = np.zeros(len(me.edges), dtype=bool)
                me.edges.foreach_get("select", a)
            elif domain == "FACE":
                a = np.zeros(len(me.polygons), dtype=bool)
                me.polygons.foreach_get("select", a)
            else:
                vs = np.zeros(len(me.vertices), dtype=bool)
                me.vertices.foreach_get("select", vs)
                cv = np.zeros(len(me.loops), dtype=np.int32)
                me.loops.foreach_get("vertex_index", cv)
                a = vs[cv]
            return a
        if comp in ("CURVES", "POINTCLOUD"):
            at = ob.data.attributes.get(".selection")
            if at is not None and at.domain == ("POINT" if domain == "POINT" else domain):
                arr, _p, _n = read_attribute(at, _domain_size(ob.data, comp, at.domain))
                return arr[:, 0].astype(bool)
    except Exception:
        pass
    return None


# ================================================================== objects columns (Attribute Spread Sheet)
def _rot_get(row):
    mode = getattr(row, "rotation_mode", "XYZ")
    if mode in ("QUATERNION",):
        e = row.rotation_quaternion.to_euler()
    elif mode == "AXIS_ANGLE":
        from mathutils import Quaternion
        aa = row.rotation_axis_angle
        e = Quaternion(aa[1:], aa[0]).to_euler()
    else:
        e = row.rotation_euler
    return [math.degrees(x) for x in e]


def _rot_set(row, c, deg):
    from mathutils import Euler
    mode = getattr(row, "rotation_mode", "XYZ")
    cur = [math.radians(x) for x in _rot_get(row)]
    cur[c] = math.radians(deg)
    if mode == "QUATERNION":
        row.rotation_quaternion = Euler(cur, "XYZ").to_quaternion()
    elif mode == "AXIS_ANGLE":
        ax, ang = Euler(cur, "XYZ").to_quaternion().to_axis_angle()
        row.rotation_axis_angle = (ang, ax.x, ax.y, ax.z)
    else:
        e = list(row.rotation_euler)
        e[c] = math.radians(deg)
        row.rotation_euler = e


def _rot_path(row):
    mode = getattr(row, "rotation_mode", "XYZ")
    return {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}.get(mode, "rotation_euler")


def _vec_specs(label, prop, axes="XYZ"):
    return [(f"{label} {a}", prop, i) for i, a in enumerate(axes)]


TAB_SPECS = {
    "Translate": _vec_specs("Translate", "location"),
    "Rotate": _vec_specs("Rotate", "rotation"),
    "Scale": _vec_specs("Scale", "scale"),
}
TAB_SPECS["Keyable"] = TAB_SPECS["Translate"] + TAB_SPECS["Rotate"] + TAB_SPECS["Scale"] + \
    [("Hide in Viewport", "hide_viewport", -1)]
TAB_SPECS["Transform"] = TAB_SPECS["Translate"] + TAB_SPECS["Rotate"] + TAB_SPECS["Scale"] + \
    _vec_specs("Dimensions", "dimensions") + [("Rotation Mode", "rotation_mode", -1)]
TAB_SPECS["Render"] = [("Hide in Renders", "hide_render", -1), ("Camera", "visible_camera", -1),
                       ("Diffuse", "visible_diffuse", -1), ("Glossy", "visible_glossy", -1),
                       ("Transmission", "visible_transmission", -1), ("Volume Scatter", "visible_volume_scatter", -1),
                       ("Shadow", "visible_shadow", -1), ("Holdout", "is_holdout", -1),
                       ("Shadow Catcher", "is_shadow_catcher", -1), ("Pass Index", "pass_index", -1)]
TAB_SPECS["Display"] = [("Display As", "display_type", -1), ("Name", "show_name", -1), ("Axes", "show_axis", -1),
                        ("Wireframe", "show_wire", -1), ("In Front", "show_in_front", -1),
                        ("Disable Selection", "hide_select", -1)] + _vec_specs("Color", "color", "RGBA")
LOCKS = {"location": "lock_location", "rotation": "lock_rotation", "scale": "lock_scale"}


def _rows_python(row):
    if isinstance(row, bpy.types.PoseBone):
        return f"bpy.data.objects[{_q(row.id_data.name)}].pose.bones[{_q(row.name)}]"
    return f"bpy.data.objects[{_q(row.name)}]"


def _anim_states(rows):
    """Per row: {(data_path, index): 'key' | 'drv'}."""
    from .graph_editor import fcurves_of
    out = []
    cache = {}
    for row in rows:
        idb = row.id_data
        key = idb.as_pointer()
        if key not in cache:
            st = {}
            for fc in fcurves_of(idb):
                st[(fc.data_path, fc.array_index)] = "key"
            ad = getattr(idb, "animation_data", None)
            if ad is not None:
                for fc in ad.drivers:
                    st[(fc.data_path, fc.array_index)] = "drv"
            cache[key] = st
        prefix = "" if row is idb else row.path_from_id() + "."
        out.append((cache[key], prefix))
    return out


def _all_specs(row):
    """Every simple editable RNA property of a row (Maya's 'All' tab)."""
    specs = [("Name", "name", -1)]
    for p in row.bl_rna.properties:
        pid = p.identifier
        if pid in ("rna_type", "name") or p.is_readonly or p.type in ("POINTER", "COLLECTION"):
            continue
        if p.type == "ENUM" and p.is_enum_flag:
            continue
        if p.type == "STRING" and getattr(p, "subtype", "") in ("FILE_PATH", "DIR_PATH"):
            continue
        n = getattr(p, "array_length", 0) or 0
        if n > 4 or (n and any(d for d in getattr(p, "array_dimensions", ())[1:])):
            continue
        if n:
            axes = "RGBA" if p.subtype in ("COLOR", "COLOR_GAMMA") else "XYZW"
            specs += [(f"{p.name} {axes[i]}", pid, i) for i in range(n)]
        else:
            specs.append((p.name, pid, -1))
    return specs


def object_columns(rows, tab):
    cols = []
    if not rows:
        return cols
    states = _anim_states(rows)
    if tab == "Custom":
        keys = []
        for row in rows:
            for k in row.keys():
                if k.startswith("_") or k in keys:
                    continue
                v = row.get(k)
                if isinstance(v, (int, float, str, bool)):
                    keys.append(k)
        specs = [(k, ("CUSTOM", k), -1) for k in keys]
    elif tab == "All":
        specs = _all_specs(rows[0])
    else:
        specs = TAB_SPECS.get(tab, [])
    for label, prop, idx in specs:
        col = _object_column(rows, states, label, prop, idx)
        if col is not None:
            cols.append(col)
    return cols


def _object_column(rows, states, label, prop, idx):
    custom = isinstance(prop, tuple)
    vals, state = [], []
    kind = None
    enum_items = []
    ok = False
    for row, (st, prefix) in zip(rows, states):
        v, s = None, None
        try:
            if custom:
                v = row.get(prop[1])
                if isinstance(v, bool):
                    kind = kind or "b"
                elif isinstance(v, int):
                    kind = kind or "i"
                elif isinstance(v, float):
                    kind = kind or "f"
                elif isinstance(v, str):
                    kind = kind or "s"
                else:
                    v = None
                path = f'["{prop[1]}"]'
            elif prop == "rotation":
                v = _rot_get(row)[idx]
                kind = "f"
                path = _rot_path(row)
                s = st.get((prefix + path, idx + (1 if path != "rotation_euler" else 0)))
                if s is None and path != "rotation_euler":
                    s = st.get((prefix + path, 0))
            else:
                if not hasattr(row, prop):
                    vals.append(None)
                    state.append("na")
                    continue
                rp = row.bl_rna.properties[prop]
                raw = getattr(row, prop)
                v = raw[idx] if idx >= 0 else raw
                t = rp.type
                kind = kind or {"FLOAT": "f", "INT": "i", "BOOLEAN": "b", "ENUM": "e", "STRING": "s"}.get(t, "s")
                if t == "ENUM" and not enum_items:
                    enum_items = [(e.identifier, e.name) for e in rp.enum_items]
                if rp.subtype in ("ANGLE", "EULER") and t == "FLOAT":
                    v = math.degrees(v)
                path = prop
            ok = True
            if not custom and prop != "rotation":
                s = st.get((prefix + path, max(idx, 0)))
            lock = LOCKS.get(prop)
            if lock and hasattr(row, lock) and idx >= 0:
                try:
                    if getattr(row, lock)[idx]:
                        s = "lock"
                except Exception:
                    pass
        except Exception:
            v = None
        vals.append(v)
        state.append(s)
    if not ok:
        return None
    kind = kind or "f"
    if kind == "f":
        vals = [None if v is None else float(v) for v in vals]

    def write(src_rows, values, prop=prop, idx=idx, custom=custom, rows_names=[_rows_python(r) for r in rows]):
        for r, v in zip(src_rows, values):
            row = _resolve_row(rows_names[int(r)])
            if row is None:
                continue
            try:
                if custom:
                    row[prop[1]] = v
                elif prop == "rotation":
                    _rot_set(row, idx, float(v))
                    _autokey_row(row, _rot_path(row))
                else:
                    rp = row.bl_rna.properties[prop]
                    if rp.subtype in ("ANGLE", "EULER") and rp.type == "FLOAT":
                        v = math.radians(float(v))
                    if idx >= 0:
                        arr = list(getattr(row, prop))
                        arr[idx] = v
                        setattr(row, prop, arr)
                    else:
                        setattr(row, prop, v)
                    _autokey_row(row, prop, idx)
            except Exception as ex:
                bridge.log(f"Spreadsheet: {prop}: {ex}", "WARNING")

    def python(r, prop=prop, idx=idx, custom=custom, names=[_rows_python(x) for x in rows], rows=rows):
        base = names[r]
        if custom:
            return f"{base}[{_q(prop[1])}]"
        if prop == "rotation":
            return f"{base}.rotation_euler[{idx}]"
        return f"{base}.{prop}[{idx}]" if idx >= 0 else f"{base}.{prop}"

    tip = label if custom else f"{label} ({'custom property' if custom else prop})"
    if not custom and prop not in ("rotation",):
        try:
            rp = rows[0].bl_rna.properties[prop]
            tip = f"{rp.name}\n{rp.description}" if rp.description else rp.name
        except Exception:
            pass
    return Column(label, vals, kind, write=write, python=python, tip=tip, state=state, enum_items=enum_items)


def _resolve_row(path):
    try:
        return eval(path, {"bpy": bpy})
    except Exception:
        return None


def _autokey_row(row, prop, idx=-1):
    try:
        from .rna_widgets import _autokey
        _autokey(row, prop, idx)
    except Exception:
        pass


def _pb_selected(pb):
    """Blender 5.x keeps pose selection on the PoseBone (older versions: on the Bone)."""
    return bool(pb.select) if hasattr(pb, "select") else bool(pb.bone.select)


def _pb_select(pb, on):
    if hasattr(pb, "select"):
        pb.select = on
    else:
        pb.bone.select = on


def object_rows(selected_only=True):
    """Rows of the Objects mode: selected pose bones in Pose Mode, else the selected (or all) objects."""
    ctx = bpy.context
    ob = ctx.view_layer.objects.active
    if ob is not None and ob.mode == "POSE" and ob.pose is not None:
        bones = [pb for pb in ob.pose.bones if _pb_selected(pb)] if selected_only else list(ob.pose.bones)
        if bones or not selected_only:
            return bones, "bones"
    obs = [o for o in ctx.view_layer.objects if (o.select_get() if selected_only else True)]
    obs.sort(key=lambda o: o.name.lower())
    return obs, "objects"


# ================================================================== Qt model
class SheetModel(QtCore.QAbstractTableModel):
    def __init__(self, sheet):
        super().__init__(sheet)
        self.sheet = sheet
        self.cols = []
        self.rowmap = np.zeros(0, dtype=np.int64)
        self.row_labels = None
        self.decimals = 3

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.rowmap)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.cols)

    def src(self, row):
        return int(self.rowmap[row])

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        col = self.cols[index.column()]
        r = self.src(index.row())
        if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
            if role == QtCore.Qt.EditRole and col.kind == "f":
                v = col.value(r)
                return "" if v is None else repr(round(float(v), 6))
            return col.text(r, self.decimals)
        if role == QtCore.Qt.CheckStateRole and col.kind == "b":
            v = col.value(r)
            if v is None:
                return None
            return QtCore.Qt.Checked if v else QtCore.Qt.Unchecked
        if role == QtCore.Qt.TextAlignmentRole:
            if col.kind in ("f", "i"):
                return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            return int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        if role == QtCore.Qt.BackgroundRole and col.state is not None:
            s = col.state[r]
            if s == "key":
                return KEYED_BG
            if s == "drv":
                return DRIVEN_BG
        if role == QtCore.Qt.ForegroundRole:
            if col.state is not None and col.state[r] in ("lock", "na"):
                return LOCKED_FG
            if col.computed:
                return COMPUTED_FG
        if role == QtCore.Qt.FontRole and col.computed:
            f = QtGui.QFont(self.sheet.font())
            f.setItalic(True)
            return f
        if role == QtCore.Qt.ToolTipRole:
            return self._tip(col, r)
        return None

    def _tip(self, col, r):
        state = col.state[r] if col.state is not None else None
        extra = {"key": "\nKeyed", "drv": "\nDriven", "lock": "\nLocked", "na": "\nNot available"}.get(state, "")
        if not col.editable:
            extra += "\nRead-only" + (" (Evaluated – switch to Original to edit)" if self.sheet.evaluated
                                      and self.sheet.mode == "GEOMETRY" else "")
        return f"{col.tip}{extra}".strip()

    def cell_editable(self, row, column):
        col = self.cols[column]
        if not col.editable:
            return False
        if col.state is not None and col.state[self.src(row)] in ("lock", "na"):
            return False
        return col.value(self.src(row)) is not None

    def flags(self, index):
        f = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        if not index.isValid():
            return f
        if self.cell_editable(index.row(), index.column()):
            col = self.cols[index.column()]
            f |= QtCore.Qt.ItemIsUserCheckable if col.kind == "b" else QtCore.Qt.ItemIsEditable
        return f

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        if not index.isValid():
            return False
        if role == QtCore.Qt.CheckStateRole:
            if isinstance(value, bool):
                on = value
            else:
                on = getattr(value, "value", value) == 2
            return self.sheet.apply_edit(index, bool(on))
        if role == QtCore.Qt.EditRole:
            return self.sheet.apply_edit(index, value)
        return False

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation == QtCore.Qt.Horizontal:
            if section >= len(self.cols):
                return None
            col = self.cols[section]
            if role == QtCore.Qt.DisplayRole:
                return col.name
            if role == QtCore.Qt.ToolTipRole:
                return col.tip
            if role == QtCore.Qt.ForegroundRole and col.computed:
                return COMPUTED_FG
            return None
        if role == QtCore.Qt.DisplayRole:
            if section >= len(self.rowmap):
                return None
            r = self.src(section)
            return self.row_labels[r] if self.row_labels is not None else str(r)
        return None

    def set_content(self, cols, rowmap, row_labels):
        same = [c.name for c in cols] == [c.name for c in self.cols] and len(rowmap) == len(self.rowmap) \
            and (row_labels is None) == (self.row_labels is None)
        if same:
            self.cols, self.rowmap, self.row_labels = cols, rowmap, row_labels
            if len(rowmap) and cols:
                self.dataChanged.emit(self.index(0, 0), self.index(len(rowmap) - 1, len(cols) - 1))
            self.headerDataChanged.emit(QtCore.Qt.Vertical, 0, max(0, len(rowmap) - 1))
            return False
        self.beginResetModel()
        self.cols, self.rowmap, self.row_labels = cols, rowmap, row_labels
        self.endResetModel()
        return True


class _Delegate(QtWidgets.QStyledItemDelegate):
    """Enum cells get a combo box, the others a line edit (expressions and += -= *= /=)."""

    def createEditor(self, parent, option, index):
        col = index.model().cols[index.column()]
        if col.kind == "e" and col.enum_items:
            cb = QtWidgets.QComboBox(parent)
            for ident, label in col.enum_items:
                cb.addItem(label, ident)
            return cb
        ed = QtWidgets.QLineEdit(parent)
        ed.setToolTip("A value or an expression (2*pi) – applies to every selected cell.\n"
                      "+=1, -=0.5, *=2, /=2 change each cell relatively.")
        return ed

    def setEditorData(self, editor, index):
        if isinstance(editor, QtWidgets.QComboBox):
            col = index.model().cols[index.column()]
            i = editor.findData(col.value(index.model().src(index.row())))
            editor.setCurrentIndex(max(0, i))
            return
        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QtWidgets.QComboBox):
            model.setData(index, editor.currentData(), QtCore.Qt.EditRole)
            return
        model.setData(index, editor.text(), QtCore.Qt.EditRole)


class _Table(QtWidgets.QTableView):
    def __init__(self, sheet):
        super().__init__(sheet)
        self.sheet = sheet

    def qtshell_python_at(self, w, pos):
        if w is not self.viewport():
            return None
        idx = self.indexAt(pos)
        if not idx.isValid():
            return None
        m = self.model()
        col = m.cols[idx.column()]
        if col.python is None:
            return None
        try:
            return m._tip(col, m.src(idx.row())), col.python(m.src(idx.row()))
        except Exception:
            return None

    def event(self, ev):
        if ev.type() == QtCore.QEvent.ShortcutOverride and self.state() != QtWidgets.QAbstractItemView.EditingState:
            for aid in ("spreadsheet.copy", "spreadsheet.paste", "spreadsheet.filter", "spreadsheet.refresh",
                        "spreadsheet.clear"):
                if keymap.hit(aid, ev):
                    ev.accept()
                    return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        if self.state() != QtWidgets.QAbstractItemView.EditingState:
            if keymap.hit("spreadsheet.copy", ev):
                self.sheet.copy()
                return
            if keymap.hit("spreadsheet.paste", ev):
                self.sheet.paste()
                return
            if keymap.hit("spreadsheet.filter", ev):
                self.sheet.filter_edit.setFocus()
                self.sheet.filter_edit.selectAll()
                return
            if keymap.hit("spreadsheet.refresh", ev):
                self.sheet.refresh(force=True)
                return
            if keymap.hit("spreadsheet.clear", ev):
                self.sheet.clear_selected_cells()
                return
        super().keyPressEvent(ev)


# ================================================================== the dock widget
class Spreadsheet(QtWidgets.QWidget):
    """Spreadsheet dock (Window → Spreadsheet, Geometry Nodes workspace)."""

    changed = QtCore.Signal()

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self.mode = _setting("mode", "GEOMETRY")
        if self.mode not in MODES:
            self.mode = "GEOMETRY"
        self.evaluated = _setting("evaluated", True)
        self.selected_only = _setting("selected_only", True)
        self.internal = _setting("internal", False)
        self.extras = _setting("extras", True)
        self.decimals = max(0, min(6, _setting("decimals", 3)))
        self.tab = _setting("tab", "Keyable")
        if self.tab not in TABS:
            self.tab = "Keyable"
        self.component = _setting("component", "MESH")
        self.domain = _setting("domain", "POINT")
        self.pinned = None                       # object name while pinned
        self.row_filters = []                    # [{"column", "op", "value", "on"}]
        self.sort_col = None
        self.sort_desc = False
        self.col_filter = ""
        self.last_info = ""
        self.last_object = None
        self._last_refresh = 0.0
        self._refresh_cost = 0.0
        self._building = False
        self._counts = {}
        self._mask_note = ""
        self._build()
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self.refresh())
        for sig in ("data_changed", "selection_changed", "file_loaded", "undo_done"):
            s = getattr(hub, sig, None)
            if s is not None:
                s.connect(lambda *_a: self.schedule())
        for sig in ("frame_changed", "mode_changed"):
            s = getattr(hub, sig, None)
            if s is not None:
                s.connect(lambda *_a: self.schedule())

    # ------------------------------------------------------------ UI
    def _build(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)

        def tbtn(text, tip, fn=None, checkable=False, icon=None, py=None):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setFocusPolicy(QtCore.Qt.NoFocus)
            if icon:
                try:
                    from . import blicons
                    if blicons.has(icon):
                        b.setIcon(blicons.icon(icon))
                        b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
                except Exception:
                    pass
            if fn is not None:
                if checkable:
                    b.toggled.connect(fn)
                else:
                    b.clicked.connect(lambda _=False: fn())
            if py:
                pytips.tag(b, SS_PY + py)
            row.addWidget(b)
            return b

        self.mode_group = QtWidgets.QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.geo_btn = tbtn("Geometry", "Geometry of the active object – attributes per vertex / edge / face …\n"
                            "(Blender's Spreadsheet, Maya's Component Editor)", checkable=True, icon="MESH_DATA",
                            py='set_mode("GEOMETRY")')
        self.obj_btn = tbtn("Objects", "Attributes of the selected objects / bones (Maya's Attribute Spread Sheet)",
                            checkable=True, icon="OBJECT_DATA", py='set_mode("OBJECTS")')
        self.mode_group.addButton(self.geo_btn)
        self.mode_group.addButton(self.obj_btn)
        (self.geo_btn if self.mode == "GEOMETRY" else self.obj_btn).setChecked(True)
        self.geo_btn.toggled.connect(lambda on: on and self.set_mode("GEOMETRY"))
        self.obj_btn.toggled.connect(lambda on: on and self.set_mode("OBJECTS"))
        row.addSpacing(6)
        self.object_label = QtWidgets.QLabel("")
        self.object_label.setMinimumWidth(theme.px(60))
        row.addWidget(self.object_label)
        self.pin_btn = tbtn("", "Pin – keep showing this object when another one becomes active", checkable=True,
                            icon="PINNED", py="pin(True)")
        self.pin_btn.toggled.connect(self._pin_toggled)
        row.addSpacing(6)
        self.eval_group = QtWidgets.QButtonGroup(self)
        self.eval_btn = tbtn("Evaluated", "The result of modifiers and Geometry Nodes (read-only)", checkable=True,
                             py="set_evaluated(True)")
        self.orig_btn = tbtn("Original", "The object's own data – values can be edited (also in Edit Mode)",
                             checkable=True, py="set_evaluated(False)")
        self.eval_group.addButton(self.eval_btn)
        self.eval_group.addButton(self.orig_btn)
        (self.eval_btn if self.evaluated else self.orig_btn).setChecked(True)
        self.eval_btn.toggled.connect(lambda on: on and self.set_evaluated(True))
        self.orig_btn.toggled.connect(lambda on: on and self.set_evaluated(False))
        self.sel_btn = tbtn("Selected Only", "Geometry: only the selected elements (Edit Mode)\n"
                            "Objects: only the selected objects / bones (off: all of them)", checkable=True,
                            icon="RESTRICT_SELECT_OFF", py="set_selected_only(True)")
        self.sel_btn.setChecked(self.selected_only)
        self.sel_btn.toggled.connect(self.set_selected_only)
        row.addSpacing(6)
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("Filter columns…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setFixedWidth(theme.px(150))
        keymap.tip(self.filter_edit, "Show only the columns whose name contains this text ({spreadsheet.filter})")
        pytips.tag(self.filter_edit, SS_PY + 'set_column_filter("pos")')
        self.filter_edit.textChanged.connect(self.set_column_filter)
        row.addWidget(self.filter_edit)
        self.copy_btn = tbtn("Copy", "", self.copy, icon="COPYDOWN", py="copy()")
        keymap.tip(self.copy_btn, "Copy the selected cells – tab separated, pastes into Excel ({spreadsheet.copy})")
        self.paste_btn = tbtn("Paste", "", self.paste, icon="PASTEDOWN", py="paste()")
        keymap.tip(self.paste_btn, "Paste into the cells from the current one (one value: into every selected cell) "
                                   "({spreadsheet.paste})")
        self.export_btn = tbtn("Export CSV…", "Save the shown rows and columns as a CSV file", self.export_dialog,
                               icon="EXPORT", py='export_csv("C:/out/sheet.csv")')
        self.opt_btn = tbtn("Options", "Decimals, internal attributes, computed columns", icon="PREFERENCES")
        self.opt_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        m = QtWidgets.QMenu(self.opt_btn)
        m.aboutToShow.connect(lambda m=m: self._fill_options(m))
        self.opt_btn.setMenu(m)
        self.refresh_btn = tbtn("", "", lambda: self.refresh(force=True), icon="FILE_REFRESH", py="refresh()")
        keymap.tip(self.refresh_btn, "Read the data again ({spreadsheet.refresh})")
        row.addStretch(1)
        lay.addWidget(hscroll.wrap_layout(row, self))

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        left = QtWidgets.QWidget(split)
        ll = QtWidgets.QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(2)
        self.tree = QtWidgets.QTreeWidget(left)
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(theme.px(10))
        self.tree.itemClicked.connect(self._tree_clicked)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        ll.addWidget(self.tree, 3)
        fh = QtWidgets.QHBoxLayout()
        fh.setContentsMargins(2, 0, 2, 0)
        lbl = QtWidgets.QLabel("Row Filters")
        lbl.setStyleSheet("font-weight: bold;")
        fh.addWidget(lbl)
        fh.addStretch(1)
        add = QtWidgets.QToolButton(left)
        add.setText("+")
        add.setToolTip("Add a row filter: keep the rows whose value matches")
        add.clicked.connect(lambda _=False: self._add_filter_ui())
        pytips.tag(add, SS_PY + 'add_row_filter("position Z", ">", 0)')
        fh.addWidget(add)
        ll.addLayout(fh)
        self.filters_host = QtWidgets.QWidget(left)
        self.filters_lay = QtWidgets.QVBoxLayout(self.filters_host)
        self.filters_lay.setContentsMargins(0, 0, 0, 0)
        self.filters_lay.setSpacing(2)
        fscroll = QtWidgets.QScrollArea(left)
        fscroll.setWidgetResizable(True)
        fscroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        fscroll.setWidget(self.filters_host)
        ll.addWidget(fscroll, 2)
        split.addWidget(left)

        right = QtWidgets.QWidget(split)
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(1)
        self.model = SheetModel(self)
        self.table = _Table(self)
        self.table.setParent(right)
        self.table.setModel(self.model)
        self.table.setItemDelegate(_Delegate(self.table))
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked |
                                   QtWidgets.QAbstractItemView.EditKeyPressed |
                                   QtWidgets.QAbstractItemView.AnyKeyPressed)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(theme.px(20))
        self.table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        hh = self.table.horizontalHeader()
        hh.setSectionsClickable(True)
        hh.setHighlightSections(True)
        hh.sectionClicked.connect(self._header_clicked)
        hh.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        hh.customContextMenuRequested.connect(self._header_menu)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._cell_menu)
        rl.addWidget(self.table, 1)
        self.status = QtWidgets.QLabel("")
        self.status.setStyleSheet("color: #9a9a9a; padding: 1px 4px;")
        rl.addWidget(self.status)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([theme.px(190), theme.px(800)])
        lay.addWidget(split, 1)
        self._sync_buttons()

    def _fill_options(self, m):
        m.clear()
        dm = m.addMenu("Decimals")
        for d in range(0, 7):
            a = dm.addAction(str(d), lambda d=d: self.set_decimals(d))
            a.setCheckable(True)
            a.setChecked(d == self.decimals)
            pytips.tag(a, SS_PY + f"set_decimals({d})")
        a = m.addAction("Internal Attributes (names starting with a dot)", lambda: self.set_option("internal",
                                                                                                   not self.internal))
        a.setCheckable(True)
        a.setChecked(self.internal)
        pytips.tag(a, SS_PY + "set_option('internal', True)")
        a = m.addAction("Computed Columns (normals, face area, corners)", lambda: self.set_option("extras",
                                                                                                  not self.extras))
        a.setCheckable(True)
        a.setChecked(self.extras)
        pytips.tag(a, SS_PY + "set_option('extras', False)")
        m.addSeparator()
        m.addAction("Fit Column Widths", self.table.resizeColumnsToContents)
        m.addAction("Clear Sorting", lambda: self.sort_by(None))
        m.addAction("Remove All Row Filters", self.clear_row_filters)

    def _sync_buttons(self):
        geo = self.mode == "GEOMETRY"
        for b in (self.eval_btn, self.orig_btn, self.pin_btn):
            b.setVisible(geo)
        self.object_label.setVisible(geo)
        for b, on in ((self.geo_btn, geo), (self.obj_btn, not geo), (self.eval_btn, self.evaluated),
                      (self.orig_btn, not self.evaluated), (self.sel_btn, self.selected_only),
                      (self.pin_btn, self.pinned is not None)):
            if b.isChecked() != on:
                b.blockSignals(True)
                b.setChecked(on)
                b.blockSignals(False)
        self.paste_btn.setEnabled(not (geo and self.evaluated))

    # ------------------------------------------------------------ state changes (also the API)
    def set_mode(self, mode):
        """GEOMETRY (Blender Spreadsheet / Maya Component Editor) or OBJECTS (Maya Attribute Spread Sheet)."""
        mode = str(mode).upper()
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.mode = mode
        _settings().setValue(SETTINGS + "mode", mode)
        self.sort_col = None
        self._sync_buttons()
        self.refresh(force=True)

    def set_evaluated(self, on=True):
        """Geometry mode: True = evaluated (modifiers / Geometry Nodes, read-only), False = original (editable)."""
        self.evaluated = bool(on)
        _settings().setValue(SETTINGS + "evaluated", self.evaluated)
        self._sync_buttons()
        self.refresh(force=True)

    def set_selected_only(self, on=True):
        """Geometry: only the selected elements (Edit Mode). Objects: only the selected objects / bones."""
        self.selected_only = bool(on)
        _settings().setValue(SETTINGS + "selected_only", self.selected_only)
        self._sync_buttons()
        self.refresh(force=True)

    def set_domain(self, domain, component=None):
        """Geometry mode: show a domain – POINT, EDGE, FACE, CORNER, CURVE or INSTANCE; component MESH, CURVES,
        POINTCLOUD or INSTANCES (None: the first one that has the domain)."""
        domain = str(domain).upper()
        if component is None:
            for comp, (_l, doms) in COMPONENTS.items():
                if any(d == domain for d, _ in doms) and (comp in self._counts or not self._counts):
                    component = comp
                    break
        component = str(component or self.component).upper()
        if component not in COMPONENTS or domain not in [d for d, _ in COMPONENTS[component][1]]:
            raise ValueError(f"{component} has no domain {domain}")
        self.component, self.domain = component, domain
        _settings().setValue(SETTINGS + "component", component)
        _settings().setValue(SETTINGS + "domain", domain)
        self.sort_col = None
        if self.mode != "GEOMETRY":
            self.set_mode("GEOMETRY")
        else:
            self.refresh(force=True)

    def set_tab(self, tab):
        """Objects mode: Keyable, Translate, Rotate, Scale, Transform, Render, Display, Custom or All."""
        t = next((x for x in TABS if x.lower() == str(tab).lower()), None)
        if t is None:
            raise ValueError(f"tab must be one of {TABS}")
        self.tab = t
        _settings().setValue(SETTINGS + "tab", t)
        self.sort_col = None
        if self.mode != "OBJECTS":
            self.set_mode("OBJECTS")
        else:
            self.refresh(force=True)

    def pin(self, on=True, name=None):
        """Geometry mode: keep showing this object (name or the active one) when another becomes active."""
        if on:
            if name is None:
                ob = bpy.context.view_layer.objects.active
                name = ob.name if ob is not None else None
            if name is not None and bpy.data.objects.get(name) is None:
                raise ValueError(f"no object {name!r}")
            self.pinned = name
        else:
            self.pinned = None
        self._sync_buttons()
        self.refresh(force=True)

    def _pin_toggled(self, on):
        if on != (self.pinned is not None):
            self.pin(on)

    def set_column_filter(self, text=""):
        """Show only the columns whose name contains the text (case-insensitive)."""
        self.col_filter = str(text or "")
        if self.filter_edit.text() != self.col_filter:
            self.filter_edit.blockSignals(True)
            self.filter_edit.setText(self.col_filter)
            self.filter_edit.blockSignals(False)
        self.refresh(force=True)

    def set_decimals(self, n=3):
        """Number of decimals shown for float values (0–6)."""
        self.decimals = max(0, min(6, int(n)))
        _settings().setValue(SETTINGS + "decimals", self.decimals)
        self.model.decimals = self.decimals
        self.refresh(force=True)

    def set_option(self, name, on):
        """'internal' – internal attributes (names starting with a dot); 'extras' – computed columns."""
        if name not in ("internal", "extras"):
            raise ValueError("option must be 'internal' or 'extras'")
        setattr(self, name, bool(on))
        _settings().setValue(SETTINGS + name, bool(on))
        self.refresh(force=True)

    def sort_by(self, column=None, descending=False):
        """Sort the rows by a column (name), None = element order."""
        if column is not None and column not in [c.name for c in self.model.cols]:
            raise ValueError(f"no column {column!r}")
        self.sort_col = column
        self.sort_desc = bool(descending)
        self.refresh(force=True)

    def add_row_filter(self, column, op="=", value=0.0):
        """Keep only the rows whose value in the column matches: op =, ≠ (or !=), >, <, ≥ (>=), ≤ (<=), contains.
        '=' on floats allows a difference of 0.0001 (like Blender)."""
        op = {"==": "=", "!=": "≠", ">=": "≥", "<=": "≤"}.get(op, op)
        if op not in OPS:
            raise ValueError(f"op must be one of {OPS}")
        self.row_filters.append({"column": column, "op": op, "value": value, "on": True})
        self._rebuild_filter_ui()
        self.refresh(force=True)
        return len(self.row_filters) - 1

    def clear_row_filters(self):
        """Remove every row filter."""
        self.row_filters = []
        self._rebuild_filter_ui()
        self.refresh(force=True)

    # ------------------------------------------------------------ row filters UI
    def _add_filter_ui(self):
        names = [c.name for c in self.model.cols]
        self.add_row_filter(names[0] if names else "", "=", "")

    def _rebuild_filter_ui(self):
        while self.filters_lay.count():
            it = self.filters_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        names = [c.name for c in self.model.cols]
        for i, f in enumerate(self.row_filters):
            box = QtWidgets.QFrame(self.filters_host)
            box.setFrameShape(QtWidgets.QFrame.StyledPanel)
            g = QtWidgets.QGridLayout(box)
            g.setContentsMargins(3, 3, 3, 3)
            g.setSpacing(2)
            on = QtWidgets.QCheckBox(box)
            on.setChecked(f["on"])
            on.setToolTip("Use this filter")
            cb = QtWidgets.QComboBox(box)
            cb.addItems(names if f["column"] in names or not f["column"] else names + [f["column"]])
            cb.setCurrentText(f["column"])
            opb = QtWidgets.QComboBox(box)
            opb.addItems(list(OPS))
            opb.setCurrentText(f["op"])
            val = QtWidgets.QLineEdit(str(f["value"]), box)
            val.setPlaceholderText("value")
            rm = QtWidgets.QToolButton(box)
            rm.setText("×")
            rm.setToolTip("Remove this filter")
            g.addWidget(on, 0, 0)
            g.addWidget(cb, 0, 1, 1, 2)
            g.addWidget(rm, 0, 3)
            g.addWidget(opb, 1, 1)
            g.addWidget(val, 1, 2, 1, 2)
            g.setColumnStretch(2, 1)

            def upd(_=None, i=i, on=on, cb=cb, opb=opb, val=val):
                if i < len(self.row_filters):
                    self.row_filters[i].update(on=on.isChecked(), column=cb.currentText(), op=opb.currentText(),
                                               value=val.text())
                    self.refresh(force=True)

            def remove(_=False, i=i):
                if i < len(self.row_filters):
                    del self.row_filters[i]
                    QtCore.QTimer.singleShot(0, self, self._rebuild_filter_ui)
                    self.refresh(force=True)
            on.toggled.connect(upd)
            cb.activated.connect(upd)
            opb.activated.connect(upd)
            val.editingFinished.connect(upd)
            rm.clicked.connect(remove)
            self.filters_lay.addWidget(box)
        self.filters_lay.addStretch(1)

    @staticmethod
    def _filter_mask(col, f, n):
        op, raw = f["op"], f["value"]
        vals = col.values
        if col.kind in ("f", "i", "b") and op != "contains":
            try:
                target = float(_eval_number(raw)) if not isinstance(raw, bool) else float(raw)
            except Exception:
                return np.ones(n, dtype=bool)
            v = np.asarray([np.nan if x is None else x for x in vals], dtype=np.float64) \
                if not isinstance(vals, np.ndarray) else vals.astype(np.float64)
            eps = 1e-4 if col.kind == "f" else 0.0
            if op == "=":
                return np.abs(v - target) <= eps
            if op == "≠":
                return np.abs(v - target) > eps
            if op == ">":
                return v > target
            if op == "<":
                return v < target
            if op == "≥":
                return v >= target - eps
            if op == "≤":
                return v <= target + eps
        texts = [str(x if x is not None else "").lower() for x in (vals.tolist() if isinstance(vals, np.ndarray)
                                                                    else vals)]
        t = str(raw).lower()
        if op == "contains":
            return np.array([t in s for s in texts], dtype=bool)
        if op == "=":
            return np.array([s == t for s in texts], dtype=bool)
        if op == "≠":
            return np.array([s != t for s in texts], dtype=bool)
        return np.ones(n, dtype=bool)

    # ------------------------------------------------------------ data set list
    def _tree_clicked(self, item, _col):
        d = item.data(0, QtCore.Qt.UserRole)
        if not d:
            return
        kind, a, b = d
        # not inside the tree's own signal – the refresh rebuilds the tree
        if kind == "domain":
            QtCore.QTimer.singleShot(0, self, lambda: self.set_domain(b, a))
        elif kind == "tab":
            QtCore.QTimer.singleShot(0, self, lambda: self.set_tab(a))

    def _fill_tree(self, counts):
        key = (self.mode, self.tab, self.component, self.domain, repr(sorted(counts.items())))
        if key == getattr(self, "_tree_key", None):
            return
        self._tree_key = key
        from . import blicons
        self.tree.blockSignals(True)
        self.tree.clear()
        bold = QtGui.QFont(self.tree.font())
        bold.setBold(True)
        cur = None
        if self.mode == "GEOMETRY":
            if not counts:
                it = QtWidgets.QTreeWidgetItem(self.tree, ["No geometry", ""])
                it.setFlags(QtCore.Qt.ItemIsEnabled)
            for comp, (label, doms) in COMPONENTS.items():
                if comp not in counts:
                    continue
                top = QtWidgets.QTreeWidgetItem(self.tree, [label, ""])
                top.setFont(0, bold)
                top.setFlags(QtCore.Qt.ItemIsEnabled)
                try:
                    if blicons.has(COMPONENT_ICONS[comp]):
                        top.setIcon(0, blicons.icon(COMPONENT_ICONS[comp]))
                except Exception:
                    pass
                for dom, dlabel in doms:
                    n = counts[comp].get(dom, 0)
                    it = QtWidgets.QTreeWidgetItem(top, ["  " + dlabel, f"{n:,}".replace(",", " ")])
                    it.setData(0, QtCore.Qt.UserRole, ("domain", comp, dom))
                    it.setTextAlignment(1, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                    it.setToolTip(0, f"{label} · {dlabel} – {n} element(s)")
                    try:
                        if blicons.has(DOMAIN_ICONS[dom]):
                            it.setIcon(0, blicons.icon(DOMAIN_ICONS[dom]))
                    except Exception:
                        pass
                    if comp == self.component and dom == self.domain:
                        cur = it
                top.setExpanded(True)
        else:
            top = QtWidgets.QTreeWidgetItem(self.tree, ["Attribute Tabs", ""])
            top.setFont(0, bold)
            top.setFlags(QtCore.Qt.ItemIsEnabled)
            for t in TABS:
                it = QtWidgets.QTreeWidgetItem(top, ["  " + t, ""])
                it.setData(0, QtCore.Qt.UserRole, ("tab", t, None))
                if t == self.tab:
                    cur = it
            top.setExpanded(True)
        if cur is not None:
            self.tree.setCurrentItem(cur)
        self.tree.blockSignals(False)

    # ------------------------------------------------------------ refresh
    def schedule(self):
        if not self.isVisible():
            return
        if self.table.state() == QtWidgets.QAbstractItemView.EditingState:
            return
        wait = max(0.08, 3 * self._refresh_cost) - (time.perf_counter() - self._last_refresh)
        if not self._timer.isActive():
            self._timer.start(int(max(0.0, wait) * 1000) + 30)

    def showEvent(self, ev):
        super().showEvent(ev)
        QtCore.QTimer.singleShot(0, self, lambda: self.refresh(force=True))

    def target_object(self):
        if self.pinned is not None:
            ob = bpy.data.objects.get(self.pinned)
            if ob is not None:
                return ob
            self.pinned = None
            self._sync_buttons()
        return bpy.context.view_layer.objects.active

    def _collect(self):
        """(columns, row labels, selection mask, counts, info)."""
        if self.mode == "OBJECTS":
            rows, kind = object_rows(self.selected_only)
            cols = object_columns(rows, self.tab)
            labels = [r.name for r in rows]
            what = "bone" if kind == "bones" else "object"
            info = f"{self.tab} · {len(rows)} {what}{'s' if len(rows) != 1 else ''}"
            self.last_object = None
            return cols, labels, None, {}, info, len(rows)
        ob = self.target_object()
        self.last_object = ob.name if ob is not None else None
        self.object_label.setText(f"  {ob.name}" if ob is not None else "  (no active object)")
        cleanup, comps = geometry_components(ob, self.evaluated)
        try:
            return self._collect_geometry(ob, comps)
        finally:
            try:
                cleanup()
            except Exception:
                pass

    def _collect_geometry(self, ob, comps):
        counts = {}
        for comp, data in comps:
            counts[comp] = {d: _domain_size(data, comp, d) for d, _l in COMPONENTS[comp][1]}
        comp_data = dict(comps)
        if self.component not in comp_data and comps:
            self.component = comps[0][0]
            self.domain = COMPONENTS[self.component][1][0][0]
        if self.component in comp_data and self.domain not in counts.get(self.component, {}):
            self.domain = COMPONENTS[self.component][1][0][0]
        if ob is None or self.component not in comp_data:
            return [], None, None, counts, "No geometry" if ob is not None else "No active object", 0
        data = comp_data[self.component]
        cols, size = geometry_columns(ob, self.component, data, self.domain, self.evaluated,
                                      internal=self.internal, extras=self.extras)
        mask = None
        self._mask_note = ""
        if self.selected_only and ob.mode == "EDIT":
            if self.evaluated:
                clean2, orig = geometry_components(ob, False)
                try:
                    od = dict(orig).get(self.component)
                    if od is not None and _domain_size(od, self.component, self.domain) == size:
                        mask = selection_mask(ob, self.component, od, self.domain)
                    else:
                        self._mask_note = " · selection not mapped (topology changed)"
                finally:
                    clean2()
            else:
                mask = selection_mask(ob, self.component, data, self.domain)
        label, doms = COMPONENTS[self.component]
        dlabel = dict(doms).get(self.domain, self.domain)
        state = "Evaluated (read-only)" if self.evaluated else "Original (editable)"
        info = f"{ob.name} · {label} · {dlabel} · {state}"
        return cols, None, mask, counts, info, size

    def refresh(self, force=False):
        """Read the data again."""
        if self._building:
            return
        if not force and not self.isVisible():
            return
        self._building = True
        t0 = time.perf_counter()
        try:
            try:
                cols, labels, mask, counts, info, n = self._collect()
            except Exception:
                bridge.log(f"Spreadsheet: {traceback.format_exc()}", "ERROR")
                cols, labels, mask, counts, info, n = [], None, None, {}, "Error – see the log", 0
            self._counts = counts
            self._fill_tree(counts)
            if self.col_filter:
                t = self.col_filter.lower()
                cols = [c for c in cols if t in c.name.lower()]
            keep = np.ones(n, dtype=bool) if mask is None else mask.copy()
            by_name = {c.name: c for c in cols}
            all_cols = cols
            for f in self.row_filters:
                c = by_name.get(f["column"])
                if f["on"] and c is not None and n:
                    try:
                        keep &= self._filter_mask(c, f, n)
                    except Exception:
                        pass
            rowmap = np.nonzero(keep)[0].astype(np.int64)
            if self.sort_col is not None and self.sort_col in by_name and len(rowmap):
                key = by_name[self.sort_col].sort_key()[rowmap]
                order = np.argsort(key, kind="stable")
                if self.sort_desc:
                    order = order[::-1]
                rowmap = rowmap[order]
            self.model.decimals = self.decimals
            reset = self.model.set_content(all_cols, rowmap, labels)
            hh = self.table.horizontalHeader()
            if self.sort_col is not None and self.sort_col in by_name:
                hh.setSortIndicatorShown(True)
                hh.setSortIndicator([c.name for c in all_cols].index(self.sort_col),
                                    QtCore.Qt.DescendingOrder if self.sort_desc else QtCore.Qt.AscendingOrder)
            else:
                hh.setSortIndicatorShown(False)
            if reset:
                self.table.resizeColumnsToContents()
                for i in range(len(all_cols)):
                    if self.table.columnWidth(i) > theme.px(220):
                        self.table.setColumnWidth(i, theme.px(220))
                    elif self.table.columnWidth(i) < theme.px(56):
                        self.table.setColumnWidth(i, theme.px(56))
                self._rebuild_filter_ui()
            shown = len(rowmap)
            rows_txt = f"{shown:,}".replace(",", " ") + (f" of {n:,}".replace(",", " ") if shown != n else "")
            self.last_info = f"{info} · {rows_txt} rows · {len(all_cols)} columns{self._mask_note}"
            self.status.setText(self.last_info)
            self.changed.emit()
        finally:
            self._building = False
            self._last_refresh = time.perf_counter()
            self._refresh_cost = self._last_refresh - t0

    # ------------------------------------------------------------ sorting / menus
    def _header_clicked(self, section):
        if section >= len(self.model.cols):
            return
        name = self.model.cols[section].name
        if self.sort_col != name:
            self.sort_by(name, False)
        elif not self.sort_desc:
            self.sort_by(name, True)
        else:
            self.sort_by(None)

    def _header_menu(self, pos):
        sec = self.table.horizontalHeader().logicalIndexAt(pos)
        if sec < 0 or sec >= len(self.model.cols):
            return
        name = self.model.cols[sec].name
        m = QtWidgets.QMenu(self)
        m.addAction("Sort Ascending", lambda: self.sort_by(name, False))
        m.addAction("Sort Descending", lambda: self.sort_by(name, True))
        m.addAction("Clear Sorting", lambda: self.sort_by(None))
        m.addSeparator()
        m.addAction(f"Filter Rows by “{name}”…", lambda: self.add_row_filter(name, "=", ""))
        m.addAction("Select Column", lambda: self.table.selectColumn(sec))
        m.exec(self.table.horizontalHeader().mapToGlobal(pos))

    def _cell_menu(self, pos):
        m = QtWidgets.QMenu(self)
        m.addAction("Copy", self.copy)
        a = m.addAction("Paste", self.paste)
        a.setEnabled(not (self.mode == "GEOMETRY" and self.evaluated))
        m.addAction("Set Selected Cells…", self.set_cells_dialog)
        m.addAction("Reset Selected Cells to 0", self.clear_selected_cells)
        m.addSeparator()
        if self.mode == "GEOMETRY":
            ob = self.target_object()
            if ob is not None and ob.mode == "EDIT" and ob.type == "MESH" and self.component == "MESH" \
                    and self.domain in ("POINT", "EDGE", "FACE"):
                m.addAction("Select These Elements in the 3D View", self.select_in_view)
        else:
            m.addAction("Select These in the 3D View", self.select_in_view)
        m.addAction("Export CSV…", self.export_dialog)
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ editing
    def _targets(self, index):
        sel = self.table.selectionModel().selectedIndexes() if self.table.selectionModel() else []
        if index is not None and (not sel or index not in sel):
            return [index]
        return sel

    def apply_edit(self, index, value):
        """A typed value: into the edited cell, or into every selected cell when it is part of the selection."""
        targets = [i for i in self._targets(index) if self.model.cell_editable(i.row(), i.column())]
        # refresh later – we are inside the delegate's setModelData
        return self._write_cells([(i.row(), i.column(), value) for i in targets], "Edit", defer=True)

    def _write_cells(self, items, what="Edit", defer=False):
        """items: [(view row, column, value)] → writes grouped per column, one undo step."""
        groups = {}
        errors = []
        for row, column, value in items:
            col = self.model.cols[column]
            src = self.model.src(row)
            try:
                v = _convert(value, col, col.value(src))
            except Exception as ex:
                errors.append(str(ex))
                continue
            groups.setdefault(column, ([], []))
            groups[column][0].append(src)
            groups[column][1].append(v)
        if not groups:
            if errors:
                self._status(f"Not a value: {errors[0]}")
            return False
        names = []
        try:
            with bridge.blender_context():
                for column, (rows, vals) in groups.items():
                    col = self.model.cols[column]
                    col.write(rows, vals)
                    names.append(col.name)
        except Exception:
            bridge.log(f"Spreadsheet: {traceback.format_exc()}", "ERROR")
        n = sum(len(r) for r, _v in groups.values())
        bridge.undo_push(f"Spreadsheet: {what} {', '.join(dict.fromkeys(names))}"[:60])
        self._status(f"{what}: {n} cell{'s' if n != 1 else ''} ({', '.join(dict.fromkeys(names))})")
        if defer:
            QtCore.QTimer.singleShot(0, self, lambda: self.refresh(force=True))
        else:
            self.refresh(force=True)
        return True

    def _status(self, text):
        try:
            w = self.window()
            if hasattr(w, "statusBar"):
                w.statusBar().showMessage(text, 4000)
        except Exception:
            pass

    def set_cells_dialog(self):
        text, ok = QtWidgets.QInputDialog.getText(self, "Set Selected Cells",
                                                  "Value or expression (+=1, *=2 … change each cell):")
        if ok and text.strip():
            self.set_selected(text)

    def set_selected(self, value):
        """Write a value (or +=, -=, *=, /= / an expression) into every selected editable cell."""
        sel = self.table.selectionModel().selectedIndexes()
        items = [(i.row(), i.column(), value) for i in sel if self.model.cell_editable(i.row(), i.column())]
        return self._write_cells(items, "Set")

    def clear_selected_cells(self):
        """Number cells of the selection → 0, check boxes off, text empty."""
        sel = self.table.selectionModel().selectedIndexes()
        items = []
        for i in sel:
            if not self.model.cell_editable(i.row(), i.column()):
                continue
            k = self.model.cols[i.column()].kind
            if k == "e":
                continue
            items.append((i.row(), i.column(), {"b": False, "s": ""}.get(k, "0")))
        return self._write_cells(items, "Reset")

    # ------------------------------------------------------------ API helpers
    def columns(self):
        """Names of the shown columns."""
        return [c.name for c in self.model.cols]

    def rows(self):
        """Element indices (Geometry) or names (Objects) of the shown rows, in the shown order."""
        if self.model.row_labels is not None:
            return [self.model.row_labels[int(r)] for r in self.model.rowmap]
        return [int(r) for r in self.model.rowmap]

    def _col_index(self, column):
        if isinstance(column, int):
            return column
        names = self.columns()
        if column not in names:
            raise ValueError(f"no column {column!r} – columns: {', '.join(names[:12])}")
        return names.index(column)

    def _row_index(self, row):
        rows = self.rows()
        if row not in rows:
            raise ValueError(f"row {row!r} is not shown")
        return rows.index(row)

    def value(self, row, column):
        """Value of a cell: row = element index (Geometry) or object / bone name (Objects), column = name."""
        c = self._col_index(column)
        r = self._row_index(row)
        return self.model.cols[c].value(self.model.src(r))

    def set_value(self, rows, column, value):
        """Write a value into the cells of these rows (an index / name or a list) in a column. value may be
        relative: "+=1", "*=2". Only Original geometry and Objects can be edited."""
        if not isinstance(rows, (list, tuple, set, range)):
            rows = [rows]
        c = self._col_index(column)
        items = []
        for row in rows:
            r = self._row_index(row)
            if not self.model.cell_editable(r, c):
                raise ValueError(f"cell {row!r} / {self.model.cols[c].name!r} can't be edited")
            items.append((r, c, value))
        return self._write_cells(items, "Set")

    def select_cells(self, rows=None, columns=None):
        """Select cells in the table (rows: indices / names, columns: names; None = all)."""
        sm = self.table.selectionModel()
        sm.clearSelection()
        rr = range(self.model.rowCount()) if rows is None else [self._row_index(r) for r in rows]
        cc = range(self.model.columnCount()) if columns is None else [self._col_index(c) for c in columns]
        sel = QtCore.QItemSelection()
        for r in rr:
            for c in cc:
                i = self.model.index(r, c)
                sel.select(i, i)
        sm.select(sel, QtCore.QItemSelectionModel.Select)

    # ------------------------------------------------------------ copy / paste / export
    def _block(self):
        sel = self.table.selectionModel().selectedIndexes()
        if not sel:
            return None
        rows = sorted({i.row() for i in sel})
        cols = sorted({i.column() for i in sel})
        chosen = {(i.row(), i.column()) for i in sel}
        return rows, cols, chosen

    def copy(self):
        """Copy the selected cells to the clipboard (tab separated rows, like Excel)."""
        b = self._block()
        if b is None:
            self._status("Nothing selected to copy")
            return ""
        rows, cols, chosen = b
        lines = []
        for r in rows:
            vals = []
            for c in cols:
                if (r, c) not in chosen:
                    vals.append("")
                    continue
                col = self.model.cols[c]
                v = col.value(self.model.src(r))
                if col.kind == "f" and v is not None:
                    vals.append(repr(round(float(v), 6)))
                elif col.kind == "b" and v is not None:
                    vals.append("1" if v else "0")
                else:
                    vals.append("" if v is None else str(v))
            lines.append("\t".join(vals))
        text = "\n".join(lines)
        QtWidgets.QApplication.clipboard().setText(text)
        self._status(f"Copied {len(chosen)} cell{'s' if len(chosen) != 1 else ''}")
        return text

    def paste(self, text=None):
        """Paste tab separated text from the current cell on; a single value goes into every selected cell."""
        if text is None:
            text = QtWidgets.QApplication.clipboard().text()
        text = (text or "").rstrip("\r\n")
        if not text:
            return False
        grid = [ln.split("\t") for ln in text.replace("\r", "").split("\n")]
        if len(grid) == 1 and len(grid[0]) == 1:
            return self.set_selected(grid[0][0])
        cur = self.table.currentIndex()
        if not cur.isValid():
            b = self._block()
            if b is None:
                return False
            r0, c0 = b[0][0], b[1][0]
        else:
            r0, c0 = cur.row(), cur.column()
        items = []
        for dr, line in enumerate(grid):
            for dc, v in enumerate(line):
                r, c = r0 + dr, c0 + dc
                if r < self.model.rowCount() and c < self.model.columnCount() and v != "" \
                        and self.model.cell_editable(r, c):
                    items.append((r, c, v))
        return self._write_cells(items, "Paste")

    def export_dialog(self):
        path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Export CSV", "spreadsheet.csv", "CSV (*.csv)")
        if path:
            self.export_csv(path)

    def export_csv(self, path):
        """Save the shown rows and columns as a CSV file (comma separated, UTF-8). Returns the path."""
        cols = self.model.cols
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["row"] + [c.name for c in cols])
            for r in range(self.model.rowCount()):
                src = self.model.src(r)
                label = self.model.row_labels[src] if self.model.row_labels is not None else src
                out = [label]
                for c in cols:
                    v = c.value(src)
                    if c.kind == "f" and v is not None:
                        v = round(float(v), 6)
                    out.append("" if v is None else v)
                w.writerow(out)
        self._status(f"Exported {self.model.rowCount()} rows to {path}")
        return path

    # ------------------------------------------------------------ selection in the 3D view
    def select_in_view(self):
        """Select the elements / objects of the selected rows in the 3D view (Edit Mode: vertices, edges, faces)."""
        sel = self.table.selectionModel().selectedIndexes()
        rows = sorted({self.model.src(i.row()) for i in sel})
        if not rows:
            return 0
        if self.mode == "OBJECTS":
            names = [self.model.row_labels[r] for r in rows]
            ob = bpy.context.view_layer.objects.active
            if ob is not None and ob.mode == "POSE":
                for pb in ob.pose.bones:
                    _pb_select(pb, pb.name in names)
            else:
                for o in bpy.context.view_layer.objects:
                    o.select_set(o.name in names)
            bridge.undo_push("Spreadsheet: Select")
            return len(rows)
        ob = self.target_object()
        if ob is None or ob.mode != "EDIT" or ob.type != "MESH":
            return 0
        import bmesh
        bm = bmesh.from_edit_mesh(ob.data)
        seq = {"POINT": bm.verts, "EDGE": bm.edges, "FACE": bm.faces}.get(self.domain)
        if seq is None:
            return 0
        for e in list(bm.verts) + list(bm.edges) + list(bm.faces):
            e.select = False
        seq.ensure_lookup_table()
        for r in rows:
            if r < len(seq):
                seq[r].select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
        bridge.undo_push("Spreadsheet: Select")
        return len(rows)


def _eval_number(text):
    t = str(text).strip().replace(",", ".") if isinstance(text, str) else text
    if not isinstance(t, str):
        return t
    if t.lower() in ("true", "on", "yes"):
        return 1
    if t.lower() in ("false", "off", "no"):
        return 0
    return eval(t, {"__builtins__": {}}, dict(_EVAL_NAMES))


def _convert(value, col, current):
    """A typed / pasted value → the column's type (relative operators use the cell's current value)."""
    k = col.kind
    if k == "s":
        return str(value)
    if k == "e":
        ids = [i for i, _l in col.enum_items]
        if value in ids:
            return value
        for i, label in col.enum_items:
            if str(value).lower() in (i.lower(), label.lower()):
                return i
        raise ValueError(f"{value!r} is not one of {', '.join(ids[:8])}")
    if k == "b":
        if isinstance(value, bool):
            return value
        return bool(float(_eval_number(value)))
    if isinstance(value, str):
        m = re.match(r"^\s*([+\-*/])=\s*(.+)$", value)
        if m:
            if current is None:
                raise ValueError("no value to change")
            x = float(_eval_number(m.group(2)))
            cur = float(current)
            v = {"+": cur + x, "-": cur - x, "*": cur * x, "/": cur / x if x else cur}[m.group(1)]
        else:
            v = float(_eval_number(value))
    else:
        v = float(value)
    return int(round(v)) if k == "i" else v

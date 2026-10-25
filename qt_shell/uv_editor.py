"""UV editor in Qt – the best of Maya's UV Editor and Blender's UV editor.

Maya-like:
- component modes UV / UV Edge / UV Face / UV Shell (1 2 3 4), double click selects a shell,
  pre-selection highlight under the mouse, Shift toggles / Ctrl removes, right click = marking menu,
- display toggles in the toolbar: texture image, dim image, checker map, shaded UVs (front blue, flipped red,
  overlaps darker), distortion colours (area stretch), shell borders, grid with 0–1 tile and labels,
- UV Toolkit on the right: Select, Pin, Transform (move step, rotate 90 / angle, flip, align min / max /
  centre, normalize), Create (projections), Cut and Sew, Unfold / Optimize / Layout, Texel Density (get / set).

Blender-like:
- the UVs and their selection are Blender's own (UV Sync Selection toggle like Blender – on: the mesh
  selection is the UV selection and all faces are shown, off: the UVs of the selected faces),
- Blender's UV operators do the heavy work (unwrap, pack, minimize stretch, stitch, weld, seams …) – they
  run in a UV editor area of the hidden Blender window (the timeline area is switched for a moment),
- G / R / S with X / Y axis, number input, Ctrl = snap to the grid; L selects the shell under the mouse,
  P / Alt+P pin / unpin, Ctrl+I invert, Ctrl+Num+ / - grow / shrink, F frame selection, Home 0–1.

In Object mode the view shows all UVs read-only (any tool switches to Edit mode first).
"""
import math
from contextlib import contextmanager

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, theme

PICK = 9.0               # px
SETTINGS = "QtShell"
MODES = (("VERT", "UV", "UV_VERTEXSEL", "uv.mode_vert"), ("EDGE", "UV Edge", "UV_EDGESEL", "uv.mode_edge"),
         ("FACE", "UV Face", "UV_FACESEL", "uv.mode_face"), ("ISLAND", "UV Shell", "UV_ISLANDSEL", "uv.mode_island"))
C_SEL = QtGui.QColor("#ff9a1f")
C_HOVER = QtGui.QColor("#7fd4ff")
C_PIN = QtGui.QColor("#ff3b3b")
C_SEAM = QtGui.QColor("#ff5050")


def _settings():
    return QtCore.QSettings(SETTINGS, SETTINGS)


def setting(key, default):
    v = _settings().value(f"uv/{key}", default)
    if isinstance(default, bool):
        return v in (True, "true", "1", 1)
    try:
        return type(default)(v)
    except Exception:
        return default


def set_setting(key, value):
    _settings().setValue(f"uv/{key}", value)


def _icon(name):
    from . import blicons
    return blicons.icon(name) if blicons.has(name) else QtGui.QIcon()


def _active_mesh():
    ob = bpy.context.view_layer.objects.active
    if ob is None or ob.type != "MESH":
        return None
    return ob


def find_image(ob):
    mat = ob.active_material if ob is not None else None
    if mat is None or mat.node_tree is None:
        return None
    nodes = mat.node_tree.nodes
    act = nodes.active
    if act is not None and act.bl_idname == "ShaderNodeTexImage" and act.image is not None:
        return act.image
    for n in nodes:
        if n.bl_idname == "ShaderNodeTexImage" and n.image is not None:
            return n.image
    return None


_img_cache = {}


def image_to_qimage(img, max_size=1024):
    try:
        w, h = img.size
    except Exception:
        return None
    if not w or not h:
        return None
    key = (img.name, w, h, img.is_dirty, getattr(img, "generated_type", ""))
    if key in _img_cache:
        return _img_cache[key]
    px = np.empty(w * h * 4, dtype=np.float32)
    try:
        img.pixels.foreach_get(px)
    except Exception:
        return None
    a = px.reshape(h, w, 4)[::-1]
    step = max(1, int(math.ceil(max(w, h) / max_size)))
    a = a[::step, ::step].copy()
    if img.is_float:
        rgb = np.clip(a[..., :3], 0, None)
        a[..., :3] = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1 / 2.4) - 0.055)
    b = np.ascontiguousarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
    hh, ww = b.shape[:2]
    q = QtGui.QImage(b.data, ww, hh, ww * 4, QtGui.QImage.Format_RGBA8888).copy()
    _img_cache.clear()
    _img_cache[key] = q
    return q


_checker = None


def checker_image():
    """Maya-like checker map (8 × 8 per UV tile, numbered columns / rows)."""
    global _checker
    if _checker is None:
        n, s = 8, 64
        img = QtGui.QImage(n * s, n * s, QtGui.QImage.Format_RGB32)
        p = QtGui.QPainter(img)
        f = p.font()
        f.setPixelSize(16)
        f.setBold(True)
        p.setFont(f)
        for i in range(n):
            for j in range(n):
                dark = (i + j) % 2 == 0
                p.fillRect(i * s, j * s, s, s, QtGui.QColor("#3c3c3c") if dark else QtGui.QColor("#d8d8d8"))
                p.setPen(QtGui.QColor("#d8d8d8") if dark else QtGui.QColor("#3c3c3c"))
                p.drawText(QtCore.QRect(i * s, j * s, s, s), QtCore.Qt.AlignCenter, f"{chr(65 + i)}{n - j}")
        p.end()
        _checker = img
    return _checker


# ---------------------------------------------------------------- Blender UV operators
@contextmanager
def uv_context(image=None):
    """A UV editor area of the hidden Blender window for bpy.ops.uv.* (the timeline area for a moment)."""
    found = bridge.ensure_view3d()
    if not found:
        raise RuntimeError("No Blender window.")
    win = found[0]
    area = next((a for a in win.screen.areas if a.type in ("DOPESHEET_EDITOR", "IMAGE_EDITOR", "GRAPH_EDITOR")),
                None)
    if area is None:
        area = next(a for a in win.screen.areas if a.type not in ("VIEW_3D",))
    old = area.ui_type
    try:
        area.ui_type = "UV"
        sp = area.spaces.active
        if image is not None:
            try:
                sp.image = image
            except Exception:
                pass
        region = next(r for r in area.regions if r.type == "WINDOW")
        with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region, space_data=sp):
            yield
    finally:
        try:
            area.ui_type = old
        except Exception:
            pass


def ensure_edit(select_all=False):
    """Tools work in Edit mode – switches the active mesh to it."""
    ob = _active_mesh()
    if ob is None:
        return None
    if ob.mode != "EDIT":
        bridge.run_op("object.mode_set", {"mode": "EDIT"})
        if select_all:
            bridge.run_op("mesh.select_all", {"action": "SELECT"})
    return ob


def run_uv_op(idname, props=None, image=None, undo=None):
    """Runs a bpy.ops.uv.* operator in a UV editor context. Returns the result set."""
    mod, name = idname.split(".", 1)
    op = getattr(getattr(bpy.ops, mod), name)
    try:
        with uv_context(image):
            if not op.poll():
                return {"CANCELLED"}
            res = op("EXEC_DEFAULT", **(props or {}))
    except Exception as ex:
        bridge.log(f"{idname}: {ex}", "ERROR")
        return {"CANCELLED"}
    if "FINISHED" in res:
        bridge.undo_push(undo or idname)
    return res


# ---------------------------------------------------------------- the mesh snapshot
class Snap:
    """UVs of the shown faces + selection, islands, borders, seams, pins (rebuilt when data changes)."""

    def __init__(self):
        self.ob = _active_mesh()
        self.bm = None
        self.uvl = None
        self.editable = False
        self.sync = bool(bpy.context.scene.tool_settings.use_uv_select_sync)
        self.faces = []          # [(face (BMFace|MeshPolygon index), [uv Vector]), …]
        self.loops = []          # [[BMLoop]] (edit mode only)
        self.face_sel = []
        self.vert_sel = []       # [[bool per corner]]
        self.edge_sel = []       # [[bool per corner]] – edge from corner i to i+1
        self.pins = []
        self.island = []         # island id per face
        self.border = []         # [[bool per corner edge]]
        self.seam = []
        self.flipped = []
        self.area3d = []
        self.areauv = []
        if self.ob is None:
            return
        if self.ob.mode == "EDIT":
            self._from_bmesh()
        else:
            self._from_mesh()

    def _from_bmesh(self):
        ob = self.ob
        bm = bmesh.from_edit_mesh(ob.data)
        self.bm = bm
        uvl = bm.loops.layers.uv.active
        self.uvl = uvl
        self.editable = True
        if uvl is None:
            return
        bm.faces.ensure_lookup_table()
        if self.sync:
            faces = [f for f in bm.faces if not f.hide]
        else:
            faces = [f for f in bm.faces if f.select and not f.hide]
        # Blender 5: in sync mode the UV selection can be its own (per face corner) – then it is the one shown
        uv_flags = (not self.sync) or bool(getattr(bm, "uv_select_sync_valid", False))
        mw = ob.matrix_world
        for f in faces:
            ls = list(f.loops)
            self.faces.append((f, [l[uvl].uv.copy() for l in ls]))
            self.loops.append(ls)
            if not uv_flags:
                self.face_sel.append(f.select)
                self.vert_sel.append([l.vert.select for l in ls])
                self.edge_sel.append([l.edge.select for l in ls])
            else:
                self.face_sel.append(bool(getattr(f, "uv_select", False)))
                self.vert_sel.append([bool(getattr(l, "uv_select_vert", False)) for l in ls])
                self.edge_sel.append([bool(getattr(l, "uv_select_edge", False)) for l in ls])
            self.pins.append([l[uvl].pin_uv for l in ls])
            self.seam.append([l.edge.seam for l in ls])
            self.area3d.append(f.calc_area() * (mw.median_scale ** 2))
        self._topology()

    def _from_mesh(self):
        me = self.ob.data
        layer = me.uv_layers.active
        self.uvl = layer
        if layer is None:
            return
        uvd = layer.data
        n = len(me.loops)
        co = np.empty(n * 2, dtype=np.float32)
        uvd.foreach_get("uv", co)
        co = co.reshape(n, 2)
        for p in me.polygons:
            if p.hide:
                continue
            li = list(p.loop_indices)
            self.faces.append((p.index, [Vector(co[i]) for i in li]))
            k = len(li)
            self.face_sel.append(False)
            self.vert_sel.append([False] * k)
            self.edge_sel.append([False] * k)
            self.pins.append([False] * k)
            self.seam.append([False] * k)
            self.area3d.append(p.area)
        self._topology()

    def _topology(self):
        """Islands (faces connected by edges with the same UVs on both sides), borders, flipped faces."""
        n = len(self.faces)
        parent = list(range(n))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        key = {}
        for fi, (_f, uvs) in enumerate(self.faces):
            k = len(uvs)
            verts = self._verts(fi)
            for i in range(k):
                a, b = verts[i], verts[(i + 1) % k]
                ua, ub = uvs[i], uvs[(i + 1) % k]
                ek = (min(a, b), max(a, b))
                e = key.setdefault(ek, [])
                e.append((fi, i, (a, (round(ua.x, 5), round(ua.y, 5))), (b, (round(ub.x, 5), round(ub.y, 5)))))
        self.border = [[True] * len(uvs) for _f, uvs in self.faces]
        for lst in key.values():
            if len(lst) < 2:
                continue
            for x in range(len(lst)):
                for y in range(x + 1, len(lst)):
                    f1, i1, a1, b1 = lst[x]
                    f2, i2, a2, b2 = lst[y]
                    if {a1, b1} == {a2, b2}:          # same UVs at both ends → connected
                        self.border[f1][i1] = False
                        self.border[f2][i2] = False
                        ra, rb = find(f1), find(f2)
                        if ra != rb:
                            parent[ra] = rb
        self.island = [find(i) for i in range(n)]
        for _f, uvs in self.faces:
            a = 0.0
            for i in range(len(uvs)):
                p, q = uvs[i], uvs[(i + 1) % len(uvs)]
                a += p.x * q.y - q.x * p.y
            self.areauv.append(abs(a) / 2)
            self.flipped.append(a < 0)

    def _verts(self, fi):
        if self.loops:
            return [l.vert.index for l in self.loops[fi]]
        me = self.ob.data
        p = me.polygons[self.faces[fi][0]]
        return list(p.vertices)

    # --- selection helpers
    def selected_corners(self, mode):
        """[(fi, ci)] of the UVs a transform moves."""
        out = []
        for fi, (_f, uvs) in enumerate(self.faces):
            if mode in ("FACE", "ISLAND") and self.sync:
                if self.face_sel[fi]:
                    out.extend((fi, ci) for ci in range(len(uvs)))
                continue
            for ci in range(len(uvs)):
                if self.vert_sel[fi][ci]:
                    out.append((fi, ci))
        return out


# ---------------------------------------------------------------- selection writing
def _set_attr_sel(elem, name, value, flush=True):
    """Sets a UV selection flag – with flush the element's own *_set() (which also (de)selects what it contains)."""
    fn = getattr(elem, name + "_set", None) if flush else None
    if fn is not None:
        try:
            fn(value)
            return
        except Exception:
            pass
    try:
        setattr(elem, name, value)
    except Exception:
        pass


def write_selection(snap, items, mode, action):
    """items: [(fi, ci)] for VERT / EDGE (corner = edge start), [fi] for FACE / ISLAND.
    action SET / ADD / SUB / TOGGLE."""
    bm = snap.bm
    if bm is None:
        return
    sync = snap.sync
    if action == "SET":
        if sync:
            for f in bm.faces:
                f.select_set(False)
            for e in bm.edges:
                e.select_set(False)
            for v in bm.verts:
                v.select_set(False)
        else:
            for ls in snap.loops:
                for l in ls:
                    _set_attr_sel(l, "uv_select_vert", False)
                    _set_attr_sel(l, "uv_select_edge", False)
            for f, _u in snap.faces:
                _set_attr_sel(f, "uv_select", False)
    uvl = snap.uvl
    shown = {f.index for f, _u in snap.faces}

    def sticky(fi, ci):
        """All corners at the same mesh vertex and the same UV (Blender's Shared Location)."""
        l = snap.loops[fi][ci]
        uv = l[uvl].uv
        return [ll for ll in l.vert.link_loops if ll.face.index in shown and (ll[uvl].uv - uv).length < 1e-5]

    def state(fi, ci=None):
        if mode in ("FACE", "ISLAND"):
            return snap.face_sel[fi]
        if mode == "EDGE":
            return snap.edge_sel[fi][ci]
        return snap.vert_sel[fi][ci]

    for it in items:
        if mode in ("FACE", "ISLAND"):
            fi = it
            on = (not state(fi)) if action == "TOGGLE" else action != "SUB"
            f = snap.faces[fi][0]
            if sync:
                f.select_set(on)
            else:
                _set_attr_sel(f, "uv_select", on)
                for ci, l in enumerate(snap.loops[fi]):
                    for ll in sticky(fi, ci):
                        _set_attr_sel(ll, "uv_select_vert", on)
                    _set_attr_sel(l, "uv_select_edge", on)
            continue
        fi, ci = it
        on = (not state(fi, ci)) if action == "TOGGLE" else action != "SUB"
        l = snap.loops[fi][ci]
        if mode == "EDGE":
            if sync:
                l.edge.select_set(on)
            else:
                _set_attr_sel(l, "uv_select_edge", on)
                for c in (ci, (ci + 1) % len(snap.loops[fi])):
                    for ll in sticky(fi, c):
                        _set_attr_sel(ll, "uv_select_vert", on)
        else:
            if sync:
                l.vert.select_set(on)
            else:
                for ll in sticky(fi, ci):
                    _set_attr_sel(ll, "uv_select_vert", on)
    if sync:
        bm.select_flush_mode()
        try:
            bm.uv_select_sync_from_mesh()       # Blender 5: the UV selection follows the mesh selection
        except Exception:
            pass
    else:
        # edges / faces follow their corners (Blender's flush)
        for fi, ls in enumerate(snap.loops):
            k = len(ls)
            allv = True
            for ci, l in enumerate(ls):
                v1 = bool(getattr(l, "uv_select_vert", False))
                v2 = bool(getattr(ls[(ci + 1) % k], "uv_select_vert", False))
                if mode != "EDGE":
                    _set_attr_sel(l, "uv_select_edge", v1 and v2, flush=False)
                allv = allv and v1
            if mode not in ("FACE", "ISLAND"):
                _set_attr_sel(snap.faces[fi][0], "uv_select", allv, flush=False)
    try:
        bmesh.update_edit_mesh(snap.ob.data, loop_triangles=False, destructive=False)
    except Exception:
        pass


# ---------------------------------------------------------------- canvas
class UVCanvas(QtWidgets.QWidget):
    status = QtCore.Signal(str)
    changed = QtCore.Signal()

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setMinimumSize(200, 200)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.scale = 300.0
        self.offset = QtCore.QPointF(60, 360)   # position of UV (0,0) in the widget
        self._snap = None
        self._pan = None
        self._zoom = None
        self._press = None
        self._box = None
        self._modal = None
        self._fitted = False
        self._hover = None
        self._mouse = None
        self._numeric = ""

    # --- settings shortcuts
    @property
    def mode(self):
        return self.editor.mode

    def flag(self, key, default=True):
        return setting(key, default)

    # --- coordinate conversion
    def to_screen(self, u, v):
        return QtCore.QPointF(self.offset.x() + u * self.scale, self.offset.y() - v * self.scale)

    def to_uv(self, p):
        return ((p.x() - self.offset.x()) / self.scale, (self.offset.y() - p.y()) / self.scale)

    def fit(self, lo=(0.0, 0.0), hi=(1.0, 1.0)):
        w = max(hi[0] - lo[0], 1e-4)
        h = max(hi[1] - lo[1], 1e-4)
        s = min((self.width() - 60) / w, (self.height() - 60) / h)
        self.scale = max(min(s, 50000), 20)
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        self.offset = QtCore.QPointF(self.width() / 2 - cx * self.scale, self.height() / 2 + cy * self.scale)
        self.update()

    def frame_selected(self):
        s = self.snap()
        pts = [s.faces[fi][1][ci] for fi, ci in s.selected_corners(self.mode)] if s else []
        if not pts and s:
            pts = [uv for _f, uvs in s.faces for uv in uvs]
        if not pts:
            self.fit()
            return
        lo = (min(p.x for p in pts), min(p.y for p in pts))
        hi = (max(p.x for p in pts), max(p.y for p in pts))
        pad = max(hi[0] - lo[0], hi[1] - lo[1]) * 0.08 + 0.01
        self.fit((lo[0] - pad, lo[1] - pad), (hi[0] + pad, hi[1] + pad))

    # --- data
    def invalidate(self):
        self._snap = None
        self.update()

    def snap(self):
        if self._snap is None or self._snap.ob is not _active_mesh():
            try:
                self._snap = Snap()
            except ReferenceError:
                self._snap = None
        return self._snap

    # --- drawing
    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#262626"))
        if not self._fitted and self.width() > 50:
            self._fitted = True
            self.fit()
        try:
            s = self.snap()
        except Exception as ex:
            s = None
            bridge.log(f"UV editor: {ex}", "WARNING")
        self._paint_background(p, s)
        if s is None or s.ob is None:
            self._hint(p, "Select a mesh object.")
            p.end()
            return
        if s.uvl is None:
            self._hint(p, "The mesh has no UV map – Create → Unwrap / Smart UV Project, or add a UV map above.")
            p.end()
            return
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        self._paint_faces(p, s)
        self._paint_edges(p, s)
        self._paint_verts(p, s)
        if self._box:
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1, QtCore.Qt.DashLine))
            p.setBrush(QtGui.QColor(255, 255, 255, 20))
            p.drawRect(QtCore.QRectF(self._box[0], self._box[1]).normalized())
        self._paint_info(p, s)
        p.end()

    def _paint_background(self, p, s):
        sc = self.scale
        # grid: subdivisions that stay readable when zooming (Maya-like), 0–1 tile brighter
        step = 10 ** math.floor(math.log10(max(60 / sc, 1e-6)))
        if step * sc < 25:
            step *= 5 if step * sc * 5 >= 25 else 10
        if not self.flag("grid", True):
            step = None
        u0, v1 = self.to_uv(QtCore.QPointF(0, 0))
        u1, v0 = self.to_uv(QtCore.QPointF(self.width(), self.height()))
        o = self.to_screen(0, 1)
        tile = QtCore.QRectF(o.x(), o.y(), sc, sc)
        p.fillRect(tile, QtGui.QColor("#303030"))
        ob = self._snap.ob if s is not None else None
        img = self.editor.current_image(ob)
        if self.flag("checker", False):
            p.drawImage(tile, checker_image())
        elif img is not None and self.flag("image", True):
            q = image_to_qimage(img)
            if q is not None:
                p.drawImage(tile, q)
                if self.flag("dim", False):
                    p.fillRect(tile, QtGui.QColor(0, 0, 0, 120))
        if step:
            pen_minor = QtGui.QPen(QtGui.QColor(255, 255, 255, 18), 1)
            pen_unit = QtGui.QPen(QtGui.QColor(255, 255, 255, 55), 1)
            i = math.floor(u0 / step)
            while i * step <= u1:
                u = i * step
                x = self.to_screen(u, 0).x()
                p.setPen(pen_unit if abs(u - round(u)) < 1e-9 else pen_minor)
                p.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, self.height()))
                i += 1
            j = math.floor(v0 / step)
            while j * step <= v1:
                v = j * step
                y = self.to_screen(0, v).y()
                p.setPen(pen_unit if abs(v - round(v)) < 1e-9 else pen_minor)
                p.drawLine(QtCore.QPointF(0, y), QtCore.QPointF(self.width(), y))
                j += 1
            # axis labels (left and bottom edge)
            p.setPen(QtGui.QColor("#8c8c8c"))
            f = p.font()
            f.setPixelSize(theme.fs(10))
            p.setFont(f)
            lab = step * (2 if step * sc < 50 else 1)
            i = math.floor(u0 / lab)
            while i * lab <= u1:
                u = i * lab
                x = self.to_screen(u, 0).x()
                p.drawText(QtCore.QPointF(x + 2, self.height() - 22), f"{u:g}")
                i += 1
            j = math.floor(v0 / lab)
            while j * lab <= v1:
                v = j * lab
                y = self.to_screen(0, v).y()
                p.drawText(QtCore.QPointF(3, y - 2), f"{v:g}")
                j += 1
        p.setPen(QtGui.QPen(QtGui.QColor("#9a9a9a"), 1.4))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRect(tile)

    def _pts(self, uvs):
        return [self.to_screen(uv.x, uv.y) for uv in uvs]

    def _paint_faces(self, p, s):
        shaded = self.flag("shaded", False)
        dist = self.flag("distortion", False)
        tot3 = sum(s.area3d) or 1.0
        totuv = sum(s.areauv) or 1.0
        hover_face = self._hover[1] if self._hover and self._hover[0] in ("FACE", "ISLAND") else None
        hover_island = s.island[hover_face] if hover_face is not None and self._hover[0] == "ISLAND" else None
        p.setPen(QtCore.Qt.NoPen)
        for fi, (_f, uvs) in enumerate(s.faces):
            poly = QtGui.QPolygonF(self._pts(uvs))
            if dist:
                r = (s.areauv[fi] / totuv) / max(s.area3d[fi] / tot3, 1e-12)
                t = min(abs(math.log2(max(r, 1e-6))) / 1.5, 1.0)
                col = QtGui.QColor.fromHsvF((0.66 * (1 - t)), 0.85, 0.9, 0.55)
                p.setBrush(col)
                p.drawPolygon(poly)
            elif shaded:
                p.setBrush(QtGui.QColor(230, 60, 60, 90) if s.flipped[fi] else QtGui.QColor(70, 120, 230, 70))
                p.drawPolygon(poly)
            if s.editable and s.face_sel[fi] and (self.mode in ("FACE", "ISLAND") or all(s.vert_sel[fi])):
                p.setBrush(QtGui.QColor(255, 150, 40, 70))
                p.drawPolygon(poly)
            elif hover_face is not None and (fi == hover_face or (hover_island is not None
                                                                  and s.island[fi] == hover_island)):
                p.setBrush(QtGui.QColor(127, 212, 255, 45))
                p.drawPolygon(poly)

    def _paint_edges(self, p, s):
        normal = QtGui.QPainterPath()
        border = QtGui.QPainterPath()
        seam = QtGui.QPainterPath()
        sel = QtGui.QPainterPath()
        borders = self.flag("borders", True)
        for fi, (_f, uvs) in enumerate(s.faces):
            pts = self._pts(uvs)
            k = len(pts)
            for i in range(k):
                a, b = pts[i], pts[(i + 1) % k]
                if s.editable and s.edge_sel[fi][i] and self.mode != "FACE":
                    path = sel
                elif s.seam[fi][i]:
                    path = seam
                elif borders and s.border[fi][i]:
                    path = border
                else:
                    path = normal
                path.moveTo(a)
                path.lineTo(b)
        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 120), 3))
        for path in (normal, border, seam, sel):
            p.drawPath(path)
        p.setPen(QtGui.QPen(QtGui.QColor("#cfcfcf") if s.editable else QtGui.QColor("#9a9a9a"), 1))
        p.drawPath(normal)
        p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2.2))
        p.drawPath(border)
        p.setPen(QtGui.QPen(C_SEAM, 2.2))
        p.drawPath(seam)
        p.setPen(QtGui.QPen(C_SEL, 2.4))
        p.drawPath(sel)
        h = self._hover
        if h and h[0] == "EDGE":
            fi, ci = h[1]
            uvs = s.faces[fi][1]
            p.setPen(QtGui.QPen(C_HOVER, 3))
            p.drawLine(self.to_screen(*uvs[ci]), self.to_screen(*uvs[(ci + 1) % len(uvs)]))

    def _paint_verts(self, p, s):
        if not s.editable:
            return
        show_all = self.mode == "VERT"
        normal, selected, pinned = [], [], []
        for fi, (_f, uvs) in enumerate(s.faces):
            for ci, uv in enumerate(uvs):
                pt = self.to_screen(uv.x, uv.y)
                if s.pins[fi][ci]:
                    pinned.append(pt)
                if s.vert_sel[fi][ci] and self.mode in ("VERT", "EDGE"):
                    selected.append(pt)
                elif show_all:
                    normal.append(pt)
        p.setPen(QtGui.QPen(QtGui.QColor("#101010"), 4.5, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        p.drawPoints(normal)
        p.setPen(QtGui.QPen(QtGui.QColor("#e0e0e0"), 2.5, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        p.drawPoints(normal)
        p.setPen(QtGui.QPen(C_PIN, 7, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        p.drawPoints(pinned)
        p.setPen(QtGui.QPen(C_SEL, 5.5, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        p.drawPoints(selected)
        h = self._hover
        if h and h[0] == "VERT":
            fi, ci = h[1]
            uv = s.faces[fi][1][ci]
            p.setPen(QtGui.QPen(C_HOVER, 7, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
            p.drawPoint(self.to_screen(uv.x, uv.y))

    def _paint_info(self, p, s):
        f = p.font()
        f.setPixelSize(theme.fs(11))
        p.setFont(f)
        p.setPen(QtGui.QColor("#d0d0d0"))
        if self._modal:
            text = self._modal_text()
        else:
            parts = []
            img = self.editor.current_image(s.ob)
            parts.append(img.name if img is not None else "no texture")
            parts.append(s.uvl.name if hasattr(s.uvl, "name") else "")
            n_sel = len(s.selected_corners(self.mode)) if s.editable else 0
            parts.append(f"{len(s.faces)} faces · {len(set(s.island))} shells")
            if s.editable:
                parts.append(f"{n_sel} UVs selected")
            if not s.editable:
                parts.append("preview only – a tool or Tab switches to Edit mode")
            if self._mouse is not None:
                u, v = self.to_uv(self._mouse)
                parts.append(f"U {u:.3f}  V {v:.3f}")
            text = "   ·   ".join(x for x in parts if x)
        p.drawText(10, self.height() - 8, text)

    def _hint(self, p, text):
        p.setPen(QtGui.QColor("#aaaaaa"))
        p.drawText(self.rect(), QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap, text)

    # --- picking
    def pick(self, pos, mode=None):
        """(kind, item) under pos: VERT (fi, ci), EDGE (fi, ci), FACE fi, ISLAND fi – or None."""
        s = self.snap()
        if s is None or not s.faces:
            return None
        mode = mode or self.mode
        x, y = pos.x(), pos.y()
        if mode == "VERT":
            best, bd = None, PICK * theme.ui_scale
            for fi, (_f, uvs) in enumerate(s.faces):
                for ci, uv in enumerate(uvs):
                    q = self.to_screen(uv.x, uv.y)
                    d = math.hypot(q.x() - x, q.y() - y)
                    if d < bd:
                        best, bd = (fi, ci), d
            return ("VERT", best) if best else None
        if mode == "EDGE":
            best, bd = None, PICK * theme.ui_scale
            for fi, (_f, uvs) in enumerate(s.faces):
                pts = self._pts(uvs)
                k = len(pts)
                for ci in range(k):
                    d = _seg_dist(x, y, pts[ci], pts[(ci + 1) % k])
                    if d < bd:
                        best, bd = (fi, ci), d
            return ("EDGE", best) if best else None
        pt = QtCore.QPointF(x, y)
        for fi in range(len(s.faces) - 1, -1, -1):           # the last drawn wins
            if QtGui.QPolygonF(self._pts(s.faces[fi][1])).containsPoint(pt, QtCore.Qt.OddEvenFill):
                return (mode, fi)
        return None

    def _items(self, kind, item):
        """Selection items for a picked element (an island expands to its faces)."""
        s = self.snap()
        if kind == "ISLAND":
            isl = s.island[item]
            return [fi for fi in range(len(s.faces)) if s.island[fi] == isl]
        return [item]

    def select_at(self, pos, action):
        s = self.snap()
        if s is None or not s.editable or s.uvl is None:
            self.status.emit("UVs can be selected in Edit mode (Tab).")
            return
        hit = self.pick(pos)
        if hit is None:
            if action == "SET":
                write_selection(s, [], self.mode, "SET")
                self._after_select()
            return
        write_selection(s, self._items(*hit), self._mode_for(hit[0]), action)
        self._after_select()

    def _mode_for(self, kind):
        return kind

    def select_island_at(self, pos, action="ADD"):
        s = self.snap()
        if s is None or not s.editable:
            return
        hit = self.pick(pos, "FACE") or self.pick(pos, "EDGE") or self.pick(pos, "VERT")
        if hit is None:
            return
        fi = hit[1] if hit[0] == "FACE" else hit[1][0]
        isl = s.island[fi]
        faces = [i for i in range(len(s.faces)) if s.island[i] == isl]
        if self.mode in ("FACE", "ISLAND"):
            write_selection(s, faces, "FACE", action)
        else:
            write_selection(s, [(i, c) for i in faces for c in range(len(s.faces[i][1]))], "VERT", action)
        self._after_select()

    def select_box(self, rect, action):
        s = self.snap()
        if s is None or not s.editable or s.uvl is None:
            return
        mode = self.mode
        items = []
        if mode == "VERT":
            for fi, (_f, uvs) in enumerate(s.faces):
                for ci, uv in enumerate(uvs):
                    if rect.contains(self.to_screen(uv.x, uv.y)):
                        items.append((fi, ci))
        elif mode == "EDGE":
            for fi, (_f, uvs) in enumerate(s.faces):
                pts = self._pts(uvs)
                for ci in range(len(pts)):
                    if rect.contains(pts[ci]) and rect.contains(pts[(ci + 1) % len(pts)]):
                        items.append((fi, ci))
        else:
            for fi, (_f, uvs) in enumerate(s.faces):
                c = sum(uvs, Vector((0, 0))) / len(uvs)
                if rect.contains(self.to_screen(c.x, c.y)):
                    items.append(fi)
            if mode == "ISLAND":
                isl = {s.island[fi] for fi in items}
                items = [fi for fi in range(len(s.faces)) if s.island[fi] in isl]
        write_selection(s, items, mode, action if action in ("SET", "ADD", "SUB") else "ADD")
        self._after_select()

    def select_all(self, action="SELECT"):
        s = self.snap()
        if s is None or not s.editable or s.uvl is None:
            return
        mode = "FACE" if self.mode in ("FACE", "ISLAND") else "VERT"
        if mode == "FACE":
            items = list(range(len(s.faces)))
        else:
            items = [(fi, ci) for fi in range(len(s.faces)) for ci in range(len(s.faces[fi][1]))]
        if action == "SELECT":
            write_selection(s, items, mode, "SET")
        elif action == "DESELECT":
            write_selection(s, [], mode, "SET")
        else:
            write_selection(s, items, mode, "TOGGLE")
        self._after_select()

    def select_flipped(self):
        s = self.snap()
        if s is None or not s.editable:
            return
        write_selection(s, [fi for fi in range(len(s.faces)) if s.flipped[fi]], "FACE", "SET")
        self._after_select()

    def convert_selection(self, to):
        """Maya's Convert Selection: to UVs / Edges / Faces / Shell."""
        s = self.snap()
        if s is None or not s.editable:
            return
        cur = s.selected_corners("VERT") if self.mode in ("VERT", "EDGE") else \
            [(fi, ci) for fi in range(len(s.faces)) if s.face_sel[fi] for ci in range(len(s.faces[fi][1]))]
        faces = sorted({fi for fi, _c in cur})
        if to == "VERT":
            write_selection(s, cur, "VERT", "SET")
        elif to == "EDGE":
            write_selection(s, cur, "VERT", "SET")
        elif to == "FACE":
            full = [fi for fi in faces if all((fi, c) in set(cur) for c in range(len(s.faces[fi][1])))] \
                if self.mode in ("VERT", "EDGE") else faces
            write_selection(s, full or faces, "FACE", "SET")
        else:
            isl = {s.island[fi] for fi in faces}
            write_selection(s, [fi for fi in range(len(s.faces)) if s.island[fi] in isl], "FACE", "SET")
        self.editor.set_mode("ISLAND" if to == "ISLAND" else to)
        self._after_select()

    def _after_select(self):
        bridge.undo_push("Select UVs")
        self._snap = None
        self.changed.emit()
        self.update()

    # --- G / R / S
    def start_modal(self, kind, start=None, drag=False):
        """G / R / S – drag: started by dragging with the mouse, releasing the button confirms."""
        s = self.snap()
        if s is None or not s.editable or s.uvl is None:
            self.status.emit("UVs can be edited in Edit mode (Tab).")
            return
        corners = s.selected_corners(self.mode)
        if not corners:
            self.status.emit("No UVs are selected.")
            return
        uvl = s.uvl
        pts = []
        seen = set()
        for fi, ci in corners:
            l = s.loops[fi][ci]
            key = (s.faces[fi][0].index, ci)
            if key in seen:
                continue
            seen.add(key)
            # keep indices, not BMLoop references: the edit BMesh can be rebuilt between mouse
            # events (viewport redraw), the old references then write into a dead copy
            pts.append((key, l[uvl].uv.copy()))
        lo = Vector((min(uv.x for _l, uv in pts), min(uv.y for _l, uv in pts)))
        hi = Vector((max(uv.x for _l, uv in pts), max(uv.y for _l, uv in pts)))
        pivot = (lo + hi) / 2
        self._modal = {"kind": kind, "pts": pts, "pivot": pivot, "uvl": uvl, "ob": s.ob,
                       "start": QtCore.QPointF(start) if start is not None else
                       QtCore.QPointF(self.mapFromGlobal(QtGui.QCursor.pos())), "axis": None,
                       "value": None, "drag": drag}
        self._numeric = ""
        self.grabMouse()
        self.setFocus()

    def _modal_text(self):
        m = self._modal
        names = {"G": "Move UV", "R": "Rotate UV", "S": "Scale UV"}
        v = m["value"]
        if isinstance(v, Vector):
            v = f"{v.x:.4f}, {v.y:.4f}"
        elif isinstance(v, float):
            v = f"{math.degrees(v):.1f}°" if m["kind"] == "R" else f"{v:.3f}"
        ax = f" ({'U' if m['axis'] == 'X' else 'V'})" if m["axis"] else ""
        num = f"   [{self._numeric}]" if self._numeric else ""
        return (f"{names[m['kind']]}{ax}: {v or ''}{num}   X / Y axis · number + Enter · Ctrl snap · "
                "LMB / Enter confirm · RMB / Esc cancel")

    def _modal_update(self, pos):
        m = self._modal
        piv = m["pivot"]
        ps = self.to_screen(piv.x, piv.y)
        st = m["start"]
        snapping = bool(QtWidgets.QApplication.queryKeyboardModifiers() & QtCore.Qt.ControlModifier)
        num = None
        if self._numeric not in ("", "-", ".", "-."):
            try:
                num = float(self._numeric)
            except ValueError:
                num = None
        out = []
        if m["kind"] == "G":
            if num is not None:
                dv = Vector((num, 0)) if m["axis"] != "Y" else Vector((0, num))
            else:
                dv = Vector(((pos.x() - st.x()) / self.scale, -(pos.y() - st.y()) / self.scale))
                if snapping:
                    step = self._grid_step()
                    dv = Vector((round(dv.x / step) * step, round(dv.y / step) * step))
            if m["axis"] == "X":
                dv.y = 0
            elif m["axis"] == "Y":
                dv.x = 0
            m["value"] = dv
            out = [uv + dv for _l, uv in m["pts"]]
        elif m["kind"] == "R":
            if num is not None:
                ang = math.radians(num)
            else:
                a0 = math.atan2(-(st.y() - ps.y()), st.x() - ps.x())
                a1 = math.atan2(-(pos.y() - ps.y()), pos.x() - ps.x())
                ang = a1 - a0
                if snapping:
                    inc = math.radians(15)
                    ang = round(ang / inc) * inc
            m["value"] = ang
            c, sn = math.cos(ang), math.sin(ang)
            for _l, uv in m["pts"]:
                d = uv - piv
                out.append(Vector((piv.x + d.x * c - d.y * sn, piv.y + d.x * sn + d.y * c)))
        else:
            if num is not None:
                fac = num
            else:
                d0 = max(math.hypot(st.x() - ps.x(), st.y() - ps.y()), 1.0)
                fac = math.hypot(pos.x() - ps.x(), pos.y() - ps.y()) / d0
                if snapping:
                    fac = round(fac * 10) / 10
            m["value"] = fac
            fx = fac if m["axis"] in (None, "X") else 1.0
            fy = fac if m["axis"] in (None, "Y") else 1.0
            out = [Vector((piv.x + (uv.x - piv.x) * fx, piv.y + (uv.y - piv.y) * fy)) for _l, uv in m["pts"]]
        self._write([(l, uv) for (l, _o), uv in zip(m["pts"], out)])
        self._snap = None
        self.update()

    def _grid_step(self):
        step = 10 ** math.floor(math.log10(max(60 / self.scale, 1e-6)))
        if step * self.scale < 25:
            step *= 5 if step * self.scale * 5 >= 25 else 10
        return step

    def _write(self, pairs):
        m = self._modal
        try:
            me = m["ob"].data
            bm = bmesh.from_edit_mesh(me)
            uvl = bm.loops.layers.uv.active
            if uvl is None:
                return
            bm.faces.ensure_lookup_table()
            faces = bm.faces
            for (fidx, ci), uv in pairs:
                faces[fidx].loops[ci][uvl].uv = uv
            bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
        except (ReferenceError, IndexError, ValueError):
            pass

    def _modal_end(self, confirm):
        m = self._modal
        self._modal = None
        self.releaseMouse()
        if not confirm:
            self._write([(l, uv) for l, uv in m["pts"]])
        else:
            bridge.undo_push({"G": "Move UVs", "R": "Rotate UVs", "S": "Scale UVs"}[m["kind"]])
        self._snap = None
        self.changed.emit()
        self.update()

    # --- events
    def enterEvent(self, ev):
        fw = QtWidgets.QApplication.focusWidget()
        if not (isinstance(fw, QtWidgets.QLineEdit) and fw.text()):
            self.setFocus()
            from . import app as _app
            _app.hover_activate(self)      # floating dock = separate window; never over other windows
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = None
        self._mouse = None
        self.update()
        super().leaveEvent(ev)

    def wheelEvent(self, ev):
        self._zoom_at(ev.position(), 1.15 ** (ev.angleDelta().y() / 120.0))

    def _zoom_at(self, pos, f):
        u, v = self.to_uv(pos)
        self.scale = min(max(self.scale * f, 20), 50000)
        self.offset += pos - self.to_screen(u, v)
        self.update()

    def _is_selected(self, hit):
        s = self.snap()
        kind, item = hit
        if kind in ("FACE", "ISLAND"):
            return s.face_sel[item]
        fi, ci = item
        return s.edge_sel[fi][ci] if kind == "EDGE" else s.vert_sel[fi][ci]

    def mousePressEvent(self, ev):
        self.setFocus()
        if self._modal:
            if not self._modal.get("drag"):
                self._modal_end(ev.button() == QtCore.Qt.LeftButton)
            elif ev.button() == QtCore.Qt.RightButton:
                self._modal_end(False)          # right click cancels a drag (Blender)
            return
        alt = bool(ev.modifiers() & QtCore.Qt.AltModifier)
        self._press_hit = None
        if ev.button() == QtCore.Qt.MiddleButton:
            from . import keymap
            if keymap.nav_scheme() == "MAYA" and not alt:
                # Maya: middle drag moves the selected UVs (Alt + middle pans)
                self._mmb_move = ev.position()
            else:
                self._pan = ev.position()
        elif ev.button() == QtCore.Qt.RightButton and alt:      # Maya: Alt+RMB zoom
            self._zoom = ev.position()
        elif ev.button() == QtCore.Qt.RightButton:
            self.editor.marking_menu(ev.globalPosition().toPoint(), ev.position())
        elif ev.button() == QtCore.Qt.LeftButton:
            self._press = ev.position()
            s = self.snap()
            if s is not None and s.editable and s.uvl is not None:
                self._press_hit = self.pick(ev.position())      # dragging an element moves it (tweak)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton and not self._modal:
            add = bool(ev.modifiers() & (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier))
            self.select_island_at(ev.position(), "ADD" if add else "SET")   # Maya: double click = shell
            self._press = None
            return
        super().mouseDoubleClickEvent(ev)

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        self._mouse = pos
        if self._modal:
            self._modal_update(pos)
            return
        if getattr(self, "_mmb_move", None) is not None:
            if (pos - self._mmb_move).manhattanLength() > 3:
                start = self._mmb_move
                self._mmb_move = None
                self.start_modal("G", start=start, drag=True)
                if self._modal:
                    self._modal_update(pos)
            return
        if self._pan is not None:
            self.offset += pos - self._pan
            self._pan = pos
            self.update()
        elif self._zoom is not None:
            d = (pos.x() - self._zoom.x()) - (pos.y() - self._zoom.y())
            self._zoom_at(self.rect().center().toPointF(), 1.01 ** d)
            self._zoom = pos
        elif self._press is not None and (pos - self._press).manhattanLength() > 5:
            hit = getattr(self, "_press_hit", None)
            if hit is not None and self._box is None:
                # drag on a UV / edge / face / shell: select it (if it isn't) and move the selection
                mods = QtWidgets.QApplication.keyboardModifiers()
                if not self._is_selected(hit):
                    add = bool(mods & (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier))
                    write_selection(self.snap(), self._items(*hit), hit[0], "ADD" if add else "SET")
                    self._snap = None
                start = self._press
                self._press = None
                self._press_hit = None
                self.start_modal("G", start=start, drag=True)
                if self._modal:
                    self._modal_update(pos)
                return
            self._box = (self._press, pos)
            self.update()
        else:
            s = self._snap
            if s is not None and s.editable and sum(len(u) for _f, u in s.faces) < 30000:
                h = self.pick(pos)
                if h != self._hover:
                    self._hover = h
            self.update()

    def mouseReleaseEvent(self, ev):
        if self._modal and self._modal.get("drag"):
            self._modal_end(True)
            return
        if ev.button() == QtCore.Qt.MiddleButton:
            self._pan = None
            self._mmb_move = None
            return
        if ev.button() == QtCore.Qt.RightButton:
            self._zoom = None
            return
        if ev.button() == QtCore.Qt.LeftButton and self._press is not None:
            mods = ev.modifiers()
            # Maya: Shift toggles, Ctrl removes, Ctrl+Shift adds · Blender: Shift extends
            if mods & QtCore.Qt.ControlModifier and mods & QtCore.Qt.ShiftModifier:
                action = "ADD"
            elif mods & QtCore.Qt.ControlModifier:
                action = "SUB"
            elif mods & QtCore.Qt.ShiftModifier:
                action = "TOGGLE"
            else:
                action = "SET"
            if self._box:
                rect = QtCore.QRectF(self._box[0], self._box[1]).normalized()
                self._box = None
                self.select_box(rect, "ADD" if action == "TOGGLE" else action)
            else:
                self.select_at(ev.position(), action)
            self._press = None
            self._press_hit = None

    def keyPressEvent(self, ev):
        k = ev.key()
        K = QtCore.Qt
        if self._modal:
            text = ev.text()
            if k == K.Key_Escape:
                self._modal_end(False)
            elif k in (K.Key_Return, K.Key_Enter):
                self._modal_end(True)
            elif k in (K.Key_X, K.Key_Y, K.Key_U, K.Key_V):
                ax = "X" if k in (K.Key_X, K.Key_U) else "Y"
                self._modal["axis"] = None if self._modal["axis"] == ax else ax
                self._modal_update(QtCore.QPointF(self.mapFromGlobal(QtGui.QCursor.pos())))
            elif k == K.Key_Backspace:
                self._numeric = self._numeric[:-1]
                self._modal_update(QtCore.QPointF(self.mapFromGlobal(QtGui.QCursor.pos())))
            elif k == K.Key_Control:
                self._modal_update(QtCore.QPointF(self.mapFromGlobal(QtGui.QCursor.pos())))
            elif text and text in "0123456789.-":
                self._numeric += text
                self._modal_update(QtCore.QPointF(self.mapFromGlobal(QtGui.QCursor.pos())))
            return
        from . import keymap
        names = keymap.event_names(ev)

        def H(aid):
            return keymap.hit(aid, ev, names)
        ed = self.editor
        if H("uv.move"):
            self.start_modal("G")
        elif H("uv.rotate"):
            self.start_modal("R")
        elif H("uv.scale"):
            self.start_modal("S")
        elif H("uv.deselect_all"):
            self.select_all("DESELECT")
        elif H("uv.select_all"):
            self.select_all("SELECT")
        elif H("uv.select_invert"):
            self.select_all("INVERT")
        elif H("uv.fit"):
            self.fit()
        elif H("uv.frame_selected"):
            self.frame_selected()
        elif H("uv.select_linked"):
            self.select_island_at(self.mapFromGlobal(QtGui.QCursor.pos()).toPointF(), "ADD")
        elif H("uv.select_more"):
            ed.tool("uv.select_more")
        elif H("uv.select_less"):
            ed.tool("uv.select_less")
        elif H("uv.pin"):
            ed.tool("uv.pin", {"clear": False})
        elif H("uv.unpin"):
            ed.tool("uv.pin", {"clear": True})
        elif H("uv.unwrap"):
            ed.unwrap()
        elif H("uv.stitch"):
            ed.tool("uv.stitch")
        elif H("uv.weld"):
            ed.tool("uv.weld")
        else:
            for mode, _l, _i, aid in MODES:
                if H(aid):
                    ed.set_mode(mode)
                    return
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if self._modal and ev.key() == QtCore.Qt.Key_Control and not ev.isAutoRepeat():
            QtCore.QTimer.singleShot(0, lambda: self._modal and self._modal_update(
                QtCore.QPointF(self.mapFromGlobal(QtGui.QCursor.pos()))))
            return
        super().keyReleaseEvent(ev)

    def focusNextPrevChild(self, _n):
        return False


def _seg_dist(x, y, a, b):
    ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
    return math.hypot(x - (ax + t * dx), y - (ay + t * dy))


# ---------------------------------------------------------------- the UV Toolkit (Maya) panel
# ---------------------------------------------------------------- Python tooltips
PY = "qt_shell.api.uv_editor()"


class _Val:
    """An argument read from a toolkit field when the button is clicked (shown as <field> in the tooltip)."""

    def __init__(self, attr, mul=1):
        self.attr = attr
        self.mul = mul

    def get(self, editor):
        return getattr(editor, self.attr).value() * self.mul

    def __repr__(self):
        return f"-<{self.attr}>" if self.mul == -1 else (f"<{self.attr}>" if self.mul else "0")


def _resolve(editor, v):
    if isinstance(v, _Val):
        return v.get(editor)
    if isinstance(v, dict):
        return {k: _resolve(editor, x) for k, x in v.items()}
    return v


def _pytag(w, code):
    from . import pytips
    pytips.tag(w, code)


def _args(args):
    return ", ".join(repr(a) for a in args)


class _Section(QtWidgets.QWidget):
    def __init__(self, title, parent, opened=True):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, theme.px(4))
        lay.setSpacing(theme.px(2))
        self.btn = QtWidgets.QToolButton(self)
        self.btn.setText(title)
        self.btn.setCheckable(True)
        key = "toolkit_" + title.lower().replace(" ", "_").replace("&", "")
        self.key = key
        self.btn.setChecked(setting(key, opened))
        self.btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.btn.setArrowType(QtCore.Qt.DownArrow if self.btn.isChecked() else QtCore.Qt.RightArrow)
        self.btn.setStyleSheet("QToolButton { font-weight: bold; border: none; }")
        self.btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.btn.toggled.connect(self._toggle)
        lay.addWidget(self.btn)
        self.body = QtWidgets.QWidget(self)
        self.grid = QtWidgets.QGridLayout(self.body)
        self.grid.setContentsMargins(theme.px(6), 0, 0, 0)
        self.grid.setSpacing(theme.px(2))
        self.body.setVisible(self.btn.isChecked())
        lay.addWidget(self.body)
        self._row = 0
        self._col = 0

    def _toggle(self, on):
        set_setting(self.key, on)
        self.btn.setArrowType(QtCore.Qt.DownArrow if on else QtCore.Qt.RightArrow)
        self.body.setVisible(on)

    def button(self, text, tip, fn, icon=None, cols=1, span=1):
        b = QtWidgets.QToolButton(self.body)
        b.setText(text)
        b.setToolTip(tip)
        if getattr(fn, "py", None):
            from . import pytips
            pytips.tag(b, fn.py)
        if icon:
            b.setIcon(_icon(icon))
            b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        b.clicked.connect(fn)
        self._place(b, cols, span)
        return b

    def widget(self, w, cols=1, span=1):
        w.setParent(self.body)
        self._place(w, cols, span)
        return w

    def _place(self, w, cols, span):
        # columns share the panel width – long texts / spin boxes must not widen it
        w.setMinimumWidth(0)
        w.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        if self._col + span > cols:
            self._row += 1
            self._col = 0
        self.grid.addWidget(w, self._row, self._col, 1, span)
        self._col += span
        if self._col >= cols:
            self._row += 1
            self._col = 0

    def newline(self):
        if self._col:
            self._row += 1
            self._col = 0


class UVEditor(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.mode = setting("select_mode", "VERT")
        self._image_name = None                     # None = the active material's image
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.canvas = UVCanvas(self)
        lay.addWidget(self._toolbar())
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        split.addWidget(self.canvas)
        self.toolkit = self._toolkit()
        split.addWidget(self.toolkit)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setChildrenCollapsible(False)
        self.toolkit.setVisible(setting("toolkit", True))
        lay.addWidget(split, 1)
        self.canvas.changed.connect(self._sync_mesh_views)
        hub.data_changed.connect(self._data_changed)
        hub.selection_changed.connect(self._data_changed)
        hub.mode_changed.connect(lambda _m: self._data_changed())
        hub.file_loaded.connect(self._data_changed)
        if hasattr(hub, "undo_done"):
            hub.undo_done.connect(self._data_changed)
        self._sync_toolbar()

    # --- state
    def _data_changed(self):
        if self.canvas._modal:
            return
        self.canvas.invalidate()
        self._sync_toolbar()

    def _sync_mesh_views(self):
        try:
            vp = getattr(self.hub, "viewport_area", None) or getattr(self.hub, "viewport", None)
            if vp is not None:
                vp.request_redraw()
        except Exception:
            pass

    def set_mode(self, mode):
        self.mode = mode
        set_setting("select_mode", mode)
        ts = bpy.context.scene.tool_settings
        try:
            if ts.use_uv_select_sync and bpy.context.mode == "EDIT_MESH":
                from . import editmesh
                editmesh.set_select_mode(mode == "VERT", mode == "EDGE", mode in ("FACE", "ISLAND"))
            else:
                ts.uv_select_mode = {"VERT": "VERTEX", "EDGE": "EDGE", "FACE": "FACE", "ISLAND": "ISLAND"}[mode]
        except Exception:
            pass
        for m, b in self.mode_buttons.items():
            b.setChecked(m == mode)
        self.canvas.invalidate()

    def current_image(self, ob=None):
        if self._image_name and self._image_name in bpy.data.images:
            return bpy.data.images[self._image_name]
        return find_image(ob if ob is not None else _active_mesh())

    # --- toolbar
    def _toolbar(self):
        from . import keymap, pytips
        self.display_buttons = {}
        bar = QtWidgets.QWidget(self)
        h = QtWidgets.QHBoxLayout(bar)
        h.setContentsMargins(theme.px(4), theme.px(2), theme.px(4), theme.px(2))
        h.setSpacing(theme.px(2))
        # component modes
        self.mode_buttons = {}
        grp = QtWidgets.QButtonGroup(bar)
        for mode, label, icon, aid in MODES:
            b = QtWidgets.QToolButton(bar)
            b.setCheckable(True)
            b.setIcon(_icon(icon))
            b.setText(label)
            keymap.tip(b, f"{label} selection ({{{aid}}})")
            b.setChecked(mode == self.mode)
            b.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            pytips.tag(b, f"{PY}.set_mode({mode!r})")
            grp.addButton(b)
            self.mode_buttons[mode] = b
            h.addWidget(b)
        self.sync_btn = self._toggle_btn(bar, h, "UV_SYNC_SELECT", "Sync",
                                         "UV Sync Selection (Blender): on – the mesh selection is the UV selection and "
                                         "all faces are shown (like Maya); off – the UVs of the selected faces",
                                         None, self._set_sync)
        pytips.tag(self.sync_btn, "bpy.context.scene.tool_settings.use_uv_select_sync = True")
        h.addSpacing(theme.px(8))
        # UV map and image
        self.uvmap_combo = QtWidgets.QComboBox(bar)
        self.uvmap_combo.setToolTip("UV map (the active one is edited) – “+ New UV Map” adds one")
        self.uvmap_combo.activated.connect(self._uvmap_chosen)
        pytips.tag(self.uvmap_combo, "bpy.context.object.data.uv_layers.active_index = 0\n"
                                     "bpy.context.object.data.uv_layers.new(name=\"UVMap.001\")")
        h.addWidget(self.uvmap_combo)
        self.image_combo = QtWidgets.QComboBox(bar)
        self.image_combo.setToolTip("Image shown behind the UVs – Auto = the active material's texture")
        self.image_combo.setMinimumContentsLength(10)
        self.image_combo.activated.connect(self._image_chosen)
        pytips.tag(self.image_combo, f"{PY}.set_image(\"UV Grid\")   # None = the material's texture")
        h.addWidget(self.image_combo)
        h.addSpacing(theme.px(8))
        # display (Maya's UV editor toolbar)
        for key, icon, text, tip, default in (
                ("image", "IMAGE_DATA", "Image", "Show the texture image", True),
                ("dim", None, "Dim", "Dim the image so the UVs stand out", False),
                ("checker", "TEXTURE", "Checker", "Checker map instead of the image (Maya) – shows stretching", False),
                ("shaded", None, "Shaded", "Shaded UVs (Maya): front faces blue, flipped faces red, overlaps darker",
                 False),
                ("distortion", None, "Distortion", "Colour faces by area distortion: blue = right size, "
                                                   "green / yellow / red = stretched or squeezed", False),
                ("borders", None, "Borders", "Thick shell (island) borders", True),
                ("grid", "MESH_GRID", "Grid", "Grid with labels", True)):
            b = self._toggle_btn(bar, h, icon, text, tip, key, None, default)
            self.display_buttons[key] = b
            pytips.tag(b, f"{PY}.set_display({key!r}, True)")
        h.addStretch(1)
        fb = QtWidgets.QToolButton(bar)
        fb.setText("Frame")
        keymap.tip(fb, "Frame the selection ({uv.frame_selected}) – 0–1 ({uv.fit})")
        fb.clicked.connect(self.canvas.frame_selected)
        pytips.tag(fb, f"{PY}.canvas.frame_selected()   # {PY}.canvas.fit() = 0–1")
        h.addWidget(fb)
        tk = QtWidgets.QToolButton(bar)
        tk.setText("UV Toolkit")
        tk.setCheckable(True)
        tk.setChecked(setting("toolkit", True))
        tk.setToolTip("Show / hide the UV Toolkit (Maya) on the right")
        tk.toggled.connect(self._show_toolkit)
        pytips.tag(tk, f"{PY}.toolkit.setVisible(True)")
        h.addWidget(tk)
        return bar

    def _toggle_btn(self, bar, h, icon, text, tip, key, fn=None, default=False):
        b = QtWidgets.QToolButton(bar)
        b.setCheckable(True)
        if icon:
            b.setIcon(_icon(icon))
            b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        b.setText(text)
        b.setToolTip(tip)
        if key:
            b.setChecked(setting(key, default))
            b.toggled.connect(lambda on, k=key: (set_setting(k, on), self.canvas.update()))
        if fn:
            b.toggled.connect(fn)
        h.addWidget(b)
        return b

    def _show_toolkit(self, on):
        set_setting("toolkit", on)
        self.toolkit.setVisible(on)

    def _set_sync(self, on):
        try:
            bpy.context.scene.tool_settings.use_uv_select_sync = bool(on)
        except Exception:
            pass
        self.canvas.invalidate()
        self._sync_mesh_views()

    def _sync_toolbar(self):
        ts = bpy.context.scene.tool_settings
        self.sync_btn.blockSignals(True)
        self.sync_btn.setChecked(bool(getattr(ts, "use_uv_select_sync", False)))
        self.sync_btn.blockSignals(False)
        ob = _active_mesh()
        self.uvmap_combo.blockSignals(True)
        self.uvmap_combo.clear()
        if ob is not None:
            layers = ob.data.uv_layers
            for l in layers:
                self.uvmap_combo.addItem(l.name, l.name)
            if layers.active is not None:
                self.uvmap_combo.setCurrentIndex(max(0, self.uvmap_combo.findData(layers.active.name)))
        self.uvmap_combo.addItem("+ New UV Map", "__new__")
        self.uvmap_combo.blockSignals(False)
        self.image_combo.blockSignals(True)
        self.image_combo.clear()
        self.image_combo.addItem("Auto (material)", None)
        for img in bpy.data.images:
            if img.type in ("RENDER_RESULT", "COMPOSITING"):
                continue
            self.image_combo.addItem(img.name, img.name)
        self.image_combo.addItem("+ UV Grid texture", "__grid__")
        self.image_combo.setCurrentIndex(max(0, self.image_combo.findData(self._image_name)))
        self.image_combo.blockSignals(False)

    def _uvmap_chosen(self, i):
        ob = _active_mesh()
        data = self.uvmap_combo.itemData(i)
        if ob is None:
            return
        if data == "__new__":
            ob.data.uv_layers.new()
            bridge.undo_push("Add UV Map")
        else:
            idx = ob.data.uv_layers.find(data)
            if idx >= 0:
                ob.data.uv_layers.active_index = idx
        self._data_changed()

    def _image_chosen(self, i):
        data = self.image_combo.itemData(i)
        if data == "__grid__":
            self.test_texture()
            return
        self._image_name = data
        self.canvas.update()

    # --- toolkit
    def _toolkit(self):
        from . import keymap
        sa = QtWidgets.QScrollArea(self)
        sa.setWidgetResizable(True)
        sa.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        sa.setMinimumWidth(theme.px(290))
        sa.setMaximumWidth(theme.px(380))
        host = QtWidgets.QWidget(sa)
        v = QtWidgets.QVBoxLayout(host)
        v.setContentsMargins(theme.px(4), theme.px(4), theme.px(4), theme.px(4))
        v.setSpacing(theme.px(4))
        T = self.tool
        # Select
        s = _Section("Select", host)
        s.button("Shell", keymap.render("Select the whole shell of the selection – {uv.select_linked} under the "
                                        "mouse, double click a shell"), self._op("uv.select_linked"), cols=3)
        s.button("Grow", keymap.render("Grow the selection ({uv.select_more})"), self._op("uv.select_more"), cols=3)
        s.button("Shrink", keymap.render("Shrink the selection ({uv.select_less})"), self._op("uv.select_less"),
                 cols=3)
        s.button("Overlapping", "Select overlapping UVs", self._op("uv.select_overlap"), cols=3)
        s.button("Flipped", "Select flipped (reversed) UV faces", self._call("canvas.select_flipped"), cols=3)
        s.button("Pinned", "Select pinned UVs", self._op("uv.select_pinned"), cols=3)
        s.button("Invert", keymap.render("Invert the selection ({uv.select_invert})"),
                 self._call("canvas.select_all", "INVERT"), cols=3)
        s.button("Split", "Select Split – the selected faces get their own UVs (detach)",
                 self._op("uv.select_split"), cols=3)
        s.button("Similar", "Select UV islands similar to the selected ones",
                 self._op("uv.select_similar"), cols=3)
        cv = QtWidgets.QLabel("Convert to:", s.body)
        s.widget(cv, cols=4, span=4)
        for to, txt in (("VERT", "UVs"), ("EDGE", "Edges"), ("FACE", "Faces"), ("ISLAND", "Shell")):
            s.button(txt, f"Convert the selection to {txt}", self._call("canvas.convert_selection", to),
                     cols=4)
        v.addWidget(s)
        # Pin
        s = _Section("Pin", host)
        s.button("Pin", keymap.render("Pin the selected UVs ({uv.pin}) – Unfold keeps them in place"),
                 self._op("uv.pin", {"clear": False}), "PINNED", cols=3)
        s.button("Unpin", keymap.render("Unpin the selected UVs ({uv.unpin})"), self._op("uv.pin", {"clear": True}),
                 "UNPINNED", cols=3)
        s.button("Invert", "Invert the pins of the selected UVs", self._op("uv.pin", {"invert": True}), cols=3)
        v.addWidget(s)
        # Transform
        s = _Section("Transform", host)
        self.step = QtWidgets.QDoubleSpinBox(s.body)
        _pytag(self.step, f"{PY}.step.setValue(0.1)")
        self.step.setRange(0.0001, 100)
        self.step.setDecimals(4)
        self.step.setSingleStep(0.05)
        self.step.setValue(setting("move_step", 0.1))
        self.step.setToolTip("Step of the move buttons (UV units)")
        self.step.valueChanged.connect(lambda val: set_setting("move_step", val))
        s.widget(QtWidgets.QLabel("Move", s.body), cols=5)
        for txt, d, tip in (("◀", (-1, 0), "Move left (−U)"), ("▶", (1, 0), "Move right (+U)"),
                            ("▲", (0, 1), "Move up (+V)"), ("▼", (0, -1), "Move down (−V)")):
            s.button(txt, tip, self._call("move_by", _Val("step", d[0]), _Val("step", d[1])),
                     cols=5)
        s.widget(QtWidgets.QLabel("Step", s.body), cols=5, span=2)
        s.widget(self.step, cols=5, span=3)
        self.angle = QtWidgets.QDoubleSpinBox(s.body)
        _pytag(self.angle, f"{PY}.angle.setValue(45)")
        self.angle.setRange(-360, 360)
        self.angle.setValue(setting("rotate_angle", 45.0))
        self.angle.setSuffix("°")
        self.angle.valueChanged.connect(lambda val: set_setting("rotate_angle", val))
        s.button("⟲ 90°", "Rotate 90° counter-clockwise", self._call("rotate_by", 90), cols=4)
        s.button("⟳ 90°", "Rotate 90° clockwise", self._call("rotate_by", -90), cols=4)
        s.widget(self.angle, cols=4)
        s.button("Rotate", "Rotate by the angle (counter-clockwise)", self._call("rotate_by", _Val("angle")),
                 cols=4)
        s.button("Flip U", "Flip horizontally (around the selection centre)", self._call("flip", True), cols=2)
        s.button("Flip V", "Flip vertically", self._call("flip", False), cols=2)
        s.widget(QtWidgets.QLabel("Align", s.body), cols=4, span=4)
        for txt, how, tip in (("U min", "UMIN", "Align to the leftmost UV"), ("U mid", "UMID", "Align to the U centre"),
                              ("U max", "UMAX", "Align to the rightmost UV"), ("V min", "VMIN", "Align to the lowest UV"),
                              ("V mid", "VMID", "Align to the V centre"), ("V max", "VMAX", "Align to the highest UV")):
            s.button(txt, tip, self._call("align", how), cols=3)
        s.button("Straighten", "Straighten the selected UV edges (Blender Align → Straighten)",
                 self._op("uv.align", {"axis": "ALIGN_S"}), cols=2)
        s.button("Orient Shells", "Rotate shells so their longest edge is horizontal / vertical (Maya Orient)",
                 self._op("uv.align_rotation", {"method": "AUTO"}), cols=2)
        s.button("Normalize", "Scale the selection to fit the 0–1 tile (keeps the proportions)", self._call("normalize"),
                 cols=2)
        s.button("Snap to Pixels", "Snap the selected UVs to the image pixels",
                 self._op("uv.snap_selected", {"target": "PIXELS"}), cols=2)
        v.addWidget(s)
        # Create
        s = _Section("Create", host)
        self.unwrap_method = QtWidgets.QComboBox(s.body)
        _pytag(self.unwrap_method, f"{PY}.unwrap_method.setCurrentIndex(0)   # Angle Based, Conformal, Minimum Stretch")
        for ident, label in (("ANGLE_BASED", "Angle Based"), ("CONFORMAL", "Conformal"),
                             ("MINIMUM_STRETCH", "Minimum Stretch")):
            self.unwrap_method.addItem(label, ident)
        self.unwrap_method.setCurrentIndex(max(0, self.unwrap_method.findData(setting("unwrap_method",
                                                                                      "ANGLE_BASED"))))
        self.unwrap_method.currentIndexChanged.connect(
            lambda _i: set_setting("unwrap_method", self.unwrap_method.currentData()))
        s.button("Unwrap", keymap.render("Unwrap the selected faces along the seams ({uv.unwrap}); pinned UVs stay"),
                 self._call("unwrap"), cols=2)
        s.widget(self.unwrap_method, cols=2)
        s.button("Smart UV", "Smart UV Project (automatic, splits by angle)", self._call("mesh_tool", "uv.smart_project"),
                 cols=2)
        s.button("Planar / Cube", "Cube Projection", self._call("mesh_tool", "uv.cube_project"), cols=2)
        s.button("Cylindrical", "Cylinder Projection", self._call("mesh_tool", "uv.cylinder_project"), cols=2)
        s.button("Spherical", "Sphere Projection", self._call("mesh_tool", "uv.sphere_project"), cols=2)
        s.button("Follow Quads", "Follow Active Quads – unwrap quads following the active face",
                 self._call("mesh_tool", "uv.follow_active_quads"), cols=2)
        s.button("Lightmap", "Lightmap Pack – every face its own square",
                 self._call("mesh_tool", "uv.lightmap_pack"), cols=2)
        s.button("Reset", "Reset UVs – every face fills the whole tile", self._call("mesh_tool", "uv.reset"), cols=2)
        v.addWidget(s)
        # Cut and Sew
        s = _Section("Cut and Sew", host)
        s.button("Mark Seam", "Mark the selected UV edges as seams (cut here at the next Unwrap)",
                 self._op("uv.mark_seam", {"clear": False}), cols=2)
        s.button("Clear Seam", "Clear the seams of the selected UV edges", self._op("uv.mark_seam", {"clear": True}),
                 cols=2)
        s.button("Seams from Shells", "Mark seams on all shell borders", self._op("uv.seams_from_islands"), cols=2)
        s.button("Split", "Split the selected faces off their neighbours (Maya Cut)", self._op("uv.select_split"),
                 cols=2)
        s.button("Stitch", keymap.render("Stitch / Sew the selected edges together ({uv.stitch})"),
                 self._op("uv.stitch"), cols=2)
        s.button("Weld", keymap.render("Merge the selected UVs to their centre ({uv.weld})"), self._op("uv.weld"),
                 cols=2)
        s.button("Merge by Distance", "Merge UVs closer than 0.0001", self._op("uv.remove_doubles"), cols=2)
        v.addWidget(s)
        # Unfold / Layout
        s = _Section("Unfold & Layout", host)
        s.button("Unfold", "Unfold the selected faces (pins stay) – Blender Unwrap with the chosen method",
                 self._call("unwrap"), cols=2)
        self.iters = QtWidgets.QSpinBox(s.body)
        _pytag(self.iters, f"{PY}.iters.setValue(50)")
        self.iters.setRange(1, 1000)
        self.iters.setValue(setting("optimize_iterations", 50))
        self.iters.valueChanged.connect(lambda val: set_setting("optimize_iterations", val))
        s.button("Optimize", "Minimize stretch (iterations)",
                 self._op("uv.minimize_stretch", {"iterations": _Val("iters")}), cols=2)
        s.widget(QtWidgets.QLabel("Iterations", s.body), cols=2)
        s.widget(self.iters, cols=2)
        s.button("Average Scale", "Average the shells' scale (same texel density)",
                 self._op("uv.average_islands_scale"), cols=2)
        s.button("Layout", "Pack the shells into the 0–1 tile (margin, rotate)", self._call("layout_shells"), cols=2)
        self.margin = QtWidgets.QDoubleSpinBox(s.body)
        _pytag(self.margin, f"{PY}.margin.setValue(0.01)")
        self.margin.setRange(0, 0.5)
        self.margin.setDecimals(3)
        self.margin.setSingleStep(0.005)
        self.margin.setValue(setting("pack_margin", 0.01))
        self.margin.valueChanged.connect(lambda val: set_setting("pack_margin", val))
        self.rotate_pack = QtWidgets.QCheckBox("Rotate", s.body)
        _pytag(self.rotate_pack, f"{PY}.rotate_pack.setChecked(True)")
        self.rotate_pack.setChecked(setting("pack_rotate", True))
        self.rotate_pack.toggled.connect(lambda on: set_setting("pack_rotate", on))
        s.widget(QtWidgets.QLabel("Margin", s.body), cols=3)
        s.widget(self.margin, cols=3)
        s.widget(self.rotate_pack, cols=3)
        v.addWidget(s)
        # Texel density
        s = _Section("Texel Density", host)
        self.td_size = QtWidgets.QSpinBox(s.body)
        _pytag(self.td_size, f"{PY}.td_size.setValue(1024)")
        self.td_size.setRange(1, 32768)
        self.td_size.setValue(setting("td_size", 1024))
        self.td_size.setToolTip("Texture size in pixels (the image's own size when an image is shown)")
        self.td_size.valueChanged.connect(lambda val: set_setting("td_size", val))
        self.td = QtWidgets.QDoubleSpinBox(s.body)
        _pytag(self.td, f"{PY}.set_texel_density(512)")
        self.td.setRange(0.001, 1e6)
        self.td.setDecimals(2)
        self.td.setValue(setting("td_value", 512.0))
        self.td.setSuffix(" px/m")
        self.td.valueChanged.connect(lambda val: set_setting("td_value", val))
        s.widget(QtWidgets.QLabel("Map size", s.body), cols=2)
        s.widget(self.td_size, cols=2)
        s.widget(QtWidgets.QLabel("Density", s.body), cols=2)
        s.widget(self.td, cols=2)
        s.button("Get", "Texel density of the selection (pixels per metre)", self._call("texel_get"), cols=2)
        s.button("Set", "Scale every selected shell to this texel density", self._call("texel_set"), cols=2)
        v.addWidget(s)
        v.addStretch(1)
        sa.setWidget(host)
        return sa

    # --- callables that carry their Python command (Python tooltips, Shift+MMB copies it)
    def _op(self, idname, props=None):
        def fn(*_a):
            self.tool(idname, _resolve(self, props) if props else None)
        p = f", {props!r}" if props else ""
        mod, name = idname.split(".", 1)
        args = ", ".join(f"{k}={v!r}" for k, v in (props or {}).items())
        fn.py = f"{PY}.tool({idname!r}{p})\n# = bpy.ops.{mod}.{name}({args}) in a UV editor context"
        return fn

    def _call(self, name, *args):
        def fn(*_a):
            obj = self
            for part in name.split("."):
                obj = getattr(obj, part)
            obj(*[_resolve(self, a) for a in args])
        fn.py = f"{PY}.{name}({_args(args)})"
        return fn

    def set_display(self, key, on=True):
        """Display options: image, dim, checker, shaded, distortion, borders, grid."""
        set_setting(key, bool(on))
        b = self.display_buttons.get(key)
        if b is not None:
            b.blockSignals(True)
            b.setChecked(bool(on))
            b.blockSignals(False)
        self.canvas.update()

    def set_image(self, name=None):
        """Image shown behind the UVs – None = the active material's texture."""
        self._image_name = name
        self._sync_toolbar()
        self.canvas.update()

    def set_texel_density(self, value):
        """Scales every selected shell to value pixels per metre."""
        self.td.setValue(float(value))
        self.texel_set()

    # --- marking menu (right click)
    def marking_menu(self, gpos, pos):
        from . import keymap, pytips
        m = QtWidgets.QMenu(self)
        m.setToolTipsVisible(True)

        def add(menu, text, fn):
            a = menu.addAction(text, fn)
            if getattr(fn, "py", None):
                pytips.tag(a, fn.py)
            return a
        for mode, label, icon, aid in MODES:
            a = m.addAction(_icon(icon), label + "\t" + keymap.render(f"{{{aid}}}"))
            a.setCheckable(True)
            a.setChecked(mode == self.mode)
            a.triggered.connect(lambda _=False, md=mode: self.set_mode(md))
            pytips.tag(a, f"{PY}.set_mode({mode!r})")
        m.addSeparator()
        sh = m.addAction("Select Shell Here", lambda: self.canvas.select_island_at(pos, "ADD"))
        pytips.tag(sh, f"{PY}.tool('uv.select_linked')   # shell of the selection")
        conv = m.addMenu("Convert Selection")
        conv.setToolTipsVisible(True)
        for to, txt in (("VERT", "To UVs"), ("EDGE", "To Edges"), ("FACE", "To Faces"), ("ISLAND", "To Shell")):
            add(conv, txt, self._call("canvas.convert_selection", to))
        m.addSeparator()
        add(m, "Unfold", self._call("unwrap"))
        add(m, "Optimize", self._op("uv.minimize_stretch", {"iterations": _Val("iters")}))
        add(m, "Layout", self._call("layout_shells"))
        m.addSeparator()
        add(m, "Split (Cut)", self._op("uv.select_split"))
        add(m, "Stitch (Sew)", self._op("uv.stitch"))
        add(m, "Weld", self._op("uv.weld"))
        m.addSeparator()
        add(m, "Pin", self._op("uv.pin", {"clear": False}))
        add(m, "Unpin", self._op("uv.pin", {"clear": True}))
        m.addSeparator()
        add(m, "Rotate 90° CCW", self._call("rotate_by", 90))
        add(m, "Rotate 90° CW", self._call("rotate_by", -90))
        add(m, "Flip U", self._call("flip", True))
        add(m, "Flip V", self._call("flip", False))
        m.addSeparator()
        add(m, "Frame Selection", self._call("canvas.frame_selected"))
        add(m, "Frame 0–1", self._call("canvas.fit"))
        m.exec(gpos)

    # --- tools
    def tool(self, idname, props=None):
        """A Blender UV operator on the current UV selection."""
        if ensure_edit() is None:
            self.canvas.status.emit("Select a mesh object.")
            return
        res = run_uv_op(idname, props, self.current_image())
        if "FINISHED" not in res:
            self.canvas.status.emit(f"{idname}: nothing to do (check the selection).")
        self.canvas.invalidate()
        self._sync_mesh_views()

    def mesh_tool(self, idname, props=None):
        """A projection (3D view operator) on the selected faces – all faces when none is selected."""
        ob = _active_mesh()
        if ob is None:
            self.canvas.status.emit("Select a mesh object.")
            return
        if ob.mode != "EDIT":
            ensure_edit(select_all=True)
        else:
            bm = bmesh.from_edit_mesh(ob.data)
            if not any(f.select for f in bm.faces):
                bridge.run_op("mesh.select_all", {"action": "SELECT"})
        if not ob.data.uv_layers:
            ob.data.uv_layers.new()
        bridge.run_op(idname, props or {})
        self.canvas.invalidate()
        self._sync_toolbar()

    def unwrap(self):
        self.mesh_tool("uv.unwrap", {"method": self.unwrap_method.currentData() or "ANGLE_BASED",
                                     "margin": 0.001})

    def layout_shells(self):
        props = {"margin": self.margin.value(), "rotate": self.rotate_pack.isChecked()}
        self.tool("uv.pack_islands", props)

    def _selected_loops(self):
        s = self.canvas.snap()
        if s is None or not s.editable or s.uvl is None:
            self.canvas.status.emit("UVs can be edited in Edit mode (Tab).")
            return None, []
        seen, out = set(), []
        for fi, ci in s.selected_corners(self.mode):
            l = s.loops[fi][ci]
            if id(l) not in seen:
                seen.add(id(l))
                out.append(l)
        if not out:
            self.canvas.status.emit("No UVs are selected.")
        return s, out

    def _apply(self, s, loops, fn, name):
        uvl = s.uvl
        if not loops:
            return
        uvs = [l[uvl].uv.copy() for l in loops]
        new = fn(uvs)
        for l, uv in zip(loops, new):
            l[uvl].uv = uv
        bmesh.update_edit_mesh(s.ob.data, loop_triangles=False, destructive=False)
        bridge.undo_push(name)
        self.canvas.invalidate()
        self._sync_mesh_views()

    @staticmethod
    def _bounds(uvs):
        lo = Vector((min(u.x for u in uvs), min(u.y for u in uvs)))
        hi = Vector((max(u.x for u in uvs), max(u.y for u in uvs)))
        return lo, hi

    def move_by(self, du, dv):
        s, loops = self._selected_loops()
        self._apply(s, loops, lambda uvs: [u + Vector((du, dv)) for u in uvs], "Move UVs")

    def rotate_by(self, deg):
        s, loops = self._selected_loops()

        def fn(uvs):
            lo, hi = self._bounds(uvs)
            c = (lo + hi) / 2
            a = math.radians(deg)
            ca, sa = math.cos(a), math.sin(a)
            return [Vector((c.x + (u.x - c.x) * ca - (u.y - c.y) * sa, c.y + (u.x - c.x) * sa + (u.y - c.y) * ca))
                    for u in uvs]
        self._apply(s, loops, fn, "Rotate UVs")

    def flip(self, horizontal):
        s, loops = self._selected_loops()

        def fn(uvs):
            lo, hi = self._bounds(uvs)
            c = (lo + hi) / 2
            return [Vector((2 * c.x - u.x, u.y)) if horizontal else Vector((u.x, 2 * c.y - u.y)) for u in uvs]
        self._apply(s, loops, fn, "Flip UVs")

    def align(self, how):
        s, loops = self._selected_loops()

        def fn(uvs):
            lo, hi = self._bounds(uvs)
            val = {"UMIN": lo.x, "UMAX": hi.x, "UMID": (lo.x + hi.x) / 2,
                   "VMIN": lo.y, "VMAX": hi.y, "VMID": (lo.y + hi.y) / 2}[how]
            return [Vector((val, u.y)) if how[0] == "U" else Vector((u.x, val)) for u in uvs]
        self._apply(s, loops, fn, "Align UVs")

    def normalize(self):
        s, loops = self._selected_loops()

        def fn(uvs):
            lo, hi = self._bounds(uvs)
            size = max(hi.x - lo.x, hi.y - lo.y, 1e-9)
            return [Vector(((u.x - lo.x) / size, (u.y - lo.y) / size)) for u in uvs]
        self._apply(s, loops, fn, "Normalize UVs")

    # --- texel density
    def _texture_size(self):
        img = self.current_image()
        try:
            if img is not None and img.size[0] and img.size[1]:
                return math.sqrt(img.size[0] * img.size[1])
        except Exception:
            pass
        return float(self.td_size.value())

    def _faces_of_selection(self, s):
        faces = sorted({fi for fi, _c in s.selected_corners(self.mode)})
        if self.mode in ("VERT", "EDGE"):
            sel = set(s.selected_corners(self.mode))
            faces = [fi for fi in faces if all((fi, c) in sel for c in range(len(s.faces[fi][1])))] or faces
        return faces

    def texel_get(self):
        s = self.canvas.snap()
        if s is None or not s.faces:
            return
        faces = self._faces_of_selection(s) if s.editable else []
        faces = faces or list(range(len(s.faces)))
        a3 = sum(s.area3d[fi] for fi in faces)
        auv = sum(s.areauv[fi] for fi in faces)
        if a3 <= 0:
            return
        density = math.sqrt(auv / a3) * self._texture_size()
        self.td.setValue(density)
        self.canvas.status.emit(f"Texel density: {density:.2f} px/m ({len(faces)} faces)")

    def texel_set(self):
        s = self.canvas.snap()
        if s is None or not s.editable or s.uvl is None:
            self.canvas.status.emit("UVs can be edited in Edit mode (Tab).")
            return
        faces = self._faces_of_selection(s)
        if not faces:
            self.canvas.status.emit("No UVs are selected.")
            return
        uvl = s.uvl
        size = self._texture_size()
        target = self.td.value()
        by_island = {}
        for fi in faces:
            by_island.setdefault(s.island[fi], []).append(fi)
        for isl, fl in by_island.items():
            all_faces = [fi for fi in range(len(s.faces)) if s.island[fi] == isl]
            a3 = sum(s.area3d[fi] for fi in all_faces)
            auv = sum(s.areauv[fi] for fi in all_faces)
            if a3 <= 0 or auv <= 0:
                continue
            cur = math.sqrt(auv / a3) * size
            k = target / cur
            loops = {id(l): l for fi in all_faces for l in s.loops[fi]}.values()
            uvs = [l[uvl].uv.copy() for l in loops]
            lo, hi = self._bounds(uvs)
            c = (lo + hi) / 2
            for l, u in zip(loops, uvs):
                l[uvl].uv = c + (u - c) * k
        bmesh.update_edit_mesh(s.ob.data, loop_triangles=False, destructive=False)
        bridge.undo_push("Set Texel Density")
        self.canvas.invalidate()
        self._sync_mesh_views()

    # --- texture
    def test_texture(self):
        ob = _active_mesh()
        if ob is None:
            return
        img = bpy.data.images.get("UV Grid") or bpy.data.images.new("UV Grid", 1024, 1024)
        img.generated_type = "UV_GRID"
        mat = ob.active_material
        if mat is None:
            mat = bpy.data.materials.new("Material")
            ob.active_material = mat
        mat.use_nodes = True
        nt = mat.node_tree
        tex = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeTexImage"), None)
        if tex is None:
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.location = (-400, 250)
        tex.image = img
        bsdf = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)
        if bsdf is not None:
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        nt.nodes.active = tex
        self._image_name = None
        bridge.undo_push("UV Grid Texture")
        self._sync_toolbar()
        self.canvas.update()

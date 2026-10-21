"""UV editor in Qt: shows the UV map of the active mesh with a texture, UV point selection, G/R/S, unwrap.

In Edit mode it shows the UVs of the selected faces (or of all faces when none is selected) and they can be edited.
In Object mode the view is read-only.
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, theme

PICK = 10.0


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


class UVCanvas(QtWidgets.QWidget):
    status = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(200, 200)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.scale = 300.0
        self.offset = QtCore.QPointF(60, 360)   # position of UV (0,0) in the widget
        self.sel = set()                         # {(face_index, corner)}
        self._pan = None
        self._press = None
        self._box = None
        self._modal = None
        self._fitted = False

    # --- coordinate conversion
    def to_screen(self, u, v):
        return QtCore.QPointF(self.offset.x() + u * self.scale, self.offset.y() - v * self.scale)

    def to_uv(self, p):
        return ((p.x() - self.offset.x()) / self.scale, (self.offset.y() - p.y()) / self.scale)

    def fit(self):
        s = min(self.width(), self.height()) - 60
        self.scale = max(s, 50)
        self.offset = QtCore.QPointF((self.width() - self.scale) / 2, (self.height() + self.scale) / 2)
        self.update()

    # --- data
    def data(self):
        """Returns (ob, bm|None, uv_layer, editable, polys) – polys = [(fi, [(ci, Vector2)])]."""
        ob = _active_mesh()
        if ob is None:
            return None
        polys = []
        if ob.mode == "EDIT":
            bm = bmesh.from_edit_mesh(ob.data)
            uvl = bm.loops.layers.uv.active
            if uvl is None:
                return ob, bm, None, True, []
            bm.faces.ensure_lookup_table()
            faces = [f for f in bm.faces if f.select and not f.hide]
            if not faces:
                faces = [f for f in bm.faces if not f.hide]
            for f in faces:
                polys.append((f.index, [(ci, l[uvl].uv.copy()) for ci, l in enumerate(f.loops)]))
            return ob, bm, uvl, True, polys
        me = ob.data
        layer = me.uv_layers.active
        if layer is None:
            return ob, None, None, False, []
        uvd = layer.data
        for p in me.polygons:
            polys.append((p.index, [(ci, Vector(uvd[li].uv)) for ci, li in enumerate(p.loop_indices)]))
        return ob, None, layer, False, polys

    # --- drawing
    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#2b2b2b"))
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        if not self._fitted and self.width() > 50:
            self._fitted = True
            self.fit()
        o = self.to_screen(0, 1)
        sq = QtCore.QRectF(o.x(), o.y(), self.scale, self.scale)
        d = self.data()
        ob = d[0] if d else None
        img = find_image(ob) if ob is not None else None
        qimg = image_to_qimage(img) if img is not None else None
        if qimg is not None:
            p.drawImage(sq, qimg)
        else:
            p.fillRect(sq, QtGui.QColor("#3a3a3a"))
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 30), 1))
        for i in range(1, 8):
            t = i / 8
            a, b = self.to_screen(t, 0), self.to_screen(t, 1)
            p.drawLine(a, b)
            a, b = self.to_screen(0, t), self.to_screen(1, t)
            p.drawLine(a, b)
        p.setPen(QtGui.QPen(QtGui.QColor("#777777"), 1))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRect(sq)
        if d is None:
            self._hint(p, "Select a mesh object.")
            p.end()
            return
        _ob, _bm, uvl, editable, polys = d
        if uvl is None:
            self._hint(p, "The mesh has no UV map – use Unwrap.")
            p.end()
            return
        sel = self.sel
        fill = QtGui.QColor(255, 140, 30, 50)
        edge_pen = QtGui.QPen(QtGui.QColor("#d8d8d8") if editable else QtGui.QColor("#9a9a9a"), 1)
        for fi, corners in polys:
            pts = [self.to_screen(uv.x, uv.y) for _ci, uv in corners]
            poly = QtGui.QPolygonF(pts)
            if editable and all((fi, ci) in sel for ci, _uv in corners):
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(fill)
                p.drawPolygon(poly)
            p.setBrush(QtCore.Qt.NoBrush)
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 160), 3))
            p.drawPolygon(poly)
            p.setPen(edge_pen)
            p.drawPolygon(poly)
        if editable:
            for fi, corners in polys:
                for ci, uv in corners:
                    pt = self.to_screen(uv.x, uv.y)
                    on = (fi, ci) in sel
                    p.setPen(QtCore.Qt.NoPen)
                    p.setBrush(QtGui.QColor("#ff9a1f") if on else QtGui.QColor("#202020"))
                    r = 3.5 if on else 2.5
                    p.drawEllipse(pt, r, r)
        if self._box:
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1, QtCore.Qt.DashLine))
            p.setBrush(QtGui.QColor(255, 255, 255, 20))
            p.drawRect(QtCore.QRectF(self._box[0], self._box[1]).normalized())
        p.setPen(QtGui.QColor("#cfcfcf"))
        f = p.font()
        f.setPixelSize(theme.fs(11))
        p.setFont(f)
        info = (img.name if img is not None else "no texture") + ("" if editable else "  ·  preview only (Tab = Edit mode)")
        if self._modal:
            info = self._modal_text()
        p.drawText(10, self.height() - 10, info)
        p.end()

    def _hint(self, p, text):
        p.setPen(QtGui.QColor("#aaaaaa"))
        p.drawText(self.rect(), QtCore.Qt.AlignCenter, text)

    # --- selection
    def _all_points(self, polys):
        for fi, corners in polys:
            for ci, uv in corners:
                yield fi, ci, uv

    def _sticky(self, polys, fi, ci, bm):
        """All corners that share the same mesh vertex and the same UV coordinate."""
        bm.faces.ensure_lookup_table()
        f = bm.faces[fi]
        vert = f.loops[ci].vert
        uv0 = dict(((a, b), uv) for a, b, uv in self._all_points(polys))[(fi, ci)]
        out = set()
        uvl = bm.loops.layers.uv.active
        shown = {a for a, _c in polys}
        for l in vert.link_loops:
            if l.face.index in shown and (l[uvl].uv - uv0).length < 1e-5:
                out.add((l.face.index, list(l.face.loops).index(l)))
        return out

    def select_at(self, pos, extend):
        d = self.data()
        if not d or not d[3] or d[2] is None:
            return
        _ob, bm, _uvl, _ed, polys = d
        best, best_d = None, PICK
        for fi, ci, uv in self._all_points(polys):
            pt = self.to_screen(uv.x, uv.y)
            dd = math.hypot(pt.x() - pos.x(), pt.y() - pos.y())
            if dd < best_d:
                best, best_d = (fi, ci), dd
        if not extend:
            self.sel = set()
        if best is not None:
            group = self._sticky(polys, best[0], best[1], bm)
            if extend and best in self.sel:
                self.sel -= group
            else:
                self.sel |= group
        self.update()

    def select_box(self, rect, mode):
        d = self.data()
        if not d or not d[3] or d[2] is None:
            return
        if mode == "SET":
            self.sel = set()
        for fi, ci, uv in self._all_points(d[4]):
            if rect.contains(self.to_screen(uv.x, uv.y)):
                if mode == "SUB":
                    self.sel.discard((fi, ci))
                else:
                    self.sel.add((fi, ci))
        self.update()

    def select_all(self, on=True):
        d = self.data()
        if d and d[3]:
            self.sel = {(fi, ci) for fi, ci, _uv in self._all_points(d[4])} if on else set()
        self.update()

    # --- G / R / S
    def start_modal(self, kind):
        d = self.data()
        if not d or not d[3] or d[2] is None:
            self.status.emit("UVs can be edited in Edit mode.")
            return
        ob, bm, uvl, _ed, polys = d
        bm.faces.ensure_lookup_table()
        pts = []
        for fi, ci in self.sel:
            if fi < len(bm.faces):
                loop = bm.faces[fi].loops[ci]
                pts.append((loop, loop[uvl].uv.copy()))
        if not pts:
            self.status.emit("No UV points are selected.")
            return
        pivot = sum((uv for _l, uv in pts), Vector((0, 0))) / len(pts)
        self._modal = {"kind": kind, "pts": pts, "pivot": pivot, "uvl": uvl, "ob": ob,
                       "start": QtCore.QPointF(self.mapFromGlobal(QtGui.QCursor.pos())), "axis": None,
                       "value": None}
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
        ax = f" ({m['axis']})" if m["axis"] else ""
        return f"{names[m['kind']]}{ax}: {v or ''}   X/Y axis · LMB/Enter confirm · RMB/Esc cancel"

    def _modal_update(self, pos):
        m = self._modal
        piv = m["pivot"]
        ps = self.to_screen(piv.x, piv.y)
        st = m["start"]
        out = []
        if m["kind"] == "G":
            dv = Vector(((pos.x() - st.x()) / self.scale, -(pos.y() - st.y()) / self.scale))
            if m["axis"] == "X":
                dv.y = 0
            elif m["axis"] == "Y":
                dv.x = 0
            m["value"] = dv
            out = [uv + dv for _l, uv in m["pts"]]
        elif m["kind"] == "R":
            a0 = math.atan2(-(st.y() - ps.y()), st.x() - ps.x())
            a1 = math.atan2(-(pos.y() - ps.y()), pos.x() - ps.x())
            ang = a1 - a0
            m["value"] = ang
            c, s = math.cos(ang), math.sin(ang)
            for _l, uv in m["pts"]:
                d = uv - piv
                out.append(Vector((piv.x + d.x * c - d.y * s, piv.y + d.x * s + d.y * c)))
        else:
            d0 = max(math.hypot(st.x() - ps.x(), st.y() - ps.y()), 1.0)
            fac = math.hypot(pos.x() - ps.x(), pos.y() - ps.y()) / d0
            m["value"] = fac
            fx = fac if m["axis"] in (None, "X") else 1.0
            fy = fac if m["axis"] in (None, "Y") else 1.0
            out = [Vector((piv.x + (uv.x - piv.x) * fx, piv.y + (uv.y - piv.y) * fy)) for _l, uv in m["pts"]]
        self._write([(l, uv) for (l, _o), uv in zip(m["pts"], out)])
        self.update()

    def _write(self, pairs):
        m = self._modal
        uvl = m["uvl"]
        try:
            for loop, uv in pairs:
                loop[uvl].uv = uv
            bmesh.update_edit_mesh(m["ob"].data, loop_triangles=False, destructive=False)
        except ReferenceError:
            pass

    def _modal_end(self, confirm):
        m = self._modal
        self._modal = None
        self.releaseMouse()
        if not confirm:
            self._write([(l, uv) for l, uv in m["pts"]])
        else:
            bridge.undo_push("UV Transform")
        self.update()

    # --- events
    def enterEvent(self, ev):
        fw = QtWidgets.QApplication.focusWidget()
        if not (isinstance(fw, QtWidgets.QLineEdit) and fw.text()):
            self.setFocus()
            win = self.window()
            if not win.isActiveWindow():   # floating dock = separate window
                win.activateWindow()
        super().enterEvent(ev)

    def wheelEvent(self, ev):
        f = 1.15 ** (ev.angleDelta().y() / 120.0)
        pos = ev.position()
        u, v = self.to_uv(pos)
        self.scale = min(max(self.scale * f, 20), 20000)
        np_ = self.to_screen(u, v)
        self.offset += pos - np_
        self.update()

    def mousePressEvent(self, ev):
        self.setFocus()
        if self._modal:
            self._modal_end(ev.button() == QtCore.Qt.LeftButton)
            return
        if ev.button() == QtCore.Qt.MiddleButton:
            self._pan = ev.position()
        elif ev.button() == QtCore.Qt.LeftButton:
            self._press = ev.position()

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._modal:
            self._modal_update(pos)
            return
        if self._pan is not None:
            self.offset += pos - self._pan
            self._pan = pos
            self.update()
        elif self._press is not None and (pos - self._press).manhattanLength() > 5:
            self._box = (self._press, pos)
            self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == QtCore.Qt.MiddleButton:
            self._pan = None
            return
        if ev.button() == QtCore.Qt.LeftButton and self._press is not None:
            mods = ev.modifiers()
            if self._box:
                rect = QtCore.QRectF(self._box[0], self._box[1]).normalized()
                mode = "SUB" if mods & QtCore.Qt.ControlModifier else ("ADD" if mods & QtCore.Qt.ShiftModifier else "SET")
                self._box = None
                self.select_box(rect, mode)
            else:
                self.select_at(ev.position(), bool(mods & QtCore.Qt.ShiftModifier))
            self._press = None

    def keyPressEvent(self, ev):
        k = ev.key()
        K = QtCore.Qt
        mods = ev.modifiers()
        if self._modal:
            if k == K.Key_Escape:
                self._modal_end(False)
            elif k in (K.Key_Return, K.Key_Enter):
                self._modal_end(True)
            elif k in (K.Key_X, K.Key_Y):
                ax = "X" if k == K.Key_X else "Y"
                self._modal["axis"] = None if self._modal["axis"] == ax else ax
                self._modal_update(QtCore.QPointF(self.mapFromGlobal(QtGui.QCursor.pos())))
            return
        from . import keymap
        names = keymap.event_names(ev)
        if keymap.hit("uv.move", ev, names):
            self.start_modal("G")
        elif keymap.hit("uv.rotate", ev, names):
            self.start_modal("R")
        elif keymap.hit("uv.scale", ev, names):
            self.start_modal("S")
        elif keymap.hit("uv.deselect_all", ev, names):
            self.select_all(False)
        elif keymap.hit("uv.select_all", ev, names):
            self.select_all(True)
        elif keymap.hit("uv.fit", ev, names):
            self.fit()
        else:
            super().keyPressEvent(ev)

    def focusNextPrevChild(self, _n):
        return False


class UVEditor(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        self.canvas = UVCanvas()
        for txt, tip, fn in (
            ("Unwrap", "UV → Unwrap (selected faces)", lambda: self._op("uv.unwrap", {"method": "ANGLE_BASED", "margin": 0.001})),
            ("Smart UV", "Smart UV Project", lambda: self._op("uv.smart_project")),
            ("Cube", "Cube Projection", lambda: self._op("uv.cube_project")),
            ("Reset", "Reset UV", lambda: self._op("uv.reset")),
            ("UV grid texture", "Creates a test UV grid texture and connects it to the material", self.test_texture),
            ("⤢", "Show 0–1 ({uv.fit})", self.canvas.fit),
        ):
            b = QtWidgets.QToolButton()
            b.setText(txt)
            from . import keymap
            keymap.tip(b, tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        hint = QtWidgets.QLabel("LMB select · Shift add · drag = box · G/R/S · A / Alt+A")
        hint.setProperty("dim", True)
        bar.addWidget(hint)
        lay.addLayout(bar)
        lay.addWidget(self.canvas, 1)
        hub.data_changed.connect(self.canvas.update)
        hub.selection_changed.connect(self._sel_changed)
        hub.mode_changed.connect(lambda _m: self._sel_changed())
        hub.file_loaded.connect(self._sel_changed)

    def _sel_changed(self):
        self.canvas.sel = set()
        self.canvas.update()

    def _op(self, idname, props=None):
        if bpy.context.mode != "EDIT_MESH":
            ob = _active_mesh()
            if ob is None:
                return
            bridge.run_op("object.mode_set", {"mode": "EDIT"})
            bridge.run_op("mesh.select_all", {"action": "SELECT"})
        bridge.run_op(idname, props or {})
        self.canvas.sel = set()
        self.canvas.update()

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
        bridge.undo_push("UV Grid Texture")
        self.canvas.update()

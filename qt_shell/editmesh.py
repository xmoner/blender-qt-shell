"""Edit mód sítě v Qt viewportu: výběr vrcholů / hran / stěn myší a transformace vybraných vrcholů.

Pracuje přímo s bmesh editované sítě (bmesh.from_edit_mesh). Body se promítají do obrazovky
přes numpy, zakryté prvky se odfiltrují ray castem do BVH stromu sítě (kromě X-ray).
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

PICK_RADIUS = 14.0


def active():
    ob = bpy.context.edit_object
    if ob is None or ob.type != "MESH":
        return None
    return ob, bmesh.from_edit_mesh(ob.data)


def select_mode():
    return tuple(bpy.context.tool_settings.mesh_select_mode)


def set_select_mode(vert=False, edge=False, face=False):
    bpy.context.tool_settings.mesh_select_mode = (vert, edge, face)
    r = active()
    if r:
        ob, bm = r
        bm.select_mode = {k for k, on in (("VERT", vert), ("EDGE", edge), ("FACE", face)) if on}
        bm.select_flush_mode()
        bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)


def _xray(vp):
    sp, _r = vp.space()
    if sp is None:
        return False
    sh = sp.shading
    if sh.type == "WIREFRAME":
        return bool(getattr(sh, "show_xray_wireframe", True))
    return bool(getattr(sh, "show_xray", False))


class Projector:
    """Promítání lokálních souřadnic sítě do pixelů widgetu + test viditelnosti."""

    def __init__(self, vp, ob, bm):
        self.vp = vp
        self.ob = ob
        self.bm = bm
        self.w, self.h = vp.width(), vp.height()
        self.vm, self.pm = vp.matrices(self.w, self.h)
        self.mw = ob.matrix_world.copy()
        self.inv = self.mw.inverted()
        self.M = np.array(self.pm @ self.vm @ self.mw, dtype=np.float64)
        self.xray = _xray(vp)
        self.bvh = None if self.xray else BVHTree.FromBMesh(bm)
        self.ortho = vp.ortho and not vp.camera_view
        self.cam = self.vm.inverted().translation
        self.fwd = vp.view_vectors()[2]

    def project(self, co_local):
        """co_local: (n,3) numpy → x, y, ok"""
        n = len(co_local)
        if n == 0:
            return np.zeros(0), np.zeros(0), np.zeros(0, dtype=bool)
        h4 = np.hstack([co_local, np.ones((n, 1))])
        clip = h4 @ self.M.T
        wv = clip[:, 3]
        ok = wv > 1e-6
        ws = np.where(ok, wv, 1.0)
        x = (clip[:, 0] / ws + 1.0) * 0.5 * self.w
        y = (1.0 - clip[:, 1] / ws) * 0.5 * self.h
        return x, y, ok

    def visible(self, co_local, face=None):
        if self.xray:
            return True
        pw = self.mw @ co_local
        origin = pw - self.fwd * 1e4 if self.ortho else self.cam
        ol = self.inv @ origin
        d = co_local - ol
        dist = d.length
        if dist < 1e-9:
            return True
        loc, _n, idx, hit = self.bvh.ray_cast(ol, d / dist, dist)
        if loc is None:
            return True
        if face is not None and idx == face.index:
            return True
        return hit >= dist - max(1e-4, dist * 1e-4)


def _vert_coords(bm):
    bm.verts.ensure_lookup_table()
    n = len(bm.verts)
    arr = np.empty(n * 3, dtype=np.float64)
    for i, v in enumerate(bm.verts):
        arr[i * 3:i * 3 + 3] = v.co
    return arr.reshape(n, 3)


def _deselect_all(bm):
    for seq in (bm.faces, bm.edges, bm.verts):
        for el in seq:
            el.select = False
    bm.select_history.clear()


def _finish(ob, bm):
    bm.select_flush_mode()
    bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)


def _find_vert(pr, co, x, y, X, Y, ok):
    bm = pr.bm
    d = np.hypot(X - x, Y - y)
    d[~ok] = np.inf
    for i in np.argsort(d)[:32]:
        if d[i] > PICK_RADIUS:
            break
        v = bm.verts[int(i)]
        if not v.hide and pr.visible(v.co):
            return v
    return None


def _find_edge(pr, X, Y, ok, x, y):
    bm = pr.bm
    bm.edges.ensure_lookup_table()
    if not len(bm.edges):
        return None
    idx = np.array([(e.verts[0].index, e.verts[1].index) for e in bm.edges], dtype=np.int64)
    ax, ay, bx, by = X[idx[:, 0]], Y[idx[:, 0]], X[idx[:, 1]], Y[idx[:, 1]]
    vx, vy = bx - ax, by - ay
    ll = vx * vx + vy * vy
    t = np.clip(((x - ax) * vx + (y - ay) * vy) / np.where(ll > 0, ll, 1), 0, 1)
    px, py = ax + t * vx, ay + t * vy
    d = np.hypot(px - x, py - y)
    d[~(ok[idx[:, 0]] & ok[idx[:, 1]])] = np.inf
    for i in np.argsort(d)[:32]:
        if d[i] > PICK_RADIUS:
            break
        e = bm.edges[int(i)]
        if e.hide:
            continue
        mid = (e.verts[0].co + e.verts[1].co) * 0.5
        if pr.visible(mid):
            return e
    return None


def _find_face(pr, x, y):
    bm = pr.bm
    bm.faces.ensure_lookup_table()
    origin, direction = pr.vp.ray(x, y)
    ol = pr.inv @ origin
    dl = (pr.inv.to_3x3() @ direction).normalized()
    if not pr.xray:
        loc, _n, idx, _d = pr.bvh.ray_cast(ol, dl)
        if loc is not None and idx is not None and idx < len(bm.faces):
            f = bm.faces[idx]
            return None if f.hide else f
        return None
    # X-ray: nejbližší střed stěny
    best, best_d = None, PICK_RADIUS * 2
    for f in bm.faces:
        if f.hide:
            continue
        c = f.calc_center_median()
        X, Y, ok = pr.project(np.array([c[:]]))
        if ok[0]:
            d = math.hypot(X[0] - x, Y[0] - y)
            if d < best_d:
                best, best_d = f, d
    return best


def pick(vp, x, y, extend):
    """Vrátí True, pokud se výběr změnil."""
    r = active()
    if not r:
        return False
    ob, bm = r
    vmode, emode, fmode = select_mode()
    pr = Projector(vp, ob, bm)
    co = _vert_coords(bm)
    X, Y, ok = pr.project(co)
    elem = None
    if vmode:
        elem = _find_vert(pr, co, x, y, X, Y, ok)
    if elem is None and emode:
        elem = _find_edge(pr, X, Y, ok, x, y)
    if elem is None and fmode:
        elem = _find_face(pr, x, y)
    if not extend:
        _deselect_all(bm)
    if elem is not None:
        if extend and elem.select:
            elem.select_set(False)
            try:
                bm.select_history.remove(elem)
            except Exception:
                pass
        else:
            elem.select_set(True)
            bm.select_history.add(elem)
    _finish(ob, bm)
    return True


def box(vp, rect, mode):
    r = active()
    if not r:
        return False
    ob, bm = r
    vmode, emode, fmode = select_mode()
    pr = Projector(vp, ob, bm)
    co = _vert_coords(bm)
    X, Y, ok = pr.project(co)
    inside = ok & (X >= rect.left()) & (X <= rect.right()) & (Y >= rect.top()) & (Y <= rect.bottom())
    if mode == "SET":
        _deselect_all(bm)
    state = mode != "SUB"
    vis_cache = {}

    def vis_vert(i):
        if i not in vis_cache:
            vis_cache[i] = pr.visible(bm.verts[i].co)
        return vis_cache[i]

    if vmode:
        for i in np.nonzero(inside)[0]:
            v = bm.verts[int(i)]
            if not v.hide and vis_vert(int(i)):
                v.select_set(state)
    elif emode:
        for e in bm.edges:
            a, b = e.verts[0].index, e.verts[1].index
            if not e.hide and inside[a] and inside[b] and (vis_vert(a) or vis_vert(b)):
                e.select_set(state)
    else:
        bm.faces.ensure_lookup_table()
        for f in bm.faces:
            if f.hide:
                continue
            c = f.calc_center_median()
            fx, fy, fok = pr.project(np.array([c[:]]))
            if fok[0] and rect.contains(fx[0], fy[0]) and pr.visible(c, face=f):
                f.select_set(state)
    _finish(ob, bm)
    return True


class TransformState:
    """Transformace vybraných vrcholů (G/R/S) v edit módu."""

    def __init__(self):
        r = active()
        if not r:
            raise ValueError("Není aktivní editovaná síť.")
        self.ob, self.bm = r
        self.verts = [v for v in self.bm.verts if v.select and not v.hide]
        if not self.verts:
            raise ValueError("Nic není vybráno.")
        self.init = [v.co.copy() for v in self.verts]
        self.mw = self.ob.matrix_world.copy()
        self.inv = self.mw.inverted()
        center = sum(self.init, Vector()) / len(self.init)
        self.pivot = self.mw @ center

    def apply(self, world_matrix):
        A = self.inv @ world_matrix @ self.mw
        try:
            for v, c in zip(self.verts, self.init):
                v.co = A @ c
            self.bm.normal_update()   # jinak zůstanou nové (vysunuté) stěny černé
            bmesh.update_edit_mesh(self.ob.data, loop_triangles=True, destructive=False)
        except ReferenceError:
            pass

    def restore(self):
        try:
            for v, c in zip(self.verts, self.init):
                v.co = c
            self.bm.normal_update()
            bmesh.update_edit_mesh(self.ob.data, loop_triangles=True, destructive=False)
        except ReferenceError:
            pass

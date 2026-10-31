"""Interactive value operators of Blender's menus (Shear, To Sphere, Push/Pull, Bevel, Inset, Edge Crease,
Adjust Light Power …) in Qt.

In Blender these run as modal operators that follow the mouse. Blender's own modal transform can't run in
Qt Shell's hidden 3D view (it crashes / does nothing), and run with EXEC they do nothing because their
value starts at 0. Here the operator runs once with the start value, then moving the mouse left / right
changes the value and the operator is redone (undo + run again, like Adjust Last Operation).
LMB / Enter confirms, RMB / Esc cancels, typing a number sets the value exactly.
"""
import math

import bpy
from PySide6 import QtCore, QtGui

from . import bridge

# prop: the operator property (or a tuple of names – the first one the operator has; they differ
# between Blender versions); index: the item of an array property (ignored when it is not an array)
# kind: "dist" – a distance (pixels × the view's size of a pixel), "factor" – about 1 per 300 px,
# "angle" – 0.5° per px, "scale" – multiplier 1 + dx / 200, "free" – 1 per 200 px
# (prop, index or None, kind, start, min, max)
SPECS = {
    "transform.shear": (("angle", "value"), None, "angle", 0.0, None, None),
    "transform.push_pull": ("value", None, "dist", 0.0, None, None),
    "transform.shrink_fatten": ("value", None, "dist", 0.0, None, None),
    "transform.tosphere": ("value", None, "factor", 0.0, 0.0, 1.0),
    "transform.bend": ("value", 0, "angle", 0.0, None, None),
    "transform.tilt": ("value", 0, "angle", 0.0, None, None),
    "transform.edge_bevelweight": ("value", None, "factor", 0.0, -1.0, 1.0),
    "transform.edge_crease": ("value", None, "factor", 0.0, -1.0, 1.0),
    "transform.vert_crease": ("value", None, "factor", 0.0, -1.0, 1.0),
    "transform.edge_slide": ("value", None, "factor", 0.0, -1.0, 1.0),
    "transform.vert_slide": (("factor", "value"), None, "factor", 0.0, -1.0, 1.0),
    "transform.skin_resize": ("value", None, "scale3", 1.0, 0.0, None),
    "mesh.bevel": ("offset", None, "dist", 0.0, 0.0, None),
    "mesh.inset": ("thickness", None, "dist", 0.0, 0.0, None),
    "pose.push": ("factor", None, "factor", 0.0, 0.0, 1.0),
    "pose.relax": ("factor", None, "factor", 0.0, 0.0, 1.0),
    "pose.breakdown": ("factor", None, "factor", 0.5, 0.0, 1.0),
    "pose.blend_to_neighbor": ("factor", None, "factor", 0.5, 0.0, 1.0),
}
# transform.transform(mode=…) used by menus (Radius, Tilt, …)
TRANSFORM_MODES = {
    "CURVE_SHRINKFATTEN": ("scale", 1.0, 0.0, None),
    "GPENCIL_SHRINKFATTEN": ("scale", 1.0, 0.0, None),
    "MASK_SHRINKFATTEN": ("scale", 1.0, 0.0, None),
    "GPENCIL_OPACITY": ("scale", 1.0, 0.0, None),
    "TILT": ("angle", 0.0, None, None),
    "BEND": ("angle", 0.0, None, None),
    "SHEAR": ("free", 0.0, None, None),
    "TOSPHERE": ("factor", 0.0, 0.0, 1.0),
    "SHRINKFATTEN": ("dist", 0.0, None, None),
    "PUSHPULL": ("dist", 0.0, None, None),
    "BONE_ENVELOPE": ("scale", 1.0, 0.0, None),
    "BONE_SIZE": ("scale", 1.0, 0.0, None),
    "BONE_ROLL": ("angle", 0.0, None, None),
    "EDGE_CREASE": ("factor", 0.0, -1.0, 1.0),
    "BWEIGHT": ("factor", 0.0, -1.0, 1.0),
    "VERT_CREASE": ("factor", 0.0, -1.0, 1.0),
    "SKIN_RESIZE": ("scale3", 1.0, 0.0, None),
}
# operators that only work interactively in Blender and have no Qt version yet
UNSUPPORTED = {
    "mesh.knife_tool": "Knife needs Blender's interactive tool – not available in Qt Shell yet.",
    "mesh.loopcut_slide": "Loop Cut and Slide needs Blender's interactive tool – not available in Qt Shell yet.",
    "mesh.loopcut": "Loop Cut needs Blender's interactive tool – not available in Qt Shell yet.",
}


def spec_for(idname, props):
    """(prop, index, kind, start, min, max) when the operator should run interactively, else None.
    An operator whose value is already in props (Repeat Last, Adjust Last Operation, a shelf button)
    runs as it is."""
    if idname == "wm.context_modal_mouse":
        return ("@context", None, "free", 0.0, None, None) if props.get("data_path_item") else None
    if idname == "transform.transform":
        mode = props.get("mode")
        t = TRANSFORM_MODES.get(mode)
        if t is None or "value" in props:
            return None
        kind, start, lo, hi = t
        return ("value", 0, kind, start, lo, hi)
    s = SPECS.get(idname)
    if s is None or not bridge.op_exists(idname):
        return None
    names = s[0] if isinstance(s[0], tuple) else (s[0],)
    rna = bridge.op_rna_props(idname)
    prop = next((n for n in names if n in rna), None)
    if prop is None or prop in props:
        return None
    return (prop,) + tuple(s[1:])


class ValueModal:
    def __init__(self, vp, idname, props, ctx, spec):
        self.vp = vp
        self.idname = idname
        self.props = dict(props)
        self.ctx = ctx
        self.prop, self.index, self.kind, self.start, self.lo, self.hi = spec
        self.value = self.start
        self.numeric = ""
        self.start_x = vp.mapFromGlobal(QtGui.QCursor.pos()).x()
        try:
            self.px = vp.pixel_size_at(vp.target)
        except Exception:
            self.px = 0.01
        self.applied = None            # value of the last finished run
        self.busy = False
        self.pending = False
        self.active = False
        self.ctx_items = None          # wm.context_modal_mouse: [(owner, attr, start value)]
        self.label = bridge.op_label(idname) if idname != "wm.context_modal_mouse" else (
            self.props.get("data_path_item", "").split(".")[-1].replace("_", " ").title())
        if self.prop == "@context":
            self.scale = float(self.props.get("input_scale", 1.0) or 1.0) * (
                -1.0 if self.props.get("invert") else 1.0)

    # -------------------------------------------------------------- start / run
    def begin(self):
        if self.prop == "@context":
            self.ctx_items = self._context_items()
            if not self.ctx_items:
                self.vp.status.emit(f"{self.label}: nothing to adjust.")
                return False
            self.active = True
            return True
        # an undo step of the state before, so the redo's undo can never go further back (an edit-mode
        # stack entered from Python has no step of its own – undo would jump to an older file state)
        bridge.undo_push(f"Before {self.label}")
        res = self._run(self.value)
        if "FINISHED" not in res:
            return False
        self.applied = self.value
        self.active = True
        return True

    def _props_for(self, value):
        p = dict(self.props)
        try:
            rp = bridge.op_rna_props(self.idname).get(self.prop)
            n = getattr(rp, "array_length", 0) if rp is not None else 0
            arr = list(rp.default_array) if n else []
        except Exception:
            arr = []
        if not arr:                               # a single value (e.g. transform.tilt in Blender 5)
            p[self.prop] = value
            return p
        if self.kind == "scale3":                 # skin resize: the same factor on X / Y / Z
            for i in range(min(3, len(arr))):
                arr[i] = value
        else:
            arr[self.index] = value
        p[self.prop] = tuple(arr)
        return p

    def _run(self, value):
        return bridge.run_op(self.idname, self._props_for(value), self.ctx)

    def _redo(self):
        """Undo the last run and run again with the current value (in a later Blender tick – the
        depsgraph must not see data that undo has just freed)."""
        if self.busy:
            self.pending = True
            return
        if self.applied == self.value:
            return
        self.busy = True
        try:
            from . import app
            app.hub().redo_burst()          # Properties waits with its full rebuild until the drag settles
            app.hub().hold_frame(True)      # the 3D view keeps its picture until the new run
        except Exception:
            pass
        bridge.run_op("ed.undo")
        value = self.value

        def again():
            try:
                res = self._run(value)
                if "FINISHED" in res:
                    self.applied = value
                else:
                    self.applied = None
            finally:
                self.busy = False
                try:
                    from . import app
                    app.hub().hold_frame(False)
                except Exception:
                    pass
                self.vp.redraw_scene()
                if self.pending:
                    self.pending = False
                    self._redo()
        bridge.later(again, 0.0)

    # -------------------------------------------------------------- wm.context_modal_mouse
    def _context_items(self):
        out = []
        try:
            iterable = bpy.context.path_resolve(self.props.get("data_path_iter", ""))
        except Exception:
            return out
        path = self.props.get("data_path_item", "")
        head, _sep, attr = path.rpartition(".")
        for item in iterable or ():
            try:
                owner = item.path_resolve(head) if head else item
                out.append((owner, attr, float(getattr(owner, attr))))
            except Exception:
                continue
        return out

    def _apply_context(self, delta):
        for owner, attr, v0 in self.ctx_items:
            try:
                setattr(owner, attr, v0 + delta)
            except Exception:
                pass
        self.vp.redraw_scene()

    # -------------------------------------------------------------- input
    def _from_dx(self, dx):
        k = self.kind
        if self.prop == "@context":
            return dx * self.scale
        if k == "dist":
            v = self.start + dx * self.px
        elif k == "angle":
            v = self.start + math.radians(dx * 0.5)
        elif k in ("scale", "scale3"):
            v = self.start * max(0.0, 1.0 + dx / 200.0)
        elif k == "factor":
            v = self.start + dx / 300.0
        else:
            v = self.start + dx / 200.0
        return v

    def _clamp(self, v):
        if self.lo is not None:
            v = max(self.lo, v)
        if self.hi is not None:
            v = min(self.hi, v)
        return v

    def set_value(self, v):
        v = self._clamp(v)
        self.value = v
        if self.prop == "@context":
            self._apply_context(v)
        else:
            self._redo()
        self.vp.update()

    def mouse_move(self, pos, fine=False):
        if self.numeric:
            return
        dx = pos.x() - self.start_x
        if fine:
            dx *= 0.1
        self.set_value(self._from_dx(dx))

    def key(self, ev):
        """True when the key was used."""
        key = ev.key()
        text = ev.text()
        if key == QtCore.Qt.Key_Escape:
            self.finish(False)
        elif key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.finish(True)
        elif key == QtCore.Qt.Key_Backspace:
            self.numeric = self.numeric[:-1]
            self._numeric_value()
        elif text and text in "0123456789.-":
            self.numeric += text
            self._numeric_value()
        return True

    def _numeric_value(self):
        try:
            v = float(self.numeric)
        except ValueError:
            self.vp.update()
            return
        if self.kind == "angle" and self.prop != "@context":
            v = math.radians(v)
        if self.prop == "@context":
            self.set_value(v - 0.0)
            return
        self.set_value(v)

    def finish(self, confirm):
        self.active = False
        if self.vp._vmodal is self:
            self.vp._vmodal = None
        try:
            self.vp.releaseMouse()
        except Exception:
            pass
        if self.prop == "@context":
            if confirm:
                bridge.undo_push(self.label)
            else:
                for owner, attr, v0 in self.ctx_items:
                    try:
                        setattr(owner, attr, v0)
                    except Exception:
                        pass
            self.vp.redraw_scene()
            self.vp.update()
            return
        if not confirm:
            def cancel():
                if self.busy:                    # wait for the running redo
                    bridge.later(cancel, 0.02)
                    return
                if self.applied is not None:
                    bridge.run_op("ed.undo")
                    panel = getattr(self.vp.window(), "last_op", None)   # Adjust Last Operation: nothing left
                    if panel is not None:
                        panel.clear()
                self.vp.redraw_scene()
            cancel()
        elif self.busy or self.applied != self.value:
            self.pending = False
            def settle():
                if self.busy:
                    bridge.later(settle, 0.02)
                    return
                if self.applied != self.value:
                    self._redo()
            settle()
        self.vp.update()

    def text(self):
        v = self.value
        if self.prop == "@context":
            shown = f"{v:+.3f}"
        elif self.kind == "angle":
            shown = f"{math.degrees(v):.1f}°"
        else:
            shown = f"{v:.3f}"
        num = f"   [{self.numeric}]" if self.numeric else ""
        return (f"{self.label}: {shown}{num}   "
                "(move the mouse left / right, Shift fine, type a number, LMB/Enter confirm, RMB/Esc cancel)")


def start(vp, idname, props, ctx=None):
    """Starts the interactive version of an operator. True when it was handled here."""
    if idname in UNSUPPORTED:
        vp.status.emit(UNSUPPORTED[idname])
        return True
    spec = spec_for(idname, props)
    if spec is None:
        return False
    if getattr(vp, "_vmodal", None) is not None:
        vp._vmodal.finish(True)
    if getattr(vp, "_modal", None):
        return False
    m = ValueModal(vp, idname, props, ctx, spec)
    if not m.begin():
        return True
    vp._vmodal = m
    vp.setFocus()
    vp.grabMouse()
    vp.update()
    return True

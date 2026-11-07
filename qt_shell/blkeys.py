"""Blender's own shortcuts of the other Edit Modes (armature, curve / surface, lattice) in the Qt 3D view.

Qt Shell's keymap (keymap.py) covers the keys every mode shares (G / R / S, select all, delete, duplicate,
hide …). Everything else a mode has in Blender – E extrude, Ctrl+P parent, Alt+P clear parent, Ctrl+R roll,
Ctrl+N recalculate roll, Alt+F switch direction, F fill, Y split, P separate, [ / ] select parent / child,
L select linked, Shift+G select similar, V handle type, Alt+C cyclic, Ctrl+T tilt, Alt+S radius … – is read
from Blender's key configuration (user first, then the default one), so a key works as it does in Blender,
including keys the user changed in Blender's preferences.

The matching keymap item's operator runs through bridge.run_op, so the operators Qt Shell handles itself
(transform macros → Qt G, transform.transform(mode=…) → valuemodal, wm.call_menu → a Qt menu) behave as
they do from the menus. Operators whose invoke() opens a menu of an enum (Parent: Connected / Keep Offset …)
show that menu in Qt; operators that pick under the mouse (L) use the Qt picking of editother.
"""
import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge

# context.mode → Blender keymaps searched (in this order)
KEYMAPS = {
    "EDIT_ARMATURE": ("Armature",),
    "EDIT_CURVE": ("Curve",),
    "EDIT_SURFACE": ("Curve",),
    "EDIT_LATTICE": ("Lattice",),
    "SCULPT": ("Sculpt",),
}

# operators whose invoke() is a menu of this enum property (WM_menu_invoke / own popup)
ENUM_MENU = {
    "armature.parent_set": "type",
    "armature.parent_clear": "type",
    "armature.calculate_roll": "type",
    "armature.select_similar": "type",
    "curve.handle_type_set": "type",
    "curve.select_similar": "type",
    "curve.spline_type_set": "type",
}

# operators that pick the element under the mouse – done by Qt (Blender's would look at its hidden 3D view)
PICK_OPS = ("armature.select_linked_pick", "curve.select_linked_pick")

# wm.tool_set_by_id (Industry Compatible: Q / W / E / R / T / D / M / C …): Blender's tools → Qt Shell's
# toolbar tools (tool, variant or None)
TOOL_MAP = {
    "builtin.select": ("SELECT", "TWEAK"), "builtin.select_box": ("SELECT", "BOX"),
    "builtin.select_circle": ("SELECT", "CIRCLE"), "builtin.select_lasso": ("SELECT", "LASSO"),
    "builtin.cursor": ("CURSOR", None), "builtin.move": ("MOVE", None), "builtin.rotate": ("ROTATE", None),
    "builtin.scale": ("SCALE", "SCALE"), "builtin.scale_cage": ("SCALE", "CAGE"),
    "builtin.transform": ("TRANSFORM", None), "builtin.annotate": ("ANNOTATE", "FREEHAND"),
    "builtin.annotate_line": ("ANNOTATE", "LINE"), "builtin.annotate_polygon": ("ANNOTATE", "POLYGON"),
    "builtin.annotate_eraser": ("ANNOTATE", "ERASER"), "builtin.measure": ("MEASURE", None),
}
# Blender tools Qt Shell has no tool for – their key runs the tool's action once (like Blender's
# operator key for it): (operator, props) or "extrude"
TOOL_ONCE = {
    "builtin.extrude": "extrude", "builtin.extrude_to_cursor": "extrude",
    "builtin.roll": ("transform.transform", {"mode": "BONE_ROLL"}),
    "builtin.bone_size": ("transform.transform", {"mode": "BONE_SIZE"}),
    "builtin.bone_envelope": ("transform.transform", {"mode": "BONE_ENVELOPE"}),
    "builtin.tilt": ("transform.tilt", {}),
    "builtin.radius": ("transform.transform", {"mode": "CURVE_SHRINKFATTEN"}),
    "builtin.shear": ("transform.shear", {}),
    "builtin.to_sphere": ("transform.tosphere", {}),
}

# bone collection menus (M / Shift+M)
COLLECTION_OPS = ("armature.move_to_collection", "armature.assign_to_collection")

_SYMBOLS = {
    "[": "LEFT_BRACKET", "]": "RIGHT_BRACKET", ",": "COMMA", ".": "PERIOD", "/": "SLASH", ";": "SEMI_COLON",
    "'": "QUOTE", "`": "ACCENT_GRAVE", "=": "EQUAL", "-": "MINUS", "\\": "BACK_SLASH", "+": "EQUAL",
    "*": "NUMPAD_ASTERIX",
}
_NUMPAD = {"+": "NUMPAD_PLUS", "-": "NUMPAD_MINUS", "*": "NUMPAD_ASTERIX", "/": "NUMPAD_SLASH",
           ".": "NUMPAD_PERIOD", ",": "NUMPAD_PERIOD"}
_DIGITS = ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE")
_QT_KEYS = {
    QtCore.Qt.Key_Delete: "DEL", QtCore.Qt.Key_Backspace: "BACK_SPACE", QtCore.Qt.Key_Tab: "TAB",
    QtCore.Qt.Key_Backtab: "TAB", QtCore.Qt.Key_Space: "SPACE", QtCore.Qt.Key_Return: "RET",
    QtCore.Qt.Key_Enter: "NUMPAD_ENTER", QtCore.Qt.Key_Escape: "ESC", QtCore.Qt.Key_Home: "HOME",
    QtCore.Qt.Key_End: "END", QtCore.Qt.Key_PageUp: "PAGE_UP", QtCore.Qt.Key_PageDown: "PAGE_DOWN",
    QtCore.Qt.Key_Left: "LEFT_ARROW", QtCore.Qt.Key_Right: "RIGHT_ARROW", QtCore.Qt.Key_Up: "UP_ARROW",
    QtCore.Qt.Key_Down: "DOWN_ARROW", QtCore.Qt.Key_Insert: "INSERT",
    QtCore.Qt.Key_BracketLeft: "LEFT_BRACKET", QtCore.Qt.Key_BracketRight: "RIGHT_BRACKET",
    QtCore.Qt.Key_Comma: "COMMA", QtCore.Qt.Key_Period: "PERIOD", QtCore.Qt.Key_Slash: "SLASH",
    QtCore.Qt.Key_Semicolon: "SEMI_COLON", QtCore.Qt.Key_Apostrophe: "QUOTE",
    QtCore.Qt.Key_QuoteLeft: "ACCENT_GRAVE", QtCore.Qt.Key_Equal: "EQUAL", QtCore.Qt.Key_Minus: "MINUS",
    QtCore.Qt.Key_Plus: "EQUAL", QtCore.Qt.Key_Backslash: "BACK_SLASH", QtCore.Qt.Key_Asterisk: "NUMPAD_ASTERIX",
    QtCore.Qt.Key_Menu: "APP",
}

last_item = None            # (keymap name, idname, props) of the last key run here (tests, status)


def event_type(ev):
    """Blender's event type of a Qt key event ('A', 'ONE', 'NUMPAD_PLUS', 'LEFT_BRACKET' …) or None."""
    key = ev.key()
    mods = ev.modifiers()
    keypad = bool(mods & QtCore.Qt.KeypadModifier)
    if QtCore.Qt.Key_A <= key <= QtCore.Qt.Key_Z:
        return chr(int(key))
    if QtCore.Qt.Key_F1 <= key <= QtCore.Qt.Key_F24:
        return f"F{int(key) - int(QtCore.Qt.Key_F1) + 1}"
    try:
        from .viewport import digit_of
        d = digit_of(ev)                       # Czech number row (+ ě š č …) gives digits too
    except Exception:
        d = None
    if d is None and QtCore.Qt.Key_0 <= key <= QtCore.Qt.Key_9:
        d = int(key) - int(QtCore.Qt.Key_0)
    if d is not None:
        return f"NUMPAD_{d}" if keypad else _DIGITS[d]
    text = ev.text() or ""
    if keypad and text in _NUMPAD:
        return _NUMPAD[text]
    if keypad and key in (QtCore.Qt.Key_Enter, QtCore.Qt.Key_Return):
        return "NUMPAD_ENTER"
    if key in _QT_KEYS:
        return _QT_KEYS[key]
    if text in _SYMBOLS:
        return _SYMBOLS[text]
    return None


def _mods(ev):
    m = ev.modifiers()
    return {"ctrl": bool(m & QtCore.Qt.ControlModifier), "shift": bool(m & QtCore.Qt.ShiftModifier),
            "alt": bool(m & QtCore.Qt.AltModifier), "oskey": bool(m & QtCore.Qt.MetaModifier)}


def _mod_ok(want, have):
    try:
        want = int(want)
    except Exception:
        want = 1 if want else 0
    return want == -1 or bool(want) == have          # -1 = KM_ANY


def find_item(ev, mode=None):
    """(keymap name, KeyMapItem) Blender would run for this key in the current Edit Mode, or None."""
    mode = mode or bpy.context.mode
    names = KEYMAPS.get(mode)
    etype = event_type(ev)
    if not names or not etype:
        return None
    have = _mods(ev)
    tries = [have]
    if have["ctrl"] and have["alt"] and not (QtCore.Qt.Key_A <= ev.key() <= QtCore.Qt.Key_Z):
        tries.append(dict(have, ctrl=False, alt=False))       # AltGr symbols ([ ] on a Czech keyboard)
    wm = bpy.context.window_manager
    for mods in tries:
        for kc in (wm.keyconfigs.user, wm.keyconfigs.default):
            if kc is None:
                continue
            for name in names:
                km = kc.keymaps.get(name)
                if km is None:
                    continue
                for it in km.keymap_items:
                    if (not it.active or it.map_type != "KEYBOARD" or it.type != etype
                            or it.value not in ("PRESS", "CLICK", "ANY")
                            or (it.key_modifier not in ("NONE", "", None))):
                        continue
                    if all(_mod_ok(getattr(it, k), mods[k]) for k in ("ctrl", "shift", "alt", "oskey")):
                        return name, it
            if kc is wm.keyconfigs.user:
                # the user configuration holds every keymap Blender uses – the default one only when it
                # is missing there
                if all(kc.keymaps.get(n) is not None for n in names):
                    break
    return None


def item_props(it):
    """The operator properties a keymap item sets, as a dict for bridge.run_op."""
    out = {}
    p = it.properties
    if p is None:
        return out
    for rp in p.bl_rna.properties:
        pid = rp.identifier
        if pid == "rna_type":
            continue
        try:
            if not p.is_property_set(pid):
                continue
            v = getattr(p, pid)
        except Exception:
            continue
        if rp.type == "POINTER" or rp.type == "COLLECTION":
            continue
        if getattr(rp, "is_array", False) or (getattr(rp, "array_length", 0) or 0) > 0:
            v = list(v)
        elif rp.type == "ENUM" and rp.is_enum_flag:
            v = set(v)
        out[pid] = v
    return out


def handle(vp, ev):
    """Runs Blender's shortcut of the current Edit Mode for this key. True when the key was used."""
    found = find_item(ev)
    if found is None:
        return False
    km_name, it = found
    idname, props = it.idname, item_props(it)
    global last_item
    last_item = (km_name, idname, dict(props))
    if not bridge.op_exists(idname) and not idname.startswith("wm."):
        return False
    run(vp, idname, props)
    return True


def _after(vp):
    from . import gizmo
    gizmo.invalidate(vp)
    vp.request_redraw()
    vp.selection_edited.emit()
    vp.update()


def wants_menu(idname, props):
    """True when Blender's invoke() of this operator would ask with a menu first (the value isn't given)."""
    if idname in COLLECTION_OPS:
        return "collection_index" not in props and not props.get("new_collection_name")
    prop = ENUM_MENU.get(idname)
    return bool(prop) and prop not in props


def set_tool(vp, name):
    """wm.tool_set_by_id: Qt Shell's tool for Blender's tool, or the tool's action once. False: unknown."""
    if name in TOOL_MAP:
        tool, variant = TOOL_MAP[name]
        vp.tools.set_tool(tool, variant)
        from . import gizmo
        v = gizmo.variant_info(tool, vp.tools.variant(tool))
        vp.status.emit(f"Tool: {v[1] if v else gizmo.TOOL_NAMES.get(tool, tool)}")
        vp.update()
        return True
    once = TOOL_ONCE.get(name)
    if once == "extrude":
        from . import editother
        editother.extrude()
        return True
    if once:
        bridge.run_op(once[0], dict(once[1]))
        _after(vp)
        return True
    vp.status.emit(f"{name.replace('builtin.', '').replace('_', ' ').title()}: this tool isn't in Qt Shell.")
    return True


# modal operators of Sculpt Mode that would run in Blender's hidden 3D view (mouse gestures, interactive
# filters / expand / voxel size) – Qt Shell says so instead of starting them
SCULPT_MODAL = ("gesture", "sculpt.expand", "voxel_size_edit", "brush_stroke", "sculpt.mesh_filter",
                "sculpt.cloth_filter", "sculpt.color_filter", "sculpt.trim_", "sculpt.project_line",
                "sculpt.face_set_edit", "sculpt.face_set_change_visibility", "paint.mask_box",
                "paint.mask_lasso", "paint.mask_line", "paint.hide_show_lasso", "sample_detail_size")


def run(vp, idname, props):
    if idname == "wm.radial_control" and getattr(vp, "sculpt", None) is not None:
        path = str(props.get("data_path_primary", "") or props.get("data_path", ""))
        from . import sculpt as _sc
        kind = "STRENGTH" if "strength" in path else ("RADIUS" if "size" in path else None)
        if kind is not None and _sc.active():
            vp.sculpt.modal = _sc.SizeModal(vp, kind)
            vp.update()
        else:
            vp.status.emit("This radial control isn't in Qt Shell – use the Sculpt panel.")
        return
    if idname == "wm.tool_set_by_id":
        name = str(props.get("name", ""))
        if name.startswith("builtin_brush.") and bpy.context.mode == "SCULPT":
            from . import sculpt as _sc
            _sc.activate_brush(name.split(".", 1)[1].replace("_", " ").title())
            return
        set_tool(vp, name)
        return
    if bpy.context.mode == "SCULPT" and any(m in idname for m in SCULPT_MODAL):
        vp.status.emit(f"{bridge.op_label(idname)}: interactive in Blender's own view – use the Sculpt panel "
                       "(Mask / Face Sets / Filters).")
        return
    if idname in PICK_OPS:
        from . import editother
        p = vp.mapFromGlobal(QtGui.QCursor.pos())
        if editother.select_linked_at(vp, p.x(), p.y(), deselect=bool(props.get("deselect"))):
            bridge.undo_push("Select Linked")
        else:
            vp.status.emit("Select Linked: nothing under the mouse.")
        _after(vp)
        return
    if idname in COLLECTION_OPS:
        collection_menu(vp, idname)
        return
    prop = ENUM_MENU.get(idname)
    if prop and prop not in props:
        from .qt_ui import fill_operator_enum_menu
        m = QtWidgets.QMenu(vp)
        m.setTitle(bridge.op_label(idname))
        title = m.addAction(bridge.op_label(idname))
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        title.setEnabled(False)
        fill_operator_enum_menu(m, idname, prop, props)
        m.triggered.connect(lambda _a: QtCore.QTimer.singleShot(0, lambda: _after(vp)))
        m.exec(QtGui.QCursor.pos())
        return
    bridge.run_op(idname, props)          # errors (poll failed …) go to the status bar via the log
    _after(vp)


def collection_menu(vp, idname):
    """Move to / Assign to bone collection (M / Shift+M): Blender's invoke menu lists the collections."""
    ob = bpy.context.edit_object
    arm = ob.data if ob is not None and ob.type == "ARMATURE" else None
    if arm is None:
        return
    m = QtWidgets.QMenu(vp)
    head = m.addAction(bridge.op_label(idname))
    f = head.font()
    f.setBold(True)
    head.setFont(f)
    head.setEnabled(False)
    cols = list(getattr(arm, "collections_all", []) or [])
    for i, bc in enumerate(cols):
        depth = 0
        p = getattr(bc, "parent", None)
        while p is not None and depth < 8:
            depth += 1
            p = getattr(p, "parent", None)
        act = m.addAction("    " * depth + bc.name)
        act.triggered.connect(lambda _=False, i=i: (bridge.run_op(idname, {"collection_index": i}), _after(vp)))
    m.addSeparator()
    new = m.addAction("New Bone Collection…")

    def _new():
        name, ok = QtWidgets.QInputDialog.getText(vp, "New Bone Collection", "Name:", text="Bones")
        if ok and name.strip():
            bridge.run_op(idname, {"new_collection_name": name.strip()})     # no index: a new one
            _after(vp)
    new.triggered.connect(_new)
    m.exec(QtGui.QCursor.pos())

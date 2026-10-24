"""Keyboard shortcuts of Qt Shell in one place (Edit → Keyboard Shortcuts…).

Every shortcut Qt Shell handles itself is an *action* with an id, a context (Window, 3D View …), a label
and default keys. The user's changes are stored in QSettings (`keymap/<id>`), the editors ask
`hit(id, event)` instead of comparing keys, window shortcuts are QActions kept in sync, and every tooltip /
menu text that mentions a shortcut is a template like "Play / Pause ({window.play})" – re-rendered when a
key changes, so the hints always show the current keys.

Key names: "G", "Shift+D", "Ctrl+Alt+Q", "Home", "Del", "Space", "F3", "1" (number row *or* numpad,
like Blender's emulation), "Num+1" (numpad only), "Num+." (numpad period).

Mouse navigation in the 3D view (Qt Preferences → Interface → Navigation): "BLENDER" or "MAYA".
"""
import re

from PySide6 import QtCore, QtGui

# ---------------------------------------------------------------- actions
ACTIONS = {}          # id → {"context", "label", "default": tuple}
CONTEXTS = []


def _a(aid, ctx, label, *keys):
    ACTIONS[aid] = {"context": ctx, "label": label, "default": tuple(keys)}
    if ctx not in CONTEXTS:
        CONTEXTS.append(ctx)


W, V, VM, VP, TL, GE, NE, UV, TE = ("Window", "3D View", "3D View · Edit Mesh", "3D View · Pose",
                                    "Timeline", "Graph Editor", "Node Editor", "UV Editor", "Text Editor")
OL = "Outliner"
RV = "Render View"
# window (work everywhere in the Qt Shell window)
_a("window.new", W, "New File", "Ctrl+N")
_a("window.open", W, "Open…", "Ctrl+O")
_a("window.open_recent", W, "Open Recent", "Ctrl+Shift+O")
_a("window.save", W, "Save", "Ctrl+S")
_a("window.save_as", W, "Save As…", "Ctrl+Shift+S")
_a("window.undo", W, "Undo", "Ctrl+Z")
_a("window.redo", W, "Redo", "Ctrl+Shift+Z", "Ctrl+Y")
_a("window.search", W, "Operator Search", "F3")
_a("window.render", W, "Render Image", "F12")
_a("window.render_anim", W, "Render Animation", "Ctrl+F12")
_a("window.show_render", W, "View Render", "F11")
_a("window.view_anim", W, "View Animation", "Ctrl+F11")
_a("window.quit", W, "Quit", "Ctrl+Q")
_a("window.play", W, "Play / Pause", "Space")
_a("window.play_reverse", W, "Play Backwards / Pause", "Ctrl+Shift+Space")
_a("window.frame_prev", W, "Previous Frame (Maya)", "Alt+,")
_a("window.frame_next", W, "Next Frame (Maya)", "Alt+.")
_a("window.maximize", W, "Maximize Area", "Ctrl+Space")
_a("window.quad", W, "Toggle Four Views", "Ctrl+Alt+Q")
# 3D view – all modes
_a("view3d.move", V, "Move", "G")
_a("view3d.rotate", V, "Rotate", "R")
_a("view3d.scale", V, "Scale", "S")
_a("view3d.insert_key", V, "Insert Keyframe", "I")
_a("view3d.delete_key", V, "Delete Keyframe", "Alt+I")
_a("view3d.duplicate", V, "Duplicate (Object)", "Shift+D")
_a("view3d.delete", V, "Delete (Object)", "X", "Del")
_a("view3d.add_menu", V, "Add Menu", "Shift+A")
_a("view3d.select_all", V, "Select All", "A")
_a("view3d.deselect_all", V, "Deselect All", "Alt+A")
_a("view3d.select_invert", V, "Invert Selection", "Ctrl+I")
_a("view3d.hide", V, "Hide Selected", "H")
_a("view3d.hide_unselected", V, "Hide Unselected", "Shift+H")
_a("view3d.reveal", V, "Reveal Hidden", "Alt+H")
_a("view3d.edit_toggle", V, "Toggle Edit Mode", "Tab")
_a("view3d.shading_pie", V, "Shading Menu", "Z")
_a("view3d.tool_menu", V, "Tool Menu", "Shift+Space")
_a("view3d.tool_select", V, "Select Tool", "W")
_a("view3d.tool_cursor", V, "Cursor Tool")
_a("view3d.tool_move", V, "Move Tool")
_a("view3d.tool_rotate", V, "Rotate Tool")
_a("view3d.tool_scale", V, "Scale Tool")
_a("view3d.tool_annotate", V, "Annotate Tool")
_a("view3d.tool_measure", V, "Measure Tool")
_a("view3d.tool_add", V, "Add Tool (Cube, Cone, Cylinder, Spheres)")
_a("view3d.ruler_remove", "3D View · Measure Tool", "Remove Ruler", "X", "Del", "Backspace")
_a("view3d.key_location", V, "Key Location")
_a("view3d.key_rotation", V, "Key Rotation")
_a("view3d.key_scale", V, "Key Scale")
_a("view3d.shading_wire", V, "Wireframe Shading")
_a("view3d.shading_solid", V, "Solid Shading")
_a("view3d.shading_material", V, "Material Preview Shading")
_a("view3d.toolbar", V, "Toolbar", "T")
_a("view3d.sidebar", V, "Sidebar", "N")
_a("view3d.frame_selected", V, "Frame Selected", "Num+.", ".")
_a("view3d.frame_all", V, "Frame All", "Home")
_a("view3d.view_front", V, "Front View", "1")
_a("view3d.view_back", V, "Back View", "Ctrl+1")
_a("view3d.view_right", V, "Right View", "3")
_a("view3d.view_left", V, "Left View", "Ctrl+3")
_a("view3d.view_top", V, "Top View", "7")
_a("view3d.view_bottom", V, "Bottom View", "Ctrl+7")
_a("view3d.view_camera", V, "Camera View", "0")
_a("view3d.view_persp", V, "Perspective / Orthographic", "5")
_a("view3d.view_flip", V, "View From the Opposite Side", "9")
_a("view3d.orbit_down", V, "Orbit Down", "2")
_a("view3d.orbit_up", V, "Orbit Up", "8")
_a("view3d.orbit_left", V, "Orbit Left", "4")
_a("view3d.orbit_right", V, "Orbit Right", "6")
_a("view3d.pan_down", V, "Pan Down", "Ctrl+2")
_a("view3d.pan_up", V, "Pan Up", "Ctrl+8")
_a("view3d.pan_left", V, "Pan Left", "Ctrl+4")
_a("view3d.pan_right", V, "Pan Right", "Ctrl+6")
# 3D view – edit mesh
_a("mesh.select_vert", VM, "Vertex Select Mode", "1")
_a("mesh.select_edge", VM, "Edge Select Mode", "2")
_a("mesh.select_face", VM, "Face Select Mode", "3")
_a("mesh.extrude", VM, "Extrude", "E")
_a("mesh.duplicate", VM, "Duplicate", "Shift+D")
_a("mesh.fill", VM, "Make Edge / Face", "F")
_a("mesh.select_linked", VM, "Select Linked", "Ctrl+L")
_a("mesh.select_invert", VM, "Invert Selection", "Ctrl+I")
_a("mesh.hide", VM, "Hide Selected", "H")
_a("mesh.hide_unselected", VM, "Hide Unselected", "Shift+H")
_a("mesh.reveal", VM, "Reveal Hidden", "Alt+H")
_a("mesh.delete_menu", VM, "Delete Menu", "X", "Del")
_a("mesh.uv_menu", VM, "UV Unwrap Menu", "U")
# 3D view – pose
_a("pose.clear_loc", VP, "Clear Location", "Alt+G")
_a("pose.clear_rot", VP, "Clear Rotation", "Alt+R")
_a("pose.clear_scale", VP, "Clear Scale", "Alt+S")
_a("pose.select_all", VP, "Select All Bones", "A")
_a("pose.deselect_all", VP, "Deselect All Bones", "Alt+A")
_a("pose.select_invert", VP, "Invert Bone Selection", "Ctrl+I")
_a("pose.hide", VP, "Hide Bones", "H")
_a("pose.hide_unselected", VP, "Hide Unselected Bones", "Shift+H")
_a("pose.reveal", VP, "Reveal Bones", "Alt+H")
# ---------------------------------------------------------------- Maya set (3D View areas)
# The 3D View areas have two sets of keys – Blender (above) and Maya – switched together with the mouse
# navigation (Qt Preferences → Interface). Only the differences from the Blender set are listed.
PROFILED = {V, VM, VP}
MAYA_DEFAULTS = {
    "view3d.move": (), "view3d.rotate": (), "view3d.scale": (),
    "view3d.tool_select": ("Q",), "view3d.tool_move": ("W",), "view3d.tool_rotate": ("E",),
    "view3d.tool_scale": ("R",),
    "view3d.insert_key": ("S",), "view3d.delete_key": (),
    "view3d.key_location": ("Shift+W",), "view3d.key_rotation": ("Shift+E",), "view3d.key_scale": ("Shift+R",),
    "view3d.duplicate": ("Ctrl+D",), "view3d.delete": ("Del", "Backspace"),
    "view3d.select_all": (), "view3d.deselect_all": (),
    "view3d.hide": ("Ctrl+H",), "view3d.hide_unselected": ("Alt+H",), "view3d.reveal": ("Ctrl+Shift+H",),
    "view3d.edit_toggle": ("F8",),
    "view3d.shading_pie": (), "view3d.shading_wire": ("4",), "view3d.shading_solid": ("5",),
    "view3d.shading_material": ("6",),
    "view3d.frame_selected": ("F",), "view3d.frame_all": ("A",),
    "view3d.view_front": ("Num+1",), "view3d.view_back": ("Ctrl+Num+1",), "view3d.view_right": ("Num+3",),
    "view3d.view_left": ("Ctrl+Num+3",), "view3d.view_top": ("Num+7",), "view3d.view_bottom": ("Ctrl+Num+7",),
    "view3d.view_camera": ("Num+0",), "view3d.view_persp": ("Num+5",), "view3d.view_flip": ("Num+9",),
    "view3d.orbit_down": ("Num+2",), "view3d.orbit_up": ("Num+8",), "view3d.orbit_left": ("Num+4",),
    "view3d.orbit_right": ("Num+6",), "view3d.pan_down": ("Ctrl+Num+2",), "view3d.pan_up": ("Ctrl+Num+8",),
    "view3d.pan_left": ("Ctrl+Num+4",), "view3d.pan_right": ("Ctrl+Num+6",),
    "mesh.select_vert": ("F9",), "mesh.select_edge": ("F10",), "mesh.select_face": ("F11",),
    "mesh.extrude": ("Ctrl+E",), "mesh.duplicate": ("Ctrl+D",), "mesh.fill": (),
    "mesh.hide": ("Ctrl+H",), "mesh.hide_unselected": ("Alt+H",), "mesh.reveal": ("Ctrl+Shift+H",),
    "mesh.delete_menu": ("Del", "Backspace"),
    "pose.select_all": (), "pose.deselect_all": (),
    "pose.hide": ("Ctrl+H",), "pose.hide_unselected": ("Alt+H",), "pose.reveal": ("Ctrl+Shift+H",),
}
PROFILES = {"BLENDER": "Blender", "MAYA": "Maya"}

# outliner
_a("outliner.show_selected", OL, "Show Selected", "F", "Num+.")
_a("outliner.show_hierarchy", OL, "Show Object Hierarchy", "Home")
_a("outliner.show_one_level", OL, "Show One Level", "Num++")
_a("outliner.hide_one_level", OL, "Hide One Level", "Num+-")
_a("outliner.expand_all", OL, "Expand / Collapse All", "Shift+A")
_a("outliner.select_all", OL, "Select All", "A")
_a("outliner.deselect_all", OL, "Deselect All", "Alt+A")
_a("outliner.select_invert", OL, "Invert Selection", "Ctrl+I")
_a("outliner.rename", OL, "Rename", "F2")
_a("outliner.delete", OL, "Delete", "X", "Del")
_a("outliner.hide", OL, "Hide", "H")
_a("outliner.unhide_all", OL, "Unhide All", "Alt+H")
_a("outliner.search", OL, "Search", "Ctrl+F")
_a("outliner.clear_search", OL, "Clear Search", "Alt+F")
_a("outliner.new_collection", OL, "New Collection", "C")
_a("outliner.move_to_collection", OL, "Move to Collection", "M")
_a("outliner.link_to_collection", OL, "Link to Collection", "Shift+M")
_a("outliner.exclude", OL, "Exclude from View Layer", "E")
_a("outliner.include", OL, "Include in View Layer", "Alt+E")
_a("outliner.parent", OL, "Parent to Active", "P")
_a("outliner.unparent", OL, "Clear Parent", "Shift+P")
# render view (Blender's render window / Image Editor with the Render Result)
AP = "Animation Player"
_a("anim.play", AP, "Play / Pause", "Space")
_a("anim.play_reverse", AP, "Play Backwards / Pause", "Shift+Space")
_a("anim.frame_prev", AP, "Previous Frame", "Left")
_a("anim.frame_next", AP, "Next Frame", "Right")
_a("anim.jump_start", AP, "First Frame", "Shift+Left", "Home")
_a("anim.jump_end", AP, "Last Frame", "Shift+Right", "End")
_a("anim.fit", AP, "Fit Image", "F", "Num+.")
_a("anim.close", AP, "Close", "Esc")
_a("timeline.delete_keys", TL, "Delete Selected Keys", "X", "Del")
_a("timeline.select_all", TL, "Select All Keys", "A")
_a("timeline.deselect_all", TL, "Deselect All Keys", "Alt+A")
_a("timeline.copy_keys", TL, "Copy Keys", "Ctrl+C")
_a("timeline.paste_keys", TL, "Paste Keys (at the current frame)", "Ctrl+V")
_a("timeline.frame_prev", TL, "Previous Frame", "Left")
_a("timeline.frame_next", TL, "Next Frame", "Right")
_a("timeline.jump_start", TL, "Jump to Start", "Shift+Left")
_a("timeline.jump_end", TL, "Jump to End", "Shift+Right")
_a("timeline.key_prev", TL, "Previous Keyframe", "Down")
_a("timeline.key_next", TL, "Next Keyframe", "Up")
_a("timeline.frame_all", TL, "Frame All", "Home")
_a("timeline.view_current", TL, "Go to Current Frame", "Num+0")
_a("timeline.zoom_in", TL, "Zoom In", "Num++", "Ctrl+=")
_a("timeline.zoom_out", TL, "Zoom Out", "Num+-", "Ctrl+-")
_a("timeline.marker_add", TL, "Add Marker", "M")
_a("timeline.marker_rename", TL, "Rename Marker", "F2")
_a("timeline.show_seconds", TL, "Show Seconds", "Ctrl+T")
_a("timeline.preview_set", TL, "Set Preview Range", "Ctrl+P")
_a("timeline.preview_clear", TL, "Clear Preview Range", "Alt+P")
_a("render.fit", RV, "Frame All", "Home")
_a("render.zoom_in", RV, "Zoom In", "Num++", "Ctrl+=")
_a("render.zoom_out", RV, "Zoom Out", "Num+-", "Ctrl+-")
_a("render.zoom_1_1", RV, "Zoom 1:1", "Num+1")
_a("render.next_slot", RV, "Next Render Slot", "J")
_a("render.prev_slot", RV, "Previous Render Slot", "Alt+J")
_a("render.sidebar", RV, "Sidebar", "N")
_a("render.save", RV, "Save", "Alt+S")
_a("render.save_as", RV, "Save As", "Shift+Alt+S")
_a("render.copy", RV, "Copy to Clipboard", "Ctrl+C")
_a("render.close", RV, "Close Render View", "Esc")
_a("render.toolbar", RV, "Toolbar", "T")
_a("render.tool_sample", RV, "Sample Tool")
_a("render.tool_annotate", RV, "Annotate Tool (again: next variant)")
# graph editor
_a("graph.frame_selected", GE, "Frame Selected Keys", "F")
_a("graph.frame_all", GE, "Frame All Curves", "A", "Home")
_a("graph.insert_keys", GE, "Insert Keys", "S", "I")
_a("graph.delete_keys", GE, "Delete Keys", "Del", "Backspace")
# node editor
_a("node.add", NE, "Add Node", "Shift+A")
_a("node.search", NE, "Node Search", "Tab")
_a("node.group", NE, "Enter / Exit Group", "Ctrl+Tab")
_a("node.delete", NE, "Delete Nodes", "X", "Del")
_a("node.select_all", NE, "Select All", "A")
_a("node.deselect_all", NE, "Deselect All", "Alt+A")
_a("node.mute", NE, "Mute", "M")
_a("node.hide", NE, "Collapse", "H")
_a("node.frame_all", NE, "Frame All", "Home", "F")
_a("node.frame_selected", NE, "Frame Selected", "Num+.")
# uv editor
_a("uv.move", UV, "Move", "G")
_a("uv.rotate", UV, "Rotate", "R")
_a("uv.scale", UV, "Scale", "S")
_a("uv.select_all", UV, "Select All", "A")
_a("uv.deselect_all", UV, "Deselect All", "Alt+A")
_a("uv.fit", UV, "Show 0–1", "Home")
# text editor
_a("text.run_script", TE, "Run Script", "Alt+P")
_a("text.run_selection", TE, "Run Selection", "Ctrl+Return", "Ctrl+Enter")
_a("text.complete", TE, "Auto-complete", "Ctrl+Space")
_a("text.run_line", TE, "Run Line (current line)", "Ctrl+Alt+Return", "Ctrl+Alt+Enter")
_a("text.run_all", TE, "Run All (whole text)", "Ctrl+Shift+Return", "Ctrl+Shift+Enter")
_a("text.save", TE, "Save Text", "Ctrl+S")
_a("text.find", TE, "Find", "Ctrl+F")
_a("text.replace", TE, "Find and Replace", "Ctrl+H")
_a("text.find_next", TE, "Find Next", "F3")
_a("text.find_prev", TE, "Find Previous", "Shift+F3")
_a("text.goto_line", TE, "Go to Line", "Ctrl+G")
_a("text.comment", TE, "Toggle Comment", "Ctrl+/")
_a("text.duplicate_line", TE, "Duplicate Line", "Ctrl+D")
_a("text.delete_line", TE, "Delete Line", "Ctrl+Shift+K")
_a("text.move_line_up", TE, "Move Line Up", "Alt+Up")
_a("text.move_line_down", TE, "Move Line Down", "Alt+Down")
_a("text.quick_help", TE, "Quick Help (documentation of the name)", "F1")
_a("text.outline", TE, "Outline (classes and functions)", "Ctrl+Shift+O")
_a("text.zoom_in", TE, "Bigger Font", "Ctrl+=", "Ctrl++")
_a("text.zoom_out", TE, "Smaller Font", "Ctrl+-")
_a("text.show_whitespace", TE, "Show Whitespace")

# mouse navigation (not editable – shown in the shortcuts window)
NAV_SCHEMES = {
    "BLENDER": (("Orbit", "Middle mouse drag  ·  Alt + Left drag"),
                ("Pan", "Shift + Middle drag"),
                ("Zoom", "Ctrl + Middle drag  ·  Wheel"),
                ("Select", "Left click / drag")),
    "MAYA": (("Orbit (tumble)", "Alt + Left drag"),
             ("Pan (track)", "Alt + Middle drag"),
             ("Zoom (dolly)", "Alt + Right drag  ·  Wheel"),
             ("Move with the active tool", "Middle drag (Move / Rotate / Scale tool)"),
             ("Select", "Left click / drag")),
}


# ---------------------------------------------------------------- storage
def _settings():
    return QtCore.QSettings("QtShell", "QtShell")


class _Notifier(QtCore.QObject):
    changed = QtCore.Signal()


notifier = _Notifier()
_cache = {}


def normalize(s):
    """Canonical key name: modifiers in the order Ctrl, Shift, Alt, Meta, Num, then the key."""
    s = (s or "").strip()
    if not s:
        return ""
    if s.endswith("++"):
        parts, key = s[:-2].split("+") if s[:-2] else [], "+"
    else:
        parts = s.split("+")
        key = parts.pop()
    alias = {"Control": "Ctrl", "Keypad": "Num", "Cmd": "Meta", "Win": "Meta"}
    mods = {alias.get(p.strip().capitalize(), p.strip().capitalize()) for p in parts if p.strip()}
    out = [m for m in ("Ctrl", "Shift", "Alt", "Meta", "Num") if m in mods]
    key = key.strip()
    key = {"Delete": "Del", "Escape": "Esc", "Period": ".", "Backtab": "Tab", "Enter": "Enter",
           "Return": "Return"}.get(key, key)
    if len(key) == 1:
        key = key.upper()
    return "+".join(out + [key])


def profiled(aid):
    """True for actions of the 3D View areas – they have a Blender and a Maya set."""
    return ACTIONS[aid]["context"] in PROFILED


def _profile(profile):
    return profile or nav_scheme()


def default_keys(aid, profile=None):
    a = ACTIONS[aid]
    keys_ = a["default"]
    if profiled(aid) and _profile(profile) == "MAYA" and aid in MAYA_DEFAULTS:
        keys_ = MAYA_DEFAULTS[aid]
    return tuple(normalize(k) for k in keys_)


def _skey(aid, profile=None):
    if profiled(aid) and _profile(profile) == "MAYA":
        return f"keymap_maya/{aid}"
    return f"keymap/{aid}"


def keys(aid, profile=None):
    """Current keys of the action (user setting or default) – for 3D View actions in the given set
    (default: the active set, which follows the mouse navigation)."""
    if aid not in ACTIONS:
        return ()
    ck = (aid, _profile(profile) if profiled(aid) else "")
    if ck in _cache:
        return _cache[ck]
    v = _settings().value(_skey(aid, profile), None)
    if v is None:
        res = default_keys(aid, profile)
    else:
        res = tuple(normalize(k) for k in str(v).split(";") if k.strip())
    _cache[ck] = res
    return res


def is_default(aid, profile=None):
    return keys(aid, profile) == default_keys(aid, profile)


def set_keys(aid, new_keys, profile=None):
    ks = [normalize(k) for k in new_keys if normalize(k)]
    st = _settings()
    if tuple(ks) == default_keys(aid, profile):
        st.remove(_skey(aid, profile))
    else:
        st.setValue(_skey(aid, profile), ";".join(ks))
    _cache.clear()
    _changed()


def reset(aid, profile=None):
    _settings().remove(_skey(aid, profile))
    _cache.clear()
    _changed()


def reset_all(profile=None):
    """Defaults for the common shortcuts and the given (default: active) 3D View set."""
    st = _settings()
    for aid in ACTIONS:
        st.remove(_skey(aid, profile))
    _cache.clear()
    _changed()


def display(k):
    """Readable key name: Num+1 → Numpad 1."""
    return k.replace("Num+.", "Numpad .").replace("Num+", "Numpad ")


def text(aid, sep=" / ", profile=None):
    """Current keys as text for hints, e.g. 'Ctrl+Shift+Z / Ctrl+Y'; '—' when unassigned."""
    ks = keys(aid, profile)
    return sep.join(display(k) for k in ks) if ks else "—"


def conflicts(aid, key, profile=None):
    """Other actions in the same area (context) that use key. A key of a more specific area (an editor,
    an edit mode) overriding a window / general 3D View key is intended and not reported."""
    ctx = ACTIONS[aid]["context"]
    k = normalize(key)
    return [other for other, a in ACTIONS.items()
            if other != aid and a["context"] == ctx and k in keys(other, profile)]


# ---------------------------------------------------------------- events
_DIGIT_ARROWS = {QtCore.Qt.Key_Down: 2, QtCore.Qt.Key_Left: 4, QtCore.Qt.Key_Right: 6, QtCore.Qt.Key_Up: 8,
                 QtCore.Qt.Key_Home: 7, QtCore.Qt.Key_End: 1, QtCore.Qt.Key_PageUp: 9,
                 QtCore.Qt.Key_PageDown: 3, QtCore.Qt.Key_Insert: 0, QtCore.Qt.Key_Clear: 5}
_MOD_KEYS = {QtCore.Qt.Key_Shift, QtCore.Qt.Key_Control, QtCore.Qt.Key_Alt, QtCore.Qt.Key_Meta,
             QtCore.Qt.Key_AltGr, QtCore.Qt.Key_unknown, QtCore.Qt.Key_CapsLock, QtCore.Qt.Key_NumLock}


def _digit(ev):
    try:
        from .viewport import digit_of
        return digit_of(ev)
    except Exception:
        k = int(ev.key()) - int(QtCore.Qt.Key_0)
        return k if 0 <= k <= 9 else None


def event_names(ev):
    """All names a key event can match: 'Ctrl+1' and, for the numpad, also 'Ctrl+Num+1'."""
    key = ev.key()
    if key in _MOD_KEYS:
        return set()
    mods = ev.modifiers()
    keypad = bool(mods & QtCore.Qt.KeypadModifier)
    parts = []
    if mods & QtCore.Qt.ControlModifier:
        parts.append("Ctrl")
    if mods & QtCore.Qt.ShiftModifier:
        parts.append("Shift")
    if mods & QtCore.Qt.AltModifier:
        parts.append("Alt")
    if mods & QtCore.Qt.MetaModifier:
        parts.append("Meta")
    d = _digit(ev)
    if d is None and keypad and key in _DIGIT_ARROWS:
        d = _DIGIT_ARROWS[key]                       # numpad with NumLock off
    if d is not None:
        name = str(d)
    elif key == QtCore.Qt.Key_Backtab:
        name = "Tab"
    else:
        name = QtGui.QKeySequence(int(key)).toString(QtGui.QKeySequence.PortableText) or ""
        name = normalize(name) if name else ""
        if "+" in name and name != "+":                # e.g. a dead key combination – keep only the key
            name = name.split("+")[-1]
    if not name:
        return set()
    names = {"+".join(parts + [name])}
    if keypad:
        names.add("+".join(parts + ["Num", name]))
    if name in ("Return", "Enter"):
        other = "Enter" if name == "Return" else "Return"
        names.add("+".join(parts + [other]))
    return {normalize(n) for n in names}


def hit(aid, ev, names=None):
    """True when the key event triggers action aid."""
    names = event_names(ev) if names is None else names
    return bool(names) and any(k in names for k in keys(aid))


_MODE_CTX = {"EDIT_MESH": "3D View · Edit Mesh", "POSE": "3D View · Pose"}


def view_owns(ev, mode):
    """True when the key event is a shortcut of the 3D view in the given mode."""
    names = event_names(ev)
    if not names:
        return False
    ctxs = {"3D View", _MODE_CTX.get(mode, "")}
    return any(a["context"] in ctxs and any(k in names for k in keys(aid)) for aid, a in ACTIONS.items())


def event_to_key(ev):
    """Name to store when the user presses a key in the shortcuts window (numpad keeps 'Num+')."""
    names = sorted(event_names(ev), key=lambda n: ("Num+" not in n, len(n)))
    return names[0] if names else ""


# ---------------------------------------------------------------- tooltips / menus / QActions
_tips = []            # (object, attribute setter name, template)
_actions = []         # (QAction, aid)
_TOKEN = re.compile(r"\{([a-z0-9_]+\.[a-z0-9_]+)\}")


def render(template):
    """'Play / Pause ({window.play})' → 'Play / Pause (Space)'."""
    return _TOKEN.sub(lambda m: text(m.group(1)), template)


def tip(obj, template, setter="setToolTip"):
    """Sets obj's tooltip (or text with setter='setText') from a template and keeps it up to date."""
    getattr(obj, setter)(render(template))
    _tips.append((obj, setter, template))
    return obj


def bind_action(action, aid):
    """A QAction whose shortcuts follow the keymap."""
    action.setShortcuts([QtGui.QKeySequence(k) for k in keys(aid)])
    _actions.append((action, aid))
    return action


def _changed():
    alive = []
    for obj, setter, template in _tips:
        try:
            getattr(obj, setter)(render(template))
            alive.append((obj, setter, template))
        except RuntimeError:
            pass
    _tips[:] = alive
    acts = []
    for act, aid in _actions:
        try:
            act.setShortcuts([QtGui.QKeySequence(k) for k in keys(aid)])
            acts.append((act, aid))
        except RuntimeError:
            pass
    _actions[:] = acts
    notifier.changed.emit()


# ---------------------------------------------------------------- navigation scheme
def nav_scheme():
    v = _settings().value("viewport/navigation", "BLENDER")
    return v if v in NAV_SCHEMES else "BLENDER"


def set_nav_scheme(scheme):
    """Switches the 3D View controls: mouse navigation and the 3D View key set (Blender / Maya)."""
    _settings().setValue("viewport/navigation", scheme)
    _cache.clear()
    _changed()

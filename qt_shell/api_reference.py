"""Command reference of the Qt Shell Python API – one entry per command, like Maya's command documentation:
synopsis, return value, description, parameters (flags) and a Python example.

- docs/API.md § "Command reference" is generated from this file: `python3 tools/make_api_reference.py`.
- The Text editor's Quick Help (F1) shows the entry of the name under the cursor (`lookup(obj)`).
- The test `_t231.py` runs every example (`run=False` entries are not run – the reason is in `skip`) and
  checks every synopsis against the real signature.

Keys are "<module>.<qualified name>" of the real function / method (`api.status`,
`sequencer.VideoSequencer.cut`), so `lookup()` finds the entry from the object itself.
"""

GROUPS = [
    ("window", "Window and status bar"),
    ("docks", "Docks (panels)"),
    ("menus", "Menu items and shortcuts"),
    ("views", "3D views"),
    ("layout", "Viewport layout"),
    ("overlays", "Overlays"),
    ("events", "Events"),
    ("owner", "Ownership and cleanup"),
    ("tools", "Toolbar tools and operators"),
    ("scripts", "Scripts (qt_shell.scripts)"),
    ("shelf", "Shelf files (qt_shell.shelf)"),
    ("timeline", "Timeline"),
    ("outliner", "Outliner"),
    ("graph", "Graph editor"),
    ("uv", "UV editor"),
    ("render", "Render View"),
    ("player", "Animation Player"),
    ("image", "Image editor"),
    ("sequencer", "Video Sequencer"),
    ("bluepencil", "Blue Pencil, burn-in and annotations"),
    ("updates", "Updates"),
]

COMMANDS = []


def C(key, group, synopsis, returns, desc, params=(), example="", run=True, skip=""):
    """One command. params: [(name, type, description)]; example: Python code (runs as it is)."""
    COMMANDS.append(dict(key=key, group=group, synopsis=synopsis, returns=returns, desc=desc,
                         params=list(params), example=example.strip("\n"), run=run, skip=skip))


# =========================================================================================== window
C("api.is_running", "window", "is_running()", "bool",
  "True when the Qt Shell window exists. Use it before calling functions that need the window.",
  example='''
import qt_shell.api as qs

if qs.is_running():
    qs.status("Qt Shell is open")
''')

C("api.main_window", "window", "main_window()", "QMainWindow or None",
  "The Qt main window – use it as the parent of your own dialogs. Its attributes are not part of the stable API.",
  example='''
import qt_shell.api as qs
from PySide6 import QtWidgets

box = QtWidgets.QMessageBox(qs.main_window())
box.setWindowTitle("My tool")
box.setText("Done")
box.show()                      # box.exec() waits for the user instead
box.close()
''')

C("main_window.MainWindow.restart_blender", "window", "restart_blender(confirm=True)", "None",
  "Quits Blender and starts it again with the current file (when it is saved). With confirm=True it asks "
  "Save / Discard / Cancel when the file has unsaved changes.",
  [("confirm", "bool", "Ask about unsaved changes first.")],
  example='''
import qt_shell.api as qs

qs.main_window().restart_blender()            # File → Restart Blender
''', run=False, skip="restarts Blender")

C("api.status", "window", "status(text, timeout_ms=4000)", "None",
  "Shows a message in the status bar. Every message is also written to the Console and kept in the status history.",
  [("text", "str", "The message (converted with str())."),
   ("timeout_ms", "int", "How long it stays, in milliseconds; 0 = until the next message.")],
  example='''
import qt_shell.api as qs

qs.status("Export finished")                 # 4 seconds
qs.status("Rendering… please wait", 0)       # stays until the next message
''')

C("api.status_history", "window", "status_history()", "list of (time, text)",
  "The status bar messages of this Blender session, newest last (at most 200). In the UI: click the status bar.",
  example='''
import qt_shell.api as qs

qs.status("Hello")
for stamp, text in qs.status_history()[-5:]:
    print(stamp, text)                         # 19:25:59 Hello
''')

# =========================================================================================== docks
C("api.add_dock", "docks", 'add_dock(dock_id, title, factory, area="right", visible=True)', "str – the dock id",
  "Adds a dockable panel; it also appears in the Window menu. The factory runs every time the Qt window is "
  "built and must create a new widget each time. Calling it again with the same id replaces the dock.",
  [("dock_id", "str", "Unique id."),
   ("title", "str", "Title of the dock."),
   ("factory", "fn() -> QWidget", "Creates the dock's widget."),
   ("area", "str", '"left", "right", "bottom" or "top" – where it appears the first time.'),
   ("visible", "bool", "Shown the first time (later the saved state wins).")],
  example='''
import qt_shell.api as qs

def make_panel():
    from PySide6 import QtWidgets
    w = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(w)
    for name in ("TOP", "FRONT", "RIGHT"):
        b = QtWidgets.QPushButton(name.title(), w)      # give every widget its parent
        b.clicked.connect(lambda _=False, n=name: qs.set_view(n))
        lay.addWidget(b)
    lay.addStretch(1)
    return w

qs.add_dock("my_views", "My Views", make_panel, area="left")
qs.remove_dock("my_views")
''')

C("api.remove_dock", "docks", "remove_dock(dock_id)", "None",
  "Removes a dock added with add_dock().",
  [("dock_id", "str", "The id given to add_dock().")],
  example='''
import qt_shell.api as qs
from PySide6 import QtWidgets

qs.add_dock("notes", "Notes", lambda: QtWidgets.QTextEdit(), area="right")
qs.remove_dock("notes")
''')

# =========================================================================================== menus
C("api.add_menu_action", "menus",
  "add_menu_action(menu, text, callback, shortcut=None, tooltip=None, action_id=None)", "str – the action id",
  "Adds an item to a menu of the menu bar (after a separator at its end). A menu that does not exist yet is "
  "created before Help. Calling it again with the same id replaces the item.",
  [("menu", "str", "Title of a top-level menu: File, Edit, Add, Object, Select, View, Render, Window, Help or a new one."),
   ("text", "str", "Text of the item."),
   ("callback", "fn()", "Runs in Blender's context."),
   ("shortcut", "str", 'Optional key, e.g. "Ctrl+Alt+H" – active in the whole window.'),
   ("tooltip", "str", "Optional tooltip / status tip."),
   ("action_id", "str", 'Optional id; default "<menu>/<text>".')],
  example='''
import qt_shell.api as qs

qs.add_menu_action("Tools", "Frame Selected", qs.frame_selected,
                   shortcut="Ctrl+Alt+F", tooltip="Fit the selection into the view", action_id="my_frame")
qs.remove_menu_action("my_frame")
''')

C("api.remove_menu_action", "menus", "remove_menu_action(action_id)", "None",
  "Removes a menu item (and its shortcut) added with add_menu_action().",
  [("action_id", "str", "The returned id.")],
  example='''
import qt_shell.api as qs

aid = qs.add_menu_action("Tools", "Say Hello", lambda: qs.status("Hello"))
qs.remove_menu_action(aid)                    # aid == "Tools/Say Hello"
''')

# =========================================================================================== views
C("api.get_view", "views", "get_view()", "dict or None",
  "The active 3D view: target (x, y, z), distance, yaw and pitch (radians), ortho, camera_view and name. "
  "None when Qt Shell is not running.",
  example='''
import math
import qt_shell.api as qs

v = qs.get_view()
print(v["name"], round(math.degrees(v["yaw"])), v["distance"])
''')

C("api.set_view", "views", "set_view(preset=None, target=None, distance=None, yaw=None, pitch=None, ortho=None)",
  "bool – False when Qt Shell is not running",
  "Changes the active 3D view: a preset, or the orbit view directly (this leaves the camera view).",
  [("preset", "str", '"FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM" or "CAMERA" (toggles the camera view).'),
   ("target", "(x, y, z)", "The point the view orbits around."),
   ("distance", "float", "Distance from the target."),
   ("yaw", "float", "Rotation around Z, radians."),
   ("pitch", "float", "Tilt, radians: 0 = from above, π/2 = horizontal."),
   ("ortho", "bool", "Orthographic (True) or perspective (False).")],
  example='''
import math
import qt_shell.api as qs

qs.set_view("TOP")
qs.set_view(target=(0, 0, 1), distance=12, yaw=math.radians(45), pitch=math.radians(60), ortho=False)
v = qs.get_view()
qs.set_view(yaw=v["yaw"] + math.radians(15))          # orbit 15°
''')

C("api.frame_all", "views", "frame_all()", "None",
  "Fits all visible objects into the active view (Home).",
  example='''
import qt_shell.api as qs

qs.frame_all()
''')

C("api.frame_selected", "views", "frame_selected()", "None",
  "Fits the selected objects into the active view (Numpad . / Maya F).",
  example='''
import bpy
import qt_shell.api as qs

bpy.ops.mesh.primitive_monkey_add(location=(4, 0, 0))   # the new object is selected
qs.frame_selected()
''')

C("api.redraw", "views", "redraw()", "None",
  "Redraws all 3D views (scene and overlays). Call it after changing what an overlay draws.",
  example='''
import qt_shell.api as qs

qs.redraw()
''')

C("api.viewport", "views", "viewport()", "QWidget or None",
  "The active 3D view widget. Prefer the view functions – its attributes are not stable API.",
  example='''
import qt_shell.api as qs

vp = qs.viewport()
print(vp.width(), vp.height())
''')

C("api.viewport_size", "views", "viewport_size()", "(width, height) or None",
  "Size of the active view in Qt (logical) pixels.",
  example='''
import qt_shell.api as qs

w, h = qs.viewport_size()
qs.status(f"The view is {w} × {h} px")
''')

C("api.view_matrix", "views", "view_matrix()", "mathutils.Matrix or None",
  "The 4×4 view matrix of the active view.",
  example='''
import qt_shell.api as qs

m = qs.view_matrix()
print(m.inverted().translation)                 # where the view's eye is
''')

C("api.projection_matrix", "views", "projection_matrix()", "mathutils.Matrix or None",
  "The 4×4 projection matrix of the active view for its current size.",
  example='''
import qt_shell.api as qs

full = qs.projection_matrix() @ qs.view_matrix()    # world → clip space
print(full)
''')

C("api.project", "views", "project(co)", "(x, y) or None",
  "World coordinates → pixel position in the active view widget ((0, 0) = top-left); None when the point "
  "is behind the view.",
  [("co", "Vector / (x, y, z)", "A point in world space.")],
  example='''
import bpy
import qt_shell.api as qs

ob = bpy.context.view_layer.objects.active or bpy.context.scene.objects[0]
print(ob.name, qs.project(ob.matrix_world.translation))
''')

# =========================================================================================== layout
C("api.set_viewport_layout", "layout", "set_viewport_layout(mode)", "bool – False when Qt Shell is not running",
  "Splits the 3D view. Each view keeps its own camera; \"quad\" sets and frames Top / Front / Right. Raises "
  "ValueError for an unknown mode.",
  [("mode", "str", '"single", "side" (two side by side), "stacked" (one above the other) or "quad" '
                   "(Top · Perspective / Front · Right).")],
  example='''
import qt_shell.api as qs

qs.set_viewport_layout("quad")
qs.set_viewport_layout("single")
''')

C("api.viewport_layout", "layout", "viewport_layout()", "str or None",
  'The current layout: "single", "side", "stacked" or "quad".',
  example='''
import qt_shell.api as qs

if qs.viewport_layout() != "single":
    qs.set_viewport_layout("single")
''')

C("api.viewports", "layout", "viewports()", "list of QWidget",
  "All visible 3D view widgets of the current layout.",
  example='''
import qt_shell.api as qs

qs.set_viewport_layout("side")
print(len(qs.viewports()))                     # 2
qs.set_viewport_layout("single")
''')

# =========================================================================================== overlays
C("api.add_overlay", "overlays", "add_overlay(overlay_id, fn)", "str – the overlay id",
  "Draws over every 3D view with Qt's QPainter. fn(painter, ctx) runs on every repaint – keep it fast. ctx has "
  "width, height, view_matrix, projection_matrix and project(co) → QPointF or None. A failing overlay is removed.",
  [("overlay_id", "str", "Unique id; the same id replaces the overlay."),
   ("fn", "fn(painter, ctx)", "The drawing function.")],
  example='''
import bpy
import qt_shell.api as qs

def draw_names(painter, ctx):
    from PySide6 import QtCore, QtGui
    painter.setPen(QtGui.QColor("#ffcc33"))
    for ob in bpy.context.visible_objects:
        p = ctx.project(ob.matrix_world.translation)
        if p is not None:
            painter.drawText(p + QtCore.QPointF(8, -8), ob.name)

qs.add_overlay("names", draw_names)
qs.redraw()
qs.remove_overlay("names")
''')

C("api.remove_overlay", "overlays", "remove_overlay(overlay_id)", "None",
  "Removes an overlay.",
  [("overlay_id", "str", "The id given to add_overlay().")],
  example='''
import qt_shell.api as qs

qs.add_overlay("frame", lambda p, ctx: p.drawRect(4, 4, ctx.width - 8, ctx.height - 8))
qs.remove_overlay("frame")
''')

# =========================================================================================== events
C("api.on", "events", "on(event, fn)", "handle for off()",
  "Calls fn when something happens. Events (qt_shell.api.EVENTS): data, selection, frame(frame), mode(mode), "
  "file, undo, render, operator(idname, props, result), playback(playing), window(main_window), "
  "script(key, state). Raises ValueError for an unknown name.",
  [("event", "str", "Event name."),
   ("fn", "callable", "The handler; its arguments depend on the event.")],
  example='''
import qt_shell.api as qs

h = qs.on("frame", lambda f: qs.status(f"Frame {f}", 1000))
qs.off(h)
''')

C("api.off", "events", "off(handle)", "None",
  "Removes an event handler.",
  [("handle", "", "What on() returned.")],
  example='''
import qt_shell.api as qs

h = qs.on("selection", lambda: print("selection changed"))
qs.off(h)
''')

# =========================================================================================== owner
C("api.owner", "owner", "owner(name)", "context manager",
  "Everything registered inside `with owner(name):` belongs to that owner and can be removed with cleanup(name) "
  "– the easiest clean-up for an add-on's unregister(). Scripts run by Qt Shell are owners automatically.",
  [("name", "str", "Owner name, e.g. your add-on's __package__.")],
  example='''
import qt_shell.api as qs

with qs.owner("my_addon"):
    qs.add_menu_action("Tools", "Hello", lambda: qs.status("Hello"))
    qs.on("frame", lambda f: None)
print(qs.owned("my_addon"))
qs.cleanup("my_addon")
''')

C("api.current_owner", "owner", "current_owner()", "str or None",
  "The owner of what is registered right now (inside `with owner():` or a script run by Qt Shell).",
  example='''
import qt_shell.api as qs

with qs.owner("my_addon"):
    print(qs.current_owner())                  # my_addon
''')

C("api.owned", "owner", "owned(name)", "list of (kind, id)",
  'What an owner registered: [("dock", "my_panel"), ("action", "Tools/Hello"), ("overlay", …), ("event", "h3")].',
  [("name", "str", "Owner name.")],
  example='''
import qt_shell.api as qs

with qs.owner("demo"):
    qs.add_overlay("demo_dot", lambda p, ctx: p.drawEllipse(10, 10, 6, 6))
print(qs.owned("demo"))                        # [('overlay', 'demo_dot')]
qs.cleanup("demo")
''')

C("api.cleanup", "owner", "cleanup(name)", "int – number of removed items",
  "Removes everything an owner registered (docks, menu items, overlays, event handlers).",
  [("name", "str", "Owner name.")],
  example='''
import qt_shell.api as qs

with qs.owner("demo"):
    qs.add_menu_action("Tools", "Demo", lambda: None)
print(qs.cleanup("demo"))                      # 1
''')

# =========================================================================================== tools
C("api.set_tool", "tools", "set_tool(tool, variant=None)", "bool",
  "Activates a tool of the 3D viewport's toolbar (shared by all views). qt_shell.api.TOOLS lists the tools and "
  "their variants. Raises ValueError for an unknown tool or variant.",
  [("tool", "str", "SELECT, CURSOR, MOVE, ROTATE, SCALE, TRANSFORM, ANNOTATE, MEASURE, ADD or BLUE_PENCIL."),
   ("variant", "str", "SELECT: TWEAK BOX CIRCLE LASSO · SCALE: SCALE CAGE · ANNOTATE: FREEHAND LINE POLYGON "
                      "ERASER · ADD: CUBE CONE CYLINDER UV_SPHERE ICO_SPHERE · BLUE_PENCIL: PENCIL BRUSH ERASER "
                      "TEXT LINE ARROW ELLIPSE RECT TRANSFORM.")],
  example='''
import qt_shell.api as qs

old = qs.active_tool()
qs.set_tool("SELECT", "LASSO")
qs.set_tool("MEASURE")
qs.set_tool(*old)                              # back to what it was
''')

C("api.active_tool", "tools", "active_tool()", "(tool, variant) or None",
  "The active toolbar tool, e.g. ('SELECT', 'BOX') or ('MEASURE', None).",
  example='''
import qt_shell.api as qs

tool, variant = qs.active_tool()
qs.status(f"Tool: {tool} {variant or ''}")
''')

C("api.run_op", "tools", "run_op(idname, invoke=False, **props)", "set – the operator's result",
  "Runs a Blender operator the way Qt Shell's menus do: in a 3D view context, with Qt Shell's own handling "
  "where it has one (render.render opens the Render View like F12, transform.translate starts the interactive "
  "move) and an undo step.",
  [("idname", "str", 'Operator id, e.g. "mesh.primitive_cube_add".'),
   ("invoke", "bool", "Run it like a click (INVOKE_DEFAULT) instead of with the given values."),
   ("**props", "", "Operator properties.")],
  example='''
import qt_shell.api as qs

qs.run_op("mesh.primitive_cube_add", size=2, location=(0, 3, 0))
qs.run_op("object.shade_smooth")
''')

# =========================================================================================== scripts
C("scripts.key_for_text", "scripts", "key_for_text(t)", "str",
  'The script key of a bpy.types.Text: "text:<name>" (saved in the .blend) or "file:<path>".',
  [("t", "bpy.types.Text", "A text.")],
  example='''
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("hello.py")
print(s.key_for_text(t))                       # text:hello.py
bpy.data.texts.remove(t)
''')

C("scripts.run", "scripts", "run(key)", "result with .ok, .output, .error_line, .removed",
  "Runs a script (unloads it first when it is loaded – a reload). What it registers is recorded for unload().",
  [("key", "str", "Script key.")],
  example='''
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("hello.py")
t.write('import qt_shell.api as qs\\nqs.add_menu_action("Tools", "Hello", lambda: qs.status("Hi"))\\n')
r = s.run(s.key_for_text(t))
print(r.ok, s.items(s.key_for_text(t)))
s.unload(s.key_for_text(t))
bpy.data.texts.remove(t)
''')

C("scripts.unload", "scripts", "unload(key)", "result (.removed = number of removed items)",
  "Calls the script's unregister() (when it has one) and removes what it registered and is still there.",
  [("key", "str", "Script key.")],
  example='''
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("overlay.py")
t.write('import qt_shell.api as qs\\nqs.add_overlay("dot", lambda p, c: p.drawEllipse(9, 9, 5, 5))\\n')
key = s.key_for_text(t)
s.run(key)
print(s.unload(key).removed)                    # 1
bpy.data.texts.remove(t)
''')

C("scripts.unload_all", "scripts", "unload_all()", "None",
  "Unloads every loaded script.",
  example='''
import qt_shell.scripts as s

s.unload_all()
''')

C("scripts.is_loaded", "scripts", "is_loaded(key)", "bool",
  "True when the script ran in this session, registered something and was not unloaded.",
  [("key", "str", "Script key.")],
  example='''
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("demo.py")
t.write('import qt_shell.api as qs\\nqs.on("frame", lambda f: None)\\n')
key = s.key_for_text(t)
s.run(key)
print(s.is_loaded(key))                         # True
s.unload(key)
bpy.data.texts.remove(t)
''')

C("scripts.info", "scripts", "info(key)", "dict or None",
  '{"status": "loaded" | "ran" | "error", "items", "error_line", "time", "has_unregister"}; None for a script '
  "that has not run.",
  [("key", "str", "Script key.")],
  example='''
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("calc.py")
t.write("x = 6 * 7\\n")
key = s.key_for_text(t)
s.run(key)
print(s.info(key)["status"])                    # ran
bpy.data.texts.remove(t)
''')

C("scripts.items", "scripts", "items(key)", "list of str",
  "Human-readable list of what a script registered.",
  [("key", "str", "Script key.")],
  example='''
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("menu.py")
t.write('import qt_shell.api as qs\\nqs.add_menu_action("Tools", "Ping", lambda: None)\\n')
key = s.key_for_text(t)
s.run(key)
print(s.items(key))
s.unload(key)
bpy.data.texts.remove(t)
''')

C("scripts.all_keys", "scripts", "all_keys()", "list of str",
  "Keys of all known scripts: texts of the .blend, files in the script list and scripts that ran.",
  example='''
import qt_shell.scripts as s

for key in s.all_keys():
    info = s.info(key)
    if info:
        print(f'{info["status"]:8} {s.location(key)}')
''')

C("scripts.location", "scripts", "location(key)", "str",
  'Where a script lives: its file path, or "in the .blend" for a text without a file.',
  [("key", "str", "Script key.")],
  example='''
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("where.py")
print(s.location(s.key_for_text(t)))            # in the .blend
bpy.data.texts.remove(t)
''')

C("scripts.add_file", "scripts", "add_file(path)", "str – the script key",
  "Adds a .py file to the script list (config/qt_shell/scripts.json). A file already in the list is not "
  "added twice, so add_file() also just turns a path into its key.",
  [("path", "str", "A .py file.")],
  example='''
import os, tempfile
import qt_shell.scripts as s

path = os.path.join(tempfile.gettempdir(), "qt_start.py")
open(path, "w").write('print("Qt Shell started")\\n')
key = s.add_file(path)
s.remove_file(key)
''')

C("scripts.remove_file", "scripts", "remove_file(key)", "None",
  "Removes a file from the script list (the file itself is kept) and unloads it.",
  [("key", "str", "Script key.")],
  example='''
import os, tempfile
import qt_shell.scripts as s

path = os.path.join(tempfile.gettempdir(), "old_tool.py")
open(path, "w").write("")
s.remove_file(s.add_file(path))
''')

C("scripts.set_autoload", "scripts", "set_autoload(key, on)", "None",
  "Turns auto-load on / off: a file in the script list runs on every start of Qt Shell (once per session); a "
  "text gets the property qtshell_autoload and runs when its .blend is opened (needs Auto Run Python Scripts).",
  [("key", "str", "Script key."), ("on", "bool", "Auto-load on / off.")],
  example='''
import os, tempfile
import qt_shell.scripts as s

path = os.path.join(tempfile.gettempdir(), "qt_start.py")
open(path, "w").write('import qt_shell.api as qs\\nqs.status("Welcome")\\n')
key = s.add_file(path)
s.set_autoload(key, True)
print(s.autoload(key))                          # True
s.set_autoload(key, False)
s.remove_file(key)
''')

C("scripts.autoload", "scripts", "autoload(key)", "bool",
  "True when auto-load is on for the script.",
  [("key", "str", "Script key.")],
  example='''
import qt_shell.scripts as s

for key, on in s.managed_files():
    print(key, s.autoload(key))
''')

C("scripts.managed_files", "scripts", "managed_files()", "list of (key, autoload)",
  "The .py files in the script list (config/qt_shell/scripts.json).",
  example='''
import qt_shell.scripts as s

print(s.managed_files())
''')

# =========================================================================================== shelf
C("shelf.export_shelves", "shelf", "export_shelves(path, names=None, data=None)", "int – shelves saved",
  "Writes shelves to a .json file (the save button next to the shelf's +).",
  [("path", "str", "The .json file."),
   ("names", "list of str", "Shelf names; None = all."),
   ("data", "dict", "Shelf data to write instead of the user's shelves (internal use).")],
  example='''
import os, tempfile
from qt_shell import shelf

path = os.path.join(tempfile.gettempdir(), "modeling.json")
print(shelf.export_shelves(path, ["Modeling"]))     # 1
''')

C("shelf.import_shelves", "shelf", "import_shelves(path, data=None)", "list of str – the added names",
  'Adds the shelves of a saved file as new tabs (a name that exists gets " (2)" …).',
  [("path", "str", "A file written by export_shelves()."),
   ("data", "dict", "Shelf data to add to instead of the user's shelves (internal use).")],
  example='''
from qt_shell import shelf

shelf.import_shelves("C:/shelves/modeling.json")
''', run=False, skip="changes the user's shelves")

C("shelf.shelf_folder", "shelf", "shelf_folder()", "str",
  "The default folder for shelf files: config/qt_shell/shelves (created when missing).",
  example='''
import os
from qt_shell import shelf

print(os.listdir(shelf.shelf_folder()))
''')

# =========================================================================================== timeline
TL = "import qt_shell\n\ntl = qt_shell.api.timeline()\n"

C("api.timeline", "timeline", "timeline()", "Timeline or None",
  "The Timeline of the Qt Shell window (None when Qt Shell is not open).",
  example=TL + 'print(tl.view_range())')

C("timeline.Timeline.set_view_range", "timeline", "set_view_range(first, last)", "None",
  "Shows frames first … last in the time bar (zoom / pan).",
  [("first", "float", "First visible frame."), ("last", "float", "Last visible frame.")],
  example=TL + "tl.set_view_range(0, 120)")

C("timeline.Timeline.view_range", "timeline", "view_range()", "(first, last)",
  "The first and last visible frame of the time bar.",
  example=TL + "first, last = tl.view_range()\nprint(first, last)")

C("timeline.Timeline.zoom", "timeline", "zoom(factor)", "None",
  "Zooms the time bar around its middle: factor < 1 zooms in, > 1 out.",
  [("factor", "float", "0.5 = twice as close.")],
  example=TL + "tl.zoom(0.5)\ntl.zoom(2)")

C("timeline.Timeline.frame_all", "timeline", "frame_all()", "None",
  "Shows the whole scene range (or the preview range when it is on).",
  example=TL + "tl.frame_all()")

C("timeline.Timeline.play", "timeline", "play(reverse=False)", "None",
  "Starts playback (from the playback cache when it is filled).",
  [("reverse", "bool", "Play backwards.")],
  example=TL + "tl.play()\ntl.stop()")

C("timeline.Timeline.stop", "timeline", "stop()", "None",
  "Stops playback.",
  example=TL + "tl.play(reverse=True)\ntl.stop()")

C("timeline.Timeline.toggle_play", "timeline", "toggle_play(reverse=False)", "None",
  "Play / pause like Space; reverse=True plays backwards. The other direction while playing turns around.",
  [("reverse", "bool", "Backwards.")],
  example=TL + "tl.toggle_play()\nprint(tl.is_playing())     # True\ntl.toggle_play()")

C("timeline.Timeline.is_playing", "timeline", "is_playing()", "bool",
  "True while the Timeline plays.",
  example=TL + "if tl.is_playing():\n    tl.stop()")

C("timeline.Timeline.step", "timeline", "step(n)", "None",
  "Moves the current frame by n frames (respects the preview range and the loop mode).",
  [("n", "int", "Frames, negative = back.")],
  example=TL + "tl.step(1)\ntl.step(-1)")

C("timeline.Timeline.set_loop_mode", "timeline", "set_loop_mode(mode)", "None",
  "What playback does at the end of the range.",
  [("mode", "str", '"LOOP" (continuous), "ONCE" (stop at the end) or "OSCILLATE" (ping-pong, Maya).')],
  example=TL + 'tl.set_loop_mode("OSCILLATE")\ntl.set_loop_mode("LOOP")')

C("timeline.Timeline.set_preview_range", "timeline", "set_preview_range(on, start=None, end=None)", "None",
  "Preview range on / off (Blender's clock button); start / end also set it.",
  [("on", "bool", "On / off."), ("start", "int", "First frame."), ("end", "int", "Last frame.")],
  example=TL + "tl.set_preview_range(True, 10, 50)\ntl.set_preview_range(False)")

C("timeline.Timeline.set_fps", "timeline", "set_fps(fps, base=1.0)", "None",
  "The scene frame rate (Output Properties → Frame Rate): fps / base frames per second.",
  [("fps", "int", "Frames per second."), ("base", "float", "Divisor – 1.001 for NTSC rates.")],
  example=TL + "tl.set_fps(25)\ntl.set_fps(30, 1.001)      # 29.97 fps\ntl.set_fps(24)")

C("timeline.Timeline.set_show_seconds", "timeline", "set_show_seconds(on)", "None",
  "Shows seconds instead of frames in the time bar.",
  [("on", "bool", "Seconds on / off.")],
  example=TL + "tl.set_show_seconds(True)\ntl.set_show_seconds(False)")

C("timeline.Timeline.select_keys", "timeline", "select_keys(frames)", "None",
  "Selects the keys of the selected objects at these frames in the time bar.",
  [("frames", "list of int", "Frames with keys.")],
  example='''
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
for f, x in ((10, 0), (20, 2)):
    ob.location.x = x
    ob.keyframe_insert("location", frame=f)
tl = qt_shell.api.timeline()
tl.select_keys([10, 20])
print(tl.selected_keys())                       # [10, 20]
''')

C("timeline.Timeline.selected_keys", "timeline", "selected_keys()", "list of int",
  "Frames of the keys selected in the time bar.",
  example=TL + "print(tl.selected_keys())")

C("timeline.Timeline.move_selected_keys", "timeline", "move_selected_keys(delta)", "int – keys moved",
  "Moves the selected keys by delta frames, like dragging them.",
  [("delta", "int", "Frames, negative = earlier.")],
  example='''
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
ob.keyframe_insert("location", frame=10)
tl = qt_shell.api.timeline()
tl.select_keys([10])
tl.move_selected_keys(5)                         # the key is now at frame 15
''')

C("timeline.Timeline.add_marker", "timeline", "add_marker(name=None, frame=None)", "TimelineMarker",
  "Adds a marker (scene.timeline_markers) at a frame.",
  [("name", "str", "Marker name; default F_<frame>."), ("frame", "int", "Default: the current frame.")],
  example=TL + 'm = tl.add_marker("Contact", 24)\nprint(m.name, m.frame)')

# =========================================================================================== outliner
OL = "import bpy, qt_shell\n\nol = qt_shell.api.outliner()\n"

C("api.outliner", "outliner", "outliner()", "Outliner or None",
  "The Outliner of the Qt Shell window. Commands that act on a selection use the Outliner's selected rows (or "
  "the selected objects).",
  example=OL + 'ol.search("Cube")')

C("outliner.Outliner.set_mode", "outliner", "set_mode(mode)", "None",
  "What the Outliner lists.",
  [("mode", "str", '"VIEW_LAYER", "BLENDER_FILE" or "ORPHAN" (unused data).')],
  example=OL + 'ol.set_mode("BLENDER_FILE")\nol.set_mode("VIEW_LAYER")')

C("outliner.Outliner.search", "outliner", 'search(text="")', "None",
  "Filters the rows by name; wildcards * and ?; \"\" clears the search.",
  [("text", "str", "Search text.")],
  example=OL + 'ol.search("*foot*")\nol.search("")')

C("outliner.Outliner.set_option", "outliner", "set_option(key, value)", "None",
  "A filter / display option. Keys: qt_shell.outliner.DEFAULTS (sort_alpha, sync, exact, case, collections, "
  "objects, children, state, invert, the object types …).",
  [("key", "str", "Option."), ("value", "", "Its value.")],
  example=OL + 'ol.set_option("sort_alpha", False)\nol.set_option("sort_alpha", True)')

C("outliner.Outliner.show_column", "outliner", "show_column(cid, on=True)", "None",
  "Shows / hides a restriction column.",
  [("cid", "str", "exclude, select, hide, viewport, render, holdout or indirect."), ("on", "bool", "Shown.")],
  example=OL + 'ol.show_column("select", True)\nol.show_column("select", False)')

C("outliner.Outliner.show_selected", "outliner", "show_selected()", "None",
  "Opens the rows down to every selected object / bone and centres the active one (Maya: Reveal Selected).",
  example=OL + "bpy.ops.mesh.primitive_cube_add()\nol.show_selected()")

C("outliner.Outliner.show_hierarchy", "outliner", "show_hierarchy()", "None",
  "Opens all collections and objects with children, closes the rest.",
  example=OL + "ol.show_hierarchy()")

C("outliner.Outliner.one_level", "outliner", "one_level(open_)", "None",
  "Numpad + / −: opens the shallowest closed level, or closes the deepest open level.",
  [("open_", "bool", "True opens, False closes.")],
  example=OL + "ol.one_level(True)\nol.one_level(False)")

C("outliner.Outliner.expand_toggle", "outliner", "expand_toggle()", "None",
  "Shift+A: expands all collections and objects, or collapses when something is open.",
  example=OL + "ol.expand_toggle()")

C("outliner.Outliner.new_collection", "outliner", "new_collection()", "None",
  "A new collection in the active collection; the selected objects are moved into it.",
  example=OL + "bpy.ops.mesh.primitive_cube_add()\nol.new_collection()")

C("outliner.Outliner.move_to", "outliner", "move_to(target, link=False, objs=None, colls=None)", "None",
  "Moves (or links) the selected objects / collections into a collection.",
  [("target", "bpy.types.Collection", "The collection."), ("link", "bool", "Link instead of move."),
   ("objs", "list", "Objects instead of the selection."), ("colls", "list", "Collections instead of the selection.")],
  example=OL + '''props = bpy.data.collections.new("Props")
bpy.context.scene.collection.children.link(props)
bpy.ops.mesh.primitive_cone_add()
ol.move_to(props, objs=[bpy.context.object])''')

C("outliner.Outliner.parent_to_active", "outliner", "parent_to_active(target=None, objs=None)", "None",
  "Parents the selected objects to the active one (or to target), keeping their world transform.",
  [("target", "Object", "The parent; default the active object."), ("objs", "list", "Children instead of the selection.")],
  example=OL + '''bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
parent = bpy.context.object
bpy.ops.mesh.primitive_uv_sphere_add(location=(0, 0, 3))
ol.parent_to_active(target=parent, objs=[bpy.context.object])''')

C("outliner.Outliner.clear_parent", "outliner", "clear_parent(objs=None)", "None",
  "Clears the parent of the selected objects, keeping their world transform.",
  [("objs", "list", "Objects instead of the selection.")],
  example=OL + "bpy.ops.mesh.primitive_cube_add()\nol.clear_parent([bpy.context.object])")

C("outliner.Outliner.hide_selected", "outliner", "hide_selected()", "None",
  "Hides the selected objects / collections in the viewport (H).",
  example=OL + "bpy.ops.mesh.primitive_cube_add()\nol.hide_selected()\nol.unhide_all()")

C("outliner.Outliner.unhide_all", "outliner", "unhide_all()", "None",
  "Shows everything that is hidden (Alt+H).",
  example=OL + "ol.unhide_all()")

C("outliner.Outliner.isolate", "outliner", 'isolate(key, cid="hide")', "None",
  "Like Ctrl+click in a restriction column: only this item stays visible (click again to restore).",
  [("key", "(type, name)", 'e.g. ("OBJECT", "Cube") or ("COLLECTION", "Props").'),
   ("cid", "str", "The column: hide, viewport, render, select …")],
  example=OL + '''bpy.ops.mesh.primitive_cube_add()
name = bpy.context.object.name
ol.isolate(("OBJECT", name))
ol.isolate(("OBJECT", name))                     # everything visible again''')

C("outliner.Outliner.collection_visibility", "outliner", "collection_visibility(c, hide, inside=False)", "None",
  "Hides / shows a collection in this view layer (inside=True: also everything in it).",
  [("c", "Collection", "The collection."), ("hide", "bool", "Hide (True) or show."), ("inside", "bool", "Also its contents.")],
  example=OL + '''props = bpy.data.collections.get("Props") or bpy.data.collections.new("Props")
if props.name not in bpy.context.scene.collection.children:
    bpy.context.scene.collection.children.link(props)
ol.collection_visibility(props, hide=True, inside=True)
ol.collection_visibility(props, hide=False, inside=True)''')

C("outliner.Outliner.duplicate_collection", "outliner", "duplicate_collection(c)", "None",
  "Duplicates a collection with its objects (references between them remapped, like Blender).",
  [("c", "Collection", "The collection.")],
  example=OL + '''props = bpy.data.collections.new("Set")
bpy.context.scene.collection.children.link(props)
ol.duplicate_collection(props)''')

C("outliner.Outliner.instance_collection", "outliner", "instance_collection(c)", "None",
  "Adds an instance of the collection (an Empty) at the 3D cursor.",
  [("c", "Collection", "The collection.")],
  example=OL + '''tree = bpy.data.collections.new("Tree")
bpy.context.scene.collection.children.link(tree)
ol.instance_collection(tree)''')

C("outliner.Outliner.delete", "outliner", "delete(hierarchy=False)", "None",
  "Deletes the selected objects / collections; hierarchy=True also their children.",
  [("hierarchy", "bool", "Delete children too.")],
  example=OL + "bpy.ops.mesh.primitive_cube_add()\nol.delete(hierarchy=False)")

# =========================================================================================== graph editor
GE = '''import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
for f, z in ((1, 0), (12, 3), (24, 0)):
    ob.location.z = z
    ob.keyframe_insert("location", index=2, frame=f)
ge = qt_shell.api.graph_editor()
'''

C("api.graph_editor", "graph", "graph_editor()", "GraphEditor or None",
  "The Graph editor of the Qt Shell window. Tangents and infinity apply to the selected keys, or to all shown "
  "curves when no key is selected.",
  example="import qt_shell\n\nge = qt_shell.api.graph_editor()\nge.frame_all()")

C("graph_editor.GraphEditor.set_tangents", "graph", "set_tangents(kind)", "None",
  "Key tangents (interpolation / handles).",
  [("kind", "str", '"AUTO", "AUTO_CLAMPED" (Spline), "LINEAR", "FLAT" or "CONSTANT" (Stepped).')],
  example=GE + 'ge.set_tangents("LINEAR")')

C("graph_editor.GraphEditor.set_handle_type", "graph", "set_handle_type(kind)", "None",
  "Handle type of the keys: break or unify the tangents.",
  [("kind", "str", '"FREE" (Break Tangents), "ALIGNED" (Unify), "VECTOR", "AUTO", "AUTO_CLAMPED".')],
  example=GE + 'ge.set_handle_type("FREE")')

C("graph_editor.GraphEditor.set_infinity", "graph", "set_infinity(mode)", "None",
  "What the curves do before the first and after the last key.",
  [("mode", "str", '"CONSTANT", "LINEAR", "REPEAT" (Cycle), "REPEAT_OFFSET" (Cycle with Offset) or "MIRROR" (Oscillate).')],
  example=GE + 'ge.set_infinity("REPEAT")')

C("graph_editor.GraphEditor.insert_keys", "graph", "insert_keys()", "None",
  "Keys the shown curves at the current frame (the selected objects when no curve is shown).",
  example=GE + "bpy.context.scene.frame_set(6)\nge.insert_keys()")

C("graph_editor.GraphEditor.delete_keys", "graph", "delete_keys()", "None",
  "Deletes the selected keys.",
  example=GE + "ge.delete_keys()")

C("graph_editor.GraphEditor.set_snap", "graph", "set_snap(on=True)", "None",
  "Snaps key times to whole frames while moving keys (the ⌗ Snap button).",
  [("on", "bool", "Snap on / off.")],
  example="import qt_shell\n\nge = qt_shell.api.graph_editor()\nge.set_snap(True)")

C("graph_editor.GraphEditor.frame_all", "graph", "frame_all()", "None",
  "Fits all shown curves into the view.",
  example=GE + "ge.frame_all()")

C("graph_editor.GraphEditor.frame_selected", "graph", "frame_selected()", "None",
  "Fits the selected keys into the view.",
  example=GE + "ge.frame_selected()")

# =========================================================================================== UV editor
UV = '''import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
'''

C("api.uv_editor", "uv", "uv_editor()", "UVEditor or None",
  "The UV editor of the Qt Shell window; it works on the active mesh in Edit Mode. Every button shows its Python "
  "line in the tooltip.",
  example=UV + 'uv.set_mode("FACE")\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVEditor.set_mode", "uv", "set_mode(mode)", "None",
  "Component mode of the UV editor.",
  [("mode", "str", '"VERT", "EDGE", "FACE" or "ISLAND" (shell).')],
  example=UV + 'uv.set_mode("ISLAND")\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVEditor.tool", "uv", "tool(idname, props=None)", "None",
  "Runs any bpy.ops.uv operator on the current UV selection, in a UV editor context.",
  [("idname", "str", 'e.g. "uv.pack_islands".'), ("props", "dict", "Operator properties.")],
  example=UV + 'uv.tool("uv.pack_islands", {"margin": 0.01})\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVEditor.mesh_tool", "uv", "mesh_tool(idname, props=None)", "None",
  "A projection (3D view operator) on the selected faces – all faces when none is selected.",
  [("idname", "str", 'e.g. "uv.smart_project", "uv.cube_project".'), ("props", "dict", "Operator properties.")],
  example=UV + 'uv.mesh_tool("uv.smart_project", {"island_margin": 0.02})\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVEditor.unwrap", "uv", "unwrap()", "None",
  "Unwraps the selected faces (all when none is selected).",
  example=UV + 'uv.unwrap()\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVEditor.layout_shells", "uv", "layout_shells()", "None",
  "Packs the shells into the 0–1 square (Maya: Layout).",
  example=UV + 'uv.layout_shells()\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVEditor.move_by", "uv", "move_by(du, dv)", "None",
  "Moves the selected UVs.",
  [("du", "float", "U offset."), ("dv", "float", "V offset.")],
  example=UV + 'uv.move_by(0.1, 0)\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVEditor.rotate_by", "uv", "rotate_by(deg)", "None",
  "Rotates the selected UVs around their centre.",
  [("deg", "float", "Degrees, counter-clockwise.")],
  example=UV + 'uv.rotate_by(90)\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVEditor.flip", "uv", "flip(horizontal)", "None",
  "Flips the selected UVs.",
  [("horizontal", "bool", "True = in U (horizontally), False = in V.")],
  example=UV + 'uv.flip(True)\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVEditor.align", "uv", "align(how)", "None",
  "Aligns the selected UVs.",
  [("how", "str", '"UMIN", "UMID", "UMAX", "VMIN", "VMID" or "VMAX".')],
  example=UV + 'uv.align("UMIN")\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVEditor.normalize", "uv", "normalize()", "None",
  "Scales the selected UVs into the 0–1 square, keeping the proportions.",
  example=UV + 'uv.normalize()\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVEditor.texel_get", "uv", "texel_get()", "None",
  "Measures the texel density of the selected faces (px per metre) into the Texel Density field and the status bar.",
  example=UV + 'uv.texel_get()\nprint(uv.td.value())\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVEditor.set_texel_density", "uv", "set_texel_density(value)", "None",
  "Scales every selected shell to value pixels per metre.",
  [("value", "float", "px / m (of the texture size set in the UV editor).")],
  example=UV + 'uv.set_texel_density(512)\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVEditor.set_display", "uv", "set_display(key, on=True)", "None",
  "Display options of the UV editor; checker is also drawn on the mesh in the 3D view.",
  [("key", "str", "image, dim, checker, shaded, distortion, borders or grid."), ("on", "bool", "On / off.")],
  example="import qt_shell\n\nuv = qt_shell.api.uv_editor()\nuv.set_display(\"checker\", True)\nuv.set_display(\"checker\", False)")

C("uv_editor.UVEditor.set_image", "uv", "set_image(name=None)", "None",
  "The image shown behind the UVs; None = the active material's texture.",
  [("name", "str", "Image name in bpy.data.images.")],
  example='''import bpy, qt_shell

img = bpy.data.images.new("Grid", 1024, 1024)
img.generated_type = "UV_GRID"
uv = qt_shell.api.uv_editor()
uv.set_image("Grid")''')

C("uv_editor.UVCanvas.select_all", "uv", 'select_all(action="SELECT")', "None",
  "Selects / deselects all UVs (uv.canvas).",
  [("action", "str", '"SELECT", "DESELECT", "INVERT" or "TOGGLE".')],
  example=UV + 'uv.canvas.select_all("SELECT")\nbpy.ops.object.mode_set(mode="OBJECT")')

C("uv_editor.UVCanvas.frame_selected", "uv", "frame_selected()", "None",
  "Fits the selected UVs into the view (uv.canvas).",
  example=UV + 'uv.canvas.select_all("SELECT")\nuv.canvas.frame_selected()\nbpy.ops.object.mode_set(mode="OBJECT")')

# =========================================================================================== render view
RV = '''import bpy, qt_shell

bpy.ops.render.render()                          # a render to look at (F12 renders in the background)
rv = qt_shell.api.render_view()
'''
RV0 = "import qt_shell\n\nrv = qt_shell.api.render_view()     # after a render (F12)\n"

C("api.render_view", "render", "render_view()", "RenderView or None",
  "Qt Shell's render window (Blender's Image Editor with the Render Result).",
  example=RV + "rv.present()")

C("render_view.RenderView.present", "render", "present()", "None",
  "Shows the Render View (F11).",
  example=RV0 + "rv.present()")

C("render_view.RenderView.set_slot", "render", "set_slot(index)", "None",
  "Shows a render slot; the next render goes there (J / Alt+J cycle the slots).",
  [("index", "int", "0 = Slot 1.")],
  example=RV0 + "rv.set_slot(1)          # Slot 2\nrv.set_slot(0)")

C("render_view.RenderView.set_channel", "render", "set_channel(channel)", "None",
  "Which channels are shown.",
  [("channel", "str", '"COLOR_ALPHA", "COLOR", "ALPHA", "RED", "GREEN" or "BLUE".')],
  example=RV0 + 'rv.set_channel("ALPHA")\nrv.set_channel("COLOR_ALPHA")')

C("render_view.RenderView.passes", "render", "passes()", "dict {view layer: [passes]}",
  "The view layers and passes of the shown result (enabled in View Layer Properties → Passes).",
  example=RV + 'print(rv.passes())        # {"ViewLayer": ["Combined", "Depth", …]}')

C("render_view.RenderView.set_pass", "render", "set_pass(pas)", "None",
  "Shows a render pass of the current view layer.",
  [("pas", "str", 'Pass name, e.g. "Depth".')],
  example=RV0 + 'rv.set_pass("Combined")')

C("render_view.RenderView.set_layer", "render", "set_layer(layer)", "None",
  "Shows a view layer of the result.",
  [("layer", "str", "View layer name.")],
  example="import bpy, qt_shell\n\nrv = qt_shell.api.render_view()     # after a render (F12)\nrv.set_layer(bpy.context.view_layer.name)")

C("render_view.RenderView.zoom", "render", "zoom(ratio)", "None",
  "Zoom like View → Fractional Zoom.",
  [("ratio", "float", "1 = 1:1, 2 = 2:1, 0.5 = 1:2 …")],
  example=RV0 + "rv.zoom(1)")

C("render_view.RenderView.fit", "render", "fit()", "None",
  "Frame All (Home): the whole image in the view.",
  example=RV0 + "rv.fit()")

C("render_view.RenderView.save_as", "render", "save_as(path=None, copy=False)", "bool",
  "Saves the render of the active slot; the format follows the extension (.png .jpg .exr .tif .webp .bmp). A "
  "picture with drawings is saved as shown. Without a path a file dialog asks.",
  [("path", "str", "The file."), ("copy", "bool", "Save a copy (keep the image's own path).")],
  example=RV + 'rv.save_as("C:/out/frame.png")')

C("render_view.RenderView.copy_to_clipboard", "render", "copy_to_clipboard()", "None",
  "Copies the picture as shown to the clipboard.",
  example=RV0 + "rv.copy_to_clipboard()")

C("render_view.RenderView.set_tool", "render", "set_tool(tool, variant=None)", "None",
  "Toolbar tool of the Render View (T).",
  [("tool", "str", '"SAMPLE", "ANNOTATE" or "BLUE_PENCIL".'),
   ("variant", "str", "ANNOTATE: FREEHAND, LINE, POLYGON, ERASER · BLUE_PENCIL: PENCIL, BRUSH, ERASER, TEXT, "
                      "LINE, ARROW, ELLIPSE, RECT, TRANSFORM.")],
  example=RV0 + 'rv.set_tool("ANNOTATE", "LINE")\nrv.set_tool("SAMPLE")')

C("render_view.RenderView.picture", "render", "picture()", "QImage or None",
  "The picture as shown: the render plus Blue Pencil and the annotations of the active slot.",
  example=RV + 'img = rv.picture()\nprint(img.width(), img.height())')

C("render_view.RenderView.has_drawings", "render", "has_drawings()", "bool",
  "True when Save writes the picture with drawings (burnt-in or Render View annotations).",
  example=RV0 + "print(rv.has_drawings())")

C("render_view.RenderView.add_annotation", "render", "add_annotation(points, color=None, width=None)", "None",
  "Adds an annotation stroke to the active slot (kept per slot for the session).",
  [("points", "list of (x, y)", "Image pixels from the top-left corner."),
   ("color", "str", '"#rrggbb"; default the current style.'), ("width", "int", "Thickness in px.")],
  example=RV + 'rv.add_annotation([(10, 10), (200, 120)], color="#ff4040", width=4)')

C("render_view.RenderView.annotations", "render", "annotations(slot=None)", "list of dict",
  'Annotation strokes of a render slot: [{"pts": [(x, y), …], "color": "#rrggbb", "width": px}, …].',
  [("slot", "int", "Default: the active slot.")],
  example=RV0 + "for st in rv.annotations():\n    print(st[\"color\"], len(st[\"pts\"]))")

C("render_view.RenderView.undo_annotation", "render", "undo_annotation()", "bool",
  "Removes the last annotation stroke of the active slot. False when there is none.",
  example=RV0 + "rv.undo_annotation()")

C("render_view.RenderView.clear_annotations", "render", "clear_annotations()", "None",
  "Removes all annotations of the active slot.",
  example=RV0 + "rv.clear_annotations()")

C("render_view.RenderView.set_annotation_style", "render", "set_annotation_style(color=None, width=None)", "None",
  "Colour and thickness of new annotation strokes.",
  [("color", "str", '"#rrggbb".'), ("width", "int", "px.")],
  example=RV0 + 'rv.set_annotation_style(color="#619bc7", width=3)')

C("render_view.RenderView.set_overlays", "render", "set_overlays(on)", "None",
  "Overlays: annotations and the render info text on the image.",
  [("on", "bool", "Shown.")],
  example=RV0 + "rv.set_overlays(False)\nrv.set_overlays(True)")

C("render_view.RenderView.set_gizmos", "render", "set_gizmos(on)", "None",
  "The navigation gizmo (zoom / pan buttons) at the top right of the image.",
  [("on", "bool", "Shown.")],
  example=RV0 + "rv.set_gizmos(True)")

C("render_view.RenderView.set_toolbar", "render", "set_toolbar(on)", "None",
  "The toolbar at the left (T).",
  [("on", "bool", "Shown.")],
  example=RV0 + "rv.set_toolbar(True)")

# =========================================================================================== player
C("anim_player.AnimPlayer.set_blue_pencil", "player", "set_blue_pencil(on)", "None",
  "Blue Pencil on the frame shown in the Animation Player (Render → View Animation, Ctrl+F11); strokes go to "
  "the player's own layers (space ANIM).",
  [("on", "bool", "Drawing on / off.")],
  example='''
import qt_shell.api as qs

player = qs.main_window().anim_player          # open it with Render → View Animation first
player.set_blue_pencil(True)
''', run=False, skip="needs rendered frames in the Animation Player")

C("anim_player.AnimPlayer.export_animation", "player",
  "export_animation(path=None, kind=None, start=None, end=None, blue_pencil=None)", "int – frames saved",
  "Saves the frames played. Without a path a dialog asks.",
  [("path", "str", "The file (MP4) or the first file of a sequence."),
   ("kind", "str", '"MP4", "PNG", "JPEG", "TIFF" or "COPY" (the rendered files).'),
   ("start", "int", "First frame."), ("end", "int", "Last frame."),
   ("blue_pencil", "bool", "Burn in the player's Blue Pencil layers (COPY then becomes PNG).")],
  example='''
import qt_shell.api as qs

player = qs.main_window().anim_player
player.export_animation("C:/out/review.mp4", "MP4", 1, 48, blue_pencil=True)
''', run=False, skip="needs rendered frames in the Animation Player")

# =========================================================================================== image editor
IE = "import qt_shell\n\nie = qt_shell.api.image_editor()\n"

C("api.image_editor", "image", "image_editor()", "ImageEditor or None",
  "The Image editor: compositor result, Viewer node, Render Result, rendered animation or an image.",
  example=IE + 'ie.set_source("RENDER")')

C("image_editor.ImageEditor.set_source", "image", "set_source(src)", "None",
  "What the Image editor shows.",
  [("src", "str", '"COMPOSITOR" (the result), "VIEWER" (the Viewer node), "RENDER", "ANIMATION" or an image '
                  'name ("IMAGE:<name>" or just the name).')],
  example='''
import bpy, qt_shell

img = bpy.data.images.new("Grid", 512, 512)
img.generated_type = "COLOR_GRID"
ie = qt_shell.api.image_editor()
ie.set_source("Grid")
''')

C("image_editor.ImageEditor.set_live", "image", "set_live(on)", "None",
  "Live on: the picture follows every change of the compositor nodes. Off: it stays as it is (compare before / "
  "after) until Reload or a new render.",
  [("on", "bool", "Live on / off.")],
  example=IE + "ie.set_live(False)\nie.set_live(True)")

C("image_editor.ImageEditor.refresh", "image", "refresh()", "None",
  "The Reload button: the compositor's current result (the Viewer is re-linked to the output first).",
  example='''
import bpy, qt_shell
from qt_shell import image_editor

bpy.ops.render.render()
image_editor.ensure_compositor()
ie = qt_shell.api.image_editor()
ie.set_source("COMPOSITOR")
ie.refresh()
''')

C("image_editor.ImageEditor.set_auto_reload", "image", "set_auto_reload(on=True)", "None",
  "Auto: an image shown is read again when it changes (follows Texture Paint live). Default on.",
  [("on", "bool", "On / off.")],
  example=IE + "ie.set_auto_reload(True)")

C("image_editor.ImageEditor.reload", "image", "reload(keep_view=True)", "None",
  "Reads the picture of the current source again.",
  [("keep_view", "bool", "Keep the zoom / pan.")],
  example=IE + "ie.reload()")

C("image_editor.ImageEditor.fit", "image", "fit()", "None",
  "Frame All: the whole picture in the view.",
  example=IE + "ie.fit()")

C("image_editor.ImageEditor.zoom", "image", "zoom(ratio)", "None",
  "Zoom ratio, 1 = 1:1.",
  [("ratio", "float", "Zoom.")],
  example=IE + "ie.zoom(1)\nie.zoom(0.5)")

C("image_editor.ImageEditor.set_channel", "image", "set_channel(ch)", "None",
  "Which channels are shown.",
  [("ch", "str", '"COLOR_ALPHA", "COLOR", "ALPHA", "RED", "GREEN" or "BLUE".')],
  example=IE + 'ie.set_channel("ALPHA")\nie.set_channel("COLOR_ALPHA")')

C("image_editor.ImageEditor.export_image", "image", "export_image(path=None)", "bool",
  "Saves the picture shown; the format follows the extension (.png .jpg .exr .tif .webp .bmp). Without a path "
  "a file dialog asks.",
  [("path", "str", "The file.")],
  example='''
import bpy, qt_shell

img = bpy.data.images.new("Grid", 256, 256)
img.generated_type = "UV_GRID"
ie = qt_shell.api.image_editor()
ie.set_source("Grid")
ie.export_image("C:/out/grid.png")
''')

C("image_editor.ImageEditor.set_frame", "image", "set_frame(f, from_ui=False, keep_view=True)", "bool",
  "Rendered animation: shows frame f (the nearest rendered one).",
  [("f", "int", "Frame."), ("from_ui", "bool", "Internal."), ("keep_view", "bool", "Keep the zoom / pan.")],
  example=IE + 'ie.set_source("ANIMATION")\nie.set_frame(12)',
  run=False, skip="needs a rendered animation")

C("image_editor.ImageEditor.play", "image", "play()", "bool",
  "Plays the rendered animation.",
  example=IE + 'ie.set_source("ANIMATION")\nie.play()\nie.pause()', run=False, skip="needs a rendered animation")

C("image_editor.ImageEditor.pause", "image", "pause()", "None",
  "Pauses the rendered animation.",
  example=IE + "ie.pause()")

C("image_editor.ImageEditor.set_cache_range", "image", "set_cache_range(start=None, end=None)", "None",
  "From / To of the compositor cache; None, None = the scene's frame range.",
  [("start", "int", "First frame."), ("end", "int", "Last frame.")],
  example=IE + "ie.set_cache_range(10, 40)\nie.set_cache_range(None, None)")

C("image_editor.ImageEditor.render_raw", "image", "render_raw()", "bool",
  "Renders the animation once without compositing (OpenEXR, temporary folder) – the input Live composites with "
  "the current nodes.",
  example=IE + "ie.render_raw()", run=False, skip="renders the whole animation")

C("image_editor.ImageEditor.use_frames", "image", "use_frames(folder=None)", "None",
  "The compositor works on frames rendered before (any image sequence); None = this file's own frames.",
  [("folder", "str", "Folder with the frames.")],
  example=IE + 'ie.use_frames("C:/frames")\nie.use_frames(None)', run=False, skip="needs rendered frames")

C("image_editor.ImageEditor.export_animation", "image", "export_animation(path=None, kind=None, start=None, end=None)",
  "bool", "Exports the rendered animation. Without a path a dialog asks.",
  [("path", "str", "The file (MP4) or the first file of a sequence."),
   ("kind", "str", '"MP4", "PNG", "JPEG", "TIFF" or "COPY" (the rendered files).'),
   ("start", "int", "First frame."), ("end", "int", "Last frame.")],
  example=IE + 'ie.export_animation("C:/out/anim.mp4", "MP4", 1, 120)', run=False, skip="needs a rendered animation")

C("image_editor.ensure_compositor", "image", "ensure_compositor(viewer=True)", "NodeTree",
  "Creates the compositor nodes when the scene has none (Render Layers → Group Output) and a Viewer node fed by "
  "what goes to the output.",
  [("viewer", "bool", "Also add / link the Viewer node.")],
  example='''
from qt_shell import image_editor

tree = image_editor.ensure_compositor()
print([n.name for n in tree.nodes])
''')

# =========================================================================================== sequencer
VS = "import bpy, qt_shell\n\nvs = qt_shell.api.video_sequencer()\n"

C("api.video_sequencer", "sequencer", "video_sequencer()", "VideoSequencer or None",
  "The Video Sequencer. It edits Blender's own strips (scene.sequence_editor), so plain bpy works alongside it; "
  "each method makes one undo step.",
  example=VS + "print([s.name for s in vs.selected()])")

C("sequencer.VideoSequencer.add_files", "sequencer", "add_files(paths, frame=None, channel=1)", "list of strips",
  "Adds movies (with their sound), sounds and images one after another; several images of a folder become one "
  "image sequence.",
  [("paths", "list of str", "Files."), ("frame", "int", "Start frame; default the current frame."),
   ("channel", "int", "Channel (a free one above is used when it is taken).")],
  example=VS + 'vs.add_files(["C:/clips/shot010.mp4", "C:/music/song.wav"], frame=1)')

C("sequencer.VideoSequencer.add_movie", "sequencer", "add_movie(path, frame=None, channel=1, with_sound=True)",
  "list of strips", "Adds a movie (and its sound strip).",
  [("path", "str", "Movie file."), ("frame", "int", "Start frame."), ("channel", "int", "Channel."),
   ("with_sound", "bool", "Also add the sound.")],
  example=VS + 'movie, sound = vs.add_movie("C:/clips/shot010.mp4", frame=1, channel=2)')

C("sequencer.VideoSequencer.add_sound", "sequencer", "add_sound(path, frame=None, channel=1)", "strip",
  "Adds a sound strip.",
  [("path", "str", "Sound file."), ("frame", "int", "Start frame."), ("channel", "int", "Channel.")],
  example=VS + 's = vs.add_sound("C:/music/song.wav", frame=1, channel=4)\ns.volume = 0.5')

C("sequencer.VideoSequencer.add_images", "sequencer", "add_images(paths, frame=None, channel=1)", "strip or None",
  "Adds images of one folder as an image strip (several = a sequence).",
  [("paths", "list of str", "Image files of one folder."), ("frame", "int", "Start frame."), ("channel", "int", "Channel.")],
  example=VS + 'vs.add_images(["C:/frames/shot_0001.png", "C:/frames/shot_0002.png"], frame=1, channel=3)')

C("sequencer.VideoSequencer.add_scene", "sequencer", "add_scene(scn, frame=None, channel=1)", "strip",
  "Adds a scene strip.",
  [("scn", "Scene", "The scene."), ("frame", "int", "Start frame."), ("channel", "int", "Channel.")],
  example=VS + 'vs.add_scene(bpy.context.scene, frame=1, channel=5)')

C("sequencer.VideoSequencer.add_camera_shot", "sequencer", "add_camera_shot(cam, start=None, end=None)", "strip",
  "A shot like Maya's Camera Sequencer: this scene through cam for a range of the scene, placed after the last "
  "shot. Range: the preview range when it is on, else the scene range.",
  [("cam", "Object", "A camera."), ("start", "int", "First scene frame."), ("end", "int", "Last scene frame.")],
  example=VS + '''cam_data = bpy.data.cameras.new("ShotCam")
cam = bpy.data.objects.new("ShotCam", cam_data)
bpy.context.scene.collection.objects.link(cam)
vs.add_camera_shot(cam, 1, 48)''')

C("sequencer.VideoSequencer.add_text", "sequencer", "add_text()", "strip",
  "Adds a text strip at the current frame.",
  example=VS + 's = vs.add_text()\ns.text = "Scene 1"')

C("sequencer.VideoSequencer.add_color", "sequencer", "add_color()", "strip",
  "Adds a colour strip at the current frame (the size of the render).",
  example=VS + "s = vs.add_color()\ns.color = (0.1, 0.1, 0.12)")

C("sequencer.VideoSequencer.add_adjustment", "sequencer", "add_adjustment()", "strip",
  "Adds an adjustment layer at the current frame.",
  example=VS + "vs.add_adjustment()")

C("sequencer.VideoSequencer.add_transition", "sequencer", "add_transition(etype)", "strip or None",
  "A transition between the two selected strips (on the channel above them). None when not exactly two are selected.",
  [("etype", "str", '"CROSS", "GAMMA_CROSS" or "WIPE".')],
  example=VS + '''a = vs.add_color()
bpy.context.scene.frame_set(a.frame_final_end - 10)
b = vs.add_color()
vs.select([a, b])
vs.add_transition("CROSS")''')

C("sequencer.VideoSequencer.select", "sequencer", "select(strips, extend=False, toggle=False, deselect=False)", "None",
  "Selects strips (the last one becomes active).",
  [("strips", "list", "Strips."), ("extend", "bool", "Keep the current selection."),
   ("toggle", "bool", "Toggle each strip."), ("deselect", "bool", "Deselect them.")],
  example=VS + "s = vs.add_text()\nvs.select([s])\nvs.select([s], deselect=True)")

C("sequencer.VideoSequencer.selected", "sequencer", "selected()", "list of strips",
  "The selected strips of the shown level (top level or the open meta strip).",
  example=VS + "for s in vs.selected():\n    print(s.name, s.channel, s.frame_final_start)")

C("sequencer.VideoSequencer.cut", "sequencer", "cut(frame=None)", "int – strips cut",
  "Splits the selected strips (none selected: all unlocked strips) at the frame – K.",
  [("frame", "int", "Default: the current frame.")],
  example=VS + "s = vs.add_color()\nvs.select([s])\nvs.cut(s.frame_final_start + 10)")

C("sequencer.VideoSequencer.delete", "sequencer", "delete(ripple=False)", "int – strips deleted",
  "Deletes the selected strips; ripple=True closes the gap on their channel.",
  [("ripple", "bool", "Ripple delete.")],
  example=VS + "s = vs.add_color()\nvs.select([s])\nvs.delete(ripple=True)")

C("sequencer.VideoSequencer.duplicate", "sequencer", "duplicate()", "int – strips added",
  "Duplicates the selected strips (Shift+D).",
  example=VS + "vs.select([vs.add_text()])\nvs.duplicate()")

C("sequencer.VideoSequencer.move_strips", "sequencer", "move_strips(strips, df, dch)", "None",
  "Moves strips by df frames and dch channels.",
  [("strips", "list", "Strips."), ("df", "int", "Frames."), ("dch", "int", "Channels.")],
  example=VS + "s = vs.add_color()\nvs.move_strips([s], 10, 1)      # +10 frames, one channel up")

C("sequencer.VideoSequencer.trim", "sequencer", "trim(s, side, frame)", "None",
  "Moves the start ('l') or end ('r') of a strip to a frame.",
  [("s", "strip", "The strip."), ("side", "str", '"l" = start, "r" = end.'), ("frame", "int", "The new frame.")],
  example=VS + 's = vs.add_color()\nvs.trim(s, "r", s.frame_final_start + 24)')

C("sequencer.VideoSequencer.set_flag", "sequencer", "set_flag(attr, on)", "None",
  "Sets mute or lock on the selected strips.",
  [("attr", "str", '"mute" or "lock".'), ("on", "bool", "On / off.")],
  example=VS + 'vs.select([vs.add_text()])\nvs.set_flag("mute", True)\nvs.set_flag("mute", False)')

C("sequencer.VideoSequencer.toggle", "sequencer", "toggle(attr)", "None",
  "Toggles mute or lock on the selected strips (on when not all of them have it).",
  [("attr", "str", '"mute" or "lock".')],
  example=VS + 'vs.select([vs.add_text()])\nvs.toggle("lock")')

C("sequencer.VideoSequencer.set_tag", "sequencer", "set_tag(key)", "None",
  "Colour tag of the selected strips.",
  [("key", "str", '"NONE" or "COLOR_01" … "COLOR_09".')],
  example=VS + 'vs.select([vs.add_text()])\nvs.set_tag("COLOR_03")')

C("sequencer.VideoSequencer.make_meta", "sequencer", "make_meta()", "meta strip or None",
  "Makes a meta strip of the selected (unlocked) strips.",
  example=VS + "vs.select([vs.add_color(), vs.add_text()])\nmeta = vs.make_meta()\nprint(meta.name)")

C("sequencer.VideoSequencer.separate_meta", "sequencer", "separate_meta()", "None",
  "Breaks the selected meta strips up into their strips.",
  example=VS + "vs.select([vs.add_color(), vs.add_text()])\nvs.make_meta()\nvs.separate_meta()")

C("sequencer.VideoSequencer.enter_meta", "sequencer", "enter_meta(s)", "None",
  "Opens a meta strip – the view then shows its strips.",
  [("s", "meta strip", "The meta strip.")],
  example=VS + "vs.select([vs.add_color(), vs.add_text()])\nmeta = vs.make_meta()\nvs.enter_meta(meta)\nvs.exit_meta()")

C("sequencer.VideoSequencer.exit_meta", "sequencer", "exit_meta()", "None",
  "Closes the open meta strip and goes back up.",
  example=VS + "vs.exit_meta()")

C("sequencer.VideoSequencer.range_to_strips", "sequencer", "range_to_strips()", "None",
  "Sets the scene range to all strips.",
  example=VS + "vs.add_color()\nvs.range_to_strips()")

C("sequencer.VideoSequencer.preview_range_to_selection", "sequencer", "preview_range_to_selection()", "None",
  "Sets the preview range to the selected strips.",
  example=VS + "vs.select([vs.add_text()])\nvs.preview_range_to_selection()\nbpy.context.scene.use_preview_range = False")

C("sequencer.VideoSequencer.view_frame_all", "sequencer", "view_frame_all()", "None",
  "Fits all strips into the strips view.",
  example=VS + "vs.view_frame_all()")

C("sequencer.VideoSequencer.play_sound", "sequencer", "play_sound()", "None",
  "Play / stop: from the preview cache in real time when it is filled, else Blender's own playback with sound.",
  example=VS + "vs.play_sound()          # play\nvs.play_sound()          # stop")

C("sequencer.VideoSequencer.set_blue_pencil", "sequencer", "set_blue_pencil(on)", "None",
  "Blue Pencil on the Qt Shell preview (switches the preview to Qt Shell's); drawings go to Video Editing layers.",
  [("on", "bool", "On / off.")],
  example=VS + "vs.set_blue_pencil(True)\nvs.set_blue_pencil(False)")

C("sequencer.VideoSequencer.cache_all", "sequencer", "cache_all()", "int – frames cached",
  "Cache All Frames: renders the play range into the Qt Shell preview's cache (Esc stops).",
  example=VS + 'vs.pane.set_mode("qt")\nvs.add_color()\nvs.cache_all()\nvs.pane.set_mode("blender")')

C("sequencer.VideoSequencer.export_video", "sequencer",
  'export_video(path=None, fmt=None, start=None, end=None, quality="HIGH", scale=100, audio=True)', "bool",
  "Exports the edit – rendered by Blender like Render Animation (progress, cancel); the scene's output settings "
  "are put back afterwards. Without a path the Export dialog opens. last_export[\"state\"] goes from \"running\" "
  "to \"done\", \"cancelled\" or \"failed\" (with \"files\").",
  [("path", "str", "The file (an image sequence: its first file name, numbers are added)."),
   ("fmt", "str", "MP4_H264, MP4_H265, MP4_AV1, MOV_H264, MOV_PRORES, MKV_H264, MKV_FFV1, WEBM_VP9, AVI_H264, "
                  "OGG_THEORA · SEQ_PNG, SEQ_JPEG, SEQ_TIFF, SEQ_EXR, SEQ_WEBP · AUDIO_WAV, AUDIO_MP3, "
                  "AUDIO_FLAC, AUDIO_OGG (qt_shell.seq_export.formats() = what this Blender can write)."),
   ("start", "int", "First frame; default the scene start."), ("end", "int", "Last frame; default the scene end."),
   ("quality", "str", '"LOSSLESS", "HIGH", "MEDIUM" or "LOW".'), ("scale", "int", "Per cent of the scene resolution."),
   ("audio", "bool", "Include the sound (video formats).")],
  example=VS + '''vs.add_color()
vs.export_video("C:/out/edit.mp4", "MP4_H264", start=1, end=24, quality="MEDIUM", scale=50)
print(vs.last_export["state"])          # running … then done''')

C("seq_export.formats", "sequencer", "formats()", "list of str",
  "The export format ids this Blender can write (its FFmpeg containers / codecs differ between builds).",
  example='''
import qt_shell.seq_export as sx

print(sx.formats())
print([f for f in sx.formats() if f.startswith("AUDIO_")])
''')

# =========================================================================================== blue pencil
BP = "import qt_shell.bluepencil as bp\n\n"

C("bluepencil.data", "bluepencil", "data(scene=None)", "dict",
  'The scene\'s Blue Pencil data: {"layers": [{"name", "camera", "space", "frames": {frame: [strokes]}}, …]} '
  '(JSON in scene["qtshell_bluepencil"]). After editing it call commit().',
  [("scene", "Scene", "Default: the current scene.")],
  example=BP + 'for lay in bp.data()["layers"]:\n    print(lay["name"], lay.get("space"), sorted(lay["frames"]))')

C("bluepencil.commit", "bluepencil", "commit(message, scene=None)", "None",
  "Writes the edited data back to the scene: saved with the file, one undo step.",
  [("message", "str", "Undo step name."), ("scene", "Scene", "Default: the current scene.")],
  example=BP + 'd = bp.data()\nif d["layers"]:\n    d["layers"][0]["name"] = "Notes"\nbp.commit("Rename Layer")')

C("bluepencil.new_layer", "bluepencil",
  'new_layer(name=None, camera=None, state="ANIMATION", do_commit=True, space="VIEWPORT")', "dict – the layer",
  "A new layer on top of the list (active).",
  [("name", "str", "Layer name."), ("camera", "str", 'Camera object name, "" = the View.'),
   ("state", "str", '"ANIMATION" (keyed on frames) or "STATIC".'), ("do_commit", "bool", "Save it at once."),
   ("space", "str", '"VIEWPORT", "RENDER", "ANIM" or "VIDEO" – the window it is drawn in.')],
  example=BP + 'lay = bp.new_layer("Notes", camera="")\nprint(lay["name"])')

C("bluepencil.insert_frame", "bluepencil", "insert_frame(f=None)", "None",
  "An empty drawing at frame f on the active layer.",
  [("f", "int", "Default: the current frame.")],
  example=BP + 'bp.new_layer("Keys", camera="")\nbp.insert_frame(1)\nbp.insert_frame(12)')

C("bluepencil.duplicate_frame", "bluepencil", "duplicate_frame(f=None)", "None",
  "Copies the drawing shown before f to a new frame at f.",
  [("f", "int", "Default: the current frame.")],
  example=BP + 'bp.new_layer("Keys", camera="")\nbp.insert_frame(1)\nbp.duplicate_frame(5)')

C("bluepencil.delete_frame", "bluepencil", "delete_frame(f=None)", "None",
  "Deletes the drawing at frame f of the active layer.",
  [("f", "int", "Default: the current frame.")],
  example=BP + 'bp.new_layer("Keys", camera="")\nbp.insert_frame(3)\nbp.delete_frame(3)')

C("bluepencil.copy_frame", "bluepencil", "copy_frame(f=None, cut=False)", "None",
  "Copies (or cuts) the drawing at frame f.",
  [("f", "int", "Default: the current frame."), ("cut", "bool", "Cut instead of copy.")],
  example=BP + 'bp.new_layer("Keys", camera="")\nbp.insert_frame(1)\nbp.copy_frame(1)\nbp.paste_frame(10)')

C("bluepencil.paste_frame", "bluepencil", "paste_frame(f=None)", "None",
  "Pastes the copied drawing at frame f.",
  [("f", "int", "Default: the current frame.")],
  example=BP + 'bp.new_layer("Keys", camera="")\nbp.insert_frame(1)\nbp.copy_frame(1)\nbp.paste_frame(20)')

C("bluepencil.step", "bluepencil", "step(direction)", "None",
  "Goes to the previous / next drawing of the active layer.",
  [("direction", "int", "1 = next, -1 = previous.")],
  example=BP + 'bp.new_layer("Keys", camera="")\nbp.insert_frame(1)\nbp.insert_frame(8)\nbp.step(-1)')

C("bluepencil.retime", "bluepencil", "retime(mode, n, selection=None)", "None",
  'Retiming: "ABS" = exactly n frames between the drawings (1–6), "REL" = ±n frames after the drawing.',
  [("mode", "str", '"ABS" or "REL".'), ("n", "int", "Frames."),
   ("selection", "list", "Selected keys (Timeline); None = the drawing at the current frame.")],
  example=BP + 'bp.new_layer("Keys", camera="")\nfor f in (1, 3, 5):\n    bp.insert_frame(f)\nbp.retime("ABS", 2)')

C("bluepencil.set_variant", "bluepencil", "set_variant(tool)", "None",
  "The Blue Pencil drawing tool without switching the 3D view to Blue Pencil (shared by the Render View, the "
  "Animation Player and the Video Sequencer).",
  [("tool", "str", "PENCIL, BRUSH, ERASER, TEXT, LINE, ARROW, ELLIPSE, RECT or TRANSFORM.")],
  example=BP + 'bp.set_variant("BRUSH")')

C("bluepencil.has_drawings", "bluepencil", 'has_drawings(cam, space="VIEWPORT")', "bool",
  "True when a visible layer of the camera / window has strokes.",
  [("cam", "str", 'Camera object name, "" = the View.'), ("space", "str", "VIEWPORT, RENDER, ANIM or VIDEO.")],
  example=BP + 'print(bp.has_drawings("", "VIEWPORT"))')

C("bluepencil.set_panel_space", "bluepencil", "set_panel_space(space)", "None",
  "The Blue Pencil panel's window tab (also where New Layer goes).",
  [("space", "str", "VIEWPORT, RENDER, ANIM or VIDEO.")],
  example=BP + 'bp.set_panel_space("RENDER")\nprint(bp.panel_space())\nbp.set_panel_space("VIEWPORT")')

C("bluepencil.panel_space", "bluepencil", "panel_space()", "str",
  "The Blue Pencil panel's window tab.",
  example=BP + "print(bp.panel_space())")

C("bluepencil.new_space_layer", "bluepencil", "new_space_layer(space=None)", "dict – the layer",
  "A new layer for a window (default: the panel's tab) with that window's camera (space_camera()).",
  [("space", "str", "VIEWPORT, RENDER, ANIM or VIDEO.")],
  example=BP + 'lay = bp.new_space_layer("ANIM")\nprint(lay["name"], lay["space"])')

C("bluepencil.space_camera", "bluepencil", "space_camera(space)", "str",
  "The camera a new layer of a window gets: the 3D view's camera when looking through it (else \"\" = the View), "
  "the render camera, the scene camera for the Animation Player, \"\" for the Video Sequencer.",
  [("space", "str", "VIEWPORT, RENDER, ANIM or VIDEO.")],
  example=BP + 'print(repr(bp.space_camera("VIEWPORT")))')

C("burnin.set_enabled", "bluepencil", "set_enabled(on)", "None",
  "Burn In: Blue Pencil / annotations burnt into renders (Render → Burn In Drawings).",
  [("on", "bool", "On / off.")],
  example="import qt_shell.burnin as burnin\n\nburnin.set_enabled(True)\nburnin.set_enabled(False)")

C("burnin.viewport_render", "bluepencil", "viewport_render(scene=None, frame=None, overlays=True, vp=None)",
  "QImage", "The scene drawn like the 3D view at the render size (Viewport Render), with the drawings when overlays.",
  [("scene", "Scene", "Default: the current scene."), ("frame", "int", "Default: the current frame."),
   ("overlays", "bool", "Draw Blue Pencil / annotations."), ("vp", "QWidget", "The view; default the active one.")],
  example='''
import qt_shell.burnin as burnin

img = burnin.viewport_render()
img.save("C:/out/viewport.png")
''')

C("burnin.playblast", "bluepencil", "playblast(scene=None, start=None, end=None, overlays=True, vp=None)",
  "(frames written, folder or message)",
  "Viewport Render Animation: PNG frames in the folder `playblast` next to the output frames.",
  [("scene", "Scene", "Default: the current scene."), ("start", "int", "First frame."), ("end", "int", "Last frame."),
   ("overlays", "bool", "Draw the drawings."), ("vp", "QWidget", "The view.")],
  example='''
import bpy
import qt_shell.burnin as burnin

bpy.context.scene.render.filepath = "C:/out/shot_"
print(burnin.playblast(start=1, end=3))
''')

C("burnin.burn_animation", "bluepencil", "burn_animation(scene=None, start=None, end=None)",
  "(frames written, message)", "Copies the rendered frames with the drawings into the folder `overlay`.",
  [("scene", "Scene", "Default: the current scene."), ("start", "int", "First frame."), ("end", "int", "Last frame.")],
  example='''
import qt_shell.burnin as burnin

print(burnin.burn_animation())         # after Render Animation
''', run=False, skip="needs rendered frames")

C("annotate.add_stroke", "bluepencil", 'add_stroke(coords, mode="3DSPACE")', "None",
  "Adds a stroke to the active note layer of the 3D view's annotations (Blender data: scene.annotation).",
  [("coords", "list of (x, y, z)", "Points."), ("mode", "str", '"3DSPACE" (world) – Blender\'s stroke placement.')],
  example='''
import qt_shell.annotate as annotate

annotate.add_stroke([(0, 0, 0), (1, 0, 1), (2, 0, 0)])
''')

# =========================================================================================== updates
C("api.check_for_updates", "updates", "check_for_updates()", "dialog or None",
  "Help → Check for Qt Shell Updates…: the dialog with newer GitHub releases, their notes and Install. The dialog "
  "has select_version(\"0.65.0\"), selected() and install().",
  example='''
import qt_shell.api as qs

dlg = qs.check_for_updates()
dlg.close()
''')

C("api.latest_release", "updates", "latest_release()", "dict or None",
  '{"version": (0, 72, 0), "tag", "name", "notes", "url", "zip", "date"} of the newest release on GitHub. Blocks '
  "while it downloads; raises RuntimeError when Blender's online access is off.",
  example='''
import qt_shell.api as qs

rel = qs.latest_release()
print(rel["tag"], rel["date"])
''', run=False, skip="needs Blender's online access")


# ------------------------------------------------------------------------------------------- lookup
_BY_KEY = {c["key"]: c for c in COMMANDS}


def entry(key):
    return _BY_KEY.get(key)


def key_of(obj):
    """'api.status', 'sequencer.VideoSequencer.cut' … for a function / method / bound method."""
    fn = getattr(obj, "__func__", obj)
    mod = getattr(fn, "__module__", "") or ""
    qual = getattr(fn, "__qualname__", "") or ""
    if not mod.startswith("qt_shell") or not qual:
        return None
    return mod.split(".")[-1] + "." + qual


def lookup(obj):
    """The reference entry of a Qt Shell API object, or None."""
    k = key_of(obj)
    return _BY_KEY.get(k) if k else None


def text(c):
    """Plain-text help of an entry (Quick Help)."""
    out = [c["synopsis"], "", c["desc"], "", f"Returns: {c['returns']}"]
    if c["params"]:
        out += ["", "Parameters:"] + [f"  {n} ({t}) – {d}" if t else f"  {n} – {d}" for n, t, d in c["params"]]
    if c["example"]:
        out += ["", "Example:", c["example"]]
    return "\n".join(out)

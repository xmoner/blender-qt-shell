<p align="center"><img src="docs/logo/qt_shell_banner.png" alt="Qt Shell" width="100%"></p>

# Qt Shell – Blender UI in PySide6

A Blender 4.2+ add-on (Windows, Linux, macOS) that replaces the Blender interface with a Qt window.

## Installation

0. Download `qt_shell.zip` from [Releases](https://github.com/xmoner/blender-qt-shell/releases).
   (The zip from *Code → Download ZIP* cannot be installed by Blender – it contains the whole repository.)

1. Blender → Edit → Preferences → Add-ons → ▾ → **Install from Disk…** → `qt_shell.zip`.
2. Enable the **Qt Shell** add-on.
3. In the add-on preferences click **Install PySide6** (downloads `PySide6-Essentials` into
   Blender's user scripts folder; no admin rights needed). Blender does not respond while it
   installs.
4. Start it with **Window → Open Qt Shell** or F3 → "Open Qt Shell".
   The *Start Qt Shell when Blender starts* option opens it automatically every time Blender starts.

## What runs in Qt

| Part | How it works |
|---|---|
| 3D viewport | Blender renders the scene into a GPUOffScreen (`draw_view3d`) and the image is shown in Qt. Navigation (MMB / Alt+LMB orbit, Shift pan, Ctrl/wheel zoom, touchpad), numpad views 1/3/7/0/5/9, 2/4/6/8 rotation in 15° steps (Ctrl = pan), click and box selection, G/R/S with X/Y/Z axes and numeric input, Shift+D, X/Delete, Shift+A, H/Alt+H, Tab, Z (shading), right click = context menu |
| Menus | File, Edit, Add, Object, Select, Render and Help are generated **from Blender's original menus** (including add-on entries), depending on the mode |
| Cached playback | Like Maya: **geometry cache** (default) – the animated geometry and rig controls of each frame are stored and drawn by Qt Shell, so the **camera can move freely** during cached playback (solid shading incl. textures); **image cache** mode for the exact look incl. materials. Green line in the Timeline shows cached frames; Cache button + menu (mode, Cache All Frames, Flush Cache, Memory Limit); **Auto** = background caching while you are idle, no playback needed; the cache drops itself when the scene changes |
| Keyboard shortcuts | Edit → Keyboard Shortcuts…: every Qt Shell shortcut in one window (window, 3D View, Edit Mesh, Pose, Graph / Node / UV / Text editor) – search by name or key, change, add alternatives, clear, reset; conflicts marked; tooltips and menus always show the current keys |
| Maya & Blender key sets | 3D View keys come in two sets that follow the chosen controls: **Blender** (G/R/S, I, A, Alt+A, H, Tab, Z pie, numpad views …) and **Maya** (Q/W/E/R tools, S key all, Shift+W/E/R key location/rotation/scale, F/A frame, 4/5/6 wireframe/solid/material, Ctrl+H / Alt+H / Ctrl+Shift+H hide, F8 edit mode, F9/F10/F11 vertex/edge/face, Ctrl+E extrude, Ctrl+D duplicate). Each set is edited on its own in Qt Preferences → Shortcuts (or Interface → Navigation & Shortcuts) |
| Navigation | Blender or Maya mouse navigation in the 3D view (Qt Preferences → Interface): Maya = Alt+left tumble, Alt+middle track, Alt+right dolly, middle drag with the active tool |
| Recent files | File → Open Recent (also Ctrl+Shift+O): the last 20 opened / saved files, newest first, like Maya's Recent Files; Qt Shell keeps its own history next to Blender's |
| Properties | The Render, Output, Scene, World, Object, Data, Material, Physics… tabs are generated **from Blender's original Python panels** through a stand-in `UILayout` |
| Modifiers, constraints | Own Qt version (Blender draws these in C), including Geometry Nodes inputs; Add Modifier menu with categories, icons and a modifier-only Search… |
| Outliner | Blender's View Layer outliner with Maya's conveniences: display modes **View Layer / Blender File / Orphan Data** (Purge); restriction columns Exclude, Selectable, Hide in Viewport, Disable in Viewports / Renders, Holdout, Indirect Only – click, **drag across rows**, Ctrl+click isolates, Shift+click includes children; filter menu (columns, sort, sync selection, collections / objects / contents / children, object types, object state, invert); search with wildcards `*` `?` (Maya), exact / case options; collection colour tags; hidden objects greyed (Maya); drag & drop (left or middle mouse) to parent, drop on a collection to move (Ctrl = link), drop on empty space to unparent; context menus for objects and collections (select hierarchy, delete hierarchy, duplicate / instance collection, visibility, view layer, colour tag…); object contents (animation, data, bone hierarchy, materials, modifiers, constraints, vertex groups); follows the viewport selection; 21 keys (F show selected, Home hierarchy, Numpad +/− levels, A / Alt+A / Ctrl+I, F2, X, H / Alt+H, C, M / Shift+M, E / Alt+E, P / Shift+P, Ctrl+F / Alt+F), all editable in the Keyboard Shortcuts window; new icon set |
| Rigs | Object mode: clicking a rig control enters Pose mode and selects it (like Maya; can be turned off in Qt Preferences). Pose mode: click / Shift+click / box selection of bones by their custom shapes (rig controls) or bone lines; moving / rotating / scaling bones with G / R / S (axis, numbers) or the gizmos, keys with I / Alt+I (and the Timeline / Graph editor) on the selected controls, Graph editor and Timeline show only the selected controls' keys, auto-keying, Alt+G/R/S clear, A / Alt+A / Ctrl+I, H / Alt+H, pose context menu; Object mode: curves and armatures are hit by their lines |
| Timeline | Playback, frame range, keyframes, auto keying |
| Edit mode | Vertex / edge / face selection by click and box (occluded elements are skipped except in X-ray), switching with 1/2/3 or header buttons, G/R/S with axes, E (extrude), Shift+D, F, X/Delete, H/Alt+H, Ctrl+L, U (UV menu) |
| Node editor | Shader (material), world, Geometry Nodes, compositor: nodes, sockets, links (drag, pull out of an input), moving, mouse wheel zoom, F / Home frame all, Numpad . frame selected, **Tab** / Shift+A node search, X delete, M/H mute/hide, Ctrl+Tab into / out of a group, sidebar with node properties and input values |
| UV editor | UV map over the texture, UV point selection (click / box), G/R/S with axes, Unwrap / Smart UV / Cube / Reset, test UV grid texture |
| Number fields | Drag left/right to change the value like in Blender (the cursor is hidden and never hits the screen edge; Shift = fine, Ctrl = snap, Esc = cancel), click to type a value; also the Frame / Start / End fields in the timeline |
| Interface size | **Window → Interface Size…**: *Interface scale* (50–300 %, buttons, fields, icons, spacing and text) and *Text size* (50–250 %, text only), presets 80–200 %, live preview; OK rebuilds the window and widens/narrows the side panels to match. Also in the add-on preferences. |
| Playback | Space / ▶ in the timeline: frames are timed precisely and follow the scene *Sync* mode (Play Every Frame / Frame Dropping); the viewport shows the real `fps:` like Blender (red when below the scene rate). About 120 fps for a simple scene on Windows. |
| Text editor | Blender's texts (`bpy.data.texts`, saved in the .blend): New / Open / Save / Save As, Python highlighting, line numbers, auto-indent, Tab / Shift+Tab, Ctrl+/ comment, Ctrl+F find, **Run Script (Alt+P)** – output and errors in the Console, the failing line is highlighted; **Auto-complete** (after `.` and while typing, or Ctrl+Space; Tab / Enter accepts; `bpy.context.` → `object`, `scene`…, `qs.` → the Qt Shell API, variables from assignments and for-loops; can be turned off with the *Auto-complete* checkbox); **Run Selection (Ctrl+Enter)** runs the selected lines / current line in the script's namespace (an expression prints its value); **■ Unload** |
| Scripts (script manager) | Run / ⟳ Reload / ■ Unload in the Text editor; **Auto-load** – a text with the custom property `qtshell_autoload` runs when the .blend is opened (respects *Auto Run Python Scripts*). The **Scripts** dock (list of scripts, Auto-load checkboxes) is temporarily disabled – it crashed Blender on Windows when the window was shown. Qt Shell records what a script registers (Qt Shell API docks, menu items, overlays, events, `bpy` classes, `bpy.app.handlers`): Unload calls the script's `unregister()` and removes whatever is left, running a script again reloads it without duplicates |
| Shelf | Like Maya's shelf: script buttons in tabs (*Window → Shelf*) – a dock at the top that can float as its own window (double-click its title). **+** adds a tab, double-click a tab renames it. **Drag selected code from the Text editor onto it**, use **→ Shelf** in the Text editor, or drop a **.py file** – each makes a button that runs the code with one click (output and errors in the Console, undo works). Right click a button: Edit… (label, icon = emoji or image, tooltip, code or script file, ▶ Test), Duplicate, Move Left / Right, Move to Shelf, Delete; right click the bar: New Button…, New / Rename / Delete Shelf. Saved in `config/qt_shell/shelves.json`. |
| Workspaces | Like Blender's workspace tabs, on the right of the menu bar: **Layout, Modeling, Shading, Animation, Scripting** (+ **UV Editing** template). Each workspace remembers its own panels, floating windows, split-view layout and shading – rearrange a workspace and it stays that way. **+** adds a copy of the current workspace or one from a template (*General → …*); right click a tab: Rename…, Duplicate, Reset to Template, Move Left / Right, Delete; double-click renames. Saved in `config/qt_shell/workspaces.json`. |
| Graph editor | Like Maya's Graph Editor (*Window → Graph editor*; in the **Animation** workspace above the Timeline). Left: the animated channels of the selected objects in axis colours – check box shows / hides a curve, select channels to see only theirs. Right: the curves, keys, tangents of the selected keys and the current frame (drag in the ruler to scrub). **LMB** selects and drags keys / tangents, LMB on empty space box-selects (Shift adds, Ctrl removes), **MMB** moves the selected keys (Shift: time or value only), **Alt+MMB** pans, **Alt+RMB** / wheel zooms (Ctrl: time only, Shift: values only). **F** frames the selection, **A** all, **S** keys the shown curves at the current frame, **Delete** removes keys. Tangents: Auto, Spline, Linear, Flat, Stepped, Break, Unify; **Infinity**: Constant, Linear, Cycle, Cycle with Offset, Oscillate; **Frame / Value** boxes edit the selected keys; key times snap to whole frames (⌗ Snap). Rotation is shown in degrees; edits have undo. |
| Python tooltips | Like Blender's *Python Tooltips*: turn on **Edit → Qt Preferences… → Interface → Python Tooltips** and hovering a button, field or menu item also shows the Python command behind it – e.g. `bpy.ops.mesh.primitive_cube_add()`, `bpy.data.objects["Cube"].location`, `bpy.context.space_data.shading.type = 'SOLID'`, `qt_shell.api.set_viewport_layout('quad')`, or a Shelf button's code. **Shift + middle click** on a button, field or menu item copies its command to the clipboard (always on) – paste it into the Text editor or a script. Works for everything built from Blender's UI (operators, properties, menus) and for Qt Shell's own buttons (viewport header, toolbar, Timeline, Graph editor, Shelf, Outliner – also each row and restriction column, e.g. `bpy.data.objects["Cube"].hide_set(True)`). |
| 3D view header & navigation gizmo | Like Blender 5.2: the header shows the menus Blender draws for the current mode (Object: View, Select, Add, Object · Edit Mesh: View, Select, Add, Mesh, Vertex, Edge, Face, UV · Sculpt, Paint, Pose… – taken from Blender's `VIEW3D_MT_editor_menus`), the mode menu lists only the modes of the active object's type, then Transform Orientation, Pivot Point, Snapping and Proportional Editing (toggle + popover), Object type visibility, Gizmos, Overlays, X-Ray and shading. A header wider than the view scrolls with the mouse wheel. **Navigation gizmo**: click an axis ball (also the negative ones) to look along it, click the aligned axis again for the opposite side, drag the ball to orbit; buttons below: Zoom (drag), Pan (drag), Camera view, Perspective / Orthographic. |
| Icons | Qt Shell's own icon set in the style of Blender's interface (monochrome, 16 px grid – drawn for Qt Shell, not copied): 3D view header (modes, orientation, pivot, snapping, proportional editing, visibility, gizmos, overlays, X-ray, shading, layout, select modes), tool toolbar and Shift+Space menu, navigation gizmo buttons, Timeline. SVG in `qt_shell/icons.py` (`icons.icon(name)`, `icons.pixmap(name, size)`); preview: `docs/logo/icon_set_preview.png`. Blender's own icon names (`MESH_CUBE`, `MOD_ARRAY`, `OUTLINER_OB_CAMERA`, … – **all 1,032 names of Blender 5.2**, 726 drawings, `qt_shell/blicons.py` + `blicons_more.py`; key, colour-set, socket and curve families drawn by code) are drawn too and appear wherever Blender's UI asks for them: Add menu and its submenus, operator buttons, menus, Properties tabs (the Data tab follows the object type), Outliner, toggle buttons and enum buttons / menus (e.g. light type); preview: `docs/logo/blender_icons_preview.png`. |
| Qt Preferences | **Edit → Qt Preferences…**: Qt Shell's own settings in one window (Blender's stay in Edit → Preferences…) – Interface (size), Window (auto start, hide Blender window, reset window layout), Viewport (resolution, layout, toolbar, active tool), Text Editor (auto-complete), Scripts (files run on startup: tick / Add File… / Remove), System (versions, logs, status history, docs). Changes apply right away. |
| Transform tools | **Toolbar** in every 3D view (T shows / hides it) – **movable**: drag its dotted grip anywhere in the view; dropped near an edge it snaps to it (top / bottom edge → horizontal, left / right → vertical); right click: Horizontal / Vertical, Flip to Left / Right, Reset Position (or double-click the grip); the place is remembered. Tools: Select, **Move**, **Rotate**, **Scale**, **Transform** with a **gizmo** like Blender – Move: X / Y / Z arrows + centre (free); Rotate: X / Y / Z rings + outer ring (view axis); Scale: X / Y / Z handles + outer ring (uniform). Transform: all in one (arrows move, rings rotate, boxes on the axes scale). **Shift+Space** = tool menu (W Select, G Move, R Rotate, S Scale, T Transform), **W** = Select. Drag a handle, release to confirm, right click / Esc cancels; works in Object and Edit (mesh) mode, with undo and auto-keying. |
| Split viewport | **▦ Layout** in the viewport header or *View → Viewport Layout*: Single View, Two Views Side by Side, Two Views Stacked, **Four Views** (Top / Perspective / Front / Right, **Ctrl+Alt+Q** like the Quad View in Blender). Each view has its own camera and navigation, the dividers can be dragged, the view under the mouse is active (blue frame) and gets the keys, header and menu commands; moving objects updates all views live. The layout is remembered. |
| Status history | Click the status bar or 🕘 at its right end: the last 200 status messages of the session with their time (Copy / Clear). Every message is also written to the Console in grey. From scripts: `qs.status_history()`. |
| Sidebar (N panel) | N over the viewport (or Window → Sidebar): Blender's and add-ons' VIEW_3D sidebar panels in tabs (Item, Tool, View, …); Item ▸ Transform is a Qt version of Blender's C panel |
| Other | Python console, "Adjust Last Operation" (redo), F3 operator search, Qt file dialogs (Open/Save/Import/Export/Append/Link), F12 render with preview |

The Blender window is hidden (Windows: WinAPI, macOS: Cocoa via ctypes, Linux: `xdotool` on X11).
You can bring it back at any time with **Window → Show Blender Window**.

## Python API for add-ons (`qt_shell.api`)

**Full reference: [`docs/API.md`](docs/API.md)** – every function, event and example.

Development notes, status and open issues: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

Most add-ons need nothing special: Qt Shell runs Blender's own UI code, so these appear in Qt automatically:

- **Properties editor panels** (`bl_space_type = 'PROPERTIES'`),
- **3D viewport sidebar panels** – the N panel (`bl_space_type = 'VIEW_3D'`, `bl_region_type = 'UI'`), one tab per `bl_category`,
- **menu entries** appended to Blender menus (`bpy.types.VIEW3D_MT_add.append(...)`, `TOPBAR_MT_file`, …),
- **operators** (menus, F3 search, panel buttons).

For things that only exist in Qt Shell, use the API (`API_VERSION = (1, 3)`):

```python
import qt_shell.api as qs

qs.is_running()                       # True when the Qt window exists
qs.status("Done", timeout_ms=4000)    # status bar message
qs.status_history()                   # [('19:25:59', 'Done'), …] – also: click the status bar

# dockable panel – the factory is called on every window (re)build
def make_panel():
    from PySide6 import QtWidgets
    return QtWidgets.QPushButton("Top view", clicked=lambda: qs.set_view("TOP"))
qs.add_dock("my_panel", "My Panel", make_panel, area="left")      # left/right/bottom/top
qs.remove_dock("my_panel")

# menu items – existing menus ('File', 'Object', 'View', 'Window', …) or a new one ('Tools')
qs.add_menu_action("Tools", "Say Hello", lambda: qs.status("Hello"), shortcut="Ctrl+Alt+H")
qs.remove_menu_action("Tools/Say Hello")

# 3D view
qs.get_view()        # {'target': (x, y, z), 'distance', 'yaw', 'pitch', 'ortho', 'camera_view', 'name'}
qs.set_view("TOP")   # FRONT/BACK/LEFT/RIGHT/TOP/BOTTOM/CAMERA
qs.set_view(target=(0, 0, 1), distance=10, yaw=0.8, pitch=1.1, ortho=False)
qs.frame_all(); qs.frame_selected(); qs.redraw()
qs.project((1, 2, 3))           # world → (x, y) pixel in the viewport, or None
qs.view_matrix(); qs.projection_matrix(); qs.viewport_size()
qs.set_viewport_layout("quad")  # single / side / stacked / quad – view functions act on the active view
qs.viewport_layout(); qs.viewports()

# drawing over the viewport with QPainter
def draw(painter, ctx):          # ctx.width, ctx.height, ctx.project(co) → QPointF | None
    for ob in bpy.context.visible_objects:
        p = ctx.project(ob.matrix_world.translation)
        if p is not None:
            painter.drawText(p, ob.name)
qs.add_overlay("names", draw)
qs.remove_overlay("names")

# events: data, selection, frame(frame), mode(mode), file, undo, render,
#         operator(idname, props, result), playback(playing), window(main_window),
#         script(key, state)
h = qs.on("frame", lambda frame: print("frame", frame))
qs.off(h)

# ownership – remove everything an add-on registered in one call
with qs.owner("my_addon"):
    qs.add_dock(...); qs.add_menu_action(...)
qs.owned("my_addon")      # [('action', 'Tools/Say Hello'), ('dock', 'my_panel')]
qs.cleanup("my_addon")    # e.g. in your add-on's unregister()
```

Everything registered is kept when the Qt window is rebuilt (Interface Size, add-on reload) and can be
registered before Qt Shell starts. Callbacks run on Blender's main thread with a valid context; errors are
written to the log instead of breaking the UI. The module does not need PySide6 to be imported, so an add-on
can use it optionally:

```python
try:
    import qt_shell.api as qs
except ImportError:
    qs = None
```

A complete example is [`examples/api_demo.py`](examples/api_demo.py) – open it in the Text editor dock and press Alt+P,
then **■ Unload** to remove it again.

### Scripts: run, unload, reload

Write scripts like Blender add-ons – it keeps them easy to turn into an add-on later:

```python
def register():
    ...            # register classes, handlers, Qt Shell docks / menus / overlays / events

def unregister():
    ...            # optional in Qt Shell – whatever is left is removed automatically

if __name__ == "__main__":
    register()
```

A script run by Qt Shell (Text editor, Scripts dock, auto-load) owns everything it registers. **■ Unload**
calls its `unregister()` and then removes what is still registered; **Run** on a loaded script unloads it
first, so editing and re-running never leaves duplicate menu items or handlers. Not tracked automatically:
`bpy.app.timers`, keymaps and functions appended to Blender menus (`VIEW3D_MT_…append`) – remove those in
`unregister()`.

How to see which scripts are loaded and how to remove a script (also one set to auto-load on startup): [Which scripts are loaded / Removing a script](docs/API.md#removing-a-script).

## Tested

Blender 5.2.0 LTS, Windows 11 (Czech keyboard): startup, hiding the Blender window, viewport
(Solid / Material / Rendered), Add menu, redo panel, G/R/S with axes, Ctrl+Z, modifiers,
materials, lights, outliner, F12 render with fit-to-window, edit mode (vertex/edge/face selection,
box select, move, extrude), UV editor (Smart UV, selection, move), node editor (adding a node, linking,
moving, Geometry Nodes), numpad view rotation.

Number shortcuts (1/2/3 in edit mode, 1/3/7/0 views) follow the physical key, so they also work on
national keyboard layouts (e.g. Czech) without Shift.

## Troubleshooting

- Errors and warnings are also written to `qtshell.log` in the system temp folder
  (Windows: `%TEMP%\qtshell.log`), because Blender's console is hidden.
- If the Qt window can't be created, the normal Blender window comes back automatically.
- A hard crash writes the Python stack to `%TEMP%\qtshell_crash.log`.
- **Floating windows** (a dock dragged out of the main window) are docked before the layout is saved – a saved
  layout with a floating dock crashed Blender on the next start – and float again at their place a moment after Qt Shell starts.
- **Safe start:** if the previous start of Qt Shell crashed Blender, the next start discards the saved
  window layout and opens with the default one.

## Limitations

- The image editor, sculpt/paint brushes, gizmos and viewport header buttons of add-ons are not converted.
- The node editor does not show special node widgets (Color Ramp, curves) – their settings are in
  the sidebar only where they are plain RNA properties.
- The UV editor has its own UV point selection (not synced with Blender's UV selection).
- `template_*` elements without a Qt counterpart are shown as a grey `‹template_…›`.
- The Blender window cannot be hidden under pure Wayland.
- macOS: Qt and Blender share one Cocoa event loop; it works, but it is the least tested platform.

## License

GPL-3.0 (same as Blender), see [LICENSE](LICENSE).

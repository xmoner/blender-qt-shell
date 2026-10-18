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
| Properties | The Render, Output, Scene, World, Object, Data, Material, Physics… tabs are generated **from Blender's original Python panels** through a stand-in `UILayout` |
| Modifiers, constraints | Own Qt version (Blender draws these in C), including Geometry Nodes inputs |
| Outliner | Collections, objects, parenting, visibility, renaming, moving to a collection |
| Timeline | Playback, frame range, keyframes, auto keying |
| Edit mode | Vertex / edge / face selection by click and box (occluded elements are skipped except in X-ray), switching with 1/2/3 or header buttons, G/R/S with axes, E (extrude), Shift+D, F, X/Delete, H/Alt+H, Ctrl+L, U (UV menu) |
| Node editor | Shader (material), world, Geometry Nodes, compositor: nodes, sockets, links (drag, pull out of an input), moving, Shift+A node search, X delete, M/H mute/hide, Tab into a group, sidebar with node properties and input values |
| UV editor | UV map over the texture, UV point selection (click / box), G/R/S with axes, Unwrap / Smart UV / Cube / Reset, test UV grid texture |
| Number fields | Drag left/right to change the value like in Blender (the cursor is hidden and never hits the screen edge; Shift = fine, Ctrl = snap, Esc = cancel), click to type a value; also the Frame / Start / End fields in the timeline |
| Interface size | **Window → Interface Size…**: *Interface scale* (50–300 %, buttons, fields, icons, spacing and text) and *Text size* (50–250 %, text only), presets 80–200 %, live preview; OK rebuilds the window and widens/narrows the side panels to match. Also in the add-on preferences. |
| Playback | Space / ▶ in the timeline: frames are timed precisely and follow the scene *Sync* mode (Play Every Frame / Frame Dropping); the viewport shows the real `fps:` like Blender (red when below the scene rate). About 120 fps for a simple scene on Windows. |
| Sidebar (N panel) | N over the viewport (or Window → Sidebar): Blender's and add-ons' VIEW_3D sidebar panels in tabs (Item, Tool, View, …); Item ▸ Transform is a Qt version of Blender's C panel |
| Other | Python console, "Adjust Last Operation" (redo), F3 operator search, Qt file dialogs (Open/Save/Import/Export/Append/Link), F12 render with preview |

The Blender window is hidden (Windows: WinAPI, macOS: Cocoa via ctypes, Linux: `xdotool` on X11).
You can bring it back at any time with **Window → Show Blender Window**.

## Python API for add-ons (`qt_shell.api`)

Most add-ons need nothing special: Qt Shell runs Blender's own UI code, so these appear in Qt automatically:

- **Properties editor panels** (`bl_space_type = 'PROPERTIES'`),
- **3D viewport sidebar panels** – the N panel (`bl_space_type = 'VIEW_3D'`, `bl_region_type = 'UI'`), one tab per `bl_category`,
- **menu entries** appended to Blender menus (`bpy.types.VIEW3D_MT_add.append(...)`, `TOPBAR_MT_file`, …),
- **operators** (menus, F3 search, panel buttons).

For things that only exist in Qt Shell, use the API (`API_VERSION = (1, 0)`):

```python
import qt_shell.api as qs

qs.is_running()                       # True when the Qt window exists
qs.status("Done", timeout_ms=4000)    # status bar message

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

# drawing over the viewport with QPainter
def draw(painter, ctx):          # ctx.width, ctx.height, ctx.project(co) → QPointF | None
    for ob in bpy.context.visible_objects:
        p = ctx.project(ob.matrix_world.translation)
        if p is not None:
            painter.drawText(p, ob.name)
qs.add_overlay("names", draw)
qs.remove_overlay("names")

# events: data, selection, frame(frame), mode(mode), file, undo, render,
#         operator(idname, props, result), playback(playing), window(main_window)
h = qs.on("frame", lambda frame: print("frame", frame))
qs.off(h)
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

A complete example is in [`examples/api_demo.py`](examples/api_demo.py).

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

# Qt Shell – Python API reference

`qt_shell.api` lets scripts and add-ons extend the Qt Shell window: add dockable panels and menu items,
control the 3D views, draw over the viewport, react to events and show messages.

- **API version:** `1.4` (`qt_shell.api.API_VERSION == (1, 4)`), Qt Shell 0.33.0
- **Requires:** Blender 4.2+, PySide6 (installed from the add-on preferences)

---

## Contents

1. [Getting started](#1-getting-started)
2. [Basics: threads, context, errors](#2-basics-threads-context-errors)
3. [Window and status bar](#3-window-and-status-bar)
4. [Docks (panels)](#4-docks-panels)
5. [Menu items and shortcuts](#5-menu-items-and-shortcuts)
6. [3D views](#6-3d-views)
7. [Viewport layout (split views)](#7-viewport-layout-split-views)
8. [Overlays (drawing over the viewport)](#8-overlays-drawing-over-the-viewport) · [Buttons over the viewport](#buttons-over-the-viewport)
9. [Events](#9-events)
10. [Ownership and cleanup](#10-ownership-and-cleanup)
11. [Scripts: run, reload, unload, auto-load](#11-scripts-run-reload-unload-auto-load)
12. [Using the API from an add-on](#12-using-the-api-from-an-add-on)
13. [Complete example](#13-complete-example)
14. [Version history](#14-version-history)

---

## 1. Getting started

```python
import qt_shell.api as qs

qs.set_viewport_layout("quad")      # four views
qs.status("Hello from my script")   # message in the status bar
```

Where to run it:

| Where | How |
|---|---|
| **Console** (bottom tabs) | Type a line, press Enter. Good for trying things out. |
| **Text editor** (bottom tabs) | `+ New`, write a script, **▶ Run Script** (Alt+P). **Ctrl+Enter** runs the selected lines / the current line. Names are suggested after `.` (e.g. `qs.` lists this API) – **Ctrl+Space** shows suggestions any time. |
| **On startup** | See [Auto-load](#auto-load). |
| **From an add-on** | See [section 12](#12-using-the-api-from-an-add-on). |

`bpy` is Blender itself (objects, materials, animation, operators). `qs` is the Qt Shell window
(panels, menus, views, status bar). Most scripts use both.

---

## 2. Basics: threads, context, errors

- **Main thread, valid context.** Every callback you give to the API (dock factories, menu actions,
  overlays, event handlers) runs on Blender's main thread with a valid context, so `bpy.context` and
  `bpy.ops` work inside it.
- **Errors don't break the UI.** An exception in a callback is caught and written to the Console and
  to `%TEMP%\qtshell.log` (Windows) / `$TMPDIR/qtshell.log`. A failing **overlay** is removed after its
  first error, so it does not flood the log on every repaint.
- **Registrations persist.** Docks, menu items, overlays and event handlers are kept in a registry
  that lives for the whole Blender session. When the Qt window is rebuilt (Interface Size, add-on
  reload) they are installed again automatically. They also survive opening another .blend file.
- **Register any time.** You can register before Qt Shell is started; everything is applied when the
  window opens.
- **No PySide6 needed to import.** `import qt_shell.api` works even when PySide6 is missing –
  `is_running()` is then `False`. Import PySide6 only inside your callbacks.
- **IDs.** Functions that take an id (`dock_id`, `action_id`, `overlay_id`) replace an existing item with
  the same id, so running a script twice does not create duplicates.

---

## 3. Window and status bar

### `is_running() -> bool`
`True` when the Qt Shell window exists.

### `main_window() -> QMainWindow | None`
The Qt main window. Useful as a parent for your own dialogs. Its attributes are **not** part of the
stable API.

```python
from PySide6 import QtWidgets
QtWidgets.QMessageBox.information(qs.main_window(), "Info", "Done")
```

### `status(text, timeout_ms=4000)`
Shows `text` in the status bar at the bottom of the window.

| Parameter | Description |
|---|---|
| `text` | Message (converted with `str()`). |
| `timeout_ms` | How long it stays, in milliseconds. `0` = until the next message replaces it. |

Every message is also written to the Console (grey) and kept in the status history.

### `status_history() -> list[tuple[str, str]]`
The status bar messages of this Blender session, `[("19:25:59", "text"), …]`, newest **last**, at most 200.
In the UI: click the status bar or the 🕘 button at its right end.

---

## 4. Docks (panels)

### `add_dock(dock_id, title, factory, area="right", visible=True) -> str`
Adds a dockable panel. It also appears in the **Window** menu, so the user can show/hide it.

| Parameter | Description |
|---|---|
| `dock_id` | Unique id (string). Calling again with the same id replaces the dock. |
| `title` | Title of the dock. |
| `factory` | `fn() -> QWidget`. Called every time the Qt window is built – it must create a **new** widget each time. |
| `area` | `"left"`, `"right"`, `"bottom"` or `"top"` – where it appears the first time. The position the user drags it to is remembered. |
| `visible` | Shown the first time (later the saved state wins). |

Returns `dock_id`.

### `remove_dock(dock_id)`
Removes the dock.

```python
def make_panel():
    from PySide6 import QtWidgets
    w = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(w)
    for name in ("TOP", "FRONT", "RIGHT"):
        b = QtWidgets.QPushButton(name.title(), w)
        b.clicked.connect(lambda _=False, n=name: qs.set_view(n))
        lay.addWidget(b)
    lay.addStretch(1)
    return w

qs.add_dock("my_views", "My Views", make_panel, area="left")
```

> **Tip:** give every widget its parent when you create it (`QPushButton("…", w)`). A widget added to
> a layout that is not yet installed on a widget can be freed by Python and crash Qt when the
> window is shown.

> **Tip:** the factory runs again when the window is rebuilt, and the old widget is deleted.
> If you keep a reference to a widget, catch `RuntimeError` when using it (see the
> [complete example](#13-complete-example)).

---

## 5. Menu items and shortcuts

### `add_menu_action(menu, text, callback, shortcut=None, tooltip=None, action_id=None) -> str`
Adds an item to a menu of the menu bar.

| Parameter | Description |
|---|---|
| `menu` | Title of a top-level menu. An existing one – `File`, `Edit`, `Add`, `Object`, `Select`, `View`, `Render`, `Window`, `Help` – or a new one (e.g. `Tools` or the name of your add-on), which is created before **Help**. |
| `text` | Text of the item. |
| `callback` | `fn()` – runs in Blender's context. |
| `shortcut` | Optional key, e.g. `"Ctrl+Alt+H"`. Active in the whole Qt window and shown in the menu. |
| `tooltip` | Optional tooltip / status tip. |
| `action_id` | Optional id; default `"<menu>/<text>"`. |

Returns the action id.

### `remove_menu_action(action_id)`
Removes the item (and its shortcut).

```python
qs.add_menu_action("Tools", "Frame Selected", qs.frame_selected,
                   shortcut="Ctrl+Alt+F", action_id="my_frame")
qs.remove_menu_action("my_frame")
```

Items are added at the end of the menu, after a separator. Menus generated from Blender (File, Add,
Object, …) get them when they open.

> Functions appended to Blender's own menus (`bpy.types.VIEW3D_MT_add.append(draw_fn)`) also appear in
> Qt Shell automatically – no API needed.

---

## 6. 3D views

All functions in this section act on the **active view** – the view under the mouse / last clicked
(it has a blue frame when there are several views). They do nothing / return `None` when Qt Shell is
not running.

### `get_view() -> dict | None`
The current view:

| Key | Description |
|---|---|
| `target` | `(x, y, z)` – the point the view orbits around |
| `distance` | Distance from the target |
| `yaw` | Rotation around Z, radians |
| `pitch` | Tilt, radians: `0` = from above, `π/2` = horizontal, `π` = from below |
| `ortho` | `True` for orthographic |
| `camera_view` | `True` when looking through the scene camera |
| `name` | e.g. `"User Perspective"`, `"Top Orthographic"` |

### `set_view(preset=None, target=None, distance=None, yaw=None, pitch=None, ortho=None) -> bool`
Changes the view.

| Parameter | Description |
|---|---|
| `preset` | `"FRONT"`, `"BACK"`, `"LEFT"`, `"RIGHT"`, `"TOP"`, `"BOTTOM"` (orthographic views) or `"CAMERA"` (toggles the camera view). |
| `target`, `distance`, `yaw`, `pitch` | Set the orbit view directly (leaves the camera view). |
| `ortho` | `True` / `False` – orthographic / perspective. |

Returns `False` when Qt Shell is not running.

```python
import math
qs.set_view("TOP")
qs.set_view(target=(0, 0, 1), distance=12, yaw=math.radians(45), pitch=math.radians(60), ortho=False)
v = qs.get_view()
qs.set_view(yaw=v["yaw"] + math.radians(15))     # orbit 15°
```

### `frame_all()` / `frame_selected()`
Fit all visible objects / the selected objects into the view (like Home / Numpad .).

### `redraw()`
Redraws **all** views (scene and overlays). Call it after changing what your overlay draws.

### `viewport() -> QWidget | None`
The active view widget. Prefer the functions above – its attributes are not stable API.

### `viewport_size() -> (width, height) | None`
Size of the active view in Qt (logical) pixels.

### `view_matrix()` / `projection_matrix()` -> `mathutils.Matrix | None`
4×4 matrices of the active view for its current size.

### `project(co) -> (x, y) | None`
World coordinates → pixel position in the active view widget (`(0, 0)` = top-left), or `None` when
the point is behind the view.

```python
ob = bpy.context.object
print(qs.project(ob.matrix_world.translation))
```

---

## 7. Viewport layout (split views)

### `set_viewport_layout(mode) -> bool`

| `mode` | Layout |
|---|---|
| `"single"` | One view |
| `"side"` | Two views side by side |
| `"stacked"` | Two views, one above the other |
| `"quad"` | Four views: Top · Perspective / Front · Right |

Returns `False` when Qt Shell is not running. Raises `ValueError` for an unknown mode.
Each view keeps its own camera; when switching to `"quad"`, the Top / Front / Right views are set and
framed. In the UI: **▦ Layout** in the viewport header, *View → Viewport Layout*, or **Ctrl+Alt+Q**.

### `viewport_layout() -> str | None`
The current layout (`"single"`, `"side"`, `"stacked"` or `"quad"`).

### `viewports() -> list[QWidget]`
All visible view widgets of the current layout.

The shading (Solid / Material / Rendered) is Blender's own setting and is shared by all views.

---

## 8. Overlays (drawing over the viewport)

### `add_overlay(overlay_id, fn) -> str`
Draws over **every** 3D view with Qt's `QPainter`. `fn(painter, ctx)` is called on every repaint of
each view – keep it fast.

`ctx` (`OverlayContext`):

| Attribute | Description |
|---|---|
| `ctx.width`, `ctx.height` | Size of the view being painted |
| `ctx.view_matrix`, `ctx.projection_matrix` | Matrices of that view |
| `ctx.project(co)` | World coordinates → `QPointF` in that view, or `None` if behind the view |

The painter state is saved and restored around your function. If `fn` raises, the overlay is
removed and the error is logged.

### `remove_overlay(overlay_id)`

```python
def draw_names(painter, ctx):
    from PySide6 import QtCore, QtGui
    painter.setPen(QtGui.QColor("#ffcc33"))
    for ob in bpy.context.visible_objects:
        p = ctx.project(ob.matrix_world.translation)
        if p is not None:
            painter.drawText(p + QtCore.QPointF(8, -8), ob.name)

qs.add_overlay("names", draw_names)
qs.remove_overlay("names")
```

The overlay is repainted when the view changes. If it shows something that changes on its own
(a timer, external data), call `qs.redraw()`.


### Buttons over the viewport

An overlay only draws – it can't be clicked. For a clickable button in the 3D view, create a normal
PySide widget with the **viewport as its parent**: it then floats over the view. The full script is
[`examples/viewport_button.py`](../examples/viewport_button.py).

```python
import bpy
import qt_shell.api as qs

_buttons = []          # the Qt buttons we created (to remove them again)


def add_cube():
    """What the button does – runs inside Blender, bpy and bpy.ops work here."""
    bpy.ops.mesh.primitive_cube_add(location=bpy.context.scene.cursor.location)
    qs.status("Cube added")


def _make_buttons(*_args):
    _remove_buttons()
    from PySide6 import QtWidgets
    for vp in qs.viewports():                          # every visible 3D view
        b = QtWidgets.QPushButton("+ Cube", vp)        # parent = the viewport -> it floats over it
        b.setToolTip("Add a cube at the 3D cursor")
        b.clicked.connect(add_cube)
        b.move(10, 50)                                 # x, y from the top-left corner of the view
        b.show()
        _buttons.append(b)


def _remove_buttons():
    for b in _buttons:
        try:
            b.deleteLater()
        except RuntimeError:                           # already deleted with its viewport
            pass
    _buttons.clear()


def register():
    _make_buttons()
    qs.on("window", _make_buttons)    # the Qt window was rebuilt (Interface Size…) -> add them again


def unregister():
    _remove_buttons()


if __name__ == "__main__":
    register()
```

How it works:

- `qs.viewports()` returns the visible 3D views; the button is created as their child, so it is shown on
  top of the view and moves with it.
- The button's `clicked` handler runs inside Blender's context, so `bpy` and `bpy.ops` work in it.
- The Qt window is rebuilt e.g. after *Window → Interface Size*; the `"window"` event creates the buttons
  again.
- **■ Unload** removes the `"window"` handler automatically and calls `unregister()`, which deletes the
  buttons (Qt widgets you create yourself are not tracked, so remove them in `unregister()`).

Adapt it:

| What | Where |
|---|---|
| Text of the button | `QPushButton("+ Cube", vp)` |
| What it does | the body of `add_cube()` – e.g. `bpy.ops.object.shade_smooth()` or `qs.set_viewport_layout("quad")` |
| Position | `b.move(10, 50)` – pixels from the top-left corner of the view |
| More buttons | create another `QPushButton` in `_make_buttons()`, e.g. at `move(10, 85)` |

> The buttons are added to the views that are visible when the script runs. After switching the
> layout (e.g. to Four Views) run the script again. For buttons in a panel *next to* the viewport, use a
> [dock](#4-docks-panels) instead.

---

## 9. Events

### `on(event, fn) -> handle`
Calls `fn` when something happens. Returns a handle for `off()`. Raises `ValueError` for an unknown
event name.

### `off(handle)`
Removes the handler.

| Event | Arguments | When |
|---|---|---|
| `"data"` | `fn()` | Scene data changed (throttled) |
| `"selection"` | `fn()` | Selection or active object changed |
| `"frame"` | `fn(frame: int)` | Current frame changed |
| `"mode"` | `fn(mode: str)` | Mode changed: `"OBJECT"`, `"EDIT_MESH"`, … |
| `"file"` | `fn()` | A .blend file was loaded |
| `"undo"` | `fn()` | Undo / redo |
| `"render"` | `fn()` | F12 render finished |
| `"operator"` | `fn(idname, props, result)` | An operator was run from Qt Shell |
| `"playback"` | `fn(playing: bool)` | Animation playback started / stopped |
| `"window"` | `fn(main_window)` | The Qt window was (re)built |
| `"script"` | `fn(key: str, state: str)` | A script changed state (see [section 11](#11-scripts-run-reload-unload-auto-load)) |

`qs.EVENTS` contains the list of names.

```python
h = qs.on("frame", lambda f: qs.status(f"Frame {f}", 1000))
qs.off(h)
```

---

## 10. Ownership and cleanup

Everything registered inside `with qs.owner(name):` belongs to that owner and can be removed in one
call. This is the easiest way to clean up in an add-on's `unregister()`.

### `owner(name)` – context manager
### `current_owner() -> str | None`
### `owned(name) -> list[tuple[str, str]]`
What the owner registered: `[("dock", "my_panel"), ("action", "Tools/Hello"), ("overlay", …), ("event", "h3")]`.

### `cleanup(name) -> int`
Removes everything the owner registered. Returns the number of removed items.

```python
with qs.owner("my_addon"):
    qs.add_dock("my_panel", "My Panel", make_panel)
    qs.add_menu_action("Tools", "Hello", lambda: qs.status("Hello"))

qs.cleanup("my_addon")
```

Scripts run by Qt Shell (Text editor, auto-load) are owners automatically – their key (see below) is
the owner name.

---

## 11. Scripts: run, reload, unload, auto-load

Qt Shell records what a script registers while it runs:

- Qt Shell API docks, menu items, overlays, event handlers,
- `bpy` classes (`bpy.utils.register_class`),
- `bpy.app.handlers`.

**■ Unload** (Text editor) calls the script's `unregister()` if it has one, and then removes everything
that is still registered. **Run** on a loaded script unloads it first (= **⟳ Reload**), so editing and
re-running never leaves duplicates.

Not tracked automatically: `bpy.app.timers`, keymaps and functions appended to Blender menus –
remove those in `unregister()`.

Recommended structure (the same as a Blender add-on):

```python
import bpy
import qt_shell.api as qs

def register():
    qs.add_menu_action("Tools", "Hello", lambda: qs.status("Hello"), action_id="hello")

def unregister():          # optional in Qt Shell
    qs.remove_menu_action("hello")

if __name__ == "__main__":
    register()
```

### Script keys
A script is identified by a key:

- `"text:<name>"` – a text in `bpy.data.texts` without a file (saved in the .blend),
- `"file:<path>"` – a `.py` file (also a text opened from that file; its current content is run).

### `qt_shell.scripts` – managing scripts from Python

```python
import qt_shell.scripts as s
```

| Function | Description |
|---|---|
| `s.key_for_text(text)` | Key of a `bpy.types.Text`. |
| `s.run(key)` | Runs the script (unloads it first if loaded). Returns a result with `.ok`, `.output`, `.error_line`, `.removed`. |
| `s.unload(key)` | Calls `unregister()` and removes what is left. Returns a result (`.removed` = number of removed items). |
| `s.unload_all()` | Unloads every loaded script. |
| `s.is_loaded(key)` | `True` when the script has run in this session and was not unloaded. |
| `s.info(key)` | `None` or `{"status": "loaded" | "ran" | "error", "items": n, "error_line", "time", "has_unregister"}`. |
| `s.items(key)` | Human-readable list of what the script registered. |
| `s.add_file(path)` | Adds a .py file to the script list; returns its key. |
| `s.remove_file(key)` | Removes the file from the list (the file itself is kept). |
| `s.set_autoload(key, on)` | Turns auto-load on / off (see below). |
| `s.autoload(key)` | `True` when auto-load is on. |

The `"script"` event is emitted with these states: `loaded`, `ran`, `error`, `unloaded`, `added`,
`removed`, `autoload`, `blocked`.

### Auto-load

**A file on every start of Qt Shell** (once per Blender session):

```python
import qt_shell.scripts as s
s.set_autoload(s.add_file(r"C:\Users\me\Documents\qt_start.py"), True)
```

The list is stored in Blender's config folder: `config/qt_shell/scripts.json`.

**A text when its .blend file is opened:**

```python
bpy.data.texts["Text"]["qtshell_autoload"] = True    # then save the .blend
```

This needs *Edit → Preferences → Save & Load → Auto Run Python Scripts*. When it is off, the script is
not run and a message appears in the Console.

When another .blend is opened, scripts from the texts of the old file are unloaded.

### Which scripts are loaded

Paste into the **Console** and press Enter:

```python
import qt_shell.scripts as s; print("\n".join(f'{s.info(k)["status"]:8} {s.location(k)}' for k in s.all_keys() if s.info(k)) or "No script is loaded")
```

```
ran      c:\users\me\documents\qt_start.py
loaded   in the .blend
```

| Status | Meaning |
|---|---|
| `loaded` | The script registered something (menu item, dock, overlay, handler, class) that is still active. **■ Unload** removes it. |
| `ran` | The script ran but registered nothing lasting. |
| `error` | The script stopped with an error (see the Console). |

Scripts set to auto-load on startup: `s.managed_files()` → `[(key, autoload), …]`.

### Removing a script

**In the Text editor** (a script opened or written there):

1. Choose the script in the list at the top left of the **Text editor**.
2. **■ Unload** – removes what the script registered (greyed out when there is nothing to remove).
3. **✕** – deletes the text from the .blend file. A file on disk is kept; delete it in your file manager
   if you don't need it.

**A file set to auto-load on startup** – deleting it from the Text editor is not enough, it would run
again on the next start. Remove it from the script list (this also unloads it):

```python
import qt_shell.scripts as s; k = s.add_file(r"C:\Users\me\Documents\qt_start.py"); s.unload(k); s.remove_file(k)
```

`add_file` only turns the path into the script's key – a file that is already in the list is not added
twice. To keep the file in the list and only stop it from running on startup:

```python
import qt_shell.scripts as s; s.set_autoload(s.add_file(r"C:\Users\me\Documents\qt_start.py"), False)
```

**A text set to auto-load with its .blend:**

```python
del bpy.data.texts["Text"]["qtshell_autoload"]    # then save the .blend
```

> **Unload does not undo one-time changes.** It removes what a script *registered*, not what it *did*:
> objects it created stay in the scene (delete them or use Ctrl+Z), and a layout it switched to stays
> (`qs.set_viewport_layout("single")` or Ctrl+Alt+Q).

---

## 12. Using the API from an add-on

Make Qt Shell optional – your add-on keeps working without it:

```python
try:
    import qt_shell.api as qs
except ImportError:
    qs = None

def register():
    # … your normal registration …
    if qs is not None:
        with qs.owner(__package__):
            qs.add_menu_action("Tools", "My Tool", my_tool, action_id=f"{__package__}.my_tool")

def unregister():
    if qs is not None:
        qs.cleanup(__package__)
    # … your normal unregistration …
```

Most add-ons need nothing special, because Qt Shell runs Blender's own UI code:

- **Properties editor panels** (`bl_space_type = 'PROPERTIES'`) appear in the Properties dock,
- **3D view sidebar panels** (`bl_space_type = 'VIEW_3D'`, `bl_region_type = 'UI'`) appear in the
  Sidebar (N), one tab per `bl_category`,
- **menu entries** appended to Blender menus appear in Qt Shell menus,
- **operators** work from menus, F3 search and panel buttons.

Use `qt_shell.api` for things that exist only in Qt Shell: Qt docks, Qt menu items with shortcuts,
QPainter overlays, view control and the viewport layout.

---

## 13. Complete example

A dock that shows the active object and updates on selection / frame changes, a menu with a shortcut
and an overlay with object names. Open it in the Text editor and press Alt+P; **■ Unload** removes
everything. (A shorter version of [`examples/api_demo.py`](../examples/api_demo.py).)

```python
import bpy
import qt_shell.api as qs

_state = {"label": None}


def _update_label(*_args):
    lab = _state["label"]
    if lab is None:
        return
    ob = bpy.context.view_layer.objects.active
    try:
        lab.setText(f"Active object: {ob.name if ob else '—'}\n"
                    f"Selected: {len(bpy.context.selected_objects)}\n"
                    f"Frame: {bpy.context.scene.frame_current}")
    except RuntimeError:          # the widget was deleted (window rebuilt)
        _state["label"] = None


def make_dock():
    from PySide6 import QtWidgets
    w = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(w)
    _state["label"] = QtWidgets.QLabel(w)
    lay.addWidget(_state["label"])
    for text, fn in (("Top view", lambda: qs.set_view("TOP")),
                     ("Four views", lambda: qs.set_viewport_layout("quad")),
                     ("Frame all", qs.frame_all)):
        b = QtWidgets.QPushButton(text, w)
        b.clicked.connect(fn)
        lay.addWidget(b)
    lay.addStretch(1)
    _update_label()
    return w


def draw_names(painter, ctx):
    from PySide6 import QtCore, QtGui
    painter.setPen(QtGui.QColor("#ffcc33"))
    for ob in bpy.context.visible_objects:
        p = ctx.project(ob.matrix_world.translation)
        if p is not None:
            painter.drawText(p + QtCore.QPointF(8, -8), ob.name)


def register():
    qs.add_dock("api_demo", "API Demo", make_dock, area="left")
    qs.add_menu_action("Tools", "Say Hello", lambda: qs.status("Hello!"),
                       shortcut="Ctrl+Alt+H", action_id="demo_hello")
    qs.add_overlay("demo_names", draw_names)
    qs.on("selection", _update_label)
    qs.on("frame", _update_label)


if __name__ == "__main__":
    register()
```

No `unregister()` is needed here – Unload removes what `register()` added.

---

## 14. Version history

| API | Qt Shell | Changes |
|---|---|---|
| 1.2 | 0.9.0 – 0.9.1 | `set_viewport_layout()`, `viewport_layout()`, `viewports()`; overlays drawn in every view. 0.9.1: `status_history()`, status messages also in the Console. |
| 1.3 | 0.31.1 | `outliner()` – the Outliner from a script (modes, search, options, columns, collections, parenting, visibility). |
| 1.4 | 0.33.0 | `render_view()` – the Render View window (slots, channels, zoom, save, clipboard). |
| 1.5 | 0.34.0 | `set_tool()`, `active_tool()`, `TOOLS` – the 3D viewport's toolbar tools (incl. Annotate, Measure, Add); Render View: `set_tool()`, annotations (`add_annotation`, `annotations`, `clear_annotations`, `undo_annotation`, `set_annotation_style`), `set_overlays`, `set_gizmos`, `set_toolbar`. |
| 1.10 | 0.68.0 | Render View `set_tool("BLUE_PENCIL", variant)`, `picture()`, `has_drawings()`; Animation Player `set_blue_pencil()`; `bluepencil.ImageBPTools`, `bluepencil.set_variant()`, `bluepencil.paint_layers()`. |
| 1.9 | 0.64.0 | `image_editor()` – the Image editor: sources (compositor Viewer, render result, rendered animation, images), live compositor updates, channels, zoom, frames / playback, export image / animation (MP4, image sequences). |
| 1.8 | 0.58.0 | `run_op(idname, invoke=False, **props)` – a Blender operator run like Qt Shell's menus (3D view context, Qt-handled operators, undo). |
| 1.7 | 0.53.1 | `uv_editor()` – the UV editor: component mode, Blender UV operators in a UV editor context, projections, unwrap / layout, move / rotate / flip / align / normalize, texel density, display toggles, image. |
| 1.6 | 0.36.0 | `timeline()` – the Timeline: view range / zoom, play / stop / step, loop mode, preview range, frame rate, seconds, key selection / moving, markers. |
| 1.1 | 0.8.0 | `owner()`, `current_owner()`, `owned()`, `cleanup()`; `"script"` event; registrations survive opening another .blend; script manager (`qt_shell.scripts`). |
| 1.0 | 0.6.0 | First version: docks, menu actions, status, view control, overlays, events. |

Check the version in your code:

```python
if qs.API_VERSION >= (1, 2):
    qs.set_viewport_layout("quad")
```

## Render View from a script

`qt_shell.api.render_view()` (API 1.4) returns Qt Shell's render window (Blender's Image Editor with the Render Result):

```python
import qt_shell
rv = qt_shell.api.render_view()
rv.present()                         # show it (F11)
rv.set_slot(1)                       # Slot 2 – the next render goes there (J / Alt+J cycle the slots)
rv.set_channel("ALPHA")              # COLOR_ALPHA, COLOR, ALPHA, RED, GREEN, BLUE
rv.passes()                          # {"ViewLayer": ["Combined", "Depth", "Normal", …]}
rv.set_pass("Depth"); rv.set_layer("ViewLayer")
rv.zoom(1); rv.fit()                 # 1:1, Frame All
rv.save_as("C:/renders/frame.png")   # the format follows the extension (.png .jpg .exr .tif .webp .bmp)
rv.copy_to_clipboard()
# API 1.5 – toolbar (T), annotations, header toggles
rv.set_tool("ANNOTATE", "LINE")      # SAMPLE, or ANNOTATE with FREEHAND / LINE / POLYGON / ERASER
rv.set_tool("BLUE_PENCIL", "BRUSH")  # API 1.10 – Blue Pencil over the render (the Render View's own layers)
rv.picture()                         # API 1.10 – QImage as shown: render + Blue Pencil + annotations
rv.add_annotation([(10, 10), (200, 120)], color="#ff4040", width=4)   # image pixels from the top-left
rv.annotations()                     # strokes of the active render slot: [{"pts", "color", "width"}, …]
rv.undo_annotation(); rv.clear_annotations()
rv.set_annotation_style(color="#619bc7", width=3)   # colour / thickness of new strokes
rv.set_overlays(False); rv.set_gizmos(True); rv.set_toolbar(True)
```

Render View annotations are kept per render slot for the Blender session. Since Qt Shell 0.67.3 Save / Save As
(PNG, JPEG, TIFF, WebP, BMP), Copy to Clipboard and Edit Externally write the picture as shown – with the
annotations and the Blue Pencil of the render's camera (OpenEXR keeps the clean render).

**Animation Player** (API 1.10): `qs.main_window().anim_player.set_blue_pencil(True)` draws Blue Pencil on the
frame shown – the strokes go to the Animation Player's own layers at that frame. Since Qt Shell 0.69.0 every Blue
Pencil layer has a `"space"`: `VIEWPORT`, `RENDER` or `ANIM` (`bluepencil.SPACES`, `bluepencil.in_space(layer, camera,
space)`, `bluepencil.new_layer(..., space=…)`); each window draws only its own layers.
Since Qt Shell 0.70.0 the Blue Pencil panel lists one window at a time: `bluepencil.panel_space()` / `bluepencil.set_panel_space("RENDER")` (signal `bluepencil.signals.space(str)`); `bluepencil.new_space_layer(space=None)` creates a layer for a window (default: the panel's tab) with `bluepencil.space_camera(space)` – the 3D view's camera or View, the Render View's render camera, or the scene camera.

## Timeline from a script

`qt_shell.api.timeline()` (API 1.6) returns the Timeline of the Qt Shell window (None when Qt Shell is closed):

```python
import qt_shell
tl = qt_shell.api.timeline()
tl.set_view_range(0, 120)          # visible frames (zoom / pan); tl.view_range()
tl.zoom(0.5); tl.frame_all()       # < 1 zooms in; Frame All = the scene (or preview) range
tl.play(); tl.play(reverse=True); tl.stop(); tl.step(1)
tl.set_loop_mode("OSCILLATE")      # LOOP, ONCE, OSCILLATE (Maya)
tl.set_preview_range(True, 10, 50); tl.set_preview_range(False)
tl.set_fps(25); tl.set_fps(30, 1.001)   # 29.97 fps
tl.set_show_seconds(True)
tl.select_keys([10, 20]); tl.move_selected_keys(5); tl.selected_keys()
tl.add_marker("Contact", 24)       # bpy.context.scene.timeline_markers
```

## Toolbar tools from a script

`qt_shell.api.set_tool(tool, variant=None)` (API 1.5) activates a tool of the 3D viewport's toolbar (shared by all
views); `active_tool()` returns `(tool, variant)`; `qt_shell.api.TOOLS` lists the tools and their variants:

```python
import qt_shell
qs = qt_shell.api
qs.set_tool("SELECT", "LASSO")      # TWEAK, BOX, CIRCLE, LASSO
qs.set_tool("SCALE", "CAGE")
qs.set_tool("ANNOTATE", "POLYGON")  # FREEHAND, LINE, POLYGON, ERASER
qs.set_tool("MEASURE")
qs.set_tool("ADD", "UV_SPHERE")     # CUBE, CONE, CYLINDER, UV_SPHERE, ICO_SPHERE (Object Mode)
qs.set_tool("BLUE_PENCIL", "BRUSH") # PENCIL, BRUSH, ERASER, TEXT, LINE, ARROW, ELLIPSE, RECT, TRANSFORM
qs.active_tool()                    # ('BLUE_PENCIL', 'BRUSH')
```

Blue Pencil drawings (0.44) live in `qt_shell.bluepencil`: `data()` (layers → frames → strokes, JSON in
`scene["qtshell_bluepencil"]`), `new_layer(name, camera)`, `insert_frame()`, `duplicate_frame()`, `delete_frame()`,
`copy_frame()`, `paste_frame()`, `step(1 | -1)`, `retime("ABS", 2)` / `retime("REL", -1)`; after editing `data()`
yourself call `commit("message")` (saves to the scene, one undo step).

Burn-in and Viewport Render (0.47): `qt_shell.burnin.set_enabled(True)`, `burnin.burn_animation()` (rendered frames → folder `overlay`), `burnin.viewport_render()` (QImage), `burnin.playblast()` (folder `playblast`); the Animation Player's `set_source("RENDER" | "OVERLAY" | "PLAYBLAST")`.

3D view annotations are Blender data: `bpy.context.scene.annotation` (layers → frames → strokes → points `co`),
rulers of the Measure tool are the strokes of its layer `RulerData3D`. `qt_shell.annotate.add_stroke(coords)`
adds a stroke to the active note layer.

## Outliner from a script

`qt_shell.api.outliner()` (API 1.3) returns the Outliner of the Qt Shell window (None when Qt Shell is closed).
These are also the commands the Outliner's Python tooltips show:

```python
import qt_shell, bpy
ol = qt_shell.api.outliner()
ol.set_mode("BLENDER_FILE")        # VIEW_LAYER, BLENDER_FILE, ORPHAN
ol.search("*foot*")                # wildcards * and ?; "" clears the search
ol.set_option("sort_alpha", False) # filter / display options, keys in qt_shell.outliner.DEFAULTS
ol.show_column("select", True)     # exclude, select, hide, viewport, render, holdout, indirect
ol.show_selected(); ol.show_hierarchy(); ol.one_level(True); ol.expand_toggle()
ol.new_collection()
ol.move_to(bpy.data.collections["Props"])   # selected objects / collections
ol.parent_to_active(); ol.clear_parent()     # keep the world transform
ol.hide_selected(); ol.unhide_all()
ol.isolate(("OBJECT", "Cube"))     # like Ctrl+click on the eye
ol.collection_visibility(bpy.data.collections["Props"], hide=True, inside=True)
ol.duplicate_collection(bpy.data.collections["Props"]); ol.instance_collection(bpy.data.collections["Props"])
ol.delete(hierarchy=False)
```

Blender's own `bpy.ops.outliner.*` operators need a Blender Outliner area and fail from a script in Qt Shell.

## Graph editor from a script

`qt_shell.api.graph_editor()` returns the Graph editor of the Qt Shell window (None when Qt Shell is closed):

```python
import qt_shell
ge = qt_shell.api.graph_editor()
ge.set_snap(True)               # snap key times to whole frames (the ⌗ Snap button)
ge.set_tangents("LINEAR")       # AUTO, AUTO_CLAMPED (Spline), LINEAR, FLAT, CONSTANT (Stepped)
ge.set_handle_type("FREE")      # FREE = Break tangents, ALIGNED = Unify
ge.set_infinity("REPEAT")       # CONSTANT, LINEAR, REPEAT (Cycle), REPEAT_OFFSET, MIRROR (Oscillate)
ge.insert_keys()                # key the shown curves at the current frame
ge.delete_keys()                # delete the selected keys
ge.frame_all(); ge.frame_selected()
```

Tangents and infinity apply to the selected keys, or to all shown curves when no key is selected.
Blender's own `bpy.ops.graph.*` operators and `bpy.context.space_data.auto_snap` only work inside a Blender
Graph Editor area – from a script in Qt Shell `space_data` is the 3D view.

## UV editor from a script

`qt_shell.api.uv_editor()` (API 1.7) returns the UV editor of the Qt Shell window (None when Qt Shell is closed).
Every button of the UV editor shows its Python line in the tooltip (Shift + middle click copies it).

```python
import qt_shell
uv = qt_shell.api.uv_editor()
uv.set_mode("FACE")                          # VERT, EDGE, FACE, ISLAND (shell)
uv.tool("uv.pack_islands", {"margin": 0.01}) # any bpy.ops.uv operator, run in a UV editor context
uv.mesh_tool("uv.smart_project")             # projections on the selected faces (all when none)
uv.unwrap(); uv.layout_shells()
uv.move_by(0.1, 0); uv.rotate_by(90); uv.flip(True)   # flip(True) = horizontally (U)
uv.align("UMIN"); uv.normalize()
uv.texel_get(); uv.set_texel_density(512)
uv.set_display("checker", True)             # also shown on the mesh in the 3D viewport (0.54.0)
uv.set_image("UV Grid")
uv.canvas.select_all("SELECT"); uv.canvas.frame_selected()
```

The UV editor works on the active mesh in Edit Mode (Tab).

## Operators from a script

`qt_shell.api.run_op(idname, invoke=False, **props)` (API 1.8) runs a Blender operator the way Qt Shell's menus
do: in a 3D view context, with Qt Shell's own handling where it has one (e.g. `render.render` opens the
Render View like F12, `transform.translate` starts the interactive move) and an undo step. Shelf buttons can
also call `bpy.ops` directly – their code runs in a 3D view context.

```python
import qt_shell
qt_shell.api.run_op("mesh.primitive_cube_add", size=2)
qt_shell.api.run_op("render.render", animation=True)
```

Shelf button icons: an emoji / symbol, an image file, or `bl:NAME` for any Blender icon (`bl:MESH_CUBE`).

## Shelf files

Shelves can be saved to and loaded from `.json` files (the button next to the shelf's **+**), also from Python:

```python
from qt_shell import shelf
shelf.export_shelves(r"C:/shelves/modeling.json", ["Modeling"])   # None = all shelves
shelf.import_shelves(r"C:/shelves/modeling.json")                 # added as new tabs of the open Shelf
shelf.shelf_folder()                                              # default folder: config/qt_shell/shelves
```

## Image editor from a script

`qt_shell.api.image_editor()` (API 1.9) returns the Image editor dock (None when Qt Shell is closed). With the
source **COMPOSITOR** it shows the compositor's Viewer node and follows every change of the compositor nodes
(the compositor works on the last render).

```python
import qt_shell
ie = qt_shell.api.image_editor()
ie.set_source("COMPOSITOR")           # COMPOSITOR (result), VIEWER, RENDER, ANIMATION or an image name
ie.set_live(True)                     # re-read the Viewer whenever the compositor ran (False = freeze the picture)
ie.refresh()                          # Reload: the compositor's current result
ie.reload(); ie.fit(); ie.zoom(1)     # 1 = 1:1
ie.set_channel("ALPHA")               # COLOR_ALPHA, COLOR, ALPHA, RED, GREEN, BLUE
ie.export_image("C:/renders/comp.exr")              # .png .jpg .exr .tif .webp .bmp
ie.set_source("ANIMATION"); ie.set_frame(12); ie.play(); ie.pause()
ie.set_cache_range(10, 40)            # From / To (None, None = the scene range)
ie.render_raw()                       # frames without compositing → Live composites the animation (cached)
ie.use_frames(r"C:/frames")           # frames rendered before (any image sequence); None = this file's own
ie.export_animation("C:/renders/anim.mp4", "MP4", 1, 120)   # MP4, PNG, JPEG, TIFF, COPY

from qt_shell import image_editor
image_editor.ensure_compositor()      # compositor nodes (Render Layers → Group Output) + a Viewer node
```

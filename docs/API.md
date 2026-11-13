# Qt Shell – Python API reference

`qt_shell.api` lets scripts and add-ons extend the Qt Shell window: add dockable panels and menu items,
control the 3D views, draw over the viewport, react to events and show messages.

- **API version:** `1.14` (`qt_shell.api.API_VERSION == (1, 14)`), Qt Shell 0.110.0 – every command with an example: [Command reference](#15-command-reference)
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
15. [Command reference](#15-command-reference) – every command: synopsis, return value, parameters, example

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

### Restart Blender
`qt_shell.api.main_window().restart_blender(confirm=True)` (Qt Shell 0.74.0) quits Blender and starts it again with
the current file (when saved); `confirm=True` asks Save / Discard / Cancel when the file has unsaved changes.

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

Oldest first. `qt_shell.api.API_VERSION` is the last row.

| API | Qt Shell | Changes |
|---|---|---|
| 1.0 | 0.6.0 | First version: docks, menu actions, status, view control, overlays, events. |
| 1.1 | 0.8.0 | `owner()`, `current_owner()`, `owned()`, `cleanup()`; `"script"` event; registrations survive opening another .blend; script manager (`qt_shell.scripts`). |
| 1.2 | 0.9.0 – 0.9.1 | `set_viewport_layout()`, `viewport_layout()`, `viewports()`; overlays drawn in every view. 0.9.1: `status_history()`, status messages also in the Console. |
| 1.3 | 0.31.1 | `outliner()` – the Outliner from a script (modes, search, options, columns, collections, parenting, visibility). |
| 1.4 | 0.33.0 | `render_view()` – the Render View window (slots, channels, zoom, save, clipboard). |
| 1.5 | 0.34.0 | `set_tool()`, `active_tool()`, `TOOLS` – the 3D viewport's toolbar tools (incl. Annotate, Measure, Add); Render View: `set_tool()`, annotations (`add_annotation`, `annotations`, `clear_annotations`, `undo_annotation`, `set_annotation_style`), `set_overlays`, `set_gizmos`, `set_toolbar`. |
| 1.6 | 0.36.0 | `timeline()` – the Timeline: view range / zoom, play / stop / step, loop mode, preview range, frame rate, seconds, key selection / moving, markers. |
| 1.7 | 0.53.1 | `uv_editor()` – the UV editor: component mode, Blender UV operators in a UV editor context, projections, unwrap / layout, move / rotate / flip / align / normalize, texel density, display toggles, image. |
| 1.8 | 0.58.0 | `run_op(idname, invoke=False, **props)` – a Blender operator run like Qt Shell's menus (3D view context, Qt-handled operators, undo). |
| 1.9 | 0.64.0 | `image_editor()` – the Image editor: sources (compositor Viewer, render result, rendered animation, images), live compositor updates, channels, zoom, frames / playback, export image / animation (MP4, image sequences). |
| 1.10 | 0.68.0 | Render View `set_tool("BLUE_PENCIL", variant)`, `picture()`, `has_drawings()`; Animation Player `set_blue_pencil()`; `bluepencil.ImageBPTools`, `bluepencil.set_variant()`, `bluepencil.paint_layers()`. |
| 1.11 | 0.71.0 | Animation Player `export_animation(path, kind, start, end, blue_pencil)` – Save Animation clean or with Blue Pencil burnt in; `bluepencil.has_drawings()`, `bluepencil.paint_layers(…, always=True)`. |
| 1.12 | 0.72.0 | `check_for_updates()` (Help → Check for Qt Shell Updates… dialog), `latest_release()` – the newest GitHub release. |
| 1.13 | 0.102.0 | `video_sequencer()` – the Video Sequencer: add movies / sounds / images / scenes / camera shots / text / colour / adjustment / transitions, cut, delete (ripple), duplicate, move, trim, meta strips, play with sound. |
| 1.14 | 0.109.0 | Video Sequencer `export_video(path, fmt, start, end, quality, scale, audio)`, `last_export`; `qt_shell.seq_export.formats()`. |

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
Since Qt Shell 0.71.0 (API 1.11) `anim_player.export_animation(path=None, kind=None, start=None, end=None, blue_pencil=None)` saves the frames played: kind `MP4`, `PNG`, `JPEG`, `TIFF` or `COPY`; `blue_pencil=True` burns in the Animation Player's Blue Pencil layers (COPY then becomes PNG); without a path a dialog asks. Returns the number of frames saved. `bluepencil.has_drawings(camera, space)`; `bluepencil.paint_layers(..., always=True)` draws even when Show drawings is off.
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

## Updates from a script

`qt_shell.api.check_for_updates()` (API 1.12, Qt Shell 0.72.0) opens Help → Check for Qt Shell Updates… (returns the
dialog; since 0.73.0 `dlg.select_version("0.65.0")` picks a release in its Version list, `dlg.selected()` returns it,
`dlg.install()` installs the picked one). `qt_shell.api.latest_release()` reads the newest published release from GitHub (blocking; raises when
Blender's online access is off): `{"version": (0, 72, 0), "tag", "name", "notes", "url", "zip", "date"}` or None.
The startup check is QSettings `updates/auto` ("true" / "false", default off) – at most once a day
(`updates/last_check`).

## Shelf files

Shelves can be saved to and loaded from `.json` files (the button next to the shelf's **+**), also from Python:

```python
from qt_shell import shelf
shelf.export_shelves(r"C:/shelves/modeling.json", ["Modeling"])   # None = all shelves
shelf.import_shelves(r"C:/shelves/modeling.json")                 # added as new tabs of the open Shelf
shelf.shelf_folder()                                              # default folder: config/qt_shell/shelves
```

## Video Sequencer from a script

`qt_shell.api.video_sequencer()` (API 1.13) returns the Video Sequencer dock (None when Qt Shell is closed). It edits
Blender's own strips (`scene.sequence_editor`), so plain bpy works alongside it; each method makes one undo step.

```python
import bpy, qt_shell
vs = qt_shell.api.video_sequencer()
vs.add_files(["C:/clips/a.mp4", "C:/music/song.wav"], frame=1)   # movies (+ their sound), sounds, images
vs.add_camera_shot(bpy.data.objects["Camera.001"])  # Maya-style shot after the last one (preview / scene range)
vs.add_camera_shot(cam, 1, 48)                       # … of scene frames 1–48
vs.add_scene(bpy.data.scenes["Intro"]); vs.add_text(); vs.add_color(); vs.add_adjustment()
vs.select([s1, s2]); vs.add_transition("CROSS")      # CROSS, GAMMA_CROSS, WIPE between two strips
vs.cut(48)                         # split the selected strips (none selected: all) at frame 48
vs.delete(ripple=True)             # delete the selection and close the gap on its channel
vs.duplicate(); vs.move_strips(vs.selected(), 10, 1); vs.trim(strip, "r", 120)
vs.make_meta(); vs.enter_meta(meta); vs.exit_meta(); vs.separate_meta()
vs.set_flag("mute", True); vs.range_to_strips(); vs.play_sound()

# Export (API 1.14) – rendered by Blender like Render Animation; the scene's output settings are put back
vs.export_video()                                    # the Export dialog
vs.export_video("C:/out/edit.mp4", "MP4_H264")       # the scene range, High quality, 100 %, with sound
vs.export_video("C:/out/web.webm", "WEBM_VP9", start=1, end=240, quality="MEDIUM", scale=50, audio=False)
vs.export_video("C:/out/frames/shot.png", "SEQ_PNG") # shot_0001.png …
vs.export_video("C:/out/mix.wav", "AUDIO_WAV")       # the sound alone
vs.last_export                                       # {"path", "format", "start", "end", "state", "files"}
qt_shell.seq_export.formats()                        # ids this Blender can write:
# MP4_H264 MP4_H265 MP4_AV1 MOV_H264 MOV_PRORES MKV_H264 MKV_FFV1 WEBM_VP9 AVI_H264 OGG_THEORA
# SEQ_PNG SEQ_JPEG SEQ_TIFF SEQ_EXR SEQ_WEBP   AUDIO_WAV AUDIO_MP3 AUDIO_FLAC AUDIO_OGG
# quality: "LOSSLESS" / "HIGH" / "MEDIUM" / "LOW";  scale: per cent of the scene resolution
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
ie.set_auto_reload(True)              # Auto: an image shown follows Texture Paint live (default on)
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

<!-- BEGIN COMMAND REFERENCE (generated by tools/make_api_reference.py) -->

## 15. Command reference

Every command of the API on its own, like Maya's command documentation: synopsis, return value, description, parameters and an example you can paste into the **Console** or the **Text editor**. The same text appears in the Text editor's **Quick Help** (F1 on a name). The examples use `C:/out/…` and `C:/clips/…` for files – change the paths to yours. Every example marked ✔ is run by an automatic test in Blender 5.2.

[Window and status bar](#15-window-and-status-bar) · [Docks (panels)](#15-docks-panels) · [Menu items and shortcuts](#15-menu-items-and-shortcuts) · [3D views](#15-3d-views) · [Viewport layout](#15-viewport-layout) · [Overlays](#15-overlays) · [Events](#15-events) · [Ownership and cleanup](#15-ownership-and-cleanup) · [Toolbar tools and operators](#15-toolbar-tools-and-operators) · [Scripts (qt_shell.scripts)](#15-scripts-qt_shellscripts) · [Shelf files (qt_shell.shelf)](#15-shelf-files-qt_shellshelf) · [Timeline](#15-timeline) · [Outliner](#15-outliner) · [Graph editor](#15-graph-editor) · [UV editor](#15-uv-editor) · [Render View](#15-render-view) · [Animation Player](#15-animation-player) · [Image editor](#15-image-editor) · [Video Sequencer](#15-video-sequencer) · [Blue Pencil, burn-in and annotations](#15-blue-pencil-burn-in-and-annotations) · [Updates](#15-updates)

### 15 Window and status bar

| Command | Description |
|---|---|
| [`is_running`](#is_running) | True when the Qt Shell window exists. |
| [`main_window`](#main_window) | The Qt main window – use it as the parent of your own dialogs. |
| [`MainWindow.restart_blender`](#mainwindowrestart_blender) | Quits Blender and starts it again with the current file (when it is saved). |
| [`status`](#status) | Shows a message in the status bar. |
| [`status_history`](#status_history) | The status bar messages of this Blender session, newest last (at most 200). |

#### is_running

**Synopsis:** `qt_shell.api.is_running()`  
**Returns:** bool

True when the Qt Shell window exists. Use it before calling functions that need the window.

**Example** (✔ tested)

```python
import qt_shell.api as qs

if qs.is_running():
    qs.status("Qt Shell is open")
```

#### main_window

**Synopsis:** `qt_shell.api.main_window()`  
**Returns:** QMainWindow or None

The Qt main window – use it as the parent of your own dialogs. Its attributes are not part of the stable API.

**Example** (✔ tested)

```python
import qt_shell.api as qs
from PySide6 import QtWidgets

box = QtWidgets.QMessageBox(qs.main_window())
box.setWindowTitle("My tool")
box.setText("Done")
box.show()                      # box.exec() waits for the user instead
box.close()
```

#### MainWindow.restart_blender

**Synopsis:** `MainWindow.restart_blender(confirm=True)`  
**Returns:** None

Quits Blender and starts it again with the current file (when it is saved). With confirm=True it asks Save / Discard / Cancel when the file has unsaved changes.

| Parameter | Type | Description |
|---|---|---|
| `confirm` | bool | Ask about unsaved changes first. |

**Example** (not run by the test – restarts Blender)

```python
import qt_shell.api as qs

qs.main_window().restart_blender()            # File → Restart Blender
```

#### status

**Synopsis:** `qt_shell.api.status(text, timeout_ms=4000)`  
**Returns:** None

Shows a message in the status bar. Every message is also written to the Console and kept in the status history.

| Parameter | Type | Description |
|---|---|---|
| `text` | str | The message (converted with str()). |
| `timeout_ms` | int | How long it stays, in milliseconds; 0 = until the next message. |

**Example** (✔ tested)

```python
import qt_shell.api as qs

qs.status("Export finished")                 # 4 seconds
qs.status("Rendering… please wait", 0)       # stays until the next message
```

#### status_history

**Synopsis:** `qt_shell.api.status_history()`  
**Returns:** list of (time, text)

The status bar messages of this Blender session, newest last (at most 200). In the UI: click the status bar.

**Example** (✔ tested)

```python
import qt_shell.api as qs

qs.status("Hello")
for stamp, text in qs.status_history()[-5:]:
    print(stamp, text)                         # 19:25:59 Hello
```

### 15 Docks (panels)

| Command | Description |
|---|---|
| [`add_dock`](#add_dock) | Adds a dockable panel; it also appears in the Window menu. |
| [`remove_dock`](#remove_dock) | Removes a dock added with add_dock(). |

#### add_dock

**Synopsis:** `qt_shell.api.add_dock(dock_id, title, factory, area="right", visible=True)`  
**Returns:** str – the dock id

Adds a dockable panel; it also appears in the Window menu. The factory runs every time the Qt window is built and must create a new widget each time. Calling it again with the same id replaces the dock.

| Parameter | Type | Description |
|---|---|---|
| `dock_id` | str | Unique id. |
| `title` | str | Title of the dock. |
| `factory` | fn() -> QWidget | Creates the dock's widget. |
| `area` | str | "left", "right", "bottom" or "top" – where it appears the first time. |
| `visible` | bool | Shown the first time (later the saved state wins). |

**Example** (✔ tested)

```python
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
```

#### remove_dock

**Synopsis:** `qt_shell.api.remove_dock(dock_id)`  
**Returns:** None

Removes a dock added with add_dock().

| Parameter | Type | Description |
|---|---|---|
| `dock_id` | str | The id given to add_dock(). |

**Example** (✔ tested)

```python
import qt_shell.api as qs
from PySide6 import QtWidgets

qs.add_dock("notes", "Notes", lambda: QtWidgets.QTextEdit(), area="right")
qs.remove_dock("notes")
```

### 15 Menu items and shortcuts

| Command | Description |
|---|---|
| [`add_menu_action`](#add_menu_action) | Adds an item to a menu of the menu bar (after a separator at its end). |
| [`remove_menu_action`](#remove_menu_action) | Removes a menu item (and its shortcut) added with add_menu_action(). |

#### add_menu_action

**Synopsis:** `qt_shell.api.add_menu_action(menu, text, callback, shortcut=None, tooltip=None, action_id=None)`  
**Returns:** str – the action id

Adds an item to a menu of the menu bar (after a separator at its end). A menu that does not exist yet is created before Help. Calling it again with the same id replaces the item.

| Parameter | Type | Description |
|---|---|---|
| `menu` | str | Title of a top-level menu: File, Edit, Add, Object, Select, View, Render, Window, Help or a new one. |
| `text` | str | Text of the item. |
| `callback` | fn() | Runs in Blender's context. |
| `shortcut` | str | Optional key, e.g. "Ctrl+Alt+H" – active in the whole window. |
| `tooltip` | str | Optional tooltip / status tip. |
| `action_id` | str | Optional id; default "<menu>/<text>". |

**Example** (✔ tested)

```python
import qt_shell.api as qs

qs.add_menu_action("Tools", "Frame Selected", qs.frame_selected,
                   shortcut="Ctrl+Alt+F", tooltip="Fit the selection into the view", action_id="my_frame")
qs.remove_menu_action("my_frame")
```

#### remove_menu_action

**Synopsis:** `qt_shell.api.remove_menu_action(action_id)`  
**Returns:** None

Removes a menu item (and its shortcut) added with add_menu_action().

| Parameter | Type | Description |
|---|---|---|
| `action_id` | str | The returned id. |

**Example** (✔ tested)

```python
import qt_shell.api as qs

aid = qs.add_menu_action("Tools", "Say Hello", lambda: qs.status("Hello"))
qs.remove_menu_action(aid)                    # aid == "Tools/Say Hello"
```

### 15 3D views

| Command | Description |
|---|---|
| [`get_view`](#get_view) | The active 3D view: target (x, y, z), distance, yaw and pitch (radians), ortho, camera_view and name. |
| [`set_view`](#set_view) | Changes the active 3D view: a preset, or the orbit view directly (this leaves the camera view). |
| [`frame_all`](#frame_all) | Fits all visible objects into the active view (Home). |
| [`frame_selected`](#frame_selected) | Fits the selected objects into the active view (Numpad . |
| [`redraw`](#redraw) | Redraws all 3D views (scene and overlays). |
| [`viewport`](#viewport) | The active 3D view widget. |
| [`viewport_size`](#viewport_size) | Size of the active view in Qt (logical) pixels. |
| [`view_matrix`](#view_matrix) | The 4×4 view matrix of the active view. |
| [`projection_matrix`](#projection_matrix) | The 4×4 projection matrix of the active view for its current size. |
| [`project`](#project) | World coordinates → pixel position in the active view widget ((0, 0) = top-left); None when the point is behind the view. |

#### get_view

**Synopsis:** `qt_shell.api.get_view()`  
**Returns:** dict or None

The active 3D view: target (x, y, z), distance, yaw and pitch (radians), ortho, camera_view and name. None when Qt Shell is not running.

**Example** (✔ tested)

```python
import math
import qt_shell.api as qs

v = qs.get_view()
print(v["name"], round(math.degrees(v["yaw"])), v["distance"])
```

#### set_view

**Synopsis:** `qt_shell.api.set_view(preset=None, target=None, distance=None, yaw=None, pitch=None, ortho=None)`  
**Returns:** bool – False when Qt Shell is not running

Changes the active 3D view: a preset, or the orbit view directly (this leaves the camera view).

| Parameter | Type | Description |
|---|---|---|
| `preset` | str | "FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM" or "CAMERA" (toggles the camera view). |
| `target` | (x, y, z) | The point the view orbits around. |
| `distance` | float | Distance from the target. |
| `yaw` | float | Rotation around Z, radians. |
| `pitch` | float | Tilt, radians: 0 = from above, π/2 = horizontal. |
| `ortho` | bool | Orthographic (True) or perspective (False). |

**Example** (✔ tested)

```python
import math
import qt_shell.api as qs

qs.set_view("TOP")
qs.set_view(target=(0, 0, 1), distance=12, yaw=math.radians(45), pitch=math.radians(60), ortho=False)
v = qs.get_view()
qs.set_view(yaw=v["yaw"] + math.radians(15))          # orbit 15°
```

#### frame_all

**Synopsis:** `qt_shell.api.frame_all()`  
**Returns:** None

Fits all visible objects into the active view (Home).

**Example** (✔ tested)

```python
import qt_shell.api as qs

qs.frame_all()
```

#### frame_selected

**Synopsis:** `qt_shell.api.frame_selected()`  
**Returns:** None

Fits the selected objects into the active view (Numpad . / Maya F).

**Example** (✔ tested)

```python
import bpy
import qt_shell.api as qs

bpy.ops.mesh.primitive_monkey_add(location=(4, 0, 0))   # the new object is selected
qs.frame_selected()
```

#### redraw

**Synopsis:** `qt_shell.api.redraw()`  
**Returns:** None

Redraws all 3D views (scene and overlays). Call it after changing what an overlay draws.

**Example** (✔ tested)

```python
import qt_shell.api as qs

qs.redraw()
```

#### viewport

**Synopsis:** `qt_shell.api.viewport()`  
**Returns:** QWidget or None

The active 3D view widget. Prefer the view functions – its attributes are not stable API.

**Example** (✔ tested)

```python
import qt_shell.api as qs

vp = qs.viewport()
print(vp.width(), vp.height())
```

#### viewport_size

**Synopsis:** `qt_shell.api.viewport_size()`  
**Returns:** (width, height) or None

Size of the active view in Qt (logical) pixels.

**Example** (✔ tested)

```python
import qt_shell.api as qs

w, h = qs.viewport_size()
qs.status(f"The view is {w} × {h} px")
```

#### view_matrix

**Synopsis:** `qt_shell.api.view_matrix()`  
**Returns:** mathutils.Matrix or None

The 4×4 view matrix of the active view.

**Example** (✔ tested)

```python
import qt_shell.api as qs

m = qs.view_matrix()
print(m.inverted().translation)                 # where the view's eye is
```

#### projection_matrix

**Synopsis:** `qt_shell.api.projection_matrix()`  
**Returns:** mathutils.Matrix or None

The 4×4 projection matrix of the active view for its current size.

**Example** (✔ tested)

```python
import qt_shell.api as qs

full = qs.projection_matrix() @ qs.view_matrix()    # world → clip space
print(full)
```

#### project

**Synopsis:** `qt_shell.api.project(co)`  
**Returns:** (x, y) or None

World coordinates → pixel position in the active view widget ((0, 0) = top-left); None when the point is behind the view.

| Parameter | Type | Description |
|---|---|---|
| `co` | Vector / (x, y, z) | A point in world space. |

**Example** (✔ tested)

```python
import bpy
import qt_shell.api as qs

ob = bpy.context.view_layer.objects.active or bpy.context.scene.objects[0]
print(ob.name, qs.project(ob.matrix_world.translation))
```

### 15 Viewport layout

| Command | Description |
|---|---|
| [`set_viewport_layout`](#set_viewport_layout) | Splits the 3D view. |
| [`viewport_layout`](#viewport_layout) | The current layout: "single", "side", "stacked" or "quad". |
| [`viewports`](#viewports) | All visible 3D view widgets of the current layout. |

#### set_viewport_layout

**Synopsis:** `qt_shell.api.set_viewport_layout(mode)`  
**Returns:** bool – False when Qt Shell is not running

Splits the 3D view. Each view keeps its own camera; "quad" sets and frames Top / Front / Right. Raises ValueError for an unknown mode.

| Parameter | Type | Description |
|---|---|---|
| `mode` | str | "single", "side" (two side by side), "stacked" (one above the other) or "quad" (Top · Perspective / Front · Right). |

**Example** (✔ tested)

```python
import qt_shell.api as qs

qs.set_viewport_layout("quad")
qs.set_viewport_layout("single")
```

#### viewport_layout

**Synopsis:** `qt_shell.api.viewport_layout()`  
**Returns:** str or None

The current layout: "single", "side", "stacked" or "quad".

**Example** (✔ tested)

```python
import qt_shell.api as qs

if qs.viewport_layout() != "single":
    qs.set_viewport_layout("single")
```

#### viewports

**Synopsis:** `qt_shell.api.viewports()`  
**Returns:** list of QWidget

All visible 3D view widgets of the current layout.

**Example** (✔ tested)

```python
import qt_shell.api as qs

qs.set_viewport_layout("side")
print(len(qs.viewports()))                     # 2
qs.set_viewport_layout("single")
```

### 15 Overlays

| Command | Description |
|---|---|
| [`add_overlay`](#add_overlay) | Draws over every 3D view with Qt's QPainter. |
| [`remove_overlay`](#remove_overlay) | Removes an overlay. |

#### add_overlay

**Synopsis:** `qt_shell.api.add_overlay(overlay_id, fn)`  
**Returns:** str – the overlay id

Draws over every 3D view with Qt's QPainter. fn(painter, ctx) runs on every repaint – keep it fast. ctx has width, height, view_matrix, projection_matrix and project(co) → QPointF or None. A failing overlay is removed.

| Parameter | Type | Description |
|---|---|---|
| `overlay_id` | str | Unique id; the same id replaces the overlay. |
| `fn` | fn(painter, ctx) | The drawing function. |

**Example** (✔ tested)

```python
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
```

#### remove_overlay

**Synopsis:** `qt_shell.api.remove_overlay(overlay_id)`  
**Returns:** None

Removes an overlay.

| Parameter | Type | Description |
|---|---|---|
| `overlay_id` | str | The id given to add_overlay(). |

**Example** (✔ tested)

```python
import qt_shell.api as qs

qs.add_overlay("frame", lambda p, ctx: p.drawRect(4, 4, ctx.width - 8, ctx.height - 8))
qs.remove_overlay("frame")
```

### 15 Events

| Command | Description |
|---|---|
| [`on`](#on) | Calls fn when something happens. |
| [`off`](#off) | Removes an event handler. |

#### on

**Synopsis:** `qt_shell.api.on(event, fn)`  
**Returns:** handle for off()

Calls fn when something happens. Events (qt_shell.api.EVENTS): data, selection, frame(frame), mode(mode), file, undo, render, operator(idname, props, result), playback(playing), window(main_window), script(key, state). Raises ValueError for an unknown name.

| Parameter | Type | Description |
|---|---|---|
| `event` | str | Event name. |
| `fn` | callable | The handler; its arguments depend on the event. |

**Example** (✔ tested)

```python
import qt_shell.api as qs

h = qs.on("frame", lambda f: qs.status(f"Frame {f}", 1000))
qs.off(h)
```

#### off

**Synopsis:** `qt_shell.api.off(handle)`  
**Returns:** None

Removes an event handler.

| Parameter | Type | Description |
|---|---|---|
| `handle` |  | What on() returned. |

**Example** (✔ tested)

```python
import qt_shell.api as qs

h = qs.on("selection", lambda: print("selection changed"))
qs.off(h)
```

### 15 Ownership and cleanup

| Command | Description |
|---|---|
| [`owner`](#owner) | Everything registered inside `with owner(name):` belongs to that owner and can be removed with cleanup(name) – the easiest clean-up for an add-on's unregister(). |
| [`current_owner`](#current_owner) | The owner of what is registered right now (inside `with owner():` or a script run by Qt Shell). |
| [`owned`](#owned) | What an owner registered: [("dock", "my_panel"), ("action", "Tools/Hello"), ("overlay", …), ("event", "h3")]. |
| [`cleanup`](#cleanup) | Removes everything an owner registered (docks, menu items, overlays, event handlers). |

#### owner

**Synopsis:** `qt_shell.api.owner(name)`  
**Returns:** context manager

Everything registered inside `with owner(name):` belongs to that owner and can be removed with cleanup(name) – the easiest clean-up for an add-on's unregister(). Scripts run by Qt Shell are owners automatically.

| Parameter | Type | Description |
|---|---|---|
| `name` | str | Owner name, e.g. your add-on's __package__. |

**Example** (✔ tested)

```python
import qt_shell.api as qs

with qs.owner("my_addon"):
    qs.add_menu_action("Tools", "Hello", lambda: qs.status("Hello"))
    qs.on("frame", lambda f: None)
print(qs.owned("my_addon"))
qs.cleanup("my_addon")
```

#### current_owner

**Synopsis:** `qt_shell.api.current_owner()`  
**Returns:** str or None

The owner of what is registered right now (inside `with owner():` or a script run by Qt Shell).

**Example** (✔ tested)

```python
import qt_shell.api as qs

with qs.owner("my_addon"):
    print(qs.current_owner())                  # my_addon
```

#### owned

**Synopsis:** `qt_shell.api.owned(name)`  
**Returns:** list of (kind, id)

What an owner registered: [("dock", "my_panel"), ("action", "Tools/Hello"), ("overlay", …), ("event", "h3")].

| Parameter | Type | Description |
|---|---|---|
| `name` | str | Owner name. |

**Example** (✔ tested)

```python
import qt_shell.api as qs

with qs.owner("demo"):
    qs.add_overlay("demo_dot", lambda p, ctx: p.drawEllipse(10, 10, 6, 6))
print(qs.owned("demo"))                        # [('overlay', 'demo_dot')]
qs.cleanup("demo")
```

#### cleanup

**Synopsis:** `qt_shell.api.cleanup(name)`  
**Returns:** int – number of removed items

Removes everything an owner registered (docks, menu items, overlays, event handlers).

| Parameter | Type | Description |
|---|---|---|
| `name` | str | Owner name. |

**Example** (✔ tested)

```python
import qt_shell.api as qs

with qs.owner("demo"):
    qs.add_menu_action("Tools", "Demo", lambda: None)
print(qs.cleanup("demo"))                      # 1
```

### 15 Toolbar tools and operators

| Command | Description |
|---|---|
| [`set_tool`](#set_tool) | Activates a tool of the 3D viewport's toolbar (shared by all views). |
| [`active_tool`](#active_tool) | The active toolbar tool, e.g. |
| [`run_op`](#run_op) | Runs a Blender operator the way Qt Shell's menus do: in a 3D view context, with Qt Shell's own handling where it has one (render.render opens the Render View like F12, transform.translate starts the interactive move) and an undo step. |

#### set_tool

**Synopsis:** `qt_shell.api.set_tool(tool, variant=None)`  
**Returns:** bool

Activates a tool of the 3D viewport's toolbar (shared by all views). qt_shell.api.TOOLS lists the tools and their variants. Raises ValueError for an unknown tool or variant.

| Parameter | Type | Description |
|---|---|---|
| `tool` | str | SELECT, CURSOR, MOVE, ROTATE, SCALE, TRANSFORM, ANNOTATE, MEASURE, ADD or BLUE_PENCIL. |
| `variant` | str | SELECT: TWEAK BOX CIRCLE LASSO · SCALE: SCALE CAGE · ANNOTATE: FREEHAND LINE POLYGON ERASER · ADD: CUBE CONE CYLINDER UV_SPHERE ICO_SPHERE · BLUE_PENCIL: PENCIL BRUSH ERASER TEXT LINE ARROW ELLIPSE RECT TRANSFORM. |

**Example** (✔ tested)

```python
import qt_shell.api as qs

old = qs.active_tool()
qs.set_tool("SELECT", "LASSO")
qs.set_tool("MEASURE")
qs.set_tool(*old)                              # back to what it was
```

#### active_tool

**Synopsis:** `qt_shell.api.active_tool()`  
**Returns:** (tool, variant) or None

The active toolbar tool, e.g. ('SELECT', 'BOX') or ('MEASURE', None).

**Example** (✔ tested)

```python
import qt_shell.api as qs

tool, variant = qs.active_tool()
qs.status(f"Tool: {tool} {variant or ''}")
```

#### run_op

**Synopsis:** `qt_shell.api.run_op(idname, invoke=False, **props)`  
**Returns:** set – the operator's result

Runs a Blender operator the way Qt Shell's menus do: in a 3D view context, with Qt Shell's own handling where it has one (render.render opens the Render View like F12, transform.translate starts the interactive move) and an undo step.

| Parameter | Type | Description |
|---|---|---|
| `idname` | str | Operator id, e.g. "mesh.primitive_cube_add". |
| `invoke` | bool | Run it like a click (INVOKE_DEFAULT) instead of with the given values. |
| `**props` |  | Operator properties. |

**Example** (✔ tested)

```python
import qt_shell.api as qs

qs.run_op("mesh.primitive_cube_add", size=2, location=(0, 3, 0))
qs.run_op("object.shade_smooth")
```

### 15 Scripts (qt_shell.scripts)

| Command | Description |
|---|---|
| [`key_for_text`](#key_for_text) | The script key of a bpy.types.Text: "text:<name>" (saved in the .blend) or "file:<path>". |
| [`run`](#run) | Runs a script (unloads it first when it is loaded – a reload). |
| [`unload`](#unload) | Calls the script's unregister() (when it has one) and removes what it registered and is still there. |
| [`unload_all`](#unload_all) | Unloads every loaded script. |
| [`is_loaded`](#is_loaded) | True when the script ran in this session, registered something and was not unloaded. |
| [`info`](#info) | {"status": "loaded" | "ran" | "error", "items", "error_line", "time", "has_unregister"}; None for a script that has not run. |
| [`items`](#items) | Human-readable list of what a script registered. |
| [`all_keys`](#all_keys) | Keys of all known scripts: texts of the .blend, files in the script list and scripts that ran. |
| [`location`](#location) | Where a script lives: its file path, or "in the .blend" for a text without a file. |
| [`add_file`](#add_file) | Adds a .py file to the script list (config/qt_shell/scripts.json). |
| [`remove_file`](#remove_file) | Removes a file from the script list (the file itself is kept) and unloads it. |
| [`set_autoload`](#set_autoload) | Turns auto-load on / off: a file in the script list runs on every start of Qt Shell (once per session); a text gets the property qtshell_autoload and runs when its .blend is opened (needs Auto Run Python Scripts). |
| [`autoload`](#autoload) | True when auto-load is on for the script. |
| [`managed_files`](#managed_files) | The .py files in the script list (config/qt_shell/scripts.json). |

#### key_for_text

**Synopsis:** `qt_shell.scripts.key_for_text(t)`  
**Returns:** str

The script key of a bpy.types.Text: "text:<name>" (saved in the .blend) or "file:<path>".

| Parameter | Type | Description |
|---|---|---|
| `t` | bpy.types.Text | A text. |

**Example** (✔ tested)

```python
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("hello.py")
print(s.key_for_text(t))                       # text:hello.py
bpy.data.texts.remove(t)
```

#### run

**Synopsis:** `qt_shell.scripts.run(key)`  
**Returns:** result with .ok, .output, .error_line, .removed

Runs a script (unloads it first when it is loaded – a reload). What it registers is recorded for unload().

| Parameter | Type | Description |
|---|---|---|
| `key` | str | Script key. |

**Example** (✔ tested)

```python
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("hello.py")
t.write('import qt_shell.api as qs\nqs.add_menu_action("Tools", "Hello", lambda: qs.status("Hi"))\n')
r = s.run(s.key_for_text(t))
print(r.ok, s.items(s.key_for_text(t)))
s.unload(s.key_for_text(t))
bpy.data.texts.remove(t)
```

#### unload

**Synopsis:** `qt_shell.scripts.unload(key)`  
**Returns:** result (.removed = number of removed items)

Calls the script's unregister() (when it has one) and removes what it registered and is still there.

| Parameter | Type | Description |
|---|---|---|
| `key` | str | Script key. |

**Example** (✔ tested)

```python
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("overlay.py")
t.write('import qt_shell.api as qs\nqs.add_overlay("dot", lambda p, c: p.drawEllipse(9, 9, 5, 5))\n')
key = s.key_for_text(t)
s.run(key)
print(s.unload(key).removed)                    # 1
bpy.data.texts.remove(t)
```

#### unload_all

**Synopsis:** `qt_shell.scripts.unload_all()`  
**Returns:** None

Unloads every loaded script.

**Example** (✔ tested)

```python
import qt_shell.scripts as s

s.unload_all()
```

#### is_loaded

**Synopsis:** `qt_shell.scripts.is_loaded(key)`  
**Returns:** bool

True when the script ran in this session, registered something and was not unloaded.

| Parameter | Type | Description |
|---|---|---|
| `key` | str | Script key. |

**Example** (✔ tested)

```python
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("demo.py")
t.write('import qt_shell.api as qs\nqs.on("frame", lambda f: None)\n')
key = s.key_for_text(t)
s.run(key)
print(s.is_loaded(key))                         # True
s.unload(key)
bpy.data.texts.remove(t)
```

#### info

**Synopsis:** `qt_shell.scripts.info(key)`  
**Returns:** dict or None

{"status": "loaded" | "ran" | "error", "items", "error_line", "time", "has_unregister"}; None for a script that has not run.

| Parameter | Type | Description |
|---|---|---|
| `key` | str | Script key. |

**Example** (✔ tested)

```python
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("calc.py")
t.write("x = 6 * 7\n")
key = s.key_for_text(t)
s.run(key)
print(s.info(key)["status"])                    # ran
bpy.data.texts.remove(t)
```

#### items

**Synopsis:** `qt_shell.scripts.items(key)`  
**Returns:** list of str

Human-readable list of what a script registered.

| Parameter | Type | Description |
|---|---|---|
| `key` | str | Script key. |

**Example** (✔ tested)

```python
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("menu.py")
t.write('import qt_shell.api as qs\nqs.add_menu_action("Tools", "Ping", lambda: None)\n')
key = s.key_for_text(t)
s.run(key)
print(s.items(key))
s.unload(key)
bpy.data.texts.remove(t)
```

#### all_keys

**Synopsis:** `qt_shell.scripts.all_keys()`  
**Returns:** list of str

Keys of all known scripts: texts of the .blend, files in the script list and scripts that ran.

**Example** (✔ tested)

```python
import qt_shell.scripts as s

for key in s.all_keys():
    info = s.info(key)
    if info:
        print(f'{info["status"]:8} {s.location(key)}')
```

#### location

**Synopsis:** `qt_shell.scripts.location(key)`  
**Returns:** str

Where a script lives: its file path, or "in the .blend" for a text without a file.

| Parameter | Type | Description |
|---|---|---|
| `key` | str | Script key. |

**Example** (✔ tested)

```python
import bpy
import qt_shell.scripts as s

t = bpy.data.texts.new("where.py")
print(s.location(s.key_for_text(t)))            # in the .blend
bpy.data.texts.remove(t)
```

#### add_file

**Synopsis:** `qt_shell.scripts.add_file(path)`  
**Returns:** str – the script key

Adds a .py file to the script list (config/qt_shell/scripts.json). A file already in the list is not added twice, so add_file() also just turns a path into its key.

| Parameter | Type | Description |
|---|---|---|
| `path` | str | A .py file. |

**Example** (✔ tested)

```python
import os, tempfile
import qt_shell.scripts as s

path = os.path.join(tempfile.gettempdir(), "qt_start.py")
open(path, "w").write('print("Qt Shell started")\n')
key = s.add_file(path)
s.remove_file(key)
```

#### remove_file

**Synopsis:** `qt_shell.scripts.remove_file(key)`  
**Returns:** None

Removes a file from the script list (the file itself is kept) and unloads it.

| Parameter | Type | Description |
|---|---|---|
| `key` | str | Script key. |

**Example** (✔ tested)

```python
import os, tempfile
import qt_shell.scripts as s

path = os.path.join(tempfile.gettempdir(), "old_tool.py")
open(path, "w").write("")
s.remove_file(s.add_file(path))
```

#### set_autoload

**Synopsis:** `qt_shell.scripts.set_autoload(key, on)`  
**Returns:** None

Turns auto-load on / off: a file in the script list runs on every start of Qt Shell (once per session); a text gets the property qtshell_autoload and runs when its .blend is opened (needs Auto Run Python Scripts).

| Parameter | Type | Description |
|---|---|---|
| `key` | str | Script key. |
| `on` | bool | Auto-load on / off. |

**Example** (✔ tested)

```python
import os, tempfile
import qt_shell.scripts as s

path = os.path.join(tempfile.gettempdir(), "qt_start.py")
open(path, "w").write('import qt_shell.api as qs\nqs.status("Welcome")\n')
key = s.add_file(path)
s.set_autoload(key, True)
print(s.autoload(key))                          # True
s.set_autoload(key, False)
s.remove_file(key)
```

#### autoload

**Synopsis:** `qt_shell.scripts.autoload(key)`  
**Returns:** bool

True when auto-load is on for the script.

| Parameter | Type | Description |
|---|---|---|
| `key` | str | Script key. |

**Example** (✔ tested)

```python
import qt_shell.scripts as s

for key, on in s.managed_files():
    print(key, s.autoload(key))
```

#### managed_files

**Synopsis:** `qt_shell.scripts.managed_files()`  
**Returns:** list of (key, autoload)

The .py files in the script list (config/qt_shell/scripts.json).

**Example** (✔ tested)

```python
import qt_shell.scripts as s

print(s.managed_files())
```

### 15 Shelf files (qt_shell.shelf)

| Command | Description |
|---|---|
| [`export_shelves`](#export_shelves) | Writes shelves to a .json file (the save button next to the shelf's +). |
| [`import_shelves`](#import_shelves) | Adds the shelves of a saved file as new tabs (a name that exists gets " (2)" …). |
| [`shelf_folder`](#shelf_folder) | The default folder for shelf files: config/qt_shell/shelves (created when missing). |

#### export_shelves

**Synopsis:** `qt_shell.shelf.export_shelves(path, names=None, data=None)`  
**Returns:** int – shelves saved

Writes shelves to a .json file (the save button next to the shelf's +).

| Parameter | Type | Description |
|---|---|---|
| `path` | str | The .json file. |
| `names` | list of str | Shelf names; None = all. |
| `data` | dict | Shelf data to write instead of the user's shelves (internal use). |

**Example** (✔ tested)

```python
import os, tempfile
from qt_shell import shelf

path = os.path.join(tempfile.gettempdir(), "modeling.json")
print(shelf.export_shelves(path, ["Modeling"]))     # 1
```

#### import_shelves

**Synopsis:** `qt_shell.shelf.import_shelves(path, data=None)`  
**Returns:** list of str – the added names

Adds the shelves of a saved file as new tabs (a name that exists gets " (2)" …).

| Parameter | Type | Description |
|---|---|---|
| `path` | str | A file written by export_shelves(). |
| `data` | dict | Shelf data to add to instead of the user's shelves (internal use). |

**Example** (not run by the test – changes the user's shelves)

```python
from qt_shell import shelf

shelf.import_shelves("C:/shelves/modeling.json")
```

#### shelf_folder

**Synopsis:** `qt_shell.shelf.shelf_folder()`  
**Returns:** str

The default folder for shelf files: config/qt_shell/shelves (created when missing).

**Example** (✔ tested)

```python
import os
from qt_shell import shelf

print(os.listdir(shelf.shelf_folder()))
```

### 15 Timeline

The methods below belong to the object you get with `tl = qt_shell.api.timeline()`.

| Command | Description |
|---|---|
| [`timeline`](#timeline) | The Timeline of the Qt Shell window (None when Qt Shell is not open). |
| [`Timeline.set_view_range`](#timelineset_view_range) | Shows frames first … last in the time bar (zoom / pan). |
| [`Timeline.view_range`](#timelineview_range) | The first and last visible frame of the time bar. |
| [`Timeline.zoom`](#timelinezoom) | Zooms the time bar around its middle: factor < 1 zooms in, > 1 out. |
| [`Timeline.frame_all`](#timelineframe_all) | Shows the whole scene range (or the preview range when it is on). |
| [`Timeline.play`](#timelineplay) | Starts playback (from the playback cache when it is filled). |
| [`Timeline.stop`](#timelinestop) | Stops playback. |
| [`Timeline.toggle_play`](#timelinetoggle_play) | Play / pause like Space; reverse=True plays backwards. |
| [`Timeline.is_playing`](#timelineis_playing) | True while the Timeline plays. |
| [`Timeline.step`](#timelinestep) | Moves the current frame by n frames (respects the preview range and the loop mode). |
| [`Timeline.set_loop_mode`](#timelineset_loop_mode) | What playback does at the end of the range. |
| [`Timeline.set_preview_range`](#timelineset_preview_range) | Preview range on / off (Blender's clock button); start / end also set it. |
| [`Timeline.set_fps`](#timelineset_fps) | The scene frame rate (Output Properties → Frame Rate): fps / base frames per second. |
| [`Timeline.set_show_seconds`](#timelineset_show_seconds) | Shows seconds instead of frames in the time bar. |
| [`Timeline.select_keys`](#timelineselect_keys) | Selects the keys of the selected objects at these frames in the time bar. |
| [`Timeline.selected_keys`](#timelineselected_keys) | Frames of the keys selected in the time bar. |
| [`Timeline.move_selected_keys`](#timelinemove_selected_keys) | Moves the selected keys by delta frames, like dragging them. |
| [`Timeline.add_marker`](#timelineadd_marker) | Adds a marker (scene.timeline_markers) at a frame. |

#### timeline

**Synopsis:** `qt_shell.api.timeline()`  
**Returns:** Timeline or None

The Timeline of the Qt Shell window (None when Qt Shell is not open).

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
print(tl.view_range())
```

#### Timeline.set_view_range

**Synopsis:** `Timeline.set_view_range(first, last)`  
**Returns:** None

Shows frames first … last in the time bar (zoom / pan).

| Parameter | Type | Description |
|---|---|---|
| `first` | float | First visible frame. |
| `last` | float | Last visible frame. |

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
tl.set_view_range(0, 120)
```

#### Timeline.view_range

**Synopsis:** `Timeline.view_range()`  
**Returns:** (first, last)

The first and last visible frame of the time bar.

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
first, last = tl.view_range()
print(first, last)
```

#### Timeline.zoom

**Synopsis:** `Timeline.zoom(factor)`  
**Returns:** None

Zooms the time bar around its middle: factor < 1 zooms in, > 1 out.

| Parameter | Type | Description |
|---|---|---|
| `factor` | float | 0.5 = twice as close. |

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
tl.zoom(0.5)
tl.zoom(2)
```

#### Timeline.frame_all

**Synopsis:** `Timeline.frame_all()`  
**Returns:** None

Shows the whole scene range (or the preview range when it is on).

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
tl.frame_all()
```

#### Timeline.play

**Synopsis:** `Timeline.play(reverse=False)`  
**Returns:** None

Starts playback (from the playback cache when it is filled).

| Parameter | Type | Description |
|---|---|---|
| `reverse` | bool | Play backwards. |

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
tl.play()
tl.stop()
```

#### Timeline.stop

**Synopsis:** `Timeline.stop()`  
**Returns:** None

Stops playback.

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
tl.play(reverse=True)
tl.stop()
```

#### Timeline.toggle_play

**Synopsis:** `Timeline.toggle_play(reverse=False)`  
**Returns:** None

Play / pause like Space; reverse=True plays backwards. The other direction while playing turns around.

| Parameter | Type | Description |
|---|---|---|
| `reverse` | bool | Backwards. |

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
tl.toggle_play()
print(tl.is_playing())     # True
tl.toggle_play()
```

#### Timeline.is_playing

**Synopsis:** `Timeline.is_playing()`  
**Returns:** bool

True while the Timeline plays.

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
if tl.is_playing():
    tl.stop()
```

#### Timeline.step

**Synopsis:** `Timeline.step(n)`  
**Returns:** None

Moves the current frame by n frames (respects the preview range and the loop mode).

| Parameter | Type | Description |
|---|---|---|
| `n` | int | Frames, negative = back. |

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
tl.step(1)
tl.step(-1)
```

#### Timeline.set_loop_mode

**Synopsis:** `Timeline.set_loop_mode(mode)`  
**Returns:** None

What playback does at the end of the range.

| Parameter | Type | Description |
|---|---|---|
| `mode` | str | "LOOP" (continuous), "ONCE" (stop at the end) or "OSCILLATE" (ping-pong, Maya). |

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
tl.set_loop_mode("OSCILLATE")
tl.set_loop_mode("LOOP")
```

#### Timeline.set_preview_range

**Synopsis:** `Timeline.set_preview_range(on, start=None, end=None)`  
**Returns:** None

Preview range on / off (Blender's clock button); start / end also set it.

| Parameter | Type | Description |
|---|---|---|
| `on` | bool | On / off. |
| `start` | int | First frame. |
| `end` | int | Last frame. |

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
tl.set_preview_range(True, 10, 50)
tl.set_preview_range(False)
```

#### Timeline.set_fps

**Synopsis:** `Timeline.set_fps(fps, base=1.0)`  
**Returns:** None

The scene frame rate (Output Properties → Frame Rate): fps / base frames per second.

| Parameter | Type | Description |
|---|---|---|
| `fps` | int | Frames per second. |
| `base` | float | Divisor – 1.001 for NTSC rates. |

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
tl.set_fps(25)
tl.set_fps(30, 1.001)      # 29.97 fps
tl.set_fps(24)
```

#### Timeline.set_show_seconds

**Synopsis:** `Timeline.set_show_seconds(on)`  
**Returns:** None

Shows seconds instead of frames in the time bar.

| Parameter | Type | Description |
|---|---|---|
| `on` | bool | Seconds on / off. |

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
tl.set_show_seconds(True)
tl.set_show_seconds(False)
```

#### Timeline.select_keys

**Synopsis:** `Timeline.select_keys(frames)`  
**Returns:** None

Selects the keys of the selected objects at these frames in the time bar.

| Parameter | Type | Description |
|---|---|---|
| `frames` | list of int | Frames with keys. |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
for f, x in ((10, 0), (20, 2)):
    ob.location.x = x
    ob.keyframe_insert("location", frame=f)
tl = qt_shell.api.timeline()
tl.select_keys([10, 20])
print(tl.selected_keys())                       # [10, 20]
```

#### Timeline.selected_keys

**Synopsis:** `Timeline.selected_keys()`  
**Returns:** list of int

Frames of the keys selected in the time bar.

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
print(tl.selected_keys())
```

#### Timeline.move_selected_keys

**Synopsis:** `Timeline.move_selected_keys(delta)`  
**Returns:** int – keys moved

Moves the selected keys by delta frames, like dragging them.

| Parameter | Type | Description |
|---|---|---|
| `delta` | int | Frames, negative = earlier. |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
ob.keyframe_insert("location", frame=10)
tl = qt_shell.api.timeline()
tl.select_keys([10])
tl.move_selected_keys(5)                         # the key is now at frame 15
```

#### Timeline.add_marker

**Synopsis:** `Timeline.add_marker(name=None, frame=None)`  
**Returns:** TimelineMarker

Adds a marker (scene.timeline_markers) at a frame.

| Parameter | Type | Description |
|---|---|---|
| `name` | str | Marker name; default F_<frame>. |
| `frame` | int | Default: the current frame. |

**Example** (✔ tested)

```python
import qt_shell

tl = qt_shell.api.timeline()
m = tl.add_marker("Contact", 24)
print(m.name, m.frame)
```

### 15 Outliner

The methods below belong to the object you get with `ol = qt_shell.api.outliner()`.

| Command | Description |
|---|---|
| [`outliner`](#outliner) | The Outliner of the Qt Shell window. |
| [`Outliner.set_mode`](#outlinerset_mode) | What the Outliner lists. |
| [`Outliner.search`](#outlinersearch) | Filters the rows by name; wildcards * and ?; "" clears the search. |
| [`Outliner.set_option`](#outlinerset_option) | A filter / display option. |
| [`Outliner.show_column`](#outlinershow_column) | Shows / hides a restriction column. |
| [`Outliner.show_selected`](#outlinershow_selected) | Opens the rows down to every selected object / bone and centres the active one (Maya: Reveal Selected). |
| [`Outliner.show_hierarchy`](#outlinershow_hierarchy) | Opens all collections and objects with children, closes the rest. |
| [`Outliner.one_level`](#outlinerone_level) | Numpad + / −: opens the shallowest closed level, or closes the deepest open level. |
| [`Outliner.expand_toggle`](#outlinerexpand_toggle) | Shift+A: expands all collections and objects, or collapses when something is open. |
| [`Outliner.new_collection`](#outlinernew_collection) | A new collection in the active collection; the selected objects are moved into it. |
| [`Outliner.move_to`](#outlinermove_to) | Moves (or links) the selected objects / collections into a collection. |
| [`Outliner.parent_to_active`](#outlinerparent_to_active) | Parents the selected objects to the active one (or to target), keeping their world transform. |
| [`Outliner.clear_parent`](#outlinerclear_parent) | Clears the parent of the selected objects, keeping their world transform. |
| [`Outliner.hide_selected`](#outlinerhide_selected) | Hides the selected objects / collections in the viewport (H). |
| [`Outliner.unhide_all`](#outlinerunhide_all) | Shows everything that is hidden (Alt+H). |
| [`Outliner.isolate`](#outlinerisolate) | Like Ctrl+click in a restriction column: only this item stays visible (click again to restore). |
| [`Outliner.collection_visibility`](#outlinercollection_visibility) | Hides / shows a collection in this view layer (inside=True: also everything in it). |
| [`Outliner.duplicate_collection`](#outlinerduplicate_collection) | Duplicates a collection with its objects (references between them remapped, like Blender). |
| [`Outliner.instance_collection`](#outlinerinstance_collection) | Adds an instance of the collection (an Empty) at the 3D cursor. |
| [`Outliner.delete`](#outlinerdelete) | Deletes the selected objects / collections; hierarchy=True also their children. |

#### outliner

**Synopsis:** `qt_shell.api.outliner()`  
**Returns:** Outliner or None

The Outliner of the Qt Shell window. Commands that act on a selection use the Outliner's selected rows (or the selected objects).

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
ol.search("Cube")
```

#### Outliner.set_mode

**Synopsis:** `Outliner.set_mode(mode)`  
**Returns:** None

What the Outliner lists.

| Parameter | Type | Description |
|---|---|---|
| `mode` | str | "VIEW_LAYER", "BLENDER_FILE" or "ORPHAN" (unused data). |

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
ol.set_mode("BLENDER_FILE")
ol.set_mode("VIEW_LAYER")
```

#### Outliner.search

**Synopsis:** `Outliner.search(text="")`  
**Returns:** None

Filters the rows by name; wildcards * and ?; "" clears the search.

| Parameter | Type | Description |
|---|---|---|
| `text` | str | Search text. |

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
ol.search("*foot*")
ol.search("")
```

#### Outliner.set_option

**Synopsis:** `Outliner.set_option(key, value)`  
**Returns:** None

A filter / display option. Keys: qt_shell.outliner.DEFAULTS (sort_alpha, sync, exact, case, collections, objects, children, state, invert, the object types …).

| Parameter | Type | Description |
|---|---|---|
| `key` | str | Option. |
| `value` |  | Its value. |

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
ol.set_option("sort_alpha", False)
ol.set_option("sort_alpha", True)
```

#### Outliner.show_column

**Synopsis:** `Outliner.show_column(cid, on=True)`  
**Returns:** None

Shows / hides a restriction column.

| Parameter | Type | Description |
|---|---|---|
| `cid` | str | exclude, select, hide, viewport, render, holdout or indirect. |
| `on` | bool | Shown. |

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
ol.show_column("select", True)
ol.show_column("select", False)
```

#### Outliner.show_selected

**Synopsis:** `Outliner.show_selected()`  
**Returns:** None

Opens the rows down to every selected object / bone and centres the active one (Maya: Reveal Selected).

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
bpy.ops.mesh.primitive_cube_add()
ol.show_selected()
```

#### Outliner.show_hierarchy

**Synopsis:** `Outliner.show_hierarchy()`  
**Returns:** None

Opens all collections and objects with children, closes the rest.

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
ol.show_hierarchy()
```

#### Outliner.one_level

**Synopsis:** `Outliner.one_level(open_)`  
**Returns:** None

Numpad + / −: opens the shallowest closed level, or closes the deepest open level.

| Parameter | Type | Description |
|---|---|---|
| `open_` | bool | True opens, False closes. |

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
ol.one_level(True)
ol.one_level(False)
```

#### Outliner.expand_toggle

**Synopsis:** `Outliner.expand_toggle()`  
**Returns:** None

Shift+A: expands all collections and objects, or collapses when something is open.

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
ol.expand_toggle()
```

#### Outliner.new_collection

**Synopsis:** `Outliner.new_collection()`  
**Returns:** None

A new collection in the active collection; the selected objects are moved into it.

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
bpy.ops.mesh.primitive_cube_add()
ol.new_collection()
```

#### Outliner.move_to

**Synopsis:** `Outliner.move_to(target, link=False, objs=None, colls=None)`  
**Returns:** None

Moves (or links) the selected objects / collections into a collection.

| Parameter | Type | Description |
|---|---|---|
| `target` | bpy.types.Collection | The collection. |
| `link` | bool | Link instead of move. |
| `objs` | list | Objects instead of the selection. |
| `colls` | list | Collections instead of the selection. |

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
props = bpy.data.collections.new("Props")
bpy.context.scene.collection.children.link(props)
bpy.ops.mesh.primitive_cone_add()
ol.move_to(props, objs=[bpy.context.object])
```

#### Outliner.parent_to_active

**Synopsis:** `Outliner.parent_to_active(target=None, objs=None)`  
**Returns:** None

Parents the selected objects to the active one (or to target), keeping their world transform.

| Parameter | Type | Description |
|---|---|---|
| `target` | Object | The parent; default the active object. |
| `objs` | list | Children instead of the selection. |

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
parent = bpy.context.object
bpy.ops.mesh.primitive_uv_sphere_add(location=(0, 0, 3))
ol.parent_to_active(target=parent, objs=[bpy.context.object])
```

#### Outliner.clear_parent

**Synopsis:** `Outliner.clear_parent(objs=None)`  
**Returns:** None

Clears the parent of the selected objects, keeping their world transform.

| Parameter | Type | Description |
|---|---|---|
| `objs` | list | Objects instead of the selection. |

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
bpy.ops.mesh.primitive_cube_add()
ol.clear_parent([bpy.context.object])
```

#### Outliner.hide_selected

**Synopsis:** `Outliner.hide_selected()`  
**Returns:** None

Hides the selected objects / collections in the viewport (H).

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
bpy.ops.mesh.primitive_cube_add()
ol.hide_selected()
ol.unhide_all()
```

#### Outliner.unhide_all

**Synopsis:** `Outliner.unhide_all()`  
**Returns:** None

Shows everything that is hidden (Alt+H).

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
ol.unhide_all()
```

#### Outliner.isolate

**Synopsis:** `Outliner.isolate(key, cid="hide")`  
**Returns:** None

Like Ctrl+click in a restriction column: only this item stays visible (click again to restore).

| Parameter | Type | Description |
|---|---|---|
| `key` | (type, name) | e.g. ("OBJECT", "Cube") or ("COLLECTION", "Props"). |
| `cid` | str | The column: hide, viewport, render, select … |

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
bpy.ops.mesh.primitive_cube_add()
name = bpy.context.object.name
ol.isolate(("OBJECT", name))
ol.isolate(("OBJECT", name))                     # everything visible again
```

#### Outliner.collection_visibility

**Synopsis:** `Outliner.collection_visibility(c, hide, inside=False)`  
**Returns:** None

Hides / shows a collection in this view layer (inside=True: also everything in it).

| Parameter | Type | Description |
|---|---|---|
| `c` | Collection | The collection. |
| `hide` | bool | Hide (True) or show. |
| `inside` | bool | Also its contents. |

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
props = bpy.data.collections.get("Props") or bpy.data.collections.new("Props")
if props.name not in bpy.context.scene.collection.children:
    bpy.context.scene.collection.children.link(props)
ol.collection_visibility(props, hide=True, inside=True)
ol.collection_visibility(props, hide=False, inside=True)
```

#### Outliner.duplicate_collection

**Synopsis:** `Outliner.duplicate_collection(c)`  
**Returns:** None

Duplicates a collection with its objects (references between them remapped, like Blender).

| Parameter | Type | Description |
|---|---|---|
| `c` | Collection | The collection. |

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
props = bpy.data.collections.new("Set")
bpy.context.scene.collection.children.link(props)
ol.duplicate_collection(props)
```

#### Outliner.instance_collection

**Synopsis:** `Outliner.instance_collection(c)`  
**Returns:** None

Adds an instance of the collection (an Empty) at the 3D cursor.

| Parameter | Type | Description |
|---|---|---|
| `c` | Collection | The collection. |

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
tree = bpy.data.collections.new("Tree")
bpy.context.scene.collection.children.link(tree)
ol.instance_collection(tree)
```

#### Outliner.delete

**Synopsis:** `Outliner.delete(hierarchy=False)`  
**Returns:** None

Deletes the selected objects / collections; hierarchy=True also their children.

| Parameter | Type | Description |
|---|---|---|
| `hierarchy` | bool | Delete children too. |

**Example** (✔ tested)

```python
import bpy, qt_shell

ol = qt_shell.api.outliner()
bpy.ops.mesh.primitive_cube_add()
ol.delete(hierarchy=False)
```

### 15 Graph editor

The methods below belong to the object you get with `ge = qt_shell.api.graph_editor()`.

| Command | Description |
|---|---|
| [`graph_editor`](#graph_editor) | The Graph editor of the Qt Shell window. |
| [`GraphEditor.set_tangents`](#grapheditorset_tangents) | Key tangents (interpolation / handles). |
| [`GraphEditor.set_handle_type`](#grapheditorset_handle_type) | Handle type of the keys: break or unify the tangents. |
| [`GraphEditor.set_infinity`](#grapheditorset_infinity) | What the curves do before the first and after the last key. |
| [`GraphEditor.insert_keys`](#grapheditorinsert_keys) | Keys the shown curves at the current frame (the selected objects when no curve is shown). |
| [`GraphEditor.delete_keys`](#grapheditordelete_keys) | Deletes the selected keys. |
| [`GraphEditor.set_snap`](#grapheditorset_snap) | Snaps key times to whole frames while moving keys (the ⌗ Snap button). |
| [`GraphEditor.frame_all`](#grapheditorframe_all) | Fits all shown curves into the view. |
| [`GraphEditor.frame_selected`](#grapheditorframe_selected) | Fits the selected keys into the view. |

#### graph_editor

**Synopsis:** `qt_shell.api.graph_editor()`  
**Returns:** GraphEditor or None

The Graph editor of the Qt Shell window. Tangents and infinity apply to the selected keys, or to all shown curves when no key is selected.

**Example** (✔ tested)

```python
import qt_shell

ge = qt_shell.api.graph_editor()
ge.frame_all()
```

#### GraphEditor.set_tangents

**Synopsis:** `GraphEditor.set_tangents(kind)`  
**Returns:** None

Key tangents (interpolation / handles).

| Parameter | Type | Description |
|---|---|---|
| `kind` | str | "AUTO", "AUTO_CLAMPED" (Spline), "LINEAR", "FLAT" or "CONSTANT" (Stepped). |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
for f, z in ((1, 0), (12, 3), (24, 0)):
    ob.location.z = z
    ob.keyframe_insert("location", index=2, frame=f)
ge = qt_shell.api.graph_editor()
ge.set_tangents("LINEAR")
```

#### GraphEditor.set_handle_type

**Synopsis:** `GraphEditor.set_handle_type(kind)`  
**Returns:** None

Handle type of the keys: break or unify the tangents.

| Parameter | Type | Description |
|---|---|---|
| `kind` | str | "FREE" (Break Tangents), "ALIGNED" (Unify), "VECTOR", "AUTO", "AUTO_CLAMPED". |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
for f, z in ((1, 0), (12, 3), (24, 0)):
    ob.location.z = z
    ob.keyframe_insert("location", index=2, frame=f)
ge = qt_shell.api.graph_editor()
ge.set_handle_type("FREE")
```

#### GraphEditor.set_infinity

**Synopsis:** `GraphEditor.set_infinity(mode)`  
**Returns:** None

What the curves do before the first and after the last key.

| Parameter | Type | Description |
|---|---|---|
| `mode` | str | "CONSTANT", "LINEAR", "REPEAT" (Cycle), "REPEAT_OFFSET" (Cycle with Offset) or "MIRROR" (Oscillate). |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
for f, z in ((1, 0), (12, 3), (24, 0)):
    ob.location.z = z
    ob.keyframe_insert("location", index=2, frame=f)
ge = qt_shell.api.graph_editor()
ge.set_infinity("REPEAT")
```

#### GraphEditor.insert_keys

**Synopsis:** `GraphEditor.insert_keys()`  
**Returns:** None

Keys the shown curves at the current frame (the selected objects when no curve is shown).

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
for f, z in ((1, 0), (12, 3), (24, 0)):
    ob.location.z = z
    ob.keyframe_insert("location", index=2, frame=f)
ge = qt_shell.api.graph_editor()
bpy.context.scene.frame_set(6)
ge.insert_keys()
```

#### GraphEditor.delete_keys

**Synopsis:** `GraphEditor.delete_keys()`  
**Returns:** None

Deletes the selected keys.

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
for f, z in ((1, 0), (12, 3), (24, 0)):
    ob.location.z = z
    ob.keyframe_insert("location", index=2, frame=f)
ge = qt_shell.api.graph_editor()
ge.delete_keys()
```

#### GraphEditor.set_snap

**Synopsis:** `GraphEditor.set_snap(on=True)`  
**Returns:** None

Snaps key times to whole frames while moving keys (the ⌗ Snap button).

| Parameter | Type | Description |
|---|---|---|
| `on` | bool | Snap on / off. |

**Example** (✔ tested)

```python
import qt_shell

ge = qt_shell.api.graph_editor()
ge.set_snap(True)
```

#### GraphEditor.frame_all

**Synopsis:** `GraphEditor.frame_all()`  
**Returns:** None

Fits all shown curves into the view.

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
for f, z in ((1, 0), (12, 3), (24, 0)):
    ob.location.z = z
    ob.keyframe_insert("location", index=2, frame=f)
ge = qt_shell.api.graph_editor()
ge.frame_all()
```

#### GraphEditor.frame_selected

**Synopsis:** `GraphEditor.frame_selected()`  
**Returns:** None

Fits the selected keys into the view.

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
for f, z in ((1, 0), (12, 3), (24, 0)):
    ob.location.z = z
    ob.keyframe_insert("location", index=2, frame=f)
ge = qt_shell.api.graph_editor()
ge.frame_selected()
```

### 15 UV editor

The methods below belong to the object you get with `uv = qt_shell.api.uv_editor()  (UVCanvas: uv.canvas)`.

| Command | Description |
|---|---|
| [`uv_editor`](#uv_editor) | The UV editor of the Qt Shell window; it works on the active mesh in Edit Mode. |
| [`UVEditor.set_mode`](#uveditorset_mode) | Component mode of the UV editor. |
| [`UVEditor.tool`](#uveditortool) | Runs any bpy.ops.uv operator on the current UV selection, in a UV editor context. |
| [`UVEditor.mesh_tool`](#uveditormesh_tool) | A projection (3D view operator) on the selected faces – all faces when none is selected. |
| [`UVEditor.unwrap`](#uveditorunwrap) | Unwraps the selected faces (all when none is selected). |
| [`UVEditor.layout_shells`](#uveditorlayout_shells) | Packs the shells into the 0–1 square (Maya: Layout). |
| [`UVEditor.move_by`](#uveditormove_by) | Moves the selected UVs. |
| [`UVEditor.rotate_by`](#uveditorrotate_by) | Rotates the selected UVs around their centre. |
| [`UVEditor.flip`](#uveditorflip) | Flips the selected UVs. |
| [`UVEditor.align`](#uveditoralign) | Aligns the selected UVs. |
| [`UVEditor.normalize`](#uveditornormalize) | Scales the selected UVs into the 0–1 square, keeping the proportions. |
| [`UVEditor.texel_get`](#uveditortexel_get) | Measures the texel density of the selected faces (px per metre) into the Texel Density field and the status bar. |
| [`UVEditor.set_texel_density`](#uveditorset_texel_density) | Scales every selected shell to value pixels per metre. |
| [`UVEditor.set_display`](#uveditorset_display) | Display options of the UV editor; checker is also drawn on the mesh in the 3D view. |
| [`UVEditor.set_image`](#uveditorset_image) | The image shown behind the UVs; None = the active material's texture. |
| [`UVCanvas.select_all`](#uvcanvasselect_all) | Selects / deselects all UVs (uv.canvas). |
| [`UVCanvas.frame_selected`](#uvcanvasframe_selected) | Fits the selected UVs into the view (uv.canvas). |

#### uv_editor

**Synopsis:** `qt_shell.api.uv_editor()`  
**Returns:** UVEditor or None

The UV editor of the Qt Shell window; it works on the active mesh in Edit Mode. Every button shows its Python line in the tooltip.

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.set_mode("FACE")
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVEditor.set_mode

**Synopsis:** `UVEditor.set_mode(mode)`  
**Returns:** None

Component mode of the UV editor.

| Parameter | Type | Description |
|---|---|---|
| `mode` | str | "VERT", "EDGE", "FACE" or "ISLAND" (shell). |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.set_mode("ISLAND")
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVEditor.tool

**Synopsis:** `UVEditor.tool(idname, props=None)`  
**Returns:** None

Runs any bpy.ops.uv operator on the current UV selection, in a UV editor context.

| Parameter | Type | Description |
|---|---|---|
| `idname` | str | e.g. "uv.pack_islands". |
| `props` | dict | Operator properties. |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.tool("uv.pack_islands", {"margin": 0.01})
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVEditor.mesh_tool

**Synopsis:** `UVEditor.mesh_tool(idname, props=None)`  
**Returns:** None

A projection (3D view operator) on the selected faces – all faces when none is selected.

| Parameter | Type | Description |
|---|---|---|
| `idname` | str | e.g. "uv.smart_project", "uv.cube_project". |
| `props` | dict | Operator properties. |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.mesh_tool("uv.smart_project", {"island_margin": 0.02})
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVEditor.unwrap

**Synopsis:** `UVEditor.unwrap()`  
**Returns:** None

Unwraps the selected faces (all when none is selected).

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.unwrap()
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVEditor.layout_shells

**Synopsis:** `UVEditor.layout_shells()`  
**Returns:** None

Packs the shells into the 0–1 square (Maya: Layout).

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.layout_shells()
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVEditor.move_by

**Synopsis:** `UVEditor.move_by(du, dv)`  
**Returns:** None

Moves the selected UVs.

| Parameter | Type | Description |
|---|---|---|
| `du` | float | U offset. |
| `dv` | float | V offset. |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.move_by(0.1, 0)
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVEditor.rotate_by

**Synopsis:** `UVEditor.rotate_by(deg)`  
**Returns:** None

Rotates the selected UVs around their centre.

| Parameter | Type | Description |
|---|---|---|
| `deg` | float | Degrees, counter-clockwise. |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.rotate_by(90)
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVEditor.flip

**Synopsis:** `UVEditor.flip(horizontal)`  
**Returns:** None

Flips the selected UVs.

| Parameter | Type | Description |
|---|---|---|
| `horizontal` | bool | True = in U (horizontally), False = in V. |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.flip(True)
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVEditor.align

**Synopsis:** `UVEditor.align(how)`  
**Returns:** None

Aligns the selected UVs.

| Parameter | Type | Description |
|---|---|---|
| `how` | str | "UMIN", "UMID", "UMAX", "VMIN", "VMID" or "VMAX". |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.align("UMIN")
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVEditor.normalize

**Synopsis:** `UVEditor.normalize()`  
**Returns:** None

Scales the selected UVs into the 0–1 square, keeping the proportions.

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.normalize()
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVEditor.texel_get

**Synopsis:** `UVEditor.texel_get()`  
**Returns:** None

Measures the texel density of the selected faces (px per metre) into the Texel Density field and the status bar.

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.texel_get()
print(uv.td.value())
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVEditor.set_texel_density

**Synopsis:** `UVEditor.set_texel_density(value)`  
**Returns:** None

Scales every selected shell to value pixels per metre.

| Parameter | Type | Description |
|---|---|---|
| `value` | float | px / m (of the texture size set in the UV editor). |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.set_texel_density(512)
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVEditor.set_display

**Synopsis:** `UVEditor.set_display(key, on=True)`  
**Returns:** None

Display options of the UV editor; checker is also drawn on the mesh in the 3D view.

| Parameter | Type | Description |
|---|---|---|
| `key` | str | image, dim, checker, shaded, distortion, borders or grid. |
| `on` | bool | On / off. |

**Example** (✔ tested)

```python
import qt_shell

uv = qt_shell.api.uv_editor()
uv.set_display("checker", True)
uv.set_display("checker", False)
```

#### UVEditor.set_image

**Synopsis:** `UVEditor.set_image(name=None)`  
**Returns:** None

The image shown behind the UVs; None = the active material's texture.

| Parameter | Type | Description |
|---|---|---|
| `name` | str | Image name in bpy.data.images. |

**Example** (✔ tested)

```python
import bpy, qt_shell

img = bpy.data.images.new("Grid", 1024, 1024)
img.generated_type = "UV_GRID"
uv = qt_shell.api.uv_editor()
uv.set_image("Grid")
```

#### UVCanvas.select_all

**Synopsis:** `UVCanvas.select_all(action="SELECT")`  
**Returns:** None

Selects / deselects all UVs (uv.canvas).

| Parameter | Type | Description |
|---|---|---|
| `action` | str | "SELECT", "DESELECT", "INVERT" or "TOGGLE". |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.canvas.select_all("SELECT")
bpy.ops.object.mode_set(mode="OBJECT")
```

#### UVCanvas.frame_selected

**Synopsis:** `UVCanvas.frame_selected()`  
**Returns:** None

Fits the selected UVs into the view (uv.canvas).

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.mesh.primitive_cube_add()
bpy.ops.object.mode_set(mode="EDIT")            # the UV editor works on the mesh in Edit Mode
uv = qt_shell.api.uv_editor()
uv.canvas.select_all("SELECT")
uv.canvas.frame_selected()
bpy.ops.object.mode_set(mode="OBJECT")
```

### 15 Render View

The methods below belong to the object you get with `rv = qt_shell.api.render_view()`.

| Command | Description |
|---|---|
| [`render_view`](#render_view) | Qt Shell's render window (Blender's Image Editor with the Render Result). |
| [`RenderView.present`](#renderviewpresent) | Shows the Render View (F11). |
| [`RenderView.set_slot`](#renderviewset_slot) | Shows a render slot; the next render goes there (J / Alt+J cycle the slots). |
| [`RenderView.set_channel`](#renderviewset_channel) | Which channels are shown. |
| [`RenderView.passes`](#renderviewpasses) | The view layers and passes of the shown result (enabled in View Layer Properties → Passes). |
| [`RenderView.set_pass`](#renderviewset_pass) | Shows a render pass of the current view layer. |
| [`RenderView.set_layer`](#renderviewset_layer) | Shows a view layer of the result. |
| [`RenderView.zoom`](#renderviewzoom) | Zoom like View → Fractional Zoom. |
| [`RenderView.fit`](#renderviewfit) | Frame All (Home): the whole image in the view. |
| [`RenderView.save_as`](#renderviewsave_as) | Saves the render of the active slot; the format follows the extension (.png .jpg .exr .tif .webp .bmp). |
| [`RenderView.copy_to_clipboard`](#renderviewcopy_to_clipboard) | Copies the picture as shown to the clipboard. |
| [`RenderView.set_tool`](#renderviewset_tool) | Toolbar tool of the Render View (T). |
| [`RenderView.picture`](#renderviewpicture) | The picture as shown: the render plus Blue Pencil and the annotations of the active slot. |
| [`RenderView.has_drawings`](#renderviewhas_drawings) | True when Save writes the picture with drawings (burnt-in or Render View annotations). |
| [`RenderView.add_annotation`](#renderviewadd_annotation) | Adds an annotation stroke to the active slot (kept per slot for the session). |
| [`RenderView.annotations`](#renderviewannotations) | Annotation strokes of a render slot: [{"pts": [(x, y), …], "color": "#rrggbb", "width": px}, …]. |
| [`RenderView.undo_annotation`](#renderviewundo_annotation) | Removes the last annotation stroke of the active slot. |
| [`RenderView.clear_annotations`](#renderviewclear_annotations) | Removes all annotations of the active slot. |
| [`RenderView.set_annotation_style`](#renderviewset_annotation_style) | Colour and thickness of new annotation strokes. |
| [`RenderView.set_overlays`](#renderviewset_overlays) | Overlays: annotations and the render info text on the image. |
| [`RenderView.set_gizmos`](#renderviewset_gizmos) | The navigation gizmo (zoom / pan buttons) at the top right of the image. |
| [`RenderView.set_toolbar`](#renderviewset_toolbar) | The toolbar at the left (T). |

#### render_view

**Synopsis:** `qt_shell.api.render_view()`  
**Returns:** RenderView or None

Qt Shell's render window (Blender's Image Editor with the Render Result).

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.render.render()                          # a render to look at (F12 renders in the background)
rv = qt_shell.api.render_view()
rv.present()
```

#### RenderView.present

**Synopsis:** `RenderView.present()`  
**Returns:** None

Shows the Render View (F11).

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.present()
```

#### RenderView.set_slot

**Synopsis:** `RenderView.set_slot(index)`  
**Returns:** None

Shows a render slot; the next render goes there (J / Alt+J cycle the slots).

| Parameter | Type | Description |
|---|---|---|
| `index` | int | 0 = Slot 1. |

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.set_slot(1)          # Slot 2
rv.set_slot(0)
```

#### RenderView.set_channel

**Synopsis:** `RenderView.set_channel(channel)`  
**Returns:** None

Which channels are shown.

| Parameter | Type | Description |
|---|---|---|
| `channel` | str | "COLOR_ALPHA", "COLOR", "ALPHA", "RED", "GREEN" or "BLUE". |

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.set_channel("ALPHA")
rv.set_channel("COLOR_ALPHA")
```

#### RenderView.passes

**Synopsis:** `RenderView.passes()`  
**Returns:** dict {view layer: [passes]}

The view layers and passes of the shown result (enabled in View Layer Properties → Passes).

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.render.render()                          # a render to look at (F12 renders in the background)
rv = qt_shell.api.render_view()
print(rv.passes())        # {"ViewLayer": ["Combined", "Depth", …]}
```

#### RenderView.set_pass

**Synopsis:** `RenderView.set_pass(pas)`  
**Returns:** None

Shows a render pass of the current view layer.

| Parameter | Type | Description |
|---|---|---|
| `pas` | str | Pass name, e.g. "Depth". |

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.set_pass("Combined")
```

#### RenderView.set_layer

**Synopsis:** `RenderView.set_layer(layer)`  
**Returns:** None

Shows a view layer of the result.

| Parameter | Type | Description |
|---|---|---|
| `layer` | str | View layer name. |

**Example** (✔ tested)

```python
import bpy, qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.set_layer(bpy.context.view_layer.name)
```

#### RenderView.zoom

**Synopsis:** `RenderView.zoom(ratio)`  
**Returns:** None

Zoom like View → Fractional Zoom.

| Parameter | Type | Description |
|---|---|---|
| `ratio` | float | 1 = 1:1, 2 = 2:1, 0.5 = 1:2 … |

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.zoom(1)
```

#### RenderView.fit

**Synopsis:** `RenderView.fit()`  
**Returns:** None

Frame All (Home): the whole image in the view.

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.fit()
```

#### RenderView.save_as

**Synopsis:** `RenderView.save_as(path=None, copy=False)`  
**Returns:** bool

Saves the render of the active slot; the format follows the extension (.png .jpg .exr .tif .webp .bmp). A picture with drawings is saved as shown. Without a path a file dialog asks.

| Parameter | Type | Description |
|---|---|---|
| `path` | str | The file. |
| `copy` | bool | Save a copy (keep the image's own path). |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.render.render()                          # a render to look at (F12 renders in the background)
rv = qt_shell.api.render_view()
rv.save_as("C:/out/frame.png")
```

#### RenderView.copy_to_clipboard

**Synopsis:** `RenderView.copy_to_clipboard()`  
**Returns:** None

Copies the picture as shown to the clipboard.

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.copy_to_clipboard()
```

#### RenderView.set_tool

**Synopsis:** `RenderView.set_tool(tool, variant=None)`  
**Returns:** None

Toolbar tool of the Render View (T).

| Parameter | Type | Description |
|---|---|---|
| `tool` | str | "SAMPLE", "ANNOTATE" or "BLUE_PENCIL". |
| `variant` | str | ANNOTATE: FREEHAND, LINE, POLYGON, ERASER · BLUE_PENCIL: PENCIL, BRUSH, ERASER, TEXT, LINE, ARROW, ELLIPSE, RECT, TRANSFORM. |

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.set_tool("ANNOTATE", "LINE")
rv.set_tool("SAMPLE")
```

#### RenderView.picture

**Synopsis:** `RenderView.picture()`  
**Returns:** QImage or None

The picture as shown: the render plus Blue Pencil and the annotations of the active slot.

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.render.render()                          # a render to look at (F12 renders in the background)
rv = qt_shell.api.render_view()
img = rv.picture()
print(img.width(), img.height())
```

#### RenderView.has_drawings

**Synopsis:** `RenderView.has_drawings()`  
**Returns:** bool

True when Save writes the picture with drawings (burnt-in or Render View annotations).

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
print(rv.has_drawings())
```

#### RenderView.add_annotation

**Synopsis:** `RenderView.add_annotation(points, color=None, width=None)`  
**Returns:** None

Adds an annotation stroke to the active slot (kept per slot for the session).

| Parameter | Type | Description |
|---|---|---|
| `points` | list of (x, y) | Image pixels from the top-left corner. |
| `color` | str | "#rrggbb"; default the current style. |
| `width` | int | Thickness in px. |

**Example** (✔ tested)

```python
import bpy, qt_shell

bpy.ops.render.render()                          # a render to look at (F12 renders in the background)
rv = qt_shell.api.render_view()
rv.add_annotation([(10, 10), (200, 120)], color="#ff4040", width=4)
```

#### RenderView.annotations

**Synopsis:** `RenderView.annotations(slot=None)`  
**Returns:** list of dict

Annotation strokes of a render slot: [{"pts": [(x, y), …], "color": "#rrggbb", "width": px}, …].

| Parameter | Type | Description |
|---|---|---|
| `slot` | int | Default: the active slot. |

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
for st in rv.annotations():
    print(st["color"], len(st["pts"]))
```

#### RenderView.undo_annotation

**Synopsis:** `RenderView.undo_annotation()`  
**Returns:** bool

Removes the last annotation stroke of the active slot. False when there is none.

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.undo_annotation()
```

#### RenderView.clear_annotations

**Synopsis:** `RenderView.clear_annotations()`  
**Returns:** None

Removes all annotations of the active slot.

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.clear_annotations()
```

#### RenderView.set_annotation_style

**Synopsis:** `RenderView.set_annotation_style(color=None, width=None)`  
**Returns:** None

Colour and thickness of new annotation strokes.

| Parameter | Type | Description |
|---|---|---|
| `color` | str | "#rrggbb". |
| `width` | int | px. |

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.set_annotation_style(color="#619bc7", width=3)
```

#### RenderView.set_overlays

**Synopsis:** `RenderView.set_overlays(on)`  
**Returns:** None

Overlays: annotations and the render info text on the image.

| Parameter | Type | Description |
|---|---|---|
| `on` | bool | Shown. |

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.set_overlays(False)
rv.set_overlays(True)
```

#### RenderView.set_gizmos

**Synopsis:** `RenderView.set_gizmos(on)`  
**Returns:** None

The navigation gizmo (zoom / pan buttons) at the top right of the image.

| Parameter | Type | Description |
|---|---|---|
| `on` | bool | Shown. |

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.set_gizmos(True)
```

#### RenderView.set_toolbar

**Synopsis:** `RenderView.set_toolbar(on)`  
**Returns:** None

The toolbar at the left (T).

| Parameter | Type | Description |
|---|---|---|
| `on` | bool | Shown. |

**Example** (✔ tested)

```python
import qt_shell

rv = qt_shell.api.render_view()     # after a render (F12)
rv.set_toolbar(True)
```

### 15 Animation Player

The methods below belong to the object you get with `player = qt_shell.api.main_window().anim_player`.

| Command | Description |
|---|---|
| [`AnimPlayer.set_blue_pencil`](#animplayerset_blue_pencil) | Blue Pencil on the frame shown in the Animation Player (Render → View Animation, Ctrl+F11); strokes go to the player's own layers (space ANIM). |
| [`AnimPlayer.export_animation`](#animplayerexport_animation) | Saves the frames played. |

#### AnimPlayer.set_blue_pencil

**Synopsis:** `AnimPlayer.set_blue_pencil(on)`  
**Returns:** None

Blue Pencil on the frame shown in the Animation Player (Render → View Animation, Ctrl+F11); strokes go to the player's own layers (space ANIM).

| Parameter | Type | Description |
|---|---|---|
| `on` | bool | Drawing on / off. |

**Example** (not run by the test – needs rendered frames in the Animation Player)

```python
import qt_shell.api as qs

player = qs.main_window().anim_player          # open it with Render → View Animation first
player.set_blue_pencil(True)
```

#### AnimPlayer.export_animation

**Synopsis:** `AnimPlayer.export_animation(path=None, kind=None, start=None, end=None, blue_pencil=None)`  
**Returns:** int – frames saved

Saves the frames played. Without a path a dialog asks.

| Parameter | Type | Description |
|---|---|---|
| `path` | str | The file (MP4) or the first file of a sequence. |
| `kind` | str | "MP4", "PNG", "JPEG", "TIFF" or "COPY" (the rendered files). |
| `start` | int | First frame. |
| `end` | int | Last frame. |
| `blue_pencil` | bool | Burn in the player's Blue Pencil layers (COPY then becomes PNG). |

**Example** (not run by the test – needs rendered frames in the Animation Player)

```python
import qt_shell.api as qs

player = qs.main_window().anim_player
player.export_animation("C:/out/review.mp4", "MP4", 1, 48, blue_pencil=True)
```

### 15 Image editor

The methods below belong to the object you get with `ie = qt_shell.api.image_editor()`.

| Command | Description |
|---|---|
| [`image_editor`](#image_editor) | The Image editor: compositor result, Viewer node, Render Result, rendered animation or an image. |
| [`ImageEditor.set_source`](#imageeditorset_source) | What the Image editor shows. |
| [`ImageEditor.set_live`](#imageeditorset_live) | Live on: the picture follows every change of the compositor nodes. |
| [`ImageEditor.refresh`](#imageeditorrefresh) | The Reload button: the compositor's current result (the Viewer is re-linked to the output first). |
| [`ImageEditor.set_auto_reload`](#imageeditorset_auto_reload) | Auto: an image shown is read again when it changes (follows Texture Paint live). |
| [`ImageEditor.reload`](#imageeditorreload) | Reads the picture of the current source again. |
| [`ImageEditor.fit`](#imageeditorfit) | Frame All: the whole picture in the view. |
| [`ImageEditor.zoom`](#imageeditorzoom) | Zoom ratio, 1 = 1:1. |
| [`ImageEditor.set_channel`](#imageeditorset_channel) | Which channels are shown. |
| [`ImageEditor.export_image`](#imageeditorexport_image) | Saves the picture shown; the format follows the extension (.png .jpg .exr .tif .webp .bmp). |
| [`ImageEditor.set_frame`](#imageeditorset_frame) | Rendered animation: shows frame f (the nearest rendered one). |
| [`ImageEditor.play`](#imageeditorplay) | Plays the rendered animation. |
| [`ImageEditor.pause`](#imageeditorpause) | Pauses the rendered animation. |
| [`ImageEditor.set_cache_range`](#imageeditorset_cache_range) | From / To of the compositor cache; None, None = the scene's frame range. |
| [`ImageEditor.render_raw`](#imageeditorrender_raw) | Renders the animation once without compositing (OpenEXR, temporary folder) – the input Live composites with the current nodes. |
| [`ImageEditor.use_frames`](#imageeditoruse_frames) | The compositor works on frames rendered before (any image sequence); None = this file's own frames. |
| [`ImageEditor.export_animation`](#imageeditorexport_animation) | Exports the rendered animation. |
| [`ensure_compositor`](#ensure_compositor) | Creates the compositor nodes when the scene has none (Render Layers → Group Output) and a Viewer node fed by what goes to the output. |

#### image_editor

**Synopsis:** `qt_shell.api.image_editor()`  
**Returns:** ImageEditor or None

The Image editor: compositor result, Viewer node, Render Result, rendered animation or an image.

**Example** (✔ tested)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.set_source("RENDER")
```

#### ImageEditor.set_source

**Synopsis:** `ImageEditor.set_source(src)`  
**Returns:** None

What the Image editor shows.

| Parameter | Type | Description |
|---|---|---|
| `src` | str | "COMPOSITOR" (the result), "VIEWER" (the Viewer node), "RENDER", "ANIMATION" or an image name ("IMAGE:<name>" or just the name). |

**Example** (✔ tested)

```python
import bpy, qt_shell

img = bpy.data.images.new("Grid", 512, 512)
img.generated_type = "COLOR_GRID"
ie = qt_shell.api.image_editor()
ie.set_source("Grid")
```

#### ImageEditor.set_live

**Synopsis:** `ImageEditor.set_live(on)`  
**Returns:** None

Live on: the picture follows every change of the compositor nodes. Off: it stays as it is (compare before / after) until Reload or a new render.

| Parameter | Type | Description |
|---|---|---|
| `on` | bool | Live on / off. |

**Example** (✔ tested)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.set_live(False)
ie.set_live(True)
```

#### ImageEditor.refresh

**Synopsis:** `ImageEditor.refresh()`  
**Returns:** None

The Reload button: the compositor's current result (the Viewer is re-linked to the output first).

**Example** (✔ tested)

```python
import bpy, qt_shell
from qt_shell import image_editor

bpy.ops.render.render()
image_editor.ensure_compositor()
ie = qt_shell.api.image_editor()
ie.set_source("COMPOSITOR")
ie.refresh()
```

#### ImageEditor.set_auto_reload

**Synopsis:** `ImageEditor.set_auto_reload(on=True)`  
**Returns:** None

Auto: an image shown is read again when it changes (follows Texture Paint live). Default on.

| Parameter | Type | Description |
|---|---|---|
| `on` | bool | On / off. |

**Example** (✔ tested)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.set_auto_reload(True)
```

#### ImageEditor.reload

**Synopsis:** `ImageEditor.reload(keep_view=True)`  
**Returns:** None

Reads the picture of the current source again.

| Parameter | Type | Description |
|---|---|---|
| `keep_view` | bool | Keep the zoom / pan. |

**Example** (✔ tested)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.reload()
```

#### ImageEditor.fit

**Synopsis:** `ImageEditor.fit()`  
**Returns:** None

Frame All: the whole picture in the view.

**Example** (✔ tested)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.fit()
```

#### ImageEditor.zoom

**Synopsis:** `ImageEditor.zoom(ratio)`  
**Returns:** None

Zoom ratio, 1 = 1:1.

| Parameter | Type | Description |
|---|---|---|
| `ratio` | float | Zoom. |

**Example** (✔ tested)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.zoom(1)
ie.zoom(0.5)
```

#### ImageEditor.set_channel

**Synopsis:** `ImageEditor.set_channel(ch)`  
**Returns:** None

Which channels are shown.

| Parameter | Type | Description |
|---|---|---|
| `ch` | str | "COLOR_ALPHA", "COLOR", "ALPHA", "RED", "GREEN" or "BLUE". |

**Example** (✔ tested)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.set_channel("ALPHA")
ie.set_channel("COLOR_ALPHA")
```

#### ImageEditor.export_image

**Synopsis:** `ImageEditor.export_image(path=None)`  
**Returns:** bool

Saves the picture shown; the format follows the extension (.png .jpg .exr .tif .webp .bmp). Without a path a file dialog asks.

| Parameter | Type | Description |
|---|---|---|
| `path` | str | The file. |

**Example** (✔ tested)

```python
import bpy, qt_shell

img = bpy.data.images.new("Grid", 256, 256)
img.generated_type = "UV_GRID"
ie = qt_shell.api.image_editor()
ie.set_source("Grid")
ie.export_image("C:/out/grid.png")
```

#### ImageEditor.set_frame

**Synopsis:** `ImageEditor.set_frame(f, from_ui=False, keep_view=True)`  
**Returns:** bool

Rendered animation: shows frame f (the nearest rendered one).

| Parameter | Type | Description |
|---|---|---|
| `f` | int | Frame. |
| `from_ui` | bool | Internal. |
| `keep_view` | bool | Keep the zoom / pan. |

**Example** (not run by the test – needs a rendered animation)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.set_source("ANIMATION")
ie.set_frame(12)
```

#### ImageEditor.play

**Synopsis:** `ImageEditor.play()`  
**Returns:** bool

Plays the rendered animation.

**Example** (not run by the test – needs a rendered animation)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.set_source("ANIMATION")
ie.play()
ie.pause()
```

#### ImageEditor.pause

**Synopsis:** `ImageEditor.pause()`  
**Returns:** None

Pauses the rendered animation.

**Example** (✔ tested)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.pause()
```

#### ImageEditor.set_cache_range

**Synopsis:** `ImageEditor.set_cache_range(start=None, end=None)`  
**Returns:** None

From / To of the compositor cache; None, None = the scene's frame range.

| Parameter | Type | Description |
|---|---|---|
| `start` | int | First frame. |
| `end` | int | Last frame. |

**Example** (✔ tested)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.set_cache_range(10, 40)
ie.set_cache_range(None, None)
```

#### ImageEditor.render_raw

**Synopsis:** `ImageEditor.render_raw()`  
**Returns:** bool

Renders the animation once without compositing (OpenEXR, temporary folder) – the input Live composites with the current nodes.

**Example** (not run by the test – renders the whole animation)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.render_raw()
```

#### ImageEditor.use_frames

**Synopsis:** `ImageEditor.use_frames(folder=None)`  
**Returns:** None

The compositor works on frames rendered before (any image sequence); None = this file's own frames.

| Parameter | Type | Description |
|---|---|---|
| `folder` | str | Folder with the frames. |

**Example** (not run by the test – needs rendered frames)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.use_frames("C:/frames")
ie.use_frames(None)
```

#### ImageEditor.export_animation

**Synopsis:** `ImageEditor.export_animation(path=None, kind=None, start=None, end=None)`  
**Returns:** bool

Exports the rendered animation. Without a path a dialog asks.

| Parameter | Type | Description |
|---|---|---|
| `path` | str | The file (MP4) or the first file of a sequence. |
| `kind` | str | "MP4", "PNG", "JPEG", "TIFF" or "COPY" (the rendered files). |
| `start` | int | First frame. |
| `end` | int | Last frame. |

**Example** (not run by the test – needs a rendered animation)

```python
import qt_shell

ie = qt_shell.api.image_editor()
ie.export_animation("C:/out/anim.mp4", "MP4", 1, 120)
```

#### ensure_compositor

**Synopsis:** `qt_shell.image_editor.ensure_compositor(viewer=True)`  
**Returns:** NodeTree

Creates the compositor nodes when the scene has none (Render Layers → Group Output) and a Viewer node fed by what goes to the output.

| Parameter | Type | Description |
|---|---|---|
| `viewer` | bool | Also add / link the Viewer node. |

**Example** (✔ tested)

```python
from qt_shell import image_editor

tree = image_editor.ensure_compositor()
print([n.name for n in tree.nodes])
```

### 15 Video Sequencer

The methods below belong to the object you get with `vs = qt_shell.api.video_sequencer()`.

| Command | Description |
|---|---|
| [`video_sequencer`](#video_sequencer) | The Video Sequencer. |
| [`VideoSequencer.add_files`](#videosequenceradd_files) | Adds movies (with their sound), sounds and images one after another; several images of a folder become one image sequence. |
| [`VideoSequencer.add_movie`](#videosequenceradd_movie) | Adds a movie (and its sound strip). |
| [`VideoSequencer.add_sound`](#videosequenceradd_sound) | Adds a sound strip. |
| [`VideoSequencer.add_images`](#videosequenceradd_images) | Adds images of one folder as an image strip (several = a sequence). |
| [`VideoSequencer.add_scene`](#videosequenceradd_scene) | Adds a scene strip. |
| [`VideoSequencer.add_camera_shot`](#videosequenceradd_camera_shot) | A shot like Maya's Camera Sequencer: this scene through cam for a range of the scene, placed after the last shot. |
| [`VideoSequencer.add_text`](#videosequenceradd_text) | Adds a text strip at the current frame. |
| [`VideoSequencer.add_color`](#videosequenceradd_color) | Adds a colour strip at the current frame (the size of the render). |
| [`VideoSequencer.add_adjustment`](#videosequenceradd_adjustment) | Adds an adjustment layer at the current frame. |
| [`VideoSequencer.add_transition`](#videosequenceradd_transition) | A transition between the two selected strips (on the channel above them). |
| [`VideoSequencer.select`](#videosequencerselect) | Selects strips (the last one becomes active). |
| [`VideoSequencer.selected`](#videosequencerselected) | The selected strips of the shown level (top level or the open meta strip). |
| [`VideoSequencer.cut`](#videosequencercut) | Splits the selected strips (none selected: all unlocked strips) at the frame – K. |
| [`VideoSequencer.delete`](#videosequencerdelete) | Deletes the selected strips; ripple=True closes the gap on their channel. |
| [`VideoSequencer.duplicate`](#videosequencerduplicate) | Duplicates the selected strips (Shift+D). |
| [`VideoSequencer.move_strips`](#videosequencermove_strips) | Moves strips by df frames and dch channels. |
| [`VideoSequencer.trim`](#videosequencertrim) | Moves the start ('l') or end ('r') of a strip to a frame. |
| [`VideoSequencer.set_flag`](#videosequencerset_flag) | Sets mute or lock on the selected strips. |
| [`VideoSequencer.toggle`](#videosequencertoggle) | Toggles mute or lock on the selected strips (on when not all of them have it). |
| [`VideoSequencer.set_tag`](#videosequencerset_tag) | Colour tag of the selected strips. |
| [`VideoSequencer.make_meta`](#videosequencermake_meta) | Makes a meta strip of the selected (unlocked) strips. |
| [`VideoSequencer.separate_meta`](#videosequencerseparate_meta) | Breaks the selected meta strips up into their strips. |
| [`VideoSequencer.enter_meta`](#videosequencerenter_meta) | Opens a meta strip – the view then shows its strips. |
| [`VideoSequencer.exit_meta`](#videosequencerexit_meta) | Closes the open meta strip and goes back up. |
| [`VideoSequencer.range_to_strips`](#videosequencerrange_to_strips) | Sets the scene range to all strips. |
| [`VideoSequencer.preview_range_to_selection`](#videosequencerpreview_range_to_selection) | Sets the preview range to the selected strips. |
| [`VideoSequencer.view_frame_all`](#videosequencerview_frame_all) | Fits all strips into the strips view. |
| [`VideoSequencer.play_sound`](#videosequencerplay_sound) | Play / stop: from the preview cache in real time when it is filled, else Blender's own playback with sound. |
| [`VideoSequencer.set_follow`](#videosequencerset_follow) | Timeline + 3D On / Off (the two toolbar buttons): True – the Timeline's playhead and the 3D views follow the sequencer's playback; False – only the sequencer plays, the Timeline and the 3D views stay frozen until it stops. |
| [`VideoSequencer.follow_on`](#videosequencerfollow_on) | True when Timeline + 3D On is chosen (the Timeline and the 3D views play along with the sequencer). |
| [`VideoSequencer.set_blue_pencil`](#videosequencerset_blue_pencil) | Blue Pencil on the Qt Shell preview (switches the preview to Qt Shell's); drawings go to Video Editing layers. |
| [`VideoSequencer.cache_all`](#videosequencercache_all) | Cache All Frames: renders the play range into the Qt Shell preview's cache (Esc stops). |
| [`VideoSequencer.export_video`](#videosequencerexport_video) | Exports the edit – rendered by Blender like Render Animation (progress, cancel); the scene's output settings are put back afterwards. |
| [`formats`](#formats) | The export format ids this Blender can write (its FFmpeg containers / codecs differ between builds). |

#### video_sequencer

**Synopsis:** `qt_shell.api.video_sequencer()`  
**Returns:** VideoSequencer or None

The Video Sequencer. It edits Blender's own strips (scene.sequence_editor), so plain bpy works alongside it; each method makes one undo step.

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
print([s.name for s in vs.selected()])
```

#### VideoSequencer.add_files

**Synopsis:** `VideoSequencer.add_files(paths, frame=None, channel=1)`  
**Returns:** list of strips

Adds movies (with their sound), sounds and images one after another; several images of a folder become one image sequence.

| Parameter | Type | Description |
|---|---|---|
| `paths` | list of str | Files. |
| `frame` | int | Start frame; default the current frame. |
| `channel` | int | Channel (a free one above is used when it is taken). |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.add_files(["C:/clips/shot010.mp4", "C:/music/song.wav"], frame=1)
```

#### VideoSequencer.add_movie

**Synopsis:** `VideoSequencer.add_movie(path, frame=None, channel=1, with_sound=True)`  
**Returns:** list of strips

Adds a movie (and its sound strip).

| Parameter | Type | Description |
|---|---|---|
| `path` | str | Movie file. |
| `frame` | int | Start frame. |
| `channel` | int | Channel. |
| `with_sound` | bool | Also add the sound. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
movie, sound = vs.add_movie("C:/clips/shot010.mp4", frame=1, channel=2)
```

#### VideoSequencer.add_sound

**Synopsis:** `VideoSequencer.add_sound(path, frame=None, channel=1)`  
**Returns:** strip

Adds a sound strip.

| Parameter | Type | Description |
|---|---|---|
| `path` | str | Sound file. |
| `frame` | int | Start frame. |
| `channel` | int | Channel. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
s = vs.add_sound("C:/music/song.wav", frame=1, channel=4)
s.volume = 0.5
```

#### VideoSequencer.add_images

**Synopsis:** `VideoSequencer.add_images(paths, frame=None, channel=1)`  
**Returns:** strip or None

Adds images of one folder as an image strip (several = a sequence).

| Parameter | Type | Description |
|---|---|---|
| `paths` | list of str | Image files of one folder. |
| `frame` | int | Start frame. |
| `channel` | int | Channel. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.add_images(["C:/frames/shot_0001.png", "C:/frames/shot_0002.png"], frame=1, channel=3)
```

#### VideoSequencer.add_scene

**Synopsis:** `VideoSequencer.add_scene(scn, frame=None, channel=1)`  
**Returns:** strip

Adds a scene strip.

| Parameter | Type | Description |
|---|---|---|
| `scn` | Scene | The scene. |
| `frame` | int | Start frame. |
| `channel` | int | Channel. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.add_scene(bpy.context.scene, frame=1, channel=5)
```

#### VideoSequencer.add_camera_shot

**Synopsis:** `VideoSequencer.add_camera_shot(cam, start=None, end=None)`  
**Returns:** strip

A shot like Maya's Camera Sequencer: this scene through cam for a range of the scene, placed after the last shot. Range: the preview range when it is on, else the scene range.

| Parameter | Type | Description |
|---|---|---|
| `cam` | Object | A camera. |
| `start` | int | First scene frame. |
| `end` | int | Last scene frame. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
cam_data = bpy.data.cameras.new("ShotCam")
cam = bpy.data.objects.new("ShotCam", cam_data)
bpy.context.scene.collection.objects.link(cam)
vs.add_camera_shot(cam, 1, 48)
```

#### VideoSequencer.add_text

**Synopsis:** `VideoSequencer.add_text()`  
**Returns:** strip

Adds a text strip at the current frame.

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
s = vs.add_text()
s.text = "Scene 1"
```

#### VideoSequencer.add_color

**Synopsis:** `VideoSequencer.add_color()`  
**Returns:** strip

Adds a colour strip at the current frame (the size of the render).

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
s = vs.add_color()
s.color = (0.1, 0.1, 0.12)
```

#### VideoSequencer.add_adjustment

**Synopsis:** `VideoSequencer.add_adjustment()`  
**Returns:** strip

Adds an adjustment layer at the current frame.

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.add_adjustment()
```

#### VideoSequencer.add_transition

**Synopsis:** `VideoSequencer.add_transition(etype)`  
**Returns:** strip or None

A transition between the two selected strips (on the channel above them). None when not exactly two are selected.

| Parameter | Type | Description |
|---|---|---|
| `etype` | str | "CROSS", "GAMMA_CROSS" or "WIPE". |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
a = vs.add_color()
bpy.context.scene.frame_set(a.frame_final_end - 10)
b = vs.add_color()
vs.select([a, b])
vs.add_transition("CROSS")
```

#### VideoSequencer.select

**Synopsis:** `VideoSequencer.select(strips, extend=False, toggle=False, deselect=False)`  
**Returns:** None

Selects strips (the last one becomes active).

| Parameter | Type | Description |
|---|---|---|
| `strips` | list | Strips. |
| `extend` | bool | Keep the current selection. |
| `toggle` | bool | Toggle each strip. |
| `deselect` | bool | Deselect them. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
s = vs.add_text()
vs.select([s])
vs.select([s], deselect=True)
```

#### VideoSequencer.selected

**Synopsis:** `VideoSequencer.selected()`  
**Returns:** list of strips

The selected strips of the shown level (top level or the open meta strip).

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
for s in vs.selected():
    print(s.name, s.channel, s.frame_final_start)
```

#### VideoSequencer.cut

**Synopsis:** `VideoSequencer.cut(frame=None)`  
**Returns:** int – strips cut

Splits the selected strips (none selected: all unlocked strips) at the frame – K.

| Parameter | Type | Description |
|---|---|---|
| `frame` | int | Default: the current frame. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
s = vs.add_color()
vs.select([s])
vs.cut(s.frame_final_start + 10)
```

#### VideoSequencer.delete

**Synopsis:** `VideoSequencer.delete(ripple=False)`  
**Returns:** int – strips deleted

Deletes the selected strips; ripple=True closes the gap on their channel.

| Parameter | Type | Description |
|---|---|---|
| `ripple` | bool | Ripple delete. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
s = vs.add_color()
vs.select([s])
vs.delete(ripple=True)
```

#### VideoSequencer.duplicate

**Synopsis:** `VideoSequencer.duplicate()`  
**Returns:** int – strips added

Duplicates the selected strips (Shift+D).

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.select([vs.add_text()])
vs.duplicate()
```

#### VideoSequencer.move_strips

**Synopsis:** `VideoSequencer.move_strips(strips, df, dch)`  
**Returns:** None

Moves strips by df frames and dch channels.

| Parameter | Type | Description |
|---|---|---|
| `strips` | list | Strips. |
| `df` | int | Frames. |
| `dch` | int | Channels. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
s = vs.add_color()
vs.move_strips([s], 10, 1)      # +10 frames, one channel up
```

#### VideoSequencer.trim

**Synopsis:** `VideoSequencer.trim(s, side, frame)`  
**Returns:** None

Moves the start ('l') or end ('r') of a strip to a frame.

| Parameter | Type | Description |
|---|---|---|
| `s` | strip | The strip. |
| `side` | str | "l" = start, "r" = end. |
| `frame` | int | The new frame. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
s = vs.add_color()
vs.trim(s, "r", s.frame_final_start + 24)
```

#### VideoSequencer.set_flag

**Synopsis:** `VideoSequencer.set_flag(attr, on)`  
**Returns:** None

Sets mute or lock on the selected strips.

| Parameter | Type | Description |
|---|---|---|
| `attr` | str | "mute" or "lock". |
| `on` | bool | On / off. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.select([vs.add_text()])
vs.set_flag("mute", True)
vs.set_flag("mute", False)
```

#### VideoSequencer.toggle

**Synopsis:** `VideoSequencer.toggle(attr)`  
**Returns:** None

Toggles mute or lock on the selected strips (on when not all of them have it).

| Parameter | Type | Description |
|---|---|---|
| `attr` | str | "mute" or "lock". |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.select([vs.add_text()])
vs.toggle("lock")
```

#### VideoSequencer.set_tag

**Synopsis:** `VideoSequencer.set_tag(key)`  
**Returns:** None

Colour tag of the selected strips.

| Parameter | Type | Description |
|---|---|---|
| `key` | str | "NONE" or "COLOR_01" … "COLOR_09". |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.select([vs.add_text()])
vs.set_tag("COLOR_03")
```

#### VideoSequencer.make_meta

**Synopsis:** `VideoSequencer.make_meta()`  
**Returns:** meta strip or None

Makes a meta strip of the selected (unlocked) strips.

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.select([vs.add_color(), vs.add_text()])
meta = vs.make_meta()
print(meta.name)
```

#### VideoSequencer.separate_meta

**Synopsis:** `VideoSequencer.separate_meta()`  
**Returns:** None

Breaks the selected meta strips up into their strips.

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.select([vs.add_color(), vs.add_text()])
vs.make_meta()
vs.separate_meta()
```

#### VideoSequencer.enter_meta

**Synopsis:** `VideoSequencer.enter_meta(s)`  
**Returns:** None

Opens a meta strip – the view then shows its strips.

| Parameter | Type | Description |
|---|---|---|
| `s` | meta strip | The meta strip. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.select([vs.add_color(), vs.add_text()])
meta = vs.make_meta()
vs.enter_meta(meta)
vs.exit_meta()
```

#### VideoSequencer.exit_meta

**Synopsis:** `VideoSequencer.exit_meta()`  
**Returns:** None

Closes the open meta strip and goes back up.

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.exit_meta()
```

#### VideoSequencer.range_to_strips

**Synopsis:** `VideoSequencer.range_to_strips()`  
**Returns:** None

Sets the scene range to all strips.

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.add_color()
vs.range_to_strips()
```

#### VideoSequencer.preview_range_to_selection

**Synopsis:** `VideoSequencer.preview_range_to_selection()`  
**Returns:** None

Sets the preview range to the selected strips.

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.select([vs.add_text()])
vs.preview_range_to_selection()
bpy.context.scene.use_preview_range = False
```

#### VideoSequencer.view_frame_all

**Synopsis:** `VideoSequencer.view_frame_all()`  
**Returns:** None

Fits all strips into the strips view.

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.view_frame_all()
```

#### VideoSequencer.play_sound

**Synopsis:** `VideoSequencer.play_sound()`  
**Returns:** None

Play / stop: from the preview cache in real time when it is filled, else Blender's own playback with sound.

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.play_sound()          # play
vs.play_sound()          # stop
```

#### VideoSequencer.set_follow

**Synopsis:** `VideoSequencer.set_follow(on=True)`  
**Returns:** None

Timeline + 3D On / Off (the two toolbar buttons): True – the Timeline's playhead and the 3D views follow the sequencer's playback; False – only the sequencer plays, the Timeline and the 3D views stay frozen until it stops.

| Parameter | Type | Description |
|---|---|---|
| `on` | bool | True = Timeline + 3D On, False = Timeline + 3D - Off. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
old = vs.follow_on()
vs.set_follow(False)          # faster playback: Timeline and 3D views frozen
print(vs.follow_on())         # False
vs.set_follow(old)
```

#### VideoSequencer.follow_on

**Synopsis:** `VideoSequencer.follow_on()`  
**Returns:** bool

True when Timeline + 3D On is chosen (the Timeline and the 3D views play along with the sequencer).

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
print(vs.follow_on())
```

#### VideoSequencer.set_blue_pencil

**Synopsis:** `VideoSequencer.set_blue_pencil(on)`  
**Returns:** None

Blue Pencil on the Qt Shell preview (switches the preview to Qt Shell's); drawings go to Video Editing layers.

| Parameter | Type | Description |
|---|---|---|
| `on` | bool | On / off. |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.set_blue_pencil(True)
vs.set_blue_pencil(False)
```

#### VideoSequencer.cache_all

**Synopsis:** `VideoSequencer.cache_all()`  
**Returns:** int – frames cached

Cache All Frames: renders the play range into the Qt Shell preview's cache (Esc stops).

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.pane.set_mode("qt")
vs.add_color()
vs.cache_all()
vs.pane.set_mode("blender")
```

#### VideoSequencer.export_video

**Synopsis:** `VideoSequencer.export_video(path=None, fmt=None, start=None, end=None, quality="HIGH", scale=100, audio=True)`  
**Returns:** bool

Exports the edit – rendered by Blender like Render Animation (progress, cancel); the scene's output settings are put back afterwards. Without a path the Export dialog opens. last_export["state"] goes from "running" to "done", "cancelled" or "failed" (with "files").

| Parameter | Type | Description |
|---|---|---|
| `path` | str | The file (an image sequence: its first file name, numbers are added). |
| `fmt` | str | MP4_H264, MP4_H265, MP4_AV1, MOV_H264, MOV_PRORES, MKV_H264, MKV_FFV1, WEBM_VP9, AVI_H264, OGG_THEORA · SEQ_PNG, SEQ_JPEG, SEQ_TIFF, SEQ_EXR, SEQ_WEBP · AUDIO_WAV, AUDIO_MP3, AUDIO_FLAC, AUDIO_OGG (qt_shell.seq_export.formats() = what this Blender can write). |
| `start` | int | First frame; default the scene start. |
| `end` | int | Last frame; default the scene end. |
| `quality` | str | "LOSSLESS", "HIGH", "MEDIUM" or "LOW". |
| `scale` | int | Per cent of the scene resolution. |
| `audio` | bool | Include the sound (video formats). |

**Example** (✔ tested)

```python
import bpy, qt_shell

vs = qt_shell.api.video_sequencer()
vs.add_color()
vs.export_video("C:/out/edit.mp4", "MP4_H264", start=1, end=24, quality="MEDIUM", scale=50)
print(vs.last_export["state"])          # running … then done
```

#### formats

**Synopsis:** `qt_shell.seq_export.formats()`  
**Returns:** list of str

The export format ids this Blender can write (its FFmpeg containers / codecs differ between builds).

**Example** (✔ tested)

```python
import qt_shell.seq_export as sx

print(sx.formats())
print([f for f in sx.formats() if f.startswith("AUDIO_")])
```

### 15 Blue Pencil, burn-in and annotations

| Command | Description |
|---|---|
| [`data`](#data) | The scene's Blue Pencil data: {"layers": [{"name", "camera", "space", "frames": {frame: [strokes]}}, …]} (JSON in scene["qtshell_bluepencil"]). |
| [`commit`](#commit) | Writes the edited data back to the scene: saved with the file, one undo step. |
| [`new_layer`](#new_layer) | A new layer on top of the list (active). |
| [`insert_frame`](#insert_frame) | An empty drawing at frame f on the active layer. |
| [`duplicate_frame`](#duplicate_frame) | Copies the drawing shown before f to a new frame at f. |
| [`delete_frame`](#delete_frame) | Deletes the drawing at frame f of the active layer. |
| [`copy_frame`](#copy_frame) | Copies (or cuts) the drawing at frame f. |
| [`paste_frame`](#paste_frame) | Pastes the copied drawing at frame f. |
| [`step`](#step) | Goes to the previous / next drawing of the active layer. |
| [`retime`](#retime) | Retiming: "ABS" = exactly n frames between the drawings (1–6), "REL" = ±n frames after the drawing. |
| [`set_variant`](#set_variant) | The Blue Pencil drawing tool without switching the 3D view to Blue Pencil (shared by the Render View, the Animation Player and the Video Sequencer). |
| [`has_drawings`](#has_drawings) | True when a visible layer of the camera / window has strokes. |
| [`set_panel_space`](#set_panel_space) | The Blue Pencil panel's window tab (also where New Layer goes). |
| [`panel_space`](#panel_space) | The Blue Pencil panel's window tab. |
| [`new_space_layer`](#new_space_layer) | A new layer for a window (default: the panel's tab) with that window's camera (space_camera()). |
| [`space_camera`](#space_camera) | The camera a new layer of a window gets: the 3D view's camera when looking through it (else "" = the View), the render camera, the scene camera for the Animation Player, "" for the Video Sequencer. |
| [`set_enabled`](#set_enabled) | Burn In: Blue Pencil / annotations burnt into renders (Render → Burn In Drawings). |
| [`viewport_render`](#viewport_render) | The scene drawn like the 3D view at the render size (Viewport Render), with the drawings when overlays. |
| [`playblast`](#playblast) | Viewport Render Animation: PNG frames in the folder `playblast` next to the output frames. |
| [`burn_animation`](#burn_animation) | Copies the rendered frames with the drawings into the folder `overlay`. |
| [`add_stroke`](#add_stroke) | Adds a stroke to the active note layer of the 3D view's annotations (Blender data: scene.annotation). |

#### data

**Synopsis:** `qt_shell.bluepencil.data(scene=None)`  
**Returns:** dict

The scene's Blue Pencil data: {"layers": [{"name", "camera", "space", "frames": {frame: [strokes]}}, …]} (JSON in scene["qtshell_bluepencil"]). After editing it call commit().

| Parameter | Type | Description |
|---|---|---|
| `scene` | Scene | Default: the current scene. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

for lay in bp.data()["layers"]:
    print(lay["name"], lay.get("space"), sorted(lay["frames"]))
```

#### commit

**Synopsis:** `qt_shell.bluepencil.commit(message, scene=None)`  
**Returns:** None

Writes the edited data back to the scene: saved with the file, one undo step.

| Parameter | Type | Description |
|---|---|---|
| `message` | str | Undo step name. |
| `scene` | Scene | Default: the current scene. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

d = bp.data()
if d["layers"]:
    d["layers"][0]["name"] = "Notes"
bp.commit("Rename Layer")
```

#### new_layer

**Synopsis:** `qt_shell.bluepencil.new_layer(name=None, camera=None, state="ANIMATION", do_commit=True, space="VIEWPORT")`  
**Returns:** dict – the layer

A new layer on top of the list (active).

| Parameter | Type | Description |
|---|---|---|
| `name` | str | Layer name. |
| `camera` | str | Camera object name, "" = the View. |
| `state` | str | "ANIMATION" (keyed on frames) or "STATIC". |
| `do_commit` | bool | Save it at once. |
| `space` | str | "VIEWPORT", "RENDER", "ANIM" or "VIDEO" – the window it is drawn in. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

lay = bp.new_layer("Notes", camera="")
print(lay["name"])
```

#### insert_frame

**Synopsis:** `qt_shell.bluepencil.insert_frame(f=None)`  
**Returns:** None

An empty drawing at frame f on the active layer.

| Parameter | Type | Description |
|---|---|---|
| `f` | int | Default: the current frame. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

bp.new_layer("Keys", camera="")
bp.insert_frame(1)
bp.insert_frame(12)
```

#### duplicate_frame

**Synopsis:** `qt_shell.bluepencil.duplicate_frame(f=None)`  
**Returns:** None

Copies the drawing shown before f to a new frame at f.

| Parameter | Type | Description |
|---|---|---|
| `f` | int | Default: the current frame. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

bp.new_layer("Keys", camera="")
bp.insert_frame(1)
bp.duplicate_frame(5)
```

#### delete_frame

**Synopsis:** `qt_shell.bluepencil.delete_frame(f=None)`  
**Returns:** None

Deletes the drawing at frame f of the active layer.

| Parameter | Type | Description |
|---|---|---|
| `f` | int | Default: the current frame. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

bp.new_layer("Keys", camera="")
bp.insert_frame(3)
bp.delete_frame(3)
```

#### copy_frame

**Synopsis:** `qt_shell.bluepencil.copy_frame(f=None, cut=False)`  
**Returns:** None

Copies (or cuts) the drawing at frame f.

| Parameter | Type | Description |
|---|---|---|
| `f` | int | Default: the current frame. |
| `cut` | bool | Cut instead of copy. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

bp.new_layer("Keys", camera="")
bp.insert_frame(1)
bp.copy_frame(1)
bp.paste_frame(10)
```

#### paste_frame

**Synopsis:** `qt_shell.bluepencil.paste_frame(f=None)`  
**Returns:** None

Pastes the copied drawing at frame f.

| Parameter | Type | Description |
|---|---|---|
| `f` | int | Default: the current frame. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

bp.new_layer("Keys", camera="")
bp.insert_frame(1)
bp.copy_frame(1)
bp.paste_frame(20)
```

#### step

**Synopsis:** `qt_shell.bluepencil.step(direction)`  
**Returns:** None

Goes to the previous / next drawing of the active layer.

| Parameter | Type | Description |
|---|---|---|
| `direction` | int | 1 = next, -1 = previous. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

bp.new_layer("Keys", camera="")
bp.insert_frame(1)
bp.insert_frame(8)
bp.step(-1)
```

#### retime

**Synopsis:** `qt_shell.bluepencil.retime(mode, n, selection=None)`  
**Returns:** None

Retiming: "ABS" = exactly n frames between the drawings (1–6), "REL" = ±n frames after the drawing.

| Parameter | Type | Description |
|---|---|---|
| `mode` | str | "ABS" or "REL". |
| `n` | int | Frames. |
| `selection` | list | Selected keys (Timeline); None = the drawing at the current frame. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

bp.new_layer("Keys", camera="")
for f in (1, 3, 5):
    bp.insert_frame(f)
bp.retime("ABS", 2)
```

#### set_variant

**Synopsis:** `qt_shell.bluepencil.set_variant(tool)`  
**Returns:** None

The Blue Pencil drawing tool without switching the 3D view to Blue Pencil (shared by the Render View, the Animation Player and the Video Sequencer).

| Parameter | Type | Description |
|---|---|---|
| `tool` | str | PENCIL, BRUSH, ERASER, TEXT, LINE, ARROW, ELLIPSE, RECT or TRANSFORM. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

bp.set_variant("BRUSH")
```

#### has_drawings

**Synopsis:** `qt_shell.bluepencil.has_drawings(cam, space="VIEWPORT")`  
**Returns:** bool

True when a visible layer of the camera / window has strokes.

| Parameter | Type | Description |
|---|---|---|
| `cam` | str | Camera object name, "" = the View. |
| `space` | str | VIEWPORT, RENDER, ANIM or VIDEO. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

print(bp.has_drawings("", "VIEWPORT"))
```

#### set_panel_space

**Synopsis:** `qt_shell.bluepencil.set_panel_space(space)`  
**Returns:** None

The Blue Pencil panel's window tab (also where New Layer goes).

| Parameter | Type | Description |
|---|---|---|
| `space` | str | VIEWPORT, RENDER, ANIM or VIDEO. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

bp.set_panel_space("RENDER")
print(bp.panel_space())
bp.set_panel_space("VIEWPORT")
```

#### panel_space

**Synopsis:** `qt_shell.bluepencil.panel_space()`  
**Returns:** str

The Blue Pencil panel's window tab.

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

print(bp.panel_space())
```

#### new_space_layer

**Synopsis:** `qt_shell.bluepencil.new_space_layer(space=None)`  
**Returns:** dict – the layer

A new layer for a window (default: the panel's tab) with that window's camera (space_camera()).

| Parameter | Type | Description |
|---|---|---|
| `space` | str | VIEWPORT, RENDER, ANIM or VIDEO. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

lay = bp.new_space_layer("ANIM")
print(lay["name"], lay["space"])
```

#### space_camera

**Synopsis:** `qt_shell.bluepencil.space_camera(space)`  
**Returns:** str

The camera a new layer of a window gets: the 3D view's camera when looking through it (else "" = the View), the render camera, the scene camera for the Animation Player, "" for the Video Sequencer.

| Parameter | Type | Description |
|---|---|---|
| `space` | str | VIEWPORT, RENDER, ANIM or VIDEO. |

**Example** (✔ tested)

```python
import qt_shell.bluepencil as bp

print(repr(bp.space_camera("VIEWPORT")))
```

#### set_enabled

**Synopsis:** `qt_shell.burnin.set_enabled(on)`  
**Returns:** None

Burn In: Blue Pencil / annotations burnt into renders (Render → Burn In Drawings).

| Parameter | Type | Description |
|---|---|---|
| `on` | bool | On / off. |

**Example** (✔ tested)

```python
import qt_shell.burnin as burnin

burnin.set_enabled(True)
burnin.set_enabled(False)
```

#### viewport_render

**Synopsis:** `qt_shell.burnin.viewport_render(scene=None, frame=None, overlays=True, vp=None)`  
**Returns:** QImage

The scene drawn like the 3D view at the render size (Viewport Render), with the drawings when overlays.

| Parameter | Type | Description |
|---|---|---|
| `scene` | Scene | Default: the current scene. |
| `frame` | int | Default: the current frame. |
| `overlays` | bool | Draw Blue Pencil / annotations. |
| `vp` | QWidget | The view; default the active one. |

**Example** (✔ tested)

```python
import qt_shell.burnin as burnin

img = burnin.viewport_render()
img.save("C:/out/viewport.png")
```

#### playblast

**Synopsis:** `qt_shell.burnin.playblast(scene=None, start=None, end=None, overlays=True, vp=None)`  
**Returns:** (frames written, folder or message)

Viewport Render Animation: PNG frames in the folder `playblast` next to the output frames.

| Parameter | Type | Description |
|---|---|---|
| `scene` | Scene | Default: the current scene. |
| `start` | int | First frame. |
| `end` | int | Last frame. |
| `overlays` | bool | Draw the drawings. |
| `vp` | QWidget | The view. |

**Example** (✔ tested)

```python
import bpy
import qt_shell.burnin as burnin

bpy.context.scene.render.filepath = "C:/out/shot_"
print(burnin.playblast(start=1, end=3))
```

#### burn_animation

**Synopsis:** `qt_shell.burnin.burn_animation(scene=None, start=None, end=None)`  
**Returns:** (frames written, message)

Copies the rendered frames with the drawings into the folder `overlay`.

| Parameter | Type | Description |
|---|---|---|
| `scene` | Scene | Default: the current scene. |
| `start` | int | First frame. |
| `end` | int | Last frame. |

**Example** (not run by the test – needs rendered frames)

```python
import qt_shell.burnin as burnin

print(burnin.burn_animation())         # after Render Animation
```

#### add_stroke

**Synopsis:** `qt_shell.annotate.add_stroke(coords, mode="3DSPACE")`  
**Returns:** None

Adds a stroke to the active note layer of the 3D view's annotations (Blender data: scene.annotation).

| Parameter | Type | Description |
|---|---|---|
| `coords` | list of (x, y, z) | Points. |
| `mode` | str | "3DSPACE" (world) – Blender's stroke placement. |

**Example** (✔ tested)

```python
import qt_shell.annotate as annotate

annotate.add_stroke([(0, 0, 0), (1, 0, 1), (2, 0, 0)])
```

### 15 Updates

| Command | Description |
|---|---|
| [`check_for_updates`](#check_for_updates) | Help → Check for Qt Shell Updates…: the dialog with newer GitHub releases, their notes and Install. |
| [`latest_release`](#latest_release) | {"version": (0, 72, 0), "tag", "name", "notes", "url", "zip", "date"} of the newest release on GitHub. |

#### check_for_updates

**Synopsis:** `qt_shell.api.check_for_updates()`  
**Returns:** dialog or None

Help → Check for Qt Shell Updates…: the dialog with newer GitHub releases, their notes and Install. The dialog has select_version("0.65.0"), selected() and install().

**Example** (✔ tested)

```python
import qt_shell.api as qs

dlg = qs.check_for_updates()
dlg.close()
```

#### latest_release

**Synopsis:** `qt_shell.api.latest_release()`  
**Returns:** dict or None

{"version": (0, 72, 0), "tag", "name", "notes", "url", "zip", "date"} of the newest release on GitHub. Blocks while it downloads; raises RuntimeError when Blender's online access is off.

**Example** (not run by the test – needs Blender's online access)

```python
import qt_shell.api as qs

rel = qs.latest_release()
print(rel["tag"], rel["date"])
```

<!-- END COMMAND REFERENCE -->

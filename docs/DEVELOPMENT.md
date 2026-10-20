# Qt Shell – development notes and status

Where the project is, how it is built, tested and released, and what is still open.
Keep this file up to date at the end of every work session.

- **Repository:** https://github.com/xmoner/blender-qt-shell (branch `main`)
- **Current version:** 0.14.0 (`qt_shell/__init__.py` → `bl_info["version"]`), Python API 1.2
- **Last updated:** 2026-10-20
- **Owner:** xmoner – communicates in **Czech**; code, comments, README, docs and release notes are in **English**.

---

## 1. What it is

A Blender add-on (`qt_shell/`) that replaces Blender's UI with a PySide6 (Qt) window: 3D viewport,
Properties, Outliner, Timeline, Console, Node editor, UV editor, Text editor, Sidebar (N panel),
menus, operator search. Blender keeps running hidden underneath; Qt drives it through `bpy`.

Tested on **Blender 5.2.0 LTS, Windows 11** (Czech keyboard). Requires Blender 4.2+.

---

## 2. Architecture – the important parts

| Topic | How it works |
|---|---|
| **Event pump** | `app.py`: a `bpy.app.timers` timer calls `QApplication.processEvents()`; returns `0.0` while playing, `0.01` otherwise. `native.wake_event_loop()` posts `WM_NULL` after processing. |
| **Blender context in Qt events** | `ShellApp.notify` delegates to the module-level `_notify_with_context` (looked up through `sys.modules`), which wraps every Qt event in `bridge.blender_context()` (`temp_override` onto a 3D view). **Never reassign `notify` on a running QApplication** – Shiboken caches the override and the freed function crashes Blender (`<invalid frame>`). |
| **Hidden Blender window** | `native.py`: SW_MINIMIZE then SW_HIDE (otherwise Blender keeps redrawing and waits for VSync → 60 fps cap). |
| **Viewport rendering** | `viewport.py`: `GPUOffScreen.draw_view3d()` with our own camera matrices → numpy → copied flipped into a Qt-owned `QImage` (`img.bits()`). One view = one `Viewport` widget with its own camera. |
| **Split views** | `ViewportArea` (in `viewport.py`): single / side / stacked / quad (Ctrl+Alt+Q). `MainWindow.viewport` is a property = the active view; `hub.viewport` follows the active view, `hub.viewport_area` is the area. Shading is shared (Blender's space). |
| **Playback** | `Timeline.playback_tick()`: time-based, follows `scene.sync_mode`; `ViewportArea.render_now()` draws every visible view. ~117 fps at 120 target. |
| **UI from Blender's Python UI code** | `fake_ui.py` records `Panel.draw` / `Menu.draw` calls; `qt_ui.py` builds Qt widgets from the recording; `rna_widgets.py` binds widgets to RNA properties. Properties pages build atomically and each panel is wrapped in try/except (one broken panel shows an error, the tab still works). |
| **Public API** | `api.py` (`import qt_shell.api as qs`), version 1.2. Registry lives in `api.state_store()` = a module `_qt_shell_state` in `sys.modules` (survives add-on reloads and loading other .blend files). Full reference: `docs/API.md`. |
| **Script manager** | `scripts.py`: runs scripts, records what they register (API items, `bpy` classes, `bpy.app.handlers`), Unload / Reload, auto-load (files in `config/qt_shell/scripts.json`, texts with custom prop `qtshell_autoload`). No PySide in this module. |
| **Text editor** | `text_editor.py`: `CodeEditor` (QPlainTextEdit) + `TextEditor` dock on `bpy.data.texts`. Auto-completion logic in `completion.py` (pure Python, no code execution) – popup = `QCompleter`, names in `Qt.UserRole`. |
| **Transform tools / gizmo** | `gizmo.py`: `ToolState` (shared tool + toolbar visibility, QSettings `viewport/tool`, `viewport/toolbar`, stored on `hub._tool_state`), `Toolbar` (child of each `Viewport`), `handles()` (ids "G:X", "R:VIEW", "S:UNIFORM", …) / `hit()` / `paint()` in screen space, `ToolMenu` (Shift+Space), `start_drag()` → `Viewport.start_modal()` with the axis set and `m['drag']=True` (mouse release confirms). Pivot = median of selected origins / selected verts (edit-mode pivot cached, invalidated on data / selection change). Constrained G follows the projected axis on screen. |
| **Built-in items in Blender menus** | Menus generated from Blender call `api.extend_menu()` when they open; it calls `MainWindow.extend_builtin_menu(menu, key)` first (e.g. inserts *Qt Preferences…* after Blender's *Preferences…* in Edit), then the API items. |
| **Theme** | `theme.py`: `qss()` app stylesheet, `px()` / `fs()` scaling, `HOVER` colours + `hover_qss()` / `field_hover_qss()` (append them to any widget stylesheet that sets a button / field background, otherwise the hover effect is hidden). |
| **Logs** | `%TEMP%\qtshell.log` (errors/warnings), `%TEMP%\qtshell_crash.log` (faulthandler – note: it also logs harmless first-chance access violations, e.g. inside the Windows file dialog). |
| **Safe start** | `app.start()` writes `%TEMP%\qtshell_starting` before building the window and removes it 3 s after `show()`. If it exists on the next start, the saved window layout (`QSettings("QtShell","QtShell")` → `state`, `geometry`) is discarded. |

### Lessons learned (avoid these bugs again)

- **Give every Qt widget its parent when you create it.** Widgets added to a layout that is not yet
  installed on a widget can be freed by Python → access violation when the window is shown.
- **A widget-level stylesheet overrides the app stylesheet for that widget and its children** – add
  `theme.hover_qss()` to it. Mixing a selector-less declaration with rules in one sheet is invalid:
  use `QWidget { … }`.
- **`QStandardItem`: `EditRole` == `DisplayRole`.** Use `Qt.UserRole` for data that differs from the label.
- **Zoom limits must clamp, not refuse** (Node editor wheel bug). Don't frame/fit a view while it is
  hidden or tiny – defer until it is visible (`NodeView._big_enough()`, `_frame_pending`).
- **Styling `QMenu::item` disables the default selection highlight** – style `:selected` explicitly.
- **Dropping text dragged from a QPlainTextEdit: force `Qt.CopyAction`** – the default is Move, which deletes the
  text from the editor.
- **Never save a layout with a floating dock.** Restoring a `QMainWindow` state that contains a floating
  `QDockWidget` crashes Qt on Windows in `show()` (execute access violation at a bogus address), even if the
  dock is docked again right after `restoreState()`. Floating at run time is fine. `MainWindow.shutdown()`
  docks floating docks before `saveState()`; restored floating docks are docked too (`api._install_dock` as well).
  This was the cause of the recurring "previous start did not finish" crashes (2026-10-19/20).
  To keep floating windows across restarts, `shutdown()` stores their geometry in QSettings `floating_docks`
  (JSON) before docking them, and `MainWindow._float_saved_docks()` floats them again **1.5 s after the start**
  (tested OK; re-floating right after `show()` crashed). Safe start also clears `floating_docks`.
  Workspaces follow the same rule: `Workspaces.capture()` docks floating docks, saves the state, then floats
  them again; `_apply()` docks everything, restores, and re-floats 50 ms later.
- **`deleteLater` is never processed by Blender's `processEvents` pump** – a closed MainWindow stays alive
  (hidden). After the workspaces were added, `devreload` crashed in the new window's `show()` (access violation,
  2026-10-20, twice). Fix: `devreload` calls `QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)`
  right after `app.stop()` → the old window is deleted before the new one is built (3 reloads in a row OK).
  Plain close (*Return to the Blender UI*) + *Window → Open Qt Shell* worked without it. When poking at the
  window from the Console, pick the *visible* one (`... if hasattr(w, "workspaces") and w.isVisible()`).
- **Re-adding docks (`_reset_layout`) can grow the window** past the screen. Workspace switches remember the
  window geometry and put it back (`workspaces.fit_to_screen`); templates set dock widths with `resizeDocks`.
- **Computer-use note:** the top-right corner of the screen (x > ~1070 in screenshots) belongs to the Claude
  app's overlay – clicks there don't reach Blender. Make the Qt Shell window narrower to click the workspace tabs.

---

## 3. Files

```
qt_shell/            the add-on (zip this folder for a release)
  __init__.py        bl_info, preferences (Install PySide6), auto start, Window → Open Qt Shell
  app.py             QApplication, event pump, start/stop, safe start, interface size
  bridge.py          Blender context, logging, run_op, file dialog hooks, DEFER_OPS
  native.py          hide/show the Blender window (WinAPI / Cocoa / xdotool)
  main_window.py     QMainWindow: docks, menus, shortcuts, status bar (+ history), render window
  viewport.py        Viewport (one 3D view) + ViewportArea (split views)
  editmesh.py        edit-mode selection / transform in the Qt viewport
  properties.py      Properties editor (tabs, atomic page build)
  sidebar.py         N panel (VIEW_3D UI panels, Item ▸ Transform in Qt)
  outliner.py, timeline.py, console.py, node_editor.py, uv_editor.py
  text_editor.py     Text editor dock (Run Script, Run Selection, Unload, auto-complete)
  completion.py      auto-completion logic (no Qt)
  scripts.py         script manager core (no Qt)
  scripts_dock.py    Scripts dock UI – NOT USED (disabled, see 6.1)
  shelf.py           Shelf (dock 'shelf' at the top, floatable) – buttons run code via scripts._execute; config/qt_shell/shelves.json
  graph_editor.py    Graph editor (Maya-like): channel tree + GraphView; selection = Blender's key select flags; Blender 4.4+ channelbags via bpy_extras.anim_utils
  workspaces.py      Workspaces (tabs = menu bar corner widget; manager captures/restores saveState per workspace; templates; config/qt_shell/workspaces.json)
  prefs_window.py    Edit → Qt Preferences… (Qt Shell settings; Scripts page replaces the disabled Scripts dock for startup files)
  api.py             public API (qt_shell.api)
  fake_ui.py, qt_ui.py, rna_widgets.py   Blender UI code → Qt widgets
  theme.py           colours, stylesheet, scaling, hover styles
  devreload.py       developer reload (closes Qt Shell, reloads all modules, opens it again)
docs/API.md          Python API reference (also saved in the claude.ai project)
docs/DEVELOPMENT.md  this file
examples/api_demo.py, examples/viewport_button.py
README.md            features table, install, troubleshooting (also qt_shell/README.md – keep both in sync)
```

---

## 4. Workflow (how changes were made and tested)

### Edit → deploy → test on the owner's PC
The cloud workspace has the repo at `/home/claude/blender-qt-shell`. The owner's PC is linked; the
add-on folder there is connected:

`C:\Users\uzivatel\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\qt_shell`
(device shell: `$HOME/mnt/qt_shell`; temp folder: `$HOME/mnt/Temp` = `%TEMP%`)

1. Edit in the repo; check syntax / undefined names (`ast` check script).
2. Copy changed files into a **new unique folder** `/mnt/user-data/outputs/<name>_<timestamp>/`
   (re-using a staging path can deliver stale content).
3. `device_commit_files` with `force=true` to the add-on folder, then verify sizes with `wc -c` on the device.
4. Reload in the running Qt Shell: Console tab → `import qt_shell.devreload as _r; _r.go()` (Enter).
   Or restart Blender.
5. Test with computer use (Blender 5.2 = `blender.exe` must be granted).

### Computer-use gotchas
- The **Claude window overlays the top-right of the screen** – clicks there land in Claude, not Blender.
  Use console commands instead of clicking top-right buttons.
- `computer_open_application("Blender")` can **start a second Blender** instead of focusing the running one.
- `computer_type` pastes via clipboard → it does **not** trigger key handlers (auto-complete); use
  `computer_key` for single keys.
- Ctrl+Space outside the Text editor = maximize viewport (window shortcut).
- **Don't reload / click while the owner is working in Blender** – deploy the files and tell them how to reload.

### Commit / release
- Commit messages end with the `Co-Authored-By` / `Claude-Session` lines from the session.
- Push to `main` works from the session. **Creating releases via the API is not possible (403)** – write
  the release text (English) and the owner publishes it: tag `vX.Y.Z` on `main`, title
  `Qt Shell X.Y.Z – …`, attach `qt_shell.zip` (zip of the `qt_shell/` folder without `__pycache__`).
- Bump `bl_info["version"]` before building the release zip.
- Release text format: "## What's new since <prev>", sections, "### Known issue" (Scripts dock),
  "## Installation" (4 steps + restart note + "Requires Blender 4.2 or newer. Tested on Blender 5.2.0 LTS, Windows 11.").

---

## 5. Version history

| Version | Release (GitHub) | Main changes |
|---|---|---|
| 0.3.0 | 2026-10-17 | First public version (PySide GUI for Blender) |
| 0.4.0 | 2026-10-17 | Interface size, draggable number fields, English UI |
| 0.5.0 | 2026-10-18 | Fast playback (120+ fps), FPS display, reload crash fixes, dead buttons fix |
| 0.6.0 | (in 0.7.0) | Public Python API, Sidebar (N panel) |
| 0.7.0 | 2026-10-18 | Text editor dock |
| 0.8.0 | 2026-10-18 | Script manager (Unload / Reload, Run Selection Ctrl+Enter, auto-load), API 1.1 ownership, safe start; Scripts dock disabled |
| 0.9.0 | 2026-10-18 | Split 3D viewport (single / side / stacked / quad, Ctrl+Alt+Q), API 1.2 |
| 0.9.1 | 2026-10-19 | Status bar history (click status bar / 🕘), `qs.status_history()` |
| 0.9.2 | 2026-10-19 | Text editor auto-completion; API reference `docs/API.md` |
| 0.9.3 | 2026-10-19 | Light-blue hover / pressed highlight for buttons, fields, lists, menus |
| 0.9.4 | 2026-10-19 | Node editor: Tab node search, Ctrl+Tab groups, wheel zoom fix, F / Home / Numpad . framing |
| 0.10.0 | 2026-10-20 | Transform tools: toolbar (T) + Select / Move / Rotate / Scale / Transform gizmos in every view, Shift+Space tool menu, W = Select; fix: crash on start after closing with a floating window; docs: buttons over the viewport, `examples/viewport_button.py` |
| 0.10.1 | 2026-10-20 | Edit → Qt Preferences… (Qt Shell settings window; startup scripts list replaces the Scripts dock for files) |
| 0.11.0 | 2026-10-20 | Shelf (Maya-like script buttons: drag code from the Text editor, → Shelf, drop .py files; tabs with +, floatable dock; non-modal edit dialog with ▶ Test); floating windows restored after restart |
| 0.12.0 | not released yet | Workspaces like Blender (tabs in the menu bar; add from template / duplicate, rename, reorder, delete, reset; each remembers docks, floating windows, view layout and shading) |
| 0.13.0 | not released yet | Movable viewport toolbar (grip, snaps to edges, horizontal / vertical, Flip, Reset; QSettings `viewport/toolbar_pos`); no saved layout → current workspace's layout is applied; dev reload deletes the old window (fixes reload crash) |
| 0.14.0 | not released yet | Graph editor like Maya (curves, keys, tangents, box select, move, tangent types, infinity, stats boxes, insert / delete keys, scrub); Animation workspace = Graph editor above the Timeline |

---

## 6. Open issues and next steps

### 6.1 Scripts dock is disabled (crash)
`scripts_dock.py` (`ScriptsPanel`, a list of scripts with Run / Reload / Unload / Auto-load checkboxes)
crashed Blender with an access violation in `_win.show()`. Bisect results (2026-10-18):

- empty panel: OK; panel with only a QLabel / only a QTreeWidget / only a QPlainTextEdit: OK;
- toolbar with parentless `QToolButton`s added via `lay.addLayout(bar)`: crash → fixed by parenting
  (toolbar alone then OK);
- toolbar + tree together: still crashed; next planned test was the tree **without its signal
  connections** (`t_noconn`) – not done.
- Afterwards it turned out that Blender **also crashed without the panel** because the **saved window
  layout** (QSettings `state`) had become broken during the debug runs – fixed by *safe start*.
  → The panel crash may partly have been the broken saved layout. **Re-test the parented panel with a
  clean layout first** before bisecting further.

Until then, scripts are managed from the Text editor and the Console (`qt_shell.scripts`, see `docs/API.md` §11).

- Note: the Scripts dock crash happened at the same place (`show()`) as the floating-dock crash found on
  2026-10-20 – the saved layouts during the 2026-10-18 debugging may have contained floating docks.

### 6.2 Ideas / not done
- Make Links (Blender's F in the Node editor) – F is now "frame all" as the owner asked.
- `examples/viewport_button.py` was written but **not run in Blender yet** – test it.
- Viewport buttons are added only to the views visible when the script runs (no "layout changed" event in the API) – could add an event `"layout"`.
- Known harmless log noise: `AttributeError: 'ActionSlot' object has no attribute 'name'` in old log
  entries (fixed in 0.5.0, still in the log file).

### 6.3 State of the owner's PC (2026-10-20)
- Add-on folder has the current `main` (0.14.0). Graph editor tested on the owner's animated Cube: channels, A framing,
  S insert key, drag key (snapped to frame 40), Linear / Stepped tangents, 4× Ctrl+Z back to the original, box select,
  Animation workspace (Reset to Template) = Graph editor above the Timeline. Not tested yet: tangent handle drag,
  MMB move, Alt pan/zoom, Infinity, Frame/Value boxes, Delete keys. Existing Animation workspaces keep their saved
  layout – *Reset to Template* (right click the tab) shows the Graph editor.
- 0.13.0: Movable toolbar tested: drag to the middle, snap to the top
  (horizontal), snap to the right (vertical), tool buttons still work, right click → Reset Position.
- 0.12.0: Workspaces tested by clicks: Modeling, Shading, Scripting,
  Layout, + → UV Editing, right click → Delete; quit + restart restores the current workspace. Animation tab not clicked (overlay).
- Add-on folder had 0.11.0 before. Shelf tested (Cube button, drag code → new Monkey button – left on the owner's shelf as an example). Qt Preferences window still not opened in a test.
- Auto-load file was configured: `C:\Users\uzivatel\Documents\qt_start.py` (switches to Four Views);
  the owner asked how to remove it, so it may have been removed since – check with `qt_shell.scripts.managed_files()`.
- Test file left in `%TEMP%\qs_viewport_button.py` (same as the example; deleting files on the device
  needs permission).

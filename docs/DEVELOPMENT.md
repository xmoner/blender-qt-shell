# Qt Shell – development notes and status

> Start with `CLAUDE.md` in the repo root (workflow, owner's preferences, checklist, current state).

Where the project is, how it is built, tested and released, and what is still open.
Keep this file up to date at the end of every work session.

- **Repository:** https://github.com/xmoner/blender-qt-shell (branch `main`)
- **Current version:** 0.36.0 (`qt_shell/__init__.py` → `bl_info["version"]`), Python API 1.6
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

- **Blender 5.x multilayer EXR = multi-part file**: one part per render pass. With OpenImageIO loop `inp.seek_subimage(i, 0)` over all parts, otherwise you only get the first pass (Combined).

- **Testing with a floated dock:** `devreload` / closing the window saves the layout (`state`) – with a floated dock the owner's next Qt Shell start comes up with it floating. Dock it back (`setFloating(False)`) before every reload.

- **Outliner selection sync vs. drag:** don't rewrite the tree selection while a mouse button is down in it – Qt only starts a drag when the pressed row is still selected. `Outliner.sync_selection` postpones itself (`_sync_pending`) until release / drop.
- **QMenu:** checkable actions with an icon show no check mark, and `addSection` text is not drawn in the Fusion style – use `QWidgetAction` rows (`outliner._check_item`, `_section`).

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
- **Restore the saved dock layout only after the window is shown.** Even with no floating docks, `restoreState()` before
  the first `show()` crashed Qt on Windows (17:54, 2026-10-20), while the same call at run time (workspace switch)
  never did. `MainWindow.__init__` now only restores the geometry; `_restore_saved_layout()` runs via
  `QTimer.singleShot(0)` after `show()`. Tested: quit + start with a saved layout OK.
- **Don't re-float docks during shutdown.** 2026-10-20 15:39: crash in `show()` at the next start after closing
  with a floating Text editor; `Workspaces.capture()` had docked + re-floated it while the window was closing.
  Now `shutdown()` collects floating geometry first and `workspaces.shutdown(floating)` captures without re-floating.
- **No Python event filter on the QApplication.** The first Python-tooltip version installed one; after a dev
  reload `notify()` received a `QMoveEvent` as the *receiver* (stale PySide wrappers, hundreds of
  "Error calling Python override of QApplication::notify()") and key events stopped working. Hook into the
  existing `app._notify_with_context` instead (it already runs for every event) and never keep events alive
  in tracebacks. Also: `QtGui.Qt.mightBeRichText`, not `QtCore.Qt`.
- **Re-adding docks (`_reset_layout`) can grow the window** past the screen. Workspace switches remember the
  window geometry and put it back (`workspaces.fit_to_screen`); templates set dock widths with `resizeDocks`.
- **Annotations are not in Blender's offscreen drawing** (`GPUOffScreen.draw_view3d` leaves them out, checked
  2026-10-22) – Qt Shell draws `scene.annotation` itself (`annotate.paint_annotations`, numpy projection). In 5.2
  `bpy.data.annotations` is the legacy *Annotation* type (layers: `info` not `name`, `frames.new`, `strokes.new`,
  `points.add`, `point.co`, stroke `display_mode` 3DSPACE / SCREEN with SCREEN in % of the region from the
  bottom left), while `bpy.data.grease_pencils` is GP v3 (`frame.drawing.add_strokes`). An empty
  `bpy.data.annotations` collection is falsy – `annotations or grease_pencils` silently picks the wrong one.
  Rulers (Measure) are strokes of 2 / 3 points in the layer `RulerData3D`, like Blender's.
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
  annotate.py (3D view tools Annotate / Measure / Add + their tool header), render_view.py (Render View – Blender's render window, toolbar Sample / Annotate), selshape.py (selection shapes: box / circle / lasso), outliner.py, wirepick.py (line picking: bones, rig controls, curves), posetransform.py (pose G/R/S, clear, select), keying.py (insert / delete keys of the selection, curve filter), playcache.py (cached playback, image mode + settings), keymap.py (all shortcuts, key matching, tooltip templates, navigation scheme), shortcuts_window.py (Keyboard Shortcuts window), geocache.py (geometry cache + own GPU drawing), timeline.py (Timeline: TimeBar zoom / keys / markers, RangeSlider, menus, playback with loop modes, frame rate), console.py, node_editor.py, uv_editor.py
  text_editor.py     Text editor dock (Run Script, Run Selection, Unload, auto-complete)
  completion.py      auto-completion logic (no Qt)
  scripts.py         script manager core (no Qt)
  scripts_dock.py    Scripts dock UI – NOT USED (disabled, see 6.1)
  shelf.py           Shelf (dock 'shelf' at the top, floatable) – buttons run code via scripts._execute; config/qt_shell/shelves.json
  blicons_more.py    the rest of Blender's icon names (extend() called at the end of blicons.py); list of names: bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items
  blicons.py         icons for Blender's icon names (has / icon); TAB_ICONS, DATA_ICONS; theme.type_icon uses it for the Outliner
  icons.py           own SVG icon set (icons.icon / pixmap / set_icon); falls back to the old text glyphs when QtSvg is missing
  pytips.py          Python tooltips: widgets/actions carry the command in Qt property "qtshell_python" (tag / tag_op / tag_prop); app._notify_with_context calls pytips.handle() for QEvent.ToolTip; QSettings interface/python_tooltips; Shift+MMB → pytips.copy_on_click() (also from app.notify) copies the command
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
- Release text format (current): tag + title in one code block; body with `## New` / `## Fixes` /
  `## Improvements` and `## Install` – see `CLAUDE.md`.

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
| 0.15.0 | 2026-10-20 | Python tooltips (Qt Preferences → Interface): command of operators, properties, menu items and Qt Shell's own buttons in the tooltip |
| 0.15.1 | not released yet | Fix: crash on start after closing with a floating window (workspaces re-floated docks during shutdown); Graph editor scripting API `qt_shell.api.graph_editor()` with working tooltip commands; Shift + middle click copies commands |
| 0.15.2 | not released yet | Fix: crash on start – the saved dock layout is restored after the first show() (MainWindow._restore_saved_layout) |
| 0.16.0 | not released yet | 3D view header like Blender 5.2 (menus per mode from VIEW3D_MT_editor_menus, orientation, pivot, snap, proportional, object types, gizmo, overlays, X-ray; mode menu per object type; wheel-scroll); navigation gizmo like Blender (± axes, click to align / flip, drag to orbit, zoom / pan / camera / persp buttons) |
| 0.17.0 | not released yet | Own icon set (qt_shell/icons.py, SVG rendered with QtSvg; text glyph fallback) in the 3D view header, mode menu, toolbar, nav gizmo and Timeline; window icon = logo; logo files in docs/logo |
| 0.18.0 | not released yet | Icons for Blender icon names (blicons.py: 347 names / 177 drawings – objects orange, data green, modifiers & constraints blue): menus, submenus, operator buttons, popovers, Properties tabs, Outliner; FakeLayout.menu / popover / operator_menu_enum now record `icon` |
| 0.19.0 | not released yet | All 1,032 Blender 5.2 icon names covered (blicons_more.py: keys/events, colour tags & sets, node sockets, IPO & falloff curves, mouse, text alignment, key & handle types, editors, modes, file browser, sequencer…); icons on prop toggles and enum buttons / combos. Qt SVG Tiny: no dominant-baseline, no hsl(), defs before use |
| 0.19.1 | not released yet | Add Modifier: the menu's Search… searches only modifiers (MenuSearch for wm.search_single_menu, flattens the menu tree, path labels like "Generate ▸ Subdivision Surface"); the Add button has a parent and the modifier/constraint stack is not rebuilt while its menu is open; constraint menu has icons. Lesson: Blender's Search… items in menus are wm.search_single_menu with menu_idname, not the global operator search |
| 0.19.2 | not released yet | Tooltips in Properties (and every panel drawn from RNA): bold property name + description on the field, its label and vector components (rna_widgets.prop_tooltip / set_prop_tooltip in make_binding); Properties tabs show their full name as a tooltip. Python Tooltips add the command below |
| 0.20.0 | not released yet | Rigs: Pose-mode click / Shift-click / box selection of bones by their custom shapes (rig controls) or bone lines (wirepick.py: numpy projection of the shape mesh with Blender's custom-shape matrix pose_mat·T·R·S(scale×length), distance to edges, point-in-triangle, depth order); Object mode hits curves and armatures by their lines too. Outliner rewritten like View Layer mode: children from other collections greyed under the parent, lazy object contents (data → bone hierarchy + materials, Modifiers, Constraints, Vertex Groups), bone selection / hide, modifier toggles, Expand/Collapse All. Pose bone selection is part of the selection snapshot (app.py). Lessons: Blender 5.x selection/hide are on PoseBone; making a hidden QTreeWidget row current scrolls → expands all parents; reuse of a stagedPath in device_commit_files can write an older copy — use a fresh folder per commit |
| 0.21.0 | not released yet | Pose mode transforms (posetransform.py): G / R / S with axis keys, numbers, Esc/RMB cancel; Move / Rotate / Scale / Transform gizmos at the median of the selected bone heads; world X @ start matrix → ob.convert_space(POSE→LOCAL) → channels in the bone's rotation mode (Euler compatible with the start value, quaternion sign kept), locked channels and connected bones' location kept, only root bones of a selected chain transformed; auto-keying of the changed channels; undo. Pose shortcuts: Alt+G/R/S clear, A / Alt+A / Ctrl+I, H / Shift+H / Alt+H, View Selected frames the bones, right-click = VIEW3D_MT_pose_context_menu |
| 0.22.0 | not released yet | File → Open Recent (like Maya's Recent Files): up to 20 files, newest first, numbered (&1…&10), file name (+ folder when names repeat), full path tooltip, missing files greyed, Clear Recent Files List; Ctrl+Shift+O opens it at the cursor. Qt Shell keeps its own history (CONFIG/qt_shell_recent.txt, load_post + save_post handlers, 30 entries) merged with Blender's recent-files.txt. qt_ui.QT_MENUS: menus filled by Qt. Lesson: TOPBAR_MT_file_open_recent has no Python class in Blender 5.2 (C menu) – fake_ui.find_menu_class returns None, so such menus need a Qt filler |
| 0.23.0 | not released yet | Keying rig controls (keying.py): I / Alt+I in the viewport insert / delete loc-rot-scale keys of the selection (selected pose bones in Pose mode, objects otherwise); Timeline +◆ Key / −◆ key the selected bones (were keying the armature object); Graph editor S / +◆ inserts the **current** (posed) value (was fc.evaluate → the key never moved); in Pose mode the Graph editor and the Timeline show only the selected bones' curves / keys, channels labelled `bone: X Rotation` |
| 0.24.0 | not released yet | Object mode: clicking a rig control (bone custom shape) enters Pose mode and selects that bone, like selecting a control in Maya (Qt Preferences → Interface → Animation, QSettings `animation/click_control_enters_pose`, default on) – before, the click selected the armature object and I keyed the object, so nothing moved in playback. I reports what was keyed (`Keyed 1 bone at frame 20: God`). Status bar shows the running Qt Shell version (tells whether Blender was restarted after an update). Lesson: after *Install from Disk* over a running Qt Shell, Blender keeps the old modules – restart Blender |
| 0.25.0 | not released yet | Cached playback like Maya (playcache.py): every rendered viewport frame is stored with the view's signature (size, matrices, shading, overlays); playback shows stored frames without frame_set (hub.display_frame, the scene frame is set to the last shown frame on stop); Timeline: green line of cached frames, Cache toggle + menu (Cache All Frames, Flush Cache, Memory Limit 256 MB–8 GB, default 1 GB, QSettings playback/cache, playback/cache_mb). Invalidation: bridge.Flags.edit_version (+1 in depsgraph_update_post – not called on frame changes –, undo, load) or a view change. ~5–6 MB per frame at 1400×630 |
| 0.26.0 | not released yet | Background caching (Timeline → Auto, also in the Cache menu; QSettings playback/cache_auto, default off): a 40 ms QTimer waits until the scene and views are unchanged for 0.6 s (edit_version + view signatures), no mouse button / popup / modal / G-R-S, not RENDERED shading; then renders missing frames of the range for ≈35 ms per step (frame_set → render_frame of each view → store), restores the scene frame, the views' images and Flags.depsgraph (frame hops don't refresh the UI). Rig 1–40: full cache in ~3–4 s, refills ~3 s after an edit |
| 0.26.1 | not released yet | Fix: with background caching on, moving animated objects / controls didn't stick – the cache's frame hops re-evaluate F-curves and threw away unkeyed changes. Background caching now waits while any animated property differs from its F-curve at the current frame (playcache.pending_edits; drivers / muted curves ignored). Auto Key in Qt property fields (rna_widgets._autokey: like Blender's UI, only properties that are already animated). Object-mode G/R/S auto-key location + rotation + scale (Blender's default key channels). Lesson: never change the scene frame behind the user's back while unkeyed animated values exist |
| 0.27.0 | not released yet | Geometry playback cache (geocache.py, default cache mode; Images mode kept): per frame the evaluated meshes (world matrix; corner positions + normals only for deformed objects, own topology when a modifier changes it), and rig controls as world-space line segments with bone colours; drawn by Qt Shell into the viewport offscreen with its own GPU shader (create_from_info: studio-like 2-light solid shading, Material / Object / Single / Random / Texture colour modes – Texture samples the image feeding Base Color through any nodes, else the active / first colour Image Texture node, active UV map) + POLYLINE_SMOOTH_COLOR for controls (In Front respected) + Qt floor grid → the camera can move during cached playback. Background caching only evaluates (frame_set + capture, no render): rig 1–40 ≈ 2.5 MB/frame, filled in ~3 s. Cache validity now also includes an animation signature (crc of all keys, throttled 4×/s) – edits evaluated by an immediate frame_set (Graph editor) never reach depsgraph_update_post. Lessons: never replace a shared base mesh when topology changes between frames; Blender's Texture mode image ≠ first TEX_IMAGE node |
| 0.33.2 | released | Properties: the tab column (properties.TabColumn) was a QListWidget with a fixed 96 px width, no horizontal scroll bar and elided names. Now it sits in a QSplitter with the page: width fits the longest name by default, can be dragged (QSettings `properties/tab_width`, unscaled px), is kept on every resize (`_apply_width` – setSizes at the first show alone was undone because the dock is still narrow then), names are not elided and both scroll bars appear when needed |
| 0.34.0 | released | Tools like Blender's toolbars. 3D view (gizmo.TOOLS + annotate.py): **Annotate** (Annotate / Line / Polygon / Eraser – strokes in `scene.annotation`, placement 3D Cursor / View / Surface from `tool_settings.annotation_stroke_placement_view3d`, drawn by Qt), **Measure** (rulers / protractors in layer `RulerData3D`, surface placement via `scene.ray_cast`, Ctrl = nearest vertex of the hit face, X / Del / Backspace removes – key `view3d.ruler_remove`, always consumed so it never deletes objects), **Add** Cube / Cone / Cylinder / UV Sphere / Ico Sphere (Object Mode only; base on the surface or grid, height along the normal, mesh built with bmesh and sized in the mesh data; options Orientation / Base / Aspect / Height in QSettings `viewport/add_*`). Tool header `annotate.ToolHeader` in the 3D header (colour, thickness, placement, eraser radius / Add options / Measure hint). Toolbar groups separated by a line; Shift+Space keys D / M / A; keymap `view3d.tool_annotate / tool_measure / tool_add` (no default key). Render View: left toolbar (T) Sample / Annotate (4 variants, per-slot strokes in image pixels, own undo stack – Ctrl+Z), header colour / thickness / clear, Gizmos (navigation gizmo zoom / pan) and Overlays toggles (QSettings `render_view/*`). New icons: tool_annotate(_line/_polygon/_eraser), tool_measure, tool_add_cube/cone/cylinder/uvsphere/icosphere, tool_sample, toolbar. API 1.5: `api.set_tool / active_tool / TOOLS`, Render View `set_tool`, `add_annotation`, `annotations`, `clear_annotations`, `undo_annotation`, `set_annotation_style`, `set_overlays`, `set_gizmos`, `set_toolbar`. Tested live (synthetic events + real mouse): all annotate variants, eraser split, ruler → protractor → remove (X kept the objects), Add Cube / Cylinder / Ico Sphere sizes, Render View annotate / erase / undo |
| 0.35.0 | released | Timeline: keys can be selected (click, Shift, Shift + drag range, A / Alt+A), moved by dragging (whole frames, live re-evaluation via `frame_set(frame_current)` like the Graph editor, keys of the same curve on the target frame are removed on release, Esc / RMB cancels, one undo step) and deleted (X / Del) – keymap `timeline.delete_keys / select_all / deselect_all`, ShortcutOverride so they win over window shortcuts while the Timeline has focus. The Timeline now shows the keys of all selected objects (`timeline.timeline_curves`, selection via `select_get()` – `context.selected_objects` is missing right after `read_homefile`). Frame rate button with Blender's presets (fps / fps_base, e.g. 29.97 = 30 / 1.001) and Custom; sets `scene.render.fps`, refreshes Properties and re-times running playback; the label follows changes made in Properties. Tested live: move 10→15, merge onto 20, undo, range select + X, scrub, 25 / 29.97 / 60 fps (Properties → Output showed 60 fps), render.fps changed in Python → button followed |
| 0.36.0 | not released yet | Timeline rework (Blender Timeline + Maya Time / Range Slider, timeline.py rewritten around the cache code): TimeBar has its own view range (`view`, None = play range + margin; wheel zoom at the mouse, Ctrl/Shift+wheel and MMB pan, Ctrl+MMB zoom, Home, Num+/-, follow during playback), RangeSlider (Maya) under it (ends zoom, middle pans, extent frozen during a drag), ruler with frames or seconds (`frame_text`), playhead box, keys by keyframe type (KEY_TYPES colours / sizes, most important type per frame), markers band (`scene.timeline_markers`: add / select / drag / rename / delete / jump), key context menu (interpolation, keyframe type, snap, copy / paste – `keyframe_points.insert(f, v)`; with `options={'REPLACE'}` it returns None when no key exists – , preview range, markers), menus View / Marker / Playback / Keying, transport with step frame and play backwards, loop modes LOOP / ONCE / OSCILLATE (`_next_frame` for Play Every Frame, `_frame_at` for real-time sync), preview range toggle (Start / End edit `frame_preview_*`; cached playback / Cache All use `play_range()`). **Blender resets the other preview end when one is set while the preview range is off** – `set_preview_range` turns it on first. 20 new keymap actions (`timeline.*`, window `play_reverse` Ctrl+Shift+Space, `frame_prev/next` Alt+, / Alt+.). Icons play_reverse, frame_prev / next, preview_range, loop_*, marker. API 1.6 `api.timeline()`. Settings `timeline/*` (loop_mode, show_seconds, show_markers, follow). Tested live: zoom / pan / range slider / Home (synthetic + real wheel and real slider drag), key type, interpolation, copy / paste, Up / Right / Shift+Right, marker add / drag / jump, preview range from keys, loop sequences, Play Once / backwards |

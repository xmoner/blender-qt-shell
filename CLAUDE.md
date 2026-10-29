# CLAUDE.md – start here (Qt Shell)

Short handoff for the next session. Read this first, then `docs/DEVELOPMENT.md` (architecture, lessons
learned, version history, open issues) and `docs/API.md` (public Python API) only for the part you need.
Don't dig through old chat history.

## Project
- **Qt Shell** – Blender add-on that replaces Blender's UI with a PySide6 (Qt) window.
  Repo: `github.com/xmoner/blender-qt-shell`, branch `main`, add-on code in `qt_shell/`.
- Target: **Blender 5.2 LTS, Windows 11** (owner's PC). `bl_info` minimum 4.2.
- Current version: see `bl_info["version"]` in `qt_shell/__init__.py` (0.63.2 on 2026-10-29; the status bar shows the running version).

## Owner's preferences (always)
- **Reply in Czech.** Code, comments, docs, commit messages and release notes in **English**.
- Do the work directly; ask only when something can't be undone or the request is really unclear.
- After every finished feature/fix, offer a **GitHub release text** (the owner publishes releases himself):
  give `Tag: vX.Y.Z` + `Title: Qt Shell X.Y.Z – <short name>` in one code block and the body
  (Markdown, English: `## New` / `## Fixes` / `## Improvements`, then `## Install`) in a second one.
  Install section: *Download `qt_shell.zip`, then in Blender 5.2: Edit → Preferences → Add-ons → Install from Disk.*
- After an update tell the owner to **restart Blender** (Install from Disk over a running Qt Shell keeps the
  old modules). The status bar shows `Qt Shell X.Y.Z` – ask him to check it when something "doesn't work".
- The owner's Blender may be open with his own work – **never reload / quit / click in it**.
  Test in a **separate Blender instance** that you start and close yourself without saving.

## Checklist after each change
1. Edit in `/home/claude/blender-qt-shell` (clone it if missing).
2. Check every changed file: `python3 /tmp/claude-0/chk.py <files>` – syntax + undefined names
   (recreate it from §Tools below if `/tmp` was wiped; `__file__` is a false positive).
3. Deploy to the PC (see below) and **test live** in a test Blender instance.
4. Bump `bl_info["version"]` (fix = patch, feature = minor).
   **Deploy the bumped `qt_shell/__init__.py` to the PC too** – otherwise the owner's status bar keeps showing
   the old version after a restart (the test only deployed the changed modules).
5. Docs:
   - `README.md` **and** `qt_shell/README.md` – same feature rows, keep them in sync;
   - `docs/DEVELOPMENT.md` – new row in §5 version history (+ lessons learned, file list in §3 for new modules);
   - push `docs/DEVELOPMENT.md` (and this file if changed) to the claude.ai project with
     `Projects project_write` (`path: docs/DEVELOPMENT.md`, `local_path: …`).
6. Commit + `git push origin main`. Commit message ends with the two attribution lines the session gives
   (`Co-Authored-By: …` and `Claude-Session: …`).
7. Zip: `rm -f /mnt/user-data/outputs/qt_shell.zip && zip -qr /mnt/user-data/outputs/qt_shell.zip qt_shell -x '*__pycache__*'`,
   send it with `SendUserFile`.
8. Reply in Czech: what was wrong / what's new, what was tested, what wasn't; then the release text.

## Deploy and test on the owner's PC (linked computer)
- Add-on folder on the PC:
  `C:\Users\uzivatel\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\qt_shell\`
- Copy changed files to a **new unique folder** `/mnt/user-data/outputs/<name>_<n>/` and send them with
  `device_commit_files` (`force: true`). **Never reuse a staging folder** – it can deliver an older copy.
  If behaviour looks unchanged, check the file on the PC (e.g. `'<new name>' in open(module.__file__).read()`).
- Start a test Blender: `computer_open_application` with
  `c:\program files\blender foundation\blender 5.2\blender.exe` (this always starts a **new** instance).
  Qt Shell starts automatically. Open the Console tab (bottom bar) for Python.
- Reload code inside that instance: Console → `import qt_shell.devreload as _r; _r.go()`.
- Open a test file from the Console: `bpy.ops.wm.open_mainfile(filepath=r'…')`.
  Rig for tests: `C:\Users\uzivatel\Downloads\TOAnimate Robot Rig V1.6\TOAnimate Robot Rig V1.6\TOAnimate-Robot_Rig.blend`.
- Close the test instance without saving: Console → `import os; os._exit(0)`.
- The Blender MCP tools (`execute_blender_code…`) don't work here (no server / no `blender` on PATH).
  To inspect data, write a small script into the add-on folder, run it from the Console, have it write
  JSON next to itself and `device_stage_files` the JSON.

### Computer-use gotchas
- The **Claude app window covers the top-right of the screen** while it works – clicks there don't reach
  Blender, and `zoom` there can show a stale image. Drive things from the Console instead, or float a
  dock out of the way (`dock.setFloating(True); dock.setGeometry(…)`).
  **Dock it back (`setFloating(False)`) before `devreload` or closing** – the reload saves the window layout to the
  shared settings and the owner's Qt Shell then starts with that dock floating.
- Screenshot coordinates ≠ Qt coordinates (Windows scaling 125 %, screenshot downscaled). For precise
  hit tests compute positions in Qt (e.g. project points) instead of guessing pixels.
- After typing in the Console, keyboard focus stays there: to send a key to another widget use
  `QTimer.singleShot(500, lambda: widget.setFocus())`, then `computer_key`.
- Console input line is at about y = 739 (screenshot frame 1456×819) when the Console tab is open.
- `left_mouse_down` / `left_mouse_up` in `computer_batch` do **not** move the cursor – `mouse_move` to the start point
  first, otherwise the press lands wherever the cursor was (e.g. the Console) and the drag goes nowhere.
- `computer_type` pastes via clipboard (no key handlers); use `computer_key` for shortcuts.
- Access grants expire after ~30 min of inactivity – request again.
- `computer_open_application` always starts a **new** Blender – never use it to bring a test instance to the front
  (a Windows notification can steal the foreground: grant "File Explorer" click access and click the Blender window).
- Before quitting a Blender with `os._exit`, make sure it is **yours**: check its process uptime in the Console
  (`GetProcessTimes` via ctypes – set `kernel32.GetCurrentProcess.restype = wintypes.HANDLE`, otherwise the call
  fails and returns 0; a few seconds/minutes = the instance you just started).

## Where things are (quick map)
- `main_window.py` – window, menus, 3D header, docks, `special_op` (operators handled in Qt), searches.
- `viewport.py` – offscreen 3D view, navigation (EEVEE draws 1 sample while anything moves – `eevee_samples` + `bridge.quiet_updates`, full samples when settled; optional `nav_scale` / second offscreen `_off_nav`), selection, interactive G/R/S (`start_modal` …).
- `gizmo.py` – toolbar (tools + variants: Select Tweak/Box/Circle/Lasso, Cursor, Scale/Scale Cage) + transform gizmos
  (`pivot()` per mode, `cage_bounds()`, plane handles 'G:XY' …; modal `axis` X/Y/Z or plane YZ/XZ/XY via Shift+X/Y/Z); `selshape.py` – selection shapes used by all box/circle/lasso selection.
- `editmesh.py` (Edit Mesh), `posetransform.py` (Pose G/R/S, clear, select), `keying.py` (keys of the
  selection: I / Alt+I, Timeline, Graph editor filter), `playcache.py` (cached playback, image mode), `geocache.py` (geometry cache drawn with our own
  GPU shader – camera-independent), `wirepick.py`
  (picking bones / rig controls / curves by their lines).
- `render_view.py` – Render View (Blender's render window: slots, channels, toolbar Sample / Annotate, save; F12 / F11).
- `anim_player.py` – Render → View Animation (Ctrl+F11): rendered frames with a timeline (Qt, owned by the main window).
- `dockable.py` – `Dockable` mixin: Render View / Animation Player as a window or a dock (released before the layout is saved).
- `bluepencil.py` – Blue Pencil (2D drawings keyed on frames, Blue Pencil 2 style): data in the scene ID property, BPTools per view, Timeline ticks, retiming, panel dock.
- `burnin.py` – Blue Pencil / annotations burnt into renders (Render View, `overlay` folder), Viewport Render / playblast.
- `annotate.py` – 3D view tools Annotate / Measure / Add (drawn by Qt – offscreen drawing has no annotations) + `ToolHeader`.
- `snap.py` – snapping of the Qt G / R / S and gizmo drags (header Snap settings, Ctrl inverts, snap marker).
- `menufind.py` – Help → Search (like Maya): menu items, tabs, buttons and operators of the whole window.
- `propedit.py` – Edit Property dialog (Blender's `wm.properties_edit` only works from its own invoke dialog).
- `outliner.py`, `properties.py`, `rna_widgets.py` (RNA → Qt widgets, tooltips), `qt_ui.py`
  (Blender layouts/menus → Qt, `LazyMenu`), `fake_ui.py` (records Blender `draw()` calls).
- `timeline.py` – Timeline (TimeBar: zoom / keys / markers, RangeSlider, menus, loop modes, preview range, fps).
- `text_editor.py` – Text editor with IDE features (tabs, live checks, outline, find / replace, line tools, quick help); `console.py` – Python console, traceback lines are links.
- `graph_editor.py`, `node_editor.py`, `uv_editor.py` (UV editor Maya + Blender: Snap of the UVs of all `uv_objects()` – multi-object, per-face object index, UV Toolkit, Blender UV ops via `uv_context()` – the hidden timeline area switched to UV for a moment), `uvchecker.py` (its Checker map drawn on the mesh in the 3D view, own GPU pass after `draw_view3d`).
- `icons.py` (own icons), `blicons.py` + `blicons_more.py` (all 1,032 Blender icon names).
- `keymap.py` – all shortcuts (registry, `hit`, templates, Blender/Maya 3D View key sets via `profile`),
  `shortcuts_window.py` – `ShortcutsPanel` (Keyboard Shortcuts window + Qt Preferences → Shortcuts page).
- `app.py` – hub, timers, selection snapshot, `notify` (tooltips, Shift+MMB copy).
- `shelf.py` (Shelf dock, `bl:NAME` icons, code runs in a 3D view context, look = QSettings `shelf/*` from Qt Preferences → Shelf, save / load shelf files `export_shelves` / `import_shelves`) + `shelf_presets.py` (built-in shelves Polygons / Modeling / Modifiers / UV / Rigging / Animation / Rendering, added once – the owner's shelves.json is shared, never overwrite it).
- `repeat.py` – Repeat Last (Maya G / Blender Shift+R): viewport G/R/S specs, `bridge.run_op` operators, shelf buttons; Repeat Last Command (Maya Shift+G) skips G/R/S.
- `api.py` – public API (`docs/API.md`). `devreload.py` – dev reload.

## Rules learned the hard way (details in DEVELOPMENT.md §2)
- Give every Qt widget a parent; no app-level Python `eventFilter` (use `app._notify_with_context`).
- Never `activateWindow()` on hover directly – use `app.hover_activate(widget)` (it pushed other windows behind Qt Shell).
- Restore saved window state only **after** the first `show()`; never re-float docks during shutdown.
- Blender 5.x: pose selection/hide live on `PoseBone`; F-curves via
  `bpy_extras.anim_utils.action_get_channelbag_for_slot`.
- Qt: making a hidden tree row current expands all its parents (autoscroll) – check visibility first.
- New shortcuts: add an action to `keymap.py` and test it with `keymap.hit(id, ev)`; any text that mentions
  a key must be a template (`keymap.tip(widget, "… ({area.action})")` / `keymap.render`) – never a literal key.
- Settings (QSettings "QtShell") are shared with the owner's Blender – reset what a test changes
  (the owner's active tool is whatever `viewport/tool` holds – read it before a test and put it back (was BLUE_PENCIL / TRANSFORM on 2026-10-24 – the owner uses Blue Pencil, his `bluepencil/*` settings are shared too: snapshot them to a file before a test); the owner uses navigation scheme **MAYA**; key overrides live in `keymap/<id>` and `keymap_maya/<id>`).
- Renders start from a hidden helper Blender window (cancel = close it); after closing any Blender window call
  `bridge.restore_gpu_context()` (+ `hold_gpu`) or the next viewport draw crashes (no GPU context). The helper is
  hidden, not minimized: its Image Editor is captured for the live Render View picture.
- When the owner's Blender is open, also grant `blender.exe` (resolve "blender.exe") – otherwise the test instance is masked
  in screenshots; check the uptime before typing anything into a Blender.
- Never let Blender's own modal transform run (transform macros like mesh.extrude_region_move invoked from menus, or Python ops that invoke them) – it crashes in the hidden 3D view; `special_op` turns them into the operator + Qt G/R/S.
- `draw_view3d` renders all EEVEE viewport samples per call – keep `viewport.eevee_samples(1)` for interactive frames; a scene setting changed from Python needs `depsgraph.update()` before drawing sees it.
- Never change the scene frame behind the user's back while animated values are unkeyed (frame_set
  re-evaluates F-curves and drops the change) – see `playcache.pending_edits`.
- Qt SVG Tiny: no `dominant-baseline`, no `hsl()`, `<defs>` before use.
- Some Blender menus are C-only (no Python class, e.g. `TOPBAR_MT_file_open_recent`) – fill them in Qt via `qt_ui.QT_MENUS`.
- Granting computer access: resolve **"Blender 5.2"** (→ `blender-launcher.exe`, works for `computer_open_application` and the started Blender); the full blender.exe path may report "not installed", the name "Blender" resolves to an old 4.3 install.

## Open ideas / next steps
- Pose mode: rotate twice (R R) trackball, local axes on double axis key, IK-heavy rigs not tested.
- Pose-mode header menus/tools still come from Blender's own menus – check them on a rig.
- Scripts dock disabled (see DEVELOPMENT.md §6.1).
- Graph editor: tangent handle drag, MMB move, Infinity, Frame/Value boxes not tested live.
- Leftover debug files on the PC: `qt_shell\_inspect.py`, `_inspect.json`, `_ol_research.py`, `_ol_research.json`,
  `_rv_probe.py`, `_rv_probe5.py`–`_rv_probe8.py`, `_rv_bg.py`, `_rv_probe.json`, `_rv_shot_*.png`,
  `_ann_probe.py`, `_ann_probe2.py`, `_ann_probe3.py`, `_t034.py`, `_t034.json`, `_t034_*.png`, `_t035.py`, `_t035.json`, `_t035_*.png`, `_t036.py`, `_t036.json`, `_t036_*.png`, `_t037.py`, `_t037.json`, `_t037_player.png`, `_t038.py`, `_t038.json`, `_t038_player.png`, `_t039.py`, `_t039.json`, `_t039_*.png`, `_t040.py`, `_t040.json`, `_t040_player.png`, `_t041.py`, `_t041.json`, `_t041_docked.png`, `_t042.py`, `_t042.json`, `_t042_player.png`, `_rc_probe.py`, `_rc_probe.json`, `_t043.py`, `_t043.json`, `_t044*.py`, `_t044*.json`, `_t044_*.png`, `_diag.txt`, `_diag_shot.png`, `_t045.py`, `_t045b.py`, `_t045*.json`, `_t045_*.png`, `_t046.py`, `_t046.json`, `_t046_*.png`, `_t047.py`, `_t047.json`, `_t047_snap.json`, `_t047_*.png`, `_t048.py`, `_t048.json`, `_t048_snap.json`, `_t048_*.png`, `_t049.py`, `_t049.json`, `_t049_*.png`, `_t050.py`, `_t050.json`, `_t050_*.png`, `_t051.py`, `_t051.json`, `_t052.py`, `_t052.json`, `_t052_*.png`, `_t053.py`, `_t053.json`, `_t053_*.png`, `_t053_src.py`, `_t054.py`, `_t054.json`, `_t054_popup.png`, `_t055.py`, `_t055.json`, `_t055_view.png`, `_t056.py`, `_t056.json`, `_t056_*.png`, `_t057.py`, `_t057.json`, `_t057_*.png`, `_t058.py`, `_t058.json`, `_t058_pose.png`, `_t059.py`, `_t059.json`, `_t059_*.png`, `_t060.py`, `_t060.json`, `_t061.py`, `_t061.json`, `_t061_*.png`, `_t062.py`, `_t062.json`, `_t062_*.png`, `_t063.py`, `_t063.json`, `_t063_world.png`, `_t064.py`, `_t064.json`, `_t065.py`, `_t065.json`, `_t066.py`, `_t066.json`, `_t066_*.png`, `_t067.py`, `_t067.json`, `_t068.py`, `_t068.json`, `_t068_*.png`, `_t068_probe*.png`, `_t069.py`, `_t069.json`, `_t070.py`, `_t070.json`, `_t071.py`, `_t071.json`, `_t071_a.py`, `_t071_b.py`, `_t071_c.py`, `_t072.py`, `_t072.json`, `_t073.py`, `_t073.json`, `_t074.py`, `_t074.json`, `_t075.py`, `_t076.py`, `_t077.py`, `_t077.json`, `_t078.py`, `_t078.json`, `_t079.py`, `_t079.json`, `_t080.py`, `_t080.json`, `_t081.py`, `_t081.json`, `_t081_one.json`, `_t081_all.json`, `_t082.py`, `_t082.json`, `_t083.py`–`_t100.py`, `_t092_native.py`, `_t095_native.py`, `_t098_native.py`, `_t099_native.py`, `_t083.json`–`_t100.json`, `_t087_*.png`, `_t100_*.png`, `_test_window.py`, `C:\tmp\playblast` (test playblast), `_turtle_*`, `_qt_shell_turtle.blend`
  (deleting needs the owner's permission).
- Outliner: drag & drop and restriction columns tested with synthetic mouse input; Ctrl / middle-mouse drag variants not tested live.

## Tools
`/tmp/claude-0/chk.py` (syntax + undefined-name check):
```python
import ast, builtins, sys
for p in sys.argv[1:]:
    tree = ast.parse(open(p).read())
    defined = set(dir(builtins))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)): defined.add(n.name)
        elif isinstance(n, ast.Import): defined |= {a.asname or a.name.split('.')[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom): defined |= {a.asname or a.name for a in n.names}
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)): defined.add(n.id)
        elif isinstance(n, ast.arg): defined.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name: defined.add(n.name)
    used = {(n.id, n.lineno) for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    bad = sorted((l, i) for i, l in used if i not in defined)
    print(p, bad or "ok")
```

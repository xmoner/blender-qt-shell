# CLAUDE.md – start here (Qt Shell)

Short handoff for the next session. Read this first, then `docs/DEVELOPMENT.md` (architecture, lessons
learned, version history, open issues) and `docs/API.md` (public Python API) only for the part you need.
Don't dig through old chat history.

## Project
- **Qt Shell** – Blender add-on that replaces Blender's UI with a PySide6 (Qt) window.
  Repo: `github.com/xmoner/blender-qt-shell`, branch `main`, add-on code in `qt_shell/`.
- Target: **Blender 5.2 LTS, Windows 11** (owner's PC). `bl_info` minimum 4.2.
- Current version: see `bl_info["version"]` in `qt_shell/__init__.py` (0.33.1 on 2026-10-21; the status bar shows the running version).

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
- `viewport.py` – offscreen 3D view, navigation, selection, interactive G/R/S (`start_modal` …).
- `gizmo.py` – toolbar (tools + variants: Select Tweak/Box/Circle/Lasso, Cursor, Scale/Scale Cage) + transform gizmos
  (`pivot()` per mode, `cage_bounds()`); `selshape.py` – selection shapes used by all box/circle/lasso selection.
- `editmesh.py` (Edit Mesh), `posetransform.py` (Pose G/R/S, clear, select), `keying.py` (keys of the
  selection: I / Alt+I, Timeline, Graph editor filter), `playcache.py` (cached playback, image mode), `geocache.py` (geometry cache drawn with our own
  GPU shader – camera-independent), `wirepick.py`
  (picking bones / rig controls / curves by their lines).
- `render_view.py` – Render View (Blender's render window: slots, channels, sampling, save; F12 / F11).
- `outliner.py`, `properties.py`, `rna_widgets.py` (RNA → Qt widgets, tooltips), `qt_ui.py`
  (Blender layouts/menus → Qt, `LazyMenu`), `fake_ui.py` (records Blender `draw()` calls).
- `graph_editor.py`, `timeline.py`, `node_editor.py`, `uv_editor.py`, `text_editor.py`, `console.py`.
- `icons.py` (own icons), `blicons.py` + `blicons_more.py` (all 1,032 Blender icon names).
- `keymap.py` – all shortcuts (registry, `hit`, templates, Blender/Maya 3D View key sets via `profile`),
  `shortcuts_window.py` – `ShortcutsPanel` (Keyboard Shortcuts window + Qt Preferences → Shortcuts page).
- `app.py` – hub, timers, selection snapshot, `notify` (tooltips, Shift+MMB copy).
- `api.py` – public API (`docs/API.md`). `devreload.py` – dev reload.

## Rules learned the hard way (details in DEVELOPMENT.md §2)
- Give every Qt widget a parent; no app-level Python `eventFilter` (use `app._notify_with_context`).
- Restore saved window state only **after** the first `show()`; never re-float docks during shutdown.
- Blender 5.x: pose selection/hide live on `PoseBone`; F-curves via
  `bpy_extras.anim_utils.action_get_channelbag_for_slot`.
- Qt: making a hidden tree row current expands all its parents (autoscroll) – check visibility first.
- New shortcuts: add an action to `keymap.py` and test it with `keymap.hit(id, ev)`; any text that mentions
  a key must be a template (`keymap.tip(widget, "… ({area.action})")` / `keymap.render`) – never a literal key.
- Settings (QSettings "QtShell") are shared with the owner's Blender – reset what a test changes
  (the owner's active tool was **MOVE**; the owner uses navigation scheme **MAYA**; key overrides live in `keymap/<id>` and `keymap_maya/<id>`).
- Never change the scene frame behind the user's back while animated values are unkeyed (frame_set
  re-evaluates F-curves and drops the change) – see `playcache.pending_edits`.
- Qt SVG Tiny: no `dominant-baseline`, no `hsl()`, `<defs>` before use.
- Some Blender menus are C-only (no Python class, e.g. `TOPBAR_MT_file_open_recent`) – fill them in Qt via `qt_ui.QT_MENUS`.
- Granting computer access: resolve Blender by its **full path** (`c:\\program files\\blender foundation\\blender 5.2\\blender.exe`), the name "Blender" resolves to an old 4.3 install.

## Open ideas / next steps
- Pose mode: rotate twice (R R) trackball, local axes on double axis key, IK-heavy rigs not tested.
- Pose-mode header menus/tools still come from Blender's own menus – check them on a rig.
- Scripts dock disabled (see DEVELOPMENT.md §6.1).
- Graph editor: tangent handle drag, MMB move, Infinity, Frame/Value boxes not tested live.
- Leftover debug files on the PC: `qt_shell\_inspect.py`, `_inspect.json`, `_ol_research.py`, `_ol_research.json`,
  `_rv_probe.py`, `_rv_probe5.py`–`_rv_probe8.py`, `_rv_bg.py`, `_rv_probe.json`, `_rv_shot_*.png`
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

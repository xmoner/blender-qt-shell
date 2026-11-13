"""Blender's own 3D viewport inside the Qt view (Qt Preferences → Viewport → Blender's viewport).

The Qt view draws Blender's scene offscreen and adds its own overlays, gizmos and navigation. Sculpting
through it (sculpt.py) goes through Python and the offscreen drawing can't show Multires levels or Dynamic
Topology. For Blender's speed and behaviour a helper Blender window (`wm.window_new`) with one 3D view is
embedded into the Qt view (QWindow.fromWinId + createWindowContainer – the GHOST window becomes a child
window). Blender draws it and handles its mouse / keys itself (strokes, brush cursor, selection, tools,
navigation of the active keyconfig, undo). The camera goes over when entering and comes back when leaving;
then the window is closed.

When it is used – QSettings `viewport/blender_view`:
  "sculpt" (default)  in Sculpt Mode only (the paint modes paint in the Qt view – sculpt.py's strokes)
  "paint"             in Sculpt Mode and the paint modes (Vertex / Weight / Texture Paint – Blender's brush cursor)
  "always"            in every mode
  "never"             never (Sculpt Mode then uses sculpt.py's Qt strokes)

While it is active, `bridge.find_view3d` returns its area, so the Qt header, menus and panels act on the
visible view; interactive operators (G / R / S, extrude …) run as Blender's own modal operators there.
"""
import math
import sys
import time

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge

KEY = "viewport/blender_view"
CHOICES = (("sculpt", "Sculpt Mode only"), ("paint", "Sculpt and Paint modes"), ("always", "Always (every mode)"), ("never", "Never (Qt Shell's view)"))
TAG = "qtshell_view"     # ID property on the helper window's screen: found again after a file is loaded
# modes that use Blender's view with the "paint" setting: sculpting and painting (strokes, brush cursor)
NATIVE_MODES = ("SCULPT", "PAINT_VERTEX", "PAINT_WEIGHT", "PAINT_TEXTURE")
SHELF_KEY = "viewport/asset_shelf"   # Blender's asset shelf (bottom of the view: brushes in Sculpt Mode …) shown


class _Signals(QtCore.QObject):
    asset_shelf = QtCore.Signal(bool)


signals = _Signals()

_views = {}             # Qt view → NativeView embedded in it (one per visible view of a split layout)
_timer = None
_watch = None           # checks for Blender's own playback started in the embedded view, follows the active view
_reasons = set()        # why Blender's views are hidden for a while (the Qt views shown): "playback", "bluepencil",
#                         "seqsolo" (the Video Sequencer plays with Timeline + 3D - Off: views frozen)
_bp_handle = None       # draw handler showing Blue Pencil drawings in Blender's view
_bp_tex = {}            # space pointer → (key, GPUTexture) of the drawings last drawn there
_bp_version = 0         # bumped when drawings / Blue Pencil settings change
_tool_state = None      # the tool state whose changes are watched (Blue Pencil tool on / off)


# ---------------------------------------------------------------- setting
def setting():
    v = str(QtCore.QSettings("QtShell", "QtShell").value(KEY, "sculpt") or "sculpt")
    return v if v in dict(CHOICES) else "sculpt"


def set_setting(value):
    if value not in dict(CHOICES):
        return
    QtCore.QSettings("QtShell", "QtShell").setValue(KEY, value)
    QtCore.QTimer.singleShot(0, sync)


def wanted(mode=None):
    s = setting()
    if s == "always":
        return True
    if s == "never":
        return False
    try:
        mode = mode or bpy.context.mode
    except Exception:
        return False
    return mode == "SCULPT" if s == "sculpt" else mode in NATIVE_MODES


# ---------------------------------------------------------------- asset shelf
def asset_shelf_on():
    v = QtCore.QSettings("QtShell", "QtShell").value(SHELF_KEY, True)
    return v not in (False, "false", "0", 0)


def set_asset_shelf(on, apply=True):
    on = bool(on)
    if on == asset_shelf_on():
        return
    QtCore.QSettings("QtShell", "QtShell").setValue(SHELF_KEY, on)
    if apply:
        for v in _all():
            v.apply_regions()
    signals.asset_shelf.emit(on)


def toggle_asset_shelf():
    set_asset_shelf(not asset_shelf_on())
    from . import app
    try:
        app._win.statusBar().showMessage(f"Asset Shelf {'shown' if asset_shelf_on() else 'hidden'}.", 2500)
    except Exception:
        pass


# ---------------------------------------------------------------- state
def _all():
    return list(_views.values())


def _cur():
    """The NativeView of the active Qt view (the one the header and menus act on), else any."""
    from . import app
    try:
        vp = app._win.viewport
    except Exception:
        vp = None
    v = _views.get(vp)
    if v is None and _views:
        v = next(iter(_views.values()))
    return v


def active(vp=None):
    if vp is None:
        return any(not v.stale for v in _views.values())
    v = _views.get(vp)
    return v is not None and not v.stale


def covers(vp=None):
    """Blender's view is embedded and shown over the Qt view (not while the Qt view is used for a while:
    cached playback, drawing with Blue Pencil)."""
    return active(vp) and not _reasons


def _set_reason(name, on):
    """The Qt views for a while (cached playback, Blue Pencil drawing) – Blender's views hidden while any reason
    holds, shown again with the Qt views' cameras when none is left."""
    if not _views:
        _reasons.clear()
        return
    before = bool(_reasons)
    if on:
        _reasons.add(name)
    else:
        _reasons.discard(name)
    after = bool(_reasons)
    if before == after:
        return
    focus = name != "seqsolo"     # the Video Sequencer keeps the keyboard (Space stops its playback)
    for v in _all():
        if v.stale:
            continue
        try:
            if after:
                v.suspend(focus=focus)
            else:
                v.resume()
        except Exception as ex:
            bridge.log(f"Blender's viewport: switching to the Qt view failed ({ex})", "WARNING")
    bridge.preferred_view3d = None if after else _preferred
    if after and focus:
        _focus_qt()
    _timeline_update()


def _focus_qt():
    """The keyboard to the active Qt view (Space stops playback there, Blue Pencil keys …)."""
    from . import app
    try:
        vp = app._win.viewport
        vp.setFocus()
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.SetFocus(int(vp.window().winId()))
    except Exception:
        pass


def _timeline_update():
    """Blue Pencil's frame ticks in the Timeline also show while Blender's view is shown – repaint it; the 3D
    header's Brushes (asset shelf) button shows only then."""
    from . import app
    try:
        app._win.timeline.bar.update()
    except Exception:
        pass
    try:
        app._win._sync_header()
    except Exception:
        pass


def bp_check(*_args):
    """The Blue Pencil tool draws in the Qt view (its tools, cursor and panel work there): Blender's views are
    hidden while the tool is active."""
    try:
        from . import bluepencil
        on = bluepencil.tool_active()
    except Exception:
        on = False
    _set_reason("bluepencil", on)


# ---------------------------------------------------------------- cached playback
def playback(on):
    """Timeline playback started / stopped. With the playback cache on, the Qt views play (from the cache –
    Blender's own view would evaluate the scene every frame): Blender's views are hidden meanwhile and come back,
    with the cameras of the Qt views, when playback stops."""
    from . import playcache
    _set_reason("playback", bool(on) and playcache.enabled())


def _watch_tick():
    _hover_focus()
    _track_active()
    _watch_playback()


_hovered = None         # the NativeView under the mouse at the last tick


def _hover_focus():
    """Like Qt Shell's own views (and Blender): the keyboard goes to the view under the mouse – Blender's view
    gets the Win32 focus when the mouse enters it (no Qt event tells Qt about that), unless text is being
    typed in a Qt field, a popup / dialog is open or a button is held."""
    global _hovered
    if sys.platform != "win32" or not _views or _reasons:
        _hovered = None
        return
    try:
        pos = QtGui.QCursor.pos()
        hit = None
        for v in _all():
            c = v.container
            if not v.stale and c.isVisible() and c.rect().contains(c.mapFromGlobal(pos)):
                hit = v
                break
        if hit is _hovered:
            return
        _hovered = hit
        if hit is None:
            return
        if QtWidgets.QApplication.activePopupWidget() is not None or \
                QtWidgets.QApplication.activeModalWidget() is not None:
            return
        if QtGui.QGuiApplication.mouseButtons() != QtCore.Qt.NoButton:
            return
        fw = QtWidgets.QApplication.focusWidget()
        typing = isinstance(fw, QtWidgets.QLineEdit) and fw.text() and not isinstance(
            fw.parent(), QtWidgets.QAbstractSpinBox)
        if typing or isinstance(fw, (QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)):
            return
        import ctypes
        u = ctypes.windll.user32
        top = int(hit.vp.window().winId())
        if u.GetForegroundWindow() != top:
            return                       # another program / window in front – leave it
        f = u.GetFocus()
        if f != hit.hwnd and not u.IsChild(hit.hwnd, f):
            u.SetFocus(hit.hwnd)
        # Blender sends key events to its active window only – a child window gets no WM_ACTIVATE of its own
        # (a click activates it inside Blender, hovering doesn't): tell it, like the click would
        u.SendMessageW(hit.hwnd, 0x0006, 1, 0)          # WM_ACTIVATE, WA_ACTIVE
    except Exception:
        pass


def _track_active():
    """A click into one of Blender's views makes its Qt view the active one (no Qt event reaches Qt there)."""
    if sys.platform != "win32" or len(_views) < 2:
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        f = u.GetFocus()
        if not f:
            return
        for vp, v in list(_views.items()):
            if f == v.hwnd or u.IsChild(v.hwnd, f):
                area = getattr(vp, "area", None)
                if area is not None and area.active is not vp:
                    area.set_active(vp)
                return
    except Exception:
        pass


def _watch_playback():
    """Space pressed in Blender's view starts Blender's own playback (no cache) – with the playback cache on,
    it is handed to the Qt Timeline instead."""
    if not _views or _reasons or bridge.op_depth or any(v.stale for v in _all()):
        return
    from . import app, playcache
    if not playcache.enabled() or app._win is None:
        return
    try:
        playing = [w for w in bpy.context.window_manager.windows
                   if w.screen is not None and w.screen.is_animation_playing]
    except Exception:
        return
    if not playing:
        return
    seq = getattr(app._win, "sequencer", None)
    try:
        if seq is not None and seq.owns_blender_playback():
            return                       # the Video Sequencer's playback (its Play / Space in its preview)
    except Exception:
        pass
    w = playing[0]
    try:
        with bpy.context.temp_override(window=w, screen=w.screen):
            bpy.ops.screen.animation_cancel(restore_frame=False)
    except Exception as ex:
        bridge.log(f"Blender's viewport: stopping Blender's playback failed ({ex})", "WARNING")
        return
    tl = getattr(app._win, "timeline", None)
    if tl is not None and not tl.is_playing():
        tl.play()


def start(win):
    """Starts the check that keeps the embedded views in line with the setting, the mode, the layout, file loads."""
    global _timer
    if _timer is not None:
        try:
            _timer.stop()
        except RuntimeError:
            pass
    _timer = QtCore.QTimer(win)
    _timer.setInterval(1000)
    _timer.timeout.connect(sync)
    _timer.start()
    global _watch
    if _watch is not None:
        try:
            _watch.stop()
        except RuntimeError:
            pass
    _watch = QtCore.QTimer(win)
    _watch.setInterval(100)
    _watch.timeout.connect(_watch_tick)
    _watch.start()
    global _tool_state, _bp_handle
    try:
        from . import gizmo, bluepencil
        ts = gizmo.tool_state(win.hub)
        if ts is not _tool_state:
            ts.changed.connect(bp_check)
            _tool_state = ts
            bluepencil.signals.changed.connect(_bp_changed)
            bluepencil.settings().changed.connect(_bp_changed)
    except Exception as ex:
        bridge.log(f"Blender's viewport: Blue Pencil not connected ({ex})", "WARNING")
    if _bp_handle is None:
        _bp_handle = bpy.types.SpaceView3D.draw_handler_add(_bp_draw, (), "WINDOW", "POST_PIXEL")
    QtCore.QTimer.singleShot(0, sync)


def stop():
    global _timer, _watch
    for t in (_timer, _watch):
        if t is not None:
            try:
                t.stop()
            except RuntimeError:
                pass
    _timer = _watch = None
    leave()
    if hasattr(bpy.types, "QTSHELL_OT_view_key"):
        try:
            bpy.utils.unregister_class(QTSHELL_OT_view_key)
        except Exception:
            pass
    global _bp_handle
    if _bp_handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_bp_handle, "WINDOW")
        except Exception:
            pass
        _bp_handle = None
    _bp_tex.clear()


def layout_changing():
    """The Qt views are about to be moved into other splitters (Viewport Layout): Blender's windows are taken out
    first – re-parenting a widget with an embedded native window is not safe – and embedded again afterwards."""
    if _views:
        leave()
    QtCore.QTimer.singleShot(0, sync)


def sync(vp=None):
    """Embeds / removes Blender's views as the setting, the mode and the visible Qt views want it."""
    from . import app
    win = app._win
    if win is None:
        return
    try:
        if bridge.op_depth or getattr(win, "_rendering", False) or getattr(win, "_render_win", None) is not None:
            return
        for q, v in list(_views.items()):
            if v.stale or not v.alive() or v.area() is None:
                leave(q, camera=v.area() is not None and not v.stale)    # a file was loaded: start over
        _close_stale_windows()
        area = getattr(win, "viewports", None)
        shown = area.visible_views() if area is not None else [win.viewport]
        targets = shown if wanted() else []
        for q in list(_views):
            if q not in targets:
                leave(q)
        new = False
        for q in targets:
            if q not in _views and enter(q):
                new = True
        if new:
            bp_check()
            _timeline_update()
        if not _reasons:
            for v in _all():
                v.apply_regions()
            _sync_shading()
    except Exception as ex:
        bridge.log(f"Blender's viewport: {ex}", "WARNING")


def _sync_shading():
    """The Qt header changes the shading of the active view – the other embedded views follow (the Qt views
    share one shading too)."""
    if len(_views) < 2:
        return
    src = _cur()
    sp = src.space() if src is not None else None
    if sp is None:
        return
    for v in _all():
        if v is src:
            continue
        dst = v.space()
        if dst is None:
            continue
        try:
            with v.context():
                _copy_props(sp.shading, dst.shading)
                _copy_props(sp.overlay, dst.overlay)
        except Exception:
            pass


def enter(vp):
    """Embeds Blender's 3D view into `vp` (Qt view). False if it can't be done."""
    v = _views.get(vp)
    if v is not None:
        if v.alive() and not v.stale:
            return True
        leave(vp)
    try:
        v = NativeView(vp)
    except Exception as ex:
        bridge.log(f"Blender's own 3D view could not be embedded ({ex}) – using the Qt view.", "WARNING")
        return False
    first = not _views
    _views[vp] = v
    if _reasons:
        v.suspend()                      # the Qt views are in use (playback, Blue Pencil) – shown later
    else:
        bridge.preferred_view3d = _preferred
    if first:
        _add_keys()
    return True


def leave(vp=None, camera=True):
    """The camera and the shading back to the Qt view(s), Blender's window(s) closed. vp None: all."""
    items = [(vp, _views.pop(vp))] if vp in _views else ([] if vp is not None else list(_views.items()))
    if vp is None:
        _views.clear()
    if _reasons:
        camera = False                   # the Qt views already have the cameras (cached playback, Blue Pencil)
    for _q, v in items:
        _bp_tex.pop(getattr(v, "space_ptr", None), None)
        v.close(camera=camera)
    if not _views:
        bridge.preferred_view3d = None
        _remove_keys()
        _reasons.clear()
        _bp_tex.clear()
    if items:
        _timeline_update()


def _preferred():
    v = _cur()
    if v is None or v.stale or not v.alive():
        return None
    area = v.area()
    if area is None:
        return None
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    return (v.window(), area, region) if region is not None else None


def _close_stale_windows():
    """Helper windows saved in a .blend (file saved while the view was embedded) – closed after loading."""
    from . import app
    wm = bpy.context.window_manager
    wins = list(wm.windows)
    mine = {v.ptr for v in _all()}
    for i, w in enumerate(wins):
        if i == 0 or w.as_pointer() in mine:
            continue
        try:
            tagged = w.screen is not None and w.screen.get(TAG)
        except Exception:
            tagged = False
        if tagged and app._win is not None:
            app._win.close_blender_window(w)


@bpy.app.handlers.persistent
def _on_load_pre(*_args):
    for v in _all():
        v.stale = True                   # its area / window may be freed – touched again only by sync()
    bridge.preferred_view3d = None


def register_handlers():
    lst = bpy.app.handlers.load_pre
    for old in [f for f in lst if getattr(f, "__name__", "") == "_on_load_pre"
                and getattr(f, "__module__", "") == __name__]:
        lst.remove(old)
    lst.append(_on_load_pre)


def unregister_handlers():
    lst = bpy.app.handlers.load_pre
    for old in [f for f in lst if getattr(f, "__name__", "") == "_on_load_pre"
                and getattr(f, "__module__", "") == __name__]:
        lst.remove(old)


# ---------------------------------------------------------------- Qt Shell keys inside Blender's view
# Blender's view has the keyboard while the mouse works in it, so Qt Shell's own shortcuts never reach Qt
# there. These actions get temporary keymap items (the keys set in Qt Shell) that hand them back to Qt.
FORWARD = ("view3d.mode_object", "view3d.mode_edit", "view3d.mode_pose", "view3d.mode_sculpt",
           "view3d.mode_weight_paint", "view3d.mode_vertex_paint", "view3d.mode_texture_paint", "view3d.mode_menu",
           "view3d.asset_shelf")
_km_items = []          # (keymap, keymap item) added while Blender's view is embedded

_KEY_NAMES = {"0": "ZERO", "1": "ONE", "2": "TWO", "3": "THREE", "4": "FOUR", "5": "FIVE", "6": "SIX",
              "7": "SEVEN", "8": "EIGHT", "9": "NINE", "TAB": "TAB", "SPACE": "SPACE", "`": "ACCENT_GRAVE",
              "-": "MINUS", "=": "EQUAL", "HOME": "HOME", "END": "END", "DEL": "DEL", "DELETE": "DEL",
              "INS": "INSERT", "INSERT": "INSERT", "PGUP": "PAGE_UP", "PGDOWN": "PAGE_DOWN",
              "BACKSPACE": "BACK_SPACE", "RETURN": "RET", "ENTER": "RET", ",": "COMMA", ".": "PERIOD",
              "/": "SLASH", ";": "SEMI_COLON", "'": "QUOTE", "[": "LEFT_BRACKET", "]": "RIGHT_BRACKET",
              "\\": "BACK_SLASH"}


def _blender_key(qt_key):
    """'Alt+1' → ('ONE', ctrl, shift, alt) for a keymap item; None for keys Blender's keymap can't take."""
    parts = [p for p in str(qt_key).replace(" ", "").split("+") if p]
    if not parts:
        return None
    mods = {p.lower() for p in parts[:-1]}
    k = parts[-1].upper()
    if k in _KEY_NAMES:
        t = _KEY_NAMES[k]
    elif len(k) == 1 and "A" <= k <= "Z":
        t = k
    elif k.startswith("F") and k[1:].isdigit() and 1 <= int(k[1:]) <= 24:
        t = k
    else:
        return None
    if mods - {"ctrl", "shift", "alt"}:
        return None
    return t, "ctrl" in mods, "shift" in mods, "alt" in mods


class QTSHELL_OT_view_key(bpy.types.Operator):
    """A Qt Shell shortcut pressed in Blender's own 3D view"""
    bl_idname = "qtshell.view_key"
    bl_label = "Qt Shell Shortcut"
    bl_options = {"INTERNAL"}

    action: bpy.props.StringProperty()

    def execute(self, context):
        # later, from Qt: switching the mode may close this very window (Blender's view of Sculpt Mode)
        QtCore.QTimer.singleShot(0, lambda a=self.action: _run_action(a))
        return {"FINISHED"}


def _run_action(aid):
    from . import app
    mw = app._win
    if mw is None:
        return
    try:
        if aid == "view3d.mode_menu":
            mw.mode_menu()
        elif aid == "view3d.asset_shelf":
            toggle_asset_shelf()
        elif aid.startswith("view3d.mode_"):
            from .viewport import _MODE_KEYS
            mode = _MODE_KEYS.get(aid[len("view3d.mode_"):])
            if mode:
                mw.switch_mode(mode)
    except Exception as ex:
        bridge.log(f"{aid}: {ex}", "WARNING")


def _add_keys():
    _remove_keys()
    from . import keymap
    try:
        if not hasattr(bpy.types, "QTSHELL_OT_view_key"):
            bpy.utils.register_class(QTSHELL_OT_view_key)
        kc = bpy.context.window_manager.keyconfigs.addon
        if kc is None:
            return
        km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
        for aid in FORWARD:
            for k in keymap.keys(aid):
                bk = _blender_key(k)
                if bk is None:
                    continue
                t, ctrl, shift, alt = bk
                kmi = km.keymap_items.new("qtshell.view_key", t, "PRESS", ctrl=ctrl, shift=shift, alt=alt)
                kmi.properties.action = aid
                _km_items.append((km, kmi))
    except Exception as ex:
        bridge.log(f"Blender's viewport: Qt Shell keys not added ({ex})", "WARNING")


def _remove_keys():
    while _km_items:
        km, kmi = _km_items.pop()
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass


# ---------------------------------------------------------------- input
def qt_pressed(obj):
    """A mouse press on a Qt widget: Windows keeps the keyboard focus on an embedded Blender window (a
    native child) even when a Qt widget gets Qt's focus – give the Win32 focus back to the Qt window."""
    if not _views or sys.platform != "win32":
        return
    try:
        w = obj.window() if isinstance(obj, QtWidgets.QWidget) else None
    except Exception:
        w = None
    if w is None:
        return
    import ctypes
    user32 = ctypes.windll.user32
    try:
        f = user32.GetFocus()
        if f and any(f == v.hwnd or user32.IsChild(v.hwnd, f) for v in _all()):
            user32.SetFocus(int(w.winId()))
    except Exception:
        pass


def focus_view():
    """Keyboard focus to the active embedded Blender window (its modal operators read keys from there)."""
    v = _cur()
    if v is None:
        return
    try:
        v.container.setFocus()
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.SetFocus(v.hwnd)
    except Exception:
        pass


def invoke(idname, props):
    """Runs an interactive operator (G / R / S, extrude, bevel …) as Blender's own modal operator in the
    active embedded view. False when it couldn't be started (the caller then uses Qt Shell's version)."""
    ctx = _preferred()
    if ctx is None:
        return False
    win, area, region = ctx
    try:
        mod, name = idname.split(".", 1)
        op = getattr(getattr(bpy.ops, mod), name)
        focus_view()
        with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
            res = op("INVOKE_DEFAULT", True, **(props or {}))
        return "CANCELLED" not in res
    except Exception as ex:
        bridge.log(f"{idname}: {ex}", "WARNING")
        return False


# ---------------------------------------------------------------- Blue Pencil drawings in Blender's view
def _bp_changed(*_args):
    global _bp_version
    _bp_version += 1
    for v in _all():
        if v.stale:
            continue
        try:
            a = v.area()
            if a is not None:
                a.tag_redraw()
        except Exception:
            pass


def _bp_rect(region, rv, w, h):
    """(camera name or "", frame rect in region pixels – top-down like Qt) of Blender's view."""
    sc = bpy.context.scene
    full = QtCore.QRectF(0, 0, w, h)
    cam = sc.camera
    if rv is None or rv.view_perspective != "CAMERA" or cam is None:
        return "", full
    if cam.type != "CAMERA":
        return cam.name, full
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    try:
        pts = [location_3d_to_region_2d(region, rv, cam.matrix_world @ q) for q in cam.data.view_frame(scene=sc)]
    except Exception:
        return cam.name, full
    if any(q is None for q in pts):
        return cam.name, full
    xs = [q.x for q in pts]
    ys = [h - q.y for q in pts]
    r = QtCore.QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    return cam.name, (r if r.width() > 4 and r.height() > 4 else full)


def _bp_draw():
    """POST_PIXEL draw handler: the Blue Pencil layers of the view / camera drawn over Blender's view (painted
    by Qt into an image – the same drawing as in the Qt view – shown as a texture)."""
    if not _views or _reasons:
        return
    ctx = bpy.context
    sp = ctx.space_data
    if sp is None:
        return
    sptr = sp.as_pointer()
    if not any(v.space_ptr == sptr and not v.stale for v in _all()):
        return
    try:
        from . import bluepencil as bp
        if not bp.settings().show:
            return
        region, rv = ctx.region, ctx.region_data
        w, h = region.width, region.height
        if w < 4 or h < 4:
            return
        cam, rect = _bp_rect(region, rv, w, h)
        if not bp.has_drawings(cam):
            return
        f = bp.current_frame()
        raw = ctx.scene.get(bp.PROP)
        key = (w, h, cam, round(rect.x(), 1), round(rect.y(), 1), round(rect.width(), 1), round(rect.height(), 1),
               f, _bp_version, hash(raw) if isinstance(raw, str) else 0,
               bool(getattr(bp._hub(), "playing", False)))
        got = _bp_tex.get(sptr)
        if got is None or got[0] != key:
            img = QtGui.QImage(w, h, QtGui.QImage.Format_RGBA8888_Premultiplied)
            img.fill(0)
            p = QtGui.QPainter(img)
            try:
                bp.paint_layers(p, cam, rect, f, space="VIEWPORT")
            finally:
                p.end()
            img = img.mirrored(False, True)          # GPU rows go bottom-up
            import gpu
            import numpy as np
            arr = np.frombuffer(img.constBits(), dtype=np.uint8, count=w * h * 4).astype(np.float32)
            arr *= 1.0 / 255.0
            buf = gpu.types.Buffer("FLOAT", w * h * 4, arr)
            got = (key, gpu.types.GPUTexture((w, h), format="RGBA8", data=buf))
            _bp_tex[sptr] = got
        import gpu
        from gpu_extras.presets import draw_texture_2d
        gpu.state.blend_set("ALPHA_PREMULT")
        draw_texture_2d(got[1], (0, 0), w, h)
        gpu.state.blend_set("NONE")
    except Exception as ex:
        _bp_tex.pop(sptr, None)
        bridge.log(f"Blender's viewport: Blue Pencil drawing failed ({ex})", "WARNING")


def resized(vp):
    v = _views.get(vp)
    if v is not None:
        v.fit()


def _copy_props(src, dst):
    for p in src.bl_rna.properties:
        pid = p.identifier
        if pid == "rna_type" or p.is_readonly or p.type in ("POINTER", "COLLECTION"):
            continue
        try:
            v = getattr(src, pid)
            if getattr(dst, pid) != v:
                setattr(dst, pid, v)
        except Exception:
            pass


class NativeView:
    def __init__(self, vp):
        from . import native, app
        self.vp = vp
        self.stale = False
        self._born = time.monotonic()
        self._shelf_applied = None
        self._shelf_mode = None
        self._shelf_set_at = 0.0
        wm = bpy.context.window_manager
        before = {w.as_pointer() for w in wm.windows}
        native_before = set(native.ghost_windows())
        main_sp = self._main_space()
        with bridge.blender_context():
            bpy.ops.wm.window_new()
        new = [w for w in wm.windows if w.as_pointer() not in before]
        if not new:
            raise RuntimeError("no new Blender window")
        self.ptr = new[0].as_pointer()
        hwnds = [h for h in native.ghost_windows() if h not in native_before]
        if not hwnds:
            self._close_window()
            raise RuntimeError("no native window handle")
        self.hwnd = hwnds[0]
        native.hide_windows(hwnds)                 # no flash as a separate window before it is embedded
        win = new[0]
        try:
            win.screen[TAG] = 1
        except Exception:
            pass
        area = max(win.screen.areas, key=lambda a: a.width * a.height)
        area.type = "VIEW_3D"
        self.area_ptr = area.as_pointer()
        self.space_ptr = area.spaces.active.as_pointer()
        self._setup_space(vp, main_sp)
        # embed
        self.qwin = QtGui.QWindow.fromWinId(self.hwnd)
        self.container = QtWidgets.QWidget.createWindowContainer(self.qwin, vp)
        self.container.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.fit()
        self.container.show()
        # Blender turns the tool header (and asset shelf) of a Sculpt Mode view back on while it sets up the
        # new window – hide them again once it has drawn (the Sculpt panel has those settings)
        for ms in (200, 800, 2000):
            QtCore.QTimer.singleShot(ms, self.apply_regions)
        try:
            if app._win is not None:
                app._win.activateWindow()
        except Exception:
            pass

    # ---- lookups (never keep Blender structs: a file load can free them)
    def window(self):
        for w in bpy.context.window_manager.windows:
            if w.as_pointer() == self.ptr:
                return w
        return None

    def alive(self):
        try:
            return self.window() is not None
        except Exception:
            return False

    def area(self):
        if self.stale:
            return None
        try:
            w = self.window()
            if w is None or w.screen is None:
                return None
            for a in w.screen.areas:
                if a.as_pointer() == self.area_ptr and a.type == "VIEW_3D":
                    return a
        except Exception:
            pass
        return None

    def space(self):
        a = self.area()
        return a.spaces.active if a is not None else None

    def _main_space(self):
        """The hidden 3D view the Qt view draws with (not this one)."""
        old, bridge.preferred_view3d = bridge.preferred_view3d, None
        try:
            sp, _r = self.vp.space()
            return sp
        except Exception:
            return None
        finally:
            bridge.preferred_view3d = old

    # ---- setup
    def apply_regions(self):
        """Blender's header, sidebar, HUD hidden (Qt Shell has them); its toolbar shown outside Sculpt Mode
        (Blender's tools work there), hidden in Sculpt Mode (the Sculpt panel has the brushes); the asset shelf
        as set (its shortcut / the Sculpt panel) – collapsing or expanding it in Blender itself
        changes that setting."""
        sp = self.space()
        if sp is None:
            return
        try:
            mode = bpy.context.mode
        except Exception:
            mode = ""
        sculpt = mode == "SCULPT"
        cur = getattr(sp, "show_region_asset_shelf", None)
        if cur is not None and getattr(self, "_shelf_applied", None) is not None and self._shelf_mode == mode \
                and cur != self._shelf_applied and time.monotonic() - self._born > 6.0 \
                and time.monotonic() - self._shelf_set_at > 1.5:   # Blender applies our own change on a redraw
            set_asset_shelf(cur, apply=False)              # changed in Blender's view by hand
        shelf = asset_shelf_on()
        want = {"show_region_header": False, "show_region_tool_header": False, "show_region_ui": False,
                "show_region_hud": False, "show_region_asset_shelf": shelf, "show_region_toolbar": not sculpt}
        self._shelf_applied, self._shelf_mode = shelf, mode
        todo = {a: on for a, on in want.items() if hasattr(sp, a) and getattr(sp, a) != on}
        if not todo:
            return
        if "show_region_asset_shelf" in todo:
            self._shelf_set_at = time.monotonic()
        with self.context():               # region updates use the context window (NULL → crash, 2026-11-08)
            for attr, on in todo.items():
                try:
                    setattr(sp, attr, on)
                except Exception:
                    pass
        try:
            self.area().tag_redraw()        # a region shown / hidden takes effect (and reads back) on a redraw
        except Exception:
            pass

    def context(self):
        """temp_override onto the embedded window / area – RNA updates of its space need a context window."""
        w, a = self.window(), self.area()
        kw = {}
        if w is not None:
            kw = dict(window=w, screen=w.screen)
            if a is not None:
                kw["area"] = a
        return bpy.context.temp_override(**kw)

    def _setup_space(self, vp, main_sp):
        sp = self.space()
        self.apply_regions()
        with self.context():
            if main_sp is not None:
                _copy_props(main_sp.shading, sp.shading)
                _copy_props(main_sp.overlay, sp.overlay)
                sp.lens = main_sp.lens
                sp.clip_start = main_sp.clip_start
                sp.clip_end = main_sp.clip_end
            if hasattr(sp.overlay, "show_text"):
                sp.overlay.show_text = True
        self._camera_in()

    def _camera_in(self):
        """The camera of the Qt view → Blender's view."""
        sp, vp = self.space(), self.vp
        if sp is None:
            return
        with self.context():
            rv = sp.region_3d
            w, h = max(vp.width(), 2), max(vp.height(), 2)
            cam_view = bool(getattr(vp, "camera_view", False)) and bpy.context.scene.camera is not None
            if cam_view:
                vp.camera_view = False               # the view behind the camera (Blender keeps it too)
                try:
                    vm, _pm = vp.matrices(w, h)
                finally:
                    vp.camera_view = True
            else:
                vm, _pm = vp.matrices(w, h)
            rv.view_perspective = "ORTHO" if getattr(vp, "ortho", False) else "PERSP"
            rv.view_distance = float(getattr(vp, "dist", 10.0))
            rv.view_matrix = vm
            if cam_view:
                rv.view_perspective = "CAMERA"

    # ---- cached playback: the Qt view for a while
    def suspend(self, focus=True):
        self._back()                             # camera + shading → the Qt view
        bridge.preferred_view3d = None
        try:
            self.container.hide()
        except Exception:
            pass
        vp = self.vp
        if focus:
            try:
                vp.setFocus()                    # Space stops playback in Qt now
                if sys.platform == "win32":
                    import ctypes
                    ctypes.windll.user32.SetFocus(int(vp.window().winId()))
            except Exception:
                pass
        vp.request_redraw()

    def resume(self):
        if not self.alive() or self.area() is None:
            return
        main_sp, sp = self._main_space(), self.space()
        if main_sp is not None:                  # shading changed from the Qt header during playback
            with self.context():
                _copy_props(main_sp.shading, sp.shading)
                _copy_props(main_sp.overlay, sp.overlay)
        self._camera_in()                        # the view may have been moved while playing
        bridge.preferred_view3d = _preferred
        self.fit()
        try:
            self.container.show()
        except Exception:
            pass
        self.apply_regions()

    def fit(self):
        try:
            self.container.setGeometry(self.vp.rect())
        except Exception:
            pass

    # ---- back to the Qt view
    def _back(self):
        sp = self.space()
        if sp is None:
            return
        try:
            rv = sp.region_3d
            vp = self.vp
            vp.target = rv.view_location.copy()
            vp.dist = float(rv.view_distance)
            # view_rotation / view_location / view_distance are current at once (view_matrix only after a draw)
            e = rv.view_rotation.to_euler("XYZ")
            vp.yaw, vp.pitch = e.z, min(max(e.x, 0.0001), math.pi - 0.0001)
            vp.ortho = rv.view_perspective == "ORTHO"
            vp.camera_view = rv.view_perspective == "CAMERA" and bpy.context.scene.camera is not None
        except Exception as ex:
            bridge.log(f"Blender's viewport: view not taken over ({ex})", "WARNING")
        main_sp = self._main_space()             # shading / overlays changed from the Qt header meanwhile
        if main_sp is not None:
            try:
                with bridge.blender_context():
                    _copy_props(sp.shading, main_sp.shading)
                    _copy_props(sp.overlay, main_sp.overlay)
            except Exception as ex:
                bridge.log(f"Blender's viewport: shading not taken over ({ex})", "WARNING")
        try:
            vp.request_redraw()
        except Exception:
            pass

    def _hwnd_ok(self):
        if sys.platform != "win32":
            return True
        try:
            import ctypes
            return bool(ctypes.windll.user32.IsWindow(self.hwnd))
        except Exception:
            return True

    def _close_window(self):
        from . import app
        try:
            w = self.window()
            wins = list(bpy.context.window_manager.windows)
            # after a file load the pointer could belong to another window: only ours (its native window still
            # exists, never Blender's main window)
            if w is not None and app._win is not None and self._hwnd_ok() and wins and w != wins[0]:
                app._win.close_blender_window(w)
        except Exception as ex:
            bridge.log(f"Blender's viewport: closing its window failed ({ex})", "WARNING")

    def close(self, camera=True):
        if camera and not self.stale and self.alive():
            self._back()
        try:
            self.container.hide()
        except Exception:
            pass
        self._close_window()
        try:
            self.container.deleteLater()
        except Exception:
            pass

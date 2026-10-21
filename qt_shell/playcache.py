"""Cached playback (like Maya's Cached Playback).

Every frame a 3D view draws is kept as an image together with the view it was drawn from. While the
scene and the view stay the same, playback shows the stored images instead of evaluating and drawing
the scene again – heavy rigs play in real time after the first pass. The Timeline shows the cached
frames as a green line and has a toggle + menu (Cache Playback, Cache All Frames, Flush Cache).

The cache is dropped automatically when:
- the scene changes (Blender's depsgraph_update_post = an edit, selection, new key …; frame changes
  don't count), undo / redo, a file is loaded  → bridge.Flags.edit_version;
- a view changes (size, camera / navigation, shading, overlays, X-ray) → per-view signature.
Memory is limited (QSettings playback/cache_mb, default 1024 MB); above it new frames are not stored.
"""
import bpy
from PySide6 import QtCore

from . import bridge

KEY_ENABLED = "playback/cache"
KEY_LIMIT = "playback/cache_mb"

_bytes = 0
_full_warned = False


def _settings():
    return QtCore.QSettings("QtShell", "QtShell")


def enabled():
    v = _settings().value(KEY_ENABLED, True)
    return v not in (False, "false", "0", 0)


def set_enabled(on):
    _settings().setValue(KEY_ENABLED, bool(on))
    if not on:
        flush()


def limit_bytes():
    try:
        mb = int(_settings().value(KEY_LIMIT, 1024))
    except (TypeError, ValueError):
        mb = 1024
    return max(64, mb) * 1024 * 1024


def used_mb():
    return _bytes / (1024 * 1024)


# ---------------------------------------------------------------- per view
def _state(vp):
    st = getattr(vp, "_playcache", None)
    if st is None:
        st = {"sig": None, "version": None, "frames": {}}
        vp._playcache = st
    return st


def _drop(st):
    global _bytes
    for img, _t in st["frames"].values():
        _bytes -= img.sizeInBytes()
    st["frames"] = {}
    _bytes = max(_bytes, 0)


def view_signature(vp):
    """Everything that changes the picture apart from the scene: size, camera, shading, overlays."""
    try:
        w, h = vp.width(), vp.height()
        vm, pm = vp.matrices(w, h)
        space, _region = vp.space()
        sh = ov = None
        if space is not None:
            s = space.shading
            o = space.overlay
            sh = (s.type, getattr(s, "light", ""), getattr(s, "color_type", ""), getattr(s, "show_xray", False),
                  getattr(s, "studio_light", ""))
            ov = (o.show_overlays, getattr(o, "show_bones", True), getattr(o, "show_floor", True),
                  getattr(o, "show_extras", True), getattr(o, "show_outline_selected", True),
                  getattr(space, "show_gizmo", True))
        scale = getattr(vp.prefs, "viewport_scale", 1.0) if getattr(vp, "prefs", None) else 1.0
        return (w, h, round(vp.devicePixelRatioF() * scale, 3),
                tuple(round(v, 5) for row in vm for v in row), tuple(round(v, 5) for row in pm for v in row),
                bool(vp.camera_view), sh, ov, bpy.context.scene.name)
    except Exception:
        return None


def _valid(vp, st, sig=None):
    """Drops the view's frames when the scene or the view changed. True when the cache may be used."""
    sig = view_signature(vp) if sig is None else sig
    ver = bridge.Flags.edit_version
    if sig is None:
        _drop(st)
        return False
    if st["sig"] != sig or st["version"] != ver:
        _drop(st)
        st["sig"], st["version"] = sig, ver
    return True


def store(vp, frame, img, transparent):
    """Called after a view rendered `frame`."""
    global _bytes, _full_warned
    if not enabled() or img is None:
        return
    st = _state(vp)
    if not _valid(vp, st):
        return
    old = st["frames"].get(frame)
    if old is not None:
        _bytes -= old[0].sizeInBytes()
    elif _bytes + img.sizeInBytes() > limit_bytes():
        if not _full_warned:
            _full_warned = True
            bridge.log(f"Playback cache is full ({used_mb():.0f} MB) – raise the limit in the Timeline's "
                       "cache menu or flush the cache.", "INFO")
        return
    st["frames"][frame] = (img, transparent)
    _bytes += img.sizeInBytes()


def lookup(vp, frame):
    """(image, transparent) for frame if it is cached for the view as it is now, else None."""
    if not enabled():
        return None
    st = _state(vp)
    if not _valid(vp, st):
        return None
    return st["frames"].get(frame)


def ready(views, frame):
    """True when every view can show `frame` from the cache."""
    return bool(views) and all(lookup(v, frame) is not None for v in views)


def cached_frames(views):
    """Frames cached in every view (for the Timeline line)."""
    if not enabled() or not views:
        return set()
    out = None
    for v in views:
        st = _state(v)
        if not _valid(v, st):
            return set()
        fr = set(st["frames"])
        out = fr if out is None else out & fr
    return out or set()


def flush(views=None):
    """Drops cached frames (all views when views is None)."""
    global _bytes, _full_warned
    _full_warned = False
    if views is None:
        from PySide6 import QtWidgets
        views = [w for w in QtWidgets.QApplication.allWidgets() if hasattr(w, "_playcache")]
    for v in views:
        _drop(_state(v))
    if views is None or not views:
        _bytes = 0

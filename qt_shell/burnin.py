"""Burn-in of Blue Pencil drawings and annotations into rendered images, and the Viewport Render (playblast).

Blender never renders annotations, and Blue Pencil is drawn by Qt Shell only – so after a render Qt Shell
draws them into the pictures itself (Render → Burn In Blue Pencil / Annotations):

- Render Image: the Render View shows the render with the drawings (its View menu / header toggle); Save /
  Save As then saves that picture (PNG, JPEG, TIFF, WebP, BMP). The clean render stays in its slot.
- Render Animation: when the render is done, every output frame is copied with the drawings into the folder
  `overlay` next to the frames (the frames themselves stay untouched); the Animation Player shows either.
- Viewport Render Image / Animation (playblast): the scene drawn like the 3D view (its shading) through the
  scene camera at the render size, with the drawings – the animation goes to the folder `playblast` next to
  the output frames (PNG) and opens in the Animation Player.

Only Blue Pencil layers that belong to the rendering camera are burnt in (View layers have no relation to
the render); annotations are projected through the camera (3D strokes) or placed on the picture (screen
strokes); the Measure tool's ruler layer is left out.
"""
import os
import shutil

import bpy
import numpy as np
from mathutils import Vector
from PySide6 import QtCore, QtGui

from . import bridge

QT_WRITABLE = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}


def _settings():
    return QtCore.QSettings("QtShell", "QtShell")


def enabled():
    return str(_settings().value("render/burn_in", "false")).lower() == "true"


def set_enabled(on):
    _settings().setValue("render/burn_in", "true" if on else "false")
    signals.changed.emit()


class _Signals(QtCore.QObject):
    changed = QtCore.Signal()


signals = _Signals()


# ---------------------------------------------------------------- geometry
def render_size(scene=None):
    r = (scene or bpy.context.scene).render
    pct = r.resolution_percentage / 100.0
    return max(1, int(r.resolution_x * pct)), max(1, int(r.resolution_y * pct))


def camera_mats(scene, cam, w, h):
    """(view matrix, projection matrix) of the scene camera for a picture w × h."""
    r = scene.render
    view = cam.matrix_world.normalized().inverted()
    proj = cam.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(), x=w, y=h,
                                  scale_x=r.pixel_aspect_x, scale_y=r.pixel_aspect_y)
    return view, proj


def _project(co, mats, w, h):
    view, proj = mats
    m = np.array(proj @ view, dtype=np.float64)
    hom = np.c_[co, np.ones(len(co))] @ m.T
    wv = hom[:, 3]
    ok = wv > 1e-6
    wv = np.where(ok, wv, 1.0)
    x = (hom[:, 0] / wv + 1) * 0.5 * w
    y = (1 - hom[:, 1] / wv) * 0.5 * h
    return np.c_[x, y], ok


# ---------------------------------------------------------------- what is drawn
def _bp_layers(scene, cam_name):
    from . import bluepencil
    d = bluepencil.data(scene)
    return [lay for lay in d["layers"] if lay.get("visible", True) and lay.get("camera", "") == cam_name]


def _ann_layers(scene):
    from . import annotate
    an = getattr(scene, "annotation", None)
    if an is None:
        return []
    return [lay for lay in an.layers
            if annotate.layer_name(lay) != annotate.RULER_LAYER and not getattr(lay, "annotation_hide", False)]


def has_content(scene=None, cam_name=None):
    sc = scene or bpy.context.scene
    if cam_name is None:
        cam_name = sc.camera.name if sc.camera else ""
    bp = any(lay["frames"] for lay in _bp_layers(sc, cam_name)) if cam_name else False
    ann = any(len(lay.frames) for lay in _ann_layers(sc))
    return bp or ann


def needs_camera_per_frame(scene=None):
    """True when 3D annotation strokes exist (they need the camera of each frame)."""
    for lay in _ann_layers(scene or bpy.context.scene):
        for fr in lay.frames:
            for st in fr.strokes:
                if getattr(st, "display_mode", "3DSPACE") == "3DSPACE":
                    return True
    return False


def paint(img, scene, frame, cam_name, mats=None, view_rect=None):
    """Draws the Blue Pencil layers of cam_name and the annotations of `frame` into the QImage img.
    view_rect: where the 3D view lies in the picture (a Viewport Render of a view that isn't a camera view) –
    then the View layers (cam_name "") and the screen annotations are placed by it."""
    from . import annotate, bluepencil
    w, h = img.width(), img.height()
    rect = QtCore.QRectF(view_rect) if view_rect is not None else QtCore.QRectF(0, 0, w, h)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setRenderHint(QtGui.QPainter.TextAntialiasing)
    drew = False
    try:
        # annotations (under Blue Pencil, like in the viewport)
        for lay in _ann_layers(scene):
            fr = annotate.shown_frame(lay, frame)
            if fr is None or not len(fr.strokes):
                continue
            c = lay.color
            col = QtGui.QColor.fromRgbF(c[0], c[1], c[2],
                                        max(0.0, min(1.0, getattr(lay, "annotation_opacity", 1.0))))
            pen = QtGui.QPen(col, max(1.0, lay.thickness * h / 800.0))
            pen.setCapStyle(QtCore.Qt.RoundCap)
            pen.setJoinStyle(QtCore.Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(QtCore.Qt.NoBrush)
            for st in fr.strokes:
                co = annotate._points(st)
                if not len(co):
                    continue
                mode = getattr(st, "display_mode", "3DSPACE")
                if mode == "SCREEN":
                    xy = np.c_[rect.left() + co[:, 0] / 100.0 * rect.width(),
                               rect.bottom() - co[:, 1] / 100.0 * rect.height()]
                    ok = np.ones(len(co), dtype=bool)
                elif mode == "3DSPACE" and mats is not None:
                    xy, ok = _project(co, mats, w, h)
                else:
                    continue
                annotate._polyline(p, xy, ok)
                drew = True
        # Blue Pencil layers of the camera (top of the list = on top)
        if cam_name or view_rect is not None:
            layers = _bp_layers(scene, cam_name or "")
            for lay in reversed(layers):
                k = bluepencil.held_key(lay, frame)
                if k is None:
                    continue
                op = float(lay.get("opacity", 1.0))
                for s in lay["frames"].get(str(k), []):
                    bluepencil.draw_stroke(p, s, rect, op)
                    drew = True
    finally:
        p.end()
    return drew


def burn(img, scene=None, frame=None, cam_name=None, mats=None):
    """A copy of img with the drawings (img itself is not changed)."""
    sc = scene or bpy.context.scene
    out = img.convertToFormat(QtGui.QImage.Format_RGBA8888)
    paint(out, sc, sc.frame_current if frame is None else frame, cam_name, mats)
    return out


# ---------------------------------------------------------------- output paths
def side_path(path, folder, ext=None):
    """…/frames/name0001.png → …/frames/<folder>/name0001<ext>."""
    d, name = os.path.split(path)
    if ext:
        name = os.path.splitext(name)[0] + ext
    return os.path.join(d, folder, name)


def frame_paths(scene, start, end):
    r = scene.render
    out = {}
    for f in range(start, end + 1):
        try:
            out[f] = bpy.path.abspath(r.frame_path(frame=f))
        except Exception:
            pass
    return out


def playblast_path(scene, f):
    """Viewport Render frame f: <output folder>/playblast/<frame>.png (also when the output is a movie)."""
    p = bpy.path.abspath(scene.render.frame_path(frame=f))
    return os.path.join(os.path.dirname(p), "playblast", f"{f:04d}.png")


def source_paths(scene, start, end, source="RENDER"):
    """{frame: file} the Animation Player shows: RENDER (the output frames), OVERLAY (with the drawings),
    PLAYBLAST (Viewport Render)."""
    if source == "PLAYBLAST":
        return {f: playblast_path(scene, f) for f in range(start, end + 1)}
    paths = frame_paths(scene, start, end)
    if source == "OVERLAY":
        return {f: side_path(pth, "overlay") for f, pth in paths.items()}
    return paths


def is_movie(scene):
    ims = scene.render.image_settings
    return getattr(ims, "media_type", "") == "VIDEO" or ims.file_format in ("FFMPEG", "AVI_JPEG", "AVI_RAW")


def _frame_range(scene):
    if scene.use_preview_range:
        return scene.frame_preview_start, scene.frame_preview_end
    return scene.frame_start, scene.frame_end


def _status(text, ms=0):
    from . import app
    mw = getattr(app.hub(), "main_window", None)
    if mw is not None:
        mw.statusBar().showMessage(text, ms)
    QtCore.QCoreApplication.processEvents()


# ---------------------------------------------------------------- Render Animation → overlay folder
def burn_animation(scene=None, start=None, end=None):
    """Copies the rendered frames with the drawings into the folder `overlay`. Returns (frames written,
    message)."""
    sc = scene or bpy.context.scene
    if is_movie(sc):
        return 0, "Burn-in works on image sequences – the output is a movie file."
    cam = sc.camera
    cam_name = cam.name if cam is not None else ""
    a, b = _frame_range(sc)
    start = a if start is None else start
    end = b if end is None else end
    paths = frame_paths(sc, start, end)
    if not paths:
        return 0, "No output frames."
    per_frame = needs_camera_per_frame(sc) and cam is not None
    keep = sc.frame_current
    done = 0
    skipped = []
    try:
        for i, (f, src) in enumerate(paths.items()):
            if not os.path.isfile(src):
                continue
            ext = os.path.splitext(src)[1].lower()
            dst = side_path(src, "overlay")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if ext not in QT_WRITABLE:
                skipped.append(os.path.basename(src))
                continue
            img = QtGui.QImage(src)
            if img.isNull():
                skipped.append(os.path.basename(src))
                continue
            mats = None
            if cam is not None:
                if per_frame and sc.frame_current != f:
                    sc.frame_set(f)
                mats = camera_mats(sc, sc.camera, img.width(), img.height())
            out = img.convertToFormat(QtGui.QImage.Format_ARGB32)
            if paint(out, sc, f, cam_name, mats):
                if ext in (".jpg", ".jpeg", ".bmp"):
                    out = out.convertToFormat(QtGui.QImage.Format_RGB32)
                out.save(dst)
            else:
                shutil.copy2(src, dst)            # nothing on this frame: the sequence stays complete
            done += 1
            if i % 4 == 0:
                _status(f"Burning in Blue Pencil / annotations: frame {f} ({i + 1} / {len(paths)})…")
    finally:
        if sc.frame_current != keep:
            sc.frame_set(keep)
    msg = f"Burn-in: {done} frames written to {os.path.dirname(side_path(next(iter(paths.values())), 'overlay'))}"
    if skipped:
        msg += f" · {len(skipped)} skipped (not PNG / JPEG / TIFF / WebP / BMP)"
    return done, msg


# ---------------------------------------------------------------- Viewport Render (playblast)
def _space():
    found = bridge.ensure_view3d()
    if not found:
        return None, None
    _win, area, region = found
    return area.spaces.active, region


def view_rect_in_image(vp, w, h):
    """Where a 3D view (widget) lies in a picture w × h drawn with vp.matrices(w, h): the view's field of
    view is fitted to the larger side (like Blender's sensor fit), the other side is centred."""
    ww, wh = max(vp.width(), 1), max(vp.height(), 1)
    if w >= h:
        s = w / ww
    else:
        s = h / wh
    return QtCore.QRectF(w / 2 - ww * s / 2, h / 2 - wh * s / 2, ww * s, wh * s)


def viewport_render(scene=None, frame=None, overlays=True, vp=None):
    """The scene drawn like the 3D view (its shading, no overlays) at the render size → QImage, with the
    drawings when overlays. Like Blender's Viewport Render: through the camera when the view looks through
    it (or when no view is given), else from the view itself (then its Blue Pencil View layers are drawn).
    None without a camera / 3D view."""
    import gpu
    sc = scene or bpy.context.scene
    cam = sc.camera
    space, region = _space()
    from_view = vp is not None and not getattr(vp, "camera_view", False)
    if space is None or (cam is None and not from_view):
        return None
    if frame is not None and sc.frame_current != frame:
        sc.frame_set(frame)
    w, h = render_size(sc)
    if from_view:
        view, proj = vp.matrices(w, h)
    else:
        view, proj = camera_mats(sc, cam, w, h)
    off = gpu.types.GPUOffScreen(w, h)
    ov = getattr(space, "overlay", None)
    keep_overlays = getattr(ov, "show_overlays", None)
    try:
        if ov is not None:
            ov.show_overlays = False       # like a playblast: no grid, outlines, 3D cursor
        passes = 16 if space.shading.type in ("MATERIAL", "RENDERED") else 1    # progressive samples
        for _n in range(passes):
            try:
                off.draw_view3d(sc, bpy.context.view_layer, space, region, view, proj,
                                do_color_management=True, draw_background=True)
            except TypeError:
                off.draw_view3d(sc, bpy.context.view_layer, space, region, view, proj)
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            buf = fb.read_color(0, 0, w, h, 4, 0, "UBYTE")
        try:
            arr = np.frombuffer(buf, dtype=np.uint8)
        except TypeError:
            arr = np.asarray(buf.to_list(), dtype=np.uint8)
    finally:
        off.free()
        if ov is not None and keep_overlays is not None:
            ov.show_overlays = keep_overlays
    img = QtGui.QImage(w, h, QtGui.QImage.Format_RGBX8888)
    dst = np.frombuffer(img.bits(), dtype=np.uint8, count=h * img.bytesPerLine())
    dst = dst.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)
    dst[:] = arr.reshape(h, w, 4)[::-1]
    img = img.convertToFormat(QtGui.QImage.Format_ARGB32)
    if overlays:
        if from_view:
            paint(img, sc, sc.frame_current, "", (view, proj), view_rect_in_image(vp, w, h))
        else:
            paint(img, sc, sc.frame_current, cam.name, (view, proj))
    return img


def playblast(scene=None, start=None, end=None, overlays=True, vp=None):
    """Viewport Render Animation: PNG frames in the folder `playblast` next to the output frames (from the
    view vp like viewport_render). Returns (frames written, folder or message)."""
    sc = scene or bpy.context.scene
    if sc.camera is None and (vp is None or getattr(vp, "camera_view", False)):
        return 0, "The scene has no camera."
    a, b = _frame_range(sc)
    start = a if start is None else start
    end = b if end is None else end
    paths = frame_paths(sc, start, end)
    keep = sc.frame_current
    done = 0
    folder = ""
    try:
        for i, (f, src) in enumerate(paths.items()):
            img = viewport_render(sc, f, overlays, vp)
            if img is None:
                return done, "No 3D view to draw with."
            dst = playblast_path(sc, f)
            folder = os.path.dirname(dst)
            os.makedirs(folder, exist_ok=True)
            img.save(dst)
            done += 1
            _status(f"Viewport Render: frame {f} ({i + 1} / {len(paths)})…")
    finally:
        if sc.frame_current != keep:
            sc.frame_set(keep)
    return done, folder

"""Image Editor – Blender's Image Editor in Qt, linked to the compositor.

Sources (header combo):
- **Compositor (Result)** – what goes to the compositor's output (Group Output). Blender's compositor only
  computes a picture for the Viewer node, so the Viewer is kept linked to the output's source (`follow_output`,
  after every change – a node put in front of the output is shown at once).
- **Viewer Node** – the Viewer node's picture wherever the Viewer is linked (to look at any node).
- Both: Blender runs the compositor only while its result is visible
  somewhere (a node editor backdrop or an Image Editor showing "Viewer Node"), so while this source is shown
  one area of Blender's hidden main window is a Compositor node editor with its backdrop on
  (`CompositorLink`). Every change of the compositor nodes – also from Qt Shell's Node editor – then runs
  the compositor again and the picture here follows (the end of the COMPOSITE job is watched). The area
  gets its old type back when another source is picked, when Qt Shell closes and around saving, so the
  .blend keeps the user's layout. The Render Layers node works on the last render (F12).
- **Render Result** – the last render (active render slot).
- **Rendered Animation** – the frames written by Render Animation (Output Properties → Output path) with a
  frame bar, play / pause and Follow Timeline.
- any other image of the file (textures, generated images).

Pixels are read like the Render View does it: Image.save_render() to a temporary PNG – with the scene's
view transform, i.e. what Blender shows (no image buffer of a render / viewer image is readable as display
colours from Python).

Export: Export Image… (PNG, JPEG, OpenEXR, TIFF, WebP, BMP – the compositor / render result saved by
Blender, so OpenEXR keeps float values) and Export Animation… (image sequence in another format or copied,
or an MP4 video encoded by Blender's sequencer in a temporary scene).

All keys live in keymap.py (area "Image Editor").
"""
import math
import os
import shutil
import tempfile
import time
import traceback

import bpy
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, icons, keymap, pytips, theme
from .anim_player import load_image, output_info

SRC_COMP, SRC_VIEWER, SRC_RENDER, SRC_ANIM = "COMPOSITOR", "VIEWER", "RENDER", "ANIMATION"
COMP_SOURCES = (SRC_COMP, SRC_VIEWER)
SOURCES = (SRC_COMP, SRC_VIEWER, SRC_RENDER, SRC_ANIM)
SOURCE_LABELS = {SRC_COMP: "Compositor (Result)", SRC_VIEWER: "Viewer Node", SRC_RENDER: "Render Result",
                 SRC_ANIM: "Rendered Animation"}
VIEWER = "Viewer Node"
CHANNELS = [("COLOR_ALPHA", "Color & Alpha"), ("COLOR", "Color"), ("ALPHA", "Alpha"),
            ("RED", "Red"), ("GREEN", "Green"), ("BLUE", "Blue")]
# Export Image: filter → (Blender media type, file format, extension)
IMAGE_FORMATS = [
    ("PNG (*.png)", "IMAGE", "PNG", ".png"),
    ("JPEG (*.jpg *.jpeg)", "IMAGE", "JPEG", ".jpg"),
    ("OpenEXR (*.exr)", "IMAGE", "OPEN_EXR", ".exr"),
    ("TIFF (*.tif *.tiff)", "IMAGE", "TIFF", ".tif"),
    ("WebP (*.webp)", "IMAGE", "WEBP", ".webp"),
    ("BMP (*.bmp)", "IMAGE", "BMP", ".bmp"),
]
# Export Animation: (id, label, extension or None)
ANIM_FORMATS = [("MP4", "Video – MP4 (H.264)", ".mp4"), ("PNG", "Image sequence – PNG", ".png"),
                ("JPEG", "Image sequence – JPEG", ".jpg"), ("TIFF", "Image sequence – TIFF", ".tif"),
                ("COPY", "Image sequence – copy the rendered files", None)]
FRAME_CACHE = 768 * 1024 * 1024


def _api(call):
    return f"import qt_shell; qt_shell.api.image_editor().{call}"


def _tmp(name):
    return os.path.join(tempfile.gettempdir(), name)


# ---------------------------------------------------------------- compositor data
def comp_tree(scene=None):
    """The scene's compositor node tree (Blender 5: scene.compositing_node_group) or None."""
    sc = scene or bpy.context.scene
    ng = getattr(sc, "compositing_node_group", None)
    if ng is None and getattr(sc, "use_nodes", False):
        ng = getattr(sc, "node_tree", None)
    return ng


def viewer_nodes(tree):
    return [n for n in tree.nodes if n.bl_idname == "CompositorNodeViewer"] if tree is not None else []


def _image_source(tree):
    """The output socket worth viewing: what feeds the Group Output (Composite), else Render Layers' image."""
    for n in tree.nodes:
        if n.bl_idname in ("NodeGroupOutput", "CompositorNodeComposite"):
            for inp in n.inputs:
                if inp.is_linked:
                    return inp.links[0].from_socket
    rl = next((n for n in tree.nodes if n.bl_idname == "CompositorNodeRLayers"), None)
    return rl.outputs[0] if rl is not None and rl.outputs else None


def output_socket(tree):
    """The socket that feeds the compositor's output (Group Output / Composite) – the final result – or None."""
    for n in tree.nodes:
        if n.bl_idname in ("NodeGroupOutput", "CompositorNodeComposite") and not n.mute:
            for inp in n.inputs:
                if inp.is_linked and inp.links[0].is_valid:
                    return inp.links[0].from_socket
    return None


def follow_output(tree):
    """Source Compositor (Result): the Viewer node shows what goes to the output. Blender's compositor only computes
    a picture for the Viewer, so the Viewer is (re)linked to the output's source after every change (a Viewer is
    added when there is none). Returns False when nothing is connected to the output."""
    src = output_socket(tree)
    if src is None:
        return False
    vs = viewer_nodes(tree)
    act = tree.nodes.active
    v = act if act is not None and act in vs else (vs[0] if vs else None)
    if v is None:
        v = tree.nodes.new("CompositorNodeViewer")
        v.location = (src.node.location.x + 260, src.node.location.y - 200)
        tree.nodes.active = v
    inp = v.inputs[0]
    if inp.is_linked and inp.links[0].from_socket == src:
        return True
    with bridge.quiet_updates():
        for link in list(inp.links):
            tree.links.remove(link)
    tree.links.new(src, inp)             # this change runs the compositor (not quiet)
    return True


def ensure_compositor(viewer=True):
    """Creates the compositor node tree when the scene has none (Render Layers → Group Output, like Blender's
    'Use Nodes') and a Viewer node fed by what goes to the output. Returns the tree."""
    sc = bpy.context.scene
    tree = comp_tree(sc)
    if tree is None:
        if hasattr(sc, "compositing_node_group"):
            tree = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
            sc.compositing_node_group = tree
            rl = tree.nodes.new("CompositorNodeRLayers")
            rl.location = (-300, 0)
            try:
                tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
                go = tree.nodes.new("NodeGroupOutput")
                go.location = (200, 60)
                tree.links.new(rl.outputs[0], go.inputs[0])
            except Exception as ex:
                bridge.log(f"Compositor: no Group Output ({ex})", "WARNING")
        else:
            sc.use_nodes = True
            tree = sc.node_tree
    if viewer and not viewer_nodes(tree):
        v = tree.nodes.new("CompositorNodeViewer")
        src = _image_source(tree)
        if src is not None:
            v.location = (src.node.location.x + 300, src.node.location.y - 160)
            tree.links.new(src, v.inputs[0])
        else:
            v.location = (200, -160)
        tree.nodes.active = v
    return tree


def _save_settings():
    s = bpy.context.scene.render.image_settings
    keep = {}
    for attr in ("media_type", "file_format", "color_mode", "color_depth", "compression", "quality"):
        if hasattr(s, attr):
            keep[attr] = getattr(s, attr)
    return s, keep


def _restore_settings(s, keep):
    for attr, v in keep.items():
        try:
            setattr(s, attr, v)
        except Exception:
            pass


def save_blender_image(img, path, file_format="PNG", media="IMAGE", depth=None, fast=False):
    """Image.save_render with a temporary output format (the scene's view transform applies – the colours
    Blender shows). The scene's own output settings are put back; no Qt Shell refresh is triggered."""
    sc = bpy.context.scene
    s, keep = _save_settings()
    with bridge.quiet_updates():
        try:
            if hasattr(s, "media_type"):
                s.media_type = media
            if media != "MULTI_LAYER_IMAGE":
                s.file_format = file_format
            if file_format in ("PNG", "TIFF", "OPEN_EXR", "WEBP"):
                try:
                    s.color_mode = "RGBA"
                except Exception:
                    pass
            if depth is not None:
                try:
                    s.color_depth = depth
                except Exception:
                    pass
            if fast and hasattr(s, "compression"):
                s.compression = 0
            if os.path.dirname(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            img.save_render(filepath=path, scene=sc)
        finally:
            _restore_settings(s, keep)


def read_blender_image(img, name="qtshell_image_editor.png"):
    """QImage of a Blender image (render result, viewer, generated or packed image) as Blender shows it."""
    path = _tmp(name)
    try:
        if os.path.exists(path):
            os.remove(path)
        save_blender_image(img, path, "PNG", depth="8", fast=True)
    except Exception as ex:
        bridge.log(f"Image Editor: cannot read {img.name} ({ex})", "WARNING")
        return None
    q = load_image(path)
    return q if q is not None and not q.isNull() else None


def apply_channel(base, ch):
    """Display channels like Blender's (Color & Alpha, Color, Alpha, Red, Green, Blue)."""
    if base is None or ch == "COLOR_ALPHA":
        return base
    base = base.convertToFormat(QtGui.QImage.Format_RGBA8888)
    arr = np.frombuffer(base.constBits(), dtype=np.uint8).reshape(base.height(), base.bytesPerLine())
    arr = arr[:, :base.width() * 4].reshape(base.height(), base.width(), 4)
    out = np.empty_like(arr)
    if ch == "COLOR":
        out[:, :, :3] = arr[:, :, :3]
    else:
        k = {"ALPHA": 3, "RED": 0, "GREEN": 1, "BLUE": 2}[ch]
        out[:, :, 0] = out[:, :, 1] = out[:, :, 2] = arr[:, :, k]
    out[:, :, 3] = 255
    out = np.ascontiguousarray(out)
    return QtGui.QImage(out.data, base.width(), base.height(), 4 * base.width(),
                        QtGui.QImage.Format_RGBA8888).copy()


# ---------------------------------------------------------------- compositor link
class CompositorLink:
    """Keeps the compositor running for Qt: one area of Blender's main window is a Compositor node editor with
    its backdrop on while `wanted` (Blender only composites when the result is visible somewhere)."""

    def __init__(self):
        self.wanted = False
        self._ptr = None          # area pointer
        self._old = None          # its ui_type before (None = it already was a compositor editor)

    def area(self):
        if self._ptr is None:
            return None
        try:
            for win in bpy.context.window_manager.windows:
                for a in win.screen.areas:
                    if a.as_pointer() == self._ptr:
                        return a
        except Exception:
            pass
        self._ptr = None
        return None

    def active(self):
        return self.area() is not None

    def acquire(self):
        self.wanted = True
        a = self.area()
        if a is None:
            a = self._pick()
            if a is None:
                return False
        try:
            if a.ui_type != "CompositorNodeTree":
                a.ui_type = "CompositorNodeTree"
            sp = a.spaces.active
            if hasattr(sp, "show_backdrop") and not sp.show_backdrop:
                sp.show_backdrop = True
        except Exception as ex:
            bridge.log(f"Image Editor: compositor link failed ({ex})", "WARNING")
            return False
        return True

    def _pick(self):
        try:
            wm = bpy.context.window_manager
            win = wm.windows[0]
            areas = list(win.screen.areas)
        except Exception:
            return None
        a = next((x for x in areas if x.type == "NODE_EDITOR" and x.ui_type == "CompositorNodeTree"), None)
        if a is not None:
            self._ptr, self._old = a.as_pointer(), None
            return a
        order = ("PROPERTIES", "OUTLINER", "INFO", "CONSOLE", "TEXT_EDITOR", "NODE_EDITOR", "SPREADSHEET",
                 "FILE_BROWSER", "SEQUENCE_EDITOR", "CLIP_EDITOR", "NLA_EDITOR", "PREFERENCES")
        cands = [x for x in areas if x.type in order]
        cands.sort(key=lambda x: order.index(x.type))
        if not cands:
            # the timeline / graph / image area is borrowed for a moment by the UV editor's operators – it
            # restores the old type afterwards, so taking it is still fine when nothing else is there
            cands = [x for x in areas if x.type != "VIEW_3D"]
        if not cands:
            return None
        a = cands[0]
        self._ptr, self._old = a.as_pointer(), a.ui_type
        return a

    def release(self, keep_wanted=False):
        a = self.area()
        if a is not None and self._old:
            try:
                a.ui_type = self._old
            except Exception:
                pass
        self._ptr = self._old = None
        if not keep_wanted:
            self.wanted = False

    def forget(self):
        """The file is being replaced – its areas go away with it."""
        self._ptr = self._old = None


LINK = CompositorLink()


@bpy.app.handlers.persistent
def _on_save_pre(*_args):
    try:
        ANIM_COMP.uninstall()                 # the temporary animation-cache node is never saved
    except Exception:
        pass
    if LINK.active():
        LINK.release(keep_wanted=True)        # the .blend keeps the user's own layout


@bpy.app.handlers.persistent
def _on_save_post(*_args):
    if LINK.wanted:
        LINK.acquire()


@bpy.app.handlers.persistent
def _on_load_pre(*_args):
    LINK.forget()


@bpy.app.handlers.persistent
def _on_load_post(*_args):
    if LINK.wanted:
        bridge.later(LINK.acquire, 0.1)


_HANDLERS = (("save_pre", _on_save_pre), ("save_post", _on_save_post), ("load_pre", _on_load_pre),
             ("load_post", _on_load_post))


def register_handlers():
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name)
        for old in [f for f in lst if getattr(f, "__name__", "") == fn.__name__
                    and getattr(f, "__module__", "") == fn.__module__]:
            lst.remove(old)            # an older copy after a reload
        lst.append(fn)


def unregister_handlers():
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name)
        for old in [f for f in lst if getattr(f, "__name__", "") == fn.__name__
                    and getattr(f, "__module__", "") == fn.__module__]:
            lst.remove(old)


# ---------------------------------------------------------------- compositor over the rendered animation
RAW_PREFIX = "raw_"
TEMP_NODE = "QtShell Animation Cache"
_SIG_SKIP_PROPS = {"location", "location_absolute", "width", "height", "select", "show_options", "show_preview",
                   "hide", "name", "label", "color", "use_custom_color", "parent", "warning_propagation",
                   "show_texture", "dimensions", "bl_idname", "bl_label", "bl_description", "bl_icon",
                   "bl_width_default", "bl_width_min", "bl_width_max", "bl_height_default", "bl_height_min",
                   "bl_height_max"}


def raw_dir(scene=None):
    """Folder of the frames rendered without compositing (input of the compositor over the animation)."""
    sc = scene or bpy.context.scene
    # an unsaved file: per Blender session (another session's frames would belong to another scene)
    name = os.path.splitext(os.path.basename(bpy.data.filepath))[0] if bpy.data.filepath else f"unsaved_{os.getpid()}"
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in f"{name}_{sc.name}")
    return os.path.join(tempfile.gettempdir(), "qtshell_comp_cache", safe)


_SEQ_RE = None


def scan_sequence(folder):
    """{frame: file} of the image sequence in a folder (name + frame number + .exr / .png / .jpg / .tif); with
    several sequences the one with the most frames (OpenEXR first)."""
    global _SEQ_RE
    import re
    if _SEQ_RE is None:
        _SEQ_RE = re.compile(r"^(.*?)(\d+)\.(exr|png|jpe?g|tiff?)$", re.IGNORECASE)
    seqs = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return {}
    for n in names:
        m = _SEQ_RE.match(n)
        if m:
            key = (m.group(1), m.group(3).lower())
            seqs.setdefault(key, {})[int(m.group(2))] = os.path.join(folder, n)
    if not seqs:
        return {}
    best = max(seqs, key=lambda k: (k[1] == "exr", len(seqs[k])))
    return seqs[best]


def raw_frames(scene=None, lo=None, hi=None, folder=None):
    """{frame: file} of the raw frames (rendered without compositing) between lo and hi – from this file's cache
    folder or another folder (frames used before)."""
    from .anim_player import scene_range
    sc = scene or bpy.context.scene
    s_lo, s_hi = scene_range(sc)
    lo = s_lo if lo is None else lo
    hi = s_hi if hi is None else hi
    seq = scan_sequence(folder or raw_dir(sc))
    return {f: p for f, p in seq.items() if lo <= f <= hi}


_SIZE_CACHE = {}


def image_size(path):
    """(width, height) of an image file from its header (Qt formats, else OpenImageIO – OpenEXR), or None."""
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    if key in _SIZE_CACHE:
        return _SIZE_CACHE[key]
    size = None
    rd = QtGui.QImageReader(path)
    sz = rd.size()
    if sz.isValid() and sz.width() > 0:
        size = (sz.width(), sz.height())
    else:
        try:
            import OpenImageIO as oiio
            inp = oiio.ImageInput.open(path)
            if inp is not None:
                spec = inp.spec()
                size = (spec.width, spec.height)
                inp.close()
        except Exception:
            size = None
    _SIZE_CACHE[key] = size
    return size


def render_size(scene=None):
    r = (scene or bpy.context.scene).render
    return (int(r.resolution_x * r.resolution_percentage / 100), int(r.resolution_y * r.resolution_percentage / 100))


def cache_folders():
    """Raw frame folders of all files (newest first): [(folder, {frame: file}, modified time)]."""
    base = os.path.join(tempfile.gettempdir(), "qtshell_comp_cache")
    out = []
    try:
        names = os.listdir(base)
    except OSError:
        return out
    for n in names:
        d = os.path.join(base, n)
        if os.path.isdir(d):
            seq = scan_sequence(d)
            if seq:
                out.append((d, seq, max(os.path.getmtime(p) for p in seq.values())))
    out.sort(key=lambda x: -x[2])
    return out


def _files_sig(frames):
    sig = []
    for f, p in sorted(frames.items()):
        try:
            sig.append((f, p, os.path.getmtime(p)))
        except OSError:
            sig.append((f, p, 0))
    return tuple(sig)


def _value(v):
    try:
        if hasattr(v, "name") and not isinstance(v, str):
            return v.name
        if hasattr(v, "__len__") and not isinstance(v, str):
            return tuple(round(x, 6) if isinstance(x, float) else x for x in v)
        return round(v, 6) if isinstance(v, float) else v
    except Exception:
        return repr(v)


def tree_signature(tree, skip=TEMP_NODE):
    """What the compositor's picture depends on (nodes, their settings and inputs, links) – without the temporary
    animation-cache node, whose links count as the Render Layers links they replace."""
    rl = next((n.name for n in tree.nodes if n.bl_idname == "CompositorNodeRLayers"), None)
    parts = []
    for n in tree.nodes:
        if n.name == skip:
            continue
        props = []
        for prop in n.bl_rna.properties:
            k = prop.identifier
            if k in _SIG_SKIP_PROPS or prop.type == "COLLECTION" or k == "rna_type":
                continue
            try:
                props.append((k, _value(getattr(n, k))))
            except Exception:
                pass
        ins = tuple((i.identifier, _value(getattr(i, "default_value", None))) for i in n.inputs)
        parts.append((n.name, n.bl_idname, n.mute, tuple(props), ins))
    links = []
    for link in tree.links:
        fn, fs = link.from_node.name, link.from_socket.name
        if fn == skip:
            fn = rl
        links.append((fn, fs, link.to_node.name, link.to_socket.identifier, link.is_muted))
    return hash((tuple(parts), tuple(sorted(links, key=repr))))


class AnimComp:
    """Composites the raw frames of the animation with the current compositor nodes: a temporary Image node
    (the raw OpenEXR sequence) takes over the Render Layers' Image / Alpha links, its frame offset picks the
    frame. The links go back to Render Layers and the node is removed when caching ends, before saving and
    when Qt Shell closes."""

    def __init__(self):
        self.moved = []          # [(output name, to node name, to socket identifier)]

    @staticmethod
    def node(tree=None):
        tree = tree or comp_tree()
        return tree.nodes.get(TEMP_NODE) if tree is not None else None

    def install(self, tree, frames):
        n = self.node(tree)
        if n is not None:
            return n
        rl = next((x for x in tree.nodes if x.bl_idname == "CompositorNodeRLayers"), None)
        if rl is None or not frames:
            return None
        first = frames[min(frames)]
        img = bpy.data.images.load(first, check_existing=False)
        img.name = TEMP_NODE
        img.source = "SEQUENCE"
        n = tree.nodes.new("CompositorNodeImage")
        n.name = n.label = TEMP_NODE
        n.image = img
        n.location = (rl.location.x, rl.location.y - 420)
        n.frame_duration = max(frames)
        self.moved = []
        for link in list(tree.links):
            if link.from_node == rl and link.from_socket.name in ("Image", "Alpha"):
                self.moved.append((link.from_socket.name, link.to_node.name, link.to_socket.identifier))
        for name, to_node, to_id in self.moved:
            to = next((i for i in tree.nodes[to_node].inputs if i.identifier == to_id), None)
            if to is not None and name in n.outputs:
                tree.links.new(n.outputs[name], to)
        return n

    def set_frame(self, tree, f):
        n = self.node(tree)
        if n is None:
            return False
        sc = bpy.context.scene
        n.frame_start = sc.frame_current          # image frame = scene frame - start + offset + 1 = f
        n.frame_offset = int(f) - 1
        return True

    def uninstall(self):
        tree = comp_tree()
        n = self.node(tree) if tree is not None else None
        if n is None:
            self.moved = []
            return False
        rl = next((x for x in tree.nodes if x.bl_idname == "CompositorNodeRLayers"), None)
        img = n.image
        if rl is not None:
            for name, to_node, to_id in self.moved:
                tn = tree.nodes.get(to_node)
                to = next((i for i in tn.inputs if i.identifier == to_id), None) if tn is not None else None
                if to is not None and name in rl.outputs:
                    tree.links.new(rl.outputs[name], to)
        tree.nodes.remove(n)
        if img is not None and img.users == 0:
            bpy.data.images.remove(img)
        self.moved = []
        return True


ANIM_COMP = AnimComp()


# ---------------------------------------------------------------- canvas
class ImageCanvas(QtWidgets.QWidget):
    """The picture: checkerboard behind alpha, wheel zooms around the mouse, middle mouse (or Alt + left) pans,
    left mouse samples the pixel under it."""

    zoom_changed = QtCore.Signal(float)
    sampled = QtCore.Signal(object)       # (x, y, QColor) or None

    def __init__(self, parent):
        super().__init__(parent)
        self.image = None
        self.zoom = 1.0
        self.offset = QtCore.QPointF(0, 0)
        self.hint = ""
        self._pan = None
        self._sampling = False
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMinimumSize(theme.px(120), theme.px(80))
        s = theme.px(8)
        self._checker = QtGui.QPixmap(2 * s, 2 * s)
        self._checker.fill(QtGui.QColor(102, 102, 102))
        p = QtGui.QPainter(self._checker)
        try:
            p.fillRect(0, 0, s, s, QtGui.QColor(153, 153, 153))
            p.fillRect(s, s, s, s, QtGui.QColor(153, 153, 153))
        finally:
            p.end()

    def set_image(self, img, keep_view=True):
        first = self.image is None or (img is not None and self.image.size() != img.size())
        self.image = img
        if img is not None and (first or not keep_view):
            self.fit()
        self.update()

    def image_rect(self):
        if self.image is None:
            return QtCore.QRectF()
        dpr = self.devicePixelRatioF()
        w, h = self.image.width() * self.zoom / dpr, self.image.height() * self.zoom / dpr
        c = QtCore.QPointF(self.width() / 2, self.height() / 2) + self.offset
        return QtCore.QRectF(c.x() - w / 2, c.y() - h / 2, w, h)

    def fit(self):
        if self.image is None:
            return
        dpr = self.devicePixelRatioF()
        m = theme.px(16)
        z = min((self.width() - m) * dpr / max(self.image.width(), 1),
                (self.height() - m) * dpr / max(self.image.height(), 1))
        # small pictures are enlarged to the view too (Blender's View Fit) – the footer shows the real size
        self.set_zoom(z if z > 0 else 1.0, reset_offset=True)

    def set_zoom(self, z, anchor=None, reset_offset=False):
        z = max(0.02, min(64.0, z))
        if reset_offset:
            self.offset = QtCore.QPointF(0, 0)
        elif anchor is not None and self.zoom > 0:
            c = QtCore.QPointF(self.width() / 2, self.height() / 2) + self.offset
            self.offset += (anchor - c) * (1 - z / self.zoom)
        self.zoom = z
        self.zoom_changed.emit(z)
        self.update()

    def pixel_at(self, pos):
        r = self.image_rect()
        if self.image is None or r.width() <= 0:
            return None
        x = int(math.floor((pos.x() - r.x()) / r.width() * self.image.width()))
        y = int(math.floor((pos.y() - r.y()) / r.height() * self.image.height()))
        if 0 <= x < self.image.width() and 0 <= y < self.image.height():
            return x, y
        return None

    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        try:
            p.fillRect(self.rect(), QtGui.QColor("#1d1d1d"))
            if self.image is not None:
                r = self.image_rect()
                p.fillRect(r, QtGui.QBrush(self._checker))
                p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, self.zoom < 1.0)
                p.drawImage(r, self.image)
                p.setPen(QtGui.QColor(0, 0, 0, 160))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawRect(r.adjusted(-0.5, -0.5, 0.5, 0.5))
            if self.hint:
                f = p.font()
                f.setPixelSize(theme.fs(12))
                p.setFont(f)
                p.setPen(QtGui.QColor("#b8b8b8"))
                box = self.rect().adjusted(20, 20, -20, -20)
                p.drawText(box, QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap, self.hint)
        finally:
            p.end()

    def wheelEvent(self, ev):
        d = ev.angleDelta().y()
        if d:
            self.set_zoom(self.zoom * (1.25 if d > 0 else 0.8), ev.position())

    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.MiddleButton or (
                ev.button() == QtCore.Qt.LeftButton and ev.modifiers() & QtCore.Qt.AltModifier):
            self._pan = ev.position()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
        elif ev.button() == QtCore.Qt.LeftButton:
            self._sampling = True
            self._sample(ev.position())

    def mouseMoveEvent(self, ev):
        if self._pan is not None:
            self.offset += ev.position() - self._pan
            self._pan = ev.position()
            self.update()
        elif self._sampling:
            self._sample(ev.position())

    def mouseReleaseEvent(self, ev):
        if self._pan is not None:
            self._pan = None
            self.unsetCursor()
        if self._sampling:
            self._sampling = False
            self.sampled.emit(None)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == QtCore.Qt.MiddleButton:
            self.fit()

    def _sample(self, pos):
        xy = self.pixel_at(pos)
        if xy is None:
            self.sampled.emit(None)
            return
        self.sampled.emit((xy[0], xy[1], self.image.pixelColor(xy[0], xy[1])))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.image is not None and self.offset == QtCore.QPointF(0, 0):
            self.fit()


class FrameBar(QtWidgets.QWidget):
    """Timeline of the rendered animation: frame numbers, which frames exist (grey), which are composited and
    cached (green), the frame shown (blue). Click / drag scrubs, the wheel steps."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.lo, self.hi = 1, 1
        self.available = set()
        self.cached = set()
        self.current = None
        self._drag = False
        self.setMinimumHeight(theme.px(30))
        self.setMouseTracking(True)
        self.setToolTip("Rendered animation – grey: rendered frames, green: composited with the current nodes and "
                        "cached (Live), blue: the frame shown. Click / drag scrubs, the wheel steps.")

    def set_state(self, lo, hi, available, cached, current):
        self.lo, self.hi = int(lo), max(int(hi), int(lo))
        self.available, self.cached, self.current = set(available), set(cached), current
        self.update()

    def _x(self, f):
        m = theme.px(8)
        n = max(1, self.hi - self.lo + 1)
        return m + (f - self.lo) / n * (self.width() - 2 * m)

    def _frame_at(self, x):
        m = theme.px(8)
        n = max(1, self.hi - self.lo + 1)
        f = self.lo + int((x - m) / max(1.0, self.width() - 2 * m) * n)
        return min(max(f, self.lo), self.hi)

    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        try:
            p.fillRect(self.rect(), QtGui.QColor("#262626"))
            h = self.height()
            n = max(1, self.hi - self.lo + 1)
            w = (self.width() - 2 * theme.px(8)) / n
            band = QtCore.QRectF(0, h - theme.px(6), 0, theme.px(5))
            for f in range(self.lo, self.hi + 1):
                x = self._x(f)
                if f in self.cached:
                    col = QtGui.QColor(70, 180, 90)
                elif f in self.available:
                    col = QtGui.QColor(95, 95, 95)
                else:
                    continue
                p.fillRect(QtCore.QRectF(x, band.y(), max(1.0, w - (1 if w > 4 else 0)), band.height()), col)
            # frame numbers
            f_ = p.font()
            f_.setPixelSize(theme.fs(10))
            p.setFont(f_)
            step = 1
            while n / step * theme.px(34) > self.width() and step < 100000:
                step *= 5 if str(step).startswith("2") else 2
            p.setPen(QtGui.QColor("#9a9a9a"))
            first = self.lo + (-self.lo) % step
            for f in range(first, self.hi + 1, step):
                x = self._x(f) + w / 2
                p.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, theme.px(4)))
                p.drawText(QtCore.QPointF(x + 2, theme.px(14)), str(f))
            if self.current is not None:
                x = self._x(self.current)
                r = QtCore.QRectF(x, 0, max(2.0, w), h)
                p.fillRect(r, QtGui.QColor(71, 114, 179, 170))
                p.setPen(QtGui.QColor("#ffffff"))
                p.drawText(QtCore.QPointF(x + max(2.0, w) + 3, h - theme.px(9)), str(self.current))
        finally:
            p.end()

    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton:
            self._drag = True
            self.editor.set_frame(self._frame_at(ev.position().x()), from_ui=True)

    def mouseMoveEvent(self, ev):
        if self._drag:
            f = self._frame_at(ev.position().x())
            if f != self.current:
                self.editor.set_frame(f, from_ui=True)

    def mouseReleaseEvent(self, _ev):
        self._drag = False

    def wheelEvent(self, ev):
        d = ev.angleDelta().y() or ev.angleDelta().x()
        if d:
            self.editor.step(-1 if d > 0 else 1)
        ev.accept()


class _SourceCombo(QtWidgets.QComboBox):
    """Sources + the images of the file – the list is rebuilt when it opens."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)

    def wheelEvent(self, ev):
        ev.ignore()

    def showPopup(self):
        self.editor.fill_sources()
        v = self.view()
        v.setTextElideMode(QtCore.Qt.ElideNone)
        v.setMinimumWidth(v.sizeHintForColumn(0) + theme.px(36))     # full names, not "Composit…"
        super().showPopup()


# ---------------------------------------------------------------- editor
class ImageEditor(QtWidgets.QWidget):
    def __init__(self, hub, main_window=None):
        super().__init__()
        self.hub = hub
        self.mw = main_window
        self.source = SRC_COMP
        self.channel = "COLOR_ALPHA"
        self.base = None               # the picture before the channel filter
        self.live = True
        self._export_path = None
        self._watch_until = 0.0        # compositor: watch the COMPOSITE job until then
        self._saw_job = False
        self._comp_dirty = False
        self._anim = None              # output_info() of the rendered animation
        self._frame = None
        self._frames = {}              # frame → QImage (rendered animation)
        self._frames_bytes = 0
        self._sample = None
        # compositor over the rendered animation (Live): frame → composited QImage
        self._raw = {}
        self._files_sig = None
        self._comp_frames = {}
        self._comp_bytes = 0
        self._comp_sig = None
        self._pending = None           # (frame, start time, saw the job, scene frame)
        self._raw_keep = None          # output settings to put back after rendering the raw frames
        self._raw_folder = None        # None: this file's cache folder, else frames used before (another folder)
        self._range = None             # (from, to) of the cache – None: the scene's frame range
        register_handlers()
        self._build()
        self._watch = QtCore.QTimer(self)
        self._watch.setInterval(25)
        self._watch.timeout.connect(self._watch_tick)
        self._play = QtCore.QTimer(self)
        self._play.timeout.connect(self._play_tick)
        self._cache_timer = QtCore.QTimer(self)
        self._cache_timer.setInterval(30)
        self._cache_timer.timeout.connect(self._cache_tick)
        hub.data_changed.connect(self._on_data_changed)
        hub.render_done.connect(self._on_render_done)
        hub.file_loaded.connect(self._on_file_loaded)
        hub.frame_changed.connect(self._on_frame_changed)
        hub.play_frame.connect(self._on_frame_changed)
        self._shown = False

    # --- UI
    def _tool(self, text="", tip="", icon=None, checkable=False):
        b = QtWidgets.QToolButton(self)
        if icon:
            icons.set_icon(b, icon, keep_text=text or None)
        if text:
            b.setText(text)
        if text and icon:
            b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        b.setCheckable(checkable)
        if tip:
            keymap.tip(b, tip)
        b.setAutoRaise(True)
        return b

    def _build(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QtWidgets.QWidget(self)
        # (the background rule for every QWidget would also hide the blue of checked buttons – Live, Follow)
        bar.setStyleSheet("QWidget { background: #303030; }\n"
                          f"QToolButton:checked {{ background: {theme.C['highlight']}; }}\n"
                          + theme.hover_qss() + theme.field_hover_qss())
        bl = QtWidgets.QHBoxLayout(bar)
        bl.setContentsMargins(4, 2, 4, 2)
        bl.setSpacing(3)
        self.source_combo = _SourceCombo(self)
        self.source_combo.setToolTip("What the Image Editor shows: the compositor's result (what goes to the Group "
                                     "Output – updates when the compositor nodes change), the Viewer node, the last "
                                     "render, the rendered animation or an image of the file")
        self.source_combo.activated.connect(lambda i: self.set_source(self.source_combo.itemData(i)))
        pytips.tag(self.source_combo, _api('set_source("COMPOSITOR")'))
        bl.addWidget(self.source_combo)
        self.live_btn = self._tool("Live", "Live (blue = on): the picture follows every change of the compositor "
                                           "nodes (the compositor works on the last render).\nOff: the picture stays "
                                           "as it is until Reload ({image.reload}) – compare before / after",
                                   checkable=True)
        self.live_btn.setChecked(True)
        self.live_btn.toggled.connect(self.set_live)
        pytips.tag(self.live_btn, _api("set_live(True)"))
        bl.addWidget(self.live_btn)
        self.render_btn = self._tool("Render", "Render Image ({window.render}) – gives the compositor a picture to "
                                               "work on", icon="camera")
        self.render_btn.clicked.connect(self._render)
        bl.addWidget(self.render_btn)
        self.reload_btn = self._tool("⟳", "Reload ({image.reload})")
        self.reload_btn.clicked.connect(lambda _c=False: self.refresh())
        pytips.tag(self.reload_btn, _api("refresh()"))
        bl.addWidget(self.reload_btn)
        # animation controls
        self.anim_box = QtWidgets.QWidget(bar)
        al = QtWidgets.QHBoxLayout(self.anim_box)
        al.setContentsMargins(6, 0, 0, 0)
        al.setSpacing(2)
        self.play_btn = self._tool("", "Play / Pause the rendered frames ({image.play})", icon="play")
        self.play_btn.clicked.connect(lambda _c=False: self.toggle_play())
        al.addWidget(self.play_btn)
        self.frame_spin = QtWidgets.QSpinBox(self.anim_box)
        self.frame_spin.setRange(-100000, 100000)
        self.frame_spin.setKeyboardTracking(False)
        self.frame_spin.valueChanged.connect(lambda v: self.set_frame(v, from_ui=True))
        al.addWidget(self.frame_spin)
        self.follow_btn = self._tool("Follow", "Follow Timeline – show the frame of the Timeline (scrubbing / playing the "
                                                        "scene shows the same rendered frame here)", checkable=True)
        self.follow_btn.setChecked(True)
        self.raw_btn = self._tool("Re-render", "Render the frames for the compositor again (after the scene changed) – "
                                               "Live composites them with the current nodes", icon="camera")
        self.raw_btn.clicked.connect(lambda _c=False: self.render_raw())
        pytips.tag(self.raw_btn, _api("render_raw()"))
        self.follow_btn.toggled.connect(lambda on: on and self._on_frame_changed(bpy.context.scene.frame_current))
        al.addWidget(self.follow_btn)
        al.addWidget(self.raw_btn)
        self.range_box = QtWidgets.QWidget(self.anim_box)
        rl = QtWidgets.QHBoxLayout(self.range_box)
        rl.setContentsMargins(4, 0, 0, 0)
        rl.setSpacing(2)
        rl.addWidget(QtWidgets.QLabel("From", self.range_box))
        self.from_spin = QtWidgets.QSpinBox(self.range_box)
        self.to_spin = QtWidgets.QSpinBox(self.range_box)
        for sp in (self.from_spin, self.to_spin):
            sp.setRange(-100000, 100000)
            sp.setKeyboardTracking(False)
            sp.setToolTip("Frames rendered for the compositor and composited (Live) – From / To")
        rl.addWidget(self.from_spin)
        rl.addWidget(QtWidgets.QLabel("To", self.range_box))
        rl.addWidget(self.to_spin)
        self.from_spin.valueChanged.connect(lambda _v: self._range_changed())
        self.to_spin.valueChanged.connect(lambda _v: self._range_changed())
        al.addWidget(self.range_box)
        self.earlier_btn = self._tool("Earlier Frames", "Use frames rendered for the compositor before – of this "
                                                         "file, another file or any folder with an image sequence")
        self.earlier_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.earlier_menu = QtWidgets.QMenu(self.earlier_btn)
        self.earlier_menu.aboutToShow.connect(self._fill_earlier_menu)
        self.earlier_btn.setMenu(self.earlier_menu)
        al.addWidget(self.earlier_btn)
        bl.addWidget(self.anim_box, 1)
        self.spacer = QtWidgets.QWidget(bar)
        self.spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        bl.addWidget(self.spacer)
        self.channel_combo = QtWidgets.QComboBox(bar)
        for ident, label in CHANNELS:
            self.channel_combo.addItem(label, ident)
        self.channel_combo.setToolTip("Display channels")
        self.channel_combo.activated.connect(lambda i: self.set_channel(self.channel_combo.itemData(i)))
        bl.addWidget(self.channel_combo)
        fit = self._tool("⤢", "Frame All ({image.fit})\nZoom 1:1: {image.zoom_1_1}")
        fit.clicked.connect(lambda _c=False: self.fit())
        bl.addWidget(fit)
        self.export_btn = self._tool("Export", "Export Image… ({image.export}) / Export Animation…")
        self.export_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        m = QtWidgets.QMenu(self.export_btn)
        self.export_image_act = m.addAction("Export Image…")
        self.export_image_act.triggered.connect(lambda _c=False: self.export_image())
        pytips.tag(self.export_image_act, _api('export_image("C:/renders/image.png")'))
        self.export_anim_act = m.addAction("Export Animation…")
        self.export_anim_act.triggered.connect(lambda _c=False: self.export_animation())
        pytips.tag(self.export_anim_act, _api('export_animation("C:/renders/anim.mp4", "MP4")'))
        m.addSeparator()
        self.copy_act = m.addAction("Copy to Clipboard")
        self.copy_act.triggered.connect(lambda _c=False: self.copy_to_clipboard())
        m.aboutToShow.connect(self._update_export_menu)
        self.export_btn.setMenu(m)
        bl.addWidget(self.export_btn)
        # a narrow dock: the header scrolls sideways with the mouse wheel instead of cutting buttons off
        from .anim_player import _WheelScroll
        self.header_area = _WheelScroll(self)
        self.header_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.header_area.setWidgetResizable(True)
        self.header_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.header_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.header_area.setWidget(bar)
        self.header_area.setFixedHeight(bar.sizeHint().height())
        lay.addWidget(self.header_area)
        # hint bar with an action (create compositor nodes, add a viewer, render)
        self.hint_bar = QtWidgets.QWidget(self)
        self.hint_bar.setStyleSheet("QWidget { background: #3a3424; }")
        hl = QtWidgets.QHBoxLayout(self.hint_bar)
        hl.setContentsMargins(8, 3, 8, 3)
        self.hint_label = QtWidgets.QLabel(self.hint_bar)
        self.hint_label.setWordWrap(True)
        hl.addWidget(self.hint_label, 1)
        self.hint_btn = QtWidgets.QPushButton(self.hint_bar)
        self.hint_btn.clicked.connect(lambda _c=False: self._hint_action())
        hl.addWidget(self.hint_btn)
        self.hint_bar.hide()
        self._hint_fn = None
        lay.addWidget(self.hint_bar)
        self.canvas = ImageCanvas(self)
        self.canvas.sampled.connect(self._on_sample)
        self.canvas.zoom_changed.connect(lambda _z: self._update_footer())
        lay.addWidget(self.canvas, 1)
        self.frame_bar = FrameBar(self)          # timeline of the rendered animation
        lay.addWidget(self.frame_bar)
        self.footer = QtWidgets.QLabel(self)
        self.footer.setContentsMargins(6, 2, 6, 2)
        self.footer.setProperty("dim", True)
        lay.addWidget(self.footer)
        self.fill_sources()
        self._update_controls()

    def fill_sources(self):
        cb = self.source_combo
        cb.blockSignals(True)
        cb.clear()
        for ident in SOURCES:
            cb.addItem(icons.icon({SRC_COMP: "nodetree", SRC_VIEWER: "nodetree", SRC_RENDER: "camera",
                                   SRC_ANIM: "play"}[ident]),
                       SOURCE_LABELS[ident], ident)
        names = [im.name for im in bpy.data.images if im.name not in ("Render Result", VIEWER)]
        if names:
            cb.insertSeparator(cb.count())
            for n in sorted(names, key=str.lower):
                cb.addItem(icons.icon("image"), n, "IMAGE:" + n)
        i = cb.findData(self.source)
        cb.setCurrentIndex(max(i, 0))
        cb.blockSignals(False)

    def _update_controls(self):
        src = self.source
        self.live_btn.setVisible(src in COMP_SOURCES or src == SRC_ANIM)
        self.frame_bar.setVisible(src == SRC_ANIM)
        for w in (self.raw_btn, self.range_box, self.earlier_btn):
            w.setVisible(src == SRC_ANIM and self.live)
        self.render_btn.setVisible(src in COMP_SOURCES or src == SRC_RENDER)
        self.anim_box.setVisible(src == SRC_ANIM)
        self.spacer.setVisible(src != SRC_ANIM)
        i = self.source_combo.findData(src)
        if i >= 0 and i != self.source_combo.currentIndex():
            self.source_combo.blockSignals(True)
            self.source_combo.setCurrentIndex(i)
            self.source_combo.blockSignals(False)

    def _update_export_menu(self):
        has = self.base is not None
        self.export_image_act.setEnabled(has)
        self.copy_act.setEnabled(has)
        self.export_anim_act.setEnabled(bool(self._available()) if self.source == SRC_ANIM else
                                        bool(self._anim_frames(output_info())))

    def _set_hint(self, text, button=None, fn=None):
        self.canvas.hint = "" if button else text
        if button:
            self.hint_label.setText(text)
            self.hint_btn.setText(button)
            self._hint_fn = fn
            self.hint_bar.show()
        else:
            self.hint_bar.hide()
            self._hint_fn = None
        self.canvas.update()

    def _hint_action(self):
        fn = self._hint_fn
        if fn is not None:
            fn()

    # --- visibility: the compositor link only while the editor is shown
    def showEvent(self, ev):
        super().showEvent(ev)
        self._shown = True
        QtCore.QTimer.singleShot(0, self._activate)

    def hideEvent(self, ev):
        super().hideEvent(ev)
        QtCore.QTimer.singleShot(0, self._check_hidden)

    def _check_hidden(self):
        if not self.isVisible():
            self._shown = False
            self.pause()
            self._stop_cache()
            self._update_link()

    def _activate(self):
        if self.isVisible():
            self._update_link()
            self.reload()

    def _update_link(self):
        # also with Live off: the compositor keeps running in Blender, Reload then shows its current picture
        want = self.isVisible() and (self.source in COMP_SOURCES or (self.source == SRC_ANIM and self.live))
        try:
            if want:
                LINK.acquire()
            elif LINK.wanted or LINK.active():
                LINK.release()
        except Exception:
            bridge.log(traceback.format_exc(), "WARNING")

    def shutdown(self):
        try:
            self.pause()
            self._stop_cache()
            LINK.release()
            unregister_handlers()
        except Exception:
            pass

    # --- sources
    def set_source(self, src):
        """COMPOSITOR, RENDER, ANIMATION or the name of an image ("IMAGE:<name>" or just the name)."""
        if src is None:
            return
        if src not in SOURCES and not src.startswith("IMAGE:"):
            src = "IMAGE:" + src
        if src.startswith("IMAGE:") and bpy.data.images.get(src[6:]) is None:
            bridge.log(f"Image Editor: no image '{src[6:]}'", "WARNING")
            return
        self.pause()
        if src != SRC_ANIM:
            self._stop_cache()
        self.source = src
        if self.source_combo.findData(src) < 0:
            self.fill_sources()
        self._update_controls()
        self._update_link()
        self.reload(keep_view=False)

    def set_live(self, on):
        """Live on: the picture follows every change of the compositor nodes. Off: the picture stays as it is
        (compare before / after) until Reload or a new render."""
        self.live = bool(on)
        if self.live_btn.isChecked() != self.live:
            self.live_btn.blockSignals(True)
            self.live_btn.setChecked(self.live)
            self.live_btn.blockSignals(False)
        if not self.live:
            self._stop_cache()
        for w in (self.raw_btn, self.range_box, self.earlier_btn):
            w.setVisible(self.source == SRC_ANIM and self.live)
        self._update_link()
        if self.source == SRC_ANIM:
            self.reload()               # the composited frames cached before are shown again at once
        elif self.live:
            self.refresh()
        self._status("Image Editor: Live on – the picture follows the compositor nodes" if self.live else
                     "Image Editor: Live off – the picture stays until Reload", 3000)

    def refresh(self):
        """Reload button: the compositor's current result (the Viewer re-linked to the output first)."""
        if self.source in COMP_SOURCES:
            if self.source == SRC_COMP:
                tree = comp_tree()
                if tree is not None:
                    try:
                        follow_output(tree)
                    except Exception as ex:
                        bridge.log(f"Image Editor: {ex}", "WARNING")
            self.reload()
            self._comp_changed()        # and once more when a compositor run it started has finished
        elif self.source == SRC_ANIM:
            self._clear_anim()          # read the frames again and composite them again
            self.reload()
        else:
            self.reload()

    def set_channel(self, ch):
        self.channel = ch
        i = self.channel_combo.findData(ch)
        if i >= 0:
            self.channel_combo.setCurrentIndex(i)
        self._show(True)

    def reload(self, keep_view=True):
        """Reads the picture of the current source again."""
        src = self.source
        try:
            if src in COMP_SOURCES:
                self._load_compositor(keep_view)
            elif src == SRC_RENDER:
                self._load_render(keep_view)
            elif src == SRC_ANIM:
                self._load_animation(keep_view)
            else:
                self._load_image(src[6:], keep_view)
        except Exception:
            bridge.log("Image Editor: " + traceback.format_exc(), "WARNING")

    def _render(self):
        mw = self.mw
        if mw is not None and hasattr(mw, "render_image"):
            mw.render_image()
        else:
            bridge.run_op("render.render", invoke=True)

    def _load_compositor(self, keep_view):
        tree = comp_tree()
        if tree is None:
            self._set_picture(None)
            self._set_hint("The scene has no compositor nodes.", "Create Compositor Nodes", self._create_nodes)
            return
        if self.source == SRC_COMP:
            try:
                ok = follow_output(tree)
            except Exception as ex:
                ok = True
                bridge.log(f"Image Editor: {ex}", "WARNING")
            if not ok:
                self._set_picture(None)
                self._set_hint("Nothing is connected to the compositor's output (Group Output).",
                               "Show the Viewer Node", lambda: self.set_source(SRC_VIEWER))
                return
        elif not viewer_nodes(tree):
            self._set_picture(None)
            self._set_hint("The compositor has no Viewer node – the Image Editor shows the Viewer's picture.",
                           "Add Viewer Node", self._add_viewer)
            return
        if self.isVisible() and not LINK.active():
            LINK.acquire()
        img = bpy.data.images.get(VIEWER)
        q = read_blender_image(img, "qtshell_image_viewer.png") if img is not None and img.size[0] > 0 else None
        if q is None:
            self._set_picture(None)
            if bpy.data.images.get("Render Result") is None or not bpy.data.images["Render Result"].has_data:
                self._set_hint("Nothing rendered yet – the compositor works on the rendered image.",
                               "Render (F12)", self._render)
            else:
                self._set_hint("Compositing…")
            return
        self._set_hint("")
        self._set_picture(q, keep_view)

    def _create_nodes(self):
        try:
            ensure_compositor(viewer=True)
            bridge.undo_push("Create Compositor Nodes")
        except Exception as ex:
            bridge.log(f"Image Editor: {ex}", "ERROR")
        self._update_link()
        self._comp_changed()
        self.reload()

    def _add_viewer(self):
        self._create_nodes()

    def _load_render(self, keep_view):
        img = bpy.data.images.get("Render Result")
        q = read_blender_image(img, "qtshell_image_render.png") if img is not None else None
        if q is None:
            self._set_picture(None)
            self._set_hint("Nothing rendered yet.", "Render (F12)", self._render)
            return
        self._set_hint("")
        self._set_picture(q, keep_view)

    def _load_image(self, name, keep_view):
        img = bpy.data.images.get(name)
        if img is None:
            self._set_picture(None)
            self._set_hint(f"The image '{name}' is gone.")
            return
        q = None
        if img.source in ("FILE", "SEQUENCE", "MOVIE") and img.packed_file is None:
            path = bpy.path.abspath(img.filepath_from_user() if hasattr(img, "filepath_from_user") else img.filepath)
            if path and os.path.isfile(path):
                q = load_image(path)
        if q is None:
            q = read_blender_image(img, "qtshell_image_other.png")
        if q is None:
            self._set_picture(None)
            self._set_hint(f"'{name}' has no pixels to show.")
            return
        self._set_hint("")
        self._set_picture(q, keep_view)

    # --- rendered animation
    @staticmethod
    def _anim_frames(info=None):
        info = info or {}
        return {f: p for f, p in info.get("frames", {}).items() if os.path.isfile(p)}

    def _clear_anim(self):
        self._anim = None
        self._frames.clear()
        self._frames_bytes = 0
        self._comp_frames.clear()
        self._comp_bytes = 0
        self._comp_sig = None
        self._files_sig = None
        self._pending = None

    def _load_animation(self, keep_view):
        info = output_info()
        if info.get("movie") and not self._raw_frames():
            self._anim = None
            self._set_picture(None)
            self._set_hint("The animation was rendered to a movie file – Render → View Animation plays it.",
                           "View Animation", self._view_animation)
            self._sync_frame_controls()
            return
        files = self._anim_frames(info)
        self._raw = self._raw_frames()  # kept with Live off too – turning it on again shows the cache at once
        self._sync_range()
        sig = (_files_sig(files), _files_sig(self._raw))
        if sig != self._files_sig:               # new / re-rendered frames → read and composite them again
            self._frames.clear()
            self._frames_bytes = 0
            self._comp_frames.clear()
            self._comp_bytes = 0
            self._comp_sig = None
            self._files_sig = sig
        self._anim = dict(info, frames=files)
        if not files and not self._raw:
            self._set_picture(None)
            self._set_hint("No rendered frames in the output folder "
                           f"({bpy.context.scene.render.filepath or '//'}).", "Render Animation (Ctrl+F12)",
                           self._render_animation)
            self._sync_frame_controls()
            return
        if self.live and not self._raw:
            self._set_hint("Live applies the compositor nodes to the animation: Qt Shell renders its frames once "
                           "without compositing (OpenEXR in a temporary folder), then composites and caches them "
                           "in the background.", "Render Frames for the Compositor", self.render_raw)
        else:
            self._set_hint("")
        f = self._frame
        if self.follow_btn.isChecked():
            f = bpy.context.scene.frame_current
        avail = self._available()
        if f is None or f not in avail:
            f = f if f is not None else min(avail)
            f = min(avail, key=lambda k: abs(k - f))
        self._frame = f
        self._sync_frame_controls()
        self.set_frame(f, keep_view=keep_view)
        if self.live and self._raw and self.isVisible():
            self._start_cache()

    def _available(self):
        return set((self._anim or {}).get("frames") or {}) | set(self._raw)

    def _view_animation(self):
        mw = self.mw
        if mw is not None and hasattr(mw, "view_animation"):
            mw.view_animation()

    def _render_animation(self):
        mw = self.mw
        if mw is not None and hasattr(mw, "render_image"):
            mw.render_image(animation=True)

    def _sync_frame_controls(self):
        avail = self._available() if self.source == SRC_ANIM else set()
        lo, hi = (min(avail), max(avail)) if avail else (0, 0)
        w = self.frame_spin
        w.blockSignals(True)
        w.setRange(lo, hi)
        if self._frame is not None:
            w.setValue(self._frame)
        w.blockSignals(False)
        self._update_bar()

    def _update_bar(self):
        avail = self._available() if self.source == SRC_ANIM else set()
        if not avail:
            self.frame_bar.set_state(0, 0, (), (), None)
            return
        lo, hi = self.cache_range() if self.live else (min(avail), max(avail))
        self.frame_bar.set_state(min(lo, min(avail)), max(hi, max(avail)), avail,
                                 self._comp_frames.keys() if (self.live and self._raw) else (), self._frame)

    def _frame_image(self, f):
        q = self._frames.get(f)
        if q is not None:
            return q
        path = (self._anim or {}).get("frames", {}).get(f) or self._raw.get(f)
        if not path:
            return None
        q = load_image(path)
        if q is None or q.isNull():
            return None
        self._frames[f] = q
        self._frames_bytes += q.sizeInBytes()
        while self._frames_bytes > FRAME_CACHE and len(self._frames) > 1:
            k = next(iter(self._frames))
            if k == f:
                break
            self._frames_bytes -= self._frames.pop(k).sizeInBytes()
        return q

    def set_frame(self, f, from_ui=False, keep_view=True):
        """Rendered Animation: shows frame f (the nearest rendered one)."""
        if self.source != SRC_ANIM or self._anim is None:
            return False
        frames = self._available()
        if not frames:
            return False
        f = int(f)
        if f not in frames:
            f = min(frames, key=lambda k: abs(k - f))
        if from_ui and self.follow_btn.isChecked() and not self._play.isActive():
            # scrubbing here moves the scene too (Follow Timeline keeps both on the same frame)
            try:
                if bpy.context.scene.frame_current != f:
                    bpy.context.scene.frame_set(f)
            except Exception:
                pass
        self._frame = f
        w = self.frame_spin
        if w.value() != f:
            w.blockSignals(True)
            w.setValue(f)
            w.blockSignals(False)
        comp = self.live and bool(self._raw)
        q = self._comp_frames.get(f) if comp else None
        if q is None:
            q = self._frame_image(f)         # the rendered file until the composited frame is cached
            if comp:
                self._start_cache()           # the frame shown comes first
        self._update_bar()
        if q is None:
            self._set_picture(None)
            self.canvas.hint = f"Frame {f} can't be read."
            self.canvas.update()
            return False
        if self.canvas.hint:
            self.canvas.hint = ""
        self._set_picture(q, keep_view)
        return True

    def step(self, n):
        if self._frame is not None:
            frames = sorted(self._available())
            if frames:
                i = frames.index(self._frame) if self._frame in frames else 0
                self.set_frame(frames[(i + n) % len(frames)], from_ui=True)

    def is_playing(self):
        return self._play.isActive()

    def toggle_play(self):
        if self._play.isActive():
            self.pause()
        else:
            self.play()

    def play(self):
        if self.source != SRC_ANIM or not self._available():
            return False
        fps = (self._anim or {}).get("fps") or 24.0
        self._play.start(max(1, int(round(1000.0 / fps))))
        icons.set_icon(self.play_btn, "pause")
        return True

    def pause(self):
        if self._play.isActive():
            self._play.stop()
        icons.set_icon(self.play_btn, "play")

    def _play_tick(self):
        frames = sorted(self._available())
        if not frames:
            self.pause()
            return
        i = frames.index(self._frame) if self._frame in frames else -1
        self.set_frame(frames[(i + 1) % len(frames)])

    def _on_frame_changed(self, f):
        if self.source == SRC_ANIM and self.follow_btn.isChecked() and not self._play.isActive() \
                and self.isVisible() and self._anim is not None and f != self._frame:
            self.set_frame(f)

    # --- compositor over the rendered animation
    def render_raw(self):
        """Renders the animation once without compositing into a temporary folder (OpenEXR) – the input that
        Live composites with the current nodes."""
        mw = self.mw
        if mw is not None and mw.is_rendering():
            self._status("A render is running – Re-render when it has finished.", 4000)
            return False
        # the temporary node goes first: its image holds the old frames (Blender caches image sequences)
        self._stop_cache()
        sc = bpy.context.scene
        r = sc.render
        s = r.image_settings
        keep = {"filepath": r.filepath, "use_compositing": r.use_compositing,
                "use_file_extension": getattr(r, "use_file_extension", True)}
        lo, hi = self.cache_range()
        scene_keep = {"frame_start": sc.frame_start, "frame_end": sc.frame_end}
        self._raw_folder = None                 # the new frames go to this file's own cache folder
        _s, img_keep = _save_settings()
        self._raw_keep = (keep, img_keep, scene_keep)
        try:
            sc.frame_start, sc.frame_end = min(lo, hi), max(lo, hi)     # From / To
            os.makedirs(raw_dir(sc), exist_ok=True)
            r.filepath = os.path.join(raw_dir(sc), RAW_PREFIX)
            r.use_compositing = False
            r.use_file_extension = True
            if hasattr(s, "media_type"):
                s.media_type = "IMAGE"
            s.file_format = "OPEN_EXR"
            s.color_mode = "RGBA"
            s.color_depth = "16"
        except Exception:
            self._restore_raw_settings()
            raise
        self._status("Rendering the frames for the compositor…", 4000)
        if mw is not None and hasattr(mw, "render_image"):
            mw.render_image(animation=True)
            if not mw.is_rendering():               # blocking fallback: already done
                self._on_render_done()
        else:
            with bridge.blender_context():
                bpy.ops.render.render(animation=True)
            self._on_render_done()

    def _restore_raw_settings(self):
        if self._raw_keep is None:
            return
        keep, img_keep, scene_keep = self._raw_keep
        self._raw_keep = None
        sc = bpy.context.scene
        r = sc.render
        for k, v in keep.items():
            try:
                setattr(r, k, v)
            except Exception:
                pass
        _restore_settings(r.image_settings, img_keep)
        for k, v in scene_keep.items():
            try:
                setattr(sc, k, v)
            except Exception:
                pass

    def cache_range(self):
        """(from, to) of the frames for the compositor (default: the scene's frame range)."""
        if self._range is not None:
            return self._range
        from .anim_player import scene_range
        return tuple(scene_range())

    def set_cache_range(self, start=None, end=None):
        """From / To of the compositor cache; None, None = the scene's frame range again."""
        self._range = None if start is None and end is None else (int(start), int(end))
        self._sync_range()
        if self.source == SRC_ANIM:
            self.reload()

    def _sync_range(self):
        lo, hi = self.cache_range()
        for sp, v in ((self.from_spin, lo), (self.to_spin, hi)):
            if sp.value() != v:
                sp.blockSignals(True)
                sp.setValue(v)
                sp.blockSignals(False)

    def _range_changed(self):
        lo, hi = self.from_spin.value(), self.to_spin.value()
        self._range = (min(lo, hi), max(lo, hi))
        if self.source == SRC_ANIM:
            self.reload()

    def _raw_frames(self):
        lo, hi = self.cache_range()
        return raw_frames(None, lo, hi, self._raw_folder)

    def use_frames(self, folder=None):
        """The compositor works on the frames in folder (rendered before – any image sequence); None = this file's
        own frames."""
        self._stop_cache()
        self._raw_folder = folder or None
        if folder:
            seq = scan_sequence(folder)
            if seq:
                self._range = (min(seq), max(seq))
                self._sync_range()
                size = image_size(seq[min(seq)])
                rw, rh = render_size()
                if size and (size[0] < rw or size[1] < rh):
                    self._status(f"These frames are {size[0]} × {size[1]} – smaller than the render ({rw} × {rh}). "
                                 "Re-render for the full resolution.", 8000)
                    self._clear_anim()
                    self.reload(keep_view=False)
                    return
        self._clear_anim()
        self.reload()
        if folder:
            self._status(f"Image Editor: compositing the frames in {folder}", 5000)

    def _fill_earlier_menu(self):
        m = self.earlier_menu
        m.clear()
        own = raw_dir()
        a = m.addAction("This file's frames" + ("  ✓" if self._raw_folder is None else ""))
        a.triggered.connect(lambda _c=False: self.use_frames(None))
        m.addSeparator()
        rw, rh = render_size()
        folders = cache_folders()[:15]
        for folder, seq, mt in folders:
            name = os.path.basename(folder)
            size = image_size(seq[min(seq)])
            res = f"{size[0]} × {size[1]}" if size else "?"
            label = (f"{name}  –  {res}  –  frames {min(seq)}–{max(seq)} ({len(seq)}), "
                     f"{time.strftime('%d.%m. %H:%M', time.localtime(mt))}")
            if size and (size[0] < rw or size[1] < rh):
                label += f"   ⚠ smaller than the render ({rw} × {rh})"
            if os.path.normcase(folder) == os.path.normcase(self._raw_folder or own):
                label += "  ✓"
            act = m.addAction(label)
            act.triggered.connect(lambda _c=False, d=folder: self.use_frames(d))
        if folders:
            dm = m.addMenu("Delete Frames")
            dm.setToolTip("Deletes a folder of frames rendered for the compositor (temporary files)")
            for folder, seq, _mt in folders:
                size = image_size(seq[min(seq)])
                res = f"{size[0]} × {size[1]}" if size else "?"
                da = dm.addAction(f"{os.path.basename(folder)}  –  {res}, {len(seq)} frames")
                da.triggered.connect(lambda _c=False, d=folder: self._delete_frames(d))
        m.addSeparator()
        b = m.addAction("Browse Folder…")
        b.setToolTip("Any folder with an image sequence – best OpenEXR rendered without compositing "
                     "(frames that already went through the compositor would get it twice)")
        b.triggered.connect(lambda _c=False: self._browse_frames())

    def _delete_frames(self, folder):
        if QtWidgets.QMessageBox.question(self, "Delete Frames", f"Delete the frames in\n{folder}?") \
                != QtWidgets.QMessageBox.Yes:
            return
        base = os.path.normcase(os.path.join(tempfile.gettempdir(), "qtshell_comp_cache"))
        if not os.path.normcase(os.path.abspath(folder)).startswith(base):
            return                               # only Qt Shell's own cache folders
        using = os.path.normcase(folder) == os.path.normcase(self._raw_folder or raw_dir())
        if using:
            self._stop_cache()
        try:
            shutil.rmtree(folder)
        except Exception as ex:
            QtWidgets.QMessageBox.warning(self, "Delete Frames", str(ex))
            return
        if using:
            self._raw_folder = None
            self._clear_anim()
            self.reload()
        self._status(f"Deleted {folder}", 4000)

    def _browse_frames(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Frames for the Compositor",
                                                       self._raw_folder or raw_dir())
        if d:
            if not scan_sequence(d):
                QtWidgets.QMessageBox.information(self, "Frames for the Compositor",
                                                  "No image sequence (name + frame number) in this folder.")
                return
            self.use_frames(d)

    def _start_cache(self):
        if self.live and self._raw and self.source == SRC_ANIM and self.isVisible() \
                and not self._cache_timer.isActive():
            self._update_link()
            self._cache_timer.start()

    def _nodes_changed(self):
        """Nodes were added / removed behind the Node editor's back – it must drop its items of removed nodes now,
        before its next paint (their Python objects point to freed memory)."""
        ne = getattr(self.mw, "node_editor", None) if self.mw is not None else None
        if ne is not None:
            try:
                ne.refresh()
            except Exception:
                bridge.log(traceback.format_exc(), "WARNING")

    def _stop_cache(self):
        self._cache_timer.stop()
        self._pending = None
        try:
            if ANIM_COMP.uninstall():
                self._nodes_changed()
        except Exception:
            bridge.log(traceback.format_exc(), "WARNING")

    def _store_comp(self, f, q):
        old = self._comp_frames.pop(f, None)
        if old is not None:
            self._comp_bytes -= old.sizeInBytes()
        self._comp_frames[f] = q
        self._comp_bytes += q.sizeInBytes()
        while self._comp_bytes > FRAME_CACHE and len(self._comp_frames) > 1:
            k = max(self._comp_frames, key=lambda x: abs(x - (self._frame or f)))
            self._comp_bytes -= self._comp_frames.pop(k).sizeInBytes()

    def _cache_tick(self):
        """One step of compositing the raw frames: the temporary Image node shows frame f, Blender's compositor
        runs (COMPOSITE job), the Viewer is read and cached. A change of the nodes starts over."""
        if not (self.live and self._raw and self.source == SRC_ANIM and self.isVisible()):
            self._stop_cache()
            return
        if bridge.is_rendering():
            return
        tree = comp_tree()
        if tree is None or not any(n.bl_idname == "CompositorNodeRLayers" for n in tree.nodes):
            self._stop_cache()
            return
        try:
            sig = tree_signature(tree)
        except Exception:
            sig = None
        if sig != self._comp_sig:
            self._comp_sig = sig
            self._comp_frames.clear()
            self._comp_bytes = 0
            self._pending = None
            try:
                follow_output(tree)
            except Exception:
                pass
            self._update_bar()
        now = time.monotonic()
        try:
            running = bpy.app.is_job_running("COMPOSITE")
        except Exception:
            running = False
        if self._pending is not None:
            f, t0, saw, cfra = self._pending
            if running:
                self._pending = (f, t0, True, cfra)
                return
            dt = now - t0
            if dt < 0.04 or (not saw and dt < 0.4):
                return
            self._pending = None
            if bpy.context.scene.frame_current != cfra:
                return                          # the scene frame moved meanwhile – that picture is not frame f
            img = bpy.data.images.get(VIEWER)
            q = read_blender_image(img, "qtshell_image_anim.png") if img is not None and img.size[0] > 0 else None
            if q is not None:
                self._store_comp(f, q)
                if f == self._frame and self.source == SRC_ANIM:
                    self._set_picture(q, True)
                self._update_bar()
                self._update_footer()
            return
        if running:
            return
        # next frame: the one shown, then onwards from it
        order = sorted(self._raw)
        cur = self._frame if self._frame in self._raw else order[0]
        i = order.index(cur)
        todo = next((x for x in order[i:] + order[:i] if x not in self._comp_frames), None)
        if todo is None:
            self._stop_cache()                  # all cached – the node tree gets its links back
            self._update_footer()
            return
        try:
            fresh = ANIM_COMP.node(tree) is None
            if ANIM_COMP.install(tree, self._raw) is None:
                self._stop_cache()
                return
            if fresh:
                self._nodes_changed()
            ANIM_COMP.set_frame(tree, todo)
        except Exception:
            bridge.log("Image Editor: " + traceback.format_exc(), "WARNING")
            self._stop_cache()
            return
        self._pending = (todo, now, False, bpy.context.scene.frame_current)

    def _on_anim_nodes_changed(self):
        """Live over the animation: a change of the compositor nodes composites the frames again."""
        if self.source == SRC_ANIM and self.live and self._raw and self.isVisible():
            self._start_cache()

    # --- picture
    def _set_picture(self, q, keep_view=True):
        self.base = q
        self._show(keep_view)

    def _show(self, keep_view=True):
        img = apply_channel(self.base, self.channel) if self.base is not None else None
        self.canvas.set_image(img, keep_view)
        self._update_footer()

    def _on_sample(self, s):
        self._sample = s
        self._update_footer()

    def _update_footer(self):
        parts = []
        if self.base is not None:
            size = f"{self.base.width()} × {self.base.height()}"
            if self.source == SRC_ANIM:
                rw, rh = render_size()
                if (self.base.width(), self.base.height()) != (rw, rh):
                    size += f" (render {rw} × {rh})"
            parts.append(size)
        label = SOURCE_LABELS.get(self.source) or self.source[6:]
        if self.source == SRC_ANIM and self._frame is not None:
            label += f" · frame {self._frame}"
            if self.live and self._raw:
                n, total = len(self._comp_frames), len(self._raw)
                label += " · composited" if self._frame in self._comp_frames else " · compositing…"
                label += f" ({n} / {total} cached)"
        parts.append(label)
        parts.append(f"{self.canvas.zoom * 100:.0f} %")
        if self._sample is not None:
            x, y, c = self._sample
            parts.append(f"X {x}  Y {y}   R {c.redF():.3f}  G {c.greenF():.3f}  B {c.blueF():.3f}  A {c.alphaF():.3f}")
        self.footer.setText("   ·   ".join(parts))

    def fit(self):
        self.canvas.fit()

    def zoom(self, ratio):
        self.canvas.set_zoom(float(ratio) * self.canvas.devicePixelRatioF())

    # --- compositor updates
    def _on_data_changed(self):
        if self.source == SRC_ANIM:
            self._on_anim_nodes_changed()
            return
        if self.source in COMP_SOURCES and self.live and self.isVisible():
            if self.source == SRC_COMP:
                tree = comp_tree()
                if tree is not None:
                    try:
                        follow_output(tree)        # a node put before the output → the Viewer moves along
                    except Exception as ex:
                        bridge.log(f"Image Editor: {ex}", "WARNING")
            self._comp_changed()
        elif self.source.startswith("IMAGE:") and self.isVisible():
            pass

    def _comp_changed(self):
        """Something changed: watch Blender's COMPOSITE job and show the Viewer when it has finished."""
        self._comp_dirty = True
        self._watch_until = time.monotonic() + 0.5
        if not self._watch.isActive():
            self._watch.start()

    def _watch_tick(self):
        now = time.monotonic()
        try:
            running = bpy.app.is_job_running("COMPOSITE")
        except Exception:
            running = False
        if running:
            self._saw_job = True
            self._watch_until = max(self._watch_until, now + 0.3)
            return
        if self._saw_job:
            self._saw_job = False
            self._comp_dirty = False
            self.reload()
            self._watch_until = now + 0.2      # a following change may start another run
            return
        if now >= self._watch_until:
            self._watch.stop()
            if self._comp_dirty:
                # no job was seen (it may have run between two checks, or nothing changed for it)
                self._comp_dirty = False
                self.reload()

    def _on_render_done(self):
        self._restore_raw_settings()
        if self.source == SRC_ANIM or not self.isVisible():
            self._clear_anim()                 # new frames on disk – read them again when shown
        if not self.isVisible():
            return
        if self.source in COMP_SOURCES or self.source == SRC_RENDER:
            QtCore.QTimer.singleShot(50, self.reload)
            if self.source in COMP_SOURCES:
                self._comp_changed()
        elif self.source == SRC_ANIM:
            self._anim = None
            QtCore.QTimer.singleShot(50, lambda: self.reload(keep_view=True))

    def _on_file_loaded(self):
        self.pause()
        self._stop_cache()
        ANIM_COMP.moved = []
        self._clear_anim()
        if self.source.startswith("IMAGE:"):
            self.source = SRC_COMP
        self.fill_sources()
        self._update_controls()
        if self.isVisible():
            QtCore.QTimer.singleShot(200, lambda: (self._update_link(), self.reload(keep_view=False)))

    # --- export
    def copy_to_clipboard(self):
        if self.canvas.image is not None:
            QtWidgets.QApplication.clipboard().setImage(self.canvas.image)
            self._status("Image copied to the clipboard")

    def _status(self, text, ms=5000):
        mw = self.mw
        if mw is not None:
            mw.statusBar().showMessage(text, ms)
        else:
            bridge.log(text)

    def _blender_image(self):
        """The Blender image behind the current picture (saved by Blender – keeps float values), or None."""
        if self.source in COMP_SOURCES:
            return bpy.data.images.get(VIEWER)
        if self.source == SRC_RENDER:
            return bpy.data.images.get("Render Result")
        if self.source.startswith("IMAGE:"):
            img = bpy.data.images.get(self.source[6:])
            if img is not None and (img.packed_file is not None or img.source == "GENERATED"):
                return img
        return None

    def _source_file(self):
        if self.source == SRC_ANIM and self._frame is not None:
            return (self._anim or {}).get("frames", {}).get(self._frame)
        if self.source.startswith("IMAGE:"):
            img = bpy.data.images.get(self.source[6:])
            if img is not None and img.packed_file is None and img.source == "FILE":
                p = bpy.path.abspath(img.filepath)
                return p if os.path.isfile(p) else None
        return None

    def _default_dir(self):
        if self._export_path:
            return os.path.dirname(self._export_path)
        return os.path.dirname(bpy.path.abspath(bpy.data.filepath)) if bpy.data.filepath else os.path.expanduser("~")

    def export_image(self, path=None):
        """Saves the picture shown (the format follows the extension: .png .jpg .exr .tif .webp .bmp).
        Compositor / Render Result are saved by Blender (OpenEXR keeps float values, the view transform
        applies to 8-bit formats); animation frames / image files are converted (or copied when the format
        is the same). Without a path a file dialog asks."""
        if self.base is None:
            return False
        fmt = None
        if not path:
            name = {SRC_COMP: "compositor", SRC_VIEWER: "viewer", SRC_RENDER: "render"}.get(self.source) or (
                f"frame_{self._frame:04d}" if self.source == SRC_ANIM and self._frame is not None
                else os.path.splitext(self.source[6:])[0])
            start = os.path.join(self._default_dir(), name + ".png")
            path, flt = QtWidgets.QFileDialog.getSaveFileName(self, "Export Image", start,
                                                              ";;".join(f[0] for f in IMAGE_FORMATS))
            if not path:
                return False
            fmt = next((f for f in IMAGE_FORMATS if f[0] == flt), None)
            if fmt is not None and not os.path.splitext(path)[1]:
                path += fmt[3]
        ext = os.path.splitext(path)[1].lower()
        fmt = next((f for f in IMAGE_FORMATS if f[3] == ext or (ext == ".jpeg" and f[2] == "JPEG")
                    or (ext == ".tiff" and f[2] == "TIFF")), fmt or IMAGE_FORMATS[0])
        try:
            if os.path.dirname(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            img = self._blender_image()
            src = self._source_file()
            if img is not None:
                save_blender_image(img, path, fmt[2], fmt[1])
            elif src and os.path.splitext(src)[1].lower() == ext:
                shutil.copyfile(src, path)
            elif fmt[2] == "OPEN_EXR":
                if not src:
                    raise RuntimeError("OpenEXR needs the compositor, a render or an image file")
                _convert_oiio(src, path)
            else:
                q = self.base
                if fmt[2] in ("JPEG", "BMP"):
                    q = q.convertToFormat(QtGui.QImage.Format_RGB32)
                if not q.save(path):
                    raise RuntimeError("Qt can't write this file")
        except Exception as ex:
            QtWidgets.QMessageBox.warning(self, "Export Image", f"Cannot save the image:\n{path}\n\n{ex}")
            return False
        self._export_path = path
        self._status(f"Exported {path}")
        return True

    def export_animation(self, path=None, kind=None, start=None, end=None):
        """Exports the rendered animation: kind MP4 (video), PNG / JPEG / TIFF (image sequence – path is the
        first file, frame numbers are added) or COPY (the rendered files copied into the folder of path).
        Without a path a dialog asks for the format, frame range and file."""
        info = output_info()
        frames = self._anim_frames(info)
        if self.source == SRC_ANIM and self.live and self._raw:
            # Live: the frames composited with the current nodes (all of them must be cached)
            missing = [f for f in self._raw if f not in self._comp_frames]
            if missing:
                QtWidgets.QMessageBox.information(
                    self, "Export Animation", f"{len(missing)} frames are still being composited – export when the "
                    "timeline is all green (or turn Live off to export the rendered files).")
                return False
            folder = os.path.join(raw_dir(), "composited")
            os.makedirs(folder, exist_ok=True)
            frames = {}
            for f, q in sorted(self._comp_frames.items()):
                fp = os.path.join(folder, f"comp_{f:04d}.png")
                q.save(fp)
                frames[f] = fp
        if not frames:
            QtWidgets.QMessageBox.information(self, "Export Animation",
                                              "No rendered frames – Render Animation first (Output Properties → "
                                              "Output path, image format).")
            return False
        lo, hi = min(frames), max(frames)
        if path is None:
            dlg = ExportAnimationDialog(self, lo, hi, self._default_dir())
            if dlg.exec() != QtWidgets.QDialog.Accepted:
                return False
            path, kind, start, end = dlg.result_values()
        kind = (kind or "MP4").upper()
        start = lo if start is None else int(start)
        end = hi if end is None else int(end)
        sel = [(f, frames[f]) for f in sorted(frames) if start <= f <= end]
        if not sel:
            return False
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            if kind == "MP4":
                if not os.path.splitext(path)[1]:
                    path += ".mp4"
                encode_video([p for _f, p in sel], path, info.get("fps") or 24.0)
                msg = f"Exported {len(sel)} frames to {path}"
            else:
                n = export_sequence(sel, path, kind)
                msg = f"Exported {n} frames to {os.path.dirname(path) or path}"
        except Exception as ex:
            bridge.log(traceback.format_exc(), "WARNING")
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.warning(self, "Export Animation", f"Export failed:\n{ex}")
            return False
        QtWidgets.QApplication.restoreOverrideCursor()
        self._export_path = path
        self._status(msg, 8000)
        return True

    # --- keys
    def keyPressEvent(self, ev):
        def H(aid):
            return keymap.hit(aid, ev)
        if H("image.fit"):
            self.fit()
        elif H("image.zoom_1_1"):
            self.zoom(1)
        elif H("image.zoom_in"):
            self.canvas.set_zoom(self.canvas.zoom * 1.25)
        elif H("image.zoom_out"):
            self.canvas.set_zoom(self.canvas.zoom * 0.8)
        elif H("image.reload"):
            self.refresh()
        elif H("image.export"):
            self.export_image()
        elif H("image.play") and self.source == SRC_ANIM:
            self.toggle_play()
        elif H("image.frame_prev") and self.source == SRC_ANIM:
            self.step(-1)
        elif H("image.frame_next") and self.source == SRC_ANIM:
            self.step(1)
        else:
            super().keyPressEvent(ev)
            return
        ev.accept()


# ---------------------------------------------------------------- export helpers
def _convert_oiio(src, dst):
    import OpenImageIO as oiio
    buf = oiio.ImageBuf(src)
    if buf.has_error or not buf.write(dst):
        raise RuntimeError(buf.geterror() or oiio.geterror())


def _seq_path(path, f, ext):
    root, e = os.path.splitext(path)
    root = root.rstrip("#_.-") if root.rstrip("#_.-") else root
    return f"{root}_{f:04d}{ext or e}"


def export_sequence(frames, path, kind):
    """frames: [(frame, file)] → image files next to path (name_0001.png …). kind PNG / JPEG / TIFF / COPY."""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    ext = {"PNG": ".png", "JPEG": ".jpg", "TIFF": ".tif"}.get(kind)
    n = 0
    for f, src in frames:
        if kind == "COPY":
            dst = os.path.join(folder, os.path.basename(src))
            if os.path.normcase(os.path.abspath(dst)) != os.path.normcase(os.path.abspath(src)):
                shutil.copyfile(src, dst)
        else:
            dst = _seq_path(path, f, ext)
            if os.path.splitext(src)[1].lower() == ext:
                shutil.copyfile(src, dst)
            else:
                q = load_image(src)
                if q is None:
                    raise RuntimeError(f"Cannot read {src}")
                if kind == "JPEG":
                    q = q.convertToFormat(QtGui.QImage.Format_RGB32)
                if not q.save(dst):
                    raise RuntimeError(f"Cannot write {dst}")
        n += 1
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents)
    return n


def encode_video(files, path, fps):
    """MP4 (H.264) from image files – Blender's sequencer renders them in a temporary scene (removed after)."""
    first = load_image(files[0])
    if first is None:
        raise RuntimeError(f"Cannot read {files[0]}")
    w, h = first.width() - first.width() % 2, first.height() - first.height() % 2   # H.264 wants even sizes
    folder = os.path.dirname(files[0])
    src = bpy.context.scene
    tmp = bpy.data.scenes.new("QtShell Video Export")
    try:
        r = tmp.render
        r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
        fps_i = int(round(fps))
        r.fps, r.fps_base = (fps_i, fps_i / fps) if fps > 0 else (24, 1.0)
        tmp.frame_start, tmp.frame_end = 1, len(files)
        # the frames already are display colours – no second view transform
        try:
            tmp.view_settings.view_transform = "Standard"
            tmp.view_settings.look = "None"
            tmp.view_settings.exposure = 0.0
            tmp.view_settings.gamma = 1.0
        except Exception:
            pass
        ims = r.image_settings
        if hasattr(ims, "media_type"):
            ims.media_type = "VIDEO"
        ims.file_format = "FFMPEG"
        ff = r.ffmpeg
        ff.format = "MPEG4"
        ff.codec = "H264"
        try:
            ff.constant_rate_factor = "HIGH"
        except Exception:
            pass
        ff.audio_codec = "NONE"
        r.filepath = path
        try:
            r.use_file_extension = False
        except Exception:
            pass
        se = tmp.sequence_editor_create()
        coll = se.strips if hasattr(se, "strips") else se.sequences       # Blender 5: strips
        strip = coll.new_image("frames", files[0], 1, 1)
        for p in files[1:]:
            if os.path.dirname(p) != folder:
                raise RuntimeError("All frames must be in one folder")
            strip.elements.append(os.path.basename(p))
        try:
            strip.colorspace_settings.name = "sRGB"
        except Exception:
            pass
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        with bridge.blender_context(scene=tmp):
            bpy.ops.render.render(animation=True, scene=tmp.name)
    finally:
        try:
            win = bpy.context.window_manager.windows[0]
            if win.scene != src:
                win.scene = src
        except Exception:
            pass
        bpy.data.scenes.remove(tmp)
    if not os.path.isfile(path):
        raise RuntimeError("Blender wrote no video file")


class ExportAnimationDialog(QtWidgets.QDialog):
    def __init__(self, parent, lo, hi, folder):
        super().__init__(parent)
        self.setWindowTitle("Export Animation")
        lay = QtWidgets.QFormLayout(self)
        self.kind = QtWidgets.QComboBox(self)
        for ident, label, _ext in ANIM_FORMATS:
            self.kind.addItem(label, ident)
        lay.addRow("Format", self.kind)
        rng = QtWidgets.QHBoxLayout()
        self.start = QtWidgets.QSpinBox(self)
        self.end = QtWidgets.QSpinBox(self)
        for s, v in ((self.start, lo), (self.end, hi)):
            s.setRange(lo, hi)
            s.setValue(v)
            rng.addWidget(s)
        lay.addRow("Frames", rng)
        row = QtWidgets.QHBoxLayout()
        self.path = QtWidgets.QLineEdit(os.path.join(folder, "animation.mp4"), self)
        row.addWidget(self.path, 1)
        browse = QtWidgets.QPushButton("…", self)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        lay.addRow("File", row)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("Export")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)
        self.resize(theme.px(520), self.sizeHint().height())

    def _ext(self):
        return next(e for i, _l, e in ANIM_FORMATS if i == self.kind.currentData())

    def _kind_changed(self):
        p = self.path.text()
        root = os.path.splitext(p)[0] if os.path.splitext(p)[1] else p
        ext = self._ext()
        self.path.setText(root + ext if ext else os.path.join(os.path.dirname(p), ""))

    def _browse(self):
        if self._ext() is None:
            d = QtWidgets.QFileDialog.getExistingDirectory(self, "Export to Folder", os.path.dirname(self.path.text()))
            if d:
                self.path.setText(os.path.join(d, ""))
            return
        p, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Export Animation", self.path.text())
        if p:
            self.path.setText(p)

    def result_values(self):
        return (self.path.text(), self.kind.currentData(), min(self.start.value(), self.end.value()),
                max(self.start.value(), self.end.value()))

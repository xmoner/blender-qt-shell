"""Video Sequencer → Export: the edit rendered by Blender to a video file, an image sequence or a sound file.

The scene's own output settings are only borrowed: `apply()` sets format / codec / range / size / path,
the render runs like Render → Render Animation (hidden helper window, progress in the status bar,
cancel), and `restore()` puts every setting back when it ends (main window `_render_done_hooks`).
Sound only (WAV / MP3 / FLAC / OGG) goes through Blender's mixdown.

    import qt_shell
    vs = qt_shell.api.video_sequencer()
    vs.export_video()                                            # the dialog
    vs.export_video("C:/out/edit.mp4", "MP4_H264")               # start, end, quality, scale, audio
    qt_shell.seq_export.formats()                                # ids available in this Blender
"""
import os

import bpy
from PySide6 import QtCore, QtWidgets

from . import bridge, theme

# id, label, extension, container, video codec, audio codec
VIDEO = [
    ("MP4_H264", "MP4 – H.264 + AAC  (plays everywhere)", ".mp4", "MPEG4", "H264", "AAC"),
    ("MP4_H265", "MP4 – H.265 / HEVC + AAC  (smaller files)", ".mp4", "MPEG4", "H265", "AAC"),
    ("MP4_AV1", "MP4 – AV1 + AAC  (smallest, slow to encode)", ".mp4", "MPEG4", "AV1", "AAC"),
    ("MOV_H264", "QuickTime MOV – H.264 + AAC", ".mov", "QUICKTIME", "H264", "AAC"),
    ("MOV_PRORES", "QuickTime MOV – ProRes + PCM  (editing master)", ".mov", "QUICKTIME", "PRORES", "PCM"),
    ("MKV_H264", "Matroska MKV – H.264 + AAC", ".mkv", "MKV", "H264", "AAC"),
    ("MKV_FFV1", "Matroska MKV – FFV1 + FLAC  (lossless)", ".mkv", "MKV", "FFV1", "FLAC"),
    ("WEBM_VP9", "WebM – VP9 + Opus  (web)", ".webm", "WEBM", "WEBM", "OPUS"),
    ("AVI_H264", "AVI – H.264 + MP3", ".avi", "AVI", "H264", "MP3"),
    ("OGG_THEORA", "Ogg – Theora + Vorbis", ".ogv", "OGG", "THEORA", "VORBIS"),
]
# id, label, extension, Blender file format, colour mode, colour depth
IMAGES = [
    ("SEQ_PNG", "Image sequence – PNG", ".png", "PNG", "RGBA", "8"),
    ("SEQ_JPEG", "Image sequence – JPEG", ".jpg", "JPEG", "RGB", "8"),
    ("SEQ_TIFF", "Image sequence – TIFF", ".tif", "TIFF", "RGBA", "8"),
    ("SEQ_EXR", "Image sequence – OpenEXR (float)", ".exr", "OPEN_EXR", "RGBA", "16"),
    ("SEQ_WEBP", "Image sequence – WebP", ".webp", "WEBP", "RGBA", "8"),
]
# id, label, extension, mixdown container, mixdown codec
AUDIO = [
    ("AUDIO_WAV", "Sound only – WAV", ".wav", "WAV", "PCM"),
    ("AUDIO_MP3", "Sound only – MP3", ".mp3", "MP3", "MP3"),
    ("AUDIO_FLAC", "Sound only – FLAC", ".flac", "FLAC", "FLAC"),
    ("AUDIO_OGG", "Sound only – Ogg Vorbis", ".ogg", "OGG", "VORBIS"),
]
QUALITY = [("LOSSLESS", "Lossless"), ("HIGH", "High"), ("MEDIUM", "Medium"), ("LOW", "Low")]
JPEG_QUALITY = {"LOSSLESS": 100, "HIGH": 92, "MEDIUM": 80, "LOW": 60}
SCALES = (100, 75, 50, 25)
NO_CRF = {"PRORES", "FFV1", "THEORA"}                   # codecs without a constant-rate-factor quality


def _enum(owner, prop):
    try:
        return {e.identifier for e in owner.bl_rna.properties[prop].enum_items}
    except Exception:
        return set()


def _mixdown_enum(prop):
    try:
        return {e.identifier for e in bpy.ops.sound.mixdown.get_rna_type().properties[prop].enum_items}
    except Exception:
        return set()


def entry(fmt):
    return next((f for f in VIDEO + IMAGES + AUDIO if f[0] == fmt), None)


def kind(fmt):
    return "audio" if fmt.startswith("AUDIO_") else "images" if fmt.startswith("SEQ_") else "video"


def formats():
    """The format ids this Blender can write (its ffmpeg containers / codecs differ between builds)."""
    ff = bpy.context.scene.render.ffmpeg
    cont, vc, ac = _enum(ff, "format"), _enum(ff, "codec"), _enum(ff, "audio_codec")
    out = [f[0] for f in VIDEO if f[3] in cont and f[4] in vc and f[5] in ac]
    imgs = _enum(bpy.context.scene.render.image_settings, "file_format")
    out += [f[0] for f in IMAGES if not imgs or f[3] in imgs]
    mc, mk = _mixdown_enum("container"), _mixdown_enum("codec")
    out += [f[0] for f in AUDIO if f[3] in mc and f[4] in mk]
    return out


def strips_range():
    """(first frame, last frame) covered by the strips, or the scene range without strips."""
    sc = bpy.context.scene
    se = sc.sequence_editor
    ss = list(se.strips if hasattr(se, "strips") else se.sequences) if se is not None else []
    if not ss:
        return sc.frame_start, sc.frame_end
    return min(s.frame_final_start for s in ss), max(s.frame_final_end for s in ss) - 1


# ---------------------------------------------------------------- borrowed output settings
_R = ("filepath", "use_file_extension", "resolution_x", "resolution_y", "resolution_percentage", "use_sequencer",
      "use_overwrite", "use_placeholder")
_IMS = ("media_type", "file_format", "color_mode", "color_depth", "quality", "compression")
_FF = ("format", "codec", "constant_rate_factor", "audio_codec", "audio_bitrate", "use_lossless_output")


def snapshot():
    sc = bpy.context.scene
    r = sc.render
    keep = {"scene": sc.name, "frame_start": sc.frame_start, "frame_end": sc.frame_end,
            "frame_current": sc.frame_current, "r": {}, "ims": {}, "ff": {}}
    for names, owner, key in ((_R, r, "r"), (_IMS, r.image_settings, "ims"), (_FF, r.ffmpeg, "ff")):
        for n in names:
            if hasattr(owner, n):
                try:
                    keep[key][n] = getattr(owner, n)
                except Exception:
                    pass
    return keep


def restore(keep):
    sc = bpy.data.scenes.get(keep.get("scene", ""))
    if sc is None:
        return
    r = sc.render
    # media type first (it limits the file formats), the range last
    for owner, key, order in ((r.image_settings, "ims", _IMS), (r.ffmpeg, "ff", _FF), (r, "r", _R)):
        for n in order:
            if n in keep[key]:
                try:
                    if getattr(owner, n) != keep[key][n]:
                        setattr(owner, n, keep[key][n])
                except Exception:
                    pass
    sc.frame_start, sc.frame_end = keep["frame_start"], keep["frame_end"]


def even_size(r, scale):
    """Video encoders (H.264 …) need an even width and height – Blender writes no file otherwise. Returns the
    scene resolution (x, y) to render with: the same, or 1–3 px more where x · scale would come out odd."""
    def fix(n):
        m = int(n)
        while (m * int(scale)) // 100 % 2:
            m += 1
        return m
    return fix(r.resolution_x), fix(r.resolution_y)


def _set(owner, prop, value):
    try:
        setattr(owner, prop, value)
        return True
    except Exception:
        return False


def apply(fmt, path, start, end, quality="HIGH", scale=100, audio=True):
    """Sets the scene's output for the export (video / image sequence). Returns the path Blender is given."""
    e = entry(fmt)
    sc = bpy.context.scene
    r = sc.render
    ims = r.image_settings
    sc.frame_start, sc.frame_end = int(start), int(end)
    r.use_sequencer = True
    r.resolution_percentage = int(scale)
    _set(r, "use_overwrite", True)
    _set(r, "use_placeholder", False)
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    if kind(fmt) == "video":
        _id, _label, _ext, cont, codec, acodec = e
        r.resolution_x, r.resolution_y = even_size(r, scale)
        if hasattr(ims, "media_type"):
            ims.media_type = "VIDEO"
        _set(ims, "file_format", "FFMPEG")
        _set(ims, "color_mode", "RGB")
        _set(ims, "color_depth", "8")
        ff = r.ffmpeg
        ff.format = cont
        ff.codec = codec
        if codec not in NO_CRF:
            crf = {"LOSSLESS": "PERC_LOSSLESS"}.get(quality, quality)
            if not _set(ff, "constant_rate_factor", crf):
                _set(ff, "constant_rate_factor", "HIGH")
        ff.audio_codec = acodec if audio else "NONE"
        if audio and acodec not in ("PCM", "FLAC"):
            _set(ff, "audio_bitrate", 192)
        r.filepath = path
        _set(r, "use_file_extension", False)
        return path
    _id, _label, ext, ff_name, mode, depth = e
    if hasattr(ims, "media_type"):
        ims.media_type = "IMAGE"
    ims.file_format = ff_name
    _set(ims, "color_mode", mode)
    _set(ims, "color_depth", depth)
    if ff_name in ("JPEG", "WEBP"):
        _set(ims, "quality", JPEG_QUALITY.get(quality, 92))
    base = path[:-len(ext)] if path.lower().endswith(ext) else os.path.splitext(path)[0]
    r.filepath = base + "_####"                         # name_0001.png …
    _set(r, "use_file_extension", True)
    return r.filepath


def sequence_files(path, fmt, start, end):
    e = entry(fmt)
    ext = e[2]
    base = path[:-len(ext)] if path.lower().endswith(ext) else os.path.splitext(path)[0]
    return [f"{base}_{f:04d}{ext}" for f in range(int(start), int(end) + 1)]


def mixdown(fmt, path, start, end):
    """Sound only: starts Blender's mixdown of the range. The operator returns before the file is complete
    (Blender 5 writes it right after) – the caller waits for it with `file_settled`. Raises on failure."""
    e = entry(fmt)
    sc = bpy.context.scene
    keep = (sc.frame_start, sc.frame_end)
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        sc.frame_start, sc.frame_end = int(start), int(end)
        kw = dict(filepath=path, check_existing=False, container=e[3], codec=e[4], relative_path=False)
        if e[4] == "PCM":
            kw["format"] = "S16"
        elif e[4] != "FLAC":
            kw["bitrate"] = 192
        from .sequencer import seq_context
        with seq_context():                             # Blender 5: the mixdown is the sequencer scene's
            res = bpy.ops.sound.mixdown(**kw)
    finally:
        sc.frame_start, sc.frame_end = keep
    if "FINISHED" not in res:
        raise RuntimeError(f"Blender's mixdown did not run ({', '.join(res)})")
    return path


class file_settled:
    """Polls a file Blender is still writing: `done()` is True once it exists and its size stood still for
    three looks; `failed()` once it has not appeared for `timeout` seconds."""

    def __init__(self, path, timeout=15.0):
        import time
        self.path, self.timeout, self.t0 = path, timeout, time.monotonic()
        self.size, self.same = -1, 0

    def done(self):
        try:
            n = os.path.getsize(self.path)
        except OSError:
            return False
        self.same = self.same + 1 if n == self.size and n > 0 else 0
        self.size = n
        return self.same >= 3

    def failed(self):
        import time
        return self.size <= 0 and time.monotonic() - self.t0 > self.timeout


# ---------------------------------------------------------------- dialog
class ExportDialog(QtWidgets.QDialog):
    """Format, quality, size, frames, sound and file of a Video Sequencer export."""

    def __init__(self, parent, folder, name="edit"):
        super().__init__(parent)
        self.setWindowTitle("Export Video")
        qs = QtCore.QSettings("QtShell", "QtShell")
        sc = bpy.context.scene
        r = sc.render
        lay = QtWidgets.QFormLayout(self)
        self.fmt = QtWidgets.QComboBox(self)
        avail = formats()
        last_kind = None
        for f in VIDEO + IMAGES + AUDIO:
            if f[0] not in avail:
                continue
            if last_kind is not None and kind(f[0]) != last_kind:
                self.fmt.insertSeparator(self.fmt.count())
            last_kind = kind(f[0])
            self.fmt.addItem(f[1], f[0])
        self.fmt.setToolTip("Video with sound, an image sequence (one file per frame) or the sound alone.\n"
                            "The list shows what this Blender's FFmpeg can write.")
        lay.addRow("Format", self.fmt)
        self.quality = QtWidgets.QComboBox(self)
        for ident, label in QUALITY:
            self.quality.addItem(label, ident)
        self.quality.setToolTip("Video: constant quality of the encoder (higher = bigger file). JPEG / WebP: image quality.")
        lay.addRow("Quality", self.quality)
        self.scale = QtWidgets.QComboBox(self)
        for pct in SCALES:
            x, y = even_size(r, pct)
            self.scale.addItem(f"{pct} %  –  {x * pct // 100} × {y * pct // 100}", pct)
        self.scale.setToolTip("Size of the picture: per cent of the scene's resolution "
                              f"({r.resolution_x} × {r.resolution_y}). Videos need an even width and height – "
                              "an odd size gets a pixel more.")
        lay.addRow("Size", self.scale)
        lo, hi = strips_range()
        lo, hi = min(lo, sc.frame_start), max(hi, sc.frame_end)
        rng = QtWidgets.QHBoxLayout()
        self.start = QtWidgets.QSpinBox(self)
        self.end = QtWidgets.QSpinBox(self)
        for s, v in ((self.start, sc.frame_start), (self.end, sc.frame_end)):
            s.setRange(min(lo, 0), max(hi, 1048574))
            s.setValue(v)
            s.valueChanged.connect(self._info)
            rng.addWidget(s)
        b1 = QtWidgets.QPushButton("Scene Range", self)
        b1.setToolTip("The scene's start and end frame")
        b1.clicked.connect(lambda _=False: self.set_range(sc.frame_start, sc.frame_end))
        b2 = QtWidgets.QPushButton("All Strips", self)
        b2.setToolTip("From the first strip's start to the last strip's end")
        b2.clicked.connect(lambda _=False: self.set_range(*strips_range()))
        rng.addWidget(b1)
        rng.addWidget(b2)
        lay.addRow("Frames", rng)
        self.audio = QtWidgets.QCheckBox("Include the sound", self)
        self.audio.setChecked(True)
        lay.addRow("Sound", self.audio)
        row = QtWidgets.QHBoxLayout()
        self.path = QtWidgets.QLineEdit(os.path.join(folder, name + ".mp4"), self)
        row.addWidget(self.path, 1)
        browse = QtWidgets.QPushButton("…", self)
        browse.setToolTip("Choose the file")
        browse.clicked.connect(lambda _=False: self._browse())
        row.addWidget(browse)
        lay.addRow("File", row)
        self.info = QtWidgets.QLabel(self)
        self.info.setStyleSheet("color:#9a9a9a;")
        self.info.setWordWrap(True)
        lay.addRow("", self.info)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("Export")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)
        for combo, key, default in ((self.fmt, "sequencer/export_format", "MP4_H264"),
                                    (self.quality, "sequencer/export_quality", "HIGH"),
                                    (self.scale, "sequencer/export_scale", 100)):
            v = qs.value(key, default)
            try:
                v = int(v) if combo is self.scale else v
            except (TypeError, ValueError):
                v = default
            i = combo.findData(v)
            combo.setCurrentIndex(i if i >= 0 else max(0, combo.findData(default)))
        self.audio.setChecked(qs.value("sequencer/export_audio", True) not in (False, "false"))
        self.fmt.currentIndexChanged.connect(lambda _i: self._fmt_changed())
        self.scale.currentIndexChanged.connect(lambda _i: self._info())
        self._fmt_changed()
        self.resize(theme.px(600), self.sizeHint().height())

    def set_range(self, a, b):
        self.start.setValue(int(a))
        self.end.setValue(int(b))

    def values(self):
        return dict(path=self.path.text().strip(), fmt=self.fmt.currentData(), start=self.start.value(),
                    end=self.end.value(), quality=self.quality.currentData(), scale=self.scale.currentData(),
                    audio=self.audio.isChecked())

    def _fmt_changed(self):
        fmt = self.fmt.currentData()
        e = entry(fmt)
        k = kind(fmt)
        self.quality.setEnabled((k == "video" and e[4] not in NO_CRF) or fmt in ("SEQ_JPEG", "SEQ_WEBP"))
        self.scale.setEnabled(k != "audio")
        self.audio.setEnabled(k == "video")
        p = self.path.text().strip()
        if p:
            self.path.setText(os.path.splitext(p)[0] + e[2])
        self._info()

    def _info(self, *_a):
        fmt = self.fmt.currentData()
        r = bpy.context.scene.render
        n = max(0, self.end.value() - self.start.value() + 1)
        rate = max(r.fps / (r.fps_base or 1.0), 1.0)
        txt = f"{n} frames  ·  {n / rate:.1f} s at {rate:g} fps"
        if kind(fmt) == "images":
            e = entry(fmt)
            base = os.path.basename(os.path.splitext(self.path.text().strip() or "edit")[0])
            txt += f"  ·  files {base}_{self.start.value():04d}{e[2]} …"
        elif kind(fmt) == "video":
            txt += "  ·  rendered by Blender – cancel from the status bar"
        self.info.setText(txt)

    def _browse(self):
        e = entry(self.fmt.currentData())
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export Video", self.path.text(),
                                                     f"{e[1].split('  (')[0]} (*{e[2]});;All files (*)")
        if p:
            self.path.setText(os.path.splitext(p)[0] + e[2])

    def _accept(self):
        v = self.values()
        if not v["path"]:
            self.info.setText("Choose a file first.")
            return
        if v["end"] < v["start"]:
            self.info.setText("The end frame is before the start frame.")
            return
        qs = QtCore.QSettings("QtShell", "QtShell")
        qs.setValue("sequencer/export_format", v["fmt"])
        qs.setValue("sequencer/export_quality", v["quality"])
        qs.setValue("sequencer/export_scale", int(v["scale"]))
        qs.setValue("sequencer/export_audio", bool(v["audio"]))
        qs.setValue("sequencer/export_dir", os.path.dirname(v["path"]))
        self.accept()

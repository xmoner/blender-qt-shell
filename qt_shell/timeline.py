"""Timeline: playback, frame range, keyframes of the active object."""
import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge
from .rna_widgets import DragSpin


class TimeBar(QtWidgets.QWidget):
    def __init__(self, timeline):
        super().__init__()
        self.tl = timeline
        self.setMinimumHeight(46)
        self.setMouseTracking(False)
        self.keys = []

    def _range(self):
        sc = bpy.context.scene
        start, end = sc.frame_start, sc.frame_end
        pad = max(2, (end - start) // 20)
        return start - pad, end + pad

    def frame_to_x(self, f):
        lo, hi = self._range()
        return 10 + (f - lo) / max(hi - lo, 1) * (self.width() - 20)

    def x_to_frame(self, x):
        lo, hi = self._range()
        return round(lo + (x - 10) / max(self.width() - 20, 1) * (hi - lo))

    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#232323"))
        sc = bpy.context.scene
        lo, hi = self._range()
        # active range
        x0, x1 = self.frame_to_x(sc.frame_start), self.frame_to_x(sc.frame_end)
        p.fillRect(QtCore.QRectF(x0, 0, x1 - x0, self.height()), QtGui.QColor("#2c2c2c"))
        span = hi - lo
        step = 1
        for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
            if span / s <= self.width() / 45:
                step = s
                break
        f = p.font()
        f.setPixelSize(10)
        p.setFont(f)
        first = (lo // step) * step
        for fr in range(int(first), int(hi) + 1, step):
            x = self.frame_to_x(fr)
            p.setPen(QtGui.QColor("#3a3a3a"))
            p.drawLine(QtCore.QPointF(x, 14), QtCore.QPointF(x, self.height()))
            p.setPen(QtGui.QColor("#9a9a9a"))
            p.drawText(QtCore.QPointF(x + 2, 11), str(fr))
        # keys
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        y = self.height() * 0.65
        for k in self.keys:
            x = self.frame_to_x(k)
            poly = QtGui.QPolygonF([QtCore.QPointF(x, y - 5), QtCore.QPointF(x + 5, y),
                                    QtCore.QPointF(x, y + 5), QtCore.QPointF(x - 5, y)])
            p.setPen(QtGui.QColor("#000"))
            p.setBrush(QtGui.QColor("#e9c44a" if k == sc.frame_current else "#d0d0d0"))
            p.drawPolygon(poly)
        # current frame
        x = self.frame_to_x(sc.frame_current)
        p.setPen(QtGui.QPen(QtGui.QColor("#4772b3"), 2))
        p.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, self.height()))
        p.end()

    def mousePressEvent(self, ev):
        self._scrub(ev.position().x())

    def mouseMoveEvent(self, ev):
        if ev.buttons() & QtCore.Qt.LeftButton:
            self._scrub(ev.position().x())

    def _scrub(self, x):
        bpy.context.scene.frame_set(self.x_to_frame(x))
        self.tl.sync()


class Timeline(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(2)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(3)

        def btn(text, tip, fn):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
            return b

        btn("⏮", "Jump to Start", lambda: self._jump("start"))
        btn("◆◀", "Previous Keyframe", lambda: self._jump("prev_key"))
        self.play_btn = btn("▶", "Play / Pause (Space)", self.toggle_play)
        btn("▶◆", "Next Keyframe", lambda: self._jump("next_key"))
        btn("⏭", "Jump to End", lambda: self._jump("end"))
        row.addSpacing(12)
        self.auto_key = QtWidgets.QToolButton()
        self.auto_key.setText("● Auto Key")
        self.auto_key.setCheckable(True)
        self.auto_key.toggled.connect(self._set_auto_key)
        row.addWidget(self.auto_key)
        btn("+◆ Key", "Insert a location/rotation/scale keyframe for the active object", self.insert_key)
        btn("−◆", "Delete the keyframe on the current frame", self.delete_key)
        row.addStretch(1)
        row.addWidget(QtWidgets.QLabel("Frame"))
        self.cur = self._spin(-1048574, 1048574)
        self.cur.valueChanged.connect(lambda v: (bpy.context.scene.frame_set(int(v)), self.bar.update()))
        row.addWidget(self.cur)
        row.addWidget(QtWidgets.QLabel("Start"))
        self.start = self._spin(0, 1048574)
        self.start.valueChanged.connect(lambda v: self._set("frame_start", v))
        self.start.editingFinished.connect(lambda: bridge.undo_push("Frame Range"))
        row.addWidget(self.start)
        row.addWidget(QtWidgets.QLabel("End"))
        self.end = self._spin(0, 1048574)
        self.end.valueChanged.connect(lambda v: self._set("frame_end", v))
        self.end.editingFinished.connect(lambda: bridge.undo_push("Frame Range"))
        row.addWidget(self.end)
        lay.addLayout(row)
        self.bar = TimeBar(self)
        lay.addWidget(self.bar)

        self._play = QtCore.QTimer(self)
        self._play.timeout.connect(self._step)
        hub.frame_changed.connect(lambda _f: self.sync())
        hub.selection_changed.connect(self.sync)
        hub.data_changed.connect(self.sync)
        hub.file_loaded.connect(self.sync)
        self.sync()

    def sync(self):
        sc = bpy.context.scene
        for w, v in ((self.cur, sc.frame_current), (self.start, sc.frame_start), (self.end, sc.frame_end)):
            if not (w._editing or w._dragging):
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)
        self.auto_key.blockSignals(True)
        self.auto_key.setChecked(sc.tool_settings.use_keyframe_insert_auto)
        self.auto_key.blockSignals(False)
        ob = bpy.context.view_layer.objects.active
        self.bar.keys = bridge.object_keyframes(ob) if ob else []
        self.bar.update()

    @staticmethod
    def _spin(lo, hi):
        """Integer field draggable with the mouse (like Blender), ~4 px per frame."""
        s = DragSpin(is_int=True)
        s.setRange(lo, hi)
        s.drag_step = 0.25
        s.setMinimumWidth(64)
        return s

    def _set(self, attr, v):
        setattr(bpy.context.scene, attr, int(v))
        self.bar.update()

    def _set_auto_key(self, on):
        bpy.context.scene.tool_settings.use_keyframe_insert_auto = on

    def _jump(self, where):
        sc = bpy.context.scene
        f = sc.frame_current
        if where == "start":
            f = sc.frame_start
        elif where == "end":
            f = sc.frame_end
        else:
            keys = self.bar.keys
            if where == "prev_key":
                prev = [k for k in keys if k < f]
                f = prev[-1] if prev else f
            else:
                nxt = [k for k in keys if k > f]
                f = nxt[0] if nxt else f
        sc.frame_set(f)
        self.sync()

    def toggle_play(self):
        if self._play.isActive():
            self._play.stop()
            self.play_btn.setText("▶")
        else:
            r = bpy.context.scene.render
            fps = r.fps / (r.fps_base or 1.0)
            self._play.start(max(5, int(1000 / max(fps, 1))))
            self.play_btn.setText("⏸")

    def _step(self):
        sc = bpy.context.scene
        f = sc.frame_current + 1
        if f > sc.frame_end:
            f = sc.frame_start
        sc.frame_set(f)
        self.cur.blockSignals(True)
        self.cur.setValue(f)
        self.cur.blockSignals(False)
        self.bar.update()

    def _paths(self, ob):
        rot = "rotation_quaternion" if ob.rotation_mode == "QUATERNION" else (
            "rotation_axis_angle" if ob.rotation_mode == "AXIS_ANGLE" else "rotation_euler")
        return ("location", rot, "scale")

    def insert_key(self):
        sel = bpy.context.selected_objects
        for ob in sel:
            for path in self._paths(ob):
                try:
                    ob.keyframe_insert(path)
                except Exception as ex:
                    bridge.log(str(ex), "ERROR")
        bridge.undo_push("Insert Keyframe")
        self.sync()

    def delete_key(self):
        for ob in bpy.context.selected_objects:
            for path in self._paths(ob):
                try:
                    ob.keyframe_delete(path)
                except Exception:
                    pass
        bridge.undo_push("Delete Keyframe")
        self.sync()

    def stop(self):
        self._play.stop()

"""Pythonová konzole (jako Python Console v Blenderu) + výpis hlášení."""
import code
import contextlib
import io
import rlcompleter
import traceback

import bpy
import mathutils
from PySide6 import QtCore, QtGui, QtWidgets


class Console(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.ns = {"bpy": bpy, "C": bpy.context, "D": bpy.data, "mathutils": mathutils,
                   "Vector": mathutils.Vector, "Matrix": mathutils.Matrix,
                   "Euler": mathutils.Euler, "Quaternion": mathutils.Quaternion}
        self.completer = rlcompleter.Completer(self.ns)
        self.history = []
        self.hpos = 0
        self.buffer = []
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.out = QtWidgets.QPlainTextEdit()
        self.out.setReadOnly(True)
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.out.setFont(font)
        self.out.setMaximumBlockCount(5000)
        lay.addWidget(self.out)
        self.inp = QtWidgets.QLineEdit()
        self.inp.setFont(font)
        self.inp.setPlaceholderText(">>> Python (bpy, C, D) – Tab doplní, ↑↓ historie")
        self.inp.returnPressed.connect(self._run)
        self.inp.installEventFilter(self)
        lay.addWidget(self.inp)
        self.write("Qt Shell – Python konzole. Proměnné: bpy, C (context), D (data).\n", "#8fb3ff")
        hub.log.connect(self._on_log)

    def write(self, text, color=None):
        cur = self.out.textCursor()
        cur.movePosition(QtGui.QTextCursor.End)
        fmt = QtGui.QTextCharFormat()
        if color:
            fmt.setForeground(QtGui.QColor(color))
        cur.insertText(text, fmt)
        self.out.setTextCursor(cur)
        self.out.ensureCursorVisible()

    def _on_log(self, msg, level):
        color = {"ERROR": "#ff7070", "WARNING": "#ffc860"}.get(level, "#9a9a9a")
        self.write(f"[{level}] {msg}\n", color)

    def _run(self):
        line = self.inp.text()
        self.inp.clear()
        if line.strip():
            self.history.append(line)
        self.hpos = len(self.history)
        prompt = "... " if self.buffer else ">>> "
        self.write(prompt + line + "\n", "#d0d0d0")
        self.buffer.append(line)
        source = "\n".join(self.buffer)
        try:
            compiled = code.compile_command(source, "<qtshell>", "single")
        except SyntaxError:
            compiled = None
            self.buffer = []
            self.write(traceback.format_exc(limit=0), "#ff7070")
            return
        if compiled is None and line.strip():
            return  # víceřádkový blok pokračuje
        self.buffer = []
        if compiled is None:
            return
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                exec(compiled, self.ns)
        except SystemExit:
            pass
        except Exception:
            out.write(traceback.format_exc())
        if out.getvalue():
            self.write(out.getvalue(), "#e5e5e5")

    def eventFilter(self, obj, ev):
        if obj is self.inp and ev.type() == QtCore.QEvent.KeyPress:
            k = ev.key()
            if k == QtCore.Qt.Key_Up and self.history:
                self.hpos = max(0, self.hpos - 1)
                self.inp.setText(self.history[self.hpos])
                return True
            if k == QtCore.Qt.Key_Down and self.history:
                self.hpos = min(len(self.history), self.hpos + 1)
                self.inp.setText(self.history[self.hpos] if self.hpos < len(self.history) else "")
                return True
            if k == QtCore.Qt.Key_Tab:
                self._complete()
                return True
        return False

    def _complete(self):
        text = self.inp.text()
        start = len(text)
        while start > 0 and (text[start - 1].isalnum() or text[start - 1] in "._"):
            start -= 1
        word = text[start:]
        opts = []
        i = 0
        while True:
            try:
                c = self.completer.complete(word, i)
            except Exception:
                c = None
            if c is None or i > 400:
                break
            opts.append(c)
            i += 1
        if not opts:
            return
        if len(opts) == 1:
            self.inp.setText(text[:start] + opts[0])
            return
        prefix = opts[0]
        for o in opts[1:]:
            while not o.startswith(prefix):
                prefix = prefix[:-1]
        self.inp.setText(text[:start] + prefix)
        self.write("  ".join(o.split(".")[-1] for o in opts[:80]) + "\n", "#8c8c8c")

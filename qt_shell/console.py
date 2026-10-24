"""Python console (like the Python Console in Blender) + report log.

Traceback lines (File "…", line N) are links like in Charcoal Editor: click one to open the text / file in
the Text editor at that line. Right click the output: Clear Output.
"""
import code
import re
import urllib.parse
import contextlib
import io
import rlcompleter
import traceback

import bpy
import mathutils
from PySide6 import QtCore, QtGui, QtWidgets

from . import theme


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
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * theme.ui_scale * theme.font_scale)
        self.out.setFont(font)
        self.out.setMaximumBlockCount(5000)
        self.out.viewport().setMouseTracking(True)
        self.out.viewport().installEventFilter(self)
        self.out.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.out.customContextMenuRequested.connect(self._out_menu)
        lay.addWidget(self.out)
        self.inp = QtWidgets.QLineEdit()
        self.inp.setFont(font)
        self.inp.setPlaceholderText(">>> Python (bpy, C, D) – Tab completes, ↑↓ history")
        self.inp.returnPressed.connect(self._run)
        self.inp.installEventFilter(self)
        lay.addWidget(self.inp)
        self.write("Qt Shell – Python console. Variables: bpy, C (context), D (data).\n", "#8fb3ff")
        hub.log.connect(self._on_log)

    _LINK = re.compile(r'File "([^"]+)", line (\d+)')

    def write(self, text, color=None):
        cur = self.out.textCursor()
        cur.movePosition(QtGui.QTextCursor.End)
        fmt = QtGui.QTextCharFormat()
        if color:
            fmt.setForeground(QtGui.QColor(color))
        pos = 0
        for m in self._LINK.finditer(text):       # traceback lines become links to the code
            if m.group(1).startswith("<"):           # <string>, <qtshell> … are not files
                continue
            cur.insertText(text[pos:m.start()], fmt)
            link = QtGui.QTextCharFormat(fmt)
            link.setAnchor(True)
            link.setAnchorHref("qsline:" + urllib.parse.quote(m.group(1)) + "#" + m.group(2))
            link.setForeground(QtGui.QColor("#7fb6ff"))
            link.setFontUnderline(True)
            link.setToolTip("Click: go to this line in the Text editor")
            cur.insertText(m.group(0), link)
            pos = m.end()
        cur.insertText(text[pos:], fmt)
        self.out.setTextCursor(cur)
        self.out.ensureCursorVisible()

    def clear(self):
        self.out.clear()

    def _out_menu(self, pos):
        m = self.out.createStandardContextMenu()
        m.addSeparator()
        m.addAction("Clear Output", self.clear)
        m.exec(self.out.viewport().mapToGlobal(pos))
        m.deleteLater()

    def open_link(self, href):
        """qsline:<file>#<line> → the Text editor at that line."""
        if not href.startswith("qsline:"):
            return False
        path, _, line = href[7:].rpartition("#")
        path = urllib.parse.unquote(path)
        from . import api
        mw = api.main_window()
        te = getattr(mw, "text_editor", None) if mw is not None else None
        if te is None or path == "<qtshell>":
            return False
        if not te.goto(path, int(line or 1)):
            mw.statusBar().showMessage(f"No text called “{path}” in the Text editor", 4000)
        return True

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
            return  # multi-line block continues
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
        if obj is self.out.viewport():
            t = ev.type()
            if t == QtCore.QEvent.MouseMove:
                href = self.out.anchorAt(ev.position().toPoint())
                obj.setCursor(QtCore.Qt.PointingHandCursor if href else QtCore.Qt.IBeamCursor)
            elif t == QtCore.QEvent.MouseButtonRelease and ev.button() == QtCore.Qt.LeftButton:
                href = self.out.anchorAt(ev.position().toPoint())
                if href and not self.out.textCursor().hasSelection():
                    self.open_link(href)
                    return True
            return False
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

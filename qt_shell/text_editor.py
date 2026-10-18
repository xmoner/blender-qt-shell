"""Text editor in Qt (like Blender's Text Editor).

Works on Blender's text datablocks (bpy.data.texts), so the texts are saved in the .blend file and
shared with Blender's own Text Editor. Python syntax highlighting, line numbers, auto-indent,
Tab / Shift+Tab indentation, Ctrl+/ comments, Ctrl+F search and Run Script (Alt+P).
"""
import contextlib
import io
import keyword
import os
import re
import traceback

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, theme

INDENT = "    "


# ---------------------------------------------------------------- syntax highlighting
class PythonHighlighter(QtGui.QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)

        def fmt(color, bold=False, italic=False):
            f = QtGui.QTextCharFormat()
            f.setForeground(QtGui.QColor(color))
            if bold:
                f.setFontWeight(QtGui.QFont.Bold)
            f.setFontItalic(italic)
            return f

        self.f_keyword = fmt("#e88a5c", bold=True)
        self.f_builtin = fmt("#8fb3ff")
        self.f_string = fmt("#9bd17a")
        self.f_comment = fmt("#7f8a96", italic=True)
        self.f_number = fmt("#d7a6ff")
        self.f_def = fmt("#ffd866")
        self.f_self = fmt("#d0a0d0", italic=True)
        self.f_deco = fmt("#5cc8c8")
        builtins = ("print len range enumerate zip dict list tuple set str int float bool super "
                    "isinstance getattr setattr hasattr min max sum abs open sorted reversed any all "
                    "map filter type object Exception").split()
        self.rules = [
            (re.compile(r"\b(" + "|".join(keyword.kwlist) + r")\b"), self.f_keyword),
            (re.compile(r"\b(" + "|".join(builtins) + r")\b"), self.f_builtin),
            (re.compile(r"\b(self|cls)\b"), self.f_self),
            (re.compile(r"\b[0-9]+(\.[0-9]*)?([eE][-+]?[0-9]+)?\b"), self.f_number),
            (re.compile(r"@[\w.]+"), self.f_deco),
        ]
        self.re_def = re.compile(r"\b(def|class)\s+(\w+)")
        self.re_str = re.compile(r"""("([^"\\]|\\.)*"|'([^'\\]|\\.)*')""")
        self.re_triple = re.compile(r'"""|\'\'\'')

    def highlightBlock(self, text):
        for rx, f in self.rules:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), f)
        for m in self.re_def.finditer(text):
            self.setFormat(m.start(2), m.end(2) - m.start(2), self.f_def)
        # strings and comments (comments only outside strings)
        string_spans = []
        for m in self.re_str.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f_string)
            string_spans.append((m.start(), m.end()))
        hash_pos = -1
        for i, ch in enumerate(text):
            if ch == "#" and not any(a <= i < b for a, b in string_spans):
                hash_pos = i
                break
        if hash_pos >= 0:
            self.setFormat(hash_pos, len(text) - hash_pos, self.f_comment)
        # triple-quoted strings across lines (state 1 = inside)
        self.setCurrentBlockState(0)
        start = 0
        if self.previousBlockState() != 1:
            m = self.re_triple.search(text)
            start = m.start() if m else -1
            if start < 0:
                return
            search_from = start + 3
        else:
            search_from = 0
        while start >= 0:
            m = self.re_triple.search(text, search_from)
            if m is None:
                self.setCurrentBlockState(1)
                self.setFormat(start, len(text) - start, self.f_string)
                return
            end = m.end()
            self.setFormat(start, end - start, self.f_string)
            m2 = self.re_triple.search(text, end)
            if m2 is None:
                return
            start, search_from = m2.start(), m2.start() + 3


# ---------------------------------------------------------------- editor with line numbers
class _LineNumbers(QtWidgets.QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QtCore.QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, ev):
        self.editor.paint_line_numbers(ev)


class CodeEditor(QtWidgets.QPlainTextEdit):
    # keys that belong to the editor even though the main window has shortcuts for them
    # (Ctrl+S saves the text, not the .blend; Ctrl+Z is the editor's undo; Space types a space…)
    _OWN_KEYS = {("S", "C"), ("F", "C"), ("P", "A"), ("Slash", "C"), ("Z", "C"), ("Y", "C"),
                 ("Z", "CS"), ("Space", ""), ("Tab", ""), ("Backtab", "S"), ("Return", ""), ("Delete", "")}
    save_requested = QtCore.Signal()
    run_requested = QtCore.Signal()
    find_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * theme.ui_scale * theme.font_scale)
        self.setFont(font)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.setTabStopDistance(QtGui.QFontMetricsF(font).horizontalAdvance(" ") * 4)
        self.setStyleSheet("QPlainTextEdit{background:#1e1e1e; color:#e0e0e0;"
                           " selection-background-color:#3d5a80;}")
        self.highlighter = PythonHighlighter(self.document())
        self.numbers = _LineNumbers(self)
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._update_numbers)
        self.cursorPositionChanged.connect(self._highlight_line)
        self._error_line = None
        self._update_margin()
        self._highlight_line()

    # --- line numbers
    def line_number_width(self):
        digits = max(3, len(str(self.blockCount())))
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margin(self, *_):
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_numbers(self, rect, dy):
        if dy:
            self.numbers.scroll(0, dy)
        else:
            self.numbers.update(0, rect.y(), self.numbers.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margin()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        cr = self.contentsRect()
        self.numbers.setGeometry(QtCore.QRect(cr.left(), cr.top(), self.line_number_width(), cr.height()))

    def paint_line_numbers(self, ev):
        p = QtGui.QPainter(self.numbers)
        p.fillRect(ev.rect(), QtGui.QColor("#262626"))
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        cur = self.textCursor().blockNumber()
        while block.isValid() and top <= ev.rect().bottom():
            if block.isVisible() and bottom >= ev.rect().top():
                if num + 1 == self._error_line:
                    p.setPen(QtGui.QColor("#ff6b6b"))
                elif num == cur:
                    p.setPen(QtGui.QColor("#e0e0e0"))
                else:
                    p.setPen(QtGui.QColor("#6f6f6f"))
                p.drawText(0, top, self.numbers.width() - 5, self.fontMetrics().height(),
                           QtCore.Qt.AlignRight, str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    def _highlight_line(self):
        sels = []
        line = QtWidgets.QTextEdit.ExtraSelection()
        line.format.setBackground(QtGui.QColor("#2a2a2a"))
        line.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
        line.cursor = self.textCursor()
        line.cursor.clearSelection()
        sels.append(line)
        if self._error_line:
            block = self.document().findBlockByNumber(self._error_line - 1)
            if block.isValid():
                err = QtWidgets.QTextEdit.ExtraSelection()
                err.format.setBackground(QtGui.QColor("#5a2626"))
                err.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
                err.cursor = QtGui.QTextCursor(block)
                sels.append(err)
        self.setExtraSelections(sels)
        self.numbers.update()

    def mark_error(self, line):
        self._error_line = line
        if line:
            block = self.document().findBlockByNumber(line - 1)
            if block.isValid():
                self.setTextCursor(QtGui.QTextCursor(block))
                self.centerCursor()
        self._highlight_line()

    # --- keys
    def event(self, ev):
        if ev.type() == QtCore.QEvent.ShortcutOverride:
            m = ev.modifiers()
            ctrl = bool(m & QtCore.Qt.ControlModifier)
            alt = bool(m & QtCore.Qt.AltModifier)
            mods = ("C" if ctrl else "") + ("A" if alt else "") + ("S" if m & QtCore.Qt.ShiftModifier else "")
            name = QtGui.QKeySequence(ev.key()).toString()
            name = {" ": "Space", "/": "Slash", "Enter": "Return"}.get(name, name)
            if (name, mods) in self._OWN_KEYS or (ev.text() and not ctrl and not alt):
                ev.accept()      # handled here; plain typing never triggers window shortcuts
                return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        k = ev.key()
        mods = ev.modifiers()
        ctrl = bool(mods & QtCore.Qt.ControlModifier)
        if ctrl and k == QtCore.Qt.Key_S:
            self.save_requested.emit()
            return
        if ctrl and k == QtCore.Qt.Key_F:
            self.find_requested.emit()
            return
        if (mods & QtCore.Qt.AltModifier) and k == QtCore.Qt.Key_P:
            self.run_requested.emit()
            return
        if ctrl and k == QtCore.Qt.Key_Slash:
            self._toggle_comment()
            return
        if k == QtCore.Qt.Key_Tab and not ctrl:
            self._indent(True)
            return
        if k == QtCore.Qt.Key_Backtab:
            self._indent(False)
            return
        if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and not ctrl:
            line = self.textCursor().block().text()
            before = line[:self.textCursor().positionInBlock()]
            indent = re.match(r"\s*", line).group(0)
            if before.rstrip().endswith(":"):
                indent += INDENT
            super().keyPressEvent(ev)
            self.insertPlainText(indent)
            return
        if k == QtCore.Qt.Key_Backspace and not self.textCursor().hasSelection():
            cur = self.textCursor()
            before = cur.block().text()[:cur.positionInBlock()]
            if before and not before.strip() and len(before) % len(INDENT) == 0:
                for _ in range(len(INDENT)):
                    cur.deletePreviousChar()
                return
        super().keyPressEvent(ev)

    def _selected_blocks(self):
        cur = self.textCursor()
        doc = self.document()
        first = doc.findBlock(cur.selectionStart())
        last = doc.findBlock(max(cur.selectionStart(), cur.selectionEnd() - (1 if cur.hasSelection() else 0)))
        blocks = []
        b = first
        while b.isValid():
            blocks.append(b)
            if b == last:
                break
            b = b.next()
        return blocks

    def _indent(self, indent):
        cur = self.textCursor()
        if indent and not cur.hasSelection():
            col = cur.positionInBlock()
            self.insertPlainText(" " * (len(INDENT) - col % len(INDENT)))
            return
        cur.beginEditBlock()
        for b in self._selected_blocks():
            c = QtGui.QTextCursor(b)
            if indent:
                c.insertText(INDENT)
            else:
                text = b.text()
                n = len(text) - len(text.lstrip(" "))
                for _ in range(min(n, len(INDENT))):
                    c.deleteChar()
        cur.endEditBlock()

    def _toggle_comment(self):
        blocks = [b for b in self._selected_blocks() if b.text().strip()]
        if not blocks:
            return
        uncomment = all(b.text().lstrip().startswith("#") for b in blocks)
        cur = self.textCursor()
        cur.beginEditBlock()
        for b in blocks:
            text = b.text()
            pos = len(text) - len(text.lstrip())
            c = QtGui.QTextCursor(b)
            c.setPosition(b.position() + pos)
            if uncomment:
                n = 2 if text[pos:pos + 2] == "# " else 1
                for _ in range(n):
                    c.deleteChar()
            else:
                c.insertText("# ")
        cur.endEditBlock()


# ---------------------------------------------------------------- the editor dock
class TextEditor(QtWidgets.QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self._name = None          # name of the shown bpy text
        self._loading = False
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(3)
        self.combo = QtWidgets.QComboBox()
        self.combo.setMinimumContentsLength(14)
        self.combo.activated.connect(lambda _i: self.show_text(self.combo.currentData()))
        bar.addWidget(self.combo)

        def tool(text, tip, fn):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
            return b

        tool("+ New", "New text", self.new_text)
        tool("Open…", "Open a text file", self.open_file)
        tool("Save", "Save the text to its file (Ctrl+S)", self.save)
        tool("Save As…", "Save the text to a new file", self.save_as)
        tool("✕", "Delete this text from the .blend file", self.delete_text)
        bar.addStretch(1)
        self.run_btn = tool("▶ Run Script", "Run the text as a Python script (Alt+P)", self.run_script)
        self.run_btn.setStyleSheet("QToolButton{background:#3d6b3d;}")
        lay.addLayout(bar)

        self.editor = CodeEditor()
        self.editor.save_requested.connect(self.save)
        self.editor.run_requested.connect(self.run_script)
        self.editor.find_requested.connect(self.show_find)
        self.editor.textChanged.connect(self._edited)
        lay.addWidget(self.editor, 1)

        # find bar (Ctrl+F)
        self.find_bar = QtWidgets.QWidget()
        fl = QtWidgets.QHBoxLayout(self.find_bar)
        fl.setContentsMargins(0, 0, 0, 0)
        self.find_edit = QtWidgets.QLineEdit()
        self.find_edit.setPlaceholderText("Find…")
        self.find_edit.returnPressed.connect(lambda: self.find(False))
        self.find_case = QtWidgets.QCheckBox("Match case")
        fl.addWidget(self.find_edit, 1)
        fl.addWidget(self.find_case)
        for text, back in (("▲", True), ("▼", False)):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.clicked.connect(lambda _c=False, back=back: self.find(back))
            fl.addWidget(b)
        close = QtWidgets.QToolButton()
        close.setText("✕")
        close.clicked.connect(self.find_bar.hide)
        fl.addWidget(close)
        self.find_bar.hide()
        lay.addWidget(self.find_bar)

        self.info = QtWidgets.QLabel()
        self.info.setProperty("dim", True)
        lay.addWidget(self.info)
        self.editor.cursorPositionChanged.connect(self._update_info)

        self._push = QtCore.QTimer(self)        # editor → bpy.data.texts (debounced)
        self._push.setSingleShot(True)
        self._push.setInterval(300)
        self._push.timeout.connect(self._write_back)
        self._poll = QtCore.QTimer(self)        # bpy.data.texts → editor (changes made elsewhere)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._sync_from_blender)
        self._poll.start()
        hub.file_loaded.connect(lambda: (setattr(self, "_name", None), self.refresh_list()))
        self.refresh_list()

    # --- texts
    def _text(self):
        return bpy.data.texts.get(self._name) if self._name else None

    def refresh_list(self):
        names = [t.name for t in bpy.data.texts]
        self.combo.blockSignals(True)
        self.combo.clear()
        for n in names:
            self.combo.addItem(n, n)
        if self._name not in names:
            self._name = None
        if self._name is None and names:
            self._name = names[0]
            self._load()
        elif self._name is None:
            self._load()
        idx = self.combo.findData(self._name)
        self.combo.setCurrentIndex(max(idx, 0))
        self.combo.blockSignals(False)

    def show_text(self, name):
        self._write_back()
        self._name = name
        self._load()
        self.refresh_list()

    def _load(self):
        t = self._text()
        self._loading = True
        self.editor.setPlainText(t.as_string() if t is not None else "")
        self.editor.setReadOnly(t is None)
        self.editor.setPlaceholderText("" if t is not None else "No text – click “+ New” or “Open…”.")
        self.editor.mark_error(None)
        self._loading = False
        self._update_info()

    def _edited(self):
        if not self._loading:
            if self.editor._error_line:
                self.editor.mark_error(None)
            self._push.start()

    def _write_back(self):
        self._push.stop()
        t = self._text()
        if t is None:
            return
        src = self.editor.toPlainText()
        if t.as_string() != src:
            t.from_string(src)

    def _sync_from_blender(self):
        """Picks up changes made outside (Blender's Text Editor, scripts) while not typing here."""
        if self._push.isActive() or self.editor.hasFocus() or not self.isVisible():
            return
        names = [t.name for t in bpy.data.texts]
        if names != [self.combo.itemData(i) for i in range(self.combo.count())]:
            self.refresh_list()
        t = self._text()
        if t is not None and t.as_string() != self.editor.toPlainText():
            pos = self.editor.textCursor().position()
            self._load()
            c = self.editor.textCursor()
            c.setPosition(min(pos, len(self.editor.toPlainText())))
            self.editor.setTextCursor(c)

    def _update_info(self):
        t = self._text()
        c = self.editor.textCursor()
        where = f"Ln {c.blockNumber() + 1}, Col {c.positionInBlock() + 1}"
        path = bpy.path.abspath(t.filepath) if t is not None and t.filepath else ""
        self.info.setText(f"{where}   ·   {path or ('internal (saved in the .blend)' if t else '')}")

    def new_text(self):
        self._write_back()
        t = bpy.data.texts.new("Text")
        self._name = t.name
        self._load()
        self.refresh_list()
        self.editor.setFocus()

    def open_file(self):
        start = os.path.dirname(bpy.data.filepath) or os.path.expanduser("~")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open Text", start,
                                                        "Python (*.py);;Text (*.txt);;All files (*)")
        if not path:
            return
        self._write_back()
        try:
            t = bpy.data.texts.load(path)
        except Exception as ex:
            QtWidgets.QMessageBox.warning(self, "Open Text", str(ex))
            return
        self._name = t.name
        self._load()
        self.refresh_list()

    def save(self):
        t = self._text()
        if t is None:
            return
        if not t.filepath:
            self.save_as()
            return
        self._write_file(bpy.path.abspath(t.filepath))

    def save_as(self):
        t = self._text()
        if t is None:
            return
        start = bpy.path.abspath(t.filepath) if t.filepath else os.path.join(
            os.path.dirname(bpy.data.filepath) or os.path.expanduser("~"),
            t.name if "." in t.name else t.name + ".py")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Text As", start,
                                                        "Python (*.py);;Text (*.txt);;All files (*)")
        if not path:
            return
        if self._write_file(path):
            t.filepath = path
            self._update_info()

    def _write_file(self, path):
        self._write_back()
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(self.editor.toPlainText())
        except Exception as ex:
            QtWidgets.QMessageBox.warning(self, "Save Text", str(ex))
            return False
        self._status(f"Saved {path}")
        return True

    def delete_text(self):
        t = self._text()
        if t is None:
            return
        r = QtWidgets.QMessageBox.question(self, "Delete Text", f"Delete the text “{t.name}” from the .blend file?")
        if r != QtWidgets.QMessageBox.Yes:
            return
        self._push.stop()
        bpy.data.texts.remove(t)
        self._name = None
        self.refresh_list()

    # --- run
    def run_script(self):
        """Runs the text like Blender's Run Script; output and errors go to the Console dock."""
        t = self._text()
        if t is None:
            return
        self._write_back()
        src = self.editor.toPlainText()
        mw = getattr(self.hub, "main_window", None)
        console = getattr(mw, "console", None)
        if console is not None:
            mw.docks["console"].show()
            mw.docks["console"].raise_()
            console.write(f"\n▶ Run Script: {t.name}\n", "#8fb3ff")
        out = io.StringIO()
        filename = bpy.path.abspath(t.filepath) if t.filepath else t.name
        ns = {"__name__": "__main__", "__file__": filename, "bpy": bpy}
        error_line = None
        try:
            code = compile(src, t.name, "exec")
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                with bridge.blender_context():
                    exec(code, ns)
            ok = True
        except Exception as ex:
            ok = False
            # show only the script's own frames (skip the exec() call inside Qt Shell)
            tb = ex.__traceback__
            while tb is not None and tb.tb_frame.f_code.co_filename != t.name:
                tb = tb.tb_next
            if isinstance(ex, SyntaxError) or tb is None:
                out.write("".join(traceback.format_exception_only(type(ex), ex)))
            else:
                out.write("Traceback (most recent call last):\n")
                out.write("".join(traceback.format_list(traceback.extract_tb(tb))))
                out.write("".join(traceback.format_exception_only(type(ex), ex)))
            if isinstance(ex, SyntaxError) and ex.filename == t.name:
                error_line = ex.lineno
            else:
                for fr in traceback.extract_tb(ex.__traceback__):
                    if fr.filename == t.name:
                        error_line = fr.lineno
        if console is not None and out.getvalue():
            console.write(out.getvalue(), "#e5e5e5" if ok else "#ff7070")
        self.editor.mark_error(error_line)
        self._status("Script finished" if ok else
                     f"Script error{f' on line {error_line}' if error_line else ''} – see the Console")
        try:
            bpy.ops.ed.undo_push(message="Run Script")
        except Exception:
            pass

    # --- find
    def show_find(self):
        sel = self.editor.textCursor().selectedText()
        if sel and " " not in sel:
            self.find_edit.setText(sel)
        self.find_bar.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def find(self, backward=False):
        text = self.find_edit.text()
        if not text:
            return
        flags = QtGui.QTextDocument.FindFlag(0)
        if backward:
            flags |= QtGui.QTextDocument.FindBackward
        if self.find_case.isChecked():
            flags |= QtGui.QTextDocument.FindCaseSensitively
        if not self.editor.find(text, flags):
            c = self.editor.textCursor()          # wrap around
            c.movePosition(QtGui.QTextCursor.End if backward else QtGui.QTextCursor.Start)
            self.editor.setTextCursor(c)
            if not self.editor.find(text, flags):
                self._status(f"“{text}” not found")

    def _status(self, msg):
        mw = getattr(self.hub, "main_window", None)
        if mw is not None:
            mw.statusBar().showMessage(msg, 5000)

    def shutdown(self):
        self._write_back()
        self._poll.stop()

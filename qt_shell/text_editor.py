"""Text editor in Qt (like Blender's Text Editor).

Works on Blender's text datablocks (bpy.data.texts), so the texts are saved in the .blend file and
shared with Blender's own Text Editor. Python syntax highlighting, line numbers, auto-indent,
Tab / Shift+Tab indentation, Ctrl+/ comments, Ctrl+F search, Run Script (Alt+P) and
Run Selection (Ctrl+Enter), auto-completion (Ctrl+Space; automatic after "." and while typing). Scripts are run through the script manager (scripts.py), so running a
script again replaces its previous run and Unload removes everything it registered.
"""
import keyword
import os
import re
import sys

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import completion, scripts, theme

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
                 ("Z", "CS"), ("Space", ""), ("Tab", ""), ("Backtab", "S"), ("Return", ""), ("Return", "C"), ("Delete", ""),
                 ("Space", "C")}
    save_requested = QtCore.Signal()
    run_requested = QtCore.Signal()
    run_selection_requested = QtCore.Signal()
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
        # auto-completion
        self.completion_namespace = None   # fn() -> dict of names, set by the TextEditor
        self.auto_complete = True          # popup automatically after "." and while typing
        self._completer = QtWidgets.QCompleter(self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self._completer.setMaxVisibleItems(12)
        self._cmodel = QtGui.QStandardItemModel(self._completer)
        self._completer.setModel(self._cmodel)
        self._completer.setCompletionRole(QtCore.Qt.UserRole)   # the name; the label may add "()"
        self._completer.activated[str].connect(self._insert_completion)
        self._completer.popup().setFont(font)
        self._clist_key = None

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
        ctrl = bool(ev.modifiers() & QtCore.Qt.ControlModifier)
        popup = self._completer.popup()
        if popup.isVisible():
            if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Tab) and not ctrl:
                idx = popup.currentIndex()
                if not idx.isValid():
                    idx = self._completer.completionModel().index(0, 0)
                if idx.isValid():
                    self._insert_completion(idx.data(QtCore.Qt.UserRole))
                popup.hide()
                return
            if k == QtCore.Qt.Key_Escape:
                popup.hide()
                return
        if ctrl and k == QtCore.Qt.Key_Space:
            self.complete(manual=True)
            return
        self._key_press(ev)
        self._after_key(ev)

    # --- auto-completion
    def _after_key(self, ev):
        k = ev.key()
        text = ev.text()
        popup = self._completer.popup()
        if popup.isVisible():
            if text or k in (QtCore.Qt.Key_Backspace, QtCore.Qt.Key_Delete):
                self.complete(manual=False, refresh=True)
            elif k in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Right, QtCore.Qt.Key_Home, QtCore.Qt.Key_End):
                popup.hide()
            return
        if not self.auto_complete or not text:
            return
        if text == "." or text.isalnum() or text == "_":
            self.complete(manual=False)

    def _line_before(self):
        c = self.textCursor()
        return c.block().text()[:c.positionInBlock()]

    def complete(self, manual=False, refresh=False):
        """Shows the completion popup for the word before the cursor."""
        popup = self._completer.popup()
        before = self._line_before()
        if completion.in_string_or_comment(before):
            popup.hide()
            return
        base, prefix = completion.split(before)
        if not manual and not refresh and base is None and len(prefix) < 3:
            return
        if base is None and not prefix and not manual:
            popup.hide()
            return
        try:
            ns = self.completion_namespace() if self.completion_namespace else {}
        except Exception:
            ns = {}
        try:
            items = completion.candidates(base, "", ns, self.toPlainText()) if base is not None else \
                completion.candidates(None, prefix[:1], ns, self.toPlainText())
        except Exception:
            items = []
        if base is None and prefix:
            # the word being typed is in the document too – don't offer it unless it is used elsewhere
            if len(re.findall(rf"\b{re.escape(prefix)}\b", self.toPlainText())) <= 1:
                items = [it for it in items if it[0] != prefix]
        key = (base, tuple(items))
        if key != self._clist_key:
            self._clist_key = key
            self._cmodel.clear()
            for name, is_call in items:
                it = QtGui.QStandardItem(name + ("()" if is_call else ""))
                it.setData(name, QtCore.Qt.UserRole)
                it.setToolTip("function / method" if is_call else "")
                self._cmodel.appendRow(it)
        self._completer.setCompletionPrefix(prefix)
        cm = self._completer.completionModel()
        n = cm.rowCount()
        if n == 0 or (n == 1 and not manual and cm.index(0, 0).data(QtCore.Qt.UserRole) == prefix):
            popup.hide()
            return
        rect = self.cursorRect()
        rect.translate(self.viewport().geometry().topLeft())
        rect.setWidth(popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width() + 12)
        self._completer.complete(rect)
        popup.setCurrentIndex(cm.index(0, 0))

    def _insert_completion(self, name):
        if not name:
            return
        prefix = self._completer.completionPrefix()
        c = self.textCursor()
        c.movePosition(QtGui.QTextCursor.Left, QtGui.QTextCursor.KeepAnchor, len(prefix))
        c.insertText(name)
        self.setTextCursor(c)

    def _key_press(self, ev):
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
        if ctrl and k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.run_selection_requested.emit()
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
        self.ac_check = QtWidgets.QCheckBox("Auto-complete")
        self.ac_check.setToolTip("Suggest names automatically after \".\" and while typing.\n"
                                 "Ctrl+Space shows the suggestions any time.")
        bar.addWidget(self.ac_check)
        self.state_lab = QtWidgets.QLabel()
        bar.addWidget(self.state_lab)
        tool("→ Shelf", "Add the selected code – or the whole text – as a button to the Shelf "
             "(you can also drag selected code onto the Shelf)", self.to_shelf)
        tool("Run Selection", "Run the selected lines, or the current line, in the script's namespace "
             "(Ctrl+Enter). A single expression prints its value.", self.run_selection)
        self.unload_btn = tool("■ Unload", "Call the script's unregister() and remove everything it "
                               "registered (menus, docks, overlays, handlers, classes)", self.unload_script)
        self.run_btn = tool("▶ Run Script", "Run the text as a Python script (Alt+P). "
                            "If it is already loaded, it is unloaded first.", self.run_script)
        self.run_btn.setStyleSheet(
            "QToolButton{background:#3d6b3d;} "
            "QToolButton:hover{background:#4f8f4f; border:1px solid #8fd08f;} "
            "QToolButton:pressed{background:#62a862; border:1px solid #b0e8b0;}")
        lay.addLayout(bar)

        self.editor = CodeEditor()
        self.editor.completion_namespace = self._completion_namespace
        settings = QtCore.QSettings("QtShell", "QtShell")
        self.editor.auto_complete = str(settings.value("text_editor/autocomplete", "true")).lower() == "true"
        self.ac_check.setChecked(self.editor.auto_complete)
        self.ac_check.toggled.connect(self._set_auto_complete)
        self.editor.save_requested.connect(self.save)
        self.editor.run_requested.connect(self.run_script)
        self.editor.run_selection_requested.connect(self.run_selection)
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
        self._scripts_version = None
        hub.file_loaded.connect(lambda: (setattr(self, "_name", None), self.refresh_list()))
        self.refresh_list()

    # --- auto-completion
    def _set_auto_complete(self, on):
        self.editor.auto_complete = bool(on)
        QtCore.QSettings("QtShell", "QtShell").setValue("text_editor/autocomplete", "true" if on else "false")

    def _completion_namespace(self):
        """Names for auto-completion: bpy, C, D, common Blender modules, the script's own namespace
        (after it has run) and the modules imported by the text."""
        ns = {"bpy": bpy, "C": bpy.context, "D": bpy.data}
        for name in ("mathutils", "bmesh", "math", "gpu", "bpy_extras"):
            mod = sys.modules.get(name)
            if mod is not None:
                ns[name] = mod
        key = self._key()
        loaded = scripts._state()["loaded"].get(key) if key else None
        if loaded is not None:
            ns.update({k: v for k, v in loaded["ns"].items() if not k.startswith("__")})
        ns.update(completion.imports_namespace(self.editor.toPlainText()))
        return ns

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
        self._update_state()

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
        if self._scripts_version != scripts.version():
            self._update_state()
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

    def _key(self):
        t = self._text()
        return scripts.key_for_text(t) if t is not None else None

    def _update_state(self):
        self._scripts_version = scripts.version()
        key = self._key()
        i = scripts.info(key) if key else None
        self.unload_btn.setEnabled(i is not None)
        self.run_btn.setText("⟳ Reload" if i is not None and i["status"] == "loaded" else "▶ Run Script")
        if i is None:
            self.state_lab.setText("")
            self.state_lab.setToolTip("")
        elif i["status"] == "error":
            self.state_lab.setText("<span style='color:#ff7070'>● error</span>")
        elif i["status"] == "loaded":
            n = i["items"]
            self.state_lab.setText(f"<span style='color:#7fcf7f'>● loaded · {n} item{'s' if n != 1 else ''}</span>")
            self.state_lab.setToolTip("\n".join(scripts.items(key)) or "has unregister()")
        else:
            self.state_lab.setText("<span style='color:#999'>● ran</span>")
            self.state_lab.setToolTip("The script ran and registered nothing.")

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
    def _console(self):
        scripts.show_console()

    def run_script(self):
        """Runs the text like Blender's Run Script; output and errors go to the Console dock."""
        t = self._text()
        if t is None:
            return
        self._write_back()
        key = self._key()
        was = scripts.is_loaded(key)
        self._console()
        r = scripts.run(key)
        title = f"{'⟳ Reload' if was else '▶ Run Script'}: {t.name}"
        if r.removed:
            title += f"  (removed {r.removed} item{'s' if r.removed != 1 else ''} of the previous run)"
        scripts.report_result(title, r)
        self.editor.mark_error(r.error_line)
        self._status("Script finished" if r.ok else
                     f"Script error{f' on line {r.error_line}' if r.error_line else ''} – see the Console")
        self._update_state()
        self._undo_push("Run Script")

    def run_selection(self):
        """Runs the selected lines (or the current line) in the namespace of the script (Ctrl+Enter)."""
        t = self._text()
        if t is None:
            return
        self._write_back()
        cur = self.editor.textCursor()
        blocks = self.editor._selected_blocks()
        if cur.hasSelection() and len(blocks) == 1:
            src = cur.selectedText()                       # part of one line
        else:
            src = "\n".join(b.text() for b in blocks)
        lines = src.split("\n")
        # remove the common indentation, so an indented block can be run on its own
        ind = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
        src = "\n".join(l[ind:] for l in lines)
        if not src.strip():
            return
        self._console()
        first = blocks[0].blockNumber() + 1
        r = scripts.run_snippet(self._key(), src, first)
        scripts.report(f"\n>>> {t.name}:{first}" + (f"-{first + len(lines) - 1}" if len(lines) > 1 else "")
                       + "\n", "#8fb3ff")
        if r.output:
            scripts.report(r.output if r.output.endswith("\n") else r.output + "\n",
                           "#e5e5e5" if r.ok else "#ff7070")
        if r.error_line:
            self.editor.mark_error(r.error_line)
        self._update_state()
        self._undo_push("Run Selection")

    def to_shelf(self):
        mw = getattr(self.hub, "main_window", None)
        shelf = getattr(mw, "shelf", None)
        if shelf is None:
            return
        cur = self.editor.textCursor()
        code = cur.selectedText().replace("\u2029", "\n") if cur.hasSelection() else self.editor.toPlainText()
        t = self._text()
        name = os.path.splitext(t.name)[0] if t is not None and not cur.hasSelection() else None
        mw.shelf_bar.show()
        shelf.add_code(code, name)

    def unload_script(self):
        key = self._key()
        if not key or not scripts.is_loaded(key):
            return
        self._console()
        r = scripts.unload(key)
        scripts.report_result(f"■ Unload: {scripts.label(key)}  (removed {r.removed} item"
                              f"{'s' if r.removed != 1 else ''})", r)
        self._status(f"Unloaded {scripts.label(key)}")
        self._update_state()

    @staticmethod
    def _undo_push(msg):
        try:
            bpy.ops.ed.undo_push(message=msg)
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

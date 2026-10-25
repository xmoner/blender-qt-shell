"""Text editor in Qt (like Blender's Text Editor, with the IDE features of Charcoal Editor 2 for Maya).

Works on Blender's text datablocks (bpy.data.texts), so the texts are saved in the .blend file and
shared with Blender's own Text Editor. The texts are tabs; ☰ holds File / Edit / Line / Run / View.

Editing: Python syntax colours, line numbers, auto-indent (also between brackets), Tab / Shift+Tab, toggle
comment, auto-closed brackets and quotes (typing the closer steps over it, Backspace removes an empty pair,
a selection gets wrapped), matching bracket and matching word highlighting (select a word), indent guides,
show whitespace, duplicate / delete / move lines, convert tabs to spaces, Ctrl + wheel font size,
auto-completion (automatic after "." and while typing), quick help (the docstring of the name under the
cursor), go to line, find and replace (match case, whole word, regular expression, all matches shown).
Live checks while typing: syntax errors and undefined names are underlined, marked in the line numbers and
listed under the editor. Outline: classes and functions, click to go there.

Running (scripts.py: running again replaces the previous run, Unload removes what it registered):
Run Script, Run Selection (selection or current line), Run Line (the current line without its indentation);
the code always stays in the editor. Errors in the Console are links – click one to go to the line.
All keys live in keymap.py (Keyboard Shortcuts window → Text Editor).
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




# ---------------------------------------------------------------- live checks (like Charcoal's Pylint)
_LINT_SKIP = {"__file__", "__name__", "__doc__", "__builtins__", "__spec__", "__loader__", "__package__",
              "__annotations__", "__dict__", "__class__"}


def lint(source, known=()):
    """Problems in Python source without running it: [(line, col, end col, 'error' | 'warning', message)].
    A syntax error stops the check; otherwise names that are used but never defined are warnings."""
    import ast
    import builtins
    try:
        tree = ast.parse(source)
    except SyntaxError as ex:
        line = ex.lineno or 1
        col = max((ex.offset or 1) - 1, 0)
        return [(line, col, col + 1, "error", f"SyntaxError: {ex.msg}")]
    except Exception as ex:          # e.g. null bytes
        return [(1, 0, 1, "error", str(ex))]
    defined = set(dir(builtins)) | set(known) | _LINT_SKIP
    star = False
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(n.name)
        elif isinstance(n, ast.Import):
            defined |= {a.asname or a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name == "*":
                    star = True
                defined.add(a.asname or a.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            defined.add(n.id)
        elif isinstance(n, ast.arg):
            defined.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            defined.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            defined |= set(n.names)
        elif type(n).__name__ in ("MatchAs", "MatchStar") and getattr(n, "name", None):
            defined.add(n.name)
        elif type(n).__name__ == "MatchMapping" and getattr(n, "rest", None):
            defined.add(n.rest)
    if star:                         # `from x import *` – any name can come from there
        return []
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in defined:
            out.append((n.lineno, n.col_offset, n.col_offset + len(n.id), "warning",
                        f"Undefined name '{n.id}'"))
    out.sort()
    return out[:200]


def outline(source):
    """[(level, kind, name, line)] of the classes and functions in Python source (regex fallback when the
    source doesn't parse)."""
    import ast
    items = []
    try:
        tree = ast.parse(source)
    except Exception:
        for i, line in enumerate(source.split("\n"), 1):
            m = re.match(r"(\s*)(async\s+)?(def|class)\s+(\w+)", line)
            if m:
                items.append((len(m.group(1)) // 4, m.group(3), m.group(4), i))
        return items

    def walk(node, level):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, ast.ClassDef):
                items.append((level, "class", ch.name, ch.lineno))
                walk(ch, level + 1)
            elif isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                items.append((level, "def", ch.name, ch.lineno))
                walk(ch, level + 1)
    walk(tree, 0)
    return items


# ---------------------------------------------------------------- editor with line numbers
class _LineNumbers(QtWidgets.QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QtCore.QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, ev):
        self.editor.paint_line_numbers(ev)


_PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
_CLOSERS = {")": "(", "]": "[", "}": "{"}


class CodeEditor(QtWidgets.QPlainTextEdit):
    """Python code editor: line numbers, syntax colours, auto-indent, auto-completion, matching brackets and
    words, auto-closed brackets / quotes, indent guides, whitespace display, line tools, live checks."""
    # keys that belong to the editor even though the main window has shortcuts for them
    # (Ctrl+Z is the editor's undo; Space types a space…)
    _OWN_KEYS = {("Z", "C"), ("Y", "C"), ("Z", "CS"), ("Space", ""), ("Tab", ""), ("Backtab", "S"),
                 ("Return", ""), ("Return", "C"), ("Delete", ""), ("Space", "C"), ("A", "C"), ("C", "C"),
                 ("V", "C"), ("X", "C"), ("Home", ""), ("End", ""), ("Left", ""), ("Right", ""),
                 ("Up", ""), ("Down", "")}
    _ACTIONS = ("text.run_script", "text.run_selection", "text.run_line", "text.run_all", "text.complete",
                "text.save", "text.find", "text.replace", "text.find_next", "text.find_prev",
                "text.goto_line", "text.comment", "text.duplicate_line", "text.delete_line",
                "text.move_line_up", "text.move_line_down", "text.quick_help", "text.outline",
                "text.zoom_in", "text.zoom_out", "text.show_whitespace")
    save_requested = QtCore.Signal()
    run_requested = QtCore.Signal()
    run_selection_requested = QtCore.Signal()
    run_line_requested = QtCore.Signal()
    find_requested = QtCore.Signal()
    replace_requested = QtCore.Signal()
    find_next_requested = QtCore.Signal(bool)          # backward
    outline_requested = QtCore.Signal()
    lint_changed = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        st = QtCore.QSettings("QtShell", "QtShell")
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self._base_pt = font.pointSizeF() * theme.ui_scale * theme.font_scale if font.pointSizeF() > 0 else 10.0
        try:
            self._zoom = float(st.value("text_editor/font_zoom", 0))
        except (TypeError, ValueError):
            self._zoom = 0.0
        self.setFont(font)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.setStyleSheet("QPlainTextEdit{background:#1e1e1e; color:#e0e0e0;"
                           " selection-background-color:#3d5a80;}")
        self.highlighter = PythonHighlighter(self.document())
        self.numbers = _LineNumbers(self)
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._update_numbers)
        self.cursorPositionChanged.connect(self._highlight_line)
        self.selectionChanged.connect(self._highlight_line)
        self._error_line = None
        self.find_matches = []             # (start, end) of the find bar's matches – drawn in yellow
        self.problems = []                 # live check results (line, col, end, kind, message)
        self.show_whitespace = str(st.value("text_editor/show_whitespace", "false")).lower() == "true"
        self.indent_guides = str(st.value("text_editor/indent_guides", "true")).lower() == "true"
        self.auto_close = str(st.value("text_editor/auto_close", "true")).lower() == "true"
        self.live_check = str(st.value("text_editor/live_check", "true")).lower() == "true"
        self._apply_font()
        self._apply_whitespace()
        self._lint_timer = QtCore.QTimer(self)
        self._lint_timer.setSingleShot(True)
        self._lint_timer.setInterval(700)
        self._lint_timer.timeout.connect(self.run_lint)
        self.textChanged.connect(lambda: self._lint_timer.start())
        self.known_names = lambda: ()      # names that exist when the script runs (bpy, C, D, …)
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
        self._completer.popup().setFont(self.font())
        self._clist_key = None

    # --- font / whitespace
    def _apply_font(self):
        f = self.font()
        f.setPointSizeF(max(6.0, self._base_pt + self._zoom))
        self.setFont(f)
        self.setTabStopDistance(QtGui.QFontMetricsF(f).horizontalAdvance(" ") * 4)
        self._update_margin()

    def zoom_font(self, step):
        self._zoom = max(-6.0, min(24.0, self._zoom + step))
        QtCore.QSettings("QtShell", "QtShell").setValue("text_editor/font_zoom", self._zoom)
        self._apply_font()
        try:
            self._completer.popup().setFont(self.font())
        except AttributeError:
            pass

    def _apply_whitespace(self):
        opt = self.document().defaultTextOption()
        flags = opt.flags()
        if self.show_whitespace:
            flags |= QtGui.QTextOption.ShowTabsAndSpaces
        else:
            flags &= ~QtGui.QTextOption.ShowTabsAndSpaces
        opt.setFlags(flags)
        self.document().setDefaultTextOption(opt)

    def set_option(self, name, on):
        """show_whitespace, indent_guides, auto_close, live_check (remembered)."""
        setattr(self, name, bool(on))
        QtCore.QSettings("QtShell", "QtShell").setValue(f"text_editor/{name}", "true" if on else "false")
        if name == "show_whitespace":
            self._apply_whitespace()
        if name == "live_check":
            self.run_lint()
        self.viewport().update()

    # --- line numbers
    def line_number_width(self):
        digits = max(3, len(str(self.blockCount())))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

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
        marks = {}
        for line, _c, _e, kind, _m in self.problems:
            if marks.get(line) != "error":
                marks[line] = kind
        h = self.fontMetrics().height()
        while block.isValid() and top <= ev.rect().bottom():
            if block.isVisible() and bottom >= ev.rect().top():
                if num + 1 == self._error_line:
                    p.setPen(QtGui.QColor("#ff6b6b"))
                elif num == cur:
                    p.setPen(QtGui.QColor("#e0e0e0"))
                else:
                    p.setPen(QtGui.QColor("#6f6f6f"))
                p.drawText(0, top, self.numbers.width() - 5, h, QtCore.Qt.AlignRight, str(num + 1))
                kind = marks.get(num + 1)
                if kind:                    # problem marker in the gutter
                    p.setPen(QtCore.Qt.NoPen)
                    p.setBrush(QtGui.QColor("#ff5c5c" if kind == "error" else "#e0b84a"))
                    r = max(2.5, h * 0.16)
                    p.drawEllipse(QtCore.QPointF(r + 3, top + h / 2), r, r)
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    # --- extra highlights: current line, error line, matching brackets / words, find matches, problems
    def _sel(self, start, end, bg=None, fg=None, underline=None, full=False):
        s = QtWidgets.QTextEdit.ExtraSelection()
        if bg is not None:
            s.format.setBackground(QtGui.QColor(bg))
        if fg is not None:
            s.format.setForeground(QtGui.QColor(fg))
        if underline is not None:
            s.format.setUnderlineStyle(QtGui.QTextCharFormat.WaveUnderline)
            s.format.setUnderlineColor(QtGui.QColor(underline))
        if full:
            s.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
        c = QtGui.QTextCursor(self.document())
        c.setPosition(start)
        if end > start:
            c.setPosition(end, QtGui.QTextCursor.KeepAnchor)
        s.cursor = c
        return s

    def _highlight_line(self):
        sels = []
        cur = self.textCursor()
        line = QtWidgets.QTextEdit.ExtraSelection()
        line.format.setBackground(QtGui.QColor("#2a2a2a"))
        line.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
        line.cursor = QtGui.QTextCursor(cur)
        line.cursor.clearSelection()
        sels.append(line)
        doc = self.document()
        if self._error_line:
            block = doc.findBlockByNumber(self._error_line - 1)
            if block.isValid():
                sels.append(self._sel(block.position(), block.position(), bg="#5a2626", full=True))
        for a, b in self.find_matches[:2000]:
            sels.append(self._sel(a, b, bg="#6b5a1e"))
        # problems (wavy underlines)
        for ln, col, end, kind, _m in self.problems:
            block = doc.findBlockByNumber(ln - 1)
            if block.isValid():
                n = len(block.text())
                a = block.position() + min(col, n)
                b = block.position() + min(max(end, col + 1), max(n, col + 1))
                sels.append(self._sel(a, b, underline="#ff5c5c" if kind == "error" else "#e0b84a"))
        # matching word (Charcoal: selecting a word highlights the others)
        text = cur.selectedText()
        if text and re.fullmatch(r"\w{2,}", text):
            src = self.toPlainText()
            for m in list(re.finditer(rf"\b{re.escape(text)}\b", src))[:500]:
                if m.start() != cur.selectionStart():
                    sels.append(self._sel(m.start(), m.end(), bg="#3b4a3b"))
        # matching bracket
        pair = self._bracket_pair()
        if pair:
            for pos in pair:
                sels.append(self._sel(pos, pos + 1, bg="#4a4a6a", fg="#ffffff"))
        self.setExtraSelections(sels)
        self.numbers.update()

    def _bracket_pair(self):
        """Positions of the bracket at / before the cursor and its partner (None when there is none)."""
        doc = self.document()
        pos = self.textCursor().position()
        for p in (pos, pos - 1):
            if p < 0:
                continue
            ch = doc.characterAt(p)
            if ch in "([{":
                close, step, opener = {"(": ")", "[": "]", "{": "}"}[ch], 1, ch
            elif ch in ")]}":
                close, step, opener = _CLOSERS[ch], -1, ch
            else:
                continue
            depth = 0
            i = p
            n = doc.characterCount()
            limit = 20000
            while 0 <= i < n and limit:
                c = doc.characterAt(i)
                if c == opener:
                    depth += 1
                elif c == close:
                    depth -= 1
                    if depth == 0:
                        return (p, i)
                i += step
                limit -= 1
            return None
        return None

    def mark_error(self, line):
        self._error_line = line
        if line:
            self.goto_line(line)
        self._highlight_line()

    def goto_line(self, line, col=0):
        block = self.document().findBlockByNumber(max(0, int(line) - 1))
        if block.isValid():
            c = QtGui.QTextCursor(block)
            c.setPosition(block.position() + min(col, len(block.text())))
            self.setTextCursor(c)
            self.centerCursor()
            self.setFocus()

    # --- live checks
    def run_lint(self):
        if not self.live_check or self.isReadOnly():
            probs = []
        else:
            try:
                known = set(self.known_names() or ())
            except Exception:
                known = set()
            probs = lint(self.toPlainText(), known)
        if probs != self.problems:
            self.problems = probs
            self._highlight_line()
            self.lint_changed.emit(probs)

    def problem_at(self, pos):
        c = self.cursorForPosition(pos)
        ln, col = c.blockNumber() + 1, c.positionInBlock()
        for p in self.problems:
            if p[0] == ln and p[1] <= col <= max(p[2], p[1] + 1):
                return p
        return None

    def viewportEvent(self, ev):
        if ev.type() == QtCore.QEvent.ToolTip:
            p = self.problem_at(ev.pos())
            if p is not None:
                QtWidgets.QToolTip.showText(ev.globalPos(), p[4], self)
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return super().viewportEvent(ev)

    # --- indent guides
    def paintEvent(self, ev):
        super().paintEvent(ev)
        if not self.indent_guides:
            return
        p = QtGui.QPainter(self.viewport())
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 28), 1, QtCore.Qt.DotLine)
        p.setPen(pen)
        sp = QtGui.QFontMetricsF(self.font()).horizontalAdvance(" ")
        off = self.contentOffset()
        left = off.x() + self.document().documentMargin()
        block = self.firstVisibleBlock()
        bottom_limit = ev.rect().bottom()
        prev_indent = 0
        while block.isValid():
            geo = self.blockBoundingGeometry(block).translated(off)
            if geo.top() > bottom_limit:
                break
            text = block.text()
            if text.strip():
                indent = len(text) - len(text.lstrip(" "))
            else:                        # blank line: keep the guides of the code around it
                nxt = block.next()
                while nxt.isValid() and not nxt.text().strip():
                    nxt = nxt.next()
                nind = len(nxt.text()) - len(nxt.text().lstrip(" ")) if nxt.isValid() else 0
                indent = min(prev_indent, nind)
            for lvl in range(4, indent + 1, 4):     # a guide at every indentation level of the line
                x = left + (lvl - 4) * sp + sp * 0.5
                p.drawLine(QtCore.QPointF(x, geo.top()), QtCore.QPointF(x, geo.bottom()))
            if text.strip():
                prev_indent = indent
            block = block.next()
        p.end()

    # --- keys
    def event(self, ev):
        if ev.type() == QtCore.QEvent.ShortcutOverride:
            m = ev.modifiers()
            ctrl = bool(m & QtCore.Qt.ControlModifier)
            alt = bool(m & QtCore.Qt.AltModifier)
            mods = ("C" if ctrl else "") + ("A" if alt else "") + ("S" if m & QtCore.Qt.ShiftModifier else "")
            name = QtGui.QKeySequence(ev.key()).toString()
            name = {" ": "Space", "/": "Slash", "Enter": "Return"}.get(name, name)
            from . import keymap
            own = any(keymap.hit(a, ev) for a in self._ACTIONS)
            if own or (name, mods) in self._OWN_KEYS or (ev.text() and not ctrl and not alt):
                ev.accept()      # handled here; plain typing never triggers window shortcuts
                return True
        return super().event(ev)

    def wheelEvent(self, ev):
        if ev.modifiers() & QtCore.Qt.ControlModifier:         # Ctrl + wheel: font size
            steps = ev.angleDelta().y() / 120.0
            if steps:
                self.zoom_font(1.0 if steps > 0 else -1.0)
            return
        super().wheelEvent(ev)

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
        from . import keymap
        if keymap.hit("text.complete", ev):
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

    # --- quick help (F1)
    def expression_at_cursor(self):
        """The dotted name under / before the cursor, e.g. 'bpy.ops.mesh.primitive_cube_add'."""
        c = self.textCursor()
        line = c.block().text()
        i = c.positionInBlock()
        j = i
        while j < len(line) and (line[j].isalnum() or line[j] == "_"):
            j += 1
        s = i
        while s > 0 and (line[s - 1].isalnum() or line[s - 1] in "._"):
            s -= 1
        return line[s:j].strip(".")

    def quick_help(self):
        import inspect
        expr = self.expression_at_cursor()
        if not expr:
            return
        try:
            ns = self.completion_namespace() if self.completion_namespace else {}
        except Exception:
            ns = {}
        obj = completion.resolve(expr, ns, self.toPlainText())
        if obj is None:
            text = f"<b>{expr}</b><br>No documentation found (run the script once so its names are known)."
        else:
            sig = ""
            try:
                sig = str(inspect.signature(obj))
            except (TypeError, ValueError):
                pass
            doc = inspect.getdoc(obj) or getattr(obj, "__doc__", "") or ""
            if not isinstance(doc, str):
                doc = ""
            if len(doc) > 1600:
                doc = doc[:1600] + " …"
            kind = type(obj).__name__
            import html
            text = (f"<b>{html.escape(expr)}{html.escape(sig)}</b> <span style='color:#999'>({kind})</span>"
                    f"<pre style='white-space:pre-wrap'>{html.escape(doc) or 'No docstring.'}</pre>")
        rect = self.cursorRect()
        QtWidgets.QToolTip.showText(self.viewport().mapToGlobal(rect.bottomLeft()), text, self)

    # --- line tools
    def _block_range(self):
        blocks = self._selected_blocks()
        return blocks[0], blocks[-1]

    def duplicate_line(self):
        cur = self.textCursor()
        if cur.hasSelection() and len(self._selected_blocks()) == 1:
            text = cur.selectedText()
            cur.clearSelection()
            cur.insertText(text)
            return
        first, last = self._block_range()
        text = "\n".join(b.text() for b in self._selected_blocks())
        c = QtGui.QTextCursor(last)
        c.movePosition(QtGui.QTextCursor.EndOfBlock)
        c.insertText("\n" + text)

    def delete_line(self):
        first, last = self._block_range()
        c = QtGui.QTextCursor(first)
        c.beginEditBlock()
        c.setPosition(first.position())
        if last.next().isValid():
            c.setPosition(last.next().position(), QtGui.QTextCursor.KeepAnchor)
        else:
            c.setPosition(last.position() + len(last.text()), QtGui.QTextCursor.KeepAnchor)
            if first.previous().isValid():                  # remove the newline before the last line
                c2 = QtGui.QTextCursor(c)
                c.setPosition(first.position() - 1)
                c.setPosition(c2.position(), QtGui.QTextCursor.KeepAnchor)
        c.removeSelectedText()
        c.endEditBlock()
        self.setTextCursor(c)

    def move_lines(self, step):
        first, last = self._block_range()
        other = first.previous() if step < 0 else last.next()
        if not other.isValid():
            return
        cur = self.textCursor()
        a, p = cur.anchor(), cur.position()
        lines = [b.text() for b in self._selected_blocks()]
        o_text = other.text()
        shift = (len(o_text) + 1) * (1 if step > 0 else -1)
        c = QtGui.QTextCursor(self.document())
        c.beginEditBlock()
        start = (other if step < 0 else first).position()
        end_block = last if step < 0 else other
        c.setPosition(start)
        c.setPosition(end_block.position() + len(end_block.text()), QtGui.QTextCursor.KeepAnchor)
        new = "\n".join(lines + [o_text]) if step < 0 else "\n".join([o_text] + lines)
        c.insertText(new)
        c.endEditBlock()
        nc = self.textCursor()
        nc.setPosition(a + shift)
        nc.setPosition(p + shift, QtGui.QTextCursor.KeepAnchor)
        self.setTextCursor(nc)

    def tabs_to_spaces(self):
        src = self.toPlainText()
        if "\t" not in src:
            return 0
        n = src.count("\t")
        c = QtGui.QTextCursor(self.document())
        c.beginEditBlock()
        c.select(QtGui.QTextCursor.Document)
        c.insertText(src.expandtabs(4))
        c.endEditBlock()
        return n

    # --- typing
    def _key_press(self, ev):
        k = ev.key()
        mods = ev.modifiers()
        ctrl = bool(mods & QtCore.Qt.ControlModifier)
        from . import keymap

        def H(aid):
            return keymap.hit(aid, ev)

        if H("text.save"):
            self.save_requested.emit()
            return
        if H("text.find"):
            self.find_requested.emit()
            return
        if H("text.replace"):
            self.replace_requested.emit()
            return
        if H("text.find_next"):
            self.find_next_requested.emit(False)
            return
        if H("text.find_prev"):
            self.find_next_requested.emit(True)
            return
        if H("text.run_line"):
            self.run_line_requested.emit()
            return
        if H("text.run_all") or H("text.run_script"):
            self.run_requested.emit()
            return
        if H("text.run_selection"):
            self.run_selection_requested.emit()
            return
        if H("text.comment"):
            self._toggle_comment()
            return
        if H("text.goto_line"):
            n, ok = QtWidgets.QInputDialog.getInt(self, "Go to Line", f"Line (1 – {self.blockCount()}):",
                                                  self.textCursor().blockNumber() + 1, 1, self.blockCount())
            if ok:
                self.goto_line(n)
            return
        if H("text.duplicate_line"):
            self.duplicate_line()
            return
        if H("text.delete_line"):
            self.delete_line()
            return
        if H("text.move_line_up"):
            self.move_lines(-1)
            return
        if H("text.move_line_down"):
            self.move_lines(1)
            return
        if H("text.quick_help"):
            self.quick_help()
            return
        if H("text.outline"):
            self.outline_requested.emit()
            return
        if H("text.zoom_in"):
            self.zoom_font(1.0)
            return
        if H("text.zoom_out"):
            self.zoom_font(-1.0)
            return
        if H("text.show_whitespace"):
            self.set_option("show_whitespace", not self.show_whitespace)
            return
        if k == QtCore.Qt.Key_Tab and not ctrl:
            self._indent(True)
            return
        if k == QtCore.Qt.Key_Backtab:
            self._indent(False)
            return
        if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and not ctrl:
            cur = self.textCursor()
            line = cur.block().text()
            before = line[:cur.positionInBlock()]
            after = line[cur.positionInBlock():]
            indent = re.match(r"\s*", line).group(0)
            if before.rstrip().endswith((":", "(", "[", "{")):
                inner = indent + INDENT
                if self.auto_close and after[:1] in (")", "]", "}") and before.rstrip()[-1:] in "([{":
                    # between a pair of brackets: the closer goes to its own line
                    cur.beginEditBlock()
                    cur.insertText("\n" + inner)
                    pos = cur.position()
                    cur.insertText("\n" + indent)
                    cur.setPosition(pos)
                    cur.endEditBlock()
                    self.setTextCursor(cur)
                    return
                indent = inner
            super().keyPressEvent(ev)
            self.insertPlainText(indent)
            return
        text = ev.text()
        if self.auto_close and text and not ctrl and self._auto_pair(text):
            return
        if k == QtCore.Qt.Key_Backspace and not self.textCursor().hasSelection():
            cur = self.textCursor()
            before = cur.block().text()[:cur.positionInBlock()]
            after = cur.block().text()[cur.positionInBlock():]
            if self.auto_close and before[-1:] in _PAIRS and after[:1] == _PAIRS[before[-1]]:
                cur.beginEditBlock()                     # delete an empty pair: () "" …
                cur.deletePreviousChar()
                cur.deleteChar()
                cur.endEditBlock()
                return
            if before and not before.strip() and len(before) % len(INDENT) == 0:
                for _ in range(len(INDENT)):
                    cur.deletePreviousChar()
                return
        super().keyPressEvent(ev)

    def _auto_pair(self, ch):
        """Insert closing brackets / quotes (and step over a closer that is already there)."""
        cur = self.textCursor()
        line = cur.block().text()
        col = cur.positionInBlock()
        nxt = line[col:col + 1]
        prev = line[col - 1:col] if col else ""
        if ch in (")", "]", "}", '"', "'") and nxt == ch and not cur.hasSelection():
            cur.movePosition(QtGui.QTextCursor.Right)        # step over the closer typed already
            self.setTextCursor(cur)
            return True
        if ch not in _PAIRS:
            return False
        if cur.hasSelection():                               # wrap the selection
            sel = cur.selectedText()
            if " " in sel:
                return False
            cur.insertText(ch + sel + _PAIRS[ch])
            return True
        if completion.in_string_or_comment(line[:col]) and ch in "([{":
            return False
        if ch in "\"'":
            if prev.isalnum() or prev == ch or (nxt and (nxt.isalnum() or nxt == "_")):
                return False                                  # it's, ''' …
            if completion.in_string_or_comment(line[:col]):
                return False
        elif nxt and (nxt.isalnum() or nxt == "_"):
            return False
        cur.insertText(ch + _PAIRS[ch])
        cur.movePosition(QtGui.QTextCursor.Left)
        self.setTextCursor(cur)
        return True

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
        from . import keymap

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(3)
        # texts as tabs (like Charcoal / an IDE); all texts of the .blend file
        self.tabs = QtWidgets.QTabBar(self)
        self.tabs.setExpanding(False)
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(QtCore.Qt.ElideNone)
        self.tabs.setToolTip("Texts of the .blend file – click to show one · double-click an empty place: new text")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.installEventFilter(self)
        bar.addWidget(self.tabs, 1)

        def tool(text, tip, fn, py=None):
            b = QtWidgets.QToolButton(self)
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False: fn())
            bar.addWidget(b)
            return b

        tool("+", "New text", self.new_text)
        self.menu_btn = QtWidgets.QToolButton(self)
        self.menu_btn.setText("☰")
        self.menu_btn.setToolTip("Text menu: file, edit, line tools, find, run, view options")
        self.menu_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.menu_btn.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        m = QtWidgets.QMenu(self.menu_btn)
        m.setToolTipsVisible(True)
        m.aboutToShow.connect(lambda: self._fill_menu(m))
        self.menu_btn.setMenu(m)
        bar.addWidget(self.menu_btn)
        self.ac_check = QtWidgets.QCheckBox("Auto-complete", self)
        keymap.tip(self.ac_check, "Suggest names automatically after \".\" and while typing.\n"
                                  "{text.complete} shows the suggestions any time.")
        bar.addWidget(self.ac_check)
        self.state_lab = QtWidgets.QLabel(self)
        bar.addWidget(self.state_lab)
        tool("→ Shelf", "Add the selected code – or the whole text – as a button to the Shelf "
             "(you can also drag selected code onto the Shelf)", self.to_shelf)
        keymap.tip(tool("Run Selection", "", self.run_selection),
                   "Run the selected lines, or the current line, in the script's namespace "
                   "({text.run_selection}; the current line only: {text.run_line}). A single expression "
                   "prints its value. The code stays in the editor.")
        self.unload_btn = tool("■ Unload", "Call the script's unregister() and remove everything it "
                               "registered (menus, docks, overlays, handlers, classes)", self.unload_script)
        self.run_btn = tool("▶ Run Script", "", self.run_script)
        keymap.tip(self.run_btn, "Run the text as a Python script ({text.run_script} · {text.run_all}). "
                                 "If it is already loaded, it is unloaded first.")
        self.run_btn.setStyleSheet(
            "QToolButton{background:#3d6b3d;} "
            "QToolButton:hover{background:#4f8f4f; border:1px solid #8fd08f;} "
            "QToolButton:pressed{background:#62a862; border:1px solid #b0e8b0;}")
        lay.addLayout(bar)

        self.editor = CodeEditor()
        self.editor.completion_namespace = self._completion_namespace
        self.editor.known_names = lambda: self._completion_namespace().keys()
        settings = QtCore.QSettings("QtShell", "QtShell")
        self.editor.auto_complete = str(settings.value("text_editor/autocomplete", "true")).lower() == "true"
        self.ac_check.setChecked(self.editor.auto_complete)
        self.ac_check.toggled.connect(self._set_auto_complete)
        self.editor.save_requested.connect(self.save)
        self.editor.run_requested.connect(self.run_script)
        self.editor.run_selection_requested.connect(self.run_selection)
        self.editor.run_line_requested.connect(self.run_line)
        self.editor.find_requested.connect(lambda: self.show_find(False))
        self.editor.replace_requested.connect(lambda: self.show_find(True))
        self.editor.find_next_requested.connect(lambda back: self.find(back))
        self.editor.outline_requested.connect(self.toggle_outline)
        self.editor.lint_changed.connect(self._problems_changed)
        self.editor.textChanged.connect(self._edited)

        # outline (classes / functions) next to the editor
        self.split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        self.split.addWidget(self.editor)
        self.outline = QtWidgets.QTreeWidget(self.split)
        self.outline.setHeaderHidden(True)
        self.outline.setMinimumWidth(theme.px(120))
        self.outline.setToolTip("Outline: classes and functions – click to go there")
        self.outline.itemClicked.connect(lambda it, _c: self.editor.goto_line(it.data(0, QtCore.Qt.UserRole)))
        self.split.addWidget(self.outline)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)
        self.outline.setVisible(str(settings.value("text_editor/outline", "false")).lower() == "true")
        self._outline_timer = QtCore.QTimer(self)
        self._outline_timer.setSingleShot(True)
        self._outline_timer.setInterval(600)
        self._outline_timer.timeout.connect(self._fill_outline)
        self.editor.textChanged.connect(lambda: self.outline.isVisible() and self._outline_timer.start())
        lay.addWidget(self.split, 1)

        # find / replace bar (Ctrl+F / Ctrl+H)
        self.find_bar = QtWidgets.QWidget(self)
        fl = QtWidgets.QGridLayout(self.find_bar)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setHorizontalSpacing(3)
        fl.setVerticalSpacing(2)
        self.find_edit = QtWidgets.QLineEdit(self.find_bar)
        self.find_edit.setPlaceholderText("Find…")
        self.find_edit.returnPressed.connect(lambda: self.find(False))
        self.find_edit.textChanged.connect(self._update_matches)
        self.replace_edit = QtWidgets.QLineEdit(self.find_bar)
        self.replace_edit.setPlaceholderText("Replace with…")
        self.replace_edit.returnPressed.connect(self.replace_one)
        self.find_case = QtWidgets.QCheckBox("Aa", self.find_bar)
        self.find_case.setToolTip("Match case")
        self.find_word = QtWidgets.QCheckBox("Word", self.find_bar)
        self.find_word.setToolTip("Whole words only")
        self.find_regex = QtWidgets.QCheckBox(".*", self.find_bar)
        self.find_regex.setToolTip("Regular expression")
        for c in (self.find_case, self.find_word, self.find_regex):
            c.toggled.connect(self._update_matches)
        self.match_lab = QtWidgets.QLabel(self.find_bar)
        self.match_lab.setProperty("dim", True)
        fl.addWidget(self.find_edit, 0, 0)
        fl.addWidget(self.find_case, 0, 1)
        fl.addWidget(self.find_word, 0, 2)
        fl.addWidget(self.find_regex, 0, 3)
        col = 4
        for text, back in (("▲", True), ("▼", False)):
            b = QtWidgets.QToolButton(self.find_bar)
            b.setText(text)
            keymap.tip(b, "Previous ({text.find_prev})" if back else "Next ({text.find_next})")
            b.clicked.connect(lambda _c=False, back=back: self.find(back))
            fl.addWidget(b, 0, col)
            col += 1
        fl.addWidget(self.match_lab, 0, col)
        close = QtWidgets.QToolButton(self.find_bar)
        close.setText("✕")
        close.clicked.connect(self.hide_find)
        fl.addWidget(close, 0, col + 1)
        fl.addWidget(self.replace_edit, 1, 0)
        rb = QtWidgets.QToolButton(self.find_bar)
        rb.setText("Replace")
        rb.clicked.connect(self.replace_one)
        fl.addWidget(rb, 1, 1, 1, 2)
        ra = QtWidgets.QToolButton(self.find_bar)
        ra.setText("Replace All")
        ra.clicked.connect(self.replace_all)
        fl.addWidget(ra, 1, 3, 1, 3)
        self._replace_widgets = (self.replace_edit, rb, ra)
        fl.setColumnStretch(0, 1)
        self.find_bar.hide()
        self.find_edit.installEventFilter(self)
        self.replace_edit.installEventFilter(self)
        lay.addWidget(self.find_bar)

        info = QtWidgets.QHBoxLayout()
        self.info = QtWidgets.QLabel(self)
        self.info.setProperty("dim", True)
        info.addWidget(self.info, 1)
        self.problem_btn = QtWidgets.QToolButton(self)
        self.problem_btn.setAutoRaise(True)
        self.problem_btn.setToolTip("Problems found while you type (syntax errors, undefined names) – "
                                    "click: go to the next one")
        self.problem_btn.clicked.connect(self.next_problem)
        self.problem_btn.hide()
        info.addWidget(self.problem_btn)
        lay.addLayout(info)
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

    # --- events: tab bar double-click, Esc in the find bar
    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is self.tabs and t == QtCore.QEvent.MouseButtonDblClick:
            if self.tabs.tabAt(ev.position().toPoint()) < 0:
                self.new_text()
                return True
        if obj in (self.find_edit, self.replace_edit) and t == QtCore.QEvent.KeyPress:
            if ev.key() == QtCore.Qt.Key_Escape:
                self.hide_find()
                return True
        return False

    # --- menu (☰)
    def _fill_menu(self, m):
        from . import keymap
        m.clear()
        ed = self.editor

        def act(menu, text, fn, aid=None, checked=None, tip=None):
            label = f"{text}\t{keymap.text(aid)}" if aid and keymap.text(aid) != "—" else text
            a = menu.addAction(label)
            if checked is not None:
                a.setCheckable(True)
                a.setChecked(bool(checked))
            if tip:
                a.setToolTip(tip)
            a.triggered.connect(lambda _c=False: fn())
            return a

        f = m.addMenu("File")
        act(f, "New Text", self.new_text)
        act(f, "Open…", self.open_file)
        self._fill_recent(f.addMenu("Open Recent"))
        act(f, "Save", self.save, "text.save")
        act(f, "Save As…", self.save_as)
        f.addSeparator()
        act(f, "Delete Text…", self.delete_text, tip="Removes the text from the .blend file")
        e = m.addMenu("Edit")
        act(e, "Undo", ed.undo)
        act(e, "Redo", ed.redo)
        e.addSeparator()
        act(e, "Find…", lambda: self.show_find(False), "text.find")
        act(e, "Find and Replace…", lambda: self.show_find(True), "text.replace")
        act(e, "Go to Line…", lambda: self._key_action("text.goto_line"), "text.goto_line")
        e.addSeparator()
        act(e, "Toggle Comment", ed._toggle_comment, "text.comment")
        act(e, "Indent", lambda: ed._indent(True))
        act(e, "Unindent", lambda: ed._indent(False))
        act(e, "Convert Tabs to Spaces", lambda: self._status(f"Converted {ed.tabs_to_spaces()} tab(s)"))
        ln = m.addMenu("Line")
        act(ln, "Duplicate Line", ed.duplicate_line, "text.duplicate_line")
        act(ln, "Delete Line", ed.delete_line, "text.delete_line")
        act(ln, "Move Line Up", lambda: ed.move_lines(-1), "text.move_line_up")
        act(ln, "Move Line Down", lambda: ed.move_lines(1), "text.move_line_down")
        r = m.addMenu("Run")
        act(r, "Run Script", self.run_script, "text.run_script")
        act(r, "Run Selection", self.run_selection, "text.run_selection")
        act(r, "Run Line", self.run_line, "text.run_line",
            tip="The line with the cursor, without its indentation")
        act(r, "Unload", self.unload_script)
        v = m.addMenu("View")
        act(v, "Outline", self.toggle_outline, "text.outline", checked=self.outline.isVisible())
        act(v, "Show Whitespace", lambda: ed.set_option("show_whitespace", not ed.show_whitespace),
            "text.show_whitespace", checked=ed.show_whitespace)
        act(v, "Indent Guides", lambda: ed.set_option("indent_guides", not ed.indent_guides),
            checked=ed.indent_guides)
        act(v, "Close Brackets and Quotes", lambda: ed.set_option("auto_close", not ed.auto_close),
            checked=ed.auto_close)
        act(v, "Check While Typing", lambda: ed.set_option("live_check", not ed.live_check),
            checked=ed.live_check, tip="Syntax errors and undefined names, underlined while you type")
        v.addSeparator()
        act(v, "Bigger Font", lambda: ed.zoom_font(1.0), "text.zoom_in")
        act(v, "Smaller Font", lambda: ed.zoom_font(-1.0), "text.zoom_out")
        m.addSeparator()
        act(m, "Quick Help", ed.quick_help, "text.quick_help",
            tip="Documentation of the name under the cursor")

    def _key_action(self, aid):
        if aid == "text.goto_line":
            ed = self.editor
            n, ok = QtWidgets.QInputDialog.getInt(self, "Go to Line", f"Line (1 – {ed.blockCount()}):",
                                                  ed.textCursor().blockNumber() + 1, 1, ed.blockCount())
            if ok:
                ed.goto_line(n)

    # --- outline
    def toggle_outline(self):
        on = not self.outline.isVisible()
        self.outline.setVisible(on)
        QtCore.QSettings("QtShell", "QtShell").setValue("text_editor/outline", "true" if on else "false")
        if on:
            self._fill_outline()

    def _fill_outline(self):
        if not self.outline.isVisible():
            return
        self.outline.clear()
        stack = []
        for level, kind, name, line in outline(self.editor.toPlainText()):
            it = QtWidgets.QTreeWidgetItem([("◆ " if kind == "class" else "ƒ ") + name])
            it.setData(0, QtCore.Qt.UserRole, line)
            it.setToolTip(0, f"{kind} {name} – line {line}")
            it.setForeground(0, QtGui.QColor("#ffd866" if kind == "class" else "#8fb3ff"))
            while stack and stack[-1][0] >= level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(it)
            else:
                self.outline.addTopLevelItem(it)
            stack.append((level, it))
        self.outline.expandAll()

    # --- problems
    def _problems_changed(self, probs):
        n_err = sum(1 for p in probs if p[3] == "error")
        n_warn = len(probs) - n_err
        if not probs:
            self.problem_btn.hide()
            return
        parts = []
        if n_err:
            parts.append(f"{n_err} error{'s' if n_err != 1 else ''}")
        if n_warn:
            parts.append(f"{n_warn} warning{'s' if n_warn != 1 else ''}")
        first = probs[0]
        self.problem_btn.setText(f"● {' · '.join(parts)}  –  line {first[0]}: {first[4]}")
        self.problem_btn.setStyleSheet("QToolButton{color:%s;}" % ("#ff6b6b" if n_err else "#e0b84a"))
        self.problem_btn.show()

    def next_problem(self):
        probs = self.editor.problems
        if not probs:
            return
        cur = self.editor.textCursor().blockNumber() + 1
        nxt = next((p for p in probs if p[0] > cur), probs[0])
        self.editor.goto_line(nxt[0], nxt[1])
        self._status(f"Line {nxt[0]}: {nxt[4]}")

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
        if self._name not in names:
            self._name = None
        if self._name is None:
            self._name = names[0] if names else None
            self._load()
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for n in names:
            t = bpy.data.texts.get(n)
            i = self.tabs.addTab(n)
            self.tabs.setTabData(i, n)
            tip = bpy.path.abspath(t.filepath) if t is not None and t.filepath else "internal (saved in the .blend)"
            self.tabs.setTabToolTip(i, tip)
        if self._name in names:
            self.tabs.setCurrentIndex(names.index(self._name))
        self.tabs.blockSignals(False)

    def _tab_changed(self, i):
        name = self.tabs.tabData(i)
        if name and name != self._name:
            self.show_text(name)

    def show_text(self, name):
        self._write_back()
        self._name = name
        self._load()
        self.refresh_list()

    def goto(self, filename, line):
        """Shows the text a traceback line points to (by its name or file path) at the line – used by the
        Console's clickable error lines. Returns False when no text matches."""
        norm = os.path.normcase(os.path.normpath(filename))
        target = bpy.data.texts.get(filename)
        if target is None:
            for t in bpy.data.texts:
                if t.filepath and os.path.normcase(os.path.normpath(bpy.path.abspath(t.filepath))) == norm:
                    target = t
                    break
        if target is None and os.path.isfile(filename):
            r = QtWidgets.QMessageBox.question(
                self, "Open File", f"{filename}\n\nisn't open in the Text editor. Open it there?")
            if r != QtWidgets.QMessageBox.Yes:
                return False
            try:
                target = bpy.data.texts.load(filename)
            except Exception as ex:
                QtWidgets.QMessageBox.warning(self, "Open File", str(ex))
                return False
        if target is None:
            return False
        mw = getattr(self.hub, "main_window", None)
        d = getattr(mw, "docks", {}).get("text_editor") if mw is not None else None
        if d is not None:
            d.show()
            d.raise_()
        if target.name != self._name:
            self.show_text(target.name)
        self.editor.goto_line(int(line))
        return True

    def _load(self):
        t = self._text()
        self._loading = True
        self.editor.setPlainText(t.as_string() if t is not None else "")
        self.editor.setReadOnly(t is None)
        self.editor.setPlaceholderText("" if t is not None else "No text – click “+” or ☰ → File → Open…")
        self.editor.mark_error(None)
        self._loading = False
        self._update_info()
        self._update_state()
        self.editor.run_lint()
        self._fill_outline()
        if self.find_bar.isVisible():
            self._update_matches()

    def _edited(self):
        if not self._loading:
            if self.editor._error_line:
                self.editor.mark_error(None)
            self._push.start()
            if self.find_bar.isVisible():
                self._update_matches()

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
        if names != [self.tabs.tabData(i) for i in range(self.tabs.count())]:
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
        if c.hasSelection():
            where += f"  ({len(c.selectedText())} selected)"
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
        recent = self.recent_files()
        start = (os.path.dirname(recent[0]) if recent else "") or os.path.dirname(bpy.data.filepath) \
            or os.path.expanduser("~")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open Text", start,
                                                        "Python (*.py);;Text (*.txt);;All files (*)")
        if not path:
            return
        self.open_path(path)

    def open_path(self, path):
        """Opens a file in the Text editor – a text already loaded from that file is just shown."""
        self._write_back()
        norm = os.path.normcase(os.path.abspath(path))
        t = next((x for x in bpy.data.texts
                  if x.filepath and os.path.normcase(os.path.abspath(bpy.path.abspath(x.filepath))) == norm), None)
        if t is None:
            try:
                t = bpy.data.texts.load(path)
            except Exception as ex:
                QtWidgets.QMessageBox.warning(self, "Open Text", str(ex))
                return None
        self._add_recent(path)
        self._name = t.name
        self._load()
        self.refresh_list()
        return t

    # --- recent files (File → Open Recent)
    RECENT_MAX = 20

    @staticmethod
    def recent_files():
        """Text files opened / saved in the Text editor, newest first (shared by all Blender sessions)."""
        v = QtCore.QSettings("QtShell", "QtShell").value("text_editor/recent", [])
        if isinstance(v, str):
            v = [v] if v else []
        return [str(p) for p in (v or []) if p]

    def _add_recent(self, path):
        path = os.path.abspath(path)
        norm = os.path.normcase(path)
        files = [path] + [p for p in self.recent_files() if os.path.normcase(os.path.abspath(p)) != norm]
        QtCore.QSettings("QtShell", "QtShell").setValue("text_editor/recent", files[:self.RECENT_MAX])

    def clear_recent(self):
        QtCore.QSettings("QtShell", "QtShell").setValue("text_editor/recent", [])

    def _fill_recent(self, menu):
        """Like File → Open Recent of the main window: numbered, newest first, missing files greyed out."""
        menu.setToolTipsVisible(True)
        files = self.recent_files()
        if not files:
            menu.addAction("No recent files").setEnabled(False)
        fm = menu.fontMetrics()
        names = [os.path.basename(p) for p in files]
        icon = None
        try:
            from . import blicons
            icon = blicons.icon("FILE_SCRIPT") if blicons.has("FILE_SCRIPT") else None
        except Exception:
            pass
        for i, path in enumerate(files):
            name = names[i]
            label = name if names.count(name) == 1 else f"{name}  ({os.path.basename(os.path.dirname(path))})"
            label = fm.elidedText(label, QtCore.Qt.ElideMiddle, theme.px(420))
            prefix = f"&{i + 1}  " if i < 9 else ("1&0  " if i == 9 else f"{i + 1}  ")
            a = menu.addAction(prefix + label)
            a.setToolTip(path)
            a.setStatusTip(path)
            if icon is not None:
                a.setIcon(icon)
            if not os.path.exists(path):
                a.setEnabled(False)
                a.setToolTip(path + "\n(file not found)")
            a.triggered.connect(lambda _=False, p=path: self.open_path(p))
        menu.addSeparator()
        clear = menu.addAction("Clear Recent Files List")
        clear.setEnabled(bool(files))
        clear.triggered.connect(self.clear_recent)

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
            self.refresh_list()

    def _write_file(self, path):
        self._write_back()
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(self.editor.toPlainText())
        except Exception as ex:
            QtWidgets.QMessageBox.warning(self, "Save Text", str(ex))
            return False
        self._status(f"Saved {path}")
        self._add_recent(path)
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

    def run_selection(self, only_line=False):
        """Runs the selected lines (or the current line) in the namespace of the script (Ctrl+Enter)."""
        t = self._text()
        if t is None:
            return
        self._write_back()
        cur = self.editor.textCursor()
        blocks = self.editor._selected_blocks()
        if only_line:
            blocks = [cur.block()]
            src = cur.block().text()
        elif cur.hasSelection() and len(blocks) == 1:
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

    def run_line(self):
        """Runs only the line with the cursor (Charcoal's Execute Line) – its indentation is removed."""
        self.run_selection(only_line=True)

    def to_shelf(self):
        mw = getattr(self.hub, "main_window", None)
        shelf = getattr(mw, "shelf", None)
        if shelf is None:
            return
        cur = self.editor.textCursor()
        code = cur.selectedText().replace(" ", "\n") if cur.hasSelection() else self.editor.toPlainText()
        t = self._text()
        name = os.path.splitext(t.name)[0] if t is not None and not cur.hasSelection() else None
        d = getattr(mw, "docks", {}).get("shelf")
        if d is not None:
            d.show()
            d.raise_()
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

    # --- find / replace
    def show_find(self, replace=False):
        sel = self.editor.textCursor().selectedText()
        if sel and " " not in sel:
            self.find_edit.setText(sel)
        for w in self._replace_widgets:
            w.setVisible(replace)
        self.find_bar.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        self._update_matches()

    def hide_find(self):
        self.find_bar.hide()
        self.editor.find_matches = []
        self.editor._highlight_line()
        self.editor.setFocus()

    def _pattern(self):
        text = self.find_edit.text()
        if not text:
            return None
        pat = text if self.find_regex.isChecked() else re.escape(text)
        if self.find_word.isChecked():
            pat = rf"\b{pat}\b"
        try:
            return re.compile(pat, 0 if self.find_case.isChecked() else re.IGNORECASE)
        except re.error:
            return None

    def _update_matches(self):
        rx = self._pattern()
        if rx is None or not self.find_bar.isVisible():
            self.editor.find_matches = []
            self.match_lab.setText("" if not self.find_edit.text() else "invalid")
        else:
            src = self.editor.toPlainText()
            self.editor.find_matches = [(m.start(), m.end()) for m in rx.finditer(src) if m.end() > m.start()]
            n = len(self.editor.find_matches)
            self.match_lab.setText(f"{n} match{'es' if n != 1 else ''}" if n else "no matches")
        self.editor._highlight_line()

    def find(self, backward=False):
        if not self.find_bar.isVisible() and not self.find_edit.text():
            self.show_find(False)
            return
        self._update_matches()
        ms = self.editor.find_matches
        if not ms:
            self._status(f"“{self.find_edit.text()}” not found")
            return
        cur = self.editor.textCursor()
        pos = cur.selectionStart() if backward else cur.selectionEnd()
        if backward:
            cand = [m for m in ms if m[1] <= pos and m != (cur.selectionStart(), cur.selectionEnd())]
            m = cand[-1] if cand else ms[-1]
        else:
            cand = [m for m in ms if m[0] >= pos]
            m = cand[0] if cand else ms[0]
        c = self.editor.textCursor()
        c.setPosition(m[0])
        c.setPosition(m[1], QtGui.QTextCursor.KeepAnchor)
        self.editor.setTextCursor(c)
        self.editor.centerCursor()
        i = ms.index(m) + 1
        self.match_lab.setText(f"{i} of {len(ms)}")

    def _replacement(self, m):
        rep = self.replace_edit.text()
        return m.expand(rep) if self.find_regex.isChecked() else rep

    def replace_one(self):
        rx = self._pattern()
        if rx is None:
            return
        cur = self.editor.textCursor()
        sel = cur.selectedText()
        m = rx.fullmatch(sel) if sel else None
        if m is not None:
            cur.insertText(self._replacement(m))
        self.find(False)

    def replace_all(self):
        rx = self._pattern()
        if rx is None:
            return
        src = self.editor.toPlainText()
        new, n = rx.subn(lambda m: self._replacement(m), src)
        if not n:
            self._status("Nothing to replace")
            return
        c = QtGui.QTextCursor(self.editor.document())
        c.beginEditBlock()
        c.select(QtGui.QTextCursor.Document)
        c.insertText(new)
        c.endEditBlock()
        self._status(f"Replaced {n} occurrence{'s' if n != 1 else ''}")
        self._update_matches()

    def _status(self, msg):
        mw = getattr(self.hub, "main_window", None)
        if mw is not None:
            mw.statusBar().showMessage(msg, 5000)

    def shutdown(self):
        self._write_back()
        self._poll.stop()

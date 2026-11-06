"""Error window: when Qt Shell hits a Python error, a window shows it and offers to report it on GitHub.

Shown for real program errors only – a logged traceback (bridge.log(..., "ERROR") with a traceback) or an
exception nobody caught (sys.excepthook, e.g. in a Qt slot). Ordinary operator failures ("nothing selected",
poll failed …) stay in the status bar. Several errors in a row collect in the same window; an error that was
already shown (same place, same message) doesn't open it again in this session.

Report on GitHub opens a new issue in the browser with the title and the details filled in (versions, OS,
the traceback with the home folder replaced by ~) – nothing is sent until the user submits it there.
QSettings "errors/popup" (check box in the window) turns the window off; the errors still go to the log.
"""
import os
import platform
import sys
import time
import traceback
import urllib.parse

from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, theme

KEY_POPUP = "errors/popup"
ISSUES = "https://github.com/xmoner/blender-qt-shell/issues/new"
MAX_URL = 7000                   # browsers / GitHub cut longer addresses

_window = None                   # the main window (parent of the dialog)
_dialog = None
_seen = set()                    # signatures of errors shown this session
_prev_hook = None
_installed = False


def _settings():
    return QtCore.QSettings("QtShell", "QtShell")


def enabled():
    return str(_settings().value(KEY_POPUP, "true")).lower() != "false"


def set_enabled(on):
    _settings().setValue(KEY_POPUP, "true" if on else "false")


# the operator can't run here (wrong mode, nothing selected …) or reported its own error – a usage situation,
# not a bug in Qt Shell: the status bar / Console show it, no window
_USAGE = ("poll() failed", "context is incorrect", "RuntimeError: Error:", "RuntimeError: Warning:",
          "KeyboardInterrupt")


def is_program_error(msg, level):
    msg = msg or ""
    if level != "ERROR" or "Traceback (most recent call last)" not in msg:
        return False
    last = next((ln.strip() for ln in reversed(msg.splitlines()) if ln.strip()), "")
    return not any(u in last for u in _USAGE)


def signature(msg):
    """Where + what: the last 'File …, line …' of the traceback and the exception line."""
    lines = [ln.strip() for ln in (msg or "").splitlines() if ln.strip()]
    where = next((ln for ln in reversed(lines) if ln.startswith("File ")), "")
    return (where, lines[-1] if lines else "")


def summary(msg):
    """One line for the window's heading: the exception (+ the context the code logged before it)."""
    lines = [ln for ln in (msg or "").splitlines() if ln.strip()]
    if not lines:
        return "Unknown error"
    head = lines[0].strip()
    last = lines[-1].strip()
    if head.startswith("Traceback") or head == last:
        return last
    return f"{head.rstrip(':')} – {last}"


def anonymize(text):
    """Home folder → ~ (user name out of the paths)."""
    home = os.path.expanduser("~")
    out = text or ""
    for h in {home, home.replace("\\", "/")}:
        if h and len(h) > 3:
            out = out.replace(h, "~")
    return out


def system_info():
    from . import bl_info
    try:
        import bpy
        blender = bpy.app.version_string
    except Exception:
        blender = "?"
    try:
        from PySide6 import __version__ as pyside
    except Exception:
        pyside = "?"
    return {"Qt Shell": ".".join(str(x) for x in bl_info["version"]), "Blender": blender,
            "OS": platform.platform(), "Python": platform.python_version(), "PySide6": pyside}


def issue_url(errors):
    """GitHub 'new issue' address with the title and body filled in (errors: [(time, text)])."""
    info = system_info()
    first = errors[0][1] if errors else ""
    title = f"Error: {summary(first)}"[:120]
    head = "\n".join(f"- **{k}:** {v}" for k, v in info.items())

    def body_for(tb):
        return ("**What were you doing when the error happened?**\n\n<!-- describe the steps here -->\n\n"
                f"**System**\n{head}\n\n**Error**\n```\n{tb}\n```\n")
    tb = anonymize("\n\n".join(t for _s, t in errors))
    body = body_for(tb)
    url = f"{ISSUES}?title={urllib.parse.quote(title)}&body={urllib.parse.quote(body)}"
    while len(url) > MAX_URL and len(tb) > 200:      # keep the end of the traceback – the useful part
        tb = "…\n" + tb[-int(len(tb) * 0.8):]
        body = body_for(tb + "\n(shortened – the full text is in the Qt Shell log)")
        url = f"{ISSUES}?title={urllib.parse.quote(title)}&body={urllib.parse.quote(body)}"
    return url


class ErrorDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Qt Shell – Error")
        self.setWindowFlag(QtCore.Qt.WindowContextHelpButtonHint, False)
        self.errors = []                         # [(time, text)]
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel(self)
        icon.setPixmap(self.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxCritical).pixmap(theme.px(32)))
        top.addWidget(icon, 0, QtCore.Qt.AlignTop)
        self.head = QtWidgets.QLabel(self)
        self.head.setWordWrap(True)
        self.head.setTextFormat(QtCore.Qt.RichText)
        self.head.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        top.addWidget(self.head, 1)
        lay.addLayout(top)
        self.details = QtWidgets.QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.details.setFont(f)
        lay.addWidget(self.details, 1)
        self.popup = QtWidgets.QCheckBox("Show this window when an error happens", self)
        self.popup.setChecked(enabled())
        self.popup.setToolTip("Off: errors only go to the Console and the log file")
        self.popup.toggled.connect(set_enabled)
        lay.addWidget(self.popup)
        row = QtWidgets.QHBoxLayout()
        self.report_btn = QtWidgets.QPushButton("Report on GitHub…", self)
        self.report_btn.setToolTip("Opens a new GitHub issue in your browser with the error and your versions "
                                   "filled in – check it, describe what you did and submit it there")
        self.report_btn.clicked.connect(self.report)
        copy = QtWidgets.QPushButton("Copy Details", self)
        copy.setToolTip("Copies the error text with the versions (for a message or an issue)")
        copy.clicked.connect(self.copy)
        log_btn = QtWidgets.QPushButton("Open Log", self)
        log_btn.setToolTip(bridge.log_path())
        log_btn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(bridge.log_path())))
        close = QtWidgets.QPushButton("Close", self)
        close.clicked.connect(self.close)
        row.addWidget(self.report_btn)
        row.addWidget(copy)
        row.addWidget(log_btn)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self.resize(theme.px(720), theme.px(420))
        self.report_url = None                   # last address Report on GitHub opened (tests)

    def add(self, text):
        self.errors.append((time.strftime("%H:%M:%S"), text))
        n = len(self.errors)
        first = summary(self.errors[0][1])
        more = f"<br><span style='color:#aaa'>{n} errors – all of them are below.</span>" if n > 1 else ""
        self.head.setText(f"<b>Something went wrong in Qt Shell.</b><br>{_html(first)}{more}"
                          "<br><span style='color:#aaa'>Blender keeps running – you can usually go on working. "
                          "Reporting it helps to fix it.</span>")
        self.details.setPlainText("\n\n".join(f"[{t}]\n{x}" for t, x in self.errors))
        self.details.moveCursor(QtGui.QTextCursor.End)

    def text(self):
        info = "\n".join(f"{k}: {v}" for k, v in system_info().items())
        return anonymize(info + "\n\n" + "\n\n".join(f"[{t}]\n{x}" for t, x in self.errors))

    def copy(self):
        QtWidgets.QApplication.clipboard().setText(self.text())

    def report(self):
        from .main_window import open_url
        self.report_url = issue_url(self.errors)
        open_url(self.report_url)

    def closeEvent(self, ev):
        global _dialog
        _dialog = None
        super().closeEvent(ev)
        self.deleteLater()


def _html(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def show_error(text, force=False):
    """Shows (or adds to) the error window. Returns the dialog, or None when it isn't shown."""
    global _dialog
    sig = signature(text)
    if not force and (sig in _seen or not enabled()):
        return None
    _seen.add(sig)
    if _window is None:
        return None
    try:
        if _dialog is None:
            _dialog = ErrorDialog(_window)
        _dialog.add(text)
        if not _dialog.isVisible():
            _dialog.show()
        _dialog.raise_()
        return _dialog
    except Exception:
        print("[QtShell] error window failed:\n" + traceback.format_exc())
        return None


def _on_log(msg, level):
    if is_program_error(msg, level):
        text = str(msg)
        QtCore.QTimer.singleShot(0, lambda: show_error(text))     # outside the code that failed


def _excepthook(etype, value, tb):
    """Uncaught exceptions (Qt slots, …): printed as before, logged and shown."""
    text = "".join(traceback.format_exception(etype, value, tb))
    try:
        if _prev_hook is not None and _prev_hook is not _excepthook:
            _prev_hook(etype, value, tb)
    except Exception:
        pass
    if issubclass(etype, (KeyboardInterrupt, SystemExit)):
        return
    bridge.log("Uncaught error:\n" + text, "ERROR")        # → _on_log → the window


def install(window):
    """Called when the Qt Shell window exists."""
    global _window, _prev_hook, _installed
    _window = window
    if not _installed:
        bridge.add_log_listener(_on_log)
        _prev_hook = sys.excepthook
        sys.excepthook = _excepthook
        _installed = True


def uninstall():
    global _window, _dialog, _installed
    if _installed:
        bridge.remove_log_listener(_on_log)
        if sys.excepthook is _excepthook:
            sys.excepthook = _prev_hook or sys.__excepthook__
        _installed = False
    if _dialog is not None:
        try:
            _dialog.close()
        except RuntimeError:
            pass
    _dialog = None
    _window = None

"""Help → Check for Qt Shell Updates…: compares the running version with the GitHub releases.

The releases of github.com/xmoner/blender-qt-shell are read in a background thread (the UI never waits on
the network). A newer release shows its notes (all releases newer than the running one); the Version list
holds every published release (the newest 30) – also older ones to go back to – and offers:

- Install – downloads the picked release's qt_shell.zip and installs it like Edit → Preferences → Add-ons →
  Install from Disk (the add-on folder is replaced); Blender must then be restarted;
- Open Release Page – the release on GitHub in the web browser.

Respects Blender's Preferences → System → Network → Allow Online Access (no request when it is off).
Optional quiet check at startup (once a day, off by default – check box in the dialog, QSettings
"updates/auto"): a newer release is announced in the status bar.
"""
import json
import os
import re
import tempfile
import threading
import time
import traceback
import urllib.request
import webbrowser

import bpy
from PySide6 import QtCore, QtGui, QtWidgets

from . import bridge, theme

REPO = "xmoner/blender-qt-shell"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
PAGE = f"https://github.com/{REPO}/releases"
ASSET = "qt_shell.zip"
AUTO_INTERVAL = 24 * 3600


def current_version():
    from . import bl_info
    return tuple(int(v) for v in bl_info["version"])


def parse_version(tag):
    """'v0.71.0' / 'Qt Shell 0.71' → (0, 71, 0); None when there are no numbers."""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(tag or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def vstr(v):
    return ".".join(str(x) for x in v) if v else "?"


def online_allowed():
    """Blender 4.2+: Preferences → System → Network → Allow Online Access."""
    return bool(getattr(bpy.app, "online_access", True))


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "QtShell-update-check",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_releases():
    """[{version, tag, name, notes, url, zip, date}] of the published releases, newest first."""
    out = []
    for r in json.loads(_get(API).decode("utf-8")):
        if r.get("draft") or r.get("prerelease"):
            continue
        v = parse_version(r.get("tag_name")) or parse_version(r.get("name"))
        if v is None:
            continue
        zip_url = next((a.get("browser_download_url") for a in r.get("assets", [])
                        if a.get("name") == ASSET), None)
        out.append({"version": v, "tag": r.get("tag_name", ""), "name": r.get("name") or r.get("tag_name", ""),
                    "notes": r.get("body") or "", "url": r.get("html_url") or PAGE, "zip": zip_url,
                    "date": (r.get("published_at") or "")[:10]})
    out.sort(key=lambda x: x["version"], reverse=True)
    return out


class _Bridge(QtCore.QObject):
    done = QtCore.Signal(object, object)       # (result, error text) – delivered in the Qt thread


def run_async(fn, callback, parent):
    """fn() in a thread; callback(result, error) in the Qt (main) thread."""
    br = _Bridge(parent)

    def finish(res, err):
        try:
            callback(res, err)
        finally:
            br.deleteLater()
    br.done.connect(finish)

    def work():
        try:
            res = fn()
            br.done.emit(res, None)
        except Exception as ex:
            msg = str(ex)
            if "403" in msg:
                msg += " – GitHub's limit of anonymous requests; try again in an hour"
            br.done.emit(None, msg)
    threading.Thread(target=work, daemon=True, name="QtShell update check").start()
    return br


def install_zip(path):
    """Installs a downloaded qt_shell.zip like Install from Disk (overwrites the add-on folder)."""
    with bridge.blender_context():
        res = bpy.ops.preferences.addon_install(overwrite=True, filepath=path)
    if "FINISHED" not in res:
        raise RuntimeError(f"Blender did not install the add-on ({', '.join(res)})")


def _settings():
    return QtCore.QSettings("QtShell", "QtShell")


def auto_enabled():
    return str(_settings().value("updates/auto", "false")).lower() == "true"


class UpdateDialog(QtWidgets.QDialog):
    """Help → Check for Qt Shell Updates…"""

    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        self.setWindowTitle("Qt Shell Updates")
        self.releases = []
        self.newer = []
        lay = QtWidgets.QVBoxLayout(self)
        self.head = QtWidgets.QLabel(self)
        self.head.setWordWrap(True)
        self.head.setTextFormat(QtCore.Qt.RichText)
        self.head.setOpenExternalLinks(True)
        lay.addWidget(self.head)
        # every published release (newest first) – also older ones to go back to
        vrow = QtWidgets.QHBoxLayout()
        self.version_label = QtWidgets.QLabel("Version", self)
        self.version_combo = QtWidgets.QComboBox(self)
        self.version_combo.setToolTip("The releases on GitHub (newest first) – pick one to see its notes and "
                                      "install it, also an older version to go back to")
        self.version_combo.currentIndexChanged.connect(lambda _i: self._show_selected())
        vrow.addWidget(self.version_label)
        vrow.addWidget(self.version_combo, 1)
        lay.addLayout(vrow)
        self.notes = QtWidgets.QTextBrowser(self)
        self.notes.setOpenExternalLinks(True)
        pal = self.notes.palette()                 # readable links on the dark theme
        pal.setColor(QtGui.QPalette.Link, QtGui.QColor("#6fa8ff"))
        self.notes.setPalette(pal)
        self.notes.setVisible(False)
        lay.addWidget(self.notes, 1)
        self.progress = QtWidgets.QProgressBar(self)
        self.progress.setRange(0, 0)
        lay.addWidget(self.progress)
        self.auto = QtWidgets.QCheckBox("Check for updates when Qt Shell starts (once a day)", self)
        self.auto.setChecked(auto_enabled())
        self.auto.toggled.connect(lambda on: _settings().setValue("updates/auto", "true" if on else "false"))
        lay.addWidget(self.auto)
        row = QtWidgets.QHBoxLayout()
        self.install_btn = QtWidgets.QPushButton("Install", self)
        self.install_btn.setToolTip("Download the release's qt_shell.zip and install it (like Edit → Preferences → "
                                    "Add-ons → Install from Disk – the add-on folder is replaced); then restart "
                                    "Blender")
        self.install_btn.clicked.connect(self.install)
        self.page_btn = QtWidgets.QPushButton("Open Release Page", self)
        self.page_btn.clicked.connect(self.open_page)
        self.retry_btn = QtWidgets.QPushButton("Check Again", self)
        self.retry_btn.clicked.connect(lambda: self.check(self._forced))
        self.force_btn = QtWidgets.QPushButton("Check Anyway", self)
        self.force_btn.setToolTip("Connect to GitHub this once, although Blender's online access is off")
        self.force_btn.clicked.connect(lambda: self.check(True))
        close = QtWidgets.QPushButton("Close", self)
        close.clicked.connect(self.reject)
        row.addWidget(self.install_btn)
        row.addWidget(self.page_btn)
        row.addStretch(1)
        row.addWidget(self.force_btn)
        row.addWidget(self.retry_btn)
        row.addWidget(close)
        lay.addLayout(row)
        self.resize(theme.px(620), theme.px(220))
        self._busy = False
        self._forced = False          # "Check Anyway" – the user allowed this dialog to go online

    def _set_head(self, html):
        self.head.setText(html)

    def selected(self):
        """The release picked in the Version list (None before the releases are read)."""
        i = self.version_combo.currentIndex()
        return self.releases[i] if 0 <= i < len(self.releases) and self.version_combo.count() else None

    def _buttons(self):
        rel = self.selected()
        self.install_btn.setVisible(bool(rel and rel.get("zip")))
        if rel is not None:
            cur = current_version()
            v = vstr(rel["version"])
            self.install_btn.setText(f"Install {v}" if rel["version"] > cur else
                                     f"Reinstall {v}" if rel["version"] == cur else f"Install {v} (older)")
            self.install_btn.setMinimumWidth(self.install_btn.fontMetrics().horizontalAdvance(
                self.install_btn.text()) + theme.px(24))       # the text changes – never clipped
        self.page_btn.setVisible(True)
        self.install_btn.setEnabled(not self._busy)
        self.retry_btn.setEnabled(not self._busy)
        offline = not online_allowed() and not self._forced
        self.force_btn.setVisible(offline)
        self.retry_btn.setVisible(not offline)
        self.progress.setVisible(self._busy)

    # --- check
    def check(self, force=False):
        """Reads the releases. force: also when Blender's online access is off (the user's explicit click)."""
        cur = vstr(current_version())
        self.newer = []
        self.notes.setVisible(False)
        self.version_label.setVisible(False)
        self.version_combo.setVisible(False)
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        self.version_combo.blockSignals(False)
        self._forced = self._forced or bool(force)
        if not online_allowed() and not self._forced:
            self._set_head(f"Qt Shell <b>{cur}</b> is running.<br><br>Blender's online access is off "
                           "(Edit → Preferences → System → Network → <i>Allow Online Access</i>), so Qt Shell does "
                           "not connect to GitHub on its own. <b>Check Anyway</b> connects this once; or open the "
                           "release page in your browser.")
            self._busy = False
            self._buttons()
            return
        self._set_head(f"Qt Shell <b>{cur}</b> is running. Looking for a newer release on GitHub…")
        self._busy = True
        self._buttons()
        run_async(fetch_releases, self._checked, self)

    def _checked(self, releases, err):
        self._busy = False
        cur = current_version()
        if err:
            self._set_head(f"Qt Shell <b>{vstr(cur)}</b> is running.<br><br>Could not read the releases: {err}")
            self._buttons()
            return
        self.releases = releases or []
        _settings().setValue("updates/last_check", time.time())
        self.newer = [r for r in self.releases if r["version"] > cur]
        latest = self.releases[0] if self.releases else None
        if self.newer:
            n = self.newer[0]
            self._set_head(f"<b>Qt Shell {vstr(n['version'])} is available</b> ({n['date']}) – you have "
                           f"{vstr(cur)}." + (f" {len(self.newer)} newer releases:" if len(self.newer) > 1 else ""))
        elif latest is not None and cur > latest["version"]:
            self._set_head(f"Qt Shell <b>{vstr(cur)}</b> is newer than the latest release "
                           f"({vstr(latest['version'])}).")
        elif latest is not None:
            self._set_head(f"Qt Shell <b>{vstr(cur)}</b> is up to date (the latest release, {latest['date']}).")
        else:
            self._set_head(f"Qt Shell <b>{vstr(cur)}</b> is running. No releases found.")
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        for r in self.releases:
            tag = "installed" if r["version"] == cur else "newer" if r["version"] > cur else "older"
            self.version_combo.addItem(f"{vstr(r['version'])}  ·  {r['date']}  ·  {tag}  –  {r['name']}")
        self.version_combo.setCurrentIndex(0)
        self.version_combo.blockSignals(False)
        self.version_label.setVisible(bool(self.releases))
        self.version_combo.setVisible(bool(self.releases))
        if self.releases:
            self.resize(self.width(), max(self.height(), theme.px(480)))
        self._show_selected()

    def select_version(self, version):
        """Picks a release in the Version list: (0, 70, 0) or '0.70.0'. Returns True when it is listed."""
        v = parse_version(version) if isinstance(version, str) else tuple(version)
        for i, r in enumerate(self.releases):
            if r["version"] == v:
                self.version_combo.setCurrentIndex(i)
                return True
        return False

    def _show_selected(self):
        """The notes of the release picked (the newest with newer releases: the notes of all of them)."""
        rel = self.selected()
        if rel is None:
            self.notes.setVisible(False)
            self._buttons()
            return
        shown = self.newer if (self.newer and rel is self.newer[0]) else [rel]
        md = "\n\n---\n\n".join(f"# {r['name']}\n\n*{r['date']}* · [release page]({r['url']})\n\n{r['notes']}"
                                  for r in shown)
        self.notes.setMarkdown(md)
        # Qt gives links a fixed dark blue – unreadable on the dark theme
        html = re.sub(r'(<a href="[^"]*"><span style="[^"]*?color:)#[0-9a-fA-F]{6}', r"\g<1>#6fa8ff",
                      self.notes.toHtml())
        self.notes.setHtml(html)
        self.notes.setVisible(True)
        self._buttons()

    # --- actions
    def open_page(self):
        rel = self.selected()
        url = rel["url"] if rel else PAGE
        if not QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)):
            webbrowser.open(url)

    def install(self, dry_run=False):
        """Downloads the release picked in the Version list (default the newest) and installs it.
        dry_run: download and check only."""
        rel = self.selected()
        if rel is None or not rel.get("zip"):
            return
        if not dry_run:
            older = rel["version"] < current_version()
            ok = QtWidgets.QMessageBox.question(
                self, "Install Qt Shell", f"Install Qt Shell {vstr(rel['version'])}"
                + (f" – an OLDER version than the running {vstr(current_version())}" if older else "") +
                "?\n\nThe add-on folder is replaced (like Install from Disk); your settings, shelves and shortcuts "
                "stay. Restart Blender afterwards to use it." + ("\n\nFeatures added after this version will be "
                                                                "missing; you can update again any time." if older else ""),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if ok != QtWidgets.QMessageBox.Yes:
                return
        self._busy = True
        self._buttons()
        self._set_head(f"Downloading Qt Shell {vstr(rel['version'])}…")
        dst = os.path.join(tempfile.gettempdir(), f"qt_shell_{vstr(rel['version'])}.zip")

        def download():
            data = _get(rel["zip"], timeout=60)
            with open(dst, "wb") as f:
                f.write(data)
            import zipfile
            with zipfile.ZipFile(dst) as z:
                names = z.namelist()
            if not any(n.startswith("qt_shell/") and n.endswith("__init__.py") for n in names):
                raise RuntimeError("the downloaded file is not a Qt Shell add-on")
            return dst
        run_async(download, lambda p, err: self._downloaded(rel, p, err, dry_run), self)

    def _downloaded(self, rel, path, err, dry_run):
        self._busy = False
        self.last_download = path
        if err:
            self._set_head(f"Download failed: {err}")
            self._buttons()
            return
        if dry_run:
            self._set_head(f"Downloaded {path} (not installed – dry run).")
            self._buttons()
            return
        try:
            install_zip(path)
        except Exception as ex:
            bridge.log(traceback.format_exc(), "WARNING")
            self._set_head(f"Installing failed: {ex}<br>The zip is in {path} – install it from Edit → "
                           "Preferences → Add-ons → Install from Disk.")
            self._buttons()
            return
        self._set_head(f"<b>Qt Shell {vstr(rel['version'])} is installed.</b><br><br>Restart Blender to use it "
                       f"(the running Qt Shell is still {vstr(current_version())}). After the restart the status "
                       "bar shows the new version.")
        self._buttons()
        st = getattr(self.window_, "statusBar", None)
        if st is not None:
            self.window_.statusBar().showMessage(f"Qt Shell {vstr(rel['version'])} installed – restart Blender", 0)


def open_dialog(window):
    """Help → Check for Qt Shell Updates…"""
    dlg = getattr(window, "_update_dialog", None)
    try:
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return dlg
    except RuntimeError:
        pass
    dlg = UpdateDialog(window)
    dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    window._update_dialog = dlg
    dlg.show()
    dlg.check()
    return dlg


def auto_check(window):
    """At startup: with 'Check for updates when Qt Shell starts' on, at most once a day and only with
    Blender's online access on – a newer release is announced in the status bar."""
    if not auto_enabled() or not online_allowed():
        return False
    try:
        last = float(_settings().value("updates/last_check", 0) or 0)
    except (TypeError, ValueError):
        last = 0.0
    if time.time() - last < AUTO_INTERVAL:
        return False

    def done(releases, err):
        if err or not releases:
            return
        _settings().setValue("updates/last_check", time.time())
        newest = releases[0]
        if newest["version"] > current_version():
            try:
                window.statusBar().showMessage(f"Qt Shell {vstr(newest['version'])} is available – "
                                               "Help → Check for Qt Shell Updates…", 30000)
            except RuntimeError:
                pass
    run_async(fetch_releases, done, window)
    return True

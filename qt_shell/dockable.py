"""Windows that can be docked into the Qt Shell window (Render View, Animation Player).

`Dockable` is a mixin for a QWidget that normally is its own window (owned by the main window). Its Dock
button (or `set_docked(True)`) moves it into a QDockWidget of the main window – like the other editors it can
then be dragged to any side, tabbed with other docks or floated; `set_docked(False)` makes it a separate
window again. The choice and the dock side are remembered (QSettings <key>/docked, <key>/dock_area).

The docks are *not* part of the saved window layout: a floating dock in a saved layout crashed Qt on Windows
at the next start (DEVELOPMENT.md §2), so `MainWindow.shutdown()` removes them before saving
(`release_docks`) and they are put back when the window is shown again.
"""
from PySide6 import QtCore, QtWidgets

_AREAS = {int(QtCore.Qt.LeftDockWidgetArea.value): QtCore.Qt.LeftDockWidgetArea,
          int(QtCore.Qt.RightDockWidgetArea.value): QtCore.Qt.RightDockWidgetArea,
          int(QtCore.Qt.TopDockWidgetArea.value): QtCore.Qt.TopDockWidgetArea,
          int(QtCore.Qt.BottomDockWidgetArea.value): QtCore.Qt.BottomDockWidgetArea}


def _qs():
    return QtCore.QSettings("QtShell", "QtShell")


class Dockable:
    """Mixin: call `_init_dockable(main_window, key, title, default_area)` in __init__."""

    def _init_dockable(self, mw, key, title, default_area=QtCore.Qt.RightDockWidgetArea):
        self._dk_mw = mw
        self._dk_key = key
        self._dk_title = title
        self._dk_default = default_area
        self._dk_dock = None
        self._dk_window_size = None
        self.docked = str(_qs().value(f"{key}/docked", "false")).lower() == "true"

    # --- dock widget
    def _dock_widget(self):
        if self._dk_dock is None:
            d = QtWidgets.QDockWidget(self._dk_title, self._dk_mw)
            d.setObjectName(f"dock_{self._dk_key}")
            d.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
            d.dockLocationChanged.connect(self._dk_area_changed)
            self._dk_dock = d
            extra = getattr(self._dk_mw, "extra_docks", None)
            if extra is None:
                extra = self._dk_mw.extra_docks = {}
            extra[self._dk_key] = d
        return self._dk_dock

    def _dk_area_changed(self, area):
        try:
            v = int(area.value) if hasattr(area, "value") else int(area)
        except Exception:
            return
        if v in _AREAS:
            _qs().setValue(f"{self._dk_key}/dock_area", v)

    def _dk_area(self):
        try:
            v = int(_qs().value(f"{self._dk_key}/dock_area", 0) or 0)
        except (TypeError, ValueError):
            v = 0
        return _AREAS.get(v, self._dk_default)

    def _dk_attach(self):
        """Puts the widget into its dock (after a start / a release at shutdown)."""
        d = self._dock_widget()
        if d.widget() is not self:
            if self.isWindow():
                self._dk_window_size = self.size()
            d.setWidget(self)
        if self._dk_mw.dockWidgetArea(d) == QtCore.Qt.NoDockWidgetArea and not d.isFloating():
            self._dk_mw.addDockWidget(self._dk_area(), d)
        return d

    def set_docked(self, on):
        """True: in the Qt Shell window (a dock); False: a separate window."""
        on = bool(on)
        was_visible = self.is_shown()
        self.docked = on
        _qs().setValue(f"{self._dk_key}/docked", "true" if on else "false")
        if on:
            d = self._dk_attach()
            if was_visible:
                d.show()
                d.raise_()
                self.show()
        else:
            d = self._dk_dock
            if d is not None and d.widget() is self:
                d.setWidget(QtWidgets.QWidget(d))      # take the widget out of the dock
                d.hide()
                self._dk_mw.removeDockWidget(d)
            self.setParent(self._dk_mw, QtCore.Qt.Window)
            if self._dk_window_size is not None:
                self.resize(self._dk_window_size)
            if was_visible:
                self.show()
                self.raise_()
                self.activateWindow()
        self._dk_sync_button()

    def _dk_sync_button(self):
        b = getattr(self, "dock_btn", None)
        if b is not None and b.isChecked() != self.docked:
            b.blockSignals(True)
            b.setChecked(self.docked)
            b.blockSignals(False)

    # --- showing / hiding
    def is_shown(self):
        if self.docked and self._dk_dock is not None and self._dk_dock.widget() is self:
            return self._dk_dock.isVisible()
        return self.isVisible()

    def present_window(self):
        """Shows it – as a dock or as a window in front of the Qt Shell window."""
        if self.docked:
            d = self._dk_attach()
            d.show()
            d.raise_()
            self.show()
        else:
            if not self.isWindow():
                self.setParent(self._dk_mw, QtCore.Qt.Window)
            self.show()
            self.raise_()
            self.activateWindow()

    def hide_window(self):
        if self.docked and self._dk_dock is not None and self._dk_dock.widget() is self:
            self._dk_dock.hide()
        else:
            QtWidgets.QWidget.close(self)

    def release_dock(self):
        """Shutdown: out of the main window's layout before it is saved."""
        d = self._dk_dock
        if d is None:
            return
        try:
            if d.isFloating():
                d.setFloating(False)
            d.hide()
            self._dk_mw.removeDockWidget(d)
        except RuntimeError:
            pass

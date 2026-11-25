"""A row of controls that may be wider than its dock: shown in a scroll area without scroll bars, the mouse wheel
scrolls it sideways (like the 3D view header). Wide toolbars in bottom docks (Timeline, Video Sequencer, UV editor,
Text editor) otherwise set the dock's – and so the main window's – minimum width, and a maximized window then
grows past the screen edge when docks are shown or hidden."""
from PySide6 import QtCore, QtWidgets


class HScroll(QtWidgets.QScrollArea):
    def __init__(self, content, parent=None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.setWidget(content)
        content.installEventFilter(self)
        self._fit_height()

    def _fit_height(self):
        w = self.widget()
        if w is not None:
            self.setFixedHeight(max(w.sizeHint().height(), w.minimumSizeHint().height()))

    def eventFilter(self, obj, ev):
        if obj is self.widget() and ev.type() == QtCore.QEvent.LayoutRequest:
            QtCore.QTimer.singleShot(0, self, self._fit_height)      # the row's height follows its contents
        return False

    def minimumSizeHint(self):
        return QtCore.QSize(40, self.height())

    def sizeHint(self):
        w = self.widget()
        h = self.height()
        return QtCore.QSize(w.sizeHint().width() if w is not None else 40, h)

    def wheelEvent(self, ev):
        sb = self.horizontalScrollBar()
        if sb.maximum() <= 0:
            return super().wheelEvent(ev)
        d = ev.angleDelta()
        step = d.y() if abs(d.y()) >= abs(d.x()) else d.x()
        sb.setValue(sb.value() - int(step / 2))
        ev.accept()


def wrap(widget, parent=None):
    """The row widget inside an HScroll (returned)."""
    return HScroll(widget, parent)


def wrap_layout(layout, parent=None):
    """A row layout (not installed yet) on its own widget inside an HScroll (returned)."""
    w = QtWidgets.QWidget()
    w.setLayout(layout)
    return HScroll(w, parent)

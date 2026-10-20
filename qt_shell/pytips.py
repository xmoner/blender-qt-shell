"""Python tooltips (like Blender's Preferences → Interface → Python Tooltips).

Widgets and menu actions carry the Python command they run in the Qt property "qtshell_python".
When the option is on (Edit → Qt Preferences… → Interface → Python Tooltips), an application-wide
event filter adds that command to the tooltip:

    Add a cube mesh
    Python: bpy.ops.mesh.primitive_cube_add()

    Location
    Python: bpy.data.objects["Cube"].location

Usage in code:  pytips.tag(widget_or_action, "bpy.ops.object.delete()")
                pytips.tag_op(widget, "mesh.primitive_cube_add", {"size": 2})
                pytips.tag_prop(widget, data, "location", index=-1)
"""
import html

from PySide6 import QtCore, QtGui, QtWidgets

PROP = "qtshell_python"
KEY = "interface/python_tooltips"
_enabled = None
_filter = None


# ---------------------------------------------------------------- setting
def enabled():
    global _enabled
    if _enabled is None:
        _enabled = str(QtCore.QSettings("QtShell", "QtShell").value(KEY, "false")).lower() == "true"
    return _enabled


def set_enabled(on):
    global _enabled
    _enabled = bool(on)
    QtCore.QSettings("QtShell", "QtShell").setValue(KEY, "true" if on else "false")


# ---------------------------------------------------------------- python text
def _value(v):
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, set):
        return "{" + ", ".join(repr(x) for x in sorted(v)) + "}"
    try:
        if hasattr(v, "__len__") and not isinstance(v, (dict, bytes)):
            return "(" + ", ".join(_value(x) for x in v) + ("," if len(v) == 1 else "") + ")"
    except Exception:
        pass
    if isinstance(v, float):
        return f"{v:g}"
    return repr(v)


def op_text(idname, props=None):
    """bpy.ops.<module>.<name>(prop=value, …)"""
    args = ", ".join(f"{k}={_value(v)}" for k, v in (props or {}).items() if not isinstance(v, dict))
    return f"bpy.ops.{idname}({args})"


def data_path(data):
    """Python path of an RNA struct, e.g. bpy.data.objects["Cube"].modifiers["Subdivision"]."""
    try:
        r = repr(data)
        if r.startswith("bpy."):
            return r.replace("'", '"')
    except Exception:
        pass
    try:
        idd = data.id_data
        base = repr(idd).replace("'", '"') if idd is not None else ""
        sub = data.path_from_id()
        if base.startswith("bpy."):
            return f"{base}.{sub}" if sub else base
    except Exception:
        pass
    try:
        return f"bpy.types.{data.bl_rna.identifier}"
    except Exception:
        return "…"


def prop_text(data, prop, index=-1):
    t = f"{data_path(data)}.{prop}"
    if index is not None and index >= 0:
        t += f"[{index}]"
    return t


# ---------------------------------------------------------------- tagging
def tag(obj, text):
    """Store the Python command on a widget or QAction (no-op for None)."""
    if obj is None or not text:
        return obj
    try:
        obj.setProperty(PROP, text)
    except RuntimeError:
        pass
    return obj


def tag_op(obj, idname, props=None):
    return tag(obj, op_text(idname, props))


def tag_prop(obj, data, prop, index=-1):
    try:
        return tag(obj, prop_text(data, prop, index))
    except Exception:
        return obj


def _get(obj):
    try:
        v = obj.property(PROP)
    except RuntimeError:
        return None
    return v if isinstance(v, str) and v else None


# ---------------------------------------------------------------- tooltip filter
def _rich(text):
    try:
        return bool(QtGui.Qt.mightBeRichText(text))
    except Exception:
        return text.lstrip().startswith("<")


def _compose(tip, py):
    tip = tip or ""
    if tip and _rich(tip):
        body = tip
    else:
        body = html.escape(tip).replace("\n", "<br>")
    code = html.escape(py).replace("\n", "<br>")
    sep = "<br>" if body else ""
    return (f"<div style='white-space:pre-wrap'>{body}{sep}"
            f"<b>Python:</b> "
            f"<span style=\"font-family:Consolas,'DejaVu Sans Mono',monospace\">{code}</span></div>")


def handle(obj, ev):
    """Called by app._notify_with_context for QEvent.ToolTip when the option is on.
    Returns True when it showed the tooltip (the event is then consumed).

    No application-wide event filter on purpose: a Python eventFilter on the QApplication sees every
    event, and stale PySide wrappers of events once made notify() receive a QMoveEvent as the receiver
    (2026-10-20). The existing notify() override already runs for every event anyway."""
    try:
        if isinstance(obj, QtWidgets.QMenu):
            act = obj.actionAt(ev.pos())
            py = _get(act) if act is not None else None
            if py is None:
                return False
            tip = act.toolTip()
            if tip == act.text().replace("&", ""):
                tip = ""                       # Qt's default tooltip of an action is its text
            QtWidgets.QToolTip.showText(ev.globalPos(), _compose(tip, py), obj, obj.actionGeometry(act))
            return True
        if not isinstance(obj, QtWidgets.QWidget):
            return False
        # the command may sit on the widget or on a parent (e.g. a field inside a vector row)
        w, py, depth = obj, None, 0
        while w is not None and depth < 4:
            py = _get(w)
            if py or w.isWindow():
                break
            w, depth = w.parentWidget(), depth + 1
        if not py:
            return False
        tip = obj.toolTip() or (w.toolTip() if w is not None else "")
        QtWidgets.QToolTip.showText(ev.globalPos(), _compose(tip, py), obj)
        return True
    except Exception as ex:                    # never keep the event alive in a traceback
        msg = f"{type(ex).__name__}: {ex}"
    from . import bridge
    bridge.log("Python tooltip: " + msg, "WARNING")
    return False


def install(app=None):
    """Removes the application event filter of the first version (tooltips now go through app.notify)."""
    app = app or QtWidgets.QApplication.instance()
    if app is None:
        return
    old = getattr(app, "_qtshell_pytips_filter", None)
    if old is not None:
        try:
            app.removeEventFilter(old)
        except RuntimeError:
            pass
        app._qtshell_pytips_filter = None

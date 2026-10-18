"""Qt Shell API demo – run it in Blender (Text Editor ▸ Run Script, or the Qt Shell console:
exec(open(r"path/to/api_demo.py").read())).

It adds:
- a dock "API Demo" with the active object and buttons that control the 3D view,
- a menu "Tools" with "Say Hello" (Ctrl+Alt+H),
- an overlay that writes object names next to the objects in the viewport,
- an event handler that updates the dock when the selection changes.

Run remove_demo() to take everything away again.
"""
import bpy
import qt_shell.api as qs

_state = {"label": None}


def _update_label(*_args):
    lab = _state["label"]
    if lab is None:
        return
    ob = bpy.context.view_layer.objects.active
    try:
        lab.setText(f"Active object: {ob.name if ob else '—'}\n"
                    f"Selected: {len(bpy.context.selected_objects)}\n"
                    f"Frame: {bpy.context.scene.frame_current}")
    except RuntimeError:            # the widget was deleted (window rebuilt) – the factory makes a new one
        _state["label"] = None


def make_dock():
    # PySide6 is only imported here – the factory runs when the Qt window is built
    from PySide6 import QtWidgets

    w = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(w)
    label = QtWidgets.QLabel()
    lay.addWidget(label)
    _state["label"] = label
    _update_label()

    def button(text, fn):
        b = QtWidgets.QPushButton(text)
        b.clicked.connect(fn)
        lay.addWidget(b)

    button("Top view", lambda: qs.set_view("TOP"))
    button("Front view", lambda: qs.set_view("FRONT"))
    button("Orbit 45°", lambda: qs.set_view(yaw=qs.get_view()["yaw"] + 0.785))
    button("Frame all", qs.frame_all)
    lay.addStretch(1)
    return w


def draw_names(painter, ctx):
    from PySide6 import QtCore, QtGui
    painter.setPen(QtGui.QColor("#ffcc33"))
    font = painter.font()
    font.setPixelSize(13)
    font.setBold(True)
    painter.setFont(font)
    for ob in bpy.context.visible_objects:
        p = ctx.project(ob.matrix_world.translation)
        if p is not None:
            painter.drawText(p + QtCore.QPointF(8, -8), ob.name)


def add_demo():
    qs.add_dock("api_demo", "API Demo", make_dock, area="left")
    qs.add_menu_action("Tools", "Say Hello", lambda: qs.status("Hello from qt_shell.api!"),
                       shortcut="Ctrl+Alt+H", action_id="demo_hello")
    qs.add_menu_action("Object", "Print Active Object",
                       lambda: print("Active:", bpy.context.view_layer.objects.active),
                       action_id="demo_print")
    qs.add_overlay("demo_names", draw_names)
    _state["handlers"] = [qs.on("selection", _update_label), qs.on("frame", _update_label)]


def remove_demo():
    qs.remove_dock("api_demo")
    qs.remove_menu_action("demo_hello")
    qs.remove_menu_action("demo_print")
    qs.remove_overlay("demo_names")
    for h in _state.get("handlers", []):
        qs.off(h)
    _state["handlers"] = []


add_demo()

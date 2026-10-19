"""A button floating over the 3D viewport (Qt Shell).

Open it in the Qt Shell Text editor and press Alt+P (Run Script). A "+ Cube" button appears in the
top-left corner of every visible 3D view; clicking it adds a cube at the 3D cursor.
■ Unload in the Text editor removes the button again.
"""
import bpy
import qt_shell.api as qs

_buttons = []          # the Qt buttons we created (to remove them again)


def add_cube():
    """What the button does – runs inside Blender, bpy and bpy.ops work here."""
    bpy.ops.mesh.primitive_cube_add(location=bpy.context.scene.cursor.location)
    qs.status("Cube added")


def _make_buttons(*_args):
    _remove_buttons()
    from PySide6 import QtWidgets
    for vp in qs.viewports():                          # every visible 3D view
        b = QtWidgets.QPushButton("+ Cube", vp)        # parent = the viewport -> it floats over it
        b.setToolTip("Add a cube at the 3D cursor")
        b.clicked.connect(add_cube)
        b.move(10, 50)                                 # x, y from the top-left corner of the view
        b.show()
        _buttons.append(b)


def _remove_buttons():
    for b in _buttons:
        try:
            b.deleteLater()
        except RuntimeError:                           # already deleted with its viewport
            pass
    _buttons.clear()


def register():
    _make_buttons()
    qs.on("window", _make_buttons)    # the Qt window was rebuilt (Interface Size…) -> add them again


def unregister():
    _remove_buttons()


if __name__ == "__main__":
    register()

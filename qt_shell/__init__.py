bl_info = {
    "name": "Qt Shell – rozhraní Blenderu v PySide6",
    "author": "Lukas Bilek",
    "version": (0, 3, 0),
    "blender": (4, 2, 0),
    "location": "F3 → Open Qt Shell / Preferences → Add-ons → Qt Shell",
    "description": "Nahradí rozhraní Blenderu oknem v Qt (PySide6): viewport, outliner, "
                   "vlastnosti, menu, timeline, konzole",
    "category": "Interface",
    "doc_url": "https://github.com/xmoner/blender-qt-shell",
}

import os
import sys
import subprocess
import traceback

import bpy

from . import bridge


def _pyside_available():
    try:
        import PySide6  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- preferences
class QTSHELL_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    auto_start: bpy.props.BoolProperty(
        name="Spouštět Qt Shell při startu Blenderu", default=False)
    hide_blender: bpy.props.BoolProperty(
        name="Skrýt okno Blenderu, když běží Qt Shell", default=True)
    viewport_scale: bpy.props.FloatProperty(
        name="Rozlišení viewportu", default=1.0, min=0.25, max=2.0,
        description="Násobek rozlišení renderu viewportu (nižší = rychlejší)")

    def draw(self, context):
        col = self.layout.column()
        if _pyside_available():
            import PySide6
            col.label(text=f"PySide6 {PySide6.__version__} je nainstalované.", icon="CHECKMARK")
        else:
            col.label(text="PySide6 není nainstalované.", icon="ERROR")
            col.operator("qtshell.install_pyside", icon="IMPORT")
        col.separator()
        col.prop(self, "auto_start")
        col.prop(self, "hide_blender")
        col.prop(self, "viewport_scale")
        col.separator()
        col.operator("qtshell.open", icon="WINDOW")


def prefs():
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except Exception:
        return None


# ---------------------------------------------------------------- operátory
class QTSHELL_OT_install_pyside(bpy.types.Operator):
    bl_idname = "qtshell.install_pyside"
    bl_label = "Nainstalovat PySide6"
    bl_description = ("Stáhne PySide6 přes pip do uživatelské složky skriptů Blenderu "
                      "(~150–250 MB, chvíli to trvá a Blender mezitím nereaguje)")

    def execute(self, context):
        target = bridge.user_modules_dir()
        py = sys.executable
        try:
            subprocess.run([py, "-m", "ensurepip", "--upgrade"], check=False)
            res = subprocess.run(
                [py, "-m", "pip", "install", "--upgrade", "--target", target, "PySide6-Essentials"],
                capture_output=True, text=True)
            print(res.stdout)
            print(res.stderr)
            if res.returncode != 0:
                self.report({"ERROR"}, "pip selhal – podrobnosti v systémové konzoli.")
                return {"CANCELLED"}
        except Exception as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        if target not in sys.path:
            sys.path.append(target)
        self.report({"INFO"}, f"PySide6 nainstalováno do {target}")
        return {"FINISHED"}


class QTSHELL_OT_open(bpy.types.Operator):
    bl_idname = "qtshell.open"
    bl_label = "Open Qt Shell"
    bl_description = "Otevře rozhraní Blenderu v Qt (PySide6)"

    def execute(self, context):
        if not _pyside_available():
            self.report({"ERROR"}, "Chybí PySide6 – nainstaluj ho v Preferences → Add-ons → Qt Shell.")
            return {"CANCELLED"}
        try:
            from . import app
            app.start(prefs())
        except Exception:
            traceback.print_exc()
            self.report({"ERROR"}, "Qt Shell se nepodařilo spustit – viz systémová konzole.")
            return {"CANCELLED"}
        return {"FINISHED"}


class QTSHELL_OT_close(bpy.types.Operator):
    bl_idname = "qtshell.close"
    bl_label = "Close Qt Shell"
    bl_description = "Zavře Qt okno a vrátí původní rozhraní Blenderu"

    def execute(self, context):
        try:
            from . import app
            app.stop()
        except Exception:
            traceback.print_exc()
        return {"FINISHED"}


def _menu_entry(self, context):
    self.layout.separator()
    self.layout.operator("qtshell.open", icon="WINDOW")


def _auto_start():
    p = prefs()
    if p and p.auto_start and _pyside_available() and not bpy.app.background:
        try:
            from . import app
            app.start(p)
        except Exception:
            traceback.print_exc()
    return None


classes = (QTSHELL_Preferences, QTSHELL_OT_install_pyside, QTSHELL_OT_open, QTSHELL_OT_close)


def register():
    target = os.path.join(bpy.utils.user_resource("SCRIPTS"), "modules")
    if os.path.isdir(target) and target not in sys.path:
        sys.path.append(target)
    for c in classes:
        bpy.utils.register_class(c)
    bridge.register_handlers()
    bpy.types.TOPBAR_MT_window.append(_menu_entry)
    if not bpy.app.background:
        bpy.app.timers.register(_auto_start, first_interval=1.0)


def unregister():
    try:
        from . import app
        app.stop()
    except Exception:
        pass
    bpy.types.TOPBAR_MT_window.remove(_menu_entry)
    bridge.unregister_handlers()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

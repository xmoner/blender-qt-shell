"""Vývojářský reload: zavře Qt Shell, znovu načte moduly addonu a otevře ho."""
import importlib
import sys

ORDER = ["bridge", "native", "theme", "fake_ui", "rna_widgets", "qt_ui", "editmesh", "viewport",
         "outliner", "properties", "timeline", "console", "node_editor", "uv_editor", "main_window", "app"]


def go(delay=0.3):
    from . import bridge

    def run():
        pkg = sys.modules[__package__]
        app = sys.modules.get(__package__ + ".app")
        if app is not None:
            app.stop(show_blender=False)
            import bpy
            try:
                if bpy.app.timers.is_registered(app._pump):
                    bpy.app.timers.unregister(app._pump)
            except Exception:
                pass
            app._pump_on = False
        sys.modules[__package__ + ".bridge"].unregister_handlers()
        for name in ORDER:
            full = f"{__package__}.{name}"
            if full in sys.modules:
                importlib.reload(sys.modules[full])
            else:
                importlib.import_module(full)
        new_bridge = sys.modules[__package__ + ".bridge"]
        new_bridge.register_handlers()
        pkg.bridge = new_bridge
        sys.modules[__package__ + ".app"].start(pkg.prefs())
    bridge.later(run, delay)

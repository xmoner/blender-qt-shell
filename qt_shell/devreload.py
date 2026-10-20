"""Developer reload: closes Qt Shell, reloads the add-on modules and opens it again."""
import importlib
import sys

ORDER = ["bridge", "native", "theme", "fake_ui", "rna_widgets", "qt_ui", "editmesh", "viewport",
         "outliner", "properties", "sidebar", "timeline", "console", "node_editor", "uv_editor", "api",
         "scripts", "text_editor", "scripts_dock", "main_window", "app"]


def go(delay=0.3):
    from . import bridge

    def run():
        try:
            _run()
        except Exception:
            import traceback
            b = sys.modules.get(__package__ + ".bridge")
            if b is not None:
                b.log("Reload failed:\n" + traceback.format_exc(), "ERROR")
            try:
                from . import native
                native.set_blender_windows_visible(True, [])
            except Exception:
                pass

    def _run():
        pkg = sys.modules[__package__]
        app = sys.modules.get(__package__ + ".app")
        if app is not None and getattr(app, "_hub", None) is not None:
            app._hub.playing = False      # stop playback before tearing the window down
        if app is not None:
            app.stop(show_blender=False)
            # Blender's event pump (processEvents) never handles deleteLater → the old window would stay
            # alive (hidden) next to the new one, and showing the new window after a reload crashed
            # (access violation in show(), 2026-10-20). Delete it now.
            try:
                from PySide6 import QtCore
                QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
            except Exception:
                pass
            import bpy
            try:
                if bpy.app.timers.is_registered(app._pump):
                    bpy.app.timers.unregister(app._pump)
            except Exception:
                pass
            app._pump_on = False
        sys.modules[__package__ + ".bridge"].unregister_handlers()
        # also any other loaded module of the add-on (new modules, or ones missing from ORDER)
        loaded = [k[len(__package__) + 1:] for k in list(sys.modules)
                  if k.startswith(__package__ + ".") and k.count(".") == __package__.count(".") + 1]
        extra = [m for m in loaded if m not in ORDER and m != "devreload"]
        order = ORDER[:ORDER.index("main_window")] + extra + ORDER[ORDER.index("main_window"):]
        for name in order:
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

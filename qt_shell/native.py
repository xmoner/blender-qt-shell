"""Skrývání / zobrazování nativních oken Blenderu (Windows, macOS, Linux/X11).

Blender si okna vytváří přes vlastní vrstvu GHOST, Python API je skrýt neumí.
Proto se tu sahá přímo na API operačního systému přes ctypes.
"""
import os
import sys
import ctypes
import shutil
import subprocess


def set_blender_windows_visible(visible, exclude_ids=()):
    """Vrátí (ok, zpráva)."""
    try:
        if sys.platform == "win32":
            return _windows(visible)
        if sys.platform == "darwin":
            return _macos(visible)
        return _x11(visible, set(int(i) for i in exclude_ids))
    except Exception as ex:  # nikdy nesmí shodit Blender
        return False, f"{type(ex).__name__}: {ex}"


# --------------------------------------------------------------------------- Windows
def _windows(visible):
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]

    pid = os.getpid()
    found = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == "GHOST_WindowClass":
                found.append(hwnd)
        return True

    cb = proc_type(callback)  # reference musí žít po dobu EnumWindows
    user32.EnumWindows(cb, 0)
    for hwnd in found:
        user32.ShowWindow(hwnd, 5 if visible else 0)  # SW_SHOW / SW_HIDE
        if visible:
            user32.SetForegroundWindow(hwnd)
    return bool(found), f"oken Blenderu: {len(found)}"


# --------------------------------------------------------------------------- macOS
def _macos(visible):
    import ctypes.util

    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.object_getClassName.restype = ctypes.c_char_p
    objc.object_getClassName.argtypes = [ctypes.c_void_p]
    msg_send = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value

    def send(obj, sel, restype=ctypes.c_void_p, argtypes=(), *args):
        fn = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(msg_send)
        return fn(obj, objc.sel_registerName(sel), *args)

    ns_app = send(objc.objc_getClass(b"NSApplication"), b"sharedApplication")
    windows = send(ns_app, b"windows")
    count = send(windows, b"count", ctypes.c_ulong)
    changed = 0
    for i in range(count):
        win = send(windows, b"objectAtIndex:", ctypes.c_void_p, (ctypes.c_ulong,), i)
        name = objc.object_getClassName(win) or b""
        if name.startswith(b"QNS") or b"Qt" in name:
            continue  # okna Qt necháme být
        if b"Blender" not in name and b"Cocoa" not in name:
            continue
        sel = b"makeKeyAndOrderFront:" if visible else b"orderOut:"
        send(win, sel, ctypes.c_void_p, (ctypes.c_void_p,), None)
        changed += 1
    return bool(changed), f"oken Blenderu: {changed}"


# --------------------------------------------------------------------------- Linux / X11
def _x11(visible, exclude):
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        return False, "Pod čistým Waylandem nejde okno Blenderu skrýt (spusť Blender přes X11/XWayland)."
    xdotool = shutil.which("xdotool")
    if not xdotool:
        return False, "Pro skrytí okna Blenderu nainstaluj 'xdotool' (např. sudo apt install xdotool)."
    out = subprocess.run([xdotool, "search", "--pid", str(os.getpid())],
                         capture_output=True, text=True, timeout=3).stdout.split()
    changed = 0
    for wid in out:
        try:
            wid_i = int(wid)
        except ValueError:
            continue
        if wid_i in exclude:
            continue
        title = subprocess.run([xdotool, "getwindowname", wid], capture_output=True,
                               text=True, timeout=3).stdout
        if "Blender" not in title:
            continue
        subprocess.run([xdotool, "windowmap" if visible else "windowunmap", wid], timeout=3)
        changed += 1
    return bool(changed), f"oken Blenderu: {changed}"

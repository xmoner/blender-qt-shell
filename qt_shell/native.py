"""Hiding / showing Blender's native windows (Windows, macOS, Linux/X11).

Blender creates its windows through its own GHOST layer and the Python API cannot hide them,
so this module calls the operating system API directly through ctypes.
"""
import os
import sys
import ctypes
import shutil
import subprocess


def set_blender_windows_visible(visible, exclude_ids=()):
    """Returns (ok, message)."""
    try:
        if sys.platform == "win32":
            return _windows(visible)
        if sys.platform == "darwin":
            return _macos(visible)
        return _x11(visible, set(int(i) for i in exclude_ids))
    except Exception as ex:  # must never crash Blender
        return False, f"{type(ex).__name__}: {ex}"


# --------------------------------------------------------------------------- Windows
def _windows(visible):
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]

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

    cb = proc_type(callback)  # the reference must stay alive during EnumWindows
    user32.EnumWindows(cb, 0)
    for hwnd in found:
        if visible:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)   # SW_RESTORE (back to normal / maximized)
            user32.ShowWindow(hwnd, 5)       # SW_SHOW
            user32.SetForegroundWindow(hwnd)
        elif not user32.IsWindowVisible(hwnd) and user32.IsIconic(hwnd):
            continue                         # hidden already (hiding again would activate another window)
        else:
            # Minimize before hiding: Blender skips drawing minimized windows. A window that is only
            # hidden is still redrawn on every change and waits for VSync – that capped playback at 60 fps.
            user32.ShowWindow(hwnd, 6)       # SW_MINIMIZE
            user32.ShowWindow(hwnd, 0)       # SW_HIDE
    global _ghost_hwnds
    _ghost_hwnds = list(found)
    return bool(found), f"Blender windows: {len(found)}"


_ghost_hwnds = []


def ghost_windows():
    """Blender's native windows of this process (Windows; [] elsewhere)."""
    if sys.platform != "win32":
        return []
    from ctypes import wintypes
    user32 = ctypes.windll.user32
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
                found.append(int(hwnd or 0))
        return True

    try:
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        cb = proc_type(callback)
        user32.EnumWindows(cb, 0)
    except Exception:
        return []
    return found


def hide_windows(hwnds):
    """Hides windows without minimizing them – Blender still draws a hidden (not minimized) window, so its
    editors stay up to date (the render helper's Image Editor)."""
    global _ghost_hwnds
    if sys.platform != "win32":
        return
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    for h in hwnds:
        try:
            user32.ShowWindow(h, 0)          # SW_HIDE
        except Exception:
            pass
    _ghost_hwnds = ghost_windows()


def repaint_blender_windows():
    """Posts WM_PAINT to Blender's (hidden) windows (Windows). Blender handles it as a GHOST WindowUpdate
    and makes that window drawable – its GPU context active again after another window was closed."""
    if sys.platform != "win32" or not _ghost_hwnds:
        return False
    try:
        for h in _ghost_hwnds:
            ctypes.windll.user32.PostMessageW(ctypes.c_void_p(h), 0x000F, 0, 0)    # WM_PAINT
        return True
    except Exception:
        return False


def wake_event_loop():
    """Makes Blender's event loop skip its idle sleep (~5 ms) on the next pass (Windows).

    Blender sleeps when its window got no message; during fast playback that sleep is longer than
    the time left until the next frame. Posting an empty message (WM_NULL) wakes it up."""
    if sys.platform != "win32" or not _ghost_hwnds:
        return
    try:
        ctypes.windll.user32.PostMessageW(ctypes.c_void_p(_ghost_hwnds[0]), 0, 0, 0)
    except Exception:
        pass


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
            continue  # leave Qt windows alone
        if b"Blender" not in name and b"Cocoa" not in name:
            continue
        sel = b"makeKeyAndOrderFront:" if visible else b"orderOut:"
        send(win, sel, ctypes.c_void_p, (ctypes.c_void_p,), None)
        changed += 1
    return bool(changed), f"Blender windows: {changed}"


# --------------------------------------------------------------------------- Linux / X11
def _x11(visible, exclude):
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        return False, "The Blender window cannot be hidden under pure Wayland (run Blender via X11/XWayland)."
    xdotool = shutil.which("xdotool")
    if not xdotool:
        return False, "Install 'xdotool' to hide the Blender window (e.g. sudo apt install xdotool)."
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
    return bool(changed), f"Blender windows: {changed}"

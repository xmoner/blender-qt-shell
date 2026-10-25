"""Repeat Last (Maya's G, Blender's Shift+R): runs the last action again.
Repeat Last Command (Shift+G in the Maya set): the same, but skips Move / Rotate / Scale.

Recorded actions: an interactive Move / Rotate / Scale in the 3D view (the same offset / angle / factor
again, around the current pivot), Blender operators run from Qt Shell's menus, headers, shortcuts and
tools (bridge.run_op – not view, selection, file or UI operators), and shelf buttons.
"""

_last = None          # (label, fn)
_last_cmd = None      # the same without the interactive Move / Rotate / Scale (Shift+G)
_suspend = 0          # > 0 while a recorded action runs its own operators (a shelf button's code)

# operators that are not "commands" worth repeating (navigation, selection, UI, files …)
_SKIP_PREFIXES = ("wm.", "screen.", "ed.", "view3d.", "view2d.", "image.", "file.", "outliner.", "ui.",
                  "text.", "console.", "buttons.", "info.", "preferences.", "script.", "render.",
                  "transform.", "sequencer.view", "graph.view", "action.view", "node.view")
_SKIP_WORDS = ("select", "mode_set", "editmode_toggle", "posemode_toggle", "hide", "reveal", "change_frame",
               "frame_jump", "keyframe_jump", "undo", "redo")


def repeatable_op(idname):
    if idname.startswith(_SKIP_PREFIXES):
        return False
    name = idname.split(".", 1)[-1]
    return not any(w in name for w in _SKIP_WORDS)


def record(label, fn, force=False, transform=False):
    """Remembers fn (no arguments) as the action Repeat Last runs. transform=True: an interactive
    Move / Rotate / Scale – Repeat Last Command (Shift+G) skips those."""
    global _last, _last_cmd
    if _suspend and not force:
        return
    _last = (label, fn)
    if not transform:
        _last_cmd = (label, fn)


class suspended:
    """with repeat.suspended(): … – operators run inside are not recorded (the caller records itself)."""

    def __enter__(self):
        global _suspend
        _suspend += 1

    def __exit__(self, *exc):
        global _suspend
        _suspend -= 1
        return False


def record_op(idname, props=None, invoke=False):
    if not repeatable_op(idname):
        return
    props = dict(props or {})

    def again():
        from . import bridge
        return bridge.run_op(idname, dict(props), invoke=invoke)
    try:
        from . import bridge
        label = bridge.op_label(idname) or idname
    except Exception:
        label = idname
    record(label, again)


def last_label(commands_only=False):
    e = _last_cmd if commands_only else _last
    return e[0] if e else None


def repeat(commands_only=False):
    """Runs the last recorded action (commands_only: the last one that isn't a Move / Rotate / Scale).
    Returns its label (None when there is nothing to repeat)."""
    from . import api, bridge
    entry = _last_cmd if commands_only else _last
    if entry is None:
        api.status("Repeat Last: nothing to repeat yet.")
        return None
    label, fn = entry
    try:
        fn()
    except Exception:
        import traceback
        bridge.log(f"Repeat Last ({label}):\n{traceback.format_exc()}", "ERROR")
        api.status(f"Repeat Last: '{label}' failed – see the log.")
        return None
    api.status(f"Repeat Last: {label}")
    return label

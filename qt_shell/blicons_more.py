"""The rest of Blender 5.2's icon names for blicons.py – families drawn by code (keys, colour sets, node
sockets, interpolation curves, mouse buttons…) and the remaining editors, modes, file-browser and misc icons."""
import colorsys
import math


def _hsl(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l, s)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))

# Blender-like colour tags (collections, layer groups, strips)
TAGS = ["#e96a6a", "#f0a050", "#e8d35a", "#7cc36a", "#5aa0e8", "#a07ae0", "#e07ab8", "#a07850", "#8a8a8a"]


def extend(add, _I, _s, W, OB, DA, MO, LI, RD):
    def has(n):
        return n in _I

    def put(names, body):
        for n in names.split():
            if not has(n):
                add(n, body)

    def txt(t, size, y=8.6, c=W, weight="bold"):
        """Centred text; y is the visual centre (Qt's SVG Tiny has no dominant-baseline → baseline computed)."""
        t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        base = y + size * 0.36
        return (f'<text x="8" y="{base:.2f}" font-family="Segoe UI, DejaVu Sans, Arial, sans-serif" '
                f'font-size="{size}" font-weight="{weight}" fill="{c}" text-anchor="middle">{t}</text>')

    def keycap(label, filled=False, wide=1.0):
        w = 13 * wide
        x = 8 - w / 2
        n = len(label)
        size = 9 if n <= 1 else 7 if n == 2 else 5.4 if n == 3 else 4.4
        if filled:
            return (f'<rect x="{x:.1f}" y="2" width="{w:.1f}" height="12" rx="2.4" fill="{W}"/>'
                    + txt(label, size, c="#262626"))
        return f'<rect x="{x:.1f}" y="2" width="{w:.1f}" height="12" rx="2.4" {_s()}/>' + txt(label, size)

    # ---------------------------------------------------------------- keyboard events
    special = {"SHIFT": "⇧", "CTRL": "Ctrl", "ALT": "Alt", "OS": "⊞", "HYPER": "Hyp", "ESC": "Esc", "TAB": "Tab",
               "PAGEUP": "PgUp", "PAGEDOWN": "PgDn", "RETURN": "↵", "SPACEKEY": "␣", "PADASTER": "*",
               "PADSLASH": "/", "PADMINUS": "−", "PADENTER": "↵", "PADPLUS": "+", "PADPERIOD": ".",
               "TABLET_STYLUS": "✎", "TABLET_ERASER": "⌫", "LEFT_ARROW": "←", "DOWN_ARROW": "↓",
               "RIGHT_ARROW": "→", "UP_ARROW": "↑", "PAUSE": "Pau", "INSERT": "Ins", "HOME": "Home", "END": "End",
               "UNKNOWN": "?", "GRLESS": "<", "MEDIAPLAY": "▶", "MEDIASTOP": "■", "MEDIAFIRST": "⏮",
               "MEDIALAST": "⏭", "APP": "≣", "CAPSLOCK": "Caps", "BACKSPACE": "⌫", "DEL": "Del", "SEMICOLON": ";",
               "PERIOD": ".", "COMMA": ",", "QUOTE": "'", "ACCENTGRAVE": "`", "MINUS": "−", "PLUS": "+",
               "SLASH": "/", "BACKSLASH": "\\", "EQUAL": "=", "LEFTBRACKET": "[", "RIGHTBRACKET": "]",
               "PAD_PAN": "Pan", "PAD_ROTATE": "Rot", "PAD_ZOOM": "Zm"}
    nums = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"]
    for i, n in enumerate(nums):
        special[f"{n}KEY"] = str(i)
        special[f"PAD{i}"] = f"n{i}"
    for k in range(4, 8):
        special[f"MOUSE_{k}"] = f"M{k}"
    for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        special[c] = c
    for f in range(1, 25):
        special[f"F{f}"] = f"F{f}"
    for key, lab in special.items():
        put(f"EVENT_{key}", keycap(lab, wide=1.0 if len(lab) <= 2 else 1.0))
    ndof = {"MENU": "≣", "FIT": "Fit", "TOP": "Top", "BOTTOM": "Bot", "LEFT": "L", "RIGHT": "R", "FRONT": "Fr",
            "BACK": "Bk", "ISO1": "Is1", "ISO2": "Is2", "ROLL_CW": "↻", "ROLL_CCW": "↺", "SPIN_CW": "↻",
            "SPIN_CCW": "↺", "TILT_CW": "↻", "TILT_CCW": "↺", "ROTATE": "Rot", "PANZOOM": "Pz", "DOMINANT": "Dom",
            "PLUS": "+", "MINUS": "−", "V1": "V1", "V2": "V2", "V3": "V3", "SAVE_V1": "S1", "SAVE_V2": "S2",
            "SAVE_V3": "S3"}
    for i in range(1, 13):
        ndof[str(i)] = str(i)
    for key, lab in ndof.items():
        put(f"EVENT_NDOF_BUTTON_{key}", keycap(lab, filled=True))

    keys = {"BACKSPACE": "⌫", "COMMAND": "⌘", "CONTROL": "^", "EMPTY1": "", "EMPTY2": "", "EMPTY3": "",
            "MENU": "≣", "OPTION": "⌥", "RETURN": "↵", "RING": "○", "SHIFT": "⇧", "TAB": "⇥", "WINDOWS": "⊞"}
    widths = {"EMPTY2": 0.8, "EMPTY3": 0.6}
    for key, lab in keys.items():
        put(f"KEY_{key}", keycap(lab, wide=widths.get(key, 1.0)))
        put(f"KEY_{key}_FILLED", keycap(lab, filled=True, wide=widths.get(key, 1.0)))

    # ---------------------------------------------------------------- colour tags & sets
    for i, col in enumerate(TAGS[:8]):
        put(f"COLLECTION_COLOR_{i + 1:02d}", f'<rect x="2" y="3" width="12" height="10" rx="1.5" fill="none" '
            f'stroke="{col}" stroke-width="1.4"/><path d="M2 6 H14" stroke="{col}" stroke-width="1.4"/>')
        put(f"LAYERGROUP_COLOR_{i + 1:02d}", f'<path d="M1.5 4 H6 L7.5 5.5 H14.5 V13 H1.5 Z" fill="{col}" '
            f'fill-opacity=".85"/>')
    for i, col in enumerate(TAGS):
        put(f"STRIP_COLOR_{i + 1:02d}", f'<rect x="2" y="4" width="12" height="8" rx="1.5" fill="{col}"/>')
    hues = [0, 25, 50, 95, 140, 175, 200, 225, 260, 290, 320, 345, 15, 70, 120, 190, 240, 280, 310, 30]
    for i, h in enumerate(hues):
        a = _hsl(h, .70, .55)
        b = _hsl((h + 25) % 360, .65, .40)
        c = _hsl(h, .40, .80)
        put(f"COLORSET_{i + 1:02d}_VEC", f'<rect x="2" y="2" width="4" height="12" fill="{a}"/>'
            f'<rect x="6" y="2" width="4" height="12" fill="{b}"/><rect x="10" y="2" width="4" height="12" fill="{c}"/>')
    for name, col in (("RED", "#e85a5a"), ("GREEN", "#6cc35a"), ("BLUE", "#5a8ee8")):
        put(f"COLOR_{name} RGB_{name}", f'<circle cx="8" cy="8" r="5.5" fill="{col}"/>')
    put("COLOR", '<circle cx="5.5" cy="6" r="3.4" fill="#e85a5a" fill-opacity=".85"/>'
        '<circle cx="10.5" cy="6" r="3.4" fill="#6cc35a" fill-opacity=".85"/>'
        '<circle cx="8" cy="10.5" r="3.4" fill="#5a8ee8" fill-opacity=".85"/>')

    # ---------------------------------------------------------------- node sockets
    sock = {"FLOAT": "#a1a1a1", "VECTOR": "#6363c7", "RGBA": "#c7c729", "SHADER": "#63c763", "BOOLEAN": "#cca6d6",
            "INT": "#598c5c", "STRING": "#70b2ff", "OBJECT": "#ed9e5c", "IMAGE": "#633863", "GEOMETRY": "#00d6a3",
            "COLLECTION": "#f5f5f5", "TEXTURE": "#9e4fa3", "MATERIAL": "#eb7582", "ROTATION": "#a663c7",
            "MENU": "#4d4d4d", "MATRIX": "#405780", "BUNDLE": "#4d8099", "CLOSURE": "#ad7a3d", "FONT": "#8f8f5c",
            "SCENE": "#c7c7c7", "TEXT": "#5c99a3", "MASK": "#7a7a7a", "SOUND": "#8f6b8f", "INT_VECTOR": "#4f8a5a"}
    for k, col in sock.items():
        if k in ("MATRIX", "BUNDLE", "CLOSURE"):
            shape = f'<path d="M8 2.5 L13.5 8 L8 13.5 L2.5 8 Z" fill="{col}" stroke="#1a1a1a" stroke-width=".8"/>'
        else:
            shape = f'<circle cx="8" cy="8" r="5" fill="{col}" stroke="#1a1a1a" stroke-width=".8"/>'
        put(f"NODE_SOCKET_{k}", shape)

    # ---------------------------------------------------------------- interpolation & falloff curves
    def plot(fn, c=W, steps=40):
        pts = []
        for i in range(steps + 1):
            t = i / steps
            v = fn(t)
            pts.append(f"{2 + t * 12:.2f},{14 - v * 12:.2f}")
        return f'<path {_s(c, 1.3)} d="M{" L".join(pts)}"/>'

    def ease_in(p):
        return lambda t: t ** p

    def ease_out(p):
        return lambda t: 1 - (1 - t) ** p

    def bounce(t):
        n, d = 7.5625, 2.75
        if t < 1 / d:
            return n * t * t
        if t < 2 / d:
            t -= 1.5 / d
            return n * t * t + .75
        if t < 2.5 / d:
            t -= 2.25 / d
            return n * t * t + .9375
        t -= 2.625 / d
        return n * t * t + .984375
    ipo = {"LINEAR": lambda t: t, "CONSTANT": lambda t: 0 if t < .999 else 1,
           "BEZIER": lambda t: t * t * (3 - 2 * t), "QUAD": ease_in(2), "CUBIC": ease_in(3), "QUART": ease_in(4),
           "QUINT": ease_in(5), "SINE": lambda t: 1 - math.cos(t * math.pi / 2), "EXPO": lambda t: 2 ** (10 * (t - 1)),
           "CIRC": lambda t: 1 - math.sqrt(max(0.0, 1 - t * t)), "BACK": lambda t: t * t * (2.7 * t - 1.7) * .8 + .1 * t,
           "BOUNCE": bounce, "ELASTIC": lambda t: 1 - math.cos(t * 9) * math.exp(-t * 4.5),
           "EASE_IN": ease_in(2), "EASE_OUT": ease_out(2),
           "EASE_IN_OUT": lambda t: 2 * t * t if t < .5 else 1 - 2 * (1 - t) ** 2}
    for k, fn in ipo.items():
        put(f"IPO_{k}", plot(fn, W) + f'<circle cx="2" cy="14" r="1.1" fill="{OB}"/><circle cx="14" cy="2" r="1.1" fill="{OB}"/>')
    fall = {"LINCURVE": lambda t: 1 - t, "NOCURVE": lambda t: 1.0, "SHARPCURVE": lambda t: (1 - t) ** 3,
            "SMOOTHCURVE": lambda t: 1 - t * t * (3 - 2 * t), "SPHERECURVE": lambda t: math.sqrt(max(0, 1 - t * t)),
            "ROOTCURVE": lambda t: math.sqrt(max(0, 1 - t)), "INVERSESQUARECURVE": lambda t: 1 - t ** 0.5,
            "RNDCURVE": lambda t: max(0, (1 - t) * (0.75 + 0.25 * math.sin(t * 40)))}
    for k, fn in fall.items():
        put(k, plot(fn, W))

    # ---------------------------------------------------------------- mouse
    def mouse(btn=None, extra=""):
        body = f'<rect x="4" y="1.5" width="8" height="13" rx="4" {_s()}/><path {_s()} d="M8 1.5 V6 M4 6 H12"/>'
        if btn == "L":
            body += f'<path fill="{OB}" d="M8 1.6 V6 H4.1 V5.5 A4 4 0 0 1 8 1.6 Z"/>'
        elif btn == "R":
            body += f'<path fill="{OB}" d="M8 1.6 V6 H11.9 V5.5 A4 4 0 0 0 8 1.6 Z"/>'
        elif btn == "M":
            body += f'<rect x="7" y="2.6" width="2" height="3" rx="1" fill="{OB}"/>'
        return body + extra
    arrows = f'<path {_s(OB)} d="M13 9 L15 11 L13 13 M1 9 L3 11 L1 13" opacity=".9"/>'
    put("MOUSE_LMB", mouse("L"))
    put("MOUSE_MMB", mouse("M"))
    put("MOUSE_RMB", mouse("R"))
    put("MOUSE_MMB_SCROLL", mouse("M", f'<path {_s(OB)} d="M14 3 V7 M13 4 L14 3 L15 4 M13 6 L14 7 L15 6"/>'))
    put("MOUSE_LMB_2X", mouse("L") + txt("2", 5, y=11, c=OB))
    put("MOUSE_MOVE", mouse(None, arrows))
    put("MOUSE_LMB_DRAG", mouse("L", arrows))
    put("MOUSE_MMB_DRAG", mouse("M", arrows))
    put("MOUSE_RMB_DRAG", mouse("R", arrows))

    # ---------------------------------------------------------------- text alignment & formatting
    al = {"LEFT": [(2, 12), (2, 9), (2, 12), (2, 8)], "RIGHT": [(2, 12), (5, 12), (2, 12), (6, 12)],
          "CENTER": [(2, 12), (3.5, 10.5), (2, 12), (4, 10)], "JUSTIFY": [(2, 12)] * 4,
          "FLUSH": [(2, 12), (2, 12), (2, 12), (2, 9)]}
    for k, rows in al.items():
        put(f"ALIGN_{k}", f'<path {_s(W, 1.4)} d="' + " ".join(f"M{a + 1} {3 + i * 3.3:.1f} H{b + 1}"
                                                             for i, (a, b) in enumerate(rows)) + '"/>')
    put("ALIGN_TOP ANCHOR_TOP", f'<path {_s()} d="M2 2.5 H14"/><rect x="5" y="4" width="6" height="7" rx="1" fill="{W}"/>')
    put("ALIGN_BOTTOM ANCHOR_BOTTOM", f'<path {_s()} d="M2 13.5 H14"/><rect x="5" y="5" width="6" height="7" rx="1" fill="{W}"/>')
    put("ALIGN_MIDDLE ANCHOR_CENTER", f'<path {_s()} d="M2 8 H14"/><rect x="5" y="4.5" width="6" height="7" rx="1" fill="{W}" fill-opacity=".8"/>')
    put("ANCHOR_LEFT", f'<path {_s()} d="M2.5 2 V14"/><rect x="4" y="5" width="7" height="6" rx="1" fill="{W}"/>')
    put("ANCHOR_RIGHT", f'<path {_s()} d="M13.5 2 V14"/><rect x="5" y="5" width="7" height="6" rx="1" fill="{W}"/>')
    put("BOLD", txt("B", 11))
    put("ITALIC", txt("I", 11, weight="normal").replace('font-weight="normal"', 'font-style="italic"'))
    put("UNDERLINE", txt("U", 10, y=7.5) + f'<path {_s()} d="M4 14 H12"/>')
    put("SMALL_CAPS", txt("Aa", 8))
    put("LINENUMBERS_ON LINENUMBERS_OFF", txt("12", 6, y=5) + f'<path {_s()} d="M8 9 H14 M8 12 H14 M2 12 H4"/>')
    put("WORDWRAP_ON WORDWRAP_OFF", f'<path {_s()} d="M2 4 H14 M2 8 H11 A2.4 2.4 0 0 1 11 12.8 H8 M9.5 11.3 L8 12.8 L9.5 14.3 M2 12.8 H5"/>')
    put("SYNTAX_ON SYNTAX_OFF", f'<path {_s()} d="M5 3 L2 8 L5 13 M11 3 L14 8 L11 13"/><path {_s(OB)} d="M9.5 3 L6.5 13"/>')
    put("SCRIPTPLUGINS", f'<path {_s()} d="M5 3 L2 8 L5 13 M11 3 L14 8 L11 13"/>')

    # ---------------------------------------------------------------- keyframe & handle types
    kt = {"KEYFRAME": "#e8e8e8", "BREAKDOWN": "#5ac0e0", "EXTREME": "#e87a9a", "JITTER": "#8fd36a",
          "MOVING_HOLD": "#8a8a8a", "GENERATED": "#5a5a5a"}
    for k, col in kt.items():
        put(f"KEYTYPE_{k}_VEC", f'<path d="M8 2.5 L13.5 8 L8 13.5 L2.5 8 Z" fill="{col}" stroke="#111" stroke-width=".8"/>')
    ht = {"FREE": "#1f1f1f", "ALIGNED": "#e85a8a", "VECTOR": "#6ac36a", "AUTO": "#e8d35a", "AUTO_CLAMP": "#e8935a"}
    for k, col in ht.items():
        put(f"HANDLETYPE_{k}_VEC", f'<path d="M2 12 L14 4" stroke="{col}" stroke-width="1.6"/>'
            f'<circle cx="8" cy="8" r="2.2" fill="#e8e8e8"/><circle cx="2.5" cy="11.7" r="1.6" fill="{col}"/>'
            f'<circle cx="13.5" cy="4.3" r="1.6" fill="{col}"/>')
    hd = {"ALIGNED": "#e85a8a", "AUTO": "#e8d35a", "AUTOCLAMPED": "#e8935a", "FREE": W, "VECTOR": "#6ac36a"}
    for k, col in hd.items():
        put(f"HANDLE_{k}", f'<path d="M2 12 L14 4" stroke="{col}" stroke-width="1.4"/><circle cx="8" cy="8" r="2" fill="{W}"/>'
            f'<circle cx="2.5" cy="11.7" r="1.5" fill="{col}"/><circle cx="13.5" cy="4.3" r="1.5" fill="{col}"/>')

    # ---------------------------------------------------------------- arrows & bars
    put("TRIA_DOWN_BAR", f'<path fill="{W}" d="M8 10 L3.5 4 H12.5 Z"/><path {_s(W, 1.5)} d="M3.5 12.5 H12.5"/>')
    put("TRIA_UP_BAR", f'<path fill="{W}" d="M8 6 L12.5 12 H3.5 Z"/><path {_s(W, 1.5)} d="M3.5 3.5 H12.5"/>')
    put("TRIA_LEFT_BAR", f'<path fill="{W}" d="M6 8 L12 3.5 V12.5 Z"/><path {_s(W, 1.5)} d="M3.5 3.5 V12.5"/>')
    put("TRIA_RIGHT_BAR", f'<path fill="{W}" d="M10 8 L4 3.5 V12.5 Z"/><path {_s(W, 1.5)} d="M12.5 3.5 V12.5"/>')
    put("RIGHTARROW RIGHTARROW_THIN FORWARD", f'<path {_s(W, 1.5)} d="M3 8 H13 M9 4 L13 8 L9 12"/>')
    put("BACK SCREEN_BACK", f'<path {_s(W, 1.5)} d="M13 8 H3 M7 4 L3 8 L7 12"/>')
    put("ARROW_LEFTRIGHT", f'<path {_s(W, 1.4)} d="M2 8 H14 M5 5 L2 8 L5 11 M11 5 L14 8 L11 11"/>')
    put("DISCLOSURE_TRI_DOWN", f'<path fill="{W}" d="M8 11 L4 6 H12 Z"/>')
    put("DISCLOSURE_TRI_RIGHT", f'<path fill="{W}" d="M6 4 L11 8 L6 12 Z"/>')
    put("FRAME_NEXT NEXT_KEYFRAME FF", f'<path fill="{W}" d="M3 3 L9 8 L3 13 Z M8 3 L14 8 L8 13 Z"/>')
    put("FRAME_PREV PREV_KEYFRAME REW", f'<path fill="{W}" d="M13 3 L7 8 L13 13 Z M8 3 L2 8 L8 13 Z"/>')
    put("LOOP_BACK", f'<path {_s()} d="M13 8 A5 5 0 1 0 8 13"/><path fill="{W}" d="M10 11 L8 13 L10 15 Z"/>')
    put("LOOP_FORWARDS", f'<path {_s()} d="M3 8 A5 5 0 1 1 8 13"/><path fill="{W}" d="M6 11 L8 13 L6 15 Z"/>')

    # ---------------------------------------------------------------- editors
    put("VIEW3D", f'<path {_s()} d="M8 2 L13.5 5 V11 L8 14 L2.5 11 V5 Z M2.5 5 L8 8 L13.5 5 M8 8 V14"/>')
    put("GRAPH FCURVE NORMALIZE_FCURVES", f'<path {_s()} d="M2 2 V14 H14"/><path {_s(OB, 1.4)} d="M3 12 C6 12 7 4 13 4"/>')
    put("FCURVE_SNAPSHOT", f'<path {_s()} d="M2 2 V14 H14"/><path {_s(OB, 1.4)} d="M3 12 C6 12 7 4 13 4" stroke-dasharray="2 1.5"/>')
    put("NLA NLA_PUSHDOWN", f'<rect x="2" y="3" width="8" height="3.5" rx="1" fill="{W}"/><rect x="6" y="9.5" width="8" height="3.5" rx="1" fill="{OB}"/>')
    put("PROPERTIES", f'<rect x="2.5" y="2" width="11" height="12" rx="1" {_s()}/><path {_s()} d="M5 5 H11 M5 8 H11 M5 11 H8"/>')
    put("OUTLINER", f'<path {_s()} d="M3 3 H13 M5 6.5 H13 M5 10 H13 M7 13.5 H13 M3 3 V13.5"/>')
    put("SPREADSHEET", f'<rect x="2" y="2.5" width="12" height="11" rx="1" {_s()}/><path {_s()} d="M2 6 H14 M2 9.5 H14 M6 2.5 V13.5"/>')
    put("SEQUENCE SEQ_SEQUENCER", f'<rect x="1.5" y="3" width="7" height="3.5" rx="1" fill="{MO}"/><rect x="5" y="9" width="9.5" height="3.5" rx="1" fill="{W}"/>')
    put("SOUND PLAY_SOUND FILE_SOUND SPEAKER", f'<path {_s()} d="M3 6 H6 L10 3 V13 L6 10 H3 Z M12 6 A3 3 0 0 1 12 10"/>')
    put("TRACKER TRACKING TRACKER_DATA", f'<rect x="4" y="4" width="8" height="8" {_s()}/><path {_s(OB)} d="M8 1.5 V5 M8 11 V14.5 M1.5 8 H5 M11 8 H14.5"/>')
    put("ASSET_MANAGER", f'<rect x="2" y="2" width="5" height="5" rx="1" {_s()}/><rect x="9" y="2" width="5" height="5" rx="1" {_s()}/>'
        f'<rect x="2" y="9" width="5" height="5" rx="1" {_s()}/><rect x="9" y="9" width="5" height="5" rx="1" fill="{OB}"/>')
    put("IMAGE IMAGE_PLANE IMAGE_REFERENCE IMAGE_BACKGROUND", f'<rect x="2" y="3" width="12" height="10" rx="1" {_s()}/>'
        f'<path {_s()} d="M3 12 L7 8 L10 11 L12 9 L14 11"/><circle cx="11" cy="6" r="1.2" fill="{W}"/>')
    put("NODE_COMPOSITING", f'<rect x="1.5" y="3" width="5" height="4" rx="1" {_s()}/><rect x="9.5" y="9" width="5" height="4" rx="1" fill="{OB}"/>'
        f'<path {_s()} d="M6.5 5 C9 5 7 11 9.5 11"/>')
    put("NODE_TEXTURE", f'<rect x="1.5" y="3" width="5" height="4" rx="1" {_s()}/><rect x="9.5" y="9" width="5" height="4" rx="1" fill="#9e4fa3"/>'
        f'<path {_s()} d="M6.5 5 C9 5 7 11 9.5 11"/>')
    put("GEOMETRY_SET", f'<path {_s("#00d6a3")} d="M8 2 L13.5 5 V11 L8 14 L2.5 11 V5 Z"/><circle cx="8" cy="8" r="2" fill="#00d6a3"/>')
    put("NODE_SEL NODE_CORNER NODE_SIDE NODE_TOP", f'<rect x="2" y="3" width="12" height="10" rx="1.5" {_s()}/><path {_s()} d="M2 6 H14"/>')
    put("NODE_INSERT_ON", f'<rect x="2" y="5" width="12" height="6" rx="1.5" {_s()}/><path {_s(OB)} d="M0.5 8 H2 M14 8 H15.5"/>')
    put("NODE_INSERT_OFF", f'<rect x="2" y="5" width="12" height="6" rx="1.5" {_s()} opacity=".5"/>')
    put("CONSOLE SCRIPT FILE_SCRIPT", f'<rect x="2" y="2.5" width="12" height="11" rx="1" {_s()}/><path {_s()} d="M4.5 6 L6.5 8 L4.5 10 M8 10.5 H11.5"/>')

    # ---------------------------------------------------------------- modes
    put("EDITMODE_HLT", f'<path {_s()} d="M8 2 L13.5 5 V11 L8 14 L2.5 11 V5 Z M2.5 5 L8 8 L13.5 5 M8 8 V14"/>'
        f'<circle cx="8" cy="8" r="1.5" fill="{OB}"/><circle cx="2.5" cy="5" r="1.5" fill="{OB}"/><circle cx="13.5" cy="5" r="1.5" fill="{OB}"/>')
    put("SCULPTMODE_HLT", f'<path {_s()} d="M2 12 C4 6 7 4 11 4 C13.5 4 14.5 6 13 8 C11.5 10 8 9 6.5 12 C5.8 13.6 3.6 14 2 12 Z"/>')
    put("VPAINT_HLT", f'<path {_s()} d="M8 2 C8 2 3.5 7.5 3.5 10.3 A4.5 4.5 0 0 0 12.5 10.3 C12.5 7.5 8 2 8 2 Z"/>'
        f'<path fill="{OB}" d="M5.2 10.6 A2.8 2.8 0 0 0 10.8 10.6 Z"/>')
    put("WPAINT_HLT", f'<path {_s()} d="M8 2 C8 2 3.5 7.5 3.5 10.3 A4.5 4.5 0 0 0 12.5 10.3 C12.5 7.5 8 2 8 2 Z"/>'
        '<path fill="#e05050" d="M5 11 A3 3 0 0 0 8 13.6 V8.4 C6.6 9 5 9.8 5 11 Z"/><path fill="#4a90e2" d="M11 11 A3 3 0 0 1 8 13.6 V8.4 C9.4 9 11 9.8 11 11 Z"/>')
    put("TPAINT_HLT", f'<path {_s()} d="M10.5 2.5 L13.5 5.5 L7 12 L4 9 Z M4 9 L2.5 13.5 L7 12"/>')
    put("POSE_HLT", f'<circle cx="8" cy="3" r="1.6" {_s()}/><path {_s()} d="M8 4.6 V9.5 M8 9.5 L5 14 M8 9.5 L11 14 M3.5 6.5 L8 6 L12.5 6.5"/>')
    put("PARTICLEMODE PARTICLE_POINT PARTICLE_TIP PARTICLE_PATH", f'<circle cx="4" cy="11" r="2" fill="{W}"/>'
        f'<circle cx="9" cy="6" r="1.5" fill="{W}"/><circle cx="12.5" cy="3" r="1" fill="{W}"/><circle cx="12" cy="10" r="1.2" fill="{W}"/>')

    # ---------------------------------------------------------------- selection & mesh elements
    quad = f'<path {_s()} d="M3 13 V5 L11 3 L13 11 Z" opacity=".55"/>'
    put("VERTEXSEL UV_VERTEXSEL SNAP_VERTEX", quad + f'<circle cx="11" cy="3" r="2" fill="{OB}"/>')
    put("EDGESEL UV_EDGESEL SNAP_EDGE", quad + f'<path d="M11 3 L13 11" stroke="{OB}" stroke-width="2.4" stroke-linecap="round"/>')
    put("FACESEL UV_FACESEL SNAP_FACE", f'<path fill="{OB}" fill-opacity=".85" d="M3 13 V5 L11 3 L13 11 Z"/>')
    put("UV_ISLANDSEL", f'<path fill="{OB}" fill-opacity=".85" d="M2 12 V6 L7 4 L8 10 Z M9 4 L14 3 L14 12 L10 11 Z"/>')
    put("UV_SYNC_SELECT", f'<path {_s()} d="M3 8 A5 5 0 0 1 12 5 M13 8 A5 5 0 0 1 4 11"/><path fill="{W}" d="M12.5 2.5 L13 6 L9.5 5.5 Z M3.5 13.5 L3 10 L6.5 10.5 Z"/>')
    put("FACE_CORNER", quad + f'<path fill="{OB}" d="M3 13 V10 L6 12.5 Z"/>')
    put("EDGE_BEVEL", f'<path {_s()} d="M2 14 V7 L7 2 H14"/><path stroke="{OB}" stroke-width="2.2" d="M2 7 L7 2"/>')
    put("EDGE_CREASE VERTEX_CREASE", f'<path {_s()} d="M2 12 L8 4 L14 12"/><circle cx="8" cy="4" r="1.8" fill="{OB}"/>')
    put("EDGE_SEAM", f'<path {_s()} d="M3 13 V5 L11 3 L13 11 Z" opacity=".55"/><path d="M3 5 L13 11" stroke="#e85a5a" stroke-width="2"/>')
    put("EDGE_SHARP", f'<path {_s()} d="M3 13 V5 L11 3 L13 11 Z" opacity=".55"/><path d="M3 5 L13 11" stroke="#5ac0e8" stroke-width="2"/>')
    put("NORMALS_FACE", f'<path {_s()} d="M2 12 H14"/><path {_s(OB)} d="M8 12 V3"/><path fill="{OB}" d="M8 1.5 L9.6 4 H6.4 Z"/>')
    put("NORMALS_VERTEX", f'<path {_s()} d="M2 12 L8 8 L14 12"/><path {_s(OB)} d="M8 8 V2"/><circle cx="8" cy="8" r="1.4" fill="{W}"/>')
    put("NORMALS_VERTEX_FACE", f'<path {_s()} d="M2 12 L8 8 L14 12"/><path {_s(OB)} d="M8 8 V2 M5 10 L3.5 6"/>')
    put("SELECT_SET", f'<rect x="3" y="3" width="10" height="10" fill="{W}" fill-opacity=".85"/>')
    put("SELECT_EXTEND", f'<rect x="2" y="2" width="8" height="8" {_s()}/><rect x="6" y="6" width="8" height="8" fill="{W}" fill-opacity=".85"/>')
    put("SELECT_SUBTRACT", f'<rect x="2" y="2" width="8" height="8" fill="{W}" fill-opacity=".85"/><rect x="6" y="6" width="8" height="8" fill="#262626" stroke="{W}" stroke-width="1.2"/>')
    put("SELECT_INTERSECT", f'<rect x="2" y="2" width="8" height="8" {_s()}/><rect x="6" y="6" width="8" height="8" {_s()}/><rect x="6" y="6" width="4" height="4" fill="{W}"/>')
    put("SELECT_DIFFERENCE", f'<rect x="2" y="2" width="8" height="8" fill="{W}" fill-opacity=".85"/><rect x="6" y="6" width="8" height="8" fill="{W}" fill-opacity=".85"/><rect x="6" y="6" width="4" height="4" fill="#262626"/>')
    put("STICKY_UVS_LOC STICKY_UVS_VERT STICKY_UVS_DISABLE", quad + f'<circle cx="11" cy="3" r="2" fill="{W}"/>')
    put("POINTCLOUD_POINT", f'<circle cx="8" cy="8" r="3" fill="{DA}"/>')
    put("STROKE GP_DRAW_STROKE", f'<path {_s(W, 1.6)} d="M2 12 C5 4 9 14 14 4"/>')
    put("GP_DRAW_FILL", f'<path fill="{W}" fill-opacity=".7" d="M2 12 C5 4 9 14 14 4 V14 H2 Z"/>')
    put("GP_DRAW_BOTH", f'<path fill="{W}" fill-opacity=".45" d="M2 12 C5 4 9 14 14 4 V14 H2 Z"/><path {_s(W, 1.6)} d="M2 12 C5 4 9 14 14 4"/>')
    put("GP_CAPS_FLAT", f'<path stroke="{W}" stroke-width="5" d="M3 8 H13"/>')
    put("GP_CAPS_ROUND", f'<path stroke="{W}" stroke-width="5" stroke-linecap="round" d="M4 8 H12"/>')
    put("GP_SELECT_POINTS GP_ONLY_SELECTED", f'<path {_s()} d="M2 12 C5 4 9 14 14 4"/><circle cx="8" cy="9" r="1.8" fill="{OB}"/>')
    put("GP_SELECT_STROKES GP_SELECT_BETWEEN_STROKES", f'<path {_s(OB, 1.8)} d="M2 12 C5 4 9 14 14 4"/>')
    put("GP_MULTIFRAME_EDITING", f'<rect x="2" y="5" width="5" height="7" {_s()}/><rect x="9" y="5" width="5" height="7" {_s(OB)}/>')
    put("GREASEPENCIL_LAYER_GROUP", f'<path {_s()} d="M1.5 4 H6 L7.5 5.5 H14.5 V13 H1.5 Z"/>')
    put("META_BALL META_ELLIPSOID META_CAPSULE META_CUBE META_PLANE", f'<circle cx="6" cy="8" r="3.6" {_s()}/><circle cx="11" cy="7" r="2.6" {_s()}/>')
    put("MESH_CAPSULE", f'<rect x="4.5" y="2" width="7" height="12" rx="3.5" {_s()}/>')
    put("SURFACE_NCIRCLE SURFACE_NCURVE SURFACE_NCYLINDER SURFACE_NSPHERE SURFACE_NSURFACE SURFACE_NTORUS",
        f'<path {_s()} d="M2 10 C5 6 11 14 14 9 M2 6 C5 2 11 10 14 5 M4 4 V12 M8 6 V12 M12 4 V11"/>')
    put("CURVES", f'<path {_s()} d="M3 14 C3 9 5 5 4 2 M8 14 C8 9 9 5 8 2 M13 14 C13 9 11 5 12 2"/>')
    put("LIGHT_HEMI", f'<path {_s(LI)} d="M3 9 A5 5 0 0 1 13 9 Z"/><path {_s(LI)} d="M4 11 L3 14 M8 11 V14 M12 11 L13 14"/>')
    put("LIGHTPROBE_SPHERE", f'<circle cx="8" cy="8" r="5.5" {_s()}/><circle cx="8" cy="8" r="2" fill="{W}"/>')
    put("LIGHTPROBE_PLANE", f'<path {_s()} d="M2 10 L8 6.5 L14 10 L8 13.5 Z"/><circle cx="8" cy="10" r="1.5" fill="{W}"/>')
    put("LIGHTPROBE_VOLUME", f'<path {_s()} d="M8 2 L13.5 5 V11 L8 14 L2.5 11 V5 Z"/><circle cx="8" cy="8" r="1.6" fill="{W}"/>')

    # ---------------------------------------------------------------- forces & physics
    force = f'<circle cx="8" cy="8" r="1.6" fill="{W}"/><circle cx="8" cy="8" r="4" {_s()} stroke-dasharray="2 1.6"/>'
    put("FORCE_BOID BOIDS", f'<path fill="{W}" d="M2 9 L14 4 L9 14 L8 10 Z"/>')
    put("FORCE_CHARGE", force + txt("±", 6, y=8, c=OB))
    put("FORCE_CURVE FORCE_DRAG FORCE_FLUIDFLOW FORCE_HARMONIC FORCE_LENNARDJONES FORCE_TEXTURE", force)
    put("RIGID_BODY", f'<rect x="3" y="3" width="10" height="10" rx="1" fill="{W}" fill-opacity=".85"/>')
    put("RIGID_BODY_CONSTRAINT", f'<rect x="1.5" y="5" width="5" height="5" fill="{W}"/><rect x="9.5" y="5" width="5" height="5" fill="{W}"/><path {_s(OB)} d="M6.5 7.5 H9.5"/>')
    put("MATCLOTH", f'<path {_s()} d="M2 3 H14 C13 7 14 10 12 13 C9 11 6 14 3 12 C4 9 2 6 2 3 Z"/>')
    put("MATFLUID", f'<path {_s()} d="M8 2 C8 2 3.5 7.5 3.5 10.3 A4.5 4.5 0 0 0 12.5 10.3 C12.5 7.5 8 2 8 2 Z"/>')
    put("MATSPHERE MATSHADERBALL MAT_SPHERE_SKY", '<circle cx="8" cy="8" r="5.8" fill="#9a9a9a"/><circle cx="6" cy="6" r="2" fill="#ffffff" fill-opacity=".7"/>')
    put("MATCUBE", f'<path fill="#9a9a9a" d="M8 2 L13.5 5 V11 L8 14 L2.5 11 V5 Z"/><path fill="#c8c8c8" d="M8 2 L13.5 5 L8 8 L2.5 5 Z"/>')
    put("MATPLANE", f'<path fill="#9a9a9a" d="M2 10 L8 6.5 L14 10 L8 13.5 Z"/>')

    # ---------------------------------------------------------------- animation
    put("MARKER", f'<path {_s()} d="M8 14 V7 M5 2.5 H11 V6 L8 8 L5 6 Z"/>')
    put("MARKER_HLT PMARKER_ACT", f'<path fill="{W}" d="M5 2.5 H11 V6 L8 8 L5 6 Z"/><path {_s()} d="M8 8 V14"/>')
    put("PMARKER PMARKER_SEL", f'<path {_s()} d="M5 2.5 H11 V6 L8 8 L5 6 Z"/>')
    put("MUTE_IPO_OFF", f'<path {_s()} d="M3 13 L13 3"/><circle cx="8" cy="8" r="5.5" {_s()}/>')
    put("MUTE_IPO_ON", f'<circle cx="8" cy="8" r="5.5" {_s()}/>')
    put("SOLO_ON", f'<path fill="{LI}" d="M8 2 L9.8 6 L14 6.3 L10.8 9 L11.8 13.5 L8 11 L4.2 13.5 L5.2 9 L2 6.3 L6.2 6 Z"/>')
    put("SOLO_OFF", f'<path {_s()} d="M8 2 L9.8 6 L14 6.3 L10.8 9 L11.8 13.5 L8 11 L4.2 13.5 L5.2 9 L2 6.3 L6.2 6 Z"/>')
    put("REC RECORD_ON", '<circle cx="8" cy="8" r="5" fill="#e04848"/>')
    put("RECORD_OFF", f'<circle cx="8" cy="8" r="5" {_s()}/>')
    put("PREVIEW_RANGE", f'<path {_s()} d="M3 3 V13 M13 3 V13"/><rect x="3" y="6" width="10" height="4" fill="{OB}" fill-opacity=".6"/>')
    put("ACTION_SLOT", f'<path {_s()} d="M2 12 L6 5 L10 10 L14 3"/><rect x="1.5" y="12.5" width="13" height="2" fill="{OB}"/>')
    put("ACTION_TWEAK", f'<path {_s()} d="M2 12 L6 5 L10 10 L14 3"/><circle cx="10" cy="10" r="1.8" fill="{OB}"/>')
    put("DRIVER_DISTANCE", f'<circle cx="3.5" cy="8" r="1.8" fill="{W}"/><circle cx="12.5" cy="8" r="1.8" fill="{W}"/><path {_s("#c38cff")} d="M5.5 8 H10.5"/>')
    put("DRIVER_ROTATIONAL_DIFFERENCE", f'<path {_s("#c38cff")} d="M3 13 L13 13 M3 13 L11 5"/><path {_s()} d="M8 13 A5 5 0 0 0 6.5 9.5"/>')
    put("DRIVER_TRANSFORM", f'<path {_s("#c38cff")} d="M8 1.5 V14.5 M1.5 8 H14.5"/>')
    put("ONIONSKIN_ON", f'<circle cx="6" cy="8" r="4" {_s()} opacity=".5"/><circle cx="10" cy="8" r="4" fill="{W}" fill-opacity=".85"/>')
    put("ONIONSKIN_OFF", f'<circle cx="6" cy="8" r="4" {_s()} opacity=".4"/><circle cx="10" cy="8" r="4" {_s()}/>')
    put("GHOST_ENABLED", f'<path fill="{W}" fill-opacity=".85" d="M3 14 V7 A5 5 0 0 1 13 7 V14 L11 12.5 L9.5 14 L8 12.5 L6.5 14 L5 12.5 Z"/>')
    put("GHOST_DISABLED", f'<path {_s()} d="M3 14 V7 A5 5 0 0 1 13 7 V14 L11 12.5 L9.5 14 L8 12.5 L6.5 14 L5 12.5 Z"/>')
    put("PLAYHEAD_SNAP_ON PLAYHEAD_SNAP_OFF", f'<path {_s("#5a8ee8", 1.6)} d="M8 4 V15"/><rect x="5" y="1.5" width="6" height="4" rx="1" fill="#5a8ee8"/>')

    # ---------------------------------------------------------------- toggles (on / off pairs)
    put("RADIOBUT_ON", f'<circle cx="8" cy="8" r="5.5" fill="#4772b3"/><circle cx="8" cy="8" r="2.4" fill="#ffffff"/>')
    put("RADIOBUT_OFF", f'<circle cx="8" cy="8" r="5.5" {_s()}/>')
    put("PINNED", f'<path fill="{W}" d="M6 2 H10 L9.5 6 L12 9 H4 L6.5 6 Z"/><path {_s()} d="M8 9 V14.5"/>')
    put("UNPINNED", f'<path {_s()} d="M6 2 H10 L9.5 6 L12 9 H4 L6.5 6 Z M8 9 V14.5"/>')
    put("AUTOMERGE_ON", f'<circle cx="5" cy="8" r="2" fill="{W}"/><circle cx="11" cy="8" r="2" fill="{W}"/><path {_s(OB)} d="M7 8 H9"/>')
    put("AUTOMERGE_OFF", f'<circle cx="5" cy="8" r="2" {_s()}/><circle cx="11" cy="8" r="2" {_s()}/>')
    put("CLIPUV_HLT CLIPUV_DEHLT", f'<rect x="2.5" y="2.5" width="11" height="11" {_s()}/><path {_s(OB)} d="M5 11 L11 5"/>')
    put("INDIRECT_ONLY_ON INDIRECT_ONLY_OFF", f'<circle cx="8" cy="8" r="5.5" {_s()}/><path {_s()} d="M5 11 L11 5"/>')
    put("HOLDOUT_ON", f'<circle cx="8" cy="8" r="5.5" fill="{W}"/><circle cx="8" cy="8" r="2.5" fill="#262626"/>')
    put("HOLDOUT_OFF", f'<circle cx="8" cy="8" r="5.5" {_s()}/><circle cx="8" cy="8" r="2.5" {_s()}/>')
    put("MODIFIER_ON", f'<path {_s(MO)} d="M10.5 2.5 A3 3 0 0 0 9 7 L3 13 L4.5 14.5 L10.5 8.5 A3 3 0 0 0 14 6 L12 6 L10 4 Z"/>')
    put("MODIFIER_OFF", f'<path {_s()} d="M10.5 2.5 A3 3 0 0 0 9 7 L3 13 L4.5 14.5 L10.5 8.5 A3 3 0 0 0 14 6 L12 6 L10 4 Z" opacity=".5"/>')
    put("RESTRICT_COLOR_ON RESTRICT_COLOR_OFF", '<circle cx="8" cy="8" r="5.5" fill="#e8935a"/>')
    put("RESTRICT_INSTANCED_ON RESTRICT_INSTANCED_OFF", f'<rect x="2" y="4" width="6" height="6" {_s()}/><rect x="8" y="6" width="6" height="6" {_s()}/>')
    put("VIS_SEL_10 VIS_SEL_01 VIS_SEL_00", f'<rect x="1.5" y="2.5" width="13" height="9" rx="1" {_s()} opacity=".6"/>')
    put("DECORATE_LOCKED", f'<rect x="4" y="7.5" width="8" height="6" rx="1" {_s()}/><path {_s()} d="M5.8 7.5 V5.5 A2.2 2.2 0 0 1 10.2 5.5 V7.5"/>')
    put("DECORATE_LIBRARY_OVERRIDE DECORATE_OVERRIDE LIBRARY_DATA_OVERRIDE LIBRARY_DATA_OVERRIDE_NONEDITABLE",
        f'<path {_s()} d="M6.5 9.5 L9.5 6.5 M7 4.5 L8.5 3 A2.5 2.5 0 0 1 13 7.5 L11.5 9 M9 11.5 L7.5 13 A2.5 2.5 0 0 1 3 8.5 L4.5 7"/>'
        f'<circle cx="12.5" cy="12.5" r="2.2" fill="{MO}"/>')
    put("DECORATE_LINKED LIBRARY_DATA_DIRECT LIBRARY_DATA_INDIRECT UNLINKED",
        f'<path {_s()} d="M6.5 9.5 L9.5 6.5 M7 4.5 L8.5 3 A2.5 2.5 0 0 1 13 7.5 L11.5 9 M9 11.5 L7.5 13 A2.5 2.5 0 0 1 3 8.5 L4.5 7"/>')
    put("LIBRARY_DATA_BROKEN", f'<path {_s(RD)} d="M7 4.5 L8.5 3 A2.5 2.5 0 0 1 13 7.5 L11.5 9 M9 11.5 L7.5 13 A2.5 2.5 0 0 1 3 8.5 L4.5 7"/>')
    put("LOCKVIEW_ON VIEW_LOCKED", f'<rect x="4" y="7.5" width="8" height="6.5" rx="1" fill="{W}"/><path {_s()} d="M5.8 7.5 V5 A2.2 2.2 0 0 1 10.2 5 V7.5"/>')
    put("LOCKVIEW_OFF VIEW_UNLOCKED", f'<rect x="4" y="7.5" width="8" height="6.5" rx="1" {_s()}/><path {_s()} d="M5.8 7.5 V5 A2.2 2.2 0 0 1 10.2 4.4"/>')

    # ---------------------------------------------------------------- view & gizmos
    put("GIZMO", f'<path {_s()} d="M8 8 V2.5 M8 8 L13 10.5 M8 8 L3 10.5"/><path fill="#5aa0ff" d="M8 1 L9.6 3.6 H6.4 Z"/>'
        '<path fill="#ff5a6e" d="M14.4 11.2 L11.4 11.6 L12.8 8.9 Z"/><path fill="#8bdc3a" d="M1.6 11.2 L3.2 8.9 L4.6 11.6 Z"/>')
    put("GRID", f'<path {_s()} d="M2.5 2.5 H13.5 V13.5 H2.5 Z M2.5 6.2 H13.5 M2.5 9.8 H13.5 M6.2 2.5 V13.5 M9.8 2.5 V13.5"/>')
    put("AXIS_FRONT", f'<path {_s()} d="M2 14 H14 M8 14 V2"/>' + txt("F", 5, y=4, c=OB))
    put("AXIS_SIDE", f'<path {_s()} d="M2 14 H14 M8 14 V2"/>' + txt("S", 5, y=4, c=OB))
    put("AXIS_TOP", f'<path {_s()} d="M2 14 H14 M8 14 V2"/>' + txt("T", 5, y=4, c=OB))
    put("VIEW_ORTHO", f'<rect x="2" y="2.5" width="12" height="11" {_s()}/><path {_s()} d="M8 2.5 V13.5 M2 8 H14"/>')
    put("VIEW_PERSPECTIVE", f'<path {_s()} d="M5 3 H11 L14.5 13 H1.5 Z M8 3 V13 M3.3 8 H12.7"/>')
    put("VIEW_ZOOM ZOOM_SELECTED ZOOM_ALL ZOOM_PREVIOUS", f'<circle cx="6.8" cy="6.8" r="4.6" {_s()}/><path d="M10.3 10.3 L14.4 14.4" stroke="{W}" stroke-width="2.2" stroke-linecap="round"/>')
    put("VIEW_CAMERA_UNSELECTED", f'<rect x="1.5" y="5" width="9.5" height="7" rx="1.2" {_s()} opacity=".6"/><path {_s()} d="M11 7.4 L14.5 5.5 V11.5 L11 9.6" opacity=".6"/>')
    put("SHADING_BBOX", f'<rect x="2.5" y="2.5" width="11" height="11" {_s()} stroke-dasharray="2 1.5"/>')
    put("LAYER_ACTIVE", f'<circle cx="8" cy="8" r="3.5" fill="{OB}"/>')
    put("LAYER_USED", f'<circle cx="8" cy="8" r="2.5" fill="{W}"/>')
    put("CAMERA_STEREO", f'<circle cx="5" cy="8" r="3" {_s()}/><circle cx="11" cy="8" r="3" {_s()}/>')
    put("FIXED_SIZE", f'<rect x="3" y="3" width="10" height="10" {_s()}/><path {_s()} d="M1.5 1.5 L3 3 M14.5 1.5 L13 3 M14.5 14.5 L13 13 M1.5 14.5 L3 13"/>')
    put("TRANSFORM_ORIGINS", f'<circle cx="8" cy="8" r="2" fill="{OB}"/><path {_s()} d="M8 1.5 V5 M8 11 V14.5 M1.5 8 H5 M11 8 H14.5"/>')
    put("CENTER_ONLY", f'<circle cx="8" cy="8" r="2" fill="{W}"/>')
    put("PASTEFLIPDOWN PASTEFLIPUP", f'<rect x="3" y="3" width="10" height="11" rx="1" {_s()}/><path {_s()} d="M6 7 L10 11 M10 7 L6 11"/>')
    put("SNAP_FACE_CENTER SNAP_FACE_NEAREST SNAP_NORMAL SNAP_PEEL_OBJECT", quad + f'<circle cx="8" cy="8" r="1.8" fill="{OB}"/>')
    put("TRACKING_FORWARDS TRACKING_FORWARDS_SINGLE TRACKING_REFINE_FORWARDS TRACKING_CLEAR_FORWARDS",
        f'<rect x="2" y="5" width="6" height="6" {_s()}/><path {_s(OB, 1.4)} d="M9 8 H14 M12 6 L14 8 L12 10"/>')
    put("TRACKING_BACKWARDS TRACKING_BACKWARDS_SINGLE TRACKING_REFINE_BACKWARDS TRACKING_CLEAR_BACKWARDS",
        f'<rect x="8" y="5" width="6" height="6" {_s()}/><path {_s(OB, 1.4)} d="M7 8 H2 M4 6 L2 8 L4 10"/>')

    # ---------------------------------------------------------------- areas & window
    put("AREA_DOCK", f'<rect x="1.5" y="2.5" width="13" height="11" rx="1" {_s()}/><rect x="1.5" y="9" width="13" height="4.5" fill="{W}" fill-opacity=".5"/>')
    put("AREA_SWAP", f'<rect x="1.5" y="2.5" width="13" height="11" rx="1" {_s()}/><path {_s()} d="M8 2.5 V13.5 M4 8 H6 M10 8 H12"/>')
    put("AREA_JOIN AREA_JOIN_DOWN AREA_JOIN_LEFT AREA_JOIN_UP", f'<rect x="1.5" y="2.5" width="13" height="11" rx="1" {_s()}/><path {_s(OB, 1.4)} d="M5 8 H11 M9 6 L11 8 L9 10"/>')
    put("SPLIT_HORIZONTAL", f'<rect x="1.5" y="2.5" width="13" height="11" rx="1" {_s()}/><path {_s()} d="M1.5 8 H14.5"/>')
    put("SPLIT_VERTICAL", f'<rect x="1.5" y="2.5" width="13" height="11" rx="1" {_s()}/><path {_s()} d="M8 2.5 V13.5"/>')
    put("FULLSCREEN_ENTER", f'<path {_s()} d="M2 6 V2 H6 M10 2 H14 V6 M14 10 V14 H10 M6 14 H2 V10"/>')
    put("FULLSCREEN_EXIT", f'<path {_s()} d="M6 2 V6 H2 M14 6 H10 V2 M10 14 V10 H14 M2 10 H6 V14"/>')
    put("TOPBAR", f'<rect x="1.5" y="2.5" width="13" height="11" rx="1" {_s()}/><rect x="1.5" y="2.5" width="13" height="3" fill="{W}"/>')
    put("STATUSBAR", f'<rect x="1.5" y="2.5" width="13" height="11" rx="1" {_s()}/><rect x="1.5" y="10.5" width="13" height="3" fill="{W}"/>')
    put("MENU_PANEL", f'<rect x="2" y="2.5" width="12" height="11" rx="1" {_s()}/><path {_s()} d="M4.5 6 H11.5 M4.5 9 H11.5"/>')
    put("GRIP GRIP_V", ''.join(f'<circle cx="{x}" cy="{y}" r="1" fill="{W}"/>' for x in (6, 10) for y in (4, 8, 12)))
    put("GRIP_CORNER_BOTTOM_RIGHT", f'<path {_s()} d="M14 6 L6 14 M14 10 L10 14"/>')
    put("THREE_DOTS OPTIONS", ''.join(f'<circle cx="{x}" cy="8" r="1.3" fill="{W}"/>' for x in (3.5, 8, 12.5)))
    put("DOT", f'<circle cx="8" cy="8" r="2" fill="{W}"/>')
    put("BORDERMOVE", f'<path {_s()} d="M8 1.5 V14.5 M1.5 8 H14.5"/><path fill="{W}" d="M8 1 L9.6 3.6 H6.4 Z M8 15 L6.4 12.4 H9.6 Z M1 8 L3.6 6.4 V9.6 Z M15 8 L12.4 9.6 V6.4 Z"/>')
    put("QUIT", f'<path {_s()} d="M9 2.5 H3 V13.5 H9 M7 8 H14 M11 5 L14 8 L11 11"/>')
    put("URL INTERNET", f'<circle cx="8" cy="8" r="5.6" {_s()}/><ellipse cx="8" cy="8" rx="2.4" ry="5.6" {_s()}/><path {_s()} d="M2.4 8 H13.6"/>')
    put("INTERNET_OFFLINE", f'<circle cx="8" cy="8" r="5.6" {_s()} opacity=".5"/><path {_s(RD)} d="M3 13 L13 3"/>')
    put("PLUGIN", f'<path {_s()} d="M5 2 V5 M11 2 V5 M3 5 H13 V9 A5 5 0 0 1 3 9 Z M8 13 V15"/>')
    put("PRESET_NEW", f'<path {_s(W, 1.5)} d="M3 4 H10 M3 8 H10 M3 12 H8"/><path {_s(OB, 1.5)} d="M12.5 9 V15 M9.5 12 H15.5"/>')
    put("PROJECT", f'<path {_s()} d="M1.5 4 H6 L7.5 5.5 H14.5 V13 H1.5 Z"/><circle cx="8" cy="9.5" r="1.6" fill="{OB}"/>')
    put("STYLUS_PRESSURE", f'<path {_s()} d="M11 2.5 L13.5 5 L6 12.5 L3 13 L3.5 10 Z"/>')
    put("AUTO", txt("A", 9))
    put("COPY_ID", f'<rect x="2" y="4.5" width="8" height="9" rx="1" {_s()}/><path {_s()} d="M6 4.5 V2.5 H14 V11.5 H10"/>')
    put("FREEZE", f'<path {_s()} d="M8 1.5 V14.5 M2.4 4.8 L13.6 11.2 M2.4 11.2 L13.6 4.8"/>')
    put("BLENDER BLENDER_LOGO_LARGE COMMUNITY", f'<circle cx="8" cy="8" r="5.6" {_s()}/><circle cx="8" cy="8" r="2" fill="{OB}"/>')
    put("RNA", f'<path {_s()} d="M3 2 C13 5 3 11 13 14 M13 2 C3 5 13 11 3 14"/>')
    put("FUND HEART", f'<path fill="#e85a8a" d="M8 13.5 C3 10 1.5 7.5 2.5 5 C3.5 2.5 6.5 2.5 8 5 C9.5 2.5 12.5 2.5 13.5 5 C14.5 7.5 13 10 8 13.5 Z"/>')
    put("USER", f'<circle cx="8" cy="5" r="2.8" {_s()}/><path {_s()} d="M2.5 14 A5.5 5.5 0 0 1 13.5 14"/>')
    put("EXPERIMENTAL", f'<path {_s()} d="M6 2 H10 M7 2 V6 L3 13 H13 L9 6 V2"/>')
    put("MEMORY", f'<rect x="3" y="3" width="10" height="10" rx="1" {_s()}/><path {_s()} d="M6 1 V3 M10 1 V3 M6 13 V15 M10 13 V15 M1 6 H3 M1 10 H3 M13 6 H15 M13 10 H15"/>')
    put("GESTURE_PAN", f'<path {_s()} d="M8 1.5 V14.5 M1.5 8 H14.5"/>')
    put("GESTURE_ROTATE", f'<path {_s()} d="M13 8 A5 5 0 1 1 10.5 3.7"/>')
    put("GESTURE_ZOOM", f'<path {_s()} d="M2 14 L14 2 M2 14 V10 M2 14 H6 M14 2 V6 M14 2 H10"/>')
    put("ALIASED", f'<path fill="{W}" d="M2 14 H6 V10 H10 V6 H14 V2 H12 V4 H8 V8 H4 V12 H2 Z"/>')
    put("ANTIALIASED", f'<path fill="{W}" d="M2 14 L14 2 V5 L5 14 Z"/>')
    put("RENDER_SWAP_DIMENSIONS", f'<rect x="2" y="4" width="8" height="5" {_s()}/><rect x="9" y="6" width="5" height="8" {_s()}/>')
    put("TIME", f'<circle cx="8" cy="8" r="6" {_s()}/><path {_s()} d="M8 4.5 V8 L10.5 10"/>')
    put("SHADERFX", f'<path {_s()} d="M2 13 L8 3 L14 13 Z"/><path fill="{OB}" d="M8 7 L9 9.5 L11.5 10 L9 10.6 L8 13 L7 10.6 L4.5 10 L7 9.5 Z"/>')
    put("LINE_DATA", f'<path {_s(DA, 1.4)} d="M2 12 L6 5 L10 10 L14 3"/>')
    put("FACE_MAPS", f'<path fill="{DA}" fill-opacity=".8" d="M3 13 V5 L11 3 L13 11 Z"/>')
    put("GROUP_BONE", f'<path {_s(DA)} d="M4 12 L11 5"/><circle cx="4" cy="12" r="1.8" fill="{DA}"/><circle cx="11" cy="5" r="1.8" fill="{DA}"/>')
    put("GROUP_VCOL", '<path fill="#e85a5a" d="M8 2 L14 13 H2 Z"/><path fill="#5a8ee8" d="M8 7 L14 13 H2 Z" fill-opacity=".8"/>')
    put("STRANDS", f'<path {_s()} d="M3 14 C3 9 5 5 4 2 M8 14 C8 9 9 5 8 2 M13 14 C13 9 11 5 12 2"/>')
    put("GREASEPENCIL", f'<path {_s()} d="M11 2.5 L13.5 5 L6 12.5 L3 13 L3.5 10 Z"/><path {_s()} d="M2 15 C5 13 9 15 14 13"/>')
    put("ORPHAN_DATA", f'<circle cx="8" cy="8" r="5.5" {_s()} stroke-dasharray="2 1.5"/>')
    put("PACKAGE PACKAGE_INDIRECT UGLYPACKAGE", f'<path {_s()} d="M8 1.5 L14 4.5 V11.5 L8 14.5 L2 11.5 V4.5 Z M2 4.5 L8 7.5 L14 4.5 M8 7.5 V14.5"/>')
    put("FILE", f'<path {_s()} d="M3.5 1.5 H9.5 L12.5 4.5 V14.5 H3.5 Z M9.5 1.5 V4.5 H12.5"/>')

    # ---------------------------------------------------------------- file browser
    doc = 'M3.5 1.5 H9.5 L12.5 4.5 V14.5 H3.5 Z M9.5 1.5 V4.5 H12.5'

    def file_with(label, c=W):
        return f'<path {_s()} d="{doc}"/>' + txt(label, 4.4 if len(label) > 2 else 5.4, y=10.2, c=c)
    for name, lab in (("FILE_3D", "3D"), ("FILE_ARCHIVE", "ZIP"), ("FILE_BACKUP", "BAK"), ("FILE_BLEND", "B"),
                      ("FILE_CACHE", "C"), ("FILE_MOVIE", "▶"), ("FILE_TEXT", "Tx"), ("FILE_VOLUME", "V"),
                      ("FILE_HIDDEN", "·"), ("FILE_ALIAS", "↪"), ("TEMP", "T")):
        put(name, file_with(lab, OB if name == "FILE_BLEND" else W))
    folder = 'M1.5 4 H6 L7.5 5.5 H14.5 V13 H1.5 Z'
    put("FILE_PARENT", f'<path {_s()} d="{folder}"/><path {_s(OB)} d="M8 12 V7.5 M6 9.5 L8 7.5 L10 9.5"/>')
    put("NEWFOLDER", f'<path {_s()} d="{folder}"/><path {_s(OB)} d="M8 7.5 V11.5 M6 9.5 H10"/>')
    put("FOLDER_REDIRECT", f'<path {_s()} d="{folder}"/><path {_s(OB)} d="M5 11 C5 8.5 7 8 10 8 M8.5 6.5 L10 8 L8.5 9.5"/>')
    put("CURRENT_FILE", f'<path {_s()} d="{doc}"/><circle cx="8" cy="10" r="1.8" fill="{OB}"/>')
    put("BOOKMARKS TAG", f'<path {_s()} d="M4 2 H12 V14 L8 11 L4 14 Z"/>')
    put("DESKTOP", f'<rect x="1.5" y="2.5" width="13" height="9" rx="1" {_s()}/><path {_s()} d="M6 14 H10 M8 11.5 V14"/>')
    put("DOCUMENTS", f'<path {_s()} d="{doc}"/><path {_s()} d="M5.5 8 H10.5 M5.5 10.5 H10.5"/>')
    put("DOWNLOAD", f'<path {_s()} d="M8 2 V10 M5 7 L8 10 L11 7 M3 13.5 H13"/>')
    put("DOWNLOAD_DONE", f'<path {_s()} d="M3 13.5 H13"/><path {_s(DA, 1.6)} d="M4 7 L7 10 L12 4"/>')
    put("HOME", f'<path {_s()} d="M2 8 L8 2.5 L14 8 M4 6.5 V13.5 H12 V6.5"/>')
    put("SYSTEM", f'<rect x="1.5" y="2.5" width="13" height="9" rx="1" {_s()}/><path {_s()} d="M6 14 H10 M8 11.5 V14"/>')
    put("DISK_DRIVE DISK_DRIVE_LARGE DISC DISC_LARGE", f'<rect x="1.5" y="5" width="13" height="6" rx="1.5" {_s()}/><circle cx="11.5" cy="8" r="1" fill="{W}"/>')
    put("EXTERNAL_DRIVE EXTERNAL_DRIVE_LARGE USB_DRIVE USB_DRIVE_LARGE", f'<rect x="4" y="5" width="8" height="9" rx="1" {_s()}/><path {_s()} d="M6 5 V2 H10 V5"/>')
    put("NETWORK_DRIVE NETWORK_DRIVE_LARGE", f'<rect x="1.5" y="3" width="13" height="5" rx="1.5" {_s()}/><path {_s()} d="M8 8 V11 M3 12.5 H13"/>')
    put("FILE_FOLDER_LARGE", f'<path {_s()} d="{folder}"/>')
    put("FILE_LARGE", f'<path {_s()} d="{doc}"/>')
    put("FILE_PARENT_LARGE", f'<path {_s()} d="{folder}"/><path {_s(OB)} d="M8 12 V7.5 M6 9.5 L8 7.5 L10 9.5"/>')
    put("CANCEL_LARGE", f'<path {_s(W, 1.6)} d="M4 4 L12 12 M12 4 L4 12"/>')
    put("INFO_LARGE STATUS_INFO", f'<circle cx="8" cy="8" r="6" {_s()}/><path {_s(W, 1.6)} d="M8 7.5 V11.5 M8 4.8 V4.9"/>')
    put("STATUS_INFO_FILLED", '<circle cx="8" cy="8" r="6" fill="#5aa0ff"/><path stroke="#fff" stroke-width="1.6" stroke-linecap="round" d="M8 7.5 V11.5 M8 4.8 V4.9"/>')
    put("QUESTION_LARGE", f'<circle cx="8" cy="8" r="6" {_s()}/><path {_s(W, 1.4)} d="M6 6.2 A2 2 0 1 1 8.5 8 C8 8.3 8 8.7 8 9.5 M8 11.8 V11.9"/>')
    put("WARNING_LARGE STATUS_WARNING", f'<path {_s("#e8a33d")} d="M8 1.5 L15 14 H1 Z"/><path stroke="#e8a33d" stroke-width="1.6" stroke-linecap="round" d="M8 6 V9.5 M8 11.8 V11.9"/>')
    put("STATUS_WARNING_FILLED", '<path fill="#e8a33d" d="M8 1.5 L15 14 H1 Z"/><path stroke="#1a1a1a" stroke-width="1.6" stroke-linecap="round" d="M8 6 V9.5 M8 11.8 V11.9"/>')
    put("STATUS_ERROR", f'<circle cx="8" cy="8" r="6" {_s(RD)}/><path {_s(RD, 1.6)} d="M5.5 5.5 L10.5 10.5 M10.5 5.5 L5.5 10.5"/>')
    put("STATUS_ERROR_FILLED", f'<circle cx="8" cy="8" r="6" fill="{RD}"/><path stroke="#fff" stroke-width="1.6" stroke-linecap="round" d="M5.5 5.5 L10.5 10.5 M10.5 5.5 L5.5 10.5"/>')
    put("FILTER", f'<path {_s()} d="M2 3 H14 L9.5 8.5 V13.5 L6.5 12 V8.5 Z"/>')
    put("FILTER_FILLED", f'<path fill="{W}" d="M2 3 H14 L9.5 8.5 V13.5 L6.5 12 V8.5 Z"/>')
    put("FONTPREVIEW", txt("Aa", 8))
    put("IMGDISPLAY", ''.join(f'<rect x="{x}" y="{y}" width="5" height="5" rx="1" {_s()}/>' for x in (2, 9) for y in (2, 9)))
    put("SHORTDISPLAY", f'<path {_s(W, 1.4)} d="M2 4 H6 M9 4 H14 M2 8 H6 M9 8 H14 M2 12 H6 M9 12 H14"/>')
    put("LONGDISPLAY", f'<path {_s(W, 1.4)} d="M2 4 H14 M2 8 H14 M2 12 H14"/>')
    put("SORT_ASC", f'<path {_s(W, 1.4)} d="M3 4 H6 M3 8 H9 M3 12 H13"/>')
    put("SORT_DESC", f'<path {_s(W, 1.4)} d="M3 4 H13 M3 8 H9 M3 12 H6"/>')
    put("SORTBYEXT", txt(".ext", 4.8))
    put("SORTSIZE", f'<rect x="2" y="9" width="3" height="5" fill="{W}"/><rect x="6.5" y="6" width="3" height="8" fill="{W}"/><rect x="11" y="2" width="3" height="12" fill="{W}"/>')
    put("PREVIEW_LOADING", f'<circle cx="8" cy="8" r="5.5" {_s()} stroke-dasharray="3 2"/>')

    # ---------------------------------------------------------------- video sequencer & image
    put("SEQ_PREVIEW", f'<rect x="1.5" y="3" width="13" height="10" rx="1" {_s()}/><path fill="{W}" d="M6.5 5.5 L10.5 8 L6.5 10.5 Z"/>')
    put("SEQ_SPLITVIEW", f'<rect x="1.5" y="3" width="13" height="10" rx="1" {_s()}/><path {_s()} d="M8 3 V13"/>')
    put("SEQ_HISTOGRAM", f'<path fill="{W}" d="M2 14 V10 H4 V6 H6 V8 H8 V4 H10 V9 H12 V11 H14 V14 Z"/>')
    put("SEQ_LUMA_WAVEFORM", f'<path {_s()} d="M2 10 L4 6 L6 11 L8 4 L10 9 L12 5 L14 8"/>')
    put("SEQ_CHROMA_SCOPE", f'<circle cx="8" cy="8" r="5.6" {_s()}/><path {_s()} d="M8 2.4 V13.6 M2.4 8 H13.6"/><circle cx="10" cy="6" r="1.4" fill="{OB}"/>')
    put("SEQ_STRIP_DUPLICATE", f'<rect x="1.5" y="3" width="9" height="4" rx="1" fill="{W}"/><rect x="5.5" y="9" width="9" height="4" rx="1" fill="{W}" fill-opacity=".6"/>')
    put("SEQ_STRIP_META", f'<rect x="1.5" y="4" width="13" height="8" rx="1.5" {_s()}/><rect x="3.5" y="6" width="5" height="4" fill="{W}"/>')
    put("SEQ_STRIP_MODIFIER", f'<rect x="1.5" y="9" width="13" height="4" rx="1" fill="{W}"/><path {_s(MO)} d="M10.5 1.5 A2 2 0 0 0 9.5 4.5 L6 8 L7 9 L10.5 5.5 A2 2 0 0 0 13 4.5 L12 4.5 L11 3.5 Z"/>')
    for k, col in (("BRIGHTNESS_CONTRAST", W), ("COLOR_BALANCE", "#e8a33d"), ("CURVES", W), ("HUE_CORRECT", "#a07ae0"),
                   ("TONEMAP", "#e8d35a"), ("WHITE_BALANCE", "#f0f0f0")):
        put(f"MOD_{k}", f'<circle cx="8" cy="8" r="5.6" {_s(col)}/><path fill="{col}" d="M8 2.4 A5.6 5.6 0 0 1 8 13.6 Z"/>')
    put("IMAGE_RGB", '<circle cx="5.5" cy="6" r="3.4" fill="#e85a5a" fill-opacity=".85"/><circle cx="10.5" cy="6" r="3.4" '
        'fill="#6cc35a" fill-opacity=".85"/><circle cx="8" cy="10.5" r="3.4" fill="#5a8ee8" fill-opacity=".85"/>')
    put("IMAGE_ALPHA", ''.join(f'<rect x="{2 + i * 3}" y="{2 + j * 3}" width="3" height="3" fill="{W}" fill-opacity="{.85 if (i + j) % 2 else .25}"/>' for i in range(4) for j in range(4)))
    put("IMAGE_RGB_ALPHA", '<circle cx="6" cy="7" r="3.6" fill="#e85a5a" fill-opacity=".8"/><circle cx="10" cy="9" r="3.6" fill="#5a8ee8" fill-opacity=".6"/>')
    put("IMAGE_ZDEPTH", '<defs><linearGradient id="z"><stop offset="0" stop-color="#000"/><stop offset="1" '
        'stop-color="#fff"/></linearGradient></defs><rect x="2" y="2" width="12" height="12" fill="url(#z)"/>')

    # ---------------------------------------------------------------- remaining modifiers / constraints
    put("MOD_CURVE_TO_TUBE", f'<path {_s(MO, 3)} d="M2 12 C5 3 11 13 14 4" opacity=".55"/><path {_s(MO)} d="M2 12 C5 3 11 13 14 4"/>')
    put("MOD_SCATTER_ON_SURFACE", f'<path {_s(MO)} d="M1.5 12 C5 9 11 9 14.5 12"/><circle cx="4" cy="8" r="1.2" fill="{MO}"/><circle cx="8" cy="6" r="1.2" fill="{MO}"/><circle cx="12" cy="8" r="1.2" fill="{MO}"/>')
    put("CON_GEOMETRYATTRIBUTE", f'<path {_s(MO)} d="M8 2 L13.5 5 V11 L8 14 L2.5 11 V5 Z"/><circle cx="8" cy="8" r="1.8" fill="{MO}"/>')
    put("OUTLINER_DATA_GP_LAYER", f'<path {_s(DA, 1.6)} d="M2 12 C5 4 9 14 14 4"/>')
    put("CHAR_NOTDEF CHAR_REPLACEMENT NOT_FOUND", f'<rect x="3" y="2" width="10" height="12" rx="1" {_s()} stroke-dasharray="2 1.5"/>' + txt("?", 7))

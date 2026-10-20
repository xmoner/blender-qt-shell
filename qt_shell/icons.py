"""Qt Shell's own icon set – small monochrome SVG icons in the style of Blender's interface
(16 × 16 grid, light grey, simple shapes). Drawn for Qt Shell, not copied from Blender.

    from . import icons
    button.setIcon(icons.icon("snap"))
    pixmap = icons.pixmap("zoom", 20)
"""
from PySide6 import QtCore, QtGui

try:
    from PySide6 import QtSvg
except Exception:          # QtSvg missing: callers fall back to their text glyphs
    QtSvg = None

FG = "#d6d6d6"
ACCENT = "#e8a33d"

S = 'fill="none" stroke="{c}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"'
F = 'fill="{c}"'

# name → SVG body (viewBox 0 0 16 16); {c} = main colour, {a} = accent colour
_ICONS = {
    # --- modes
    "object_mode": f'<path {S} d="M8 2 L13.5 5 V11 L8 14 L2.5 11 V5 Z M2.5 5 L8 8 L13.5 5 M8 8 V14"/>',
    "edit_mode": f'<path {S} d="M8 2 L13.5 5 V11 L8 14 L2.5 11 V5 Z M2.5 5 L8 8 L13.5 5 M8 8 V14"/>'
                 '<g fill="{a}"><circle cx="8" cy="2" r="1.4"/><circle cx="13.5" cy="5" r="1.4"/>'
                 '<circle cx="2.5" cy="5" r="1.4"/><circle cx="8" cy="8" r="1.4"/><circle cx="2.5" cy="11" r="1.4"/>'
                 '<circle cx="13.5" cy="11" r="1.4"/><circle cx="8" cy="14" r="1.4"/></g>',
    "sculpt_mode": f'<path {S} d="M2 12 C4 6 7 4 11 4 C13.5 4 14.5 6 13 8 C11.5 10 8 9 6.5 12 C5.8 13.6 3.6 14 2 12 Z"/>'
                   f'<circle cx="11" cy="6" r="1" {F}/>',
    "vertex_paint": f'<path {S} d="M8 2 C8 2 3.5 7.5 3.5 10.3 A4.5 4.5 0 0 0 12.5 10.3 C12.5 7.5 8 2 8 2 Z"/>'
                    '<path fill="{a}" d="M5.2 10.6 A2.8 2.8 0 0 0 10.8 10.6 Z"/>',
    "weight_paint": f'<path {S} d="M8 2 C8 2 3.5 7.5 3.5 10.3 A4.5 4.5 0 0 0 12.5 10.3 C12.5 7.5 8 2 8 2 Z"/>'
                    '<path fill="#e05050" d="M5 11 A3 3 0 0 0 8 13.6 V8.4 C6.6 9 5 9.8 5 11 Z"/>'
                    '<path fill="#4a90e2" d="M11 11 A3 3 0 0 1 8 13.6 V8.4 C9.4 9 11 9.8 11 11 Z"/>',
    "texture_paint": f'<path {S} d="M10.5 2.5 L13.5 5.5 L7 12 L4 9 Z M4 9 L2.5 13.5 L7 12"/>'
                     '<path fill="{a}" d="M2.5 13.5 L4 9 L7 12 Z"/>',
    "pose_mode": f'<circle cx="8" cy="3" r="1.6" {S}/><path {S} d="M8 4.6 V9.5 M8 9.5 L5 14 M8 9.5 L11 14 M3.5 6.5 L8 6 L12.5 6.5"/>',

    # --- header: tool settings
    "orientation": f'<circle cx="8" cy="8" r="5.6" {S}/><ellipse cx="8" cy="8" rx="2.4" ry="5.6" {S}/>'
                   f'<path {S} d="M2.4 8 H13.6"/>',
    "pivot": f'<circle cx="8" cy="8" r="5.2" {S}/><circle cx="8" cy="8" r="1.6" fill="{{a}}"/>'
             f'<path {S} d="M8 1 V3 M8 13 V15 M1 8 H3 M13 8 H15"/>',
    "snap": f'<path {S} d="M4 2.5 V8.5 A4 4 0 0 0 12 8.5 V2.5 M9.6 2.5 V8.5 A1.6 1.6 0 0 1 6.4 8.5 V2.5"/>'
            '<path fill="{a}" d="M3.4 2 H6.9 V4.4 H3.4 Z M9.1 2 H12.6 V4.4 H9.1 Z"/>',
    "proportional": f'<circle cx="8" cy="8" r="6" {S} opacity=".45"/><circle cx="8" cy="8" r="3.8" {S} opacity=".75"/>'
                    '<circle cx="8" cy="8" r="1.7" fill="{c}"/>',
    "visibility": f'<path {S} d="M1.5 8 C3.5 4.5 5.7 3.5 8 3.5 C10.3 3.5 12.5 4.5 14.5 8 C12.5 11.5 10.3 12.5 8 12.5 '
                  f'C5.7 12.5 3.5 11.5 1.5 8 Z"/><circle cx="8" cy="8" r="2.2" fill="{{c}}"/>',
    "gizmo": f'<path {S} d="M8 8 V2.5 M8 8 L13 10.5 M8 8 L3 10.5"/>'
             '<path fill="#5aa0ff" d="M8 1 L9.6 3.6 H6.4 Z"/><path fill="#ff5a6e" d="M14.4 11.2 L11.4 11.6 L12.8 8.9 Z"/>'
             '<path fill="#8bdc3a" d="M1.6 11.2 L3.2 8.9 L4.6 11.6 Z"/>',
    "overlays": f'<circle cx="6" cy="8" r="4.2" {S}/><circle cx="10" cy="8" r="4.2" {S}/>',
    "xray": f'<rect x="2" y="2" width="9" height="9" rx="1" {S}/>'
            '<rect x="5" y="5" width="9" height="9" rx="1" fill="{c}" fill-opacity=".35" stroke="{c}" stroke-width="1.2"/>',
    "layout": f'<rect x="2" y="2.5" width="12" height="11" rx="1.2" {S}/><path {S} d="M8 2.5 V13.5 M2 8 H14"/>',

    # --- shading
    "shading_wire": f'<circle cx="8" cy="8" r="5.8" {S}/><ellipse cx="8" cy="8" rx="5.8" ry="2.2" {S}/>'
                    f'<ellipse cx="8" cy="8" rx="2.2" ry="5.8" {S}/>',
    "shading_solid": '<circle cx="8" cy="8" r="5.8" fill="{c}"/>',
    "shading_material": f'<circle cx="8" cy="8" r="5.8" {S}/><path fill="{{c}}" d="M8 2.2 A5.8 5.8 0 0 1 8 13.8 Z"/>'
                        '<path fill="{c}" fill-opacity=".45" d="M5 4 h1.5 v1.5 h-1.5z M3.5 7 h1.5 v1.5 h-1.5z '
                        'M5 10 h1.5 v1.5 h-1.5z"/>',
    "shading_rendered": '<circle cx="8" cy="8" r="5.8" fill="{c}" fill-opacity=".9"/>'
                        '<circle cx="6" cy="6" r="2" fill="#ffffff" fill-opacity=".85"/>',

    # --- edit mode select modes
    "select_vert": f'<path {S} d="M3 13 V5 L11 3 L13 11 Z" opacity=".55"/><circle cx="11" cy="3" r="2" fill="{{a}}"/>',
    "select_edge": f'<path {S} d="M3 13 V5 L11 3 L13 11 Z" opacity=".55"/>'
                   '<path d="M11 3 L13 11" stroke="{a}" stroke-width="2.4" stroke-linecap="round"/>',
    "select_face": f'<path {S} d="M3 13 V5 L11 3 L13 11 Z"/><path fill="{{a}}" fill-opacity=".85" d="M3 13 V5 L11 3 L13 11 Z"/>',

    # --- tools
    "tool_select": '<rect x="2" y="2" width="10" height="10" fill="none" stroke="{c}" stroke-width="1.2" '
                   'stroke-dasharray="2 1.6"/><path fill="{c}" d="M8 8 L14.5 10.4 L11.6 11.3 L13.9 13.9 L13 14.8 '
                   'L10.6 12.2 L9.6 15 Z"/>',
    "tool_move": f'<path {S} d="M8 1.5 V14.5 M1.5 8 H14.5"/>'
                 '<path fill="{c}" d="M8 0.8 L10 3.4 H6 Z M8 15.2 L6 12.6 H10 Z M0.8 8 L3.4 6 V10 Z M15.2 8 L12.6 10 V6 Z"/>',
    "tool_rotate": f'<path {S} d="M13 8 A5 5 0 1 1 10.5 3.7"/><path fill="{{c}}" d="M9.3 1.4 L13.2 3.6 L9.6 6 Z"/>',
    "tool_scale": f'<rect x="2" y="7" width="7" height="7" rx="1" {S}/><path {S} d="M7 9 L13.5 2.5"/>'
                  '<path fill="{c}" d="M14.5 1.5 V6.4 L9.6 1.5 Z"/>',
    "tool_transform": f'<rect x="4.5" y="4.5" width="7" height="7" rx="1" {S}/><path {S} d="M8 0.8 V3 M8 13 V15.2 M0.8 8 H3 M13 8 H15.2"/>'
                      '<circle cx="8" cy="8" r="1.4" fill="{a}"/>',

    # --- navigation
    "zoom": f'<circle cx="6.8" cy="6.8" r="4.6" {S}/><path d="M10.3 10.3 L14.4 14.4" stroke="{{c}}" stroke-width="2.2" '
            'stroke-linecap="round"/>',
    "pan": f'<path {S} d="M5 14 C3.2 12 2.6 10.4 3.2 9.6 C3.8 8.9 4.8 9.4 5.4 10.4 V3.6 A0.9 0.9 0 0 1 7.2 3.6 V8 '
           f'V2.6 A0.9 0.9 0 0 1 9 2.6 V8 V3.4 A0.9 0.9 0 0 1 10.8 3.4 V8.4 V5 A0.9 0.9 0 0 1 12.6 5 V10 '
           f'C12.6 12.4 11.6 14 9.6 14 Z"/>',
    "camera": f'<rect x="1.5" y="5" width="9.5" height="7" rx="1.2" {S}/><path {S} d="M11 7.4 L14.5 5.5 V11.5 L11 9.6"/>'
              f'<circle cx="4" cy="3.5" r="1.5" {S}/><circle cx="7.8" cy="3.5" r="1.5" {S}/>',
    "perspective": f'<path {S} d="M5 3 H11 L14.5 13 H1.5 Z M8 3 V13 M3.3 8 H12.7"/>',
    "orthographic": f'<rect x="2" y="2.5" width="12" height="11" {S}/><path {S} d="M8 2.5 V13.5 M2 8 H14"/>',

    # --- timeline
    "jump_start": '<path fill="{c}" d="M3 3 H4.6 V13 H3 Z M13 3 V13 L5.4 8 Z"/>',
    "jump_end": '<path fill="{c}" d="M11.4 3 H13 V13 H11.4 Z M3 3 V13 L10.6 8 Z"/>',
    "key_prev": '<path fill="{c}" d="M9.5 3 V13 L2.5 8 Z"/><path fill="{a}" d="M12 5 L14.5 8 L12 11 L9.5 8 Z"/>',
    "key_next": '<path fill="{c}" d="M6.5 3 V13 L13.5 8 Z"/><path fill="{a}" d="M4 5 L6.5 8 L4 11 L1.5 8 Z"/>',
    "play": '<path fill="{c}" d="M4 2.5 L13.5 8 L4 13.5 Z"/>',
    "pause": '<path fill="{c}" d="M4 2.8 H6.8 V13.2 H4 Z M9.2 2.8 H12 V13.2 H9.2 Z"/>',
    "keyframe": '<path fill="{a}" stroke="{c}" stroke-width="1" d="M8 2 L14 8 L8 14 L2 8 Z"/>',
    "key_delete": '<path fill="none" stroke="{c}" stroke-width="1.2" d="M8 2 L14 8 L8 14 L2 8 Z"/>'
                  '<path stroke="#ff6060" stroke-width="1.6" stroke-linecap="round" d="M5.5 5.5 L10.5 10.5 M10.5 5.5 L5.5 10.5"/>',
    "record": '<circle cx="8" cy="8" r="5" fill="#e04848"/>',
}


def svg(name, color=FG, accent=ACCENT):
    body = _ICONS[name].replace("{c}", color).replace("{a}", accent).replace("{{c}}", color).replace("{{a}}", accent)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">{body}</svg>'


def names():
    return list(_ICONS)


_cache = {}


def pixmap(name, size=16, color=FG, accent=ACCENT, dpr=None):
    """The icon rendered at size × size logical pixels (sharp on HiDPI screens)."""
    if QtSvg is None or name not in _ICONS:
        return None
    app = QtGui.QGuiApplication.instance()
    dpr = dpr or (app.devicePixelRatio() if app else 1.0)
    key = (name, size, color, accent, dpr)
    pm = _cache.get(key)
    if pm is None:
        px = max(1, int(round(size * dpr)))
        img = QtGui.QImage(px, px, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.transparent)
        r = QtSvg.QSvgRenderer(QtCore.QByteArray(svg(name, color, accent).encode()))
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r.render(p)
        p.end()
        pm = QtGui.QPixmap.fromImage(img)
        pm.setDevicePixelRatio(dpr)
        _cache[key] = pm
    return pm


def icon(name, size=16):
    """QIcon with a normal, a disabled (dimmed) and a checked (white) look; a null QIcon if unknown."""
    ic = QtGui.QIcon()
    if QtSvg is None or name not in _ICONS:
        return ic
    for sz in (size, size * 2):
        ic.addPixmap(pixmap(name, sz), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        ic.addPixmap(pixmap(name, sz, color="#ffffff"), QtGui.QIcon.Normal, QtGui.QIcon.On)
        ic.addPixmap(pixmap(name, sz, color="#ffffff"), QtGui.QIcon.Active, QtGui.QIcon.Off)
        ic.addPixmap(pixmap(name, sz, color="#6c6c6c", accent="#7a6a50"), QtGui.QIcon.Disabled, QtGui.QIcon.Off)
    return ic


def set_icon(button, name, keep_text=None):
    """Gives a QToolButton / QPushButton the icon; keep_text: text shown beside it (e.g. '▾'), else icon only.
    Returns False (and leaves the button unchanged) when the icon cannot be drawn."""
    ic = icon(name)
    if ic.isNull():
        return False
    button.setIcon(ic)
    from . import theme
    button.setIconSize(QtCore.QSize(theme.px(16), theme.px(16)))
    if keep_text:
        button.setText(keep_text)
        try:
            button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        except AttributeError:
            pass
    else:
        button.setText("")
    return True

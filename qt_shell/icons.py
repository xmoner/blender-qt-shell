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
    # sidebar toggle: a frame with a panel on the right
    "sidebar": '<rect x="1.5" y="2.5" width="13" height="11" rx="1.2" fill="none" stroke="{c}" stroke-width="1.2"/>'
               '<rect x="10" y="3.2" width="4" height="9.6" fill="{c}" fill-opacity=".55"/>',
    # select variants (the arrow = the same pointer as in tool_select)
    "tool_tweak": '<path fill="{c}" d="M4 1.5 L12.2 8.8 L8.4 9.2 L10.9 13.9 L9.2 14.8 L6.8 10.1 L4 12.8 Z"/>',
    "tool_select_circle": '<circle cx="7" cy="7" r="5.2" fill="none" stroke="{c}" stroke-width="1.2" '
                          'stroke-dasharray="2 1.6"/><path fill="{c}" d="M8 8 L14.5 10.4 L11.6 11.3 L13.9 13.9 '
                          'L13 14.8 L10.6 12.2 L9.6 15 Z"/>',
    "tool_select_lasso": '<path fill="none" stroke="{c}" stroke-width="1.2" stroke-dasharray="2 1.6" '
                         'd="M3 9 C0.8 6 2.5 2 7 2 C11 2 13 4 12 6.5 C11.4 8 9 8 7.5 7.6 C5.5 7 4.5 10 3 9 Z"/>'
                         '<path fill="{c}" d="M8 8 L14.5 10.4 L11.6 11.3 L13.9 13.9 L13 14.8 L10.6 12.2 L9.6 15 Z"/>',
    # 3D cursor: red / white ring with a cross (like Blender's)
    "tool_cursor": '<circle cx="8" cy="8" r="4.6" fill="none" stroke="#ffffff" stroke-width="1.6"/>'
                   '<circle cx="8" cy="8" r="4.6" fill="none" stroke="#e84a4a" stroke-width="1.6" '
                   'stroke-dasharray="3.6 3.6"/><path fill="none" stroke="{c}" stroke-width="1.1" '
                   'd="M8 0.8 V5 M8 11 V15.2 M0.8 8 H5 M11 8 H15.2"/>',
    # scale cage: dashed box with square handles on corners and sides
    "tool_scale_cage": '<rect x="3" y="3" width="10" height="10" fill="none" stroke="{c}" stroke-width="1" '
                       'stroke-dasharray="1.6 1.4"/><g fill="{c}"><rect x="1.5" y="1.5" width="3" height="3"/>'
                       '<rect x="11.5" y="1.5" width="3" height="3"/><rect x="1.5" y="11.5" width="3" height="3"/>'
                       '<rect x="11.5" y="11.5" width="3" height="3"/></g><g fill="{a}">'
                       '<rect x="6.6" y="1.6" width="2.8" height="2.8"/><rect x="11.6" y="6.6" width="2.8" height="2.8"/>'
                       '<rect x="6.6" y="11.6" width="2.8" height="2.8"/><rect x="1.6" y="6.6" width="2.8" height="2.8"/></g>',

    # annotate: a pencil with its stroke (Annotate / Line / Polygon / Eraser)
    "tool_annotate": '<path fill="none" stroke="{a}" stroke-width="1.3" stroke-linecap="round" '
                     'd="M1.5 13.5 C3 11 4.5 14.5 6.5 12.5"/><path fill="none" stroke="{c}" stroke-width="1.2" '
                     'stroke-linejoin="round" d="M7.5 11.5 L14 5 L12 3 L5.5 9.5 Z M5.5 9.5 L4.8 12.2 L7.5 11.5"/>',
    "tool_annotate_line": '<path fill="none" stroke="{a}" stroke-width="1.3" stroke-linecap="round" d="M1.5 14 L7 8.5"/>'
                          '<circle cx="1.8" cy="13.8" r="1.1" fill="{a}"/><path fill="none" stroke="{c}" '
                          'stroke-width="1.2" stroke-linejoin="round" d="M9.5 9.5 L15 4 L13 2 L7.5 7.5 Z '
                          'M7.5 7.5 L6.8 10.2 L9.5 9.5"/>',
    "tool_annotate_polygon": '<path fill="none" stroke="{a}" stroke-width="1.3" stroke-linejoin="round" '
                             'd="M1.5 14.5 L2.5 8 L6.5 10.5 L4.5 14.5 Z"/><g fill="{a}"><circle cx="1.5" cy="14.5" '
                             'r="1"/><circle cx="2.5" cy="8" r="1"/><circle cx="6.5" cy="10.5" r="1"/></g>'
                             '<path fill="none" stroke="{c}" stroke-width="1.2" stroke-linejoin="round" '
                             'd="M10 9 L15 4 L13 2 L8 7 Z M8 7 L7.3 9.7 L10 9"/>',
    "tool_annotate_eraser": '<path fill="none" stroke="{c}" stroke-width="1.2" stroke-linejoin="round" '
                            'd="M2 10.5 L8.5 4 L13 8.5 L8 13.5 H5 Z M5.2 7.3 L9.7 11.8"/>'
                            '<path fill="{a}" d="M2 10.5 L5.2 7.3 L9.7 11.8 L8 13.5 H5 Z"/>'
                            '<path fill="none" stroke="{c}" stroke-width="1.1" stroke-linecap="round" d="M9 14.5 H15"/>',
    # measure: a ruler lying diagonally with ticks
    "tool_measure": '<path fill="none" stroke="{c}" stroke-width="1.2" stroke-linejoin="round" '
                    'd="M1.5 11 L11 1.5 L14.5 5 L5 14.5 Z"/><path fill="none" stroke="{c}" stroke-width="1" '
                    'stroke-linecap="round" d="M4 8.5 L5.6 10.1 M6 6.5 L7 7.5 M8 4.5 L9.6 6.1 M10 2.5 L11 3.5"/>'
                    '<circle cx="3.2" cy="12.8" r="1" fill="{a}"/>',
    # add primitive tools: the shape plus a small accent "+"
    "tool_add_cube": '<path fill="none" stroke="{c}" stroke-width="1.2" stroke-linejoin="round" '
                     'd="M7 4 L12 6.5 V12 L7 14.5 L2 12 V6.5 Z M2 6.5 L7 9 L12 6.5 M7 9 V14.5"/>'
                     '<path fill="none" stroke="{a}" stroke-width="1.4" stroke-linecap="round" d="M13 0.8 V5.2 M10.8 3 H15.2"/>',
    "tool_add_cone": '<path fill="none" stroke="{c}" stroke-width="1.2" stroke-linejoin="round" '
                     'd="M7 3.5 L12 12 M7 3.5 L2 12"/><ellipse cx="7" cy="12" rx="5" ry="2" fill="none" '
                     'stroke="{c}" stroke-width="1.2"/><path fill="none" stroke="{a}" stroke-width="1.4" '
                     'stroke-linecap="round" d="M13 0.8 V5.2 M10.8 3 H15.2"/>',
    "tool_add_cylinder": '<ellipse cx="7" cy="5.5" rx="5" ry="2" fill="none" stroke="{c}" stroke-width="1.2"/>'
                         '<path fill="none" stroke="{c}" stroke-width="1.2" d="M2 5.5 V12.5 A5 2 0 0 0 12 12.5 V5.5"/>'
                         '<path fill="none" stroke="{a}" stroke-width="1.4" stroke-linecap="round" '
                         'd="M13 0.8 V5.2 M10.8 3 H15.2"/>',
    "tool_add_uvsphere": '<circle cx="7" cy="9" r="5.5" fill="none" stroke="{c}" stroke-width="1.2"/>'
                         '<ellipse cx="7" cy="9" rx="5.5" ry="2" fill="none" stroke="{c}" stroke-width="1"/>'
                         '<ellipse cx="7" cy="9" rx="2.2" ry="5.5" fill="none" stroke="{c}" stroke-width="1"/>'
                         '<path fill="none" stroke="{a}" stroke-width="1.4" stroke-linecap="round" '
                         'd="M13 0.8 V5.2 M10.8 3 H15.2"/>',
    "tool_add_icosphere": '<path fill="none" stroke="{c}" stroke-width="1.1" stroke-linejoin="round" '
                          'd="M7 3.5 L12 6.3 V11.7 L7 14.5 L2 11.7 V6.3 Z M7 3.5 L4.5 9.6 L9.5 9.6 Z M4.5 9.6 L2 6.3 '
                          'M4.5 9.6 L2 11.7 M4.5 9.6 L7 14.5 L9.5 9.6 L12 11.7 M9.5 9.6 L12 6.3"/>'
                          '<path fill="none" stroke="{a}" stroke-width="1.4" stroke-linecap="round" '
                          'd="M13 0.8 V5.2 M10.8 3 H15.2"/>',
    # sample: an eyedropper
    "tool_sample": '<path fill="none" stroke="{c}" stroke-width="1.2" stroke-linejoin="round" '
                   'd="M9 4.5 L11.5 7 L5 13.5 L2.5 14 L3 11.5 Z"/><path fill="{c}" d="M9.5 3.5 L11.8 1.2 '
                   'C12.6 0.4 13.8 0.4 14.6 1.2 C15.4 2 15.4 3.2 14.6 4 L12.3 6.3 L13 7 L12 8 L8 4 L9 3 Z"/>'
                   '<path fill="{a}" d="M3 11.5 L5.8 8.7 L7.2 10.1 L4.6 12.7 Z"/>',
    # toolbar toggle: a frame with a panel of tools on the left
    # dock: a window frame with a panel docked at its bottom
    "dock": '<rect x="1.5" y="2.5" width="13" height="11" rx="1.2" fill="none" stroke="{c}" stroke-width="1.2"/>'
            '<rect x="2.2" y="8.6" width="11.6" height="4.2" fill="{a}" fill-opacity=".85"/>'
            '<path fill="none" stroke="{c}" stroke-width="1.1" stroke-linecap="round" d="M8 3.8 V7 M6.4 5.6 L8 7.2 L9.6 5.6"/>',
    "toolbar": '<rect x="1.5" y="2.5" width="13" height="11" rx="1.2" fill="none" stroke="{c}" stroke-width="1.2"/>'
               '<rect x="2.2" y="3.2" width="4" height="9.6" fill="{c}" fill-opacity=".55"/>',

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
    "play_reverse": '<path fill="{c}" d="M12 2.5 L2.5 8 L12 13.5 Z"/>',
    "frame_prev": '<path fill="{c}" d="M3 3 H4.6 V13 H3 Z M12.5 3 V13 L5.5 8 Z"/>',
    "frame_next": '<path fill="{c}" d="M11.4 3 H13 V13 H11.4 Z M3.5 3 V13 L10.5 8 Z"/>',
    "preview_range": '<circle cx="8" cy="8" r="5.6" fill="none" stroke="{c}" stroke-width="1.2"/>'
                     '<path fill="none" stroke="{a}" stroke-width="1.4" stroke-linecap="round" d="M8 4.6 V8 L10.4 9.6"/>',
    "loop_continuous": '<path fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" '
                       'd="M3 9.5 V7.5 A2.5 2.5 0 0 1 5.5 5 H12 M13 6.5 V8.5 A2.5 2.5 0 0 1 10.5 11 H4"/>'
                       '<path fill="{c}" d="M11 3 L13.8 5 L11 7 Z M5 9 L2.2 11 L5 13 Z"/>',
    "loop_once": '<path fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" d="M2.5 8 H10.5"/>'
                 '<path fill="{c}" d="M10 5 L13.5 8 L10 11 Z"/><path fill="{a}" d="M13.6 3.5 H15 V12.5 H13.6 Z"/>',
    "loop_oscillate": '<path fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" d="M4.5 6 H11.5 M4.5 10 H11.5"/>'
                      '<path fill="{c}" d="M11 3.5 L14 6 L11 8.5 Z M5 7.5 L2 10 L5 12.5 Z"/>',
    "marker": '<path fill="{c}" d="M4.5 3 H11.5 V9.5 L8 13 L4.5 9.5 Z"/>',
    "keyframe": '<path fill="{a}" stroke="{c}" stroke-width="1" d="M8 2 L14 8 L8 14 L2 8 Z"/>',
    "key_delete": '<path fill="none" stroke="{c}" stroke-width="1.2" d="M8 2 L14 8 L8 14 L2 8 Z"/>'
                  '<path stroke="#ff6060" stroke-width="1.6" stroke-linecap="round" d="M5.5 5.5 L10.5 10.5 M10.5 5.5 L5.5 10.5"/>',
    "record": '<circle cx="8" cy="8" r="5" fill="#e04848"/>',
    # --- Blue Pencil (bluepencil.py)
    "tool_blue_pencil": '<path fill="#5aa0ff" d="M10.6 2.2 L13.8 5.4 L6 13.2 L2.2 13.8 L2.8 10 Z"/>'
                        '<path fill="none" stroke="#1d3d66" stroke-width="0.9" d="M9.4 3.4 L12.6 6.6"/>'
                        '<path fill="#f0d8b0" d="M2.8 10 L6 13.2 L2.2 13.8 Z"/>',
    "bp_pencil": '<path fill="none" stroke="{c}" stroke-width="1.2" stroke-linejoin="round" '
                 'd="M10.6 2.2 L13.8 5.4 L6 13.2 L2.2 13.8 L2.8 10 Z M9.2 3.6 L12.4 6.8"/>',
    "bp_brush": '<path fill="{c}" d="M13.6 1.8 C14.4 2.6 10.6 7.6 8.6 9.2 L6.8 7.4 C8.4 5.4 12.8 1 13.6 1.8 Z"/>'
                '<path fill="#5aa0ff" d="M6.2 8.2 L7.8 9.8 C7.6 12.6 5 14.4 1.8 14 C3.6 12.6 3 9 6.2 8.2 Z"/>',
    "bp_eraser": '<path fill="none" stroke="{c}" stroke-width="1.2" stroke-linejoin="round" '
                 'd="M9.6 2.4 L14 6.8 L7.6 13.2 H4.4 L2 10.8 Z M5.6 6.4 L10 10.8 M7.6 13.2 H14"/>',
    "bp_text": '<path fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round" '
               'd="M3 3.5 H13 M8 3.5 V13.5 M6 13.5 H10"/>',
    "bp_line": '<path fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round" d="M2.5 13.5 L13.5 2.5"/>',
    "bp_arrow": '<path fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round" d="M2.5 13.5 L12 4"/>'
                '<path fill="{c}" d="M14 2 L13 8 L8 3 Z"/>',
    "bp_ellipse": '<ellipse cx="8" cy="8" rx="6" ry="4.5" fill="none" stroke="{c}" stroke-width="1.4"/>',
    "bp_rect": '<rect x="2.2" y="3.5" width="11.6" height="9" fill="none" stroke="{c}" stroke-width="1.4"/>',
    "bp_transform": '<rect x="3" y="3" width="10" height="10" fill="none" stroke="{c}" stroke-width="1" '
                    'stroke-dasharray="1.8 1.4"/><g fill="{c}"><rect x="1.5" y="1.5" width="3" height="3"/>'
                    '<rect x="11.5" y="1.5" width="3" height="3"/><rect x="1.5" y="11.5" width="3" height="3"/>'
                    '<rect x="11.5" y="11.5" width="3" height="3"/></g>',
    "bp_frame_prev": '<path fill="{c}" d="M3 3 H4.6 V13 H3 Z"/><rect x="6.5" y="4.5" width="7" height="7" rx="1.2" '
                     'fill="#5aa0ff"/>',
    "bp_frame_next": '<rect x="2.5" y="4.5" width="7" height="7" rx="1.2" fill="#5aa0ff"/>'
                     '<path fill="{c}" d="M11.4 3 H13 V13 H11.4 Z"/>',
    "bp_frame_insert": '<rect x="2.5" y="4" width="8" height="8" rx="1.2" fill="none" stroke="#5aa0ff" stroke-width="1.3"/>'
                       '<path fill="none" stroke="{c}" stroke-width="1.4" d="M12.5 5.5 V10.5 M10 8 H15"/>',
    "bp_frame_dup": '<rect x="1.8" y="2.5" width="7.5" height="7.5" rx="1.2" fill="#5aa0ff" opacity="0.55"/>'
                    '<rect x="6.5" y="6" width="7.5" height="7.5" rx="1.2" fill="#5aa0ff"/>',
    "bp_frame_delete": '<rect x="2.5" y="4" width="8" height="8" rx="1.2" fill="#5aa0ff"/>'
                       '<path fill="none" stroke="#ff5a5a" stroke-width="1.5" d="M11 4.5 L15 8.5 M15 4.5 L11 8.5"/>',
    "bp_cut": '<circle cx="4.5" cy="12" r="2.2" fill="none" stroke="{c}" stroke-width="1.2"/>'
              '<circle cx="11.5" cy="12" r="2.2" fill="none" stroke="{c}" stroke-width="1.2"/>'
              '<path fill="none" stroke="{c}" stroke-width="1.2" d="M5.8 10.3 L11.5 2 M10.2 10.3 L4.5 2"/>',
    "bp_copy": '<rect x="2" y="2" width="8" height="9" rx="1" fill="none" stroke="{c}" stroke-width="1.2"/>'
               '<rect x="6" y="5" width="8" height="9" rx="1" fill="#303030" stroke="{c}" stroke-width="1.2"/>',
    "bp_paste": '<rect x="3" y="3" width="10" height="11" rx="1" fill="none" stroke="{c}" stroke-width="1.2"/>'
                '<rect x="5.5" y="1.6" width="5" height="3" rx="0.8" fill="{c}"/>'
                '<path fill="none" stroke="#5aa0ff" stroke-width="1.2" d="M5.5 8 H10.5 M5.5 10.5 H9"/>',
    "bp_color_custom": '<path fill="#ff4d4d" d="M8 8 L8 1.5 A6.5 6.5 0 0 1 14.5 8 Z"/>'
                       '<path fill="#ffd60a" d="M8 8 L14.5 8 A6.5 6.5 0 0 1 8 14.5 Z"/>'
                       '<path fill="#34c759" d="M8 8 L8 14.5 A6.5 6.5 0 0 1 1.5 8 Z"/>'
                       '<path fill="#2f7bff" d="M8 8 L1.5 8 A6.5 6.5 0 0 1 8 1.5 Z"/>'
                       '<circle cx="8" cy="8" r="2.2" fill="#ffffff"/>',
    "bp_layer_new": '<path fill="none" stroke="{c}" stroke-width="1.2" stroke-linejoin="round" '
                    'd="M8 3 L14 6 L8 9 L2 6 Z M2 9 L8 12 L11 10.5"/>'
                    '<path fill="none" stroke="#5aa0ff" stroke-width="1.5" d="M13 9.5 V14.5 M10.5 12 H15.5"/>',
    "render_cancel": '<circle cx="8" cy="8" r="6.2" fill="#c84646"/>'
                     '<path stroke="#ffffff" stroke-width="1.8" stroke-linecap="round" fill="none" '
                     'd="M5.6 5.6 L10.4 10.4 M10.4 5.6 L5.6 10.4"/>',
}


# --- Outliner (v0.31): data-block shapes – drawn in one colour, the Outliner tints them by role
#     (object = orange, object data = green, modifier = blue, …, see outliner._TINT)
SL = 'fill="none" stroke="{c}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'
_ICONS.update({
    # object types
    "mesh": f'<path {S} d="M8 3 L13 12.5 H3 Z"/><path fill="{{c}}" fill-opacity=".25" d="M8 3 L13 12.5 H3 Z"/>'
            '<g fill="{c}"><rect x="6.6" y="1.6" width="2.8" height="2.8" rx=".4"/>'
            '<rect x="11.6" y="11.1" width="2.8" height="2.8" rx=".4"/><rect x="1.6" y="11.1" width="2.8" height="2.8" rx=".4"/></g>',
    "curve": f'<path {S} d="M3 13 C3 6 13 10 13 3"/><path {S} d="M3 13 L7 9.5 M13 3 L9 6.5" opacity=".55"/>'
             '<g fill="{c}"><circle cx="3" cy="13" r="1.6"/><circle cx="13" cy="3" r="1.6"/>'
             '<circle cx="7" cy="9.5" r="1.1"/><circle cx="9" cy="6.5" r="1.1"/></g>',
    "surface": f'<path {S} d="M2.5 5 C6 3 10 7 13.5 4.5 V11.5 C10 14 6 10 2.5 12 Z"/>'
               f'<path {S} opacity=".55" d="M2.5 8.5 C6 6.5 10 10.5 13.5 8 M8 5.3 V11.6"/>',
    "font": f'<path {SL} d="M3.5 3.5 H12.5 M8 3.5 V13 M6 13 H10 M3.5 3.5 V5 M12.5 3.5 V5"/>',
    "meta": f'<circle cx="6" cy="9.5" r="3.6" {S}/><circle cx="10.6" cy="5.8" r="2.8" {S}/>'
            '<circle cx="6" cy="9.5" r="3.6" fill="{c}" fill-opacity=".25"/>',
    "armature": f'<circle cx="8" cy="3.2" r="1.8" {S}/><path {S} d="M8 5 V9.6 M8 9.6 L5.2 14 M8 9.6 L10.8 14 '
                f'M3.4 7.4 L8 6.4 L12.6 7.4"/>',
    "bone": f'<path {S} d="M5.4 10.6 L10.6 5.4"/><circle cx="4" cy="12" r="2" {S}/><circle cx="12" cy="4" r="2" {S}/>'
            '<path fill="{c}" fill-opacity=".35" d="M4.6 9.6 L9.6 4.6 L11.4 6.4 L6.4 11.4 Z"/>',
    "lattice": f'<path {S} d="M3 4 L11 2.5 L13.5 11.5 L5 13.5 Z M7 3.25 L9.25 12.5 M4 8.75 L12.25 7"/>',
    "empty": f'<path {S} d="M8 8 V2.2 M8 8 L13.2 11 M8 8 L2.8 11"/><circle cx="8" cy="8" r="1.4" fill="{{c}}"/>',
    "camera_ob": f'<rect x="1.8" y="5" width="8.6" height="7" rx="1" {S}/><path {S} d="M10.4 7.3 L14.2 5.2 V11.8 L10.4 9.7"/>'
                 '<path fill="{c}" d="M4 2.8 H8.2 L9 5 H3.2 Z"/>',
    "light": f'<path {S} d="M8 1.8 A4.1 4.1 0 0 1 10.6 9 V11 H5.4 V9 A4.1 4.1 0 0 1 8 1.8 Z M6 13.6 H10"/>'
             '<path fill="{c}" fill-opacity=".3" d="M8 1.8 A4.1 4.1 0 0 1 10.6 9 V11 H5.4 V9 A4.1 4.1 0 0 1 8 1.8 Z"/>',
    "speaker": f'<path {S} d="M2.5 6 H5 L9 3 V13 L5 10 H2.5 Z M11.2 5.6 C12.3 6.8 12.3 9.2 11.2 10.4 '
               f'M13 4 C14.9 6 14.9 10 13 12"/>',
    "lightprobe": f'<circle cx="8" cy="8" r="5.4" {S}/><circle cx="8" cy="8" r="2" fill="{{c}}"/>'
                  f'<path {S} opacity=".55" d="M8 2.6 V5 M8 11 V13.4 M2.6 8 H5 M11 8 H13.4"/>',
    "gpencil": f'<path {S} d="M1.8 12.5 C3.8 8.5 5.8 13.5 7.8 9.5 C9 7.2 10 8.2 10.8 7"/>'
               f'<path {S} d="M10.6 3.2 L13.6 6.2 L11.6 8.2 L8.6 5.2 Z"/><path fill="{{c}}" d="M10.6 3.2 L12 1.8 L15 4.8 L13.6 6.2 Z"/>',
    "hair": f'<path {S} d="M4 13.5 C4 9.5 6 7.5 5 2.5 M8 13.5 C8 9.5 10 7.5 9 2.5 M12 13.5 C12 9.5 14 7.5 13 2.5"/>',
    "pointcloud": '<g fill="{c}"><circle cx="4" cy="5" r="1.3"/><circle cx="8.5" cy="3.5" r="1.3"/><circle cx="12" cy="6.5" r="1.3"/>'
                  '<circle cx="6.5" cy="8.5" r="1.3"/><circle cx="10.5" cy="10.5" r="1.3"/><circle cx="4.5" cy="12" r="1.3"/>'
                  '<circle cx="12.5" cy="13" r="1.1"/></g>',
    "volume": f'<path {S} d="M4.6 12.8 A3 3 0 0 1 4.1 6.9 A3.7 3.7 0 0 1 11 5.6 A3.3 3.3 0 0 1 11.6 12.8 Z"/>'
              '<path fill="{c}" fill-opacity=".25" d="M4.6 12.8 A3 3 0 0 1 4.1 6.9 A3.7 3.7 0 0 1 11 5.6 A3.3 3.3 0 0 1 11.6 12.8 Z"/>',
    # object contents
    "material": f'<circle cx="8" cy="8" r="5.6" {S}/><path fill="{{c}}" d="M13.6 8 A5.6 5.6 0 0 1 8 13.6 A5.6 5.6 0 0 1 2.4 8 Z"/>'
                '<circle cx="6" cy="5.6" r="1.3" fill="{c}" fill-opacity=".6"/>',
    "modifier": f'<path {S} d="M10.8 2.2 A3.1 3.1 0 0 0 7.5 6.3 L2.6 11.2 A1.3 1.3 0 0 0 4.8 13.4 L9.7 8.5 '
                f'A3.1 3.1 0 0 0 13.8 5.2 L11.7 7.3 L9.5 6.5 L8.7 4.3 Z"/>',
    "constraint": f'<path {S} d="M7.2 10.9 L5.6 12.5 A2.3 2.3 0 0 1 2.4 9.3 L4.9 6.8 A2.3 2.3 0 0 1 8.1 6.8"/>'
                  f'<path {S} d="M8.8 5.1 L10.4 3.5 A2.3 2.3 0 0 1 13.6 6.7 L11.1 9.2 A2.3 2.3 0 0 1 7.9 9.2"/>',
    "vgroup": f'<path {S} opacity=".5" d="M3 12.5 L8 3.5 L13 12.5 Z"/>'
              '<g fill="{c}"><circle cx="8" cy="3.5" r="1.6"/><circle cx="3" cy="12.5" r="1.6"/><circle cx="13" cy="12.5" r="1.6"/>'
              '<circle cx="8" cy="9.6" r="1.6"/></g>',
    "action": f'<path {S} opacity=".5" d="M1.2 8 H14.8"/>'
              '<path fill="{c}" d="M4.6 4.8 L7.8 8 L4.6 11.2 L1.4 8 Z"/>'
              f'<path {S} d="M11.4 4.8 L14.6 8 L11.4 11.2 L8.2 8 Z"/>',
    "fcurve": f'<path {S} d="M1.8 12.5 C5 12.5 5.6 3.5 8.6 3.5 C11 3.5 11.6 9.5 14.2 9.5"/>'
              '<g fill="{c}"><circle cx="1.8" cy="12.5" r="1.3"/><circle cx="8.6" cy="3.5" r="1.3"/><circle cx="14.2" cy="9.5" r="1.3"/></g>',
    "image": f'<rect x="1.8" y="2.8" width="12.4" height="10.4" rx="1" {S}/>'
             f'<path {S} d="M2.4 11.6 L6 8 L8.6 10.6 L10.6 8.6 L13.6 11.6"/><circle cx="10.6" cy="5.8" r="1.3" fill="{{c}}"/>',
    "texture": f'<rect x="2.5" y="2.5" width="11" height="11" rx=".6" {S}/>'
               '<path fill="{c}" fill-opacity=".75" d="M2.5 2.5 H8 V8 H2.5 Z M8 8 H13.5 V13.5 H8 Z"/>',
    "world": f'<circle cx="8" cy="8" r="5.8" {S}/><ellipse cx="8" cy="8" rx="2.5" ry="5.8" {S}/>'
             f'<path {S} d="M2.4 6 H13.6 M2.4 10 H13.6"/>',
    "nodetree": f'<rect x="1.5" y="2.5" width="5" height="4.5" rx=".9" {S}/><rect x="9.5" y="9" width="5" height="4.5" rx=".9" {S}/>'
                f'<path {S} d="M6.5 4.75 C9.5 4.75 6.5 11.25 9.5 11.25"/>',
    "text": f'<path {S} d="M3.5 1.8 H10 L12.5 4.3 V14.2 H3.5 Z M10 1.8 V4.3 H12.5"/>'
            f'<path {S} opacity=".7" d="M5.6 7 H10.4 M5.6 9.4 H10.4 M5.6 11.8 H8.8"/>',
    "library": f'<path {S} d="M2.5 3 V13.5 M5.5 3 V13.5 M2.5 3 H5.5 M2.5 13.5 H5.5 M8 4.2 L10.8 3.4 L13.6 13 L10.8 13.8 Z"/>',
    "sound": f'<path {S} d="M6 12 V3.6 L13.2 2 V10.4"/><circle cx="4.4" cy="12" r="1.8" fill="{{c}}"/>'
             '<circle cx="11.6" cy="10.4" r="1.8" fill="{c}"/>',
    "movieclip": f'<rect x="2" y="3" width="12" height="10" rx="1" {S}/>'
                 '<g fill="{c}"><rect x="3.2" y="4.2" width="1.6" height="1.6"/><rect x="3.2" y="7.2" width="1.6" height="1.6"/>'
                 '<rect x="3.2" y="10.2" width="1.6" height="1.6"/><rect x="11.2" y="4.2" width="1.6" height="1.6"/>'
                 '<rect x="11.2" y="7.2" width="1.6" height="1.6"/><rect x="11.2" y="10.2" width="1.6" height="1.6"/></g>',
    "brush": f'<path {S} d="M13.5 2.5 L8 9 M8 9 L6.6 7.6"/><path fill="{{c}}" d="M6.4 7.8 L8.2 9.6 C7.6 12.4 5 13.6 2.2 13.4 '
             'C3.4 12.2 3.4 9 6.4 7.8 Z"/>',
    "workspace": f'<rect x="1.8" y="2.8" width="12.4" height="10.4" rx="1" {S}/><path {S} d="M1.8 5.6 H14.2 M6.4 5.6 V13.2"/>',
    "datablock": f'<rect x="3" y="3" width="10" height="10" rx="2" {S}/><circle cx="8" cy="8" r="1.6" fill="{{c}}"/>',
    # containers
    "scene": f'<path {S} d="M1.5 13 H14.5"/><circle cx="5" cy="9.6" r="2.6" {S}/><path {S} d="M8.8 13 L11.6 4.6 L14.4 13"/>',
    "collection": f'<rect x="2" y="4.6" width="12" height="9" rx="1.2" {S}/><path {S} d="M2 7.6 H14 M4.2 4.6 L5.4 2.4 H10.6 L11.8 4.6"/>'
                  '<path fill="{c}" fill-opacity=".22" d="M2.6 8.2 H13.4 V12.8 H2.6 Z"/>',
    "view_layer": f'<path {S} d="M8 2.2 L14 5.3 L8 8.4 L2 5.3 Z"/><path {S} d="M2 8.3 L8 11.4 L14 8.3 M2 10.9 L8 14 L14 10.9"/>',
    "blend_file": f'<path {S} d="M3.5 1.8 H10 L12.5 4.3 V14.2 H3.5 Z M10 1.8 V4.3 H12.5"/>'
                  '<circle cx="8" cy="9.4" r="2.4" fill="{a}"/>',
    "orphan": f'<path {S} d="M6.6 9.4 L4.6 11.4 A2.1 2.1 0 0 1 1.6 8.4 L3.6 6.4 M9.4 6.6 L11.4 4.6 A2.1 2.1 0 0 1 14.4 7.6 L12.4 9.6"/>'
              '<path stroke="{a}" stroke-width="1.3" stroke-linecap="round" d="M6.2 2 L6.7 4 M2 6.2 L4 6.7 M9.8 14 L9.3 12 M14 9.8 L12 9.3"/>',
    # restriction toggles (on = enabled / visible, off = drawn dim by the Outliner)
    "chk_on": '<rect x="2.5" y="2.5" width="11" height="11" rx="2.2" fill="{a}"/>'
              '<path fill="none" stroke="#ffffff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" '
              'd="M5 8.3 L7.2 10.5 L11.2 5.6"/>',
    "chk_off": f'<rect x="2.5" y="2.5" width="11" height="11" rx="2.2" {S}/>',
    "select_on": '<path fill="{c}" d="M4 1.8 L12.8 9.6 L8.8 10 L11 14 L9.3 14.9 L7.1 10.8 L4 13.4 Z"/>',
    "select_off": f'<path {S} d="M4 1.8 L12.8 9.6 L8.8 10 L11 14 L9.3 14.9 L7.1 10.8 L4 13.4 Z"/>',
    "eye_on": f'<path {S} d="M1.5 8 C3.5 4.5 5.7 3.5 8 3.5 C10.3 3.5 12.5 4.5 14.5 8 C12.5 11.5 10.3 12.5 8 12.5 '
              f'C5.7 12.5 3.5 11.5 1.5 8 Z"/><circle cx="8" cy="8" r="2.3" fill="{{c}}"/>',
    "eye_off": f'<path {S} d="M1.5 6.5 C3.5 9.5 5.7 10.5 8 10.5 C10.3 10.5 12.5 9.5 14.5 6.5 '
               f'M3.6 8.8 L2.4 10.6 M6 10.1 L5.5 12.2 M10 10.1 L10.5 12.2 M12.4 8.8 L13.6 10.6"/>',
    "monitor_on": f'<rect x="1.8" y="2.5" width="12.4" height="8.6" rx="1" {S}/><path {S} d="M5.6 13.6 H10.4 M8 11.1 V13.6"/>'
                  '<path fill="{c}" fill-opacity=".3" d="M3 3.7 H13 V9.9 H3 Z"/>',
    "monitor_off": f'<rect x="1.8" y="2.5" width="12.4" height="8.6" rx="1" {S}/><path {S} d="M5.6 13.6 H10.4 M8 11.1 V13.6"/>'
                   '<path stroke="{c}" stroke-width="1.5" stroke-linecap="round" d="M2.2 14.2 L13.8 1.8"/>',
    "render_on": f'<rect x="1.5" y="4.6" width="9.6" height="7.6" rx="1.2" {S}/><path {S} d="M11.1 7.2 L14.5 5.2 V11.6 L11.1 9.6"/>'
                 '<circle cx="6.3" cy="8.4" r="1.9" fill="{c}"/>',
    "render_off": f'<rect x="1.5" y="4.6" width="9.6" height="7.6" rx="1.2" {S}/><path {S} d="M11.1 7.2 L14.5 5.2 V11.6 L11.1 9.6"/>'
                  '<path stroke="{c}" stroke-width="1.5" stroke-linecap="round" d="M2.2 14.2 L13.8 1.8"/>',
    "holdout_on": f'<circle cx="8" cy="8" r="5.6" {S}/><path fill="{{c}}" d="M8 2.4 A5.6 5.6 0 0 1 8 13.6 Z"/>',
    "holdout_off": f'<circle cx="8" cy="8" r="5.6" {S}/>',
    "indirect_on": f'<circle cx="7" cy="6" r="2.6" {S}/><path {S} d="M7 1.2 V2 M2.2 6 H3 M11 6 H11.8 M3.6 2.6 L4.2 3.2 M10.4 2.6 L9.8 3.2"/>'
                   '<ellipse cx="9" cy="12.6" rx="5" ry="1.6" fill="{c}"/>',
    "indirect_off": f'<circle cx="7" cy="6" r="2.6" {S}/><ellipse cx="9" cy="12.6" rx="5" ry="1.6" {S}/>',
    "fake_on": '<path fill="{c}" d="M8 1.6 L13.2 3.5 V8 C13.2 11.1 10.9 13.3 8 14.5 C5.1 13.3 2.8 11.1 2.8 8 V3.5 Z"/>'
               '<path fill="none" stroke="#202020" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" '
               'd="M6.4 11 V5.4 H9.8 M6.4 8.2 H9.2"/>',
    "fake_off": f'<path {S} d="M8 1.6 L13.2 3.5 V8 C13.2 11.1 10.9 13.3 8 14.5 C5.1 13.3 2.8 11.1 2.8 8 V3.5 Z"/>',
    # Outliner header / menus
    "filter": f'<path {S} d="M2 3 H14 L9.4 8.6 V13.6 L6.6 12.2 V8.6 Z"/>',
    "filter_on": '<path fill="{a}" stroke="{a}" stroke-width="1.2" stroke-linejoin="round" d="M2 3 H14 L9.4 8.6 V13.6 L6.6 12.2 V8.6 Z"/>',
    "collection_new": f'<rect x="1.5" y="5.6" width="10" height="8" rx="1.1" {S}/><path {S} d="M1.5 8.4 H11.5"/>'
                      '<path stroke="{a}" stroke-width="1.8" stroke-linecap="round" d="M12.6 1.4 V6.4 M10.1 3.9 H15.1"/>',
    "sort_alpha": f'<path {S} d="M2.2 13 L4.8 3 L7.4 13 M3.2 9.6 H6.4 M11.6 3 V13 M9.4 10.8 L11.6 13 L13.8 10.8"/>',
    "sync": f'<path {S} d="M2.8 7 A5.3 5.3 0 0 1 12.4 4.6 M13.2 9 A5.3 5.3 0 0 1 3.6 11.4"/>'
            '<path fill="{c}" d="M13.6 2 V6.2 H9.4 Z M2.4 14 V9.8 H6.6 Z"/>',
    "hierarchy": f'<path {S} d="M4 3.8 V12.2 M4 8 H8.5 M4 12.2 H8.5"/>'
                 '<g fill="{c}"><rect x="2" y="1.6" width="4" height="3.2" rx=".6"/><rect x="9" y="6.4" width="5" height="3.2" rx=".6"/>'
                 '<rect x="9" y="10.6" width="5" height="3.2" rx=".6"/></g>',
    "trash": f'<path {S} d="M2.6 4.2 H13.4 M6 4.2 V2.4 H10 V4.2 M4 4.2 L4.8 14 H11.2 L12 4.2 M6.8 6.6 V11.6 M9.2 6.6 V11.6"/>',
    "isolate": f'<circle cx="8" cy="8" r="5.6" {S} stroke-dasharray="1.6 1.6"/><circle cx="8" cy="8" r="2.4" fill="{{c}}"/>',
    "rename": f'<path {S} d="M2 12.8 H14 M4 10.4 L9.8 2.8 L12 4.4 L6.2 12 L3.6 12.6 Z"/>',
    "parent": f'<circle cx="4.2" cy="4.2" r="2.4" {S}/><circle cx="11.8" cy="11.8" r="2.4" {S}/><path {S} d="M5.9 5.9 L10.1 10.1"/>',
    "unparent": f'<circle cx="4.2" cy="4.2" r="2.4" {S}/><circle cx="11.8" cy="11.8" r="2.4" {S}/>'
                '<path stroke="#ff6a6a" stroke-width="1.5" stroke-linecap="round" d="M6 8.8 L8.8 6 M7.2 10 L10 7.2"/>',
})
# accent colour per icon where the default orange doesn't fit
_ACCENTS = {"chk_on": "#4772b3", "filter_on": "#ffa033", "blend_file": "#ffa033", "orphan": "#ff6a6a",
            "collection_new": "#7ec94f"}


def svg(name, color=FG, accent=None):
    accent = accent or _ACCENTS.get(name, ACCENT)
    body = _ICONS[name].replace("{c}", color).replace("{a}", accent).replace("{{c}}", color).replace("{{a}}", accent)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">{body}</svg>'


def names():
    return list(_ICONS)


_cache = {}


def pixmap(name, size=16, color=FG, accent=None, dpr=None):
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


def tinted(name, color=FG, size=16, selected_white=False):
    """QIcon of `name` drawn in `color` (Outliner rows: one colour per data-block role).
    selected_white: the selected / active state (a blue row) uses white like Blender's highlighted icons."""
    ic = QtGui.QIcon()
    if QtSvg is None or name not in _ICONS:
        return ic
    for sz in (size, size * 2):
        ic.addPixmap(pixmap(name, sz, color=color), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        ic.addPixmap(pixmap(name, sz, color="#ffffff" if selected_white else color), QtGui.QIcon.Selected, QtGui.QIcon.Off)
    return ic

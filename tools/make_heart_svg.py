"""Generates qt_shell/heart.svg – the colour-wheel heart of About the Author (hue wedges clipped to the heart
+ a white radial centre; plain paths, no conic gradient / clipPath – Qt SVG Tiny draws it). Run from the repo root."""
import math, colorsys
N = 400
pts = []
for i in range(N):
    t = 2 * math.pi * i / N
    x = 16 * math.sin(t) ** 3
    y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
    pts.append((x, -y))
xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
S, M = 100.0, 3.0
sc = (S - 2 * M) / max(maxx - minx, maxy - miny)
ox = (S - (maxx - minx) * sc) / 2 - minx * sc
oy = (S - (maxy - miny) * sc) / 2 - miny * sc
heart = [(x * sc + ox, y * sc + oy) for x, y in pts]
cx, cy = 50.0, 47.0          # centre of the colour wheel (a little above the middle, like the reference)

def clip(subject, a, b):
    """Sutherland–Hodgman: keep the part of subject left of the directed line a→b."""
    def inside(p):
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0
    def inter(p, q):
        x1, y1, x2, y2 = p[0], p[1], q[0], q[1]
        x3, y3, x4, y4 = a[0], a[1], b[0], b[1]
        d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(d) < 1e-12:
            return q
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    out = []
    for i in range(len(subject)):
        cur, prev = subject[i], subject[i - 1]
        if inside(cur):
            if not inside(prev):
                out.append(inter(prev, cur))
            out.append(cur)
        elif inside(prev):
            out.append(inter(prev, cur))
    return out

def wedge_clip(poly, a0, a1):
    R = 200
    c = (cx, cy)
    p0 = (cx + R * math.cos(a0), cy - R * math.sin(a0))
    p1 = (cx + R * math.cos(a1), cy - R * math.sin(a1))
    # triangle c, p0, p1 counter-clockwise in screen (y down) → keep the side consistently
    tri = [c, p0, p1]
    # orientation of the triangle in screen coords
    area = (p0[0] - c[0]) * (p1[1] - c[1]) - (p0[1] - c[1]) * (p1[0] - c[0])
    if area > 0:
        tri = [c, p1, p0]
    res = poly
    for i in range(3):
        a, b = tri[i], tri[(i + 1) % 3]
        res = clip(res, b, a) if True else res
        if not res:
            break
    return res

STEPS = 72
OFFSET = math.radians(35)    # red a little above the right side
paths = []
for k in range(STEPS):
    a0 = OFFSET + 2 * math.pi * k / STEPS - 0.012
    a1 = OFFSET + 2 * math.pi * (k + 1) / STEPS + 0.012
    poly = wedge_clip(heart, a0, a1)
    if len(poly) < 3:
        continue
    h = ((k + 0.5) / STEPS) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 1.0, 1.0)
    col = "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))
    d = "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in poly) + " Z"
    paths.append(f'<path d="{d}" fill="{col}"/>')
hd = "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in heart) + " Z"
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
<defs>
<radialGradient id="w" cx="{cx}" cy="{cy}" r="50" gradientUnits="userSpaceOnUse">
<stop offset="0" stop-color="#ffffff" stop-opacity="1"/>
<stop offset="0.3" stop-color="#ffffff" stop-opacity="0.6"/>
<stop offset="0.8" stop-color="#ffffff" stop-opacity="0"/>
</radialGradient>
</defs>
{chr(10).join(paths)}
<path d="{hd}" fill="url(#w)"/>
</svg>
'''
open("qt_shell/heart.svg", "w").write(svg)
print(len(paths), len(svg))

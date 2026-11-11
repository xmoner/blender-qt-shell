"""Generates qt_shell/coins.svg – an open palm holding a stack of gold coins (the status bar's Sponsors button).
Qt SVG Tiny safe: paths, ellipses and linear gradients only. Run from the repo root."""
import os

W = 64
SKIN = ("#ffd2a8", "#e9a877", "#b97a4e")     # light, mid, outline
GOLD = ("#ffe27a", "#f5c542", "#c9952a", "#8a6414")


def coin(cx, cy, rx=13.0, ry=4.2, h=4.0):
    """One coin seen from the side: rim band + top face; cy = the top face's centre."""
    band = (f'<path d="M{cx-rx:.2f},{cy:.2f} L{cx-rx:.2f},{cy+h:.2f} '
            f'A{rx:.2f},{ry:.2f} 0 0 0 {cx+rx:.2f},{cy+h:.2f} L{cx+rx:.2f},{cy:.2f} Z" '
            f'fill="url(#rim)" stroke="{GOLD[3]}" stroke-width="0.8"/>')
    top = (f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" fill="url(#face)" '
           f'stroke="{GOLD[3]}" stroke-width="0.8"/>')
    ring = (f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx*0.62:.2f}" ry="{ry*0.6:.2f}" fill="none" '
            f'stroke="{GOLD[2]}" stroke-width="0.7"/>')
    return band + top + ring


def build():
    defs = f'''<defs>
<linearGradient id="skin" x1="0" y1="0" x2="0" y2="1">
 <stop offset="0" stop-color="{SKIN[0]}"/><stop offset="1" stop-color="{SKIN[1]}"/></linearGradient>
<linearGradient id="sleeve" x1="0" y1="0" x2="1" y2="0">
 <stop offset="0" stop-color="#2b5fb8"/><stop offset="1" stop-color="#3a86ff"/></linearGradient>
<linearGradient id="rim" x1="0" y1="0" x2="1" y2="0">
 <stop offset="0" stop-color="{GOLD[2]}"/><stop offset="0.45" stop-color="{GOLD[1]}"/>
 <stop offset="1" stop-color="{GOLD[2]}"/></linearGradient>
<linearGradient id="face" x1="0" y1="0" x2="1" y2="1">
 <stop offset="0" stop-color="{GOLD[0]}"/><stop offset="1" stop-color="{GOLD[1]}"/></linearGradient>
</defs>'''
    o = SKIN[2]
    # the palm seen from the side: wrist on the left, cupped palm, fingers curling up on the right
    hand = (f'<path d="M12,41 C20,43 30,44 40,44 C47,44 52,42 55,38 C57,35.5 60.5,36.5 60,40 '
            f'C59.2,46 53,52 44,54 C34,56.5 22,56 12,54 Z" fill="url(#skin)" stroke="{o}" stroke-width="1.5" '
            f'stroke-linejoin="round"/>')
    fingers = (f'<path d="M53.5,46.5 C55.5,45.5 57.2,43.6 58.2,41.6" fill="none" stroke="{o}" '
               f'stroke-width="0.9" stroke-linecap="round"/>'
               f'<path d="M50,50 C53,49 55.5,47.4 57,45.4" fill="none" stroke="{o}" stroke-width="0.9" '
               f'stroke-linecap="round"/>')
    # the thumb in front, coming up from the near side of the palm
    thumb = (f'<path d="M18,48 C20,44 23,40.5 27.5,38.4 C30.2,37.2 32.2,39.4 30.6,41.6 C28.8,44 27.6,46.2 27,49.5 Z" '
             f'fill="url(#skin)" stroke="{o}" stroke-width="1.5" stroke-linejoin="round"/>')
    sleeve = ('<path d="M2,38 L13,39.5 C14.5,44 14.5,51 13,56 L2,57.5 Z" fill="url(#sleeve)" '
              'stroke="#1d3f7a" stroke-width="1.5" stroke-linejoin="round"/>'
              '<path d="M10.5,39.4 C12,44.5 12,51 10.5,56.4" fill="none" stroke="#9cc2ff" stroke-width="1"/>')
    coins = "".join(coin(39, y) for y in (37.2, 32.2, 27.2))
    loose = (coin(45, 12.5, rx=10, ry=3.3, h=3.2))   # a coin dropping onto the stack
    shine = ('<path d="M31.5,26 C33.5,24.3 37,23.6 40,24" fill="none" stroke="#fff6c8" stroke-width="1.1" '
             'stroke-linecap="round"/>')
    spark = ('<path d="M58,4 L59.2,7.8 L63,9 L59.2,10.2 L58,14 L56.8,10.2 L53,9 L56.8,7.8 Z" fill="#fff3b0" '
             'stroke="#d9a520" stroke-width="0.5"/>')
    body = sleeve + hand + fingers + coins + shine + loose + spark + thumb
    return (f'<svg xmlns="http://www.w3.org/2000/svg" version="1.2" baseProfile="tiny" width="{W}" height="{W}" '
            f'viewBox="0 0 {W} {W}">{defs}{body}</svg>\n')


if __name__ == "__main__":
    out = os.path.join("qt_shell", "coins.svg")
    with open(out, "w") as f:
        f.write(build())
    print("wrote", out)

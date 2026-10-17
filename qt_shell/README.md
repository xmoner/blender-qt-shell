# Qt Shell – rozhraní Blenderu v PySide6

Addon pro Blender 4.2+ (Windows, Linux, macOS), který nahradí rozhraní Blenderu oknem v Qt.

## Instalace

1. Blender → Edit → Preferences → Add-ons → ▾ → **Install from Disk…** → `qt_shell.zip`.
2. Zapni addon **Qt Shell**.
3. V nastavení addonu klikni na **Nainstalovat PySide6** (stáhne `PySide6-Essentials` do
   uživatelské složky skriptů Blenderu, žádná práva správce nejsou potřeba). Blender po dobu
   instalace nereaguje.
4. Spusť přes **Window → Open Qt Shell** nebo F3 → „Open Qt Shell“.
   Volba *Spouštět Qt Shell při startu* ho otevře automaticky při každém startu Blenderu.

## Co je v Qt

| Část | Jak funguje |
|---|---|
| 3D viewport | Blender kreslí scénu do GPUOffScreen (`draw_view3d`), obraz se zobrazí v Qt. Navigace (MMB / Alt+LMB orbit, Shift pan, Ctrl/kolečko zoom, touchpad), numerické pohledy 1/3/7/0/5/9, otáčení 2/4/6/8 po 15° (Ctrl = posun), výběr kliknutím i obdélníkem, G/R/S s osami X/Y/Z a číselným zadáním, Shift+D, X/Delete, Shift+A, H/Alt+H, Tab, Z (stínování), pravé tlačítko = kontextové menu |
| Menu | File, Edit, Add, Object, Select, Render, Help se generují **z originálních menu Blenderu** (včetně položek addonů), podle módu |
| Vlastnosti | Záložky Render, Výstup, Scéna, Svět, Objekt, Data, Materiál, Fyzika… se generují **z originálních Python panelů Blenderu** přes náhradní `UILayout` |
| Modifikátory, omezení | vlastní Qt verze (v Blenderu jsou kreslené v C), včetně vstupů Geometry Nodes |
| Outliner | kolekce, objekty, rodiče, viditelnost, přejmenování, přesun do kolekce |
| Timeline | přehrávání, rozsah, klíče, auto-klíč |
| Edit mód | výběr vrcholů / hran / stěn kliknutím i obdélníkem (zakryté prvky se nevybírají, kromě X-ray), přepínání 1/2/3 nebo tlačítky v hlavičce, G/R/S s osami, E (extrude), Shift+D, F, X/Delete, H/Alt+H, Ctrl+L, U (UV menu) |
| Node editor | shader (materiál), svět, Geometry Nodes, compositor: uzly, sockety, spoje (tažení, odpojení ze vstupu), přesun, Shift+A hledání uzlů, X mazání, M/H mute/hide, Tab vstup do skupiny, postranní panel s vlastnostmi a hodnotami vstupů |
| UV editor | UV mapa s texturou na pozadí, výběr UV bodů (klik / obdélník), G/R/S s osami, Unwrap / Smart UV / Cube / Reset, testovací UV grid textura |
| Ostatní | Python konzole, „Upravit poslední operaci“ (redo), F3 hledání operátorů, Qt dialogy pro soubory (Open/Save/Import/Export/Append/Link), render F12 s náhledem |

Okno Blenderu se skryje (Windows: WinAPI, macOS: Cocoa přes ctypes, Linux: `xdotool` na X11).
Přes **Window → Zobrazit okno Blenderu** se k němu dá kdykoli vrátit.

## Otestováno

Blender 5.2.0 LTS, Windows 11 (česká klávesnice): start, skrytí okna Blenderu, viewport
(Solid / Material / Rendered), menu Add, redo panel, G/R/S s osami, Ctrl+Z, modifikátory,
materiály, světla, outliner, F12 render s přizpůsobením okna, edit mód (výběr vrcholů/hran/stěn,
obdélník, posun, extrude), UV editor (Smart UV, výběr, posun), node editor (přidání uzlu, spojení,
přesun, Geometry Nodes).

Číselné zkratky (1/2/3 v edit módu, 1/3/7/0 pohledy) fungují podle fyzické klávesy, takže i na
české klávesnici bez Shiftu.

## Omezení

- Image editor, sculpt/paint štětce a gizma nejsou převedené.
- Node editor nezobrazuje speciální widgety uzlů (Color Ramp, křivky) – jejich vlastnosti jsou
  v postranním panelu jen tam, kde jsou to běžné RNA vlastnosti.
- UV editor má vlastní výběr UV bodů (nesynchronizuje se s výběrem UV v Blenderu).
- Prvky `template_*` bez Qt protějšku se zobrazí jako šedý `‹template_…›`.
- Pod čistým Waylandem nejde okno Blenderu skrýt.
- macOS: Qt a Blender sdílí jednu Cocoa smyčku událostí, funguje to, ale je to nejméně odladěná platforma.

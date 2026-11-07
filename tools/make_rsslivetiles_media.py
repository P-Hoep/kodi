"""Draw RSS Live Tiles' media: the window textures (plain white, tinted in Kodi with
colordiffuse so one set serves every accent and theme) and the add-ons' icons and fanart.

  python3 tools/make_rsslivetiles_media.py

Needs Pillow. Writes script.module.rsslivetiles/resources/skins/Default/media/*.png and
icon.png (+ fanart.jpg) for script.rsslivetiles, screensaver.rsslivetiles and the library.
Text in the artwork uses DejaVu Sans (free licence), which Kodi ships as media/Fonts/arial.ttf.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(ROOT, 'script.module.rsslivetiles', 'lib'))
from rsslivetiles.tiles import geometry as g  # noqa: E402
from rsslivetiles.tiles.styles import STYLES  # noqa: E402

MEDIA = os.path.join(ROOT, 'script.module.rsslivetiles', 'resources', 'skins', 'Default', 'media')
FONT_PATHS = ['/Applications/Kodi.app/Contents/Resources/Kodi/media/Fonts/arial.ttf',
              '/usr/share/kodi/media/Fonts/arial.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
SS = 4

ACCENTS = {'cobalt': (0, 80, 239), 'lime': (164, 196, 0), 'magenta': (216, 0, 115), 'orange': (250, 104, 0),
           'teal': (0, 171, 169), 'violet': (170, 0, 255), 'crimson': (162, 0, 37), 'cyan': (27, 161, 226),
           'amber': (240, 163, 10), 'emerald': (0, 138, 0), 'steel': (100, 118, 135)}


def font(size):
    for path in FONT_PATHS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def white_alpha(alpha):
    img = Image.new('RGBA', alpha.size, (255, 255, 255, 0))
    img.putalpha(alpha)
    return img


def rounded(w, h, r):
    big = Image.new('L', (w * SS, h * SS), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), r * SS, fill=255)
    return white_alpha(big.resize((w, h), Image.LANCZOS))


def scrim():
    h = 256
    alpha = Image.new('L', (8, h), 0)
    for y in range(h):
        t = y / (h - 1.0)
        alpha.paste(int(255 * (t ** 1.7)), (0, y, 8, y + 1))
    return white_alpha(alpha)


def warn(size=64):
    s = size * SS
    alpha = Image.new('L', (s, s), 0)
    d = ImageDraw.Draw(alpha)
    d.polygon([(s * 0.5, s * 0.06), (s * 0.97, s * 0.92), (s * 0.03, s * 0.92)], fill=255)
    d.rounded_rectangle((s * 0.455, s * 0.34, s * 0.545, s * 0.66), s * 0.04, fill=0)
    d.ellipse((s * 0.45, s * 0.72, s * 0.55, s * 0.82), fill=0)
    return white_alpha(alpha.resize((size, size), Image.LANCZOS))


def play(size=180):
    s = size * SS
    alpha = Image.new('L', (s, s), 0)
    d = ImageDraw.Draw(alpha)
    d.ellipse((0, 0, s - 1, s - 1), fill=255)
    d.ellipse((s * 0.04, s * 0.04, s * 0.96, s * 0.96), fill=0)
    d.polygon([(s * 0.40, s * 0.30), (s * 0.40, s * 0.70), (s * 0.72, s * 0.50)], fill=255)
    return white_alpha(alpha.resize((size, size), Image.LANCZOS))


def textures():
    os.makedirs(MEDIA, exist_ok=True)
    Image.new('RGBA', (8, 8), (255, 255, 255, 255)).save(os.path.join(MEDIA, 'white.png'))
    rounded(32, 32, 8).save(os.path.join(MEDIA, 'round8.png'))
    inset = STYLES['modern']['inset']
    for size, (w, h) in g.PIXELS.items():
        rounded(w - 2 * inset, h - 2 * inset, STYLES['modern']['radius']).save(
            os.path.join(MEDIA, 'mask_%s.png' % size))
    scrim().save(os.path.join(MEDIA, 'scrim.png'))
    warn().save(os.path.join(MEDIA, 'warn.png'))
    play().save(os.path.join(MEDIA, 'play.png'))


# ------------------------------------------------------------------ artwork

def rss_glyph(size, colour=(255, 255, 255)):
    """The feed icon: a dot and two arcs, drawn supersampled."""
    s = size * SS
    img = Image.new('L', (s, s), 0)
    d = ImageDraw.Draw(img)
    w = s * 0.13
    r = s * 0.11
    d.ellipse((s * 0.12 - r, s * 0.88 - r, s * 0.12 + r, s * 0.88 + r), fill=255)
    for radius in (0.45, 0.76):
        rr = s * radius
        box = (s * 0.12 - rr, s * 0.88 - rr, s * 0.12 + rr, s * 0.88 + rr)
        d.arc(box, 270, 360, fill=255, width=int(w))
    glyph = img.resize((size, size), Image.LANCZOS)
    out = Image.new('RGBA', (size, size), colour + (0,))
    out.putalpha(glyph)
    return out


def tile_wall(w, h, unit, gap, layout, bg=(0, 0, 0), glyph_tile=None, clock=None, lines=None):
    """layout: [(col, row, cols, rows, colour)] in units of (unit + gap)."""
    img = Image.new('RGB', (w, h), bg)
    d = ImageDraw.Draw(img)
    step = unit + gap
    total_w = max(c + cw for c, r, cw, rh, _ in layout) * step - gap
    total_h = max(r + rh for c, r, cw, rh, _ in layout) * step - gap
    ox, oy = (w - total_w) // 2, (h - total_h) // 2
    for i, (c, r, cw, rh, col) in enumerate(layout):
        x0, y0 = ox + c * step, oy + r * step
        x1, y1 = x0 + cw * step - gap, y0 + rh * step - gap
        d.rectangle((x0, y0, x1, y1), fill=col)
        if glyph_tile == i:
            gs = int(min(x1 - x0, y1 - y0) * 0.55)
            img.paste(rss_glyph(gs), (int((x0 + x1 - gs) / 2), int((y0 + y1 - gs) / 2)), rss_glyph(gs))
        if clock == i:
            f = font(int((y1 - y0) * 0.27))
            text = '10:42'
            tw = d.textlength(text, font=f)
            d.text(((x0 + x1 - tw) / 2, y0 + (y1 - y0) * 0.24), text, font=f, fill=(255, 255, 255))
        if lines and i in lines:
            lh = max(6, int((y1 - y0) * 0.075))
            pad = int(lh * 1.6)
            for k, frac in enumerate(lines[i]):
                yy = y0 + pad + k * int(lh * 1.9)
                d.rectangle((x0 + pad, yy, x0 + pad + int((x1 - x0 - 2 * pad) * frac), yy + lh),
                            fill=(255, 255, 255))
    return img


def write_art():
    a = ACCENTS
    app_layout = [(0, 0, 2, 2, a['cobalt']), (2, 0, 1, 1, a['lime']), (3, 0, 1, 1, a['magenta']),
                  (2, 1, 2, 1, a['orange']), (0, 2, 4, 2, a['teal'])]
    ss_layout = [(0, 0, 2, 2, a['violet']), (2, 0, 2, 2, a['cobalt']), (0, 2, 1, 1, a['amber']),
                 (1, 2, 1, 1, a['crimson']), (2, 2, 2, 2, a['cyan']), (0, 3, 2, 1, a['emerald'])]
    lib_layout = [(0, 0, 2, 2, a['steel']), (2, 0, 2, 2, a['cobalt']), (0, 2, 4, 2, (60, 60, 60))]
    targets = [
        ('script.rsslivetiles', app_layout, 0, None, {4: (0.9, 0.7, 0.8)}),
        ('screensaver.rsslivetiles', ss_layout, 1, 0, {4: (0.85, 0.6)}),
        ('script.module.rsslivetiles', lib_layout, 1, None, {2: (0.8, 0.6)}),
    ]
    for addon, layout, glyph, clock, lines in targets:
        folder = os.path.join(ROOT, addon)
        os.makedirs(folder, exist_ok=True)
        icon = tile_wall(512, 512, 106, 8, layout, glyph_tile=glyph, clock=clock, lines=lines)
        icon.save(os.path.join(folder, 'icon.png'))
        if addon != 'script.module.rsslivetiles':
            fanart(addon == 'screensaver.rsslivetiles').save(os.path.join(folder, 'fanart.jpg'), quality=88)


def fanart(clock, seed=7):
    """A full-screen Start-screen wall: bands 4 units wide, random tile sizes and accents."""
    import random
    rng = random.Random(seed + (1 if clock else 0))
    colours = list(ACCENTS.values())
    layout, glyphs, lines = [], [], {}
    for band in range(4):
        grid = [[False] * 4 for _ in range(6)]
        for row in range(6):
            for col in range(4):
                if grid[row][col]:
                    continue
                options = [(1, 1)]
                if col + 1 < 4 and row + 1 < 6 and not grid[row][col + 1] and not grid[row + 1][col] \
                        and not grid[row + 1][col + 1]:
                    options += [(2, 2)] * 3
                    if col == 0 and all(not grid[row + dr][dc] for dr in (0, 1) for dc in range(4)):
                        options += [(4, 2)] * 2
                cw, rh = rng.choice(options)
                for dr in range(rh):
                    for dc in range(cw):
                        grid[row + dr][col + dc] = True
                n = len(layout)
                layout.append((band * 4 + col, row, cw, rh, rng.choice(colours)))
                if cw >= 2 and rng.random() < 0.25:
                    glyphs.append(n)
                elif cw >= 2:
                    lines[n] = tuple(rng.uniform(0.5, 0.95) for _ in range(rng.randint(2, 3)))
    img = tile_wall(1920, 1080, 120, 10, layout, lines=lines)
    step = 130
    total_w = 16 * step - 10
    ox, oy = (1920 - total_w) // 2, (1080 - (6 * step - 10)) // 2
    for n in glyphs:
        c, r, cw, rh, _col = layout[n]
        size = int(min(cw, rh) * step * 0.45)
        x = ox + c * step + (cw * step - 10 - size) // 2
        y = oy + r * step + (rh * step - 10 - size) // 2
        img.paste(rss_glyph(size), (x, y), rss_glyph(size))
    return img


if __name__ == '__main__':
    textures()
    write_art()
    print('textures ->', MEDIA)

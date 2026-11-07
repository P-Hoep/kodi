"""Generate Sand Clock's glyph images and masks, grain textures, icon and fanart.

  python3 tools/make_sandclock_media.py

Downloads the OFL fonts from github.com/google/fonts into tools/.wordclock-fonts/ (once; the
cache is shared with Word Clock), then writes, under screensaver.sandclock/:
  resources/media/fonts/<font>/<w><c>.png   white digits and colon, weight w = 0 light, 1, 2 bold
  resources/media/fonts/fonts.json          per font and weight: glyph box sizes and ink masks
  resources/media/grains/<look>/<n>_<v>.png strips of n grains (variant v), for the pile
  resources/media/white.png
  icon.png (512) and fanart.jpg (1920x1080), drawn by draw() below
Every glyph of a font has the same height (lining figures, so none dips below the baseline);
the digits share one width so the clock does not
jiggle as they change. Needs Pillow.
"""

import json
import math
import os
import random
import sys
import urllib.request

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock'))
CACHE = os.path.join(HERE, '.wordclock-fonts')
MEDIA = os.path.join(ROOT, 'resources', 'media')
sys.path.insert(0, ROOT)

from resources.lib import config, sand  # noqa: E402

GOOGLE = 'https://github.com/google/fonts/raw/main/ofl/'
DIGIT_PX = 200          # height of the digits' ink in the glyph images
PAD = 0.08              # above and below the ink, as a fraction of DIGIT_PX
GAP = 0.16              # between characters
MASK_H = 120            # mask rows
GRAIN_PX = 12           # one grain in a strip texture
VARIANTS = 4
CHARS = '0123456789:'
FEATURES = ['lnum', 'tnum']   # lining, tabular figures where the font has them

# folder -> (Google Fonts dir, file, weight axis values for light, regular, bold, other axes)
FONTS = {
    'inter': ('inter', 'Inter[opsz,wght].ttf', (300, 500, 800), {'Optical size': 32}),
    'montserrat': ('montserrat', 'Montserrat[wght].ttf', (300, 500, 800), {}),
    'orbitron': ('orbitron', 'Orbitron[wght].ttf', (400, 600, 900), {}),
    'pixelify': ('pixelifysans', 'PixelifySans[wght].ttf', (400, 500, 700), {}),
    'doto': ('doto', 'Doto[ROND,wght].ttf', (300, 600, 900), {'Roundness': 100}),
    'jetbrains': ('jetbrainsmono', 'JetBrainsMono[wght].ttf', (200, 500, 800), {}),
    'comfortaa': ('comfortaa', 'Comfortaa[wght].ttf', (300, 500, 700), {}),
    'playfair': ('playfairdisplay', 'PlayfairDisplay[wght].ttf', (400, 600, 900), {}),
    'stencil': ('bigshouldersstencil', 'BigShouldersStencil[opsz,wght].ttf', (300, 600, 900),
                {'Optical size': 72}),
}


def fetch(folder, filename):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, filename)
    if not os.path.exists(path):
        url = GOOGLE + folder + '/' + urllib.request.quote(filename)
        print('downloading', url)
        urllib.request.urlretrieve(url, path)
        urllib.request.urlretrieve(GOOGLE + folder + '/OFL.txt', os.path.join(CACHE, folder + '-OFL.txt'))
    return path


def load(path, size, axes):
    font = ImageFont.truetype(path, size)
    names = [a['name'] if isinstance(a['name'], str) else a['name'].decode() for a in font.get_variation_axes()]
    current = [a['default'] for a in font.get_variation_axes()]
    font.set_variation_by_axes([axes.get(n, current[i]) for i, n in enumerate(names)])
    return font


def font_for_digits(path, axes):
    """The size at which '0' is DIGIT_PX tall."""
    probe = load(path, 400, axes)
    top, bottom = probe.getbbox('0', anchor='ls', features=FEATURES)[1::2]
    return load(path, max(8, int(round(400.0 * DIGIT_PX / (bottom - top)))), axes)


def glyph_set(font):
    """{char: RGBA image}, all the same height, the digits all the same width."""
    pad, gap = int(DIGIT_PX * PAD), int(DIGIT_PX * GAP)
    ink = dict((c, font.getbbox(c, anchor='ls', features=FEATURES)) for c in CHARS)
    top = min(b[1] for b in ink.values())
    h = max(b[3] for b in ink.values()) - top + 2 * pad     # every glyph's ink fits
    digit_w = max(b[2] - b[0] for c, b in ink.items() if c != ':') + gap
    colon_w = (ink[':'][2] - ink[':'][0]) + gap * 2
    out = {}
    for c in CHARS:
        w = colon_w if c == ':' else digit_w
        left, _t, right, _b = ink[c]
        mask = Image.new('L', (w, h), 0)
        ImageDraw.Draw(mask).text((w / 2.0 - (left + right) / 2.0, pad - top), c, font=font, fill=255, anchor='ls',
                                  features=FEATURES)
        img = Image.new('RGBA', (w, h), (255, 255, 255, 0))
        img.putalpha(mask)
        out[c] = img
    return out, h, digit_w, colon_w


def rle(img):
    mw = max(1, int(round(img.width * MASK_H / float(img.height))))
    alpha = img.getchannel('A').resize((mw, MASK_H), Image.BOX)
    px = alpha.load()
    rows = []
    for y in range(MASK_H):
        runs, start = [], None
        for x in range(mw + 1):
            on = x < mw and px[x, y] >= 128
            if on and start is None:
                start = x
            elif not on and start is not None:
                runs.append([start, x - start])
                start = None
        rows.append(runs)
    return [mw, rows]


def save(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, optimize=True)


def fonts():
    meta = {}
    for name, (folder, filename, weights, axes) in FONTS.items():
        path = fetch(folder, filename)
        meta[name] = {}
        for w, wght in enumerate(weights):
            font = font_for_digits(path, dict(axes, Weight=wght))
            glyphs, h, digit_w, colon_w = glyph_set(font)
            for c, img in glyphs.items():
                save(img, os.path.join(MEDIA, 'fonts', name, '%d%s.png' % (w, 'colon' if c == ':' else c)))
            meta[name][str(w)] = dict(h=h, digit_w=digit_w, colon_w=colon_w,
                                      masks=dict((c, rle(img)) for c, img in glyphs.items()))
        print('%-10s %d x %d digits' % (name, digit_w, h))
    with open(os.path.join(MEDIA, 'fonts', 'fonts.json'), 'w') as handle:
        json.dump(meta, handle, separators=(',', ':'), sort_keys=True)
    assert set(n for _l, n in config.FONTS) == set(FONTS), 'config.FONTS and FONTS disagree'


def shades(variant):
    rng = random.Random(1000 + variant)
    return [0.74 + 0.26 * rng.random() for _ in range(sand.RUN_BLOCK)]


def bead(shade):
    """One round grain, lit from the top left, on transparent."""
    ss = 4
    n = GRAIN_PX * ss
    big = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.ellipse((ss, ss, n - ss - 1, n - ss - 1), fill=(int(205 * shade),) * 3 + (255,))
    d.ellipse((n * 0.28, n * 0.24, n * 0.52, n * 0.48), fill=(255, 255, 255, 255))
    big = big.filter(ImageFilter.GaussianBlur(ss * 0.9))
    return big.resize((GRAIN_PX, GRAIN_PX), Image.LANCZOS)


def grains():
    """Strips of 1..RUN_BLOCK grains. Grain i (counting up from the bottom) of variant v has
    the same shade in every strip, so a strip that grows by a grain keeps its pattern."""
    for v in range(VARIANTS):
        sh = shades(v)
        for n in range(1, sand.RUN_BLOCK + 1):
            strip = Image.new('RGBA', (GRAIN_PX, GRAIN_PX * n), (255, 255, 255, 255))
            beads = Image.new('RGBA', (GRAIN_PX, GRAIN_PX * n), (0, 0, 0, 0))
            for i in range(n):
                y = (n - 1 - i) * GRAIN_PX
                level = int(round(255 * sh[i]))
                strip.paste((level, level, level, 255), (0, y, GRAIN_PX, y + GRAIN_PX))
                b = bead(sh[i])
                beads.alpha_composite(b, (0, y))
            save(strip, os.path.join(MEDIA, 'grains', 'sand', '%d_%d.png' % (n, v)))
            save(beads, os.path.join(MEDIA, 'grains', 'beads', '%d_%d.png' % (n, v)))
    save(Image.new('RGBA', (8, 8), (255, 255, 255, 255)), os.path.join(MEDIA, 'white.png'))


# ------------------------------------------------------------------ preview art

def tint(img, colour):
    r, g, b = [int(colour[i:i + 2], 16) for i in (2, 4, 6)]
    out = Image.new('RGBA', img.size, (r, g, b, 0))
    out.putalpha(img.getchannel('A'))
    return out


def cell_image(s, colour, shade, g):
    rgb = tuple(int(colour[i:i + 2], 16) for i in (2, 4, 6))
    if s['grain_look'] == 2:
        return tint(bead(shade).resize((g, g), Image.LANCZOS), colour)
    k = shade if s['grain_look'] == 0 else 1.0
    return Image.new('RGBA', (g, g), tuple(int(x * k) for x in rgb) + (255,))


def flight_pos(f, ms):
    """Where a grain is `ms` after its batch started (the screensaver's animations, in Python)."""
    x, y = f.x, f.y
    e = ms - f.delay
    if e > 0:
        p = min(1.0, e / max(1.0, f.fall_ms))
        y += f.fall_px * p * p
        x += f.scatter_px * math.sin(p * math.pi / 2)
    e -= f.fall_ms
    if e > 0 and f.slide_ms:
        p = min(1.0, e / float(f.slide_ms))
        x, y = x + f.dx * p, y + f.dy * p
    return x, y


def draw(s, hour, minute, second, seconds_of_sand=40, seed=3, crumbling=0.45):
    """A frame like the screensaver's: `seconds_of_sand` seconds of crumbles have built a pile,
    and the clock shown is `crumbling` seconds into falling apart (0 for the whole clock)."""
    rng = random.Random(seed)
    meta = json.load(open(os.path.join(MEDIA, 'fonts', 'fonts.json')))
    folder = config.FONTS[s['font']][1]
    font = sand.Font(meta[folder][str(s['weight'])])
    g = sand.grain_px(s, font)
    grid = sand.Grid(g)
    pile = sand.Pile(grid, rng, 0.0)
    target = sand.pile_target(s, font, g)
    colours = ['FF' + c for c in config.PALETTES[s['palette']][1]]
    gravity, spread = sand.GRAVITY[s['gravity']], sand.SPREAD[s['speed']]
    lead = sand.lead(s)
    end = hour * 3600 + minute * 60 + second
    colour, dropped, last = colours[0], [], []
    for k in range(seconds_of_sand + 1):
        clock = end - seconds_of_sand + k
        t0 = k - lead
        old = sand.time_text(s, clock // 3600 % 24, clock // 60 % 60, clock % 60)
        new = sand.time_text(s, (clock + 1) // 3600 % 24, (clock + 1) // 60 % 60, (clock + 1) % 60)
        boxes = sand.layout(s, font, old)
        flights = []
        if k == seconds_of_sand and not crumbling:
            break
        for i, ch in enumerate(old):
            if s['crumble'] == 1 or len(old) != len(new) or ch != new[i]:
                flights += pile.drop(sand.grains(font, ch, boxes[i], grid), colour, t0 + 1, gravity, spread)
        dropped.append((t0 + 1, len(flights)))
        last = flights
        if k % 2 == 0 and pile.change is None:
            rate = sum(n for when, n in dropped if when > k - 20) * g * g / max(1.0, min(20.0, k))
            speed = sand.sink_speed(rate, pile.height_px(k), target, pile.footprint(k))
            if sand.speed_changed(speed, pile.speed):
                pile.schedule(k + 3, speed)
        pile.commit(k)
        colour = sand.pick(colours, colour, rng)
    now = seconds_of_sand - lead + crumbling if crumbling else seconds_of_sand
    bg = Image.new('RGBA', (sand.W, sand.H), '#' + s['background'][2:])
    for col, column in pile.cells.items():
        sh = shades(col % VARIANTS)
        for row, (c, landed) in column.items():
            if landed <= now:
                strip_base = row - row % sand.RUN_BLOCK
                bg.alpha_composite(cell_image(s, c, sh[(row - strip_base) % sand.RUN_BLOCK], g),
                                   (grid.x(col), int(round(pile.cell_y(row, now)))))
    for f in last if crumbling else []:
        t0 = seconds_of_sand - lead
        if t0 + f.land_ms / 1000.0 > now:
            x, y = flight_pos(f, (now - t0) * 1000.0)
            bg.alpha_composite(cell_image(s, f.colour, 1.0, g), (int(x), int(round(y))))
    # The clock: the new time if the crumble is over, else the old time still crumbling.
    text = sand.time_text(s, hour, minute, second)
    boxes = sand.layout(s, font, text)
    if crumbling:
        return bg
    for i, ch in enumerate(text):
        x, y, w, h = boxes[i]
        img = Image.open(os.path.join(MEDIA, 'fonts', folder, '%d%s.png' % (s['weight'], 'colon' if ch == ':' else ch)))
        glyph = img.resize((int(round(w)), int(round(h))), Image.LANCZOS)
        bg.alpha_composite(tint(glyph, colour), (int(round(x)), int(round(y))))
    return bg


def art():
    s = config.defaults()
    frame = draw(s, 17, 52, 14, crumbling=0)
    frame.convert('RGB').save(os.path.join(ROOT, 'fanart.jpg'), quality=88)
    side = 1080
    icon = frame.crop(((1920 - side) // 2, 0, (1920 + side) // 2, side)).resize((512, 512), Image.LANCZOS)
    icon.convert('RGB').save(os.path.join(ROOT, 'icon.png'), optimize=True)
    print('icon.png, fanart.jpg')


if __name__ == '__main__':
    fonts()
    grains()
    art()

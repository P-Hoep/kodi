"""Draw Word Clock's face with Pillow, the way the screensaver lays it out in Kodi.

  python3 tools/preview_wordclock.py out.png 13:55 [setting=value ...]
  python3 tools/preview_wordclock.py out.png 00:10 font=6 glow=2 night_palette=3

Uses the glyph PNGs from tools/make_wordclock_media.py and resources/lib/look.py's geometry
and colours (night or day palette as the 'mode' setting and the time say).
"""

import datetime
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'screensaver.wordclock'))
sys.path.insert(0, ROOT)

from resources.lib import config, grid, look  # noqa: E402

MEDIA = os.path.join(ROOT, 'resources', 'media')
CARD_RADIUS = 104
_cache = {}


def tinted(path, size, colour):
    key = (path, size, colour)
    if key not in _cache:
        a, r, g, b = look.rgb(colour)
        img = Image.open(path).convert('RGBA').resize(size, Image.LANCZOS)
        alpha = img.getchannel('A').point(lambda v: v * a // 255)
        out = Image.new('RGBA', size, (r, g, b, 0))
        out.putalpha(alpha)
        _cache[key] = out
    return _cache[key]


def paste(canvas, path, rect, colour):
    x, y, w, h = rect
    if w > 0 and h > 0 and look.rgb(colour)[0]:
        canvas.alpha_composite(tinted(path, (w, h), colour), (x, y))


def draw(s, hour, minute, second=0, offset=(0, 0)):
    now = datetime.datetime(2026, 1, 1, hour, minute, second)
    c = look.finish(s, look.palette(s, look.phase(s, now)), look.dim_factor(s, now))
    words, dots = grid.phrase(hour, minute, second, config.clock_options(s))
    lit = {}
    for w in words:
        for i in grid.cells(w):
            lit[i] = look.word_colour(s, w, c['lit'], hour * 3600 + minute * 60 + second)
    a, r, g, b = look.rgb(c['bg'])
    canvas = Image.new('RGBA', (look.W, look.H), (r, g, b, 255))
    lay = look.Layout(s, offset)
    if s['frame'] != 2:
        x, y, side, _ = lay.card
        rad = CARD_RADIUS if s['frame'] == 0 else 0
        ImageDraw.Draw(canvas).rounded_rectangle((x, y, x + side - 1, y + side - 1), rad, fill=look.rgb(c['card'])[1:])
    font = os.path.join(MEDIA, 'fonts', config.FONTS[s['font']][1])
    lit_weight = 'b' if s['weight'] == 0 else 'r'
    for i in range(grid.SIZE * grid.SIZE):
        letter = grid.ROWS[i // grid.SIZE][i % grid.SIZE]
        if i in lit:
            if s['glow']:
                paste(canvas, os.path.join(font, letter + 'g' + lit_weight + '.png'), lay.glow_rect(i),
                      look.with_alpha(lit[i], look.GLOW_ALPHA[s['glow']]))
            paste(canvas, os.path.join(font, letter + lit_weight + '.png'), lay.letter_rect(i), lit[i])
        else:
            paste(canvas, os.path.join(font, letter + 'r.png'), lay.letter_rect(i), c['unlit'])
    if s['dots']:
        for k, rect in enumerate(lay.dot_rects()):
            paste(canvas, os.path.join(MEDIA, 'dot.png'), rect, c['lit'] if k < dots else c['unlit'])
    return canvas


def main(args):
    out, hhmm = args[0], args[1]
    s = config.defaults()
    for arg in args[2:]:
        k, _, v = arg.partition('=')
        s[k] = v if k.endswith(('_bg', '_card', '_lit', '_unlit', '_start')) else int(v)
    h, m = [int(p) for p in hhmm.split(':')[:2]]
    draw(s, h, m).convert('RGB').save(out)
    print(out, grid.text(grid.phrase(h, m, 0, config.clock_options(s))[0]))


if __name__ == '__main__':
    main(sys.argv[1:])

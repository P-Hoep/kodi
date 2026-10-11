"""Draw Math Clock's screen with Pillow, exactly as the add-on lays it out in Kodi.

  python3 tools/preview_mathclock.py out.png [setting=value ...]
  python3 tools/preview_mathclock.py out.png colours=0 seconds=false equation_set=1

Needs Pillow. Uses the current time and a fixed random seed.
"""

import datetime
import os
import random
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'screensaver.math.clock'))
sys.path.insert(0, ROOT)

from resources.lib import clockface, config, texmath  # noqa: E402

GLYPHS = os.path.join(ROOT, 'resources', 'media', 'glyphs')


def rgb(argb):
    return tuple(int(argb[i:i + 2], 16) for i in (2, 4, 6))


def paint(img, rects, colour):
    draw = ImageDraw.Draw(img)
    for name, x, y, w, h in rects:
        if name is None:
            draw.rectangle([x, y, x + w - 1, y + h - 1], fill=colour)
            continue
        g = Image.open(os.path.join(GLYPHS, name + '.png')).resize((w, h), Image.LANCZOS)
        tint = Image.new('RGBA', g.size, colour + (0,))
        tint.putalpha(g.getchannel('A'))
        img.alpha_composite(tint, (x, y))


def face(s, now, rng):
    pal = dict((k, rgb(v)) for k, v in clockface.palette(s, now).items())
    img = Image.new('RGBA', (clockface.W, clockface.H), pal['bg'] + (255,))
    kinds = clockface.rows(s)
    geo = clockface.Geometry(len(kinds), s['text_size'])
    if s['separators']:
        paint(img, [(None,) + r for r in geo.separators()], pal['rule'])
    for i, kind in enumerate(kinds):
        paint(img, geo.rects(texmath.typeset(clockface.puzzle(kind, now, s, rng)), i), pal['text'])
        if s['labels']:
            paint(img, geo.label(clockface.ROWS[kind][0], i), pal['label'])
    if s['military'] and s['military_badge']:
        paint(img, geo.badge(), pal['badge'])
    return img


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'mathclock.png'
    s = config.defaults()
    for arg in sys.argv[2:]:
        key, _, v = arg.partition('=')
        s[key] = (v == 'true') if v in ('true', 'false') else int(v)
    face(s, datetime.datetime.now(), random.Random(7)).convert('RGB').save(out)
    print(out)


if __name__ == '__main__':
    main()

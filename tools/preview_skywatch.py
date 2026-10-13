"""Draw a SkyWatch panel scene to a PNG without Kodi, with live data, to check layouts.

  python3 tools/preview_skywatch.py current out.png lat=44.9 lon=-93.3 place=Minneapolis
  python3 tools/preview_skywatch.py all /tmp/previews     # every panel scene

Fetches data through the real hub into tools/.skywatch-cache/preview (so reruns are quick)
and approximates Kodi's labels with Estuary's Noto Sans at the skin's font sizes.
Needs Pillow.
"""

import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'screensaver.skywatch'))
sys.path.insert(0, ROOT)

from resources.lib import budget, cache, config, hub as hub_mod, units  # noqa: E402
from resources.lib import scenes  # noqa: E402
from resources.lib.scenes.common import Context  # noqa: E402

MEDIA = os.path.join(ROOT, 'resources', 'media')
FONT = '/System/Library/Fonts/Supplemental/Arial.ttf'   # close to Estuary's Noto Sans metrics
SIZES = {'xs': 23, 'sm': 30, 'md': 37, 'lg': 45, 'xl': 60}


def color(hexstr, default=(255, 255, 255, 255)):
    if not hexstr:
        return default
    v = int(hexstr, 16)
    return ((v >> 16) & 255, (v >> 8) & 255, v & 255, (v >> 24) & 255)


def tint(img, c):
    r, g, b, a = img.split()
    cr, cg, cb, ca = c
    r = r.point(lambda v: v * cr // 255)
    g = g.point(lambda v: v * cg // 255)
    b = b.point(lambda v: v * cb // 255)
    a = a.point(lambda v: v * ca // 255)
    return Image.merge('RGBA', (r, g, b, a))


def render(lay, out):
    bg = Image.open(os.path.join(MEDIA, lay.background)).convert('RGBA').resize((1920, 1080))
    canvas = bg
    draw = ImageDraw.Draw(canvas)
    fonts = dict((k, ImageFont.truetype(FONT, v)) for k, v in SIZES.items())
    for item in lay.items:
        if item[0] == 'image':
            _k, x, y, w, h, path, col, _aspect, rotate = item
            full = path if os.path.isabs(path) else os.path.join(MEDIA, path)
            if w <= 0 or h <= 0 or not os.path.exists(full):
                continue
            img = Image.open(full).convert('RGBA').resize((max(1, w), max(1, h)))
            if col:
                img = tint(img, color(col))
            if rotate:
                img = img.rotate(-rotate, expand=False)
            canvas.alpha_composite(img, (max(0, x), max(0, y)))
            draw = ImageDraw.Draw(canvas)
        else:
            _k, x, y, w, h, text, font, align, col = item
            text = text.replace('[B]', '').replace('[/B]', '')
            f = fonts[font]
            tw = draw.textlength(text, font=f)
            tx = x if align == 'left' else (x + (w - tw) / 2 if align == 'center' else x + w - tw)
            draw.text((tx, y), text, font=f, fill=color(col))
    if lay.textbox:
        x, y, w, h, text = lay.textbox
        f = fonts['md']
        cy = y
        for para in text.split('\n'):
            words, line = para.split(), ''
            for word in words:
                if draw.textlength(line + ' ' + word, font=f) > w:
                    draw.text((x, cy), line, font=f, fill=(230, 235, 240, 255))
                    cy += 50
                    line = word
                else:
                    line = (line + ' ' + word).strip()
            draw.text((x, cy), line, font=f, fill=(230, 235, 240, 255))
            cy += 50
    canvas.convert('RGB').save(out)


def main(argv):
    sid, out = argv[0], argv[1]
    s = config.defaults()
    s.update({'lat': 44.9031, 'lon': -93.3096, 'location_name': 'Minneapolis'})
    for arg in argv[2:]:
        key, _, value = arg.partition('=')
        s[key] = type(s.get(key, ''))(value) if key in s and not isinstance(s.get(key), bool) else value
    for key in ('lat', 'lon'):
        s[key] = float(s[key])
    for sc in config.SCENE_IDS:
        s['scene_' + sc] = max(1, s.get('scene_' + sc, 0)) if sc != 'ambient' else s.get('scene_ambient', 2)
    profile = os.path.join(HERE, '.skywatch-cache', 'preview')
    store = cache.JsonCache(os.path.join(profile, 'data.db'))
    hub = hub_mod.Hub(s, store, budget.Budget())
    for _ in range(3):
        hub.run_due()
    u = units.Units(s)
    ids = list(scenes.PANELS) if sid == 'all' else [sid]
    if sid == 'all':
        os.makedirs(out, exist_ok=True)
    for scene_id in ids:
        ctx = Context(s, u, hub, profile, s['location_name'] or 'Home')
        started = time.time()
        lay = scenes.build_panel(scene_id, ctx, hub.alerts())
        built = time.time() - started
        path = os.path.join(out, scene_id + '.png') if sid == 'all' else out
        render(lay, path)
        print('%-10s %4d items  built in %.2f s  -> %s' % (scene_id, len(lay.items), built, path))


if __name__ == '__main__':
    main(sys.argv[1:])

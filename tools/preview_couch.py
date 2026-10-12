"""Draw Couchstronomy's sky to a PNG without Kodi, using the add-on's own code, with
Pillow standing in for Kodi to stack the layers and draw the labels.

  python3 tools/preview_couch.py out.png                       # now, default settings
  python3 tools/preview_couch.py out.png time=2026-10-12T03:00 azimuth=90 tilt=30 labels=2
  python3 tools/preview_couch.py out.png show_lines=true hfov=100 look=1

Settings use the ids in resources/lib/config.py; time is UTC (ISO 8601).
"""

import calendar
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'screensaver.couchstronomy'))
sys.path.insert(0, ROOT)

from resources.lib import config, draw, scene, skylayer  # noqa: E402

STYLE = {'star': (215, 225, 240), 'planet': (255, 226, 160), 'moon': (235, 235, 235), 'sun': (255, 230, 170),
         'dso': (160, 200, 170), 'const': (120, 150, 210), 'compass': (230, 190, 120)}


def parse(args):
    s = config.defaults()
    when = time.time()
    for arg in args:
        key, _, value = arg.partition('=')
        if key == 'time':
            when = calendar.timegm(time.strptime(value, '%Y-%m-%dT%H:%M'))
            continue
        if value in ('true', 'false'):
            s[key] = value == 'true'
        else:
            try:
                s[key] = int(value)
            except ValueError:
                try:
                    s[key] = float(value)
                except ValueError:
                    s[key] = value
    return s, when


def render(s, when, width=1920, height=1080, timings=None):
    t0 = time.time()
    view = scene.View(s, width, height)
    view.time_offset = 0
    model = scene.Model(view)
    t1 = time.time()
    sc = model.build(when)
    t2 = time.time()
    layer = draw.StarLayer(width, height, draw.Appearance(view.enhance, s['star_brightness'] / 100.0))
    moon = draw.MoonTexture(os.path.join(ROOT, 'resources', 'data', 'moon.bin'))
    raw = layer.render(sc, moon, show_icons=s['labels'] == config.EXPLORER)
    t3 = time.time()
    png_stars = draw.encode_png(width, height, bytes(raw))
    t4 = time.time()
    light = skylayer.SkyLight(sc.sun_alt, sc.sun_hor, sc.moon_alt, sc.moon_hor, sc.moon_illum,
                              view.light_pollution, view.keep_dark)
    bg = skylayer.Background(view.camera)
    png_bg = bg.render(light)
    t5 = time.time()
    ground = skylayer.Ground(view.camera, s['horizon'])
    t6 = time.time()
    png_ground = ground.render(light.ground())
    t7 = time.time()
    if timings is not None:
        timings.update(load=t1 - t0, scene=t2 - t1, stars=t3 - t2, encode=t4 - t3, background=t5 - t4,
                       ground_mask=t6 - t5, ground_frame=t7 - t6, points=len(sc.points), considered=sc.stars_considered)
    return sc, view, png_bg, png_ground, png_stars


def composite(sc, view, png_bg, png_ground, png_stars, width, height):
    import io
    img = Image.open(io.BytesIO(png_bg)).convert('RGBA').resize((width, height), Image.BILINEAR)
    img = Image.alpha_composite(img, Image.open(io.BytesIO(png_ground)).convert('RGBA').resize((width, height),
                                                                                            Image.BILINEAR))
    img = Image.alpha_composite(img, Image.open(io.BytesIO(png_stars)).convert('RGBA'))
    for key, x, y, size, angle, alpha in sc.photos:
        ph = Image.open(os.path.join(scene.PHOTO_DIR, key + '.png')).convert('RGBA')
        ph = ph.resize((max(1, int(size)), max(1, int(size))), Image.BILINEAR).rotate(-angle, Image.BILINEAR)
        ph.putalpha(ph.getchannel('A').point(lambda v: int(v * alpha)))
        img.alpha_composite(ph, (int(x - ph.width / 2), int(y - ph.height / 2)))
    if view.labels != config.NATURAL:
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 20)
        except Exception:
            font = ImageFont.load_default()
        for lab in scene.place_labels(sc.labels, width, height):
            x, y, w, h = lab.placed
            d.text((x, y + 2), lab.text, fill=STYLE.get(lab.style, (220, 220, 220)) + (200,), font=font)
    return img.convert('RGB')


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'couch.png'
    s, when = parse(sys.argv[2:])
    timings = {}
    sc, view, a, b, c = render(s, when, timings=timings)
    composite(sc, view, a, b, c, 1920, 1080).save(out)
    print(out, view.camera.describe(), time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(when)))
    print('sun alt %.1f, moon alt %.1f (%.0f%% lit), limit %.1f, diffuse visibility %.2f' % (
        sc.sun_alt, sc.moon_alt, sc.moon_illum * 100, sc.limit, sc.diffuse_visibility))
    print(', '.join('%s %s' % (k, ('%.0f ms' % (v * 1000)) if isinstance(v, float) else v)
                    for k, v in timings.items()))


if __name__ == '__main__':
    main()

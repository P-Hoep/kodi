"""Generate Couchstronomy's images: control sprites, the add-on icon and fanart.

  python3 tools/make_couch_media.py      # needs Pillow; fanart uses tools/preview_couch.py

The fanart is the add-on's own rendering of Orion rising over Minneapolis.
"""

import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.normpath(os.path.join(HERE, '..', 'screensaver.couchstronomy'))
MEDIA = os.path.join(ADDON, 'resources', 'media')
sys.path.insert(0, HERE)


def radial(size, fn):
    img = Image.new('RGBA', (size, size), (255, 255, 255, 0))
    px = img.load()
    c = (size - 1) / 2.0
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - c, y - c) / c
            px[x, y] = (255, 255, 255, int(max(0.0, min(1.0, fn(d))) * 255))
    return img


def sprites():
    Image.new('RGBA', (8, 8), (255, 255, 255, 255)).save(os.path.join(MEDIA, 'white.png'))
    # Satellite: a small hard core with a soft edge.
    radial(32, lambda d: 1.0 if d < 0.22 else math.exp(-((d - 0.22) / 0.2) ** 2)).save(os.path.join(MEDIA, 'dot.png'))
    # Twinkle halo for bright stars.
    radial(64, lambda d: 0.55 * math.exp(-(d / 0.35) ** 2) + 0.25 * max(0.0, 1 - d) ** 3).save(
        os.path.join(MEDIA, 'glow.png'))
    # Spotlight reticle: a thin ring broken at the four compass points.
    size = 128
    img = Image.new('RGBA', (size, size), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    for start in (15, 105, 195, 285):
        d.arc((6, 6, size - 7, size - 7), start, start + 60, fill=(255, 255, 255, 230), width=3)
    img.save(os.path.join(MEDIA, 'reticle.png'))


def icon():
    size = 512
    img = Image.new('RGB', (size, size), (6, 9, 22))
    d = ImageDraw.Draw(img)
    # A sky gradient.
    for y in range(size):
        t = y / float(size)
        d.line([(0, y), (size, y)], fill=(int(6 + 18 * t), int(9 + 22 * t), int(22 + 40 * t)))
    # Stars: the Big Dipper, roughly as it looks.
    dipper = [(120, 150), (190, 135), (250, 160), (300, 205), (330, 290), (430, 285), (440, 205)]
    for i, (x, y) in enumerate(dipper):
        r = 7 if i in (0, 5, 6) else 6
        glow = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((x - r * 3, y - r * 3, x + r * 3, y + r * 3), fill=(180, 200, 255, 70))
        img.paste(glow.filter(ImageFilter.GaussianBlur(6)), (0, 0), glow.filter(ImageFilter.GaussianBlur(6)))
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 250))
    for a, b in zip(dipper, dipper[1:]):
        d.line([a, b], fill=(110, 140, 210), width=2)
    d.line([dipper[3], dipper[6]], fill=(110, 140, 210), width=2)
    import random
    rng = random.Random(4)
    for _ in range(90):
        x, y = rng.randrange(size), rng.randrange(330)
        v = rng.randrange(90, 210)
        d.point((x, y), fill=(v, v, v + 20))
    # The TV's frame and a sofa silhouette.
    d.rounded_rectangle((18, 18, size - 19, 400), 18, outline=(205, 210, 225), width=14)
    d.rectangle((0, 418, size, size), fill=(16, 16, 22))
    d.rounded_rectangle((70, 430, 442, 500), 24, fill=(70, 48, 40))
    d.rounded_rectangle((40, 418, 110, 500), 20, fill=(84, 58, 48))
    d.rounded_rectangle((402, 418, 472, 500), 20, fill=(84, 58, 48))
    d.rounded_rectangle((110, 405, 402, 450), 16, fill=(96, 66, 54))
    img.resize((256, 256), Image.LANCZOS).save(os.path.join(ADDON, 'icon.png'))


def fanart():
    import preview_couch
    s, when = preview_couch.parse(['time=2026-12-20T05:30', 'azimuth=120', 'tilt=28', 'hfov=75',
                                   'show_lines=true', 'labels=1', 'show_satellites=false'])
    sc, view, a, b, c = preview_couch.render(s, when)
    preview_couch.composite(sc, view, a, b, c, 1920, 1080).save(os.path.join(ADDON, 'fanart.jpg'), quality=88)


def main():
    os.makedirs(MEDIA, exist_ok=True)
    sprites()
    icon()
    fanart()
    print('media written to', MEDIA)


if __name__ == '__main__':
    main()

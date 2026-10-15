"""Draw Live Cams' media: icon, fanart, the fallback card background and overlay textures.

  python3 tools/make_livecams_media.py

Needs Pillow. Writes screensaver.livecams/icon.png, fanart.jpg and resources/media/*.
The loading splash comes from tools/make_splash.py livecams.
"""

import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'screensaver.livecams'))
MEDIA = os.path.join(ROOT, 'resources', 'media')
ACCENT = (77, 208, 225)


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(len(a)))


def gradient(w, h, stops):
    """Vertical gradient through [(t, rgb), ...]."""
    img = Image.new('RGB', (w, h))
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        for k in range(len(stops) - 1):
            t0, c0 = stops[k]
            t1, c1 = stops[k + 1]
            if t0 <= t <= t1:
                c = lerp(c0, c1, (t - t0) / max(1e-9, t1 - t0))
                break
        for x in range(w):
            px[x, y] = c
    return img


def scene(w, h, seed=3):
    """Dawn over the sea: sky, sun with glow, horizon, sea with a glitter path, a headland."""
    rnd = random.Random(seed)
    horizon = int(h * 0.62)
    sky = gradient(w, horizon, [(0, (14, 28, 64)), (0.55, (92, 72, 128)), (0.85, (236, 132, 96)),
                                (1, (255, 196, 128))])
    sea = gradient(w, h - horizon, [(0, (52, 70, 110)), (1, (8, 18, 40))])
    img = Image.new('RGB', (w, h))
    img.paste(sky, (0, 0))
    img.paste(sea, (0, horizon))
    sun_x, sun_r = int(w * 0.62), int(h * 0.085)
    glow = Image.new('L', (w, h), 0)
    ImageDraw.Draw(glow).ellipse((sun_x - sun_r * 4, horizon - sun_r * 4, sun_x + sun_r * 4, horizon + sun_r * 4),
                                 fill=150)
    glow = glow.filter(ImageFilter.GaussianBlur(sun_r * 1.6))
    img = Image.composite(Image.new('RGB', (w, h), (255, 200, 140)), img, glow)
    d = ImageDraw.Draw(img)
    d.ellipse((sun_x - sun_r, horizon - sun_r, sun_x + sun_r, horizon + sun_r), fill=(255, 236, 200))
    d.rectangle((0, horizon, w, h), fill=None)
    img.paste(sea.crop((0, 0, w, 1)).resize((w, 1)), (0, horizon))
    sea_layer = img.crop((0, horizon, w, h))
    img.paste(Image.blend(sea_layer, sea, 0.35), (0, horizon))
    d = ImageDraw.Draw(img)
    # Glitter on the water under the sun.
    for _ in range(int(w * 0.6)):
        y = rnd.uniform(horizon + 2, h)
        spread = (y - horizon) / (h - horizon)
        x = rnd.gauss(sun_x, sun_r * (0.6 + 2.2 * spread))
        length = rnd.uniform(4, 18) * (0.5 + spread) * w / 512
        a = max(0, 1 - abs(x - sun_x) / (sun_r * 3 + 1)) * (1 - spread * 0.6)
        c = lerp((60, 80, 120), (255, 214, 160), a)
        d.line((x - length / 2, y, x + length / 2, y), fill=c, width=max(1, int(w / 512)))
    # A dark headland on the left.
    pts = [(0, horizon - h * 0.10)]
    for i in range(1, 11):
        x = w * 0.34 * i / 10
        pts.append((x, horizon - h * 0.10 * (1 - (i / 10) ** 1.6) + rnd.uniform(-1, 1) * h * 0.006))
    pts += [(w * 0.36, horizon + 1), (0, horizon + 1)]
    d.polygon(pts, fill=(10, 16, 34))
    return img


def rounded_mask(size, radius):
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius, fill=255)
    return mask


def viewfinder(d, box, colour, width, arm):
    x0, y0, x1, y1 = box
    for (cx, cy, sx, sy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        d.line((cx, cy, cx + sx * arm, cy), fill=colour, width=width)
        d.line((cx, cy, cx, cy + sy * arm), fill=colour, width=width)


def icon():
    n, s = 512, 4                      # draw at 4x and scale down for smooth edges
    big = scene(n * s, n * s)
    d = ImageDraw.Draw(big)
    m = 70 * s
    viewfinder(d, (m, m, n * s - m, n * s - m), (255, 255, 255), 14 * s // 2, 70 * s)
    # LIVE badge: red dot and label block, top left inside the frame.
    bx, by = m + 34 * s, m + 34 * s
    d.ellipse((bx, by, bx + 34 * s, by + 34 * s), fill=(244, 67, 54))
    for k, bar in enumerate((64, 44)):
        d.rounded_rectangle((bx + 52 * s, by + (4 + k * 18) * s, bx + (52 + bar) * s, by + (14 + k * 18) * s),
                            5 * s, fill=(255, 255, 255))
    out = big.resize((n, n), Image.LANCZOS).convert('RGBA')
    out.putalpha(rounded_mask(n, 96))
    out.save(os.path.join(ROOT, 'icon.png'), optimize=True)


def fanart():
    img = scene(1920, 1080, seed=5).filter(ImageFilter.GaussianBlur(1.2))
    img.save(os.path.join(ROOT, 'fanart.jpg'), quality=82, optimize=True)


def fallback():
    """The fallback card: a dark, blurred, dimmed dawn so the clock reads clearly."""
    img = scene(960, 540, seed=9).resize((1920, 1080), Image.BICUBIC).filter(ImageFilter.GaussianBlur(28))
    dark = Image.new('RGB', img.size, (4, 8, 16))
    img = Image.blend(img, dark, 0.72)
    # Vignette.
    v = Image.new('L', (1920, 1080), 0)
    ImageDraw.Draw(v).ellipse((-300, -260, 2220, 1340), fill=255)
    v = v.filter(ImageFilter.GaussianBlur(160))
    img = Image.composite(img, dark, v)
    img.save(os.path.join(MEDIA, 'fallback.jpg'), quality=80, optimize=True)


def textures():
    Image.new('RGBA', (8, 8), (255, 255, 255, 255)).save(os.path.join(MEDIA, 'white.png'))
    # Transparent at the top to opaque at the bottom (tinted by colordiffuse in the skin).
    h = 256
    fade = Image.new('RGBA', (4, h))
    for y in range(h):
        t = y / (h - 1.0)
        a = int(255 * (math.sin(t * math.pi / 2) ** 2))
        for x in range(4):
            fade.putpixel((x, y), (255, 255, 255, a))
    fade.save(os.path.join(MEDIA, 'fade_up.png'))


if __name__ == '__main__':
    if not os.path.isdir(MEDIA):
        os.makedirs(MEDIA)
    textures()
    fallback()
    fanart()
    icon()
    for name in ('icon.png', 'fanart.jpg'):
        print('%s: %d KB' % (name, os.path.getsize(os.path.join(ROOT, name)) // 1024))
    for name in sorted(os.listdir(MEDIA)):
        print('media/%s: %d KB' % (name, os.path.getsize(os.path.join(MEDIA, name)) // 1024))

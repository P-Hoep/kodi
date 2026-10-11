"""Generate the add-on's icons. Run with Python 3 + Pillow: python3 tools/make_media.py

Marker icons are white with a dark outline: Kodi's colorDiffuse tints the white
per layer and leaves the outline dark, so one file serves every color.
"""

import math
import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screensaver.godseye.map')
MEDIA = os.path.join(ROOT, 'resources', 'media')
SS = 4  # supersampling factor
WHITE = (255, 255, 255, 255)
DARK = (10, 14, 20, 255)


def canvas(size):
    return Image.new('RGBA', (size * SS, size * SS), (0, 0, 0, 0))


# Rotating markers get one pre-drawn image per 5° of heading, padded so corners
# survive rotation. Kodi's rotate animation pivots on where a control was when the
# animation was set, so rotated markers that move drift; swapping images never does.
HEADING_STEP = 5
ROT_PAD = 1.125  # padded canvas / icon size; screensaver.py draws rotated icons this much larger


def finish(img, size, name, rotations=False):
    img.resize((size, size), Image.LANCZOS).save(os.path.join(MEDIA, name))
    if not rotations:
        return
    folder = os.path.join(MEDIA, 'rot')
    if not os.path.isdir(folder):
        os.makedirs(folder)
    big = int(round(size * ROT_PAD))
    padded = Image.new('RGBA', (big * SS, big * SS), (0, 0, 0, 0))
    offset = (big * SS - img.width) // 2
    padded.paste(img, (offset, offset))
    stem = os.path.splitext(name)[0]
    for heading in range(0, 360, HEADING_STEP):
        # PIL rotates counter-clockwise; headings are clockwise from north.
        turned = padded.rotate(-heading, resample=Image.BICUBIC)
        turned.resize((big, big), Image.LANCZOS).save(os.path.join(folder, '%s_%03d.png' % (stem, heading)))


def scaled(points, size):
    k = size * SS / 64.0
    return [(x * k, y * k) for x, y in points]


def outlined_polygon(draw, points, size, outline=3):
    k = size * SS / 64.0
    draw.polygon(points, fill=DARK)
    # Shrink toward the centroid for the white fill, leaving a dark rim.
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    inner = []
    for x, y in points:
        dx, dy = x - cx, y - cy
        d = math.hypot(dx, dy) or 1
        inner.append((x - dx / d * outline * k, y - dy / d * outline * k))
    draw.polygon(inner, fill=WHITE)


def plane():
    size = 64
    img = canvas(size)
    d = ImageDraw.Draw(img)
    pts = scaled([(32, 3), (36, 10), (36, 24), (60, 38), (60, 44), (36, 37), (35, 52), (43, 58),
                  (43, 62), (32, 59), (21, 62), (21, 58), (29, 52), (28, 37), (4, 44), (4, 38),
                  (28, 24), (28, 10)], size)
    d.polygon(pts, fill=DARK)
    for _ in range(2):  # dark outline around the silhouette
        img = img.filter(ImageFilter.MaxFilter(9))
    d = ImageDraw.Draw(img)
    d.polygon(pts, fill=WHITE)
    finish(img, size, 'plane.png', rotations=True)


def circle():
    size = 64
    img = canvas(size)
    d = ImageDraw.Draw(img)
    s = size * SS
    d.ellipse([2 * SS, 2 * SS, s - 2 * SS, s - 2 * SS], fill=DARK)
    d.ellipse([6 * SS, 6 * SS, s - 6 * SS, s - 6 * SS], fill=(255, 255, 255, 200))
    d.ellipse([s / 2 - 5 * SS, s / 2 - 5 * SS, s / 2 + 5 * SS, s / 2 + 5 * SS], fill=WHITE)
    finish(img, size, 'circle.png')


def ring():
    size = 96
    img = canvas(size)
    d = ImageDraw.Draw(img)
    s = size * SS
    d.ellipse([3 * SS, 3 * SS, s - 3 * SS, s - 3 * SS], outline=DARK, width=9 * SS)
    d.ellipse([5 * SS, 5 * SS, s - 5 * SS, s - 5 * SS], outline=WHITE, width=5 * SS)
    finish(img, size, 'ring.png')


def storm():
    size = 96
    img = canvas(size)
    d = ImageDraw.Draw(img)
    s = size * SS
    c = s / 2.0
    for color, width in ((DARK, 15), (WHITE, 8)):
        for arm in (0, math.pi):
            pts = []
            for i in range(40):
                t = i / 39.0
                ang = arm + t * 2.3
                r = (12 + t * 30) * SS
                pts.append((c + r * math.cos(ang), c + r * math.sin(ang)))
            d.line(pts, fill=color, width=width * SS, joint='curve')
    d.ellipse([c - 16 * SS, c - 16 * SS, c + 16 * SS, c + 16 * SS], fill=DARK)
    d.ellipse([c - 11 * SS, c - 11 * SS, c + 11 * SS, c + 11 * SS], fill=WHITE)
    d.ellipse([c - 5 * SS, c - 5 * SS, c + 5 * SS, c + 5 * SS], fill=DARK)
    finish(img, size, 'storm.png')


def crosshair():
    size = 64
    img = canvas(size)
    d = ImageDraw.Draw(img)
    s = size * SS
    c = s / 2.0
    for color, w in ((DARK, 6), (WHITE, 2)):
        for (x1, y1, x2, y2) in ((c, 4 * SS, c, 24 * SS), (c, s - 24 * SS, c, s - 4 * SS),
                                 (4 * SS, c, 24 * SS, c), (s - 24 * SS, c, s - 4 * SS, c)):
            d.line([x1, y1, x2, y2], fill=color, width=w * SS)
    d.ellipse([c - 4 * SS, c - 4 * SS, c + 4 * SS, c + 4 * SS], fill=DARK)
    d.ellipse([c - 2 * SS, c - 2 * SS, c + 2 * SS, c + 2 * SS], fill=WHITE)
    finish(img, size, 'crosshair.png')


def satellite():
    size = 64
    img = canvas(size)
    d = ImageDraw.Draw(img)
    k = SS * size / 64.0
    # Solar panels either side of a body, drawn dark-outlined then white.
    for color, grow in ((DARK, 3), (WHITE, 0)):
        g = grow * k
        d.rectangle([4 * k - g, 24 * k - g, 24 * k + g, 40 * k + g], fill=color)
        d.rectangle([40 * k - g, 24 * k - g, 60 * k + g, 40 * k + g], fill=color)
        d.rectangle([24 * k - g, 30 * k - g, 40 * k + g, 34 * k + g], fill=color)
        d.ellipse([22 * k - g, 22 * k - g, 42 * k + g, 42 * k + g], fill=color)
    d.line([14 * k, 24 * k, 14 * k, 40 * k], fill=DARK, width=int(2 * k))
    d.line([50 * k, 24 * k, 50 * k, 40 * k], fill=DARK, width=int(2 * k))
    d.ellipse([28 * k, 28 * k, 36 * k, 36 * k], fill=DARK)
    finish(img, size, 'satellite.png')


HOUSE = [(64, 12), (118, 60), (104, 60), (104, 114), (24, 114), (24, 60), (10, 60)]
CHIMNEY = [(84, 22), (98, 22), (98, 47), (84, 34)]


def home(size=128):
    """Two layers drawn on top of each other at the home location:
    home_back.png  - white sticker border + soft shadow, never tinted (visible on any map);
    home_front.png - the house: white fill, dark outline, door and window (tinted per look)."""
    k = SS * size / 128.0
    house = [(x * k, y * k) for x, y in HOUSE]
    chimney = [(x * k, y * k) for x, y in CHIMNEY]

    def silhouette(fill):
        img = canvas(size)
        d = ImageDraw.Draw(img)
        d.polygon(house, fill=fill)
        d.polygon(chimney, fill=fill)
        return img

    # Back: silhouette grown into a white border, over a blurred dark shadow.
    shadow = silhouette((0, 0, 0, 255))
    for _ in range(3):
        shadow = shadow.filter(ImageFilter.MaxFilter(9))
    shadow = shadow.filter(ImageFilter.GaussianBlur(5 * SS))
    shadow.putalpha(shadow.split()[3].point(lambda a: int(a * 0.75)))
    border = silhouette(WHITE)
    for _ in range(3):
        border = border.filter(ImageFilter.MaxFilter(9))
    back = Image.alpha_composite(shadow, border)
    back.resize((size, size), Image.LANCZOS).save(os.path.join(MEDIA, 'home_back.png'))

    # Front: dark outline, white house, dark door and window.
    front = silhouette(DARK)
    inner = canvas(size)
    d = ImageDraw.Draw(inner)
    shrink = 6 * k

    def inset(points, cx=64 * k, cy=70 * k):
        out = []
        for x, y in points:
            dx, dy = x - cx, y - cy
            dist = math.hypot(dx, dy) or 1
            out.append((x - dx / dist * shrink, y - dy / dist * shrink))
        return out
    d.polygon(inset(house), fill=WHITE)
    d.polygon(inset(chimney, 91 * k, 34 * k), fill=WHITE)
    front = Image.alpha_composite(front, inner)
    d = ImageDraw.Draw(front)
    d.rounded_rectangle([54 * k, 78 * k, 74 * k, 108 * k], radius=3 * k, fill=DARK)   # door
    d.rectangle([34 * k, 70 * k, 48 * k, 84 * k], fill=DARK)                          # window
    d.rectangle([80 * k, 70 * k, 94 * k, 84 * k], fill=DARK)                          # window
    front.resize((size, size), Image.LANCZOS).save(os.path.join(MEDIA, 'home_front.png'))


def _bus_badge(d, k):
    """Dark rounded badge with a white (tinted) border and a front-facing bus."""
    navy = (18, 22, 30, 255)
    d.rounded_rectangle([14 * k, 14 * k, 50 * k, 50 * k], radius=8 * k, fill=WHITE)
    d.rounded_rectangle([16.5 * k, 16.5 * k, 47.5 * k, 47.5 * k], radius=6.5 * k, fill=navy)
    # Bus body, windscreen, headlights, wheels.
    d.rounded_rectangle([21.5 * k, 20 * k, 42.5 * k, 42 * k], radius=4 * k, fill=WHITE)
    d.rectangle([23.5 * k, 23.5 * k, 40.5 * k, 31.5 * k], fill=navy)
    d.rectangle([24.5 * k, 21 * k, 39.5 * k, 22.2 * k], fill=navy)
    d.ellipse([24 * k, 35.5 * k, 28 * k, 39.5 * k], fill=navy)
    d.ellipse([36 * k, 35.5 * k, 40 * k, 39.5 * k], fill=navy)
    d.rectangle([23 * k, 42 * k, 26.5 * k, 45 * k], fill=WHITE)
    d.rectangle([37.5 * k, 42 * k, 41 * k, 45 * k], fill=WHITE)


def bus(size=64):
    """bus.png (no direction) and rot/bus_<heading>.png: the badge stays upright and a
    chevron orbits it, pointing the way the bus is heading."""
    k = SS * size / 64.0
    img = canvas(size)
    _bus_badge(ImageDraw.Draw(img), k)
    img.resize((size, size), Image.LANCZOS).save(os.path.join(MEDIA, 'bus.png'))
    folder = os.path.join(MEDIA, 'rot')
    if not os.path.isdir(folder):
        os.makedirs(folder)
    c = 32 * k
    for heading in range(0, 360, HEADING_STEP):
        img = canvas(size)
        d = ImageDraw.Draw(img)
        a = math.radians(heading)
        ux, uy = math.sin(a), -math.cos(a)   # heading as a screen direction
        px, py = -uy, ux                     # perpendicular

        def pt(along, across):
            return (c + ux * along * k + px * across * k, c + uy * along * k + py * across * k)
        tip, base = 30.5, 19
        chevron = [pt(tip, 0), pt(base, 10), pt(base + 4, 0), pt(base, -10)]
        outline = [pt(tip + 1.5, 0), pt(base - 1.8, 12.5), pt(base + 4, 2.8), pt(base - 1.8, -12.5)]
        d.polygon(outline, fill=DARK)
        d.polygon(chevron, fill=WHITE)
        _bus_badge(d, k)
        img.resize((size, size), Image.LANCZOS).save(os.path.join(folder, 'bus_%03d.png' % heading))


def moons(frames=30, size=128):
    """media/moon/moon_NN.png: the moon at age NN/frames of a synodic month, as seen from the
    northern hemisphere (waxing lit on the right)."""
    folder = os.path.join(MEDIA, 'moon')
    if not os.path.isdir(folder):
        os.makedirs(folder)
    big = size * SS
    r = big / 2.0 - 2 * SS
    c = big / 2.0
    for i in range(frames):
        angle = 2 * math.pi * i / frames
        k = math.cos(angle)
        img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
        px = img.load()
        for y in range(big):
            ny = (y + 0.5 - c) / r
            if abs(ny) > 1:
                continue
            half = math.sqrt(1 - ny * ny)
            for x in range(big):
                nx = (x + 0.5 - c) / r
                if abs(nx) > half:
                    continue
                # Waxing: lit to the right of the terminator; waning: to the left.
                lit = nx > k * half if i <= frames / 2 else nx < -k * half
                shade = 0.82 + 0.18 * half  # gentle limb darkening
                px[x, y] = ((int(236 * shade), int(232 * shade), int(214 * shade), 255) if lit
                            else (44, 48, 58, 255))
        img.resize((size, size), Image.LANCZOS).save(os.path.join(folder, 'moon_%02d.png' % i))


def look_overlays():
    """Full-screen overlays for the sensor looks (Kodi stretches them to 1920x1080)."""
    import random
    folder = os.path.join(MEDIA, 'look')
    if not os.path.isdir(folder):
        os.makedirs(folder)
    # Vignette: transparent centre, dark elliptical edge.
    w, h = 480, 270
    img = Image.new('RGBA', (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            d = math.hypot((x + 0.5 - w / 2.0) / (w / 2.0), (y + 0.5 - h / 2.0) / (h / 2.0))
            a = max(0.0, min(1.0, (d - 0.55) / 0.75)) ** 1.6
            px[x, y] = (0, 0, 0, int(a * 255))
    img.save(os.path.join(folder, 'vignette.png'))
    # Scanlines: one row in every three dark; 8 px wide, stretched across the screen.
    img = Image.new('RGBA', (8, 1080))
    for y in range(1080):
        a = 255 if y % 3 == 2 else 0
        for x in range(8):
            img.putpixel((x, y), (0, 0, 0, a))
    img.save(os.path.join(folder, 'scanlines.png'))
    # Grain: four frames of light/dark speckle, cycled to animate.
    rnd = random.Random(7)
    w, h = 320, 180
    for frame in range(4):
        img = Image.new('RGBA', (w, h))
        px = img.load()
        for y in range(h):
            for x in range(w):
                v = 255 if rnd.random() < 0.5 else 0
                px[x, y] = (v, v, v, int(rnd.random() ** 2 * 255))
        img.save(os.path.join(folder, 'grain_%d.png' % frame))


def white():
    Image.new('RGBA', (16, 16), WHITE).save(os.path.join(MEDIA, 'white.png'))


def addon_icon():
    size = 512
    img = Image.new('RGBA', (size * 2, size * 2), (8, 16, 24, 255))
    d = ImageDraw.Draw(img)
    s = size * 2
    c = s / 2.0
    green = (80, 230, 160, 255)
    d.ellipse([c - 380, c - 380, c + 380, c + 380], outline=green, width=20)
    for f in (0.35, 0.7):
        d.ellipse([c - 380 * f, c - 380, c + 380 * f, c + 380], outline=green, width=10)
    for lat in (-0.5, 0.0, 0.5):
        y = c + lat * 380
        half = math.sqrt(max(0, 380 ** 2 - (lat * 380) ** 2))
        d.line([c - half, y, c + half, y], fill=green, width=10)
    for x1, y1, x2, y2 in ((c, 40, c, 220), (c, s - 220, c, s - 40), (40, c, 220, c), (s - 220, c, s - 40, c)):
        d.line([x1, y1, x2, y2], fill=(255, 255, 255, 255), width=22)
    d.ellipse([c - 30, c - 30, c + 30, c + 30], fill=(255, 82, 82, 255))
    img.resize((size, size), Image.LANCZOS).save(os.path.join(ROOT, 'icon.png'))


if __name__ == '__main__':
    if not os.path.isdir(MEDIA):
        os.makedirs(MEDIA)
    for fn in (plane, circle, storm, satellite, bus, home, moons, look_overlays, white, addon_icon):
        fn()
    print('wrote media to', os.path.normpath(MEDIA))

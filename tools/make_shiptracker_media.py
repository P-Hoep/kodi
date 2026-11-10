"""Generate the Ship Tracker media: icon, fanart, the white tint texture, the ocean backdrop,
the photo placeholder and the sixteen rotated ship markers.

The markers are white with a dark navy outline, so the add-on can tint each one to its vessel
type at run time with setColorDiffuse; the outline stays dark and keeps the shape readable on
both the dark ocean and the pale parts of the Blue Marble. The map itself is fetched at run time
from NASA GIBS, not bundled.

Run:  python3 tools/make_shiptracker_media.py
"""

import math
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ADDON = os.path.join(ROOT, 'screensaver.shiptracker')
MEDIA = os.path.join(ADDON, 'resources', 'skins', 'Default', 'media')

ACCENT = (142, 202, 230)
INK = (7, 11, 18)
MARKER_COLOURS = [(142, 202, 230), (255, 183, 3), (255, 143, 171), (181, 228, 140),
                  (244, 162, 97), (233, 196, 106), (179, 136, 235), (187, 187, 187),
                  (255, 255, 255)]


def ensure(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def vertical_gradient(size, top, bottom):
    width, height = size
    strip = Image.new('RGB', (1, height))
    pixels = strip.load()
    for y in range(height):
        u = y / float(max(1, height - 1))
        pixels[0, y] = tuple(int(top[i] + (bottom[i] - top[i]) * u) for i in range(3))
    return strip.resize((width, height), Image.NEAREST)


def radial_glow(image, centre, radius, colour, strength=120, blur=120):
    layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
    cx, cy = centre
    ImageDraw.Draw(layer).ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                                  fill=colour + (strength,))
    return Image.alpha_composite(image, layer.filter(ImageFilter.GaussianBlur(blur)))


def add_waves(image, colour, count=24, alpha=34, width=2, spacing=260.0):
    layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    w, h = image.size
    for index in range(count):
        y = int((index + 1) * h / float(count + 1))
        amplitude = 3 + (index * 7 % 9)
        phase = index * 1.9
        points = [(x, y + int(amplitude * math.sin(x / spacing + phase)))
                  for x in range(0, w + 20, 20)]
        draw.line(points, fill=colour + (alpha,), width=width)
    return Image.alpha_composite(image, layer)


def add_grid(image, colour, step, alpha=20, width=1):
    layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    w, h = image.size
    for x in range(step, w, step):
        draw.line([(x, 0), (x, h)], fill=colour + (alpha,), width=width)
    for y in range(step, h, step):
        draw.line([(0, y), (w, y)], fill=colour + (alpha,), width=width)
    return Image.alpha_composite(image, layer)


def add_vignette(image, strength=170):
    w, h = image.size
    small = Image.new('L', (256, 256), 0)
    ImageDraw.Draw(small).ellipse((-70, -70, 326, 326), fill=255)
    small = small.filter(ImageFilter.GaussianBlur(58))
    mask = small.resize((w, h), Image.BICUBIC)
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    layer.putalpha(Image.eval(mask, lambda value: int((255 - value) * strength / 255)))
    return Image.alpha_composite(image, layer)


def ship_image(size=320, fill=(255, 255, 255, 255), outline=INK + (255,)):
    """A top-down cargo ship pointing up: blunt bow, parallel sides, flat stern, cargo holds,
    a bridge block near the stern and a funnel."""
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    scale = size / 320.0

    def point(x, y):
        return int(round(x * scale)), int(round(y * scale))

    def line_width(pixels):
        return max(1, int(round(pixels * scale)))

    hull = [point(160, 22), point(176, 28), point(192, 48), point(202, 78), point(206, 106),
            point(206, 280), point(196, 296), point(124, 296), point(114, 280),
            point(114, 106), point(118, 78), point(128, 48), point(144, 28)]
    draw.polygon(hull, fill=fill, outline=outline, width=line_width(11))
    for row in range(3):
        top = 116 + row * 36
        for left, right in ((130, 154), (166, 190)):
            draw.rectangle([point(left, top), point(right, top + 28)],
                           fill=(232, 232, 232, 255), outline=outline,
                           width=line_width(4))
    draw.rectangle([point(150, 226), point(170, 242)], fill=(170, 170, 170, 255),
                   outline=outline, width=line_width(4))
    draw.rounded_rectangle([point(126, 248), point(194, 278)], radius=line_width(4),
                           fill=fill, outline=outline, width=line_width(7))
    draw.line([point(130, 263), point(190, 263)], fill=outline, width=line_width(3))
    draw.rectangle([point(126, 284), point(194, 292)], fill=(214, 214, 214, 255),
                   outline=outline, width=line_width(3))
    return image


def make_white():
    ensure(MEDIA)
    Image.new('RGBA', (16, 16), (255, 255, 255, 255)).save(os.path.join(MEDIA, 'white.png'))


def make_icon():
    size = 512
    image = vertical_gradient((size, size), (4, 9, 16), (12, 38, 56)).convert('RGBA')
    image = add_grid(image, ACCENT, 64, alpha=16)
    image = radial_glow(image, (256, 250), 230, ACCENT, 90, 90)
    for index, colour in enumerate(MARKER_COLOURS[:8]):
        angle = index * math.pi / 4.0
        x = int(256 + 178 * math.cos(angle))
        y = int(248 + 178 * math.sin(angle))
        dot = Image.new('RGBA', (26, 26), (0, 0, 0, 0))
        ImageDraw.Draw(dot).ellipse((3, 3, 23, 23), fill=colour + (255,))
        image.alpha_composite(dot, (x - 13, y - 13))
    ship = ship_image(1024).resize((300, 300), Image.LANCZOS)
    image.alpha_composite(ship, (256 - 150, 248 - 150))
    image = add_vignette(image, 120)
    image.resize((size, size), Image.LANCZOS).convert('RGB').save(
        os.path.join(ADDON, 'icon.png'), optimize=True)


def make_fanart():
    width, height = 1920, 1080
    image = vertical_gradient((width, height), (3, 7, 12), (10, 30, 44)).convert('RGBA')
    image = add_grid(image, ACCENT, 120, alpha=12)
    image = add_waves(image, (86, 150, 180), count=30, alpha=26, width=2, spacing=300.0)
    image = radial_glow(image, (1400, 520), 520, ACCENT, 70, 220)

    ship = ship_image(1024).resize((430, 430), Image.LANCZOS)
    ship = ship.rotate(-28, resample=Image.BICUBIC, expand=True)
    layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    layer.alpha_composite(ship, (1400 - ship.width // 2, 520 - ship.height // 2))

    draw = ImageDraw.Draw(layer)
    for index in range(7):
        x = 240 + index * 155
        y = 760 - int(90 * math.sin(index * 0.9))
        colour = MARKER_COLOURS[index % len(MARKER_COLOURS)]
        draw.ellipse((x - 13, y - 13, x + 13, y + 13), fill=colour + (220,))
        draw.line([(x + 22, y + 12), (x + 150, y + 92)], fill=colour + (70,), width=3)
    for index in range(5):
        offset = 120 + index * 26
        draw.arc((1400 - offset, 520 - offset, 1400 + offset, 520 + offset),
                 start=110, end=250, fill=ACCENT + (45 - index * 6,), width=3)
    image = Image.alpha_composite(image, layer)
    image = add_vignette(image, 150)
    image.convert('RGB').save(os.path.join(ADDON, 'fanart.jpg'), quality=90, optimize=True)


def make_sea():
    width, height = 1920, 1080
    image = vertical_gradient((width, height), (2, 5, 10), (5, 15, 24)).convert('RGBA')
    image = add_waves(image, (46, 96, 126), count=32, alpha=22, width=2, spacing=240.0)
    image = add_waves(image, (14, 34, 50), count=14, alpha=26, width=4, spacing=520.0)
    image = add_vignette(image, 190)
    image.convert('RGB').save(os.path.join(MEDIA, 'sea.png'), optimize=True)


def make_placeholder():
    width, height = 864, 576
    image = vertical_gradient((width, height), (8, 20, 30), (4, 10, 16)).convert('RGBA')
    image = add_grid(image, ACCENT, 72, alpha=14)
    image = radial_glow(image, (width // 2, height // 2), 250, ACCENT, 26, 140)
    ship = ship_image(512).resize((230, 230), Image.LANCZOS)
    faded = ship.copy()
    faded.putalpha(Image.eval(faded.getchannel('A'), lambda value: int(value * 0.38)))
    image.alpha_composite(faded, (width // 2 - 115, height // 2 - 115 - 18))
    image = add_waves(image, (70, 120, 150), count=8, alpha=16, width=2, spacing=160.0)
    image.convert('RGB').save(os.path.join(MEDIA, 'photo_placeholder.png'), optimize=True)


def make_ship_icons():
    base = ship_image(320)
    for index in range(16):
        icon = base.rotate(-index * 22.5, resample=Image.BICUBIC)
        icon = icon.resize((80, 80), Image.LANCZOS)
        icon.save(os.path.join(MEDIA, 'ship_%02d.png' % index), optimize=True)


def main():
    ensure(MEDIA)
    make_white()
    make_icon()
    make_fanart()
    make_sea()
    make_placeholder()
    make_ship_icons()
    print('media written to %s' % MEDIA)


if __name__ == '__main__':
    main()

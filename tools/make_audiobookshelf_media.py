"""Draw the Audiobookshelf add-on's icon.png and fanart.jpg (needs Pillow).

Run: python3 tools/make_audiobookshelf_media.py
"""

import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'plugin.audio.audiobookshelf')
SS = 4
BG_TOP, BG_BOTTOM = (24, 32, 44), (10, 13, 19)
SPINES = [(232, 168, 56), (79, 195, 247), (129, 199, 132), (239, 154, 154), (206, 147, 216)]


def gradient(w, h):
    img = Image.new('RGB', (w, h))
    px = img.load()
    for y in range(h):
        f = y / max(1, h - 1)
        c = tuple(int(a + (b - a) * f) for a, b in zip(BG_TOP, BG_BOTTOM))
        for x in range(w):
            px[x, y] = c
    return img


def shelf(draw, x0, base, unit):
    """Five book spines of varied height on a shelf, the middle one leaning."""
    widths = [1.0, 0.8, 1.15, 0.9, 1.0]
    heights = [4.6, 4.0, 5.2, 4.3, 3.7]
    x = x0
    for i, (w, h, colour) in enumerate(zip(widths, heights, SPINES)):
        w, h = w * unit, h * unit
        if i == 3:  # leaning book
            lean = h * 0.2
            pts = [(x, base), (x + w, base), (x + w + lean, base - h * 0.98), (x + lean, base - h * 0.98)]
            draw.polygon(pts, fill=colour)
            x += w + lean + unit * 0.02
            continue
        draw.rounded_rectangle([x, base - h, x + w, base], radius=unit * 0.12, fill=colour)
        for band in (0.18, 0.78):
            y = base - h * band
            draw.rectangle([x + w * 0.15, y - unit * 0.06, x + w * 0.85, y + unit * 0.06], fill=(255, 255, 255, 150))
        x += w + unit * 0.15
    return x


def headphones(draw, cx, cy, r, width):
    draw.arc([cx - r, cy - r, cx + r, cy + r], 180, 360, fill=(240, 244, 248), width=width)
    for side in (-1, 1):
        x = cx + side * r
        draw.rounded_rectangle([x - width * 1.4, cy - width * 0.4, x + width * 1.4, cy + width * 3.2],
                               radius=width * 0.8, fill=(240, 244, 248))


def icon(size=512):
    s = size * SS
    unit = s / 13.0
    end = shelf(ImageDraw.Draw(Image.new('RGBA', (s, s))), 0, s * 0.78, unit)  # measure, then centre
    books = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    shelf(ImageDraw.Draw(books, 'RGBA'), (s - end) / 2, s * 0.78, unit)
    img = gradient(s, s).convert('RGBA')
    draw = ImageDraw.Draw(img, 'RGBA')
    headphones(draw, s / 2, s * 0.47, s * 0.33, int(s * 0.045))
    img.alpha_composite(books)
    draw.rounded_rectangle([s * 0.1, s * 0.78, s * 0.9, s * 0.8], radius=s * 0.01, fill=(120, 130, 145))
    img.convert('RGB').resize((size, size), Image.LANCZOS).save(os.path.join(ROOT, 'icon.png'), optimize=True)


def fanart(w=1920, h=1080):
    img = gradient(w, h)
    glow = Image.new('L', (w, h), 0)
    ImageDraw.Draw(glow).ellipse([w * 0.55, -h * 0.3, w * 1.3, h * 0.9], fill=60)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    img = Image.composite(Image.new('RGB', (w, h), (60, 90, 120)), img, glow)
    img.save(os.path.join(ROOT, 'fanart.jpg'), quality=85, optimize=True)


if __name__ == '__main__':
    icon()
    fanart()
    print('icon.png, fanart.jpg -> %s' % os.path.normpath(ROOT))

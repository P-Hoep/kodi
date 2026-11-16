"""Draw AI Arcade's icon.png and fanart.jpg: pixel lettering from the add-on's own 8x8 font, a
small neural network wired to a pad's buttons, and a CRT-style scanline glow. No game artwork.

  python3 tools/make_aiarcade_media.py
"""

import math
import os
import random
import re

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.normpath(os.path.join(HERE, '..', 'screensaver.aiarcade'))

src = open(os.path.join(ADDON, 'src', 'Font8x8.h')).read()
GLYPHS = [[int(b, 16) for b in re.findall(r'0x[0-9A-Fa-f]{2}', row)]
          for row in re.findall(r'\{(0x[^}]*)\}', src)]


def text(draw, x, y, s, scale, colour):
    for i, ch in enumerate(s):
        g = GLYPHS[ord(ch) - 32]
        for row in range(8):
            for col in range(8):
                if (g[row] >> col) & 1:
                    x0 = x + (i * 8 + col) * scale
                    y0 = y + row * scale
                    draw.rectangle([x0, y0, x0 + scale - 1, y0 + scale - 1], fill=colour)
    return len(s) * 8 * scale


def network(draw, box, seed, scale):
    """Inputs on the left, a hidden layer, eight outputs on the right (A B Sel St U D L R)."""
    rnd = random.Random(seed)
    x0, y0, x1, y1 = box
    layers = [10, 6, 8]
    pos = []
    for li, n in enumerate(layers):
        x = x0 + (x1 - x0) * li / (len(layers) - 1)
        pos.append([(x, y0 + (y1 - y0) * (i + 0.5) / n) for i in range(n)])
    for a, b in ((0, 1), (1, 2), (0, 2)):
        for p in pos[a]:
            for q in pos[b]:
                if rnd.random() < (0.35 if b - a == 1 else 0.08):
                    hot = rnd.random() < 0.3
                    col = (255, 200, 70) if hot else (70, 170, 255)
                    draw.line([p, q], fill=col + (200 if hot else 110,), width=max(1, scale // 2))
    for li, layer in enumerate(pos):
        for (x, y) in layer:
            r = scale * (1.6 if li == 2 else 1.2)
            lit = li == 2 and rnd.random() < 0.4
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 210, 90) if lit else (120, 200, 255))


def background(w, h):
    img = Image.new('RGB', (w, h), (8, 6, 20))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(10 + 30 * t), int(6 + 8 * t), int(28 + 40 * (1 - t))))
    # a perspective grid floor
    hor = int(h * 0.62)
    for i in range(-20, 21):
        d.line([(w / 2 + i * w * 0.02, hor), (w / 2 + i * w * 0.2, h)], fill=(180, 40, 160), width=max(1, w // 900))
    for k in range(1, 14):
        y = hor + (h - hor) * (k / 13) ** 2
        d.line([(0, y), (w, y)], fill=(180, 40, 160), width=max(1, w // 900))
    return img


def scanlines(img, step):
    over = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for y in range(0, img.size[1], step):
        d.line([(0, y), (img.size[0], y)], fill=(0, 0, 0, 70))
    return Image.alpha_composite(img.convert('RGBA'), over)


def glow(img, radius):
    return Image.blend(img, img.filter(ImageFilter.GaussianBlur(radius)), 0.35)


def icon():
    s = 512
    img = background(s, s).convert('RGBA')
    layer = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    network(d, (70, 70, 440, 290), 7, 8)
    w = 8 * 2 * 9
    text(d, (s - 2 * 8 * 9) // 2 + 4, 334 + 4, 'AI', 9, (0, 0, 0, 255))
    text(d, (s - 2 * 8 * 9) // 2, 334, 'AI', 9, (255, 210, 90, 255))
    text(d, (s - 6 * 8 * 5) // 2 + 3, 428 + 3, 'ARCADE', 5, (0, 0, 0, 255))
    text(d, (s - 6 * 8 * 5) // 2, 428, 'ARCADE', 5, (120, 210, 255, 255))
    img = Image.alpha_composite(img, glow(layer, 6))
    img = scanlines(img, 4)
    img.convert('RGB').save(os.path.join(ADDON, 'icon.png'))


def fanart():
    w, h = 1920, 1080
    img = background(w, h).convert('RGBA')
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    network(d, (1300, 160, 1800, 600), 3, 12)
    text(d, 110 + 6, 260 + 6, 'AI ARCADE', 14, (0, 0, 0, 255))
    text(d, 110, 260, 'AI ARCADE', 14, (255, 210, 90, 255))
    text(d, 114, 420, 'IT TEACHES ITSELF', 5, (120, 210, 255, 255))
    text(d, 114, 480, 'TO PLAY YOUR GAMES', 5, (120, 210, 255, 255))
    # a fitness curve climbing
    pts = []
    rnd = random.Random(5)
    best = 10
    for i in range(60):
        best = max(best, best + rnd.uniform(-1, 4) * (1 - i / 80))
        pts.append((150 + i * 11, 900 - best * 3.2))
    d.line(pts, fill=(255, 210, 90, 255), width=6)
    img = Image.alpha_composite(img, glow(layer, 10))
    img = scanlines(img, 5)
    img.convert('RGB').save(os.path.join(ADDON, 'fanart.jpg'), quality=88)


if __name__ == '__main__':
    icon()
    fanart()
    print('icon.png and fanart.jpg written')

"""Draw OpenTrivia's shared window textures and the app's and screensaver's artwork (Pillow).

Run: python3 tools/make_opentrivia_media.py

All the window textures are plain white shapes that Kodi tints with colordiffuse, so one set
serves every theme. The artwork uses DejaVu Sans, which Kodi ships as media/Fonts/arial.ttf, so
no font has to be bundled.

Writes script.module.opentrivia/resources/skins/Default/media/*.png and icon.png + fanart.jpg
for the library, script.opentrivia and screensaver.opentrivia.
"""

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
MODULE = os.path.join(ROOT, 'script.module.opentrivia')
MEDIA = os.path.join(MODULE, 'resources', 'skins', 'Default', 'media')
FONT_PATHS = ['/Applications/Kodi.app/Contents/Resources/Kodi/media/Fonts/arial.ttf',
              '/usr/share/kodi/media/Fonts/arial.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
SS = 4

INK_BG = (11, 13, 17)
INK_CARD = (21, 24, 30)
INK_OPTION = (28, 32, 41)
TEXT = (244, 240, 231)
MUTED = (142, 150, 164)
GOLD = (226, 185, 106)
GOOD = (87, 185, 139)
WHITE = (255, 255, 255)


def font(size):
    for path in FONT_PATHS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def bold(size):
    """DejaVu Sans has no bold file next to it; a same-colour hairline stroke thickens it."""
    return font(size), max(2, size // 26)


def rounded(w, h, r, fill=255, outline=False, width=0):
    """White rounded rectangle (or a ring) on transparent, supersampled."""
    w, h = max(1, int(w)), max(1, int(h))
    big = Image.new('L', (w * SS, h * SS), 0)
    d = ImageDraw.Draw(big)
    if outline:
        d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), r * SS, fill=255)
        inset = width * SS
        d.rounded_rectangle((inset, inset, w * SS - 1 - inset, h * SS - 1 - inset),
                            max(0, r - width) * SS, fill=0)
    else:
        d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), r * SS, fill=fill)
    img = Image.new('RGBA', (w, h), (255, 255, 255, 0))
    img.putalpha(big.resize((w, h), Image.LANCZOS))
    return img


def shadow(w, h, r, blur, pad):
    alpha = Image.new('L', (w + 2 * pad, h + 2 * pad), 0)
    ImageDraw.Draw(alpha).rounded_rectangle((pad, pad, pad + w, pad + h), r, fill=140)
    img = Image.new('RGBA', alpha.size, (255, 255, 255, 0))
    img.putalpha(alpha.filter(ImageFilter.GaussianBlur(blur)))
    return img


def radial(size, strength=1.0):
    alpha = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(alpha)
    steps = 64
    for i in range(steps):
        t = i / float(steps)
        rad = size / 2.0 * (1 - t)
        a = int(255 * (t ** 1.7) * strength)
        d.ellipse((size / 2.0 - rad, size / 2.0 - rad, size / 2.0 + rad, size / 2.0 + rad), fill=a)
    img = Image.new('RGBA', (size, size), (255, 255, 255, 0))
    img.putalpha(alpha.filter(ImageFilter.GaussianBlur(size / 22.0)))
    return img


def tint(shape, colour, alpha=255):
    img = Image.new('RGBA', shape.size, colour + (alpha,))
    img.putalpha(shape.split()[3])
    return img


def glyph(size, kind):
    """A white check or cross, for the option badges."""
    big = Image.new('L', (size * SS, size * SS), 0)
    d = ImageDraw.Draw(big)
    s, w = size * SS, int(size * SS * 0.13)
    if kind == 'check':
        pts = [(s * 0.22, s * 0.52), (s * 0.43, s * 0.73), (s * 0.79, s * 0.29)]
        d.line(pts, fill=255, width=w, joint='curve')
    else:
        d.line([(s * 0.27, s * 0.27), (s * 0.73, s * 0.73)], fill=255, width=w)
        d.line([(s * 0.73, s * 0.27), (s * 0.27, s * 0.73)], fill=255, width=w)
    img = Image.new('RGBA', (size, size), (255, 255, 255, 0))
    img.putalpha(big.resize((size, size), Image.LANCZOS))
    return img


def textures():
    os.makedirs(MEDIA, exist_ok=True)
    Image.new('RGBA', (8, 8), (255, 255, 255, 255)).save(os.path.join(MEDIA, 'white.png'))
    for size, radius in ((128, 32), (96, 28), (96, 24), (64, 22), (64, 16), (48, 12)):
        rounded(size, size, radius).save(os.path.join(MEDIA, 'round%d.png' % radius))
    for size, radius, thick in ((128, 32, 2), (96, 28, 2), (96, 24, 2)):
        suffix = '_thick' if thick > 2 else ''
        rounded(size, size, radius, outline=True, width=thick).save(
            os.path.join(MEDIA, 'outline%d%s.png' % (radius, suffix)))
    rounded(96, 96, 28, outline=True, width=4).save(os.path.join(MEDIA, 'outline28_thick.png'))
    rounded(96, 96, 24, outline=True, width=4).save(os.path.join(MEDIA, 'outline24_thick.png'))
    shadow(128, 128, 32, 24, 64).save(os.path.join(MEDIA, 'shadow.png'))
    radial(512).save(os.path.join(MEDIA, 'glow.png'))
    for kind in ('check', 'cross'):
        glyph(96, kind).save(os.path.join(MEDIA, '%s.png' % kind))
    # A soft vignette, tinted dark at the edges for depth.
    w, h = 480, 270
    vig = Image.new('L', (w, h), 0)
    px = vig.load()
    for y in range(h):
        for x in range(w):
            dx, dy = (x - w / 2) / (w / 2), (y - h / 2) / (h / 2)
            d = (dx * dx + dy * dy) ** 0.5 / 1.414
            px[x, y] = int(max(0.0, d - 0.45) / 0.55 * 120)
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    img.putalpha(vig.filter(ImageFilter.GaussianBlur(3)))
    img.save(os.path.join(MEDIA, 'vignette.png'))
    print('textures ->', MEDIA)


def text(draw, xy, message, size, fill, weight=False, anchor='la'):
    f, stroke = (bold(size) if weight else (font(size), 0))
    draw.text(xy, message, font=f, fill=fill, anchor=anchor,
              stroke_width=stroke, stroke_fill=fill)


def option_row(img, draw, x, y, w, h, letter, message, fill, text_fill, badge_fill, badge_text,
               check=False, check_fill=GOOD):
    draw.rounded_rectangle((x, y, x + w, y + h), h // 2 if h < 70 else 20, fill=fill)
    r = h - 20
    draw.rounded_rectangle((x + 10, y + 10, x + 10 + r, y + h - 10), 10, fill=badge_fill)
    if check:
        mark = tint(glyph(64, 'check'), check_fill).resize((int(r * 0.7), int(r * 0.7)), Image.LANCZOS)
        img.alpha_composite(mark, (int(x + 10 + (r - mark.width) / 2), int(y + (h - mark.height) / 2)))
    else:
        text(draw, (x + 10 + r / 2, y + h / 2 + 1), letter, int(h * 0.34), badge_text, weight=True, anchor='mm')
    text(draw, (x + 20 + r + 24, y + h / 2 + 1), message, int(h * 0.31), text_fill, anchor='lm')


def fanart(accent=GOLD):
    w, h = 1920, 1080
    img = Image.new('RGBA', (w, h), INK_BG + (255,))
    glow = radial(int(w * 0.9), 1.0)
    img.alpha_composite(tint(glow, accent, 46), (int(w * 0.45), -int(h * 0.15)))
    card_w, card_h = 1120, 610
    cx, cy = (w - card_w) // 2, (h - card_h) // 2 + 55
    img.alpha_composite(shadow(card_w, card_h, 44, 34, 120), (cx - 120, cy - 80))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((cx, cy, cx + card_w, cy + card_h), 44, fill=INK_CARD)
    draw.rounded_rectangle((cx + 40, cy + 92, cx + 50, cy + card_h - 92), 5, fill=accent)
    text(draw, (cx + 88, cy + 62), 'QUESTION 07', 26, accent, weight=True)
    text(draw, (cx + 88, cy + 112), 'Which planet has the most moons?', 52, TEXT, weight=True)
    rows = [('A', 'Jupiter', False), ('B', 'Saturn', True), ('C', 'Neptune', False), ('D', 'Uranus', False)]
    for i, (letter, label, good) in enumerate(rows):
        y = cy + 220 + i * 86
        option_row(img, draw, cx + 88, y, card_w - 176, 72, letter, label,
                   GOOD if good else INK_OPTION, WHITE if good else TEXT,
                   WHITE if good else accent, INK_CARD if good else INK_CARD, check=good)
    # Title block top-left.
    text(draw, (112, 74), 'OPEN TRIVIA', 68, TEXT, weight=True)
    text(draw, (116, 160), 'A QUESTION. FOUR ANSWERS.', 26, accent, weight=True)
    text(draw, (w - 112, h - 78), 'THE ANSWER AFTER A FEW SECONDS', 24, MUTED, anchor='ra')
    return img


def icon(size, accent=GOLD, kind='app'):
    s = size
    img = Image.new('RGBA', (s, s), INK_BG + (255,))
    glow = radial(int(s * 1.2), 0.8)
    img.alpha_composite(tint(glow, accent, 34), (-int(s * 0.2), -int(s * 0.3)))
    draw = ImageDraw.Draw(img)
    pad = int(s * 0.16)
    draw.rounded_rectangle((pad, pad, s - pad, s - pad), int(s * 0.1), fill=INK_CARD)
    draw.rounded_rectangle((pad + int(s * 0.045), pad + int(s * 0.18), pad + int(s * 0.06),
                            s - pad - int(s * 0.18)), int(s * 0.008), fill=accent)
    text(draw, (pad + int(s * 0.12), pad + int(s * 0.09)), '?', int(s * 0.36), TEXT, weight=True)
    rows = [('A', False), ('B', True), ('C', False)]
    for i, (letter, good) in enumerate(rows):
        y = pad + int(s * 0.46) + i * int(s * 0.14)
        draw.rounded_rectangle((pad + int(s * 0.12), y, s - pad - int(s * 0.09), y + int(s * 0.1)),
                               int(s * 0.03), fill=GOOD if good else INK_OPTION)
        draw.rounded_rectangle((pad + int(s * 0.14), y + int(s * 0.02), pad + int(s * 0.2),
                                y + int(s * 0.08)), int(s * 0.012), fill=WHITE if good else accent)
    if kind in ('app', 'screensaver'):
        r = int(s * 0.12)
        bx, by = s - pad - r, s - pad - r
        draw.ellipse((bx - r, by - r, bx + r, by + r), fill=accent)
        if kind == 'app':
            mark = tint(glyph(64, 'check'), INK_BG)
            img.alpha_composite(mark.resize((int(r * 1.2), int(r * 1.2)), Image.LANCZOS), (bx - int(r * 0.6), by - int(r * 0.6)))
        else:
            draw.arc((bx - int(r * 0.55), by - int(r * 0.55), bx + int(r * 0.55), by + int(r * 0.55)),
                     300, 60, fill=INK_BG, width=max(2, int(s * 0.018)))
            draw.line((bx, by - int(r * 0.55), bx, by), fill=INK_BG, width=max(2, int(s * 0.018)))
    return img


def write_art():
    targets = [(MODULE, (141, 150, 164), 'module'), (ROOT + '/script.opentrivia', GOLD, 'app'),
               (ROOT + '/screensaver.opentrivia', GOLD, 'screensaver')]
    for folder, accent, kind in targets:
        icon(512, accent, kind).convert('RGB').save(os.path.join(folder, 'icon.png'))
        if kind != 'module':
            fanart(accent).convert('RGB').save(os.path.join(folder, 'fanart.jpg'), quality=90)


if __name__ == '__main__':
    textures()
    write_art()
    print('icons and fanart written')

"""Draw Sheetcards' media: the shared window textures (all plain white, tinted in Kodi with
colordiffuse so one set serves every theme) and the front-ends' icons and fanart.

  python3 tools/make_sheetcards_media.py

Needs Pillow. Writes script.module.sheetcards/resources/skins/Default/media/*.png and
icon.png + fanart.jpg for script.sheetcards, screensaver.sheetcards and the library.
Text in the artwork uses DejaVu Sans (free licence), which Kodi ships as media/Fonts/arial.ttf.
"""

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
MEDIA = os.path.join(ROOT, 'script.module.sheetcards', 'resources', 'skins', 'Default', 'media')
FONT_PATHS = ['/Applications/Kodi.app/Contents/Resources/Kodi/media/Fonts/arial.ttf',   # DejaVu Sans
              '/usr/share/kodi/media/Fonts/arial.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
SS = 4  # supersampling for smooth edges

INDIGO = (99, 102, 241)
NIGHT_BG = (14, 17, 22)
NIGHT_CARD = (26, 31, 39)
TEXT = (242, 244, 247)
MUTED = (154, 163, 175)
GOOD = (52, 199, 123)


def font(size):
    for path in FONT_PATHS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def rounded(w, h, r, fill=255, outline=None, width=0):
    """White rounded rectangle on transparent, supersampled. outline: ring only, width px."""
    big = Image.new('L', (w * SS, h * SS), 0)
    d = ImageDraw.Draw(big)
    if outline:
        d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), r * SS, fill=255)
        inset = width * SS
        d.rounded_rectangle((inset, inset, w * SS - 1 - inset, h * SS - 1 - inset), max(0, r - width) * SS, fill=0)
    else:
        d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), r * SS, fill=fill)
    alpha = big.resize((w, h), Image.LANCZOS)
    img = Image.new('RGBA', (w, h), (255, 255, 255, 0))
    img.putalpha(alpha)
    return img


def white_with_alpha(alpha):
    img = Image.new('RGBA', alpha.size, (255, 255, 255, 0))
    img.putalpha(alpha)
    return img


def shadow(w, h, r, blur, pad):
    alpha = Image.new('L', (w + 2 * pad, h + 2 * pad), 0)
    ImageDraw.Draw(alpha).rounded_rectangle((pad, pad, pad + w, pad + h), r, fill=150)
    return white_with_alpha(alpha.filter(ImageFilter.GaussianBlur(blur)))


def radial(size, inner=1.0):
    """Soft radial glow, white, alpha falling off from the centre."""
    alpha = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(alpha)
    steps = 64
    for i in range(steps):
        t = i / float(steps)
        rad = size / 2.0 * (1 - t)
        a = int(255 * (t ** 1.6) * inner)
        d.ellipse((size / 2.0 - rad, size / 2.0 - rad, size / 2.0 + rad, size / 2.0 + rad), fill=a)
    return white_with_alpha(alpha.filter(ImageFilter.GaussianBlur(size / 24.0)))


def icon_shape(size, kind):
    big = Image.new('L', (size * SS, size * SS), 0)
    d = ImageDraw.Draw(big)
    s = size * SS
    w = int(s * 0.12)
    if kind == 'check':
        d.line([(s * 0.2, s * 0.53), (s * 0.42, s * 0.74), (s * 0.8, s * 0.3)], fill=255, width=w, joint='curve')
        for x, y in ((s * 0.2, s * 0.53), (s * 0.42, s * 0.74), (s * 0.8, s * 0.3)):
            d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=255)
    elif kind == 'cross':
        for a, b in (((0.25, 0.25), (0.75, 0.75)), ((0.75, 0.25), (0.25, 0.75))):
            d.line([(s * a[0], s * a[1]), (s * b[0], s * b[1])], fill=255, width=w)
            for x, y in (a, b):
                d.ellipse((s * x - w / 2, s * y - w / 2, s * x + w / 2, s * y + w / 2), fill=255)
    elif kind == 'circle':
        d.ellipse((0, 0, s - 1, s - 1), fill=255)
    elif kind == 'ring':
        d.ellipse((0, 0, s - 1, s - 1), fill=255)
        inset = int(s * 0.09)
        d.ellipse((inset, inset, s - 1 - inset, s - 1 - inset), fill=0)
    return white_with_alpha(big.resize((size, size), Image.LANCZOS))


def bars(folder):
    """Mastery bar fills, 0..100 % in 5 % steps (a fixed-size image per step: list items
    cannot size a control from a value)."""
    w, h = 240, 8
    for step in range(21):
        img = Image.new('RGBA', (w, h), (255, 255, 255, 0))
        fill = int(round(w * step / 20.0))
        if fill:
            img.paste(rounded(max(fill, h), h, h // 2), (0, 0))
        img.save(os.path.join(folder, 'bar_%02d.png' % (step * 5)))


def textures():
    os.makedirs(MEDIA, exist_ok=True)
    Image.new('RGBA', (8, 8), (255, 255, 255, 255)).save(os.path.join(MEDIA, 'white.png'))
    rounded(128, 128, 32).save(os.path.join(MEDIA, 'round32.png'))          # card, <texture border="32">
    rounded(96, 96, 28).save(os.path.join(MEDIA, 'round28.png'))            # option pills, tiles, buttons
    rounded(128, 128, 32, outline=True, width=2).save(os.path.join(MEDIA, 'outline32.png'))
    rounded(96, 96, 28, outline=True, width=2).save(os.path.join(MEDIA, 'outline28.png'))
    rounded(96, 96, 28, outline=True, width=4).save(os.path.join(MEDIA, 'outline28_thick.png'))
    rounded(64, 64, 22).save(os.path.join(MEDIA, 'round22.png'))            # chips
    shadow(128, 128, 32, 22, 64).save(os.path.join(MEDIA, 'shadow.png'))  # 256x256, border 96
    radial(512).save(os.path.join(MEDIA, 'glow.png'))
    for kind in ('check', 'cross', 'circle', 'ring'):
        icon_shape(96, kind).save(os.path.join(MEDIA, '%s.png' % kind))
    bars(MEDIA)


# ------------------------------------------------------------------ artwork

def card_art(size, scale, offset, angle, fill, text, text_fill, label, label_fill):
    w, h = int(size[0] * scale), int(size[1] * scale)
    layer = Image.new('RGBA', (w + 200, h + 200), (0, 0, 0, 0))
    sh = shadow(w, h, int(48 * scale), 30 * scale, 100)
    layer.alpha_composite(Image.merge('RGBA', (sh.split()[0].point(lambda v: 0),) * 3 + (sh.split()[3],)))
    body = rounded(w, h, int(48 * scale))
    tinted = Image.new('RGBA', (w, h), fill + (255,))
    tinted.putalpha(body.split()[3])
    layer.alpha_composite(tinted, (100, 100))
    d = ImageDraw.Draw(layer)
    f = font(int(h * 0.42))
    tw = d.textlength(text, font=f)
    d.text((100 + (w - tw) / 2, 100 + h * 0.18), text, font=f, fill=text_fill)
    if label:
        lf = font(int(h * 0.085))
        lw = d.textlength(label, font=lf)
        d.text((100 + (w - lw) / 2, 100 + h * 0.08), label, font=lf, fill=label_fill)
    return layer.rotate(angle, resample=Image.BICUBIC, expand=True), offset


def artwork(w, h, accent, glyph_front, glyph_back, kicker=('QUESTION', 'ANSWER'), check=False):
    img = Image.new('RGBA', (w, h), NIGHT_BG + (255,))
    glow = radial(int(max(w, h) * 1.1), 1.0)
    tint = Image.new('RGBA', glow.size, accent + (0,))
    tint.putalpha(glow.split()[3].point(lambda v: int(v * 0.30)))
    img.alpha_composite(tint, ((w - glow.size[0]) // 2, (h - glow.size[1]) // 2))
    s = min(w / 1.3, h) / 1000.0
    back, _ = card_art((900, 560), s, None, 8, accent, glyph_back, (255, 255, 255), kicker[1], (225, 228, 255))
    front, _ = card_art((900, 560), s, None, -6, NIGHT_CARD, glyph_front, TEXT, kicker[0], MUTED)
    img.alpha_composite(back, (int(w / 2 - back.size[0] / 2 + 150 * s), int(h / 2 - back.size[1] / 2 - 90 * s)))
    img.alpha_composite(front, (int(w / 2 - front.size[0] / 2 - 120 * s), int(h / 2 - front.size[1] / 2 + 80 * s)))
    if check:
        r = int(110 * s)
        cx, cy = int(w / 2 + 330 * s), int(h / 2 + 260 * s)
        circle = icon_shape(2 * r, 'circle')
        green = Image.new('RGBA', circle.size, GOOD + (255,))
        green.putalpha(circle.split()[3])
        img.alpha_composite(green, (cx - r, cy - r))
        mark = icon_shape(2 * r, 'check')
        img.alpha_composite(mark, (cx - r, cy - r))
    return img


def write_art():
    targets = [
        ('script.sheetcards', INDIGO, '?', 'A', True),
        ('screensaver.sheetcards', (20, 184, 166), 'Q', 'A', False),
        ('script.module.sheetcards', (100, 116, 139), '{ }', 'A', False),
    ]
    for addon, accent, front, back, check in targets:
        folder = os.path.join(ROOT, addon)
        icon = artwork(512, 512, accent, front, back, check=check)
        # Kodi shows icons in a square; keep the art centred with breathing room.
        icon.convert('RGB').save(os.path.join(folder, 'icon.png'))
        if addon != 'script.module.sheetcards':
            artwork(1920, 1080, accent, front, back, check=check).convert('RGB').save(
                os.path.join(folder, 'fanart.jpg'), quality=88)


if __name__ == '__main__':
    textures()
    write_art()
    print('textures ->', MEDIA)

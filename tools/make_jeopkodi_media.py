"""Render Jeopkodi's glyph images, vignette, icon and fanart (Pillow).

Run: python3 tools/make_jeopkodi_media.py path/to/KorinnaStd-Bold.ttf

The font is not kept in the repository; the glyph images rendered from it are.

Add-ons cannot register fonts, so every character is a pre-rendered PNG: Korinna Bold with the
classic hard drop shadow, in white and in Jeopardy yellow. resources/media/glyphs/metrics.json
holds the advance widths and kerning so the screensaver can wrap and centre text exactly
without measuring anything at run time. Every glyph image is the same height (HEIGHT), so a line
is just the images placed side by side.
"""

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'screensaver.jeopkodi'))
MEDIA = os.path.join(ROOT, 'resources', 'media')

SIZE = 160                 # font size the glyphs are drawn at; the screensaver scales them
SHADOW = 0.055             # shadow offset in em
BLUR = 0.012               # shadow softening in em
WHITE = (255, 255, 255)
YELLOW = (255, 204, 0)
BLUE = (6, 12, 233)        # #060CE9

# The characters the clue database uses that the font has (anything else is mapped or dropped).
CODES = list(range(0x21, 0x7F)) + list(range(0xA1, 0x100)) + [0x152, 0x153, 0x160, 0x161, 0x17D, 0x17E,
                                                               0x2022, 0x20AC]


def has_glyph(font, ch):
    return font.getmask(ch).getbbox() is not None


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    font = ImageFont.truetype(sys.argv[1], SIZE)
    ascent, descent = font.getmetrics()
    off = round(SIZE * SHADOW)
    pad = off + round(SIZE * BLUR * 3) + 2
    top_pad = round(SIZE * BLUR * 3) + 2
    height = ascent + descent + top_pad + pad
    metrics = {'size': SIZE, 'height': height, 'ascent': ascent + top_pad, 'adv': {}, 'kern': {}}
    codes = [c for c in CODES if has_glyph(font, chr(c))]
    metrics['space'] = font.getlength(' ')
    for colour, name in ((WHITE, 'w'), (YELLOW, 'y')):
        folder = os.path.join(MEDIA, 'glyphs', name)
        os.makedirs(folder, exist_ok=True)
        for code in codes:
            ch = chr(code)
            adv = font.getlength(ch)
            width = int(adv) + 1 + pad + round(SIZE * 0.05)       # room for overhang and shadow
            left = round(SIZE * 0.025)
            mask = Image.new('L', (width, height), 0)
            ImageDraw.Draw(mask).text((left, top_pad), ch, font=font, fill=255)
            shadow = Image.new('L', (width, height), 0)
            ImageDraw.Draw(shadow).text((left + off, top_pad + off), ch, font=font, fill=255)
            shadow = shadow.filter(ImageFilter.GaussianBlur(SIZE * BLUR))
            out = Image.new('RGBA', (width, height), (0, 0, 0, 0))
            out.paste(Image.new('RGBA', (width, height), (0, 0, 0, 255)), (0, 0), shadow.point(lambda v: min(255, v * 2)))
            out.paste(Image.new('RGBA', (width, height), colour + (255,)), (0, 0), mask)
            out.save(os.path.join(folder, '%04x.png' % code), optimize=True)
            if name == 'w':
                metrics['adv'][str(code)] = [adv, left, width]
    # kerning for the pairs that matter in capitals and digits
    keys = [c for c in codes if chr(c).isupper() or chr(c) in '.,\'"-:;']
    for a in keys:
        for b in keys:
            k = font.getlength(chr(a) + chr(b)) - font.getlength(chr(a)) - font.getlength(chr(b))
            if abs(k) >= 0.5:
                metrics['kern']['%d,%d' % (a, b)] = round(k, 2)
    metrics['codes'] = codes
    with open(os.path.join(MEDIA, 'glyphs', 'metrics.json'), 'w') as f:
        json.dump(metrics, f, separators=(',', ':'))

    # Vignette: transparent in the middle, a little darker at the corners, like the studio screens.
    w, h = 480, 270
    vig = Image.new('L', (w, h), 0)
    px = vig.load()
    for y in range(h):
        for x in range(w):
            dx, dy = (x - w / 2) / (w / 2), (y - h / 2) / (h / 2)
            d = (dx * dx + dy * dy) ** 0.5 / 1.414
            px[x, y] = int(max(0.0, d - 0.35) / 0.65 * 150)
    vig = vig.filter(ImageFilter.GaussianBlur(4))
    img = Image.new('RGBA', (w, h), (0, 0, 40, 0))
    img.putalpha(vig)
    img.save(os.path.join(MEDIA, 'vignette.png'), optimize=True)
    Image.new('RGBA', (4, 4), (255, 255, 255, 255)).save(os.path.join(MEDIA, 'white.png'))

    # Icon and fanart.
    def title_card(size, lines):
        card = Image.new('RGB', size, BLUE)
        card.paste(Image.open(os.path.join(MEDIA, 'vignette.png')).resize(size), (0, 0),
                   Image.open(os.path.join(MEDIA, 'vignette.png')).resize(size))
        return card

    def text_image(text, scale, folder):
        gl = []
        x = 0
        for ch in text:
            if ch == ' ':
                x += metrics['space'] * scale
                continue
            code = ord(ch)
            if str(code) not in metrics['adv']:
                continue
            adv, left, _ = metrics['adv'][str(code)]
            img = Image.open(os.path.join(MEDIA, 'glyphs', folder, '%04x.png' % code))
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
            gl.append((round(x), img))
            x += adv * scale
        total = int(x + 40)
        canvas = Image.new('RGBA', (total, gl[0][1].height), (0, 0, 0, 0))
        for gx, img in gl:
            canvas.alpha_composite(img, (gx, 0))
        return canvas

    for name, size, scale_w in (('icon.png', (512, 512), 0.42), ('fanart.jpg', (1920, 1080), 1.0)):
        card = title_card(size, None)
        title = text_image('JEOPKODI', scale_w * size[0] / 1100, 'w')
        sub = text_image('WHAT IS A SCREENSAVER?', scale_w * size[0] / 4200, 'y')
        x = (size[0] - title.width) // 2
        y = (size[1] - title.height - sub.height) // 2
        card = card.convert('RGBA')
        card.alpha_composite(title, (x, y))
        card.alpha_composite(sub, ((size[0] - sub.width) // 2, y + title.height + int(size[1] * 0.02)))
        card.convert('RGB').save(os.path.join(ROOT, name), quality=90)
    print('glyphs:', len(codes), 'height:', height)


if __name__ == '__main__':
    main()

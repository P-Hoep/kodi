"""Generate Word Clock's glyph images, card textures, icon and fanart.

  python3 tools/make_wordclock_media.py

Downloads the eight OFL fonts from github.com/google/fonts into tools/.wordclock-fonts/ (once),
then writes, under screensaver.wordclock/:
  resources/media/fonts/<font>/<L>r.png, <L>b.png   white glyphs, regular and bold (128 px box)
  resources/media/fonts/<font>/<L>gr.png, <L>gb.png their glows (96 px for a 1.5-cell box)
  resources/media/white.png, dot.png
  resources/skins/Default/media/card_round.png      9-slice card (border="CARD_RADIUS")
  icon.png (512) and fanart.jpg (1920x1080), drawn with tools/preview_wordclock.py
Every glyph in a font shares one baseline and cap height (half the box), and sits centred on
its ink horizontally, so every font fills the same cells. Needs Pillow.
"""

import os
import sys
import urllib.request

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'screensaver.wordclock'))
CACHE = os.path.join(HERE, '.wordclock-fonts')
MEDIA = os.path.join(ROOT, 'resources', 'media')
SKIN_MEDIA = os.path.join(ROOT, 'resources', 'skins', 'Default', 'media')
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from resources.lib import config, grid  # noqa: E402

GOOGLE = 'https://github.com/google/fonts/raw/main/ofl/'
BOX = 128              # glyph image side
CAP = 0.6              # cap height as a fraction of the box (as in the reference)
GLOW_BOX = 192         # rendered at 1.5x the glyph box ...
GLOW_OUT = 96          # ... and stored small (it is a blur anyway)
GLOW_BLUR = 9
CARD = 256
CARD_RADIUS = 104      # keep in step with the border in screensaver-wordclock.xml

# folder -> (Google Fonts dir, file, {axis name: value} for regular, the same for bold)
FONTS = {
    'inter': ('inter', 'Inter[opsz,wght].ttf', {'Optical size': 32, 'Weight': 400}, {'Weight': 700}),
    'montserrat': ('montserrat', 'Montserrat[wght].ttf', {'Weight': 400}, {'Weight': 700}),
    'raleway': ('raleway', 'Raleway[wght].ttf', {'Weight': 200}, {'Weight': 500}),
    'playfair': ('playfairdisplay', 'PlayfairDisplay[wght].ttf', {'Weight': 400}, {'Weight': 800}),
    'jetbrains': ('jetbrainsmono', 'JetBrainsMono[wght].ttf', {'Weight': 400}, {'Weight': 800}),
    'comfortaa': ('comfortaa', 'Comfortaa[wght].ttf', {'Weight': 400}, {'Weight': 700}),
    'doto': ('doto', 'Doto[ROND,wght].ttf', {'Roundness': 100, 'Weight': 400}, {'Weight': 900}),
    'stencil': ('bigshouldersstencil', 'BigShouldersStencil[opsz,wght].ttf',
                {'Optical size': 72, 'Weight': 500}, {'Weight': 800}),
}


def fetch(folder, filename):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, filename)
    if not os.path.exists(path):
        url = GOOGLE + folder + '/' + urllib.request.quote(filename)
        print('downloading', url)
        urllib.request.urlretrieve(url, path)
        urllib.request.urlretrieve(GOOGLE + folder + '/OFL.txt', os.path.join(CACHE, folder + '-OFL.txt'))
    return path


def load(path, size, axes):
    font = ImageFont.truetype(path, size)
    names = [a['name'] if isinstance(a['name'], str) else a['name'].decode() for a in font.get_variation_axes()]
    current = [a['default'] for a in font.get_variation_axes()]
    values = [axes.get(n, current[i]) for i, n in enumerate(names)]
    font.set_variation_by_axes(values)
    return font


def font_at_cap(path, axes, cap_px):
    """The font size whose 'H' is cap_px tall."""
    probe = load(path, 400, axes)
    top, bottom = probe.getbbox('H', anchor='ls')[1::2]
    return load(path, max(8, int(round(400.0 * cap_px / (bottom - top)))), axes)


def glyph(font, letter, box, cap_px):
    """White letter on transparent, baseline so the cap height is centred, ink centred."""
    left, _top, right, _bottom = font.getbbox(letter, anchor='ls')
    mask = Image.new('L', (box, box), 0)
    ImageDraw.Draw(mask).text((box / 2.0 - (left + right) / 2.0, box / 2.0 + cap_px / 2.0), letter,
                              font=font, fill=255, anchor='ls')
    img = Image.new('RGBA', (box, box), (255, 255, 255, 0))
    img.putalpha(mask)
    return img


def glow(font, letter):
    img = glyph(font, letter, GLOW_BOX, BOX * CAP)
    alpha = img.getchannel('A').filter(ImageFilter.GaussianBlur(GLOW_BLUR))
    alpha = alpha.point(lambda v: min(255, int(v * 1.8)))
    out = Image.new('RGBA', (GLOW_BOX, GLOW_BOX), (255, 255, 255, 0))
    out.putalpha(alpha)
    return out.resize((GLOW_OUT, GLOW_OUT), Image.LANCZOS)


def save(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, optimize=True)


def fonts():
    letters = grid.letters()
    for name, (folder, filename, regular, bold) in FONTS.items():
        path = fetch(folder, filename)
        bold = dict(regular, **bold)
        out = os.path.join(MEDIA, 'fonts', name)
        total = 0
        for weight, axes in (('r', regular), ('b', bold)):
            font = font_at_cap(path, axes, BOX * CAP)
            for letter in letters:
                save(glyph(font, letter, BOX, BOX * CAP), os.path.join(out, letter + weight + '.png'))
                save(glow(font, letter), os.path.join(out, letter + 'g' + weight + '.png'))
        total = sum(os.path.getsize(os.path.join(out, f)) for f in os.listdir(out))
        print('%-10s %d glyphs, %d KB' % (name, len(os.listdir(out)), total // 1024))
    assert set(n for _l, n in config.FONTS) == set(FONTS), 'config.FONTS and FONTS disagree'


def rounded(size, radius, ss=4):
    big = Image.new('L', (size * ss, size * ss), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, size * ss - 1, size * ss - 1), radius * ss, fill=255)
    img = Image.new('RGBA', (size, size), (255, 255, 255, 0))
    img.putalpha(big.resize((size, size), Image.LANCZOS))
    return img


def textures():
    save(Image.new('RGBA', (8, 8), (255, 255, 255, 255)), os.path.join(MEDIA, 'white.png'))
    save(rounded(64, 32), os.path.join(MEDIA, 'dot.png'))
    save(rounded(CARD, CARD_RADIUS), os.path.join(SKIN_MEDIA, 'card_round.png'))
    save(Image.new('RGBA', (8, 8), (255, 255, 255, 255)), os.path.join(SKIN_MEDIA, 'card_square.png'))


def art():
    import preview_wordclock as preview
    s = config.defaults()
    face = preview.draw(s, 13, 55)            # the reference: IT IS FIVE TO TWO PM
    side = int(round(1080 * s['size'] / 100.0))
    x0, y0 = (1920 - side) // 2, (1080 - side) // 2
    icon = face.crop((x0, y0, x0 + side, y0 + side)).resize((512, 512), Image.LANCZOS)
    icon.save(os.path.join(ROOT, 'icon.png'), optimize=True)
    s.update(glow=1, night_palette=3)           # amber LED with a soft glow
    preview.draw(s, 22, 40).convert('RGB').save(os.path.join(ROOT, 'fanart.jpg'), quality=88)
    print('icon.png, fanart.jpg')


if __name__ == '__main__':
    fonts()
    textures()
    art()

"""Generate DVD Logo's images from dvd-asset/image.png.

  python3 tools/make_dvd_media.py [source.png]

Writes, under screensaver.dvdlogo/:
  resources/media/dvd.png      the logo alone, white with a transparent background,
                               trimmed to its ink (the black box and the hole in the disc
                               disappear), so Kodi can tint it with setColorDiffuse
  resources/media/white.png    a plain white texture for the background
  icon.png                     the Kodi icon (512), the logo on black
  fanart.jpg                   the fanart (1920x1080), the logo on a dark backdrop

The add-on's LOGO_W/LOGO_H in resources/lib/config.py must match the size of dvd.png;
tests/test_dvdlogo.py checks it. Needs Pillow.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
ADDON = os.path.join(ROOT, 'screensaver.dvdlogo')
MEDIA = os.path.join(ADDON, 'resources', 'media')
SOURCE = os.path.join(ROOT, 'dvd-asset', 'image.png')

INK = 8          # a pixel this bright or brighter is the logo
PAD = 3          # transparent pixels around the ink, so the bounce edge is the ink edge


def trim(img):
    """The logo as white RGB with the black background turned into alpha."""
    img = img.convert('RGB')
    grey = img.convert('L')
    box = grey.point(lambda v: 255 if v >= INK else 0).getbbox()
    if not box:
        raise SystemExit('no logo found in the source image')
    left, top, right, bottom = box
    left, top = max(0, left - PAD), max(0, top - PAD)
    right, bottom = min(img.width, right + PAD), min(img.height, bottom + PAD)
    # Supersample before trimming so the alpha edge stays smooth when the logo is scaled up.
    crop = img.crop((left, top, right, bottom))
    alpha = crop.convert('L')
    out = Image.new('RGBA', crop.size, (255, 255, 255, 0))
    out.putalpha(alpha)
    rgb = Image.new('RGB', crop.size, (255, 255, 255))
    out = Image.merge('RGBA', (*rgb.split(), alpha))
    return out


def fit(img, width):
    height = int(round(width * img.height / float(img.width)))
    return img.resize((width, height), Image.LANCZOS)


def backdrop(size, top, bottom):
    """A vertical gradient, from `top` at the top to `bottom` at the bottom."""
    img = Image.new('RGB', (1, size[1]))
    px = img.load()
    for y in range(size[1]):
        t = y / float(max(1, size[1] - 1))
        px[0, y] = tuple(int(round(top[i] + (bottom[i] - top[i]) * t)) for i in range(3))
    return img.resize(size, Image.BILINEAR)


def glow(img, colour, strength, blur, pad):
    """A soft halo behind the logo: the logo's alpha, tinted, blurred and padded."""
    big = Image.new('RGBA', (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
    tinted = Image.new('RGBA', img.size, colour + (0,))
    tinted.putalpha(img.getchannel('A'))
    big.paste(tinted, (pad, pad), tinted)
    out = big.filter(ImageFilter.GaussianBlur(blur))
    alpha = out.getchannel('A').point(lambda a: int(a * strength))
    out.putalpha(alpha)
    return out


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else SOURCE
    logo = trim(Image.open(source))
    os.makedirs(MEDIA, exist_ok=True)
    logo.save(os.path.join(MEDIA, 'dvd.png'), optimize=True)
    Image.new('RGBA', (8, 8), (255, 255, 255, 255)).save(os.path.join(MEDIA, 'white.png'))

    # Icon: 512 square, near-black, the logo at 88% of the width.
    icon = Image.new('RGBA', (512, 512), (0, 0, 0, 255))
    bg = backdrop((512, 512), (18, 20, 26), (0, 0, 0)).convert('RGBA')
    icon.paste(bg, (0, 0))
    mark = fit(logo, 450)
    halo = glow(mark, (120, 150, 255), 0.35, 26, 40)
    icon.alpha_composite(halo, ((512 - halo.width) // 2, (512 - halo.height) // 2))
    icon.alpha_composite(mark, ((512 - mark.width) // 2, (512 - mark.height) // 2))
    icon.convert('RGB').save(os.path.join(ADDON, 'icon.png'), optimize=True)

    # Fanart: 1920x1080, the logo four fifths across the middle on a dark blue-grey glow.
    fan = backdrop((1920, 1080), (16, 19, 27), (0, 0, 0)).convert('RGBA')
    mark = fit(logo, 760)
    halo = glow(mark, (90, 120, 220), 0.30, 70, 120)
    fan.alpha_composite(halo, ((1920 - halo.width) // 2, (1080 - halo.height) // 2))
    fan.alpha_composite(mark, ((1920 - mark.width) // 2, (1080 - mark.height) // 2))
    fan.convert('RGB').save(os.path.join(ADDON, 'fanart.jpg'), quality=90, optimize=True)

    print('%s: %dx%d -> resources/media/dvd.png (%dx%d), icon.png, fanart.jpg' % (
        source, Image.open(source).width, Image.open(source).height, logo.width, logo.height))


if __name__ == '__main__':
    main()

"""Generate Tetris AI's images, icon and fanart.

  python3 tools/make_tetris_media.py

Writes, under screensaver.tetris/resources/media/:
  block.png     a white, bevel-shaded block that Kodi tints with setColorDiffuse; drawn at
                192x120 (2x its 96x60 size on screen) so it stays crisp on 4K screens
  grid-NN.png   the NN x 18 cell lines, transparent apart from them; one per column count the
                block size slider can produce, so a narrow or wide board gets matching lines
  panel.png     a rounded white panel, tinted with the HUD's opacity at run time
  vignette.png  a soft dark edge over the background
  white.png     a plain white texture
and icon.png (512) and fanart.jpg (1920x1080).

Needs Pillow and numpy. tests/test_tetris.py checks the sizes.
"""

import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
ADDON = os.path.join(ROOT, 'screensaver.tetris')
MEDIA = os.path.join(ADDON, 'resources', 'media')
sys.path.insert(0, ADDON)

from resources.lib import config  # noqa: E402

SS = 3                      # supersampling for the block sprite
BLOCK_W, BLOCK_H = 192, 120


def gradient(size, top, bottom):
    img = Image.new('RGB', (1, size[1]))
    px = img.load()
    for y in range(size[1]):
        t = y / float(max(1, size[1] - 1))
        px[0, y] = tuple(int(round(top[i] + (bottom[i] - top[i]) * t)) for i in range(3))
    return img.resize(size, Image.BILINEAR)


def rounded_mask(size, radius):
    big = 4
    mask = Image.new('L', (size[0] * big, size[1] * big), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, mask.width - 1, mask.height - 1), radius=radius * big, fill=255)
    return mask.resize(size, Image.LANCZOS)


def block_sprite():
    """A white block with a lit top, shaded sides and a dark border. Every pixel stays white in
    hue, so multiplying it by a piece colour gives that colour with the same relief."""
    w, h = BLOCK_W * SS, BLOCK_H * SS
    radius = int(26 * SS)
    mask = rounded_mask((w, h), radius)
    inset = int(7 * SS)
    inner = Image.new('L', (w, h), 0)
    inner.paste(rounded_mask((w - inset * 2, h - inset * 2), max(4, radius - inset)),
                (inset, inset))

    m = np.asarray(mask).astype(np.float32) / 255.0
    inn = np.asarray(inner).astype(np.float32) / 255.0
    yy = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    xx = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]

    shade = 0.98 - 0.20 * yy - 0.05 * xx            # top-lit, slightly darker to the right
    shade = np.maximum(shade, np.where(inn > 0.5, 0.86, 0.0))
    shade = np.where(inn > 0.5, shade, 0.42)        # border ring
    gloss = (yy > 0.07) & (yy < 0.30) & (inn > 0.5)
    shade = np.where(gloss, np.minimum(1.0, shade + 0.10), shade)
    shade = np.clip(shade * m, 0.0, 1.0)
    rgb = (shade * 255.0).astype(np.uint8)
    alpha = (m * 255.0).astype(np.uint8)
    out = np.dstack([rgb, rgb, rgb, alpha])
    return Image.fromarray(out, 'RGBA').resize((BLOCK_W, BLOCK_H), Image.LANCZOS)


def tint(img, argb):
    hexcolour = argb[-6:]
    r, g, b = (int(hexcolour[i:i + 2], 16) for i in (0, 2, 4))
    arr = np.asarray(img).astype(np.float32)
    arr[..., 0] *= r / 255.0
    arr[..., 1] *= g / 255.0
    arr[..., 2] *= b / 255.0
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), 'RGBA')


def glow(mark, argb, blur, strength):
    pad = blur * 3
    big = Image.new('RGBA', (mark.width + pad * 2, mark.height + pad * 2), (0, 0, 0, 0))
    flat = tint(Image.new('RGBA', mark.size, (255, 255, 255, 255)), argb)
    flat.putalpha(mark.getchannel('A'))
    big.alpha_composite(flat, (pad, pad))
    big = big.filter(ImageFilter.GaussianBlur(blur))
    alpha = big.getchannel('A').point(lambda a: int(a * strength))
    big.putalpha(alpha)
    return big


def grid_image(w=config.W, h=config.H, cols=20, rows=config.ROWS, alpha=config.GRID_ALPHA):
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    line = (255, 255, 255, alpha)
    for x in range(cols + 1):
        px = int(round(w * x / float(cols)))
        draw.rectangle((max(0, px - 1), 0, min(w - 1, px), h), fill=line)
    for y in range(rows + 1):
        py = int(round(h * y / float(rows)))
        draw.rectangle((0, max(0, py - 1), w, min(h - 1, py)), fill=line)
    border = (255, 255, 255, min(255, alpha * 3))
    draw.rectangle((0, 0, w - 1, h - 1), outline=border, width=2)
    return img


def vignette_image(size=(config.W, config.H)):
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    nx = (xx - w / 2.0) / (w / 2.0)
    ny = (yy - h / 2.0) / (h / 2.0)
    d = np.sqrt(nx * nx + ny * ny) / np.sqrt(2.0)
    a = np.clip((d - 0.25) / 0.75, 0.0, 1.0) ** 1.7
    alpha = (a * config.VIGNETTE_ALPHA * 255).astype(np.uint8)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 3] = alpha
    return Image.fromarray(rgba, 'RGBA')


def panel_image(size=(512, 512), radius=44):
    mask = rounded_mask(size, radius)
    img = Image.new('RGBA', size, (255, 255, 255, 255))
    img.putalpha(mask)
    return img


def blend(base, img, xy):
    base.alpha_composite(img, xy)


def make_icon(block):
    icon = gradient((512, 512), (20, 26, 40), (5, 7, 12)).convert('RGBA')
    grid = grid_image(512, 512, 4, 4, alpha=16)
    icon.alpha_composite(grid)
    cell_w, cell_h = 96, 80
    left, top = 64, 96
    classic = config.piece_colours(dict(config.defaults(), scheme=0))

    def block_at(col, row, letter, scale=1.0):
        w, h = int(cell_w * 0.92 * scale), int(cell_h * 0.92 * scale)
        img = tint(block.resize((w, h), Image.LANCZOS), classic[letter])
        x = left + int(col * cell_w + (cell_w - w) / 2)
        y = top + int(row * cell_h + (cell_h - h) / 2)
        return img, (x, y)

    stack = [('I', 0, 3), ('S', 1, 3), ('O', 2, 3), ('L', 3, 3),
             ('J', 0, 2), ('Z', 1, 2)]
    for letter, col, row in stack:
        img, xy = block_at(col, row, letter)
        blend(icon, img, xy)
    # A T piece falling in front of the stack.
    t_cells = ((1, 0), (0, 1), (1, 1), (2, 1))
    halo = None
    for dx, dy in t_cells:
        img, xy = block_at(dx, dy, 'T')
        halo = glow(img, classic['T'], 16, 0.75)
        blend(icon, halo, (xy[0] - halo.width // 2 + img.width // 2,
                           xy[1] - halo.height // 2 + img.height // 2))
    for dx, dy in t_cells:
        img, xy = block_at(dx, dy, 'T')
        blend(icon, img, xy)
    icon.convert('RGB').save(os.path.join(ADDON, 'icon.png'), optimize=True)


def make_fanart(block):
    fan = gradient((1920, 1080), (19, 25, 41), (4, 5, 9)).convert('RGBA')
    fan.alpha_composite(grid_image(1920, 1080, 20, 18, alpha=13))
    colours = config.piece_colours(dict(config.defaults(), scheme=0))

    cell_w, cell_h = 96, 60
    left, top = 0, 0

    def block_at(col, row, letter, scale=1.0):
        w, h = int(cell_w * 0.96 * scale), int(cell_h * 0.96 * scale)
        img = tint(block.resize((w, h), Image.LANCZOS), colours[letter])
        x = left + int(col * cell_w + (cell_w - w) / 2)
        y = top + int(row * cell_h + (cell_h - h) / 2)
        return img, (x, y)

    # A low stack, with pieces still falling above it.
    stack = [('I', 0, 17), ('J', 1, 17), ('L', 2, 17), ('O', 3, 17), ('S', 4, 17),
             ('Z', 5, 17), ('T', 6, 17), ('I', 7, 17), ('J', 8, 17), ('L', 9, 17),
             ('S', 10, 17), ('Z', 11, 17), ('T', 12, 17), ('I', 13, 17), ('J', 14, 17),
             ('L', 15, 17), ('O', 16, 17), ('S', 17, 17), ('Z', 18, 17), ('T', 19, 17),
             ('J', 0, 16), ('L', 1, 16), ('O', 2, 16), ('I', 3, 16), ('S', 5, 16),
             ('Z', 6, 16), ('T', 7, 16), ('L', 9, 16), ('J', 10, 16), ('I', 12, 16),
             ('O', 13, 16), ('S', 15, 16), ('T', 16, 16), ('Z', 18, 16),
             ('I', 0, 15), ('L', 1, 15), ('S', 4, 15), ('J', 7, 15), ('T', 11, 15),
             ('O', 14, 15), ('Z', 17, 15),
             ('O', 3, 14), ('T', 8, 14), ('L', 15, 14)]
    for letter, col, row in stack:
        img, xy = block_at(col, row, letter)
        blend(fan, img, xy)

    falling = [
        ('T', ((6, 2), (5, 3), (6, 3), (7, 3))),
        ('L', ((2, 4), (2, 5), (2, 6), (3, 6))),
        ('I', ((10, 1), (11, 1), (12, 1), (13, 1))),
        ('J', ((18, 3), (18, 4), (18, 5), (17, 5))),
    ]
    for letter, cells in falling:
        imgs = []
        for dx, dy in cells:
            img, xy = block_at(dx, dy, letter)
            imgs.append((img, xy))
        for img, xy in imgs:
            halo = glow(img, colours[letter], 22, 0.55)
            blend(fan, halo, (xy[0] - halo.width // 2 + img.width // 2,
                             xy[1] - halo.height // 2 + img.height // 2))
        for img, xy in imgs:
            blend(fan, img, xy)

    fan.alpha_composite(vignette_image())
    fan.convert('RGB').save(os.path.join(ADDON, 'fanart.jpg'), quality=92, optimize=True)


def main():
    os.makedirs(MEDIA, exist_ok=True)
    block = block_sprite()
    block.save(os.path.join(MEDIA, 'block.png'), optimize=True)
    for cols in config.column_counts():
        grid_image(cols=cols).save(os.path.join(MEDIA, 'grid-%d.png' % cols), optimize=True)
    panel_image().save(os.path.join(MEDIA, 'panel.png'), optimize=True)
    vignette_image().save(os.path.join(MEDIA, 'vignette.png'), optimize=True)
    Image.new('RGBA', (8, 8), (255, 255, 255, 255)).save(os.path.join(MEDIA, 'white.png'))
    make_icon(block)
    make_fanart(block)
    print('block %dx%d, grid %dx%d for %s columns, icon 512, fanart 1920x1080' % (
        block.width, block.height, config.W, config.H,
        ', '.join(str(c) for c in config.column_counts())))


if __name__ == '__main__':
    main()

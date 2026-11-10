"""Make the Hacker News screensaver's icon, fanart and white texture (Pillow).

  python3 tools/make_hackernews_media.py

Writes icon.png (512), fanart.jpg (1920x1080) and the white.png the skin tints, into
screensaver.hackernews. The add-on draws everything else itself; Hacker News' orange is
#FF6600, used as the accent in the screensaver too.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
ADDON = os.path.join(ROOT, 'screensaver.hackernews')
ORANGE = (255, 102, 0)
BLACK = (16, 18, 20)
WHITE = (237, 235, 232)
DIM = (142, 140, 136)

FONTS = ['/System/Library/Fonts/Helvetica.ttc',
         '/System/Library/Fonts/Supplemental/Arial.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']


def font(size):
    for path in FONTS:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size, index=1)
            except (OSError, IOError):
                continue
    return ImageFont.load_default()


def icon():
    image = Image.new('RGB', (512, 512), ORANGE)
    draw = ImageDraw.Draw(image)
    face = font(330)
    # The white Y, drawn a little above centre the way the site's square reads.
    width = draw.textbbox((0, 0), 'Y', font=face)[2]
    draw.text(((512 - width) / 2, 52), 'Y', font=face, fill=WHITE)
    return image


def fanart():
    image = Image.new('RGB', (1920, 1080), BLACK)
    draw = ImageDraw.Draw(image)
    # Orange frame marks in the corners, quiet enough not to fight the slides.
    draw.rectangle((96, 96, 102, 220), fill=ORANGE)
    draw.rectangle((96, 96, 300, 102), fill=ORANGE)

    title = font(150)
    subtitle = font(46)
    draw.text((150, 300), 'Hacker News', font=title, fill=WHITE)
    draw.text((154, 510), 'Top stories and their best comments', font=subtitle, fill=DIM)
    draw.text((154, 580), 'Titles, points, authors and ages · reading-time paced',
              font=subtitle, fill=DIM)

    # The wordmark square, right of centre.
    square = 300
    x, y = 1380, 300
    draw.rectangle((x, y, x + square, y + square), fill=ORANGE)
    y_face = font(230)
    width, height = draw.textbbox((0, 0), 'Y', font=y_face)[2:]
    draw.text((x + (square - width) / 2, y + (square - height) / 2 - 28), 'Y',
              font=y_face, fill=WHITE)

    draw.rectangle((96, 900, 1824, 902), fill=(60, 60, 60))
    return image


def white():
    return Image.new('RGB', (8, 8), (255, 255, 255))


def main():
    icon().save(os.path.join(ADDON, 'icon.png'), optimize=True)
    fanart().save(os.path.join(ADDON, 'fanart.jpg'), quality=90, optimize=True)
    folder = os.path.join(ADDON, 'resources', 'skins', 'Default', 'media')
    os.makedirs(folder, exist_ok=True)
    white().save(os.path.join(folder, 'white.png'), optimize=True)
    print('media: %s' % ADDON)


if __name__ == '__main__':
    main()

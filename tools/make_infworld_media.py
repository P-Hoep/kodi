"""Make Endless World (OpenGL)'s icon and fanart from harness screenshots.

The screensaver draws its own art, so both images are frames from the test window:

  ./build/infworld_glfw_core --assets resources/textures --seed 2 --shot /tmp/iw-fanart.ppm --shot-after 8
  ./build/infworld_glfw_core --assets resources/textures --seed 3 --shot /tmp/iw-icon.ppm --shot-after 6
  python3 tools/make_infworld_media.py /tmp/iw-fanart.ppm /tmp/iw-icon.ppm

writes icon.png (512) and fanart.jpg (1920x1080) into screensaver.infworld.gl and
screensaver.infworld.gl.armv7. Needs Pillow.
"""

import os
import sys

from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
ADDONS = ['screensaver.infworld.gl', 'screensaver.infworld.gl.armv7']


def load(path):
    image = Image.open(path).convert('RGB')
    if image.width > 2560:  # the harness writes at the window size; be gentle with huge captures
        image = image.resize((2560, round(image.height * 2560.0 / image.width)), Image.LANCZOS)
    return image


def square_crop(image, focus):
    """Crop the largest square around a focus point given as a fraction of the width/height."""
    side = min(image.width, image.height)
    x = int(image.width * focus[0] - side / 2)
    y = int(image.height * focus[1] - side / 2)
    x = max(0, min(image.width - side, x))
    y = max(0, min(image.height - side, y))
    return image.crop((x, y, x + side, y + side))


def main():
    fanart_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/iw-fanart.ppm'
    icon_path = sys.argv[2] if len(sys.argv) > 2 else '/tmp/iw-icon.ppm'
    fanart = load(fanart_path)
    icon = square_crop(load(icon_path), (0.42, 0.55))
    icon = icon.resize((512, 512), Image.LANCZOS).filter(ImageFilter.SHARPEN)
    for addon in ADDONS:
        folder = os.path.join(ROOT, addon)
        if not os.path.isdir(folder):
            continue
        icon.save(os.path.join(folder, 'icon.png'))
        fanart.resize((1920, 1080), Image.LANCZOS).save(os.path.join(folder, 'fanart.jpg'),
                                                       quality=88)
        print('media: %s' % folder)


if __name__ == '__main__':
    main()

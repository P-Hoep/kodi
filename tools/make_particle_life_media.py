"""Make Particle Life (OpenGL)'s icon and fanart from harness screenshots.

The screensaver draws its own art, so both images are frames from the test window:

  ./build/particle_life_glfw_core --seed 2 --shot /tmp/pl-fanart.ppm --shot-after 4
  ./build/particle_life_glfw_core --seed 7 --shot /tmp/pl-icon.ppm --shot-after 4
  python3 tools/make_particle_life_media.py /tmp/pl-fanart.ppm /tmp/pl-icon.ppm

writes icon.png (512) and fanart.jpg (1920x1080) into screensaver.particlelife.gl and
screensaver.particlelife.gl.armv7. Needs Pillow.
"""

import os
import sys

from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
ADDONS = ['screensaver.particlelife.gl', 'screensaver.particlelife.gl.armv7']


def load(path):
    image = Image.open(path).convert('RGB')
    if image.width > 2560:  # the harness writes at the window size; be gentle with huge captures
        image = image.resize((2560, round(image.height * 2560.0 / image.width)), Image.LANCZOS)
    return image


def square_crop(image, focus, scale=1.0):
    """Crop a square around a focus point given as a fraction of the width/height."""
    side = int(min(image.width, image.height) * scale)
    x = int(image.width * focus[0] - side / 2)
    y = int(image.height * focus[1] - side / 2)
    x = max(0, min(image.width - side, x))
    y = max(0, min(image.height - side, y))
    return image.crop((x, y, x + side, y + side))


def to_sixteen_nine(image):
    """Centre-crop to 16:9 (a Kodi screenshot may be a different aspect)."""
    if image.width * 9 < image.height * 16:
        height = image.width * 9 // 16
        top = (image.height - height) // 2
        return image.crop((0, top, image.width, top + height))
    width = image.height * 16 // 9
    left = (image.width - width) // 2
    return image.crop((left, 0, left + width, image.height))


def main():
    fanart_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/pl-fanart.ppm'
    icon_path = sys.argv[2] if len(sys.argv) > 2 else fanart_path
    fanart = to_sixteen_nine(load(fanart_path))
    icon = square_crop(load(icon_path), (0.46, 0.44), 0.35)
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

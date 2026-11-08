"""Generate the settings.xml and strings.po of both Tetris AI (OpenGL) add-ons from the table in
screensaver.tetris/resources/lib/config.py, so the GPU add-ons and the Python one use the same
setting ids, defaults and option indices.

Run: python3 tools/make_settings_tetris_gl.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(ROOT, 'screensaver.tetris'))
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from resources.lib import config  # noqa: E402

ADDONS = ('screensaver.tetris.gl', 'screensaver.tetris.gl.armv7')

if __name__ == '__main__':
    for addon in ADDONS:
        write(os.path.join(ROOT, addon), addon, 'Tetris AI (OpenGL)', config.CATEGORIES,
              'tools/make_settings_tetris_gl.py')

"""Generate the OpenGL Sand Clock's settings.xml and strings.po from the Python add-on's table
(screensaver.sandclock/resources/lib/config.py), so both versions have the same settings.

Run: python3 tools/make_settings_sandclock_gl.py
     python3 tools/make_settings_sandclock_gl.py screensaver.sandclock.gl.armv7 'Sand Clock (OpenGL, 32-bit Android)'
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock'))
ADDON_ID = sys.argv[1] if len(sys.argv) > 1 else 'screensaver.sandclock.gl'
NAME = sys.argv[2] if len(sys.argv) > 2 else 'Sand Clock (OpenGL)'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from resources.lib import config  # noqa: E402


if __name__ == '__main__':
    write(ROOT, ADDON_ID, NAME, config.CATEGORIES, 'tools/make_settings_sandclock_gl.py')

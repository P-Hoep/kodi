"""Generate the OpenGL Sand Clock's settings.xml and strings.po from the Python add-on's table
(screensaver.sandclock/resources/lib/config.py), so both versions have the same settings.

Run: python3 tools/make_settings_sandclock_gl.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock'))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock.gl'))
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from resources.lib import config  # noqa: E402

ADDON_ID = 'screensaver.sandclock.gl'

if __name__ == '__main__':
    write(ROOT, ADDON_ID, 'Sand Clock (OpenGL)', config.CATEGORIES, 'tools/make_settings_sandclock_gl.py')

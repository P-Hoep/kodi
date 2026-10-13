"""Generate Audiobookshelf's settings.xml and strings.po from the table in resources/lib/config.py.

Run: python3 tools/make_settings_audiobookshelf.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'plugin.audio.audiobookshelf'))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from resources.lib import config  # noqa: E402

if __name__ == '__main__':
    write(ROOT, config.ADDON_ID, config.ADDON_NAME, config.CATEGORIES, 'tools/make_settings_audiobookshelf.py')

"""Generate Liquid Clock's settings.xml and strings.po. Same table as Sand Clock
(screensaver.sandclock/resources/lib/config.py) with the sand wording and defaults swapped for
liquid, and a Sloshing setting.

Run: python3 tools/make_settings_liquidclock.py
"""

import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock'))
ADDON_ID = 'screensaver.liquidclock.armv7'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from resources.lib import config  # noqa: E402


def liquid_categories():
    cats = []
    for title, settings in copy.deepcopy(config.CATEGORIES):
        if title == 'Sand':
            title = 'Liquid'
        out = []
        for s in settings:
            sid = s['id']
            if sid == 'crumble':
                s['label'] = 'What melts'
            elif sid == 'speed':
                s['label'] = 'Melt speed'
            elif sid == 'grain':
                s.update(label='Droplet size', default=0)
            elif sid == 'grain_look':
                s.update(label='Liquid looks', default=0, options=['Glossy', 'Flat', 'Glowing'])
            elif sid == 'pile':
                s.update(label='Liquid level (% of the screen height)', default=20)
            out.append(s)
            if sid == 'gravity':
                out.append(config.O('slosh', 'Sloshing', 1, ['Gentle', 'Normal', 'Wild']))
        cats.append((title, out))
    return cats


if __name__ == '__main__':
    write(ROOT, ADDON_ID, 'Liquid Clock', liquid_categories(), 'tools/make_settings_liquidclock.py')

"""Generate Live Cams' settings.xml and strings.po from the table in resources/lib/config.py,
then append the on-screen strings (config.STRINGS, ids 32000 and up) to strings.po.

Run: python3 tools/make_settings_livecams.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'screensaver.livecams'))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from resources.lib import config  # noqa: E402

if __name__ == '__main__':
    write(ROOT, config.ADDON_ID, config.ADDON_NAME, config.CATEGORIES, 'tools/make_settings_livecams.py')
    po = os.path.join(ROOT, 'resources', 'language', 'resource.language.en_gb', 'strings.po')
    with open(po, 'a') as handle:
        for sid in sorted(config.STRINGS):
            handle.write('\nmsgctxt "#%d"\nmsgid "%s"\nmsgstr ""\n' % (sid, config.STRINGS[sid].replace('"', '\\"')))
    print('on-screen strings: %d' % len(config.STRINGS))

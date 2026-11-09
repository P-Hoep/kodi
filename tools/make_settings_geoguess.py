"""Generate settings.xml and strings.po for screensaver.geoguess from the one table in
resources/lib/config.py. The on-screen strings (config.STRINGS, ids 32000 and up) are appended
after the settings labels.

Run: python3 tools/make_settings_geoguess.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(ROOT, 'screensaver.geoguess', 'resources', 'lib'))
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from config import ADDON_ID, ADDON_NAME, CATEGORIES, STRINGS  # noqa: E402

GENERATOR = 'tools/make_settings_geoguess.py'


def append_strings(root, addon_name, strings):
    """Add ids above the settings range to the strings.po write() has just produced."""
    path = os.path.join(root, 'resources', 'language', 'resource.language.en_gb', 'strings.po')
    po = ['']
    for sid in sorted(strings):
        po += ['msgctxt "#%d"' % sid, 'msgid "%s"' % strings[sid].replace('"', '\\"'), 'msgstr ""', '']
    with open(path, 'a') as handle:
        handle.write('\n'.join(po))
    print('extra strings: %d' % len(strings))


def main():
    root = os.path.join(ROOT, ADDON_ID)
    write(root, ADDON_ID, ADDON_NAME, CATEGORIES, GENERATOR)
    append_strings(root, ADDON_NAME, STRINGS)


if __name__ == '__main__':
    main()

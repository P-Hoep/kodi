"""Build dist/<add-on>-<version>.zip for Kodi's "Install from zip file".

  python3 tools/build_zip.py                              # God's Eye Map
  python3 tools/build_zip.py screensaver.godsworld.map    # God's World Map
"""

import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
ADDON = sys.argv[1].strip('/') if len(sys.argv) > 1 else 'screensaver.godseye.map'


def main():
    src = os.path.join(ROOT, ADDON)
    version = re.search(r'<addon[^>]*version="([^"]+)"', open(os.path.join(src, 'addon.xml')).read()).group(1)
    dist = os.path.join(ROOT, 'dist')
    if not os.path.isdir(dist):
        os.makedirs(dist)
    out = os.path.join(dist, '%s-%s.zip' % (ADDON, version))
    count = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for folder, dirs, files in os.walk(src):
            dirs[:] = sorted(d for d in dirs if d != '__pycache__')
            for name in sorted(files):
                if name.endswith(('.pyc', '.pyo')) or name.startswith('.'):
                    continue
                full = os.path.join(folder, name)
                z.write(full, os.path.join(ADDON, os.path.relpath(full, src)))
                count += 1
    print('%s (%d files, %.0f KB)' % (out, count, os.path.getsize(out) / 1024.0))


if __name__ == '__main__':
    main()

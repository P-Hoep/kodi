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


def addon_version(src):
    return re.search(r'<addon[^>]*version="([^"]+)"', open(os.path.join(src, 'addon.xml')).read()).group(1)


def build(addon, dist):
    """Zip ROOT/<addon> into <dist>/<addon>-<version>.zip; return (path, file count)."""
    src = os.path.join(ROOT, addon)
    if not os.path.isdir(dist):
        os.makedirs(dist)
    out = os.path.join(dist, '%s-%s.zip' % (addon, addon_version(src)))
    count = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for folder, dirs, files in os.walk(src):
            dirs[:] = sorted(d for d in dirs if d != '__pycache__')
            for name in sorted(files):
                if name.endswith(('.pyc', '.pyo')) or name.startswith('.'):
                    continue
                full = os.path.join(folder, name)
                z.write(full, os.path.join(addon, os.path.relpath(full, src)))
                count += 1
    return out, count


def main():
    addon = sys.argv[1].strip('/') if len(sys.argv) > 1 else 'screensaver.godseye.map'
    out, count = build(addon, os.path.join(ROOT, 'dist'))
    print('%s (%d files, %.0f KB)' % (out, count, os.path.getsize(out) / 1024.0))


if __name__ == '__main__':
    main()

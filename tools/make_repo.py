"""Build the Kodi repository (repository.phoep) that GitHub Pages serves.

  python3 tools/make_repo.py                 # -> dist/repo
  python3 tools/make_repo.py --out _site     # what the GitHub Actions workflow publishes

Every top-level folder with an addon.xml is an add-on. The output is the layout
repository.phoep/addon.xml points at:

  addons.xml, addons.xml.md5            the index Kodi polls for updates
  <id>/<id>-<version>.zip (+ .sha256)   one zip per add-on
  <id>/icon.png, fanart.jpg …           the assets each addon.xml names
  repository.phoep-<version>.zip        also at the top, for "Install from zip file"
  index.html                            links Kodi's file manager can browse
"""

import argparse
import hashlib
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_zip import ROOT, addon_version, build  # noqa: E402

REPO_ID = 'repository.phoep'


def addons():
    return sorted(d for d in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, d, 'addon.xml')))


def addon_element(addon):
    """The <addon>…</addon> element of an addon.xml, without the XML declaration."""
    xml = open(os.path.join(ROOT, addon, 'addon.xml'), encoding='utf-8').read()
    return re.sub(r'^\s*<\?xml[^>]*\?>\s*', '', xml).rstrip()


def assets(addon):
    xml = open(os.path.join(ROOT, addon, 'addon.xml'), encoding='utf-8').read()
    block = re.search(r'<assets>(.*?)</assets>', xml, re.S)
    return re.findall(r'>\s*([^<>\s]+)\s*</', block.group(1)) if block else []


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=os.path.join(ROOT, 'dist', 'repo'))
    out = os.path.abspath(parser.parse_args().out)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)

    ids = addons()
    if REPO_ID not in ids:
        sys.exit('%s/addon.xml is missing' % REPO_ID)
    for addon in ids:
        folder = os.path.join(out, addon)
        zip_path, count = build(addon, folder)
        with open(zip_path + '.sha256', 'w') as f:
            f.write(sha256(zip_path) + '\n')
        for asset in assets(addon):
            src = os.path.join(ROOT, addon, asset)
            if not os.path.isfile(src):
                sys.exit('%s: asset %s is missing' % (addon, asset))
            dst = os.path.join(folder, asset)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
        print('%-32s %-8s %4d files %7.0f KB' % (addon, addon_version(os.path.join(ROOT, addon)),
                                                 count, os.path.getsize(zip_path) / 1024.0))

    index = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n'
    index += '\n'.join(addon_element(a) for a in ids) + '\n</addons>\n'
    with open(os.path.join(out, 'addons.xml'), 'w', encoding='utf-8') as f:
        f.write(index)
    with open(os.path.join(out, 'addons.xml.md5'), 'w') as f:
        f.write(hashlib.md5(index.encode('utf-8')).hexdigest() + '\n')

    repo_zip = '%s-%s.zip' % (REPO_ID, addon_version(os.path.join(ROOT, REPO_ID)))
    shutil.copyfile(os.path.join(out, REPO_ID, repo_zip), os.path.join(out, repo_zip))
    with open(os.path.join(out, 'index.html'), 'w') as f:
        f.write('<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>P-Hoep Kodi add-ons</title></head>\n'
                '<body>\n<p>Kodi repository. In Kodi: Settings &rarr; File manager &rarr; Add source &rarr; '
                'this page\'s URL, then Add-ons &rarr; Install from zip file.</p>\n'
                '<a href="%s">%s</a>\n</body></html>\n' % (repo_zip, repo_zip))
    # GitHub Pages runs Jekyll unless told not to.
    open(os.path.join(out, '.nojekyll'), 'w').close()
    print('-> %s' % out)


if __name__ == '__main__':
    main()

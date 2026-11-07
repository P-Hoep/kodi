"""The on-disk cache shared by both add-ons (in the library's addon_data folder):

  cache/{sheet_id}/tabs.json         {"title", "tabs": [{gid, title, index}], "fetched_at", "source"}
  cache/{sheet_id}/{gid}.csv         raw CSV as downloaded
  cache/{sheet_id}/{gid}.meta.json   {"fetched_at", "row_count", "source"}
  progress/{sheet_id}.json           spaced repetition + stats (app only)

Every write goes to *.tmp first and is then renamed, so a power cut never leaves half a file.
"""

import json
import os
import re
import shutil
import time


def atomic_write(path, data):
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as handle:
        handle.write(data)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def safe_name(text):
    """A file name for a gid or, for name-only tabs, a tab title."""
    return re.sub(r'[^A-Za-z0-9_-]', '_', str(text))[:80] or '_'


class Cache(object):
    def __init__(self, root):
        self.root = root

    def folder(self, sheet_id):
        return os.path.join(self.root, 'cache', safe_name(sheet_id))

    def progress_path(self, sheet_id):
        return os.path.join(self.root, 'progress', safe_name(sheet_id) + '.json')

    # ---------------------------------------------------------------- tabs

    def read_tabs(self, sheet_id):
        return self._json(os.path.join(self.folder(sheet_id), 'tabs.json'))

    def write_tabs(self, sheet_id, title, tabs, source, now=None):
        data = {'title': title, 'tabs': tabs, 'source': source, 'fetched_at': now or time.time()}
        atomic_write(os.path.join(self.folder(sheet_id), 'tabs.json'), json.dumps(data, indent=1).encode('utf-8'))

    # ---------------------------------------------------------------- tab CSVs

    def tab_key(self, tab):
        return safe_name(tab['gid'] if tab.get('gid') is not None else 'name-' + tab['title'])

    def read_csv(self, sheet_id, tab):
        path = os.path.join(self.folder(sheet_id), self.tab_key(tab) + '.csv')
        try:
            with open(path, 'rb') as handle:
                return handle.read().decode('utf-8', 'replace')
        except OSError:
            return None

    def read_meta(self, sheet_id, tab):
        return self._json(os.path.join(self.folder(sheet_id), self.tab_key(tab) + '.meta.json'))

    def write_csv(self, sheet_id, tab, text, source, row_count, now=None):
        base = os.path.join(self.folder(sheet_id), self.tab_key(tab))
        atomic_write(base + '.csv', text.encode('utf-8'))
        meta = {'fetched_at': now or time.time(), 'row_count': row_count, 'source': source}
        atomic_write(base + '.meta.json', json.dumps(meta).encode('utf-8'))

    # ---------------------------------------------------------------- housekeeping

    def age(self, sheet_id, now=None):
        """Seconds since the tab list was fetched, or None with no cache."""
        tabs = self.read_tabs(sheet_id)
        if not tabs:
            return None
        return max(0.0, (now or time.time()) - float(tabs.get('fetched_at', 0)))

    def clear(self):
        shutil.rmtree(os.path.join(self.root, 'cache'), ignore_errors=True)

    @staticmethod
    def _json(path):
        try:
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

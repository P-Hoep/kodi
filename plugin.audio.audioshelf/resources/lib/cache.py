"""A small JSON file cache for library lists and book details. No Kodi imports.

Each plugin call is a fresh Python process, so lists are kept on disk under the add-on's
profile folder for a configurable time. Progress is never cached here: it changes while
you listen, so it is fetched fresh (one /api/me call per screen) and merged in.
"""

import hashlib
import json
import os
import shutil
import time


class Cache(object):
    def __init__(self, folder, ttl, scope=''):
        self.folder = folder
        self.ttl = ttl
        self.scope = scope  # server address: switching servers never shows the old library

    def _path(self, key):
        digest = hashlib.sha1(('%s|%s' % (self.scope, key)).encode('utf-8')).hexdigest()
        return os.path.join(self.folder, digest[:2], digest + '.json')

    def get(self, key):
        if self.ttl <= 0:
            return None
        path = self._path(key)
        try:
            if time.time() - os.path.getmtime(path) > self.ttl:
                return None
            with open(path) as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    def put(self, key, value):
        if self.ttl <= 0:
            return
        path = self._path(key)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + '.tmp'
            with open(tmp, 'w') as handle:
                json.dump(value, handle)
            os.replace(tmp, path)
        except OSError:
            pass

    def fetch(self, key, loader):
        value = self.get(key)
        if value is None:
            value = loader()
            self.put(key, value)
        return value

    def clear(self):
        shutil.rmtree(self.folder, ignore_errors=True)

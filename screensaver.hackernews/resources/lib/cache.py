"""JSON files on disk, one per story list, with a fetch time.

The cache lets the screensaver start instantly from the last download and carry on when the
network is down. Writes go to a temporary file and are renamed into place, so a Kodi shutdown
in the middle of a save cannot leave half a file behind. No Kodi imports: cache.py is tested
on its own with a temporary folder and an injected clock.
"""

import json
import os
import tempfile
import time


class Cache(object):
    def __init__(self, folder, clock=time.time):
        self.folder = folder
        self.clock = clock

    def path(self, kind):
        return os.path.join(self.folder, '%s.json' % kind)

    def load(self, kind):
        """The cached dict, or None when the file is missing, unreadable or the wrong shape."""
        try:
            with open(self.path(kind), encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get('stories'), list):
            return None
        try:
            data['fetched_at'] = float(data.get('fetched_at') or 0)
        except (TypeError, ValueError):
            return None
        return data

    def save(self, kind, data):
        """Write atomically. Failures are swallowed: a cache that cannot be written must not
        stop the screensaver from showing what it has."""
        try:
            if not os.path.isdir(self.folder):
                os.makedirs(self.folder, exist_ok=True)
            handle, temp = tempfile.mkstemp(prefix='.%s-' % kind, suffix='.tmp', dir=self.folder)
            try:
                with os.fdopen(handle, 'w', encoding='utf-8') as out:
                    json.dump(data, out, ensure_ascii=False, separators=(',', ':'))
                os.replace(temp, self.path(kind))
            except Exception:
                try:
                    os.remove(temp)
                except OSError:
                    pass
                raise
        except OSError:
            return False
        return True

    def age(self, data):
        return max(0.0, self.clock() - float(data.get('fetched_at') or 0))

    def is_fresh(self, data, ttl_seconds):
        return self.age(data) < ttl_seconds

    def clear(self, kinds=None):
        removed = 0
        for kind in kinds or ['top', 'best', 'new', 'ask', 'show']:
            try:
                os.remove(self.path(kind))
                removed += 1
            except OSError:
                pass
        return removed

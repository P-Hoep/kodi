"""Camera health (health.json) and viewing history plus favourites (history.json). No Kodi imports.

Health: each failure adds 1 to a camera's score. Score 1 skips the camera for an hour,
2 for a day, 3 or more for a week, after which it gets one more try (a failure then
starts another week). 60 s of good playback clears the score. When more than half of
one source's attempts in the last hour failed (at least SOURCE_MIN_FAILS of them), the
whole source is skipped for 6 hours. A catalogue refresh keeps all of this; entries
for cameras that left the catalogue are pruned.
"""

import json
import os
import time

HOUR = 3600
SKIP = {1: HOUR, 2: 24 * HOUR}
SKIP_LONG = 7 * 24 * HOUR
SOURCE_WINDOW = HOUR
SOURCE_BLOCK = 6 * HOUR
SOURCE_MIN_FAILS = 3
HISTORY_SIZE = 200
RECENT = 6 * HOUR
LOWRES_TTL = 7 * 24 * HOUR


def _load(path):
    try:
        with open(path, 'r') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w') as handle:
        json.dump(data, handle, separators=(',', ':'))
    os.replace(tmp, path)


class Health(object):
    def __init__(self, path):
        self.path = path
        data = _load(path)
        self.cams = data.get('cams') or {}           # id -> {'score': n, 't': last failure}
        self.attempts = data.get('attempts') or {}   # family -> [[t, ok], ...] within the last hour
        self.sources = data.get('sources') or {}     # family -> blocked until
        self.lowres = data.get('lowres') or {}       # id -> [height, seen at]: probed below the minimum
        self.dirty = False

    def save(self):
        if self.dirty:
            _save(self.path, {'cams': self.cams, 'attempts': self.attempts, 'sources': self.sources,
                              'lowres': self.lowres})
            self.dirty = False

    def reset(self):
        self.cams, self.attempts, self.sources, self.lowres = {}, {}, {}, {}
        self.dirty = True

    # ------------------------------------------------------------ queries

    def skip_until(self, cam_id):
        entry = self.cams.get(cam_id)
        if not entry:
            return 0
        return entry['t'] + SKIP.get(entry['score'], SKIP_LONG)

    def blocked(self, cam, now=None):
        now = time.time() if now is None else now
        if self.sources.get(cam.family, 0) > now:
            return True
        return self.skip_until(cam.id) > now

    def blocked_ids(self, now=None):
        now = time.time() if now is None else now
        return set(cid for cid in self.cams if self.skip_until(cid) > now)

    def blocked_sources(self, now=None):
        now = time.time() if now is None else now
        return set(f for f, until in self.sources.items() if until > now)

    def known_height(self, cam_id, now=None):
        """The height a probe found for a camera whose catalogue entry has none, or 0."""
        now = time.time() if now is None else now
        entry = self.lowres.get(cam_id)
        return entry[0] if entry and now - entry[1] < LOWRES_TTL else 0

    # ------------------------------------------------------------ updates

    def _attempt(self, family, ok, now):
        recent = [a for a in self.attempts.get(family, []) if now - a[0] < SOURCE_WINDOW]
        recent.append([now, 1 if ok else 0])
        self.attempts[family] = recent[-50:]
        fails = sum(1 for a in recent if not a[1])
        if not ok and fails >= SOURCE_MIN_FAILS and fails * 2 > len(recent):
            if self.sources.get(family, 0) <= now:
                self.sources[family] = now + SOURCE_BLOCK
                return True
        return False

    def failed(self, cam, now=None):
        """Record a failure. Returns True if this blocked the camera's whole source."""
        now = time.time() if now is None else now
        entry = self.cams.get(cam.id) or {'score': 0, 't': now}
        entry['score'] = min(entry['score'] + 1, 9)
        entry['t'] = now
        self.cams[cam.id] = entry
        self.dirty = True
        return self._attempt(cam.family, False, now)

    def started(self, cam, now=None):
        """The camera opened: counts as a good attempt for its source."""
        self._attempt(cam.family, True, time.time() if now is None else now)
        self.dirty = True

    def healthy(self, cam):
        """60 s of good playback: forget the camera's failures."""
        if self.cams.pop(cam.id, None) is not None:
            self.dirty = True

    def saw_height(self, cam, height, now=None):
        self.lowres[cam.id] = [height, time.time() if now is None else now]
        self.dirty = True

    def prune(self, ids, now=None):
        """Drop entries for cameras no longer in the catalogue, and stale attempts."""
        now = time.time() if now is None else now
        ids = set(ids)
        for table in (self.cams, self.lowres):
            for cid in [c for c in table if c not in ids]:
                del table[cid]
        for family in list(self.attempts):
            kept = [a for a in self.attempts[family] if now - a[0] < SOURCE_WINDOW]
            if kept:
                self.attempts[family] = kept
            else:
                del self.attempts[family]
        for family in [f for f, until in self.sources.items() if until <= now]:
            del self.sources[family]
        self.dirty = True


class History(object):
    """The last HISTORY_SIZE cameras shown, newest last, and the user's favourites."""

    def __init__(self, path):
        self.path = path
        data = _load(path)
        self.shown = [entry for entry in data.get('shown') or [] if isinstance(entry, list) and len(entry) == 2]
        self.favourites = list(data.get('favourites') or [])
        self.dirty = False

    def save(self):
        if self.dirty:
            _save(self.path, {'shown': self.shown, 'favourites': self.favourites})
            self.dirty = False

    def add(self, cam_id, now=None):
        self.shown.append([cam_id, time.time() if now is None else now])
        self.shown = self.shown[-HISTORY_SIZE:]
        self.dirty = True

    def recent(self, now=None, window=RECENT):
        now = time.time() if now is None else now
        return set(cid for cid, t in self.shown if now - t < window)

    def last(self):
        return self.shown[-1][0] if self.shown else None

    def favourite(self, cam_id):
        if cam_id and cam_id not in self.favourites:
            self.favourites.append(cam_id)
            self.dirty = True
            return True
        return False

    def clear_favourites(self):
        self.favourites = []
        self.dirty = True

    def reset(self):
        self.shown = []
        self.dirty = True

    def prune(self, ids):
        ids = set(ids)
        self.favourites = [f for f in self.favourites if f in ids]
        self.dirty = True

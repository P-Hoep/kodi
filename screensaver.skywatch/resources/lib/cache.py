"""On-disk caches under the add-on's profile folder. No Kodi imports.

- JsonCache: SQLite rows of (key, body, fetched_at, expires_at). Scenes read only from here.
- TileStore: base-map tiles keyed source/z/x/y, downloaded in the background.
- evict(): keeps the whole profile under the user's size limit, oldest radar frames first,
  base maps last.
"""

import json
import os
import sqlite3
import threading
import time

from . import net
from .workers import Workers


class JsonCache(object):
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        self._db = sqlite3.connect(path, timeout=10, check_same_thread=False)
        with self.lock:
            self._db.execute('CREATE TABLE IF NOT EXISTS json (key TEXT PRIMARY KEY, body TEXT, '
                             'fetched REAL, expires REAL)')
            self._db.execute('CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)')
            self._db.commit()

    def put(self, key, value, ttl, fetched=None):
        fetched = time.time() if fetched is None else fetched
        with self.lock:
            self._db.execute('INSERT OR REPLACE INTO json VALUES (?, ?, ?, ?)',
                             (key, json.dumps(value, separators=(',', ':')), fetched, fetched + ttl))
            self._db.commit()

    def get(self, key):
        """-> (value, fetched_at, fresh) or (None, None, False)."""
        with self.lock:
            row = self._db.execute('SELECT body, fetched, expires FROM json WHERE key = ?', (key,)).fetchone()
        if not row:
            return None, None, False
        try:
            return json.loads(row[0]), row[1], time.time() < row[2]
        except ValueError:
            return None, None, False

    def value(self, key):
        return self.get(key)[0]

    def fresh(self, key):
        return self.get(key)[2]

    def expire(self, key):
        with self.lock:
            self._db.execute('UPDATE json SET expires = 0 WHERE key = ?', (key,))
            self._db.commit()

    def setkv(self, key, value):
        with self.lock:
            self._db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (key, json.dumps(value)))
            self._db.commit()

    def getkv(self, key, default=None):
        with self.lock:
            row = self._db.execute('SELECT value FROM kv WHERE key = ?', (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except ValueError:
            return default

    def clear(self):
        with self.lock:
            self._db.execute('DELETE FROM json')
            self._db.commit()

    def close(self):
        with self.lock:
            self._db.close()


class TileSource(object):
    def __init__(self, sid, url, ext, attribution, max_zoom=19, max_age=None, workers=3, retina=False):
        self.id = sid
        self._url = url
        self.ext = ext
        self.attribution = attribution
        self.max_zoom = max_zoom
        self.max_age = max_age     # None: never expires (base maps do not change)
        self.workers = workers
        self.retina = retina

    def url(self, z, x, y):
        if callable(self._url):
            return self._url(z, x, y)
        return self._url.format(z=z, x=x, y=y, r='@2x' if self.retina else '')


class TileStore(object):
    """ensure() returns a ready path or schedules a download and returns None."""

    def __init__(self, root, on_ready=None, log=None, counter=None):
        self.root = root
        self.on_ready = on_ready or (lambda *a: None)
        self.log = log or (lambda msg: None)
        self.counter = counter or (lambda source_id: None)
        self._pools = {}
        self._pending = set()
        self._failed = {}
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def path(self, source, z, x, y):
        name = '%d_%d_%d%s.%s' % (z, x, y, '@2x' if source.retina else '', source.ext)
        return os.path.join(self.root, source.id, str(z), name)

    def ensure(self, source, z, x, y):
        path = self.path(source, z, x, y)
        try:
            age = time.time() - os.path.getmtime(path)
            if source.max_age is None or age < source.max_age:
                self.hits += 1
                return path
        except OSError:
            pass
        self.misses += 1
        with self._lock:
            if path in self._pending or time.time() - self._failed.get(path, 0) < 60:
                return None
            self._pending.add(path)
        pool = self._pools.get(source.id)
        if pool is None:
            pool = self._pools[source.id] = Workers(source.workers, 'tiles-' + source.id)
        pool.submit(self._download, source, (z, x, y), path)
        return None

    def _download(self, source, key, path):
        try:
            body = net.fetch_image(source.url(*key), timeout=10, max_bytes=4 * 1024 * 1024)
            self.counter(source.id)
            write_atomic(path, body)
            self.on_ready(source.id, key, path)
        except Exception as error:  # network or disk; retry after a pause
            with self._lock:
                self._failed[path] = time.time()
            self.log('tile %s %s failed: %s' % (source.id, key, error))
        finally:
            with self._lock:
                self._pending.discard(path)

    def shutdown(self):
        for pool in self._pools.values():
            pool.shutdown()


def write_atomic(path, body):
    folder = os.path.dirname(path)
    try:
        os.makedirs(folder)
    except OSError:
        if not os.path.isdir(folder):  # parallel workers may race to create it
            raise
    tmp = '%s.%d.part' % (path, threading.get_ident())
    mode = 'w' if isinstance(body, str) else 'wb'
    with open(tmp, mode) as handle:
        handle.write(body)
    os.replace(tmp, path)


# Eviction order: the first folders listed lose files first.
EVICT_ORDER = ('frames', 'charts', 'thumbs', 'tiles')


def evict(profile, limit_bytes, log=None):
    """Delete the oldest files until the profile fits in limit_bytes. Returns bytes freed."""
    files = []
    total = 0
    for folder, _dirs, names in os.walk(profile):
        for name in names:
            full = os.path.join(folder, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            total += st.st_size
            top = os.path.relpath(full, profile).split(os.sep)[0]
            if top in EVICT_ORDER and not name.endswith('.json'):
                files.append((EVICT_ORDER.index(top), st.st_mtime, st.st_size, full))
    freed = 0
    if total <= limit_bytes:
        return 0
    files.sort()
    for _rank, _mtime, size, full in files:
        if total - freed <= limit_bytes * 0.9:
            break
        try:
            os.remove(full)
            freed += size
        except OSError:
            pass
    if log:
        log('cache: freed %.1f MB (was %.1f MB, limit %.0f MB)' % (freed / 1e6, total / 1e6, limit_bytes / 1e6))
    return freed


def remove_older(folder, max_age, keep=()):
    """Delete files in folder (recursively) older than max_age seconds, except paths in keep."""
    now = time.time()
    for root, _dirs, names in os.walk(folder):
        for name in names:
            full = os.path.join(root, name)
            if full in keep:
                continue
            try:
                if now - os.path.getmtime(full) > max_age:
                    os.remove(full)
            except OSError:
                pass

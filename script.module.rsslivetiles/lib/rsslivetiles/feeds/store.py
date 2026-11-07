"""Everything on disk, in the library's addon_data folder (shared by the program and the
screensaver):

  feeds.json          the feed list (spec 3.5)
  cache/<id>.json     one parsed feed: info, items and fetch state (ETag, failures, next try)
  state.json          per-feed "last viewed" time and hidden items
  qr/                 QR code PNGs for the detail view

Every write goes to *.tmp first and is then renamed, so a power cut never leaves half a file.
"""

import hashlib
import json
import os
import re
import shutil
import threading
import time

from .parser import FeedInfo, FeedItem

SIZES = ('small', 'medium', 'wide', 'large')
SAMPLE_FEEDS = [
    ('BBC News', 'https://feeds.bbci.co.uk/news/rss.xml'),
    ('r/kodi', 'https://www.reddit.com/r/kodi.rss'),
    ('NASA Image of the Day', 'https://www.nasa.gov/feeds/iotd-feed/'),
]
MIN_KEEP = 3            # retention never empties a quiet feed completely
HIDDEN_CAP = 1000


def atomic_write(path, data):
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    tmp = '%s.%d.tmp' % (path, threading.get_ident())
    with open(tmp, 'wb') as handle:
        handle.write(data)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def feed_id_for(url):
    return hashlib.sha1(url.strip().encode('utf-8')).hexdigest()[:8]


class Feed(object):
    """One entry of feeds.json. None for accent / max_items / refresh_min / tile_size means
    'use the global setting'."""

    FIELDS = ('id', 'url', 'title', 'accent', 'enabled', 'max_items', 'refresh_min', 'tile_size')

    def __init__(self, url, title='', id=None, accent=None, enabled=True, max_items=None, refresh_min=None,
                 tile_size=None):
        self.url = url.strip()
        self.id = id or feed_id_for(self.url)
        self.title = title
        self.accent = accent
        self.enabled = bool(enabled)
        self.max_items = max_items
        self.refresh_min = refresh_min
        self.tile_size = tile_size if tile_size in SIZES else None

    def to_dict(self):
        return dict((f, getattr(self, f)) for f in self.FIELDS)

    @classmethod
    def from_dict(cls, d):
        return cls(d.get('url', ''), d.get('title', ''), d.get('id'), d.get('accent'), d.get('enabled', True),
                   d.get('max_items'), d.get('refresh_min'), d.get('tile_size'))

    def __repr__(self):
        return 'Feed(%r, %r)' % (self.id, self.title or self.url)


class FeedData(object):
    """A feed's cache file: what we know about it plus its fetch state."""

    def __init__(self, feed_id, info=None, items=None, meta=None):
        self.feed_id = feed_id
        self.info = info or FeedInfo()
        self.items = items or []
        self.meta = meta or {}

    @property
    def error(self):
        return self.meta.get('error', '')

    @property
    def fetched_at(self):
        return float(self.meta.get('fetched_at', 0) or 0)

    def to_dict(self):
        return {'version': 1, 'info': self.info.to_dict(), 'meta': self.meta,
                'items': [i.to_dict() for i in self.items]}

    @classmethod
    def from_dict(cls, feed_id, d):
        items = []
        for raw in d.get('items', []):
            try:
                items.append(FeedItem.from_dict(raw))
            except (TypeError, ValueError, AttributeError):
                continue
        return cls(feed_id, FeedInfo.from_dict(d.get('info')), items, d.get('meta') or {})


def retain(items, max_items, max_age_days, now):
    """Newest first, at most max_items, nothing older than max_age_days (but always the newest
    MIN_KEEP, so a quiet feed never goes blank)."""
    items = sorted(items, key=lambda i: i.published, reverse=True)
    out = []
    cutoff = now - max_age_days * 86400 if max_age_days else None
    for i, item in enumerate(items):
        if len(out) >= max_items:
            break
        if cutoff is not None and item.published < cutoff and i >= MIN_KEEP:
            continue
        out.append(item)
    return out


def merge(old, new):
    """Items from a fresh fetch replace cached ones with the same id; cached items that have
    dropped off the feed stay (retention removes them later). An item without a date in the
    feed keeps the time we first saw it."""
    by_id = dict((i.id, i) for i in old)
    for item in new:
        prev = by_id.get(item.id)
        if prev is not None and not item.dated:
            item.published = prev.published
        by_id[item.id] = item
    return list(by_id.values())


class Store(object):
    def __init__(self, root):
        self.root = root
        self.lock = threading.RLock()
        self._data = {}

    # ------------------------------------------------------------ feeds.json

    @property
    def feeds_path(self):
        return os.path.join(self.root, 'feeds.json')

    def feeds(self):
        """The feed list; the sample feeds on first run."""
        data = read_json(self.feeds_path)
        if data is None:
            feeds = [Feed(url, title) for title, url in SAMPLE_FEEDS]
            self.save_feeds(feeds)
            return feeds
        out, seen = [], set()
        for raw in data.get('feeds', []):
            if not isinstance(raw, dict) or not raw.get('url'):
                continue
            feed = Feed.from_dict(raw)
            if feed.id in seen:
                continue
            seen.add(feed.id)
            out.append(feed)
        return out

    def save_feeds(self, feeds):
        data = {'version': 1, 'feeds': [f.to_dict() for f in feeds]}
        with self.lock:
            atomic_write(self.feeds_path, json.dumps(data, indent=1).encode('utf-8'))

    # ------------------------------------------------------------ cache

    def cache_path(self, feed_id):
        return os.path.join(self.root, 'cache', re.sub(r'[^A-Za-z0-9_-]', '_', feed_id) + '.json')

    def load(self, feed_id):
        with self.lock:
            if feed_id not in self._data:
                raw = read_json(self.cache_path(feed_id))
                self._data[feed_id] = FeedData.from_dict(feed_id, raw) if raw else FeedData(feed_id)
            return self._data[feed_id]

    def save(self, data):
        with self.lock:
            self._data[data.feed_id] = data
            atomic_write(self.cache_path(data.feed_id), json.dumps(data.to_dict()).encode('utf-8'))

    def forget(self, feed_id):
        with self.lock:
            self._data.pop(feed_id, None)
            try:
                os.remove(self.cache_path(feed_id))
            except OSError:
                pass

    def clear_cache(self):
        with self.lock:
            self._data.clear()
            shutil.rmtree(os.path.join(self.root, 'cache'), ignore_errors=True)
            shutil.rmtree(os.path.join(self.root, 'qr'), ignore_errors=True)

    # ------------------------------------------------------------ state.json

    @property
    def state_path(self):
        return os.path.join(self.root, 'state.json')

    def state(self):
        data = read_json(self.state_path) or {}
        data.setdefault('last_view', {})
        data.setdefault('hidden', [])
        return data

    def save_state(self, state):
        state['hidden'] = state.get('hidden', [])[-HIDDEN_CAP:]
        with self.lock:
            atomic_write(self.state_path, json.dumps(state).encode('utf-8'))

    def mark_read(self, feed_ids, now=None):
        state = self.state()
        for fid in feed_ids:
            state['last_view'][fid] = now or time.time()
        self.save_state(state)

    def hide(self, item_id):
        state = self.state()
        if item_id not in state['hidden']:
            state['hidden'].append(item_id)
        self.save_state(state)

    # ------------------------------------------------------------ QR

    def qr_path(self, url):
        return os.path.join(self.root, 'qr', hashlib.sha1(url.encode('utf-8')).hexdigest()[:16] + '.png')

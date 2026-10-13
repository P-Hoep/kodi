"""Per-source request counters, caps and back-off. No Kodi imports.

Counters live in the JSON cache's key-value table so the service and the screensaver share
them. Back-off follows the spec: after an HTTP 429 or a server error, wait 1 min, doubling
up to 60 min; any success resets it.
"""

import threading
import time

BACKOFF_START = 60.0
BACKOFF_MAX = 3600.0


def month_key(now=None):
    return time.strftime('%Y-%m', time.gmtime(time.time() if now is None else now))


def day_key(now=None):
    return time.strftime('%Y-%m-%d', time.gmtime(time.time() if now is None else now))


class Budget(object):
    def __init__(self, store=None):
        self.store = store          # a cache.JsonCache, or None for in-memory only
        self.lock = threading.Lock()
        self.counts = {}            # (source, period key) -> requests
        self.backoff = {}           # source -> (next allowed time, current delay)
        self.status = {}            # source -> ('OK'|'Stale'|'Down', message, time)
        if store is not None:
            self.counts = dict((tuple(k.split('|', 1)), v) for k, v in (store.getkv('budget', {}) or {}).items())

    # ------------------------------------------------------------ counting

    def count(self, source, n=1, now=None):
        with self.lock:
            for key in (day_key(now), month_key(now)):
                self.counts[(source, key)] = self.counts.get((source, key), 0) + n

    def used_today(self, source, now=None):
        return self.counts.get((source, day_key(now)), 0)

    def used_month(self, source, now=None):
        return self.counts.get((source, month_key(now)), 0)

    def allows(self, source, cost, cap, share=0.9, now=None):
        """True if spending cost more requests keeps this month's use under share * cap."""
        return self.used_month(source, now) + cost <= cap * share

    def save(self):
        if self.store is None:
            return
        with self.lock:
            month, day = month_key(), day_key()
            keep = dict(('%s|%s' % k, v) for k, v in self.counts.items() if k[1] in (month, day))
        self.store.setkv('budget', keep)

    # ------------------------------------------------------------ back-off

    def ready(self, source, now=None):
        now = time.time() if now is None else now
        return now >= self.backoff.get(source, (0.0, 0.0))[0]

    def failed(self, source, status=None, message='', now=None):
        """Record a failure. 429 and 5xx back off exponentially; others retry in 2 min."""
        now = time.time() if now is None else now
        with self.lock:
            if status == 429 or (status or 0) >= 500:
                delay = self.backoff.get(source, (0.0, 0.0))[1]
                delay = BACKOFF_START if delay <= 0 else min(BACKOFF_MAX, delay * 2)
            else:
                delay = 120.0
            self.backoff[source] = (now + delay, delay)
            self.status[source] = ('Down', message or ('HTTP %s' % status if status else 'error'), now)
        return delay

    def ok(self, source, now=None):
        with self.lock:
            self.backoff.pop(source, None)
            self.status[source] = ('OK', '', time.time() if now is None else now)

    def stale(self, source, message=''):
        with self.lock:
            self.status[source] = ('Stale', message, time.time())

    def summary(self):
        with self.lock:
            return dict(self.status)

"""Progress-sync bookkeeping, kept free of Kodi so it can be tested.

Audiobookshelf is the source of truth. While a book plays, the service reports through
the playback session (POST /api/session/:id/sync every N seconds, on pause, and
/close on stop). If the session has gone (404: server restarted or expired the session)
it falls back to PATCH /api/me/progress/:id. If the server can't be reached at all, the
last position is written to a small pending file and retried later, a bounded number of
times, and dropped if the server has a newer update by then.
"""

import json
import os
import time

MAX_LISTEN_STEP = 5.0     # seconds of wall time credited per tick, so a stall isn't "listening"
RETRY_BACKOFF = (15, 30, 60, 120, 300)
PENDING_MAX_ATTEMPTS = 20
PENDING_MAX_AGE = 7 * 86400


class Tracker(object):
    """Position and listened time for one playback session."""

    def __init__(self, duration, interval, now=None):
        self.duration = duration
        self.interval = interval
        self.position = None        # last known book time
        self.listened = 0.0         # listened seconds not yet reported
        self.last_tick = None
        self.last_sent = now if now is not None else time.time()
        self.failures = 0
        self.next_try = 0.0
        self.dirty = False          # position changed since the last successful report

    def tick(self, position, playing, now):
        if position is not None:
            if self.position is None or abs(position - self.position) > 0.5:
                self.dirty = True
            self.position = position
        if playing and self.last_tick is not None:
            self.listened += max(0.0, min(MAX_LISTEN_STEP, now - self.last_tick))
        self.last_tick = now if playing else None

    def due(self, now):
        return (self.position is not None and now >= self.next_try
                and now - self.last_sent >= self.interval and (self.dirty or self.listened >= 1))

    def payload(self, ended=False):
        t = self.duration if ended and self.duration else (self.position or 0.0)
        if self.duration:
            t = min(t, self.duration)
        return {'currentTime': round(t, 3), 'timeListened': round(self.listened, 3),
                'duration': self.duration}

    def sent(self, payload, now):
        self.listened = max(0.0, self.listened - payload['timeListened'])
        self.last_sent = now
        self.failures = 0
        self.next_try = 0.0
        self.dirty = False

    def failed(self, now):
        """Keep the unreported time; back off before the next try."""
        self.failures += 1
        self.next_try = now + RETRY_BACKOFF[min(self.failures, len(RETRY_BACKOFF)) - 1]


def near_end(position, duration, slack=60.0):
    return bool(duration) and position is not None and position >= duration - slack


class Pending(object):
    """Positions that couldn't be sent, keyed by book: {item_id: {...}} in a JSON file."""

    def __init__(self, path):
        self.path = path

    def load(self):
        try:
            with open(self.path) as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, data):
        if not data:
            try:
                os.remove(self.path)
            except OSError:
                pass
            return
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as handle:
            json.dump(data, handle)
        os.replace(tmp, self.path)

    def add(self, item_id, current_time, duration, now=None):
        data = self.load()
        data[item_id] = {'currentTime': current_time, 'duration': duration,
                         'stamp': int((now if now is not None else time.time()) * 1000), 'attempts': 0}
        self.save(data)

    def discard(self, item_id):
        data = self.load()
        if data.pop(item_id, None) is not None:
            self.save(data)

    def flush(self, client, log=lambda message: None, now=None):
        """Try each pending position once. A newer update on the server wins (someone
        listened elsewhere since), and entries give up after PENDING_MAX_ATTEMPTS."""
        from .api import NotFound, Unreachable
        data = self.load()
        if not data:
            return 0
        now = now if now is not None else time.time()
        sent = 0
        for item_id, entry in list(data.items()):
            if now * 1000 - entry.get('stamp', 0) > PENDING_MAX_AGE * 1000:
                del data[item_id]
                continue
            try:
                server = client.progress(item_id)
                if server and (server.get('lastUpdate') or 0) > entry.get('stamp', 0):
                    log('pending %s: the server has a newer position, dropping ours' % item_id)
                else:
                    client.update_progress(item_id, entry['currentTime'], entry.get('duration') or 0)
                    log('pending %s: sent %.0f s' % (item_id, entry['currentTime']))
                    sent += 1
                del data[item_id]
            except Unreachable:
                entry['attempts'] = entry.get('attempts', 0) + 1
                if entry['attempts'] >= PENDING_MAX_ATTEMPTS:
                    log('pending %s: giving up after %d attempts' % (item_id, entry['attempts']))
                    del data[item_id]
                break  # the server is down; don't hammer it for each entry
            except NotFound:
                del data[item_id]  # the book was removed
            except Exception as error:
                entry['attempts'] = entry.get('attempts', 0) + 1
                log('pending %s: %s' % (item_id, error))
                if entry['attempts'] >= PENDING_MAX_ATTEMPTS:
                    del data[item_id]
        self.save(data)
        return sent

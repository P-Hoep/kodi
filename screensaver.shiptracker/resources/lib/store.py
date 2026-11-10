"""The on-disk cache: a small SQLite database in the add-on profile.

Two things are kept there, and both exist so the screensaver does not ask the network again for
something it already knows:

* ``ships`` - the last AIS identity, position and voyage for each MMSI. It is seeded into the
  fleet at start-up, so a restart shows the last known ships instantly while the stream
  reconnects, and a ship that only sends position reports keeps the name and dimensions it
  broadcast days ago.
* ``profiles`` - the merged Wikidata/Commons result for an MMSI, with the identifier signature
  it was built from. A ship that keeps showing up reuses it for a month; a "nothing found"
  result is retried after a week; a new IMO number changes the signature and triggers a fresh
  lookup.

Only sqlite3 from the standard library is used. The class is safe to share between the AIS
thread, the lookup worker and the UI.
"""

import json
import os
import sqlite3
import threading
import time

from . import config

SHIP_COLUMNS = ('mmsi', 'name', 'call_sign', 'imo', 'ship_type', 'lat', 'lon', 'sog', 'cog',
                'heading', 'nav_status', 'rate_of_turn', 'destination', 'eta', 'draught',
                'length', 'beam', 'first_seen', 'seen', 'static_seen', 'updated')

SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS ships (
        mmsi INTEGER PRIMARY KEY,
        name TEXT, call_sign TEXT, imo INTEGER, ship_type INTEGER,
        lat REAL, lon REAL, sog REAL, cog REAL, heading REAL, nav_status INTEGER,
        rate_of_turn INTEGER, destination TEXT, eta TEXT, draught REAL,
        length REAL, beam REAL, first_seen REAL, seen REAL, static_seen REAL, updated REAL
    )''',
    '''CREATE TABLE IF NOT EXISTS profiles (
        mmsi INTEGER PRIMARY KEY,
        signature TEXT NOT NULL,
        payload TEXT NOT NULL,
        fetched_at REAL NOT NULL
    )''',
)


class Store(object):
    def __init__(self, path, clock=time.time):
        self.path = path
        self.clock = clock
        self._lock = threading.RLock()
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
        self._conn = self._open()
        self._last_commit = self.clock()
        self._pending = 0

    def _open(self):
        try:
            return self._connect()
        except sqlite3.DatabaseError:
            # A half-written or corrupt database must not stop the screensaver. Move it aside
            # and start clean; the next AIS message fills it again.
            try:
                os.replace(self.path, '%s.corrupt-%d' % (self.path, int(self.clock())))
            except OSError:
                pass
            return self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        conn.execute('PRAGMA busy_timeout=5000')
        try:
            conn.execute('PRAGMA journal_mode=WAL')
        except sqlite3.DatabaseError:
            pass
        for statement in SCHEMA:
            conn.execute(statement)
        conn.commit()
        return conn

    # ------------------------------------------------------------------ ships
    def save_ship(self, ship, force=False):
        values = [ship.get(column) for column in SHIP_COLUMNS]
        placeholders = ','.join('?' for _ in SHIP_COLUMNS)
        with self._lock:
            self._conn.execute(
                'INSERT OR REPLACE INTO ships (%s) VALUES (%s)'
                % (','.join(SHIP_COLUMNS), placeholders), values)
            self._pending += 1
            self._maybe_commit(force=force)
        return True

    def save_ships(self, ships):
        for ship in ships:
            self.save_ship(ship)
        self.commit()

    def load_ships(self, limit=500):
        with self._lock:
            try:
                cursor = self._conn.execute(
                    'SELECT * FROM ships ORDER BY updated DESC LIMIT ?', (int(limit),))
                columns = [description[0] for description in cursor.description]
                rows = cursor.fetchall()
            except sqlite3.DatabaseError:
                return []
        return [dict(zip(columns, row)) for row in rows]

    def prune(self, older_than=90 * 24 * 3600):
        cutoff = self.clock() - older_than
        with self._lock:
            self._conn.execute(
                'DELETE FROM ships WHERE COALESCE(seen, updated, 0) < ?', (cutoff,))
            self._conn.commit()

    # ------------------------------------------------------------------ profiles
    def get_profile(self, mmsi):
        """{'signature', 'data', 'fetched_at'} or None. data is None for a negative result."""
        with self._lock:
            try:
                row = self._conn.execute(
                    'SELECT signature, payload, fetched_at FROM profiles WHERE mmsi = ?',
                    (int(mmsi),)).fetchone()
            except (sqlite3.DatabaseError, TypeError, ValueError):
                return None
        if row is None:
            return None
        try:
            data = json.loads(row[1])
        except (TypeError, ValueError):
            return None
        return {'signature': row[0], 'data': data, 'fetched_at': float(row[2] or 0)}

    def put_profile(self, mmsi, signature, data, fetched_at=None):
        fetched_at = self.clock() if fetched_at is None else fetched_at
        payload = json.dumps(data, ensure_ascii=False, default=str)
        with self._lock:
            self._conn.execute(
                'INSERT OR REPLACE INTO profiles (mmsi, signature, payload, fetched_at) '
                'VALUES (?, ?, ?, ?)', (int(mmsi), signature, payload, fetched_at))
            self._pending += 1
            self._maybe_commit(force=True)

    def profile_is_fresh(self, mmsi, signature, now=None):
        """True when this exact identifier set was looked up recently enough to reuse."""
        now = self.clock() if now is None else now
        row = self.get_profile(mmsi)
        if row is None or row['signature'] != signature:
            return False
        ttl = config.PROFILE_TTL if row['data'] else config.NEGATIVE_TTL
        return now - row['fetched_at'] < ttl

    # ------------------------------------------------------------------ housekeeping
    def _maybe_commit(self, force=False):
        if force or self._pending >= 40 or self.clock() - self._last_commit >= 5.0:
            self.commit()

    def commit(self):
        with self._lock:
            try:
                self._conn.commit()
            except sqlite3.DatabaseError:
                pass
            self._pending = 0
            self._last_commit = self.clock()

    def clear(self):
        with self._lock:
            for table in ('ships', 'profiles'):
                try:
                    self._conn.execute('DELETE FROM %s' % table)
                except sqlite3.DatabaseError:
                    pass
            self.commit()

    def close(self):
        with self._lock:
            self.commit()
            try:
                self._conn.close()
            except sqlite3.DatabaseError:
                pass

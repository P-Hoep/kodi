"""The AIS connection thread: subscribe, read messages, put them in the fleet and the database.

The public stream can drop at any time, so the loop reconnects with a backoff and re-sends the
subscription. The raw WebSocket client lives in ws.py; this module only knows about AIS and the
two caches. State is read by the screen through a lock, never by blocking on the socket.
"""

import json
import threading
import time

from . import ais, config, sources, ws


class Tracker(threading.Thread):
    def __init__(self, api_key, boxes, fleet, store, enricher=None, debug=None,
                 clock=time.time, connection_factory=None):
        threading.Thread.__init__(self, name='shiptracker-ais')
        self.daemon = True
        self.api_key = (api_key or '').strip()
        self.boxes = [tuple(box) for box in boxes]
        self.fleet = fleet
        self.store = store
        self.enricher = enricher
        self.debug = debug
        self.clock = clock
        self.connection_factory = connection_factory or self._default_connection
        self._halt = threading.Event()
        self._lock = threading.RLock()
        self._client = None
        self.state = 'idle'           # idle, no_key, connecting, connected, error, stopped
        self.messages = 0
        self.last_message_at = 0.0
        self.last_error = None
        self.connected_at = 0.0
        self._enqueued = {}

    def _default_connection(self):
        return ws.WebSocket(config.STREAM_HOST, config.STREAM_PORT, config.STREAM_PATH,
                            timeout=config.HTTP_TIMEOUT)

    # ------------------------------------------------------------------ state
    def snapshot(self):
        with self._lock:
            return {'state': self.state, 'messages': self.messages,
                    'last_message_at': self.last_message_at, 'last_error': self.last_error,
                    'connected_at': self.connected_at,
                    'pending_lookups': self.enricher.pending() if self.enricher else 0}

    def _set_state(self, state, error=None):
        with self._lock:
            self.state = state
            self.last_error = error

    def stop(self):
        self._halt.set()
        client = self._client
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ loop
    def run(self):
        if not self.api_key:
            self._set_state('no_key')
            return
        backoff = 5
        while not self._halt.is_set():
            self._set_state('connecting')
            client = None
            try:
                client = self.connection_factory()
                self._client = client
                client.connect()
                client.send_text(json.dumps(config.subscription(self.api_key, self.boxes)))
                with self._lock:
                    self.state = 'connected'
                    self.last_error = None
                    self.connected_at = self.clock()
                backoff = 5
                self._read(client)
            except Exception as error:
                if self._halt.is_set():
                    break
                self._set_state('error', '%s: %s' % (type(error).__name__, error))
                self._log('connection lost: %s' % error)
            finally:
                self._client = None
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass
            if self._halt.is_set():
                break
            self._halt.wait(backoff)
            backoff = min(60, backoff * 2)
        self._set_state('stopped')

    def _read(self, client):
        while not self._halt.is_set():
            raw = client.recv_text(timeout=5)
            if raw is None:
                continue
            try:
                message = json.loads(raw)
            except ValueError:
                self._log('ignored a message that was not JSON')
                continue
            if not isinstance(message, dict):
                continue
            if message.get('error'):
                raise RuntimeError('server error: %s' % message['error'])
            self._handle(message)

    def _handle(self, message):
        now = self.clock()
        mmsi = self.fleet.handle(message, now=now)
        if mmsi is None:
            return
        ship = self.fleet.get(mmsi)
        if ship is None:
            return
        message_type = message.get('MessageType')
        self.store.save_ship(ship, force=message_type in config.STATIC_TYPES)
        with self._lock:
            self.messages += 1
            self.last_message_at = now
        self._maybe_enrich(ship, now)

    def _maybe_enrich(self, ship, now):
        if self.enricher is None:
            return
        mmsi = ship['mmsi']
        signature_value = sources.ship_signature(ship)
        previous = self._enqueued.get(mmsi)
        if previous is not None and previous[0] == signature_value and \
                now - previous[1] < 300:
            return
        self._enqueued[mmsi] = (signature_value, now)
        self.enricher.enqueue(ship)

    def _log(self, message):
        if self.debug:
            self.debug(message)

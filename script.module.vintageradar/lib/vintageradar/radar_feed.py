"""Fetching the aircraft feed: adsb.lol first, OpenSky as the fallback.

Same endpoints and fallback rules as the native screensaver (radar_feed.cpp). urlopen is
passed in, so the offline tests never touch the network.
"""

import math
import threading
import time

from . import radar_core


def fetch_radius_nm(range_km):
    # Pull a little past the displayed range so a plane does not pop into existence at the rim.
    nm = math.ceil((range_km / 1.852) * 1.25)
    return int(max(10.0, min(250.0, nm)))


def adsblol_url(settings):
    return 'https://api.adsb.lol/v2/lat/%.3f/lon/%.3f/dist/%d' % (
        settings.lat, settings.lon, fetch_radius_nm(settings.range_km))


def opensky_url(settings):
    pad_km = settings.range_km * 1.35 + 5.0
    dlat = pad_km / 111.32
    coslat = max(0.15, math.cos(settings.lat * math.pi / 180.0))
    dlon = dlat / coslat
    return ('https://opensky-network.org/api/states/all?lamin=%.4f&lomin=%.4f'
            '&lamax=%.4f&lomax=%.4f' % (
                max(-90.0, settings.lat - dlat), max(-180.0, settings.lon - dlon),
                min(90.0, settings.lat + dlat), min(180.0, settings.lon + dlon)))


def _join(first, second):
    if not first:
        return second
    if not second:
        return first
    return first + ' | ' + second


class FeedPump(object):
    """Fetches in the background; the UI thread takes (feed, error) results without blocking."""

    def __init__(self, settings, urlopen):
        self.settings = settings
        self.urlopen = urlopen
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.has_result = False
        self.pending_feed = None
        self.pending_error = ''
        self.result_is_error = False
        self.url = ''
        self.fetching = False

    def start(self):
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._run, name='vintageradar-feed')
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        thread = self.thread
        self.thread = None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)

    def take(self):
        """(feed, error) or None. A feed is either a radar_core.Feed or an error string."""
        with self.lock:
            if not self.has_result:
                return None
            self.has_result = False
            if self.result_is_error:
                return None, self.pending_error
            feed = self.pending_feed
            self.pending_feed = None
            return feed, ''

    def _sleep(self, seconds):
        return not self.stop_event.wait(seconds)

    def _run(self):
        while not self.stop_event.is_set():
            self.fetching = True
            primary = adsblol_url(self.settings)
            with self.lock:
                self.url = primary
            feed = None
            error = ''
            body, failure = self._fetch(primary)
            if body is not None:
                try:
                    feed = radar_core.parse_adsblol(body)
                except radar_core.FeedError as problem:
                    error = str(problem)
            if feed is None:
                fallback = opensky_url(self.settings)
                with self.lock:
                    self.url = fallback
                body, failure = self._fetch(fallback)
                if body is not None:
                    try:
                        feed = radar_core.parse_opensky(body)
                    except radar_core.FeedError as problem:
                        error = _join(error, str(problem))
                else:
                    error = _join(error, failure)
            with self.lock:
                if feed is not None:
                    self.pending_feed = feed
                    self.result_is_error = False
                else:
                    self.pending_error = error or 'No data from adsb.lol or OpenSky'
                    self.result_is_error = True
                self.has_result = True
            self.fetching = False
            if self.stop_event.is_set():
                break
            wait = (max(10, self.settings.refresh_seconds) if feed is not None
                    else min(30, max(10, self.settings.refresh_seconds // 2)))
            if not self._sleep(wait):
                break
        self.fetching = False

    def _fetch(self, url):
        try:
            data = self.urlopen(url)
        except Exception as error:
            return None, '%s: %s' % (url.split('/')[2] if '//' in url else 'source', error)
        if isinstance(data, bytes):
            data = data.decode('utf-8', 'replace')
        return data, ''

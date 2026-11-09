"""The datasets-server client: random batches of rows, single-row re-requests, backoff.
No Kodi imports.

One metadata request per batch. The response carries the signed image URLs as well as the row
data, so nothing else is fetched per row. A 429 or 5xx is retried with the configured backoff; a
4xx caused by the dataset itself moves on to the next configured source.
"""

import random as random_module
import time
from urllib.parse import urlencode

from . import net
from .config import API, BACKOFF, SOURCES

CONFIG = 'default'
SPLIT = 'train'
MAX_ATTEMPTS = 8


class Aborted(Exception):
    """The screensaver was closed; every wait stops immediately."""


class Item(object):
    """One row: enough to download, place, name and put on a map."""

    __slots__ = ('row_idx', 'src', 'width', 'height', 'country', 'address', 'latitude',
                 'longitude')

    def __init__(self, row_idx, src, country='', address='', width=0, height=0, latitude=None,
                 longitude=None):
        self.row_idx = row_idx
        self.src = src
        self.country = (country or '').strip().upper()
        self.address = address or ''
        self.width = width
        self.height = height
        self.latitude = latitude
        self.longitude = longitude

    def __repr__(self):
        return 'Item(%d, %s)' % (self.row_idx, self.country)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coord(value, limit):
    """A coordinate as a float in range, or None. The dataset stores them as strings."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or not -limit <= number <= limit:   # NaN or out of range
        return None
    return number


def parse_rows(payload):
    """Items from a /rows response. Entries without a usable index or image are skipped."""
    items = []
    for entry in (payload or {}).get('rows') or []:
        try:
            row = entry['row']
            row_idx = int(entry['row_idx'])
            image = row['image']
            src = image['src'] if isinstance(image, dict) else image
            if not isinstance(src, str) or not src.startswith('http'):
                continue
            width = _int(image.get('width')) if isinstance(image, dict) else 0
            height = _int(image.get('height')) if isinstance(image, dict) else 0
            items.append(Item(row_idx, src, row.get('country_iso_alpha2') or row.get('country'),
                              row.get('address'), width, height,
                              _coord(row.get('latitude'), 90), _coord(row.get('longitude'), 180)))
        except (KeyError, TypeError, ValueError):
            continue        # a malformed row is skipped, not fatal
    return items


class Client(object):
    def __init__(self, monitor=None, wait=None, rand=None, sources=None, on_retry=None):
        self._monitor = monitor
        self._wait = wait or self._monitor_wait
        self._rand = rand or random_module
        self.sources = list(sources or SOURCES)
        self.source_index = 0
        self._total = 0
        self._on_retry = on_retry

    # -- abort-aware waiting -------------------------------------------------

    def _monitor_wait(self, seconds):
        if self._monitor is None:
            time.sleep(seconds)
            return False
        return self._monitor.waitForAbort(seconds)

    def _backoff(self, attempt, error=None):
        delay = BACKOFF[min(attempt, len(BACKOFF) - 1)]
        if self._on_retry is not None:
            self._on_retry(error, delay)      # lets the screen say it is retrying
        if self._wait(delay):
            raise Aborted()

    def _sleep(self, seconds):
        if self._wait(seconds):
            raise Aborted()

    # -- source and size -----------------------------------------------------

    @property
    def source(self):
        return self.sources[self.source_index]

    def _rotate(self):
        """Move to the next source; called when one keeps failing."""
        self.source_index = (self.source_index + 1) % len(self.sources)
        self._total = 0

    def _get(self, path):
        return net.fetch_json(API + path)

    def total(self):
        """Rows in the current source; asked once per source."""
        if self._total:
            return self._total
        payload = self._get('/size?' + urlencode([('dataset', self.source), ('config', CONFIG),
                                                 ('split', SPLIT)]))
        size = (payload or {}).get('size') or {}
        try:
            self._total = int(size['config']['num_rows'])
        except (KeyError, TypeError, ValueError):
            splits = size.get('splits') or []
            try:
                self._total = int(splits[0]['num_rows'])
            except (IndexError, KeyError, TypeError, ValueError):
                raise net.HttpError('size: no row count for %s' % self.source, 0, 'http')
        if self._total <= 0:
            raise net.HttpError('size: %s is empty' % self.source, 0, 'http')
        return self._total

    def _rows_path(self, offset, length):
        return '/rows?' + urlencode([('dataset', self.source), ('config', CONFIG),
                                     ('split', SPLIT), ('offset', offset), ('length', length)])

    def _fetch_rows(self, offset, length):
        return parse_rows(self._get(self._rows_path(offset, length)))

    # -- public --------------------------------------------------------------

    def batch(self, count, recent=()):
        """Up to `count` rows from a random offset, shuffled and without recent indices."""
        recent = set(recent or ())
        count = max(1, int(count))
        last_error = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                total = self.total()
                length = min(count, total)
                offset = self._rand.randint(0, max(0, total - length))
                items = self._fetch_rows(offset, length)
            except net.HttpError as error:
                last_error = error
                if error.retryable:
                    self._backoff(attempt, error)
                    if attempt % 4 == 3:
                        self._rotate()
                else:
                    self._rotate()
                    self._sleep(1)
                continue
            fresh = [item for item in items if item.row_idx not in recent]
            if fresh:
                self._rand.shuffle(fresh)
                return fresh
            # every row in this batch was shown recently; try another offset
            self._sleep(1)
        raise last_error or net.HttpError('no rows available', 0, 'http')

    def row(self, row_idx):
        """One row by index, for the case where a signed image URL expired."""
        for attempt in range(3):
            try:
                items = self._fetch_rows(int(row_idx), 1)
            except net.HttpError as error:
                if not error.retryable or attempt == 2:
                    raise
                self._backoff(attempt, error)
                continue
            for item in items:
                if item.row_idx == int(row_idx):
                    return item
            return None
        return None

"""Loading a sheet: from the cache straight away, from Google when stale (stale-while-revalidate).

Tab discovery order: Sheets API (only with an API key) -> htmlview -> the 'tab_names' setting
(loaded by name through gviz) -> gid 0 as a single deck named after the sheet.
"""

import threading
import time

from . import parser, sheet
from .deck import Deck


class SheetData(object):
    def __init__(self, sheet_id, title, decks, fetched_at, source=''):
        self.sheet_id = sheet_id
        self.title = title
        self.decks = decks
        self.fetched_at = fetched_at
        self.source = source
        self.offline = False         # set when a refresh failed and this is cached data

    @property
    def usable(self):
        return [d for d in self.decks if d.cards]

    def all_cards(self):
        return [c for d in self.decks for c in d.cards]


class Loader(object):
    def __init__(self, cache, sheet_id, header=parser.HEADER_AUTO, tab_names='', api_key='',
                 get=sheet.http_get, log=None, debug=None):
        self.cache = cache
        self.sheet_id = sheet_id
        self.header = header
        self.tab_names = [t.strip() for t in (tab_names or '').split(',') if t.strip()]
        self.api_key = api_key
        self.get = get
        self.log = log or (lambda message: None)
        self.debug = debug

    # ---------------------------------------------------------------- cache

    def cached(self):
        """SheetData from the cache, or None."""
        info = self.cache.read_tabs(self.sheet_id)
        if not info or not info.get('tabs'):
            return None
        decks = []
        for tab in info['tabs']:
            text = self.cache.read_csv(self.sheet_id, tab)
            if text is None:
                continue
            decks.append(self._deck(tab, text))
        if not decks:
            return None
        return SheetData(self.sheet_id, info.get('title') or '', decks, float(info.get('fetched_at', 0)),
                         info.get('source', ''))

    def is_stale(self, refresh_hours, now=None):
        age = self.cache.age(self.sheet_id, now)
        return age is None or refresh_hours <= 0 or age > refresh_hours * 3600

    def _deck(self, tab, text):
        cards = parser.cards(self.sheet_id, tab, text, self.header, self.debug)
        if not cards:
            self.log('deck "%s" has no usable rows (column A question, column B answer); hidden' % tab['title'])
        return Deck(tab.get('gid'), tab['title'], int(tab.get('index', 0)), cards)

    # ---------------------------------------------------------------- network

    def refresh(self):
        """Download everything, write the cache, return the new SheetData. Raises SheetError."""
        if not self.sheet_id:
            raise sheet.SheetError('no_id')
        started = time.time()
        title, tabs, source = '', [], ''
        try:
            title, tabs, source = sheet.discover_tabs(self.sheet_id, self.api_key, self.get, self.debug)
        except sheet.SheetError as err:
            if err.kind in ('not_public', 'not_found', 'network'):
                raise
            self.log('tab discovery failed: %s' % err)
        if not tabs and self.tab_names:
            tabs = [{'gid': None, 'title': name, 'index': i} for i, name in enumerate(self.tab_names)]
            source = 'tab_names'
        if not tabs:
            tabs = [{'gid': '0', 'title': title or 'Cards', 'index': 0}]
            source = 'gid0'
        decks, failures = [], []
        for tab in tabs:
            try:
                text, how = sheet.fetch_tab(self.sheet_id, tab, self.get, self.debug)
            except sheet.SheetError as err:
                failures.append(err)
                old = self.cache.read_csv(self.sheet_id, tab)
                self.log('tab "%s" failed to load (%s)%s' % (tab['title'], err, '; kept the cached copy' if old else ''))
                if old is not None:
                    decks.append(self._deck(tab, old))
                continue
            deck = self._deck(tab, text)
            self.cache.write_csv(self.sheet_id, tab, text, how, len(deck.cards))
            decks.append(deck)
        if not decks:
            raise failures[0] if failures else sheet.SheetError('bad_data', 'no tabs')
        now = time.time()
        self.cache.write_tabs(self.sheet_id, title, tabs, source, now)
        self.log('loaded %d decks, %d cards in %.1f s (%s)' % (
            len(decks), sum(len(d.cards) for d in decks), time.time() - started, source))
        return SheetData(self.sheet_id, title, decks, now, source)


class Refresher(object):
    """Runs Loader.refresh() on a daemon thread. Poll take() at a card boundary."""

    def __init__(self, loader):
        self.loader = loader
        self.thread = None
        self.result = None
        self.error = None
        self.lock = threading.Lock()
        self.finished = threading.Event()

    def start(self):
        if self.running:
            return False
        self.finished.clear()
        self.thread = threading.Thread(target=self._run, name='sheetcards-refresh')
        self.thread.daemon = True
        self.thread.start()
        return True

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def _run(self):
        try:
            data = self.loader.refresh()
            with self.lock:
                self.result, self.error = data, None
        except sheet.SheetError as err:
            with self.lock:
                self.result, self.error = None, err
        except Exception as err:  # never let a refresh kill the session
            with self.lock:
                self.result, self.error = None, sheet.SheetError('bad_data', repr(err))
        finally:
            self.finished.set()

    def take(self):
        """(data, error) once, after the thread finished; (None, None) otherwise."""
        with self.lock:
            data, error = self.result, self.error
            self.result = self.error = None
        return data, error

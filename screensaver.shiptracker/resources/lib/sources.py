"""Ship details and photos from Wikidata and Wikimedia Commons, with the database as the cache.

AIS knows where a ship is and what it is doing, but not who it is. The enrichment worker looks a
ship up once by IMO (falling back to MMSI) and once by IMO on Commons for photographs, merges the
result and stores it in the profile table. The database decides whether a ship needs a lookup at
all: the identifier signature must have changed or the cached answer must have expired.

Only the standard library is used; requests are sequential and spaced out.
"""

import queue
import re
import threading
import time
import urllib.parse

from . import config, net


def commons_file_url(filename, width=None):
    url = config.COMMONS_FILEPATH + urllib.parse.quote(str(filename).replace(' ', '_'))
    return url + ('?width=%d' % width if width else '')


def commons_page_url(title):
    return ('https://commons.wikimedia.org/wiki/'
            + urllib.parse.quote(str(title).replace(' ', '_')))


def wd_values(entity, prop):
    values = []
    for claim in (entity.get('claims') or {}).get(prop, []):
        value = ((claim.get('mainsnak') or {}).get('datavalue') or {}).get('value')
        if value is not None:
            values.append(value)
    return values


def wd_quantity(values, metres_only=False):
    for value in values:
        try:
            if metres_only and not str(value.get('unit', '')).endswith('/Q11573'):
                continue
            return float(value['amount'])
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return None


def _integer(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_wikidata(imo=None, mmsi=None):
    """Blocking. The Wikidata facts for a ship, or None. Raises net.HttpError/RateLimited."""
    qid = None
    for prop, value in (('P458', imo), ('P587', mmsi)):
        if not value:
            continue
        response = net.get_json(config.WIKIDATA_API, {
            'action': 'query', 'list': 'search', 'format': 'json', 'srlimit': 1,
            'srsearch': 'haswbstatement:%s=%d' % (prop, int(value)),
        })
        hits = (response.get('query') or {}).get('search') or []
        if hits:
            qid = hits[0].get('title')
            break
    if not qid:
        return None

    response = net.get_json(config.WIKIDATA_API, {
        'action': 'wbgetentities', 'ids': qid, 'format': 'json', 'languages': 'en',
        'props': 'labels|descriptions|claims|sitelinks', 'sitefilter': 'enwiki',
    })
    entity = (response.get('entities') or {}).get(qid)
    if not entity:
        return None

    imos = [str(value) for value in wd_values(entity, 'P458')]
    mmsis = [str(value) for value in wd_values(entity, 'P587')]
    if (imo and str(imo) not in imos) and (mmsi and str(mmsi) not in mmsis):
        return None       # the search hit did not actually carry our identifier

    item_props = {'P176': 'builder', 'P137': 'operator', 'P127': 'owner',
                  'P504': 'home_port', 'P289': 'vessel_class'}
    item_ids = {}
    for prop in item_props:
        item_ids[prop] = [value['id'] for value in wd_values(entity, prop)
                          if isinstance(value, dict) and 'id' in value]
    all_ids = sorted(set(item for ids in item_ids.values() for item in ids))
    labels = {}
    if all_ids:
        try:
            response = net.get_json(config.WIKIDATA_API, {
                'action': 'wbgetentities', 'ids': '|'.join(all_ids[:50]), 'format': 'json',
                'props': 'labels', 'languages': 'en',
            })
            labels = dict((qid, ((entry.get('labels') or {}).get('en') or {}).get('value'))
                          for qid, entry in (response.get('entities') or {}).items())
        except net.RateLimited:
            raise
        except Exception:
            pass          # labels are a nice-to-have

    result = {
        'qid': qid,
        'url': 'https://www.wikidata.org/wiki/%s' % qid,
        'label': ((entity.get('labels') or {}).get('en') or {}).get('value'),
        'description': ((entity.get('descriptions') or {}).get('en') or {}).get('value'),
        'imo': _integer(imos[0]) if imos else None,
        'mmsi': mmsis,
        'call_sign': next(iter(wd_values(entity, 'P2317')), None),
        'built_year': None,
        'length_m': wd_quantity(wd_values(entity, 'P2043'), metres_only=True),
        'beam_m': wd_quantity(wd_values(entity, 'P2049'), metres_only=True),
        'gross_tonnage': wd_quantity(wd_values(entity, 'P1093')),
    }
    for value in wd_values(entity, 'P571'):
        try:
            result['built_year'] = int(value['time'][1:5])
            break
        except (KeyError, TypeError, ValueError):
            continue
    for prop, name in item_props.items():
        names = [labels.get(item) or item for item in item_ids[prop]]
        result[name] = names[0] if len(names) == 1 else (names or None)

    images = [value for value in wd_values(entity, 'P18') if isinstance(value, str)]
    result['images'] = [{'title': name, 'url': commons_file_url(name),
                         'thumb': commons_file_url(name, 800),
                         'page': commons_page_url(name)} for name in images]
    title = ((entity.get('sitelinks') or {}).get('enwiki') or {}).get('title')
    result['article'] = ('https://en.wikipedia.org/wiki/'
                         + urllib.parse.quote(title.replace(' ', '_'))) if title else None
    return result


IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png')


def fetch_commons(imo):
    """Blocking. Photographs on Wikimedia Commons that mention the IMO number."""
    if not imo:
        return []
    response = net.get_json(config.COMMONS_API, {
        'action': 'query', 'list': 'search', 'format': 'json', 'srnamespace': 6,
        'srlimit': 6, 'srsearch': '"IMO %d"' % int(imo),
    })
    photos = []
    for hit in (response.get('query') or {}).get('search') or []:
        title = hit.get('title') or ''
        if not title.lower().endswith(IMAGE_EXTENSIONS):
            continue
        filename = title.split(':', 1)[-1]
        photos.append({'title': filename, 'url': commons_file_url(filename),
                       'thumb': commons_file_url(filename, 800),
                       'page': commons_page_url(title)})
    return photos


def merge_profile(wikidata, commons):
    """One JSON-friendly profile, or None when neither source found anything."""
    if not wikidata and not commons:
        return None
    photos = []
    seen = set()

    def add(photo):
        url = photo.get('url')
        if url and url not in seen:
            seen.add(url)
            photos.append(photo)

    if wikidata:
        for photo in wikidata.get('images') or []:
            add(photo)
    for photo in commons or []:
        add(photo)
    return {
        'name': (wikidata or {}).get('label'),
        'description': (wikidata or {}).get('description'),
        'built_year': (wikidata or {}).get('built_year'),
        'length_m': (wikidata or {}).get('length_m'),
        'beam_m': (wikidata or {}).get('beam_m'),
        'gross_tonnage': (wikidata or {}).get('gross_tonnage'),
        'builder': (wikidata or {}).get('builder'),
        'owner': (wikidata or {}).get('owner'),
        'operator': (wikidata or {}).get('operator'),
        'home_port': (wikidata or {}).get('home_port'),
        'vessel_class': (wikidata or {}).get('vessel_class'),
        'article': (wikidata or {}).get('article'),
        'qid': (wikidata or {}).get('qid'),
        'url': (wikidata or {}).get('url'),
        'photos': photos,
        'sources': {'wikidata': bool(wikidata), 'commons': len(commons or [])},
    }


def signature(imo=None, call_sign=None, mmsi=None):
    """What a cached profile was built from. A new IMO or call sign means a new lookup."""
    return 'imo:%s|cs:%s|mmsi:%s' % (imo or '', call_sign or '', mmsi or '')


def ship_signature(ship):
    return signature(ship.get('imo'), ship.get('call_sign'), ship.get('mmsi'))


def valid_mmsi(mmsi):
    try:
        return len(str(int(mmsi))) == 9
    except (TypeError, ValueError):
        return False


class Enricher(threading.Thread):
    """One lookup worker. Ships are queued by the AIS thread and the database answers repeats."""

    def __init__(self, store, enabled=True, debug=None, clock=time.time,
                 wikidata_fetcher=fetch_wikidata, commons_fetcher=fetch_commons,
                 gap=config.LOOKUP_GAP):
        threading.Thread.__init__(self, name='shiptracker-enrich')
        self.daemon = True
        self.store = store
        self.enabled = enabled
        self.debug = debug
        self.clock = clock
        self.wikidata_fetcher = wikidata_fetcher
        self.commons_fetcher = commons_fetcher
        self.gap = gap
        self.jobs = queue.Queue()
        self._queued = set()
        self._lock = threading.RLock()
        self._halt = threading.Event()
        self._retry_at = {}
        self._fails = {}
        self._results = {}
        self.last_error = None
        self.lookups = 0

    # ------------------------------------------------------------------ queue
    def enqueue(self, ship):
        """Queue a ship when its cached profile is missing, stale or built from other IDs."""
        if not self.enabled:
            return False
        mmsi = ship.get('mmsi')
        if not valid_mmsi(mmsi):
            return False
        signature_value = ship_signature(ship)
        if self.store.profile_is_fresh(mmsi, signature_value, self.clock()):
            row = self.store.get_profile(mmsi)
            with self._lock:
                self._results[mmsi] = row['data'] if row else None
            return False
        now = self.clock()
        with self._lock:
            if mmsi in self._queued or now < self._retry_at.get(mmsi, 0):
                return False
            self._queued.add(mmsi)
        self.jobs.put({'mmsi': mmsi, 'imo': ship.get('imo'),
                       'call_sign': ship.get('call_sign'), 'name': ship.get('name'),
                       'signature': signature_value})
        return True

    def profile(self, mmsi):
        """The last merged profile for an MMSI, from memory or the database."""
        with self._lock:
            if mmsi in self._results:
                return self._results[mmsi]
        row = self.store.get_profile(mmsi)
        data = row['data'] if row else None
        with self._lock:
            self._results[mmsi] = data
        return data

    def pending(self):
        with self._lock:
            return len(self._queued)

    def stop(self):
        self._halt.set()

    def run(self):
        while not self._halt.is_set():
            try:
                job = self.jobs.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._process(job)
            finally:
                with self._lock:
                    self._queued.discard(job['mmsi'])
                self.jobs.task_done()

    # ------------------------------------------------------------------ work
    def _process(self, job):
        if self._halt.is_set():
            return
        imo, mmsi = job.get('imo'), job.get('mmsi')
        wikidata, commons = None, []
        try:
            if imo or mmsi:
                wikidata = self.wikidata_fetcher(imo, mmsi)
            if imo and not self._halt.is_set():
                if self._halt.wait(self.gap):
                    return
                commons = self.commons_fetcher(imo)
        except net.RateLimited as error:
            with self._lock:
                self._retry_at[mmsi] = self.clock() + error.wait
            self.last_error = 'Wikimedia rate limit'
            self._log('rate limited for %s, waiting %.0fs' % (mmsi, error.wait))
            return
        except Exception as error:
            fails = self._fails.get(mmsi, 0) + 1
            self._fails[mmsi] = fails
            delay = config.RETRY_SECONDS if fails < 3 else config.MAX_RETRY_SECONDS
            with self._lock:
                self._retry_at[mmsi] = self.clock() + delay
            self.last_error = str(error)
            self._log('lookup failed for %s %s: %s (attempt %d)'
                      % (mmsi, job.get('name') or '', error, fails))
            return

        profile = merge_profile(wikidata, commons)
        self.store.put_profile(mmsi, job['signature'], profile)
        with self._lock:
            self._results[mmsi] = profile
            self._fails.pop(mmsi, None)
            self._retry_at.pop(mmsi, None)
            self.lookups += 1
        if profile:
            self.last_error = None
            self._log('enriched %s %s: wikidata=%s photos=%d'
                      % (mmsi, job.get('name') or '?', profile['sources']['wikidata'],
                         len(profile.get('photos') or [])))
        else:
            self._log('no details found for %s %s' % (mmsi, job.get('name') or '?'))

    def _log(self, message):
        if self.debug:
            self.debug(message)

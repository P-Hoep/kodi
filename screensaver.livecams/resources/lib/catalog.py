"""The camera catalogue: download streams.geojson (and sources.json beside it), keep a slim
index in the add-on's profile folder, and parse it into Camera objects. No Kodi imports.

Activation never waits on the network when an index is cached: the session loads the
cache and refreshes it in the background once it is older than the refresh interval, using
the stored ETag. A new download replaces the cache only if it parses and has more than
MIN_FEATURES features.
"""

import calendar
import hashlib
import json
import os
import re
import time
import unicodedata

from . import net

INDEX = 'catalog.json'
INDEX_VERSION = 1
MIN_FEATURES = 100
PLAYABLE_TYPES = ('hls', 'youtube')       # html_page needs page scraping: never in v1
# Licence types from sources.json whose terms rule out showing the feed. None of the
# dataset's sources use one today; the check is here so a future one is dropped on refresh.
BLOCKED_LICENSES = frozenset(['no_embed', 'no_embedding', 'no_redistribution', 'proprietary', 'restricted',
                              'forbidden', 'prohibited'])
BLOCKED_SOURCES = frozenset()

QUALITY = ('premium', 'high', 'standard', 'low')
FIELDS = ['id', 'title', 'place', 'url', 'kind', 'status', 'env', 'scene', 'quality', 'w', 'h', 'cc', 'lat',
          'lon', 'cq', 'family', 'verified']


class Camera(object):
    __slots__ = FIELDS

    def __init__(self, *values):
        for name, value in zip(FIELDS, values):
            setattr(self, name, value)

    def row(self):
        return [getattr(self, name) for name in FIELDS]

    @property
    def height(self):
        """The shorter side in pixels ('1080' for 1920x1080), or 0 when unknown."""
        return min(self.w, self.h) if self.w and self.h else 0

    def __repr__(self):
        return '<Camera %s %s>' % (self.id, self.title)


def camera_id(url):
    return hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]


# ---------------------------------------------------------------- names

COUNTRIES = {
    'AE': 'United Arab Emirates', 'AL': 'Albania', 'AR': 'Argentina', 'AT': 'Austria', 'AU': 'Australia',
    'AW': 'Aruba', 'BA': 'Bosnia and Herzegovina', 'BB': 'Barbados', 'BE': 'Belgium', 'BG': 'Bulgaria',
    'BL': 'Saint Barthélemy', 'BM': 'Bermuda', 'BO': 'Bolivia', 'BQ': 'Caribbean Netherlands', 'BR': 'Brazil',
    'BZ': 'Belize', 'CA': 'Canada', 'CH': 'Switzerland', 'CL': 'Chile', 'CN': 'China', 'CR': 'Costa Rica',
    'CV': 'Cape Verde', 'CW': 'Curaçao', 'CY': 'Cyprus', 'CZ': 'Czechia', 'DE': 'Germany', 'DK': 'Denmark',
    'DO': 'Dominican Republic', 'EC': 'Ecuador', 'EE': 'Estonia', 'EG': 'Egypt', 'ES': 'Spain', 'FI': 'Finland',
    'FO': 'Faroe Islands', 'FR': 'France', 'GB': 'United Kingdom', 'GD': 'Grenada', 'GP': 'Guadeloupe',
    'GR': 'Greece', 'GT': 'Guatemala', 'GY': 'Guyana', 'HK': 'Hong Kong', 'HR': 'Croatia', 'HU': 'Hungary',
    'ID': 'Indonesia', 'IE': 'Ireland', 'IL': 'Israel', 'IN': 'India', 'IR': 'Iran', 'IS': 'Iceland',
    'IT': 'Italy', 'JM': 'Jamaica', 'JO': 'Jordan', 'JP': 'Japan', 'KE': 'Kenya', 'KG': 'Kyrgyzstan',
    'KR': 'South Korea', 'KY': 'Cayman Islands', 'KZ': 'Kazakhstan', 'LK': 'Sri Lanka', 'LT': 'Lithuania',
    'LU': 'Luxembourg', 'LV': 'Latvia', 'MA': 'Morocco', 'ME': 'Montenegro', 'MK': 'North Macedonia',
    'MQ': 'Martinique', 'MT': 'Malta', 'MV': 'Maldives', 'MX': 'Mexico', 'MY': 'Malaysia', 'NA': 'Namibia',
    'NL': 'Netherlands', 'NO': 'Norway', 'NZ': 'New Zealand', 'PE': 'Peru', 'PH': 'Philippines', 'PL': 'Poland',
    'PR': 'Puerto Rico', 'PT': 'Portugal', 'QA': 'Qatar', 'RO': 'Romania', 'RS': 'Serbia', 'RU': 'Russia',
    'SC': 'Seychelles', 'SE': 'Sweden', 'SG': 'Singapore', 'SI': 'Slovenia', 'SK': 'Slovakia', 'SM': 'San Marino',
    'SX': 'Sint Maarten', 'TC': 'Turks and Caicos', 'TH': 'Thailand', 'TR': 'Türkiye', 'TT': 'Trinidad and Tobago',
    'TW': 'Taiwan', 'TZ': 'Tanzania', 'UA': 'Ukraine', 'US': 'United States', 'UY': 'Uruguay', 'VE': 'Venezuela',
    'VG': 'British Virgin Islands', 'VI': 'US Virgin Islands', 'VN': 'Vietnam', 'XK': 'Kosovo',
    'ZA': 'South Africa', 'ZM': 'Zambia',
}

SOURCE_NAMES = {
    'webcamera_pl': 'WebCamera.pl', 'beachcam_meo': 'MEO Beachcam', 'balticlivecam': 'Balticlivecam',
    'worldviewstream': 'WorldViewStream', 'worldviewstream-direct-hls': 'WorldViewStream', 'camguide': 'CamGuide',
    'resortcams': 'ResortCams', 'opencctv': 'OpenCCTV', 'manual': 'Live-Environment-Streams',
    'osm_webcam_pages': 'OpenStreetMap webcams', 'wral': 'WRAL',
    'youtube': 'YouTube', 'skyline-youtube': 'SkylineWebcams on YouTube', 'brownrice': 'Brown Rice Internet',
}

# Boilerplate that sources put in camera names ("... kamera na żywo", "Webcam 🎦").
NOISE = [r'online ponad \d+ kamer hd', r'kamerki z turystycznych miejsc w polsce\.?', r'webcamera\.pl',
         r'zobacz live', r'kamera na żywo', r'kamery na żywo', r'na żywo', r'\bkamer[a-zę]*\b', r'\bzobacz\b',
         r'\blive ?stream\b', r'\blive ?cams?\b', r'\bwebcams?\b', r'\blive\b', r'\bonline\b', r'\bstream\b',
         r'\bhd\b', r'\b4k\b', r'\bptz\b']
NOISE_RE = re.compile('|'.join(NOISE), re.IGNORECASE | re.UNICODE)
EDGES = ' \t-–—,.|:;/·•'


def _strip_symbols(text):
    # Emoji, pictographs, variation selectors and joiners; keep letters, digits and punctuation.
    return ''.join(ch for ch in text if unicodedata.category(ch) not in ('So', 'Cs', 'Co')
                   and not 0xFE00 <= ord(ch) <= 0xFE0F and ch != '\u200d')


def _tidy(text):
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\(\s*\)', '', text)
    text = re.sub(r'\s*([-–—|,])\s*(?:[-–—|,]\s*)+', r' \1 ', text)   # "a - - b" -> "a - b"
    text = re.sub(r'\s+([,.])', r'\1', text)
    return text.strip(EDGES).strip()


def clean_name(name, display_name, cc):
    """(title, place) for the overlay: the camera's own name without site boilerplate, and the
    town or region when the name carries one ("PT - Faro - Albufeira - Praia" style)."""
    raw = unicodedata.normalize('NFC', _strip_symbols(name or display_name or ''))
    place = ''
    match = re.match(r'^([A-Z]{2}) - (.+)$', raw)
    if match:
        parts = [p.strip() for p in match.group(2).split(' - ') if p.strip()]
        raw = parts[-1]
        for candidate in reversed(parts[:-1]):
            if candidate.lower() not in raw.lower():
                place = candidate
                break
    country = COUNTRIES.get((cc or '').upper(), '')
    title = NOISE_RE.sub(' ', raw)
    if country:
        title = re.sub(r'[\s,\-–—]+%s\s*$' % re.escape(country), '', title, flags=re.IGNORECASE)
    title = _tidy(title)
    if len(title) < 3:
        title = _tidy(re.sub(r',\s*%s$' % re.escape(country), '', display_name or '')) if country else ''
        title = title or _tidy(raw) or (name or '').strip()
    if len(title) > 70:
        title = title[:67].rstrip(EDGES) + '...'
    return title, _tidy(place)


def source_name(family, sources=None):
    """A readable name for a source_family: 'camguide-ipcamlive' -> 'CamGuide'."""
    full = ((sources or {}).get(family) or {}).get('name')
    if family in SOURCE_NAMES:
        return SOURCE_NAMES[family]
    if full and full != family:
        return full
    for key in sorted(SOURCE_NAMES, key=len, reverse=True):
        if family.startswith(key + '-') or family.startswith(key + '_'):
            return SOURCE_NAMES[key]
    if family.startswith('ipcamlive'):
        return 'IPCamLive'
    return ' '.join(w.capitalize() for w in re.split(r'[_\-]+', family) if w)


def country_name(cc):
    return COUNTRIES.get((cc or '').upper(), '')


# ---------------------------------------------------------------- parsing

def _resolution(text):
    match = re.match(r'^\s*(\d+)\s*[xX×]\s*(\d+)\s*$', text or '')
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def _epoch(text):
    if not text:
        return 0
    try:
        return calendar.timegm(time.strptime(text[:19], '%Y-%m-%dT%H:%M:%S'))
    except (ValueError, OverflowError):
        return 0


def parse_sources(data):
    """sources.json -> {family: {'name': full name, 'license': licence type}}."""
    out = {}
    for family, info in (data or {}).items():
        if isinstance(info, dict):
            out[family] = {'name': info.get('full_name') or family, 'license': info.get('license_type') or 'unknown'}
    return out


def parse(geojson, sources=None):
    """Parsed streams.geojson (a dict) -> (cameras, feature count). Keeps only cameras v1 can
    play: HLS or YouTube links that need no browser or token, from sources whose licence
    does not rule it out."""
    features = geojson.get('features') if isinstance(geojson, dict) else None
    if not isinstance(features, list):
        raise ValueError('no features')
    cams = []
    seen = set()
    for feature in features:
        try:
            p = feature.get('properties') or {}
            kind = p.get('url_type')
            url = (p.get('url') or '').strip()
            if kind not in PLAYABLE_TYPES or p.get('source_url_requires') or not url.startswith(('http://', 'https://')):
                continue
            family = p.get('source_family') or 'unknown'
            licence = ((sources or {}).get(family) or {}).get('license', '')
            if family in BLOCKED_SOURCES or licence in BLOCKED_LICENSES:
                continue
            cid = camera_id(url)
            if cid in seen:
                continue
            seen.add(cid)
            coords = (feature.get('geometry') or {}).get('coordinates') or [None, None]
            lon, lat = (float(coords[0]), float(coords[1])) if coords[0] is not None else (None, None)
            cc = (p.get('country_code') or '').upper()
            title, place = clean_name(p.get('name'), p.get('display_name'), cc)
            w, h = _resolution(p.get('resolution'))
            quality = p.get('quality_tier') if p.get('quality_tier') in QUALITY else 'standard'
            cams.append(Camera(cid, title, place, url, kind, p.get('status') or 'unverified',
                               p.get('environment') or '', p.get('scene_type') or '', quality, w, h, cc, lat, lon,
                               p.get('coordinates_quality') or '', family, _epoch(p.get('last_verified'))))
        except (TypeError, ValueError, AttributeError, IndexError):
            continue
    return cams, len(features)


# ---------------------------------------------------------------- cache

class Catalog(object):
    def __init__(self, profile, log=lambda msg: None):
        self.path = os.path.join(profile, INDEX)
        self.log = log
        self.cams = []
        self.sources = {}
        self.fetched = 0
        self.etag = ''
        self.url = ''
        self.features = 0

    def load(self):
        """Read the cached index. False if there is none or it is unreadable."""
        try:
            with open(self.path, 'r') as handle:
                data = json.load(handle)
            if data.get('v') != INDEX_VERSION:
                return False
            fields = data['fields']
            order = [fields.index(name) for name in FIELDS]
            self.cams = [Camera(*[row[i] for i in order]) for row in data['cams']]
            self.sources = data.get('sources') or {}
            self.fetched = data.get('fetched', 0)
            self.etag = data.get('etag', '')
            self.url = data.get('url', '')
            self.features = data.get('features', 0)
            return bool(self.cams)
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def save(self):
        data = {'v': INDEX_VERSION, 'fetched': self.fetched, 'etag': self.etag, 'url': self.url,
                'features': self.features, 'sources': self.sources, 'fields': FIELDS,
                'cams': [c.row() for c in self.cams]}
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as handle:
            json.dump(data, handle, separators=(',', ':'), ensure_ascii=False)
        os.replace(tmp, self.path)

    def stale(self, url, refresh_days, now=None):
        now = time.time() if now is None else now
        return not self.cams or url != self.url or now - self.fetched > refresh_days * 86400

    def refresh(self, url, now=None, fetch=net.fetch):
        """Download the catalogue if it changed. Returns 'updated' or 'unchanged'; raises
        net.HttpError or ValueError (and keeps the old index) when the download is bad."""
        now = time.time() if now is None else now
        headers = {'If-None-Match': self.etag} if self.etag and url == self.url and self.cams else {}
        response = fetch(url, timeout=30, headers=headers)
        if response.status == 304:
            self.fetched = now
            self.save()
            return 'unchanged'
        try:
            geojson = json.loads(response.body.decode('utf-8'))
        except ValueError as error:
            raise ValueError('catalogue is not valid JSON (%s)' % error)
        sources = self.sources
        try:
            sources = parse_sources(json.loads(fetch(sources_url(url), timeout=15).body.decode('utf-8')))
        except Exception as error:
            self.log('sources.json: %s (keeping the previous licence list)' % error)
        cams, features = parse(geojson, sources)
        if features <= MIN_FEATURES or not cams:
            raise ValueError('catalogue has only %d features' % features)
        self.cams, self.sources, self.features = cams, sources, features
        self.fetched, self.url = now, url
        self.etag = response.headers.get('ETag', '') if response.headers else ''
        self.save()
        return 'updated'

    def by_id(self):
        return dict((c.id, c) for c in self.cams)


def sources_url(catalog_url):
    return catalog_url.rsplit('/', 1)[0] + '/sources.json'

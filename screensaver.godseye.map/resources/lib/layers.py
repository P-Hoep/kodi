"""Live data layers. Each fetches public feeds and returns map Items. No Kodi imports."""

import math
import os
import time
from datetime import datetime

from . import gtfs_rt, net
from .geo import clamp, haversine_km

# Colors are Kodi ARGB hex strings.
BLUE = 'FF4FC3F7'
GREY = 'FFB0BEC5'
ORANGE = 'FFFFA726'
RED = 'FFFF5252'
GREEN = 'FF69F0AE'
YELLOW = 'FFFFD600'
PURPLE = 'FFE040FB'


class Item(object):
    """One thing on the map."""

    __slots__ = ('uid', 'layer', 'lat', 'lon', 'label', 'title', 'details', 'icon',
                 'color', 'size', 'heading', 'priority', 'media', 'speed', 'at')

    def __init__(self, uid, layer, lat, lon, title, icon, color, size=32, label='',
                 details=None, heading=None, priority=0, media=None, speed=None, at=None):
        self.uid = uid
        self.layer = layer
        self.lat = lat
        self.lon = lon
        self.title = title
        self.label = label
        self.details = details or []
        self.icon = icon
        self.color = color
        self.size = size
        self.heading = heading
        self.priority = priority
        self.media = media
        # Dead reckoning: ground speed (m/s) along `heading` from the fix at epoch `at`.
        self.speed = speed
        self.at = at

    def position_at(self, now):
        """Where the item is expected to be at `now`, projected along its track."""
        if not self.speed or self.heading is None or self.at is None:
            return self.lat, self.lon
        dt = min(max(0.0, now - self.at), MAX_EXTRAPOLATION)
        distance = self.speed * dt
        h = math.radians(self.heading)
        dlat = distance * math.cos(h) / EARTH_RADIUS_M
        dlon = distance * math.sin(h) / (EARTH_RADIUS_M * max(0.01, math.cos(math.radians(self.lat))))
        return self.lat + math.degrees(dlat), self.lon + math.degrees(dlon)


EARTH_RADIUS_M = 6371008.8
# Stop projecting a fix older than this: a plane that stopped reporting may have turned.
MAX_EXTRAPOLATION = 60.0
KT_TO_MS = 0.514444


def _num(value, default=None):
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_int(value):
    return '{:,}'.format(int(round(value)))


def _age(seconds):
    if seconds < 90:
        return '%d s ago' % seconds
    if seconds < 5400:
        return '%d min ago' % (seconds // 60)
    if seconds < 172800:
        return '%.1f h ago' % (seconds / 3600.0)
    return '%d days ago' % (seconds // 86400)


class Layer(object):
    id = ''
    name = ''
    attribution = ''
    interval = 60          # seconds between refreshes
    view_dependent = False  # refetch when the view moves
    min_zoom = 0

    def __init__(self, settings):
        self.settings = settings

    def fetch(self, view):
        raise NotImplementedError


# ---------------------------------------------------------------- aircraft

EMERGENCY_SQUAWKS = {'7500': 'HIJACK', '7600': 'RADIO FAILURE', '7700': 'EMERGENCY'}


def _aircraft_item(layer_id, hex_id, lat, lon, callsign, reg, actype, alt_ft, on_ground,
                   speed_kt, track, squawk, military, source, at=None):
    callsign = (callsign or '').strip()
    name = callsign or reg or hex_id.upper()
    if squawk in EMERGENCY_SQUAWKS:
        color = RED
    elif military:
        color = ORANGE
    elif on_ground:
        color = GREY
    else:
        color = BLUE
    details = []
    if callsign:
        details.append('Callsign: %s' % callsign)
    if reg:
        details.append('Registration: %s' % reg)
    if actype:
        details.append('Type: %s' % actype)
    if on_ground:
        details.append('Altitude: on ground')
    elif alt_ft is not None:
        details.append('Altitude: %s ft' % _fmt_int(alt_ft))
    if speed_kt is not None:
        details.append('Ground speed: %s kt' % _fmt_int(speed_kt))
    if track is not None:
        details.append('Track: %d°' % int(round(track)))
    if squawk:
        details.append('Squawk: %s%s' % (squawk, (' ' + EMERGENCY_SQUAWKS[squawk]) if squawk in EMERGENCY_SQUAWKS else ''))
    if military:
        details.append('Flagged military')
    details.append('ICAO: %s' % hex_id.upper())
    details.append('Source: %s' % source)
    label = name
    if alt_ft is not None and not on_ground and alt_ft >= 100:
        if alt_ft >= 18000:
            label = '%s  FL%03d' % (name, int(round(alt_ft / 100.0)))
        else:
            label = '%s  %s ft' % (name, _fmt_int(alt_ft))
    return Item('ac:' + hex_id.lower(), layer_id, lat, lon, name, 'plane', color, size=34,
                label=label, details=details, heading=track,
                priority=3 if color == RED else (2 if military else 1),
                speed=None if on_ground or speed_kt is None else speed_kt * KT_TO_MS, at=at)


def parse_adsblol(data, layer_id, source='adsb.lol'):
    now = _num(data.get('now'), time.time() * 1000)
    if now > 1e11:  # adsb.lol reports milliseconds
        now /= 1000.0
    items = []
    for ac in data.get('ac') or []:
        lat, lon = _num(ac.get('lat')), _num(ac.get('lon'))
        hex_id = ac.get('hex') or ''
        if lat is None or lon is None or not hex_id:
            continue
        alt = ac.get('alt_baro')
        on_ground = alt == 'ground'
        alt_ft = None if on_ground else _num(alt, _num(ac.get('alt_geom')))
        items.append(_aircraft_item(
            layer_id, hex_id.lstrip('~'), lat, lon, ac.get('flight'), ac.get('r'), ac.get('t'),
            alt_ft, on_ground, _num(ac.get('gs')), _num(ac.get('track'), _num(ac.get('true_heading'))),
            ac.get('squawk'), bool((ac.get('dbFlags') or 0) & 1), source,
            at=now - (_num(ac.get('seen_pos'), 0) or 0)))
    return items


def parse_opensky(data, layer_id):
    items = []
    for s in data.get('states') or []:
        if len(s) < 15 or s[5] is None or s[6] is None:
            continue
        alt_m = s[7] if s[7] is not None else s[13]
        items.append(_aircraft_item(
            layer_id, s[0], s[6], s[5], s[1], None, None,
            None if alt_m is None else alt_m * 3.28084, bool(s[8]),
            None if s[9] is None else s[9] * 1.943844, s[10], s[14], False, 'OpenSky Network',
            at=s[3] or s[4]))
    return items


class FlightsLayer(Layer):
    id = 'flights'
    name = 'Flights'
    attribution = 'adsb.lol (ODbL) / OpenSky Network'
    interval = 30
    view_dependent = True
    min_zoom = 4

    def fetch(self, view):
        # Fetch well beyond the screen edge so aircraft are already known, and projected,
        # when they fly in, instead of popping up mid-screen on the next refresh.
        reach_km = max(2 * view.radius_km(), view.radius_km() + 30)
        radius_nm = int(clamp(reach_km / 1.852, 10, 250))
        try:
            data = net.fetch_json('https://api.adsb.lol/v2/lat/%.3f/lon/%.3f/dist/%d'
                                  % (view.lat, view.lon, radius_nm), timeout=15)
            return parse_adsblol(data, self.id)
        except net.HttpError:
            south, west, north, east = view.bbox()
            pad = (reach_km - view.radius_km()) / 111.0
            south, north = max(-90.0, south - pad), min(90.0, north + pad)
            west, east = west - pad, east + pad
            if west > east or west < -180 or east > 180:
                west, east = -180.0, 180.0
            data = net.fetch_json(
                'https://opensky-network.org/api/states/all?lamin=%.3f&lomin=%.3f&lamax=%.3f&lomax=%.3f'
                % (south, west, north, east), timeout=20)
            return parse_opensky(data, self.id)


class MilitaryLayer(Layer):
    id = 'military'
    name = 'Military aircraft'
    attribution = 'adsb.lol (ODbL)'
    interval = 60

    def fetch(self, view):
        items = parse_adsblol(net.fetch_json('https://api.adsb.lol/v2/mil', timeout=20), self.id)
        for item in items:
            item.priority = max(item.priority, 2)
            if item.color != RED:
                item.color = ORANGE
        return items


# ---------------------------------------------------------------- earthquakes

QUAKE_FEEDS = ['all_day', '2.5_week', '4.5_month']
QUAKE_MIN_MAG = [0.0, 1.0, 2.5, 4.5]


def parse_usgs(data, layer_id, min_mag=0.0, now=None):
    now = now or time.time()
    items = []
    for feature in data.get('features') or []:
        props = feature.get('properties') or {}
        coords = (feature.get('geometry') or {}).get('coordinates') or []
        mag = _num(props.get('mag'))
        if len(coords) < 2 or mag is None or mag < min_mag:
            continue
        when = (_num(props.get('time'), 0) or 0) / 1000.0
        age = max(0, now - when)
        color = RED if age < 3600 else (ORANGE if age < 86400 else YELLOW)
        details = ['Magnitude: %.1f %s' % (mag, props.get('magType') or ''),
                   'Depth: %.1f km' % (_num(coords[2], 0) if len(coords) > 2 else 0),
                   'Time: %s UTC (%s)' % (datetime.utcfromtimestamp(when).strftime('%Y-%m-%d %H:%M'), _age(age))]
        if props.get('tsunami'):
            details.append('Tsunami flag set')
        if props.get('alert'):
            details.append('PAGER alert: %s' % props['alert'])
        details.append('Source: USGS')
        place = props.get('place') or 'Earthquake'
        items.append(Item('eq:' + str(feature.get('id')), layer_id, coords[1], coords[0],
                          'M%.1f %s' % (mag, place), 'circle', color,
                          size=int(clamp(14 + mag * 8, 14, 72)),
                          label=('M%.1f' % mag) if mag >= 2.5 else '',
                          details=details, priority=2 if mag >= 4.5 else 0))
    return items


class QuakesLayer(Layer):
    id = 'quakes'
    name = 'Earthquakes'
    attribution = 'USGS'
    interval = 300

    def fetch(self, view):
        feed = QUAKE_FEEDS[clamp(self.settings.get('quake_period', 0), 0, len(QUAKE_FEEDS) - 1)]
        min_mag = QUAKE_MIN_MAG[clamp(self.settings.get('quake_min_mag', 1), 0, len(QUAKE_MIN_MAG) - 1)]
        data = net.fetch_json('https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/%s.geojson' % feed)
        return parse_usgs(data, self.id, min_mag)


# ---------------------------------------------------------------- cyclones

CYCLONE_CLASSES = {
    'TD': 'Tropical Depression', 'TS': 'Tropical Storm', 'HU': 'Hurricane',
    'MH': 'Major Hurricane', 'STD': 'Subtropical Depression', 'STS': 'Subtropical Storm',
    'PTC': 'Post-tropical / Potential TC', 'TY': 'Typhoon', 'PC': 'Potential Cyclone',
}


def parse_nhc(data, layer_id):
    items = []
    for storm in data.get('activeStorms') or []:
        lat, lon = _num(storm.get('latitudeNumeric')), _num(storm.get('longitudeNumeric'))
        if lat is None or lon is None:
            continue
        cls = CYCLONE_CLASSES.get(storm.get('classification'), storm.get('classification') or 'Storm')
        name = storm.get('name') or storm.get('id') or 'Storm'
        details = ['Class: %s' % cls]
        if storm.get('intensity'):
            details.append('Max wind: %s kt' % storm['intensity'])
        if storm.get('pressure'):
            details.append('Pressure: %s mb' % storm['pressure'])
        if storm.get('movementSpeed') is not None:
            details.append('Moving: %s° at %s mph' % (storm.get('movementDir'), storm.get('movementSpeed')))
        if storm.get('lastUpdate'):
            details.append('Updated: %s' % storm['lastUpdate'].replace('T', ' ')[:16] + ' UTC')
        details.append('Source: NOAA NHC / CPHC')
        items.append(Item('tc:' + str(storm.get('id')), layer_id, lat, lon, '%s %s' % (cls, name),
                          'storm', PURPLE, size=56, label=name, details=details, priority=3))
    return items


class CyclonesLayer(Layer):
    id = 'cyclones'
    name = 'Tropical cyclones'
    attribution = 'NOAA NHC'
    interval = 900

    def fetch(self, view):
        return parse_nhc(net.fetch_json('https://www.nhc.noaa.gov/CurrentStorms.json'), self.id)


# ---------------------------------------------------------------- public transit

# (id, name, lat, lon, radius_km, url, headers, attribution) — the keyless GTFS-realtime
# vehicle feeds God's Eye View uses. A feed loads when its service area reaches the view.
TRANSIT_FEEDS = [
    ('mbta', 'MBTA', 42.3601, -71.0589, 70, 'https://cdn.mbta.com/realtime/VehiclePositions.pb',
     {}, 'MBTA / MassDOT'),
    ('capmetro', 'CapMetro', 30.2672, -97.7431, 60,
     'https://data.texas.gov/download/eiei-9rpf/application%2Foctet-stream', {}, 'CapMetro'),
    ('metrotransit', 'Metro Transit', 44.9778, -93.265, 70,
     'https://svc.metrotransit.org/mtgtfs/vehiclepositions.pb', {}, 'Metro Transit'),
    ('hsl', 'HSL', 60.1699, 24.9384, 70, 'https://realtime.hsl.fi/realtime/vehicle-positions/v2/hsl',
     {}, 'HSL (CC BY 4.0)'),
    ('ovapi', 'OVapi', 52.2, 5.3, 220, 'https://gtfs.ovapi.nl/nl/vehiclePositions.pb', {}, 'OVapi'),
    ('entur', 'Entur', 64.0, 11.5, 720, 'https://api.entur.io/realtime/v1/gtfs-rt/vehicle-positions',
     {'ET-Client-Name': 'godseyemap-kodi'}, 'Entur (NLOD)'),
    ('translink', 'TransLink', -27.4698, 153.0251, 150,
     'https://gtfsrt.api.translink.com.au/api/realtime/seq/VehiclePositions', {}, 'TransLink (CC BY 4.0)'),
]
TRANSIT_COLOR = 'FFFFCA28'
TRANSIT_MAX_AGE = 600


def transit_feeds_for(view, custom_url=''):
    radius = view.radius_km()
    feeds = [f for f in TRANSIT_FEEDS
             if haversine_km(view.lat, view.lon, f[2], f[3]) < f[4] + radius]
    if custom_url:
        feeds.append(('custom', 'Custom feed', view.lat, view.lon, 0, custom_url, {}, 'Custom GTFS-RT feed'))
    return feeds


class TransitLayer(Layer):
    id = 'transit'
    name = 'Public transit vehicles'
    attribution = 'Transit agencies (GTFS-RT)'
    interval = 30
    view_dependent = True
    min_zoom = 8

    def fetch(self, view):
        feeds = transit_feeds_for(view, (self.settings.get('transit_custom_url') or '').strip())
        self.attribution = ', '.join(f[7] for f in feeds) or 'Transit agencies (GTFS-RT)'
        now = time.time()
        items, errors = [], []
        for fid, name, _lat, _lon, _r, url, headers, _attr in feeds:
            try:
                vehicles = gtfs_rt.vehicle_positions(net.fetch(url, timeout=20, headers=headers))
            except (net.HttpError, ValueError, IndexError) as error:
                errors.append('%s: %s' % (name, error))
                continue
            for v in vehicles:
                if v['timestamp'] and now - v['timestamp'] > TRANSIT_MAX_AGE:
                    continue
                route = v['route'] or ''
                short = route.split(':')[-1].split('_')[0] if route else ''
                details = ['Operator: %s' % name]
                if route:
                    details.append('Route: %s' % route)
                if v['label'] or v['id']:
                    details.append('Vehicle: %s' % (v['label'] or v['id']))
                items.append(Item('tr:%s:%s' % (fid, v['id'] or len(items)), self.id, v['lat'], v['lon'],
                                  '%s %s' % (name, short), 'bus', TRANSIT_COLOR, size=46,
                                  label=short[:8], details=details, heading=v['bearing']))
        if errors and not items:
            raise net.HttpError(errors[0])
        return items


# ---------------------------------------------------------------- satellites

# (CelesTrak group, label). Big groups refresh positions less often.
SATELLITE_GROUPS = [('stations', 'Space stations'), ('visual', '100 brightest'),
                    ('gps-ops', 'GPS'), ('weather', 'Weather satellites'), ('starlink', 'Starlink')]
TLE_TTL = 6 * 3600  # CelesTrak asks clients not to refetch a group more than every few hours


def _gmst(jd_ut1):
    """Greenwich mean sidereal time in radians (IAU-82)."""
    t = (jd_ut1 - 2451545.0) / 36525.0
    sec = 67310.54841 + (876600.0 * 3600 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t ** 3
    return math.radians((sec % 86400) / 240.0)


def teme_to_geodetic(r, jd, fr):
    """TEME position (km) at Julian date jd+fr -> (lat, lon, alt_km), WGS-84."""
    g = _gmst(jd + fr)
    x = r[0] * math.cos(g) + r[1] * math.sin(g)
    y = -r[0] * math.sin(g) + r[1] * math.cos(g)
    z = r[2]
    a, e2 = 6378.137, 0.00669437999014
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(4):
        n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        alt = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1 - e2 * n / (n + alt)))
    n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    alt = p / math.cos(lat) - n
    return math.degrees(lat), math.degrees(lon), alt


def parse_tle(text):
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    out = []
    for i in range(len(lines) - 2):
        if lines[i + 1].startswith('1 ') and lines[i + 2].startswith('2 ') and not lines[i].startswith(('1 ', '2 ')):
            out.append((lines[i].strip(), lines[i + 1], lines[i + 2]))
    return out


class SatellitesLayer(Layer):
    id = 'satellites'
    name = 'Satellites overhead'
    attribution = 'CelesTrak'
    interval = 5

    def __init__(self, settings):
        Layer.__init__(self, settings)
        self._group = None
        self._sats = []
        self._loaded_at = 0

    def _load(self, group):
        cache_dir = self.settings.get('_cache_dir')
        path = os.path.join(cache_dir, 'tle_%s.txt' % group) if cache_dir else None
        text = None
        if path and os.path.exists(path) and time.time() - os.path.getmtime(path) < TLE_TTL:
            with open(path) as handle:
                text = handle.read()
        if text is None:
            try:
                text = net.fetch('https://celestrak.org/NORAD/elements/gp.php?GROUP=%s&FORMAT=tle' % group,
                                 timeout=30).decode('utf-8', 'replace')
                if path:
                    with open(path, 'w') as handle:
                        handle.write(text)
            except net.HttpError:
                if path and os.path.exists(path):  # stale elements beat no satellites
                    with open(path) as handle:
                        text = handle.read()
                else:
                    raise
        from sgp4.api import Satrec
        sats = []
        for name, l1, l2 in parse_tle(text):
            try:
                sats.append((name, Satrec.twoline2rv(l1, l2)))
            except Exception:
                continue
        self._group, self._sats, self._loaded_at = group, sats, time.time()

    def fetch(self, view):
        from sgp4.api import jday
        index = int(clamp(self.settings.get('satellite_group', 0), 0, len(SATELLITE_GROUPS) - 1))
        group = SATELLITE_GROUPS[index][0]
        self.interval = 30 if group == 'starlink' else 5
        if group != self._group or time.time() - self._loaded_at > TLE_TTL:
            self._load(group)
        now = datetime.utcfromtimestamp(time.time())
        jd, fr = jday(now.year, now.month, now.day, now.hour, now.minute,
                      now.second + now.microsecond / 1e6)
        south, west, north, east = view.bbox()
        pad = 5.0
        items = []
        for name, sat in self._sats:
            err, r, _v = sat.sgp4(jd, fr)
            if err:
                continue
            lat, lon, alt = teme_to_geodetic(r, jd, fr)
            if not (south - pad <= lat <= north + pad):
                continue
            if west <= east and not (west - pad <= lon <= east + pad):
                continue
            iss = name.startswith('ISS')
            items.append(Item('sat:%s' % sat.satnum, self.id, lat, lon, name, 'satellite',
                              'FFFFD740' if iss else 'FF80DEEA', size=48 if iss else 38,
                              label=name.split('(')[0].strip()[:18],
                              details=['Altitude: %s km' % _fmt_int(alt), 'NORAD: %s' % sat.satnum,
                                       'Source: CelesTrak'],
                              priority=2 if iss else 1))
        return items


LAYER_CLASSES = [FlightsLayer, MilitaryLayer, QuakesLayer, CyclonesLayer, TransitLayer, SatellitesLayer]


# ---------------------------------------------------------------- place search

def search_places(query, near=None, limit=10):
    """Photon (komoot) keyless geocoder: [(label, lat, lon)]."""
    url = 'https://photon.komoot.io/api/?' + net.urlencode({'q': query, 'limit': limit})
    if near:
        url += '&lat=%.4f&lon=%.4f' % near
    out = []
    for feature in net.fetch_json(url).get('features') or []:
        props = feature.get('properties') or {}
        coords = (feature.get('geometry') or {}).get('coordinates') or []
        if len(coords) < 2:
            continue
        parts = [props.get('name'), props.get('city'), props.get('state'), props.get('country')]
        seen = []
        for part in parts:
            if part and part not in seen:
                seen.append(part)
        out.append((', '.join(seen) or query, coords[1], coords[0]))
    return out

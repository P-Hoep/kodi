"""Where the data comes from, and the on-disk cache that keeps it through outages.
No Kodi imports.

Each Feed downloads one resource, keeps the last good copy on disk with the time it was
fetched, and retries failures with a growing delay (2 minutes doubling up to an hour), so
a dead network is never hammered and the map keeps showing the last good data."""

import calendar
import hashlib
import json
import math
import os
import time

from . import flights, net, overlays, raster

GIBS = ('https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap'
        '&VERSION=1.1.1&SRS=EPSG:4326&BBOX=-180,-90,180,90&FORMAT=image/png&TRANSPARENT=TRUE'
        '&LAYERS={layer}&WIDTH={w}&HEIGHT={h}')
NOWCOAST_IR = ('https://nowcoast.noaa.gov/geoserver/observations/satellite/ows?service=WMS&version=1.1.1'
               '&request=GetMap&layers=global_longwave_imagery_mosaic&styles=reflectance&srs=EPSG:4326'
               '&bbox=-180,-90,180,90&width=%d&height=%d&format=image/png&transparent=true')
OPEN_METEO = ('https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s'
              '&current=temperature_2m,wind_speed_10m,wind_direction_10m')
GDACS = 'https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH?eventlist=TC'
NHC = 'https://www.nhc.noaa.gov/CurrentStorms.json'
USGS_QUAKES = 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/%s.geojson'
QUAKE_FEEDS = ['2.5_day', '4.5_week', 'significant_month']
GVP_ERUPTIONS = ('https://webservices.volcano.si.edu/geoserver/GVP-VOTW/ows?service=WFS&version=2.0.0'
                 '&request=GetFeature&typeName=GVP-VOTW:E3WebApp_Eruptions1960&outputFormat=application/json'
                 '&CQL_FILTER=ContinuingEruption=%27True%27')
NOWCOAST_LIGHTNING = ('https://nowcoast.noaa.gov/geoserver/observations/lightning_detection/ows?service=WMS'
                      '&version=1.1.1&request=GetMap&layers=ldn_lightning_strike_density&styles=lightning_density'
                      '&srs=EPSG:4326&bbox=-180,-90,180,90&width=%d&height=%d&format=image/png&transparent=true')
ISS_TLE = 'https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=tle'
# Every aircraft in the world in one request. Anonymous use allows about 400 credits a day per
# IP address and this request costs 4, so the default refresh is half an hour.
OPENSKY_ALL = 'https://opensky-network.org/api/states/all'
OSM_TILE = 'https://tile.openstreetmap.org/%d/%d/%d.png'
CARTO_TILE = 'https://a.basemaps.cartocdn.com/dark_nolabels/%d/%d/%d.png'
NOAA_VEGETATION = 'ftp://public.sos.noaa.gov/overlays/land_mask/veg/4096.png'
SOS_LAND = 'ftp://public.sos.noaa.gov/land/'
# Days missing from NOAA's daily land temperature series (2024-03-31 to 2025-04-07).
LAND_TEMP_GAPS = {'20240514', '20240627', '20240628', '20240629'} | {'202501%02d' % d for d in range(23, 32)} \
    | {'202502%02d' % d for d in range(1, 6)}
BASE_W, BASE_H = 2048, 1024   # world.SW, world.SH

RETRY_MIN, RETRY_MAX = 120.0, 3600.0
HOUR = 3600.0


class Store(object):
    """Files in one folder: <name>.bin plus <name>.json holding when it was fetched."""

    def __init__(self, folder):
        self.folder = folder
        self.metas = {}   # name -> meta, so asking how old something is never touches the disk
        if not os.path.isdir(folder):
            os.makedirs(folder)

    def meta(self, name):
        """When `name` was fetched (and its valid time), without reading the data."""
        if name not in self.metas:
            try:
                with open(self._paths(name)[1]) as handle:
                    self.metas[name] = json.load(handle)
            except (OSError, IOError, ValueError):
                self.metas[name] = None
        return self.metas[name]

    def _paths(self, name):
        return os.path.join(self.folder, name + '.bin'), os.path.join(self.folder, name + '.json')

    def get(self, name):
        data_path, meta_path = self._paths(name)
        try:
            with open(meta_path) as handle:
                meta = json.load(handle)
            with open(data_path, 'rb') as handle:
                return handle.read(), meta
        except (OSError, IOError, ValueError):
            return None, None

    def put(self, name, data, meta):
        raster.write(self._paths(name)[0], data)
        self.put_meta(name, meta)

    def put_meta(self, name, meta):
        meta_path = self._paths(name)[1]
        with open(meta_path + '.tmp', 'w') as handle:
            json.dump(meta, handle)
        os.replace(meta_path + '.tmp', meta_path)
        self.metas[name] = meta


class Feed(object):
    """One remote resource with a refresh interval, a disk copy and failure backoff."""

    def __init__(self, name, label, refresh, download, attribution, source=None, every_start=False):
        self.name = name
        self.source = source   # when set, a cached copy fetched from elsewhere is out of date
        # every_start: fetched once whenever the screensaver starts, however fresh the copy is;
        # download then takes the last meta and returns (None, None, meta) when nothing changed.
        self.every_start = every_start
        self.fetched = False
        self.unchanged = False
        self.label = label
        self.refresh = refresh
        self.download = download
        self.attribution = attribution
        self.next_try = 0.0
        self.delay = RETRY_MIN
        self.error = None

    def due(self, store, now):
        if now < self.next_try:
            return False
        meta = store.meta(self.name)
        if meta is None or (self.source and meta.get('source') != self.source):
            return True
        if self.every_start and not self.fetched:
            return True
        return now - meta.get('fetched', 0) >= self.refresh

    def run(self, store, now=None):
        """Download now; returns True when new data was stored."""
        now = now or time.time()
        self.unchanged = False
        try:
            if self.every_start:
                data, valid, extra = self.download(store.meta(self.name) or {})
            else:
                (data, valid), extra = self.download(), {}
            meta = dict(extra, fetched=now, valid=valid, source=self.source)
            self.fetched = True
            if data is None:   # same as the copy on disk
                store.put_meta(self.name, meta)
                self.unchanged = True
            else:
                store.put(self.name, data, meta)
            self.error = None
            self.delay = RETRY_MIN
            self.next_try = now + self.refresh
            return not self.unchanged
        except Exception as error:
            self.error = str(error)
            self.next_try = now + self.delay
            self.delay = min(RETRY_MAX, self.delay * 2)
            return False


# ---------------------------------------------------------------- downloads

def gibs(layer, w, h, extra=''):
    return net.fetch(GIBS.format(layer=layer, w=w, h=h) + extra, timeout=60)


def _yesterday():
    return time.strftime('%Y-%m-%d', time.gmtime(time.time() - 86400))


def download_clouds():
    return net.fetch(NOWCOAST_IR % (overlays.OW, overlays.OH), timeout=60), None


def download_precip():
    return gibs('IMERG_Precipitation_Rate', overlays.OW, overlays.OH), None


def download_weather():
    lats, lons = overlays.grid_points()
    la, lo = [], []
    for lat in lats:
        for lon in lons:
            la.append(str(lat))
            lo.append(str(lon))
    body = net.fetch(OPEN_METEO % (','.join(la), ','.join(lo)), timeout=60)
    docs = json.loads(body.decode('utf-8'))
    valid = None
    if docs and isinstance(docs, list):
        stamp = (docs[0].get('current') or {}).get('time')
        if stamp:
            valid = calendar.timegm(time.strptime(stamp, '%Y-%m-%dT%H:%M'))
    return body, valid


def download_storms():
    storms = []
    try:
        doc = net.fetch_json(GDACS, timeout=30)
        for f in doc.get('features', []):
            p = f.get('properties', {})
            if str(p.get('iscurrent')).lower() != 'true':
                continue
            lon, lat = f['geometry']['coordinates'][:2]
            sev = (p.get('severitydata') or {}).get('severity') or 0
            storms.append({'name': (p.get('eventname') or '').split('-')[0].title(), 'lat': lat, 'lon': lon,
                           'wind_kmh': sev, 'level': p.get('alertlevel') or ''})
    except Exception:
        if not storms:
            storms = None
    try:
        nhc = net.fetch_json(NHC, timeout=30)
        for s in nhc.get('activeStorms', []):
            entry = {'name': s.get('name', ''), 'lat': s.get('latitudeNumeric'), 'lon': s.get('longitudeNumeric'),
                     'wind_kmh': float(s.get('intensity') or 0) * 1.852, 'level': s.get('classification', '')}
            if storms is None:
                storms = []
            # NHC has the current position and intensity; prefer it over GDACS for its storms.
            storms = [x for x in storms if x['name'].lower() != entry['name'].lower()] + [entry]
    except Exception:
        pass
    if storms is None:
        raise net.HttpError('no storm feed answered')
    return json.dumps(storms).encode('utf-8'), None


def download_quakes(feed='2.5_day'):
    return net.fetch(USGS_QUAKES % feed, timeout=30), None


def download_volcanoes():
    return net.fetch(GVP_ERUPTIONS, timeout=60), None


def download_fires():
    # Yesterday's complete global VIIRS (NOAA-20) fire detections.
    return gibs('VIIRS_NOAA20_Thermal_Anomalies_375m_All', 2048, 1024, '&TIME=' + _yesterday()), None


def download_lightning():
    return net.fetch(NOWCOAST_LIGHTNING % (overlays.OW, overlays.OH), timeout=60), None


def download_flights():
    data = net.fetch_json(OPENSKY_ALL, timeout=60)
    aircraft = flights.parse_opensky(data)
    if not aircraft:
        raise net.HttpError('OpenSky returned no aircraft')
    return flights.encode(aircraft, data.get('time') or time.time()), None


def download_iss():
    text = net.fetch(ISS_TLE, timeout=30)
    if b'\n1 25544' not in text:
        raise net.HttpError('no ISS elements in the CelesTrak answer')
    return text, None


def _mercator_world(tile_url, z):
    """A Web Mercator tile mosaic at zoom z, resampled to an equirectangular RGBA image.
    Longitude is linear in both, so this only re-orders rows."""
    n = 2 ** z
    size = 256 * n
    rows = [None] * size
    for ty in range(n):
        tiles = [raster.decode(net.fetch(tile_url % (z, tx, ty), timeout=30), want=4) for tx in range(n)]
        for y in range(256):
            rows[ty * 256 + y] = b''.join(bytes(t.data[y * 1024:(y + 1) * 1024]) for t in tiles)
    w, h = size, size // 2
    out = bytearray()
    for y in range(h):
        lat = 90.0 - (y + 0.5) * 180.0 / h
        if abs(lat) > 85.0:  # beyond Web Mercator: repeat the edge row
            out += rows[0] if lat > 0 else rows[-1]
            continue
        my = (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * size
        out += rows[min(size - 1, int(my))]
    return raster.encode_rgba(w, h, bytes(out), level=6), None


def download_osm():
    return _mercator_world(OSM_TILE, 3)


def download_carto_dark():
    return _mercator_world(CARTO_TILE, 3)


def download_image(url, previous):
    """A whole-world equirectangular PNG from an http(s):// or ftp:// address (ftp://user:password@host/
    also works), resized to the base map size. Decoding a big PNG takes minutes on a Fire TV
    Stick, so a download identical to the last one (by MD5) is not decoded again."""
    url = url.strip()
    if not url.lower().startswith(('ftp://', 'http://', 'https://')):
        raise net.HttpError('base map address must start with ftp://, http:// or https://')
    body = net.fetch(url, timeout=180, max_bytes=64 * 1024 * 1024)
    digest = hashlib.md5(body).hexdigest()
    if previous.get('md5') == digest and previous.get('source') == url:
        return None, None, {'md5': digest}
    img = raster.resize(raster.decode(body, want=4), BASE_W, BASE_H)
    return raster.encode_rgba(img.w, img.h, bytes(img.data), level=6), None, {'md5': digest}


def download_relief():
    return gibs('BlueMarble_ShadedRelief_Bathymetry', 2048, 1024), None


def download_viirs():
    return gibs('VIIRS_NOAA20_CorrectedReflectance_TrueColor', 2048, 1024, '&TIME=' + _yesterday()), None


WEATHER_FEEDS = {
    'clouds': lambda: Feed('clouds', 'Clouds', HOUR, download_clouds, 'NOAA nowCOAST'),
    'precip': lambda: Feed('precip', 'Rain', HOUR, download_precip, 'NASA GPM IMERG'),
    'weather': lambda: Feed('weather', 'Temp/wind', 3 * HOUR, download_weather, 'Open-Meteo.com (CC BY 4.0)'),
    'storms': lambda: Feed('storms', 'Storms', HOUR / 2, download_storms, 'GDACS, NOAA NHC'),
    'quakes': lambda: Feed('quakes', 'Quakes', HOUR / 6, download_quakes, 'USGS'),
    'volcanoes': lambda: Feed('volcanoes', 'Volcanoes', 12 * HOUR, download_volcanoes, 'Smithsonian GVP'),
    'fires': lambda: Feed('fires', 'Fires', 3 * HOUR, download_fires, 'NASA FIRMS / VIIRS'),
    'lightning': lambda: Feed('lightning', 'Lightning', HOUR / 6, download_lightning, 'NOAA nowCOAST'),
    'iss': lambda: Feed('iss', 'ISS', 12 * HOUR, download_iss, 'CelesTrak'),
    'flights': lambda: Feed('flights', 'Flights', HOUR / 2, download_flights, 'OpenSky Network'),
}

def sos_surface_temperature(now):
    """Average land and sea surface temperature for this calendar month."""
    return 'surface_temperature/4096/surface_temps_4096_%02d.png' % time.localtime(now).tm_mon


def sos_vegetation_index(now):
    """NDVI for this week of the year; NOAA's year runs from 2012 week 14 to 2013 week 14."""
    week = min(52, int(time.strftime('%V', time.localtime(now))))
    return 'global_vegetation/4096/%dweek%02d.png' % (2012 if week >= 14 else 2013, week)


def sos_koppen_now(now):
    """Köppen climate zones for the 25-year period containing this year."""
    start = 1901 + (max(1901, min(2100, time.localtime(now).tm_year)) - 1901) // 25 * 25
    return 'koppen_climate/koppen_1901-2100/4096/%d-%d.png' % (start, start + 24)


def sos_land_temperature(now):
    """Daytime land surface temperature on this calendar day (from 2024-25), or the nearest earlier day."""
    day = time.localtime(now)
    year = 2024 if (day.tm_mon, day.tm_mday) >= (3, 31) else 2025
    t = calendar.timegm((year, day.tm_mon, min(day.tm_mday, 28 if day.tm_mon == 2 else 31), 12, 0, 0))
    while time.strftime('%Y%m%d', time.gmtime(t)) in LAND_TEMP_GAPS:
        t -= 86400
    return 'land_temp/4096/land_temp_%s.png' % time.strftime('%Y%m%d', time.gmtime(t))


def sos_map(bid, name, path, attribution):
    """A base map from NOAA Science On a Sphere's public FTP site, fetched at every start.
    path is a file under /land, or a function of the time giving one (maps that change by date)."""
    def factory(_settings):
        url = SOS_LAND + (path(time.time()) if callable(path) else path)
        return Feed(bid, name, 24 * HOUR, lambda prev: download_image(url, prev), '', url, every_start=True)
    return (bid, name, factory, 'NOAA Science On a Sphere: ' + attribution)


# Base maps: (id, name, feed factory(settings) or None when bundled/generated, attribution)
BASEMAPS = [
    ('bluemarble', 'Satellite (Blue Marble)', None, 'NASA Blue Marble'),
    ('relief', 'Relief and ocean floor', lambda s: Feed('relief', 'Relief', 90 * 24 * HOUR, download_relief, ''),
     'NASA Blue Marble shaded relief'),
    ('viirs', "Satellite, yesterday's image", lambda s: Feed('viirs', 'Satellite', 24 * HOUR, download_viirs, ''),
     'NASA GIBS / VIIRS NOAA-20'),
    ('osm', 'OpenStreetMap', lambda s: Feed('osm', 'OSM', 30 * 24 * HOUR, download_osm, ''),
     '© OpenStreetMap contributors'),
    ('dark', 'Dark (CARTO)', lambda s: Feed('dark', 'Dark', 30 * 24 * HOUR, download_carto_dark, ''),
     '© OpenStreetMap contributors, © CARTO'),
    ('atlas', 'Atlas (flat colours)', None, 'Land cover from NASA and Mapzen data'),
    ('atlas_dark', 'Dark atlas', None, 'Land cover from NASA and Mapzen data'),
    # Added later: config.STYLES lists these after the ASCII modes so saved choices keep their numbers.
    ('vegetation', 'Vegetation (NOAA)',
     lambda s: Feed('vegetation', 'Vegetation', 24 * HOUR, lambda prev: download_image(NOAA_VEGETATION, prev),
                    '', NOAA_VEGETATION, every_start=True),
     'NOAA Science On a Sphere, vegetation'),
    ('custom', 'Custom (FTP or web address)',
     lambda s: Feed('custom', 'Custom map', 24 * HOUR, lambda prev: download_image(s['custom_basemap_url'], prev),
                    '', s['custom_basemap_url'].strip(), every_start=True),
     'Custom base map'),
    sos_map('sos_gray', 'Gray relief (NOAA)', 'gray_earth/4096.png', 'gray Earth'),
    sos_map('sos_seafloor', 'Age of the sea floor (NOAA)', 'sea_floor_age/topo/seafloor_4096.png', 'sea floor age'),
    sos_map('sos_plates', 'Plates and sea floor age (NOAA)', 'sea_floor_age/shaded_veg/4096.png',
            'sea floor age, plate boundaries'),
    sos_map('sos_birds', 'Bird species richness (NOAA)', 'species_richness/birds/4096-background.png',
            'bird species richness'),
    sos_map('sos_mammals', 'Mammal species richness (NOAA)', 'species_richness/mammals/4096-background.png',
            'mammal species richness'),
    sos_map('sos_amphibians', 'Amphibian species richness (NOAA)',
            'species_richness/amphibians/4096-background.png', 'amphibian species richness'),
    sos_map('sos_pasture', 'Pastureland (NOAA)', 'agriculture/pastureland/4096.png', 'pastureland'),
    sos_map('sos_food_feed', 'Crops for food or feed (NOAA)', 'food_v_feed/4096.png', 'food versus feed'),
    sos_map('sos_surface_temp', 'Surface temperature, this month (NOAA)', sos_surface_temperature,
            'surface temperature'),
    sos_map('sos_land_temp', 'Land temperature, this day (NOAA)', sos_land_temperature, 'land surface temperature'),
    sos_map('sos_ndvi', 'Vegetation index, this week (NOAA)', sos_vegetation_index, 'global vegetation (NDVI)'),
    sos_map('sos_koppen', 'Climate zones, today (NOAA)', sos_koppen_now, 'Köppen climate'),
    sos_map('sos_koppen_2100', 'Climate zones, 2076-2100 (NOAA)', 'koppen_climate/koppen_1901-2100/4096/2076-2100.png',
            'Köppen climate projection'),
]
ORIGINAL_BASEMAPS = 7
BASEMAP_IDS = [b[0] for b in BASEMAPS]

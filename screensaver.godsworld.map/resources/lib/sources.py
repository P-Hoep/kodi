"""Where the data comes from, and the on-disk cache that keeps it through outages.
No Kodi imports.

Each Feed downloads one resource, keeps the last good copy on disk with the time it was
fetched, and retries failures with a growing delay (2 minutes doubling up to an hour), so
a dead network is never hammered and the map keeps showing the last good data."""

import calendar
import json
import math
import os
import time

from . import net, overlays, raster

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
OSM_TILE = 'https://tile.openstreetmap.org/%d/%d/%d.png'
CARTO_TILE = 'https://a.basemaps.cartocdn.com/dark_nolabels/%d/%d/%d.png'

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
        data_path, meta_path = self._paths(name)
        raster.write(data_path, data)
        with open(meta_path + '.tmp', 'w') as handle:
            json.dump(meta, handle)
        os.replace(meta_path + '.tmp', meta_path)
        self.metas[name] = meta


class Feed(object):
    """One remote resource with a refresh interval, a disk copy and failure backoff."""

    def __init__(self, name, label, refresh, download, attribution):
        self.name = name
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
        return meta is None or now - meta.get('fetched', 0) >= self.refresh

    def run(self, store, now=None):
        """Download now; returns True when new data was stored."""
        now = now or time.time()
        try:
            data, valid = self.download()
            store.put(self.name, data, {'fetched': now, 'valid': valid})
            self.error = None
            self.delay = RETRY_MIN
            self.next_try = now + self.refresh
            return True
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
}

# Base maps: (id, name, feed factory or None when bundled/generated, attribution)
BASEMAPS = [
    ('bluemarble', 'Satellite (Blue Marble)', None, 'NASA Blue Marble'),
    ('relief', 'Relief and ocean floor', lambda: Feed('relief', 'Relief', 90 * 24 * HOUR, download_relief, ''),
     'NASA Blue Marble shaded relief'),
    ('viirs', "Satellite, yesterday's image", lambda: Feed('viirs', 'Satellite', 24 * HOUR, download_viirs, ''),
     'NASA GIBS / VIIRS NOAA-20'),
    ('osm', 'OpenStreetMap', lambda: Feed('osm', 'OSM', 30 * 24 * HOUR, download_osm, ''),
     '© OpenStreetMap contributors'),
    ('dark', 'Dark (CARTO)', lambda: Feed('dark', 'Dark', 30 * 24 * HOUR, download_carto_dark, ''),
     '© OpenStreetMap contributors, © CARTO'),
    ('atlas', 'Atlas (flat colours)', None, 'Land cover from NASA and Mapzen data'),
    ('atlas_dark', 'Dark atlas', None, 'Land cover from NASA and Mapzen data'),
]
BASEMAP_IDS = [b[0] for b in BASEMAPS]

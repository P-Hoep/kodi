"""Tile sources and an on-disk tile cache with background downloads. No Kodi imports."""

import os
import threading
import time
from . import net
from .workers import Workers
from .geo import mercator_bounds


class TileSource(object):
    def __init__(self, sid, name, url, ext, attribution, max_zoom=19, max_age=7 * 86400,
                 workers=2, bucket=0, transform=None):
        self.id = sid
        self.name = name
        self._url = url
        self.ext = ext
        self.attribution = attribution
        self.max_zoom = max_zoom
        self.max_age = max_age
        self.workers = workers
        # Time-varying layers (weather) cache per bucket of this many seconds.
        self.bucket = bucket
        # Optional f(bytes) -> bytes or None, applied to each tile before it is cached.
        self.transform = transform

    def url(self, z, x, y):
        if callable(self._url):
            return self._url(z, x, y)
        return self._url.format(z=z, x=x, y=y)

    def stamp(self):
        return int(time.time() // self.bucket) if self.bucket else 0


def _nowcoast(service, layer, style):
    base = 'https://nowcoast.noaa.gov/geoserver/observations/%s/ows' % service

    def url(z, x, y):
        bbox = ','.join('%.2f' % v for v in mercator_bounds(x, y, z))
        return (base + '?service=WMS&version=1.1.1&request=GetMap&layers=%s&styles=%s'
                '&srs=EPSG:3857&bbox=%s&width=256&height=256&format=image/png&transparent=true'
                % (layer, style, bbox))
    return url


def _gibs_url(z, x, y):
    # Yesterday (UTC): today's VIIRS composite is still filling in.
    day = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 86400))
    return ('https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_SNPP_CorrectedReflectance_TrueColor'
            '/default/%s/GoogleMapsCompatible_Level9/%d/%d/%d.jpg' % (day, z, y, x))


OSM = TileSource('osm', 'OpenStreetMap', 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', 'png',
                 '© OpenStreetMap contributors', max_zoom=19, workers=2)
DARK = TileSource('dark', 'Dark', 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
                  'jpg', 'Esri, HERE, Garmin, © OpenStreetMap contributors', max_zoom=16, workers=4)
DARK_LABELS = TileSource('dark-labels', 'Dark labels',
                         'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
                         'png', 'Esri', max_zoom=16, workers=4)
ESRI = TileSource('esri', 'Esri satellite',
                  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                  'jpg', 'Esri, Maxar, Earthstar Geographics', max_zoom=19, workers=4)
GIBS = TileSource('gibs', "NASA VIIRS (yesterday's satellite image)", _gibs_url, 'jpg',
                  'NASA GIBS / VIIRS', max_zoom=9, max_age=86400, workers=3, bucket=86400)
ESRI_LABELS = TileSource('esri-labels', 'Esri labels',
                         'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
                         'png', 'Esri', max_zoom=19, workers=4)

# Settings "basemap" index -> tile sources drawn bottom to top.
BASEMAPS = [
    ('OpenStreetMap', [OSM]),
    ('Dark', [DARK, DARK_LABELS]),
    ('Satellite (Esri)', [ESRI]),
    ('Satellite + labels', [ESRI, ESRI_LABELS]),
    ("NASA satellite image of the day", [GIBS, ESRI_LABELS]),
]

def recolored(source, look):
    """source with every tile recoloured for a sensor look, cached in its own folder."""
    from .looks import recolor_palette_png

    return TileSource('%s-%s' % (source.id, look.id), '%s (%s)' % (source.name, look.name), source._url,
                      source.ext, source.attribution, max_zoom=source.max_zoom, max_age=source.max_age,
                      workers=source.workers, bucket=source.bucket,
                      transform=lambda body: recolor_palette_png(body, look.recolor))


RAIL = TileSource('rail', 'Rail, subway & tram lines', 'https://tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png',
                  'png', 'OpenRailwayMap (CC BY-SA)', max_zoom=19, workers=2)

RADAR = TileSource('radar', 'Rain radar (US)',
                   _nowcoast('weather_radar', 'conus_base_reflectivity_mosaic', 'weather_radar_base_reflectivity'),
                   'png', 'NOAA nowCOAST MRMS', max_age=600, workers=3, bucket=300)
LIGHTNING = TileSource('lightning', 'Lightning (Americas)',
                       _nowcoast('lightning_detection', 'ldn_lightning_strike_density', 'lightning_density'),
                       'png', 'NOAA nowCOAST; Vaisala', max_age=900, workers=3, bucket=300)


# Time-bucketed tile folders are pruned sooner than base maps.
SHORT_LIVED = {'radar': 3 * 3600, 'clouds': 6 * 3600, 'lightning': 3 * 3600,
               'tomtom-flow': 3 * 3600, 'tomtom-incidents': 3 * 3600, 'gibs': 3 * 86400}


def tomtom(kind, key, refresh):
    """TomTom traffic raster tiles (free key: 200k tiles/month). kind: 'flow' or 'incidents'."""
    path = 'flow/relative0' if kind == 'flow' else 'incidents/s3'

    def url(z, x, y):
        return 'https://api.tomtom.com/traffic/map/4/tile/%s/%d/%d/%d.png?key=%s&tileSize=256' % (path, z, x, y, key)
    return TileSource('tomtom-' + kind, 'Traffic ' + kind, url, 'png', 'TomTom Traffic', max_zoom=18,
                      max_age=refresh, workers=2, bucket=refresh)


RAIL_MIN_ZOOM = 7  # below this the whole network is a solid tangle


def overlays(settings):
    """Overlay tile layers turned on in settings, drawn bottom to top, each with an opacity 0-255."""
    alpha = int(max(0, min(100, settings.get('overlay_opacity', 70))) * 255 / 100)
    out = []
    if settings.get('layer_rail') and settings.get('zoom', 99) >= RAIL_MIN_ZOOM:
        out.append((RAIL, 255))
    key = (settings.get('tomtom_key') or '').strip()
    if key and settings.get('layer_traffic'):
        out.append((tomtom('flow', key, max(300, settings.get('traffic_refresh', 600))), 255))
    if key and settings.get('layer_incidents'):
        out.append((tomtom('incidents', key, max(300, settings.get('traffic_refresh', 600))), 255))
    if settings.get('layer_radar'):
        out.append((RADAR, alpha))
    if settings.get('layer_lightning'):
        out.append((LIGHTNING, alpha))
    return out


class TileCache(object):
    """Downloads tiles to disk. ensure() returns a ready path or schedules a download."""

    def __init__(self, root, on_ready, log=None):
        self.root = root
        self.on_ready = on_ready  # called (source_id, key, path) from worker threads
        self.log = log or (lambda msg: None)
        self._pools = {}
        self._pending = set()
        self._failed = {}
        self._lock = threading.Lock()
        self._wanted = set()

    def path(self, source, z, x, y):
        stamp = source.stamp()
        name = '%d_%d_%d%s.%s' % (z, x, y, ('_%d' % stamp) if stamp else '', source.ext)
        return os.path.join(self.root, source.id, str(z), name)

    def want(self, keys):
        """Only keys in this set are downloaded; older queued requests are dropped."""
        with self._lock:
            self._wanted = set(keys)

    def ensure(self, source, z, x, y):
        path = self.path(source, z, x, y)
        try:
            if time.time() - os.path.getmtime(path) < source.max_age:
                return path
        except OSError:
            pass
        key = (source.id, z, x, y)
        with self._lock:
            if path in self._pending or time.time() - self._failed.get(path, 0) < 60:
                return None
            self._pending.add(path)
        pool = self._pools.get(source.id)
        if pool is None:
            pool = self._pools[source.id] = Workers(source.workers, 'tiles-' + source.id)
        pool.submit(self._download, source, key, path)
        return None

    def _download(self, source, key, path):
        try:
            with self._lock:
                if key not in self._wanted:
                    return
            body = net.fetch(source.url(key[1], key[2], key[3]), timeout=10, max_bytes=4 * 1024 * 1024)
            if source.transform:
                body = source.transform(body) or body
            folder = os.path.dirname(path)
            try:
                os.makedirs(folder)
            except OSError:
                if not os.path.isdir(folder):  # parallel workers may race to create it
                    raise
            tmp = path + '.part'
            with open(tmp, 'wb') as handle:
                handle.write(body)
            os.replace(tmp, path)
            self.on_ready(source.id, key, path)
        except Exception as error:  # network or disk; retry after a pause
            with self._lock:
                self._failed[path] = time.time()
            self.log('tile %s failed: %s' % (key, error))
        finally:
            with self._lock:
                self._pending.discard(path)

    def prune(self, max_age=14 * 86400):
        """Delete tiles older than max_age (and all expired weather frames)."""
        now = time.time()
        for folder, _dirs, files in os.walk(self.root):
            for name in files:
                full = os.path.join(folder, name)
                try:
                    limit = max_age
                    top = os.path.relpath(full, self.root).split(os.sep)[0]
                    if top in SHORT_LIVED:
                        limit = SHORT_LIVED[top]
                    if now - os.path.getmtime(full) > limit:
                        os.remove(full)
                except OSError:
                    pass

    def shutdown(self):
        with self._lock:
            self._wanted = set()
        for pool in self._pools.values():
            pool.shutdown()

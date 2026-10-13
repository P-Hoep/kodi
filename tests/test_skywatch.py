"""Offline tests for SkyWatch: tile math, astronomy against published times, the fishing
score, climate normals, cache expiry, back-off, the radar fallback chain, the playlist and
the chart rasteriser. No network, no Kodi.

python3 -m unittest tests.test_skywatch
"""

import calendar
import os
import shutil
import sys
import tempfile
import time
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screensaver.skywatch'))

from resources.lib import (astro, budget, cache, climate, config, fishing, geo, player, radar,  # noqa: E402
                           raster, scenes, units)
from resources.lib.layout import Layout  # noqa: E402
from resources.lib.scenes import conditions  # noqa: E402
from resources.lib.sources import nws  # noqa: E402
from resources.lib.sources.base import Source, parse_iso  # noqa: E402

MSP = (44.9778, -93.2650)
CDT = -5 * 3600


def utc(*args):
    return calendar.timegm(args + (0,) * (6 - len(args)))


def local_hm(epoch, offset=CDT):
    tm = time.gmtime(epoch + offset)
    return tm.tm_hour * 60 + tm.tm_min


class TileMath(unittest.TestCase):
    def test_round_trip(self):
        for lat, lon, z in ((44.9, -93.3, 8), (-33.9, 151.2, 12), (0.0, 0.0, 3)):
            x, y = geo.to_pixel(lat, lon, z)
            lat2, lon2 = geo.from_pixel(x, y, z)
            self.assertAlmostEqual(lat, lat2, 6)
            self.assertAlmostEqual(lon, lon2, 6)

    def test_centre_is_screen_centre(self):
        v = geo.Viewport(44.9, -93.3, 8)
        x, y = v.screen_xy(44.9, -93.3)
        self.assertAlmostEqual(x, 960, 6)
        self.assertAlmostEqual(y, 540, 6)

    def test_bbox3857_matches_tiles(self):
        # The WMS bounding box and the tile grid must describe the same pixels.
        v = geo.Viewport(44.9, -93.3, 8)
        x0, y0, x1, y1 = v.bbox3857()
        ox, oy = v.origin
        self.assertAlmostEqual(geo.pixel_to_mercator(ox, oy, 8)[0], x0, 3)
        self.assertAlmostEqual(geo.pixel_to_mercator(ox, oy, 8)[1], y1, 3)
        span = 2 * geo.HALF_WORLD_M / geo.world_size(8)
        self.assertAlmostEqual((x1 - x0) / span, 1920, 6)
        self.assertAlmostEqual((y1 - y0) / span, 1080, 6)

    def test_tiles_cover_screen(self):
        v = geo.Viewport(44.9, -93.3, 8)
        tiles = v.tiles_at(19)
        self.assertLessEqual(len(tiles), v.max_tiles())
        self.assertTrue(any(sx <= 0 and sy <= 0 for _z, _x, _y, sx, sy, _s in tiles))
        self.assertTrue(any(sx + s >= 1920 and sy + s >= 1080 for _z, _x, _y, sx, sy, s in tiles))
        # Above a source's max zoom tiles are enlarged.
        self.assertTrue(all(s == 512 for _z, _x, _y, _sx, _sy, s in v.tiles_at(7)))

    def test_offset_point(self):
        lat, lon = geo.offset_point(45.0, -93.0, 90, 100)
        self.assertAlmostEqual(geo.haversine_km(45.0, -93.0, lat, lon), 100, 1)
        self.assertGreater(lon, -93.0)


class Astronomy(unittest.TestCase):
    """Against USNO / timeanddate values for Minneapolis, 12 Oct 2026."""

    def test_sun(self):
        day = astro.sun_day(utc(2026, 10, 12, 18), MSP[0], MSP[1], CDT)
        self.assertAlmostEqual(local_hm(day['sunrise']), 7 * 60 + 25, delta=2)
        self.assertAlmostEqual(local_hm(day['sunset']), 18 * 60 + 34, delta=3)
        self.assertAlmostEqual(day['day_length'] / 3600.0, 11.14, delta=0.06)

    def test_moon_phases(self):
        new = astro.next_phase(utc(2026, 10, 1), 0)
        full = astro.next_phase(utc(2026, 10, 12), 180)
        self.assertAlmostEqual(new, utc(2026, 10, 10, 15, 50), delta=3600)
        self.assertAlmostEqual(full, utc(2026, 10, 26, 4, 12), delta=3600)
        phase = astro.moon_phase(utc(2026, 10, 12, 18))
        self.assertEqual(phase['name'], 'Waxing crescent')

    def test_solunar_periods(self):
        p = astro.solunar(utc(2026, 10, 12, 18), MSP[0], MSP[1], CDT)
        self.assertTrue(1 <= len(p['major']) <= 3)
        for a, b, c in p['major']:
            self.assertAlmostEqual(b - a, 2 * 3600)
            self.assertTrue(a < c < b)
        for a, b, _c in p['minor']:
            self.assertAlmostEqual(b - a, 3600)

    def test_days_from_new_or_full(self):
        self.assertLess(astro.days_from_new_or_full(utc(2026, 10, 10, 16)), 0.5)
        self.assertGreater(astro.days_from_new_or_full(utc(2026, 10, 18)), 5)


class Fishing(unittest.TestCase):
    def test_factor_shapes(self):
        self.assertEqual(fishing.pressure_factor(-1.0), 1.0)
        self.assertLess(fishing.pressure_factor(3.0), fishing.pressure_factor(0.0))
        self.assertEqual(fishing.wind_factor(16.0), 1.0)          # 10 mph
        self.assertEqual(fishing.wind_factor(40.0), 0.2)          # 25 mph
        self.assertEqual(fishing.moon_factor(1.0), 1.0)
        self.assertEqual(fishing.cloud_factor(90), 1.0)

    def test_score_renormalises_missing(self):
        w = fishing.weights(config.defaults())
        full = dict((f, 1.0) for f in fishing.FACTORS)
        self.assertEqual(fishing.score(full, w)[0], 100)
        missing = dict(full, water=None)
        value, parts = fishing.score(missing, w)
        self.assertEqual(value, 100)
        self.assertNotIn('water', parts)
        half = dict((f, 0.5) for f in fishing.FACTORS)
        self.assertEqual(fishing.score(half, w)[0], 50)

    def test_presets_scale_weights(self):
        s = config.defaults()
        self.assertGreater(fishing.weights(s, 'Trout')['water'], fishing.weights(s)['water'])


def synthetic_archive(years=range(1985, 2026)):
    """Highs follow a seasonal sine with a year trend; one record day planted."""
    import math
    dates, his, los = [], [], []
    for year in years:
        for doy in range(365):
            t = time.gmtime(utc(year, 1, 1) + doy * 86400)
            dates.append(time.strftime('%Y-%m-%d', t))
            base = 10 - 15 * math.cos(2 * math.pi * (doy - 15) / 365.0)
            his.append(base + 5 + (year - 2000) * 0.02)
            los.append(base - 5)
    i = dates.index('1999-07-04')
    his[i] = 45.0
    return {'time': dates, 'max': his, 'min': los}


class Climate(unittest.TestCase):
    def test_normals_and_records(self):
        arc = synthetic_archive()
        rows = climate.normals(arc)
        self.assertEqual(len(rows), 366)
        july = rows[climate.INDEX['07-15']]
        jan = rows[climate.INDEX['01-15']]
        self.assertGreater(july['hi'], jan['hi'] + 20)
        self.assertLessEqual(july['hi10'], july['hi'])
        self.assertGreaterEqual(july['hi90'], july['hi'])
        rec = climate.records(arc)[climate.INDEX['07-04']]
        self.assertEqual(rec['hi'], (45.0, 1999))

    def test_fact(self):
        arc = synthetic_archive()
        rows = climate.normals(arc)
        hist = climate.by_day(arc)
        u = units.Units(config.defaults())
        n = rows[climate.INDEX['07-04']]
        self.assertEqual(climate.fact('07-04', 2026, 50.0, 20.0, hist, n, u),
                         'Warmest Jul 4 since records began in 1985')
        self.assertEqual(climate.fact('07-04', 2026, 44.0, 20.0, hist, n, u), 'Warmest Jul 4 since 1999')
        self.assertIn('normal', climate.fact('07-04', 2026, n['hi'] + 0.8, 20.0, hist, n, u))

    def test_anomalies(self):
        arc = synthetic_archive()
        rows = climate.normals(arc)
        out = climate.anomalies(arc, rows, ['2010-07-01', '1900-01-01'])
        self.assertIsNotNone(out[0])
        self.assertIsNone(out[1])


class Caches(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_expiry(self):
        c = cache.JsonCache(os.path.join(self.tmp, 'd.db'))
        c.put('a', {'x': 1}, ttl=60)
        self.assertEqual(c.get('a')[0], {'x': 1})
        self.assertTrue(c.fresh('a'))
        c.put('b', [1], ttl=60, fetched=time.time() - 120)
        self.assertFalse(c.fresh('b'))
        self.assertEqual(c.value('b'), [1])     # stale values are still served
        c.expire('a')
        self.assertFalse(c.fresh('a'))

    def test_evict_order(self):
        for folder, n in (('frames', 5), ('tiles', 5)):
            os.makedirs(os.path.join(self.tmp, folder))
            for i in range(n):
                with open(os.path.join(self.tmp, folder, '%d.png' % i), 'wb') as f:
                    f.write(b'x' * 1000)
        cache.evict(self.tmp, 6000)
        self.assertLess(len(os.listdir(os.path.join(self.tmp, 'frames'))), 5)
        self.assertEqual(len(os.listdir(os.path.join(self.tmp, 'tiles'))), 5)   # base maps go last


class Backoff(unittest.TestCase):
    def test_doubles_and_resets(self):
        b = budget.Budget()
        now = 1000.0
        self.assertEqual(b.failed('x', 429, now=now), 60)
        self.assertFalse(b.ready('x', now + 30))
        self.assertEqual(b.failed('x', 429, now=now), 120)
        for _ in range(10):
            delay = b.failed('x', 503, now=now)
        self.assertEqual(delay, 3600)
        b.ok('x')
        self.assertTrue(b.ready('x', now))

    def test_monthly_cap(self):
        b = budget.Budget()
        b.count('rainbow', 26000)
        self.assertFalse(b.allows('rainbow', 2000, 30000))
        self.assertTrue(b.allows('rainbow', 500, 30000))


class FakeSource(Source):
    def __init__(self, sid, kinds, covers=True):
        self.id = sid
        self.kinds = kinds
        self._covers = covers
        self.attribution = sid

    def covers(self, lat, lon):
        return self._covers

    def frames(self, view, kind, minutes, size=None, *args):
        if kind not in self.kinds:
            return []
        now = 1_800_000_000
        step = 300 if kind == 'past' else 900
        n = int(minutes * 60 // step)
        ts = [now - k * step for k in range(n, -1, -1)] if kind == 'past' else [now + k * step for k in range(1, n + 1)]
        return [{'t': t, 'kind': kind, 'key': '%s_%d' % (self.id, t), 'run': None,
                 'parts': [('u', 0, 0, 1920, 1080)]} for t in ts]


class FakeChains(object):
    def __init__(self, past, future):
        self._past, self._future = past, future

    def past(self):
        return self._past

    def future(self, allow_rainbow=True):
        return self._future


class FallbackChain(unittest.TestCase):
    def feed(self, chains, b, past=120, future=120, max_frames=36):
        return radar.Feed('t', geo.Viewport(44.9, -93.3, 8), chains, '/tmp/none', (960, 540), b,
                          lambda m: None, past, future, max_frames)

    def test_first_healthy_source_wins(self):
        a, c = FakeSource('a', ('past',)), FakeSource('c', ('past',))
        hrrr = FakeSource('hrrr', ('future',))
        b = budget.Budget()
        f = self.feed(FakeChains([a, c], [hrrr]), b)
        f.make_plan()
        self.assertEqual(f.past_source.id, 'a')
        b.failed('a', 429)
        f.make_plan()
        self.assertEqual(f.past_source.id, 'c')

    def test_uncovered_source_skipped_and_future_drops_out(self):
        iem = FakeSource('iem', ('past',), covers=False)
        rv = FakeSource('rainviewer', ('past',))
        rainbow, hrrr = FakeSource('rainbow', ('future',)), FakeSource('hrrr', ('future',))
        b = budget.Budget()
        f = self.feed(FakeChains([iem, rv], [rainbow, hrrr]), b)
        f.make_plan()
        self.assertEqual((f.past_source.id, f.future_source.id), ('rainviewer', 'rainbow'))
        b.failed('rainbow', 503)
        b.failed('hrrr', 503)
        plan = f.make_plan()
        self.assertIsNone(f.future_source)                  # Rainbow -> HRRR -> past only
        self.assertTrue(all(fr['kind'] == 'past' for fr in plan))

    def test_frame_budget(self):
        f = self.feed(FakeChains([FakeSource('a', ('past',))], [FakeSource('h', ('future',))]), budget.Budget(),
                      max_frames=24)
        plan = f.make_plan()
        self.assertLessEqual(len(plan), 24)
        self.assertEqual(sum(1 for fr in plan if fr['kind'] == 'future'), 8)
        self.assertEqual(plan[-9]['t'], 1_800_000_000)      # the NOW frame is always kept


def defaults(**kw):
    s = config.defaults()
    s.update(lat=MSP[0], lon=MSP[1])
    s.update(kw)
    return s


class Playlist(unittest.TestCase):
    def test_order_and_skip(self):
        s = defaults(pos_current=1)
        p = player.Playlist(s)
        order = p.base_order()
        self.assertEqual(order[0], 'current')
        self.assertNotIn('ambient', order)          # off by default
        self.assertNotIn('national', order)         # off by default
        seen = [p.next(lambda sid: sid != 'local') for _ in range(len(order))]
        self.assertNotIn('local', seen)

    def test_alert_promoted(self):
        p = player.Playlist(defaults())
        self.assertEqual(p.next(lambda sid: True, alerts=True), 'alert')
        self.assertNotEqual(p.next(lambda sid: True, alerts=True), 'alert')

    def test_nothing_available(self):
        self.assertIsNone(player.Playlist(defaults()).next(lambda sid: False))


class Precipitation(unittest.TestCase):
    def forecast(self, mm):
        now = 1_800_000_000
        return {'minutely': {'time': [now + k * 900 for k in range(10)], 'precipitation': mm,
                             'snowfall': [0] * 10}, 'hourly': {}}, now

    def test_headline(self):
        fc, now = self.forecast([0, 0, 0.3, 0.5, 0, 0, 0, 0, 0, 0])
        self.assertEqual(conditions.headline(fc, now - 60, None), 'Rain starting in about 30 min')
        self.assertTrue(conditions.precip_expected(fc, now))
        self.assertEqual(conditions.first_rain(fc, now), now + 1800)
        fc, now = self.forecast([0] * 10)
        self.assertFalse(conditions.precip_expected(fc, now))
        self.assertIn('No precipitation', conditions.headline(fc, now, None))


class Text(unittest.TestCase):
    AFD = """FXUS63 KMPX 122337
AFDMPX

.KEY MESSAGES...

- Spotty showers and an isolated storm possible over western and
  central MN this afternoon.

- Our first shot at widespread sub-freezing temperatures is possible
  Saturday morning.

&&

.DISCUSSION...
Issued at 300 PM CDT Mon Oct 12 2026

Long text here that should not be used because key messages exist.
"""

    def test_key_points(self):
        pts = nws.key_points(self.AFD)
        self.assertEqual(len(pts), 2)
        self.assertTrue(pts[0].startswith('Spotty showers'))
        self.assertIn('western and central MN', pts[0])

    def test_parse_iso(self):
        self.assertEqual(parse_iso('2026-10-12T23:00:00Z'), utc(2026, 10, 12, 23))
        self.assertEqual(parse_iso('2026-10-12T23:00Z'), utc(2026, 10, 12, 23))

    def test_units(self):
        u = units.Units(defaults())
        self.assertEqual(u.temp(20), '68°')
        self.assertEqual(u.wind_text(16.09344), '10 mph')
        self.assertEqual(u.pressure_text(1013.25), '29.92 inHg')
        m = units.Units(defaults(u_temp=1, u_wind=1, u_pressure=1))
        self.assertEqual((m.temp(20), m.wind_text(10), m.pressure_text(1013.25)), ('20°', '10 km/h', '1013 hPa'))
        self.assertEqual(units.compass(225), 'SW')
        self.assertEqual(units.ago(200), '3 min ago')


class Raster(unittest.TestCase):
    def test_png_and_drawing(self):
        c = raster.Canvas(40, 20)
        c.fill_rect(0, 0, 10, 10, 'FFFF0000')
        c.line(0, 15, 39, 15, 'FF00FF00', 3)
        c.fill_polygon([(20, 0), (30, 0), (25, 10)], 'FF0000FF')
        self.assertEqual(c.pixel(5, 5), (255, 0, 0, 255))
        self.assertEqual(c.pixel(20, 15)[1], 255)
        self.assertEqual(c.pixel(25, 3), (0, 0, 255, 255))
        self.assertEqual(c.pixel(35, 5)[3], 0)
        data = c.png()
        self.assertEqual(raster.png_size(data), (40, 20))
        idat = data[data.index(b'IDAT') + 4:data.index(b'IEND') - 8]
        self.assertEqual(len(zlib.decompress(idat)), 20 * (1 + 40 * 4))


class Layouts(unittest.TestCase):
    def test_big_text_and_shift(self):
        lay = Layout('t')
        width = lay.big('72°', 100, 100, 200)
        self.assertGreater(width, 200)
        self.assertEqual(len(lay.items), 3)
        moved = lay.shifted(5, -3)
        self.assertEqual(moved.items[0][1:3], (lay.items[0][1] + 5, lay.items[0][2] - 3))

    def test_map_specs(self):
        specs = scenes.map_specs(defaults(scene_national=1, scene_satellite=1))
        self.assertEqual(set(specs), {'local', 'regional', 'national', 'satellite', 'future'})
        self.assertEqual(specs['local'].view.zoom, 8)
        self.assertEqual(specs['regional'].view.zoom, 6)
        self.assertTrue(specs['regional'].warnings)
        self.assertEqual(specs['future'].future, 18 * 60)
        self.assertNotIn('future', scenes.map_specs(defaults(future_source=4)))
        # Outside HRRR coverage, Auto drops the future scene.
        self.assertNotIn('future', scenes.map_specs(defaults(lat=52.37, lon=4.9, scene_future=2)))


class Settings(unittest.TestCase):
    def test_settings_xml_in_sync(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screensaver.skywatch', 'resources',
                            'settings.xml')
        with open(path) as f:
            xml = f.read()
        for s in config.all_settings():
            self.assertIn('id="%s"' % s['id'], xml)

    def test_read_falls_back(self):
        def bad(_key):
            raise ValueError
        out = config.read({'boolean': bad, 'integer': lambda k: 999, 'number': bad, 'string': lambda k: ''})
        self.assertEqual(out['zoom'], 12)          # slider clamped
        self.assertEqual(out['basemap'], 0)        # option out of range -> default


if __name__ == '__main__':
    unittest.main()

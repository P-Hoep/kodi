"""Unit tests for the Kodi-free modules. Run: python3 -m unittest discover tests
Set LIVE=1 to also hit the real feeds."""

import os
import struct
import sys
import tempfile
import unittest

ADDON = os.path.join(os.path.dirname(__file__), '..', 'screensaver.godseye.map')
sys.path.insert(0, ADDON)
sys.path.insert(0, os.path.join(ADDON, 'resources', 'lib'))  # vendored sgp4, as default.py does

from resources.lib import clouds, geo, gtfs_rt, layers, looks, motion, png, tiles, weather  # noqa: E402


class GeoTest(unittest.TestCase):
    def test_round_trip(self):
        for lat, lon, z in ((37.6213, -122.379, 9), (-33.86, 151.2, 14), (0, 0, 2), (51.5, -0.12, 18)):
            x, y = geo.to_pixel(lat, lon, z)
            lat2, lon2 = geo.from_pixel(x, y, z)
            self.assertAlmostEqual(lat, lat2, places=6)
            self.assertAlmostEqual(lon, lon2, places=6)

    def test_center_is_screen_center(self):
        x, y = geo.Viewport(37.6213, -122.379, 9).screen_xy(37.6213, -122.379)
        self.assertAlmostEqual(x, 960, places=3)
        self.assertAlmostEqual(y, 540, places=3)

    def test_tiles_cover_screen(self):
        v = geo.Viewport(37.6213, -122.379, 9)
        t = v.tiles_at(19)
        self.assertTrue(len(t) <= v.max_tiles())
        self.assertTrue(min(s[3] for s in t) <= 0 and max(s[3] for s in t) + 256 >= 1920)
        self.assertTrue(min(s[4] for s in t) <= 0 and max(s[4] for s in t) + 256 >= 1080)

    def test_overzoom_uses_enlarged_parent_tiles(self):
        v = geo.Viewport(37.6213, -122.379, 12)
        t = v.tiles_at(9)
        self.assertTrue(all(s[0] == 9 and s[5] == 2048 for s in t))
        self.assertTrue(1 <= len(t) <= 4)
        self.assertTrue(min(s[3] for s in t) <= 0 and max(s[3] + s[5] for s in t) >= 1920)

    def test_antimeridian_wrap(self):
        v = geo.Viewport(0, 179.9, 6)
        x, _y = v.screen_xy(0, -179.9)
        self.assertTrue(960 < x < 1000, x)
        tx = set(s[1] for s in v.tiles_at(19))
        self.assertIn(0, tx)
        self.assertIn((1 << 6) - 1, tx)

    def test_pan_keeps_inside_world(self):
        v = geo.Viewport(84, 0, 4)
        v.pan(0, -10000)
        self.assertGreaterEqual(v.origin[1], -1)

    def test_radius(self):
        self.assertTrue(100 < geo.Viewport(37.6, -122.4, 9).radius_km() < 400)


def _pb_varint(n):
    out = b''
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out += bytes([b | 0x80])
        else:
            return out + bytes([b])


def _pb_field(number, wire, payload):
    key = _pb_varint(number << 3 | wire)
    if wire == 2:
        return key + _pb_varint(len(payload)) + payload
    return key + payload


class GtfsRtTest(unittest.TestCase):
    def test_vehicle_position(self):
        position = (_pb_field(1, 5, struct.pack('<f', 42.35)) + _pb_field(2, 5, struct.pack('<f', -71.06))
                    + _pb_field(3, 5, struct.pack('<f', 90.0)))
        trip = _pb_field(5, 2, b'Red')
        desc = _pb_field(1, 2, b'veh1') + _pb_field(2, 2, b'1801')
        vehicle = (_pb_field(1, 2, trip) + _pb_field(2, 2, position) + _pb_field(5, 0, _pb_varint(1700000000))
                   + _pb_field(8, 2, desc))
        entity = _pb_field(1, 2, b'e1') + _pb_field(4, 2, vehicle)
        feed = _pb_field(1, 2, _pb_field(1, 2, b'2.0')) + _pb_field(2, 2, entity)
        v = gtfs_rt.vehicle_positions(feed)
        self.assertEqual(len(v), 1)
        self.assertAlmostEqual(v[0]['lat'], 42.35, places=4)
        self.assertEqual((v[0]['route'], v[0]['id'], v[0]['label'], v[0]['bearing']), ('Red', 'veh1', '1801', 90.0))


class GlideTest(unittest.TestCase):
    def _bus(self, lat, lon):
        return layers.Item('bus1', 'transit', lat, lon, 'Bus', 'vehicle', 'FFFFFFFF', heading=0.0)

    def test_glides_from_drawn_position_to_new_fix(self):
        g = motion.Glider()
        first = self._bus(45.0, -93.0)
        g.update([first], now=0.0, duration=30.0)
        self.assertEqual(g.position(first, 10.0), (45.0, -93.0))  # new vehicle appears in place
        second = self._bus(45.0, -92.99)  # moved east
        g.update([second], now=30.0, duration=30.0)
        self.assertEqual(g.position(second, 30.0), (45.0, -93.0))  # starts where it was drawn
        lat, lon = g.position(second, 45.0)
        self.assertAlmostEqual(lon, -92.995, places=6)  # halfway
        self.assertEqual(g.position(second, 90.0), (45.0, -92.99))  # holds at the fix
        self.assertAlmostEqual(second.heading, 90.0, places=1)  # faces its direction of travel

    def test_update_mid_glide_continues_smoothly(self):
        g = motion.Glider()
        g.update([self._bus(0.0, 0.0)], now=0.0, duration=30.0)
        g.update([self._bus(0.0, 0.001)], now=30.0, duration=30.0)  # ~110 m per refresh
        drawn = g.position(self._bus(0.0, 0.001), 45.0)  # halfway: lon 0.0005
        third = self._bus(0.0, 0.002)
        g.update([third], now=45.0, duration=30.0)  # early refresh
        self.assertEqual(g.position(third, 45.0), drawn)  # no jump

    def test_implausible_jump_reappears_instead_of_gliding(self):
        g = motion.Glider()
        g.update([self._bus(45.0, -93.0)], now=0.0, duration=30.0)
        far = self._bus(45.05, -93.0)  # 5.6 km in 30 s
        g.update([far], now=30.0, duration=30.0)
        self.assertEqual(g.position(far, 30.0), (45.05, -93.0))

    def test_stopped_vehicle_keeps_bearing_and_missing_ones_drop(self):
        g = motion.Glider()
        a = self._bus(1.0, 1.0)
        a.heading = 123.0
        g.update([a], now=0.0, duration=30.0)
        b = self._bus(1.0, 1.0)
        b.heading = 123.0
        g.update([b], now=30.0, duration=30.0)
        self.assertEqual(b.heading, 123.0)
        g.update([], now=60.0, duration=30.0)
        self.assertEqual(g.tracks, {})


class WeatherTest(unittest.TestCase):
    def test_parse_open_meteo(self):
        w = weather.parse({'current': {'temperature_2m': 77.6, 'apparent_temperature': 72.2,
                                       'relative_humidity_2m': 36, 'weather_code': 61,
                                       'wind_speed_10m': 12.7, 'wind_direction_10m': 185},
                           'daily': {'temperature_2m_max': [88.1], 'temperature_2m_min': [59.4],
                                     'sunrise': ['2026-10-10T07:22'], 'sunset': ['2026-10-10T18:37']}})
        self.assertEqual(w['temp'], '78°F')
        self.assertEqual(w['condition'], 'Light rain')
        self.assertEqual(w['feels_hi_lo'], 'Feels 72°   ·   H 88°  L 59°')
        self.assertEqual(w['wind_humidity'], 'Wind 13 mph S   ·   Humidity 36%')
        self.assertEqual(w['sun'], 'Sunrise 7:22   ·   Sunset 18:37')

    def test_parse_handles_missing_fields(self):
        w = weather.parse({}, imperial=False)
        self.assertEqual(w['temp'], '--C')
        self.assertEqual(w['sun'], 'Sunrise --   ·   Sunset --')

    def test_moon_matches_usno_phases(self):
        import calendar
        # USNO phase times for October 2026 (aa.usno.navy.mil/api/moon/phases).
        cases = [((2026, 10, 10, 15, 50), 'New moon'), ((2026, 10, 18, 16, 12), 'First quarter'),
                 ((2026, 10, 26, 4, 12), 'Full moon'), ((2026, 11, 1, 20, 28), 'Last quarter')]
        for when, name in cases:
            m = weather.moon(calendar.timegm(when + (0,)))
            self.assertEqual(m['name'], name, when)
        full = weather.moon(calendar.timegm((2026, 10, 26, 4, 12, 0)))
        self.assertGreater(full['illumination'], 0.99)
        self.assertEqual(full['frame'], 15)


def _png(color_type, palette=None):
    import zlib as z

    def chunk(kind, body):
        return struct.pack('>I4s', len(body), kind) + body + struct.pack('>I', z.crc32(kind + body) & 0xFFFFFFFF)
    out = looks.PNG_SIGNATURE + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 1, 8, color_type, 0, 0, 0))
    if palette:
        out += chunk(b'PLTE', bytes(c for rgb in palette for c in rgb))
    width = 2 if color_type == 3 else 6
    out += chunk(b'IDAT', z.compress(b'\x00' + bytes(range(width))))
    return out + chunk(b'IEND', b'')


class LooksTest(unittest.TestCase):
    def test_palette_recolor_rewrites_only_the_palette(self):
        src = _png(3, palette=[(170, 211, 223), (232, 146, 162)])  # OSM water, motorway pink
        out = looks.recolor_palette_png(src, looks.white_hot)
        self.assertIsNotNone(out)
        self.assertEqual(len(out), len(src))
        plte = out.index(b'PLTE')
        self.assertEqual(out[plte + 4:plte + 10], bytes([31, 31, 31, 247, 247, 247]))  # water cold, road hot
        # Every chunk CRC must still be valid, or Kodi refuses the tile.
        import zlib as z
        i = 8
        while i < len(out):
            n, kind = struct.unpack('>I4s', out[i:i + 8])
            crc = struct.unpack('>I', out[i + 8 + n:i + 12 + n])[0]
            self.assertEqual(crc, z.crc32(kind + out[i + 8:i + 8 + n]) & 0xFFFFFFFF, kind)
            i += 12 + n

    def test_non_palette_images_are_left_alone(self):
        self.assertIsNone(looks.recolor_palette_png(_png(2), looks.noir))
        self.assertIsNone(looks.recolor_palette_png(b'\xff\xd8\xff jpeg', looks.noir))

    def test_ironbow_ramp_ends(self):
        self.assertEqual(looks.ironbow(0.0), (0, 0, 0))
        self.assertEqual(looks.ironbow(1.0), (255, 255, 255))
        self.assertEqual(looks.ironbow(0.5), (219, 26, 46))

    def test_recolor_looks_use_their_own_cache_folder(self):
        src = tiles.recolored(tiles.OSM, looks.by_index(3))
        self.assertEqual(src.id, 'osm-flir_white')
        self.assertIs(looks.by_index(99), looks.LOOKS[0])


class CloudsTest(unittest.TestCase):
    def test_png_round_trip(self):
        pixels = [(10, 20, 30, 40), (50, 60, 70, 80), (90, 100, 110, 120), (130, 140, 150, 160)]
        self.assertEqual(png.decode(png.encode_rgba(2, 2, pixels)), (2, 2, pixels))

    def test_clouds_only_keeps_cold_tops(self):
        thresholds = clouds.GOES[3]
        data = clouds.clouds_only(3, 1, [(80, 80, 80, 255), (145, 145, 145, 255), (230, 230, 230, 255)], thresholds)
        _w, _h, out = png.decode(data)
        self.assertEqual(out[0][3], 0)                 # clear ground: transparent
        self.assertTrue(0 < out[1][3] < 230)           # thin cloud: partial
        self.assertEqual(out[2][3], 230)               # cold cloud top: (nearly) opaque white
        self.assertEqual(out[2][:3], (255, 255, 255))

    def test_request_covers_the_screen_with_margin(self):
        url, rect, thresholds = clouds.request(geo.Viewport(44.9, -93.3, 9))
        self.assertIn('goes_longwave_imagery', url)
        self.assertEqual(rect[:2], (-clouds.MARGIN_PX, -clouds.MARGIN_PX))
        self.assertEqual(rect[2], 1920 + 2 * clouds.MARGIN_PX)
        _url, _rect, _t = clouds.request(geo.Viewport(44.9, -93.3, 4))
        self.assertIn('global_longwave_imagery_mosaic', _url)  # wider than GOES coverage
        _url, _rect, _t = clouds.request(geo.Viewport(50.0, 10.0, 9))
        self.assertIn('global_longwave_imagery_mosaic', _url)  # outside the Americas


class ParserTest(unittest.TestCase):
    def test_adsblol(self):
        items = layers.parse_adsblol({'ac': [
            {'hex': 'a254dd', 'flight': 'UAL949  ', 'r': 'N24979', 't': 'B789', 'alt_baro': 37000,
             'gs': 480, 'track': 161.1, 'lat': 37.8, 'lon': -122.7, 'squawk': '1766'},
            {'hex': 'ae1234', 'alt_baro': 'ground', 'lat': 37.6, 'lon': -122.4, 'dbFlags': 1},
            {'hex': 'bad'},
        ]}, 'flights')
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].label, 'UAL949  FL370')
        self.assertEqual(items[1].color, layers.ORANGE)

    def test_dead_reckoning(self):
        # 100 m/s due east for 10 s from the equator: 1000 m east, no latitude change.
        item = layers.Item('x', 'flights', 0.0, 0.0, 't', 'plane', 'FFFFFFFF', heading=90, speed=100.0, at=1000.0)
        lat, lon = item.position_at(1010.0)
        self.assertAlmostEqual(lat, 0.0, places=6)
        self.assertAlmostEqual(geo.haversine_km(0, 0, lat, lon), 1.0, places=3)
        # Never projected further than MAX_EXTRAPOLATION, never backwards, untouched without speed.
        far = item.position_at(1000.0 + 10 * layers.MAX_EXTRAPOLATION)
        self.assertAlmostEqual(geo.haversine_km(0, 0, *far), layers.MAX_EXTRAPOLATION * 0.1, places=3)
        self.assertEqual(item.position_at(900.0), (0.0, 0.0))
        parked = layers.Item('y', 'flights', 1.0, 2.0, 't', 'plane', 'FFFFFFFF', heading=90)
        self.assertEqual(parked.position_at(5000.0), (1.0, 2.0))

    def test_adsblol_fix_time(self):
        items = layers.parse_adsblol({'now': 1800000000000, 'ac': [
            {'hex': 'a1', 'lat': 1, 'lon': 2, 'alt_baro': 30000, 'gs': 400, 'track': 10, 'seen_pos': 2.5},
            {'hex': 'a2', 'lat': 1, 'lon': 2, 'alt_baro': 'ground', 'gs': 10, 'track': 10}]}, 'flights')
        self.assertEqual(items[0].at, 1800000000 - 2.5)
        self.assertAlmostEqual(items[0].speed, 400 * 0.514444, places=3)
        self.assertIsNone(items[1].speed)  # taxiing aircraft are not projected

    def test_usgs(self):
        now = 1800000000
        items = layers.parse_usgs({'features': [
            {'id': 'x', 'properties': {'mag': 4.6, 'place': 'Somewhere', 'time': (now - 600) * 1000},
             'geometry': {'coordinates': [-120, 36, 8.5]}},
            {'id': 'y', 'properties': {'mag': 0.4, 'time': now * 1000}, 'geometry': {'coordinates': [-120, 36, 1]}},
        ]}, 'quakes', min_mag=1.0, now=now)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].color, layers.RED)

    def test_transit_feeds_for_location(self):
        boston = geo.Viewport(42.36, -71.06, 11)
        self.assertEqual([f[0] for f in layers.transit_feeds_for(boston)], ['mbta'])
        self.assertEqual(layers.transit_feeds_for(geo.Viewport(37.6, -122.4, 9)), [])
        custom = layers.transit_feeds_for(geo.Viewport(37.6, -122.4, 9), 'https://example.org/vp.pb')
        self.assertEqual(custom[0][5], 'https://example.org/vp.pb')

    def test_overlays_follow_settings(self):
        ids = [s.id for s, _a in tiles.overlays({'layer_radar': True, 'layer_rail': True, 'layer_traffic': True,
                                                 'layer_clouds': True, 'tomtom_key': ''})]
        self.assertEqual(ids, ['rail', 'radar'])  # traffic needs a key
        ids = [s.id for s, _a in tiles.overlays({'layer_traffic': True, 'tomtom_key': 'k'})]
        self.assertEqual(ids, ['tomtom-flow'])

    def test_satellite_position(self):
        # Sanity check with ISS-like elements: inclination bounds the latitude, altitude is low orbit.
        l1 = '1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9005'
        l2 = '2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391428256'
        from sgp4.api import Satrec, jday
        sat = Satrec.twoline2rv(l1, l2)
        jd, fr = jday(2024, 1, 1, 12, 0, 0)
        _e, r, _v = sat.sgp4(jd, fr)
        lat, lon, alt = layers.teme_to_geodetic(r, jd, fr)
        self.assertTrue(-51.7 <= lat <= 51.7)
        self.assertTrue(300 < alt < 450, alt)


@unittest.skipUnless(os.environ.get('LIVE'), 'set LIVE=1 to hit real feeds')
class LiveTest(unittest.TestCase):
    def test_layers(self):
        settings = {'quake_period': 0, 'quake_min_mag': 1, 'satellite_group': 1, '_cache_dir': tempfile.mkdtemp()}
        sf = geo.Viewport(37.6213, -122.379, 9)
        boston = geo.Viewport(42.36, -71.06, 11)
        world = geo.Viewport(20, 0, 2)
        for cls, view in ((layers.FlightsLayer, sf), (layers.MilitaryLayer, sf), (layers.QuakesLayer, sf),
                          (layers.CyclonesLayer, sf), (layers.TransitLayer, boston),
                          (layers.SatellitesLayer, world)):
            items = cls(settings).fetch(view)
            print('%-11s %4d items  e.g. %s' % (cls.id, len(items), items[0].title if items else '-'))
            if cls is not layers.CyclonesLayer:
                self.assertTrue(items, cls.id)


if __name__ == '__main__':
    unittest.main()

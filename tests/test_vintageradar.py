"""Offline tests for the Vintage Radar library's pure Python modules (no Kodi needed).

Run with:  python3 -m unittest tests.test_vintageradar -v
"""

import math
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(os.path.dirname(HERE), 'script.module.vintageradar')
MEDIA = os.path.join(ADDON, 'resources', 'media')
LIB = os.path.join(ADDON, 'lib')
if LIB not in sys.path:
    sys.path.insert(0, LIB)

# config.read imports xbmcaddon at module load; nothing else here needs Kodi, so provide a
# module object that the test can swap out.
if 'xbmcaddon' not in sys.modules:
    sys.modules['xbmcaddon'] = types.ModuleType('xbmcaddon')

from vintageradar import config, fontdraw, pngcodec, radar_core, radar_feed, theme


def feed_json(*aircraft):
    import json
    return json.dumps({'now': 1700000000000, 'ac': list(aircraft)})


def plane(hex_value='abc123', flight='TEST1', lat=0.0, lon=0.3, **values):
    item = {'hex': hex_value, 'flight': flight, 'lat': lat, 'lon': lon,
            'alt_baro': 10000, 'gs': 200, 'track': 90, 'seen_pos': 1.0}
    item.update(values)
    return item


class GeometryTests(unittest.TestCase):
    def test_distance_and_bearing(self):
        self.assertAlmostEqual(radar_core.distance_m((0, 0), (0, 0)), 0.0, places=3)
        distance = radar_core.distance_m((0, 0), (0, 1))
        self.assertAlmostEqual(distance, 111195.0, delta=50.0)
        self.assertAlmostEqual(radar_core.bearing_deg((0, 0), (0, 1)), 90.0, delta=0.1)
        self.assertAlmostEqual(radar_core.bearing_deg((0, 0), (1, 0)), 0.0, delta=0.1)

    def test_destination_round_trip(self):
        lat, lon = radar_core.destination(44.9, -93.3, 73.0, 25000.0)
        back = radar_core.distance_m((44.9, -93.3), (lat, lon))
        self.assertAlmostEqual(back, 25000.0, delta=2.0)
        self.assertAlmostEqual(radar_core.bearing_deg((44.9, -93.3), (lat, lon)), 73.0,
                               delta=0.1)

    def test_east_north(self):
        east, north = radar_core.east_north_m((0, 0), (0, 1))
        self.assertAlmostEqual(east, 111195.0, delta=50.0)
        self.assertAlmostEqual(north, 0.0, delta=1.0)

    def test_angle_helpers(self):
        self.assertAlmostEqual(radar_core.normalize_deg(-10), 350.0)
        self.assertAlmostEqual(radar_core.angle_delta(350, 10), 20.0)
        self.assertAlmostEqual(radar_core.angle_delta(10, 350), -20.0)
        self.assertTrue(radar_core.crossed_deg(350.0, 10.0, 0.0))
        self.assertFalse(radar_core.crossed_deg(10.0, 20.0, 0.0))


class ParseTests(unittest.TestCase):
    def test_adsblol_fields(self):
        text = feed_json(plane(
            baro_rate=-640, geom_rate=-600, nav_altitude_mcp=10016, nav_heading=88.5,
            nav_qnh=1013.6, ias=240, tas=270, mach=0.52, mag_heading=87.0,
            true_heading=89.0, seen=0.4, rssi=-12.5, nac_p=9, nac_v=2, sil=3, nic=8,
            rc=186, messages=1234, version=2, dbFlags=1, alert=True, spi=True,
            squawk='1200', r='N12345', t='B738', category='A3', type='adsb_icao',
            alt_geom=10250, emergency='none'))
        feed = radar_core.parse_adsblol(text)
        self.assertEqual(feed.source, 'adsb.lol')
        self.assertEqual(feed.total, 1)
        ac = feed.aircraft[0]
        self.assertEqual(ac.hex, 'abc123')
        self.assertEqual(ac.flight, 'TEST1')
        self.assertEqual(ac.reg, 'N12345')
        self.assertEqual(ac.type_code, 'B738')
        self.assertEqual(ac.category, 'A3')
        self.assertEqual(ac.squawk, '1200')
        self.assertTrue(ac.has_alt and ac.has_gs and ac.has_track)
        self.assertTrue(ac.has_baro_rate and ac.has_geom_rate)
        self.assertEqual(ac.baro_rate_fpm, -640)
        self.assertEqual(ac.nav_alt_ft, 10016)
        self.assertTrue(ac.has_nac_p and ac.has_rc)
        self.assertEqual(ac.messages, 1234)
        self.assertTrue(ac.military and ac.alert and ac.spi)
        self.assertTrue(ac.has_true_heading and ac.has_mag_heading)

    def test_ground_and_filters(self):
        feed = radar_core.parse_adsblol(feed_json(
            plane(hex_value='aaa111', lat=0.0, lon=0.0, alt_baro='ground', gs=12),
            plane(hex_value='bbb222', lat=0.0, lon=0.2, alt_baro=None, alt_geom=5000),
            plane(hex_value='ccc333', lat=0.0, lon=0.3, alt_baro=500),
        ))
        self.assertTrue(feed.aircraft[0].on_ground)
        self.assertTrue(feed.aircraft[1].has_alt)
        self.assertEqual(feed.aircraft[1].alt_ft, 5000)
        settings = radar_core.Settings(lat=0.0, lon=0.0, show_ground=False, min_altitude=2)
        model = radar_core.Model(settings)
        model.apply_feed(feed, 100.0)
        model.update(100.0)
        # Only the 5000 ft aircraft clears the 5000 ft floor.
        self.assertEqual(model.in_range_count, 1)
        self.assertEqual(model.contacts[model.order[0]].ac.hex, 'bbb222')

        settings = radar_core.Settings(lat=0.0, lon=0.0, show_ground=True,
                                       min_altitude=0, max_contacts=10)
        model = radar_core.Model(settings)
        model.apply_feed(feed, 100.0)
        model.update(100.0)
        names = set(model.contacts[index].ac.hex for index in model.order)
        self.assertIn('aaa111', names)

    def test_opensky(self):
        text = ('{"time": 1700000000, "states": ['
                '["abc123", "TEST1", "United States", 1700000000, 1700000000, 0.3, 0.0, '
                '10000.0, false, 200.0, 90.0, 0.0, null, 10000.0, "1200", false, 0],'
                '["def456", "TEST2", null, 1700000000, 1700000000, 0.4, 0.1, null, '
                'true, 0.0, 0.0, 0.0, null, null, "7000", false, 0]]}')
        feed = radar_core.parse_opensky(text)
        self.assertEqual(feed.source, 'OpenSky')
        self.assertEqual(len(feed.aircraft), 2)
        first = feed.aircraft[0]
        self.assertTrue(first.has_pos and first.has_alt and first.has_gs)
        self.assertEqual(first.squawk, '1200')
        self.assertTrue(feed.aircraft[1].on_ground)


class ModelTests(unittest.TestCase):
    def make_model(self, aircraft, **values):
        settings = radar_core.Settings(lat=0.0, lon=0.0, range_km=60, **values)
        model = radar_core.Model(settings)
        model.set_page_rows(12)
        model.apply_feed(radar_core.parse_adsblol(feed_json(*aircraft)), 100.0)
        model.reset_clock(100.0)
        model.update(100.0)
        return model

    def test_order_nearest_first_and_spotlight(self):
        model = self.make_model([
            plane(hex_value='aaa111', flight='FAR', lat=0.0, lon=0.4),
            plane(hex_value='bbb222', flight='NEAR', lat=0.0, lon=0.1),
            plane(hex_value='ccc333', flight='MID', lat=0.0, lon=0.25),
        ])
        self.assertEqual([model.contacts[i].ac.hex for i in model.order],
                         ['bbb222', 'ccc333', 'aaa111'])
        self.assertEqual(model.spotlight_hex, 'bbb222')
        self.assertTrue(model.contacts[model.order[0]].selected)

    def test_step_and_pin(self):
        model = self.make_model([
            plane(hex_value='aaa111', flight='A', lat=0.0, lon=0.1),
            plane(hex_value='bbb222', flight='B', lat=0.0, lon=0.2),
        ])
        model.step_spotlight(1)
        self.assertEqual(model.spotlight_hex, 'bbb222')
        self.assertTrue(model.pinned)
        model.step_spotlight(1)
        self.assertEqual(model.spotlight_hex, 'aaa111')
        model.unpin()
        self.assertFalse(model.pinned)

    def test_auto_rotation(self):
        model = self.make_model([
            plane(hex_value='aaa111', flight='A', lat=0.0, lon=0.1),
            plane(hex_value='bbb222', flight='B', lat=0.0, lon=0.2),
        ], detail_seconds=4)
        model.update(102.0)  # 2 s
        self.assertEqual(model.spotlight_hex, 'aaa111')
        model.update(105.0)  # another 3 s, past the 4 s timer
        self.assertEqual(model.spotlight_hex, 'bbb222')

    def test_echo_on_sweep_crossing(self):
        model = self.make_model([
            plane(hex_value='aaa111', flight='EAST', lat=0.0, lon=0.1),
        ], sweep_seconds=6)
        contact = model.contacts[model.order[0]]
        self.assertAlmostEqual(contact.bearing_deg, 90.0, delta=0.5)
        model.update(102.0)  # sweep is now at 120 degrees, crossing the 090 bearing
        self.assertGreaterEqual(contact.echo_count, 1)
        self.assertTrue(contact.echoes[0].active)

    def test_feed_error_and_stale(self):
        model = self.make_model([plane()])
        model.apply_error('no signal', 100.0)
        self.assertEqual(model.feed_error, 'no signal')
        self.assertFalse(model.stale(100.0))
        self.assertTrue(model.stale(1000.0))

    def test_empty_model(self):
        model = self.make_model([])
        self.assertEqual(model.order, [])
        self.assertEqual(model.page_count(), 1)
        self.assertIsNone(model.spotlight())


class FormattingTests(unittest.TestCase):
    def test_altitude_speed_distance(self):
        ac = radar_core.Aircraft()
        ac.has_alt = True
        ac.alt_ft = 18500
        ac.has_gs = True
        ac.gs_kt = 250
        self.assertEqual(radar_core.fmt_altitude(ac, 1), 'FL185')
        self.assertEqual(radar_core.fmt_altitude(ac, 1, True), 'FL185')
        self.assertEqual(radar_core.fmt_speed(ac, 1, True), '250KT')
        self.assertEqual(radar_core.fmt_distance(5000.0, 1), '2.7 NM')
        self.assertEqual(radar_core.fmt_distance(25000.0, 0), '25 KM')

    def test_ground(self):
        ac = radar_core.Aircraft()
        ac.on_ground = True
        self.assertEqual(radar_core.fmt_altitude(ac, 1), 'GND')
        self.assertEqual(radar_core.fmt_altitude(ac, 1, True), 'GND')

    def test_vertical_rate(self):
        ac = radar_core.Aircraft()
        ac.has_baro_rate = True
        ac.baro_rate_fpm = -1203
        self.assertEqual(radar_core.fmt_vertical_rate(ac, 1), '-1205 FPM')
        self.assertEqual(radar_core.fmt_vertical_rate(ac, 1, True), '-1205FPM')
        ac.baro_rate_fpm = 10
        self.assertEqual(radar_core.fmt_vertical_rate(ac, 1), 'LEVEL')

    def test_names_and_flags(self):
        ac = radar_core.Aircraft()
        ac.hex = 'ABC123'
        self.assertEqual(radar_core.aircraft_name(ac), 'ABC123')
        ac.reg = 'n12345'
        self.assertEqual(radar_core.aircraft_name(ac), 'N12345')
        ac.flight = ' ual123 '
        self.assertEqual(radar_core.aircraft_name(ac), 'UAL123')
        ac.military = True
        ac.alert = True
        self.assertEqual(radar_core.flag_text(ac), 'MILITARY · ALERT')
        ac.squawk = '7700'
        self.assertEqual(radar_core.emergency_label(ac), 'EMERGENCY')

    def test_coordinates_and_text(self):
        self.assertEqual(radar_core.fmt_coord(44.9, True), '44.9000N')
        self.assertEqual(radar_core.fmt_coord(-93.3, False), '93.3000W')
        self.assertEqual(radar_core.fmt_deg(-10), '350°')
        self.assertEqual(radar_core.fmt_seen(1.25), '1.2 s')
        self.assertEqual(radar_core.range_short(60, 1), '32NM')
        self.assertEqual(radar_core.truncate_text('ABCDEF', 3), 'ABC')
        self.assertEqual(radar_core.fit_text(len, 'ABC', 8), 'ABC')
        self.assertEqual(radar_core.fit_text(len, 'ABCDEFGH', 5), 'AB...')


class ConfigTests(unittest.TestCase):
    class FakeAddon(object):
        def __init__(self, values):
            self.values = values

        def getSetting(self, key):
            return self.values.get(key, '')

    def test_defaults_and_mapping(self):
        settings = config.read('x', self.FakeAddon({}))
        self.assertAlmostEqual(settings.lat, 44.9031331)
        self.assertAlmostEqual(settings.lon, -93.3096136)
        self.assertEqual(settings.range_km, 60)
        self.assertEqual(settings.units, 1)
        self.assertTrue(settings.show_labels)

    def test_stored_values(self):
        settings = config.read('x', self.FakeAddon({
            'latitude': '51.5', 'longitude': '-0.1', 'range_km': '120',
            'units': '0', 'show_ground': 'true', 'theme': '2', 'dim': '35',
            'sweep_seconds': '99', 'location_name': '  London  '}))
        self.assertAlmostEqual(settings.lat, 51.5)
        self.assertAlmostEqual(settings.lon, -0.1)
        self.assertEqual(settings.range_km, 120)
        self.assertEqual(settings.units, 0)
        self.assertTrue(settings.show_ground)
        self.assertEqual(settings.theme, 2)
        self.assertEqual(settings.dim, 35)
        self.assertEqual(settings.sweep_seconds, 12)  # sanitised
        self.assertEqual(settings.location_name, 'London')


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix='vintageradar-test-')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_png_round_trip(self):
        pixels = bytearray()
        for y in range(3):
            for x in range(4):
                pixels.extend((x * 40, y * 80, 128, 255 - x * 10))
        data = pngcodec.encode_rgba(4, 3, pixels)
        width, height, decoded = pngcodec.decode(data)
        self.assertEqual((width, height), (4, 3))
        self.assertEqual(bytes(decoded), bytes(pixels))

    def test_theme_colours(self):
        palette = theme.palette(1)
        self.assertEqual(len(palette.primary), 3)
        self.assertEqual(theme.argb((1, 2, 3), 4), '04010203')

    def test_renderer_and_cache(self):
        media = MEDIA
        renderer = fontdraw.Renderer(media, self.workdir, max_entries=20)
        first = renderer.image('UAL123', 'small', (10, 200, 30), 0.4, 0.9)
        again = renderer.image('UAL123', 'small', (10, 200, 30), 0.4, 0.9)
        self.assertIs(first, again)
        self.assertTrue(os.path.exists(first.path))
        with open(first.path, 'rb') as handle:
            width, height, pixels = pngcodec.decode(handle.read())
        self.assertEqual(width, first.width)
        self.assertEqual(height, first.height)
        self.assertTrue(any(pixels[index] for index in range(3, len(pixels), 4)))

    def test_protected_images_survive_trimming(self):
        media = MEDIA
        renderer = fontdraw.Renderer(media, self.workdir, max_entries=4)
        images = []
        for index in range(12):
            images.append(renderer.image('PLANE %d' % index, 'tiny', (200, 255, 200)))
            if index == 0:
                renderer.protect([images[0].key])
        self.assertTrue(os.path.exists(images[0].path))

    def test_png_rejects_garbage(self):
        with self.assertRaises(pngcodec.PngError):
            pngcodec.decode(b'not a png')


class FeedTests(unittest.TestCase):
    def test_urls_and_radius(self):
        settings = radar_core.Settings(lat=44.9, lon=-93.3, range_km=60)
        self.assertEqual(radar_feed.fetch_radius_nm(60), 41)
        self.assertIn('/dist/41', radar_feed.adsblol_url(settings))
        url = radar_feed.opensky_url(settings)
        self.assertIn('lamin=', url)
        self.assertIn('lomax=', url)

    def test_take_without_result(self):
        pump = radar_feed.FeedPump(radar_core.Settings(), lambda url: '')
        self.assertIsNone(pump.take())

    def test_take_error(self):
        pump = radar_feed.FeedPump(radar_core.Settings(), lambda url: '')
        pump.pending_error = 'offline'
        pump.result_is_error = True
        pump.has_result = True
        self.assertEqual(pump.take(), (None, 'offline'))


if __name__ == '__main__':
    unittest.main()

"""Unit tests for God's World Map's Kodi-free modules. Run: python3 -m unittest discover tests"""

import json
import os
import sys
import tempfile
import time
import unittest
from array import array

ADDON = os.path.join(os.path.dirname(__file__), '..', 'screensaver.godsworld.map')
sys.path.insert(0, ADDON)
sys.path.insert(0, os.path.join(ADDON, 'resources', 'lib'))  # vendored sgp4, as default.py does

from resources.lib import (ascii, config, events, motion, overlays, projections, raster,  # noqa: E402
                           render, reproject, sun, world)

MEDIA = os.path.join(ADDON, 'resources', 'media')


class RasterTest(unittest.TestCase):
    def test_png_round_trip(self):
        data = bytearray(range(256)) * 4
        img = raster.decode(raster.encode_rgba(16, 16, bytes(data)))
        self.assertEqual((img.w, img.h), (16, 16))
        self.assertEqual(bytes(img.data), bytes(data))

    def test_filtered_rows(self):
        # Sub (1) and Up (2) filtered rows decode like the unfiltered original.
        import struct
        import zlib
        rows = [bytes((x * 7 + y * 3) % 256 for x in range(12)) for y in range(3)]
        raw = b'\x00' + rows[0]
        raw += b'\x01' + bytes((rows[1][x] - (rows[1][x - 3] if x >= 3 else 0)) % 256 for x in range(12))
        raw += b'\x02' + bytes((rows[2][x] - rows[1][x]) % 256 for x in range(12))

        def chunk(kind, body):
            return struct.pack('>I4s', len(body), kind) + body + struct.pack('>I', zlib.crc32(kind + body))
        png = (raster.SIGNATURE + chunk(b'IHDR', struct.pack('>IIBBBBB', 4, 3, 8, 2, 0, 0, 0))
               + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
        img = raster.decode(png)
        self.assertEqual(bytes(img.data[0::4]), b''.join(r[0::3] for r in rows))

    def test_roll(self):
        w = array('I', list(range(8)) + [99])
        self.assertEqual(list(raster.roll_words(w, 4, 2, 1)), [1, 2, 3, 0, 5, 6, 7, 4, 99])


class SunTest(unittest.TestCase):
    def test_equinox_noon_greenwich(self):
        lat, lon = sun.subsolar(time.mktime((2026, 3, 20, 12, 7, 0, 0, 0, 0)) - time.timezone)
        self.assertLess(abs(lat), 0.6)
        self.assertLess(abs(lon), 3.0)

    def test_june_solstice(self):
        lat, _lon = sun.subsolar(time.mktime((2026, 6, 21, 12, 0, 0, 0, 0, 0)) - time.timezone)
        self.assertAlmostEqual(lat, 23.44, delta=0.1)


class ProjectionTest(unittest.TestCase):
    def test_all_twelve(self):
        self.assertEqual(len(projections.ALL), 12)

    def test_forward_lands_inside_bounds(self):
        for p in projections.ALL:
            xmin, ymin, xmax, ymax = p.bounds()
            for lon, lat in ((0, 0), (100, 40), (-70, -30), (150, -60)):
                pt = p.forward(lon, lat)
                if pt is None:
                    continue
                self.assertTrue(xmin - 1e-6 <= pt[0] <= xmax + 1e-6 and ymin - 1e-6 <= pt[1] <= ymax + 1e-6,
                                '%s %s' % (p.id, (lon, lat)))

    def test_lut_matches_forward(self):
        """The pixel where forward() puts a point shows that point in the lookup table."""
        sw, sh = 360, 180
        for pid in ('robinson', 'goode', 'dymaxion', 'waterman', 'peirce', 'winkel_tripel'):
            p = projections.get(pid)
            lay = reproject.Layout(p, 480, 270)
            lut = reproject.build(p, lay.disp_w, lay.disp_h, lay.k, lay.k, sw, sh)
            for lon, lat in ((10.5, 20.5), (-60.5, -15.5), (120.5, 45.5)):
                x, y = lay.plane_to_display(*p.forward(lon, lat))
                idx = lut[int(y) * lay.disp_w + int(x)]
                self.assertNotEqual(idx, sw * sh, pid)
                v, u = divmod(idx, sw)
                self.assertLess(abs(((u + 0.5) - (lon + 180)) % 360 - 0), 3.5 if pid != 'peirce' else 6, pid)
                self.assertLess(abs((90 - v - 0.5) - lat), 3.5, pid)

    def test_globe_inverse(self):
        lon, lat = projections.Orthographic.ortho_inverse(0, 0, 30, 10)
        self.assertAlmostEqual(lon, 30)
        self.assertAlmostEqual(lat, 10)
        self.assertIsNone(projections.Orthographic.ortho_inverse(0.9, 0.9, 0, 0))


class MotionTest(unittest.TestCase):
    def test_shuffle_has_no_immediate_repeats(self):
        seq = motion.Sequence(list(range(5)), shuffle=True, seed=1)
        picks = [seq.next() for _ in range(60)]
        self.assertTrue(all(a != b for a, b in zip(picks, picks[1:])))
        self.assertEqual(set(picks[:5]), set(range(5)))

    def test_fixed_order(self):
        seq = motion.Sequence(['a', 'b', 'c'])
        self.assertEqual([seq.next() for _ in range(4)], ['a', 'b', 'c', 'a'])

    def test_modes(self):
        m = motion.Motion('flat', False, motion.ROTATE, 3, True, 0, 2000, 1000, 1920, 1080)
        self.assertEqual(m.mode, 'pan')   # interrupted maps can't rotate: pan instead
        self.assertEqual(motion.Motion('globe', True, motion.AUTO, 3, True, 0, 900, 900, 1920, 1080).mode, 'spin')

    def test_static_centre(self):
        # A rotatable map takes the centre longitude as its central meridian.
        m = motion.Motion('flat', True, motion.STATIC, 3, True, 0, 3000, 1600, 1920, 1080, -90.0)
        self.assertEqual(m.rotation(10.0), 270.0)
        # The focus point goes to mid-screen, clamped so the map still covers the screen.
        m.focus = (1500.0, 500.0)
        self.assertEqual(m.offset(0.0), (960.0 - 1500.0, 0.0))
        m.focus = (2000.0, 1000.0)
        self.assertEqual(m.offset(0.0), (960.0 - 2000.0, 540.0 - 1000.0))
        # Interrupted maps keep their meridian and only slide.
        m = motion.Motion('flat', False, motion.STATIC, 3, True, 0, 3000, 1600, 1920, 1080, -90.0)
        self.assertEqual(m.rotation(0.0), 0.0)


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        from resources.lib import sources
        self.world = world.World(MEDIA, sources.Store(os.path.join(self.tmp, 'cache')))
        self.world.load_base('bluemarble', {'daynight': True, 'lights': True})
        self.renderer = render.Renderer(self.world, os.path.join(self.tmp, 'frames'),
                                        reproject.LutCache(os.path.join(self.tmp, 'lut')), MEDIA)

    def test_map_and_ascii_frames(self):
        for pid, style in (('equal_earth', render.MAP), ('orthographic', render.ASCII_GEO),
                           ('mercator', render.ASCII_IMAGE)):
            scene = render.Scene(projections.get(pid), style, 640, 360, ascii_opts=config.ascii_options(config.defaults()))
            geo = self.renderer.prepare(scene)
            if style == render.MAP:
                path = self.renderer.render_map(geo, 30.0, set())['base']
            else:
                path = self.renderer.render_ascii(geo, 30.0, {'clouds', 'wind'}, time.time())['base']
            img = raster.read(path)
            self.assertGreater(img.w, 100)

    def test_night_is_darker_than_day(self):
        t = time.time()
        words = self.world.update_composite(t)
        s = sun.Sun(t)

        def brightness(lon, lat):
            u = int((lon + 180) % 360 / 360.0 * world.SW)
            v = int((90 - lat) / 180.0 * world.SH)
            w = words[v * world.SW + u]
            return (w & 255) + (w >> 8 & 255) + (w >> 16 & 255)
        day = sum(brightness(s.lon + d, s.lat) for d in (-5, 0, 5))
        night = sum(brightness(s.lon + 180 + d, -s.lat) for d in (-5, 0, 5))
        self.assertGreater(day, night)


class OverlayTest(unittest.TestCase):
    def test_temperature_scale(self):
        self.assertEqual(overlays.temperature_color(-100), overlays.TEMP_STOPS[0][1])
        self.assertEqual(overlays.temperature_color(100), overlays.TEMP_STOPS[-1][1])

    def test_arrow(self):
        self.assertEqual(ascii.arrow(270), '→')   # wind from the west blows east


class EventsTest(unittest.TestCase):
    def test_quakes_biggest_first(self):
        doc = {'features': [{'properties': {'mag': 3.1, 'time': 1e12, 'place': 'a'}, 'geometry': {'coordinates': [10, 20, 5]}},
                            {'properties': {'mag': 6.2, 'time': 1e12, 'place': 'b'}, 'geometry': {'coordinates': [30, -5, 9]}},
                            {'properties': {'mag': None}, 'geometry': {'coordinates': [0, 0]}}]}
        quakes = events.parse_quakes(json.dumps(doc).encode())
        self.assertEqual([q['mag'] for q in quakes], [6.2, 3.1])

    def test_iss_orbit(self):
        tle = ('ISS (ZARYA)\n1 25544U 98067A   26283.78925095  .00010839  00000+0  20582-3 0  9996\n'
               '2 25544  51.6307  88.0087 0006720 246.7167 113.3114 15.48817123589672\n')
        lat, lon = events.Orbit(tle).position(1791697000)
        self.assertLessEqual(abs(lat), 52.0)       # never beyond its inclination
        self.assertLessEqual(abs(lon), 180.0)

    def test_fire_hotspots_need_several_detections(self):
        w, h = 2048, 1024
        data = bytearray(w * h * 4)
        for (x, y) in [(100, 100), (101, 100), (100, 101), (101, 101), (102, 102), (103, 103), (102, 103), (103, 102),
                       (900, 500)]:   # a busy block and one lone detection
            data[(y * w + x) * 4:(y * w + x) * 4 + 4] = b'\xf0\x28\x28\xff'
        img, _mask = events.fire_overlay(raster.encode_rgba(w, h, bytes(data)))
        lit = sum(1 for a in img.data[3::4] if a)
        self.assertEqual(lit, 4)   # one 2 x 2 dot for the busy block, nothing for the lone one


if __name__ == '__main__':
    unittest.main()

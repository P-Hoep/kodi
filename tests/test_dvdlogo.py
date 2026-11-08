"""Offline tests for DVD Logo: the folded-plane motion, corner aiming, near misses, settings
and the generated media.

python3 -m unittest tests.test_dvdlogo
"""

import math
import os
import random
import struct
import sys
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', 'screensaver.dvdlogo')
sys.path.insert(0, ROOT)

from resources.lib import bounce, config  # noqa: E402

FIELD_W = config.W - config.LOGO_W
FIELD_H = config.H - config.LOGO_H
SPEED = 200.0


def new_motion(seed=1, width=FIELD_W, height=FIELD_H, speed=SPEED):
    rng = random.Random(seed)
    motion = bounce.Motion(width, height, speed, rng)
    motion.start(rng.uniform(0, width), rng.uniform(0, height))
    return motion


def run(motion, seconds, near_miss=False, lead=0.5, aiming=True):
    """Simulate the screensaver's loop; return corner hits and veers as (time, position)."""
    now = 0.0
    hits, veers = [], []
    while now < seconds:
        dt, kind = motion.next_leg()
        before = motion.point()
        motion.advance(dt, kind)
        after = motion.point()
        now += dt
        for name, value in (('x', after[0]), ('y', after[1])):
            if not -1e-6 <= value <= (motion.width if name == 'x' else motion.height) + 1e-6:
                raise AssertionError('left the screen at %s=%r on %s' % (name, value, kind))
        if kind == 'corner':
            hits.append((now, after))
            motion.target = None
        elif kind == 'veer':
            veers.append((now, after))
        elif kind == 'wall' and motion.target is None and aiming and not motion.turning:
            if near_miss:
                motion.aim_near_miss(lead)
            else:
                motion.aim()
        if dt <= 0:
            raise AssertionError('zero-length leg')
    return hits, veers


def distance_to_nearest_corner(p, width=FIELD_W, height=FIELD_H):
    return min(math.hypot(p[0] - x, p[1] - y)
               for x in (0.0, float(width)) for y in (0.0, float(height)))


class FoldTest(unittest.TestCase):
    def test_fold(self):
        self.assertEqual(bounce.fold(0, 100), 0)
        self.assertEqual(bounce.fold(50, 100), 50)
        self.assertEqual(bounce.fold(100, 100), 100)
        self.assertEqual(bounce.fold(150, 100), 50)
        self.assertEqual(bounce.fold(200, 100), 0)
        self.assertEqual(bounce.fold(-25, 100), 25)

    def test_start_is_diagonal(self):
        motion = new_motion()
        px, py = motion.physical_velocity()
        self.assertGreater(min(abs(px), abs(py)), 0.2 * SPEED)


class BounceTest(unittest.TestCase):
    def test_normal_bounces_stay_on_the_screen_and_on_the_walls(self):
        for seed in range(6):
            motion = new_motion(seed)
            hits, _ = run(motion, 120, aiming=False)
            self.assertEqual(hits, [], 'a plain run should not hit a corner at seed %d' % seed)

    def test_every_wall_leg_ends_on_one_wall_and_corners_on_two(self):
        after_walls = 0
        for seed in range(6):
            motion = new_motion(seed)
            now = 0.0
            while now < 120:
                dt, kind = motion.next_leg()
                motion.advance(dt, kind)
                now += dt
                x, y = motion.point()
                walls = (abs(x) < 1e-6 or abs(x - motion.width) < 1e-6,
                         abs(y) < 1e-6 or abs(y - motion.height) < 1e-6)
                if kind == 'wall':
                    self.assertEqual(sum(walls), 1, (seed, x, y))
                    after_walls += 1
                elif kind == 'corner':
                    self.assertEqual(sum(walls), 2, (seed, x, y))
        self.assertGreater(after_walls, 50)


class AimTest(unittest.TestCase):
    def test_aim_bends_by_a_little(self):
        for seed in range(20):
            motion = new_motion(seed)
            # Walk to a bounce, then aim.
            while True:
                dt, kind = motion.next_leg()
                motion.advance(dt, kind)
                if kind == 'wall':
                    break
            before = motion.physical_velocity()
            target = motion.aim(tolerance_degrees=12.0)
            if target is None:
                continue
            after = motion.physical_velocity()
            dot = (before[0] * after[0] + before[1] * after[1]) / (SPEED * SPEED)
            bend = math.degrees(math.acos(max(-1.0, min(1.0, dot))))
            self.assertLessEqual(bend, 12.0 + 1e-6, seed)

    def test_aim_reaches_the_corner(self):
        for seed in range(8):
            motion = new_motion(seed)
            hits, _ = run(motion, 60)
            self.assertGreater(len(hits), 0, 'seed %d never hit a corner' % seed)
            for _t, (x, y) in hits:
                self.assertIn(round(x, 6), (0.0, float(FIELD_W)))
                self.assertIn(round(y, 6), (0.0, float(FIELD_H)))

    def test_near_miss_never_arrives_and_veers_close_to_the_corner(self):
        for seed in range(6):
            motion = new_motion(seed)
            hits, veers = run(motion, 90, near_miss=True)
            self.assertEqual(hits, [], 'seed %d hit a corner on a fake-out' % seed)
            self.assertGreater(len(veers), 1, 'seed %d never veered' % seed)
            for _t, point in veers:
                # The swerve starts half a second out: about 100 px at this speed.
                self.assertLess(distance_to_nearest_corner(point), 140.0, seed)

    def test_near_miss_keeps_turning(self):
        motion = new_motion(4)
        motion.aim_near_miss(0.5)
        kinds = []
        now = 0.0
        while now < 60:
            dt, kind = motion.next_leg()
            motion.advance(dt, kind)
            now += dt
            kinds.append(kind)
        self.assertIn('veer', kinds)
        self.assertGreaterEqual(kinds.count('turn'), 1)


def png_size(path):
    with open(path, 'rb') as handle:
        head = handle.read(26)
    if head[:8] != b'\x89PNG\r\n\x1a\n':
        raise AssertionError('%s is not a PNG' % path)
    return struct.unpack('>II', head[16:24])


class MediaTest(unittest.TestCase):
    def test_logo_is_the_size_the_layout_expects(self):
        width, height = png_size(os.path.join(ROOT, 'resources', 'media', 'dvd.png'))
        self.assertEqual((width, height), (config.LOGO_W, config.LOGO_H))

    def test_background_texture_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, 'resources', 'media', 'white.png')))

    def test_assets(self):
        for name in ('icon.png', 'fanart.jpg', 'LICENSE.txt'):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, name)), name)


class SettingsTest(unittest.TestCase):
    def test_defaults(self):
        d = config.defaults()
        self.assertEqual((d['size'], d['speed'], d['colour_mode'], d['trick'], d['trick_every']),
                         (18, 100, config.COLOUR_CORNER, config.ALTERNATE, 10))
        self.assertEqual(d['background'], 'FF000000')
        width, height = config.logo_pixels(d)
        self.assertEqual(height, 194)
        self.assertAlmostEqual(width / float(height), config.LOGO_ASPECT, places=2)

    def test_read_falls_back_and_clamps(self):
        values = {'size': 500, 'speed': 5, 'colour_mode': 99, 'trick': 7, 'trick_every': 3,
                  'colour': '#00ff00', 'background': 'nonsense'}
        getters = {'boolean': lambda k: True,
                   'integer': lambda k: values.get(k, 0),
                   'string': lambda k: values.get(k, '')}
        s = config.read(getters)
        self.assertEqual(s['size'], 40)
        self.assertEqual(s['speed'], 20)
        self.assertEqual(s['colour_mode'], config.COLOUR_CORNER)
        self.assertEqual(s['trick'], config.ALTERNATE)
        self.assertEqual(s['trick_every'], 5)
        self.assertEqual(s['colour'], 'FF00FF00')
        self.assertEqual(s['background'], 'FF000000')

    def test_settings_xml_is_generated_from_the_table(self):
        tree = ET.parse(os.path.join(ROOT, 'resources', 'settings.xml'))
        ids = [e.get('id') for e in tree.iter('setting')]
        self.assertEqual(ids, [s['id'] for s in config.all_settings()])
        self.assertEqual(tree.getroot().find('section').get('id'), config.ADDON_ID)

    def test_strings_cover_every_label(self):
        path = os.path.join(ROOT, 'resources', 'language', 'resource.language.en_gb', 'strings.po')
        with open(path, encoding='utf-8') as handle:
            text = handle.read()
        for _title, settings in config.CATEGORIES:
            for s in settings:
                self.assertIn('msgid "%s"' % s['label'], text)
                for option in s.get('options', []):
                    self.assertIn('msgid "%s"' % option, text)

    def test_addon_metadata(self):
        tree = ET.parse(os.path.join(ROOT, 'addon.xml'))
        addon = tree.getroot()
        self.assertEqual(addon.get('id'), config.ADDON_ID)
        self.assertEqual(addon.get('version'), '1.0.0')
        ext = addon.find("extension[@point='xbmc.ui.screensaver']")
        self.assertEqual(ext.get('library'), 'default.py')
        self.assertTrue(os.path.isfile(os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i',
                                                    'screensaver-dvdlogo.xml')))


if __name__ == '__main__':
    unittest.main()

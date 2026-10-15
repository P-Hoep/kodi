"""The loading splash shared by the screensavers, with a stand-in for Kodi's xbmcgui."""

import importlib.util
import os
import sys
import time
import types
import unittest

ROOT = os.path.join(os.path.dirname(__file__), '..')
ADDONS = ['screensaver.godseye.map', 'screensaver.godsworld.map', 'screensaver.math.clock',
          'screensaver.couchstronomy', 'screensaver.skywatch', 'screensaver.livecams']


class FakeImage(object):
    def __init__(self, x, y, w, h, path, aspectRatio=0, colorDiffuse=None):
        self.path, self.visible, self.anims = path, True, []

    def setAnimations(self, anims):
        self.anims = anims

    def setVisible(self, visible):
        self.visible = visible


class FakeWindow(object):
    def __init__(self):
        self.controls = []

    def addControls(self, controls):
        self.controls.extend(controls)


def load_splash():
    sys.modules['xbmcgui'] = types.SimpleNamespace(ControlImage=FakeImage)
    path = os.path.join(ROOT, ADDONS[0], 'resources', 'lib', 'splash.py')
    spec = importlib.util.spec_from_file_location('splash_under_test', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.MIN_SECONDS, mod.FADE_OUT_MS = 0.2, 50
    return mod


class SplashTest(unittest.TestCase):
    def setUp(self):
        self.splash = load_splash()
        self.window = FakeWindow()
        self.window.addControls(['map tile'])

    def make(self, max_seconds=30.0):
        return self.splash.Splash(self.window, '/media', 'FF69F0AE', max_seconds)

    def test_goes_on_top(self):
        s = self.make()
        self.assertEqual(self.window.controls[0], 'map tile')
        self.assertEqual(self.window.controls[1:], s.controls)
        self.assertTrue(s.art.path.endswith('splash.png'))

    def test_stays_for_the_minimum_then_fades(self):
        s = self.make()
        s.done()
        s.done()   # repeated calls are harmless
        self.assertEqual(s.state, 'leaving')
        self.assertTrue(s.art.visible)
        time.sleep(0.45)
        self.assertEqual(s.state, 'gone')
        self.assertFalse(any(c.visible for c in s.controls))
        self.assertEqual(s.art.anims, [])

    def test_times_out(self):
        s = self.make(max_seconds=0.05)
        time.sleep(0.45)
        self.assertEqual(s.state, 'gone')

    def test_copies_match(self):
        texts = set()
        for addon in ADDONS:
            with open(os.path.join(ROOT, addon, 'resources', 'lib', 'splash.py')) as f:
                texts.add(f.read())
            for name in ('splash.png', 'splash_dots.png', 'white.png'):
                self.assertTrue(os.path.exists(os.path.join(ROOT, addon, 'resources', 'media', name)))
        self.assertEqual(len(texts), 1, 'resources/lib/splash.py differs between add-ons')


if __name__ == '__main__':
    unittest.main()

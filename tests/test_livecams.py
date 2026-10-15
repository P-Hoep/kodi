"""Offline tests for Live Cams: solar elevation against reference values, local time and
DST, catalogue parsing and refresh, name cleaning, selector filters, weighting and
relaxation, health score transitions, the HLS probe, the playback watchdog and the overlay.
No network, no Kodi.

python3 -m unittest tests.test_livecams
"""

import calendar
import collections
import copy
import json
import os
import random
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screensaver.livecams'))

from resources.lib import catalog, config, health, net, overlay, player, selector, sun  # noqa: E402
from resources.lib.resolvers import Options, ResolveError, hls, youtube  # noqa: E402


def utc(*args):
    return calendar.timegm(args + (0,) * (6 - len(args)))


# ---------------------------------------------------------------- fixture

def feature(name, url, lon, lat, cc='PT', env='coastal', kind='hls', status='active', requires=None,
            quality='standard', resolution='1920x1080', family='beachcam_meo', cq='exact', display=None,
            scene='beach', verified='2026-10-01T12:00:00'):
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
            'properties': {'name': name, 'url': url, 'display_name': display or name, 'country_code': cc,
                           'environment': env, 'source_family': family, 'quality_tier': quality,
                           'scene_type': scene, 'url_type': kind, 'resolution': resolution,
                           'coordinates_quality': cq, 'status': status, 'last_verified': verified,
                           'source_url_requires': requires}}


# Synthetic features shaped like streams.geojson (no records copied from the dataset).
FEATURES = [
    feature('Praia da Rocha', 'https://cams.example.pt/rocha/playlist.m3u8', -8.53, 37.12, quality='premium'),
    feature('Nazaré North Beach', 'https://cams.example.pt/nazare/playlist.m3u8', -9.07, 39.60, quality='high'),
    feature('PL - Pomorskie - Hel - Plaża Hel', 'https://cams.example.pl/hel/playlist.m3u8', 18.80, 54.61,
            cc='PL', family='opencctv', resolution='1280x720'),
    feature('Zakopane kamera na żywo WebCamera.pl zobacz live', 'https://cams.example.pl/zak/playlist.m3u8',
            19.95, 49.30, cc='PL', env='mountain', family='webcamera_pl', resolution=None),
    feature('Burleigh Beach Webcam - Australia 🎦', 'https://cams.example.au/burleigh.m3u8', 153.45, -28.09,
            cc='AU', family='worldviewstream', resolution=None),
    feature('Virginia I-95 at Exit 4', 'https://dot.example.us/i95.m3u8', -77.4, 37.5, cc='US', env='traffic',
            family='vdot', scene='traffic', resolution='640x480'),
    feature('Lake Tahoe Shore', 'https://cams.example.us/tahoe.m3u8', -120.0, 39.1, cc='US', env='lake',
            family='resortcams', status='unverified'),
    feature('Mountain Pass', 'https://cams.example.ch/pass.m3u8', 8.0, 46.5, cc='CH', env='mountain',
            family='camguide', resolution='704x576', quality='low'),
    feature('Country Centre Cam', 'https://cams.example.kg/centre.m3u8', 74.6, 41.2, cc='KG', env='urban',
            family='opencctv', cq='country_centroid'),
    feature('Skyline Page', 'https://www.example.com/webcam/page.html', 12.3, 45.4, cc='IT', kind='html_page',
            requires='token_refresh', family='skylinewebcams'),
    feature('Browser Only', 'https://cams.example.it/browser.m3u8', 12.3, 45.4, cc='IT', requires='browser',
            family='opencctv'),
    feature('Beach on YouTube', 'https://www.youtube.com/watch?v=abcDEF12345', -80.1, 25.8, cc='US',
            kind='youtube', family='youtube'),
    feature('Duplicate of Rocha', 'https://cams.example.pt/rocha/playlist.m3u8', -8.53, 37.12),
]
SOURCES = {'beachcam_meo': {'full_name': 'beachcam_meo', 'license_type': 'fair_use'},
           'vdot': {'full_name': 'Virginia Department of Transportation', 'license_type': 'public_domain'},
           'camguide': {'full_name': 'camguide', 'license_type': 'fair_use'}}


def geojson(features=FEATURES):
    return {'type': 'FeatureCollection', 'features': copy.deepcopy(features)}


def parsed():
    return catalog.parse(geojson(), catalog.parse_sources(SOURCES))[0]


def by_title(cams):
    return dict((c.title, c) for c in cams)


# ---------------------------------------------------------------- sun

class SolarElevation(unittest.TestCase):
    # Reference elevations from Couchstronomy's ephemeris (checked against JPL DE421).
    REFERENCE = [
        (52.23, 21.01, (2026, 6, 21, 10, 30), 61.168), (52.23, 21.01, (2026, 1, 15, 7, 0), 1.844),
        (38.72, -9.14, (2026, 10, 15, 18, 40), -8.889), (44.98, -93.27, (2026, 10, 15, 5, 0), -51.377),
        (-33.87, 151.21, (2026, 3, 1, 4, 0), 53.089), (-0.18, -78.47, (2026, 3, 20, 17, 15), 88.421),
        (69.65, 18.96, (2026, 12, 21, 11, 0), -3.144), (21.31, -157.86, (2026, 7, 4, 16, 0), 0.399),
    ]

    def test_against_reference(self):
        for lat, lon, t, ref in self.REFERENCE:
            self.assertAlmostEqual(sun.solar_elevation(lat, lon, utc(*t)), ref, delta=0.05, msg=(lat, lon, t))

    def test_classes(self):
        self.assertEqual(sun.classify(10), sun.DAY)
        self.assertEqual(sun.classify(-3), sun.TWILIGHT)
        self.assertEqual(sun.classify(-6), sun.TWILIGHT)
        self.assertEqual(sun.classify(-6.1), sun.NIGHT)
        self.assertEqual(sun.daylight(52.2, 21.0, utc(2026, 6, 21, 10, 30)), sun.DAY)
        self.assertEqual(sun.daylight(69.65, 18.96, utc(2026, 12, 21, 11)), sun.TWILIGHT)   # polar night noon
        self.assertEqual(sun.daylight(44.98, -93.27, utc(2026, 10, 15, 5)), sun.NIGHT)
        self.assertEqual(sun.daylight(41.2, 74.6, utc(2026, 6, 1, 6), 'country_centroid'), sun.UNKNOWN)


class LocalTime(unittest.TestCase):
    def offset(self, cc, lat, lon, *t):
        return sun.utc_offset(cc, lat, lon, utc(*t)) / 3600.0

    def test_europe(self):
        self.assertEqual(self.offset('PL', 52.2, 21.0, 2026, 1, 15), 1)
        self.assertEqual(self.offset('PL', 52.2, 21.0, 2026, 7, 1), 2)
        self.assertEqual(self.offset('PT', 38.7, -9.1, 2026, 7, 1), 1)
        self.assertEqual(self.offset('PT', 37.7, -25.7, 2026, 1, 15), -1)      # Azores
        self.assertEqual(self.offset('ES', 28.1, -15.4, 2026, 7, 1), 1)        # Canaries
        self.assertEqual(self.offset('TR', 41.0, 29.0, 2026, 7, 1), 3)

    def test_eu_switch_at_01_utc(self):
        # 2026: last Sunday of March is the 29th, of October the 25th.
        self.assertEqual(self.offset('DE', 52.5, 13.4, 2026, 3, 29, 0, 59), 1)
        self.assertEqual(self.offset('DE', 52.5, 13.4, 2026, 3, 29, 1, 0), 2)
        self.assertEqual(self.offset('DE', 52.5, 13.4, 2026, 10, 25, 0, 59), 2)
        self.assertEqual(self.offset('DE', 52.5, 13.4, 2026, 10, 25, 1, 0), 1)

    def test_americas(self):
        self.assertEqual(self.offset('US', 40.7, -74.0, 2026, 7, 1), -4)
        self.assertEqual(self.offset('US', 40.7, -74.0, 2026, 12, 1), -5)
        self.assertEqual(self.offset('US', 33.45, -112.07, 2026, 7, 1), -7)    # Phoenix: no DST
        self.assertEqual(self.offset('US', 21.3, -157.9, 2026, 7, 1), -10)     # Honolulu
        self.assertEqual(self.offset('US', 44.98, -93.27, 2026, 7, 1), -5)     # Minneapolis CDT
        self.assertEqual(self.offset('US', 34.05, -118.24, 2026, 1, 15), -8)
        self.assertEqual(self.offset('US', 40.7, -74.0, 2026, 3, 8, 6, 59), -5)  # 01:59 EST
        self.assertEqual(self.offset('US', 40.7, -74.0, 2026, 3, 8, 7, 0), -4)   # 02:00 EST -> EDT
        self.assertEqual(self.offset('PR', 18.4, -66.1, 2026, 7, 1), -4)
        self.assertEqual(self.offset('BR', -23.5, -46.6, 2026, 7, 1), -3)

    def test_southern(self):
        self.assertEqual(self.offset('AU', -33.87, 151.21, 2026, 1, 15), 11)   # Sydney summer
        self.assertEqual(self.offset('AU', -33.87, 151.21, 2026, 7, 1), 10)
        self.assertEqual(self.offset('AU', -28.09, 153.45, 2026, 1, 15), 10)   # Gold Coast: Queensland, no DST
        self.assertEqual(self.offset('AU', -31.95, 115.86, 2026, 1, 15), 8)    # Perth
        self.assertEqual(self.offset('NZ', -36.85, 174.76, 2026, 1, 15), 13)

    def test_format(self):
        t = utc(2026, 7, 1, 12, 5)
        self.assertEqual(sun.local_time('PL', 52.2, 21.0, t), '14:05')
        self.assertEqual(sun.local_time('US', 40.7, -74.0, t, twenty_four=False), '8:05 AM')
        self.assertEqual(sun.local_time('XX', 0.0, 30.0, t), '14:05')          # unknown: by longitude


# ---------------------------------------------------------------- catalogue

class Catalogue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_keeps_only_playable(self):
        cams, features = catalog.parse(geojson(), catalog.parse_sources(SOURCES))
        self.assertEqual(features, len(FEATURES))
        titles = [c.title for c in cams]
        self.assertNotIn('Skyline Page', titles)        # html_page, token refresh
        self.assertNotIn('Browser Only', titles)        # needs a browser
        self.assertEqual(len(titles), len(set(c.id for c in cams)))   # duplicate URL dropped
        self.assertEqual(len(cams), 10)
        self.assertEqual(set(c.kind for c in cams), {'hls', 'youtube'})

    def test_fields(self):
        cams = by_title(parsed())
        rocha = cams['Praia da Rocha']
        self.assertEqual((rocha.w, rocha.h, rocha.height), (1920, 1080, 1080))
        self.assertEqual((rocha.lat, rocha.lon, rocha.cc, rocha.quality), (37.12, -8.53, 'PT', 'premium'))
        self.assertEqual(rocha.verified, utc(2026, 10, 1, 12))
        self.assertEqual(rocha.id, catalog.camera_id('https://cams.example.pt/rocha/playlist.m3u8'))
        self.assertEqual(cams['Zakopane'].height, 0)

    def test_licence_block(self):
        sources = catalog.parse_sources(dict(SOURCES, camguide={'full_name': 'x', 'license_type': 'no_embed'}))
        cams, _n = catalog.parse(geojson(), sources)
        self.assertNotIn('camguide', set(c.family for c in cams))

    def test_clean_names(self):
        cases = [
            (('PL - Pomorskie - Hel - Plaża Hel', '', 'PL'), ('Plaża Hel', 'Pomorskie')),
            (('AR - Buenos Aires - Ostende - La Rambla (Ostende)', '', 'AR'), ('La Rambla (Ostende)', 'Buenos Aires')),
            (('Zakopane kamera na żywo WebCamera.pl zobacz live', '', 'PL'), ('Zakopane', '')),
            (('Andrychów na żywo. KAMERKI z turystycznych miejsc w Polsce.', '', 'PL'), ('Andrychów', '')),
            (('Burleigh Beach Webcam - Australia 🎦', 'Burleigh Beach', 'AU'), ('Burleigh Beach', '')),
            (('Live', 'Lisbon harbour, Portugal', 'PT'), ('Lisbon harbour', '')),
        ]
        for args, expected in cases:
            self.assertEqual(catalog.clean_name(*args), expected, args)

    def test_source_names(self):
        sources = catalog.parse_sources(SOURCES)
        self.assertEqual(catalog.source_name('vdot', sources), 'Virginia Department of Transportation')
        self.assertEqual(catalog.source_name('beachcam_meo', sources), 'MEO Beachcam')
        self.assertEqual(catalog.source_name('camguide-ipcamlive'), 'CamGuide')
        self.assertEqual(catalog.source_name('ipcamlive-ocean-city-md'), 'IPCamLive')
        self.assertEqual(catalog.source_name('some_new-source'), 'Some New Source')

    def fake_fetch(self, responses):
        calls = []

        def fetch(url, timeout=10, headers=None, **kw):
            calls.append((url, dict(headers or {})))
            result = responses[url].pop(0) if isinstance(responses[url], list) else responses[url]
            if isinstance(result, Exception):
                raise result
            return result
        return fetch, calls

    def big(self):
        many = [feature('Cam %d' % i, 'https://cams.example.org/%d.m3u8' % i, i * 0.1, 40.0) for i in range(120)]
        return json.dumps(geojson(many)).encode('utf-8')

    def test_refresh_etag_and_bad_downloads(self):
        url = 'https://example.org/data/streams.geojson'
        src = 'https://example.org/data/sources.json'
        good = net.Response(200, self.big(), {'ETag': '"v1"'}, url)
        fetch, calls = self.fake_fetch({url: [good, net.Response(304, b'', {}, url),
                                              net.Response(200, self.big()[:5000], {}, url),
                                              net.Response(200, json.dumps(geojson()).encode(), {}, url)],
                                        src: net.Response(200, json.dumps(SOURCES).encode(), {}, src)})
        cat = catalog.Catalog(self.tmp)
        self.assertEqual(cat.refresh(url, now=1000, fetch=fetch), 'updated')
        self.assertEqual((len(cat.cams), cat.etag, cat.fetched), (120, '"v1"', 1000))
        # Refresh with the ETag: 304 keeps the index and restarts the interval.
        self.assertEqual(cat.refresh(url, now=2000, fetch=fetch), 'unchanged')
        self.assertEqual(calls[-1][1].get('If-None-Match'), '"v1"')
        self.assertEqual(cat.fetched, 2000)
        # A truncated download and a too-small catalogue both keep the previous index.
        self.assertRaises(ValueError, cat.refresh, url, 3000, fetch)
        self.assertRaises(ValueError, cat.refresh, url, 3000, fetch)
        again = catalog.Catalog(self.tmp)
        self.assertTrue(again.load())
        self.assertEqual((len(again.cams), again.fetched, again.etag), (120, 2000, '"v1"'))
        self.assertEqual(again.cams[5].row(), cat.cams[5].row())

    def test_stale(self):
        cat = catalog.Catalog(self.tmp)
        self.assertTrue(cat.stale('u', 7, now=0))
        cat.cams, cat.url, cat.fetched = parsed(), 'u', 1000
        self.assertFalse(cat.stale('u', 7, now=1000 + 6 * 86400))
        self.assertTrue(cat.stale('u', 7, now=1000 + 8 * 86400))
        self.assertTrue(cat.stale('other', 7, now=1001))
        self.assertEqual(catalog.sources_url('https://h/x/main/streams.geojson'), 'https://h/x/main/sources.json')


# ---------------------------------------------------------------- selector

# 2026-06-21 10:30 UTC: midday in Europe, night in the Americas and Australia evening.
EURO_NOON = utc(2026, 6, 21, 10, 30)


class Selection(unittest.TestCase):
    def setUp(self):
        self.cams = parsed()
        self.s = config.defaults()

    def titles(self, s=None, relax=0, now=EURO_NOON, hl=None, hist=None):
        return sorted(c.title for c, _l in selector.candidates(self.cams, s or self.s, hl, hist, now, relax=relax))

    def test_default_pool(self):
        # Default: active, HLS, scenic (no traffic), 720p or unknown, daylight on.
        self.assertEqual(self.titles(), ['Nazaré North Beach', 'Plaża Hel', 'Praia da Rocha', 'Zakopane'])

    def test_filters(self):
        s = dict(self.s, daylight=False)
        self.assertIn('Burleigh Beach', self.titles(s))
        self.assertIn('Country Centre Cam', self.titles(s))
        self.assertNotIn('Virginia I-95 at Exit 4', self.titles(dict(s, traffic=True)))   # 480p < 720p
        self.assertIn('Virginia I-95 at Exit 4', self.titles(dict(s, traffic=True, min_res=0)))
        self.assertIn('Lake Tahoe Shore', self.titles(dict(s, unverified=True)))
        self.assertIn('Beach on YouTube', self.titles(dict(s, youtube=True)))
        self.assertEqual(self.titles(dict(s, country_mode=1, countries='pl')), ['Plaża Hel', 'Zakopane'])
        self.assertNotIn('Plaża Hel', self.titles(dict(s, country_mode=2, countries='PL, AU')))
        self.assertEqual(self.titles(dict(s, environments=[1])), ['Zakopane'])            # mountains, >= 720p
        self.assertEqual(self.titles(dict(s, environments=[1], min_res=1)), ['Mountain Pass', 'Zakopane'])

    def test_night_and_relaxation(self):
        s = dict(self.s, environments=[2])          # lakes: only Lake Tahoe, unverified, at night
        self.assertEqual(self.titles(s), [])
        sel = selector.Selector(s, rng=random.Random(1))
        self.assertEqual(sel.pool(self.cams, EURO_NOON)[1], 3)   # daylight, resolution, then unverified
        self.assertEqual(sel.draw(self.cams, now=EURO_NOON).title, 'Lake Tahoe Shore')
        s = dict(s, unverified=True)
        sel = selector.Selector(s, rng=random.Random(1))
        found, relax = sel.pool(self.cams, EURO_NOON)
        self.assertEqual((relax, [c.title for c, _l in found]), (1, ['Lake Tahoe Shore']))   # daylight relaxed
        self.assertIn('Lake Tahoe Shore', self.titles(dict(s, night=True)))                  # night allowed

    def test_relax_order(self):
        # Only 480p traffic cameras and a 576p one: the resolution step makes them eligible.
        s = dict(self.s, environments=[], traffic=True, daylight=False)
        self.assertEqual(selector.Selector(s).pool(self.cams, EURO_NOON)[1], 2)
        s = dict(self.s, environments=[0], country_mode=1, countries='US', unverified=False, daylight=False)
        self.assertEqual(selector.Selector(s).pool(self.cams, EURO_NOON), ([], 4))

    def test_health_blocks(self):
        hl = health.Health(os.path.join(tempfile.mkdtemp(), 'h.json'))
        rocha = by_title(self.cams)['Praia da Rocha']
        hl.failed(rocha, now=EURO_NOON - 60)
        self.assertNotIn('Praia da Rocha', self.titles(hl=hl))
        self.assertIn('Praia da Rocha', self.titles(hl=hl, now=EURO_NOON + 3600))

    def test_weights(self):
        s = dict(self.s, daylight=True)
        cams = by_title(self.cams)
        rocha, hel = cams['Praia da Rocha'], cams['Plaża Hel']
        self.assertAlmostEqual(selector.weight(rocha, sun.DAY, s, set(), set()), 1.5)
        self.assertAlmostEqual(selector.weight(rocha, sun.TWILIGHT, s, set(), set()), 0.9)
        self.assertAlmostEqual(selector.weight(rocha, sun.NIGHT, s, set(), set()), 0.075)
        self.assertAlmostEqual(selector.weight(rocha, sun.NIGHT, dict(s, night=True), set(), set()), 1.5)
        self.assertAlmostEqual(selector.weight(rocha, sun.DAY, s, {rocha.id}, set()), 4.5)
        self.assertAlmostEqual(selector.weight(rocha, sun.DAY, s, set(), {rocha.id}), 0.15)
        self.assertAlmostEqual(selector.weight(hel, sun.DAY, s, set(), set(), current=cams['Zakopane']), 0.5)

    def test_draw_distribution(self):
        hist = health.History(os.path.join(tempfile.mkdtemp(), 'hist.json'))
        hist.add(by_title(self.cams)['Nazaré North Beach'].id, now=EURO_NOON - 600)
        sel = selector.Selector(self.s, history=hist, rng=random.Random(7))
        counts = collections.Counter(sel.draw(self.cams, now=EURO_NOON).title for _ in range(4000))
        # Rocha (premium) > Hel and Zakopane (standard) > Nazaré (high, but shown 10 minutes ago).
        self.assertGreater(counts['Praia da Rocha'], counts['Plaża Hel'])
        self.assertGreater(counts['Zakopane'], counts['Nazaré North Beach'] * 4)
        current = by_title(self.cams)['Plaża Hel']
        picks = set(sel.draw(self.cams, current, now=EURO_NOON).title for _ in range(200))
        self.assertNotIn('Plaża Hel', picks)

    def test_daylight_share(self):
        # Acceptance: with "Prefer daylight" on, at least 90% of picks are in day or twilight.
        rng = random.Random(3)
        cams = []
        for i in range(400):
            lon = rng.uniform(-170, 170)
            cams.append(catalog.Camera('c%d' % i, 'Cam %d' % i, '', 'u%d' % i, 'hls', 'active', 'coastal', '',
                                       'standard', 1920, 1080, 'XX', rng.uniform(-50, 60), lon, 'exact', 'f%d' % (i % 9), 0))
        sel = selector.Selector(self.s, rng=random.Random(5))
        for hour in range(0, 24, 3):
            now = utc(2026, 3, 1, hour)
            lights = [selector.light_of(sel.draw(cams, now=now), now) for _ in range(300)]
            share = sum(1 for l in lights if l in (sun.DAY, sun.TWILIGHT)) / float(len(lights))
            self.assertGreaterEqual(share, 0.9, hour)


# ---------------------------------------------------------------- health

class Cam(object):
    def __init__(self, cid, family='src'):
        self.id, self.family = cid, family


class HealthScores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'health.json')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_skip_windows(self):
        h = health.Health(self.path)
        cam, t = Cam('a'), 1000000.0
        h.failed(cam, now=t)
        self.assertTrue(h.blocked(cam, t + 3599))
        self.assertFalse(h.blocked(cam, t + 3601))
        h.failed(cam, now=t + 4000)
        self.assertTrue(h.blocked(cam, t + 4000 + 86399))
        self.assertFalse(h.blocked(cam, t + 4000 + 86401))
        h.failed(cam, now=t + 100000)
        self.assertTrue(h.blocked(cam, t + 100000 + 7 * 86400 - 1))
        self.assertFalse(h.blocked(cam, t + 100000 + 7 * 86400 + 1))   # one more try after a week
        h.failed(cam, now=t + 800000)
        self.assertTrue(h.blocked(cam, t + 800000 + 6 * 86400))        # and another week if it fails
        h.healthy(cam)
        self.assertFalse(h.blocked(cam, t + 800001))

    def test_persists_and_prunes(self):
        h = health.Health(self.path)
        h.failed(Cam('a'), now=100)
        h.failed(Cam('gone'), now=100)
        h.saw_height(Cam('a'), 576, now=100)
        h.save()
        h2 = health.Health(self.path)
        self.assertEqual(h2.cams['a']['score'], 1)
        self.assertEqual(h2.known_height('a', now=200), 576)
        h2.prune(['a'], now=200)
        self.assertNotIn('gone', h2.cams)
        self.assertIn('a', h2.cams)

    def test_source_outage(self):
        h = health.Health(self.path)
        t = 5000.0
        h.started(Cam('ok1', 'big'), now=t)
        h.started(Cam('ok2', 'big'), now=t)
        self.assertFalse(h.failed(Cam('x1', 'big'), now=t + 1))
        self.assertFalse(h.failed(Cam('x2', 'big'), now=t + 2))
        self.assertTrue(h.failed(Cam('x3', 'big'), now=t + 3))       # 3 of 5 failed in the hour
        self.assertTrue(h.blocked(Cam('fresh', 'big'), t + 6 * 3600 - 10))
        self.assertFalse(h.blocked(Cam('fresh', 'big'), t + 6 * 3600 + 10))
        self.assertFalse(h.blocked(Cam('other', 'small'), t + 10))
        # Old attempts fall out of the window: two failures an hour apart don't block a source.
        h2 = health.Health(os.path.join(self.tmp, 'h2.json'))
        h2.failed(Cam('y1', 's'), now=0)
        h2.failed(Cam('y2', 's'), now=1)
        self.assertFalse(h2.failed(Cam('y3', 's'), now=4000))

    def test_history(self):
        hist = health.History(os.path.join(self.tmp, 'history.json'))
        for i in range(250):
            hist.add('c%d' % i, now=i)
        self.assertEqual(len(hist.shown), health.HISTORY_SIZE)
        self.assertEqual(hist.last(), 'c249')
        self.assertIn('c249', hist.recent(now=300))
        self.assertNotIn('c60', hist.recent(now=60 + 6 * 3600 + 1))
        self.assertTrue(hist.favourite('c249'))
        self.assertFalse(hist.favourite('c249'))
        hist.save()
        self.assertEqual(health.History(hist.path).favourites, ['c249'])


# ---------------------------------------------------------------- resolvers

MASTER = '''#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360,CODECS="avc1.4d401e,mp4a.40.2"
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720
mid/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080
https://cdn.example.org/high/index.m3u8
'''
MEDIA = '#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4.0,\nseg1.ts\n#EXTINF:4.0,\nseg2.ts\n'


class FakeCam(object):
    def __init__(self, url, w=0, h=0, kind='hls', title='Test cam'):
        self.url, self.w, self.h, self.kind, self.title = url, w, h, kind, title

    @property
    def height(self):
        return min(self.w, self.h) if self.w and self.h else 0


def fetcher(body=None, error=None, status=200, cert_only=False):
    calls = []

    def fetch(url, timeout=4, headers=None, max_bytes=0, verify=True):
        calls.append(verify)
        if cert_only and verify:
            raise net.HttpError('%s: CERTIFICATE_VERIFY_FAILED' % url, 'cert')
        if error is not None:
            raise error
        return net.Response(status, body.encode('utf-8'), {}, url)
    return fetch, calls


class Hls(unittest.TestCase):
    URL = 'https://cams.example.org/cam/playlist.m3u8'

    def test_parse_master(self):
        m = hls.parse('﻿' + MASTER, self.URL)
        self.assertEqual(len(m.variants), 3)
        self.assertEqual(m.variants[0][3], 'https://cams.example.org/cam/low/index.m3u8')
        self.assertEqual(m.variants[2][3], 'https://cdn.example.org/high/index.m3u8')
        self.assertEqual(m.height, 1080)
        self.assertEqual(hls.choose_variant(m.variants)[1:3], (1280, 720))
        self.assertEqual(hls.choose_variant(m.variants[:1])[1:3], (640, 360))

    def test_parse_media_and_rejects(self):
        self.assertEqual(hls.parse(MEDIA, self.URL).segments, 2)
        self.assertRaises(ResolveError, hls.parse, '<html>Not found</html>', self.URL)
        self.assertRaises(ResolveError, hls.parse, '#EXTM3U\n#EXT-X-VERSION:3\n', self.URL)

    def test_resolve(self):
        fetch, _calls = fetcher(MASTER)
        item = hls.resolve(FakeCam(self.URL), Options(min_height=720), fetch)
        self.assertEqual((item.url, item.height, item.properties), (self.URL, 1080, {}))
        item = hls.resolve(FakeCam(self.URL), Options(data_saver=True), fetch)
        self.assertEqual(item.url, 'https://cams.example.org/cam/mid/index.m3u8')
        item = hls.resolve(FakeCam(self.URL), Options(isa=True, data_saver=True, kodi_major=21), fetch)
        self.assertEqual(item.url, self.URL)
        self.assertEqual(item.properties, {'inputstream': 'inputstream.adaptive',
                                           'inputstream.adaptive.chooser_resolution_max': '720p'})
        item = hls.resolve(FakeCam(self.URL), Options(isa=True, kodi_major=20), fetch)
        self.assertEqual(item.properties['inputstream.adaptive.manifest_type'], 'hls')

    def test_minimum_resolution(self):
        low = MASTER.split('#EXT-X-STREAM-INF:BANDWIDTH=2500000')[0]
        fetch, _calls = fetcher(low)
        with self.assertRaises(ResolveError) as ctx:
            hls.resolve(FakeCam(self.URL), Options(min_height=720), fetch)
        self.assertEqual((ctx.exception.kind, ctx.exception.height), ('skip', 360))
        # A catalogue resolution wins over the manifest (it was already filtered by it).
        self.assertTrue(hls.resolve(FakeCam(self.URL, 1920, 1080), Options(min_height=720), fetch))

    def test_errors_and_certificates(self):
        fetch, _c = fetcher(error=net.HttpError('404', 'http', 404))
        with self.assertRaises(ResolveError) as ctx:
            hls.resolve(FakeCam(self.URL), Options(), fetch)
        self.assertEqual(ctx.exception.kind, 'http')
        fetch, _c = fetcher(error=net.HttpError('timed out', 'network'))
        with self.assertRaises(ResolveError) as ctx:
            hls.resolve(FakeCam(self.URL), Options(), fetch)
        self.assertEqual(ctx.exception.kind, 'network')
        fetch, calls = fetcher(MEDIA, cert_only=True)
        item = hls.resolve(FakeCam(self.URL), Options(isa=True), fetch)
        self.assertEqual(calls, [True, False])
        self.assertEqual((item.url, item.insecure, item.properties), (self.URL + '|verifypeer=false', True, {}))
        fetch, calls = fetcher(MEDIA, cert_only=True)
        self.assertRaises(ResolveError, hls.resolve, FakeCam(self.URL), Options(insecure=False), fetch)
        self.assertEqual(calls, [True])

    def test_youtube(self):
        self.assertEqual(youtube.video_id('https://www.youtube.com/watch?v=abcDEF12345&t=1'), 'abcDEF12345')
        self.assertEqual(youtube.video_id('https://youtu.be/abcDEF12345'), 'abcDEF12345')
        self.assertEqual(youtube.video_id('https://www.youtube.com/live/abcDEF12345?si=x'), 'abcDEF12345')
        self.assertIsNone(youtube.video_id('https://www.youtube.com/@channel/live'))
        cam = FakeCam('https://youtu.be/abcDEF12345', kind='youtube')
        item = youtube.resolve(cam, Options(youtube_installed=True))
        self.assertEqual(item.url, 'plugin://plugin.video.youtube/play/?video_id=abcDEF12345')
        with self.assertRaises(ResolveError) as ctx:
            youtube.resolve(cam, Options(youtube_installed=False))
        self.assertEqual(ctx.exception.kind, 'skip')


# ---------------------------------------------------------------- watchdog and overlay

class Watchdog(unittest.TestCase):
    def test_start_timeout(self):
        w = player.Watchdog()
        w.play(0)
        self.assertEqual(w.check(14.9), player.STARTING)
        self.assertEqual(w.check(15.1), player.FAILED)
        self.assertIn('no picture', w.reason)

    def test_start_stall_healthy(self):
        w = player.Watchdog()
        w.play(0)
        w.av_started(3)
        self.assertEqual(w.check(3.1, 0.0), player.STARTED)
        self.assertEqual(w.check(4, 1.0), player.PLAYING)
        self.assertEqual(w.check(13.9, 1.0), player.PLAYING)   # 9.9 s without progress
        self.assertEqual(w.check(14, 11.0), player.PLAYING)
        self.assertEqual(w.check(63.5, 60.0), player.HEALTHY_NOW)
        self.assertEqual(w.check(64, 61.0), player.PLAYING)
        self.assertEqual(w.check(74.5, 61.0), player.FAILED)    # 10.5 s frozen
        self.assertIn('stalled', w.reason)

    def test_errors_and_grace(self):
        w = player.Watchdog()
        w.play(100)
        w.fail('playback error', 100.5)      # the previous item's callback: ignored
        self.assertEqual(w.check(101), player.STARTING)
        w.av_started(102)
        w.fail('stream ended', 110)
        self.assertEqual(w.check(110.1, 5.0), player.FAILED)
        self.assertEqual(w.reason, 'stream ended')
        w.stop()
        w.fail('late', 120)
        self.assertEqual(w.reason, 'stream ended')


class OverlayLogic(unittest.TestCase):
    def test_on_change(self):
        o = overlay.Overlay(overlay.ON_CHANGE_MODE, burnin=True, rng=random.Random(2))
        self.assertFalse(o.visible(0))
        o.changed(100)
        self.assertTrue(o.visible(107.9))
        self.assertFalse(o.visible(108.1))
        self.assertTrue(all(abs(v) <= overlay.DRIFT for v in o.offset))
        self.assertFalse(o.tick(1000))

    def test_always_drifts(self):
        o = overlay.Overlay(overlay.ALWAYS, burnin=True, rng=random.Random(4))
        o.changed(0)
        self.assertTrue(o.visible(10 ** 6))
        self.assertFalse(o.tick(100))
        self.assertTrue(o.tick(overlay.DRIFT_PERIOD + 1))
        still = overlay.Overlay(overlay.ALWAYS, burnin=False)
        still.changed(0)
        self.assertEqual(still.offset, (0, 0))
        self.assertFalse(still.tick(10 ** 6))
        self.assertFalse(overlay.Overlay(overlay.OFF).visible(0))

    def test_card_moves(self):
        o = overlay.Overlay(burnin=True, rng=random.Random(9))
        first = o.card_position(0)
        self.assertEqual(o.card_position(30), first)
        positions = set(o.card_position(60 * k) for k in range(1, 20))
        self.assertGreater(len(positions), 10)
        self.assertTrue(all(abs(x) <= 360 and abs(y) <= 200 for x, y in positions))

    def test_texts(self):
        cams = by_title(parsed())
        t = overlay.texts(cams['Plaża Hel'], utc(2026, 7, 1, 12, 5), catalog.parse_sources(SOURCES))
        self.assertEqual(t, {'title': 'Plaża Hel', 'place': 'Pomorskie, Poland',
                             'detail': 'OpenCCTV  ·  14:05 local time'})
        t = overlay.texts(cams['Country Centre Cam'], 0)
        self.assertEqual((t['place'], t['detail']), ('Kyrgyzstan', 'OpenCCTV'))   # no local time at a centroid


class Settings(unittest.TestCase):
    def test_defaults_and_bad_values(self):
        d = config.defaults()
        self.assertEqual(d['environments'], list(range(9)))
        self.assertEqual((d['dwell'], d['min_res'], d['overlay'], d['cutoff']), (3, 2, 1, 2))
        self.assertEqual(config.DWELL_SECONDS[d['dwell']], 180)
        self.assertEqual(config.CUTOFF_SECONDS[d['cutoff']], 7200)

        def bad(_sid):
            raise ValueError
        s = config.read({'boolean': bad, 'integer': lambda sid: 99, 'number': bad, 'string': lambda sid: '',
                         'list': lambda sid: ['1', '42']})
        self.assertEqual((s['dwell'], s['environments'], s['catalog_url']), (3, [1], config.CATALOG_URL))
        self.assertEqual(config.country_codes(' pt, PL;us x  DEU'), {'PT', 'PL', 'US'})

    def test_generated_files_match(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screensaver.livecams', 'resources')
        with open(os.path.join(root, 'settings.xml')) as handle:
            xml = handle.read()
        for s in config.all_settings():
            self.assertIn('id="%s"' % s['id'], xml)
        with open(os.path.join(root, 'language', 'resource.language.en_gb', 'strings.po')) as handle:
            po = handle.read()
        for sid, text in config.STRINGS.items():
            self.assertIn('msgctxt "#%d"\nmsgid "%s"' % (sid, text), po)


if __name__ == '__main__':
    unittest.main()

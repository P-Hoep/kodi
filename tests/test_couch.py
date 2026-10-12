"""Couchstronomy: the spec's acceptance criteria that can run without Kodi.

  python3 -m unittest tests.test_couch

The accuracy tests compare against Skyfield (JPL DE421) and are skipped when skyfield is
not installed (pip install skyfield; the first run downloads de421.bsp).
"""

import calendar
import math
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screensaver.couchstronomy')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'resources', 'lib'))   # the vendored sgp4, as default.py does

from resources.lib import astro, bodies, camera, config, satellites, scene  # noqa: E402

DEG = astro.DEG
NIGHT = calendar.timegm((2026, 10, 12, 4, 0, 0))     # 23:00 CDT in Minneapolis
DAY = calendar.timegm((2026, 10, 11, 19, 0, 0))

try:
    import skyfield.api as sf
except ImportError:
    sf = None


def settings(**kw):
    s = config.defaults()
    s.update(kw)
    return s


def model(**kw):
    return scene.Model(scene.View(settings(**kw)))


class Orientation(unittest.TestCase):
    def test_centreline_is_centre(self):
        for proj in (camera.PERSPECTIVE, camera.STEREOGRAPHIC, camera.EQUIDISTANT):
            for az, tilt, rot in ((0, 0, 0), (137, 33, 0), (250, -40, 1), (90, 90, 2)):
                cam = camera.Camera(az, tilt, 60, 1920, 1080, rot, 0, proj)
                x, y = cam.project(astro.enu(math.radians(az), math.radians(tilt)))
                self.assertAlmostEqual(x, 960, places=6)
                self.assertAlmostEqual(y, 540, places=6)

    def test_azimuth_north_to_east_is_90_degrees(self):
        north = camera.Camera(0, 0, 60, 1920, 1080)
        east = camera.Camera(90, 0, 60, 1920, 1080)
        v = astro.enu(math.radians(20), math.radians(10))
        w = astro.enu(math.radians(110), math.radians(10))   # the same point turned 90 degrees
        a, b = north.project(v), east.project(w)
        self.assertAlmostEqual(a[0], b[0], places=6)
        self.assertAlmostEqual(a[1], b[1], places=6)

    def test_tilt_up_moves_centre_to_higher_altitude(self):
        for tilt in (10, 45, 80):
            cam = camera.Camera(180, tilt, 60, 1920, 1080)
            _az, alt = astro.az_alt(cam.unproject(960, 540))
            self.assertAlmostEqual(math.degrees(alt), tilt, places=6)
            _az, top = astro.az_alt(cam.unproject(960, 0))
            self.assertGreater(top, alt)

    def test_field_of_view_edges(self):
        cam = camera.Camera(180, 0, 60, 1920, 1080)
        x, _y = cam.project(astro.enu(math.radians(180 + 30), 0.0))
        self.assertAlmostEqual(x, 1920.0, places=6)       # west is to the right when facing south
        self.assertAlmostEqual(cam.vfov, 2 * math.degrees(math.atan(math.tan(math.radians(30)) * 1080 / 1920)), 6)
        self.assertIsNone(cam.project(astro.enu(0.0, 0.0)))   # behind the TV

    def test_screen_size_and_distance(self):
        self.assertAlmostEqual(camera.fov_from_screen(200, 100 / math.tan(math.radians(30))), 60.0, places=6)

    def test_rotated_screen_keeps_physical_field(self):
        cam = camera.Camera(180, 0, 40, 1920, 1080, rotation_steps=1)
        # Turned clockwise: the framebuffer's top edge is physically on the right (west,
        # facing south) and its right edge is the bottom. The 40 degrees span the TV's
        # physical width, which is the framebuffer's height.
        az, alt = astro.az_alt(cam.unproject(960, 0))
        self.assertAlmostEqual(math.degrees(az), 180 + 20, places=4)
        self.assertAlmostEqual(math.degrees(alt), 0.0, places=6)
        _az, alt_bottom = astro.az_alt(cam.unproject(1920, 540))
        half_v = math.degrees(math.atan(960 * math.tan(math.radians(20)) / 540))
        self.assertAlmostEqual(math.degrees(alt_bottom), -half_v, places=6)

    def test_roll_correction_rotates_about_centre(self):
        cam = camera.Camera(180, 0, 60, 1920, 1080, roll_deg=10)
        p = cam.project(astro.enu(math.radians(190), 0.0))
        self.assertLess(p[1], 540)   # turned clockwise: content on the right sits higher


class Rendering(unittest.TestCase):
    def test_objects_outside_frustum_are_not_drawn(self):
        sc = model(labels=2, show_lines=True, tilt=25).build(NIGHT)
        self.assertGreater(len(sc.points), 50)
        for p in sc.points:
            self.assertTrue(-20 <= p.x <= 1940 and -20 <= p.y <= 1100)

    def test_horizon_clipping(self):
        m = model(tilt=-30, refraction=False)
        sc = m.build(NIGHT)
        cam = m.view.camera
        for p in sc.points:
            _az, alt = astro.az_alt(cam.unproject(p.x, p.y))
            self.assertGreaterEqual(alt, -0.01 * DEG)
        see_through = model(tilt=-30, horizon=2).build(NIGHT)
        self.assertGreater(len(see_through.points), len(sc.points))

    def test_time_moves_the_sky(self):
        m = model()
        a = {p.key: (p.x, p.y) for p in m.build(NIGHT).points}
        b = {p.key: (p.x, p.y) for p in m.build(NIGHT + 600).points}
        common = set(a) & set(b)
        self.assertGreater(len(common), 20)
        # Ten minutes is 2.5 degrees of rotation, tens of pixels at 60 degrees: everything
        # moves, and stars rise in the east: facing south they drift to the right.
        dx = [b[k][0] - a[k][0] for k in common]
        self.assertTrue(all(d > 5 for d in dx))

    def test_daylight_hides_faint_stars(self):
        self.assertLess(model().build(DAY).limit, 0)
        self.assertGreater(len(model(daytime=1).build(DAY).points), 20)

    def test_labels_are_independent_of_the_sky(self):
        plain = model(labels=0).build(NIGHT)
        named = model(labels=2).build(NIGHT)
        self.assertEqual(len(plain.labels), 0)
        self.assertGreater(len(named.labels), 0)
        self.assertEqual([(round(p.x, 6), round(p.y, 6)) for p in plain.points],
                         [(round(p.x, 6), round(p.y, 6)) for p in named.points])
        lines_off = model(labels=2, show_lines=False).build(NIGHT)
        lines_on = model(labels=2, show_lines=True).build(NIGHT)
        self.assertEqual(len(lines_off.lines), 0)
        self.assertGreater(len(lines_on.lines), 0)

    def test_label_placement_never_overlaps(self):
        sc = model(labels=2, show_lines=True, hfov=120).build(NIGHT)
        placed = scene.place_labels(sc.labels, 1920, 1080)
        rects = [l.placed for l in placed]
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                self.assertFalse(a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3])

    def test_star_layer_renders(self):
        from resources.lib import draw
        m = model(show_lines=True, labels=2)
        sc = m.build(NIGHT)
        layer = draw.StarLayer(1920, 1080, draw.Appearance())
        raw = layer.render(sc, draw.MoonTexture(os.path.join(ROOT, 'resources', 'data', 'moon.bin')), True)
        self.assertGreater(sum(1 for a in raw[3::4 * 97] if a), 10)
        png = draw.encode_png(1920, 1080, bytes(raw))
        self.assertTrue(png.startswith(b'\x89PNG'))


class Satellites(unittest.TestCase):
    TLE = ('ISS (ZARYA)\n'
           '1 25544U 98067A   26284.17638745  .00009430  00000+0  18014-3 0  9995\n'
           '2 25544  51.6312  86.0933 0006713 248.1316 111.8959 15.48821882589734\n')

    def test_offline_with_cache_and_stale_data(self):
        folder = tempfile.mkdtemp()
        store = satellites.ElementStore(folder)
        self.assertEqual(store.load(['stations']), [])          # no data, no crash
        with open(store.path('stations'), 'w') as handle:
            handle.write(self.TLE)
        sats = store.load(['stations'])
        self.assertEqual(len(sats), 1)
        obs = satellites.Observer(44.9 * DEG, -93.3 * DEG, 260)
        epoch = sats[0].epoch_unix
        fresh = satellites.Tracker(sats, obs, 7)
        fresh.select(epoch + 2 * 86400)
        self.assertEqual(len(fresh.sats), 1)
        fresh.select(epoch + 9 * 86400)
        self.assertEqual(len(fresh.sats), 0)                   # too old: hidden, not guessed
        self.assertEqual(fresh.stale, 1)

    def test_interpolation_matches_direct_propagation(self):
        sats = satellites.parse_tle(self.TLE, 'stations')
        obs = satellites.Observer(0.0, 0.0, 0)
        tr = satellites.Tracker(sats, obs, 30)
        t0 = sats[0].epoch_unix
        tr.step = 30.0
        tr.window = (t0, t0 + 30, [(sats[0], tr._propagate(sats[0], t0), tr._propagate(sats[0], t0 + 30))])
        for k in (5, 13, 22):
            r = satellites.slerp(tr.window[2][0][1], tr.window[2][0][2], k / 30.0)
            direct = tr._propagate(sats[0], t0 + k)
            self.assertLess(astro.length(astro.sub(r, direct)), 0.5)   # km

    def test_brightness_and_shadow(self):
        self.assertLess(satellites.magnitude(-1.8, 500, math.radians(60)), -1.5)
        sun = (1.0, 0.0, 0.0)
        self.assertTrue(satellites.in_shadow((-7000.0, 0.0, 0.0), sun))
        self.assertFalse(satellites.in_shadow((-7000.0, 0.0, 6600.0), sun))


@unittest.skipIf(sf is None, 'skyfield not installed')
class Accuracy(unittest.TestCase):
    """Positions against Skyfield/DE421 for both hemispheres, day and night."""

    @classmethod
    def setUpClass(cls):
        cls.ts = sf.load.timescale()
        cls.eph = sf.load('de421.bsp')

    def test_sun_moon_planets_and_stars(self):
        names = {'Sun': 'sun', 'Moon': 'moon', 'Mercury': 'mercury', 'Venus': 'venus', 'Mars': 'mars',
                 'Jupiter': 'jupiter barycenter', 'Saturn': 'saturn barycenter',
                 'Uranus': 'uranus barycenter', 'Neptune': 'neptune barycenter'}
        sites = ((44.9778, -93.2650, 256), (-33.86, 151.21, 40), (64.1, -21.9, 0))
        dates = ((2026, 10, 11, 3, 0, 0), (2026, 10, 11, 15, 30, 0), (2028, 7, 22, 1, 0, 0))
        stars = ((6.752481, -16.716116, -546.01, -1223.08), (18.61564, 38.783692, 201.02, 287.46))
        for lat, lon, h in sites:
            obs = self.eph['earth'] + sf.wgs84.latlon(lat, lon, elevation_m=h)
            for d in dates:
                t = self.ts.utc(*d)
                fr = astro.Frame(calendar.timegm(d), lat * DEG, lon * DEG, h)
                bs = bodies.compute(fr)
                for name, key in names.items():
                    alt, az, _ = obs.at(t).observe(self.eph[key]).apparent().altaz()
                    err = astro.angle(astro.enu(az.radians, alt.radians), bs[name].hor) / astro.ARCSEC
                    self.assertLess(err, 10 if name == 'Moon' else 5, '%s %s %s' % (name, d, (lat, lon)))
                for ra, dec, pmra, pmdec in stars:
                    star = sf.Star(ra_hours=ra, dec_degrees=dec, ra_mas_per_year=pmra, dec_mas_per_year=pmdec)
                    alt, az, _ = obs.at(t).observe(star).apparent().altaz()
                    a, dd = ra * 15 * DEG, dec * DEG
                    yrs = (fr.jd_tt - astro.J2000) / 365.25
                    mas = astro.ARCSEC / 1000
                    ea = (-math.sin(a), math.cos(a), 0)
                    ed = (-math.sin(dd) * math.cos(a), -math.sin(dd) * math.sin(a), math.cos(dd))
                    u = astro.vec(a, dd)
                    u = astro.norm(tuple(u[k] + yrs * mas * (pmra * ea[k] + pmdec * ed[k]) for k in range(3)))
                    err = astro.angle(astro.enu(az.radians, alt.radians), fr.star_to_hor(u)) / astro.ARCSEC
                    self.assertLess(err, 5)

    def test_refraction_matches_skyfield(self):
        lat, lon = 44.9778, -93.2650
        obs = self.eph['earth'] + sf.wgs84.latlon(lat, lon)
        t = self.ts.utc(2026, 10, 12, 0, 0, 0)
        fr = astro.Frame(calendar.timegm((2026, 10, 12, 0, 0, 0)), lat * DEG, lon * DEG)
        moon = bodies.compute(fr)['Moon']
        alt, _az, _ = obs.at(t).observe(self.eph['moon']).apparent().altaz(temperature_C=10, pressure_mbar=1010)
        if alt.degrees > 3:
            ours = math.degrees(math.asin(astro.refract_enu(moon.hor)[2]))
            self.assertLess(abs(ours - alt.degrees) * 3600, 30)

    def test_satellite_track(self):
        sats = satellites.parse_tle(Satellites.TLE, 'stations')
        lines = Satellites.TLE.splitlines()
        ref = sf.EarthSatellite(lines[1], lines[2], 'ISS', self.ts)
        lat, lon = 44.9031, -93.3096
        obs = satellites.Observer(lat * DEG, lon * DEG, 260)
        tr = satellites.Tracker(sats, obs, 7)
        start = sats[0].epoch_unix
        checked = 0
        import datetime
        for k in range(0, 2 * 86400, 60):
            t = start + k
            tr.window = None
            tr.build(t - 7.0)
            fixes = tr.fixes(t, shadowed=True)
            if not fixes:
                continue
            when = self.ts.from_datetime(datetime.datetime.fromtimestamp(t, datetime.timezone.utc))
            alt, az, _ = (ref - sf.wgs84.latlon(lat, lon, 260)).at(when).altaz()
            err = astro.angle(astro.enu(az.radians, alt.radians), fixes[0].hor) / DEG
            self.assertLess(err, 0.02)
            checked += 1
        self.assertGreater(checked, 5)


if __name__ == '__main__':
    unittest.main()

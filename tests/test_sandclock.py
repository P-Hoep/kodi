"""Offline tests for Sand Clock: settings, fonts and layout, the falling-sand physics, the
sinking pile and its speed control, and colours.

python3 -m unittest tests.test_sandclock
"""

import datetime
import json
import os
import random
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screensaver.sandclock')
sys.path.insert(0, ROOT)

from resources.lib import config, sand  # noqa: E402

MEDIA = os.path.join(ROOT, 'resources', 'media')
FONTS_JSON = os.path.join(MEDIA, 'fonts', 'fonts.json')


def font(folder='inter', weight=2):
    return sand.Font.load(FONTS_JSON, folder, weight)


def settings(**kw):
    return dict(config.defaults(), **kw)


def run_clock(s, seconds, f=None, seed=1):
    """The screensaver's loop without Kodi: crumble every second, rebuild every 1.5 s, steer
    the sinking speed. Returns (pile, [(t, height)], [flights])."""
    f = f or font()
    g = sand.grain_px(s, f)
    grid = sand.Grid(g)
    pile = sand.Pile(grid, random.Random(seed), 0.0)
    target = sand.pile_target(s, f, g)
    inflow, heights, every, rebuild = [], [], [], 1.5
    for k in range(seconds):
        t0 = k + 1 - sand.lead(s)
        old = sand.time_text(s, 17, (52 + (k + 14) // 60) % 60, (k + 14) % 60)
        new = sand.time_text(s, 17, (52 + (k + 15) // 60) % 60, (k + 15) % 60)
        n = 0
        for i, (ch, box) in enumerate(zip(old, sand.layout(s, f, old))):
            if s['crumble'] == 1 or ch != new[i]:
                flights = pile.drop(sand.grains(f, ch, box, grid), 'FF%06X' % k, t0,
                                    sand.GRAVITY[s['gravity']], sand.SPREAD[s['speed']])
                # (start, flight, the floor's row when it lands, as planned at the drop)
                every += [(t0, fl, pile.floor_row(t0 + fl.land_ms / 1000.0)) for fl in flights]
                n += len(flights)
        inflow.append((t0, n))
        while rebuild <= k + 1:
            t = rebuild
            if pile.change and t >= pile.change[0] - 0.05:
                pile.commit(pile.change[0])
            pile.prune(t)
            h = pile.height_px(t)
            rate = sum(m for w, m in inflow if w > t - 20) * g * g / min(20.0, max(1.0, t))
            speed = sand.sink_speed(rate, h, target, pile.footprint(t))
            if pile.change is None and sand.speed_changed(speed, pile.speed):
                last = max([t0 + fl.land_ms / 1000.0 for t0, fl, _f in every[-2000:]] + [t])
                pile.schedule(t + rebuild_step(last - t), speed)
            heights.append((t, h))
            rebuild += 1.5
    return pile, heights, every, target


def rebuild_step(ahead):
    steps = 1
    while steps * 1.5 < ahead:
        steps += 1
    return steps * 1.5


class SettingsTest(unittest.TestCase):
    def test_settings_xml_is_generated_from_the_table(self):
        tree = ET.parse(os.path.join(ROOT, 'resources', 'settings.xml'))
        ids = [e.get('id') for e in tree.iter('setting')]
        self.assertEqual(ids, [s['id'] for s in config.all_settings()])

    def test_read_falls_back(self):
        values = {'font': 99, 'size': 500, 'colour': '#00ff00', 'day_start': '25:00', 'night_start': '6:5'}
        getters = {'boolean': lambda k: True, 'integer': lambda k: values[k],
                   'string': lambda k: values.get(k, '')}
        s = config.read(getters)
        self.assertEqual(s['font'], 0)
        self.assertEqual(s['size'], 95)
        self.assertEqual(s['colour'], 'FF00FF00')
        self.assertEqual(s['day_start'], '07:00')
        self.assertEqual(s['night_start'], '06:05')
        self.assertEqual(s['background'], 'FF000000')

    def test_defaults_are_the_video(self):
        d = config.defaults()
        self.assertTrue(d['seconds'])
        self.assertEqual((d['crumble'], d['colour_mode'], d['palette']), (1, config.COLOUR_EVERY_CHANGE, 0))


class FontTest(unittest.TestCase):
    def test_every_font_has_every_glyph(self):
        with open(FONTS_JSON) as handle:
            meta = json.load(handle)
        self.assertEqual(set(meta), set(folder for _l, folder in config.FONTS))
        for folder, weights in meta.items():
            self.assertEqual(set(weights), set(str(w) for w in range(len(config.WEIGHTS))))
            for w, data in weights.items():
                self.assertEqual(set(data['masks']), set('0123456789:'))
                for ch in '0123456789:':
                    name = 'colon' if ch == ':' else ch
                    path = os.path.join(MEDIA, 'fonts', folder, '%s%s.png' % (w, name))
                    self.assertTrue(os.path.exists(path), path)
                    mw, rows = data['masks'][ch]
                    self.assertTrue(any(rows), (folder, w, ch))
                    expected = data['colon_w'] if ch == ':' else data['digit_w']
                    self.assertAlmostEqual(mw / float(len(rows)), expected / float(data['h']), delta=0.02)

    def test_ink_stays_inside_the_glyph(self):
        """Old-style figures (Playfair's 9) dip below the baseline: the box must hold them."""
        for _l, folder in config.FONTS:
            f = font(folder)
            for ch, mask in f.masks.items():
                self.assertFalse(any(mask[-1]), (folder, ch, 'touches the bottom'))
                self.assertFalse(any(mask[0]), (folder, ch, 'touches the top'))

    def test_grain_textures(self):
        for look in ('sand', 'beads'):
            for n in range(1, sand.RUN_BLOCK + 1):
                for v in range(4):
                    self.assertTrue(os.path.exists(os.path.join(MEDIA, 'grains', look, '%d_%d.png' % (n, v))))


class LayoutTest(unittest.TestCase):
    def test_time_text(self):
        self.assertEqual(sand.time_text(settings(), 17, 52, 14), '17:52:14')
        self.assertEqual(sand.time_text(settings(hours=1), 17, 52, 14), '5:52:14')
        self.assertEqual(sand.time_text(settings(hours=1, seconds=False), 0, 5, 0), '12:05')
        self.assertEqual(sand.time_text(settings(seconds=False), 9, 5, 59), '09:05')

    def test_clock_fits_and_clears_the_pile(self):
        for _l, folder in config.FONTS:
            f = font(folder)
            for size in (40, 80, 95):
                for position in (0, 1):
                    for seconds in (True, False):
                        s = settings(size=size, position=position, seconds=seconds)
                        for off in ((-sand.DRIFT_PX, -sand.DRIFT_PX), (sand.DRIFT_PX, sand.DRIFT_PX)):
                            boxes = sand.layout(s, f, sand.widest_text(s), off)
                            x0, y0 = boxes[0][:2]
                            x1, y1 = boxes[-1][0] + boxes[-1][2], boxes[-1][1] + boxes[-1][3]
                            self.assertGreaterEqual(x0, 0)
                            self.assertLessEqual(x1, sand.W)
                            self.assertGreaterEqual(y0, 0)
                            g = sand.grain_px(s, f)
                            self.assertLessEqual(y1, sand.H - sand.pile_target(s, f, g), (folder, size, position))

    def test_grains_are_the_glyph(self):
        f = font()
        grid = sand.Grid(9)
        box = sand.layout(settings(), f, '88:88:88')[0]
        cells = sand.grains(f, '8', box, grid)
        self.assertGreater(len(cells), 100)
        self.assertEqual(len(set(cells)), len(cells))
        x, y, w, h = box
        for col, top in cells:
            self.assertTrue(x - 9 <= grid.x(col) <= x + w and y - 9 <= top <= y + h)
        # A 1 has less ink than an 8, and a colon less still.
        one = sand.grains(f, '1', box, grid)
        colon = sand.grains(f, ':', sand.layout(settings(), f, '88:88:88')[2], grid)
        self.assertLess(len(colon), len(one))
        self.assertLess(len(one), len(cells))

    def test_whole_clock_keeps_to_the_grain_budget(self):
        for _l, folder in config.FONTS:
            f = font(folder)
            for grain in range(3):
                s = settings(grain=grain, crumble=1)
                g = sand.grain_px(s, f)
                self.assertGreaterEqual(g, sand.GRAIN_PX[grain])
                grid = sand.Grid(g)
                text = sand.widest_text(s)
                n = sum(len(sand.grains(f, ch, b, grid)) for ch, b in zip(text, sand.layout(s, f, text)))
                if g != sand.GRAIN_PX[-1]:
                    self.assertLessEqual(n, sand.GRAIN_BUDGET)
            self.assertEqual(sand.grain_px(settings(grain=0, crumble=0), f), sand.GRAIN_PX[0])


class PhysicsTest(unittest.TestCase):
    def test_flights_add_up(self):
        """The animation pieces (fall, drift, slide) end exactly on the cell the grain books,
        and no two grains book the same cell."""
        s = settings(crumble=1)
        pile, _h, every, _t = run_clock(s, 12)
        seen = set()
        for t0, f, _floor in every:
            self.assertNotIn((f.col, f.row), seen)
            seen.add((f.col, f.row))
            self.assertEqual(f.x + f.scatter_px + f.dx, pile.grid.x(f.col))
            self.assertAlmostEqual(f.y + f.fall_px + f.dy, f.land_y, places=6)
            self.assertGreater(f.fall_px, 0)
            self.assertEqual(f.land_ms, f.delay + f.fall_ms + f.slide_ms)
            self.assertLessEqual(f.delay, 1000 * sand.SPREAD[s['speed']])

    def test_no_floating_sand(self):
        """Every grain rests on another grain or on the floor as it was when it landed."""
        pile, _h, every, _t = run_clock(settings(crumble=0), 20)
        landed = dict(((f.col, f.row), floor) for _t0, f, floor in every)
        for (col, row), floor in landed.items():
            self.assertTrue(row <= floor or (col, row - 1) in landed, (col, row))

    def test_slopes_are_dry_sand(self):
        """After a while no column stands more than one grain above both its neighbours."""
        pile, _h, _e, _t = run_clock(settings(crumble=0, gravity=2), 30)
        h = pile.heights
        spikes = [c for c in range(1, len(h) - 1) if h[c] > h[c - 1] + 1 and h[c] > h[c + 1] + 1]
        self.assertEqual(spikes, [])

    def test_sinking_is_continuous(self):
        pile = sand.Pile(sand.Grid(10), random.Random(1), 0.0)
        pile.schedule(2.0, 30.0)
        self.assertEqual(pile.sunk(1.0), 0.0)
        self.assertAlmostEqual(pile.sunk(3.0), 30.0)
        pile.commit(2.0)
        pile.schedule(4.0, 10.0)
        self.assertAlmostEqual(pile.sunk(4.0), 60.0)
        self.assertAlmostEqual(pile.sunk(5.0), 70.0)
        self.assertEqual(pile.speed_at(3.9), 30.0)
        self.assertEqual(pile.speed_at(4.1), 10.0)
        self.assertEqual(pile.floor_row(5.0), 7)

    def test_strips(self):
        pile = sand.Pile(sand.Grid(10), random.Random(1), 0.0)
        for row in range(40):
            pile.cells.setdefault(3, {})[row] = ('A' if row < 36 else 'B', 0.0)
        pile.cells[3][41] = ('B', 0.0)            # after a gap
        pile.cells[3][42] = ('B', 9.0)            # not landed yet
        self.assertEqual(pile.strips(3, 1.0), [(0, 32, 'A'), (32, 4, 'A'), (36, 4, 'B'), (41, 1, 'B')])

    def test_pile_stays_near_its_target(self):
        for crumble in (0, 1):
            s = settings(crumble=crumble, grain=2)
            _p, heights, _e, target = run_clock(s, 100)
            later = [h for t, h in heights if t > 45]
            mean = sum(later) / len(later)
            self.assertLess(abs(mean - target) / target, 0.3, (crumble, mean, target))
            self.assertLess(max(later), 1.6 * target)

    def test_sink_speed(self):
        self.assertEqual(sand.sink_speed(1e5, 0, 300, 1000), 0)
        self.assertLess(sand.sink_speed(1e5, 150, 300, 1000), sand.sink_speed(1e5, 300, 300, 1000))
        self.assertAlmostEqual(sand.sink_speed(1e5, 300, 300, 1000), 100.0)
        self.assertFalse(sand.speed_changed(52, 50))
        self.assertTrue(sand.speed_changed(70, 50))


class ColourTest(unittest.TestCase):
    def test_palettes(self):
        for _name, colours in config.PALETTES:
            self.assertGreaterEqual(len(colours), 5)
            for c in colours:
                self.assertEqual(config.valid_colour(c), 'FF' + c.upper())

    def test_pick_never_repeats(self):
        rng = random.Random(4)
        colours = sand.palette(settings(), datetime.datetime(2026, 1, 1, 12))
        last = None
        for _ in range(200):
            c = sand.pick(colours, last, rng)
            self.assertNotEqual(c, last)
            last = c

    def test_night(self):
        s = settings(night_palette=3, night_dim=50, dim=20)
        noon, late = datetime.datetime(2026, 1, 1, 12), datetime.datetime(2026, 1, 1, 23)
        self.assertEqual(sand.palette(s, noon)[0], 'FF' + config.PALETTES[0][1][0])
        self.assertEqual(sand.palette(s, late)[0], 'FF' + config.PALETTES[2][1][0])
        self.assertAlmostEqual(sand.dim_factor(s, noon), 0.8)
        self.assertAlmostEqual(sand.dim_factor(s, late), 0.4)
        self.assertEqual(sand.scale('FF804020', 0.5), 'FF402010')
        wrap = settings(day_start='22:00', night_start='06:00')
        self.assertFalse(sand.is_night(wrap, late))
        self.assertTrue(sand.is_night(wrap, noon))

    def test_rainbow(self):
        hues = set(sand.rainbow(sand.RAINBOW_SECONDS * k / 9.0) for k in range(9))
        self.assertEqual(len(hues), 9)
        self.assertEqual(sand.rainbow(0), sand.rainbow(sand.RAINBOW_SECONDS))


if __name__ == '__main__':
    unittest.main()

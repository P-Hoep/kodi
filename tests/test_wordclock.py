"""Offline tests for Word Clock: the grid, every minute's phrase, settings, colours and layout.

python3 -m unittest tests.test_wordclock
"""

import datetime
import os
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screensaver.wordclock')
sys.path.insert(0, ROOT)

from resources.lib import config, grid, look  # noqa: E402

REFERENCE = """
ITLISASAMPM
ACQUARTERDC
TWENTYFIVEX
HALFBTENFTO
PASTERUNINE
ONESIXTHREE
FOURFIVETWO
EIGHTELEVEN
SEVENTWELVE
TENSEOCLOCK
MIDNIGHTNOO
""".split()


def say(h, m, s=0, **options):
    return grid.text(grid.phrase(h, m, s, options)[0])


def every_option_set():
    for rounding in (0, 1):
        for it_is in (True, False):
            for quarter_a in (True, False):
                for ampm in (True, False):
                    for midnight in (True, False):
                        yield dict(rounding=rounding, it_is=it_is, quarter_a=quarter_a, ampm=ampm,
                                   midnight=midnight, dots=True)


class GridTest(unittest.TestCase):
    def test_grid_is_the_reference(self):
        self.assertEqual(grid.ROWS, REFERENCE)
        self.assertTrue(all(len(r) == grid.SIZE for r in grid.ROWS))
        self.assertEqual(len(grid.ROWS), grid.SIZE)

    def test_words_spell_themselves(self):
        for key in grid.WORDS:
            self.assertEqual(grid.word_letters(key), key.split('_')[-1], key)

    def test_words_do_not_overlap(self):
        seen = {}
        for key in grid.WORDS:
            for c in grid.cells(key):
                self.assertNotIn(c, seen, '%s overlaps %s' % (key, seen.get(c)))
                seen[c] = key

    def test_letters(self):
        self.assertEqual(len(grid.letters()), 24)
        self.assertNotIn('J', grid.letters())


class PhraseTest(unittest.TestCase):
    def test_reference_time(self):
        self.assertEqual(say(13, 55), 'IT IS FIVE TO TWO PM')
        words, _ = grid.phrase(13, 55)
        self.assertEqual(sorted(grid.lit_cells(words)),
                         [0, 1, 3, 4, 9, 10, 28, 29, 30, 31, 42, 43, 74, 75, 76])

    def test_spot_checks(self):
        cases = {
            (0, 0): 'IT IS MIDNIGHT', (0, 7): 'IT IS FIVE PAST MIDNIGHT',
            (23, 50): 'IT IS TEN TO MIDNIGHT', (23, 35): 'IT IS TWENTY FIVE TO MIDNIGHT',
            (12, 0): "IT IS TWELVE O'CLOCK PM", (11, 45): 'IT IS A QUARTER TO TWELVE PM',
            (11, 44): 'IT IS TWENTY TO TWELVE PM', (9, 15): 'IT IS A QUARTER PAST NINE AM',
            (9, 30): 'IT IS HALF PAST NINE AM', (21, 25): 'IT IS TWENTY FIVE PAST NINE PM',
            (6, 20): 'IT IS TWENTY PAST SIX AM', (1, 0): "IT IS ONE O'CLOCK AM",
            (10, 10): 'IT IS TEN PAST TEN AM', (16, 40): 'IT IS TWENTY TO FIVE PM',
        }
        for (h, m), expected in cases.items():
            self.assertEqual(say(h, m), expected, '%02d:%02d' % (h, m))

    def test_options(self):
        self.assertEqual(say(0, 0, midnight=False), "IT IS TWELVE O'CLOCK AM")
        self.assertEqual(say(23, 55, midnight=False), 'IT IS FIVE TO TWELVE AM')
        self.assertEqual(say(9, 15, it_is=False, quarter_a=False, ampm=False), 'QUARTER PAST NINE')

    def test_rounding(self):
        self.assertEqual(say(13, 58), 'IT IS FIVE TO TWO PM')
        self.assertEqual(say(13, 58, rounding=1), "IT IS TWO O'CLOCK PM")
        self.assertEqual(say(13, 57, 29, rounding=1), 'IT IS FIVE TO TWO PM')
        self.assertEqual(say(13, 57, 30, rounding=1), "IT IS TWO O'CLOCK PM")
        self.assertEqual(say(23, 58, rounding=1), 'IT IS MIDNIGHT')
        self.assertEqual(say(11, 58, rounding=1), "IT IS TWELVE O'CLOCK PM")

    def test_dots(self):
        for m in range(60):
            self.assertEqual(grid.phrase(8, m, 0, dict(dots=True))[1], m % 5)
            self.assertEqual(grid.phrase(8, m, 0, dict(dots=False))[1], 0)
            self.assertEqual(grid.phrase(8, m, 0, dict(dots=True, rounding=1))[1], 0)

    def test_every_minute(self):
        """Every minute and option set: words in reading order, one hour word, sensible size."""
        hour_words = set(grid.HOURS) | {'MIDNIGHT'}
        for options in every_option_set():
            for h in range(24):
                for m in range(60):
                    words, dots = grid.phrase(h, m, 0, options)
                    positions = [grid.WORDS[w][:2] for w in words]
                    self.assertEqual(positions, sorted(positions))
                    self.assertEqual(len(set(words)), len(words))
                    self.assertEqual(len([w for w in words if w in hour_words]), 1, (h, m, options))
                    self.assertLessEqual(dots, 4)
                    joins = [w for w in words if w in ('TO', 'PAST', 'OCLOCK')]
                    self.assertLessEqual(len(joins), 1)
                    if 'MIDNIGHT' not in words:
                        self.assertEqual(len(joins), 1, (h, m, options))

    def test_phrase_changes_every_five_minutes(self):
        changes = 0
        last = None
        for t in range(24 * 60):
            text = say(t // 60, t % 60)
            if text != last:
                changes += 1
                self.assertEqual(t % 5, 0, '%d:%02d' % divmod(t, 60))
            last = text
        self.assertEqual(changes, 24 * 12)


class SettingsTest(unittest.TestCase):
    def test_defaults_match_the_picture(self):
        d = config.defaults()
        self.assertEqual((d['font'], d['weight'], d['glow'], d['frame'], d['mode'], d['night_palette']),
                         (0, 0, 0, 0, 0, config.GRAPHITE))
        self.assertFalse(d['dots'])
        now = datetime.datetime(2026, 1, 1, 13, 55)
        c = look.finish(d, look.palette(d, look.phase(d, now)), look.dim_factor(d, now))
        self.assertEqual((c['bg'], c['card'], c['lit'], c['unlit']), ('FF000000', 'FF1B1B1D', 'FFFFFFFF', 'FF474749'))

    def test_read_falls_back(self):
        values = {'font': 99, 'size': 500, 'night_lit': '#00ff00', 'day_start': '25:00', 'night_start': '6:5'}
        getters = {'boolean': lambda k: True, 'integer': lambda k: values[k],
                   'string': lambda k: values.get(k, '')}
        s = config.read(getters)
        self.assertEqual(s['font'], 0)
        self.assertEqual(s['size'], 100)
        self.assertEqual(s['night_lit'], 'FF00FF00')
        self.assertEqual(s['day_start'], '07:00')
        self.assertEqual(s['night_start'], '06:05')
        self.assertEqual(s['night_bg'], 'FF000000')
        self.assertEqual(s['rounding'], 0)

    def test_settings_xml_is_generated_from_the_table(self):
        tree = ET.parse(os.path.join(ROOT, 'resources', 'settings.xml'))
        ids = [e.get('id') for e in tree.iter('setting')]
        self.assertEqual(ids, [s['id'] for s in config.all_settings()])

    def test_every_font_has_every_glyph(self):
        for _label, folder in config.FONTS:
            for letter in grid.letters():
                for kind in ('r', 'b', 'gr', 'gb'):
                    path = os.path.join(ROOT, 'resources', 'media', 'fonts', folder, letter + kind + '.png')
                    self.assertTrue(os.path.exists(path), path)


class LookTest(unittest.TestCase):
    def test_colour_maths(self):
        self.assertEqual(look.blend('FF000000', 'FFFFFFFF', 0.5), 'FF808080')
        self.assertEqual(look.scale('FF804020', 0.5), 'FF402010')
        self.assertEqual(look.with_alpha('FF123456', 0x60), '60123456')
        self.assertEqual(config.valid_colour('zz'), None)

    def test_day_hours(self):
        s = dict(config.defaults(), mode=2)
        at = lambda h, m=0: datetime.datetime(2026, 1, 1, h, m)
        self.assertEqual(look.phase(s, at(6, 59)), 'night')
        self.assertEqual(look.phase(s, at(7, 0)), 'day')
        self.assertEqual(look.phase(s, at(20, 59)), 'day')
        self.assertEqual(look.phase(s, at(21, 0)), 'night')
        s.update(day_start='22:00', night_start='06:00')   # night shift: 'day' wraps midnight
        self.assertEqual(look.phase(s, at(23)), 'day')
        self.assertEqual(look.phase(s, at(12)), 'night')
        self.assertEqual(look.phase(dict(s, mode=1), at(12)), 'day')

    def test_palettes_and_effects(self):
        s = config.defaults()
        for i in range(len(config.PALETTE_NAMES)):
            p = look.palette(dict(s, night_palette=i), 'night')
            self.assertTrue(all(config.valid_colour(v) for v in p.values()))
            if i < config.CUSTOM:   # lit letters stand out from the card
                self.assertGreater(abs(look.luminance(p['lit']) - look.luminance(p['card'])), 0.4, i)
        p = look.palette(s, 'night')
        self.assertEqual(look.finish(dict(s, unlit=2), p, 1)['unlit'], '00000000')
        self.assertEqual(look.finish(dict(s, frame=2), p, 1)['bg'], 'FF1B1B1D')
        self.assertEqual(look.finish(s, p, 0.5)['lit'], 'FF808080')
        self.assertEqual(set(look.WORD_HUES), set(grid.WORDS))
        cycle = [look.word_colour(dict(s, lit_effect=2), 'IT', 'FFFFFFFF', t) for t in (0, 150, 300)]
        self.assertEqual(len(set(cycle)), 3)

    def test_night_dimming(self):
        s = dict(config.defaults(), night_dim=50, dim=20)
        self.assertAlmostEqual(look.dim_factor(s, datetime.datetime(2026, 1, 1, 12)), 0.8)
        self.assertAlmostEqual(look.dim_factor(s, datetime.datetime(2026, 1, 1, 23)), 0.4)

    def test_layout_on_screen(self):
        for size in range(40, 101, 5):
            for letter_size in (70, 100, 140):
                for frame in (0, 2):
                    s = dict(config.defaults(), size=size, letter_size=letter_size, frame=frame)
                    for minute in range(0, 24 * 60, 7):
                        lay = look.Layout(s, look.drift(s, minute * 60))
                        rects = [lay.glow_rect(i) for i in range(121)] + lay.dot_rects()
                        if frame != 2:
                            rects.append(lay.card)
                        for x, y, w, h in rects:
                            self.assertGreaterEqual(x, 0)
                            self.assertLessEqual(x + w, look.W)
                            self.assertGreaterEqual(y, -look.DRIFT_PX if frame == 2 else 0)
                            self.assertLessEqual(y + h, look.H + (look.DRIFT_PX if frame == 2 else 0))

    def test_grid_matches_the_reference_proportions(self):
        lay = look.Layout(config.defaults())
        x0, y0, side, _ = lay.card
        # The first column's centre: x = 53 of 332 in the reference image.
        self.assertAlmostEqual((lay.cell_centre(0)[0] - x0) / side, 53 / 332.0, delta=0.01)
        self.assertEqual(lay.cell_centre(60), (look.W / 2.0, look.H / 2.0))


if __name__ == '__main__':
    unittest.main()

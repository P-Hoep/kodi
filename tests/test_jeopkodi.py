"""Offline tests for Jeopkodi: settings, the clue database and its shuffled chunks, response
phrasing, and laying text out in glyph images.

python3 -m unittest tests.test_jeopkodi
"""

import os
import sqlite3
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screensaver.jeopkodi')
sys.path.insert(0, ROOT)

from resources.lib import clues, config, layout  # noqa: E402

DB = os.path.join(ROOT, 'resources', 'data', 'clues.db')
GLYPHS = os.path.join(ROOT, 'resources', 'media', 'glyphs')


def defaults(**kw):
    s = dict((x['id'], x['default']) for x in config.all_settings())
    s.update(kw)
    return s


class Settings(unittest.TestCase):
    def test_settings_xml_matches_config(self):
        tree = ET.parse(os.path.join(ROOT, 'resources', 'settings.xml'))
        ids = set(e.get('id') for e in tree.iter('setting'))
        self.assertEqual(ids, set(s['id'] for s in config.all_settings()))

    def test_read_falls_back_to_defaults(self):
        def broken(_sid):
            raise RuntimeError
        s = config.read({'boolean': broken, 'integer': broken})
        self.assertEqual(s, defaults())

    def test_sliders_are_clamped(self):
        s = config.read({'boolean': lambda _: True, 'integer': lambda _: 999})
        self.assertEqual(s['clue_seconds'], 60)

    def test_levels(self):
        self.assertEqual(config.levels(defaults()), [1, 2, 3, 4, 5, 6])
        self.assertEqual(config.levels(defaults(easy=False, medium=False, final=False)), [4, 5])
        self.assertEqual(config.levels(defaults(easy=False, medium=False, hard=False, final=False)),
                         [1, 2, 3, 4, 5])      # nothing ticked: show everything

    def test_years(self):
        self.assertEqual(config.years(defaults()), (1984, 2026))
        self.assertEqual(config.years(defaults(year_min=2010, year_max=1990)), (1990, 2010))


class Database(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = sqlite3.connect(DB)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_has_every_level(self):
        rows = dict(self.db.execute('SELECT level, COUNT(*) FROM clues GROUP BY level'))
        self.assertEqual(sorted(rows), [1, 2, 3, 4, 5, 6])
        self.assertGreater(min(rows.values()), 5000)

    def test_year_range_matches_the_seasons(self):
        self.assertEqual(self.db.execute('SELECT MIN(year), MAX(year) FROM clues').fetchone(),
                         (1984, 2026))       # first season 1984, 42nd 2026

    def test_text_is_clean_capitals(self):
        bad = self.db.execute("SELECT COUNT(*) FROM clues WHERE clue != UPPER(clue) OR clue LIKE '%\\%' "
                              "OR clue LIKE '%<%' OR response = '' OR category = ''").fetchone()[0]
        self.assertEqual(bad, 0)

    def test_no_media_clues(self):
        n = self.db.execute("SELECT COUNT(*) FROM clues WHERE clue LIKE '%SEEN HERE%' "
                            "OR clue LIKE '%CLUE CREW%'").fetchone()[0]
        self.assertEqual(n, 0)


class Chunks(unittest.TestCase):
    def test_filters_and_never_repeats_within_a_round(self):
        source = clues.Clues(DB, [4, 5], daily=False)
        try:
            seen = set()
            for _ in range(3000):
                level, value, daily, category, clue, response, _year = source.next()
                self.assertIn(level, (4, 5))
                self.assertEqual(daily, 0)
                key = (clue, response)
                self.assertNotIn(key, seen)
                seen.add(key)
        finally:
            source.close()

    def test_year_range(self):
        source = clues.Clues(DB, [1, 2, 3, 4, 5, 6], daily=True, years=(2000, 2005))
        try:
            for _ in range(500):
                _level, _value, _daily, _category, _clue, _response, year = source.next()
                self.assertTrue(2000 <= year <= 2005, year)
        finally:
            source.close()

    def test_narrow_year_range_is_not_missed(self):
        """A single year sits in only a handful of the 600-row blocks; they must still be found."""
        source = clues.Clues(DB, [1, 2, 3, 4, 5, 6], daily=True, years=(1984, 1984))
        try:
            for _ in range(100):
                self.assertEqual(source.next()[6], 1984)
        finally:
            source.close()

    def test_final_only(self):
        source = clues.Clues(DB, [6], daily=True)
        try:
            self.assertTrue(all(source.next()[0] == 6 for _ in range(200)))
        finally:
            source.close()


class Responses(unittest.TestCase):
    def test_what_and_who(self):
        self.assertEqual(clues.response_form('RIVER MENTIONED MOST OFTEN IN THE BIBLE', 'THE JORDAN'),
                         'WHAT IS THE JORDAN?')
        self.assertEqual(clues.response_form('THIS PLAYWRIGHT WROTE "THE LITTLE FOXES"', 'LILLIAN HELLMAN'),
                         'WHO IS LILLIAN HELLMAN?')
        self.assertEqual(clues.response_form('THESE ANIMALS LIVE IN PODS', 'WHALES'), 'WHAT ARE WHALES?')

    def test_already_a_question(self):
        self.assertEqual(clues.response_form('FIRST 4-LETTER WORD IN THE ANTHEM', 'what'), 'WHAT?')


class Layout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.font = layout.Font(os.path.join(GLYPHS, 'metrics.json'))

    def test_every_glyph_has_both_colours(self):
        for code in self.font.adv:
            for colour in ('w', 'y'):
                self.assertTrue(os.path.exists(os.path.join(GLYPHS, colour, '%04x.png' % code)), (code, colour))

    def test_long_clue_fits_the_box(self):
        text = 'A' * 10 + ' ' + ' '.join(['WONDERFUL'] * 26)
        px, lines = layout.fit(self.font, text, 1320, 760, 96, 36)
        self.assertLessEqual(layout.block_height(lines, px), 760)
        scale = px / self.font.size
        for line in lines:
            self.assertLessEqual(layout.line_width(self.font, line) * scale, 1320 + 1)

    def test_short_text_uses_the_largest_size(self):
        px, lines = layout.fit(self.font, 'WHAT IS LOCH?', 1320, 760, 96, 36)
        self.assertEqual((px, len(lines)), (96, 1))

    def test_wraps_like_the_show(self):
        """The W.C. Handy slide from the show breaks after WAS and after the quote."""
        text = 'W.C. HANDY WAS "THE FATHER OF" THIS MUSICAL STYLE'
        px, lines = layout.fit(self.font, text, 1320, 760, 96, 36)
        words = [' '.join(''.join(map(chr, w)) for w in line) for line in lines]
        self.assertEqual(words, ['W.C. HANDY WAS', '"THE FATHER OF"', 'THIS MUSICAL STYLE'])

    def test_placed_glyphs_are_centred(self):
        px, lines = layout.fit(self.font, 'LOCH', 1320, 760, 96, 36)
        rects = layout.place(self.font, lines, px, 960, 0)
        left = rects[0][1] + self.font.adv[rects[0][0]][1] * px / self.font.size
        last = rects[-1]
        right = last[1] + (self.font.adv[last[0]][1] + self.font.adv[last[0]][0]) * px / self.font.size
        self.assertAlmostEqual((left + right) / 2, 960, delta=2)

    def test_accents_fall_back(self):
        self.assertEqual(self.font.codes('Ā'), [ord('A')])
        self.assertEqual(self.font.codes('É'), [ord('É')])

    def test_right_aligned_text_ends_at_the_margin(self):
        rects = layout.right_place(self.font, '1984', 42, 1840, 972)
        right_edge = max(x + w for _code, x, _y, w, _h in rects)
        self.assertAlmostEqual(right_edge, 1840, delta=20)

    def test_left_aligned_text_starts_at_the_margin(self):
        rects = layout.left_place(self.font, '$800', 42, 80, 972)
        left_edge = min(x for _code, x, _y, _w, _h in rects)
        self.assertAlmostEqual(left_edge, 80, delta=20)


if __name__ == '__main__':
    unittest.main()

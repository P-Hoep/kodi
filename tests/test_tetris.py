"""Offline tests for Tetris AI: settings, the seven pieces, the board, the heuristic, skill
levels, scoring, the layout maths and the generated media.

python3 -m unittest tests.test_tetris
"""

import os
import random
import struct
import sys
import time
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', 'screensaver.tetris')
sys.path.insert(0, ROOT)

from resources.lib import ai, board, clockface, config, game, pieces  # noqa: E402

MEDIA = os.path.join(ROOT, 'resources', 'media')


def defaults(**kw):
    s = dict((x['id'], x['default']) for x in config.all_settings())
    s.update(kw)
    return s


def png_size(path):
    with open(path, 'rb') as f:
        head = f.read(24)
    assert head[:8] == b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II', head[16:24])


def simulate(pieces_count, seed=1, skill=0, start_level=1):
    b = board.Board(config.COLS, config.ROWS)
    rng = random.Random(seed)
    g = game.Game(b, rng, start_level)
    tops = 0
    max_height = 0
    played = 0
    for _ in range(pieces_count):
        letter = g.take()
        p = ai.choose(b, letter, rng, skill)
        if p is None:
            tops += 1
            g.reset()
            continue
        shape = pieces.ROTATIONS[letter][p.rotation]
        assert b.landing(pieces.masks(shape), p.x) == p.y
        b.place(letter, shape, p.x, p.y)
        g.lock(b.remove_rows(b.full_rows()))
        max_height = max(max_height, max(b.column_height(x) for x in range(config.COLS)))
        played += 1
    return g, tops, max_height, played


class SettingsTest(unittest.TestCase):
    def test_settings_xml_matches_config(self):
        tree = ET.parse(os.path.join(ROOT, 'resources', 'settings.xml'))
        ids = set(e.get('id') for e in tree.iter('setting'))
        self.assertEqual(ids, set(s['id'] for s in config.all_settings()))

    def test_read_falls_back_to_defaults(self):
        def broken(_sid):
            raise RuntimeError
        s = config.read({'boolean': broken, 'integer': broken, 'string': broken})
        self.assertEqual(s, defaults())

    def test_sliders_are_clamped(self):
        s = config.read({'boolean': lambda _: True, 'integer': lambda _: 9999,
                         'string': lambda _: 'nonsense'})
        self.assertEqual(s['speed'], 400)
        self.assertEqual(s['block_size'], 100)
        self.assertEqual(s['background'], 'FF06080F')

    def test_colour_schemes(self):
        for index in range(len(config.SCHEMES) + 1):
            colours = config.piece_colours(defaults(scheme=index))
            self.assertEqual(set(colours), set(config.PIECES))
            for value in colours.values():
                self.assertEqual(len(value), 8)
                int(value, 16)
        self.assertEqual(config.piece_colours(defaults(scheme=0))['I'], 'FF00F0F0')
        custom = config.piece_colours(defaults(scheme=config.SCHEME_CUSTOM, custom_T='FF112233'))
        self.assertEqual(custom['T'], 'FF112233')

    def test_ghost_and_hud_colours(self):
        self.assertEqual(config.ghost_colour('FF00F0F0', 0x40), '4000F0F0')
        self.assertEqual(config.hud_colour(defaults(hud_opacity=60)), '99000000')

    def test_clock_text(self):
        noon = time.struct_time((2026, 11, 8, 12, 5, 0, 6, 312, 0))
        midnight = time.struct_time((2026, 11, 8, 0, 7, 0, 6, 312, 0))
        self.assertEqual(config.clock_text(noon, False), '12:05 PM')
        self.assertEqual(config.clock_text(midnight, False), '12:07 AM')
        self.assertEqual(config.clock_text(noon, True), '12:05')

    def test_layout_fills_the_screen_at_100(self):
        s = defaults()
        self.assertEqual(config.board_rect(s), (0, 0, 1920, 1080))
        left, top, w, h = config.cell_rect(s, 0, 0)
        self.assertEqual((left, top, w, h), (0, 0, 96, 60))
        right, bottom = config.cell_rect(s, config.COLS - 1, config.ROWS - 1)[:2]
        self.assertEqual((right + w, bottom + h), (1920, 1080))
        self.assertEqual(config.board_rect(defaults(block_size=50)), (480, 270, 960, 540))

    def test_clock_settings(self):
        s = defaults()
        self.assertEqual(s['clock_style'], config.CLOCK_TEXT)
        self.assertIn('Tetris blocks', config.CLOCK_STYLES)
        self.assertEqual(s['ghost'], True)
        self.assertEqual(config.valid_colour(s['clock_colour']), 'FFE8ECF4')

    def test_delays_shrink_with_speed_and_level(self):
        slow = config.delays(defaults(speed=50), 1)
        fast = config.delays(defaults(speed=200), 1)
        levelled = config.delays(defaults(speed=200, progressive=True), 10)
        self.assertGreater(slow[0], fast[0])
        self.assertGreater(fast[0], levelled[0])
        self.assertGreater(min(levelled), 0)


class PieceTest(unittest.TestCase):
    def test_all_seven_and_four_cells(self):
        self.assertEqual(pieces.TYPES, ('I', 'O', 'T', 'S', 'Z', 'J', 'L'))
        for letter in pieces.TYPES:
            for shape in pieces.ROTATIONS[letter]:
                self.assertEqual(len(shape), 4)
                self.assertEqual(len(set(shape)), 4)

    def test_classic_rotation_counts(self):
        counts = dict((letter, len(pieces.ROTATIONS[letter])) for letter in pieces.TYPES)
        self.assertEqual(counts, {'I': 2, 'O': 1, 'T': 4, 'S': 2, 'Z': 2, 'J': 4, 'L': 4})

    def test_rotations_are_normalised_and_unique(self):
        for letter in pieces.TYPES:
            shapes = pieces.ROTATIONS[letter]
            self.assertEqual(len(shapes), len(set(shapes)))
            for shape in shapes:
                self.assertEqual(min(x for x, _y in shape), 0)
                self.assertEqual(min(y for _x, y in shape), 0)

    def test_masks(self):
        shape = ((0, 0), (1, 0), (0, 1), (1, 1))       # O
        self.assertEqual(pieces.masks(shape), ((0, 0b11), (1, 0b11)))
        self.assertEqual(pieces.width(shape), 2)
        self.assertEqual(pieces.height(shape), 2)


class BoardTest(unittest.TestCase):
    def test_landing_and_placement(self):
        b = board.Board(10, 6)
        shape = ((0, 0), (1, 0), (0, 1), (1, 1))
        self.assertEqual(b.landing(pieces.masks(shape), 0), 4)
        b.place('O', shape, 0, 4)
        self.assertEqual(b.column_height(0), 2)
        self.assertEqual(b.letters[4][0], 'O')
        self.assertEqual(b.letters[5][1], 'O')

    def test_full_rows_clear_and_fall(self):
        b = board.Board(4, 3)
        for x in range(4):
            b.bits[2] |= 1 << x
            b.letters[2][x] = 'I'
        b.bits[0] = 0b0001
        b.letters[0][0] = 'T'
        self.assertEqual(b.full_rows(), [2])
        self.assertEqual(b.remove_rows([2]), 1)
        self.assertEqual(b.bits, [0, 0b0001, 0])       # the top row fell one cell
        self.assertEqual(b.letters[1][0], 'T')

    def test_walls_and_collisions(self):
        b = board.Board(6, 6)
        shape = ((0, 0), (1, 0), (2, 0), (3, 0))       # I
        masks = pieces.masks(shape)
        self.assertEqual(b.landing(masks, 0), 5)
        self.assertIsNone(b.landing(masks, 3))          # over the right wall
        b.place('O', ((0, 0), (1, 0), (0, 1), (1, 1)), 2, 4)
        self.assertFalse(b.fits(masks, 0, 4))           # the O is in the way
        self.assertEqual(b.landing(masks, 0), 3)

    def test_fixed_cells_block_and_survive(self):
        b = board.Board(4, 4)
        b.set_fixed([(1, 2)])
        self.assertEqual(b.letters[2][1], board.FIXED)
        b.place('O', ((0, 0), (1, 0), (0, 1), (1, 1)), 0, 0)
        self.assertFalse(b.can_set_fixed([(0, 0)]))     # a piece there
        self.assertTrue(b.can_set_fixed([(1, 2)]))
        b.clear()
        self.assertEqual(b.letters[2][1], board.FIXED)  # clear keeps the clock
        self.assertIsNone(b.letters[0][0])

    def test_full_rows_keep_the_clock(self):
        b = board.Board(4, 4)
        b.set_fixed([(1, 2)])
        for x in (0, 2, 3):
            b.bits[2] |= 1 << x
            b.letters[2][x] = 'T'
        b.bits[0] |= 1
        b.letters[0][0] = 'S'
        self.assertEqual(b.full_rows(), [2])
        self.assertEqual(b.remove_rows([2]), 1)
        self.assertEqual(b.letters[2][1], board.FIXED)   # the clock stays put
        self.assertIsNone(b.letters[2][0])                # the pieces cleared
        self.assertEqual(b.letters[1][0], 'S')            # the cell above fell one
        self.assertIsNone(b.letters[0][0])


class ClockfaceTest(unittest.TestCase):
    def test_clock_fits_on_the_board(self):
        now = time.struct_time((2026, 11, 8, 23, 59, 0, 6, 312, 0))
        for twelve in (False, True):
            cells = clockface.cells(now, twelve)
            self.assertTrue(cells)
            for x, y in cells:
                self.assertTrue(0 <= x < config.COLS)
                self.assertTrue(0 <= y < config.ROWS)

    def test_digits_are_five_rows_high(self):
        now = time.struct_time((2026, 11, 8, 12, 27, 0, 6, 312, 0))
        cells = clockface.cells(now, True)
        self.assertEqual(min(y for _x, y in cells), clockface.TOP)
        self.assertEqual(max(y for _x, y in cells), clockface.TOP + clockface.HEIGHT - 1)
        self.assertIn((clockface.LEFT + 1, clockface.TOP), cells)        # the 1's top
        for dx in range(3):
            self.assertIn((clockface.LEFT + 4 + dx, clockface.TOP), cells)  # the 2's bar
        self.assertIn((clockface.LEFT + 8, clockface.TOP + 1), cells)    # the colon

    def test_twelve_hour_midnight_is_twelve(self):
        midnight = time.struct_time((2026, 11, 8, 0, 7, 0, 6, 312, 0))
        noon = time.struct_time((2026, 11, 8, 12, 7, 0, 6, 312, 0))
        self.assertEqual(clockface.cells(midnight, False), clockface.cells(noon, False))
        self.assertNotEqual(clockface.cells(midnight, True), clockface.cells(noon, True))


class AiTest(unittest.TestCase):
    def test_perfect_keeps_a_long_game(self):
        g, tops, max_height, played = simulate(400, seed=1, skill=0)
        self.assertEqual(tops, 0)
        self.assertEqual(played, 400)
        self.assertGreater(g.lines, 20)
        self.assertLess(max_height, config.ROWS)

    def test_skill_changes_the_choice(self):
        b = board.Board(config.COLS, config.ROWS)
        rng = random.Random(7)
        letter = 'T'
        best = ai.best(b, letter)
        self.assertEqual(ai.choose(b, letter, random.Random(9), 0), best)
        poorer = [ai.choose(b, letter, rng, 4) for _ in range(60)]
        self.assertTrue(any(p != best for p in poorer))

    def test_beginner_tops_out_more_often(self):
        _g, perfect_tops, _h, _p = simulate(250, seed=3, skill=0)
        _g, beginner_tops, _h, _p = simulate(250, seed=3, skill=4)
        self.assertLessEqual(perfect_tops, beginner_tops)

    def test_no_placement_on_a_full_board(self):
        b = board.Board(config.COLS, config.ROWS)
        for y in range(config.ROWS):
            b.bits[y] = b.full_mask
        self.assertIsNone(ai.choose(b, 'T', random.Random(1), 0))

    def test_candidates_are_legal_and_clear(self):
        b = board.Board(config.COLS, config.ROWS)
        places = ai.candidates(b, 'I')
        self.assertEqual(len(places), (config.COLS - 3) + config.COLS)  # flat: 17, upright: 20
        for p in places:
            shape = pieces.ROTATIONS['I'][p.rotation]
            self.assertEqual(b.landing(pieces.masks(shape), p.x), p.y)

    def test_pieces_play_around_the_block_clock(self):
        now = time.struct_time((2026, 11, 8, 11, 17, 0, 6, 312, 0))
        clock = clockface.cells(now, False)
        b = board.Board(config.COLS, config.ROWS)
        b.set_fixed(clock)
        fixed = set(clock)
        rng = random.Random(5)
        g = game.Game(b, rng, 1)
        played = 0
        for _ in range(120):
            letter = g.take()
            p = ai.choose(b, letter, rng, 0)
            if p is None:
                g.reset()
                continue
            shape = pieces.ROTATIONS[letter][p.rotation]
            for dx, dy in shape:
                self.assertNotIn((p.x + dx, p.y + dy), fixed)
            b.place(letter, shape, p.x, p.y)
            g.lock(b.remove_rows(b.full_rows()))
            played += 1
            for x, y in fixed:
                self.assertEqual(b.letters[y][x], board.FIXED)
        self.assertGreater(played, 90)


class GameTest(unittest.TestCase):
    def test_bag_has_every_piece_before_repeating(self):
        g = game.Game(board.Board(config.COLS, config.ROWS), random.Random(2))
        first = [g.take() for _ in range(7)]
        self.assertEqual(sorted(first), sorted(pieces.TYPES))

    def test_scoring_and_levels(self):
        g = game.Game(board.Board(config.COLS, config.ROWS), random.Random(2))
        g.lock(4)
        self.assertEqual((g.score, g.lines, g.level), (800, 4, 1))
        g.lock(2)
        self.assertEqual(g.score, 1100)
        g.lock(0)
        g.lock(4)
        self.assertEqual(g.lines, 10)
        self.assertEqual(g.level, 2)
        self.assertEqual(g.score, 1900)
        g.lock(4)
        self.assertEqual(g.score, 1900 + 800 * 2)

    def test_start_level_and_reset(self):
        g = game.Game(board.Board(config.COLS, config.ROWS), random.Random(2), start_level=4)
        self.assertEqual(g.level, 4)
        g.lock(10)
        self.assertEqual(g.level, 5)
        g.reset()
        self.assertEqual((g.score, g.lines, g.level), (0, 0, 4))


class AddonTest(unittest.TestCase):
    def test_manifest(self):
        tree = ET.parse(os.path.join(ROOT, 'addon.xml'))
        addon = tree.getroot()
        self.assertEqual(addon.get('id'), config.ADDON_ID)
        self.assertEqual(addon.get('version'), '1.0.0')
        points = set(e.get('point') for e in addon.iter('extension'))
        self.assertIn('xbmc.ui.screensaver', points)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, 'default.py')))

    def test_window_xml(self):
        ET.parse(os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i',
                              'screensaver-tetris.xml'))

    def test_media_sizes(self):
        self.assertEqual(png_size(os.path.join(MEDIA, 'block.png')), (192, 120))
        self.assertEqual(png_size(os.path.join(MEDIA, 'grid.png')), (1920, 1080))
        self.assertEqual(png_size(os.path.join(MEDIA, 'vignette.png')), (1920, 1080))
        self.assertEqual(png_size(os.path.join(MEDIA, 'panel.png')), (512, 512))
        self.assertEqual(png_size(os.path.join(ROOT, 'icon.png')), (512, 512))
        self.assertTrue(os.path.getsize(os.path.join(ROOT, 'fanart.jpg')) > 10000)


if __name__ == '__main__':
    unittest.main()

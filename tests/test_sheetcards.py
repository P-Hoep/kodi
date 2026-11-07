"""Offline tests for Sheetcards (script.module.sheetcards): sheet-ID extraction, htmlview tab
parsing against a saved page of the sample sheet, CSV parsing (headers, quoted newlines, BOM,
blanks, duplicates), the loader's fallbacks and cache, distractor ranking and fallback, the
uniform position of the correct option, Leitner transitions and session building, theme
contrast and the settings table. No network, no Kodi.

python3 -m unittest tests.test_sheetcards
"""

import collections
import datetime
import json
import os
import random
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'script.module.sheetcards', 'lib'))

from sheetcards import cache, choices, config, data, deck, parser, plan, sheet, srs, theme  # noqa: E402
from sheetcards.ui import fonts  # noqa: E402

FIXTURES = os.path.join(HERE, 'fixtures', 'sheetcards')
SAMPLE_ID = '1oOBsLmJIfHB57YVifu1Vu1g1MdiuApkiytAl4o_leoo'
SAMPLE_GID = '1439483256'


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding='utf-8') as handle:
        return handle.read()


def make_cards(pairs, title='Deck', gid='1'):
    return [deck.Card('c%03d' % i, q, a, gid, title, i) for i, (q, a) in enumerate(pairs)]


class FakeWeb(object):
    """get(url) for the loader: maps URL substrings to (body, content type) or a SheetError kind."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, timeout=10, log=None):
        self.calls.append(url)
        for key, value in self.routes.items():
            if key in url:
                if isinstance(value, str) and value in ('not_public', 'not_found', 'network'):
                    raise sheet.SheetError(value)
                body, kind = value
                return body.encode('utf-8'), kind, url
        raise sheet.SheetError('not_found')


class SheetIdTest(unittest.TestCase):
    def test_bare_and_url(self):
        self.assertEqual(sheet.extract_id('  %s \n' % SAMPLE_ID), SAMPLE_ID)
        url = 'https://docs.google.com/spreadsheets/d/%s/edit?gid=%s#gid=%s' % (SAMPLE_ID, SAMPLE_GID, SAMPLE_GID)
        self.assertEqual(sheet.extract_id(url), SAMPLE_ID)
        self.assertEqual(sheet.extract_id('not an id'), '')
        self.assertEqual(sheet.extract_id(''), '')

    def test_api_key_redacted(self):
        self.assertNotIn('SECRET', sheet.redact('https://x/y?fields=a&key=SECRET'))


class HtmlviewTest(unittest.TestCase):
    def test_sample_page(self):
        title, tabs = sheet.parse_htmlview(fixture('htmlview.html'))
        self.assertEqual(title, 'kodiQuiz')
        self.assertEqual(tabs, [{'gid': SAMPLE_GID, 'title': 'ml_ai_developer_glossary', 'index': 0}])

    def test_several_tabs_and_escapes(self):
        page = ('<title>My übung - Google Sheets</title><script>'
                'items.push({name: "Capitals \\x26 flags", pageUrl: "x", gid: "0"});'
                'items.push({name: "Verbs \\/ tenses", pageUrl: "y", gid: "123"});'
                'items.push({name: "Capitals \\x26 flags", pageUrl: "x", gid: "0"});</script>')
        title, tabs = sheet.parse_htmlview(page)
        self.assertEqual(title, 'My übung')
        self.assertEqual([(t['gid'], t['title']) for t in tabs], [('0', 'Capitals & flags'), ('123', 'Verbs / tenses')])


class ParserTest(unittest.TestCase):
    def test_sample_export(self):
        cards = parser.cards(SAMPLE_ID, {'gid': SAMPLE_GID, 'title': 'ml_ai_developer_glossary'},
                             fixture('export.csv'))
        self.assertEqual(len(cards), 131)
        self.assertEqual(cards[0].question, 'AI')
        self.assertTrue(cards[7].answer.startswith('A collection of data used for training, validation'))
        gviz = parser.cards(SAMPLE_ID, {'gid': SAMPLE_GID, 'title': 'ml_ai_developer_glossary'}, fixture('gviz.csv'))
        self.assertEqual([(c.question, c.answer) for c in gviz], [(c.question, c.answer) for c in cards])

    def test_headers(self):
        for a, b in (('Question', 'Answer'), ('q', 'A'), ('FRONT', 'back'), ('Term', 'Definition')):
            self.assertEqual(parser.rows('%s,%s\nx,y\n' % (a, b)), [('x', 'y')])
        self.assertEqual(parser.rows('Capital,City\nx,y\n'), [('Capital', 'City'), ('x', 'y')])
        self.assertEqual(parser.rows('Capital,City\nx,y\n', parser.HEADER_YES), [('x', 'y')])
        self.assertEqual(parser.rows('question,answer\nx,y\n', parser.HEADER_NO), [('question', 'answer'), ('x', 'y')])

    def test_bom_quotes_blanks_columns(self):
        text = '﻿Q,A\n"Two, words","line one\nline two"\n,missing\nmissing,\n  \n a , b ,extra,cols\n'
        self.assertEqual(parser.rows(text), [('Two, words', 'line one\nline two'), ('a', 'b')])

    def test_blank_lines_collapse(self):
        self.assertEqual(parser.clean('a\n\n\n\n\nb'), 'a\n\nb')
        self.assertEqual(parser.clean('a\r\n\r\nb'), 'a\n\nb')

    def test_duplicates_and_ids(self):
        logged = []
        tab = {'gid': '5', 'title': 'T'}
        cards = parser.cards('S', tab, 'x,1\nX ,2\ny,3\n', log=logged.append)
        self.assertEqual([(c.question, c.answer) for c in cards], [('x', '1'), ('y', '3')])
        self.assertEqual(len(logged), 1)
        self.assertEqual(cards[0].id, parser.card_id('S', 'T', 'x'))
        self.assertEqual(len(cards[0].id), 12)
        # Editing the answer keeps the id; editing the question changes it.
        self.assertEqual(parser.cards('S', tab, 'x,changed\n')[0].id, cards[0].id)
        self.assertNotEqual(parser.cards('S', tab, 'x?,1\n')[0].id, cards[0].id)


class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.cache = cache.Cache(self.root)

    def tearDown(self):
        shutil.rmtree(self.root)

    def loader(self, routes, **kw):
        web = FakeWeb(routes)
        return data.Loader(self.cache, SAMPLE_ID, get=web, **kw), web

    def test_refresh_and_cache(self):
        loader, web = self.loader({'/htmlview': (fixture('htmlview.html'), 'text/html'),
                                   'export?format=csv&gid=%s' % SAMPLE_GID: (fixture('export.csv'), 'text/csv')})
        self.assertTrue(loader.is_stale(6))
        got = loader.refresh()
        self.assertEqual(got.title, 'kodiQuiz')
        self.assertEqual([(d.title, len(d.cards)) for d in got.decks], [('ml_ai_developer_glossary', 131)])
        self.assertFalse(loader.is_stale(6))
        self.assertTrue(loader.is_stale(0))
        cached = loader.cached()
        self.assertEqual(len(cached.all_cards()), 131)
        meta = self.cache.read_meta(SAMPLE_ID, got.decks and {'gid': SAMPLE_GID, 'title': ''})
        self.assertEqual(meta['row_count'], 131)
        self.assertEqual(meta['source'], 'export')
        self.assertFalse([f for f in os.listdir(self.cache.folder(SAMPLE_ID)) if f.endswith('.tmp')])

    def test_gviz_fallback(self):
        loader, web = self.loader({'/htmlview': (fixture('htmlview.html'), 'text/html'),
                                   'export?': 'network',
                                   'gviz/tq': (fixture('gviz.csv'), 'text/csv')})
        got = loader.refresh()
        self.assertEqual(len(got.all_cards()), 131)
        self.assertIn('sheet=ml_ai_developer_glossary', web.calls[-1])

    def test_not_public(self):
        loader, _web = self.loader({'/htmlview': (fixture('htmlview.html'), 'text/html'),
                                    'export?': ('<html>sign in</html>', 'text/html; charset=utf-8')})
        with self.assertRaises(sheet.SheetError) as ctx:
            loader.refresh()
        self.assertEqual(ctx.exception.kind, 'not_public')

    def test_not_found_and_network(self):
        for kind in ('not_found', 'network', 'not_public'):
            loader, _web = self.loader({'/htmlview': kind})
            with self.assertRaises(sheet.SheetError) as ctx:
                loader.refresh()
            self.assertEqual(ctx.exception.kind, kind)

    def test_tab_names_then_gid0(self):
        empty_page = ('<title>Quiz - Google Sheets</title>', 'text/html')
        loader, web = self.loader({'/htmlview': empty_page, 'sheet=Capitals': ('Paris,France\n', 'text/csv'),
                                   'sheet=Verbs': ('go,went\n', 'text/csv')}, tab_names='Capitals, Verbs')
        got = loader.refresh()
        self.assertEqual([d.title for d in got.decks], ['Capitals', 'Verbs'])
        self.assertEqual(got.decks[0].key, 'Capitals')
        loader, web = self.loader({'/htmlview': empty_page, 'gid=0': ('a,b\n', 'text/csv')})
        got = loader.refresh()
        self.assertEqual([(d.gid, d.title) for d in got.decks], [('0', 'Quiz')])

    def test_failed_tab_keeps_cached_copy(self):
        page = ('items.push({name: "A", pageUrl: "", gid: "1"}); items.push({name: "B", pageUrl: "", gid: "2"});',
                'text/html')
        loader, _ = self.loader({'/htmlview': page, 'gid=1': ('a,1\n', 'text/csv'), 'gid=2': ('b,2\n', 'text/csv')})
        loader.refresh()
        loader, _ = self.loader({'/htmlview': page, 'gid=1': ('a,1\nc,3\n', 'text/csv'), 'gid=2': 'network',
                                 'sheet=B': 'network'})
        got = loader.refresh()
        self.assertEqual([len(d.cards) for d in got.decks], [2, 1])

    def test_select_decks(self):
        decks = [deck.Deck('1', 'A', 0, make_cards([('a', 'b')])), deck.Deck('2', 'B', 1, []),
                 deck.Deck('3', 'C', 2, make_cards([('c', 'd')]))]
        self.assertEqual([d.title for d in deck.select(decks, [])], ['A', 'C'])
        self.assertEqual([d.title for d in deck.select(decks, deck.parse_keys(' 3 ,'))], ['C'])
        self.assertEqual([d.title for d in deck.select(decks, ['2'])], ['A', 'C'])  # empty deck -> all


class ChoicesTest(unittest.TestCase):
    def test_classify(self):
        cases = {'1969': 'year', '42': 'integer', '1,000,000': 'integer', '3.14': 'decimal', '12%': 'decimal',
                 '2024-03-01': 'date', '14 July 1789': 'date', 'March 3, 1999': 'date', 'Paris': 'word',
                 'New York City': 'phrase', 'The quick brown fox jumps.': 'sentence', '999': 'integer',
                 '3000': 'integer'}
        for text, kind in cases.items():
            self.assertEqual(choices.classify(text), kind, text)

    def test_normalise(self):
        self.assertEqual(choices.normalise('  Paris.  '), 'paris')
        self.assertEqual(choices.normalise('New   York!?'), 'new york')

    def test_same_class_first_and_excludes_correct(self):
        rng = random.Random(1)
        pool = ['1066', '1492', '1789', '1815', 'Paris', 'Napoleon Bonaparte', '1969.', '1969']
        for _ in range(50):
            picks = choices.distractors('1969', pool, 3, rng)
            self.assertEqual(len(picks), 3)
            self.assertTrue(all(choices.classify(p) == 'year' for p in picks), picks)
            self.assertNotIn('1969', [choices.normalise(p) for p in picks])

    def test_top_up_from_other_classes(self):
        picks = choices.distractors('1969', ['1066', 'Paris', 'London', 'a very long sentence answer here'], 3,
                                    random.Random(2))
        self.assertEqual(len(picks), 3)
        self.assertIn('1066', picks)
        self.assertNotIn('a very long sentence answer here', picks)  # Paris/London are closer in length

    def test_top_eight_variety(self):
        pool = ['w%02d' % i for i in range(30)]
        seen = set()
        rng = random.Random(3)
        for _ in range(200):
            seen.update(choices.distractors('xyz', pool, 3, rng))
        self.assertEqual(len(seen), 8)

    def test_pool_too_small(self):
        self.assertEqual(choices.distractors('a', ['b', 'B.', 'a'], 3, random.Random()), [])
        cards = make_cards([('q1', 'x'), ('q2', 'y'), ('q3', 'x')])
        self.assertIsNone(choices.build('q', cards[0], cards, 4, random.Random()))

    def test_correct_position_uniform(self):
        cards = make_cards([('q%d' % i, 'answer %d' % i) for i in range(20)])
        rng = random.Random(7)
        counts = collections.Counter()
        trials = 8000
        for _ in range(trials):
            options, correct = choices.build('q', cards[0], cards, 4, rng)
            self.assertEqual(options[correct], 'answer 0')
            self.assertEqual(len(set(options)), 4)
            counts[correct] += 1
        expected = trials / 4.0
        chi2 = sum((counts[i] - expected) ** 2 / expected for i in range(4))
        self.assertLess(chi2, 16.27)  # p = 0.001, 3 degrees of freedom

    def test_answer_to_question_uses_questions(self):
        cards = make_cards([('Paris', 'France'), ('Rome', 'Italy'), ('Madrid', 'Spain'), ('Berlin', 'Germany')])
        options, correct = choices.build('a', cards[1], cards, 4, random.Random(1))
        self.assertEqual(sorted(options), ['Berlin', 'Madrid', 'Paris', 'Rome'])
        self.assertEqual(options[correct], 'Rome')

    def test_stacked(self):
        self.assertFalse(choices.stacked(['a' * 90, 'b']))
        self.assertTrue(choices.stacked(['a' * 91, 'b']))


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.cards = make_cards([('q%d' % i, 'a%d' % i) for i in range(6)])

    def test_modes(self):
        rng = random.Random(4)
        s = config.defaults('app')
        self.assertEqual(plan.make(self.cards[0], dict(s, mode=0), self.cards, rng).kind, 'flash')
        p = plan.make(self.cards[0], dict(s, mode=1), self.cards, rng)
        self.assertEqual((p.kind, len(p.options), p.options[p.correct]), ('choice', 4, 'a0'))
        p = plan.make(self.cards[0], dict(s, mode=1, options=0), self.cards, rng)
        self.assertEqual(len(p.options), 3)
        kinds = collections.Counter(plan.make(self.cards[0], dict(s, mode=2, mix_ratio=30), self.cards, rng).kind
                                    for _ in range(2000))
        self.assertAlmostEqual(kinds['choice'] / 2000.0, 0.3, delta=0.05)

    def test_direction(self):
        rng = random.Random(5)
        s = dict(config.defaults('app'), mode=0)
        self.assertEqual(plan.make(self.cards[0], dict(s, direction=1), self.cards, rng).prompt, 'a0')
        sides = collections.Counter(plan.make(self.cards[0], dict(s, direction=2), self.cards, rng).side
                                    for _ in range(1000))
        self.assertTrue(400 < sides['q'] < 600)

    def test_fallback_and_flash_only(self):
        small = make_cards([('q1', 'x'), ('q2', 'y'), ('q3', 'x')])
        p = plan.make(small[0], dict(config.defaults('app'), mode=1), small, random.Random())
        self.assertEqual((p.kind, p.fell_back), ('flash', True))
        decks = [deck.Deck('1', 'Small', 0, small), deck.Deck('2', 'Big', 1, self.cards)]
        self.assertEqual([d.title for d in plan.flash_only_decks(decks, config.defaults('app'))], ['Small'])


class ShuffleBagTest(unittest.TestCase):
    def test_every_card_once_and_no_repeat_across_boundary(self):
        cards = make_cards([('q%d' % i, 'a') for i in range(5)])
        bag = deck.ShuffleBag(cards, random.Random(9))
        previous = None
        for _round in range(200):
            drawn = [bag.next() for _ in range(5)]
            self.assertEqual(sorted(c.id for c in drawn), sorted(c.id for c in cards))
            if previous is not None:
                self.assertNotEqual(drawn[0].id, previous.id)
            previous = drawn[-1]

    def test_replace(self):
        cards = make_cards([('q%d' % i, 'a') for i in range(5)])
        bag = deck.ShuffleBag(cards, random.Random(1))
        bag.next()
        bag.replace(cards[:2])
        self.assertTrue(all(bag.next().id in ('c000', 'c001') for _ in range(10)))


class SrsTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.path = os.path.join(self.root, 'progress', 'S.json')
        self.now = datetime.datetime(2026, 11, 6, 18, 20)
        self.today = self.now.date()

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_leitner_transitions(self):
        p = srs.Progress(self.path, 'S')
        for box, days in ((1, 1), (2, 2), (3, 4), (4, 8), (5, 16), (5, 16)):
            entry = p.record('c', True, self.now)
            self.assertEqual(entry['box'], box)
            self.assertEqual(entry['due'], (self.today + datetime.timedelta(days=days)).isoformat())
        entry = p.record('c', False, self.now)
        self.assertEqual((entry['box'], entry['due']), (1, self.today.isoformat()))
        self.assertEqual((entry['seen'], entry['correct'], entry['misses']), (7, 6, 1))
        self.assertEqual(p.stats['answered'], 7)

    def test_srs_off_keeps_stats_only(self):
        p = srs.Progress(self.path, 'S')
        entry = p.record('c', True, self.now, srs=False)
        self.assertEqual(entry['box'], 0)
        self.assertEqual(p.stats['correct'], 1)

    def test_save_load_and_corrupt(self):
        p = srs.Progress(self.path, 'S')
        p.record('c', True, self.now)
        p.note_streak(14)
        p.save()
        saved = json.load(open(self.path))
        self.assertEqual((saved['version'], saved['sheet_id'], saved['stats']['best_streak']), (1, 'S', 14))
        self.assertEqual(srs.Progress(self.path, 'S').box('c'), 1)
        with open(self.path, 'w') as handle:
            handle.write('{not json')
        logged = []
        p = srs.Progress(self.path, 'S', log=logged.append)
        self.assertEqual(p.cards, {})
        self.assertTrue(os.path.exists(self.path + '.bak'))
        self.assertEqual(len(logged), 1)

    def test_prune_after_90_days(self):
        p = srs.Progress(self.path, 'S')
        p.record('gone', True, self.now)
        p.prune([], self.today)
        p.prune([], self.today + datetime.timedelta(days=90))
        self.assertIn('gone', p.cards)
        p.prune(['gone'], self.today + datetime.timedelta(days=91))  # back in the sheet: kept
        self.assertIn('gone', p.cards)
        p.prune([], self.today + datetime.timedelta(days=100))
        p.prune([], self.today + datetime.timedelta(days=191))
        self.assertNotIn('gone', p.cards)

    def test_smart_session(self):
        cards = make_cards([('q%d' % i, 'a%d' % i) for i in range(30)])
        p = srs.Progress(None, 'S')
        old = self.now - datetime.timedelta(days=10)
        p.record(cards[5].id, False, old)                                   # box 1, due 10 days ago
        p.record(cards[6].id, False, self.now - datetime.timedelta(days=2))  # box 1, due 2 days ago
        p.record(cards[7].id, True, self.now)                               # box 1, due tomorrow
        for _ in range(3):
            p.record(cards[8].id, True, self.now)                           # box 3, not due
        session = srs.build_session(cards, p, self.today, 20, new_per_session=10)
        ids = [c.id for c in session]
        self.assertEqual(ids[:2], [cards[5].id, cards[6].id])               # overdue, oldest first
        self.assertEqual(ids[2:12], [c.id for c in cards[:5] + cards[9:14]])  # then 10 new
        self.assertEqual(ids[12:14], [cards[7].id, cards[8].id])            # then lowest box
        self.assertEqual(len(session), 14)
        self.assertEqual(len(srs.build_session(cards, p, self.today, None, new_per_session=50)), 30)

    def test_other_orders(self):
        cards = make_cards([('q%d' % i, 'a') for i in range(10)])
        p = srs.Progress(None, 'S')
        p.record(cards[3].id, False, self.now)
        p.record(cards[3].id, False, self.now)
        p.record(cards[4].id, False, self.now)
        p.record(cards[2].id, True, self.now)
        p.record(cards[2].id, True, self.now)
        self.assertEqual(srs.build_session(cards, p, self.today, 5, srs.ORDER_SHEET), cards[:5])
        hardest = srs.build_session(cards, p, self.today, 3, srs.ORDER_HARDEST, rng=random.Random(1))
        self.assertEqual([c.id for c in hardest], [cards[3].id, cards[4].id, cards[2].id])
        shuffled = srs.build_session(cards, p, self.today, None, srs.ORDER_SHUFFLE, rng=random.Random(1))
        self.assertEqual(sorted(c.id for c in shuffled), sorted(c.id for c in cards))

    def test_queue_requeues_once(self):
        cards = make_cards([('q%d' % i, 'a') for i in range(10)])
        q = srs.Queue(cards, random.Random(2))
        first = q.current()
        self.assertTrue(q.requeue(first))
        self.assertFalse(q.requeue(first))
        later = q.items.index(first, 1)
        self.assertTrue(4 <= later <= 6)
        self.assertEqual(q.length, 11)


class ThemeTest(unittest.TestCase):
    def test_builtin_contrast(self):
        for palette in (theme.NIGHT, theme.DAY):
            self.assertGreaterEqual(theme.contrast(palette['text'], palette['card']), 4.5)
            self.assertGreaterEqual(theme.contrast(palette['muted'], palette['card']), 4.5)

    def test_resolve(self):
        s = config.defaults('app')
        night = theme.resolve(s, datetime.datetime(2026, 1, 1, 12))
        self.assertEqual((night['name'], night['card'], night['accent']), ('night', 'FF1A1F27', 'FF6366F1'))
        self.assertEqual(night['glow'], '2E6366F1')
        auto = dict(s, theme_mode=2)
        self.assertEqual(theme.resolve(auto, datetime.datetime(2026, 1, 1, 12))['name'], 'day')
        self.assertEqual(theme.resolve(auto, datetime.datetime(2026, 1, 1, 6, 59))['name'], 'night')
        self.assertEqual(theme.resolve(dict(auto, day_starts='22:00', night_starts='06:00'),
                                       datetime.datetime(2026, 1, 1, 23))['name'], 'day')

    def test_custom_colours(self):
        s = dict(config.defaults('app'), accent=theme.CUSTOM, accent_custom='#12ab34', card_custom='FFFFFF')
        p = theme.resolve(s, datetime.datetime(2026, 1, 1))
        self.assertEqual(p['accent'], 'FF12AB34')
        self.assertEqual(p['text'], theme.DAY['text'])     # night theme, white card -> dark text
        self.assertGreaterEqual(theme.contrast(p['text'], p['card']), 4.5)
        bad = theme.resolve(dict(s, accent_custom='zzz'), datetime.datetime(2026, 1, 1))
        self.assertEqual(bad['accent'], theme.ACCENTS[0])
        for card in ('777777', '3B82F6', 'FDE68A', '111111'):
            p = theme.resolve(dict(s, card_custom=card), datetime.datetime(2026, 1, 1))
            self.assertGreaterEqual(theme.contrast(p['text'], p['card']), 4.5 if card != '777777' else 4.0, card)

    def test_parse_hex(self):
        self.assertEqual(theme.parse_hex('abc'), 'FFAABBCC')
        self.assertEqual(theme.parse_hex('80ABCDEF'), 'FFABCDEF')
        self.assertIsNone(theme.parse_hex('12345'))


class ConfigTest(unittest.TestCase):
    def test_split_between_addons(self):
        app = config.defaults('app')
        ss = config.defaults('ss')
        self.assertIn('order', app)
        self.assertNotIn('order', ss)
        self.assertIn('question_seconds', ss)
        self.assertNotIn('question_seconds', app)
        self.assertIn('use_app_settings', ss)
        self.assertIn('sheet_id', config.shared_ids())
        self.assertNotIn('show_clock', config.shared_ids())

    def test_read_falls_back(self):
        def broken(_sid):
            raise RuntimeError
        got = config.read({'boolean': broken, 'integer': lambda sid: 99, 'string': lambda sid: ' x '}, 'app')
        self.assertEqual(got['srs_enabled'], True)
        self.assertEqual(got['mode'], config.MODE_MIXED)       # 99 is out of range
        self.assertEqual(got['refresh_hours'], 72)               # clamped
        self.assertEqual(got['sheet_id'], 'x')
        self.assertEqual(config.session_length(dict(got, cards_per_session=4)), None)

    def test_strings_unique(self):
        self.assertEqual(len(set(config.STRINGS.values())), len(config.STRINGS))


class FontTest(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual([fonts.bucket('x' * n) for n in (1, 40, 41, 90, 91, 180, 181)],
                         ['xl', 'xl', 'l', 'l', 'm', 'm', 's'])


class CacheTest(unittest.TestCase):
    def test_atomic_and_clear(self):
        root = tempfile.mkdtemp()
        try:
            c = cache.Cache(root)
            c.write_tabs('S', 'T', [{'gid': '0', 'title': 'A', 'index': 0}], 'htmlview', now=100)
            self.assertEqual(c.read_tabs('S')['title'], 'T')
            self.assertAlmostEqual(c.age('S', now=160), 60)
            self.assertIsNone(c.age('other'))
            c.write_csv('S', {'gid': None, 'title': 'A/B'}, 'x,y', 'gviz', 1)
            self.assertEqual(c.read_csv('S', {'gid': None, 'title': 'A/B'}), 'x,y')
            c.clear()
            self.assertIsNone(c.read_tabs('S'))
        finally:
            shutil.rmtree(root)


if __name__ == '__main__':
    unittest.main()

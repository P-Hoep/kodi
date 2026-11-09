"""Offline tests for OpenTrivia: the settings table against both settings.xml files, the question
database and its shuffled block reader, theme resolution, the quiz's layout and scoring, the
generated skin, strings and artwork.

python3 -m unittest tests.test_opentrivia
"""

import datetime
import json
import os
import re
import sqlite3
import sys
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
MODULE = os.path.join(ROOT, 'script.module.opentrivia')
APP = os.path.join(ROOT, 'script.opentrivia')
SAVER = os.path.join(ROOT, 'screensaver.opentrivia')
DB = os.path.join(MODULE, 'resources', 'data', 'trivia.db')
SKIN = os.path.join(MODULE, 'resources', 'skins', 'Default', '1080i', 'opentrivia.xml')
MEDIA = os.path.join(MODULE, 'resources', 'skins', 'Default', 'media')
sys.path.insert(0, os.path.join(MODULE, 'lib'))

from opentrivia import config, database, quiz, theme  # noqa: E402

# Every font id in Estuary's Font.xml (Kodi 21). A name that is not in this list silently falls
# back to Kodi's tiny default, which is how font52 / font23 / font20 slipped through once.
FONTS = {'font10', 'font12', 'font13', 'font14', 'font23_narrow', 'font25_narrow', 'font27',
         'font27_narrow', 'font32', 'font37', 'font45', 'font60', 'font20_title', 'font25_title',
         'font30_title', 'font32_title', 'font36_title', 'font40_title', 'font45_title',
         'font52_title', 'font_flag', 'font_clock', 'font_MainMenu'}

PROPS = (set(theme.PROPERTIES) | set(config.VIEW_STRINGS) |
         {'app', 'clock', 'view', 'q', 'qsize', 'osize', 'layout', 'n', 'letters', 'timer', 'chip',
          'kicker', 'progress', 'score_text', 'streak_text', 'result', 'feedback', 'hint',
          'title', 'tagline', 'summary', 'r.score', 'r.accuracy', 'r.best', 'r.counts',
          'msg.title', 'msg.body', 'msg.button', 'paused', 'dim'} |
         {'o%d' % i for i in range(1, 5)} | {'s%d' % i for i in range(1, 5)})


def settings(**kw):
    s = dict((x['id'], x['default']) for x in config.all_settings('app'))
    s.update(kw)
    return s


class Settings(unittest.TestCase):
    def assert_xml(self, folder, who):
        tree = ET.parse(os.path.join(folder, 'resources', 'settings.xml'))
        ids = set(e.get('id') for e in tree.iter('setting'))
        expected = set(s['id'] for s in config.all_settings(who))
        self.assertEqual(ids, expected)

    def test_app_settings_xml_matches_config(self):
        self.assert_xml(APP, 'app')

    def test_saver_settings_xml_matches_config(self):
        self.assert_xml(SAVER, 'ss')

    def test_every_category_has_a_toggle(self):
        rows = [s for s in config.all_settings('app') if s['id'].startswith('cat_')]
        self.assertEqual(len(rows), len(config.CATEGORIES), 22)
        self.assertEqual(set(s['id'] for s in rows), set(config.setting_id(slug) for slug, _ in config.CATEGORIES))
        self.assertTrue(all(s['type'] == 'boolean' and s['default'] for s in rows))

    def test_setting_id_roundtrip(self):
        for slug, _title in config.CATEGORIES:
            self.assertEqual(config.category_slug(config.setting_id(slug)), slug)

    def test_titles_cover_the_database(self):
        self.assertEqual(len(config.TITLES), 22)
        self.assertEqual(config.category_title('science-technology'), 'Science & Technology')

    def test_read_falls_back_to_defaults(self):
        def broken(_sid):
            raise RuntimeError
        s = config.read({'boolean': broken, 'integer': broken, 'string': broken}, 'app')
        self.assertEqual(s, config.defaults('app'))

    def test_sliders_are_clamped_and_options_fall_back(self):
        getters = {'boolean': lambda _sid: True, 'integer': lambda _sid: 5000, 'string': lambda _sid: ''}
        s = config.read(getters, 'app')
        self.assertEqual(s['text_size'], 130)
        self.assertEqual(s['advance_correct_ms'], 3000)
        self.assertEqual(s['dim'], 80)
        self.assertEqual(s['theme'], 0)            # invalid option -> default (Ink)

    def test_nothing_ticked_means_every_category(self):
        self.assertEqual(len(config.selected_categories(settings())), 22)
        only = dict((config.setting_id(slug), False) for slug, _ in config.CATEGORIES)
        only[config.setting_id('music')] = True
        self.assertEqual(config.selected_categories(only), ['music'])
        self.assertEqual(len(config.selected_categories(dict.fromkeys(only, False))), 22)

    def test_session_lengths(self):
        self.assertEqual(config.session_length(settings(session_length=0)), 10)
        self.assertEqual(config.session_length(settings(session_length=3)), 50)
        self.assertIsNone(config.session_length(settings(session_length=4)))
        self.assertEqual(config.session_length(settings(session_length=99)), 20)

    def test_visible_references_an_existing_setting(self):
        by_id = dict((s['id'], s) for s in config.all_settings('app'))
        for s in config.all_settings('app'):
            if 'visible' not in s:
                continue
            rule = s['visible']
            if isinstance(rule, str):
                self.assertIn(rule, by_id, s['id'])
                self.assertEqual(by_id[rule]['type'], 'boolean')
                continue
            other, index = rule[0], rule[-1]
            self.assertIn(other, by_id, s['id'])
            self.assertEqual(by_id[other]['type'], 'options')
            self.assertTrue(0 <= index < len(by_id[other]['options']))
            self.assertNotEqual(by_id[other]['default'], index, s['id'])


class Addons(unittest.TestCase):
    def addon(self, folder):
        tree = ET.parse(os.path.join(folder, 'addon.xml'))
        return tree.getroot()

    def test_ids_and_versions(self):
        for folder, addon_id in ((MODULE, 'script.module.opentrivia'),
                                 (APP, 'script.opentrivia'), (SAVER, 'screensaver.opentrivia')):
            root = self.addon(folder)
            self.assertEqual(root.get('id'), addon_id)
            self.assertEqual(root.get('version'), '1.0.0')
            self.assertEqual(root.get('provider-name'), 'P-Hoep')

    def test_entry_points_and_dependencies(self):
        module = self.addon(MODULE)
        self.assertEqual(module.find('extension').get('point'), 'xbmc.python.module')
        self.assertEqual(module.find('extension').get('library'), 'lib')
        for folder, point in ((APP, 'xbmc.python.script'), (SAVER, 'xbmc.ui.screensaver')):
            root = self.addon(folder)
            self.assertEqual(root.find('extension').get('point'), point)
            requires = set((r.get('addon'), r.get('version')) for r in root.findall('requires/import'))
            self.assertIn(('script.module.opentrivia', '1.0.0'), requires)
            self.assertTrue(os.path.exists(os.path.join(folder, 'default.py')))

    def test_metadata_and_assets(self):
        for folder in (MODULE, APP, SAVER):
            root = self.addon(folder)
            meta = [e for e in root.findall('extension') if e.get('point') == 'xbmc.addon.metadata'][0]
            self.assertTrue(meta.find('summary').text)
            self.assertTrue(meta.find('description').text)
            self.assertEqual(meta.find('license').text, 'MIT')
            icon = meta.find('assets/icon').text
            self.assertTrue(os.path.exists(os.path.join(folder, icon)))
            if folder != MODULE:
                self.assertTrue(os.path.exists(os.path.join(folder, meta.find('assets/fanart').text)))

    def test_license_mentions_the_data_licence(self):
        for folder in (MODULE, APP, SAVER):
            with open(os.path.join(folder, 'LICENSE.txt'), encoding='utf-8') as handle:
                text = handle.read()
            self.assertIn('MIT License', text)
            self.assertIn('CC BY-SA 4.0', text)
            self.assertIn('OpenTriviaQA', text)

    def test_png_icons_are_square_and_big(self):
        for folder in (MODULE, APP, SAVER):
            with open(os.path.join(folder, 'icon.png'), 'rb') as handle:
                head = handle.read(24)
            self.assertEqual(head[:8], b'\x89PNG\r\n\x1a\n')
            width, height = int.from_bytes(head[16:20], 'big'), int.from_bytes(head[20:24], 'big')
            self.assertEqual((width, height), (512, 512))


class Database(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = sqlite3.connect(DB)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_every_category_is_present(self):
        rows = dict(self.db.execute('SELECT category, COUNT(*) FROM questions GROUP BY category'))
        self.assertEqual(set(rows), set(slug for slug, _ in config.CATEGORIES))
        self.assertGreater(min(rows.values()), 100)
        self.assertEqual(sum(rows.values()), 49110)

    def test_ids_are_contiguous(self):
        self.assertEqual(self.db.execute('SELECT MIN(id), MAX(id), COUNT(*) FROM questions').fetchone(),
                         (1, 49110, 49110))

    def test_rows_are_in_random_order(self):
        first = [c for (c,) in self.db.execute('SELECT category FROM questions ORDER BY id LIMIT 200')]
        self.assertGreater(len(set(first)), 15)      # not grouped by category

    def test_choices_and_answer_are_consistent(self):
        for category, question, answer, choices, correct in self.db.execute(
                'SELECT category, question, answer, choices, correct FROM questions'):
            options = json.loads(choices)
            self.assertIn(category, config.TITLES)
            self.assertTrue(2 <= len(options) <= 4, question)
            self.assertEqual(len(options), len(set(options)), question)
            self.assertTrue(0 <= correct < len(options), question)
            self.assertEqual(options[correct], answer, question)

    def test_text_is_clean_and_within_limits(self):
        bad = 0
        for question, answer, choices in self.db.execute('SELECT question, answer, choices FROM questions'):
            options = json.loads(choices)
            if (not question or not answer or len(question) > 420 or len(answer) > 160
                    or any(not c or len(c) > 160 for c in options)
                    or '�' in question + answer or '<' in question + answer
                    or '  ' in question + answer + ''.join(options)
                    or question != question.strip()):
                bad += 1
        self.assertEqual(bad, 0)

    def test_meta(self):
        meta = dict(self.db.execute('SELECT key, value FROM meta'))
        self.assertEqual(meta['source'], 'OpenTriviaQA (github.com/uberspot/OpenTriviaQA)')
        self.assertEqual(meta['license'], 'CC BY-SA 4.0')
        self.assertEqual(meta['count'], '49110')
        self.assertEqual(meta['block'], str(database.BLOCK))


class Blocks(unittest.TestCase):
    def test_reads_are_filtered_and_do_not_repeat(self):
        source = database.Questions(DB, ['animals'])
        try:
            seen = set()
            for _ in range(500):
                item = source.next()
                self.assertEqual(item.category, 'animals')
                self.assertNotIn(item.question, seen)
                seen.add(item.question)
                self.assertEqual(item.choices[item.correct], item.answer)
        finally:
            source.close()

    def test_a_narrow_category_is_not_missed(self):
        source = database.Questions(DB, ['brain-teasers'])
        try:
            self.assertEqual(source.total(), 192)
            questions = set()
            for _ in range(192):
                item = source.next()
                self.assertEqual(item.category, 'brain-teasers')
                questions.add(item.question)
            self.assertEqual(len(questions), 192)
        finally:
            source.close()

    def test_many_pulls_across_blocks_in_one_go(self):
        source = database.Questions(DB, ['music'])
        try:
            items = source.many(1500)
            self.assertEqual(len(items), 1500)
            self.assertEqual(len(set(i.question for i in items)), 1500)
            self.assertTrue(all(i.category == 'music' for i in items))
        finally:
            source.close()

    def test_total_with_and_without_a_filter(self):
        source = database.Questions(DB)
        try:
            self.assertEqual(source.total(), 49110)
        finally:
            source.close()
        source = database.Questions(DB, ['sports', 'history'])
        try:
            expected = 2838 + 1632
            self.assertEqual(source.total(), expected)
        finally:
            source.close()

    def test_round_resets_after_every_block(self):
        source = database.Questions(DB, ['video-games'])
        try:
            # video-games has 595 questions, so 700 draws must wrap the block order once and
            # still return valid questions rather than fail.
            for _ in range(700):
                self.assertEqual(source.next().category, 'video-games')
        finally:
            source.close()


class Theme(unittest.TestCase):
    def test_parse_hex(self):
        self.assertEqual(theme.parse_hex('#AbC123'), 'FFABC123')
        self.assertEqual(theme.parse_hex('abc'), 'FFAABBCC')
        self.assertEqual(theme.parse_hex('80ABC123'), '80ABC123')
        self.assertIsNone(theme.parse_hex('nope'))
        self.assertIsNone(theme.parse_hex(''))

    def test_presets_are_not_rewritten(self):
        for mode in (theme.MODE_INK, theme.MODE_PAPER, theme.MODE_MIDNIGHT):
            palette = theme.resolve(settings(theme=mode), datetime.datetime(2026, 1, 1, 12))
            base = theme.THEMES[mode]
            for key in ('bg', 'card', 'option', 'text', 'muted', 'accent', 'good', 'bad'):
                self.assertEqual(palette[key], base[key], key)
        self.assertEqual(palette['on_accent'], theme.on_colour(base['accent']))
        self.assertEqual(palette['on_good'], theme.on_colour(base['good']))
        self.assertEqual(palette['on_bad'], theme.on_colour(base['bad']))
        for key in ('good', 'bad'):
            self.assertGreater(theme.contrast(palette['on_' + key], base[key]), 3.5, key)

    def test_auto_switches_by_time(self):
        day = theme.resolve(settings(theme=theme.MODE_AUTO), datetime.datetime(2026, 1, 1, 12))
        night = theme.resolve(settings(theme=theme.MODE_AUTO), datetime.datetime(2026, 1, 1, 23))
        self.assertEqual(day['name'], 'paper')
        self.assertEqual(night['name'], 'ink')

    def test_custom_colours(self):
        palette = theme.resolve(settings(theme=theme.MODE_INK, bg_custom='112233', accent=theme.CUSTOM,
                                         accent_custom='#00FF00'), datetime.datetime(2026, 1, 1, 12))
        self.assertEqual(palette['bg'], 'FF112233')
        self.assertEqual(palette['accent'], 'FF00FF00')
        self.assertNotEqual(palette['card'], palette['bg'])      # derived from the custom background
        self.assertNotEqual(palette['option'], palette['card'])

    def test_custom_card_picks_readable_text(self):
        palette = theme.resolve(settings(theme=theme.MODE_INK, card_custom='FFFFFF'),
                                datetime.datetime(2026, 1, 1, 12))
        self.assertEqual(palette['text'], theme.INK_TEXT)
        self.assertGreater(theme.contrast(palette['text'], palette['card']), 7)

    def test_bad_colours_fall_back(self):
        palette = theme.resolve(settings(accent=theme.CUSTOM, accent_custom='not a colour'),
                                datetime.datetime(2026, 1, 1, 12))
        self.assertEqual(palette['accent'], theme.INK['accent'])

    def test_each_theme_has_its_own_default_accent(self):
        now = datetime.datetime(2026, 1, 1, 12)
        self.assertEqual(theme.ACCENT_NAMES[0], 'Theme')
        self.assertEqual(theme.ACCENT_NAMES[theme.CUSTOM], 'Custom')
        self.assertEqual(len(theme.ACCENT_NAMES), len(theme.ACCENTS) + 2)
        ink = theme.resolve(settings(theme=theme.MODE_INK), now)
        paper = theme.resolve(settings(theme=theme.MODE_PAPER), now)
        midnight = theme.resolve(settings(theme=theme.MODE_MIDNIGHT), now)
        self.assertEqual(len({ink['accent'], paper['accent'], midnight['accent']}), 3)
        self.assertEqual(theme.resolve(settings(accent=1), now)['accent'], theme.ACCENTS[0])

    def test_glow_and_dim(self):
        on = theme.resolve(settings(background_style=1), datetime.datetime(2026, 1, 1, 12))
        off = theme.resolve(settings(background_style=0), datetime.datetime(2026, 1, 1, 12))
        self.assertEqual(on['glow_on'], '1')
        self.assertEqual(off['glow_on'], '')
        self.assertEqual(theme.resolve(settings(dim=40), datetime.datetime(2026, 1, 1, 12))['dim_alpha'], '66')

    def test_time_windows_can_cross_midnight(self):
        self.assertTrue(theme.is_day(datetime.datetime(2026, 1, 1, 23), '19:00', '07:00'))
        self.assertFalse(theme.is_day(datetime.datetime(2026, 1, 1, 12), '19:00', '07:00'))
        self.assertTrue(theme.is_day(datetime.datetime(2026, 1, 1, 12), '07:00', '19:00'))


class Quiz(unittest.TestCase):
    def test_question_buckets(self):
        self.assertEqual(quiz.question_bucket('x' * 70), 'xl')
        self.assertEqual(quiz.question_bucket('x' * 71), 'l')
        self.assertEqual(quiz.question_bucket('x' * 150), 'l')
        self.assertEqual(quiz.question_bucket('x' * 151), 'm')
        self.assertEqual(quiz.question_bucket('x' * 300), 'm')
        self.assertEqual(quiz.question_bucket('x' * 301), 's')
        self.assertEqual(quiz.question_bucket('x' * 420), 's')

    def test_text_size_shifts_the_buckets(self):
        self.assertEqual(quiz.question_bucket('x' * 80, 100), 'l')
        self.assertEqual(quiz.question_bucket('x' * 80, 130), 'xl')
        self.assertEqual(quiz.question_bucket('x' * 140, 100), 'l')
        self.assertEqual(quiz.question_bucket('x' * 140, 80), 'm')

    def test_option_buckets(self):
        self.assertEqual(quiz.option_bucket('x' * 52), 'm')
        self.assertEqual(quiz.option_bucket('x' * 53), 's')
        self.assertEqual(quiz.option_bucket('x' * 110), 's')
        self.assertEqual(quiz.option_bucket('x' * 111), 'xs')

    def test_layouts(self):
        s = settings(option_layout=quiz.LAYOUT_AUTO)
        self.assertEqual(quiz.layout(s, ['a', 'b']), 'duo')
        self.assertEqual(quiz.layout(s, ['a', 'b', 'c']), 'stack')
        self.assertEqual(quiz.layout(s, ['a', 'b', 'c', 'd']), 'grid')
        self.assertEqual(quiz.layout(s, ['x' * 65, 'b', 'c', 'd']), 'stack')
        self.assertEqual(quiz.layout(settings(option_layout=quiz.LAYOUT_CARDS), ['x' * 65, 'b', 'c', 'd']), 'grid')
        self.assertEqual(quiz.layout(settings(option_layout=quiz.LAYOUT_LIST), ['a', 'b', 'c', 'd']), 'stack')

    def test_round_scoring(self):
        items = [database.Question('general', 'q%d' % i, ('a', 'b'), 0) for i in range(4)]
        source = FakeSource(items)
        round_ = quiz.Round(source, 3)
        self.assertEqual(round_.remaining, 3)
        q = round_.next_question()
        self.assertEqual(round_.asked, 1)
        self.assertFalse(round_.answered)
        self.assertFalse(round_.answer(1))           # wrong
        self.assertTrue(round_.answer(0))            # the first answer counts
        self.assertEqual((round_.score, round_.missed, round_.streak, round_.best), (0, 1, 0, 0))
        q = round_.next_question()
        self.assertTrue(round_.answer(q.correct))
        round_.answer(1)                             # too late: the first answer counts
        self.assertEqual((round_.score, round_.streak, round_.best), (1, 1, 1))
        q = round_.next_question()
        self.assertTrue(round_.answer(q.correct))
        self.assertEqual((round_.score, round_.streak, round_.best), (2, 2, 2))
        self.assertTrue(round_.done)
        self.assertEqual(round_.remaining, 0)
        self.assertIsNone(round_.next_question())
        self.assertAlmostEqual(round_.accuracy, 200.0 / 3)

    def test_endless_round(self):
        round_ = quiz.Round(FakeSource([database.Question('general', 'q', ('a', 'b'), 0)]), None)
        round_.next_question()
        self.assertFalse(round_.done)
        self.assertIsNone(round_.remaining)


class FakeSource(object):
    def __init__(self, items):
        self.items = list(items)

    def next(self):
        return self.items.pop(0)


class Skin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ET.parse(SKIN)
        cls.root = cls.tree.getroot()

    def test_control_ids(self):
        ids = set(int(c.get('id')) for c in self.root.iter('control') if c.get('id'))
        expected = ({101, 102, 103, 111, 112, 113, 141, 150, 301, 302, 303, 304} |
                    {201, 202, 203, 204} | {211, 212, 213, 214} | {221, 222})
        self.assertEqual(ids, expected)

    def test_textures_exist(self):
        for control in self.root.iter('control'):
            texture = control.find('texture')
            if texture is not None and texture.text and not texture.text.startswith('$'):
                self.assertTrue(os.path.exists(os.path.join(MEDIA, texture.text)), texture.text)

    def test_fonts_come_from_the_skin(self):
        for font in self.root.iter('font'):
            self.assertIn(font.text, FONTS)

    def test_every_property_is_set_by_python(self):
        used = set(re.findall(r'Window\.Property\(ot\.([\w.]+)\)', ET.tostring(self.root, encoding='unicode')))
        self.assertTrue(used)
        self.assertEqual(used - PROPS, set())

    def test_views_and_layouts_are_named(self):
        text = ET.tostring(self.root, encoding='unicode')
        for view in ('start', 'quiz', 'results', 'message'):
            self.assertIn('String.IsEqual(Window.Property(ot.view),%s)' % view, text)
        for layout in ('duo', 'stack', 'grid'):
            self.assertIn('String.IsEqual(Window.Property(ot.layout),%s)' % layout, text)
        for bucket in ('xl', 'l', 'm', 's'):
            self.assertIn('String.IsEqual(Window.Property(ot.qsize),%s)' % bucket, text)
        for bucket in ('m', 's', 'xs'):
            self.assertIn('String.IsEqual(Window.Property(ot.osize),%s)' % bucket, text)

    def test_a_timer_bar_for_every_duration(self):
        timers = [c for c in self.root.iter('control')
                  if c.find('visible') is not None and
                  c.find('visible').text and 'ot.timer' in c.find('visible').text]
        self.assertEqual(len(timers), 58)      # 3..60 seconds
        self.assertEqual(sorted(int(re.findall(r'ot\.timer\),(\d+)\)', c.find('visible').text)[0])
                              for c in timers), list(range(3, 61)))


class Strings(unittest.TestCase):
    def read_po(self, path):
        out = {}
        with open(path, encoding='utf-8') as handle:
            text = handle.read()
        for match in re.finditer(r'msgctxt "#(\d+)"\s*\nmsgid "(.*)"', text):
            out[int(match.group(1))] = match.group(2).replace('\\"', '"')
        return out

    def test_module_strings_match_the_table(self):
        po = self.read_po(os.path.join(MODULE, 'resources', 'language', 'resource.language.en_gb', 'strings.po'))
        self.assertEqual(po, config.STRINGS)

    def test_every_view_string_exists(self):
        for prop, sid in config.VIEW_STRINGS.items():
            self.assertIn(sid, config.STRINGS, prop)

    def test_front_end_strings_cover_their_settings(self):
        for folder, who in ((APP, 'app'), (SAVER, 'ss')):
            po = self.read_po(os.path.join(folder, 'resources', 'language',
                                           'resource.language.en_gb', 'strings.po'))
            labels = set(s['label'] for s in config.all_settings(who))
            self.assertTrue(labels <= set(po.values()), folder)
            self.assertIn(30100, po)       # the first settings string

    def test_percent_strings_format(self):
        self.assertEqual(config.STRINGS[32007] % (3, 10), '3 / 10')
        self.assertEqual(config.STRINGS[32008] % 70, '70% correct')
        self.assertEqual(config.STRINGS[32023] % (2, 10), 'Question 2 of 10')
        self.assertEqual(config.STRINGS[32052] % (config.number(22), config.number(49110)),
                         '22 categories  ·  49,110 questions')


if __name__ == '__main__':
    unittest.main()

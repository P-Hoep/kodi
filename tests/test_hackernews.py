"""Offline tests for the Hacker News screensaver.

The API calls use recorded live JSON from tests/fixtures/hackernews, the offline Algolia
fallback is exercised with a synthetic tree, and nothing here imports xbmc.

python3 -m unittest tests.test_hackernews
"""

import json
import os
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', 'screensaver.hackernews')
sys.path.insert(0, ROOT)

from resources.lib import cache as cache_module  # noqa: E402
from resources.lib import config, formatter, hn_client, playlist  # noqa: E402

FIXTURES = os.path.join(HERE, 'fixtures', 'hackernews')
STORY_ID = 50442736


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding='utf-8') as handle:
        return json.load(handle)


def tr(string_id):
    return config.STRINGS.get(string_id, '#%d' % string_id)


def settings(**overrides):
    values = config.defaults()
    values.update(overrides)
    return values


def sample_story(story_id=1, title='A story', comments=None, **extra):
    story = {
        'id': story_id,
        'title': title,
        'url': 'https://example.com/article',
        'by': 'alice',
        'score': 120,
        'time': 1000000,
        'descendants': 12,
        'text': '',
        'comments': comments or [],
    }
    story.update(extra)
    return story


def comment(by='bob', text='A comment long enough to pass the minimum length setting.', time=1000100, **extra):
    value = {'by': by, 'time': time, 'text': text}
    value.update(extra)
    return value


class HtmlToLabel(unittest.TestCase):
    def test_entities_and_paragraphs(self):
        self.assertEqual(formatter.to_label('A &amp; B<p>C &#x27;quoted&#x27;</p>'),
                         "A & B\n\nC 'quoted'")

    def test_line_break(self):
        self.assertEqual(formatter.to_label('one<br>two<br/>three'), 'one\ntwo\nthree')

    def test_italics(self):
        self.assertEqual(formatter.to_label('<i>really</i> nice'), '[I]really[/I] nice')
        self.assertEqual(formatter.to_label('<em>em</em> and <i>i</i>'),
                         '[I]em[/I] and [I]i[/I]')

    def test_text_link_keeps_its_text(self):
        label = formatter.to_label('read <a href="https://example.com/x">the paper</a> now')
        self.assertEqual(label, 'read the paper now')

    def test_raw_url_link_becomes_the_domain(self):
        label = formatter.to_label(
            '<a href="https://news.ycombinator.com/item?id=4955">'
            'https://news.ycombinator.com/item?id=4955</a>')
        self.assertEqual(label, 'news.ycombinator.com')

    def test_empty_link_uses_the_domain(self):
        self.assertEqual(formatter.to_label('see <a href="https://www.example.org/a"></a>'),
                         'see example.org')

    def test_code_block_is_indented_and_keeps_its_spacing(self):
        label = formatter.to_label('<pre><code>for i in x:\n    print(i)</code></pre>')
        self.assertEqual(label, '    for i in x:\n        print(i)')

    def test_brackets_cannot_be_read_as_kodi_tags(self):
        self.assertEqual(formatter.to_label('[b]not bold[/b] [COLOR=red]x[/COLOR]'),
                         '(b)not bold(/b) (COLOR=red)x(/COLOR)')

    def test_truncates_at_a_sentence(self):
        text = ('One sentence here. ' * 20).strip()
        label = formatter.to_label(text, max_chars=100)
        self.assertLessEqual(len(label), 101)
        self.assertTrue(label.endswith('…'))
        self.assertTrue(label.endswith('One sentence here.…'))

    def test_truncates_at_a_word_when_there_is_no_sentence(self):
        label = formatter.to_label('alpha beta gamma delta epsilon zeta eta theta', max_chars=24)
        self.assertTrue(label.endswith('…'))
        self.assertNotIn(' g…', label)
        self.assertTrue(label[:-1].rstrip().endswith(('alpha', 'beta', 'gamma', 'delta')))

    def test_short_text_is_not_truncated(self):
        self.assertFalse(formatter.to_label('short', max_chars=700).endswith('…'))

    def test_plain_text_has_no_tags(self):
        self.assertEqual(formatter.plain_text('<i>a</i> <b>b</b>'), 'a b')

    def test_domain_handles_www_and_text_posts(self):
        self.assertEqual(formatter.domain('https://www.example.com/a?b=1'), 'example.com')
        self.assertEqual(formatter.domain(''), 'news.ycombinator.com')
        self.assertEqual(formatter.domain(None), 'news.ycombinator.com')

    def test_real_comment_fixture(self):
        tree = load_fixture('algolia_%d.json' % STORY_ID)
        label = formatter.to_label(tree['children'][0]['text'], 700)
        self.assertIn('icann.org', label)
        self.assertNotIn('href', label)
        self.assertNotIn('&#x2F;', label)

    def test_display_seconds_follows_reading_speed(self):
        plain = 'word ' * 55
        self.assertAlmostEqual(formatter.display_seconds(plain, 220, 6, 30), 15.0)
        self.assertEqual(formatter.display_seconds('word', 220, 6, 30), 6)
        self.assertEqual(formatter.display_seconds('word ' * 500, 220, 6, 30), 30)

    def test_age_text(self):
        now = 1000000
        self.assertEqual(formatter.age_text(now - 10, now, 'now', '%s ago'), 'now')
        self.assertEqual(formatter.age_text(now - 3600, now, 'now', '%s ago'), '1 h ago')
        self.assertEqual(formatter.age_text(now - 3 * 86400, now, 'now', '%s ago'), '3 d ago')


class Queue(unittest.TestCase):
    def test_story_then_its_comments(self):
        stories = [sample_story(1, 'First', [comment('bob', 'One comment that is definitely long enough.'),
                                             comment('carol', 'Another one that is also clearly long enough.')]),
                   sample_story(2, 'Second', [])]
        slides = playlist.build({'stories': stories}, settings(randomize=False), tr, now=2000000)
        self.assertEqual([s['kind'] for s in slides],
                         [playlist.STORY, playlist.COMMENT, playlist.COMMENT, playlist.STORY])
        self.assertEqual([s['rank'] for s in slides], [1, 1, 1, 2])
        self.assertEqual(slides[0]['title'], 'First')
        self.assertEqual(slides[1]['author'].split(' · ')[0], 'by bob')

    def test_comments_per_story_setting(self):
        stories = [sample_story(comments=[comment(text='A sufficiently long comment number %d to show.' % i)
                                          for i in range(6)])]
        slides = playlist.build({'stories': stories}, settings(randomize=False, comments=2), tr, now=2000000)
        self.assertEqual(len(slides), 3)
        self.assertEqual(len([s for s in slides if s['kind'] == playlist.COMMENT]), 2)

    def test_short_comments_are_skipped_unless_alone(self):
        stories = [sample_story(comments=[comment(text='tiny'), comment(text='A comment long enough to show.')])]
        slides = playlist.build({'stories': stories}, settings(randomize=False, min_chars=40), tr, now=2000000)
        self.assertEqual([s['kind'] for s in slides], [playlist.STORY, playlist.COMMENT])
        self.assertIn('long enough', slides[1]['text'])

        only_short = [sample_story(comments=[comment(text='tiny')])]
        slides = playlist.build({'stories': only_short}, settings(randomize=False, min_chars=40), tr, now=2000000)
        self.assertEqual(len(slides), 2)      # the longest short one still shows

    def test_first_reply(self):
        reply = comment('dave', 'The reply, which is long enough to appear underneath.')
        stories = [sample_story(comments=[comment(text='Top comment long enough to show.', reply=reply)])]
        slides = playlist.build({'stories': stories}, settings(randomize=False, include_reply=True), tr, now=2000000)
        self.assertIn('> The reply', slides[1]['text'])

        slides = playlist.build({'stories': stories}, settings(randomize=False, include_reply=False), tr, now=2000000)
        self.assertNotIn('reply', slides[1]['text'].lower())

    def test_meta_line_and_setting(self):
        story = sample_story(score=321, by='alice', time=2000000 - 7200)
        slides = playlist.build({'stories': [story]}, settings(randomize=False), tr, now=2000000)
        self.assertEqual(slides[0]['meta'], 'example.com · 321 points · by alice · 2 h ago · 12 comments')

        slides = playlist.build({'stories': [story]}, settings(randomize=False, meta=False), tr, now=2000000)
        self.assertEqual(slides[0]['meta'], 'example.com · 12 comments')

    def test_text_post_domain(self):
        story = sample_story(url='', text='<p>Ask HN: something</p>')
        slides = playlist.build({'stories': [story]}, settings(randomize=False), tr, now=2000000)
        self.assertTrue(slides[0]['meta'].startswith('news.ycombinator.com'))
        self.assertEqual(slides[0]['body'], 'Ask HN: something')

    def test_randomize_rotates_but_keeps_rank_order(self):
        stories = [sample_story(i + 1, 'Story %d' % (i + 1)) for i in range(5)]
        import random
        slides = playlist.build({'stories': stories}, settings(randomize=True), tr, now=2000000,
                                rng=random.Random(7))
        ranks = [s['rank'] for s in slides if s['kind'] == playlist.STORY]
        self.assertEqual(sorted(ranks), [1, 2, 3, 4, 5])
        self.assertNotEqual(ranks, [1, 2, 3, 4, 5])
        self.assertEqual(ranks, sorted(ranks) if ranks[0] == 1 else ranks)

    def test_empty_data(self):
        self.assertEqual(playlist.build({'stories': []}, settings(), tr), [])

    def test_refresh_due(self):
        self.assertFalse(playlist.refresh_due(1000, 1000 + 59, 60))
        self.assertTrue(playlist.refresh_due(1000, 1000 + 60, 60))
        self.assertTrue(playlist.refresh_due(0, 10, 5))


class Client(unittest.TestCase):
    def test_story_list_and_algolia_comments(self):
        ids = load_fixture('topstories.json')
        item = load_fixture('item_%d.json' % STORY_ID)
        tree = load_fixture('algolia_%d.json' % STORY_ID)

        def get(url, **kwargs):
            if url.endswith('/topstories.json'):
                return [STORY_ID]
            if url.endswith('/item/%d.json' % STORY_ID):
                return item
            if url.endswith('/items/%d' % STORY_ID):
                return tree
            raise hn_client.FetchError(url)

        data = hn_client.load('top', limit=1, comments=3, get=get, now=lambda: 42)
        self.assertEqual(data['fetched_at'], 42)
        self.assertEqual(len(data['stories']), 1)
        story = data['stories'][0]
        self.assertEqual(story['title'], '.name Grandfathered')
        self.assertEqual(story['comments'][0]['by'], 'toomuchtodo')
        self.assertEqual(len(story['comments']), 3)

    def test_algolia_failure_falls_back_to_kids(self):
        story = {'id': 5, 'type': 'story', 'title': 'Fallback', 'by': 'a', 'score': 1, 'time': 1,
                 'descendants': 2, 'kids': [51, 52]}
        comments = {51: {'id': 51, 'type': 'comment', 'by': 'x', 'time': 2, 'text': 'first comment'},
                    52: {'id': 52, 'type': 'comment', 'by': 'y', 'time': 3, 'text': 'second comment'}}

        def get(url, **kwargs):
            if url.endswith('/topstories.json'):
                return [5]
            if url.endswith('/item/5.json'):
                return story
            for key, value in comments.items():
                if url.endswith('/item/%d.json' % key):
                    return value
            raise hn_client.FetchError(url)

        data = hn_client.load('top', limit=1, comments=2, get=get, now=lambda: 1)
        self.assertEqual([c['by'] for c in data['stories'][0]['comments']], ['x', 'y'])

    def test_trim_filters(self):
        self.assertIsNone(hn_client.trim_story({'type': 'comment', 'title': 'x'}))
        self.assertIsNone(hn_client.trim_story({'type': 'story', 'title': 'x', 'dead': True}))
        self.assertIsNone(hn_client.trim_story({'type': 'story', 'title': '  '}))
        story = hn_client.trim_story({'id': 1, 'type': 'story', 'title': ' T ',
                                      'kids': [2, 'bad']})
        self.assertEqual(story['title'], 'T')
        self.assertEqual(story['kids'], [2])

    def test_deleted_and_empty_comments_are_skipped(self):
        tree = {'children': [
            {'author': 'a', 'text': None, 'children': []},
            {'author': 'b', 'text': '  ', 'children': []},
            {'author': 'c', 'deleted': True, 'text': 'gone', 'children': []},
            {'author': 'd', 'text': 'kept', 'children': []},
        ]}
        comments = hn_client.algolia_comments(1, 5, get=lambda url, **kw: tree)
        self.assertEqual([c['by'] for c in comments], ['d'])

    def test_first_reply_is_kept_when_asked(self):
        tree = {'children': [{'author': 'a', 'text': 'top', 'children': [
            {'author': 'b', 'text': 'reply', 'children': []},
            {'author': 'c', 'text': 'second reply', 'children': []}]}]}
        comments = hn_client.algolia_comments(1, 1, include_reply=True, get=lambda url, **kw: tree)
        self.assertEqual(comments[0]['reply'], {'by': 'b', 'time': 0, 'text': 'reply'})
        comments = hn_client.algolia_comments(1, 1, include_reply=False, get=lambda url, **kw: tree)
        self.assertNotIn('reply', comments[0])


class Cache(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = [1000.0]
        self.cache = cache_module.Cache(self.folder.name, clock=lambda: self.now[0])

    def test_round_trip(self):
        self.cache.save('top', {'kind': 'top', 'fetched_at': 1000, 'stories': [{'title': 'x'}]})
        data = self.cache.load('top')
        self.assertEqual(data['stories'], [{'title': 'x'}])
        self.assertTrue(self.cache.is_fresh(data, 60))
        self.now[0] = 1060.0
        self.assertFalse(self.cache.is_fresh(data, 60))

    def test_missing_and_broken_files(self):
        self.assertIsNone(self.cache.load('best'))
        with open(os.path.join(self.folder.name, 'best.json'), 'w', encoding='utf-8') as handle:
            handle.write('{not json')
        self.assertIsNone(self.cache.load('best'))
        with open(os.path.join(self.folder.name, 'new.json'), 'w', encoding='utf-8') as handle:
            handle.write('{"stories": "nope"}')
        self.assertIsNone(self.cache.load('new'))

    def test_no_partial_file_after_save(self):
        self.cache.save('top', {'kind': 'top', 'fetched_at': 1, 'stories': []})
        names = [n for n in os.listdir(self.folder.name) if n.endswith('.tmp')]
        self.assertEqual(names, [])

    def test_clear(self):
        self.cache.save('top', {'kind': 'top', 'fetched_at': 1, 'stories': []})
        self.cache.save('ask', {'kind': 'ask', 'fetched_at': 1, 'stories': []})
        self.assertEqual(self.cache.clear(), 2)
        self.assertIsNone(self.cache.load('top'))


class Settings(unittest.TestCase):
    def test_settings_xml_matches_the_table(self):
        tree = ET.parse(os.path.join(ROOT, 'resources', 'settings.xml'))
        ids = set(element.get('id') for element in tree.iter('setting'))
        self.assertEqual(ids, set(config.defaults()) | {'clear_cache'})

    def test_every_label_exists_in_strings(self):
        tree = ET.parse(os.path.join(ROOT, 'resources', 'settings.xml'))
        for element in tree.iter():
            if element.tag in ('setting', 'category', 'group', 'option') and element.get('label'):
                self.assertIn(int(element.get('label')), config.STRINGS, element.get('id'))

    def test_strings_po_matches_the_table(self):
        path = os.path.join(ROOT, 'resources', 'language', 'resource.language.en_gb', 'strings.po')
        entries = {}
        with open(path, encoding='utf-8') as handle:
            lines = handle.read().splitlines()
        for index, line in enumerate(lines):
            if line.startswith('msgctxt "#') and index + 1 < len(lines):
                string_id = int(line.split('#')[1].rstrip('"'))
                msgid = lines[index + 1]
                self.assertTrue(msgid.startswith('msgid "'))
                entries[string_id] = msgid[len('msgid "'):-1]
        self.assertEqual(entries, config.STRINGS)

    def test_read_falls_back_and_clamps(self):
        def broken(_sid):
            raise RuntimeError
        values = config.read({'boolean': broken, 'integer': broken})
        self.assertEqual(values, config.defaults())
        values = config.read({'boolean': lambda _sid: True, 'integer': lambda _sid: 99999})
        self.assertEqual(values['story_seconds'], 60)
        self.assertEqual(values['max_chars'], 2000)
        self.assertLess(values['theme'], len(config.THEMES))

    def test_bad_option_index_falls_back(self):
        values = config.read({'boolean': lambda _sid: False, 'integer': lambda sid: 9})
        self.assertIn(values['list'], range(len(config.LIST_KEYS)))
        self.assertLess(values['theme'], len(config.THEMES))

    def test_list_and_label(self):
        self.assertEqual(config.list_key(settings(list=3)), 'ask')
        self.assertEqual(config.source_label_id(settings(list=3)), 30105)

    def test_themes_and_refresh(self):
        self.assertEqual(len(config.THEMES), 3)
        self.assertEqual(config.refresh_seconds(settings(refresh_minutes=30)), 1800)


class Skin(unittest.TestCase):
    PATH = os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i', 'screensaver-hackernews.xml')

    def setUp(self):
        self.root = ET.parse(self.PATH).getroot()

    def test_required_controls(self):
        ids = set(int(element.get('id')) for element in self.root.iter('control')
                  if element.get('id', '').isdigit())
        for required in (100, 110, 120, 200, 210, 220, 401, 501, 600, 900):
            self.assertIn(required, ids)

    def test_layers_are_mirrored(self):
        with open(self.PATH, encoding='utf-8') as handle:
            text = handle.read()
        properties = set(re.findall(r'Window\.Property\(([^)]+)\)', text))
        layer = [name for name in properties if name.startswith(('hn.a.', 'hn.b.'))]
        self.assertTrue(layer)
        self.assertIn('hn.a.mode', properties)
        self.assertIn('hn.b.ctext', properties)
        self.assertEqual(set(name[5:] for name in layer if name.startswith('hn.a.')),
                         set(name[5:] for name in layer if name.startswith('hn.b.')))
        self.assertEqual(set(name[5:] for name in layer if name.startswith('hn.a.')),
                         {'mode', 'rank', 'title', 'meta', 'storytext',
                          'chead', 'cauthor', 'ctext'})

    def test_properties_the_ui_sets(self):
        with open(os.path.join(ROOT, 'resources', 'lib', 'ui.py'), encoding='utf-8') as handle:
            source = handle.read()
        for prop in ('bg', 'text', 'dim', 'accent', 'track', 'scale', 'clock', 'wordmark',
                     'source', 'status', 'message', 'counter', 'front'):
            self.assertIn("'%s'" % prop, source)


if __name__ == '__main__':
    unittest.main()

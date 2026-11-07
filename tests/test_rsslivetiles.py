"""Offline tests for RSS Live Tiles (script.module.rsslivetiles): feed parsing against saved
real-world feeds (BBC RSS 2.0 + Media RSS, Reddit Atom, NASA enclosures, The Verge Atom with
HTML images) and synthetic RSS 1.0 / XHTML / podcast / malformed feeds, image ranking and
filtering, HTML sanitising, dates, retention and merging, refresh with conditional GET and
backoff, OPML, the packing engine and every layout, the scheduler rules, text fitting, faces,
theme scheduling and the sun calculation, the settings table, QR PNGs and the generated XML.
No network, no Kodi.

python3 -m unittest tests.test_rsslivetiles
"""

import datetime
import glob
import os
import random
import re
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(ROOT, 'script.module.rsslivetiles', 'lib'))
# pyqrcode ships with Kodi (script.module.pyqrcode); use the local Kodi copy when there is one.
for kodi_home in ('~/Library/Application Support/Kodi', '~/.kodi'):
    candidate = os.path.expanduser(os.path.join(kodi_home, 'addons', 'script.module.pyqrcode', 'lib'))
    if os.path.isdir(candidate):
        sys.path.append(candidate)

from rsslivetiles import config, qr, sources, theme  # noqa: E402
from rsslivetiles.feeds import fetcher, images, opml, parser, refresh, sanitize  # noqa: E402
from rsslivetiles.feeds.store import Feed, FeedData, Store, merge, retain  # noqa: E402
from rsslivetiles.tiles import faces, geometry as g, layouts, styles, text  # noqa: E402
from rsslivetiles.tiles.layout import Packer  # noqa: E402
from rsslivetiles.tiles.model import Source, Tile  # noqa: E402
from rsslivetiles.tiles.scheduler import Scheduler  # noqa: E402

FIXTURES = os.path.join(HERE, 'fixtures', 'rsslivetiles')
NOW = 1793000000.0          # Nov 2026


def fixture(name):
    with open(os.path.join(FIXTURES, name), 'rb') as handle:
        return handle.read()


def item(i, published=NOW, image=True, summary='A summary.'):
    imgs = [images.ImageRef('https://example.com/%d.jpg' % i, 800, 450, 'media:content')] if image else []
    return parser.FeedItem('id%d' % i, 'f', 'Headline number %d' % i, summary, '<p>Body</p>',
                           'https://example.com/%d' % i, None, published - i * 600, imgs)


def source(fid='f1', n=8, images_every=2, title='Feed'):
    feed = Feed('https://example.com/%s.xml' % fid, title, id=fid)
    items = [item(i, image=(i % images_every == 0)) for i in range(n)]
    for it in items:
        it.id = '%s-%s' % (fid, it.id)
    return Source(feed, FeedData(fid), items, new_count=3, accent='0050EF')


# ------------------------------------------------------------------ parsing real feeds

class RealFeedsTest(unittest.TestCase):
    def test_bbc_rss_media_thumbnails_upgraded(self):
        info, items = parser.parse(fixture('bbc.xml'), 'bbc', now=NOW)
        self.assertEqual(info.kind, 'rss')
        self.assertEqual(info.title, 'BBC News')
        self.assertTrue(info.image.endswith('.gif'))
        self.assertGreater(len(items), 20)
        first = items[0]
        self.assertTrue(first.title and first.link.startswith('https://www.bbc.co.uk/'))
        self.assertTrue(first.dated)
        self.assertEqual(first.images[0].source, 'media:thumbnail')
        self.assertIn('/ace/standard/800/', first.image)       # 240 px thumbnail upgraded
        self.assertTrue(all(i.images for i in items))

    def test_reddit_atom(self):
        info, items = parser.parse(fixture('reddit.xml'), 'r', now=NOW)
        self.assertEqual(info.kind, 'atom')
        self.assertEqual(info.title, 'Kodi')
        self.assertEqual(info.image, 'https://www.redditstatic.com/icon.png')    # trailing "/" removed
        self.assertEqual(len(items), 25)
        self.assertTrue(all(i.author and i.author.startswith('/u/') for i in items))
        self.assertTrue(any(i.images for i in items))
        for it in items:
            self.assertNotIn('submitted by', it.summary)
            self.assertNotIn('[link]', sanitize.to_kodi(it.content_html))

    def test_nasa_enclosures_and_short_dates(self):
        info, items = parser.parse(fixture('nasa.xml'), 'n', now=NOW)
        self.assertTrue(items)
        self.assertTrue(all(i.images and i.images[0].source == 'enclosure' for i in items))
        self.assertTrue(all(i.dated for i in items))           # "Fri, 06 Nov 2026 16:28 GMT" (no seconds)
        self.assertEqual(items[0].title, "M30's Sparkling Stars")

    def test_verge_atom_images_from_html(self):
        _info, items = parser.parse(fixture('verge.xml'), 'v', now=NOW)
        self.assertTrue(items)
        self.assertTrue(all(i.images for i in items))
        self.assertEqual(items[0].images[0].source, 'content')


# ------------------------------------------------------------------ parsing synthetic feeds

RSS1 = b'''<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
 <channel rdf:about="http://example.org/"><title>RDF site</title><link>http://example.org/</link></channel>
 <image rdf:resource="http://example.org/logo.png"/>
 <item rdf:about="http://example.org/a"><title>First</title><link>http://example.org/a</link>
  <description>Hello &lt;b&gt;world&lt;/b&gt;</description><dc:date>2026-11-05T10:00:00+01:00</dc:date>
  <dc:creator>Ann</dc:creator></item>
</rdf:RDF>'''

ATOM_XHTML = b'''<feed xmlns="http://www.w3.org/2005/Atom"><title type="html">A &amp;lt;b&amp;gt;feed</title>
<link href="https://ex.com/"/><logo>/logo.png</logo>
<entry><id>urn:1</id><title>Entry</title><updated>2026-11-01T00:00:00Z</updated>
<link rel="alternate" href="/posts/1"/><link rel="enclosure" type="audio/mpeg" href="https://ex.com/ep.mp3"/>
<content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml"><p>Para <em>one</em></p>
<img src="https://ex.com/pic.jpg" width="640"/></div></content></entry></feed>'''

PODCAST = b'''<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>
<title>Pod</title><itunes:image href="https://pod.com/cover.jpg"/>
<item><title>Episode 1</title><guid isPermaLink="false">ep1</guid>
<enclosure url="https://pod.com/ep1.mp3" type="audio/mpeg" length="1234"/>
<itunes:image href="https://pod.com/ep1.jpg"/><pubDate>Tue, 03 Nov 2026 08:00:00 -0500</pubDate></item>
</channel></rss>'''

MALFORMED = b'''<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>Bad &nbsp; feed</title>
<item><title>Fish & chips &mdash; cheap</title><link>https://bad.com/1?a=1&b=2</link>
<description>Caf\xc3\xa9 \x01 ok</description></item></channel></rss>'''


class SyntheticFeedsTest(unittest.TestCase):
    def test_rss1(self):
        info, items = parser.parse(RSS1, 'x', now=NOW)
        self.assertEqual((info.kind, info.title, info.image), ('rdf', 'RDF site', 'http://example.org/logo.png'))
        self.assertEqual(items[0].id, 'http://example.org/a')
        self.assertEqual(items[0].summary, 'Hello world')
        self.assertEqual(items[0].author, 'Ann')
        self.assertEqual(items[0].published, parser.parse_date('2026-11-05T09:00:00Z'))

    def test_atom_xhtml_relative_links_and_enclosure(self):
        info, items = parser.parse(ATOM_XHTML, 'x', url='https://ex.com/feed', now=NOW)
        self.assertEqual(info.title, 'A <b>feed')
        self.assertEqual(info.image, 'https://ex.com/logo.png')
        it = items[0]
        self.assertEqual(it.link, 'https://ex.com/posts/1')
        self.assertEqual(it.image, 'https://ex.com/pic.jpg')
        self.assertEqual(it.media.kind, 'audio')
        self.assertIn('[I]one[/I]', sanitize.to_kodi(it.content_html))

    def test_podcast(self):
        info, items = parser.parse(PODCAST, 'p', now=NOW)
        self.assertEqual(info.image, 'https://pod.com/cover.jpg')
        it = items[0]
        self.assertEqual(it.id, 'ep1')
        self.assertEqual(it.image, 'https://pod.com/ep1.jpg')
        self.assertEqual(it.media.url, 'https://pod.com/ep1.mp3')
        self.assertEqual(it.published, parser.parse_date('2026-11-03T13:00:00Z'))

    def test_malformed_is_repaired(self):
        info, items = parser.parse(MALFORMED, 'm', now=NOW)
        self.assertIn('Bad', info.title)
        self.assertEqual(items[0].title, 'Fish & chips — cheap')
        self.assertEqual(items[0].link, 'https://bad.com/1?a=1&b=2')
        self.assertFalse(items[0].dated)
        self.assertEqual(items[0].published, NOW)

    def test_not_a_feed(self):
        with self.assertRaises(parser.FeedError):
            parser.parse(b'<!DOCTYPE html><html><body>hi</body></html>', 'x')
        with self.assertRaises(parser.FeedError):
            parser.parse(b'', 'x')
        with self.assertRaises(parser.FeedError):
            parser.parse(b'<foo/>', 'x')

    def test_item_without_guid_gets_stable_hash(self):
        a = parser.parse(MALFORMED, 'm', now=NOW)[1][0].id
        b = parser.parse(MALFORMED, 'm', now=NOW + 100)[1][0].id
        self.assertEqual(a, b)
        self.assertTrue(a.startswith('h:'))

    def test_roundtrip_dict(self):
        _info, items = parser.parse(PODCAST, 'p', now=NOW)
        again = parser.FeedItem.from_dict(items[0].to_dict())
        self.assertEqual(again.to_dict(), items[0].to_dict())


class DatesTest(unittest.TestCase):
    def test_formats(self):
        z = parser.parse_date('2026-11-06T16:28:00Z')
        self.assertEqual(parser.parse_date('Fri, 06 Nov 2026 16:28:00 GMT'), z)
        self.assertEqual(parser.parse_date('Fri, 06 Nov 2026 16:28 GMT'), z)
        self.assertEqual(parser.parse_date('Fri, 06 Nov 2026 11:28:00 EST'), z)
        self.assertEqual(parser.parse_date('2026-11-06T17:28:00+01:00'), z)
        self.assertEqual(parser.parse_date('2026-11-06 16:28:00'), z)
        self.assertEqual(parser.parse_date('2026-11-06T16:28:00.123Z'), z)
        self.assertIsNone(parser.parse_date('yesterday'))
        self.assertIsNone(parser.parse_date(''))


# ------------------------------------------------------------------ images

class ImagesTest(unittest.TestCase):
    def test_priority_and_size(self):
        ranked = images.rank([
            ('content', 'https://a.com/inline.jpg', 0, 0, ''),
            ('media:thumbnail', 'https://a.com/thumb.jpg', 300, 200, ''),
            ('media:content', 'https://a.com/small.jpg', 400, 300, 'image/jpeg'),
            ('media:content', 'https://a.com/big.jpg', 1200, 800, 'image/jpeg'),
        ])
        self.assertEqual([r.url for r in ranked], ['https://a.com/big.jpg', 'https://a.com/small.jpg',
                                                   'https://a.com/thumb.jpg', 'https://a.com/inline.jpg'])

    def test_filters(self):
        bad = [
            ('content', 'https://a.com/tiny.jpg', 1, 1, ''),
            ('content', 'https://a.com/narrow.jpg', 100, 600, ''),
            ('content', 'https://a.com/logo.svg', 0, 0, ''),
            ('content', 'data:image/png;base64,AAAA', 0, 0, ''),
            ('content', 'https://feeds.feedburner.com/~r/x/1.gif', 0, 0, ''),
            ('content', 'https://s.w.org/images/core/emoji/14/72x72/1f600.png', 0, 0, ''),
            ('content', 'https://example.com/pixel.gif', 0, 0, ''),
            ('enclosure', 'https://a.com/x.jpg', 0, 0, 'image/svg+xml'),
        ]
        self.assertEqual(images.rank(bad), [])

    def test_dedup_relative_and_protocol_relative(self):
        ranked = images.rank([('content', '/a.jpg', 0, 0, ''), ('description', 'https://site.com/a.jpg', 0, 0, ''),
                              ('content', '//cdn.com/b.jpg', 0, 0, '')], base='https://site.com/post')
        self.assertEqual([r.url for r in ranked], ['https://site.com/a.jpg', 'https://cdn.com/b.jpg'])

    def test_srcset_and_html(self):
        cands = images.from_html('<p><img srcset="a.jpg 320w, b.jpg 1024w" src="a.jpg"></p>', 'content')
        self.assertEqual(cands[0][1], 'b.jpg')
        self.assertEqual(images.to_int(cands[0][2]), 1024)

    def test_bbc_upgrade_only_upwards(self):
        self.assertEqual(images.upgrade('https://ichef.bbci.co.uk/ace/standard/240/x/y.jpg'),
                         'https://ichef.bbci.co.uk/ace/standard/800/x/y.jpg')
        self.assertEqual(images.upgrade('https://ichef.bbci.co.uk/ace/standard/976/x/y.jpg'),
                         'https://ichef.bbci.co.uk/ace/standard/976/x/y.jpg')
        self.assertEqual(images.upgrade('https://other.com/240/x.jpg'), 'https://other.com/240/x.jpg')

    def test_og_image(self):
        page = '<head><meta property="og:image" content="https://a.com/og.jpg"><meta name="x"></head>'
        self.assertEqual(images.og_image(page), 'https://a.com/og.jpg')
        self.assertEqual(images.og_image('<p>no</p>'), '')


# ------------------------------------------------------------------ sanitising

class SanitizeTest(unittest.TestCase):
    def test_text(self):
        html = '<p>Hello&nbsp;<b>bold</b></p><script>evil()</script><p>Second <a href="x">link</a></p>'
        self.assertEqual(sanitize.to_text(html), 'Hello bold Second link')

    def test_kodi_markup(self):
        html = ('<h2>Title</h2><p>One <em>two</em> <strong>three</strong></p><ul><li>a</li><li>b</li></ul>'
                '<iframe src="x"></iframe><p>[B]sneaky[/B]</p>')
        out = sanitize.to_kodi(html)
        self.assertTrue(out.startswith('[B]Title[/B][CR][CR]One [I]two[/I] [B]three[/B]'))
        self.assertIn('• a[CR]• b', out)
        self.assertNotIn('iframe', out)
        self.assertIn('(B)sneaky(/B)', out)
        self.assertNotIn('[CR][CR][CR]', out)

    def test_shorten(self):
        self.assertEqual(sanitize.shorten('one two three four five', 14), 'one two three…')
        self.assertEqual(sanitize.shorten('short', 10), 'short')

    def test_plain_text_passthrough(self):
        self.assertEqual(sanitize.to_text('  just   text  '), 'just text')


# ------------------------------------------------------------------ store, retention, refresh

class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = Store(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_sample_feeds_on_first_run(self):
        feeds = self.store.feeds()
        self.assertEqual([f.title for f in feeds], ['BBC News', 'r/kodi', 'NASA Image of the Day'])
        self.assertTrue(os.path.exists(self.store.feeds_path))
        self.assertEqual([f.id for f in Store(self.dir).feeds()], [f.id for f in feeds])

    def test_cache_roundtrip_and_state(self):
        data = FeedData('a', parser.FeedInfo('T'), [item(1)], {'etag': 'x'})
        self.store.save(data)
        loaded = Store(self.dir).load('a')
        self.assertEqual(loaded.info.title, 'T')
        self.assertEqual(loaded.items[0].to_dict(), data.items[0].to_dict())
        self.store.mark_read(['a'], now=123)
        self.store.hide('id1')
        state = self.store.state()
        self.assertEqual(state['last_view']['a'], 123)
        self.assertEqual(state['hidden'], ['id1'])

    def test_retention(self):
        items = [item(i, published=NOW - i * 86400 + i * 600) for i in range(20)]
        kept = retain(items, 30, 7, NOW)
        self.assertEqual(len(kept), 8)                          # days 0..7
        self.assertEqual(len(retain(items, 5, 7, NOW)), 5)
        old = [item(i, published=NOW - 30 * 86400) for i in range(10)]
        self.assertEqual(len(retain(old, 30, 7, NOW)), 3)        # a quiet feed keeps its newest 3

    def test_merge_keeps_first_seen_time_for_undated(self):
        a = item(1)
        b = parser.FeedItem.from_dict(a.to_dict())
        b.published, b.dated = NOW + 999, False
        merged = merge([a], [b])
        self.assertEqual(merged[0].published, a.published)

    def test_sources_hidden_and_new_counts(self):
        feed = Feed('https://x.com/f', 'F', id='f')
        self.store.save(FeedData('f', parser.FeedInfo('F'), [item(i) for i in range(5)]))
        self.store.hide('id0')
        state = self.store.state()
        state['last_view']['f'] = NOW - 1500       # items 0, 1, 2 newer (item 0 hidden)
        srcs = sources.build(self.store, [feed], {}, '0050EF', state)
        self.assertEqual(len(srcs[0].items), 4)
        self.assertEqual(srcs[0].new_count, 2)


class FakeGet(object):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, etag='', last_modified='', timeout=10, limit=0, accept=''):
        self.calls.append((url, etag, last_modified))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.feed = Feed('https://feeds.bbci.co.uk/news/rss.xml', 'BBC', id='bbc')
        self.opts = {'refresh_min': 30, 'max_items': 30, 'max_age_days': 3650, 'timeout': 10}

    def test_success_then_304_then_backoff(self):
        ok = fetcher.Response(200, fixture('bbc.xml'), 'application/rss+xml', 'E1', 'LM1', self.feed.url)
        icon = fetcher.Response(200, b'GIF89a', 'image/gif')
        get = FakeGet([ok, icon])
        data, new = refresh.refresh(self.feed, FeedData('bbc'), self.opts, now=NOW, get=get)
        self.assertEqual(len(new), len(data.items))
        self.assertEqual((data.meta['etag'], data.meta['next_try']), ('E1', NOW + 1800))
        self.assertTrue(data.meta['icon_ok'])

        get = FakeGet([fetcher.Response(304)])
        data2, new2 = refresh.refresh(self.feed, data, self.opts, now=NOW + 1800, get=get)
        self.assertEqual(get.calls[0][1:], ('E1', 'LM1'))
        self.assertEqual(new2, [])
        self.assertEqual(len(data2.items), len(data.items))

        failures = []
        current = data2
        for n in range(1, 9):
            get = FakeGet([fetcher.FetchError('network', 'down')])
            current, _ = refresh.refresh(self.feed, current, self.opts, now=NOW, get=get)
            failures.append(current.meta['next_try'] - NOW)
        self.assertEqual(failures[:4], [300, 600, 1200, 2400])
        self.assertEqual(failures[-1], 6 * 3600)
        self.assertEqual(len(current.items), len(data.items))       # cached items survive
        self.assertIn('down', current.error)

    def test_dead_icon_is_dropped(self):
        ok = fetcher.Response(200, fixture('reddit.xml'), 'application/atom+xml', url='https://r.com/x')
        get = FakeGet([ok, fetcher.FetchError('http', 'HTTP 404', 404)])
        data, _ = refresh.refresh(Feed('https://r.com/x', id='r'), FeedData('r'), self.opts, now=NOW, get=get)
        self.assertEqual(data.info.image, '')
        self.assertFalse(data.meta['icon_ok'])

    def test_due(self):
        self.assertTrue(refresh.is_due(self.feed, FeedData('bbc'), self.opts, NOW))
        data = FeedData('bbc', meta={'checked_at': NOW, 'next_try': NOW + 60})
        self.assertFalse(refresh.is_due(self.feed, data, self.opts, NOW))
        self.assertTrue(refresh.is_due(self.feed, data, self.opts, NOW + 61))


class OpmlTest(unittest.TestCase):
    def test_roundtrip_and_nesting(self):
        feeds = [Feed('https://a.com/rss', 'A & B'), Feed('https://b.com/atom', '')]
        text_ = opml.export(feeds)
        self.assertEqual(opml.parse(text_), [('A & B', 'https://a.com/rss'), ('https://b.com/atom',
                                                                               'https://b.com/atom')])
        nested = ('<opml version="1.0"><body><outline text="News"><outline text="X" xmlUrl="https://x.com/f"/>'
                  '<outline text="X again" xmlUrl="https://x.com/f"/></outline></body></opml>')
        self.assertEqual(opml.parse(nested), [('X', 'https://x.com/f')])
        with self.assertRaises(parser.FeedError):
            opml.parse('<rss/>')


# ------------------------------------------------------------------ layout

class PackerTest(unittest.TestCase):
    def test_first_fit_and_backfill(self):
        p = Packer(rows=6, left=80, top=210)
        p.new_group()
        tiles = [Tile('w', 'item', 'wide'), Tile('m1', 'item', 'medium'), Tile('s', 'item', 'small'),
                 Tile('m2', 'item', 'medium')]
        for t in tiles:
            self.assertTrue(p.place(t))
        self.assertEqual([(t.col, t.row) for t in tiles], [(0, 0), (0, 2), (2, 2), (2, 3)])
        self.assertEqual((tiles[2].x, tiles[2].y), (80 + 2 * g.STEP, 210 + 2 * g.STEP))
        self.assertEqual(len(p.holes()), 24 - 8 - 4 - 1 - 4)

    def test_groups_gap_and_max_bands(self):
        p = Packer(rows=2, left=0, max_bands=2)
        p.new_group()
        self.assertTrue(p.place(Tile('a', 'item', 'wide')))
        p.new_group()
        self.assertTrue(p.place(Tile('b', 'item', 'wide')))
        self.assertEqual(p.band_x, [0, g.BAND_STEP + g.GROUP_GAP])
        self.assertFalse(p.place(Tile('c', 'item', 'wide')))     # no third band on a fixed screen

    def test_no_overlap_in_any_layout(self):
        srcs = [source('a', 30, 2, 'Alpha'), source('b', 12, 3, 'Beta'), source('c', 6, 1, 'Gamma')]
        for name in layouts.NAMES:
            for ss in (False, True):
                if ss and name not in config.SS_LAYOUTS:
                    continue
                ctx = {'rows': g.SS_ROWS if ss else g.HUB_ROWS, 'top': g.SS_TOP if ss else g.HUB_TOP,
                       'left': g.SS_LEFT if ss else g.MARGIN_X, 'max_bands': g.SS_BANDS if ss else None,
                       'clock': ss, 'show_images': True}
                lay = layouts.build(name, srcs, ctx)
                self.assertTrue(lay.tiles, name)
                rects = [(t.x, t.y, t.x + t.w, t.y + t.h) for t in lay.tiles]
                for i, a in enumerate(rects):
                    for b in rects[i + 1:]:
                        overlap = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
                        self.assertFalse(overlap, '%s overlaps in %s' % ((a, b), name))
                ids = [t.id for t in lay.tiles]
                self.assertEqual(len(ids), len(set(ids)), name)
                bottom = max(t.y + t.h for t in lay.tiles)
                self.assertLessEqual(bottom, g.SCREEN_H - 30, name)
                if ss and name != 'spotlight':
                    self.assertLessEqual(max(t.x + t.w for t in lay.tiles), g.SCREEN_W - g.SS_LEFT + 1, name)

    def test_feed_groups(self):
        lay = layouts.build('feed_groups', [source('a', 10), source('b', 0, title='Empty')],
                            {'rows': 6, 'group_items': 3})
        self.assertEqual([h[1] for h in lay.headers], ['Feed', 'Empty'])
        kinds = [(t.kind, t.size) for t in lay.tiles if t.source.id == 'a'][:5]
        self.assertEqual(kinds[:2], [('feed', 'wide'), ('count', 'small')])
        self.assertEqual(sum(1 for t in lay.tiles if t.source.id == 'b'), 2)   # feed + count tile
        bands_a = set(t.band for t in lay.tiles if t.source.id == 'a')
        self.assertEqual(len(bands_a), 1)

    def test_pinned_size(self):
        src = source('a', 10)
        src.feed.tile_size = 'large'
        lay = layouts.build('feed_groups', [src], {'rows': 6})
        self.assertEqual(lay.tiles[0].size, 'large')

    def test_mixed_wall_newest_first_and_images_large(self):
        lay = layouts.build('mixed_wall', [source('a', 10, 1)], {'rows': 6})
        items_ = [t for t in lay.tiles if t.kind == 'item']
        self.assertEqual(items_[0].size, 'large')
        self.assertEqual(items_[0].item.id, 'a-id0')

    def test_spotlight_pages_one_screen_apart(self):
        lay = layouts.build('spotlight', [source('a', 12), source('b', 12)], {'rows': 6, 'left': g.SS_LEFT})
        self.assertEqual(len(lay.pages), 2)
        self.assertEqual(lay.pages[1] - lay.pages[0], g.SCREEN_W)

    def test_mosaic_pictures_only_without_titles(self):
        lay = layouts.build('mosaic', [source('a', 20, 2)], {'rows': 6})
        self.assertTrue(all(t.item.images for t in lay.tiles))
        self.assertTrue(all(t.notitle for t in lay.tiles))
        no_pics = layouts.build('mosaic', [source('a', 5)], {'rows': 6, 'show_images': False})
        self.assertEqual(no_pics.name, 'mixed_wall')

    def test_shade_variation(self):
        lay = layouts.build('feed_groups', [source('a', 10)], {'rows': 6, 'shade': True})
        colours = set(t.colour for t in lay.tiles)
        self.assertEqual(len(colours), 2)
        flat = layouts.build('feed_groups', [source('a', 10)], {'rows': 6, 'shade': False})
        self.assertEqual(set(t.colour for t in flat.tiles), {'0050EF'})


# ------------------------------------------------------------------ scheduler

class SchedulerTest(unittest.TestCase):
    def tiles(self, n):
        out = []
        for i in range(n):
            t = Tile('t%d' % i, 'feed', 'wide', items=[item(1), item(2)])
            out.append(t)
        return out

    def test_rules(self):
        s = Scheduler(liveliness=1, max_active=2, rng=random.Random(1))
        tiles = self.tiles(5)
        picks = []
        now = 0.0
        for _ in range(200):
            t = s.pick(tiles, now, focused='t0', visible={'t1', 't2', 't3'})
            if t:
                picks.append(t.id)
                s.mark(t.id, now + 0.5)
            now += 1.0
        self.assertNotIn('t0', picks)                       # focused never animates
        self.assertNotIn('t4', picks)                       # on-screen tiles preferred
        self.assertTrue(all(a != b for a, b in zip(picks, picks[1:])))   # never twice in a row

    def test_max_active(self):
        s = Scheduler(max_active=2, rng=random.Random(2))
        tiles = self.tiles(4)
        for _ in range(2):
            s.mark(s.pick(tiles, 0.0).id, 10.0)
        self.assertIsNone(s.pick(tiles, 1.0))
        self.assertFalse(s.due(1.0))
        self.assertIsNotNone(s.pick(tiles, 11.0))

    def test_liveliness_intervals(self):
        for level, (lo, hi) in ((0, (6, 10)), (2, (1, 2.5))):
            s = Scheduler(liveliness=level, rng=random.Random(3))
            delays = [s.delay() for _ in range(100)]
            self.assertTrue(lo <= min(delays) and max(delays) <= hi)

    def test_live(self):
        self.assertFalse(Tile('a', 'feed', 'wide', items=[item(1)]).live)
        self.assertTrue(Tile('a', 'item', 'medium', items=[item(0)]).live)
        self.assertFalse(Tile('a', 'item', 'medium', items=[item(1, image=False, summary='')]).live)
        self.assertFalse(Tile('a', 'thumb', 'small', items=[item(0)]).live)


# ------------------------------------------------------------------ text, faces, styles

class TextTest(unittest.TestCase):
    def test_wrap_and_ellipsis(self):
        lines, cut = text.wrap('word ' * 40, 200, 27, 3)
        self.assertEqual(len(lines), 3)
        self.assertTrue(cut)
        self.assertTrue(lines[-1].endswith('…'))
        for line in lines:
            self.assertLessEqual(text.width_px(line, 27), 200)

    def test_short_text_one_line(self):
        self.assertEqual(text.fit('Hello', 500, 27, 3), ('Hello', 1))
        self.assertEqual(text.fit('', 500, 27, 3), ('', 0))

    def test_long_word_is_split(self):
        lines, _ = text.wrap('x' * 80, 150, 25, 4)
        self.assertGreater(len(lines), 1)

    def test_relative_and_initials(self):
        r = lambda s: text.relative(NOW - s, NOW, text.ENGLISH)
        self.assertEqual([r(10), r(600), r(7200), r(100000), r(400000)],
                         ['NOW', '10 MIN AGO', '2 H AGO', 'YESTERDAY', '4 DAYS AGO'])
        self.assertEqual(text.initials('BBC News'), 'BN')
        self.assertEqual(text.initials('r/kodi'), 'RK')
        self.assertEqual(text.initials('Engadget'), 'EN')


class FacesTest(unittest.TestCase):
    def ctx(self, style='classic'):
        strings = dict(text.ENGLISH, new='%d NEW', up_to_date='UP TO DATE', offline='OFFLINE',
                       offline_body='Couldn\'t load', empty='No items yet.')
        return {'style': style, 'palette': theme.resolve({}, datetime.datetime(2026, 11, 6, 22)), 'now': NOW,
                'strings': strings, 'show_images': True}

    def test_image_and_text_faces(self):
        src = source('a', 4)
        tile = Tile('i', 'item', 'wide', src, [src.items[0]])
        face = faces.front(tile, self.ctx())
        self.assertEqual(face['kind'], 'image')
        self.assertTrue(face['img'] and face['ititle'] and face['itl'] in ('1', '2'))
        self.assertTrue(face['meta'].startswith('FEED'))
        text_tile = Tile('t', 'item', 'large', src, [src.items[1]])
        tf = faces.front(text_tile, self.ctx())
        self.assertEqual(tf['kind'], 'text')
        self.assertTrue(tf['sum'])
        self.assertEqual(set(face), set(faces.KEYS))

    def test_summary_face_and_count_face(self):
        src = source('a', 4)
        tile = Tile('i', 'item', 'medium', src, [src.items[1]])
        tile.side = 'back'
        face = faces.front(tile, self.ctx())
        self.assertLessEqual(int(face['tl']), 2)
        self.assertTrue(face['sum'])
        count = Tile('c', 'count', 'small', src)
        self.assertEqual(faces.front(count, self.ctx())['num'], '3')
        count.side = 'back'
        self.assertEqual(faces.front(count, self.ctx())['meta'], '3 NEW')

    def test_outline_colours(self):
        src = source('a', 2)
        tile = Tile('i', 'item', 'medium', src, [src.items[1]])
        face = faces.front(tile, self.ctx('outline'))
        self.assertEqual(face['fg'], 'FF0050EF')
        self.assertEqual(face['bg'], theme.NIGHT['tile'])

    def test_empty_feed_tile(self):
        src = source('a', 0)
        face = faces.front(Tile('f', 'feed', 'wide', src, []), self.ctx())
        self.assertEqual(face['kind'], 'text')
        self.assertIn('No items', face['sum'])

    def test_summary_lines_fit(self):
        for size in ('medium', 'wide', 'large'):
            for n in range(1, g.FACES[size]['title'][1] + 1):
                lines = faces.summary_lines(size, n)
                _l, top, _w, label_y = g.text_area(size)
                tfont = g.FACES[size]['title'][0]
                if lines:
                    sfont = g.FACES[size]['summary'][0]
                    self.assertLessEqual(top + n * g.line_px(tfont) + 8 + lines * g.line_px(sfont), label_y)


# ------------------------------------------------------------------ theme

class ThemeTest(unittest.TestCase):
    def test_palette_and_custom(self):
        self.assertEqual(len(theme.ACCENTS), 20)
        self.assertEqual(theme.global_accent({}), '0050EF')
        self.assertEqual(theme.global_accent({'accent': theme.CUSTOM, 'accent_custom': '#abc'}), 'AABBCC')
        self.assertEqual(theme.global_accent({'accent': theme.CUSTOM, 'accent_custom': 'zz'}), '0050EF')
        self.assertTrue(theme.custom_accent_warning({'accent': theme.CUSTOM, 'accent_custom': 'F0F0A0'}))
        self.assertFalse(theme.custom_accent_warning({'accent': theme.CUSTOM, 'accent_custom': '0050EF'}))
        self.assertEqual(theme.accent_hex('magenta'), 'D80073')

    def test_shade(self):
        self.assertEqual(theme.shade('FFFFFF', -0.5), '808080')
        self.assertEqual(theme.shade('000000', 0.5), '808080')

    def test_modes(self):
        night = datetime.datetime(2026, 11, 6, 22, 0)
        noon = datetime.datetime(2026, 11, 6, 12, 0)
        self.assertEqual(theme.resolve({'theme_mode': theme.MODE_DAY}, night)['name'], 'day')
        self.assertEqual(theme.resolve({'theme_mode': theme.MODE_NIGHT}, noon)['name'], 'night')
        sched = {'theme_mode': theme.MODE_SCHEDULED, 'day_start': '07:00', 'night_start': '19:00'}
        self.assertEqual(theme.resolve(sched, noon)['name'], 'day')
        self.assertEqual(theme.resolve(sched, night)['name'], 'night')
        wrap = dict(sched, day_start='20:00', night_start='06:00')
        self.assertEqual(theme.resolve(wrap, night)['name'], 'day')

    def test_sun_times(self):
        # London on the solstice: sunrise 03:43 UTC, sunset 20:21 UTC.
        rise, sset = theme.sun_times(datetime.date(2026, 6, 21), 51.5074, -0.1278)
        self.assertAlmostEqual(rise, 3 * 60 + 43, delta=3)
        self.assertAlmostEqual(sset, 20 * 60 + 21, delta=3)
        # Minneapolis on 1 January: 07:51 and 16:42 CST (UTC-6).
        rise, sset = theme.sun_times(datetime.date(2026, 1, 1), 44.98, -93.27)
        self.assertAlmostEqual(rise - 360, 7 * 60 + 51, delta=3)
        self.assertAlmostEqual(sset - 360, 16 * 60 + 42, delta=3)
        self.assertEqual(theme.sun_times(datetime.date(2026, 12, 21), 78.2, 15.6), (None, None))
        self.assertEqual(theme.sun_times(datetime.date(2026, 6, 21), 78.2, 15.6), (0.0, 1440.0))

    def test_sun_mode(self):
        s = {'theme_mode': theme.MODE_SUN, 'latitude': 44.98, 'longitude': -93.27, 'utc_offset': -360}
        self.assertTrue(theme.is_day(s, datetime.datetime(2026, 1, 1, 12, 0)))
        self.assertFalse(theme.is_day(s, datetime.datetime(2026, 1, 1, 17, 30)))
        self.assertFalse(theme.is_day(dict(s, sun_offset=30), datetime.datetime(2026, 1, 1, 16, 30)))


# ------------------------------------------------------------------ settings table

class ConfigTest(unittest.TestCase):
    def test_ids_unique_per_addon_and_defaults(self):
        for who in ('app', 'ss'):
            ids = [r['id'] for r in config.rows(who)]
            self.assertEqual(len(ids), len(set(ids)), who)
        d = config.defaults('app')
        self.assertEqual((d['layout'], d['style'], d['accent'], d['refresh_min']), (0, 0, theme.DEFAULT_ACCENT, 30))

    def test_read_types(self):
        values = {'layout': 3, 'show_images': False, 'latitude': '12.5', 'accent': 99}
        getters = {'boolean': lambda k: values[k], 'integer': lambda k: values[k],
                   'string': lambda k: values[k]}
        out = config.read(getters, 'app')
        self.assertEqual(out['layout'], 3)
        self.assertIs(out['show_images'], False)
        self.assertEqual(out['latitude'], 12.5)
        self.assertEqual(out['accent'], theme.DEFAULT_ACCENT)    # out of range -> default
        self.assertEqual(out['refresh_min'], 30)                 # missing -> default

    def test_effective_screensaver(self):
        app = dict(config.defaults('app'), layout=4, style=1, accent=0, theme_mode=1)
        same = config.effective(app, config.defaults('ss'))
        self.assertEqual((same['layout'], same['style'], same['accent'], same['theme_mode']),
                         ('mixed_wall', 'modern', 0, 1))
        own = config.effective(app, dict(config.defaults('ss'), ss_layout=3, ss_style=3, ss_accent=10,
                                         ss_theme_mode=3, ss_day_start='06:00'))
        self.assertEqual((own['layout'], own['style'], own['accent'], own['theme_mode'], own['day_start']),
                         ('mosaic', 'outline', 9, 2, '06:00'))
        self.assertEqual(config.effective(app)['layout'], 'mosaic')

    def test_strings_have_no_bad_formats(self):
        for sid, value in config.STRINGS.items():
            self.assertLessEqual(value.count('%d'), 2, sid)


# ------------------------------------------------------------------ QR and generated files

class QrTest(unittest.TestCase):
    def test_png(self):
        rows = [[1, 0, 1], [0, 1, 0], [1, 0, 1]]
        data = qr.png_bytes(rows, scale=2, quiet=1)
        self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
        side = (3 + 2) * 2
        self.assertEqual(int.from_bytes(data[16:20], 'big'), side)
        raw = zlib.decompress(data[data.index(b'IDAT') + 4:data.index(b'IEND') - 8])
        self.assertEqual(len(raw), side * (side + 1))

    def test_matrix_when_pyqrcode_available(self):
        rows = qr.matrix('https://www.bbc.co.uk/news/articles/cqgkvv8m8pgyo')
        if rows is None:
            self.skipTest('pyqrcode not installed')
        self.assertEqual(len(rows), len(rows[0]))
        self.assertGreaterEqual(len(rows), 25)


class GeneratedFilesTest(unittest.TestCase):
    SKIN = os.path.join(ROOT, 'script.module.rsslivetiles', 'resources', 'skins', 'Default')

    def test_windows_have_every_slot(self):
        for style in styles.STYLES:
            path = os.path.join(self.SKIN, '1080i', styles.window_xml(style))
            root = ET.parse(path).getroot()
            ids = set(int(c.get('id')) for c in root.iter('control') if c.get('id'))
            for size in g.POOLS:
                for i in range(g.POOLS[size]):
                    self.assertIn(g.slot_id(size, i), ids)
            for cid in (g.FOCUS_HOLDER, g.BOARD, g.STRIP, g.DETAIL, g.ZOOMER, g.DETAIL_BODY, 972):
                self.assertIn(cid, ids)

    def test_textures_exist(self):
        used = set()
        for path in glob.glob(os.path.join(self.SKIN, '1080i', '*.xml')):
            with open(path) as handle:
                used.update(re.findall(r'>([\w.]+\.png)<', handle.read()))
        for name in used:
            self.assertTrue(os.path.exists(os.path.join(self.SKIN, 'media', name)), name)

    def test_settings_xml(self):
        for addon in ('script.rsslivetiles', 'screensaver.rsslivetiles'):
            root = ET.parse(os.path.join(ROOT, addon, 'resources', 'settings.xml')).getroot()
            ids = [s.get('id') for s in root.iter('setting')]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertIn('manage_feeds', ids)


if __name__ == '__main__':
    unittest.main()

"""Offline tests for the Audiobookshelf add-on: parsing both item shapes, the book
timeline (tracks, chapters, resume rules), progress-sync bookkeeping, the pending queue,
the cache, and the API client's error mapping against a local fake server. No Kodi.

python3 -m unittest tests.test_audiobookshelf

LIVE=1 ABS_URL=http://host:13378 ABS_KEY=... also runs read-only checks against a real
server (no sessions are opened and no progress is written).
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'plugin.audio.audiobookshelf'))

from resources.lib import api, auth, cache, config, model, sync  # noqa: E402

MINIFIED = {
    'id': 'li1', 'addedAt': 1, 'updatedAt': 2, 'isMissing': False, 'isInvalid': False,
    'media': {'metadata': {'title': 'A Game of Thrones', 'authorName': 'George R. R. Martin',
                           'narratorName': 'Roy Dotrice', 'seriesName': 'A Song of Ice and Fire #1, Other #2.5',
                           'description': '<p>Winter is <b>coming</b>.</p>', 'publishedYear': '1996',
                           'genres': ['Fantasy']},
              'coverPath': '/metadata/items/li1/cover.jpg', 'numChapters': 3, 'duration': 120000.0},
}
EXPANDED = {
    'id': 'li2', 'media': {
        'metadata': {'title': 'Dune Messiah', 'authors': [{'id': 'a1', 'name': 'Frank Herbert'}],
                     'narrators': ['Scott Brick', 'Katherine Kellgren'],
                     'series': [{'id': 's1', 'name': 'Dune', 'sequence': '2'}], 'descriptionPlain': 'Paul rules.'},
        'coverPath': None, 'duration': 300.0,
        'chapters': [{'id': 1, 'start': 100, 'end': 300, 'title': ''}, {'id': 0, 'start': 0, 'end': 100,
                                                                        'title': 'Opening'}]},
    'userMediaProgress': {'currentTime': 150.0, 'progress': 0.5, 'isFinished': False, 'lastUpdate': 9},
}
TRACKS = [{'start': 0.0, 'duration': 100.0, 'path': '/a'}, {'start': 100.0, 'duration': 50.0, 'path': '/b'},
          {'start': 150.0, 'duration': 150.0, 'path': '/c'}]


class Books(unittest.TestCase):
    def test_minified(self):
        b = model.book(MINIFIED)
        self.assertEqual(b['title'], 'A Game of Thrones')
        self.assertEqual(b['author'], 'George R. R. Martin')
        self.assertEqual(b['narrator'], 'Roy Dotrice')
        self.assertEqual(b['series'], [(None, 'A Song of Ice and Fire', '1'), (None, 'Other', '2.5')])
        self.assertEqual(b['description'], 'Winter is coming.')
        self.assertTrue(b['has_cover'])
        self.assertEqual(b['progress']['state'], 'new')
        self.assertEqual(b['num_chapters'], 3)

    def test_expanded(self):
        b = model.book(EXPANDED)
        self.assertEqual(b['author'], 'Frank Herbert')
        self.assertEqual(b['author_ids'], [('a1', 'Frank Herbert')])
        self.assertEqual(b['narrator'], 'Scott Brick, Katherine Kellgren')
        self.assertEqual(b['series'], [('s1', 'Dune', '2')])
        self.assertFalse(b['has_cover'])
        self.assertEqual([c['title'] for c in b['chapters']], ['Opening', 'Chapter 2'])
        self.assertEqual(b['progress']['state'], 'progress')
        self.assertAlmostEqual(b['progress']['fraction'], 0.5)

    def test_series_filter_shape(self):
        # A list filtered by series carries metadata.series as one dict.
        item = {'id': 'x', 'media': {'metadata': {'title': 'T', 'series': {'id': 's', 'name': 'S',
                                                                          'sequence': '3'}}}}
        self.assertEqual(model.sequence_in(model.book(item), series_id='s'), '3')

    def test_missing_everything(self):
        b = model.book({'id': 'z'})
        self.assertEqual(b['title'], 'Untitled')
        self.assertEqual(b['author'], '')
        self.assertEqual(b['series'], [])
        self.assertEqual(b['duration'], 0)

    def test_finished(self):
        p = model.progress_state({'currentTime': 10, 'isFinished': True, 'progress': 1}, 100)
        self.assertEqual(p['state'], 'finished')

    def test_progress_map_skips_episodes(self):
        me = {'mediaProgress': [{'libraryItemId': 'a', 'currentTime': 1},
                                {'libraryItemId': 'b', 'episodeId': 'e', 'currentTime': 2}]}
        self.assertEqual(list(model.progress_map(me)), ['a'])

    def test_sequence_order(self):
        seqs = ['10', '', '2', '1.5', '1']
        self.assertEqual(sorted(seqs, key=model.sequence_key), ['1', '1.5', '2', '10', ''])


class Timeline(unittest.TestCase):
    def test_locate(self):
        self.assertEqual(model.locate(TRACKS, 0), (0, 0))
        self.assertEqual(model.locate(TRACKS, 99.5), (0, 99.0))  # clamped 1 s short of the track end
        self.assertEqual(model.locate(TRACKS, 120), (1, 20))
        self.assertEqual(model.locate(TRACKS, 200), (2, 50))
        self.assertEqual(model.locate([], 5), (0, 0))

    def test_round_trip(self):
        for t in (0, 42, 100, 149, 151, 299):
            i, off = model.locate(TRACKS, t)
            self.assertAlmostEqual(model.book_time(TRACKS, i, off), t)
        self.assertIsNone(model.book_time(TRACKS, 5, 0))

    def test_tracks_from_session(self):
        session = {'audioTracks': [{'index': 2, 'startOffset': 100, 'duration': 50, 'contentUrl': '/b'},
                                   {'index': 1, 'startOffset': 0, 'duration': 100, 'contentUrl': '/a'},
                                   {'index': 3, 'startOffset': 150, 'duration': 1}]}
        self.assertEqual([t['path'] for t in model.tracks(session)], ['/a', '/b'])

    def test_chapter_at(self):
        chapters = model.chapters([{'start': 0, 'end': 10}, {'start': 10, 'end': 20}, {'start': 20, 'end': 30}])
        self.assertEqual(model.chapter_at(chapters, 0), 0)
        self.assertEqual(model.chapter_at(chapters, 9.9), 1)  # within half a second of the next
        self.assertEqual(model.chapter_at(chapters, 25), 2)
        self.assertEqual(model.chapter_at([], 5), -1)

    def test_resume_rules(self):
        new = model.progress_state(None)
        self.assertEqual(model.start_position(new, 1000), 0)
        mid = model.progress_state({'currentTime': 500}, 1000)
        self.assertEqual(model.start_position(mid, 1000), 500)
        self.assertEqual(model.start_position(mid, 1000, rewind=10), 490)
        done = model.progress_state({'currentTime': 500, 'isFinished': True}, 1000)
        self.assertEqual(model.start_position(done, 1000), 0)  # finished books start again
        end = model.progress_state({'currentTime': 990}, 1000)
        self.assertEqual(model.start_position(end, 1000), 0)

    def test_formatting(self):
        self.assertEqual(model.clock(3725), '1:02:05')
        self.assertEqual(model.clock(65), '1:05')
        self.assertEqual(model.length(3725), '1h 02m')
        self.assertEqual(model.length(600), '10m')
        self.assertEqual(model.length(30), '30s')


class Tracking(unittest.TestCase):
    def test_listened_time_and_due(self):
        t = sync.Tracker(1000, interval=30, now=0)
        for second in range(0, 31):
            t.tick(100 + second, True, second)
        self.assertAlmostEqual(t.listened, 30)
        self.assertTrue(t.due(31))
        payload = t.payload()
        self.assertEqual(payload['currentTime'], 130)
        t.sent(payload, 31)
        self.assertEqual(t.listened, 0)
        self.assertFalse(t.due(40))

    def test_paused_time_is_not_listening(self):
        t = sync.Tracker(1000, 30, 0)
        t.tick(10, True, 0)
        t.tick(11, True, 1)
        for second in range(2, 100):
            t.tick(11, False, second)
        self.assertAlmostEqual(t.listened, 1)

    def test_stall_is_capped(self):
        t = sync.Tracker(1000, 30, 0)
        t.tick(10, True, 0)
        t.tick(11, True, 600)  # the box slept
        self.assertEqual(t.listened, sync.MAX_LISTEN_STEP)

    def test_failure_keeps_time_and_backs_off(self):
        t = sync.Tracker(1000, 10, 0)
        for second in range(12):
            t.tick(second, True, second)
        self.assertTrue(t.due(12))
        t.failed(12)
        self.assertFalse(t.due(20))
        self.assertTrue(t.due(12 + sync.RETRY_BACKOFF[0]))
        self.assertGreater(t.listened, 10)

    def test_end_of_book(self):
        t = sync.Tracker(1000, 30, 0)
        t.tick(990, True, 0)
        self.assertEqual(t.payload(ended=True)['currentTime'], 1000)
        self.assertEqual(t.payload(ended=False)['currentTime'], 990)
        self.assertTrue(sync.near_end(990, 1000))
        self.assertFalse(sync.near_end(500, 1000))

    def test_stopping_early_is_not_finishing(self):
        t = sync.Tracker(1000, 30, 0)
        t.tick(300, True, 0)
        self.assertEqual(t.payload()['currentTime'], 300)

    def test_nothing_to_send_when_idle(self):
        t = sync.Tracker(1000, 30, 0)
        self.assertFalse(t.due(100))  # no position yet


class FakeClient(object):
    def __init__(self, server_update=0, down=False):
        self.server_update = server_update
        self.down = down
        self.sent = []

    def progress(self, item_id):
        if self.down:
            raise api.Unreachable('down')
        return {'lastUpdate': self.server_update}

    def update_progress(self, item_id, current_time, duration):
        self.sent.append((item_id, current_time))


class PendingQueue(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.pending = sync.Pending(os.path.join(self.dir, 'pending.json'))

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_sends_and_clears(self):
        self.pending.add('b1', 500, 1000, now=100)
        client = FakeClient(server_update=1)
        self.assertEqual(self.pending.flush(client, now=101), 1)
        self.assertEqual(client.sent, [('b1', 500)])
        self.assertEqual(self.pending.load(), {})

    def test_newer_server_update_wins(self):
        self.pending.add('b1', 500, 1000, now=100)
        client = FakeClient(server_update=200 * 1000)
        self.pending.flush(client, now=201)
        self.assertEqual(client.sent, [])
        self.assertEqual(self.pending.load(), {})

    def test_server_down_keeps_then_gives_up(self):
        self.pending.add('b1', 500, 1000, now=100)
        client = FakeClient(down=True)
        self.pending.flush(client, now=101)
        self.assertEqual(self.pending.load()['b1']['attempts'], 1)
        for _ in range(sync.PENDING_MAX_ATTEMPTS):
            self.pending.flush(client, now=101)
        self.assertEqual(self.pending.load(), {})


class Settings(unittest.TestCase):
    def test_defaults_and_bad_values(self):
        values = {'server_url': '192.168.1.5:13378/', 'api_key': ' k ', 'timeout': 999, 'sort': 7,
                  'auth_method': 0, 'username': ''}
        getter = lambda sid: values[sid] if sid in values else (_ for _ in ()).throw(KeyError(sid))
        s = config.read({'boolean': getter, 'integer': getter, 'string': getter})
        self.assertEqual(s['server_url'], 'http://192.168.1.5:13378')
        self.assertEqual(s['api_key'], 'k')
        self.assertEqual(s['timeout'], 60)
        self.assertEqual(s['sort'], len(config.SORTS) - 1)
        self.assertEqual(s['sync_interval'], 30)
        self.assertTrue(s['use_api_key'])  # an install from 1.0 keeps its key until a username is set
        values['username'] = 'me'
        self.assertFalse(config.read({'boolean': getter, 'integer': getter, 'string': getter})['use_api_key'])

    def test_settings_file_is_current(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'plugin.audio.audiobookshelf')
        xml = open(os.path.join(root, 'resources', 'settings.xml')).read()
        for s in config.all_settings():
            self.assertIn('id="%s"' % s['id'], xml)
        self.assertIn('<hidden>true</hidden>', xml)  # the API key is masked


class Caching(unittest.TestCase):
    def test_ttl_and_scope(self):
        folder = tempfile.mkdtemp()
        try:
            c = cache.Cache(folder, 60, 'http://a')
            calls = []
            self.assertEqual(c.fetch('k', lambda: calls.append(1) or {'v': 1}), {'v': 1})
            self.assertEqual(c.fetch('k', lambda: calls.append(1) or {'v': 2}), {'v': 1})
            self.assertEqual(len(calls), 1)
            self.assertIsNone(cache.Cache(folder, 60, 'http://b').get('k'))
            self.assertIsNone(cache.Cache(folder, 0, 'http://a').get('k'))
            c.clear()
            self.assertIsNone(c.get('k'))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


def jwt(kind, lifetime, serial):
    import base64

    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip('=')
    now = int(time.time())
    return '%s.%s.sig' % (part({'alg': 'HS256'}), part({'type': kind, 'iat': now, 'exp': now + lifetime, 'n': serial}))


class FakeAuthServer(object):
    """Token state shared by the request handler: valid access and refresh tokens."""
    access, refresh, logins, refreshes, serial = set(), set(), 0, 0, 0
    access_life = 12 * 3600

    @classmethod
    def issue(cls):
        cls.serial += 1
        a, r = jwt('access', cls.access_life, cls.serial), jwt('refresh', 7 * 86400, cls.serial)
        cls.access.add(a)
        cls.refresh.add(r)
        return {'user': {'username': 'reader', 'accessToken': a, 'refreshToken': r}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def authorised(self):
        token = (self.headers.get('Authorization') or '')[len('Bearer '):]
        return token == 'good' or token in FakeAuthServer.access

    def reply(self, code, body, kind='application/json'):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/status':
            return self.reply(200, {'app': 'audiobookshelf', 'serverVersion': '2.28.0'})
        if not self.authorised():
            return self.reply(401, 'Unauthorized', 'text/plain')
        if self.path == '/api/me':
            return self.reply(200, {'username': 'u', 'mediaProgress': []})
        if self.path == '/api/libraries':
            return self.reply(200, {'libraries': [{'id': 'p', 'mediaType': 'podcast'},
                                                  {'id': 'b', 'mediaType': 'book'}]})
        if self.path.startswith('/api/me/progress/'):
            return self.reply(404, 'Not Found', 'text/plain')
        if self.path == '/api/garbage':
            return self.reply(200, '<html>', 'text/html')
        self.reply(500, 'boom', 'text/plain')

    def do_POST(self):
        length = int(self.headers.get('Content-Length') or 0)
        body = json.loads(self.rfile.read(length) or b'{}')
        if self.path == '/login':
            if body == {'username': 'reader', 'password': 'pw'} and self.headers.get('x-return-tokens') == 'true':
                FakeAuthServer.logins += 1
                return self.reply(200, FakeAuthServer.issue())
            return self.reply(401, 'Unauthorized', 'text/plain')
        if self.path == '/auth/refresh':
            token = self.headers.get('x-refresh-token')
            if token in FakeAuthServer.refresh:
                FakeAuthServer.refresh.discard(token)  # rotation: a refresh token works once
                FakeAuthServer.refreshes += 1
                return self.reply(200, FakeAuthServer.issue())
            return self.reply(401, 'Unauthorized', 'text/plain')
        if self.path == '/api/session/s1/sync' and 'currentTime' in body and 'timeListened' in body:
            return self.reply(200, 'OK', 'text/plain')
        self.reply(404, 'Not Found', 'text/plain')


class Client(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(('127.0.0.1', 0), Handler)
        cls.url = 'http://127.0.0.1:%d' % cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_ok(self):
        c = api.Client(self.url, 'good', 5)
        self.assertEqual(c.status()['serverVersion'], '2.28.0')
        self.assertEqual(c.me()['username'], 'u')
        self.assertEqual([lib['id'] for lib in c.libraries()], ['b'])  # podcasts are left out
        self.assertIsNone(c.progress('never-started'))
        self.assertEqual(c.sync_session('s1', 10, 5, 100), 'OK')

    def test_errors(self):
        with self.assertRaises(api.AuthError):
            api.Client(self.url, 'bad', 5).me()
        with self.assertRaises(api.NotFound):
            api.Client(self.url, 'good', 5).sync_session('gone', 1, 1, 1)
        with self.assertRaises(api.ApiError):
            api.Client(self.url, 'good', 5).get('/api/garbage')
        with self.assertRaises(api.Unreachable):
            api.Client('http://127.0.0.1:9', 'good', 2).me()
        with self.assertRaises(api.NotConfigured):
            api.Client('', '', 2).me()

    def test_key_stays_out_of_messages_and_urls(self):
        c = api.Client(self.url, 'secret-key', 5)
        try:
            c.me()
        except api.ApiError as error:
            self.assertNotIn('secret-key', str(error))
        self.assertNotIn('secret', c.cover_url('i', 5))
        self.assertTrue(c.stream_url('/api/items/i/file/1').endswith('|Authorization=Bearer%20secret-key'))

    def test_filter_encoding(self):
        self.assertEqual(api.b64('abc'), 'YWJj')


class SignIn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(('127.0.0.1', 0), Handler)
        cls.url = 'http://127.0.0.1:%d' % cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, 'tokens.json')
        FakeAuthServer.access_life = 12 * 3600
        FakeAuthServer.logins = FakeAuthServer.refreshes = 0

    def tearDown(self):
        shutil.rmtree(self.dir)

    def read_tokens(self):
        with open(self.path) as handle:
            return handle.read()

    def client(self, password='pw'):
        return api.Client(self.url, auth.Login('reader', password, self.path), 5)

    def test_signs_in_once_and_reuses_the_token(self):
        c = self.client()
        self.assertEqual(c.me()['username'], 'u')
        self.client().me()  # a new process reads tokens.json
        self.assertEqual((FakeAuthServer.logins, FakeAuthServer.refreshes), (1, 0))
        self.assertNotIn('pw', self.read_tokens())  # the password is never written to the token file

    def test_refreshes_a_token_that_is_about_to_expire(self):
        FakeAuthServer.access_life = 60  # inside the refresh margin
        self.client().me()
        self.client().me()
        self.assertEqual((FakeAuthServer.logins, FakeAuthServer.refreshes), (1, 1))

    def test_playback_asks_for_a_token_that_lasts(self):
        FakeAuthServer.access_life = 3600
        c = self.client()
        c.me()
        c.stream_url('/f', min_valid=8 * 3600)
        self.assertEqual(FakeAuthServer.refreshes, 1)

    def test_used_refresh_token_falls_back_to_signing_in(self):
        self.client().me()
        saved = json.loads(self.read_tokens())
        FakeAuthServer.refresh.discard(saved['refresh'])  # another process used it
        FakeAuthServer.access.discard(saved['access'])    # and the access token was revoked
        self.assertEqual(self.client().me()['username'], 'u')
        self.assertEqual(FakeAuthServer.logins, 2)

    def test_wrong_password(self):
        with self.assertRaises(api.AuthError) as caught:
            self.client(password='nope').me()
        self.assertIn('Wrong username or password', str(caught.exception))

    def test_signed_out_without_password(self):
        with self.assertRaises(api.AuthError):
            self.client(password='').me()

    def test_jwt_expiry(self):
        self.assertAlmostEqual(auth.jwt_expiry(jwt('access', 100, 0)), time.time() + 100, delta=2)
        self.assertIsNone(auth.jwt_expiry('not-a-jwt'))


@unittest.skipUnless(os.environ.get('LIVE') and os.environ.get('ABS_URL') and os.environ.get('ABS_KEY'),
                     'set LIVE=1 ABS_URL=... ABS_KEY=... to check a real server')
class Live(unittest.TestCase):
    """Read-only: browses the server and parses what comes back."""

    def setUp(self):
        self.c = api.Client(config.normalise_url(os.environ['ABS_URL']), os.environ['ABS_KEY'], 20)

    def test_browse(self):
        self.c.status()
        progress = model.progress_map(self.c.me())
        libraries = self.c.libraries()
        self.assertTrue(libraries)
        lib = libraries[0]['id']
        page = self.c.items(lib, 0, 20)
        self.assertGreater(page['total'], 0)
        books = [model.book(i, progress.get(i['id'])) for i in page['results']]
        self.assertTrue(all(b['title'] for b in books))
        for name, key, desc in config.SORTS:
            self.assertTrue(self.c.items(lib, 0, 5, key, desc)['results'], name)
        series = self.c.series(lib, 0, 5)['results']
        if series:
            filtered = self.c.items(lib, 0, 50, filter='series.' + api.b64(series[0]['id']), minified=False)
            self.assertTrue(filtered['results'])
        authors = self.c.authors(lib)
        if authors:
            self.assertTrue(self.c.items(lib, 0, 5, filter='authors.' + api.b64(authors[0]['id']))['results'])
        self.assertIn('book', self.c.search(lib, 'the', 5))
        item = self.c.item(page['results'][0]['id'])
        b = model.book(item)
        self.assertGreater(b['duration'], 0)


if __name__ == '__main__':
    unittest.main()

"""Offline tests for the GeoGuess screensaver: the settings table, label cleaning and country
names, the pan geometry, the datasets-server client (batching, recent rows, backoff, source
rotation, abort), image header parsing, the temp store, expired-URL re-requests and the files
Kodi needs. No network, no Kodi.

python3 -m unittest tests.test_geoguess
"""

import os
import shutil
import struct
import sys
import tempfile
import unittest
import unittest.mock as mock
import xml.etree.ElementTree as ElementTree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screensaver.geoguess'))

from resources.lib import config, downloader, hf_client, labels, layout  # noqa: E402

ADDON_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                                          'screensaver.geoguess'))


class FakeRandom(object):
    def __init__(self, offset=0):
        self.offset = offset
        self.asked = []
        self.shuffled = 0

    def randint(self, low, high):
        self.asked.append((low, high))
        return self.offset if low <= self.offset <= high else low

    def shuffle(self, items):
        self.shuffled += 1
        items.reverse()


def row(idx, country='SI', address='A place', src='https://example/img.jpg', width=100, height=50):
    return {'row_idx': idx,
            'row': {'image': {'src': src, 'width': width, 'height': height},
                    'country_iso_alpha2': country, 'address': address}}


def rows_payload(items, total=1000):
    return {'rows': items, 'num_rows_total': total}


class SettingsTable(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = [s['id'] for s in config.all_settings()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_spec_defaults(self):
        values = config.defaults()
        self.assertEqual(values['reveal_after'], 8)
        self.assertEqual(values['show_for'], 25)
        self.assertEqual(values['batch_size'], 40)
        self.assertTrue(values['show_country_name'])
        self.assertTrue(values['pan_enabled'])
        self.assertEqual(values['label_size'], 1)

    def test_slider_ranges_match_the_spec(self):
        by_id = dict((s['id'], s) for s in config.all_settings())
        self.assertEqual((by_id['reveal_after']['min'], by_id['reveal_after']['max']), (1, 60))
        self.assertEqual((by_id['show_for']['min'], by_id['show_for']['max']), (5, 120))
        self.assertEqual((by_id['batch_size']['min'], by_id['batch_size']['max']), (10, 100))
        self.assertEqual(by_id['label_size']['options'], ['Small', 'Medium', 'Large'])

    def test_read_keeps_defaults_when_a_setting_is_missing(self):
        class Empty(object):
            def getSetting(self, sid):
                return ''

        values = config.read(Empty())
        self.assertTrue(values['show_country_name'])
        self.assertTrue(values['pan_enabled'])
        self.assertEqual(values['reveal_after'], 8)

    def test_timing_clamps(self):
        self.assertEqual(config.timing({'reveal_after': 8, 'show_for': 25}), (8.0, 25))
        self.assertEqual(config.timing({'reveal_after': 200, 'show_for': 10}), (9.0, 10))
        self.assertEqual(config.timing({'reveal_after': -4, 'show_for': 1}), (0.5, 5))

    def test_batch_size_clamps(self):
        self.assertEqual(config.batch_size({'batch_size': 3}), 10)
        self.assertEqual(config.batch_size({'batch_size': 500}), 100)
        self.assertEqual(config.batch_size({'batch_size': 40}), 40)

    def test_strings_are_above_the_settings_range(self):
        self.assertTrue(all(sid >= 32000 for sid in config.STRINGS))
        self.assertEqual(len(config.LABEL_FONTS), 3)


class LabelCleaning(unittest.TestCase):
    def test_coordinate_suffix_is_stripped(self):
        self.assertEqual(labels.clean_address('Jarše Slovenia_46.1069942_14.9378597'),
                         'Jarše Slovenia')
        self.assertEqual(labels.clean_address('  Somewhere   Else_1_-2.5 '), 'Somewhere Else')

    def test_whitespace_is_tidied(self):
        self.assertEqual(labels.clean_address('  a\t b\n c '), 'a b c')
        self.assertEqual(labels.clean_address(None), '')

    def test_country_is_appended_when_missing(self):
        self.assertEqual(labels.display_label('106 109, 1315 Velike Lašče', 'SI'),
                         '106 109, 1315 Velike Lašče, Slovenia')
        self.assertEqual(labels.display_label('Ulica, Warszawa', 'PL'), 'Ulica, Warszawa, Poland')

    def test_localized_country_is_not_repeated(self):
        self.assertEqual(labels.display_label('Maribor, Słowenia', 'SI'), 'Maribor, Słowenia')
        self.assertEqual(labels.display_label('Seoul, Corée du Sud', 'KR'), 'Seoul, Corée du Sud')
        self.assertEqual(labels.display_label('東京, 日本', 'JP'), '東京, 日本')
        self.assertEqual(labels.display_label('Kraków, Polska', 'PL'), 'Kraków, Polska')
        self.assertEqual(labels.display_label('São Paulo, Brazylia', 'BR'), 'São Paulo, Brazylia')

    def test_english_name_is_not_repeated(self):
        self.assertEqual(labels.display_label('Velike Lašče, Slovenia', 'SI'),
                         'Velike Lašče, Slovenia')
        self.assertEqual(labels.display_label('Austin, United States', 'US'),
                         'Austin, United States')
        self.assertEqual(labels.display_label('Austin, USA', 'US'), 'Austin, USA')

    def test_abbreviation_inside_a_word_is_not_a_match(self):
        self.assertFalse(labels.ends_with_country('Nicosia, Cyprus', 'US'))
        self.assertEqual(labels.display_label('Nicosia, Cyprus', 'US'),
                         'Nicosia, Cyprus, United States')

    def test_missing_address_falls_back_to_the_country(self):
        self.assertEqual(labels.display_label('', 'SI'), 'Slovenia')
        self.assertEqual(labels.display_label(None, 'NZ'), 'New Zealand')
        self.assertEqual(labels.display_label('', 'SI', show_country=False), 'Slovenia')
        self.assertEqual(labels.display_label('', 'ZZ'), 'ZZ')

    def test_show_country_off_keeps_the_dataset_address(self):
        self.assertEqual(labels.display_label('Ulica, Warszawa', 'PL', show_country=False),
                         'Ulica, Warszawa')
        self.assertEqual(labels.display_label('Jarše Slovenia_1_2', 'SI', show_country=False),
                         'Jarše Slovenia')

    def test_non_ascii_survives(self):
        self.assertIn('Łódź', labels.display_label('Łódź, Polska', 'PL'))
        self.assertIn('Üsküdar', labels.display_label('Üsküdar', 'TR'))

    def test_every_dataset_country_is_known(self):
        self.assertEqual(len(labels.COUNTRY_NAMES), 55)
        for code, name in labels.COUNTRY_NAMES.items():
            self.assertTrue(name)
            self.assertEqual(labels.display_label('X', code), 'X, %s' % name)


class LayoutMath(unittest.TestCase):
    def test_full_height_width_follows_aspect(self):
        width, height = layout.display_size(3030, 561, 1920, 1080)
        self.assertEqual(height, 1080)
        self.assertEqual(width, int(round(3030 * 1080.0 / 561)))

    def test_unknown_size_fills_the_screen(self):
        self.assertEqual(layout.display_size(0, 0, 1920, 1080), (1920, 1080))
        self.assertEqual(layout.display_size(-4, 10, 1920, 1080), (1920, 1080))

    def test_pan_runs_from_left_edge_to_right_edge(self):
        width = 5835
        extent = width - 1920
        self.assertEqual(layout.pan_offset(width, 1920, 0, 25), 0)
        self.assertEqual(layout.pan_offset(width, 1920, 25, 25), -extent)
        self.assertAlmostEqual(layout.pan_offset(width, 1920, 12.5, 25), -extent / 2.0, delta=1)

    def test_pan_is_clamped_after_the_end(self):
        self.assertEqual(layout.pan_offset(4000, 1920, 99, 25), -2080)

    def test_pan_is_smooth_and_monotonic(self):
        previous = 0
        for step in range(101):
            value = layout.pan_offset(5000, 1920, step / 100.0 * 20, 20)
            self.assertLessEqual(value, previous)
            previous = value

    def test_narrow_image_is_centred_and_does_not_pan(self):
        self.assertEqual(layout.centre_offset(800, 1920), 560)
        self.assertEqual(layout.centre_offset(2000, 1920), 0)
        self.assertEqual(layout.pan_offset(800, 1920, 10, 20), 0)
        self.assertEqual(layout.pan_extent(800, 1920), 0)

    def test_pan_can_be_switched_off(self):
        self.assertEqual(layout.pan_offset(5000, 1920, 10, 20, enabled=False), 0)

    def test_ease_is_clamped(self):
        self.assertEqual(layout.ease(-1), 0.0)
        self.assertEqual(layout.ease(2), 1.0)
        self.assertAlmostEqual(layout.ease(0.5), 0.5)


class ParseRows(unittest.TestCase):
    def test_valid_rows(self):
        items = hf_client.parse_rows(rows_payload([row(7, 'nz', '211 Te Moehau Road', height=561)]))
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual((item.row_idx, item.country, item.address), (7, 'NZ', '211 Te Moehau Road'))
        self.assertEqual((item.width, item.height), (100, 561))

    def test_malformed_rows_are_skipped(self):
        payload = {'rows': [
            {'row': {'image': {'src': 'https://x/1.jpg'}}, 'row_idx': 0},
            {'row_idx': 1},                                        # no row
            {'row': {'image': {'src': 'ftp://x'}}, 'row_idx': 2},  # not http
            {'row': {'image': {}}, 'row_idx': 3},                  # no src
            {'row': {'image': 'https://x/4.jpg'}, 'row_idx': 4},   # image as a bare string
            'nonsense',
        ]}
        items = hf_client.parse_rows(payload)
        self.assertEqual([i.row_idx for i in items], [0, 4])
        self.assertEqual(items[1].src, 'https://x/4.jpg')

    def test_empty_or_missing(self):
        self.assertEqual(hf_client.parse_rows(None), [])
        self.assertEqual(hf_client.parse_rows({}), [])
        self.assertEqual(hf_client.parse_rows({'rows': []}), [])

    def test_missing_country_and_address(self):
        items = hf_client.parse_rows({'rows': [{'row_idx': 5, 'row': {'image': 'https://x/5.jpg'}}]})
        self.assertEqual((items[0].country, items[0].address), ('', ''))


class Client(unittest.TestCase):
    def client(self, fetch, wait=None, rand=None, sources=('one',)):
        self.calls = []
        self.waits = []

        def recording_wait(seconds):
            self.waits.append(seconds)
            return False

        patcher = mock.patch.object(hf_client.net, 'fetch_json', fetch)
        patcher.start()
        self.addCleanup(patcher.stop)
        return hf_client.Client(wait=wait or recording_wait, rand=rand or FakeRandom(),
                                sources=sources)

    def fetcher(self, by_kind):
        def fetch(url):
            self.calls.append(url)
            for key, value in by_kind.items():
                if key in url:
                    if isinstance(value, Exception):
                        raise value
                    return value
            raise AssertionError('unexpected URL %s' % url)
        return fetch

    def test_size_is_asked_once_per_source(self):
        client = self.client(self.fetcher({'/size': {'size': {'config': {'num_rows': 11054}}}}))
        self.assertEqual(client.total(), 11054)
        self.assertEqual(client.total(), 11054)
        self.assertEqual(len(self.calls), 1)
        self.assertIn('dataset=one', self.calls[0])

    def test_size_falls_back_to_the_split_entry(self):
        payload = {'size': {'config': {}, 'splits': [{'num_rows': 321}]}}
        client = self.client(self.fetcher({'/size': payload}))
        self.assertEqual(client.total(), 321)

    def test_batch_uses_a_random_offset_and_shuffles(self):
        rand = FakeRandom(offset=500)
        client = self.client(self.fetcher({'/size': {'size': {'config': {'num_rows': 1000}}},
                                          '/rows': rows_payload([row(1), row(2), row(3)])}),
                             rand=rand)
        items = client.batch(40)
        self.assertEqual(rand.asked, [(0, 960)])
        self.assertIn('offset=500', self.calls[-1])
        self.assertIn('length=40', self.calls[-1])
        self.assertEqual(rand.shuffled, 1)
        self.assertEqual([i.row_idx for i in items], [3, 2, 1])

    def test_recent_rows_are_dropped(self):
        client = self.client(self.fetcher({'/size': {'size': {'config': {'num_rows': 1000}}},
                                          '/rows': rows_payload([row(1), row(2), row(3)])}))
        items = client.batch(40, recent={2, 3})
        self.assertEqual([i.row_idx for i in items], [1])

    def test_server_error_is_retried_with_backoff(self):
        error = hf_client.net.HttpError('boom', 503, 'http')
        calls = {'rows': 0}

        def fetch(url):
            self.calls.append(url)
            if '/size' in url:
                return {'size': {'config': {'num_rows': 1000}}}
            calls['rows'] += 1
            if calls['rows'] == 1:
                raise error
            return rows_payload([row(1)])

        client = self.client(fetch)
        items = client.batch(10)
        self.assertEqual([i.row_idx for i in items], [1])
        self.assertIn(10, self.waits)

    def test_retry_callback_reports_the_wait(self):
        reported = []

        def fetch(url):
            if '/size' in url:
                return {'size': {'config': {'num_rows': 1000}}}
            raise hf_client.net.HttpError('busy', 429, 'http')

        client = self.client(fetch)
        client._on_retry = lambda error, delay: reported.append(delay)
        with self.assertRaises(hf_client.net.HttpError):
            client.batch(10)
        self.assertTrue(reported)
        self.assertEqual(reported[0], 10)

    def test_bad_request_moves_to_the_next_source(self):
        def fetch(url):
            self.calls.append(url)
            if 'dataset=one' in url and '/rows' in url:
                raise hf_client.net.HttpError('bad', 400, 'http')
            if '/size' in url:
                return {'size': {'config': {'num_rows': 50}}}
            return rows_payload([row(9, 'JP')])

        client = self.client(fetch, sources=('one', 'two'))
        items = client.batch(10)
        self.assertEqual(client.source, 'two')
        self.assertEqual([i.row_idx for i in items], [9])

    def test_abort_stops_a_wait(self):
        def fetch(url):
            raise hf_client.net.HttpError('offline', 0, 'network')

        client = self.client(fetch, wait=lambda seconds: True)
        with self.assertRaises(hf_client.Aborted):
            client.batch(10)

    def test_gives_up_after_a_bounded_number_of_attempts(self):
        def fetch(url):
            self.calls.append(url)
            if '/size' in url:
                return {'size': {'config': {'num_rows': 1000}}}
            raise hf_client.net.HttpError('offline', 0, 'network')

        client = self.client(fetch)
        with self.assertRaises(hf_client.net.HttpError):
            client.batch(10)
        self.assertEqual(len([c for c in self.calls if '/rows' in c]), hf_client.MAX_ATTEMPTS)

    def test_row_returns_the_matching_index(self):
        client = self.client(self.fetcher({'/size': {'size': {'config': {'num_rows': 1000}}},
                                          '/rows': rows_payload([row(42, 'FR')])}))
        item = client.row(42)
        self.assertEqual(item.row_idx, 42)
        self.assertEqual(item.country, 'FR')

    def test_row_missing_returns_none(self):
        client = self.client(self.fetcher({'/size': {'size': {'config': {'num_rows': 1000}}},
                                          '/rows': rows_payload([row(41)])}))
        self.assertIsNone(client.row(42))


def jpeg(width=320, height=240):
    app0 = b'\xff\xe0' + struct.pack('>H', 16) + b'JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
    sof = b'\xff\xc0' + struct.pack('>H', 17) + b'\x08' + struct.pack('>HH', height, width) + b'\x03' + b'\x00' * 9
    return b'\xff\xd8' + app0 + sof + b'\xff\xd9'


class ImageSize(unittest.TestCase):
    def test_png_header(self):
        data = b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', 3030, 561)
        self.assertEqual(downloader.image_size(data), (3030, 561))

    def test_jpeg_header(self):
        self.assertEqual(downloader.image_size(jpeg(800, 600)), (800, 600))

    def test_unknown_data(self):
        self.assertEqual(downloader.image_size(b'GIF89a' + b'\x00' * 32), (0, 0))
        self.assertEqual(downloader.image_size(b''), (0, 0))
        self.assertEqual(downloader.image_size(b'\xff\xd8'), (0, 0))


class TempStore(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(self._remove)

    def _remove(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_save_writes_the_file_and_creates_the_folder(self):
        self.store = downloader.TempStore(os.path.join(self.folder, 'geoguess'))
        path = self.store.save(7, b'abc')
        self.assertTrue(os.path.isfile(path))
        with open(path, 'rb') as handle:
            self.assertEqual(handle.read(), b'abc')
        self.assertEqual(os.listdir(os.path.join(self.folder, 'geoguess')), ['geoguess-7.jpg'])

    def test_cap_keeps_the_newest_files(self):
        self.store = downloader.TempStore(self.folder, keep=3)
        for index, stamp in ((1, 100), (2, 200), (3, 300), (4, 400), (5, 500)):
            path = self.store.save(index, b'x')
            os.utime(path, (stamp, stamp))
        self.assertEqual(sorted(os.path.basename(p) for p in self.store._files()),
                         ['geoguess-3.jpg', 'geoguess-4.jpg', 'geoguess-5.jpg'])

    def test_clear_removes_only_our_files(self):
        self.store = downloader.TempStore(self.folder)
        self.store.save(1, b'x')
        keep = os.path.join(self.folder, 'other.txt')
        with open(keep, 'w') as handle:
            handle.write('keep')
        self.store.clear()
        self.assertEqual(os.listdir(self.folder), ['other.txt'])


class Downloader(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.store = downloader.TempStore(self.folder)
        self.addCleanup(self._remove)

    def _remove(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_saved_image_and_size_from_the_row(self):
        item = hf_client.Item(3, 'https://x/3.jpg', width=3030, height=561)
        with mock.patch.object(downloader.net, 'fetch_image', return_value=jpeg(100, 50)) as fetch:
            got = downloader.Downloader(None, self.store).download(item)
        self.assertEqual((got.width, got.height), (3030, 561))
        self.assertTrue(os.path.isfile(got.path))
        fetch.assert_called_once()

    def test_missing_row_size_is_read_from_the_header(self):
        item = hf_client.Item(4, 'https://x/4.jpg')
        with mock.patch.object(downloader.net, 'fetch_image', return_value=jpeg(800, 600)):
            got = downloader.Downloader(None, self.store).download(item)
        self.assertEqual((got.width, got.height), (800, 600))

    def test_expired_url_is_re_requested_once(self):
        expired = hf_client.net.HttpError('expired', 403, 'http')
        fresh = hf_client.Item(5, 'https://x/5-fresh.jpg', width=20, height=10)
        urls = []

        def fetch(url):
            urls.append(url)
            if url == 'https://x/5-old.jpg':
                raise expired
            return jpeg(20, 10)

        class Rows(object):
            asked = []

            def row(self, index):
                self.asked.append(index)
                return fresh

        rows = Rows()
        with mock.patch.object(downloader.net, 'fetch_image', fetch):
            got = downloader.Downloader(rows, self.store).download(hf_client.Item(5, 'https://x/5-old.jpg'))
        self.assertEqual(urls, ['https://x/5-old.jpg', 'https://x/5-fresh.jpg'])
        self.assertEqual(rows.asked, [5])
        self.assertEqual(got.item.row_idx, 5)

    def test_network_error_does_not_re_request(self):
        class Rows(object):
            asked = []

            def row(self, index):
                self.asked.append(index)
                return None

        rows = Rows()
        error = hf_client.net.HttpError('offline', 0, 'network')

        def fetch(url):
            raise error

        with mock.patch.object(downloader.net, 'fetch_image', fetch):
            with self.assertRaises(hf_client.net.HttpError):
                downloader.Downloader(rows, self.store).download(hf_client.Item(6, 'https://x/6.jpg'))
        self.assertEqual(rows.asked, [])


class AddonFiles(unittest.TestCase):
    def test_addon_xml(self):
        tree = ElementTree.parse(os.path.join(ADDON_DIR, 'addon.xml'))
        root = tree.getroot()
        self.assertEqual(root.get('id'), config.ADDON_ID)
        self.assertEqual(root.get('version'), config.VERSION)
        points = [e.get('point') for e in root.findall('extension')]
        self.assertIn('xbmc.ui.screensaver', points)
        self.assertIn('xbmc.addon.metadata', points)
        imports = [e.get('addon') for e in root.findall('./requires/import')]
        self.assertIn('xbmc.python', imports)
        self.assertTrue(os.path.isfile(os.path.join(ADDON_DIR, 'default.py')))
        self.assertTrue(os.path.isfile(os.path.join(ADDON_DIR, 'LICENSE.txt')))

    def test_window_and_media_exist(self):
        self.assertTrue(os.path.isfile(os.path.join(
            ADDON_DIR, 'resources', 'skins', 'Default', '1080i', 'screensaver-geoguess.xml')))
        for name in ('white.png', 'shade.png'):
            self.assertTrue(os.path.isfile(os.path.join(
                ADDON_DIR, 'resources', 'skins', 'Default', 'media', name)))

    def test_settings_xml_has_every_setting(self):
        with open(os.path.join(ADDON_DIR, 'resources', 'settings.xml')) as handle:
            text = handle.read()
        for setting in config.all_settings():
            self.assertIn('id="%s"' % setting['id'], text)

    def test_strings_po_has_the_on_screen_text(self):
        path = os.path.join(ADDON_DIR, 'resources', 'language', 'resource.language.en_gb',
                            'strings.po')
        with open(path) as handle:
            text = handle.read()
        for sid in config.STRINGS:
            self.assertIn('msgctxt "#%d"' % sid, text)


if __name__ == '__main__':
    unittest.main()

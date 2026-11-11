"""Offline tests for the Ship Tracker screensaver: the settings table and generated files, the
bounding box and map projection, AIS decoding and the fleet, WebSocket frames and message
assembly, the ship/profile database and its TTLs, the enrichment worker with injected fetchers,
the AIS tracker, the map download cache and the media Kodi needs. No network, no Kodi.

python3 -m unittest tests.test_shiptracker
"""

import os
import shutil
import socket
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                                'screensaver.shiptracker'))

from resources.lib import ais, config, mapimage, net, sources, store, tracker, ws  # noqa: E402

ADDON_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                                          'screensaver.shiptracker'))
MEDIA_DIR = os.path.join(ADDON_DIR, 'resources', 'skins', 'Default', 'media')


def position_message(mmsi=366123456, lat=47.5, lon=-88.0, name='TEST SHIP',
                     sog=12.3, cog=90.0, heading=91, nav=0):
    return {'MessageType': 'PositionReport',
            'MetaData': {'MMSI': mmsi, 'ShipName': name, 'latitude': lat, 'longitude': lon},
            'Message': {'PositionReport': {'Latitude': lat, 'Longitude': lon, 'Sog': sog,
                                           'Cog': cog, 'TrueHeading': heading,
                                           'NavigationalStatus': nav}}}


def static_message(mmsi=366123456, name='TEST SHIP'):
    return {'MessageType': 'ShipStaticData',
            'MetaData': {'MMSI': mmsi, 'ShipName': name},
            'Message': {'ShipStaticData': {
                'ImoNumber': 9876543, 'CallSign': 'WX1234', 'Name': name,
                'Destination': 'DULUTH', 'Type': 70, 'MaximumStaticDraught': 8.5,
                'Eta': {'Month': 11, 'Day': 10, 'Hour': 12, 'Minute': 30},
                'Dimension': {'A': 100, 'B': 20, 'C': 10, 'D': 10}}}}


class SettingsTable(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = [s['id'] for s in config.all_settings()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_defaults_are_the_lake_superior_box(self):
        values = config.defaults()
        self.assertEqual(values['api_key'], '')
        self.assertEqual(values['area1_name'], 'Lake Superior')
        self.assertEqual(values['area1_south_lat'], '46.3')
        self.assertEqual(values['area1_west_lon'], '-92.3')
        self.assertEqual(values['area1_north_lat'], '49.1')
        self.assertEqual(values['area1_east_lon'], '-84.2')
        self.assertEqual(config.area_box(values, 0), (46.3, -92.3, 49.1, -84.2))
        self.assertEqual(config.DEFAULT_BBOX, (46.3, -92.3, 49.1, -84.2))

    def test_ten_areas_ship_with_names_and_boxes(self):
        self.assertEqual(len(config.AREAS), 10)
        names = [area['name'] for area in config.AREAS]
        self.assertEqual(names[0], 'Lake Superior')
        self.assertIn('Strait of Hormuz', names)
        self.assertIn('San Diego', names)
        self.assertIn('San Francisco Bay', names)
        self.assertIn('Hawaii', names)
        for area in config.AREAS:
            south, west, north, east = area['box']
            self.assertLess(south, north)
            self.assertLess(west, east)
            self.assertTrue(-90 <= south and north <= 90)
            self.assertTrue(-180 <= west and east <= 180)

    def test_display_defaults(self):
        values = config.defaults()
        self.assertEqual(values['ship_timeout'], 15)
        self.assertEqual(values['photo_seconds'], 8)
        self.assertEqual(values['map_brightness'], 8)
        self.assertEqual(values['area_minutes'], 5)
        self.assertTrue(values['show_clock'])
        self.assertTrue(values['enrich'])
        self.assertFalse(values['debug'])

    def test_read_clamps_a_slider_and_keeps_a_bad_string(self):
        getters = {
            'boolean': lambda sid: sid == 'debug',
            'integer': lambda sid: 999 if sid == 'photo_seconds' else 0,
            'number': lambda sid: 0.0,
            'string': lambda sid: None if sid == 'api_key' else 'x',
        }
        values = config.read(getters)
        self.assertEqual(values['photo_seconds'], 30)       # clamped to the maximum
        self.assertEqual(values['ship_timeout'], 2)         # clamped to the minimum
        self.assertEqual(values['area_minutes'], 1)         # clamped to the minimum
        self.assertTrue(values['debug'])
        self.assertEqual(values['api_key'], '')             # a None string falls back

    def test_number_settings_are_read_with_the_number_getter(self):
        # Kodi's getSettingString refuses a 'number' setting: it logs "Invalid setting type"
        # and returns ''. Reading coordinates that way silently lost every custom box.
        boxes = {'area1_south_lat': 40.0, 'area1_west_lon': -80.0,
                 'area1_north_lat': 41.0, 'area1_east_lon': -79.0}
        number_ids = {s['id'] for s in config.all_settings() if s['type'] == 'number'}

        def string(sid):
            return '' if sid in number_ids else 'x'

        values = config.read({'boolean': lambda sid: False,
                              'integer': lambda sid: 0,
                              'number': lambda sid: boxes.get(sid, 0.0),
                              'string': string})
        self.assertEqual(values['area1_south_lat'], 40.0)
        self.assertEqual(config.area_box(values, 0), (40.0, -80.0, 41.0, -79.0))

    def test_clear_cache_is_an_action_not_a_stored_setting(self):
        ids = [s['id'] for s in config.all_settings()]
        self.assertNotIn('clear_cache', ids)


class BoundingBox(unittest.TestCase):
    def test_a_custom_box_is_used(self):
        settings = config.defaults()
        settings.update({'area1_south_lat': '40', 'area1_west_lon': '-80',
                         'area1_north_lat': '41', 'area1_east_lon': '-79'})
        self.assertEqual(config.area_box(settings, 0), (40.0, -80.0, 41.0, -79.0))

    def test_invalid_boxes_fall_back_to_their_area(self):
        for values in ((50, -92, 49, -84),          # upside down
                       (46, -84, 49, -92),          # east of west
                       (95, -92, 96, -84),          # out of range
                       ('x', -92, 49, -84)):        # not a number
            settings = config.defaults()
            for key, value in zip(('south_lat', 'west_lon', 'north_lat', 'east_lon'), values):
                settings['area2_' + key] = value
            self.assertEqual(config.area_box(settings, 1), config.AREAS[1]['box'])

    def test_label_and_name(self):
        settings = config.defaults()
        label = config.box_label(config.area_box(settings, 0))
        self.assertEqual(label, '46.30–49.10°N · 92.30–84.20°W')
        self.assertLessEqual(len(label), 32)                # fits the panel at font12
        self.assertEqual(config.area_name(settings, 0), 'Lake Superior')
        settings['area1_name'] = '  '
        self.assertEqual(config.area_name(settings, 0), 'Lake Superior')

    def test_label_names_each_end_across_the_equator(self):
        settings = config.defaults()
        settings.update({'area1_south_lat': '-1', 'area1_west_lon': '5',
                         'area1_north_lat': '1', 'area1_east_lon': '6'})
        self.assertEqual(config.box_label(config.area_box(settings, 0)),
                         '1.00°S–1.00°N · 5.00–6.00°E')


class Areas(unittest.TestCase):
    def test_enabled_areas_follow_the_switches(self):
        settings = config.defaults()
        self.assertEqual(len(config.enabled_areas(settings)), 10)
        settings['area2_enabled'] = False
        areas = config.enabled_areas(settings)
        self.assertEqual(len(areas), 9)
        self.assertNotIn('Strait of Hormuz', [area['name'] for area in areas])
        self.assertEqual(areas[0]['name'], 'Lake Superior')
        for index in range(10):
            settings['area%d_enabled' % (index + 1)] = False
        self.assertEqual(config.enabled_areas(settings), [])

    def test_a_renamed_area_keeps_its_custom_name(self):
        settings = config.defaults()
        settings['area3_name'] = '  My Harbour  '
        self.assertEqual(config.area_name(settings, 2), 'My Harbour')
        self.assertEqual(config.enabled_areas(settings)[2]['name'], 'My Harbour')

    def test_in_box(self):
        box = (46.3, -92.3, 49.1, -84.2)
        self.assertTrue(config.in_box({'lat': 47.5, 'lon': -88.0}, box))
        self.assertTrue(config.in_box({'lat': 46.3, 'lon': -92.3}, box))
        self.assertFalse(config.in_box({'lat': 47.5, 'lon': -80.0}, box))
        self.assertFalse(config.in_box({'lat': 40.0, 'lon': -88.0}, box))
        self.assertFalse(config.in_box({}, box))

    def test_rotation_minutes_are_clamped(self):
        self.assertEqual(config.area_seconds({'area_minutes': 0}), 60)
        self.assertEqual(config.area_seconds({'area_minutes': 10}), 600)
        self.assertEqual(config.area_seconds({'area_minutes': 999}), 3600)


class MapGeometry(unittest.TestCase):
    def test_the_requested_box_stays_inside_the_padded_box(self):
        left, bottom, right, top = config.map_bounds(11.5, 3.0, 12.0, 4.0, 1400, 1080)
        self.assertLessEqual(left, 3.0)
        self.assertGreaterEqual(right, 4.0)
        self.assertLessEqual(bottom, 11.5)
        self.assertGreaterEqual(top, 12.0)

    def test_a_tiny_box_is_shown_with_surrounding_water(self):
        left, bottom, right, top = config.map_bounds(32.5, -117.4, 32.9, -116.9, 1400, 1080)
        self.assertGreaterEqual(top - bottom, config.MIN_MAP_SPAN - 0.001)
        self.assertLessEqual(bottom, 32.5)
        self.assertGreaterEqual(top, 32.9)

    def test_degrees_are_square_on_screen(self):
        import math
        south, north = 46.3, 49.1
        left, bottom, right, top = config.map_bounds(south, -92.3, north, -84.2, 1400, 1080)
        mid_lat = (bottom + top) / 2.0
        pixels_per_lat = 1080.0 / (top - bottom)
        pixels_per_lon = 1400.0 / (right - left)
        self.assertAlmostEqual(pixels_per_lon / math.cos(math.radians(mid_lat)),
                               pixels_per_lat, delta=0.2)

    def test_projection_corners_and_centre(self):
        bounds = (0.0, -90.0, 360.0, 90.0)
        self.assertEqual(config.project(-90.0, 0.0, bounds, 100, 50), (0.0, 50.0))
        self.assertEqual(config.project(90.0, 360.0, bounds, 100, 50), (100.0, 0.0))
        x, y = config.project(0.0, 180.0, bounds, 100, 50)
        self.assertAlmostEqual(x, 50.0)
        self.assertAlmostEqual(y, 25.0)

    def test_map_url_and_cache_name(self):
        bounds = config.map_bounds(46.3, -92.3, 49.1, -84.2, 1400, 1080)
        url = config.map_url(bounds)
        self.assertIn('https://tiles.maps.eox.at/wms', url)
        self.assertIn('REQUEST=GetMap', url)
        self.assertIn('LAYERS=%s' % config.MAP_LAYER, url)
        self.assertEqual(config.MAP_LAYER, 's2cloudless-2025')
        self.assertIn('WIDTH=1400', url)
        self.assertIn('HEIGHT=1080', url)
        self.assertIn('BBOX=', url)
        first = config.map_cache_name(bounds, 1400, 1080)
        self.assertEqual(first, config.map_cache_name(bounds, 1400, 1080))
        self.assertNotEqual(first, config.map_cache_name(bounds, 1000, 1080))
        self.assertTrue(first.startswith('map_') and first.endswith('.jpg'))


class AisHelpers(unittest.TestCase):
    def test_ship_types(self):
        self.assertEqual(config.ship_type_text(70), 'Cargo')
        self.assertEqual(config.ship_type_text(89), 'Tanker')
        self.assertEqual(config.ship_type_text(60), 'Passenger')
        self.assertEqual(config.ship_type_text(52), 'Tug')
        self.assertEqual(config.ship_type_text(37), 'Pleasure craft')
        self.assertEqual(config.ship_type_text(99), 'Other')
        self.assertEqual(config.ship_type_text(123), 'Type 123')
        self.assertIsNone(config.ship_type_text(None))

    def test_nav_status(self):
        self.assertEqual(config.nav_status_text(1), 'At anchor')
        self.assertEqual(config.nav_status_text(8), 'Under way sailing')
        self.assertIsNone(config.nav_status_text(99))

    def test_flag_from_mmsi(self):
        self.assertEqual(config.mid_country(366123456), 'United States')
        self.assertEqual(config.mid_country(316123456), 'Canada')
        self.assertIsNone(config.mid_country(123456789))
        self.assertIsNone(config.mid_country(12345))
        self.assertIsNone(config.mid_country('nope'))

    def test_heading_index(self):
        self.assertEqual(config.heading_index(0), 0)
        self.assertEqual(config.heading_index(22.5), 1)
        self.assertEqual(config.heading_index(90), 4)
        self.assertEqual(config.heading_index(180), 8)
        self.assertEqual(config.heading_index(359), 0)
        self.assertEqual(config.heading_index(None), 0)

    def test_marker_groups(self):
        self.assertEqual(config.marker_group(70), 'cargo')
        self.assertEqual(config.marker_group(80), 'tanker')
        self.assertEqual(config.marker_group(60), 'passenger')
        self.assertEqual(config.marker_group(52), 'tug')
        self.assertEqual(config.marker_group(30), 'fishing')
        self.assertEqual(config.marker_group(37), 'pleasure')
        self.assertEqual(config.marker_group(40), 'high-speed')
        self.assertEqual(config.marker_group(35), 'military')
        self.assertEqual(config.marker_group(None), 'other')
        self.assertEqual(config.marker_colour(70), 'FF8ECAE6')

    def test_subscription_carries_every_enabled_box(self):
        boxes = [(46.3, -92.3, 49.1, -84.2), (25.6, 55.6, 27.0, 57.0)]
        payload = config.subscription('KEY', boxes)
        self.assertEqual(payload['APIKey'], 'KEY')
        self.assertEqual(payload['BoundingBoxes'], [[[46.3, -92.3], [49.1, -84.2]],
                                                    [[25.6, 55.6], [27.0, 57.0]]])
        self.assertIn('PositionReport', payload['FilterMessageTypes'])
        self.assertIn('ShipStaticData', payload['FilterMessageTypes'])


class AisDecoding(unittest.TestCase):
    def test_position_report(self):
        fleet = ais.Fleet()
        mmsi = fleet.handle(position_message(), now=1000.0)
        self.assertEqual(mmsi, 366123456)
        ship = fleet.get(mmsi)
        self.assertEqual(ship['name'], 'TEST SHIP')
        self.assertAlmostEqual(ship['lat'], 47.5)
        self.assertAlmostEqual(ship['lon'], -88.0)
        self.assertAlmostEqual(ship['sog'], 12.3)
        self.assertAlmostEqual(ship['cog'], 90.0)
        self.assertEqual(ship['heading'], 91)
        self.assertEqual(ship['nav_status'], 0)
        self.assertEqual(ship['seen'], 1000.0)

    def test_invalid_position_values_are_dropped(self):
        fleet = ais.Fleet()
        message = position_message(sog=102.3, cog=360.0, heading=511)
        fleet.handle(message, now=1000.0)
        ship = fleet.get(366123456)
        self.assertIsNone(ship['sog'])
        self.assertIsNone(ship['cog'])
        self.assertIsNone(ship['heading'])

    def test_static_data_merges_into_the_position(self):
        fleet = ais.Fleet()
        fleet.handle(position_message(), now=1000.0)
        fleet.handle(static_message(), now=1010.0)
        ship = fleet.get(366123456)
        self.assertEqual(ship['imo'], 9876543)
        self.assertEqual(ship['call_sign'], 'WX1234')
        self.assertEqual(ship['destination'], 'DULUTH')
        self.assertEqual(ship['ship_type'], 70)
        self.assertEqual(ship['length'], 120.0)
        self.assertEqual(ship['beam'], 20.0)
        self.assertEqual(ship['eta'], '11-10 12:30 UTC')
        self.assertEqual(ship['static_seen'], 1010.0)

    def test_class_b_static_report(self):
        fleet = ais.Fleet()
        message = {'MessageType': 'StaticDataReport', 'MetaData': {'MMSI': 316123456},
                   'Message': {'StaticDataReport': {
                       'ReportA': {'Name': 'CLASS B'},
                       'ReportB': {'ShipType': 37,
                                   'Dimension': {'A': 10, 'B': 5, 'C': 4, 'D': 4}}}}}
        fleet.handle(message, now=1000.0)
        ship = fleet.get(316123456)
        self.assertEqual(ship['name'], 'CLASS B')
        self.assertEqual(ship['ship_type'], 37)
        self.assertEqual(ship['length'], 15.0)
        self.assertEqual(ship['beam'], 8.0)

    def test_confirmation_and_unknown_messages_are_ignored(self):
        fleet = ais.Fleet()
        self.assertIsNone(fleet.handle({'MessageType': 'SubscriptionConfirmation'}))
        self.assertIsNone(fleet.handle({'MessageType': 'LongRangeAisBroadcastMessage',
                                        'MetaData': {'MMSI': 1}}))
        self.assertEqual(fleet.count(), 0)

    def test_seed_does_not_overwrite_live_values(self):
        fleet = ais.Fleet()
        fleet.handle(position_message(), now=1000.0)
        fleet.seed([{'mmsi': 366123456, 'name': 'OLD NAME', 'destination': 'DULUTH',
                     'seen': 900.0}])
        ship = fleet.get(366123456)
        self.assertEqual(ship['name'], 'TEST SHIP')
        self.assertEqual(ship['destination'], 'DULUTH')

    def test_snapshot_filters_and_sorts(self):
        fleet = ais.Fleet()
        fleet.handle(position_message(mmsi=366000002, name='ZULU'), now=1000.0)
        fleet.handle(position_message(mmsi=366000001, name='ALPHA'), now=1000.0)
        fleet.handle(position_message(mmsi=366000003, name='NO POSITION',
                                      lat=91, lon=181), now=1000.0)
        fleet.handle(static_message(mmsi=366000004, name='STATIC ONLY'), now=1000.0)
        names = [ship['name'] for ship in fleet.snapshot(now=1000.0, timeout=900)]
        self.assertEqual(names, ['ALPHA', 'ZULU'])
        self.assertEqual(fleet.snapshot(now=2000.0, timeout=900), [])
        self.assertEqual(fleet.count(), 4)


class WebSocketFrames(unittest.TestCase):
    def test_roundtrip_small_frame(self):
        frame = ws.build_frame(ws.OP_TEXT, 'hello', key=b'abcd')
        self.assertEqual(frame[0], 0x81)
        self.assertEqual(frame[1], 0x80 | 5)
        fin, opcode, payload, consumed = ws.parse_frame(frame)
        self.assertTrue(fin)
        self.assertEqual(opcode, ws.OP_TEXT)
        self.assertEqual(payload, b'hello')
        self.assertEqual(consumed, len(frame))

    def test_extended_lengths(self):
        for size in (200, 70000):
            frame = ws.build_frame(ws.OP_BINARY, b'x' * size)
            fin, opcode, payload, consumed = ws.parse_frame(frame)
            self.assertEqual(opcode, ws.OP_BINARY)
            self.assertEqual(len(payload), size)
            self.assertEqual(consumed, len(frame))

    def test_partial_frame_returns_none(self):
        frame = ws.build_frame(ws.OP_TEXT, b'x' * 300)
        self.assertIsNone(ws.parse_frame(frame[:2]))
        self.assertIsNone(ws.parse_frame(frame[:20]))
        self.assertIsNone(ws.parse_frame(frame[:-1]))

    def test_accept_key_matches_rfc_example(self):
        self.assertEqual(ws.accept_key('dGhlIHNhbXBsZSBub25jZQ=='),
                         's3pPLMBiTxaQ9kYGzzhZRbK+xOo=')

    def test_reserved_bits_are_refused(self):
        with self.assertRaises(ws.WebSocketError):
            ws.parse_frame(bytearray([0xC1, 0x00]))


class FakeSocket(object):
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []

    def settimeout(self, _value):
        pass

    def recv(self, _size):
        if self.chunks:
            return self.chunks.pop(0)
        raise socket.timeout()

    def sendall(self, data):
        self.sent.append(data)

    def close(self):
        pass


class WebSocketMessages(unittest.TestCase):
    def client(self, chunks):
        return ws.WebSocket('example', sock=FakeSocket(chunks))

    def test_binary_message_is_returned_as_text(self):
        frame = ws.build_frame(ws.OP_BINARY, '{"a": 1}')
        client = self.client([frame])
        self.assertEqual(client.recv_text(timeout=1), '{"a": 1}')

    def test_a_ping_is_answered_and_skipped(self):
        ping = ws.build_frame(ws.OP_PING, b'hi')
        message = ws.build_frame(ws.OP_TEXT, 'ok')
        client = self.client([ping + message])
        self.assertEqual(client.recv_text(timeout=1), 'ok')
        self.assertEqual(client._sock.sent[0][0], 0x8A)      # FIN + pong

    def test_a_fragmented_message_is_joined(self):
        first = ws.build_frame(ws.OP_TEXT, 'hel', fin=False)
        second = ws.build_frame(ws.OP_CONT, 'lo', fin=True)
        client = self.client([first + second])
        self.assertEqual(client.recv_text(timeout=1), 'hello')

    def test_a_new_message_clears_the_fragment_buffer(self):
        first = ws.build_frame(ws.OP_TEXT, 'old', fin=False)
        last = ws.build_frame(ws.OP_CONT, 'er', fin=True)
        fresh = ws.build_frame(ws.OP_TEXT, 'new')
        client = self.client([first + last + fresh])
        self.assertEqual(client.recv_text(timeout=1), 'older')
        self.assertEqual(client.recv_text(timeout=1), 'new')

    def test_timeout_returns_none(self):
        client = self.client([])
        self.assertIsNone(client.recv_text(timeout=0.01))

    def test_close_frame_raises(self):
        client = self.client([ws.build_frame(ws.OP_CLOSE, b'')])
        with self.assertRaises(ws.WebSocketClosed):
            client.recv_text(timeout=1)


class ShipStore(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, 'ships.db')
        self.now = [1000.0]
        self.store = store.Store(self.path, clock=lambda: self.now[0])

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_ship_roundtrip(self):
        ship = {'mmsi': 366123456, 'name': 'TEST SHIP', 'lat': 47.5, 'lon': -88.0,
                'seen': 1000.0, 'updated': 1000.0, 'ship_type': 70, 'length': 120.0}
        self.store.save_ship(ship, force=True)
        rows = self.store.load_ships()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'TEST SHIP')
        self.assertAlmostEqual(rows[0]['length'], 120.0)

    def test_a_found_profile_is_fresh_for_a_month(self):
        signature = sources.signature(9876543, 'WX1234', 366123456)
        self.store.put_profile(366123456, signature, {'name': 'TEST SHIP'})
        self.assertTrue(self.store.profile_is_fresh(
            366123456, signature, now=1000.0 + config.PROFILE_TTL - 1))
        self.assertFalse(self.store.profile_is_fresh(
            366123456, signature, now=1000.0 + config.PROFILE_TTL + 1))

    def test_a_miss_is_retried_after_a_week(self):
        signature = sources.signature(None, None, 366123456)
        self.store.put_profile(366123456, signature, None)
        self.assertTrue(self.store.profile_is_fresh(
            366123456, signature, now=1000.0 + config.NEGATIVE_TTL - 1))
        self.assertFalse(self.store.profile_is_fresh(
            366123456, signature, now=1000.0 + config.NEGATIVE_TTL + 1))

    def test_a_new_identifier_set_invalidates_the_profile(self):
        old = sources.signature(None, None, 366123456)
        new = sources.signature(9876543, 'WX1234', 366123456)
        self.store.put_profile(366123456, old, {'name': 'TEST SHIP'})
        self.assertFalse(self.store.profile_is_fresh(366123456, new, now=1000.0))

    def test_clear_empties_both_tables(self):
        self.store.save_ship({'mmsi': 1, 'name': 'A'}, force=True)
        self.store.put_profile(1, 'sig', {'name': 'A'})
        self.store.clear()
        self.assertEqual(self.store.load_ships(), [])
        self.assertIsNone(self.store.get_profile(1))

    def test_a_corrupt_database_is_moved_aside(self):
        self.store.close()
        with open(self.path, 'wb') as handle:
            handle.write(b'this is not a database at all')
        recovered = store.Store(self.path, clock=lambda: self.now[0])
        try:
            self.assertEqual(recovered.load_ships(), [])
            recovered.save_ship({'mmsi': 2, 'name': 'B'}, force=True)
            self.assertEqual(recovered.load_ships()[0]['name'], 'B')
            moved = [name for name in os.listdir(self.folder) if '.corrupt-' in name]
            self.assertEqual(len(moved), 1)
        finally:
            recovered.close()


class Profiles(unittest.TestCase):
    def wikidata(self, imo, mmsi):
        return {'label': 'TEST SHIP', 'built_year': 2001, 'length_m': 120.0,
                'images': [{'url': 'https://example/a.jpg', 'thumb': 'https://example/a.jpg'}],
                'owner': 'TEST LINE', 'qid': 'Q1', 'url': 'https://example/q1'}

    def commons(self, imo):
        return [{'url': 'https://example/b.jpg', 'thumb': 'https://example/b.jpg'},
                {'url': 'https://example/a.jpg', 'thumb': 'https://example/a.jpg'}]

    def test_merge_dedupes_and_keeps_both_sources(self):
        profile = sources.merge_profile(self.wikidata(1, 2), self.commons(1))
        self.assertEqual([photo['url'] for photo in profile['photos']],
                         ['https://example/a.jpg', 'https://example/b.jpg'])
        self.assertEqual(profile['name'], 'TEST SHIP')
        self.assertEqual(profile['owner'], 'TEST LINE')
        self.assertTrue(profile['sources']['wikidata'])
        self.assertEqual(profile['sources']['commons'], 2)

    def test_nothing_found_is_none(self):
        self.assertIsNone(sources.merge_profile(None, []))

    def test_signature_changes_with_any_identifier(self):
        first = sources.signature(1, 'A', 2)
        self.assertNotEqual(first, sources.signature(3, 'A', 2))
        self.assertNotEqual(first, sources.signature(1, 'B', 2))
        self.assertNotEqual(first, sources.signature(1, 'A', 3))
        ship = {'imo': 1, 'call_sign': 'A', 'mmsi': 2}
        self.assertEqual(sources.ship_signature(ship), first)

    def test_valid_mmsi(self):
        self.assertTrue(sources.valid_mmsi(366123456))
        self.assertFalse(sources.valid_mmsi(12345))
        self.assertFalse(sources.valid_mmsi(None))


class EnricherWorker(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.now = [1000.0]
        self.store = store.Store(os.path.join(self.folder, 'ships.db'),
                                 clock=lambda: self.now[0])
        self.wikidata_calls = []
        self.commons_calls = []

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def worker(self):
        def wikidata(imo, mmsi):
            self.wikidata_calls.append((imo, mmsi))
            return {'label': 'TEST SHIP', 'built_year': 1999,
                    'images': [{'url': 'https://example/a.jpg', 'thumb': 'https://example/a.jpg'}]}

        def commons(imo):
            self.commons_calls.append(imo)
            return [{'url': 'https://example/b.jpg', 'thumb': 'https://example/b.jpg'}]

        enricher = sources.Enricher(self.store, gap=0, clock=lambda: self.now[0],
                                            wikidata_fetcher=wikidata, commons_fetcher=commons)
        enricher.start()
        self.addCleanup(self.store.close)
        self.addCleanup(enricher.join, 2.0)
        self.addCleanup(enricher.stop)
        return enricher

    def test_a_ship_is_looked_up_once_and_cached(self):
        enricher = self.worker()
        ship = {'mmsi': 366123456, 'imo': 9876543, 'call_sign': 'WX1234', 'name': 'TEST SHIP'}
        self.assertTrue(enricher.enqueue(ship))
        enricher.jobs.join()
        profile = enricher.profile(366123456)
        self.assertEqual(len(profile['photos']), 2)
        self.assertEqual(self.wikidata_calls, [(9876543, 366123456)])
        self.assertEqual(self.commons_calls, [9876543])

        self.assertFalse(enricher.enqueue(ship))
        enricher.jobs.join()
        self.assertEqual(len(self.wikidata_calls), 1)

    def test_a_new_imo_triggers_a_new_lookup(self):
        enricher = self.worker()
        ship = {'mmsi': 366123456, 'imo': 9876543, 'call_sign': 'WX1234', 'name': 'TEST SHIP'}
        enricher.enqueue(ship)
        enricher.jobs.join()
        changed = dict(ship, imo=9876544)
        self.assertTrue(enricher.enqueue(changed))
        enricher.jobs.join()
        self.assertEqual(len(self.wikidata_calls), 2)

    def test_a_rate_limit_is_remembered(self):
        def limited(imo, mmsi):
            raise net.RateLimited(30)

        enricher = sources.Enricher(self.store, gap=0, clock=lambda: self.now[0],
                                    wikidata_fetcher=limited, commons_fetcher=lambda imo: [])
        enricher.start()
        self.addCleanup(self.store.close)
        self.addCleanup(enricher.join, 2.0)
        self.addCleanup(enricher.stop)
        ship = {'mmsi': 366123456, 'imo': 9876543, 'call_sign': '', 'name': 'TEST'}
        enricher.enqueue(ship)
        enricher.jobs.join()
        self.assertFalse(enricher.enqueue(ship))
        self.now[0] += 31
        self.assertTrue(enricher.enqueue(ship))
        enricher.jobs.join()

    def test_photos_and_details_end_up_in_the_database(self):
        enricher = self.worker()
        ship = {'mmsi': 366123456, 'imo': 9876543, 'call_sign': 'WX1234', 'name': 'TEST SHIP'}
        enricher.enqueue(ship)
        enricher.jobs.join()
        row = self.store.get_profile(366123456)
        self.assertEqual(row['signature'], sources.signature(9876543, 'WX1234', 366123456))
        self.assertEqual(row['data']['built_year'], 1999)


class TrackerWork(unittest.TestCase):
    def test_messages_fill_the_fleet_and_the_store(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        ship_store = store.Store(os.path.join(folder, 'ships.db'))
        self.addCleanup(ship_store.close)
        fleet = ais.Fleet()
        enricher = type('E', (), {'seen': [], 'enqueue': lambda self, ship: self.seen.append(ship)})()
        worker = tracker.Tracker('KEY', [config.DEFAULT_BBOX], fleet, ship_store,
                                 enricher=enricher, clock=lambda: 1000.0,
                                 connection_factory=lambda: None)
        worker._handle(position_message())
        self.assertEqual(worker.messages, 1)
        self.assertEqual(worker.last_message_at, 1000.0)
        self.assertEqual(len(enricher.seen), 1)
        self.assertEqual(fleet.get(366123456)['name'], 'TEST SHIP')
        self.assertEqual(ship_store.load_ships()[0]['name'], 'TEST SHIP')

    def test_no_key_means_no_connection(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        ship_store = store.Store(os.path.join(folder, 'ships.db'))
        self.addCleanup(ship_store.close)
        worker = tracker.Tracker('', [config.DEFAULT_BBOX], ais.Fleet(), ship_store)
        worker.start()
        worker.join(2.0)
        self.assertEqual(worker.snapshot()['state'], 'no_key')


class MapCache(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.bounds = config.map_bounds(46.3, -92.3, 49.1, -84.2, 1400, 1080)

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_downloads_once_then_uses_the_cache(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return b'x' * 3000

        path = mapimage.ensure_map(self.folder, self.bounds, fetch=fetch)
        self.assertTrue(mapimage.has_map(path))
        self.assertEqual(len(calls), 1)
        self.assertEqual(mapimage.ensure_map(self.folder, self.bounds, fetch=fetch), path)
        self.assertEqual(len(calls), 1)

    def test_a_tiny_download_is_rejected(self):
        path = mapimage.ensure_map(self.folder, self.bounds, fetch=lambda url: b'x')
        self.assertIsNone(path)

    def test_an_offline_run_still_uses_the_cached_map(self):
        path = mapimage.ensure_map(self.folder, self.bounds, fetch=lambda url: b'x' * 3000)

        def broken(url):
            raise net.HttpError('offline', 'network')

        self.assertEqual(mapimage.ensure_map(self.folder, self.bounds, fetch=broken), path)

    def test_clear_removes_only_maps(self):
        path = mapimage.ensure_map(self.folder, self.bounds, fetch=lambda url: b'x' * 3000)
        keep = os.path.join(self.folder, 'photo_abc.jpg')
        with open(keep, 'wb') as handle:
            handle.write(b'x' * 2000)
        self.assertEqual(mapimage.clear(self.folder), 1)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(keep))


class GeneratedFiles(unittest.TestCase):
    def test_required_files_exist(self):
        for name in ('addon.xml', 'default.py', 'LICENSE.txt', 'icon.png', 'fanart.jpg',
                     'resources/settings.xml',
                     'resources/language/resource.language.en_gb/strings.po',
                     'resources/skins/Default/1080i/screensaver-shiptracker.xml'):
            self.assertTrue(os.path.exists(os.path.join(ADDON_DIR, name)), name)
        for name in (['white.png', 'sea.png', 'photo_placeholder.png'] +
                     ['ship_%02d.png' % index for index in range(16)]):
            self.assertTrue(os.path.exists(os.path.join(MEDIA_DIR, name)), name)

    def test_addon_metadata(self):
        tree = ElementTree.parse(os.path.join(ADDON_DIR, 'addon.xml'))
        root = tree.getroot()
        self.assertEqual(root.get('id'), config.ADDON_ID)
        self.assertEqual(root.get('version'), config.VERSION)
        points = [element.get('point') for element in root]
        self.assertIn('xbmc.ui.screensaver', points)
        self.assertIn('xbmc.addon.metadata', points)
        requires = [element.get('addon') for element in root.find('requires')]
        self.assertIn('xbmc.python', requires)

    def test_settings_xml_has_every_setting(self):
        tree = ElementTree.parse(os.path.join(ADDON_DIR, 'resources', 'settings.xml'))
        ids = set(element.get('id') for element in tree.getroot().iter('setting'))
        for setting in config.all_settings():
            self.assertIn(setting['id'], ids)
        api_key = [element for element in tree.getroot().iter('setting')
                   if element.get('id') == 'api_key'][0]
        self.assertEqual(api_key.find('default').text or '', '')

    def test_strings_po_has_the_screen_text(self):
        path = os.path.join(ADDON_DIR, 'resources', 'language',
                            'resource.language.en_gb', 'strings.po')
        with open(path, encoding='utf-8') as handle:
            text = handle.read()
        for sid in config.STRINGS:
            self.assertIn('#%d' % sid, text)

    def test_the_local_api_key_is_not_in_the_addon(self):
        self.assertFalse(os.path.exists(os.path.join(ADDON_DIR, 'key')))
        for folder, _dirs, names in os.walk(ADDON_DIR):
            self.assertNotIn('key', names, folder)


if __name__ == '__main__':
    unittest.main()

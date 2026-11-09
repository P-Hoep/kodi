"""The radar's data model, ported from the native screensaver (radar_core.cpp).

The app and the screensaver must agree about distances, bearing, dead reckoning, the sweep
clock, sweep echoes, which contacts survive, and every line of text. The C++ file is the
reference; keep the two in step. Nothing here imports xbmc, so the offline tests can drive
time and feeds directly.
"""

import math

EARTH_RADIUS_M = 6371008.8
METRES_PER_NM = 1852.0
KT_TO_MS = 0.5144444444444445
FT_TO_M = 0.3048
MAX_EXTRAPOLATION_S = 90.0
MAX_ECHOES = 3
PI = 3.14159265358979323846
DEG = PI / 180.0
RAD = 180.0 / PI


def _clamp(value, low, high):
    return low if value < low else (high if value > high else value)


def _clampi(value, low, high):
    return int(_clamp(value, low, high))


def _round_half_away(value):
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(-value + 0.5))


# ---- geometry -----------------------------------------------------------------------------


def distance_m(a, b):
    p1 = a[0] * DEG
    p2 = b[0] * DEG
    dp = (b[0] - a[0]) * DEG
    dl = (b[1] - a[1]) * DEG
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(_clamp(h, 0.0, 1.0)))


def bearing_deg(a, b):
    p1 = a[0] * DEG
    p2 = b[0] * DEG
    dl = (b[1] - a[1]) * DEG
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return normalize_deg(math.atan2(y, x) * RAD)


def destination(lat, lon, bearing, distance):
    if distance <= 0.0:
        return lat, lon
    d = distance / EARTH_RADIUS_M
    brg = bearing * DEG
    p1 = lat * DEG
    l1 = lon * DEG
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(brg))
    l2 = l1 + math.atan2(math.sin(brg) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return p2 * RAD, (l2 * RAD + 540.0) % 360.0 - 180.0


def normalize_deg(value):
    value = math.fmod(value, 360.0)
    return value + 360.0 if value < 0.0 else value


def angle_delta(start, end):
    return math.fmod(end - start + 540.0, 360.0) - 180.0


def crossed_deg(previous, current, target):
    previous = normalize_deg(previous)
    current = normalize_deg(current)
    target = normalize_deg(target)
    if previous == current:
        return False
    if previous < current:
        return target > previous and target <= current
    return target > previous or target <= current


def east_north_m(home, point):
    mid = (home[0] + point[0]) * 0.5 * DEG
    north = (point[0] - home[0]) * DEG * EARTH_RADIUS_M
    east = (point[1] - home[1]) * DEG * EARTH_RADIUS_M * math.cos(mid)
    return east, north


# ---- settings -----------------------------------------------------------------------------


class Settings(object):
    def __init__(self, **values):
        self.location_name = 'Home'
        self.lat = 44.9031331
        self.lon = -93.3096136
        self.range_km = 60
        self.units = 1
        self.refresh_seconds = 20
        self.show_ground = False
        self.min_altitude = 0
        self.sweep_seconds = 6
        self.show_labels = True
        self.label_detail = 1
        self.show_history = True
        self.max_contacts = 40
        self.show_panel = True
        self.detail_seconds = 10
        self.list_seconds = 8
        self.theme = 0
        self.crt = True
        self.dim = 0
        self.quality = 1
        for key, value in values.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.sanitise()

    def sanitise(self):
        if not (-90.0 <= self.lat <= 90.0):
            self.lat = 0.0
        if not (-180.0 <= self.lon <= 180.0):
            self.lon = 0.0
        self.lon = ((self.lon + 180.0) % 360.0) - 180.0
        self.range_km = _clampi(self.range_km, 5, 400)
        self.units = _clampi(self.units, 0, 1)
        self.refresh_seconds = _clampi(self.refresh_seconds, 10, 120)
        self.min_altitude = _clampi(self.min_altitude, 0, 3)
        self.sweep_seconds = _clampi(self.sweep_seconds, 2, 12)
        self.label_detail = _clampi(self.label_detail, 0, 2)
        self.max_contacts = _clampi(self.max_contacts, 5, 200)
        self.detail_seconds = _clampi(self.detail_seconds, 4, 60)
        self.list_seconds = _clampi(self.list_seconds, 3, 60)
        self.theme = _clampi(self.theme, 0, 3)
        self.dim = _clampi(self.dim, 0, 80)
        self.quality = _clampi(self.quality, 0, 2)
        self.location_name = trim_string(str(self.location_name))
        if not self.location_name:
            self.location_name = 'Home'


# ---- aircraft and feeds -------------------------------------------------------------------


class Aircraft(object):
    def __init__(self):
        self.hex = ''
        self.flight = ''
        self.reg = ''
        self.type_code = ''
        self.category = ''
        self.emergency = ''
        self.squawk = ''
        self.type = ''

        self.has_pos = False
        self.lat = 0.0
        self.lon = 0.0
        self.on_ground = False
        self.has_alt = False
        self.alt_ft = 0.0
        self.has_alt_geom = False
        self.alt_geom_ft = 0.0
        self.has_gs = False
        self.gs_kt = 0.0
        self.has_track = False
        self.track = 0.0
        self.has_baro_rate = False
        self.baro_rate_fpm = 0.0
        self.has_geom_rate = False
        self.geom_rate_fpm = 0.0

        self.has_nav_alt = False
        self.nav_alt_ft = 0.0
        self.has_nav_heading = False
        self.nav_heading = 0.0
        self.has_nav_qnh = False
        self.nav_qnh = 0.0
        self.has_ias = False
        self.ias_kt = 0.0
        self.has_tas = False
        self.tas_kt = 0.0
        self.has_mach = False
        self.mach = 0.0
        self.has_mag_heading = False
        self.mag_heading = 0.0
        self.has_true_heading = False
        self.true_heading = 0.0

        self.has_seen = False
        self.seen = 0.0
        self.has_seen_pos = False
        self.seen_pos = 0.0
        self.has_rssi = False
        self.rssi = 0.0
        self.messages = 0
        self.version = 0
        self.military = False
        self.interesting = False
        self.pia = False
        self.ladd = False
        self.alert = False
        self.spi = False
        self.has_nac_p = False
        self.nac_p = 0.0
        self.has_nac_v = False
        self.nac_v = 0.0
        self.has_sil = False
        self.sil = 0.0
        self.has_nic = False
        self.nic = 0.0
        self.has_rc = False
        self.rc_m = 0.0
        self.mlat = False
        self.tisb = False


class Feed(object):
    def __init__(self):
        self.aircraft = []
        self.source_time = 0.0
        self.total = 0
        self.source = 'adsb.lol'


class FeedError(Exception):
    pass


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return False


def _text(value):
    return trim_string(str(value)) if isinstance(value, str) else ''


def _squawk(value):
    if isinstance(value, str):
        return value
    number = _number(value)
    if number is not None:
        return '%04.0f' % number
    return ''


def parse_adsblol(text):
    try:
        root = __import__('json').loads(text)
    except ValueError as error:
        raise FeedError('adsb.lol: bad JSON (%s)' % error)
    if not isinstance(root, dict):
        raise FeedError('adsb.lol: response is not an object')
    feed = Feed()
    feed.source = 'adsb.lol'
    feed.source_time = _number(root.get('now')) or 0.0
    if feed.source_time > 1e11:
        feed.source_time /= 1000.0
    aircraft = root.get('ac')
    if not isinstance(aircraft, list):
        raise FeedError('adsb.lol: no aircraft list')
    feed.total = len(aircraft)
    for item in aircraft:
        if not isinstance(item, dict):
            continue
        ac = Aircraft()
        ac.hex = lower_string(_text(item.get('hex')))
        lat = _number(item.get('lat'))
        lon = _number(item.get('lon'))
        if not ac.hex or lat is None or lon is None:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        ac.lat = lat
        ac.lon = lon
        ac.has_pos = True
        ac.flight = _text(item.get('flight'))
        ac.reg = _text(item.get('r'))
        ac.type_code = _text(item.get('t'))
        ac.category = _text(item.get('category'))
        ac.emergency = _text(item.get('emergency'))
        ac.type = _text(item.get('type'))
        ac.squawk = _squawk(item.get('squawk'))

        alt_baro = item.get('alt_baro')
        if isinstance(alt_baro, str) and alt_baro == 'ground':
            ac.on_ground = True
        else:
            value = _number(alt_baro)
            if value is not None:
                ac.alt_ft = value
                ac.has_alt = True
        value = _number(item.get('alt_geom'))
        if value is not None:
            ac.alt_geom_ft = value
            ac.has_alt_geom = True
            if not ac.has_alt and not ac.on_ground:
                ac.alt_ft = value
                ac.has_alt = True
        value = _number(item.get('gs'))
        if value is not None:
            ac.gs_kt = value
            ac.has_gs = True
        value = _number(item.get('track'))
        if value is not None:
            ac.track = value
            ac.has_track = True
        if not ac.has_track:
            value = _number(item.get('true_heading'))
            if value is not None:
                ac.track = value
                ac.has_track = True
        for name, attr, has_attr in (
                ('baro_rate', 'baro_rate_fpm', 'has_baro_rate'),
                ('geom_rate', 'geom_rate_fpm', 'has_geom_rate'),
                ('nav_altitude_mcp', 'nav_alt_ft', 'has_nav_alt'),
                ('nav_heading', 'nav_heading', 'has_nav_heading'),
                ('nav_qnh', 'nav_qnh', 'has_nav_qnh'),
                ('ias', 'ias_kt', 'has_ias'),
                ('tas', 'tas_kt', 'has_tas'),
                ('mach', 'mach', 'has_mach'),
                ('mag_heading', 'mag_heading', 'has_mag_heading'),
                ('true_heading', 'true_heading', 'has_true_heading'),
                ('seen', 'seen', 'has_seen'),
                ('seen_pos', 'seen_pos', 'has_seen_pos'),
                ('rssi', 'rssi', 'has_rssi'),
                ('nac_p', 'nac_p', 'has_nac_p'),
                ('nac_v', 'nac_v', 'has_nac_v'),
                ('sil', 'sil', 'has_sil'),
                ('nic', 'nic', 'has_nic'),
                ('rc', 'rc_m', 'has_rc')):
            value = _number(item.get(name))
            if value is not None:
                setattr(ac, attr, value)
                setattr(ac, has_attr, True)
        messages = _number(item.get('messages'))
        if messages is not None:
            ac.messages = int(messages)
        version = _number(item.get('version'))
        if version is not None:
            ac.version = int(version)

        flags = _number(item.get('dbFlags'))
        if flags is not None:
            flags = int(flags)
            ac.military = bool(flags & 1)
            ac.interesting = bool(flags & 2)
            ac.pia = bool(flags & 4)
            ac.ladd = bool(flags & 8)
        ac.alert = _bool(item.get('alert'))
        ac.spi = _bool(item.get('spi'))
        mlat = item.get('mlat')
        tisb = item.get('tisb')
        ac.mlat = isinstance(mlat, list) and bool(mlat)
        ac.tisb = isinstance(tisb, list) and bool(tisb)
        feed.aircraft.append(ac)
    return feed


_OPENSKY_CATEGORIES = ['', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'B1', 'B2', 'B3',
                       'B4', 'B5', 'B6', 'B7', 'C1', 'C2', 'C3', 'C4', 'C5']


def parse_opensky(text):
    try:
        root = __import__('json').loads(text)
    except ValueError as error:
        raise FeedError('OpenSky: bad JSON (%s)' % error)
    if not isinstance(root, dict):
        raise FeedError('OpenSky: response is not an object')
    feed = Feed()
    feed.source = 'OpenSky'
    feed.source_time = _number(root.get('time')) or 0.0
    states = root.get('states')
    if states is None:
        feed.total = 0
        return feed
    if not isinstance(states, list):
        raise FeedError('OpenSky: states is not an array')
    feed.total = len(states)
    for state in states:
        if not isinstance(state, list) or len(state) < 17:
            continue
        ac = Aircraft()
        ac.hex = lower_string(state[0] if isinstance(state[0], str) else '')
        if not ac.hex:
            continue
        lon = _number(state[5])
        lat = _number(state[6])
        if lon is None or lat is None:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        ac.lon = lon
        ac.lat = lat
        ac.has_pos = True
        ac.flight = _text(state[1])
        ac.on_ground = _bool(state[8])
        value = _number(state[7])
        if value is not None:
            ac.alt_ft = value / FT_TO_M
            ac.has_alt = True
        value = _number(state[13])
        if value is not None:
            ac.alt_geom_ft = value / FT_TO_M
            ac.has_alt_geom = True
            if not ac.has_alt:
                ac.alt_ft = ac.alt_geom_ft
                ac.has_alt = True
        value = _number(state[9])
        if value is not None:
            ac.gs_kt = value / KT_TO_MS
            ac.has_gs = True
        value = _number(state[10])
        if value is not None:
            ac.track = normalize_deg(value)
            ac.has_track = True
        value = _number(state[11])
        if value is not None:
            ac.baro_rate_fpm = value / (FT_TO_M / 60.0)
            ac.has_baro_rate = True
        ac.squawk = state[14] if isinstance(state[14], str) else _squawk(state[14])
        ac.spi = _bool(state[15])
        category = int(_number(state[17]) or 0) if len(state) > 17 else 0
        if 0 < category < len(_OPENSKY_CATEGORIES):
            ac.category = _OPENSKY_CATEGORIES[category]
        ac.type = 'opensky'
        time_position = _number(state[3]) or 0.0
        if time_position > 0.0 and feed.source_time > 0.0:
            ac.seen_pos = max(0.0, feed.source_time - time_position)
            ac.has_seen_pos = True
        feed.aircraft.append(ac)
    return feed


# ---- model --------------------------------------------------------------------------------


class Echo(object):
    __slots__ = ('active', 'x', 'y', 'at_deg')

    def __init__(self, active=False, x=0.0, y=0.0, at_deg=0.0):
        self.active = active
        self.x = x
        self.y = y
        self.at_deg = at_deg


class Contact(object):
    def __init__(self, ac):
        self.ac = ac
        self.fresh = False
        self.first_seen = 0.0
        self.last_seen = 0.0
        self.fix_time = 0.0
        self.base_lat = 0.0
        self.base_lon = 0.0

        self.lat = 0.0
        self.lon = 0.0
        self.distance_m = 0.0
        self.bearing_deg = 0.0
        self.x = 0.0
        self.y = 0.0
        self.in_range = False
        self.blip = 0.0
        self.selected = False
        self.echoes = [Echo(), Echo(), Echo()]
        self.echo_count = 0


class Model(object):
    def __init__(self, settings=None):
        self.settings = settings or Settings()
        self.contacts = []
        self.order = []
        self.spotlight_hex = ''
        self.pinned = False
        self.page = 0
        self.page_rows = 9
        self.page_locked = False
        self.spotlight_timer = 0.0
        self.spotlight_changed_at = 0.0
        self.sweep_deg = 0.0
        self.last_update = -1.0
        self.last_feed_at = -1.0
        self.feed_received_at = -1.0
        self.feed_error_at = -1.0
        self.has_feed = False
        self.feed_error = ''
        self.feed_source = ''
        self.in_range_count = 0

    # -- settings and feed

    def set_settings(self, settings):
        self.settings = settings
        self.update(self.last_update if self.last_update >= 0.0 else 0.0)

    def min_altitude_ft(self):
        return (0, 1000, 5000, 10000)[_clampi(self.settings.min_altitude, 0, 3)]

    def passes_filter(self, ac):
        if not ac.has_pos:
            return False
        if ac.on_ground and not self.settings.show_ground:
            return False
        if not ac.on_ground:
            floor = self.min_altitude_ft()
            if floor > 0 and ac.has_alt and ac.alt_ft < floor:
                return False
        return True

    def apply_feed(self, feed, now):
        seen = [False] * len(self.contacts)
        by_hex = {}
        for index, contact in enumerate(self.contacts):
            by_hex[lower_string(contact.ac.hex)] = index
        for ac in feed.aircraft:
            if not self.passes_filter(ac):
                continue
            key = lower_string(ac.hex)
            if not key:
                continue
            found = by_hex.get(key)
            age = _clamp(ac.seen_pos, 0.0, 300.0) if ac.has_seen_pos else 0.0
            if found is None:
                contact = Contact(ac)
                contact.first_seen = now
                contact.last_seen = now
                contact.fix_time = now - age
                contact.base_lat = ac.lat
                contact.base_lon = ac.lon
                contact.lat = ac.lat
                contact.lon = ac.lon
                contact.fresh = True
                by_hex[key] = len(self.contacts)
                self.contacts.append(contact)
                seen.append(True)
            else:
                contact = self.contacts[found]
                contact.ac = ac
                contact.fresh = True
                contact.last_seen = now
                contact.fix_time = now - age
                contact.base_lat = ac.lat
                contact.base_lon = ac.lon
                contact.lat = ac.lat
                contact.lon = ac.lon
                seen[found] = True
        for index, contact in enumerate(self.contacts):
            if not seen[index]:
                contact.fresh = False
        self.has_feed = True
        self.last_feed_at = now
        self.feed_received_at = now
        self.feed_error = ''
        self.feed_source = feed.source
        self.feed_error_at = -1.0

    def apply_error(self, error, now):
        self.feed_error = error
        self.feed_error_at = now

    def feed_age(self, now):
        return -1.0 if self.feed_received_at < 0.0 else max(0.0, now - self.feed_received_at)

    def stale(self, now):
        return not self.has_feed or self.feed_age(now) > self.settings.refresh_seconds * 3.0

    # -- per-frame update

    def update(self, now):
        dt = 0.0 if self.last_update < 0.0 else max(0.0, now - self.last_update)
        dt = min(dt, 5.0)
        period = max(1.0, float(self.settings.sweep_seconds))
        if dt > 0.0:
            self.sweep_deg = normalize_deg(self.sweep_deg + 360.0 * dt / period)
        previous_sweep = self.sweep_deg - 360.0 * dt / period
        range_m = self.settings.range_km * 1000.0
        home = (self.settings.lat, self.settings.lon)

        for contact in self.contacts:
            age = _clamp(now - contact.fix_time, 0.0, MAX_EXTRAPOLATION_S)
            lat, lon = contact.base_lat, contact.base_lon
            ac = contact.ac
            if not ac.on_ground and ac.has_gs and ac.has_track and ac.gs_kt > 0.5:
                lat, lon = destination(lat, lon, ac.track, ac.gs_kt * KT_TO_MS * age)
            contact.lat = lat
            contact.lon = lon
            contact.distance_m = distance_m(home, (lat, lon))
            contact.bearing_deg = bearing_deg(home, (lat, lon)) if contact.distance_m > 1.0 else 0.0
            east, north = east_north_m(home, (lat, lon))
            contact.x = east / range_m
            contact.y = north / range_m
            contact.in_range = contact.distance_m <= range_m

            if contact.in_range and crossed_deg(previous_sweep, self.sweep_deg, contact.bearing_deg):
                for i in range(MAX_ECHOES - 1, 0, -1):
                    contact.echoes[i] = contact.echoes[i - 1]
                contact.echoes[0] = Echo(True, contact.x, contact.y, self.sweep_deg)
                contact.echo_count = min(MAX_ECHOES, contact.echo_count + 1)
            self._compute_blip(contact, now)

        self._remove_contacts(now)
        self._rebuild_order()
        self._update_spotlight(now, dt)
        self.last_update = now

    def _compute_blip(self, contact, now):
        since = normalize_deg(self.sweep_deg - contact.bearing_deg)
        alpha = 0.14 + 0.86 * math.exp(-since / (360.0 * 0.22))
        if since < 90.0:
            alpha += 0.85 * math.exp(-since / 10.0)
        if not contact.fresh:
            fade = _clamp(1.0 - (now - contact.last_seen) / 75.0, 0.0, 1.0)
            alpha *= 0.30 + 0.70 * fade
        if contact.ac.military:
            alpha *= 1.15
        if contact.selected:
            alpha = max(alpha, 0.95)
        contact.blip = _clamp(alpha, 0.0, 1.7)

    def _remove_contacts(self, now):
        self.contacts = [c for c in self.contacts
                         if self.passes_filter(c.ac) and now - c.last_seen <= 90.0]

    def _rebuild_order(self):
        self.order = [i for i, c in enumerate(self.contacts) if c.in_range]
        self.in_range_count = len(self.order)
        self.order.sort(key=lambda i: (self.contacts[i].distance_m,
                                       aircraft_name(self.contacts[i].ac)))
        limit = self.settings.max_contacts
        if len(self.order) > limit:
            kept = []
            for position, index in enumerate(self.order):
                contact = self.contacts[index]
                if position < limit or emergency_label(contact.ac):
                    kept.append(index)
            self.order = kept

    def _update_spotlight(self, now, dt):
        if not self.order:
            self.spotlight_hex = ''
            self.pinned = False
            self.page = 0
            self.page_locked = False
            self.spotlight_timer = 0.0
            for contact in self.contacts:
                contact.selected = False
            return
        position = self.spotlight_position()
        if position < 0:
            self.pinned = False
            self.page_locked = False
            position = 0
            self.spotlight_hex = lower_string(self.contacts[self.order[0]].ac.hex)
            self.spotlight_timer = 0.0
            self.spotlight_changed_at = now
        elif not self.pinned and dt > 0.0:
            self.spotlight_timer += dt
            if self.spotlight_timer >= max(1.0, float(self.settings.detail_seconds)):
                self.spotlight_timer = 0.0
                position = (position + 1) % len(self.order)
                self.spotlight_hex = lower_string(self.contacts[self.order[position]].ac.hex)
                self.spotlight_changed_at = now
                self.page_locked = False
        if not self.page_locked:
            self.page = position // max(1, self.page_rows)
        self.page = _clampi(self.page, 0, self.page_count() - 1)
        for contact in self.contacts:
            contact.selected = lower_string(contact.ac.hex) == self.spotlight_hex

    # -- spotlight and pages

    def find(self, hex_value):
        key = lower_string(hex_value)
        for contact in self.contacts:
            if lower_string(contact.ac.hex) == key:
                return contact
        return None

    def spotlight(self):
        for contact in self.contacts:
            if lower_string(contact.ac.hex) == self.spotlight_hex:
                return contact
        return None

    def page_count(self):
        return max(1, (len(self.order) + self.page_rows - 1) // self.page_rows)

    def set_page_rows(self, rows):
        self.page_rows = max(1, int(rows))

    def set_page(self, page):
        self.page_locked = True
        self.page = _clampi(page, 0, self.page_count() - 1)

    def pin(self, hex_value):
        key = lower_string(hex_value)
        for position, index in enumerate(self.order):
            if lower_string(self.contacts[index].ac.hex) == key:
                self.pinned = True
                self.spotlight_hex = key
                self.spotlight_timer = 0.0
                self.spotlight_changed_at = self.last_update if self.last_update >= 0.0 else 0.0
                self.page_locked = False
                self.page = position // max(1, self.page_rows)
                for contact in self.contacts:
                    contact.selected = lower_string(contact.ac.hex) == key
                return True
        return False

    def unpin(self):
        self.pinned = False
        self.spotlight_timer = 0.0

    def step_spotlight(self, delta):
        if not self.order:
            return
        position = self.spotlight_position()
        if position < 0:
            position = 0
        nxt = (position + delta) % len(self.order)
        if nxt < 0:
            nxt += len(self.order)
        self.pin(self.contacts[self.order[nxt]].ac.hex)

    def spotlight_position(self):
        for position, index in enumerate(self.order):
            if lower_string(self.contacts[index].ac.hex) == self.spotlight_hex:
                return position
        return -1

    def spotlight_progress(self):
        if self.pinned:
            return 0.0
        return _clamp(self.spotlight_timer / max(1.0, float(self.settings.detail_seconds)),
                      0.0, 1.0)

    def seconds_to_sweep(self):
        period = max(1.0, float(self.settings.sweep_seconds))
        return (360.0 - self.sweep_deg) / 360.0 * period

    def reset_clock(self, now):
        self.last_update = now
        self.sweep_deg = 0.0

    def reset_sweep(self, now):
        self.last_update = now
        self.sweep_deg = 0.0


# ---- formatting ---------------------------------------------------------------------------


def trim_string(text):
    return text.strip()


def upper_string(text):
    return text.upper()


def lower_string(text):
    return text.lower()


def fmt_commas(value):
    return '{:,}'.format(int(value))


def fmt_altitude(ac, units, compact=False):
    if ac.on_ground:
        return 'GND'
    if not ac.has_alt:
        return 'N/A'
    if units == 1:
        if ac.alt_ft >= 18000.0:
            return 'FL%03d' % (_round_half_away(ac.alt_ft / 100.0))
        return fmt_commas(_round_half_away(ac.alt_ft)) + ('FT' if compact else ' FT')
    metres = _round_half_away(ac.alt_ft * FT_TO_M)
    return fmt_commas(metres) + ('M' if compact else ' M')


def fmt_speed(ac, units, compact=False):
    if not ac.has_gs:
        return 'N/A'
    if units == 1:
        return fmt_commas(_round_half_away(ac.gs_kt)) + ('KT' if compact else ' KT')
    return fmt_commas(_round_half_away(ac.gs_kt * 1.852)) + ('KM/H' if compact else ' KM/H')


def fmt_distance(metres, units, compact=False):
    if metres < 0.0:
        return 'N/A'
    if units == 1:
        nm = metres / METRES_PER_NM
        if nm < 100.0:
            return '%.1f%s' % (nm, 'NM' if compact else ' NM')
        return '%.0f%s' % (nm, 'NM' if compact else ' NM')
    if metres < 1000.0:
        return '%.0f%s' % (metres, 'M' if compact else ' M')
    if metres < 10000.0:
        return '%.1f%s' % (metres / 1000.0, 'KM' if compact else ' KM')
    return '%.0f%s' % (metres / 1000.0, 'KM' if compact else ' KM')


def fmt_vertical_rate(ac, units, compact=False):
    if not ac.has_baro_rate and not ac.has_geom_rate:
        return 'LEVEL'
    fpm = ac.baro_rate_fpm if ac.has_baro_rate else ac.geom_rate_fpm
    if abs(fpm) < 50.0:
        return 'LEVEL'
    if units == 1:
        value = _round_half_away(fpm / 5.0) * 5
        return '%+d%s' % (value, 'FPM' if compact else ' FPM')
    return '%+.1f%s' % (fpm * 0.00508, 'M/S' if compact else ' M/S')


def fmt_deg(value):
    return '%03d°' % (_round_half_away(normalize_deg(value)) % 360)


def fmt_bearing(value):
    return fmt_deg(value)


def fmt_coord(value, latitude):
    hemi = ('S' if value < 0 else 'N') if latitude else ('W' if value < 0 else 'E')
    return '%.4f%s' % (abs(value), hemi)


def fmt_seen(seconds):
    if seconds < 0.0:
        return 'N/A'
    if seconds < 10.0:
        return '%.1f s' % seconds
    if seconds < 120.0:
        return '%.0f s' % seconds
    return '%.0f min' % (seconds / 60.0)


def aircraft_name(ac):
    name = upper_string(trim_string(ac.flight))
    if not name:
        name = upper_string(trim_string(ac.reg))
    if not name:
        name = upper_string(trim_string(ac.hex))
    return name


_CATEGORY_NAMES = {
    'A1': 'LIGHT', 'A2': 'SMALL', 'A3': 'LARGE', 'A4': 'HIGH VORTEX', 'A5': 'HEAVY',
    'A6': 'HIGH PERF', 'A7': 'ROTORCRAFT', 'B1': 'GLIDER', 'B2': 'LIGHTER-THAN-AIR',
    'B3': 'PARACHUTIST', 'B4': 'ULTRALIGHT', 'B5': 'RESERVED', 'B6': 'UAV', 'B7': 'SPACE',
    'C1': 'SURFACE EMERG', 'C2': 'SURFACE SERVICE', 'C3': 'POINT OBSTACLE',
    'C4': 'CLUSTER OBSTACLE', 'C5': 'LINE OBSTACLE', 'A0': 'NO INFO', 'B0': 'NO INFO',
    'C0': 'NO INFO',
}


def category_name(code):
    up = upper_string(trim_string(code))
    return _CATEGORY_NAMES.get(up, up)


def source_name(ac):
    if ac.mlat:
        return 'MLAT'
    if ac.tisb:
        return 'TIS-B'
    kind = lower_string(ac.type)
    if kind.startswith('adsb'):
        return 'ADS-B'
    if kind == 'mode_s':
        return 'MODE S'
    if kind == 'adsr':
        return 'ADS-R'
    if kind == 'opensky':
        return 'OPENSKY'
    return upper_string(kind) if kind else 'UNKNOWN'


def emergency_label(ac):
    value = upper_string(trim_string(ac.emergency))
    if value and value != 'NONE':
        return value
    if ac.squawk == '7500':
        return 'HIJACK'
    if ac.squawk == '7600':
        return 'RADIO FAIL'
    if ac.squawk == '7700':
        return 'EMERGENCY'
    return ''


def flag_text(ac):
    flags = []
    if ac.military:
        flags.append('MILITARY')
    emergency = emergency_label(ac)
    if emergency:
        flags.append(emergency)
    if ac.interesting:
        flags.append('INTERESTING')
    if ac.pia:
        flags.append('PIA')
    if ac.ladd:
        flags.append('LADD')
    if ac.alert:
        flags.append('ALERT')
    if ac.spi:
        flags.append('SPI')
    return ' · '.join(flags)


def range_text(range_km, units):
    if units == 1:
        return '%d KM / %d NM' % (range_km, _round_half_away(range_km / 1.852))
    return '%d KM' % range_km


def range_short(range_km, units):
    if units == 1:
        return '%dNM' % _round_half_away(range_km / 1.852)
    return '%dKM' % range_km


def truncate_text(text, limit):
    return text if len(text) <= limit else text[:limit]


def fit_text(width_fn, text, max_width):
    if width_fn(text) <= max_width:
        return text
    out = text
    while out and width_fn(out + '...') > max_width:
        out = out[:-1]
    return out + '...'

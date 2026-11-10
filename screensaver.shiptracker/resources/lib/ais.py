"""AIS message decoding and the in-memory fleet. No Kodi imports and no network here, so the
message layouts and the snapshot rules are tested directly.

The field names follow the aisstream.io JSON: MetaData carries the MMSI and the padded ship
name; PositionReport family messages carry the position; ShipStaticData and StaticDataReport
carry the identity, dimensions and voyage. A ship is one dict, updated in place under a lock.
"""

import threading
import time
from datetime import datetime, timezone

from . import config

POSITION_TYPES = config.POSITION_TYPES
STATIC_TYPES = config.STATIC_TYPES

INVALID_SOG = 102.3
INVALID_COURSE = 360.0
INVALID_HEADING = 511


def clean(text):
    text = (text or '').replace('@', ' ').strip()
    return ' '.join(text.split()) or None


def integer(value, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_eta(eta):
    if not isinstance(eta, dict):
        return None
    month, day = integer(eta.get('Month') or 0), integer(eta.get('Day') or 0)
    hour, minute = integer(eta.get('Hour') or 0), integer(eta.get('Minute') or 0)
    if not month or not day or hour is None or hour >= 24 or month > 12 or day > 31:
        return None
    return '%02d-%02d %02d:%02d UTC' % (month, day, hour, minute if minute < 60 else 0)


def iso(timestamp):
    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec='seconds')


def apply_dimension(ship, dimension):
    if not isinstance(dimension, dict):
        return
    a, b, c, d = (integer(dimension.get(key) or 0) or 0 for key in 'ABCD')
    if a + b:
        ship['length'] = float(a + b)
    if c + d:
        ship['beam'] = float(c + d)


def _apply_common(ship, body):
    name = clean(body.get('Name'))
    if name:
        ship['name'] = name
    call_sign = clean(body.get('CallSign'))
    if call_sign:
        ship['call_sign'] = call_sign


def apply_static(ship, body, now):
    imo = integer(body.get('ImoNumber'))
    if imo:
        ship['imo'] = imo
    _apply_common(ship, body)
    destination = clean(body.get('Destination'))
    if destination:
        ship['destination'] = destination
    ship_type = integer(body.get('Type'))
    if ship_type:
        ship['ship_type'] = ship_type
    draught = float_or_none(body.get('MaximumStaticDraught'))
    if draught:
        ship['draught'] = draught
    eta = fmt_eta(body.get('Eta'))
    if eta:
        ship['eta'] = eta
    apply_dimension(ship, body.get('Dimension'))
    ship['static_seen'] = now


def apply_static_report(ship, body, now):
    """Class B transponders split their static data over two reports."""
    report_a = body.get('ReportA') or {}
    report_b = body.get('ReportB') or {}
    _apply_common(ship, report_a)
    _apply_common(ship, report_b)
    ship_type = integer(report_b.get('ShipType'))
    if ship_type:
        ship['ship_type'] = ship_type
    apply_dimension(ship, report_b.get('Dimension'))
    ship['static_seen'] = now


def apply_position(ship, body, meta, now):
    latitude = body.get('Latitude')
    if latitude is None:
        latitude = meta.get('latitude')
    longitude = body.get('Longitude')
    if longitude is None:
        longitude = meta.get('longitude')
    latitude, longitude = float_or_none(latitude), float_or_none(longitude)
    if latitude is not None and longitude is not None and \
            -90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0 and \
            not (abs(latitude) == 91 or abs(longitude) == 181):
        ship['lat'] = latitude
        ship['lon'] = longitude

    sog = float_or_none(body.get('Sog'))
    ship['sog'] = sog if sog is not None and sog < INVALID_SOG else None
    course = float_or_none(body.get('Cog'))
    ship['cog'] = course if course is not None and course < INVALID_COURSE else None
    heading = integer(body.get('TrueHeading'))
    ship['heading'] = heading if heading is not None and heading < INVALID_HEADING else None
    navigation = integer(body.get('NavigationalStatus'))
    if navigation is not None:
        ship['nav_status'] = navigation
    rate_of_turn = integer(body.get('RateOfTurn'))
    if rate_of_turn is not None:
        ship['rate_of_turn'] = rate_of_turn
    ship['seen'] = now


class Fleet(object):
    """Every ship heard in this run, keyed by MMSI, safe to read from another thread."""

    def __init__(self):
        self._lock = threading.RLock()
        self.ships = {}

    def handle(self, message, now=None):
        """Apply one aisstream message; return the MMSI when a ship changed, else None."""
        now = time.time() if now is None else now
        message_type = message.get('MessageType')
        if message_type == 'SubscriptionConfirmation':
            return None
        if message_type not in POSITION_TYPES and message_type not in STATIC_TYPES:
            return None
        meta = message.get('MetaData') or {}
        body = (message.get('Message') or {}).get(message_type) or {}
        if not isinstance(body, dict):
            return None
        mmsi = integer(meta.get('MMSI')) or integer(body.get('UserID'))
        if not mmsi:
            return None

        with self._lock:
            ship = self.ships.get(mmsi)
            if ship is None:
                ship = {'mmsi': mmsi, 'first_seen': now}
                self.ships[mmsi] = ship
            name = clean(meta.get('ShipName'))
            if name:
                ship['name'] = name

            if message_type in POSITION_TYPES:
                apply_position(ship, body, meta, now)
                if message_type == 'ExtendedClassBPositionReport':
                    _apply_common(ship, body)
                    ship_type = integer(body.get('Type'))
                    if ship_type:
                        ship['ship_type'] = ship_type
                    apply_dimension(ship, body.get('Dimension'))
            elif message_type == 'ShipStaticData':
                apply_static(ship, body, now)
            elif message_type == 'StaticDataReport':
                apply_static_report(ship, body, now)
            else:
                return None
            ship['updated'] = now
            return mmsi

    def get(self, mmsi):
        with self._lock:
            ship = self.ships.get(mmsi)
            return dict(ship) if ship is not None else None

    def seed(self, rows):
        """Fill the fleet from stored rows so the screen has something to show at start-up."""
        with self._lock:
            for row in rows:
                try:
                    mmsi = int(row['mmsi'])
                except (KeyError, TypeError, ValueError):
                    continue
                ship = dict(row)
                ship['mmsi'] = mmsi
                current = self.ships.get(mmsi)
                if current is None:
                    self.ships[mmsi] = ship
                else:
                    for key, value in ship.items():
                        if current.get(key) in (None, '') and value not in (None, ''):
                            current[key] = value

    def snapshot(self, now=None, timeout=900):
        """Ships with a position seen within timeout, as copies, sorted by display name."""
        now = time.time() if now is None else now
        with self._lock:
            rows = [dict(ship) for ship in self.ships.values()]
        visible = []
        for ship in rows:
            seen = ship.get('seen') or ship.get('updated') or 0
            if now - seen > timeout:
                continue
            if ship.get('lat') is None or ship.get('lon') is None:
                continue
            ship['age'] = max(0.0, now - seen)
            visible.append(ship)
        visible.sort(key=lambda s: ((s.get('name') or str(s.get('mmsi'))).upper(),
                                    s.get('mmsi') or 0))
        return visible

    def count(self):
        with self._lock:
            return len(self.ships)

    def clear(self):
        with self._lock:
            self.ships.clear()

"""Aircraft from ADS-B: which to show under a cap, and where they are now. No Kodi imports.

The whole-world feed (OpenSky Network) can only be fetched every half hour or so without
running out of anonymous credits, so between fetches each aircraft is flown on along its
track at its ground speed. At world scale that is good to a pixel or two for many minutes.
"""

import json
import math

# Fields of one stored aircraft, as a list (compact on disk and in memory).
ICAO, CALLSIGN, LON, LAT, TRACK, SPEED, ALT, AT, SQUAWK = range(9)
EMERGENCY = ('7500', '7600', '7700')
EARTH_M = 6371000.0
BIN_DEG = 15.0         # cells for spreading the selection over the world
MAX_DEAD_RECKON = 3600.0


def parse_opensky(data):
    """OpenSky /states/all JSON -> list of airborne aircraft with a position and velocity."""
    out = []
    for s in data.get('states') or []:
        if len(s) < 15 or s[5] is None or s[6] is None or s[8]:
            continue
        speed, track = s[9], s[10]
        if speed is None or track is None:
            continue
        alt = s[7] if s[7] is not None else s[13]
        at = s[3] or s[4] or data.get('time') or 0
        out.append([s[0], (s[1] or '').strip(), round(s[5], 4), round(s[6], 4), round(track, 1),
                    round(speed, 1), None if alt is None else int(alt), int(at), s[14] or ''])
    return out


def encode(aircraft, fetched):
    return json.dumps({'time': fetched, 'ac': aircraft}, separators=(',', ':')).encode('utf-8')


def decode(data):
    return json.loads(data.decode('utf-8')).get('ac') or []


def _bin(ac):
    return (int((ac[LON] + 180.0) // BIN_DEG), int((ac[LAT] + 90.0) // BIN_DEG))


def _stable_key(ac):
    # A fixed pseudo-random order, so the same aircraft are picked from one fetch to the next.
    return int(ac[ICAO], 16) * 2654435761 % 4294967296 if all(c in '0123456789abcdef' for c in ac[ICAO]) else 0


def select(aircraft, cap, keep=()):
    """At most cap aircraft, spread over the world in proportion to the square root of the
    traffic in each 15-degree cell: busy skies still look busy, oceans aren't empty.
    Emergencies always come first; aircraft in keep (shown last time) are preferred."""
    if cap <= 0 or not aircraft:
        return []
    keep = set(keep)
    chosen = [ac for ac in aircraft if ac[SQUAWK] in EMERGENCY][:cap]
    taken = set(ac[ICAO] for ac in chosen)
    bins = {}
    for ac in aircraft:
        if ac[ICAO] not in taken:
            bins.setdefault(_bin(ac), []).append(ac)
    for members in bins.values():
        members.sort(key=lambda ac: (ac[ICAO] not in keep, _stable_key(ac)))
    room = cap - len(chosen)
    weights = dict((b, math.sqrt(len(m))) for b, m in bins.items())
    total = sum(weights.values()) or 1.0
    quota = dict((b, min(len(bins[b]), int(room * w / total))) for b, w in weights.items())
    # Hand out what rounding left over to the cells with the largest remainders.
    spare = room - sum(quota.values())
    order = sorted(bins, key=lambda b: -(room * weights[b] / total - quota[b]))
    while spare > 0 and order:
        progressed = False
        for b in order:
            if spare <= 0:
                break
            if quota[b] < len(bins[b]):
                quota[b] += 1
                spare -= 1
                progressed = True
        if not progressed:
            break
    for b, members in bins.items():
        chosen.extend(members[:quota[b]])
    return chosen[:cap]


def position(ac, now):
    """(lon, lat) flown on from the last report along the track at ground speed."""
    dt = max(0.0, min(MAX_DEAD_RECKON, now - ac[AT]))
    if ac[SPEED] * dt <= 0:
        return ac[LON], ac[LAT]
    return ahead(ac[LON], ac[LAT], ac[TRACK], ac[SPEED] * dt)


def ahead(lon, lat, bearing, metres):
    """The point `metres` along a great circle from (lon, lat) on `bearing`."""
    d = metres / EARTH_M
    lat1, lon1, brg = math.radians(lat), math.radians(lon), math.radians(bearing)
    lat2 = math.asin(max(-1.0, min(1.0, math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brg))))
    lon2 = lon1 + math.atan2(math.sin(brg) * math.sin(d) * math.cos(lat1),
                             math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return (math.degrees(lon2) + 540.0) % 360.0 - 180.0, math.degrees(lat2)


def heading(ac, lon, lat, now):
    """The track at the dead-reckoned point (a great circle's bearing drifts as it goes)."""
    if ac[SPEED] <= 0 or now <= ac[AT]:
        return ac[TRACK]
    lat1, lat2 = math.radians(ac[LAT]), math.radians(lat)
    dlon = math.radians(ac[LON] - lon)
    # Bearing from the current point back to the start, turned round.
    y = math.sin(dlon) * math.cos(lat1)
    x = math.cos(lat2) * math.sin(lat1) - math.sin(lat2) * math.cos(lat1) * math.cos(dlon)
    if abs(x) < 1e-12 and abs(y) < 1e-12:
        return ac[TRACK]
    return (math.degrees(math.atan2(y, x)) + 180.0) % 360.0


def color(ac):
    """ARGB diffuse: red for an emergency, otherwise by altitude (low cyan to high white)."""
    if ac[SQUAWK] in EMERGENCY:
        return 'FFFF5050'
    alt = ac[ALT] or 0
    if alt < 3000:
        return 'E080E0FF'
    if alt < 9000:
        return 'E0FFE082'
    return 'E0FFFFFF'

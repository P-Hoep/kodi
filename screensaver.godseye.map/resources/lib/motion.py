"""Smooth motion for layers whose vehicles stop and turn (transit). No Kodi imports.

Each refresh, a vehicle glides in a straight line from where it is currently drawn to
its newly reported position, taking one refresh interval to get there. The map is shown
about one refresh behind, but nothing ever jumps and every point it passes through lies
between real reports (unlike projecting forward, which overshoots stops)."""

import math

MIN_MOVE_M = 5.0  # below this a vehicle is treated as stopped and keeps its reported bearing
# A jump implying more than this (~100 mph) is a bad fix or a relocated vehicle, not driving:
# the vehicle reappears at its new position instead of streaking across the map.
MAX_GLIDE_SPEED_MS = 45.0


def bearing(lat1, lon1, lat2, lon2):
    """Initial compass bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _distance_m(lat1, lon1, lat2, lon2):
    k = 111195.0  # metres per degree of latitude
    return math.hypot((lat2 - lat1) * k, (lon2 - lon1) * k * math.cos(math.radians((lat1 + lat2) / 2)))


class Glider(object):
    def __init__(self):
        # uid -> (from_lat, from_lon, to_lat, to_lon, start, duration)
        self.tracks = {}

    def update(self, items, now, duration):
        """Start gliding every item towards its new position. Sets item.heading to the
        direction of travel while it moves."""
        tracks = {}
        for item in items:
            old = self.tracks.get(item.uid)
            if old is None:
                start_lat, start_lon = item.lat, item.lon  # new vehicle: appears where reported
            else:
                start_lat, start_lon = self._at(old, now)
            distance = _distance_m(start_lat, start_lon, item.lat, item.lon)
            if duration > 0 and distance / duration > MAX_GLIDE_SPEED_MS:
                start_lat, start_lon = item.lat, item.lon
            elif distance >= MIN_MOVE_M:
                item.heading = bearing(start_lat, start_lon, item.lat, item.lon)
            tracks[item.uid] = (start_lat, start_lon, item.lat, item.lon, now, float(duration))
        self.tracks = tracks  # vehicles missing from the feed are dropped

    def position(self, item, now):
        track = self.tracks.get(item.uid)
        if track is None:
            return item.lat, item.lon
        return self._at(track, now)

    @staticmethod
    def _at(track, now):
        from_lat, from_lon, to_lat, to_lon, start, duration = track
        f = 1.0 if duration <= 0 else min(1.0, max(0.0, (now - start) / duration))
        return from_lat + (to_lat - from_lat) * f, from_lon + (to_lon - from_lon) * f

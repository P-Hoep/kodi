"""RainViewer Weather Maps API (past radar outside the US). Keyless, personal use.

Since 1 Jan 2026 the free API serves past radar only, at zoom 7 and below, in one colour
scheme; tiles above zoom 7 are drawn enlarged. weather-maps.json lists frames (10-minute
steps, about 2 hours) with a path each; a tile is {host}{path}/256/{z}/{x}/{y}/{color}/1_1.png.
LibreWXR (librewxr.py) serves the same API with nowcast frames, so it subclasses this.
"""

import time

from .. import net
from .base import Source

MAPS = 'https://api.rainviewer.com/public/weather-maps.json'


class RainViewer(Source):
    id = 'rainviewer'
    name = 'RainViewer'
    attribution = 'Radar: RainViewer'
    kinds = ('past',)
    max_zoom = 7
    color = 2          # the only scheme on the free API

    def __init__(self, universal_blue=False):
        self._maps = (0.0, None)
        if universal_blue:
            self.color = 2

    def maps_url(self):
        return MAPS

    def maps(self):
        checked, value = self._maps
        if value is None or time.time() - checked > 240:
            value = net.fetch_json(self.maps_url(), timeout=10)
            self._maps = (time.time(), value)
        return value

    def tile_url(self, host, path, z, x, y):
        return '%s%s/256/%d/%d/%d/%d/1_1.png' % (host, path, z, x, y, self.color)

    def frames(self, view, kind, minutes, size=None):
        try:
            data = self.maps()
        except Exception:
            return []
        host = data.get('host') or ''
        radar = data.get('radar') or {}
        entries = radar.get('past' if kind == 'past' else 'nowcast') or []
        now = time.time()
        out = []
        for e in entries:
            t = e.get('time')
            if not t:
                continue
            if kind == 'past' and t < now - minutes * 60 - 300:
                continue
            if kind == 'future' and t > now + minutes * 60:
                continue
            parts = [(self.tile_url(host, e['path'], z, x, y), sx, sy, s, s)
                     for z, x, y, sx, sy, s in view.tiles_at(self.max_zoom)]
            out.append({'t': t, 'kind': kind, 'key': '%s_%s_%d' % (self.id, e['path'].strip('/').replace('/', '_'),
                                                                    view.zoom),
                        'run': None, 'parts': parts})
        return out

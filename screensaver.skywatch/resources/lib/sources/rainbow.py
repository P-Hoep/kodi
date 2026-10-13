"""Rainbow.ai Tiles API (future radar, global ML nowcast). Free key: 30,000 tiles a month.

GET /tiles/v1/snapshot gives the newest snapshot (epoch, 10-minute steps); tiles are
/tiles/v1/precip-global/{snapshot}/{forecast seconds}/{z}/{x}/{y}, forecast 0..14400 in
600 s steps, zoom 0..12. To stay inside the free tier SkyWatch draws tiles one zoom level
below the view (each tile shown at 512 px), uses 20-minute steps, and lets budget.py cap
refreshes (radar.py: at most hourly, only while the screensaver runs).
"""

import time

from .. import net
from .base import Source

API = 'https://api.rainbow.ai/tiles/v1'
STEP = 1200
MAX_SECONDS = 14400


class Rainbow(Source):
    id = 'rainbow'
    name = 'Rainbow.ai'
    attribution = 'Future radar: Rainbow.ai'
    kinds = ('future',)
    model = True
    refresh = 3600

    def __init__(self, key, cap):
        self.key = key.strip()
        self.quota = cap
        self._snap = (0.0, None)

    def snapshot(self):
        checked, value = self._snap
        if value is None or time.time() - checked > 600:
            data = net.fetch_json('%s/snapshot?layer=precip-global&token=%s' % (API, self.key), timeout=10)
            if isinstance(data, dict):
                value = int(data.get('snapshot') or data.get('timestamp') or data.get('time') or 0) or None
            elif isinstance(data, (int, float)):
                value = int(data)
            self._snap = (time.time(), value)
        return value

    def frames(self, view, kind, minutes, size=None):
        if kind != 'future' or not self.key:
            return []
        try:
            snap = self.snapshot()
        except Exception:
            return []
        if not snap:
            return []
        z = max(0, view.zoom - 1)
        out = []
        seconds = STEP
        while seconds <= min(MAX_SECONDS, minutes * 60):
            parts = [('%s/precip-global/%d/%d/%d/%d/%d?token=%s&color=0' % (API, snap, seconds, tz, tx, ty, self.key),
                      sx, sy, s, s) for tz, tx, ty, sx, sy, s in view.tiles_at(z)]
            out.append({'t': snap + seconds, 'kind': 'future', 'key': 'rainbow_%d_%d_%d' % (snap, seconds, view.zoom),
                        'run': snap, 'parts': parts})
            seconds += STEP
        return out

"""Iowa Environmental Mesonet NEXRAD composite (past radar, US). Keyless.

One WMS GetMap per 5-minute frame, sized to the view, so a frame is a single image that
lines up exactly with the base-map tiles. Layer nexrad-n0q-wmst takes a TIME parameter.
"""

import time

from .. import geo, net
from .base import Source, floor_to, iso, parse_iso, wms_url, whole_view

WMS = 'https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi'
LATEST = 'https://mesonet.agron.iastate.edu/data/gis/images/4326/USCOMP/n0q_0.json'
STEP = 300


class IEM(Source):
    id = 'iem'
    name = 'IEM NEXRAD'
    attribution = 'Radar: IEM / NWS NEXRAD'
    kinds = ('past',)

    def __init__(self):
        self._latest = (0.0, None)

    def covers(self, lat, lon):
        return geo.inside(lat, lon, geo.IEM_NEXRAD)

    def latest(self):
        """Valid time of the newest composite (checked at most every 2 minutes)."""
        checked, value = self._latest
        if value is None or time.time() - checked > 120:
            try:
                meta = net.fetch_json(LATEST, timeout=10)
                value = parse_iso(meta['meta']['valid'])
            except Exception:
                value = value or floor_to(time.time() - 600, STEP)
            self._latest = (time.time(), value)
        return value

    def frames(self, view, kind, minutes, size=None, step=STEP):
        if kind != 'past':
            return []
        size = size or (view.width, view.height)
        newest = self.latest()
        out = []
        for k in range(int(minutes * 60 // step), -1, -1):
            t = newest - k * step
            url = wms_url(WMS, 'nexrad-n0q-wmst', view, size, '&TIME=' + iso(t))
            out.append({'t': t, 'kind': 'past', 'key': 'iem_%d' % t, 'run': None,
                        'parts': whole_view(url, view)})
        return out

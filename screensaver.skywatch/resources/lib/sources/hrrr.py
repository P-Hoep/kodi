"""HRRR simulated reflectivity from the IEM (future radar, CONUS). Keyless.

The WMS serves the newest complete run with one layer per forecast minute (refd_0015 ...
refd_1080, 15-minute steps). refd_1080.json names the run, so frames are keyed by run and
minute and expire when a new run lands (hourly, ready about 50 minutes past the hour).
REFP is the same reflectivity coloured by precipitation type.
"""

import time

from .. import geo, net
from .base import Source, parse_iso, wms_url, whole_view

WMS = 'https://mesonet.agron.iastate.edu/cgi-bin/wms/hrrr/%s.cgi'
RUN = 'https://mesonet.agron.iastate.edu/data/gis/images/4326/hrrr/refd_1080.json'
STEP = 900
LAST_MINUTE = 1080


class HRRR(Source):
    id = 'hrrr'
    name = 'HRRR (IEM)'
    attribution = 'Future radar: NOAA HRRR via IEM'
    kinds = ('future',)
    model = True

    def __init__(self, precip_type=False):
        self.product = 'refp' if precip_type else 'refd'
        self._run = (0.0, None)

    def covers(self, lat, lon):
        return geo.inside(lat, lon, geo.HRRR)

    def run(self):
        """Initialisation time of the newest complete run (checked at most every 5 minutes)."""
        checked, value = self._run
        if value is None or time.time() - checked > 300:
            try:
                value = parse_iso(net.fetch_json(RUN, timeout=10)['model_init_utc'])
            except Exception:
                pass
            self._run = (time.time(), value)
        return value

    def frames(self, view, kind, minutes, size=None, step=STEP, start=None):
        if kind != 'future':
            return []
        run = self.run()
        if run is None:
            return []
        size = size or (view.width, view.height)
        now = time.time() if start is None else start
        first = int(now // step + 1) * step
        out = []
        t = first
        while t <= now + minutes * 60:
            minute = int((t - run) // 60)
            if 0 < minute <= LAST_MINUTE and minute % 15 == 0:
                layer = '%s_%04d' % (self.product, minute)
                url = wms_url(WMS % self.product, layer, view, size)
                out.append({'t': t, 'kind': 'future', 'key': 'hrrr_%s_%d_%04d' % (self.product, run, minute),
                            'run': run, 'parts': whole_view(url, view)})
            t += step
        return out

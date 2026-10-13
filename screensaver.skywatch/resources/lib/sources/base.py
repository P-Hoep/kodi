"""The common radar/imagery source interface. No Kodi imports.

A source turns a view into timestamped frames. Each frame is a dict:

    {'t': valid epoch, 'kind': 'past' | 'future', 'key': unique cache key,
     'run': model run epoch or None, 'parts': [(url, x, y, w, h), ...]}

parts are images in screen coordinates (1920x1080 space). WMS sources return one part per
frame, sized to the whole view; tile sources return one part per tile. The fallback chain
(radar.py) and the budget manager treat every source alike through:

    frames(view, kind, minutes) -> [frame]      kind 'past': last N minutes; 'future': next N
    fetch(url) -> bytes                          one part
    covers(lat, lon) -> bool
    cost(frame) -> requests a frame costs
    quota -> None or (monthly cap)               used by the budget manager
    expiry -> seconds a fetched past frame stays valid
"""

import time

from .. import net

FRAME_TTL = 3 * 3600   # radar tiles expire after 3 h


class Source(object):
    id = 'base'
    name = 'Source'
    attribution = ''
    quota = None
    expiry = FRAME_TTL
    kinds = ('past',)

    def covers(self, lat, lon):
        return True

    def frames(self, view, kind, minutes, size=None):
        return []

    def fetch(self, url):
        return net.fetch_image(url, timeout=10)

    def cost(self, frame):
        return len(frame['parts'])


def floor_to(epoch, step):
    return int(epoch // step) * step


def iso(epoch):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch))


def parse_iso(text):
    """'2026-10-12T23:00:00Z' or '2026-10-12T23:00Z' -> epoch (UTC)."""
    import calendar
    text = text.strip().rstrip('Z').replace(' ', 'T')
    if '+' in text[10:]:
        text = text[:10] + text[10:].split('+')[0]
    fmt = '%Y-%m-%dT%H:%M:%S' if text.count(':') == 2 else '%Y-%m-%dT%H:%M'
    return calendar.timegm(time.strptime(text[:19] if text.count(':') == 2 else text[:16], fmt))


def wms_url(base, layer, view, size, extra=''):
    """GetMap for the whole view in EPSG:3857 at size (w, h)."""
    x0, y0, x1, y1 = view.bbox3857()
    return ('%s?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1&LAYERS=%s&STYLES=&SRS=EPSG:3857'
            '&BBOX=%.1f,%.1f,%.1f,%.1f&WIDTH=%d&HEIGHT=%d&FORMAT=image/png&TRANSPARENT=true%s'
            % (base, layer, x0, y0, x1, y1, size[0], size[1], extra))


def whole_view(url, view):
    return [(url, 0, 0, view.width, view.height)]

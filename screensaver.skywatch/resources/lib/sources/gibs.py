"""NASA GIBS geostationary imagery (satellite scene): GeoColor by day, clean infrared at
night, as one WMS image for the view. Keyless.

GOES-East covers the Americas east of about 115W, GOES-West the eastern Pacific and the
western US. Imagery lands 20-40 minutes after the scan, so the newest frame tried is 30
minutes old, then older ones if that fails.
"""

import time

from .. import astro
from .base import Source, iso, whole_view

WMS = 'https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi'


def satellite_for(lat, lon):
    if -60 <= lat <= 60:
        if -115 <= lon <= -20:
            return 'GOES-East'
        if lon < -115 or lon > 165:
            return 'GOES-West'
    return None


class GIBS(Source):
    id = 'gibs'
    name = 'NASA GIBS GOES'
    attribution = 'Satellite: NASA GIBS / NOAA GOES'

    def covers(self, lat, lon):
        return satellite_for(lat, lon) is not None

    def layer(self, lat, lon, epoch=None):
        sat = satellite_for(lat, lon)
        day = astro.sun_altitude(time.time() if epoch is None else epoch, lat, lon) > 3
        return '%s_ABI_%s' % (sat, 'GeoColor' if day else 'Band13_Clean_Infrared'), day

    def image(self, view, size, age_minutes=30):
        """(url, valid time, is_day) for the newest likely-available image."""
        t = int((time.time() - age_minutes * 60) // 600) * 600
        layer, day = self.layer(view.lat, view.lon, t)
        x0, y0, x1, y1 = view.bbox3857()
        fmt = 'image/jpeg' if day else 'image/png'
        url = ('%s?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1&LAYERS=%s&STYLES=&SRS=EPSG:3857'
               '&BBOX=%.1f,%.1f,%.1f,%.1f&WIDTH=%d&HEIGHT=%d&FORMAT=%s&TIME=%s'
               % (WMS, layer, x0, y0, x1, y1, size[0], size[1], fmt, iso(t)))
        return url, t, day, whole_view(url, view)

"""LibreWXR: a self-hosted, RainViewer-compatible radar server with nowcast frames and every
colour scheme. SkyWatch only needs its base URL."""

from .rainviewer import RainViewer


class LibreWXR(RainViewer):
    id = 'librewxr'
    name = 'LibreWXR'
    attribution = 'Radar: LibreWXR'
    kinds = ('past', 'future')
    max_zoom = 10

    def __init__(self, base_url, universal_blue=False):
        RainViewer.__init__(self)
        self.base = base_url.rstrip('/')
        self.color = 2 if universal_blue else 6   # 6: NEXRAD level III colours

    def maps_url(self):
        return self.base + '/public/weather-maps.json'

    def tile_url(self, host, path, z, x, y):
        # A server behind a LAN address may report a host the TV can't reach; prefer ours.
        return '%s%s/256/%d/%d/%d/%d/1_1.png' % (self.base, path, z, x, y, self.color)

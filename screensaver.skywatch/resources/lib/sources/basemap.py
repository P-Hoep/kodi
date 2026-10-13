"""Base-map tile sources: Esri's Canvas maps (keyless; Dark Gray is the default because it
reads best under radar), OpenStreetMap, Esri World Imagery and Stadia terrain (free key).
Each style is a background layer drawn under the radar and a labels layer drawn above it.
(CARTO's basemaps were the first choice but now require an API key.)"""

from ..cache import TileSource

ESRI_BASE = 'https://server.arcgisonline.com/ArcGIS/rest/services/%s/MapServer/tile/{z}/{y}/{x}'
ESRI_CANVAS_CREDIT = 'Esri, HERE, Garmin, © OpenStreetMap contributors'
ESRI_IMAGERY_CREDIT = 'Esri, Maxar, Earthstar Geographics'
OSM_CREDIT = '© OpenStreetMap contributors'
STADIA = 'https://tiles.stadiamaps.com/tiles/%s/{z}/{x}/{y}{r}.png?api_key=%s'
STADIA_CREDIT = '© Stadia Maps © Stamen Design © OpenStreetMap contributors'

# Esri's export endpoint renders any bounding box as one image: used for small inset maps.
ESRI_DARK_EXPORT = ('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/'
                    'export?bbox=%.1f,%.1f,%.1f,%.1f&bboxSR=3857&imageSR=3857&size=%d,%d&format=png&f=image')


def _esri(sid, service, ext, credit, max_zoom=16):
    return TileSource(sid, ESRI_BASE % service, ext, credit, max_zoom=max_zoom, workers=4)


def layers(style, retina=False, key=''):
    """(background, labels or None) TileSources for a settings basemap index."""
    if style == 1:
        return (_esri('esri-light', 'Canvas/World_Light_Gray_Base', 'jpg', ESRI_CANVAS_CREDIT),
                _esri('esri-light-labels', 'Canvas/World_Light_Gray_Reference', 'png', ESRI_CANVAS_CREDIT))
    if style == 2:
        return (TileSource('osm', 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', 'png', OSM_CREDIT,
                           max_zoom=19, workers=2), None)
    if style == 3:
        return (_esri('esri', 'World_Imagery', 'jpg', ESRI_IMAGERY_CREDIT, 19),
                _esri('esri-labels', 'Reference/World_Boundaries_and_Places', 'png', 'Esri', 19))
    if style == 4 and key:
        return (TileSource('stadia-terrain', STADIA % ('stamen_terrain_background', key), 'png', STADIA_CREDIT,
                           max_zoom=18, workers=3, retina=retina),
                TileSource('stadia-labels', STADIA % ('stamen_terrain_labels', key), 'png', STADIA_CREDIT,
                           max_zoom=18, workers=3, retina=retina))
    return (_esri('esri-dark', 'Canvas/World_Dark_Gray_Base', 'jpg', ESRI_CANVAS_CREDIT),
            _esri('esri-dark-labels', 'Canvas/World_Dark_Gray_Reference', 'png', ESRI_CANVAS_CREDIT))


def is_light(style):
    return style in (1, 2)

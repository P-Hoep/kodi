"""The scene registry: panel builders, map scene specs, and each scene's availability rule.
No Kodi imports."""

from .. import config, geo
from ..sources import gibs
from . import airmarine, climatescenes, conditions, fishingscene, forecast, sky, textscenes

PANELS = {
    'current': conditions.current,
    'nexthours': conditions.nexthours,
    'hourly': forecast.hourly,
    'daily': forecast.daily,
    'climate': climatescenes.today_vs_normal,
    'year': climatescenes.year,
    'fishing': fishingscene.build,
    'sunmoon': sky.build,
    'air': airmarine.air,
    'marine': airmarine.marine,
    'discussion': textscenes.discussion,
    'ambient': textscenes.ambient,
}

TITLES = dict((sid, name) for sid, name, _show, _dur, _modes in config.SCENES)
TITLES.update({'local': 'Local radar', 'regional': 'Regional radar', 'national': 'National radar',
               'satellite': 'Satellite and radar', 'future': "What's coming", 'alert': 'Weather alert'})
NATIONAL_US = (38.6, -96.5, 5)


class MapSpec(object):
    def __init__(self, sid, view, past, future, future_step=None, fps_factor=1.0, warnings=False,
                 satellite=False, radar_alpha=None, allow_rainbow=True, past_step=300):
        self.id = sid
        self.view = view
        self.past = past
        self.future = future
        self.future_step = future_step
        self.fps_factor = fps_factor
        self.warnings = warnings
        self.satellite = satellite
        self.radar_alpha = radar_alpha
        self.allow_rainbow = allow_rainbow
        self.past_step = past_step


def map_specs(s, wind_from=None, zoom=None):
    """{scene id: MapSpec} for the enabled map scenes."""
    from .. import radar
    lat, lon = s['lat'], s['lon']
    z = int(zoom if zoom is not None else s['zoom'])
    past = config.PAST_MINUTES[s.get('past_minutes', 3)]
    future = config.FUTURE_HOURS[s.get('future_hours', 1)] * 60 if s.get('future_source', 0) != 4 else 0
    us = geo.inside(lat, lon, geo.IEM_NEXRAD)
    out = {}

    def centre(zoom_level):
        if s.get('center', 0) == 1 and wind_from is not None:
            v = geo.Viewport(lat, lon, zoom_level)
            return radar.upwind_center(lat, lon, wind_from, v.width * v.km_per_pixel())
        return lat, lon

    if s.get('scene_local', 1):
        c = centre(z)
        out['local'] = MapSpec('local', geo.Viewport(c[0], c[1], z), past, future)
    rz = max(3, z - s.get('regional_offset', 2))
    if s.get('scene_regional', 1) or s.get('scene_satellite', 0):
        c = centre(rz)
        rview = geo.Viewport(c[0], c[1], rz)
        if s.get('scene_regional', 1):
            out['regional'] = MapSpec('regional', rview, past, future, warnings=bool(s.get('warnings', True)) and us,
                                      allow_rainbow=False)
        if s.get('scene_satellite', 0):
            out['satellite'] = MapSpec('satellite', rview, past, 0, satellite=True, radar_alpha=60)
    if s.get('scene_national', 0):
        if us:
            view = geo.Viewport(NATIONAL_US[0], NATIONAL_US[1], NATIONAL_US[2])
        else:
            view = geo.Viewport(lat, lon, 5)
        out['national'] = MapSpec('national', view, min(past, 120), 0, fps_factor=0.6, past_step=600)
    if s.get('scene_future', 1) and s.get('future_source', 0) != 4:
        if s.get('scene_future', 1) == 1 or geo.inside(lat, lon, geo.HRRR):
            out['future'] = MapSpec('future', geo.Viewport(lat, lon, max(3, z - 1)), 0, 18 * 60, future_step=1800,
                                    allow_rainbow=False)
    return out


def available(sid, hub, s, now, feeds=None, alerts=None):
    """Can this scene be shown right now? Scenes without data are skipped silently."""
    mode = s.get('scene_' + sid, 0)
    if sid == 'alert':
        return bool(alerts)
    if sid in config.MAP_SCENES:
        feed = (feeds or {}).get(sid)
        if feed is None:
            return False
        if sid == 'satellite' and not gibs.GIBS().covers(s['lat'], s['lon']):
            return False
        return len(feed.ready) > 0
    if sid == 'sunmoon':
        return True
    if sid == 'ambient':
        return True
    fc = hub.get('forecast') if hub else None
    if sid in ('current', 'hourly', 'daily', 'fishing'):
        return bool(fc)
    if sid == 'nexthours':
        if not fc:
            return False
        return mode == 1 or conditions.precip_expected(fc, now)
    if sid in ('climate', 'year'):
        return bool(hub and hub.get('archive') and fc)
    if sid == 'air':
        return bool(hub and ((hub.get('air') or {}).get('current') or {}).get('us_aqi') is not None)
    if sid == 'marine':
        return bool(hub and (hub.get('tides') or {}).get('curve'))
    if sid == 'discussion':
        return bool(hub and hub.us and (hub.get('afd') or {}).get('points'))
    return False


def build_panel(sid, ctx, alerts=None):
    if sid == 'alert':
        return textscenes.alert(ctx, alerts)
    return PANELS[sid](ctx)

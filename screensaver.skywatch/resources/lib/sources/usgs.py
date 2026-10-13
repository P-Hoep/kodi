"""USGS Water Data OGC API (api.waterdata.usgs.gov, which replaces the legacy waterservices):
river gauge water temperature, flow and stage for the fishing scene. Keyless.

Parameter codes: 00010 water temperature °C, 00011 °F, 00060 discharge ft³/s, 00065 gage height ft.
"""

import time

from .. import net
from .base import parse_iso

API = 'https://api.waterdata.usgs.gov/ogcapi/v0/collections'
ATTRIBUTION = 'River data: USGS'


def _location_id(gauge):
    gauge = gauge.strip()
    return gauge if gauge.upper().startswith('USGS-') else 'USGS-' + gauge


def _time(stamp):
    return parse_iso(stamp[:19])   # stamps are UTC (+00:00)


def gauge(gauge_id):
    """{'name', 'lat', 'lon', 'water_c', 'flow_cfs', 'stage_ft', 't', 'water_series': [(t, °C)]}"""
    loc = _location_id(gauge_id)
    out = {'id': loc, 'name': loc, 'lat': None, 'lon': None}
    try:
        meta = net.fetch_json('%s/monitoring-locations/items/%s?f=json' % (API, loc), timeout=15)
        out['name'] = (meta.get('properties') or {}).get('monitoring_location_name') or loc
        coords = (meta.get('geometry') or {}).get('coordinates') or [None, None]
        out['lon'], out['lat'] = coords[0], coords[1]
    except net.HttpError:
        pass
    latest = net.fetch_json('%s/latest-continuous/items?f=json&monitoring_location_id=%s&limit=50' % (API, loc),
                            timeout=15)
    for f in latest.get('features') or []:
        p = f.get('properties') or {}
        try:
            value = float(p.get('value'))
        except (TypeError, ValueError):
            continue
        code = p.get('parameter_code')
        if code == '00010':
            out['water_c'] = value
        elif code == '00011' and 'water_c' not in out:
            out['water_c'] = (value - 32) * 5 / 9.0
        elif code == '00060':
            out['flow_cfs'] = value
        elif code == '00065':
            out['stage_ft'] = value
        out['t'] = max(out.get('t') or 0, _time(p.get('time') or '1970-01-01T00:00:00'))
    out['water_series'] = water_series(loc)
    return out


def water_series(loc, days=4):
    """Water temperature over the last few days as [(t, °C)], one sample an hour."""
    since = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - days * 86400))
    for code, to_c in (('00010', lambda v: v), ('00011', lambda v: (v - 32) * 5 / 9.0)):
        try:
            data = net.fetch_json('%s/continuous/items?f=json&monitoring_location_id=%s&parameter_code=%s'
                                  '&time=%s/..&limit=2000&properties=time,value' % (API, loc, code, since),
                                  timeout=20)
        except net.HttpError:
            continue
        rows = []
        last_hour = None
        for f in data.get('features') or []:
            p = f.get('properties') or {}
            try:
                t, v = _time(p['time']), float(p['value'])
            except (KeyError, TypeError, ValueError):
                continue
            if last_hour is None or t - last_hour >= 3600:
                rows.append((t, to_c(v)))
                last_hour = t
        if rows:
            return sorted(rows)
    return []

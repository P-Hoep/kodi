"""NOAA CO-OPS Tides & Currents: the nearest tide-prediction station, today's tide curve,
high and low times, and water temperature where the station measures it. Keyless."""

import calendar
import time

from .. import geo, net

STATIONS = 'https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions'
DATA = 'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter'
ATTRIBUTION = 'Tides: NOAA CO-OPS'
COASTAL_KM = 40.0


def stations():
    data = net.fetch_json(STATIONS, timeout=30)
    return [(s['id'], s.get('name') or s['id'], float(s['lat']), float(s['lng']))
            for s in data.get('stations') or [] if s.get('lat') is not None]


def nearest(all_stations, lat, lon, limit_km=COASTAL_KM):
    best = None
    for sid, name, slat, slon in all_stations:
        if abs(slat - lat) > 2 or abs(slon - lon) > 3:
            continue
        d = geo.haversine_km(lat, lon, slat, slon)
        if d <= limit_km and (best is None or d < best[0]):
            best = (d, sid, name, slat, slon)
    return best


def _get(station, product, extra):
    url = ('%s?product=%s&application=SkyWatch_Kodi&station=%s&time_zone=gmt&units=metric&format=json%s'
           % (DATA, product, station, extra))
    return net.fetch_json(url, timeout=15)


def _epoch(stamp):
    return calendar.timegm(time.strptime(stamp, '%Y-%m-%d %H:%M'))


def tides(station, start_epoch, hours=30):
    """{'curve': [(t, metres)], 'hilo': [(t, metres, 'H'|'L')]} from start_epoch (UTC)."""
    begin = time.strftime('%Y%m%d %H:%M', time.gmtime(start_epoch))
    common = '&datum=MLLW&begin_date=%s&range=%d' % (begin.replace(' ', '%20'), hours)
    curve = _get(station, 'predictions', common + '&interval=30')
    hilo = _get(station, 'predictions', common + '&interval=hilo')
    return {
        'curve': [(_epoch(p['t']), float(p['v'])) for p in curve.get('predictions') or []],
        'hilo': [(_epoch(p['t']), float(p['v']), p.get('type', '')) for p in hilo.get('predictions') or []],
    }


def water_temperature(station):
    """(°C, epoch) or None; many prediction-only stations have no sensor."""
    try:
        data = _get(station, 'water_temperature', '&date=recent')
    except net.HttpError:
        return None
    rows = [r for r in data.get('data') or [] if r.get('v') not in (None, '')]
    if not rows:
        return None
    return {'now': float(rows[-1]['v']), 't': _epoch(rows[-1]['t']),
            'series': [(_epoch(r['t']), float(r['v'])) for r in rows[::10]]}

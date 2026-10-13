"""US National Weather Service API (api.weather.gov): point metadata, alerts, the text
forecast and the Area Forecast Discussion. Keyless; the User-Agent carries a contact email."""

import re

from .. import net
from .base import parse_iso

API = 'https://api.weather.gov'
HEADERS = {'Accept': 'application/geo+json'}
ATTRIBUTION = 'Alerts and forecasts: NWS'

# Official NWS hazard colours (weather.gov/help-map) for the common products.
COLORS = {
    'Tornado Warning': 'FFFF0000', 'Severe Thunderstorm Warning': 'FFFFA500',
    'Flash Flood Warning': 'FF8B0000', 'Flood Warning': 'FF00FF00', 'Special Marine Warning': 'FFFFA500',
    'Extreme Wind Warning': 'FFFF8C00', 'Snow Squall Warning': 'FFC71585', 'Dust Storm Warning': 'FFFFE4C4',
    'Winter Storm Warning': 'FFFF69B4', 'Blizzard Warning': 'FFFF4500', 'Ice Storm Warning': 'FF8B008B',
    'High Wind Warning': 'FFDAA520', 'Hurricane Warning': 'FFDC143C', 'Tropical Storm Warning': 'FFB22222',
    'Storm Surge Warning': 'FFB524F7', 'Excessive Heat Warning': 'FFC71585', 'Red Flag Warning': 'FFFF1493',
    'Tornado Watch': 'FFFFFF00', 'Severe Thunderstorm Watch': 'FFDB7093', 'Flood Advisory': 'FF00FF7F',
}
DEFAULT_WARNING = 'FFFF5252'


def color(event):
    return COLORS.get(event, DEFAULT_WARNING if 'Warning' in event else 'FFFFC107')


def level(event):
    """3 warning, 2 watch, 1 advisory/statement, 0 other."""
    if 'Warning' in event or 'Emergency' in event:
        return 3
    if 'Watch' in event:
        return 2
    if 'Advisory' in event or 'Statement' in event:
        return 1
    return 0


def point(lat, lon):
    data = net.fetch_json('%s/points/%.4f,%.4f' % (API, lat, lon), headers=HEADERS)
    p = data.get('properties') or {}
    rel = (p.get('relativeLocation') or {}).get('properties') or {}
    return {'cwa': p.get('cwa'), 'forecast': p.get('forecast'), 'county': p.get('county'),
            'zone': p.get('forecastZone'), 'city': rel.get('city'), 'state': rel.get('state')}


def _alert(feature):
    p = feature.get('properties') or {}
    ends = p.get('ends') or p.get('expires')
    return {
        'id': p.get('id') or feature.get('id'), 'event': p.get('event') or 'Alert',
        'headline': p.get('headline') or '', 'severity': p.get('severity'),
        'description': (p.get('description') or '').strip(), 'instruction': (p.get('instruction') or '').strip(),
        'area': p.get('areaDesc') or '', 'ends': parse_iso(ends[:19]) - _offset(ends) if ends else None,
        'level': level(p.get('event') or ''), 'color': color(p.get('event') or ''),
    }


def _offset(stamp):
    """UTC offset in seconds of an ISO stamp such as 2026-10-12T19:00:00-05:00."""
    m = re.search(r'([+-])(\d\d):(\d\d)$', stamp or '')
    if not m:
        return 0
    sign = 1 if m.group(1) == '+' else -1
    return sign * (int(m.group(2)) * 3600 + int(m.group(3)) * 60)


def alerts_for_point(lat, lon):
    data = net.fetch_json('%s/alerts/active?point=%.4f,%.4f' % (API, lat, lon), headers=HEADERS)
    out = [_alert(f) for f in data.get('features') or []]
    out.sort(key=lambda a: -a['level'])
    return out


def warning_polygons(bbox):
    """Active warnings with polygons inside bbox (south, west, north, east):
    [{'event', 'color', 'rings': [[(lon, lat), ...]]}]."""
    s, w, n, e = bbox
    data = net.fetch_json('%s/alerts/active?status=actual&message_type=alert,update' % API, headers=HEADERS,
                          timeout=20)
    out = []
    for f in data.get('features') or []:
        geom = f.get('geometry')
        p = f.get('properties') or {}
        event = p.get('event') or ''
        if not geom or 'Warning' not in event:
            continue
        polys = geom['coordinates'] if geom.get('type') == 'MultiPolygon' else [geom.get('coordinates') or []]
        rings = []
        for poly in polys:
            for ring in poly[:1]:
                if any(s <= lat <= n and w <= lon <= e for lon, lat in ring):
                    rings.append([(lon, lat) for lon, lat in ring])
        if rings:
            out.append({'event': event, 'color': color(event), 'rings': rings})
    return out


def forecast_periods(url):
    data = net.fetch_json(url, headers=HEADERS)
    out = []
    for p in (data.get('properties') or {}).get('periods') or []:
        start = p.get('startTime') or ''
        out.append({'name': p.get('name'), 'day': p.get('isDaytime'), 'short': p.get('shortForecast'),
                    'detailed': p.get('detailedForecast'), 'date': start[:10],
                    'start': parse_iso(start[:19]) - _offset(start) if start else None})
    return out


def discussion(cwa):
    """The newest Area Forecast Discussion: {'issued', 'office', 'points': [str], 'text'}."""
    listing = net.fetch_json('%s/products/types/AFD/locations/%s' % (API, cwa), headers=HEADERS)
    items = listing.get('@graph') or []
    if not items:
        return None
    product = net.fetch_json('%s/products/%s' % (API, items[0]['id']), headers=HEADERS)
    text = product.get('productText') or ''
    issued = product.get('issuanceTime') or ''
    return {'issued': parse_iso(issued[:19]) - _offset(issued) if issued else None, 'office': cwa,
            'points': key_points(text), 'text': text}


def key_points(text):
    """The .KEY MESSAGES bullets of an AFD, or the first paragraphs of its short-term
    section when there are none. Line-wrapped text is joined into sentences."""
    sections = re.split(r'\n(?=\.[A-Z][A-Z /]+\.\.\.)', text)
    chosen = None
    for name in ('.KEY MESSAGES', '.SYNOPSIS', '.SHORT TERM', '.DISCUSSION', '.UPDATE'):
        for sec in sections:
            if sec.strip().startswith(name):
                chosen = sec
                break
        if chosen:
            break
    if not chosen:
        return []
    body = chosen.split('...', 1)[1] if '...' in chosen else chosen
    body = body.split('&&')[0]
    body = re.sub(r'^.*?(?:Issued at|Updated at)[^\n]*\n', '', body, count=1, flags=re.S | re.I)
    # Bullets start with '-' or a number; otherwise split into paragraphs.
    chunks = re.split(r'\n\s*(?:-|\d+[.)])\s+|\n\s*\n', body)
    points = []
    for c in chunks:
        c = re.sub(r'\s+', ' ', c).strip(' -')
        if len(c) > 25:
            points.append(c[0].upper() + c[1:].lower() if c.isupper() else c)
    return points[:6]

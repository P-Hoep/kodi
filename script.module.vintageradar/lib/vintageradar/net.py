"""Small HTTP helper on urllib: identifying User-Agent, gzip, timeouts, CA bundle."""

import gzip
import ssl

from urllib.parse import quote
from urllib.request import Request, urlopen

USER_AGENT = 'VintageRadar-Kodi/1.0 (Kodi add-on script.vintageradar)'


def _ssl_context():
    # Kodi's Python on Android often lacks a system CA store; use certifi when present.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_CONTEXT = _ssl_context()


class HttpError(Exception):
    pass


def fetch(url, timeout=15, headers=None, max_bytes=32 * 1024 * 1024):
    request = Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'gzip'})
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        response = urlopen(request, timeout=timeout, context=_CONTEXT)
    except Exception as error:
        raise HttpError('%s: %s' % (url.split('?')[0], error))
    try:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise HttpError('%s: response too large' % url.split('?')[0])
        if response.headers.get('Content-Encoding', '').lower() == 'gzip':
            body = gzip.decompress(body)
        return body
    finally:
        response.close()


def fetch_json(url, timeout=15, headers=None):
    import json
    body = fetch(url, timeout=timeout, headers=headers)
    try:
        return json.loads(body.decode('utf-8'))
    except ValueError as error:
        raise HttpError('%s: bad JSON (%s)' % (url.split('?')[0], error))


def search_places(query, near=None, limit=10):
    """Photon (komoot) keyless geocoder: [(label, lat, lon)]."""
    url = 'https://photon.komoot.io/api/?' + 'q=%s&limit=%d' % (quote(query), limit)
    if near:
        url += '&lat=%.4f&lon=%.4f' % near
    out = []
    for feature in fetch_json(url).get('features') or []:
        props = feature.get('properties') or {}
        coords = (feature.get('geometry') or {}).get('coordinates') or []
        if len(coords) < 2:
            continue
        parts = [props.get('name'), props.get('city'), props.get('state'), props.get('country')]
        seen = []
        for part in parts:
            if part and part not in seen:
                seen.append(part)
        out.append((', '.join(seen) or query, coords[1], coords[0]))
    return out

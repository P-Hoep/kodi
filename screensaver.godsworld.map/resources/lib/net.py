"""Small HTTP helpers on urllib: identifying User-Agent, gzip, timeouts, CA bundle."""

import gzip
import json
import ssl

from urllib.request import Request, urlopen

USER_AGENT = 'GodsWorldMap-Kodi/0.1 (Kodi screensaver screensaver.godsworld.map)'


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
    body = fetch(url, timeout=timeout, headers=headers)
    try:
        return json.loads(body.decode('utf-8'))
    except ValueError as error:
        raise HttpError('%s: bad JSON (%s)' % (url.split('?')[0], error))

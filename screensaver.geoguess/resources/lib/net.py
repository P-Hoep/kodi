"""Small HTTP helpers on urllib: identifying User-Agent, gzip, timeouts, CA bundle.
No Kodi imports."""

import gzip
import json
import ssl
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .config import TIMEOUT, USER_AGENT


def _ssl_context():
    # Kodi's Python on Android often lacks a system CA store; use certifi when present.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_CONTEXT = _ssl_context()


class HttpError(Exception):
    """status is the HTTP code (0 for a connection failure), kind is 'http' or 'network'."""

    def __init__(self, message, status=0, kind='network'):
        Exception.__init__(self, message)
        self.status = status
        self.kind = kind

    @property
    def retryable(self):
        return self.kind == 'network' or self.status == 429 or self.status >= 500


def short(url):
    return url.split('?')[0]


def fetch(url, timeout=TIMEOUT, headers=None, max_bytes=32 * 1024 * 1024):
    request = Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'gzip'})
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        response = urlopen(request, timeout=timeout, context=_CONTEXT)
    except HTTPError as error:
        raise HttpError('%s: HTTP %s' % (short(url), error.code), error.code, 'http')
    except Exception as error:
        raise HttpError('%s: %s' % (short(url), error))
    try:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise HttpError('%s: response too large' % short(url), 0, 'http')
        if response.headers.get('Content-Encoding', '').lower() == 'gzip':
            body = gzip.decompress(body)
        return body
    except HttpError:
        raise
    except Exception as error:
        raise HttpError('%s: %s' % (short(url), error))
    finally:
        response.close()


def fetch_json(url, timeout=TIMEOUT, headers=None):
    body = fetch(url, timeout=timeout, headers=headers)
    try:
        return json.loads(body.decode('utf-8'))
    except ValueError as error:
        raise HttpError('%s: bad JSON (%s)' % (short(url), error), 0, 'http')


def fetch_image(url, timeout=TIMEOUT, max_bytes=24 * 1024 * 1024):
    """Image bytes; a signed URL that has expired answers with a JSON or HTML body, so the
    signature is checked rather than trusted."""
    body = fetch(url, timeout=timeout, max_bytes=max_bytes)
    if not (body.startswith(b'\x89PNG') or body.startswith(b'\xff\xd8')):
        raise HttpError('%s: not an image (%s)' % (short(url), body[:80].decode('latin-1', 'replace').strip()),
                        0, 'http')
    return body

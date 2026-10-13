"""Small HTTP helpers on urllib: identifying User-Agent, gzip, 10 s timeouts, CA bundle.
No Kodi imports."""

import gzip
import json
import ssl
from urllib.error import HTTPError
from urllib.request import Request, urlopen

VERSION = '1.0.0'
_contact = ['']


def set_contact(email):
    """NWS asks every client to identify itself with a contact address."""
    _contact[0] = (email or '').strip()


def user_agent():
    contact = _contact[0] or 'github.com/P-Hoep/kodi'
    return 'SkyWatch-Kodi/%s (%s)' % (VERSION, contact)


def _ssl_context():
    # Kodi's Python on Android often lacks a system CA store; use certifi when present.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_CONTEXT = _ssl_context()


class HttpError(Exception):
    def __init__(self, message, status=None):
        Exception.__init__(self, message)
        self.status = status


def short(url):
    return url.split('?')[0]


def fetch(url, timeout=10, headers=None, max_bytes=32 * 1024 * 1024):
    request = Request(url, headers={'User-Agent': user_agent(), 'Accept-Encoding': 'gzip'})
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        response = urlopen(request, timeout=timeout, context=_CONTEXT)
    except HTTPError as error:
        raise HttpError('%s: HTTP %s' % (short(url), error.code), error.code)
    except Exception as error:
        raise HttpError('%s: %s' % (short(url), error))
    try:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise HttpError('%s: response too large' % short(url))
        if response.headers.get('Content-Encoding', '').lower() == 'gzip':
            body = gzip.decompress(body)
        return body
    except HttpError:
        raise
    except Exception as error:
        raise HttpError('%s: %s' % (short(url), error))
    finally:
        response.close()


def fetch_json(url, timeout=10, headers=None):
    body = fetch(url, timeout=timeout, headers=headers)
    try:
        return json.loads(body.decode('utf-8'))
    except ValueError as error:
        raise HttpError('%s: bad JSON (%s)' % (short(url), error))


def fetch_image(url, timeout=10, max_bytes=16 * 1024 * 1024):
    """Image bytes; a WMS error comes back as XML with HTTP 200, so check the signature."""
    body = fetch(url, timeout=timeout, max_bytes=max_bytes)
    if not (body.startswith(b'\x89PNG') or body.startswith(b'\xff\xd8')):
        raise HttpError('%s: not an image (%s)' % (short(url), body[:80].decode('latin-1', 'replace').strip()))
    return body

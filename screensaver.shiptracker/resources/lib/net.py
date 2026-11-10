"""Small HTTP helpers on urllib: a certifi CA bundle when Kodi has none, JSON and byte fetches,
and errors sorted into "the server answered badly" and "could not reach it". No Kodi imports.
"""

import json
import socket
import ssl
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError

from . import config

USER_AGENT = config.USER_AGENT


def _ssl_context():
    # Kodi's Python on Android often lacks a system CA store; use certifi when present.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_CONTEXT = _ssl_context()


def short(url):
    return url.split('?')[0]


def _kind(error):
    reason = getattr(error, 'reason', error)
    if isinstance(reason, ssl.SSLCertVerificationError) or \
            'CERTIFICATE_VERIFY_FAILED' in str(reason):
        return 'cert'
    if isinstance(reason, ssl.SSLError):
        return 'http'
    if isinstance(reason, (socket.timeout, TimeoutError)) or 'timed out' in str(reason):
        return 'network'
    if isinstance(reason, ConnectionRefusedError):
        return 'http'
    return 'network'


class HttpError(Exception):
    """kind: 'http' (a bad status or body), 'cert' (TLS did not verify) or 'network'."""

    def __init__(self, message, kind='network', status=None):
        Exception.__init__(self, message)
        self.kind = kind
        self.status = status


class RateLimited(Exception):
    def __init__(self, wait):
        Exception.__init__(self, 'rate limited, wait %.0fs' % wait)
        self.wait = wait


def retry_after(headers):
    try:
        return min(float(headers.get('Retry-After')), 300.0)
    except (TypeError, ValueError, AttributeError):
        return 60.0


def fetch(url, timeout=config.HTTP_TIMEOUT, headers=None, max_bytes=16 * 1024 * 1024):
    """GET url -> bytes. Raises HttpError or RateLimited (HTTP 429/503)."""
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT,
                                                   'Accept-Encoding': 'identity'})
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        response = urllib.request.urlopen(request, timeout=timeout, context=_CONTEXT)
    except HTTPError as error:
        if error.code in (429, 503):
            raise RateLimited(retry_after(error.headers or {}))
        raise HttpError('%s: HTTP %s' % (short(url), error.code), 'http', error.code)
    except URLError as error:
        raise HttpError('%s: %s' % (short(url), error.reason), _kind(error))
    except Exception as error:
        raise HttpError('%s: %s' % (short(url), error), _kind(error))
    try:
        body = response.read(max_bytes + 1)
    except Exception as error:
        raise HttpError('%s: %s' % (short(url), error), _kind(error))
    if len(body) > max_bytes:
        raise HttpError('%s: response too large' % short(url), 'http')
    return body


def get_json(base, params, timeout=config.HTTP_TIMEOUT):
    url = base + '?' + urllib.parse.urlencode(params)
    try:
        return json.loads(fetch(url, timeout=timeout,
                                headers={'Accept': 'application/json'}).decode('utf-8'))
    except ValueError as error:
        raise HttpError('%s: bad JSON (%s)' % (short(url), error), 'http')

"""Small HTTP helpers on urllib: identifying User-Agent, gzip, ETags, CA bundle, and errors
sorted into "the server answered badly" and "could not reach it". No Kodi imports."""

import gzip
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import config

USER_AGENT = '%s/%s (Kodi screensaver; +https://github.com/P-Hoep/kodi)' % (config.ADDON_ID, config.VERSION)


def _ssl_context():
    # Kodi's Python on Android often lacks a system CA store; use certifi when present.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_CONTEXT = _ssl_context()
_INSECURE = ssl.create_default_context()
_INSECURE.check_hostname = False
_INSECURE.verify_mode = ssl.CERT_NONE


class HttpError(Exception):
    """kind: 'http' (an HTTP error status or a bad body: the resource's fault), 'cert' (the
    TLS certificate did not verify), or 'network' (DNS, refused, timeout: maybe our side)."""

    def __init__(self, message, kind='network', status=None):
        Exception.__init__(self, message)
        self.kind = kind
        self.status = status


def short(url):
    return url.split('?')[0]


def _kind(error):
    reason = getattr(error, 'reason', error)
    if isinstance(reason, ssl.SSLCertVerificationError) or 'CERTIFICATE_VERIFY_FAILED' in str(reason):
        return 'cert'
    if isinstance(reason, ssl.SSLError):
        return 'http'
    if isinstance(reason, (socket.timeout, TimeoutError)) or 'timed out' in str(reason):
        return 'network'
    if isinstance(reason, ConnectionRefusedError):
        return 'http'      # the host is up and answered: the camera server is down
    return 'network'


class Response(object):
    def __init__(self, status, body, headers, url):
        self.status, self.body, self.headers, self.url = status, body, headers, url


def fetch(url, timeout=10, headers=None, max_bytes=64 * 1024 * 1024, verify=True):
    """GET url -> Response (status 304 has an empty body). Raises HttpError."""
    request = Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'gzip'})
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        response = urlopen(request, timeout=timeout, context=_CONTEXT if verify else _INSECURE)
    except HTTPError as error:
        if error.code == 304:
            return Response(304, b'', error.headers, url)
        raise HttpError('%s: HTTP %s' % (short(url), error.code), 'http', error.code)
    except URLError as error:
        raise HttpError('%s: %s' % (short(url), error.reason), _kind(error))
    except Exception as error:
        raise HttpError('%s: %s' % (short(url), error), _kind(error))
    try:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise HttpError('%s: response too large' % short(url), 'http')
        if (response.headers.get('Content-Encoding') or '').lower() == 'gzip':
            body = gzip.decompress(body)
        return Response(response.status, body, response.headers, response.geturl())
    except HttpError:
        raise
    except Exception as error:
        raise HttpError('%s: %s' % (short(url), error), _kind(error))
    finally:
        response.close()

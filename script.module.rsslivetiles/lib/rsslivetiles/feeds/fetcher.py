"""HTTP for feeds: one GET with gzip, a timeout, a 5 MB cap, a custom User-Agent and
conditional requests (ETag / Last-Modified). Plain urllib (no requests module needed);
certifi's CA bundle is used when Kodi has it, which matters on Android.
"""

import gzip
import ssl
import time
import urllib.error
import urllib.request
import zlib

from .. import USER_AGENT

MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = 10
ACCEPT = 'application/rss+xml, application/atom+xml, application/rdf+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5'


class FetchError(Exception):
    """kind: 'network', 'http', 'too_big'. code: the HTTP status for 'http'."""

    def __init__(self, kind, detail='', code=0):
        Exception.__init__(self, '%s: %s' % (kind, detail) if detail else kind)
        self.kind = kind
        self.detail = detail
        self.code = code


class Response(object):
    def __init__(self, status, body=b'', content_type='', etag='', last_modified='', url=''):
        self.status = status            # 200, or 304 Not Modified
        self.body = body
        self.content_type = content_type
        self.etag = etag
        self.last_modified = last_modified
        self.url = url


_context = []


def ssl_context():
    if not _context:
        ctx = None
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            try:
                ctx = ssl.create_default_context()
            except Exception:
                ctx = None
        _context.append(ctx)
    return _context[0]


def _read_capped(response, limit):
    chunks, total = [], 0
    while True:
        chunk = response.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise FetchError('too_big', 'more than %d MB' % (limit // (1024 * 1024)))
        chunks.append(chunk)
    return b''.join(chunks)


def _decompress(body, encoding):
    encoding = (encoding or '').lower()
    try:
        if encoding == 'gzip' or body[:2] == b'\x1f\x8b':
            return gzip.decompress(body)
        if encoding == 'deflate':
            try:
                return zlib.decompress(body)
            except zlib.error:
                return zlib.decompress(body, -zlib.MAX_WBITS)
    except (OSError, zlib.error, EOFError) as err:
        raise FetchError('network', 'bad compressed data: %s' % err)
    return body


def get(url, etag='', last_modified='', timeout=TIMEOUT, limit=MAX_BYTES, accept=ACCEPT, log=None):
    """GET url -> Response. Raises FetchError."""
    started = time.time()
    headers = {'User-Agent': USER_AGENT, 'Accept': accept, 'Accept-Encoding': 'gzip, deflate'}
    if etag:
        headers['If-None-Match'] = etag
    if last_modified:
        headers['If-Modified-Since'] = last_modified
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=timeout, context=ssl_context())
        try:
            raw = _read_capped(response, limit)
            hdr = response.headers
            body = _decompress(raw, hdr.get('Content-Encoding'))
            if len(body) > limit:
                raise FetchError('too_big', 'more than %d MB' % (limit // (1024 * 1024)))
            result = Response(response.status, body, hdr.get('Content-Type', '') or '', hdr.get('ETag', '') or '',
                              hdr.get('Last-Modified', '') or '', response.geturl() or url)
        finally:
            response.close()
    except urllib.error.HTTPError as err:
        if err.code == 304:
            return Response(304, url=url, etag=etag, last_modified=last_modified)
        raise FetchError('http', 'HTTP %d' % err.code, err.code)
    except FetchError:
        raise
    except (urllib.error.URLError, OSError, ValueError, ssl.SSLError) as err:
        raise FetchError('network', str(getattr(err, 'reason', err)))
    if log:
        log('GET %s -> %d, %d bytes, %.2f s' % (url, result.status, len(result.body), time.time() - started))
    return result

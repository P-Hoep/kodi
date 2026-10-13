"""Audiobookshelf REST client on urllib. No Kodi imports.

Every endpoint used here was checked against a 2.28.0 server (see docs/audiobookshelf.md,
"API used"). Requests carry "Authorization: Bearer <token>", where the token is an API key
or a signed-in access token (auth.py); it never appears in URLs, exceptions or log lines.
"""

import base64
import gzip
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

VERSION = '1.1.0'

# What Kodi's own player decodes. Sent with forceDirectPlay so the server hands back the
# original files rather than starting an HLS transcode.
SUPPORTED_MIME_TYPES = ['audio/mpeg', 'audio/mp4', 'audio/x-m4b', 'audio/x-m4a', 'audio/aac', 'audio/flac',
                        'audio/x-flac', 'audio/ogg', 'audio/opus', 'audio/webm', 'audio/wav', 'audio/x-wav',
                        'audio/x-ms-wma', 'audio/x-aiff']


def _ssl_context():
    # Kodi's Python on Android often lacks a system CA store; use certifi when present.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_CONTEXT = None


class ApiError(Exception):
    """Unexpected status or response. .status is the HTTP status, if there was one."""

    def __init__(self, message, status=None):
        Exception.__init__(self, message)
        self.status = status


class NotConfigured(ApiError):
    pass


class Unreachable(ApiError):
    """No answer: DNS, refused connection, timeout, TLS failure."""


class AuthError(ApiError):
    """401/403: the key is wrong, revoked or expired."""


class NotFound(ApiError):
    pass


def b64(text):
    """Library filters take base64 ids: filter=series.<b64(id)>."""
    return base64.b64encode(text.encode('utf-8')).decode('ascii')


class Client(object):
    def __init__(self, server, auth, timeout=15):
        """auth: an auth.Login or auth.ApiKey, or a plain API key string."""
        from .auth import ApiKey
        self.server = (server or '').rstrip('/')
        self.auth = ApiKey(auth) if isinstance(auth, str) or auth is None else auth
        self.timeout = timeout

    def configured(self):
        return bool(self.server and self.auth.configured())

    # -- transport -----------------------------------------------------------------

    def token(self, force=False, min_valid=0):
        return self.auth.token(self, force=force, min_valid=min_valid)

    def auth_header(self, min_valid=0):
        return 'Bearer ' + self.token(min_valid=min_valid)

    def request(self, method, path, params=None, body=None, auth=True, headers=None):
        if not self.server or (auth and not self.auth.configured()):
            raise NotConfigured('The server address or sign-in details are not set')
        try:
            return self._request(method, path, params, body, self.token() if auth else None, headers)
        except AuthError:
            if not auth or not hasattr(self.auth, 'forget'):
                raise
            # A signed-in token can be revoked or expire early: get a new one, once.
            return self._request(method, path, params, body, self.token(force=True), headers)

    def _request(self, method, path, params, body, token, headers):
        global _CONTEXT
        url = self.server + path
        if params:
            url += '?' + urlencode([(k, v) for k, v in params.items() if v is not None])
        data = json.dumps(body).encode('utf-8') if body is not None else None
        req = Request(url, data=data, method=method)
        req.add_header('User-Agent', 'Kodi-Audiobookshelf/%s' % VERSION)
        req.add_header('Accept', 'application/json')
        req.add_header('Accept-Encoding', 'gzip')
        if data is not None:
            req.add_header('Content-Type', 'application/json')
        if token:
            req.add_header('Authorization', 'Bearer ' + token)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        if _CONTEXT is None and url.startswith('https'):
            _CONTEXT = _ssl_context()
        try:
            response = urlopen(req, timeout=self.timeout, context=_CONTEXT if url.startswith('https') else None)
        except HTTPError as error:
            error.close()
            if error.code in (401, 403):
                raise AuthError('%s %s: HTTP %d' % (method, path, error.code), error.code)
            if error.code == 404:
                raise NotFound('%s %s: not found' % (method, path), 404)
            raise ApiError('%s %s: HTTP %d' % (method, path, error.code), error.code)
        except (URLError, OSError, ValueError) as error:
            reason = getattr(error, 'reason', error)
            raise Unreachable('%s: %s' % (self.server, reason))
        try:
            raw = response.read()
            if response.headers.get('Content-Encoding', '').lower() == 'gzip':
                raw = gzip.decompress(raw)
        except Exception as error:
            raise Unreachable('%s %s: connection lost (%s)' % (method, path, error))
        finally:
            response.close()
        text = raw.decode('utf-8', 'replace')
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except ValueError:
            if text.strip() == 'OK':  # session sync/close answer plain text
                return 'OK'
            raise ApiError('%s %s: the answer was not JSON' % (method, path))

    def get(self, path, **params):
        return self.request('GET', path, params)

    # -- server and user -----------------------------------------------------------

    def status(self):
        """Unauthenticated: confirms an Audiobookshelf server is listening there."""
        data = self.request('GET', '/status', auth=False)
        if not isinstance(data, dict) or data.get('app') != 'audiobookshelf':
            raise ApiError('%s does not look like an Audiobookshelf server' % self.server)
        return data

    def login(self, username, password):
        """POST /login; the user dict carries accessToken and refreshToken."""
        try:
            data = self.request('POST', '/login', body={'username': username, 'password': password}, auth=False,
                                headers={'x-return-tokens': 'true'})
        except AuthError:
            raise AuthError('Wrong username or password', 401)
        return expect(expect(data, dict, 'sign-in').get('user'), dict, 'sign-in')

    def refresh(self, refresh_token):
        data = self.request('POST', '/auth/refresh', auth=False, headers={'x-refresh-token': refresh_token})
        return expect(expect(data, dict, 'token refresh').get('user'), dict, 'token refresh')

    def me(self):
        return expect(self.get('/api/me'), dict, 'user')

    def libraries(self):
        data = expect(self.get('/api/libraries'), dict, 'library list')
        return [lib for lib in data.get('libraries') or [] if lib.get('mediaType') == 'book']

    # -- browsing ------------------------------------------------------------------

    def items(self, library_id, page=0, limit=50, sort='media.metadata.title', desc=False, filter=None,
              minified=True):
        """One page of books: {'results': [...], 'total': n}."""
        data = self.get('/api/libraries/%s/items' % quote(library_id), page=page, limit=limit, sort=sort,
                        desc=1 if desc else 0, filter=filter, minified=1 if minified else 0)
        return expect(data, dict, 'library items')

    def items_in_progress(self, limit=50):
        data = expect(self.get('/api/me/items-in-progress', limit=limit), dict, 'items in progress')
        return data.get('libraryItems') or []

    def series(self, library_id, page=0, limit=50):
        data = self.get('/api/libraries/%s/series' % quote(library_id), page=page, limit=limit, sort='name')
        return expect(data, dict, 'series')

    def authors(self, library_id):
        return expect(self.get('/api/libraries/%s/authors' % quote(library_id)), dict, 'authors').get('authors') or []

    def search(self, library_id, query, limit=25):
        data = self.get('/api/libraries/%s/search' % quote(library_id), q=query, limit=limit)
        return expect(data, dict, 'search results')

    def filter_data(self, library_id):
        """Genres, tags, narrators... used in the library: {'genres': [names], ...}."""
        return expect(self.get('/api/libraries/%s/filterdata' % quote(library_id)), dict, 'filter data')

    def item(self, item_id):
        data = self.get('/api/items/%s' % quote(item_id), expanded=1, include='progress')
        return expect(data, dict, 'book')

    def progress(self, item_id):
        """The user's progress for a book, or None if never started."""
        try:
            return expect(self.get('/api/me/progress/%s' % quote(item_id)), dict, 'progress')
        except NotFound:
            return None

    # -- playback and progress -----------------------------------------------------

    def start_session(self, item_id, device):
        """POST /api/items/:id/play: a playback session whose audioTracks carry contentUrl
        paths to the original files, and whose currentTime is the saved position."""
        body = {'deviceInfo': device, 'forceDirectPlay': True, 'forceTranscode': False,
                'supportedMimeTypes': SUPPORTED_MIME_TYPES, 'mediaPlayer': 'kodi'}
        return expect(self.request('POST', '/api/items/%s/play' % quote(item_id), body=body), dict, 'session')

    def sync_session(self, session_id, current_time, time_listened, duration):
        return self.request('POST', '/api/session/%s/sync' % quote(session_id),
                            body={'currentTime': current_time, 'timeListened': time_listened,
                                  'duration': duration})

    def close_session(self, session_id, current_time, time_listened, duration):
        return self.request('POST', '/api/session/%s/close' % quote(session_id),
                            body={'currentTime': current_time, 'timeListened': time_listened,
                                  'duration': duration})

    def update_progress(self, item_id, current_time, duration):
        """PATCH /api/me/progress/:id: the fallback when a session has gone (server restart,
        expiry). Sends only the position; the server decides whether the book is finished."""
        body = {'currentTime': current_time, 'duration': duration,
                'progress': min(1.0, current_time / duration) if duration else 0}
        return self.request('PATCH', '/api/me/progress/%s' % quote(item_id), body=body)

    # -- URLs for Kodi -------------------------------------------------------------

    def cover_url(self, item_id, updated_at=None, width=600):
        """Covers are served without authentication; JPEG because WebP support varies."""
        url = '%s/api/items/%s/cover?width=%d&format=jpeg' % (self.server, quote(item_id), width)
        return url + ('&ts=%s' % updated_at if updated_at else '')

    def author_image_url(self, author_id, updated_at=None, width=400):
        url = '%s/api/authors/%s/image?width=%d&format=jpeg' % (self.server, quote(author_id), width)
        return url + ('&ts=%s' % updated_at if updated_at else '')

    def stream_url(self, content_url, min_valid=0):
        """A track's file URL in Kodi's 'url|Header=value' form, so the token travels as a
        header (files need authentication; HTTP Range requests work). Kodi keeps this URL
        for the whole playlist, so playback asks for a token that lasts (min_valid)."""
        return '%s%s|Authorization=%s' % (self.server, content_url, quote(self.auth_header(min_valid)))


def expect(data, kind, what):
    if not isinstance(data, kind):
        raise ApiError('Unexpected answer from the server for %s' % what)
    return data

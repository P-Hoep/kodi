"""Signing in with a username and password, or with an API key. No Kodi imports.

Username and password (checked against a 2.28.0 server):
  POST /login {username, password} with "x-return-tokens: true" returns user.accessToken
  (a JWT valid 12 hours) and user.refreshToken (valid 7 days). POST /auth/refresh with
  "x-refresh-token: <refresh>" returns a new pair; the old refresh token stops working
  at once, so the new pair is saved straight away. A wrong password is HTTP 401.

Tokens live in tokens.json in the add-on's profile folder, not in the settings. When the
refresh token has expired (a week without Kodi) or another process already used it, the
add-on signs in again with the stored username and password, so the user never has to.
The legacy non-expiring user.token is deliberately not used: the server has deprecated it.
"""

import base64
import json
import os
import time

REFRESH_MARGIN = 600  # refresh an access token this many seconds before it expires


def jwt_expiry(token):
    """The 'exp' claim of a JWT (seconds), or None. The signature isn't checked: the
    server does that; this only decides when to ask for a new token."""
    try:
        payload = token.split('.')[1]
        data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)).decode('utf-8'))
        return float(data['exp']) if data.get('exp') else None
    except Exception:
        return None


class ApiKey(object):
    """A fixed API key (Audiobookshelf: Settings > API Keys)."""

    def __init__(self, key):
        self.key = key or ''

    def configured(self):
        return bool(self.key)

    def token(self, client, force=False, min_valid=0):
        return self.key

    def secrets(self):
        return [self.key]


class Login(object):
    """Username and password, with access and refresh tokens cached on disk."""

    def __init__(self, username, password, path):
        self.username = username or ''
        self.password = password or ''
        self.path = path

    def configured(self):
        return bool(self.username)

    def secrets(self):
        saved = self._load()
        return [self.password, saved.get('access', ''), saved.get('refresh', '')]

    def _load(self):
        try:
            with open(self.path) as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, client, user):
        access, refresh = user.get('accessToken'), user.get('refreshToken')
        if not access or not refresh:
            from .api import ApiError
            raise ApiError('The server did not return sign-in tokens (Audiobookshelf 2.26 or later is needed)')
        data = {'server': client.server, 'username': self.username, 'access': access, 'refresh': refresh,
                'expires': jwt_expiry(access) or time.time() + 3600}
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as handle:
            json.dump(data, handle)
        os.replace(tmp, self.path)
        return access

    def forget(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def token(self, client, force=False, min_valid=0):
        """A valid access token: the saved one, a refreshed one, or a fresh sign-in.
        force: the server just rejected the saved token. min_valid: seconds it must last
        (playback puts the token into stream URLs that can't be changed later)."""
        from .api import AuthError, Unreachable
        saved = self._load()
        if saved.get('server') != client.server or saved.get('username') != self.username:
            saved = {}
        if saved.get('access') and not force and \
                saved.get('expires', 0) - time.time() > max(REFRESH_MARGIN, min_valid):
            return saved['access']
        if saved.get('refresh'):
            try:
                return self._save(client, client.refresh(saved['refresh']))
            except AuthError:
                pass  # expired, or already used by another Kodi process: sign in again
            except Unreachable:
                raise
        if not self.password:
            raise AuthError('Signed out: enter your password in the add-on settings')
        return self._save(client, client.login(self.username, self.password))

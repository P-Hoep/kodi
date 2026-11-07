"""Google Sheets access with no API key: sheet-ID extraction, tab discovery and CSV download.

Endpoints (the sheet must be shared as "Anyone with the link can view"):
  tabs      https://docs.google.com/spreadsheets/d/{ID}/htmlview            (undocumented page)
  tab CSV   https://docs.google.com/spreadsheets/d/{ID}/export?format=csv&gid={GID}
  fallback  https://docs.google.com/spreadsheets/d/{ID}/gviz/tq?tqx=out:csv&sheet={NAME}
  optional  https://sheets.googleapis.com/v4/spreadsheets/{ID}?fields=...&key={KEY}
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import VERSION

BASE = 'https://docs.google.com/spreadsheets/d/%s'
TIMEOUT = 10
USER_AGENT = 'Kodi-Sheetcards/%s' % VERSION
ID_IN_URL = re.compile(r'/d/([A-Za-z0-9_-]{20,})')
BARE_ID = re.compile(r'^[A-Za-z0-9_-]{20,}$')


class SheetError(Exception):
    """kind: 'no_id', 'not_public', 'not_found', 'network' or 'bad_data'."""

    def __init__(self, kind, detail=''):
        Exception.__init__(self, '%s: %s' % (kind, detail) if detail else kind)
        self.kind = kind
        self.detail = detail


def extract_id(text):
    """A bare ID, or the ID inside a pasted URL. Whitespace is trimmed; '' if nothing usable."""
    text = (text or '').strip()
    match = ID_IN_URL.search(text)
    if match:
        return match.group(1)
    return text if BARE_ID.match(text) else ''


# ------------------------------------------------------------------ HTTP

def http_get(url, timeout=TIMEOUT, log=None):
    """GET url -> (body bytes, content type, final url). Raises SheetError."""
    started = time.time()
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
        body = response.read()
        kind = response.headers.get('Content-Type', '') or ''
        final = response.geturl() or url
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise SheetError('not_found', 'HTTP 404')
        if err.code in (401, 403):
            raise SheetError('not_public', 'HTTP %d' % err.code)
        raise SheetError('network', 'HTTP %d' % err.code)
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise SheetError('network', str(getattr(err, 'reason', err)))
    if log:
        log('GET %s -> %s, %d bytes, %.2f s' % (redact(url), kind or '?', len(body), time.time() - started))
    if 'accounts.google.com' in final or 'ServiceLogin' in final:
        raise SheetError('not_public', 'redirected to sign-in')
    return body, kind, final


def redact(url):
    return re.sub(r'([?&]key=)[^&]+', r'\1***', url)


# ------------------------------------------------------------------ tabs

_ITEM = re.compile(r'items\.push\(\{name:\s*"((?:[^"\\]|\\.)*)",[^}]*?gid:\s*"(\d+)"')
_TITLE = re.compile(r'<title>(.*?)</title>', re.S)


def _js_string(raw):
    """Decode a JavaScript string literal body (\\xNN, \\uNNNN, \\/ and friends)."""
    raw = re.sub(r'\\x([0-9a-fA-F]{2})', r'\\u00\1', raw).replace("\\'", "'")
    try:
        return json.loads('"%s"' % raw)
    except ValueError:
        return raw


def _html_unescape(text):
    import html
    return html.unescape(text)


def parse_htmlview(page):
    """htmlview HTML -> (sheet title, [{'gid', 'title', 'index'}]). Either may be empty."""
    tabs, seen = [], set()
    for name, gid in _ITEM.findall(page):
        if gid in seen:
            continue
        seen.add(gid)
        tabs.append({'gid': gid, 'title': _js_string(name), 'index': len(tabs)})
    title = ''
    match = _TITLE.search(page)
    if match:
        title = _html_unescape(match.group(1)).strip()
        title = re.sub(r'\s+-\s+Google (Drive|Sheets|Tabellen|Hojas de cálculo)\s*$', '', title).strip()
    return title, tabs


def discover_tabs(sheet_id, api_key='', get=http_get, log=None):
    """-> (title, tabs, source). Tries the Sheets API when a key is set, then htmlview.
    Raises SheetError for not_public / not_found / network; returns [] tabs if the page
    parsed but listed no tabs."""
    if api_key:
        url = ('https://sheets.googleapis.com/v4/spreadsheets/%s?fields=properties.title,'
               'sheets.properties(sheetId,title,index)&key=%s' % (sheet_id, urllib.parse.quote(api_key)))
        try:
            body, _kind, _final = get(url, log=log)
            data = json.loads(body.decode('utf-8'))
            tabs = [{'gid': str(s['properties']['sheetId']), 'title': s['properties']['title'],
                     'index': int(s['properties'].get('index', i))}
                    for i, s in enumerate(data.get('sheets', []))]
            tabs.sort(key=lambda t: t['index'])
            if tabs:
                return data.get('properties', {}).get('title', ''), tabs, 'api'
        except (SheetError, ValueError, KeyError, TypeError) as err:
            if log:
                log('Sheets API tab discovery failed (%s); trying htmlview' % err)
    body, kind, _final = get((BASE % sheet_id) + '/htmlview', log=log)
    page = body.decode('utf-8', 'replace')
    title, tabs = parse_htmlview(page)
    if not tabs and 'ServiceLogin' in page:
        raise SheetError('not_public', 'htmlview asks to sign in')
    return title, tabs, 'htmlview'


# ------------------------------------------------------------------ CSV

def export_url(sheet_id, gid):
    return (BASE % sheet_id) + '/export?format=csv&gid=%s' % gid


def gviz_url(sheet_id, name):
    return (BASE % sheet_id) + '/gviz/tq?tqx=out:csv&sheet=%s' % urllib.parse.quote(name)


def _csv_body(body, kind):
    if 'text/html' in kind.lower():
        raise SheetError('not_public', 'got an HTML page instead of CSV')
    return body.decode('utf-8', 'replace')


def fetch_tab(sheet_id, tab, get=http_get, log=None):
    """tab: {'gid', 'title'} (gid may be None for a name-only tab). -> (csv text, source).
    Primary is the export endpoint; gviz by name is the fallback."""
    first_error = None
    if tab.get('gid') is not None:
        try:
            body, kind, _final = get(export_url(sheet_id, tab['gid']), log=log)
            return _csv_body(body, kind), 'export'
        except SheetError as err:
            first_error = err
            if err.kind == 'not_found' and not tab.get('title'):
                raise
    if tab.get('title'):
        try:
            body, kind, _final = get(gviz_url(sheet_id, tab['title']), log=log)
            return _csv_body(body, kind), 'gviz'
        except SheetError as err:
            raise first_error or err
    raise first_error or SheetError('bad_data', 'tab has neither gid nor name')

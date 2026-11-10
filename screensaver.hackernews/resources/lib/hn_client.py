"""Hacker News' public read-only APIs, with the fallbacks the spec asks for.

Story lists and single items come from the Firebase API. Comments come from Algolia's item
endpoint, which returns a whole comment tree in one request; when that fails, the story's
`kids` array (already in ranking order) is read item by item instead. Requests are small,
timeouts are 10 s, one retry is allowed, and at most six run at once.

No Kodi imports: every function takes an optional `get` so the tests can feed recorded JSON.
"""

import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import config

BASE = 'https://hacker-news.firebaseio.com/v0'
ALGOLIA = 'https://hn.algolia.com/api/v1/items/%d'
ENDPOINTS = {
    'top': 'topstories',
    'best': 'beststories',
    'new': 'newstories',
    'ask': 'askstories',
    'show': 'showstories',
}
USER_AGENT = 'screensaver.hackernews/%s Kodi' % config.ADDON_VERSION
TIMEOUT = 10.0
WORKERS = 6


class FetchError(Exception):
    pass


def get_json(url, timeout=TIMEOUT, retries=1, opener=None):
    """GET url and decode JSON. One retry after a short pause; certificate checks stay on."""
    opener = opener or urllib.request.urlopen
    last = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers={
            'User-Agent': USER_AGENT,
            'Accept': 'application/json',
        })
        try:
            with opener(request, timeout=timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except (urllib.error.URLError, OSError, ValueError) as error:
            last = error
            if attempt < retries:
                time.sleep(0.6)
    raise FetchError('%s: %s' % (url, last))


def story_ids(kind, get=get_json):
    endpoint = ENDPOINTS.get(kind, ENDPOINTS['top'])
    ids = get('%s/%s.json' % (BASE, endpoint))
    if not isinstance(ids, list):
        raise FetchError('story list %s is not a list' % kind)
    return [int(i) for i in ids if isinstance(i, int)]


def story_item(story_id, get=get_json):
    return get('%s/item/%d.json' % (BASE, story_id))


def trim_story(item):
    """The fields the screensaver shows, or None when the item is unusable."""
    if not isinstance(item, dict) or item.get('type') != 'story':
        return None
    if item.get('deleted') or item.get('dead'):
        return None
    title = (item.get('title') or '').strip()
    if not title:
        return None
    story = {
        'id': int(item.get('id') or 0),
        'title': title,
        'url': item.get('url') or '',
        'by': item.get('by') or '',
        'score': int(item.get('score') or 0),
        'time': int(item.get('time') or 0),
        'descendants': int(item.get('descendants') or 0),
        'text': item.get('text') or '',
        'kids': [int(k) for k in (item.get('kids') or []) if isinstance(k, int)],
        'comments': [],
    }
    return story


def _trim_comment(item, include_reply=False):
    if not isinstance(item, dict):
        return None
    if item.get('deleted') or item.get('dead'):
        return None
    text = item.get('text')
    if not isinstance(text, str) or not text.strip():
        return None
    comment = {
        'by': item.get('author') or item.get('by') or '',
        'time': int(item.get('time') or item.get('created_at_i') or 0),
        'text': text,
    }
    if include_reply:
        children = item.get('children') or []
        for child in children:
            reply = _trim_comment(child, include_reply=False)
            if reply:
                comment['reply'] = reply
                break
    return comment


def algolia_comments(story_id, limit, include_reply=False, get=get_json):
    """The first `limit` top-level comments in HN ranking order, from one request."""
    tree = get(ALGOLIA % story_id)
    if not isinstance(tree, dict):
        raise FetchError('comment tree %d is not an object' % story_id)
    comments = []
    for child in tree.get('children') or []:
        comment = _trim_comment(child, include_reply)
        if comment:
            comments.append(comment)
        if len(comments) >= limit:
            break
    return comments


def firebase_comments(kids, limit, include_reply=False, get=get_json):
    """Fallback: fetch comment items one by one, following the story's kids order."""
    comments = []
    for kid in (kids or [])[:max(limit + 4, limit)]:
        try:
            comment = _trim_comment(story_item(kid, get), include_reply)
        except FetchError:
            continue
        if comment:
            comments.append(comment)
        if len(comments) >= limit:
            break
    return comments


def _comments_for(story, limit, include_reply, use_algolia, get):
    if limit <= 0:
        return []
    if use_algolia:
        try:
            return algolia_comments(story['id'], limit, include_reply, get)
        except FetchError:
            pass
    return firebase_comments(story.get('kids'), limit, include_reply, get)


def load(kind, limit=15, comments=3, include_reply=False, use_algolia=True,
         get=get_json, now=time.time, debug=None):
    """Fetch a story list with its comments. Returns a cache-shaped dict.

    Raises FetchError when the list itself cannot be read. A story whose item fails is
    skipped; a story whose comments fail simply has none on this pass.
    """
    ids = story_ids(kind, get)[:max(0, limit)]
    if not ids:
        return {'kind': kind, 'fetched_at': now(), 'stories': []}
    started = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        items = list(pool.map(lambda sid: _safe_story(sid, get), ids))
    stories = [story for story in items if story]
    if debug:
        debug('stories: %d of %d fetched in %.1f s' % (len(stories), len(ids), time.time() - started))

    if comments > 0 and stories:
        def with_comments(story):
            story['comments'] = _comments_for(story, comments, include_reply, use_algolia, get)
            return story
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            stories = list(pool.map(with_comments, stories))
        if debug:
            debug('comments: %d stories in %.1f s' %
                  (sum(1 for s in stories if s['comments']), time.time() - started))
    return {'kind': kind, 'fetched_at': now(), 'stories': stories}


def _safe_story(story_id, get):
    try:
        return trim_story(story_item(story_id, get))
    except FetchError:
        return None


def trim_for_cache(data):
    """Defensive copy: only the displayed fields, in case a caller hands over extra data."""
    out = {'kind': data.get('kind', 'top'), 'fetched_at': data.get('fetched_at', 0), 'stories': []}
    for story in data.get('stories') or []:
        out['stories'].append(dict(story))
    return out

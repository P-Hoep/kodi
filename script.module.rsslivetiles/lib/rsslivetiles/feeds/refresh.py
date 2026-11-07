"""Refreshing feeds: when each one is due, fetching + parsing + merging into the cache,
exponential backoff on failure, and the optional og:image lookup.

Options (a dict, from settings): refresh_min (default interval), max_items, max_age_days,
timeout, og_image. No Kodi imports; the program's and screensaver's worker threads call
refresh_due() in a loop.
"""

import re
import time

from . import fetcher, images, parser
from .store import FeedData, merge, retain

MIN_INTERVAL = 5 * 60
MAX_BACKOFF = 6 * 3600
BACKOFF_BASE = 5 * 60
OG_PER_REFRESH = 6
OG_TRIED_CAP = 400


def interval(feed, opts):
    minutes = feed.refresh_min or opts.get('refresh_min', 30)
    return max(MIN_INTERVAL, int(minutes) * 60)


def backoff(failures, base_interval):
    """5, 10, 20, 40 ... minutes after successive failures, never more than 6 h and never
    sooner than the feed's normal interval would allow on the first failure."""
    delay = BACKOFF_BASE * (2 ** max(0, failures - 1))
    return min(MAX_BACKOFF, max(delay, min(base_interval, BACKOFF_BASE)))


def is_due(feed, data, opts, now):
    meta = data.meta
    if not meta.get('checked_at'):
        return True
    return now >= float(meta.get('next_try', 0) or 0)


def refresh(feed, data, opts, now=None, get=fetcher.get, log=None):
    """Fetch one feed and return (FeedData, new_item_ids). Never raises for feed problems:
    a failure is recorded in data.meta['error'] and the cached items stay."""
    now = now or time.time()
    meta = dict(data.meta)
    meta['checked_at'] = now
    base_interval = interval(feed, opts)
    try:
        resp = get(feed.url, meta.get('etag', ''), meta.get('last_modified', ''), opts.get('timeout', 10))
        if resp.status == 304:
            meta.update(failures=0, error='', next_try=now + base_interval)
            out = FeedData(feed.id, data.info, data.items, meta)
            check_icon(out, get)
            return out, []
        info, fresh = parser.parse(resp.body, feed.id, resp.url or feed.url, resp.content_type, now)
        if not fresh and not info.title:
            raise parser.FeedError('the feed has no items')
        known = set(i.id for i in data.items)
        items = retain(merge(data.items, fresh), feed.max_items or opts.get('max_items', 30),
                       opts.get('max_age_days', 7), now)
        new_ids = [i.id for i in items if i.id not in known]
        meta.update(etag=resp.etag, last_modified=resp.last_modified, fetched_at=now, failures=0, error='',
                    next_try=now + base_interval)
        out = FeedData(feed.id, info, items, meta)
        check_icon(out, get)
        if opts.get('og_image'):
            add_og_images(out, get, opts, log)
        return out, new_ids
    except (fetcher.FetchError, parser.FeedError) as err:
        failures = int(meta.get('failures', 0) or 0) + 1
        meta.update(failures=failures, error=str(err), next_try=now + backoff(failures, base_interval))
        if log:
            log('feed %s failed (%d in a row): %s' % (feed.url, failures, err))
        return FeedData(feed.id, data.info, data.items, meta), []


def check_icon(data, get):
    """Kodi cannot tell us when an image fails to load, so a feed icon that does not download
    is dropped here (the tiles then show the feed's initials). Each icon URL is checked once."""
    url = re.sub(r'(\.(?:png|jpe?g|gif|webp|ico))/$', r'\1', data.info.image or '', flags=re.I)
    data.info.image = url
    if not url:
        return
    if data.meta.get('icon_checked') == url:
        if not data.meta.get('icon_ok', True):
            data.info.image = ''
        return
    ok = True
    try:
        resp = get(url, timeout=5, limit=2 * 1024 * 1024, accept='image/*')
        ok = resp.status == 304 or len(resp.body) > 0
    except fetcher.FetchError:
        ok = False
    data.meta['icon_checked'] = url
    data.meta['icon_ok'] = ok
    if not ok:
        data.info.image = ''


def add_og_images(data, get, opts, log=None):
    """For items without a picture, read og:image from the article page (a few per refresh;
    each article is tried once)."""
    tried = list(data.meta.get('og_tried', []))
    budget = OG_PER_REFRESH
    for item in data.items:
        if budget <= 0:
            break
        if item.images or not item.link or item.id in tried:
            continue
        budget -= 1
        tried.append(item.id)
        try:
            resp = get(item.link, timeout=opts.get('timeout', 10), limit=1024 * 1024,
                       accept='text/html,application/xhtml+xml')
        except fetcher.FetchError:
            continue
        url = images.og_image(resp.body[:400000].decode('utf-8', 'replace'))
        ranked = images.rank([('og:image', url, 0, 0, '')], item.link)
        if ranked:
            item.images = ranked
            if log:
                log('og:image for %s' % item.link)
    data.meta['og_tried'] = tried[-OG_TRIED_CAP:]


def refresh_due(store, feeds, opts, now=None, get=fetcher.get, log=None, stop=None, force=False):
    """Refresh every enabled feed that is due. Yields (feed, FeedData, new_ids) as each
    finishes, so the caller can update the screen feed by feed."""
    for feed in feeds:
        if stop and stop():
            return
        if not feed.enabled:
            continue
        data = store.load(feed.id)
        if not force and not is_due(feed, data, opts, now or time.time()):
            continue
        fresh, new_ids = refresh(feed, data, opts, now, get, log)
        store.save(fresh)
        yield feed, fresh, new_ids

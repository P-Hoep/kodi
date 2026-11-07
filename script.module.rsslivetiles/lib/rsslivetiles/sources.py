"""Feeds + cache + state -> the Sources the layouts consume. No Kodi imports."""

from . import theme
from .tiles.model import Source


def build(store, feeds, settings, global_hex, state=None):
    state = state if state is not None else store.state()
    hidden = set(state.get('hidden', []))
    last_view = state.get('last_view', {})
    out = []
    for feed in feeds:
        if not feed.enabled:
            continue
        out.append(make(store, feed, settings, global_hex, hidden, last_view))
    return out


def make(store, feed, settings, global_hex, hidden, last_view):
    data = store.load(feed.id)
    items = [i for i in data.items if i.id not in hidden]
    items.sort(key=lambda i: i.published, reverse=True)
    seen = float(last_view.get(feed.id, 0) or 0)
    if seen:
        new = sum(1 for i in items if i.published > seen)
    else:
        new = len(items)
    accent = theme.feed_accent(feed, settings, global_hex)
    return Source(feed, data, items, new, accent)

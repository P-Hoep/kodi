"""Manage feeds (spec 3.5): add by URL (checked, title detected), edit title / accent / max
items / refresh interval / enabled / pinned tile size, reorder, delete, OPML import / export.
Built from Kodi's own dialogs, so it works with any remote and any skin.
"""

import xbmc
import xbmcgui
import xbmcvfs

from .. import kodi, theme
from ..feeds import opml, parser, refresh
from ..feeds.store import Feed, SIZES

tr = kodi.tr


def run(store):
    """The manager loop. Returns True when the feed list changed."""
    changed = False
    dialog = xbmcgui.Dialog()
    while True:
        feeds = store.feeds()
        labels = ['[B]%s[/B]' % tr(32041)]
        for f in feeds:
            data = store.load(f.id)
            name = f.title or data.info.title or f.url
            extra = []
            if not f.enabled:
                extra.append(tr(32063))
            if data.error:
                extra.append(tr(32011).lower())
            labels.append(name + ('  [COLOR FF808080](%s)[/COLOR]' % ', '.join(extra) if extra else ''))
        labels += [tr(32042), tr(32043)]
        choice = dialog.select(tr(32040), labels)
        if choice < 0:
            return changed
        if choice == 0:
            changed = add_feed(store) or changed
        elif choice == len(labels) - 2:
            changed = import_opml(store) or changed
        elif choice == len(labels) - 1:
            export_opml(store)
        else:
            changed = edit_feed(store, choice - 1) or changed


def add_feed(store, url=None):
    dialog = xbmcgui.Dialog()
    if url is None:
        url = dialog.input(tr(32044), 'https://', type=xbmcgui.INPUT_ALPHANUM).strip()
    if not url or url in ('https://', 'http://'):
        return False
    if '://' not in url:
        url = 'https://' + url
    feeds = store.feeds()
    feed = Feed(url)
    if any(f.id == feed.id for f in feeds):
        dialog.notification('RSS Live Tiles', tr(32077), xbmcgui.NOTIFICATION_INFO, 3000)
        return False
    settings = kodi.read_settings(kodi.APP_ID)
    opts = kodi.fetch_options(settings)
    progress = xbmcgui.DialogProgress()
    progress.create('RSS Live Tiles', tr(32045))
    try:
        data = refresh.refresh(feed, store.load(feed.id), opts, log=kodi.debug)[0]
    finally:
        progress.close()
    if data.error and not data.items:
        dialog.ok('RSS Live Tiles', '%s\n%s\n[COLOR FF808080]%s[/COLOR]' % (tr(32046), url, data.error))
        return False
    feed.title = data.info.title or url
    title = dialog.input(tr(32047), feed.title, type=xbmcgui.INPUT_ALPHANUM)
    if title:
        feed.title = title.strip()
    store.save(data)
    feeds.append(feed)
    store.save_feeds(feeds)
    dialog.notification('RSS Live Tiles', tr(32064), xbmcgui.NOTIFICATION_INFO, 2500)
    return True


def _accent_label(feed):
    if not feed.accent:
        return tr(32056)
    for name, hexa in theme.ACCENTS:
        if name.lower() == str(feed.accent).lower() or hexa == theme.parse_hex(str(feed.accent)):
            return name
    return '#' + (theme.parse_hex(str(feed.accent)) or '?')


def _size_label(size):
    return {None: tr(32057), 'small': tr(32072), 'medium': tr(32073), 'wide': tr(32074),
            'large': tr(32075)}[size]


def choose_accent(current=None):
    """Palette list with Default and Custom. -> None (default), a palette name or 'RRGGBB';
    False when cancelled."""
    dialog = xbmcgui.Dialog()
    labels = [tr(32056)] + [name for name, _hex in theme.ACCENTS] + [tr(32078)]
    pick = dialog.select(tr(32048), labels)
    if pick < 0:
        return False
    if pick == 0:
        return None
    if pick == len(labels) - 1:
        value = theme.parse_hex(dialog.input(tr(32076), current or '', type=xbmcgui.INPUT_ALPHANUM))
        if not value:
            return False
        if theme.white_contrast(value) < theme.MIN_CONTRAST:
            dialog.notification('RSS Live Tiles', tr(32069), xbmcgui.NOTIFICATION_WARNING, 4000)
        return value
    return theme.ACCENTS[pick - 1][0]


def edit_feed(store, index):
    dialog = xbmcgui.Dialog()
    changed = False
    while True:
        feeds = store.feeds()
        if not 0 <= index < len(feeds):
            return changed
        feed = feeds[index]
        rows = [
            ('title', '%s: %s' % (tr(32047), feed.title or feed.url)),
            ('accent', '%s: %s' % (tr(32048), _accent_label(feed))),
            ('max', '%s: %s' % (tr(32049), feed.max_items or tr(32056))),
            ('refresh', '%s: %s' % (tr(32062), feed.refresh_min or tr(32056))),
            ('enabled', '%s: %s' % (tr(32050), tr(32066) if feed.enabled else tr(32067))),
            ('size', '%s: %s' % (tr(32051), _size_label(feed.tile_size))),
            ('up', tr(32052)), ('down', tr(32053)), ('delete', tr(32054)),
        ]
        pick = dialog.select(feed.title or feed.url, [r[1] for r in rows])
        if pick < 0:
            return changed
        what = rows[pick][0]
        if what == 'title':
            value = dialog.input(tr(32047), feed.title, type=xbmcgui.INPUT_ALPHANUM)
            if not value:
                continue
            feed.title = value.strip()
        elif what == 'accent':
            value = choose_accent(feed.accent)
            if value is False:
                continue
            feed.accent = value
        elif what == 'max':
            value = dialog.numeric(0, tr(32049), str(feed.max_items or ''))
            feed.max_items = max(5, min(200, int(value))) if value and value.isdigit() and int(value) else None
        elif what == 'refresh':
            value = dialog.numeric(0, tr(32062), str(feed.refresh_min or ''))
            feed.refresh_min = max(5, int(value)) if value and value.isdigit() and int(value) else None
        elif what == 'enabled':
            feed.enabled = not feed.enabled
        elif what == 'size':
            options = [None] + list(SIZES)
            value = dialog.select(tr(32051), [_size_label(s) for s in options])
            if value < 0:
                continue
            feed.tile_size = options[value]
        elif what in ('up', 'down'):
            other = index - 1 if what == 'up' else index + 1
            if not 0 <= other < len(feeds):
                continue
            feeds[index], feeds[other] = feeds[other], feeds[index]
            index = other
        elif what == 'delete':
            if not dialog.yesno(feed.title or feed.url, tr(32055)):
                continue
            del feeds[index]
            store.save_feeds(feeds)
            store.forget(feed.id)
            return True
        store.save_feeds(feeds)
        changed = True


def import_opml(store, path=None):
    dialog = xbmcgui.Dialog()
    if path is None:
        path = dialog.browseSingle(1, tr(32060), 'files', '.opml|.xml')
    if not path:
        return False
    handle = xbmcvfs.File(path)
    try:
        raw = handle.readBytes()
    finally:
        handle.close()
    try:
        entries = opml.parse(bytes(raw))
    except parser.FeedError as err:
        dialog.ok('RSS Live Tiles', str(err))
        return False
    feeds = store.feeds()
    known = set(f.id for f in feeds)
    added = 0
    for title, url in entries:
        feed = Feed(url, title)
        if feed.id in known:
            continue
        known.add(feed.id)
        feeds.append(feed)
        added += 1
    store.save_feeds(feeds)
    dialog.notification('RSS Live Tiles', tr(32058) % added, xbmcgui.NOTIFICATION_INFO, 3000)
    return added > 0


def export_opml(store, folder=None):
    dialog = xbmcgui.Dialog()
    if folder is None:
        folder = dialog.browseSingle(3, tr(32061), 'files')
    if not folder:
        return
    feeds = store.feeds()
    path = folder.rstrip('/\\') + '/rsslivetiles.opml'
    handle = xbmcvfs.File(path, 'w')
    try:
        handle.write(opml.export(feeds).encode('utf-8'))
    finally:
        handle.close()
    kodi.log('exported %d feeds to %s' % (len(feeds), path), xbmc.LOGINFO)
    dialog.notification('RSS Live Tiles', tr(32059) % len(feeds), xbmcgui.NOTIFICATION_INFO, 3000)

"""Settings buttons: Manage feeds, Import / Export OPML, Refresh all feeds now, Clear cache.
Both front-ends call run(addon_id, action) from their default.py (RunScript(...,<action>)),
then the settings dialog reopens."""

import xbmc
import xbmcaddon
import xbmcgui

from . import kodi
from .feeds import refresh


def run(addon_id, action):
    store = kodi.store()
    try:
        if action == 'manage':
            from .ui import manager
            manager.run(store)
        elif action == 'import_opml':
            from .ui import manager
            manager.import_opml(store)
        elif action == 'export_opml':
            from .ui import manager
            manager.export_opml(store)
        elif action == 'refresh':
            refresh_all(store, addon_id)
        elif action == 'clear_cache':
            store.clear_cache()
            kodi.notify(kodi.tr(32068), addon_id)
        else:
            kodi.log('unknown action %r' % action, xbmc.LOGWARNING)
            return
    finally:
        if action in ('manage', 'import_opml', 'export_opml', 'refresh', 'clear_cache'):
            xbmcaddon.Addon(addon_id).openSettings()


def refresh_all(store, addon_id):
    settings = kodi.read_settings(addon_id)
    opts = kodi.fetch_options(settings)
    feeds = [f for f in store.feeds() if f.enabled]
    progress = xbmcgui.DialogProgress()
    progress.create('RSS Live Tiles', kodi.tr(32070))
    try:
        for n, (feed, data, _new) in enumerate(refresh.refresh_due(store, feeds, opts, log=kodi.debug,
                                                                   stop=progress.iscanceled, force=True)):
            progress.update(int(100.0 * (n + 1) / max(1, len(feeds))), feed.title or feed.url)
    finally:
        progress.close()
    kodi.notify(kodi.tr(32071), addon_id)

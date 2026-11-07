"""Settings buttons: Choose decks, Refresh now, Reset progress, Clear cache. Both front-ends
call run(addon_id, action) from their default.py (RunScript(...,<action>))."""

import xbmc
import xbmcaddon
import xbmcgui

from . import kodi, sheet, srs
from .deck import parse_keys


def run(addon_id, action):
    settings = kodi.read_settings(addon_id)
    target = settings['source_addon'] if action == 'choose_decks' else addon_id
    try:
        if action == 'choose_decks':
            choose_decks(settings, target)
        elif action == 'refresh':
            refresh(settings)
        elif action == 'reset_progress':
            reset_progress(settings)
        elif action == 'clear_cache':
            kodi.cache().clear()
            kodi.notify(kodi.tr(32052), addon_id)
    finally:
        xbmcaddon.Addon(addon_id).openSettings()


def load(settings):
    """Cached data, or a fresh download with a busy dialog. None (and a dialog) on error."""
    loader = kodi.loader(settings)
    got = loader.cached()
    if got:
        return got
    xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    try:
        return loader.refresh()
    except sheet.SheetError as err:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        title, body = kodi.error_text(err)
        xbmcgui.Dialog().ok('Sheetcards', '%s\n%s' % (title, body))
        return None
    finally:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')


def choose_decks(settings, target):
    if not settings['sheet_id']:
        xbmcgui.Dialog().ok('Sheetcards', '%s\n%s' % (kodi.tr(32000), kodi.tr(32001)))
        return
    got = load(settings)
    if not got:
        return
    decks = got.usable
    keys = parse_keys(settings.get('decks', ''))
    pre = [i for i, d in enumerate(decks) if d.key in keys] or list(range(len(decks)))
    labels = ['%s  (%s)' % (d.title, kodi.tr(32019) % len(d.cards)) for d in decks]
    picked = xbmcgui.Dialog().multiselect(kodi.tr(32049), labels, preselect=pre)
    if picked is None:
        return
    chosen = [decks[i].key for i in picked]
    value = '' if len(chosen) in (0, len(decks)) else ','.join(chosen)
    xbmcaddon.Addon(target).setSettingString('decks', value)


def refresh(settings):
    if not settings['sheet_id']:
        xbmcgui.Dialog().ok('Sheetcards', '%s\n%s' % (kodi.tr(32000), kodi.tr(32001)))
        return
    try:
        got = kodi.loader(settings).refresh()
    except sheet.SheetError as err:
        title, body = kodi.error_text(err)
        xbmcgui.Dialog().ok('Sheetcards', '%s\n%s' % (title, body))
        return
    kodi.notify(kodi.tr(32053) % (len(got.usable), len(got.all_cards())))


def reset_progress(settings):
    if not settings['sheet_id']:
        return
    if not xbmcgui.Dialog().yesno('Sheetcards', kodi.tr(32050)):
        return
    srs.Progress(kodi.cache().progress_path(settings['sheet_id']), settings['sheet_id'], kodi.log).reset()
    kodi.notify(kodi.tr(32051))

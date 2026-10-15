"""The settings screen's buttons: catalogue status, country picker, favourites, reset, preview."""

import os
import time

import xbmc
import xbmcaddon
import xbmcgui

from . import catalog as catalog_mod
from . import config, controller, health as health_mod, selector as selector_mod


def run(action):
    addon = xbmcaddon.Addon(config.ADDON_ID)
    profile = controller.profile_dir(addon)
    tr = controller.translator(addon)
    if action == 'preview':
        controller.run_session(preview=True)
    elif action == 'status':
        status(addon, profile, tr)
    elif action == 'pick_countries':
        pick_countries(addon, profile, tr)
    elif action == 'fav_last':
        history = health_mod.History(os.path.join(profile, 'history.json'))
        last = history.last()
        if last and history.favourite(last):
            history.save()
            name = dict((c.id, c.title) for c in load_catalog(profile).cams).get(last, '')
            notify(addon, tr(32006, 'Added to favourites'), name)
        elif last:
            notify(addon, tr(32006, 'Added to favourites'), '')
        else:
            notify(addon, tr(32007, 'No camera has been shown yet'), '')
    elif action == 'fav_clear':
        history = health_mod.History(os.path.join(profile, 'history.json'))
        history.clear_favourites()
        history.save()
        notify(addon, tr(32008, 'Favourites cleared'), '')
    elif action == 'reset':
        health = health_mod.Health(os.path.join(profile, 'health.json'))
        health.reset()
        health.save()
        history = health_mod.History(os.path.join(profile, 'history.json'))
        history.reset()
        history.save()
        notify(addon, tr(32009, 'Camera health and history reset'), '')


def notify(addon, heading, message):
    xbmcgui.Dialog().notification(heading, message or config.ADDON_NAME,
                                  os.path.join(addon.getAddonInfo('path'), 'icon.png'), 3000)


def load_catalog(profile, download=False, url=None):
    cat = catalog_mod.Catalog(profile)
    if not cat.load() and download:
        xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
        try:
            cat.refresh(url or config.CATALOG_URL)
        except Exception as error:
            controller.log('catalogue download failed: %s' % error, xbmc.LOGWARNING)
        finally:
            xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
    return cat


def status(addon, profile, tr):
    s = controller.read_settings(addon)
    cat = load_catalog(profile, download=True, url=s.get('catalog_url'))
    if not cat.cams:
        xbmcgui.Dialog().ok(tr(32002, 'Catalogue'), tr(32003, 'Not downloaded yet'))
        return
    health = health_mod.Health(os.path.join(profile, 'health.json'))
    history = health_mod.History(os.path.join(profile, 'history.json'))
    now = time.time()
    # Count with the filters as set (no relaxation), and ignoring the time of day.
    plain = dict(s, daylight=False)
    pool = selector_mod.candidates(cat.cams, plain, health, history, now)
    lit = selector_mod.candidates(cat.cams, s, health, history, now) if s.get('daylight', True) else pool
    lines = [tr(32005, 'Downloaded %s, %d cameras') % (time.strftime('%Y-%m-%d', time.localtime(cat.fetched)),
                                                        len(cat.cams)),
             tr(32004, '%d cameras match your filters') % len(pool)]
    if s.get('daylight', True):
        lines[-1] += ' ' + tr(32014, '(%d in daylight now)') % len(lit)
    blocked = len(health.blocked_ids(now))
    if blocked:
        lines.append(tr(32012, '%d cameras blocked after failures') % blocked)
    lines.append(tr(32013, 'Source: %s') % config.DATASET)
    xbmcgui.Dialog().ok(tr(32002, 'Catalogue'), '[CR]'.join(lines))


def pick_countries(addon, profile, tr):
    s = controller.read_settings(addon)
    cat = load_catalog(profile, download=True, url=s.get('catalog_url'))
    if not cat.cams:
        xbmcgui.Dialog().ok(tr(32002, 'Catalogue'), tr(32010, 'Download the catalogue first: run the screensaver once'))
        return
    # Count each country's cameras under the other filters (all countries allowed).
    f = selector_mod.Filters(dict(s, country_mode=0))
    counts = {}
    for cam in cat.cams:
        if cam.cc and f.static_ok(cam):
            counts[cam.cc] = counts.get(cam.cc, 0) + 1
    codes = sorted(counts, key=lambda cc: catalog_mod.country_name(cc) or cc)
    chosen = config.country_codes(s.get('countries', ''))
    labels = ['%s (%d)' % (catalog_mod.country_name(cc) or cc, counts[cc]) for cc in codes]
    pre = [i for i, cc in enumerate(codes) if cc in chosen]
    picked = xbmcgui.Dialog().multiselect(tr(32011, 'Choose countries'), labels, preselect=pre)
    if picked is None:
        return
    addon.setSetting('countries', ', '.join(codes[i] for i in picked))
    addon.openSettings()

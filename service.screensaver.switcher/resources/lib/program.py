"""The Programs entry: shows the schedule and what is chosen now, with a few actions.

RunScript(service.screensaver.switcher,apply) applies the schedule and
RunScript(service.screensaver.switcher,preview) starts the screensaver, without the menu
(also reachable over JSON-RPC with Addons.ExecuteAddon and params ["preview"])."""

import xbmc
import xbmcaddon
import xbmcgui

from . import config, schedule, switcher


def describe(s, names):
    def name(addon_id):
        return names.get(addon_id, addon_id + ' (not installed)') if addon_id else 'leave as is'

    slot, target = schedule.wanted(s, switcher.now_minutes())
    lines = ['Now: [B]%s[/B] (%s)' % (name(target), 'window %d' % slot if slot else 'default'),
             "Kodi's screensaver: %s" % name(switcher.current())]
    if not s['enabled']:
        lines.append('[COLOR orange]Scheduling is switched off.[/COLOR]')
    lines.append('')
    rows = schedule.windows(s)
    for n, start, end, pool in rows:
        span = 'all day' if start == end else '%s-%s' % (schedule.clock(start), schedule.clock(end))
        every = '  (alternating every %d min)' % s['alternate_minutes'] if len(pool) > 1 else ''
        lines.append('Window %d  %s  %s%s' % (n, span, ' / '.join(name(p) for p in pool), every))
    if not rows:
        lines.append('No windows are set up yet.')
    lines.append('Other times  %s' % name(s['default_screensaver']))
    return '\n'.join(lines)


def apply_now():
    _slot, target = schedule.wanted(switcher.settings(), switcher.now_minutes())
    return target, switcher.apply(target, xbmc.Monitor(), False)


def run(args=()):
    if 'apply' in args:
        apply_now()
        return
    if 'preview' in args:
        xbmc.executebuiltin('ActivateScreensaver')
        return
    addon = xbmcaddon.Addon(config.ADDON_ID)
    dialog = xbmcgui.Dialog()
    while True:
        s = switcher.settings()
        names = switcher.installed()
        choice = dialog.select(addon.getAddonInfo('name'),
                               ['Show the schedule', 'Apply the schedule now', 'Preview the screensaver',
                                'Settings'])
        if choice == 0:
            dialog.textviewer(addon.getAddonInfo('name'), describe(s, names))
        elif choice == 1:
            target, changed = apply_now()
            dialog.notification(addon.getAddonInfo('name'),
                                'Switched to %s' % names.get(target, target) if changed else 'Already up to date',
                                time=3000, sound=False)
        elif choice == 2:
            xbmc.executebuiltin('ActivateScreensaver')
            return
        elif choice == 3:
            addon.openSettings()
        else:
            return

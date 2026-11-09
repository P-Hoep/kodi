"""The "Find a place by name" action: search Photon, then store the coordinates.

The action is offered by both add-ons, so it writes to every installed Vintage Radar add-on and
they stay in step. Kodi's settings dialog is reopened afterwards, which is where the user can
fine-tune or press Cancel.
"""

import xbmc
import xbmcaddon
import xbmcgui

from . import net

TARGETS = ('script.vintageradar', 'screensaver.vintageradar.gl',
           'screensaver.vintageradar.gl.armv7')


def _parse_coordinates(text):
    parts = text.replace(',', ' ').split()
    if len(parts) != 2:
        return None
    try:
        lat = float(parts[0])
        lon = float(parts[1])
    except ValueError:
        return None
    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
        return lat, lon
    return None


def _store(name, lat, lon):
    for addon_id in TARGETS:
        if not xbmc.getCondVisibility('System.HasAddon(%s)' % addon_id):
            continue
        try:
            addon = xbmcaddon.Addon(addon_id)
            addon.setSettingNumber('latitude', round(lat, 5))
            addon.setSettingNumber('longitude', round(lon, 5))
            addon.setSettingString('location_name', name)
        except Exception:
            continue


def find_location():
    addon = xbmcaddon.Addon('script.vintageradar')
    query = xbmcgui.Dialog().input('Search for a place (or type "lat, lon")')
    if not query:
        addon.openSettings()
        return
    direct = _parse_coordinates(query)
    if direct is not None:
        _store('Lat %.4f, Lon %.4f' % direct, direct[0], direct[1])
        addon.openSettings()
        return
    try:
        results = net.search_places(query)
    except net.HttpError as error:
        xbmcgui.Dialog().ok('Vintage Radar', 'Search failed: %s' % error)
        addon.openSettings()
        return
    if not results:
        xbmcgui.Dialog().ok('Vintage Radar', 'No places found for "%s".' % query)
        addon.openSettings()
        return
    choice = xbmcgui.Dialog().select('Choose the place', [result[0] for result in results])
    if choice >= 0:
        label, lat, lon = results[choice]
        _store(label.split(',')[0], lat, lon)
    addon.openSettings()

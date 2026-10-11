"""Settings helper: "Find a location" button searches a place name and stores its coordinates."""

import xbmcaddon
import xbmcgui

from . import layers, net

ADDON_ID = 'screensaver.godseye.map'


def find_location():
    addon = xbmcaddon.Addon(ADDON_ID)
    query = xbmcgui.Dialog().input('Search for a place (city, landmark, address)')
    if not query:
        addon.openSettings()
        return
    try:
        results = layers.search_places(query)
    except net.HttpError as error:
        xbmcgui.Dialog().ok("God's Eye Map", 'Search failed: %s' % error)
        addon.openSettings()
        return
    if not results:
        xbmcgui.Dialog().ok("God's Eye Map", 'No places found for "%s".' % query)
        addon.openSettings()
        return
    choice = xbmcgui.Dialog().select('Choose the place', [r[0] for r in results])
    if choice >= 0:
        name, lat, lon = results[choice]
        addon.setSettingNumber('lat', round(lat, 5))
        addon.setSettingNumber('lon', round(lon, 5))
        addon.setSettingString('location_name', name.split(',')[0])
    addon.openSettings()

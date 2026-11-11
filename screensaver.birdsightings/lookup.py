# -*- coding: utf-8 -*-
"""Settings button: turn a place name into latitude/longitude."""
import os
import sys

import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()
sys.path.insert(0, os.path.join(ADDON.getAddonInfo("path"), "resources", "lib"))
import birdsdata  # noqa: E402


def main():
    dialog = xbmcgui.Dialog()
    name = ADDON.getAddonInfo("name")
    query = dialog.input(ADDON.getLocalizedString(30040), type=xbmcgui.INPUT_ALPHANUM)
    if not query:
        return
    try:
        places = birdsdata.geocode(query)
    except Exception:
        dialog.ok(name, ADDON.getLocalizedString(30043))
        return
    if not places:
        dialog.ok(name, ADDON.getLocalizedString(30041))
        return
    choice = 0
    if len(places) > 1:
        choice = dialog.select(name, [p["display"] for p in places])
        if choice < 0:
            return
    p = places[choice]
    ADDON.setSetting("latitude", "%.4f" % p["lat"])
    ADDON.setSetting("longitude", "%.4f" % p["lng"])
    ADDON.setSetting("location_name", p["short"])
    dialog.notification(name, "%s  (%.4f, %.4f)" % (p["short"], p["lat"], p["lng"]), time=4000)


if __name__ == "__main__":
    main()

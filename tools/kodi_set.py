"""Runs INSIDE Kodi (via RunScript) to change the screensaver's settings for testing.
Args: key=value ... ; ints, floats and true/false are typed automatically."""
import sys

import xbmcaddon

addon = xbmcaddon.Addon('screensaver.godseye.map')
for arg in sys.argv[1:]:
    key, _, value = arg.partition('=')
    if value in ('true', 'false'):
        addon.setSettingBool(key, value == 'true')
    else:
        try:
            addon.setSettingInt(key, int(value))
        except ValueError:
            try:
                addon.setSettingNumber(key, float(value))
            except ValueError:
                addon.setSettingString(key, value)

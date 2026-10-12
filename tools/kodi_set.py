"""Runs INSIDE Kodi (via RunScript) to change the screensaver's settings for testing.
Args: [addon=<id>] key=value ... ; ints, floats and true/false are typed automatically.
A comma-separated list goes in with ';' between items, e.g. projection_list=0;3;11."""
import sys

import xbmcaddon

args = sys.argv[1:]
addon_id = 'screensaver.godseye.map'
if args and args[0].startswith('addon='):
    addon_id = args.pop(0).partition('=')[2]
addon = xbmcaddon.Addon(addon_id)
for arg in args:
    key, _, value = arg.partition('=')
    if ';' in value:
        addon.getSettings().setIntList(key, [int(v) for v in value.split(';')])
        continue
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

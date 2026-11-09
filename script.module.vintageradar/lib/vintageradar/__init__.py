"""Vintage Radar: the shared scope behind script.vintageradar (the app) and
screensaver.vintageradar (the screensaver).

The aircraft model, feed, geometry and formatting (radar_core, radar_feed, net), the text
renderer (fontdraw, pngcodec), the phosphor palettes (theme), the window and its controls (ui),
the main loop (session) and the place search (setup) all live here. The front-ends are thin:
the app adds the remote, the clickable contact sheet and the settings menu; the screensaver
runs the same session hands-off and exits on any key.

The pure modules import no Kodi modules and are tested offline by tests/test_vintageradar.py.
"""

VERSION = '1.0.1'
LIBRARY_ID = 'script.module.vintageradar'
APP_ID = 'script.vintageradar'
SCREENSAVER_ID = 'screensaver.vintageradar'
SKIN = 'script-vintageradar-main.xml'

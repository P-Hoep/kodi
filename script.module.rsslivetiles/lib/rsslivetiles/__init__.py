"""RSS Live Tiles: RSS/Atom feeds as Windows Phone style live tiles, shared by
script.rsslivetiles (the program) and screensaver.rsslivetiles.

Everything outside ui/, kodi.py and actions.py is pure Python (no Kodi imports) and is
tested offline by tests/test_rsslivetiles.py.
"""

VERSION = '1.0.0'
LIBRARY_ID = 'script.module.rsslivetiles'
APP_ID = 'script.rsslivetiles'
SCREENSAVER_ID = 'screensaver.rsslivetiles'
USER_AGENT = 'Kodi-RSSLiveTiles/%s (+https://github.com/P-Hoep/kodi)' % VERSION

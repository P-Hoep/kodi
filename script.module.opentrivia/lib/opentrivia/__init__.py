"""OpenTrivia: the shared code, data and windows behind script.opentrivia (the quiz app) and
screensaver.opentrivia (the hands-free quiz screensaver).

Everything outside kodi.py and ui/ is pure Python (no Kodi imports) and is tested offline by
tests/test_opentrivia.py.
"""

VERSION = '1.0.0'
LIBRARY_ID = 'script.module.opentrivia'
APP_ID = 'script.opentrivia'
SCREENSAVER_ID = 'screensaver.opentrivia'
SKIN = 'opentrivia.xml'

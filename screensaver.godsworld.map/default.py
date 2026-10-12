import os
import sys

# The vendored sgp4 package uses absolute imports, so resources/lib goes on the path.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', 'lib'))

from resources.lib import screensaver  # noqa: E402

if len(sys.argv) > 1 and sys.argv[1] == 'clear_cache':
    screensaver.clear_cache()
else:
    screensaver.run()

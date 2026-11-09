import sys

import xbmc

from resources.lib import saver
from vintageradar import setup

if __name__ == '__main__':
    if 'find_location' in sys.argv[1:]:
        setup.find_location()
    else:
        try:
            saver.main()
        except Exception:
            import traceback
            xbmc.log(traceback.format_exc(), xbmc.LOGERROR)
            raise

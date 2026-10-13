import sys

from resources.lib import window

if len(sys.argv) > 1 and sys.argv[1] == 'find_location':
    from resources.lib import setup
    setup.find_location()
elif len(sys.argv) > 1 and sys.argv[1] == 'test_sources':
    from resources.lib import setup
    setup.test_sources()
elif len(sys.argv) > 1 and sys.argv[1] == 'clear_cache':
    window.clear_cache()
elif len(sys.argv) > 1 and sys.argv[1] == 'interactive':
    window.run(interactive=True)
else:
    window.run()

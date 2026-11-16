"""Generate the AI Arcade screensaver's settings.xml and strings.po from one table, so the Kodi
settings and screensaver.aiarcade/src/ScreensaverAIArcade.cpp agree on ids and ranges.

Run:
  python3 tools/make_settings_aiarcade.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402

B = lambda sid, label, default, **kw: dict(id=sid, type='boolean', label=label, default=default, **kw)
I = lambda sid, label, default, lo, hi, step=1, **kw: dict(
    id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)

CATEGORIES = [
    ('General', [
        dict(id='rom_folder', type='path', label='ROM folder (.nes files)', default=''),
        B('recursive', 'Include sub-folders', True),
        I('switch_minutes', 'Switch to another ROM every N minutes (0 = never)', 0, 0, 120, 5),
        B('hud', 'Show the HUD and fitness graph', True),
    ]),
    ('Training', [
        I('threads', 'Training threads', 1, 1, 15),
        I('cpu_cap', 'CPU cap per training thread (% of one core)', 60, 10, 100, 10),
        I('population', 'Population size', 100, 25, 300, 25),
    ]),
    ('Advanced', [
        B('reset_all', 'Reset the learning of all ROMs the next time it starts', False),
    ]),
]

if __name__ == '__main__':
    root = os.path.normpath(os.path.join(HERE, '..', 'screensaver.aiarcade'))
    os.makedirs(os.path.join(root, 'resources'), exist_ok=True)
    write(root, 'screensaver.aiarcade', 'AI Arcade', CATEGORIES, 'tools/make_settings_aiarcade.py')

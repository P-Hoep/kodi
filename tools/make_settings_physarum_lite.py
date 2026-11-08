"""Generate the Physarum Lite screensaver's settings.xml and strings.po from one table.

Physarum Lite is the Physarum simulation with the clock, the fonts and every timer removed: no
clock in the middle, no start over every so many minutes, no wandering between behaviours. What is
left is the agent model and its drawing, running continuously. It is meant for low-resource
devices, so its defaults are light: 65 thousand agents on a 480 x 270 trail at 30 steps/s, no
glow, no screen effect.

It shares the behaviour, agent-size, trail-size, speed, food, colour, view and camera lists with the
Physarum add-on, so the two cannot disagree about what option 3 means. Only the start list differs
(the clock digit start is gone). Run: python3 tools/make_settings_physarum_lite.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock'))
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from make_settings_physarum import (AGENTS, CAMERAS, FOODS, MODES, PRESETS, SCREEN_FX, SPEEDS,  # noqa: E402
                                    TRAILS, VIEWS, count_text)

from resources.lib import config  # noqa: E402

ADDON_ID = 'screensaver.physarum.lite.armv7'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))

# The original start list without "From the clock digits" (index 5); the species-third start moves
# into that slot. The shader's init pass in physarum_lite_app.cpp matches this order.
LITE_STARTS = ['Everywhere at random', 'A disc in the middle (it grows outwards)', 'A ring, facing inwards',
               'Scattered colonies', 'Big bang (all from the centre, facing out)',
               'Each species in its own third of the screen']


def categories():
    O, S, B, C = config.O, config.S, config.B, config.C
    custom = len(PRESETS)
    is_custom = ('preset', str(custom))
    first = PRESETS[0][1]
    return [
        ('Behaviour', [
            O('preset', 'Behaviour', 0, [p[0] for p in PRESETS] + ['Custom (set below)']),
            O('species', 'Species', 0, ['1', '2 (they avoid each other)', '3 (they avoid each other)']),
            B('species_differ', 'Each species behaves a little differently', True, visible=('species', '!', '0')),
            S('scale', 'Pattern scale (%)', 100, 40, 300, 10),
            S('sa', 'Sensor angle (degrees)', int(first['sa']), 5, 120, 1, visible=is_custom),
            S('ra', 'Turn angle (degrees)', int(first['ra']), 5, 120, 1, visible=is_custom),
            S('so', 'Sensor distance (px)', first['so'], 1, 60, 1, visible=is_custom),
            S('ss', 'Step (tenths of a px)', first['ss'], 2, 50, 1, visible=is_custom),
            S('decay', 'Trail kept per step (%)', first['decay'], 70, 99, 1, visible=is_custom),
            S('diffuse', 'Diffusion (%)', first['diffuse'], 0, 100, 5, visible=is_custom),
            S('deposit', 'Deposit', first['deposit'], 5, 100, 5, visible=is_custom),
            S('jitter', 'Random wobble (degrees)', first['jitter'], 0, 45, 1, visible=is_custom),
            S('repel', 'How much species avoid each other (%)', first['repel'], 0, 100, 10, visible=is_custom),
        ]),
        ('Size and speed', [
            O('agents', 'Agents', 1, [count_text(w, h) for w, h in AGENTS]),
            O('trail', 'Trail map resolution', 0, ['%d x %d' % t for t in TRAILS]),
            O('speed', 'Steps per second', 1, ['%d' % s for s in SPEEDS] + ['Maximum (as many as the device can do)']),
        ]),
        ('Start and food', [
            O('start', 'Starting pattern', 0, LITE_STARTS),
            O('food', 'Food', 0, FOODS),
            S('food_nodes', 'Food sources', 12, 3, 40, 1, visible=('food', '1')),
        ]),
        ('Colours', [
            O('colour_mode', 'Colour', 0, MODES),
            O('palette', 'Palette', 0, config.PALETTE_NAMES),
            C('colour', 'Colour of the slime', 'FFFFD36B', visible=('colour_mode', '5')),
            C('background', 'Background', 'FF000000'),
            S('brightness', 'Brightness (%)', 100, 30, 300, 10),
            S('cycle', 'Colour cycling speed', 20, 0, 100, 5),
            S('glow', 'Glow (costs speed)', 0, 0, 100, 10),
            O('screen_fx', 'Screen effect', 0, SCREEN_FX),
            S('dim', 'Dim (%)', 0, 0, 80, 10),
        ]),
        ('Camera and 3D', [
            O('view', 'View', 0, VIEWS),
            O('camera', 'Camera', 0, CAMERAS),
            S('camera_speed', 'Camera speed', 30, 5, 100, 5),
            S('zoom', 'Deepest zoom (x)', 3, 1, 12, 1),
        ]),
    ]


if __name__ == '__main__':
    os.makedirs(os.path.join(ROOT, 'resources'), exist_ok=True)
    write(ROOT, ADDON_ID, 'Physarum Lite', categories(), 'tools/make_settings_physarum_lite.py')

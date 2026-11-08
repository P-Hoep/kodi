"""Generate the Physarum Lite screensaver's settings.xml and strings.po from one table.

Physarum Lite is the Physarum simulation with every timer removed: no restart every so many
minutes and no wandering between behaviours. What is left is the agent model and its drawing,
running continuously, plus an optional clock in the middle. The clock is off by default; while it
is off nothing about it runs (no font is loaded, no clock texture is made and the shaders take
their ordinary path), so the add-on is as light as it was before the clock was added. It is meant
for low-resource devices, so its defaults are light: 16 thousand agents on a 480 x 270 trail, no
glow, no screen effect, and one simulation step on every displayed frame (which is what keeps the
frame rate even: every frame costs the same). The scene itself is drawn at twice the trail
resolution and scaled up, so the draw pass costs a fraction of a screen-sized one whatever the
output.

It shares the behaviour, agent-size, food, clock, colour, view and camera lists with the Physarum
add-on, so the two cannot disagree about what option 3 means. The start list differs (the clock
digit start is appended at the end), the step rate is frames per step instead of steps per second,
and one 320 x 180 trail map is added below the shared list for very weak GPUs. Run:
python3 tools/make_settings_physarum_lite.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock'))
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from make_settings_physarum import (AGENTS, CAMERAS, CLOCKS, FOODS, MODES, PRESETS, SCREEN_FX, TRAILS,  # noqa: E402
                                    VIEWS, count_text)

from resources.lib import config  # noqa: E402

ADDON_ID = 'screensaver.physarum.lite.armv7'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))

# The original start list without "From the clock digits" (its index 5), with the species-third
# start moved into that slot and the clock start appended at the end. The shader's init pass in
# physarum_lite_app.cpp matches this order, and appending keeps every saved index meaningful.
LITE_STARTS = ['Everywhere at random', 'A disc in the middle (it grows outwards)', 'A ring, facing inwards',
               'Scattered colonies', 'Big bang (all from the centre, facing out)',
               'Each species in its own third of the screen', 'From the clock digits']

# The shared trail list plus one smaller map for very weak GPUs, appended so that the shared
# indices keep their meaning (a saved trail index must not change resolution on an update). The
# shader-side list is LITE_TRAIL_SIZES in physarum_lite.hpp; keep the two in step.
LITE_TRAILS = TRAILS + [(320, 180)]


def categories():
    O, S, B, C = config.O, config.S, config.B, config.C
    custom = len(PRESETS)
    is_custom = ('preset', str(custom))
    first = PRESETS[0][1]
    clock_on = ('clock', '!', '0')
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
            O('agents', 'Agents', 0, [count_text(w, h) for w, h in AGENTS]),
            O('trail', 'Trail map resolution', 0, ['%d x %d' % t for t in LITE_TRAILS]),
            # One step per displayed frame costs the same on every frame, so the frame rate stays
            # even. A steps-per-second setting would make some frames twice as heavy as others.
            O('pace', 'Simulation updates', 0, ['Every frame (smoothest)', 'Every other frame',
                                                'Every third frame', 'Every fourth frame']),
        ]),
        ('Start and food', [
            O('start', 'Starting pattern', 0, LITE_STARTS),
            O('food', 'Food', 0, FOODS),
            S('food_nodes', 'Food sources', 12, 3, 40, 1, visible=('food', '1')),
        ]),
        ('Clock', [
            # Off by default: the add-on does no clock work at all until this is not "Off".
            O('clock', 'Clock in the middle', 0, CLOCKS),
            S('food_strength', 'How strongly the digits draw the slime (%)', 50, 10, 100, 10, visible=clock_on),
            O('clock_font', 'Font', 0, [f[0] for f in config.FONTS], visible=clock_on),
            O('clock_weight', 'Weight', 2, config.WEIGHTS, visible=clock_on),
            B('seconds', 'Show seconds', False, visible=clock_on),
            O('hours', 'Hours', 0, ['24 hour (17:52)', '12 hour (5:52)'], visible=clock_on),
            S('clock_size', 'Clock width (% of the screen)', 60, 20, 90, 5, visible=clock_on),
            O('clock_colour_mode', 'Clock colour (when drawn on top)', 0, ['White', 'Follows the palette', 'One colour'],
              visible=clock_on),
            C('clock_colour', 'Colour of the clock', 'FFFFFFFF', visible=('clock_colour_mode', '2')),
            S('clock_opacity', 'Clock opacity (%)', 85, 10, 100, 5, visible=clock_on),
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

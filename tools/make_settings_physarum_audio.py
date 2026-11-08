"""Generate the Physarum Visualisation add-on's settings.xml and strings.po from one table.

This is Physarum Lite as a music visualisation: the same agent model and drawing, with no clock,
no timers and the whole simulation driven by what Kodi is playing. The analyser (audio_react.cpp)
turns Kodi's 44.1 kHz stereo float samples into an overall level, five bands, a beat impulse and a
32-band spectrum; the simulation moves faster and deposits more on loud music and beats, and the
draw pass brightens, pulses the zoom, sends a ring across the screen on every beat, drifts the
palette and shows the spectrum if asked.

It shares the behaviour, agent-size, food, colour, view and camera lists with Physarum Lite, so
the two cannot disagree about what option 3 means. The start list is Lite's without "From the
clock digits", and the music settings are new. Run:
python3 tools/make_settings_physarum_audio.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock'))
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from make_settings_physarum import (AGENTS, CAMERAS, FOODS, MODES, PRESETS, SCREEN_FX, TRAILS, VIEWS,  # noqa: E402
                                    count_text)
from make_settings_physarum_lite import LITE_STARTS  # noqa: E402

from resources.lib import config  # noqa: E402

ADDON_ID = 'visualization.physarum.lite'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))

# Lite's start list without "From the clock digits"; the init pass in physarum_audio_app.cpp
# matches this order.
STARTS = LITE_STARTS[:-1]

# The shared trail list plus the small map for very weak GPUs (AUDIO_TRAIL_SIZES in
# physarum_audio.hpp; keep the two in step).
TRAILS_EXTRA = TRAILS + [(320, 180)]


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
        ('Music', [
            S('reactivity', 'Reactivity to the music (%)', 70, 0, 150, 5),
            S('sensitivity', 'Sensitivity (automatic gain, %)', 100, 50, 200, 5),
            B('react_speed', 'Loud passages make the agents move faster', True),
            B('react_trails', 'Bass makes the trails stronger and longer-lasting', True),
            B('react_beat', 'Beats pulse the zoom and send a ring across the screen', True),
            B('react_colour', 'The colours drift with the music', True),
            S('beat_zoom', 'Zoom pulse on a beat (%)', 8, 0, 25, 1, visible=('react_beat', 'true')),
            S('beat_wave', 'Strength of the beat ring (%)', 60, 0, 100, 5, visible=('react_beat', 'true')),
            O('spectrum', 'Show the spectrum', 1, ['Off', 'Bars along the bottom', 'A ring around the edge']),
        ]),
        ('Size and speed', [
            O('agents', 'Agents', 0, [count_text(w, h) for w, h in AGENTS]),
            O('trail', 'Trail map resolution', 0, ['%d x %d' % t for t in TRAILS_EXTRA]),
            # One step per displayed frame costs the same on every frame, so the frame rate stays
            # even. A steps-per-second setting would make some frames twice as heavy as others.
            O('pace', 'Simulation updates', 0, ['Every frame (smoothest)', 'Every other frame',
                                                'Every third frame', 'Every fourth frame']),
        ]),
        ('Start and food', [
            O('start', 'Starting pattern', 0, STARTS),
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
    write(ROOT, ADDON_ID, 'Physarum Visualisation', categories(), 'tools/make_settings_physarum_audio.py')

"""Generate the Physarum v2 screensaver's settings.xml and strings.po from one table, so the Kodi
settings and screensaver.physarum_v2/src/ScreensaverPhysarum.cpp agree on option indices.

Run (writes both add-ons):
  python3 tools/make_settings_physarum_v2.py

Physarum v2 runs the slime mould on the CPU (Physarum.h) instead of the GPU. The 32-bit Android
build gets lighter defaults (fewer agents, a smaller trail map).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402

B = lambda sid, label, default, **kw: dict(id=sid, type='boolean', label=label, default=default, **kw)
I = lambda sid, label, default, lo, hi, step=1, **kw: dict(
    id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)
O = lambda sid, label, default, options, **kw: dict(
    id=sid, type='options', label=label, default=default, options=options, **kw)
C = lambda sid, label, default, **kw: dict(id=sid, type='colour', label=label, default=default, **kw)

# Index orders are read by LoadSettings() in ScreensaverPhysarum.cpp (kPresets in Presets.h,
# the Start enum in Physarum.h, the Mode / Pace enums and the k* lists in the wrapper).
PRESETS = ['Transport network (Jones)', 'Fine web', 'Double-veined cells', 'Coarse veins (long sensors)',
           'Honeycomb', 'Labyrinth (squiggles)', 'Worms', 'Spots and comets',
           'Foam (turns wider than the sensors)', 'Long threads (fast agents)', 'Restless (jittery agents)',
           'A different one at every restart', 'Custom (set below)']
SPECIES = ['1', '2 (they avoid each other)', '3 (they avoid each other)']
STARTS = ['Everywhere at random', 'A disc in the middle (it grows outwards)', 'A ring, facing inwards',
          'Scattered colonies', 'Big bang (all from the centre, facing out)',
          'Each species in its own third of the screen']
RESTARTS = ['Never', '2 minutes', '5 minutes', '10 minutes', '20 minutes', '30 minutes', '60 minutes']
MODES = ['Palette (by density; one colour per species)', 'Neon (white-hot cores)', 'Fire', 'One colour']
PALETTES = ['Neon', 'Desert sand', 'Ocean', 'Sunset', 'Candy', 'Forest', 'Ice', 'Greyscale']
AGENTS = ['25 thousand', '50 thousand', '100 thousand', '150 thousand', '250 thousand', '500 thousand',
          '1 million']
TRAILS = ['320 x 180', '480 x 270', '640 x 360', '800 x 450', '960 x 540', '1280 x 720', '1920 x 1080']
PACES = ['Normal (60 steps a second: one per frame on a 60 Hz TV)', 'Fast (120 steps a second)',
         'Slow (30 steps a second, half the CPU)']
THREADS = ['Automatic (one per core but one, up to 4)', '1', '2', '3', '4']

CUSTOM = ('preset', str(len(PRESETS) - 1))


def categories(low_power):
    return [
        ('Behaviour', [
            O('preset', 'Behaviour', 0, PRESETS),
            O('species', 'Species', 0, SPECIES),
            B('species_differ', 'Each species behaves a little differently', True, visible=('species', '!', '0')),
            I('scale', 'Pattern scale (%)', 100, 40, 300, 10),
            I('sa', 'Sensor angle (degrees)', 22, 5, 120, visible=CUSTOM),
            I('ra', 'Turn angle (degrees)', 45, 5, 120, visible=CUSTOM),
            I('so', 'Sensor distance (px of a 960 px map)', 9, 1, 60, visible=CUSTOM),
            I('ss', 'Step (tenths of a px)', 10, 2, 50, visible=CUSTOM),
            I('decay', 'Trail kept per step (%)', 90, 70, 99, visible=CUSTOM),
            I('diffuse', 'Diffusion (%)', 100, 0, 100, 5, visible=CUSTOM),
            I('deposit', 'Deposit', 30, 5, 100, 5, visible=CUSTOM),
            I('jitter', 'Wobble (degrees)', 0, 0, 45, visible=CUSTOM),
            I('repel', 'Avoid the other species (%)', 50, 0, 100, 10, visible=CUSTOM),
        ]),
        ('Start', [
            O('start', 'Starting pattern', 0, STARTS),
            O('restart', 'Start over every', 3, RESTARTS),
        ]),
        ('Colours', [
            O('colour_mode', 'Colour', 0, MODES),
            O('palette', 'Palette', 0, PALETTES),
            C('colour', 'Colour of the slime', 'FFFFD36B', visible=('colour_mode', '3')),
            C('background', 'Background', 'FF000000'),
            I('brightness', 'Brightness (%)', 100, 30, 300, 10),
            I('cycle', 'Colour cycling speed', 20, 0, 100, 5),
            I('dim', 'Dim (%)', 0, 0, 80, 10),
        ]),
        ('Performance', [
            O('agents', 'Agents', 3 if low_power else 4, AGENTS),
            O('trail', 'Trail map resolution', 2 if low_power else 4, TRAILS),
            O('pace', 'Speed', 0, PACES),
            O('threads', 'Simulation threads', 0, THREADS),
        ]),
    ]


if __name__ == '__main__':
    for addon_id, name, low in (('screensaver.physarum_v2', 'Physarum v2 (OpenGL)', False),
                                ('screensaver.physarum_v2.armv7', 'Physarum v2 (OpenGL, 32-bit Android)', True)):
        root = os.path.normpath(os.path.join(HERE, '..', addon_id))
        os.makedirs(os.path.join(root, 'resources'), exist_ok=True)
        write(root, addon_id, name, categories(low), 'tools/make_settings_physarum_v2.py')

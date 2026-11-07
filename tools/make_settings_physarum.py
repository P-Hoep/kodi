"""Generate the Physarum screensaver's settings.xml, strings.po and its C++ tables
(screensaver.sandclock.gl/src/physarum_tables.hpp) from one table, so the Kodi settings and the
code cannot disagree about what option 3 means.

The model is Jeff Jones's agent approximation of Physarum polycephalum transport networks
(Artificial Life 16(2), 2010) as Sage Jenson draws it: each agent senses the trail ahead, ahead-left
and ahead-right, turns towards the strongest, moves and deposits; the trail diffuses and decays.

Run: python3 tools/make_settings_physarum.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock'))
GL = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock.gl'))
ADDON_ID = 'screensaver.physarum.armv7'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from resources.lib import config  # noqa: E402

# Behaviours, in the units of the Custom sliders: sensor angle and turn (degrees), sensor distance
# (px of a 960 px wide trail), step (tenths of a px), decay (% kept per step), diffusion (%),
# deposit, jitter (degrees of random wobble), repel (how much a species avoids the others, %).
PRESET_KEYS = ['sa', 'ra', 'so', 'ss', 'decay', 'diffuse', 'deposit', 'jitter', 'repel']
PRESETS = [
    ('Transport network (Jones: SA 22.5, RA 45, SO 9)', dict(sa=22.5, ra=45, so=9, ss=10, decay=90, diffuse=100, deposit=30, jitter=0, repel=50)),
    ('Fine web (Sage Jenson style)', dict(sa=20, ra=10, so=15, ss=10, decay=70, diffuse=0, deposit=30, jitter=0, repel=50)),
    ('Double-veined cells', dict(sa=45, ra=9, so=30, ss=15, decay=90, diffuse=30, deposit=30, jitter=0, repel=50)),
    ('Coarse veins (long sensors)', dict(sa=22.5, ra=45, so=24, ss=12, decay=92, diffuse=100, deposit=30, jitter=2, repel=50)),
    ('Honeycomb', dict(sa=60, ra=30, so=14, ss=10, decay=94, diffuse=60, deposit=30, jitter=0, repel=50)),
    ('Labyrinth (squiggles)', dict(sa=45, ra=22.5, so=7, ss=8, decay=88, diffuse=100, deposit=30, jitter=0, repel=50)),
    ('Worms', dict(sa=45, ra=45, so=3, ss=10, decay=90, diffuse=100, deposit=30, jitter=0, repel=50)),
    ('Spots and comets', dict(sa=90, ra=10, so=15, ss=10, decay=90, diffuse=50, deposit=30, jitter=0, repel=50)),
    ('Foam (turns wider than the sensors)', dict(sa=15, ra=120, so=10, ss=20, decay=93, diffuse=60, deposit=30, jitter=0, repel=50)),
    ('Long threads (fast agents)', dict(sa=30, ra=30, so=8, ss=40, decay=90, diffuse=50, deposit=30, jitter=0, repel=50)),
    ('Restless (jittery agents)', dict(sa=35, ra=35, so=18, ss=18, decay=93, diffuse=70, deposit=30, jitter=25, repel=40)),
]
AGENTS = [(128, 128), (256, 256), (512, 256), (512, 512), (1024, 512), (1024, 1024), (2048, 1024),
          (2048, 2048), (4096, 2048)]                                 # agent texture sizes
TRAILS = [(480, 270), (640, 360), (960, 540), (1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)]
SPEEDS = [15, 30, 60, 90, 120, 240, 480]                              # steps per second; then Maximum
RESTARTS = [0, 2, 5, 10, 20, 30, 60]                                  # minutes; 0 = never
WANDERS = [1, 2, 3, 5, 10]                                            # minutes per behaviour
STARTS = ['Everywhere at random', 'A disc in the middle (it grows outwards)', 'A ring, facing inwards',
          'Scattered colonies', 'Big bang (all from the centre, facing out)', 'From the clock digits',
          'Each species in its own third of the screen']
FOODS = ['None', 'Scattered food (the network links them, as in the Tokyo rail experiment)',
         'A ring of food', 'A grid of food']
CLOCKS = ['Off', 'On top', 'The slime grows into the digits', 'Grows into the digits, with the clock faintly on top',
          'Made of slime (kept inside the digits)', 'The network flows around the digits']
MODES = ['Density (palette gradient)', 'Species colours (palette)', 'Fire', 'Neon (white-hot cores)',
         'Ink on paper', 'One colour', 'Rainbow (drifts across the screen)', 'Plasma (a moving colour field)']
VIEWS = ['Flat', 'Relief (lit, embossed)', 'Landscape (flying over it)', 'Tunnel (flying through it)',
         'Globe (a spinning planet)']
CAMERAS = ['Still', 'Drift', 'Zoom in and out', 'Fly through (drift, zoom and turn)']
SCREEN_FX = ['None', 'Vignette', 'CRT (scanlines and vignette)']


def count_text(w, h):
    n = w * h
    if n >= 1000000:
        text = '%.1f million' % (n / 1048576.0)
    else:
        text = '%d thousand' % round(n / 1024.0)
    if n >= 4096 * 2048:
        text += ', insane'
    elif n >= 2048 * 2048:
        text += ', very heavy'
    return text


def categories():
    O, S, B, C = config.O, config.S, config.B, config.C
    custom = len(PRESETS) + 1
    is_custom = ('preset', str(custom))
    first = PRESETS[0][1]
    clock_on = ('clock', '!', '0')
    return [
        ('Clock', [
            O('clock', 'Clock in the middle', 2, CLOCKS),
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
        ('Behaviour', [
            O('preset', 'Behaviour', len(PRESETS), [p[0] for p in PRESETS] +
              ['Wander through all of them', 'Custom (set below)']),
            O('wander_minutes', 'Change behaviour every', 1, ['%d minute%s' % (m, '' if m == 1 else 's') for m in WANDERS],
              visible=('preset', str(len(PRESETS)))),
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
            O('agents', 'Agents', 3, [count_text(w, h) for w, h in AGENTS]),
            O('trail', 'Trail map resolution', 2, ['%d x %d' % t for t in TRAILS]),
            O('speed', 'Steps per second', 2, ['%d' % s for s in SPEEDS] + ['Maximum (as many as the device can do)']),
        ]),
        ('Start and food', [
            O('start', 'Starting pattern', 0, STARTS),
            O('food', 'Food', 0, FOODS),
            S('food_nodes', 'Food sources', 12, 3, 40, 1, visible=('food', '1')),
            O('restart_every', 'Start over every', 3,
              ['Never'] + ['%d minutes' % m for m in RESTARTS[1:]]),
        ]),
        ('Colours', [
            O('colour_mode', 'Colour', 0, MODES),
            O('palette', 'Palette', 0, config.PALETTE_NAMES),
            C('colour', 'Colour of the slime', 'FFFFD36B', visible=('colour_mode', '5')),
            C('background', 'Background', 'FF000000'),
            S('brightness', 'Brightness (%)', 100, 30, 300, 10),
            S('cycle', 'Colour cycling speed', 20, 0, 100, 5),
            S('glow', 'Glow (costs speed)', 40, 0, 100, 10),
            O('screen_fx', 'Screen effect', 1, SCREEN_FX),
            S('dim', 'Dim (%)', 0, 0, 80, 10),
        ]),
        ('Camera and 3D', [
            O('view', 'View', 0, VIEWS),
            O('camera', 'Camera', 0, CAMERAS),
            S('camera_speed', 'Camera speed', 30, 5, 100, 5),
            S('zoom', 'Deepest zoom (x)', 3, 1, 12, 1),
        ]),
    ]


def write_tables(path):
    presets = ',\n'.join('    {"%s", %s}' % (n.replace('"', ''), ', '.join('%.2ff' % p[k] for k in PRESET_KEYS))
                         for n, p in PRESETS)
    agents = ', '.join('{%d, %d}' % a for a in AGENTS)
    trails = ', '.join('{%d, %d}' % t for t in TRAILS)
    speeds = ', '.join(str(s) for s in SPEEDS) + ', -1'
    restarts = ', '.join(str(r) for r in RESTARTS)
    wanders = ', '.join(str(w) for w in WANDERS)
    pal = ',\n'.join('    {%s}' % ', '.join('0x' + c for c in colours) for _name, colours in config.PALETTES)
    with open(path, 'w') as f:
        f.write('''// Generated by tools/make_settings_physarum.py; edit the table there.
#pragma once
#include <cstdint>

namespace sandclock {
namespace physarum {

// sa, ra: degrees; so: px of a 960 px wide trail; ss: tenths of a px; decay: %% kept per step;
// diffuse: %%; deposit; jitter: degrees; repel: %%.
struct PresetDef { const char* name; float sa, ra, so, ss, decay, diffuse, deposit, jitter, repel; };
constexpr PresetDef PRESETS[] = {
%s
};
constexpr int PRESET_COUNT = %d;               // PRESET_COUNT = wander, PRESET_COUNT + 1 = custom
struct Size { int w, h; };
constexpr Size AGENT_SIZES[] = {%s};
constexpr int AGENT_COUNT = %d;
constexpr Size TRAIL_SIZES[] = {%s};
constexpr int TRAIL_COUNT = %d;
constexpr int SPEED_SPS[] = {%s};              // steps per second; -1 = maximum
constexpr int SPEED_COUNT = %d;
constexpr int RESTART_MINUTES[] = {%s};        // 0 = never
constexpr int RESTART_COUNT = %d;
constexpr int WANDER_MINUTES[] = {%s};
constexpr int WANDER_COUNT = %d;
constexpr int START_COUNT = %d;
constexpr int FOOD_COUNT = %d;
constexpr int CLOCK_COUNT = %d;
constexpr int MODE_COUNT = %d;
constexpr int VIEW_COUNT = %d;
constexpr int CAMERA_COUNT = %d;
constexpr uint32_t PALETTE[][7] = {
%s
};
constexpr int PALETTE_COUNT = %d;

}  // namespace physarum
}  // namespace sandclock
''' % (presets, len(PRESETS), agents, len(AGENTS), trails, len(TRAILS), speeds, len(SPEEDS) + 1, restarts,
       len(RESTARTS), wanders, len(WANDERS), len(STARTS), len(FOODS), len(CLOCKS), len(MODES), len(VIEWS),
       len(CAMERAS), pal, len(config.PALETTES)))


if __name__ == '__main__':
    os.makedirs(os.path.join(ROOT, 'resources'), exist_ok=True)
    write(ROOT, ADDON_ID, 'Physarum', categories(), 'tools/make_settings_physarum.py')
    write_tables(os.path.join(GL, 'src', 'physarum_tables.hpp'))

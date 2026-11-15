"""Generate the Sand Clock v2 screensaver's settings.xml and strings.po from one table, so the Kodi
settings and screensaver.sandclock_v2/src/ScreensaverSandClock.cpp agree on option indices.

Run (writes both add-ons):
  python3 tools/make_settings_sandclock_v2.py

Sand Clock v2 runs a granular sand simulation or a melting liquid clock on the CPU. The 32-bit
Android build gets lighter defaults (fewer, bigger grains).
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

# Index orders are read by LoadSettings() in ScreensaverSandClock.cpp (the k* lists there, the
# enums in Sand.h, Liquid.h and Colours.h, and the fonts in tools/make_sandclock_v2_fonts.py).
MODES = ['Sand (grains pour, pile up and crumble)', 'Liquid (the digits melt)']
FONTS = ['Modern sans: Inter', 'Geometric: Montserrat', 'Digital: Orbitron', 'Pixel: Pixelify Sans',
         'Dot matrix: Doto', 'Monospace: JetBrains Mono', 'Rounded: Comfortaa', 'Serif: Playfair Display',
         'Stencil: Big Shoulders']
WEIGHTS = ['Regular', 'Bold']
POSITIONS = ['Near the top', 'Upper third', 'Middle']
NEW_DIGITS = ['Poured in from the top', 'Built up in place']
CRUMBLE = ['From the bottom up', 'All at once', 'Dissolving grain by grain']
GRAINS = ['Big (180 rows)', 'Medium (216 rows)', 'Fine (270 rows)', 'Very fine (360 rows)']
VISCOSITY = ['Water', 'Oil', 'Syrup', 'Honey']
MELT = ['Dripping from the bottom', 'Slumping all at once', 'Running down from the top']
SLOSH = ['Still', 'Gently rocking', 'Sloshing']
DETAIL = ['Low (54 rows)', 'Normal (72 rows)', 'High (90 rows)', 'Very high (108 rows)']
COLOUR_MODES = ['A new colour from the palette for every change', 'Each digit keeps its own colour',
                'One colour', 'Rainbow (the hue walks round every two minutes)']
PALETTES = ['Neon', 'Desert sand', 'Ocean', 'Sunset', 'Candy', 'Forest', 'Ice', 'Greyscale']
THREADS = ['Automatic (one per core but one, up to 4)', '1', '2', '3', '4']

SAND = ('mode', '0')
LIQUID = ('mode', '1')


def categories(low_power):
    return [
        ('Clock', [
            O('mode', 'Clock made of', 0, MODES),
            B('seconds', 'Show seconds', True),
            B('twelve_hour', '12-hour clock', False),
            O('font', 'Font', 0, FONTS),
            O('weight', 'Weight', 1, WEIGHTS),
            I('size', 'Size (% of the screen width)', 80, 30, 100, 5),
            O('position', 'Position', 1, POSITIONS),
        ]),
        ('Sand', [
            O('new_digits', 'New digits', 0, NEW_DIGITS, visible=SAND),
            O('crumble', 'Old digits crumble', 0, CRUMBLE, visible=SAND),
            B('sand_whole', 'The whole clock crumbles when the minute changes', False, visible=SAND),
            O('grain', 'Grain size', 1 if low_power else 2, GRAINS, visible=SAND),
            I('sand_gravity', 'Gravity (%)', 100, 50, 200, 25, visible=SAND),
            I('pile', 'Height of the pile (% of the screen)', 20, 5, 35, 5, visible=SAND),
            B('round', 'Round grains (when they are big enough to see)', True, visible=SAND),
        ]),
        ('Liquid', [
            O('viscosity', 'Liquid', 1, VISCOSITY, visible=LIQUID),
            O('melt', 'Old digits melt', 0, MELT, visible=LIQUID),
            B('liquid_whole', 'The whole clock melts when the minute changes', False, visible=LIQUID),
            B('drips', 'Standing digits drip now and then', True, visible=LIQUID),
            O('slosh', 'Pool', 1, SLOSH, visible=LIQUID),
            I('pool', 'Depth of the pool (% of the screen)', 20, 10, 35, 5, visible=LIQUID),
            O('detail', 'Detail', 1, DETAIL, visible=LIQUID),
        ]),
        ('Colours', [
            O('colour_mode', 'Colours', 0, COLOUR_MODES),
            O('palette', 'Palette', 1, PALETTES,
              visible='<dependencies><dependency type="visible"><and>'
                      '<condition setting="colour_mode" operator="!is">2</condition>'
                      '<condition setting="colour_mode" operator="!is">3</condition>'
                      '</and></dependency></dependencies>'),
            C('colour', 'Colour', 'FFE8C27A', visible=('colour_mode', '2')),
            C('background', 'Background', 'FF0A0910'),
            I('dim', 'Dim (%)', 0, 0, 80, 10),
        ]),
        ('Performance', [
            O('threads', 'Simulation threads', 0, THREADS),
        ]),
    ]


if __name__ == '__main__':
    for addon_id, name, low in (('screensaver.sandclock_v2', 'Sand Clock v2 (OpenGL)', False),
                                ('screensaver.sandclock_v2.armv7', 'Sand Clock v2 (OpenGL, 32-bit Android)', True)):
        root = os.path.normpath(os.path.join(HERE, '..', addon_id))
        os.makedirs(os.path.join(root, 'resources'), exist_ok=True)
        write(root, addon_id, name, categories(low), 'tools/make_settings_sandclock_v2.py')

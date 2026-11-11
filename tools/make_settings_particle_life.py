"""Generate the Particle Life (OpenGL) screensaver's settings.xml and strings.po from one table, so
the Kodi settings and screensaver.sandclock.gl/src/kodi_particle_life.cpp cannot disagree about
what option 2 means.

Run:
  python3 tools/make_settings_particle_life.py
  python3 tools/make_settings_particle_life.py screensaver.particlelife.gl.armv7 \
      'Particle Life (OpenGL, 32-bit Android)' low

The optional third argument 'low' makes the 32-bit build's defaults lighter: 2,048 particles
instead of 4,096, a smaller interaction radius, and the scene drawn at 720p before scaling up.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ID = sys.argv[1] if len(sys.argv) > 1 else 'screensaver.particlelife.gl'
NAME = sys.argv[2] if len(sys.argv) > 2 else 'Particle Life (OpenGL)'
LOW_POWER = len(sys.argv) > 3 and sys.argv[3] == 'low'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402

B = lambda sid, label, default, **kw: dict(id=sid, type='boolean', label=label, default=default, **kw)
I = lambda sid, label, default, lo, hi, step=1, **kw: dict(
    id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)
O = lambda sid, label, default, options, **kw: dict(
    id=sid, type='options', label=label, default=default, options=options, **kw)

# Order matches only the *names used in settings.xml*; the numbers come from
# screensaver.sandclock.gl/src/particle_life_tables.hpp at run time.
PRESETS = ['DNA', 'Worm', 'Waves', 'Soap', 'Photon', 'Ladybug', 'Flower', 'Cells', 'Vacuum', 'Y']
STARTS = ['Scattered', 'Disk', 'Ring', 'Species clusters', 'Grid', 'Two blobs']
PALETTES = ['Neon', 'Ocean', 'Sunset', 'Forest', 'Candy', 'Ice', 'Fire', 'Mono']
COLOURS = ['By species', 'By speed (heat)', 'Shimmering']
PARTICLES = ['1,024', '2,048', '3,072', '4,096', '6,144', '8,192',
             '12,288', '16,384', '24,576', '32,768']
SPEEDS = ['30 steps/s', '45 steps/s', '60 steps/s', '90 steps/s',
          '120 steps/s', '180 steps/s', 'Maximum (as many as the device can do)']
RESTARTS = ['Never', '1 minute', '2 minutes', '5 minutes', '10 minutes',
            '20 minutes', '30 minutes', '60 minutes']
EVOLVES = ['Never', 'Every 30 seconds', 'Every minute', 'Every 2 minutes',
           'Every 5 minutes', 'Every 10 minutes', 'Every 30 minutes']
DRAWS = ['Automatic (up to 1080p)', 'Up to 1080p (sharpest)', 'Up to 720p',
         'Up to 540p', 'Up to 360p (softest, fastest)',
         'Full screen (every output pixel, the heaviest)']
VARY = ['Same rules and look every time',
        'New interaction rules each time',
        'New rules, colours and layout each time']

PARTICLE_DEFAULT = 1 if LOW_POWER else 3
RADIUS_DEFAULT = 10 if LOW_POWER else 12
DRAW_DEFAULT = 2 if LOW_POWER else 0
SIZE_DEFAULT = 70 if LOW_POWER else 65
TRAIL_DEFAULT = 45 if LOW_POWER else 50


def categories():
    return [
        ('Rules', [
            O('matrix_mode', 'How the rules are chosen', 0,
              ['Preset (choose below)', 'Custom (type the matrix below)',
               'A new random matrix every start']),
            O('preset', 'Preset', 0, PRESETS, visible=('matrix_mode', '0')),
            dict(id='custom_matrix',
                 type='string',
                 label='Custom matrix (row by row; positive attracts, negative repels)',
                 default='0.37,-0.50,-0.10,0.25,0.36,-0.71,0.37,0.09,'
                         '-0.66,0.12,-0.50,0.71,-0.37,0.08,-0.65,0.24',
                 visible=('matrix_mode', '1')),
            I('species', 'Species (for custom and random rules)', 6, 2, 8,
              visible=('matrix_mode', '!', '0')),
            I('radius', 'Interaction radius (% of the screen height)', RADIUS_DEFAULT, 4, 24),
            I('force', 'Force strength (%)', 70, 10, 200, 5),
            I('friction', 'Damping (%)', 30, 0, 100, 5),
            B('wrap', 'Wrap around the edges (a torus)', True),
        ]),
        ('Particles and movement', [
            O('particles', 'Particles', PARTICLE_DEFAULT, PARTICLES),
            O('speed', 'Simulation speed', 2, SPEEDS),
            O('start', 'Starting arrangement', 0, STARTS),
        ]),
        ('Look', [
            O('palette', 'Palette', 0, PALETTES),
            O('colour_mode', 'Colour', 0, COLOURS),
            I('size', 'Particle size (%)', SIZE_DEFAULT, 10, 100),
            I('glow', 'Glow halo (%)', 60, 0, 100, 5),
            I('trail', 'Trails (how long the glow lingers, %)', TRAIL_DEFAULT, 0, 100, 5),
            dict(id='background', type='colour', label='Background', default='FF05060A'),
            I('dim', 'Dim the picture (%)', 0, 0, 80, 10),
        ]),
        ('Start and evolve', [
            O('vary', 'When it starts over', 0, VARY),
            O('restart', 'Start over every', 3, RESTARTS),
            O('evolve', 'Nudge the rules every', 0, EVOLVES),
            dict(id='seed_text', type='string',
                 label='Seed (blank = different every start)', default=''),
        ]),
        ('Performance', [
            # The CPU cost follows particles x neighbours, so the particle count and the radius
            # matter most; this setting bounds only the drawing.
            O('draw', 'Draw the scene at', DRAW_DEFAULT, DRAWS),
        ]),
    ]


if __name__ == '__main__':
    os.makedirs(os.path.join(ROOT, 'resources'), exist_ok=True)
    write(ROOT, ADDON_ID, NAME, categories(), 'tools/make_settings_particle_life.py')

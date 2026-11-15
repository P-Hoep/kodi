"""Generate the EvolveLife screensaver's settings.xml and strings.po from one table, so the Kodi
settings and screensaver.evolvelife/src/ScreensaverEvolveLife.cpp agree on option indices.

Run (writes both add-ons):
  python3 tools/make_settings_evolvelife.py

The 32-bit Android build defaults to the Low profile.
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

# Index order is read by LoadSettings() in ScreensaverEvolveLife.cpp: PROFILE is Profile (Smooth = Low evolution with
# the Smooth quality), QUALITY 4 is Smooth, GOALS is
# 0 = random then evo::Goal + 1, CAMERA is evo::CameraMode, INSIGHT is evo::InsightLevel, PALETTE is
# evo::PaletteId, LOG is LogLevel; the other lists index the tables next to them in LoadSettings().
PROFILE = ['Automatic (by device)', 'Low (TV sticks, Raspberry Pi 4)', 'Balanced (typical HTPC, Shield)',
           'High (desktop)', 'Smooth (weakest devices: 4 creatures, lighter drawing)']
POPULATION = ['Automatic (by profile)', '24', '40', '60', '100', '150', '250']
SPEED = ['Watch every generation', 'Normal (up to 3 generations a round)', 'Fast (up to 8 a round)',
         'Fastest (up to 20 a round)']
GOALS = ['Random (a new goal every epoch)', 'Travel far', 'Reach the beacon', 'Climb to the beacon',
         'Cross the chasm', 'Jump as high as possible', 'Glide from the cliff', 'Run the hurdles']
GOAL_CHANGE = ['Random (8 to 40 generations, or when progress stalls)', 'Every 10 generations',
               'Every 20 generations', 'Every 40 generations', 'Never']
COMPLEXITY = ['Automatic (by profile)', 'Simple (up to 6 segments)', 'Medium (up to 10 segments)',
              'Complex (up to 16 segments)']
MUTATION = ['Low', 'Normal', 'High']
IMMIGRANTS = ['None', '5%', '8%', '12%']
QUALITY = ['Automatic (by profile)', 'Low (12 creatures on stage)', 'Balanced (24 on stage)',
           'High (48 on stage)', 'Smooth (4 on stage, half-resolution scene, for weak GPUs)']
CAMERA = ['Cinematic', 'Follow the leader', 'Overview']
INSIGHT = ['Off (just the creatures)', 'Light (goal, ticker and titles)',
           'Rich (live brain, charts and info cards)', 'Full (everything, plus system figures)']
CARD_SECONDS = ['15 seconds', '25 seconds', '40 seconds']
PALETTE = ['Automatic (a different one each run)', 'Warm dusk', 'Cool night', 'Neon', 'Mono']
LOG = ['Off', 'Summary (a line per generation)', 'Verbose (every event too)']
THREADS = ['Automatic (cores minus two, up to 4)', '1', '2', '3', '4']


def categories(low_power):
    return [
        ('General', [
            O('profile', 'Performance profile', 1 if low_power else 0, PROFILE),
            O('population', 'Population size', 0, POPULATION),
            O('speed', 'Evolution speed', 1, SPEED),
        ]),
        ('Evolution', [
            O('goal', 'Goal', 0, GOALS),
            O('goal_change', 'Change the goal', 0, GOAL_CHANGE),
            O('complexity', 'Creature complexity', 0, COMPLEXITY),
            O('mutation', 'Mutation rate', 1, MUTATION),
            O('immigrants', 'Fresh random creatures each generation', 2, IMMIGRANTS),
            B('vary_gravity', 'Vary gravity between goals', True),
        ]),
        ('Visuals', [
            O('quality', 'Visual quality', 0, QUALITY),
            O('camera', 'Camera', 0, CAMERA),
            O('insight', 'Information on screen', 2, INSIGHT),
            B('neural', 'Show the champion\'s brain', True),
            B('ticker', 'Show the event ticker', True),
            B('labels', 'Show names over the creatures', True),
            O('palette', 'Colours', 0, PALETTE),
            B('motes', 'Drifting motes in the sky', True),
            I('brightness', 'Brightness cap (%)', 100, 30, 100, 10),
            I('text_size', 'Text size (%)', 100, 70, 150, 10),
        ]),
        ('Info cards', [
            O('card_seconds', 'Change the card every', 1, CARD_SECONDS),
            B('card_profile', 'Champion profile', True),
            B('card_briefing', 'Goal briefing', True),
            B('card_totals', 'Run totals', True),
            B('card_fitness', 'Fitness history', True),
            B('card_species', 'Species over time', True),
            B('card_brain', 'Brain growth', True),
            B('card_family', 'Family tree', True),
            B('card_thennow', 'Then and now (with a ghost of an early champion)', True),
            B('card_milestones', 'Milestones', True),
            B('card_hall', 'Hall of fame', True),
            B('card_commentary', 'Commentary', True),
            B('card_facts', 'Did you know', True),
            B('card_map', 'Species map', True),
        ]),
        ('Advanced', [
            O('log', 'Kodi log', 1, LOG),
            O('threads', 'Evolution threads', 0, THREADS),
            dict(id='seed', type='string', label='Fixed seed (blank = a new random run every time)', default=''),
        ]),
    ]


if __name__ == '__main__':
    for addon_id, name, low in (('screensaver.evolvelife', 'EvolveLife (OpenGL)', False),
                                ('screensaver.evolvelife.armv7', 'EvolveLife (OpenGL, 32-bit Android)', True)):
        root = os.path.normpath(os.path.join(HERE, '..', addon_id))
        os.makedirs(os.path.join(root, 'resources'), exist_ok=True)
        write(root, addon_id, name, categories(low), 'tools/make_settings_evolvelife.py')

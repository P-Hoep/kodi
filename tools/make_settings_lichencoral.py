"""Generate the Lichen & Coral screensaver's settings.xml and strings.po from one table, so the
Kodi settings and screensaver.lichencoral/src/ScreensaverLichenCoral.cpp agree on option indices.

Run:
  python3 tools/make_settings_lichencoral.py
  python3 tools/make_settings_lichencoral.py screensaver.lichencoral.armv7 \
      'Lichen & Coral (OpenGL, 32-bit Android)' low

The optional third argument 'low' makes the 32-bit build default to low detail.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ID = sys.argv[1] if len(sys.argv) > 1 else 'screensaver.lichencoral'
NAME = sys.argv[2] if len(sys.argv) > 2 else 'Lichen & Coral (OpenGL)'
LOW_POWER = len(sys.argv) > 3 and sys.argv[3] == 'low'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402

B = lambda sid, label, default, **kw: dict(id=sid, type='boolean', label=label, default=default, **kw)
I = lambda sid, label, default, lo, hi, step=1, **kw: dict(
    id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)
O = lambda sid, label, default, options, **kw: dict(
    id=sid, type='options', label=label, default=default, options=options, **kw)

# Index order is read by LoadSettings() in ScreensaverLichenCoral.cpp.
SCENES = ['Take turns (all three)', 'Lichen on rock', 'Reef ridges', 'Coral colony']
ORDERS = ['Random', 'In turn']
DURATIONS = ['1 minute', '2 minutes', '3 minutes', '5 minutes', '10 minutes', '20 minutes']
VIEWS = ['Mix of flat and 3D', 'Flat (straight down)', '3D (moving camera)']
COLOURS = ['Natural', 'Vivid (invented colours)', 'Mix of both']
LICHEN_FORMS = ['Mixed (each species picks)', 'Crustose (smooth crusts)',
                'Foliose (lobed rosettes)', 'Branching fans']
CORAL_FORMS = ['Random', 'Branching (staghorn)', 'Bushy', 'Massive (boulder)', 'Table',
               'Sea fan']
COLONIES = ['Random', '1', '2', '3', '4']
DETAILS = ['Low (weak boxes, Fire TV)', 'Medium', 'High']


def categories():
    return [
        ('Scenes', [
            O('scene', 'Show', 0, SCENES),
            O('order', 'Order', 0, ORDERS, visible=('scene', '0')),
            O('duration', 'Each scene lasts up to', 2, DURATIONS),
            O('view', 'Lichen and reef view', 0, VIEWS),
            O('colours', 'Colours', 0, COLOURS),
        ]),
        ('Lichen', [
            I('lichen_species', 'Species on the rock', 5, 1, 8),
            O('lichen_form', 'Growth form', 0, LICHEN_FORMS),
            B('lichen_rings', 'Old centres die back into rings', True),
        ]),
        ('Reef', [
            B('reef_random_flow', 'Random current each scene', True),
            I('reef_flow', 'Current strength (%)', 50, 0, 100, 5,
              visible=('reef_random_flow', '!', 'true')),
            B('reef_storms', 'Storms break up the reef now and then', True),
        ]),
        ('Coral', [
            O('coral_form', 'Growth form', 0, CORAL_FORMS),
            O('coral_colonies', 'Colonies', 0, COLONIES),
            I('coral_spin', 'Camera orbit speed (%)', 100, 0, 300, 10),
        ]),
        ('Performance', [
            O('detail', 'Detail', 0 if LOW_POWER else 1, DETAILS),
            I('dim', 'Dim the picture (%)', 0, 0, 80, 10),
        ]),
    ]


if __name__ == '__main__':
    os.makedirs(os.path.join(ROOT, 'resources'), exist_ok=True)
    write(ROOT, ADDON_ID, NAME, categories(), 'tools/make_settings_lichencoral.py')

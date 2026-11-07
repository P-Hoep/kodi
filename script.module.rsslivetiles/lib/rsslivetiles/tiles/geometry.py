"""The unit grid (spec 2.2), tile sizes, slot pools and per-size face metrics.

Shared by the runtime (layout, text fitting) and tools/make_rsslivetiles_skin.py, which
generates the window XML from the same numbers, so the two cannot drift apart.
Coordinates are Kodi's 1080i skin pixels (1920 x 1080).
"""

UNIT = 130
GUTTER = 10
STEP = UNIT + GUTTER
BAND_UNITS = 4                      # layouts pack tiles into columns 4 units wide


def px(units):
    return units * UNIT + (units - 1) * GUTTER


SIZES = {'small': (1, 1), 'medium': (2, 2), 'wide': (4, 2), 'large': (4, 4)}
ORDER = ('small', 'medium', 'wide', 'large')
PIXELS = dict((name, (px(w), px(h))) for name, (w, h) in SIZES.items())
BAND_W = px(BAND_UNITS)             # 550
BAND_STEP = BAND_W + GUTTER         # 560
GROUP_GAP = 70                      # extra space between feed groups (Windows 8 Start style)

SCREEN_W, SCREEN_H = 1920, 1080
MARGIN_X = 80
HUB_TOP = 210                       # first tile row in the program (title and group headers above)
HUB_ROWS = 6
HEADER_Y = 140
SS_ROWS = 7
SS_BANDS = 3
SS_TOP = (SCREEN_H - px(SS_ROWS)) // 2
SS_LEFT = (SCREEN_W - (SS_BANDS * BAND_STEP - GUTTER)) // 2

# Slot pools: how many tiles of each size the window can show at once. The program binds
# only tiles near the visible part of the hub, so these cover about three screens.
POOLS = {'large': 6, 'wide': 18, 'medium': 36, 'small': 36}
SLOT_IDS = {'large': 1000, 'wide': 1100, 'medium': 1200, 'small': 1300}
SLOT_PREFIX = {'large': 'l', 'wide': 'w', 'medium': 'm', 'small': 's'}
HEADERS = 24                        # group header labels, ids 701..724
HEADER_ID = 700

# Control ids used by Python.
FOCUS_HOLDER = 9000
BOARD = 800
STRIP = 900
DETAIL = 950
DETAIL_CONTENT = 955
ZOOMER = 960
DETAIL_BODY = 971


def slot_names(size):
    return ['%s%d' % (SLOT_PREFIX[size], i + 1) for i in range(POOLS[size])]


def slot_id(size, index):
    return SLOT_IDS[size] + index + 1


# Kodi font names (Estuary; most skins have the same names) and their pixel sizes.
FONT_PX = {'font10': 23, 'font12': 25, 'font13': 30, 'font27': 27, 'font32': 32, 'font37': 37, 'font45': 45,
           'font60': 60, 'font_flag': 18, 'font_clock': 70}
LINE = 1.36                         # line height as a multiple of the font size (Noto Sans)


def line_px(font):
    return int(round(FONT_PX[font] * LINE))


# Face metrics per tile size:
#   pad          inner padding
#   title        (font, max lines) on a text face
#   summary      (font, max lines) under the title on wide / large text faces; None = no summary
#   image_title  (font, max lines) over the scrim on an image face; None = image only
#   count        font of the number on a count face
FACES = {
    'small': {'pad': 10, 'title': ('font10', 3), 'summary': None, 'image_title': None, 'count': 'font27',
              'icon': 64, 'initials': 'font37'},
    'medium': {'pad': 14, 'title': ('font27', 4), 'summary': ('font10', 3), 'image_title': ('font12', 3),
               'count': 'font60', 'icon': 120, 'initials': 'font60'},
    'wide': {'pad': 16, 'title': ('font32', 2), 'summary': ('font12', 2), 'image_title': ('font27', 2),
             'count': 'font60', 'icon': 120, 'initials': 'font60'},
    'large': {'pad': 20, 'title': ('font37', 4), 'summary': ('font13', 5), 'image_title': ('font32', 3),
              'count': 'font60', 'icon': 200, 'initials': 'font60'},
}
LABEL_FONT = 'font_flag'            # source / time labels: small caps
LABEL_H = 26


def text_area(size, inset=0):
    """(left, top, width) of the text block on a face, and the y of the bottom label row."""
    w, h = PIXELS[size]
    pad = FACES[size]['pad'] + inset
    return pad, pad - 4, w - 2 * pad, h - pad - LABEL_H + 2


# Animation timings in milliseconds (spec 4.3 and 5).
FLIP_MS = 250
FLIP_DEPTH = 8                      # % a flipping tile shrinks at the edge-on midpoint
CYCLE_MS = 350
FADE_MS = 400
PEEK_MS = 400
PULSE_MS = 150
ENTRANCE_MS = 350
ENTRANCE_STAGGER = 40
SCROLL_MS = 300
EXPAND_MS = 350
DETAIL_FADE_MS = 200
THEME_FADE_MS = 300

"""The clock drawn as blocks on the playfield: HH:MM in a 3 x 5 block font.

The cells come back as board coordinates, so the game can set them as fixed obstacles: pieces
collide with the digits and have to be played around them. No Kodi imports.
"""

from . import config

DIGITS = {
    '0': ('111', '101', '101', '101', '111'),
    '1': ('010', '110', '010', '010', '111'),
    '2': ('111', '001', '111', '100', '111'),
    '3': ('111', '001', '111', '001', '111'),
    '4': ('101', '101', '111', '001', '001'),
    '5': ('111', '100', '111', '001', '111'),
    '6': ('111', '100', '111', '101', '111'),
    '7': ('111', '001', '001', '001', '001'),
    '8': ('111', '101', '111', '101', '111'),
    '9': ('111', '101', '111', '001', '111'),
}
COLON = ('0', '1', '0', '1', '0')

DIGIT_W = 3
GAP = 1
COLON_W = 1
WIDTH = DIGIT_W + GAP + DIGIT_W + GAP + COLON_W + GAP + DIGIT_W + GAP + DIGIT_W   # 17
HEIGHT = 5

# Placed in the bottom five rows, flush with the floor: the stack builds on top of the digits
# instead of being walled off above them.
TOP = 13
LEFT = (config.COLS - WIDTH) // 2


def glyphs(now, twenty_four_hour):
    """The four digits and the colon, in reading order."""
    hour = now.tm_hour
    if not twenty_four_hour:
        hour = hour % 12 or 12
    text = '%02d%02d' % (hour, now.tm_min)
    return [DIGITS[text[0]], DIGITS[text[1]], COLON, DIGITS[text[2]], DIGITS[text[3]]]


def cells(now, twenty_four_hour, left=LEFT, top=TOP):
    """The board cells the clock occupies, as (x, y)."""
    out = []
    x = left
    for glyph in glyphs(now, twenty_four_hour):
        for row, bits in enumerate(glyph):
            for dx, bit in enumerate(bits):
                if bit == '1':
                    out.append((x + dx, top + row))
        x += len(glyph[0]) + GAP
    return out

"""The clock drawn as blocks on the playfield: HH:MM (or HH:MM:SS) in a 3 x 5 block font.

The cells come back as board coordinates, so the game can set them as fixed obstacles: pieces
collide with the digits and have to be played around them. No Kodi imports.
"""

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
HEIGHT = 5
SUSPENDED_GAP = 3         # empty rows under a suspended clock, so it clearly hangs in the air


def width(seconds=False):
    """Board columns taken by the clock: HH:MM is 17, HH:MM:SS is 27."""
    digits = 6 if seconds else 4
    colons = 2 if seconds else 1
    return (digits * DIGIT_W + colons * COLON_W
            + (digits + colons - 1) * GAP)


def fits(cols, seconds=False):
    return width(seconds) <= cols


def glyphs(now, twenty_four_hour, seconds=False):
    """The digits and colons, in reading order."""
    hour = now.tm_hour
    if not twenty_four_hour:
        hour = hour % 12 or 12
    text = '%02d%02d' % (hour, now.tm_min)
    out = [DIGITS[text[0]], DIGITS[text[1]], COLON, DIGITS[text[2]], DIGITS[text[3]]]
    if seconds:
        text = '%02d' % now.tm_sec
        out += [COLON, DIGITS[text[0]], DIGITS[text[1]]]
    return out


def cells(now, twenty_four_hour, cols, rows, seconds=False, floating=False):
    """The board cells the clock occupies, as (x, y).

    On the floor it sits in the bottom five rows, flush with it, so the stack builds on top of
    the digits instead of being walled off above them. Suspended, it hangs a few rows off the
    floor with empty air beneath: pieces still collide with it, and play around and above it.
    Seconds are dropped when the board does not have 27 columns for them, and the clock is left
    out entirely when even HH:MM lacks room.
    """
    if seconds and not fits(cols, True):
        seconds = False
    if not fits(cols, seconds):
        return []
    left = (cols - width(seconds)) // 2
    if floating:
        top = max(0, rows - HEIGHT - SUSPENDED_GAP)
    else:
        top = rows - HEIGHT
    out = []
    x = left
    for glyph in glyphs(now, twenty_four_hour, seconds):
        for row, bits in enumerate(glyph):
            for dx, bit in enumerate(bits):
                if bit == '1':
                    out.append((x + dx, top + row))
        x += len(glyph[0]) + GAP
    return out

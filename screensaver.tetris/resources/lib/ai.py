"""The AI: for a piece and a board, score every rotation and column with the El-Tetris
heuristic, then pick one. No Kodi imports.

Skill levels differ only in how often the best placement is taken. Perfect always takes it;
the weaker ones sometimes take a worse placement, down to Beginner, which mostly picks a
legal column at random.

The heuristic is Pieter Spronck's El-Tetris weights: landing height, cleared lines, row and
column transitions, holes and wells. It is not a solved-game search, but it keeps a stack
flat and low and rarely tops out.
"""

from collections import namedtuple

from . import pieces

Placement = namedtuple('Placement', 'rotation x y score lines')

# skill -> (chance of taking the best placement, how many runners-up are still considered)
# A negative pool means any other placement at all.
SKILL_TUNING = {
    0: (1.00, 0),      # Perfect
    1: (0.90, 2),      # Expert
    2: (0.72, 4),      # Skilled
    3: (0.40, -1),     # Average
    4: (0.12, -1),     # Beginner
}

W_LANDING = -4.500158825082766
W_LINES = 3.4181268101392694
W_ROW = -3.2178882868487753
W_COL = -9.348695305445199
W_HOLES = -7.899265427351652
W_WELLS = -3.3855972247263626
W_HEIGHT = -2.0


def popcount(value):
    return bin(value).count('1')


def row_transitions(bits, cols):
    total = 0
    for row in bits:
        prev = 0
        for x in range(cols):
            bit = (row >> x) & 1
            total += bit != prev
            prev = bit
        total += prev              # to the empty wall on the right
    return total


def column_transitions(bits, cols, rows):
    total = 0
    for x in range(cols):
        prev = 0
        for y in range(rows):
            bit = (bits[y] >> x) & 1
            total += bit != prev
            prev = bit
        total += prev              # to the empty floor
    return total


def holes(bits, cols, rows):
    total = 0
    for x in range(cols):
        seen = False
        for y in range(rows):
            filled = (bits[y] >> x) & 1
            if filled:
                seen = True
            elif seen:
                total += 1
    return total


def wells(bits, cols, rows):
    total = 0
    for x in range(cols):
        for y in range(rows):
            if (bits[y] >> x) & 1:
                continue
            left = x == 0 or (bits[y] >> (x - 1)) & 1
            right = x == cols - 1 or (bits[y] >> (x + 1)) & 1
            if not (left and right):
                continue
            depth = 0
            yy = y
            while yy < rows and not (bits[yy] >> x) & 1:
                depth += 1
                yy += 1
            total += depth
    return total


def max_height(bits, cols, rows):
    for y in range(rows):
        if bits[y]:
            return rows - y
    return 0


def score_board(bits, cols, rows, landing_height, cleared):
    return (W_LANDING * landing_height + W_LINES * cleared
            + W_ROW * row_transitions(bits, cols)
            + W_COL * column_transitions(bits, cols, rows)
            + W_HOLES * holes(bits, cols, rows)
            + W_WELLS * wells(bits, cols, rows)
            + W_HEIGHT * max_height(bits, cols, rows))


def candidates(board, letter):
    """Every legal placement for this piece, best first."""
    out = []
    bits = board.bits
    full = board.full_mask
    for rotation, shape in enumerate(pieces.ROTATIONS[letter]):
        masks = pieces.masks(shape)
        width = pieces.width(shape)
        for x in range(board.cols - width + 1):
            y = board.landing(masks, x, bits)
            if y is None:
                continue
            after = list(bits)
            cells = 0
            height_sum = 0
            for dy, mask in masks:
                after[y + dy] |= mask << x
                cells += popcount(mask)
                height_sum += popcount(mask) * (board.height - (y + dy))
            landing_height = height_sum / float(cells)
            kept = [row for row in after if row != full]
            cleared = len(after) - len(kept)
            if cleared:
                kept = [0] * cleared + kept
            out.append(Placement(rotation, x, y,
                                 score_board(kept, board.cols, board.height, landing_height, cleared),
                                 cleared))
    out.sort(key=lambda p: -p.score)
    return out


def choose(board, letter, rng, skill=0):
    """A placement for `letter` on `board`, or None when nothing fits (the game is over)."""
    places = candidates(board, letter)
    if not places:
        return None
    best_chance, pool = SKILL_TUNING.get(skill, SKILL_TUNING[0])
    if len(places) == 1 or rng.random() < best_chance:
        return places[0]
    if pool > 0:
        runners_up = places[1:1 + pool]
        return rng.choice(runners_up) if runners_up else places[0]
    others = places[1:]
    return rng.choice(others) if others else places[0]


def best(board, letter):
    places = candidates(board, letter)
    return places[0] if places else None

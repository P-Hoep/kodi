"""The playfield: occupancy as one bitmask per row, plus the piece letter of each cell for the
renderer. No Kodi imports.

Row 0 is the top. A full row is removed and all the rows above it move down one, which is what
the renderer then redraws as a diff. Fixed cells (the block clock) are obstacles that pieces
collide with, but they never fall and never clear.
"""

FIXED = '#'


class Board(object):
    def __init__(self, cols, rows):
        self.cols = cols
        self.height = rows
        self.full_mask = (1 << cols) - 1
        self.bits = [0] * rows
        self.letters = [[None] * cols for _ in range(rows)]
        self.fixed_bits = [0] * rows
        self.fixed_letters = [[None] * cols for _ in range(rows)]

    # ------------------------------------------------------------ queries

    def blank_row(self):
        return [None] * self.cols

    def is_empty(self):
        return not any(self.bits)

    def fits(self, masks, x, y, bits=None):
        """Can a piece with these row masks sit at (x, y)?"""
        bits = self.bits if bits is None else bits
        if x < 0:
            return False
        width = max(mask.bit_length() for _dy, mask in masks)
        if x + width > self.cols:
            return False
        for dy, mask in masks:
            yy = y + dy
            if yy < 0 or yy >= self.height:
                return False
            if bits[yy] & (mask << x):
                return False
        return True

    def landing(self, masks, x, bits=None):
        """The lowest y the piece can reach from above at column x, or None if it cannot enter."""
        bits = self.bits if bits is None else bits
        if not self.fits(masks, x, 0, bits):
            return None
        y = 0
        while self.fits(masks, x, y + 1, bits):
            y += 1
        return y

    def full_rows(self):
        return [y for y in range(self.height) if self.bits[y] == self.full_mask]

    def column_height(self, x):
        for y in range(self.height):
            if self.bits[y] & (1 << x):
                return self.height - y
        return 0

    # ------------------------------------------------------------ changes

    def can_set_fixed(self, cells):
        """True when no locked piece is in the way of these fixed cells (the clock is free to
        change to a new pattern)."""
        for x, y in cells:
            if (self.bits[y] >> x) & 1 and not (self.fixed_bits[y] >> x) & 1:
                return False
        return True

    def set_fixed(self, cells):
        """Replace the fixed cells: the block clock's digits. Fixed cells never fall or clear.
        Only call this when can_set_fixed() is true, so no piece is overwritten."""
        for y in range(self.height):
            old = self.fixed_bits[y]
            if not old:
                continue
            self.bits[y] &= ~old
            for x in range(self.cols):
                if (old >> x) & 1:
                    self.letters[y][x] = None
        self.fixed_bits = [0] * self.height
        self.fixed_letters = [[None] * self.cols for _ in range(self.height)]
        for x, y in cells:
            if 0 <= x < self.cols and 0 <= y < self.height:
                self.fixed_bits[y] |= 1 << x
                self.fixed_letters[y][x] = FIXED
                self.bits[y] |= 1 << x
                self.letters[y][x] = FIXED

    def place(self, letter, shape, x, y):
        for dx, dy in shape:
            xx, yy = x + dx, y + dy
            if 0 <= xx < self.cols and 0 <= yy < self.height:
                self.bits[yy] |= 1 << xx
                self.letters[yy][xx] = letter

    def remove_rows(self, rows):
        """Remove these full rows; the piece cells above fall down, while fixed clock cells stay
        exactly where they are (a cell that would land in the clock stops just above it).
        Returns how many rows were removed."""
        rows = set(rows)
        if not rows:
            return 0
        pieces = []
        for y in range(self.height):
            row = self.letters[y]
            for x in range(self.cols):
                letter = row[x]
                if letter is not None and letter != FIXED:
                    pieces.append((x, y, letter))
        self.bits = list(self.fixed_bits)
        self.letters = [row[:] for row in self.fixed_letters]
        for x, y, letter in sorted(pieces, key=lambda c: -c[1]):   # bottom-up
            if y in rows:
                continue
            yy = y + sum(1 for r in rows if r > y)
            while yy >= 0 and (self.bits[yy] >> x) & 1:          # never enter the clock
                yy -= 1
            if yy < 0:
                continue
            self.bits[yy] |= 1 << x
            self.letters[yy][x] = letter
        return len(rows)

    def clear(self):
        """Empty the playfield but keep the fixed cells (the block clock)."""
        self.bits = list(self.fixed_bits)
        self.letters = [row[:] for row in self.fixed_letters]

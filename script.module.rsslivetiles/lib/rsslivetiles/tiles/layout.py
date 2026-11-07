"""The grid packing engine. Tiles are packed into bands (columns 4 units wide, `rows` units
tall) left to right. Within a group, each tile goes to the first free spot of the group's
bands in band / row / column order, so later small tiles back-fill holes; a new band opens
when nothing fits. Groups start on a fresh band with a gap before it.
"""

from . import geometry as g


class Packer(object):
    def __init__(self, rows, left=0, top=0, max_bands=None, group_bands=None, gap=g.GROUP_GAP):
        self.rows = rows
        self.left = left
        self.top = top
        self.max_bands = max_bands          # screensaver: the screen's width
        self.group_bands = group_bands      # Spotlight: a page is at most this many bands
        self.gap = gap
        self.grids = []                     # per band: rows x 4 booleans (occupied)
        self.band_x = []
        self.band_group = []
        self.group = -1
        self.group_start = 0

    # ------------------------------------------------------------ bands and groups

    def new_group(self):
        """Start a new group; its first band opens on demand."""
        self.group += 1
        self.group_start = len(self.grids)

    def _open_band(self):
        if self.max_bands is not None and len(self.grids) >= self.max_bands:
            return False
        if self.group_bands is not None and len(self.grids) - self.group_start >= self.group_bands:
            return False
        if self.group < 0:
            self.group = 0
        if not self.band_x:
            x = self.left
        else:
            x = self.band_x[-1] + g.BAND_STEP
            if self.band_group[-1] != self.group:
                x += self.gap
        self.grids.append([[False] * g.BAND_UNITS for _ in range(self.rows)])
        self.band_x.append(x)
        self.band_group.append(self.group)
        return True

    def group_x(self, group):
        xs = [x for x, grp in zip(self.band_x, self.band_group) if grp == group]
        return (xs[0], xs[-1] + g.BAND_W) if xs else (None, None)

    # ------------------------------------------------------------ placing

    def _fits(self, band, col, row, w, h):
        grid = self.grids[band]
        if col + w > g.BAND_UNITS or row + h > self.rows:
            return False
        return all(not grid[r][c] for r in range(row, row + h) for c in range(col, col + w))

    def _mark(self, band, col, row, w, h):
        for r in range(row, row + h):
            for c in range(col, col + w):
                self.grids[band][r][c] = True

    def find(self, size):
        """The first free spot for size in the current group, without opening a band."""
        w, h = g.SIZES[size]
        if h > self.rows:
            return None
        for band in range(self.group_start, len(self.grids)):
            for row in range(self.rows - h + 1):
                for col in range(0, g.BAND_UNITS - w + 1):
                    if self._fits(band, col, row, w, h):
                        return band, col, row
        return None

    def place(self, tile):
        """Place tile (sets band / col / row / x / y / group). False if it cannot fit."""
        spot = self.find(tile.size)
        if spot is None:
            if not self._open_band():
                return False
            spot = self.find(tile.size)
            if spot is None:
                return False
        band, col, row = spot
        w, h = g.SIZES[tile.size]
        self._mark(band, col, row, w, h)
        tile.band, tile.col, tile.row = band, col, row
        tile.x = self.band_x[band] + col * g.STEP
        tile.y = self.top + row * g.STEP
        tile.group = self.group
        return True

    def holes(self):
        """Free 1x1 cells in the current group's bands, in reading order per band."""
        out = []
        for band in range(self.group_start, len(self.grids)):
            for row in range(self.rows):
                for col in range(g.BAND_UNITS):
                    if not self.grids[band][row][col]:
                        out.append((band, col, row))
        return out

    def free_units(self):
        return len(self.holes())

    @property
    def width(self):
        return (self.band_x[-1] + g.BAND_W - self.left) if self.band_x else 0

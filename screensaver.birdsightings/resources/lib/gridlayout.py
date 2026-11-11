# -*- coding: utf-8 -*-
"""Bento-style mosaic layout: mostly 1x1 tiles with a few 2x2 feature tiles."""
import random


def make_layout(cols, rows, max_big=0, rng=None):
    """Return a list of (col, row, size) covering every cell exactly once."""
    rng = rng or random
    occ = [[False] * cols for _ in range(rows)]
    cells = []

    spots = [(c, r) for r in range(rows - 1) for c in range(cols - 1)]
    rng.shuffle(spots)
    big = 0
    for c, r in spots:
        if big >= max_big:
            break
        if not (occ[r][c] or occ[r][c + 1] or occ[r + 1][c] or occ[r + 1][c + 1]):
            for dr in (0, 1):
                for dc in (0, 1):
                    occ[r + dr][c + dc] = True
            cells.append((c, r, 2))
            big += 1

    for r in range(rows):
        for c in range(cols):
            if not occ[r][c]:
                occ[r][c] = True
                cells.append((c, r, 1))

    cells.sort(key=lambda t: (t[1], t[0]))
    return cells

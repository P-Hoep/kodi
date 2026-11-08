"""The game state around the board: the 7-bag, the next piece, score, lines and level.
No Kodi imports.
"""

from . import config, pieces

SCORE = (0, 100, 300, 500, 800)


class Game(object):
    def __init__(self, board, rng, start_level=1):
        self.board = board
        self.rng = rng
        self.start_level = max(1, min(config.MAX_LEVEL, int(start_level)))
        self.bag = []
        self.next = self._take()
        self.score = 0
        self.lines = 0
        self.level = self.start_level
        self.pieces = 0

    def _take(self):
        """Next piece from a shuffled 7-bag."""
        if not self.bag:
            self.bag = list(pieces.TYPES)
            self.rng.shuffle(self.bag)
        return self.bag.pop()

    def take(self):
        letter = self.next
        self.next = self._take()
        self.pieces += 1
        return letter

    def lock(self, rows_cleared):
        """Account for a piece that has just locked and these full rows removed."""
        self.score += SCORE[min(4, rows_cleared)] * self.level
        self.lines += rows_cleared
        if self.lines:
            self.level = min(config.MAX_LEVEL,
                             self.start_level + self.lines // config.LEVEL_LINES)

    def reset(self):
        self.board.clear()
        self.bag = []
        self.next = self._take()
        self.score = 0
        self.lines = 0
        self.level = self.start_level
        self.pieces = 0

    def delays(self, s):
        return config.delays(s, self.level)

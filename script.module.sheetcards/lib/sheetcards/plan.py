"""What one card looks like on screen: flashcard or multiple choice, which side is asked, and
the options. Shared by both front-ends; pure Python."""

from . import choices
from .config import DIR_AQ, DIR_BOTH, MODE_CHOICE, MODE_FLASH, MODE_MIXED, option_count


class Plan(object):
    def __init__(self, card, kind, side, options=None, correct=None):
        self.card = card
        self.kind = kind              # 'flash' or 'choice'
        self.side = side              # 'q': question asked, answer revealed; 'a': the reverse
        self.options = options or []
        self.correct = correct
        self.stacked = choices.stacked(self.options) if self.options else False
        self.fell_back = False        # asked for multiple choice, too few distinct answers

    @property
    def prompt(self):
        return self.card.question if self.side == 'q' else self.card.answer

    @property
    def reveal(self):
        return self.card.answer if self.side == 'q' else self.card.question


def choose_side(settings, rng):
    direction = settings.get('direction', 0)
    if direction == DIR_BOTH:
        return 'q' if rng.random() < 0.5 else 'a'
    return 'a' if direction == DIR_AQ else 'q'


def wants_choice(settings, rng):
    mode = settings.get('mode', MODE_MIXED)
    if mode == MODE_FLASH:
        return False
    if mode == MODE_CHOICE:
        return True
    return rng.random() * 100 < settings.get('mix_ratio', 50)


def make(card, settings, scope, rng, mode=None):
    """scope: the cards wrong options may come from. mode overrides settings['mode']."""
    if mode is not None:
        settings = dict(settings, mode=mode)
    side = choose_side(settings, rng)
    if not wants_choice(settings, rng):
        return Plan(card, 'flash', side)
    built = choices.build(side, card, scope, option_count(settings), rng)
    if built is None:
        plan = Plan(card, 'flash', side)
        plan.fell_back = True
        return plan
    options, correct = built
    return Plan(card, 'choice', side, options, correct)


def scope_for(card, decks_by_title, selected_cards, settings):
    """distractor_scope 0 = this deck, 1 = all selected decks."""
    if settings.get('distractor_scope', 0) == 1:
        return selected_cards
    deck = decks_by_title.get(card.deck)
    return deck.cards if deck else selected_cards


def flash_only_decks(decks, settings):
    """Decks with fewer distinct answers (or questions) than options: flashcards only."""
    need = option_count(settings)
    out = []
    for d in decks:
        if min(choices.distinct_count([c.answer for c in d.cards]),
               choices.distinct_count([c.question for c in d.cards])) < need:
            out.append(d)
    return out

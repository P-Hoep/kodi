"""The screensaver: a hands-free loop over the selected decks. Shows a card, reveals the answer
on a timer, moves on, and exits the instant anything is pressed. It never records progress.
"""

import random
import threading
import time

import xbmc

from sheetcards import SCREENSAVER_ID, deck, kodi, plan as plans, sheet, theme
from sheetcards.data import Refresher
from sheetcards.ui.card_window import Closed, CardView, Screen

RETRY_SECONDS = 300


class ExitMonitor(xbmc.Monitor):
    def __init__(self, on_wake):
        xbmc.Monitor.__init__(self)
        self.on_wake = on_wake

    def onScreensaverDeactivated(self):
        self.on_wake()


class Saver(object):
    def __init__(self):
        self.settings = kodi.read_settings(SCREENSAVER_ID)
        self.rng = random.Random()
        self.screen = None
        self.lock = threading.Lock()
        self.woken = False
        self.monitor = ExitMonitor(self.wake)
        self.palette = None
        self.started = time.time()

    # ------------------------------------------------------------ exit

    def wake(self):
        with self.lock:
            self.woken = True
            screen = self.screen
        if screen:
            screen.finish()

    def on_input(self, _action_id):
        """Any key, click, touch or mouse move: close now (on Kodi's UI thread)."""
        self.wake()
        return True

    # ------------------------------------------------------------ run

    def run(self):
        started = time.time()
        Screen.open('sheetcards-card.xml', self.logic, on_input=self.on_input, palette=self.resolve_palette(),
                    props={'clock': '1' if self.settings.get('show_clock') else ''})
        kodi.debug('screensaver closed after %.1f s' % (time.time() - started))

    def resolve_palette(self):
        self.palette = theme.resolve(self.settings, kodi.now())
        return self.palette

    def logic(self, screen):
        with self.lock:
            self.screen = screen
            if self.woken:
                return None
        s = self.settings
        view = CardView(screen, app=False, rng=self.rng)
        if not s['sheet_id']:
            title, body = kodi.error_text(sheet.SheetError('no_id'))
            view.message(title, body)
            while True:
                screen.wait(3600)
        loader = kodi.loader(s)
        refresher = Refresher(loader)
        got = loader.cached()
        if got is None:
            got = self.first_load(screen, view, refresher)
        elif loader.is_stale(s.get('refresh_hours', 6)):
            refresher.start()
        self.loop(screen, view, got, refresher)

    def first_load(self, screen, view, refresher):
        """No cache: download while showing a calm card; retry every 5 minutes."""
        view.message(kodi.tr(32010))
        while True:
            refresher.start()
            while refresher.running:
                screen.sleep(0.2)
            got, err = refresher.take()
            if got is not None and got.usable:
                return got
            if err is None or err.kind == 'network':
                view.message(kodi.tr(32006))
            else:
                title, body = kodi.error_text(err)
                view.message(title, body)
            screen.sleep(RETRY_SECONDS)

    def pick_decks(self, got):
        return deck.select(got.decks, deck.parse_keys(self.settings.get('decks', '')))

    def loop(self, screen, view, got, refresher):
        s = self.settings
        decks = self.pick_decks(got)
        cards = [c for d in decks for c in d.cards]
        by_title = dict((d.title, d) for d in decks)
        bag = deck.ShuffleBag(cards, self.rng)
        question = s.get('question_seconds', 8)
        answer = s.get('answer_seconds', 6)
        dim_after = s.get('dim_after_minutes', 0) * 60
        while True:
            # Card boundary: new data, theme (Auto), dimming.
            fresh, err = refresher.take()
            if fresh is not None and fresh.usable:
                decks = self.pick_decks(fresh)
                cards = [c for d in decks for c in d.cards]
                by_title = dict((d.title, d) for d in decks)
                bag.replace(cards)
                kodi.debug('swapped in refreshed cards: %d' % len(cards))
            elif err is not None:
                kodi.log('refresh failed, carrying on with cached cards: %s' % err)
            if self.palette.get('name') != self.resolve_palette().get('name'):
                screen.apply_theme(self.palette)
            if dim_after and time.time() - self.started > dim_after:
                screen.prop('dim', '1')
            card = bag.next()
            if card is None:
                view.message(kodi.tr(32011), kodi.tr(32012))
                screen.sleep(RETRY_SECONDS)
                continue
            plan = plans.make(card, s, plans.scope_for(card, by_title, cards, s), self.rng)
            view.show(plan, chip=card.deck if len(decks) > 1 else '', drift=True)
            if s.get('show_timer_bar', True):
                screen.prop('timer', question)
            screen.sleep(question)
            screen.prop('timer', '')
            if plan.kind == 'choice':
                view.reveal_choice(None)
            else:
                view.flip()
            screen.sleep(answer)


def main(args):
    if args:
        from sheetcards import actions
        actions.run(SCREENSAVER_ID, args[0])
        return
    try:
        Saver().run()
    except Closed:
        pass

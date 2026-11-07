"""The app: deck picker -> study session -> results, driven by remote, mouse or touch.

Every interactive element is a real Kodi button, so focus + Select, a mouse click and a tap
all arrive as onClick. Progress (Leitner boxes and stats) is written after every answer.
"""

import random
import time

import xbmc
import xbmcaddon
import xbmcgui

from sheetcards import APP_ID, config, deck, kodi, plan as plans, sheet, srs, theme
from sheetcards.data import Refresher
from sheetcards.ui import card_window as cw
from sheetcards.ui.card_window import CardView, Screen

MODE_LABELS = {config.MODE_FLASH: 32016, config.MODE_CHOICE: 32017, config.MODE_MIXED: 32018}
MILESTONES = (5, 10, 25)


def is_back(event):
    return event and event[0] == 'action' and event[1] in cw.BACK_ACTIONS


def clicked(event, *ids):
    return event and event[0] == 'click' and (not ids or event[1] in ids)


class Quit(Exception):
    pass


class App(object):
    def __init__(self):
        self.rng = random.Random()
        self.reload_settings()
        self.data = None
        self.progress = None
        self.refresher = None
        self.offline = None          # SheetError of the last failed refresh, if any
        self.review = None           # cards for a "Review missed" session
        self.result = None           # last session's numbers for the results screen
        self.told_flash_only = False

    def reload_settings(self):
        self.settings = kodi.read_settings(APP_ID)
        self.mode = self.settings.get('mode', config.MODE_MIXED)

    def palette(self):
        return theme.resolve(self.settings, kodi.now())

    # ------------------------------------------------------------ flow

    def run(self):
        screen = 'load'
        while screen:
            kodi.debug('screen: %s' % screen)
            if screen == 'load':
                screen = self.load()
            elif screen == 'decks':
                screen = self.decks()
            elif screen == 'study':
                screen = self.study()
            elif screen == 'results':
                screen = self.results()
            elif screen == 'settings':
                xbmcaddon.Addon(APP_ID).openSettings()
                self.reload_settings()
                self.data = None
                screen = 'load'
            else:
                screen = None

    def use(self, got):
        self.data = got
        if self.progress is None or self.progress.sheet_id != got.sheet_id:
            self.progress = srs.Progress(kodi.cache().progress_path(got.sheet_id), got.sheet_id, kodi.log)
        self.progress.prune([c.id for c in got.all_cards()], kodi.now().date())

    # ------------------------------------------------------------ loading / errors

    def load(self):
        s = self.settings
        loader = kodi.loader(s)
        self.refresher = Refresher(loader)
        if s['sheet_id']:
            got = loader.cached()
            if got is not None and got.usable:
                self.use(got)
                if loader.is_stale(s.get('refresh_hours', 6)):
                    self.refresher.start()
                return 'decks'
        return Screen.open('sheetcards-card.xml', self.load_logic, palette=self.palette())

    def load_logic(self, screen):
        view = CardView(screen, app=True, rng=self.rng)
        while True:
            if not self.settings['sheet_id']:
                err = sheet.SheetError('no_id')
            else:
                view.message(kodi.tr(32010))
                self.refresher.start()
                while self.refresher.running:
                    screen.sleep(0.1)
                got, err = self.refresher.take()
                if got is not None and got.usable:
                    self.use(got)
                    self.offline = None
                    return 'decks'
                if got is not None:
                    err = sheet.SheetError('bad_data')
            title, body = kodi.error_text(err)
            retry, settings = kodi.tr(32009), kodi.tr(32008)
            if err.kind == 'no_id':
                view.message(title, body, settings)
                buttons = {150: 'settings'}
            elif err.kind in ('network', 'bad_data'):
                view.message(title, body, retry, settings)
                buttons = {152: 'retry', 151: 'settings'}
            else:
                view.message(title, body, settings, retry)
                buttons = {152: 'settings', 151: 'retry'}
            choice = None
            while choice is None:
                event = screen.wait(60)
                if is_back(event):
                    return None
                if clicked(event):
                    choice = buttons.get(event[1])
            if choice == 'settings':
                return 'settings'

    # ------------------------------------------------------------ deck picker

    def deck_label2(self, d, today):
        due = self.progress.due_count(d.cards, today)
        text = kodi.tr(32019) % len(d.cards)
        if self.settings.get('srs_enabled', True):
            text += '  ·  ' + kodi.tr(32020) % due
        return text

    def fill_decks(self, screen, keys):
        today = kodi.now().date()
        lst = screen.getControl(50)
        lst.reset()
        items = []
        for d in self.data.usable:
            item = xbmcgui.ListItem(d.title, self.deck_label2(d, today))
            mastery = self.progress.mastery(d.cards)
            item.setProperty('mastery', '%d%%' % round(100 * mastery))
            item.setProperty('bar', 'bar_%02d.png' % (5 * int(round(mastery * 20))) if mastery < 0.995
                             else 'bar_100.png')
            item.setProperty('key', d.key)
            item.select(d.key in keys)
            items.append(item)
        lst.addItems(items)
        title = self.data.title or 'Sheetcards'
        screen.prop('title', title)
        stats = self.progress.stats
        accuracy = self.progress.accuracy()
        screen.prop('stats', kodi.tr(32044) % (stats['best_streak'], stats['sessions'],
                                                '%d%%' % round(accuracy) if accuracy is not None else '-'))
        self.status(screen)

    def status(self, screen):
        if self.refresher and self.refresher.running:
            screen.prop('status', kodi.tr(32045))
        elif self.offline is not None:
            screen.prop('status', kodi.tr(32021) % kodi.ago(self.data.fetched_at))
        else:
            screen.prop('status', '')

    def selected_keys(self, screen):
        lst = screen.getControl(50)
        keys = []
        for i in range(lst.size()):
            item = lst.getListItem(i)
            if item.isSelected():
                keys.append(item.getProperty('key'))
        return keys

    def decks(self):
        return Screen.open('sheetcards-decks.xml', self.decks_logic, palette=self.palette())

    def decks_logic(self, screen):
        screen.set_strings({'t.start': 32013, 't.refresh': 32014, 't.settings': 32015})
        keys = deck.parse_keys(self.settings.get('decks', ''))
        if not keys:
            keys = [d.key for d in self.data.usable]
        self.fill_decks(screen, keys)
        screen.prop('mode_label', kodi.tr(MODE_LABELS[self.mode]))
        screen.prop('hint', kodi.tr(32043))
        screen.focus(50)
        while True:
            event = screen.wait(0.5)
            if self.refresher and not self.refresher.running:
                got, err = self.refresher.take()
                if got is not None and got.usable:
                    keys = self.selected_keys(screen)
                    self.use(got)
                    self.offline = None
                    self.fill_decks(screen, keys)
                elif err is not None:
                    self.offline = err
                    kodi.log('refresh failed: %s' % err)
                self.status(screen)
            if event is None:
                continue
            if is_back(event):
                return None
            if clicked(event, 50):
                lst = screen.getControl(50)
                item = lst.getSelectedItem()
                if item is not None:
                    item.select(not item.isSelected())
            elif clicked(event, 60):
                self.mode = (self.mode + 1) % 3
                screen.prop('mode_label', kodi.tr(MODE_LABELS[self.mode]))
                xbmcaddon.Addon(APP_ID).setSettingInt('mode', self.mode)
            elif clicked(event, 61):
                keys = self.selected_keys(screen)
                if not keys:
                    screen.prop('hint', '[COLOR %s]%s[/COLOR]' % (screen.getProperty('sc.accent'), kodi.tr(32043)))
                    screen.focus(50)
                    continue
                all_keys = [d.key for d in self.data.usable]
                value = '' if sorted(keys) == sorted(all_keys) else ','.join(keys)
                xbmcaddon.Addon(APP_ID).setSettingString('decks', value)
                self.settings['decks'] = value
                self.review = None
                return 'study'
            elif clicked(event, 62):
                if self.refresher.start():
                    self.status(screen)
            elif clicked(event, 63):
                return 'settings'

    # ------------------------------------------------------------ study

    def chosen_decks(self):
        return deck.select(self.data.decks, deck.parse_keys(self.settings.get('decks', '')))

    def study(self):
        return Screen.open('sheetcards-card.xml', self.study_logic, palette=self.palette())

    def study_logic(self, screen):
        s = self.settings
        view = CardView(screen, app=True, rng=self.rng)
        decks = self.chosen_decks()
        by_title = dict((d.title, d) for d in decks)
        cards = [c for d in decks for c in d.cards]
        today = kodi.now().date()
        srs_on = s.get('srs_enabled', True)
        if self.review:
            session = list(self.review)
            self.rng.shuffle(session)
        else:
            session = srs.build_session(cards, self.progress, today, config.session_length(s), s.get('order', 0),
                                        s.get('new_per_session', 10), srs_on, self.rng)
        if not session:
            return 'decks'
        if self.mode != config.MODE_FLASH and not self.told_flash_only:
            small = plans.flash_only_decks(decks, s)
            if small:
                self.told_flash_only = True
                kodi.notify(kodi.tr(32047))
        queue = srs.Queue(session, self.rng)
        st = {'score': 0, 'streak': 0, 'best': 0, 'answered': 0, 'missed': [], 'started': time.time()}
        palette_name = self.palette().get('name')
        screen.prop('score', 0)
        screen.prop('streak', 0)
        try:
            while not queue.done:
                card = queue.current()
                palette = self.palette()
                if palette.get('name') != palette_name:
                    palette_name = palette.get('name')
                    screen.apply_theme(palette)
                plan = plans.make(card, s, plans.scope_for(card, by_title, cards, s), self.rng, mode=self.mode)
                screen.prop('progress', kodi.tr(32065) % (queue.number, queue.length))
                view.show(plan, chip=card.deck if len(decks) > 1 else '')
                correct = self.ask(screen, view, plan, st)
                self.record(screen, card, correct, st, srs_on and not self.review)
                if not correct:
                    st['missed'].append(card)
                    queue.requeue(card)
                self.after_answer(screen, view, plan, correct, st)
                queue.advance()
        except Quit as stop:
            if stop.args and stop.args[0] == 'quit':
                self.finish_session(st)
                return None
        self.finish_session(st)
        return 'results'

    def finish_session(self, st):
        if st['answered']:
            self.progress.stats['sessions'] += 1
            self.progress.note_streak(st['best'])
            self.progress.save()
        seen, unique = set(), []
        for c in st['missed']:
            if c.id not in seen:
                seen.add(c.id)
                unique.append(c)
        st['missed'] = unique
        st['seconds'] = time.time() - st['started']
        self.result = st

    def record(self, screen, card, correct, st, use_srs):
        st['answered'] += 1
        if correct:
            st['score'] += 1
            st['streak'] += 1
            st['best'] = max(st['best'], st['streak'])
        else:
            st['streak'] = 0
        self.progress.record(card.id, correct, kodi.now().replace(microsecond=0), srs=use_srs)
        self.progress.note_streak(st['best'])
        try:
            self.progress.save()
        except OSError as err:
            kodi.log('could not save progress: %s' % err, xbmc.LOGWARNING)
        screen.prop('score', st['score'])
        screen.prop('streak', st['streak'])
        if st['streak'] in MILESTONES:
            screen.prop('pulse', '1')
            screen.sleep(0.15)
            screen.prop('pulse', '')

    def ask(self, screen, view, plan, st):
        """Wait for an answer. True / False; raises Quit for End session / Quit."""
        if plan.kind == 'flash':
            screen.focus(101)
            while True:
                event = self.next_event(screen, view, plan, 101)
                if clicked(event, 101):
                    break
            view.flip()
            screen.focus(112)
            while True:
                event = self.next_event(screen, view, plan, 112)
                if clicked(event, 111, 112):
                    return event[1] == 112
        ids = view.option_ids()
        screen.focus(ids[0])
        while True:
            event = self.next_event(screen, view, plan, ids[0])
            picked = None
            if clicked(event) and event[1] in ids:
                picked = ids.index(event[1])
            elif event and event[0] == 'action' and cw.ACTION_REMOTE_1 <= event[1] <= cw.ACTION_REMOTE_4:
                n = event[1] - cw.ACTION_REMOTE_1
                if n < len(ids):
                    picked = n
            if picked is not None:
                view.reveal_choice(picked)
                return picked == plan.correct

    def after_answer(self, screen, view, plan, correct, st):
        """Multiple choice: auto-advance (or wait for Select / a tap anywhere)."""
        if plan.kind == 'flash':
            return
        s = self.settings
        screen.prop('answered', '1')
        screen.focus(140)
        delay = (s.get('advance_ms_correct', 900) if correct else s.get('advance_ms_wrong', 2200)) / 1000.0
        deadline = time.time() + delay if s.get('auto_advance', True) else None
        while True:
            remaining = 3600 if deadline is None else deadline - time.time()
            if remaining <= 0:
                return
            event = self.next_event(screen, view, plan, 140, timeout=min(remaining, 0.5))
            if clicked(event, 140):
                return

    def next_event(self, screen, view, plan, refocus, timeout=0.5):
        """One event, with Back (pause sheet) and Info (card stats) handled here."""
        event = screen.wait(timeout)
        if event is None:
            return None
        if is_back(event):
            if screen.getProperty('sc.info'):
                screen.prop('info', '')
                return None
            self.pause(screen, refocus)
            return None
        if event[0] == 'action' and event[1] == cw.ACTION_SHOW_INFO:
            if screen.getProperty('sc.info'):
                screen.prop('info', '')
            else:
                screen.prop('info.text', self.card_stats(plan.card))
                screen.prop('info', '1')
            return None
        return event

    def card_stats(self, card):
        entry = self.progress.cards.get(card.id, {})
        lines = [card.deck]
        box = int(entry.get('box', 0) or 0)
        lines.append(kodi.tr(32037) % box if box else kodi.tr(32038))
        if entry.get('seen'):
            lines.append(kodi.tr(32039) % int(entry['seen']))
            lines.append(kodi.tr(32040) if entry.get('result') else kodi.tr(32041))
        due = self.progress.due(card.id, kodi.now().date())
        if due is not None:
            lines.append(kodi.tr(32060) if due <= kodi.now().date() else kodi.tr(32061) % due.isoformat())
        return '[CR]'.join(lines)

    def pause(self, screen, refocus):
        screen.prop('paused', '1')
        screen.focus(301)
        while True:
            event = screen.wait(3600)
            if is_back(event) or clicked(event, 301):
                screen.prop('paused', '')
                screen.focus(refocus)
                return
            if clicked(event, 302):
                screen.prop('paused', '')
                raise Quit('end')
            if clicked(event, 303):
                raise Quit('quit')

    # ------------------------------------------------------------ results

    def results(self):
        return Screen.open('sheetcards-results.xml', self.results_logic, palette=self.palette())

    def results_logic(self, screen):
        st = self.result or {'score': 0, 'answered': 0, 'best': 0, 'missed': [], 'seconds': 0}
        screen.set_strings({'t.complete': 32062, 't.r.score': 32024, 't.r.accuracy': 32030, 't.r.best': 32031,
                            't.r.time': 32032, 't.review': 32034, 't.new': 32035, 't.decks': 32036})
        screen.prop('r.score', '%d / %d' % (st['score'], st['answered']))
        screen.prop('r.accuracy', '%d%%' % round(100.0 * st['score'] / st['answered']) if st['answered'] else '-')
        screen.prop('r.best', st['best'])
        seconds = int(st.get('seconds', 0))
        screen.prop('r.time', '%d:%02d' % (seconds // 60, seconds % 60))
        screen.prop('r.deck', ', '.join(d.title for d in self.chosen_decks()))
        missed = st['missed']
        screen.prop('r.missed', '1' if missed else '')
        screen.prop('r.missed_head', '%s (%d)' % (kodi.tr(32033), len(missed)) if missed else kodi.tr(32048))
        items = []
        for c in missed:
            items.append(xbmcgui.ListItem(c.question.replace('\n', ' '), c.answer.replace('\n', ' ')))
        screen.getControl(50).addItems(items)
        screen.focus(72)
        while True:
            event = screen.wait(3600)
            if is_back(event) or clicked(event, 73):
                self.review = None
                return 'decks'
            if clicked(event, 71) and missed:
                self.review = list(missed)
                return 'study'
            if clicked(event, 72):
                self.review = None
                return 'study'


def main(args):
    if args:
        from sheetcards import actions
        actions.run(APP_ID, args[0])
        return
    App().run()

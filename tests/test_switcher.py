"""Offline tests for Screensaver Switcher's schedule.

python3 -m unittest tests.test_switcher
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'service.screensaver.switcher'))

from resources.lib import config, schedule  # noqa: E402


def at(text):
    return schedule.minutes(text)


def settings(*windows, default=''):
    s = config.defaults()
    s['default_screensaver'] = default
    for n, (start, end, screensaver) in enumerate(windows, 1):
        s.update({'w%d_on' % n: True, 'w%d_start' % n: start, 'w%d_end' % n: end,
                  'w%d_screensaver' % n: screensaver})
    return s


class Minutes(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(at('00:00'), 0)
        self.assertEqual(at('08:30'), 510)
        self.assertEqual(at(' 23:59 '), 1439)
        self.assertEqual(at('7:05'), 425)

    def test_bad(self):
        for text in ('', '24:00', '12:60', 'noon', None, '12'):
            self.assertIsNone(at(text), text)


class Wanted(unittest.TestCase):
    def test_defaults_do_nothing(self):
        self.assertEqual(schedule.wanted(config.defaults(), at('12:00')), (0, ''))

    def test_day_window(self):
        s = settings(('08:00', '17:00', 'a'), default='z')
        self.assertEqual(schedule.wanted(s, at('07:59')), (0, 'z'))
        self.assertEqual(schedule.wanted(s, at('08:00')), (1, 'a'))
        self.assertEqual(schedule.wanted(s, at('16:59')), (1, 'a'))
        self.assertEqual(schedule.wanted(s, at('17:00')), (0, 'z'))

    def test_crosses_midnight(self):
        s = settings(('22:00', '06:00', 'night'), default='day')
        self.assertEqual(schedule.wanted(s, at('21:59'))[1], 'day')
        self.assertEqual(schedule.wanted(s, at('22:00'))[1], 'night')
        self.assertEqual(schedule.wanted(s, at('00:00'))[1], 'night')
        self.assertEqual(schedule.wanted(s, at('05:59'))[1], 'night')
        self.assertEqual(schedule.wanted(s, at('06:00'))[1], 'day')

    def test_all_day(self):
        s = settings(('09:00', '09:00', 'a'))
        for t in ('00:00', '09:00', '23:59'):
            self.assertEqual(schedule.wanted(s, at(t)), (1, 'a'))

    def test_lowest_window_wins(self):
        s = settings(('12:00', '13:00', 'lunch'), ('08:00', '17:00', 'work'))
        self.assertEqual(schedule.wanted(s, at('12:30')), (1, 'lunch'))
        self.assertEqual(schedule.wanted(s, at('13:00')), (2, 'work'))

    def test_skips_off_and_incomplete_windows(self):
        s = settings(('08:00', '17:00', 'a'), ('08:00', '17:00', ''), ('08:00', '17:00', 'c'), default='z')
        s['w1_on'] = False
        self.assertEqual(schedule.wanted(s, at('09:00')), (3, 'c'))
        s['w3_start'] = 'bad'
        self.assertEqual(schedule.wanted(s, at('09:00')), (0, 'z'))

    def test_full_day_partition(self):
        s = settings(('06:00', '12:00', 'a'), ('12:00', '18:00', 'b'), ('18:00', '06:00', 'c'))
        seen = [schedule.wanted(s, m)[1] for m in range(1440)]
        self.assertEqual(seen.count('a'), 360)
        self.assertEqual(seen.count('b'), 360)
        self.assertEqual(seen.count('c'), 720)


class Alternate(unittest.TestCase):
    def day(self, every=30):
        s = settings(('07:30', '19:00', 'eye'), ('19:00', '07:30', 'couch'))
        s['w1_alt'] = 'world'
        s['alternate_minutes'] = every
        return s

    def test_alternates_from_window_start(self):
        s = self.day()
        self.assertEqual(schedule.wanted(s, at('07:30')), (1, 'eye'))
        self.assertEqual(schedule.wanted(s, at('07:59')), (1, 'eye'))
        self.assertEqual(schedule.wanted(s, at('08:00')), (1, 'world'))
        self.assertEqual(schedule.wanted(s, at('08:30')), (1, 'eye'))
        self.assertEqual(schedule.wanted(s, at('18:29')), (1, 'world'))
        self.assertEqual(schedule.wanted(s, at('18:59')), (1, 'eye'))  # block 22 of 30 minutes
        self.assertEqual(schedule.wanted(s, at('19:00')), (2, 'couch'))

    def test_even_split(self):
        s = self.day(every=45)
        seen = [schedule.wanted(s, m)[1] for m in range(at('07:30'), at('19:00'))]
        changes = [i for i in range(1, len(seen)) if seen[i] != seen[i - 1]]
        self.assertEqual(changes, list(range(45, len(seen), 45)))

    def test_alternation_across_midnight(self):
        s = settings(('23:00', '01:00', 'a'))
        s['w1_alt'] = 'b'
        s['alternate_minutes'] = 60
        self.assertEqual(schedule.wanted(s, at('23:30'))[1], 'a')
        self.assertEqual(schedule.wanted(s, at('00:30'))[1], 'b')

    def test_same_or_missing_alternate_is_ignored(self):
        s = settings(('00:00', '00:00', 'a'))
        s['w1_alt'] = 'a'
        self.assertEqual(set(schedule.wanted(s, m)[1] for m in range(1440)), {'a'})
        s['w1_alt'] = ''
        self.assertEqual(set(schedule.wanted(s, m)[1] for m in range(1440)), {'a'})

    def test_alternate_alone(self):
        s = settings(('00:00', '00:00', ''))
        s['w1_alt'] = 'b'
        self.assertEqual(schedule.wanted(s, at('12:00')), (1, 'b'))


class Read(unittest.TestCase):
    def test_falls_back_to_defaults(self):
        def broken(_sid):
            raise RuntimeError
        self.assertEqual(config.read({'boolean': broken, 'string': broken}), config.defaults())

    def test_settings_count(self):
        self.assertEqual(len(list(config.all_settings())), 4 + 5 * config.SLOTS)

    def test_slider_clamped(self):
        s = config.read({'boolean': lambda _id: True, 'integer': lambda _id: 1, 'string': lambda _id: ''})
        self.assertEqual(s['alternate_minutes'], 5)


if __name__ == '__main__':
    unittest.main()

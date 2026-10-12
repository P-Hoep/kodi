"""Offline tests for Math Clock: every puzzle has one answer, the clock value, and typesets.

python3 -m unittest tests.test_mathclock
"""

import cmath
import datetime
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screensaver.math.clock'))

from resources.lib import clockface, config, equations, texmath  # noqa: E402

# ---------------------------------------------------------------- a solver for the puzzles
#
# Works from texmath's parse tree, so it checks what is actually typeset: converts each
# clause to Python, defines f(x) = ... and a_n = ..., and solves for the unknowns.

OPS = {'rm_plus': '+', 'sy_minus': '-', 'sy_times': '*', 'sy_div': '/', 'sy_cdot': '*', 'rm_percent': '%'}
RELS = {'rm_equal': '==', 'mi_greater': '>', 'mi_less': '<', 'sy_geq': '>=', 'sy_leq': '<='}
CONSTANTS = {'x': 2, 'e': math.e, 'i': 1j}     # x is the base in x^a x^b = x^h
SEARCH = range(-300, 2400)


def letter(node):
    if node[0] == 'sym' and node[2].startswith('mi_') and len(node[2]) in (4, 8) and node[2] not in ('mi_less',):
        return node[2][-1]
    return None


def is_sym(node, glyph):
    return node[0] == 'sym' and node[2] == glyph


def digit(node):
    return node[0] == 'sym' and node[2][:3] == 'rm_' and node[2][3:].isdigit()


def solid(nodes):
    return [n for n in nodes if n[0] != 'space']


def join(toks):
    out, prev = '', None
    for kind, text in toks:
        if prev in ('val', 'close') and kind in ('val', 'open', 'func'):
            out += '*'
        out += text
        prev = kind
    return out


class Puzzle(object):
    def __init__(self, latex):
        self.latex = latex
        self.funcs = set()
        self.env = dict(CONSTANTS, floor=math.floor, comb=math.comb, log=math.log, sqrt=math.sqrt,
                        factorial=math.factorial, abs=abs, root=lambda a, n: a ** (1.0 / n), log10=math.log10,
                        det=lambda m: m[0][0] * m[1][1] - m[0][1] * m[1][0],
                        div=lambda a, b: a // b if isinstance(a, int) and isinstance(b, int) and a % b == 0
                        else a / b)

    # -------------------------------------------------------- to Python

    def operand(self, nodes, j):
        while nodes[j][0] == 'space':
            j += 1
        if digit(nodes[j]) or (nodes[j][0] == 'scripts' and digit(nodes[j][1])):
            k = j
            while k < len(nodes) and digit(nodes[k]):
                k += 1
            if k < len(nodes) and nodes[k][0] == 'scripts' and digit(nodes[k][1]):
                k += 1
            return self.conv(nodes[j:k]), k
        if is_sym(nodes[j], 'rm_lparen'):
            depth, k = 0, j
            while True:
                n = nodes[k][1] if nodes[k][0] == 'scripts' else nodes[k]
                depth += is_sym(n, 'rm_lparen') - is_sym(n, 'rm_rparen')
                k += 1
                if depth == 0:
                    return self.conv(nodes[j:k]), k
        return self.conv([nodes[j]]), j + 1

    def conv(self, nodes):
        toks, digits = [], ''
        j = 0
        while j < len(nodes):
            n = nodes[j]
            kind = n[0]
            if digit(n):
                digits += n[2][3:]
                j += 1
                continue
            if digits and not (kind == 'scripts' and digit(n[1])):
                toks.append(('val', digits))
                digits = ''
            j += 1
            if kind == 'space':
                continue
            if kind == 'sym':
                g = n[2]
                name = letter(n)
                if name:
                    nxt = solid(nodes[j:])
                    callable_ = name in self.funcs and nxt and is_sym(nxt[0], 'rm_lparen')
                    toks.append(('func' if callable_ else 'val', name))
                elif g == 'rm_lparen':
                    toks.append(('open', '('))
                elif g == 'rm_rparen':
                    toks.append(('close', ')'))
                elif g in OPS:
                    toks.append(('op', OPS[g]))
                elif g in RELS:
                    toks.append(('op', RELS[g]))
                elif g == 'rm_exclam':
                    if toks[-1][0] == 'val':
                        toks[-1] = ('val', 'factorial(%s)' % toks[-1][1])
                    else:
                        depth, k = 0, len(toks) - 1
                        while True:
                            depth += (toks[k][0] == 'close') - (toks[k][0] == 'open')
                            if depth == 0:
                                break
                            k -= 1
                        toks[k:] = [('val', 'factorial(%s)' % join(toks[k:]))]
                else:
                    raise ValueError('symbol %s' % g)
            elif kind == 'word':
                if n[2] == 'mod':
                    toks.append(('op', '%'))
                else:
                    arg, j = self.operand(nodes, j)
                    toks.append(('val', '%s(%s)' % ('log10' if n[2] == 'log' else 'log', arg)))
            elif kind == 'scripts':
                base, sup, sub = n[1], n[2], n[3]
                if digit(base):
                    digits += base[2][3:]
                    toks.append(('val', '(%s**(%s))' % (digits, self.conv([sup]))))
                    digits = ''
                elif base[0] == 'bigop':
                    sub_nodes = solid(sub[1])
                    idx = letter(sub_nodes[0])
                    start = self.conv(sub_nodes[2:])
                    body, j = self.operand(nodes, j)
                    toks.append(('val', 'sum((%s) for %s in range(int(%s), int(%s) + 1))'
                                 % (body, idx, start, self.conv([sup]))))
                elif base[0] == 'word':
                    arg, j = self.operand(nodes, j)
                    toks.append(('val', 'log(%s, %s)' % (arg, self.conv([sub]))))
                elif letter(base) and sup and letter(base) in self.funcs:
                    toks.append(('func', 'inv_' + letter(base)))
                elif letter(base) and sub and letter(base) in self.funcs:
                    toks.append(('val', '%s(%s)' % (letter(base), self.conv([sub]))))
                elif is_sym(base, 'rm_rparen'):
                    toks += [('close', ')'), ('op', '**'), ('val', '(%s)' % self.conv([sup]))]
                else:
                    toks.append(('val', '((%s)**(%s))' % (self.conv([base]), self.conv([sup]))))
            elif kind == 'group':
                toks.append(('val', '(%s)' % self.conv(n[1])))
            elif kind == 'frac':
                toks.append(('val', 'div(%s, %s)' % (self.conv([n[1]]), self.conv([n[2]]))))
            elif kind == 'binom':
                toks.append(('val', 'comb(%s, %s)' % (self.conv([n[1]]), self.conv([n[2]]))))
            elif kind == 'sqrt':
                if n[2]:
                    toks.append(('val', 'root(%s, %s)' % (self.conv([n[1]]), self.conv([n[2]]))))
                else:
                    toks.append(('val', 'sqrt(%s)' % self.conv([n[1]])))
            elif kind == 'left':
                f = {'|': 'abs', '\\lfloor': 'floor', '(': ''}[n[1]]
                toks.append(('val', '%s(%s)' % (f, self.conv([n[2]]))))
            elif kind == 'matrix':
                rows = ', '.join('[%s]' % ', '.join(self.conv([c]) for c in r) for r in n[2])
                toks.append(('val', 'det([%s])' % rows))
            else:
                raise ValueError('node %s' % kind)
        if digits:
            toks.append(('val', digits))
        return join(toks)

    # -------------------------------------------------------- clauses

    def letters(self, node, out):
        if isinstance(node, tuple):
            if letter(node):
                out.add(letter(node))
            if node and node[0] == 'scripts' and node[1][0] == 'bigop':
                out.add('#' + letter(solid(node[3][1])[0]))      # a summation index
            for part in node[1:]:
                self.letters(part, out)
        elif isinstance(node, list):
            for part in node:
                self.letters(part, out)
        return out

    def solve(self, var):
        nodes = solid(texmath.parse(self.latex)[1])
        if any(n[0] == 'ldots' for n in nodes):
            colon = next(i for i, n in enumerate(nodes) if is_sym(n, 'rm_colon'))
            terms, cur = [], []
            for n in nodes[:colon]:
                if is_sym(n, 'mi_comma') or n[0] == 'ldots':
                    if cur:
                        terms.append(eval(self.conv(cur)))
                    cur = []
                else:
                    cur.append(n)
            t1, t2, t3 = terms[:3]
            if t2 - t1 == t3 - t2:
                self.env['a'] = lambda n, a=t1, d=t2 - t1: a + (n - 1) * d
            else:
                self.env['a'] = lambda n, a=t1, r=t2 // t1: a * r ** (n - 1)
            self.funcs.add('a')
            nodes = nodes[colon + 1:]
        clauses, cur = [], []
        for n in nodes:
            if is_sym(n, 'mi_comma'):
                clauses.append(cur)
                cur = []
            else:
                cur.append(n)
        clauses.append(cur)
        clauses = [solid(c) for c in clauses]
        # Function and sequence definitions first.
        rest = []
        for c in clauses:
            if len(c) > 4 and letter(c[0]) and is_sym(c[1], 'rm_lparen') and letter(c[2]) \
                    and is_sym(c[3], 'rm_rparen') and is_sym(c[4], 'rm_equal'):
                self.define(letter(c[0]), letter(c[2]), c[5:])
            elif self.sequence_param(c):
                self.define(letter(c[0][1]), self.sequence_param(c), c[2:])
            else:
                rest.append(c)
        known = set(CONSTANTS) | self.funcs
        unknowns = sorted(u for u in self.letters(rest, set()) - known if not u.startswith('#'))
        unknowns = [u for u in unknowns if '#' + u not in self.letters(rest, set())]
        exprs, tests = [], []
        for c in rest:
            rel = [i for i, n in enumerate(c) if n[0] == 'sym' and n[2] in RELS]
            if rel:
                i = rel[0]
                tests.append((self.conv(c[:i]), RELS[c[i][2]], self.conv(c[i + 1:])))
            else:
                exprs.append(self.conv(c))
        if not unknowns:
            assert len(exprs) == 1 and not tests, self.latex
            return self.value(eval(exprs[0], self.env))
        assert not exprs, self.latex
        args = ', '.join(unknowns)
        checks = [(eval('lambda %s: (%s, %s)' % (args, l, r), self.env), op) for l, op, r in tests]
        if len(unknowns) == 2:
            return self.solve_linear(checks)[unknowns.index(var)]
        assert unknowns == [var], '%s: unknowns %s' % (self.latex, unknowns)
        hits = [u for u in SEARCH if self.holds(checks, (u,))]
        assert len(hits) == 1, '%s: solutions %s' % (self.latex, hits[:5])
        return hits[0]

    def sequence_param(self, c):
        """'n' for a definition a_n = <something with n>; None otherwise (a_{h} = 9)."""
        if len(c) < 3 or c[0][0] != 'scripts' or not letter(c[0][1]) or not c[0][3] or not is_sym(c[1], 'rm_equal'):
            return None
        sub = c[0][3]
        param = letter(solid(sub[1])[0]) if sub[0] == 'group' else letter(sub)
        return param if param and param in self.letters(c[2:], set()) else None

    def define(self, name, param, body):
        self.funcs.add(name)
        self.env[name] = eval('lambda %s: %s' % (param, self.conv(body)), self.env)
        f = self.env[name]
        self.env['inv_' + name] = lambda q, f=f: next(x for x in SEARCH if f(x) == q)

    @staticmethod
    def value(v):
        if isinstance(v, complex):
            assert abs(v.imag) < 1e-9
            v = v.real
        return v

    @staticmethod
    def holds(checks, args):
        for fn, op in checks:
            try:
                l, r = fn(*args)
                if op != '==':
                    ok = eval('l %s r' % op)
                elif isinstance(l, int) and isinstance(r, int):
                    ok = l == r
                else:
                    ok = abs(l - r) <= 1e-9 * max(1, abs(r))
            except (ValueError, ZeroDivisionError, OverflowError, TypeError):
                return False
            if not ok:
                return False
        return True

    def solve_linear(self, checks):
        eqs = [fn for fn, op in checks if op == '==']
        rows = []
        for fn in eqs:
            r = lambda a, b, fn=fn: (lambda lr: lr[0] - lr[1])(fn(a, b))
            c0 = r(0, 0)
            rows.append((r(1, 0) - c0, r(0, 1) - c0, -c0))
        (a1, b1, c1), (a2, b2, c2) = rows
        d = a1 * b2 - a2 * b1
        assert d, self.latex
        x, y = (c1 * b2 - c2 * b1) / d, (a1 * c2 - a2 * c1) / d
        assert self.holds(checks, (x, y)), self.latex
        return x, y


def solve(latex, var):
    return Puzzle(latex).solve(var)


class Equations(unittest.TestCase):
    VALUES = list(range(0, 61)) + [2025, 2026, 2099]

    def check(self, gens, var):
        rng = random.Random(3)
        for gen in gens:
            fits = 0
            for v in self.VALUES:
                for _ in range(3):
                    latex = gen(v, var, rng)
                    if latex is None:
                        continue
                    fits += 1
                    got = solve(latex, var)
                    self.assertAlmostEqual(got, v, msg='%s(%d) -> %s = %s' % (gen.__name__, v, latex, got),
                                           delta=1e-6 * max(1, v))
                    box = texmath.typeset(latex)
                    self.assertGreater(box.width, 0)
            self.assertTrue(fits, gen.__name__)

    def test_classic_and_advanced(self):
        self.check(equations.CLASSIC + equations.ADVANCED, 'h')

    def test_algebra2(self):
        for var in ('h', 'm', 'M', 'y'):
            self.check(equations.ALGEBRA2, var)

    def test_make_always_returns(self):
        rng = random.Random(1)
        for gens in equations.SETS:
            for v in (0, 1, 13, 59, 2026):
                self.assertTrue(equations.make(v, 'm', gens, rng))


class TeX(unittest.TestCase):
    def test_unary_minus_is_tighter_than_binary(self):
        unary = texmath.typeset('-5')
        binary = texmath.typeset('3 - 5')
        three = texmath.typeset('3')
        self.assertGreater(binary.width - three.width - unary.width, 0.4)

    def test_constructs_have_sensible_extents(self):
        self.assertGreater(texmath.typeset(r'\frac{84}{7}').depth, 0.5)
        self.assertGreater(texmath.typeset(r'\sum_{i=1}^{9} i').height, 1.2)
        sq = texmath.typeset(r'\sqrt{144}')
        rules = [it for it in sq.items if it[0] is None]
        self.assertEqual(len(rules), 1)
        self.assertGreater(rules[0][3], texmath.typeset('144').width)

    def test_bad_input(self):
        for bad in (r'\frac{1}', '{1', r'\nope', r'\left( 1'):
            self.assertRaises(texmath.TexError, texmath.typeset, bad)


class Face(unittest.TestCase):
    def setUp(self):
        self.s = config.defaults()

    def test_rows_and_values(self):
        now = datetime.datetime(2026, 10, 11, 0, 7, 9)
        self.assertEqual(clockface.rows(self.s), ['year', 'month', 'day', 'hours', 'minutes', 'seconds'])
        self.assertEqual(clockface.value('hours', now, False), 12)
        self.assertEqual(clockface.value('hours', now, True), 0)
        self.assertEqual(clockface.value('hours', now.replace(hour=13), False), 1)
        self.s.update(date=False, seconds=False)
        self.assertEqual(clockface.rows(self.s), ['hours', 'minutes'])

    def test_day_night(self):
        self.s['colours'] = 2
        self.assertFalse(clockface.is_dark(self.s, datetime.datetime(2026, 1, 1, 8)))
        self.assertFalse(clockface.is_dark(self.s, datetime.datetime(2026, 1, 1, 16, 59)))
        self.assertTrue(clockface.is_dark(self.s, datetime.datetime(2026, 1, 1, 17)))
        self.assertTrue(clockface.is_dark(self.s, datetime.datetime(2026, 1, 1, 7, 59)))

    def test_everything_fits_on_screen(self):
        rng = random.Random(5)
        now = datetime.datetime(2026, 12, 31, 23, 59, 59)
        for size in (60, 100, 140):
            geo = clockface.Geometry(6, size, (36, 24))
            for i, kind in enumerate(clockface.rows(self.s)):
                for _ in range(40):
                    self.s['equation_set'] = 1
                    box = texmath.typeset(clockface.puzzle(kind, now, self.s, rng))
                    top = geo.centre(i) - geo.pitch / 2
                    for _n, x, y, w, h in geo.rects(box, i):
                        self.assertTrue(0 <= x and x + w <= clockface.W)
                        self.assertTrue(top - 2 <= y and y + h <= top + geo.pitch + 2, (kind, size))

    def test_settings_defaults_load(self):
        s = config.read({'boolean': lambda k: 1 / 0, 'integer': lambda k: 999})
        self.assertEqual(s['colours'], 1)
        self.assertEqual(s['text_size'], 140)


if __name__ == '__main__':
    unittest.main()

"""The clock's puzzles: each generator turns a value (an hour, a minute, a year...) into a
LaTeX expression or equation whose answer is that value. No Kodi imports.

CLASSIC is a one-for-one port of themathclock.com's script.js (mathclock-old/), in the
same order. A generator returns None when it does not fit the value (a perfect square, an
odd number, a factorial...) and the caller picks another, as the original did by
recursing into a random function.

ADVANCED adds fractions, powers, logarithms, sums, binomials and floors.
"""

import math
import random


def rint(rng, top):
    """1..top inclusive, as getRandomInt(max) in the original."""
    return rng.randint(1, top)


def _neg(n):
    """Numbers are typed straight into the LaTeX, so negatives come out as '-5'."""
    return str(n)


# ---------------------------------------------------------------- the original set

def c_var_minus(v, var, rng):
    r = rint(rng, 25)
    return '%s - %d = %s' % (var, r, _neg(v - r))


def c_minus_var(v, var, rng):
    r = rint(rng, 25)
    return '%d - %s = %s' % (r, var, _neg(r - v))


def c_var_plus(v, var, rng):
    r = rint(rng, 25)
    return '%s + %d = %d' % (var, r, v + r)


def c_plus_var(v, var, rng):
    r = rint(rng, 25)
    return '%d + %s = %d' % (r, var, v + r)


def c_times(v, var, rng):
    r = rint(rng, 5)
    return '%s \\times %d = %d' % (var, r, v * r)


def c_divide(v, var, rng):
    r = rint(rng, 5)
    return '%d \\div %d = %s' % (r * v, r, var)


def c_sum(v, var, rng):
    r = rint(rng, 20)
    return '%s + %d' % (_neg(v - r), r)


def c_difference(v, var, rng):
    r = rint(rng, 20)
    return '%d - %d' % (v + r, r)


def c_three_terms(v, var, rng):
    a, s = rint(rng, 20), rint(rng, 20)
    return '%s - %d + %d' % (_neg(v + s - a), s, a)


def c_sqrt_square(v, var, rng):
    return '\\sqrt{%d}' % (v * v)


def c_square(v, var, rng):
    root = math.isqrt(v) if v >= 0 else -1
    return '%d^2' % root if root >= 0 and root * root == v else None


def c_sqrt_product(v, var, rng):
    return '\\sqrt{%d} \\times \\sqrt{%d}' % (v, v)


def c_odd(v, var, rng):
    return '(%d \\times 2) + 1' % ((v - 1) // 2) if v % 2 == 1 else None


def c_cube(v, var, rng):
    root = int(round(abs(v) ** (1 / 3.0)))
    return '%d^3' % root if root ** 3 == v else None


def c_factorial(v, var, rng):
    return {1: '1!', 2: '2!', 6: '3!', 24: '4!'}.get(v)


def c_modulo(v, var, rng):
    return '%d \\%% %d' % (2 * v + 1, v + 1)


# themathclock.com's array_of_functions has the subtract-from-sum generator twice
# (functions 7 and 10), which makes "a - b" puzzles a little more common; kept.
CLASSIC = [c_var_minus, c_minus_var, c_var_plus, c_plus_var, c_times, c_divide, c_sum,
           c_difference, c_three_terms, c_difference, c_sqrt_square, c_square, c_sqrt_product,
           c_odd, c_cube, c_factorial, c_modulo]


# ---------------------------------------------------------------- additions

def a_fraction(v, var, rng):
    k = rng.randint(2, 9)
    return '\\frac{%d}{%d}' % (v * k, k)


def a_fraction_sum(v, var, rng):
    d = rng.randint(2, 7)
    total = v * d
    if total < 2:
        return None
    a = rng.randint(1, total - 1)
    return '\\frac{%d}{%d} + \\frac{%d}{%d}' % (a, d, total - a, d)


def a_power_of_two(v, var, rng):
    if v < 2 or v & (v - 1):
        return None
    return '2^{%d}' % (v.bit_length() - 1)


def a_log(v, var, rng):
    if v < 1:
        return None
    b = rng.choice([2, 3, 10])
    if b ** v > 10 ** 6:
        return None     # '\\log_3 3^{2026}' gives the answer away
    return '\\log_{%d} %d' % (b, b ** v)


def a_sum_ones(v, var, rng):
    if v < 1:
        return None
    a = rng.randint(1, 5)
    return '\\sum_{i=%d}^{%d} 1' % (a, a + v - 1)


def a_triangular(v, var, rng):
    n = int((math.sqrt(8 * v + 1) - 1) / 2) if v > 0 else 0
    return '\\sum_{i=1}^{%d} i' % n if n > 1 and n * (n + 1) // 2 == v else None


def a_binom(v, var, rng):
    for n in range(2, 80):
        if n * (n - 1) // 2 == v and v > 1:
            return '\\binom{%d}{2}' % n
    return None


def a_floor(v, var, rng):
    k = rng.randint(2, 5)
    return '\\left\\lfloor \\frac{%d}{%d} \\right\\rfloor' % (v * k + rng.randint(1, k - 1), k)


def a_abs(v, var, rng):
    r = rint(rng, 20)
    return '\\left| %d - %d \\right|' % (r, r + v)


def a_square_diff(v, var, rng):
    # a^2 - b^2 = (a-b)(a+b) = v with a - b = 1: a = (v+1)/2
    if v % 2 == 0 or v < 3:
        return None
    a = (v + 1) // 2
    return '%d^2 - %d^2' % (a, a - 1)


def a_equation(v, var, rng):
    k, r = rng.randint(2, 6), rint(rng, 20)
    return '%d%s + %d = %d' % (k, var, r, k * v + r)


def a_mean(v, var, rng):
    d = rng.randint(1, 9)
    return '\\frac{%d + %d}{2}' % (v - d, v + d)


ADVANCED = [a_fraction, a_fraction_sum, a_power_of_two, a_log, a_sum_ones, a_triangular,
            a_binom, a_floor, a_abs, a_square_diff, a_equation, a_mean]


# ---------------------------------------------------------------- Algebra 2
#
# Every equation has exactly one solution: when a quadratic or an absolute value has
# two, a condition such as "h > 4" picks the clock's value. Unknowns other than the
# clock's variable are k (or n), and function definitions use x.

LIMIT = 10 ** 7     # keep numbers readable on a TV


def poly(terms, var):
    """[(coefficient, power), ...] -> '3x^2 - x + 5'. Zero terms are dropped."""
    out = ''
    for coef, power in terms:
        if coef == 0:
            continue
        body = '' if power == 0 else var if power == 1 else '%s^{%d}' % (var, power)
        mag = abs(coef)
        text = (str(mag) if mag != 1 or not body else '') + body
        if not out:
            out = ('-' if coef < 0 else '') + text
        else:
            out += (' - ' if coef < 0 else ' + ') + text
    return out or '0'


def signed(n):
    """' + 5' or ' - 5' (nothing for 0)."""
    return '' if n == 0 else (' + %d' % n if n > 0 else ' - %d' % -n)


def other(var):
    return 'n' if var == 'k' else 'k'


def q_factor(v, var, rng):
    """Quadratic with roots v and r; the condition picks v."""
    r = rng.randint(1, 12)
    if r == v:
        return None
    cond = '>' if v > r else '<'
    return '%s = 0,\\; %s %s %d' % (poly([(1, 2), (-(v + r), 1), (v * r, 0)], var), var, cond, r)


def q_negative_root(v, var, rng):
    """Roots v and -r, so 'var >= 0' picks v."""
    r = rng.randint(1, 9)
    return '%s = 0,\\; %s \\ge 0' % (poly([(1, 2), (r - v, 1), (-v * r, 0)], var), var)


def q_perfect_square(v, var, rng):
    a = rng.randint(1, 3)
    return '%s = 0' % poly([(a * a, 2), (-2 * a * a * v, 1), (a * a * v * v, 0)], var)


def q_formula(v, var, rng):
    """The quadratic formula, worked: roots v and k of x^2 - (v+k)x + vk."""
    if not 2 <= v <= 99:
        return None
    k = rng.randint(1, v - 1)
    s, p = v + k, v * k
    return '\\frac{%d + \\sqrt{%d^2 - 4 \\cdot %d}}{2}' % (s, s, p)


def sys_linear(v, var, rng):
    """Two linear equations in var and k."""
    k = rng.randint(1, 12)
    while True:
        a1, a2 = rng.randint(1, 3), rng.randint(1, 3)
        b1, b2 = [rng.choice([-3, -2, -1, 1, 2, 3]) for _ in range(2)]
        if a1 * b2 - a2 * b1:
            break
    o = other(var)
    eq = lambda a, b: '%s = %d' % (_lin(a, var, b, o), a * v + b * k)
    return '%s,\\; %s' % (eq(a1, b1), eq(a2, b2))


def _lin(a, x, b, y):
    """'2h - 3k'"""
    first = poly([(a, 1)], x)
    return first + (' - ' if b < 0 else ' + ') + (str(abs(b)) if abs(b) != 1 else '') + y


def exp_shift(v, var, rng):
    """b^(var - s) = b^e"""
    b = rng.choice([2, 3, 5])
    top = {2: 12, 3: 8, 5: 5}[b]
    e = rng.randint(1, min(top, v + 9)) if v >= -8 else None
    if e is None:
        return None
    s = v - e
    return '%d^{%s%s} = %d' % (b, var, signed(-s), b ** e)


def exp_rebase(v, var, rng):
    """4^var = 2^(2v), 27^var = 3^(3v)..."""
    b, p = rng.choice([(2, 2), (2, 3), (3, 2), (2, 4), (3, 3)])
    return '%d^{%s} = %d^{%d}' % (b ** p, var, b, p * v)


def log_equation(v, var, rng):
    """log_b(var + k) = n"""
    if v < 1:
        return None
    b = rng.choice([2, 3, 10]) if v < 900 else rng.choice([2, 10])
    n = 1
    while b ** n <= v:
        n += 1
    k = b ** n - v
    base = '' if b == 10 else '_{%d}' % b
    return '\\log%s (%s + %d) = %d' % (base, var, k, n)


def log_product(v, var, rng):
    """log_b var + log_b k = log_b (vk)"""
    if v < 1:
        return None
    b, k = rng.choice([2, 3, 5]), rng.randint(2, 9)
    return '\\log_{%d} %s + \\log_{%d} %d = \\log_{%d} %d' % (b, var, b, k, b, v * k)


def log_rules(v, var, rng):
    """log_b A + log_b B or log_b A - log_b B, both whole powers of b."""
    b = rng.choice([2, 3])
    top = {2: 16, 3: 10}[b]
    if rng.random() < 0.5 and 2 <= v <= 2 * top - 2:
        a = rng.randint(max(1, v - top), min(top, v - 1))
        return '\\log_{%d} %d + \\log_{%d} %d' % (b, b ** a, b, b ** (v - a))
    if 0 <= v <= top - 1:
        a = rng.randint(1, top - v)
        return '\\log_{%d} %d - \\log_{%d} %d' % (b, b ** (v + a), b, b ** a)
    return None


def log_power(v, var, rng):
    """log_b (b^a)^c = a*c, or ln e^v."""
    if v >= 2 and rng.random() < 0.7:
        divisors = [d for d in range(2, min(v, 12) + 1) if v % d == 0 and v // d <= 10]
        if divisors:
            c = rng.choice(divisors)
            b = rng.choice([2, 3])
            return '\\log_{%d} \\left(%d^{%d}\\right)' % (b, b ** (v // c), c) if b ** (v // c) < LIMIT else None
    return '\\ln e^{%d}' % v if v < 100 else None


def rational_exponent(v, var, rng):
    """(c^q)^(p/q) = c^p = v."""
    if v < 2:
        return None
    options = [(v, 1)]
    for p in (2, 3):
        c = int(round(v ** (1.0 / p)))
        if c >= 2 and c ** p == v:
            options.append((c, p))
    c, p = rng.choice(options)
    q = rng.choice([q for q in (2, 3, 4) if q != p and (c ** q) < LIMIT] or [None])
    if q is None:
        return None
    return '%d^{\\frac{%d}{%d}}' % (c ** q, p, q)


def nth_root(v, var, rng):
    if v < 2:
        return None
    n = rng.choice([3, 4, 5])
    return '\\sqrt[%d]{%d}' % (n, v ** n) if v ** n < LIMIT else None


def radical_equation(v, var, rng):
    """sqrt(var + k) = n, or sqrt(a*var + k) = n."""
    a = rng.choice([1, 1, 2, 3])
    n = int(math.sqrt(a * v)) + rng.randint(1, 3)
    k = n * n - a * v
    return '\\sqrt{%s%s} = %d' % (poly([(a, 1)], var), signed(k), n)


def rational_equation(v, var, rng):
    """a / (var - k) = c"""
    if v < 1:
        return None
    k = rng.randint(0, v - 1)
    c = rng.randint(2, 6)
    den = var + signed(-k)
    return '\\frac{%d}{%s} = %d' % (c * (v - k), den, c)


def abs_equation(v, var, rng):
    """|var - k| = d with a condition choosing the right root."""
    k = rng.randint(1, 20)
    if k == v:
        return None
    return '\\left|%s - %d\\right| = %d,\\; %s %s %d' % (var, k, abs(v - k), var, '>' if v > k else '<', k)


def func_eval(v, var, rng):
    """f(x) = quadratic or cubic, f(a)."""
    a = rng.randint(2, 5)
    if rng.random() < 0.6:
        b = rng.randint(-6, 6)
        c = v - a * a - b * a
        return 'f(x) = %s,\\; f(%d)' % (poly([(1, 2), (b, 1), (c, 0)], 'x'), a)
    a = rng.randint(1, 3)
    b = rng.randint(-4, 4)
    c = v - a ** 3 - b * a
    return 'P(x) = %s,\\; P(%d)' % (poly([(1, 3), (b, 1), (c, 0)], 'x'), a)


def func_compose(v, var, rng):
    """f(g(a)) with f linear and g quadratic."""
    m, a, n = rng.randint(2, 3), rng.randint(1, 4), rng.randint(-3, 3)
    p = v - m * (a * a + n)
    return 'f(x) = %s,\\; g(x) = %s,\\; f(g(%d))' % (poly([(m, 1), (p, 0)], 'x'),
                                                     poly([(1, 2), (n, 0)], 'x'), a)


def func_inverse(v, var, rng):
    m, p = rng.randint(2, 5), rng.randint(-9, 9)
    return 'f(x) = %s,\\; f^{-1}(%d)' % (poly([(m, 1), (p, 0)], 'x'), m * v + p)


def complex_modulus(v, var, rng):
    """|a + bi| = v for a Pythagorean pair, else (a + bi)(a - bi) = a^2 + b^2 = v."""
    pairs = [(a, b) for a in range(1, v) for b in range(a, v) if a * a + b * b == v * v] if 0 < v < 200 else []
    if pairs and rng.random() < 0.6:
        a, b = rng.choice(pairs)
        if rng.random() < 0.5:
            a, b = b, a
        return '\\left|%d + %di\\right|' % (a, b)
    sums = [(a, b) for a in range(1, int(math.sqrt(v)) + 1) for b in range(1, int(math.sqrt(v)) + 1)
            if a * a + b * b == v]
    if sums:
        a, b = rng.choice(sums)
        return '(%d + %di)(%d - %di)' % (a, b, a, b)
    return None


def complex_i_squared(v, var, rng):
    """-c i^2 + d = c + d, since i^2 = -1."""
    c = rng.randint(1, 9)
    return '%si^{2} + %d' % ('-' if c == 1 else '-%d ' % c, v - c) if v - c > 0 else None


def arith_sequence(v, var, rng):
    """a_n = dn + c, with var the index of a given term."""
    if v < 1:
        return None
    d, c = rng.randint(2, 9), rng.randint(-9, 9)
    return 'a_n = %s,\\; a_{%s} = %d' % (poly([(d, 1), (c, 0)], 'n'), var, d * v + c)


def arith_term(v, var, rng):
    """First terms of an arithmetic sequence and the term asked for."""
    d, n = rng.randint(2, 9), rng.randint(5, 12)
    a1 = v - (n - 1) * d
    return '%d, %d, %d, \\ldots:\\; a_{%d}' % (a1, a1 + d, a1 + 2 * d, n)


def geo_sequence(v, var, rng):
    """a_n = c * r^(n-1): a term, or the index of a term."""
    if 1 <= v <= 14 and rng.random() < 0.5:
        c, r = rng.randint(1, 5), 2
        return 'a_n = %d \\cdot %d^{n - 1},\\; a_{%s} = %d' % (c, r, var, c * r ** (v - 1))
    for _ in range(10):
        r, n = rng.choice([2, 3]), rng.randint(4, 7)    # past the three terms shown
        if v > 0 and v % (r ** (n - 1)) == 0:
            c = v // r ** (n - 1)
            return '%d, %d, %d, \\ldots:\\; a_{%d}' % (c, c * r, c * r * r, n)
    return None


def arith_series(v, var, rng):
    """sum_{k=1}^{n} (dk + c) = v."""
    for _ in range(20):
        n, d = rng.randint(2, 6), rng.randint(1, 4)
        rest = v - d * n * (n + 1) // 2
        if rest % n == 0:
            c = rest // n
            return '\\sum_{k=1}^{%d} (%s)' % (n, poly([(d, 1), (c, 0)], 'k'))
    return None


def odd_series(v, var, rng):
    """1 + 3 + 5 + ... = n^2, or a geometric sum 2^0 + ... + 2^n = 2^(n+1) - 1."""
    n = int(math.sqrt(v)) if v > 0 else 0
    if n >= 2 and n * n == v:
        return '\\sum_{k=1}^{%d} (2k - 1)' % n
    m = (v + 1).bit_length() - 1
    if v >= 3 and 2 ** m == v + 1:
        return '\\sum_{k=0}^{%d} 2^k' % (m - 1)
    return None


def determinant(v, var, rng):
    for _ in range(30):
        a, d, b = rng.randint(2, 9), rng.randint(2, 9), rng.randint(1, 6)
        if (a * d - v) % b == 0:
            c = (a * d - v) // b
            return '\\begin{vmatrix} %d & %d \\\\ %d & %d \\end{vmatrix}' % (a, b, c, d)
    return None


def permutation(v, var, rng):
    """n!/(n-r)! = v, or C(n, k) = v with 3 <= k <= n-3."""
    hits = []
    for n in range(3, 30):
        p = 1
        for r in range(1, n):
            p *= n - r + 1
            if p == v and r >= 2:
                hits.append('\\frac{%d!}{%d!}' % (n, n - r))
            if p > v:
                break
        for k in range(3, n - 2):
            if math.factorial(n) // (math.factorial(k) * math.factorial(n - k)) == v:
                hits.append('\\binom{%d}{%d}' % (n, k))
    return rng.choice(hits) if hits else None


def exponent_rules(v, var, rng):
    """x^a x^b = x^var, x^a / x^b = x^var or (x^a)^b = x^var."""
    pick = rng.random()
    if pick < 0.4 and v >= 2:
        a = rng.randint(1, v - 1)
        return 'x^{%d} \\cdot x^{%d} = x^{%s}' % (a, v - a, var)
    if pick < 0.7:
        b = rng.randint(1, 9)
        return '\\frac{x^{%d}}{x^{%d}} = x^{%s}' % (v + b, b, var)
    divisors = [d for d in range(2, 10) if v and v % d == 0 and v // d > 1]
    if not divisors:
        return None
    b = rng.choice(divisors)
    return '\\left(x^{%d}\\right)^{%d} = x^{%s}' % (v // b, b, var)


ALGEBRA2 = [q_factor, q_negative_root, q_perfect_square, q_formula, sys_linear,
            exp_shift, exp_rebase, log_equation, log_product, log_rules, log_power,
            rational_exponent, nth_root, radical_equation, rational_equation, abs_equation,
            func_eval, func_compose, func_inverse, complex_modulus, complex_i_squared,
            arith_sequence, arith_term, geo_sequence, arith_series, odd_series, determinant,
            permutation, exponent_rules]

# Each level keeps the easier puzzles and adds harder ones; every generator is equally
# likely, so Algebra 2 is about half Algebra 2 puzzles and half earlier ones.
SETS = [CLASSIC, CLASSIC + ADVANCED, ADVANCED, CLASSIC + ADVANCED + ALGEBRA2]
SET_NAMES = ['Classic (as themathclock.com)', 'Classic and advanced', 'Advanced only',
             'Algebra 2 (with the classic and advanced ones)']


def make(value, variable, generators=CLASSIC, rng=random):
    """A random LaTeX puzzle whose answer is value. Falls back to the plain number."""
    for _ in range(40):
        latex = rng.choice(generators)(value, variable, rng)
        if latex:
            return latex
    return str(value)

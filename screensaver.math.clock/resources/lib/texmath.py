"""A small TeX math typesetter: parses the subset of LaTeX the clock's equations use and
lays it out the way TeX (and MathJax) would in display style, as positioned glyph
images and rules. No Kodi imports.

Supported: digits, italic letters, + - = < > \\le \\ge \\times \\div \\cdot \\circ \\pm \\% !
| ( ) [ ] , \\ldots, {groups}, ^ and _, \\sqrt{} and \\sqrt[n]{}, \\frac{}{}, \\binom{}{},
\\sum with limits, \\log, \\ln, \\bmod, \\left/\\right with ( ) [ ] | \\lfloor \\rfloor,
matrix/pmatrix/bmatrix/vmatrix environments, and the spaces \\, \\: \\; \\quad.

typeset(latex) returns a Box whose items are (glyph or None, left, top, width, height)
in em, y up from the baseline; None is a solid rule.
"""

import re

from .glyphs import GLYPHS, PAD

AXIS = 0.25          # height of the math axis (where fraction bars and minus signs sit)
RULE = 0.04          # default rule thickness: fraction bars and radical vinculums
XHEIGHT = 0.4306
NULL_DELIM = 0.12
SCRIPT_SPACE = 0.05
THIN, MED, THICK = 3 / 18.0, 4 / 18.0, 5 / 18.0
SCALE = {'D': 1.0, 'T': 1.0, 'S': 0.7, 'SS': 0.5}
SMALLER = {'D': 'T', 'T': 'S', 'S': 'SS', 'SS': 'SS'}   # numerator/denominator style
SCRIPT = {'D': 'S', 'T': 'S', 'S': 'SS', 'SS': 'SS'}

SYMBOLS = {   # token -> (atom class, glyph)
    '+': ('bin', 'rm_plus'), '-': ('bin', 'sy_minus'), '=': ('rel', 'rm_equal'),
    '(': ('open', 'rm_lparen'), ')': ('close', 'rm_rparen'), '[': ('open', 'rm_lbrack'),
    ']': ('close', 'rm_rbrack'), '!': ('close', 'rm_exclam'), '|': ('ord', 'sy_vert'),
    ',': ('punct', 'mi_comma'), '.': ('ord', 'mi_period'), ':': ('rel', 'rm_colon'),
    '\\times': ('bin', 'sy_times'), '\\div': ('bin', 'sy_div'), '\\cdot': ('bin', 'sy_cdot'),
    '\\pm': ('bin', 'sy_pm'), '\\%': ('bin', 'rm_percent'),   # the clock's modulo operator
    '\\lfloor': ('open', 'sy_lfloor'), '\\rfloor': ('close', 'sy_rfloor'),
    '\\vert': ('ord', 'sy_vert'), '<': ('rel', 'mi_less'), '>': ('rel', 'mi_greater'),
    '\\le': ('rel', 'sy_leq'), '\\leq': ('rel', 'sy_leq'), '\\ge': ('rel', 'sy_geq'),
    '\\geq': ('rel', 'sy_geq'), '\\circ': ('bin', 'sy_circ'),
}
WORDS = {'\\log': ('op', 'log'), '\\ln': ('op', 'ln'), '\\bmod': ('bin', 'mod')}
SPACES = {'\\,': THIN, '\\:': MED, '\\;': THICK, '\\quad': 1.0, '\\ ': 0.25}
DELIMS = {   # \left / \right delimiters: glyphs from smallest to largest
    '(': ['rm_lparen', 'ex_lparen1', 'ex_lparen2', 'ex_lparen3', 'ex_lparen4'],
    ')': ['rm_rparen', 'ex_rparen1', 'ex_rparen2', 'ex_rparen3', 'ex_rparen4'],
    '[': ['rm_lbrack', 'ex_lbrack1', 'ex_lbrack2', 'ex_lbrack3'],
    ']': ['rm_rbrack', 'ex_rbrack1', 'ex_rbrack2', 'ex_rbrack3'], '|': ['sy_vert'], '\\vert': ['sy_vert'],
    '\\lfloor': ['sy_lfloor', 'ex_lfloor1', 'ex_lfloor2', 'ex_lfloor3', 'ex_lfloor4'],
    '\\rfloor': ['sy_rfloor', 'ex_rfloor1', 'ex_rfloor2', 'ex_rfloor3', 'ex_rfloor4'],
}
SURDS = ['sy_surd', 'ex_surd1', 'ex_surd2', 'ex_surd3', 'ex_surd4']
MATRICES = {'matrix': ('.', '.'), 'pmatrix': ('(', ')'), 'bmatrix': ('[', ']'), 'vmatrix': ('|', '|')}

# TeX's spacing between atom classes (ord op bin rel open close punct inner); 'm' and 't'
# are dropped in script styles.
_CLASSES = ['ord', 'op', 'bin', 'rel', 'open', 'close', 'punct', 'inner']
_SPACING = {
    'ord':   ['', 's', 'm', 't', '', '', '', 's'],
    'op':    ['s', 's', '', 't', '', '', '', 's'],
    'bin':   ['m', 'm', '', '', 'm', '', '', 'm'],
    'rel':   ['t', 't', '', '', 't', '', '', 't'],
    'open':  ['', '', '', '', '', '', '', ''],
    'close': ['', 's', 'm', 't', '', '', '', 's'],
    'punct': ['s', 's', '', 's', 's', 's', 's', 's'],
    'inner': ['s', 's', 'm', 't', 's', '', 's', 's'],
}


class TexError(ValueError):
    pass


class Box(object):
    def __init__(self, width=0.0, height=0.0, depth=0.0, items=None, cls='ord'):
        self.width, self.height, self.depth = width, height, depth
        self.items = items or []
        self.cls = cls

    def place(self, dx, dy):
        """This box's items moved right by dx and up by dy."""
        return [(n, l + dx, t + dy, w, h) for n, l, t, w, h in self.items]


def glyph_box(name, scale, cls='ord'):
    adv, left, top, right, bottom = GLYPHS[name]
    item = (name, left * scale, top * scale, (right - left) * scale, (top - bottom) * scale)
    return Box(adv * scale, (top - PAD) * scale, -(bottom + PAD) * scale, [item], cls)


def ink(name):
    """(ink height, ink top, ink bottom) of a glyph, in em at scale 1."""
    _adv, _l, top, _r, bottom = GLYPHS[name]
    return top - bottom - 2 * PAD, top - PAD, bottom + PAD


def glyph_at(name, scale, x, ink_top, stretch=None):
    """A glyph placed so that its ink top is at ink_top; stretch gives its ink a new height."""
    adv, left, top, right, bottom = GLYPHS[name]
    k = scale if stretch is None else stretch / (top - bottom - 2 * PAD)
    return (name, x + left * scale, ink_top + PAD * k, (right - left) * scale, (top - bottom) * k)


# ---------------------------------------------------------------- parsing

_TOKEN = re.compile(r'\\[a-zA-Z]+|\\.|[0-9]|[a-zA-Z]|\S')


def tokenize(latex):
    return _TOKEN.findall(latex)


class _Parser(object):
    def __init__(self, latex):
        self.tokens = tokenize(latex)
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self):
        tok = self.peek()
        if tok is None:
            raise TexError('unexpected end')
        self.pos += 1
        return tok

    def expression(self, stop=None):
        """Atoms up to the stop token (or one of a tuple of them), which is consumed and
        left in self.stopped_by."""
        stops = stop if isinstance(stop, tuple) else (stop,)
        nodes = []
        while True:
            tok = self.peek()
            if tok is None:
                if stop:
                    raise TexError('missing %s' % (stops,))
                return nodes
            if tok in stops:
                self.pos += 1
                self.stopped_by = tok
                return nodes
            if tok in ('}', '\\right'):
                raise TexError('unexpected %s' % tok)
            atom = self.atom()
            sup = sub = None
            while self.peek() in ('^', '_'):
                which = self.take()
                arg = self.argument()
                if which == '^':
                    sup = arg
                else:
                    sub = arg
            nodes.append(('scripts', atom, sup, sub) if sup or sub else atom)

    def argument(self):
        """A {group} or a single token's atom."""
        if self.peek() == '{':
            self.pos += 1
            return ('group', self.expression('}'))
        return self.atom()

    def atom(self):
        tok = self.take()
        if tok == '{':
            return ('group', self.expression('}'))
        if tok.isdigit():
            return ('sym', 'ord', 'rm_' + tok)
        if tok.isalpha():
            return ('sym', 'ord', 'mi_' + (tok if tok.islower() else 'cap_' + tok))
        if tok in SYMBOLS:
            return ('sym',) + SYMBOLS[tok]
        if tok in WORDS:
            return ('word',) + WORDS[tok]
        if tok in SPACES:
            return ('space', SPACES[tok])
        if tok == '\\sqrt':
            index = None
            if self.peek() == '[':
                self.pos += 1
                index = ('group', self.expression(']'))
            return ('sqrt', self.argument(), index)
        if tok == '\\ldots':
            return ('ldots',)
        if tok == '\\begin':
            return self.environment()
        if tok in ('\\frac', '\\binom', '\\dfrac', '\\tfrac'):
            num, den = self.argument(), self.argument()
            return ('binom' if tok == '\\binom' else 'frac', num, den)
        if tok == '\\sum':
            return ('bigop', 'ex_sum')
        if tok == '\\left':
            left = self.take()
            body = self.expression('\\right')
            right = self.take()
            for d in (left, right):
                if d != '.' and d not in DELIMS:
                    raise TexError('bad delimiter %s' % d)
            return ('left', left, ('group', body), right)
        raise TexError('unknown token %s' % tok)

    def env_name(self):
        if self.take() != '{':
            raise TexError('expected {')
        name = ''
        while self.peek() != '}':
            name += self.take()
        self.pos += 1
        return name

    def environment(self):
        name = self.env_name()
        if name not in MATRICES:
            raise TexError('unknown environment %s' % name)
        rows, row = [], []
        while True:
            cell = self.expression(('&', '\\\\', '\\end'))
            row.append(('group', cell))
            if self.stopped_by != '&':
                rows.append(row)
                row = []
            if self.stopped_by == '\\end':
                break
        if self.env_name() != name:
            raise TexError('mismatched \\end')
        return ('matrix', name, [r for r in rows if r != [('group', [])]])


def parse(latex):
    return ('group', _Parser(latex).expression())


# ---------------------------------------------------------------- layout

def hlist(boxes, scale, script):
    """Join boxes left to right with TeX's inter-atom spacing."""
    classes = [b.cls for b in boxes]
    # A binary operator with nothing to its left (or after another operator) is unary.
    prev = None
    for i, c in enumerate(classes):
        if c == 'bin' and (prev in (None, 'bin', 'op', 'rel', 'open', 'punct')):
            classes[i] = c = 'ord'
        if c in ('rel', 'close', 'punct') and prev == 'bin':
            classes[i - 1] = 'ord'
        prev = c if c != 'space' else prev
    if classes and classes[-1] == 'bin':
        classes[-1] = 'ord'
    x, height, depth, items = 0.0, 0.0, 0.0, []
    prev = None
    for box, cls in zip(boxes, classes):
        if cls == 'space':
            x += box.width
            continue
        if prev is not None:
            kind = _SPACING[prev][_CLASSES.index(cls)]
            if kind == 's':
                x += THIN * scale
            elif kind == 'm' and not script:
                x += MED * scale
            elif kind == 't' and not script:
                x += THICK * scale
        items += box.place(x, 0.0)
        x += box.width
        height, depth = max(height, box.height), max(depth, box.depth)
        prev = cls
    return Box(x, height, depth, items)


def delimiter(tok, needed, scale, x=0.0):
    """A delimiter at least `needed` em tall (ink), centred on the axis: (Box, width)."""
    if tok == '.':
        return Box(NULL_DELIM * scale)
    choices = DELIMS[tok]
    pick, stretch = choices[-1], None
    for name in choices:
        if ink(name)[0] * scale >= needed:
            pick = name
            break
    else:
        if ink(pick)[0] * scale < needed:
            stretch = needed
    total = stretch if stretch else ink(pick)[0] * scale
    top = AXIS * scale + total / 2.0
    item = glyph_at(pick, scale, x, top, stretch)
    return Box(GLYPHS[pick][0] * scale, top, total - top, [item])


def layout(node, style):
    scale = SCALE[style]
    kind = node[0]
    if kind == 'group':
        box = hlist([layout(n, style) for n in node[1]], scale, style in ('S', 'SS'))
        return box
    if kind == 'sym':
        return glyph_box(node[2], scale, node[1])
    if kind == 'space':
        return Box(node[1] * scale, cls='space')
    if kind == 'word':
        parts = [glyph_box('rm_' + c, scale) for c in node[2]]
        box = hlist(parts, scale, True)
        box.cls = node[1]
        return box
    if kind == 'scripts':
        return scripts(node, style)
    if kind == 'sqrt':
        index = layout(node[2], 'SS') if node[2] else None
        return radical(layout(node[1], style), scale, style, index)
    if kind == 'ldots':
        dot = glyph_box('mi_period', scale)
        gap = THIN * scale
        items = []
        for k in range(3):
            items += dot.place(k * (dot.width + gap), 0)
        return Box(3 * dot.width + 2 * gap, dot.height, dot.depth, items, 'inner')
    if kind == 'matrix':
        return matrix(node, style)
    if kind == 'box':
        return node[1]
    if kind in ('frac', 'binom'):
        return fraction(node, style)
    if kind == 'bigop':
        box = glyph_box(node[1] if style == 'D' else 'ex_sum_text', scale, 'op')
        shift = AXIS * scale - (box.height - box.depth) / 2.0   # centre on the axis
        return Box(box.width, box.height + shift, box.depth - shift, box.place(0, shift), 'op')
    if kind == 'left':
        inner = layout(node[2], style)
        needed = max(2 * max(inner.height - AXIS * scale, inner.depth + AXIS * scale) * 0.901,
                     inner.height + inner.depth - 0.5 * scale)
        left = delimiter(node[1], needed, scale)
        right = delimiter(node[3], needed, scale)
        width = left.width + inner.width + right.width
        items = left.items + inner.place(left.width, 0) + right.place(left.width + inner.width, 0)
        return Box(width, max(left.height, inner.height, right.height),
                   max(left.depth, inner.depth, right.depth), items, 'inner')
    raise TexError('cannot lay out %s' % kind)


def scripts(node, style):
    _kind, base_node, sup_node, sub_node = node
    scale = SCALE[style]
    sub_style = SCRIPT[style]
    if base_node[0] == 'bigop' and style == 'D':
        return limits(layout(base_node, style), sup_node, sub_node, style)
    base = layout(base_node, style)
    single = base_node[0] == 'sym'
    sup = layout(sup_node, sub_style) if sup_node else None
    sub = layout(sub_node, sub_style) if sub_node else None
    s_scale = SCALE[sub_style]
    items = list(base.items)
    width, height, depth = base.width, base.height, base.depth
    # TeX's rules 18a-18f, simplified: start from the base, then keep clear of it.
    u = 0.0 if single else base.height - 0.386 * s_scale
    v = 0.0 if single else base.depth + 0.05 * s_scale
    if sup:
        u = max(u, (0.413 if style == 'D' else 0.363) * scale, sup.depth + XHEIGHT * scale / 4)
    if sub and not sup:
        v = max(v, 0.15 * scale, sub.height - 0.8 * XHEIGHT * scale)
    if sub and sup:
        v = max(v, 0.247 * scale)
        gap = (u - sup.depth) - (sub.height - v)
        if gap < 4 * RULE * scale:
            v += 4 * RULE * scale - gap
    italic = 0.05 * scale if base_node[0] == 'sym' and base_node[2].startswith('mi_') else 0.0
    end = width
    if sup:
        items += sup.place(width + italic, u)
        end = max(end, width + italic + sup.width)
        height, depth = max(height, u + sup.height), max(depth, sup.depth - u)
    if sub:
        items += sub.place(width, -v)
        end = max(end, width + sub.width)
        height, depth = max(height, sub.height - v), max(depth, v + sub.depth)
    return Box(end + SCRIPT_SPACE * scale, height, depth, items, base.cls)


def limits(op, sup_node, sub_node, style):
    """Display-style big operator with its limits centred above and below."""
    scale = SCALE[style]
    sup = layout(sup_node, 'S') if sup_node else None
    sub = layout(sub_node, 'S') if sub_node else None
    width = max(op.width, sup.width if sup else 0, sub.width if sub else 0)
    items = op.place((width - op.width) / 2.0, 0)
    height, depth = op.height, op.depth
    if sup:
        base = op.height + max(0.111 * scale, 0.2 * scale - sup.depth) + sup.depth
        items += sup.place((width - sup.width) / 2.0, base)
        height = base + sup.height + 0.1 * scale
    if sub:
        base = op.depth + max(0.167 * scale, 0.6 * scale - sub.height) + sub.height
        items += sub.place((width - sub.width) / 2.0, -base)
        depth = base + sub.depth + 0.1 * scale
    return Box(width, height, depth, items, 'op')


def fraction(node, style):
    kind, num_node, den_node = node
    scale = SCALE[style]
    inner = SMALLER[style]
    num, den = layout(num_node, inner), layout(den_node, inner)
    rule = RULE * scale if kind == 'frac' else 0.0
    display = style == 'D'
    u = (0.677 if display else 0.394) * scale
    v = (0.686 if display else 0.345) * scale
    axis = AXIS * scale
    if kind == 'frac':
        clear = (3 if display else 1) * RULE * scale
        u = max(u, axis + rule / 2 + clear + num.depth)
        v = max(v, den.height + clear - (axis - rule / 2))
    else:
        clear = (7 if display else 3) * RULE * scale
        gap = (u - num.depth) - (den.height - v)
        if gap < clear:
            u += (clear - gap) / 2
            v += (clear - gap) / 2
    width = max(num.width, den.width)
    pad = NULL_DELIM * scale
    items = num.place(pad + (width - num.width) / 2.0, u) + den.place(pad + (width - den.width) / 2.0, -v)
    if rule:
        items.append((None, pad, axis + rule / 2, width, rule))
    box = Box(width + 2 * pad, u + num.height, v + den.depth, items, 'inner' if kind == 'binom' else 'ord')
    return _wrap(box, style) if kind == 'binom' else box


def _wrap(box, style):
    """Parentheses sized for a \\binom (TeX uses \\delim1 = 2.39 em in display style)."""
    scale = SCALE[style]
    needed = max(2.39 if style == 'D' else 1.01, box.height + box.depth) * scale * 0.95
    left, right = delimiter('(', needed, scale), delimiter(')', needed, scale)
    items = left.items + box.place(left.width, 0) + right.place(left.width + box.width, 0)
    return Box(left.width + box.width + right.width, max(left.height, box.height),
               max(left.depth, box.depth), items, 'inner')


def matrix(node, style):
    """An amsmath matrix: centred columns 1 em apart, rows on struts, centred on the
    axis, inside the environment's delimiters."""
    _kind, name, rows = node
    scale = SCALE[style]
    inner = SMALLER[style] if style == 'D' else style
    cells = [[layout(c, inner) for c in row] for row in rows]
    ncols = max(len(r) for r in cells)
    widths = [max(r[j].width for r in cells if j < len(r)) for j in range(ncols)]
    heights = [max([c.height for c in r] + [0.7 * scale]) for r in cells]
    depths = [max([c.depth for c in r] + [0.3 * scale]) for r in cells]
    gap = 0.2 * scale
    total = sum(heights) + sum(depths) + gap * (len(cells) - 1)
    top = AXIS * scale + total / 2.0
    items, y = [], top
    for r, row in enumerate(cells):
        base = y - heights[r]
        x = 0.0
        for j, cell in enumerate(row):
            items += cell.place(x + (widths[j] - cell.width) / 2.0, base)
            x += widths[j] + 1.0 * scale
        y = base - depths[r] - gap
    pad = 0.12 * scale                                  # room between the entries and the bars
    width = sum(widths) + 1.0 * scale * (ncols - 1) + 2 * pad
    body = Box(width, top, total - top, [(n, l + pad, t, w, h) for n, l, t, w, h in items])
    left, right = MATRICES[name]
    return layout(('left', left, ('box', body), right), style)


def radical(body, scale, style, index=None):
    rule = RULE * scale
    phi = XHEIGHT * scale if style == 'D' else rule
    clear = rule + phi / 4
    needed = body.height + body.depth + clear + rule
    pick, stretch = SURDS[-1], None
    for name in SURDS:
        if ink(name)[0] * scale >= needed:
            pick = name
            break
    else:
        stretch = needed
    total = stretch if stretch else ink(pick)[0] * scale
    extra = total - needed
    if extra > 0:
        clear += extra / 2
    top = body.height + clear + rule
    # An index (\\sqrt[3]{}) sits in the crook of the surd, raised to 60 % of its height.
    shift, height = 0.0, top + rule
    items = []
    if index:
        lift = (top - total) + 0.6 * total + index.depth
        shift = max(0.0, 5 / 18.0 * scale + index.width - 10 / 18.0 * scale)   # TeX: 5mu, index, -10mu
        items += index.place(5 / 18.0 * scale, lift)
        height = max(height, lift + index.height)
    surd = glyph_at(pick, scale, shift, top, stretch)
    _adv, left, _t, right, _b = GLYPHS[pick]
    surd_right = shift + (right - PAD) * scale          # where the ink of the hook ends
    body_x = surd_right
    width = body_x + body.width + 0.06 * scale
    items += [surd, (None, surd_right - 0.02 * scale, top, width - surd_right + 0.02 * scale, rule)]
    items += body.place(body_x, 0)
    return Box(width, height, max(body.depth, total - top), items)


def typeset(latex):
    """Lay out a LaTeX math string in display style. Returns a Box (em units)."""
    return layout(parse(latex), 'D')

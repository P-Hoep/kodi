"""Generate OpenTrivia's one window, shared by the app and the screensaver:

  script.module.opentrivia/resources/skins/Default/1080i/opentrivia.xml

  python3 tools/make_opentrivia_skin.py

The window has four views (start, quiz, results, message) plus a pause sheet and a dim layer.
Everything on screen is driven by window properties that Python sets (ot.*): the view, the
question and its font bucket, the option states, and the theme colours, which the XML reads with
$INFO[Window.Property(ot.x)] in colordiffuse and textcolor. Kodi's own Visible/Hidden/conditional
animations do the motion; Python never moves controls in a loop.

The repeated parts - one control per font bucket, one timer bar per duration, the three option
layouts and their four reveal states - are why this is generated rather than written by hand.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, '..', 'script.module.opentrivia',
                                    'resources', 'skins', 'Default', '1080i'))

QUESTION_FONTS = {'xl': 'font45', 'l': 'font37', 'm': 'font27', 's': 'font23_narrow'}
OPTION_FONTS = {'m': 'font27', 's': 'font23_narrow', 'xs': 'font20_title'}
TIMER_SECONDS = range(3, 61)

OPTION_IDS = {'duo': (221, 222), 'stack': (211, 212, 213, 214), 'grid': (201, 202, 203, 204)}
OPTION_RECTS = {
    'duo': [(260, 560 + i * 180, 1400, 150) for i in range(2)],
    'stack': [(260, 500 + i * 104, 1400, 88) for i in range(4)],
    'grid': [(260 + (i % 2) * 720, 500 + (i // 2) * 188, 680, 150) for i in range(4)],
}

ENTER_MS = 240


def prop(name):
    return 'Window.Property(ot.%s)' % name


def info(name):
    return '$INFO[%s]' % prop(name)


def eq(name, value):
    return 'String.IsEqual(%s,%s)' % (prop(name), value)


def empty(name):
    return 'String.IsEmpty(%s)' % prop(name)


def has(name):
    return '!String.IsEmpty(%s)' % prop(name)


def all_of(*conds):
    return ' + '.join('[%s]' % c for c in conds if c)


def any_of(*conds):
    return ' | '.join('[%s]' % c for c in conds if c)


def color(name):
    return info(name)


def pos(left, top, width, height):
    return '<left>%d</left><top>%d</top><width>%d</width><height>%d</height>' % (left, top, width, height)


def image(left, top, width, height, texture, tint=None, border=None, visible=None, extra='', cid=None):
    """A media shape tinted by a colour property (or a literal #AARRGGBB)."""
    out = '<control type="image"%s>%s<texture%s>%s</texture><aspectratio>stretch</aspectratio>' % (
        ' id="%d"' % cid if cid else '', pos(left, top, width, height),
        ' border="%d"' % border if border else '', texture)
    if tint:
        out += '<colordiffuse>%s</colordiffuse>' % (color(tint) if not tint.startswith('#') else tint[1:])
    if visible:
        out += '<visible>%s</visible>' % visible
    return out + extra + '</control>'


def label(left, top, width, height, text, font, tint='text', align='center', aligny='center', wrap=False,
          visible=None, extra='', scroll=False):
    out = '<control type="label">%s<font>%s</font><align>%s</align><aligny>%s</aligny>' % (
        pos(left, top, width, height), font, align, aligny)
    tc = color(tint) if not tint.startswith('#') else tint[1:]
    # selectedcolor too: otherwise a focused label can take the skin's default colour.
    out += '<textcolor>%s</textcolor><selectedcolor>%s</selectedcolor>' % (tc, tc)
    if wrap:
        out += '<wrapmultiline>true</wrapmultiline>'
    if scroll:
        out += '<scroll>true</scroll>'
    out += '<label>%s</label>' % text
    if visible:
        out += '<visible>%s</visible>' % visible
    return out + extra + '</control>'


def group(children, left=0, top=0, width=1920, height=1080, visible=None, animations='', cid=None):
    out = '<control type="group"%s>%s' % (' id="%d"' % cid if cid else '', pos(left, top, width, height))
    if visible:
        out += '<visible>%s</visible>' % visible
    out += animations
    return out + ''.join(children) + '</control>'


def button(cid, left, top, width, height, text, nav=None, visible=None, font='font13', primary=False,
           invisible=False, align='center'):
    nav = nav or {}
    out = '<control type="button" id="%d">%s' % (cid, pos(left, top, width, height))
    if invisible:
        out += ('<texturefocus colordiffuse="00FFFFFF">white.png</texturefocus>'
                '<texturenofocus colordiffuse="00FFFFFF">white.png</texturenofocus>')
    else:
        out += '<texturefocus border="28" colordiffuse="%s">round28.png</texturefocus>' % color('accent')
        out += '<texturenofocus border="28" colordiffuse="%s">round28.png</texturenofocus>' % (
            color('soft') if primary else color('card'))
        out += '<textcolor>%s</textcolor><focusedcolor>%s</focusedcolor>' % (
            color('accent') if primary else color('text'), color('on_accent'))
        out += '<align>%s</align><aligny>center</aligny><textoffsetx>28</textoffsetx>' % align
    out += '<font>%s</font><label>%s</label>' % (font, text)
    for key in ('left', 'right', 'up', 'down'):
        if key in nav:
            out += '<on%s>%s</on%s>' % (key, nav[key], key)
    if visible:
        out += '<visible>%s</visible>' % visible
    out += ('<animation effect="zoom" start="100" end="104" time="120" tween="cubic" easing="out" '
            'center="auto">Focus</animation>')
    out += ('<animation effect="zoom" start="104" end="100" time="120" tween="cubic" easing="out" '
            'center="auto">Unfocus</animation>')
    return out + '</control>'


def backdrop():
    return (image(-20, -20, 1960, 1120, 'white.png', 'bg') +
            image(-240, -700, 2400, 2400, 'glow.png', 'glow', visible=has('glow_on')) +
            image(-20, -20, 1960, 1120, 'vignette.png', 'shadow'))


def card_shape(left, top, width, height):
    return [image(left - 96, top - 96 + 18, width + 192, height + 192, 'shadow.png', 'shadow', border=96) +
            image(left, top, width, height, 'round32.png', 'card', border=32) +
            image(left, top, width, height, 'outline32.png', 'hairline', border=32)]


def window(body, default):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!-- Generated by tools/make_opentrivia_skin.py; edit it there. -->\n'
            '<window>\n<defaultcontrol always="true">%d</defaultcontrol>\n'
            '<animation effect="fade" start="0" end="100" time="300">WindowOpen</animation>\n'
            '<animation effect="fade" start="100" end="0" time="220">WindowClose</animation>\n'
            '<controls>\n%s\n</controls>\n</window>\n' % (default, '\n'.join(body)))


# ------------------------------------------------------------------ top bar

def topbar():
    """Brand, category chip, and either the app's progress and score or the saver's clock."""
    app = eq('app', 1)
    shown = any_of(eq('view', 'quiz'), eq('view', 'results'))
    return group([
        label(96, 44, 560, 52, 'OPEN TRIVIA', 'font25_title', 'text', align='left'),
        image(96, 100, 96, 4, 'white.png', 'accent', visible=app),
        image(700, 52, 380, 44, 'round22.png', 'soft', border=22, visible=has('chip')),
        label(720, 52, 340, 44, info('chip'), 'font12', 'text', visible=has('chip'), scroll=True),
        label(1096, 44, 264, 52, info('progress'), 'font13', 'muted', align='right', visible=app),
        label(1370, 44, 200, 52, info('score_text'), 'font13', 'muted', align='right', visible=app),
        label(1580, 44, 244, 52, info('streak_text'), 'font13', 'muted', align='right',
              visible=all_of(app, has('streak_text'))),
        label(1424, 34, 400, 76, '$INFO[System.Time]', 'font45', 'muted', align='right',
              visible=has('clock')),
    ], visible=shown)


# ------------------------------------------------------------------ quiz

def question_texts():
    """One label per font bucket; the one named by ot.qsize shows."""
    out = []
    for name, font in QUESTION_FONTS.items():
        out.append(label(340, 196, 1260, 212, info('q'), font, align='left', wrap=True,
                         visible=eq('qsize', name)))
    return out


def timer_bars(left, top, width):
    out = []
    for n in TIMER_SECONDS:
        anim = ('<animation effect="zoom" start="100,100" end="0,100" center="%d,%d" time="%d">Visible'
                '</animation>' % (left, top + 2, n * 1000))
        out.append(image(left, top, width, 6, 'white.png', 'accent', visible=eq('timer', n), extra=anim))
    return out


def option_nav(layout, i):
    ids = OPTION_IDS[layout]
    n = len(ids)
    if layout == 'grid':
        col, row = i % 2, i // 2
        return {'left': ids[i - 1] if col else ids[i], 'right': ids[i + 1] if not col else ids[i],
                'up': ids[i - 2] if row else ids[i], 'down': ids[i + 2] if not row else ids[i]}
    return {'up': ids[i - 1] if i > 0 else ids[i], 'down': ids[i + 1] if i < n - 1 else ids[i]}


def option_text(text, left, top, width, height, tint):
    out = []
    for name, font in OPTION_FONTS.items():
        align = 'left'
        out.append(label(left, top, width, height, text, font, tint, align=align, wrap=True,
                         visible=eq('osize', name)))
    return out


def option(layout, i):
    """One answer surface: plain (focusable), correct, wrong, or dimmed after the reveal."""
    left, top, width, height = OPTION_RECTS[layout][i]
    bid = OPTION_IDS[layout][i]
    n = i + 1
    state = 's%d' % n
    shown = all_of(eq('layout', layout), any_of(*[eq('n', k) for k in (2, 3, 4) if k > i]))
    good, bad = eq(state, 'good'), eq(state, 'bad')
    plain = '!' + any_of(good, bad)
    focus = 'Control.HasFocus(%d)' % bid
    anims = ('<animation effect="zoom" start="100" end="102" time="140" tween="cubic" easing="out" '
             'center="auto" condition="%s">Conditional</animation>' % focus)
    anims += ('<animation effect="fade" start="100" end="34" time="260" condition="%s">Conditional'
              '</animation>' % eq(state, 'dim'))

    badge = 44
    bx, by = left + 24, top + (height - badge) // 2
    tx = bx + badge + 20
    tw = width - (tx - left) - 24
    ty = top + 8
    th = height - 16

    shake = ('<animation type="Visible">'
             '<effect type="slide" start="0,0" end="8,0" time="40"/>'
             '<effect type="slide" start="0,0" end="-16,0" time="80" delay="40"/>'
             '<effect type="slide" start="0,0" end="14,0" time="80" delay="120"/>'
             '<effect type="slide" start="0,0" end="-6,0" time="40" delay="200"/></animation>')
    pop = ('<animation effect="zoom" start="50" end="100" time="240" tween="back" easing="out" '
           'center="auto">Visible</animation>')

    plain_children = [
        image(left, top, width, height, 'round24.png', 'option', border=24),
        image(left, top, width, height, 'outline24.png', 'hairline', border=24),
        image(left, top, width, height, 'outline24_thick.png', 'accent', border=24,
              visible=all_of(focus, plain)),
        image(bx, by, badge, badge, 'round12.png', 'soft', border=12),
        label(bx, by, badge, badge, 'ABCD'[i], 'font20_title', 'accent', visible=has('letters')),
    ] + option_text(info('o%d' % n), tx, ty, tw, th, 'text')
    good_children = [
        image(left, top, width, height, 'round24.png', 'good', border=24),
        image(bx, by, badge, badge, 'round12.png', '#FFFFFFFF', border=12),
        image(bx + 4, by + 4, badge - 8, badge - 8, 'check.png', 'good', extra=pop),
    ] + option_text(info('o%d' % n), tx, ty, tw, th, 'on_good')
    bad_children = [
        image(left, top, width, height, 'round24.png', 'bad', border=24),
        image(bx, by, badge, badge, 'round12.png', '#FFFFFFFF', border=12),
        image(bx + 4, by + 4, badge - 8, badge - 8, 'cross.png', 'bad'),
    ] + option_text(info('o%d' % n), tx, ty, tw, th, 'on_bad')

    return group([
        group(plain_children, visible=plain),
        group(good_children, visible=good),
        group(bad_children, visible=bad, animations=shake),
        button(bid, left, top, width, height, '', option_nav(layout, i), invisible=True),
    ], visible=shown, animations=anims)


def quiz_view():
    left, top, width, height = 260, 120, 1400, 340
    question = group(
        card_shape(left, top, width, height) +
        [image(left + 40, top + 58, 8, height - 116, 'white.png', 'accent'),
         label(left + 84, top + 34, width - 140, 38, info('kicker'), 'font13', 'muted', align='left'),
         ] +
        question_texts() +
        timer_bars(left + 40, top + height - 12, width - 80),
        visible=eq('view', 'quiz'),
        animations='<animation type="Visible"><effect type="fade" start="0" end="100" time="%d" '
                   'tween="cubic" easing="out"/><effect type="slide" start="0,26" end="0,0" time="%d" '
                   'tween="cubic" easing="out"/></animation>'
                   '<animation type="Hidden"><effect type="fade" start="100" end="0" time="180" '
                   'tween="cubic" easing="in"/></animation>' % (ENTER_MS, ENTER_MS))

    options = group([group([option(layout, i) for i in range(len(OPTION_IDS[layout]))],
                           visible=eq('view', 'quiz'))
                     for layout in ('duo', 'stack', 'grid')])

    footer = group([
        label(260, 924, 1040, 60, info('hint'), 'font13', 'muted', align='left',
              visible=all_of(eq('app', 1), empty('result'))),
        label(260, 924, 1040, 60, info('feedback'), 'font25_title', 'text', align='left',
              visible=all_of(eq('app', 1), eq('result', 'good'))),
        label(260, 924, 1040, 60, info('feedback'), 'font25_title', 'text', align='left',
              visible=all_of(eq('app', 1), eq('result', 'bad'))),
        button(141, 1420, 924, 240, 68, info('t.next'),
               {'up': 211, 'left': 141, 'right': 141},
               visible=all_of(eq('app', 1), has('result')), primary=True),
    ], visible=eq('view', 'quiz'))

    return group([question, options, footer], visible=eq('view', 'quiz'))


# ------------------------------------------------------------------ start, results, message

def start_view():
    left, top, width, height = 320, 220, 1280, 640
    return group(
        card_shape(left, top, width, height) +
        [image(left + 80, top + 84, 8, 212, 'white.png', 'accent'),
         label(left + 120, top + 72, 1040, 96, info('title'), 'font52_title', 'text', align='left'),
         label(left + 120, top + 180, 1040, 40, info('tagline'), 'font13', 'muted', align='left'),
         label(left + 120, top + 236, 1040, 56, info('summary'), 'font23_narrow', 'text', align='left'),
         label(left + 120, top + 300, 1040, 44, info('hint'), 'font13', 'muted', align='left',
               visible=has('hint')),
         button(101, left + 120, top + 436, 420, 88, info('t.start'),
                {'right': 102, 'left': 101}, primary=True),
         button(102, left + 580, top + 436, 320, 88, info('t.settings'), {'left': 101, 'right': 103}),
         button(103, left + 940, top + 436, 260, 88, info('t.quit'), {'left': 102, 'right': 103}),
         label(0, 1014, 1920, 40, info('t.back_quit'), 'font12', 'muted', visible=empty('hint'))],
        visible=eq('view', 'start'),
        animations='<animation type="Visible"><effect type="fade" start="0" end="100" time="260" '
                   'tween="cubic" easing="out"/><effect type="slide" start="0,30" end="0,0" time="260" '
                   'tween="cubic" easing="out"/></animation>'
                   '<animation type="Hidden"><effect type="fade" start="100" end="0" time="180" '
                   'tween="cubic" easing="in"/></animation>')


def results_view():
    tiles = []
    for i, (value, caption) in enumerate((('r.score', 't.your_score'), ('r.accuracy', 't.accuracy'),
                                          ('r.best', 't.best_streak'))):
        left = 390 + i * 390
        tiles += [image(left, 300, 360, 180, 'round28.png', 'card', border=28),
                  image(left, 300, 360, 180, 'outline28.png', 'hairline', border=28),
                  label(left, 322, 360, 86, info(value), 'font45', 'accent' if i == 0 else 'text'),
                  label(left, 414, 360, 40, info(caption), 'font13', 'muted')]
    return group(
        [label(0, 120, 1920, 80, info('t.complete'), 'font45', 'text'),
         label(0, 202, 1920, 44, info('summary'), 'font13', 'muted'),
         ] + tiles +
        [label(0, 520, 1920, 44, info('r.counts'), 'font23_narrow', 'muted'),
         button(111, 470, 720, 340, 88, info('t.play_again'), {'right': 112, 'left': 111}, primary=True),
         button(112, 850, 720, 340, 88, info('t.settings'), {'left': 111, 'right': 113}),
         button(113, 1230, 720, 220, 88, info('t.quit'), {'left': 112, 'right': 113}),
         label(0, 844, 1920, 40, info('t.back_quit'), 'font12', 'muted')],
        visible=eq('view', 'results'),
        animations='<animation type="Visible"><effect type="fade" start="0" end="100" time="300" '
                   'tween="cubic" easing="out"/><effect type="slide" start="0,30" end="0,0" time="300" '
                   'tween="cubic" easing="out"/></animation>')


def message_view():
    left, top, width, height = 320, 220, 1280, 640
    return group(
        card_shape(left, top, width, height) +
        [image(left + 80, top + 106, 8, 120, 'white.png', 'accent'),
         label(left + 120, top + 96, 1040, 60, info('msg.title'), 'font37', 'text', align='left'),
         label(left + 120, top + 178, 1040, 220, info('msg.body'), 'font23_narrow', 'muted', align='left',
               aligny='top', wrap=True),
         button(150, left + 440, top + 470, 400, 88, info('msg.button'), {'left': 150, 'right': 150},
                visible=has('msg.button'), primary=True)],
        visible=eq('view', 'message'),
        animations='<animation type="Visible"><effect type="fade" start="0" end="100" time="220" '
                   'tween="cubic" easing="out"/></animation>')


# ------------------------------------------------------------------ pause sheet and dim

def pause_sheet():
    left, top, width, height = 660, 280, 600, 520
    return group(
        [image(-20, -20, 1960, 1120, 'white.png', 'scrim'),
         image(left, top, width, height, 'round32.png', 'card', border=32),
         image(left, top, width, height, 'outline32.png', 'hairline', border=32),
         label(left, top + 30, width, 70, info('t.paused'), 'font37', 'text'),
         button(301, left + 80, top + 140, 440, 76, info('t.resume'), {'down': 302, 'up': 304}, primary=True),
         button(302, left + 80, top + 230, 440, 76, info('t.end'), {'up': 301, 'down': 303}),
         button(303, left + 80, top + 320, 440, 76, info('t.settings'), {'up': 302, 'down': 304}),
         button(304, left + 80, top + 410, 440, 76, info('t.quit_kodi'), {'up': 303, 'down': 301})],
        visible=eq('paused', 1),
        animations='<animation effect="fade" start="0" end="100" time="160">Visible</animation>')


def dim_layer():
    return image(-20, -20, 1960, 1120, 'white.png', 'dim', visible=has('dim'),
                 extra='<animation effect="fade" start="0" end="100" time="2500">Visible</animation>')


def main():
    os.makedirs(OUT, exist_ok=True)
    xml = window([backdrop(), start_view(), quiz_view(), results_view(), message_view(), topbar(),
                  pause_sheet(), dim_layer()], 101)
    path = os.path.join(OUT, 'opentrivia.xml')
    with open(path, 'w') as handle:
        handle.write(xml)
    print('%s (%d KB)' % (path, len(xml) // 1024))


if __name__ == '__main__':
    main()

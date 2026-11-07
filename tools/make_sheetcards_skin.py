"""Generate Sheetcards' three WindowXML files (1080i) into script.module.sheetcards:

  sheetcards-card.xml      the card: flashcard, multiple choice, messages, pause sheet (both add-ons)
  sheetcards-decks.xml     the app's deck picker
  sheetcards-results.xml   the app's results screen

  python3 tools/make_sheetcards_skin.py

Everything on screen is driven by window properties that Python sets (sc.*): text, which view
and side shows, option states, and the theme colours, which the XML reads with
$INFO[Window.Property(sc.card)] in colordiffuse and textcolor. Animations are XML
Visible / Hidden / Conditional / Focus animations; Python never moves controls in a loop.
The repeated parts (font buckets, option pills, one timer bar per duration) are why this is
generated rather than written by hand.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, '..', 'script.module.sheetcards', 'resources', 'skins', 'Default', '1080i'))

FONTS = {'xl': 'font60', 'l': 'font45', 'm': 'font37', 's': 'font27'}
TIMER_SECONDS = range(3, 31)


def prop(name):
    return 'Window.Property(sc.%s)' % name


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
    return ('<left>%d</left><top>%d</top><width>%d</width><height>%d</height>' % (left, top, width, height))


def image(left, top, width, height, texture, tint=None, border=None, visible=None, extra='', cid=None):
    attrs = ' border="%d"' % border if border else ''
    out = '<control type="image"%s>%s<texture%s>%s</texture><aspectratio>stretch</aspectratio>' % (
        ' id="%d"' % cid if cid else '', pos(left, top, width, height), attrs, texture)
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
    # selectedcolor too: otherwise a selected list item takes the skin's default (yellow in Estuary).
    out += '<textcolor>%s</textcolor><selectedcolor>%s</selectedcolor>' % (tc, tc)
    if wrap:
        out += '<wrapmultiline>true</wrapmultiline>'
    if scroll:
        out += '<scroll>true</scroll>'
    out += '<label>%s</label>' % text
    if visible:
        out += '<visible>%s</visible>' % visible
    return out + extra + '</control>'


def textbox(left, top, width, height, text, font, tint='text', visible=None):
    out = '<control type="textbox">%s<font>%s</font><align>center</align><aligny>center</aligny>' % (
        pos(left, top, width, height), font)
    out += '<textcolor>%s</textcolor><autoscroll delay="4000" time="3000" repeat="6000">true</autoscroll>' % color(tint)
    out += '<label>%s</label>' % text
    if visible:
        out += '<visible>%s</visible>' % visible
    return out + '</control>'


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
    out += '<animation effect="zoom" start="100" end="104" time="120" tween="cubic" easing="out" center="auto">Focus</animation>'
    out += '<animation effect="zoom" start="104" end="100" time="120" tween="cubic" easing="out" center="auto">Unfocus</animation>'
    return out + '</control>'


def backdrop():
    return (image(-20, -20, 1960, 1120, 'white.png', 'bg') +
            image(-240, -700, 2400, 2400, 'glow.png', 'glow', visible=has('glow_on')))


def card_shape(left, top, width, height):
    return [image(left - 96, top - 96 + 18, width + 192, height + 192, 'shadow.png', 'shadow', border=96) +
            image(left, top, width, height, 'round32.png', 'card', border=32) +
            image(left, top, width, height, 'outline32.png', 'hairline', border=32)]


def window(body, default, extra_head=''):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!-- Generated by tools/make_sheetcards_skin.py; edit it there. -->\n'
            '<window>\n<defaultcontrol always="true">%d</defaultcontrol>\n%s'
            '<animation effect="fade" start="0" end="100" time="300">WindowOpen</animation>\n'
            '<animation effect="fade" start="100" end="0" time="200">WindowClose</animation>\n'
            '<controls>\n%s\n</controls>\n</window>\n' % (default, extra_head, '\n'.join(body)))


# ------------------------------------------------------------------ the card window

def texts(prefix, size_prop, left, top, width, height, visible):
    """One control per font bucket; the one named by sc.<size_prop> shows."""
    out = []
    for name, font in FONTS.items():
        cond = all_of(visible, eq(size_prop, name))
        if name == 's':
            out.append(textbox(left, top, width, height, info(prefix), font, visible=cond))
        else:
            out.append(label(left, top, width, height, info(prefix), font, wrap=True, visible=cond))
    return out


def timer_bars(left, top, width):
    out = []
    for n in TIMER_SECONDS:
        anim = ('<animation effect="zoom" start="0,100" end="100,100" center="%d,%d" time="%d">Visible</animation>'
                % (left, top + 2, n * 1000))
        out.append(image(left, top, width, 4, 'white.png', 'accent', visible=eq('timer', n), extra=anim))
    return out


OPTION_RECTS = {
    'grid': [(320 + (i % 2) * 660, 590 + (i // 2) * 160, 620, 120) for i in range(4)],
    'stack': [(320, 560 + i * 120, 1280, 96) for i in range(4)],
}
OPTION_IDS = {'grid': [201, 202, 203, 204], 'stack': [211, 212, 213, 214]}


def option_nav(layout, i):
    ids = OPTION_IDS[layout]
    if layout == 'stack':
        return {'up': ids[i - 1] if i > 0 else ids[i], 'down': ids[i + 1] if i < 3 else ids[i]}
    col, row = i % 2, i // 2
    return {'left': ids[i - 1] if col else ids[i], 'right': ids[i + 1] if not col else ids[i],
            'up': ids[i - 2] if row else ids[i], 'down': ids[i + 2] if not row else ids[i]}


def option(layout, i):
    left, top, width, height = OPTION_RECTS[layout][i]
    bid = OPTION_IDS[layout][i]
    n = i + 1
    state = 's%d' % n
    show = all_of(eq('layout', layout), '!' + eq('n', 3) if n == 4 else '')
    good, bad = eq(state, 'good'), eq(state, 'bad')
    plain = '!' + any_of(good, bad)
    focus = 'Control.HasFocus(%d)' % bid
    anims = ('<animation effect="zoom" start="100" end="104" time="120" tween="cubic" easing="out" center="auto" '
             'condition="%s">Conditional</animation>' % focus)
    anims += ('<animation effect="fade" start="100" end="40" time="200" condition="%s">Conditional</animation>'
              % eq(state, 'dim'))
    badge = 40
    bx, by = left + 28, top + (height - badge) // 2
    tx = left + 28 + badge + 24
    tw = width - (tx - left) - 32
    shake = ('<animation type="Visible">'
             '<effect type="slide" start="0,0" end="8,0" time="40"/>'
             '<effect type="slide" start="0,0" end="-16,0" time="80" delay="40"/>'
             '<effect type="slide" start="0,0" end="16,0" time="80" delay="120"/>'
             '<effect type="slide" start="0,0" end="-8,0" time="40" delay="200"/></animation>')
    pop = ('<animation effect="zoom" start="60" end="100" time="220" tween="back" easing="out" center="auto">'
           'Visible</animation>')
    children = [
        image(left, top, width, height, 'round28.png', 'card', border=28, visible=plain),
        image(left, top, width, height, 'outline28.png', 'hairline', border=28, visible=plain),
        image(left, top, width, height, 'outline28_thick.png', 'accent', border=28, visible=all_of(focus, plain)),
        image(bx, by, badge, badge, 'ring.png', 'muted', visible=plain),
        label(bx, by, badge, badge, '$NUMBER[%d]' % n, 'font12', 'muted', visible=plain),
        label(tx, top + 8, tw, height - 16, info('o%d' % n), 'font27', align='left', wrap=True, visible=plain),
        group([image(left, top, width, height, 'round28.png', 'good', border=28),
               image(bx - 4, by - 4, badge + 8, badge + 8, 'check.png', '#FFFFFFFF', extra=pop),
               label(tx, top + 8, tw, height - 16, info('o%d' % n), 'font27', '#FFFFFFFF', align='left', wrap=True)],
              visible=good),
        group([image(left, top, width, height, 'round28.png', 'bad', border=28),
               image(bx - 4, by - 4, badge + 8, badge + 8, 'cross.png', '#FFFFFFFF'),
               label(tx, top + 8, tw, height - 16, info('o%d' % n), 'font27', '#FFFFFFFF', align='left', wrap=True)],
              visible=bad, animations=shake),
        button(bid, left, top, width, height, '', option_nav(layout, i), invisible=True),
    ]
    return group(children, visible=show, animations=anims)


def card_window():
    app = eq('app', 1)
    stage_anims = (
        '<animation type="Visible"><effect type="fade" start="0" end="100" time="260" tween="cubic" easing="out"/>'
        '<effect type="slide" start="0,40" end="0,0" time="260" tween="cubic" easing="out"/></animation>'
        '<animation type="Hidden"><effect type="fade" start="100" end="0" time="200" tween="cubic" easing="in"/>'
        '<effect type="slide" start="0,0" end="-60,0" time="200" tween="cubic" easing="in"/></animation>')
    flip = ('<animation effect="zoom" start="100,100" end="0,100" center="960,540" time="180" tween="cubic" '
            'easing="in" condition="%s">Conditional</animation>' % eq('flip', 1))
    front, back = eq('side', 'front'), eq('side', 'back')

    # Flashcard: 1280 x 640, centred.
    fl, ft, fw, fh = 320, 220, 1280, 640
    flash_card = group(
        card_shape(fl, ft, fw, fh) +
        [label(fl, ft + 36, fw, 40, info('kicker'), 'font12', 'muted')] +
        texts('prompt', 'qsize', fl + 96, ft + 90, fw - 192, fh - 190, front) +
        texts('reveal', 'rsize', fl + 96, ft + 90, fw - 192, fh - 190, back) +
        [label(fl, ft + fh - 72, fw, 40, info('hint'), 'font12', 'muted', visible=has('hint'))] +
        timer_bars(fl + 32, ft + fh - 6, fw - 64),
        animations=flip)
    flash = group([
        flash_card,
        button(101, fl, ft, fw, fh, '', visible=all_of(app, front, empty('answered')), invisible=True),
        button(111, 640, 884, 300, 88, info('t.missed'), {'right': 112, 'left': 111},
               visible=all_of(app, back, empty('answered'))),
        button(112, 980, 884, 300, 88, info('t.got'), {'left': 111, 'right': 112},
               visible=all_of(app, back, empty('answered')), primary=True),
    ], visible=eq('view', 'flash'))

    # Multiple choice: the question card, 1280 x 380 at y = 150, options below.
    cl, ct, cw, ch = 320, 150, 1280, 380
    choice = group(
        card_shape(cl, ct, cw, ch) +
        [label(cl, ct + 24, cw, 40, info('kicker'), 'font12', 'muted')] +
        texts('prompt', 'qsize', cl + 80, ct + 64, cw - 160, ch - 110, 'true') +
        timer_bars(cl + 32, ct + ch - 6, cw - 64) +
        [option(layout, i) for layout in ('grid', 'stack') for i in range(4)],
        visible=eq('view', 'choice'))

    # Message card: errors, loading, "no cards yet".
    message = group(
        card_shape(fl, ft, fw, fh) +
        [label(fl + 96, ft + 150, fw - 192, 130, info('msg.title'), 'font45', wrap=True),
         label(fl + 96, ft + 290, fw - 192, 150, info('msg.body'), 'font27', 'muted', wrap=True),
         # One button (150) centred, or two side by side (152 + 151).
         button(150, 760, ft + fh - 150, 400, 88, info('msg.button'), {'right': 150, 'left': 150},
                visible=all_of(has('msg.button'), empty('msg.button2')), primary=True),
         button(152, 560, ft + fh - 150, 380, 88, info('msg.button'), {'right': 151, 'left': 152},
                visible=all_of(has('msg.button'), has('msg.button2')), primary=True),
         button(151, 980, ft + fh - 150, 380, 88, info('msg.button2'), {'left': 152, 'right': 151},
                visible=has('msg.button2'))],
        visible=eq('view', 'message'))

    # Screensaver deck chip, above the card.
    chip = []
    for view, top in (('flash', 150), ('choice', 84)):
        cond = all_of('!' + app, has('chip'), eq('view', view))
        chip.append(image(700, top, 520, 44, 'round22.png', 'soft', border=22, visible=cond))
        chip.append(label(720, top, 480, 44, info('chip'), 'font12', 'text', visible=cond, scroll=True))

    stage = group([flash, choice, message] + chip, visible=eq('shown', 1), animations=stage_anims, cid=100)

    next_button = button(140, 0, 0, 1920, 1080, '', visible=has('answered'), invisible=True)

    pulse = ('<animation effect="zoom" start="100" end="115" time="150" center="auto" condition="%s">Conditional'
             '</animation>' % eq('pulse', 1))
    topbar = group([
        label(96, 48, 500, 64, info('progress'), 'font13', 'muted', align='left'),
        image(700, 58, 520, 44, 'round22.png', 'soft', border=22, visible=has('chip')),
        label(720, 58, 480, 44, info('chip'), 'font12', 'text', visible=has('chip'), scroll=True),
        label(1224, 48, 300, 64, '$INFO[%s]  [COLOR %s]%s[/COLOR]' % (prop('t.score'), info('text'), info('score')),
              'font13', 'muted', align='right'),
        group([label(1544, 48, 280, 64, '$INFO[%s]  [COLOR %s]%s[/COLOR]' % (prop('t.streak'), info('accent'),
                                                                               info('streak')),
                     'font13', 'muted', align='right')], animations=pulse),
    ], visible=all_of(app, '!' + eq('view', 'message'), eq('shown', 1)))

    clock = label(1424, 40, 400, 70, '$INFO[System.Time]', 'font45', 'muted', align='right',
                  visible=eq('clock', 1))

    info_panel = group(
        [image(1280, 132, 560, 230, 'round28.png', 'card', border=28),
         image(1280, 132, 560, 230, 'outline28.png', 'hairline', border=28),
         label(1312, 148, 496, 200, info('info.text'), 'font12', 'text', align='left', aligny='top', wrap=True)],
        visible=eq('info', 1),
        animations='<animation effect="fade" start="0" end="100" time="150">Visible</animation>')

    sheet = group([
        image(-20, -20, 1960, 1120, 'white.png', '#B0000000'),
        image(660, 300, 600, 480, 'round32.png', 'card', border=32),
        label(660, 330, 600, 80, info('t.paused'), 'font37'),
        button(301, 740, 430, 440, 84, info('t.resume'), {'up': 303, 'down': 302}),
        button(302, 740, 534, 440, 84, info('t.end'), {'up': 301, 'down': 303}),
        button(303, 740, 638, 440, 84, info('t.quit'), {'up': 302, 'down': 301}),
    ], visible=eq('paused', 1), animations='<animation effect="fade" start="0" end="100" time="150">Visible</animation>')

    dim = image(-20, -20, 1960, 1120, 'white.png', '#B3000000', visible=eq('dim', 1),
                extra='<animation effect="fade" start="0" end="100" time="4000">Visible</animation>')

    return window([backdrop(), stage, next_button, topbar, clock, info_panel, sheet, dim], 101)


# ------------------------------------------------------------------ the deck picker

def deck_item(focused):
    sel = 'ListItem.IsSelected'
    out = [
        image(0, 0, 1280, 116, 'round28.png', 'card', border=28),
        image(0, 0, 1280, 116, 'outline28.png', 'hairline', border=28),
        image(32, 34, 48, 48, 'ring.png', 'muted', visible='!' + sel),
        image(32, 34, 48, 48, 'circle.png', 'accent', visible=sel),
        image(36, 38, 40, 40, 'check.png', 'on_accent', visible=sel),
        label(112, 14, 820, 50, '$INFO[ListItem.Label]', 'font32', 'text', align='left', scroll=focused),
        label(112, 62, 820, 40, '$INFO[ListItem.Label2]', 'font12', 'muted', align='left'),
        label(984, 16, 240, 36, '$INFO[ListItem.Property(mastery)]', 'font12', 'muted', align='right'),
        image(984, 60, 240, 8, 'bar_100.png', 'hairline'),
        image(984, 60, 240, 8, '$INFO[ListItem.Property(bar)]', 'accent'),
    ]
    if focused:
        out.append(image(0, 0, 1280, 116, 'outline28_thick.png', 'accent', border=28, visible='Control.HasFocus(50)'))
    return ''.join(out)


def decks_window():
    lst = ('<control type="list" id="50">%s<orientation>vertical</orientation><scrolltime tween="cubic">200</scrolltime>'
           '<ondown>61</ondown><onup>50</onup><onleft>50</onleft><onright>50</onright>'
           '<itemlayout height="132" width="1280">%s</itemlayout>'
           '<focusedlayout height="132" width="1280">%s</focusedlayout></control>'
           % (pos(320, 196, 1280, 660), deck_item(False), deck_item(True)))
    buttons = []
    labels = [(60, 'mode_label'), (61, 't.start'), (62, 't.refresh'), (63, 't.settings')]
    for i, (cid, text) in enumerate(labels):
        left = 364 + i * 304
        nav = {'up': 50, 'left': labels[i - 1][0] if i else cid, 'right': labels[i + 1][0] if i < 3 else cid}
        buttons.append(button(cid, left, 892, 280, 88, info(text), nav, primary=(cid == 61)))
    head = [
        label(96, 52, 1200, 72, info('title'), 'font45', 'text', align='left'),
        label(96, 124, 1200, 40, info('stats'), 'font12', 'muted', align='left'),
        image(1404, 70, 420, 44, 'round22.png', 'soft', border=22, visible=has('status')),
        label(1424, 70, 380, 44, info('status'), 'font12', 'text', visible=has('status')),
        label(0, 994, 1920, 40, info('hint'), 'font12', 'muted', visible=has('hint')),
    ]
    return window([backdrop()] + head + [lst] + buttons, 50)


# ------------------------------------------------------------------ results

def results_window():
    tiles = []
    for i, key in enumerate(('score', 'accuracy', 'best', 'time')):
        left = 315 + i * 330
        tiles += [image(left, 270, 300, 160, 'round28.png', 'card', border=28),
                  image(left, 270, 300, 160, 'outline28.png', 'hairline', border=28),
                  label(left, 290, 300, 80, info('r.%s' % key), 'font45', 'accent' if i == 0 else 'text'),
                  label(left, 372, 300, 40, info('t.r.%s' % key), 'font12', 'muted')]
    item = ''.join([image(0, 0, 1290, 92, 'round28.png', 'card', border=28),
                    label(32, 8, 1226, 44, '$INFO[ListItem.Label]', 'font13', 'text', align='left'),
                    label(32, 48, 1226, 36, '$INFO[ListItem.Label2]', 'font12', 'muted', align='left')])
    focused = ''.join([image(0, 0, 1290, 92, 'round28.png', 'card', border=28),
                       image(0, 0, 1290, 92, 'outline28_thick.png', 'accent', border=28,
                             visible='Control.HasFocus(50)'),
                       label(32, 8, 1226, 44, '$INFO[ListItem.Label]', 'font13', 'text', align='left', scroll=True),
                       label(32, 48, 1226, 36, '$INFO[ListItem.Label2]', 'font12', 'muted', align='left',
                             scroll=True)])
    lst = ('<control type="list" id="50">%s<orientation>vertical</orientation><scrolltime>200</scrolltime>'
           '<ondown>72</ondown><onup>50</onup><onleft>50</onleft><onright>50</onright>'
           '<itemlayout height="104" width="1290">%s</itemlayout>'
           '<focusedlayout height="104" width="1290">%s</focusedlayout></control>' % (pos(315, 520, 1290, 330),
                                                                                   item, focused))
    buttons = [
        button(71, 420, 900, 340, 88, info('t.review'), {'up': 50, 'right': 72, 'left': 71},
               visible=has('r.missed')),
        button(72, 790, 900, 340, 88, info('t.new'), {'up': 50, 'left': 71, 'right': 73}, primary=True),
        button(73, 1160, 900, 340, 88, info('t.decks'), {'up': 50, 'left': 72, 'right': 73}),
    ]
    head = [label(0, 80, 1920, 80, info('t.complete'), 'font45'),
            label(0, 160, 1920, 50, info('r.deck'), 'font13', 'muted'),
            label(315, 460, 1290, 44, info('r.missed_head'), 'font13', 'muted', align='left')]
    return window([backdrop()] + head + tiles + [lst] + buttons, 72)


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, xml in (('sheetcards-card.xml', card_window()), ('sheetcards-decks.xml', decks_window()),
                      ('sheetcards-results.xml', results_window())):
        path = os.path.join(OUT, name)
        with open(path, 'w') as handle:
            handle.write(xml)
        print('%s (%d KB)' % (path, len(xml) // 1024))


if __name__ == '__main__':
    main()

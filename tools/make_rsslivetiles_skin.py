"""Generate RSS Live Tiles' window XML (1080i), one file per tile style, into
script.module.rsslivetiles/resources/skins/Default/1080i/rsslivetiles-<style>.xml

  python3 tools/make_rsslivetiles_skin.py

The board is a fixed set of tile *slots* (pools per size, see tiles/geometry.py). Python
positions a slot with setPosition() and fills it through window properties:

  rt.<slot>.on              1 = shown
  rt.<slot>.face            a | b: which of the two faces shows (double buffering)
  rt.<slot>.fx              flip | cycle | fade: how the faces swap (Hidden / Visible animations)
  rt.<slot>.peek            1 = the picture folds away and shows the text underneath
  rt.<slot>.pulse           1 = count changed
  rt.<slot>.<face>.<key>    the face's content (tiles/faces.py: kind, bg, title, img ...)
  focus                     the focused slot

All motion is Kodi's own animation engine (Python only flips properties), so animations stay
smooth even though Python is slow. Groups do not clip in Kodi (checked on 21.1), so peek and
cycle are folds and rolls that stay inside the tile instead of slides.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(ROOT, 'script.module.rsslivetiles', 'lib'))

from rsslivetiles.tiles import geometry as g  # noqa: E402
from rsslivetiles.tiles.styles import STYLES  # noqa: E402

OUT = os.path.join(ROOT, 'script.module.rsslivetiles', 'resources', 'skins', 'Default', '1080i')


def prop(name):
    return 'Window.Property(%s)' % name


def info(name):
    return '$INFO[%s]' % prop(name)


def eq(name, value):
    return 'String.IsEqual(%s,%s)' % (prop(name), value)


def has(name):
    return '!String.IsEmpty(%s)' % prop(name)


def empty(name):
    return 'String.IsEmpty(%s)' % prop(name)


def all_of(*conds):
    conds = [c for c in conds if c]
    return conds[0] if len(conds) == 1 else ' + '.join('[%s]' % c for c in conds)


def pos(left, top, width, height):
    return '<left>%d</left><top>%d</top><width>%d</width><height>%d</height>' % (left, top, width, height)


def colour(value):
    """'#AARRGGBB' literal, or a property name."""
    return value[1:] if value.startswith('#') else info(value)


def image(left, top, width, height, texture, tint=None, border=0, visible=None, aspect='stretch', extra='',
          cid=None, background=False, diffuse=None):
    attrs = ''
    if border:
        attrs += ' border="%d"' % border
    if background:
        attrs += ' background="true"'
    if diffuse:
        attrs += ' diffuse="%s"' % diffuse
    out = '<control type="image"%s>%s<texture%s>%s</texture>' % (' id="%d"' % cid if cid else '',
                                                               pos(left, top, width, height), attrs, texture)
    out += '<aspectratio%s>%s</aspectratio>' % (' scalediffuse="false"' if diffuse else '', aspect)
    if tint:
        out += '<colordiffuse>%s</colordiffuse>' % colour(tint)
    if visible:
        out += '<visible>%s</visible>' % visible
    return out + extra + '</control>'


def label(left, top, width, height, text, font, tint, align='left', aligny='center', visible=None, wrap=False,
          cid=None, extra=''):
    out = '<control type="label"%s>%s<font>%s</font><align>%s</align><aligny>%s</aligny>' % (
        ' id="%d"' % cid if cid else '', pos(left, top, width, height), font, align, aligny)
    out += '<textcolor>%s</textcolor>' % colour(tint)
    if wrap:
        out += '<wrapmultiline>true</wrapmultiline>'
    out += '<label>%s</label>' % text
    if visible:
        out += '<visible>%s</visible>' % visible
    return out + extra + '</control>'


def textbox(left, top, width, height, text, font, tint, visible=None, align='left', cid=None):
    out = '<control type="textbox"%s>%s<font>%s</font><align>%s</align>' % (
        ' id="%d"' % cid if cid else '', pos(left, top, width, height), font, align)
    out += '<textcolor>%s</textcolor><label>%s</label>' % (colour(tint), text)
    if visible:
        out += '<visible>%s</visible>' % visible
    return out + '</control>'


def group(children, left=0, top=0, width=1920, height=1080, visible=None, animations='', cid=None, camera=None):
    out = '<control type="group"%s>%s' % (' id="%d"' % cid if cid else '', pos(left, top, width, height))
    if camera:
        # The 3D camera for rotations inside this group, in group coordinates. Without it Kodi
        # projects from the screen centre and tiles away from it shear badly when they flip.
        out += '<camera x="%d" y="%d"/>' % camera
    if visible:
        out += '<visible>%s</visible>' % visible
    return out + animations + ''.join(children) + '</control>'


def anim(kind, effects, condition=None):
    cond = ' condition="%s"' % condition if condition else ''
    return '<animation type="%s"%s>%s</animation>' % (kind, cond, ''.join(effects))


def effect(kind, **kw):
    attrs = ''.join(' %s="%s"' % (k, v) for k, v in kw.items())
    return '<effect type="%s"%s/>' % (kind, attrs)


# ------------------------------------------------------------------ tile slots

def face_animations(slot, size, w, h):
    """Hidden / Visible animations of a face, one set per swap effect.

    Flips are 2D: the face squashes to an edge-on line (and shrinks a little, for depth) and
    the new face grows back. Kodi's 3D rotations use a close camera that makes a turning tile
    balloon out of its rectangle, which looked broken on picture tiles (checked on 21.1).
    Wide tiles flip about the horizontal axis, the rest about the vertical one."""
    cx, cy = w // 2, h // 2
    edge = ('0,%d' % (100 - g.FLIP_DEPTH)) if size != 'wide' else ('%d,0' % (100 - g.FLIP_DEPTH))
    fx = 'rt.%s.fx' % slot
    t, c, f = g.FLIP_MS, g.CYCLE_MS, g.FADE_MS
    centre = '%d,%d' % (cx, cy)
    return ''.join([
        anim('Hidden', [effect('zoom', start='100,100', end=edge, center=centre, time=t, tween='quadratic',
                               easing='in')], eq(fx, 'flip')),
        anim('Visible', [effect('zoom', start=edge, end='100,100', center=centre, time=t, delay=t,
                                tween='quadratic', easing='out')], eq(fx, 'flip')),
        # Cycle: the old face rolls up out of the top edge while the new one rolls in from below.
        anim('Hidden', [effect('zoom', start='100,100', end='100,0', center='%d,0' % cx, time=c, tween='cubic',
                               easing='inout'),
                        effect('fade', start=100, end=40, time=c)], eq(fx, 'cycle')),
        anim('Visible', [effect('zoom', start='100,0', end='100,100', center='%d,%d' % (cx, h), time=c,
                                tween='cubic', easing='inout')], eq(fx, 'cycle')),
        anim('Hidden', [effect('fade', start=100, end=0, time=f)], eq(fx, 'fade')),
        anim('Visible', [effect('fade', start=0, end=100, time=f)], eq(fx, 'fade')),
    ])


def text_layer(slot, face, size, style):
    st = STYLES[style]
    w, h = g.PIXELS[size]
    spec = g.FACES[size]
    k = 'rt.%s.%s.' % (slot, face)
    inset = st['inset']
    text_inset = inset + (st['image_inset'] if st['border'] else 0)
    left, top, width, label_y = g.text_area(size, text_inset)
    out = []
    if st['radius']:
        out.append(image(inset, inset, w - 2 * inset, h - 2 * inset, 'round8.png', k + 'bg', border=8))
    else:
        out.append(image(0, 0, w, h, 'white.png', k + 'bg'))
    is_text = any_kind(k, 'text', 'image')
    tfont, tmax = spec['title']
    lh = g.line_px(tfont)
    if size == 'small':
        out.append(textbox(left, top, width, tmax * lh + 6, info(k + 'title'), tfont, k + 'fg',
                           visible=all_of(is_text, empty(k + 'meta'))))
        # Small text tile with a status line (count tile back): title above, label at the bottom.
        out.append(textbox(left, top, width, 2 * lh + 4, info(k + 'title'), tfont, k + 'fg',
                           visible=all_of(is_text, has(k + 'meta'))))
        out.append(label(left, label_y, width, g.LABEL_H, info(k + 'meta'), g.LABEL_FONT, k + 'fg2',
                         visible=all_of(is_text, has(k + 'meta'))))
        return out
    out.append(textbox(left, top, width, tmax * lh + 6, info(k + 'title'), tfont, k + 'fg', visible=is_text))
    if spec['summary']:
        sfont, _smax = spec['summary']
        slh = g.line_px(sfont)
        for n in range(1, tmax + 1):
            stop = top + n * lh + 8
            lines = max(0, (label_y - stop - 4) // slh)
            if lines <= 0:
                continue
            out.append(textbox(left, stop, width, lines * slh + 4, info(k + 'sum'), sfont, k + 'body',
                               visible=all_of(is_text, eq(k + 'tl', n), has(k + 'sum'))))
    icon = 30
    out.append(label(left, label_y, width - icon - 8, g.LABEL_H, info(k + 'meta'), g.LABEL_FONT, k + 'fg2',
                     visible=is_text))
    out.append(image(left + width - icon, label_y - 2, icon, icon, info(k + 'icon'), aspect='keep',
                     visible=all_of(is_text, has(k + 'icon')), background=True))
    return out


def bars(left, top, w, h, t, tint, visible=None):
    """A rectangular frame t px thick as four solid bars (crisper than a bordered texture,
    which Kodi filters softly when stretched)."""
    return [image(left, top, w, t, 'white.png', tint, visible=visible),
            image(left, top + h - t, w, t, 'white.png', tint, visible=visible),
            image(left, top + t, t, h - 2 * t, 'white.png', tint, visible=visible),
            image(left + w - t, top + t, t, h - 2 * t, 'white.png', tint, visible=visible)]


def any_kind(k, *kinds):
    conds = [eq(k + 'kind', kind) for kind in kinds]
    return conds[0] if len(conds) == 1 else ' | '.join('[%s]' % c for c in conds)


def image_layer(slot, face, size, style):
    st = STYLES[style]
    w, h = g.PIXELS[size]
    spec = g.FACES[size]
    k = 'rt.%s.%s.' % (slot, face)
    ins = st['inset'] + st['image_inset']
    iw, ih = w - 2 * ins, h - 2 * ins
    diffuse = 'mask_%s.png' % size if st['radius'] else None
    children = [image(ins, ins, iw, ih, info(k + 'img'), aspect='scale', background=True, diffuse=diffuse)]
    if spec['image_title']:
        font, nmax = spec['image_title']
        lh = g.line_px(font)
        pad = spec['pad'] + ins
        label_y = h - pad - g.LABEL_H + 2
        titled = empty(k + 'notitle')
        if st['scrim'] == 'panel':
            for n in range(1, nmax + 1):
                top = label_y - 10 - n * lh - 10
                children.append(image(ins, top, iw, h - ins - top, 'round8.png', k + 'panel', border=8,
                                      visible=all_of(titled, eq(k + 'itl', n))))
        else:
            sh = int(ih * 0.72)
            children.append(image(ins, h - ins - sh, iw, sh, 'scrim.png', k + 'panel', visible=titled))
        for n in range(1, nmax + 1):
            children.append(textbox(pad, label_y - 6 - n * lh, w - 2 * pad, n * lh + 6, info(k + 'ititle'), font,
                                    '#FFFFFFFF', visible=all_of(titled, eq(k + 'itl', n))))
        children.append(label(pad, label_y, w - 2 * pad, g.LABEL_H, info(k + 'meta'), g.LABEL_FONT, '#D9FFFFFF',
                              visible=titled))
    peek = 'rt.%s.peek' % slot
    rm = has('rm')
    # The picture rolls up like a blind into the tile's top edge, showing the text beneath.
    anims = (anim('Conditional', [effect('zoom', start='100,100', end='100,0', center='%d,0' % (w // 2),
                                         time=g.PEEK_MS, tween='cubic', easing='inout')],
                  all_of(eq(peek, 1), '!' + rm)) +
             anim('Conditional', [effect('fade', start=100, end=0, time=g.PEEK_MS)], all_of(eq(peek, 1), rm)))
    return [group(children, 0, 0, w, h, visible=eq(k + 'kind', 'image'), animations=anims)]


def count_layer(slot, face, size, style):
    st = STYLES[style]
    w, h = g.PIXELS[size]
    spec = g.FACES[size]
    k = 'rt.%s.%s.' % (slot, face)
    vis = eq(k + 'kind', 'count')
    inset = st['inset']
    pad = spec['pad'] + inset
    icon = spec['icon']
    num_h = g.line_px(spec['count'])
    if size == 'small':
        ix, iy = (w - icon) // 2, 14 + inset
    else:
        ix, iy = (w - icon) // 2, (h - icon) // 2 - num_h // 3
    return [
        image(ix, iy, icon, icon, info(k + 'icon'), aspect='keep', background=True,
              visible=all_of(vis, has(k + 'icon'))),
        label(ix - 20, iy, icon + 40, icon, info(k + 'ini'), spec['initials'], k + 'fg', align='center',
              visible=all_of(vis, empty(k + 'icon'))),
        label(pad, h - pad - num_h + 6, w - 2 * pad, num_h, info(k + 'num'), spec['count'], k + 'fg',
              align='right', visible=vis),
    ]


def clock_layer(slot, face, size):
    w, h = g.PIXELS[size]
    k = 'rt.%s.%s.' % (slot, face)
    vis = eq(k + 'kind', 'clock')
    return [
        label(0, h // 2 - 70, w, 100, '$INFO[System.Time]', 'font_clock', k + 'fg', align='center', visible=vis),
        label(0, h // 2 + 30, w, 40, '[UPPERCASE]$INFO[System.Date(ddd d mmm)][/UPPERCASE]', g.LABEL_FONT,
              k + 'fg2', align='center', visible=vis),
    ]


def face_group(slot, face, size, style):
    w, h = g.PIXELS[size]
    children = text_layer(slot, face, size, style) + image_layer(slot, face, size, style)
    if size in ('small', 'medium', 'wide'):
        children += count_layer(slot, face, size, style)
    if size == 'medium':
        children += clock_layer(slot, face, size)
    return group(children, 0, 0, w, h, visible=eq('rt.%s.face' % slot, face),
                 animations=face_animations(slot, size, w, h))


def slot_xml(size, index, style):
    st = STYLES[style]
    w, h = g.PIXELS[size]
    slot = g.slot_names(size)[index]
    inner = [face_group(slot, 'a', size, style), face_group(slot, 'b', size, style)]
    if st['border']:
        inner += bars(0, 0, w, h, 2, 'rt.%s.edge' % slot)
    inner.append(image(w - 34, 8, 26, 26, 'warn.png', '#FFFFFFFF', visible=eq('rt.%s.warn' % slot, 1)))
    inner.append(group(bars(-3, -3, w + 6, h + 6, 3, 'rt.%s.fc' % slot), -3, -3, w + 6, h + 6,
                       visible=eq('focus', slot)))
    anims = (anim('Conditional', [effect('zoom', start=100, end=104, time=150, tween='cubic', easing='out',
                                         center='auto')], eq('focus', slot)) +
             anim('Conditional', [effect('zoom', start=100, end=106, time=g.PULSE_MS, tween='sine', easing='out',
                                         center='auto')], eq('rt.%s.pulse' % slot, 1)))
    focus_group = group(inner, 0, 0, w, h, animations=anims, camera=(w // 2, h // 2))
    return group([focus_group], -4000, 0, w, h, visible=eq('rt.%s.on' % slot, 1), cid=g.slot_id(size, index))


# ------------------------------------------------------------------ the rest of the window

def headers():
    out = []
    for i in range(g.HEADERS):
        out.append(label(-4000, g.HEADER_Y, 1600, 60, info('hdr.%d' % (i + 1)), 'font37', 'text',
                         visible=has('hdr.%d' % (i + 1)), cid=g.HEADER_ID + i + 1))
    return out


def chrome():
    hub = empty('ss')
    return [
        label(g.MARGIN_X - 4, 26, 1200, 100, info('t.title'), 'font_clock', 'text', visible=hub),
        label(1240, 40, 600, 60, '$INFO[System.Time]', 'font37', 'text', align='right', visible=hub),
        label(1240, 96, 600, 30, '[UPPERCASE]%s[/UPPERCASE]' % info('status'), g.LABEL_FONT, 'text2',
              align='right', visible=all_of(hub, has('status'))),
        label(0, 430, 1920, 80, info('msg.title'), 'font45', 'text', align='center', visible=has('msg.title')),
        label(360, 520, 1200, 120, info('msg.body'), 'font13', 'text2', align='center', aligny='top', wrap=True,
              visible=has('msg.title')),
    ]


def detail():
    left_w = int(g.SCREEN_W * 0.55)          # 1056
    rx, rw = left_w + 64, g.SCREEN_W - left_w - 64 - 80
    swap = (anim('Conditional', [effect('fade', start=100, end=0, time=150),
                                 effect('slide', start='0,0', end='-80,0', time=150, tween='cubic', easing='in')],
                 eq('dswap', 'next')) +
            anim('Conditional', [effect('fade', start=100, end=0, time=150),
                                 effect('slide', start='0,0', end='80,0', time=150, tween='cubic', easing='in')],
                 eq('dswap', 'prev')))
    no_img = empty('d.img')
    content = group([
        image(0, 0, left_w, 1080, 'white.png', 'd.accent'),
        image((left_w - 240) // 2, 420, 240, 240, info('d.icon'), aspect='keep', background=True,
              visible=all_of(no_img, has('d.icon'))),
        label(0, 440, left_w, 200, info('d.ini'), 'font60', '#FFFFFFFF', align='center',
              visible=all_of(no_img, empty('d.icon'))),
        image(0, 0, left_w, 1080, info('d.img'), aspect='scale', background=True, visible=has('d.img')),
        image((left_w - 180) // 2, 450, 180, 180, 'play.png', '#E6FFFFFF', visible=has('d.play')),
        label(rx, 70, rw, 34, '[UPPERCASE]%s[/UPPERCASE]' % info('d.source'), 'font_flag', 'd.accent_text'),
        textbox(rx, 110, rw, 3 * g.line_px('font45') + 8, info('d.title'), 'font45', 'text'),
        label(rx, 330, rw, 36, info('d.byline'), 'font12', 'text2', cid=972),
        textbox(rx, 380, rw, 440, info('d.body'), 'font12', 'text', cid=g.DETAIL_BODY),
        image(rx, 862, 170, 170, info('d.qr'), aspect='keep', visible=has('d.qr')),
        label(rx + 196, 868, rw - 196, 34, info('t.scan'), 'font12', 'text2', visible=has('d.qr')),
        label(rx + 196, 910, rw - 196, 44, '[COLOR %s]%s[/COLOR]' % (info('d.accent_text'), info('t.play')),
              'font13', 'text', visible=has('d.play')),
        label(rx, 1006, rw, 34, info('t.hints'), 'font10', 'text2', visible=empty('d.qr')),
        label(rx + 196, 990, rw - 196, 40, info('t.hints'), 'font10', 'text2', wrap=True, visible=has('d.qr')),
        label(1460, 30, 380, 36, info('d.pos'), 'font12', 'text2', align='right'),
    ], animations=swap, cid=g.DETAIL_CONTENT)
    shown = eq('detail', 1)
    anims = (anim('Visible', [effect('fade', start=0, end=100, time=g.DETAIL_FADE_MS, delay=g.EXPAND_MS - 50)]) +
             anim('Hidden', [effect('fade', start=100, end=0, time=150)]))
    return group([image(0, 0, 1920, 1080, 'white.png', 'panel'), content], visible=shown, animations=anims,
                 cid=g.DETAIL)


def window(style):
    slots = []
    for size in ('large', 'wide', 'medium', 'small'):
        for i in range(g.POOLS[size]):
            slots.append(slot_xml(size, i, style))
    strip = group(headers() + slots, 0, 0, 1920, 1080, cid=g.STRIP)
    board_anims = (
        anim('Conditional', [effect('zoom', start=100, end=95, center='960,540', time=300, tween='cubic',
                                    easing='out'),
                             effect('fade', start=100, end=0, time=300)], eq('detail', 1)) +
        anim('Conditional', [effect('fade', start=100, end=0, time=g.THEME_FADE_MS)], eq('themefade', 1)) +
        anim('Conditional', [effect('fade', start=100, end=0, time=g.THEME_FADE_MS)], eq('relayout', 1)))
    board = group(chrome() + [strip], 0, 0, 1920, 1080, animations=board_anims, cid=g.BOARD)
    body = [
        image(-40, -40, 2000, 1160, 'white.png', 'bg'),
        '<control type="button" id="%d">%s<texturefocus/><texturenofocus/><label></label></control>'
        % (g.FOCUS_HOLDER, pos(-200, -200, 10, 10)),
        board,
        image(-60, -60, 4, 4, info('pre1'), background=True),
        image(-60, -60, 4, 4, info('pre2'), background=True),
        image(-60, -60, 4, 4, info('pre3'), background=True),
        group([image(0, 0, 1920, 1080, 'white.png', 'd.zcolor')], visible=eq('zoom', 1), cid=g.ZOOMER),
        detail(),
        image(-40, -40, 2000, 1160, 'white.png', 'dim', visible=has('dim'),
              extra=anim('Visible', [effect('fade', start=0, end=100, time=3000)])),
    ]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!-- Generated by tools/make_rsslivetiles_skin.py (style: %s); edit it there. -->\n'
            '<window>\n<defaultcontrol always="true">%d</defaultcontrol>\n'
            '<animation effect="fade" start="0" end="100" time="250">WindowOpen</animation>\n'
            '<animation effect="fade" start="100" end="0" time="200">WindowClose</animation>\n'
            '<controls>\n%s\n</controls>\n</window>\n' % (style, g.FOCUS_HOLDER, '\n'.join(body)))


def main():
    os.makedirs(OUT, exist_ok=True)
    for style in STYLES:
        xml = window(style)
        path = os.path.join(OUT, 'rsslivetiles-%s.xml' % style)
        with open(path, 'w') as handle:
            handle.write(xml)
        print('%s (%d KB, %d controls)' % (path, len(xml) // 1024, xml.count('<control ')))


if __name__ == '__main__':
    main()

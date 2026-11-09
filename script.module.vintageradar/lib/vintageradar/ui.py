"""The Vintage Radar window: every control is built at runtime.

Kodi's WindowXML skins cannot use an add-on's own font unless the active skin declares it, so
every string is drawn into a PNG by fontdraw and shown through a ControlImage. The radar art,
panel frames, contact pool, list, spotlight card and the full contact sheet are all controls
created here; the app's main loop only updates their positions, images and colours.
"""

import math
import os
import time

import xbmcgui

from . import radar_core, theme

VW, VH = 1920, 1080
PAGE_ROWS = 12
POOL = 48
MAX_ECHOES = 3

# The generated radar.png is a 1400 px square whose disc has a 630 px radius, so a control of
# 1400 * r / 630 squares the disc up with the native screensaver's 394 px disc.
ART = 1400.0
DISC = 630.0

# Rows in the spotlight card and the full contact sheet.
DETAIL_LABELS = (
    ('ALT', 'GS', 'VS', 'DIST'),
    ('TRK', 'IAS', 'TAS', 'MACH'),
    ('BRG', 'LAT', 'LON', 'SEEN'),
)
OVERLAY_COLUMNS = (
    ('CALLSIGN', 'REGISTRATION', 'TYPE', 'CATEGORY', 'HEX', 'SQUAWK', 'SOURCE', 'FLAGS',
     'LATITUDE', 'LONGITUDE', 'DISTANCE', 'BEARING', 'FIRST SEEN', 'LAST SEEN'),
    ('ALTITUDE', 'ALT GEOM', 'GROUND SPD', 'TRACK', 'MAG HDG', 'TRUE HDG', 'IAS', 'TAS',
     'MACH', 'BARO V/S', 'GEOM V/S', 'NAV ALT', 'NAV QNH', 'NAV HDG'),
    ('EMERGENCY', 'NACP', 'NACV', 'SIL', 'NIC', 'RC', 'MESSAGES', 'VERSION', 'RSSI', 'SEEN',
     'SEEN POS', 'ON GROUND', 'MLAT', 'TIS-B'),
)
OVERLAY_LABELS = OVERLAY_COLUMNS[0] + OVERLAY_COLUMNS[1] + OVERLAY_COLUMNS[2]

OVERLAY_X = 292
OVERLAY_Y = 150
OVERLAY_W = 1400
OVERLAY_H = 780
OVERLAY_GRID_Y = 306
OVERLAY_ROW_H = 30
OVERLAY_COL_X = (324, 782, 1240)


def make_layout(settings):
    if settings.show_panel:
        return {'cx': 500, 'cy': 576, 'r': 394, 'bez': 430, 'panel': True,
                'px': 956, 'py': 132, 'pw': 912, 'list_h': 536,
                'detail_y': 692, 'detail_h': 316}
    return {'cx': 960, 'cy': 576, 'r': 400, 'bez': 436, 'panel': False,
            'px': 0, 'py': 0, 'pw': 0, 'list_h': 0, 'detail_y': 0, 'detail_h': 0}


def pad2(value):
    return '%02d' % value


def seconds_short(seconds):
    if seconds < 0:
        return 'N/A'
    if seconds < 120.0:
        return '%.0fS' % seconds
    return '%.0fM' % (seconds / 60.0)


def clock_string():
    return time.strftime('%H:%M:%S')


def date_string():
    return time.strftime('%a %d %b %Y').upper()


class Screen(xbmcgui.WindowXML):
    """A plain WindowXML; callbacks only queue events for the app's loop, never touch controls."""

    def __init__(self, xml, addon_path):
        xbmcgui.WindowXML.__init__(self, xml, addon_path, 'Default', '1080i')
        self.builder = None
        self.scene = None
        self._events = []
        self.exit_requested = False

    def onInit(self):
        if self.scene is None and self.builder is not None:
            self.scene = self.builder(self)
            self.setFocusId(self.scene.anchor_id)

    def onClick(self, control_id):
        self._events.append(('click', control_id))

    def onAction(self, action):
        self._events.append(('action', action.getId()))

    def drain(self):
        events, self._events = self._events, []
        return events


class Scene(object):
    def __init__(self, window, media_dir, renderer, model, settings):
        self.window = window
        self.media = media_dir
        self.renderer = renderer
        self.model = model
        self.settings = settings
        self.palette = theme.palette(settings.theme)
        self.layout = make_layout(settings)

        self._solid = os.path.join(media_dir, 'solid.png')
        self._clear = os.path.join(media_dir, 'transparent.png')
        self._radar_art = os.path.join(media_dir, 'radar.png')
        self._sweep_art = os.path.join(media_dir, 'sweep.png')
        self._blip_art = os.path.join(media_dir, 'blip.png')
        self._echo_art = os.path.join(media_dir, 'echo.png')
        self._ring_art = os.path.join(media_dir, 'ring.png')
        self._scan_art = os.path.join(media_dir, 'scanlines.png')
        self._panel_list_art = os.path.join(media_dir, 'panel_list.png')
        self._panel_detail_art = os.path.join(media_dir, 'panel_detail.png')
        self._panel_overlay_art = os.path.join(media_dir, 'panel_overlay.png')

        self._controls = []
        self._initial_hidden = []
        self._buttons = []
        self.click_roles = {}
        self._shown = {}
        self._sigs = {}
        self._keys = {}
        self._images = {}
        self._positions = {}

        self.anchor_id = 0
        self.overlay_open = False
        self.label_offsets = {}
        self.label_boxes = {}
        self.row_hex = [''] * PAGE_ROWS
        self.blip_hex = [''] * POOL
        self._row_visible = [False] * PAGE_ROWS

        self.panel_controls = []
        self._build()

    # ---- control creation ------------------------------------------------------------------

    def _new_image(self, path, color=None, size=(1, 1)):
        control = xbmcgui.ControlImage(0, 0, size[0], size[1], path, aspectRatio=0,
                                       colorDiffuse=color or 'FFFFFFFF')
        self._controls.append(control)
        self._initial_hidden.append(control)
        return control

    def _new_text(self):
        control = self._new_image(self._solid)
        return control

    def _new_button(self, role, x=0, y=0, w=1, h=1):
        control = xbmcgui.ControlButton(x, y, w, h, '', focusTexture=self._clear,
                                        noFocusTexture=self._clear)
        self._controls.append(control)
        self._initial_hidden.append(control)
        self._buttons.append((control, role))
        return control

    def _build(self):
        # Background, radar face, sweep and its compass ring labels.
        self.bg = self._new_image(self._solid, 'FF020403', (VW, VH))
        self.radar = self._new_image(self._radar_art)
        self.sweep = self._new_image(self._sweep_art)
        self.range_labels = [self._new_text() for _ in range(4)]

        self.echoes = [[self._new_image(self._echo_art) for _ in range(MAX_ECHOES)]
                       for _ in range(POOL)]
        self.rings = [self._new_image(self._ring_art) for _ in range(POOL)]
        self.blips = [self._new_image(self._blip_art) for _ in range(POOL)]
        self.labels1 = [self._new_text() for _ in range(POOL)]
        self.labels2 = [self._new_text() for _ in range(POOL)]

        # Header and footer.
        self.title = self._new_text()
        self.subtitle = self._new_text()
        self.clock = self._new_text()
        self.date = self._new_text()
        self.status = self._new_text()
        self.header_rule1 = self._new_image(self._solid)
        self.header_rule2 = self._new_image(self._solid)
        self.footer_rule = self._new_image(self._solid)
        self.footer_range = self._new_text()
        self.footer_sweep = self._new_text()
        self.footer_source = self._new_text()
        self.footer_error = self._new_text()

        # Panels.
        self.fill_list = self._new_image(self._solid)
        self.fill_detail = self._new_image(self._solid)
        self.panel_list = self._new_image(self._panel_list_art)
        self.panel_detail = self._new_image(self._panel_detail_art)
        self.panel_controls = [self.fill_list, self.fill_detail, self.panel_list,
                               self.panel_detail]

        # Contact list.
        self.list_title = self._new_text()
        self.list_count = self._new_text()
        self.list_sub = self._new_text()
        self.list_headers = [self._new_text() for _ in range(6)]
        self.list_rule_top = self._new_image(self._solid)
        self.list_rule_bottom = self._new_image(self._solid)
        self.list_highlight = self._new_image(self._solid)
        self.list_highlight_bar = self._new_image(self._solid)
        self.row_cells = [[self._new_text() for _ in range(6)] for _ in range(PAGE_ROWS)]
        self.empty1 = self._new_text()
        self.empty2 = self._new_text()
        self.row_buttons = [self._new_button(('row', row)) for row in range(PAGE_ROWS)]
        self.panel_controls.extend([self.list_title, self.list_count, self.list_sub,
                                    self.list_rule_top, self.list_rule_bottom,
                                    self.list_highlight, self.list_highlight_bar,
                                    self.empty1, self.empty2])
        for row in range(PAGE_ROWS):
            self.panel_controls.extend(self.row_cells[row])
        self.panel_controls.extend(self.list_headers)
        self.panel_controls.extend(self.row_buttons)

        # Spotlight card.
        self.detail_title = self._new_text()
        self.detail_pos = self._new_text()
        self.detail_mode = self._new_text()
        self.detail_name = self._new_text()
        self.detail_kind = self._new_text()
        self.detail_info = self._new_text()
        self.detail_bar_base = self._new_image(self._solid)
        self.detail_bar = self._new_image(self._solid)
        self.detail_labels = [self._new_text() for _ in range(12)]
        self.detail_values = [self._new_text() for _ in range(12)]
        self.detail_quality = self._new_text()
        self.detail_nav = self._new_text()
        self.detail_flags = self._new_text()
        self.detail_empty1 = self._new_text()
        self.detail_empty2 = self._new_text()
        self.panel_controls.extend([self.detail_title, self.detail_pos, self.detail_mode,
                                    self.detail_name, self.detail_kind, self.detail_info,
                                    self.detail_bar_base, self.detail_bar,
                                    self.detail_quality, self.detail_nav, self.detail_flags,
                                    self.detail_empty1, self.detail_empty2])
        self.panel_controls.extend(self.detail_labels)
        self.panel_controls.extend(self.detail_values)

        # CRT scanlines and the dimming layer sit above the scope.
        self.scan = self._new_image(self._scan_art, 'FFFFFFFF', (VW, VH))
        self.dim = self._new_image(self._solid, 'FF000000', (VW, VH))

        # Invisible click targets: the focus anchor, one per contact, one per list row.
        self.anchor = self._new_button(('anchor',))
        # The anchor must stay visible to be focusable; its textures are fully transparent.
        self._initial_hidden.remove(self.anchor)
        self.hotspots = [self._new_button(('blip', index)) for index in range(POOL)]

        # Full contact sheet, above everything else.
        self.ov_dim = self._new_image(self._solid, 'FF000000', (VW, VH))
        self.ov_fill = self._new_image(self._solid)
        self.ov_panel = self._new_image(self._panel_overlay_art)
        self.ov_title = self._new_text()
        self.ov_name = self._new_text()
        self.ov_kind = self._new_text()
        self.ov_spot = self._new_text()
        self.ov_rule = self._new_image(self._solid)
        self.ov_labels = [self._new_text() for _ in OVERLAY_LABELS]
        self.ov_values = [self._new_text() for _ in OVERLAY_LABELS]
        self.ov_hint = self._new_text()
        self.overlay_controls = [self.ov_dim, self.ov_fill, self.ov_panel, self.ov_title,
                                 self.ov_name, self.ov_kind, self.ov_spot, self.ov_rule,
                                 self.ov_hint]
        self.overlay_controls.extend(self.ov_labels)
        self.overlay_controls.extend(self.ov_values)
        self.close_button = self._new_button(('overlay_close',))
        self.overlay_controls.append(self.close_button)

        # Attach in chunks; Kodi blocks the GUI while adding, so keep each hold short.
        for start in range(0, len(self._controls), 64):
            self.window.addControls(self._controls[start:start + 64])
        for control in self._initial_hidden:
            control.setVisible(False)
            self._shown[id(control)] = False
        for control, role in self._buttons:
            try:
                self.click_roles[control.getId()] = role
            except Exception:
                pass
        self.anchor_id = self.anchor.getId()
        self.close_id = self.close_button.getId()
        self._place_overlay_chrome()

    # ---- helpers ---------------------------------------------------------------------------

    def _visible(self, control, wanted):
        key = id(control)
        if self._shown.get(key, True) == wanted:
            return
        control.setVisible(wanted)
        self._shown[key] = wanted

    def _fit(self, text, atlas, max_width, tracking=0.0):
        if self.renderer.width(text, atlas, tracking) <= max_width:
            return text
        return radar_core.fit_text(
            lambda value: self.renderer.width(value, atlas, tracking), text, max_width)

    def _text(self, control, text, atlas='small', color=None, x=0, y=0, align=0,
              tracking=0.0, alpha=1.0, visible=True, max_width=None):
        key = id(control)
        color = color or self.palette.primary
        if text is None:
            text = ''
        if max_width is not None:
            text = self._fit(text, atlas, max_width, tracking)
        signature = (text, atlas, tuple(color), round(tracking, 2), round(alpha, 2))
        if self._sigs.get(key) != signature:
            image = self.renderer.image(text, atlas, color, tracking, alpha)
            control.setImage(image.path)
            control.setWidth(image.width)
            control.setHeight(image.height)
            self._sigs[key] = signature
            self._keys[key] = image.key
            self._images[key] = image
        image = self._images.get(key)
        if image is None:
            return
        position = image.place(x, y, align)
        if self._positions.get(key) != position:
            control.setPosition(position[0], position[1])
            self._positions[key] = position
        self._visible(control, visible)

    def _solid_rect(self, control, x, y, w, h, color, alpha=255):
        if w <= 0 or h <= 0:
            self._visible(control, False)
            return
        control.setPosition(int(round(x)), int(round(y)))
        control.setWidth(int(round(w)))
        control.setHeight(int(round(h)))
        control.setColorDiffuse(theme.argb(color, int(round(alpha * 255.0))))
        self._visible(control, True)

    def _protect(self):
        self.renderer.protect(self._keys.values())

    # ---- settings and static chrome ---------------------------------------------------------

    def apply_settings(self, settings):
        self.settings = settings
        self.palette = theme.palette(settings.theme)
        self.layout = make_layout(settings)
        layout = self.layout
        palette = self.palette

        scale = layout['r'] / DISC
        size = int(round(ART * scale))
        left = int(round(layout['cx'] - size * 0.5))
        top = int(round(layout['cy'] - size * 0.5))
        for control in (self.radar, self.sweep):
            control.setPosition(left, top)
            control.setWidth(size)
            control.setHeight(size)
        self.radar.setColorDiffuse(theme.argb(palette.primary))
        self.sweep.setColorDiffuse(theme.argb(palette.primary))
        self.scan.setColorDiffuse(theme.argb((255, 255, 255)))
        # The scope is opaque; the app and the screensaver both cover whatever is behind them.
        self._visible(self.bg, True)
        self._visible(self.radar, True)
        self._visible(self.sweep, True)
        self._visible(self.scan, settings.crt)

        self._set_sweep_animation()

        # Lines.
        self._solid_rect(self.header_rule1, 30, 117, 490, 2, palette.primary, 0.55)
        self._solid_rect(self.header_rule2, 520, 118, 1370, 1, palette.dim, 0.35)
        self._solid_rect(self.footer_rule, 30, 1028, 1860, 1, palette.dim, 0.35)
        self._solid_rect(self.dim, 0, 0, VW, VH, (0, 0, 0), 1.0)
        self.dim.setColorDiffuse(theme.argb((0, 0, 0),
                                            int(round(settings.dim / 100.0 * 255.0))))
        self._visible(self.dim, settings.dim > 0)

        # Panels.
        for control in self.panel_controls:
            self._visible(control, layout['panel'])
        if layout['panel']:
            x, y, w = layout['px'], layout['py'], layout['pw']
            detail_y = layout['detail_y']
            fill = theme.argb(palette.fill, 238)
            self.fill_list.setColorDiffuse(fill)
            self.fill_detail.setColorDiffuse(fill)
            self.fill_list.setPosition(x, y)
            self.fill_list.setWidth(w)
            self.fill_list.setHeight(layout['list_h'])
            self.fill_detail.setPosition(x, detail_y)
            self.fill_detail.setWidth(w)
            self.fill_detail.setHeight(layout['detail_h'])
            self.panel_list.setPosition(x + 2, y - 2)
            self.panel_detail.setPosition(x + 2, detail_y)
            self.panel_list.setColorDiffuse(theme.argb(palette.primary))
            self.panel_detail.setColorDiffuse(theme.argb(palette.primary))
            self._solid_rect(self.list_rule_top, x + 14, 224, w - 34, 1, palette.dim, 0.35)
            self._solid_rect(self.list_rule_bottom, x + 14, 665, w - 34, 1, palette.dim, 0.22)
            for row in range(PAGE_ROWS):
                button = self.row_buttons[row]
                button.setPosition(x + 14, 231 + row * 36)
                button.setWidth(w - 28)
                button.setHeight(34)
            self.detail_bar_base.setPosition(x + 22, detail_y + 112)
            self.detail_bar_base.setWidth(w - 44)
            self.detail_bar_base.setHeight(2)
            self.detail_bar_base.setColorDiffuse(theme.argb(palette.dim, 90))
            self.detail_bar.setHeight(2)

        self._build_static()
        self._update_compass()
        self._update_pool(self.model, time.monotonic())

    def _set_sweep_animation(self):
        ms = max(1000, int(round(self.settings.sweep_seconds * 1000.0)))
        self.sweep.setAnimations([
            ('conditional', 'effect=rotate start=0 end=360 center=auto time=%d loop=true '
                            'condition=true' % ms)])

    def _build_static(self):
        palette = self.palette
        layout = self.layout
        self._text(self.title, 'VINTAGE RADAR', 'big', palette.primary, 34, 8,
                   tracking=1.6)
        self._text(self.detail_title, 'SPOTLIGHT', 'tiny', palette.dim,
                   layout['px'] + 22, layout['detail_y'] + 12, tracking=1.0,
                   visible=layout['panel'])
        self._text(self.list_title, 'CONTACTS', 'small', palette.bright,
                   layout['px'] + 22, 140, tracking=1.0, visible=layout['panel'])
        headers = (('CALLSIGN', layout['px'] + 44, 0),
                   ('TYPE', layout['px'] + 274, 0),
                   ('ALT', layout['px'] + 464, 2),
                   ('SPD', layout['px'] + 604, 2),
                   ('DIST', layout['px'] + 764, 2),
                   ('BRG', layout['px'] + layout['pw'] - 20, 2))
        for control, (label, x, align) in zip(self.list_headers, headers):
            self._text(control, label, 'tiny', palette.faint, x, 202, align=align,
                       visible=layout['panel'])
        self._text(self.empty1, 'NO CONTACTS IN RANGE', 'small', palette.dim,
                   layout['px'] + layout['pw'] * 0.5, 380, align=1, visible=False)
        self._text(self.empty2, 'WAITING FOR A SWEEP', 'tiny', palette.faint,
                   layout['px'] + layout['pw'] * 0.5, 416, align=1, visible=False)
        self._text(self.detail_empty1, 'NO CONTACT', 'mid', palette.dim,
                   layout['px'] + layout['pw'] * 0.5, layout['detail_y'] + 100, align=1,
                   visible=False)
        self._text(self.detail_empty2, 'THE SCOPE IS CLEAR', 'tiny', palette.faint,
                   layout['px'] + layout['pw'] * 0.5, layout['detail_y'] + 150, align=1,
                   visible=False)

        # Detail field names and their value columns.
        value_x = []
        for column in range(4):
            labels = [DETAIL_LABELS[row][column] for row in range(3)]
            base = (layout['px'] + 22, layout['px'] + 242, layout['px'] + 462,
                    layout['px'] + 682)[column]
            widest = max(self.renderer.width(label + ' ', 'tiny') for label in labels)
            value_x.append(base + widest + 3)
        self._detail_value_x = value_x
        for row in range(3):
            y = layout['detail_y'] + 126 + row * 27
            for column in range(4):
                index = row * 4 + column
                self._text(self.detail_labels[index], DETAIL_LABELS[row][column] + ' ',
                           'tiny', palette.dim, (layout['px'] + 22, layout['px'] + 242,
                                                 layout['px'] + 462, layout['px'] + 682)[column],
                           y + 5, alpha=0.72, visible=layout['panel'])

        self._text(self.ov_title, 'CONTACT CARD', 'mid', palette.bright,
                   OVERLAY_X + 32, OVERLAY_Y + 18, tracking=1.4, visible=False)
        self._text(self.ov_hint,
                   'LEFT / RIGHT STEP CONTACTS   ·   BACK CLOSES THIS CARD', 'tiny',
                   palette.faint, OVERLAY_X + 32, OVERLAY_Y + OVERLAY_H - 34, visible=False)
        self._solid_rect(self.ov_rule, OVERLAY_X + 32, OVERLAY_Y + 130,
                         OVERLAY_W - 64, 1, palette.primary, 0.32)
        self._visible(self.ov_rule, False)
        for index, label in enumerate(OVERLAY_LABELS):
            column, row = index // 14, index % 14
            self._text(self.ov_labels[index], label, 'tiny', palette.dim,
                       OVERLAY_COL_X[column], OVERLAY_GRID_Y + row * OVERLAY_ROW_H + 6,
                       visible=False)

        self.ov_fill.setPosition(OVERLAY_X, OVERLAY_Y)
        self.ov_fill.setWidth(OVERLAY_W)
        self.ov_fill.setHeight(OVERLAY_H)
        self.ov_fill.setColorDiffuse(theme.argb(palette.fill, 245))
        self.ov_panel.setPosition(OVERLAY_X, OVERLAY_Y)
        self.ov_panel.setWidth(OVERLAY_W)
        self.ov_panel.setHeight(OVERLAY_H)
        self.ov_panel.setColorDiffuse(theme.argb(palette.primary))
        self.ov_dim.setColorDiffuse(theme.argb((0, 0, 0), int(round(0.80 * 255))))
        self.close_button.setPosition(0, 0)
        self.close_button.setWidth(VW)
        self.close_button.setHeight(VH)

    def _place_overlay_chrome(self):
        # Called once from _build; settings/build_static may not have run yet, so this only
        # sets the controls that never move.
        self.close_button.setPosition(0, 0)
        self.close_button.setWidth(VW)
        self.close_button.setHeight(VH)

    def _update_compass(self):
        layout = self.layout
        palette = self.palette
        angle = math.radians(45.0)
        for index in range(4):
            fraction = (index + 1) / 4.0
            km = int(round(self.settings.range_km * fraction))
            text = ('%dKM' % km) if index == 3 else str(km)
            distance = layout['r'] * (0.955 if index == 3 else fraction)
            x = layout['cx'] + math.sin(angle) * distance + 7
            y = layout['cy'] - math.cos(angle) * distance - 9
            self._text(self.range_labels[index], text, 'tiny', palette.faint, x, y)

    # ---- per-frame contact pool -------------------------------------------------------------

    def update_contacts(self, model, now):
        self.model = model
        self._update_pool(model, now)

    def _update_pool(self, model, now):
        palette = self.palette
        settings = self.settings
        layout = self.layout
        order = model.order
        history = settings.show_history and settings.quality > 0

        for slot in range(POOL):
            if slot >= len(order):
                self._visible(self.blips[slot], False)
                self._visible(self.rings[slot], False)
                for echo in self.echoes[slot]:
                    self._visible(echo, False)
                self._visible(self.labels1[slot], False)
                self._visible(self.labels2[slot], False)
                self._visible(self.hotspots[slot], False)
                self.blip_hex[slot] = ''
                self.label_boxes.pop(slot, None)
                continue

            contact = model.contacts[order[slot]]
            ac = contact.ac
            x = layout['cx'] + contact.x * layout['r']
            y = layout['cy'] - contact.y * layout['r']
            self.blip_hex[slot] = ac.hex

            if settings.quality > 0 and history:
                count = contact.echo_count
            else:
                count = 0
            for index, control in enumerate(self.echoes[slot]):
                echo = contact.echoes[index]
                if index >= count or not echo.active:
                    self._visible(control, False)
                    continue
                ex = layout['cx'] + echo.x * layout['r']
                ey = layout['cy'] - echo.y * layout['r']
                size = 30 + 10 * index
                control.setPosition(int(round(ex - size * 0.5)),
                                    int(round(ey - size * 0.5)))
                control.setWidth(size)
                control.setHeight(size)
                alpha = min(0.30, 0.26 * contact.blip / (1.0 + index))
                control.setColorDiffuse(theme.argb(palette.primary, int(alpha * 255)))
                self._visible(control, True)

            selected = contact.selected
            if ac.on_ground:
                size = 44
                color = palette.ground
                alpha = min(1.0, 0.55 + 0.25 * contact.blip)
            else:
                size = 56
                color = palette.alert if radar_core.emergency_label(ac) else palette.primary
                if selected:
                    color = palette.bright
                alpha = min(1.0, 0.20 + 0.78 * contact.blip)
            control = self.blips[slot]
            control.setPosition(int(round(x - size * 0.5)), int(round(y - size * 0.5)))
            control.setWidth(size)
            control.setHeight(size)
            control.setColorDiffuse(theme.argb(color, int(round(alpha * 255.0))))
            self._visible(control, True)

            ring = self.rings[slot]
            if selected:
                ring.setPosition(int(round(x - 30)), int(round(y - 30)))
                ring.setWidth(60)
                ring.setHeight(60)
                ring.setColorDiffuse(theme.argb(palette.bright, 190))
                self._visible(ring, True)
            else:
                self._visible(ring, False)

            hotspot = self.hotspots[slot]
            box = (x - 32, y - 32, 64, 64)
            label = self.label_boxes.get(slot)
            if label is not None:
                # Let the visible label be part of the click target too.
                lx, ly, lw, lh = label
                left = min(box[0], x + lx)
                top = min(box[1], y + ly)
                right = max(box[0] + box[2], x + lx + lw)
                bottom = max(box[1] + box[3], y + ly + lh)
                box = (left, top, right - left, bottom - top)
            hotspot.setPosition(int(round(box[0])), int(round(box[1])))
            hotspot.setWidth(max(1, int(round(box[2]))))
            hotspot.setHeight(max(1, int(round(box[3]))))
            self._visible(hotspot, True)

            # Labels keep their chosen offset while the blip drifts between text updates.
            offset = self.label_offsets.get(slot)
            if offset is not None:
                self.labels1[slot].setPosition(int(round(x + offset[0])),
                                               int(round(y + offset[1])))
                self.labels2[slot].setPosition(int(round(x + offset[2])),
                                               int(round(y + offset[3])))

    # ---- text groups -----------------------------------------------------------------------

    def update_group(self, group, model, now):
        self.model = model
        self._protect()
        if group == 'clock':
            self._update_clock(model, now)
        elif group == 'header':
            self._update_header(model, now)
        elif group == 'footer':
            self._update_footer(model, now)
        elif group == 'list':
            self._update_list(model, now)
        elif group == 'detail':
            self._update_detail(model, now)
        elif group == 'labels':
            self._update_labels(model, now)
        elif group == 'bar':
            self._update_bar(model)
        elif group == 'overlay':
            if self.overlay_open:
                self._update_overlay(model, now)

    def _update_clock(self, model, now):
        palette = self.palette
        self._text(self.clock, clock_string(), 'mid', palette.bright, 1886, 6, align=2)
        self._text(self.date, date_string(), 'tiny', palette.dim, 1886, 58, align=2)
        age = model.feed_age(now)
        if age < 0.0:
            status, color = 'ACQUIRING SIGNAL', palette.dim
        elif model.stale(now):
            status, color = 'STALE ' + seconds_short(age), palette.alert
        else:
            status, color = 'LIVE  ' + seconds_short(age) + ' AGO', palette.primary
        self._text(self.status, status, 'tiny', color, 1886, 80, align=2)

    def _update_header(self, model, now):
        palette = self.palette
        subtitle = ('AIRCRAFT OVERHEAD  ·  %s  ·  RANGE %s' %
                    (radar_core.upper_string(self.settings.location_name),
                     radar_core.range_short(self.settings.range_km, self.settings.units)))
        self._text(self.subtitle, subtitle, 'small', palette.dim, 36, 80, max_width=1400)

    def _update_footer(self, model, now):
        palette = self.palette
        self._text(self.footer_range,
                   'RANGE %s' % radar_core.range_text(self.settings.range_km,
                                                      self.settings.units),
                   'tiny', palette.dim, 34, 1038, alpha=0.85)
        self._text(self.footer_sweep,
                   'SWEEP %02dS  ·  %d IN RANGE  ·  %d TRACKED' % (
                       int(round(self.settings.sweep_seconds)), model.in_range_count,
                       len(model.contacts)),
                   'tiny', palette.dim, 960, 1038, align=1, alpha=0.85)
        source = model.feed_source or 'NO FEED'
        age = model.feed_age(now)
        self._text(self.footer_source,
                   'SOURCE %s  ·  %s' % (radar_core.upper_string(source),
                                         'N/A' if age < 0 else seconds_short(age)),
                   'tiny', palette.dim, 1886, 1038, align=2, alpha=0.85)
        error = model.feed_error if (model.feed_error and model.stale(now)) else ''
        self._text(self.footer_error, ('FEED ERROR  ' + error) if error else '',
                   'tiny', palette.alert, 960, 1058, align=1, alpha=0.95,
                   visible=bool(error), max_width=1200)

    def _update_list(self, model, now):
        palette = self.palette
        layout = self.layout
        if not layout['panel']:
            return
        x, w = layout['px'], layout['pw']
        right = x + w - 20
        self._text(self.list_count,
                   '%d IN RANGE / %d' % (model.in_range_count, len(model.contacts)),
                   'tiny', palette.dim, right, 146, align=2)
        self._text(self.list_sub,
                   'NEAREST FIRST   PAGE %d/%d' % (model.page + 1, model.page_count()),
                   'tiny', palette.faint, right, 163, align=2)
        self._visible(self.empty1, not model.order)
        self._visible(self.empty2, not model.order)

        selected_row = -1
        start = model.page * PAGE_ROWS
        for row in range(PAGE_ROWS):
            position = start + row
            cells = self.row_cells[row]
            if position >= len(model.order):
                for control in cells:
                    self._visible(control, False)
                self._visible(self.row_buttons[row], False)
                self.row_hex[row] = ''
                self._row_visible[row] = False
                continue
            self._row_visible[row] = True
            self._visible(self.row_buttons[row], True)
            contact = model.contacts[model.order[position]]
            ac = contact.ac
            self.row_hex[row] = ac.hex
            ry = 232 + row * 36
            if contact.selected:
                selected_row = row
            name_color = palette.bright if contact.selected else (
                palette.alert if radar_core.emergency_label(ac)
                else (palette.military if ac.military else palette.primary))
            alpha = 1.0 if contact.selected else 0.9
            name = radar_core.truncate_text(radar_core.aircraft_name(ac), 9)
            kind = ac.type_code or radar_core.category_name(ac.category)
            self._text(cells[0], name, 'small', name_color, x + 44, ry + 5,
                       alpha=alpha)
            self._text(cells[1], radar_core.truncate_text(kind, 6), 'tiny', palette.dim,
                       x + 274, ry + 8, alpha=0.85)
            value_alpha = 1.0 if contact.selected else 0.8
            self._text(cells[2], radar_core.fmt_altitude(ac, self.settings.units, True),
                       'small', palette.primary, x + 464, ry + 7, align=2,
                       alpha=value_alpha)
            self._text(cells[3], radar_core.fmt_speed(ac, self.settings.units, True),
                       'small', palette.primary, x + 604, ry + 7, align=2,
                       alpha=value_alpha)
            self._text(cells[4], radar_core.fmt_distance(contact.distance_m,
                                                         self.settings.units, True),
                       'small', palette.primary, x + 764, ry + 7, align=2,
                       alpha=value_alpha)
            self._text(cells[5], radar_core.fmt_bearing(contact.bearing_deg), 'small',
                       palette.dim, right, ry + 7, align=2, alpha=value_alpha)

        if selected_row >= 0:
            ry = 232 + selected_row * 36
            self._solid_rect(self.list_highlight, x + 14, ry - 1, w - 28, 34,
                             palette.primary, 0.10)
            self._solid_rect(self.list_highlight_bar, x + 14, ry - 1, 3, 34,
                             palette.bright, 0.90)
        else:
            self._visible(self.list_highlight, False)
            self._visible(self.list_highlight_bar, False)

    def _update_detail(self, model, now):
        palette = self.palette
        layout = self.layout
        if not layout['panel']:
            return
        x = layout['px']
        detail_y = layout['detail_y']
        right = x + layout['pw'] - 20
        contact = model.spotlight()
        position = model.spotlight_position()
        total = len(model.order)

        self._text(self.detail_pos,
                   '%d / %d' % (position + 1, total) if position >= 0 else '-- / --',
                   'tiny', palette.faint, x + 150, detail_y + 12, alpha=0.9)
        self._text(self.detail_mode, 'PINNED' if model.pinned else 'AUTO', 'tiny',
                   palette.bright if model.pinned else palette.dim, right, detail_y + 12,
                   align=2, alpha=0.9)

        if contact is None:
            for control in (self.detail_name, self.detail_kind, self.detail_info,
                            self.detail_quality, self.detail_nav, self.detail_flags):
                self._visible(control, False)
            for control in self.detail_values:
                self._visible(control, False)
            for control in self.detail_labels:
                self._visible(control, False)
            self.detail_empty1.setPosition(int(x + layout['pw'] * 0.5), detail_y + 100)
            self.detail_empty2.setPosition(int(x + layout['pw'] * 0.5), detail_y + 150)
            self._visible(self.detail_empty1, True)
            self._visible(self.detail_empty2, True)
            self._visible(self.detail_bar_base, False)
            self._visible(self.detail_bar, False)
            return

        for control in (self.detail_empty1, self.detail_empty2):
            self._visible(control, False)
        ac = contact.ac
        name = radar_core.truncate_text(radar_core.aircraft_name(ac), 12)
        name_color = palette.alert if radar_core.emergency_label(ac) else palette.bright
        self._text(self.detail_name, name, 'mid', name_color, x + 22, detail_y + 38,
                   tracking=1.2)
        name_width = self.renderer.width(name, 'mid', 1.2)
        kind = ac.type_code or radar_core.category_name(ac.category)
        if ac.reg and radar_core.upper_string(ac.reg) != name:
            kind = radar_core.upper_string(ac.reg) + '  ' + kind
        self._text(self.detail_kind, radar_core.truncate_text(kind, 22), 'small',
                   palette.dim, x + 22 + name_width + 20, detail_y + 50, alpha=0.95)

        info = 'HEX ' + radar_core.upper_string(ac.hex)
        if ac.squawk:
            info += '  ·  SQK ' + ac.squawk
        if ac.category:
            info += '  ·  %s %s' % (ac.category, radar_core.category_name(ac.category))
        info += '  ·  ' + radar_core.source_name(ac)
        if ac.type:
            info += '  ·  ' + radar_core.upper_string(ac.type)
        self._text(self.detail_info, info, 'tiny', palette.dim, x + 22, detail_y + 88,
                   alpha=0.95, max_width=layout['pw'] - 44)

        self._visible(self.detail_bar_base, True)
        self._update_bar(model)

        values = (
            radar_core.fmt_altitude(ac, self.settings.units),
            radar_core.fmt_speed(ac, self.settings.units),
            radar_core.fmt_vertical_rate(ac, self.settings.units),
            radar_core.fmt_distance(contact.distance_m, self.settings.units),
            radar_core.fmt_deg(ac.track if ac.has_track else ac.true_heading),
            ('%dKT' % radar_core._round_half_away(ac.ias_kt)) if ac.has_ias else '--',
            ('%dKT' % radar_core._round_half_away(ac.tas_kt)) if ac.has_tas else '--',
            ('%.2f' % ac.mach) if ac.has_mach else '--',
            radar_core.fmt_bearing(contact.bearing_deg),
            radar_core.fmt_coord(contact.lat, True),
            radar_core.fmt_coord(contact.lon, False),
            radar_core.fmt_seen(ac.seen_pos if ac.has_seen_pos else ac.seen),
        )
        for row in range(3):
            y = detail_y + 126 + row * 27
            for column in range(4):
                index = row * 4 + column
                self._text(self.detail_labels[index],
                           DETAIL_LABELS[row][column] + ' ', 'tiny', palette.dim,
                           (x + 22, x + 242, x + 462, x + 682)[column], y + 5, alpha=0.72)
                self._text(self.detail_values[index], values[index], 'small',
                           palette.primary, self._detail_value_x[column], y - 1)

        quality = 'NACp %.0f   NACv %.0f   SIL %.0f   NIC %.0f   RC %.0fM   MSG %d   VER %d' % (
            ac.nac_p if ac.has_nac_p else 0.0, ac.nac_v if ac.has_nac_v else 0.0,
            ac.sil if ac.has_sil else 0.0, ac.nic if ac.has_nic else 0.0,
            ac.rc_m if ac.has_rc else 0.0, ac.messages, ac.version)
        self._text(self.detail_quality, quality, 'tiny', palette.faint, x + 22,
                   detail_y + 207, alpha=0.95)

        parts = []
        if ac.has_nav_alt:
            parts.append('NAV ALT %s' % radar_core.fmt_commas(
                radar_core._round_half_away(ac.nav_alt_ft)))
        if ac.has_nav_qnh:
            parts.append('QNH %.0f' % ac.nav_qnh)
        if ac.has_nav_heading:
            parts.append('NAV HDG ' + radar_core.fmt_deg(ac.nav_heading))
        if ac.has_mag_heading:
            parts.append('MAG ' + radar_core.fmt_deg(ac.mag_heading))
        if ac.has_true_heading:
            parts.append('TRUE ' + radar_core.fmt_deg(ac.true_heading))
        if ac.has_alt_geom:
            parts.append('GEOM ALT %s' % radar_core.fmt_commas(
                radar_core._round_half_away(ac.alt_geom_ft)))
        nav = '   '.join(parts) or 'NO NAVIGATION DATA'
        self._text(self.detail_nav, nav, 'tiny', palette.dim, x + 22, detail_y + 232,
                   alpha=0.9, max_width=layout['pw'] - 44)

        flags = radar_core.flag_text(ac)
        if flags:
            self._text(self.detail_flags, '! ' + flags, 'tiny', palette.alert, x + 22,
                       detail_y + 257, tracking=0.5, max_width=layout['pw'] - 44)
        else:
            self._text(self.detail_flags, 'RX ' + radar_core.fmt_seen(
                ac.seen if ac.has_seen else ac.seen_pos), 'tiny', palette.faint,
                x + 22, detail_y + 257, alpha=0.9)

    def _update_bar(self, model):
        layout = self.layout
        if not layout['panel']:
            return
        x = layout['px']
        bar_y = layout['detail_y'] + 112
        width = layout['pw'] - 44
        progress = model.spotlight_progress()
        if progress > 0.0:
            self._solid_rect(self.detail_bar, x + 22, bar_y, max(2, width * progress), 2,
                             self.palette.primary, 0.65)
        elif model.pinned:
            self._solid_rect(self.detail_bar, x + 22, bar_y, width, 2,
                             self.palette.bright, 0.80)
        else:
            self._visible(self.detail_bar, False)

    def _update_labels(self, model, now):
        palette = self.palette
        layout = self.layout
        cap = 10 if self.settings.quality == 0 else 18
        used = []
        drawn = 0
        # Labels live on the scope only; they must not slide under a side panel.
        right_limit = layout['cx'] + layout['bez'] - 8

        for slot, index in enumerate(model.order[:POOL]):
            contact = model.contacts[index]
            control1 = self.labels1[slot]
            control2 = self.labels2[slot]
            if not self.settings.show_labels:
                self._visible(control1, False)
                self._visible(control2, False)
                self.label_boxes.pop(slot, None)
                continue
            if not contact.selected and drawn >= cap:
                self._visible(control1, False)
                self._visible(control2, False)
                self.label_boxes.pop(slot, None)
                continue

            ac = contact.ac
            l1 = radar_core.truncate_text(radar_core.aircraft_name(ac), 12)
            l2 = ''
            if self.settings.label_detail == 1:
                l2 = '%s  %s' % (radar_core.fmt_altitude(ac, self.settings.units, True),
                                 radar_core.fmt_speed(ac, self.settings.units, True))
            elif self.settings.label_detail == 2:
                kind = ac.type_code or radar_core.category_name(ac.category)
                l2 = '%s  %s' % (kind,
                                 radar_core.fmt_altitude(ac, self.settings.units, True))
            if ac.on_ground:
                l2 = 'GND  %s' % radar_core.fmt_speed(ac, self.settings.units, True)

            color = palette.alert if radar_core.emergency_label(ac) else palette.primary
            alpha = 0.82
            if contact.selected:
                color = palette.bright
                alpha = 1.0
            image1 = self.renderer.image(l1, 'small', color, 0.4, alpha)
            image2 = (self.renderer.image(l2, 'tiny', color, 0.2, alpha * 0.75)
                      if l2 else None)
            width = max(image1.text_width,
                        image2.text_width if image2 else 0.0) + 6.0
            height = image1.height if image2 is None else image1.height + 18

            bx = layout['cx'] + contact.x * layout['r']
            by = layout['cy'] - contact.y * layout['r']
            candidates = ((bx + 15, by - height + 4), (bx - 15 - width, by - height + 4),
                          (bx + 15, by + 12), (bx - 15 - width, by + 12))
            chosen = None
            for cx, cy in candidates:
                if cx < 24 or cy < 132 or cx + width > right_limit or cy + height > 1014:
                    continue
                clash = False
                for rx, ry, rw, rh in used:
                    if cx < rx + rw and cx + width > rx and cy < ry + rh and cy + height > ry:
                        clash = True
                        break
                if not clash:
                    chosen = (cx, cy)
                    break
            if chosen is None and contact.selected:
                chosen = (min(bx + 15, right_limit - width), by + 12)
            if chosen is None:
                self._visible(control1, False)
                self._visible(control2, False)
                self.label_boxes.pop(slot, None)
                continue
            used.append((chosen[0], chosen[1], width, height))
            drawn += 1

            self._text(control1, l1, 'small', color, chosen[0] + 2, chosen[1],
                       tracking=0.4, alpha=alpha)
            if l2:
                self._text(control2, l2, 'tiny', color, chosen[0] + 2, chosen[1] + 21,
                           tracking=0.2, alpha=alpha * 0.75)
            else:
                self._visible(control2, False)

            p1 = self._positions.get(id(control1), (chosen[0] + 2, chosen[1]))
            if l2:
                p2 = self._positions.get(id(control2), (p1[0], p1[1] + 21))
            else:
                p2 = p1
            self.label_offsets[slot] = (p1[0] - bx, p1[1] - by, p2[0] - bx, p2[1] - by)
            self.label_boxes[slot] = (chosen[0] - bx, chosen[1] - by, width, height)

    # ---- full contact sheet ----------------------------------------------------------------

    def show_overlay(self, model, now):
        if not self.overlay_open:
            self.overlay_open = True
            for control in self.overlay_controls:
                self._visible(control, True)
            try:
                self.window.setFocusId(self.close_id)
            except Exception:
                pass
        self._update_overlay(model, now)

    def hide_overlay(self):
        for control in self.overlay_controls:
            self._visible(control, False)
        self.overlay_open = False
        try:
            self.window.setFocusId(self.anchor_id)
        except Exception:
            pass

    def _update_overlay(self, model, now):
        palette = self.palette
        contact = model.spotlight()
        if contact is None:
            self.hide_overlay()
            return
        ac = contact.ac
        position = model.spotlight_position()
        total = len(model.order)
        name = radar_core.truncate_text(radar_core.aircraft_name(ac), 18)
        emergency = radar_core.emergency_label(ac)
        self._text(self.ov_name, name, 'mid', palette.alert if emergency else palette.bright,
                   OVERLAY_X + 32, OVERLAY_Y + 58, tracking=1.2)
        kind = []
        if ac.reg:
            kind.append(radar_core.upper_string(ac.reg))
        if ac.type_code:
            kind.append(radar_core.upper_string(ac.type_code))
        if ac.category:
            kind.append('%s %s' % (ac.category, radar_core.category_name(ac.category)))
        if ac.hex:
            kind.append('HEX ' + radar_core.upper_string(ac.hex))
        kind.append(radar_core.source_name(ac))
        self._text(self.ov_kind, '  ·  '.join(kind), 'small', palette.dim,
                   OVERLAY_X + 32, OVERLAY_Y + 100, max_width=900)
        mode = 'PINNED' if model.pinned else 'AUTO'
        spot = ('%d / %d' % (position + 1, total)) if position >= 0 else '-- / --'
        self._text(self.ov_spot, spot + '   ' + mode, 'tiny',
                   palette.bright if model.pinned else palette.dim,
                   OVERLAY_X + OVERLAY_W - 32, OVERLAY_Y + 26, align=2)

        values = self._overlay_values(contact, now)
        for index, value in enumerate(values):
            column, row = index // 14, index % 14
            color = palette.primary
            label = OVERLAY_LABELS[index]
            if label in ('EMERGENCY', 'FLAGS') and value not in ('NONE', '--'):
                color = palette.alert
            self._text(self.ov_values[index], value, 'small', color,
                       OVERLAY_COL_X[column] + 112,
                       OVERLAY_GRID_Y + row * OVERLAY_ROW_H - 3,
                       max_width=330)

    def _overlay_values(self, contact, now):
        ac = contact.ac
        units = self.settings.units

        def rate(has, value):
            if not has:
                return '--'
            if abs(value) < 50.0:
                return 'LEVEL'
            if units == 1:
                return '%+d FPM' % (radar_core._round_half_away(value / 5.0) * 5)
            return '%+.1f M/S' % (value * 0.00508)

        def geom_alt():
            if not ac.has_alt_geom:
                return '--'
            if units == 1:
                return radar_core.fmt_commas(
                    radar_core._round_half_away(ac.alt_geom_ft)) + ' FT'
            return radar_core.fmt_commas(
                radar_core._round_half_away(ac.alt_geom_ft * 0.3048)) + ' M'

        def nav_alt():
            if not ac.has_nav_alt:
                return '--'
            if units == 1:
                return radar_core.fmt_commas(
                    radar_core._round_half_away(ac.nav_alt_ft)) + ' FT'
            return radar_core.fmt_commas(
                radar_core._round_half_away(ac.nav_alt_ft * 0.3048)) + ' M'

        def number(value, has, fmt):
            return (fmt % value) if has else '--'

        seen = ac.seen_pos if ac.has_seen_pos else ac.seen
        seen_pos = ac.seen_pos if ac.has_seen_pos else -1.0
        first = now - contact.first_seen if contact.first_seen > 0 else -1.0
        last = now - contact.last_seen if contact.last_seen > 0 else -1.0
        category = (ac.category + ' ' + radar_core.category_name(ac.category)
                    if ac.category else '--')
        source = radar_core.source_name(ac)
        if ac.type:
            source += ' / ' + radar_core.upper_string(ac.type)

        return [
            # column 1
            ac.flight or '--',
            ac.reg or '--',
            ac.type_code or '--',
            category,
            radar_core.upper_string(ac.hex) or '--',
            ac.squawk or '--',
            source,
            radar_core.flag_text(ac) or 'NONE',
            radar_core.fmt_coord(contact.lat, True),
            radar_core.fmt_coord(contact.lon, False),
            radar_core.fmt_distance(contact.distance_m, units),
            radar_core.fmt_bearing(contact.bearing_deg),
            radar_core.fmt_seen(first),
            radar_core.fmt_seen(last),
            # column 2
            radar_core.fmt_altitude(ac, units),
            geom_alt(),
            radar_core.fmt_speed(ac, units),
            radar_core.fmt_deg(ac.track) if ac.has_track else '--',
            radar_core.fmt_deg(ac.mag_heading) if ac.has_mag_heading else '--',
            radar_core.fmt_deg(ac.true_heading) if ac.has_true_heading else '--',
            ('%d KT' % radar_core._round_half_away(ac.ias_kt)) if ac.has_ias else '--',
            ('%d KT' % radar_core._round_half_away(ac.tas_kt)) if ac.has_tas else '--',
            ('%.2f' % ac.mach) if ac.has_mach else '--',
            rate(ac.has_baro_rate, ac.baro_rate_fpm),
            rate(ac.has_geom_rate, ac.geom_rate_fpm),
            nav_alt(),
            ('%.0f' % ac.nav_qnh) if ac.has_nav_qnh else '--',
            radar_core.fmt_deg(ac.nav_heading) if ac.has_nav_heading else '--',
            # column 3
            radar_core.emergency_label(ac) or 'NONE',
            number(ac.nac_p, ac.has_nac_p, '%.0f'),
            number(ac.nac_v, ac.has_nac_v, '%.0f'),
            number(ac.sil, ac.has_sil, '%.0f'),
            number(ac.nic, ac.has_nic, '%.0f'),
            number(ac.rc_m, ac.has_rc, '%.0f M'),
            str(ac.messages),
            str(ac.version),
            number(ac.rssi, ac.has_rssi, '%.1f'),
            radar_core.fmt_seen(seen),
            radar_core.fmt_seen(seen_pos),
            'YES' if ac.on_ground else 'NO',
            'YES' if ac.mlat else 'NO',
            'YES' if ac.tisb else 'NO',
        ]

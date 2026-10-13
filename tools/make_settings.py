"""Generate resources/settings.xml and the English strings.po from one table.

Run: python3 tools/make_settings.py   (keeps setting ids, labels and string ids in sync)
"""

import os
from xml.sax.saxutils import escape

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screensaver.godseye.map')
ADDON = 'screensaver.godseye.map'

# (category, [settings]); setting = dict(id, type, label, default, ...)
B = lambda sid, label, default, **kw: dict(id=sid, type='boolean', label=label, default=default, **kw)
CATEGORIES = [
    ('Location', [
        dict(id='location_name', type='string', label='Place name shown on screen', default='Home'),
        dict(id='find_location', type='action', label='Find a place by name...',
             data='RunScript(special://home/addons/%s/default.py,find_location)' % ADDON),
        dict(id='lat', type='number', label='Latitude', default='44.9031331'),
        dict(id='lon', type='number', label='Longitude', default='-93.3096136'),
        dict(id='zoom', type='slider', label='Zoom (3 continent, 9 city, 13 streets)',
             default=16, min=2, max=17),
        B('show_home', 'Show home icon at the centre', True),
        dict(id='basemap', type='options', label='Base map', default=1,
             options=['OpenStreetMap', 'Dark', 'Satellite (Esri)', 'Satellite + labels',
                      "NASA satellite image of the day"]),
    ]),
    ('Air & space', [
        B('layer_flights', 'Flights', True),
        B('layer_military', 'Military aircraft', False),
        dict(id='flight_refresh', type='slider', label='Flight refresh (seconds)', default=20, min=10, max=120, step=5),
        B('layer_satellites', 'Satellites overhead', True),
        dict(id='satellite_group', type='options', label='Which satellites', default=1,
             options=['Space stations', '100 brightest', 'GPS', 'Weather satellites', 'Starlink'],
             visible='layer_satellites'),
    ]),
    ('Weather & Earth', [
        B('layer_radar', 'Rain radar (US)', True),
        B('layer_clouds', 'Infrared clouds (shown at zoom 10 and below)', False),
        B('layer_lightning', 'Lightning (Americas)', False),
        dict(id='overlay_opacity', type='slider', label='Weather overlay opacity (%)', default=70, min=30, max=100, step=10),
        B('layer_quakes', 'Earthquakes', True),
        dict(id='quake_period', type='options', label='Earthquakes from', default=0,
             options=['Past day', 'Past week (M2.5+)', 'Past month (M4.5+)'], visible='layer_quakes'),
        dict(id='quake_min_mag', type='options', label='Minimum magnitude', default=1,
             options=['Any', '1.0', '2.5', '4.5'], visible='layer_quakes'),
        B('layer_cyclones', 'Tropical storms & hurricanes', True),
    ]),
    ('Traffic & transit', [
        dict(id='tomtom_key', type='string', label='TomTom API key', default=''),
        B('layer_traffic', 'Traffic flow (needs TomTom key)', True),
        B('layer_incidents', 'Traffic incidents (needs TomTom key)', False),
        dict(id='traffic_refresh', type='slider', label='Traffic refresh (seconds)', default=600, min=300, max=1800, step=60),
        B('layer_rail', 'Rail, subway & tram lines', True),
        B('layer_transit', 'Live transit vehicles (Boston, Austin, Minneapolis, Helsinki, NL, Norway, SE Queensland)', True),
        dict(id='transit_custom_url', type='string', label='Extra GTFS-realtime vehicle positions URL (optional)', default=''),
    ]),
    ('Weather card', [
        B('show_weather', 'Show local weather card', True),
        B('show_moon', 'Show moon phase', True),
        dict(id='units', type='options', label='Units', default=0,
             options=['Fahrenheit, mph', 'Celsius, km/h']),
    ]),
    ('Display', [
        dict(id='look', type='options', label='Sensor look', default=0,
             options=['Off', 'Night vision', 'CRT terminal', 'FLIR white-hot (street map)',
                      'FLIR black-hot (street map)', 'Ironbow thermal (street map)', 'Noir (street map)']),
        B('show_info', 'Show place name, clock and layer counts', True),
        B('show_labels', 'Show labels next to markers', True),
        dict(id='max_markers', type='slider', label='Maximum markers on screen', default=150, min=50, max=300, step=25),
        dict(id='dim', type='slider', label='Dim the map (%)', default=0, min=0, max=80, step=10),
        B('drift', 'Slowly drift the map (protects OLED/plasma screens)', False),
    ]),
]


def visible_dependency(rule):
    """'setting' (a boolean that must be on), ('setting', value) or ('setting', '!', value)."""
    if isinstance(rule, str):
        return ('<dependencies><dependency type="visible" setting="%s">true</dependency></dependencies>' % rule)
    if len(rule) == 3:
        return ('<dependencies><dependency type="visible" setting="%s" operator="!is">%s</dependency>'
                '</dependencies>' % (rule[0], rule[2]))
    return '<dependencies><dependency type="visible" setting="%s">%s</dependency></dependencies>' % rule


def write(root, addon, addon_name, categories, generator='tools/make_settings.py'):
    """Write settings.xml and strings.po for one add-on from a category table."""
    strings = []

    def sid(text):
        if text not in strings:
            strings.append(text)
        return 30100 + strings.index(text)

    out = ['<?xml version="1.0" encoding="utf-8" standalone="yes"?>',
           '<!-- Generated by %s; edit the table there. -->' % generator,
           '<settings version="1">', '  <section id="%s">' % addon]
    for c, (title, settings) in enumerate(categories):
        out.append('    <category id="c%d" label="%d">' % (c, sid(title)))
        out.append('      <group id="1">')
        group = 1
        for s in settings:
            label = sid(s['label'])
            kind = s['type']
            if kind == 'group':  # starts a new labelled group within the category
                if out[-1].startswith('      <group'):  # nothing in the open group yet
                    out.pop()
                else:
                    out.append('      </group>')
                    group += 1
                out.append('      <group id="%d" label="%d">' % (group, label))
                continue
            xtype = {'slider': 'integer', 'options': 'integer', 'multi': 'list[integer]'}.get(kind, kind)
            out.append('        <setting id="%s" type="%s" label="%d">' % (s['id'], xtype, label))
            out.append('          <level>0</level>')
            if kind == 'action':
                out.append('          <data>%s</data>' % escape(s['data']))
                out.append('          <control type="button" format="action"><close>true</close></control>')
            elif kind == 'boolean':
                out.append('          <default>%s</default>' % ('true' if s['default'] else 'false'))
                out.append('          <control type="toggle"/>')
            elif kind == 'string':
                out.append('          <default>%s</default>' % escape(s['default']))
                out.append('          <constraints><allowempty>true</allowempty></constraints>')
                out.append('          <control type="edit" format="string"><heading>%d</heading>%s</control>'
                           % (label, '<hidden>true</hidden>' if s.get('hidden') else ''))
            elif kind == 'time':
                out.append('          <default>%s</default>' % s['default'])
                out.append('          <control type="button" format="time"><heading>%d</heading></control>' % label)
            elif kind == 'addon':
                out.append('          <default>%s</default>' % s['default'])
                out.append('          <constraints><addontype>%s</addontype><allowempty>true</allowempty></constraints>'
                           % s['addontype'])
                out.append('          <control type="button" format="addon"><show more="true" details="true">installed</show>'
                           '</control>')
            elif kind == 'number':
                out.append('          <default>%s</default>' % s['default'])
                out.append('          <control type="edit" format="number"><heading>%d</heading></control>' % label)
            elif kind == 'slider':
                out.append('          <default>%d</default>' % s['default'])
                out.append('          <constraints><minimum>%d</minimum><step>%d</step><maximum>%d</maximum></constraints>'
                           % (s['min'], s.get('step', 1), s['max']))
                out.append('          <control type="slider" format="integer"><popup>false</popup></control>')
            elif kind == 'options':
                out.append('          <default>%d</default>' % s['default'])
                out.append('          <constraints><options>')
                for i, opt in enumerate(s['options']):
                    out.append('            <option label="%d">%d</option>' % (sid(opt), i))
                out.append('          </options></constraints>')
                out.append('          <control type="spinner" format="string"/>')
            elif kind == 'multi':
                out.append('          <default>%s</default>' % ','.join(str(v) for v in s['default']))
                out.append('          <constraints>')
                out.append('            <options>')
                for i, opt in enumerate(s['options']):
                    out.append('              <option label="%d">%d</option>' % (sid(opt), i))
                out.append('            </options>')
                out.append('            <delimiter>,</delimiter>')
                out.append('            <minimumitems>1</minimumitems>')
                out.append('          </constraints>')
                out.append('          <control type="list" format="string"><multiselect>true</multiselect></control>')
            if s.get('visible'):
                out.append('          ' + visible_dependency(s['visible']))
            out.append('        </setting>')
        out.append('      </group>')
        out.append('    </category>')
    out += ['  </section>', '</settings>', '']
    with open(os.path.join(root, 'resources', 'settings.xml'), 'w') as handle:
        handle.write('\n'.join(out))

    po = ['# Kodi Media Center language file', '# Addon Name: %s' % addon_name, '# Addon id: %s' % addon,
          '# Generated by %s' % generator, 'msgid ""', 'msgstr ""',
          '"Content-Type: text/plain; charset=UTF-8\\n"', '"Language: en_GB\\n"', '']
    for i, text in enumerate(strings):
        po += ['msgctxt "#%d"' % (30100 + i), 'msgid "%s"' % text.replace('"', '\\"'), 'msgstr ""', '']
    folder = os.path.join(root, 'resources', 'language', 'resource.language.en_gb')
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(os.path.join(folder, 'strings.po'), 'w') as handle:
        handle.write('\n'.join(po))
    print('settings: %d, strings: %d' % (sum(1 for _c, ss in categories for s in ss if s['type'] != 'group'),
                                         len(strings)))


def main():
    write(ROOT, ADDON, "God's Eye Map", CATEGORIES)


if __name__ == '__main__':
    main()

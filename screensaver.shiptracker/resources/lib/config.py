"""Every setting, string, map request and colour in one table. No Kodi imports.

tools/make_settings_shiptracker.py turns CATEGORIES and STRINGS into
resources/settings.xml and the English strings.po. The map and AIS geometry lives here too,
so the tests can check it without a screen or a network.
"""

import hashlib
import math
from urllib.parse import urlencode

ADDON_ID = 'screensaver.shiptracker'
ADDON_NAME = 'Ship Tracker Screensaver'
VERSION = '0.3.0'

# aisstream.io's public AIS stream. The free key is tied to an account; the user pastes it into
# the add-on settings. It is never bundled.
STREAM_HOST = 'stream.aisstream.io'
STREAM_PORT = 443
STREAM_PATH = '/v0/stream'

# Ten ready-made areas. Each one is a setting group: it can be renamed, its four edges can be
# changed, and it can be switched off. Enabled areas share one AIS subscription and the screen
# rotates between them every area_minutes minutes.
AREAS = (
    {'name': 'Lake Superior', 'box': (46.3, -92.3, 49.1, -84.2)},
    {'name': 'Strait of Hormuz', 'box': (25.6, 55.6, 27.0, 57.0)},
    {'name': 'San Diego', 'box': (32.5, -117.4, 32.9, -116.9)},
    {'name': 'San Francisco Bay', 'box': (37.55, -122.6, 38.2, -121.7)},
    {'name': 'Hawaii', 'box': (21.0, -158.3, 21.7, -157.5)},
    {'name': 'Singapore Strait', 'box': (1.0, 103.4, 1.45, 104.3)},
    {'name': 'Rotterdam', 'box': (51.8, 3.8, 52.1, 4.6)},
    {'name': 'Panama Canal', 'box': (8.7, -80.0, 9.6, -79.3)},
    {'name': 'Suez Canal', 'box': (29.7, 32.2, 31.4, 32.7)},
    {'name': 'New York Harbor', 'box': (40.4, -74.3, 40.95, -73.6)},
)
DEFAULT_BBOX = AREAS[0]['box']

POSITION_TYPES = ('PositionReport', 'StandardClassBPositionReport',
                  'ExtendedClassBPositionReport')
STATIC_TYPES = ('ShipStaticData', 'StaticDataReport')

# EOX renders the Sentinel-2 cloudless mosaic on demand, so the map is exactly the tracked box
# (padded to the screen's aspect ratio) rather than a crop from a bundled world image. No key;
# the mosaic is CC BY-NC-SA 4.0 and needs the attribution shown on screen.
MAP_SERVICE = 'https://tiles.maps.eox.at/wms'
MAP_LAYER = 's2cloudless-2025'
MAP_WIDTH, MAP_HEIGHT = 1400, 1080
# Sentinel-2 cloudless is 10 m per pixel, so a window at least 0.05 degrees tall (about 5.5 km)
# is still sharp at 1080p. Wider boxes are shown as they are; tighter boxes get surrounding
# water so the image is not blown up into a blocky mess.
MIN_MAP_SPAN = 0.05

USER_AGENT = '%s/%s (Kodi screensaver; +https://github.com/P-Hoep/kodi)' % (ADDON_ID, VERSION)

WIKIDATA_API = 'https://www.wikidata.org/w/api.php'
COMMONS_API = 'https://commons.wikimedia.org/w/api.php'
COMMONS_FILEPATH = 'https://commons.wikimedia.org/wiki/Special:FilePath/'

HTTP_TIMEOUT = 15
LOOKUP_GAP = 0.5                 # seconds between Wikimedia requests (be polite)
PROFILE_TTL = 30 * 24 * 3600     # a found profile is reused for a month
NEGATIVE_TTL = 7 * 24 * 3600     # "no match" is retried after a week
RETRY_SECONDS = 60
MAX_RETRY_SECONDS = 600

NAV_STATUS = {
    0: 'Under way using engine', 1: 'At anchor', 2: 'Not under command',
    3: 'Restricted manoeuvrability', 4: 'Constrained by draught', 5: 'Moored', 6: 'Aground',
    7: 'Engaged in fishing', 8: 'Under way sailing', 9: 'Reserved',
    10: 'Reserved', 11: 'Towing astern',
    12: 'Pushing ahead or towing alongside', 13: 'Reserved', 14: 'AIS-SART active',
    15: 'Undefined',
}

# The first three digits of an MMSI are the Maritime Identification Digits, which identify the
# flag state. Only the digits a vessel can carry are listed; an unknown MID simply shows no flag.
MID_COUNTRIES = {
    201: 'Albania', 205: 'Belgium', 209: 'Cyprus', 210: 'Cyprus', 211: 'Germany',
    212: 'Cyprus', 213: 'Georgia', 218: 'Germany', 219: 'Denmark', 220: 'Denmark',
    224: 'Spain', 225: 'Spain', 226: 'France', 227: 'France', 228: 'France',
    230: 'Finland', 231: 'Faroe Islands', 232: 'United Kingdom', 233: 'United Kingdom',
    234: 'United Kingdom', 235: 'United Kingdom', 236: 'Gibraltar', 237: 'Greece',
    238: 'Croatia', 239: 'Greece', 240: 'Greece', 241: 'Greece', 242: 'Morocco',
    243: 'Hungary', 244: 'Netherlands', 245: 'Netherlands', 246: 'Netherlands',
    247: 'Italy', 248: 'Malta', 249: 'Malta', 250: 'Ireland', 251: 'Iceland',
    252: 'Liechtenstein', 253: 'Luxembourg', 254: 'Monaco', 255: 'Portugal',
    256: 'Malta', 257: 'Norway', 258: 'Norway', 259: 'Norway', 261: 'Poland',
    262: 'Montenegro', 263: 'Portugal', 264: 'Romania', 265: 'Sweden', 266: 'Sweden',
    267: 'Slovakia', 268: 'San Marino', 269: 'Switzerland', 270: 'Czechia',
    271: 'Türkiye', 272: 'Ukraine', 273: 'Russia', 274: 'North Macedonia',
    275: 'Latvia', 276: 'Estonia', 277: 'Lithuania', 278: 'Slovenia', 279: 'Serbia',
    301: 'Anguilla', 303: 'United States', 304: 'Antigua and Barbuda',
    305: 'Antigua and Barbuda', 306: 'Curaçao', 307: 'Aruba', 308: 'Bahamas',
    309: 'Bahamas', 310: 'Bermuda', 311: 'Bahamas', 312: 'Belize', 314: 'Barbados',
    316: 'Canada', 319: 'Cayman Islands', 321: 'Costa Rica', 323: 'Cuba',
    325: 'Dominica', 327: 'Dominican Republic', 329: 'Guadeloupe', 330: 'Grenada',
    331: 'Greenland', 332: 'Guatemala', 334: 'Honduras', 336: 'Haiti',
    338: 'United States', 339: 'Jamaica', 341: 'Saint Kitts and Nevis',
    343: 'Saint Lucia', 345: 'Mexico', 347: 'Martinique', 348: 'Montserrat',
    350: 'Nicaragua', 351: 'Panama', 352: 'Panama', 353: 'Panama', 354: 'Panama',
    355: 'Panama', 356: 'Panama', 357: 'Panama', 358: 'Puerto Rico',
    359: 'El Salvador', 361: 'Saint Pierre and Miquelon', 362: 'Trinidad and Tobago',
    364: 'Turks and Caicos Islands', 366: 'United States', 367: 'United States',
    368: 'United States', 369: 'United States', 370: 'Panama', 371: 'Panama',
    372: 'Panama', 373: 'Panama', 374: 'Panama', 375: 'Saint Vincent and the Grenadines',
    376: 'Saint Vincent and the Grenadines', 377: 'Saint Vincent and the Grenadines',
    378: 'British Virgin Islands', 379: 'United States Virgin Islands',
    401: 'Afghanistan', 403: 'Saudi Arabia', 405: 'Bangladesh', 408: 'Bahrain',
    410: 'Bhutan', 412: 'China', 413: 'China', 414: 'China', 416: 'Taiwan',
    417: 'Sri Lanka', 419: 'India', 422: 'Iran', 423: 'Azerbaijan', 425: 'Iraq',
    428: 'Israel', 431: 'Japan', 432: 'Japan', 434: 'Turkmenistan',
    436: 'Kazakhstan', 437: 'Uzbekistan', 438: 'Jordan', 440: 'South Korea',
    441: 'South Korea', 443: 'Palestine', 445: 'North Korea', 447: 'Kuwait',
    450: 'Lebanon', 451: 'Kyrgyzstan', 453: 'Macao', 455: 'Maldives',
    457: 'Mongolia', 459: 'Nepal', 461: 'Oman', 463: 'Pakistan', 466: 'Qatar',
    468: 'Syria', 470: 'United Arab Emirates', 472: 'Tajikistan', 473: 'Yemen',
    475: 'Yemen', 477: 'Hong Kong', 478: 'Bosnia and Herzegovina',
    501: 'Adélie Land', 503: 'Australia', 506: 'Myanmar', 508: 'Brunei',
    510: 'Micronesia', 511: 'Palau', 512: 'New Zealand', 514: 'Cambodia',
    515: 'Cambodia', 516: 'Christmas Island', 518: 'Cook Islands', 520: 'Fiji',
    523: 'Cocos (Keeling) Islands', 525: 'Indonesia', 529: 'Kiribati', 531: 'Laos',
    533: 'Malaysia', 536: 'Northern Mariana Islands', 538: 'Marshall Islands',
    540: 'New Caledonia', 542: 'Niue', 544: 'Nauru', 546: 'French Polynesia',
    548: 'Philippines', 553: 'Papua New Guinea', 555: 'Pitcairn Islands',
    557: 'Solomon Islands', 559: 'American Samoa', 561: 'Samoa', 563: 'Singapore',
    564: 'Singapore', 565: 'Singapore', 566: 'Singapore', 567: 'Thailand',
    570: 'Tonga', 572: 'Tuvalu', 574: 'Vietnam', 576: 'Vanuatu', 577: 'Vanuatu',
    578: 'Wallis and Futuna', 601: 'South Africa', 603: 'Angola', 605: 'Algeria',
    607: 'Saint Paul and Amsterdam Islands', 608: 'Ascension Island',
    609: 'Burundi', 610: 'Benin', 611: 'Botswana', 612: 'Central African Republic',
    613: 'Cameroon', 615: 'Republic of the Congo', 616: 'Comoros',
    617: 'Cape Verde', 618: 'Crozet Islands', 619: "Côte d'Ivoire", 620: 'Comoros',
    621: 'Djibouti', 622: 'Egypt', 624: 'Ethiopia', 625: 'Eritrea', 626: 'Gabon',
    627: 'Ghana', 629: 'Gambia', 630: 'Guinea-Bissau', 631: 'Equatorial Guinea',
    632: 'Guinea', 633: 'Burkina Faso', 634: 'Kenya', 635: 'Kerguelen Islands',
    636: 'Liberia', 637: 'Liberia', 638: 'South Sudan', 642: 'Libya',
    644: 'Lesotho', 645: 'Mauritius', 647: 'Madagascar', 649: 'Mali',
    650: 'Mozambique', 654: 'Mauritania', 655: 'Malawi', 656: 'Niger',
    657: 'Nigeria', 659: 'Namibia', 660: 'Réunion', 661: 'Rwanda', 662: 'Sudan',
    663: 'Senegal', 664: 'Seychelles', 665: 'Saint Helena', 666: 'Somalia',
    667: 'Sierra Leone', 668: 'São Tomé and Príncipe', 669: 'Eswatini', 670: 'Chad',
    671: 'Togo', 672: 'Tunisia', 674: 'Tanzania', 675: 'Uganda',
    676: 'Democratic Republic of the Congo', 677: 'Tanzania', 678: 'Zambia',
    679: 'Zimbabwe', 701: 'Argentina', 710: 'Brazil', 720: 'Bolivia', 725: 'Chile',
    730: 'Colombia', 735: 'Ecuador', 740: 'Falkland Islands', 745: 'French Guiana',
    750: 'Guyana', 755: 'Paraguay', 760: 'Peru', 765: 'Suriname', 770: 'Uruguay',
    775: 'Venezuela',
}


def B(sid, label, default, **kw):
    return dict(id=sid, type='boolean', label=label, default=default, **kw)


def S(sid, label, default, lo, hi, step=1, **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step,
                **kw)


def A(sid, label, command):
    """A settings button that runs default.py with this argument (see ui.clear_cache)."""
    return dict(id=sid, type='action', label=label,
                data='RunScript(special://home/addons/%s/default.py,%s)' % (ADDON_ID, command))


def area_settings(index):
    """The six settings behind one area: a switch, a name and the four edges."""
    number = index + 1
    area = AREAS[index]
    prefix = 'area%d_' % number
    settings = [
        B(prefix + 'enabled', 'Enabled', True),
        dict(id=prefix + 'name', type='string', label='Name shown on screen',
             default=area['name']),
    ]
    labels = ('South latitude', 'West longitude', 'North latitude', 'East longitude')
    for key, label, value in zip(('south_lat', 'west_lon', 'north_lat', 'east_lon'),
                                 labels, area['box']):
        settings.append(dict(id=prefix + key, type='number', label=label,
                             default='%g' % value))
    return settings


CATEGORIES = (
    [('AIS stream', [
        dict(id='api_key', type='string', label='aisstream.io API key (free from aisstream.io)',
             default=''),
    ]),
     ('Rotation', [
         S('area_minutes', 'Minutes per area before switching', 5, 1, 60),
     ])]
    + [('Area %d · %s' % (index + 1, area['name']), area_settings(index))
       for index, area in enumerate(AREAS)]
    + [('Display', [
        S('ship_timeout', 'Keep a ship listed for (minutes)', 15, 2, 120),
        S('photo_seconds', 'Seconds per ship photo', 8, 3, 30),
        S('map_brightness', 'Lighten the map (percent)', 8, 0, 30, step=2),
        B('show_clock', 'Show a clock', True),
    ]),
       ('Data', [
        B('enrich', 'Look up ship details and photos on Wikipedia', True),
        A('clear_cache', 'Clear cached ships, map and photos', 'clear_cache'),
        B('debug', 'Debug logging', False),
    ])]
)

# On-screen text. Settings labels start at 30100; these start at 32000 so the generator can
# append them without renumbering the settings.
STRINGS = {
    32000: 'Connecting to the AIS stream…',
    32001: 'Add your aisstream.io API key in the add-on settings',
    32002: 'Listening for ships…',
    32003: 'No ships in this area right now',
    32004: 'AIS connection lost — retrying',
    32005: 'Showing last known positions',
    32006: 'AIS live',
    32007: '%d vessel',
    32008: '%d vessels',
    32009: 'VESSELS · %d–%d OF %d',
    32010: 'No ship photos yet',
    32011: 'Ship photos: Wikimedia Commons',
    32012: 'Cached data cleared',
    32013: 'No detailed information yet',
    32014: 'Map: Sentinel-2 cloudless – https://s2maps.eu by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2025)',
    32015: 'Waiting for a position…',
    32016: 'Last position %s ago',
    32017: 'No map image available',
    32018: 'Loading ship photos…',
    32019: 'Wikimedia',
    32020: 'VESSELS · 0',
    32021: 'No AIS key',
    32022: 'No areas enabled in the settings',
    32023: 'Loading map…',
    32024: 'No areas enabled',
    32025: 'AIS: aisstream.io',
}


def all_settings():
    for _title, settings in CATEGORIES:
        for setting in settings:
            if setting['type'] != 'action':
                yield setting


def defaults():
    return dict((s['id'], s['default']) for s in all_settings())


def read(getters):
    """Settings as a dict.
    getters: {'boolean', 'integer', 'number', 'string'} -> f(setting id)."""
    out = {}
    for s in all_settings():
        kind = s['type']
        try:
            if kind == 'boolean':
                value = bool(getters['boolean'](s['id']))
            elif kind == 'slider':
                value = int(getters['integer'](s['id']))
                value = max(s['min'], min(s['max'], value))
            elif kind == 'options':
                value = int(getters['integer'](s['id']))
            elif kind == 'number':
                # Kodi refuses to read a 'number' setting as a string: getSettingString
                # logs "Invalid setting type" and returns ''. That made every bounding
                # box silently fall back to its shipped default.
                value = float(getters['number'](s['id']))
            else:
                value = getters['string'](s['id'])
        except Exception:
            value = s['default']
        if kind == 'string' and value is None:
            value = s['default']
        out[s['id']] = value
    return out


# ---------------------------------------------------------------------------------------------
# The tracked box
# ---------------------------------------------------------------------------------------------
def area_key(index, key):
    return 'area%d_%s' % (index + 1, key)


def area_enabled(settings, index):
    return bool(settings.get(area_key(index, 'enabled'), True))


def area_name(settings, index):
    name = (settings.get(area_key(index, 'name')) or '').strip()
    return name or AREAS[index]['name']


def area_box(settings, index):
    """(south, west, north, east) for one area, or that area's shipped box when it is invalid.

    An out-of-range, upside-down or empty box cannot be sent to aisstream, so the whole box
    falls back to the area's default rather than silently tracking a sliver.
    """
    keys = ('south_lat', 'west_lon', 'north_lat', 'east_lon')
    try:
        south, west, north, east = (float(settings.get(area_key(index, key))) for key in keys)
    except (TypeError, ValueError):
        return AREAS[index]['box']
    if not (-90.0 <= south < north <= 90.0 and -180.0 <= west < east <= 180.0):
        return AREAS[index]['box']
    return (south, west, north, east)


def enabled_areas(settings):
    """The areas the screen rotates through, in settings order, with their current names."""
    areas = []
    for index in range(len(AREAS)):
        if area_enabled(settings, index):
            areas.append({'index': index, 'name': area_name(settings, index),
                          'box': area_box(settings, index)})
    return areas


def in_box(ship, box):
    """Whether a ship's last position is inside a tracked box."""
    try:
        latitude, longitude = float(ship['lat']), float(ship['lon'])
    except (KeyError, TypeError, ValueError):
        return False
    south, west, north, east = box
    return south <= latitude <= north and west <= longitude <= east


def format_lat(lat):
    return '%.2f°%s' % (abs(lat), 'N' if lat >= 0 else 'S')


def format_lon(lon):
    return '%.2f°%s' % (abs(lon), 'E' if lon >= 0 else 'W')


def _range_label(low, high, positive, negative, formatter):
    """One axis, sharing the hemisphere when both ends are on the same side of the equator.

    '46.30–49.10°N' fits the panel; '46.30°N – 49.10°N' does not. A box that crosses the
    equator or the prime meridian names each end separately instead.
    """
    if low >= 0 and high >= 0:
        return '%.2f–%.2f°%s' % (low, high, positive)
    if low <= 0 and high <= 0:
        return '%.2f–%.2f°%s' % (abs(low), abs(high), negative)
    return '%s–%s' % (formatter(low), formatter(high))


def box_label(box):
    south, west, north, east = box
    return '%s · %s' % (_range_label(south, north, 'N', 'S', format_lat),
                        _range_label(west, east, 'E', 'W', format_lon))


# ---------------------------------------------------------------------------------------------
# Map window and projection
# ---------------------------------------------------------------------------------------------
def map_bounds(south, west, north, east, width, height):
    """(left, bottom, right, top) for a plate carree image that fills width x height.

    The requested box is centred and then widened or heightened as needed, with longitude
    scaled by 1/cos(mid latitude), so one degree of latitude and one of longitude occupy the
    same distance on screen and the satellite image is not stretched. A box smaller than
    MIN_MAP_SPAN is shown with surrounding water, so the image stays sharp at the mosaic's
    native resolution. The original box always stays inside the returned one; near the edge of
    the world the window is slid inwards instead.
    """
    lat_span = max(MIN_MAP_SPAN, float(north) - float(south))
    lon_span = max(0.0001, float(east) - float(west))
    mid_lat = (float(south) + float(north)) / 2.0
    cos_lat = max(0.02, math.cos(math.radians(mid_lat)))
    aspect = float(width) / max(1.0, float(height))
    ground_width = lon_span * cos_lat
    if ground_width / lat_span > aspect:
        new_lat = ground_width / aspect
        new_lon = lon_span
    else:
        new_lon = lat_span * aspect / cos_lat
        new_lat = lat_span
    new_lat = min(180.0, new_lat)
    new_lon = min(360.0, new_lon)
    centre_lat = (float(south) + float(north)) / 2.0
    centre_lon = (float(west) + float(east)) / 2.0
    bottom, top = centre_lat - new_lat / 2.0, centre_lat + new_lat / 2.0
    if bottom < -90.0:
        top += -90.0 - bottom
        bottom = -90.0
    if top > 90.0:
        bottom -= top - 90.0
        top = 90.0
    left, right = centre_lon - new_lon / 2.0, centre_lon + new_lon / 2.0
    if left < -180.0:
        right += -180.0 - left
        left = -180.0
    if right > 180.0:
        left -= right - 180.0
        right = 180.0
    return (left, bottom, right, top)


def project(lat, lon, bounds, width, height):
    """Pixel position of a point inside a plate carree window. May fall outside the image."""
    left, bottom, right, top = bounds
    x = (float(lon) - left) / (right - left) * width
    y = (top - float(lat)) / (top - bottom) * height
    return x, y


def map_url(bounds, width=MAP_WIDTH, height=MAP_HEIGHT):
    left, bottom, right, top = bounds
    query = [('SERVICE', 'WMS'), ('REQUEST', 'GetMap'), ('VERSION', '1.1.1'),
             ('SRS', 'EPSG:4326'), ('FORMAT', 'image/jpeg'), ('LAYERS', MAP_LAYER),
             ('WIDTH', int(width)), ('HEIGHT', int(height)),
             ('BBOX', '%.4f,%.4f,%.4f,%.4f' % (left, bottom, right, top))]
    return MAP_SERVICE + '?' + urlencode(query)


def map_cache_name(bounds, width, height):
    return 'map_%s.jpg' % hashlib.sha1(
        map_url(bounds, width, height).encode('utf-8')).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------
# AIS helpers
# ---------------------------------------------------------------------------------------------
def ship_type_text(code):
    if not code:
        return None
    try:
        value = int(code)
    except (TypeError, ValueError):
        return None
    exact = {30: 'Fishing', 31: 'Towing', 32: 'Towing (large)', 33: 'Dredging',
             34: 'Diving operations', 35: 'Military operations', 36: 'Sailing',
             37: 'Pleasure craft', 50: 'Pilot vessel', 51: 'Search and rescue',
             52: 'Tug', 53: 'Port tender', 54: 'Anti-pollution',
             55: 'Law enforcement', 58: 'Medical transport', 59: 'Non-combatant'}
    if value in exact:
        return exact[value]
    ranges = [(20, 29, 'Wing in ground'), (40, 49, 'High-speed craft'),
              (60, 69, 'Passenger'), (70, 79, 'Cargo'), (80, 89, 'Tanker'),
              (90, 99, 'Other')]
    for low, high, text in ranges:
        if low <= value <= high:
            return text
    return 'Type %d' % value


def nav_status_text(code):
    try:
        return NAV_STATUS.get(int(code))
    except (TypeError, ValueError):
        return None


def mid_country(mmsi):
    """Flag state from the first three digits of an MMSI, or None when it is not a vessel."""
    try:
        digits = str(int(mmsi))
    except (TypeError, ValueError):
        return None
    if len(digits) != 9:
        return None
    return MID_COUNTRIES.get(int(digits[:3]))


MARKER_COLOURS = {
    'cargo': 'FF8ECAE6',
    'tanker': 'FFFFB703',
    'passenger': 'FFFF8FAB',
    'tug': 'FFB5E48C',
    'fishing': 'FFF4A261',
    'pleasure': 'FFE9C46A',
    'high-speed': 'FFB388EB',
    'military': 'FFBBBBBB',
    'other': 'FFFFFFFF',
}


def marker_group(ship_type):
    text = ship_type_text(ship_type)
    if text == 'Cargo':
        return 'cargo'
    if text == 'Tanker':
        return 'tanker'
    if text == 'Passenger':
        return 'passenger'
    if text in ('Tug', 'Towing', 'Towing (large)'):
        return 'tug'
    if text == 'Fishing':
        return 'fishing'
    if text in ('Sailing', 'Pleasure craft'):
        return 'pleasure'
    if text == 'High-speed craft':
        return 'high-speed'
    if text == 'Military operations':
        return 'military'
    return 'other'


def marker_colour(ship_type):
    return MARKER_COLOURS.get(marker_group(ship_type), MARKER_COLOURS['other'])


def heading_index(course):
    """The 16-way icon nearest a course in degrees (0 = pointing up)."""
    try:
        value = float(course) % 360.0
    except (TypeError, ValueError):
        return 0
    return int(round(value / 22.5)) % 16


def subscription(api_key, boxes):
    """One aisstream subscription covering every enabled area."""
    bounding_boxes = []
    for box in boxes:
        south, west, north, east = box
        bounding_boxes.append([[south, west], [north, east]])
    return {
        'APIKey': api_key,
        'BoundingBoxes': bounding_boxes,
        'FilterMessageTypes': list(POSITION_TYPES + STATIC_TYPES),
    }


def area_minutes(settings):
    return max(1, min(60, int(settings.get('area_minutes', 5))))


def area_seconds(settings):
    return area_minutes(settings) * 60


def ship_timeout_seconds(settings):
    return max(2, min(120, int(settings.get('ship_timeout', 15)))) * 60


def photo_seconds(settings):
    return max(3, min(30, int(settings.get('photo_seconds', 8))))


def map_brightness(settings):
    return max(0, min(30, int(settings.get('map_brightness', 8))))


def enrich_enabled(settings):
    return bool(settings.get('enrich', True))


def debug_enabled(settings):
    return bool(settings.get('debug', False))

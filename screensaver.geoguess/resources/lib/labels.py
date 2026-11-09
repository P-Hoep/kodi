"""Turning a dataset row into the name shown on screen. No Kodi imports.

The dataset's address field is a place name followed by the country, for example
"106 109, 1315 Velike Lašče, Slovenia". The card also documents a coordinate suffix
("Jarše Slovenia_46.1069942_14.9378597"); the live rows no longer carry it, but it is stripped
when present. Addresses use the country's own spelling often enough (Slovensko, Australien,
Corée du Sud) that the English name is only appended when none of the known spellings is already
at the end.
"""

import re

# The 55 countries in the dataset (sampled across the whole split).
COUNTRY_NAMES = {
    'AD': 'Andorra',
    'AE': 'United Arab Emirates',
    'AR': 'Argentina',
    'AU': 'Australia',
    'BD': 'Bangladesh',
    'BE': 'Belgium',
    'BG': 'Bulgaria',
    'BR': 'Brazil',
    'BT': 'Bhutan',
    'BW': 'Botswana',
    'CA': 'Canada',
    'CH': 'Switzerland',
    'CL': 'Chile',
    'CO': 'Colombia',
    'CZ': 'Czech Republic',
    'DE': 'Germany',
    'DK': 'Denmark',
    'EE': 'Estonia',
    'ES': 'Spain',
    'FI': 'Finland',
    'FR': 'France',
    'GB': 'United Kingdom',
    'GR': 'Greece',
    'HK': 'Hong Kong',
    'HR': 'Croatia',
    'HU': 'Hungary',
    'ID': 'Indonesia',
    'IE': 'Ireland',
    'IL': 'Israel',
    'IS': 'Iceland',
    'IT': 'Italy',
    'JP': 'Japan',
    'KH': 'Cambodia',
    'KR': 'South Korea',
    'LT': 'Lithuania',
    'LV': 'Latvia',
    'MX': 'Mexico',
    'MY': 'Malaysia',
    'NL': 'Netherlands',
    'NO': 'Norway',
    'NZ': 'New Zealand',
    'PE': 'Peru',
    'PL': 'Poland',
    'PT': 'Portugal',
    'RO': 'Romania',
    'RU': 'Russia',
    'SE': 'Sweden',
    'SG': 'Singapore',
    'SI': 'Slovenia',
    'SK': 'Slovakia',
    'TH': 'Thailand',
    'TW': 'Taiwan',
    'UA': 'Ukraine',
    'US': 'United States',
    'ZA': 'South Africa',
}

# Other spellings of the same country, seen in the address column, so the English name is not
# repeated after it. Only used to recognise a trailing country name, never displayed.
COUNTRY_ALIASES = {
    'AR': ('Argentinien', 'Argentine'),
    'AU': ('Australien', 'Australie'),
    'BD': ('Bangladesch',),
    'BR': ('Brazylia', 'Brasilien', 'Brésil'),
    'CA': ('Kanada',),
    'CH': ('Schweiz', 'Suisse', 'Svizzera'),
    'CL': ('Chili',),
    'CO': ('Kolumbia', 'Colombie'),
    'CZ': ('Česko', 'Tschechien', 'Czechia'),
    'DE': ('Deutschland', 'Allemagne', 'Niemcy', 'Germania'),
    'DK': ('Danmark', 'Danemark', 'Denemarken'),
    'ES': ('España', 'Espagne', 'Hiszpania', 'Spagna', 'Spanien'),
    'FR': ('Frankreich', 'Francja', 'Francia'),
    'GB': ('UK', 'U.K.', 'Great Britain', 'England', 'Scotland', 'Wales', 'Northern Ireland'),
    'GR': ('Grekland', 'Griechenland', 'Grækenland', 'Grecia', 'Grèce'),
    'HK': ('Гонконг',),
    'HR': ('Kroatien', 'Croatie', 'Chorwacja'),
    'HU': ('Magyarország', 'Ungarn', 'Hongrie'),
    'IE': ('Irlandia', 'Irlande', 'Irland'),
    'IS': ('Island', 'Islande', 'Islandia'),
    'IT': ('Italia', 'Italie', 'Italien', 'איטליה'),
    'JP': ('Nhật Bản', '日本', 'Japon'),
    'KH': ('Cambodgia', 'Kambodscha', 'Cambodge'),
    'KR': ('Corée du Sud', 'Südkorea', 'Corea del Sur', 'Korea'),
    'LT': ('Litwa', 'Lituanie'),
    'LV': ('Łotwa', 'Lettonie'),
    'MX': ('Mexiko', 'Mexique', 'México'),
    'MY': ('Malaisie', 'Малайзия'),
    'NL': ('Nederland', 'Pays-Bas', 'Niederlande', 'Holland'),
    'NO': ('Norge', 'Norvège', 'Norwegen'),
    'NZ': ('Neuseeland', 'Nouvelle-Zélande'),
    'PE': ('Перу', 'Pérou'),
    'PL': ('Polska', 'Pologne', 'Polen'),
    'PT': ('Portugalia',),
    'RO': ('Rumunia', 'Rumänien', 'Roumanie'),
    'RU': ('Россия', 'Russie', 'Russland'),
    'SE': ('Sverige', 'Suède', 'Schweden'),
    'SI': ('Słowenia', 'Slowenien', 'Slovenija', 'Słowenii'),
    'SK': ('Slovensko', 'Slowakei', 'Slovaquie'),
    'TW': ('台灣',),
    'UA': ('Україна',),
    'US': ('USA', 'U.S.A.', 'United States of America', 'Vereinigte Staaten', 'États-Unis'),
    'ZA': ('Südafrika', 'Afrique du Sud'),
}

COORD_SUFFIX = re.compile(r'_-?\d+(?:\.\d+)?_-?\d+(?:\.\d+)?\s*$')
SPACES = re.compile(r'\s+')


def clean_address(address):
    """Strip the coordinate suffix the dataset card documents and tidy whitespace."""
    text = (address or '').strip()
    text = COORD_SUFFIX.sub('', text).strip(' ,')
    return SPACES.sub(' ', text)


def country_name(code):
    return COUNTRY_NAMES.get((code or '').upper(), '')


def _names(code):
    code = (code or '').upper()
    name = COUNTRY_NAMES.get(code)
    extra = COUNTRY_ALIASES.get(code, ())
    return ([name] if name else []) + list(extra)


def ends_with_country(text, code):
    """True when the place already ends in the country's name or a known spelling of it.

    A word boundary is required, so a country ending in "us" (Cyprus) is not mistaken for the
    abbreviation "US".
    """
    for name in _names(code):
        if re.search(r'(?:^|[\s,])' + re.escape(name) + r'$', text, re.IGNORECASE):
            return True
    return False


def display_label(address, code, show_country=True):
    """The line shown at the bottom of the screen.

    show_country is the setting; when it is off the dataset's address is shown as it is. When it
    is on, the English country name is appended unless the address already names the country, and
    the country name alone is used when there is no address at all.
    """
    place = clean_address(address)
    name = country_name(code)
    code = (code or '').upper()
    if not show_country:
        return place or name or code
    if not place:
        return name or code
    if name and not ends_with_country(place, code):
        return '%s, %s' % (place, name)
    return place


def map_caption(address, code):
    """The line under the answer map: the English country name.

    An unknown code falls back to the place name, so the caption still answers the guess.
    """
    return country_name(code) or clean_address(address) or (code or '').upper()

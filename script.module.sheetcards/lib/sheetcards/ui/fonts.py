"""Font size by text length. The window has one text control per bucket (fonts come from the
active skin's Font.xml; add-ons cannot ship fonts) and shows the one named by sc.qsize.

Estuary names, checked against its Font.xml (Kodi 21): font60 60 px, font45 45 px,
font37 37 px, font27 27 px. A skin without one of these falls back to its default font.
"""

BUCKETS = (('xl', 40), ('l', 90), ('m', 180))
FONTS = {'xl': 'font60', 'l': 'font45', 'm': 'font37', 's': 'font27'}
OPTION_FONT = 'font27'
FALLBACK = 'font13'


def bucket(text):
    n = len(text or '')
    for name, limit in BUCKETS:
        if n <= limit:
            return name
    return 's'

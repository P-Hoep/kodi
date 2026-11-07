"""Tile styles (spec 2.1a). A style changes only the visual treatment; layouts, animations and
content are shared. Each definition is read twice: by tools/make_rsslivetiles_skin.py (which
textures and insets go into the XML; one window file per style) and at run time (colours).

  inset         px trimmed from every side of the tile's visuals (Modern: 2 -> 14 px gutters)
  radius        corner radius of the tile textures (0 = square)
  scrim         'gradient' (bottom fade under the headline) or 'panel' (translucent "acrylic" bar)
  border        2 px accent border around every tile
  image_inset   the picture sits this far inside the tile (Outline)
"""

from .. import theme

STYLES = {
    'classic': {'name': 'Classic', 'inset': 0, 'radius': 0, 'scrim': 'gradient', 'border': False, 'image_inset': 0},
    'modern': {'name': 'Modern', 'inset': 2, 'radius': 8, 'scrim': 'panel', 'border': False, 'image_inset': 0},
    'outline': {'name': 'Outline', 'inset': 0, 'radius': 0, 'scrim': 'gradient', 'border': True, 'image_inset': 8},
}
ORDER = ('classic', 'modern', 'outline')


def window_xml(style):
    return 'rsslivetiles-%s.xml' % (style if style in STYLES else 'classic')


def colours(style, tile_hex, palette):
    """Colours for one tile face.
      bg     the tile fill        fg    headline      fg2   labels and summary
      edge   border (Outline)     focus focus frame   panel scrim / acrylic tint
    """
    white = 'FFFFFFFF'
    if style == 'outline':
        return {'bg': palette['tile'], 'fg': theme.argb(tile_hex), 'fg2': palette['text2'],
                'body': palette['text'], 'edge': theme.argb(tile_hex), 'focus': palette['text'],
                'panel': palette['scrim']}
    panel = palette['scrim']
    if style == 'modern':
        panel = ('CC' if palette['name'] == 'night' else 'B3') + theme.shade(tile_hex, -0.55)
    return {'bg': theme.argb(tile_hex), 'fg': white, 'fg2': 'D9FFFFFF', 'body': 'F2FFFFFF', 'edge': '00000000',
            'focus': white, 'panel': panel}

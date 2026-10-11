"""Land-cover classes of the bundled world map (media/world/landclass.png). No Kodi imports.

tools/make_world_data.py derives them from NASA Blue Marble colours, an elevation model, a
land/water mask and the city-lights image. They drive the geographic ASCII mode and the
flat-colour Atlas base maps."""

(DEEP, OCEAN, SHALLOW, LAKE, SEA_ICE, ICE, TUNDRA, DESERT, PLAINS, GRASS, FOREST, JUNGLE,
 HILLS, MOUNTAINS, PEAKS, URBAN) = range(16)
COUNT = 16
WATER = (DEEP, OCEAN, SHALLOW, LAKE)

NAMES = ['deep ocean', 'ocean', 'shallow sea', 'lake', 'sea ice', 'ice', 'tundra', 'desert',
         'plains', 'grassland', 'forest', 'jungle', 'hills', 'mountains', 'peaks', 'urban']

# Colours for the build preview and the "Atlas" base map.
PREVIEW = [
    (16, 38, 82), (24, 58, 112), (44, 96, 148), (56, 110, 160), (200, 220, 232), (236, 242, 248),
    (150, 160, 140), (222, 196, 140), (196, 200, 130), (150, 184, 104), (70, 128, 70), (40, 110, 52),
    (164, 146, 104), (140, 124, 108), (220, 220, 225), (210, 120, 90)]
ATLAS = PREVIEW
# A dark, low-key variant for night-friendly display.
DARK = [
    (8, 12, 22), (10, 16, 30), (14, 24, 40), (16, 28, 46), (70, 80, 92), (92, 98, 108),
    (52, 56, 54), (70, 64, 52), (58, 62, 50), (48, 58, 44), (34, 48, 36), (28, 46, 32),
    (62, 58, 50), (72, 68, 64), (110, 112, 118), (120, 96, 60)]

# Geographic ASCII: (unicode glyphs, plain-ASCII glyphs, colour) per class, in the spirit of
# Dwarf Fortress's world map. A glyph is picked per place, so the pattern stays put as the
# map moves.
ASCII = [
    ('≈≈~', '~~-', (24, 52, 150)),     # deep ocean  ≈
    ('≈~≈', '~-~', (36, 84, 196)),     # ocean
    ('~~≈', '~~=', (60, 140, 220)),         # shallow sea
    ('≈~', '~=', (80, 160, 230)),           # lake
    ('░·:', ':.:', (200, 230, 240)),   # sea ice  ░·:
    ('░*:', '*:*', (240, 248, 255)),        # ice
    ('.,"', '.,"', (150, 170, 150)),             # tundra
    ('·∙,', '.,:', (228, 196, 110)),   # desert  ·∙
    ('.,`', '.,`', (178, 200, 96)),              # plains
    ('"∙,', '",;', (110, 190, 80)),         # grassland
    ('♣♠τ', 'TtT', (46, 150, 60)),  # forest  ♣♠τ
    ('♠♣Γ', 'T%T', (30, 170, 70)),  # jungle  ♠♣Γ
    ('∩n∩', 'nnm', (176, 150, 96)),    # hills  ∩
    ('▲^∧', '^^A', (170, 160, 150)),   # mountains  ▲^∧
    ('▲▲^', 'AA^', (245, 245, 250)),   # peaks
    ('#+▓', '#+#', (220, 210, 160)),        # urban  ▓
]

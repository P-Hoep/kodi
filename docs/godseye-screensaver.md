# God's Eye Map: Kodi screensaver

`screensaver.godseye.map` v0.2.0

A Kodi screensaver that shows a live, slowly animated map of one place. It draws
real-time layers on top of the map: aircraft, satellites, transit vehicles,
traffic, rain radar, clouds, lightning, earthquakes and storms. It also shows a
local weather card with the moon phase, and offers optional "sensor looks"
(night vision, FLIR, CRT and so on). The ideas and data sources come from
[God's Eye View](https://github.com/bilawalsidhu/gods-eye-view), redone as a 2D
OpenStreetMap-style map that runs on a Fire TV Stick.

It is pure Python with no compiled dependencies. It runs on Kodi 20 (Nexus) and
21 (Omega) and has been tested on Kodi 21.1 (macOS) and 21.2 (Fire TV Stick).
There is no tracking or interactivity: you set a location, a zoom level and the
layers you want, and it plays.

---

## Contents

- [Installing](#installing)
- [Settings reference](#settings-reference)
- [Layers and data sources](#layers-and-data-sources)
- [Sensor looks](#sensor-looks)
- [How it works](#how-it-works)
- [Project layout](#project-layout)
- [Development and testing](#development-and-testing)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)

---

## Installing

### On a Fire TV Stick (adb, the quick way)

See [fire-sticks.md](fire-sticks.md). In short: push the `screensaver.godseye.map`
folder into Kodi's `addons` folder, restart Kodi, enable the add-on and set it
as the screensaver over JSON-RPC.

### From the zip (any Kodi, no adb)

1. Build the zip: `python3 tools/build_zip.py` → `dist/screensaver.godseye.map-0.2.0.zip`
2. Serve it on the LAN: `cd dist && python3 -m http.server 8000`
3. In Kodi, go to **Settings → File manager → Add source** and enter `http://<mac-ip>:8000`.
4. Turn on **Settings → System → Add-ons → Unknown sources**.
5. **Settings → Add-ons → Install from zip file →** that source → the zip. Kodi
   pulls `script.module.certifi` from the official repo automatically.
6. Go to **Settings → Interface → Screensaver → Screensaver mode** and pick
   **God's Eye Map**. **Preview** runs it right away, and **Settings** configures it.

### On the Mac's Kodi (development)

`python3 tools/kodi.py install` symlinks the add-on folder into
`~/Library/Application Support/Kodi/addons/` and enables it, so code edits take
effect the next time the screensaver starts.

> ⚠️ **The TomTom key is hardcoded** (`BUILTIN_TOMTOM_KEY` in
> `resources/lib/screensaver.py`) for home use. Don't push this repo or share
> the zip publicly while it is there. Either blank the constant and enter the
> key in settings, or keep the repo private.

---

## Settings reference

Open them from **Settings → Interface → Screensaver → Settings**. Defaults are in **bold**.

### Location

| Setting | Default | Notes |
|---|---|---|
| Place name shown on screen | **Home** | Shown on the info card. |
| Find a place by name… | - | Searches with Photon (OpenStreetMap geocoder) and fills in name, lat and lon. |
| Latitude / Longitude | **44.9031331 / -93.3096136** | Map centre. |
| Zoom | **16** (2-17) | 3 ≈ continent, 9 ≈ metro area, 13 ≈ streets, 16 ≈ a few blocks. |
| Show home icon at the centre | **On** | A large house marker at the exact centre, tinted to suit the look. |
| Base map | **Dark** | OpenStreetMap, Dark (Esri Dark Gray), Satellite (Esri), Satellite + labels, NASA satellite image of the day (VIIRS, yesterday's, zoom ≤ 9 detail). |

### Air & space

| Setting | Default | Notes |
|---|---|---|
| Flights | **On** | Shown from zoom 4. Positions are dead-reckoned between fetches, so planes glide. |
| Military aircraft | Off | adb.lol military feed. |
| Flight refresh (seconds) | **20** (10-120) | How often aircraft data is fetched. Motion stays smooth regardless. |
| Satellites overhead | **On** | Computed on the device with SGP4. |
| Which satellites | **100 brightest** | Space stations, 100 brightest, GPS, Weather satellites, Starlink. |

### Weather & Earth

| Setting | Default | Notes |
|---|---|---|
| Rain radar (US) | **On** | NOAA MRMS base reflectivity, refreshed every 5 min. |
| Infrared clouds | Off | **Only drawn at zoom 10 and further out**, hidden automatically when zoomed in (see [clouds](#infrared-clouds)). |
| Lightning (Americas) | Off | NOAA nowCOAST strike density. |
| Weather overlay opacity | **70 %** | Applies to radar and lightning. |
| Earthquakes | **On** | USGS, past day / week (M2.5+) / month (M4.5+), with a minimum magnitude filter. |
| Tropical storms & hurricanes | **On** | NHC active storms. |

### Traffic & transit

| Setting | Default | Notes |
|---|---|---|
| TomTom API key | blank | Blank uses the built-in key. Free tier is 200k tiles/month. |
| Traffic flow | **On** | TomTom relative-speed flow lines. |
| Traffic incidents | Off | TomTom incident tiles. The white arrows are road closures and incident directions. |
| Traffic refresh | **600 s** (300-1800) | |
| Rail, subway & tram lines | **On** | OpenRailwayMap, from zoom 7. |
| Live transit vehicles | **On** | Keyless GTFS-realtime feeds, from zoom 8. Minneapolis–St Paul (Metro Transit) covers home. |
| Extra GTFS-realtime URL | blank | Any keyless *vehicle positions* feed for another city. |

### Weather card

| Setting | Default | Notes |
|---|---|---|
| Show local weather card | **On** | Open-Meteo current conditions for the map centre, refreshed every 15 min. |
| Show moon phase | **On** | Calculated locally, no network. Accurate to about half a day against USNO tables. |
| Units | **Fahrenheit, mph** | Or Celsius, km/h. |

### Display

| Setting | Default | Notes |
|---|---|---|
| Sensor look | **Off** | See [Sensor looks](#sensor-looks). |
| Show place name, clock and layer counts | **On** | Info card. |
| Show labels next to markers | **On** | Callsigns, route numbers, etc. At most 30 labels, without overlaps. |
| Maximum markers on screen | **150** (50-300) | Lower this if a stick struggles. |
| Dim the map | **0 %** | |
| Slowly drift the map | Off | Burn-in protection for OLED and plasma screens. |

---

## Layers and data sources

None of these need a paid key. The only key is TomTom's, and its free tier covers this use.

| Layer | Source | Coverage | Refresh |
|---|---|---|---|
| Base maps | OpenStreetMap, Esri, NASA GIBS | Global | Cached on disk 7 days |
| Flights | adsb.lol, with OpenSky as fallback | Global (ADS-B coverage) | 20 s (setting) |
| Military aircraft | adsb.lol `/mil` | Global | 60 s |
| Satellites | CelesTrak TLEs + bundled `sgp4` 2.24 | Global | TLEs every 6 h, positions every tick |
| Earthquakes | USGS GeoJSON feeds | Global | 5 min |
| Tropical storms | NOAA NHC `CurrentStorms.json` | Atlantic / E. Pacific | 15 min |
| Rain radar | NOAA nowCOAST (MRMS) WMS | CONUS | 5 min |
| Lightning | NOAA nowCOAST WMS | Americas | 5 min |
| Infrared clouds | NOAA nowCOAST GOES / global IR mosaic | Global | 10 min |
| Traffic | TomTom raster flow + incidents | Global | 10 min (setting) |
| Rail lines | OpenRailwayMap tiles | Global | Cached 7 days |
| Transit vehicles | GTFS-realtime (MBTA, CapMetro, Metro Transit, HSL, OVapi, Entur, TransLink) | Those cities | 30 s |
| Weather card | Open-Meteo | Global | 15 min |
| Moon phase | Local calculation | - | - |

Credits are shown on screen. For personal use, follow each provider's terms.
The OpenStreetMap tile servers aren't meant for heavy use, so don't deploy this widely as is.

---

## Sensor looks

Kodi can't run shaders, so each look combines what a Python screensaver can do:

| Look | Works on | How |
|---|---|---|
| Night vision | Any base map | Green tile tint, light-green markers, heavy vignette, grain |
| CRT terminal | Any base map | Warm tint, scanlines, vignette, light grain |
| FLIR white-hot | OpenStreetMap | Tiles recoloured by a made-up "heat" (roads hot, water cold), white markers |
| FLIR black-hot | OpenStreetMap | Inverse of white-hot. Markers are black, but the home and bus badges stay white so they remain readable |
| Ironbow thermal | OpenStreetMap | Heat mapped to the black→purple→red→yellow→white ironbow ramp |
| Noir | OpenStreetMap | High-contrast greyscale |

The recolouring looks work by rewriting the 256-entry palette of OSM's palette
PNGs as tiles are cached (`looks.recolor_palette_png`). That is cheap, but it
only works on OpenStreetMap tiles. On other base maps those looks fall back to
markers and overlays only. Recoloured tiles go in their own cache folder (for
example `osm-ironbow`).

---

## How it works

### Rendering loop

`screensaver.py` opens a 1080i `WindowXMLDialog` and adds every control up
front, in fixed pools: tiles, overlay tiles, cloud image, markers, labels, info
card, weather card, home icon and look overlays. Nothing is created or destroyed
while it runs.

- **Fixed 1-second tick.** Each tick computes where every marker will be one
  second from now and gives Kodi a 1-second *slide* animation to get there.
  Kodi interpolates at the display frame rate, so motion is smooth even though
  Python only runs once a second. This replaced an earlier 2 Hz update that
  visibly stuttered, and cut CPU from about 60% to about 44% on the stick.
- **Stable slots.** Each object (aircraft hex, vehicle id) keeps the same
  control between ticks, so animations continue instead of jumping.
- **Selection** (which markers to draw, given the marker limit) runs every 4 s
  or when new data arrives. A fair-share budget per layer plus a 64 px grid
  declutter stops one busy layer from crowding out the others.
- **Tiles** are only re-checked when a download finished, the map drifted, or
  every 5 s.
- **Headings** use pre-rendered rotated icons (`media/rot/plane_000…355`, every
  5°). Kodi's rotate animation pivots around the control's *original* position,
  so planes drifted away from their labels when it was used.

### Motion

- **Aircraft use dead reckoning.** Each fix has a time, speed and track, and
  `Item.position_at(t)` projects forward, for up to 60 s. Planes move
  continuously between 20-second fetches.
- **Transit glides one step behind.** Buses and trains only report positions, so
  `motion.Glider` moves each vehicle from its previous reported point to the
  newest one over the 30 s fetch interval plus 3 s. A jump faster than 45 m/s, such
  as a GPS glitch or a new trip, teleports instead of gliding.

### Tiles and caching

- `TileCache` downloads in background daemon threads (`workers.Workers`; not
  `concurrent.futures`, because Kodi kills a screensaver that takes more than
  5 s to exit) into `special://profile/addon_data/screensaver.godseye.map/tiles/<source>/<z>/`.
- Weather tiles are time-bucketed, and old buckets are pruned (radar and
  lightning after 3 h, base maps after 14 days).
- Zooming in past a source's maximum zoom uses enlarged parent tiles
  (`Viewport.tiles_at(max_zoom)`).

### Infrared clouds

Infrared satellite pixels are 2-4 km wide. As ordinary map tiles, they turned
into blocky bins from about zoom 8 and empty or opaque edge tiles from zoom 12.
That edge tile was the grey bar on the right of the screen. Clouds therefore
use a different approach (`clouds.py`):

1. One WMS `GetMap` covers the whole screen plus a 96 px margin, at roughly the
   satellite's own resolution (24-384 px wide).
2. Zoom 6 and closer inside the Americas uses GOES regional IR (2 km). Anything
   else uses the global IR mosaic (4 km).
3. The image is decoded with a small pure-Python PNG codec (`png.py`). Warm,
   clear pixels become transparent and cold cloud tops become white, with
   brightness thresholds set per product. The result is re-encoded and
   stretched by Kodi.
4. The overlay is **hidden above zoom 10**, where the satellite pixels are larger than the view.

### Kodi gotchas found along the way

- Calling `setLabel` on a label **before** `addControls` broadcasts the text to
  id-0 labels in the active window, and it showed up on the Kodi home screen.
  Pass the initial text in the constructor instead.
- Kodi caches add-on strings. After renaming the add-on or editing `strings.po`,
  restart Kodi, or the settings labels show blank.
- New add-ons copied into `addons/` start **disabled**. Enable them with
  `Addons.SetAddonEnabled`.

---

## Project layout

```
screensaver.godseye.map/            the add-on (this folder is what gets installed)
  addon.xml                         id, version, deps (xbmc.python 3.0.0, script.module.certifi)
  default.py                        entry point: screensaver, or the "find_location" action
  resources/settings.xml            GENERATED by tools/make_settings.py
  resources/language/.../strings.po GENERATED by tools/make_settings.py
  resources/skins/Default/1080i/    the (empty) window XML
  resources/media/                  icons, rotated icons, moon phases, look overlays (GENERATED)
  resources/lib/
    screensaver.py                  window, render loop, settings (the only Kodi-heavy module)
    layers.py                       data layers + parsers (flights, quakes, storms, transit, satellites)
    tiles.py                        tile sources, overlays, disk cache
    clouds.py                       single-image infrared cloud overlay
    png.py                          minimal PNG decoder/encoder
    looks.py                        sensor looks + palette recolouring
    weather.py                      Open-Meteo + moon phase
    motion.py                       transit glider
    geo.py                          Web Mercator maths, Viewport
    gtfs_rt.py                      protobuf decoder for GTFS-realtime
    net.py                          HTTP (user agent, certifi, gzip)
    workers.py                      daemon thread pool
    setup.py                        "Find a place by name" dialog
    sgp4/                           vendored python-sgp4 2.24 (MIT)
tools/
  make_settings.py                  the settings table → settings.xml + strings.po
  make_media.py                     draws all icons/overlays (needs Pillow)
  build_zip.py                      → dist/screensaver.godseye.map-<version>.zip
  kodi.py, kodi_set.py              drive the Mac's Kodi over JSON-RPC for testing
tests/test_core.py                  unit tests for the Kodi-free modules
```

Modules marked "no Kodi imports" in their docstrings can be tested with plain `python3`.

---

## Development and testing

```bash
python3 -m unittest discover tests          # offline tests
LIVE=1 python3 -m unittest discover tests   # also hits every live feed

python3 tools/make_settings.py              # after editing the settings table
python3 tools/make_media.py                 # after editing icons (needs Pillow)
python3 tools/build_zip.py                  # build the installable zip

# Mac Kodi (log: ~/Library/Logs/kodi.log)
python3 tools/kodi.py install               # symlink + enable
python3 tools/kodi.py select                # make it the screensaver
python3 tools/kodi.py set zoom=12 basemap=0 look=3
python3 tools/kodi.py run                   # start it now
python3 tools/kodi.py shot out.png          # screenshot
python3 tools/kodi.py log                   # recent add-on log lines
```

To change a default, edit **both** `tools/make_settings.py` (what Kodi shows)
and the `BOOLS`/`INTS`/`NUMBERS` tables in `screensaver.py` (the fallbacks the
code uses), then run `make_settings.py`.

To bump the version, edit `addon.xml`. `build_zip.py` reads it from there.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Settings labels blank | Kodi string cache. Restart Kodi. |
| Add-on not in the screensaver list | It's disabled. Enable it in My add-ons, or over JSON-RPC. |
| "Loading weather…" text on Kodi's home screen | Old build. Fixed by constructing labels with their text. |
| Grey bar on the right with clouds on | Old build (tile-based clouds). Update to the current add-on. |
| No planes | Zoom must be 4 or more. adsb.lol may be rate-limiting; check the log for `flights`. |
| No transit vehicles | Zoom must be 8 or more, and the location must be inside a supported feed (or set a custom URL). |
| No traffic | Bad or exhausted TomTom key, or traffic tiles simply aren't loaded yet. |
| FLIR/ironbow look shows a normal map | Those looks only recolour the OpenStreetMap base map. |
| Stutters on an older stick | Lower *Maximum markers*, turn off labels, or turn off satellites (Starlink is heavy). |

Logs: `~/Library/Logs/kodi.log` (Mac) and
`/sdcard/Android/data/org.xbmc.kodi/files/.kodi/temp/kodi.log` (Fire TV).
Add-on lines contain `godseye`.

---

## Known limitations

- Radar is US-only and lightning is Americas-only. Clouds are global but only make sense at zoom ≤ 10.
- The recolouring sensor looks need the OpenStreetMap base map.
- Dark and NASA base maps max out at zoom 16 and 9; closer zooms enlarge parent tiles.
- Transit only works in cities with a keyless GTFS-realtime feed.
- Everything is fetched by the stick itself, so a dozen sticks means a dozen
  times the requests. Keep refresh intervals at their defaults.

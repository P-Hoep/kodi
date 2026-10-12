# God's Eye Map — Kodi screensaver

A Kodi screensaver that shows a live map of a place you choose, with layers
inspired by [God's Eye View](https://github.com/bilawalsidhu/gods-eye-view):
flights, military aircraft, satellites overhead, earthquakes, tropical storms,
rain radar, infrared clouds, lightning, rail/subway lines, live transit
vehicles and traffic, plus a local weather card with the moon phase and
optional sensor looks (night vision, FLIR, CRT…).

Pure Python, no compiled dependencies: runs on Kodi 20 (Nexus) and 21 (Omega),
including Android / Fire TV. Tested on Kodi 21.1 (macOS) and 21.2 / 21.3 (Fire TV Stick).

## God's World Map (new, v0.1)

A second screensaver in this repo, `screensaver.godsworld.map`, built from
[docs/godsworld-screensaver.md](docs/godsworld-screensaver.md): the whole Earth in
thirteen projections (Mercator, Robinson, Dymaxion, Gall–Peters, Equal Earth,
Sinu-Mollweide, Goode, cylindrical equal-area, Peirce quincuncial, Winkel tripel,
an octahedral butterfly, globe, and Waterman's butterfly on his W5 polyhedron), with clouds, precipitation, temperature, wind and
storms, the day/night line and city lights, and Dwarf Fortress-style ASCII modes. 

```bash
python3 tools/make_world_data.py              # bundled world data (needs Pillow, numpy)
python3 tools/make_settings_godsworld.py      # settings.xml + strings.po from resources/lib/config.py
python3 tools/build_zip.py screensaver.godsworld.map
KODI_ADDON=screensaver.godsworld.map python3 tools/kodi.py install   # then select / run / shot
python3 -m unittest tests.test_world
```

Design in one paragraph: all layers are composed in longitude/latitude
(`world.py`), every projection is a triangle mesh rasterised once into a cached
lookup table (`projections.py`, `reproject.py`), and each frame is one C-level
table lookup plus a PNG write, all in pure Python. Kodi itself animates panning,
cross-fades and the wind particles at display rate. Spinning views (the globe)
are re-rendered frames, about 3–10 a second on a Mac.

## Math Clock (new, v0.1)

A third screensaver, `screensaver.math.clock`, built from
[docs/math-clock.md](docs/math-clock.md) and the old web clock in `mathclock-old/`
(themathclock.com). The year, month, day, hours, minutes and seconds each show as an
equation whose answer is the current value, typeset in Computer Modern like LaTeX.

- **Equation sets:** *Classic* (the original 17 puzzles, ported one for one), *Advanced*
  (fractions, powers, logs, sums, binomials, floors) and **Algebra 2** (the default),
  which mixes the classic and advanced puzzles with Algebra 2 ones: quadratics by
  factoring and by the quadratic formula, linear systems, exponential and
  log equations, log rules, rational exponents and nth roots, radical, rational and
  absolute-value equations, f(x) evaluation, composition and inverses, complex numbers,
  arithmetic and geometric sequences and series, 2×2 determinants, permutations and
  combinations. Every puzzle has exactly one answer; a quadratic with
  two roots says which one, e.g. `h² − 13h + 36 = 0, h > 4`.
- **The original's settings:** seconds, 24-hour clock (with a 24h badge), date, labels,
  inverted colours, day/night mode. **Extras:** date order, distinct M for month, refresh
  rate, text size, separators, fade or cut, dimming, OLED drift.

No TeX at run time: `tools/make_mathclock_media.py` renders each glyph once from the
BaKoMa Computer Modern fonts that ship with matplotlib, `texmath.py` is a small TeX
math layout engine (scripts, radicals, fractions, big operators, delimiters,
matrices), and Kodi positions and fades the glyph images. Kodi uses about 10–20 % CPU
on a Mac while it runs.

```bash
python3 tools/make_mathclock_media.py      # glyphs, metrics, icon (needs Pillow, matplotlib)
python3 tools/make_settings_mathclock.py   # settings.xml + strings.po from resources/lib/config.py
python3 tools/preview_mathclock.py out.png equation_set=3 colours=0   # draw the face with Pillow
python3 tools/build_zip.py screensaver.math.clock
KODI_ADDON=screensaver.math.clock python3 tools/kodi.py install       # then select / run / shot
python3 -m unittest tests.test_mathclock   # solves every generated puzzle from its LaTeX
```

## Couchstronomy (new, v0.1)

A fourth screensaver, `screensaver.couchstronomy`, built from
[docs/couchstronomy.md](docs/couchstronomy.md): the TV becomes a window onto the real
sky. Enter where the TV is and which way it faces (compass heading, tilt, field of view,
or screen width and viewing distance), and it shows the sky outside that window right now:
41,000 stars to magnitude 8 (HYG/Hipparcos), the Sun, the Moon with its phase and
earthshine, the planets with phases and Saturn's rings, Messier and bright
NGC objects, constellation lines and boundaries, and live satellites from CelesTrak.
Twilight, daylight, moonlight, light pollution, extinction and refraction are modelled.
Messier objects are shown as Fred Espenak's photos (AstroPixels.com, used with permission;
not MIT-licensed), blended into the sky and turned so north matches the sky. The originals
are in `tools/couch-src/messier`, and `python3 tools/make_couch_media.py messier` rebuilds them.

- **Labels** are independent of the sky: *Natural* (none), *Named objects* or *Explorer*
  (names, constellations, deep sky, an object spotlight every 30 s with distance,
  magnitude, altitude and azimuth). Clock, compass and a data-status line are optional.
- **Realistic vs Enhanced:** realistic is the default and shows only what the eye could
  see (the limiting magnitude drops in twilight and moonlight). Enhanced brightens faint
  stars and enlarges the Moon and planets, and the status line says so.
- **Satellites** are propagated on the device with SGP4 and hidden when their orbital
  data is older than the chosen limit (7 days by default); the status line gives the data
  age. Time-lapse and time-offset settings exist for previews, and are shown on screen.

Accuracy (checked by `tests/test_couch.py` against Skyfield/JPL DE421 for both
hemispheres, day and night): stars, Sun and planets within 5″, the Moon within 10″, the ISS
within 0.02° of SGP4, for 2020–2030. Beyond that, the unknown future difference between
UT1 and UTC adds up to 15″ per second of drift. One screen pixel is about 110″ at a 60°
field, so on screen the error is the TV's own calibration (a 1° heading error moves the
whole sky 32 pixels), not the astronomy.

```bash
python3 tools/make_couch_data.py       # bundled catalogues and textures (needs Pillow, numpy)
python3 tools/make_couch_media.py      # icon, fanart, sprites
python3 tools/make_settings_couch.py   # settings.xml + strings.po from resources/lib/config.py
python3 tools/preview_couch.py out.png time=2026-10-12T04:00 tilt=25 labels=2   # draw without Kodi
python3 tools/build_zip.py screensaver.couchstronomy
KODI_ADDON=screensaver.couchstronomy python3 tools/kodi.py install   # then select / run / shot
python3 -m unittest tests.test_couch   # acceptance tests (pip install skyfield for the accuracy ones)
```

Design: pure Python, no compiled code. For a fixed TV each screen pixel looks at a fixed
altitude and azimuth, so the ground mask is computed once and the sky colour is a small
image Kodi stretches. Stars, planets and lines are drawn into a transparent full-HD PNG with cached
sprites, re-rendered as often as the sky moves half a pixel (about every 4 s at 60°).
Satellites are Kodi controls that slide between positions at display rate.

## Screensaver Switcher (new, v0.1)

`service.screensaver.switcher`, built from [docs/screensaver-switcher.md](docs/screensaver-switcher.md):
a different screensaver for different times of day. Up to six time windows, each with a
start, an end and a screensaver chosen from the ones installed (Kodi's own picker), plus a
default for the times no window covers. A window can name a second screensaver to
alternate with, every 5-240 minutes (30 by default) counted from the window's start. Windows can cross midnight (22:00-06:00); start =
end means all day; when windows overlap the lowest-numbered one wins.

- A background service checks at each minute and, when the scheduled choice changes, sets
  Kodi's `screensaver.mode`. If a screensaver is running at that moment it wakes it and
  starts it again, so the new one shows within 1-2 s (*Restart a running screensaver*, on
  by default).
- It only acts when the schedule's choice changes (or at start-up or after a settings
  change), so a screensaver picked by hand in Kodi's settings stays until the next window
  boundary.
- **Programs → Screensaver Switcher** shows what is scheduled now, applies the schedule,
  previews the screensaver or opens the settings.

```bash
python3 tools/make_settings_switcher.py      # settings.xml + strings.po from resources/lib/config.py
python3 tools/build_zip.py service.screensaver.switcher
KODI_ADDON=service.screensaver.switcher python3 tools/kodi.py install   # then restart Kodi (see below)
python3 -m unittest tests.test_switcher
```

Kodi loads an add-on's strings only at start-up, so after a first install by symlink the
settings show blank labels until Kodi restarts.

## Documentation

- **[docs/godseye-screensaver.md](docs/godseye-screensaver.md)**: full
  documentation: every setting, layers and data sources, sensor looks, how the
  rendering and motion work, development and troubleshooting.
- **[docs/fire-sticks.md](docs/fire-sticks.md)**: the Fire TV Sticks on the home
  network (IPs, models, status) and how to connect with adb and deploy.

## Install from the repository (any Kodi 19+ device)

All the add-ons are published as a Kodi repository at
**https://p-hoep.github.io/kodi/**, so Kodi installs them and updates them itself.

1. **Settings → System → Add-ons → Unknown sources → On**.
2. **Settings → File manager → Add source →** `https://p-hoep.github.io/kodi/`, name it `phoep`.
3. **Settings → Add-ons → Install from zip file → phoep →** `repository.phoep-<version>.zip`.
4. **Settings → Add-ons → Install from repository → P-Hoep Add-ons →** pick a screensaver.
   Kodi pulls in `script.module.certifi` from its official repository automatically.

### Publishing a new version

Bump `version="…"` in the add-on's `addon.xml` and push to `main`. The
[Kodi repository workflow](.github/workflows/kodi-repo.yml) runs `tools/make_repo.py`
and deploys the result to GitHub Pages; installed copies update on Kodi's next
repository check (or **Add-ons → … → Check for updates**). Without a version bump Kodi
sees no update. Any new top-level folder with an `addon.xml` is picked up automatically.

```bash
python3 tools/make_repo.py      # build the same repository locally into dist/repo
cd dist/repo && python3 -m http.server 8000   # browse it at http://localhost:8000
```

## Install a local build on a Fire TV Stick

1. Build the zip on your computer: `python3 tools/build_zip.py`
   → `dist/screensaver.godseye.map-<version>.zip`
2. Get the zip onto the stick. The simplest way is to serve the `dist` folder
   from your computer and add it to Kodi as a file source:
   ```bash
   cd dist && python3 -m http.server 8000
   ```
   In Kodi: **Settings → File manager → Add source →** `http://<your-computer-ip>:8000`
3. Allow zips: **Settings → System → Add-ons → Unknown sources → On**.
4. **Settings → Add-ons → Install from zip file →** pick the source → the zip.
   Kodi installs `script.module.certifi` from its official repository
   automatically.
5. **Settings → Interface → Screensaver → Screensaver mode → God's Eye Map**,
   then **Settings** below it to configure. **Preview** shows it straight away.

## Configure

Everything is in the screensaver's settings (Settings → Interface →
Screensaver → Settings):

| Category | Settings |
|---|---|
| Location | Place name, **Find a place by name…** (searches and fills in the coordinates), latitude, longitude, zoom, home icon, base map (OpenStreetMap, Dark, Satellite, Satellite + labels, NASA satellite image of the day) |
| Air & space | Flights, military aircraft, flight refresh, satellites overhead and which group (space stations, 100 brightest, GPS, weather, Starlink) |
| Weather & Earth | Rain radar (US), infrared clouds (zoom ≤ 10), lightning (Americas), overlay opacity, earthquakes (period, minimum magnitude), tropical storms |
| Traffic & transit | TomTom API key, traffic flow, traffic incidents, traffic refresh, rail/subway/tram lines, live transit vehicles, extra GTFS-realtime URL |
| Weather card | Local weather (Open-Meteo), moon phase, °F/°C |
| Display | Sensor look, info card (place, clock, counts), marker labels, marker limit, dimming, slow drift for OLED/plasma screens |

Defaults: home (44.9031, -93.3096) at zoom 16. Zoom guide: 3 ≈ a continent, 9 ≈ a metro area, 13 ≈ streets, 16 ≈ a few blocks. Flights show from
zoom 4, transit vehicles from zoom 8, rail lines from zoom 7.

### Layer notes

- **Traffic** uses TomTom and needs a free TomTom API key, entered in the
  "TomTom API key" setting (nothing is built in). The free
  tier is 200,000 tiles/month; the default 10-minute refresh uses a few
  thousand a day.
- **Live transit vehicles** come from the keyless GTFS-realtime feeds God's Eye
  View uses: Boston (MBTA), Austin (CapMetro), Minneapolis–St Paul, Helsinki
  (HSL), the Netherlands (OVapi), Norway (Entur) and South East Queensland
  (TransLink). For another city, paste its GTFS-realtime *vehicle positions*
  URL into "Extra GTFS-realtime vehicle positions URL" (it must not need a key).
- **Rail, subway & tram lines** (OpenRailwayMap) work worldwide.
- **Rain radar and lightning** cover the US / the Americas only (NOAA).
  Infrared clouds are global but only drawn at zoom 10 and further out.
- **Satellites** are computed on the device from CelesTrak orbital elements
  (refreshed every 6 hours) with the bundled `sgp4` library.

## Develop

```
screensaver.godseye.map/        the add-on
  default.py                    entry point (screensaver, or the Find-a-place action)
  resources/lib/screensaver.py  window, rendering and refresh loop (Kodi-specific)
  resources/lib/layers.py       data layers (no Kodi imports)
  resources/lib/tiles.py        map tile sources and the tile cache (no Kodi imports)
  resources/lib/gtfs_rt.py      GTFS-realtime decoder (no Kodi imports)
  resources/lib/geo.py          Web Mercator maths (no Kodi imports)
  resources/lib/sgp4/           vendored python-sgp4 2.24 (MIT)
tools/make_settings.py          generates settings.xml + strings.po from one table
tools/make_media.py             generates the icons (needs Pillow)
tools/make_splash.py            draws every screensaver's loading splash (SVG in tools/splash/,
                                rendered to resources/media/splash.png with headless Chrome)
tools/build_zip.py              builds the installable zip
tools/make_repo.py              builds the Kodi repository (repository.phoep + every add-on)
tools/kodi.py                   drives a local Kodi over JSON-RPC for testing
tests/test_core.py              unit tests (LIVE=1 also hits the real feeds)
tests/test_splash.py            the shared loading splash (resources/lib/splash.py in each add-on)
```

```bash
python3 -m unittest discover tests        # offline tests
LIVE=1 python3 -m unittest discover tests # plus every live feed
python3 tools/kodi.py install             # symlink into a local Kodi and enable
python3 tools/kodi.py select              # make it Kodi's screensaver
python3 tools/kodi.py set zoom=12 basemap=0
python3 tools/kodi.py run                 # start it now
python3 tools/kodi.py shot out.png        # screenshot via Kodi
```

After renaming the add-on or changing `strings.po`, restart Kodi: it caches an
add-on's strings, and the settings labels show up blank until it reloads them.

## Data and terms

Map tiles © OpenStreetMap contributors, Esri, NASA GIBS, OpenRailwayMap
(CC BY-SA). Data from adsb.lol (ODbL), OpenSky Network, CelesTrak, USGS, NOAA
nowCOAST and NHC, TomTom, and the transit agencies listed above. Credits are
shown on screen. This is for personal use; follow each provider's terms, and
use a different tile provider if you deploy it widely (the OpenStreetMap tile
servers are not meant for heavy use).

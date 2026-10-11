# God's Eye Map — Kodi screensaver

A Kodi screensaver that shows a live map of a place you choose, with layers
inspired by [God's Eye View](https://github.com/bilawalsidhu/gods-eye-view):
flights, military aircraft, satellites overhead, earthquakes, tropical storms,
rain radar, infrared clouds, lightning, rail/subway lines, live transit
vehicles and traffic, plus a local weather card with the moon phase and
optional sensor looks (night vision, FLIR, CRT…).

Pure Python, no compiled dependencies: runs on Kodi 20 (Nexus) and 21 (Omega),
including Android / Fire TV. Tested on Kodi 21.1 (macOS) and 21.2 / 21.3 (Fire TV Stick).

## Documentation

- **[docs/godseye-screensaver.md](docs/godseye-screensaver.md)**: full
  documentation: every setting, layers and data sources, sensor looks, how the
  rendering and motion work, development and troubleshooting.
- **[docs/fire-sticks.md](docs/fire-sticks.md)**: the Fire TV Sticks on the home
  network (IPs, models, status) and how to connect with adb and deploy.

## Install on a Fire TV Stick

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

- **Traffic** uses TomTom. A personal key is built in (`BUILTIN_TOMTOM_KEY`
  in `screensaver.py`) for home use; the "TomTom API key" setting overrides
  it. Don't publish this repository or the zip with the key in it. The free
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
tools/build_zip.py              builds the installable zip
tools/kodi.py                   drives a local Kodi over JSON-RPC for testing
tests/test_core.py              unit tests (LIVE=1 also hits the real feeds)
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

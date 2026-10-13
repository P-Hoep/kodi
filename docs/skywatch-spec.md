# Kodi Weather Radar Screensaver — Spec

Oct 12, 2026

## Overview

**SkyWatch** (working name, add-on id `screensaver.skywatch`) is a Kodi screensaver that turns an idle TV into a live weather station: an animated radar loop over a map of your location, a short future-radar extension, and a rotating set of forecast, fishing and climate panels you switch on or off.

**Goals**

- Look great from the couch: legible at 3 m on a 1080p or 4K screen, smooth 60 fps panning and crossfades.
- Run on modest hardware (Raspberry Pi 4/5, Shield, x86 HTPC) without hurting playback when the screensaver exits.
- Use only free data: keyless services first, free-tier API keys you paste in to unlock extras.
- Every feature is a toggle; every view is a "scene" in a playlist you control.
- Degrade gracefully: if a source fails, its panel hides or shows cached data with an age stamp, never an error dialog.

**Non-goals (v1)**

- Not a general weather add-on (Kodi's `weather.*` providers stay separate; SkyWatch can optionally read the active one but does not replace it).
- No interactive analysis tools (no velocity products, cross-sections or storm tracking).
- No push notifications or alerts outside the screensaver; severe alerts show as a banner only while it runs.
- No paid data sources required for any default feature.

**Assumptions**: US location for the richest data (NWS, NOAA, USGS); worldwide still works through Open-Meteo and global radar with fewer extras. Units default to imperial (°F, mph, inHg) and are switchable.

## Data sources

Every default feature runs keyless; two optional free keys unlock global future radar and extra polish. The big change to plan around: RainViewer's free API dropped future (nowcast) radar, satellite and zoom above 7 on 1 Jan 2026 ([RainViewer transition FAQ](https://rainviewer.com/api/transition-faq.html)), so future radar comes from HRRR model tiles (US) or Rainbow.ai (global, free key).

### Radar and imagery

| Source | Used for | Key | Coverage | Limits and terms |
| --- | --- | --- | --- | --- |
| [IEM NEXRAD composite tiles](https://mesonet.agron.iastate.edu/GIS/) | Past radar loop (5-min frames, ~2 h) | None | US | Public academic service; cache tiles, keep request rate low |
| [IEM HRRR simulated reflectivity](https://mesonet.agron.iastate.edu/GIS/model.phtml) | **Future radar (default, US)**: REFD, or REFP with precip-type colors | None | US (CONUS) | 15-min steps out to 18 h; new run hourly, ready ~:40 past the hour |
| [Rainbow.ai Tiles API](https://developer.rainbow.ai/) | **Future radar (optional, global)**: ML nowcast from real radar | Free key | Global, ~1 km | 30,000 tiles/month free, then $0.20 per 1,000; up to 4 h ahead |
| [RainViewer Weather Maps API](https://rainviewer.com/api.html) | Past radar outside the US | None | Global | Zoom 7 max, one color scheme, 100 req/IP/min, personal use, attribution required |
| [LibreWXR](https://github.com/JoshuaKimsey/LibreWXR) (self-hosted) | Power-user alternative: RainViewer-compatible API with nowcast, satellite, all color schemes | None | Global | You run the server; SkyWatch just points at its base URL |
| NASA GIBS / IEM GOES tiles | Satellite (GeoColor, IR) layer | None | Global / Americas | Cache aggressively |

### Forecast, climate and alerts

| Source | Used for | Key | Limits and terms |
| --- | --- | --- | --- |
| [Open-Meteo](https://open-meteo.com/) Forecast | Current, 15-min, hourly (48 h), daily (16 d): temp, precip probability, wind, gusts, pressure, cloud, UV, visibility | None | Non-commercial; ~10,000 calls/day; credit requested |
| Open-Meteo Historical (archive) | Normals and anomaly: 30-year daily mean/max/min from ERA5 back to 1940 | None | Same quota; fetch once per location, cache forever |
| Open-Meteo Marine | Wave height, sea-surface temp for coastal spots | None | Same quota |
| Open-Meteo Air Quality | AQI, PM2.5, pollen (where modeled) | None | Same quota |
| Open-Meteo Geocoding | City/ZIP search in settings | None | Same quota |
| NWS API (api.weather.gov) | Active alerts for the point, NWS text forecast, Area Forecast Discussion | None (send a User-Agent with contact) | US only |
| RCC-ACIS (data.rcc-acis.org) | Station-based records and normals for the nearest long-record station | None | US only; better "record high" than gridded data |
| NOAA CO-OPS Tides & Currents | Tide predictions, water temp at tide stations | None | US coasts and Great Lakes |
| USGS Water Data | River gauge water temperature, flow, stage (fishing) | None | US; confirm current endpoint at build time (legacy service is being replaced) |
| Computed locally | Sun/moon times, moon phase, solunar periods | n/a | No network |

### Base maps

| Source | Key | Notes |
| --- | --- | --- |
| CARTO basemaps (Dark Matter, Positron, Voyager) | None | Default: Dark Matter reads best under radar; attribution to OSM and CARTO |
| Stadia Maps or MapTiler | Free key | More styles (terrain, satellite hybrid) |
| Esri World Imagery | None | Satellite photo base; attribution required |

Base-map tiles are rendered once per location and zoom, then cached indefinitely: the map does not move, so it costs almost nothing after first run.

### Request budget (typical day, screensaver on 8 h)

- Open-Meteo: ~150 calls (forecast every 15 min, air quality hourly, marine hourly); well under 10,000.
- IEM radar + HRRR: one 1080p view at one zoom is ~50 tiles of 256 px; past loop refresh every 5 min adds 1 new frame (~50 tiles), HRRR refresh hourly (~12 frames, ~600 tiles).
- Rainbow.ai: 30,000 tiles/month is ~1,000/day, i.e. about 20 frames of one view per day. The budget manager (see Architecture) refreshes the nowcast at most every 60 min, only while the screensaver is active, at one zoom, and falls back to HRRR when the month's allowance is 90% used.

## Architecture

SkyWatch is one Python add-on with two entry points: a background service that fetches, caches and composites, and a screensaver window that only plays finished frames and reads cached values.

```
 FREE DATA SOURCES            BACKGROUND SERVICE                 SCREENSAVER WINDOW
+----------------------+     +-------------------------------+   +------------------------+
| Radar and imagery    |---->| Fetchers + budget manager     |   | Scene player           |
| IEM, HRRR, Rainbow,  |  +->| polls on schedule, backs off, |   | playlist, timers,      |
| RainViewer, GIBS,    |  |  | falls back Rainbow -> HRRR    |   | crossfades, alerts     |
| base maps            |  |  +---------------+---------------+   +-----------+------------+
+----------------------+  |                  v                       ^       v
| Weather APIs         |--+  +-------------------------------+       |  +------------------------+
| Open-Meteo, NWS,     |     | Cache                         |-------+  | Frame stack            |
| ACIS, CO-OPS, USGS   |     | tiles by source/z/x/y/time    | values   | one ControlImage per   |
+----------------------+     | SQLite JSON with expiry       |          | frame, toggled to play |
| Computed locally     |     +---------------+---------------+          +------------------------+
| sun, moon, solunar,  |                     v                               ^
| fishing score        |---->+-------------------------------+   frames      |
+----------------------+     | Compositor (Pillow)           |---------------+
                             | map + radar + labels -> JPEG  |   +------------------------+
                             | graphs drawn as PNG           |   | Overlay layer          |
                             +-------------------------------+   | clock, legend, age,    |
                                                                 | attribution            |
                                                                 +------------------------+
```

Data flows left to right. The screensaver never touches the network, so it starts instantly and keeps running offline.

### Add-on layout

```
screensaver.skywatch/
  addon.xml
  default.py                  # screensaver entry: opens the window
  service.py                  # background service entry
  resources/
    settings.xml
    language/resource.language.en_gb/strings.po
    skins/default/1080i/skywatch-main.xml
    media/                    # icons, legends, location pin
    lib/
      config.py               # settings wrapper, units
      geo.py                  # Web Mercator tile math, bbox, pixel at lat/lon
      sources/                # one module per provider, common interface
        base.py               # Source: frames(), fetch(), expiry, quota, status
        iem.py hrrr.py rainbow.py rainviewer.py librewxr.py gibs.py basemap.py
        openmeteo.py nws.py acis.py coops.py usgs.py
      budget.py               # per-source request counters and caps
      cache.py                # tile store, SQLite JSON cache, LRU eviction
      compose/
        radar.py              # frame compositor
        charts.py             # Pillow chart primitives
        scenes/               # one renderer per graph scene
      astro.py                # sun, moon, solunar
      fishing.py              # score model
      climate.py              # normals and anomalies
      player.py               # scene playlist, timers, alert promotion
      window.py               # WindowXMLDialog subclass, frame stack
```

### addon.xml essentials

```xml
<addon id="screensaver.skywatch" name="SkyWatch" version="1.0.0" provider-name="you">
  <requires>
    <import addon="xbmc.python" version="3.0.1"/>
    <import addon="script.module.requests"/>
    <import addon="script.module.pil"/>
  </requires>
  <extension point="xbmc.ui.screensaver" library="default.py"/>
  <extension point="xbmc.service" library="service.py"/>
  <extension point="xbmc.addon.metadata">...</extension>
</addon>
```

Minimum Kodi 20 (Python 3 API 3.0.1); primary target Kodi 21 Omega, tested on 22 Piers beta. Pin module versions to what the official repo ships at build time.

### Source interface

Every provider implements one small interface so the fallback chain and budget manager treat them alike: `frames(bbox, zoom, kind)` returns timestamped tile URLs for `past` or `future`, plus `fetch(url)`, `expiry`, `quota` and `status`. The radar pipeline asks for past and future frames, and the chain picks the first healthy source in the user's order.

### Processes and threads

- **Service**: one scheduler thread (a priority queue of jobs by next-due time), a download pool of 4 threads (2 on Low), one compositor thread. Sleeps entirely during video playback.
- **Screensaver**: Kodi's UI thread for the window, plus one timer thread that advances frames and scenes. It reloads frames when the service atomically rewrites a `manifest.json` in the frame store.
- **Hand-off**: files plus a few home-window properties (`xbmcgui.Window(10000).setProperty`) for status flags; no sockets.
- **Exit**: the window closes on `onAction` (unless interactive mode) and on `xbmc.Monitor.onScreensaverDeactivated`.

## Views and panels

The screensaver plays a **scene playlist**: each scene is a full-screen view shown for a set time, then crossfades to the next. Every scene can be switched off, reordered and given its own duration. A persistent **overlay layer** (clock, location, alert banner, attribution) sits on top of all scenes.

### Scenes

| # | Scene | What it shows | Default | Data |
| --- | --- | --- | --- | --- |
| 1 | Local radar loop | Your zoom, past 2 h + future 2 h, looping; timeline bar marked PAST / NOW / FUTURE; frame timestamp; your location pin; optional storm-motion arrow | On, 60 s | IEM, HRRR or Rainbow, base map |
| 2 | Regional radar | Same loop 2 zoom levels out, plus active NWS warning polygons outlined in their official colors | On, 30 s | IEM, NWS |
| 3 | National mosaic | CONUS or continent-wide loop, slower frame rate | Off, 20 s | IEM or RainViewer |
| 4 | Satellite + radar | GeoColor by day, IR at night, radar on top at 60% opacity | Off, 30 s | GIBS/IEM GOES |
| 5 | Future-only "what's coming" | 0 to 18 h HRRR in 30-min steps, with "rain reaches you around 4:40 PM" when the pixel at your pin first crosses 20 dBZ | On, 30 s | HRRR |
| 6 | Current conditions | Large temp and icon, feels-like, wind and gusts with compass, humidity, dew point, pressure with 3-h trend arrow, UV, visibility, sunrise/sunset | On, 20 s | Open-Meteo |
| 7 | Next 2 hours | 15-min precipitation bars, "rain starting in 25 min" headline | On when precip expected | Open-Meteo minutely_15 or Rainbow nowcast |
| 8 | Hourly graph | 48 h: temp and feels-like lines, precip probability bars, wind speed band, day/night shading | On, 25 s | Open-Meteo |
| 9 | Daily forecast | 7 or 10 day cards: icon, hi/lo range bar on a shared scale, precip %, wind, and the NWS one-line summary when in the US | On, 25 s | Open-Meteo, NWS |
| 10 | Climate: today vs normal | Today's hi/lo against the 1991–2020 normal band and record hi/lo; month-to-date daily anomaly bars; "warmest Oct 12 since 2015" style facts | On, 25 s | Open-Meteo archive, ACIS |
| 11 | Year in temperature | Rolling 365-day daily highs and lows over the normal band, records marked | Off, 25 s | Open-Meteo archive |
| 12 | Fishing forecast | 0–100 score for today and next 3 days, solunar major/minor windows on a 24 h strip, moon phase, pressure trend, wind, cloud, water temp and tide or river flow | Off, 25 s | Computed + Open-Meteo, USGS, CO-OPS |
| 13 | Sun and moon | Day-length arc, change vs yesterday, moon phase and illumination, next full/new moon, golden hour | Off, 15 s | Computed |
| 14 | Air quality and pollen | AQI dial, dominant pollutant, pollen by type where available | Off, 15 s | Open-Meteo AQ |
| 15 | Marine and tides | Tide curve for today with high/low times, wave height and period, water temp | Auto when coastal | CO-OPS, Open-Meteo Marine |
| 16 | Forecast discussion | Scrolling key points from the NWS Area Forecast Discussion, large type | Off, 40 s | NWS |
| 17 | Ambient clock | Big clock, temp, small radar thumbnail | Off, 30 s | All cached |

### Overlay layer (each toggleable)

- Clock and date, 12/24 h.
- Location name and "updated 3 min ago" data age.
- Mini conditions chip (temp, icon) shown on non-conditions scenes.
- **Severe alert banner**: any active NWS Warning for your point pins a red banner to every scene and inserts the alert text scene at the head of the playlist. Watches and Advisories show as an amber chip only.
- Radar legend (dBZ color scale, precip-type legend for REFP).
- Attribution footer: required credits for map, radar and Open-Meteo, small and low-contrast.

### Fishing score

The score is a transparent weighted sum, shown with its parts so it never feels like a black box. Default weights (editable in settings):

| Factor | Weight | Best when |
| --- | --- | --- |
| Solunar period overlap | 30% | Major period within the hour window; dawn/dusk overlap scores extra |
| Barometric trend | 25% | Falling slowly before a front; poor right after a sharp rise |
| Moon phase | 15% | Within 2 days of new or full |
| Wind | 15% | 5–15 mph; poor above 20 mph |
| Cloud and light | 10% | Overcast or low light |
| Water temperature trend | 5% | Stable or warming in spring, stable in fall (needs a gauge) |

Users pick a **water body** (lake, river with USGS gauge, or coastal tide station) separate from the home location, so the fishing panel can show a favorite spot.

### Interaction

Kodi closes a screensaver on any input by default. SkyWatch keeps that default, with one optional **interactive mode**: left/right skip scenes, up/down change radar zoom, OK pauses the loop, Back exits. In interactive mode, only Back or a period of no input ends it.

## Settings

Settings use Kodi's version-1 `resources/settings.xml` format, grouped into categories as below. Location search runs through Open-Meteo Geocoding from a settings action button, so the user types "Duluth" or a ZIP and picks from a list; lat/lon can also be typed directly.

| Category | Setting | Type | Default |
| --- | --- | --- | --- |
| Location | Home location (search) | action → list | none; first run prompts |
| Location | Latitude / longitude | number | from search |
| Location | Display name | text | from search |
| Location | Fishing spot: same as home / custom lat-lon / USGS gauge ID / CO-OPS station ID | select + text | same as home |
| Map | Local zoom | slider 4–12 | 8 |
| Map | Regional zoom offset | slider −1 to −4 | −2 |
| Map | Base map style | select: Dark, Light, Voyager, Satellite, Terrain (key) | Dark |
| Map | Map center offset (keeps pin off-center so incoming weather shows) | select: center, upwind | center |
| Map | Show roads/labels layer above radar | bool | on |
| Radar | Past loop length | select: 30, 60, 90, 120 min | 120 |
| Radar | Future radar source | select: Auto, HRRR (US), Rainbow.ai, LibreWXR, Off | Auto (HRRR in US, Rainbow if key, else off) |
| Radar | Future length | select: 1, 2, 4, 6, 12, 18 h | 2 h |
| Radar | Color scheme | select: NWS classic, Precip type (REFP), Universal Blue | NWS classic |
| Radar | Radar opacity | slider 40–100% | 75% |
| Radar | Frame rate | slider 2–10 fps | 5 |
| Radar | Pause on NOW frame | slider 0–3 s | 1.5 s |
| Radar | Smooth frames (crossfade) | bool | on |
| Radar | Warning polygons | bool | on (US) |
| Scenes | Per-scene enable, duration, order | bool + slider + order list (×17) | see Views |
| Scenes | Shuffle after radar | bool | off |
| Scenes | Transition | select: crossfade, slide, cut | crossfade |
| Overlay | Clock, date, location, data age, mini conditions, legend | bool each | on |
| Overlay | Clock format | 12 h / 24 h | 12 h |
| Alerts | Alert banner | select: Warnings only, + Watches, + Advisories, Off | Warnings + Watches |
| Alerts | Promote warning scene to front | bool | on |
| Units | Temperature, wind, pressure, precip, distance | select each | °F, mph, inHg, in, mi |
| Fishing | Factor weights | sliders summing to 100 | see Views |
| Fishing | Target species preset | select: General, Bass, Walleye, Trout, Panfish, Saltwater | General |
| Display | OLED protection (pixel shift, rotating layout) | bool | off |
| Display | Interactive mode | bool | off |
| Data | Rainbow.ai API key | text (hidden) | empty |
| Data | Map provider API key | text (hidden) | empty |
| Data | LibreWXR base URL | text | empty |
| Data | NWS contact email (User-Agent) | text | empty, prompt when US |
| Data | Refresh while screensaver is off | select: Never, Hourly, Smart | Smart |
| Data | Monthly Rainbow tile cap | number | 27,000 |
| Advanced | Performance profile | select: Low (Pi), Balanced, High (4K) | auto-detect |
| Advanced | Cache size limit | slider 100 MB–2 GB | 500 MB |
| Advanced | Debug overlay (fps, cache hits, request counts) | bool | off |
| Advanced | Clear cache / Test all sources | action | n/a |

**Smart refresh**: the background service keeps radar frames warm only in the 30 minutes before Kodi's screensaver timeout would normally fire (it watches idle time via `xbmc.getGlobalIdleTime()`), so the loop is ready the moment the screensaver starts without fetching all day.

## Rendering, performance and errors

All heavy work happens off-screen in the background service; the screensaver window only flips between finished full-screen images, which is the one thing Kodi's Python GUI does fast on every device.

### Rendering model

- **Pre-composited frames.** For each radar frame the compositor stacks base map + radar tiles + labels layer + warning polygons + pin into one image at the output resolution (1920×1080, or 3840×2160 on the High profile) using Pillow, and writes it as JPEG (quality 88) to the frame store. Base map and labels are composited once per location/zoom and reused.
- **Frame playback.** The window holds a fixed stack of `ControlImage` controls, one per frame (up to 36). Playback toggles visibility rather than calling `setImage`, so textures load once and the loop runs smoothly even on a Pi 4. A new frame replaces the oldest control's image during the NOW pause, never mid-loop.
- **Crossfade between frames** uses Kodi's built-in `<animation effect="fade">` on visibility, 120 ms, so radar echoes move instead of jumping.
- **Graph scenes** (hourly, climate, fishing strip, tide curve) are drawn with Pillow's `ImageDraw` into PNGs from a small in-house chart module: lines, bars, bands, labels. No matplotlib (too large for low-end boxes).
- **Text-heavy scenes** (current conditions, daily cards, alerts) use skin XML labels with Kodi fonts so text stays crisp at any resolution; values come from window properties set by the scene player.
- **Fonts and icons**: a bundled weather icon set (e.g. Meteocons, MIT) and the skin's fonts; all sizes defined for a 1080p coordinate space, which Kodi scales to 4K.

### Performance targets

| Metric | Low (Pi 4) | Balanced | High (4K) |
| --- | --- | --- | --- |
| Output resolution | 1280×720 | 1920×1080 | 3840×2160 |
| Max radar frames in loop | 24 | 36 | 36 |
| Composite one frame | < 400 ms | < 200 ms | < 600 ms |
| Screensaver start to first frame | < 1 s (cached) | < 1 s | < 1.5 s |
| RAM held by screensaver | < 120 MB | < 200 MB | < 400 MB |
| Background CPU while Kodi plays video | 0 (service sleeps during playback) | 0 | 0 |

The service checks `xbmc.Player().isPlaying()` and pauses all fetching and compositing during playback, so the screensaver can never cost a dropped frame in a movie.

### Caching

- **Tile cache** on disk under the add-on's profile folder, keyed `source/z/x/y/timestamp`; base-map tiles never expire, radar tiles expire after 3 h, HRRR after the next run lands.
- **JSON cache** in SQLite: each fetch stores body, fetched-at, and expiry. Panels read only from the cache, never from the network directly.
- **Climate normals** computed once per location from 30 years of Open-Meteo archive data (1991–2020) and stored as 366 rows of mean/p10/p90/max/min; re-computed only when the location changes.
- **LRU eviction** to the user's cache size limit, oldest radar frames first, base maps last.

### Error handling

- Every source has a status: OK, Stale (served from cache, age shown), Down. Status is shown in the debug overlay and in Settings → Test all sources.
- A scene whose data is Down and has no cache is **skipped silently** in the playlist; the screensaver never shows an error dialog.
- Radar loop with missing frames: play what exists; if future frames are missing, the timeline bar shows FUTURE greyed out with "model update pending".
- HTTP 429 or a quota near its cap: exponential back-off (1 min doubling to 60 min) and fall back down the source chain (Rainbow → HRRR → past-only).
- No network at all: run entirely from cache with a small "offline, data from 7:40 PM" chip.
- All network calls use a 10 s timeout and a SkyWatch User-Agent with the user's contact email for NWS.

## Milestones, testing and open questions

Build in five milestones, each ending in something you can run on the TV.

1. **M1 — Radar MVP.** Add-on skeleton, settings with location search, base map + IEM past radar loop, frame stack playback, clock overlay, attribution. Done when a 2 h loop plays smoothly on a Pi 4 at 720p and a desktop at 1080p.
2. **M2 — Future radar.** HRRR future frames with PAST/NOW/FUTURE timeline, source chain (Rainbow key, LibreWXR URL), request budget manager, regional scene with NWS warning polygons, alert banner.
3. **M3 — Forecast scenes.** Current conditions, next 2 hours, hourly graph, daily cards, scene playlist editor, transitions.
4. **M4 — Climate and fishing.** Normals computation, climate and year-in-temperature scenes, solunar engine, fishing score with water-body picker, USGS and CO-OPS, sun and moon, tides.
5. **M5 — Polish.** Satellite scene, air quality, forecast discussion, ambient clock, OLED protection, 4K profile, translations (`strings.po`), submission to the official Kodi repo (checker passes, licenses for icons and fonts).

### Testing

- **Unit tests** (pytest, outside Kodi, with a stubbed `xbmc` module): tile math, solunar times against published tables, fishing score, normals computation, cache expiry, source fallback chain, budget manager.
- **Recorded fixtures** for every API so tests and UI work run offline and do not hit free services.
- **Device matrix**: Raspberry Pi 4 and 5 (LibreELEC), Nvidia Shield (Android), Windows and Linux desktop, one 4K TV; Kodi 21.3 Omega (current stable) and 22 Piers beta.
- **Soak test**: 12 h screensaver run checking memory stays flat, cache stays under its limit and request counts match the budget.
- **Failure drills**: pull the network, return 429s, corrupt a cached tile, set a location outside the US, outside HRRR coverage, and in the middle of the ocean.

### Open questions

- Single home location, or a rotating list of saved locations (cabin, lake, family)? The design supports a list; v1 assumes one home plus one fishing spot.
- Should HRRR future frames blend into the observed loop with a visible seam (honest) or crossfade (prettier)? Default is a visible "MODEL" tag on future frames.
- Exact current USGS endpoint and the IEM tile layer names should be confirmed at the start of M1; both services publish change notes.

## Sources

- [RainViewer API transition FAQ](https://rainviewer.com/api/transition-faq.html) and [RainViewer API terms](https://rainviewer.com/api.html)
- [Rainbow.ai developer portal](https://developer.rainbow.ai/)
- [IEM HRRR forecast reflectivity tiles](https://mesonet.agron.iastate.edu/GIS/model.phtml)
- [LibreWXR](https://github.com/JoshuaKimsey/LibreWXR)
- [Open-Meteo](https://open-meteo.com/)
- [Kodi screensaver add-on how-to](https://kodi.wiki/view/HOW-TO:Screensaver_addon) and [Kodi release history](https://kodi.wiki/view/Releases)
- [Kodi 22 Piers Beta 1 announcement](https://kodi.tv/article/kodi-22-piers-beta-1)

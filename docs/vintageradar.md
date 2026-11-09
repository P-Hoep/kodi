# Vintage Radar

`screensaver.vintageradar.gl` v1.0.0, `screensaver.vintageradar.gl.armv7` v1.0.0,
`script.vintageradar` v1.0.0

An old radar scope for Kodi, showing the aircraft flying over you right now. A green (or amber,
ice-blue or white) phosphor disc with range rings, a compass rose, a sweeping beam and glowing
blips; a nearest-first contact list; and a spotlight card that rotates through the contacts showing
everything their transponder reports. The screensaver draws it in OpenGL; the app puts the same
scope in a window you can drive with the remote.

The idea is the radar instrument, not the flight map: the beam sweeps, a contact glides on
dead-reckoned position between feeds, and its last three sweep echoes fade behind it. Labels on the
scope stay short; the card and the app's contact sheet carry the detail.

The native screensavers need Kodi 21 (Omega); the Python app runs on Kodi 20 (Nexus) or later.

---

## Contents

- [Installing](#installing)
- [Which add-on do I need?](#which-add-on-do-i-need)
- [The screensaver](#the-screensaver)
- [The app](#the-app)
- [Settings reference](#settings-reference)
- [Data and how it is used](#data-and-how-it-is-used)
- [Project layout](#project-layout)
- [Development and testing](#development-and-testing)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)

---

## Installing

The add-ons are in the P-Hoep repository (see the [root README](../README.md#install-from-the-repository)).
Install **Vintage Radar (OpenGL)** or its 32-bit Android build, and **Vintage Radar** (the app) if
you want the interactive window or the **Find a place by name** button in the settings.

1. **Settings → Add-ons → Install from repository → P-Hoep Add-ons.**
2. Screensaver: **Look and feel → Screensaver → Vintage Radar (OpenGL)**.
3. App: **Program add-ons → Vintage Radar**.
4. **Settings → Interface → Screensaver → Screensaver mode → Vintage Radar (OpenGL)**.
5. Open the add-on's settings and set your latitude and longitude, or type a place into **Find a
   place by name**.

The app is also in **Program add-ons**; launch it from there, or make a home-screen shortcut.

## Which add-on do I need?

| Device | Install |
|---|---|
| macOS, Intel or Apple Silicon | **Vintage Radar (OpenGL)** (universal `.dylib`) |
| 64-bit Android Kodi (for example Nvidia Shield, many recent Android TV boxes) | **Vintage Radar (OpenGL)** (arm64-v8a `.so`) |
| 32-bit Android Kodi: Fire TV, many Google TV boxes, Chromecast with Google TV | **Vintage Radar (OpenGL, 32-bit Android)** (`screensaver.vintageradar.gl.armv7`, armeabi-v7a `.so`) |

A 64-bit library cannot load in 32-bit Kodi and vice versa, so the 32-bit build is a separate add-on
with its own id and name. Its settings are separate too; **Find a place by name** writes the
coordinates to every Vintage Radar add-on that is installed, so they normally stay in step.

## The screensaver

The header shows the place name, the local clock and date, the range, and the age of the feed. The
footer shows the range in both units, the sweep position, the contacts in range and tracked, and
the source.

**The scope** has range rings with distance labels, a compass ring with a degree label every 30°
and ticks every 10°, and a rotating sweep wedge. Aircraft are drawn as aircraft-shaped blips with a
leader line and a short label; the label content is a setting. Up to three past sweep echoes trail
each contact. Ground traffic is off by default and has its own filter; the lowest-altitude setting
is a second filter.

**The contact list** is ordered nearest first, with callsign, type, altitude, ground speed,
distance and bearing. The spotlight row is highlighted and scrolled into view as the spotlight
rotates, and the list pages back after *List follow* seconds.

**The spotlight card** rotates through every contact every *Spotlight hold* seconds. It shows the
callsign, registration, ICAO type, category, hex, squawk, altitude, ground speed, vertical rate,
distance, track, IAS, TAS, Mach, bearing, position, navigation altitude and QNH, geometric altitude,
NACp/NACv/SIL/NIC, RSSI, message count and rate, ADS-B version, and the fix source. An emergency
squawk is called out by name; military, alert and SPI flags are summarised.

Turning off **Show the contact list and spotlight panel** gives the full-screen scope with the disc
centred and slightly larger. The screensaver is otherwise hands-off: there is nothing to click, and
any key or remote press dismisses it as usual.

## The app

The app is the same scope in a 1920×1080 window. It adds interactivity:

| Input | Action |
|---|---|
| Left / Right | Step the spotlight through the contacts |
| Select (Enter) | Open the full contact sheet for the spotlighted contact |
| Click a blip, its label or a list row | Open that contact's sheet |
| Page Up / Page Down | Turn the contact list |
| Back (or right-click) | Close the sheet; again leaves the scope |
| Menu | Open the settings |

The contact sheet is a three-column page with every field the model knows: callsign, registration,
type, category, hex, squawk, source, flags, latitude, longitude, distance, bearing, first and last
seen, altitude, geometric altitude, ground speed, track, magnetic and true heading, IAS, TAS, Mach,
barometric and geometric vertical rate, navigation altitude, QNH and heading, emergency state,
NACp, NACv, SIL, NIC, RC, message count, ADS-B version, RSSI, seen, seen position, on-ground state,
MLAT and TIS-B. It closes with its corner button or Back.

Stepping the spotlight pins it until the sheet is closed or the scope is left; otherwise the
spotlight rotates as in the screensaver. Settings are re-read every two seconds while the window is
open, so changes apply live without restarting.

## Settings reference

The app and both screensaver builds share one table in
[`tools/make_settings_vintageradar.py`](../tools/make_settings_vintageradar.py), which generates the
`settings.xml` and strings for all three add-ons and the app's `defaults.py`. The values below are
the defaults; the settings dialog has the same labels.

| Category | Setting | Default | Meaning |
|---|---|---|---|
| Location | Place name shown on screen | Home | Header text; cosmetic only |
| Location | Find a place by name... | — | Opens a search box (Photon), or takes `lat, lon` directly, and writes the coordinates to every installed Vintage Radar add-on. Needs the app installed |
| Location | Latitude | 44.9031331 | Decimal degrees, south negative |
| Location | Longitude | -93.3096136 | Decimal degrees, west negative |
| Scope | Range of the scope (km) | 60 | 5-400 km radius |
| Scope | Units | Aviation | Metric (km, m, km/h) or aviation (nm, ft, kt) |
| Scope | How often to fetch aircraft | 20 s | 10-120 s |
| Scope | One sweep of the beam | 6 s | 2-12 s |
| Scope | Show aircraft and vehicles on the ground | off | Includes surface contacts |
| Scope | Lowest altitude to show | All altitudes | All / 1,000 / 5,000 / 10,000 ft and above |
| Contacts | Label the contacts on the scope | on | |
| Contacts | What a scope label shows | Callsign + altitude and speed | Callsign only / + altitude and speed / + type and altitude |
| Contacts | Trail of past sweep echoes | on | Up to three echoes per contact |
| Contacts | Most contacts to track | 40 | 5-200 |
| Information panel | Show the contact list and spotlight panel | on | Off gives the full-screen scope |
| Information panel | How long each contact holds the spotlight | 10 s | 4-60 s |
| Information panel | How long the list follows the spotlight before paging back | 8 s | 3-60 s |
| Look | Phosphor | P1 green | P1 green / P3 amber / P11 ice blue / white |
| Look | CRT scanlines and vignette | on | |
| Look | Dim the picture (%) | 0 | 0-40 % |
| Look | Detail | Normal | Low (for slow boxes) / Normal / High |

Moving the scope or changing the range or refresh interval drops the contacts from the old place
and starts a new feed. Changing the sweep restarts the beam from north. Kodi caches an add-on's
strings: if the settings labels are blank, restart Kodi.

## Data and how it is used

The primary feed is adsb.lol's point query,
`https://api.adsb.lol/v2/point/<lat>/<lon>/<radius-nm>`, with the radius derived from the range plus
a margin for dead reckoning. It needs no account or key. If it fails, the app falls back to the
OpenSky Network's `https://opensky-network.org/api/states/all?lamin=...` bounding box, which is
anonymous and rate-limited; the footer and the card name the active source. If both fail, the last
contacts stay on the scope and the footer shows how old the feed is.

From the JSON the model reads ADS-B and Mode S fields: callsign, registration, type, category,
squawk, altitude (barometric and geometric), ground speed, track, magnetic and true heading, IAS,
TAS, Mach, vertical rates, navigation altitude/QNH/heading, position, seen/seen_pos, RSSI, NACp,
NACv, SIL, NIC, RC, message count, ADS-B version and the military/alert/SPI flags. Ground aircraft
(`alt_baro: "ground"`) are handled separately. The fix source is derived from the ADS-B message
type: ADS-B, MLAT or TIS-B.

Filtering is by range, ground state and lowest altitude. Contacts are ordered nearest first. Between
feeds each contact is dead-reckoned at its reported ground speed and track; a contact missing from a
new feed is kept briefly and then dropped. Echoes are added when the sweep passes a contact's
bearing and fade out, so the scope shows how the picture built up.

Aircraft data comes from the volunteer-run adsb.lol and OpenSky Network APIs and is used as-is. It
is not for navigation or flight safety: feeds are incomplete, positions are delayed and some
aircraft do not transmit ADS-B at all. adsb.lol data is ODbL; see the providers' terms.

## Project layout

| Project | What it is |
|---|---|
| [`screensaver.vintageradar.gl`](../screensaver.vintageradar.gl/README.md) | The native OpenGL screensaver: C++ model and renderer, Kodi wrapper, GLFW test window, C++ tests |
| `screensaver.vintageradar.gl.armv7` | The same sources built for 32-bit Android under its own add-on id |
| [`script.vintageradar`](../script.vintageradar/README.md) | The pure-Python app: window, controls, main loop, PNG text renderer, place search, Python tests |
| `tools/make_settings_vintageradar.py` | The shared settings table and generated files |
| `tools/make_vintageradar_media.py` | Icons, fanart, radar art and font atlases (Pillow) |

The screensaver's source layout is in its README. The app's `ui.py` builds every control at
runtime; `app.py` owns the model, feed, text cadence, input and settings reload; `radar_core.py` is
Kodi-free and holds the geometry, model and formatting shared in spirit with the C++ `radar_core`.
Text in the app is rendered to PNGs by `fontdraw.py` because a WindowXML skin cannot load an
add-on's own TTF.

## Development and testing

Native screensaver, including the GLFW harness and C++ tests:

```sh
cd screensaver.vintageradar.gl
cmake -S . -B build && cmake --build build && ctest --test-dir build
./build/radar_glfw --live
./build/radar_glfw --fixture tests/fixtures/adsblol.json
```

The Kodi add-on builds need the Kodi 21 dev-kit headers; the macOS and Android build commands are
in the [screensaver README](../screensaver.vintageradar.gl/README.md).

Python app tests (no Kodi, no network):

```sh
python3 -m unittest tests.test_vintageradar -v
```

Live testing against a local Kodi and screenshots: see
[`tools/kodi.py`](../tools/kodi.py) and the [development guide](development.md). Screenshots of the
native screensaver are best taken with Kodi's own `TakeScreenshot`; on macOS the OpenGL screensaver
builds use the 3.2 core profile (`radar_glfw_core` mirrors it).

## Troubleshooting

**The screensaver is selected but nothing happens.** Kodi only starts the screensaver after its idle
timer. Pressing a key or moving the mouse dismisses it; taking a screenshot can also wake it.

**Labels are blank in the settings dialog.** Kodi has not reloaded the add-on's strings. Restart
Kodi.

**"This add-on is incompatible" or it fails to load on Fire TV.** Install the 32-bit Android
(`armv7`) build; the 64-bit library cannot load in 32-bit Kodi.

**The scope is empty.** Check the coordinates and range, the lowest-altitude and ground filters, and
the footer's feed age and source. The feed needs internet access; adsb.lol can be briefly down and
OpenSky may rate-limit anonymous requests. The address must resolve, so Kodi's DNS must be working.

**It is slow on an old box.** Set **Detail → Low**, turn off **CRT**, and reduce the range or the
number of contacts. In the app, turning off the information panel also removes a lot of text
updates.

**The app shows the wrong place after I changed the screensaver's settings.** The 32-bit and 64-bit
screensavers and the app keep separate setting values under separate add-on ids. Use **Find a place
by name** (which writes to all of them) or set each add-on's coordinates.

## Known limitations

- Native builds target Kodi 21 (Omega). Other Kodi versions need a rebuild against their add-on
  API, and the OpenGL path is macOS and Android only (Kodi on Windows uses ANGLE/GLES).
- The feeds are community receivers: coverage varies, positions are delayed, and some aircraft
  never appear. Military and low-level traffic is especially patchy.
- OpenSky's anonymous API is rate-limited; adsb.lol is the primary source for that reason.
- The list shows twelve rows per page; with more contacts use Page Up / Page Down (native panel)
  or the app's paging.
- Labels avoid each other but a very crowded scope can still tuck a label near its neighbour; the
  spotlight card is the reliable way to read a contact.

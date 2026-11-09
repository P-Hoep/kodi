# Vintage Radar (OpenGL)

A Kodi screensaver that turns the idle TV into an old radar scope: a green (or amber, ice-blue or
white) phosphor disc with range rings, a compass rose, a sweeping beam and glowing aircraft blips.
It shows the aircraft actually overhead right now, fetched live from
[adsb.lol](https://adsb.lol/) with the [OpenSky Network](https://opensky-network.org/) as a
fallback, centred on the place and range you choose.

It is drawn entirely with OpenGL, so the sweep stays smooth at full screen. A contact does not
jump when a new position arrives: it is dead-reckoned between updates at its reported ground speed
and track, and each blip keeps three past sweep echoes, so the scope looks like a radar rather than
a map. The right side carries a nearest-first contact list and a spotlight card that rotates through
the contacts showing everything the transponder reports; the radar labels stay short.

This add-on is a native Kodi add-on (C++ / OpenGL 2.1, 3.2 core and OpenGL ES 2.0). There are two
Kodi add-ons:

- **Vintage Radar (OpenGL)** — macOS (universal, Intel and Apple Silicon) and 64-bit Android.
- **Vintage Radar (OpenGL, 32-bit Android)** — for 32-bit Android Kodi, as on Fire TV and many
  Google TV boxes. Its id is `screensaver.vintageradar.gl.armv7`, because the 64-bit library
  cannot load in 32-bit Kodi.

The Python companion, [script.vintageradar](../script.vintageradar/README.md), puts the same scope
in a window you can drive with the remote.

## What is on screen

- **The scope:** concentric range rings with distance labels, a compass ring with degree ticks
  every 10° and labels every 30°, a rotating sweep wedge with a fading afterglow, an aircraft-shaped
  blip with a leader line and a short label, and up to three echo trails behind each contact.
- **The contact list:** nearest first, with callsign, type, altitude, ground speed, distance and
  bearing. The spotlight row is highlighted, and the list follows it and pages back as the
  spotlight rotates.
- **The spotlight card:** callsign, registration, ICAO type, category, hex, squawk, altitude and
  geometric altitude, ground speed, track, magnetic and true heading, IAS, TAS, Mach, vertical
  rates, navigation altitude and QNH, position, distance, bearing, NACp/NACv/SIL/NIC, RSSI, message
  count and rate, ADS-B version, military/alert/SPI flags, and whether the fix came from ADS-B,
  MLAT or TIS-B.
- **The header and footer:** place name, local clock and date, range, sweep position, number of
  contacts in range and tracked, feed source and age.
- **The look:** four phosphors, CRT scanlines and vignette, dimming, and a detail setting for slow
  boxes.

When the contact list is turned off the scope uses the whole screen. An emergency squawk
(7500/7600/7700) is called out in the emergency field rather than hidden in the flags.

## Settings

`tools/make_settings_vintageradar.py` writes `resources/settings.xml`, the strings and the Python
app's `defaults.py` from one table, so the screensaver, the app and the tests cannot disagree.
Run it again after changing the table:

```sh
python3 tools/make_settings_vintageradar.py
python3 tools/make_settings_vintageradar.py screensaver.vintageradar.gl.armv7 \
    'Vintage Radar (OpenGL, 32-bit Android)'
```

| Category | Setting | Default | Meaning |
|---|---|---|---|
| Location | Place name | Home | The name shown in the header |
| Location | Find a place by name | — | Searches Photon (or takes "lat, lon") and writes the coordinates to every installed Vintage Radar add-on |
| Location | Latitude / Longitude | 44.9031, -93.3096 | The centre of the scope, decimal degrees, south and west negative |
| Scope | Range | 60 km | Radius of the scope, 5-400 km |
| Scope | Units | Aviation | Metric (km, m, km/h) or aviation (nm, ft, kt) |
| Scope | Refresh | 20 s | How often the feed is fetched, 10-120 s |
| Scope | Sweep | 6 s | One revolution of the beam, 2-12 s |
| Scope | Ground traffic | off | Show aircraft and vehicles on the ground |
| Scope | Lowest altitude | all | All / 1,000 / 5,000 / 10,000 ft and above |
| Contacts | Labels | on | Label contacts on the scope |
| Contacts | Label detail | callsign + altitude and speed | Callsign only, + altitude and speed, or + type and altitude |
| Contacts | History | on | Trail of past sweep echoes |
| Contacts | Most contacts | 40 | Stop tracking beyond this many, 5-200 |
| Panel | Show panel | on | The contact list and spotlight card; off gives the full-screen scope |
| Panel | Spotlight hold | 10 s | How long each contact owns the spotlight, 4-60 s |
| Panel | List follow | 8 s | How long the list follows the spotlight before paging back |
| Look | Phosphor | P1 green | P1 green / P3 amber / P11 ice blue / white |
| Look | CRT | on | Scanlines and vignette |
| Look | Dim | 0 % | Darkens the whole picture, 0-40 % |
| Look | Detail | Normal | Low (slow boxes) / Normal / High |

The location action is implemented in the Python app, so `script.vintageradar` must be installed
for it to appear and work; the coordinates it writes are shared by every Vintage Radar add-on.

## Build

The screensaver has no third-party dependencies beyond OpenGL and Kodi's add-on headers. A local
Kodi 21 tree provides the dev kit at `xbmc/addons/kodi-dev-kit/include`.

macOS (universal):

```sh
cmake -S . -B build-macos-arm64 -DCMAKE_OSX_ARCHITECTURES=arm64 \
      -DRADAR_HARNESS=OFF -DRADAR_KODI=ON \
      -DKODI_DEVKIT_INCLUDE=/path/to/xbmc/addons/kodi-dev-kit/include
cmake --build build-macos-arm64 -j8
cmake -S . -B build-macos-x86_64 -DCMAKE_OSX_ARCHITECTURES=x86_64 \
      -DRADAR_HARNESS=OFF -DRADAR_KODI=ON \
      -DKODI_DEVKIT_INCLUDE=/path/to/xbmc/addons/kodi-dev-kit/include
cmake --build build-macos-x86_64 -j8
lipo -create -output screensaver.vintageradar.gl.dylib \
     build-macos-arm64/screensaver.vintageradar.gl.dylib \
     build-macos-x86_64/screensaver.vintageradar.gl.dylib
codesign --force --sign - screensaver.vintageradar.gl.dylib
```

Android, using the NDK toolchain (64-bit shown; use `armeabi-v7a` and the `.armv7` add-on folder
for the 32-bit build):

```sh
NDK=...   # the Android NDK path
cmake -S . -B build-android64 \
      -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
      -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static \
      -DRADAR_HARNESS=OFF -DRADAR_KODI=ON \
      -DKODI_DEVKIT_INCLUDE=/path/to/xbmc/addons/kodi-dev-kit/include
cmake --build build-android64 -j8
cp build-android64/screensaver.vintageradar.gl.so screensaver.vintageradar.gl.so
```

## Test window and tests

With GLFW installed (`brew install glfw`) the same renderer builds as a plain window that needs no
Kodi:

```sh
cmake -S . -B build && cmake --build build && ctest --test-dir build
./build/radar_glfw --live                       # live data
./build/radar_glfw --fixture tests/fixtures/adsblol.json   # offline
./build/radar_glfw_core --live                  # the 3.2 core profile Kodi uses on macOS
```

The harness takes `--lat --lon --range --units --sweep --refresh --theme --quality
--max-contacts --detail-seconds --label-detail --min-altitude --show-ground --no-labels
--no-history --no-panel --no-crt --dim --fixture --live --no-fetch --select HEX --page --step
--width --height-px --shot out.ppm --shot-after S --run-for S`, so a layout can be checked without
Kodi.

`ctest` runs `tests/test_radar.cpp` against the JSON fixtures in `tests/fixtures`: distance and
bearing, destination and east/north conversion, ADS-B and OpenSky parsing, filtering, ordering,
spotlight rotation, echoes, and formatting. The Python app's equivalent tests are in the repository's `tests/test_vintageradar.py`.

## Source layout

| Part | File | Kodi / GL needed |
|---|---|---|
| Geometry, aircraft model, ordering, echoes, formatting | `src/radar_core.*` | no |
| Feed URLs, JSON parsing, background fetch | `src/radar_feed.*` | no |
| Renderer: disc, rings, sweep, blips, labels, panel, CRT | `src/radar_app.*` | GL 2.1 / 3.2 core / GLES 2.0 |
| Kodi wrapper (`CInstanceScreensaver`, settings, entry point) | `src/kodi_radar.cpp` | kodi-addon-dev-kit |
| Test window | `src/main_radar_glfw.cpp` | GLFW |
| Tests and fixtures | `tests/` | no |

## Data and licence

Aircraft data comes from the volunteer-run adsb.lol and OpenSky Network APIs and is used as-is. It
is not for navigation or flight safety. adsb.lol data is ODbL; see the providers' terms.

The code is MIT (see `LICENSE.txt`). The typeface is [Doto](https://fonts.google.com/specimen/Doto)
under the SIL Open Font License 1.1 (`resources/media/fonts/Doto-OFL.txt`); it is baked into the
texture atlases `font_*.png` with `font_*.json` metrics.

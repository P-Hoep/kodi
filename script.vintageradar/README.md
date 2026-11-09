# Vintage Radar (app)

A Kodi program add-on that puts the [Vintage Radar](../docs/vintageradar.md) scope in a window
you can drive with the remote. It shows the aircraft actually overhead right now, fetched live from
[adsb.lol](https://adsb.lol/) with the [OpenSky Network](https://opensky-network.org/) as a
fallback, centred on the place and range you choose.

The same phosphor disc, range rings, compass rose, sweeping beam, echoing blips and short scope
labels as the screensaver, plus a nearest-first contact list and a spotlight card. Clicking a
contact, a list row or a blip (or pointing the spotlight at it and pressing Select) opens the full
contact sheet: every field the transponder reports, laid out in three columns.

The app is pure Python and runs on Kodi 20 (Nexus) or later. The companion screensaver puts the
same scope on the idle TV. Both are thin front-ends over the shared library
[`script.module.vintageradar`](../script.module.vintageradar), which Kodi installs with them and
which holds the model, window, media and settings defaults.

## Controls

| Input | Action |
|---|---|
| Left / Right | Step the spotlight through the contacts |
| Select (Enter) | Open the full contact sheet for the spotlighted contact |
| Click a blip, a label or a list row | Open that contact's sheet |
| Page Up / Page Down | Turn the contact list |
| Back (or right-click) | Close the sheet; again leaves the scope |
| Menu | Open the settings |

The sheet has a close button in its corner. Stepping the spotlight pins it until you close the
sheet or leave the scope; otherwise the spotlight rotates on its own every *Spotlight hold* seconds
and the list follows it for *List follow* seconds before paging back.

## The window

The window is the library's `ui.Scene`, the same one the screensaver shows. Kodi's WindowXML skins
cannot use an add-on's own font unless the active skin declares it, so every string is drawn into a
PNG by `fontdraw` and shown through a `ControlImage`. `ui.py` builds all the controls at runtime:
the radar art, panel frames, a pool of blips and echo images, twelve list rows, the spotlight card
and the full contact sheet. The main loop only updates positions, images and colours.

| Part | File |
|---|---|
| App entry point | `default.py`, `resources/lib/app.py` |
| Main loop: model cadence, feed pump, input, settings reload | `script.module.vintageradar/lib/vintageradar/session.py` |
| Window, controls, layout, labels, contact sheet | `script.module.vintageradar/lib/vintageradar/ui.py` |
| Geometry, aircraft model, ordering, spotlight, echoes, formatting | `script.module.vintageradar/lib/vintageradar/radar_core.py` |
| Feed URLs, JSON parsing, background fetch on a thread | `script.module.vintageradar/lib/vintageradar/radar_feed.py` |
| Settings and generated `defaults.py` | `script.module.vintageradar/lib/vintageradar/config.py`, `defaults.py` |
| Text rendering: font atlases to PNG | `script.module.vintageradar/lib/vintageradar/fontdraw.py`, `pngcodec.py` |
| Phosphor palettes | `script.module.vintageradar/lib/vintageradar/theme.py` |
| HTTP and the place search | `script.module.vintageradar/lib/vintageradar/net.py` |
| The "Find a place by name" action | `script.module.vintageradar/lib/vintageradar/setup.py` |
| Window XML, generated media, fonts | `script.module.vintageradar/resources/skins/`, `resources/media/` |
| Offline tests | `../tests/test_vintageradar.py` |

The text images go in a per-session directory under `special://temp/vintageradar/` (keyed by process
id and start time), so the app and the screensaver never overwrite each other. Directories older
than a day are removed at start.

## Settings

The app and the screensaver share one settings table in
[`tools/make_settings_vintageradar.py`](../tools/make_settings_vintageradar.py), which generates
each add-on's `resources/settings.xml` and strings, plus the library's `defaults.py`. Run it after
changing the table:

```sh
python3 tools/make_settings_vintageradar.py
```

| Category | Setting | Default | Meaning |
|---|---|---|---|
| Location | Place name | Home | The name shown in the header |
| Location | Find a place by name | — | Searches Photon (or takes "lat, lon") and writes the coordinates to both add-ons |
| Location | Latitude / Longitude | 44.9031, -93.3096 | The centre of the scope |
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

Settings are re-read every two seconds while the window is open, so changes take effect live. Moving
the scope or changing the range or refresh interval drops the contacts from the old place and starts
a new feed; changing the sweep restarts the beam.

If the settings labels show up blank in Kodi, restart Kodi: it caches an add-on's strings until it
reloads them.

## Data

The feed is adsb.lol's `/v2/point/<lat>/<lon>/<radius>` endpoint, with a radius in nautical miles
derived from the range and a margin for dead reckoning. If adsb.lol fails, the add-on tries the
OpenSky `/api/states/all` bounding box and labels the source `OpenSky`; if both fail it keeps the
last contacts and shows the feed age. The network request runs on a background thread and only the
result crosses back to the Kodi thread.

Aircraft are filtered by range, ground state and the lowest-altitude setting, then ordered nearest
first. Between updates every contact is dead-reckoned along its reported ground speed and track, and
its echo trail is extended whenever the sweep passes its bearing. A contact that stops being
reported is held briefly and then dropped.

Aircraft data comes from the volunteer-run adsb.lol and OpenSky Network APIs and is used as-is. It
is not for navigation or flight safety. adsb.lol data is ODbL; see the providers' terms.

The add-on code is MIT licensed. The typeface is [Doto](https://fonts.google.com/specimen/Doto)
under the SIL Open Font License 1.1, baked into the texture atlases under
`script.module.vintageradar/resources/media/fonts`.

## Tests

The pure-Python modules need no Kodi and no network:

```sh
python3 -m unittest tests.test_vintageradar -v
```

The tests cover geometry, ADS-B and OpenSky parsing, filtering, ordering, the spotlight and
pinning, echo crossings, formatting, config defaults and stored values, the PNG codec, the theme,
and renderer cache protection.

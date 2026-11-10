# Ship Tracker Screensaver

`screensaver.shiptracker` v0.1.0

A Kodi screensaver that watches a box of water (or coast, or harbour) and shows the ships in it
right now. The left of the screen is NASA's Blue Marble satellite image of exactly that area; every
AIS-equipped vessel inside the box gets a small ship marker, coloured by type and turned to its
course. The right-hand panel lists the ships, six at a time, with their flag state, type, speed,
length and voyage status, and a slideshow underneath shows photographs of them where Wikimedia
Commons has one. Any key closes it.

It is pure Python 3 using only the standard library — no compiled code, no imaging library at run
time. Two external services are used: the [aisstream.io](https://aisstream.io/) WebSocket for live
positions, and NASA GIBS for the map image.

---

## Contents

- [Installing](#installing)
- [What the screen shows](#what-the-screen-shows)
- [Settings reference](#settings-reference)
- [How a ship gets on screen](#how-a-ship-gets-on-screen)
- [The map](#the-map)
- [Ship details and photos](#ship-details-and-photos)
- [The cache](#the-cache)
- [Data and terms](#data-and-terms)
- [Leaving the screensaver](#leaving-the-screensaver)
- [Project layout](#project-layout)
- [Development and testing](#development-and-testing)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)

---

## Installing

The add-on is in the P-Hoep repository (see the
[root README](../README.md#install-from-the-repository)). It needs Kodi 19 (Matrix) or later.

1. **Settings → Add-ons → Install from repository → P-Hoep Add-ons → Look and feel →
   Screensavers → Ship Tracker.**
2. Open the add-on's settings. Enter the **aisstream.io API key** (free: sign in at
   [aisstream.io](https://aisstream.io/) with GitHub, then copy the key from your account page)
   and set the four edges of the bounding box.
3. **Settings → Interface → Screensaver → Screensaver mode → Ship Tracker.**

The default box is Lake Superior:

| Setting | Default |
|---|---|
| South latitude | 46.3 |
| West longitude | −92.3 |
| North latitude | 49.1 |
| East longitude | −84.2 |
| Area name | Lake Superior |

The API key is stored in Kodi's add-on profile and is never bundled with the add-on or written to
the repository. Without a key the screen says so and the map still draws.

## What the screen shows

The list is the screen's spine; everything else describes the same ships.

```
+------------------------------------------------+-----------------------------+
|                                                | Lake Superior     4:58 PM  |
|                                                | 46.30–49.10°N · 92.30–84.20°W|
|                                                | ● AIS live · 9 vessels      |
|                  NASA Blue Marble              |-----------------------------|
|                                                | VESSELS · 1–6 OF 9          |
|          ▲   the tracked box, with a           | R/V LAKE EXPLORER II        |
|         ▮▮   marker for every ship             | United States · 0.0 kn · …  |
|                                                | R/V NEIL ARMSTRONG          |
|                                                | United States · 0.0 kn · …  |
|                                                | …                           |
|                                                |-----------------------------|
|                                                | [ photograph of the ship ]  |
|                                                | R/V NEIL ARMSTRONG          |
|                                                | Office of Naval Research    |
+------------------------------------------------+-----------------------------+
| AIS: aisstream.io  ·  Map: NASA Blue Marble                                  |
+------------------------------------------------------------------------------+
```

- **Map (left, 1400 × 1080).** The Blue Marble image of the tracked box, padded to fill the screen
  without stretching. Markers are top-down ship icons, rotated to the vessel's course or heading
  and tinted by type: cargo light blue, tanker amber, passenger pink, tug green, fishing orange,
  pleasure yellow, high-speed craft purple, military grey, everything else white. A ship without a
  course points north. At most 90 markers are drawn.
- **Header.** The area name (or the latitude range when the name is blank), the clock, the
  compass-style latitude/longitude range, and the live status line: `● AIS live · N vessels`, or
  `Connecting…`, `Listening for ships…`, `AIS connection lost — retrying`, `Showing last known
  positions` after three quiet minutes, or `No AIS key`.
- **Ship list.** Six rows per page, sorted by name. Each row is the name and one line of details:
  flag state, type, speed in knots, length, and either the destination (when it fits) or a short
  navigation status (`Moored`, `Under way`, `At anchor`…). Parts that do not fit are dropped whole
  rather than cut mid-word. A ship whose last position is more than ten minutes old adds `Last
  position N min ago`. Pages advance every 8 seconds when there are more than six ships.
- **Photo slideshow.** Under the list, a 3:2 frame cross-fades every **Seconds per ship photo**
  (8 by default) between photographs of the listed ships. The ship name sits below the frame, and
  the owner/operator/builder and build year (or the vessel class) under that when Wikidata knows
  them. A small `Wikimedia` credit is burnt into the bottom-right of each real photograph;
  while photos are being fetched the frame says `Loading ship photos…`, and when nothing is found,
  `No ship photos yet`. Images are cached on disk, so a later run reuses them.
- **Attribution.** The bottom-left of the map credits aisstream.io and NASA Blue Marble.

Every control is created from Python when the screensaver starts — Kodi has no layout file with
the rows, because the number of ships is not known in advance.

## Settings reference

**AIS stream**

| Setting | Default | What it does |
|---|---|---|
| aisstream.io API key | empty | The key from your aisstream.io account. Required for positions; the map works without it |
| Area name shown on screen | Lake Superior | The title in the panel. Blank falls back to the latitude range |
| South latitude | 46.3 | Southern edge of the box, −90 to 90 |
| West longitude | −92.3 | Western edge, −180 to 180 |
| North latitude | 49.1 | Northern edge, south of the south edge is rejected |
| East longitude | −84.2 | Eastern edge, west of the west edge is rejected |

The four edges are validated together. If any is not a number, the box is upside down, empty or out
of range, the whole box falls back to the Lake Superior default rather than silently subscribing to
a sliver. A box cannot cross the antimeridian: the west edge must be numerically smaller than the
east edge.

**Display**

| Setting | Default | Range | What it does |
|---|---|---|---|
| Keep a ship listed for (minutes) | 15 | 2–120 | How long after its last position a ship stays on screen and in the list |
| Seconds per ship photo | 8 | 3–30 | Slideshow interval |
| Lighten the map (percent) | 8 | 0–30 (2) | A white overlay over the Blue Marble; 0 is the raw image, 30 is noticeably brighter |
| Show a clock | on | | Time of day in the top-right corner |

**Data**

| Setting | Default | What it does |
|---|---|---|
| Look up ship details and photos on Wikipedia | on | Enables the Wikidata and Wikimedia Commons lookups. Off, the list still has AIS data (name, flag, type, speed) but no photos or owner |
| Clear cached ships, map and photos | action | Deletes the ship database, cached map images and downloaded photos, then confirms with a notification |
| Debug logging | off | Logs connection changes, lookups, photo downloads and layout decisions to `kodi.log` |

Settings are read once when the screensaver starts. Wake it and let it start again to pick up a
change.

## How a ship gets on screen

1. The tracker opens a TLS WebSocket to `stream.aisstream.io` and sends one subscription: your API
   key, the box as `[[south, west], [north, east]]`, and a filter for the position and static
   message types (Class A and Class B position reports, `ShipStaticData`, `StaticDataReport`).
2. Each message updates one ship in an in-memory fleet keyed by MMSI: position, speed over ground
   (SOG), course over ground (COG), true heading, navigation status, name, call sign, IMO, type,
   dimensions, destination, ETA and draught. AIS "not available" markers (SOG 102.3, COG 360,
   heading 511) are ignored rather than shown as real values.
3. The flag state is the first three digits of the MMSI (the Maritime Identification Digits).
   A ship with an unknown MID simply shows no country.
4. The fleet snapshot keeps ships whose last position is younger than **Keep a ship listed for**.
   They are sorted by name; the screen pages through them six at a time.
5. Positions are projected into the padded map window with a plate carrée projection, so a marker
   sits where the ship is relative to the Blue Marble image. Ships outside the padded window (only
   possible at the edge of the world) are clipped.
6. When the connection drops, the tracker reconnects with a 5-second backoff that doubles to 60
   seconds and re-sends the subscription. The screen keeps the last known ships and says `AIS
   connection lost — retrying`.

The public stream is shared and lossy; a ship that broadcasts rarely can take a while to appear.
The screensaver only listens — it never transmits, and it uses no other account.

## The map

The image is a WMS `GetMap` request to NASA GIBS for the `BlueMarble_ShadedRelief_Bathymetry`
layer, in `EPSG:4326`, rendered at exactly 1400 × 1080. The requested box is centred and then
widened or heightened as needed to fill a 1400 × 1080 frame at the middle latitude, with longitude
scaled by `1/cos(latitude)` so degrees of latitude and longitude cover the same distance on screen.
The original box always stays inside the returned window; near the poles or the date line the
window is slid inwards instead. The map is cached under a name derived from the full request URL, so
changing any edge produces a new image and leaves the old one to be pruned. When the download fails
and a cached image exists, the cached image is used; with no image at all the screen says `No map
image available`.

The `Lighten the map` setting is a white Kodi image over the map with an alpha proportional to the
percentage; it does not modify the cached JPEG.

## Ship details and photos

AIS carries the position and the voyage, but rarely the ship's story. When **Look up ship details
and photos on Wikipedia** is on, a single background worker looks each new ship up, politely, with
requests spaced half a second apart:

1. **Wikidata.** Search for an entity with property `P458` (IMO number), then `P587` (MMSI). The
   hit must actually carry the identifier, or it is rejected. One `wbgetentities` call fetches the
   labels, description, build year, length, beam, tonnage and the item-valued builder, operator,
   owner, home port and vessel class (their labels come from a second call). Images come from
   `P18`; the English Wikipedia article from the sitelink.
2. **Wikimedia Commons.** Search file namespace for `"IMO <number>"`, take up to six JPEG/PNG
   files, and use their 800-pixel thumbnails. Photos from Wikidata and Commons are merged and
   deduplicated by URL.

The merged profile is one JSON object per MMSI, stored with the **identifier signature** it was
built from (`imo:…|cs:…|mmsi:…`). The database decides whether to look a ship up again:

- signature unchanged and a profile was found → reuse it for 30 days;
- signature unchanged and nothing was found → retry after 7 days;
- a new IMO or call sign → look it up immediately.

The display filters photos against the ships currently in the fleet, so the slideshow only shows
photographs of ships that are on screen. Downloads are one at a time, capped at 8 MB each, written
to a temporary file and renamed into the photo cache. Failed downloads are remembered for the run
and tried again later; a successful one is never downloaded twice. The lookup worker respects a
Wikimedia rate-limit response by pausing for the requested time, and retries ordinary failures
after 60 seconds (up to 10 minutes after repeated failures).

If nothing is known about a ship, the row still shows its AIS details and the image frame says `No
ship photos yet`; `No detailed information yet` appears only when AIS has also sent nothing beyond
the position.

## The cache

Everything is kept in the add-on's profile folder:

| File | What it is |
|---|---|
| `ships.db` (+ `-wal`, `-shm`) | SQLite database with the `ships` and `profiles` tables |
| `map_<hash>.jpg` | One Blue Marble image per bounding box and size |
| `photos/photo_<hash>.<ext>` | Downloaded ship photographs |

`ships` holds the last known AIS state of every MMSI heard (`name`, `call_sign`, `imo`, position,
speed, course, heading, navigation status, destination, ETA, dimensions, timestamps). At start-up
the fleet is seeded from it, so the screen has something to show while the WebSocket reconnects; a
ship that only sends position reports keeps the name and dimensions it broadcast days ago.
Records older than 90 days are pruned.

`profiles` holds the merged Wikidata/Commons JSON and its identifier signature. Both tables are
written from the AIS and lookup threads under a lock, with WAL mode and batched commits. If the
database file is corrupt or half-written, it is moved aside to `ships.db.corrupt-<epoch>` and a
fresh one is created, rather than the screensaver failing to start. If the profile folder cannot be
used at all, the cache falls back to an in-memory database for that run.

**Clear cached ships, map and photos** removes `ships.db*`, all `map_*.jpg` files and the
`photo_*` files. The add-on itself is not touched.

## Data and terms

- **AIS positions** come from [aisstream.io](https://aisstream.io/), a free public aggregator. It
  needs an account and an API key, and is used only to read the stream. Follow its terms; it is not
  affiliated with this add-on.
- **Map imagery** is NASA's Blue Marble, served by NASA GIBS. It is in the public domain; credit is
  shown on screen.
- **Ship details and photographs** come from Wikidata (CC0) and Wikimedia Commons. Each photograph
  keeps its own licence, which is not bundled or copied with the add-on — the slideshow loads it
  from Commons and credits Wikimedia Commons on screen. The add-on code is MIT-licensed; see
  `LICENSE.txt`.
- No photo, map image or API key is shipped in the add-on. Only the generated ship icons, panel
  textures, icon and fanart are bundled.

## Leaving the screensaver

Any key, remote button, mouse move or touch wakes it. Kodi may also close the screensaver itself;
the add-on watches `System.ScreenSaverActive` and stops when Kodi says it is no longer active, so
it never leaves a window behind. On shutdown it stops the display thread first, then the lookup and
AIS threads (closing the WebSocket), commits and closes the database, and closes the window.

## Project layout

```
screensaver.shiptracker/
  addon.xml                     id, version, screensaver extension, metadata
  default.py                    entry point; `clear_cache` argument for the settings button
  icon.png, fanart.jpg          add-on artwork (generated)
  resources/
    settings.xml                GENERATED from resources/lib/config.py
    language/resource.language.en_gb/strings.po  GENERATED
    skins/Default/1080i/screensaver-shiptracker.xml  full-screen window
    media/                      map panel textures, placeholder, 16 ship icons (generated)
    lib/
      config.py                 settings table, strings, bounding box, map URL and projection
      ws.py                     minimal RFC 6455 WebSocket client (TLS, binary frames, ping/pong)
      ais.py                    AIS message decoding and the in-memory fleet
      tracker.py                AIS connection thread: subscribe, reconnect, write the cache
      sources.py                Wikidata/Commons lookup worker and profile cache policy
      store.py                  SQLite ship and profile tables
      mapimage.py               Blue Marble download and cache
      net.py                    small HTTP/JSON helper with a timeout and size cap
      ui.py                     the Kodi window, display loop and settings glue
  tools/make_settings_shiptracker.py   settings.xml + strings.po from config.py
  tools/make_shiptracker_media.py      icon, fanart, textures and ship icons (Pillow)
  tests/test_shiptracker.py            offline tests for everything above
```

The `resources/lib` modules except `ui.py` have no Kodi imports; the tests drive them directly.

## Development and testing

```bash
python3 tools/make_settings_shiptracker.py    # settings.xml + strings.po from config.py
python3 tools/make_shiptracker_media.py       # icon, fanart, textures, ship icons (Pillow)
python3 -m unittest tests.test_shiptracker    # offline: settings, geometry, AIS, WebSocket, DB
KODI_ADDON=screensaver.shiptracker python3 tools/kodi.py install   # symlink into local Kodi
KODI_ADDON=screensaver.shiptracker python3 tools/kodi.py select    # make it the screensaver
KODI_ADDON=screensaver.shiptracker python3 tools/kodi.py set api_key=… south_lat=46.3
KODI_ADDON=screensaver.shiptracker python3 tools/kodi.py run       # start it now
```

The tests use fake AIS messages, a fake WebSocket and fake lookup functions, so they need no
network and no key. For a live check, enter a key in the add-on's settings file (or through the
settings dialog), run it, and use `tools/kodi.py shot out.png` — or, because the EventServer
screenshot packet itself wakes the screensaver, run an in-Kodi script that calls
`ActivateScreensaver`, waits, and then `TakeScreenshot(path, sync)`.

After changing `strings.po`, restart Kodi: it caches an add-on's strings and the settings labels
show blank until it reloads them.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `No AIS key` | The API key setting is empty. Paste the key from your aisstream.io account |
| `Listening for ships…` for a long time | The stream is connected but this box has had no AIS traffic yet. Lake Superior is quiet; try a busy harbour or widen the box |
| A blank settings screen | Kodi caches the add-on's strings. Restart Kodi after installing or changing `strings.po` |
| `AIS connection lost — retrying` | The stream dropped or the host is unreachable. It reconnects automatically; check `kodi.log` with **Debug logging** on |
| No map, just `No map image available` | GIBS was unreachable and no image was cached. Check the network; the next run retries |
| Map shows the wrong place | Check the four edges. A west edge larger than the east edge, or a box crossing the antimeridian, falls back to Lake Superior |
| No photos | Wikimedia has no photograph for that IMO/MMSI, lookups are off, or the downloads are still running. With **Debug logging** the log names each failed download |
| Photos of ships that have left | The slideshow rebuilds its candidates every 10 seconds; old photos stay until the next successful download. If it persists, clear the cache |
| List stays empty with `● AIS live · 0 vessels` | The stream is healthy but no ship inside the box has reported a position yet |
| Add-on does not appear | Kodi 19+ is required, and the repository version must be installed — see the root README |

## Known limitations

- Only AIS-equipped ships appear. Small craft without a transponder are invisible, and a ship with
  a switched-off or faulty AIS never shows.
- AIS coverage depends on shore receivers. Some areas and some message types are sparse.
- The box cannot cross the antimeridian (west must be numerically smaller than east), and a box
  that crosses the equator or prime meridian is labelled end-by-end.
- Ship details and photos depend on Wikidata/Commons matching the IMO or MMSI; many working vessels
  have no entry and therefore no photo.
- The screen shows the current snapshot, not a track history; the database keeps the last known
  state, not a time series.
- The public stream is free and shared; it can be slow, lossy or briefly unavailable. The
  screensaver is a listener and does not retry a ship that has stopped transmitting.

# GeoGuess Screensaver

`screensaver.geoguess` v0.4.0

A Kodi screensaver that turns the idle screen into a guessing game. Each location is a random
street-view panorama from around the world, filling the screen height while it pans slowly — as
many times back and forth as you like, to give you another look. The answer appears only when
the final pass begins, so every earlier sweep is played without it: the place name fades in at
the bottom left, or, if you prefer, a zoomed satellite map centred on the location, with a pin
and the country name beneath it. A fixed clock in the top right corner is optional. After a while
the next panorama crossfades in. It streams the panoramas, place names and answer maps at run
time; the only bundled image is the pin.

It is pure Python (Kodi 19 or later), with no compiled code and no imaging library. One metadata
request per batch of locations, one image download per cycle, plus one map request when the map
answer is switched on.

---

## Contents

- [Installing](#installing)
- [How a cycle works](#how-a-cycle-works)
- [Settings reference](#settings-reference)
- [The location label](#the-location-label)
- [The answer map](#the-answer-map)
- [Data and how it is used](#data-and-how-it-is-used)
- [Images, panning and temporary files](#images-panning-and-temporary-files)
- [Offline and errors](#offline-and-errors)
- [Leaving the screensaver](#leaving-the-screensaver)
- [Project layout](#project-layout)
- [Development and testing](#development-and-testing)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)

---

## Installing

The add-on is in the P-Hoep repository (see the
[root README](../README.md#install-from-the-repository)).

1. **Settings → Add-ons → Install from repository → P-Hoep Add-ons.**
2. **Look and feel → Screensaver → GeoGuess Screensaver.**
3. **Settings → Interface → Screensaver → Screensaver mode → GeoGuess Screensaver.**
4. Open the add-on's settings below it to change the timing, the pan passes, the clock, the map
   and the label.

`script.module.certifi` is installed automatically as a dependency. It supplies a CA bundle on
devices whose Python has no system store of its own (common on Android).

## How a cycle works

1. A batch of rows is fetched from a random offset in the dataset, shuffled, and the row indices
   shown in the last 200 places are dropped. The batch is kept in memory and consumed one row at
   a time.
2. The next row is downloaded ahead of time, on a worker thread, to a file in Kodi's temp folder.
3. When the current cycle ends, that file is put into the spare image control and the two
   controls crossfade over one second. The old image is hidden.
4. The panorama is scaled to the full screen height; its width follows its aspect ratio. A
   panorama wider than the screen pans from its left edge to its right edge in one pass, at a
   constant speed. With **Passes across each panorama** above one, the direction reverses
   at each edge, so the panorama is shown back and forth; odd pass counts end at the right edge,
   even ones at the left. A narrower one, or panning switched off, is centred and does not move.
5. The answer fades in over the bottom shade at **Reveal the location** seconds into the final
   pass, so every earlier pass is played without it: with three passes the answer is hidden for
   two full sweeps. With **Show a zoomed map of the location instead of its name** on, a
   satellite map centred on the row's latitude and longitude appears instead of the text, with a
   pin on the spot and the English country name under it. After **Seconds per panorama pass** ×
   the pass count the answer fades out and the next crossfade begins. Repeated passes keep the
   pace of one pass; they make the location stay longer rather than pan faster.
6. With **Show a clock** on, the time is drawn as plain white text in the top right corner, in
   Kodi's own 12/24-hour format. It is a separate control, so it stays put while the panorama
   pans behind it.

Nothing is displayed until the first image is ready: the background is black, with **Loading a
street view…** in the middle. A hint of the answer is never shown before the final pass.

## Settings reference

All the settings are on one page, in two groups. They are listed here with their ids for the
`tools/kodi.py set` command.

| Setting | Id | Default | Range / options | Effect |
|---|---|---|---|---|
| Reveal the location (seconds into the last pass) | `reveal_after` | 8 | 1–60 | How long into the final pass to wait before the answer appears. Every earlier pass is played without it. Clamped to at most one second before the end of the cycle. |
| Seconds per panorama pass | `show_for` | 25 | 5–120 | How long one sweep from edge to edge takes. A location stays for this × the number of passes. |
| Locations fetched per request | `batch_size` | 40 | 10–100, step 10 | Rows asked for in one metadata request. Bigger batches mean fewer requests and more images skipped over. |
| Append the full country name | `show_country_name` | on | on/off | Adds the English country name when the address does not already end with any known spelling of it. |
| Pan slowly across each panorama | `pan_enabled` | on | on/off | Off pins wide panoramas to their left edge instead of panning. |
| Passes across each panorama | `pan_passes` | 1 | 1–10 | How many sweeps before the next location. Each pass reverses direction, so 2 or 3 gives another look at the scene. Hidden when panning is off; centred images always show for one pass. |
| Show a clock in the top right corner | `show_clock` | off | on/off | Plain white clock text over the panorama, in Kodi's time format. |
| Show a zoomed map of the location instead of its name | `show_map` | off | on/off | A satellite map centred on the row's latitude and longitude, with a pin and the country name, in place of the place name. A row without coordinates, or whose map could not be downloaded, falls back to the name. |
| Location label size | `label_size` | Medium | Small / Medium / Large | `font28`, `font37` or `font45` in Kodi's GUI resolution. Ignored while the map is shown. |

The name is white over a 460-pixel gradient shade at the bottom of the screen, so it stays
readable over bright skies and snow. The clock is plain white text in the corner.

## The location label

The dataset's `address` field already reads like a place, for example
`106 109, 1315 Velike Lašče, Slovenia`. The add-on cleans it up before showing it:

- A coordinate suffix is stripped when present: `Jarše Slovenia_46.1069942_14.9378597` becomes
  `Jarše Slovenia`. (The live rows no longer carry it, but the documented format does.)
- The ISO 3166-1 alpha-2 code is mapped to the English country name using the 55 countries in the
  dataset. Addresses often use the country's own spelling at the end — `Slovenija`, `Słowenia`,
  `Slowenien`, `Corée du Sud`, `日本` — so the English name is only appended when no known spelling
  is already at the end.
- If the address is empty, the country name is shown on its own.

The source data occasionally pairs an address with the wrong country code (for example a Romanian
street labelled `IS`). The screensaver shows what the row says; it does not try to correct the
dataset.

## The answer map

With **Show a zoomed map of the location instead of its name** on, the answer is a 720 × 360
satellite image in the bottom left corner, centred on the row's latitude and longitude and zoomed
in to a region roughly 670 km wide and 335 km tall. A red pin marks the exact spot, its tip on the
row's coordinates, and the English country name is shown in white underneath.

- **Source:** NASA Blue Marble imagery (shaded relief with bathymetry), rendered on demand by the
  NASA EOSDIS **GIBS** WMS. GIBS needs no key, is in the public domain, and returns the exact
  bounding box asked for, so the view can be centred on the row rather than cropped from a world
  map. The image is requested as JPEG, which keeps it to roughly 20–50 KB.
- **Projection:** plate carrée (EPSG:4326). The latitude span is fixed at 3°; the longitude span
  is `6° / cos(latitude)`, so the view covers about the same distance on the ground at every
  latitude and the terrain is not stretched. The point is placed with a linear interpolation
  inside the requested bounds: `x = (lon − left) / (right − left) × width`,
  `y = (top − lat) / (top − bottom) × height`.
- **Edges:** near the antimeridian or a pole the window is slid inward instead of crossing the
  edge of the world. The pin is placed from the bounds actually requested, so it stays on the
  location even then, and is clamped to the image if a point falls just outside.
- **Fallback:** a row without usable coordinates, or one whose map request fails, shows the place
  name instead, so the answer is never missing.

The map is fetched ahead of the reveal with the panorama, so the extra request does not delay the
answer. It is deliberately not taken from OpenStreetMap or Wikimedia: their tile services are not
licensed for use by applications, whereas GIBS is a public NASA service intended for exactly this
kind of use. The imagery has no country borders or place labels of its own; the country caption
under it is what names the answer.

## Data and how it is used

The rows come from the Hugging Face **datasets server**, which serves the dataset without the
`datasets` library:

- `https://datasets-server.huggingface.co/size` gives the row count for the split.
- `https://datasets-server.huggingface.co/rows` gives a page of rows from an offset, with the
  image URLs already signed.

The primary dataset is `yunusserhat/random_streetview_images` (11,054 rows, `train` split); the
same rows are mirrored as `stochastic/random_streetview_images_pano_v0.0.2`. The mirror's parquet
row groups exceed the datasets server's 300 MB scan limit, so its `/rows` endpoint currently
answers HTTP 500 and the client stays on the primary. It is kept in the source list in case that
limit changes or the primary disappears.

Each row carries `image` (a signed `cached-assets` URL plus its width and height),
`country_iso_alpha2`, `address`, `latitude` and `longitude`. The coordinates are strings in the
dataset; the client turns each into a float, checks its range and leaves it `None` when it cannot.
Malformed rows — no index, no image, a non-HTTP source — are skipped without stopping the batch.
Signed URLs expire; if an image download is refused, the add-on asks for that one row again by
`row_idx` once, then either shows the fresh URL or skips the row.

Requests identify themselves as `screensaver.geoguess/0.4.0 (Kodi screensaver;
+https://github.com/P-Hoep/kodi)`, send `Accept-Encoding: gzip`, and time out after 15 seconds.
Responses are capped at 32 MB for JSON and 24 MB for images, and an image must start with a JPEG
or PNG signature before it is accepted. With the map answer on, the prefetch also makes one GIBS
request per row (see [The answer map](#the-answer-map)); that image goes through the same
checks, and its failure is not fatal.

## Images, panning and temporary files

Kodi's image control wants a path, not bytes, so each download is written to
`special://temp/geoguess/geoguess-<row_idx>.jpg`; with the map answer on, its map is written next
to it as `geoguess-<row_idx>-map.jpg`. A `.part` file is written first and renamed into place, so a
half-written file is never shown. At most eight files are kept — two per row for the current row,
the prefetched one and the one being replaced — oldest deleted first; the folder is created when
missing and every file the add-on wrote is deleted when the screensaver closes.

The display size is computed from the image header when the dataset row does not carry a size:

- Height is always the full GUI height (1080 pixels in Kodi's `1080i` resolution).
- Width is `height × image_width / image_height`.
- If the file is not a readable JPEG or PNG, the image fills the screen instead of crashing.

Kodi's GUI runs at a fixed virtual resolution, so the same sizes are used on 720p, 1080p and 4K
displays; the GPU scales the whole GUI. The image is decoded by Kodi, not by Python.

The pan is stepped from Python because Kodi's own `slide` animation does not move a control that
was created from Python (tested on Kodi 21; the control stays where it was put). The positions
are computed from the clock rather than accumulated, and the display loop ticks at 120 Hz, faster
than a 50, 60 or 120 Hz refresh, so each rendered frame gets its own evenly spaced position. The
cost is one `setPosition` call per frame, which is negligible next to decoding the image.

## Offline and errors

- **No network when the screensaver starts:** the background stays black and the screen says
  **No connection. Retrying…**. Metadata requests retry after 10, 20, 40 and then 60 seconds. As
  soon as one succeeds, the normal cycle starts.
- **A 429 or 5xx from the datasets server:** retried with the same exponential backoff, up to
  eight attempts per batch. After four failed attempts the client switches to the next configured
  source and carries on.
- **A non-retryable error** (for example a dataset that does not exist, or a body that is not
  JSON): the client switches source after a one-second pause.
- **An image download failure:** retryable network errors pause for a second and try the next row;
  a refused or expired URL is re-requested by `row_idx` once. A row that cannot be shown is skipped
  without interrupting the screensaver.
- **A map download failure:** the panorama is still shown and the answer falls back to the place
  name; the next row tries its map again.
- **A row whose index was just shown:** the batch is refetched from another offset rather than
  showing it again.

All waits go through `xbmc.Monitor.waitForAbort`, so closing Kodi or waking the screensaver
interrupts a backoff immediately.

## Leaving the screensaver

Any key, remote press, click, touch or mouse move closes the window at once, as does Kodi
deactivating the screensaver or requesting an abort. Shutdown stops the prefetch thread, joins the
display thread for at most 1.5 seconds, deletes the temp files and closes the window. The window is
shown with `show()` rather than `doModal()`: when Kodi itself wakes the screensaver it closes the
window without telling Python, and `doModal()` would never return.

The prefetch thread is a daemon, so even a Kodi shutdown that skips the normal path cannot leave
Python blocking the process.

## Project layout

```
screensaver.geoguess/
  addon.xml                      id, version, metadata, attribution
  default.py                     entry point: from resources.lib import saver
  icon.png, fanart.jpg           generated by tools/make_geoguess_media.py
  resources/
    lib/
      config.py                  settings table, reveal timing, sources, answer map, strings
      labels.py                  address cleaning, ISO alpha-2 -> country name, map caption
      layout.py                  display size, pan extent, constant-speed pan, passes, map placement
      net.py                     urllib helpers, TLS, timeouts, image signature check
      hf_client.py               datasets-server client: /size, /rows, retries, rotation
      downloader.py              temp store, JPEG/PNG size, panorama and map download, prefetch
      saver.py                   the Kodi window and display loop (the only xbmc code)
    settings.xml                 GENERATED from config.py
    language/…/strings.po        GENERATED from config.py
    skins/Default/1080i/         the empty screensaver window
    skins/Default/media/         white backdrop, bottom shade and pin
```

The logic modules import no Kodi modules and are tested offline; `saver.py` is the glue and the
only place that touches `xbmc`, `xbmcgui`, `xbmcaddon` or `xbmcvfs`.

## Development and testing

```bash
python3 tools/make_settings_geoguess.py   # settings.xml + strings.po from resources/lib/config.py
python3 tools/make_geoguess_media.py      # icon, fanart, textures and pin (Pillow)
python3 -m unittest tests.test_geoguess   # 77 offline tests
python3 tools/build_zip.py screensaver.geoguess
KODI_ADDON=screensaver.geoguess python3 tools/kodi.py install   # then select / run / shot
KODI_ADDON=screensaver.geoguess python3 tools/kodi.py set reveal_after=3 show_for=30
```

The tests cover the settings table and reveal timing, the label cleaning (including non-ASCII and
missing addresses), the layout and pan maths, the answer map's window and pin placement, row and
coordinate parsing, the client's retry and rotation behaviour, image size parsing, the temp
store's cap and cleanup, the downloader's re-request and map paths, and the add-on's files and
generated settings. They need no network.

Restart Kodi after changing `strings.po`: Kodi caches an add-on's strings, and the settings labels
show up blank until it reloads them.

## Troubleshooting

**The screen stays black.** Watch the message. **Loading a street view…** means the first batch or
image is still arriving; the datasets server can occasionally take tens of seconds, and the
add-on's own timeout is 15 seconds per request. **No connection. Retrying…** means the metadata
requests are failing; check that
`https://datasets-server.huggingface.co/size?dataset=yunusserhat/random_streetview_images&config=default&split=train`
answers in a browser, and watch `kodi.log` for `[screensaver.geoguess]` lines.

**The first image takes a while.** A batch is one `/size` request, one `/rows` request and one
image download. On a slow connection the panorama can be several megabytes; the next images are
prefetched while the current one is shown, so only the first cycle waits.

**A place is labelled wrongly.** The address and the country code come from the dataset and
occasionally disagree. This is not an add-on error.

**The label is too small or too big.** Change **Location label size**; it switches between Kodi's
`font28`, `font37` and `font45`.

**The settings labels are blank.** Restart Kodi so it reloads the add-on's `strings.po`.

## Known limitations

- The dataset is a fixed collection of 11,054 rows; the screensaver avoids the last 200 shown
  indices, not every index it has ever shown.
- No images are cached between runs: the eight temp files exist only while the screensaver is
  active, by design.
- The answer map is satellite imagery at regional zoom, not a street map: it has no borders,
  roads or labels, and the country name under it is what identifies the answer.
- The second source in `config.py` currently answers HTTP 500 on `/rows`; see
  [Data and how it is used](#data-and-how-it-is-used).
- Street-view imagery is © Google and its contributors and is subject to Google's terms; the
  add-on is not affiliated with, endorsed by or sponsored by Google. Use it for personal viewing
  and follow the dataset's terms.

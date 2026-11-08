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

## SkyWatch (new, v1.0)

A fifth screensaver, `screensaver.skywatch`, built from
[docs/skywatch-spec.md](docs/skywatch-spec.md): the TV becomes a live weather station. An
animated radar loop over a map of your location runs into a future-radar extension, with a
PAST / NOW / FUTURE timeline. After the radar comes a playlist of scenes you can switch on,
reorder and time: regional radar with NWS warning polygons, a national mosaic, satellite +
radar, "what's coming" (HRRR to 18 h), current conditions, the next 2 hours, a 48-hour graph,
7 or 10 daily cards, today against the 1991–2020 normal, a year in temperature, a fishing
score with solunar periods, sun and moon, air quality and pollen, marine and tides, the NWS
forecast discussion, and an ambient clock. Active warnings pin a banner to every scene
and put a warning scene at the front of the playlist.

- **Data is keyless by default**: IEM NEXRAD and HRRR (via WMS), Open-Meteo (forecast,
  ERA5 archive, air quality, marine, geocoding), NWS, NOAA CO-OPS, USGS, NASA GIBS and
  Esri/OpenStreetMap base maps. Outside the US it uses RainViewer. A free Rainbow.ai key adds
  a global nowcast, capped by a monthly tile budget that falls back to HRRR; a LibreWXR server
  URL and a Stadia terrain key are optional extras.
- **Degrades quietly**: each source is OK, Stale or Down. On HTTP 429 or a server error it
  backs off from 1 minute, doubling to 60, and the radar chain falls back from Rainbow to
  HRRR to past-only. A scene with no data is skipped. With no network at all it runs from
  cache and the overlay shows "offline, data from …".
- **A background service** warms data and radar frames in the 30 minutes before Kodi's
  screensaver would start ("Smart" refresh), and sleeps during playback.
- **Interactive mode** (optional): waking SkyWatch reopens it as a normal window, where
  left/right skip scenes, up/down zoom the radar, OK pauses and Back exits.

```bash
python3 tools/make_skywatch_media.py     # Meteocons icons, Inter glyphs, backgrounds, icon (Pillow + Chrome)
python3 tools/make_splash.py skywatch    # loading splash
python3 tools/make_settings_skywatch.py  # settings.xml + strings.po from resources/lib/config.py
python3 tools/preview_skywatch.py all /tmp/sw   # draw every panel scene with live data, no Kodi
python3 tools/build_zip.py screensaver.skywatch
KODI_ADDON=screensaver.skywatch python3 tools/kodi.py install   # then set lat=… lon=… / select / run / shot
python3 -m unittest tests.test_skywatch  # offline: tile math, astronomy, fishing, climate, fallback, playlist
```

Design: the spec composites frames with Pillow, but Kodi on Android and Fire TV has no
imaging library, so SkyWatch lets Kodi composite on the GPU instead. Each radar frame is one
WMS image fetched at exactly the view's bounding box, so it lines up with the base-map tiles
and the labels layer drawn above it. Frames are a fixed stack of image controls that playback
only shows and hides, with a 120 ms fade. Charts are drawn by a small pure-Python rasteriser
(`raster.py`, `charts.py`) with Kodi labels on top, and the big numbers are pre-rendered
glyph images. Scenes are plain layouts, built and tested without Kodi.

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

## Audioshelf (new, v1.1)

`plugin.audio.audioshelf`, built from [docs/audioshelf.md](docs/audioshelf.md): not a
screensaver but a music add-on that plays the audiobooks on an
[Audiobookshelf](https://www.audiobookshelf.org/) server. It lives under **Add-ons → Music add-ons**
and opens on Continue Listening, Recently Added, All Audiobooks (sorted by title, author or date
added, paged), Series (in reading order), Authors, Genres and Search, plus **Play a random book**.
Every book shows its cover and its progress: a blue percentage while in progress, greyed with a
green "Finished" when done.

Renamed from `plugin.audio.audiobookshelf` (1.0–1.1.0) to avoid clashing with another add-on of that id.
If the old one is installed, uninstall it and install **Audioshelf**; you will need to sign in again.

- **Sign in**: the first time it opens, **Sign in to your Audiobookshelf server…** asks for the
  server address, your username and your password, one box at a time. The add-on keeps the
  server's access and refresh tokens and renews them itself (signing in again when needed), so
  you sign in once. An API key still works (**Sign in with → API key** in the settings), and an
  install that already has a key keeps using it until a username is entered. Nothing about the
  server is built in. With several audiobook libraries, **Choose library…** picks one.
- **Random**: **Play a random book** picks one you haven't finished, and each genre starts with
  **Play a random *genre* book**. The server does the shuffling; an in-progress pick resumes.
- **Playback** uses Kodi's own player on the book's original files (no transcoding). A book's
  page offers Resume (with the time left), Play from start, Chapters and About this book. A
  finished book starts again from the beginning rather than from an old position.
- **Progress** goes back to Audiobookshelf through a playback session, the same way the official
  apps do it: every 30 s while playing (configurable), on pause, and on stop, from a small
  background service. If the server has forgotten the session it opens a new one or writes the
  position directly; if it can't be reached, the position is kept on the device and sent later.
  Nothing is reported until playback has actually reached the point it was asked to start from,
  so a failed seek can't wind your position back to the start of a file.
- **Skip back / forward** by your own steps (15 s / 30 s by default) with
  `RunPlugin(plugin://plugin.audio.audioshelf/?action=skip&dir=back)` (or `dir=forward`) in a
  keymap; these work across a book's files. Kodi's own seek steps work too.

```bash
python3 tools/make_settings_audioshelf.py   # settings.xml + strings.po from resources/lib/config.py
python3 tools/make_audioshelf_media.py      # icon.png, fanart.jpg (Pillow)
python3 tools/build_zip.py plugin.audio.audioshelf
KODI_ADDON=plugin.audio.audioshelf python3 tools/kodi.py install   # then open it: Sign in to your server…
python3 -m unittest tests.test_audioshelf   # offline; LIVE=1 ABS_URL=… ABS_KEY=… adds read-only server checks
```

## Live Cams (new, v1.0)

`screensaver.livecams`, built from [docs/livecams-screensaver.md](docs/livecams-screensaver.md):
the idle TV becomes a window onto live outdoor scenes. It rotates through public camera feeds
from the [Live-Environment-Streams](https://github.com/william-ricchiuti/Live-Environment-Streams)
dataset (beaches, mountains, lakes, harbours, towns; traffic cameras optional), with a small
overlay giving the place, the source and the local time there.

- **Choosing a camera**: a weighted draw that favours places in daylight right now (offline NOAA
  sun position), premium and HD streams and your favourites. It plays down cameras shown in the
  last 6 hours and the source or country already on screen. If the filters leave nothing, it
  relaxes daylight, then minimum resolution, then unverified streams.
- **Self-healing**: each pick's manifest is probed first (4 s), so a dead feed costs no screen
  time. A stream that shows no picture in 15 s, or stalls for 10 s, is skipped. Failures are
  remembered (skip for 1 hour, 1 day, then a week), and a source where more than half the
  attempts fail in an hour is skipped for 6 hours. After 5 failures in a row, or with no
  network, a fallback card with a clock shows and it retries every minute.
- **Safe with your media**: if your own video or music is loaded (paused), it shows only a clock
  and never touches the player. Any key, mouse move or remote button exits straight away. Streams
  play muted unless *Play audio* is on. After 2 hours (*Stop streaming after*) it switches to a
  clock that uses no network.
- **Catalogue**: downloaded at run time (nothing bundled; the dataset has no licence yet), cached
  as a slim index and refreshed weekly in the background with an ETag. A bad download keeps the
  old index.

```bash
python3 tools/make_livecams_media.py     # icon, fanart, fallback card (Pillow)
python3 tools/make_splash.py livecams    # loading splash (Chrome)
python3 tools/make_settings_livecams.py  # settings.xml + strings.po from resources/lib/config.py
python3 tools/build_zip.py screensaver.livecams
KODI_ADDON=screensaver.livecams python3 tools/kodi.py install   # then select / Preview
python3 -m unittest tests.test_livecams  # offline: sun, local time, catalogue, selector, health, HLS, watchdog
```

Notes from building it:

- Kodi wakes a screensaver as soon as anything starts playing, then stops its script. So
  `default.py` (the screensaver) only checks for your media and starts `session.py` as an
  ordinary script, which owns the window and the player and ignores the wake-up its own
  `play()` causes. Before the first camera, any key still wakes Kodi's screensaver and the
  session closes.
- The video layer is drawn under the whole GUI, so the window's black backdrop is hidden while a
  camera plays, and two black bars, sized from the video and screen aspect, cover the letterbox.
- The default pool (active, HLS, no token or browser needed, not traffic) is **282 cameras**, not
  the README's 2,929 or 4,229. In October 2026, 131 of them answered a strict probe. The 45
  Balticlivecam URLs carry tokens that expired in April 2026, and about 40 others return 404;
  health tracking learns this within a few sessions. The 58 `ls.tkchopin.pl` cameras send an
  incomplete certificate chain: with *Allow cameras with incomplete HTTPS certificates* (on by
  default) they are probed and played without certificate checks. No source needed special
  headers (User-Agent or Referer made no difference).

## Sheetcards (new, v1.0)

![Sheetcards: deck picker, flashcards, multiple choice, pause sheet and results](release/gifs/sheetcards.gif)

`script.sheetcards` (an app under **Add-ons → Program add-ons**) and `screensaver.sheetcards`, built
from [docs/Sheetcards.md](docs/Sheetcards.md): flashcards from any public Google Sheet. Column A
is the question, column B the answer, and every tab is a deck. Share the sheet as "Anyone with the
link can view", then paste its ID or link in the settings. You need no Google login or API key.
Both add-ons use the shared library `script.module.sheetcards`, which Kodi installs with them.

- **Modes**: Flashcard (question, then the card flips), Multiple choice (3 or 4 options) and
  Mixed. Wrong options come from other cards' answers of the same kind (number, year, date,
  word, phrase, sentence) and similar length. A deck with too few different answers runs as
  flashcards. Direction can be Question → Answer, Answer → Question, or both.
- **The app**: a deck picker (multi-select, cards, due count and mastery per deck), study by
  remote, mouse or touch (number keys 1–4 answer directly, Back pauses, Info shows the
  card's stats), score and streaks, and results with the missed cards and **Review missed**.
  Spaced repetition uses Leitner boxes (1, 2, 4, 8 and 16 days). A missed card comes back 3–5
  cards later. Order can be Smart, Shuffle, Sheet order or Hardest first.
- **The screensaver**: a question, a timer bar, then the answer, card after card from a
  shuffle bag. Any input exits at once. The card drifts ±24 px at each change, and it can show
  a clock and dim. By default it uses the app's sheet, decks and look.
- **Data**: cards load from the cache first and refresh in the background every 6 hours by
  default. If the network is down, the cached cards keep working. Tabs are found through the
  sheet's `htmlview` page, with an optional API key or a list of tab names as fallbacks.
- **Look**: Night, Day or Auto (by time), six accent colours or a custom one, optional custom
  background and card colours (the text colour follows for contrast), and a soft glow. All
  textures are white and tinted from window properties, so they look the same in every skin.

```bash
python3 tools/make_sheetcards_media.py     # textures, icons, fanart (Pillow)
python3 tools/make_sheetcards_skin.py      # the three WindowXML files
python3 tools/make_settings_sheetcards.py  # both settings.xml + strings.po from lib/sheetcards/config.py
python3 tools/build_zip.py script.module.sheetcards   # and script.sheetcards, screensaver.sheetcards
for a in script.module.sheetcards script.sheetcards screensaver.sheetcards; do KODI_ADDON=$a python3 tools/kodi.py install; done
python3 -m unittest tests.test_sheetcards  # offline: parsing, tabs, loader fallbacks, distractors, Leitner, theme
```

Notes from building it (Kodi 21.1, macOS): `$INFO[Window.Property(...)]` works in `textcolor`,
`selectedcolor` and texture `colordiffuse`, including inside list layouts, so one XML serves every
theme. A bare number in a `<label>` is read as a string ID, so the option badges use
`$NUMBER[n]`. Any EventServer packet (`kodi.py shot`, `kodi.py builtin`) wakes a screensaver. To
take screenshots of one, run a script inside Kodi that activates it and calls `TakeScreenshot`.

## RSS Live Tiles (new, v1.0)

![RSS Live Tiles: the hub of live tiles, a tile expanding into its story, the menu, the Mixed wall, Magazine, Spotlight and Mosaic layouts in the Classic, Modern and Outline styles, and the screensaver](release/gifs/rss-live-tiles.gif)

Your news feeds as a wall of flat, coloured live tiles, like the Windows Phone home screen and
the Windows 8 Start screen. Headlines and pictures come straight from the feeds. Tiles flip,
peek and roll on their own to show the next story. Select one to read the whole story, with a
QR code to open it on your phone. The screensaver turns an idle TV into a news wall.

`script.rsslivetiles` (an app under **Add-ons → Program add-ons**) and `screensaver.rsslivetiles`,
built from [docs/RSSliveTiles.md](docs/RSSliveTiles.md): RSS and Atom feeds as Windows Phone
style live tiles. Both use the shared library `script.module.rsslivetiles`, which Kodi installs
with them (with `script.module.certifi` and `script.module.pyqrcode` from Kodi's repository).
It ships with three sample feeds: BBC News, r/kodi and NASA Image of the Day.

- **Tiles**: flat accent squares and rectangles in four sizes (small, medium, wide, large) on a
  130 px grid. Picture tiles have a scrim, the headline and "SOURCE · 12 MIN AGO". Text tiles
  show the headline, plus a summary on wide and large tiles. Count tiles show the feed icon (or
  its initials) and how many items are new.
- **Live**: a scheduler animates a random on-screen tile every few seconds (Calm / Normal /
  Lively, 1–4 at once, never the focused tile). Feed tiles flip or roll to their next story,
  picture tiles peek to their text, text tiles flip to their summary and count tiles pulse when
  the count changes. Tiles drop in column by column on open. Reduced motion uses fades only.
- **Layouts**: Feed groups (a scrolling Start-screen hub, one group per feed), Mixed wall,
  Magazine, Spotlight (one feed per screen) and Mosaic (pictures only; headlines on peek).
  **Styles**: Classic, Modern (rounded, translucent panels) and Outline.
- **Look**: the 20 Windows Phone accents or your own hex (warns below 3:1 contrast), per-feed
  accents, shade variation, and Night / Day / Scheduled / Sunrise–sunset themes (sun times are
  computed locally) with a crossfade.
- **Detail view**: Select expands the tile into the story: picture, headline, author and time,
  the article text (bold, italics and paragraphs kept) and a QR code of the link. Left / Right
  go through the feed. Podcasts and video enclosures play.
- **Feeds**: add by URL (checked, title detected), edit title, accent, max items, refresh
  interval, enabled and pinned tile size; reorder; OPML import and export. A background thread
  refreshes them with conditional GET, a 5 MB cap and backoff up to 6 h. Everything renders from
  the cache first and works offline. A failing feed shows a warning glyph.
- **The screensaver**: the grid fills the screen without scrolling, rotates fresh stories in
  every few minutes, shifts a few pixels every two minutes (optionally drifts), can show a clock
  tile and dims at night. Any input exits at once.

```bash
python3 tools/make_rsslivetiles_media.py     # textures, icons, fanart (Pillow)
python3 tools/make_rsslivetiles_skin.py      # one window XML per tile style
python3 tools/make_settings_rsslivetiles.py  # both settings.xml + strings.po from lib/rsslivetiles/config.py
for a in script.module.rsslivetiles script.rsslivetiles screensaver.rsslivetiles; do KODI_ADDON=$a python3 tools/kodi.py install; done
python3 -m unittest tests.test_rsslivetiles  # offline: parsing, images, layouts, scheduler, theme, sun, QR
```

Notes from building it (Kodi 21.1, macOS):
- **Fixed slots.** The board is a set of tile slots generated into the window XML (pools per
  size). Python moves a slot with `setPosition()` and fills it through window properties, and
  Kodi animates everything. Only tiles near the visible part of the hub are bound, so a hub of
  any length fits the pools. Each face is double-buffered: new content goes into the hidden
  face, then a property swaps them and XML `Hidden`/`Visible` animations play.
- **No clipping.** Kodi groups and grouplists do not clip animated children, so peeks and rolls
  are squashes that stay inside the tile, not slides.
- **No 3D flips.** Kodi's `rotatex`/`rotatey` use a close camera, so a flipping picture tile
  balloons out of its rectangle. Flips are 2D squashes with a slight shrink at the midpoint.
- **Scrolling** restarts a `condition=true` slide with `setAnimations()` and then
  `setPosition()`s the strip, which gives a smooth 300 ms scroll.
- **Frames** are four solid bars. A small bordered texture, stretched, renders soft.
- **Fonts.** Add-ons cannot register fonts without editing the skin, so tiles use Estuary's
  font names. The hub title uses `font_clock` (Roboto Thin) for the light Metro look.
- **Speed.** A window file is about 1.5 MB and ~3,800 controls. It loads in about 0.15 s, and
  the board fills from the cache in 0.01 s.

## Word Clock (new, v1.0)

![Word Clock: IT IS FIVE TO TWO PM turning to TWO O'CLOCK, a ripple, midnight in blue with a glow, rainbow words, an amber dot-matrix face, a serif walnut card, minute dots, and the day colours blending into night](release/gifs/word-clock.gif)

`screensaver.wordclock`, built from [docs/wordclock.md](docs/wordclock.md): the time in words on an
11 × 11 grid of letters, like a QlockTwo-style word clock. The words that tell the time light up
(IT IS FIVE TO TWO PM, IT IS TEN PAST MIDNIGHT). By default it matches the classic graphite face:
bold white letters over dim grey ones on a rounded `#1B1B1D` card.

- **Clock:** round down or to the nearest five minutes, minute dots in the corners, and IT IS,
  A QUARTER, AM/PM and MIDNIGHT can each be turned off. AM/PM follows the hour that is named, so
  11:45 AM reads QUARTER TO TWELVE PM. The grid has no NOON (row 11 ends `NOO`).
- **Letters:** eight OFL fonts (Inter, Montserrat, Raleway, Playfair Display, JetBrains Mono,
  Comfortaa, Doto dot matrix, Big Shoulders Stencil), bold or regular lit letters, unlit letters
  shown, faint or hidden, a soft or strong glow, and letter size.
- **Colours:** eight palettes or Custom (Kodi 20+ colour pickers for background, card, lit and
  unlit), separately for day and night. Lit words can be one colour, each word its own colour,
  or a slow rainbow cycle.
- **Day and night:** night colours, day colours, or both by the clock (an 8 s blend at the
  switch), and dimming at night.
- **Screen:** rounded card, square card or full screen, size, fade / ripple / cut transitions,
  dimming and an OLED drift. Any input exits in about 0.02 s.

```bash
python3 tools/make_wordclock_media.py      # glyphs for 8 fonts, card textures, icon, fanart (Pillow; downloads the fonts)
python3 tools/make_settings_wordclock.py   # settings.xml + strings.po from resources/lib/config.py
python3 tools/preview_wordclock.py out.png 13:55 font=6 glow=2 night_palette=3   # draw the face with Pillow
python3 tools/build_zip.py screensaver.wordclock
KODI_ADDON=screensaver.wordclock python3 tools/kodi.py install         # then select / run
python3 -m unittest tests.test_wordclock   # offline: the grid, every minute of the day, settings, colours, layout
```

Notes from building it (Kodi 21.1, macOS): letters are white glyph PNGs tinted with
`setColorDiffuse`, because add-ons cannot load fonts. Each cell has an unlit, a glow and a lit
image whose `setVisibleCondition()` watches a Home window property, with Visible/Hidden fade
animations. A time change is a few `setProperty` calls and Kodi does the cross-fade, so Kodi uses
about 3% CPU while it runs. The rounded card is an XML image with a 9-slice `border`, so its
corners stay the same at any size. Setting the Home property `wordclock.demo` to `HH:MM` shows
that time, for testing.

## Sand Clock (new, v1.0)

![Sand Clock: 17:52 crumbling every second into neon sand that piles into striped mountains, a pixel font crumbling into round beads, a digital font in a slow rainbow, and a stencil clock in desert sand](release/gifs/sand-clock.gif)

`screensaver.sandclock`, built from [docs/sandclock.md](docs/sandclock.md): a big clock that crumbles
into sand. Shortly before each second ticks over, the digits break into grains that fall under
gravity, drift a little sideways and slide into heaps at the bottom of the screen. Each change can
bring a new colour, so the heaps build up in stripes, and the pile sinks slowly through the floor
so it stays the same size.

- **Clock:** seconds on or off, 24 or 12 hour, the whole clock crumbles (as in the video it is
  based on) or only the digits that change, and a slow, normal or quick crumble.
- **Font:** nine OFL fonts (Inter, Montserrat, Orbitron, Pixelify Sans, Doto, JetBrains Mono,
  Comfortaa, Playfair Display, Big Shoulders Stencil), light, regular or bold, width and position.
- **Sand:** fine, medium or coarse grains that look like sand, flat squares or round beads,
  floaty, normal or heavy gravity, and how tall the pile gets.
- **Colours:** a new colour each change or per digit, one colour of your own, or a slow rainbow;
  eight palettes; a background colour.
- **Day and night:** a different palette at night, dimming at night or all the time, and a slow
  drift to protect OLED screens.

```bash
python3 tools/make_sandclock_media.py      # glyphs and masks for 9 fonts x 3 weights, grain textures, icon, fanart
python3 tools/make_settings_sandclock.py   # settings.xml + strings.po from resources/lib/config.py
python3 tools/build_zip.py screensaver.sandclock
KODI_ADDON=screensaver.sandclock python3 tools/kodi.py install         # then select / run
python3 -m unittest tests.test_sandclock   # offline: fonts, layout, the physics, the sinking pile, colours
```

Notes from building it (Kodi 21.1, macOS): Python plans and Kodi animates. Each grain is an image
control with a chain of `Conditional` slide animations (wait, fall, drift, slide down the pile,
sink) keyed to one Home window property per crumble. Landed sand is merged every 1.5 s into
strips of same-coloured grains, one image each, so a minute of sand is a few hundred controls,
not tens of thousands. The sinking speed follows how much sand falls and how wide the heap is,
and changes only once every grain in the air has landed. When the whole clock crumbles the grains
get coarser if needed to stay under 1000 per second. It uses about 50% of one core on a retina
Mac, where Kodi alone takes about 37% while anything animates. Setting the Home property
`sandclock.demo` to `HH:MM:SS` starts the clock at that time, for testing.

## Jeopkodi (new, v1.0)

![Jeopkodi: a $800 clue in CHAMPAGNE PROBLEMS, the response WHO IS MICHELANGELO?, a Final Jeopardy clue about the ravens of the Tower of London, and a clue shown without the category and value](release/gifs/jeopkodi.jpg)

`screensaver.jeopkodi`: an endless Jeopardy! slideshow. Each clue comes up on the classic blue
screen (#060CE9) in white Korinna capitals with the hard drop shadow, and a few seconds later the
response replaces it, phrased as a question ("WHAT IS THE JORDAN?"). The category is shown in
white and the dollar value in Jeopardy yellow at the top. There are 533,168 clues from 42 seasons.

- **Clues:** easy ($200 and $400), medium ($600) and hard ($800 and $1000) rows, each on or off,
  plus Daily Doubles and Final Jeopardy. Clues from before the 2001 value doubling count by their
  row on the board, so an old $100 clue is easy.
- **Timing:** how long a clue stays up (12 seconds by default, with more time for long clues) and
  how long the response stays up.
- **Display:** the category and value at the top or not, WHAT IS / WHO IS phrasing or the bare
  response, text size and dimming.

```bash
python3 tools/make_jeopkodi_db.py combined_season1-42.tsv     # J! Archive TSV -> resources/data/clues.db
python3 tools/make_jeopkodi_media.py KorinnaStd-Bold.ttf     # glyph images (white and yellow), vignette, icon, fanart
python3 tools/make_settings_jeopkodi.py                      # settings.xml + strings.po from resources/lib/config.py
python3 tools/build_zip.py screensaver.jeopkodi
KODI_ADDON=screensaver.jeopkodi python3 tools/kodi.py install           # then select / run
python3 -m unittest tests.test_jeopkodi                      # offline: settings, database, chunks, phrasing, layout
```

Notes from building it (Kodi 21.1, macOS): add-ons can't load fonts, so every character is a
pre-rendered PNG with its shadow, and `metrics.json` holds the advances and kerning. Python then
wraps and centres the text itself: it picks the largest size that fits, then narrows the column
as far as it can without adding a line, which gives the show's stacked look (the W.C. Handy clue
breaks exactly as on air). Two pools of image controls, 70 for the header and 250 for the text,
are created once and re-textured for each slide, and they fade through Home window properties.
The database is 70 MB of SQLite with the rows already in random order, so a chunk is one
indexed read of 600 consecutive ids, filtered by the settings and shuffled again. Clues that need
a picture, video or audio clip are left out. The window is shown with `show()` and a loop instead
of `doModal()`: when Kodi wakes a screensaver itself (a `RunScript` or a screenshot) it closes the
window without telling Python, `doModal()` never returns and Kodi kills the script after 5 seconds.
The loop also watches `System.ScreenSaverActive`, so it always exits.

## DVD Logo (new, v1.0)

![DVD Logo: the white logo bouncing across a black screen, landing exactly in a corner, then lining up another corner and veering away at the last second](release/gifs/dvd-logo.gif)

`screensaver.dvdlogo`: the classic waiting game. The white DVD logo — the picture in
`dvd-asset/image.png`, trimmed and rendered white-on-transparent by `tools/make_dvd_media.py` —
drifts across a black screen and bounces off the edges, changing colour when it lands a corner.

- **Corner tricks:** *Off*, *Hit the corner*, *Veer off at the last second*, or *Alternate*
  (the default: hit a corner, then fake the next one). A slider sets how often it tries
  (every 10 seconds by default).
- **Logo:** size and speed, from a slow drift to a quick scoot.
- **Colours:** white, a new colour on every bounce (the classic), a new colour only at corner
  hits, a slow rainbow, or one fixed colour; the background is any colour too.

How the corner hits work: in a rectangle a bouncing diagonal is a straight line folded back into
the screen, so a corner is a lattice point of the unfolded plane. `aim()` turns the direction onto
one of those points by at most 12° at a bounce, where it reads as part of the bounce, and the
logo then really does land exactly in the corner, however many walls later. The fake-out uses the
same aim but starts a six-step swerve half a second before arrival: the logo gets within about
100 px and then turns away. `bounce.py` has no Kodi imports, and `tests/test_dvdlogo.py`
simulates whole screens against it, including that a plain run never hits a corner and a fake-out
never does either.

```bash
python3 tools/make_dvd_media.py              # media, icon and fanart from dvd-asset/image.png
python3 tools/make_settings_dvdlogo.py       # settings.xml + strings.po from resources/lib/config.py
python3 tools/make_dvdlogo_gif.py release/gifs/dvd-logo.gif   # demo frames from the same motion code
python3 tools/build_zip.py screensaver.dvdlogo
KODI_ADDON=screensaver.dvdlogo python3 tools/kodi.py install   # then select / run
python3 -m unittest tests.test_dvdlogo       # fold, aiming, fake-outs, settings and media
```

The logo moves as one Kodi slide animation per wall, so Python wakes only a few times a minute.
The window is shown with `show()` and a `System.ScreenSaverActive` loop rather than `doModal()`,
so it always exits, and `Dialog.Close` closes it without waiting for Kodi's main thread.

The DVD logo is a trademark of DVD Format/Logo Licensing Corporation; this is an unaffiliated
fan project.

## Tetris AI (new, v1.1)

![Tetris AI: the AI stacks tetrominoes edge to edge, clears rows, and plays around a clock made of blocks suspended above the floor](release/gifs/tetris.gif)

`screensaver.tetris`: an AI plays Tetris across the whole screen, forever. The playfield is
always 18 rows tall and reaches all four edges; the *block size* setting sets how wide the
blocks are in pixels. At the default 96 pixels there are 20 columns of 96 × 60 pixels — exactly
16:9 — and smaller blocks fit more, narrower columns, so a wide screen does not fill up with
huge squares: 64 gives 30 near-square columns, the minimum 32 gives 60. All seven classic
tetrominoes come from a seven-bag randomizer, with the Guideline rotation counts (I, S and Z
have two orientations, O one, T, J and L four).

- **AI skill:** *Perfect*, *Expert*, *Skilled*, *Average* or *Beginner*. Perfect always takes
  the best placement under the El-Tetris heuristic (landing height, rows cleared, row and
  column transitions, holes and wells). The lower levels increasingly pick
  a runner-up instead, so the stack grows and the board tops out now and then — and clears
  itself and starts again.
- **Speed:** an overall slider from 25% to 400%. *Speed up as lines are cleared* shortens
  every step with each level, as on a real machine, and the starting level can begin higher.
- **Colours:** the *Classic* Guideline rainbow (cyan I, yellow O, purple T, green S, red Z,
  blue J, orange L), the muted *NES* palette, plus Neon, Pastel, Monochrome, Game Boy, Sunset,
  Ocean and Vaporwave, or seven colours of your own. The background is any colour too, and the
  blocks are the same relief sprite as a real Tetris app, tinted per piece.
- **The clock:** on by default, drawn as text in the top-left panel or — *Clock style:
  Tetris blocks* — as HH:MM in a 3 × 5 block font, with seconds when the board has 27 columns
  for them. *Block clock position* leaves it resting on the floor or suspended three rows above
  it, hanging in mid-air with the game playing around and above it. Either way its digits are
  fixed cells: pieces collide with them and have to be placed around them, they never fall with
  the stack, and a row that clears leaves them exactly where they are. The digits are redrawn
  once a minute (every second with seconds on), as soon as no locked piece is in the way; a
  piece resting on a digit that vanishes falls into the gap it leaves, never hanging in the
  air. The clock can be any colour (*Block clock colour*). If the clock is off, the game is
  plain Tetris.
- **Look:** block width from 32 to 96 pixels (60 down to 20 columns), the grid, the stats panel
  (score, lines, level and best), its opacity, the landing ghost and the next-piece preview can
  each be switched off.

The playfield is a bitmask per row (`board.py`), so collisions, landings in all four
orientations and full-row detection are integer operations, and the AI scores every legal
placement of the current piece in one pass (`ai.py`). `game.py` keeps the seven-bag, the score
(100/300/500/800 × level), the level every ten lines and the best score; `clockface.py` turns
a `struct_time` into board cells. None of the engine modules import Kodi. The window is shown
with `show()` and a `System.ScreenSaverActive` loop rather than `doModal()` — Kodi closes a
screensaver itself when it wakes, and `doModal()` would never return — and it always exits by
`Dialog.Close`.

```bash
python3 tools/make_tetris_media.py           # blocks, a grid per column count, panels, icon, fanart
python3 tools/make_settings_tetris.py        # settings.xml + strings.po from resources/lib/config.py
python3 tools/make_tetris_gif.py release/gifs/tetris.gif   # demo frames from the same engine
python3 tools/build_zip.py screensaver.tetris
KODI_ADDON=screensaver.tetris python3 tools/kodi.py install   # then select / run
python3 -m unittest tests.test_tetris        # engine, clock, settings, AI and media
```

Tetris is a trademark of The Tetris Company; this is an unaffiliated fan project.

## Tetris AI (OpenGL) (new, v1.0.2)

`screensaver.tetris.gl` is the same game drawn by the GPU instead of by Kodi image controls:
everything about the rules, the AI, the colours, the clock and the settings is the same, but the
piece does not jump cell to cell. It slides and falls at sub-pixel positions on eased curves, so
the motion is as smooth as the display, dropped pieces land exactly on the ghost, a line clear
flashes twice and collapses, and a piece resting on a clock digit that changes slides down into
the gap. Blocks are antialiased rounded tiles, so they look right at any block size and stay
sharp on a high-DPI screen.

It is a native add-on (C++ / OpenGL, 2.1 and GLES 2.0), so it is built per platform, and there
are two Kodi add-ons for it:

- **Tetris AI (OpenGL, macOS and 64-bit Android)** — macOS (universal, Intel and Apple Silicon)
  and 64-bit Android.
- **Tetris AI (OpenGL, 32-bit Android)** — the same build for 32-bit Android Kodi, which the Fire
  TV, many Google TV boxes and the Chromecast with Google TV use. Install this one on those
  devices; the 64-bit library cannot load in a 32-bit Kodi.

The code lives in `screensaver.sandclock.gl` with the other GPU add-ons and is documented in
[screensaver.sandclock.gl/README.md](screensaver.sandclock.gl/README.md#tetris-ai-opengl). The
engine is a plain C++ port of the Python one (`src/tetris.*`, tested by
`screensaver.sandclock.gl/tests/test_tetris.cpp`), the renderer is `src/tetris_app.*`, and the
settings are generated from the Python add-on's table so both have the same 25 settings:

```bash
cd screensaver.sandclock.gl
cmake -S . -B build && cmake --build build      # tetris_glfw test window (macOS also tetris_glfw_core)
./build/tetris_glfw --no-clock --shot out.ppm --shot-after 8
ctest --test-dir build -R tetris                # engine, rotations, AI, clock cells

# Kodi add-on: macOS universal dylib
cmake -S . -B build-uni -DCMAKE_OSX_ARCHITECTURES="x86_64;arm64" \
  -DSANDCLOCK_KODI=ON -DSANDCLOCK_HARNESS=OFF \
  -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include && cmake --build build-uni

# Kodi add-on: Android (arm64-v8a, or armeabi-v7a for the 32-bit add-on)
cmake -S . -B build-android -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static \
  -DSANDCLOCK_KODI=ON -DSANDCLOCK_HARNESS=OFF \
  -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include && cmake --build build-android

python3 tools/make_settings_tetris_gl.py        # settings.xml + strings.po for both add-on folders
```

Tetris is a trademark of The Tetris Company; this is an unaffiliated fan project.

## Physarum Visualisation (new, v1.0.0)

`visualization.physarum.lite` is Physarum Lite as a **music visualisation**: the same GPU slime
mould, with no clock and no timers, driven by whatever Kodi is playing. An analyser in the add-on
reads Kodi's samples and measures the overall level, five bands (bass, low, mid, treble, air), a
beat and a 32-band spectrum, with automatic gain so quiet tracks still move the picture. Loud
passages make the agents travel further, bass thickens the trails and slows their fade, and a beat
jolts the agents, pulses the zoom and sends a ring across the screen that drags the network with
it; the palette drifts with the music. The spectrum is drawn as bars along the bottom by default,
and can also be a ring around the edge or hidden. One Reactivity slider sets how much the music
does — at 0 it is exactly the Physarum Lite screensaver running still — and each reaction (speed,
trails, beat, colour) can be switched off on its own.

It is a native add-on (C++ / OpenGL, 2.1 and GLES 2.0), so it is built per platform, and there are
two Kodi add-ons for it:

- **Physarum Visualisation (macOS and 64-bit Android)** — macOS (universal, Intel and Apple
  Silicon) and 64-bit Android.
- **Physarum Visualisation (32-bit Android)** — for 32-bit Android Kodi, which the Fire TV, many
  Google TV boxes and the Chromecast with Google TV use. The 64-bit library cannot load there.

Pick it under **Settings → Player → Music → Visualisation** (or from the music OSD) while a song
plays; Kodi starts and stops it with each track. It is not a screensaver, so `tools/kodi.py
select` does not apply. The code lives in `screensaver.sandclock.gl` with the other GPU add-ons and
is documented in
[screensaver.sandclock.gl/README.md](screensaver.sandclock.gl/README.md#physarum-visualisation).

```bash
cd screensaver.sandclock.gl
cmake -S . -B build && cmake --build build      # physarum_audio_glfw test window
./build/physarum_audio_glfw --selftest          # analyser + a rendered synthetic track
./build/physarum_audio_glfw --spectrum 2 --shot out.ppm --shot-after 20

# Kodi add-on: macOS universal dylib
cmake -S . -B build-uni -DCMAKE_OSX_ARCHITECTURES="x86_64;arm64" \
  -DSANDCLOCK_KODI=ON -DSANDCLOCK_HARNESS=OFF \
  -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include && cmake --build build-uni

# Kodi add-on: Android (arm64-v8a, or armeabi-v7a for the 32-bit add-on)
cmake -S . -B build-android -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static \
  -DSANDCLOCK_KODI=ON -DSANDCLOCK_HARNESS=OFF \
  -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include && cmake --build build-android

python3 tools/make_settings_physarum_audio.py   # settings.xml + strings.po for both add-on folders
KODI_ADDON=visualization.physarum.lite python3 tools/kodi.py install
```

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

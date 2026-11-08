# P-Hoep Kodi Add-ons

Ambient screensavers, a word clock, a sand clock, a Jeopardy! slideshow, a scheduler, a flashcard app and a news reader for Kodi, published as one Kodi
repository so Kodi installs them and keeps them up to date.

| Add-on | Version | What it is |
|---|---|---|
| [God's Eye Map](#gods-eye-map) | 0.2.2 | A live map of your area: flights, satellites, weather, traffic and transit |
| [God's World Map](#gods-world-map) | 0.1.1 | The whole Earth in thirteen projections, with live weather and events |
| [Math Clock](#math-clock) | 0.1.1 | The date and time as maths puzzles, typeset like LaTeX |
| [Couchstronomy](#couchstronomy) | 0.1.3 | Your TV as a window onto the real night sky |
| [Screensaver Switcher](#screensaver-switcher) | 0.1.0 | Different screensavers at different times of day |
| [Sheetcards](#sheetcards) | 1.0.0 | Flashcards from a Google Sheet: an app to study with and a screensaver |
| [RSS Live Tiles](#rss-live-tiles) | 1.0.0 | Your RSS and Atom feeds as Windows Phone style live tiles: an app and a screensaver |
| [Word Clock](#word-clock) | 1.0.0 | The time in words on a grid of letters, with your own fonts and colours |
| [Sand Clock](#sand-clock) | 1.0.1 | A clock whose digits crumble into falling sand every second |
| [Jeopkodi](#jeopkodi) | 1.0.0 | An endless Jeopardy! slideshow: clue, then the response |
| [DVD Logo](#dvd-logo) | 1.0.1 | The classic bouncing DVD logo, with corner tricks |
| [Tetris AI](#tetris-ai) | 1.1.1 | An AI plays Tetris edge to edge, with a clock made of blocks |
| [Tetris AI (OpenGL)](#tetris-ai-opengl) | 1.0.2 | The same AI in native code and OpenGL: the motion is as smooth as the display |
| [Endless World (OpenGL)](#endless-world-opengl) | 1.0.0 | An endless procedural landscape of mountains, lakes and forests, generated as the camera flies |

All of them are pure Python with no compiled code, except Tetris AI (OpenGL) and Endless World
(OpenGL), which are native add-ons. The Python add-ons run on Kodi 19 (Matrix) and later, on any
platform; the OpenGL add-ons are built for macOS (Intel and Apple Silicon) and Android, in a
64-bit and a 32-bit build. They were developed and tested on Kodi 21 on macOS. God's Eye Map has
also been tested on Amazon Fire TV Sticks.

---

## Install

The add-ons are in a Kodi repository hosted on GitHub Pages:
**https://p-hoep.github.io/kodi/**

1. **Settings → System → Add-ons → Unknown sources → On.**
2. **Settings → File manager → Add source →** enter `https://p-hoep.github.io/kodi/`
   and name it `phoep`.
3. **Settings → Add-ons → Install from zip file → phoep →** `repository.phoep-1.0.6.zip`.
   Kodi shows "P-Hoep Add-ons — Add-on installed".
4. **Settings → Add-ons → Install from repository → P-Hoep Add-ons.** The screensavers are
   under **Look and feel → Screensaver**, the Switcher is under **Services**, and the
   Sheetcards app is under **Program add-ons**.
5. To turn one on, go to **Settings → Interface → Screensaver → Screensaver mode**, pick it,
   then open **Settings** below it to configure it. **Preview** starts it straight away.

Kodi checks the repository for new versions and updates installed add-ons automatically.
To check now, open **Add-ons → My add-ons**, open the add-on and choose **Update**. Some
add-ons also need `script.module.certifi`, which Kodi installs from its official
repository by itself.

---

## God's Eye Map

![God's Eye Map: Minneapolis at metro and street zoom with live flights, buses and light rail](gifs/gods-eye-map.gif)

A live map of a place you choose, inspired by Bilawal Sidhu's *God's Eye View*. Pick the
location, the zoom and a base map: street, dark, satellite, or NASA's satellite image of
the day. Then turn on the layers you want:

- **Air and space:** live flights with call signs and altitudes, military aircraft, and
  satellites overhead (space stations, the 100 brightest, GPS, weather or Starlink),
  computed on the device from CelesTrak orbits.
- **Weather and Earth:** rain radar (US), infrared clouds, lightning (Americas),
  earthquakes and tropical storms.
- **Getting around:** rail, subway and tram lines worldwide, live transit vehicles in
  cities with open feeds, and traffic flow and incidents (needs a free TomTom key).
- **Weather card:** local conditions and the moon phase.
- **Looks:** optional sensor styles (night vision, FLIR, CRT), dimming and a slow drift to
  protect OLED and plasma screens.

Most layers need no account. To find a place, type its name in **Find a place by name…**
in the settings.

Data from adsb.lol, OpenSky Network, CelesTrak, USGS, NOAA, NASA GIBS, OpenRailwayMap,
transit agencies and TomTom. Map tiles © OpenStreetMap contributors, CARTO and Esri.

## God's World Map

![God's World Map: Waterman butterfly, Robinson as ASCII, Dymaxion and Peirce quincuncial](gifs/gods-world-map.gif)

The whole Earth as an ambient world map. It shows thirteen projections:

- **Classics:** Mercator, Robinson, Winkel tripel, Equal Earth, Gall–Peters and
  cylindrical equal-area.
- **Interrupted maps:** Goode homolosine and Sinu-Mollweide.
- **Unusual ones:** Fuller's Dymaxion, Peirce's quincuncial square, an octahedral
  butterfly, Waterman's butterfly on his W5 polyhedron, and a spinning globe.

Each projection can use a satellite, relief, OpenStreetMap or atlas base map, or be drawn
as **Dwarf Fortress-style ASCII art**, either from geography or from satellite imagery.

Layers:

- **Weather:** infrared clouds, precipitation, temperature, flowing wind particles and
  tropical storms.
- **Events:** earthquakes, erupting volcanoes, wildfires from yesterday's satellite
  passes, lightning, live flights and the International Space Station.
- **Light:** the moving day/night line and city lights on the night side.

It can cycle through projections and styles on a timer, pan or rotate slowly, and keep
working from cached data when the network drops.

Data from NASA (Blue Marble, GIBS, GPM IMERG, FIRMS), NOAA (nowCOAST, NHC), GDACS, USGS,
the Smithsonian Global Volcanism Program, Open-Meteo.com (CC BY 4.0), Natural Earth and
Mapzen terrain tiles. Map tiles © OpenStreetMap contributors, © CARTO.

## Math Clock

![Math Clock: each row is an equation whose answer is the current year, month, day, hour, minute or second](gifs/math-clock.gif)

A clock you solve. The year, month, day, hours, minutes and seconds each appear as a random
equation whose answer is the current value, typeset in Computer Modern like a LaTeX
document. For example, `√144` might stand for the hour, and `log₃(m + 32) = 4` for the
minute.

It is based on the web clock themathclock.com and keeps all its settings: seconds, 24-hour
time, the date, labels, inverted colours and day/night mode.

There are three equation sets:

- **Classic:** the original 17 puzzles.
- **Advanced:** fractions, powers, logarithms, sums, binomials and floors.
- **Algebra 2** (the default): mixes both with quadratics, linear systems, exponential and
  log equations, radicals, absolute values, function composition and inverses, complex
  numbers, sequences and series, 2×2 determinants, permutations and combinations.

Every puzzle has exactly one answer. When a quadratic has two roots, the puzzle says which
one it means.

Equations fade from one to the next, and a slow drift protects OLED screens. It is light
enough for a Fire TV Stick.

Glyphs are rendered from the BaKoMa Computer Modern fonts, as shipped with matplotlib.

## Couchstronomy

![Couchstronomy: the real sky facing east with constellation lines, labels and an object spotlight](gifs/couchstronomy.gif)

*This clip is real time sped up 6×.*

Tell Couchstronomy where your TV is and which way it faces: compass heading, tilt, and
field of view (or screen width and viewing distance). It then shows the patch of sky that
would be outside that window right now, computed for the real time.

**What it shows:**

- About 41,000 stars down to magnitude 8, from the Hipparcos-based HYG catalogue.
- The Sun, and the Moon with its phase and earthshine.
- The planets, with their phases and Saturn's rings.
- Messier and bright NGC objects, shown as real photographs.
- Constellation lines and boundaries.
- Live satellites that cross the screen when they really pass.

Stars drift as the Earth turns. Twilight, daylight, moonlight, light pollution,
atmospheric extinction and refraction are all modelled.

**Labels** can be off (a quiet natural sky), on for named objects, or in **Explorer** mode.
Explorer spotlights one object every 30 seconds with its distance, magnitude, altitude and
azimuth.

**Rendering** is *Realistic* by default: you see only what the eye could, and faint stars
fade out in twilight and moonlight. *Enhanced* brightens faint stars and enlarges the Moon
and planets.

**Accuracy:** stars, Sun and planets are within 5″, the Moon within 10″ and the ISS within
0.02°, checked against JPL ephemerides for 2020–2030. On screen, any error comes from how
precisely you enter your TV's heading, not from the astronomy.

It works offline from the bundled catalogues. Satellite orbits refresh from CelesTrak when
the device is online.

Data: HYG database (CC BY-SA 4.0), d3-celestial (BSD), VSOP87 via astronomia (MIT), NASA
SVS Moon imagery and CelesTrak. The Messier photographs are by Fred Espenak
(AstroPixels.com), used with permission and **not** covered by the MIT licence.

## Screensaver Switcher

A service that picks a different screensaver for different times of day. For example: Math
Clock in the morning, God's World Map during the day, and Black at night.

- **Time windows:** set up to six, each with a start time, an end time and a screensaver
  chosen from the ones you have installed. A default covers the rest of the day.
- **Alternating:** a window can switch between two screensavers every 5–240 minutes.
- **Flexible windows:** a window can cross midnight (22:00–06:00). If two windows
  overlap, the lower-numbered one wins.
- **Instant switching:** at each window boundary it changes Kodi's screensaver, and
  restarts one that is already running so the change shows within a second or two.
- **Manual choices stick:** a screensaver you pick by hand stays until the next window
  boundary.

Open **Programs → Screensaver Switcher** to see what is scheduled now, apply the schedule,
preview it or change the settings.

---

## Sheetcards

![Sheetcards: the deck picker, flashcards that flip, multiple choice with right and wrong answers, the pause sheet and the results](gifs/sheetcards.gif)

Flashcards from any Google Sheet: an app you study with, and a screensaver that plays the
cards by itself. Put questions in column A and answers in column B. Every tab is a deck.
Share the sheet as "Anyone with the link can view" and paste its ID or link in the settings.
It needs no Google account or API key.

- **Three modes:** Flashcard (the card flips to the answer), Multiple choice (3 or 4
  options) and Mixed. Wrong options come from the deck's other answers, picked to look
  plausible: years with years, single words with single words, similar lengths.
- **The app:** pick decks, then answer with the remote, a mouse or a touch screen (number
  keys 1–4 answer directly). You get a score, streaks, and a results screen listing the
  cards you missed, with **Review missed**.
- **Spaced repetition:** Leitner boxes bring cards back after 1, 2, 4, 8 and 16 days. A
  missed card comes back 3–5 cards later in the same session.
- **The screensaver:** a question with a timer bar, then the answer, card after card. Any
  key exits at once. The card drifts slightly at each change to protect OLED screens. It
  can also show a clock and dim after a while.
- **Looks and offline use:** Night, Day or Auto themes with six accent colours or your own.
  Cards are cached, so they keep working without a network.

The app is under **Program add-ons** and the screensaver under **Look and feel →
Screensaver**. By default the screensaver uses the app's sheet and decks.

---

## RSS Live Tiles

![RSS Live Tiles: the hub of live tiles, a tile expanding into its story, the menu, the layouts and tile styles, and the screensaver](gifs/rss-live-tiles.gif)

Your RSS and Atom feeds as a wall of flat, coloured live tiles, in the style of Windows Phone
and the Windows 8 Start screen. It comes as an app you browse with the remote and a screensaver
that runs by itself. Three sample feeds are included (BBC News, r/kodi and NASA Image of the
Day). Add your own in **Manage feeds**.

- **Live tiles:** pictures come from the feeds themselves. Tiles flip to the next story, peek
  from the picture to the headline and summary, and count new items. Calm, Normal or Lively, or
  fades only with Reduced motion.
- **Five layouts and three styles:** Feed groups (a scrolling hub with one group per feed),
  Mixed wall, Magazine, Spotlight and Mosaic, in Classic, Modern or Outline style.
- **Your colours:** the 20 Windows Phone accent colours or your own, a different accent per feed
  if you like, and Night / Day themes that can switch by the clock or at sunrise and sunset.
- **Read the story:** Select expands a tile into the full story with a QR code to open it on your
  phone. Left and Right go through the feed. Podcast and video enclosures play straight away.
- **Feeds:** add, edit, reorder and delete them in the app, or import and export OPML. They
  refresh in the background and everything works offline from the cache.
- **The screensaver:** fills the screen with tiles, rotates fresh stories in every few minutes,
  can show a clock, dims at night and shifts slightly to protect OLED screens. Any key exits
  at once.

The app is under **Program add-ons** (press **Menu** on a tile for Manage feeds, layouts and
settings) and the screensaver under **Look and feel → Screensaver**. By default the screensaver
uses the app's feeds and look.

---

## Word Clock

![Word Clock: IT IS FIVE TO TWO PM turning to TWO O'CLOCK, a ripple, midnight in blue with a glow, rainbow words, an amber dot-matrix face, a serif walnut card, minute dots, and the day colours blending into night](gifs/word-clock.gif)

A word clock like the ones sold for walls and desks: an 11 × 11 grid of letters where the words
that tell the time light up. At 1:55 PM it reads **IT IS FIVE TO TWO PM**, and at ten past
twelve at night **IT IS TEN PAST MIDNIGHT**. Out of the box it looks like the classic graphite
word clock: bold white letters over dim grey ones on a rounded dark card.

- **Fonts:** eight to choose from: Inter (the default), Montserrat, Raleway, Playfair Display,
  JetBrains Mono, Comfortaa, a dot-matrix font and a stencil font. Lit letters can be bold.
- **Colours:** eight palettes (Graphite, Paper, Midnight blue, Amber LED, Terminal green, Rose,
  Walnut, Steel) or your own, chosen with colour pickers. Lit words can also each have their own
  colour, or slowly cycle through the rainbow. Add a soft or strong glow, and make the unlit
  letters faint or hide them.
- **Day and night:** separate day and night colours that switch at the times you set, blending
  over a few seconds, and optional dimming at night.
- **The clock:** round down (like most word clocks) or to the nearest five minutes, minute dots
  in the corners, and IT IS, A QUARTER, AM/PM and MIDNIGHT can each be turned off.
- **Screen:** a rounded card, a square card or full screen, any size, a fade or ripple when the
  time changes, dimming, and a slow drift to protect OLED screens. Any key exits at once.

It is under **Look and feel → Screensaver**.

---

## Sand Clock

![Sand Clock: 17:52 crumbling every second into neon sand that piles into striped mountains, a pixel font crumbling into round beads, a digital font in a slow rainbow, and a stencil clock in desert sand](gifs/sand-clock.gif)

A big clock that crumbles into sand. Just before each second ticks over, the digits break into
grains that fall, scatter and slide into heaps at the bottom of the screen. Every change brings
a new colour, so the heaps build up in stripes, and they sink slowly through the floor so the
screen never fills up.

- **Fonts:** nine, from Inter and Montserrat to a digital, a pixel, a dot-matrix and a stencil
  font, in light, regular or bold.
- **Sand:** fine, medium or coarse grains that look like sand, flat squares or round beads,
  with floaty, normal or heavy gravity, and as tall a pile as you like.
- **What crumbles:** the whole clock every second, or only the digits that change. Turn seconds
  off and it crumbles once a minute.
- **Colours:** a new colour every change or for each digit, eight palettes (Neon, Desert sand,
  Ocean, Sunset, Candy, Forest, Ice, Greyscale), one colour of your own, or a slow rainbow.
- **Day and night:** a different palette at night, dimming, and a slow drift to protect OLED
  screens. Any key exits at once.

It is under **Look and feel → Screensaver**.

---

## Jeopkodi

![Jeopkodi: a $800 clue in CHAMPAGNE PROBLEMS, the response WHO IS MICHELANGELO?, a Final Jeopardy clue about the ravens of the Tower of London, and a clue shown without the category and value](gifs/jeopkodi.jpg)

Jeopardy! as a screensaver. A clue comes up on the classic blue screen in white capitals with a
drop shadow, just like on the show, and a few seconds later the response appears, phrased as a
question. Then the next clue. There are over half a million clues from 42 seasons, shuffled, so
it never runs out.

- **Difficulty:** easy ($200 and $400), medium ($600) and hard ($800 and $1000) clues, each on
  or off, and Daily Doubles and Final Jeopardy if you want them.
- **Timing:** how long a clue stays up before the response (long clues get a little extra), and
  how long the response stays up.
- **Display:** the category and the dollar value (in Jeopardy yellow) at the top, or just the
  clue; WHAT IS / WHO IS phrasing; text size and dimming. Any key exits at once.

It is under **Look and feel → Screensaver**. An unofficial fan project, not affiliated with
Jeopardy Productions, Inc.

---

## DVD Logo

![DVD Logo: the white logo bouncing across a black screen, landing exactly in a corner, then lining up another corner and veering away at the last second](gifs/dvd-logo.gif)

The classic DVD screensaver: the white logo drifts across a black screen and bounces off the
edges. Left alone it behaves like the real thing, so a corner hit is rare — but the corner
tricks can make it happen.

- **Corner tricks:** *Off*, *Hit the corner* (it quietly bends its path by a few degrees at a
  bounce and then lands exactly in the corner), *Veer off at the last second* (it lines up a
  perfect hit and swerves away from the corner half a second before arriving), or *Alternate*
  (the default: hit a corner, then fake the next one). A slider sets how often it tries.
- **The logo:** any size, from a slow drift to a quick scoot.
- **Colours:** white, a new colour on every bounce (the classic), a new colour only when it
  hits a corner, a slow rainbow, or one colour of your choice; the background is any colour too.

Every move is a Kodi animation, so it is light enough for a Fire TV Stick, and any key or click
ends it at once.

It is under **Look and feel → Screensaver**. The DVD logo is a trademark of DVD Format/Logo
Licensing Corporation; this is an unaffiliated fan project.

---

## Tetris AI

![Tetris AI: the AI stacks tetrominoes edge to edge, clears rows, and plays around a clock made of blocks suspended above the floor](gifs/tetris.gif)

An AI plays Tetris across the whole screen, forever. The playfield is 18 rows tall and reaches
all four edges; the *block size* sets how wide the blocks are in pixels, so a wide screen can
show 20 big columns at the default 96 pixels or as many as 60 narrow ones at 32. All seven
classic tetrominoes fall in the modern Guideline shapes and colours.

- **AI skill:** *Perfect*, *Expert*, *Skilled*, *Average* or *Beginner*. Perfect always picks
  the best placement; the lower levels increasingly choose a runner-up, so the stack grows and
  the board tops out now and then before clearing itself and starting again.
- **Clock:** on by default, as text in the top-left panel or — *Clock style: Tetris blocks* —
  as HH:MM (with seconds when the board is wide enough) built from blocks on the floor or
  suspended in mid-air. The block clock is part of the game: pieces collide with the digits and
  have to be placed around them, the digits never fall, rows clear around them, and the time is
  redrawn once a minute (every second with seconds on) — a piece resting on a digit that
  vanishes falls into the gap rather than hanging in the air.
- **Look:** seven classic colours, the muted NES palette, Neon, Pastel, Monochrome, Game Boy,
  Sunset, Ocean, Vaporwave, or your own seven colours; the background is any colour, the block
  width runs from 32 to 96 pixels, and the grid, score panel, its opacity, the landing ghost and
  the next-piece preview can each be switched off.
- **Speed:** an overall slider from 25% to 400%, an optional speed-up with each level, and a
  starting level up to 10.

Any key or click ends it at once.

It is under **Look and feel → Screensaver**. Tetris is a trademark of The Tetris Company;
this is an unaffiliated fan project.

---

## Tetris AI (OpenGL)

The same AI plays the same game, but the screen is drawn in native code and OpenGL instead of by
Kodi image controls, so nothing moves in cell-sized steps: the active piece slides and falls at
sub-pixel positions on eased curves, dropped pieces land exactly where the ghost showed, a line
clear flashes twice and collapses into place, and a piece stranded on a clock digit that changes
slides down into the gap it leaves. Everything is drawn as antialiased rounded tiles, so it
stays sharp at every block size and on high-DPI screens.

It has the same 25 settings as Tetris AI: the five skill levels, speed and progressive levels,
nine colour schemes or your own seven colours, the block size (96 pixels down to 32, so 20 to 60
columns), the grid, the score panel and its opacity, the ghost and next-piece preview, the
background colour, and the clock (text or blocks, 12/24 hour, seconds, on the floor or floating,
any colour). The engine is a C++ port of the Python one, so the AI behaves the same.

This is a native add-on, so Kodi needs the build for its platform:

- **Tetris AI (OpenGL, macOS and 64-bit Android)** — macOS (Intel and Apple Silicon) and 64-bit
  Android.
- **Tetris AI (OpenGL, 32-bit Android)** — 32-bit Android Kodi: the Fire TV, many Google TV boxes
  and the Chromecast with Google TV. Install this one on those devices; the other one is for
  64-bit Android and macOS, and its library cannot load in a 32-bit Kodi.

Any key or click ends it at once. It is under **Look and feel → Screensaver**. Tetris is a
trademark of The Tetris Company; this is an unaffiliated fan project.

---

## Endless World (OpenGL)

![Endless World: a slow glide over hills, a lake and forests that are generated as they come into view, with rippling water and drifting clouds](gifs/endless-world.gif)

A camera flies slowly over an infinite landscape generated from noise: mountains, green hills,
sandy beaches, lakes and seas, pine and broadleaf forests, and a sky with drifting clouds.
Nothing is loaded from disk except the textures: the height of every hill and the position of
every tree come from the seed when a chunk comes into view, and the world is redrawn in five
levels of detail around the camera, so it never ends and the ground near you stays detailed.
It is a port of [infworld](https://github.com/NULLPTR-ERROR/infworld) by Jeremy Li "Nullptr
Error".

The flight can glide, circle or drift; you pick the seed (0 is a new world every start), how far
to draw, the terrain and tree detail, the tree density, the speed and the height, and whether to
look around while flying and to draw the sea. Automatic resolution and adaptive quality keep a
slow box smooth.

This is a native add-on, so Kodi needs the build for its platform:

- **Endless World (OpenGL)** — macOS (Intel and Apple Silicon) and 64-bit Android.
- **Endless World (OpenGL, 32-bit Android)** — 32-bit Android Kodi: many Google TV boxes and the
  Chromecast with Google TV. Install this one on those devices; the other one's library cannot
  load in a 32-bit Kodi.

Any key or click ends it at once. It is under **Look and feel → Screensaver**. The code is MIT
licensed; the textures are used under CC-BY-SA 3.0, with the credits in the add-on's
`LICENSE.txt` and `resources/textures/credits.txt`.

---

## Licence

The add-on code is MIT-licensed. Bundled data and imagery keep their own licences, listed
above and in each add-on's `LICENSE.txt` or `addon.xml`.

All data comes from public sources. It is for personal use, so follow each provider's
terms. Positions of flights, satellites and events are as accurate as the feeds they come
from.

# Word Clock for Kodi: Specification

**Status:** Implemented as v1.0.0 (see §8 for implementation notes)
**Add-on ID:** `screensaver.wordclock` (extension point `xbmc.ui.screensaver`)
**Target:** Kodi 20 "Nexus" and later, Python 3 (custom colour pickers need Kodi 20's `colorbutton`)
**Location:** `screensaver.wordclock/` at the repository root, next to the other add-ons

---

## 1. Overview

A screensaver that tells the time in words on a fixed grid of letters, like the QlockTwo-style
word clocks sold for walls and desks. The letters that spell the time are lit, the rest stay
dim: at 1:55 PM the clock reads **IT IS FIVE TO TWO PM**.

The face reproduces one reference design exactly: an 11 × 11 grid on a rounded graphite card,
bold white lit letters over dim grey ones. Everything about its look can then be changed in the
settings: fonts, colours (separately for day and night), glow, frame, size, transitions.

### 1.1 Goals
- Reproduce the reference grid letter for letter, and its colours and proportions by default.
- Correct phrasing for every minute of the day, including MIDNIGHT and AM/PM.
- Settings for colours (presets and custom), fonts, day/night mode, dimming and motion.
- Light on CPU: nothing is drawn in Python; Kodi fades pre-rendered glyph images.
- Runs on a Fire TV Stick as well as a desktop.

### 1.2 Non-goals (v1)
- Other languages or grid layouts (the reference grid is English only).
- Seconds, dates or digits.
- Alarms, chimes or any sound.

---

## 2. The grid

Eleven rows of eleven letters, transcribed from the reference image:

```
 col  1 2 3 4 5 6 7 8 9 10 11
  1   I T L I S A S A M P M
  2   A C Q U A R T E R D C
  3   T W E N T Y F I V E X
  4   H A L F B T E N F T O
  5   P A S T E R U N I N E
  6   O N E S I X T H R E E
  7   F O U R F I V E T W O
  8   E I G H T E L E V E N
  9   S E V E N T W E L V E
 10   T E N S E O C L O C K
 11   M I D N I G H T N O O
```

### 2.1 Words (row, first column, length)

| Word | Position | Word | Position |
|---|---|---|---|
| IT | 1, 1, 2 | ONE | 6, 1, 3 |
| IS | 1, 4, 2 | SIX | 6, 4, 3 |
| AM | 1, 8, 2 | THREE | 6, 7, 5 |
| PM | 1, 10, 2 | FOUR | 7, 1, 4 |
| A | 2, 1, 1 | FIVE (hour) | 7, 5, 4 |
| QUARTER | 2, 3, 7 | TWO | 7, 9, 3 |
| TWENTY | 3, 1, 6 | EIGHT | 8, 1, 5 |
| FIVE (minutes) | 3, 7, 4 | ELEVEN | 8, 6, 6 |
| HALF | 4, 1, 4 | SEVEN | 9, 1, 5 |
| TEN (minutes) | 4, 6, 3 | TWELVE | 9, 6, 6 |
| TO | 4, 10, 2 | TEN (hour) | 10, 1, 3 |
| PAST | 5, 1, 4 | O'CLOCK | 10, 6, 6 (`OCLOCK`) |
| NINE | 5, 8, 4 | MIDNIGHT | 11, 1, 8 |

The other letters are filler. The grid has no NOON (row 11 ends `NOO`), so 12 in the daytime is
always TWELVE.

### 2.2 Phrases

The minute is first reduced to a five-minute step `m5` (§2.3). Then:

| m5 | Phrase | m5 | Phrase |
|---|---|---|---|
| 0 | IT IS *hour* O'CLOCK | 30 | IT IS HALF PAST *hour* |
| 5 | IT IS FIVE PAST *hour* | 35 | IT IS TWENTY FIVE TO *next* |
| 10 | IT IS TEN PAST *hour* | 40 | IT IS TWENTY TO *next* |
| 15 | IT IS A QUARTER PAST *hour* | 45 | IT IS A QUARTER TO *next* |
| 20 | IT IS TWENTY PAST *hour* | 50 | IT IS TEN TO *next* |
| 25 | IT IS TWENTY FIVE PAST *hour* | 55 | IT IS FIVE TO *next* |

followed by AM or PM. *next* is the following hour, and its AM/PM: 11:45 AM is
QUARTER TO TWELVE PM, because the hour it names is in the afternoon.

- **Midnight:** when the named hour is 0 (12 at night) and "Say MIDNIGHT" is on, the hour word is
  MIDNIGHT, O'CLOCK is dropped and so is AM/PM: IT IS MIDNIGHT, IT IS TEN PAST MIDNIGHT,
  IT IS TEN TO MIDNIGHT (11:50 PM). With the setting off it is TWELVE … AM.
- **Options:** IT IS, the A before QUARTER and AM/PM can each be turned off.

### 2.3 Rounding and minute dots

- **Round down** (default, like most word clocks): 1:55 to 1:59 all read FIVE TO TWO.
- **Round to nearest:** 1:57:30 onwards reads TWO O'CLOCK. Rounding is on the seconds too, so the
  phrase changes at :57:30, :02:30 and so on.
- **Minute dots** (off by default, round-down only): four dots, one in each corner of the card,
  light clockwise from the top left to show 1 to 4 minutes past the step.

---

## 3. Look

### 3.1 Proportions (from the reference)

- Card: a square, 80% of the screen height by default, centred, corner radius about 12% of its
  side. Background outside the card is black.
- Letters: the grid spans the middle 70% of the card in both directions (15% margins). Cap height
  is about half the cell pitch. Lit letters bold, unlit letters regular, both uppercase.
- Colours: card `#1B1B1D`, unlit letters `#474749`, lit letters `#FFFFFF`.

### 3.2 Fonts

Kodi add-ons cannot install fonts without editing the skin, so each letter is a pre-rendered
white PNG in two weights, tinted at run time. All fonts are SIL Open Font License 1.1, from
Google Fonts. Only the 24 letters the grid uses are rendered.

| Setting | Font | Unlit / lit weight |
|---|---|---|
| Modern sans (as pictured) | Inter | 400 / 700 |
| Geometric | Montserrat | 400 / 700 |
| Elegant thin | Raleway | 200 / 500 |
| Serif | Playfair Display | 400 / 800 |
| Monospace | JetBrains Mono | 400 / 800 |
| Rounded | Comfortaa | 400 / 700 |
| Dot matrix | Doto (round dots) | 400 / 900 |
| Stencil (laser cut) | Big Shoulders Stencil | 500 / 800 |

Glyphs share a baseline per font and are centred on their ink horizontally, so every font sits
in the same cells. "Lit letters" can be Bold (default) or the same weight as the unlit letters.

### 3.3 Palettes

Each palette is four colours: background, card, lit, unlit.

| Palette | Background | Card | Lit | Unlit |
|---|---|---|---|---|
| Graphite (as pictured) | `#000000` | `#1B1B1D` | `#FFFFFF` | `#474749` |
| Paper | `#D9D5CC` | `#F4F1EA` | `#1A1A1A` | `#D2CDC2` |
| Midnight blue | `#000000` | `#0E1628` | `#8FD3FF` | `#22304C` |
| Amber LED | `#000000` | `#140C04` | `#FFB347` | `#33240F` |
| Terminal green | `#000000` | `#050D07` | `#4CFF7A` | `#163520` |
| Rose | `#120A0E` | `#2A1520` | `#FFC2D4` | `#4D2E3C` |
| Walnut | `#0F0A06` | `#3B2A1E` | `#FFF1D6` | `#5A4332` |
| Steel | `#0B0F11` | `#263238` | `#E0F7FA` | `#3E4F57` |
| Custom | four colour pickers |||

### 3.4 Day and night

- **Colour mode:** Night colours all the time (default, as pictured), Day colours all the time,
  or Day and night by the clock.
- **Day starts / Night starts** times (07:00 / 21:00). Day and night each have their own palette
  (defaults Paper and Graphite) and their own custom colours.
- **Dim at night (%)** dims everything during night hours, whatever the colour mode.
- Switching between day and night blends the colours over 8 seconds.

### 3.5 Effects

- **Unlit letters:** Shown (as pictured), Faint (blended 55% toward the card) or Hidden.
- **Glow:** Off (as pictured), Soft or Strong: a blurred copy of each lit letter behind it in the
  lit colour.
- **Lit colour:** From the palette, Each word a different colour (a fixed set of 12 hues, so a
  word keeps its colour), or Slowly cycle through the rainbow (one turn every 10 minutes).
- **Frame:** Rounded card (as pictured), Square card, or Full screen with no card.
- **Clock size:** 40–100% of the screen height. **Letter size:** 70–140% of the default.

### 3.6 Motion

- **Transition** when the time changes: Fade (0.8 s cross-fade between unlit and lit letters),
  Ripple (the same fade, delayed cell by cell in reading order, so changes sweep down the face)
  or Cut.
- **Drift** (on by default): the whole clock moves along a slow Lissajous path, up to 24 px, one
  step a minute, to protect OLED and plasma screens.
- **Dim (%)** dims everything all the time.
- Any key or remote input exits at once.

---

## 4. Settings

| Category | Settings |
|---|---|
| Clock | Rounding; Light IT IS; Say A QUARTER; Light AM and PM; Say MIDNIGHT; Minute dots |
| Letters | Font; Lit letters weight; Unlit letters; Glow; Letter size |
| Colours | Night palette; Day palette; Lit colour; custom night and day colours (when Custom) |
| Day and night | Colour mode; Day starts; Night starts; Dim at night |
| Screen | Frame; Clock size; Transition; Dim; Drift |

The table lives in `resources/lib/config.py`; `tools/make_settings_wordclock.py` turns it into
`settings.xml` and `strings.po` (shared generator `tools/make_settings.py`, which gains a
`colour` kind for `colorbutton` controls).

---

## 5. Architecture

```
screensaver.wordclock/
  addon.xml, default.py, icon.png, fanart.jpg, LICENSE.txt
  resources/settings.xml, language/resource.language.en_gb/strings.po   (generated)
  resources/lib/grid.py         the grid, words and phrase rules (no Kodi imports)
  resources/lib/config.py       settings table, palettes, read() (no Kodi imports)
  resources/lib/look.py         colours, day/night, effects, layout geometry (no Kodi imports)
  resources/lib/screensaver.py  the Kodi window and clock thread
  resources/media/fonts/<font>/<L><w>.png   glyphs: r regular, b bold, gr/gb their glows
  resources/media/white.png, dot.png
  resources/skins/Default/1080i/screensaver-wordclock.xml   background and card
  resources/skins/Default/media/card_round.png, card_square.png
tools/make_wordclock_media.py   glyphs, card textures, icon, fanart (Pillow, fonts downloaded)
tools/make_settings_wordclock.py
tools/preview_wordclock.py      draws the face with Pillow for a given time and settings
tests/test_wordclock.py
```

### 5.1 Rendering

- The window XML holds the background and the card. The card is an image with a 9-slice
  `border`, so its corners keep their radius at any size; its colour comes from a window
  property.
- Python adds three image controls per cell: unlit glyph, glow (only if glow is on) and lit
  glyph, plus two per minute dot. That is 242–363 controls, created once.
- Each lit control has a visibility condition on a Home window property
  (`wordclock.c<n>`); the unlit control has the inverse. Kodi plays `Visible`/`Hidden` fade
  animations when a property flips, so a time change is a handful of `setProperty` calls and no
  per-frame work in Python. Ripple adds a per-cell `delay`.
- Colours are `setColorDiffuse` on white glyphs. A clock thread wakes every second, works out
  the phrase, flips changed properties, and updates colours only when they change (day/night
  blend, rainbow cycle, dimming).
- Test hook: if the Home property `wordclock.demo` holds `HH:MM` or `HH:MM:SS`, the clock shows
  that time instead of the real one. Used by the GIF capture and for manual checks.

### 5.2 Performance

No images are generated at run time and nothing is drawn in Python. Properties change at most
once a minute (dots) or every five minutes. Expect Kodi's own idle-GUI CPU use.

---

## 6. Testing

- `tests/test_wordclock.py`, offline: the grid matches §2 letter for letter; every word's
  letters are where §2.1 says; all 1,440 minutes of the day give a phrase whose words read in
  grid order and never overlap; spot checks (1:55 PM is IT IS FIVE TO TWO PM, 0:00 MIDNIGHT,
  11:50 PM TEN TO MIDNIGHT, 11:45 AM QUARTER TO TWELVE PM); rounding and dots; option toggles;
  settings table defaults and `read()` fallbacks; palettes, hex parsing, blending and the
  day/night schedule across midnight; layout stays on screen at every size and drift offset.
- In Kodi 21 on macOS: install with `tools/kodi.py`, run it, check every font, palette, frame,
  transition and day/night, check exit on input, capture the demo GIF.

---

## 7. Decisions

| Decision | Why |
|---|---|
| Glyph PNGs instead of Kodi fonts | Add-ons cannot register fonts; images allow any font and weight, and tint cleanly. |
| Visibility conditions on Home properties | Kodi animates the fades itself; Python does nothing between changes. |
| No NOON | The reference grid does not contain it; the spec keeps the grid exact. |
| AM/PM follows the named hour | QUARTER TO TWELVE AM at 11:45 AM would be wrong. |
| Defaults match the picture | Night palette all the time, Inter, bold, no glow, no dots, rounded card. |

---

## 8. Implementation notes (v1.0.0)

Built and tested in Kodi 21.1 on macOS.

- **Visibility conditions work on Python controls.** `setVisibleCondition()` on a
  `ControlImage` added with `addControls()`, against `Window(Home).Property(...)`, plus
  `setAnimations([('Visible', ...), ('Hidden', ...)])`, gives Kodi-driven cross-fades. The unlit
  glyph fades out while the lit one fades in. Ripple is the same fade with `delay=12 ms × cell`.
- **The card is XML, the letters are Python.** The window XML holds the background and two card
  images (rounded with `border="104"`, and square), coloured by `$INFO[Window(Home).Property(...)]`.
  Python only positions them. Python-added controls always draw above XML ones, which is the
  order needed.
- **Proportions.** Measured from the reference: cell pitch 6.72% of the card side, cap height
  0.6 of the pitch, card `#1B1B1D`, unlit `#474749`. The Pillow preview of the defaults matches
  the reference image to within a pixel at 332 px.
- **Speed.** About 3% CPU on a Mac while it runs (the same as idle Kodi), and exit in 0.02 s.
  Media is 768 small glyph PNGs (about 1 MB).
- **Settings strings.** If you symlink the add-on into a running Kodi, its settings dialog can
  show blank labels until Kodi restarts. A normal install is not affected.
- **Colour pickers** (`<control type="colorbutton"/>`) render as a hex value with a swatch. The
  custom colour groups show only when that palette is set to Custom.
- **Demo GIF.** macOS screen recording needs a permission prompt, so the GIF in
  `release/gifs/word-clock.gif` was made from Kodi's own `TakeScreenshot` frames (about 2 a
  second), taken by a script inside Kodi that uses the `wordclock.demo` hook to step through
  times and settings.

### 8.1 Not done yet
- Tested on macOS only, not yet on a Fire TV Stick.
- Other languages would each need their own grid.

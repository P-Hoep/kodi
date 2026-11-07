# Sand Clock screensaver (`screensaver.sandclock`)

A digital clock that crumbles into sand. Based on a video of a 64 × 64 LED matrix clock in
which HH:MM:SS shows in a new colour each second, then falls apart into grains that pile up in
layered heaps at the bottom. The LED look is not the point; the effect is: the clock dissolving
into sand, continuously.

## 1. Behaviour

- **The time** is drawn large in a real font (HH:MM:SS by default, or HH:MM; 24 or 12 hour).
- **Crumbling.** Shortly before the time changes, the characters that are about to change
  (or the whole clock, the default, as in the video) turn into grains: one grain per cell of a
  screen-wide grid whose centre lies inside the glyph. The grains let go over a short window
  (lower ones first, with random scatter), fall under gravity while drifting slightly sideways,
  land on the pile and slide down its side while a neighbouring column is lower, which gives
  the 45° slopes of dry sand. The new time appears the moment the old one has let go.
- **The pile** never fills the screen. The floor is a slow drain: the whole pile sinks at a
  speed that keeps it near its target height (default 30 % of the screen), so the heap stays
  roughly the same size while new layers land on top and old ones sink out of sight.
- **Colours.** A new colour each change (default, as in the video), a new colour for each digit
  that changes, one colour, or a slow rainbow. Because each change lands as its own layer, the
  pile is striped with past colours.

## 2. Settings

| Category | Setting | Options (default first or marked) |
|---|---|---|
| Clock | Show seconds | on |
| | Hours | 24 hour, 12 hour |
| | What crumbles | Only digits that change, **Whole clock** |
| | Crumble speed | Slow, **Normal**, Quick (0.7 / 0.45 / 0.3 s release window) |
| Font | Font | Inter, Montserrat, Orbitron, Pixelify Sans, Doto, JetBrains Mono, Comfortaa, Playfair Display, Big Shoulders Stencil |
| | Weight | Light, Regular, **Bold** |
| | Clock width | 40–95 % of the screen (80) |
| | Clock position | Upper part, Centre |
| Sand | Grain size | Fine 6 px, **Medium 9 px**, Coarse 14 px |
| | Grains look like | Sand (shaded grains), Flat squares, Round beads |
| | Gravity | Floaty, **Normal**, Heavy (1400 / 3000 / 6000 px/s²) |
| | Pile height | 10–50 % of the screen (30) |
| Colours | Colour | New colour each change, New colour per digit, One colour, Slow rainbow (2 min per turn) |
| | Colours to pick from | Neon (as in video), Desert sand, Ocean, Sunset, Candy, Forest, Ice, Greyscale |
| | Colour of the clock and sand | colour picker (one-colour mode) |
| | Background | colour picker (black) |
| Day and night | Colours at night | Same as by day, or any palette |
| | Dim at night, night times, dim all the time | |
| | Slowly drift the clock | on (OLED) |

When the whole clock crumbles, the grain size steps up (Fine → Medium → Coarse) until one
crumble is at most 1000 grains, so a Fire TV Stick is not asked to animate thousands at once.

## 3. Architecture

- `resources/lib/config.py`: the settings table, fonts and palettes (no Kodi imports).
  `tools/make_settings_sandclock.py` generates `settings.xml` and `strings.po` from it.
- `resources/lib/sand.py`: layout, glyph → grains, the physics (`Pile.drop`), the sinking
  pile (`sunk(t)` piecewise linear with scheduled speed changes), strips, the speed controller
  and colours (no Kodi imports; tested offline).
- `resources/lib/screensaver.py`: the Kodi side. **Python plans, Kodi animates.**
  - Each falling grain is an image control with a chain of `Conditional` slide animations
    (wait, fall with quadratic easing, sideways drift, slide down the pile, sink with it), all
    keyed to one Home property per batch that Python sets at the planned start time.
  - Every 1.5 s, landed sand is merged into **strips** (runs of same-coloured grains in a
    column, cut every 32 rows) drawn as one image each, sinking with one long slide animation.
    Unchanged strips keep running, so a rebuild only touches the top of the pile.
  - The sinking speed is `inflow / footprint × height / target`, applied from the first rebuild
    after every grain in the air has landed, so sand already falling lands where planned.
  - Strip textures (`media/grains/<look>/<n>_<v>.png`) give grain *i* of a strip the same shade
    in every length, so growing strips do not shimmer.
- Glyphs are white PNGs tinted with `setColorDiffuse` (add-ons cannot load fonts), rendered by
  `tools/make_sandclock_media.py` with lining, tabular figures, plus ink masks in `fonts.json`.
- Closing: callbacks only set a stop flag and post `Dialog.Close(<id>,true)`. Calling
  `Window.close()` holds Python's lock while waiting for Kodi's main thread, which deadlocked
  Kodi when a screensaver was re-activated while this one was closing.

## 4. Testing

- `python3 -m unittest tests.test_sandclock`: settings, every font's glyphs and masks, layout
  for every font/size/position, the grain budget, flights adding up to their landing cells, no
  floating sand, dry-sand slopes, continuous sinking, strips, the pile staying within 30 % of
  its target over 100 s in both modes, colours and night.
- Kodi 21.1 on macOS: all fonts, looks and colour modes; the pile holds its height; about 50 %
  of one core on a retina Mac (Kodi alone uses about 37 % while anything animates).
- The Home property `sandclock.demo = HH:MM:SS` starts the clock at that time (then it runs on).

## 5. Not done yet

- Not tested on a Fire TV or other low-power box.
- The close-path fix (posted `Dialog.Close`) passed single wakes but the repeated
  wake/re-activate stress run was not finished.

# Kodi Flashcards Add-ons — Development Spec

Nov 6, 2026 · @Patrick

Addon Name: Sheetcards

## Overview

We are building two Kodi 21+ add-ons that turn a publicly shared Google Sheet into a polished flashcard experience: a **screensaver** that plays cards hands-free, and an **application** the user drives with the remote, mouse or touch. Both share one core library, so data loading, card logic and theming are written once.

Working name is **Sheetcards** (rename freely; IDs below follow it).

### Goals

- Zero-setup data: paste a sheet ID, pick decks, done. No API keys, no Google login.
- Two study modes in both add-ons: **Flashcard** (question, then reveal) and **Multiple choice**, plus **Mixed**.
- A clean, premium look that does not depend on the active Kodi skin's styling.
- Day / Night / Auto themes and a user-chosen accent colour.
- Application extras: tap-to-answer, score and streaks, spaced repetition, deck ordering, offline cache.

### Non-goals (v1)

- Editing cards from inside Kodi.
- Private sheets or OAuth.
- Images, audio or rich formatting inside cards (sheet is text-only: Question | Answer).
- Syncing progress between devices.

### Decisions already made

| Topic | Decision |
| --- | --- |
| Sheet columns | Column A = Question, column B = Answer. Nothing else is required. |
| Wrong answers for multiple choice | Generated automatically from other answers in the same deck |
| Decks | Each sheet tab is a deck; the user selects one, several or all |
| Minimum Kodi | 21 Omega (Python 3, `xbmc.python` 3.0.1) |
| App extras | Score and streaks, spaced repetition, deck order options, offline cache |
| Delivery | Three add-ons added to the existing add-on repo |

## Add-on structure

Ship three add-ons: a shared library and two thin front-ends. The library owns everything except input handling and session flow, which is what actually differs between screensaver and app.

| Add-on ID | Type / extension point | Responsibility |
| --- | --- | --- |
| `script.module.sheetcards` | `xbmc.python.module` | Sheet fetch, CSV parse, cache, deck model, distractors, spaced repetition store, theme engine, shared WindowXML + textures |
| `screensaver.sheetcards` | `xbmc.ui.screensaver` | Auto-play loop, exits instantly on any input |
| `script.sheetcards` | `xbmc.python.script` (`<provides>executable</provides>`) | Deck picker, interactive study, scoring, results |

Both front-ends `<import addon="script.module.sheetcards" version="1.0.0"/>` and `<import addon="xbmc.python" version="3.0.1"/>`. No third-party Python dependencies: use `urllib.request`, `csv`, `json` from the standard library.

### Repo layout

```
script.module.sheetcards/
  addon.xml
  lib/sheetcards/
    __init__.py
    sheet.py          # URL building, fetch, tab discovery
    parser.py         # CSV -> Card list, header detection
    cache.py          # addon_data cache read/write, freshness
    deck.py           # Card, Deck, ordering strategies
    choices.py        # multiple-choice distractor generation
    srs.py            # Leitner boxes, progress JSON
    theme.py          # palette resolution, day/night/auto
    ui/
      card_window.py  # base WindowXMLDialog shared by both front-ends
      fonts.py        # length-based font bucket selection
  resources/
    skins/Default/1080i/sheetcards-card.xml
    skins/Default/1080i/sheetcards-decks.xml
    skins/Default/1080i/sheetcards-results.xml
    skins/Default/media/   # white rounded-rect, pill, glow, check, cross PNGs
    language/resource.language.en_gb/strings.po
screensaver.sheetcards/
  addon.xml
  default.py
  resources/settings.xml
  resources/language/resource.language.en_gb/strings.po
  resources/icon.png, fanart.jpg
script.sheetcards/
  addon.xml
  default.py
  resources/settings.xml
  resources/language/...
  resources/icon.png, fanart.jpg
```

WindowXML lookup is per add-on, so the front-ends open the windows with the **library's** path: `CardWindow('sheetcards-card.xml', xbmcaddon.Addon('script.module.sheetcards').getAddonInfo('path'), 'Default', '1080i')`. All textures are plain white shapes tinted with `colordiffuse`, which keeps one asset set for every theme.

Match the existing repo's conventions for versioning, `addons.xml` generation, zip packaging and changelogs; those are not known yet (see open questions).

## Data source

Cards come from Google's public CSV export, one request per tab, with no API key. The sheet must be shared as "Anyone with the link can view".

### Sheet ID input

- Setting `sheet_id` takes the bare ID, e.g. `1oOBsLmJIfHB57YVifu1Vu1g1MdiuApkiytAl4o_leoo`.
- Also accept a pasted full URL: extract with `/d/([A-Za-z0-9_-]{20,})` and store only the ID. Trim whitespace.
- Validate on save is not possible in Kodi settings, so validate on first fetch and show a clear error (see Error handling).

### Endpoints

| Purpose | Request | Notes |
| --- | --- | --- |
| Discover tabs | `GET https://docs.google.com/spreadsheets/d/{ID}/htmlview` | Parse tab names and `gid`s from the page's sheet list. Undocumented, so isolate in one function with tests against a saved fixture. |
| Load a tab (primary) | `GET https://docs.google.com/spreadsheets/d/{ID}/export?format=csv&gid={GID}` | Exact cell values, all rows. Follows a redirect to googleusercontent.com. |
| Load a tab (fallback) | `GET https://docs.google.com/spreadsheets/d/{ID}/gviz/tq?tqx=out:csv&sheet={NAME}` | Used if export fails. Known quirk: gviz can blank values in mixed text/number columns, so it is second choice. |
| Discover tabs (optional, robust) | `GET https://sheets.googleapis.com/v4/spreadsheets/{ID}?fields=sheets.properties(sheetId,title,index)&key={KEY}` | Only if the user fills the optional `api_key` setting. |

If tab discovery fails and no API key is set, fall back to the `tab_names` setting (comma-separated names, loaded through the gviz endpoint). If that is empty too, load `gid=0` as a single deck named after the sheet.

All requests: 10 s timeout, `User-Agent: Kodi-Sheetcards/<version>`, run off the UI thread. A response with `Content-Type: text/html` on a CSV endpoint, or a redirect to `accounts.google.com`, means the sheet is not public.

### Parsing

1. Decode as UTF-8, strip a BOM, parse with `csv.reader` (handles quoted commas and line breaks in cells).
2. Header row: skip row 1 when A1/B1 match `question/answer`, `q/a`, `front/back` or `term/definition` (case-insensitive). Setting `header_row` = Auto / Yes / No overrides.
3. Use columns A and B only; ignore the rest. Strip each cell; skip rows where either is empty.
4. Keep line breaks inside cells (rendered as new lines). Collapse runs of 3+ blank lines.
5. Duplicate questions within a deck: keep the first, log the rest.
6. Card ID = first 12 hex of `sha1(sheet_id + tab_title + question)`. Editing an answer keeps progress; editing a question resets it.
7. A deck with 0 valid rows is hidden from the picker; log a warning.

### Cache

Cache is shared by both add-ons and lives in the library's profile folder:

```
special://profile/addon_data/script.module.sheetcards/
  cache/{sheet_id}/tabs.json        # [{gid, title, index}], fetched_at
  cache/{sheet_id}/{gid}.csv        # raw CSV as downloaded
  cache/{sheet_id}/{gid}.meta.json  # fetched_at, row_count, source endpoint
  progress/{sheet_id}.json          # spaced repetition + stats (app only)
```

- Strategy is stale-while-revalidate: show cached cards immediately, refresh in a background thread, swap in new data at the next card boundary (never mid-card).
- Refresh when older than `refresh_hours` (default 6; 0 = every launch). The app also has a manual "Refresh now" action.
- On network failure with a cache present: keep going, show a small "Offline · updated 2 days ago" chip on the deck picker (app) or nothing (screensaver).
- On failure with no cache: error screen (app) or a calm "No cards yet" card (screensaver).
- Writes are atomic: write to `*.tmp`, then rename.

## Study modes

Both add-ons offer the same three modes; only who advances the card differs (timer in the screensaver, the user in the app).

| Mode | Card front | Card back / outcome |
| --- | --- | --- |
| Flashcard | Question, centred, large | Card flips to the answer |
| Multiple choice | Question on top, 3 or 4 option pills below | Correct pill turns green with a check; a wrong pick turns red with a cross |
| Mixed | Each card is randomly Flashcard or Multiple choice, weighted by `mix_ratio` (default 50%) | As above |

Setting `direction` = Question → Answer (default), Answer → Question, or Both (random per card). With Answer → Question, distractors are drawn from questions instead of answers.

### Distractor generation

The sheet has only Question and Answer, so wrong options come from other cards' answers. Goal: plausible, not random-looking.

1. **Pool** = distinct answers in scope, excluding the correct one. Compare normalised text (lowercase, trimmed, collapsed spaces, trailing punctuation removed). Scope setting `distractor_scope` = This deck (default) or All selected decks.
2. **Classify** every answer once: `integer`, `decimal`, `year` (4-digit 1000–2999), `date`, `single word`, `short phrase` (2–4 words), `sentence` (5+ words).
3. **Rank** candidates: same class first, then by closeness in character length (ratio nearest 1.0).
4. **Pick** `options − 1` at random from the top 8 ranked, so the same distractors do not repeat every time.
5. **Top up** if fewer than needed in the same class: take the next best from other classes.
6. **Shuffle** option order; the correct position must be uniformly random (unit-test the distribution).
7. **Fallback**: if the pool still cannot fill the options, show that card as a Flashcard. A deck with fewer than `options` distinct answers runs as Flashcard only; the app tells the user once per session.

Setting `options` = 3 or 4 (default 4). Long answers: if any option exceeds 90 characters, switch that card to a stacked one-column layout (see Visual design).

The generator is pure Python with a seeded `random.Random`, so it is fully unit-testable outside Kodi.

## Screensaver behaviour

The screensaver is a hands-free loop: it shows a card, reveals the answer on a timer, moves on, and exits the instant the user touches anything.

### Lifecycle

1. Kodi starts `default.py` when the screensaver activates (also from the Preview button in Kodi's screensaver settings).
2. Load decks from cache synchronously (fast); start a background refresh thread if stale.
3. Open the shared card window as a `WindowXMLDialog` and run the loop.
4. Exit when either fires: `xbmc.Monitor.onScreensaverDeactivated()` or any `onAction` / `onClick` in the window. Close within 150 ms; the refresh thread is a daemon and checks an abort flag.
5. All waits use `monitor.waitForAbort(step)` in 100 ms steps, never `time.sleep`, so Kodi shutdown is clean.

The screensaver never records progress or scores: it is passive viewing.

### Per-card timeline

| Mode | Phase 1 | Phase 2 | Then |
| --- | --- | --- | --- |
| Flashcard | Question for `question_seconds` (default 8) | Flip, answer for `answer_seconds` (default 6) | Next card |
| Multiple choice | Question + options for `question_seconds` | Correct option highlights, others fade to 40% for `answer_seconds` | Next card |

A hairline progress bar along the card's bottom edge fills during phase 1, so viewers know when the reveal comes. Setting `show_timer_bar` (default on).

### Order and variety

- Cards are drawn from a shuffled bag across all selected decks; no card repeats until every card has shown once, then reshuffle (no immediate repeat across the boundary).
- Deck name appears as a small chip above the card when more than one deck is selected.

### Screen care

- The card drifts to a new position within a ±24 px box at every card change, to avoid burn-in on OLED TVs.
- Optional clock in the top-right corner (`show_clock`, default off).
- `dim_after_minutes` (default 0 = never): after this long, background and card fade to 30% brightness.

### Shared settings

The screensaver has its own settings, plus `use_app_settings` (default on, shown only when `script.sheetcards` is installed). When on, it reads sheet ID, decks and theme from the app's settings via `xbmcaddon.Addon('script.sheetcards')`, so users configure once.

## Application behaviour

The app is an interactive study session: pick decks, answer by remote, mouse or touch, get scored, and let spaced repetition decide what comes back.

### Screens

1. **Deck picker** (`sheetcards-decks.xml`): one tile per tab with card count, "due today" count and mastery bar. Multi-select with Select; a **Start** button, a mode toggle (Flashcard / Multiple choice / Mixed), and **Refresh**. Remembers last selection.
2. **Study** (`sheetcards-card.xml`): the card, a top bar with progress ("7 / 20"), score and current streak.
3. **Results** (`sheetcards-results.xml`): score, accuracy, best streak, time taken, a scrollable list of missed cards, and buttons **Review missed**, **New session**, **Decks**.

Back from Study opens a small pause sheet: Resume / End session (go to Results) / Quit.

### Input

Every interactive element is a real Kodi `button` control, so remote focus, mouse click and touch tap all route through `onClick`.

| Context | Remote / keyboard | Mouse / touch |
| --- | --- | --- |
| Flashcard, front | Select = flip | Tap card = flip |
| Flashcard, back | Left = Missed it, Right = Got it (focus starts on Got it) | Tap Missed it / Got it |
| Multiple choice | Arrows move focus across the 2×2 grid (or column), Select = answer; number keys 1–4 answer directly | Tap an option |
| After an answer | Select = next (or auto-advance) | Tap anywhere |
| Anywhere | Back = pause sheet; Info = card stats (box, times seen, last result) | Right-click = Back |

After a multiple-choice answer: correct → green pill + check, auto-advance after `advance_ms_correct` (default 900). Wrong → picked pill red + cross, correct pill green, auto-advance after `advance_ms_wrong` (default 2200). `auto_advance` = off makes both wait for Select.

### Scoring and streaks

- +1 per correct answer (Flashcard "Got it" counts as correct). No negative points.
- Streak = consecutive correct; a counter pulses at 5, 10, 25.
- Per sheet, persist: best streak, total sessions, lifetime accuracy. Shown on the deck picker header.

### Spaced repetition (Leitner)

Five boxes with intervals 1, 2, 4, 8, 16 days. New cards start in box 0 (unseen).

- Correct → box + 1 (max 5), due = today + that box's interval.
- Wrong → box 1, due today, and the card is re-queued 3–5 cards later in the current session (once).
- Session build for order = Smart: overdue and due cards (oldest first), then up to `new_per_session` new cards (default 10), then, if still short, not-yet-due cards from the lowest box.
- `srs_enabled` off: nothing is persisted except stats; order setting applies to all cards.

### Deck order

Setting `order`: **Smart** (spaced repetition, default), **Shuffle**, **Sheet order**, **Hardest first** (lowest box, then most misses). Session length `cards_per_session` = 10, 20 (default), 30, 50 or All.

### Progress file

```json
{
  "version": 1,
  "sheet_id": "1oOB...leoo",
  "cards": {
    "a1b2c3d4e5f6": {"box": 3, "due": "2026-11-10", "seen": 7, "correct": 5, "last": "2026-11-06T18:20:00"}
  },
  "stats": {"best_streak": 14, "sessions": 9, "answered": 180, "correct": 141}
}
```

Cards that disappear from the sheet stay in the file for 90 days, then are pruned (so moving a card between tabs does not lose progress immediately). Progress is written after every answer (atomic), so a crash or power cut loses at most one card.

## Visual design

The look is one floating card on a calm background, generous spacing, one accent colour, and short, eased motion. Nothing borrows from the active skin except font files.

### Layout (1080i, 1920 × 1080 coordinates)

| Element | Position / size | Notes |
| --- | --- | --- |
| Card (Flashcard) | 1280 × 640, centred | Radius 32 via a 9-slice rounded texture; soft shadow texture underneath |
| Card (Multiple choice) | 1280 × 380, top at y = 150 | Question only |
| Option pills, 2 × 2 | 620 × 120 each, 40 gap, top at y = 590 | Used when every option is ≤ 90 characters |
| Option pills, stacked | 1280 × 96 each, 24 gap | Used when any option is longer |
| Top bar (app) | y = 48, 64 high | Progress left, score and streak right, deck chip centre |
| Timer bar | 4 high, card's bottom edge | Screensaver only |
| Safe area | 64 px all sides | Overscan-safe on TVs |

### Typography

- Text is centred, sentence case, line-height comfortable; a question never exceeds 4 lines.
- Font size is chosen by length bucket in `ui/fonts.py`: ≤ 40 characters → largest; 41–90 → large; 91–180 → medium; > 180 → small in a `textbox` with `autoscroll` on.
- Fonts come from the active skin's Font.xml (Kodi add-ons cannot ship fonts). Map buckets to Estuary font names by default, verify they exist in Estuary and two popular third-party skins during the M1 spike, and fall back to `font13`.

### Motion

| Moment | Animation |
| --- | --- |
| Card enters | Fade 0 → 100 and slide up 40 px, 260 ms, cubic out |
| Card leaves | Fade out and slide left 60 px, 200 ms, cubic in |
| Flip | Front zooms x 100 → 0 (180 ms, ease in), then back zooms x 0 → 100 (180 ms, ease out), centred on the card. Triggered by window property `sc.flipped`. |
| Option focus | Scale to 104%, border turns accent, 120 ms |
| Correct | Pill tints green, check icon pops 60 → 100% with a back tween, 220 ms |
| Wrong | Pill tints red with a 3-step horizontal shake (±8 px, 240 ms); correct pill tints green |
| Streak milestone | Streak counter pulses 100 → 115 → 100%, 300 ms |

All animations are XML `Conditional` / `WindowOpen` / `Focus` animations driven by window properties the Python sets; Python never animates by moving controls in a loop.

### Theming

Python resolves the palette and publishes it as window properties (`sc.bg`, `sc.card`, `sc.text`, `sc.muted`, `sc.hairline`, `sc.accent`, `sc.good`, `sc.bad`). The XML reads them with `$INFO[Window.Property(sc.card)]` in `colordiffuse` and `textcolor`, so a theme change needs no XML edits. Textures are white and tinted. Verify `$INFO[]` in `textcolor` during the M1 spike; fallback is per-theme XML include files.

| Token | Night (AARRGGBB) | Day (AARRGGBB) |
| --- | --- | --- |
| Background | FF0E1116 | FFF4F5F7 |
| Card | FF1A1F27 | FFFFFFFF |
| Text | FFF2F4F7 | FF14171C |
| Muted text | FF9AA3AF | FF5B6472 |
| Hairline / pill border | 1FFFFFFF | 1A000000 |
| Correct | FF34C77B | FF1F9D5A |
| Wrong | FFFF5C5C | FFE5484D |

Accent presets: Indigo `FF6366F1` (default), Teal `FF14B8A6`, Coral `FFFF6B5B`, Amber `FFF5A524`, Rose `FFEC4899`, Sky `FF38BDF8`, or **Custom** (hex `RRGGBB` text field, validated, falls back to Indigo). Users can also override Background and Card colours with custom hex; Text colour is then picked automatically for contrast.

Theme mode: **Night** (default), **Day**, or **Auto**, which switches at `day_starts` (07:00) and `night_starts` (19:00), checked at every card boundary. Background style: **Solid** or **Soft glow** (a large blurred accent-tinted radial texture at 18% opacity behind the card).

### Accessibility

- Text vs. card contrast ≥ 4.5 : 1 in both built-in palettes; custom colours are checked and text flips light/dark to keep it.
- Right/wrong is never colour alone: always a check or cross icon too.
- Option pills show their number (1–4) in a small muted badge for keyboard users.

## Settings reference

Both add-ons use the Kodi settings format `version="1"`, grouped into four categories: Source, Study, Look, Advanced. All labels live in `strings.po`.

| Category | ID | Type | Default | App | Screensaver |
| --- | --- | --- | --- | --- | --- |
| Source | `use_app_settings` | boolean | on | — | yes (visible only if app installed) |
| Source | `sheet_id` | string | empty | yes | yes |
| Source | `decks` | string (comma-separated gids), set via a "Choose decks" action button that opens a multiselect | all | yes | yes |
| Source | `header_row` | list: Auto / Yes / No | Auto | yes | yes |
| Source | `tab_names` | string (fallback list) | empty | yes | yes |
| Source | `refresh_hours` | integer 0–72 | 6 | yes | yes |
| Study | `mode` | list: Flashcard / Multiple choice / Mixed | Mixed | yes | yes |
| Study | `mix_ratio` | slider 10–90 % | 50 | yes | yes |
| Study | `direction` | list: Q → A / A → Q / Both | Q → A | yes | yes |
| Study | `options` | list: 3 / 4 | 4 | yes | yes |
| Study | `distractor_scope` | list: This deck / All selected decks | This deck | yes | yes |
| Study | `question_seconds` | slider 3–30 | 8 | — | yes |
| Study | `answer_seconds` | slider 2–20 | 6 | — | yes |
| Study | `show_timer_bar` | boolean | on | — | yes |
| Study | `order` | list: Smart / Shuffle / Sheet order / Hardest first | Smart | yes | — |
| Study | `cards_per_session` | list: 10 / 20 / 30 / 50 / All | 20 | yes | — |
| Study | `srs_enabled` | boolean | on | yes | — |
| Study | `new_per_session` | slider 0–50 | 10 | yes | — |
| Study | `auto_advance` | boolean | on | yes | — |
| Study | `advance_ms_correct` / `advance_ms_wrong` | slider | 900 / 2200 | yes | — |
| Look | `theme_mode` | list: Night / Day / Auto | Night | yes | yes |
| Look | `day_starts` / `night_starts` | time | 07:00 / 19:00 | yes | yes |
| Look | `accent` | list: 6 presets + Custom | Indigo | yes | yes |
| Look | `accent_custom` | string hex | empty | yes | yes |
| Look | `bg_custom` / `card_custom` | string hex | empty | yes | yes |
| Look | `background_style` | list: Solid / Soft glow | Soft glow | yes | yes |
| Look | `show_clock` | boolean | off | — | yes |
| Look | `dim_after_minutes` | slider 0–120 | 0 | — | yes |
| Advanced | `api_key` | string, hidden input | empty | yes | yes |
| Advanced | Refresh now / Reset progress / Clear cache | action buttons | — | yes | Clear cache only |
| Advanced | `debug_log` | boolean | off | yes | yes |

Custom-colour fields are visible only when the matching preset is Custom; screensaver Study and Look settings are hidden while `use_app_settings` is on (except screensaver-only rows). "Reset progress" asks for confirmation.

## Errors, testing and delivery

### Error handling

Errors appear on a card styled like the rest of the UI, never as a raw Kodi dialog or traceback.

| Situation | App | Screensaver |
| --- | --- | --- |
| No sheet ID set | Card: "Add your Google Sheet ID in settings" + **Open settings** button | Card with the same message, no button |
| Sheet not public (HTML / login redirect) | Card: "This sheet isn't shared. Set sharing to Anyone with the link → Viewer." | Same message |
| Bad ID (404) | Card: "Sheet not found. Check the ID." | Same |
| Network down, cache present | Continue from cache; "Offline" chip on deck picker | Continue silently |
| Network down, no cache | Card with **Retry** | "No cards yet" card, retry every 5 min |
| No decks selected / all empty | Deck picker with a hint | Falls back to all decks |
| Corrupt progress file | Rename to `.bak`, start fresh, log | n/a |

All errors log to `kodi.log` with the `[sheetcards]` prefix; `debug_log` adds request URLs (never the API key) and timings.

### Testing

- **Unit tests** (pytest, run outside Kodi with a small `xbmc*` stub package): parser (headers, quoted newlines, BOM, blanks, duplicates), sheet-ID extraction, distractor ranking and fallback, uniform correct-position distribution, Leitner transitions and session building, theme contrast checks, cache atomic writes.
- **Fixtures**: saved CSV exports and an `htmlview` page from the sample sheet `1oOBsLmJIfHB57YVifu1Vu1g1MdiuApkiytAl4o_leoo`.
- **Manual matrix**: Kodi 21 on Windows, Android TV (Shield or Google TV), LibreELEC on a Raspberry Pi 4/5 (performance floor), and touch on an Android tablet. Skins: Estuary plus two popular third-party skins.
- **Acceptance checks**: screensaver exits within 150 ms of a key press; card change runs at 60 fps on Pi 5 (no dropped frames visible); a 1,000-row sheet loads from cache in under 1 s; app is fully usable with only arrows, Select and Back.

### Milestones

1. **M1 – Spike**: confirm `htmlview` tab parsing, `export?format=csv&gid=` on the sample sheet, `$INFO[]` in `textcolor`, skin font names, flip animation feel on a Pi. Go / no-go on the theming approach.
2. **M2 – Core library**: fetch, parse, cache, deck model, distractors, theme engine, with unit tests.
3. **M3 – Screensaver**: card window, auto-play loop, timer bar, drift, settings.
4. **M4 – Application**: deck picker, interactive study, scoring, SRS, results, pause sheet.
5. **M5 – Polish and release**: motion tuning, error cards, icons and fanart, strings, repo packaging, changelog.

### Risks

- `htmlview` tab discovery is undocumented and may change. Mitigation: isolated parser, fixture tests, optional API key path, manual tab-names fallback.
- Google may rate-limit frequent CSV pulls from shared IPs. Mitigation: cache-first with a 6 h default refresh.
- Skin fonts vary and add-ons cannot ship fonts. Mitigation: bucket map with verified fallbacks; test on three skins.
- Weak devices (older Pi, cheap Android sticks) may stutter on large textures. Mitigation: keep textures small and 9-sliced; Soft glow off automatically if frame time is poor is a v2 idea.

### Open questions

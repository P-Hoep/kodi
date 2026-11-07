# RSS Live Tiles for Kodi: Specification

**Status:** Implemented as v1.0.0 (see §14 for what changed from this draft)
**Working name:** RSS Live Tiles
**Addon IDs:** `script.module.rsslivetiles` (shared), `script.rsslivetiles` (program), `screensaver.rsslivetiles` (screensaver)
**Target:** Kodi 21 "Omega" and later, Python 3
**Location:** repository root, next to the other add-ons (`script.module.rsslivetiles/`, `script.rsslivetiles/`, `screensaver.rsslivetiles/`)

> Items marked **[ASSUMPTION]** are decisions I made to keep the spec concrete. Each one should be confirmed or changed during review.

---

## 1. Overview

RSS Live Tiles shows content from one or more RSS/Atom feeds as a grid of animated tiles, modeled on the Windows Phone / Windows 8 "Live Tiles" design language: flat colored squares and rectangles, bold typography, a user-chosen accent color, and tiles that flip, peek, and cycle to show new content.

It ships in two forms that share one core library:

| Form | Kodi extension point | Interaction |
|---|---|---|
| **Program** | `xbmc.python.script` (`<provides>executable</provides>`) | Navigable with remote/keyboard; selecting a tile expands it into a detail view |
| **Screensaver** | `xbmc.ui.screensaver` | Passive, fills the screen, any input exits |

### 1.1 Goals
- Consume **multiple** RSS 2.0 and Atom feeds.
- Extract images from feeds (media tags, enclosures, embedded HTML) and use them on tiles where available.
- Slick, smooth live-tile animations: 3D flip, peek, cycle, and an expand/zoom transition into detail.
- User-selectable **accent colors** (global, with optional per-feed override).
- **Day/Night** (light/dark) modes, switchable manually or on a schedule.
- Runs well on modest hardware (e.g. Raspberry Pi 4/5, Fire TV, Shield).
- Fits cleanly into the existing repository.

### 1.2 Non-goals (v1)
- A full article reader / web browser inside Kodi.
- Accounts, sync, or read/unread state across devices.
- Feed discovery or search.
- Touch-first interaction.

---

## 2. Design language

### 2.1 Principles (from Metro / Windows Phone)
- **Typography carries the design.** Large, light-weight headings; small all-caps labels for source names.
- **Motion has meaning.** Tiles move to signal fresh content; transitions connect a tile to its detail view.
- **Content first.** Images go full-bleed; text sits on a scrim only when it overlays an image.

### 2.1a Tile styles
The user picks a tile style in settings. Styles change only visual treatment (shape, fill, borders, scrims); layout, animations, and content are shared, so every style works with every layout.

| Style | Look | Implementation notes |
|---|---|---|
| **Classic** (default) | Windows Phone 8: flat, square, edge-to-edge accent color, no shadows | White-pixel texture with `colordiffuse` |
| **Modern** | Windows 11-inspired: 8 px rounded corners, slightly larger gutters (14 px), translucent "acrylic" text panels over images | Rounded-corner `diffuse` mask textures per tile size; acrylic approximated with a semi-transparent tinted panel (Kodi has no runtime blur) |
| **Outline** | Dark/light background tiles with a 2 px accent border and accent-colored headlines; images inset | Lower visual weight, good for night use and OLED screens |

Each style is a small definition (textures, gutter, corner mask, scrim, face templates) in `tiles/styles.py`, so more styles can be added later without touching layout or animation code.

### 2.2 Grid and tile sizes
Layout is built on a fixed unit grid at 1920×1080 (Kodi `1080i` skin resolution, scaled automatically for other resolutions).

| Token | Value |
|---|---|
| Unit cell | 130 px |
| Gutter | 10 px |
| Screen margin | 80 px left/right, 60 px top |

| Tile size | Grid units | Pixel size | Typical use |
|---|---|---|---|
| Small | 1×1 | 130×130 | Feed icon + unread count |
| Medium | 2×2 | 270×270 | Single headline, or image + headline |
| Wide | 4×2 | 550×270 | Headline + summary, image peek |
| Large | 4×4 | 550×550 | Hero image + headline + summary |

### 2.3 Typography
- **Font:** Selawik (Microsoft's open-source, OFL-licensed Segoe UI metric-compatible font), bundled with the addon and registered through a font include. Fallback: Open Sans.
- Weights: Light (headlines), Regular (body), Semibold (labels).
- Scale (1080p): Hub title 72 px Light · Group header 36 px Light · Tile headline 22–30 px · Body 22 px · Labels 16 px Semibold, all-caps, letter-spaced.

### 2.4 Accent colors
The default palette is the Windows Phone 8 accent set, plus a custom hex option:

| Name | Hex | Name | Hex |
|---|---|---|---|
| Lime | `#A4C400` | Magenta | `#D80073` |
| Green | `#60A917` | Crimson | `#A20025` |
| Emerald | `#008A00` | Red | `#E51400` |
| Teal | `#00ABA9` | Orange | `#FA6800` |
| Cyan | `#1BA1E2` | Amber | `#F0A30A` |
| Cobalt | `#0050EF` | Yellow | `#E3C800` |
| Indigo | `#6A00FF` | Brown | `#825A2C` |
| Violet | `#AA00FF` | Olive | `#6D8764` |
| Pink | `#F472D0` | Steel | `#647687` |
| Mauve | `#76608A` | Taupe | `#87794E` |

- **Global accent** applies to all text-only tiles, focus highlights, and the detail view accent bar.
- **Per-feed accent** (optional) overrides the global accent for that feed's tiles.
- **Tile shade variation** *[ASSUMPTION]*: text-only tiles in the same group alternate between the accent and a 10–15% darker/lighter tint, so a wall of tiles doesn't read as one flat block. Can be turned off.
- Text on accent tiles is always white; contrast is checked at setting time for custom hex values, and a warning is shown if contrast is below WCAG AA for large text (3:1).

### 2.5 Day / Night modes

| Token | Night (dark) | Day (light) |
|---|---|---|
| Background | `#000000` | `#FFFFFF` |
| Primary text (outside tiles) | `#FFFFFF` | `#000000` |
| Secondary text | `#A0A0A0` | `#5A5A5A` |
| Image scrim | black 0→70% | black 0→60% |
| Tile text | white | white |
| Detail panel background | `#111111` | `#F2F2F2` |

**Mode selection** (setting; all three methods are supported):
1. **Manual:** Always Night or Always Day
2. **Scheduled:** user picks day-start and night-start times *(default 07:00 / 19:00)*
3. **Sunrise/sunset:** computed locally from latitude/longitude entered in settings (no network call), with an optional offset in minutes

The program and screensaver each have their own mode setting, with a "Same as program" option (default) for the screensaver.

Mode changes while running crossfade over 600 ms. The screensaver can additionally apply a **Night dim** (reduce overall brightness by a set percentage) during night hours.

---

## 3. Feeds

### 3.1 Supported formats
- RSS 2.0, RSS 1.0 (RDF), Atom 1.0.
- Namespaces: `media:` (Media RSS), `content:encoded`, `dc:`, `itunes:`, `atom:`.
- Encodings: honor the XML declaration and HTTP `charset`; fall back to UTF-8 with replacement.

### 3.2 Parsing
Uses **feedparser** for format detection, namespace handling, date parsing, and tolerance of malformed feeds (via a Kodi repository module if one is available for Omega, otherwise vendored inside `script.module.rsslivetiles`). A thin adapter in `feeds/parser.py` maps feedparser's output to the normalized model below, and adds the Media RSS and embedded-HTML image handling in §3.3 that feedparser exposes only partially.

Normalized item model:

```python
@dataclass
class FeedItem:
    id: str              # guid / atom:id / hash(link+title)
    feed_id: str
    title: str
    summary: str         # plain text, ≤ 500 chars
    content_html: str    # sanitized, for detail view
    link: str
    author: str | None
    published: datetime  # UTC; falls back to fetch time
    images: list[ImageRef]       # ranked, best first
    enclosures: list[Enclosure]  # audio/video
```

### 3.3 Image extraction
Candidates are collected per item in this priority order, then deduplicated:

1. `media:content` with `medium="image"` or an image MIME type (prefer the largest `width`)
2. `media:group` → best `media:content`
3. `media:thumbnail` (largest)
4. `<enclosure type="image/*">`
5. `itunes:image`
6. Atom `<link rel="enclosure" type="image/*">`
7. First suitable `<img>` in `content:encoded`, then in `description`/`summary`
8. *(Optional, off by default)* Fetch the article page and read its `og:image` meta tag, rate-limited and cached

**Filtering:** skip images with declared width or height under 120 px, 1×1 tracking pixels, known tracker/ad hosts, `data:` URIs over 200 KB, and non-raster formats Kodi can't render (e.g. SVG).
**Feed-level image** (`<image>`, `atom:logo`, `atom:icon`) is used for the feed's small tile and as a source badge.
**Loading:** image URLs are passed directly to Kodi image controls so Kodi's texture cache handles download, decoding, and caching. Tiles whose image fails to load fall back to the text-only accent style.

### 3.4 Fetching and caching
- Fetching runs on a background thread driven by `xbmc.Monitor`, never on the GUI thread.
- HTTP: `requests` (`script.module.requests`) with a shared session, gzip, 10 s timeout, 5 MB response limit, custom User-Agent, and conditional GET (`ETag` / `Last-Modified`).
- Per-feed refresh interval (default 30 min, min 5 min); exponential backoff on failure (up to 6 h).
- Parsed feeds are cached as JSON in `special://profile/addon_data/<id>/cache/`. Both the program and screensaver render instantly from cache, then refresh in the background.
- Retention: keep the newest N items per feed (default 30) and drop items older than X days (default 7).
- A failing feed shows a subtle error state on its tile (feed icon dimmed plus a small warning glyph) rather than disappearing.

### 3.5 Feed management
- **In-program "Manage feeds" screen:** add (by URL, with validation and title auto-detect), edit (title, accent, max items, enabled, pinned tile size), reorder, delete.
- **OPML import/export** from a file path.
- Stored in `addon_data/<id>/feeds.json` (shared by program and screensaver).
- Ships with 3 sample feeds that the user can remove.

```json
{
  "version": 1,
  "feeds": [
    {"id": "a1b2", "url": "https://example.com/rss", "title": "Example",
     "accent": null, "enabled": true, "max_items": 30, "refresh_min": 30,
     "tile_size": "wide"}
  ]
}
```

---

## 4. Tiles

### 4.1 Tile kinds
| Kind | Content | Live behavior |
|---|---|---|
| **Feed tile** | One tile per feed, cycles through that feed's latest items | Flip/peek between items |
| **Item tile** | A single article (used in the large/medium "highlights" area) | Peek between image and text |
| **Count tile** (small) | Feed icon + count of items newer than last view | Count increments with a flip |

### 4.1a Layouts
The user picks a layout in settings (program and screensaver set separately). All layouts are produced by one layout engine that packs tiles into columns 4 units wide using the sizes in §2.2; each layout is a packing strategy in `tiles/layouts/`.

| Layout | Description | Program | Screensaver |
|---|---|---|---|
| **Feed groups** (program default) | Horizontally scrolling hub, Windows 8 Start style. One group per feed: header, feed tile, then medium/small item tiles for the newest items | ✓ | — |
| **Mixed wall** (screensaver default) | Newest items from all feeds interleaved, sorted by date, with image items given larger tiles | ✓ | ✓ |
| **Magazine** | One large hero tile (newest item with an image), a column of wide tiles, then medium/small tiles | ✓ | ✓ |
| **Spotlight** | One feed at a time fills the screen; Left/Right (or a timer in the screensaver) moves between feeds | ✓ | ✓ |
| **Mosaic** | Image-only tiles in mixed sizes, headline shown on peek; items without images are skipped | ✓ | ✓ |

- **Per-feed tile size pinning:** in Feed groups and Mixed wall, a feed's tile size can be pinned (Small/Medium/Wide/Large) in the feed manager; otherwise the layout chooses.
- Switching layout while the program is open plays the exit/entrance animation (§4.3) rather than a hard cut.

### 4.2 Faces
Each tile has a **front** and **back** face, each rendered from a template:

- **Image face:** full-bleed image, bottom scrim, headline (max 3 lines), source label.
- **Text face:** accent background, headline (max 4–5 lines on medium), relative time ("12 MIN AGO"), source label bottom-left, feed icon bottom-right.
- **Summary face** (wide/large only): headline + 2–4 lines of summary.

Text is truncated with ellipses; headlines never overflow the tile.

### 4.3 Live animations

| Animation | Description | Timing |
|---|---|---|
| **Flip** | 3D rotation about the Y axis (or X for wide tiles). Front rotates 0°→90° (ease-in), content swaps, back rotates −90°→0° (ease-out) | 2 × 250 ms |
| **Peek** | Image face slides up to reveal text face beneath, holds, slides back | 400 ms out, 3–4 s hold, 400 ms back |
| **Cycle** | Content slides up out of the tile and the next item slides in from below | 350 ms, cubic ease |
| **Fade** | Crossfade (low-power fallback) | 400 ms |
| **Pulse** | Count tile scales 100%→104%→100% when the count changes | 300 ms |

**Scheduler rules:**
- At most **2 tiles animate at once** (configurable 1–4).
- A random tile animates every 2–6 s (configurable "liveliness": Calm / Normal / Lively).
- No tile animates twice in a row; tiles currently on screen are preferred.
- The focused tile in the program does not animate (so the user can read it).
- **Reduced motion** setting replaces flip/peek/cycle with fade.

**Entrance:** on open, tiles drop in column by column with a 40 ms stagger (rotate from −30° on X plus fade), Windows Phone "turnstile" style. Exit reverses it.

### 4.4 Focus (program only)
- Focused tile scales to 104% with a 3 px accent (or white on accent tiles) border.
- Moving focus off-screen scrolls the hub smoothly (300 ms).
- Long-press / context menu on a tile: Open, Mark feed read, Refresh feed, Edit feed, Hide item.

---

## 5. Program: detail view

Selecting a tile **expands** it:

1. The tile zooms from its on-screen rectangle to full screen (350 ms, ease-out) while other tiles fade and slightly scale back (to 95%).
2. The detail layout fades in on top (200 ms).
3. **Back** reverses the transition to the originating tile.

**Detail layout (1080p):**
- Left 55%: hero image (best `ImageRef`), or a large accent block with the feed icon if there is none.
- Right 45%: source label in accent color, headline (Light, 44 px), author · relative time, then body text from `content_html` converted to Kodi label markup (bold/italic/paragraphs; links and scripts stripped), in a scrollable text box.
- Bottom bar: position indicator ("3 / 30"), hints for Left/Right = previous/next item in the same feed.
- **QR code (optional, setting "Show QR code for article link", default on):** a QR code of the article URL in the detail view so it can be opened on a phone. Generated as a PNG into the addon cache with a QR library (a Kodi repository module if available, otherwise a pure-Python library such as `segno` vendored in the shared module). When off, the URL is not shown.
- **Enclosures:** if the item has an audio/video enclosure, a **Play** button hands it to Kodi's player.

Moving between items within the detail view uses the Cycle animation horizontally.

---

## 6. Screensaver

- Fills the screen with the tile grid, **no scrolling**. Uses its own layout setting (Mixed wall, Magazine, Spotlight, or Mosaic) and fits as many tiles as the screen allows, prioritizing newest items with images.
- Content rotates: every N minutes (default 3), the oldest-shown tiles are re-populated with fresh items via Flip.
- **Burn-in protection:** the whole grid shifts by a few pixels every 2 minutes; optional slow drift.
- Optional clock/date tile.
- Starts from cache in under 1.5 s; never blocks on the network.
- Any input exits (standard Kodi behavior). Screensaver preview from Kodi settings is supported.
- Separate liveliness and night-dim settings from the program, since it runs unattended.

---

## 7. Settings

Kodi `settings.xml` (Kodi 19+ format), grouped:

**Feeds**
- Manage feeds… (opens the in-program manager)
- Import OPML… / Export OPML…
- Default refresh interval · Max items per feed · Max item age

**Appearance**
- Layout: Feed groups / Mixed wall / Magazine / Spotlight / Mosaic
- Tile style: Classic / Modern / Outline
- Accent color (palette list + "Custom…" hex entry)
- Use per-feed accents (on/off) · Tile shade variation (on/off)
- Theme mode: Night / Day / Scheduled / Sunrise–sunset
- Day start / Night start times · Latitude / Longitude · Sunrise/sunset offset
- Show images on tiles (on/off) · Fetch article images (og:image) (on/off)
- Show QR code for article link (on/off)

**Motion**
- Liveliness: Calm / Normal / Lively
- Max simultaneous animations (1–4)
- Reduced motion (on/off)

**Screensaver**
- Layout: Mixed wall / Magazine / Spotlight / Mosaic
- Tile style: Same as program / Classic / Modern / Outline
- Theme mode: Same as program / Night / Day / Scheduled / Sunrise–sunset
- Content rotation interval · Burn-in shift (on/off)
- Night dim (0–70%) · Show clock tile (on/off)

**Advanced**
- Clear cache · Debug logging · Network timeout

---

## 8. Architecture

### 8.1 Packaging
Two addons plus a shared module, placed at the repository root:

```
kodi/
  script.module.rsslivetiles/      # shared core library (feeds, layout, styles, theme, UI)
  script.rsslivetiles/             # program; depends on the module
  screensaver.rsslivetiles/        # screensaver; depends on the module
```

Dependencies declared in `script.module.rsslivetiles/addon.xml`:

| Dependency | Use |
|---|---|
| `xbmc.python` 3.0.1 | Kodi Python API (Omega+) |
| `script.module.requests` | HTTP fetching |
| `script.module.feedparser` *(or vendored)* | Feed parsing |
| `script.module.dateutil` | Date handling, sunrise/sunset schedule |
| QR library *(Kodi module or vendored `segno`)* | Optional QR codes |

Availability of each module in the Omega repository is confirmed during M0; anything missing is vendored under `resources/lib/vendor/` with its license.

Skin XML, fonts, and media live in the shared module; the program and screensaver addons are thin entry points that load windows from the module's skin path.

### 8.2 Module layout (shared library)
```
resources/lib/rsslivetiles/
  feeds/
    fetcher.py      # HTTP, conditional GET, backoff
    parser.py       # RSS/Atom → FeedItem
    images.py       # candidate extraction, ranking, filtering
    sanitize.py     # HTML → plain text / Kodi label markup
    store.py        # feeds.json, cache JSON, retention
    opml.py
  tiles/
    layout.py       # grid packing engine (pure Python, unit-tested)
    layouts/        # feed_groups.py, mixed_wall.py, magazine.py, spotlight.py, mosaic.py
    styles.py       # Classic / Modern / Outline style definitions
    model.py        # Tile, Face, TileSize
    scheduler.py    # which tile animates next
    animations.py   # animation definitions (Kodi animation tuples)
  ui/
    hub_window.py       # program main window
    detail_window.py
    feed_manager.py
    screensaver_window.py
    controls.py     # tile control groups, face swapping
  theme.py          # accents, day/night tokens, schedule, sun calc
  settings.py       # typed wrapper over addon settings
  kodi.py           # thin wrapper over xbmc/xbmcgui for testability
resources/skins/default/1080i/
  rsslivetiles-hub.xml
  rsslivetiles-detail.xml
  rsslivetiles-screensaver.xml
  rsslivetiles-feeds.xml
resources/skins/default/media/   # white pixel, scrim gradients, icons
resources/fonts/                 # Selawik
resources/language/resource.language.en_gb/strings.po
```

### 8.3 Rendering approach
- Windows are `xbmcgui.WindowXML` / `WindowXMLDialog` with static chrome (background, headers, detail layout) defined in skin XML.
- Tiles are created at runtime in Python (`ControlImage`, `ControlLabel`, `ControlTextBox`) because the grid is dynamic.
- Animations use Kodi's native animation engine (`fade`, `slide`, `zoom`, `rotatex`, `rotatey` effects) via `Control.setAnimations()` with **conditional** triggers bound to window properties (e.g. `String.IsEqual(Window.Property(tile.7.face),back)`). Python flips the property; Kodi's GUI thread runs the animation. This keeps animations smooth even though Python is slow.
- Colors (accent, theme) are applied through window properties and `colordiffuse` on a white-pixel texture, so changing accent or mode doesn't rebuild controls.

### 8.4 Phase 0 technical spike (must precede full build)
Verify on the lowest-spec target device:
1. `rotatey` flip on a tile composed of several controls stays in sync and hits 60 fps (or decide on a per-face rendering trick).
2. 2–4 concurrent tile animations plus image loading don't drop frames.
3. Zoom-from-tile-rect transition into the detail window looks seamless.
4. Runtime-created controls can be positioned inside a scrolling group, or decide to scroll by offsetting every control.
5. Bundled font registration works without modifying the user's skin.
6. Rounded-corner masks for the Modern style render cleanly during flip and zoom animations.
7. Which dependencies (§8.1) exist in the Omega repository and which must be vendored.

Outcome: a short note in the repo choosing between runtime controls vs. a fixed-slot XML template approach.

### 8.5 Threading
- GUI thread: window events, property changes only.
- Worker thread: fetching, parsing, layout computation; hands results to the GUI via a queue checked on a short timer.
- Everything shuts down cleanly on `Monitor.abortRequested()` and window close.

---

## 9. Non-functional requirements

| Area | Requirement |
|---|---|
| Performance | 60 fps animations on Pi 5 / Shield; no animation stutter during refresh; startup from cache < 1.5 s |
| Memory | < 150 MB additional on low-end devices; image count on screen capped by layout |
| Network | Never blocks the UI; works fully offline from cache |
| Robustness | A broken feed never breaks the board |
| Accessibility | Reduced-motion option; contrast check on custom accents; readable at 3 m (min 16 px labels at 1080p) |
| Localization | All UI strings in `strings.po` |
| Logging | `xbmc.log` with addon prefix; debug level behind setting |
| Privacy | No analytics; og:image fetching off by default |

---

## 10. Testing

- **Unit tests** (pytest, run outside Kodi using `Kodistubs`): parser against a fixture set of real-world feeds (RSS 2.0, Atom, Media RSS, podcast, malformed), image extraction ranking, HTML sanitizing, layout packing, scheduler rules, theme scheduling and sun calculation.
- **Static checks:** `kodi-addon-checker` for each addon, flake8/ruff.
- **Manual test plan** on target devices: navigation, expand/collapse, theme switch while open, offline start, 20+ feeds, screensaver start/exit/preview.
- CI wired into the repository's existing pipeline.

---

## 11. Milestones

| # | Milestone | Exit criteria |
|---|---|---|
| M0 | Technical spike | §8.4 questions answered on target hardware |
| M1 | Feed core | Fetch, parse, image extraction, cache; unit tests green |
| M2 | Static hub | Feed groups + Mixed wall layouts, Classic style, tile faces, accents, day/night, navigation |
| M3 | Live tiles | Flip/peek/cycle, scheduler, entrance animation |
| M4 | Detail view | Expand transition, detail layout, item navigation, QR/play |
| M5 | Screensaver | Full-screen grid, rotation, burn-in shift, night dim |
| M6 | Feed manager, settings & variants | Add/edit/reorder feeds, OPML, Magazine/Spotlight/Mosaic layouts, Modern/Outline styles, all settings wired |
| M7 | Polish & release | Localization, addon-checker clean, repository packaging |

---

## 12. Decisions log

| # | Topic | Decision |
|---|---|---|
| 1 | Location | Repository root, like every other add-on (MIT, `P-Hoep` provider, published by `tools/make_repo.py`) |
| 2 | Kodi versions | 21 "Omega" and later |
| 3 | Packaging | Two addons sharing one module |
| 4 | Layout | Multiple layouts (§4.1a) |
| 5 | Tile style | Multiple styles (§2.1a) |
| 6 | Day/night | Manual, scheduled, and sunrise/sunset all supported |
| 7 | QR code | Optional, controlled by a setting |
| 8 | Dependencies | Kodi module dependencies allowed |

## 13. Open questions

1. **Directory:** Which directory in the existing repository should the three addons go in? Any addon ID prefix, license, or CI conventions to follow?
2. **Lowest-spec device:** What is the slowest hardware it must animate smoothly on?
3. **Feed management:** Is the in-program manager plus OPML enough, or should feeds also be editable from Kodi's settings dialog? Roughly how many feeds do you expect?
4. **og:image scraping:** Acceptable to fetch article pages for images when the feed has none (off by default)?

---

## 14. Implementation notes (v1.0.0)

Built and tested on Kodi 21.1 (macOS) with the BBC News, r/kodi and NASA Image of the Day feeds.

### 14.1 Phase 0 outcome
The spike (§8.4) chose a **fixed-slot XML template** over controls created at run time:

| Question | Finding on Kodi 21.1 | Decision |
|---|---|---|
| Can runtime controls go in a scrolling group? | No. Python controls are added at window level, and grouplists cannot be fetched from Python. | Slot pools per tile size generated into the window XML (`tools/make_rsslivetiles_skin.py`). Python positions slots with `setPosition()` and fills them through window properties. Only tiles near the viewport are bound. |
| Do groups clip animated children? | No, not even grouplists. | Peek and cycle are squashes that stay inside the tile, not slides. |
| Does `rotatey` / `rotatex` look right? | Kodi's camera is close, so a flipping picture tile balloons well outside its rectangle. | Flips are 2D squashes with an 8 % shrink at the edge-on midpoint, about the Y axis (X for wide tiles). |
| Smooth hub scrolling? | `setAnimations()` with a `condition=true` slide restarts on every call. | The strip is scrolled with a 300 ms slide, then `setPosition()`. |
| Bundled fonts without touching the skin? | Not possible. | Estuary font names. The hub title uses `font_clock` (Roboto Thin). |
| Rounded masks (Modern)? | `diffuse` masks work with `aspectratio scale`. | Per-size masks. |
| Dependencies in the Omega repository | `script.module.certifi` and `script.module.pyqrcode` are there; `feedparser` is not. | A small ElementTree parser instead of feedparser; urllib instead of requests; pyqrcode's matrix with our own PNG writer. |

Window files are about 1.5 MB and ~3,800 controls each. They load in about 0.15 s, and the
board fills from the cache in about 0.01 s. Lowest-spec hardware has not been tested yet.

### 14.2 Differences from the draft
- **Code layout** follows the repository: `lib/rsslivetiles/` (not `resources/lib/`). The layouts
  are one module (`tiles/layouts.py`); the faces are built in `tiles/faces.py`.
- **One window per tile style** (`rsslivetiles-classic|modern|outline.xml`). The detail view is a
  layer of the same window, so a tile can expand into it. Instead of a zoom of the tile itself, a
  solid panel in the tile's colour zooms from the tile's rectangle to full screen. The screensaver
  uses the same windows.
- **Feed manager** uses Kodi's own dialogs (select, input, context menu) rather than a custom
  `rsslivetiles-feeds.xml`. It opens from the program (Menu on a tile) and from both add-ons'
  settings.
- **Entrance** is a vertical unfold plus fade with a 40 ms stagger per grid column, instead of
  a 3D turnstile (see 14.1).
- **Retention** always keeps a feed's newest 3 items, even past the age limit, so quiet feeds never go blank.
- **Images**: `data:` URIs are always skipped (Kodi image controls cannot load them). BBC
  thumbnails (`ichef.bbci.co.uk/.../240/`) are upgraded to 800 px. Feed icons are downloaded once
  to check them, because Kodi cannot report a failed image load; broken ones fall back to initials.
- **Screensaver settings** have "Same as program" for tile style, accent and theme mode (the layout is always its own). Fetch
  settings and per-feed options come from the program when it is installed.
- **Custom accent contrast** is checked when the program opens and in the feed manager (Kodi
  settings cannot validate on entry).
- **Count tiles** count items newer than the last time the program was closed (or "Mark feed read").
- **Spotlight** pages are exactly one screen apart. The screensaver turns the page every 30 s.

### 14.3 Not done yet
- Testing on a Raspberry Pi, Fire TV or Shield.
- `kodi-addon-checker`. CI runs only the repository build.
- Translations beyond English.


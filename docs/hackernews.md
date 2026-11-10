# Hacker News Screensaver

`screensaver.hackernews` v0.1.0

A Kodi screensaver that shows the front page of Hacker News while the TV is idle. Each story gets
a slide with its rank, title, domain, points, author, age and comment count; then up to ten of its
top-level comments follow, one at a time, each for as long as it takes to read at your reading
speed. It cycles through the queue, refreshes the stories in the background, and works from a
cache when the network is down. Any key closes it.

It is pure Python 3 using only the standard library — no compiled code, no imaging library, no
bundled data. The only outbound requests go to Hacker News' two public read-only APIs.

---

## Contents

- [Installing](#installing)
- [The shape of the show](#the-shape-of-the-show)
- [Settings reference](#settings-reference)
- [How a comment becomes text](#how-a-comment-becomes-text)
- [Reading time](#reading-time)
- [Caching, refreshing and offline](#caching-refreshing-and-offline)
- [Data and how it is used](#data-and-how-it-is-used)
- [Leaving the screensaver](#leaving-the-screensaver)
- [Project layout](#project-layout)
- [Development and testing](#development-and-testing)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)

---

## Installing

The add-on is in the P-Hoep repository (see the
[root README](../README.md#install-from-the-repository)). It needs Kodi 20 (Nexus) or later.

1. **Settings → Add-ons → Install from repository → P-Hoep Add-ons → Look and feel →
   Screensavers → Hacker News.**
2. **Settings → Interface → Screensaver → Screensaver mode → Hacker News.**
3. Next to the mode, open the add-on's settings (**Settings**) to pick the list, the counts, the
   timing and the theme.

There is nothing else to install: the API needs no key and no account, and the add-on has no
dependencies beyond `xbmc.python`.

## The shape of the show

The show is a queue. Every story contributes one **story slide** and then one **comment slide per
comment**, in the order Hacker News ranks them, and the queue repeats after the last slide.

A story slide:

```
 1    Show HN: I built a thing that does the thing
      example.com · 321 points · by alice · 2 h ago · 84 comments
```

- The rank is the story's position in the list the add-on fetched (Top, Best, New, Ask, Show).
  With *Randomize starting story* on, the queue starts at a random story but each slide keeps its
  real rank.
- The title is large; the line under it is the domain (or `news.ycombinator.com` for text posts),
  the score, the author, the age and the comment count. Score, author and age can be switched off;
  the domain and comment count stay.
- Text posts (Ask HN, Show HN and the like) show their own text under the meta line, formatted
  like a comment.

A comment slide:

```
#1  Show HN: I built a thing that does the thing
by alice · 2 h ago

The comment text, with italics, paragraphs and indented code blocks.
```

The header names the story, the author line is in the accent colour, and the body is the comment.
With *Include the first reply* on, the first reply follows the comment as a quoted block
(`> …`), trimmed to 300 characters.

Around the slides:

- **Top left**, an orange wordmark, "Hacker News", with the chosen list underneath (Top, Best…).
- **Top right**, the time of day when *Show clock* is on.
- **Bottom left**, the position in the queue (`7 / 63`) and a progress bar that fills as the
  slide's time runs out.
- **Offline badge**: when a background refresh fails, an accent-coloured line under the header
  reads "offline, showing cached data" until the next successful refresh.

Slides cross-fade over 500 ms: the incoming slide is written into a hidden second layer and a
window property swaps the two. The layout keeps a 5 % margin (96 px at 1080i) and the progress bar
sits just inside the safe area.

## Settings reference

**Content**

| Setting | Default | Range | What it does |
|---|---|---|---|
| Story list | Top | Top, Best, New, Ask, Show | Which Hacker News list to read |
| Number of stories | 15 | 5–50 | How many stories per queue |
| Comments per story | 3 | 0–10 | Comment slides after each story; 0 shows stories only |
| Include the first reply under each comment | off | | Adds the comment's first reply as a quote, up to 300 characters |
| Minimum comment characters | 40 | 0–400 (10) | Comments shorter than this are skipped, unless no comment reaches it — then the longest one shows |
| Maximum comment characters | 700 | 200–2000 (50) | Comments longer than this are cut at a sentence or word boundary |

**Timing**

| Setting | Default | Range | What it does |
|---|---|---|---|
| Story slide seconds | 8 | 3–60 | How long a story slide stays |
| Minimum comment seconds | 6 | 3–60 | Lower clamp on a comment's reading time |
| Maximum comment seconds | 30 | 10–180 (5) | Upper clamp |
| Reading speed (words per minute) | 220 | 120–400 (10) | Words per minute used to time comments |
| Data refresh interval (minutes) | 30 | 5–240 (5) | Cache lifetime; also how often the queue refreshes |

**Appearance**

| Setting | Default | Range | What it does |
|---|---|---|---|
| Theme | Dark | Dark, OLED black, Light | Background, text, secondary text and track colours; the accent is Hacker News orange in all three |
| Font scale (percent) | 100 | 80–120 (10) | Zooms the whole slide; 100 is the designed layout |
| Show clock | on | | Time of day, top right |
| Burn-in drift | on | | Moves the layout a few pixels every minute |
| Show score, author and age | on | | Hides those three parts of the meta line when off |

**Advanced**

| Setting | Default | Range | What it does |
|---|---|---|---|
| Randomize starting story | on | | Starts the queue at a random story; ranks stay correct |
| Use Algolia for comments | on | | Comment trees from Algolia in one request per story; off, or when it fails, reads the story's `kids` from Firebase |
| Clear cache | action | | Deletes the cached lists and confirms with a dialog |
| Debug logging | off | | Logs fetch timings and slide builds to kodi.log |

Settings are read once when the screensaver starts. Restarting the screensaver (wait for it, or
change the mode back and forth) picks up changes.

## How a comment becomes text

Hacker News comments are a small subset of HTML; Kodi labels are plain text with a handful of
tags. The formatter (`resources/lib/formatter.py`) walks the HTML once and produces runs of text:

| Input | Output |
|---|---|
| `&amp;`, `&#x27;`, `&quot;`, numeric entities | the real characters |
| `<p>`, `<div>`, `<blockquote>`, headings, list containers | a blank line |
| `<br>` | a line break |
| `<i>`, `<em>` | `[I]…[/I]` |
| `<pre><code>` | the block kept verbatim, every line indented four spaces, blank lines kept |
| `<a href="https://x/y">the paper</a>` | `the paper` |
| `<a href="https://x/y">https://x/y</a>` | `x` (the domain) |
| `<a href="https://x/y"></a>` | `x` |
| `<ul><li>` | a blank line and `• ` |
| `[b]`, `[/b]`, `[COLOR=red]` | `(b)`, `(/b)`, `(COLOR=red)` |

Literal square brackets become parentheses so a comment can never inject a Kodi tag. Runs of
spaces and newlines inside prose collapse to one space; a text post's own text is formatted the
same way.

Long text is cut at the last sentence end (`.`, `!`, `?`) in the final half of the allowed length;
if there is none, at the last word boundary; otherwise hard at the limit. An ellipsis (`…`) is
appended, and trailing whitespace is trimmed. A trailing `[I]` is never left open, because the cut
keeps whole runs.

## Reading time

A comment's time on screen is

```
seconds = words × 60 ÷ words-per-minute
```

with `words` counted on the visible text (reply included, if shown) and the result clamped to the
minimum and maximum comment seconds. At the defaults, a 40-word comment stays about 11 seconds; a
400-word one hits the 30-second cap. The progress bar shows the fraction that has elapsed.

Story slides are a fixed number of seconds; they do not depend on the reading speed.

## Caching, refreshing and offline

The last successful fetch of a list is written to the add-on's profile folder as
`<list>.json` — `top.json`, `ask.json`, and so on — with a `fetched_at` timestamp. Writes go to a
temporary file renamed into place, so stopping Kodi mid-save cannot leave half a file behind.

On start-up:

1. A cached list is used immediately, fresh or stale — the screensaver never waits on the network
   when it has something to show.
2. With no cache at all, it shows "Loading Hacker News…" and fetches. If that fails it shows
   "Can't reach Hacker News" and retries after 60 seconds, then 120, then 5 minutes.
3. When the queue reaches its end and the cache is older than the refresh interval, a background
   thread fetches the next list; the show keeps playing while it does. A successful refresh
   replaces the queue from its first slide. A failed one leaves the current queue playing and puts
   the offline badge under the header; the next attempt is 60 seconds later, doubling to 5
   minutes.
4. A successful refresh clears the badge and resets the backoff.

Changing settings takes effect the next time the screensaver starts: exit it (any key) and wait
for it again. *Clear cache* deletes all five files (only the chosen list is used at a time, but
clearing is all-or-nothing and fast); the next start fetches afresh.

## Data and how it is used

Two hosts, both Hacker News':

| What | Endpoint |
|---|---|
| Story ids | `https://hacker-news.firebaseio.com/v0/{top,best,new,ask,show}stories.json` |
| Story item | `https://hacker-news.firebaseio.com/v0/item/{id}.json` |
| Comment tree | `https://hn.algolia.com/api/v1/items/{id}` |
| Comment item (fallback) | `https://hacker-news.firebaseio.com/v0/item/{id}.json` |

- HTTPS only, with certificate validation left on. On Android Kodi, whose Python has no system CA
  store, HTTPS to these hosts works through Kodi's own bundle.
- Every request sends `User-Agent: screensaver.hackernews/0.1.0 Kodi`.
- Timeouts are 10 seconds, one retry follows a 0.6-second pause, and at most six requests run at
  once (`ThreadPoolExecutor`).
- A story list is trimmed to the number of stories chosen. A story whose item fails is skipped; a
  story whose comments fail simply has none this pass. Comments are kept as their first ten
  top-level entries (Algolia returns them in ranking order), with author, time and text.
- Nothing is written back: no login, no votes, no comments, no telemetry, no requests to any other
  domain. Titles, scores and comments remain the work of their authors.

The cache files hold only what is displayed: title, URL, score, author, time, comment count and
the chosen comments' text.

## Leaving the screensaver

Any key, click or remote button closes it, as does waking the screensaver from outside. The window
is shown with `show()` and watched by the runner rather than with `doModal()`, because Kodi can
close a screensaver itself (a screenshot, a notification) without telling Python, and `doModal()`
would then never return. Python closes the window with `Dialog.Close(id, true)`, which is posted to
Kodi's main thread and cannot deadlock the way `Window.close()` can while Kodi is restarting the
screensaver.

## Project layout

```
screensaver.hackernews/
  addon.xml                     metadata, xbmc.python 3.0.0, screensaver extension
  screensaver.py                entry point: ui.run(), or ui.clear_cache() for the action
  icon.png  fanart.jpg          artwork
  LICENSE.txt                   MIT, plus the non-affiliation and API notice
  resources/
    settings.xml                generated from config.py by tools/make_hackernews_settings.py
    language/resource.language.en_gb/strings.po
    lib/
      config.py                 settings table, strings table, themes; no Kodi imports
      hn_client.py              both APIs, trimming, Algolia→Firebase fallback; injectable get
      formatter.py              HTML → Kodi label, truncation, reading time, ages; no Kodi imports
      playlist.py               the slide queue; no Kodi imports
      cache.py                  JSON files on disk, atomic writes, TTL; no Kodi imports
      ui.py                     the window class, the show loop, fetching, properties
    skins/Default/
      media/white.png           solid texture for the background and bars
      1080i/screensaver-hackernews.xml  the whole window: header, two content layers, footer
```

The five modules without Kodi imports (`config`, `formatter`, `playlist`, `cache`, plus
`hn_client`) hold all the logic and are what the tests exercise.

## Development and testing

```bash
python3 tools/make_hackernews_settings.py      # regenerate settings.xml and strings.po
python3 tools/make_hackernews_media.py         # regenerate icon, fanart, white texture (Pillow)
python3 -m unittest tests.test_hackernews      # 44 tests, offline, no Kodi needed
```

The tests use recorded live JSON in `tests/fixtures/hackernews/`:

- `topstories.json` — the first 50 ids of the real top list;
- `item_50442736.json` — the story `.name Grandfathered`, 268 points, 16 comments;
- `algolia_50442736.json` — its comment tree, trimmed to the first five top-level comments with
  their first replies.

What is covered: entities, paragraphs, line breaks, italics, links and raw URLs, `<pre><code>`
indentation, bracket escaping, sentence/word truncation, minimum lengths, reading time clamps, age
text; queue order, ranks, randomization, per-story comment counts, the short-comment fallback,
first replies, the meta line and refresh timing; cache round-trip, corruption, atomic saves and
clearing; story trimming and filters, Algolia parsing from the fixture, the Firebase `kids`
fallback with synthetic items; settings.xml/strings.po against the config table, clamping and
option bounds; and skin sanity (required control ids, mirrored `a.`/`b.` properties).

Notes for the next change:

- **Kodi has no dynamic controls.** Everything is in the window XML once per layer; Python sets
  window properties. Adding a label means editing both layer groups (100/200 and 110/120,
  210/220) and their property names.
- **Fonts cannot change at run time**, so *Font scale* is four conditional zoom animations on the
  drift group (80, 90, 110, 120); 100 percent is no animation.
- **The progress bar** is an image whose width Python sets with `setWidth()`, from 1 px to 1728 px
  (the bar's full width), every 100 ms.
- **Drift** moves group 900 by absolute offsets from a fixed cycle
  `(0,0), (4,2), (-3,3), …` every 60 seconds. If the Kodi build cannot move a group, drift
  switches itself off quietly.

## Troubleshooting

**"Can't reach Hacker News" stays on screen.** The device has no usable network route to
`hacker-news.firebaseio.com` or `hn.algolia.com`, or DNS is failing. Check the clock: HTTPS
certificate validation fails when the system date is far off. The screensaver retries every 5
minutes; *Clear cache* only removes old data, it cannot fix connectivity.

**It shows old stories and the offline badge.** A refresh failed; the cached queue is still
playing. It retries within a minute. If it persists, the network is down or a firewall blocks one
of the two hosts.

**Comments are missing under some stories.** Those stories' comment fetches failed, or their
comments are all below *Minimum comment characters*. Turning *Use Algolia for comments* off uses
Firebase's item-by-item fallback, which is slower but sometimes succeeds when Algolia is down.

**Not enough comments.** Hacker News stories without discussion simply have none. Reduce the
minimum characters, or raise *Comments per story*.

**The clock or a status line is in the wrong place.** Kodi's Estuary skin fonts differ from build
to build; the layout uses system font names so it works without registering fonts. If a build
shows clipping, lower *Font scale*.

**It does not appear in the screensaver list.** Check that the repository's `addons.xml` lists
`screensaver.hackernews` (the build step writes it), then restart Kodi. Enabling debug logging and
looking for `[screensaver.hackernews]` in kodi.log shows whether it started and what it fetched.

## Known limitations

- No touch gestures and no scrolling within a slide: a comment is cut to *Maximum comment
  characters*, not paged.
- Only top-level comments are shown, ten at most, with optionally one reply each. Deeper trees are
  not walked.
- The queue is built once per fetch; if you change the story list, the cache is fetched for that
  list and the first slide of the new queue may repeat the last story.
- Ages are relative to when the queue was built, not re-computed per slide; the refresh interval
  keeps that difference small.
- Story ranks are positions in the fetched list. New and Best change quickly, so between refreshes
  a rank can be out of date.
- Hacker News' API is unauthenticated and best-effort; there is no retry beyond one per request.
  The cache and fallbacks are what keep the screen filled.

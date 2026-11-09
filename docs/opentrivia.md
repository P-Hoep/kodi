# OpenTrivia — screensaver (`screensaver.opentrivia`) and app (`script.opentrivia`)

A trivia quiz that runs itself on the television and one you can play with the remote. Both draw
from the same 49,110 questions in 22 categories, converted from the
[OpenTriviaQA](https://github.com/uberspot/OpenTriviaQA) collection into one SQLite database.

- **The screensaver** picks a question at random, shows a countdown bar, reveals the answer and
  moves on. It needs no input at all.
- **The app** lets you pick the answer with a remote, a mouse or a finger, keeps score, and shows
  the correct answer the moment you choose.

Both add-ons use the shared library `script.module.opentrivia`, which Kodi installs with them;
it holds the database, the window skin, the textures and all of the code. Requires Kodi 20
(Nexus) or later.

## 1. Categories

All 22 categories are on at first and each has its own switch under **Categories**. They are
grouped as the settings dialog shows them:

| Group | Categories |
|---|---|
| Everyday | General, Newest, Rated, For Kids, People |
| Arts & media | Movies, Music, Television, Celebrities, Entertainment |
| Knowledge | Science & Technology, History, Geography, World, Humanities |
| Words & ideas | Literature, Religion & Faith, Brain Teasers |
| Life & leisure | Sports, Hobbies, Animals, Video Games |

A question is packed as the question text plus two to four answers, one of which is correct.
`Newest` and `Rated` are the OpenTriviaQA sources of the same name. If every switch is turned
off, the add-on falls back to using them all rather than sitting there with nothing to show.

## 2. The screensaver

Each question appears for **Seconds before the answer is revealed** (10 by default); during that
time the accent bar under the question drains as a countdown. The correct answer then turns
green with a check and the other answers fade back, for **Seconds the answer stays up** (6 by
default). The window then fades out and the next question comes in.

- **Countdown bar** and **clock** can be turned off.
- **Dim after (minutes)** slowly dims the whole screen for OLED and plasma panels; 0 is never.
- The category above the question follows **Show the category**.
- Any key, click, tap or mouse movement closes the screensaver immediately, and so does Kodi
  itself waking it.

## 3. The app

The start screen offers **Start**, **Settings** and **Quit** (Back quits). A round is
**Questions per round**: 10, 20 (the default), 30, 50 or Endless.

- **Answering.** Each answer is a real button, so focus + Select, a mouse click and a touch all
  work. Number keys are not bound; the d-pad moves between options and Select answers.
- **The reveal.** The pick turns red with a cross and the correct answer turns green with a
  check; the other answers fade. A wrong answer shakes briefly. **Correct** or **Not quite**
  appears next to the **Next** button.
- **Moving on.** With **Move on automatically after an answer** on (the default) the next
  question arrives after **After a correct answer** (1 s) or **After a wrong answer** (2.5 s),
  both adjustable. With it off, choose **Next** yourself.
- **Pause.** Back opens a pause sheet with **Resume**, **End round**, **Settings** and
  **Quit to Kodi**. Back again resumes.
- **Results.** Your score, accuracy, best streak and the count of correct and missed answers,
  then **Play again**, **Settings** and **Quit**.

## 4. Look

The same look settings are in both add-ons. Every colour and texture is set by the skin at run
time, so the add-ons look the same in every Kodi skin.

| Setting | Options |
|---|---|
| Theme | Ink (default), Paper, Midnight, Auto |
| Day starts at / Night starts at | 07:00 and 19:00 by default; only Auto uses them (Paper by day, Ink at night) |
| Accent colour | Theme (each theme's own accent), Gold, Rust, Teal, Blue, Rose, Custom (hex) |
| Custom colours | Background, question card, answer options, text, muted text, correct answer, wrong answer; empty uses the theme. Text on a custom card is chosen for contrast. |
| Answer layout | Auto (default; short answers in two columns, long ones in a list), Cards (always two columns), List (always one column) |
| Show the A/B/C/D letters | on |
| Show the category | on |
| Show the question number | on (app only) |
| Background | Solid, Soft glow (default) |
| Text size | 80–130 % (100) |
| Dim the screen | 0–80 % (0) |

Two answers always take the two wide rows; three or four follow the layout setting. The question
font steps between four sizes by its length, so a long question stays inside its card.

## 5. Data and licence

`tools/make_opentrivia_db.py` reads the category files in `OpenTrivia/`, de-duplicates them,
caps the answer count at four and writes `script.module.opentrivia/resources/data/trivia.db`
(inserted in random order). The questions and answers are © the OpenTriviaQA contributors and
are licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); the add-on code is MIT. Each
add-on's `LICENSE.txt` carries the attribution and lists the changes made to the data.

Questions are read in blocks: one query picks up 600 consecutive rows by their primary key, the
block is filtered by the chosen categories and shuffled in memory, and a block is only visited
again after every other block has been used. That is one database read per 600 questions, not
one per question.

## 6. Building

```bash
python3 tools/make_opentrivia_db.py        # OpenTrivia/ -> resources/data/trivia.db
python3 tools/make_opentrivia_media.py     # textures, icon and fanart (Pillow)
python3 tools/make_settings_opentrivia.py  # both settings.xml + all strings.po from lib/opentrivia/config.py
python3 tools/make_opentrivia_skin.py      # the one shared WindowXML
python3 tools/build_zip.py script.module.opentrivia
python3 tools/build_zip.py script.opentrivia
python3 tools/build_zip.py screensaver.opentrivia
python3 -m unittest tests.test_opentrivia  # offline: settings, database, blocks, theme, quiz, skin, strings
```

## 7. How it is put together

```
script.module.opentrivia/
  lib/opentrivia/
    config.py     settings table, category list, all static strings
    database.py   sqlite3 open, block reads, category filter, count
    quiz.py       question/option font buckets, layout choice, Round scoring
    theme.py      Ink/Paper/Midnight/Auto, accents, custom colours, derived colours
    ui.py         the shared WindowXMLDialog (Screen) and the property presenter (View)
    kodi.py       settings, strings, database path, logging (the only Kodi imports)
    __init__.py   add-on ids
  resources/
    data/trivia.db
    skins/Default/1080i/opentrivia.xml   GENERATED by tools/make_opentrivia_skin.py
    media/                               white shapes, outlines and icons, tinted at run time
script.opentrivia/        default.py + app.py      start -> round -> results
screensaver.opentrivia/   default.py + saver.py    question -> countdown -> reveal -> next
```

- **One window for both.** `ui.Screen` is a `WindowXMLDialog` from the library's skin. The app
  shows it with `doModal()`; the screensaver shows it with `show()` and waits in a loop instead,
  because Kodi closes a screensaver's window without telling Python when it wakes the screensaver
  itself (a screenshot or a notification does that), and `doModal()` would then never return.
- **Input.** `onAction`/`onClick` put events on a queue on Kodi's UI thread; the front-end's
  logic runs on a worker thread and reads that queue, so a remote press is never delayed by a
  timer. The screensaver's `on_input` wakes it on the UI thread and returns at once.
- **Only properties.** Python never creates, moves or animates a control. It sets `ot.*` window
  properties and the XML decides what is visible, what colour it takes and how it animates. That
  is what lets one XML file serve every theme, layout and view.
- **Fonts come from the active skin.** Estuary on Kodi 21 defines `font45`, `font37`, `font27`,
  `font23_narrow` and friends; a name that does not exist silently falls back to a tiny default,
  so the generated XML and the test both check against the real list.

# Project: Audiobookshelf Kodi Add-on

## Objective

Build a Kodi add-on that connects to an existing Audiobookshelf server and provides a polished audiobook browsing, playback, and listening-progress experience within Kodi.

The application should feel like a native Kodi media experience, be usable with a TV remote, and avoid unnecessary complexity.

## 1. Platform and implementation

- Implement this as a Kodi add-on using the appropriate Kodi add-on APIs and Python runtime supported by the target Kodi versions.
- Use Audiobookshelf's official API wherever possible.
- Before implementing API calls, consult the official Audiobookshelf API documentation and verify the available endpoints, authentication requirements, response formats, and media-streaming behavior.
- Use Kodi's native audio player for playback rather than building a separate audio engine.
- Follow Kodi conventions for navigation, playback, artwork, settings, and error handling.
- Keep the implementation modular, with separate responsibilities for API communication, library browsing, playback, progress synchronization, and settings.
- Avoid unnecessary dependencies and keep the code compatible with the Python version supported by the selected Kodi target.

## 2. Initial setup and connection

Provide a settings screen that allows the user to configure:

- Audiobookshelf server URL.
- Authentication credentials or API token, using a supported authentication method.
- Optional connection timeout and synchronization preferences.

Requirements:

- Validate the server connection and authentication.
- Display a useful error if the server is unreachable or authentication fails.
- Store credentials using an appropriate secure mechanism where available.
- Allow users to edit the connection settings without reinstalling the add-on.
- Do not hardcode server addresses, credentials, or user-specific identifiers.

## 3. Home screen

Create a home screen with these entries:

1. Continue Listening
2. Recently Added
3. All Audiobooks
4. Series
5. Authors
6. Search
7. Settings

Show relevant audiobook cover art, titles, authors, and listening progress.

Empty categories should display a helpful message instead of an error.

## 4. Library browsing

### All Audiobooks

- Retrieve the user's accessible audiobook library from Audiobookshelf.
- Display a navigable list or grid of books with cover art.
- Support sorting by title, author, recently added, and series where the API and available metadata permit.
- Support pagination or incremental loading for large libraries.
- Cache metadata and artwork appropriately to reduce repeated requests.

### Audiobook details

Show the available metadata for each audiobook:

- Title
- Author
- Narrator
- Description
- Cover artwork
- Total duration
- Series and sequence number, if available
- Listening progress
- Chapter list, when available

Provide actions to Play, Resume, and select a chapter.

### Series and authors

- Group audiobooks by series and author using available server metadata.
- Display the associated books in a sensible reading or listening order.
- Handle missing metadata gracefully.

### Search

- Allow users to search audiobooks by title, author, and series.
- Debounce requests or search locally against cached metadata when appropriate.
- Provide clear feedback for empty results and failed searches.

## 5. Playback

- Start playback using Kodi's native player.
- Use a valid Audiobookshelf media-streaming URL or supported playback method verified against the actual API.
- Resume from the last known listening position.
- Start playback from a selected chapter when chapter seeking is supported.
- Display the audiobook's cover art, title, chapter information when available, and progress through Kodi's normal playback interface.
- Support play, pause, seeking, and skip-forward/skip-backward using Kodi's native controls.
- Allow configurable seek intervals, with sensible defaults.
- Handle expired stream URLs, interrupted connections, and unavailable media.
- Do not download entire audiobooks into memory.
- Do not assume that a browser-oriented streaming endpoint will work with Kodi; verify stream compatibility and required headers.

## 6. Listening progress synchronization

Audiobookshelf must remain the source of truth for the user's listening progress.

- Retrieve the current listening position and completion status.
- Resume from the saved position when playback starts.
- Periodically report playback progress using the appropriate supported API mechanism.
- Report progress when playback pauses, stops, or ends.
- Synchronize chapter and completion information when supported.
- Avoid sending excessive requests or creating conflicting updates.
- Handle temporary network failures with bounded retries and safe recovery.
- Preserve the most recent valid position if synchronization fails.
- Ensure completed books do not unexpectedly restart at an old position.
- Do not mark a book completed merely because the user stopped playback early.

Use the server's documented progress-update semantics rather than inventing custom endpoints or payloads.

## 7. Visual design and remote-control usability

- Use a dark, uncluttered interface that fits naturally into Kodi.
- Prioritize cover art and readable titles.
- Use clear visual distinctions between unplayed, in-progress, and completed audiobooks.
- Provide visible listening-progress indicators.
- Ensure all important actions can be performed using a standard TV remote or keyboard.
- Preserve predictable Back, Select, and navigation behavior.
- Avoid mouse-dependent controls, excessive nested menus, and unnecessary dialogs.
- Keep the interface responsive when navigating large libraries.

## 8. Caching and performance

- Cache library metadata and artwork where appropriate.
- Refresh cached data without blocking the entire interface unnecessarily.
- Avoid fetching the same audiobook metadata repeatedly.
- Support large libraries through pagination or incremental loading.
- Handle missing covers and incomplete metadata with sensible fallbacks.
- Keep playback independent of background library-refresh operations.

## 9. Error handling and logging

Handle the following cases explicitly:

- Server unreachable.
- Invalid credentials.
- Expired authentication.
- Empty library.
- Missing audiobook files.
- Unsupported stream format.
- Network interruption during playback.
- Failed progress synchronization.
- Missing artwork or metadata.
- Unexpected API response.

Provide useful user-facing messages and diagnostic logs without logging authentication secrets.

## 10. Testing and acceptance criteria

The add-on is complete when:

1. A user can configure an Audiobookshelf server and connect successfully.
2. The user's audiobooks and cover artwork appear in Kodi.
3. The user can browse, search, and open audiobook details.
4. The user can start an audiobook and control playback using Kodi.
5. Resuming a partially played audiobook starts at the saved position.
6. Playback progress is sent back to Audiobookshelf.
7. The updated position is retained after stopping playback and restarting Kodi.
8. Network failures do not crash Kodi or permanently lose the saved position.
9. Empty libraries, missing metadata, and authentication errors are handled cleanly.
10. The add-on can be installed and configured using Kodi's normal add-on mechanisms.

## Implementation instructions

Start by inspecting the target Kodi version, the official Audiobookshelf API documentation, and any existing Kodi add-on structure.

First produce a concise implementation plan identifying the required API endpoints, authentication flow, streaming approach, progress-sync mechanism, and Kodi integration points.

Then implement the smallest complete working version, prioritizing connection, audiobook browsing, playback, and progress synchronization.

Do not invent API endpoints or assume unverified response schemas. Clearly identify any API behavior that requires verification.

Keep the scope focused on audiobook listening. Do not implement unrelated media types, user administration, a web interface, or a replacement for the Audiobookshelf server.

Include installation instructions, configuration instructions, diagnostic logging, and a list of any remaining limitations.
---

# Implementation (plugin.audio.audiobookshelf 1.1.0)

Built 2026-10-13; 1.1.0 the same day added sign-in with a username and password, Genres and
random play. Tested on Kodi 21.1 (macOS) against an Audiobookshelf 2.28.0 server with
666 books, including multi-file MP3 books. Targets Kodi 19+ (`xbmc.python` 3.0.0) and uses no
modules beyond the standard library and `script.module.certifi` (for HTTPS on Android).

## Plan as built

| Part | How |
|---|---|
| Authentication | **Username and password** (`resources/lib/auth.py`): `/login` returns an access token (12 h) and a refresh token (7 d), kept in `tokens.json` in the profile folder and renewed automatically; if renewal fails the add-on signs in again with the stored password. An **API key** is the alternative, and stays in use on installs from 1.0 until a username is entered. Either way requests carry `Authorization: Bearer <token>`. |
| Browsing | Plugin directories (`resources/lib/plugin.py`), one Kodi call per screen. |
| Streaming | A playback session with direct play; Kodi plays the original files as a playlist, with the key sent as a header (`url\|Authorization=Bearer%20…`). |
| Progress | A background service (`resources/lib/player.py`) follows Kodi's player and reports through the session's sync and close calls. |
| Settings | `resources/lib/config.py`, turned into `settings.xml` and `strings.po` by `tools/make_settings_audiobookshelf.py`. |

Modules: `api.py` (HTTP client and error types), `model.py` (JSON to book records, track and
chapter timeline maths, resume rules), `sync.py` (listened-time bookkeeping and the pending
queue), `cache.py` (on-disk list cache), `kodiutil.py` (Kodi glue), `plugin.py`, `player.py`.
Only the last three import Kodi modules, so the rest is covered by `tests/test_audiobookshelf.py`.

## API used (each call checked against the 2.28.0 server)

| Call | Used for | Notes from checking |
|---|---|---|
| `GET /status` | Is it an Audiobookshelf server? | No auth needed. Returns `app`, `serverVersion`. |
| `POST /login` + header `x-return-tokens: true` | Sign in | Body `{username, password}`. `user.accessToken` (JWT, 12 h), `user.refreshToken` (JWT, 7 d); also the deprecated non-expiring `user.token`, which is not used. 401 for a wrong password. |
| `POST /auth/refresh` + header `x-refresh-token` | Renew tokens | Returns a new pair in `user`. Rotates: the old refresh token is rejected (401) once used. |
| `GET /api/libraries/:id/filterdata` | Genres | `genres[]` (names only, 96 on the test server), also tags, narrators, series. |
| `GET /api/me` | Validate the sign-in; all progress | `mediaProgress[]` with `libraryItemId`, `currentTime`, `progress`, `isFinished`, `lastUpdate`. 401 for a bad key. |
| `GET /api/libraries` | Pick the book library | Podcast libraries (`mediaType: podcast`) are left out. |
| `GET /api/me/items-in-progress` | Continue Listening | Items carry no progress, so it's merged from `/api/me`. Covers all libraries; filtered by `libraryId`. |
| `GET /api/libraries/:id/items` | All books, Recently Added, a series, an author | `sort`, `desc`, `page`, `limit`, `minified`, `filter=series.<base64 id>` / `authors.<base64 id>`. The sorts honoured are `media.metadata.title`, `media.metadata.authorNameLF` and `addedAt`; `media.metadata.seriesName` is silently ignored, so series order comes from the Series view. Filtered by series and not minified, `media.metadata.series` is one `{id, name, sequence}` dict. |
| `…/items?sort=random` | Random book | The server shuffles. Combined with `filter=progress.<base64 "not-finished">` (whole library) or `filter=genres.<base64 name>` (one genre); finished books and books with missing files are skipped client-side. Progress filter values: `finished`, `not-started`, `not-finished`, `in-progress`. |
| `GET /api/libraries/:id/series` | Series list | `results[].books[]`, `total`. |
| `GET /api/libraries/:id/authors` | Authors | `authors[]` with `numBooks`, `imagePath`. |
| `GET /api/libraries/:id/search?q=` | Search | `book[].libraryItem`, `series[].series/books`, `authors[]`. Matches titles, authors and series. |
| `GET /api/items/:id?expanded=1&include=progress` | Book page | `media.chapters[]` (`start`, `end`, `title`), `media.tracks[]`, `userMediaProgress`. |
| `GET /api/me/progress/:id` | Resume point | 404 when the book was never started. |
| `GET /api/items/:id/cover?width=&format=jpeg` | Covers | No auth needed. WebP by default, so JPEG is asked for. 404 when there is no cover. |
| `GET /api/authors/:id/image` | Author photos | No auth needed. |
| `POST /api/items/:id/play` | Start a session | Body: `deviceInfo`, `forceDirectPlay: true`, `supportedMimeTypes`, `mediaPlayer: "kodi"`. Answer: `id`, `currentTime` (the saved position), `duration`, `chapters`, `audioTracks[]` with `startOffset`, `duration`, `mimeType` and `contentUrl` (`/api/items/:id/file/:ino`). `playMethod` 0 is direct play. |
| `GET <contentUrl>` | The audio | Needs auth (401 without). A Bearer header works, and so does `?token=`; the header is used, so the key stays out of URLs. HTTP Range gives 206. |
| `POST /api/session/:id/sync` | Progress while playing | Body `currentTime`, `timeListened`, `duration`. Plain-text `OK`. 404 once the session has been closed. |
| `POST /api/session/:id/close` | Progress on stop | Same body. |
| `PATCH /api/me/progress/:id` | Fallback when a session has gone | Body `currentTime`, `duration`, `progress`. Sends only the position; the server decides `isFinished`. |

## Progress rules

- The server is the source of truth: Resume always asks it for the position at that moment.
- **Reported:** every *Send progress every* seconds (30 by default) while playing, once on
  pause, and on stop (session close). `timeListened` counts only wall time spent playing, at
  most 5 s per tick, so a paused or sleeping box doesn't add listening time.
- **Nothing is reported until playback reaches the requested start** (resume point, chapter or
  skip), within 15 s. Kodi gets the start as the item's `StartOffset`, and the service retries the
  seek for 20 s. If it never gets there, nothing is reported for that session and the saved
  position stays as it was. (The first test build seeked after start; Kodi ignored that seek, and
  the build would have saved 0:47 over a 5:29:58 position.)
- **End of book:** if Kodi ends the playlist within 60 s of the end, the close sends the full
  length and the server marks the book finished. Stopping early sends the actual position,
  so a book is never marked finished just because playback stopped.
- **Finished books:** Resume and Play start from the beginning, never from an old position.
  The same applies to a position within 30 s of the end.
- **Failures:**
  - A 404 on sync means the server forgot the session (restart or expiry). A new session is
    opened for the same book; if that fails, the position is written with `PATCH`.
  - If the server can't be reached, the position goes to `addon_data/…/pending.json`. It is
    sent at the next playback start or every 5 minutes, with up to 20 attempts over up to 7
    days. It is dropped if the server already has a newer update.
  - Sync retries back off 15 s, 30 s, 60 s, 120 s, then 300 s.
- **Stop and end events** are confirmed 2.5 s later, because Kodi also fires them between a book's
  files and when another book replaces the current one.

## Install and configure

**Sign in (1.1):** open the add-on and choose **Sign in to your Audiobookshelf server…**. It asks for
the address, the username and the password (masked) in turn, then confirms the server version, user
and libraries. The same fields are in the settings under **Sign in with → Username and password**.
The steps below use an API key instead.

1. Install from the P-Hoep repository (**Add-ons → Install from repository → P-Hoep Add-ons →
   Music add-ons → Audiobookshelf**), or from a zip built with
   `python3 tools/build_zip.py plugin.audio.audiobookshelf`.
2. In Audiobookshelf: **Settings → API Keys → Add API Key**. Give it a name (for example
   "Kodi"), choose the user whose progress Kodi should use, and copy the key.
3. In Kodi, open the add-on's settings:
   - **Server address**, for example `http://192.168.1.10:13378`. `http://` is added if left out.
   - **API key**: the input is masked.
   - **Test connection…** confirms the server version, the user and the audiobook libraries.
4. If the server has several audiobook libraries, use **Choose library…**. The home screen then
   shows which library is selected.
5. Other settings:
   - Connection timeout.
   - Skip back and skip forward steps.
   - Step back when resuming.
   - Send progress every N seconds.
   - Books per page.
   - Default sort.
   - How long library lists are cached. Progress is never cached.
   - **Clear cached library data**.

Diagnostics: lines tagged `[plugin.audio.audiobookshelf]` in `kodi.log` cover sessions opened
and closed, the resume point, sync failures and fallbacks. The API key is never written to the
log. The client never puts it in URLs or exception messages, and every log line is scrubbed.

## Remaining limitations

- **Password storage:** the password (or API key) is stored in plain text in Kodi's
  `addon_data/…/settings.xml`, so the add-on can sign in again on its own after a week unused. Kodi
  has no secure store; anyone with access to the device's files can read it. Use a non-admin
  account, and change its password if the device is lost.
- **Very long sessions:** Kodi fixes a playlist's URLs, token included, when playback starts. The
  add-on starts playback with a token that has at least 8 of its 12 hours left, so one unbroken
  session of over 8 hours can hit an expired token; stopping and resuming fixes it.
- **Genres** show without book counts (the server's genre list has none).
- **Podcast libraries** are not shown (out of scope).
- **Now-playing title:** Kodi shows the file's own tags (for example "a. The Terror"), not the
  book or chapter name. The service tries to change the title to the chapter name (Kodi 20+),
  but in testing Kodi kept the file's title for MP3s.
- **Seek steps on the remote:** Kodi's own seek steps are global. The add-on's skip steps
  need a keymap entry calling the `skip` action (see the README).
- **Sorting by series** in All Audiobooks isn't offered, because the server ignores it. Use
  Series.
- **Untested:** Kodi 19 and 20 (Python code paths for the older list-item API are there but
  untested), Fire TV, HTTPS servers, and books stored as a single `.m4b` with embedded chapters.
- **Continue Listening** shows the server's in-progress list (up to 100 books).

Live Cams Kodi Screensaver — Spec
Oct 15, 2026 · @Patrick
Overview
A Kodi screensaver add-on (working ID screensaver.livecams) that turns an idle TV into a window onto live outdoor scenes, rotating through verified camera feeds from the Live-Environment-Streams  https://github.com/william-ricchiuti/Live-Environment-Streams dataset with a minimal location overlay.
Goals
• Start a live camera within 5 seconds of the screensaver activating, and exit instantly on any input.
• Play only feeds Kodi can open natively in v1 (direct HLS), so the add-on works with no extra dependencies.
• Favour scenes worth looking at: daylight, scenic environments, HD where known.
• Never interrupt or lose the user's own paused media.
• Self-heal: skip dead or stalled feeds silently and remember them.
Non-goals for v1
• Scraping HTML camera pages (SkylineWebcams token refresh).
• Browsing cameras as a video add-on (a natural v2 companion).
• Recording, analysis or any computer-vision features the dataset was built for.
Data source
The add-on reads streams.geojson from the repo: 5,997 cameras across 98 countries and 67 sources, of which 4,226 are marked verified active. Each camera is a GeoJSON Feature with a point geometry ([lon, lat]) and the properties below. Per-country subsets live in data/<CC>.json; per-source licence notes live in sources.json. The repo re-validates weekly via a GitHub Action.
Property
Values
Used for
url
HLS manifest, YouTube link, or HTML page
Playback
url_type
hls (3,754), youtube (475), html_page (1,768)
Choosing a resolver; v1 plays hls only
source_url_requires
null, browser, token_refresh
Exclude anything non-null in v1
status
active, unverified
Default pool = active; unverified opt-in
environment
traffic 3,551 · urban 1,375 · coastal 461 · mountain 161 · harbor 119 · lake 89 · nature 78 · waterway 71 · landmark 54 · marina 32 · transport 6
Category filter
scene_type
Finer label (beach, marina, traffic…)
Overlay icon, future filters
quality_tier
premium, high, standard, low
Selection weighting
resolution
WxH or null
Minimum-resolution filter
display_name, name
Location label, camera name
Overlay text
country_code
ISO 3166-1 alpha-2
Overlay flag/name, country filter
geometry.coordinates
[lon, lat]
Daylight check, local time
coordinates_quality
exact, city, country_centroid
Skip daylight maths for country_centroid (10 cams)
source_family
e.g. vdot, skylinewebcams, youtube
Licence lookup, per-source block list
last_verified
ISO 8601 or null
Freshness tiebreak
Default v1 pool: status == active AND url_type == hls AND source_url_requires is null AND environment != traffic. The README's own recommended filter (which also admits YouTube) yields about 2,929 streams; the HLS-only, non-traffic pool will be considerably smaller and must be measured at build time (open question).
Camera selection
Selection is a weighted random draw from the filtered pool, biased toward daylit, high-quality scenes and away from anything shown recently.
1. Filter the cached catalog by the user's settings: environments, countries (allow or block list), minimum resolution, include unverified, and the local health block list (see Caching and health).
2. Daylight check (default on). Compute solar elevation for each camera's coordinates at the current UTC time, entirely offline (NOAA solar position formula, no API). Classify as day (sun above 0°), twilight (−6° to 0°) or night. Cameras with coordinates_quality == country_centroid are treated as unknown and only used if nothing else qualifies.
3. Weight each remaining camera:
    ◦ Daylight: day ×1.0, twilight ×0.6 (golden hour can be the best view), night ×0.05 unless "Night cams" is on.
    ◦ quality_tier: premium ×1.5, high ×1.2, standard ×1.0, low ×0.5.
    ◦ Favourites ×3; cameras shown in the last 6 hours ×0.1; same source_family or country as the current camera ×0.5 to keep variety.
4. Draw one camera and hand it to the resolver. If the pool is empty after filtering, relax filters in this order: daylight → minimum resolution → unverified allowed → show the static fallback card.
Rotation: each camera plays for a dwell time (default 3 minutes, range 30 s to 30 min, or "never rotate"). A "Follow the sun" mode is a v1.1 candidate: pick the next camera roughly where the sun is currently rising or setting.
Stream resolution and playback
Each url_type gets its own resolver behind one interface, resolve(camera) -> PlayableItem | None; v1 ships the HLS resolver only and the others stay behind settings flags.
url_type
v1
Resolver
Notes
hls
On
Pass the URL straight to xbmc.Player as a ListItem; optionally route through inputstream.adaptive if installed (setting)
Kodi plays live HLS natively via its FFmpeg demuxer
youtube
Off (v1.1 opt-in)
Hand off to the YouTube add-on via plugin://plugin.video.youtube/play/?video_id=<id>
Hard dependency on a third-party add-on and its API-key setup; README notes broadcasters rotate video IDs
html_page
Not supported
Would require fetching the page and extracting a short-lived m3u8
Mostly SkylineWebcams; out of scope pending a terms-of-use review
Pre-flight probe. Before switching, fetch the manifest with a 4 s timeout and confirm an #EXTM3U header and at least one variant or segment. A failed probe costs no screen time: the selector simply draws again.
Playback. Create a ListItem with the stream URL, set IsPlayable, mime application/vnd.apple.mpegurl, and title/plot from the camera so Kodi's own OSD stays sensible. Audio is muted by default (most cams are silent or have wind noise); a setting allows sound.
Start and stall detection.
• Start timeout: 15 s from play() to onAVStarted. Miss it and the camera is marked failed.
• Stall: Player.getTime() fails to advance for 10 s, or onPlayBackError/onPlayBackEnded fires on a live stream. Mark failed and move on.
• Up to 5 consecutive failures, then show the fallback card for 60 s and retry (handles a dropped internet connection without hammering).
Add-on architecture
A pure-Python Kodi add-on registered on the xbmc.ui.screensaver extension point, targeting Kodi 21 "Omega" and later (Python 3). It follows the pattern already proven by video screensavers such as Aerial (screensaver.atv4): a full-screen WindowXMLDialog owns input and the overlay, while xbmc.Player renders video beneath it.
screensaver.livecams/
  addon.xml
  default.py                  # entry: build window, start controller, block until exit
  resources/
    settings.xml
    language/resource.language.en_gb/strings.po
    lib/
      catalog.py              # download, cache, parse, index streams.geojson
      selector.py             # filters, daylight weighting, history
      sun.py                  # offline solar elevation + local time from lon/lat
      resolvers/hls.py        # probe + ListItem
      resolvers/youtube.py    # v1.1, disabled
      player.py               # xbmc.Player subclass: start/stall detection
      health.py               # failure scores, block list with TTL
      overlay.py              # label text, fade timers, burn-in drift
      controller.py           # main loop tying it together
    skins/default/1080i/screensaver-livecams.xml
    media/  (icons, fallback card background)
<addon id="screensaver.livecams" name="Live Cams" version="1.0.0" provider-name="…">
  <requires>
    <import addon="xbmc.python" version="3.0.0"/>
  </requires>
  <extension point="xbmc.ui.screensaver" library="default.py"/>
  <extension point="xbmc.addon.metadata">
    <platform>all</platform>
    <summary lang="en_GB">Live outdoor webcams from around the world</summary>
    <license>TBD</license>
  </extension>
</addon>
Exit handling. The window's onAction (any key, remote, mouse or CEC input) stops the player, closes the window and returns. An xbmc.Monitor subclass also watches onScreensaverDeactivated and abortRequested so Kodi shutdown or another add-on waking the screen exits cleanly within 1 s.
Protecting the user's media. At activation, check xbmc.Player().isPlaying(). If the user's own media is paused, do not start a camera (that would discard their item); fall back to the dim/black mode with the clock overlay only. This is a hard requirement.
Settings
Four categories in settings.xml (Kodi settings format v2); defaults are chosen so the add-on looks good with zero configuration.
Category
Setting
Type
Default
Cameras
Environments
Multi-select
coastal, mountain, lake, nature, waterway, harbor, marina, landmark, urban
Cameras
Include traffic cameras
Toggle
Off
Cameras
Countries
Allow list / block list
All
Cameras
Minimum resolution
480p / 720p / 1080p / any
720p (unknown resolution allowed)
Cameras
Include unverified streams
Toggle
Off
Cameras
Favourites only
Toggle
Off
Rotation
Time per camera
Slider, 30 s to 30 min, or never
3 min
Rotation
Prefer daylight
Toggle
On
Rotation
Allow night cameras
Toggle
Off
Display
Overlay
Off / on change / always
On change (8 s)
Display
Show local time at camera
Toggle
On
Display
Show clock (viewer's time)
Toggle
Off
Display
Burn-in protection (overlay drift)
Toggle
On
Display
Play audio
Toggle
Off
Advanced
Catalog URL
Text
raw streams.geojson on main
Advanced
Catalog refresh interval
Days
7
Advanced
Use inputstream.adaptive
Toggle
Off
Advanced
Enable YouTube cameras (v1.1)
Toggle, needs YouTube add-on
Off
Advanced
Data-saver (cap at 720p variant)
Toggle
Off
Advanced
Reset camera health / history
Action
—
The settings screen also exposes Preview (run the screensaver now) and a read-only line showing catalog date and pool size, e.g. "N cameras match your filters".
Catalog caching and camera health
The add-on never blocks activation on the network: it always starts from the last cached catalog and refreshes in the background.
Catalog cache
• First run: download streams.geojson from raw.githubusercontent.com (via urllib/xbmcvfs), parse, and write a slim index to the add-on profile folder (special://profile/addon_data/screensaver.livecams/): only the fields the selector needs, as compact JSON.
• Refresh: when older than the refresh interval, re-download using If-None-Match with the stored ETag. Validate the new file (parses, has more than 100 features) before swapping; on failure keep the old one.
• Ship a bundled snapshot of the slim index in the add-on so a first run with no network still works (only if the dataset's licence allows redistribution; see Licensing).
• Parse cost on a Raspberry Pi-class device must stay under 3 s; if the full GeoJSON is too slow, download the per-country data/ files instead or pre-filter in a background service on first run.
Health tracking (health.json)
• Each failure adds 1 to a camera's score and records the time; each successful 60 s of playback resets it.
• Score 1: skip for 1 hour. Score 2: skip for 24 hours. Score 3 or more: skip for 7 days, then retry once.
• If more than 50% of a single source_family fails within an hour, block that source for 6 hours (catches a provider-wide outage).
• A catalog refresh does not wipe health; entries for cameras no longer in the catalog are pruned.
History (history.json): last 200 cameras shown with timestamps, feeding the recency penalty; plus the user's favourites.
Error states shown on screen
Condition
What the viewer sees
No network at activation, no cache
Fallback card: dark background, clock, "Live cams unavailable" in small type, retried every 60 s
5 consecutive stream failures
Same fallback card for 60 s, then retry
Filters leave an empty pool
Filters relaxed silently (see Camera selection); if still empty, fallback card and a log entry
User's own media paused
Dim/black mode with clock only, no camera
Performance, bandwidth and platforms
A screensaver can run for hours unattended, so bandwidth is the main cost to manage: a typical 720p webcam HLS stream at roughly 2–4 Mbps uses about 0.9–1.8 GB per hour (estimate; to be measured on real feeds).
• Idle cut-off. Add a "Stop streaming after" setting (default 2 hours, options 30 min to never). After it, switch to the black/clock mode, which uses no network.
• Data-saver. When on, pick the lowest HLS variant at or above 720p; when using inputstream.adaptive, cap max resolution through its properties.
• Low-end hardware. Target Raspberry Pi 4/5 (LibreELEC), Android TV boxes, Fire TV, plus Windows, macOS and Linux desktops. Memory budget for the add-on's Python side: under 60 MB including the catalog index. No video decoding happens in Python; Kodi's player does it.
• Burn-in. The overlay drifts a few pixels every rotation and fades out; nothing static stays on screen longer than the dwell time. Matters for OLED TVs.
• Network politeness. One manifest probe per selection, no background prefetching of video, catalog download at most once per refresh interval. Set a descriptive User-Agent (add-on ID and version).
• Logging. Log at LOGINFO only for camera switches and failures; everything else at LOGDEBUG, so a 24-hour run does not bloat kodi.log.
Licensing, content and privacy
The add-on code can be GPL-2.0-or-later like most Kodi add-ons, but the dataset and the feeds it points to carry their own terms, which must be settled before public release.
• Dataset licence. The repository page shows no licence. Before bundling a snapshot or listing the add-on in the official Kodi repository, ask the maintainer for an explicit licence; until then, fetch the catalog at runtime only and credit the repo in the add-on description.
• Per-feed terms. sources.json records licence notes per source. Build a source allow list from it and exclude any source whose terms forbid embedding or redistribution.
• Attribution. The overlay shows the source name (from source_family) alongside the location, and the add-on's About text links to the dataset.
• Scraping. No HTML page scraping or token extraction in v1. SkylineWebcams support would need explicit permission or an official API.
• Privacy. Feeds are public outdoor cameras. The add-on records nothing, takes no snapshots and sends no telemetry; its only outbound requests are the catalog download and the streams themselves. A user-facing Report camera action (v1.1) adds a camera to the local block list, for anything showing people in a way the user isn't comfortable with.
Testing and acceptance criteria
v1 ships when every item below passes on a Android TV/Fire TV device and one desktop OS.
[ ] With a warm cache, first live frame within 5 s of activation for 9 of 10 activations.
[ ] Any remote key, mouse move or CEC input exits within 1 s, video stopped, no lingering audio.
[ ] With the user's own video paused, activation never stops or replaces it.
[ ] A dead URL, a 404 manifest and a stream that stalls mid-play are each skipped with no more than 15 s of black screen.
[ ] Unplugging the network mid-session shows the fallback card; reconnecting resumes cameras within 2 minutes.
[ ] 12-hour soak test: no crash, Python memory stays under 60 MB, kodi.log growth under 1 MB.
[ ] With "Prefer daylight" on, at least 90% of cameras shown are in day or twilight (checked against sun.py output in the log).
[ ] Idle cut-off switches to black/clock mode at the set time and makes no further stream requests.
[ ] Catalog refresh with a corrupted or truncated download keeps the previous catalog.
[ ] All strings come from strings.po; settings screen readable at 720p and 4K skins.
Automated tests (pytest, run outside Kodi with stubbed xbmc* modules): selector weighting and filter relaxation, solar elevation against reference values, health score transitions, catalog parsing against a pinned fixture of the GeoJSON.
Milestones and open questions
The riskiest assumption is that Kodi keeps the screensaver active while it drives xbmc.Player, so the first milestone is a throwaway spike that proves it.
1. Spike: screensaver window + one hard-coded HLS camera + exit on input + paused-media guard, on Pi and Android.
2. Core: catalog download and cache, selector with filters, HLS resolver with probe, start/stall detection, health list.
3. Polish: overlay with fades and drift, daylight weighting, settings screen, fallback card, idle cut-off.
4. Hardening: soak tests, acceptance checklist, translations scaffold, packaging for a personal Kodi repo.
5. v1.1: YouTube resolver (opt-in), favourites from the overlay, Report camera, "Follow the sun" rotation, optional weather badge (e.g. Open-Meteo by coordinates).
Open questions
[ ] Does the dataset maintainer grant a licence that allows bundling a snapshot and an official-repo listing?
[ ] How many cameras are in the default pool (active, HLS, no special handling, non-traffic)? Measure from the current streams.geojson.
[ ] Do HLS feeds from DOT sources need specific headers (Referer, User-Agent) to play in Kodi? Sample 20 per top source.
[ ] On Android TV, does starting playback from a screensaver trigger the system's own sleep/daydream handling?
[ ] Pin the catalog to a tagged release or commit for stability, or always follow main?
[ ] The README lists 4,229 "directly usable" streams in its header but about 2,929 from its recommended filter; confirm which definition applies.
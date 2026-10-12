# Couchstronomy — Kodi Screensaver Specification

Product requirements document · Version 1.0 · October 2026

## 1. Product vision

Couchstronomy turns your television into a real-time window onto the night sky.

The user configures the physical direction their TV faces, including its compass heading and vertical tilt. The screensaver then renders the exact corresponding patch of sky as it would appear outside a real window at that moment, from the user's observing location.

Stars drift naturally across the screen as Earth rotates. Planets move against the background stars. Satellites cross the field of view. Deep-sky objects, constellations, and other astronomical phenomena appear in their correct positions.

The result should feel like looking through a real window into space, rather than watching a planetarium animation or a generic starfield.

[Starry night sky Window view. Milky Way Galaxy.](https://images.openai.com/static-rsc-4/HXq_DyXT0zeQTl9GwhSbW6BcXCx9UuRxRI-BgUTKqTP-abS2bwBZdqHXzRqBPA2STHyZ4FcmiKwEGjI8X2BCWu6l5BW2FnUd8Bc2XsJLFW0-DJmfxTfZDywHOi_0bx-BPDXeEXi1AVufBfH-Fik4fJBUkxi6fdTGfX9y14vEbmA4NOxJaQYYWTU9evrXgDSs?purpose=inline)

[#99700: 同一夜の木星と土星（10月18日） by 山田昇 - 天体写真ギャラリー](https://images.openai.com/static-rsc-4/nH8m0X6sXTu29kGPW402tocAPA3ehFlLAKsyTdRMBIE29LbZOG_YktmYYnGE13Pbg9N08Mhvzbj-kEIR1GH75zfBgLgAWCAv6jqEB0AWeC_NVDI0NOhhbhcF2gmNQrW1EFTmC1SYMI3v-q9J2xcYSoivZu5gVxzvAHpQyiiStyQ?purpose=inline)

[Astrophotography in December 2024: what to shoot in the night sky this coming month | Digital Camera World](https://images.openai.com/static-rsc-4/iohDvDXiYNoN1rUiR2-7HFFnljJs7zog4SuI0hs7pArHYWDPRBMVZpsIE0ZCWd2e_VBSA2nDnKfdm2fR9Iz7VCFn0SHo3ZU0dii_iPOUSu3PRqH4dDxNxmG-HGeYuA1xlvN5l2HN_TDJaab7SlqgwUufFzRAzO7Aueg0nfrsOfg?purpose=inline)

9

### Core design principle

The television represents a fixed physical window onto the sky.

If a star would be visible through that window in real life, Couchstronomy should render it at the corresponding position. If an object is below the horizon, behind the window frame, or outside the screen's field of view, it should not appear.

The sky must be driven by astronomical calculations and real observation time, not by randomly generated star positions.

## 2. User experience

The ideal experience is:

1. Install Couchstronomy as a Kodi screensaver.
2. Enter the location where the TV is installed.
3. Point the TV's front face toward a compass heading, such as \\(180^\circ\\) (south).
4. Enter its vertical tilt, field of view, and optionally the TV's physical dimensions and viewing distance.
5. Start the screensaver.
6. See the sky that would actually be outside that window, updated continuously in real time.

Labels can be toggled on or off. With labels off, the experience should look like a natural, quiet night sky. With labels on, objects receive unobtrusive names and optional astronomical information.

## 3. Configuration and calibration

The add-on must expose a settings interface accessible through Kodi's normal add-on settings.

## Couchstronomy settings — proposed UI

Illustrative configuration layout

### Location

Latitude

Degrees north or south

44.9778° N

Longitude

Degrees east or west

93.2650° W

### TV orientation

Compass heading (azimuth)

### 180°

N · 0°

E · 90°

S · 180°

W · 270°

Vertical tilt

### 0°

Down

Level

Up

Horizontal field of view

### 60°

Narrow

Wide

Ultra-wide

Screen rotation

### 0°

0°90°180°270°

### Display options

Show object labels

Show constellation lines

Show satellites

Show Milky Way

Preview of saved orientation

## 180° azimuth · 0° tilt

Horizontal field of view: 60° · Rotation: 0°

Labels: Off · Satellites: On

Interactive concept mockup, not the actual Kodi settings screen. Example location coordinates are placeholders; the preview does not calculate astronomical positions.

### Required settings

| Setting                           | Requirement                                                                                     |
| --------------------------------- | ----------------------------------------------------------------------------------------------- |
| Observer latitude                 | Decimal degrees, north positive and south negative                                              |
| Observer longitude                | Decimal degrees, east positive and west negative                                                |
| Altitude                          | Optional elevation above sea level                                                              |
| Azimuth                           | Direction the TV faces, clockwise from true north                                               |
| Vertical tilt                     | Direction the screen points, from straight down to straight up                                  |
| Horizontal field of view          | Angular width of the visible sky                                                                |
| Vertical field of view            | Angular height, preferably calculated from the horizontal field of view and screen aspect ratio |
| Screen rotation                   | Correct mapping for rotated displays                                                            |
| Labels                            | Off, selected objects, or all supported objects                                                 |
| Object categories                 | Independent visibility toggles                                                                  |
| Time display                      | Optional local time and date                                                                    |
| Brightness and limiting magnitude | Adjust star visibility and rendering density                                                    |

### Important distinction: compass heading versus sky coordinates

Azimuth and elevation describe a direction in the local sky, whereas right ascension and declination describe celestial positions. Couchstronomy must transform between these coordinate systems using the observer's location and current time.

The user should not need to understand celestial coordinates to configure the screensaver.

### Orientation convention

- Azimuth \\(0^\circ\\): north.
- Azimuth \\(90^\circ\\): east.
- Azimuth \\(180^\circ\\): south.
- Azimuth \\(270^\circ\\): west.
- Elevation \\(0^\circ\\): horizontal.
- Elevation \\(+90^\circ\\): directly overhead.
- Elevation \\(-90^\circ\\): directly downward.

All azimuths should be normalized to \\(0^\circ\\)–\\(359.999\ldots^\circ\\). Internally, use true north rather than magnetic north. If the user supplies a compass reading, provide an optional magnetic declination correction.

For a typical wall-mounted television, vertical tilt is zero. A ceiling-mounted display can point upward, and a floor-facing or tilted display can use other angles.

## 4. The sky rendering engine

The rendering engine is the heart of Couchstronomy. It must produce a mathematically correct view of the sky, rather than place astronomical objects approximately on the screen.

### 4.1 Coordinate transformation

For every astronomical object:

1. Obtain its celestial coordinates and, where relevant, its distance, magnitude, angular size, and motion.
2. Calculate its apparent position for the observer and current time.
3. Convert that position to local azimuth and altitude.
4. Compare it with the TV's viewing direction and field of view.
5. Project the object onto the two-dimensional screen.
6. Render the object if it is in the visible portion of the sky.

A suitable camera model should support perspective projection, with an optional rectilinear or angular projection mode for particularly wide fields of view.

For the default perspective mode, define:

- \\(A\\): object azimuth.
- \\(h\\): object altitude.
- \\(A_0\\): TV azimuth.
- \\(h_0\\): TV elevation.
- \\(H\\): horizontal field of view.
- \\(V\\): vertical field of view.

Transform each object's local sky direction into a three-dimensional camera coordinate system whose forward axis is the TV's viewing direction. Then use the camera coordinates to compute the object's screen position.

The simplest implementation can use a rotation matrix or quaternion for the camera orientation. This avoids errors when the TV faces diagonally, tilts upward, or is rotated.

Acceptance criterion: An object on the centerline of the TV must appear at the center of the image. An object outside the configured field of view must not be drawn.

### 4.2 Time and astronomical motion

- Use UTC internally for all astronomical calculations.
- Use the actual current time, not the time Kodi started.
- Update object positions continuously, with a configurable update interval.
- Recalculate positions after resuming from a paused or suspended state.
- Handle daylight saving time only in local-time display, never in the underlying astronomical calculations.
- Account for precession, nutation, proper motion, and aberration where supported by the chosen astronomical library and precision target.
- Use appropriate ephemerides for the Moon, planets, and other moving solar-system bodies.

Stars should remain fixed relative to the celestial sphere over ordinary viewing intervals, while their screen positions change naturally as the sky moves.

### 4.3 Atmospheric and horizon effects

The renderer should distinguish between geometric visibility and realistic appearance.

- Do not display objects below the astronomical horizon in the default terrestrial-observer mode.
- Offer optional atmospheric extinction to make low-altitude objects appear dimmer.
- Account for atmospheric refraction near the horizon if supported.
- Provide an option for a realistic horizon or a transparent-looking sky that fades to black.
- Do not simulate clouds or weather by default unless a future feature explicitly adds a weather data source.

The screensaver should not assume that every geometrically above-horizon object is actually visible to the naked eye. Light pollution, clouds, atmospheric conditions, and the window itself can affect real visibility.

## 5. Astronomical objects and data sources

Couchstronomy should use real astronomical catalogs and live or regularly updated orbital data. No random stars, fabricated satellite trajectories, or invented celestial labels.

[ESO Supernova Exhibition — Wie sieht die Milchstraße aus?](https://images.openai.com/static-rsc-4/-5tjTrPD5kjqxF492gZ1GBQl94236hTvG8c6VKzrr5R3hRbhbditW_GBNC2u5bxrhFxEb4p8sfuzG0EzbuLbMspedXo6k5TPXh5YOJWLMlOVmr0kY_w3r3UAF60_De84QjuQFrPZ2K5aAbLYYthTSZmk1-XGqIgVED26QipH3no?purpose=inline)

Stars

- Star positions from a catalog such as Hipparcos or Gaia-derived data.
- Magnitudes, colors, proper motion, and identifiers where available.
- Configurable limiting magnitude to control the number of rendered stars.
- Optional spectral-color rendering and subtle twinkling.
- Optional double-star and variable-star designations.

[Astrophotographer’s Story: Mathieu Guinot – ZWO ASTRO USA](https://images.openai.com/static-rsc-4/O4G0oUs70XGFO1W4Ha125SEztv-Tb5VGi-hXNbMwQJ1FWIo63kRL4QWOJsBwYXGMQ4MbTKRlvZKODXvfoxr0qD0WqOZal3FCZ1t7qPtzkQ28R6GnT3eH26q5ClAEY_xE54r7ypHJG5u_bt-xa6EA4r_Q0NwCOSj7fVFebIxkstU?purpose=inline)

Solar-system objects

- Sun and Moon, with correct positions and apparent sizes.
- Mercury, Venus, Mars, Jupiter, and Saturn.
- Uranus and Neptune when the rendering configuration permits.
- Major natural satellites, dwarf planets, and selected asteroids and comets where suitable ephemerides are available.
- Lunar phases, planetary phases where relevant, and optional planetary disk detail.

[2020年10月31日ブルームーン（満月）など…全部肉眼で見える！2020年10月の天体ショーリスト](https://images.openai.com/static-rsc-4/NKiiXeyUGTJkz9HG8YG1a3XVCn3gy7kEx4wd4NAYK10OBC2c2sKeqBk_sESu94i3T1poDDIRBgOiDnpivyl2k2VAWkKaCArrQBM3vJHHifkXDSiK0TQJoXVO03oF1ImlAFLxSw0pFa1Z_1sMkQSpJiKWuugbRg6XAU4kOkFmn1A?purpose=inline)

Artificial satellites

- International Space Station.
- Other satellites with available orbital elements, including Starlink satellites.
- Optional labels, pass predictions, and approximate brightness.
- Correct movement across the screen based on time, orbit, and observer position.
- Support for refreshing orbital elements when an internet connection is available.

[Beehive Cluster — Location Tonight | Messier 44 | M44 Star Cluster — Astronomy | Praesepe](https://images.openai.com/static-rsc-4/j9qlzOonTVA_w0MXimB_NS805byUtw9n5p_AhNwEUYXOhUvBH3Vk5_p_emcRiuohXYpXkr962kqNGqgLv2Fa9JYPv7TfDJm7WS76oN1u5xBwA6xiRuOcZLphZr90eavQoZshnk3hP050zAZML-XAmUgavi3HCHiDsJ2Q2SGn3pw?purpose=inline)

Deep-sky objects

- Messier catalog.
- Selected NGC and IC catalog objects.
- Nebulae, galaxies, globular clusters, and open clusters.
- Optional angular-size rendering, icons, and object labels.
- Objects appear only when their positions fall within the screen's field of view.

[Ever heard of a ‘meteor storm’? Picture 40 shooting stars per second. - The Washington Post](https://images.openai.com/static-rsc-4/4ST5HHeKp-98a4vqHiEzw5lvPgkEIYrzw2wXL7iJu7Fe3dUxPGmq_K-8V4z1qWLhJsDZdD-L315DqyIa3hWn1s4yFAAufS6OCYZ2ZOUyYr1_dobw2tS-KHUApvAbpx-rlB0MCZp2iLNVMhI2tNgzPCBQkhA8M2IRsxHIfRXmqsM?purpose=inline)

Other astronomical phenomena

- Constellation boundaries and connecting lines.
- Meteor showers as an optional simulated ambient effect, clearly distinguished from live meteor detections.
- Comets, eclipses, and notable astronomical events where supported.
- Optional aurora data as a later enhancement, using real forecasts or observations when available.

### Recommended data sources

| Data                   | Suggested source or method                                                |
| ---------------------- | ------------------------------------------------------------------------- |
| Star catalogs          | ESA Gaia archive or Hipparcos catalog                                     |
| Solar-system positions | Skyfield-compatible ephemerides or another validated astronomical library |
| Satellite orbits       | CelesTrak GP/TLE data or another reputable orbital-element provider       |
| Deep-sky catalogs      | Messier, NGC, and IC catalogs                                             |
| Constellations         | A bundled, licensed constellation dataset                                 |
| Observer location      | User-entered coordinates; optional manual city selection                  |

Data providers and libraries must be checked for licensing, redistribution conditions, update policies, and compatibility with the target Kodi platform.

### What “all objects” means in practice

The application should support all objects in its configured catalogs that can be evaluated for the observer and time. It cannot guarantee every astronomical object that physically exists or every satellite currently in orbit.

The screensaver should gracefully handle missing data, stale satellite elements, unsupported objects, and network failures without crashing or displaying misleading positions.

## 6. Satellite accuracy and real-time updates

Satellites require special treatment because their positions change much faster than those of stars.

The add-on must:

- Download orbital elements when online.
- Cache valid orbital data locally.
- Calculate satellite positions using the observer's coordinates and current UTC time.
- Update satellite positions at a higher rate than the star background.
- Check orbital-element age and warn or suppress objects whose data is too stale for the configured accuracy threshold.
- Recalculate after a network outage or device resume.
- Distinguish a predicted satellite pass from a confirmed real-world observation.

A satellite's orbital elements can become less accurate over time. Therefore, the interface must never imply that a stale orbit gives an exact real-time position.

For the first release, a sensible default is to refresh orbital data periodically when online and calculate the displayed positions locally between refreshes.

## 7. Rendering and visual design

[Starry night sky with distant stars](https://images.openai.com/static-rsc-4/SUKBaJP8-AyKarOvfuLZ2KzLuaZsDSEUvEIDM_NCUg2GwQq_nFqn9Rl9ky3-rM2OiX9_Q8RHqFjhfAiKQd68htqmB68jKpAOEW6PD27o8HaVdYQ3smRDgGHNmMF-WaR08aa4du6z19Po7CpM2TcG7PFBJ2usqR3yXaf775LIfUuq4GPmWT6GA_rV8VqRDK1N?purpose=inline)

[Starry Night The Ultimate Desktop Planetarium  – Simulation Curriculum Corp.](https://images.openai.com/static-rsc-4/f-GMdoCslNaVJpd_FrQmc1aahUt-C1LQ8tW_fh5M5fuevvR9wZqox0ibCCT37zJQMKWluVV1-Nq_nhHxkvu3D8gH2i74ueWNFZTVrFKIE0MmvppObTFvIcJU-emaRCKMj2hUPkIIbzxybkMfG0KN95tjvJeIc_Xl1N_hLfrl954?purpose=inline)

[Tähtitieteellinen yhdistys Ursa: Havaintotehtävä kouluille: Planeetat ja aurinkokunnan ratataso](https://images.openai.com/static-rsc-4/oDCGlmnsx4exJbt7gHqExoRwIZdN3eRZNTjXnbHjle1kw9XsoG7I9SpQk3HG9h0d1jTYNOO_ZXYC2xvt9CwRM4QPW-uMUsPaP4gnfy0DXzHphTjkXQUZUEA9TMuHeH0EGRSRFufJ-0lBPAT3_vuQplZHlWXOrAGQIt9DquY_9vs?purpose=inline)

8

The screensaver should prioritize a convincing natural sky over a busy scientific interface.

### Visual requirements

- Black or very dark blue-black background.
- Stars rendered with brightness corresponding approximately to their apparent magnitude.
- Bright stars visibly larger than faint stars, with restrained glow.
- Correct relative angular positions and separation between objects.
- The Milky Way represented using a suitable bundled sky map or an approximation derived from astronomical data.
- Sun, Moon, and planets rendered with appropriate apparent sizes, while allowing a configurable visibility enhancement for usability.
- Deep-sky objects rendered as subtle extended features or icons when their angular size and brightness justify it.
- Smooth transitions and no sudden starfield resets when the time updates.

### Labels and overlays

All labels must be independently toggleable from the sky rendering itself.

Recommended modes:

1. Natural: no labels, no interface overlays.
2. Named objects: labels for bright stars, planets, the Moon, and selected satellites.
3. Explorer: labels, constellation lines, object types, and selected astronomical information.

Additional optional overlays:

- Local date and time.
- Compass direction at screen center.
- Altitude and azimuth of a selected object.
- Object name, magnitude, distance, and catalog designation.
- Satellite name and estimated pass information.

Labels should avoid overlapping important objects where practical. A label's presence must never cause an object to be repositioned.

### Realism versus visibility

Realism should be the default, but the user must be able to enhance faint stars and planets for a more attractive living-room display.

A configurable visual enhancement mode must be clearly distinguished from the physically representative mode. In particular, objects that would be too faint to see unaided should not be rendered at exaggerated brightness without the user enabling enhancement.

## 8. Kodi add-on architecture

Couchstronomy should be implemented as a native Kodi screensaver add-on, using Kodi's supported add-on interfaces rather than a separate application that must be launched manually.

### Recommended implementation

Kodi screensaver entry point

Lifecycle, configuration, activation and exit

Astronomy engine

Time, coordinates, ephemerides and projection

Data manager

Star catalogs, orbital elements and caches

Sky renderer

Stars, planets, satellites and labels

Settings and overlays

Calibration, display modes and user controls

### Technology choices

- Add-on interface: Kodi's screensaver add-on API and the interface supported by the target Kodi version.
- Primary language: Python for configuration, data management, and astronomical calculations.
- Rendering: Kodi-compatible graphics rendering. For a dense starfield, prefer batched GPU rendering where the target API allows it.
- Astronomy library: Evaluate Skyfield or PyEphem for coordinate calculations and ephemerides. Verify platform compatibility before committing to a dependency.
- Catalog storage: Local files or a compact indexed database for efficient loading.
- Network access: Optional; essential astronomical catalogs should be bundled or cached so the screensaver continues to work offline.

Important implementation decision: Kodi's supported screensaver interfaces and graphics capabilities vary by version and platform. Before implementing the renderer, verify the current Kodi add-on API, target Kodi releases, and whether a Python-based renderer can meet the performance target. If it cannot, use a supported GPU rendering path or a native rendering component rather than building the whole screensaver around a slow per-star Python drawing loop.

## 9. Performance and reliability

Couchstronomy should run continuously on a television-connected media device without noticeably increasing noise, power consumption, or system instability.

| Requirement            | Target                                                        |
| ---------------------- | ------------------------------------------------------------- |
| Frame rate             | 30 FPS minimum; 60 FPS preferred                              |
| Star updates           | Smooth apparent motion with no visible jumps                  |
| Satellite updates      | Approximately 1–5 times per second, configurable              |
| Planetary calculations | Efficient periodic updates                                    |
| Network outages        | No crash; cached data remains usable                          |
| Cold start             | Target under 5 seconds on reference hardware                  |
| Memory                 | Bounded catalog and texture caching                           |
| GPU usage              | Batched rendering and minimal unnecessary redraws             |
| Sleep/resume           | Recalculate from actual time and refresh relevant data        |
| Shutdown               | Release graphics resources and cancel background work cleanly |

These are proposed engineering targets and should be measured on representative hardware before being treated as guaranteed performance.

### Resource management

- Load catalogs lazily where practical.
- Precompute star properties that do not change frequently.
- Avoid downloading data during every frame.
- Separate network refreshes from the rendering loop.
- Suspend unnecessary work when the screensaver is inactive.
- Handle malformed catalogs, unavailable servers, and corrupted cache files gracefully.

## 10. Privacy and offline behavior

Couchstronomy should work without an account.

- Do not require user registration.
- Do not transmit viewing history or personal information.
- Use manually entered coordinates by default.
- Never require precise device location access.
- Make network-dependent features optional.
- Provide a clear way to disable automatic data updates.
- Explain that satellite orbital elements and other live datasets can become outdated when offline.

The location is essential for accurate sky calculations, but it can remain local to the device.

## 11. Testing and acceptance criteria

The following criteria define when the first production-ready release can be considered complete.

### Required acceptance tests

0 of 12 acceptance criteria checked

Reset

Orientation calibration

Changing azimuth from north to east rotates the view by the expected 90°.

Elevation calibration

Tilting the TV upward moves the camera's centerline toward higher-altitude sky.

Field-of-view boundaries

Objects outside the configured camera frustum are not rendered.

Astronomical time

Changing the simulated time changes object positions according to the correct time and location.

Fixed stars

Star positions agree with an independent astronomical reference within the selected accuracy tolerance.

Solar-system bodies

The Sun, Moon and planets appear at their calculated positions.

Satellite movement

Satellite positions are calculated from current orbital data and observer coordinates.

Horizon clipping

Below-horizon objects are hidden in normal terrestrial mode.

Label controls

Labels and constellation overlays can be independently enabled and disabled.

Offline operation

The screensaver continues running using cached or bundled data.

Resume behavior

Returning from sleep or suspension does not leave the sky frozen at an old time.

Kodi integration

The add-on starts and exits correctly on every supported target platform.

### Accuracy verification

Test the projection and ephemerides against a trusted planetarium program or astronomical reference for multiple locations, dates, and viewing directions.

At minimum, test:

- Northern and southern hemispheres.
- North-, south-, east-, and west-facing TVs.
- Horizontal and upward-tilted screens.
- Narrow and wide fields of view.
- Daytime and nighttime.
- Moonrise, moonset, and objects near the horizon.
- Satellite passes at multiple observation times.

The application must document its intended positional accuracy and distinguish errors in the astronomical calculations from uncertainty in the physical TV calibration.

## 12. Development roadmap

The project should be built incrementally, so the hardest technical risks are validated before adding large catalogs and visual effects.

Phase 1 — Minimum viable screensaver

- Create a valid Kodi screensaver add-on.
- Implement location, azimuth, elevation, and field-of-view settings.
- Render a catalog of stars at correct positions.
- Implement the coordinate transformation and time-dependent sky rotation.
- Validate orientation against a planetarium reference.

First milestone

Phase 2 — Solar system and deep sky

- Add the Sun, Moon, planets, and deep-sky catalogs.
- Add magnitude-based rendering and visual scaling.
- Implement labels and constellation overlays.
- Add realistic horizon clipping and optional atmospheric effects.

Phase 3 — Live satellites

- Integrate orbital-element updates.
- Calculate satellite trajectories for the observer.
- Implement caching, data-age checks, and offline operation.
- Add satellite labels and optional brightness estimates.

Phase 4 — Polish and release

- Optimize GPU rendering and memory use.
- Add natural, named-object, and explorer modes.
- Test Kodi installation, configuration, and exit behavior.
- Package the add-on, documentation, licensing notices, and test suite.

## 13. Explicitly out of scope for version 1.0

To keep the first release achievable, defer:

- Camera-based automatic TV orientation.
- Automatic location detection.
- Weather simulation and cloud forecasts.
- Live meteor detection.
- Telescope control and telescope-camera feeds.
- Photorealistic atmospheric scattering.
- A full interactive planetarium interface navigable with a remote.
- Guaranteed visibility of every known astronomical object.

These can be introduced after the core geometric projection and time-dependent sky calculations are verified.

## 14. Definition of done

Couchstronomy 1.0 is complete when a user can install the Kodi add-on, enter their location and the direction their television faces, and receive a continuously updated view of the corresponding real sky. Stars and supported astronomical objects must be positioned using actual astronomical data, labels must be independently toggleable, and satellite positions must use current or appropriately validated orbital information.

The defining feature is not simply that the screensaver looks like space. It is that the screen behaves like a calibrated window onto the real sky.
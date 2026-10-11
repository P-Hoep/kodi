# Project Specification: Kodi World Map Screensaver

Draft 1.0 · Functional requirements and technical acceptance criteria

## 1. Project overview

Develop a configurable world-map screensaver for Kodi that displays an animated, visually customizable representation of Earth. It should support multiple map projections, different geographic rendering styles, global weather overlays, and a real-time day/night visualization with city lights.

The application must prioritize smooth performance on recent Amazon Fire TV Stick devices while maintaining a flexible architecture that can accommodate different rendering modes and data sources.

The screensaver is intended primarily for ambient display on televisions, rather than interactive map navigation.

### Core objectives

- Render the world using multiple supported map projections, including unusual and interrupted projections.
- Support different base-map styles, including satellite imagery, conventional street maps, and other available map layers.
- Provide a Dwarf Fortress-inspired ASCII mode with both geographic characters and image-to-ASCII shading.
- Display configurable global weather overlays.
- Show the moving day/night boundary and nighttime city lights.
- Provide extensive controls for movement, zoom, projection cycling, and visual styles.
- Run smoothly on Fire TV Stick hardware, targeting 60 FPS where feasible.
- Continue displaying cached map data during network interruptions.

## 2. Scope and platform

| Requirement          | Specification                                                               |
| -------------------- | --------------------------------------------------------------------------- |
| Host application     | Kodi screensaver                                                            |
| Primary device       | Recent Amazon Fire TV Stick models                                          |
| Rendering target     | 60 FPS where hardware permits                                               |
| Operating conditions | Online, intermittent connectivity, and cached-data fallback                 |
| Primary interface    | Kodi-compatible settings                                                    |
| Display orientation  | Landscape television displays                                               |
| Interaction model    | Configured before activation; ambient playback during screensaver operation |

The application should respect Kodi's lifecycle, including activation, deactivation, and return to normal playback. It should not require ongoing user interaction once the screensaver starts.

## 3. Map rendering and projections

### 3.1 Base-map rendering

The screensaver must support the base-map layers available to the application, including satellite imagery, OpenStreetMap-style cartography, and other supported map sources.

Users must be able to configure the base-map appearance independently of the selected projection and overlays.

The renderer must accommodate both continuous rectangular maps and projections with interrupted or nonrectangular layouts.

### 3.2 Required projections

The following projection list is the proposed baseline for implementation.

1

Mercator

2

Robinson

3

Dymaxion

4

Gall–Peters

5

Equal Earth

6

Sinu-Mollweide

7

Goode’s Homolosine

8

Cylindrical Equal Area

9

Peirce Quincuncial

10

Winkel Tripel

11

Waterman Butterfly

12

Orthographic globe

Three-dimensional spherical view

The implementation must treat each projection as a supported rendering mode, not merely as a pre-rendered image.

### 3.3 Projection requirements

- Users can select a projection manually.
- Automatic projection cycling can be enabled or disabled.
- Every projection must support the overlays applicable to that rendering mode.
- Changing projections must preserve overlay alignment and geographic positioning.
- Interrupted projections must respect their geographic cuts and layout.
- The globe view must support rotation and appropriate zoom behavior.
- Projections that cannot support a particular transformation or visual effect must fail gracefully rather than displaying misaligned data.

Weather data and day/night geometry must be transformed consistently with the active projection.

## 4. ASCII rendering modes

The screensaver must provide a dedicated ASCII rendering mode inspired by the geographic visual language of Dwarf Fortress.

ASCII rendering is a first-class rendering mode, not a static filter or separate screensaver.

### 4.1 Geographic ASCII mode

Render geographic information using characters selected to represent the underlying features.

Examples of potential character mappings:

| Feature               | Example characters |
| --------------------- | ------------------ |
| Ocean and water       | `~`, `≈`, `≋`      |
| Plains and grassland  | `.`, `,`, `"`      |
| Forest                | `♣`, `T`, `♠`      |
| Mountains             | `^`, `▲`, `∧`      |
| Snow and ice          | `*`, `:`, `░`      |
| Urban areas           | `#`, `▓`, `+`      |
| Geographic boundaries | `-`, `\\|`, `+`    |

These are illustrative mappings, not mandatory character assignments. The renderer should allow appropriate mappings for the features available in each base-map layer.

### 4.2 Image-to-ASCII mode

Provide an alternative rendering mode that converts the visible base-map imagery into characters based on image characteristics such as brightness and color.

This mode should support satellite imagery and other image-based map layers, where feasible.

### 4.3 Color and palette settings

Users must be able to choose between:

- Monochrome ASCII.
- Colored ASCII.
- Configurable color palettes for colored rendering.

Palette choices should be independent of the underlying geographic data. Weather overlays and nighttime lighting should remain distinguishable from terrain characters.

### 4.4 ASCII settings

The settings interface should expose, where supported:

- ASCII rendering mode: geographic, image-to-ASCII, or automatic.
- Character density and output resolution.
- Character palette.
- Color palette or monochrome output.
- Brightness-to-character mapping for image-to-ASCII.
- Optional display of geographic boundaries and urban features.

The ASCII renderer must operate within the same projection and animation system as the normal map renderer.

## 5. Global weather overlays

### 5.1 Required overlays

The application must provide independently configurable overlays for the following weather categories.

[The continents and oceans with clouds photo – Free Earth Image on Unsplash](https://images.openai.com/static-rsc-4/wBwg0Kds3uuGLLu6qxLd7kJGO1beWz6I7WGsLUStix2iHRk384JX3X-cdpKu-EcXSxpMkFCqFH1SzKHrCKW4rNJL2gTKA4fYuJjHISDjrhTS89Y8YQvUdgJ6SRsVbeUdFPNZv_eLnAFBOGFOzg0pTX2Pqu1HWNA7y-7PsgPDkXM?purpose=inline)

Cloud cover

Display global cloud distribution over the base map.

[NASA Satellite Captures Amazing 3D Videos of Rain, Snow | Live Science](https://images.openai.com/static-rsc-4/g73CUQZJG4Jie0kYUtL8yMu6rkBGyUFVcEd8QdXIlRdxhKdw6h73wz8DwhvctqLSKHFZJ5QibFaQ4ffSXK_2qvjSFT4hI5U958p3xYIRLuRiXGOcDDS1Qd3fOwaXkEmsTlGdlrUaDER4FcIRNAL_G833sQI_79EMsMPVR4BXypU?purpose=inline)

Precipitation

Visualize the geographic distribution and intensity of precipitation.

[Rising Water Temperatures in the Gulf of Mexico: A Looming Threat of Mega-Hurricanes for Americans | The Voss Law Firm, P.C.](https://images.openai.com/static-rsc-4/ZLdE9ntgbG_hjW5aNlGWvCm4MBsSADm4X4Q1gK65CPd830gqnlgh4TVxbqR7LU46g2fbeGh3Znl5TYSP8sIv4QekOOK71eADpjzBZi-T_f2sDETJdX5XPZPqSkAIM7_DKccixsC5aXGrpth0oCP-U04vz6dLfwSS-xORwTGSrno?purpose=inline)

Temperature

Show spatial temperature variation using a distinguishable visual scale.

[Modeling Future Climate -  			NYU Abu Dhabi](https://images.openai.com/static-rsc-4/HAF9OtRDZrVjcJoJujBO3A-hP3-GaN2UD2f7IZJfwG4SYbr5AGs2bi7lEuxmQf8hAU6eX_BmBe31tbCj67lUTHUdFiMP2_3atcM3B9Xx_XtYd-JYwRC1AbWX0gV96wy_wyi4zXOjAVtJg_xviPkMTSsoiIbrlodi9DL74eyUy3A?purpose=inline)

Wind

Visualize wind speed and direction, using motion or directional symbols where practical.

Storms

Show available storm-system information and associated geographic features.

These illustrations communicate the intended visual categories; they do not specify or require particular data providers.

### 5.2 Overlay behavior

- Each weather overlay can be enabled or disabled independently.
- Multiple weather overlays can be displayed simultaneously, subject to performance constraints.
- Users can adjust overlay opacity or intensity where applicable.
- The base map must remain legible when overlays are active.
- Weather overlays must align with the underlying geography.
- Weather rendering must support all required projections, including the globe view and interrupted projections.
- Weather rendering must work in both conventional and ASCII modes, using appropriate visual representations for each.
- Weather information should be refreshed when new data is available.
- Cached weather information may be displayed during connectivity interruptions, with its age indicated where practical.

The application must not imply that cached weather is current when it is not.

## 6. Day/night visualization and city lights

### 6.1 Day/night layer

Provide an optional global day/night overlay representing the illuminated daytime hemisphere and the nighttime hemisphere.

The day/night boundary must update over time to reflect the Earth's rotation relative to the Sun.

The implementation should account for the active map projection so that the terminator is correctly positioned in rectangular, interrupted, and globe views.

### 6.2 City lights

Provide a separate city-light visualization that depicts nighttime artificial illumination.

The following behaviors must be configurable:

- City lights visible on the nighttime side only.
- City lights displayed independently of the day/night mask.

### 6.3 Day/night settings

Users should be able to:

- Enable or disable the day/night layer.
- Enable or disable city lights.
- Choose whether city lights follow the night mask.
- Adjust the intensity of the day/night shading.
- Adjust city-light brightness.
- Retain the selected behavior when projections or base-map styles change.

### 6.4 ASCII compatibility

The day/night layer must work in both ASCII rendering modes. It may use character density, palette changes, or other appropriate terminal-style shading to distinguish day and night.

City lights should remain visually identifiable without making the map unreadable.

## 7. Movement, camera, and automatic cycling

All movement and cycling behavior must be configurable through the screensaver settings.

### 7.1 Movement modes

The application must support:

- Static display.
- Panning across the map.
- Rotation of the globe.
- Automatic movement.
- Zooming.
- Automatic cycling through projections and visual styles.

Movement options must be compatible with the active projection. For example, a globe can rotate as a sphere, while a flat map can pan across its projected surface.

### 7.2 Advanced controls

| Setting              | Required behavior                                                  |
| -------------------- | ------------------------------------------------------------------ |
| Movement mode        | Select static, pan, rotate, or automatic movement                  |
| Movement speed       | Adjust the speed of movement                                       |
| Rotation direction   | Configure the direction of globe rotation                          |
| Pan behavior         | Configure direction and movement behavior                          |
| Zoom                 | Configure zoom level and, where practical, automatic zoom behavior |
| Projection cycling   | Enable or disable automatic projection changes                     |
| Style cycling        | Enable or disable automatic visual-style changes                   |
| Cycling interval     | Configure the time between changes                                 |
| Randomized sequences | Enable or disable randomized projection and style selection        |
| Fixed sequences      | Allow repeatable cycling through a defined sequence                |

### 7.3 Cycling behavior

- Users must be able to disable all automatic cycling.
- Projection and style cycling must be independently configurable.
- Randomized cycling must avoid unnecessary rapid repetition where practical.
- Changing a projection must not reset unrelated user preferences.
- Transition effects should be configurable or kept simple enough to protect performance.
- Cycling should not cause repeated full-resolution downloads or unnecessary reconstruction of unchanged map data.

## 8. Fire TV Stick performance requirements

The primary performance objective is smooth, stable rendering on recent Fire TV Stick models.

### 8.1 Performance targets

| Metric               | Requirement                                                         |
| -------------------- | ------------------------------------------------------------------- |
| Preferred frame rate | 60 FPS where hardware permits                                       |
| Fallback behavior    | Reduce rendering workload when 60 FPS cannot be maintained          |
| Animation            | Avoid visible stuttering and irregular motion                       |
| Memory               | Bound memory usage and prevent unbounded growth                     |
| CPU/GPU load         | Avoid unnecessary work during static periods                        |
| Network usage        | Avoid repeated downloads of unchanged resources                     |
| Thermal stability    | Avoid sustained workloads that cause severe performance degradation |

The implementation should not assume that every supported device can sustain 60 FPS with every combination of high-resolution imagery, weather overlays, ASCII rendering, and animation.

### 8.2 Adaptive rendering

The renderer should be able to reduce workload when necessary, prioritizing:

1. Stable animation and responsiveness.
2. Correct geographic alignment.
3. Legibility of the base map and overlays.
4. Visual detail and rendering resolution.

Possible optimizations include lower-resolution intermediate textures, cached projection transforms, reuse of unchanged map tiles, and reduced overlay update frequency.

The implementation should use hardware-appropriate rendering paths and avoid expensive per-frame operations when their results can be reused.

### 8.3 Performance acceptance criteria

- On a designated recent Fire TV Stick reference device, the application should sustain approximately 60 FPS in a defined baseline scene when hardware permits.
- When the full rendering workload exceeds the device budget, the renderer should degrade gracefully rather than entering persistent severe stuttering.
- Static scenes should not continuously perform expensive redraws or unnecessary data processing.
- Extended operation should not exhibit steadily increasing memory usage.
- Projection changes and overlay toggles should not cause crashes or persistent rendering stalls.

Benchmark requirement: performance testing must document the reference device, screen resolution, active overlays, map detail, ASCII mode, and movement configuration. The precise fallback frame-rate threshold and startup-time target should be established during implementation testing.

## 9. Settings and configuration

Settings should be organized into clear categories so users can configure the screensaver without navigating a long, unstructured list.

| Category         | Settings                                                          |
| ---------------- | ----------------------------------------------------------------- |
| Base map         | Available map layer, map appearance                               |
| Projection       | Projection selection, automatic cycling                           |
| Movement         | Mode, speed, direction, pan behavior, zoom                        |
| Cycling          | Enablement, interval, fixed or randomized sequence                |
| Rendering style  | Conventional map, geographic ASCII, image-to-ASCII                |
| ASCII appearance | Monochrome, colored, palette, character density                   |
| Weather          | Independent toggles for each supported weather overlay            |
| Day/night        | Enablement, shading intensity                                     |
| City lights      | Enablement, brightness, nighttime-only behavior                   |
| Performance      | Rendering quality and adaptive performance options, where exposed |
| Data and cache   | Cache behavior, refresh preferences, stale-data handling          |

The settings interface should be suitable for remote-control navigation, with readable labels and sensible defaults.

Settings must persist across screensaver sessions and Kodi restarts wherever Kodi's configuration system permits.

## 10. Caching and network resilience

The screensaver must remain visually usable when internet connectivity is interrupted.

### Requirements

- Reuse cached map tiles, imagery, and other previously obtained map resources.
- Continue rendering with available cached data when the network becomes unavailable.
- Continue displaying cached weather overlays when possible.
- Avoid blocking the animation loop while waiting for network requests.
- Refresh stale resources when connectivity returns.
- Avoid repeatedly requesting unavailable resources in rapid succession.
- Handle missing tiles and incomplete weather data gracefully.
- Keep the last usable visual state available while replacement data loads.

Cached content should be treated as a performance optimization and resilience mechanism, not a guarantee that the entire world is available offline.

A complete offline mode with a full local world map is not a requirement of this draft.

## 11. Reliability and lifecycle

The application must:

- Start and stop cleanly in response to Kodi's screensaver lifecycle.
- Release graphics resources, network tasks, and other resources when stopped.
- Avoid retaining unnecessary high-resolution map textures in memory.
- Recover gracefully from failed downloads and incomplete data.
- Handle projection changes and overlay toggles without crashing.
- Preserve settings when the screensaver is restarted.
- Avoid displaying invalid, corrupted, or visibly misaligned overlays when data is missing.
- Continue animating independently of network latency.

## 12. Functional acceptance checklist

The project is ready for release when the following requirements have been verified.

### Release verification checklist

0/22

Map and projections

All 12 proposed projections can be selected and rendered.

The orthographic globe supports rotation and zoom.

Base-map layers remain geographically aligned when projections change.

Interrupted projections render with their intended layouts.

ASCII rendering

Geographic ASCII mode represents available geographic features with characters.

Image-to-ASCII mode converts supported imagery into character shading.

Monochrome and colored palettes are selectable.

ASCII rendering works with movement, projections, and compatible overlays.

Weather and lighting

All five required weather overlays can be enabled independently.

Multiple overlays can be combined.

Weather overlays remain geographically aligned across projections.

Day/night shading updates over time.

City lights support both nighttime-only and independent display modes.

Controls

Movement mode, speed, direction, pan, and zoom can be configured.

Projection and style cycling can be independently controlled.

Cycling intervals and randomized sequences work as configured.

Settings persist across restarts.

Performance and resilience

The reference-device performance test documents FPS and workload.

The renderer targets 60 FPS where feasible and degrades gracefully.

Cached map data remains usable during network interruptions.

Network delays do not block rendering.

Long-running tests show no unbounded memory growth.

Copy checklistReset

## 13. Explicitly out of scope for this specification

To keep the spec focused on product behavior rather than prematurely constraining implementation, it does not prescribe:

- Specific map providers, tile services, or weather APIs.
- Particular rendering libraries or graphics APIs.
- Individual projection algorithms or mathematical implementation details.
- A particular city-light dataset.
- A complete downloadable offline atlas.
- Exact hardware-independent memory, CPU, or GPU budgets.

The application is assumed to already know which base-map layers and weather services are available. The specification requires those sources to integrate with the rendering and overlay systems, without redefining the provider configuration.

## 14. Recommended implementation priorities

1. Foundation: Establish the Kodi screensaver lifecycle, base-map renderer, caching system, and performance instrumentation.
2. Projection engine: Implement the required projections and globe view, with a consistent geographic coordinate pipeline.
3. Overlays: Integrate weather, day/night shading, and city lights through a common projection-aware overlay system.
4. Visual modes: Add geographic ASCII, image-to-ASCII, color palettes, and their overlay rendering paths.
5. Animation and controls: Implement advanced movement, zoom, cycling, and randomized sequences.
6. Optimization and release testing: Profile representative scenes on the target Fire TV Stick devices, improve bottlenecks, and validate the acceptance checklist.

## 15. Key architectural requirement

The most important technical decision is to keep geographic data, projection transforms, rendering styles, and overlays logically separate.

That separation allows the same weather data or day/night geometry to be rendered as a conventional map, a globe, or ASCII characters without implementing an entirely different geographic system for each visual style.

It also makes the project easier to extend with new projections, rendering modes, and available data sources in the future.

Status: This is a complete first-draft functional specification. The remaining engineering decisions—such as the exact rendering technology, reference-device benchmark, fallback frame-rate threshold, and individual projection implementation strategies—can be finalized during technical design.
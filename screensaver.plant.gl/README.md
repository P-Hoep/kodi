# Growing Plant (OpenGL)

A Kodi screensaver in which a single procedural plant grows from a seed, sways in the wind and then
holds while the camera moves around it. Each cycle is a new plant from the TwoOL plant / L-system
core in this repository: a tree, bush, fern, fan-leaf plant, or a glowing 2D L-system pattern.

Built for Kodi's native screensaver API, which draws with **OpenGL, not WebGL** — a Kodi binary
add-on is a compiled shared library and there is no browser engine or WebGL context inside Kodi.
The renderer is written once in GLSL 1.20 style and compiled as:

| Where | Context | Shader dialect |
|---|---|---|
| Kodi on macOS | OpenGL 3.2 core | GLSL 1.50 (`#version 150`) |
| Kodi on Linux (desktop GL) | OpenGL 3.2 core | GLSL 1.50 |
| Kodi on Android | OpenGL ES 2.0 | GLSL ES 1.00 |
| Test window (non-core) | GL 2.1 compatibility | GLSL 1.20 |

## How the growth works

The plant is generated once per cycle by `twol::generate_node_graph()` (a node/branch graph with
birth and growth windows), then turned into one static triangle mesh by `build_growth_mesh()`. Every
vertex carries its final `position`, the `anchor` it grows out of, a `birth` time and a `span`.

The vertex shader does the rest:

```glsl
float g = smoothstep(a_growth.x, a_growth.x + a_growth.y, u_time01);
vec3 p = mix(a_anchor, a_pos, g);          // stem pixels slide out of the parent branch
p += wind_sway(a_sway, u_time) * g;        // leaves only move once they exist
```

So growth costs nothing per frame: one VAO and two buffers per batch, drawn with
`glDrawElements`. Birth/end times are normalized after generation so the last leaf always finishes
exactly at `time01 = 1`, and sapling geometry that predates the cycle is simply already grown.

Each cycle: fade in (1.6 s) → grow (11-36 s, depending on the setting) → hold (default 14 s) →
fade out (1.6 s) → a new seed, plant, background and camera move.

## Files

| Part | File | Kodi / GL needed |
|---|---|---|
| Node graph, L-system, presets, math (vendored from `../plant`) | `src/twol/` | no |
| Growth mesh: branches as tubes, leaves as tapered ribbons with a midrib | `src/plant_growth.hpp`, `src/plant_growth.cpp` | no |
| Renderer: growth shader, procedural skies, ground, pollen, camera | `src/plant_app.hpp`, `src/plant_app.cpp` | GL 2.1 / GL 3.2 core / GLES 2.0 |
| GLSL dialect prefixes, compilation, GL state save/restore | `src/gl_util.hpp`, `src/gl_include.hpp` | — |
| Kodi add-on wrapper (`CInstanceScreensaver`, settings, entry point) | `src/kodi_plant.cpp` | kodi-addon-dev-kit |
| Test window (`plant_glfw`, and `plant_glfw_core` for the macOS core profile) | `src/main_plant_glfw.cpp` | GLFW |
| Tests | `tests/test_plant_growth.cpp` | no |

The settings table lives in `tools/make_settings_plant_gl.py`, which writes `resources/settings.xml`
and the strings, so the Kodi UI and `kodi_plant.cpp` cannot disagree about what option 2 means. Run
it again after changing the table:

```sh
python3 tools/make_settings_plant_gl.py
python3 tools/make_settings_plant_gl.py screensaver.plant.gl.armv7 'Growing Plant (OpenGL, 32-bit Android)'
```

## Settings

| Category | Setting | Default | Meaning |
|---|---|---|---|
| Plant | Plant | Automatic | Automatic / Tree / Bush / Fern-vine / Fan-leaf / L-system pattern |
| Plant | Seed | 0 | 0 gives a new plant every start; 1-999 always gives the same plant |
| Plant | Leaf density | Normal | Sparse / Normal / Lush (scales leaf nodes per branch) |
| Plant | How long a plant takes to grow | Normal (25 s) | 36 / 25 / 17 / 11 seconds |
| Plant | Hold | 14 s | How long the finished plant stays before the next cycle |
| Camera | Camera movement | Automatic | Automatic / Orbit / Sway / Spiral / Crane / Still |
| Camera | Camera speed | 100% | 10-200%, scales the movement |
| Camera | Framing | Normal | Normal / Close / Wide |
| Scene | Background | Automatic | Automatic / Dawn / Meadow / Dusk / Night / Studio / Aurora |
| Scene | Ground and contact shadow | on | Ground disc, light pool, contact shadow |
| Scene | Drifting pollen | on | Small additive motes around the plant |
| Display | Detail | Normal | Low for slow boxes / Normal / High (generations, segments, leaf density) |
| Display | Dim the picture | 0% | Darkens the output, 0-80% |

Automatic mode rotates plant, background and camera move independently, so consecutive cycles do
not repeat together. Studio is reserved for the L-system pattern (it has no ground), and automatic
mode only pairs the pattern with the dark skies.

## Build and test

```sh
cmake -S . -B build -DPLANT_HARNESS=OFF && cmake --build build && ctest --test-dir build
```

Test window (needs GLFW: `brew install glfw`; the core-profile variant is built on macOS too):

```sh
cmake -S . -B build && cmake --build build
./build/plant_glfw      --preset 1 --background 1 --motion 1 --seed 42
./build/plant_glfw_core --preset 1 --background 1 --motion 1 --seed 42   # what Kodi uses on macOS
```

The harness takes `--preset --seed --quality --leaf-density --growth-speed --hold --motion
--camera-speed --framing --background --no-particles --no-ground --dim --width --height-px
--fullscreen --start-at SECONDS --run-for SECONDS --shot out.ppm --shot-after SECONDS` and prints
the GL version, mesh counts and fps.

## Kodi add-on

Built against the Kodi 21 "Omega" dev kit (screensaver API 2.2.0). Get the headers once:

```sh
git clone --depth 1 --branch 21.1-Omega https://github.com/xbmc/xbmc.git   # or a sparse checkout of xbmc/addons/kodi-dev-kit/include
cmake -S . -B build-kodi -DPLANT_HARNESS=OFF -DPLANT_KODI=ON \
  -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include
cmake --build build-kodi
```

macOS universal library (Intel + Apple Silicon), built in `build-macos-x86_64` and
`build-macos-arm64`, then lipo'd and ad-hoc signed:

```sh
cmake -S . -B build-macos-x86_64 -DCMAKE_OSX_ARCHITECTURES=x86_64 -DPLANT_HARNESS=OFF -DPLANT_KODI=ON -DKODI_DEVKIT_INCLUDE=<...>
cmake --build build-macos-x86_64
cmake -S . -B build-macos-arm64 -DCMAKE_OSX_ARCHITECTURES=arm64 -DPLANT_HARNESS=OFF -DPLANT_KODI=ON -DKODI_DEVKIT_INCLUDE=<...>
cmake --build build-macos-arm64
lipo -create -output screensaver.plant.gl.dylib \
  build-macos-x86_64/screensaver.plant.gl.dylib build-macos-arm64/screensaver.plant.gl.dylib
codesign --force --sign - screensaver.plant.gl.dylib
```

Android (needs the NDK: `brew install --cask android-ndk`):

```sh
cmake -S . -B build-android -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static \
  -DPLANT_HARNESS=OFF -DPLANT_KODI=ON -DKODI_DEVKIT_INCLUDE=<...>
cmake --build build-android
```

`tools/make_repo.py` publishes anything with an `addon.xml`, so the built
`screensaver.plant.gl.dylib` and `.so` are committed next to it.

## Shader dialects and gotchas

- Kodi on macOS uses a **3.2 core** context: no fixed-function state, a VAO is required, and
  `attribute`/`varying`/`gl_FragColor` are aliased to `in`/`out`/`pl_fragColor` by the prefixes in
  `glu::version_*`. The harness has `plant_glfw_core`, which requests the same context, so shader
  errors show up without installing into Kodi.
- GLES 2.0 has no VAOs, no `GL_PROGRAM_POINT_SIZE`, only 16-bit indices and no
  `glBlendFuncSeparate`; all four are guarded. A mesh batch is capped at 60000 vertices so every
  index fits in a `uint16_t`.
- `glu::SavedState` restores the FBO, viewport, program, buffers (including the element buffer),
  blend state, enables, depth-write mask and clear colour. Leaving culling, the depth test or a
  depth mask behind made Kodi's GUI lose its images after a screensaver exited, so this is the
  part to extend carefully if more GL state is ever touched.
- The renderer never assumes it owns the context: `Start`/`Render`/`Stop` happen with Kodi's
  context current, and `Stop` deletes the buffers there rather than in the destructor.

## Testing in a local Kodi

```sh
export KODI_ADDON=screensaver.plant.gl
python3 tools/kodi.py install
python3 tools/kodi.py select
python3 tools/kodi.py run
python3 tools/kodi.py shot /tmp/plant.png
python3 tools/kodi.py log
```

Settings can be changed live with `python3 tools/kodi.py set background=6 quality=2`; take the
screenshot with Kodi's own `TakeScreenshot`, which keeps the screensaver rendering (screen
recording does not).

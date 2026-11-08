# Endless World (OpenGL)

A Kodi screensaver that flies a camera over an endless, procedurally generated landscape, drawn
with OpenGL. It is a port of [infworld](https://github.com/NULLPTR-ERROR/infworld) by Jeremy Li
"Nullptr Error" (MIT).

Mountains, green hills, sandy beaches, lakes and seas, pine and broadleaf forests, and a sky with
drifting clouds. Nothing is loaded from disk except the textures: the height of every hill and the
position of every tree come from the seed when a chunk comes into view. The world is drawn in five
levels of detail around the camera, so it never ends and the near ground stays detailed.

| Part | File | Kodi / GL needed |
|---|---|---|
| World model: noise, chunks, LOD table, trees, camera (port of infworld's `infworld.cpp`) | `src/infworld.hpp`, `src/infworld.cpp` | no |
| Renderer: shaders, palette textures, water, skybox, adaptive quality | `src/infworld_app.hpp`, `src/infworld_app.cpp` | GL 2.1 / GL 3.2 core / GLES 2.0 |
| Kodi add-on wrapper (`CInstanceScreensaver`, settings, entry point) | `src/kodi_infworld.cpp` | kodi-addon-dev-kit |
| Test window (`infworld_glfw`, and `infworld_glfw_core` for the macOS core profile) | `src/main_infworld_glfw.cpp` | GLFW |
| Tests | `tests/test_infworld.cpp` | no |

The settings table lives in `tools/make_settings_infworld.py`, which writes `resources/settings.xml`
and the strings, so the Kodi UI and `kodi_infworld.cpp` cannot disagree about what option 2 means.
Run it again after changing the table:

```sh
python3 tools/make_settings_infworld.py
python3 tools/make_settings_infworld.py screensaver.infworld.gl.armv7 'Endless World (OpenGL, 32-bit Android)'
```

## Settings

| Category | Setting | Default | Meaning |
|---|---|---|---|
| World | Seed | 0 | 0 gives a new world every start; 1-999 always gives the same world |
| World | How far to draw | 6 | Chunks per LOD ring (3-9): more world, slower |
| World | Terrain and tree detail | Medium | Low / Medium / High mesh precision |
| World | Trees | Normal | None / Sparse / Normal / Lush |
| Camera | Flight | Glide | Glide (wandering), Circle (steady turn), Drift (very slow, calm) |
| Camera | Speed | 45 | World units per second, 10-200 |
| Camera | Height | 90 | Metres above the ground, 20-400 |
| Camera | Look around as it flies | on | Gentle yaw so the view is not a straight line |
| Scene | Draw the sea and lakes | on | The water plane and its shader |
| Display | Dim the picture | 0% | Darkens the output, 0-80% |
| Display | Render resolution | Automatic (up to 1440p) | Full / up to 1080p / 720p / 540p |
| Display | Lower the detail when the frame rate drops | on | Adaptive quality: drops LOD detail when slow |

The render resolution and adaptive quality are the two settings to reach for on a weak box: the
terrain is fill-rate heavy at 4K, and the two together keep an old set-top box smooth.

## Build and test

```sh
cmake -S . -B build -DSANDCLOCK_HARNESS=OFF && cmake --build build && ctest --test-dir build
```

Test window (needs GLFW: `brew install glfw`; the core-profile variant is built on macOS too):

```sh
cmake -S . -B build && cmake --build build
./build/infworld_glfw      --assets resources/textures --seed 2
./build/infworld_glfw_core --assets resources/textures --seed 2   # what Kodi uses on macOS
```

The harness takes `--seed --range --detail --trees --mode --speed --height --no-wander --no-water
--dim --draw-res --no-adaptive --assets --fullscreen --width --height-px --shot out.ppm
--shot-after SECONDS` and prints fps, chunk and tree counts, per-LOD draw counts and the camera
position once a second.

## Kodi add-on

Built against the Kodi 21 "Omega" dev kit (screensaver API 2.2.0). Get the headers once:

```sh
git clone --depth 1 --branch 21.1-Omega https://github.com/xbmc/xbmc.git   # or a sparse checkout of xbmc/addons/kodi-dev-kit/include
cmake -S . -B build -DSANDCLOCK_HARNESS=OFF -DSANDCLOCK_KODI=ON \
  -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include
cmake --build build
```

macOS universal library (Intel + Apple Silicon), built here in `build-macos-x86_64` and
`build-macos-arm64`, then lipo'd and ad-hoc signed:

```sh
cmake -S . -B build-macos-x86_64 -DCMAKE_OSX_ARCHITECTURES=x86_64 -DSANDCLOCK_HARNESS=OFF -DSANDCLOCK_KODI=ON -DKODI_DEVKIT_INCLUDE=<...>
cmake --build build-macos-x86_64
cmake -S . -B build-macos-arm64 -DCMAKE_OSX_ARCHITECTURES=arm64 -DSANDCLOCK_HARNESS=OFF -DSANDCLOCK_KODI=ON -DKODI_DEVKIT_INCLUDE=<...>
cmake --build build-macos-arm64
lipo -create -output screensaver.infworld.gl.dylib \
  build-macos-x86_64/screensaver.infworld.gl.dylib build-macos-arm64/screensaver.infworld.gl.dylib
codesign --force --sign - screensaver.infworld.gl.dylib
```

Android (needs the NDK: `brew install --cask android-ndk`):

```sh
cmake -S . -B build-android -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static \
  -DSANDCLOCK_HARNESS=OFF -DSANDCLOCK_KODI=ON -DKODI_DEVKIT_INCLUDE=<...>
cmake --build build-android
cmake -S . -B build-android32 -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=armeabi-v7a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static \
  -DSANDCLOCK_HARNESS=OFF -DSANDCLOCK_KODI=ON -DKODI_DEVKIT_INCLUDE=<...>
cmake --build build-android32
```

The built `screensaver.infworld.gl.dylib` (macOS universal), `screensaver.infworld.gl.so`
(Android arm64-v8a) and `screensaver.infworld.gl.armv7.so` (Android armeabi-v7a) are committed in
this folder and `../screensaver.infworld.gl.armv7`, so `tools/make_repo.py` publishes them in the
Kodi repository. Rebuild and recopy them after code changes.

## 32-bit Android

Kodi on many Google TV boxes and the Chromecast with Google TV is a 32-bit app and cannot load the
64-bit library. Install **Endless World (OpenGL, 32-bit Android)** from
`../screensaver.infworld.gl.armv7` on those devices; every other platform uses this add-on. The two
add-on ids differ only so Kodi can tell them apart.

## Shader dialects and gotchas

- The renderer is written in GLSL 1.20 / GLSL ES 1.00 and converted to GLSL 1.50 core for the macOS
  core profile by `glu::version_*` prefixes (`src/gl_util.hpp`). The core profile needs a VAO.
- Terrain triangles are wound counter-clockwise as seen from above, because the default
  `glFrontFace(GL_CCW)` with `glCullFace(GL_BACK)` would otherwise cull the ground. infworld's
  original vertex shader swapped x and z in `gl_VertexID`, which mirrored every chunk; the port
  builds the grid explicitly, so the index order was reversed instead.
- The terrain palette (`terraintextures.png`, four quarter-width strips) and the water maps
  (`watermaps.png`, four 128x128 quarters: two normal maps and a dudv map) are split into separate
  repeating textures at load and sampled with continuous UVs. Sampling one atlas with `fract()`
  made a visible line at every tile edge, where the mip level jumps; the water's diagonal seams
  were the same bug.

## Credits and licence

The world model and renderer are a port of infworld (MIT, copyright 2024 Jeremy Li "Nullptr
Error"); the textures come from its assets under CC-BY-SA 3.0. Full credits are in `LICENSE.txt`
and `resources/textures/credits.txt`. Anybody redistributing the add-on or the textures must keep
those credits and share alike.

`resources/textures/credits.txt`, `LICENSE.txt` and `addon.xml` are the canonical place for this:
the add-on is MIT licensed for the code, CC-BY-SA 3.0 for the textures.

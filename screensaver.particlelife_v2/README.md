# Particle Life v2 (OpenGL) - Kodi screensaver

Binary (C++) Kodi screensaver port of the openFrameworks "Particle Life" app.
Colours of particles attract/repel under a matrix of pair forces; the rules are
replaced every N seconds (default 60) so it never gets stale.

## 1.1.0 additions
- **Presets**: `src/Presets.h` holds the 19 models from the original app's
  `bin/interesting_models` folder, converted from the file order (green, red,
  white, yellow; 32 rule values, 4 counts, viscosity) to this port's
  red/green/yellow/white order. A preset brings its own viscosity; the force and
  range scaling settings apply to random rules only, and the particle count stays
  the setting's. Rule source: random, presets in order, shuffled, a 50/50 mix,
  or one preset (the timer then only respawns the particles).
- **1–8 colours** (`MAX_GROUPS`), with an optional random count per rule set.
  Palettes: Classic (the original's four, then cyan, magenta, orange, lavender
  from the JS version), Neon, Pastel, Rainbow, random hues.
- **Randomisation** from the JS version: symmetric rules, random exploration
  (every ~1.7 s one rule flips sign or one radius is re-rolled), pulses
  (impulse ~ 100 x strength / distance, fading over 10 steps, clamped), plus a
  random viscosity (30–75 %) per random rule set and the original's gravity.
- **Rendering**: round, square or glow (additive) point sprites, and motion
  trails through two ping-pong FBO textures (fade = `max(prev * keep - 1.5/255, 0)`
  so trails reach black). If the FBO cannot be created the trails switch off and
  the particles still draw.
- **Cost**: steps scale with colours^2 x particles^2 within the radius. Some
  presets use radii up to ~390, so they are the heaviest case (up to ~10 ms per
  step at 1000 per colour on a desktop, ~2 ms at 500); lower the particle count
  on a TV box.

The add-on files live at the top level of this folder, like the other native
add-ons in this repository; the simulation and wrapper sources are in `src/`.

## What changed vs. the openFrameworks app
- No GUI panel; everything is in the addon settings (particles per colour,
  steps/sec, re-roll interval, rule source / preset, colours, randomisation,
  viscosity, force strength, range, gravity, wall repel, hard bounds, palette,
  particle style and size, trails).
- Physics is the same loop (16 group pairs per step, viscosity/wall repel applied
  per pair), but neighbour search uses a uniform grid instead of all-pairs, so
  1000 particles per colour costs ~1.6 ms/step on a desktop CPU.
- The original passed `powerSliderRR` for every red interaction (RR/RG/RY/RW);
  this port uses the matching RG/RY/RW values. One-line change in
  `Simulation::Step()` if you want the old behaviour back.
- Fixed simulation timestep instead of "as fast as the GPU goes".
- Simulation space is 900 px high (the original's scale), width follows the
  screen aspect ratio; point size scales with resolution.
- Dropped: save/load model dialogs (the shipped models are presets instead),
  live rule sliders, the FPS / physics labels.

## Build (macOS, universal Intel + Apple Silicon)
    cmake -S . -B build-uni -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_OSX_ARCHITECTURES="x86_64;arm64" \
      -DKODI_DEVKIT_INCLUDE=/tmp/kodi-src/xbmc/addons/kodi-dev-kit/include
    cmake --build build-uni
    cp build-uni/addon/screensaver.particlelife_v2/screensaver.particlelife_v2.dylib .

`-DKODI_DEVKIT_INCLUDE` points at the `xbmc/addons/kodi-dev-kit/include`
directory of a Kodi 21 source checkout; the headers used for the committed
build came from Kodi 21.3.

## Build (Android, 64-bit and 32-bit)
    NDK=/opt/homebrew/Caskroom/android-ndk/30/AndroidNDK16248370.app/Contents/NDK
    cmake -S . -B build-android \
      -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
      -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static \
      -DKODI_DEVKIT_INCLUDE=/tmp/kodi-src/xbmc/addons/kodi-dev-kit/include
    cmake --build build-android
    $NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-strip --strip-unneeded \
      -o screensaver.particlelife_v2.so \
      build-android/addon/screensaver.particlelife_v2/screensaver.particlelife_v2.so

Use `-DANDROID_ABI=armeabi-v7a` and build the 32-bit add-on folder
`../screensaver.particlelife_v2.armv7`; the library is committed there as
`screensaver.particlelife_v2.armv7.so`.

## Release
    python3 ../tools/build_zip.py screensaver.particlelife_v2
    # or rebuild the whole repository:
    python3 ../tools/make_repo.py

Bump `version="..."` in `addon.xml` (and in the `.armv7` companion when it
changes), then commit the libraries and the metadata and push to `main`; the
GitHub Actions workflow deploys the updated repository to GitHub Pages.

## Test the simulation alone (no Kodi needed)
    c++ -O2 -std=c++17 tests/sim_test.cpp -o sim_test && ./sim_test

## Notes
- The add-on is a native OpenGL / OpenGL ES 2 add-on (Kodi 21 Omega API:
  `kodi.binary.instance.screensaver` 2.2.0). It draws with plain desktop GL on
  macOS/Linux and GLES 2 on Android.
- The 32-bit Android companion exists because Kodi on many Fire TV sticks and
  Google TV boxes is a 32-bit app and cannot load the arm64 library.

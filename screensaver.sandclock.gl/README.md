# Sand Clock (OpenGL), work in progress

A C++ / OpenGL port of `../screensaver.sandclock`. The Python add-on stays as it is.

| Part | File | Kodi / GL needed |
|---|---|---|
| Layout, glyph grains, falling-sand planner, colours (port of `sand.py` + `config.py`) | `src/sand.*` | no |
| The clock loop (port of `screensaver.py` minus Kodi): when digits crumble, the pile's sink speed | `src/engine.*` | no |
| Shaders: each grain's fall, slide and sink is computed in the vertex shader from its flight data and the time | `src/renderer.*` | GL 2.1 / GLES 2.0 |
| Kodi add-on wrapper (`CInstanceScreensaver`, settings, entry point) | `src/kodi_addon.cpp` | kodi-addon-dev-kit |
| Test window (`sandclock_glfw`, and `sandclock_glfw_core` for the macOS core profile) | `src/main_glfw.cpp` | GLFW |
| Tests | `tests/test_sand.cpp` | no |

Nothing is uploaded per frame. A crumble appends its grains to one buffer and the GPU does the
rest, so the CPU cost is a few hundred planner steps once a second.

## Liquid Clock

A second screensaver from the same code: the digits shimmer, melt into stretched drops that run
into streams and fall into a pool, and the pool is a 1-D shallow-water simulation (`src/liquid.*`:
192 columns, wave speed from depth, ripples where drops land, a tilt "slosh" every few seconds, a
drain that holds the level). Drops are evaluated on the GPU like the sand grains; the pool is one
triangle strip uploaded per frame (about 6 KB), so it is cheap enough for a 32-bit set-top box.
Files: `liquid.*`, `liquid_renderer.*`, `kodi_liquid.cpp`; test window `liquidclock_glfw`
(`--slosh`, `--pile`); the add-on folder is `../screensaver.liquidclock.armv7`, whose settings
come from `tools/make_settings_liquidclock.py`.

## Build and test

```sh
cmake -S . -B build -DSANDCLOCK_HARNESS=OFF && cmake --build build && ctest --test-dir build
```

Test window (needs GLFW: `brew install glfw`, or configure with `-DSANDCLOCK_FETCH_GLFW=ON`):

```sh
cmake -S . -B build && cmake --build build
./build/sandclock_glfw --fonts ../screensaver.sandclock/resources/media/fonts/fonts.json
```

## Kodi add-on

Built against the Kodi 21 "Omega" dev kit (screensaver API 2.2.0). Get the headers once:

```sh
git clone --depth 1 --branch 21.1-Omega https://github.com/xbmc/xbmc.git   # or a sparse checkout of xbmc/addons/kodi-dev-kit/include
cmake -S . -B build -DSANDCLOCK_KODI=ON -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include
cmake --build build
```

That writes `build/addon/screensaver.sandclock.gl/` (library, `addon.xml`, settings, fonts), ready
to copy into Kodi's `addons` folder. `resources/settings.xml` and the strings are generated from
the Python add-on's settings table by `tools/make_settings_sandclock_gl.py`, so both have the same
settings.

Android (arm64-v8a; needs the NDK, `brew install --cask android-ndk`):

```sh
cmake -S . -B build-android -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static \
  -DSANDCLOCK_HARNESS=OFF -DSANDCLOCK_KODI=ON -DKODI_DEVKIT_INCLUDE=<xbmc>/xbmc/addons/kodi-dev-kit/include
cmake --build build-android   # then llvm-strip --strip-unneeded the .so
```

The built `screensaver.sandclock.gl.dylib` (macOS universal, ad-hoc signed) and
`screensaver.sandclock.gl.so` (Android arm64) are committed in this folder so
`tools/make_repo.py` publishes them in the Kodi repository. Rebuild and recopy them after code changes.
32-bit Android (armeabi-v7a) is not built.

Shader dialects: GLES 2 (`-DSANDCLOCK_GLES=ON`), desktop GL 2.1 and the 3.2 core profile (macOS,
automatic; needs a VAO). Linux and Android builds have not been run on a device.

## Not done yet

- Not yet run inside Kodi itself.
- macOS: the library is only ad-hoc signed and Kodi may refuse it.
- CI build matrix; Linux, Windows (ANGLE) and 32-bit Android (armeabi-v7a) builds.
- Time is a float in the shader. Fine for hours; rebase `born` and `now` for sessions of days.

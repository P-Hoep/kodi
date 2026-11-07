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

Shader dialects: GLES 2 (`-DSANDCLOCK_GLES=ON`), desktop GL 2.1 and the 3.2 core profile (macOS,
automatic; needs a VAO). Linux and Android builds are untested.

## Not done yet

- Not yet run inside Kodi itself.
- macOS: the library needs ad-hoc signing (`codesign -s -`) and Kodi may refuse unsigned add-ons.
- CI build matrix (Linux x64/ARM, Android arm64, Windows/ANGLE) and Kodi's own add-on repo packaging.
- Time is a float in the shader. Fine for hours; rebase `born` and `now` for sessions of days.

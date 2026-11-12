# Development guide

How to work on the add-ons in this repository: the Python ones and the native OpenGL ones.
Deployment (packaging, the repository, GitHub Pages, Fire TV) is in
[deployment.md](deployment.md).

> **The native add-ons use OpenGL and OpenGL ES, not WebGL.** A Kodi binary add-on is a compiled
> shared library loaded by Kodi; there is no browser engine and no WebGL context inside Kodi.
> Kodi on macOS gives the add-on an OpenGL 3.2 core context; Kodi on Android gives it an
> OpenGL ES 2.0 context. Everything below is about those two APIs. This is stated in
> [screensaver.plant.gl/README.md](../screensaver.plant.gl/README.md).

## The two kinds of add-on

| | Python add-ons | Native add-ons |
|---|---|---|
| What ships | `.py` files and generated media | a `.dylib` (macOS) and/or `.so` (Android) plus `addon.xml` and `resources/` |
| Entry point | `default.py` or the `library` named in `addon.xml` | a C++ `CAddonBase` / `CInstance*` class, exported with `ADDONCREATOR` |
| Kodi API | `xbmc*` Python modules | C++ headers from Kodi's dev kit |
| Platforms | all | macOS, Android (64-bit and 32-bit builds) |
| Tests | `python3 -m unittest` | `ctest` (CPU-side core tests and harness selftests) |
| Built by CI? | no build step | **no**: libraries are compiled locally and committed |

The GitHub workflow only builds zips and the repository index. It does not compile native code,
so a native change is not published until someone rebuilds the library and commits it next to
`addon.xml`.

## Repository layout

```
screensaver.godseye.map/            one add-on folder per add-on id
  addon.xml                         id, version, requires, extension point, libraries
  default.py                        entry point (screensavers, scripts)
  resources/
    lib/                            Kodi-free core + thin Kodi glue
    settings.xml                    GENERATED
    language/resource.language.en_gb/strings.po   GENERATED
    skins/…                         window XML
    media/, data/                   generated artwork and bundled data
  tests/test_*.py                   offline unit tests (may live at the top level too)
tools/
  make_settings*.py                 settings.xml + strings.po from one Python table
  make_*_media.py                   icons, fanart, textures, glyphs (Pillow)
  build_zip.py                      one installable zip
  make_repo.py                      the Kodi repository
  kodi.py                           drive a local Kodi over JSON-RPC
screensaver.sandclock.gl/           native project: Sand Clock, Liquid Clock,
                                    Cellular Automata (3), Physarum (2), Tetris AI, Particle Life,
                                    Visualisation
screensaver.plant.gl/               native project: Growing Plant
screensaver.infworld.gl/            native project: Endless World
screensaver.particlelife_v2/        native project: Particle Life v2
screensaver.screenmazer/            native project: ScreenMazer
screensaver.lichencoral/            native project: Lichen & Coral
```

Each native project is one CMake build producing the Kodi module(s) and GLFW test harnesses. Its
library is copied into the add-on folder(s) that declare it.

---

# Python add-ons

## Anatomy

A screensaver needs `default.py` with:

```python
import xbmc
import xbmcgui

if __name__ == '__main__':
    # build the window, show() it, run until ScreenSaverActive goes false
```

Keep the logic that does not need Kodi in `resources/lib/` and import it from the entry point.
`tests/test_*.py` imports those modules directly, so the tests run without Kodi. Anything that
imports `xbmc`, `xbmcgui`, `xbmcaddon` or `xbmcvfs` belongs in the thin glue layer.

## Screensaver lifecycle: use `show()`, not `doModal()`

When Kodi wakes a screensaver itself (a `RunScript`, a screenshot request), it closes the window
without telling Python. A `doModal()` then never returns, and Kodi kills the script after about
5 seconds. Show the window with `show()` and loop while `System.ScreenSaverActive` is true:

```python
win = MyWindow()
win.show()
mon = xbmc.Monitor()
while not mon.abortRequested() and xbmc.getCondVisibility('System.ScreenSaverActive'):
    if mon.waitForAbort(0.25):
        break
xbmc.executebuiltin('Dialog.Close(all,true)')
```

`Dialog.Close` closes the window without waiting on Kodi's main thread. This pattern is used by
Jeopkodi, DVD Logo, Tetris AI and others.

Other lifecycle notes that have bitten these add-ons:

- Kodi wakes a screensaver when anything starts playing, then stops its script. Live Cams starts
  a second, ordinary script for the session so its own `play()` does not immediately end it.
- A screensaver that takes over the screen needs to exit on any input quickly (Word Clock exits
  in about 0.02 s).
- Screenshots: EventServer packets wake a screensaver, so `kodi.py shot` cannot photograph one.
  Run a script inside Kodi that calls `TakeScreenshot` instead.

## Settings: one table generates `settings.xml` and `strings.po`

Do not hand-edit `resources/settings.xml` or `strings.po`. Each add-on has one Python table
(usually `resources/lib/config.py`), and `tools/make_settings_<addon>.py` writes both files:

```bash
python3 tools/make_settings_jeopkodi.py
python3 tools/make_settings_plant_gl.py                 # native: also cross-checks option indices
python3 tools/make_settings_tetris_gl.py                # writes both tetris.gl and tetris.gl.armv7
python3 tools/make_settings_vintageradar.py             # writes both Vintage Radar add-ons and the library defaults
```

`tools/make_settings.py` contains the shared writer. String ids start at **30100** and are
positional, so inserting an option in the middle of a table renumbers everything after it. Kodi
loads an add-on's strings only at start-up: after a first install by symlink, settings labels are
blank until Kodi restarts.

Two settings features that work well:

- **Window properties + XML animations.** Python sets a Home window property; XML
  `setVisibleCondition()` / `Conditional` animations react. A time change becomes a few
  `setProperty` calls and Kodi does the animation, so CPU use stays low (Word Clock about 3 %).
- **Theming with `colordiffuse`.** White textures tinted from window properties look the same in
  every skin. `$INFO[Window.Property(...)]` is accepted in `textcolor`, `selectedcolor` and
  texture `colordiffuse`, including inside list layouts.

## Kodi API gotchas collected from this repo

- **Add-ons cannot load fonts.** Every glyph is a pre-rendered PNG. Word Clock, Sand Clock,
  Jeopkodi and Math Clock all ship glyph images plus metrics and position them from Python.
- **A bare number in a `<label>` is a string id.** Use `$NUMBER[n]` to print a number (Sheetcards).
- **Groups and grouplists do not clip animated children.** Peeks and rolls must be squashes that
  stay inside the tile, not slides (RSS Live Tiles).
- **`rotatex` / `rotatey` use a close camera**, so a flipping picture tile balloons out of its
  rectangle. Use 2D squashes instead.
- **Add-ons cannot register fonts** without editing the skin, so use the skin's font names.
- **No imaging library on Android or Fire TV.** Kodi cannot composite pictures in Python there;
  let Kodi's GPU do it (SkyWatch composites WMS frames as image controls).
- **Kodi's own player** is the right place for video and audio; a screensaver should not fight it.
- **Strings are cached at start-up**; restart Kodi after renaming an add-on or editing
  `strings.po`.

## Testing

```bash
python3 -m unittest discover tests          # offline
LIVE=1 python3 -m unittest discover tests   # also hits real feeds
python3 -m unittest tests.test_jeopkodi     # one add-on
```

Keep every test offline by default. Network tests go behind `LIVE=1` (or the add-on's own
environment variables, for example Audioshelf's `LIVE=1 ABS_URL=… ABS_KEY=…`).

## Driving a local Kodi

`tools/kodi.py` talks JSON-RPC on TCP 9090 and the EventServer on UDP 9777:

```bash
python3 tools/build_zip.py screensaver.jeopkodi
KODI_ADDON=screensaver.jeopkodi python3 tools/kodi.py install   # symlink + enable
KODI_ADDON=screensaver.jeopkodi python3 tools/kodi.py select    # make it the screensaver
KODI_ADDON=screensaver.jeopkodi python3 tools/kodi.py set hours=12
KODI_ADDON=screensaver.jeopkodi python3 tools/kodi.py run       # start it now
python3 tools/kodi.py shot out.png                              # screenshot via Kodi
python3 tools/kodi.py log                                       # tail kodi.log
```

`KODI_ADDON` defaults to `screensaver.godseye.map`. The Kodi home is
`~/Library/Application Support/Kodi` on macOS and `~/.kodi` elsewhere; override with
`KODI_HOME`. Commands are `install`, `select`, `set`, `run`, `action`, `builtin`, `shot`, `log`.

---

# Native OpenGL / OpenGL ES add-ons

## Prerequisites

| Tool | Install / version |
|---|---|
| C++17 compiler, CMake ≥ 3.16 | Xcode command line tools (`xcode-select --install`), `brew install cmake` |
| GLFW (harnesses) | `brew install glfw`, or configure with `-DSANDCLOCK_FETCH_GLFW=ON` / `-DPLANT_FETCH_GLFW=ON` (FetchContent pulls GLFW 3.4) |
| glslangValidator | `brew install glslang` (checks dumped shaders) |
| Android NDK | `brew install --cask android-ndk` |
| Kodi dev-kit headers | Kodi 21.1 Omega (see below) |

The NDK is **not** at `$ANDROID_NDK_HOME` on a Homebrew install. Its toolchain file is inside a
`.app` bundle, for example:

```bash
NDK=/opt/homebrew/Caskroom/android-ndk/30/AndroidNDK16248370.app/Contents/NDK
```

(There is also `/opt/homebrew/share/android-ndk`, which is what the build caches on this machine
used.) Point `-DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake` at whichever
exists.

Kodi dev-kit headers, a shallow sparse checkout:

```bash
git clone --depth 1 --filter=blob:none --sparse --branch 21.1-Omega https://github.com/xbmc/xbmc.git
cd xbmc
git sparse-checkout set addons/kodi-dev-kit/include
# then pass -DKODI_DEVKIT_INCLUDE=/path/to/xbmc/xbmc/addons/kodi-dev-kit/include
```

If `KODI_DEVKIT_INCLUDE` is omitted, CMake tries `find_package(Kodi QUIET)` and uses
`KODI_INCLUDE_DIR`. The caches in this checkout used `/tmp/kodi-src/xbmc/addons/kodi-dev-kit/include`.

## The three native projects

| Project | Add-ons built from it | CMake option prefix |
|---|---|---|
| `screensaver.sandclock.gl` | Sand Clock GL, Liquid Clock, Cellular Automata, CA Lite, CA 3D, Physarum, Physarum Lite, Tetris AI GL, Physarum Visualisation | `SANDCLOCK_*` |
| `screensaver.plant.gl` | Growing Plant GL | `PLANT_*` |
| `screensaver.infworld.gl` | Endless World GL | `SANDCLOCK_*` (same names, different project) |

Each has the same shape:

- **GL-free core** (`src/*.cpp`, into e.g. `sandclock_core`, `plant_core`, `infworld_core`): the
  model — sand physics, automata rules, slime agents, Tetris engine, plant L-system, world
  noise/chunks. It has no OpenGL and is what `tests/test_*.cpp` tests.
- **Renderer** (`*_app.cpp`, `renderer.cpp`): owns GL objects and draws a frame.
- **Kodi wrapper** (`src/kodi_*.cpp`): settings, `CInstance*` subclass, lifecycle.
- **GLFW harness** (`src/main_*_glfw.cpp`): runs the renderer in a window with no Kodi, for fast
  iteration and screenshots.
- **Tests** (`tests/test_*.cpp`), registered with `add_test`, run with `ctest`.

CMake options (sandclock project; plant uses the `PLANT_` spelling):

| Option | Default | Meaning |
|---|---|---|
| `SANDCLOCK_GLES` | OFF | OpenGL ES 2.0 shaders and headers |
| `SANDCLOCK_HARNESS` | ON | Build the GLFW windows (needs GLFW) |
| `SANDCLOCK_FETCH_GLFW` | OFF | Download GLFW 3.4 instead of finding it |
| `SANDCLOCK_KODI` | OFF | Build the Kodi add-on modules |
| `KODI_DEVKIT_INCLUDE` | — | path to `xbmc/addons/kodi-dev-kit/include` |

## Shader dialects: one source, three prefixes

Shaders are written in GLSL 1.20 / GLSL ES 1.00 style (`attribute`, `varying`, `texture2D`,
`gl_FragColor`). `glu::compile` in `src/gl_util.hpp` prepends a version and a precision header:

| Context | Prefix | Selection |
|---|---|---|
| OpenGL ES 2.0 | none (GLSL ES 1.00) | `HAS_GLES=2`, `*_GLES` |
| OpenGL 3.2 core (Kodi on macOS) | `#version 150` + `attribute`→`in`, `varying`→`in/out`, `texture2D`/`textureCube`→`texture`, `gl_FragColor`→out variable | `*_CORE` |
| Desktop compatibility (harness) | `#version 120` | default |

The precision header adds `precision highp float` (falling back to `mediump` for fragment
shaders when `GL_FRAGMENT_PRECISION_HIGH` is absent). `gl_include.hpp` picks the right GL header:
`<kodi/gui/gl/GL.h>` for Kodi builds, `<GLES2/gl2.h>` for GLES harnesses, `<OpenGL/gl3.h>` for
macOS core, otherwise desktop GL.

**Windows is not supported by these CMake files**: Kodi on Windows uses ANGLE (GLES), and the
projects fail configure with a message telling you to build with Kodi's own add-on CMake there.

## Renderer rules that matter

1. **A VAO is required in core contexts.** Bind one under the core macro, and restore the
   previous binding in `SavedState` — a core context draws only through a bound VAO.
2. **GLES 2 has 16-bit indices only.** Cap each mesh batch at 60,000 vertices (Growing Plant) and
   clamp tree meshes to 65,535 indices (Endless World), and draw with `GL_UNSIGNED_SHORT`.
3. **GLES 2 has no VAOs, no `GL_PROGRAM_POINT_SIZE`, no `glBlendFuncSeparate`.** Guard them. The
   GLES `SavedState` restores blend factors with `glBlendFunc`, because the separate-alpha queries
   do not exist.
4. **Save and restore all GL state you touch.** `glu::SavedState` saves FBO, viewport, active
   texture, program, array and element buffers, clear colour, depth mask, blend factors and
   equations, enables and (in core builds) the VAO, and disables blend/depth/cull/scissor while
   the add-on draws. Leaving culling or depth test on makes Kodi's GUI lose its images after the
   screensaver exits — that is exactly why the class exists. Extend it carefully if you touch more
   state.
5. **The context is Kodi's.** `Start`, `Render` and `Stop` run with Kodi's context current.
   Create GL objects in `Start`/first render; delete them in `Stop()` (call `release()` there),
   not in the destructor.
6. **Winding and atlases.** Endless World builds its ground triangles counter-clockwise as seen
   from above so back-face culling does not eat the terrain, and splits atlases into repeating
   textures because `fract()` sampling showed seams.
7. **No 3D textures in GLES 2.** Cellular Automata 3D stores its volume in a 2D RGBA8 slice atlas
   with a one-cell wrapped border, so the update shader reads fixed offsets with no wrap
   arithmetic.

Check shader variants without a device: harnesses with `--dump-shaders DIR` write every compiled
variant, and `glslangValidator` checks them. CA Lite dumps 218 files for 57 settings combinations;
CA 3D dumps 1,272 files and is checked as both GLSL ES 1.00 and core.

## Kodi wrapper: screensaver

```cpp
#include <kodi/addon-instance/Screensaver.h>

class ATTR_DLL_LOCAL MySaver : public kodi::addon::CInstanceScreensaver {
public:
  explicit MySaver(const kodi::addon::IInstanceInfo& instance)
      : CInstanceScreensaver(instance) {}

  bool Start() override { /* read settings, build App, init(); log ADDON_LOG_ERROR and
                            return false on failure */ }
  void Stop() override  { app_->release(); app_.reset(); }   // context is current
  void Render() override { app_->render(now, Width(), Height()); }
};

class MyAddon : public kodi::addon::CAddonBase {
public:
  ADDON_STATUS CreateInstance(int instanceType, const std::string& instanceID,
                              KODI_HANDLE instance, const std::string& version,
                              KODI_HANDLE& addonInstance) override {
    if (instanceType == ADDON_INSTANCE_SCREENSAVER) { … return ADDON_STATUS_OK; }
    return ADDON_STATUS_UNKNOWN;
  }
};

ADDONCREATOR(MyAddon)
```

`Render()` gets elapsed seconds from `std::chrono::steady_clock` and Kodi's `Width()`/`Height()`.
Settings are read with `kodi::addon::GetSettingInt/Boolean/String` into a struct, clamped to the
same ranges as the generated `settings.xml`. Resource paths come from
`kodi::addon::GetAddonPath`. Colours accept `RRGGBB` and `AARRGGBB` (masked to RGB).

## Kodi wrapper: music visualisation

`visualization.physarum.lite` derives from `CInstanceVisualization` and has one extra rule:
`AudioData` arrives on Kodi's audio thread while `Render` runs on the render thread. Store the
instance under a mutex, copy the `shared_ptr` out, then use it. `Start(...)` is called once per
track, so build a fresh analyser each time. `IsDirty()` returns true; `Stop()` swaps the pointer
out and calls `release()` while the context is current.

## Build: desktop harness and CPU tests

Sand Clock project (also builds every other harness):

```bash
cd screensaver.sandclock.gl
cmake -S . -B build -DSANDCLOCK_HARNESS=OFF && cmake --build build && ctest --test-dir build
cmake -S . -B build && cmake --build build
./build/sandclock_glfw      --fonts ../screensaver.sandclock/resources/media/fonts/fonts.json
./build/sandclock_glfw_core --fonts ../screensaver.sandclock/resources/media/fonts/fonts.json
```

Growing Plant and Endless World:

```bash
cd screensaver.plant.gl
cmake -S . -B build -DPLANT_HARNESS=OFF && cmake --build build && ctest --test-dir build
cmake -S . -B build && cmake --build build
./build/plant_glfw --preset 1 --background 1 --motion 1 --seed 42

cd ../screensaver.infworld.gl
cmake -S . -B build -DSANDCLOCK_HARNESS=OFF && cmake --build build && ctest --test-dir build
cmake -S . -B build && cmake --build build
./build/infworld_glfw --assets resources/textures --seed 2
```

Every harness supports `--shot out.ppm --shot-after SECONDS` (PPM via `glReadPixels`). The
`*_core` variant asks for a 3.2 core context, matching Kodi on macOS. Harnesses with
`--selftest` compare the GPU result against the CPU core: Automata, Automata Lite, Physarum,
Physarum Lite, Physarum Audio and Voxel. `--dump-shaders DIR` is on Automata Lite and Voxel.

## Build: macOS universal dylib

Two equivalent recipes.

**One CMake build for both architectures** (Sand Clock project: Sand Clock, Tetris,
Visualisation):

```bash
cd screensaver.sandclock.gl
cmake -S . -B build-uni -DCMAKE_OSX_ARCHITECTURES="x86_64;arm64" \
  -DSANDCLOCK_KODI=ON -DSANDCLOCK_HARNESS=OFF \
  -DKODI_DEVKIT_INCLUDE=/path/to/xbmc/xbmc/addons/kodi-dev-kit/include
cmake --build build-uni
codesign --force --sign - build-uni/screensaver.sandclock.gl.dylib
cp build-uni/screensaver.sandclock.gl.dylib screensaver.sandclock.gl/
```

**Two builds plus `lipo`** (Growing Plant and Endless World):

```bash
cd screensaver.plant.gl
for arch in x86_64 arm64; do
  cmake -S . -B build-macos-$arch -DCMAKE_OSX_ARCHITECTURES=$arch \
    -DPLANT_HARNESS=OFF -DPLANT_KODI=ON \
    -DKODI_DEVKIT_INCLUDE=/path/to/xbmc/xbmc/addons/kodi-dev-kit/include
  cmake --build build-macos-$arch
done
lipo -create -output screensaver.plant.gl.dylib \
  build-macos-x86_64/screensaver.plant.gl.dylib build-macos-arm64/screensaver.plant.gl.dylib
codesign --force --sign - screensaver.plant.gl.dylib
cp screensaver.plant.gl.dylib ../screensaver.plant.gl/
```

Signing ad hoc (`--sign -`) is enough for a locally loaded add-on. The committed dylibs are
universal (`file` shows `Mach-O universal … x86_64 arm64`).

## Build: Android 64-bit and 32-bit

64-bit (`arm64-v8a`) for the main add-ons, 32-bit (`armeabi-v7a`) for the `.armv7` add-ons:

```bash
cd screensaver.sandclock.gl
NDK=/opt/homebrew/Caskroom/android-ndk/30/AndroidNDK16248370.app/Contents/NDK

cmake -S . -B build-android \
  -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static \
  -DSANDCLOCK_HARNESS=OFF -DSANDCLOCK_KODI=ON \
  -DKODI_DEVKIT_INCLUDE=/path/to/xbmc/xbmc/addons/kodi-dev-kit/include
cmake --build build-android
llvm-strip --strip-unneeded build-android/screensaver.sandclock.gl.so
cp build-android/screensaver.sandclock.gl.so screensaver.sandclock.gl/

# 32-bit companion
cmake -S . -B build-android32 \
  -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=armeabi-v7a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static \
  -DSANDCLOCK_HARNESS=OFF -DSANDCLOCK_KODI=ON \
  -DKODI_DEVKIT_INCLUDE=/path/to/xbmc/xbmc/addons/kodi-dev-kit/include
cmake --build build-android32
llvm-strip --strip-unneeded build-android32/screensaver.sandclock.gl.so
cp build-android32/screensaver.sandclock.gl.so \
  screensaver.sandclock.gl.armv7/screensaver.sandclock.gl.armv7.so
```

Growing Plant and Endless World use the same flags with their `PLANT_*` / `SANDCLOCK_*` options;
their READMEs give the exact copy commands.

### Why the `.armv7` add-ons have different ids

Kodi installs one library per add-on id per platform. A 32-bit Kodi (Fire TV, many Google TV
boxes, Chromecast with Google TV) cannot load the arm64 `.so`, and the reverse is also true.
Putting both in one zip would make what installs depend on which platform Kodi picks, so the
32-bit builds are separate add-ons (`screensaver.tetris.gl.armv7` and so on) with their own
`addon.xml`, `library_android="<id>.armv7.so"` and `<platform>android</platform>`.

A `.armv7` folder contains `addon.xml` and the 32-bit `.so` — no `.dylib`. If the add-on reads
resources at run time, copy those too into the folder.

## Which file goes where

| Built artifact | Destination |
|---|---|
| `build-uni/<id>.dylib` | `<id>/<id>.dylib` |
| `build-android/<id>.so` | `<id>/<id>.so` |
| `build-android32/<id>.so` | `<id>.armv7/<id>.armv7.so` |
| `build/addon/screensaver.sandclock.gl/` (POST_BUILD) | ready-to-copy folder for Sand Clock GL |

Only the `screensaver.sandclock.gl` target assembles its add-on folder automatically. The other
modules produce a bare library; populate the add-on folder by hand.

## Settings for native add-ons

The Kodi UI and the C++ wrapper must agree on what option index N means. The generators ensure
that:

- `tools/make_settings_plant_gl.py`: its own table; optional args take the add-on id and name, and
  `low` makes the `quality` default Low (for the armv7 add-on).
- `tools/make_settings_sandclock_gl.py`: imports the Python add-on's `config.CATEGORIES` and
  reuses it.
- `tools/make_settings_tetris_gl.py`: imports `screensaver.tetris`'s table and writes **both**
  `screensaver.tetris.gl` and `screensaver.tetris.gl.armv7`.
- `tools/make_settings_infworld.py`: its own table, optional id/name args.
- `tools/make_settings_vintageradar.py`: one table for the Python screensaver and app; it also
  writes the shared library's `defaults.py`.
- `tools/make_settings_automata*.py`, `make_settings_voxel.py`, `make_settings_physarum*.py`: also
  write the renderer's option tables (`src/automata_tables.hpp`, `voxel_tables.hpp`,
  `physarum_tables.hpp`) so indices cannot drift.

Run the matching generator after changing any native settings table, then rebuild.

## Testing and iterating on a device

The quickest loop is the GLFW harness with `--shot`, then `tools/kodi.py` against a local Kodi.
For Fire TV, the device must run a Kodi whose bit width matches the library; see
[fire-sticks.md](fire-sticks.md) and [deployment.md](deployment.md). Two hard-won notes:

- Never `am force-stop` Kodi after changing settings; use `Application.Quit`.
- `adb exec-out screencap` does not wake a screensaver; use Kodi's `TakeScreenshot`.

---

## Further reading

- [Deployment guide](deployment.md): zips, the repository, GitHub Pages, Fire TV, troubleshooting.
- Native project READMEs: [sandclock.gl](../screensaver.sandclock.gl/README.md),
  [plant.gl](../screensaver.plant.gl/README.md),
  [infworld.gl](../screensaver.infworld.gl/README.md).
- Per-add-on design notes linked from the [root README](../README.md).

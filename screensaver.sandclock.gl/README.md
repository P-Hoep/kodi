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

A second screensaver from the same code: the digits shimmer, melt into threads that stretch and
fall into a pool, and the pool is a conservative 1-D shallow-water simulation (`src/liquid.*`):
256 columns, a depth per column and a velocity at every face, pressure from the surface slope,
upwind momentum advection, linear and quadratic drag, viscosity and a CFL-clamped upwind transport
of mass, stepped at 240 Hz. Every colour falling into the pool is a fluid of its own with its own
depth array: the liquids never mix, so the pool settles into coloured strata (heavier colours
sink), each drawn as its own band between cumulative interfaces with caustics, a meniscus at every
interface and a specular waterline. Impacts deposit their volume over five columns, kick a ripple
and throw ballistic spray droplets plus a short-lived foam crown; a tilt "slosh" rocks the pool
every few seconds and a drain holds the level. Drops and spray are evaluated on the GPU like the
sand grains; the pool is one triangle strip per fluid uploaded per frame (a few KB), so it is
cheap enough for a 32-bit set-top box. Files: `liquid.*`, `liquid_renderer.*`, `kodi_liquid.cpp`;
test window `liquidclock_glfw` (`--slosh`, `--pile`); the add-on folder is
`../screensaver.liquidclock.armv7`, whose settings come from `tools/make_settings_liquidclock.py`.

## Cellular Automata

A third screensaver: Conway's Life and other Life-like and multi-state (Generations) rules run
entirely on the GPU. The grid is two RGBA8 textures (state, age, trail, alive) that a fragment
shader ping-pongs, one pass per generation, so cost is a few texture reads per cell: on an Apple M2
about 1,400 generations/s on 2.1 million cells and 490/s on 8.3 million (3840 x 2160). A governor
lowers generations per frame if the display slows. Files: `automata.*` (rules, patterns, a CPU
reference, no GL), `automata_app.*` (shaders, textures, restarts), `kodi_automata.cpp`,
`main_automata_glfw.cpp`. `automata_glfw --selftest` runs random boards on the GPU and compares
every cell with the CPU reference for 10 rule/wrap combinations (all match). Since 1.1: a clock in
the middle (on top, digits that burst into life, cut out of the cells, or made of living cells;
the font masks are drawn into a texture the update shader reads), nine colour modes, glow,
backgrounds, vignette/CRT, a camera (drift, zoom, fly-through) and 3D-looking views (raised blocks,
a perspective landscape, a tunnel, a globe), all in the draw shader. Every shader in this folder is
checked against GLSL ES 1.00 with `glslangValidator` (`brew install glslang`) before an Android
build. The rule, grid, speed and pattern lists come from `tools/make_settings_automata.py`, which writes both the Kodi settings
and `src/automata_tables.hpp`. Add-on folder: `../screensaver.automata.armv7`.

## Cellular Automata Lite

A separate, stripped-down Cellular Automata for weak devices (32-bit ARM boxes), published as its
own add-on: `../screensaver.automata.lite.armv7`. The shaders are written for speed, and the clock
is optional and off by default: while it is off nothing about it exists (no font loaded, no clock
texture, no mask sampler or mask branch in the update shader, no overlay pass), so it costs
exactly what a build with no clock at all does. Switched on, it has the same five modes, fonts and
colours as the full add-on, and the overlay is drawn after the scale-up, so the digits stay sharp
whatever the scene is drawn at.

What changed, and what it bought on an Apple M2 (same board, same settings, measured in one
process):

- **Specialised shaders.** The update and draw shaders are generated at start with the rule,
  wrap, colour mode, clock mode, view, background, shape, glow and screen effect compiled in as
  `#define`s, so the options not in use cost nothing: no branches on the view or colour mode, no
  palette or neighbour lookups for the ones not selected. The fixed 16-uniform budget is kept.
  The clock mask is compiled in the same way (`CLOCK_MASK` 0, and the mask sampler, the rect and
  the branch are not in the shader at all); the overlay pass is linked only when a clock mode that
  needs it is selected.
- **Cheaper wrapping.** A torus cell lookup is `fract((c + 0.5) * u_inv)` -- one multiply-add and
  a fract per neighbour -- instead of a `mod` and a divide.
- **Uniform locations cached** and one `glu::SavedState` per frame instead of one per pass.
- **Draw resolution cap.** The scene is drawn into a target no larger than twice the grid and no
  more than 1920 x 1080, then one cheap pass scales it up. On a 4K output that is one copy pass
  instead of shading every pixel. The setting "Draw the scene at" (Automatic, 1080p, 720p, 540p,
  360p, full screen) exposes it; lower it first if the picture stutters.
- **Sharp clock at any draw size.** The clock overlay is drawn after the scale-up, at output
  resolution, so it does not inherit the capped draw resolution.
- **Lighter defaults.** 640 x 360 cells (230 thousand) instead of 960 x 540, same 30 generations a
  second, with the same governor that lowers generations per frame if the display slows.
- **Glow** reuses the already-fetched cell colour for the halo instead of calling the shader twice.

Measured against the full add-on, the update pass (the part that fixes how large a grid the box can
run) is 1.7-1.9x faster: 9,400 generations/s against 5,300 at 960 x 540, and 960 against 660 at
3840 x 2160. The draw pass at the default 640 x 360 grid costs 0.57 ms a frame at 1080p instead of
0.86 (and 1.12 instead of 1.53 at 4K); with glow at 100 the two are even. Absolute numbers vary with
machine load; the ratios held across grid sizes, views, colour modes and shapes.

With the clock back, clock-off is unchanged (A/B against the 1.0.0 build: update 0.075 against
0.079 ms a generation at 640 x 360, draw 0.63 against 0.63 ms a frame at 1080p, both within the
run-to-run noise of the machine). Clock-on adds one blended quad after the scale-up (about 0.1 ms
at 1080p) for the three overlay modes, and a mask lookup per cell in the update pass only for the
masked modes: "made of living cells" reads the mask every generation, which is about 10% of the
update cost at 640 x 360.

Files: `automata_lite_app.*` (shaders, targets, restarts), `kodi_automata_lite.cpp`,
`main_automata_lite_glfw.cpp`; it shares `automata.*` (rules, patterns, the CPU reference).
The harness's `--selftest` compares the GPU states with the CPU reference for 10 rule/wrap
combinations, and `--dump-shaders DIR` writes the update, draw, present and (when a clock mode
needs it) clock shaders for the flags given, which every variant is checked as GLSL ES 1.00 with
`glslangValidator` before an Android build (218 files for 57 settings combinations, clock modes
crossed with views included). Settings come from `tools/make_settings_automata_lite.py`, which
reuses the rule, clock and option lists from `tools/make_settings_automata.py`, so a setting index
means the same thing in both add-ons; the only list of its own is "Draw the scene at".

The 32-bit library is built with the NDK in `build-android32` (`-DANDROID_ABI=armeabi-v7a
-DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static -DSANDCLOCK_HARNESS=OFF -DSANDCLOCK_KODI=ON`)
and stripped with `llvm-strip --strip-unneeded`; the built
`screensaver.automata.lite.armv7.so` is committed in the add-on folder. It was also run in Kodi
21.1 on macOS (a universal dylib from the same sources) in the flat and globe views, and with the
clock on top, made of living cells and off.

## Physarum

A fourth: the slime mould model of Jeff Jones ("Characteristics of pattern formation and evolution
in approximations of Physarum transport networks", Artificial Life 16(2), 2010), drawn as Sage
Jenson and nicoptere/physarum do, entirely on the GPU. Agents live in RGBA8 textures (position x/y
and heading as 16-bit fractions, the only render target every GLES 2 device has); the trail map is
half float where the device can render and blend it, else RGBA8 with a rounding floor. A step is
four passes: sense and turn, move, deposit (every agent a 1 px point blended into its species'
channel; the vertex shader reads the agent's texel, so it needs vertex texture fetch) and diffuse +
decay + feed. Trail A is food (clock digits, food sources) that every species is drawn to. Clock
modes feed the digits, wall the slime inside them (Jones's blocked agents pick a new direction) or
wall it out. Above 1M agents each step deposits a rotating 1/k of them at k times the amount,
because blended points are the slow part on tile-based GPUs (4x faster at 4M). On an Apple M2:
1M agents at about 165 steps/s, 4M at 115, 8M on a 1920 x 1080 trail at 30. Files: `physarum.*`
(settings, behaviours, wandering, no GL), `physarum_app.*`, `kodi_physarum.cpp`,
`main_physarum_glfw.cpp`, shared `gl_util.hpp`. `physarum_glfw --selftest` checks the move, deposit
and turning passes against the model on the CPU, with both trail formats. `--custom
sa,ra,so,ss,decay,diffuse,deposit,jitter` tries a behaviour. Presets and settings come from
`tools/make_settings_physarum.py`. Add-on folder: `../screensaver.physarum.armv7`.

## Physarum Lite

A separate, stripped-down Physarum for low-resource devices, published as its own add-on. Every
timer is gone: the simulation never starts over on a schedule and the behaviour never wanders on
its own. What is left is the four-pass agent model and the draw pass, running continuously for as
long as Kodi shows it, plus an optional clock in the middle.

The clock is **off by default**, and while it is off nothing about it runs: no font is loaded, no
clock texture is created, the digit raster is skipped, the food map keeps only its food sources and
the shaders take their ordinary path (the digit, wall and respawn terms are zero and early-out).
When switched on, the same five modes as the full add-on are available: on top, grows into the
digits, faintly on top while the slime grows in, made of slime (agents confined inside the digits,
respawned into them), and flows around. The clock start option is appended at the end of the start
list, so no saved setting index changed meaning. A debug build of the Lite app with the clock off
measured 88 fps against 90 on top on an M2 desktop; on a real device the cost is the font texture
and the overlay pass only while a mode is selected.

The defaults are deliberately light (16 thousand agents, a 480 x 270 trail, no glow, no screen
effect, no clock); the settings expose the same behaviour, size, food, clock, colour, view and
camera lists as the full add-on, plus a 320 x 180 trail below it. The simulation is locked to the
display instead of a clock: one step runs on every rendered frame, and never more than one, so
every frame asks the GPU for the same work and the frame rate either holds or settles evenly lower
instead of alternating heavy and light frames. "Simulation updates" steps on every second, third or
fourth frame to calm it down (still evenly spaced). The draw pass renders at no more than twice
the trail size (960 x 540 at the default) and scales that up, so the most per-pixel work in the
add-on costs a quarter of a 1080p draw and a 4K output costs the same again; below that it draws
straight to the screen.
Files: `physarum_lite.hpp` (settings and the shared params), `physarum_lite_app.*`,
`kodi_physarum_lite.cpp`, `main_physarum_lite_glfw.cpp`. `physarum_lite_glfw --selftest` runs the
same move/deposit/turning checks as `physarum_glfw`; `--pace N` and `--draw-cap N` exercise the
frame pacing and the scale-up path, and `--clock-style N --time HH:MM:SS --fonts fonts.json` runs
a clock mode against a fixed time. Settings come from `tools/make_settings_physarum_lite.py`.
Add-on folder: `../screensaver.physarum.lite.armv7`.

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

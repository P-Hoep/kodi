# Sand Clock (OpenGL)

A C++ / OpenGL port of `../screensaver.sandclock`. The Python add-on stays as it is.

This project also builds the other GPU add-ons: Liquid Clock, the Cellular Automata family
(full, Lite and 3D), Physarum and Physarum Lite, Tetris AI (OpenGL) and the Physarum music
visualisation. Each is a separate CMake target and Kodi add-on, sharing the GL-free core and the
shader dialect layer described here.

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

## Physarum Visualisation

Physarum Lite as a music visualisation, published as its own add-on: the same four-pass agent
model, with no clock and no timers, but Kodi hands it the track's samples and the simulation
listens. It is a `xbmc.player.musicviz` add-on, not a screensaver, so it is chosen under
**Settings → Player → Music → Visualisation** (or from the music OSD) and it starts and stops with
each track.

An analyser (`audio_react.*`, no GL and no Kodi) turns the 44.1 kHz stereo float stream into an
overall level, five broad bands (30–140, 140–400, 400–1200, 1200–4000, 4000–12000 Hz), a beat
impulse and a 32-band log spectrum (40 Hz to min(16 kHz, 0.45 x the sample rate)). It keeps a
1024-sample ring, applies a Hann window and an iterative radix-2 FFT, then a per-band automatic
gain, separate attack and release smoothing, and a bass-energy beat detector with a 160 ms
refractory period. When audio stops arriving (pause, or the end of a track) everything decays to
zero after 0.25 s and the scene settles.

Reactivity (one slider, 0–150%, default 70%) decides how much the music does: loud passages shorten
the step so the agents travel further, bass multiplies the deposit and slows the fade, beats add a
jolt to the jitter and widen the turn; each of these has its own switch. The draw pass also
brightens with the level, pulses the zoom on a beat, sends a ring from the centre that drags the
trail with it, drifts the hue with the music, and can draw the spectrum as bars along the bottom or
as a ring around the edge (bars by default). The analyser's sensitivity sets the automatic gain, so
quiet tracks still move the picture.

Files: `physarum_audio.hpp` (settings, trail sizes, spectrum styles), `physarum_audio.cpp` (the
audio-to-params mapping), `physarum_audio_app.*` (shaders, targets and the draw additions),
`kodi_physarum_audio.cpp` (the `CInstanceVisualization`), `main_physarum_audio_glfw.cpp` (the
harness, with a synthetic 120 bpm track). `physarum_audio_glfw --selftest` checks the analyser
(tone, beat count, silence decay, reactivity) and renders 240 frames of the synthetic track;
`--silent`, `--bpm N`, `--reactivity N`, `--sensitivity N`, `--spectrum 0|1|2`, `--beat-zoom N`,
`--beat-wave N`, `--no-react-speed|trails|beat|colour`, `--rgba8` and `--draw-cap N` exercise the
rest. Settings come from `tools/make_settings_physarum_audio.py`, which reuses the Lite lists
(without "From the clock digits") and adds the Music category. Add-on folders:
`../visualization.physarum.lite` (macOS universal dylib and Android arm64 library) and
`../visualization.physarum.lite.armv7` (32-bit Android).

The libraries are built from the `visualization.physarum.lite` module in `build-uni`,
`build-android` and `build-android32` with the commands above and committed in those folders. It
was run in Kodi 21.1 on macOS: the instance starts and stops with each track, the log reports about
110 steps/s and the analyser's level, bass and beat, and the picture reacts to the test track.

## Cellular Automata 3D

The 2D cellular automata taken into a cube: an N x N x N volume of voxels running Life-like rules
on all 26 neighbours (faces, edges and corners), drawn by ray marching, with no clock. Published
as its own add-on for 32-bit Android boxes: `../screensaver.automata3d.armv7`.

OpenGL ES 2.0 has no 3D textures, so the volume lives in a 2D RGBA8 texture as N slices laid
eight to a row, each slice surrounded by a one-cell border. The borders are filled with the
wrapped opposite face, so the update shader (one fragment pass per generation) reads 26 fixed
offsets with no wrap arithmetic and no branches; the birth/survive sets are one 32 x 1 RGBA LUT
sampled with `NEAREST`. Without wrapping the border is dead, which is exactly an open edge. The
draw pass is a ray-box slab through the volume, stepping at 0.75 of a cell and stopping at the
first living voxel, with the face normal taken from the nearest cell side, one directional light,
depth fog and an optional glow sample. The scene is drawn at a capped resolution and scaled up
once, because the raymarch is the expensive part.

Nine presets set a whole look (rule, cube, starting pattern, colour mode and palette, glow,
background, screen effect, camera and closeness) and the settings offer them one by one or as
"Rotate through the presets", which shows them in a shuffled order and changes on a timer of 15 s
to 5 min. A preset never touches speed, draw resolution, sparks or the restart timers, so it
cannot make a weak device stutter; a rotation rebuilds the GL objects (shader compile and
allocations included) between presets. Two camera modes put the eye inside the volume (drifting or
tumbling) at a wider field of view, and the Endless cube option, with wrapping on, repeats the
volume for ever instead of drawing a box: cell lookups are taken modulo the grid and the view is
limited by fog rather than by a wall. In a truly periodic world there is no outside, so inside is
how the endless mode is meant to be seen.

Files: `voxel.*` (rules, atlas, starting patterns, presets, the CPU reference, no GL),
`voxel_app.*` (shaders, textures, camera, rotation), `kodi_voxel.cpp`,
`main_voxel_glfw.cpp`; the rule, cube, start, colour, camera and preset lists come from
`tools/make_settings_voxel.py`, which writes both the Kodi settings and `src/voxel_tables.hpp`.
`voxel_glfw --selftest` compares the GPU updates with the CPU reference for every rule with and
without wrapping, and builds and draws every preset; `--dump-shaders DIR` writes the update, draw
and present shaders for the flags given, which `glslangValidator` checks as GLSL ES 1.00 and as the
core profile before an Android build (1,272 files, no failures). On an Apple M2 at 2560 x 1440 with
the automatic 360p draw cap: 0.59 ms a frame for the default, 0.63 with the inside camera, 1.22
for the dense Inside the Torus preset and 1.58 for the endless cube (no box to clip the march
against). The 32-bit library is built in `build-android32` with the flags above and stripped with
`llvm-strip --strip-unneeded`, and the built `screensaver.automata3d.armv7.so` is committed in the
add-on folder, as with the Lite add-ons. It was run in Kodi 21.1 on macOS (a universal dylib from
the same sources) with the presets (including Inside the Torus), from inside the cube and with the
endless cube on; the settings, screenshots and a 15 s preset rotation were checked in the harness,
where rotation can be observed without Kodi restarting the screensaver after each screenshot.

## Tetris AI (OpenGL)

The Python `../screensaver.tetris` screensaver ported to the same native renderer, because Kodi's
image-control animation makes the Python version move in cell-sized steps. The engine is a
straight port (`src/tetris.*`: 18 rows, the column count from the block size, the seven-bag, the
Guideline rotations, the El-Tetris placement search, the score and level, the fixed block-clock
cells, settle/row-clear bitmasks), with no Kodi or GL in it, and `tests/test_tetris.cpp` checks it.
`src/tetris_app.*` draws everything: a rounded-tile SDF shader for the blocks, the background
gradient, veil, border and vignette, and a 5 x 7 bitmap font atlas for the HUD, all in a few
textured batches.

The active piece is the point. It moves at sub-pixel positions along eased curves (a smoothstep
on the slide and the fall), not one cell per frame, and the four phases of a move (think, slide,
drop, flash, fall) run off a continuous clock, so a 60/90/120 Hz display gets 60/90/120 distinct
intermediate positions. A drop lands exactly on the ghost, line clears flash twice for 0.24 s
and collapse into place, and when the block clock changes, a piece left resting on a vanishing
digit slides down into the gap.

Settings, defaults and option indices are generated from the Python add-on's table by
`tools/make_settings_tetris_gl.py`, so both add-ons have the same 25 settings. The test window is
`tetris_glfw` (`tetris_glfw_core` on macOS), with `--skill --speed --start --scheme --block
--no-grid --no-hud --no-clock --clock-style --clock-seconds --24h --floating --time --seed
--shot out.ppm --shot-after SECONDS` and the rest. Add-on folders: `../screensaver.tetris.gl`
(macOS universal dylib and Android arm64) and `../screensaver.tetris.gl.armv7` (32-bit Android
arms). Both are built here in `build-uni` and `build-android` / `build-android32` from the
`screensaver.tetris.gl` module and the libraries are committed in those folders.

## Particle Life (OpenGL)

A native port of Hunar Ahmad's Particle Life: each pair of species has an attraction or repulsion
force, and thousands of particles self-organise into cells, worms, membranes and rings. Unlike the
original all-pairs demo, the simulation is a separate GL-free core (`src/particle_life.*`) with a
uniform neighbour grid rebuilt each step by a counting sort, so a step costs the particles plus the
pairs inside the interaction radius rather than every possible pair; `tests/test_particle_life.cpp`
checks the grid forces against a brute-force sum, the wrap-aware interpolation, the matrix parsing
and the preset tables. Ten preset matrices come from the original "interesting models"; custom text
matrices and completely random rules are first-class settings.

The physics deliberately mirrors the original rather than smoothing it: every neighbour inside a
pair's radius contributes a constant-magnitude `dx / distance` force (no distance falloff and no
invented short-range core), each pair has its own radius from the model file, and the simulation
runs the original's sequential in-place update — one `interaction()` per ordered species pair,
applying viscosity and moving the subject group before the next pass. Summing all forces and
integrating once looks similar for a second and then collapses into static clumps; the sequential
update is what keeps the original alive for minutes. The original's red-row bug (red's outgoing
forces all using the red-red power) is intentionally not reproduced.

`src/particle_life_app.*` draws it with point sprites in two passes (a broad dim halo and a bright
core) into an offscreen target that fades itself for trails. Both passes use premultiplied "over"
blending, because additive accumulation in an 8-bit target saturates every channel to white; the
present pass scales the capped target up with a hue-preserving tone map, a vignette and dither.
Positions are interpolated between simulation steps, so a 30 steps/s simulation still moves at
display rate. The settings table lives in `src/particle_life_tables.hpp`; the setting ids
and labels are generated by `tools/make_settings_particle_life.py`.

An optional camera moves the view rather than the particles. A screensaver has no input, so it is
a deterministic, slow drift: two sine waves with different periods move the centre around the
torus, and a third drives a zoom that drifts in and out. The vertex shader takes the shortest
wrapped offset from the camera centre, so a pan crosses the wrap seam without a visible edge; the
point size is scaled by the zoom so particles keep their size relative to the scene. Camera mode
(still, slow pan, pan and zoom, zoom) and its zoom and speed are settings; the camera never
changes the simulation. The accumulation target keeps its trails, so a moving camera leaves brief
motion streaks — lower the trail setting if you prefer a cleaner view.

The test window is `particle_life_glfw` (`particle_life_glfw_core` on macOS), with
`--preset --custom "a,b,..." --random --species --particles --radius --force --friction --speed
--no-wrap --start --palette --mode --size --glow --trail --bg --dim --draw --camera
--camera-zoom --camera-speed --vary --restart --evolve --seed --shot --shot-after --selftest
--bench --simulate`. Add-on folders:
`../screensaver.particlelife.gl` (macOS universal dylib and Android arm64) and
`../screensaver.particlelife.gl.armv7` (32-bit Android), built from the
`screensaver.particlelife.gl` module in `build-uni`, `build-android` and `build-android32`.

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
`tools/make_repo.py` publishes them in the Kodi repository. Rebuild and recopy them after code
changes. The 32-bit Android build (armeabi-v7a) is committed as
`../screensaver.sandclock.gl.armv7/screensaver.sandclock.gl.armv7.so`, built with
`-DANDROID_ABI=armeabi-v7a` and the same flags.

Shader dialects: GLES 2 (`-DSANDCLOCK_GLES=ON`), desktop GL 2.1 and the 3.2 core profile (macOS,
automatic; needs a VAO).

## Known limitations

- Linux (desktop GL) and Windows (ANGLE / GLES) builds have not been run on a device. macOS and
  Android have.
- Time is a float in the shader. Fine for hours; rebase `born` and `now` for sessions of days.

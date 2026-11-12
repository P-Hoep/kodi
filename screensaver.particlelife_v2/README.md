# particlelife_v2 - Kodi screensaver

Binary (C++) Kodi screensaver port of the openFrameworks "Particle Life" app.
Four colours of particles attract/repel under random rules; the rules are
re-rolled every N seconds (default 60) so it never gets stale.

## What changed vs. the openFrameworks app
- No GUI panel; everything is in the addon settings (particles per colour,
  steps/sec, re-roll interval, viscosity, force strength, range, wall repel,
  hard bounds, "evolve", point size).
- Physics is the same loop (16 group pairs per step, viscosity/wall repel applied
  per pair), but neighbour search uses a uniform grid instead of all-pairs, so
  1000 particles per colour costs ~1.6 ms/step on a desktop CPU.
- The original passed `powerSliderRR` for every red interaction (RR/RG/RY/RW);
  this port uses the matching RG/RY/RW values. One-line change in
  `Simulation::Step()` if you want the old behaviour back.
- Fixed 60 steps/sec timestep instead of "as fast as the GPU goes".
- Simulation space is 900 px high (the original's scale), width follows the
  screen aspect ratio; point size scales with resolution.
- Dropped: save/load model dialogs, motion-blur toggle (needs a persistent
  framebuffer, not guaranteed in a Kodi screensaver).

## Build (Linux, kodi-addon-dev installed)
    mkdir build && cd build
    cmake -DCMAKE_BUILD_TYPE=Release ..
    make
Or drop this folder next to Kodi's `cmake/addons` tree and build with
`-DADDONS_TO_BUILD=screensaver.particlelife_v2` as described in Kodi's addon
build docs. The result must match your Kodi version and platform (GL vs GLES).
The addon targets GL/GLES (Linux, macOS, Android, LibreELEC); Windows (DX11)
is not covered.

## Test the simulation alone (no Kodi needed)
    g++ -O2 -std=c++17 test/sim_test.cpp -o sim_test && ./sim_test

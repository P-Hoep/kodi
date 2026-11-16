# Kodi AI Arcade: Simplified Spec

A Kodi screensaver that picks a NES ROM from a folder, teaches itself to play it with no human input, and shows the result. Give it ROMs, watch it.

## 1. What it does

1. On activation, pick a ROM from the configured folder.
2. Find where gameplay starts, explore the game, discover what "progress" means from RAM, then evolve NEAT controllers against that objective.
3. Show the best known play fullscreen with a small HUD.
4. Save everything per ROM. Next time that ROM is picked, resume.
5. Stop instantly on user input.

No demos, no per-game profiles, no external processes, no Python, no network.

**Cut from the original spec:** pixel-only fitness, game profiles, hybrid modes, CRT shaders, showcase mode, audio, FDS/UNIF, ARM/Fire TV. Add later if wanted.

## 2. Stack

- Kodi native C++ screensaver addon (`kodi::addon::CInstanceScreensaver`), C++17, CMake.
- **Emulator: Nestopia core, compiled in, using its class-based API** (`Nes::Api::Emulator`, `Machine`, `Video`, `Input`, `Cartridge`). Do not use the libretro wrapper: libretro cores keep global state, so you cannot run two instances in one process, and this design needs two (training and display). Verify early that two `Emulator` objects run independently.
- Own NEAT implementation (about 600 lines), no dependency.
- JSON via nlohmann/json, SHA-1 via a small header, zlib for savestate compression.
- Target: Linux x86-64 desktop Kodi first.

## 3. ROM handling (exact)

**Settings:** ROM folder, recursive (default on).

**Scan at start:**

- Accept `.nes` only.
- Validate: first 4 bytes are `4E 45 53 1A` (iNES header), file size at least 16 + PRG size (header byte 4 × 16 KB) + CHR size (byte 5 × 8 KB).
- **ROM ID = SHA-1 of the file contents after the 16-byte header** (PRG + CHR). This is stable across header-only edits.
- Try loading each new ROM once in Nestopia. If it fails (unsupported mapper), record `bad: true` in its `meta.json` and skip it.

**Selection:**

- Exclude the last 3 played ROMs (fewer if the library is small).
- Weight each remaining ROM by `1 / (1 + hours_trained)`. Pick by weighted random.
- One ROM per screensaver activation. Optional setting: switch ROM every N minutes (default 0 = never).

**Storage:** `userdata/addon_data/screensaver.aiarcade/<rom_id>/`

| File | Contents |
| --- | --- |
| `meta.json` | title (from filename), hours\_trained, last\_played, bad flag, phase, schema\_version |
| `start.state` | savestate at start of gameplay |
| `archive.bin` | exploration archive (zlib) |
| `objectives.json` | discovered objectives |
| `neat.bin` | population, species, innovation table, generation, RNG state |
| `champion.bin` | best genome |

All writes go to a temp file, then atomic rename. Autosave every 5 minutes, after a new champion, and in `Stop()`. A corrupt or version-mismatched file is ignored and that stage restarts.

## 4. Per-ROM pipeline

Phase order: FIND\_GAMEPLAY, EXPLORE, LEARN\_OBJECTIVES, EVOLVE. EVOLVE re-runs LEARN\_OBJECTIVES periodically.

### 4.1 FIND\_GAMEPLAY (finds `start.state`)

Goal: get past title screens and menus without knowing the game.

- Run from power-on. Every frame choose input: Start pressed for 5 frames every 90 frames, A pressed randomly (10% of frames), otherwise random motif play (see 4.2).
- Every 120 frames run an **input-sensitivity probe**: save state; branch 1 runs 60 frames with no input; restore; branch 2 runs 60 frames holding Right+A; compare the 2 KB RAM of both branches and count differing bytes.
- **"Live" = at least 10 differing bytes on 3 consecutive probes.** Title screens and cutscenes mostly ignore input; gameplay does not.
- On the first live probe, save the state as `start.state` and store its RAM as `start_ram`.
- Fallback: if no probe is live after 5 minutes of emulated time (about 18,000 frames), use the state from the probe with the highest difference count.

### 4.2 EXPLORE (Go-Explore archive)

NES emulation is deterministic and savestates are cheap, so use an archive of states.

**Cell key:** downscale the 256×240 frame to 11×8 grayscale, quantize each pixel to 8 levels, hash the 88 values. Different key means a different cell.

**Archive entry:** cell key, compressed savestate, 2 KB RAM snapshot, depth (number of motifs from `start.state`), visit count, parent cell. **Cap: 1500 entries.** When full, evict the entry with the most visits that is not an ancestor of the deepest cell.

**Loop (on the training thread):**

1. Pick a cell with weight `1 / sqrt(visits + 1)`, plus a bonus of +1 if it was added in the last 100 iterations.
2. Restore its savestate. Increment `visits`.
3. Play 10 random motifs. A **motif** is a button set held for a random 4 to 30 frames. Button sets: `{R}`, `{L}`, `{R,A}`, `{R,B}`, `{R,A,B}`, `{L,A}`, `{A}`, `{B}`, `{U}`, `{D}`, `{}`. Weights: Right-containing sets ×3, others ×1.
4. After each motif compute the cell key. If new, add it (depth = parent depth + 1).

Run at least 10 minutes of emulated time or until the archive has 300 cells, whichever comes later, then move on. It continues in the background later (4.5).

### 4.3 LEARN\_OBJECTIVES (discover "progress" from RAM, unsupervised)

Input: all archive entries (RAM snapshot + depth).

**Step 1, drop constants.** Remove bytes with fewer than 8 distinct values across the archive.

**Step 2, drop clocks (counterfactual test).** Pick 50 random archive states. For each, run 30 frames twice from the same state with two different random input sequences. A byte is **input-dependent** if its end value differs between the two runs in at least 5% of the 50 tests. Keep only input-dependent bytes. Frame counters, timers and RNG bytes change identically regardless of input and get removed.

**Step 3, candidates.** Each remaining byte is a candidate. Also add 16-bit candidates for every address pair (a, a+1), both byte orders, when at least one byte is input-dependent.

**Step 4, score by progress.** For each candidate compute the **Spearman rank correlation between its value and archive depth**. Keep candidates with rho ≥ 0.30 (positive only, so countdown timers drop out).

**Step 5, select.** Sort by rho, then drop any candidate whose value series has |correlation| > 0.98 with a higher-ranked one. Keep the top 8 as the objective set. Each stores its address(es), its sorted archive values (for percentile lookup), and weight `w_i = rho_i / sum(rho)`.

**Value of a state:**

```
Value(state) = sum_i  w_i * percentile_rank_i(state)     // 0..1
```

`percentile_rank_i` is the fraction of archive values for objective i that are below the state's value, so Value is normalized and no single score byte dominates. If no candidate passes, Value falls back to **cell novelty only** (section 4.4 fitness with the Value terms set to 0), and the HUD says "exploring".

**Death detection (unsupervised):** let `sim(state)` be the fraction of the 2048 RAM bytes equal to `start_ram`. A **death event** is when `sim` rises by at least 0.20 within 30 frames while Value drops by at least 20% of the episode's max Value. It ends the episode.

### 4.4 EVOLVE (NEAT)

**Inputs (about 265):**

- Screen: 16×15 grayscale grid, values 0 to 1 (240 inputs).
- The bytes used by the 8 objectives, each divided by 255 (up to 16 inputs).
- Previous action: the 8 outputs from the last decision.
- Bias = 1.

**Outputs (8):** A, B, Select, Start, Up, Down, Left, Right. A button is pressed when its sigmoid output is above 0.5. Network is evaluated every **4th frame**; the buttons are held for the other 3.

**Network:** feed-forward only (no recurrent links). Hidden activation: sigmoid with slope 4.9. Initial genomes: no hidden nodes, each output connected to a random 10% of inputs (plus bias), weights uniform in \[-1, 1\].

**Population:** 100 (setting 25 to 300).

**Episode:**

- Start state: for each generation, **all genomes use the same start**. With 50% probability that is `start.state`; otherwise a random cell from the top 10% of archive cells by Value. This pushes learning past the first screen.
- End when any occurs: a death event (4.3), 4000 frames elapsed, or no new max Value in 600 frames.

**Fitness:**

```
fitness = 100 * maxValue + 20 * finalValue + 0.25 * min(newCells, 50) / 50 * 100
```

`newCells` is the number of archive cell keys the genome reached that are not in the archive yet (novelty, weight 0.25). New cells are also inserted into the archive, so the archive keeps growing during evolution.

**NEAT parameters:**

| Parameter | Value |
| --- | --- |
| Compatibility c1, c2, c3 | 1.0, 1.0, 0.4 |
| Compatibility threshold | 3.0, adjusted ±0.3 per generation to target 8 to 12 species |
| Weight mutation | 80% of genomes; each weight perturbed N(0, 0.2) with 90% chance, else replaced uniform \[-1, 1\] |
| Add connection | 5% |
| Add node | 3% (split a connection: old weight → disabled, in-link weight 1.0, out-link weight old) |
| Toggle enable | 1% |
| Crossover | 75% of offspring; matching genes random parent, disabled gene stays disabled with 75% chance |
| Interspecies mating | 0.1% |
| Survival cutoff | top 20% of each species breed |
| Elitism | best genome of every species with 5 or more members copied unchanged |
| Species stagnation | removed after 15 generations without improvement, but the top 2 species are always kept |
| Fitness sharing | adjusted fitness = fitness / species size |
| Innovation numbers | global table, reused for identical (in, out) pairs within a generation |

**Champion:** best genome by fitness ever evaluated in the current objective set. It is **re-scored every time objectives are re-learned** (Value changes when objectives change), and the population is re-evaluated.

### 4.5 Re-learning objectives

Exploration keeps adding cells during EVOLVE. Re-run LEARN\_OBJECTIVES every 20 generations, or sooner when the deepest archive depth grows by 25%. Objectives sharpen as the agent gets deeper. Keep the previous objective set and only switch if the new set's top objective has a higher rho.

## 5. Threads and emulator instances

| Thread | Does | Rate |
| --- | --- | --- |
| Kodi render thread | uploads latest display frame as a texture, draws HUD in `Render()` | 60 fps |
| Display thread | owns emulator instance #1; plays champion from `start.state` in real time, loops on death or after 4000 frames | 60 fps |
| Training thread(s) | each owns its own emulator instance; runs phases 4.1 to 4.4 | as fast as allowed |

- Default 1 training thread; setting up to cores minus 1. Evaluate genomes in parallel when more than one.
- CPU cap setting (default 60% of one core per training thread) via sleeping between batches.
- Shared state is published as immutable snapshots under a mutex: latest display frame, champion genome copy, stats struct. The render thread never touches genomes or emulators.
- Atomic stop flag checked every frame in every thread. `Stop()` signals, joins, saves, returns.
- During FIND\_GAMEPLAY, EXPLORE and LEARN, the display thread restores the deepest archive cell and plays random motifs live, with the HUD labelled "exploring".

Expected speed: Nestopia runs on the order of 1000 frames per second per core on a desktop. A generation of 100 genomes up to 4000 frames each is up to 400k frames, so roughly 3 to 10 minutes per generation on one thread after early terminations. Expect several hours of idle time before a game shows clear progress, and many games will show none.

## 6. Rendering and HUD

- Frame: 256×240 RGBA texture, uploaded once per display frame, scaled to fullscreen with nearest-neighbor, aspect preserved (letterbox/pillarbox).
- HUD (small, bottom of screen, embedded 8×8 bitmap font as a texture): ROM title, phase (finding gameplay / exploring / learning / evolving), generation, best fitness, species count, training hours, archive size.
- Fitness graph: best and average fitness per generation, last 100 generations, drawn as a line strip in the corner.
- HUD toggle in settings.

## 7. Settings (Kodi `settings.xml`)

ROM folder; recursive scan; training threads; CPU cap per thread; population size; HUD on/off; switch ROM every N minutes; a "reset learning for all ROMs" action.

## 8. Build order

1. **M1:** addon loads, one hard-coded ROM runs on the display thread and renders fullscreen, exits cleanly. Confirm two Nestopia instances run side by side.
2. **M2:** ROM scan, hashing, selection, `start.state` discovery (4.1).
3. **M3:** Go-Explore archive (4.2) with the display showing exploration.
4. **M4:** objective learner (4.3). Log the discovered objectives and their rho per ROM. Check by hand that it finds x-position or score in a side-scroller.
5. **M5:** NEAT (4.4) and champion display.
6. **M6:** persistence, HUD, graph, CPU cap, settings.

## 9. Acceptance

- Installs and runs as a screensaver on Linux x86-64 Kodi, stops within one frame of input.
- Given a folder of ROMs with no setup, it reaches gameplay on most supported games without help.
- On a side-scrolling platformer test ROM, discovered objectives rank an x-position byte (or 16-bit pair) in the top 3, and champion Value improves over the first 50 generations.
- State survives Kodi restart per ROM, and a deleted or corrupt file does not crash it.
- Memory stays bounded over a 12-hour run (archive cap, population cap).

## 10. Known limits

- Works best on side-scrollers and shooters. Puzzle, RPG and menu-heavy games will mostly look like exploration.
- The frame-sensitivity probe can misfire on games with attract-mode demos. The fallback in 4.1 covers the worst case.
- Scroll counters that wrap at 255 can confuse the rank correlation. The 16-bit pair candidates and the depth correlation reduce this but do not remove it.
- A wrong objective can steer exploration. Keeping 8 objectives plus novelty limits the damage.
- Do not promise every ROM learns. The HUD should show plainly when it is only exploring.

# EvolveLife: Kodi Screensaver Specification

*An artificial-life screensaver where strange, glowing creatures evolve their bodies and brains to move through a world.*

Version 2.0 (cleaned-up spec). Language: C++17. Build: CMake. Target: Kodi 21+ binary screensaver addon.

## 1. Vision

EvolveLife is a living-room aquarium for evolution. The viewer sees a population of soft, luminous, organic creatures attempting a task (reach a beacon, cross a gap, leap a chasm, glide between islands). Early generations flail and topple. Within minutes the bodies and motion visibly improve, and because every run draws its own random creatures and goals, no two sessions end up in the same place.

The screen is also an **evolution show**. While creatures evolve, it continuously presents interesting information about what is happening: live neural activity, how this generation compares with the first, family trees, species maps, hall-of-fame replays, spectacular failures, run totals and plain-language commentary. A viewer can glance up and learn something about the run, or just enjoy the creatures.

**Design pillars**

1. **Beautiful first.** On a TV across the room, it must look like a piece of generative art even when evolution is going badly.
2. **Emergent, never scripted.** No authored gaits or morphologies. Everything moving was evolved.
3. **Legible evolution.** A viewer should be able to *see* species, progress, and champions at a glance, and can read the story of the run when they want to: the screen continuously shows interesting facts, charts and commentary about what is evolving.
4. **Good Kodi citizen.** Bounded CPU/GPU/memory, instant exit, smooth on Raspberry Pi 4 and Fire Stick class hardware (the supported floor) up to a desktop HTPC.
5. **Random.** Every run starts from a fresh random seed with very random creatures and very random goals, unless settings pin something. Nothing is saved between runs.

## 2. Key Decisions (resolving ambiguities in the original draft)

| Topic | Decision | Why |
| --- | --- | --- |
| Dimensionality | **2D physics (Box2D), 2.5D rendering.** Creatures are extruded/rounded 2D shapes rendered as lit 3D meshes with parallax depth layers. | Box2D is 2D only. 2.5D gives depth, lighting, and soft shadows at a fraction of the cost of 3D physics. |
| Graphics API | **OpenGL ES 3.0 baseline** (also valid on desktop GL 3.3 compat). | Kodi runs on GLES (Android, Fire TV, Pi 4) and GL (Linux, macOS, Windows). One shader set, thin abstraction. |
| Physics lib | **Box2D 2.4.x** (MIT), pinned. Box2D 3.x only if its API is stable at implementation time. | Mature; simple joints, motors, sensors. |
| Neural evolution | **MultiNEAT** (pin a specific commit/release). Verify the "MultiNEAT2" fork's maintenance and license first. | Project is LGPL-family; confirm compatibility with Kodi addon GPL distribution. Wrap behind an `INeuralEvolver` interface so it can be swapped. |
| Morphology encoding | **Directed-graph genotype with recursion and mirror symmetry** (Sims-style). | Compact, naturally produces limbs/segments, mutation-friendly, always connected by construction. |
| Evaluation | **Isolated Box2D world per creature, headless, deterministic**, run on worker threads. Display is a re-simulation of the same seed. | Thread-safe, no creature-creature collisions, replays and showcase come for free. |
| Cross-device determinism | Same platform/build only. Replays store genome + seed + build tag. | Float determinism across CPUs/compilers is not guaranteed. |
| Diversity | **Species (NEAT) plus a in-session MAP-Elites style morphology grid.** | Prevents convergence on one body plan. |
| UI | **Information-rich by default.** Live data, brain activity and commentary are on screen, with a clean mode available. | Screensaver should be art that also tells the story of the run. |

## 3. Architecture

The simulation core is a plain C++ library with **no Kodi or OpenGL dependencies**. The Kodi addon is a thin shell around it. This allows a headless CLI for tuning and tests.

```
evolvelife/
  core/        evolution, morphology, creature, physics, fitness, environment, goals
  render/      GLES renderer, camera, effects, HUD (depends on core data only)
  addon/       Kodi shell: lifecycle, settings, GL context glue
  tools/       headless trainer CLI, genome inspector, replay exporter
  data/        shaders, palettes
  tests/
```

### 3.1 Modules

| Module | Responsibility |
| --- | --- |
| `ScreensaverShell` (addon) | Kodi `CInstanceScreensaver` lifecycle (`Start`, `Render`, `Stop`), settings read, GL context handoff, clean shutdown. |
| `EvolutionManager` | Population, selection, reproduction, generation scheduling, random goal epochs, in-session history. |
| `MorphologyGA` | Genome init, mutation, crossover, validation, distance metric, descriptor extraction. |
| `NeuralEvolver` | Adapter over MultiNEAT: genome creation, mutation, crossover, speciation, phenotype build. |
| `CreatureFactory` | Morphology genome to Box2D bodies/joints and a render mesh description. |
| `ControllerRuntime` | Sensor gathering, network activation, actuator output clamping and masking, activation snapshots for the neural view. |
| `PhysicsWorld` | Fixed-step Box2D wrapper, aero forces, wind, contact reporting. |
| `FitnessEvaluator` | Objective scoring, anti-exploit checks, per-trial aggregation. |
| `EnvironmentGenerator` | Seeded terrain, obstacles, targets, bounded randomization, solvability guarantees. |
| `EvalScheduler` | Worker thread pool, job queue, time budgets, priorities. |
| `Archive` | In-session MAP-Elites grid, session champions, lineage (memory only). |
| Telemetry | Lock-free event bus, rolling in-memory stats, event ticker feed, optional Kodi log and JSONL file sinks. |
| InsightRenderer | Neural activity view, sparklines, ticker, title cards, info scene rendering, panel layout and burn-in drift. |
| InsightDirector | Chooses info scenes by priority and freshness, builds card data from telemetry, writes template commentary, and schedules replays with the Director. |
| `Renderer` / `Camera` / `Director` | Drawing, camera moves, generation-transition choreography. |

### 3.2 Threading model

- **Render thread** (Kodi's): draws interpolated snapshots. Never waits on evaluation.
- **Sim thread**: advances the visible "stage" worlds at fixed 60 Hz physics with display interpolation.
- **Eval workers**: `min(hardware_threads - 1, profile_cap)` threads at below-normal priority, headless, faster than real time. Always leave a core for Kodi.
- Communication through lock-free or double-buffered snapshots. No shared Box2D worlds across threads.
- On `Stop()`: signal cancel, join workers within a short bound (target under 200 ms), free GL resources on the render thread.

## 4. The Individual

An individual is a single inheritable unit. Bodies and brains are never recombined across unrelated parents unless an explicit experimental flag is set.

```cpp
struct Individual {
    uint64_t id, parent_a, parent_b;
    uint32_t generation;
    uint32_t schema_version;
    MorphologyGenome body;     // custom GA
    NEAT::Genome     brain;    // MultiNEAT
    VisualGenes      look;     // drifts neutrally, not fitness-driven
    uint64_t         eval_seed_base;
    Scores           scores;   // fitness, novelty, descriptors, per-objective
};
```

All MultiNEAT API calls must be validated against the pinned version before the interfaces are frozen.

## 5. Morphology

### 5.1 Genotype

A directed graph of **body-part nodes** and **attachment edges**:

- **Node**: shape (capsule, rounded box, ellipse-polygon, wedge/fin), width/height, density, friction, and visual parameters.
- **Edge**: parent node, attach point on the parent's perimeter (parameterized angle), child orientation, joint type, angular limits, motor strength and speed caps, **repeat count** (0..R, with taper scale) and **mirror flag**.
- A single root node. Cycles are allowed only through bounded recursion, so the expanded body is a tree.

### 5.2 Phenotype segment roles

Roles are inferred from structure and parameters, never assigned: torso, limb segments, feet (segments with contact sensors), tail, wing/fin surfaces (thin segments with aerodynamic response), antennae/appendages. The initial release supports **revolute joints only** (plus an optional fixed joint), with other joint types as stretch goals.

### 5.3 Hard constraints (enforced in `CreatureFactory`)

- Max segments (profile-dependent: Low 8, Balanced 12, High 16)
- Max total mass and max bounding box
- Min segment size and min joint range (avoids degenerate or tunneling parts)
- Center of mass within a sane region of the support polygon at spawn
- No overlap at spawn (resolved by deterministic separation or rejected)
- Connected by construction
- Invalid offspring are **repaired first, then rejected and re-rolled**, with a retry cap and a counter exposed in debug stats. Never crash or spawn an unstable body.

### 5.4 Variation operators

- **Parameter mutation**: Gaussian perturbation of sizes, densities, limits, strengths, attach angles.
- **Structural mutation**: add node, remove leaf, duplicate subtree, change repeat count, toggle mirror, change shape, reattach subtree.
- **Crossover**: subtree swap between parents with graph-aware alignment; parameter blend for matched nodes.
- **Growth cost pressure**: mild mass/segment cost in fitness so bodies do not bloat.

### 5.5 Morphology distance and descriptors

- **Distance**: tree edit distance on the expanded graph plus normalized parameter distance (used for niching and archive deduplication).
- **Descriptors** (for MAP-Elites and visual species identity): limb count, body aspect ratio, total mass bucket, wing area fraction, tail length.

## 6. Neural Controller

### 6.1 Fixed-size interface with masking

The interface is constant so brains remain inheritable when bodies change. Joint slots are assigned in canonical depth-first order of the expanded body, so structurally similar bodies map similar slots. Mirrored limbs get adjacent slots.

**Inputs** (all normalized to \[-1, 1\]; unused slots are zero):

- Per joint slot (J\_max = 16): angle, angular velocity
- Per contact slot (up to 8 feet/segments): ground contact flag
- Root body: orientation (sin, cos), angular velocity, linear velocity (x, y)
- Objective: direction to target (unit vector), distance (squashed), relative target height
- Clock oscillators: 2 to 3 sin/cos pairs at evolvable-free fixed frequencies (gives rhythm without scripting gaits)
- Energy remaining; bias
- Objective ID one-hot (optional, so one brain can switch behaviors across epochs)
- Wing/airflow: local airspeed per wing slot (Low profile may disable)

**Outputs** (tanh, clamped):

- Per joint slot: target position (servo style), mapped within the joint limits
- Per joint slot: effort scale (torque fraction), which feeds the energy cost
- Global: jump/crouch impulse trigger (consumed only by bodies with suitable feet), wing flap bias

Masked slots are ignored and not penalized. Unused outputs have no cost.

### 6.2 Timing

Physics steps at fixed 60 Hz. The controller runs every 2nd step (30 Hz) with held outputs. Both rates are constants, never frame-time dependent.

### 6.3 Initialization

Minimal NEAT topologies (inputs directly connected to outputs) with sparse initial connectivity, to avoid slow random-bloat starts. Recurrent connections enabled.

## 7. Physics and Environment

### 7.1 Physics rules

- Fixed timestep, bounded solver iterations, bounded velocity and joint-speed clamps
- Energy model: each unit of motor effort drains a finite budget. When empty, motors weaken. This closes energy exploits.
- **Aero model for wings/fins**: per-segment lift and drag from airspeed and angle of attack, with constant coefficients and a stall clamp. Applied as forces in Box2D. Wind is optional and per-environment.
- Water and gravity variants are optional environment modifiers (stretch goal).

### 7.2 Environments

All generated from a seed, with **solvability guarantees** (target reachable by at least one known baseline trajectory or reference check).

| Environment | Notes |
| --- | --- |
| Rolling terrain | Smooth noise heightfield. Phase 1 default. |
| Flat plains | Used for early epochs and sanity tests. |
| Obstacle course | Steps, walls, pits with bounded sizes. |
| Climb slope / cliff | Inclined surfaces with footholds. Stretch goal. |
| Floating islands | Gaps scaled to jump/glide capability bands. |
| Open sky | Altitude and distance objectives for fliers. |

### 7.3 Randomization

Per trial: slope, friction, target offset, obstacle placement, wind, within bounds. Each individual is evaluated on **K trials** (default 2, Low 1, High 3) with shared seeds across the generation so comparisons are fair. Fitness is the mean with a mild penalty for variance.

## 8. Objectives and Fitness

### 8.1 Objective types

| Objective | Core signal |
| --- | --- |
| Reach target | Net progress toward target, completion bonus, time bonus |
| Walk/run | Forward displacement, upright fraction, sustained speed |
| Jump | Peak height, horizontal distance, landing stability |
| Fly/glide | Airborne time, altitude gained, controlled descent rate, reach target |
| Cross/climb | Progress along the course, checkpoint count |

### 8.2 General form

```
fitness = w_progress * progress
        + w_goal * completion
        + w_stable * stability
        - w_energy * energy_used
        - w_growth * body_cost
        - penalties
```

Weights are per objective and live in data files, not code. Fitness is **normalized per objective** (0..1 against a rolling reference) so cross-objective archives and epoch changes remain comparable.

### 8.3 Anti-exploit rules (required)

- Net progress is measured on the target axis or course path, so circling and oscillating score zero.
- Early termination for: stuck for T seconds, fallen and not recovering, out of bounds, or NaN/explosion detected.
- Cap on rewarded speed and on single-step displacement (kills physics-glitch launches).
- Penalize sustained high-frequency motor chatter (jitter-for-propulsion).
- Contact-sensor sanity checks (body parts embedded in terrain are flagged).
- Any individual that triggers solver instability is scored zero and logged.

### 8.4 Novelty and diversity

Final selection score blends fitness with a small novelty bonus based on morphology descriptors and a behavior descriptor (e.g., path shape, duty cycle of contacts). The in-session MAP-Elites grid keeps the best creature per descriptor cell, and is the source for showcases.

## 9. Evolution Loop

### 9.1 Generation cycle

1. Build the generation's trial seeds.
2. Evaluate all individuals headlessly across the eval pool (the **stage** simultaneously replays a chosen subset live).
3. Compute fitness and novelty, update species and the archive.
4. Select parents (species-aware tournament, elitism, a small rate of fresh random immigrants).
5. Produce offspring: crossover/reproduce body, reproduce brain, apply independent mutations, repair/validate, build phenotypes.
6. Director choreographs the transition (Section 11.3).

### 9.2 Random goals

Unless a setting pins it, **goals are random**. Each epoch draws a fresh goal from a pool of parameterized templates: reach a beacon (near, far, uphill, across a gap), chase a moving beacon, travel as far as possible in a random direction, reach a random altitude, stay airborne, jump the widest chasm, cross an obstacle field, climb a wall, or glide between islands. Every draw also randomizes the world: terrain type, slope, gravity (within bounds), friction, wind, and target placement.

An epoch lasts a random 8 to 40 generations, or ends early when progress plateaus. The population carries over between epochs, so creatures adapt to the new goal rather than restarting. A goal-ID input lets one brain keep several behaviors. Every draw must pass the solvability checks in Section 7.2.

### 9.3 Pacing for viewers

A generation is about 25 to 60 s of watchable time. Because evaluation is headless and faster than real time, the stage can show the **previous** generation's champions and a varied sample while the next generation is already being evaluated. The viewer never watches a spinner.

### 9.4 Random starts

Every run begins from nothing. Generation 0 is a wide random draw of body plans (segment counts, shapes, symmetry, limb counts, wing area and scale, all sampled from broad ranges with no hand-picked starting designs) paired with minimal random brains. Each generation also injects a share of fresh random immigrants (default 5 to 10 percent) so new body plans keep appearing and no single design takes over. The first epoch uses a gentle goal so the opening minutes are watchable without a head start.

## 10. Rendering (2.5D)

### 10.1 Look

- Soft bioluminescent palette on deep, atmospheric backgrounds (dusk gradients, drifting motes, faint fog layers with parallax).
- Creatures: smooth-shaded rounded meshes generated from segment shapes, joined with metaball-like blended skin at joints (approximated with overlapping capsules plus fresnel rim lighting and subsurface-style soft shading).
- Procedural patterns (stripes, spots, gradients) from `VisualGenes`. Eyes and head details are cosmetic and optional.
- **Species = hue family.** NEAT species/lineage determines base hue so speciation is visible as color groups. Champions get a gentle halo or pulse.
- Targets are luminous beacons with a soft bloom.
- Terrain: low-poly or smooth ribbon surface with gradient shading and layered silhouettes.

### 10.2 Quality tiers

| Feature | Low | Balanced | High |
| --- | --- | --- | --- |
| Render scale | 0.5 to 0.75x | 1.0x | 1.0x (up to 4K) |
| Shadows | Blob shadows | Blob shadows | Soft projected shadows |
| Bloom | Off | Cheap single-pass | Multi-pass |
| Particles | Few | Moderate | Many |
| Parallax layers | 2 | 3 | 5 |
| Visible creatures | up to 12 | up to 24 | up to 48 |

An **adaptive quality governor** monitors frame time and steps tiers or render scale down, and cautiously up, with hysteresis, so the screensaver never stutters on weak hardware.

### 10.3 Technique notes

- Instanced rendering for repeated segments and particles; single shader program per material class.
- Pre-allocated vertex buffers; no per-frame allocation. Mesh rebuilt only when a creature appears.
- Rendering uses interpolated physics snapshots, so it is smooth regardless of sim rate.
- Only draw creatures that are on-screen. Off-screen ones are simulated headlessly.
- Use sRGB-correct blending and dithering to prevent banding on dark gradients.
- Avoid desktop-only GL features. Verify against GLES 3.0 and GL 3.3 compat.

### 10.3a Burn-in and TV friendliness

Slow global camera drift, no static high-contrast elements, and a HUD that periodically relocates. Peak brightness is capped by setting.

## 11. Camera, Direction, and Presentation

### 11.1 Camera modes

- **Follow**: tracks the current champion with critically damped smoothing and look-ahead.
- **Overview**: frames the whole stage with gentle zoom breathing.
- **Cinematic (default)**: a Director that chooses shots (wide, follow, close tracking, target reveal) on a timer or by event. Transitions are always eased, never cuts that jolt.

### 11.2 Director events

The Director responds to meaningful events: first creature to reach the beacon, a new all-time record, a successful glide, a dramatic fall and recovery. This gives the screensaver a sense of narrative. It also schedules the info scenes in 11.9 between camera shots.

### 11.3 Generation transition choreography

1. Evaluation of the visible batch ends; creatures slow to a gentle fade or settle.
2. Top performers brighten and rise slightly; losers desaturate and fade into the ground or sky.
3. A short champions showcase (2 to 3 s of the best run replay).
4. Offspring materialize from particle motes at spawn points, with a brief lineage cue (offspring inherit parent hue, with a faint trail from parents).
5. Terrain and target morph smoothly into the next seed's layout where feasible, otherwise crossfade.

No hard resets, ever.

### 11.4 Showcase mode

Optional mode, off by default for continuous evolution. Cycles through this session's greatest creatures (one per MAP-Elites cell or objective), replays their runs, and optionally displays name (procedurally generated, e.g., "Skitterwing, gen 412"), fitness, and lineage depth. Genomes remain available for further evolution.

### 11.5 Insight layer: the screensaver is also a show about evolution

Showing interesting information while evolution runs is a **core feature**, not an add-on. At any moment the screen carries something worth reading: how a brain is firing, how this generation compares with the first, which creature is the strangest, what the world is throwing at them. It is drawn as part of the scene (soft glass panels, animated charts, fading ticker lines), never as a debug window, and it is **on by default at the Rich level**.

| Level | Shows |
| --- | --- |
| Off | Clean screensaver: no text or overlays |
| Light | Event ticker and generation/goal title cards |
| Rich (default) | Neural activity view, rotating info scenes (11.9), live sparklines, commentary ticker, creature profile cards |
| Full | Everything in 11.6 to 11.9 plus histograms, lineage tree, per-creature stats, system metrics and debug counters |

Panels fade in and out, stay clear of the creature being followed, and drift slowly to avoid burn-in. Each info category can be switched off in settings. All on-screen text goes through Kodi's localization (`strings.po`) and is sized and contrasted to be readable from across a room.

### 11.6 Neural activity view

The brain of the followed creature (the champion by default) is drawn live while it moves.

- **Graph**: inputs on the left (grouped as joints, contacts, target, clock, energy), hidden nodes in the middle laid out by topological depth with a one-time force relaxation cached per genome, outputs on the right. Recurrent links draw as arcs.
- **Firing**: node size and brightness follow activation, and a node crossing a threshold flashes briefly.
- **Signals**: links are colored by sign (warm positive, cool negative) and sized by weight. A pulse travels along a link whenever its source node changes sharply.
- **Brain to body**: each output node is tied by a thin line to its joint on the creature. Driven joints glow and show an effort ring, and contact inputs light the matching feet, so the viewer can see which neuron moves which limb.
- **Evolution in view**: when a new champion appears, its new nodes and links are highlighted for a few seconds so mutations are visible. The species hue tints the graph.
- **Modes**: Corner panel (default), Anchored overlay (the graph floats beside the creature and follows it), or Off. Large brains show the strongest connections and aggregate the rest.
- **Cost model**: activations are published only for visible creatures, as quantized snapshots from `ControllerRuntime` at the 30 Hz control tick into a ring buffer, and the render thread interpolates. Headless evaluation pays nothing. Other visible creatures get a small activity halo or sparkline instead of a full graph.

### 11.7 Live data and event ticker

Everything below is collected in memory during the run. Rich shows sparklines (best and mean fitness, species count) and feeds the rotating info scenes in 11.9. Full shows all of it.

| Group | Data tracked |
| --- | --- |
| Evolution | Best, mean and median fitness per generation, fitness histogram, epoch and goal number, generations since last improvement |
| Species | Species count, sizes over time (stacked area in species hues), births and extinctions |
| Brains | Nodes and connections (mean, max), recurrent link count, mutation counts by type, champion activation entropy |
| Bodies | Segment count, mass, limb count, wing area, size distribution, morphology diversity, MAP-Elites coverage |
| Creature runs | Distance, progress, airborne time, falls, jumps, energy used, time to target |
| Goal and world | Goal parameters, terrain seed, gravity, wind, friction |
| Process | Creatures evaluated per second, simulation speed multiplier, early-termination reasons (stuck, fell, exploit caught), frame time, quality tier changes |

The **event ticker** shows short fading lines for notable moments: a new all-time best, a species born or gone extinct, the first creature to reach the beacon this epoch, a new goal drawn with its parameters, a notable structural mutation that survived (for example, wings appearing in a lineage), an exploit caught and zeroed, and quality tier changes. Full level adds the champion's lineage depth and a mini ancestry tree.

### 11.8 Telemetry and logging

- **`Telemetry` module**: fixed-size plain-data events are pushed from eval workers, `EvolutionManager` and `ControllerRuntime` into a bounded lock-free ring buffer. No heap allocation or locks on hot paths. If the buffer fills, events are dropped and counted (the count shows at Full level).
- **In-memory windows**: the last \~500 events and the last \~300 generations of stats, downsampled beyond that. Everything is bounded.
- **Kodi log sink**: Off, Summary (one line per generation and per goal change, the default) or Verbose (every notable event).
- **Session log file (off by default)**: JSON Lines under the addon profile `logs/` folder, one line per generation plus notable events, capped and rotated (for example 5 files of 2 MB). It is write-only, for the viewer's curiosity and for debugging. Evolution state is never loaded from it, so the no-persistence rule still holds.
- **Headless CLI**: can dump the full telemetry stream as CSV or JSONL for tuning runs.

### 11.9 Info scenes and cards

The Director (11.2) interleaves normal camera shots with **info scenes**: 20 to 40 second moments where one piece of information gets the stage. Scenes are chosen by priority (fresh events first), never repeat within about 10 minutes, and are always built from data the simulation actually produced. Only one card plus the ticker is on screen at a time.

| Card | What it shows |
| --- | --- |
| Creature profile | Procedural name, generation, lineage depth, body plan (segments, limbs, wings), brain size, goal results, and a computed one-line note on what makes it unusual (for example, most limbs seen this run) |
| Then and now | Split view of generation 1's best and the current best attempting the same goal, with the improvement multiple |
| Family tree | Animated ancestry of the champion with ancestor silhouettes and the mutations that mattered (wings appeared, a limb was added) |
| Species map | Live species as colored clusters in morphology space, drifting as they evolve, with births and extinctions marked |
| Brain growth | How the champion's nodes and connections grew across generations, replaying key mutations in the neural view |
| Hall of fame | This run's best creature per goal type and per body niche, with short replays |
| Fail reel | Short clips of the most spectacular failures (faceplants, tumbles, caught physics glitches) with a caption |
| Goal briefing | The current goal and world conditions (gravity, wind, terrain) as a mini diagram, and how the population is doing against it |
| Fitness landscape | Per-generation fitness distribution as a ridgeline, showing the population shifting |
| Milestones | First creature to walk, jump, glide or reach the beacon, with generation number and run time |
| Run totals | Creatures born, generations, simulated creature-hours, total distance travelled, falls, longest flight |
| Commentary | One-line narration from fixed templates filled with real numbers (for example, a six-legged crawler overtook the biped lineage in generation 87). No generated text models |
| Did you know | Short, accurate notes about real evolution, neuroevolution and speciation, shown only between scenes |

Replays are re-simulations of the stored genome and seed within the session, rendered live, so no video is recorded. Cards that need a replay queue a headless run ahead of time so scenes never wait.

## 12. Performance

### 12.1 Targets

| Profile | Target hardware | Population | Eval threads | Render |
| --- | --- | --- | --- | --- |
| Low | Pi 4 / Fire Stick (minimum supported) | 24 to 40 | 1 | 30 FPS, GLES 3.0 |
| Balanced | Typical HTPC / Shield | 60 to 100 | 2 to 3 | 60 FPS |
| High | Desktop GPU/CPU | 150 to 300 | up to cores-1 | 60 FPS, effects on |

- Stable for 8+ hours; no unbounded memory growth; flat RSS in soak tests.
- Eval pool uses a per-generation time budget. If the budget is exceeded, unevaluated individuals receive a conservative score and are re-queued rather than stalling the display.
- Object pooling for Box2D worlds and bodies, pre-sized NN activation buffers.
- Auto-detect profile at first run and expose manual override. Hardware below Raspberry Pi 4 / Fire Stick class is explicitly unsupported, so there is no GLES 2.0 fallback path. The Insight layer has a budget of about 5 percent of frame time and is the first thing the quality governor simplifies.

### 12.2 Idle behavior

On `Stop()` all workers pause or stop immediately. The addon does no background work while Kodi is not showing the screensaver (a background-evolution mode is out of scope for v1).

## 13. Session State (No Persistence)

EvolveLife keeps nothing between runs. Every screensaver start uses a brand-new random seed and a brand-new random population: no saved genomes, no elite library, no history files, and no writes to the addon profile directory by default (the optional telemetry log in Section 11.8 is the only exception).

**In-session memory only**: the current population, species state, a MAP-Elites grid of this session's best creatures (used for showcase mode and as a source of immigrants), and a short rolling stats history for the optional HUD. All of it is freed on `Stop()`.

**Why**: every viewing is different, there is no save format to version or migrate, no corruption to handle, and no storage growth. For development only, the headless tool can export a creature to a JSON file on request. This is not exposed in Kodi settings.

## 14. Kodi Integration

### 14.1 Addon structure

- `addon.xml` declaring the `kodi.screensaver` extension point, with metadata, platform support, and dependencies on the addon API
- Implemented via the Kodi C++ addon dev kit (`kodi::addon::CAddonBase`, `kodi::addon::CInstanceScreensaver`)
- `Start()` starts a fresh random simulation and creates GL objects, `Render()` is called per frame and must return quickly, `Stop()` tears down cleanly
- Handle GL context loss/recreation defensively, and never leave Kodi's GL state modified (save/restore state and bound objects)

### 14.2 Settings (`settings.xml`)

| Category | Setting |
| --- | --- |
| General | Performance profile (Auto/Low/Balanced/High), population size, simulation speed |
| Evolution | Objective mode (Random by default, or pin Walk, Run, Jump, Reach, Fly), goal change interval (Random or fixed), environment (Random or specific), creature complexity (Random or a max segment count), evolution mode (Continuous / Showcase) |
| Visuals | Visual quality override, camera mode (Cinematic/Follow/Overview), Insight level (Off/Light/Rich/Full), info card categories (profiles, then and now, family tree, species map, hall of fame, fail reel, run totals, did you know), card frequency, neural view (Off/Corner/Anchored), event ticker, color palette (Auto/Warm/Cool/Neon/Mono), brightness cap |
| Logging | Kodi log detail (Off/Summary/Verbose), write session log file (off by default) |
| Advanced | Eval threads, fixed seed (blank = new random seed every run; for debugging), debug overlay |

Settings changes apply on next screensaver start, with simple ones (HUD, camera) applying live.

### 14.3 Build and packaging

- CMake with the standard Kodi binary-addon build (`find_package(Kodi)`, `build_addon`), plus an `addon-depends` style build for third-party libs
- **Vendor and pin** Box2D, MultiNEAT, GLM via `FetchContent`/`ExternalProject`; static link; no runtime dependency installs
- Strip Python/Boost heavy bindings from MultiNEAT if possible (core C++ only). If Boost is unavoidable, isolate it and measure the size/build impact, and consider a thin fork or replacement behind `INeuralEvolver`
- CI matrix: Linux x86\_64 and aarch64, macOS (arm64/x86\_64), Windows optional, Android / Fire TV (aarch64) as a supported target
- Licensing audit documented (Kodi GPL, MultiNEAT, Box2D, asset licenses)

## 15. Testing

| Layer | Tests |
| --- | --- |
| Unit | Morphology mutate/crossover validity (fuzzed, 1M+ offspring, 0 invalid), genome copy round-trips, controller masking, fitness anti-exploit cases |
| Property | Any valid genome builds a stable physics body for 10 s with random controller input (no NaN, no explosion) |
| Determinism | Same genome + seed yields the same trajectory on the same build |
| Evolution regression | Headless trainer shows fitness improvement over N generations on the flat-walk objective (statistical threshold across seeds) |
| Performance | Frame-time and memory soak (8 h Balanced profile), quality governor behavior under throttled CPU |
| Kodi integration | Start/stop 1000 times without leaks, abrupt stop during evaluation |
| Visual | Golden screenshots per quality tier, banding checks |

## 16. Development Phases (with exit criteria)

| Phase | Scope | Exit criteria |
| --- | --- | --- |
| 0. Foundations | Repo, CMake, dependency pinning, license audit, headless CLI skeleton, MultiNEAT API validation | Library builds on Linux and macOS, Box2D + NEAT smoke test passes |
| 1. Evolving walkers | Fixed-body creatures, NN control, flat/rolling terrain, walk fitness, anti-exploit basics, telemetry bus | Fitness improves measurably over 100 generations in 5 of 5 seeds |
| 2. Coupled morphology | Graph genome, mutation/crossover/repair, fixed-size interface, niching/MAP-Elites | 0 invalid creatures in fuzz test, visibly different body plans, diversity metric stable |
| 3. Locomotion expansion | Jump, crawl-capable bodies, aero model, glide then flight, objective epochs | At least three distinct emergent strategies documented in headless runs |
| 4. Presentation | 2.5D renderer, species hues, camera/Director, transitions, Insight layer (neural activity view, live stats, event ticker, info scenes, commentary), random goal system | A 10-minute capture looks compelling with no text, 60 FPS on Balanced |
| 5. Kodi integration | Addon shell, settings, lifecycle, GL state hygiene, packaging | Installs and runs as a Kodi screensaver on Linux and macOS, clean stop |
| 6. Hardening | Quality governor, optional log sinks, soak tests, low-end profile, docs | 8 h soak stable, Pi 4 hits Low profile target, memory flat across 1,000 start/stop cycles |

## 17. Acceptance Criteria

1. Kodi activates the screensaver, and any input exits it within a fraction of a second.
2. Creatures are procedurally generated with diverse body structures (descriptor coverage metric above threshold).
3. Neural networks drive actuators; no authored gaits exist in the codebase.
4. Fitness demonstrably improves across generations per objective.
5. At least walking, crawling-style, jumping, and gliding behaviors emerge in headless runs. Powered flight is experimental and not required for release.
6. Multiple creatures render simultaneously with smooth generation transitions and no hard resets.
7. Body and brain genomes stay coupled through reproduction, verified by test.
8. Morphology evolution is implemented independently of MultiNEAT.
9. Neural controllers stay compatible with all valid morphologies.
10. Neural (species) and morphological diversity are both preserved and measurable.
11. Every run starts from a fresh random seed with random creatures and random goals unless settings pin them, and nothing is written to disk.
12. Runs for 8+ hours with bounded memory and CPU, and adapts to weaker hardware.
13. Builds and installs using Kodi's supported addon tooling.
14. Any random start looks good: even failing creatures and unlucky goals stay visually compelling. The followed creature's neural activity is visible live, alongside generation stats, notable events and rotating info scenes (creature profiles, then and now, family tree, species map, hall of fame, run totals), with an optional session log.

## 18. Engineering Constraints

- Use MultiNEAT for neural evolution and Box2D for physics. No custom NN library or physics engine.
- No predefined gaits or hardcoded morphologies or strategies.
- Core simulation stays independent of Kodi and rendering code.
- Fixed physics timestep. Rendering is decoupled and interpolated.
- Every mutation path ends in validate/repair before a creature is built.
- Avoid unnecessary dependencies. Pin all versions.
- No per-frame heap allocation in the render path.

## 19. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| MultiNEAT maintenance, Boost dependency, license friction | Wrap behind `INeuralEvolver`, validate in Phase 0, fallback plan to a minimal in-house NEAT or alternative library |
| Evolution too slow to be interesting on screen | Headless faster-than-real-time evaluation, a gentle first epoch, random immigrants, plateau-triggered goal changes |
| Physics exploits dominate | Anti-exploit rules, clamps, solver-instability detection, regression tests |
| Flight never emerges convincingly | Treated as experimental. Gliding and altitude-based objectives first, with simplified aero tuned in the CLI |
| Weak devices stutter | Adaptive quality governor, Low profile, render scaling |
| GLES/GL differences | Single shader subset, CI on both, avoid extensions |
| Same-seed replays diverge across machines | Replays tagged to build, fallback to re-evaluation or archived video-like keyframe track |
| Visual sameness over long runs | Palette variation, MAP-Elites diversity, Director variety, environment rotation |

## 20. Future Ideas (out of scope for v1)

Optional persistence with a saved creature library, water and swimming environments, creature-creature interaction (predator/prey or cooperation), co-evolving environments, audio ambience reacting to events, community creature sharing, optional background evolution while Kodi is idle, 3D physics backend.

## 21. Final Design Goal

EvolveLife should feel like a synthetic ecosystem you can leave running in the corner of the room. You glance up and see something unfamiliar crawling, leaping, or gliding in a way no one designed. It should always be pleasant to look at, even when evolution is failing, and over time it should surprise you.

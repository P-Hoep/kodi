// Alien Life simulation core - no Kodi / OpenGL dependencies.
//
// A small CPU take on ALIEN (Christian Heinemann's GPU artificial life
// simulator, https://github.com/chrxh/alien, BSD-3): creatures are networks of
// round cells held together by elastic connections, built cell by cell from a
// genome. Every cell has one of thirteen types (sensor, muscle, attacker,
// digestor, injector, reconnector, detonator, memory, communicator, ...) and a
// tiny neural network; signals travel from the last node of the genome towards
// node 0, one cell per cycle, so a sensor at the tail steers the muscles in
// front of it. Creatures eat free energy particles that radiation sources
// emit, attack creatures of other lineages, grab them, infect them with their
// own genome, blast their neighbours away, and build offspring at their tail,
// which separate when complete and carry a mutated genome. Bodies come in six
// shapes, from worms and ribbons to filled hexagonal jellies and tadpoles.
// Static rocks give the world some geography. Energy never appears out of
// nothing: a fixed budget circulates between an external pool, the energy
// particles and the creatures.
//
// Performance follows Dancing Boids and Particle Life v2:
//  - structure-of-arrays cells in fixed slots with a free list, no per-step
//    allocation;
//  - a uniform grid rebuilt every step by counting sort, with the positions
//    gathered into cell order so the contact loop walks memory linearly;
//  - the contact/bond/integration pass and the energy particle pass write only
//    their own element, so both are split over a worker pool with results
//    identical to one thread;
//  - creature logic (signals, sensors, building, death) runs once per 6-step
//    cycle, staggered over the creatures, and senses a coarse density map
//    instead of searching neighbours;
//  - no square root in the contact loop unless two cells actually touch.
#pragma once

#include "WorkerPool.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <random>
#include <vector>

namespace alien
{

constexpr int MAX_NODES = 20;
constexpr int MAX_BONDS = 8;
constexpr int NUM_COLOURS = 7;
constexpr int CYCLE = 6;
constexpr int GENE_BANK = 48;
constexpr float kPi = 3.14159265f;
constexpr uint32_t SOLID_TAG = 0xffffffffu; // grid tag of a rock cell
constexpr uint8_t NODE_COLOUR = 255;        // a node coloured like its genome

enum CellType : uint8_t
{
  CT_BASE,
  CT_SENSOR,
  CT_MUSCLE,
  CT_GENERATOR,
  CT_ATTACKER,
  CT_DIGESTOR,
  CT_DEFENDER,
  CT_DEPOT,        // stores energy for later
  CT_INJECTOR,     // writes its genome into a foreign creature
  CT_RECONNECTOR,  // grabs foreign cells and rocks
  CT_DETONATOR,    // blasts everything around it away
  CT_MEMORY,       // smooths or holds a signal
  CT_COMMUNICATOR, // sends signals to, or receives them from, its own colour
  CT_COUNT
};

enum Shape : uint8_t
{
  SHAPE_WORM,   // a chain that bends at every node
  SHAPE_RIBBON, // a strip of triangles, stiff
  SHAPE_RING,   // a closed chain
  SHAPE_FLOWER, // six petals round node 0, then a tail
  SHAPE_HEX,    // a filled hexagon that grows ring by ring
  SHAPE_LOLLI,  // a hexagonal head of seven cells and a thin tail
  SHAPE_COUNT
};

enum SenseTarget : uint8_t
{
  SENSE_FOOD, // energy particles
  SENSE_PREY, // cells of other colours
  SENSE_KIN,  // cells of the own colour
  SENSE_COUNT
};

enum MuscleMode : uint8_t
{
  MM_DIRECT, // accelerates the cell towards the direction in signal 1
  MM_BEND,   // bends its joint in a wave along the body, and swims
  MM_CRAWL,  // stretches and shrinks its connection, and creeps
  MM_COUNT
};

// Index order is the "world" setting minus one (0 there = a random one).
enum WorldKind
{
  WORLD_GRAZERS,
  WORLD_HUNT,
  WORLD_SOUP,
  WORLD_ECOSYSTEM,
  WORLD_COUNT
};

enum CellState : uint8_t
{
  CS_FREE,
  CS_ALIVE,
  CS_DYING,
  CS_SOLID // a rock: never moves, carries no energy
};

enum EventKind : uint8_t
{
  EV_ATTACK, // a beam from attacker to target
  EV_INJECT, // an injector writes its genome
  EV_GRAB,   // a reconnector takes hold
  EV_BLAST,  // a detonator explodes
  EV_BIRTH,  // an offspring separates
  EV_COUNT
};

// Steps an event stays visible, per EventKind.
constexpr int kEventLife[EV_COUNT] = {14, 40, 20, 80, 45};

struct Event
{
  float x0 = 0, y0 = 0, x1 = 0, y1 = 0;
  int a = -1, b = -1; // the cells, followed while they live
  uint8_t kind = EV_ATTACK;
  uint8_t colour = 0;
  uint16_t age = 0;
};

inline uint32_t Hash(uint32_t x)
{
  x ^= x >> 16;
  x *= 0x7feb352du;
  x ^= x >> 15;
  x *= 0x846ca68bu;
  x ^= x >> 16;
  return x;
}
inline float HashSigned(uint32_t h) { return static_cast<float>(h >> 8) * (2.0f / 16777216.0f) - 1.0f; }

// tanh to within 2 % on [-3, 3], saturating outside: the cells' activation
inline float SoftClip(float x)
{
  if (x <= -3.0f)
    return -1.0f;
  if (x >= 3.0f)
    return 1.0f;
  const float x2 = x * x;
  return x * (27.0f + x2) / (27.0f + 9.0f * x2);
}

struct Node
{
  uint8_t type = CT_BASE;
  uint8_t param = 0;             // sensor: SenseTarget; muscle: MuscleMode; generator: period; memory: mode
  uint8_t colour = NODE_COLOUR;  // an own colour for this cell, or the genome's
  float angle = 0;               // bend at this node (worm, flower tail), curve (ribbon)
  // out = SoftClip(w . [signal in 0, signal in 1, energy, 1]); the default
  // copies the incoming signal, as ALIEN's default networks do
  float w[2][4] = {{1, 0, 0, 0}, {0, 1, 0, 0}};
};

struct Genome
{
  Node nodes[MAX_NODES];
  int numNodes = 1;
  uint8_t shape = SHAPE_WORM;
  uint8_t colour = 0;
  uint32_t lineage = 0;
  int drift = 0; // mutations since the lineage was founded
};

struct Creature
{
  Genome g;
  int cells[MAX_NODES];
  float chainRest[MAX_NODES]; // rest length of node n's bond to n-1, as built
  float bendRest[MAX_NODES];  // rest length of node n's bend spring to n-2 (or 0)
  int8_t chainNode[MAX_NODES]; // the nodes those two bonds go to (-1: none)
  int8_t bendNode[MAX_NODES];
  int built = 0;
  bool alive = false;
  bool infected = false; // the next offspring is built from an injected genome
  float energy = 0;      // usable energy
  float structure = 0;   // energy that went into its cells
  float depot = 0;       // energy its depots hold
  int age = 0, maxAge = 0;
  int parent = -1, child = -1; // construction links
  int buildTimer = 0;
  float heading = 0;
  float seedX = 0, seedY = 0;
  uint32_t id = 0;
  int generation = 0;
  int defenders = 0, digestors = 0;
  int offspring = 0;
};

struct Source
{
  float x = 0, y = 0;
  float cx = 0, cy = 0, rx = 0, ry = 0, fx = 0, fy = 0, phase = 0;
};

struct Params
{
  float worldHeight = 150; // world units; a cell is 1 unit across
  int maxCells = 7000;
  int maxParticles = 4000;
  int initialCreatures = 120;
  float energy = 1.0f;     // budget multiplier
  int world = WORLD_HUNT;
  float mutation = 1.0f;   // 0 = off
  float muscle = 1.0f;     // muscle strength multiplier
  int sources = 3;
  int rocks = 1;           // 0 none, 1 a few, 2 many
};

// Physics and economy constants (per step at 60 steps a second).
struct Constants
{
  float radius = 1.0f;       // contact distance
  float repulse = 0.30f;
  float bondK = 0.22f;
  float bendK = 0.06f;
  float bondDamp = 0.18f;
  float friction = 0.90f;
  float maxSpeed = 0.45f;
  float attackRange = 1.5f;
  float absorbRange = 0.9f;
  float muscleForce = 0.030f;
  float cellCost = 60.0f;     // energy stored in a built cell
  float reserve = 80.0f;      // energy a creature keeps before building offspring
  float particleEnergy = 20.0f;
  float upkeep = 0.0035f;     // per cell per step
  float attack = 12.0f;       // per attack, before defenders
  int buildInterval = 10;     // steps per built cell
  float budgetPerArea = 8.0f; // energy per square unit at energy 1.0
  int particleLife = 2400;    // steps before an uneaten particle decays into the pool
  float injectCost = 60.0f;   // per injection, before defenders
  float blastCost = 25.0f;
  float blastRadius = 7.0f;
  float blastPush = 0.55f;
  int blastCooldown = 1500;   // steps before a detonator is ready again
  float depotRate = 8.0f;     // per cycle in or out
  float depotMax = 400.0f;
};

class World
{
public:
  Constants k;

  explicit World(uint32_t seed = 1) : m_rng(seed) {}

  // ---- setup ---------------------------------------------------------------

  void Reset(float aspect, const Params& p, uint32_t seed)
  {
    params = p;
    m_rng.seed(seed);
    m_seed = seed;
    const float G = kGrid;
    m_gy = std::max(8, static_cast<int>(std::lround(p.worldHeight / G)));
    m_gx = std::max(8, static_cast<int>(std::lround(p.worldHeight * std::max(aspect, 0.25f) / G)));
    m_h = m_gy * G;
    m_w = m_gx * G;
    m_invG = 1.0f / G;

    const size_t n = static_cast<size_t>(std::max(64, p.maxCells));
    for (auto* v : {&m_x, &m_y, &m_vx, &m_vy, &m_nx, &m_ny, &m_nvx, &m_nvy, &m_tx, &m_ty, &m_s0, &m_s1, &m_cellE,
                    &m_mem0, &m_mem1})
      v->assign(n, 0.0f);
    m_creature.assign(n, -1);
    m_target.assign(n, -1);
    m_node.assign(n, 0);
    m_type.assign(n, 0);
    m_state.assign(n, CS_FREE);
    m_colour.assign(n, 0);
    m_lineage.assign(n, 0);
    m_flash.assign(n, 0);
    m_timer.assign(n, 0);
    m_bondN.assign(n, 0);
    m_bondTo.assign(n * MAX_BONDS, -1);
    m_bondRest.assign(n * MAX_BONDS, 1.0f);
    m_bondK.assign(n * MAX_BONDS, 0.0f);
    m_freeCells.clear();
    for (size_t i = n; i-- > 0;)
      m_freeCells.push_back(static_cast<int>(i));
    m_liveCells = 0;
    m_solidCells = 0;

    m_cr.assign(n / 2, Creature());
    m_payload.assign(m_cr.size(), Genome());
    m_freeCr.clear();
    for (size_t i = m_cr.size(); i-- > 0;)
      m_freeCr.push_back(static_cast<int>(i));
    m_numCreatures = 0;

    m_np = 0;
    const size_t np = static_cast<size_t>(std::max(64, p.maxParticles));
    for (auto* v : {&m_px, &m_py, &m_pvx, &m_pvy, &m_pe})
      v->assign(np, 0.0f);
    m_page.assign(np, 0);
    m_pabs.assign(np, -1);

    m_cellStart.assign(static_cast<size_t>(m_gx) * m_gy + 1, 0);
    m_cellOf.assign(n, 0);
    m_sx.assign(n, 0);
    m_sy.assign(n, 0);
    m_sidx.assign(n, 0);
    m_stag.assign(n, 0);
    m_sorted = 0;

    m_dx = std::max(4, static_cast<int>(m_w / kDensityCell));
    m_dy = std::max(4, static_cast<int>(m_h / kDensityCell));
    m_food.assign(static_cast<size_t>(m_dx) * m_dy, 0.0f);
    m_kin.assign(static_cast<size_t>(m_dx) * m_dy * NUM_COLOURS, 0);
    m_all.assign(static_cast<size_t>(m_dx) * m_dy, 0);
    m_msgS.assign(static_cast<size_t>(m_dx) * m_dy * NUM_COLOURS, 0.0f);
    m_msgA.assign(static_cast<size_t>(m_dx) * m_dy * NUM_COLOURS, 0.0f);

    m_events.clear();
    m_step = 0;
    m_nextId = 1;
    m_nextLineage = 1;
    m_bank.clear();
    m_founderLineage.clear();
    m_bankNext = 0;
    m_births = m_deaths = 0;
    m_blasts = m_injections = m_grabs = m_attacks = 0;

    m_budget = static_cast<double>(k.budgetPerArea) * p.energy * m_w * m_h;
    m_pool = m_budget;

    m_numSources = std::min(std::max(p.sources, 1), 6);
    for (int s = 0; s < m_numSources; s++)
    {
      Source& q = m_src[s];
      q.cx = Uniform(0, m_w);
      q.cy = Uniform(0.2f, 0.8f) * m_h;
      q.rx = Uniform(0.05f, 0.25f) * m_w;
      q.ry = Uniform(0.05f, 0.2f) * m_h;
      q.fx = Uniform(0.6f, 1.4f) * 0.00012f;
      q.fy = Uniform(0.6f, 1.4f) * 0.00012f;
      q.phase = Uniform(0, 6.2831853f);
    }
    MoveSources();
    BuildRocks();

    // a world opens with food spread round the sources and its founders
    const int initialParticles = std::min(static_cast<int>(np) / 2, static_cast<int>(m_pool * 0.25 / k.particleEnergy));
    for (int i = 0; i < initialParticles; i++)
      Emit(i % m_numSources, true);
    for (int i = 0; i < p.initialCreatures; i++)
      SpawnFounder();
    BuildDensity();
  }

  // ---- stepping --------------------------------------------------------------

  void Step(WorkerPool& pool)
  {
    BuildGrid();
    pool.Run(m_sorted, [this](size_t a, size_t b) { CellRange(a, b); });
    pool.Run(static_cast<size_t>(m_np), [this](size_t a, size_t b) { ParticleRange(a, b); });
    Commit();
  }

  void Step()
  {
    BuildGrid();
    CellRange(0, m_sorted);
    ParticleRange(0, static_cast<size_t>(m_np));
    Commit();
  }

  // ---- read access (rendering, tests) ---------------------------------------

  Params params;

  float width() const { return m_w; }
  float height() const { return m_h; }
  size_t capacity() const { return m_x.size(); }
  const float* x() const { return m_x.data(); }
  const float* y() const { return m_y.data(); }
  const uint8_t* state() const { return m_state.data(); }
  const uint8_t* type() const { return m_type.data(); }
  const uint8_t* colour() const { return m_colour.data(); }
  const uint8_t* flash() const { return m_flash.data(); }
  const uint16_t* timer() const { return m_timer.data(); }
  const float* signal() const { return m_s0.data(); }
  const int* creatureOf() const { return m_creature.data(); }
  const uint8_t* bondCount() const { return m_bondN.data(); }
  const int* bondTo() const { return m_bondTo.data(); }
  const Creature& creature(int i) const { return m_cr[static_cast<size_t>(i)]; }
  int numParticles() const { return m_np; }
  const float* px() const { return m_px.data(); }
  const float* py() const { return m_py.data(); }
  const float* pe() const { return m_pe.data(); }
  const int* page() const { return m_page.data(); }
  int numSources() const { return m_numSources; }
  const Source& source(int i) const { return m_src[i]; }
  int liveCells() const { return m_liveCells; }
  int solidCells() const { return m_solidCells; }
  int numCreatures() const { return m_numCreatures; }
  uint64_t steps() const { return m_step; }
  long births() const { return m_births; }
  long deaths() const { return m_deaths; }
  long blasts() const { return m_blasts; }
  long injections() const { return m_injections; }
  long grabs() const { return m_grabs; }
  long attacks() const { return m_attacks; }
  double pool() const { return m_pool; }
  double budget() const { return m_budget; }
  const std::vector<Event>& events() const { return m_events; }
  // the coarse map of live cells the sensors read (and the camera follows)
  int densityW() const { return m_dx; }
  int densityH() const { return m_dy; }
  const uint16_t* density() const { return m_all.data(); }
  int maxGeneration() const
  {
    int g = 0;
    for (const Creature& c : m_cr)
      if (c.alive)
        g = std::max(g, c.generation);
    return g;
  }
  int lineages() const
  {
    std::vector<uint32_t> l;
    for (const Creature& c : m_cr)
      if (c.alive)
        l.push_back(c.g.lineage);
    std::sort(l.begin(), l.end());
    return static_cast<int>(std::unique(l.begin(), l.end()) - l.begin());
  }
  int countType(int t) const
  {
    int n = 0;
    for (size_t i = 0; i < m_state.size(); i++)
      if (m_state[i] == CS_ALIVE && m_type[i] == t)
        n++;
    return n;
  }
  int countShape(int s) const
  {
    int n = 0;
    for (const Creature& c : m_cr)
      if (c.alive && c.g.shape == s)
        n++;
    return n;
  }

  // Every unit of energy in the world; stays equal to budget().
  double TotalEnergy() const
  {
    double e = m_pool;
    for (int i = 0; i < m_np; i++)
      e += m_pe[i];
    for (const Creature& c : m_cr)
      if (c.alive)
        e += c.energy + c.structure + c.depot;
    for (size_t i = 0; i < m_state.size(); i++)
      if (m_state[i] == CS_DYING)
        e += m_cellE[i];
    return e;
  }

  // A cell's creature's usable energy against what it needs to reproduce, 0..1.
  float Vigour(int cell) const
  {
    const int c = m_creature[static_cast<size_t>(cell)];
    if (c < 0)
      return 0.0f;
    const Creature& cr = m_cr[static_cast<size_t>(c)];
    const float need = cr.g.numNodes * k.cellCost + k.reserve;
    return std::min(std::max((cr.energy + 0.5f * cr.depot) / need, 0.0f), 1.0f);
  }

  float Uniform(float a, float b) { return std::uniform_real_distribution<float>(a, b)(m_rng); }
  int RandomInt(int lo, int hi) { return std::uniform_int_distribution<int>(lo, hi)(m_rng); }

  // ---- genomes -----------------------------------------------------------------

  enum Kind
  {
    KIND_WORM,     // a wriggling worm grazer
    KIND_FLOWER,   // six petals and a tail
    KIND_RIBBON,   // a stiff, armoured strip
    KIND_RING,     // a closed loop
    KIND_HUNTER,   // a red worm that grabs and bites
    KIND_JELLY,    // a filled hexagon, small or large
    KIND_TADPOLE,  // a round head and a swimming tail
    KIND_PUFFER,   // blasts its neighbours away now and then
    KIND_VIRUS,    // writes its genome into others
    KIND_COUNT
  };

  // A designed species.
  Genome Species(int kind, int colour)
  {
    Genome g;
    g.colour = static_cast<uint8_t>(colour % NUM_COLOURS);
    auto set = [&](std::initializer_list<int> types) {
      g.numNodes = 0;
      for (int t : types)
      {
        Node& n = g.nodes[g.numNodes++];
        n = Node();
        n.type = static_cast<uint8_t>(t);
      }
    };
    auto accent = [&](int node, int offset) {
      g.nodes[node].colour = static_cast<uint8_t>((g.colour + offset) % NUM_COLOURS);
    };
    switch (kind)
    {
      case KIND_WORM:
        g.shape = SHAPE_WORM;
        set({CT_MUSCLE, CT_BASE, CT_DIGESTOR, CT_MUSCLE, CT_DIGESTOR, CT_MUSCLE, CT_BASE, CT_SENSOR});
        for (int i = 1; i < g.numNodes; i++)
          g.nodes[i].angle = Uniform(-0.35f, 0.35f);
        for (int i : {0, 3, 5})
          g.nodes[i].param = MM_BEND;
        break;
      case KIND_FLOWER:
        g.shape = SHAPE_FLOWER;
        set({CT_DIGESTOR, CT_MUSCLE, CT_BASE, CT_GENERATOR, CT_MUSCLE, CT_BASE, CT_SENSOR});
        g.nodes[3].param = static_cast<uint8_t>(RandomInt(0, 3));
        for (int i = 1; i <= 6; i += 2)
          accent(i, 1);
        break;
      case KIND_RIBBON:
        g.shape = SHAPE_RIBBON;
        set({CT_MUSCLE, CT_MUSCLE, CT_DIGESTOR, CT_BASE, CT_DEFENDER, CT_BASE, CT_SENSOR, CT_BASE});
        for (int i = 1; i < g.numNodes; i++)
          g.nodes[i].angle = Uniform(-0.25f, 0.25f);
        g.nodes[1].param = MM_CRAWL;
        break;
      case KIND_RING:
        g.shape = SHAPE_RING;
        set({CT_DIGESTOR, CT_MUSCLE, CT_BASE, CT_DIGESTOR, CT_MUSCLE, CT_BASE, CT_GENERATOR, CT_SENSOR});
        g.nodes[6].param = static_cast<uint8_t>(RandomInt(0, 3));
        break;
      case KIND_JELLY:
        g.shape = SHAPE_HEX;
        if (RandomInt(0, 2) == 0)
        {
          // a large jelly: 19 cells, armoured rim, a sensor at the end of the spiral
          set({CT_DEPOT,    CT_MUSCLE,   CT_DIGESTOR, CT_MUSCLE, CT_DIGESTOR, CT_MUSCLE,   CT_DIGESTOR,
               CT_BASE,     CT_DEFENDER, CT_BASE,     CT_MUSCLE, CT_BASE,     CT_DIGESTOR, CT_BASE,
               CT_DEFENDER, CT_BASE,     CT_MUSCLE,   CT_BASE,   CT_SENSOR});
          for (int i = 7; i < 19; i += 3)
            accent(i, 6);
        }
        else
          set({CT_DEPOT, CT_MUSCLE, CT_DIGESTOR, CT_MUSCLE, CT_DIGESTOR, CT_MUSCLE, CT_SENSOR});
        // the muscles pulse like a jellyfish's bell
        for (int i = 0; i < g.numNodes; i++)
          if (g.nodes[i].type == CT_MUSCLE)
            g.nodes[i].param = MM_CRAWL;
        // the depot stores when the creature is well fed and gives back when it is not
        g.nodes[0].w[0][0] = 0.0f;
        g.nodes[0].w[0][2] = 2.4f;
        g.nodes[0].w[0][3] = -1.4f;
        accent(0, 3);
        break;
      case KIND_TADPOLE:
        g.shape = SHAPE_LOLLI;
        set({CT_DIGESTOR, CT_DIGESTOR, CT_BASE, CT_DIGESTOR, CT_BASE, CT_DIGESTOR, CT_BASE, CT_MUSCLE, CT_MUSCLE,
             CT_MUSCLE, CT_BASE, CT_SENSOR});
        for (int i = 7; i <= 9; i++)
          g.nodes[i].param = MM_BEND;
        for (int i = 7; i < g.numNodes; i++)
          g.nodes[i].angle = Uniform(-0.2f, 0.2f);
        for (int i = 7; i < g.numNodes; i++)
          accent(i, 1);
        break;
      case KIND_PUFFER:
        g.shape = SHAPE_WORM;
        set({CT_DETONATOR, CT_MUSCLE, CT_DIGESTOR, CT_MUSCLE, CT_BASE, CT_GENERATOR, CT_SENSOR});
        g.nodes[5].param = 3; // the slowest clock
        g.nodes[0].w[0][0] = 3.0f; // the clock has faded on its way down the body: amplify it
        for (int i = 1; i < g.numNodes; i++)
          g.nodes[i].angle = Uniform(-0.3f, 0.3f);
        accent(0, 2);
        break;
      case KIND_VIRUS:
        g.shape = SHAPE_WORM;
        set({CT_INJECTOR, CT_DIGESTOR, CT_MUSCLE, CT_DIGESTOR, CT_MUSCLE, CT_SENSOR});
        for (int i = 1; i < g.numNodes; i++)
          g.nodes[i].angle = Uniform(-0.3f, 0.3f);
        g.nodes[4].param = MM_BEND;
        break;
      case KIND_HUNTER:
      default:
        g.shape = SHAPE_WORM;
        // no digestor: a hunter lives off its prey, not off the radiation
        set({CT_ATTACKER, CT_RECONNECTOR, CT_MUSCLE, CT_MUSCLE, CT_BASE, CT_SENSOR});
        for (int i = 1; i < g.numNodes; i++)
          g.nodes[i].angle = Uniform(-0.3f, 0.3f);
        g.nodes[3].param = MM_BEND;
        accent(0, 2);
        break;
    }
    const bool predator = kind == KIND_HUNTER || kind == KIND_VIRUS;
    for (int i = 0; i < g.numNodes; i++)
      if (g.nodes[i].type == CT_SENSOR)
        g.nodes[i].param = predator ? SENSE_PREY : SENSE_FOOD;
    g.lineage = m_nextLineage++;
    return g;
  }

  Genome RandomGenome()
  {
    Genome g;
    g.colour = static_cast<uint8_t>(RandomInt(0, NUM_COLOURS - 1));
    g.shape = static_cast<uint8_t>(RandomInt(0, SHAPE_COUNT - 1));
    g.numNodes = g.shape == SHAPE_HEX ? (RandomInt(0, 3) == 0 ? 19 : 7)
                                      : RandomInt(g.shape == SHAPE_LOLLI ? 9 : 3, g.shape == SHAPE_LOLLI ? 13 : 11);
    for (int i = 0; i < g.numNodes; i++)
    {
      Node& n = g.nodes[i];
      n.type = static_cast<uint8_t>(RandomInt(0, CT_COUNT - 1));
      n.param = static_cast<uint8_t>(RandomInt(0, 3));
      if (n.type == CT_SENSOR)
        n.param = static_cast<uint8_t>(RandomInt(0, SENSE_COUNT - 1));
      if (n.type == CT_MUSCLE)
        n.param = static_cast<uint8_t>(RandomInt(0, MM_COUNT - 1));
      if (RandomInt(0, 7) == 0)
        n.colour = static_cast<uint8_t>(RandomInt(0, NUM_COLOURS - 1));
      n.angle = Uniform(-0.5f, 0.5f);
      for (auto& row : n.w)
        for (float& w : row)
          w += Uniform(-0.5f, 0.5f);
    }
    g.lineage = m_nextLineage++;
    return g;
  }

  void Mutate(Genome& g)
  {
    if (params.mutation <= 0.0f)
      return;
    // about 0.7 mutations per offspring at the normal rate
    std::poisson_distribution<int> count(0.7 * params.mutation);
    const int n = count(m_rng);
    bool newLineage = false;
    for (int m = 0; m < n; m++)
    {
      const float r = Uniform(0, 1);
      Node& node = g.nodes[RandomInt(0, g.numNodes - 1)];
      if (r < 0.42f)
        node.w[RandomInt(0, 1)][RandomInt(0, 3)] += std::normal_distribution<float>(0.0f, 0.45f)(m_rng);
      else if (r < 0.56f)
        node.angle = std::min(std::max(node.angle + Uniform(-0.4f, 0.4f), -1.2f), 1.2f);
      else if (r < 0.68f)
      {
        node.type = static_cast<uint8_t>(RandomInt(0, CT_COUNT - 1));
        if (node.type == CT_SENSOR)
          node.param = static_cast<uint8_t>(RandomInt(0, SENSE_COUNT - 1));
        if (node.type == CT_MUSCLE)
          node.param = static_cast<uint8_t>(RandomInt(0, MM_COUNT - 1));
      }
      else if (r < 0.74f)
        node.param = static_cast<uint8_t>(node.type == CT_SENSOR   ? RandomInt(0, SENSE_COUNT - 1)
                                          : node.type == CT_MUSCLE ? RandomInt(0, MM_COUNT - 1)
                                                                   : RandomInt(0, 3));
      else if (r < 0.77f)
        node.colour = RandomInt(0, 2) == 0 ? NODE_COLOUR : static_cast<uint8_t>(RandomInt(0, NUM_COLOURS - 1));
      else if (r < 0.86f && g.numNodes < MAX_NODES)
      {
        const int at = RandomInt(1, g.numNodes);
        for (int i = g.numNodes; i > at; i--)
          g.nodes[i] = g.nodes[i - 1];
        g.nodes[at] = Node();
        g.nodes[at].type = static_cast<uint8_t>(RandomInt(0, CT_COUNT - 1));
        g.nodes[at].angle = Uniform(-0.4f, 0.4f);
        g.numNodes++;
      }
      else if (r < 0.95f && g.numNodes > 3)
      {
        const int at = RandomInt(1, g.numNodes - 1);
        for (int i = at; i + 1 < g.numNodes; i++)
          g.nodes[i] = g.nodes[i + 1];
        g.numNodes--;
      }
      else if (r < 0.98f)
        g.shape = static_cast<uint8_t>(RandomInt(0, SHAPE_COUNT - 1));
      else
      {
        g.colour = static_cast<uint8_t>((g.colour + RandomInt(1, NUM_COLOURS - 1)) % NUM_COLOURS);
        newLineage = true;
      }
      g.drift++;
    }
    if (newLineage || g.drift >= 10)
    {
      g.lineage = m_nextLineage++;
      g.drift = 0;
    }
  }

private:
  static constexpr float kGrid = 1.6f;         // >= attack range
  static constexpr float kDensityCell = 5.0f;  // the sensors' map

  // ---- geometry ----------------------------------------------------------------

  float WrapX(float v) const
  {
    if (v < 0.0f)
      v += m_w;
    else if (v >= m_w)
      v -= m_w;
    return std::min(std::max(v, 0.0f), m_w - 1e-3f);
  }
  float WrapY(float v) const
  {
    if (v < 0.0f)
      v += m_h;
    else if (v >= m_h)
      v -= m_h;
    return std::min(std::max(v, 0.0f), m_h - 1e-3f);
  }
  float DX(float a, float b) const // b - a across the wrap
  {
    float d = b - a;
    return d > 0.5f * m_w ? d - m_w : (d < -0.5f * m_w ? d + m_w : d);
  }
  float DY(float a, float b) const
  {
    float d = b - a;
    return d > 0.5f * m_h ? d - m_h : (d < -0.5f * m_h ? d + m_h : d);
  }
  static void Norm(float& x, float& y)
  {
    const float l = std::sqrt(x * x + y * y);
    if (l > 1e-6f)
    {
      x /= l;
      y /= l;
    }
    else
    {
      x = 1.0f;
      y = 0.0f;
    }
  }
  static void Rot(float& x, float& y, float a)
  {
    const float c = std::cos(a), s = std::sin(a);
    const float nx = x * c - y * s;
    y = x * s + y * c;
    x = nx;
  }
  // unit vector from cell a to cell b
  void Dir(int a, int b, float& x, float& y) const
  {
    x = DX(m_x[a], m_x[b]);
    y = DY(m_y[a], m_y[b]);
    Norm(x, y);
  }
  float Dist(int a, int b) const
  {
    const float dx = DX(m_x[a], m_x[b]), dy = DY(m_y[a], m_y[b]);
    return std::sqrt(dx * dx + dy * dy);
  }

  // The hexagonal lattice of SHAPE_HEX and the head of SHAPE_LOLLI, in spiral
  // order (axial coordinates): node 0 in the centre, then ring after ring.
  struct Hex
  {
    int q, r;
  };
  static const Hex* Spiral()
  {
    static Hex s[37];
    static bool done = false;
    if (!done)
    {
      static const Hex kDir[6] = {{1, 0}, {1, -1}, {0, -1}, {-1, 0}, {-1, 1}, {0, 1}};
      int n = 0;
      s[n++] = {0, 0};
      for (int k = 1; k <= 3; k++)
      {
        Hex h = {kDir[4].q * k, kDir[4].r * k};
        for (int i = 0; i < 6; i++)
          for (int j = 0; j < k; j++)
          {
            s[n++] = h;
            h = {h.q + kDir[i].q, h.r + kDir[i].r};
          }
      }
      done = true;
    }
    return s;
  }
  static bool HexAdjacent(const Hex& a, const Hex& b)
  {
    const int dq = a.q - b.q, dr = a.r - b.r;
    return std::max(std::max(std::abs(dq), std::abs(dr)), std::abs(dq + dr)) == 1;
  }
  static void HexXY(const Hex& h, float& x, float& y)
  {
    x = h.q + 0.5f * h.r;
    y = h.r * 0.8660254f;
  }

  // ---- cells and bonds -----------------------------------------------------------

  int AllocCell(float x, float y, int cr, int node, const Node& n, int colour)
  {
    if (m_freeCells.empty())
      return -1;
    const int i = m_freeCells.back();
    m_freeCells.pop_back();
    m_x[i] = WrapX(x);
    m_y[i] = WrapY(y);
    m_vx[i] = m_vy[i] = m_tx[i] = m_ty[i] = m_s0[i] = m_s1[i] = m_cellE[i] = m_mem0[i] = m_mem1[i] = 0.0f;
    m_creature[i] = cr;
    m_node[i] = static_cast<uint8_t>(node);
    m_type[i] = n.type;
    m_state[i] = CS_ALIVE;
    m_colour[i] = static_cast<uint8_t>(n.colour == NODE_COLOUR ? colour : n.colour % NUM_COLOURS);
    m_lineage[i] = cr >= 0 ? m_cr[static_cast<size_t>(cr)].g.lineage : 0;
    m_flash[i] = 140; // a new cell lights up as it is built
    m_timer[i] = 0;
    m_bondN[i] = 0;
    m_target[i] = -1;
    m_liveCells++;
    return i;
  }

  bool Bonded(int a, int b) const
  {
    for (int s = 0; s < m_bondN[a]; s++)
      if (m_bondTo[static_cast<size_t>(a) * MAX_BONDS + s] == b)
        return true;
    return false;
  }

  bool AddBond(int a, int b, float rest, float kk)
  {
    if (a < 0 || b < 0 || a == b || m_bondN[a] >= MAX_BONDS || m_bondN[b] >= MAX_BONDS || Bonded(a, b))
      return false;
    const size_t sa = static_cast<size_t>(a) * MAX_BONDS + m_bondN[a]++;
    const size_t sb = static_cast<size_t>(b) * MAX_BONDS + m_bondN[b]++;
    m_bondTo[sa] = b;
    m_bondTo[sb] = a;
    m_bondRest[sa] = m_bondRest[sb] = rest;
    m_bondK[sa] = m_bondK[sb] = kk;
    return true;
  }

  void SetRest(int a, int b, float rest)
  {
    for (int pass = 0; pass < 2; pass++, std::swap(a, b))
    {
      const size_t base = static_cast<size_t>(a) * MAX_BONDS;
      for (int s = 0; s < m_bondN[a]; s++)
        if (m_bondTo[base + s] == b)
        {
          m_bondRest[base + s] = rest;
          break;
        }
    }
  }

  void RemoveBondSlot(int a, int b)
  {
    const size_t base = static_cast<size_t>(a) * MAX_BONDS;
    for (int s = 0; s < m_bondN[a]; s++)
      if (m_bondTo[base + s] == b)
      {
        const int last = --m_bondN[a];
        m_bondTo[base + s] = m_bondTo[base + last];
        m_bondRest[base + s] = m_bondRest[base + last];
        m_bondK[base + s] = m_bondK[base + last];
        return;
      }
  }

  void RemoveBond(int a, int b)
  {
    RemoveBondSlot(a, b);
    RemoveBondSlot(b, a);
  }

  void FreeCell(int i)
  {
    while (m_bondN[i] > 0)
      RemoveBond(i, m_bondTo[static_cast<size_t>(i) * MAX_BONDS]);
    m_state[i] = CS_FREE;
    m_creature[i] = -1;
    m_freeCells.push_back(i);
    m_liveCells--;
  }

  void AddEvent(int kind, int a, int b, int colour)
  {
    if (m_events.size() >= 768)
      return;
    Event e;
    e.kind = static_cast<uint8_t>(kind);
    e.a = a;
    e.b = b;
    e.colour = static_cast<uint8_t>(colour);
    e.x0 = m_x[a];
    e.y0 = m_y[a];
    e.x1 = b >= 0 ? m_x[b] : m_x[a];
    e.y1 = b >= 0 ? m_y[b] : m_y[a];
    m_events.push_back(e);
  }

  // ---- rocks -----------------------------------------------------------------------

  // A few static rocks on a hexagonal lattice, kept clear of the sources. Their
  // cells take part in contacts (creatures and particles bump into them) but
  // never move and carry no energy.
  void BuildRocks()
  {
    static const int kCount[] = {0, 3, 7};
    const int rocks = kCount[std::min(std::max(params.rocks, 0), 2)];
    // no more than a twelfth of the cells
    int budget = static_cast<int>(m_x.size()) / 12;
    const float scale = std::sqrt(m_h / 150.0f);
    for (int r = 0; r < rocks && budget > 40; r++)
    {
      float cx = 0, cy = 0;
      bool ok = false;
      for (int tries = 0; tries < 30 && !ok; tries++)
      {
        cx = Uniform(0, m_w);
        cy = Uniform(0, m_h);
        ok = true;
        for (int s = 0; s < m_numSources; s++)
        {
          const float dx = DX(cx, m_src[s].x), dy = DY(cy, m_src[s].y);
          if (dx * dx + dy * dy < (0.22f * m_h) * (0.22f * m_h))
            ok = false;
        }
      }
      const float radius = Uniform(3.0f, 6.5f) * scale;
      const float stretch = Uniform(0.6f, 1.7f), turn = Uniform(0, kPi);
      const float p1 = Uniform(0, 6.3f), p2 = Uniform(0, 6.3f);
      const int R = static_cast<int>(radius * 2.0f) + 2;
      // lattice sites inside a lumpy, stretched outline
      std::vector<int> ids;
      std::vector<Hex> hexes;
      for (int q = -R; q <= R; q++)
        for (int rr = -R; rr <= R; rr++)
        {
          float x, y;
          HexXY({q, rr}, x, y);
          float ex = x / stretch, ey = y * stretch;
          Rot(ex, ey, turn);
          const float a = std::atan2(ey, ex);
          const float edge = radius * (1.0f + 0.22f * std::sin(3 * a + p1) + 0.12f * std::sin(5 * a + p2));
          if (ex * ex + ey * ey > edge * edge || budget <= 0)
            continue;
          Rot(x, y, turn);
          const int i = AllocSolid(cx + x, cy + y);
          if (i < 0)
            continue;
          ids.push_back(i);
          hexes.push_back({q, rr});
          budget--;
        }
      for (size_t a = 0; a < ids.size(); a++)
        for (size_t b = a + 1; b < ids.size(); b++)
          if (HexAdjacent(hexes[a], hexes[b]))
            AddBond(ids[a], ids[b], 1.0f, 0.0f);
    }
  }

  int AllocSolid(float x, float y)
  {
    if (m_freeCells.empty())
      return -1;
    const int i = m_freeCells.back();
    m_freeCells.pop_back();
    m_x[i] = WrapX(x);
    m_y[i] = WrapY(y);
    m_vx[i] = m_vy[i] = m_tx[i] = m_ty[i] = m_s0[i] = m_s1[i] = m_cellE[i] = m_mem0[i] = m_mem1[i] = 0.0f;
    m_creature[i] = -1;
    m_type[i] = CT_BASE;
    m_state[i] = CS_SOLID;
    m_colour[i] = 0;
    m_lineage[i] = 0;
    m_flash[i] = 0;
    m_timer[i] = static_cast<uint16_t>(Hash(static_cast<uint32_t>(i) ^ m_seed) & 0xff); // texture
    m_bondN[i] = 0;
    m_target[i] = -1;
    m_solidCells++;
    return i;
  }

  // ---- creatures ------------------------------------------------------------------

  int AllocCreature(const Genome& g, float x, float y, float heading)
  {
    if (m_freeCr.empty())
      return -1;
    const int i = m_freeCr.back();
    m_freeCr.pop_back();
    Creature& c = m_cr[static_cast<size_t>(i)];
    c = Creature();
    c.g = g;
    c.alive = true;
    c.seedX = x;
    c.seedY = y;
    c.heading = heading;
    c.id = m_nextId++;
    c.maxAge = 9000 + RandomInt(0, 6000);
    c.buildTimer = k.buildInterval;
    for (int n = 0; n < MAX_NODES; n++)
    {
      c.cells[n] = -1;
      c.chainRest[n] = c.bendRest[n] = 0.0f;
      c.chainNode[n] = c.bendNode[n] = -1;
    }
    m_numCreatures++;
    return i;
  }

  // Place and bond the creature's next cell (node c.built). Its energy is the
  // caller's business.
  bool BuildNext(int ci)
  {
    Creature& c = m_cr[static_cast<size_t>(ci)];
    const Genome& g = c.g;
    const int kNode = c.built;
    if (kNode >= g.numNodes)
      return false;
    const Node& node = g.nodes[kNode];
    auto P = [&](int n) { return c.cells[n]; };

    float px = c.seedX, py = c.seedY;
    // up to six links: node, stiffness, rest (-1 = as placed); slot 0 is the
    // chain bond to the node before, slot 1 the bend spring (if any)
    int links[6] = {-1, -1, -1, -1, -1, -1};
    float stiff[6] = {k.bondK, k.bondK, k.bondK, k.bondK, k.bondK, k.bondK};
    float fixedRest[6] = {1.0f, -1.0f, -1.0f, 1.0f, 1.0f, 1.0f};
    int bendSlot = -1;

    auto chain = [&](int prev, float dx, float dy) {
      Rot(dx, dy, node.angle);
      px = m_x[P(prev)] + dx;
      py = m_y[P(prev)] + dy;
    };

    const bool lattice = g.shape == SHAPE_HEX || (g.shape == SHAPE_LOLLI && kNode <= 6);
    if (kNode > 0 && lattice)
    {
      // on the lattice: place relative to node 0 in the body's own frame and
      // bond to every built lattice neighbour
      const Hex* sp = Spiral();
      float hx, hy;
      HexXY(sp[kNode], hx, hy);
      float rot = c.heading;
      if (kNode >= 2)
      {
        float ax, ay, lx, ly;
        Dir(P(0), P(1), ax, ay);
        HexXY(sp[1], lx, ly);
        rot = std::atan2(ay, ax) - std::atan2(ly, lx);
      }
      else
      {
        float lx, ly;
        HexXY(sp[1], lx, ly);
        rot = c.heading - std::atan2(ly, lx);
      }
      Rot(hx, hy, rot);
      px = m_x[P(0)] + hx;
      py = m_y[P(0)] + hy;
      int l = 0;
      for (int n = 0; n < kNode && l < 6; n++)
        if (HexAdjacent(sp[n], sp[kNode]))
        {
          links[l] = n;
          fixedRest[l] = 1.0f;
          l++;
        }
    }
    else if (kNode > 0)
    {
      const float hx = std::cos(c.heading), hy = std::sin(c.heading);
      switch (g.shape)
      {
        case SHAPE_LOLLI:
        {
          // the tail grows straight out of node 4, away from the head
          float dx, dy;
          if (kNode == 7)
            Dir(P(0), P(4), dx, dy);
          else
            Dir(P(kNode - 2), P(kNode - 1), dx, dy);
          const int prev = kNode == 7 ? 4 : kNode - 1;
          Rot(dx, dy, node.angle * 0.5f);
          px = m_x[P(prev)] + dx;
          py = m_y[P(prev)] + dy;
          links[0] = prev;
          links[1] = kNode == 7 ? 0 : kNode - 2;
          stiff[1] = k.bendK * 1.5f;
          bendSlot = 1;
          break;
        }
        case SHAPE_RIBBON:
          links[0] = kNode - 1;
          if (kNode == 1)
          {
            float dx = hx, dy = hy;
            Rot(dx, dy, kPi / 3.0f);
            px = m_x[P(0)] + dx;
            py = m_y[P(0)] + dy;
          }
          else
          {
            float ax, ay;
            if (kNode == 2)
            {
              Dir(P(0), P(1), ax, ay);
              Rot(ax, ay, -kPi / 3.0f);
            }
            else
              Dir(P(kNode - 3), P(kNode - 1), ax, ay);
            Rot(ax, ay, node.angle * 0.3f);
            px = m_x[P(kNode - 2)] + ax;
            py = m_y[P(kNode - 2)] + ay;
            links[1] = kNode - 2;
            fixedRest[0] = -1.0f;
            fixedRest[1] = 1.0f;
          }
          break;
        case SHAPE_FLOWER:
          if (kNode <= 6)
          {
            float dx = hx, dy = hy;
            if (kNode > 1)
            {
              Dir(P(0), P(1), dx, dy);
              Rot(dx, dy, (kNode - 1) * kPi / 3.0f);
            }
            px = m_x[P(0)] + dx;
            py = m_y[P(0)] + dy;
            links[0] = 0;
            if (kNode > 1)
            {
              links[1] = kNode - 1;
              fixedRest[1] = 1.0f;
            }
            if (kNode == 6)
            {
              links[2] = 1;
              fixedRest[2] = 1.0f;
            }
          }
          else
          {
            float dx, dy;
            if (kNode == 7)
              Dir(P(0), P(6), dx, dy);
            else
              Dir(P(kNode - 2), P(kNode - 1), dx, dy);
            chain(kNode - 1, dx, dy);
            links[0] = kNode - 1;
            links[1] = kNode == 7 ? 0 : kNode - 2;
            stiff[1] = k.bendK;
            bendSlot = 1;
          }
          break;
        case SHAPE_RING:
        case SHAPE_WORM:
        default:
        {
          float dx = hx, dy = hy;
          if (kNode >= 2)
            Dir(P(kNode - 2), P(kNode - 1), dx, dy);
          if (g.shape == SHAPE_RING)
          {
            Rot(dx, dy, 2.0f * kPi / std::max(g.numNodes, 3));
            px = m_x[P(kNode - 1)] + dx;
            py = m_y[P(kNode - 1)] + dy;
          }
          else
            chain(kNode - 1, dx, dy);
          links[0] = kNode - 1;
          if (kNode >= 2)
          {
            links[1] = kNode - 2;
            stiff[1] = g.shape == SHAPE_RING ? k.bondK * 0.6f : k.bendK;
            bendSlot = 1;
          }
          if (g.shape == SHAPE_RING && kNode == g.numNodes - 1 && g.numNodes >= 4)
          {
            links[2] = 0;
            fixedRest[2] = 1.0f;
          }
          break;
        }
      }
    }

    const int cell = AllocCell(px, py, ci, kNode, node, g.colour);
    if (cell < 0)
      return false;
    c.cells[kNode] = cell;
    c.built++;
    if (node.type == CT_DEFENDER)
      c.defenders++;
    if (node.type == CT_DIGESTOR)
      c.digestors++;
    // inherit the motion of the body it grows from
    if (kNode > 0)
    {
      const int from = links[0] >= 0 ? P(links[0]) : P(kNode - 1);
      m_vx[cell] = m_vx[from];
      m_vy[cell] = m_vy[from];
    }
    for (int l = 0; l < 6; l++)
    {
      if (links[l] < 0)
        continue;
      const int other = P(links[l]);
      float rest = fixedRest[l];
      if (rest < 0.0f)
      {
        const float dx = DX(m_x[other], m_x[cell]), dy = DY(m_y[other], m_y[cell]);
        rest = std::min(std::max(std::sqrt(dx * dx + dy * dy), 0.6f), 2.2f);
      }
      if (AddBond(cell, other, rest, stiff[l]))
      {
        if (l == 0)
        {
          c.chainRest[kNode] = rest;
          c.chainNode[kNode] = static_cast<int8_t>(links[l]);
        }
        if (l == bendSlot)
        {
          c.bendRest[kNode] = rest;
          c.bendNode[kNode] = static_cast<int8_t>(links[l]);
        }
      }
    }
    return true;
  }

  // A creature built at once (a founder or a respawn), paid from the pool.
  bool SpawnCreature(const Genome& g, float x, float y, float heading)
  {
    const double cost = g.numNodes * k.cellCost + k.reserve * 1.5f;
    if (m_pool < cost || m_freeCells.size() < static_cast<size_t>(g.numNodes))
      return false;
    const int ci = AllocCreature(g, x, y, heading);
    if (ci < 0)
      return false;
    Creature& c = m_cr[static_cast<size_t>(ci)];
    while (c.built < g.numNodes)
      if (!BuildNext(ci))
        break;
    c.structure = c.built * k.cellCost;
    c.energy = k.reserve * 1.5f;
    c.age = RandomInt(0, c.maxAge / 3);
    m_pool -= c.structure + c.energy;
    if (c.built == 0)
    {
      m_pool += c.structure + c.energy;
      c.alive = false;
      m_freeCr.push_back(ci);
      m_numCreatures--;
      return false;
    }
    return true;
  }

  Genome FounderGenome()
  {
    static const int kGrazerColours[] = {0, 1, 4, 5, 6, 2};
    switch (params.world)
    {
      case WORLD_SOUP:
        return RandomGenome();
      case WORLD_GRAZERS:
      {
        static const int kKinds[] = {KIND_WORM, KIND_FLOWER, KIND_RIBBON, KIND_RING, KIND_JELLY, KIND_TADPOLE};
        const int i = RandomInt(0, 5);
        return Species(kKinds[i], (i * 2 + RandomInt(0, 1)) % NUM_COLOURS);
      }
      case WORLD_ECOSYSTEM:
      {
        // every design: grazers of every shape, a few hunters, puffers and viruses
        const int r = RandomInt(0, 23);
        if (r < 3)
          return Species(KIND_HUNTER, 3);
        if (r < 5)
          return Species(KIND_PUFFER, 5);
        if (r < 6)
          return Species(KIND_VIRUS, 2);
        static const int kKinds[] = {KIND_WORM, KIND_FLOWER, KIND_RIBBON, KIND_RING, KIND_JELLY, KIND_TADPOLE};
        const int i = RandomInt(0, 5);
        return Species(kKinds[i], kGrazerColours[(i + RandomInt(0, 1) * 3) % 5]);
      }
      case WORLD_HUNT:
      default:
      {
        // about one hunter in eight; hunters are red, grazers never are
        if (RandomInt(0, 7) == 0)
          return Species(KIND_HUNTER, 3);
        static const int kKinds[] = {KIND_WORM, KIND_FLOWER, KIND_RIBBON, KIND_RING, KIND_JELLY, KIND_TADPOLE};
        const int i = RandomInt(0, 5);
        return Species(kKinds[i], kGrazerColours[(i + RandomInt(0, 1) * 4) % 6]);
      }
    }
  }

  void SpawnFounder()
  {
    // founders start round the sources, where the food is
    const Source& s = m_src[RandomInt(0, m_numSources - 1)];
    std::normal_distribution<float> spread(0.0f, 0.18f * m_h);
    Genome g = FounderGenome();
    if (params.world == WORLD_SOUP && !m_bank.empty() && RandomInt(0, 1) == 0)
    {
      g = m_bank[static_cast<size_t>(RandomInt(0, static_cast<int>(m_bank.size()) - 1))];
      Mutate(g);
    }
    // give each founder group of the same design one lineage so colouring by
    // lineage starts with a few families, not one per founder
    const int key = g.colour * 16 + g.shape;
    bool found = false;
    for (const auto& kv : m_founderLineage)
      if (kv.first == key)
      {
        g.lineage = kv.second;
        found = true;
      }
    if (!found)
      m_founderLineage.emplace_back(key, g.lineage);
    SpawnCreature(g, WrapX(s.x + spread(m_rng)), WrapY(s.y + spread(m_rng)), Uniform(0, 6.2831853f));
  }

  // Kill a creature: its cells start to fall apart and will release its
  // energy as particles. An offspring still attached dies with it.
  void Kill(int ci)
  {
    Creature& c = m_cr[static_cast<size_t>(ci)];
    if (!c.alive)
      return;
    c.alive = false;
    m_numCreatures--;
    m_deaths++;
    const int child = c.child;
    if (c.parent >= 0)
    {
      Creature& p = m_cr[static_cast<size_t>(c.parent)];
      if (p.alive && p.child == ci)
        p.child = -1;
    }
    const float total = c.energy + c.structure + c.depot;
    const float release = std::max(0.0f, total);
    const float overdraw = std::min(0.0f, total);
    m_pool += overdraw; // never happens with sane constants; keeps the books exact
    if (c.built > 0)
    {
      const float each = release / c.built;
      for (int n = 0; n < c.built; n++)
      {
        const int cell = c.cells[n];
        if (cell < 0)
          continue;
        m_state[cell] = CS_DYING;
        m_creature[cell] = -1;
        m_cellE[cell] = each;
        m_tx[cell] = m_ty[cell] = 0.0f;
        m_timer[cell] = static_cast<uint16_t>(60 + (Hash(static_cast<uint32_t>(cell) ^ m_seed) % 90));
      }
    }
    else
      m_pool += release;
    c.energy = c.structure = c.depot = 0.0f;
    c.built = 0;
    m_freeCr.push_back(ci);
    if (child >= 0 && m_cr[static_cast<size_t>(child)].alive && m_cr[static_cast<size_t>(child)].parent == ci)
      Kill(child);
  }

  // A sensor looks around in eight directions at three distances on the
  // coarse density map and reports the strongest one: s0 = how strong,
  // s1 = its angle against the creature's front (-1..1 = -pi..pi).
  void Sense(int cell, int target, int colour, float ax, float ay, float& s0, float& s1) const
  {
    static const float kDist[3] = {4.0f, 9.0f, 15.0f};
    static const float kC[8] = {1, 0.7071f, 0, -0.7071f, -1, -0.7071f, 0, 0.7071f};
    static const float kS[8] = {0, 0.7071f, 1, 0.7071f, 0, -0.7071f, -1, -0.7071f};
    const float x0 = m_x[cell], y0 = m_y[cell];
    const int n = m_dx * m_dy;
    float best = 0.0f;
    int bestDir = -1;
    for (int d = 0; d < 8; d++)
    {
      float score = 0.0f;
      for (int r = 0; r < 3; r++)
      {
        const int ix = DensityX(WrapX(x0 + kC[d] * kDist[r]));
        const int iy = DensityY(WrapY(y0 + kS[d] * kDist[r]));
        const int at = iy * m_dx + ix;
        float v;
        if (target == SENSE_FOOD)
          v = m_food[at];
        else if (target == SENSE_KIN)
          v = m_kin[static_cast<size_t>(colour) * n + at];
        else
          v = static_cast<float>(m_all[at] - m_kin[static_cast<size_t>(colour) * n + at]);
        score += v * (1.0f / (1.0f + 0.12f * kDist[r]));
      }
      if (score > best)
      {
        best = score;
        bestDir = d;
      }
    }
    if (bestDir < 0)
    {
      s0 = 0.0f;
      s1 = 0.0f;
      return;
    }
    const float norm = target == SENSE_FOOD ? 1.0f / (3.0f * k.particleEnergy) : 1.0f / 6.0f;
    s0 = std::min(best * norm, 1.0f);
    // angle of the best direction relative to the forward axis
    const float c = kC[bestDir] * ax + kS[bestDir] * ay;
    const float s = ax * kS[bestDir] - ay * kC[bestDir];
    s1 = std::atan2(s, c) * (1.0f / kPi);
  }

  // The creature's front direction, as ALIEN passes it from the head cell to
  // every other cell: sensors measure angles against it and muscles steer by it.
  void Front(const Creature& c, float& ax, float& ay) const
  {
    ax = std::cos(c.heading);
    ay = std::sin(c.heading);
    if (c.built < 2)
      return;
    switch (c.g.shape)
    {
      case SHAPE_HEX:
        Dir(c.cells[0], c.cells[1], ax, ay);
        break;
      case SHAPE_LOLLI:
        if (c.built > 4)
          Dir(c.cells[4], c.cells[0], ax, ay);
        else
          Dir(c.cells[0], c.cells[1], ax, ay);
        break;
      case SHAPE_FLOWER:
        if (c.built > 6)
          Dir(c.cells[6], c.cells[0], ax, ay);
        else
          Dir(c.cells[0], c.cells[1], ax, ay);
        break;
      case SHAPE_RING:
      {
        float sx = 0, sy = 0;
        for (int n = 0; n < c.built; n++)
        {
          sx += DX(m_x[c.cells[0]], m_x[c.cells[n]]);
          sy += DY(m_y[c.cells[0]], m_y[c.cells[n]]);
        }
        ax = -sx;
        ay = -sy;
        Norm(ax, ay);
        break;
      }
      default:
        Dir(c.cells[1], c.cells[0], ax, ay);
        break;
    }
  }

  // A detonator goes off: everything within the blast radius is pushed away,
  // the closer the harder, and other detonators may go off with it.
  void Blast(int cell)
  {
    const float R = k.blastRadius, R2 = R * R;
    const float x0 = m_x[cell], y0 = m_y[cell];
    const int reach = static_cast<int>(std::ceil(R * m_invG));
    const int cx = CellX(x0), cy = CellY(y0);
    for (int oy = -reach; oy <= reach; oy++)
    {
      const int ry = ((cy + oy) % m_gy + m_gy) % m_gy;
      for (int ox = -reach; ox <= reach; ox++)
      {
        const int rx = ((cx + ox) % m_gx + m_gx) % m_gx;
        const int c = ry * m_gx + rx;
        for (int kk = m_cellStart[c]; kk < m_cellStart[c + 1]; kk++)
        {
          const int o = m_sidx[kk];
          if (o == cell || m_state[o] == CS_FREE || m_state[o] == CS_SOLID)
            continue;
          float dx = DX(x0, m_x[o]), dy = DY(y0, m_y[o]);
          const float d2 = dx * dx + dy * dy;
          if (d2 >= R2 || d2 < 1e-6f)
            continue;
          const float d = std::sqrt(d2);
          const float push = k.blastPush * (1.0f - d / R);
          m_vx[o] += dx / d * push;
          m_vy[o] += dy / d * push;
          m_flash[o] = std::max<uint8_t>(m_flash[o], static_cast<uint8_t>(80 + 170 * (1.0f - d / R)));
          // chain reaction
          if (m_type[o] == CT_DETONATOR && m_state[o] == CS_ALIVE && m_mem0[o] <= 0.0f && m_mem1[o] <= 0.0f &&
              RandomInt(0, 4) == 0)
            m_mem0[o] = 1.0f;
        }
      }
    }
    for (int i = 0; i < m_np; i++)
    {
      const float dx = DX(x0, m_px[i]), dy = DY(y0, m_py[i]);
      const float d2 = dx * dx + dy * dy;
      if (d2 >= R2 || d2 < 1e-6f)
        continue;
      const float d = std::sqrt(d2);
      const float push = 0.6f * k.blastPush * (1.0f - d / R);
      m_pvx[i] += dx / d * push;
      m_pvy[i] += dy / d * push;
    }
    m_flash[cell] = 255;
    m_blasts++;
    AddEvent(EV_BLAST, cell, -1, m_colour[cell]);
  }

  // One cycle of a creature: every cell thinks once (node 0 first, so node n
  // reads what node n+1 had last cycle), then acts.
  void Cycle(int ci)
  {
    Creature& c = m_cr[static_cast<size_t>(ci)];
    const float need = c.g.numNodes * k.cellCost + k.reserve;
    const float en = std::min(c.energy / need, 1.0f);
    const bool free = c.parent < 0;
    float fx, fy;
    Front(c, fx, fy);
    const float frontAngle = std::atan2(fy, fx);
    const size_t mapN = static_cast<size_t>(m_dx) * m_dy;
    for (int n = 0; n < c.built; n++)
    {
      const int cell = c.cells[n];
      const Node& node = c.g.nodes[n];
      float in0 = 0.0f, in1 = 0.0f;
      if (n + 1 < c.built)
      {
        in0 = m_s0[c.cells[n + 1]];
        in1 = m_s1[c.cells[n + 1]];
      }
      float s0 = SoftClip(node.w[0][0] * in0 + node.w[0][1] * in1 + node.w[0][2] * en + node.w[0][3]);
      float s1 = SoftClip(node.w[1][0] * in0 + node.w[1][1] * in1 + node.w[1][2] * en + node.w[1][3]);
      switch (node.type)
      {
        case CT_SENSOR:
          Sense(cell, node.param % SENSE_COUNT, c.g.colour, fx, fy, s0, s1);
          break;
        case CT_GENERATOR:
        {
          const float period = 90.0f * (1 + node.param % 4);
          s0 = std::sin(static_cast<float>(m_step % 100000) * (6.2831853f / period) + c.id);
          break;
        }
        case CT_MEMORY:
        {
          // 0, 1: a slow and a quick running average; 2, 3: hold a strong
          // signal and let it fade slowly
          const int mode = node.param % 4;
          if (mode < 2)
          {
            const float a = mode == 0 ? 0.15f : 0.4f;
            m_mem0[cell] += (s0 - m_mem0[cell]) * a;
            m_mem1[cell] += (s1 - m_mem1[cell]) * a;
          }
          else if (std::fabs(s0) > 0.3f)
          {
            m_mem0[cell] = s0;
            m_mem1[cell] = s1;
          }
          else
          {
            m_mem0[cell] *= mode == 2 ? 0.97f : 0.9f;
            m_mem1[cell] *= mode == 2 ? 0.97f : 0.9f;
          }
          s0 = m_mem0[cell];
          s1 = m_mem1[cell];
          break;
        }
        case CT_COMMUNICATOR:
        {
          const size_t at = static_cast<size_t>(c.g.colour) * mapN +
                            static_cast<size_t>(DensityY(m_y[cell]) * m_dx + DensityX(m_x[cell]));
          if (node.param % 2 == 0)
          {
            // send: the strength and the absolute direction it points to
            if (std::fabs(s0) >= 0.1f && std::fabs(s0) > std::fabs(m_msgS[at]))
            {
              m_msgS[at] = s0;
              m_msgA[at] = frontAngle + s1 * kPi;
            }
          }
          else if (m_msgS[at] != 0.0f)
          {
            // receive: in the own frame of reference
            s0 = m_msgS[at];
            float d = m_msgA[at] - frontAngle;
            d = std::atan2(std::sin(d), std::cos(d));
            s1 = d * (1.0f / kPi);
          }
          break;
        }
        case CT_DEPOT:
          if (s0 >= 0.1f && c.energy > need * 0.6f && c.depot < k.depotMax)
          {
            const float move = std::min({k.depotRate, c.energy - need * 0.6f, k.depotMax - c.depot});
            c.energy -= move;
            c.depot += move;
          }
          else if (s0 <= -0.1f && c.depot > 0.0f)
          {
            const float move = std::min(k.depotRate, c.depot);
            c.depot -= move;
            c.energy += move;
          }
          break;
        case CT_DETONATOR:
          if (m_mem1[cell] > 0.0f)
            m_mem1[cell] = std::max(0.0f, m_mem1[cell] - CYCLE); // cooling down
          else if (m_mem0[cell] > 0.0f)
          {
            // counting down, a cycle at a time; it glows as it goes
            m_flash[cell] = std::max<uint8_t>(m_flash[cell], 160);
            m_mem0[cell] -= 1.0f;
            if (m_mem0[cell] <= 0.0f && c.energy > k.blastCost)
            {
              c.energy -= k.blastCost;
              m_pool += k.blastCost;
              Blast(cell);
              m_mem1[cell] = static_cast<float>(k.blastCooldown + RandomInt(0, k.blastCooldown / 2));
            }
          }
          else if (free && s0 >= 0.6f && c.energy > k.blastCost + k.reserve)
            m_mem0[cell] = 4.0f;
          break;
        default:
          break;
      }
      m_s0[cell] = s0;
      m_s1[cell] = s1;
      m_tx[cell] = m_ty[cell] = 0.0f;
      if (node.type != CT_MUSCLE || !free)
        continue;

      // a muscle: push towards the direction in signal 1, bend or crawl
      const int mode = node.param % MM_COUNT;
      float ax = fx, ay = fy;
      Rot(ax, ay, std::min(std::max(s1, -1.0f), 1.0f) * 0.9f);
      const float strength = 0.35f + 0.65f * s0;
      float mag = k.muscleForce * params.muscle * strength;
      if (mode != MM_DIRECT)
      {
        // a wave travels down the body from head to tail
        const float wave = std::sin(static_cast<float>(m_step % 100000) * 0.045f - n * 0.9f + (c.id & 15));
        const float amp = std::min(std::max(std::fabs(s0), 0.25f), 1.0f);
        if (mode == MM_BEND && c.bendNode[n] >= 0)
          SetRest(cell, c.cells[c.bendNode[n]], c.bendRest[n] * (1.0f + 0.28f * amp * wave));
        else if (c.chainNode[n] >= 0)
          SetRest(cell, c.cells[c.chainNode[n]], c.chainRest[n] * (1.0f + 0.22f * amp * wave));
        // and the strokes push: harder on the power stroke than the return
        mag *= 0.75f * (0.65f + 0.35f * wave);
      }
      m_tx[cell] = ax * mag;
      m_ty[cell] = ay * mag;
    }
  }

  void Construct(int ci)
  {
    Creature& c = m_cr[static_cast<size_t>(ci)];
    if (--c.buildTimer > 0)
      return;
    c.buildTimer = k.buildInterval;
    // own body first (offspring are built by their parent)
    if (c.built < c.g.numNodes)
    {
      if (c.parent >= 0)
        return;
      if (c.energy >= k.cellCost && BuildNext(ci))
      {
        c.energy -= k.cellCost;
        c.structure += k.cellCost;
      }
      return;
    }
    if (c.parent >= 0)
      return;
    if (c.child < 0)
    {
      // start an offspring at the tail end, pointing away from the body; an
      // infected creature builds the genome it was injected with
      Genome g = c.infected ? m_payload[static_cast<size_t>(ci)] : c.g;
      Mutate(g);
      const float need = g.numNodes * k.cellCost + 2.0f * k.reserve;
      if (c.energy + c.depot < need || m_freeCells.size() < static_cast<size_t>(g.numNodes + 8) || m_freeCr.empty())
        return;
      // the depot gives what is missing
      if (c.energy < need)
      {
        const float move = need - c.energy;
        c.depot -= move;
        c.energy += move;
      }
      const int tail = c.cells[c.built - 1];
      float cx = 0, cy = 0;
      for (int n = 0; n < c.built; n++)
      {
        cx += DX(m_x[tail], m_x[c.cells[n]]);
        cy += DY(m_y[tail], m_y[c.cells[n]]);
      }
      float ox = -cx, oy = -cy;
      Norm(ox, oy);
      const int ki = AllocCreature(g, WrapX(m_x[tail] + ox * 1.1f), WrapY(m_y[tail] + oy * 1.1f), std::atan2(oy, ox));
      if (ki < 0)
        return;
      Creature& kid = m_cr[static_cast<size_t>(ki)];
      Creature& parent = m_cr[static_cast<size_t>(ci)];
      kid.parent = ci;
      kid.generation = parent.generation + 1;
      parent.child = ki;
      parent.infected = false;
      if (BuildNext(ki))
      {
        parent.energy -= k.cellCost;
        kid.structure += k.cellCost;
        AddBond(tail, kid.cells[0], 1.1f, k.bondK * 0.5f);
      }
      else
      {
        kid.alive = false;
        m_numCreatures--;
        m_freeCr.push_back(ki);
        parent.child = -1;
      }
      return;
    }
    Creature& kid = m_cr[static_cast<size_t>(c.child)];
    if (kid.built < kid.g.numNodes)
    {
      if (c.energy >= k.cellCost + k.reserve * 0.5f && BuildNext(c.child))
      {
        c.energy -= k.cellCost;
        kid.structure += k.cellCost;
      }
      return;
    }
    // complete: cut the cord and hand over half of what is left
    RemoveBond(c.cells[c.built - 1], kid.cells[0]);
    const float give = std::max(0.0f, (c.energy - k.reserve) * 0.5f) + k.reserve * 0.5f;
    const float moved = std::min(give, std::max(c.energy, 0.0f));
    c.energy -= moved;
    kid.energy += moved;
    kid.parent = -1;
    kid.age = 0;
    c.child = -1;
    c.offspring++;
    m_births++;
    AddEvent(EV_BIRTH, kid.cells[0], -1, kid.g.colour);
    m_bank.resize(std::min<size_t>(m_bank.size() + 1, GENE_BANK));
    m_bank[m_bankNext] = kid.g;
    m_bankNext = (m_bankNext + 1) % GENE_BANK;
  }

  // ---- particles and sources ----------------------------------------------------

  void MoveSources()
  {
    const float t = static_cast<float>(m_step);
    for (int s = 0; s < m_numSources; s++)
    {
      Source& q = m_src[s];
      q.x = WrapX(q.cx + q.rx * std::sin(t * q.fx + q.phase));
      q.y = WrapY(q.cy + q.ry * std::sin(t * q.fy + q.phase * 1.7f));
    }
  }

  // One particle from the pool at source s; `wide` spreads the opening food.
  bool Emit(int s, bool wide = false)
  {
    if (m_np >= static_cast<int>(m_px.size()) || m_pool < k.particleEnergy)
      return false;
    const Source& q = m_src[s];
    std::normal_distribution<float> spread(0.0f, (wide ? 0.16f : 0.07f) * m_h);
    const int i = m_np++;
    m_px[i] = WrapX(q.x + spread(m_rng));
    m_py[i] = WrapY(q.y + spread(m_rng));
    const float a = Uniform(0, 6.2831853f), v = Uniform(0.0f, 0.06f);
    m_pvx[i] = std::cos(a) * v;
    m_pvy[i] = std::sin(a) * v;
    m_pe[i] = k.particleEnergy;
    m_page[i] = wide ? RandomInt(0, k.particleLife / 2) : 0;
    m_pabs[i] = -1;
    m_pool -= k.particleEnergy;
    return true;
  }

  // A free particle at (x, y) carrying e (dying cells).
  void Drop(float x, float y, float e)
  {
    if (e <= 0.0f)
      return;
    if (m_np >= static_cast<int>(m_px.size()))
    {
      m_pool += e;
      return;
    }
    const int i = m_np++;
    m_px[i] = WrapX(x);
    m_py[i] = WrapY(y);
    const float a = Uniform(0, 6.2831853f), v = Uniform(0.01f, 0.08f);
    m_pvx[i] = std::cos(a) * v;
    m_pvy[i] = std::sin(a) * v;
    m_pe[i] = e;
    m_page[i] = 0;
    m_pabs[i] = -1;
  }

  // ---- the passes ------------------------------------------------------------------

  int CellX(float x) const { return std::min(std::max(static_cast<int>(x * m_invG), 0), m_gx - 1); }
  int CellY(float y) const { return std::min(std::max(static_cast<int>(y * m_invG), 0), m_gy - 1); }
  int DensityX(float x) const { return std::min(static_cast<int>(x * m_dx / m_w), m_dx - 1); }
  int DensityY(float y) const { return std::min(static_cast<int>(y * m_dy / m_h), m_dy - 1); }

  void BuildGrid()
  {
    const size_t numCells = static_cast<size_t>(m_gx) * m_gy;
    std::fill(m_cellStart.begin(), m_cellStart.end(), 0);
    const size_t cap = m_x.size();
    for (size_t i = 0; i < cap; i++)
    {
      if (m_state[i] == CS_FREE)
        continue;
      const int c = CellY(m_y[i]) * m_gx + CellX(m_x[i]);
      m_cellOf[i] = c;
      m_cellStart[static_cast<size_t>(c) + 1]++;
    }
    for (size_t c = 0; c < numCells; c++)
      m_cellStart[c + 1] += m_cellStart[c];
    m_fill.assign(m_cellStart.begin(), m_cellStart.end() - 1);
    for (size_t i = 0; i < cap; i++)
    {
      if (m_state[i] == CS_FREE)
        continue;
      const int to = m_fill[static_cast<size_t>(m_cellOf[i])]++;
      m_sx[to] = m_x[i];
      m_sy[to] = m_y[i];
      m_sidx[to] = static_cast<int>(i);
      // the lineage (never 0) for a live cell, SOLID_TAG for rock, 0 for a
      // dying one, which cannot be attacked and eats nothing
      m_stag[to] = m_state[i] == CS_ALIVE ? m_lineage[i] : (m_state[i] == CS_SOLID ? SOLID_TAG : 0);
    }
    m_sorted = static_cast<size_t>(m_cellStart[numCells]);
  }

  // Contacts, bonds, muscles and integration for the sorted cells [a, b).
  // Writes only the cells' own next state.
  void CellRange(size_t a, size_t b)
  {
    const float R = k.radius, R2 = R * R;
    const float A2 = k.attackRange * k.attackRange;
    const float halfW = 0.5f * m_w, halfH = 0.5f * m_h;
    const float* __restrict SX = m_sx.data();
    const float* __restrict SY = m_sy.data();
    const int* __restrict SI = m_sidx.data();
    const uint32_t* __restrict SC = m_stag.data();
    const int* __restrict start = m_cellStart.data();
    const float maxV2 = k.maxSpeed * k.maxSpeed;

    for (size_t i = a; i < b; i++)
    {
      const int o = SI[i];
      const float px = SX[i], py = SY[i];
      if (SC[i] == SOLID_TAG)
      {
        m_nx[o] = px;
        m_ny[o] = py;
        m_nvx[o] = m_nvy[o] = 0.0f;
        m_target[o] = -1;
        continue;
      }
      const int cx = CellX(px), cy = CellY(py);
      const uint8_t t = m_type[o];
      // attackers and injectors look for foreign live cells, reconnectors also for rock
      const bool hunts = (t == CT_ATTACKER || t == CT_INJECTOR || t == CT_RECONNECTOR) && SC[i] != 0;
      // a reconnector with an odd parameter holds on to rock as well
      const bool grabsRock =
          hunts && t == CT_RECONNECTOR && (m_cr[static_cast<size_t>(m_creature[o])].g.nodes[m_node[o]].param & 1) != 0;
      const uint32_t ownTag = SC[i]; // spare the own lineage
      float fx = 0.0f, fy = 0.0f;
      float bestD2 = A2;
      int target = -1;

      for (int oy = -1; oy <= 1; oy++)
      {
        int ry = cy + oy;
        ry = ry < 0 ? ry + m_gy : (ry >= m_gy ? ry - m_gy : ry);
        for (int ox = -1; ox <= 1; ox++)
        {
          int rx = cx + ox;
          rx = rx < 0 ? rx + m_gx : (rx >= m_gx ? rx - m_gx : rx);
          const int c = ry * m_gx + rx;
          const int kEnd = start[c + 1];
          for (int kk = start[c]; kk < kEnd; kk++)
          {
            float dx = SX[kk] - px;
            float dy = SY[kk] - py;
            dx = dx > halfW ? dx - m_w : (dx < -halfW ? dx + m_w : dx);
            dy = dy > halfH ? dy - m_h : (dy < -halfH ? dy + m_h : dy);
            const float d2 = dx * dx + dy * dy;
            if (d2 < R2 && d2 > 1e-8f)
            {
              const float d = std::sqrt(d2);
              // rock pushes twice as hard: it does not give way
              const float f = k.repulse * (SC[kk] == SOLID_TAG ? 2.0f : 1.0f) * (R - d) / d;
              fx -= dx * f;
              fy -= dy * f;
            }
            if (hunts && d2 < bestD2 && SC[kk] != 0 && SC[kk] != ownTag && (SC[kk] != SOLID_TAG || grabsRock))
            {
              bestD2 = d2;
              target = SI[kk];
            }
          }
        }
      }

      const float vx = m_vx[o], vy = m_vy[o];
      const size_t base = static_cast<size_t>(o) * MAX_BONDS;
      for (int s = 0; s < m_bondN[o]; s++)
      {
        const int q = m_bondTo[base + s];
        float dx = m_x[q] - px, dy = m_y[q] - py;
        dx = dx > halfW ? dx - m_w : (dx < -halfW ? dx + m_w : dx);
        dy = dy > halfH ? dy - m_h : (dy < -halfH ? dy + m_h : dy);
        const float d2 = dx * dx + dy * dy;
        if (d2 < 1e-10f)
          continue;
        const float inv = 1.0f / std::sqrt(d2);
        const float d = d2 * inv;
        const float rel = ((m_vx[q] - vx) * dx + (m_vy[q] - vy) * dy) * inv;
        // a bond to rock (a reconnector's hold) acts as an ordinary bond on
        // this side; rock has bondK 0 among its own cells
        const float kk = m_bondK[base + s] > 0.0f ? m_bondK[base + s] : k.bondK * 0.5f;
        const float f = (kk * (d - m_bondRest[base + s]) + k.bondDamp * rel) * inv;
        fx += dx * f;
        fy += dy * f;
      }

      float nvx = (vx + fx + m_tx[o]) * k.friction;
      float nvy = (vy + fy + m_ty[o]) * k.friction;
      const float v2 = nvx * nvx + nvy * nvy;
      if (v2 > maxV2)
      {
        const float s = k.maxSpeed / std::sqrt(v2);
        nvx *= s;
        nvy *= s;
      }
      m_nvx[o] = nvx;
      m_nvy[o] = nvy;
      m_nx[o] = WrapX(px + nvx);
      m_ny[o] = WrapY(py + nvy);
      m_target[o] = target;
    }
  }

  // Drift the energy particles [a, b) and find the live cell (if any) that
  // eats each one; rock turns them away. Writes only the particles' own state.
  void ParticleRange(size_t a, size_t b)
  {
    const float R2 = k.absorbRange * k.absorbRange;
    const float halfW = 0.5f * m_w, halfH = 0.5f * m_h;
    const int* start = m_cellStart.data();
    const uint32_t salt = static_cast<uint32_t>(m_step) * 0x9e3779b9u ^ m_seed;
    for (size_t i = a; i < b; i++)
    {
      const uint32_t h = Hash(static_cast<uint32_t>(i) * 0x85ebca6bu ^ salt);
      m_pvx[i] = m_pvx[i] * 0.985f + HashSigned(h) * 0.0025f;
      m_pvy[i] = m_pvy[i] * 0.985f + HashSigned(Hash(h)) * 0.0025f;
      const float px = WrapX(m_px[i] + m_pvx[i]);
      const float py = WrapY(m_py[i] + m_pvy[i]);
      m_px[i] = px;
      m_py[i] = py;
      const int cx = CellX(px), cy = CellY(py);
      int eater = -1;
      float best = R2;
      for (int oy = -1; oy <= 1; oy++)
      {
        int ry = cy + oy;
        ry = ry < 0 ? ry + m_gy : (ry >= m_gy ? ry - m_gy : ry);
        for (int ox = -1; ox <= 1; ox++)
        {
          int rx = cx + ox;
          rx = rx < 0 ? rx + m_gx : (rx >= m_gx ? rx - m_gx : rx);
          const int c = ry * m_gx + rx;
          for (int kk = start[c]; kk < start[c + 1]; kk++)
          {
            if (m_stag[kk] == 0)
              continue;
            float dx = m_sx[kk] - px, dy = m_sy[kk] - py;
            dx = dx > halfW ? dx - m_w : (dx < -halfW ? dx + m_w : dx);
            dy = dy > halfH ? dy - m_h : (dy < -halfH ? dy + m_h : dy);
            const float d2 = dx * dx + dy * dy;
            if (m_stag[kk] == SOLID_TAG)
            {
              if (d2 < 0.81f && d2 > 1e-8f)
              {
                const float inv = 0.02f / std::sqrt(d2);
                m_pvx[i] -= dx * inv;
                m_pvy[i] -= dy * inv;
              }
              continue;
            }
            if (d2 < best)
            {
              best = d2;
              eater = m_sidx[kk];
            }
          }
        }
      }
      m_pabs[i] = eater;
    }
  }

  void BuildDensity()
  {
    std::fill(m_food.begin(), m_food.end(), 0.0f);
    std::fill(m_kin.begin(), m_kin.end(), 0);
    std::fill(m_all.begin(), m_all.end(), 0);
    for (int i = 0; i < m_np; i++)
      m_food[static_cast<size_t>(DensityY(m_py[i]) * m_dx + DensityX(m_px[i]))] += m_pe[i];
    const size_t n = static_cast<size_t>(m_dx) * m_dy;
    for (size_t i = 0; i < m_x.size(); i++)
      if (m_state[i] == CS_ALIVE)
      {
        const size_t at = static_cast<size_t>(DensityY(m_y[i]) * m_dx + DensityX(m_x[i]));
        m_all[at]++;
        m_kin[m_cr[static_cast<size_t>(m_creature[i])].g.colour * n + at]++;
      }
    // messages fade unless they are sent again
    for (float& s : m_msgS)
      s = std::fabs(s) < 0.02f ? 0.0f : s * 0.9f;
  }

  // Everything that is not per element: eating, attacks, creature cycles,
  // building, death, decay, emission. Serial and in a fixed order, so the
  // result does not depend on the number of threads.
  void Commit()
  {
    m_x.swap(m_nx);
    m_y.swap(m_ny);
    m_vx.swap(m_nvx);
    m_vy.swap(m_nvy);
    m_step++;

    // events age; beams follow their cells
    size_t keep = 0;
    for (size_t e = 0; e < m_events.size(); e++)
    {
      Event& ev = m_events[e];
      if (++ev.age >= kEventLife[ev.kind])
        continue;
      if (ev.a >= 0 && m_state[ev.a] != CS_FREE)
      {
        ev.x0 = m_x[ev.a];
        ev.y0 = m_y[ev.a];
      }
      if (ev.b >= 0 && m_state[ev.b] != CS_FREE)
      {
        ev.x1 = m_x[ev.b];
        ev.y1 = m_y[ev.b];
      }
      m_events[keep++] = ev;
    }
    m_events.resize(keep);

    // eating: raw energy needs digestors, as in ALIEN. A digestor keeps all
    // of a particle, another cell of a creature with digestors 60 % (the
    // energy travels to them through the body), a creature without any 10 %;
    // the rest goes back to the pool and the sources
    for (int i = 0; i < m_np; i++)
    {
      const int cell = m_pabs[i];
      if (cell < 0 || m_state[cell] != CS_ALIVE)
        continue;
      Creature& c = m_cr[static_cast<size_t>(m_creature[cell])];
      const float keepE = m_type[cell] == CT_DIGESTOR ? 1.0f : (c.digestors > 0 ? 0.6f : 0.1f);
      c.energy += m_pe[i] * keepE;
      m_pool += m_pe[i] * (1.0f - keepE);
      m_pe[i] = -1.0f;
      m_flash[cell] = 255;
    }
    // particles: remove the eaten, decay the old
    int out = 0;
    for (int i = 0; i < m_np; i++)
    {
      if (m_pe[i] < 0.0f)
        continue;
      if (++m_page[i] > k.particleLife)
      {
        m_pool += m_pe[i];
        continue;
      }
      if (out != i)
      {
        m_px[out] = m_px[i];
        m_py[out] = m_py[i];
        m_pvx[out] = m_pvx[i];
        m_pvy[out] = m_pvy[i];
        m_pe[out] = m_pe[i];
        m_page[out] = m_page[i];
      }
      out++;
    }
    m_np = out;

    // cells: attacks, injections and grabs (once a cycle each), flashes, the dying
    const size_t cap = m_x.size();
    for (size_t i = 0; i < cap; i++)
    {
      const uint8_t st = m_state[i];
      if (st == CS_FREE || st == CS_SOLID)
        continue;
      m_flash[i] = static_cast<uint8_t>(m_flash[i] > 10 ? m_flash[i] - 10 : 0);
      if (st == CS_DYING)
      {
        if (--m_timer[i] == 0)
        {
          float e = m_cellE[i];
          const int parts = e > 2.5f * k.particleEnergy ? 3 : (e > 1.5f * k.particleEnergy ? 2 : 1);
          for (int p = 0; p < parts; p++)
            Drop(m_x[i] + Uniform(-0.4f, 0.4f), m_y[i] + Uniform(-0.4f, 0.4f), e / parts);
          m_cellE[i] = 0.0f;
          FreeCell(static_cast<int>(i));
        }
        continue;
      }
      const uint8_t type = m_type[i];
      if (type != CT_ATTACKER && type != CT_INJECTOR && type != CT_RECONNECTOR)
        continue;
      if ((m_step + i) % CYCLE != 0)
        continue;
      Creature& hunter = m_cr[static_cast<size_t>(m_creature[i])];
      if (type == CT_RECONNECTOR)
      {
        Reconnect(static_cast<int>(i), hunter);
        continue;
      }
      const int t = m_target[i];
      if (t < 0 || m_state[t] != CS_ALIVE || m_creature[t] < 0)
        continue;
      const int preyCi = m_creature[t];
      Creature& prey = m_cr[static_cast<size_t>(preyCi)];
      if (type == CT_ATTACKER)
      {
        if (m_s0[i] <= -0.2f)
          continue;
        const float stock = std::max(prey.energy, 0.0f) + prey.depot;
        const float amount = std::min(k.attack / (1.0f + prey.defenders), stock);
        if (amount > 0.0f)
        {
          // usable energy first, then the depot
          const float fromE = std::min(amount, std::max(prey.energy, 0.0f));
          prey.energy -= fromE;
          prey.depot -= amount - fromE;
          const float keepE = hunter.digestors > 0 ? 0.85f : 0.5f;
          hunter.energy += amount * keepE;
          m_pool += amount * (1.0f - keepE);
          m_flash[i] = 255;
          m_flash[t] = std::max<uint8_t>(m_flash[t], 200);
          m_attacks++;
          AddEvent(EV_ATTACK, static_cast<int>(i), t, m_colour[i]);
        }
      }
      else if (m_s0[i] >= 0.1f && !prey.infected && prey.parent < 0)
      {
        // an injector writes its genome into the prey's constructor: the
        // prey's next offspring is one of the injector's kind
        const float cost = k.injectCost * (1.0f + 0.5f * prey.defenders);
        if (hunter.energy < cost + k.reserve)
          continue;
        hunter.energy -= cost;
        m_pool += cost;
        m_payload[static_cast<size_t>(preyCi)] = hunter.g;
        prey.infected = true;
        m_flash[i] = 255;
        for (int n = 0; n < prey.built; n++)
          m_flash[prey.cells[n]] = std::max<uint8_t>(m_flash[prey.cells[n]], 180);
        m_injections++;
        AddEvent(EV_INJECT, static_cast<int>(i), t, m_colour[i]);
      }
    }

    // creatures
    for (size_t ci = 0; ci < m_cr.size(); ci++)
    {
      Creature& c = m_cr[ci];
      if (!c.alive)
        continue;
      if (c.parent < 0)
      {
        // upkeep: being alive (worth two cells, so tiny creatures are no
        // free lunch), every cell, and muscles, attackers and injectors twice
        float cost = 2.0f;
        for (int n = 0; n < c.built; n++)
        {
          const uint8_t t = m_type[c.cells[n]];
          cost += t == CT_MUSCLE || t == CT_ATTACKER || t == CT_INJECTOR ? 2.0f : 1.0f;
        }
        cost *= k.upkeep;
        c.energy -= cost;
        m_pool += cost;
        c.age++;
        // a starving creature draws on its depot first
        if (c.energy < 0.0f && c.depot > 0.0f)
        {
          const float move = std::min(c.depot, -c.energy + k.cellCost * 0.25f);
          c.depot -= move;
          c.energy += move;
        }
        if (c.energy < 0.0f || c.age > c.maxAge || c.built == 0)
        {
          Kill(static_cast<int>(ci));
          continue;
        }
      }
      if ((m_step + ci) % CYCLE == 0)
        Cycle(static_cast<int>(ci));
      Construct(static_cast<int>(ci));
    }

    // radiation sources
    MoveSources();
    const int emit = 2 + static_cast<int>(m_px.size() / 400);
    for (int e = 0; e < emit; e++)
      if (!Emit(static_cast<int>((m_step * 7 + e) % m_numSources)))
        break;

    // a world never stays empty: when the creatures die out, new ones
    // (from the gene bank or the world's designs) start from the pool
    if (m_step % 120 == 0 && m_numCreatures < std::max(4, params.initialCreatures / 6))
      for (int i = 0; i < 3; i++)
        SpawnFounder();

    BuildDensity();
  }

  // A reconnector: a positive signal takes hold of the foreign cell or rock
  // in reach, a negative one lets go of everything foreign; a hold that is
  // stretched too far breaks.
  void Reconnect(int cell, Creature& c)
  {
    const size_t base = static_cast<size_t>(cell) * MAX_BONDS;
    const int own = m_creature[cell];
    for (int s = m_bondN[cell] - 1; s >= 0; s--)
    {
      const int q = m_bondTo[base + s];
      if (m_creature[q] == own)
        continue;
      if (m_s0[cell] <= -0.1f || Dist(cell, q) > 3.0f || m_state[q] == CS_DYING)
        RemoveBond(cell, q);
    }
    const int t = m_target[cell];
    if (m_s0[cell] < 0.1f || t < 0 || c.parent >= 0 || m_state[t] == CS_FREE || m_state[t] == CS_DYING)
      return;
    if (Bonded(cell, t))
      return;
    // one foreign hold at a time
    for (int s = 0; s < m_bondN[cell]; s++)
      if (m_creature[m_bondTo[base + s]] != own)
        return;
    if (AddBond(cell, t, std::max(Dist(cell, t), 0.9f), k.bondK * 0.6f))
    {
      m_flash[cell] = 255;
      m_grabs++;
      AddEvent(EV_GRAB, cell, t, m_colour[cell]);
    }
  }

  std::mt19937 m_rng;
  uint32_t m_seed = 1;
  float m_w = 266, m_h = 150, m_invG = 1;
  int m_gx = 1, m_gy = 1;

  // cells (slots; m_state says which are in use)
  std::vector<float> m_x, m_y, m_vx, m_vy, m_nx, m_ny, m_nvx, m_nvy, m_tx, m_ty, m_s0, m_s1, m_cellE;
  std::vector<float> m_mem0, m_mem1; // memory cells' values, detonators' countdown and cooldown
  std::vector<int> m_creature, m_target;
  std::vector<uint8_t> m_node, m_type, m_state, m_colour, m_flash, m_bondN;
  std::vector<uint32_t> m_lineage;
  std::vector<uint16_t> m_timer;
  std::vector<int> m_bondTo;
  std::vector<float> m_bondRest, m_bondK;
  std::vector<int> m_freeCells;
  int m_liveCells = 0, m_solidCells = 0;

  std::vector<Creature> m_cr;
  std::vector<Genome> m_payload; // injected genomes, by creature
  std::vector<int> m_freeCr;
  int m_numCreatures = 0;

  // energy particles (packed, 0..m_np)
  std::vector<float> m_px, m_py, m_pvx, m_pvy, m_pe;
  std::vector<int> m_page, m_pabs;
  int m_np = 0;

  Source m_src[6];
  int m_numSources = 1;

  // contact grid
  std::vector<int> m_cellStart, m_cellOf, m_fill, m_sidx;
  std::vector<float> m_sx, m_sy;
  std::vector<uint32_t> m_stag;
  size_t m_sorted = 0;

  // sensor maps, and the communicators' messages per colour
  int m_dx = 1, m_dy = 1;
  std::vector<float> m_food;
  std::vector<uint16_t> m_kin, m_all;
  std::vector<float> m_msgS, m_msgA;

  std::vector<Event> m_events;

  std::vector<Genome> m_bank;
  size_t m_bankNext = 0;
  std::vector<std::pair<int, uint32_t>> m_founderLineage;

  double m_pool = 0, m_budget = 0;
  uint64_t m_step = 0;
  uint32_t m_nextId = 1, m_nextLineage = 1;
  long m_births = 0, m_deaths = 0;
  long m_blasts = 0, m_injections = 0, m_grabs = 0, m_attacks = 0;
};

} // namespace alien

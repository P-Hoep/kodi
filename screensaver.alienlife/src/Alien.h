// Alien Life simulation core - no Kodi / OpenGL dependencies.
//
// A small CPU take on ALIEN (Christian Heinemann's GPU artificial life
// simulator, https://github.com/chrxh/alien, BSD-3): creatures are networks of
// round cells held together by elastic connections, built cell by cell from a
// genome. Every cell has a type (sensor, muscle, attacker, digestor, ...) and
// a tiny neural network; signals travel from the last node of the genome
// towards node 0, one cell per cycle, so a sensor at the tail steers the
// muscles in front of it. Creatures eat free energy particles that radiation
// sources emit, attack creatures of other lineages, and build offspring at
// their tail, which separate when complete and carry a mutated genome. Energy
// never appears out of nothing: a fixed budget circulates between an external
// pool, the energy particles and the creatures.
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

constexpr int MAX_NODES = 14;
constexpr int MAX_BONDS = 8;
constexpr int NUM_COLOURS = 7;
constexpr int CYCLE = 6;
constexpr int GENE_BANK = 48;
constexpr float kPi = 3.14159265f;

enum CellType : uint8_t
{
  CT_BASE,
  CT_SENSOR,
  CT_MUSCLE,
  CT_GENERATOR,
  CT_ATTACKER,
  CT_DIGESTOR,
  CT_DEFENDER,
  CT_COUNT
};

enum Shape : uint8_t
{
  SHAPE_WORM,   // a chain that bends at every node
  SHAPE_RIBBON, // a strip of triangles, stiff
  SHAPE_RING,   // a closed chain
  SHAPE_FLOWER, // six petals round node 0, then a tail
  SHAPE_COUNT
};

enum SenseTarget : uint8_t
{
  SENSE_FOOD, // energy particles
  SENSE_PREY, // cells of other colours
  SENSE_KIN,  // cells of the own colour
  SENSE_COUNT
};

// Index order is the "world" setting minus one (0 there = a random one).
enum WorldKind
{
  WORLD_GRAZERS,
  WORLD_HUNT,
  WORLD_SOUP,
  WORLD_COUNT
};

enum CellState : uint8_t
{
  CS_FREE,
  CS_ALIVE,
  CS_DYING
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
  uint8_t param = 0; // sensor: SenseTarget; generator: period index
  float angle = 0;   // bend at this node (worm, flower tail), curve (ribbon)
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
  int built = 0;
  bool alive = false;
  float energy = 0;    // usable energy
  float structure = 0; // energy that went into its cells
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
    for (auto* v : {&m_x, &m_y, &m_vx, &m_vy, &m_nx, &m_ny, &m_nvx, &m_nvy, &m_tx, &m_ty, &m_s0, &m_s1, &m_cellE})
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

    m_cr.assign(n / 2, Creature());
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

    m_step = 0;
    m_nextId = 1;
    m_nextLineage = 1;
    m_bank.clear();
    m_founderLineage.clear();
    m_bankNext = 0;
    m_births = m_deaths = 0;

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
  int numCreatures() const { return m_numCreatures; }
  uint64_t steps() const { return m_step; }
  long births() const { return m_births; }
  long deaths() const { return m_deaths; }
  double pool() const { return m_pool; }
  double budget() const { return m_budget; }
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

  // Every unit of energy in the world; stays equal to budget().
  double TotalEnergy() const
  {
    double e = m_pool;
    for (int i = 0; i < m_np; i++)
      e += m_pe[i];
    for (const Creature& c : m_cr)
      if (c.alive)
        e += c.energy + c.structure;
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
    return std::min(std::max(cr.energy / need, 0.0f), 1.0f);
  }

  float Uniform(float a, float b) { return std::uniform_real_distribution<float>(a, b)(m_rng); }
  int RandomInt(int lo, int hi) { return std::uniform_int_distribution<int>(lo, hi)(m_rng); }

  // ---- genomes -----------------------------------------------------------------

  // A designed species: `kind` 0 worm grazer, 1 flower grazer, 2 ribbon grazer,
  // 3 ring grazer, 4 hunter.
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
    switch (kind)
    {
      case 0:
        g.shape = SHAPE_WORM;
        set({CT_MUSCLE, CT_BASE, CT_DIGESTOR, CT_MUSCLE, CT_BASE, CT_SENSOR});
        for (int i = 1; i < g.numNodes; i++)
          g.nodes[i].angle = Uniform(-0.5f, 0.5f);
        break;
      case 1:
        g.shape = SHAPE_FLOWER;
        set({CT_DIGESTOR, CT_MUSCLE, CT_BASE, CT_GENERATOR, CT_MUSCLE, CT_BASE, CT_SENSOR});
        g.nodes[3].param = static_cast<uint8_t>(RandomInt(0, 3));
        break;
      case 2:
        g.shape = SHAPE_RIBBON;
        set({CT_MUSCLE, CT_MUSCLE, CT_DIGESTOR, CT_BASE, CT_DEFENDER, CT_BASE, CT_SENSOR, CT_BASE});
        for (int i = 1; i < g.numNodes; i++)
          g.nodes[i].angle = Uniform(-0.25f, 0.25f);
        // the sensor sits on node 6; let node 7 pass it a neutral signal
        break;
      case 3:
        g.shape = SHAPE_RING;
        set({CT_DIGESTOR, CT_MUSCLE, CT_BASE, CT_DIGESTOR, CT_MUSCLE, CT_BASE, CT_GENERATOR, CT_SENSOR});
        g.nodes[6].param = static_cast<uint8_t>(RandomInt(0, 3));
        break;
      default:
        g.shape = SHAPE_WORM;
        set({CT_ATTACKER, CT_MUSCLE, CT_BASE, CT_MUSCLE, CT_BASE, CT_SENSOR});
        for (int i = 1; i < g.numNodes; i++)
          g.nodes[i].angle = Uniform(-0.3f, 0.3f);
        break;
    }
    for (int i = 0; i < g.numNodes; i++)
      if (g.nodes[i].type == CT_SENSOR)
        g.nodes[i].param = kind == 4 ? SENSE_PREY : SENSE_FOOD;
    g.lineage = m_nextLineage++;
    return g;
  }

  Genome RandomGenome()
  {
    Genome g;
    g.colour = static_cast<uint8_t>(RandomInt(0, NUM_COLOURS - 1));
    g.shape = static_cast<uint8_t>(RandomInt(0, SHAPE_COUNT - 1));
    g.numNodes = RandomInt(3, 10);
    for (int i = 0; i < g.numNodes; i++)
    {
      Node& n = g.nodes[i];
      n.type = static_cast<uint8_t>(RandomInt(0, CT_COUNT - 1));
      n.param = static_cast<uint8_t>(RandomInt(0, 3));
      if (n.type == CT_SENSOR)
        n.param = static_cast<uint8_t>(RandomInt(0, SENSE_COUNT - 1));
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
      if (r < 0.45f)
        node.w[RandomInt(0, 1)][RandomInt(0, 3)] += std::normal_distribution<float>(0.0f, 0.45f)(m_rng);
      else if (r < 0.60f)
        node.angle = std::min(std::max(node.angle + Uniform(-0.4f, 0.4f), -1.2f), 1.2f);
      else if (r < 0.72f)
      {
        node.type = static_cast<uint8_t>(RandomInt(0, CT_COUNT - 1));
        if (node.type == CT_SENSOR)
          node.param = static_cast<uint8_t>(RandomInt(0, SENSE_COUNT - 1));
      }
      else if (r < 0.78f)
        node.param = static_cast<uint8_t>(node.type == CT_SENSOR ? RandomInt(0, SENSE_COUNT - 1) : RandomInt(0, 3));
      else if (r < 0.87f && g.numNodes < MAX_NODES)
      {
        const int at = RandomInt(1, g.numNodes);
        for (int i = g.numNodes; i > at; i--)
          g.nodes[i] = g.nodes[i - 1];
        g.nodes[at] = Node();
        g.nodes[at].type = static_cast<uint8_t>(RandomInt(0, CT_COUNT - 1));
        g.nodes[at].angle = Uniform(-0.4f, 0.4f);
        g.numNodes++;
      }
      else if (r < 0.96f && g.numNodes > 3)
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

  // ---- cells and bonds -----------------------------------------------------------

  int AllocCell(float x, float y, int cr, int node, const Node& n, int colour)
  {
    if (m_freeCells.empty())
      return -1;
    const int i = m_freeCells.back();
    m_freeCells.pop_back();
    m_x[i] = WrapX(x);
    m_y[i] = WrapY(y);
    m_vx[i] = m_vy[i] = m_tx[i] = m_ty[i] = m_s0[i] = m_s1[i] = m_cellE[i] = 0.0f;
    m_creature[i] = cr;
    m_node[i] = static_cast<uint8_t>(node);
    m_type[i] = n.type;
    m_state[i] = CS_ALIVE;
    m_colour[i] = static_cast<uint8_t>(colour);
    m_lineage[i] = m_cr[static_cast<size_t>(cr)].g.lineage;
    m_flash[i] = 140; // a new cell lights up as it is built
    m_timer[i] = 0;
    m_bondN[i] = 0;
    m_target[i] = -1;
    m_liveCells++;
    return i;
  }

  bool AddBond(int a, int b, float rest, float kk)
  {
    if (a < 0 || b < 0 || a == b || m_bondN[a] >= MAX_BONDS || m_bondN[b] >= MAX_BONDS)
      return false;
    for (int s = 0; s < m_bondN[a]; s++)
      if (m_bondTo[a * MAX_BONDS + s] == b)
        return false;
    const size_t sa = static_cast<size_t>(a) * MAX_BONDS + m_bondN[a]++;
    const size_t sb = static_cast<size_t>(b) * MAX_BONDS + m_bondN[b]++;
    m_bondTo[sa] = b;
    m_bondTo[sb] = a;
    m_bondRest[sa] = m_bondRest[sb] = rest;
    m_bondK[sa] = m_bondK[sb] = kk;
    return true;
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
    for (int& cell : c.cells)
      cell = -1;
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
    int links[3] = {-1, -1, -1};
    float stiff[3] = {k.bondK, k.bondK, k.bondK};
    float fixedRest[3] = {1.0f, -1.0f, -1.0f}; // -1: rest = distance as placed

    auto chain = [&](int prev, float dx, float dy) {
      Rot(dx, dy, node.angle);
      px = m_x[P(prev)] + dx;
      py = m_y[P(prev)] + dy;
    };

    if (kNode > 0)
    {
      const float hx = std::cos(c.heading), hy = std::sin(c.heading);
      switch (g.shape)
      {
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
      m_vx[cell] = m_vx[P(kNode - 1)];
      m_vy[cell] = m_vy[P(kNode - 1)];
    }
    for (int l = 0; l < 3; l++)
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
      AddBond(cell, other, rest, stiff[l]);
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
    switch (params.world)
    {
      case WORLD_SOUP:
        return RandomGenome();
      case WORLD_GRAZERS:
      {
        const int kind = RandomInt(0, 3);
        return Species(kind, (kind * 2 + RandomInt(0, 1)) % NUM_COLOURS);
      }
      case WORLD_HUNT:
      default:
      {
        // about one hunter in eight; hunters are red, grazers never are
        if (RandomInt(0, 7) == 0)
          return Species(4, 3);
        const int kind = RandomInt(0, 3);
        static const int kGrazerColours[] = {0, 1, 4, 5, 6, 2};
        return Species(kind, kGrazerColours[(kind + RandomInt(0, 1) * 4) % 6]);
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
    // species share a lineage per kind and colour only by chance; give each
    // founder group of the same design one lineage so colouring by lineage
    // starts with a few families, not one per founder
    for (const auto& kv : m_founderLineage)
      if (kv.first == g.colour * 16 + g.shape)
        g.lineage = kv.second;
    if (std::find_if(m_founderLineage.begin(), m_founderLineage.end(),
                     [&](const std::pair<int, uint32_t>& kv) { return kv.first == g.colour * 16 + g.shape; }) ==
        m_founderLineage.end())
      m_founderLineage.emplace_back(g.colour * 16 + g.shape, g.lineage);
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
    const float release = std::max(0.0f, c.energy + c.structure);
    const float overdraw = std::min(0.0f, c.energy + c.structure);
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
    c.energy = c.structure = 0.0f;
    c.built = 0;
    m_freeCr.push_back(ci);
    if (child >= 0 && m_cr[static_cast<size_t>(child)].alive && m_cr[static_cast<size_t>(child)].parent == ci)
      Kill(child);
  }

  // A sensor looks around in eight directions at three distances on the
  // coarse density map and reports the strongest one: s0 = how strong,
  // s1 = its angle against the cell's forward axis (-1..1 = -pi..pi).
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

  // forward axis of node n: towards node 0, the head
  void Forward(const Creature& c, int n, float& ax, float& ay) const
  {
    if (n > 0)
      Dir(c.cells[n], c.cells[n - 1], ax, ay);
    else if (c.built > 1)
      Dir(c.cells[1], c.cells[0], ax, ay);
    else
    {
      ax = std::cos(c.heading);
      ay = std::sin(c.heading);
    }
  }

  // One cycle of a creature: every cell thinks once (node 0 first, so node n
  // reads what node n+1 had last cycle), then acts.
  void Cycle(Creature& c)
  {
    const float en = std::min(c.energy / (c.g.numNodes * k.cellCost + k.reserve), 1.0f);
    const bool free = c.parent < 0;
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
      float ax = 0.0f, ay = 0.0f;
      if (node.type == CT_SENSOR || node.type == CT_MUSCLE)
        Forward(c, n, ax, ay);
      switch (node.type)
      {
        case CT_SENSOR:
          Sense(cell, node.param % SENSE_COUNT, c.g.colour, ax, ay, s0, s1);
          break;
        case CT_GENERATOR:
        {
          const float period = 90.0f * (1 + node.param % 4);
          s0 = std::sin(static_cast<float>(m_step % 100000) * (6.2831853f / period) + c.id);
          break;
        }
        default:
          break;
      }
      m_s0[cell] = s0;
      m_s1[cell] = s1;
      if (node.type == CT_MUSCLE && free)
      {
        Rot(ax, ay, std::min(std::max(s1, -1.0f), 1.0f) * 0.9f);
        const float mag = k.muscleForce * params.muscle * (0.35f + 0.65f * s0);
        m_tx[cell] = ax * mag;
        m_ty[cell] = ay * mag;
      }
      else
        m_tx[cell] = m_ty[cell] = 0.0f;
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
      // start an offspring at the tail end, pointing away from the body
      Genome g = c.g;
      Mutate(g);
      const float need = g.numNodes * k.cellCost + 2.0f * k.reserve;
      if (c.energy < need || m_freeCells.size() < static_cast<size_t>(g.numNodes + 8) || m_freeCr.empty())
        return;
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
      Creature& parent = m_cr[static_cast<size_t>(ci)]; // (no reallocation, but be explicit)
      kid.parent = ci;
      kid.generation = parent.generation + 1;
      parent.child = ki;
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
    m_bank.resize(std::min<size_t>(m_bank.size() + 1, GENE_BANK));
    m_bank[m_bankNext] = c.g;
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
      // the lineage (never 0) for a live cell, 0 for a dying one, which
      // cannot be attacked and eats nothing
      m_stag[to] = m_state[i] == CS_ALIVE ? m_lineage[i] : 0;
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
      const int cx = CellX(px), cy = CellY(py);
      const bool attacker = m_type[o] == CT_ATTACKER && SC[i] != 0;
      const uint32_t ownTag = SC[i]; // attackers spare their own lineage
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
              const float f = k.repulse * (R - d) / d;
              fx -= dx * f;
              fy -= dy * f;
            }
            if (attacker && d2 < bestD2 && SC[kk] != 0 && SC[kk] != ownTag)
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
        const float f = (m_bondK[base + s] * (d - m_bondRest[base + s]) + k.bondDamp * rel) * inv;
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
  // eats each one. Writes only the particles' own state.
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
        m_kin[m_colour[i] * n + at]++;
      }
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
      const float keep = m_type[cell] == CT_DIGESTOR ? 1.0f : (c.digestors > 0 ? 0.6f : 0.1f);
      c.energy += m_pe[i] * keep;
      m_pool += m_pe[i] * (1.0f - keep);
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

    // cells: attacks (once a cycle each), flashes, the dying
    const size_t cap = m_x.size();
    for (size_t i = 0; i < cap; i++)
    {
      if (m_state[i] == CS_FREE)
        continue;
      m_flash[i] = static_cast<uint8_t>(m_flash[i] > 10 ? m_flash[i] - 10 : 0);
      if (m_state[i] == CS_DYING)
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
      const int t = m_target[i];
      if (t >= 0 && (m_step + i) % CYCLE == 0 && m_s0[i] > -0.2f && m_state[t] == CS_ALIVE && m_creature[t] >= 0)
      {
        Creature& prey = m_cr[static_cast<size_t>(m_creature[t])];
        Creature& hunter = m_cr[static_cast<size_t>(m_creature[i])];
        const float amount = std::min(k.attack / (1.0f + prey.defenders), std::max(prey.energy, 0.0f));
        if (amount > 0.0f)
        {
          prey.energy -= amount;
          const float keep = hunter.digestors > 0 ? 0.85f : 0.5f;
          hunter.energy += amount * keep;
          m_pool += amount * (1.0f - keep);
          m_flash[i] = 255;
          m_flash[t] = std::max<uint8_t>(m_flash[t], 200);
        }
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
        // free lunch), every cell, and muscles and attackers twice
        float cost = 2.0f;
        for (int n = 0; n < c.built; n++)
          cost += m_type[c.cells[n]] == CT_MUSCLE || m_type[c.cells[n]] == CT_ATTACKER ? 2.0f : 1.0f;
        cost *= k.upkeep;
        c.energy -= cost;
        m_pool += cost;
        c.age++;
        if (c.energy < 0.0f || c.age > c.maxAge || c.built == 0)
        {
          Kill(static_cast<int>(ci));
          continue;
        }
      }
      if ((m_step + ci) % CYCLE == 0)
        Cycle(c);
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

  std::mt19937 m_rng;
  uint32_t m_seed = 1;
  float m_w = 266, m_h = 150, m_invG = 1;
  int m_gx = 1, m_gy = 1;

  // cells (slots; m_state says which are in use)
  std::vector<float> m_x, m_y, m_vx, m_vy, m_nx, m_ny, m_nvx, m_nvy, m_tx, m_ty, m_s0, m_s1, m_cellE;
  std::vector<int> m_creature, m_target;
  std::vector<uint8_t> m_node, m_type, m_state, m_colour, m_flash, m_bondN;
  std::vector<uint32_t> m_lineage;
  std::vector<uint16_t> m_timer;
  std::vector<int> m_bondTo;
  std::vector<float> m_bondRest, m_bondK;
  std::vector<int> m_freeCells;
  int m_liveCells = 0;

  std::vector<Creature> m_cr;
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

  // sensor maps
  int m_dx = 1, m_dy = 1;
  std::vector<float> m_food;
  std::vector<uint16_t> m_kin, m_all;

  std::vector<Genome> m_bank;
  size_t m_bankNext = 0;
  std::vector<std::pair<int, uint32_t>> m_founderLineage;

  double m_pool = 0, m_budget = 0;
  uint64_t m_step = 0;
  uint32_t m_nextId = 1, m_nextLineage = 1;
  long m_births = 0, m_deaths = 0;
};

} // namespace alien

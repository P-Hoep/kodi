// Emergence: Physarum, boids and Particle Life in one world - no Kodi / GL.
//
// The three simulations are the cores of Physarum v2, Dancing Boids and
// Particle Life v2, each in its own namespace and its own coordinates
// (trail px; a world 1000 units high; a world 900 units high), all stretched
// over the same screen. A scene runs one of them alone or couples two or three
// through the slime's trail map, which is the shared "chemistry":
//
//  - Slime mould, Murmuration, Particle life: one simulation alone.
//  - Slime highways: every boid lays scent on the trail map as it flies; the
//    slime grows along the flight paths, and the boids steer up the trail, so
//    the flock and the network pull each other into rivers.
//  - Cell garden: the Particle Life creatures are food. Each particle lays
//    scent where it is, and the slime forages a transport network between the
//    living cells (Physarum's food-source experiments, with food that walks).
//  - Reef: the flock swims round the particle cells. The particles' density is
//    splatted into a small blurred map, and the boids steer down its gradient.
//  - Ecosystem: all three. The cells feed the slime, the slime's veins guide
//    the flock, and the flock's scent feeds the slime in turn.
//
// One Step() runs the three in turn on the calling thread, each split over the
// worker pool. Couplings are a few thousand deposits and four byte reads per
// boid, so the cost of a scene is close to the sum of its simulations.
#pragma once

#include "Boids.h"
#include "ParticleLife.h"
#include "Physarum.h"
#include "WorkerPool.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <random>
#include <vector>

namespace emergence
{

enum Scene
{
  SCENE_SLIME,
  SCENE_FLOCK,
  SCENE_LIFE,
  SCENE_HIGHWAYS,
  SCENE_GARDEN,
  SCENE_REEF,
  SCENE_ECOSYSTEM,
  SCENE_COUNT
};

inline const char* SceneName(int s)
{
  static const char* kNames[SCENE_COUNT] = {"Slime mould", "Murmuration", "Particle life", "Slime highways",
                                            "Cell garden", "Reef", "Ecosystem"};
  return kNames[std::min(std::max(s, 0), SCENE_COUNT - 1)];
}

inline bool HasSlime(int s) { return s == SCENE_SLIME || s == SCENE_HIGHWAYS || s == SCENE_GARDEN || s == SCENE_ECOSYSTEM; }
inline bool HasFlock(int s) { return s == SCENE_FLOCK || s == SCENE_HIGHWAYS || s == SCENE_REEF || s == SCENE_ECOSYSTEM; }
inline bool HasLife(int s) { return s == SCENE_LIFE || s == SCENE_GARDEN || s == SCENE_REEF || s == SCENE_ECOSYSTEM; }
inline bool IsCombination(int s) { return s >= SCENE_HIGHWAYS; }

// How much of each simulation a scene runs, by detail level. A scene that
// runs two or three simulations gives each a smaller share.
struct Budget
{
  size_t agents;
  int trailW, trailH;
  int boids;
  int perColour;
};

inline Budget BudgetFor(int detail, int scene)
{
  // {solo, in a combination} for each detail level
  static const Budget kSolo[3] = {
      {150000, 640, 360, 1500, 500}, {250000, 960, 540, 3000, 1000}, {500000, 1280, 720, 5000, 1500}};
  static const Budget kCombo[3] = {
      {80000, 640, 360, 900, 300}, {150000, 960, 540, 1500, 500}, {300000, 1280, 720, 2500, 800}};
  detail = std::min(std::max(detail, 0), 2);
  return IsCombination(scene) ? kCombo[detail] : kSolo[detail];
}

struct Settings
{
  int detail = 1;          // 0 low (TV sticks), 1 medium, 2 high
  int slimePreset = -1;    // -1: a different one each scene
  int lifeRules = 2;       // 0 random rules, 1 the original's saved models, 2 either
  int lifeColours = 4;     // colours for random rules (2..8)
  int flocks = 1;          // 1..4
  int hawks = 1;           // in Murmuration and Reef
  float coupling = 1.0f;   // how strongly the simulations feel each other
  bool vary = true;        // a different temperament for each flock
};

// The slime behaviours that read well in each combination: thick veins that
// a flock can follow, or a network coarse enough to see it gather on food.
inline int ComboPreset(int scene, uint32_t r)
{
  static const int kHighways[] = {0, 3, 4, 9, 10};
  static const int kGarden[] = {0, 3, 4, 5};
  static const int kEcosystem[] = {0, 3, 10};
  switch (scene)
  {
    case SCENE_HIGHWAYS: return kHighways[r % 5];
    case SCENE_GARDEN: return kGarden[r % 4];
    default: return kEcosystem[r % 3];
  }
}

class World
{
public:
  World() : flock(1), life(2) {}

  physarum::Simulation slime;
  boids::Simulation flock;
  particlelife::Simulation life;

  int scene() const { return m_scene; }
  int slimePreset() const { return m_slimePreset; }
  int lifePreset() const { return m_lifePreset; } // -1 = random rules
  uint64_t steps() const { return m_steps; }
  const Budget& budget() const { return m_budget; }
  // The particles' blurred density (Reef), m_dw x m_dh bytes.
  const std::vector<uint8_t>& density() const { return m_density; }

  // Set up `scene` for a screen of `aspect` (width / height).
  void Begin(int scene, const Settings& set, uint32_t seed, float aspect)
  {
    m_scene = std::min(std::max(scene, 0), SCENE_COUNT - 1);
    m_set = set;
    m_rng.seed(seed);
    m_budget = BudgetFor(set.detail, m_scene);
    m_steps = 0;
    aspect = std::min(std::max(aspect, 0.5f), 4.0f);

    if (HasSlime(m_scene))
      BeginSlime();
    if (HasFlock(m_scene))
      BeginFlock(aspect);
    flock.field = boids::Field{};
    if (HasLife(m_scene))
      BeginLife(aspect);

    // the couplings
    const float c = std::max(0.0f, set.coupling);
    if (m_scene == SCENE_HIGHWAYS || m_scene == SCENE_ECOSYSTEM)
    {
      boids::Field& f = flock.field;
      f.data = slime.display();
      f.w = slime.width();
      f.h = slime.height();
      f.stride = slime.species();
      f.step = std::max(1, slime.width() / 320);
      f.look = 28.0f;
      f.gain = 5.0f;
      f.weight = (m_scene == SCENE_HIGHWAYS ? 0.9f : 0.7f) * c;
    }
    if (m_scene == SCENE_REEF)
    {
      m_dw = kDensityW;
      m_dh = kDensityH;
      m_count.assign(static_cast<size_t>(m_dw) * m_dh, 0);
      m_blur.assign(m_count.size(), 0);
      m_density.assign(m_count.size(), 0);
      boids::Field& f = flock.field;
      f.data = m_density.data();
      f.w = m_dw;
      f.h = m_dh;
      f.stride = 1;
      f.step = 1;
      f.look = 45.0f;
      f.gain = 4.0f;
      f.weight = -2.2f * c;
    }
    m_food = 0;
    m_scent = 0;
    if (HasSlime(m_scene))
    {
      const double agent = slime.AgentDeposit(0);
      if (m_scene == SCENE_GARDEN || m_scene == SCENE_ECOSYSTEM)
        m_food = static_cast<uint32_t>(std::min(65535.0, agent * kFood * c * PerScreen(m_budget.perColour * 4)));
      if (m_scene == SCENE_HIGHWAYS || m_scene == SCENE_ECOSYSTEM)
        m_scent = static_cast<uint32_t>(std::min(
            65535.0, agent * (m_scene == SCENE_HIGHWAYS ? kScent : kScent * 0.5) * c * PerScreen(m_budget.boids)));
    }
    if (m_scene == SCENE_REEF)
      BuildDensity();
  }

  // One step of the scene: the particles, their couplings, the flock, then
  // the slime. All on the calling thread, each split over `pool`.
  void Step(WorkerPool& pool)
  {
    auto run = [&pool](size_t n, const std::function<void(size_t, size_t)>& fn) { pool.Run(n, fn); };
    const bool hasSlime = HasSlime(m_scene), hasFlock = HasFlock(m_scene), hasLife = HasLife(m_scene);

    if (hasLife)
    {
      if (m_scene == SCENE_LIFE && m_steps > 0 && m_steps % kPulseEvery == 0)
        RandomPulse();
      life.StepWith(run);
      if (m_food)
        DepositParticles();
      if (m_scene == SCENE_REEF)
        BuildDensity();
    }
    if (hasFlock)
    {
      flock.BeginStep();
      pool.Run(flock.size(), [this](size_t lo, size_t hi) { flock.UpdateRange(lo, hi); });
      flock.EndStep();
      if (m_scent)
        DepositBoids();
    }
    if (hasSlime)
    {
      pool.Run(slime.agents(), [this](size_t lo, size_t hi) { slime.MoveAgents(lo, hi); });
      pool.Run(static_cast<size_t>(slime.height()), [this](size_t lo, size_t hi) { slime.DiffuseRows(lo, hi); });
      slime.EndStep();
    }
    m_steps++;
  }

  // Counts for tests and the log.
  size_t ParticleCount() const
  {
    size_t n = 0;
    for (int g = 0; g < life.numGroups(); g++)
      n += life.group(g).size();
    return n;
  }

  static constexpr int kDensityW = 160, kDensityH = 90;

private:
  // Food per particle and scent per boid, in agent deposits, for a screen
  // with kReference of them; fewer particles each lay more (PerScreen), so a
  // lighter detail level looks the same.
  static constexpr double kFood = 14.0;
  static constexpr double kScent = 40.0;
  static constexpr int kPulseEvery = 1500; // steps between random pulses (Particle life)
  static constexpr float kReefReach = 0.6f;

  static double PerScreen(int count) { return std::min(4.0, std::max(0.5, 2000.0 / std::max(1, count))); }

  void BeginSlime()
  {
    const int n = physarum::kNumPresets;
    int preset;
    if (m_set.slimePreset >= 0)
      preset = std::min(m_set.slimePreset, n - 1);
    else if (IsCombination(m_scene))
      preset = ComboPreset(m_scene, m_rng());
    else
      preset = static_cast<int>(m_rng() % n);
    m_slimePreset = preset;

    // alone, the slime sometimes splits into two species that avoid each other
    const int species = m_scene == SCENE_SLIME && m_rng() % 3 == 0 ? 2 : 1;
    slime.Configure(m_budget.trailW, m_budget.trailH, species, m_budget.agents);
    const physarum::Params base = physarum::FromDef(physarum::kPresets[preset], m_budget.trailW / 960.0f);
    for (int s = 0; s < species; s++)
      slime.SetParams(s, physarum::ForSpecies(base, s, true));
    int start = physarum::START_RANDOM;
    if (m_scene == SCENE_SLIME)
    {
      static const int kStarts[] = {physarum::START_RANDOM, physarum::START_DISC, physarum::START_RING,
                                    physarum::START_COLONIES, physarum::START_BIG_BANG};
      start = species == 2 && m_rng() % 2 ? physarum::START_THIRDS : kStarts[m_rng() % 5];
    }
    slime.Spawn(start, m_rng());
  }

  void BeginFlock(float aspect)
  {
    boids::Params p; // the Dancing Boids defaults at 60 steps a second
    p.count = m_budget.boids;
    p.species = std::min(std::max(m_set.flocks, 1), boids::MAX_SPECIES);
    p.leadWeight = 0.25f;
    p.predators = (m_scene == SCENE_FLOCK || m_scene == SCENE_REEF) ? m_set.hawks : 0;
    p.maxNeighbours = m_set.detail == 0 ? 24 : 32;
    if (m_set.vary)
    {
      std::uniform_real_distribution<float> u(0.0f, 1.0f);
      auto r = [&](float a, float b) { return a + (b - a) * u(m_rng); };
      p.sepWeight *= r(0.75f, 1.35f);
      p.alignWeight *= r(0.6f, 1.4f);
      p.cohWeight *= r(0.6f, 1.5f);
      p.vision *= r(0.8f, 1.25f);
      p.separation = std::min(p.separation, p.vision * 0.6f);
      const float s = r(0.85f, 1.15f);
      p.maxSpeed *= s;
      p.minSpeed *= s;
    }
    flock.params = p;
    flock.Resize(1000.0f * aspect, 1000.0f);
    // the original's blues: (rand(0, 0.3), rand(0.1, 0.3), 1), packed RGBA
    flock.Restart([](std::mt19937& rng, uint8_t) -> uint32_t {
      std::uniform_real_distribution<float> u(0.0f, 1.0f);
      const uint32_t r = static_cast<uint32_t>(0.3f * u(rng) * 255.0f + 0.5f);
      const uint32_t g = static_cast<uint32_t>((0.1f + 0.2f * u(rng)) * 255.0f + 0.5f);
      return r | (g << 8) | (255u << 16) | (255u << 24);
    });
  }

  void BeginLife(float aspect)
  {
    particlelife::Params& p = life.params;
    p = particlelife::Params{};
    p.perColour = m_budget.perColour;
    p.explorePeriod = 100;
    life.Resize(900.0f * aspect, 900.0f);
    if (m_scene == SCENE_REEF && m_set.lifeRules != 0)
    {
      // Reef wants cells for the flock to swim round: one of the original's
      // cell-forming models (Flower cell, Cells I-III), its reach scaled down
      // so it costs about what the others do and the cells come out a size
      // that fits between the birds. Reef has no slime to pay for, so it
      // gets half as many particles again.
      static const int kCells[] = {4, 5, 6, 7};
      m_lifePreset = kCells[m_rng() % 4];
      p.perColour = m_budget.perColour * 3 / 2;
      life.LoadPreset(m_lifePreset);
      for (int i = 0; i < life.numGroups(); i++)
        for (int j = 0; j < life.numGroups(); j++)
          life.setRadius(i, j, life.radius(i, j) * kReefReach);
      return;
    }
    const bool preset = m_set.lifeRules == 1 || (m_set.lifeRules == 2 && m_rng() % 2 == 0);
    if (preset)
    {
      // In a combination, one of the lively short-reach models (DNA, Ladybug,
      // Mosquito, Photon, Soap, Waves, Y): the others are slow drifting gases
      // or reach so far that they cost several times as much.
      static const int kLively[] = {3, 8, 9, 10, 12, 16, 18};
      m_lifePreset = IsCombination(m_scene) ? kLively[m_rng() % 7]
                                            : static_cast<int>(m_rng() % particlelife::kNumPresets);
      life.LoadPreset(m_lifePreset);
    }
    else
    {
      m_lifePreset = -1;
      const int most = std::min(std::max(m_set.lifeColours, 2), particlelife::MAX_GROUPS);
      // 2..most colours, mostly 3-5 (more colours cost more pairs)
      int n = 2 + static_cast<int>(m_rng() % static_cast<uint32_t>(most - 1));
      if (IsCombination(m_scene))
        n = std::min(n, 5);
      life.SetNumGroups(n);
      // keep the total about the same whatever the colour count
      p.perColour = std::max(50, m_budget.perColour * 4 / n);
      std::uniform_real_distribution<float> u(0.0f, 1.0f);
      p.viscosity = 0.35f + 0.35f * u(m_rng);
      // alone, random rules keep changing one rule at a time (the JavaScript
      // version's "random exploration"), so a scene that settles into a quiet
      // gas does not stay one for minutes
      p.explore = m_scene == SCENE_LIFE;
      life.Randomize();
    }
  }

  void DepositParticles()
  {
    const float sx = slime.width() / life.width(), sy = slime.height() / life.height();
    for (int g = 0; g < life.numGroups(); g++)
    {
      const particlelife::Group& gr = life.group(g);
      for (size_t i = 0; i < gr.size(); i++)
        slime.Deposit(gr.x[i] * sx, gr.y[i] * sy, m_food, 0);
    }
  }

  void DepositBoids()
  {
    const float sx = slime.width() / flock.width(), sy = slime.height() / flock.height();
    const float* X = flock.x();
    const float* Y = flock.y();
    for (size_t i = 0; i < flock.size(); i++)
      slime.Deposit(X[i] * sx, Y[i] * sy, m_scent, 0);
  }

  // Splat the particles into a small grid, blur it twice (5-wide box, rows
  // then columns) and scale to bytes: a soft map of where the cells are.
  void BuildDensity()
  {
    std::fill(m_count.begin(), m_count.end(), 0);
    const float sx = m_dw / life.width(), sy = m_dh / life.height();
    for (int g = 0; g < life.numGroups(); g++)
    {
      const particlelife::Group& gr = life.group(g);
      for (size_t i = 0; i < gr.size(); i++)
      {
        const int x = std::min(std::max(static_cast<int>(gr.x[i] * sx), 0), m_dw - 1);
        const int y = std::min(std::max(static_cast<int>(gr.y[i] * sy), 0), m_dh - 1);
        m_count[static_cast<size_t>(y) * m_dw + x] += 16;
      }
    }
    for (int pass = 0; pass < 2; pass++)
    {
      BoxRows(m_count, m_blur);
      BoxColumns(m_blur, m_count);
    }
    // 16 per particle, /25 per box pass twice -> a lone particle is ~0.03;
    // a cell of a few particles per grid cell comes out near 200
    const double k = 4.0 * PerScreen(static_cast<int>(ParticleCount()) / 2);
    for (size_t i = 0; i < m_count.size(); i++)
      m_density[i] = static_cast<uint8_t>(std::min(255.0, m_count[i] * k));
  }

  void BoxRows(const std::vector<uint32_t>& in, std::vector<uint32_t>& out) const
  {
    for (int y = 0; y < m_dh; y++)
    {
      const uint32_t* r = in.data() + static_cast<size_t>(y) * m_dw;
      uint32_t* o = out.data() + static_cast<size_t>(y) * m_dw;
      for (int x = 0; x < m_dw; x++)
      {
        uint32_t s = 0;
        for (int d = -2; d <= 2; d++)
          s += r[std::min(std::max(x + d, 0), m_dw - 1)];
        o[x] = s / 5;
      }
    }
  }

  void BoxColumns(const std::vector<uint32_t>& in, std::vector<uint32_t>& out) const
  {
    for (int y = 0; y < m_dh; y++)
      for (int x = 0; x < m_dw; x++)
      {
        uint32_t s = 0;
        for (int d = -2; d <= 2; d++)
          s += in[static_cast<size_t>(std::min(std::max(y + d, 0), m_dh - 1)) * m_dw + x];
        out[static_cast<size_t>(y) * m_dw + x] = s / 5;
      }
  }

  // A burst (mostly) or an implosion somewhere on the screen, as Particle
  // Life v2's random pulses.
  void RandomPulse()
  {
    std::uniform_real_distribution<float> u(0.0f, 1.0f);
    const float x = (0.15f + 0.7f * u(m_rng)) * life.width();
    const float y = (0.15f + 0.7f * u(m_rng)) * life.height();
    life.Pulse(x, y, u(m_rng) < 0.7f ? 10 : -10);
  }

  int m_scene = SCENE_SLIME;
  Settings m_set;
  Budget m_budget = BudgetFor(1, SCENE_SLIME);
  std::mt19937 m_rng{1};
  uint64_t m_steps = 0;
  int m_slimePreset = 0, m_lifePreset = -1;
  uint32_t m_food = 0, m_scent = 0;

  int m_dw = kDensityW, m_dh = kDensityH;
  std::vector<uint32_t> m_count, m_blur;
  std::vector<uint8_t> m_density;
};

} // namespace emergence

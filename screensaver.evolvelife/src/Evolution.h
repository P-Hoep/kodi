// The evolution loop (Section 9 of EvolveLife.md): a population of coupled
// body + brain genomes, evaluated headlessly over a worker pool, sorted into
// NEAT species (brain and body distance), bred with fitness sharing, elitism
// and a share of fresh immigrants, under goals that change every epoch. An
// in-session MAP-Elites grid keeps the best of each body niche; telemetry
// (events, rolling per-generation stats, run totals and milestones) feeds the
// insight layer. Each finished generation is published as an immutable
// Snapshot the stage replays and the HUD reads. Nothing is ever saved.
#pragma once

#include "Trial.h"
#include "WorkerPool.h"

#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>

namespace evo
{

constexpr int ANCESTORS = 8;

struct AncestorNote
{
  int gen;
  uint8_t segs, limbs, fins, hidden;
  int16_t conns;
  float fitness;
  uint32_t flags;
};

struct Individual
{
  uint64_t id = 0, parentA = 0, parentB = 0;
  int born = 0, lineage = 0, species = -1;
  BodyGenome body;
  BrainGenome brain;
  float hue = 0.0f;     // look genes: drift neutrally
  float stripes = 0.0f;
  uint32_t mutFlags = 0;
  Phenotype ph;
  BodyTraits traits;
  TrialResult res;
  float fitness = 0.0f, score = 0.0f;
  int nAnc = 0;
  AncestorNote anc[ANCESTORS];
  char name[24] = "";
};

struct Config
{
  int population = 60;
  int maxSegs = 12;
  int trials = 1;
  float mutation = 1.0f;
  int goal = -1;           // -1: a random goal every epoch
  int epochGens = 0;       // 0: random 8-40 (or a plateau), > 0: fixed, < 0: never change
  float immigrants = 0.07f;
  int targetSpecies = 6;
  bool varyGravity = true;
};

enum EventType
{
  EV_NEW_BEST,
  EV_SPECIES_BORN,
  EV_SPECIES_EXTINCT,
  EV_FIRST_REACH,
  EV_NEW_GOAL,
  EV_MUTATION,
  EV_EXPLOIT,
  EV_MILESTONE,
  EV_INFO,
};

struct Event
{
  uint32_t seq;
  int type, gen;
  float hue; // the species hue the line is tinted with (< 0: none)
  char text[112];
};

struct SpeciesView
{
  int id;
  char name[24];
  float hue;
  int size, age, champ; // champ: index into Snapshot::pop
  float best;
};

struct GenStats
{
  int gen, epoch, goal;
  float best, mean, median;
  int species;
  float segs, hidden, conns;
  int champSegs, champHidden, champConns, champSpecies;
  int reached;
  uint8_t nsp;
  struct
  {
    int16_t id, size;
    float hue;
  } sp[10];
};

struct Totals
{
  uint64_t born = 0;
  int generations = 0;
  double creatureSeconds = 0.0, distance = 0.0;
  int tumbles = 0, exploits = 0, unstable = 0, repairs = 0, rerolls = 0;
  float longestFlight = 0.0f, highestJump = 0.0f, longestGlide = 0.0f;
};

enum Milestone
{
  MS_WALK,   // a creature travelled 3 m
  MS_JUMP,   // cleared 0.3 m off the ground
  MS_GLIDE,  // flew 3 m from a cliff
  MS_BEACON, // reached a beacon
  MS_CHASM,  // crossed a chasm
  MS_COUNT
};

inline const char* MilestoneName(int m)
{
  static const char* k[MS_COUNT] = {"First to travel 3 m", "First jump clear of the ground",
                                    "First glide of 3 m", "First to reach a beacon", "First across a chasm"};
  return k[m];
}

struct MilestoneHit
{
  bool hit = false;
  int gen = 0;
  float minutes = 0.0f;
  char who[24] = "";
};

struct HallEntry
{
  bool set = false;
  float fitness = 0.0f;
  int gen = 0, segs = 0;
  char name[24] = "";
  char score[40] = "";
};

struct Snapshot
{
  int generation = 0, epoch = 0, epochGen = 0, epochLen = 0;
  std::shared_ptr<const WorldSpec> world;
  std::vector<Individual> pop; // best first
  std::vector<SpeciesView> species;
  std::vector<GenStats> history;
  std::vector<Event> events;   // recent, oldest first
  Totals totals;
  MilestoneHit milestones[MS_COUNT];
  HallEntry hall[GOAL_COUNT];
  bool hasGhost = false;
  Individual ghost;            // the epoch's first champion, for "then and now"
  int ghostGen = 0;
  float epochBest = 0.0f;
  int archiveFilled = 0, archiveCells = 0;
  int reached = 0;
  double evalMs = 0.0, evalsPerSec = 0.0, minutes = 0.0;
  uint64_t seed = 0;
  int maxSegs = 12;
};

// Text for a result in the goal's own units.
inline void ScoreText(int goal, const TrialResult& r, char* out, size_t n)
{
  switch (goal)
  {
    case G_BEACON:
    case G_CLIMB:
      if (r.reached)
        std::snprintf(out, n, "reached in %.1f s", r.reachTime);
      else
        std::snprintf(out, n, "%.1f m closer", std::max(r.progress, 0.0f));
      break;
    case G_CHASM:
      std::snprintf(out, n, r.crossed ? "crossed, %.1f m" : "%.1f m", std::max(r.progress, 0.0f));
      break;
    case G_LEAP:
      std::snprintf(out, n, "%.2f m high", r.maxClear);
      break;
    case G_GLIDE:
      std::snprintf(out, n, "%.1f m flight", r.glide);
      break;
    case G_FLY:
      std::snprintf(out, n, "%.2f m high, %.1f s aloft", r.maxClear, r.airtime);
      break;
    default:
      std::snprintf(out, n, "%.1f m", std::max(r.progress, 0.0f));
      break;
  }
}

inline void MakeName(uint32_t seed, const BodyTraits& t, char* out, size_t n)
{
  static const char* kPre[] = {"Skit", "Glim", "Vor", "Lum", "Quill", "Nim", "Tor", "Sel", "Bram", "Oro",
                               "Fen", "Wisp", "Kel", "Zan", "Mor", "Pip", "Dri", "Fla", "Gon", "Hux",
                               "Jal", "Rin", "Sto", "Tam", "Vel", "Yor", "Cra", "Bel", "Ish", "Ulv"};
  static const char* kWing[] = {"wing", "fin", "glider", "flutter"};
  static const char* kLegs[] = {"pede", "crawler", "scuttle", "skitter"};
  static const char* kTail[] = {"tail", "coil", "worm", "whip"};
  static const char* kSmall[] = {"hop", "nub", "blob", "bounce"};
  static const char* kWalk[] = {"strider", "walker", "loper", "step"};
  const uint32_t h = Hash(seed * 2654435761u + 17u);
  const char* pre = kPre[h % (sizeof(kPre) / sizeof(kPre[0]))];
  const char* const* suf = kWalk;
  if (t.fins > 0)
    suf = kWing;
  else if (t.limbs >= 4)
    suf = kLegs;
  else if (t.chain >= 4)
    suf = kTail;
  else if (t.segs <= 3)
    suf = kSmall;
  std::snprintf(out, n, "%s%s", pre, suf[(h >> 8) % 4]);
}

class Evolution
{
public:
  void Reset(const Config& cfg, uint64_t seed)
  {
    m_cfg = cfg;
    m_cfg.population = std::max(cfg.population, 8);
    m_cfg.maxSegs = std::min(std::max(cfg.maxSegs, 3), MAX_SEGS);
    m_seed = seed;
    m_rng.Seed(seed);
    m_inn.Reset();
    m_pop.clear();
    m_species.clear();
    m_history.clear();
    m_events.clear();
    m_seq = 0;
    m_gen = 0;
    m_epoch = 0;
    m_nextId = 1;
    m_nextSpecies = 0;
    m_threshold = 5.0f;
    m_totals = Totals();
    for (auto& m : m_milestones)
      m = MilestoneHit();
    for (auto& h : m_hall)
      h = HallEntry();
    for (auto& c : m_archive)
      c.set = false;
    m_lastChamp = 0;
    m_hasGhost = false;
    m_start = std::chrono::steady_clock::now();
    m_minutesOffset = 0.0;
    m_cancel.store(false);
    std::lock_guard<std::mutex> lock(m_mutex);
    m_latest.reset();
  }

  // One generation: (new epoch?) breed or seed, evaluate, speciate, record,
  // publish. Serial apart from the evaluation.
  void RunGeneration(WorkerPool& pool)
  {
    if (m_pop.empty())
    {
      NewEpoch();
      for (int i = 0; i < m_cfg.population; i++)
        m_pop.push_back(Immigrant(false));
    }
    else
    {
      if (EpochOver())
        NewEpoch();
      Breed();
    }
    const auto t0 = std::chrono::steady_clock::now();
    Evaluate(pool);
    if (m_cancel.load())
      return;
    const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    Speciate();
    Record(ms);
    Publish(ms);
    m_gen++;
    m_epochGen++;
  }

  // Ask a running generation to stop early (Kodi is closing the screensaver).
  void Cancel() { m_cancel.store(true); }
  bool cancelled() const { return m_cancel.load(); }

  std::shared_ptr<const Snapshot> Latest() const
  {
    std::lock_guard<std::mutex> lock(m_mutex);
    return m_latest;
  }

  int generation() const { return m_gen; }
  const std::vector<Individual>& population() const { return m_pop; }
  const WorldSpec& world() const { return *m_world; }
  const Config& config() const { return m_cfg; }

  // Pretend the run has been going for longer (tests: milestone times).
  void AddMinutes(double m) { m_minutesOffset += m; }

private:
  struct SpeciesRec
  {
    int id;
    char name[24];
    float hue;
    BrainGenome repBrain;
    BodyTraits repTraits;
    int size = 0, born = 0, lastImprove = 0;
    float best = 0.0f, bestEver = 0.0f, sumAdj = 0.0f;
    bool announced = false;
    std::vector<int> members;
  };

  struct ArchiveCell
  {
    bool set = false;
    float rel = 0.0f; // fitness relative to its generation's best
    Individual ind;
  };
  static constexpr int ARCH_LIMBS = 6, ARCH_ASPECT = 4;

  double Minutes() const
  {
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - m_start).count() / 60.0 + m_minutesOffset;
  }

  void Push(int type, float hue, const char* fmt, ...) __attribute__((format(printf, 4, 5)))
  {
    Event e;
    e.seq = ++m_seq;
    e.type = type;
    e.gen = m_gen;
    e.hue = hue;
    va_list ap;
    va_start(ap, fmt);
    std::vsnprintf(e.text, sizeof(e.text), fmt, ap);
    va_end(ap);
    m_events.push_back(e);
    if (m_events.size() > 48)
      m_events.erase(m_events.begin());
  }

  bool EpochOver() const
  {
    if (m_cfg.epochGens < 0)
      return false;
    if (m_epochGen >= m_epochLen)
      return true;
    // a plateau ends a random-length epoch early
    return m_cfg.epochGens == 0 && m_epochGen >= 8 && m_gen - m_epochImproved >= 10;
  }

  void NewEpoch()
  {
    m_epoch++;
    int goal = m_cfg.goal;
    const bool first = m_epoch == 1;
    if (goal < 0)
    {
      if (first)
        goal = m_rng.Chance(0.5f) ? G_WALK : G_BEACON; // a gentle start
      else
        for (int tries = 0; tries < 6; tries++)
        {
          goal = -1;
          WorldSpec probe = MakeWorld(-1, m_rng.Next(), false);
          goal = probe.goal;
          if (goal != m_world->goal)
            break;
        }
    }
    auto w = std::make_shared<WorldSpec>(MakeWorld(goal, m_rng.Next(), first && m_cfg.goal < 0, m_cfg.varyGravity));
    w->epoch = m_epoch;
    m_world = w;
    m_epochGen = 0;
    m_epochLen = m_cfg.epochGens > 0 ? m_cfg.epochGens : m_rng.IntRange(8, 40);
    m_epochBest = 0.0f;
    m_epochImproved = m_gen;
    m_hasGhost = false;
    m_epochReached = false;
    char extra[64] = "";
    if (std::fabs(w->gravity - 9.8f) > 0.4f)
      std::snprintf(extra, sizeof(extra), ", gravity %.2f g", w->gravity / 9.8f);
    Push(EV_NEW_GOAL, -1.0f, "New goal: %s on %s%s", GoalName(w->goal), TerrainName(w->terrain), extra);
  }

  // A build that cannot fail: repair, re-roll, or fall back to a stick.
  bool Build(Individual& ind)
  {
    Repair(ind.body);
    if (Expand(ind.body, m_cfg.maxSegs, ind.ph))
    {
      ind.traits = Traits(ind.ph);
      return true;
    }
    return false;
  }

  Individual Immigrant(bool fromArchive)
  {
    Individual ind;
    ind.id = m_nextId++;
    ind.born = m_gen;
    ind.mutFlags = MF_IMMIGRANT;
    if (fromArchive)
    {
      int filled[ARCH_LIMBS * ARCH_ASPECT];
      int nf = 0;
      for (int i = 0; i < ARCH_LIMBS * ARCH_ASPECT; i++)
        if (m_archive[i].set)
          filled[nf++] = i;
      if (nf > 0)
      {
        const Individual& src = m_archive[filled[m_rng.Int(nf)]].ind;
        ind.body = src.body;
        ind.brain = src.brain;
        ind.hue = src.hue;
        ind.stripes = src.stripes;
        ind.lineage = src.lineage + 1;
        MutateBrain(ind.brain, m_inn, m_rng, m_cfg.mutation);
        if (Build(ind))
          return ind;
      }
    }
    for (int tries = 0; tries < 20; tries++)
    {
      ind.body = RandomBody(m_rng, m_cfg.maxSegs);
      if (Build(ind))
        break;
      m_totals.rerolls++;
    }
    if (ind.ph.numSegs < 2)
    {
      // a two-part stick: always valid
      ind.body = BodyGenome();
      ind.body.numNodes = 2;
      ind.body.numEdges = 1;
      ind.body.edge[0].from = 0;
      ind.body.edge[0].to = 1;
      ind.body.edge[0].angle = -1.2f;
      Build(ind);
    }
    ind.brain = RandomBrain(m_rng, m_inn);
    ind.hue = m_rng.Range(-0.05f, 0.05f);
    ind.stripes = m_rng.Chance(0.5f) ? m_rng.Range(0.0f, 1.0f) : 0.0f;
    return ind;
  }

  void Evaluate(WorkerPool& pool)
  {
    const WorldSpec* w = m_world.get();
    const int trials = std::max(1, std::min(m_cfg.trials, 3));
    pool.RunEach(m_pop.size(), [&](size_t i) {
      Individual& ind = m_pop[i];
      if (m_cancel.load(std::memory_order_relaxed))
        return;
      float sum = 0.0f, lo = 1e9f, hi = -1e9f;
      Trial t;
      TrialResult first;
      for (int k = 0; k < trials; k++)
      {
        t.Init(ind.ph, ind.brain, w, k);
        t.Run();
        if (k == 0)
          first = t.res;
        sum += t.res.fitness;
        lo = std::min(lo, t.res.fitness);
        hi = std::max(hi, t.res.fitness);
      }
      ind.res = first; // the stage replays trial 0
      ind.fitness = trials > 1 ? sum / static_cast<float>(trials) - 0.25f * (hi - lo) : sum;
      if (!std::isfinite(ind.fitness))
        ind.fitness = 0.0f;
    });
  }

  float Distance(const Individual& a, const BrainGenome& b, const BodyTraits& bt) const
  {
    return BrainDistance(a.brain, b) + 0.6f * BodyDistance(a.traits, bt);
  }

  void Speciate()
  {
    for (SpeciesRec& s : m_species)
    {
      s.members.clear();
      s.size = 0;
    }
    for (size_t i = 0; i < m_pop.size(); i++)
    {
      Individual& ind = m_pop[i];
      int found = -1;
      // keep to the parent's species when it is still close (stable colours)
      for (size_t k = 0; k < m_species.size() && found < 0; k++)
        if (m_species[k].id == ind.species && Distance(ind, m_species[k].repBrain, m_species[k].repTraits) < m_threshold * 1.2f)
          found = static_cast<int>(k);
      for (size_t k = 0; k < m_species.size() && found < 0; k++)
        if (Distance(ind, m_species[k].repBrain, m_species[k].repTraits) < m_threshold)
          found = static_cast<int>(k);
      if (found < 0)
      {
        SpeciesRec s;
        s.id = m_nextSpecies++;
        // golden-ratio hues: neighbouring species look different
        s.hue = std::fmod(0.13f + 0.6180339f * static_cast<float>(s.id), 1.0f);
        s.repBrain = ind.brain;
        s.repTraits = ind.traits;
        s.born = m_gen;
        s.lastImprove = m_gen;
        MakeName(static_cast<uint32_t>(m_seed) ^ static_cast<uint32_t>(s.id * 7919), ind.traits, s.name, sizeof(s.name));
        m_species.push_back(s);
        found = static_cast<int>(m_species.size()) - 1;
      }
      SpeciesRec& s = m_species[static_cast<size_t>(found)];
      ind.species = s.id;
      std::snprintf(ind.name, sizeof(ind.name), "%s", s.name);
      s.members.push_back(static_cast<int>(i));
      s.size++;
    }
    // extinctions
    for (size_t k = 0; k < m_species.size();)
    {
      if (m_species[k].size == 0)
      {
        if (m_species[k].announced)
          Push(EV_SPECIES_EXTINCT, m_species[k].hue, "The %s species died out after %d generations", m_species[k].name,
               m_gen - m_species[k].born);
        m_species.erase(m_species.begin() + static_cast<long>(k));
      }
      else
        k++;
    }
    // per species: best, improvement, a new representative, announcements
    for (SpeciesRec& s : m_species)
    {
      float best = 0.0f;
      int champ = s.members[0];
      for (int m : s.members)
        if (m_pop[static_cast<size_t>(m)].fitness > best)
        {
          best = m_pop[static_cast<size_t>(m)].fitness;
          champ = m;
        }
      s.best = best;
      if (best > s.bestEver * 1.02f + 0.01f)
      {
        s.bestEver = best;
        s.lastImprove = m_gen;
      }
      const Individual& rep = m_pop[static_cast<size_t>(s.members[static_cast<size_t>(m_rng.Int(static_cast<int>(s.members.size())))])];
      s.repBrain = rep.brain;
      s.repTraits = rep.traits;
      if (!s.announced && s.size >= 3 && m_gen > 0)
      {
        s.announced = true;
        const BodyTraits& t = m_pop[static_cast<size_t>(champ)].traits;
        Push(EV_SPECIES_BORN, s.hue, "A new species appeared: %s (%d segments, %d limbs%s)", s.name, t.segs, t.limbs,
             t.fins ? ", fins" : "");
      }
      else if (!s.announced && m_gen == 0)
        s.announced = s.size >= 2;
    }
    const int n = static_cast<int>(m_species.size());
    // steer the threshold towards the target count (faster when far off)
    if (n < m_cfg.targetSpecies)
      m_threshold *= n * 2 < m_cfg.targetSpecies ? 0.85f : 0.93f;
    else if (n > m_cfg.targetSpecies)
      m_threshold *= n > m_cfg.targetSpecies * 2 ? 1.25f : 1.07f;
    m_threshold = Clamp(m_threshold, 0.3f, 8.0f);

    // selection score: fitness plus a small novelty bonus in body space
    float mean = 0.0f;
    for (const Individual& ind : m_pop)
      mean += ind.fitness;
    mean /= static_cast<float>(m_pop.size());
    for (Individual& ind : m_pop)
    {
      float nearest[5] = {1e9f, 1e9f, 1e9f, 1e9f, 1e9f};
      for (const Individual& o : m_pop)
      {
        if (&o == &ind)
          continue;
        float d = BodyDistance(ind.traits, o.traits);
        for (float& v : nearest)
          if (d < v)
            std::swap(d, v);
      }
      float nov = 0.0f;
      for (float v : nearest)
        nov += std::min(v, 3.0f);
      nov /= 5.0f;
      ind.score = ind.fitness + 0.08f * std::max(mean, 0.2f) * nov;
    }
  }

  void Breed()
  {
    const int P = m_cfg.population;
    std::vector<Individual> next;
    next.reserve(static_cast<size_t>(P));
    // the overall champion survives unchanged
    int champ = 0;
    for (size_t i = 1; i < m_pop.size(); i++)
      if (m_pop[i].fitness > m_pop[static_cast<size_t>(champ)].fitness)
        champ = static_cast<int>(i);
    next.push_back(m_pop[static_cast<size_t>(champ)]);
    next.back().mutFlags = 0;

    int immigrants = static_cast<int>(std::lround(static_cast<float>(P) * m_cfg.immigrants));
    immigrants = std::min(immigrants, P - 1);
    const int bred = P - 1 - immigrants;

    // offspring per species from shared (size-adjusted) scores; stagnant
    // species get none unless they are among the two best
    std::vector<int> order(m_species.size());
    for (size_t k = 0; k < order.size(); k++)
      order[k] = static_cast<int>(k);
    std::sort(order.begin(), order.end(),
              [&](int a, int b) { return m_species[static_cast<size_t>(a)].best > m_species[static_cast<size_t>(b)].best; });
    float total = 0.0f;
    for (size_t r = 0; r < order.size(); r++)
    {
      SpeciesRec& s = m_species[static_cast<size_t>(order[r])];
      s.sumAdj = 0.0f;
      const bool stagnant = m_gen - s.lastImprove > 18 && r >= 2;
      if (stagnant)
        continue;
      for (int m : s.members)
        s.sumAdj += (m_pop[static_cast<size_t>(m)].score + 0.05f) / static_cast<float>(s.size);
      total += s.sumAdj;
    }
    std::vector<int> quota(m_species.size(), 0);
    int given = 0;
    std::vector<std::pair<float, int>> rem;
    for (size_t k = 0; k < m_species.size(); k++)
    {
      const float share = total > 0 ? m_species[k].sumAdj / total * static_cast<float>(bred) : 0.0f;
      quota[k] = static_cast<int>(share);
      given += quota[k];
      rem.push_back({share - static_cast<float>(quota[k]), static_cast<int>(k)});
    }
    std::sort(rem.begin(), rem.end(), [](const std::pair<float, int>& a, const std::pair<float, int>& b) {
      return a.first != b.first ? a.first > b.first : a.second < b.second;
    });
    for (size_t r = 0; given < bred && r < rem.size(); r++, given++)
      quota[static_cast<size_t>(rem[r].second)]++;
    if (given < bred && !order.empty())
      quota[static_cast<size_t>(order[0])] += bred - given;

    for (size_t k = 0; k < m_species.size(); k++)
    {
      SpeciesRec& s = m_species[k];
      if (quota[k] <= 0)
        continue;
      std::vector<int> mem = s.members;
      std::sort(mem.begin(), mem.end(), [&](int a, int b) {
        const float fa = m_pop[static_cast<size_t>(a)].score, fb = m_pop[static_cast<size_t>(b)].score;
        return fa != fb ? fa > fb : a < b;
      });
      const int survivors = std::max(1, static_cast<int>(mem.size() + 1) / 2);
      int made = 0;
      // the species champion survives (if the species is big enough)
      if (s.size >= 3 && mem[0] != champ)
      {
        next.push_back(m_pop[static_cast<size_t>(mem[0])]);
        next.back().mutFlags = 0;
        made++;
      }
      auto pick = [&]() {
        const int a = m_rng.Int(survivors), b = m_rng.Int(survivors);
        return mem[static_cast<size_t>(std::min(a, b))];
      };
      while (made < quota[k])
      {
        const Individual& pa = m_pop[static_cast<size_t>(pick())];
        Individual child;
        if (survivors >= 2 && m_rng.Chance(0.3f))
        {
          const Individual* pb = &m_pop[static_cast<size_t>(pick())];
          for (int tries = 0; tries < 3 && pb == &pa; tries++)
            pb = &m_pop[static_cast<size_t>(pick())];
          if (pb == &pa)
            pb = &m_pop[static_cast<size_t>(mem[static_cast<size_t>(survivors - 1)])];
          const Individual& fit = pa.score >= pb->score ? pa : *pb;
          const Individual& other = pa.score >= pb->score ? *pb : pa;
          child = MakeChild(fit, &other);
        }
        else
          child = MakeChild(pa, nullptr);
        next.push_back(std::move(child));
        made++;
      }
    }
    while (static_cast<int>(next.size()) < P - immigrants)
      next.push_back(MakeChild(m_pop[static_cast<size_t>(champ)], nullptr));
    while (static_cast<int>(next.size()) < P)
      next.push_back(Immigrant(m_rng.Chance(0.3f)));
    next.resize(static_cast<size_t>(P));
    m_pop.swap(next);
  }

  Individual MakeChild(const Individual& pa, const Individual* pb)
  {
    Individual c;
    c.id = m_nextId++;
    c.parentA = pa.id;
    c.parentB = pb ? pb->id : 0;
    c.born = m_gen;
    c.lineage = pa.lineage + 1;
    c.species = pa.species;
    c.hue = Clamp(pa.hue + 0.006f * m_rng.Gauss(), -0.08f, 0.08f);
    c.stripes = Clamp(pa.stripes + 0.03f * m_rng.Gauss(), 0.0f, 1.0f);
    // the family record: the parent's ancestors plus the parent
    const int keep = std::min(pa.nAnc, ANCESTORS - 1);
    for (int i = 0; i < keep; i++)
      c.anc[i] = pa.anc[pa.nAnc - keep + i];
    AncestorNote& note = c.anc[keep];
    note.gen = pa.born;
    note.segs = static_cast<uint8_t>(pa.traits.segs);
    note.limbs = static_cast<uint8_t>(pa.traits.limbs);
    note.fins = static_cast<uint8_t>(pa.traits.fins);
    note.hidden = static_cast<uint8_t>(pa.brain.hidden.size());
    note.conns = static_cast<int16_t>(pa.brain.Enabled());
    note.fitness = pa.fitness;
    note.flags = pa.mutFlags;
    c.nAnc = keep + 1;

    uint32_t flags = 0;
    if (pb)
    {
      c.body = CrossBody(pa.body, pb->body, m_rng);
      c.brain = CrossBrain(pa.brain, pb->brain, m_rng);
      flags |= MF_CROSS;
    }
    else
    {
      c.body = pa.body;
      c.brain = pa.brain;
    }
    flags |= MutateBrain(c.brain, m_inn, m_rng, m_cfg.mutation);
    const BodyGenome before = c.body;
    bool built = false;
    if (m_rng.Chance(0.5f * std::min(m_cfg.mutation, 2.0f)))
    {
      for (int tries = 0; tries < 5 && !built; tries++)
      {
        c.body = before;
        const uint32_t bf = MutateBody(c.body, m_rng, m_cfg.mutation);
        built = Build(c);
        if (built)
          flags |= bf;
        else
          m_totals.rerolls++;
      }
      if (!built)
        m_totals.repairs++;
    }
    if (!built)
    {
      c.body = before;
      if (!Build(c))
      {
        c.body = pa.body;
        c.ph = pa.ph;
        c.traits = pa.traits;
      }
    }
    // a fin that really appears in the body
    if ((flags & MF_FIN) && c.traits.fins <= pa.traits.fins)
      flags &= ~static_cast<uint32_t>(MF_FIN);
    if ((flags & MF_LIMB) && c.traits.segs <= pa.traits.segs)
      flags &= ~static_cast<uint32_t>(MF_LIMB);
    c.mutFlags = flags;
    return c;
  }

  void Record(double evalMs)
  {
    (void)evalMs;
    const int goal = m_world->goal;
    std::vector<float> fit;
    fit.reserve(m_pop.size());
    int best = 0, reached = 0;
    float segs = 0, hidden = 0, conns = 0, mean = 0;
    for (size_t i = 0; i < m_pop.size(); i++)
    {
      const Individual& ind = m_pop[i];
      fit.push_back(ind.fitness);
      mean += ind.fitness;
      segs += static_cast<float>(ind.traits.segs);
      hidden += static_cast<float>(ind.brain.hidden.size());
      conns += static_cast<float>(ind.brain.Enabled());
      if (ind.fitness > m_pop[static_cast<size_t>(best)].fitness)
        best = static_cast<int>(i);
      if (ind.res.reached || ind.res.crossed)
        reached++;
      // totals
      m_totals.creatureSeconds += static_cast<double>(ind.res.time) * m_cfg.trials;
      m_totals.distance += ind.res.distance;
      m_totals.tumbles += ind.res.tumbles;
      if (ind.res.stop == STOP_EXPLOIT)
        m_totals.exploits++;
      if (ind.res.stop == STOP_UNSTABLE)
        m_totals.unstable++;
      m_totals.longestFlight = std::max(m_totals.longestFlight, ind.res.airtime);
      m_totals.highestJump = std::max(m_totals.highestJump, ind.res.maxClear);
      m_totals.longestGlide = std::max(m_totals.longestGlide, ind.res.glide);
    }
    if (m_gen == 0)
      m_totals.born += m_pop.size();
    else
      for (const Individual& ind : m_pop)
        if (ind.born == m_gen)
          m_totals.born++;
    m_totals.generations = m_gen + 1;
    m_reached = reached;
    const int n = static_cast<int>(m_pop.size());
    mean /= static_cast<float>(n);
    std::vector<float> sorted = fit;
    std::sort(sorted.begin(), sorted.end());
    const Individual& champ = m_pop[static_cast<size_t>(best)];

    // exploits caught this generation
    int caught = 0;
    for (const Individual& ind : m_pop)
      caught += ind.res.stop == STOP_EXPLOIT;
    if (caught > 0)
      Push(EV_EXPLOIT, -1.0f, "Caught %d creature%s exploiting the physics: scored zero", caught, caught > 1 ? "s" : "");

    // records
    char score[48];
    ScoreText(goal, champ.res, score, sizeof(score));
    const float hue = SpeciesHue(champ.species);
    if (champ.fitness > m_epochBest * 1.05f + 0.05f)
    {
      if (m_epochGen > 0)
        Push(EV_NEW_BEST, hue, "New record: %s, %s (generation %d)", champ.name, score, m_gen);
      m_epochBest = champ.fitness;
      m_epochImproved = m_gen;
    }
    if (champ.id != m_lastChamp && m_gen > 0)
    {
      const uint32_t f = champ.mutFlags;
      if (f & MF_FIN)
        Push(EV_MUTATION, hue, "Fins appeared in the %s lineage and it took the lead", champ.name);
      else if (f & MF_LIMB)
        Push(EV_MUTATION, hue, "A new limb paid off: %s now has %d segments", champ.name, champ.traits.segs);
      else if (f & MF_NEURON)
        Push(EV_MUTATION, hue, "A new neuron in %s's brain helped it to the top", champ.name);
      else if (f & MF_MIRROR)
        Push(EV_MUTATION, hue, "Symmetry changed in the %s lineage, and it worked", champ.name);
    }
    m_lastChamp = champ.id;

    // hall of fame per goal
    HallEntry& h = m_hall[goal];
    if (!h.set || champ.fitness > h.fitness)
    {
      h.set = true;
      h.fitness = champ.fitness;
      h.gen = m_gen;
      h.segs = champ.traits.segs;
      std::snprintf(h.name, sizeof(h.name), "%s", champ.name);
      std::snprintf(h.score, sizeof(h.score), "%s", score);
    }

    // milestones
    const double minutes = Minutes();
    auto hit = [&](int m, const Individual& who) {
      MilestoneHit& ms = m_milestones[m];
      if (ms.hit)
        return;
      ms.hit = true;
      ms.gen = m_gen;
      ms.minutes = static_cast<float>(minutes);
      std::snprintf(ms.who, sizeof(ms.who), "%s", who.name);
      Push(EV_MILESTONE, SpeciesHue(who.species), "Milestone: %s - %s, generation %d", MilestoneName(m), who.name, m_gen);
    };
    for (const Individual& ind : m_pop)
    {
      if ((goal == G_WALK || goal == G_HURDLES || goal == G_CHASM) && ind.res.progress >= 3.0f)
        hit(MS_WALK, ind);
      if (ind.res.maxClear >= 0.3f)
        hit(MS_JUMP, ind);
      if (ind.res.glide >= 3.0f)
        hit(MS_GLIDE, ind);
      if (ind.res.reached)
      {
        if (!m_epochReached)
          Push(EV_FIRST_REACH, SpeciesHue(ind.species), "%s is the first to reach the beacon this epoch (generation %d)",
               ind.name, m_gen);
        m_epochReached = true;
        hit(MS_BEACON, ind);
      }
      if (ind.res.crossed)
        hit(MS_CHASM, ind);
    }

    // the epoch's first champion, for "then and now"
    if (!m_hasGhost)
    {
      m_ghost = champ;
      m_ghostGen = m_gen;
      m_hasGhost = true;
    }

    // MAP-Elites: the best per (limbs, aspect) niche, relative to its generation
    const float top = std::max(champ.fitness, 1e-3f);
    for (const Individual& ind : m_pop)
    {
      const int li = std::min(ind.traits.limbs, ARCH_LIMBS - 1);
      const float a = ind.traits.aspect;
      const int ai = a < 0.8f ? 0 : (a < 1.6f ? 1 : (a < 3.0f ? 2 : 3));
      ArchiveCell& cell = m_archive[li * ARCH_ASPECT + ai];
      const float rel = ind.fitness / top;
      if (!cell.set || rel > cell.rel || (rel >= cell.rel * 0.98f && m_rng.Chance(0.1f)))
      {
        cell.set = true;
        cell.rel = rel;
        cell.ind = ind;
      }
    }

    GenStats st;
    st.gen = m_gen;
    st.epoch = m_epoch;
    st.goal = goal;
    st.best = champ.fitness;
    st.mean = mean;
    st.median = sorted[sorted.size() / 2];
    st.species = static_cast<int>(m_species.size());
    st.segs = segs / static_cast<float>(n);
    st.hidden = hidden / static_cast<float>(n);
    st.conns = conns / static_cast<float>(n);
    st.champSegs = champ.traits.segs;
    st.champHidden = static_cast<int>(champ.brain.hidden.size());
    st.champConns = champ.brain.Enabled();
    st.champSpecies = champ.species;
    st.reached = reached;
    st.nsp = 0;
    for (const SpeciesRec& s : m_species)
    {
      if (st.nsp >= 10)
        break;
      st.sp[st.nsp].id = static_cast<int16_t>(s.id);
      st.sp[st.nsp].size = static_cast<int16_t>(s.size);
      st.sp[st.nsp].hue = s.hue;
      st.nsp++;
    }
    m_history.push_back(st);
    if (m_history.size() > 300)
      m_history.erase(m_history.begin());
  }

  float SpeciesHue(int id) const
  {
    for (const SpeciesRec& s : m_species)
      if (s.id == id)
        return s.hue;
    return -1.0f;
  }

  void Publish(double evalMs)
  {
    auto snap = std::make_shared<Snapshot>();
    snap->generation = m_gen;
    snap->epoch = m_epoch;
    snap->epochGen = m_epochGen;
    snap->epochLen = m_cfg.epochGens < 0 ? 0 : m_epochLen;
    snap->world = m_world;
    snap->pop = m_pop;
    std::stable_sort(snap->pop.begin(), snap->pop.end(),
                     [](const Individual& a, const Individual& b) { return a.fitness > b.fitness; });
    for (const SpeciesRec& s : m_species)
    {
      SpeciesView v;
      v.id = s.id;
      std::snprintf(v.name, sizeof(v.name), "%s", s.name);
      v.hue = s.hue;
      v.size = s.size;
      v.age = m_gen - s.born;
      v.best = s.best;
      v.champ = 0;
      for (size_t i = 0; i < snap->pop.size(); i++)
        if (snap->pop[i].species == s.id)
        {
          v.champ = static_cast<int>(i);
          break;
        }
      snap->species.push_back(v);
    }
    std::sort(snap->species.begin(), snap->species.end(),
              [](const SpeciesView& a, const SpeciesView& b) { return a.best > b.best; });
    snap->history = m_history;
    snap->events = m_events;
    snap->totals = m_totals;
    for (int m = 0; m < MS_COUNT; m++)
      snap->milestones[m] = m_milestones[m];
    for (int g = 0; g < GOAL_COUNT; g++)
      snap->hall[g] = m_hall[g];
    snap->hasGhost = m_hasGhost && m_ghostGen < m_gen;
    if (snap->hasGhost)
      snap->ghost = m_ghost;
    snap->ghostGen = m_ghostGen;
    snap->epochBest = m_epochBest;
    int filled = 0;
    for (const ArchiveCell& c : m_archive)
      filled += c.set;
    snap->archiveFilled = filled;
    snap->archiveCells = ARCH_LIMBS * ARCH_ASPECT;
    snap->reached = m_reached;
    snap->evalMs = evalMs;
    snap->evalsPerSec = evalMs > 0 ? static_cast<double>(m_pop.size() * static_cast<size_t>(m_cfg.trials)) / (evalMs / 1000.0) : 0.0;
    snap->minutes = Minutes();
    snap->seed = m_seed;
    snap->maxSegs = m_cfg.maxSegs;
    std::lock_guard<std::mutex> lock(m_mutex);
    m_latest = snap;
  }

  Config m_cfg;
  uint64_t m_seed = 0;
  Rng m_rng;
  Innovations m_inn;
  std::vector<Individual> m_pop;
  std::vector<SpeciesRec> m_species;
  std::vector<GenStats> m_history;
  std::vector<Event> m_events;
  uint32_t m_seq = 0;
  int m_gen = 0, m_epoch = 0, m_epochGen = 0, m_epochLen = 10, m_epochImproved = 0;
  float m_epochBest = 0.0f;
  bool m_epochReached = false;
  int m_reached = 0;
  uint64_t m_nextId = 1;
  int m_nextSpecies = 0;
  float m_threshold = 2.0f;
  std::shared_ptr<const WorldSpec> m_world;
  Totals m_totals;
  MilestoneHit m_milestones[MS_COUNT];
  HallEntry m_hall[GOAL_COUNT];
  ArchiveCell m_archive[ARCH_LIMBS * ARCH_ASPECT];
  uint64_t m_lastChamp = 0;
  bool m_hasGhost = false;
  Individual m_ghost;
  int m_ghostGen = 0;
  std::chrono::steady_clock::time_point m_start;
  double m_minutesOffset = 0.0;
  mutable std::mutex m_mutex;
  std::shared_ptr<const Snapshot> m_latest;
  std::atomic<bool> m_cancel{false};
};

} // namespace evo

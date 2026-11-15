// Checks and benchmarks the EvolveLife core without Kodi (Section 15 of EvolveLife.md).
//
//   c++ -O3 -std=c++17 -Isrc tests/sim_test.cpp -o /tmp/evolve_test -pthread && /tmp/evolve_test
//   /tmp/evolve_test quick       # skip the long evolution runs
//   /tmp/evolve_test evolve GOAL GENS [SEED]  # print one run's progress (GOAL 0-6)
//
// - fuzz: 200,000 mutated offspring, every one repairs into a buildable body;
// - property: random bodies with random brains stay finite and stable for
//   10 s on every terrain;
// - determinism: a stage replay of a creature matches its evaluation exactly,
//   and four threads give the same generation as one;
// - momentum: a creature in free fall cannot push its centre of mass sideways;
// - evolution: the best travel distance improves over 30 generations on
//   every seed, and every goal runs;
// - benchmark: ms per generation at each profile.
#include "Evolution.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

using namespace evo;

static int g_failures = 0;
#define CHECK(cond, ...)                                                                                     \
  do                                                                                                         \
  {                                                                                                          \
    if (!(cond))                                                                                             \
    {                                                                                                        \
      std::printf("FAIL %s:%d: ", __FILE__, __LINE__);                                                       \
      std::printf(__VA_ARGS__);                                                                              \
      std::printf("\n");                                                                                     \
      g_failures++;                                                                                          \
    }                                                                                                        \
  } while (0)

// The profiles of the Kodi add-on (keep in step with ScreensaverEvolveLife.cpp).
static Config Profile(int p)
{
  Config c;
  static const int kPop[] = {32, 60, 120};
  static const int kSegs[] = {8, 12, 16};
  static const int kTrials[] = {1, 1, 2};
  static const int kSpecies[] = {4, 6, 8};
  c.population = kPop[p];
  c.maxSegs = kSegs[p];
  c.trials = kTrials[p];
  c.targetSpecies = kSpecies[p];
  return c;
}

static void Fuzz()
{
  Rng r(7);
  int invalid = 0, total = 0, fails = 0;
  for (int lineage = 0; lineage < 2000; lineage++)
  {
    BodyGenome g = RandomBody(r, 16);
    for (int k = 0; k < 100; k++)
    {
      BodyGenome c = g;
      MutateBody(c, r, 2.0f);
      if (r.Chance(0.2f))
        c = CrossBody(c, RandomBody(r, 16), r);
      Phenotype ph;
      total++;
      if (!Expand(c, 16, ph))
      {
        fails++; // the breeder re-rolls these
        continue;
      }
      bool ok = ph.numSegs >= 2 && ph.numSegs <= MAX_SEGS && ph.numParts == ph.numSegs + 1 &&
                ph.numJoints == ph.numSegs - 1 && ph.totalMass > 0;
      for (int i = 0; i < ph.numParts && ok; i++)
        ok = std::isfinite(ph.px[i]) && std::isfinite(ph.py[i]) && ph.py[i] >= -1e-4f && ph.mass[i] > 0;
      for (int s = 0; s < ph.numSegs && ok; s++)
        ok = ph.seg[s].len >= 0.05f && ph.seg[s].a < ph.numParts && ph.seg[s].b < ph.numParts;
      invalid += !ok;
      g = c;
    }
  }
  std::printf("fuzz: %d offspring, %d invalid, %d degenerate (re-rolled)\n", total, invalid, fails);
  CHECK(invalid == 0, "invalid bodies %d", invalid);
}

static void Property()
{
  Rng r(11);
  Innovations inn;
  inn.Reset();
  int unstable = 0, runs = 0;
  for (int terrain = 0; terrain < GOAL_COUNT; terrain++)
  {
    WorldSpec w = MakeWorld(terrain, 1000 + terrain, false);
    w.duration = 10.0f;
    for (int k = 0; k < 150; k++)
    {
      Individual ind;
      ind.body = RandomBody(r, 16);
      if (!Expand(ind.body, 16, ind.ph))
        continue;
      ind.brain = RandomBrain(r, inn);
      for (int m = 0; m < 30; m++)
        MutateBrain(ind.brain, inn, r, 3.0f);
      Trial t;
      t.Init(ind.ph, ind.brain, &w);
      // run the full 10 s even past early termination
      bool finite = true;
      for (int s = 0; s < 600; s++)
      {
        t.Step();
        for (int i = 0; i < ind.ph.numParts; i++)
          finite = finite && std::isfinite(t.x[i]) && std::isfinite(t.y[i]);
      }
      runs++;
      if (!finite || t.res.stop == STOP_UNSTABLE)
        unstable++;
    }
  }
  std::printf("property: %d random creatures x 10 s, %d unstable\n", runs, unstable);
  CHECK(unstable == 0, "%d of %d random creatures went unstable", unstable, runs);
}

static void Momentum()
{
  // no gravity, no ground under it: flailing must not move the centre of mass
  Rng r(5);
  Innovations inn;
  inn.Reset();
  WorldSpec w = MakeWorld(G_WALK, 3, false);
  w.gravity = 0.0f;
  w.air = 0.0f; // fins push on air legitimately: that is flight
  float worst = 0.0f;
  for (int k = 0; k < 40; k++)
  {
    BodyGenome g = RandomBody(r, 12);
    Phenotype ph;
    if (!Expand(g, 12, ph))
      continue;
    BrainGenome b = RandomBrain(r, inn);
    Trial t;
    for (float& h : w.h)
      h = 0.0f;
    t.Init(ph, b, &w);
    for (float& h : w.h) // then take the ground away
      h = -1000.0f;
    const float x0 = t.cx, y0 = t.cy;
    for (int s = 0; s < 600; s++)
      t.Step();
    worst = std::max(worst, std::fabs(t.cx - x0) + std::fabs(t.cy - y0));
  }
  std::printf("momentum: worst centre-of-mass drift in free flight %.4f m over 10 s\n", worst);
  CHECK(worst < 0.05f, "a creature swam through empty space: %.3f m", worst);
}

static void Determinism()
{
  WorkerPool one, four;
  one.Start(1);
  four.Start(4);
  Config c = Profile(1);
  c.population = 40;
  Evolution a, b;
  a.Reset(c, 1234);
  b.Reset(c, 1234);
  for (int g = 0; g < 4; g++)
  {
    a.RunGeneration(one);
    b.RunGeneration(four);
  }
  bool same = true;
  for (size_t i = 0; i < a.population().size(); i++)
    same = same && a.population()[i].fitness == b.population()[i].fitness &&
           a.population()[i].id == b.population()[i].id;
  CHECK(same, "four threads differ from one");

  // replay: the stage steps the same Trial in real time
  auto snap = a.Latest();
  int mismatches = 0;
  for (size_t i = 0; i < std::min<size_t>(snap->pop.size(), 12); i++)
  {
    const Individual& ind = snap->pop[i];
    Trial t;
    t.Init(ind.ph, ind.brain, snap->world.get());
    const int n = static_cast<int>(snap->world->duration / kDt) + 2;
    for (int s = 0; s < n; s++)
      t.Step();
    if (t.res.fitness != ind.res.fitness)
      mismatches++;
  }
  std::printf("determinism: 1 vs 4 threads %s, replay mismatches %d of 12\n", same ? "identical" : "DIFFERENT", mismatches);
  CHECK(mismatches == 0, "replays differ from evaluation");
}

static float RunEvolution(int goal, int gens, uint64_t seed, bool verbose, int profile = 1)
{
  WorkerPool pool;
  pool.Start(0);
  Config c = Profile(profile);
  c.goal = goal;
  c.epochGens = -1;
  Evolution e;
  e.Reset(c, seed);
  float first = 0, last = 0;
  for (int g = 0; g < gens; g++)
  {
    e.RunGeneration(pool);
    auto s = e.Latest();
    const Individual& best = s->pop[0];
    char score[48];
    ScoreText(s->world->goal, best.res, score, sizeof(score));
    if (g == 0)
      first = best.fitness;
    last = std::max(last, best.fitness);
    if (verbose)
      std::printf("  gen %3d  best %6.2f (%s, %s, %d segs, %d hidden, %d conns)  mean %5.2f  species %d  %.0f ms\n", g,
                  best.fitness, score, best.name, best.traits.segs, static_cast<int>(best.brain.hidden.size()),
                  best.brain.Enabled(), s->history.back().mean, static_cast<int>(s->species.size()), s->evalMs);
  }
  if (verbose)
  {
    auto s = e.Latest();
    for (const Event& ev : s->events)
      std::printf("  [%d] %s\n", ev.gen, ev.text);
  }
  return first > 0 ? last / first : last;
}

int main(int argc, char** argv)
{
  if (argc >= 3 && std::strcmp(argv[1], "evolve") == 0)
  {
    const int goal = std::atoi(argv[2]);
    const int gens = argc > 3 ? std::atoi(argv[3]) : 40;
    const uint64_t seed = argc > 4 ? std::strtoull(argv[4], nullptr, 10) : 1;
    std::printf("improvement x%.2f\n", RunEvolution(goal, gens, seed, true));
    return 0;
  }
  const bool quick = argc > 1 && std::strcmp(argv[1], "quick") == 0;
  Fuzz();
  Property();
  Momentum();
  Determinism();

  if (!quick)
  {
    for (uint64_t seed = 1; seed <= 3; seed++)
    {
      const float k = RunEvolution(G_WALK, 30, seed, false);
      std::printf("evolution: walk, seed %llu: best improved x%.2f in 30 generations\n",
                  static_cast<unsigned long long>(seed), k);
      CHECK(k > 1.5f, "walking did not improve on seed %llu (x%.2f)", static_cast<unsigned long long>(seed), k);
    }
    for (int goal = 0; goal < GOAL_COUNT; goal++)
    {
      const float k = RunEvolution(goal, 12, 40 + goal, false);
      std::printf("evolution: %-26s x%.2f in 12 generations\n", GoalName(goal), k);
    }
    // a long random-goal run: epochs change, nothing breaks, memory stays bounded
    {
      WorkerPool pool;
      pool.Start(0);
      Config c = Profile(0);
      Evolution e;
      e.Reset(c, 99);
      for (int g = 0; g < 150; g++)
        e.RunGeneration(pool);
      auto s = e.Latest();
      std::printf("long run: 150 generations, %d epochs, %d species, %d events kept, archive %d/%d\n", s->epoch,
                  static_cast<int>(s->species.size()), static_cast<int>(s->events.size()), s->archiveFilled,
                  s->archiveCells);
      CHECK(s->epoch >= 3, "goals did not change");
    }
  }

  // benchmark
  for (int p = 0; p < 3; p++)
  {
    static const char* kNames[] = {"Low", "Balanced", "High"};
    for (int threads : {1, 3})
    {
      WorkerPool pool;
      pool.Start(threads);
      Config c = Profile(p);
      c.goal = G_WALK;
      Evolution e;
      e.Reset(c, 5);
      double total = 0;
      const int gens = 6;
      for (int g = 0; g < gens; g++)
      {
        const auto t0 = std::chrono::steady_clock::now();
        e.RunGeneration(pool);
        total += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
      }
      std::printf("bench: %-8s pop %3d, %d thread(s): %.0f ms a generation\n", kNames[p], c.population, threads,
                  total / gens);
    }
  }
  // one stage step: a creature's physics and brain, the unit the stage pays per frame
  {
    Rng r(3);
    Innovations inn;
    inn.Reset();
    WorldSpec w = MakeWorld(G_WALK, 9, false);
    Phenotype ph;
    BodyGenome g;
    do
      g = RandomBody(r, 16);
    while (!Expand(g, 16, ph) || ph.numSegs < 10);
    BrainGenome b = RandomBrain(r, inn);
    for (int m = 0; m < 60; m++)
      MutateBrain(b, inn, r, 2.0f);
    Trial t;
    t.Init(ph, b, &w);
    const auto t0 = std::chrono::steady_clock::now();
    const int n = 200000;
    for (int s = 0; s < n; s++)
      t.Step();
    const double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count() / n;
    std::printf("bench: one creature step (%d segments): %.2f us\n", ph.numSegs, us);
  }

  if (g_failures)
    std::printf("%d FAILURE(S)\n", g_failures);
  else
    std::printf("all checks passed\n");
  return g_failures ? 1 : 0;
}

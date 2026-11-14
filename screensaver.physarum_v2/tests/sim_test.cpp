// Checks and benchmarks the Physarum v2 simulation without Kodi.
//
//   c++ -O3 -std=c++17 -Isrc tests/sim_test.cpp -o /tmp/physarum_test -pthread && /tmp/physarum_test
//   /tmp/physarum_test out.pgm   # also writes the picture after 600 steps
//
// - one thread and four threads give the same agents when deposits cannot race
//   (one species, one worker), and nearly the same trail mass with four;
// - the trail stays bounded and a network forms (the picture is far from flat);
// - every species and start runs and lays a trail;
// - ms per step for a few sizes.
#include "Physarum.h"
#include "WorkerPool.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <functional>

using namespace physarum;

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

static void Setup(Simulation& sim, int w, int h, int species, size_t agents, int preset, int start)
{
  sim.Configure(w, h, species, agents);
  const Params base = FromDef(kPresets[preset], w / 960.0f);
  for (int s = 0; s < species; s++)
    sim.SetParams(s, ForSpecies(base, s, true));
  sim.Spawn(start, 1234);
}

static void StepPool(Simulation& sim, WorkerPool& pool)
{
  pool.Run(sim.agents(), [&](size_t lo, size_t hi) { sim.MoveAgents(lo, hi); });
  pool.Run(static_cast<size_t>(sim.height()), [&](size_t lo, size_t hi) { sim.DiffuseRows(lo, hi); });
  sim.EndStep();
}

static double Mass(const Simulation& sim)
{
  double m = 0;
  for (uint16_t v : sim.trail())
    m += v;
  return m;
}

// Standard deviation / mean of the picture: ~0 for a flat haze, high for a network.
static double Contrast(const Simulation& sim)
{
  const size_t n = static_cast<size_t>(sim.width()) * sim.height() * sim.species();
  double sum = 0, sq = 0;
  for (size_t i = 0; i < n; i++)
  {
    sum += sim.display()[i];
    sq += double(sim.display()[i]) * sim.display()[i];
  }
  const double mean = sum / n;
  return mean > 0 ? std::sqrt(std::max(0.0, sq / n - mean * mean)) / mean : 0;
}

int main(int argc, char** argv)
{
  // 1. deterministic with one thread; same result through the pool with one worker
  {
    Simulation a, b;
    Setup(a, 320, 180, 1, 20000, 0, START_RANDOM);
    Setup(b, 320, 180, 1, 20000, 0, START_RANDOM);
    WorkerPool one;
    one.Start(1);
    for (int i = 0; i < 50; i++)
    {
      a.Step();
      StepPool(b, one);
    }
    bool same = true;
    for (size_t i = 0; i < a.agents() && same; i++)
      same = a.agentList()[i].x == b.agentList()[i].x && a.agentList()[i].y == b.agentList()[i].y && a.agentList()[i].a == b.agentList()[i].a;
    CHECK(same, "single-threaded runs differ");
  }

  // 2. four threads: trail mass within a few percent of one thread
  {
    Simulation a, b;
    Setup(a, 480, 270, 1, 100000, 0, START_RANDOM);
    Setup(b, 480, 270, 1, 100000, 0, START_RANDOM);
    WorkerPool four;
    four.Start(4);
    for (int i = 0; i < 200; i++)
    {
      a.Step();
      StepPool(b, four);
    }
    const double ma = Mass(a), mb = Mass(b);
    CHECK(std::fabs(ma - mb) / ma < 0.05, "mass 1 thread %.0f vs 4 threads %.0f", ma, mb);
  }

  // 3. every preset forms a pattern and stays bounded; every start and species count runs
  for (int p = 0; p < kNumPresets; p++)
  {
    Simulation sim;
    Setup(sim, 480, 270, 1, 100000, p, START_RANDOM);
    for (int i = 0; i < 400; i++)
      sim.Step();
    const double c = Contrast(sim);
    std::printf("preset %-20s contrast %.2f\n", kPresets[p].name, c);
    CHECK(c > 0.3, "preset %s stayed flat (contrast %.2f)", kPresets[p].name, c);
  }
  for (int species = 1; species <= 3; species++)
    for (int start = 0; start < START_COUNT; start++)
    {
      Simulation sim;
      Setup(sim, 320, 180, species, 30000, 0, start);
      for (int i = 0; i < 100; i++)
        sim.Step();
      CHECK(Mass(sim) > 0, "no trail (species %d, start %d)", species, start);
    }

  // 4. benchmark
  struct Case
  {
    int w, h, species;
    size_t agents;
    int threads;
  } cases[] = {{640, 360, 1, 100000, 1}, {640, 360, 1, 100000, 4}, {640, 360, 1, 250000, 4},
               {960, 540, 1, 500000, 4}, {640, 360, 3, 250000, 4}, {1280, 720, 1, 1000000, 4}};
  for (const Case& c : cases)
  {
    Simulation sim;
    Setup(sim, c.w, c.h, c.species, c.agents, 0, START_RANDOM);
    WorkerPool pool;
    pool.Start(c.threads);
    for (int i = 0; i < 30; i++)
      StepPool(sim, pool);
    const int n = 200;
    const auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < n; i++)
      StepPool(sim, pool);
    const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count() / n;
    std::printf("%4dx%-4d %d species %7zu agents %d thread(s): %.2f ms/step\n", c.w, c.h, c.species, c.agents,
                c.threads, ms);
  }

  if (argc > 1)
  {
    Simulation sim;
    Setup(sim, 640, 360, 1, 150000, argc > 2 ? std::atoi(argv[2]) : 0, START_RANDOM);
    for (int i = 0; i < 600; i++)
      sim.Step();
    FILE* f = std::fopen(argv[1], "wb");
    std::fprintf(f, "P5 %d %d 255\n", sim.width(), sim.height());
    std::fwrite(sim.display(), 1, static_cast<size_t>(sim.width()) * sim.height(), f);
    std::fclose(f);
  }

  std::printf(g_failures ? "%d FAILURE(S)\n" : "all passed\n", g_failures);
  return g_failures ? 1 : 0;
}

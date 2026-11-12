// Standalone check: grid-based Interaction() must match the original
// brute-force loop (for distinct groups), and report step timing.
//   c++ -O2 -std=c++17 tests/sim_test.cpp -o sim_test && ./sim_test
#include "../src/ParticleLife.h"
#include <chrono>
#include <cstdio>

using namespace particlelife;

static void BruteForce(Group& g1, const Group& g2, float G, float radius, const Params& p, float W, float H)
{
  const float g = G / -100.0f;
  for (size_t i = 0; i < g1.size(); i++)
  {
    float fx = 0, fy = 0;
    for (size_t j = 0; j < g2.size(); j++)
    {
      const float dx = g1.x[i] - g2.x[j], dy = g1.y[i] - g2.y[j];
      const float d2 = dx * dx + dy * dy;
      if (d2 > 0 && d2 < radius * radius)
      {
        const float inv = 1.0f / std::sqrt(d2);
        fx += dx * inv;
        fy += dy * inv;
      }
    }
    const float wr = p.wallRepel;
    float& vx = g1.vx[i];
    float& vy = g1.vy[i];
    vx += g1.x[i] < wr ? (wr - g1.x[i]) * 0.1f : 0.0f;
    vy += g1.y[i] < wr ? (wr - g1.y[i]) * 0.1f : 0.0f;
    vx += g1.x[i] > W - wr ? (W - wr - g1.x[i]) * 0.1f : 0.0f;
    vy += g1.y[i] > H - wr ? (H - wr - g1.y[i]) * 0.1f : 0.0f;
    vx = (vx + fx * g) * (1 - p.viscosity);
    vy = (vy + fy * g) * (1 - p.viscosity) + p.gravity;
    g1.x[i] += vx;
    g1.y[i] += vy;
  }
}

int main()
{
  Simulation sim(1234);
  sim.params.perColour = 1000;
  sim.Resize(1600, 900);
  sim.Randomize();

  // exactness: green <- red, different groups, so no in-place aliasing
  Group ref = sim.group(GREEN);
  const Group src = sim.group(RED);
  const float G = sim.power(GREEN, RED), R = sim.radius(GREEN, RED);
  BruteForce(ref, src, G, R, sim.params, 1600, 900);
  Group test = sim.group(GREEN);
  sim.Interaction(test, src, G, R);
  float maxDiff = 0;
  for (size_t i = 0; i < ref.size(); i++)
    maxDiff = std::max({maxDiff, std::fabs(ref.x[i] - test.x[i]), std::fabs(ref.y[i] - test.y[i])});
  std::printf("max |grid - brute force| after one interaction: %g (radius %.1f, power %.1f)\n", maxDiff, R, G);

  auto finite = [&]() {
    bool ok = true;
    for (int c = 0; c < sim.numGroups(); c++)
      for (size_t i = 0; i < sim.group(c).size(); i++)
        ok = ok && std::isfinite(sim.group(c).x[i]) && std::isfinite(sim.group(c).y[i]);
    return ok;
  };
  auto timeSteps = [&](int steps) {
    auto t0 = std::chrono::steady_clock::now();
    for (int s = 0; s < steps; s++)
      sim.Step();
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count() / steps;
  };
  int failures = maxDiff < 1e-3f ? 0 : 1;

  // timing + sanity (no NaNs, particles stay finite) for 4 and 8 colours
  sim.params.evolve = true;
  sim.params.explore = true;
  sim.params.explorePeriod = 20;
  for (int colours : {4, 8})
    for (int n : {500, 1000, 2000})
    {
      sim.SetNumGroups(colours);
      sim.params.perColour = n;
      sim.Randomize();
      sim.Pulse(800, 450, 10);
      const double ms = timeSteps(200);
      const bool ok = finite();
      failures += !ok;
      std::printf("%d colours, %4d per colour (%5d total): %6.2f ms/step, finite=%d\n", colours, n,
                  n * colours, ms, ok);
    }
  sim.params.evolve = false;
  sim.params.explore = false;

  // only the active groups have particles
  sim.SetNumGroups(3);
  sim.params.perColour = 100;
  sim.Randomize();
  failures += sim.group(3).size() != 0 || sim.group(2).size() != 100;

  // symmetric rules
  sim.SetNumGroups(6);
  sim.params.symmetric = true;
  sim.Randomize();
  for (int a = 0; a < 6; a++)
    for (int b = 0; b < 6; b++)
      failures += sim.power(a, b) != sim.power(b, a);
  sim.params.symmetric = false;

  // presets: four colours, values copied, all of them run
  sim.params.perColour = 1000;
  double worst = 0;
  for (int i = 0; i < kNumPresets; i++)
  {
    sim.SetNumGroups(7);
    sim.LoadPreset(i);
    failures += sim.numGroups() != 4 || sim.power(1, 0) != kPresets[i].power[1][0] ||
                sim.params.viscosity != kPresets[i].viscosity;
    const double ms = timeSteps(60);
    worst = std::max(worst, ms);
    failures += !finite();
  }
  std::printf("presets: %d loaded, slowest %.2f ms/step at 1000 per colour\n", kNumPresets, worst);
  // "Worm": the original's file lists green first; check the reorder (red x green = file's RG)
  sim.LoadPreset(17);
  std::printf("preset 17 = %s, red<-green %.4g (file -16), green<-red %.4g (file 4.66666)\n",
              kPresets[17].name, sim.power(RED, GREEN), sim.power(GREEN, RED));

  std::printf(failures ? "FAILED (%d)\n" : "all checks passed\n", failures);
  return failures ? 1 : 0;
}

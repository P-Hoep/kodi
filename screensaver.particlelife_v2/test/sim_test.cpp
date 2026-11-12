// Standalone check: grid-based Interaction() must match the original
// brute-force loop (for distinct groups), and report step timing.
//   g++ -O2 -std=c++17 test/sim_test.cpp -o sim_test && ./sim_test
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

  // timing + sanity (no NaNs, particles stay finite)
  for (int n : {500, 1000, 2000})
  {
    sim.params.perColour = n;
    sim.params.evolve = true;
    sim.Randomize();
    auto t0 = std::chrono::steady_clock::now();
    for (int s = 0; s < 300; s++)
      sim.Step();
    auto ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count() / 300;
    bool ok = true;
    for (int c = 0; c < NUM_GROUPS; c++)
      for (size_t i = 0; i < sim.group(c).size(); i++)
        ok = ok && std::isfinite(sim.group(c).x[i]) && std::isfinite(sim.group(c).y[i]);
    std::printf("%4d per colour (%5d total): %.2f ms/step, finite=%d\n", n, n * 4, ms, ok);
  }
  return 0;
}

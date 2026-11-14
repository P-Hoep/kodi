// Offline tests for the boids core (no Kodi, no GL):
//   c++ -O2 -std=c++17 -Isrc tests/sim_test.cpp -o /tmp/boids_test -pthread && /tmp/boids_test
//
// 1. the grid neighbour search matches an all-pairs reference;
// 2. a threaded step is bit-identical to a single-threaded one;
// 3. a long run stays finite, in bounds and actually flocks;
// 4. timings per step for a few flock sizes.
#include "Boids.h"
#include "WorkerPool.h"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>

using boids::Simulation;

static int g_failures = 0;
#define CHECK(cond, ...)                \
  do                                    \
  {                                     \
    if (!(cond))                        \
    {                                   \
      std::printf("FAIL: " __VA_ARGS__); \
      std::printf("\n");                \
      g_failures++;                     \
    }                                   \
  } while (0)

static uint32_t Tint(std::mt19937&, uint8_t sp) { return 0xff000000u | sp; }

// All-pairs version of UpdateRange's velocity rule, on the sorted state that
// BeginStep() produced. Returns the new velocity of boid i.
static void Reference(const Simulation& s, size_t i, float& ovx, float& ovy)
{
  const auto& p = s.params;
  const float* X = s.x();
  const float* Y = s.y();
  const float* VX = s.vx();
  const float* VY = s.vy();
  const uint8_t* SP = s.species();
  const float px = X[i], py = Y[i], vx = VX[i], vy = VY[i];
  const float v2 = vx * vx + vy * vy;
  const bool wrap = p.edges == boids::EDGES_WRAP;
  float sepX = 0, sepY = 0, aliX = 0, aliY = 0, cohX = 0, cohY = 0;
  int sepN = 0, flockN = 0;
  for (size_t k = 0; k < s.size(); k++)
  {
    float dx = X[k] - px, dy = Y[k] - py;
    if (wrap)
    {
      if (dx > s.width() / 2) dx -= s.width();
      if (dx < -s.width() / 2) dx += s.width();
      if (dy > s.height() / 2) dy -= s.height();
      if (dy < -s.height() / 2) dy += s.height();
    }
    const float d2 = dx * dx + dy * dy;
    if (d2 >= p.vision * p.vision || d2 <= 1e-6f)
      continue;
    const float dot = dx * vx + dy * vy;
    if (p.blindSpot && dot < 0 && dot * dot > 0.413f * v2 * d2)
      continue;
    if (d2 < p.separation * p.separation)
    {
      sepX -= dx / d2;
      sepY -= dy / d2;
      sepN++;
    }
    if (SP[k] == SP[i])
    {
      aliX += VX[k];
      aliY += VY[k];
      cohX += dx;
      cohY += dy;
      flockN++;
    }
  }
  auto steer = [&](float dx, float dy, float w, float& ax, float& ay) {
    const float d = std::sqrt(dx * dx + dy * dy);
    if (d < 1e-6f) return;
    float sx = dx / d * p.maxSpeed - vx, sy = dy / d * p.maxSpeed - vy;
    const float m = std::sqrt(sx * sx + sy * sy);
    if (m > p.maxForce) { sx *= p.maxForce / m; sy *= p.maxForce / m; }
    ax += sx * w;
    ay += sy * w;
  };
  float ax = 0, ay = 0;
  if (sepN) steer(sepX, sepY, p.sepWeight, ax, ay);
  if (flockN)
  {
    steer(aliX, aliY, p.alignWeight, ax, ay);
    steer(cohX, cohY, p.cohWeight, ax, ay);
  }
  float nvx = vx + ax, nvy = vy + ay;
  if (!wrap)
  {
    const float m = p.margin;
    if (px < m) nvx += p.turn * (1 - px / m);
    else if (px > s.width() - m) nvx -= p.turn * (1 - (s.width() - px) / m);
    if (py < m) nvy += p.turn * (1 - py / m);
    else if (py > s.height() - m) nvy -= p.turn * (1 - (s.height() - py) / m);
  }
  const float sp = std::sqrt(nvx * nvx + nvy * nvy);
  if (sp > p.maxSpeed) { nvx *= p.maxSpeed / sp; nvy *= p.maxSpeed / sp; }
  else if (sp < p.minSpeed && sp > 0) { nvx *= p.minSpeed / sp; nvy *= p.minSpeed / sp; }
  ovx = nvx;
  ovy = nvy;
}

static void TestAgainstReference(int edges, int species)
{
  Simulation s(1234);
  s.Resize(1778, 1000);
  s.params.count = 1500;
  s.params.species = species;
  s.params.edges = edges;
  s.params.maxNeighbours = 0; // the cap makes the result order-dependent
  s.Restart(Tint);
  for (int i = 0; i < 50; i++) // let the flocks bunch up first
    s.Step();

  s.BeginStep();
  std::vector<float> rvx(s.size()), rvy(s.size());
  for (size_t i = 0; i < s.size(); i++)
    Reference(s, i, rvx[i], rvy[i]);
  s.UpdateRange(0, s.size());
  s.EndStep();

  float worst = 0;
  for (size_t i = 0; i < s.size(); i++)
    worst = std::max(worst, std::max(std::fabs(rvx[i] - s.vx()[i]), std::fabs(rvy[i] - s.vy()[i])));
  std::printf("reference (%s, %d species): max |dv| = %.2e\n",
              edges == boids::EDGES_WRAP ? "wrap" : "turn", species, worst);
  CHECK(worst < 1e-3f, "grid result differs from all-pairs by %g", worst);
}

static void TestThreadsIdentical()
{
  Simulation a(99), b(99);
  for (Simulation* s : {&a, &b})
  {
    s->Resize(1778, 1000);
    s->params.count = 5000;
    s->params.species = 3;
    s->params.predators = 2;
    s->params.leadWeight = 0.4f;
    s->Restart(Tint);
  }
  boids::WorkerPool pool;
  pool.Start(4);
  for (int i = 0; i < 300; i++)
  {
    a.Step();
    b.BeginStep();
    pool.Run(b.size(), [&](size_t lo, size_t hi) { b.UpdateRange(lo, hi); });
    b.EndStep();
  }
  const bool same = std::memcmp(a.x(), b.x(), a.size() * sizeof(float)) == 0 &&
                    std::memcmp(a.vy(), b.vy(), a.size() * sizeof(float)) == 0;
  std::printf("threads (%d) vs single: %s\n", pool.threads(), same ? "identical" : "DIFFERENT");
  CHECK(same, "threaded run diverged from the single-threaded run");
}

static void TestHealth(int edges)
{
  Simulation s(7);
  s.Resize(1778, 1000);
  s.params.count = 2000;
  s.params.edges = edges;
  s.params.predators = 1;
  s.params.leadWeight = 0.35f;
  s.Restart(Tint);
  for (int i = 0; i < 3000; i++)
    s.Step();

  bool finite = true, inside = true;
  double order = 0; // mean over boids of the alignment with their neighbours
  for (size_t i = 0; i < s.size(); i++)
  {
    finite &= std::isfinite(s.x()[i]) && std::isfinite(s.vx()[i]) && std::isfinite(s.vy()[i]);
    inside &= s.x()[i] >= 0 && s.x()[i] <= s.width() && s.y()[i] >= 0 && s.y()[i] <= s.height();
  }
  // local polarisation: |sum of unit headings| / count over 55-unit neighbourhoods
  size_t counted = 0;
  for (size_t i = 0; i < s.size(); i += 7)
  {
    float hx = 0, hy = 0;
    int n = 0;
    for (size_t k = 0; k < s.size(); k++)
    {
      const float dx = s.x()[k] - s.x()[i], dy = s.y()[k] - s.y()[i];
      if (dx * dx + dy * dy < 55 * 55)
      {
        const float v = std::sqrt(s.vx()[k] * s.vx()[k] + s.vy()[k] * s.vy()[k]);
        hx += s.vx()[k] / v;
        hy += s.vy()[k] / v;
        n++;
      }
    }
    if (n > 2)
    {
      order += std::sqrt(hx * hx + hy * hy) / n;
      counted++;
    }
  }
  order /= std::max<size_t>(counted, 1);
  std::printf("health (%s): finite %d, in bounds %d, local alignment %.2f\n",
              edges == boids::EDGES_WRAP ? "wrap" : "turn", finite, inside, order);
  CHECK(finite, "non-finite state");
  CHECK(inside, "boid left the world");
  CHECK(order > 0.8, "boids are not flocking (local alignment %.2f)", order);
}

static void Bench(int count, int threads)
{
  Simulation s(5);
  s.Resize(1778, 1000);
  s.params.count = count;
  s.params.predators = 1;
  s.params.leadWeight = 0.35f;
  s.Restart(Tint);
  boids::WorkerPool pool;
  pool.Start(threads);
  auto step = [&] {
    s.BeginStep();
    pool.Run(s.size(), [&](size_t lo, size_t hi) { s.UpdateRange(lo, hi); });
    s.EndStep();
  };
  for (int i = 0; i < 600; i++) // flocks form and pack together: the costly state
    step();
  const int steps = 300;
  const auto t0 = std::chrono::steady_clock::now();
  for (int i = 0; i < steps; i++)
    step();
  const double ms =
      std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count() / steps;
  std::printf("bench %6d boids, %d thread(s): %.3f ms/step\n", count, pool.threads(), ms);
}

int main(int argc, char** argv)
{
  const bool benchOnly = argc > 1 && std::strcmp(argv[1], "bench") == 0;
  if (!benchOnly)
  {
    TestAgainstReference(boids::EDGES_TURN, 1);
    TestAgainstReference(boids::EDGES_WRAP, 3);
    TestThreadsIdentical();
    TestHealth(boids::EDGES_TURN);
    TestHealth(boids::EDGES_WRAP);
  }
  for (int n : {1000, 2000, 4000, 8000})
    for (int t : {1, 4})
      Bench(n, t);
  std::printf(g_failures ? "%d FAILURE(S)\n" : "all tests passed\n", g_failures);
  return g_failures ? 1 : 0;
}

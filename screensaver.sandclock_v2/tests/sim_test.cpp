// Checks and benchmarks the Sand Clock v2 simulations without Kodi.
//
//   c++ -O3 -std=c++17 -Isrc tests/sim_test.cpp -o /tmp/sandclock2_test -pthread && /tmp/sandclock2_test
//
// Sand:
// - four threads give exactly the same grid as one thread;
// - a poured heap stands at a dry-sand angle (25 to 40 degrees), and a
//   block of sand collapses into a slope, not a tower or a flat sheet;
// - every new digit is poured full within a second, no heap grows up
//   towards the clock, and the grain count stays put over a minute of clock;
// Liquid:
// - the fluid stays bounded (no explosion), keeps its volume and does not
//   leak into the digits, for every liquid and melting style;
// - the drain keeps the particle count constant;
// Benchmarks: ms per step for a few sizes, one and several threads.
#include "Liquid.h"
#include "Sand.h"
#include "WorkerPool.h"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>

using namespace sandclock2;

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

static std::string Clock(const ClockStyle& s, int second) // 12:34:SS walking on, a minute change at 60
{
  const int m = 34 + second / 60;
  return TimeText(s, 12, m % 60, second % 60);
}

// ---- sand

static void SandThreads()
{
  SandWorld a, b;
  a.Configure(480, 270, 7);
  b.Configure(480, 270, 7);
  WorkerPool one, four;
  one.Start(1);
  four.Start(4);
  for (int s = 0; s < 600; s++)
  {
    if (s % 60 == 0)
    {
      a.SetText(Clock(a.style, 50 + s / 60), s / 60.0);
      b.SetText(Clock(b.style, 50 + s / 60), s / 60.0);
    }
    a.Step(one);
    b.Step(four);
  }
  size_t diff = 0;
  for (size_t i = 0; i < static_cast<size_t>(a.width()) * a.height(); i++)
    diff += a.display()[i] != b.display()[i];
  CHECK(diff == 0, "sand: 1 and 4 threads differ in %zu cells", diff);
  std::printf("sand threads: 1 and 4 threads identical over 600 steps (%zu differing cells)\n", diff);
}

static float HeapAngle(uint32_t seed)
{
  SandWorld w;
  w.params.pile = 0.0f;
  w.Configure(480, 270, seed);
  w.Clear();
  w.drainOn = false;
  for (int s = 0; s < 8000; s++)
  {
    if (s < 5000)
      w.Drop(240 + (s % 3) - 1, 60);
    w.Step();
  }
  auto colh = [&](int x) {
    int y = 0;
    while (y < 270 && !w.At(x, y))
      y++;
    return 270 - y;
  };
  const int peak = colh(240);
  int xl = 240, xr = 240, xl2 = 240, xr2 = 240;
  while (xl > 0 && colh(xl) > peak * 0.15)
    xl--;
  while (xr < 479 && colh(xr) > peak * 0.15)
    xr++;
  while (colh(xl2) > peak * 0.85)
    xl2--;
  while (colh(xr2) > peak * 0.85)
    xr2++;
  CHECK(w.Unstable() == 0, "sand heap: %ld grains still unsupported after settling", w.Unstable());
  return (w.SurfaceSlope(xl, xl2) + w.SurfaceSlope(xr2, xr)) / 2;
}

static void SandHeap()
{
  for (uint32_t seed : {3u, 11u})
  {
    const float a = HeapAngle(seed);
    CHECK(a > 25.0f && a < 40.0f, "sand heap (seed %u): slope %.1f degrees", seed, a);
    std::printf("sand heap (seed %u): poured heap stands at %.1f degrees\n", seed, a);
  }
}

static void SandBlock()
{
  SandWorld w;
  w.params.pile = 0;
  w.Configure(200, 120, 3);
  w.Clear();
  w.drainOn = false;
  for (int y = 60; y < 120; y++)
    for (int x = 90; x < 110; x++)
      w.Drop(x, y);
  for (int s = 0; s < 600; s++)
    w.Step();
  auto colh = [&](int x) {
    int y = 0;
    while (y < 120 && !w.At(x, y))
      y++;
    return 120 - y;
  };
  const int peak = colh(100);
  const float slope = w.SurfaceSlope(70, 95);
  CHECK(peak < 60 && peak > 15, "sand block: peak %d rows after collapsing", peak);
  CHECK(slope > 20.0f && slope < 45.0f, "sand block: collapsed to %.1f degrees", slope);
  CHECK(w.Unstable() == 0, "sand block: %ld grains unsupported", w.Unstable());
  std::printf("sand block: a 60-row column collapses to a %d-row heap at %.1f degrees\n", peak, slope);
}

static void SandClockRun(int newDigits, int crumble)
{
  SandWorld w;
  w.params.newDigits = newDigits;
  w.params.crumble = crumble;
  w.Configure(480, 270, 5);
  WorkerPool pool;
  pool.Start(4);
  long grains0 = -1;
  long incomplete = 0;
  bool minuteChanged = false;
  for (int s = 0; s < 60 * 70; s++) // 70 clock seconds, one minute change
  {
    if (s % 60 == 0)
    {
      // the seconds are complete before they change; the other digits take
      // their time and get two seconds
      if (s > 0 && !minuteChanged && w.EmptyMould() > 0)
        incomplete++;
      const std::string text = Clock(w.style, 50 + s / 60);
      minuteChanged = !w.text().empty() && text.substr(0, 5) != w.text().substr(0, 5);
      w.SetText(text, s / 60.0);
    }
    w.Step(pool);
    if (s == 120)
      grains0 = w.grains();
  }
  // no heap may grow towards the clock (sand standing on sand, up from the floor)
  int tallest = 0;
  for (int x = 0; x < w.width(); x++)
  {
    int y = w.height();
    while (y > 0 && w.At(x, y - 1) && !w.HeldAt(x, y - 1))
      y--;
    tallest = std::max(tallest, w.height() - y);
  }
  CHECK(tallest < w.height() * 0.42, "sand clock: a heap stands %d rows tall", tallest);
  const double drift = std::fabs(static_cast<double>(w.grains() - grains0)) / grains0;
  CHECK(incomplete == 0, "sand clock (new %d, crumble %d): %ld digits unfinished after a second", newDigits,
        crumble, incomplete);
  CHECK(drift < 0.03, "sand clock: grain count drifted %.1f%% (%ld -> %ld)", drift * 100, grains0, w.grains());
  std::printf("sand clock (new digits %d, crumble %d): every digit complete within its second, %ld grains "
              "(%.2f%% drift), tallest heap %d rows\n",
              newDigits, crumble, w.grains(), drift * 100, tallest);
}

// ---- liquid

static void LiquidRun(int viscosity, int melt, bool whole)
{
  static const float kVisc[][3] = {{0.95f, 0.0f, 0.35f}, {0.85f, 0.05f, 0.55f}, {0.6f, 0.15f, 0.7f}, {0.35f, 0.3f, 0.8f}};
  LiquidWorld w;
  w.params.flip = kVisc[viscosity][0];
  w.params.smooth = kVisc[viscosity][1];
  w.params.stick = kVisc[viscosity][2];
  w.params.melt = melt;
  w.params.wholeClock = whole;
  w.params.slosh = 0.08f;
  w.Configure(128, 72, 9);
  WorkerPool pool;
  pool.Start(4);
  const size_t n0 = w.particles();
  float maxSpeed = 0, minDensity = 9, maxDensity = 0;
  double inSolid = 0;
  int samples = 0;
  bool finite = true;
  for (int s = 0; s < 60 * 65; s++)
  {
    if (s % 60 == 0)
      w.SetText(Clock(w.style, 50 + s / 60), s / 60.0);
    w.Step(pool);
    if (s > 60)
    {
      maxSpeed = std::max(maxSpeed, w.MaxSpeed());
      const float d = w.MeanDensityRatio();
      minDensity = std::min(minDensity, d);
      maxDensity = std::max(maxDensity, d);
      inSolid += w.ParticlesInSolid();
      samples++;
      finite = finite && std::isfinite(w.MaxSpeed()) && w.LowestParticleY() < w.height();
    }
  }
  CHECK(finite, "liquid %d/%d: particles left the box or went NaN", viscosity, melt);
  CHECK(maxSpeed < 250.0f, "liquid %d/%d: max speed %.0f cells/s", viscosity, melt, maxSpeed);
  CHECK(minDensity > 0.6f && maxDensity < 1.5f, "liquid %d/%d: density ratio %.2f..%.2f", viscosity, melt,
        minDensity, maxDensity);
  inSolid /= samples; // brief while a digit thaws from one side; should stay rare
  CHECK(inSolid < 5.0, "liquid %d/%d: %.1f particles inside the digits on average", viscosity, melt, inSolid);
  const double drift = std::fabs(static_cast<double>(w.particles()) - n0) / n0;
  CHECK(drift < 0.1, "liquid %d/%d: particle count %zu -> %zu", viscosity, melt, n0, w.particles());
  std::printf("liquid (viscosity %d, melt %d%s): max speed %.0f, density %.2f..%.2f, %.1f in digits, "
              "%zu -> %zu particles\n",
              viscosity, melt, whole ? ", whole clock" : "", maxSpeed, minDensity, maxDensity, inSolid, n0,
              w.particles());
}

// ---- benchmarks

template <typename World>
static double Bench(World& w, int threads, int steps)
{
  WorkerPool pool;
  pool.Start(threads);
  for (int s = 0; s < 120; s++) // warm up past the first digits
  {
    if (s % 60 == 0)
      w.SetText(Clock(w.style, 50 + s / 60), s / 60.0);
    w.Step(pool);
  }
  const auto t0 = std::chrono::steady_clock::now();
  for (int s = 0; s < steps; s++)
  {
    if (s % 60 == 0)
      w.SetText(Clock(w.style, 52 + s / 60), 2 + s / 60.0);
    w.Step(pool);
  }
  return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count() / steps;
}

static void Benchmarks(int maxThreads)
{
  for (int rows : {216, 270, 360})
    for (int t : {1, maxThreads})
    {
      SandWorld w;
      w.Configure(rows * 16 / 9, rows, 1);
      const double ms = Bench(w, t, 600);
      std::printf("bench sand   %4dx%-4d %d thread(s): %.3f ms/step\n", w.width(), w.height(), t, ms);
    }
  for (int rows : {54, 72, 90})
    for (int t : {1, maxThreads})
    {
      LiquidWorld w;
      w.Configure(rows * 16 / 9, rows, 1);
      const double ms = Bench(w, t, 600);
      std::printf("bench liquid %4dx%-4d %d thread(s): %.3f ms/step (%zu particles + %zu frozen)\n", w.width(),
                  w.height(), t, ms, w.particles(), w.frozen());
    }
}

int main(int argc, char** argv)
{
  if (argc > 1 && std::string(argv[1]) == "bench")
  {
    Benchmarks(argc > 2 ? std::atoi(argv[2]) : 4);
    return 0;
  }
  SandThreads();
  SandHeap();
  SandBlock();
  SandClockRun(NEW_POUR, CRUMBLE_BOTTOM_UP);
  SandClockRun(NEW_BUILD, CRUMBLE_AT_ONCE);
  SandClockRun(NEW_POUR, CRUMBLE_DISSOLVE);
  for (int v = 0; v < 4; v++)
    LiquidRun(v, v % 3, false);
  LiquidRun(1, MELT_DRIP, true);
  Benchmarks(4);
  if (g_failures)
  {
    std::printf("%d check(s) failed\n", g_failures);
    return 1;
  }
  std::printf("all checks passed\n");
  return 0;
}

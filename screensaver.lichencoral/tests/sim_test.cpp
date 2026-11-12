// Standalone checks for the growth simulations (no Kodi or GL needed):
//   c++ -O2 -std=c++17 -Isrc tests/sim_test.cpp -o sim_test && ./sim_test
// With a directory argument it also writes PPM snapshots: ./sim_test /tmp/out

#include "Coral.h"
#include "Lichen.h"
#include "Reef.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>

#define CHECK(cond)                                                        \
  do                                                                       \
  {                                                                        \
    if (!(cond))                                                           \
    {                                                                      \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
      std::exit(1);                                                        \
    }                                                                      \
  } while (0)

using Clock = std::chrono::steady_clock;

static double Ms(Clock::time_point a, Clock::time_point b)
{
  return std::chrono::duration<double, std::milli>(b - a).count();
}

// RGBA rows bottom-to-top -> PPM top-to-bottom.
static void WritePpm(const std::string& path, const std::vector<uint8_t>& rgba, int w, int h)
{
  FILE* f = std::fopen(path.c_str(), "wb");
  if (!f)
    return;
  std::fprintf(f, "P6\n%d %d\n255\n", w, h);
  for (int y = h - 1; y >= 0; y--)
    for (int x = 0; x < w; x++)
      std::fwrite(&rgba[(static_cast<size_t>(y) * w + x) * 4], 1, 3, f);
  std::fclose(f);
}

static void TestLichen(const char* dir, int form, uint32_t seed)
{
  lc::LichenParams p;
  p.width = 640;
  p.height = 360;
  p.duration = 180;
  p.species = 6;
  p.form = form;
  p.seed = seed;
  lc::Lichen sim;
  sim.Init(p);
  std::vector<uint8_t> rgba;
  double worst = 0, total = 0;
  int steps = 0;
  float coveredAt = -1;
  const float dt = 1.0f / 30.0f;
  for (; sim.Time() < 1.5f * p.duration; steps++)
  {
    const auto a = Clock::now();
    sim.Step(dt);
    const double ms = Ms(a, Clock::now());
    worst = std::max(worst, ms);
    total += ms;
    if (std::getenv("VERBOSE") && steps % 300 == 0)
      std::printf("  t=%.0f steps=%ld ms=%.2f colonies=%zu free=%.3f\n", sim.Time(), sim.StepsUsed(), ms,
                  sim.Colonies(), sim.FreeFraction());
    if (coveredAt < 0 && sim.FreeFraction() < 0.05f)
      coveredAt = sim.Time();
    if (dir && (steps % 1350 == 0)) // every 45 s
    {
      sim.Paint(rgba);
      WritePpm(std::string(dir) + "/lichen_f" + std::to_string(form) + "_s" +
                   std::to_string(seed) + "_t" + std::to_string(static_cast<int>(sim.Time())) + ".ppm",
               rgba, sim.Width(), sim.Height());
    }
    if (sim.Done())
      break;
  }
  const auto a = Clock::now();
  sim.Paint(rgba);
  const double paint = Ms(a, Clock::now());
  if (dir)
    WritePpm(std::string(dir) + "/lichen_f" + std::to_string(form) + "_s" + std::to_string(seed) +
                 "_end.ppm",
             rgba, sim.Width(), sim.Height());
  std::printf("lichen form %d seed %u: %zu colonies, free %.3f, covered at %.0f s (scene %g s), "
              "step avg %.2f ms worst %.2f ms, paint %.2f ms\n",
              form, seed, sim.Colonies(), sim.FreeFraction(), coveredAt, p.duration, total / steps,
              worst, paint);
  CHECK(sim.Colonies() > 3);
  CHECK(sim.FreeFraction() < 0.5f);
}

static void TestReef(const char* dir, uint32_t seed)
{
  lc::ReefParams p;
  p.width = 320;
  p.height = 180;
  p.seed = seed;
  lc::Reef sim;
  sim.Init(p);
  std::vector<uint8_t> rgba;
  double total = 0;
  int frames = 0;
  for (; sim.Time() < 180.0f; frames++)
  {
    const auto a = Clock::now();
    sim.Advance(1.0f / 30.0f);
    total += Ms(a, Clock::now());
    if (dir && frames % 900 == 0)
    {
      sim.Paint(rgba);
      WritePpm(std::string(dir) + "/reef_s" + std::to_string(seed) + "_t" +
                   std::to_string(static_cast<int>(sim.Time())) + ".ppm",
               rgba, sim.Width(), sim.Height());
    }
  }
  sim.Paint(rgba);
  if (dir)
    WritePpm(std::string(dir) + "/reef_s" + std::to_string(seed) + "_end.ppm", rgba, sim.Width(),
             sim.Height());
  std::printf("reef seed %u: cover %.2f, contrast %.3f, frame avg %.2f ms\n", seed, sim.Cover(),
              sim.Contrast(), total / frames);
  CHECK(sim.Contrast() > 0.05f); // a pattern formed rather than a uniform state
}

static void TestCoral(const char* dir, int form, uint32_t seed)
{
  lc::CoralParams p;
  p.size = 128;
  p.maxVoxels = 120000;
  p.duration = 180;
  p.form = form;
  p.seed = seed;
  lc::Coral sim;
  sim.Init(p);
  double total = 0, worst = 0;
  int frames = 0;
  for (; !sim.Done() && sim.Time() < 1.6f * p.duration; frames++)
  {
    const auto a = Clock::now();
    sim.Advance(1.0f / 30.0f);
    const double ms = Ms(a, Clock::now());
    total += ms;
    worst = std::max(worst, ms);
  }
  std::printf("coral form %d seed %u: %zu spheres, height %d, progress %.2f, done at %.0f s, "
              "frame avg %.2f ms worst %.2f ms\n",
              form, seed, sim.Voxels().size(), sim.MaxZ(), sim.Progress(), sim.Time(), total / frames,
              worst);
  CHECK(sim.Voxels().size() > 1000);
  CHECK(sim.Progress() > 0.5f);

  if (dir) // side and top projections, shaded by depth
  {
    const int n = p.size;
    for (int view = 0; view < 2; view++)
    {
      std::vector<uint8_t> img(static_cast<size_t>(n) * n * 4, 0);
      std::vector<float> depth(static_cast<size_t>(n) * n, -1e9f);
      for (const auto& v : sim.Voxels())
      {
        const float u0 = v.x, w0 = view == 0 ? v.z : v.y;
        const float d = view == 0 ? n - v.y : v.z;
        const lc::Col c = sim.ColourAt(v, sim.Time());
        const int ir = static_cast<int>(v.r + 0.5f);
        for (int dw = -ir; dw <= ir; dw++)
          for (int du = -ir; du <= ir; du++)
          {
            if (du * du + dw * dw > v.r * v.r + 0.5f)
              continue;
            const int u = static_cast<int>(u0) + du, w = static_cast<int>(w0) + dw;
            if (u < 0 || w < 0 || u >= n || w >= n)
              continue;
            const size_t i = static_cast<size_t>(w) * n + u;
            if (d > depth[i])
            {
              depth[i] = d;
              const float k = 0.3f + 0.7f * d / n;
              img[i * 4] = lc::ToByte(c.r * k);
              img[i * 4 + 1] = lc::ToByte(c.g * k);
              img[i * 4 + 2] = lc::ToByte(c.b * k);
            }
          }
      }
      WritePpm(std::string(dir) + "/coral_f" + std::to_string(form) + "_s" +
                   std::to_string(seed) + (view ? "_top" : "_side") + ".ppm",
               img, n, n);
    }
  }
}

int main(int argc, char** argv)
{
  const char* dir = argc > 1 ? argv[1] : nullptr;
  const std::string only = argc > 2 ? argv[2] : "";
  if (only.empty() || only == "lichen")
    for (int form = 0; form <= 3; form++)
      if (argc < 4 || std::atoi(argv[3]) == form)
        TestLichen(dir, form, 7 + form);
  if (only.empty() || only == "reef")
    for (uint32_t seed = 1; seed <= 3; seed++)
      TestReef(dir, seed);
  if (only.empty() || only == "coral")
    for (int form = 1; form <= 5; form++)
      TestCoral(dir, form, 3 + form);
  std::printf("ok\n");
  return 0;
}

// Checks and benchmarks the Alien Life world without Kodi.
//
//   c++ -O3 -std=c++17 -Isrc tests/sim_test.cpp -o /tmp/alien_test -pthread && /tmp/alien_test
//   /tmp/alien_test DIR [detail 0-2] [steps]   # also writes DIR/world_N.ppm previews
//
// - energy is conserved to rounding in every world, at every detail level;
// - four threads give exactly the same world as one;
// - every world stays alive: creatures reproduce, generations pass, and in
//   the hunting world the hunters both eat and survive;
// - mutation founds new lineages;
// - ms per step at each detail level.
#include "Alien.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>

using namespace alien;

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

// The detail levels of the Kodi add-on (keep in step with ScreensaverAlienLife.cpp).
static Params Detail(int d, int world)
{
  Params p;
  static const float kHeight[] = {110.0f, 150.0f, 200.0f};
  static const int kCells[] = {3500, 7000, 14000};
  static const int kParticles[] = {2500, 4000, 7000};
  static const int kFounders[] = {70, 120, 220};
  p.worldHeight = kHeight[d];
  p.maxCells = kCells[d];
  p.maxParticles = kParticles[d];
  p.initialCreatures = kFounders[d];
  p.world = world;
  return p;
}

static const char* kWorldNames[] = {"grazers", "hunt", "soup"};

static bool Finite(const World& w)
{
  for (size_t i = 0; i < w.capacity(); i++)
    if (w.state()[i] != CS_FREE && (!std::isfinite(w.x()[i]) || !std::isfinite(w.y()[i])))
      return false;
  return true;
}

// A rough CPU picture of the world, glows added up: enough to judge a preview.
static void WritePreview(const World& w, const std::string& path, int W = 960)
{
  const int H = static_cast<int>(W * w.height() / w.width());
  std::vector<float> img(static_cast<size_t>(W) * H * 3, 0.0f);
  const float s = W / w.width();
  static const float kCol[NUM_COLOURS][3] = {{0.25f, 0.45f, 1.0f}, {0.70f, 0.35f, 1.0f}, {1.0f, 0.35f, 0.75f},
                                             {1.0f, 0.30f, 0.25f}, {1.0f, 0.62f, 0.25f}, {0.95f, 0.95f, 0.35f},
                                             {0.40f, 1.0f, 0.45f}};
  auto splat = [&](float x, float y, float r, float cr, float cg, float cb) {
    const int x0 = static_cast<int>((x - 2 * r) * s), x1 = static_cast<int>((x + 2 * r) * s) + 1;
    const int y0 = static_cast<int>((y - 2 * r) * s), y1 = static_cast<int>((y + 2 * r) * s) + 1;
    for (int py = std::max(y0, 0); py < std::min(y1, H); py++)
      for (int px = std::max(x0, 0); px < std::min(x1, W); px++)
      {
        const float dx = (px + 0.5f) / s - x, dy = (py + 0.5f) / s - y;
        const float g = std::exp(-(dx * dx + dy * dy) / (r * r));
        float* o = &img[(static_cast<size_t>(py) * W + px) * 3];
        o[0] += cr * g;
        o[1] += cg * g;
        o[2] += cb * g;
      }
  };
  for (int i = 0; i < w.numParticles(); i++)
    splat(w.px()[i], w.py()[i], 0.35f, 0.5f, 0.45f, 0.3f);
  for (size_t i = 0; i < w.capacity(); i++)
  {
    if (w.state()[i] == CS_FREE)
      continue;
    const float* c = kCol[w.colour()[i]];
    const float k = w.state()[i] == CS_DYING ? 0.25f : 0.55f + 0.45f * w.Vigour(static_cast<int>(i));
    splat(w.x()[i], w.y()[i], 0.6f, c[0] * k, c[1] * k, c[2] * k);
  }
  FILE* f = std::fopen(path.c_str(), "wb");
  if (!f)
    return;
  std::fprintf(f, "P6\n%d %d\n255\n", W, H);
  std::vector<unsigned char> row(static_cast<size_t>(W) * 3);
  for (int y = 0; y < H; y++)
  {
    for (int x = 0; x < W * 3; x++)
    {
      const float v = img[static_cast<size_t>(y) * W * 3 + x];
      row[x] = static_cast<unsigned char>(std::min(255.0f, 255.0f * (1.0f - std::exp(-1.6f * v))));
    }
    std::fwrite(row.data(), 1, row.size(), f);
  }
  std::fclose(f);
}

static void TestThreads()
{
  World a(1), b(1);
  const Params p = Detail(0, WORLD_HUNT);
  a.Reset(16.0f / 9.0f, p, 77);
  b.Reset(16.0f / 9.0f, p, 77);
  WorkerPool pool;
  pool.Start(4);
  for (int i = 0; i < 800; i++)
  {
    a.Step();
    b.Step(pool);
  }
  bool same = a.liveCells() == b.liveCells() && a.numParticles() == b.numParticles();
  for (size_t i = 0; same && i < a.capacity(); i++)
    same = a.state()[i] == b.state()[i] && (a.state()[i] == CS_FREE || (a.x()[i] == b.x()[i] && a.y()[i] == b.y()[i]));
  CHECK(same, "4 threads differ from 1 thread after 800 steps");
  std::printf("threads: 1 vs 4 identical after 800 steps: %s\n", same ? "yes" : "NO");
}

static void RunWorld(int detail, int world, int steps, const char* dir)
{
  World w(1);
  WorkerPool pool;
  pool.Start(4);
  w.Reset(16.0f / 9.0f, Detail(detail, world), 1234 + world * 7 + detail);
  const double budget = w.budget();
  double ms = 0;
  int minCreatures = 1 << 30;
  int hunterSteps = 0, hunterChecks = 0;
  for (int s = 1; s <= steps; s++)
  {
    const auto t0 = std::chrono::steady_clock::now();
    w.Step(pool);
    ms += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    if (s > 600)
      minCreatures = std::min(minCreatures, w.numCreatures());
    if (s % 600 == 0)
    {
      int hunters = 0;
      for (size_t i = 0; i < w.capacity(); i++)
        if (w.state()[i] == CS_ALIVE && w.type()[i] == CT_ATTACKER)
          hunters++;
      hunterChecks++;
      if (hunters > 0)
        hunterSteps++;
    }
    if (s % 1500 == 0)
      std::printf("  %-7s d%d step %5d: %4d creatures %5d cells %5d particles, pool %4.1f%%, births %ld deaths %ld, "
                  "gen %d, lineages %d\n",
                  kWorldNames[world], detail, s, w.numCreatures(), w.liveCells(), w.numParticles(),
                  100.0 * w.pool() / budget, w.births(), w.deaths(), w.maxGeneration(), w.lineages());
  }
  const double err = std::fabs(w.TotalEnergy() - budget) / budget;
  CHECK(err < 1e-4, "%s d%d: energy drifted by %.2e", kWorldNames[world], detail, err);
  CHECK(Finite(w), "%s d%d: non-finite positions", kWorldNames[world], detail);
  CHECK(minCreatures >= 4, "%s d%d: population fell to %d", kWorldNames[world], detail, minCreatures);
  CHECK(w.births() > 50, "%s d%d: only %ld births", kWorldNames[world], detail, w.births());
  CHECK(w.maxGeneration() >= 2, "%s d%d: no generations (%d)", kWorldNames[world], detail, w.maxGeneration());
  if (world == WORLD_HUNT)
    CHECK(hunterSteps * 2 >= hunterChecks, "hunt d%d: hunters gone for most of the run", detail);
  if (world != WORLD_GRAZERS || detail == 1)
    CHECK(w.lineages() >= 2, "%s d%d: only %d lineage(s)", kWorldNames[world], detail, w.lineages());
  std::printf("%-7s detail %d: %.3f ms per step (4 threads), energy error %.1e\n", kWorldNames[world], detail,
              ms / steps, err);
  if (dir)
    WritePreview(w, std::string(dir) + "/world_" + std::to_string(world) + "_d" + std::to_string(detail) + ".ppm");
}

int main(int argc, char** argv)
{
  const char* dir = argc > 1 ? argv[1] : nullptr;
  const int onlyDetail = argc > 2 ? std::atoi(argv[2]) : -1;
  const int steps = argc > 3 ? std::atoi(argv[3]) : 9000;
  TestThreads();
  for (int d = 0; d < 3; d++)
  {
    if (onlyDetail >= 0 && d != onlyDetail)
      continue;
    for (int world = 0; world < WORLD_COUNT; world++)
      RunWorld(d, world, steps, dir);
  }
  std::printf(g_failures ? "%d FAILURE(S)\n" : "all passed\n", g_failures);
  return g_failures ? 1 : 0;
}

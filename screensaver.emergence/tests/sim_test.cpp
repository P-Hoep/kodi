// Checks and benchmarks Emergence's world without Kodi.
//
//   c++ -O3 -std=c++17 -Isrc tests/sim_test.cpp -o /tmp/emergence_test -pthread && /tmp/emergence_test
//   /tmp/emergence_test DIR [detail] [steps] [seed]   # also writes DIR/scene_N.ppm previews
//
// - every scene at every detail level runs, stays finite and keeps its counts;
// - the parallel Particle Life step matches the serial one for pairs of
//   different groups and stays close overall;
// - the boids' field steering moves a flock towards a bright band;
// - the slime forms a network in Slime highways and Cell garden, and gathers
//   on the food: the trail under the particles is denser than elsewhere;
// - in Reef cells form and the boids keep out of them: under half the cells'
//   share of the screen, averaged over 300 steps;
// - ms per step for each scene.
#include "World.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>

using namespace emergence;

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

static bool Finite(const World& w)
{
  if (HasFlock(w.scene()))
    for (size_t i = 0; i < w.flock.size(); i++)
      if (!std::isfinite(w.flock.x()[i]) || !std::isfinite(w.flock.y()[i]))
        return false;
  if (HasLife(w.scene()))
    for (int g = 0; g < w.life.numGroups(); g++)
      for (size_t i = 0; i < w.life.group(g).size(); i++)
        if (!std::isfinite(w.life.group(g).x[i]) || !std::isfinite(w.life.group(g).vx[i]))
          return false;
  return true;
}

// Standard deviation / mean of the slime picture: ~0 for a flat haze, high for a network.
static double Contrast(const physarum::Simulation& sim)
{
  const size_t n = static_cast<size_t>(sim.width()) * sim.height() * sim.species();
  double sum = 0, sq = 0;
  for (size_t i = 0; i < n; i += sim.species())
  {
    sum += sim.display()[i];
    sq += double(sim.display()[i]) * sim.display()[i];
  }
  const double mean = sum / n;
  return mean > 0 ? std::sqrt(std::max(0.0, sq / n - mean * mean)) / mean : 0;
}

// A rough CPU picture of a scene, for tuning: the slime in teal, the
// particles in their group colours, the boids white.
static void WritePreview(const World& w, const std::string& path)
{
  const int W = 960, H = 540;
  std::vector<float> img(static_cast<size_t>(W) * H * 3, 0.0f);
  if (HasSlime(w.scene()))
  {
    const physarum::Simulation& s = w.slime;
    for (int y = 0; y < H; y++)
      for (int x = 0; x < W; x++)
      {
        const int tx = x * s.width() / W, ty = y * s.height() / H;
        const uint8_t* c = s.display() + (static_cast<size_t>(ty) * s.width() + tx) * s.species();
        const float d = c[0] / 255.0f, e = s.species() > 1 ? c[1] / 255.0f : 0.0f;
        float* p = &img[(static_cast<size_t>(y) * W + x) * 3];
        p[0] = 0.25f * d + 0.9f * e;
        p[1] = 0.75f * d + 0.4f * e;
        p[2] = 0.85f * d + 0.2f * e;
      }
  }
  static const float kCol[8][3] = {{1, 0.2f, 0.2f}, {0.2f, 1, 0.2f}, {1, 1, 0.2f}, {1, 1, 1},
                                   {0.2f, 1, 1},   {1, 0.2f, 1},   {1, 0.6f, 0}, {0.7f, 0.6f, 1}};
  auto dot = [&](float fx, float fy, const float* col, int r) {
    const int cx = static_cast<int>(fx), cy = static_cast<int>(fy);
    for (int y = cy - r; y <= cy + r; y++)
      for (int x = cx - r; x <= cx + r; x++)
        if (x >= 0 && y >= 0 && x < W && y < H)
        {
          float* p = &img[(static_cast<size_t>(y) * W + x) * 3];
          p[0] = col[0];
          p[1] = col[1];
          p[2] = col[2];
        }
  };
  if (HasLife(w.scene()))
    for (int g = 0; g < w.life.numGroups(); g++)
      for (size_t i = 0; i < w.life.group(g).size(); i++)
        dot(w.life.group(g).x[i] * W / w.life.width(), w.life.group(g).y[i] * H / w.life.height(), kCol[g], 1);
  if (HasFlock(w.scene()))
  {
    static const float white[3] = {1, 1, 1};
    for (size_t i = 0; i < w.flock.size(); i++)
      dot(w.flock.x()[i] * W / w.flock.width(), w.flock.y()[i] * H / w.flock.height(), white, 1);
  }
  FILE* f = std::fopen(path.c_str(), "wb");
  if (!f)
    return;
  std::fprintf(f, "P6\n%d %d\n255\n", W, H);
  std::vector<uint8_t> bytes(img.size());
  for (size_t i = 0; i < img.size(); i++)
    bytes[i] = static_cast<uint8_t>(std::min(255.0f, std::max(0.0f, img[i] * 255.0f)));
  std::fwrite(bytes.data(), 1, bytes.size(), f);
  std::fclose(f);
}

// Mean slime trail under the particles / mean trail everywhere.
static double FoodRatio(const World& w)
{
  const physarum::Simulation& s = w.slime;
  double all = 0, under = 0;
  size_t n = 0;
  for (int i = 0; i < s.width() * s.height(); i++)
    all += s.display()[i * s.species()];
  all /= s.width() * s.height();
  for (int g = 0; g < w.life.numGroups(); g++)
    for (size_t i = 0; i < w.life.group(g).size(); i++)
    {
      const int x = std::min(std::max(static_cast<int>(w.life.group(g).x[i] * s.width() / w.life.width()), 0), s.width() - 1);
      const int y = std::min(std::max(static_cast<int>(w.life.group(g).y[i] * s.height() / w.life.height()), 0), s.height() - 1);
      under += s.display()[(static_cast<size_t>(y) * s.width() + x) * s.species()];
      n++;
    }
  return n && all > 0 ? under / n / all : 0;
}

int main(int argc, char** argv)
{
  const std::string dir = argc > 1 ? argv[1] : "";
  const int previewDetail = argc > 2 ? std::atoi(argv[2]) : 0;
  const int previewSteps = argc > 3 ? std::atoi(argv[3]) : 900;
  const int seedBase = argc > 4 ? std::atoi(argv[4]) : 42;

  WorkerPool pool;
  pool.Start(4);

  // 1. Particle Life: the parallel step is the serial one for different
  //    groups (up to the compiler fusing multiply-adds differently, which a
  //    chaotic system grows: identical with -ffp-contract=off)
  {
    particlelife::Simulation a(7), b(7);
    for (auto* s : {&a, &b})
    {
      s->params.perColour = 300;
      s->Resize(1600, 900);
      s->SetNumGroups(3);
    }
    a.Randomize();
    b.Randomize();
    for (int i = 0; i < 3; i++)
      for (int j = 0; j < 3; j++)
        if (i == j)
        {
          a.setPower(i, j, 0);
          b.setPower(i, j, 0);
        }
    for (int t = 0; t < 10; t++)
    {
      a.Step();
      b.StepWith([&](size_t n, const std::function<void(size_t, size_t)>& fn) { pool.Run(n, fn); });
    }
    double diff = 0;
    for (int g = 0; g < 3; g++)
      for (size_t i = 0; i < a.group(g).size(); i++)
        diff = std::max(diff, double(std::fabs(a.group(g).x[i] - b.group(g).x[i])));
    CHECK(diff < 1e-2, "parallel Particle Life differs from serial by %g", diff);
  }

  // 2. field steering: a flock with a bright band at the top climbs to it
  {
    boids::Simulation sim(3);
    sim.params.count = 400;
    sim.params.predators = 0;
    sim.Resize(1778, 1000);
    sim.Restart([](std::mt19937&, uint8_t) { return 0xffffffffu; });
    std::vector<uint8_t> field(160 * 90);
    for (int y = 0; y < 90; y++)
      for (int x = 0; x < 160; x++)
        field[y * 160 + x] = static_cast<uint8_t>(std::max(0, 255 - y * 6));
    sim.field.data = field.data();
    sim.field.w = 160;
    sim.field.h = 90;
    sim.field.step = 1;
    sim.field.weight = 1.5f;
    double y0 = 0, y1 = 0;
    for (size_t i = 0; i < sim.size(); i++)
      y0 += sim.y()[i];
    for (int t = 0; t < 600; t++)
      sim.Step();
    for (size_t i = 0; i < sim.size(); i++)
      y1 += sim.y()[i];
    y0 /= sim.size();
    y1 /= sim.size();
    CHECK(y1 < y0 - 100, "field steering: mean y %.0f -> %.0f, expected it to rise", y0, y1);
  }

  // 3. every scene at every detail level
  for (int detail = 0; detail < 3; detail++)
    for (int scene = 0; scene < SCENE_COUNT; scene++)
    {
      World w;
      Settings set;
      set.detail = detail;
      w.Begin(scene, set, 100 + scene, 16.0f / 9.0f);
      const size_t particles = w.ParticleCount(), boidsN = HasFlock(scene) ? w.flock.size() : 0;
      const int steps = detail == 0 ? 200 : 60;
      const auto t0 = std::chrono::steady_clock::now();
      for (int t = 0; t < steps; t++)
        w.Step(pool);
      const double ms =
          std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count() / steps;
      CHECK(Finite(w), "scene %d detail %d went non-finite", scene, detail);
      CHECK(w.ParticleCount() == particles, "scene %d lost particles", scene);
      CHECK(!HasFlock(scene) || w.flock.size() == boidsN, "scene %d lost boids", scene);
      std::printf("detail %d  %-15s %6.2f ms/step  (%zu agents %dx%d, %zu boids, %zu particles)\n", detail,
                  SceneName(scene), ms, HasSlime(scene) ? w.slime.agents() : 0, HasSlime(scene) ? w.slime.width() : 0,
                  HasSlime(scene) ? w.slime.height() : 0, boidsN, particles);
    }

  // 4. the couplings do what they say, and previews
  for (int scene = 0; scene < SCENE_COUNT; scene++)
  {
    World w;
    Settings set;
    set.detail = previewDetail;
    w.Begin(scene, set, seedBase + scene, 16.0f / 9.0f);
    for (int t = 0; t < previewSteps; t++)
      w.Step(pool);
    if (HasSlime(scene))
    {
      const double c = Contrast(w.slime);
      std::printf("%-15s slime preset %d, contrast %.2f\n", SceneName(scene), w.slimePreset(), c);
      CHECK(c > 0.5, "%s: no network (contrast %.2f)", SceneName(scene), c);
    }
    if (scene == SCENE_GARDEN || scene == SCENE_ECOSYSTEM)
    {
      const double r = FoodRatio(w);
      std::printf("%-15s trail under the particles / mean: %.2f\n", SceneName(scene), r);
      CHECK(r > 1.5, "%s: the slime does not gather on the food (%.2f)", SceneName(scene), r);
    }
    if (HasLife(scene))
      std::printf("%-15s life rules: %s, %d colours\n", SceneName(scene),
                  w.lifePreset() < 0 ? "random" : particlelife::kPresets[w.lifePreset()].name, w.life.numGroups());
    if (scene == SCENE_REEF)
    {
      // Averaged over 300 more steps (one moment can catch a flock crossing
      // a cell): the share of boids over dense cells against the share of the
      // screen the cells cover. Without the coupling the two are equal.
      double share = 0, area = 0;
      int samples = 0;
      for (int t = 0; t < 300; t++)
      {
        w.Step(pool);
        if (t % 10)
          continue;
        const std::vector<uint8_t>& d = w.density();
        size_t dense = 0, over = 0;
        for (uint8_t v : d)
          dense += v > 120;
        for (size_t i = 0; i < w.flock.size(); i++)
        {
          const int x = std::min(static_cast<int>(w.flock.x()[i] / w.flock.width() * World::kDensityW), World::kDensityW - 1);
          const int y = std::min(static_cast<int>(w.flock.y()[i] / w.flock.height() * World::kDensityH), World::kDensityH - 1);
          over += d[static_cast<size_t>(y) * World::kDensityW + x] > 120;
        }
        share += double(over) / w.flock.size();
        area += double(dense) / d.size();
        samples++;
      }
      share /= samples;
      area /= samples;
      std::printf("Reef            dense cells cover %.1f%% of the screen, %.2f%% of the boids are over them\n",
                  area * 100, share * 100);
      CHECK(area > 0.002, "Reef: no cells formed (%.4f)", area);
      CHECK(share < 0.5 * area, "Reef: boids do not avoid the cells (%.4f vs %.4f)", share, area);
    }
    if (!dir.empty())
      WritePreview(w, dir + "/scene_" + std::to_string(scene) + ".ppm");
  }

  if (g_failures)
  {
    std::printf("%d failure(s)\n", g_failures);
    return 1;
  }
  std::printf("all passed\n");
  return 0;
}

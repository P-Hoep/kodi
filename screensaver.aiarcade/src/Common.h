// Small shared pieces: a serialisable RNG, screen features (the 16 x 15 grid
// the networks see and the 11 x 8 cell key the archive uses), the motif
// vocabulary, and the CPU throttle.
#pragma once

#include "Emu.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <thread>

namespace arcade
{

// xoshiro256** seeded by splitmix64; the state is four words, saved in neat.bin.
struct Rng
{
  uint64_t s[4];
  explicit Rng(uint64_t seed = 0x9E3779B97F4A7C15ULL) { Seed(seed); }
  void Seed(uint64_t seed)
  {
    for (int i = 0; i < 4; i++)
    {
      seed += 0x9E3779B97F4A7C15ULL;
      uint64_t z = seed;
      z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
      z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
      s[i] = z ^ (z >> 31);
    }
  }
  static uint64_t Rol(uint64_t x, int k) { return (x << k) | (x >> (64 - k)); }
  uint64_t Next()
  {
    const uint64_t r = Rol(s[1] * 5, 7) * 9, t = s[1] << 17;
    s[2] ^= s[0];
    s[3] ^= s[1];
    s[1] ^= s[2];
    s[0] ^= s[3];
    s[2] ^= t;
    s[3] = Rol(s[3], 45);
    return r;
  }
  double Uniform() { return static_cast<double>(Next() >> 11) * (1.0 / 9007199254740992.0); }
  double Uniform(double a, double b) { return a + (b - a) * Uniform(); }
  int Int(int n) { return n <= 1 ? 0 : static_cast<int>(Next() % static_cast<uint64_t>(n)); } // [0, n)
  int Range(int lo, int hi) { return lo + Int(hi - lo + 1); }                                   // [lo, hi]
  bool Chance(double p) { return Uniform() < p; }
  double Normal()
  {
    double u = Uniform();
    if (u < 1e-300)
      u = 1e-300;
    return std::sqrt(-2.0 * std::log(u)) * std::cos(6.283185307179586 * Uniform());
  }
};

// ---- motifs (spec 4.2) --------------------------------------------------------

constexpr int kMotifSets = 11;
constexpr uint8_t kMotifButtons[kMotifSets] = {
  BTN_RIGHT, BTN_LEFT, BTN_RIGHT | BTN_A, BTN_RIGHT | BTN_B, BTN_RIGHT | BTN_A | BTN_B,
  BTN_LEFT | BTN_A, BTN_A, BTN_B, BTN_UP, BTN_DOWN, 0,
};

inline uint8_t RandomMotifButtons(Rng& rng)
{
  // sets with Right weigh 3, the others 1: 4 x 3 + 7 = 19
  int r = rng.Int(19);
  for (int i = 0; i < kMotifSets; i++)
  {
    const int w = (kMotifButtons[i] & BTN_RIGHT) ? 3 : 1;
    if (r < w)
      return kMotifButtons[i];
    r -= w;
  }
  return 0;
}

inline int RandomMotifLength(Rng& rng) { return rng.Range(4, 30); }

// ---- screen features ------------------------------------------------------------

inline int Luma(uint32_t p) { return ((p & 0xFF) * 77 + ((p >> 8) & 0xFF) * 150 + ((p >> 16) & 0xFF) * 29) >> 8; }

// Mean grey of each cell of a gw x gh grid over the 256 x 240 frame, 0..255.
inline void GreyGrid(const uint32_t* rgba, int gw, int gh, float* out)
{
  for (int gy = 0; gy < gh; gy++)
  {
    const int y0 = gy * kScreenH / gh, y1 = (gy + 1) * kScreenH / gh;
    for (int gx = 0; gx < gw; gx++)
    {
      const int x0 = gx * kScreenW / gw, x1 = (gx + 1) * kScreenW / gw;
      int sum = 0;
      // every other pixel each way: plenty for a block mean, a quarter of the work
      int n = 0;
      for (int y = y0; y < y1; y += 2)
      {
        const uint32_t* row = rgba + y * kScreenW;
        for (int x = x0; x < x1; x += 2)
        {
          sum += Luma(row[x]);
          n++;
        }
      }
      out[gy * gw + gx] = n ? static_cast<float>(sum) / static_cast<float>(n) : 0.0f;
    }
  }
}

constexpr int kNetGridW = 16, kNetGridH = 15, kNetGrid = kNetGridW * kNetGridH; // 240 inputs
constexpr int kCellW = 11, kCellH = 8;

// The Go-Explore cell of a frame: 11 x 8 grey, 8 levels, hashed (spec 4.2).
inline uint64_t CellKey(const uint32_t* rgba)
{
  float g[kCellW * kCellH];
  GreyGrid(rgba, kCellW, kCellH, g);
  uint64_t h = 1469598103934665603ULL;
  for (float v : g)
  {
    const int q = std::min(7, static_cast<int>(v) >> 5);
    h = (h ^ static_cast<uint64_t>(q)) * 1099511628211ULL;
  }
  return h ? h : 1; // 0 means "none"
}

// ---- CPU cap -----------------------------------------------------------------------

// Call Tick() often from a working thread; it sleeps so that the thread is busy
// about `cap` of the wall time (spec 5: default 60% of one core).
class Throttle
{
public:
  using Clock = std::chrono::steady_clock;
  explicit Throttle(double cap = 0.6) { SetCap(cap); }
  void SetCap(double cap) { m_cap = std::min(1.0, std::max(0.05, cap)); }
  void Tick(const std::atomic<bool>& stop)
  {
    const auto now = Clock::now();
    const double busy = std::chrono::duration<double>(now - m_mark).count();
    if (busy < 0.02)
      return;
    if (m_cap < 0.999)
    {
      double rest = busy * (1.0 - m_cap) / m_cap;
      while (rest > 0 && !stop.load(std::memory_order_relaxed))
      {
        const double d = std::min(rest, 0.01);
        std::this_thread::sleep_for(std::chrono::duration<double>(d));
        rest -= d;
      }
    }
    m_mark = Clock::now();
  }
  void Reset() { m_mark = Clock::now(); }

private:
  double m_cap = 0.6;
  Clock::time_point m_mark = Clock::now();
};

} // namespace arcade

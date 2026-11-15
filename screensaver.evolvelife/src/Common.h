// Shared bits of the EvolveLife core: a small deterministic random number
// generator, hashing, and fast approximations used in the hot loops. No Kodi
// or GL here: the core builds on its own for tests/sim_test.cpp.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace evo
{

constexpr float kPi = 3.14159265f;
constexpr float kTwoPi = 6.28318531f;

inline uint32_t Hash(uint32_t x)
{
  x ^= x >> 16;
  x *= 0x7feb352dU;
  x ^= x >> 15;
  x *= 0x846ca68bU;
  x ^= x >> 16;
  return x;
}

inline uint64_t Mix64(uint64_t z)
{
  z += 0x9e3779b97f4a7c15ULL;
  z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
  z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
  return z ^ (z >> 31);
}

// xorshift64*: fast, deterministic, good enough for evolution.
struct Rng
{
  uint64_t s = 0x2545F4914F6CDD1DULL;

  Rng() = default;
  explicit Rng(uint64_t seed) { Seed(seed); }
  void Seed(uint64_t seed)
  {
    s = Mix64(seed);
    if (s == 0)
      s = 0x2545F4914F6CDD1DULL;
  }
  uint64_t Next()
  {
    s ^= s >> 12;
    s ^= s << 25;
    s ^= s >> 27;
    return s * 2685821657736338717ULL;
  }
  uint32_t U32() { return static_cast<uint32_t>(Next() >> 32); }
  // [0, 1)
  float Uni() { return static_cast<float>(Next() >> 40) * (1.0f / 16777216.0f); }
  float Range(float lo, float hi) { return lo + (hi - lo) * Uni(); }
  int Int(int n) { return n <= 1 ? 0 : static_cast<int>(U32() % static_cast<uint32_t>(n)); }
  int IntRange(int lo, int hi) { return lo + Int(hi - lo + 1); } // inclusive
  bool Chance(float p) { return Uni() < p; }
  // a normal deviate (Irwin-Hall of four uniforms, scaled: no log/sqrt and
  // the same on every libm)
  float Gauss()
  {
    const float u = Uni() + Uni() + Uni() + Uni() - 2.0f;
    return u * 1.7320508f;
  }
};

inline float Clamp(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

inline float WrapAngle(float a)
{
  while (a > kPi)
    a -= kTwoPi;
  while (a < -kPi)
    a += kTwoPi;
  return a;
}

// |error| < 1e-5 rad; branch-light and deterministic.
inline float FastAtan2(float y, float x)
{
  const float ax = std::fabs(x), ay = std::fabs(y);
  const float mx = std::max(ax, ay), mn = std::min(ax, ay);
  if (mx < 1e-20f)
    return 0.0f;
  const float a = mn / mx;
  const float s = a * a;
  float r = ((((0.0208351f * s - 0.0851330f) * s + 0.1801410f) * s - 0.3302995f) * s + 0.9998660f) * a;
  if (ay > ax)
    r = 1.57079637f - r;
  if (x < 0.0f)
    r = 3.14159265f - r;
  if (y < 0.0f)
    r = -r;
  return r;
}

// tanh to ~1e-3, saturating cleanly
inline float FastTanh(float x)
{
  if (x > 4.97f)
    return 1.0f;
  if (x < -4.97f)
    return -1.0f;
  const float x2 = x * x;
  const float a = x * (135135.0f + x2 * (17325.0f + x2 * (378.0f + x2)));
  const float b = 135135.0f + x2 * (62370.0f + x2 * (3150.0f + x2 * 28.0f));
  return Clamp(a / b, -1.0f, 1.0f);
}

// Smooth 1D value noise in [-1, 1].
inline float Noise1(float x, uint32_t seed)
{
  const float fl = std::floor(x);
  const int i = static_cast<int>(fl);
  const float f = x - fl;
  auto v = [seed](int k) { return static_cast<float>(Hash(static_cast<uint32_t>(k) * 0x9E3779B1u ^ seed) >> 8) / 8388608.0f - 1.0f; };
  const float t = f * f * (3.0f - 2.0f * f);
  return v(i) + (v(i + 1) - v(i)) * t;
}

} // namespace evo

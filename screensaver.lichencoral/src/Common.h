// Shared helpers for the growth simulations: a fast RNG, value noise and colours.
// Header-only and free of GL so the simulations can be tested without Kodi.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace lc
{

constexpr float kPi = 3.14159265358979f;

// xorshift128+ : fast enough for millions of random-walk steps per frame.
struct Rng
{
  uint64_t a = 0x9E3779B97F4A7C15ull, b = 0xBF58476D1CE4E5B9ull;

  explicit Rng(uint64_t seed = 1) { Seed(seed); }
  void Seed(uint64_t seed)
  {
    // splitmix64 to spread the seed over both words
    auto mix = [](uint64_t& z) {
      z += 0x9E3779B97F4A7C15ull;
      uint64_t x = z;
      x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ull;
      x = (x ^ (x >> 27)) * 0x94D049BB133111EBull;
      return x ^ (x >> 31);
    };
    a = mix(seed);
    b = mix(seed);
    if (!a && !b)
      a = 1;
  }
  uint64_t Next()
  {
    uint64_t x = a;
    const uint64_t y = b;
    a = y;
    x ^= x << 23;
    b = x ^ y ^ (x >> 17) ^ (y >> 26);
    return b + y;
  }
  uint32_t U32() { return static_cast<uint32_t>(Next() >> 32); }
  float Uni() { return (U32() >> 8) * (1.0f / 16777216.0f); } // [0, 1)
  float Range(float lo, float hi) { return lo + (hi - lo) * Uni(); }
  int Int(int lo, int hi) { return lo + static_cast<int>(U32() % static_cast<uint32_t>(hi - lo + 1)); }
  bool Chance(float p) { return Uni() < p; }
};

inline uint32_t Hash(int x, int y, uint32_t seed)
{
  uint32_t h = seed ^ (static_cast<uint32_t>(x) * 0x8DA6B343u) ^ (static_cast<uint32_t>(y) * 0xD8163841u);
  h ^= h >> 13;
  h *= 0x5bd1e995u;
  h ^= h >> 15;
  return h;
}

inline float Hash01(int x, int y, uint32_t seed)
{
  return (Hash(x, y, seed) >> 8) * (1.0f / 16777216.0f);
}

// Smooth value noise in [0, 1].
inline float ValueNoise(float x, float y, uint32_t seed)
{
  const float fx = std::floor(x), fy = std::floor(y);
  const int ix = static_cast<int>(fx), iy = static_cast<int>(fy);
  float tx = x - fx, ty = y - fy;
  tx = tx * tx * (3 - 2 * tx);
  ty = ty * ty * (3 - 2 * ty);
  const float a = Hash01(ix, iy, seed), b = Hash01(ix + 1, iy, seed);
  const float c = Hash01(ix, iy + 1, seed), d = Hash01(ix + 1, iy + 1, seed);
  return (a + (b - a) * tx) + ((c + (d - c) * tx) - (a + (b - a) * tx)) * ty;
}

// Fractal sum of value noise, normalised to about [0, 1].
inline float Fbm(float x, float y, uint32_t seed, int octaves, float gain = 0.5f)
{
  float sum = 0, amp = 1, norm = 0;
  for (int i = 0; i < octaves; i++)
  {
    sum += amp * ValueNoise(x, y, seed + 1013u * i);
    norm += amp;
    amp *= gain;
    x = x * 2.03f + 17.1f;
    y = y * 2.03f + 5.7f;
  }
  return sum / norm;
}

inline float Clamp01(float v) { return std::min(1.0f, std::max(0.0f, v)); }

inline float Smooth(float e0, float e1, float v)
{
  const float t = Clamp01((v - e0) / (e1 - e0));
  return t * t * (3 - 2 * t);
}

struct Col
{
  float r = 0, g = 0, b = 0;
};

inline Col Mix(const Col& a, const Col& b, float t)
{
  return {a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t};
}

inline Col Scale(const Col& a, float k) { return {a.r * k, a.g * k, a.b * k}; }

inline Col Hsv(float h, float s, float v)
{
  h = (h - std::floor(h)) * 6.0f;
  const int i = static_cast<int>(h) % 6;
  const float f = h - std::floor(h);
  const float p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f));
  switch (i)
  {
    case 0: return {v, t, p};
    case 1: return {q, v, p};
    case 2: return {p, v, t};
    case 3: return {p, q, v};
    case 4: return {t, p, v};
    default: return {v, p, q};
  }
}

inline uint8_t ToByte(float v)
{
  return static_cast<uint8_t>(Clamp01(v) * 255.0f + 0.5f);
}

// Write one RGBA texel; alpha carries the surface height for the relief shader.
inline void Put(uint8_t* p, const Col& c, float height)
{
  p[0] = ToByte(c.r);
  p[1] = ToByte(c.g);
  p[2] = ToByte(c.b);
  p[3] = ToByte(height);
}

} // namespace lc

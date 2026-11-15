// The world a generation is tested in: a goal, a terrain heightfield and the
// physical conditions, all drawn from one seed within fixed bounds, so every
// draw is solvable (Section 7 and 9.2 of EvolveLife.md).
#pragma once

#include "Common.h"

#include <vector>

namespace evo
{

enum Goal
{
  G_WALK,    // travel as far as possible in one direction
  G_BEACON,  // reach a beacon on the ground
  G_CLIMB,   // reach a beacon on top of a hill
  G_CHASM,   // cross a pit
  G_LEAP,    // jump as high as possible (all of the body off the ground)
  G_GLIDE,   // leave a cliff and travel as far as possible before landing
  G_HURDLES, // travel far over a field of bumps
  G_FLY,     // get off the ground and stay up as high as possible, in thick air
  GOAL_COUNT
};

enum Terrain
{
  T_FLAT,
  T_ROLLING,
  T_HILL,
  T_PIT,
  T_CLIFF,
  T_BUMPS,
  TERRAIN_COUNT
};

inline const char* GoalName(int g)
{
  static const char* k[GOAL_COUNT] = {"Travel far",         "Reach the beacon", "Climb to the beacon", "Cross the chasm",
                                      "Jump as high as possible", "Glide from the cliff", "Run the hurdles",
                                      "Fly as high as possible"};
  return k[g < 0 || g >= GOAL_COUNT ? 0 : g];
}

inline const char* TerrainName(int t)
{
  static const char* k[TERRAIN_COUNT] = {"flat plain", "rolling hills", "a hill", "a chasm", "a cliff", "bumps"};
  return k[t < 0 || t >= TERRAIN_COUNT ? 0 : t];
}

struct WorldSpec
{
  int goal = G_WALK;
  int terrain = T_FLAT;
  int dir = 1;            // +1 or -1: the direction of travel
  float gravity = 9.8f;   // m/s^2
  float friction = 0.8f;  // Coulomb coefficient
  float air = 1.0f;       // fin drag scale
  float wind = 0.0f;      // m/s^2 sideways push on fins
  float duration = 15.0f; // seconds of a trial
  float startX = 0.0f;
  bool hasTarget = false;
  float targetX = 0.0f, targetY = 0.0f;
  float pitL = 0.0f, pitR = 0.0f; // chasm, in x
  float cliffEdge = 0.0f, cliffTop = 0.0f;
  float x0 = -60.0f;              // the heightfield's first sample
  static constexpr float kDx = 0.25f;
  std::vector<float> h;           // ground height every kDx metres
  uint64_t seed = 0;
  int epoch = 0;

  float x1() const { return x0 + kDx * static_cast<float>(h.size() - 1); }

  // ground height and slope at x (flat beyond the ends)
  float Height(float x, float* slope = nullptr) const
  {
    const float f = (x - x0) * (1.0f / kDx);
    const int n = static_cast<int>(h.size());
    if (f <= 0.0f)
    {
      if (slope)
        *slope = 0.0f;
      return h[0];
    }
    const int i = static_cast<int>(f);
    if (i >= n - 1)
    {
      if (slope)
        *slope = 0.0f;
      return h[n - 1];
    }
    const float t = f - static_cast<float>(i);
    if (slope)
      *slope = (h[i + 1] - h[i]) * (1.0f / kDx);
    return h[i] + (h[i + 1] - h[i]) * t;
  }
};

// Draw the world for a goal (`goal` < 0: a random one) from a seed. `gentle`
// keeps the first epoch easy to watch.
inline WorldSpec MakeWorld(int goal, uint64_t seed, bool gentle, bool varyGravity = true)
{
  Rng r(seed);
  WorldSpec w;
  w.seed = seed;
  if (goal < 0 || goal >= GOAL_COUNT)
  {
    // the pool of goal templates; walking and beacons come up most
    static const int kPool[] = {G_WALK, G_WALK, G_BEACON, G_BEACON, G_CLIMB, G_CHASM, G_LEAP, G_GLIDE, G_HURDLES, G_FLY};
    goal = kPool[r.Int(static_cast<int>(sizeof(kPool) / sizeof(kPool[0])))];
  }
  w.goal = goal;
  w.dir = r.Chance(0.5f) ? 1 : -1;
  w.gravity = 9.8f * (gentle || !varyGravity ? 1.0f : r.Range(0.7f, 1.2f));
  w.friction = gentle ? 0.9f : r.Range(0.55f, 1.0f);
  w.air = 1.0f;
  w.wind = 0.0f;

  const int n = static_cast<int>(120.0f / WorldSpec::kDx) + 1; // -60 .. 60 m
  w.x0 = -60.0f;
  w.h.assign(static_cast<size_t>(n), 0.0f);
  const uint32_t ns = static_cast<uint32_t>(r.Next());
  auto X = [&](int i) { return w.x0 + WorldSpec::kDx * static_cast<float>(i); };
  auto addRolling = [&](float amp, float wave) {
    for (int i = 0; i < n; i++)
    {
      const float x = X(i);
      // flatten the start so a creature lands on level ground
      const float k = Clamp((std::fabs(x) - 1.5f) / 4.0f, 0.0f, 1.0f);
      w.h[i] += k * amp * (Noise1(x / wave, ns) + 0.5f * Noise1(x / (wave * 0.37f), ns ^ 0x55u));
    }
  };

  switch (goal)
  {
    case G_WALK:
      w.terrain = gentle ? T_FLAT : (r.Chance(0.5f) ? T_ROLLING : T_FLAT);
      w.duration = 15.0f;
      break;
    case G_HURDLES:
      w.terrain = T_BUMPS;
      w.duration = 16.0f;
      break;
    case G_BEACON:
      w.terrain = r.Chance(0.5f) ? T_ROLLING : T_FLAT;
      w.duration = 15.0f;
      w.hasTarget = true;
      break;
    case G_CLIMB:
      w.terrain = T_HILL;
      w.duration = 18.0f;
      w.hasTarget = true;
      break;
    case G_CHASM:
      w.terrain = T_PIT;
      w.duration = 14.0f;
      break;
    case G_LEAP:
      // no air: fins give no lift, so height only comes from the push off
      // the ground (with air, flapping fins won the jump contest by flying)
      w.terrain = T_FLAT;
      w.duration = 8.0f;
      w.dir = 1;
      w.air = 0.0f;
      break;
    case G_FLY:
      w.terrain = T_FLAT;
      w.duration = 12.0f;
      w.dir = 1;
      w.air = r.Range(2.2f, 3.2f);
      break;
    case G_GLIDE:
      w.terrain = T_CLIFF;
      w.duration = 12.0f;
      w.air = r.Range(1.2f, 2.0f);
      w.wind = r.Range(-0.4f, 1.2f);
      break;
    default:
      break;
  }

  switch (w.terrain)
  {
    case T_ROLLING:
      addRolling(r.Range(0.25f, gentle ? 0.4f : 0.8f), r.Range(6.0f, 16.0f));
      break;
    case T_BUMPS:
    {
      const float hgt = r.Range(0.12f, 0.35f), gap = r.Range(2.5f, 4.5f), wid = r.Range(0.4f, 0.9f);
      for (int i = 0; i < n; i++)
      {
        const float x = X(i);
        if (std::fabs(x) < 2.5f)
          continue;
        const float m = std::fmod(std::fabs(x), gap) - gap * 0.5f;
        const float t = Clamp(1.0f - std::fabs(m) / wid, 0.0f, 1.0f);
        w.h[i] += hgt * t * t * (3.0f - 2.0f * t);
      }
      break;
    }
    case T_HILL:
    {
      const float slope = std::tan(r.Range(6.0f, gentle ? 10.0f : 18.0f) * kPi / 180.0f);
      const float run = r.Range(9.0f, 16.0f);
      for (int i = 0; i < n; i++)
      {
        const float d = static_cast<float>(w.dir) * X(i) - 2.0f; // distance up the hill
        float y = 0.0f;
        if (d > 0.0f)
          y = slope * std::min(d, run) - (d > run ? slope * 0.3f * std::min(d - run, 4.0f) : 0.0f);
        w.h[i] = y;
      }
      addRolling(0.12f, 4.0f);
      w.targetX = static_cast<float>(w.dir) * (2.0f + run);
      break;
    }
    case T_PIT:
    {
      const float near = r.Range(3.0f, 4.5f);
      const float width = gentle ? 0.6f : r.Range(0.7f, 2.2f);
      w.pitL = static_cast<float>(w.dir) > 0 ? near : -near - width;
      w.pitR = w.pitL + width;
      for (int i = 0; i < n; i++)
      {
        const float x = X(i);
        if (x > w.pitL && x < w.pitR)
          w.h[i] = -3.0f;
      }
      break;
    }
    case T_CLIFF:
    {
      w.cliffTop = r.Range(5.0f, 9.0f);
      w.cliffEdge = static_cast<float>(w.dir) * r.Range(2.0f, 3.5f);
      for (int i = 0; i < n; i++)
      {
        const float d = static_cast<float>(w.dir) * (X(i) - w.cliffEdge);
        w.h[i] = d < 0.0f ? w.cliffTop : 0.0f;
      }
      // a gentle lip so the edge reads as a cliff, rolling land below
      for (int i = 0; i < n; i++)
      {
        const float d = static_cast<float>(w.dir) * (X(i) - w.cliffEdge);
        if (d > 0.5f)
          w.h[i] += 0.3f * Noise1(X(i) / 7.0f, ns);
      }
      break;
    }
    default:
      for (int i = 0; i < n; i++)
        w.h[i] += 0.02f * Noise1(X(i) * 2.0f, ns);
      break;
  }

  if (goal == G_BEACON)
  {
    const float d = gentle ? r.Range(6.0f, 9.0f) : r.Range(7.0f, 18.0f);
    w.targetX = static_cast<float>(w.dir) * d;
  }
  if (w.hasTarget)
    w.targetY = w.Height(w.targetX) + 0.6f;
  if (w.goal == G_GLIDE)
    w.startX = static_cast<float>(w.dir) * -0.5f;
  return w;
}

} // namespace evo

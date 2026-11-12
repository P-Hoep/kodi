// Particle Life simulation core - no Kodi / OpenGL dependencies.
// Port of the openFrameworks ofApp physics, with a uniform-grid neighbour
// search replacing the O(N^2) all-pairs loop (results are the same because
// the force only acts within `radius`).
//
// 1.1 generalises the original's four fixed colours to 1..MAX_GROUPS colours
// and adds the extras of the original JavaScript version: symmetric rules,
// "random exploration" (single-rule mutations) and pulses.
#pragma once

#include "Presets.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <random>
#include <vector>

namespace particlelife
{

// The first four keep the original update order: red, green, yellow, white.
enum Colour { RED = 0, GREEN = 1, YELLOW = 2, WHITE = 3 };
constexpr int MAX_GROUPS = 8;
constexpr int NUM_GROUPS = 4; // the original's colour count (and the presets')

struct Group
{
  std::vector<float> x, y, vx, vy;
  size_t size() const { return x.size(); }
};

struct Params
{
  int perColour = 1000;
  float viscosity = 0.5f; // 0..1
  float gravity = 0.0f;
  float wallRepel = 10.0f;
  bool bounded = false;
  float forceVariance = 0.8f;  // scales random power   (-100..100)
  float radiusVariance = 0.6f; // scales random radius  (10..200)
  bool symmetric = false;      // make power[a][b] == power[b][a] on each new rule set
  bool evolve = false;         // the C++ app's "evolve parameters": jitter every rule
  float evoChance = 1.0f;      // percent chance per step
  float evoAmount = 1.0f;      // percent of slider range
  bool explore = false;        // the JS app's "random exploration": mutate one rule
  int explorePeriod = 100;     // steps between mutations
};

class Simulation
{
public:
  explicit Simulation(uint32_t seed = std::random_device{}()) : m_rng(seed) {}

  Params params;

  void Resize(float width, float height)
  {
    m_w = width;
    m_h = height;
  }

  int numGroups() const { return m_numGroups; }
  void SetNumGroups(int n) { m_numGroups = std::min(std::max(n, 1), MAX_GROUPS); }

  // New random rule set, then respawn all particles (the original's
  // random() + restart(), i.e. the space-bar action).
  void Randomize()
  {
    for (int i = 0; i < m_numGroups; i++)
      for (int j = 0; j < m_numGroups; j++)
      {
        m_power[i][j] = RandomFloat(-100, 100) * params.forceVariance;
        m_radius[i][j] = RandomFloat(10, 200) * params.radiusVariance;
      }
    if (params.symmetric)
      Symmetrize();
    Restart();
  }

  // One of the original app's saved models. Presets are four-colour and carry
  // their own viscosity; the force / range scaling does not apply to them.
  void LoadPreset(int index)
  {
    const Preset& p = kPresets[std::min(std::max(index, 0), kNumPresets - 1)];
    m_numGroups = NUM_GROUPS;
    for (int i = 0; i < NUM_GROUPS; i++)
      for (int j = 0; j < NUM_GROUPS; j++)
      {
        m_power[i][j] = p.power[i][j];
        m_radius[i][j] = p.radius[i][j];
      }
    params.viscosity = p.viscosity;
    if (params.symmetric)
      Symmetrize();
    Restart();
  }

  // The JS app's "Symmetric Rules": average each pair so a attracts b exactly
  // as much as b attracts a. Symmetric rule sets settle into calmer, crystal-
  // like structures; asymmetric ones chase each other.
  void Symmetrize()
  {
    for (int i = 0; i < m_numGroups; i++)
      for (int j = 0; j < i; j++)
        m_power[i][j] = m_power[j][i] = 0.5f * (m_power[i][j] + m_power[j][i]);
  }

  void Restart()
  {
    const size_t n = static_cast<size_t>(std::max(0, params.perColour));
    for (int k = 0; k < MAX_GROUPS; k++)
    {
      Group& g = m_groups[k];
      const size_t count = k < m_numGroups ? n : 0;
      g.x.resize(count);
      g.y.resize(count);
      g.vx.assign(count, 0.0f);
      g.vy.assign(count, 0.0f);
      for (size_t i = 0; i < count; i++)
      {
        g.x[i] = std::floor(RandomFloat(0, m_w));
        g.y[i] = std::floor(RandomFloat(0, m_h));
      }
    }
    m_exploreTimer = params.explorePeriod;
  }

  // A burst at (x, y) for `steps` steps, fading out: positive pushes the
  // particles away, negative pulls them in (the JS app's click / shift-click).
  void Pulse(float x, float y, int steps)
  {
    m_pulseX = x;
    m_pulseY = y;
    m_pulse = steps;
  }

  // One simulation frame. Same order as the original update(): each group is
  // integrated once per source group (so viscosity / wall-repel / gravity are
  // applied once per colour per frame, exactly like the original).
  void Step()
  {
    if (params.evolve && RandomFloat(0, 1) < params.evoChance / 100.0f)
      Evolve();
    if (params.explore && --m_exploreTimer <= 0)
    {
      Explore();
      m_exploreTimer = std::max(1, params.explorePeriod);
    }
    if (m_pulse != 0)
      ApplyPulse();

    for (int a = 0; a < m_numGroups; a++)
      for (int b = 0; b < m_numGroups; b++)
        Interaction(m_groups[a], m_groups[b], m_power[a][b], m_radius[a][b]);
  }

  const Group& group(int i) const { return m_groups[i]; }
  float power(int a, int b) const { return m_power[a][b]; }
  float radius(int a, int b) const { return m_radius[a][b]; }
  void setPower(int a, int b, float v) { m_power[a][b] = v; }
  void setRadius(int a, int b, float v) { m_radius[a][b] = v; }

  // Public so it can be tested against a brute-force reference.
  void Interaction(Group& g1, const Group& g2, float G, float radius)
  {
    const float g = G / -100.0f; // attraction coefficient (positive G attracts)
    const float r2 = radius * radius;
    const float wr = params.wallRepel;
    const float visc = 1.0f - params.viscosity;

    BuildGrid(g2, std::max(radius, 1.0f));

    for (size_t i = 0; i < g1.size(); i++)
    {
      float fx = 0.0f, fy = 0.0f;
      const float px = g1.x[i], py = g1.y[i];
      const int cx = CellX(px), cy = CellY(py);

      for (int oy = std::max(cy - 1, 0); oy <= std::min(cy + 1, m_cellsY - 1); oy++)
      {
        for (int ox = std::max(cx - 1, 0); ox <= std::min(cx + 1, m_cellsX - 1); ox++)
        {
          const int c = oy * m_cellsX + ox;
          for (int k = m_cellStart[c]; k < m_cellStart[c + 1]; k++)
          {
            const int j = m_sorted[k];
            const float dx = px - g2.x[j];
            const float dy = py - g2.y[j];
            const float d2 = dx * dx + dy * dy;
            if (d2 > 0.0f && d2 < r2)
            {
              const float inv = 1.0f / std::sqrt(d2);
              fx += dx * inv;
              fy += dy * inv;
            }
          }
        }
      }

      float& vx = g1.vx[i];
      float& vy = g1.vy[i];

      if (wr > 0.0f)
      {
        vx += g1.x[i] < wr ? (wr - g1.x[i]) * 0.1f : 0.0f;
        vy += g1.y[i] < wr ? (wr - g1.y[i]) * 0.1f : 0.0f;
        vx += g1.x[i] > m_w - wr ? (m_w - wr - g1.x[i]) * 0.1f : 0.0f;
        vy += g1.y[i] > m_h - wr ? (m_h - wr - g1.y[i]) * 0.1f : 0.0f;
      }

      vx = (vx + fx * g) * visc;
      vy = (vy + fy * g) * visc + params.gravity;

      g1.x[i] += vx;
      g1.y[i] += vy;
    }

    if (params.bounded)
    {
      for (size_t i = 0; i < g1.size(); i++)
      {
        g1.x[i] = std::min(std::max(g1.x[i], 0.0f), m_w);
        g1.y[i] = std::min(std::max(g1.y[i], 0.0f), m_h);
      }
    }
  }

  float RandomFloat(float a, float b)
  {
    return std::uniform_real_distribution<float>(a, b)(m_rng);
  }
  int RandomInt(int lo, int hi) // inclusive
  {
    return std::uniform_int_distribution<int>(lo, hi)(m_rng);
  }
  std::mt19937& rng() { return m_rng; }

private:
  void Evolve()
  {
    const float amt = params.evoAmount / 100.0f;
    for (int i = 0; i < m_numGroups; i++)
      for (int j = 0; j < m_numGroups; j++)
      {
        float& p = m_power[i][j];
        float& r = m_radius[i][j];
        p = std::min(100.0f, std::max(-100.0f, p + RandomFloat(-1, 1) * 200.0f * amt));
        r = std::min(200.0f, std::max(10.0f, r + RandomFloat(-1, 1) * 490.0f * amt));
      }
  }

  // The JS version's exploreParameters(): 80% of the time flip one rule to a
  // new strength of the opposite sign, otherwise re-roll one radius.
  void Explore()
  {
    const int a = RandomInt(0, m_numGroups - 1);
    const int b = RandomInt(0, m_numGroups - 1);
    if (RandomFloat(0, 1) >= 0.2f)
    {
      float s = RandomFloat(0, 100) * params.forceVariance;
      if (m_power[a][b] > 0)
        s = -s;
      m_power[a][b] = s;
      if (params.symmetric)
        m_power[b][a] = s;
    }
    else
    {
      m_radius[a][b] = RandomFloat(10, 200) * params.radiusVariance;
    }
  }

  // Impulse ~ 100 * pulse / distance, as in the JS app, clamped so particles
  // right at the centre do not get flung across the screen.
  void ApplyPulse()
  {
    const float strength = 100.0f * static_cast<float>(m_pulse);
    for (int k = 0; k < m_numGroups; k++)
    {
      Group& g = m_groups[k];
      for (size_t i = 0; i < g.size(); i++)
      {
        const float dx = g.x[i] - m_pulseX;
        const float dy = g.y[i] - m_pulseY;
        const float d2 = dx * dx + dy * dy;
        if (d2 < 1.0f)
          continue;
        const float d = std::sqrt(d2);
        float imp = strength / d2; // per unit of (dx, dy)
        const float mag = std::fabs(imp) * d;
        const float maxMag = m_pulse < 0 ? 0.5f * d : 30.0f; // implosions never overshoot
        if (mag > maxMag)
          imp *= maxMag / mag;
        g.vx[i] += imp * dx;
        g.vy[i] += imp * dy;
      }
    }
    m_pulse += m_pulse > 0 ? -1 : 1;
  }

  // Counting-sort the particles of `g` into square cells of size `cell`.
  void BuildGrid(const Group& g, float cell)
  {
    m_cell = cell;
    m_cellsX = static_cast<int>(m_w / cell) + 1;
    m_cellsY = static_cast<int>(m_h / cell) + 1;
    const size_t numCells = static_cast<size_t>(m_cellsX) * m_cellsY;

    m_cellStart.assign(numCells + 1, 0);
    m_cellOf.resize(g.size());
    for (size_t j = 0; j < g.size(); j++)
    {
      const int c = CellY(g.y[j]) * m_cellsX + CellX(g.x[j]);
      m_cellOf[j] = c;
      m_cellStart[c + 1]++;
    }
    for (size_t c = 0; c < numCells; c++)
      m_cellStart[c + 1] += m_cellStart[c];

    m_fill.assign(m_cellStart.begin(), m_cellStart.end() - 1);
    m_sorted.resize(g.size());
    for (size_t j = 0; j < g.size(); j++)
      m_sorted[m_fill[m_cellOf[j]]++] = static_cast<int>(j);
  }

  // Clamping keeps out-of-bounds particles usable: clamping is 1-Lipschitz in
  // cell units, so two points closer than one cell are never >1 cell apart.
  int CellX(float x) const
  {
    return std::min(std::max(static_cast<int>(std::floor(x / m_cell)), 0), m_cellsX - 1);
  }
  int CellY(float y) const
  {
    return std::min(std::max(static_cast<int>(std::floor(y / m_cell)), 0), m_cellsY - 1);
  }

  std::mt19937 m_rng;
  int m_numGroups = NUM_GROUPS;
  Group m_groups[MAX_GROUPS];
  float m_power[MAX_GROUPS][MAX_GROUPS] = {};
  float m_radius[MAX_GROUPS][MAX_GROUPS] = {};
  float m_w = 1600, m_h = 900;

  int m_exploreTimer = 100;
  int m_pulse = 0;
  float m_pulseX = 0, m_pulseY = 0;

  float m_cell = 100;
  int m_cellsX = 1, m_cellsY = 1;
  std::vector<int> m_cellStart, m_cellOf, m_fill, m_sorted;
};

} // namespace particlelife

// Particle Life simulation core - no Kodi / OpenGL dependencies.
// Port of the openFrameworks ofApp physics, with a uniform-grid neighbour
// search replacing the O(N^2) all-pairs loop (results are the same because
// the force only acts within `radius`).
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <random>
#include <vector>

namespace particlelife
{

// Group order matches the original update loop: red, green, yellow, white.
enum Colour { RED = 0, GREEN = 1, YELLOW = 2, WHITE = 3, NUM_GROUPS = 4 };

struct Group
{
  std::vector<float> x, y, vx, vy;
  float r = 1, g = 1, b = 1;
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
  bool evolve = false;
  float evoChance = 1.0f; // percent chance per step
  float evoAmount = 1.0f; // percent of slider range
};

class Simulation
{
public:
  explicit Simulation(uint32_t seed = std::random_device{}()) : m_rng(seed)
  {
    m_groups[RED].r = 1;    m_groups[RED].g = 0;    m_groups[RED].b = 0;
    m_groups[GREEN].r = 0;  m_groups[GREEN].g = 1;  m_groups[GREEN].b = 0;
    m_groups[YELLOW].r = 1; m_groups[YELLOW].g = 1; m_groups[YELLOW].b = 0;
    m_groups[WHITE].r = 1;  m_groups[WHITE].g = 1;  m_groups[WHITE].b = 1;
  }

  Params params;

  void Resize(float width, float height)
  {
    m_w = width;
    m_h = height;
  }

  // New random rule set, then respawn all particles (the original's
  // random() + restart(), i.e. the space-bar action).
  void Randomize()
  {
    for (int i = 0; i < NUM_GROUPS; i++)
      for (int j = 0; j < NUM_GROUPS; j++)
      {
        m_power[i][j] = RandomFloat(-100, 100) * params.forceVariance;
        m_radius[i][j] = RandomFloat(10, 200) * params.radiusVariance;
      }
    Restart();
  }

  void Restart()
  {
    for (auto& g : m_groups)
    {
      const size_t n = static_cast<size_t>(std::max(0, params.perColour));
      g.x.resize(n);
      g.y.resize(n);
      g.vx.assign(n, 0.0f);
      g.vy.assign(n, 0.0f);
      for (size_t i = 0; i < n; i++)
      {
        g.x[i] = std::floor(RandomFloat(0, m_w));
        g.y[i] = std::floor(RandomFloat(0, m_h));
      }
    }
  }

  // One simulation frame. Same order as the original update(): each group is
  // integrated once per source group (so viscosity / wall-repel / gravity are
  // applied four times per frame, exactly like the original).
  void Step()
  {
    if (params.evolve && RandomFloat(0, 1) < params.evoChance / 100.0f)
      Evolve();

    for (int a = 0; a < NUM_GROUPS; a++)
      for (int b = 0; b < NUM_GROUPS; b++)
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

private:
  float RandomFloat(float a, float b)
  {
    return std::uniform_real_distribution<float>(a, b)(m_rng);
  }

  void Evolve()
  {
    const float amt = params.evoAmount / 100.0f;
    for (auto& row : m_power)
      for (float& p : row)
        p = std::min(100.0f, std::max(-100.0f, p + RandomFloat(-1, 1) * 200.0f * amt));
    for (auto& row : m_radius)
      for (float& r : row)
        r = std::min(200.0f, std::max(10.0f, r + RandomFloat(-1, 1) * 490.0f * amt));
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
  Group m_groups[NUM_GROUPS];
  float m_power[NUM_GROUPS][NUM_GROUPS] = {};
  float m_radius[NUM_GROUPS][NUM_GROUPS] = {};
  float m_w = 1600, m_h = 900;

  float m_cell = 100;
  int m_cellsX = 1, m_cellsY = 1;
  std::vector<int> m_cellStart, m_cellOf, m_fill, m_sorted;
};

} // namespace particlelife

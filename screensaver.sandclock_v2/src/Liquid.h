// Sand Clock v2: the liquid. A FLIP fluid in which the digits melt; no Kodi /
// OpenGL.
//
// The fluid is particles on a MAC grid, the FLIP method as in Matthias
// Muller's "Ten Minute Physics" water simulator: every step the particles
// fall and are pushed apart, their velocities are splatted onto the grid, the
// grid is made divergence-free by Gauss-Seidel pressure iterations (with the
// particle density correcting the volume that drifts), and the change is
// handed back to the particles, blended with plain PIC for viscosity.
//
// The digits are frozen particles. The cells they occupy are solid walls to
// the fluid, so melt runs over and around what is left of a digit. When a
// digit changes, its particles thaw from the bottom up (or all at once, or
// from the top) and drip and slump into the pool; freshly melted fluid is
// sticky and clings to the solid before it lets go, which gives the hanging,
// stretching drips of a melting clock. The new digit condenses in place once
// the old one has run out of the way. A drain in the floor keeps the pool at
// its depth and hands the drained particles back for the next digits, so the
// particle count never grows.
//
// Cost is kept down the same ways as the sand: structure-of-arrays particles
// counting-sorted into cell order every step (so every grid transfer and the
// neighbour search walk memory in order), the pressure solve walking a list
// of the fluid cells with its constants worked out once, the grid transfers
// and the separation pass split over threads with per-thread accumulators,
// and a picture splatted per band of rows in parallel from a weight table,
// with the standing digits kept in a picture of their own.
#pragma once

#include "ClockFace.h"
#include "Colours.h"
#include "WorkerPool.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace sandclock2
{

// Four floats (a texel's colour and weight) in one SIMD register: NEON on
// ARM, SSE on x86, so a particle adds itself to a texel in one instruction.
typedef float V4 __attribute__((vector_size(16)));

enum Melt { MELT_DRIP = 0, MELT_SLUMP, MELT_FROM_TOP };

struct LiquidParams
{
  float gravity = 110.0f;   // cells per second^2
  float dt = 1.0f / 60.0f;
  int substeps = 1;
  int pressureIters = 24;
  int separationIters = 2;
  float overRelax = 1.9f;
  float flip = 0.9f;        // FLIP share of the velocity update (1 - PIC): lower is thicker
  float smooth = 0.0f;      // extra viscosity: grid velocity smoothing per substep (0..0.4)
  float stick = 0.55f;      // fresh melt touching the solid keeps this share of its speed
  float pool = 0.2f;        // depth of the pool, fraction of the height
  int melt = MELT_DRIP;
  bool wholeClock = false;  // the whole clock melts when the minute changes
  bool drips = true;        // the digits drip now and then while they stand
  float slosh = 0.0f;       // how far the pool rocks to and fro (0 = still)
};

class LiquidWorld
{
  using Clock = std::chrono::steady_clock;

public:
  LiquidParams params;
  ClockStyle style;
  ColourPicker colours;

  // picture resolution: texels per cell
  int texScale = 3;

  // time spent per stage (ms, summed) when profile is set: integrate, sort,
  // separate, collide, to grid, density + viscosity, pressure, to particles, splat
  bool profile = false;
  double prof[9] = {};

  void Configure(int nx, int ny, uint32_t seed)
  {
    m_nx = std::max(nx, 8);
    m_ny = std::max(ny, 8);
    m_seed = seed;
    m_rng = seed * 2654435761u + 1;
    const size_t n = static_cast<size_t>(m_nx) * m_ny;
    for (auto* a : {&m_u, &m_v, &m_du, &m_dv, &m_prevU, &m_prevV, &m_s, &m_density})
      a->assign(n, 0.0f);
    m_type.assign(n, AIR);
    m_solid.assign(n, 0);
    m_cellStart.assign(n + 1, 0);
    m_cellCount.assign(n, 0);
    m_r = 0.3f;
    m_rest = 0.0f;
    m_step = 0;
    m_text.clear();
    m_slots.clear();
    m_frozen.clear();
    m_unsplat.clear();
    m_frozenAcc.clear();
    m_kernel.clear();
    m_glyphs.Set(style);
    colours.Seed(seed);
    m_bases = colours.NumBases();
    for (int b = 0; b < m_bases && b < 64; b++)
      m_baseRGB[b] = colours.Base(b);
    ClearParticles();
    // the pool to start with: a still layer, in a few colours
    const float depth = params.pool * m_ny;
    const float sp = 2.0f * m_r;
    for (float y = m_ny - 1 - 0.5f * sp; y > m_ny - 1 - depth; y -= sp)
      for (float x = 1 + 0.5f * sp; x < m_nx - 1; x += sp)
      {
        const float jitter = (Hash(static_cast<uint32_t>(x * 64), static_cast<uint32_t>(y * 64), seed) & 255) / 2550.0f;
        const int band = static_cast<int>((m_ny - 1 - y) / std::max(1.0f, depth / 3.0f));
        AddParticle(x + jitter, y, 0, 0, static_cast<uint8_t>((band * 3 + 1) % m_bases), 1000);
      }
    m_target = m_count;
    m_tw = m_nx * texScale;
    m_th = m_ny * texScale;
    m_picture.assign(static_cast<size_t>(m_tw) * m_th * 4, 0);
    m_acc.assign(static_cast<size_t>(m_tw) * m_th, V4{0, 0, 0, 0});
    m_rest = 0.0f;
  }

  int width() const { return m_nx; }
  int height() const { return m_ny; }
  int texWidth() const { return m_tw; }
  int texHeight() const { return m_th; }
  size_t particles() const { return m_count; }
  size_t frozen() const { return m_frozen.size(); }
  long step() const { return m_step; }
  const std::string& text() const { return m_text; }
  // RGBA8, m_tw x m_th: density in A, the colour premultiplied by it in RGB
  const uint8_t* picture() const { return m_picture.data(); }

  void SetText(const std::string& text, double seconds)
  {
    if (text == m_text)
      return;
    const std::vector<Box> boxes = Layout(style, text, m_nx, m_ny);
    const bool first = m_text.empty();
    bool all = first || text.size() != m_text.size();
    auto minutes = [this](const std::string& t) {
      return style.seconds && t.size() > 3 ? t.substr(0, t.size() - 3) : t;
    };
    if (!all && params.wholeClock && minutes(text) != minutes(m_text))
      all = true;
    if (!all)
      for (size_t i = 0; i < boxes.size() && i < m_slots.size(); i++)
        if (std::fabs(boxes[i].x - m_slots[i].box.x) > 0.01f)
          all = true;
    if (all)
    {
      for (size_t i = 0; i < m_slots.size(); i++)
        MeltSlot(static_cast<int>(i));
      m_slots.assign(text.size(), Slot());
    }
    for (size_t i = 0; i < text.size(); i++)
    {
      Slot& s = m_slots[i];
      if (!all && s.ch == text[i])
        continue;
      if (!all)
        MeltSlot(static_cast<int>(i));
      s.ch = text[i];
      s.box = boxes[i];
      FormSlot(static_cast<int>(i), first, seconds);
    }
    m_text = text;
  }

  void Step(WorkerPool& pool)
  {
    m_step++;
    m_pool = &pool;
    Thaw();
    Condense();
    Drain();
    UpdateSolid();
    const float sdt = params.dt / std::max(1, params.substeps);
    // the pool rocks: gravity tilts a little, slowly
    const float tilt = params.slosh * std::sin(static_cast<float>(m_step) * 0.012f) *
                       std::sin(static_cast<float>(m_step) * 0.0031f + 1.0f);
    m_gx = params.gravity * tilt;
    m_gy = params.gravity * std::sqrt(std::max(0.0f, 1.0f - tilt * tilt));
    auto t = Clock::now();
    auto lap = [&](int k) {
      if (!profile)
        return;
      const auto n = Clock::now();
      prof[k] += std::chrono::duration<double, std::milli>(n - t).count();
      t = n;
    };
    for (int sub = 0; sub < params.substeps; sub++)
    {
      Integrate(sdt);
      lap(0);
      Sort();
      lap(1);
      for (int k = 0; k < params.separationIters; k++)
        Separate();
      lap(2);
      Collide();
      lap(3);
      ToGrid();
      lap(4);
      Density();
      Viscosity();
      lap(5);
      Pressure(sdt);
      lap(6);
      ToParticles();
      lap(7);
    }
    Splat();
    lap(8);
    m_pool = nullptr;
  }

  void Step()
  {
    WorkerPool none;
    Step(none);
  }

  // volume checks for tests
  float MeanDensityRatio() const
  {
    double sum = 0;
    int n = 0;
    for (size_t c = 0; c < m_density.size(); c++)
      if (m_type[c] == FLUID && m_density[c] > 0)
      {
        sum += m_density[c];
        n++;
      }
    return n && m_rest > 0 ? static_cast<float>(sum / n / m_rest) : 0.0f;
  }
  float MaxSpeed() const
  {
    float m = 0;
    for (size_t i = 0; i < m_count; i++)
      m = std::max(m, m_vx[i] * m_vx[i] + m_vy[i] * m_vy[i]);
    return std::sqrt(m);
  }
  // fluid particles in the cells of the current digits (tests: should stay small)
  size_t ParticlesInSolid() const
  {
    size_t n = 0;
    for (size_t i = 0; i < m_count; i++)
    {
      const int ci = Clampi(static_cast<int>(m_px[i]), 0, m_nx - 1);
      const int cj = Clampi(static_cast<int>(m_py[i]), 0, m_ny - 1);
      n += m_solid[static_cast<size_t>(cj) * m_nx + ci] != 0;
    }
    return n;
  }
  float LowestParticleY() const
  {
    float m = 0;
    for (size_t i = 0; i < m_count; i++)
      m = std::max(m, m_py[i]);
    return m;
  }
  bool drainOn = true;

private:
  enum : uint8_t { FLUID = 0, AIR = 1, SOLID = 2 };

  struct Frozen
  {
    float x, y;
    int thaw;       // step at which it melts (INT_MAX = standing)
    int appear;     // step at which it has fully condensed
    uint8_t base;
    uint8_t slot;
    uint8_t cached = 0; // drawn into the standing-digit picture
  };
  struct Slot
  {
    char ch = 0;
    Box box{0, 0, 0, 0};
  };

  static int Clampi(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }
  float Rand()
  {
    m_rng ^= m_rng << 13;
    m_rng ^= m_rng >> 17;
    m_rng ^= m_rng << 5;
    return (m_rng & 0xFFFFFF) / 16777216.0f;
  }

  // ---- particles

  void ClearParticles()
  {
    m_count = 0;
    for (auto* a : {&m_px, &m_py, &m_vx, &m_vy, &m_ox, &m_oy})
      a->clear();
    m_col.clear();
    m_age.clear();
  }

  void AddParticle(float x, float y, float vx, float vy, uint8_t base, int age)
  {
    m_px.push_back(x);
    m_py.push_back(y);
    m_vx.push_back(vx);
    m_vy.push_back(vy);
    m_ox.push_back(x);
    m_oy.push_back(y);
    m_col.push_back(base);
    m_age.push_back(static_cast<uint16_t>(std::min(age, 60000)));
    m_count++;
  }

  void RemoveParticle(size_t i)
  {
    const size_t last = m_count - 1;
    m_px[i] = m_px[last];
    m_py[i] = m_py[last];
    m_vx[i] = m_vx[last];
    m_vy[i] = m_vy[last];
    m_ox[i] = m_ox[last];
    m_oy[i] = m_oy[last];
    m_col[i] = m_col[last];
    m_age[i] = m_age[last];
    for (auto* a : {&m_px, &m_py, &m_vx, &m_vy, &m_ox, &m_oy})
      a->pop_back();
    m_col.pop_back();
    m_age.pop_back();
    m_count--;
  }

  // ---- the clock

  void MeltSlot(int i)
  {
    const Slot& s = m_slots[i];
    const float span = std::max(1.0f, s.box.h);
    const bool fast = style.seconds && i + 3 >= static_cast<int>(m_slots.size());
    const int D = fast ? 18 : 90; // steps over which a digit lets go
    for (Frozen& f : m_frozen)
    {
      if (f.slot != i || f.thaw != INT32_MAX)
        continue;
      const float rel = (f.y - s.box.y) / span; // 0 top .. 1 bottom
      const float noise = (Hash(static_cast<uint32_t>(f.x * 97), static_cast<uint32_t>(f.y * 89), m_seed) & 1023) / 1023.0f;
      float d;
      if (params.melt == MELT_SLUMP)
        d = noise * 0.15f;
      else if (params.melt == MELT_FROM_TOP)
        d = rel * 0.7f + noise * 0.3f;
      else
        d = (1.0f - rel) * 0.7f + noise * 0.3f;
      f.thaw = static_cast<int>(m_step) + static_cast<int>(d * D);
      f.slot = 255; // no longer part of a standing digit
    }
    m_slots[i].ch = 0;
  }

  void FormSlot(int i, bool instant, double seconds)
  {
    Slot& s = m_slots[i];
    const int base = colours.Next(i, seconds) % m_bases;
    // particles on a half-cell lattice inside the glyph
    Box fine = s.box;
    fine.x *= 2;
    fine.y *= 2;
    fine.w *= 2;
    fine.h *= 2;
    const std::vector<Cell> cells = Rasterise(m_glyphs.Get(s.ch), fine, m_nx * 2, m_ny * 2);
    const bool fast = style.seconds && i + 3 >= static_cast<int>(m_slots.size());
    const int wait = instant ? 0 : (fast ? 26 : 110); // let the old digit run out first
    const int now = static_cast<int>(m_step);
    for (const Cell& c : cells)
    {
      Frozen f;
      f.x = (c.x + 0.5f) * 0.5f;
      f.y = (c.y + 0.5f) * 0.5f;
      f.thaw = INT32_MAX;
      const int stagger = static_cast<int>(Hash(c.x, c.y, m_seed) % 12);
      f.appear = instant ? -1 : now + wait + stagger;
      f.base = static_cast<uint8_t>(base);
      f.slot = static_cast<uint8_t>(i);
      m_frozen.push_back(f);
    }
  }

  // Frozen particles whose time has come become fluid; the standing digits
  // also drip a little now and then.
  void Thaw()
  {
    const int now = static_cast<int>(m_step);
    if (params.drips && !m_slots.empty() && now % 45 == 0)
    {
      // a drip: a few particles at the bottom edge of a random digit let go
      const int si = static_cast<int>(Rand() * m_slots.size()) % static_cast<int>(m_slots.size());
      const Box& b = m_slots[si].box;
      const float x = b.x + b.w * (0.2f + 0.6f * Rand());
      int taken = 0;
      for (Frozen& f : m_frozen)
        if (f.slot == si && f.thaw == INT32_MAX && f.appear < now && std::fabs(f.x - x) < 0.8f &&
            f.y > b.y + b.h * 0.3f && IsBottomEdge(f) && taken < 3)
        {
          f.thaw = now;
          taken++;
        }
    }
    for (size_t k = 0; k < m_frozen.size();)
    {
      Frozen& f = m_frozen[k];
      if (f.thaw > now)
      {
        k++;
        continue;
      }
      if (f.appear < now) // a digit that never finished condensing just vanishes
        AddParticle(f.x, f.y, 0, 0.5f, f.base, 0);
      if (f.cached)
        m_unsplat.push_back(f);
      f = m_frozen.back();
      m_frozen.pop_back();
    }
  }

  bool IsBottomEdge(const Frozen& f) const
  {
    const int ci = Clampi(static_cast<int>(f.x), 0, m_nx - 1);
    const int cj = Clampi(static_cast<int>(f.y) + 1, 0, m_ny - 1);
    return !m_solid[static_cast<size_t>(cj) * m_nx + ci];
  }

  // New digits: a frozen particle appears once no fluid is in its cell, so
  // the new digit grows into the space the old one has drained out of.
  void Condense()
  {
    const int now = static_cast<int>(m_step);
    bool any = false;
    for (const Frozen& f : m_frozen)
      if (f.appear == now + 1 || f.appear == now)
      {
        any = true;
        break;
      }
    if (!any)
      return;
    for (Frozen& f : m_frozen)
    {
      if (f.appear != now)
        continue;
      const int ci = Clampi(static_cast<int>(f.x), 0, m_nx - 1);
      const int cj = Clampi(static_cast<int>(f.y), 0, m_ny - 1);
      const size_t c = static_cast<size_t>(cj) * m_nx + ci;
      if (m_cellCount[c] > 0 && f.appear < now + 60)
        f.appear = now + 1; // fluid still here: wait
    }
  }

  // While the pool holds more than it started with, the bottom row loses
  // particles; they come back as the next digits.
  void Drain()
  {
    if (!drainOn || m_count <= m_target)
      return;
    size_t excess = m_count - m_target;
    const float floorY = m_ny - 1.0f - 0.9f;
    const size_t limit = std::max<size_t>(4, m_nx / 6);
    size_t removed = 0;
    for (size_t i = 0; i < m_count && removed < std::min(excess, limit);)
    {
      if (m_py[i] > floorY && (Hash(static_cast<uint32_t>(i), static_cast<uint32_t>(m_step)) & 3) == 0)
      {
        RemoveParticle(i);
        removed++;
      }
      else
        i++;
    }
  }

  // Cells holding a standing (fully condensed) frozen particle are solid.
  void UpdateSolid()
  {
    std::fill(m_solid.begin(), m_solid.end(), 0);
    const int now = static_cast<int>(m_step);
    for (const Frozen& f : m_frozen)
      if (f.appear <= now)
      {
        const int ci = Clampi(static_cast<int>(f.x), 1, m_nx - 2);
        const int cj = Clampi(static_cast<int>(f.y), 1, m_ny - 2);
        m_solid[static_cast<size_t>(cj) * m_nx + ci] = 1;
      }
    for (int j = 0; j < m_ny; j++)
      for (int i = 0; i < m_nx; i++)
      {
        const size_t c = static_cast<size_t>(j) * m_nx + i;
        const bool wall = i == 0 || i == m_nx - 1 || j == m_ny - 1;
        m_s[c] = (wall || m_solid[c]) ? 0.0f : 1.0f;
      }
  }

  // ---- the FLIP step

  template<typename Fn>
  void Parallel(size_t n, Fn fn)
  {
    if (m_pool)
      m_pool->Run(n, [&](size_t lo, size_t hi) { fn(lo, hi); });
    else
      fn(0, n);
  }

  // fn(k) for k in [0, n), dealt out to the threads like cards (k, k + T,
  // k + 2T ... to one thread), so work bunched at one end is shared out.
  template <typename Fn>
  void ParallelDealt(int n, Fn fn)
  {
    const int deal = m_pool ? std::max(1, m_pool->threads()) : 1;
    m_deal.clear();
    for (int r = 0; r < deal; r++)
      for (int k = r; k < n; k += deal)
        m_deal.push_back(k);
    Parallel(m_deal.size(), [&](size_t a, size_t b) {
      for (size_t i = a; i < b; i++)
        fn(m_deal[i]);
    });
  }
  std::vector<int> m_deal;
  std::vector<uint8_t> m_late;

  void Integrate(float dt)
  {
    const float gx = m_gx * dt, gy = m_gy * dt;
    Parallel(m_count, [&](size_t lo, size_t hi) {
      for (size_t i = lo; i < hi; i++)
      {
        m_ox[i] = m_px[i];
        m_oy[i] = m_py[i];
        m_vx[i] += gx;
        m_vy[i] += gy;
        m_px[i] += m_vx[i] * dt;
        m_py[i] += m_vy[i] * dt;
      }
    });
  }

  // Counting sort of the particles into cell order, data and all.
  void Sort()
  {
    const size_t cells = static_cast<size_t>(m_nx) * m_ny;
    std::fill(m_cellCount.begin(), m_cellCount.end(), 0);
    m_key.resize(m_count);
    for (size_t i = 0; i < m_count; i++)
    {
      const int ci = Clampi(static_cast<int>(m_px[i]), 0, m_nx - 1);
      const int cj = Clampi(static_cast<int>(m_py[i]), 0, m_ny - 1);
      const uint32_t c = static_cast<uint32_t>(cj * m_nx + ci);
      m_key[i] = c;
      m_cellCount[c]++;
    }
    uint32_t run = 0;
    for (size_t c = 0; c < cells; c++)
    {
      m_cellStart[c] = run;
      run += m_cellCount[c];
    }
    m_cellStart[cells] = run;
    m_fill.assign(m_cellStart.begin(), m_cellStart.end() - 1);
    auto permute = [&](auto& a, auto& tmp) {
      tmp.resize(m_count);
      for (size_t i = 0; i < m_count; i++)
        tmp[m_fill2[i]] = a[i];
      a.swap(tmp);
    };
    m_fill2.resize(m_count);
    for (size_t i = 0; i < m_count; i++)
      m_fill2[i] = m_fill[m_key[i]]++;
    permute(m_px, m_tmpF);
    permute(m_py, m_tmpF);
    permute(m_vx, m_tmpF);
    permute(m_vy, m_tmpF);
    permute(m_ox, m_tmpF);
    permute(m_oy, m_tmpF);
    permute(m_col, m_tmpB);
    permute(m_age, m_tmpA);
  }

  // Push overlapping particles apart (Jacobi: read positions, write moves),
  // so threads can share the work and the result does not depend on it.
  void Separate()
  {
    const float minDist = 2.0f * m_r, minDist2 = minDist * minDist;
    m_dx.assign(m_count, 0.0f);
    m_dy.assign(m_count, 0.0f);
    Parallel(m_count, [&](size_t lo, size_t hi) {
      for (size_t i = lo; i < hi; i++)
      {
        const float px = m_px[i], py = m_py[i];
        const int ci = Clampi(static_cast<int>(px), 0, m_nx - 1);
        const int cj = Clampi(static_cast<int>(py), 0, m_ny - 1);
        float mx = 0, my = 0;
        // only the neighbouring cells a particle within minDist can be in
        const float fx = px - ci, fy = py - cj;
        const int i0 = fx < minDist && ci > 0 ? ci - 1 : ci, i1 = fx > 1 - minDist && ci < m_nx - 1 ? ci + 1 : ci;
        const int j0 = fy < minDist && cj > 0 ? cj - 1 : cj, j1 = fy > 1 - minDist && cj < m_ny - 1 ? cj + 1 : cj;
        for (int j = j0; j <= j1; j++)
        {
          const size_t row = static_cast<size_t>(j) * m_nx;
          const uint32_t a = m_cellStart[row + i0];
          const uint32_t b = m_cellStart[row + i1 + 1];
          for (uint32_t k = a; k < b; k++)
          {
            if (k == i)
              continue;
            const float dx = px - m_px[k], dy = py - m_py[k];
            const float d2 = dx * dx + dy * dy;
            if (d2 >= minDist2 || d2 == 0.0f)
              continue;
            const float d = std::sqrt(d2);
            const float s = 0.5f * (minDist - d) / d;
            mx += dx * s;
            my += dy * s;
          }
        }
        m_dx[i] = mx * 0.6f; // under-relaxed: neighbours move too
        m_dy[i] = my * 0.6f;
      }
    });
    Parallel(m_count, [&](size_t lo, size_t hi) {
      for (size_t i = lo; i < hi; i++)
      {
        m_px[i] += m_dx[i];
        m_py[i] += m_dy[i];
      }
    });
  }

  // Walls and the solid digits. A particle that ends up in a solid cell goes
  // back to where it was this substep and loses its speed into the wall;
  // fresh melt touching the solid clings to it.
  void Collide()
  {
    const float lo = 1.0f + m_r, hix = m_nx - 1.0f - m_r, hiy = m_ny - 1.0f - m_r, top = m_r;
    const float stick = params.stick;
    Parallel(m_count, [&](size_t a, size_t b) {
      for (size_t i = a; i < b; i++)
      {
        float x = m_px[i], y = m_py[i];
        if (x < lo) { x = lo; m_vx[i] = 0; }
        if (x > hix) { x = hix; m_vx[i] = 0; }
        if (y > hiy) { y = hiy; m_vy[i] = 0; }
        if (y < top) { y = top; m_vy[i] = 0; }
        const int ci = static_cast<int>(x), cj = static_cast<int>(y);
        if (m_solid[static_cast<size_t>(cj) * m_nx + ci])
        {
          const int oi = Clampi(static_cast<int>(m_ox[i]), 0, m_nx - 1);
          const int oj = Clampi(static_cast<int>(m_oy[i]), 0, m_ny - 1);
          if (!m_solid[static_cast<size_t>(oj) * m_nx + oi])
          {
            if (oi != ci) m_vx[i] = 0;
            if (oj != cj) m_vy[i] = 0;
            x = m_ox[i];
            y = m_oy[i];
          }
          else
          {
            // inside a digit that formed around it: out through the nearest side
            const float fx = x - ci, fy = y - cj;
            const float d[4] = {fx, 1 - fx, fy, 1 - fy};
            int best = -1;
            float bd = 9;
            const int ni[4] = {ci - 1, ci + 1, ci, ci};
            const int nj[4] = {cj, cj, cj - 1, cj + 1};
            for (int k = 0; k < 4; k++)
              if (ni[k] > 0 && ni[k] < m_nx - 1 && nj[k] >= 0 && nj[k] < m_ny - 1 &&
                  !m_solid[static_cast<size_t>(nj[k]) * m_nx + ni[k]] && d[k] < bd)
              {
                bd = d[k];
                best = k;
              }
            if (best == 0) x = ci - 0.01f;
            else if (best == 1) x = ci + 1.01f;
            else if (best == 2) y = cj - 0.01f;
            else if (best == 3) y = cj + 1.01f;
            m_vx[i] *= 0.5f;
            m_vy[i] *= 0.5f;
          }
        }
        else if (m_age[i] < 120 && Touching(ci, cj))
        {
          // young melt clings to the solid it came from
          const float k = stick + (1.0f - stick) * (m_age[i] / 120.0f);
          m_vx[i] *= k;
          m_vy[i] *= k;
        }
        m_px[i] = x;
        m_py[i] = y;
      }
    });
    for (size_t i = 0; i < m_count; i++)
      if (m_age[i] < 60000)
        m_age[i]++;
  }

  bool Touching(int ci, int cj) const
  {
    for (int j = std::max(cj - 1, 0); j <= std::min(cj + 1, m_ny - 1); j++)
      for (int i = std::max(ci - 1, 0); i <= std::min(ci + 1, m_nx - 1); i++)
        if (m_solid[static_cast<size_t>(j) * m_nx + i])
          return true;
    return false;
  }

  // Particle velocities onto the grid (u on the left faces, v on the top
  // faces), with per-thread accumulators so threads never share a cell.
  void ToGrid()
  {
    const size_t cells = static_cast<size_t>(m_nx) * m_ny;
    // cell types
    for (size_t c = 0; c < cells; c++)
      m_type[c] = m_s[c] == 0.0f ? SOLID : (m_cellCount[c] ? FLUID : AIR);
    // m_cellCount is from before the separation; recount the occupied cells
    for (size_t i = 0; i < m_count; i++)
    {
      const int ci = Clampi(static_cast<int>(m_px[i]), 0, m_nx - 1);
      const int cj = Clampi(static_cast<int>(m_py[i]), 0, m_ny - 1);
      const size_t c = static_cast<size_t>(cj) * m_nx + ci;
      if (m_type[c] == AIR)
        m_type[c] = FLUID;
    }
    // The particles are sorted by cell, so the ones in a band of 4 rows only
    // touch the rows from two above to one below it: the even bands can be
    // splatted at the same time, then the odd ones, into one set of arrays.
    // A particle that has moved more than a row since the sort waits and is
    // done afterwards on one thread.
    std::fill(m_u.begin(), m_u.end(), 0.0f);
    std::fill(m_v.begin(), m_v.end(), 0.0f);
    std::fill(m_du.begin(), m_du.end(), 0.0f);
    std::fill(m_dv.begin(), m_dv.end(), 0.0f);
    m_late.assign(m_count, 0);
    const int bands = (m_ny + 3) / 4;
    for (int parity = 0; parity < 2; parity++)
      ParallelDealt((bands + 1 - parity) / 2, [&](int k) {
        const int band = 2 * k + parity;
        const uint32_t a = m_cellStart[static_cast<size_t>(band * 4) * m_nx];
        const uint32_t b = m_cellStart[static_cast<size_t>(std::min(m_ny, band * 4 + 4)) * m_nx];
        const float lo = band * 4 - 1.0f, hi = band * 4 + 5.0f;
        for (uint32_t i = a; i < b && i < m_count; i++)
        {
          if (m_py[i] < lo || m_py[i] >= hi)
          {
            m_late[i] = 1;
            continue;
          }
          Splat4(m_u, m_du, m_px[i], m_py[i] - 0.5f, m_vx[i]);
          Splat4(m_v, m_dv, m_px[i] - 0.5f, m_py[i], m_vy[i]);
        }
      });
    for (size_t i = 0; i < m_count; i++)
      if (m_late[i])
      {
        Splat4(m_u, m_du, m_px[i], m_py[i] - 0.5f, m_vx[i]);
        Splat4(m_v, m_dv, m_px[i] - 0.5f, m_py[i], m_vy[i]);
      }
    for (size_t c = 0; c < cells; c++)
    {
      m_u[c] = m_du[c] > 0 ? m_u[c] / m_du[c] : 0.0f;
      m_v[c] = m_dv[c] > 0 ? m_v[c] / m_dv[c] : 0.0f;
    }
    // no flow through solid faces
    for (int j = 0; j < m_ny; j++)
      for (int i = 0; i < m_nx; i++)
      {
        const size_t c = static_cast<size_t>(j) * m_nx + i;
        const bool solid = m_type[c] == SOLID;
        if (solid || (i > 0 && m_type[c - 1] == SOLID))
          m_u[c] = 0.0f;
        if (solid || (j > 0 && m_type[c - m_nx] == SOLID))
          m_v[c] = 0.0f;
      }
    // FLIP hands the particles the change the grid makes from here on
    // (viscosity and pressure), not the transfer itself
    std::copy(m_u.begin(), m_u.end(), m_prevU.begin());
    std::copy(m_v.begin(), m_v.end(), m_prevV.begin());
  }

  // Bilinear splat of a value at (x, y) on a grid whose nodes sit at integer
  // coordinates.
  void Splat4(std::vector<float>& f, std::vector<float>& w, float x, float y, float val) const
  {
    x = std::min(std::max(x, 0.0f), m_nx - 1.001f);
    y = std::min(std::max(y, 0.0f), m_ny - 1.001f);
    const int i = std::min(static_cast<int>(x), m_nx - 2), j = std::min(static_cast<int>(y), m_ny - 2);
    const float tx = x - i, ty = y - j, sx = 1 - tx, sy = 1 - ty;
    const size_t c = static_cast<size_t>(j) * m_nx + i;
    const float w0 = sx * sy, w1 = tx * sy, w2 = tx * ty, w3 = sx * ty;
    f[c] += w0 * val;
    w[c] += w0;
    f[c + 1] += w1 * val;
    w[c + 1] += w1;
    f[c + m_nx + 1] += w2 * val;
    w[c + m_nx + 1] += w2;
    f[c + m_nx] += w3 * val;
    w[c + m_nx] += w3;
  }

  float Sample(const std::vector<float>& f, float x, float y) const
  {
    x = std::min(std::max(x, 0.0f), m_nx - 1.001f);
    y = std::min(std::max(y, 0.0f), m_ny - 1.001f);
    const int i = std::min(static_cast<int>(x), m_nx - 2), j = std::min(static_cast<int>(y), m_ny - 2);
    const float tx = x - i, ty = y - j;
    const size_t c = static_cast<size_t>(j) * m_nx + i;
    return (1 - tx) * (1 - ty) * f[c] + tx * (1 - ty) * f[c + 1] + tx * ty * f[c + m_nx + 1] +
           (1 - tx) * ty * f[c + m_nx];
  }

  // Particle density at cell centres, for the drift correction.
  void Density()
  {
    std::fill(m_density.begin(), m_density.end(), 0.0f);
    m_wtmp.assign(m_density.size(), 0.0f);
    for (size_t i = 0; i < m_count; i++)
      Splat4(m_density, m_wtmp, m_px[i] - 0.5f, m_py[i] - 0.5f, 1.0f);
    // the splat added the weights to both: the density is the weight sum
    m_density.swap(m_wtmp);
    if (m_rest == 0.0f)
    {
      double sum = 0;
      int n = 0;
      for (size_t c = 0; c < m_density.size(); c++)
        if (m_type[c] == FLUID)
        {
          sum += m_density[c];
          n++;
        }
      if (n > 0)
        m_rest = static_cast<float>(sum / n);
    }
  }

  // Thicker liquids: blend each fluid face velocity with its neighbours.
  void Viscosity()
  {
    if (params.smooth <= 0.0f)
      return;
    const float a = params.smooth;
    for (auto* f : {&m_u, &m_v})
    {
      m_wtmp = *f;
      for (int j = 1; j < m_ny - 1; j++)
        for (int i = 1; i < m_nx - 1; i++)
        {
          const size_t c = static_cast<size_t>(j) * m_nx + i;
          if (m_type[c] != FLUID)
            continue;
          const float avg = 0.25f * (m_wtmp[c - 1] + m_wtmp[c + 1] + m_wtmp[c - m_nx] + m_wtmp[c + m_nx]);
          (*f)[c] += a * (avg - m_wtmp[c]);
        }
    }
  }

  // Make the grid velocity divergence-free: Gauss-Seidel over a list of the
  // fluid cells, red then black (a fork-join per sweep costs more than the
  // sweep on grids this small, so it stays on one thread). The per-cell
  // constants (open sides, 1/sum, the drift correction) are worked out once.
  void Pressure(float dt)
  {
    (void)dt;
    const float omega = params.overRelax;
    m_fluid.clear();
    for (int colour = 0; colour < 2; colour++)
    {
      if (colour == 1)
        m_redCount = m_fluid.size();
      for (int j = 1; j < m_ny - 1; j++)
        for (int i = 1 + ((j + colour) & 1); i < m_nx - 1; i += 2)
        {
          const size_t c = static_cast<size_t>(j) * m_nx + i;
          if (m_type[c] != FLUID)
            continue;
          const float s = m_s[c - 1] + m_s[c + 1] + m_s[c - m_nx] + m_s[c + m_nx];
          if (s == 0.0f)
            continue;
          FluidCell f;
          f.c = static_cast<uint32_t>(c);
          f.inv = omega / s;
          f.s[0] = m_s[c - 1];
          f.s[1] = m_s[c + 1];
          f.s[2] = m_s[c - m_nx];
          f.s[3] = m_s[c + m_nx];
          const float comp = m_rest > 0.0f ? m_density[c] - m_rest : 0.0f;
          f.drift = comp > 0.0f ? comp : 0.0f;
          m_fluid.push_back(f);
        }
    }
    float* u = m_u.data();
    float* v = m_v.data();
    const size_t nx = static_cast<size_t>(m_nx);
    // Two cells of a colour at a time: they share no face, and loading both
    // before storing either keeps an in-order core (the Cortex-A53/A55 of a
    // TV stick) busy instead of waiting out each one's chain of adds.
    const size_t pairs = m_redCount / 2 * 2;
    for (int it = 0; it < params.pressureIters; it++)
      for (int colour = 0; colour < 2; colour++)
      {
        const size_t begin = colour ? m_redCount : 0, end = colour ? m_fluid.size() : m_redCount;
        const size_t pairEnd = begin + (colour ? (end - begin) / 2 * 2 : pairs);
        size_t k = begin;
        for (; k < pairEnd; k += 2)
        {
          const FluidCell& f = m_fluid[k];
          const FluidCell& g = m_fluid[k + 1];
          const size_t c = f.c, d = g.c;
          const float fu0 = u[c], fu1 = u[c + 1], fv0 = v[c], fv1 = v[c + nx];
          const float gu0 = u[d], gu1 = u[d + 1], gv0 = v[d], gv1 = v[d + nx];
          const float p = -(fu1 - fu0 + fv1 - fv0 - f.drift) * f.inv;
          const float q = -(gu1 - gu0 + gv1 - gv0 - g.drift) * g.inv;
          u[c] = fu0 - f.s[0] * p;
          u[c + 1] = fu1 + f.s[1] * p;
          v[c] = fv0 - f.s[2] * p;
          v[c + nx] = fv1 + f.s[3] * p;
          u[d] = gu0 - g.s[0] * q;
          u[d + 1] = gu1 + g.s[1] * q;
          v[d] = gv0 - g.s[2] * q;
          v[d + nx] = gv1 + g.s[3] * q;
        }
        for (; k < end; k++)
        {
          const FluidCell& f = m_fluid[k];
          const size_t c = f.c;
          const float p = -(u[c + 1] - u[c] + v[c + nx] - v[c] - f.drift) * f.inv;
          u[c] -= f.s[0] * p;
          u[c + 1] += f.s[1] * p;
          v[c] -= f.s[2] * p;
          v[c + nx] += f.s[3] * p;
        }
      }
  }

  struct FluidCell
  {
    uint32_t c;
    float inv, drift;
    float s[4]; // open sides: left, right, top, bottom
  };
  std::vector<FluidCell> m_fluid;
  size_t m_redCount = 0;

  // Grid back to the particles: the FLIP change blended with PIC.
  void ToParticles()
  {
    const float flip = params.flip;
    Parallel(m_count, [&](size_t a, size_t b) {
      for (size_t i = a; i < b; i++)
      {
        const float x = m_px[i], y = m_py[i];
        const float u = SampleValid(m_u, x, y - 0.5f, 0);
        const float v = SampleValid(m_v, x - 0.5f, y, 1);
        const float du = u - SampleValid(m_prevU, x, y - 0.5f, 0);
        const float dv = v - SampleValid(m_prevV, x - 0.5f, y, 1);
        m_vx[i] = (1 - flip) * u + flip * (m_vx[i] + du);
        m_vy[i] = (1 - flip) * v + flip * (m_vy[i] + dv);
      }
    });
  }

  // Bilinear sample over faces next to fluid only (faces between air cells
  // carry no information).
  float SampleValid(const std::vector<float>& f, float x, float y, int axis) const
  {
    x = std::min(std::max(x, 0.0f), m_nx - 1.001f);
    y = std::min(std::max(y, 0.0f), m_ny - 1.001f);
    const int i = std::min(static_cast<int>(x), m_nx - 2), j = std::min(static_cast<int>(y), m_ny - 2);
    const float tx = x - i, ty = y - j;
    const size_t c[4] = {static_cast<size_t>(j) * m_nx + i, static_cast<size_t>(j) * m_nx + i + 1,
                         static_cast<size_t>(j + 1) * m_nx + i + 1, static_cast<size_t>(j + 1) * m_nx + i};
    const float w[4] = {(1 - tx) * (1 - ty), tx * (1 - ty), tx * ty, (1 - tx) * ty};
    const size_t off = axis == 0 ? 1 : static_cast<size_t>(m_nx);
    float sum = 0, ws = 0;
    for (int k = 0; k < 4; k++)
    {
      const bool valid = m_type[c[k]] == FLUID || (c[k] >= off && m_type[c[k] - off] == FLUID);
      if (valid)
      {
        sum += w[k] * f[c[k]];
        ws += w[k];
      }
    }
    return ws > 0 ? sum / ws : 0.0f;
  }

  // ---- the picture: every particle (fluid and frozen) splatted with a
  // smooth kernel into an RGBA picture, colour in RGB and density in A.

  // The picture: every particle adds a smooth bump (colour weighted, and a
  // density in alpha) to the texels around it. The weights come from a table
  // for 8 x 8 positions inside a texel, so a bump is only multiply-adds.
  void BuildKernel()
  {
    const int S = texScale;
    const float R = 1.15f * S; // kernel radius in texels
    m_kr = static_cast<int>(std::ceil(R));
    m_kw = 2 * m_kr + 1;
    m_kernel.assign(static_cast<size_t>(64) * m_kw * m_kw, 0.0f);
    for (int qy = 0; qy < 8; qy++)
      for (int qx = 0; qx < 8; qx++)
        for (int ky = -m_kr; ky <= m_kr; ky++)
          for (int kx = -m_kr; kx <= m_kr; kx++)
          {
            const float dx = kx + 0.5f - (qx + 0.5f) / 8.0f, dy = ky + 0.5f - (qy + 0.5f) / 8.0f;
            const float q = 1.0f - (dx * dx + dy * dy) / (R * R);
            m_kernel[((qy * 8 + qx) * m_kw + ky + m_kr) * m_kw + kx + m_kr] = q > 0 ? q * q * q : 0.0f;
          }
  }

  void SplatOne(V4* buf, int ty0, int ty1, float px, float py, const RGB& c, float weight) const
  {
    const float cx = px * texScale, cy = py * texScale;
    const int bx = static_cast<int>(cx), by = static_cast<int>(cy);
    const int qx = Clampi(static_cast<int>((cx - bx) * 8), 0, 7), qy = Clampi(static_cast<int>((cy - by) * 8), 0, 7);
    const float* k = m_kernel.data() + static_cast<size_t>(qy * 8 + qx) * m_kw * m_kw;
    const int ya = std::max(ty0, by - m_kr), yb = std::min(ty1 - 1, by + m_kr);
    const int xa = std::max(0, bx - m_kr), xb = std::min(m_tw - 1, bx + m_kr);
    const V4 c4 = {c.r * weight, c.g * weight, c.b * weight, weight};
    for (int y = ya; y <= yb; y++)
    {
      const float* kr = k + (y - by + m_kr) * m_kw - bx + m_kr;
      V4* t = buf + static_cast<size_t>(y) * m_tw;
      for (int x = xa; x <= xb; x++)
        t[x] += c4 * kr[x];
    }
  }

  void Splat()
  {
    const int S = texScale;
    const int now = static_cast<int>(m_step);
    const size_t texels = static_cast<size_t>(m_tw) * m_th;
    if (m_kernel.empty())
      BuildKernel();

    // The standing digits are kept in a picture of their own: a digit is added
    // once it has condensed and taken away when it thaws, and only the digits
    // still condensing are drawn every step.
    if (m_frozenAcc.size() != texels || now % 1800 == 0)
    {
      m_frozenAcc.assign(texels, V4{0, 0, 0, 0});
      for (Frozen& f : m_frozen)
        f.cached = 0;
      m_unsplat.clear();
    }
    for (const Frozen& f : m_unsplat)
      SplatOne(m_frozenAcc.data(), 0, m_th, f.x, f.y, m_baseRGB[f.base % 64], -1.08f);
    m_unsplat.clear();
    m_condensing.clear();
    for (size_t k = 0; k < m_frozen.size(); k++)
    {
      Frozen& f = m_frozen[k];
      if (f.cached || f.appear > now)
        continue;
      if (now - f.appear >= 20)
      {
        SplatOne(m_frozenAcc.data(), 0, m_th, f.x, f.y, m_baseRGB[f.base % 64], 1.08f);
        f.cached = 1;
      }
      else
        m_condensing.push_back(static_cast<uint32_t>(k));
    }

    const int Ri = m_kr;
    // Bands of 8 rows, dealt out to the threads like cards: the fluid is
    // mostly at the bottom, so contiguous slices would leave one thread with
    // all of it.
    const int bands = std::max(1, m_th / 8);
    const int deal = m_pool ? std::max(1, m_pool->threads()) : 1;
    m_bandOrder.clear();
    for (int r = 0; r < deal; r++)
      for (int b = r; b < bands; b += deal)
        m_bandOrder.push_back(b);
    Parallel(static_cast<size_t>(bands), [&](size_t b0, size_t b1) {
      for (size_t bi = b0; bi < b1; bi++)
      {
        const size_t band = static_cast<size_t>(m_bandOrder[bi]);
        const int ty0 = static_cast<int>(band) * m_th / bands;
        const int ty1 = static_cast<int>(band + 1) * m_th / bands;
        const size_t o0 = static_cast<size_t>(ty0) * m_tw, o1 = static_cast<size_t>(ty1) * m_tw;
        std::copy(m_frozenAcc.begin() + o0, m_frozenAcc.begin() + o1, m_acc.begin() + o0);
        const int rj0 = Clampi((ty0 - Ri) / S - 1, 0, m_ny - 1), rj1 = Clampi((ty1 + Ri) / S + 1, 0, m_ny - 1);
        const uint32_t pa = m_cellStart[static_cast<size_t>(rj0) * m_nx];
        const uint32_t pb = m_cellStart[static_cast<size_t>(rj1 + 1) * m_nx];
        for (uint32_t i = pa; i < pb && i < m_count; i++)
          SplatOne(m_acc.data(), ty0, ty1, m_px[i], m_py[i], m_baseRGB[m_col[i] % 64], 1.0f);
        const float ylo = static_cast<float>(ty0 - Ri - 1) / S, yhi = static_cast<float>(ty1 + Ri + 1) / S;
        for (uint32_t k : m_condensing)
        {
          const Frozen& f = m_frozen[k];
          if (f.y >= ylo && f.y <= yhi)
            SplatOne(m_acc.data(), ty0, ty1, f.x, f.y, m_baseRGB[f.base % 64], (now - f.appear) / 20.0f * 1.08f);
        }
        // to bytes: colour normalised, density scaled so a packed fluid is ~0.75
        const float dscale = 0.75f * 255.0f / std::max(0.2f, m_restTex);
        const V4* acc = m_acc.data();
        uint8_t* o = m_picture.data() + o0 * 4;
        for (size_t k = o0; k < o1; k++, o += 4)
        {
          const V4 a = acc[k];
          const float w = a[3];
          if (w <= 1e-3f)
          {
            o[0] = o[1] = o[2] = o[3] = 0;
            continue;
          }
          // premultiplied, so the colour filters cleanly at the edges
          const float alpha = std::min(255.0f, w * dscale);
          const float inv = alpha / w;
          o[0] = static_cast<uint8_t>(std::min(alpha, a[0] * inv));
          o[1] = static_cast<uint8_t>(std::min(alpha, a[1] * inv));
          o[2] = static_cast<uint8_t>(std::min(alpha, a[2] * inv));
          o[3] = static_cast<uint8_t>(alpha);
        }
      }
    });
    if (m_restTex == 0.0f)
    {
      // the kernel sum inside packed fluid, measured once on the starting pool
      double sum = 0;
      int n = 0;
      for (int y = m_th - 4 * S; y < m_th - 2 * S; y++)
        for (int x = m_tw / 3; x < 2 * m_tw / 3; x++)
        {
          sum += m_acc[static_cast<size_t>(y) * m_tw + x][3];
          n++;
        }
      m_restTex = n && sum > 0 ? static_cast<float>(sum / n) : 1.0f;
      Splat();
    }
  }

  std::vector<float> m_kernel;
  int m_kr = 0, m_kw = 0;
  std::vector<Frozen> m_unsplat;
  std::vector<uint32_t> m_condensing;
  std::vector<V4> m_frozenAcc;
  std::vector<int> m_bandOrder;

  int m_nx = 0, m_ny = 0;
  uint32_t m_seed = 1, m_rng = 1;
  long m_step = 0;
  float m_r = 0.3f, m_rest = 0.0f, m_restTex = 0.0f;
  float m_gx = 0, m_gy = 0;
  WorkerPool* m_pool = nullptr;

  // particles (structure of arrays)
  size_t m_count = 0, m_target = 0;
  std::vector<float> m_px, m_py, m_vx, m_vy, m_ox, m_oy, m_dx, m_dy, m_tmpF;
  std::vector<uint8_t> m_col, m_tmpB;
  std::vector<uint16_t> m_age, m_tmpA;
  std::vector<uint32_t> m_key, m_fill, m_fill2;

  // grid
  std::vector<float> m_u, m_v, m_du, m_dv, m_prevU, m_prevV, m_s, m_density, m_wtmp;
  std::vector<uint8_t> m_type, m_solid;
  std::vector<uint32_t> m_cellStart, m_cellCount;

  // the clock
  GlyphCache m_glyphs;
  std::string m_text;
  std::vector<Slot> m_slots;
  std::vector<Frozen> m_frozen;
  RGB m_baseRGB[64];
  int m_bases = 7;

  // the picture
  int m_tw = 0, m_th = 0;
  std::vector<uint8_t> m_picture;
  std::vector<V4> m_acc;
};

} // namespace sandclock2

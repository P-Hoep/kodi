// Reef ridges: autocatalytic calcification against a nutrient carried by a current
// (after Mistr & Bercovici 2003).
//
// Two fields on a periodic grid: the reef (solid volume fraction) psi and the dissolved
// nutrient c. With the paper's autocatalytic exponents m = 2, l = 1 and the porosity terms
// folded into the rate constants, the dimensionless system is
//
//   dc/dt   = alpha_s - c - c psi^2 - u . grad c + kappa lap c     supply, flushing, uptake, current
//   dpsi/dt = c psi^2 (1 - psi/K) - mu psi + lambda lap psi        calcification, bio-erosion, slumping
//
// The (1 - psi/K) factor is the closing porosity: as the matrix fills, the pore water that feeds
// calcification runs out. The nutrient is stepped semi-implicitly (uptake and inflow), which
// keeps the scheme stable at the diffusion time step.
//
// A reef patch strips nutrient from the water passing over it, so the water just downstream is
// starved until the surface supply alpha_s refills it. That instability (it needs m > 1) sets up
// ridges at right angles to the current, at a spacing set by the fastest-growing wavenumber, and
// the ridges creep upstream towards the fresh water. Storms now and then break up a patch of reef
// so it has to regrow.
#pragma once

#include "Common.h"

#include <vector>

namespace lc
{

struct ReefParams
{
  int width = 320;
  int height = 180;
  float flow = 0.5f;   // 0..1: strength of the current (Peclet number)
  bool storms = true;
  bool vivid = false;
  uint32_t seed = 1;
};

class Reef
{
public:
  void Init(const ReefParams& p)
  {
    m_p = p;
    m_w = std::max(16, p.width);
    m_h = std::max(16, p.height);
    m_rng.Seed(p.seed * 0x2545F4914F6CDD1Dull + 99);
    m_seed = p.seed * 31u + 7u;
    m_time = 0;
    m_modelTime = 0;

    // Random regime within the patterned range.
    m_supply = m_rng.Range(0.9f, 2.0f);
    m_mu = 0.45f;
    m_lambda = 1.0f;
    m_kappa = m_rng.Chance(0.5f) ? m_rng.Range(0.0f, 1.0f) : m_rng.Range(4.0f, 12.0f);
    m_u = 20.0f + 140.0f * Clamp01(p.flow) * m_rng.Range(0.8f, 1.2f);
    m_alongX = m_rng.Chance(0.65f);
    m_sign = m_rng.Chance(0.5f) ? 1 : -1;
    // Grid spacing: about 5-15 ridges across the long side.
    m_dx = m_rng.Range(0.8f, 1.3f) * 320.0f / std::max(m_w, m_h * 16 / 9);
    // Stable explicit step: advection CFL and diffusion limits.
    m_dt = 0.2f * m_dx * m_dx / m_lambda;
    m_rate = m_rng.Range(4.0f, 7.0f); // model time units per real second

    const size_t n = static_cast<size_t>(m_w) * m_h;
    m_psi.assign(n, 0.0f);
    m_c.assign(n, m_supply);
    m_np.assign(n, 0.0f);
    m_nc.assign(n, 0.0f);
    m_height.assign(n, 0.0f);
    const float H = static_cast<float>(m_h);
    for (int y = 0; y < m_h; y++)
      for (int x = 0; x < m_w; x++)
      {
        const float f = Fbm(x / H * 6.0f, y / H * 6.0f, m_seed, 3);
        const size_t i = static_cast<size_t>(y) * m_w + x;
        m_psi[i] = f > 0.62f ? m_rng.Range(1.0f, 3.0f) : (m_rng.Chance(0.02f) ? 1.5f : 0.0f);
      }
    m_psiRef = 3.0f;
    m_nextStorm = m_rng.Range(25.0f, 45.0f);
    BuildPalette();
  }

  // Advance by dt real seconds.
  void Advance(float realDt)
  {
    m_time += realDt;
    m_owed += realDt * m_rate;
    int steps = static_cast<int>(m_owed / m_dt);
    steps = std::min(steps, kMaxStepsPerFrame);
    for (int s = 0; s < steps; s++)
      Step();
    m_owed -= steps * m_dt;
    if (m_owed > 10 * m_dt)
      m_owed = 0; // can't keep up: slow the model down instead of spiralling

    if (m_p.storms && m_time >= m_nextStorm)
    {
      Storm();
      m_nextStorm = m_time + m_rng.Range(25.0f, 50.0f);
    }
  }

  void Paint(std::vector<uint8_t>& rgba)
  {
    rgba.resize(static_cast<size_t>(m_w) * m_h * 4);
    // Normalise the height by a slowly tracked high percentile so the look is stable.
    float peak = 0;
    for (size_t i = 0; i < m_psi.size(); i += 7)
      peak = std::max(peak, m_psi[i]);
    m_psiRef += (std::max(peak, 0.5f) - m_psiRef) * 0.05f;
    const float inv = 1.0f / m_psiRef;
    for (int y = 0; y < m_h; y++)
    {
      for (int x = 0; x < m_w; x++)
      {
        const size_t i = static_cast<size_t>(y) * m_w + x;
        const Base& base = m_base[i];
        const float t = Smooth(0.04f, 0.85f, m_psi[i] * inv);
        // rubble and turf algae at the thin edges, living coral where the reef is thick
        const Col edge = Mix(m_turf, base.sand, 0.4f);
        Col c = t < 0.35f ? Mix(base.sand, edge, t / 0.35f)
                          : Mix(edge, base.coral, (t - 0.35f) / 0.65f);
        // deeper water over the sand is bluer
        c = Mix(c, m_water, 0.15f * (1.0f - t));
        const float h = 0.12f + 0.7f * t * base.rough + base.sandH;
        m_height[i] = h;
        Put(&rgba[i * 4], c, h);
      }
    }
  }

  int Width() const { return m_w; }
  int Height() const { return m_h; }
  float Time() const { return m_time; }
  const std::vector<float>& Heights() const { return m_height; } // valid after Paint

  float Cover() const
  {
    size_t k = 0;
    for (float v : m_psi)
      k += v > 0.5f;
    return static_cast<float>(k) / m_psi.size();
  }
  // Coefficient of variation of the reef: 0 for a uniform state.
  float Contrast() const
  {
    double s = 0, s2 = 0;
    for (float v : m_psi)
    {
      s += v;
      s2 += static_cast<double>(v) * v;
    }
    const double n = static_cast<double>(m_psi.size());
    const double mean = s / n;
    const double var = std::max(0.0, s2 / n - mean * mean);
    return mean > 1e-6 ? static_cast<float>(std::sqrt(var) / mean) : 0.0f;
  }

private:
  static constexpr int kMaxStepsPerFrame = 24;
  static constexpr float kCapacity = 6.0f;

  void Step()
  {
    const int w = m_w, h = m_h;
    const float dt = m_dt, inv2 = 1.0f / (m_dx * m_dx);
    const float adv = m_u / m_dx;
    const float invK = 1.0f / kCapacity;
    const float kap = m_kappa * inv2;
    for (int y = 0; y < h; y++)
    {
      const int yu = y + 1 < h ? y + 1 : 0, yd = y > 0 ? y - 1 : h - 1;
      for (int x = 0; x < w; x++)
      {
        const int xr = x + 1 < w ? x + 1 : 0, xl = x > 0 ? x - 1 : w - 1;
        const size_t i = static_cast<size_t>(y) * w + x;
        const size_t il = static_cast<size_t>(y) * w + xl, ir = static_cast<size_t>(y) * w + xr;
        const size_t id = static_cast<size_t>(yd) * w + x, iu = static_cast<size_t>(yu) * w + x;
        const float p = m_psi[i], c = m_c[i];
        const float lapP = (m_psi[il] + m_psi[ir] + m_psi[id] + m_psi[iu] - 4 * p) * inv2;
        // first-order upwind: the value the current brings in
        const size_t up = m_alongX ? (m_sign > 0 ? il : ir) : (m_sign > 0 ? id : iu);
        const float p2 = p * p;
        const float nsum = m_c[il] + m_c[ir] + m_c[id] + m_c[iu];
        const float cn = std::max(0.0f, (c + dt * (m_supply + adv * m_c[up] + kap * nsum)) /
                                            (1.0f + dt * (1.0f + p2 + adv + 4.0f * kap)));
        m_nc[i] = cn;
        m_np[i] = std::max(0.0f, p + dt * (cn * p2 * std::max(0.0f, 1.0f - p * invK) - m_mu * p +
                                           m_lambda * lapP));
      }
    }
    m_psi.swap(m_np);
    m_c.swap(m_nc);
    m_modelTime += dt;
  }

  void Storm()
  {
    const float r = m_rng.Range(0.08f, 0.2f) * m_h;
    const float cx = m_rng.Range(0.0f, static_cast<float>(m_w));
    const float cy = m_rng.Range(0.0f, static_cast<float>(m_h));
    const int ir = static_cast<int>(r) + 1;
    for (int dy = -ir; dy <= ir; dy++)
      for (int dx = -ir; dx <= ir; dx++)
      {
        const float d = std::sqrt(static_cast<float>(dx * dx + dy * dy)) / r;
        if (d >= 1.0f)
          continue;
        const int x = ((static_cast<int>(cx) + dx) % m_w + m_w) % m_w;
        const int y = ((static_cast<int>(cy) + dy) % m_h + m_h) % m_h;
        const size_t i = static_cast<size_t>(y) * m_w + x;
        const float keep = 0.05f + 0.95f * Smooth(0.6f, 1.0f, d);
        m_psi[i] *= keep;
        // a few fragments survive and seed the regrowth
        if (m_rng.Chance(0.004f))
          m_psi[i] = 1.5f;
      }
  }

  void BuildPalette()
  {
    struct Pal
    {
      Col a, b, c, tip;
    };
    static const Pal kPals[] = {
        {{0.95f, 0.45f, 0.55f}, {0.98f, 0.62f, 0.38f}, {0.62f, 0.38f, 0.80f}, {1.0f, 0.9f, 0.8f}},
        {{0.72f, 0.58f, 0.38f}, {0.48f, 0.62f, 0.42f}, {0.40f, 0.70f, 0.85f}, {0.8f, 1.0f, 0.9f}},
        {{0.55f, 0.32f, 0.70f}, {0.30f, 0.65f, 0.75f}, {0.95f, 0.55f, 0.75f}, {0.9f, 0.9f, 1.0f}},
        {{0.95f, 0.60f, 0.25f}, {0.85f, 0.40f, 0.30f}, {0.98f, 0.85f, 0.45f}, {1.0f, 1.0f, 0.85f}},
        {{0.40f, 0.78f, 0.55f}, {0.70f, 0.85f, 0.45f}, {0.35f, 0.55f, 0.85f}, {0.85f, 1.0f, 0.7f}},
    };
    const Pal& p = kPals[m_rng.Int(0, 4)];
    m_coralA = p.a;
    m_coralB = p.b;
    m_coralC = p.c;
    m_tip = p.tip;
    if (m_p.vivid)
    {
      const float hue = m_rng.Uni();
      m_coralA = Hsv(hue, 0.8f, 1.0f);
      m_coralB = Hsv(hue + 0.12f, 0.7f, 0.95f);
      m_coralC = Hsv(hue + 0.5f, 0.75f, 0.9f);
      m_tip = Hsv(hue + 0.3f, 0.3f, 1.0f);
    }
    m_sand = Mix({0.86f, 0.80f, 0.64f}, {0.80f, 0.78f, 0.72f}, m_rng.Uni());
    m_turf = {0.45f, 0.48f, 0.30f};
    m_water = Mix({0.08f, 0.30f, 0.60f}, {0.05f, 0.40f, 0.55f}, m_rng.Uni());

    // The static part of every cell's colour, so Paint only blends.
    m_base.assign(static_cast<size_t>(m_w) * m_h, {});
    const float H = static_cast<float>(m_h);
    for (int y = 0; y < m_h; y++)
      for (int x = 0; x < m_w; x++)
      {
        Base& b = m_base[static_cast<size_t>(y) * m_w + x];
        const float r = Hash01(x, y, m_seed);
        const float sandN = Fbm(x / H * 14.0f, y / H * 14.0f, m_seed + 5, 3);
        b.sand = Scale(m_sand, 0.82f + 0.3f * sandN + 0.06f * r);
        // ripples in the sand, across the current
        const float along = m_alongX ? static_cast<float>(x) : static_cast<float>(y);
        b.sand = Scale(b.sand, 0.94f + 0.06f * std::sin(along * 0.9f + 5.0f * sandN));
        const float patch = Fbm(x / H * 3.0f, y / H * 3.0f, m_seed + 9, 3);
        Col coral = Mix(m_coralA, m_coralB, Smooth(0.35f, 0.65f, patch));
        coral = Mix(coral, m_coralC,
                    Smooth(0.6f, 0.75f, Fbm(x / H * 7.0f, y / H * 7.0f, m_seed + 13, 2)));
        if (r > 0.9f) // polyps
          coral = Mix(coral, m_tip, 0.5f);
        b.coral = Scale(coral, 0.8f + 0.3f * Hash01(x >> 1, y >> 1, m_seed + 3));
        b.rough = 0.85f + 0.15f * r;
        b.sandH = 0.04f * sandN;
      }
  }

  struct Base
  {
    Col sand, coral;
    float rough = 1, sandH = 0;
  };
  std::vector<Base> m_base;

  ReefParams m_p;
  int m_w = 0, m_h = 0;
  uint32_t m_seed = 1;
  Rng m_rng;
  float m_time = 0, m_modelTime = 0, m_owed = 0;
  float m_supply = 1.5f, m_mu = 0.45f, m_lambda = 1, m_kappa = 0, m_u = 60;
  float m_dx = 0.5f, m_dt = 0.005f, m_rate = 3;
  bool m_alongX = true;
  int m_sign = 1;
  float m_psiRef = 3, m_nextStorm = 30;
  Col m_coralA, m_coralB, m_coralC, m_tip, m_sand, m_turf, m_water;
  std::vector<float> m_psi, m_c, m_np, m_nc, m_height;
};

} // namespace lc

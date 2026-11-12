// Lichen on rock: Open-DLA colonies competing for a rock face.
//
//  * Morphology (Desbenoit, Galin & Akkouche 2004, Open-DLA): biomass particles random-walk
//    around a colony and stick with probability P(p) = E(p) * A(p), where
//      E(p) = min(I(p), L(p), W(p))                  indirect light, direct light, moisture
//      A(p) = alpha + (1 - alpha) exp(-sigma (n(p) - tau)^2)
//    and n(p) is the number of the colony's own cells within the 5x5 neighbourhood of p.
//  * Radial growth rate (Hill 1981; Seminara et al. 2018): each colony's target radius obeys
//      dR/dt = v_max R / (R + r0)
//    exponential while small, then a constant margin speed. The walkers fill the disc of that
//    radius, so the shape comes from A(p) and the space left by neighbours.
//  * Community (Jettestuen et al. 2010): new colonies nucleate on free rock at a rate b per unit
//    free area. b is chosen from the 2D coverage-time law
//      t ~ [ ln(U0/U) / (a^2 b) ]^(1/3)
//    so the rock is covered in about the scene length. Colonies meet along tessellation lines.
//  * Old centres of some species die back (Hill's senescing centre), leaving rings and free rock
//    that new colonies can claim.
#pragma once

#include "Common.h"

#include <vector>

namespace lc
{

struct LichenParams
{
  int width = 640;
  int height = 360;
  float duration = 180.0f; // seconds the community should take to cover the rock
  int species = 5;         // 1..8 species on one rock
  int form = 0;            // 0 mixed, 1 crustose, 2 lobed (foliose), 3 branching
  bool rings = true;       // allow centre die-back
  bool vivid = false;      // invented colours instead of natural lichen colours
  uint32_t seed = 1;
};

class Lichen
{
public:
  struct Species
  {
    Col body, margin, old, apo;
    float vmax = 1, r0 = 5, thick = 0.4f;
    float aggregation[25] = {}; // A(n) for n = 0..24
    bool ring = false, prothallus = false, apothecia = false;
    float life = 0, apoDensity = 0;
    int form = 1;
  };

  static constexpr int kRecent = 48;

  struct Colony
  {
    int species = 0;
    float cx = 0, cy = 0;
    float R = 1, rmax = 0;
    int grown = 0;
    int stall = 0;
    float env = 1;
    int recent[kRecent] = {};
    int recentCount = 0;
  };

  void Init(const LichenParams& p)
  {
    m_p = p;
    m_w = std::max(16, p.width);
    m_h = std::max(16, p.height);
    m_rng.Seed(p.seed * 2654435761ull + 12345);
    m_seed = p.seed;
    m_time = 0;
    m_colonies.clear();
    const size_t n = static_cast<size_t>(m_w) * m_h;
    m_owner.assign(n, 0);
    m_birth.assign(n, 0.0f);
    m_rnd.assign(n, 0);
    m_scar.assign(n, -1e9f);
    m_env.assign(n, 0.0f);
    m_rockH.assign(n, 0.0f);
    m_rockCol.assign(n * 3, 0);
    m_heightOut.assign(n, 0.0f);
    BuildRock();
    BuildSpecies();

    // Nucleation rate from the 2D coverage-time law, using the mean margin speed for a.
    float vmean = 0;
    for (const auto& s : m_species)
      vmean += s.vmax;
    vmean /= static_cast<float>(m_species.size());
    const float tCover = 0.75f * p.duration;
    const float lnRatio = std::log(1.0f / 0.03f);
    // The exponential start (R < r0) delays coverage, which the 2.5 compensates for.
    m_b = 2.5f * lnRatio / (vmean * vmean * tCover * tCover * tCover);

    const int initial = m_rng.Int(3, 7);
    for (int i = 0; i < initial; i++)
      Nucleate();
    m_deathTimer = 0;
  }

  // Advance the model by dt seconds.
  void Step(float dt)
  {
    m_time += dt;

    // Jettestuen nucleation: expected b * U * dt new colonies.
    const float expected = m_b * static_cast<float>(m_freeHab) * dt;
    int births = static_cast<int>(expected);
    if (m_rng.Uni() < expected - births)
      births++;
    for (int i = 0; i < births; i++)
      Nucleate();

    // Growth: each colony fills the disc set by dR/dt = v R / (R + r0).
    long budget = kStepBudget;
    const int n = static_cast<int>(m_colonies.size());
    if (n > 0)
    {
      m_rr = (m_rr + 1) % n;
      for (int k = 0; k < n && budget > 0; k++)
      {
        const int id = (m_rr + k) % n;
        Colony& c = m_colonies[id];
        const Species& s = m_species[c.species];
        c.R += dt * s.vmax * c.R / (c.R + s.r0) * (0.35f + 0.65f * c.env);
        c.R = std::min(c.R, std::sqrt(c.grown / kPi) + 1.5f);
        const float deficit = kPi * c.R * c.R - static_cast<float>(c.grown);
        if (deficit < 1.0f)
          continue;
        // A colony boxed in by its neighbours only probes now and then.
        if (c.stall > 8 && (++c.stall % 24) != 0)
          continue;
        const int attempts = std::min(static_cast<int>(deficit * 3.0f) + 1, 48);
        int wins = 0;
        for (int a = 0; a < attempts && budget > 0; a++)
        {
          if (Walk(c, id, budget))
          {
            if (++wins >= static_cast<int>(deficit) + 1)
              break;
          }
        }
        if (wins == 0)
          c.stall++;
        else if (wins > 0)
          c.stall = 0;
      }
    }

    m_stepsUsed = kStepBudget - budget;
    m_deathTimer += dt;
    if (m_deathTimer >= 0.5f)
    {
      m_deathTimer = 0;
      DieBack();
    }
  }

  // Colour and height of every cell; RGBA rows bottom to top, alpha = height.
  void Paint(std::vector<uint8_t>& rgba)
  {
    rgba.resize(static_cast<size_t>(m_w) * m_h * 4);
    const float marginT = std::max(2.0f, 0.04f * m_p.duration);
    const float oldT0 = 0.15f * m_p.duration, oldT1 = 0.8f * m_p.duration;
    const float scarT = 0.2f * m_p.duration;
    // Age-dependent factors through a table: margin glow and greying of old tissue.
    const float ageMax = 2.0f * m_p.duration;
    const float lutScale = (kLut - 1) / ageMax;
    if (m_lutFor != m_p.duration)
    {
      m_lutFor = m_p.duration;
      for (int k = 0; k < kLut; k++)
      {
        const float age = k / lutScale;
        m_lutMargin[k] = std::exp(-age / marginT);
        m_lutOld[k] = 0.4f * Smooth(oldT0, oldT1, age);
      }
    }
    for (int y = 0; y < m_h; y++)
    {
      for (int x = 0; x < m_w; x++)
      {
        const int i = y * m_w + x;
        const int o = m_owner[i];
        Col c;
        const float rock = m_rockH[i];
        float h = 0.6f * rock;
        if (o)
        {
          const Species& s = m_species[m_colonies[o - 1].species];
          const float age = m_time - m_birth[i];
          const float r = m_rnd[i] * (1.0f / 255.0f);
          const int k = std::min(kLut - 1, static_cast<int>(age * lutScale));
          const float m = m_lutMargin[k];
          c = Scale(Mix(s.body, s.margin, m), 0.86f + 0.26f * r);
          c = Mix(c, s.old, m_lutOld[k]);
          float thick = s.thick * (0.5f + 0.5f * (1.0f - m)) * (0.85f + 0.3f * r);
          if (s.apothecia && age > 0.12f * m_p.duration &&
              Hash01(x >> 1, y >> 1, m_seed + 977u * o) < s.apoDensity)
          {
            c = Scale(s.apo, 0.8f + 0.35f * r);
            thick += 0.12f;
          }
          // Where two colonies meet, a dark line (the black prothallus of map lichens).
          if (Border(x, y, o))
            c = Scale(c, s.prothallus ? 0.22f : 0.6f);
          h += 0.4f * thick;
        }
        else
        {
          c = {m_rockCol[i * 3] / 255.0f, m_rockCol[i * 3 + 1] / 255.0f,
               m_rockCol[i * 3 + 2] / 255.0f};
          const float since = m_time - m_scar[i];
          if (since < 3 * scarT)
            c = Scale(c, 1.0f - 0.3f * std::exp(-since / scarT));
        }
        m_heightOut[i] = h;
        Put(&rgba[static_cast<size_t>(i) * 4], c, h);
      }
    }
  }

  int Width() const { return m_w; }
  int Height() const { return m_h; }
  const std::vector<float>& Heights() const { return m_heightOut; } // valid after Paint
  float Time() const { return m_time; }
  size_t Colonies() const { return m_colonies.size(); }
  long StepsUsed() const { return m_stepsUsed; }
  const std::vector<Species>& SpeciesList() const { return m_species; }
  float FreeFraction() const
  {
    return m_hab > 0 ? static_cast<float>(m_freeHab) / static_cast<float>(m_hab) : 0.0f;
  }
  bool Done() const { return FreeFraction() < 0.05f || m_time > 1.5f * m_p.duration; }

private:
  static constexpr long kStepBudget = 400000; // walker steps per Step at most
  static constexpr int kMaxColonies = 60000;
  static constexpr int kWalk = 600;
  static constexpr int kLut = 512;
  float m_lutMargin[kLut] = {}, m_lutOld[kLut] = {};
  float m_lutFor = -1;
  long m_stepsUsed = 0;

  bool In(int x, int y) const { return x >= 2 && y >= 2 && x < m_w - 2 && y < m_h - 2; }

  bool Border(int x, int y, int o) const
  {
    const int i = y * m_w + x;
    auto other = [&](int j) { return m_owner[j] && m_owner[j] != o; };
    return (x > 0 && other(i - 1)) || (x < m_w - 1 && other(i + 1)) ||
           (y > 0 && other(i - m_w)) || (y < m_h - 1 && other(i + m_w));
  }

  void BuildRock()
  {
    const uint32_t s = m_seed * 7919u + 3u;
    const float H = static_cast<float>(m_h);
    const int type = m_rng.Int(0, 4);
    // granite, sandstone, slate, limestone, basalt
    static const Col kBase[5][2] = {
        {{0.62f, 0.58f, 0.56f}, {0.78f, 0.72f, 0.70f}},
        {{0.66f, 0.50f, 0.36f}, {0.80f, 0.66f, 0.50f}},
        {{0.30f, 0.33f, 0.37f}, {0.44f, 0.47f, 0.50f}},
        {{0.70f, 0.69f, 0.64f}, {0.84f, 0.83f, 0.78f}},
        {{0.24f, 0.24f, 0.25f}, {0.38f, 0.37f, 0.36f}},
    };
    const float dir = m_rng.Chance(0.5f) ? 1.0f : -1.0f;
    const float bandAngle = m_rng.Range(-0.4f, 0.4f);

    std::vector<float> raw(m_env.size());
    for (int y = 0; y < m_h; y++)
    {
      for (int x = 0; x < m_w; x++)
      {
        const int i = y * m_w + x;
        const float fx = x / H, fy = y / H;
        const float coarse = Fbm(fx * 2.2f, fy * 2.2f, s, 2);
        const float fine = Fbm(fx * 2.2f, fy * 2.2f, s, 6);
        const float grain = Fbm(fx * 40.0f, fy * 40.0f, s + 11, 2);
        // cracks: thin lines where a noise field crosses its middle
        const float crackField = Fbm(fx * 3.0f, fy * 3.0f, s + 23, 4);
        const float crack = 1.0f - Smooth(0.0f, 0.012f, std::fabs(crackField - 0.5f));
        float h = 0.75f * fine + 0.25f * grain - 0.35f * crack;
        m_rockH[i] = Clamp01(h);

        float t = Fbm(fx * 1.5f, fy * 1.5f, s + 31, 4);
        if (type == 1 || type == 2) // bedding planes
          t = 0.5f + 0.5f * std::sin((fy + bandAngle * fx) * 28.0f + 6.0f * t);
        Col c = Mix(kBase[type][0], kBase[type][1], t);
        const float speck = Hash01(x, y, s + 41);
        if (type == 0 && speck > 0.93f)
          c = speck > 0.975f ? Col{0.92f, 0.9f, 0.88f} : Col{0.15f, 0.14f, 0.15f};
        else
          c = Scale(c, 0.9f + 0.2f * speck);

        // Moisture: vertical drip streaks plus a damper foot of the rock.
        const float streak = Fbm(fx * 9.0f, fy * 0.7f, s + 53, 3);
        const float wraw = 0.75f * streak + 0.35f * (1.0f - fy * H / m_h);
        const float wet = Smooth(0.45f, 0.8f, wraw);
        c = Scale(c, (1.0f - 0.28f * wet) * (1.0f - 0.45f * crack));
        m_rockCol[i * 3] = ToByte(c.r);
        m_rockCol[i * 3 + 1] = ToByte(c.g);
        m_rockCol[i * 3 + 2] = ToByte(c.b);

        // The three environment fields of Desbenoit et al.
        const float I = Clamp01(0.7f + 5.0f * (fine - coarse) - crack);
        const float L = Clamp01(0.35f + Fbm(fx * 1.2f, fy * 1.2f, s + 61, 3) +
                                0.35f * dir * (fx * H / m_w - 0.5f));
        const float W = Clamp01(0.2f + wraw);
        raw[i] = std::min(I, std::min(L, W));
      }
    }

    // Choose the cut so a random 5-25% of the rock is too harsh for lichen.
    std::vector<float> sample;
    for (size_t i = 0; i < raw.size(); i += 37)
      sample.push_back(raw[i]);
    const float barren = m_rng.Range(0.05f, 0.25f);
    const size_t k = static_cast<size_t>(barren * (sample.size() - 1));
    std::nth_element(sample.begin(), sample.begin() + k, sample.end());
    const float q = sample[k];
    m_hab = 0;
    for (size_t i = 0; i < raw.size(); i++)
    {
      m_env[i] = Smooth(q, q + 0.08f, raw[i]);
      if (m_env[i] > 0.0f)
        m_hab++;
    }
    m_freeHab = m_hab;
  }

  void BuildSpecies()
  {
    struct Natural
    {
      Col body, margin, apo;
      bool prothallus;
    };
    // Rough colours of common rock lichens.
    static const Natural kNatural[] = {
        {{0.93f, 0.55f, 0.12f}, {1.0f, 0.72f, 0.25f}, {0.85f, 0.35f, 0.05f}, false}, // Xanthoria
        {{0.74f, 0.80f, 0.20f}, {0.86f, 0.90f, 0.38f}, {0.08f, 0.08f, 0.07f}, true},  // Rhizocarpon
        {{0.62f, 0.74f, 0.62f}, {0.75f, 0.85f, 0.74f}, {0.50f, 0.35f, 0.22f}, false}, // Flavoparmelia
        {{0.86f, 0.86f, 0.80f}, {0.95f, 0.95f, 0.90f}, {0.72f, 0.58f, 0.36f}, false}, // Lecanora
        {{0.95f, 0.40f, 0.10f}, {1.0f, 0.55f, 0.20f}, {0.80f, 0.25f, 0.05f}, false},  // Caloplaca
        {{0.97f, 0.84f, 0.22f}, {1.0f, 0.93f, 0.45f}, {0.90f, 0.70f, 0.10f}, false},  // Candelariella
        {{0.60f, 0.66f, 0.70f}, {0.74f, 0.79f, 0.82f}, {0.15f, 0.15f, 0.16f}, false}, // Physcia
        {{0.27f, 0.27f, 0.26f}, {0.40f, 0.40f, 0.38f}, {0.05f, 0.05f, 0.05f}, true},  // Lecidea
        {{0.72f, 0.70f, 0.63f}, {0.84f, 0.82f, 0.76f}, {0.20f, 0.18f, 0.16f}, false}, // Aspicilia
        {{0.76f, 0.78f, 0.45f}, {0.88f, 0.88f, 0.58f}, {0.45f, 0.30f, 0.18f}, false}, // Xanthoparmelia
    };
    constexpr int kNat = sizeof(kNatural) / sizeof(kNatural[0]);
    int order[kNat];
    for (int i = 0; i < kNat; i++)
      order[i] = i;
    for (int i = kNat - 1; i > 0; i--)
      std::swap(order[i], order[m_rng.Int(0, i)]);

    const int count = std::max(1, std::min(8, m_p.species));
    const float hueBase = m_rng.Uni();
    const float vBase = 0.22f * m_h / m_p.duration; // cells per second
    m_species.assign(count, {});
    for (int k = 0; k < count; k++)
    {
      Species& s = m_species[k];
      if (m_p.vivid)
      {
        const float hue = hueBase + static_cast<float>(k) / count + m_rng.Range(-0.04f, 0.04f);
        s.body = Hsv(hue, m_rng.Range(0.55f, 0.9f), m_rng.Range(0.7f, 1.0f));
        s.margin = Hsv(hue + 0.05f, 0.35f, 1.0f);
        s.apo = Hsv(hue + 0.5f, 0.8f, 0.6f);
        s.prothallus = m_rng.Chance(0.4f);
      }
      else
      {
        const Natural& n = kNatural[order[k % kNat]];
        s.body = n.body;
        s.margin = n.margin;
        s.apo = n.apo;
        s.prothallus = n.prothallus;
      }
      s.old = Mix(s.body, {0.45f, 0.45f, 0.42f}, 0.6f);

      int form = m_p.form;
      if (form < 1 || form > 3)
      {
        const float u = m_rng.Uni();
        form = u < 0.5f ? 1 : (u < 0.85f ? 2 : 3);
      }
      s.form = form;
      float alpha, sigma, tau;
      if (form == 1) // crustose: dense, smooth-edged discs
      {
        tau = m_rng.Range(12.0f, 15.0f);
        sigma = m_rng.Range(0.05f, 0.12f);
        alpha = m_rng.Range(0.002f, 0.01f);
        s.thick = m_rng.Range(0.2f, 0.35f);
      }
      else if (form == 2) // foliose: lobed rosettes
      {
        tau = m_rng.Range(8.0f, 11.0f);
        sigma = m_rng.Range(0.08f, 0.2f);
        alpha = m_rng.Range(0.005f, 0.02f);
        s.thick = m_rng.Range(0.4f, 0.6f);
      }
      else // fruticose-like: branching fans
      {
        tau = m_rng.Range(3.0f, 5.0f);
        sigma = m_rng.Range(0.15f, 0.4f);
        alpha = m_rng.Range(0.02f, 0.06f);
        s.thick = m_rng.Range(0.5f, 0.75f);
      }
      for (int n = 0; n <= 24; n++)
        s.aggregation[n] = alpha + (1 - alpha) * std::exp(-sigma * (n - tau) * (n - tau));

      s.vmax = vBase * m_rng.Range(0.6f, 1.4f) * (form == 3 ? 1.2f : 1.0f);
      s.r0 = m_rng.Range(3.0f, 12.0f);
      s.ring = m_p.rings && form != 3 && m_rng.Chance(0.4f);
      s.life = m_rng.Range(0.35f, 0.6f) * m_p.duration;
      s.apothecia = m_rng.Chance(0.6f);
      s.apoDensity = m_rng.Range(0.006f, 0.025f);
    }
  }

  void Nucleate()
  {
    if (static_cast<int>(m_colonies.size()) >= kMaxColonies || m_freeHab == 0)
      return;
    for (int tries = 0; tries < 30; tries++)
    {
      const int x = m_rng.Int(3, m_w - 4), y = m_rng.Int(3, m_h - 4);
      const int i = y * m_w + x;
      if (m_owner[i] || m_env[i] < 0.2f || m_rng.Uni() > m_env[i])
        continue;
      Colony c;
      c.species = m_rng.Int(0, static_cast<int>(m_species.size()) - 1);
      c.cx = static_cast<float>(x);
      c.cy = static_cast<float>(y);
      c.env = m_env[i];
      m_colonies.push_back(c);
      Stick(m_colonies.back(), static_cast<int>(m_colonies.size()) - 1, x, y);
      return;
    }
  }

  void Stick(Colony& c, int id, int x, int y)
  {
    const int i = y * m_w + x;
    m_owner[i] = static_cast<uint16_t>(id + 1);
    m_birth[i] = m_time;
    m_rnd[i] = static_cast<uint8_t>(m_rng.U32() & 255);
    if (m_env[i] > 0.0f)
      m_freeHab--;
    c.grown++;
    c.recent[c.recentCount++ % kRecent] = i;
    const float dx = x - c.cx, dy = y - c.cy;
    c.rmax = std::max(c.rmax, std::sqrt(dx * dx + dy * dy));
  }

  // One Open-DLA particle: released just outside the colony, it walks until it sticks,
  // strays too far or runs out of steps. Cells held by any colony block it.
  bool Walk(Colony& c, int id, long& budget)
  {
    // Release the particle a few cells from a recently grown margin cell (or, now and then,
    // anywhere on a circle around the colony), so walkers reach the open margin and the
    // pockets between neighbours instead of dying on blocked sides.
    float ox, oy, killR;
    const float ang = m_rng.Uni() * 2.0f * kPi;
    if (c.recentCount > 0 && m_rng.Chance(0.75f))
    {
      const int j = c.recent[m_rng.U32() % static_cast<uint32_t>(std::min(c.recentCount, kRecent))];
      ox = static_cast<float>(j % m_w) + 3.0f * std::cos(ang);
      oy = static_cast<float>(j / m_w) + 3.0f * std::sin(ang);
      killR = 9.0f;
    }
    else
    {
      ox = c.cx + (c.rmax + 2.5f) * std::cos(ang);
      oy = c.cy + (c.rmax + 2.5f) * std::sin(ang);
      killR = 12.0f;
    }
    int x = static_cast<int>(std::lround(ox));
    int y = static_cast<int>(std::lround(oy));
    budget--;
    if (!In(x, y) || m_owner[y * m_w + x])
      return false;
    const float kill = killR * killR;
    const float sx = static_cast<float>(x), sy = static_cast<float>(y);
    const uint16_t own = static_cast<uint16_t>(id + 1);
    const Species& s = m_species[c.species];
    static const int kDx[4] = {1, -1, 0, 0}, kDy[4] = {0, 0, 1, -1};
    for (int step = 0; step < kWalk; step++)
    {
      const int i = y * m_w + x;
      if (m_owner[i - 1] == own || m_owner[i + 1] == own || m_owner[i - m_w] == own ||
          m_owner[i + m_w] == own)
      {
        int n = 0;
        for (int dy = -2; dy <= 2; dy++)
        {
          const uint16_t* row = &m_owner[i + dy * m_w - 2];
          n += (row[0] == own) + (row[1] == own) + (row[2] == own) + (row[3] == own) +
               (row[4] == own);
        }
        if (m_rng.Uni() < m_env[i] * s.aggregation[n])
        {
          Stick(c, id, x, y);
          budget -= step;
          return true;
        }
      }
      const uint32_t d = m_rng.U32() & 3u;
      const int nx = x + kDx[d], ny = y + kDy[d];
      if (!In(nx, ny))
      {
        budget -= step;
        return false;
      }
      if (m_owner[ny * m_w + nx])
        continue;
      const float ddx = nx - sx, ddy = ny - sy;
      if (ddx * ddx + ddy * ddy > kill)
      {
        budget -= step;
        return false;
      }
      x = nx;
      y = ny;
    }
    budget -= kWalk;
    return false;
  }

  // Ring species lose their oldest tissue, which frees rock for newcomers.
  void DieBack()
  {
    bool any = false;
    for (const auto& s : m_species)
      any |= s.ring;
    if (!any)
      return;
    const size_t n = m_owner.size();
    for (size_t i = 0; i < n; i++)
    {
      const int o = m_owner[i];
      if (!o)
        continue;
      const Species& s = m_species[m_colonies[o - 1].species];
      if (!s.ring)
        continue;
      const float life = s.life * (0.85f + 0.3f * m_rnd[i] / 255.0f);
      if (m_time - m_birth[i] > life)
      {
        m_owner[i] = 0;
        m_scar[i] = m_time;
        if (m_env[i] > 0.0f)
          m_freeHab++;
      }
    }
  }

  LichenParams m_p;
  int m_w = 0, m_h = 0;
  uint32_t m_seed = 1;
  Rng m_rng;
  float m_time = 0, m_b = 0, m_deathTimer = 0;
  int m_rr = 0;
  long m_hab = 0, m_freeHab = 0;
  std::vector<Species> m_species;
  std::vector<Colony> m_colonies;
  std::vector<uint16_t> m_owner;
  std::vector<float> m_birth, m_scar, m_env, m_rockH, m_heightOut;
  std::vector<uint8_t> m_rnd, m_rockCol;
};

} // namespace lc

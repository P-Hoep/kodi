// A 3D coral colony (after Merks, Hoekstra, Kaandorp & Sloot 2003, 2004).
//
// Two growth models, picked by the growth form:
//
// Branching forms (staghorn, bushy, table, sea fan) use the polyp-oriented model of Merks et al.
// 2004. The colony is a set of discrete polyps at the growing tips. Each polyp i takes up nutrient
//   U_i = exp(-k S_i)
// where S_i is the skeleton density in the water above and ahead of it (self-shading of the
// diffusing nutrient), and deposits skeleton beneath itself, moving outwards by the
// Michaelis-Menten step
//   dl(U_i) = l_max U_i / (K_U + U_i).
// A polyp that has grown further than its spacing limit d_max from its last division buds a
// daughter (a new branch). A polyp dies when it runs into skeleton closer than d_min or when
// its uptake falls below a survival threshold U_crit (shaded inside the colony). Older skeleton
// keeps thickening, so the base of each branch is stoutest.
//
// The massive form uses Laplacian growth on a voxel lattice (Merks et al. 2003): nutrient parcels
// random-walk in from all sides (the diffusion term) and calcify where they touch the colony with
// the Open-DLA probability
//   A(n) = alpha + (1 - alpha) exp(-sigma (n - tau)^2),
// n = skeleton neighbours among 26. A high tau fills hollows, giving a lumpy dome.
//
// The newest skeleton carries the living-tissue colour and fades into the colony colour.
#pragma once

#include "Common.h"

#include <vector>

namespace lc
{

struct CoralParams
{
  int size = 128;          // grid size in voxels (all three axes)
  int maxVoxels = 120000;  // the massive form stops growing here (branching forms use a quarter)
  float duration = 180.0f; // seconds to reach full size
  int form = 0;            // 0 random, 1 staghorn, 2 bushy, 3 massive, 4 table, 5 sea fan
  int colonies = 0;        // 0 random
  bool vivid = false;
  uint32_t seed = 1;
};

class Coral
{
public:
  // One sphere of skeleton, in grid units.
  struct Voxel
  {
    float x, y, z, r;
    float birth;
    uint8_t colony;
    uint8_t rgb[3];
  };

  struct Colony
  {
    float cx, cy;
    float radius = 2;
    float reach = 0, room = 1; // horizontal extent and the space available to it
    Col base, top, tip;
  };

  void Init(const CoralParams& p)
  {
    m_p = p;
    m_n = std::max(32, p.size);
    m_rng.Seed(p.seed * 0x9E3779B97F4A7C15ull + 4242);
    m_time = 0;
    m_voxels.clear();
    m_tips.clear();
    m_occ.assign(static_cast<size_t>(m_n) * m_n * m_n, 0);
    m_done = false;
    m_maxZ = 0;
    m_minX = m_minY = m_n;
    m_maxX = m_maxY = 0;

    m_form = p.form;
    if (m_form < 1 || m_form > 5)
    {
      static const int kPick[] = {1, 1, 1, 2, 2, 3, 3, 4, 4, 5};
      m_form = kPick[m_rng.Int(0, 9)];
    }
    m_dla = m_form == 3;
    m_limit = m_dla ? p.maxVoxels : std::max(2000, p.maxVoxels / 4);
    m_voxels.reserve(static_cast<size_t>(m_limit) + 256);

    int count = p.colonies;
    if (count < 1)
      count = m_form == 4 || m_form == 5 ? m_rng.Int(1, 2) : m_rng.Int(1, 3);
    count = std::min(count, 4);
    BuildColonies(count);
    if (m_dla)
      InitDla();
    else
      InitPolyps();
  }

  void Advance(float dt)
  {
    m_time += dt;
    if (m_done)
      return;
    const float target = Clamp01(m_time / std::max(10.0f, 0.85f * m_p.duration));
    if (m_dla)
    {
      long budget = kFrameBudget;
      int added = 0;
      while (budget > 0 && !m_done && added < 4000 && Progress() < target)
        if (WalkDla(budget))
          added++;
    }
    else
    {
      // Grow while behind the scene clock; a step moves a tip about half a voxel.
      for (int s = 0; s < 4 && !m_done && Progress() < target; s++)
        StepPolyps();
    }
    if (Progress() >= 1.0f)
      m_done = true;
  }

  // How far the colony has grown towards its limits, 0..1.
  float Progress() const
  {
    const float count = static_cast<float>(m_voxels.size()) / std::max(1, m_limit);
    const float height = static_cast<float>(m_maxZ) / (m_n * (m_form == 4 ? 0.45f : 0.82f));
    float side = 0;
    if (!m_dla)
      for (const auto& c : m_colonies)
        side = std::max(side, c.reach / c.room);
    return std::max(count, std::max(height, side));
  }

  Col ColourAt(const Voxel& v, float now) const
  {
    const Col c{v.rgb[0] / 255.0f, v.rgb[1] / 255.0f, v.rgb[2] / 255.0f};
    return Mix(c, m_colonies[v.colony].tip, std::exp(-(now - v.birth) / TipSpan()));
  }

  float TipSpan() const { return std::max(2.0f, 0.05f * m_p.duration); }
  // Older skeleton grows this much thicker (as a fraction of its radius) ...
  float Thickening() const { return m_dla ? 0.0f : m_thicken; }
  // ... over this many seconds.
  float ThickeningTime() const { return 0.5f * m_p.duration; }
  const std::vector<Voxel>& Voxels() const { return m_voxels; }
  const std::vector<Colony>& ColonyList() const { return m_colonies; }
  int Size() const { return m_n; }
  int MaxZ() const { return m_maxZ; }
  int Form() const { return m_form; }
  float Time() const { return m_time; }
  bool Done() const { return m_done; }
  size_t LiveTips() const
  {
    size_t k = 0;
    for (const auto& t : m_tips)
      k += t.alive;
    return k;
  }
  void Bounds(int& x0, int& y0, int& x1, int& y1, int& z1) const
  {
    x0 = m_minX;
    y0 = m_minY;
    x1 = m_maxX;
    y1 = m_maxY;
    z1 = m_maxZ;
  }

private:
  static constexpr long kFrameBudget = 250000;
  static constexpr int kMaxTips = 420;

  struct Tip
  {
    float p[3], d[3];
    float since = 0, next = 10, emit = 0, r = 1.5f;
    int colony = 0;
    bool alive = true;
  };

  size_t Idx(int x, int y, int z) const { return (static_cast<size_t>(z) * m_n + y) * m_n + x; }

  void BuildColonies(int count)
  {
    struct Pal
    {
      Col base, top, tip;
    };
    static const Pal kPals[] = {
        {{0.78f, 0.62f, 0.42f}, {0.90f, 0.78f, 0.56f}, {0.55f, 0.75f, 1.0f}},  // staghorn, blue tips
        {{0.85f, 0.38f, 0.52f}, {0.98f, 0.58f, 0.66f}, {1.0f, 0.85f, 0.9f}},   // pink
        {{0.52f, 0.32f, 0.75f}, {0.70f, 0.48f, 0.92f}, {0.85f, 0.75f, 1.0f}},  // purple
        {{0.30f, 0.60f, 0.42f}, {0.48f, 0.85f, 0.56f}, {0.75f, 1.0f, 0.6f}},   // green
        {{0.90f, 0.48f, 0.20f}, {1.0f, 0.66f, 0.32f}, {1.0f, 0.9f, 0.55f}},    // orange
        {{0.80f, 0.78f, 0.72f}, {0.96f, 0.95f, 0.91f}, {1.0f, 1.0f, 1.0f}},    // bleached
        {{0.58f, 0.46f, 0.30f}, {0.75f, 0.64f, 0.40f}, {0.45f, 1.0f, 0.75f}},  // brown, green glow
        {{0.25f, 0.45f, 0.72f}, {0.38f, 0.64f, 0.90f}, {0.7f, 0.95f, 1.0f}},   // blue
        {{0.80f, 0.20f, 0.25f}, {0.95f, 0.40f, 0.35f}, {1.0f, 0.75f, 0.6f}},   // red sea fan
        {{0.92f, 0.75f, 0.20f}, {1.0f, 0.88f, 0.40f}, {1.0f, 1.0f, 0.75f}},    // yellow
    };
    constexpr int kNum = sizeof(kPals) / sizeof(kPals[0]);
    m_colonies.clear();
    const float c = m_n * 0.5f;
    const float spread = count == 1 ? 0.0f : m_n * (m_form == 4 ? 0.2f : 0.16f);
    const float phase = m_rng.Range(0.0f, 2 * kPi);
    const float hue = m_rng.Uni();
    for (int k = 0; k < count; k++)
    {
      Colony col;
      const float a = phase + 2 * kPi * k / count + m_rng.Range(-0.3f, 0.3f);
      const float r = spread * m_rng.Range(0.75f, 1.1f);
      col.cx = c + r * std::cos(a);
      col.cy = c + r * std::sin(a);
      col.room = std::max(8.0f, std::min(std::min(col.cx, m_n - col.cx), std::min(col.cy, m_n - col.cy)) - 5.0f);
      if (m_p.vivid)
      {
        const float h = hue + static_cast<float>(k) / count * 0.6f;
        col.base = Hsv(h, 0.75f, 0.7f);
        col.top = Hsv(h + 0.06f, 0.6f, 1.0f);
        col.tip = Hsv(h + 0.4f, 0.35f, 1.0f);
      }
      else
      {
        const Pal& p = kPals[m_rng.Int(0, kNum - 1)];
        col.base = p.base;
        col.top = p.top;
        col.tip = p.tip;
      }
      m_colonies.push_back(col);
    }
  }

  // Add a sphere of skeleton; `crowd` (0..1) darkens sites deep inside the colony.
  void Emit(float x, float y, float z, float r, int colony, float crowd)
  {
    Colony& c = m_colonies[colony];
    const float t = Clamp01(z / (0.7f * m_n));
    Col col = Mix(c.base, c.top, t);
    col = Scale(col, (0.88f + 0.24f * m_rng.Uni()) * (1.0f - 0.5f * Clamp01(crowd)));
    Voxel v;
    v.x = x;
    v.y = y;
    v.z = z;
    v.r = r;
    v.birth = m_time;
    v.colony = static_cast<uint8_t>(colony);
    v.rgb[0] = ToByte(col.r);
    v.rgb[1] = ToByte(col.g);
    v.rgb[2] = ToByte(col.b);
    m_voxels.push_back(v);
    const int ix = static_cast<int>(x), iy = static_cast<int>(y), iz = static_cast<int>(z);
    m_minX = std::min(m_minX, ix - static_cast<int>(r));
    m_maxX = std::max(m_maxX, ix + static_cast<int>(r));
    m_minY = std::min(m_minY, iy - static_cast<int>(r));
    m_maxY = std::max(m_maxY, iy + static_cast<int>(r));
    m_maxZ = std::max(m_maxZ, iz);
    const float dx = x - c.cx, dy = y - c.cy;
    c.radius = std::max(c.radius, std::sqrt(dx * dx + dy * dy + z * z));
    c.reach = std::max(c.reach, std::sqrt(dx * dx + dy * dy) + r);
    if (static_cast<int>(m_voxels.size()) >= m_limit)
      m_done = true;
  }

  // ---------------------------------------------------------------- polyp-oriented model

  void InitPolyps()
  {
    m_coarse.assign(static_cast<size_t>(Cells()) * Cells() * Cells(), 0);
    m_tips.reserve(kMaxTips * 4 + 16); // budding appends while a reference to the parent is held
    float rLo, rHi;
    int startLo, startHi;
    switch (m_form)
    {
      case 1: // staghorn: long, stout, upward branches that fork at narrow angles
        m_elev = m_rng.Range(1.0f, 1.25f);
        m_steer = 0.05f;
        m_wander = 0.18f;
        m_angle = m_rng.Range(0.35f, 0.55f);
        m_branchLo = 6;
        m_branchHi = 14;
        rLo = 1.6f;
        rHi = 2.2f;
        startLo = 2;
        startHi = 4;
        m_thicken = 0.6f;
        break;
      case 2: // bushy: short internodes, wide angles
        m_elev = m_rng.Range(0.7f, 1.0f);
        m_steer = 0.04f;
        m_wander = 0.3f;
        m_angle = m_rng.Range(0.55f, 0.8f);
        m_branchLo = 4;
        m_branchHi = 9;
        rLo = 1.1f;
        rHi = 1.5f;
        startLo = 4;
        startHi = 7;
        m_thicken = 0.5f;
        break;
      case 4: // table: a stalk, then a near-horizontal plate of fine branches
        m_elev = m_rng.Range(0.0f, 0.15f);
        m_steer = 0.16f;
        m_wander = 0.15f;
        m_angle = m_rng.Range(0.4f, 0.6f);
        m_branchLo = 4;
        m_branchHi = 8;
        rLo = 1.1f;
        rHi = 1.4f;
        startLo = startHi = 1;
        m_thicken = 0.8f;
        m_stalk = m_rng.Range(0.12f, 0.22f) * m_n;
        break;
      default: // sea fan: fine branches in one vertical plane
        m_elev = m_rng.Range(0.9f, 1.2f);
        m_steer = 0.03f;
        m_wander = 0.22f;
        m_angle = m_rng.Range(0.45f, 0.7f);
        m_branchLo = 4;
        m_branchHi = 9;
        rLo = 0.8f;
        rHi = 1.1f;
        startLo = 1;
        startHi = 2;
        m_thicken = 0.7f;
        m_planar = true;
        break;
    }
    m_lmax = 0.55f;
    m_K = 0.35f;
    m_shadeK = m_rng.Range(0.05f, 0.09f);
    m_uCrit = m_rng.Range(0.06f, 0.12f);
    m_current = m_rng.Range(0.0f, 0.04f);
    m_currentAng = m_rng.Range(0.0f, 2 * kPi);

    const float plane = m_rng.Range(0.0f, kPi); // sea fans face the current together
    m_planeN[0] = std::cos(plane);
    m_planeN[1] = std::sin(plane);
    for (size_t k = 0; k < m_colonies.size(); k++)
    {
      const Colony& c = m_colonies[k];
      const float r = m_rng.Range(rLo, rHi);
      // holdfast
      for (int i = 0; i < 6; i++)
        Emit(c.cx + m_rng.Range(-1.5f, 1.5f), c.cy + m_rng.Range(-1.5f, 1.5f), 0.5f, r * 1.4f,
             static_cast<int>(k), 0.5f);
      const int starts = m_rng.Int(startLo, startHi);
      for (int i = 0; i < starts; i++)
      {
        Tip t;
        t.colony = static_cast<int>(k);
        t.p[0] = c.cx;
        t.p[1] = c.cy;
        t.p[2] = 1.0f;
        const float a = m_rng.Range(0.0f, 2 * kPi);
        const float tilt = m_form == 4 ? 0.05f : m_rng.Range(0.15f, 0.6f);
        t.d[0] = std::sin(tilt) * std::cos(a);
        t.d[1] = std::sin(tilt) * std::sin(a);
        t.d[2] = std::cos(tilt);
        if (m_planar)
          Flatten(t.d);
        t.r = r;
        t.next = m_form == 4 ? m_stalk : m_rng.Range(m_branchLo, m_branchHi);
        m_tips.push_back(t);
      }
    }
  }

  int Cells() const { return (m_n + 3) / 4; }

  // Project a direction onto the sea fan's plane.
  void Flatten(float d[3]) const
  {
    const float k = d[0] * m_planeN[0] + d[1] * m_planeN[1];
    d[0] -= k * m_planeN[0];
    d[1] -= k * m_planeN[1];
    Normalize(d);
  }

  static void Normalize(float d[3])
  {
    const float l = std::sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
    if (l > 1e-6f)
    {
      d[0] /= l;
      d[1] /= l;
      d[2] /= l;
    }
    else
    {
      d[0] = d[1] = 0;
      d[2] = 1;
    }
  }

  float CoarseAt(float x, float y, float z) const
  {
    const int c = Cells();
    const int ix = static_cast<int>(x) >> 2, iy = static_cast<int>(y) >> 2, iz = static_cast<int>(z) >> 2;
    if (ix < 0 || iy < 0 || iz < 0 || ix >= c || iy >= c || iz >= c)
      return 0;
    return m_coarse[(static_cast<size_t>(iz) * c + iy) * c + ix];
  }

  // Skeleton density in the water above and ahead of a tip: what shades its nutrient supply.
  float Shade(const Tip& t) const
  {
    float s = 0;
    for (int k = 1; k <= 4; k++)
    {
      const float f = 4.0f * k;
      s += CoarseAt(t.p[0] + t.d[0] * f * 0.5f, t.p[1] + t.d[1] * f * 0.5f, t.p[2] + f) / k;
      s += 0.5f * CoarseAt(t.p[0] + t.d[0] * f, t.p[1] + t.d[1] * f, t.p[2] + t.d[2] * f) / k;
    }
    return s;
  }

  // Mark the voxels inside a skeleton sphere, and the coarse density field.
  void Stamp(float x, float y, float z, float r)
  {
    const int ir = static_cast<int>(std::ceil(r));
    const int cx = static_cast<int>(x), cy = static_cast<int>(y), cz = static_cast<int>(z);
    for (int dz = -ir; dz <= ir; dz++)
      for (int dy = -ir; dy <= ir; dy++)
        for (int dx = -ir; dx <= ir; dx++)
        {
          const int X = cx + dx, Y = cy + dy, Z = cz + dz;
          if (X < 0 || Y < 0 || Z < 0 || X >= m_n || Y >= m_n || Z >= m_n)
            continue;
          if (dx * dx + dy * dy + dz * dz <= r * r)
            m_occ[Idx(X, Y, Z)] = 1;
        }
    const int c = Cells();
    const int ix = cx >> 2, iy = cy >> 2, iz = cz >> 2;
    if (ix >= 0 && iy >= 0 && iz >= 0 && ix < c && iy < c && iz < c)
    {
      uint8_t& v = m_coarse[(static_cast<size_t>(iz) * c + iy) * c + ix];
      if (v < 250)
        v++;
    }
  }

  bool Occupied(float x, float y, float z) const
  {
    const int X = static_cast<int>(x), Y = static_cast<int>(y), Z = static_cast<int>(z);
    if (X < 0 || Y < 0 || Z < 0 || X >= m_n || Y >= m_n || Z >= m_n)
      return false;
    return m_occ[Idx(X, Y, Z)] != 0;
  }

  void StepPolyps()
  {
    const float lo = 4.0f, hi = m_n - 5.0f;
    const size_t count = m_tips.size();
    int alive = 0;
    for (size_t i = 0; i < count; i++)
    {
      Tip& t = m_tips[i];
      if (!t.alive)
        continue;
      alive++;
      const Colony& col = m_colonies[t.colony];

      // nutrient uptake and the Michaelis-Menten growth step
      const float S = Shade(t);
      const float U = std::exp(-m_shadeK * S);
      if (U < m_uCrit && m_rng.Chance(0.15f))
      {
        t.alive = false; // starved inside the colony
        continue;
      }
      const float dl = m_lmax * U / (m_K + U) * (1.0f + m_K);

      // steer towards the form's preferred elevation, away from the colony centre
      float out[2] = {t.p[0] - col.cx, t.p[1] - col.cy};
      float ol = std::sqrt(out[0] * out[0] + out[1] * out[1]);
      if (ol < 1.0f)
      {
        out[0] = t.d[0];
        out[1] = t.d[1];
        ol = std::sqrt(out[0] * out[0] + out[1] * out[1]) + 1e-6f;
      }
      out[0] /= ol;
      out[1] /= ol;
      float elev = m_elev;
      if (m_form == 4 && t.p[2] < m_stalk)
        elev = 1.5f; // the table's stalk grows straight up first
      const float want[3] = {std::cos(elev) * out[0], std::cos(elev) * out[1], std::sin(elev)};
      const float steer = (m_form == 4 && t.p[2] < m_stalk) ? 0.3f : m_steer;
      for (int k = 0; k < 3; k++)
        t.d[k] += steer * (want[k] - t.d[k]) + m_wander * m_rng.Range(-0.5f, 0.5f) * 0.5f;
      t.d[0] += m_current * std::cos(m_currentAng);
      t.d[1] += m_current * std::sin(m_currentAng);
      // polyps keep their distance from other branch tips (d_min)
      for (size_t j = 0; j < count; j++)
      {
        if (j == i || !m_tips[j].alive)
          continue;
        const float* q = m_tips[j].p;
        const float ex = t.p[0] - q[0], ey = t.p[1] - q[1], ez = t.p[2] - q[2];
        const float d2 = ex * ex + ey * ey + ez * ez;
        if (d2 < 49.0f && d2 > 1e-4f)
        {
          const float k = 0.6f / d2;
          t.d[0] += ex * k;
          t.d[1] += ey * k;
          t.d[2] += ez * k;
        }
      }
      if (m_planar)
        Flatten(t.d);
      Normalize(t.d);
      if (t.d[2] < -0.2f)
      {
        t.d[2] = -0.2f;
        Normalize(t.d);
      }

      // running into skeleton ahead (d_min): the polyp stops
      const float ahead = t.r + 1.6f;
      if (Occupied(t.p[0] + t.d[0] * ahead, t.p[1] + t.d[1] * ahead, t.p[2] + t.d[2] * ahead))
      {
        t.alive = false;
        continue;
      }

      for (int k = 0; k < 3; k++)
        t.p[k] += t.d[k] * dl;
      if (t.p[0] < lo || t.p[1] < lo || t.p[0] > hi || t.p[1] > hi || t.p[2] > hi || t.p[2] < 0.5f)
      {
        t.alive = false;
        continue;
      }

      // deposit skeleton behind the polyp
      t.emit += dl;
      const float spacing = std::max(0.35f, 0.33f * t.r);
      while (t.emit >= spacing)
      {
        t.emit -= spacing;
        const float crowd = CoarseAt(t.p[0], t.p[1], t.p[2]) / 30.0f;
        Emit(t.p[0], t.p[1], t.p[2], t.r, t.colony, crowd);
        Stamp(t.p[0], t.p[1], t.p[2], t.r * 0.8f);
      }

      // budding: past the spacing limit d_max the polyp divides into a new branch
      t.since += dl;
      if (t.since >= t.next && static_cast<int>(m_tips.size()) < kMaxTips * 4 && alive < kMaxTips)
      {
        t.since = 0;
        t.next = m_rng.Range(m_branchLo, m_branchHi);
        Tip b = t;
        // a random axis perpendicular to the branch
        float axis[3] = {m_rng.Range(-1.0f, 1.0f), m_rng.Range(-1.0f, 1.0f), m_rng.Range(-1.0f, 1.0f)};
        if (m_planar)
        {
          axis[0] = m_planeN[0];
          axis[1] = m_planeN[1];
          axis[2] = 0;
        }
        const float dot = axis[0] * t.d[0] + axis[1] * t.d[1] + axis[2] * t.d[2];
        for (int k = 0; k < 3; k++)
          axis[k] -= dot * t.d[k];
        Normalize(axis);
        Rotate(b.d, axis, m_angle);
        Rotate(t.d, axis, -m_angle * 0.4f);
        b.r = t.r * m_rng.Range(0.85f, 1.0f);
        b.since = 0;
        b.emit = 0;
        b.next = m_rng.Range(m_branchLo, m_branchHi);
        // step the bud clear of its parent so it does not see the parent as an obstacle
        for (int k = 0; k < 3; k++)
          b.p[k] += b.d[k] * (t.r + 0.5f);
        m_tips.push_back(b);
        alive++;
      }
    }
    if (alive == 0)
      m_done = true;
  }

  // Rodrigues rotation of v about a unit axis.
  static void Rotate(float v[3], const float a[3], float ang)
  {
    const float c = std::cos(ang), s = std::sin(ang);
    const float d = a[0] * v[0] + a[1] * v[1] + a[2] * v[2];
    const float x[3] = {a[1] * v[2] - a[2] * v[1], a[2] * v[0] - a[0] * v[2], a[0] * v[1] - a[1] * v[0]};
    for (int k = 0; k < 3; k++)
      v[k] = v[k] * c + x[k] * s + a[k] * d * (1 - c);
  }

  // ---------------------------------------------------------------- Laplacian DLA (massive)

  void InitDla()
  {
    const float alpha = m_rng.Range(0.01f, 0.04f);
    const float sigma = m_rng.Range(0.06f, 0.12f);
    const float tau = m_rng.Range(8.0f, 11.0f);
    for (int n = 0; n <= 26; n++)
      m_aggregation[n] = alpha + (1 - alpha) * std::exp(-sigma * (n - tau) * (n - tau));
    for (size_t k = 0; k < m_colonies.size(); k++)
    {
      const int cx = static_cast<int>(m_colonies[k].cx), cy = static_cast<int>(m_colonies[k].cy);
      for (int dy = -2; dy <= 2; dy++)
        for (int dx = -2; dx <= 2; dx++)
          if (dx * dx + dy * dy <= 5)
            AddDla(cx + dx, cy + dy, 0, static_cast<int>(k), 6);
    }
  }

  void AddDla(int x, int y, int z, int colony, int crowd)
  {
    const size_t i = Idx(x, y, z);
    if (m_occ[i])
      return;
    m_occ[i] = static_cast<uint8_t>(colony + 1);
    Emit(x + 0.5f, y + 0.5f, z + 0.5f, 0.75f, colony, Smooth(2.0f, 14.0f, static_cast<float>(crowd)));
    if (m_minX < 4 || m_minY < 4 || m_maxX >= m_n - 4 || m_maxY >= m_n - 4 || m_maxZ >= m_n - 4)
      m_done = true;
  }

  // One nutrient parcel released on a hemisphere around a colony; true if it calcified.
  bool WalkDla(long& budget)
  {
    const int n = m_n;
    const Colony& c = m_colonies[m_rng.Int(0, static_cast<int>(m_colonies.size()) - 1)];
    const float r = c.radius + 3.0f;
    const float u = m_rng.Uni(), a = m_rng.Uni() * 2 * kPi;
    const float s = std::sqrt(std::max(0.0f, 1 - u * u));
    int x = static_cast<int>(std::lround(c.cx + r * s * std::cos(a)));
    int y = static_cast<int>(std::lround(c.cy + r * s * std::sin(a)));
    int z = static_cast<int>(std::lround(r * u));
    const float kill2 = (c.radius + 12.0f) * (c.radius + 12.0f);
    budget--;
    if (x < 1 || y < 1 || x > n - 2 || y > n - 2 || z < 0 || z > n - 2 || m_occ[Idx(x, y, z)])
      return false;
    const size_t sy = static_cast<size_t>(n), sz = static_cast<size_t>(n) * n;
    static const int kD[6][3] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
    for (int step = 0; step < 3000; step++)
    {
      const size_t i = Idx(x, y, z);
      if (m_occ[i + 1] || m_occ[i - 1] || m_occ[i + sy] || m_occ[i - sy] || m_occ[i + sz] ||
          (z > 0 && m_occ[i - sz]))
      {
        int count = 0, owner = 0;
        for (int dz = -1; dz <= 1; dz++)
        {
          if (z + dz < 0)
            continue;
          for (int dy = -1; dy <= 1; dy++)
          {
            const uint8_t* row = &m_occ[Idx(x - 1, y + dy, z + dz)];
            for (int dx = 0; dx < 3; dx++)
              if (row[dx])
              {
                count++;
                owner = row[dx];
              }
          }
        }
        if (m_rng.Uni() < m_aggregation[count])
        {
          AddDla(x, y, z, owner - 1, count);
          budget -= step;
          return true;
        }
      }
      const int* d = kD[m_rng.U32() % 6];
      const int nx = x + d[0], ny = y + d[1], nz = z + d[2];
      if (nz < 0)
        continue;
      if (nx < 1 || ny < 1 || nx > n - 2 || ny > n - 2 || nz > n - 2)
      {
        budget -= step;
        return false;
      }
      const float ddx = nx - c.cx, ddy = ny - c.cy;
      if (ddx * ddx + ddy * ddy + static_cast<float>(nz * nz) > kill2)
      {
        budget -= step;
        return false;
      }
      if (m_occ[Idx(nx, ny, nz)])
        continue;
      x = nx;
      y = ny;
      z = nz;
    }
    budget -= 3000;
    return false;
  }

  CoralParams m_p;
  int m_n = 128;
  Rng m_rng;
  float m_time = 0;
  int m_form = 1, m_limit = 30000;
  bool m_dla = false, m_done = false, m_planar = false;
  float m_aggregation[27] = {};
  int m_minX = 0, m_minY = 0, m_maxX = 0, m_maxY = 0, m_maxZ = 0;
  // polyp model
  float m_elev = 1, m_steer = 0.05f, m_wander = 0.2f, m_angle = 0.5f;
  float m_branchLo = 6, m_branchHi = 12, m_thicken = 0.5f, m_stalk = 0;
  float m_lmax = 0.5f, m_K = 0.3f, m_shadeK = 0.07f, m_uCrit = 0.08f;
  float m_current = 0, m_currentAng = 0;
  float m_planeN[2] = {1, 0};
  std::vector<Tip> m_tips;
  std::vector<uint8_t> m_coarse;
  std::vector<Colony> m_colonies;
  std::vector<Voxel> m_voxels;
  std::vector<uint8_t> m_occ;
};

} // namespace lc

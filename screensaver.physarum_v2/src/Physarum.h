// Physarum v2 simulation core - no Kodi / OpenGL dependencies.
//
// Jeff Jones's agent model of Physarum polycephalum transport networks
// (Artificial Life 16(2), 2010), as the Physarum screensavers in this
// repository run it: every agent senses the trail ahead, ahead-left and
// ahead-right, turns towards the strongest, steps forward and deposits; then
// the trail diffuses (3x3 mean) and decays. Up to three species follow their
// own trail and avoid the others'.
//
// The first Physarum add-ons run all of this on the GPU, which needs float
// render targets, vertex texture fetch and a dozen passes a step; the weak
// GPUs in 32-bit TV sticks choke on that. This version follows Particle Life
// v2 and Dancing Boids instead and runs the model on the CPU, built to be
// cheap there:
//  - the trail is 16-bit fixed point (4096 = density 1.0), the species
//    interleaved per cell so one sensor read is one cache line;
//  - positions are 16.16 fixed-point px, headings 32-bit fixed-point angles
//    (2^32 = one turn, so turning is an add that wraps by itself);
//  - the trail has a ghost border as wide as the longest sensor reach, filled
//    from the opposite edges after every step, so a sensor read is
//    trail[cell + delta[heading]] with the deltas precomputed per species: no
//    wrap, no float, no division and no branch in the agent loop. (The
//    in-order Cortex-A53/A55 cores of TV sticks have one multiplier and stall
//    on float<->int moves and flag chains; wrapping each sensor point cost
//    more than everything else in the loop together.);
//  - every 16 steps the agents are counting-sorted by 16 x 16 px tile, so
//    neighbouring agents are processed together (their sensor reads hit the
//    cache) and each worker thread keeps to its own part of the map (no cache
//    lines bouncing between cores on deposits);
//  - agents go through in batches (all sensor cells, then all reads, then the
//    turns), so an in-order core has independent loads to overlap;
//  - diffusion + decay is one integer multiply-add pass with running 3-wide row
//    sums (NEON-vectorised), and it writes the 8-bit picture through a tone
//    table, so the renderer uploads one small texture a step and draws one quad;
//  - agents and diffusion rows are split over a worker pool, and the screen
//    saver runs the steps on its own thread so Kodi's render thread never waits.
// Deposits from different threads may race (a lost deposit now and then); they
// use relaxed atomic loads and stores, which compile to plain loads and stores.
#pragma once

#include "Presets.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace physarum
{

constexpr int MAX_SPECIES = 3;
constexpr float kOne = 4096.0f; // trail units per density 1.0

// One behaviour in simulation units: angles in radians, distances in trail px,
// decay as the fraction kept per step, diffuse 0..1, deposit and repel 0..1.
struct Params
{
  float sa = 0, ra = 0, so = 0, ss = 0, decay = 0, diffuse = 0, deposit = 0, jitter = 0, repel = 0;
};

// px: trail width / 960 * pattern scale (the presets are tuned on 960 px).
inline Params FromDef(const PresetDef& d, float px)
{
  constexpr float DEG = 3.14159265f / 180.0f;
  Params p;
  p.sa = d.sa * DEG;
  p.ra = d.ra * DEG;
  p.so = std::max(1.0f, d.so * px);
  p.ss = std::max(0.05f, d.ss / 10.0f * px);
  p.decay = std::min(0.999f, std::max(0.5f, d.decay / 100.0f));
  p.diffuse = std::min(1.0f, std::max(0.0f, d.diffuse / 100.0f));
  p.deposit = std::max(0.01f, d.deposit / 100.0f);
  p.jitter = d.jitter * DEG;
  p.repel = std::min(1.0f, std::max(0.0f, d.repel / 100.0f));
  return p;
}

// Species 1 and 2 get a longer or shorter reach and other angles when the
// species are set to differ (as in the other Physarum add-ons).
inline Params ForSpecies(const Params& p, int i, bool differ)
{
  if (!differ || i <= 0)
    return p;
  static const float SO[3] = {1.0f, 1.6f, 0.65f};
  static const float SA[3] = {1.0f, 0.75f, 1.4f};
  static const float SS[3] = {1.0f, 1.3f, 0.8f};
  static const float RA[3] = {1.0f, 1.2f, 0.8f};
  i = std::min(2, i);
  Params q = p;
  q.so *= SO[i];
  q.sa = std::min(2.0f, q.sa * SA[i]);
  q.ss *= SS[i];
  q.ra = std::min(2.0f, q.ra * RA[i]);
  return q;
}

enum Start
{
  START_RANDOM,
  START_DISC,
  START_RING,
  START_COLONIES,
  START_BIG_BANG,
  START_THIRDS,
  START_COUNT
};

struct Agent
{
  int32_t x, y; // position, 16.16 fixed-point px, 0 <= x < w << 16
  uint32_t a;   // heading, 2^32 = one full turn
};

// v + d wrapped onto [0, size) without a branch, for |d| < size.
inline int32_t WrapAdd(int32_t v, int32_t d, int32_t size)
{
  v += d;
  v += (v >> 31) & size;            // went below 0
  v -= ((size - 1 - v) >> 31) & size; // reached size
  return v;
}

inline uint32_t XorShift(uint32_t& s)
{
  s ^= s << 13;
  s ^= s >> 17;
  s ^= s << 5;
  return s;
}

inline uint32_t Hash(uint32_t x)
{
  x ^= x >> 16;
  x *= 0x7feb352du;
  x ^= x >> 15;
  x *= 0x846ca68bu;
  x ^= x >> 16;
  return x ? x : 0x9e3779b9u;
}

class Simulation
{
public:
  Simulation() { SetTone(1.0f); }

  // Trail size, species (1..3) and agent count. Clears everything.
  void Configure(int w, int h, int species, size_t agents)
  {
    m_w = std::max(16, w);
    m_h = std::max(16, h);
    m_species = std::min(std::max(species, 1), MAX_SPECIES);
    m_agents.assign(std::max<size_t>(agents, 1), Agent{0, 0, 0});
    for (int s = 0; s <= m_species; s++)
      m_begin[s] = m_agents.size() * s / m_species;
    m_display.assign(static_cast<size_t>(m_w) * m_h * m_species, 0);
    m_pad = -1; // laid out by the next Spawn
    m_step = 0;
  }

  // The behaviour of species s; call after Configure and before Spawn.
  void SetParams(int s, const Params& p)
  {
    if (s < 0 || s >= m_species)
      return;
    constexpr double TURN = 4294967296.0 / 6.283185307179586; // radians -> angle units
    K& k = m_k[s];
    k.sa = static_cast<uint32_t>(static_cast<int64_t>(std::llround(p.sa * TURN)));
    k.ra = static_cast<uint32_t>(static_cast<int64_t>(std::llround(p.ra * TURN)));
    k.jitter = static_cast<uint32_t>(std::min(2147483647.0, std::max(0.0, p.jitter * TURN)));
    // Sensor reach and step stay under a quarter of the map (the ghost border
    // and the branch-free wrap rely on it; it is plenty).
    const float lim = 0.24f * std::min(m_w, m_h);
    k.so = std::min(p.so, lim);
    k.ss = std::min(p.ss, lim);
    k.repel = static_cast<int>(std::lround(std::min(1.0f, std::max(0.0f, p.repel)) * 256));

    // Deposit so the mean density settles near deposit/2 whatever the agent
    // count and trail size: d * agents_per_px / (1 - decay) = deposit / 2.
    const double perPx = static_cast<double>(m_begin[s + 1] - m_begin[s]) /
                         (static_cast<double>(m_w) * m_h);
    const double d = p.deposit * (1.0 - p.decay) * 0.5 / std::max(1e-4, perPx);
    k.deposit = static_cast<uint32_t>(std::min(65535.0, std::max(1.0, d * kOne)));
    if (s == 0)
    {
      // out = (v * keepOwn + sum9 * keepMean) >> 15, the 3x3 mean mixed in by
      // `diffuse`, all times `decay`. The two weights are a convex mix of v and
      // the mean scaled by 32768 * decay, so the sum stays under 2^31.
      const double dec = std::min(0.9995f, std::max(0.5f, p.decay));
      const double dif = std::min(1.0f, std::max(0.0f, p.diffuse));
      m_keepOwn = static_cast<uint32_t>(std::floor(32768.0 * dec * (1.0 - dif)));
      m_keepMean = static_cast<uint32_t>(std::floor(32768.0 * dec * dif / 9.0));
    }
  }

  // Tone curve for the picture: 255 * (1 - exp(-density * 2.5 * gain)).
  void SetTone(float gain)
  {
    for (int i = 0; i < kToneSize; i++)
    {
      const double density = i * 16.0 / kOne;
      m_tone[i] = static_cast<uint8_t>(std::lround(255.0 * (1.0 - std::exp(-density * 2.5 * gain))));
    }
  }

  // Place the agents and clear the trail (laid out for the current params).
  void Spawn(int start, uint32_t seed)
  {
    Layout();
    uint32_t r = Hash(seed);
    auto uni = [&r]() { return (XorShift(r) >> 8) * (1.0f / 16777216.0f); };
    const float W = static_cast<float>(m_w), H = static_cast<float>(m_h);
    const float cx = W * 0.5f, cy = H * 0.5f;
    constexpr float TAU = 6.2831853f;
    constexpr double TURN = 4294967296.0 / 6.283185307179586;
    auto angle = [&](float rad) {
      return static_cast<uint32_t>(static_cast<int64_t>(std::llround(rad * TURN)));
    };

    float colonies[12][2];
    const int numColonies = 5 + static_cast<int>(uni() * 6);
    for (int c = 0; c < numColonies; c++)
    {
      colonies[c][0] = (0.1f + 0.8f * uni()) * W;
      colonies[c][1] = (0.1f + 0.8f * uni()) * H;
    }

    for (int s = 0; s < m_species; s++)
      for (size_t i = m_begin[s]; i < m_begin[s + 1]; i++)
      {
        Agent& g = m_agents[i];
        float x, y, a = uni() * TAU;
        switch (start)
        {
          case START_DISC:
          {
            const float rr = 0.22f * H * std::sqrt(uni()), t = uni() * TAU;
            x = cx + rr * std::cos(t);
            y = cy + rr * std::sin(t);
            break;
          }
          case START_RING:
          {
            const float rr = (0.36f + 0.02f * uni()) * H, t = uni() * TAU;
            x = cx + rr * std::cos(t);
            y = cy + rr * std::sin(t);
            a = t + 3.14159265f; // facing the centre
            break;
          }
          case START_COLONIES:
          {
            const int c = std::min(numColonies - 1, static_cast<int>(uni() * numColonies));
            const float rr = 0.05f * H * std::sqrt(uni()), t = uni() * TAU;
            x = colonies[c][0] + rr * std::cos(t);
            y = colonies[c][1] + rr * std::sin(t);
            break;
          }
          case START_BIG_BANG:
          {
            const float rr = 2.0f * uni(), t = uni() * TAU;
            x = cx + rr * std::cos(t);
            y = cy + rr * std::sin(t);
            a = t; // facing out
            break;
          }
          case START_THIRDS:
            x = (s + uni()) * W / m_species;
            y = uni() * H;
            break;
          default:
            x = uni() * W;
            y = uni() * H;
            break;
        }
        g.x = std::min(static_cast<int32_t>(Wrap(x, W) * 65536.0f), (m_w << 16) - 1);
        g.y = std::min(static_cast<int32_t>(Wrap(y, H) * 65536.0f), (m_h << 16) - 1);
        g.a = angle(a);
      }
    SortAgents();
    std::fill(m_trail.begin(), m_trail.end(), 0);
    std::fill(m_next.begin(), m_next.end(), 0);
    std::fill(m_display.begin(), m_display.end(), 0);
  }

  // --- one step = MoveAgents over [0, agents) then DiffuseRows over [0, h)
  // then EndStep(); each range call may run on its own thread.

  void MoveAgents(size_t lo, size_t hi)
  {
    for (int s = 0; s < m_species; s++)
    {
      const size_t a = std::max(lo, m_begin[s]), b = std::min(hi, m_begin[s + 1]);
      if (a >= b)
        continue;
      uint32_t rng = Hash(static_cast<uint32_t>(m_step * 2654435761u) ^ static_cast<uint32_t>(a * 40503u) ^
                          static_cast<uint32_t>(s));
      switch (m_species)
      {
        case 1: Move<1>(a, b, s, rng); break;
        case 2: Move<2>(a, b, s, rng); break;
        default: Move<3>(a, b, s, rng); break;
      }
    }
  }

  void DiffuseRows(size_t y0, size_t y1)
  {
    const int n = m_w * m_species; // values per row (the interior only)
    thread_local std::vector<uint32_t> scratch;
    scratch.resize(static_cast<size_t>(n) * 3);
    uint32_t* rows[3] = {scratch.data(), scratch.data() + n, scratch.data() + 2 * n};
    const int S = m_species;
    const uint16_t* T = m_trail.data() + m_origin;
    const size_t rowStride = static_cast<size_t>(m_stride) * S;

    // Wraps at the map edges itself (the ghost cells hold last step's values,
    // without this step's deposits).
    auto hsum = [&](int y, uint32_t* out) {
      const uint16_t* r = T + static_cast<size_t>(y) * rowStride;
      // first and last cell wrap around the row
      for (int i = 0; i < S; i++)
      {
        out[i] = r[n - S + i] + r[i] + r[i + S];
        out[n - S + i] = r[n - 2 * S + i] + r[n - S + i] + r[i];
      }
      for (int i = S; i < n - S; i++)
        out[i] = static_cast<uint32_t>(r[i - S]) + r[i] + r[i + S];
    };

    const int h = m_h;
    int y = static_cast<int>(y0);
    hsum(y == 0 ? h - 1 : y - 1, rows[0]);
    hsum(y, rows[1]);
    const uint32_t keepOwn = m_keepOwn, keepMean = m_keepMean;
    for (; y < static_cast<int>(y1); y++)
    {
      hsum(y + 1 == h ? 0 : y + 1, rows[2]);
      const uint32_t *a = rows[0], *b = rows[1], *c = rows[2];
      const uint16_t* cur = T + static_cast<size_t>(y) * rowStride;
      uint16_t* out = m_next.data() + m_origin + static_cast<size_t>(y) * rowStride;
      uint8_t* disp = m_display.data() + static_cast<size_t>(y) * n;
      // two passes: the first is lane-wise integer maths (NEON), the second
      // the table lookup that cannot be vectorised
      for (int i = 0; i < n; i++)
        out[i] = static_cast<uint16_t>((cur[i] * keepOwn + (a[i] + b[i] + c[i]) * keepMean) >> 15);
      const uint8_t* tone = m_tone;
      for (int i = 0; i < n; i++)
        disp[i] = tone[out[i] >> 4];
      uint32_t* t = rows[0];
      rows[0] = rows[1];
      rows[1] = rows[2];
      rows[2] = t;
    }
  }

  void EndStep()
  {
    FillGhosts(m_next);
    m_trail.swap(m_next);
    m_step++;
    if (m_step % kSortEvery == 0)
      SortAgents();
  }

  // Counting sort of each species' agents by 16 x 16 px tile, row by row.
  void SortAgents()
  {
    const int tilesX = (m_w + 15) >> 4, tilesY = (m_h + 15) >> 4;
    const size_t tiles = static_cast<size_t>(tilesX) * tilesY;
    m_count.assign(tiles + 1, 0);
    m_key.resize(m_agents.size());
    m_sorted.resize(m_agents.size());
    for (int s = 0; s < m_species; s++)
    {
      const size_t a = m_begin[s], b = m_begin[s + 1];
      std::fill(m_count.begin(), m_count.end(), 0);
      for (size_t i = a; i < b; i++)
      {
        const uint32_t key = static_cast<uint32_t>((m_agents[i].y >> 20) * tilesX + (m_agents[i].x >> 20));
        m_key[i] = key;
        m_count[key + 1]++;
      }
      for (size_t t = 0; t < tiles; t++)
        m_count[t + 1] += m_count[t];
      for (size_t i = a; i < b; i++)
        m_sorted[a + m_count[m_key[i]]++] = m_agents[i];
    }
    m_agents.swap(m_sorted);
  }

  // Single-threaded step, for tests.
  void Step()
  {
    MoveAgents(0, m_agents.size());
    DiffuseRows(0, m_h);
    EndStep();
  }

  int width() const { return m_w; }
  int height() const { return m_h; }
  int species() const { return m_species; }
  size_t agents() const { return m_agents.size(); }
  uint32_t steps() const { return m_step; }
  // The picture of the last step: w * h cells of `species` bytes, top row first.
  const uint8_t* display() const { return m_display.data(); }
  const std::vector<uint16_t>& trail() const { return m_trail; }
  const std::vector<Agent>& agentList() const { return m_agents; }
  // An agent's position in trail px.
  float AgentX(size_t i) const { return m_agents[i].x / 65536.0f; }
  float AgentY(size_t i) const { return m_agents[i].y / 65536.0f; }

private:
  static constexpr int kSortEvery = 16;
  static constexpr int kDirBits = 9;
  static constexpr int kDirs = 1 << kDirBits;
  static constexpr int kToneSize = 4096; // indexed by trail >> 4

  struct Dir
  {
    int32_t sensor; // sensor cell - own cell, in trail values
    int32_t mx, my; // step, 16.16 px
    int32_t unused;
  };
  struct K
  {
    uint32_t sa = 0, ra = 0, jitter = 0, deposit = 1;
    float so = 1, ss = 1;
    int repel = 128; // 0..256
  };

  // Size the ghost border for the longest sensor reach, allocate the trail
  // and fill the direction tables.
  void Layout()
  {
    float reach = 1;
    for (int s = 0; s < m_species; s++)
      reach = std::max(reach, m_k[s].so);
    const int pad = static_cast<int>(std::ceil(reach)) + 1;
    if (pad != m_pad)
    {
      m_pad = pad;
      m_stride = m_w + 2 * pad;
      const size_t cells = static_cast<size_t>(m_stride) * (m_h + 2 * pad) * m_species;
      m_trail.assign(cells, 0);
      m_next.assign(cells, 0);
      m_origin = (static_cast<size_t>(pad) * m_stride + pad) * m_species;
    }
    for (int s = 0; s < m_species; s++)
      for (int i = 0; i < kDirs; i++)
      {
        const double t = 6.283185307179586 * (i + 0.5) / kDirs;
        const double c = std::cos(t), sn = std::sin(t);
        Dir& d = m_dirs[s][i];
        const int dx = static_cast<int>(std::lround(c * m_k[s].so));
        const int dy = static_cast<int>(std::lround(sn * m_k[s].so));
        d.sensor = (dy * m_stride + dx) * m_species;
        d.mx = static_cast<int32_t>(std::lround(c * m_k[s].ss * 65536.0));
        d.my = static_cast<int32_t>(std::lround(sn * m_k[s].ss * 65536.0));
        d.unused = 0;
      }
  }

  // Copy the opposite edges into the ghost border of `t`.
  void FillGhosts(std::vector<uint16_t>& t) const
  {
    const int S = m_species, P = m_pad, W = m_w, H = m_h;
    const size_t row = static_cast<size_t>(m_stride) * S;
    uint16_t* base = t.data();
    for (int y = P; y < P + H; y++)
    {
      uint16_t* r = base + y * row;
      std::copy(r + W * S, r + (W + P) * S, r);              // left <- right edge
      std::copy(r + P * S, r + 2 * P * S, r + (W + P) * S);  // right <- left edge
    }
    for (int y = 0; y < P; y++)
    {
      std::copy(base + (y + H) * row, base + (y + H + 1) * row, base + y * row);         // top
      std::copy(base + (y + P) * row, base + (y + P + 1) * row, base + (y + P + H) * row); // bottom
    }
  }

  static float Wrap(float v, float size)
  {
    v -= std::floor(v / size) * size;
    return v >= size ? 0.0f : v;
  }

  static uint16_t Load(const uint16_t* p) { return __atomic_load_n(p, __ATOMIC_RELAXED); }
  static void Store(uint16_t* p, uint16_t v) { __atomic_store_n(p, v, __ATOMIC_RELAXED); }

  // What species s smells at the cell starting at value c: its own trail minus
  // the others' (x repel).
  template <int S>
  static inline int Smell(const uint16_t* T, int c, int s, int repel)
  {
    if (S == 1)
      return Load(T + c);
    const uint16_t* p = T + c;
    int own = 0, others = 0;
    for (int i = 0; i < S; i++)
    {
      const int v = Load(p + i);
      if (i == s)
        own = v;
      else
        others += v;
    }
    return own * 256 - others * repel;
  }

  // Agents go through in batches of kBatch, in three passes: work out every
  // sensor cell, read them all, then turn, step and deposit. An in-order core
  // (Cortex-A53/A55) keeps issuing past a load until something uses its
  // result, so a batch has 3 x kBatch reads in flight instead of stalling on
  // each one in turn; that alone halves the loop's time on a Fire TV stick.
  static constexpr int kBatch = 8;

  template <int S>
  void Move(size_t lo, size_t hi, int s, uint32_t& rngRef)
  {
    const K k = m_k[s];
    const int32_t W = m_w << 16, H = m_h << 16;
    const int rowValues = m_stride * S;
    uint16_t* const T = m_trail.data() + m_origin; // cell (0, 0) of the interior
    Agent* const agents = m_agents.data();
    const Dir* const dirs = m_dirs[s];
    constexpr int SH = 32 - kDirBits;
    const uint64_t jitterSpan = static_cast<uint64_t>(k.jitter) * 2 + 1;
    const uint32_t left = k.ra, right = 0u - k.ra;
    uint32_t rng = rngRef;
    auto cell = [rowValues](int32_t x, int32_t y) { return (y >> 16) * rowValues + (x >> 16) * S; };

    int cf[kBatch], cl[kBatch], cr[kBatch];
    int vf[kBatch], vl[kBatch], vr[kBatch];
    for (size_t b = lo; b < hi; b += kBatch)
    {
      const int n = static_cast<int>(std::min<size_t>(kBatch, hi - b));
      Agent* const g = agents + b;

      for (int j = 0; j < n; j++)
      {
        const uint32_t a = g[j].a;
        const int c = cell(g[j].x, g[j].y);
        cf[j] = c + dirs[a >> SH].sensor;
        cl[j] = c + dirs[(a + k.sa) >> SH].sensor;
        cr[j] = c + dirs[(a - k.sa) >> SH].sensor;
      }
      for (int j = 0; j < n; j++)
      {
        vf[j] = Smell<S>(T, cf[j], s, k.repel);
        vl[j] = Smell<S>(T, cl[j], s, k.repel);
        vr[j] = Smell<S>(T, cr[j], s, k.repel);
      }
      for (int j = 0; j < n; j++)
      {
        // Jones's rule, branch-free (the branches are close to random, so a
        // mispredict per agent would cost more than the whole decision):
        // ahead strongest -> straight; ahead weakest -> left or right at
        // random; otherwise towards the stronger side; all equal -> straight.
        const int F = vf[j], L = vl[j], R = vr[j];
        const uint32_t coin = (XorShift(rng) & 1u) ? left : right;
        uint32_t turn = L > R ? left : (R > L ? right : 0u);
        turn = (F < L && F < R) ? coin : turn;
        turn = (F > L && F > R) ? 0u : turn;
        uint32_t a = g[j].a + turn;
        if (k.jitter)
          a += static_cast<uint32_t>((static_cast<uint64_t>(XorShift(rng)) * jitterSpan) >> 32) - k.jitter;

        // step forward, wrapping around the map
        const Dir& m = dirs[a >> SH];
        const int32_t x = WrapAdd(g[j].x, m.mx, W), y = WrapAdd(g[j].y, m.my, H);
        g[j] = Agent{x, y, a};
        cf[j] = cell(x, y) + s;
      }
      for (int j = 0; j < n; j++) // deposit
      {
        uint16_t* p = T + cf[j];
        const uint32_t v = Load(p) + k.deposit;
        Store(p, static_cast<uint16_t>(v > 65535u ? 65535u : v));
      }
    }
    rngRef = rng;
  }

  int m_w = 16, m_h = 16, m_species = 1;
  int m_pad = -1, m_stride = 16; // ghost border, cells per trail row (with the border)
  size_t m_origin = 0;           // value index of interior cell (0, 0)
  std::vector<Agent> m_agents, m_sorted;
  std::vector<uint32_t> m_key, m_count;
  size_t m_begin[MAX_SPECIES + 1] = {};
  std::vector<uint16_t> m_trail, m_next;
  std::vector<uint8_t> m_display;
  K m_k[MAX_SPECIES];
  uint32_t m_keepOwn = 0, m_keepMean = 3276; // decay 0.9, full diffusion
  uint32_t m_step = 0;
  Dir m_dirs[MAX_SPECIES][kDirs];
  uint8_t m_tone[kToneSize];
};

} // namespace physarum

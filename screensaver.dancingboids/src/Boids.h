// Dancing Boids simulation core - no Kodi / OpenGL dependencies.
//
// Craig Reynolds' boids (separation, alignment, cohesion), as in the netlight
// "Dancing Boids" macOS screensaver, with the same performance recipe as
// Particle Life v2 and a few more tricks for small ARM boxes:
//
//  - structure-of-arrays state, no per-boid allocation;
//  - a uniform grid rebuilt every step by counting sort, with the boid data
//    itself (not just an index) permuted into cell order, so the neighbour
//    loop walks memory linearly;
//  - a synchronous update (read the sorted "current" arrays, write the "next"
//    arrays), so the neighbour loop has no data races and can be split over
//    worker threads with results identical to the single-threaded run;
//  - no sqrt in the neighbour loop: separation weights by 1/d^2 and the blind
//    spot test is done on squared terms;
//  - a cap on the neighbours each boid listens to (real starlings follow ~7),
//    which bounds the worst case when a flock packs tight.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <random>
#include <vector>

namespace boids
{

constexpr int MAX_SPECIES = 4;
constexpr int MAX_PREDATORS = 4;

// The 8 cells around the centre (4) of a 3x3 block, clockwise.
constexpr int kRing[8] = {0, 1, 2, 5, 8, 7, 6, 3};

enum Edges { EDGES_TURN = 0, EDGES_WRAP = 1 };

struct Params
{
  int count = 2000;
  int species = 1;              // flocks that align / cohere only with their own kind
  float maxSpeed = 3.4f;        // world units per step (the world is 1000 units high)
  float minSpeed = 1.6f;
  float maxForce = 0.075f;      // steering limit per step
  float vision = 55.0f;         // alignment / cohesion radius
  float separation = 24.0f;     // separation radius
  float sepWeight = 1.8f;
  float alignWeight = 1.0f;
  float cohWeight = 0.9f;
  int maxNeighbours = 32;       // 0 = no cap
  bool blindSpot = true;        // ignore boids in the ~100 degrees behind
  int edges = EDGES_TURN;
  float margin = 90.0f;         // EDGES_TURN: distance at which boids start to turn
  float turn = 0.22f;           // EDGES_TURN: turning acceleration at the wall
  float leadWeight = 0.0f;      // pull towards the wandering lead point (0 = off)
  float leadRate = 0.0022f;     // lead point phase per step
  int predators = 0;
  float fearRadius = 130.0f;
  float fearWeight = 3.0f;
};

struct Predator
{
  float x = 0, y = 0, vx = 0, vy = 0;
  int target = -1;              // boid id it is chasing
  int retarget = 0;             // steps until it picks a new one
};

class Simulation
{
public:
  explicit Simulation(uint32_t seed = std::random_device{}()) : m_rng(seed) {}

  Params params;

  void Resize(float w, float h)
  {
    m_w = std::max(w, 1.0f);
    m_h = std::max(h, 1.0f);
  }
  float width() const { return m_w; }
  float height() const { return m_h; }

  size_t size() const { return m_x.size(); }
  const float* x() const { return m_x.data(); }
  const float* y() const { return m_y.data(); }
  const float* vx() const { return m_vx.data(); }
  const float* vy() const { return m_vy.data(); }
  const uint8_t* species() const { return m_sp.data(); }
  const uint32_t* tint() const { return m_tint.data(); }
  const uint32_t* id() const { return m_id.data(); }
  const Predator* predators() const { return m_pred; }
  int numPredators() const { return m_numPred; }
  float leadX() const { return m_leadX; }
  float leadY() const { return m_leadY; }

  // Respawn the flock: a few loose clusters with a shared heading each, so the
  // screen opens on flocks already forming rather than on uniform noise.
  // `tintFn(rng, species)` gives each boid its fixed RGBA colour.
  template<typename TintFn>
  void Restart(TintFn tintFn)
  {
    const size_t n = static_cast<size_t>(std::max(0, params.count));
    for (auto* v : {&m_x, &m_y, &m_vx, &m_vy, &m_nx, &m_ny, &m_nvx, &m_nvy})
      v->resize(n);
    m_sp.resize(n);
    m_nsp.resize(n);
    m_tint.resize(n);
    m_ntint.resize(n);
    m_id.resize(n);
    m_nid.resize(n);

    const int numSpecies = std::min(std::max(params.species, 1), MAX_SPECIES);
    const int clusters = 3 + RandomInt(0, 4);
    float cx[8], cy[8], ch[8];
    for (int c = 0; c < clusters; c++)
    {
      cx[c] = RandomFloat(0.15f, 0.85f) * m_w;
      cy[c] = RandomFloat(0.15f, 0.85f) * m_h;
      ch[c] = RandomFloat(0, 6.2831853f);
    }
    std::normal_distribution<float> spread(0.0f, 0.08f * m_h);
    for (size_t i = 0; i < n; i++)
    {
      const int c = RandomInt(0, clusters - 1);
      m_x[i] = Wrap(cx[c] + spread(m_rng), m_w);
      m_y[i] = Wrap(cy[c] + spread(m_rng), m_h);
      const float a = ch[c] + RandomFloat(-0.6f, 0.6f);
      const float s = RandomFloat(params.minSpeed, params.maxSpeed);
      m_vx[i] = std::cos(a) * s;
      m_vy[i] = std::sin(a) * s;
      m_sp[i] = static_cast<uint8_t>(i % numSpecies);
      m_tint[i] = tintFn(m_rng, m_sp[i]);
      m_id[i] = static_cast<uint32_t>(i);
    }

    m_numPred = std::min(std::max(params.predators, 0), MAX_PREDATORS);
    for (int p = 0; p < m_numPred; p++)
    {
      Predator& q = m_pred[p];
      q.x = RandomFloat(0, m_w);
      q.y = RandomFloat(0, m_h);
      const float a = RandomFloat(0, 6.2831853f);
      q.vx = std::cos(a) * params.maxSpeed;
      q.vy = std::sin(a) * params.maxSpeed;
      q.target = -1;
      q.retarget = 0;
    }
    m_leadPhase = RandomFloat(0, 100);
    m_leadFx = RandomFloat(0.6f, 1.0f);
    m_leadFy = RandomFloat(0.9f, 1.4f);
    m_steps = 0;
    m_where.clear();
    UpdateLead();
  }

  // Phase 1 of a step (single-threaded, O(N)): move the lead point and the
  // predators, then counting-sort the boids into grid cells, permuting their
  // data into the "current" arrays in cell order.
  void BeginStep()
  {
    m_steps++;
    UpdateLead();
    UpdatePredators();
    BuildGrid();
  }

  // Phase 2: update boids [begin, end) of the sorted order. Reads only the
  // current arrays and writes only the next arrays, so disjoint ranges can run
  // on different threads.
  void UpdateRange(size_t begin, size_t end)
  {
    const Params& p = params;
    const float vis2 = p.vision * p.vision;
    const float sep2 = p.separation * p.separation;
    const int cap = p.maxNeighbours > 0 ? p.maxNeighbours : 1 << 30;
    const bool wrap = p.edges == EDGES_WRAP && m_cellsX >= 3 && m_cellsY >= 3;
    const float halfW = 0.5f * m_w, halfH = 0.5f * m_h;
    const float fear2 = p.fearRadius * p.fearRadius;

    const float* __restrict X = m_x.data();
    const float* __restrict Y = m_y.data();
    const float* __restrict VX = m_vx.data();
    const float* __restrict VY = m_vy.data();
    const uint8_t* __restrict SP = m_sp.data();
    const int* __restrict start = m_cellStart.data();

    for (size_t i = begin; i < end; i++)
    {
      const float px = X[i], py = Y[i];
      const float vx = VX[i], vy = VY[i];
      const uint8_t sp = SP[i];
      const float v2 = vx * vx + vy * vy;
      const int cx = CellX(px), cy = CellY(py);

      float sepX = 0, sepY = 0, aliX = 0, aliY = 0, cohX = 0, cohY = 0;
      int sepN = 0, flockN = 0, heard = 0;

      // Own cell first (the nearest boids are most likely there), then the
      // eight around it in an order rotated per boid: with the neighbour cap,
      // a fixed order would make every boid listen mostly to the boids up and
      // to the left, and the whole flock would drift into that corner.
      const int rot = static_cast<int>(i & 7);
      for (int t = 0; t < 9 && heard < cap; t++)
      {
        const int o = t == 0 ? 4 : kRing[(t - 1 + rot) & 7];
        int ry = cy + o / 3 - 1;
        int rx = cx + o % 3 - 1;
        if (wrap)
        {
          ry = ry < 0 ? ry + m_cellsY : (ry >= m_cellsY ? ry - m_cellsY : ry);
          rx = rx < 0 ? rx + m_cellsX : (rx >= m_cellsX ? rx - m_cellsX : rx);
        }
        else if (ry < 0 || ry >= m_cellsY || rx < 0 || rx >= m_cellsX)
          continue;
        {
          const int c = ry * m_cellsX + rx;
          const int kEnd = start[c + 1];
          for (int k = start[c]; k < kEnd; k++)
          {
            float dx = X[k] - px;
            float dy = Y[k] - py;
            if (wrap)
            {
              dx = dx > halfW ? dx - m_w : (dx < -halfW ? dx + m_w : dx);
              dy = dy > halfH ? dy - m_h : (dy < -halfH ? dy + m_h : dy);
            }
            const float d2 = dx * dx + dy * dy;
            if (d2 >= vis2 || d2 <= 1e-6f)
              continue;
            // blind spot: the neighbour is behind (dot < 0) and outside a
            // +-130 degree cone, i.e. dot^2 > cos^2(130) * |v|^2 * d^2
            if (p.blindSpot)
            {
              const float dot = dx * vx + dy * vy;
              if (dot < 0.0f && dot * dot > 0.413f * v2 * d2)
                continue;
            }
            if (d2 < sep2)
            {
              const float inv = 1.0f / d2;
              sepX -= dx * inv;
              sepY -= dy * inv;
              sepN++;
            }
            if (SP[k] == sp)
            {
              aliX += VX[k];
              aliY += VY[k];
              cohX += dx;
              cohY += dy;
              flockN++;
            }
            if (++heard >= cap)
              break;
          }
        }
      }

      float ax = 0, ay = 0;
      if (sepN > 0)
        Steer(sepX, sepY, vx, vy, p.sepWeight, ax, ay);
      if (flockN > 0)
      {
        Steer(aliX, aliY, vx, vy, p.alignWeight, ax, ay);
        Steer(cohX, cohY, vx, vy, p.cohWeight, ax, ay);
      }

      if (p.leadWeight > 0.0f)
      {
        float dx = m_leadX - px, dy = m_leadY - py;
        if (wrap)
        {
          dx = dx > halfW ? dx - m_w : (dx < -halfW ? dx + m_w : dx);
          dy = dy > halfH ? dy - m_h : (dy < -halfH ? dy + m_h : dy);
        }
        Steer(dx, dy, vx, vy, p.leadWeight, ax, ay);
      }

      for (int q = 0; q < m_numPred; q++)
      {
        float dx = px - m_pred[q].x, dy = py - m_pred[q].y;
        if (wrap)
        {
          dx = dx > halfW ? dx - m_w : (dx < -halfW ? dx + m_w : dx);
          dy = dy > halfH ? dy - m_h : (dy < -halfH ? dy + m_h : dy);
        }
        const float d2 = dx * dx + dy * dy;
        if (d2 < fear2 && d2 > 1e-6f)
        {
          // flee harder the closer it is; this is what makes the flock split
          // and swirl around the hawk
          const float w = p.fearWeight * (1.0f - d2 / fear2);
          Steer(dx, dy, vx, vy, w, ax, ay);
        }
      }

      float nvx = vx + ax, nvy = vy + ay;

      if (!wrap)
      {
        const float m = p.margin;
        if (px < m)
          nvx += p.turn * (1.0f - px / m);
        else if (px > m_w - m)
          nvx -= p.turn * (1.0f - (m_w - px) / m);
        if (py < m)
          nvy += p.turn * (1.0f - py / m);
        else if (py > m_h - m)
          nvy -= p.turn * (1.0f - (m_h - py) / m);
      }

      const float s2 = nvx * nvx + nvy * nvy;
      if (s2 > p.maxSpeed * p.maxSpeed)
      {
        const float k = p.maxSpeed / std::sqrt(s2);
        nvx *= k;
        nvy *= k;
      }
      else if (s2 < p.minSpeed * p.minSpeed)
      {
        const float k = s2 > 1e-8f ? p.minSpeed / std::sqrt(s2) : 0.0f;
        nvx = s2 > 1e-8f ? nvx * k : p.minSpeed;
        nvy *= k;
      }

      float nx = px + nvx, ny = py + nvy;
      if (wrap || p.edges == EDGES_WRAP)
      {
        nx = Wrap(nx, m_w);
        ny = Wrap(ny, m_h);
      }
      else
      {
        nx = std::min(std::max(nx, 0.0f), m_w);
        ny = std::min(std::max(ny, 0.0f), m_h);
      }
      m_nx[i] = nx;
      m_ny[i] = ny;
      m_nvx[i] = nvx;
      m_nvy[i] = nvy;
    }
  }

  // Phase 3: the next arrays become the current ones.
  void EndStep()
  {
    m_x.swap(m_nx);
    m_y.swap(m_ny);
    m_vx.swap(m_nvx);
    m_vy.swap(m_nvy);
  }

  // A whole step on the calling thread.
  void Step()
  {
    BeginStep();
    UpdateRange(0, size());
    EndStep();
  }

  float RandomFloat(float a, float b) { return std::uniform_real_distribution<float>(a, b)(m_rng); }
  int RandomInt(int lo, int hi) { return std::uniform_int_distribution<int>(lo, hi)(m_rng); }
  std::mt19937& rng() { return m_rng; }

private:
  // Reynolds steering: turn towards `dir` at full speed, limited to maxForce,
  // scaled by `w`. One sqrt per rule per boid; none per neighbour.
  void Steer(float dx, float dy, float vx, float vy, float w, float& ax, float& ay) const
  {
    const float d2 = dx * dx + dy * dy;
    if (d2 < 1e-12f)
      return;
    const float k = params.maxSpeed / std::sqrt(d2);
    float sx = dx * k - vx, sy = dy * k - vy;
    const float s2 = sx * sx + sy * sy;
    const float mf = params.maxForce;
    if (s2 > mf * mf)
    {
      const float r = mf / std::sqrt(s2);
      sx *= r;
      sy *= r;
    }
    ax += sx * w;
    ay += sy * w;
  }

  static float Wrap(float v, float m)
  {
    if (v < 0.0f)
      v += m;
    else if (v >= m)
      v -= m;
    return std::min(std::max(v, 0.0f), std::nextafter(m, 0.0f));
  }

  // The lead point traces a slow Lissajous figure: a flock that follows it
  // swoops in loops and figure eights instead of drifting into a corner.
  void UpdateLead()
  {
    const float t = m_leadPhase + static_cast<float>(m_steps) * params.leadRate;
    m_leadX = (0.5f + 0.30f * std::sin(t * m_leadFx)) * m_w;
    m_leadY = (0.5f + 0.28f * std::sin(t * m_leadFy + 1.3f)) * m_h;
  }

  void UpdatePredators()
  {
    const size_t n = size();
    const float maxS = params.maxSpeed * 1.12f;
    const float maxF = params.maxForce * 1.4f;
    for (int q = 0; q < m_numPred; q++)
    {
      Predator& pr = m_pred[q];
      if (--pr.retarget <= 0 || pr.target < 0 || static_cast<size_t>(pr.target) >= n)
      {
        pr.target = n ? RandomInt(0, static_cast<int>(n) - 1) : -1;
        pr.retarget = 240 + RandomInt(0, 360);
      }
      float ax = 0, ay = 0;
      if (pr.target >= 0)
      {
        // targets are boid ids; m_where maps an id to its sorted slot
        const size_t at = m_where.size() == n ? m_where[pr.target] : static_cast<size_t>(pr.target);
        float dx = m_x[at] - pr.x, dy = m_y[at] - pr.y;
        if (params.edges == EDGES_WRAP)
        {
          dx = dx > 0.5f * m_w ? dx - m_w : (dx < -0.5f * m_w ? dx + m_w : dx);
          dy = dy > 0.5f * m_h ? dy - m_h : (dy < -0.5f * m_h ? dy + m_h : dy);
        }
        const float d = std::sqrt(dx * dx + dy * dy);
        if (d > 1e-3f)
        {
          ax = dx / d * maxS - pr.vx;
          ay = dy / d * maxS - pr.vy;
          const float a = std::sqrt(ax * ax + ay * ay);
          if (a > maxF)
          {
            ax *= maxF / a;
            ay *= maxF / a;
          }
        }
      }
      pr.vx += ax;
      pr.vy += ay;
      if (params.edges != EDGES_WRAP)
      {
        const float m = params.margin;
        const float t = params.turn;
        if (pr.x < m) pr.vx += t * (1.0f - pr.x / m);
        else if (pr.x > m_w - m) pr.vx -= t * (1.0f - (m_w - pr.x) / m);
        if (pr.y < m) pr.vy += t * (1.0f - pr.y / m);
        else if (pr.y > m_h - m) pr.vy -= t * (1.0f - (m_h - pr.y) / m);
      }
      const float s = std::sqrt(pr.vx * pr.vx + pr.vy * pr.vy);
      if (s > maxS)
      {
        pr.vx *= maxS / s;
        pr.vy *= maxS / s;
      }
      pr.x += pr.vx;
      pr.y += pr.vy;
      if (params.edges == EDGES_WRAP)
      {
        pr.x = Wrap(pr.x, m_w);
        pr.y = Wrap(pr.y, m_h);
      }
      else
      {
        pr.x = std::min(std::max(pr.x, 0.0f), m_w);
        pr.y = std::min(std::max(pr.y, 0.0f), m_h);
      }
    }
  }

  void BuildGrid()
  {
    const size_t n = size();
    // Cells at least `vision` wide, so a 3x3 block covers the whole radius.
    // In wrap mode the cell count must divide the world exactly for the
    // wrapped neighbour cells to line up, so the cells grow a little instead.
    const float r = std::max(params.vision, 1.0f);
    m_cellsX = std::max(1, static_cast<int>(m_w / r));
    m_cellsY = std::max(1, static_cast<int>(m_h / r));
    m_invCellX = m_cellsX / m_w;
    m_invCellY = m_cellsY / m_h;
    const size_t numCells = static_cast<size_t>(m_cellsX) * m_cellsY;

    m_cellStart.assign(numCells + 1, 0);
    m_cellOf.resize(n);
    for (size_t j = 0; j < n; j++)
    {
      const int c = CellY(m_y[j]) * m_cellsX + CellX(m_x[j]);
      m_cellOf[j] = c;
      m_cellStart[c + 1]++;
    }
    for (size_t c = 0; c < numCells; c++)
      m_cellStart[c + 1] += m_cellStart[c];

    m_fill.assign(m_cellStart.begin(), m_cellStart.end() - 1);
    m_where.resize(n);
    for (size_t j = 0; j < n; j++)
    {
      const int to = m_fill[m_cellOf[j]]++;
      m_nx[to] = m_x[j];
      m_ny[to] = m_y[j];
      m_nvx[to] = m_vx[j];
      m_nvy[to] = m_vy[j];
      m_nsp[to] = m_sp[j];
      m_ntint[to] = m_tint[j];
      m_nid[to] = m_id[j];
      m_where[m_id[j]] = to;
    }
    m_x.swap(m_nx);
    m_y.swap(m_ny);
    m_vx.swap(m_nvx);
    m_vy.swap(m_nvy);
    m_sp.swap(m_nsp);
    m_tint.swap(m_ntint);
    m_id.swap(m_nid);
  }

  int CellX(float x) const
  {
    return std::min(std::max(static_cast<int>(x * m_invCellX), 0), m_cellsX - 1);
  }
  int CellY(float y) const
  {
    return std::min(std::max(static_cast<int>(y * m_invCellY), 0), m_cellsY - 1);
  }

  std::mt19937 m_rng;
  float m_w = 1778, m_h = 1000;

  // current (sorted) and next state
  std::vector<float> m_x, m_y, m_vx, m_vy, m_nx, m_ny, m_nvx, m_nvy;
  std::vector<uint8_t> m_sp, m_nsp;
  std::vector<uint32_t> m_tint, m_ntint, m_id, m_nid;

  Predator m_pred[MAX_PREDATORS];
  int m_numPred = 0;

  float m_leadX = 0, m_leadY = 0, m_leadPhase = 0, m_leadFx = 1, m_leadFy = 1;
  uint64_t m_steps = 0;

  int m_cellsX = 1, m_cellsY = 1;
  float m_invCellX = 1, m_invCellY = 1;
  std::vector<int> m_cellStart, m_cellOf, m_fill;
  std::vector<uint32_t> m_where;
};

} // namespace boids

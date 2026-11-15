// One creature in its own private world for one trial (Section 7 and 8 of
// EvolveLife.md): headless and deterministic, so the same genome and world
// replay the same run on the stage that it had in evaluation.
//
// Physics is position-based (Verlet integration, constraint iterations), in
// place of Box2D: a creature is at most 17 point masses and 16 rods, which a
// handful of iterations keeps stiff and stable on any body evolution comes up
// with, and costs a few microseconds a step. Motor joints rotate the two rods
// they join towards the brain's target angle (inverse-inertia weighted) and
// move the pivot to cancel the push, so internal forces never move the
// centre of mass: a creature only gets anywhere by pushing on the ground or
// the air. Ground contact uses Coulomb friction from the contact impulse.
#pragma once

#include "Body.h"
#include "Brain.h"
#include "World.h"

namespace evo
{

constexpr float kDt = 1.0f / 60.0f;  // fixed physics step (60 Hz)
constexpr int kIters = 4;            // constraint iterations per step
constexpr int kThinkEvery = 2;       // the brain runs at 30 Hz
constexpr float kMaxStep = 0.16f;    // max displacement per step (9.6 m/s)

enum StopReason
{
  STOP_NONE,
  STOP_TIME,
  STOP_STUCK,
  STOP_GOAL,     // reached the beacon / landed
  STOP_FELL,     // into the chasm
  STOP_EXPLOIT,  // impossible speed: scored zero
  STOP_UNSTABLE, // the solver blew up: scored zero
};

struct TrialResult
{
  float fitness = 0.0f;
  float progress = 0.0f;   // metres along the goal's axis (or towards the beacon)
  float distance = 0.0f;   // path length of the centre of mass
  float airtime = 0.0f;    // seconds with nothing touching the ground
  float maxClear = 0.0f;   // highest jump: lowest point above the ground
  float effort = 0.0f;     // motor work, radians
  float reachTime = -1.0f;
  float glide = 0.0f;      // distance flown past the cliff edge
  float time = 0.0f;       // seconds simulated before the result was final
  int tumbles = 0, jumps = 0;
  int stop = STOP_NONE;
  bool reached = false, crossed = false;
};

class Trial
{
public:
  void Init(const Phenotype& ph, const BrainGenome& brain, const WorldSpec* world, int variant = 0)
  {
    m_ph = &ph;
    m_w = world;
    m_np = ph.numParts;
    m_friction = world->friction * (variant ? 0.85f : 1.0f);
    const float sx = world->startX + (variant ? 0.3f * static_cast<float>(world->dir) : 0.0f);
    float off = -1e9f;
    for (int i = 0; i < m_np; i++)
      off = std::max(off, world->Height(sx + ph.px[i]) - (ph.py[i] - ph.radius[i]));
    off += 0.02f;
    for (int i = 0; i < m_np; i++)
    {
      x[i] = px[i] = sx + ph.px[i];
      y[i] = py[i] = ph.py[i] + off;
      m_im[i] = 1.0f / std::max(ph.mass[i], 1e-4f);
      contact[i] = 0;
    }
    for (int j = 0; j < ph.numJoints; j++)
    {
      target[j] = ph.joint[j].rest;
      effortNow[j] = 0.0f;
      m_lastDelta[j] = 0.0f;
    }
    m_flips = 0;
    net.Build(brain);
    net.Reset();
    res = TrialResult();
    steps = 0;
    t = 0.0f;
    done = false;
    m_strengthScale = 1.0f;
    m_budget = 45.0f * static_cast<float>(std::max(ph.numJoints, 1)) * world->duration / 15.0f;
    Com(cx0, cy0);
    cx = cx0;
    cy = cy0;
    m_hist[0] = cx;
    m_histY[0] = cy;
    m_histN = 1;
    m_comX30 = cx;
    m_angle0 = TorsoAngle();
    m_anglePrev = m_angle0;
    m_thinkAngle = m_angle0;
    m_thinkX = cx;
    m_thinkY = cy;
    m_flipped = false;
    m_airborne = false;
    m_fellIn = false;
    m_left = false;
    m_maxProg = 0.0f;
    m_maxRise = 0.0f;
    m_aloft = 0.0f;
    if (world->hasTarget)
    {
      const float dx = world->targetX - cx, dy = world->targetY - cy;
      m_d0 = std::sqrt(dx * dx + dy * dy);
      m_dmin = m_d0;
    }
    m_edge0 = std::fabs(world->cliffEdge - cx0);
  }

  // One 1/60 s step. After `done` the creature keeps moving (for the stage)
  // but its result is frozen.
  void Step()
  {
    const Phenotype& ph = *m_ph;
    const WorldSpec& w = *m_w;
    if (steps % kThinkEvery == 0)
      Think();

    // velocities, fin drag, gravity, integration
    // The speed cap scales every velocity relative to the centre of mass by
    // one factor (and the centre's own speed separately), so it never hands
    // the body a net push the way clamping particles one by one would.
    float vx[MAX_PARTS], vy[MAX_PARTS];
    float mvx = 0, mvy = 0, mt = 0;
    for (int i = 0; i < m_np; i++)
    {
      vx[i] = (x[i] - px[i]) * 0.999f;
      vy[i] = (y[i] - py[i]) * 0.999f;
      const float m = 1.0f / m_im[i];
      mvx += vx[i] * m;
      mvy += vy[i] * m;
      mt += m;
    }
    mvx /= mt;
    mvy /= mt;
    float rel2 = 0.0f;
    for (int i = 0; i < m_np; i++)
      rel2 = std::max(rel2, (vx[i] - mvx) * (vx[i] - mvx) + (vy[i] - mvy) * (vy[i] - mvy));
    const float com2 = mvx * mvx + mvy * mvy;
    if (rel2 > kMaxStep * kMaxStep || com2 > kMaxStep * kMaxStep)
    {
      const float sr = rel2 > kMaxStep * kMaxStep ? kMaxStep / std::sqrt(rel2) : 1.0f;
      const float sc = com2 > kMaxStep * kMaxStep ? kMaxStep / std::sqrt(com2) : 1.0f;
      for (int i = 0; i < m_np; i++)
      {
        vx[i] = mvx * sc + (vx[i] - mvx) * sr;
        vy[i] = mvy * sc + (vy[i] - mvy) * sr;
      }
    }
    const float wind = w.wind * kDt;
    for (int s = 0; s < ph.numSegs; s++)
    {
      const Segment& sg = ph.seg[s];
      if (sg.fin <= 0.0f)
        continue;
      const int a = sg.a, b = sg.b;
      float nx = -(y[b] - y[a]), ny = x[b] - x[a];
      const float l = std::sqrt(nx * nx + ny * ny);
      if (l < 1e-6f)
        continue;
      nx /= l;
      ny /= l;
      const float fvx = 0.5f * (vx[a] + vx[b]) - wind, fvy = 0.5f * (vy[a] + vy[b]);
      const float vn = fvx * nx + fvy * ny;                   // m per step
      const float area = sg.fin * sg.len;
      // quadratic drag on the plate: dv = k A vn|vn| / m (per-step units)
      float dv = 2.2f * w.air * area * vn * std::fabs(vn) / (kDt * std::max(sg.mass, 0.02f));
      dv = Clamp(dv, -0.9f * std::fabs(vn), 0.9f * std::fabs(vn));
      vx[a] -= dv * nx;
      vy[a] -= dv * ny;
      vx[b] -= dv * nx;
      vy[b] -= dv * ny;
    }
    const float g = w.gravity * kDt * kDt;
    for (int i = 0; i < m_np; i++)
    {
      px[i] = x[i];
      py[i] = y[i];
      x[i] += vx[i];
      y[i] += vy[i] - g;
      m_pen[i] = 0.0f;
    }

    const float strength = m_strengthScale;
    for (int j = 0; j < ph.numJoints; j++)
      effortNow[j] = 0.0f;
    for (int it = 0; it < kIters; it++)
    {
      // rods
      for (int s = 0; s < ph.numSegs; s++)
      {
        const Segment& sg = ph.seg[s];
        const int a = sg.a, b = sg.b;
        const float dx = x[b] - x[a], dy = y[b] - y[a];
        const float l2 = dx * dx + dy * dy;
        if (l2 < 1e-12f)
          continue;
        const float l = std::sqrt(l2);
        const float k = (l - sg.len) / (l * (m_im[a] + m_im[b]));
        x[a] += dx * k * m_im[a];
        y[a] += dy * k * m_im[a];
        x[b] -= dx * k * m_im[b];
        y[b] -= dy * k * m_im[b];
      }
      // motor joints with limits
      for (int j = 0; j < ph.numJoints; j++)
      {
        const Joint& jt = ph.joint[j];
        const int p = jt.p, q = jt.q, c = jt.c;
        const float d1x = x[q] - x[p], d1y = y[q] - y[p];
        const float d2x = x[c] - x[q], d2y = y[c] - y[q];
        const float phi = jt.rest + WrapAngle(FastAtan2(d1x * d2y - d1y * d2x, d1x * d2x + d1y * d2y) - jt.rest);
        const float maxd = jt.speed * kDt / static_cast<float>(kIters);
        float corr = Clamp((target[j] - phi) * jt.strength * strength, -maxd, maxd);
        const float motor = std::fabs(corr);
        if (phi + corr > jt.hi)
          corr = jt.hi - phi;
        else if (phi + corr < jt.lo)
          corr = jt.lo - phi;
        if (std::fabs(corr) < 1e-7f)
          continue;
        effortNow[j] += motor;
        // position-based angle constraint: phi = angle(d2) - angle(d1); its
        // gradients sum to zero (and are rotation invariant), so the push
        // conserves linear and angular momentum
        const float l1 = d1x * d1x + d1y * d1y, l2 = d2x * d2x + d2y * d2y;
        if (l1 < 1e-10f || l2 < 1e-10f)
          continue;
        const float gcx = -d2y / l2, gcy = d2x / l2; // dphi/dc
        const float gpx = -d1y / l1, gpy = d1x / l1; // dphi/dp
        const float gqx = -gcx - gpx, gqy = -gcy - gpy;
        const float wp = m_im[p], wq = m_im[q], wc = m_im[c];
        const float denom = wp * (gpx * gpx + gpy * gpy) + wq * (gqx * gqx + gqy * gqy) + wc * (gcx * gcx + gcy * gcy);
        const float lam = corr / std::max(denom, 1e-9f);
        x[p] += lam * wp * gpx;
        y[p] += lam * wp * gpy;
        x[q] += lam * wq * gqx;
        y[q] += lam * wq * gqy;
        x[c] += lam * wc * gcx;
        y[c] += lam * wc * gcy;
      }
      // ground
      for (int i = 0; i < m_np; i++)
      {
        float s;
        const float h = w.Height(x[i], &s);
        const float inv = 1.0f / std::sqrt(1.0f + s * s);
        const float dist = (y[i] - h) * inv;
        const float r = ph.radius[i];
        if (dist < r)
        {
          const float c = r - dist;
          x[i] += -s * inv * c;
          y[i] += inv * c;
          m_pen[i] += c;
        }
      }
    }
    // Coulomb friction from the contact push of this step
    int touching = 0;
    for (int i = 0; i < m_np; i++)
    {
      contact[i] = m_pen[i] > 0.0f;
      if (!contact[i])
        continue;
      touching++;
      float s;
      w.Height(x[i], &s);
      const float inv = 1.0f / std::sqrt(1.0f + s * s);
      const float tx = inv, ty = s * inv;
      const float d = (x[i] - px[i]) * tx + (y[i] - py[i]) * ty;
      const float lim = m_friction * m_pen[i];
      const float rm = std::fabs(d) <= lim ? d : (d > 0 ? lim : -lim);
      x[i] -= tx * rm;
      y[i] -= ty * rm;
    }
    for (int j = 0; j < ph.numJoints; j++)
      res.effort += done ? 0.0f : effortNow[j];
    if (res.effort > m_budget)
      m_strengthScale = 0.3f; // out of energy: weak motors

    steps++;
    t += kDt;
    const float ocx = cx, ocy = cy;
    Com(cx, cy);
    if (done)
      return;

    // --- safety
    bool bad = !std::isfinite(cx) || !std::isfinite(cy);
    for (int s = 0; s < ph.numSegs && !bad; s++)
    {
      const Segment& sg = ph.seg[s];
      const float dx = x[sg.b] - x[sg.a], dy = y[sg.b] - y[sg.a];
      if (dx * dx + dy * dy > 6.25f * sg.len * sg.len)
        bad = true;
    }
    if (bad)
    {
      Finish(STOP_UNSTABLE);
      return;
    }
    if (steps % 30 == 0)
    {
      // more than 8 m/s along the ground is a physics glitch, not a gait
      if (std::fabs(cx - m_comX30) > 4.0f && touching > 0)
      {
        Finish(STOP_EXPLOIT);
        return;
      }
      m_comX30 = cx;
    }

    // --- stats
    res.distance += std::sqrt((cx - ocx) * (cx - ocx) + (cy - ocy) * (cy - ocy));
    float clear = 1e9f;
    for (int i = 0; i < m_np; i++)
      clear = std::min(clear, y[i] - ph.radius[i] - w.Height(x[i]));
    const bool air = touching == 0;
    if (air)
      res.airtime += kDt;
    if (air && clear > 0.1f && !m_airborne)
    {
      m_airborne = true;
      res.jumps++;
    }
    if (!air)
      m_airborne = false;
    const float ang = TorsoAngle();
    const bool flipped = std::fabs(WrapAngle(ang - m_angle0)) > 2.6f;
    if (flipped && !m_flipped)
      res.tumbles++;
    m_flipped = flipped;
    m_anglePrev = ang;

    // --- the goal
    const float dir = static_cast<float>(w.dir);
    const float prog = dir * (cx - cx0);
    switch (w.goal)
    {
      case G_WALK:
      case G_HURDLES:
        res.progress = prog;
        res.fitness = std::max(prog, 0.0f);
        break;
      case G_BEACON:
      case G_CLIMB:
      {
        const float dx = w.targetX - cx, dy = w.targetY - cy;
        const float d = std::sqrt(dx * dx + dy * dy);
        m_dmin = std::min(m_dmin, d);
        res.progress = m_d0 - m_dmin;
        res.fitness = std::max(res.progress, 0.0f);
        if (d < 1.0f)
        {
          res.reached = true;
          res.reachTime = t;
          res.fitness = m_d0 + 4.0f + 4.0f * (1.0f - t / w.duration);
          Finish(STOP_GOAL);
          return;
        }
        break;
      }
      case G_CHASM:
      {
        if (cy < w.Height(w.pitL - 0.5f) - 0.6f && cx > w.pitL - 0.3f && cx < w.pitR + 0.3f)
        {
          m_fellIn = true;
          res.progress = m_maxProg;
          res.fitness = std::max(m_maxProg, 0.0f);
          Finish(STOP_FELL);
          return;
        }
        m_maxProg = std::max(m_maxProg, prog);
        const float farEdge = dir > 0 ? w.pitR : -w.pitL;
        if (!res.crossed && dir * cx > farEdge + 0.4f)
          res.crossed = true;
        res.progress = m_maxProg;
        res.fitness = std::max(m_maxProg, 0.0f) + (res.crossed ? 3.0f : 0.0f);
        break;
      }
      case G_LEAP:
        if (air && clear > res.maxClear)
          res.maxClear = clear;
        m_maxRise = std::max(m_maxRise, cy - cy0);
        res.progress = res.maxClear;
        res.fitness = 5.0f * res.maxClear + 0.5f * m_maxRise;
        break;
      case G_FLY:
        // height held in the air: metre-seconds of clearance while airborne,
        // so a hop scores little and staying up high scores a lot
        if (air && clear > 0.0f)
          m_aloft += clear * kDt;
        if (air && clear > res.maxClear)
          res.maxClear = clear;
        res.progress = res.maxClear;
        res.fitness = res.maxClear + 0.6f * m_aloft;
        break;
      case G_GLIDE:
      {
        const float past = dir * (cx - w.cliffEdge);
        if (!m_left)
        {
          if (past > 0.0f && clear > 0.15f)
            m_left = true;
          const float edge = Clamp(1.0f - std::fabs(w.cliffEdge - cx) / std::max(m_edge0, 0.1f), 0.0f, 1.0f);
          res.progress = 0.0f;
          res.fitness = 2.0f * edge;
          if (cy < w.cliffTop - 1.5f) // slid down the face
            m_left = true;
        }
        if (m_left)
        {
          res.glide = std::max(past, 0.0f);
          res.progress = res.glide;
          res.fitness = 2.0f + res.glide + 0.5f * res.airtime;
          bool low = false;
          for (int i = 0; i < m_np && !low; i++)
            low = contact[i] && w.Height(x[i]) < w.cliffTop - 1.0f;
          if (low)
          {
            Finish(STOP_GOAL);
            return;
          }
        }
        break;
      }
      default:
        break;
    }

    // --- stuck: barely moved in three seconds
    if (steps % 60 == 0)
    {
      m_hist[m_histN % 4] = cx;
      m_histY[m_histN % 4] = cy;
      m_histN++;
      if (m_histN > 4)
      {
        const int old = m_histN % 4;
        const float dx = cx - m_hist[old], dy = cy - m_histY[old];
        if (dx * dx + dy * dy < 0.08f * 0.08f)
        {
          Finish(STOP_STUCK);
          return;
        }
      }
    }
    if (t >= w.duration - 1e-4f)
      Finish(STOP_TIME);
  }

  // Run to the end (evaluation).
  void Run()
  {
    const int maxSteps = static_cast<int>(m_w->duration / kDt) + 2;
    while (!done && steps < maxSteps)
      Step();
    if (!done)
      Finish(STOP_TIME);
  }

  float TorsoAngle() const
  {
    const Segment& s = m_ph->seg[0];
    return FastAtan2(y[s.b] - y[s.a], x[s.b] - x[s.a]);
  }

  const Phenotype& phenotype() const { return *m_ph; }

  // state (read by the stage renderer)
  float x[MAX_PARTS], y[MAX_PARTS], px[MAX_PARTS], py[MAX_PARTS];
  uint8_t contact[MAX_PARTS];
  float target[MAX_SEGS];
  float effortNow[MAX_SEGS];
  float cx = 0, cy = 0, cx0 = 0, cy0 = 0;
  Net net;
  TrialResult res;
  int steps = 0;
  float t = 0.0f;
  bool done = false;

private:
  void Com(float& ox, float& oy) const
  {
    float mx = 0, my = 0, mt = 0;
    for (int i = 0; i < m_np; i++)
    {
      const float m = 1.0f / m_im[i];
      mx += x[i] * m;
      my += y[i] * m;
      mt += m;
    }
    ox = mx / mt;
    oy = my / mt;
  }

  void Think()
  {
    const Phenotype& ph = *m_ph;
    const WorldSpec& w = *m_w;
    float* in = net.val.data();
    for (int j = 0; j < J_MAX; j++)
    {
      if (j < ph.numJoints)
      {
        const Joint& jt = ph.joint[j];
        const int p = jt.p, q = jt.q, c = jt.c;
        const float d1x = x[q] - x[p], d1y = y[q] - y[p];
        const float d2x = x[c] - x[q], d2y = y[c] - y[q];
        const float phi = WrapAngle(FastAtan2(d1x * d2y - d1y * d2x, d1x * d2x + d1y * d2y) - jt.rest);
        in[IN_ANGLE + j] = Clamp(phi / std::max(0.5f * (jt.hi - jt.lo), 0.1f), -1.5f, 1.5f);
      }
      else
        in[IN_ANGLE + j] = 0.0f;
    }
    for (int k = 0; k < C_MAX; k++)
      in[IN_CONTACT + k] = k < ph.numFeet ? (contact[ph.foot[k]] ? 1.0f : -1.0f) : 0.0f;
    const float ang = TorsoAngle();
    in[IN_SIN] = std::sin(ang);
    in[IN_COS] = std::cos(ang);
    in[IN_SPIN] = Clamp(WrapAngle(ang - m_thinkAngle) / (kDt * kThinkEvery) * 0.1f, -1.0f, 1.0f);
    m_thinkAngle = ang;
    float vxs = 0, vys = 0;
    if (steps > 0)
    {
      vxs = (cx - m_thinkX) / (kDt * kThinkEvery);
      vys = (cy - m_thinkY) / (kDt * kThinkEvery);
    }
    m_thinkX = cx;
    m_thinkY = cy;
    in[IN_VX] = Clamp(vxs / 3.0f, -1.0f, 1.0f);
    in[IN_VY] = Clamp(vys / 3.0f, -1.0f, 1.0f);
    float tx = static_cast<float>(w.dir), ty = 0.0f, td = 0.0f;
    if (w.hasTarget)
    {
      const float dx = w.targetX - cx, dy = w.targetY - cy;
      const float d = std::sqrt(dx * dx + dy * dy);
      tx = d > 1e-4f ? dx / d : 0.0f;
      ty = d > 1e-4f ? dy / d : 0.0f;
      td = d / (d + 5.0f);
    }
    else if (w.goal == G_LEAP || w.goal == G_FLY)
    {
      tx = 0.0f;
      ty = 1.0f;
    }
    in[IN_TX] = tx;
    in[IN_TY] = ty;
    in[IN_TDIST] = td;
    const float a1 = kTwoPi * 0.9f * t, a2 = kTwoPi * 1.9f * t;
    in[IN_CLK1S] = std::sin(a1);
    in[IN_CLK1C] = std::cos(a1);
    in[IN_CLK2S] = std::sin(a2);
    in[IN_CLK2C] = std::cos(a2);
    in[IN_ENERGY] = 1.0f - 2.0f * Clamp(res.effort / m_budget, 0.0f, 1.0f);
    in[IN_BIAS] = 1.0f;
    net.Activate();
    for (int j = 0; j < ph.numJoints; j++)
    {
      const Joint& jt = ph.joint[j];
      const float nt = jt.rest + 0.5f * (jt.hi - jt.lo) * net.val[static_cast<size_t>(OUT0 + j)];
      const float delta = nt - target[j];
      if (delta * m_lastDelta[j] < 0.0f && std::fabs(delta) > 0.05f)
        m_flips++;
      if (std::fabs(delta) > 0.05f)
        m_lastDelta[j] = delta;
      target[j] = nt;
    }
  }

  void Finish(int reason)
  {
    if (done)
      return;
    done = true;
    res.stop = reason;
    res.time = t;
    if (reason == STOP_EXPLOIT || reason == STOP_UNSTABLE)
    {
      res.fitness = 0.0f;
      return;
    }
    // jitter for propulsion: direction flips faster than ~5 Hz per joint
    const float secs = std::max(t, 1.0f);
    const float flipHz = static_cast<float>(m_flips) / (2.0f * secs * static_cast<float>(std::max(m_ph->numJoints, 1)));
    const float chatter = Clamp((flipHz - 5.0f) / 10.0f, 0.0f, 0.5f);
    // mild growth cost so bodies do not bloat
    const float growth = 1.0f - 0.008f * static_cast<float>(m_ph->numSegs);
    res.fitness = std::max(res.fitness, 0.0f) * (1.0f - chatter) * growth;
  }

  const Phenotype* m_ph = nullptr;
  const WorldSpec* m_w = nullptr;
  int m_np = 0;
  float m_im[MAX_PARTS];
  float m_pen[MAX_PARTS];
  float m_lastDelta[MAX_SEGS];
  int m_flips = 0;
  float m_friction = 0.8f;
  float m_strengthScale = 1.0f, m_budget = 1.0f;
  float m_hist[4], m_histY[4];
  int m_histN = 0;
  float m_comX30 = 0.0f;
  float m_angle0 = 0.0f, m_anglePrev = 0.0f, m_thinkAngle = 0.0f, m_thinkX = 0.0f, m_thinkY = 0.0f;
  bool m_flipped = false, m_airborne = false, m_fellIn = false, m_left = false;
  float m_maxProg = 0.0f, m_maxRise = 0.0f, m_aloft = 0.0f;
  float m_d0 = 0.0f, m_dmin = 0.0f, m_edge0 = 1.0f;
};

} // namespace evo

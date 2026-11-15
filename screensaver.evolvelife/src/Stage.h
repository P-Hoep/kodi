// The stage and the insight layer (Sections 10 and 11 of EvolveLife.md).
//
// The stage replays a finished generation live: its champion, the best of
// the rest and a random sample run the same trial they had in evaluation, in
// real time, all in the same world (they never touch each other). A round is
// the trial plus a short outro where the winners brighten and the losers
// fade; then the next finished generation comes in. The camera Director
// eases between a reveal of the goal, wide shots of the pack and shots that
// follow the leader, and closes on the champion at the end.
//
// The insight layer draws what the evolution is doing: the goal and the
// generation, the event ticker, live fitness sparklines, the champion's brain
// firing as it moves, and a rotating info card (profile, goal briefing, run
// totals, fitness and species history, brain growth, family tree, then and
// now, milestones, hall of fame, commentary, facts, species map), all from
// data the run produced. Panels drift slowly and swap sides every ten
// minutes against burn-in, and fade when the followed creature is under one.
//
// Everything here is plain CPU work into three quad batches (world, HUD,
// text) in clip space; the Kodi shell uploads and draws them.
#pragma once

#include "Draw.h"
#include "Evolution.h"

#include <atomic>
#include <cstdio>
#include <memory>

namespace evo
{

enum CameraMode
{
  CAM_CINEMATIC,
  CAM_FOLLOW,
  CAM_OVERVIEW
};

enum InsightLevel
{
  INS_OFF,
  INS_LIGHT,
  INS_RICH,
  INS_FULL
};

enum Card
{
  CARD_PROFILE,
  CARD_BRIEFING,
  CARD_TOTALS,
  CARD_FITNESS,
  CARD_SPECIES,
  CARD_BRAIN,
  CARD_FAMILY,
  CARD_THENNOW,
  CARD_MILESTONES,
  CARD_HALL,
  CARD_COMMENTARY,
  CARD_FACT,
  CARD_MAP,
  CARD_COUNT
};

struct StageOptions
{
  int visible = 24;
  int camera = CAM_CINEMATIC;
  int insight = INS_RICH;
  bool neural = true;
  bool ticker = true;
  uint32_t cards = 0xFFFFu; // bit per Card
  float cardSeconds = 25.0f;
  int palette = PAL_AUTO;
  float bright = 1.0f;      // brightness cap
  bool motes = true;
  int parallax = 3;         // background silhouette layers
  float textScale = 1.0f;
  bool labels = true;       // names over the creatures
};

class Stage
{
public:
  static constexpr float kOutro = 3.5f;
  static constexpr float kEnd = 0.8f;
  static constexpr float kEndNewWorld = 1.6f;

  void Reset(const StageOptions& o, uint64_t seed)
  {
    m_o = o;
    m_rng.Seed(seed ^ 0xABCDEFULL);
    m_palette = GetPalette(o.palette == PAL_AUTO ? 1 + m_rng.Int(3) : o.palette);
    m_snap.reset();
    m_next.reset();
    m_actors.clear();
    m_actors.reserve(64);
    m_time = 0.0f;
    m_roundT = 0.0f;
    m_phase = PH_WAIT;
    m_consumed.store(-1);
    m_lastSeq = 0;
    m_nTicker = 0;
    m_nPending = 0;
    m_card = -1;
    m_cardStart = -1e9f;
    for (int& c : m_recentCards)
      c = -1;
    m_titleT0 = -100.0f;
    m_layoutId = ~0ull;
    m_rounds = 0;
    m_cam = {};
    m_camInit = false;
    for (int i = 0; i < kMotes; i++)
    {
      Mote& m = m_motes[i];
      m.x = m_rng.Uni();
      m.y = m_rng.Uni();
      m.f = m_rng.Range(0.04f, 0.35f);
      m.size = m_rng.Range(0.5f, 1.6f);
      m.phase = m_rng.Range(0.0f, kTwoPi);
    }
  }

  void SetScreen(int w, int h)
  {
    m_W = static_cast<float>(std::max(w, 16));
    m_H = static_cast<float>(std::max(h, 16));
    for (Batch* b : {&world, &hud, &text})
    {
      b->W = m_W;
      b->H = m_H;
    }
  }

  void SetVisible(int n) { m_o.visible = n; }
  int visible() const { return m_o.visible; }
  void SetMotes(bool on, int parallax)
  {
    m_o.motes = on;
    m_o.parallax = parallax;
  }
  void SetPerf(float stepMs, float fps, int threads)
  {
    m_stepMs = stepMs;
    m_fps = fps;
    m_threads = threads;
  }
  void Notice(const char* text) { QueueTicker(text, -1.0f); }

  // the newest generation the stage has taken (the evolver may run ahead of it)
  int consumed() const { return m_consumed.load(); }
  bool waiting() const { return m_phase == PH_WAIT; }
  // the generation on screen and its world (for the log)
  const Snapshot* snapshot() const { return m_snap.get(); }

  // One 1/60 s tick of the stage.
  void Tick(const std::shared_ptr<const Snapshot>& latest)
  {
    m_time += kDt;
    if (m_phase == PH_WAIT)
    {
      if (latest)
        BeginRound(latest);
      else
        return;
    }
    m_roundT += kDt;
    for (Actor& a : m_actors)
      a.trial.Step();
    if (m_o.ticker)
      FeedTicker();
    const float dur = m_snap->world->duration;
    switch (m_phase)
    {
      case PH_RUN:
        if (m_roundT >= dur)
          m_phase = PH_OUTRO;
        break;
      case PH_OUTRO:
        if (m_roundT >= dur + kOutro)
        {
          m_next = latest && latest->generation > m_snap->generation ? latest : m_snap;
          m_newWorld = m_next->world != m_snap->world;
          m_phase = PH_END;
          m_endAt = m_roundT;
        }
        break;
      case PH_END:
        if (m_roundT >= m_endAt + (m_newWorld ? kEndNewWorld : kEnd))
          BeginRound(m_next);
        break;
      default:
        break;
    }
    UpdateCamera(false);
    UpdateBrainFlash();
  }

  void Build()
  {
    world.Clear();
    hud.Clear();
    text.Clear();
    m_pw = m_cam.h / m_H; // metres per pixel
    BuildSky();
    if (!m_snap)
    {
      BuildWaiting();
      return;
    }
    BuildSilhouettes();
    if (m_o.motes)
      BuildMotes();
    BuildTerrain();
    BuildMarkers();
    BuildCreatures();
    if (m_o.insight > INS_OFF)
      BuildHud();
  }

  Batch world, hud, text;

private:
  enum Phase
  {
    PH_WAIT,
    PH_RUN,
    PH_OUTRO,
    PH_END
  };

  struct Actor
  {
    const Individual* ind = nullptr;
    Trial trial;
    RGB col;
    float hue = 0.0f;
    int rank = 0;
    bool ghost = false;
  };

  struct Cam
  {
    float x = 0, y = 0, h = 8, vx = 0, vy = 0, vh = 0;
  };

  struct Mote
  {
    float x, y, f, size, phase;
  };

  struct TickerLine
  {
    char text[112];
    float hue, t0;
  };

  // ---------------------------------------------------------------- rounds

  void BeginRound(const std::shared_ptr<const Snapshot>& snap)
  {
    const bool newWorld = !m_snap || snap->world != m_snap->world;
    const bool first = !m_snap;
    m_snap = snap;
    m_consumed.store(snap->generation);
    m_rounds++;
    if (newWorld)
      m_epochRound = 0;
    else
      m_epochRound++;

    ChooseCard(newWorld);

    // who is on stage: the champion and the best of the rest, then a sample
    m_actors.clear();
    const int P = static_cast<int>(snap->pop.size());
    const int N = std::min(std::max(m_o.visible, 1), P);
    const int top = std::max(1, (N + 1) / 2);
    int picks[64];
    int np = 0;
    for (int i = 0; i < top && np < 64; i++)
      picks[np++] = i;
    Rng r(static_cast<uint64_t>(snap->generation) * 7919ULL + m_rounds);
    for (int tries = 0; np < N && np < 64 && tries < 400; tries++)
    {
      const int c = top + r.Int(std::max(P - top, 1));
      if (c >= P)
        break;
      bool dup = false;
      for (int k = 0; k < np && !dup; k++)
        dup = picks[k] == c;
      if (!dup)
        picks[np++] = c;
    }
    if (m_card == CARD_THENNOW && snap->hasGhost)
    {
      Actor g;
      g.ind = &snap->ghost;
      g.ghost = true;
      g.rank = -1;
      g.col = {0.85f, 0.9f, 1.0f};
      m_actors.push_back(std::move(g));
    }
    // worst first, so the champion is drawn on top
    for (int k = np - 1; k >= 0; k--)
    {
      Actor a;
      a.ind = &snap->pop[static_cast<size_t>(picks[k])];
      a.rank = picks[k];
      a.hue = SpeciesHue(a.ind->species) + a.ind->hue;
      a.col = CreatureColour(a.hue, a.ind->id);
      m_actors.push_back(std::move(a));
    }
    for (Actor& a : m_actors)
      a.trial.Init(a.ind->ph, a.ind->brain, snap->world.get());

    m_roundT = 0.0f;
    m_phase = PH_RUN;
    if (newWorld)
    {
      m_titleT0 = m_time;
      m_titleFirst = first;
      UpdateCamera(true);
    }
  }

  void ChooseCard(bool newWorld)
  {
    const Snapshot& s = *m_snap;
    const bool due = m_time - m_cardStart >= m_o.cardSeconds - 0.5f || m_card < 0;
    if (!due && !newWorld)
      return;
    auto ok = [&](int c) {
      if (!(m_o.cards & (1u << c)))
        return false;
      if (c == CARD_THENNOW)
        return s.hasGhost && s.epochGen >= 3 && s.pop[0].fitness > 0.01f;
      if (c == CARD_FAMILY)
        return s.pop[0].nAnc >= 2;
      if (c == CARD_FITNESS || c == CARD_BRAIN || c == CARD_SPECIES)
        return s.history.size() >= 3;
      return true;
    };
    auto recent = [&](int c) {
      for (int r : m_recentCards)
        if (r == c)
          return true;
      return false;
    };
    int pick = -1;
    // fresh events first
    if (newWorld && ok(CARD_BRIEFING))
      pick = CARD_BRIEFING;
    for (const Event& e : s.events)
    {
      if (pick >= 0 || e.seq <= m_cardSeq)
        continue;
      int c = -1;
      if (e.type == EV_SPECIES_BORN || e.type == EV_SPECIES_EXTINCT)
        c = CARD_SPECIES;
      else if (e.type == EV_NEW_BEST || e.type == EV_MUTATION)
        c = CARD_PROFILE;
      else if (e.type == EV_MILESTONE)
        c = CARD_MILESTONES;
      if (c >= 0 && ok(c) && !recent(c))
        pick = c;
    }
    if (!s.events.empty())
      m_cardSeq = s.events.back().seq;
    for (int k = 1; pick < 0 && k <= CARD_COUNT; k++)
    {
      const int c = (std::max(m_card, 0) + k) % CARD_COUNT;
      if (ok(c) && !recent(c))
        pick = c;
    }
    for (int k = 1; pick < 0 && k <= CARD_COUNT; k++)
    {
      const int c = (std::max(m_card, 0) + k) % CARD_COUNT;
      if (ok(c))
        pick = c;
    }
    if (pick < 0)
      pick = CARD_TOTALS;
    if (pick != m_card)
    {
      for (int i = kRecent - 1; i > 0; i--)
        m_recentCards[i] = m_recentCards[i - 1];
      m_recentCards[0] = pick;
      m_card = pick;
      m_cardStart = m_time;
      m_cardVariant = m_rng.U32();
    }
  }

  float SpeciesHue(int id) const
  {
    for (const SpeciesView& v : m_snap->species)
      if (v.id == id)
        return v.hue;
    return 0.5f;
  }

  const SpeciesView* Species(int id) const
  {
    for (const SpeciesView& v : m_snap->species)
      if (v.id == id)
        return &v;
    return nullptr;
  }

  RGB CreatureColour(float hue, uint64_t id) const
  {
    if (m_palette.mono)
    {
      const float v = 0.65f + 0.35f * static_cast<float>(Hash(static_cast<uint32_t>(id)) & 255) / 255.0f;
      return {v * 0.9f, v * 0.95f, v};
    }
    return Hsv(hue, m_palette.sat, m_palette.val);
  }

  const Actor* Leader() const
  {
    const Actor* best = nullptr;
    for (const Actor& a : m_actors)
      if (!a.ghost && (!best || a.trial.res.fitness > best->trial.res.fitness ||
                       (a.trial.res.fitness == best->trial.res.fitness && a.rank < best->rank)))
        best = &a;
    return best;
  }

  const Actor* Champion() const
  {
    for (const Actor& a : m_actors)
      if (a.rank == 0)
        return &a;
    return m_actors.empty() ? nullptr : &m_actors.back();
  }

  // ---------------------------------------------------------------- camera

  void UpdateCamera(bool snap)
  {
    if (!m_snap || m_actors.empty())
      return;
    const WorldSpec& w = *m_snap->world;
    const float aspect = m_W / m_H;
    const Actor* lead = m_phase == PH_OUTRO || m_phase == PH_END ? Champion() : Leader();
    if (!lead)
      return;
    float minx = 1e9f, maxx = -1e9f, miny = 1e9f, maxy = -1e9f;
    for (const Actor& a : m_actors)
    {
      if (a.ghost)
        continue;
      minx = std::min(minx, a.trial.cx - 1.0f);
      maxx = std::max(maxx, a.trial.cx + 1.0f);
      miny = std::min(miny, a.trial.cy - 1.0f);
      maxy = std::max(maxy, a.trial.cy + 1.0f);
    }
    // the shot
    int shot = 0; // 0 follow, 1 wide, 2 reveal, 3 close
    if (m_o.camera == CAM_FOLLOW)
      shot = m_phase == PH_RUN ? 0 : 3;
    else if (m_o.camera == CAM_OVERVIEW)
      shot = 1;
    else if (m_phase == PH_RUN)
    {
      if (m_roundT < 2.2f)
        shot = 2;
      else
      {
        const float c = std::fmod(m_roundT - 2.2f, 11.0f);
        shot = c < 7.0f ? 0 : 1;
      }
    }
    else
      shot = 3;
    if (snap)
      shot = 2;

    float tx, ty, th;
    if (shot == 0 || shot == 3)
    {
      const float size = std::max(lead->ind->ph.width, lead->ind->ph.height);
      float vx = (lead->trial.cx - lead->trial.cx0) / std::max(lead->trial.t, 1.0f);
      tx = lead->trial.cx + Clamp(vx, -2.0f, 2.0f) * 0.6f;
      ty = lead->trial.cy + 0.5f;
      th = (shot == 3 ? 4.5f : 6.5f) + 1.2f * size;
    }
    else
    {
      if (shot == 2)
      {
        // the start and what lies ahead
        minx = std::min(minx, w.startX - 2.0f);
        maxx = std::max(maxx, w.startX + 2.0f);
        const float ahead = w.hasTarget ? w.targetX : (w.goal == G_CHASM ? (w.dir > 0 ? w.pitR + 2.0f : w.pitL - 2.0f)
                                                       : (w.goal == G_GLIDE ? w.cliffEdge + w.dir * 8.0f
                                                       : (w.goal == G_LEAP ? w.startX : w.startX + w.dir * 8.0f)));
        minx = std::min(minx, ahead - 1.5f);
        maxx = std::max(maxx, ahead + 1.5f);
        if (w.hasTarget)
        {
          miny = std::min(miny, w.targetY - 1.0f);
          maxy = std::max(maxy, w.targetY + 1.0f);
        }
        if (w.goal == G_GLIDE)
          miny = std::min(miny, w.Height(w.cliffEdge + w.dir * 6.0f));
      }
      tx = 0.5f * (minx + maxx);
      ty = 0.5f * (miny + maxy);
      th = std::max(std::max((maxy - miny) * 1.5f + 1.5f, (maxx - minx) / aspect * 1.2f + 1.0f), 7.0f);
      th = std::min(th, 40.0f);
    }
    // keep the ground in the lower third and the subject in frame
    const float gy = std::min(w.Height(tx), ty - 0.2f);
    ty = std::max(ty, gy + 0.18f * th);
    if (w.goal == G_LEAP && shot != 2)
      th = std::max(th, (lead->trial.cy - gy) * 2.0f + 3.0f);
    // a slow drift against burn-in
    tx += 0.12f * std::sin(m_time * 0.071f);
    ty += 0.08f * std::sin(m_time * 0.053f + 1.0f);

    if (snap || !m_camInit)
    {
      m_cam = {tx, ty, th, 0, 0, 0};
      m_camInit = true;
      return;
    }
    auto spring = [](float& x, float& v, float target, float omega) {
      const float a = omega * omega * (target - x) - 2.0f * omega * v;
      v += a * kDt;
      x += v * kDt;
    };
    spring(m_cam.x, m_cam.vx, tx, 1.6f);
    spring(m_cam.y, m_cam.vy, ty, 1.6f);
    spring(m_cam.h, m_cam.vh, th, 1.1f);
    m_cam.h = std::max(m_cam.h, 3.0f);
  }

  // ---------------------------------------------------------------- coords

  // pixels (y down) to clip space
  float Cx(float px) const { return px * 2.0f / m_W - 1.0f; }
  float Cy(float py) const { return 1.0f - py * 2.0f / m_H; }
  // world (metres, y up) to pixels
  float Px(float x) const { return (x - m_cam.x) / m_pw + 0.5f * m_W; }
  float Py(float y) const { return 0.5f * m_H - (y - m_cam.y) / m_pw; }

  void QuadPx(Batch& b, float x0, float y0, float x1, float y1, uint32_t col, uint32_t par, float u0 = 0, float v0 = 0,
              float u1 = 1, float v1 = 1)
  {
    const float xy[8] = {Cx(x0), Cy(y0), Cx(x1), Cy(y0), Cx(x0), Cy(y1), Cx(x1), Cy(y1)};
    const float uv[8] = {u0, v0, u1, v0, u0, v1, u1, v1};
    b.Quad(xy, uv, col, par);
  }

  void GradPx(Batch& b, float x0, float y0, float x1, float y1, uint32_t top, uint32_t bottom)
  {
    const float xy[8] = {Cx(x0), Cy(y0), Cx(x1), Cy(y0), Cx(x0), Cy(y1), Cx(x1), Cy(y1)};
    const float uv[8] = {0, 0, 0, 0, 0, 0, 0, 0};
    const uint32_t c[4] = {top, top, bottom, bottom};
    b.Quad4(xy, uv, c, PackPar(LK_FLAT, 0, 0, 0));
  }

  // a quad along a segment in pixels: half-width w across, extended by e along
  void Oriented(Batch& b, float ax, float ay, float bx, float by, float w, float e, uint32_t col, uint32_t par,
                float uScale, float vScale)
  {
    float dx = bx - ax, dy = by - ay;
    const float l = std::sqrt(dx * dx + dy * dy);
    if (l < 1e-4f)
    {
      dx = 1;
      dy = 0;
    }
    else
    {
      dx /= l;
      dy /= l;
    }
    const float nx = -dy * w, ny = dx * w;
    const float ex = dx * e, ey = dy * e;
    const float x0 = ax - ex, y0 = ay - ey, x1 = bx + ex, y1 = by + ey;
    const float xy[8] = {Cx(x0 + nx), Cy(y0 + ny), Cx(x1 + nx), Cy(y1 + ny),
                         Cx(x0 - nx), Cy(y0 - ny), Cx(x1 - nx), Cy(y1 - ny)};
    const float hu = (0.5f * l + e) * uScale;
    const float uv[8] = {-hu, vScale, hu, vScale, -hu, -vScale, hu, -vScale};
    b.Quad(xy, uv, col, par);
  }

  void LinePx(Batch& b, float ax, float ay, float bx, float by, float width, const RGB& c, float a)
  {
    Oriented(b, ax, ay, bx, by, 0.5f * width + 1.0f, 0.5f, PackPre(c, a), PackPar(LK_LINE, 0, 0, 0), 0.0f,
             (0.5f * width + 1.0f) / std::max(0.5f * width, 0.5f));
  }

  void GlowPx(Batch& b, float x, float y, float r, const RGB& c, float k)
  {
    QuadPx(b, x - r, y - r, x + r, y + r, PackPre(c, 0.0f, k), PackPar(LK_GLOW, 0, 0, 0), -1, -1, 1, 1);
  }

  void ShadowPx(Batch& b, float x, float y, float rx, float ry, float a)
  {
    QuadPx(b, x - rx, y - ry, x + rx, y + ry, PackPre({0, 0, 0}, a), PackPar(LK_GLOW, 0, 0, 0), -1, -1, 1, 1);
  }

  void DiscPx(Batch& b, float x, float y, float r, const RGB& c, float a)
  {
    const float R = r * 1.8f;
    QuadPx(b, x - R, y - R, x + R, y + R, PackPre(c, a), PackPar(LK_DISC, 0, 0, 0), -1.8f, -1.8f, 1.8f, 1.8f);
  }

  // a lit capsule from a to b with radius r (pixels)
  void CapsulePx(Batch& b, float ax, float ay, float bx, float by, float r, const RGB& c, float a, float stripes,
                 float glowBoost = 0.0f)
  {
    r = std::max(r, 1.2f);
    const float dx = bx - ax, dy = by - ay;
    const float half = 0.5f * std::sqrt(dx * dx + dy * dy);
    const float e = r + 1.5f;
    const float w = r + 1.5f;
    // u, v in units of r; the shader gets the half length / r and the AA width
    const float hr = half / r;
    // w byte: stripes (high nibble) and the motor glow (low nibble)
    const float sw = std::floor(Clamp(stripes, 0, 1) * 15.0f + 0.5f) * 16.0f + std::floor(Clamp(glowBoost, 0, 1) * 15.0f + 0.5f);
    const uint32_t par = PackPar(LK_CAPSULE, std::min(hr * 10.0f, 255.0f), std::min(1.5f / r * 64.0f, 255.0f), sw);
    Oriented(b, ax, ay, bx, by, w, e, PackPre(c, a), par, 1.0f / r, w / r);
  }

  void PanelPx(float x0, float y0, float x1, float y1, float alpha)
  {
    const float hh = 0.5f * (y1 - y0);
    const float aspect = (x1 - x0) / (y1 - y0);
    const float rad = std::min(18.0f * m_S / hh, 0.9f);
    QuadPx(hud, x0, y0, x1, y1, PackPre({0.02f, 0.025f, 0.045f}, 0.5f * alpha),
           PackPar(LK_PANEL, std::min(aspect * 16.0f, 255.0f), rad * 255.0f, std::min(1.5f / hh * 255.0f * 4.0f, 255.0f)),
           -aspect, -1, aspect, 1);
  }

  // ---------------------------------------------------------------- world

  void BuildSky()
  {
    const Palette& p = m_palette;
    const float k = m_o.bright * SceneFade();
    // the sky shifts a little as the camera climbs
    const float lift = m_snap ? Clamp(m_cam.y * 0.01f, -0.2f, 0.3f) : 0.0f;
    const RGB top = Scale(p.skyTop, k), bottom = Scale(Mix(p.skyBottom, p.skyTop, lift), k);
    GradPx(world, 0, 0, m_W, m_H, PackPre(top, 1.0f), PackPre(bottom, 1.0f));
  }

  float SceneFade() const
  {
    if (!m_snap)
      return std::min(m_time / 1.5f, 1.0f);
    float f = std::min(m_time / 2.0f, 1.0f);
    // new world: fade the whole scene down and back up
    if (m_phase == PH_END && m_newWorld)
      f *= 1.0f - std::min((m_roundT - m_endAt) / kEndNewWorld, 1.0f);
    if (m_phase == PH_RUN && m_epochRound == 0)
      f *= std::min(m_roundT / 1.0f, 1.0f);
    return f * f * (3.0f - 2.0f * f);
  }

  void BuildWaiting()
  {
    const float a = std::min(m_time / 1.0f, 1.0f) * (0.6f + 0.4f * std::sin(m_time * 2.0f));
    m_S = m_H / 1080.0f * m_o.textScale;
    if (m_o.insight > INS_OFF)
      DrawText(text, 0.5f * m_W, 0.5f * m_H - 20 * m_S, 34 * m_S, {0.9f, 0.9f, 1.0f}, a * m_o.bright,
               "Seeding life...", 1);
  }

  void BuildSilhouettes()
  {
    const Palette& p = m_palette;
    const float k = m_o.bright * SceneFade();
    const int layers = std::min(std::max(m_o.parallax, 0), 5);
    const float viewW = m_cam.h * m_W / m_H;
    const float groundPy = Py(m_snap->world->Height(m_cam.x));
    for (int l = 0; l < layers; l++)
    {
      const float depth = static_cast<float>(layers - l) / static_cast<float>(layers); // 1 far .. 1/n near
      const float f = 0.08f + 0.5f * (1.0f - depth);                                    // parallax
      const RGB c = Scale(Mix(p.groundBottom, p.fog, 0.25f + 0.6f * depth), k * (0.5f + 0.5f * depth));
      const float horizon = groundPy - (0.12f + 0.18f * depth) * m_H + (m_cam.y * f) / m_pw * 0.15f;
      const float amp = (0.09f + 0.10f * (1.0f - depth)) * m_H;
      const uint32_t seed = 977u * static_cast<uint32_t>(l + 1) + static_cast<uint32_t>(m_snap->world->seed);
      const int cols = 48;
      float prevX = 0, prevY = 0;
      for (int i = 0; i <= cols; i++)
      {
        const float sx = m_W * static_cast<float>(i) / cols;
        const float u = m_cam.x * f + (sx / m_W - 0.5f) * viewW;
        const float n = Noise1(u / (3.0f + 5.0f * depth), seed) + 0.45f * Noise1(u / (1.2f + 1.5f * depth), seed ^ 77u);
        const float y = horizon - amp * (0.6f + 0.5f * n);
        if (i > 0)
        {
          const float xy[8] = {Cx(prevX), Cy(prevY), Cx(sx), Cy(y), Cx(prevX), Cy(m_H), Cx(sx), Cy(m_H)};
          const float uv[8] = {0, 0, 0, 0, 0, 0, 0, 0};
          world.Quad(xy, uv, PackPre(c, 1.0f), PackPar(LK_FLAT, 0, 0, 0));
        }
        prevX = sx;
        prevY = y;
      }
    }
    // a fog band over the far silhouettes
    const RGB fog = Scale(p.fog, k * 0.5f);
    GradPx(world, 0, groundPy - 0.35f * m_H, m_W, groundPy + 0.05f * m_H, PackPre(fog, 0.0f), PackPre(fog, 0.35f));
  }

  void BuildMotes()
  {
    const float k = m_o.bright * SceneFade();
    const float viewW = m_cam.h * m_W / m_H;
    const int n = m_o.parallax >= 3 ? kMotes : kMotes / 3;
    for (int i = 0; i < n; i++)
    {
      const Mote& m = m_motes[i];
      float sx = m.x - (m_cam.x * m.f) / (viewW * 1.5f);
      sx -= std::floor(sx);
      float sy = m.y - m_time * 0.004f * (0.5f + m.f) + (m_cam.y * m.f) / (m_cam.h * 3.0f);
      sy -= std::floor(sy);
      const float tw = 0.5f + 0.5f * std::sin(m_time * (0.6f + m.f) + m.phase);
      GlowPx(world, sx * m_W, sy * m_H, (3.0f + 5.0f * m.size) * m_H / 1080.0f, m_palette.mote, 0.10f * tw * k);
    }
  }

  void BuildTerrain()
  {
    const Palette& p = m_palette;
    const WorldSpec& w = *m_snap->world;
    const float k = m_o.bright * SceneFade();
    const float viewW = m_cam.h * m_W / m_H;
    const float x0 = m_cam.x - 0.5f * viewW - 0.5f, x1 = m_cam.x + 0.5f * viewW + 0.5f;
    const float step = std::max(WorldSpec::kDx, viewW / 200.0f);
    const RGB top = Scale(p.groundTop, k), bottom = Scale(p.groundBottom, k);
    const uint32_t ct = PackPre(top, 1.0f), cb = PackPre(bottom, 1.0f);
    const float uv[8] = {0, 0, 0, 0, 0, 0, 0, 0};
    float px0 = Px(x0), py0 = Py(w.Height(x0));
    const float edgeW = std::max(2.0f, 0.035f / m_pw);
    const RGB edge = Scale(p.edge, k);
    for (float x = x0 + step; x <= x1 + step; x += step)
    {
      const float px1 = Px(x), py1 = Py(w.Height(x));
      // ground: gradient down from the surface
      const float depth = 0.5f * m_H;
      const float xy[8] = {Cx(px0), Cy(py0), Cx(px1), Cy(py1), Cx(px0), Cy(py0 + depth), Cx(px1), Cy(py1 + depth)};
      const uint32_t c[4] = {ct, ct, cb, cb};
      world.Quad4(xy, uv, c, PackPar(LK_FLAT, 0, 0, 0));
      if (py0 + depth < m_H || py1 + depth < m_H)
      {
        const float xy2[8] = {Cx(px0), Cy(py0 + depth), Cx(px1), Cy(py1 + depth), Cx(px0), Cy(m_H + 2), Cx(px1), Cy(m_H + 2)};
        world.Quad(xy2, uv, cb, PackPar(LK_FLAT, 0, 0, 0));
      }
      px0 = px1;
      py0 = py1;
    }
    // the luminous rim of the ground
    px0 = Px(x0);
    py0 = Py(w.Height(x0));
    for (float x = x0 + step; x <= x1 + step; x += step)
    {
      const float px1 = Px(x), py1 = Py(w.Height(x));
      LinePx(world, px0, py0, px1, py1, edgeW, edge, 0.85f);
      px0 = px1;
      py0 = py1;
    }
  }

  void BuildMarkers()
  {
    const WorldSpec& w = *m_snap->world;
    const float k = m_o.bright * SceneFade();
    const float pulse = 0.75f + 0.25f * std::sin(m_time * 2.4f);
    const RGB bc = Scale(m_palette.beacon, k);
    if (w.hasTarget)
    {
      const float bx = Px(w.targetX), by = Py(w.targetY);
      const float gy = Py(w.Height(w.targetX));
      // a beam up from the ground, a halo and a bright core
      const float bw = 0.18f / m_pw;
      GradPx(world, bx - bw, by - 6.0f / m_pw, bx + bw, gy, PackPre(bc, 0.0f, 0.0f), PackPre(bc, 0.0f, 0.18f * pulse));
      GlowPx(world, bx, by, 2.2f / m_pw, bc, 0.45f * pulse);
      GlowPx(world, bx, by, 0.7f / m_pw, bc, 0.9f);
      DiscPx(world, bx, by, 0.16f / m_pw, Mix(bc, {1, 1, 1}, 0.5f), 1.0f);
    }
    // distance marks along the way for the travel goals
    const bool travel = w.goal == G_WALK || w.goal == G_HURDLES || w.goal == G_CHASM || w.goal == G_GLIDE;
    if (travel && m_o.insight > INS_OFF)
    {
      const float base = w.goal == G_GLIDE ? w.cliffEdge : w.startX;
      const float viewW = m_cam.h * m_W / m_H;
      const float spacing = viewW > 30.0f ? 10.0f : 5.0f;
      for (int i = 1; i <= 24; i++)
      {
        const float x = base + static_cast<float>(w.dir) * spacing * static_cast<float>(i);
        if (std::fabs(x - m_cam.x) > 0.6f * viewW)
          continue;
        const float gy = Py(w.Height(x));
        LinePx(world, Px(x), gy, Px(x), gy - 0.5f / m_pw, std::max(1.5f, 0.02f / m_pw), m_palette.edge, 0.35f * k);
        char buf[16];
        std::snprintf(buf, sizeof(buf), "%d m", static_cast<int>(spacing) * i);
        DrawText(text, Px(x), gy - 0.5f / m_pw - 26.0f * m_H / 1080.0f, 20.0f * m_H / 1080.0f, m_palette.edge, 0.55f * k, buf, 1);
      }
    }
    if (w.goal == G_LEAP && m_o.insight > INS_OFF)
    {
      const float gy = w.Height(w.startX);
      for (int i = 1; i <= 4; i++)
      {
        const float y = Py(gy + 0.5f * static_cast<float>(i));
        LinePx(world, Px(w.startX - 3.0f), y, Px(w.startX + 3.0f), y, 1.5f, m_palette.edge, 0.18f * k);
        char buf[16];
        std::snprintf(buf, sizeof(buf), "%.1f m", 0.5f * static_cast<float>(i));
        DrawText(text, Px(w.startX + 3.0f) + 8.0f, y - 12.0f * m_H / 1080.0f, 20.0f * m_H / 1080.0f, m_palette.edge, 0.5f * k, buf);
      }
    }
  }

  float ActorAlpha(const Actor& a) const
  {
    float al = std::min(m_roundT / 0.8f, 1.0f);
    if (m_phase == PH_OUTRO || m_phase == PH_END)
    {
      const float t = std::min((m_roundT - m_snap->world->duration) / 1.2f, 1.0f);
      if (a.rank > 2 && !a.ghost)
        al *= 1.0f - 0.6f * t;
    }
    if (m_phase == PH_END)
      al *= 1.0f - std::min((m_roundT - m_endAt) / kEnd, 1.0f);
    if (a.ghost)
      al *= 0.42f;
    return al;
  }

  void BuildCreatures()
  {
    const WorldSpec& w = *m_snap->world;
    const float k = m_o.bright * SceneFade();
    const bool outro = m_phase == PH_OUTRO || m_phase == PH_END;
    const float ot = outro ? std::min((m_roundT - w.duration) / 1.2f, 1.0f) : 0.0f;
    // soft shadows on the ground
    for (const Actor& a : m_actors)
    {
      const float al = ActorAlpha(a) * k;
      const float gh = w.Height(a.trial.cx);
      const float lift = Clamp((a.trial.cy - gh) / 3.0f, 0.0f, 1.0f);
      const float sw = (0.5f * a.ind->ph.width + 0.2f) / m_pw;
      ShadowPx(world, Px(a.trial.cx), Py(gh), sw * (1.0f + 0.5f * lift), 0.12f / m_pw, 0.45f * al * (1.0f - 0.7f * lift));
    }
    for (const Actor& a : m_actors)
    {
      const float al = ActorAlpha(a);
      if (al <= 0.01f)
        continue;
      const Phenotype& ph = a.ind->ph;
      const Trial& t = a.trial;
      RGB col = a.col;
      if (outro && a.rank > 2 && !a.ghost)
        col = Mix(col, {0.45f, 0.45f, 0.5f}, 0.6f * ot); // the losers grey
      float lift = 0.0f;
      if (outro && a.rank == 0)
      {
        col = Mix(col, {1, 1, 1}, 0.25f * ot);
        lift = 0.0f;
      }
      col = Scale(col, k);
      // the champion's halo
      if (a.rank == 0 && !a.ghost)
      {
        const float pulse = 0.8f + 0.2f * std::sin(m_time * 3.0f);
        GlowPx(world, Px(t.cx), Py(t.cy) - lift, (std::max(ph.width, ph.height) * 0.9f + 0.6f) / m_pw, a.col,
               (outro ? 0.28f + 0.2f * ot : 0.14f) * pulse * al * k);
      }
      const float fade = std::min(m_roundT / 0.8f, 1.0f);
      const float grow = 0.55f + 0.45f * fade; // materialise: thin to full
      for (int pass = 0; pass < 2; pass++)
        for (int s = 0; s < ph.numSegs; s++)
        {
          const Segment& sg = ph.seg[s];
          if ((sg.back != 0) != (pass == 0))
            continue;
          const float ax = Px(t.x[sg.a]), ay = Py(t.y[sg.a]) - lift, bx = Px(t.x[sg.b]), by = Py(t.y[sg.b]) - lift;
          float eff = 0.0f;
          if (s > 0)
          {
            const Joint& j = ph.joint[s - 1];
            eff = Clamp(t.effortNow[s - 1] / std::max(j.speed * kDt, 1e-4f), 0.0f, 1.0f);
          }
          const RGB c = sg.back ? Scale(col, 0.55f) : col;
          if (sg.fin > 0.0f)
          {
            // a membrane: a broad translucent capsule round a thin bone
            CapsulePx(world, ax, ay, bx, by, 0.45f * sg.fin / m_pw * grow, Mix(c, {1, 1, 1}, 0.15f), 0.38f * al,
                      0.0f, 0.3f);
          }
          CapsulePx(world, ax, ay, bx, by, sg.thick / m_pw * grow, c, al, a.ind->stripes, eff * (a.ghost ? 0 : 1));
        }
      // an eye on the torso's leading end
      if (!a.ghost)
      {
        const Segment& s0 = ph.seg[0];
        const int lead = (t.x[s0.b] - t.x[s0.a]) * static_cast<float>(w.dir) >= 0 ? s0.b : s0.a;
        const int tail = lead == s0.b ? s0.a : s0.b;
        float dx = t.x[lead] - t.x[tail], dy = t.y[lead] - t.y[tail];
        const float l = std::sqrt(dx * dx + dy * dy) + 1e-6f;
        dx /= l;
        dy /= l;
        const float r = s0.thick * 0.42f;
        const float ex = t.x[lead] - dx * r * 0.6f - dy * r * 0.9f * static_cast<float>(w.dir);
        const float ey = t.y[lead] - dy * r * 0.6f + dx * r * 0.9f * static_cast<float>(w.dir);
        DiscPx(world, Px(ex), Py(ey) - lift, r / m_pw * grow, Scale({1, 1, 1}, k * 0.95f), al);
        DiscPx(world, Px(ex + dx * r * 0.3f), Py(ey + dy * r * 0.3f) - lift, 0.5f * r / m_pw * grow, {0.02f, 0.02f, 0.04f}, al);
      }
    }
    // names over the heads
    if (m_o.labels && m_o.insight > INS_OFF)
    {
      const float size = 22.0f * m_H / 1080.0f * m_o.textScale;
      const Actor* lead = Leader();
      for (const Actor& a : m_actors)
      {
        const float al = ActorAlpha(a) * k;
        char buf[96];
        const char* label = nullptr;
        if (a.ghost)
        {
          std::snprintf(buf, sizeof(buf), "generation %d's best", m_snap->ghostGen);
          label = buf;
        }
        else if (outro && a.rank <= 2)
        {
          char score[48];
          ScoreText(w.goal, a.ind->res, score, sizeof(score));
          std::snprintf(buf, sizeof(buf), "%d. %s  %s", a.rank + 1, a.ind->name, score);
          label = buf;
        }
        else if (!outro && &a == lead && m_roundT > 2.0f)
        {
          std::snprintf(buf, sizeof(buf), "%s", a.ind->name);
          label = buf;
        }
        if (!label)
          continue;
        float top = 1e9f;
        for (int i = 0; i < a.ind->ph.numParts; i++)
          top = std::min(top, Py(a.trial.y[i] + a.ind->ph.radius[i]));
        DrawText(text, Px(a.trial.cx), top - size * 1.6f, size, a.ghost ? RGB{0.85f, 0.9f, 1.0f} : Mix(a.col, {1, 1, 1}, 0.5f),
                 std::min(al * 1.2f, 1.0f), label, 1);
      }
    }
  }

  // ---------------------------------------------------------------- HUD

  void QueueTicker(const char* s, float hue)
  {
    if (m_nPending >= kPending)
    {
      for (int i = 1; i < kPending; i++)
        m_pending[i - 1] = m_pending[i];
      m_nPending--;
    }
    TickerLine& t = m_pending[m_nPending++];
    std::snprintf(t.text, sizeof(t.text), "%s", s);
    t.hue = hue;
    t.t0 = 0;
  }

  void FeedTicker()
  {
    if (m_snap)
      for (const Event& e : m_snap->events)
        if (e.seq > m_lastSeq)
        {
          m_lastSeq = e.seq;
          QueueTicker(e.text, e.hue);
        }
    // one new line every 2.5 s at most
    if (m_nPending > 0 && m_time - m_lastTickerAt > 2.5f)
    {
      if (m_nTicker >= kTicker)
      {
        for (int i = 1; i < kTicker; i++)
          m_ticker[i - 1] = m_ticker[i];
        m_nTicker--;
      }
      m_ticker[m_nTicker] = m_pending[0];
      m_ticker[m_nTicker].t0 = m_time;
      m_nTicker++;
      for (int i = 1; i < m_nPending; i++)
        m_pending[i - 1] = m_pending[i];
      m_nPending--;
      m_lastTickerAt = m_time;
    }
  }

  RGB HueText(float hue) const { return hue < 0 ? RGB{0.92f, 0.92f, 0.96f} : Mix(Hsv(hue, 0.55f, 1.0f), {1, 1, 1}, 0.35f); }

  // panel alpha: fade when the followed creature is underneath
  float Avoid(float x0, float y0, float x1, float y1) const
  {
    const Actor* lead = m_phase == PH_RUN ? Leader() : Champion();
    if (!lead)
      return 1.0f;
    const float lx = Px(lead->trial.cx), ly = Py(lead->trial.cy);
    const float m = 0.6f / m_pw;
    return (lx > x0 - m && lx < x1 + m && ly > y0 - m && ly < y1 + m) ? 0.3f : 1.0f;
  }

  void BuildHud()
  {
    const Snapshot& s = *m_snap;
    const WorldSpec& w = *s.world;
    m_S = m_H / 1080.0f * m_o.textScale;
    const float S = m_S;
    const float fadeAll = SceneFade() * m_o.bright;
    // slow drift, and swap sides every ten minutes
    const float dx = 14.0f * S * std::sin(m_time / 97.0f), dy = 9.0f * S * std::cos(m_time / 131.0f);
    const bool flip = (static_cast<int>(m_time / 600.0f) & 1) != 0;
    const float margin = 46.0f * S;
    const RGB white = {0.93f, 0.93f, 0.97f}, dim = {0.62f, 0.64f, 0.72f};

    // --- title block
    {
      const float x = (flip ? m_W - margin - 640 * S : margin) + dx, y = margin + dy;
      const float a = fadeAll * Avoid(x, y, x + 640 * S, y + 150 * S);
      char buf[160];
      std::snprintf(buf, sizeof(buf), "Generation %d   -   epoch %d", s.generation, s.epoch);
      DrawText(text, x, y, 24 * S, dim, a, buf);
      DrawText(text, x, y + 32 * S, 42 * S, white, a, GoalName(w.goal));
      char extra[96] = "";
      if (w.goal == G_GLIDE && std::fabs(w.wind) > 0.2f)
        std::snprintf(extra, sizeof(extra), ", wind %.1f m/s", w.wind);
      std::snprintf(buf, sizeof(buf), "on %s   gravity %.2f g   friction %.2f%s", TerrainName(w.terrain), w.gravity / 9.8f,
                    w.friction, extra);
      DrawText(text, x, y + 84 * S, 22 * S, dim, a, buf);
      if (m_phase == PH_RUN)
      {
        const Actor* lead = Leader();
        char score[48] = "";
        if (lead)
          ScoreText(w.goal, lead->trial.res, score, sizeof(score));
        std::snprintf(buf, sizeof(buf), "%.0f / %.0f s    leading: %s, %s", std::min(m_roundT, w.duration), w.duration,
                      lead ? lead->ind->name : "-", score);
        DrawText(text, x, y + 114 * S, 22 * S, HueText(lead ? lead->hue : -1.0f), a, buf);
      }
      else
      {
        char score[48];
        ScoreText(w.goal, s.pop[0].res, score, sizeof(score));
        std::snprintf(buf, sizeof(buf), "Winner: %s, %s", s.pop[0].name, score);
        DrawText(text, x, y + 114 * S, 22 * S, HueText(SpeciesHue(s.pop[0].species)), a, buf);
      }
    }

    // --- the big title when a goal begins
    if (m_o.insight >= INS_LIGHT)
    {
      const float tt = m_time - m_titleT0;
      if (tt >= 0 && tt < 6.0f)
      {
        const float a = fadeAll * Clamp(std::min(tt / 0.8f, (6.0f - tt) / 1.2f), 0.0f, 1.0f);
        const float cy = 0.24f * m_H;
        if (m_titleFirst)
        {
          DrawText(text, 0.5f * m_W, cy - 70 * S, 30 * S, dim, a, "EvolveLife", 1);
          DrawText(text, 0.5f * m_W, cy - 34 * S, 22 * S, dim, a,
                   "every body and brain here evolves from scratch", 1);
        }
        else
          DrawText(text, 0.5f * m_W, cy - 34 * S, 26 * S, dim, a, "A new goal", 1);
        DrawText(text, 0.5f * m_W, cy, 64 * S, white, a, GoalName(w.goal), 1);
      }
    }

    // --- ticker
    if (m_o.ticker)
    {
      // centred in the gap between the bottom panels when they are shown
      const bool rich = m_o.insight >= INS_RICH;
      const float brainW = rich && m_o.neural ? 520.0f * S + 24.0f * S : 0.0f;
      const float cardW = rich && m_card >= 0 ? 600.0f * S + 24.0f * S : 0.0f;
      const float leftW = flip ? cardW : brainW, rightW = flip ? brainW : cardW;
      const float gap = m_W - 2 * margin - leftW - rightW;
      const float tw = std::max(std::min(640.0f * S, gap), 260.0f * S);
      const float x = margin + leftW + 0.5f * gap + dx;
      float y = m_H - margin - 30 * S + dy;
      for (int i = m_nTicker - 1; i >= 0; i--)
      {
        const TickerLine& t = m_ticker[i];
        const float age = m_time - t.t0;
        if (age > 14.0f)
          continue;
        const float a = fadeAll * Clamp(std::min(age / 0.6f, (14.0f - age) / 2.0f), 0.0f, 1.0f);
        char lines[2][128];
        const int n = WrapText(t.text, 24 * S, tw, lines, 2);
        for (int l = n - 1; l >= 0; l--)
        {
          DrawText(text, x, y, 24 * S, HueText(t.hue), a, lines[l], 1);
          y -= 30 * S;
        }
        y -= 8 * S;
      }
    }

    if (m_o.insight < INS_RICH)
      return;

    // --- sparklines: best and mean this epoch, species count
    {
      const float pw = 440 * S, phh = 168 * S;
      const float x0 = (flip ? margin : m_W - margin - pw) + dx, y0 = margin + dy;
      const float a = fadeAll * Avoid(x0, y0, x0 + pw, y0 + phh);
      PanelPx(x0, y0, x0 + pw, y0 + phh, a);
      const GenStats& last = s.history.back();
      char buf[96];
      char score[48];
      ScoreText(w.goal, s.pop[0].res, score, sizeof(score));
      std::snprintf(buf, sizeof(buf), "Best %s", score);
      DrawText(text, x0 + 18 * S, y0 + 12 * S, 24 * S, white, a, buf);
      std::snprintf(buf, sizeof(buf), "%d species", last.species);
      DrawText(text, x0 + pw - 18 * S, y0 + 14 * S, 20 * S, dim, a, buf, 2);
      // this epoch's history
      int first = static_cast<int>(s.history.size()) - 1;
      while (first > 0 && s.history[static_cast<size_t>(first - 1)].epoch == s.epoch &&
             static_cast<int>(s.history.size()) - first < 60)
        first--;
      const int n = static_cast<int>(s.history.size()) - first;
      float hi = 0.1f;
      for (int i = first; i < static_cast<int>(s.history.size()); i++)
        hi = std::max(hi, s.history[static_cast<size_t>(i)].best);
      const float cx0 = x0 + 18 * S, cx1 = x0 + pw - 18 * S, cy0 = y0 + 50 * S, cy1 = y0 + phh - 34 * S;
      LinePx(hud, cx0, cy1, cx1, cy1, 1.0f, dim, 0.35f * a);
      const RGB champ = HueText(SpeciesHue(s.pop[0].species));
      for (int series = 0; series < 2; series++)
      {
        float px = 0, py = 0;
        for (int i = 0; i < n; i++)
        {
          const GenStats& g = s.history[static_cast<size_t>(first + i)];
          const float v = series == 0 ? g.mean : g.best;
          const float x = n > 1 ? cx0 + (cx1 - cx0) * static_cast<float>(i) / static_cast<float>(n - 1) : cx1;
          const float y = cy1 - (cy1 - cy0) * v / hi;
          if (i > 0)
            LinePx(hud, px, py, x, y, series ? 2.5f * S : 1.6f * S, series ? champ : dim, (series ? 0.95f : 0.6f) * a);
          px = x;
          py = y;
        }
        if (n == 1)
          DiscPx(hud, cx1, cy1 - (cy1 - cy0) * (series ? s.history.back().best : s.history.back().mean) / hi, 3 * S,
                 series ? champ : dim, a);
      }
      std::snprintf(buf, sizeof(buf), "best and mean, %d generation%s of this goal", n, n == 1 ? "" : "s");
      DrawText(text, x0 + 18 * S, y0 + phh - 28 * S, 18 * S, dim, a, buf);
    }

    // --- neural view (bottom left, or right when flipped)
    const float bh = 280 * S;
    const float by0 = m_H - margin - bh + dy;
    if (m_o.neural)
    {
      const float nw = 520 * S;
      const float x0 = (flip ? m_W - margin - nw : margin) + dx;
      BuildBrain(x0, by0, nw, bh, fadeAll * Avoid(x0, by0, x0 + nw, by0 + bh));
    }
    // --- info card (bottom right, or left)
    if (m_card >= 0)
    {
      const float cw = 600 * S;
      const float x0 = (flip ? margin : m_W - margin - cw) + dx;
      const float age = m_time - m_cardStart;
      const float a = fadeAll * Avoid(x0, by0, x0 + cw, by0 + bh) * Clamp(age / 0.8f, 0.0f, 1.0f);
      PanelPx(x0, by0, x0 + cw, by0 + bh, a);
      BuildCard(x0, by0, cw, bh, a);
    }

    // --- the process, at the Full level
    if (m_o.insight >= INS_FULL)
    {
      char buf[200];
      std::snprintf(buf, sizeof(buf),
                    "%d creatures   %.0f ms a generation   %.0f evaluations/s   step %.2f ms   %.0f fps   %d thread%s   "
                    "seed %llu   exploits %d   repairs %d",
                    static_cast<int>(s.pop.size()), s.evalMs, s.evalsPerSec, m_stepMs, m_fps, m_threads,
                    m_threads == 1 ? "" : "s", static_cast<unsigned long long>(s.seed), s.totals.exploits,
                    s.totals.repairs + s.totals.rerolls);
      DrawText(text, 0.5f * m_W + dx, 12 * S, 17 * S, dim, 0.7f * fadeAll, buf, 1);
    }
  }

  // ---- the neural view

  struct NodePos
  {
    int16_t local;
    float x, y; // 0..1 in the graph area
    uint8_t group;
  };

  void Layout(const Actor& a)
  {
    const Net& net = a.trial.net;
    m_layoutId = a.ind->id;
    m_nodes.clear();
    m_nodeOf.assign(static_cast<size_t>(net.numNodes), -1);
    // inputs with a link out of them, outputs for the joints this body has, all hidden
    // an input is shown if it feeds a hidden node or a joint this body has
    std::vector<uint8_t> used(static_cast<size_t>(net.numNodes), 0);
    const int njoints = a.ind->ph.numJoints;
    for (size_t o = 0; o < net.order.size(); o++)
    {
      const int dst = net.order[o];
      if (dst < HID0 && dst - OUT0 >= njoints)
        continue;
      for (int l = net.first[o]; l < net.first[o + 1]; l++)
        used[static_cast<size_t>(net.links[static_cast<size_t>(l)].src)] = 1;
    }
    auto group = [](int i) -> uint8_t {
      if (i < IN_CONTACT)
        return 0; // joints
      if (i < IN_SIN)
        return 1; // feet
      if (i < IN_TX)
        return 2; // body
      if (i < IN_CLK1S)
        return 3; // goal
      return 4;   // clocks, energy, bias
    };
    std::vector<int> ins;
    for (int i = 0; i < N_IN; i++)
      if (used[static_cast<size_t>(i)])
        ins.push_back(i);
    for (size_t k = 0; k < ins.size(); k++)
    {
      m_nodeOf[static_cast<size_t>(ins[k])] = static_cast<int>(m_nodes.size());
      m_nodes.push_back({static_cast<int16_t>(ins[k]), 0.0f,
                         ins.size() > 1 ? static_cast<float>(k) / static_cast<float>(ins.size() - 1) : 0.5f, group(ins[k])});
    }
    const int nj = a.ind->ph.numJoints;
    for (int j = 0; j < nj; j++)
    {
      m_nodeOf[static_cast<size_t>(OUT0 + j)] = static_cast<int>(m_nodes.size());
      m_nodes.push_back({static_cast<int16_t>(OUT0 + j), 1.0f, nj > 1 ? static_cast<float>(j) / static_cast<float>(nj - 1) : 0.5f, 5});
    }
    const size_t firstHidden = m_nodes.size();
    for (int i = HID0; i < net.numNodes; i++)
    {
      m_nodeOf[static_cast<size_t>(i)] = static_cast<int>(m_nodes.size());
      m_nodes.push_back({static_cast<int16_t>(i), Clamp(net.depth[static_cast<size_t>(i)], 0.15f, 0.85f), 0.5f, 6});
    }
    // hidden nodes settle between their neighbours, then spread apart
    for (int it = 0; it < 30; it++)
      for (size_t k = firstHidden; k < m_nodes.size(); k++)
      {
        float sum = 0;
        int n = 0;
        const int local = m_nodes[k].local;
        for (size_t o = 0; o < net.order.size(); o++)
          for (int l = net.first[o]; l < net.first[o + 1]; l++)
          {
            const int src = net.links[static_cast<size_t>(l)].src, dst = net.order[o];
            const int other = src == local ? dst : (dst == local ? src : -1);
            if (other < 0 || other == local)
              continue;
            const int idx = m_nodeOf[static_cast<size_t>(other)];
            if (idx < 0)
              continue;
            sum += m_nodes[static_cast<size_t>(idx)].y;
            n++;
          }
        if (n)
          m_nodes[k].y = 0.5f * m_nodes[k].y + 0.5f * sum / static_cast<float>(n);
        for (size_t o = firstHidden; o < m_nodes.size(); o++)
        {
          if (o == k)
            continue;
          const float ddx = m_nodes[o].x - m_nodes[k].x, ddy = m_nodes[o].y - m_nodes[k].y;
          if (ddx * ddx + ddy * ddy < 0.012f)
            m_nodes[k].y += ddy > 0 ? -0.02f : 0.02f;
        }
        m_nodes[k].y = Clamp(m_nodes[k].y, 0.0f, 1.0f);
      }
    m_prevVal.assign(static_cast<size_t>(net.numNodes), 0.0f);
    m_flash.assign(static_cast<size_t>(net.numNodes), 0.0f);
  }

  void UpdateBrainFlash()
  {
    const Actor* a = Champion();
    if (!a || a->ghost || a->ind->id != m_layoutId || m_flash.size() != a->trial.net.val.size())
      return;
    const std::vector<float>& v = a->trial.net.val;
    for (size_t i = 0; i < v.size(); i++)
    {
      if (std::fabs(v[i] - m_prevVal[i]) > 0.35f)
        m_flash[i] = 1.0f;
      m_flash[i] *= 0.9f;
      m_prevVal[i] = v[i];
    }
  }

  void BuildBrain(float x0, float y0, float w, float h, float a)
  {
    const Actor* ch = Champion();
    if (!ch || ch->ghost)
      return;
    if (ch->ind->id != m_layoutId)
      Layout(*ch);
    const float S = m_S;
    PanelPx(x0, y0, x0 + w, y0 + h, a);
    const Net& net = ch->trial.net;
    const RGB white = {0.93f, 0.93f, 0.97f}, dim = {0.62f, 0.64f, 0.72f};
    char buf[96];
    std::snprintf(buf, sizeof(buf), "Brain of %s, live", ch->ind->name);
    DrawText(text, x0 + 18 * S, y0 + 12 * S, 23 * S, white, a, buf);
    std::snprintf(buf, sizeof(buf), "%d neurons, %d links", static_cast<int>(ch->ind->brain.hidden.size()),
                  static_cast<int>(net.links.size()));
    DrawText(text, x0 + w - 18 * S, y0 + 15 * S, 18 * S, dim, a, buf, 2);
    const float gx0 = x0 + 96 * S, gx1 = x0 + w - 90 * S, gy0 = y0 + 54 * S, gy1 = y0 + h - 22 * S;
    auto X = [&](const NodePos& n) { return gx0 + (gx1 - gx0) * n.x; };
    auto Y = [&](const NodePos& n) { return gy0 + (gy1 - gy0) * n.y; };
    const RGB warm = {1.0f, 0.62f, 0.32f}, cool = {0.35f, 0.65f, 1.0f};
    // links (strongest drawn when the brain is big)
    const size_t maxLinks = 140;
    for (size_t o = 0; o < net.order.size(); o++)
      for (int l = net.first[o]; l < net.first[o + 1]; l++)
      {
        if (static_cast<size_t>(l) > maxLinks && std::fabs(net.links[static_cast<size_t>(l)].w) < 1.0f)
          continue;
        const Net::Link& L = net.links[static_cast<size_t>(l)];
        const int si = m_nodeOf[static_cast<size_t>(L.src)], di = m_nodeOf[static_cast<size_t>(net.order[o])];
        if (si < 0 || di < 0)
          continue;
        const NodePos& sn = m_nodes[static_cast<size_t>(si)];
        const NodePos& dn = m_nodes[static_cast<size_t>(di)];
        const float act = std::fabs(L.w * net.val[static_cast<size_t>(L.src)]);
        const float al = (0.10f + 0.55f * std::min(act, 1.0f)) * a;
        const float width = (0.8f + 1.4f * std::min(std::fabs(L.w) / 3.0f, 1.0f)) * S;
        const RGB c = L.w >= 0 ? warm : cool;
        if (sn.x >= dn.x)
        {
          // recurrent: an arc over the top
          const float mx = 0.5f * (X(sn) + X(dn)), my = std::min(Y(sn), Y(dn)) - 26 * S;
          LinePx(hud, X(sn), Y(sn), mx, my, width, c, al);
          LinePx(hud, mx, my, X(dn), Y(dn), width, c, al);
        }
        else
          LinePx(hud, X(sn), Y(sn), X(dn), Y(dn), width, c, al);
      }
    // nodes
    static const RGB kGroup[7] = {{0.55f, 0.75f, 1.0f}, {0.5f, 1.0f, 0.7f}, {0.85f, 0.8f, 1.0f}, {1.0f, 0.9f, 0.5f},
                                  {0.8f, 0.8f, 0.85f},  {1.0f, 0.6f, 0.45f}, {1.0f, 1.0f, 1.0f}};
    const RGB hid = HueText(ch->hue);
    for (const NodePos& n : m_nodes)
    {
      const float v = net.val[static_cast<size_t>(n.local)];
      const float f = m_flash.empty() ? 0.0f : m_flash[static_cast<size_t>(n.local)];
      RGB c = n.group == 6 ? hid : kGroup[n.group];
      c = Mix(Scale(c, 0.35f + 0.65f * std::fabs(v)), {1, 1, 1}, 0.6f * f);
      DiscPx(hud, X(n), Y(n), (2.6f + 3.4f * std::fabs(v) + 2.0f * f) * S, c, a);
    }
    // group labels
    static const char* kLabels[] = {"joints", "feet", "body", "goal", "clocks"};
    for (int gi = 0; gi < 5; gi++)
    {
      float sum = 0;
      int k = 0;
      for (const NodePos& n : m_nodes)
        if (n.group == gi)
        {
          sum += n.y;
          k++;
        }
      if (k)
        DrawText(text, gx0 - 14 * S, gy0 + (gy1 - gy0) * sum / static_cast<float>(k) - 10 * S, 17 * S, kGroup[gi],
                 0.85f * a, kLabels[gi], 2);
    }
    DrawText(text, gx1 + 14 * S, 0.5f * (gy0 + gy1) - 10 * S, 17 * S, kGroup[5], 0.85f * a, "muscles");
  }

  // ---- info cards

  void CardTitle(float x0, float y0, const char* t, float a)
  {
    DrawText(text, x0 + 20 * m_S, y0 + 14 * m_S, 26 * m_S, {0.95f, 0.95f, 1.0f}, a, t);
  }

  void CardLine(float x, float y, const char* t, float a, const RGB& c = {0.80f, 0.82f, 0.88f}, float size = 22.0f)
  {
    DrawText(text, x, y, size * m_S, c, a, t);
  }

  // A small line chart; values per series, colours, in a rectangle.
  void Chart(float x0, float y0, float x1, float y1, const float* const* series, const RGB* cols, int nSeries, int n,
             float a)
  {
    float hi = 1e-3f;
    for (int s = 0; s < nSeries; s++)
      for (int i = 0; i < n; i++)
        hi = std::max(hi, series[s][i]);
    LinePx(hud, x0, y1, x1, y1, 1.0f, {0.6f, 0.62f, 0.7f}, 0.4f * a);
    for (int s = 0; s < nSeries; s++)
    {
      float px = 0, py = 0;
      for (int i = 0; i < n; i++)
      {
        const float x = n > 1 ? x0 + (x1 - x0) * static_cast<float>(i) / static_cast<float>(n - 1) : x1;
        const float y = y1 - (y1 - y0) * series[s][i] / hi;
        if (i > 0)
          LinePx(hud, px, py, x, y, (s == 0 ? 2.4f : 1.6f) * m_S, cols[s], 0.9f * a);
        px = x;
        py = y;
      }
    }
  }

  void BuildCard(float x0, float y0, float w, float h, float a)
  {
    const Snapshot& s = *m_snap;
    const WorldSpec& wd = *s.world;
    const float S = m_S;
    const float lx = x0 + 20 * S;
    float ly = y0 + 56 * S;
    const float lh = 30 * S;
    const RGB dim = {0.62f, 0.64f, 0.72f}, body = {0.82f, 0.84f, 0.9f};
    char buf[192], score[48];
    const Individual& champ = s.pop[0];
    const RGB champCol = HueText(SpeciesHue(champ.species));
    switch (m_card)
    {
      case CARD_PROFILE:
      {
        std::snprintf(buf, sizeof(buf), "Champion: %s, gen %d", champ.name, champ.born);
        CardTitle(x0, y0, buf, a);
        ScoreText(wd.goal, champ.res, score, sizeof(score));
        const float tx = x0 + 230 * S;
        std::snprintf(buf, sizeof(buf), "Result: %s", score);
        CardLine(tx, ly, buf, a, champCol);
        std::snprintf(buf, sizeof(buf), "%d segments, %d limbs%s", champ.traits.segs, champ.traits.limbs,
                      champ.traits.fins ? (champ.traits.fins > 1 ? ", fins" : ", a fin") : "");
        CardLine(tx, ly + lh, buf, a);
        std::snprintf(buf, sizeof(buf), "Brain: %d neurons, %d links", static_cast<int>(champ.brain.hidden.size()),
                      champ.brain.Enabled());
        CardLine(tx, ly + 2 * lh, buf, a);
        std::snprintf(buf, sizeof(buf), "Lineage: %d generations deep", champ.lineage);
        CardLine(tx, ly + 3 * lh, buf, a);
        Unusual(buf, sizeof(buf));
        char lines[2][128];
        const int n = WrapText(buf, 21 * S, w - 250 * S, lines, 2);
        for (int i = 0; i < n; i++)
          CardLine(tx, ly + (4.3f + static_cast<float>(i) * 0.9f) * lh, lines[i], a, dim, 21);
        Silhouette(champ, x0 + 20 * S, y0 + 56 * S, 190 * S, h - 76 * S, champCol, a);
        break;
      }
      case CARD_BRIEFING:
      {
        std::snprintf(buf, sizeof(buf), "The goal: %s", GoalName(wd.goal));
        CardTitle(x0, y0, buf, a);
        static const char* kHow[GOAL_COUNT] = {
            "Score: distance travelled in the direction of the arrow.",
            "Score: how much closer they get; reaching it, and reaching it fast, earn a bonus.",
            "Score: progress up the hill towards the beacon on top.",
            "Score: distance before the edge; getting across earns a bonus. Falling in ends the run.",
            "Score: the highest the whole body gets off the ground.",
            "Score: how far past the cliff edge they land, plus time in the air.",
            "Score: distance travelled over the bumps."};
        char lines[3][128];
        const int n = WrapText(kHow[wd.goal], 21 * S, w - 40 * S, lines, 2);
        for (int i = 0; i < n; i++)
          CardLine(lx, ly + static_cast<float>(i) * 26 * S, lines[i], a, body, 21);
        ly += static_cast<float>(n) * 26 * S + 8 * S;
        std::snprintf(buf, sizeof(buf), "%s, gravity %.2f g, friction %.2f%s", TerrainName(wd.terrain), wd.gravity / 9.8f,
                      wd.friction, wd.goal == G_GLIDE ? ", thick air" : "");
        CardLine(lx, ly, buf, a, dim, 20);
        const GenStats& g = s.history.back();
        ScoreText(wd.goal, champ.res, score, sizeof(score));
        if (wd.goal == G_BEACON || wd.goal == G_CLIMB || wd.goal == G_CHASM)
          std::snprintf(buf, sizeof(buf), "%d of %d %s this generation; best %s", s.reached, static_cast<int>(s.pop.size()),
                        wd.goal == G_CHASM ? "got across" : "reached it", score);
        else
          std::snprintf(buf, sizeof(buf), "Best %s, mean score %.1f", score, g.mean);
        CardLine(lx, ly + 28 * S, buf, a, champCol, 20);
        if (s.epochLen > 0)
          std::snprintf(buf, sizeof(buf), "Epoch %d: generation %d of %d", s.epoch, s.epochGen + 1, s.epochLen);
        else
          std::snprintf(buf, sizeof(buf), "Epoch %d: generation %d", s.epoch, s.epochGen + 1);
        CardLine(lx, ly + 56 * S, buf, a, dim, 20);
        Profile(x0 + 20 * S, ly + 90 * S, x0 + w - 20 * S, y0 + h - 16 * S, a);
        break;
      }
      case CARD_TOTALS:
      {
        CardTitle(x0, y0, "Run totals", a);
        const Totals& t = s.totals;
        std::snprintf(buf, sizeof(buf), "%llu creatures born in %d generations (%.0f min)",
                      static_cast<unsigned long long>(t.born), t.generations, s.minutes);
        CardLine(lx, ly, buf, a);
        std::snprintf(buf, sizeof(buf), "%.1f creature-hours simulated", t.creatureSeconds / 3600.0);
        CardLine(lx, ly + lh, buf, a);
        std::snprintf(buf, sizeof(buf), "%.1f km travelled in all, %d tumbles", t.distance / 1000.0, t.tumbles);
        CardLine(lx, ly + 2 * lh, buf, a);
        std::snprintf(buf, sizeof(buf), "Longest time airborne %.1f s, highest jump %.2f m", t.longestFlight, t.highestJump);
        CardLine(lx, ly + 3 * lh, buf, a);
        std::snprintf(buf, sizeof(buf), "Longest glide %.1f m", t.longestGlide);
        CardLine(lx, ly + 4 * lh, buf, a);
        std::snprintf(buf, sizeof(buf), "%d physics exploits caught, %d body niches filled of %d", t.exploits,
                      s.archiveFilled, s.archiveCells);
        CardLine(lx, ly + 5 * lh, buf, a, dim, 20);
        break;
      }
      case CARD_FITNESS:
      case CARD_BRAIN:
      {
        const int n = std::min(static_cast<int>(s.history.size()), 120);
        const size_t first = s.history.size() - static_cast<size_t>(n);
        m_chartA.resize(static_cast<size_t>(n));
        m_chartB.resize(static_cast<size_t>(n));
        for (int i = 0; i < n; i++)
        {
          const GenStats& g = s.history[first + static_cast<size_t>(i)];
          m_chartA[static_cast<size_t>(i)] = m_card == CARD_FITNESS ? g.best : static_cast<float>(g.champConns);
          m_chartB[static_cast<size_t>(i)] = m_card == CARD_FITNESS ? g.mean : static_cast<float>(g.champHidden) * 4.0f;
        }
        const float* series[2] = {m_chartA.data(), m_chartB.data()};
        const GenStats& g0 = s.history[first];
        const GenStats& g1 = s.history.back();
        if (m_card == CARD_FITNESS)
        {
          std::snprintf(buf, sizeof(buf), "Fitness, last %d generations", n);
          CardTitle(x0, y0, buf, a);
          const RGB cols[2] = {champCol, dim};
          Chart(lx, ly + 34 * S, x0 + w - 20 * S, y0 + h - 22 * S, series, cols, 2, n, a);
          std::snprintf(buf, sizeof(buf), "best (bright) and mean; goals change at the dips");
          CardLine(lx, ly, buf, a, dim, 19);
        }
        else
        {
          CardTitle(x0, y0, "Brain growth of the champions", a);
          const RGB cols[2] = {{1.0f, 0.62f, 0.32f}, {0.6f, 0.85f, 1.0f}};
          Chart(lx, ly + 34 * S, x0 + w - 20 * S, y0 + h - 22 * S, series, cols, 2, n, a);
          std::snprintf(buf, sizeof(buf), "links %d -> %d (orange), neurons %d -> %d (blue)", g0.champConns, g1.champConns,
                        g0.champHidden, g1.champHidden);
          CardLine(lx, ly, buf, a, dim, 19);
        }
        // epoch boundaries
        for (int i = 1; i < n; i++)
          if (s.history[first + static_cast<size_t>(i)].epoch != s.history[first + static_cast<size_t>(i) - 1].epoch)
          {
            const float x = lx + (x0 + w - 20 * S - lx) * static_cast<float>(i) / static_cast<float>(std::max(n - 1, 1));
            LinePx(hud, x, ly + 34 * S, x, y0 + h - 22 * S, 1.0f, dim, 0.3f * a);
          }
        break;
      }
      case CARD_SPECIES:
      {
        std::snprintf(buf, sizeof(buf), "Species: %d alive", static_cast<int>(s.species.size()));
        CardTitle(x0, y0, buf, a);
        // stacked sizes over time, coloured by species
        const int n = std::min(static_cast<int>(s.history.size()), 80);
        const size_t first = s.history.size() - static_cast<size_t>(n);
        const float cx0 = lx, cx1 = x0 + w - 220 * S, cy0 = ly, cy1 = y0 + h - 22 * S;
        const float bw = (cx1 - cx0) / static_cast<float>(std::max(n, 1));
        for (int i = 0; i < n; i++)
        {
          const GenStats& g = s.history[first + static_cast<size_t>(i)];
          int total = 0;
          for (int k = 0; k < g.nsp; k++)
            total += g.sp[k].size;
          float y = cy1;
          for (int k = 0; k < g.nsp; k++)
          {
            const float hh = (cy1 - cy0) * static_cast<float>(g.sp[k].size) / static_cast<float>(std::max(total, 1));
            const float bx = cx0 + bw * static_cast<float>(i);
            QuadPx(hud, bx, y - hh, bx + bw + 0.5f, y, PackPre(Hsv(g.sp[k].hue, 0.6f, 0.85f), 0.85f * a), PackPar(LK_FLAT, 0, 0, 0));
            y -= hh;
          }
        }
        // the biggest species
        int row = 0;
        for (const SpeciesView& v : s.species)
        {
          if (row >= 6)
            break;
          std::snprintf(buf, sizeof(buf), "%s %d", v.name, v.size);
          DiscPx(hud, x0 + w - 200 * S, cy0 + 12 * S + static_cast<float>(row) * 30 * S, 6 * S, Hsv(v.hue, 0.6f, 1.0f), a);
          CardLine(x0 + w - 184 * S, cy0 + static_cast<float>(row) * 30 * S, buf, a, HueText(v.hue), 20);
          row++;
        }
        break;
      }
      case CARD_FAMILY:
      {
        std::snprintf(buf, sizeof(buf), "Family tree of %s", champ.name);
        CardTitle(x0, y0, buf, a);
        const int n = champ.nAnc + 1;
        const float cx0 = lx + 20 * S, cx1 = x0 + w - 40 * S, cy = y0 + 0.58f * h;
        float px = 0;
        for (int i = 0; i < n; i++)
        {
          const bool self = i == n - 1;
          const float x = n > 1 ? cx0 + (cx1 - cx0) * static_cast<float>(i) / static_cast<float>(n - 1) : cx1;
          if (i > 0)
            LinePx(hud, px, cy, x, cy, 2.0f * S, dim, 0.6f * a);
          px = x;
          const int gen = self ? champ.born : champ.anc[i].gen;
          const uint32_t fl = self ? champ.mutFlags : champ.anc[i].flags;
          const int segs = self ? champ.traits.segs : champ.anc[i].segs;
          DiscPx(hud, x, cy, (self ? 9.0f : 6.0f) * S, self ? champCol : Mix(champCol, dim, 0.5f), a);
          std::snprintf(buf, sizeof(buf), "g%d", gen);
          DrawText(text, x, cy + 16 * S, 18 * S, dim, a, buf, 1);
          std::snprintf(buf, sizeof(buf), "%d seg", segs);
          DrawText(text, x, cy + 38 * S, 16 * S, dim, 0.8f * a, buf, 1);
          const char* tag = (fl & MF_FIN) ? "+fin" : (fl & MF_LIMB) ? "+limb" : (fl & MF_NEURON) ? "+neuron"
                          : (fl & MF_IMMIGRANT) ? "new" : (fl & MF_MIRROR) ? "mirror" : (fl & MF_LOSE) ? "-part"
                          : (fl & MF_CROSS) ? "mated" : (fl & MF_SYNAPSE) ? "+link" : "";
          if (*tag)
            DrawText(text, x, cy - 40 * S - (i % 2 ? 22 * S : 0), 18 * S, HueText(SpeciesHue(champ.species)), a, tag, 1);
        }
        CardLine(lx, y0 + 50 * S, "the champion's last ancestors and what changed in each", a, dim, 19);
        break;
      }
      case CARD_THENNOW:
      {
        CardTitle(x0, y0, "Then and now", a);
        char then[48];
        ScoreText(wd.goal, s.ghost.res, then, sizeof(then));
        ScoreText(wd.goal, champ.res, score, sizeof(score));
        std::snprintf(buf, sizeof(buf), "Generation %d's best (white ghost): %s", s.ghostGen, then);
        CardLine(lx, ly, buf, a, {0.85f, 0.9f, 1.0f});
        std::snprintf(buf, sizeof(buf), "Generation %d's best: %s", s.generation, score);
        CardLine(lx, ly + lh, buf, a, champCol);
        if (s.ghost.fitness > 0.05f)
          std::snprintf(buf, sizeof(buf), "%.1fx the score after %d generations", champ.fitness / s.ghost.fitness,
                        s.generation - s.ghostGen);
        else
          std::snprintf(buf, sizeof(buf), "from nothing to %s in %d generations", score, s.generation - s.ghostGen);
        CardLine(lx, ly + 2.2f * lh, buf, a, {1, 1, 1}, 26);
        std::snprintf(buf, sizeof(buf), "Both run the same course on stage now, same world, same start.");
        CardLine(lx, ly + 3.6f * lh, buf, a, dim, 20);
        break;
      }
      case CARD_MILESTONES:
      {
        CardTitle(x0, y0, "Milestones", a);
        for (int m = 0; m < MS_COUNT; m++)
        {
          const MilestoneHit& ms = s.milestones[m];
          if (ms.hit)
            std::snprintf(buf, sizeof(buf), "%s: %s, gen %d (%.0f min)", MilestoneName(m), ms.who, ms.gen, ms.minutes);
          else
            std::snprintf(buf, sizeof(buf), "%s: not yet", MilestoneName(m));
          CardLine(lx, ly + static_cast<float>(m) * lh, buf, ms.hit ? a : 0.5f * a, ms.hit ? body : dim, 21);
        }
        break;
      }
      case CARD_HALL:
      {
        CardTitle(x0, y0, "Hall of fame", a);
        int row = 0;
        for (int g = 0; g < GOAL_COUNT && row < 7; g++)
        {
          const HallEntry& e = s.hall[g];
          if (!e.set)
            continue;
          std::snprintf(buf, sizeof(buf), "%s: %s, %s (gen %d)", GoalName(g), e.name, e.score, e.gen);
          CardLine(lx, ly + static_cast<float>(row) * lh, buf, a, body, 21);
          row++;
        }
        if (row <= 1)
          CardLine(lx, ly + static_cast<float>(row) * lh, "More goals come up as the run goes on.", a, dim, 20);
        break;
      }
      case CARD_COMMENTARY:
      {
        CardTitle(x0, y0, "Meanwhile", a);
        char lines[4][128];
        float y = ly;
        for (int k = 0; k < 3; k++)
        {
          Commentary(static_cast<int>((m_cardVariant >> (k * 4)) % 6), k, buf, sizeof(buf));
          if (!buf[0])
            continue;
          const int n = WrapText(buf, 22 * S, w - 40 * S, lines, 2);
          for (int i = 0; i < n; i++)
          {
            CardLine(lx, y, lines[i], a, body, 22);
            y += 27 * S;
          }
          y += 10 * S;
        }
        break;
      }
      case CARD_FACT:
      {
        CardTitle(x0, y0, "Did you know?", a);
        static const char* kFacts[] = {
            "In NEAT, every new connection gets an innovation number, so two brains can be lined up gene by gene for "
            "crossover.",
            "Karl Sims evolved block creatures with coupled bodies and brains in 1994; their bodies grew from "
            "recursive graphs, as these do.",
            "Speciation protects new ideas: a new body plan competes mostly within its own species until it is good "
            "enough to take on the rest.",
            "Most mutations are neutral or harmful. Selection keeps the rare ones that help.",
            "No gait is written anywhere in this program. The clocks give each brain a beat; evolution finds what to "
            "do with it.",
            "MAP-Elites keeps the best creature for each kind of body, not just the overall best, so odd designs "
            "survive to be tried again.",
            "Unrelated lineages often find the same solution. Wings evolved separately in insects, pterosaurs, birds "
            "and bats.",
            "Each creature here is tested alone in its own copy of the world, so they never collide or get in each "
            "other's way.",
            "In small populations, chance alone can fix or lose a trait. Biologists call it genetic drift.",
            "Fitness sharing divides a creature's score by its species' size, so no single species can crowd out the "
            "others.",
            "Real neurons fire in spikes. These pass smooth values through a tanh curve thirty times a second.",
            "Richard Lenski's E. coli populations have been evolving in his lab since 1988, for more than 75,000 "
            "generations.",
            "Bodies mutate here too: limbs are added, removed, duplicated, mirrored and chained, and fins come and go.",
            "Peter and Rosemary Grant measured the beaks of Galapagos finches change in a few generations after a "
            "drought.",
            "A creature's score is cut if its joints chatter faster than about five times a second, which closes a "
            "physics loophole."};
        const int nf = static_cast<int>(sizeof(kFacts) / sizeof(kFacts[0]));
        char lines[6][128];
        const int n = WrapText(kFacts[m_cardVariant % static_cast<uint32_t>(nf)], 24 * S, w - 40 * S, lines, 6);
        for (int i = 0; i < n; i++)
          CardLine(lx, ly + static_cast<float>(i) * 31 * S, lines[i], a, body, 24);
        break;
      }
      case CARD_MAP:
      {
        CardTitle(x0, y0, "Species map", a);
        CardLine(lx, ly - 4 * S, "every creature by body size (across) and brain size (up)", a, dim, 19);
        const float cx0 = lx + 10 * S, cx1 = x0 + w - 30 * S, cy0 = ly + 28 * S, cy1 = y0 + h - 26 * S;
        LinePx(hud, cx0, cy1, cx1, cy1, 1.0f, dim, 0.4f * a);
        LinePx(hud, cx0, cy0, cx0, cy1, 1.0f, dim, 0.4f * a);
        int maxConns = 10;
        for (const Individual& ind : s.pop)
          maxConns = std::max(maxConns, ind.brain.Enabled());
        for (const Individual& ind : s.pop)
        {
          const uint32_t hsh = Hash(static_cast<uint32_t>(ind.id));
          const float jx = (static_cast<float>(hsh & 255) / 255.0f - 0.5f) * 0.8f;
          const float jy = (static_cast<float>((hsh >> 8) & 255) / 255.0f - 0.5f) * 0.05f;
          const float fx = (static_cast<float>(ind.traits.segs) - 1.5f + jx) / static_cast<float>(s.maxSegs);
          const float fy = static_cast<float>(ind.brain.Enabled()) / static_cast<float>(maxConns) + jy;
          DiscPx(hud, cx0 + (cx1 - cx0) * Clamp(fx, 0, 1), cy1 - (cy1 - cy0) * Clamp(fy, 0, 1), 3.5f * S,
                 Hsv(SpeciesHue(ind.species), 0.6f, 1.0f), 0.9f * a);
        }
        break;
      }
      default:
        break;
    }
  }

  // the champion's body at rest, in a box
  void Silhouette(const Individual& ind, float x0, float y0, float w, float h, const RGB& c, float a)
  {
    const Phenotype& ph = ind.ph;
    float minx = 1e9f, maxx = -1e9f, maxy = 0;
    for (int i = 0; i < ph.numParts; i++)
    {
      minx = std::min(minx, ph.px[i] - ph.radius[i]);
      maxx = std::max(maxx, ph.px[i] + ph.radius[i]);
      maxy = std::max(maxy, ph.py[i] + ph.radius[i]);
    }
    const float k = std::min(w / std::max(maxx - minx, 0.1f), h / std::max(maxy, 0.1f)) * 0.9f;
    const float ox = x0 + 0.5f * w - 0.5f * (minx + maxx) * k, oy = y0 + 0.5f * h + 0.5f * maxy * k;
    for (int pass = 0; pass < 2; pass++)
      for (int s = 0; s < ph.numSegs; s++)
      {
        const Segment& sg = ph.seg[s];
        if ((sg.back != 0) != (pass == 0))
          continue;
        const float ax = ox + ph.px[sg.a] * k, ay = oy - ph.py[sg.a] * k, bx = ox + ph.px[sg.b] * k, by = oy - ph.py[sg.b] * k;
        const RGB cc = sg.back ? Scale(c, 0.55f) : c;
        if (sg.fin > 0)
          CapsulePx(hud, ax, ay, bx, by, 0.45f * sg.fin * k, cc, 0.35f * a, 0.0f);
        CapsulePx(hud, ax, ay, bx, by, sg.thick * k, cc, a, ind.stripes);
      }
  }

  // the course in miniature
  void Profile(float x0, float y0, float x1, float y1, float a)
  {
    const WorldSpec& w = *m_snap->world;
    if (y1 - y0 < 20 * m_S)
      return;
    const float d = static_cast<float>(w.dir);
    float lo = w.startX - d * 3.0f, hi = w.startX + d * 24.0f;
    if (w.hasTarget)
      hi = w.targetX + d * 4.0f;
    if (lo > hi)
      std::swap(lo, hi);
    float ymin = 1e9f, ymax = -1e9f;
    for (int i = 0; i <= 60; i++)
    {
      const float x = lo + (hi - lo) * static_cast<float>(i) / 60.0f;
      ymin = std::min(ymin, w.Height(x));
      ymax = std::max(ymax, w.Height(x));
    }
    ymax = std::max(ymax, ymin + 2.0f);
    if (w.hasTarget)
      ymax = std::max(ymax, w.targetY);
    auto X = [&](float x) { return x0 + (x1 - x0) * (x - lo) / (hi - lo); };
    auto Y = [&](float y) { return y1 - (y1 - y0) * (y - ymin) / (ymax - ymin); };
    float px = X(lo), py = Y(w.Height(lo));
    for (int i = 1; i <= 60; i++)
    {
      const float x = lo + (hi - lo) * static_cast<float>(i) / 60.0f;
      const float nx = X(x), ny = Y(w.Height(x));
      LinePx(hud, px, py, nx, ny, 2.0f * m_S, m_palette.edge, 0.8f * a);
      px = nx;
      py = ny;
    }
    DiscPx(hud, X(w.startX), Y(w.Height(w.startX)) - 6 * m_S, 5 * m_S, {1, 1, 1}, a);
    if (w.hasTarget)
      DiscPx(hud, X(w.targetX), Y(w.targetY), 6 * m_S, m_palette.beacon, a);
  }

  void Unusual(char* out, size_t n) const
  {
    const Snapshot& s = *m_snap;
    const Individual& c = s.pop[0];
    int maxLimbs = 0, maxHidden = 0, finned = 0, maxLineage = 0;
    float minMass = 1e9f;
    for (const Individual& ind : s.pop)
    {
      maxLimbs = std::max(maxLimbs, ind.traits.limbs);
      maxHidden = std::max(maxHidden, static_cast<int>(ind.brain.hidden.size()));
      finned += ind.traits.fins > 0;
      maxLineage = std::max(maxLineage, ind.lineage);
      minMass = std::min(minMass, ind.traits.mass);
    }
    if (c.traits.fins > 0 && finned <= 2)
      std::snprintf(out, n, "One of the only finned bodies in the population.");
    else if (c.traits.limbs == maxLimbs && maxLimbs >= 3)
      std::snprintf(out, n, "The most limbs in the population: %d.", maxLimbs);
    else if (static_cast<int>(c.brain.hidden.size()) == maxHidden && maxHidden > 0)
      std::snprintf(out, n, "The biggest brain here: %d hidden neurons.", maxHidden);
    else if (c.traits.mass <= minMass * 1.01f)
      std::snprintf(out, n, "The lightest body in the population.");
    else if (c.lineage == maxLineage && maxLineage > 3)
      std::snprintf(out, n, "The oldest lineage here: %d generations.", maxLineage);
    else if (c.res.jumps >= 5)
      std::snprintf(out, n, "It moves in %d leaps, airborne %.1f s of the run.", c.res.jumps, c.res.airtime);
    else
      std::snprintf(out, n, "It has %d joints, all driven by its own brain.", c.ph.numJoints);
  }

  void Commentary(int kind, int slot, char* out, size_t n) const
  {
    const Snapshot& s = *m_snap;
    const WorldSpec& w = *s.world;
    const Individual& c = s.pop[0];
    const GenStats& g = s.history.back();
    char score[48];
    ScoreText(w.goal, c.res, score, sizeof(score));
    kind = (kind + slot * 2) % 6;
    switch (kind)
    {
      case 0:
        std::snprintf(out, n, "A %d-segment %s leads generation %d with %s; the mean score is %.1f.", c.traits.segs,
                      c.name, s.generation, score, g.mean);
        break;
      case 1:
      {
        // how long the champion's species has held the top
        int run = 0;
        for (size_t i = s.history.size(); i-- > 0;)
        {
          if (s.history[i].champSpecies != c.species)
            break;
          run++;
        }
        std::snprintf(out, n, "The %s species has held the top spot for %d generation%s.", c.name, run, run == 1 ? "" : "s");
        break;
      }
      case 2:
        std::snprintf(out, n, "Bodies average %.1f segments now; brains %.1f hidden neurons and %.0f links.", g.segs,
                      g.hidden, g.conns);
        break;
      case 3:
      {
        const SpeciesView* big = nullptr;
        for (const SpeciesView& v : s.species)
          if (!big || v.size > big->size)
            big = &v;
        if (big)
          std::snprintf(out, n, "%d species are alive; %s is the biggest, with %d members.",
                        static_cast<int>(s.species.size()), big->name, big->size);
        else
          out[0] = 0;
        break;
      }
      case 4:
        if (w.goal == G_BEACON || w.goal == G_CLIMB)
          std::snprintf(out, n, "%d of %d creatures reached the beacon this generation.", s.reached, static_cast<int>(s.pop.size()));
        else if (w.goal == G_CHASM)
          std::snprintf(out, n, "%d of %d creatures got across the chasm this generation.", s.reached, static_cast<int>(s.pop.size()));
        else
          std::snprintf(out, n, "%llu creatures have been born since this run began.", static_cast<unsigned long long>(s.totals.born));
        break;
      default:
        if (s.hasGhost && s.ghost.fitness > 0.05f)
          std::snprintf(out, n, "The best now scores %.1fx what generation %d's best did on this goal.",
                        c.fitness / s.ghost.fitness, s.ghostGen);
        else
          std::snprintf(out, n, "This goal is %d generation%s old; the population carries over from the last one.",
                        s.epochGen + 1, s.epochGen == 0 ? "" : "s");
        break;
    }
  }

  // ---------------------------------------------------------------- state

  static constexpr int kMotes = 60;
  static constexpr int kTicker = 4;
  static constexpr int kPending = 8;
  static constexpr int kRecent = 5;

  StageOptions m_o;
  Palette m_palette;
  Rng m_rng;
  float m_W = 1920, m_H = 1080, m_S = 1.0f, m_pw = 0.01f;
  std::shared_ptr<const Snapshot> m_snap, m_next;
  std::vector<Actor> m_actors;
  float m_time = 0, m_roundT = 0, m_endAt = 0;
  int m_phase = PH_WAIT;
  bool m_newWorld = false;
  int m_epochRound = 0;
  unsigned m_rounds = 0;
  std::atomic<int> m_consumed{-1};
  Cam m_cam;
  bool m_camInit = false;
  Mote m_motes[kMotes];
  uint32_t m_lastSeq = 0, m_cardSeq = 0;
  TickerLine m_ticker[kTicker], m_pending[kPending];
  int m_nTicker = 0, m_nPending = 0;
  float m_lastTickerAt = -10.0f;
  int m_card = -1;
  float m_cardStart = 0;
  uint32_t m_cardVariant = 0;
  int m_recentCards[kRecent];
  float m_titleT0 = -100;
  bool m_titleFirst = true;
  uint64_t m_layoutId = ~0ull;
  std::vector<NodePos> m_nodes;
  std::vector<int> m_nodeOf;
  std::vector<float> m_prevVal, m_flash;
  std::vector<float> m_chartA, m_chartB;
  float m_stepMs = 0, m_fps = 0;
  int m_threads = 1;
};

} // namespace evo

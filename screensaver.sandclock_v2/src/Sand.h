// Sand Clock v2: the sand. A granular cellular automaton with real motion,
// no Kodi / OpenGL.
//
// Every cell of the grid is empty or holds one grain. Unlike the usual
// "falling sand" toy, a grain carries a velocity and a sub-cell position
// (8.6 fixed point), so it accelerates under gravity, falls several cells a
// step along a traced path, turns part of its fall into a sideways scatter
// when it lands, rolls down slopes gaining speed and slides to a stop under
// friction. That is what makes piles settle below 45 degrees, avalanches run
// out and streams splash, as dry sand does.
//
// The digits of the clock are grains too, held in place. When a digit
// changes its grains are let go (from the bottom up, all at once or at
// random) and the new digit is a mould that sand pours into from the top of
// the screen, filling it from the bottom of each column, or that builds up in
// place. A hole in the floor drains the pile so it keeps its height.
//
// The performance recipe of Particle Life v2, Dancing Boids and Physarum v2:
//  - one byte per cell for the picture (the GPU gets exactly this array) and
//    an 8-byte motion record per cell, moved with the grain;
//  - 16 x 16 chunks with an activity flag: only chunks where something moved
//    last step, or next to one, are visited, so a settled pile costs nothing;
//  - the grid is split into 32-column strips, updated in two passes (even
//    strips, then odd) on worker threads. A grain moves at most 7 columns a
//    step, so strips running at the same time never touch the same cell, and
//    a stamp per grain stops it moving twice;
//  - stateless hashed randomness, so the result does not depend on how the
//    work is split (tests/sim_test.cpp checks threads against one thread).
#pragma once

#include "ClockFace.h"
#include "Colours.h"
#include "WorkerPool.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

namespace sandclock2
{

constexpr int kChunk = 16;       // activity chunks are kChunk x kChunk cells
constexpr int kStrip = 32;       // columns per strip (two chunks)
constexpr int kMaxDx = 7;        // most columns a grain moves in one step (< kStrip / 4)
constexpr int kFix = 64;         // velocities and sub-cell positions are in 1/64 cell
constexpr int kShades = 8;       // shades per base colour in the palette

enum Crumble { CRUMBLE_BOTTOM_UP = 0, CRUMBLE_AT_ONCE, CRUMBLE_DISSOLVE };
enum NewDigits { NEW_POUR = 0, NEW_BUILD };

struct SandParams
{
  int gravity = 8;          // 1/64 cell per step^2 (8: a 270-row screen falls in ~1.1 s)
  int maxFall = 6 * kFix;   // terminal speed
  // Landings are very inelastic and the surface friction is high, as for dry
  // sand: a poured heap stands at about 35 degrees (tests/sim_test.cpp).
  int scatter = 6;          // share of the landing speed turned sideways, /64
  int maxScatter = 64;      // most sideways speed a landing gives
  int friction = 18;        // sideways speed lost per step on the surface, 1/64 cell
  int roll = 4;             // sideways speed gained rolling down one cell of slope
  int punch = 2 * kFix;     // landing speed at which a grain knocks the one below aside
  int release = kFix;       // speed of a grain that has just lost its support
  float pile = 0.20f;       // mean height of the pile, fraction of the screen
  float hole = 0.8f;        // width of the drain under each character, fraction of its width
  int spread = 40;          // chance /64 that a flowing grain steps over a 2:1 lip
  int newDigits = NEW_POUR;
  int crumble = CRUMBLE_BOTTOM_UP;
  bool wholeClock = false;  // the whole clock crumbles when the minute changes
};

struct Grain
{
  uint8_t flags;  // HELD or POUR, and the mould generation in bits 2..7
  uint8_t stamp;  // the step it last moved in
  int8_t fx, fy;  // sub-cell position, 0..63 (fx: a pour grain's wait counter)
  int16_t vx, vy; // 1/64 cell per step (vx: a pour grain's target row)
};
static_assert(sizeof(Grain) == 8, "Grain should pack into 8 bytes");

class SandWorld
{
public:
  // HELD: part of a digit; POUR: poured into a mould (both with the mould
  // generation in bits 2..7). FLOW, for loose grains only: it rolled or
  // stepped last step and is still running down the slope.
  enum : uint8_t { HELD = 1, POUR = 2, FLOW = 4 };

  SandParams params;
  ClockStyle style;
  ColourPicker colours;

  // A new world: an empty grid with a settled, striped pile at the bottom.
  void Configure(int w, int h, uint32_t seed)
  {
    m_w = std::max(w, 8);
    m_h = std::max(h, 8);
    m_seed = seed;
    const size_t n = static_cast<size_t>(m_w) * m_h;
    m_col.assign(n, 0);
    m_g.assign(n, Grain{0, 0, 0, 0, 0, 0});
    m_target.assign(n, 0);
    m_cw = (m_w + kChunk - 1) / kChunk;
    m_ch = (m_h + kChunk - 1) / kChunk;
    m_active.assign(static_cast<size_t>(m_cw) * m_ch, 1);
    m_next.reset(new std::atomic<uint8_t>[static_cast<size_t>(m_cw) * m_ch]);
    for (int i = 0; i < m_cw * m_ch; i++)
      m_next[i].store(0, std::memory_order_relaxed);
    m_step = 0;
    m_total = 0;
    m_held = 0;
    m_heldDelta.store(0);
    m_text.clear();
    m_slots.clear();
    m_releases.clear();
    m_fills.clear();
    m_pours.clear();
    m_generation = 0;
    m_glyphs.Set(style);
    colours.Seed(seed);
    BuildPalette();
    Prefill();
    m_dirtyY0 = 0;
    m_dirtyY1 = m_h;
  }

  int width() const { return m_w; }
  int height() const { return m_h; }
  const uint8_t* display() const { return m_col.data(); }
  // 256 RGBA entries: 0 is empty, then kShades shades of each base colour.
  const uint8_t* palette() const { return m_palette; }
  long grains() const { return m_total; }
  long held() const { return m_held; }
  long step() const { return m_step; }
  int activeChunks() const { return m_lastActive; }
  const std::string& text() const { return m_text; }

  // Rows changed since the last call (the part of the picture to upload).
  bool TakeDirtyRows(int& y0, int& y1)
  {
    if (m_dirtyY1 <= m_dirtyY0)
      return false;
    y0 = m_dirtyY0;
    y1 = m_dirtyY1;
    m_dirtyY0 = m_h;
    m_dirtyY1 = 0;
    return true;
  }

  // Show `text` (the clock). The first call puts the digits in place; later
  // calls crumble the digits that changed and pour in the new ones.
  void SetText(const std::string& text, double seconds)
  {
    if (text == m_text)
      return;
    const std::vector<Box> boxes = Layout(style, text, m_w, m_h);
    const bool first = m_text.empty();
    bool all = first || text.size() != m_text.size();
    auto minutes = [this](const std::string& t) { return style.seconds && t.size() > 3 ? t.substr(0, t.size() - 3) : t; };
    if (!all && params.wholeClock && minutes(text) != minutes(m_text))
      all = true; // the minute changed
    if (!all)
      for (size_t i = 0; i < boxes.size() && i < m_slots.size(); i++)
        if (std::fabs(boxes[i].x - m_slots[i].box.x) > 0.01f)
          all = true; // the layout moved (12-hour clock gaining a digit)
    if (all)
    {
      for (size_t i = 0; i < m_slots.size(); i++)
        ClearSlot(static_cast<int>(i));
      m_slots.assign(text.size(), Slot());
    }
    for (size_t i = 0; i < text.size(); i++)
    {
      Slot& s = m_slots[i];
      if (!all && s.ch == text[i])
        continue;
      if (!all)
        ClearSlot(static_cast<int>(i));
      s.ch = text[i];
      s.box = boxes[i];
      FillSlot(static_cast<int>(i), first, seconds);
    }
    m_text = text;
  }

  // One step: due releases, pours and fills, the drain, then the grains.
  void Step(WorkerPool& pool)
  {
    m_step++;
    m_stamp = static_cast<uint8_t>(m_step);
    RunReleases();
    RunFills();
    RunPours();
    RunDrain();

    const int strips = (m_w + kStrip - 1) / kStrip;
    const int pairs = (strips + 1) / 2;
    for (int pass = 0; pass < 2; pass++)
    {
      const int count = pass == 0 ? pairs : strips / 2;
      pool.Run(static_cast<size_t>(count), [&](size_t lo, size_t hi) {
        for (size_t k = lo; k < hi; k++)
        {
          const int s = static_cast<int>(k) * 2 + pass;
          UpdateStrip(s * kStrip, std::min(m_w, (s + 1) * kStrip));
        }
      });
    }
    EndStep();
  }

  // Run one step on the calling thread (tests).
  void Step()
  {
    WorkerPool none;
    Step(none);
  }

  // The steepest slope of the pile surface between columns x0 and x1, in
  // degrees, from a least-squares line through the column heights (tests).
  float SurfaceSlope(int x0, int x1) const
  {
    double sx = 0, sy = 0, sxx = 0, sxy = 0;
    int n = 0;
    for (int x = std::max(0, x0); x < std::min(m_w, x1); x++)
    {
      int y = 0;
      while (y < m_h && !m_col[static_cast<size_t>(y) * m_w + x])
        y++;
      const double hgt = m_h - y;
      sx += x;
      sy += hgt;
      sxx += static_cast<double>(x) * x;
      sxy += x * hgt;
      n++;
    }
    if (n < 2)
      return 0;
    const double b = (n * sxy - sx * sy) / std::max(1e-9, n * sxx - sx * sx);
    return static_cast<float>(std::atan(std::fabs(b)) * 57.29578);
  }

  // Test hooks: put a free grain at (x, y), and clear the whole grid.
  void Drop(int x, int y, int vx = 0, int vy = 0)
  {
    const size_t i = static_cast<size_t>(y) * m_w + x;
    if (m_col[i])
      return;
    m_col[i] = Shade(0, x, y);
    m_g[i] = Grain{0, 0, 0, 0, static_cast<int16_t>(vx), static_cast<int16_t>(vy)};
    m_total++;
    Mark(x, y);
  }
  void Clear()
  {
    std::fill(m_col.begin(), m_col.end(), 0);
    std::fill(m_target.begin(), m_target.end(), 0);
    m_total = m_held = 0;
    m_slots.clear();
    m_text.clear();
    m_releases.clear();
    m_fills.clear();
    m_pours.clear();
  }
  bool At(int x, int y) const { return m_col[static_cast<size_t>(y) * m_w + x] != 0; }
  bool HeldAt(int x, int y) const
  {
    const size_t i = static_cast<size_t>(y) * m_w + x;
    return m_col[i] && (m_g[i].flags & HELD);
  }
  bool drainOn = true;

  // Grains still on their way into a mould, and mould cells still empty (tests).
  long Pouring() const
  {
    long n = 0;
    for (size_t i = 0; i < m_col.size(); i++)
      n += m_col[i] && (m_g[i].flags & POUR);
    return n;
  }
  // Free grains that could still roll or fall but whose chunk is asleep (tests: should be 0).
  long Unstable() const
  {
    long n = 0;
    for (int y = 0; y < m_h; y++)
      for (int x = 0; x < m_w; x++)
      {
        const size_t i = static_cast<size_t>(y) * m_w + x;
        if (!m_col[i] || (m_g[i].flags & (HELD | POUR)))
          continue;
        const bool canMove = Free(x, y + 1) || (Free(x - 1, y) && Free(x - 1, y + 1)) ||
                             (Free(x + 1, y) && Free(x + 1, y + 1));
        if (canMove && !m_active[(y / kChunk) * m_cw + x / kChunk])
          n++;
      }
    return n;
  }
  long EmptyMould() const
  {
    long n = 0;
    for (size_t i = 0; i < m_col.size(); i++)
      n += m_target[i] && !(m_col[i] && (m_g[i].flags & HELD));
    return n;
  }

private:
  struct Slot
  {
    char ch = 0;
    Box box{0, 0, 0, 0};
    uint8_t tv = 0; // mould generation written into m_target
  };
  struct Release
  {
    int cell, step;
  };
  struct Fill
  {
    int cell, step, deadline;
    uint8_t tv, base;
  };
  struct Pour
  {
    int x;
    std::vector<int16_t> rows; // target rows, bottom first
    size_t next = 0;
    int nextStep = 0, slug = 2;
    uint8_t tv = 0, base = 0;
  };

  // ---- the palette and the colour index of a grain

  void BuildPalette()
  {
    std::memset(m_palette, 0, sizeof(m_palette));
    m_bases = std::min(colours.NumBases(), 255 / kShades);
    for (int b = 0; b < m_bases; b++)
    {
      const RGB c = colours.Base(b);
      for (int s = 0; s < kShades; s++)
      {
        // grains of one colour vary in brightness and a little in warmth
        const float k = 0.74f + 0.065f * s;
        const float warm = (s & 1 ? 0.03f : -0.02f);
        uint8_t* p = m_palette + (1 + b * kShades + s) * 4;
        p[0] = static_cast<uint8_t>(std::min(255.0f, (c.r * k + warm) * 255.0f));
        p[1] = static_cast<uint8_t>(std::min(255.0f, c.g * k * 255.0f));
        p[2] = static_cast<uint8_t>(std::min(255.0f, std::max(0.0f, c.b * k - warm) * 255.0f));
        p[3] = 255;
      }
    }
  }

  uint8_t Shade(int base, int x, int y) const
  {
    const int b = ((base % m_bases) + m_bases) % m_bases;
    return static_cast<uint8_t>(1 + b * kShades + (Hash(x, y, m_seed + m_step) % kShades));
  }

  // ---- the starting pile: column heights with gentle hills, at most one
  // cell of rise per column, in wavy coloured strata like a sand bottle.

  void Prefill()
  {
    // keep the pile well clear of the clock
    const std::vector<Box> b = Layout(style, style.seconds ? "88:88:88" : "88:88", m_w, m_h);
    m_clockBottom = std::min(m_h - 1, static_cast<int>(b[0].y + b[0].h) + 1);
    const float mean = std::max(2.0f, std::min(params.pile * m_h, (m_h - m_clockBottom) * 2.0f / 3.0f));
    std::vector<int> hgt(m_w);
    const float p1 = (m_seed % 1000) * 0.0063f, p2 = (m_seed / 1000 % 1000) * 0.0071f;
    for (int x = 0; x < m_w; x++)
    {
      const float u = static_cast<float>(x) / m_w;
      float hh = mean * (1.0f + 0.22f * std::sin(u * 7.1f + p1) + 0.12f * std::sin(u * 15.3f + p2));
      hgt[x] = std::max(1, std::min(m_h / 2, static_cast<int>(hh)));
    }
    for (int x = 1; x < m_w; x++) // no slope steeper than 45 degrees
      hgt[x] = std::min(hgt[x], hgt[x - 1] + 1);
    for (int x = m_w - 2; x >= 0; x--)
      hgt[x] = std::min(hgt[x], hgt[x + 1] + 1);
    const float band = std::max(4.0f, mean / 3.0f);
    for (int x = 0; x < m_w; x++)
      for (int k = 0; k < hgt[x]; k++)
      {
        const int y = m_h - 1 - k;
        const float wave = 3.5f * std::sin(x * 0.045f + p1) + 2.0f * std::sin(x * 0.11f + p2);
        const int stratum = static_cast<int>((k + wave + band) / band);
        const size_t i = static_cast<size_t>(y) * m_w + x;
        m_col[i] = Shade(stratum * 3 + 1, x, y);
        m_g[i] = Grain{0, 0, 0, 0, 0, 0};
        m_total++;
      }
    m_level = static_cast<int>(mean);
    m_looseTarget = m_total;
  }

  // ---- the clock

  void ClearSlot(int i)
  {
    Slot& s = m_slots[i];
    // The mould is gone: grains still pouring into it fall as plain sand.
    const int x0 = std::max(0, static_cast<int>(std::floor(s.box.x)));
    const int x1 = std::min(m_w, static_cast<int>(std::ceil(s.box.x + s.box.w)));
    const int y0 = std::max(0, static_cast<int>(std::floor(s.box.y)));
    const int y1 = std::min(m_h, static_cast<int>(std::ceil(s.box.y + s.box.h)));
    const float span = std::max(1.0f, s.box.h);
    // Steps over which a digit crumbles: the seconds have a second to crumble
    // and fill again, the others take their time.
    const bool fast = style.seconds && i + 3 >= static_cast<int>(m_slots.size());
    const int R = fast ? 6 : 28;
    for (int y = y0; y < y1; y++)
      for (int x = x0; x < x1; x++)
      {
        const size_t c = static_cast<size_t>(y) * m_w + x;
        if (m_target[c] == s.tv)
          m_target[c] = 0;
        if (!m_col[c] || !(m_g[c].flags & HELD))
          continue;
        const uint32_t r = Hash(x, y, m_seed ^ static_cast<uint32_t>(m_step));
        int delay;
        if (params.crumble == CRUMBLE_AT_ONCE)
          delay = static_cast<int>(r % 2);
        else if (params.crumble == CRUMBLE_DISSOLVE)
          delay = static_cast<int>(r % (fast ? R : R * 2));
        else // from the bottom up, a ragged front
          delay = static_cast<int>((1.0f - (y - s.box.y) / span) * R) + static_cast<int>(r % (fast ? 2 : 5));
        m_releases.push_back({static_cast<int>(c), static_cast<int>(m_step) + std::max(0, delay)});
      }
    s.ch = 0;
  }

  void FillSlot(int i, bool instant, double seconds)
  {
    Slot& s = m_slots[i];
    m_generation = m_generation % 63 + 1;
    s.tv = static_cast<uint8_t>(m_generation);
    const int base = colours.Next(i, seconds);
    const std::vector<Cell> cells = Rasterise(m_glyphs.Get(s.ch), s.box, m_w, m_h);
    for (const Cell& c : cells)
      m_target[static_cast<size_t>(c.y) * m_w + c.x] = s.tv;
    if (instant)
    {
      for (const Cell& c : cells)
        Place(static_cast<size_t>(c.y) * m_w + c.x, c.x, c.y, base, s.tv);
      return;
    }
    const int now = static_cast<int>(m_step);
    if (params.newDigits == NEW_BUILD)
    {
      // Built up in place, bottom rows first, once the old grains are out of the way.
      const float span = std::max(1.0f, s.box.h);
      for (const Cell& c : cells)
      {
        const int delay = 10 + static_cast<int>((1.0f - (c.y - s.box.y) / span) * 24.0f);
        m_fills.push_back({c.y * m_w + c.x, now + delay, now + delay + 120, s.tv,
                           static_cast<uint8_t>(base)});
      }
      return;
    }
    // Poured: per column, the target rows from the bottom up. A column pours
    // a short slug of grains every other step, long columns faster, so every
    // column is full about half a second after the pour starts.
    std::vector<std::vector<int16_t>> cols(static_cast<size_t>(m_w));
    for (const Cell& c : cells)
      cols[c.x].push_back(static_cast<int16_t>(c.y));
    for (int x = 0; x < m_w; x++)
    {
      if (cols[x].empty())
        continue;
      Pour p;
      p.x = x;
      p.rows = std::move(cols[x]);
      std::sort(p.rows.begin(), p.rows.end(), [](int16_t a, int16_t b) { return a > b; });
      p.slug = std::max(2, static_cast<int>((p.rows.size() + 13) / 14));
      p.nextStep = now + 1 + static_cast<int>(Hash(x, m_generation) % 6); // columns start out of step
      p.tv = s.tv;
      p.base = static_cast<uint8_t>(base);
      m_pours.push_back(std::move(p));
    }
  }

  void Place(size_t c, int x, int y, int base, uint8_t tv)
  {
    if (m_col[c])
      return;
    m_col[c] = Shade(base, x, y);
    m_g[c] = Grain{static_cast<uint8_t>(HELD | tv << 2), m_stamp, 0, 0, 0, 0};
    m_total++;
    m_held++;
    Mark(x, y);
  }

  void RunReleases()
  {
    const int now = static_cast<int>(m_step);
    for (size_t k = 0; k < m_releases.size();)
    {
      const Release r = m_releases[k];
      if (r.step > now)
      {
        k++;
        continue;
      }
      m_releases[k] = m_releases.back();
      m_releases.pop_back();
      Grain& g = m_g[r.cell];
      if (!m_col[r.cell] || !(g.flags & HELD))
        continue;
      const uint32_t h = Hash(r.cell, m_seed);
      g.flags = 0;
      g.vx = static_cast<int16_t>(static_cast<int>(h % 9) - 4); // a little sideways jitter
      // Released grains drop at slightly different speeds, so a crumbling
      // digit stretches into streams rather than falling as one block.
      g.vy = static_cast<int16_t>(h >> 16 & 31);
      g.fx = static_cast<int8_t>(h >> 8 & 63);
      g.fy = 0;
      m_held--;
      Mark(r.cell % m_w, r.cell / m_w);
    }
  }

  void RunFills()
  {
    const int now = static_cast<int>(m_step);
    for (size_t k = 0; k < m_fills.size();)
    {
      Fill& f = m_fills[k];
      bool done = false;
      if (m_target[f.cell] != f.tv || now > f.deadline)
        done = true;
      else if (f.step <= now && !m_col[f.cell])
      {
        Place(f.cell, f.cell % m_w, f.cell / m_w, f.base, f.tv);
        done = true;
      }
      else if (f.step <= now && !(m_g[f.cell].flags & (HELD | POUR)))
      {
        // a loose grain caught in the new digit joins it
        const int x = static_cast<int>(f.cell % m_w), y = static_cast<int>(f.cell / m_w);
        m_col[f.cell] = Shade(f.base, x, y);
        m_g[f.cell] = Grain{static_cast<uint8_t>(HELD | f.tv << 2), m_stamp, 0, 0, 0, 0};
        m_held++;
        Mark(x, y);
        done = true;
      }
      if (done)
      {
        m_fills[k] = m_fills.back();
        m_fills.pop_back();
      }
      else
        k++;
    }
  }

  void RunPours()
  {
    const int now = static_cast<int>(m_step);
    for (size_t k = 0; k < m_pours.size();)
    {
      Pour& p = m_pours[k];
      if (p.next >= p.rows.size() ||
          m_target[static_cast<size_t>(p.rows[p.next]) * m_w + p.x] != p.tv)
      {
        m_pours[k] = std::move(m_pours.back());
        m_pours.pop_back();
        continue;
      }
      k++;
      if (now < p.nextStep)
        continue;
      const int n = std::min(p.slug, static_cast<int>(p.rows.size() - p.next));
      bool clear = true;
      for (int j = 0; j < n && clear; j++)
        clear = !m_col[static_cast<size_t>(j) * m_w + p.x];
      if (!clear)
        continue; // the top of the column is busy: try again next step
      for (int j = 0; j < n; j++)
      {
        const int target = p.rows[p.next + (n - 1 - j)];
        const size_t c = static_cast<size_t>(j) * m_w + p.x;
        if (target <= j) // mould at the very top: no need to pour
        {
          Place(static_cast<size_t>(target) * m_w + p.x, p.x, target, p.base, p.tv);
          continue;
        }
        m_col[c] = Shade(p.base, p.x, target);
        m_g[c] = Grain{static_cast<uint8_t>(POUR | p.tv << 2), 0, 0, 0, static_cast<int16_t>(target),
                       static_cast<int16_t>(4 * kFix)};
        m_total++;
        Mark(p.x, j);
      }
      p.next += n;
      p.nextStep = now + 1 + static_cast<int>(Hash(p.x, p.next, m_generation) % 3); // a ragged stream, not a grid
    }
  }

  // A funnel in the floor under every character, like a row of hourglasses:
  // while there is more loose sand than the starting pile, the bottom row over
  // a funnel loses its grains and the sand drains through a crater, at the
  // funnels where the sand over the hole stands above the pile's level (or
  // the highest one). A heap that grows far too tall drains whatever the
  // count.
  void RunDrain()
  {
    if (!drainOn || m_slots.empty())
      return;
    const bool excess = m_total - m_held > m_looseTarget;
    m_funnels.assign(m_slots.size(), 0);
    size_t highest = 0;
    for (size_t i = 0; i < m_slots.size(); i++)
    {
      const Slot& s = m_slots[i];
      const int centre = static_cast<int>(s.box.x + s.box.w * 0.5f);
      const int half = std::max(1, static_cast<int>(s.box.w * params.hole * 0.5f));
      // the top of the sand over the hole
      int level = 0;
      for (int k = -2; k <= 2; k++)
        level = std::max(level, m_h - SandTop(centre + k * half / 2));
      m_funnels[i] = level;
      if (m_funnels[i] > m_funnels[highest])
        highest = i;
    }
    const int y = m_h - 1;
    for (size_t i = 0; i < m_slots.size(); i++)
    {
      const int level = m_funnels[i];
      const bool drain = level > m_level * 3 / 2 || (excess && (level > m_level || i == highest));
      if (!drain)
        continue;
      const Slot& s = m_slots[i];
      const int centre = static_cast<int>(s.box.x + s.box.w * 0.5f);
      const int half = std::max(1, static_cast<int>(s.box.w * params.hole * 0.5f));
      for (int x = centre - half; x < centre + half; x++)
      {
        const size_t c = static_cast<size_t>(y) * m_w + x;
        if (x < 0 || x >= m_w || !m_col[c] || (m_g[c].flags & HELD))
          continue;
        m_col[c] = 0;
        m_total--;
        Mark(x, y);
      }
    }
  }

  // The top of the sand in column x: the first empty cell up from the floor,
  // so grains still falling through the air do not count (m_h if the column
  // is empty, never above the clock).
  int SandTop(int x) const
  {
    x = std::min(std::max(x, 0), m_w - 1);
    int y = m_h;
    while (y > m_clockBottom && m_col[static_cast<size_t>(y - 1) * m_w + x])
      y--;
    return y;
  }

  // ---- activity

  void Mark(int x, int y)
  {
    const int cx = x / kChunk, cy = y / kChunk;
    const int lx = x - cx * kChunk, ly = y - cy * kChunk;
    const int xa = (lx == 0 && cx > 0) ? cx - 1 : cx;
    const int xb = (lx == kChunk - 1 && cx + 1 < m_cw) ? cx + 1 : cx;
    const int ya = (ly == 0 && cy > 0) ? cy - 1 : cy;
    const int yb = (ly == kChunk - 1 && cy + 1 < m_ch) ? cy + 1 : cy;
    for (int j = ya; j <= yb; j++)
      for (int i = xa; i <= xb; i++)
        m_next[j * m_cw + i].store(1, std::memory_order_relaxed);
  }

  void EndStep()
  {
    m_held += m_heldDelta.exchange(0);
    int count = 0, y0 = m_dirtyY0 * 1, y1 = m_dirtyY1;
    for (int cy = 0; cy < m_ch; cy++)
      for (int cx = 0; cx < m_cw; cx++)
      {
        const size_t k = static_cast<size_t>(cy) * m_cw + cx;
        const uint8_t a = m_next[k].exchange(0, std::memory_order_relaxed);
        if (a || m_active[k])
        {
          y0 = std::min(y0, cy * kChunk);
          y1 = std::max(y1, std::min(m_h, (cy + 1) * kChunk));
        }
        m_active[k] = a;
        count += a;
      }
    m_dirtyY0 = y0;
    m_dirtyY1 = y1;
    m_lastActive = count;
  }

  // ---- the grains

  void UpdateStrip(int sx0, int sx1)
  {
    const int cx0 = sx0 / kChunk, cx1 = (sx1 + kChunk - 1) / kChunk;
    for (int cy = m_ch - 1; cy >= 0; cy--)
    {
      const uint8_t* act = m_active.data() + static_cast<size_t>(cy) * m_cw;
      bool any = false;
      for (int cx = cx0; cx < cx1; cx++)
        any |= act[cx] != 0;
      if (!any)
        continue;
      const int ya = cy * kChunk, yb = std::min(m_h, ya + kChunk);
      for (int y = yb - 1; y >= ya; y--) // bottom up: a falling column moves as one
      {
        if (((y + m_step) & 1) == 0)
        {
          for (int cx = cx0; cx < cx1; cx++)
            if (act[cx])
              for (int x = std::max(sx0, cx * kChunk), xe = std::min(sx1, (cx + 1) * kChunk); x < xe; x++)
                UpdateCell(x, y);
        }
        else // alternate sweep direction so nothing drifts one way
        {
          for (int cx = cx1 - 1; cx >= cx0; cx--)
            if (act[cx])
              for (int x = std::min(sx1, (cx + 1) * kChunk) - 1, xe = std::max(sx0, cx * kChunk); x >= xe; x--)
                UpdateCell(x, y);
        }
      }
    }
  }

  // Cell b (row y) holds a grain that is falling: moving down with nothing
  // under it. A grain that has just rolled onto something still carries a
  // little downward speed, but it is not falling, and the grains above it
  // must not ride on it (they would stand on a slope steeper than 45 degrees).
  bool FallingAt(size_t b, int y) const
  {
    return y < m_h && m_col[b] && !(m_g[b].flags & HELD) && m_g[b].vy > 0;
  }

  bool Free(int x, int y) const
  {
    return x >= 0 && x < m_w && y < m_h && !m_col[static_cast<size_t>(y) * m_w + x];
  }

  void Move(size_t from, int x, int y, int nx, int ny)
  {
    const size_t to = static_cast<size_t>(ny) * m_w + nx;
    m_col[to] = m_col[from];
    m_col[from] = 0;
    m_g[to] = m_g[from];
    Mark(x, y);
    Mark(nx, ny);
  }

  static int Clamp(int v, int lim) { return v > lim ? lim : v < -lim ? -lim : v; }

  void UpdateCell(int x, int y)
  {
    const size_t i = static_cast<size_t>(y) * m_w + x;
    if (!m_col[i])
      return;
    Grain& g = m_g[i];
    if ((g.flags & HELD) || g.stamp == m_stamp)
      return;
    g.stamp = m_stamp;
    if (g.flags & POUR)
    {
      UpdatePour(x, y, i, g);
      return;
    }
    const SandParams& p = params;
    const int vmax = kMaxDx * kFix;

    if (Free(x, y + 1))
    {
      // In the air: accelerate, then trace the path cell by cell. A grain
      // that has just lost its support starts at the speed sand flows with
      // rather than from rest, or every grain in a collapsing slope would
      // wait four steps before moving one cell.
      g.vy = static_cast<int16_t>(std::min(std::max(g.vy + p.gravity, p.release), p.maxFall));
      const int ax = g.fx + g.vx, ay = g.fy + g.vy;
      const int dx = ax >> 6, dy = ay >> 6; // floor division by 64
      g.fx = static_cast<int8_t>(ax & 63);
      g.fy = static_cast<int8_t>(ay & 63);
      const int n = std::max(std::abs(dx), dy);
      if (n == 0)
      {
        Mark(x, y); // still moving, slower than a cell a step
        return;
      }
      int px = x, py = y;
      bool landed = false;
      for (int k = 1; k <= n; k++)
      {
        const int cx = x + dx * k / n, cy = y + dy * k / n;
        if (cx < 0 || cx >= m_w)
        {
          g.vx = static_cast<int16_t>(-g.vx / 4); // off a side wall
          break;
        }
        if (cy >= m_h || m_col[static_cast<size_t>(cy) * m_w + cx])
        {
          if (!Free(px, py + 1))
            landed = true;
          else
            g.vx = static_cast<int16_t>(g.vx / 2); // clipped something on the way down
          break;
        }
        px = cx;
        py = cy;
      }
      if (landed && FallingAt(static_cast<size_t>(py + 1) * m_w + px, py + 1))
      {
        // Caught up with a slower falling grain: carry on at its pace.
        const Grain& b = m_g[static_cast<size_t>(py + 1) * m_w + px];
        g.vy = b.vy;
        g.fy = b.fy;
      }
      else if (landed)
      {
        // Part of the fall goes sideways, towards the open side if there is one.
        int s = (g.vx > 0) - (g.vx < 0);
        if (s == 0)
        {
          const bool l = Free(px - 1, py + 1), r = Free(px + 1, py + 1);
          s = l == r ? ((Hash(px, py, static_cast<uint32_t>(m_step)) & 1) ? 1 : -1) : (r ? 1 : -1);
        }
        g.vx = static_cast<int16_t>(Clamp(g.vx + s * std::min(g.vy * p.scatter >> 6, p.maxScatter), vmax));
        g.vy = 0;
        g.fy = 0;
      }
      if (px != x || py != y)
        Move(i, x, y, px, py);
      else
        Mark(x, y);
      return;
    }

    // On a grain that is itself falling: fall with it. Without this a
    // released column would come apart one grain at a time, each landing on
    // the one below it, instead of dropping as one body.
    if (FallingAt(i + m_w, y + 1))
    {
      const Grain& b = m_g[i + m_w];
      g.vy = b.vy;
      g.fy = b.fy;
      Mark(x, y);
      return;
    }
    // Resting on something: no vertical speed. A grain that was still
    // falling (riding down on the grains below it) takes the impact now.
    int s = (g.vx > 0) - (g.vx < 0);
    if (s == 0)
    {
      const bool l = Free(x - 1, y) && Free(x - 1, y + 1), r = Free(x + 1, y) && Free(x + 1, y + 1);
      s = l == r ? ((Hash(x, y, static_cast<uint32_t>(m_step)) & 1) ? 1 : -1) : (r ? 1 : -1);
    }
    if (g.vy >= p.punch && y + 2 <= m_h - 1)
    {
      // Coming down hard on a grain at rest: knock it aside and take its
      // place. A falling stream digs into the pile and spreads it instead of
      // standing on it as a rod.
      const size_t b = i + m_w;
      Grain& o = m_g[b];
      if (!(o.flags & (HELD | POUR)) && o.vy == 0)
        for (int t = 0; t < 2; t++, s = -s)
          if (Free(x + s, y + 1) || Free(x + s, y + 2))
          {
            const int ny = Free(x + s, y + 2) ? y + 2 : y + 1;
            o.vx = static_cast<int16_t>(Clamp(o.vx + s * (g.vy >> 2), vmax));
            o.stamp = m_stamp;
            Move(b, x, y + 1, x + s, ny);
            g.vy = static_cast<int16_t>(g.vy / 2);
            Move(i, x, y, x, y + 1);
            return;
          }
    }
    const bool flowing = g.vy > 0 || (g.flags & FLOW);
    g.flags = 0;
    if (g.vy > 0)
      g.vx = static_cast<int16_t>(Clamp(g.vx + s * std::min(g.vy * p.scatter >> 6, p.maxScatter), vmax));
    g.vy = 0;
    g.fy = 0;
    for (int t = 0; t < 2; t++, s = -s)
    {
      const int nx = x + s;
      if (Free(nx, y) && Free(nx, y + 1))
      {
        // Still on the way down, but resting on the grain it rolled onto:
        // flagged rather than given a downward speed, so the grains above
        // do not ride on it as if it were falling.
        g.vx = static_cast<int16_t>(Clamp(g.vx + s * p.roll, vmax));
        g.flags = FLOW;
        Move(i, x, y, nx, y + 1);
        return;
      }
    }
    // A grain that is still flowing (it fell or rolled to get here) may also
    // step over a 2:1 lip: flowing sand runs out at about 33 degrees, while
    // sand at rest holds up to 45.
    if (flowing && (Hash(x, y, static_cast<uint32_t>(m_step) * 7u) & 63) < static_cast<uint32_t>(p.spread))
    {
      for (int t = 0; t < 2; t++, s = -s)
        if (Free(x + s, y) && Free(x + 2 * s, y) && Free(x + 2 * s, y + 1))
        {
          g.flags = FLOW;
          Move(i, x, y, x + s, y);
          return;
        }
    }
    if (g.vx == 0)
      return; // settled: nothing to do until a neighbour moves
    // Sliding along the surface, losing speed to friction.
    const int sd = g.vx > 0 ? 1 : -1;
    const int ax = g.fx + g.vx;
    const int dx = ax >> 6;
    g.fx = static_cast<int8_t>(ax & 63);
    const int mag = std::abs(g.vx);
    g.vx = static_cast<int16_t>(mag <= p.friction ? 0 : g.vx - sd * p.friction);
    int px = x;
    for (int k = 0; k < std::abs(dx); k++)
    {
      if (!Free(px + sd, y))
      {
        g.vx = 0;
        g.fx = 0;
        break;
      }
      px += sd;
      if (Free(px, y + 1))
        break; // over an edge: it falls from here next step
    }
    if (px != x)
      Move(i, x, y, px, y);
    else
      Mark(x, y);
  }

  // A grain poured into a mould falls straight down to its target cell. The
  // clock has right of way: loose grains in its path (a crumbled digit still
  // falling out of the mould, sand flowing to a funnel) swap places with it,
  // so a pour can never be held up by sand passing through.
  void UpdatePour(int x, int y, size_t i, Grain& cell)
  {
    Grain g = cell;
    const uint8_t colour = m_col[i];
    const int target = g.vx;
    const uint8_t tv = static_cast<uint8_t>(g.flags >> 2);
    const uint8_t mine = static_cast<uint8_t>(HELD | tv << 2);
    if (target >= m_h || m_target[static_cast<size_t>(target) * m_w + x] != tv)
    {
      cell.flags = 0; // its mould is gone (the digit changed again): plain sand from here
      cell.vx = 0;
      cell.fx = 0;
      Mark(x, y);
      return;
    }
    g.vy = static_cast<int16_t>(std::min(g.vy + params.gravity, params.maxFall + 2 * kFix));
    const int ay = g.fy + g.vy;
    const int dy = ay >> 6;
    g.fy = static_cast<int8_t>(ay & 63);
    int py = y;
    bool blocked = false, swapped = false;
    for (int k = 0; k < dy && py < target; k++)
    {
      const size_t n = static_cast<size_t>(py + 1) * m_w + x;
      if (py + 1 >= m_h)
      {
        blocked = true;
        break;
      }
      if (m_col[n] && !(m_g[n].flags & (HELD | POUR)))
      {
        // a loose grain: it takes the cell this grain is passing through
        const size_t here = static_cast<size_t>(py) * m_w + x;
        m_col[here] = m_col[n];
        m_g[here] = m_g[n];
        m_g[here].stamp = m_stamp;
        m_col[n] = 0;
        swapped |= py == y;
        Mark(x, py);
      }
      else if (m_col[n])
      {
        blocked = true;
        break;
      }
      py++;
    }
    const size_t b = static_cast<size_t>(py + 1) * m_w + x;
    if (blocked && py < target && m_g[b].flags == mine && m_target[static_cast<size_t>(py) * m_w + x] == tv)
      g.vx = static_cast<int16_t>(target > py ? py : target); // the cell below is done: fill this one
    if (py >= g.vx)
    {
      g.flags = mine; // in the mould
      g.vx = g.vy = 0;
      m_heldDelta.fetch_add(1, std::memory_order_relaxed);
    }
    else if (blocked)
    {
      if (FallingAt(b, py + 1))
      {
        g.vy = m_g[b].vy; // behind a falling grain: keep pace with it
        g.fy = m_g[b].fy;
      }
      else
        g.vy = 0;
      if (++g.fx > 60) // stuck for a second: give up and be sand
      {
        g.flags = 0;
        g.vx = 0;
        g.fx = 0;
      }
    }
    if (py != y)
    {
      const size_t to = static_cast<size_t>(py) * m_w + x;
      m_col[to] = colour;
      m_g[to] = g;
      if (!swapped)
        m_col[i] = 0;
      Mark(x, y);
      Mark(x, py);
    }
    else
    {
      cell = g;
      Mark(x, y);
    }
  }

  int m_w = 0, m_h = 0, m_cw = 0, m_ch = 0;
  uint32_t m_seed = 1;
  long m_step = 0;
  uint8_t m_stamp = 0;
  std::vector<uint8_t> m_col;    // the picture: 0 empty, else palette index
  std::vector<Grain> m_g;
  std::vector<uint8_t> m_target; // mould generation of the clock cell, 0 = none
  std::vector<uint8_t> m_active;
  std::unique_ptr<std::atomic<uint8_t>[]> m_next;
  int m_lastActive = 0;
  int m_dirtyY0 = 0, m_dirtyY1 = 0;
  uint8_t m_palette[256 * 4];
  int m_bases = 7;

  long m_total = 0, m_held = 0;
  int m_level = 0, m_clockBottom = 0;
  long m_looseTarget = 0;
  std::vector<int> m_funnels;
  std::atomic<int> m_heldDelta{0};

  GlyphCache m_glyphs;
  std::string m_text;
  std::vector<Slot> m_slots;
  std::vector<Release> m_releases;
  std::vector<Fill> m_fills;
  std::vector<Pour> m_pours;
  int m_generation = 0;
};

} // namespace sandclock2

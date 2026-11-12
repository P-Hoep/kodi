// ScreenMazer animation: builds a maze cell by cell, pauses, traces the
// solution, pauses, fades everything back to the wall colour and starts over
// (MazeScene.swift in the original). No GL here; the wrapper uploads pixels().

#pragma once

#include "Maze.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <ctime>
#include <memory>
#include <random>
#include <string>
#include <vector>

namespace mazer
{

struct RGB
{
  float r, g, b;
};

struct Settings
{
  RGB wall{0, 0, 0};
  RGB path{0.5f, 0.5f, 0.5f};   // NSColor.gray
  RGB solve{1, 1, 1};           // NSColor.white
  double buildSeconds = 30;
  double solveSeconds = 10;
  bool solveMaze = true;
  bool showClock = true;
  int clockScale = 1;
  bool hour24 = false;
  bool centreClock = false;
  double fadeSeconds = 0.5;     // per-cell colour change (SKAction.colorize)
  double resetSeconds = 1.0;    // fade back to the wall colour
  double pauseBuilt = 1.0;      // 60 ticks after the maze is complete
  double pauseSolved = 2.0;     // 120 ticks after the solution is drawn
  double pauseReset = 1.0;      // 60 ticks before the next maze starts
};

inline std::string ClockText(bool hour24, std::time_t t)
{
  std::tm lt{};
#if defined(_WIN32)
  localtime_s(&lt, &t);
#else
  localtime_r(&t, &lt);
#endif
  int h = lt.tm_hour;
  if (!hour24)
  {
    h %= 12;
    if (h == 0)
      h = 12; // "hh" is 01-12
  }
  char buf[8];
  std::snprintf(buf, sizeof(buf), "%02d:%02d", h, lt.tm_min);
  return buf;
}

class Animator
{
public:
  enum Phase { BUILD, PAUSE_BUILT, SOLVE, PAUSE_SOLVED, RESET };

  void Init(int rows, int cols, const Settings& s, uint32_t seed)
  {
    m_rows = rows;
    m_cols = cols;
    m_s = s;
    m_rng.seed(seed);
    const size_t n = static_cast<size_t>(rows) * cols;
    m_from.assign(n, s.wall);
    m_to.assign(n, s.wall);
    m_t0.assign(n, 0.0);
    m_dur.assign(n, 0.0);
    m_active.assign(n, 0);
    m_activeList.clear();
    m_pixels.assign(n * 4, 0);
    for (size_t i = 0; i < n; i++)
      Store(i, s.wall);
    m_time = 0;
    NewMaze();
    m_phase = BUILD;
    m_phaseStart = 0;
    m_index = 0;
    m_carry = 0;
  }

  // Advance by dt seconds. Returns true when pixels() changed.
  bool Update(double dt)
  {
    if (!m_maze)
      return false;
    dt = std::min(std::max(dt, 0.0), 0.25);
    m_time += dt;
    const double inPhase = m_time - m_phaseStart;
    const auto& order = m_maze->order();
    const auto& solution = m_maze->solution();

    switch (m_phase)
    {
      case BUILD:
        if (Reveal(order, m_s.path, m_s.buildSeconds, dt))
          Enter(PAUSE_BUILT);
        break;
      case PAUSE_BUILT:
        if (inPhase >= m_s.pauseBuilt)
          Enter(m_s.solveMaze ? SOLVE : RESET);
        break;
      case SOLVE:
        if (Reveal(solution, m_s.solve, m_s.solveSeconds, dt))
          Enter(PAUSE_SOLVED);
        break;
      case PAUSE_SOLVED:
        if (inPhase >= m_s.pauseSolved)
          Enter(RESET);
        break;
      case RESET:
        if (inPhase >= m_s.pauseReset)
          Enter(BUILD);
        break;
    }
    return Fade();
  }

  Phase phase() const { return m_phase; }
  int rows() const { return m_rows; }
  int cols() const { return m_cols; }
  const Maze* maze() const { return m_maze.get(); }
  // RGBA8, row 0 = bottom row of the screen (GL texture order).
  const std::vector<uint8_t>& pixels() const { return m_pixels; }
  size_t activeCells() const { return m_activeList.size(); }

private:
  void NewMaze()
  {
    const std::string text = m_s.showClock ? ClockText(m_s.hour24, std::time(nullptr)) : "";
    m_maze = std::make_unique<Maze>(m_rows, m_cols, text, m_s.clockScale, m_s.centreClock, m_rng);
  }

  void Enter(Phase p)
  {
    m_phase = p;
    m_phaseStart = m_time;
    m_index = 0;
    m_carry = 0;
    if (p == RESET)
    {
      for (size_t i = 0; i < m_to.size(); i++)
        Colorize(i, m_s.wall, m_s.resetSeconds);
      NewMaze(); // the clock shows the time the maze was made
    }
  }

  // Light the next cells of `cells` at a rate that finishes in `seconds`, at
  // least one cell per frame like the original. Returns true when all are lit.
  bool Reveal(const std::vector<Cell>& cells, const RGB& colour, double seconds, double dt)
  {
    const size_t total = cells.size();
    if (m_index >= total)
      return true;
    m_carry += static_cast<double>(total) / std::max(seconds, 0.1) * dt;
    size_t step = static_cast<size_t>(m_carry);
    m_carry -= static_cast<double>(step);
    step = std::max<size_t>(step, 1);
    const size_t until = std::min(total, m_index + step);
    for (; m_index < until; m_index++)
    {
      const Cell& c = cells[m_index];
      Colorize(static_cast<size_t>(c.r) * m_cols + c.c, colour, m_s.fadeSeconds);
    }
    return m_index >= total;
  }

  RGB Current(size_t i) const
  {
    if (!m_active[i])
      return m_to[i];
    const double t = m_dur[i] > 0 ? std::min(1.0, (m_time - m_t0[i]) / m_dur[i]) : 1.0;
    const float k = static_cast<float>(t);
    return {m_from[i].r + (m_to[i].r - m_from[i].r) * k, m_from[i].g + (m_to[i].g - m_from[i].g) * k,
            m_from[i].b + (m_to[i].b - m_from[i].b) * k};
  }

  // removeAllActions() + colorize(with:duration:) on one cell.
  void Colorize(size_t i, const RGB& to, double seconds)
  {
    m_from[i] = Current(i);
    m_to[i] = to;
    m_t0[i] = m_time;
    m_dur[i] = seconds;
    if (!m_active[i])
    {
      m_active[i] = 1;
      m_activeList.push_back(static_cast<uint32_t>(i));
    }
  }

  bool Fade()
  {
    if (m_activeList.empty())
      return false;
    size_t keep = 0;
    for (size_t k = 0; k < m_activeList.size(); k++)
    {
      const uint32_t i = m_activeList[k];
      Store(i, Current(i));
      if (m_time - m_t0[i] >= m_dur[i])
        m_active[i] = 0;
      else
        m_activeList[keep++] = i;
    }
    m_activeList.resize(keep);
    return true;
  }

  void Store(size_t i, const RGB& c)
  {
    auto byte = [](float v) {
      return static_cast<uint8_t>(std::lround(std::min(std::max(v, 0.0f), 1.0f) * 255.0f));
    };
    m_pixels[i * 4 + 0] = byte(c.r);
    m_pixels[i * 4 + 1] = byte(c.g);
    m_pixels[i * 4 + 2] = byte(c.b);
    m_pixels[i * 4 + 3] = 255;
  }

  int m_rows = 0, m_cols = 0;
  Settings m_s;
  std::mt19937 m_rng;
  std::unique_ptr<Maze> m_maze;

  std::vector<RGB> m_from, m_to;
  std::vector<double> m_t0, m_dur;
  std::vector<uint8_t> m_active;
  std::vector<uint32_t> m_activeList;
  std::vector<uint8_t> m_pixels;

  double m_time = 0;
  Phase m_phase = BUILD;
  double m_phaseStart = 0;
  size_t m_index = 0;
  double m_carry = 0;
};

} // namespace mazer

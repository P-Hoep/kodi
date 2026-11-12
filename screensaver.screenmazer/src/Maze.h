// ScreenMazer maze generator: a C++ port of MazeGenerator.swift from
// Alex Beals' ScreenMazer (https://github.com/dado3212/ScreenMazer).
//
// The grid uses the original's SpriteKit orientation: row 0 is the BOTTOM row
// of the screen, column 0 the left column. Cells start as walls; the generator
// records, in order, every cell that is "lit" (the clock digits first, then the
// passages as a randomised depth-first search carves them, then the entrance
// and exit), and the solution path from the entrance (bottom left) to the exit
// (right edge, near the top).

#pragma once

#include <cstdint>
#include <random>
#include <string>
#include <vector>

namespace mazer
{

struct Cell
{
  int r, c;
};

// 3x5 digit glyphs, row by row from the top ("1" = lit).
inline const char* Glyph(char ch)
{
  switch (ch)
  {
    case '0': return "111101101101111";
    case '1': return "010010010010010";
    case '2': return "111001111100111";
    case '3': return "111001011001111";
    case '4': return "101101111001001";
    case '5': return "111100111001111";
    case '6': return "111100111101111";
    case '7': return "111001001001001";
    case '8': return "111101111101111";
    case '9': return "111101111001001";
    case ':': return "000010000010000";
    default: return "000000000000000";
  }
}

// The clock block for "HH:MM" as rows of 0/1, top row first, each glyph pixel
// `scale` cells wide, inside a one-pixel frame with a one-pixel gap
// (timeToArray() in the original). Size: (9 * scale) rows x (23 * scale) cols.
inline std::vector<std::vector<int>> ClockBlock(const std::string& text, int scale)
{
  const int cs = scale < 1 ? 1 : scale;
  std::vector<std::vector<int>> out(5 * cs);

  for (size_t i = 0; i < text.size(); i++)
  {
    const char* pattern = Glyph(text[i]);
    for (int index = 0; index < 15; index++)
    {
      const int bit = pattern[index] == '1' ? 1 : 0;
      for (int k = 0; k < cs; k++)
        for (int j = 0; j < cs; j++)
          out[index / 3 * cs + j].push_back(bit);
      if ((index + 1) % 3 == 0 && i != text.size() - 1)
        for (int k = 0; k < cs; k++)
          for (int j = 0; j < cs; j++)
            out[index / 3 * cs + j].push_back(0);
    }
  }

  std::vector<int> leftPad, rightPad;
  for (int k = 0; k < cs; k++)
  {
    leftPad.push_back(1);
    rightPad.push_back(0);
  }
  for (int k = 0; k < cs; k++)
  {
    leftPad.push_back(0);
    rightPad.push_back(1);
  }
  for (auto& row : out)
  {
    row.insert(row.begin(), leftPad.begin(), leftPad.end());
    row.insert(row.end(), rightPad.begin(), rightPad.end());
  }

  const size_t width = out[0].size();
  std::vector<int> gapRow(width - 4 * cs, 0);
  gapRow.insert(gapRow.begin(), leftPad.begin(), leftPad.end());
  gapRow.insert(gapRow.end(), rightPad.begin(), rightPad.end());
  const std::vector<int> solidRow(width, 1);

  std::vector<std::vector<int>> block;
  for (int k = 0; k < cs; k++)
    block.push_back(solidRow);
  for (int k = 0; k < cs; k++)
    block.push_back(gapRow);
  block.insert(block.end(), out.begin(), out.end());
  for (int k = 0; k < cs; k++)
    block.push_back(gapRow);
  for (int k = 0; k < cs; k++)
    block.push_back(solidRow);
  return block;
}

class Maze
{
public:
  enum : uint8_t { WALL = 1, SPACE = 0, NO_GO = 2 };

  // clockText: "" for no clock, otherwise e.g. "09:41".
  // centreClock: centre the clock instead of the original's random placement.
  Maze(int rows, int cols, const std::string& clockText, int clockScale, bool centreClock,
       std::mt19937& rng)
    : m_rows(rows), m_cols(cols), m_rng(rng)
  {
    m_blocked.assign(static_cast<size_t>(rows) * cols, WALL);
    m_prev.assign(static_cast<size_t>(rows) * cols, -1);
    if (rows < 5 || cols < 5)
      return;

    m_start = {1, 0};
    m_end = {rows - (rows % 2 == 0 ? 3 : 2), cols - (cols % 2 == 0 ? 2 : 1)};
    m_target = {m_end.r, m_end.c - 1};
    At(m_start) = SPACE;
    At(m_end) = SPACE;

    if (!clockText.empty())
      PlaceClock(ClockBlock(clockText, clockScale), centreClock);

    CreateMaze();
    m_order.push_back(m_start);
    m_order.push_back(m_end);

    // Walk back from the exit to build the solution.
    std::vector<Cell> path;
    int at = Index(m_end);
    while (at >= 0)
    {
      path.push_back({at / m_cols, at % m_cols});
      at = m_prev[at];
    }
    m_solution.assign(path.rbegin(), path.rend());
  }

  int rows() const { return m_rows; }
  int cols() const { return m_cols; }
  // Cells to light, in drawing order (clock, passages, entrance, exit).
  const std::vector<Cell>& order() const { return m_order; }
  // Entrance to exit, inclusive. Just the exit if the exit was never reached.
  const std::vector<Cell>& solution() const { return m_solution; }
  uint8_t blocked(int r, int c) const { return m_blocked[static_cast<size_t>(r) * m_cols + c]; }
  Cell start() const { return m_start; }
  Cell end() const { return m_end; }

private:
  int Index(Cell s) const { return s.r * m_cols + s.c; }
  uint8_t& At(Cell s) { return m_blocked[Index(s)]; }
  uint8_t& At(int r, int c) { return m_blocked[static_cast<size_t>(r) * m_cols + c]; }

  // random(in: a...b) in the original: a + uniform[0, b - a), i.e. [a, b).
  int RandomIn(int lo, int hi)
  {
    if (hi <= lo)
      return lo;
    return lo + std::uniform_int_distribution<int>(0, hi - lo - 1)(m_rng);
  }

  void PlaceClock(const std::vector<std::vector<int>>& block, bool centre)
  {
    const int h = static_cast<int>(block.size());
    const int w = static_cast<int>(block[0].size());
    const int border = 4;
    // Too small for the clock (a preview-sized maze, or a huge clock): skip it,
    // where the original would trap on an empty random range.
    if (m_rows - 2 * border - h < 0 || m_cols - 2 * border - w < 0)
      return;
    const int top = centre ? m_rows / 2 - h / 2 : RandomIn(border, m_rows - border - h);
    const int left = centre ? m_cols / 2 - w / 2 : RandomIn(border, m_cols - border - w);

    for (int r = 0; r < h; r++)
      for (int c = 0; c < w; c++)
      {
        const int rr = m_rows - r - top; // clock row 0 is its top line
        const int cc = c + left;
        if (rr >= 0 && rr < m_rows && cc < m_cols - 1)
        {
          At(rr, cc) = NO_GO;
          if (block[r][c] == 1)
            m_order.push_back({rr, cc});
        }
      }
  }

  void Carve(Cell from, Cell wall, Cell to)
  {
    At(wall) = SPACE;
    At(to) = SPACE;
    m_prev[Index(wall)] = Index(from);
    m_prev[Index(to)] = Index(wall);
    m_order.push_back(wall);
    m_order.push_back(to);
    if (m_prev[Index(m_end)] < 0)
    {
      if (wall.r == m_target.r && wall.c == m_target.c)
        m_prev[Index(m_end)] = Index(wall);
      else if (to.r == m_target.r && to.c == m_target.c)
        m_prev[Index(m_end)] = Index(to);
    }
  }

  void CreateMaze()
  {
    // The original never marked the first cell open, so it stayed dark (and
    // could be carved into a second time); open and light it here.
    Cell pos{1, 1};
    At(pos) = SPACE;
    m_prev[Index(pos)] = Index(m_start);
    m_order.push_back(pos);

    std::vector<Cell> moves{pos};
    Cell options[4];
    while (!moves.empty())
    {
      int n = 0;
      if (pos.r + 2 < m_rows && At(pos.r + 2, pos.c) == WALL && pos.r + 2 != m_rows - 1)
        options[n++] = {1, 0}; // down in the original's naming (towards higher rows)
      if (pos.r - 2 >= 0 && At(pos.r - 2, pos.c) == WALL && pos.r - 2 != 0)
        options[n++] = {-1, 0};
      if (pos.c - 2 >= 0 && At(pos.r, pos.c - 2) == WALL && pos.c - 2 != 0)
        options[n++] = {0, -1};
      if (pos.c + 2 < m_cols && At(pos.r, pos.c + 2) == WALL && pos.c + 2 != m_cols - 1)
        options[n++] = {0, 1};

      if (n > 0)
      {
        const Cell d = options[RandomIn(0, n)];
        const Cell wall{pos.r + d.r, pos.c + d.c};
        const Cell to{pos.r + 2 * d.r, pos.c + 2 * d.c};
        Carve(pos, wall, to);
        pos = to;
        moves.push_back(pos);
      }
      else
      {
        pos = moves.back();
        moves.pop_back();
      }
    }
  }

  int m_rows, m_cols;
  std::mt19937& m_rng;
  std::vector<uint8_t> m_blocked;
  std::vector<int> m_prev;
  std::vector<Cell> m_order;
  std::vector<Cell> m_solution;
  Cell m_start{1, 0}, m_end{0, 0}, m_target{0, 0};
};

} // namespace mazer

// Standalone checks for the maze generator and animator (no Kodi needed):
//   c++ -O2 -std=c++17 -Isrc tests/maze_test.cpp -o maze_test && ./maze_test
// Optional snapshot of a solved maze: ./maze_test out.ppm [cell_px rows cols seed]

#include "Mazer.h"

#include <cstdio>
#include <cstdlib>
#include <set>

#define CHECK(cond)                                                              \
  do                                                                             \
  {                                                                              \
    if (!(cond))                                                                 \
    {                                                                            \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);       \
      std::exit(1);                                                              \
    }                                                                            \
  } while (0)

using namespace mazer;

static void CheckMaze(int rows, int cols, const std::string& clock, int scale, bool centre,
                      uint32_t seed)
{
  std::mt19937 rng(seed);
  Maze m(rows, cols, clock, scale, centre, rng);

  // every lit cell is inside the grid and lit once
  std::set<int> seen;
  for (const Cell& c : m.order())
  {
    CHECK(c.r >= 0 && c.r < rows && c.c >= 0 && c.c < cols);
    CHECK(seen.insert(c.r * cols + c.c).second);
  }

  // the solution runs from the entrance to the exit through adjacent open cells
  const auto& s = m.solution();
  CHECK(s.size() > 2);
  CHECK(s.front().r == m.start().r && s.front().c == m.start().c);
  CHECK(s.back().r == m.end().r && s.back().c == m.end().c);
  for (size_t i = 0; i < s.size(); i++)
  {
    CHECK(m.blocked(s[i].r, s[i].c) == Maze::SPACE);
    CHECK(seen.count(s[i].r * cols + s[i].c));
    if (i)
      CHECK(std::abs(s[i].r - s[i - 1].r) + std::abs(s[i].c - s[i - 1].c) == 1);
  }

  // with a clock, its lit pixels count matches the glyphs + frame
  if (!clock.empty())
  {
    const auto block = ClockBlock(clock, scale);
    CHECK(static_cast<int>(block.size()) == 9 * scale);
    CHECK(static_cast<int>(block[0].size()) == 23 * scale);
    int noGo = 0;
    for (int r = 0; r < rows; r++)
      for (int c = 0; c < cols; c++)
        noGo += m.blocked(r, c) == Maze::NO_GO;
    const bool fits = rows - 8 >= 9 * scale && cols - 8 >= 23 * scale;
    CHECK(noGo == (fits ? 9 * scale * 23 * scale : 0));
  }
}

static void WritePpm(const char* path, const Animator& a, int px)
{
  FILE* f = std::fopen(path, "wb");
  if (!f)
    return;
  std::fprintf(f, "P6 %d %d 255\n", a.cols() * px, a.rows() * px);
  const auto& p = a.pixels();
  for (int y = a.rows() * px - 1; y >= 0; y--) // texture row 0 is the bottom
    for (int x = 0; x < a.cols() * px; x++)
    {
      const size_t i = (static_cast<size_t>(y / px) * a.cols() + x / px) * 4;
      std::fputc(p[i], f);
      std::fputc(p[i + 1], f);
      std::fputc(p[i + 2], f);
    }
  std::fclose(f);
}

int main(int argc, char** argv)
{
  for (uint32_t seed = 1; seed <= 40; seed++)
  {
    CheckMaze(154, 274, "12:34", 1, false, seed); // 1080p at the default size
    CheckMaze(155, 275, "09:41", 2, seed % 2, seed);
    CheckMaze(72, 128, "23:59", 3, true, seed);
    CheckMaze(540, 960, "", 1, false, seed);
    CheckMaze(20, 30, "10:10", 3, false, seed); // too small for the clock: skipped
  }
  CHECK(ClockText(true, 0).size() == 5);

  // run the animator through two full cycles at 60 fps
  Settings s;
  s.buildSeconds = 3;
  s.solveSeconds = 1;
  Animator a;
  const int px = argc > 2 ? std::atoi(argv[2]) : 4;
  const int rows = argc > 3 ? std::atoi(argv[3]) : 154;
  const int cols = argc > 4 ? std::atoi(argv[4]) : 274;
  a.Init(rows, cols, s, argc > 5 ? std::atoi(argv[5]) : 7);
  const double dt = 1.0 / 60.0;
  int frames = 0, cycles = 0;
  Animator::Phase last = a.phase();
  bool wrote = false;
  while (cycles < 2 && frames < 60 * 60)
  {
    a.Update(dt);
    frames++;
    if (a.phase() == Animator::PAUSE_SOLVED && !wrote && argc > 1 && a.activeCells() == 0)
    {
      WritePpm(argv[1], a, px);
      wrote = true;
    }
    if (last == Animator::RESET && a.phase() == Animator::BUILD)
      cycles++;
    last = a.phase();
  }
  CHECK(cycles == 2);
  // build 3 + pause 1 + solve 1 + pause 2 + reset 1 = 8 s a cycle (plus fades)
  std::printf("2 cycles in %.1f s\n", frames * dt);
  CHECK(frames * dt > 15.0 && frames * dt < 17.5);

  std::printf("ok\n");
  return 0;
}

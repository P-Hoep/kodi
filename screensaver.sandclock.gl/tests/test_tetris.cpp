// Tests for the GL-free Tetris engine: pieces, the board with the block clock and settling,
// El-Tetris, the game state and the clockface. The rendering is checked by `tetris_glfw --shot`
// and by the shader compiler in CMake.
#include <cmath>
#include <cstdio>
#include <random>
#include <set>
#include <string>
#include <vector>

#include "tetris.hpp"

using namespace tetris;

static int failures = 0;
#define CHECK(cond, ...)                                                \
  do {                                                                  \
    if (!(cond)) {                                                      \
      std::printf("FAIL %s:%d  %s  ", __FILE__, __LINE__, #cond);       \
      std::printf(__VA_ARGS__);                                         \
      std::printf("\n");                                                \
      ++failures;                                                       \
    }                                                                   \
  } while (0)

static bool has_cell(const std::vector<Cell>& cells, int x, int y) {
  for (const Cell& c : cells) {
    if (c.x == x && c.y == y) return true;
  }
  return false;
}

static int count_letter(const Board& board, char letter) {
  int count = 0;
  for (int y = 0; y < board.height; ++y) {
    for (int x = 0; x < board.cols; ++x) {
      if (board.letters[y][x] == letter) ++count;
    }
  }
  return count;
}

static bool board_consistent(const Board& board) {
  for (int y = 0; y < board.height; ++y) {
    uint64_t bits = 0;
    for (int x = 0; x < board.cols; ++x) {
      if (board.letters[y][x]) bits |= 1ull << x;
      const bool filled = ((board.bits[y] >> x) & 1u) != 0;
      if (filled != (board.letters[y][x] != 0)) return false;
      if ((board.bits[y] >> x) & ~board.full_mask) return false;
    }
    if (bits != board.bits[y]) return false;
  }
  return true;
}

static bool something_hanging(const Board& board) {
  // A rigid 4-connected group of piece cells that can fall as a whole.
  std::vector<std::vector<char>> seen(board.height, std::vector<char>(board.cols, 0));
  for (int y = 0; y < board.height; ++y) {
    for (int x = 0; x < board.cols; ++x) {
      const char letter = board.letters[y][x];
      if (!letter || letter == FIXED || seen[y][x]) continue;
      std::vector<Cell> group;
      std::vector<Cell> stack{{x, y}};
      seen[y][x] = 1;
      while (!stack.empty()) {
        Cell c = stack.back();
        stack.pop_back();
        group.push_back(c);
        const int dx[4] = {1, -1, 0, 0}, dy[4] = {0, 0, 1, -1};
        for (int d = 0; d < 4; ++d) {
          const int nx = c.x + dx[d], ny = c.y + dy[d];
          if (nx >= 0 && nx < board.cols && ny >= 0 && ny < board.height && !seen[ny][nx] &&
              board.letters[ny][nx] && board.letters[ny][nx] != FIXED) {
            seen[ny][nx] = 1;
            stack.push_back({nx, ny});
          }
        }
      }
      bool clear_below = true;
      for (const Cell& c : group) {
        bool in_group_below = false;
        for (const Cell& other : group) {
          if (other.x == c.x && other.y == c.y + 1) in_group_below = true;
        }
        const bool empty_below =
            c.y + 1 < board.height && board.letters[c.y + 1][c.x] == 0;
        if (!in_group_below && !empty_below) {
          clear_below = false;
          break;
        }
      }
      if (clear_below) return true;
    }
  }
  return false;
}

int main() {
  // ---------------------------------------------------------------- pieces
  CHECK(piece('O').count == 1, "O rotations %d", piece('O').count);
  CHECK(piece('I').count == 2, "I rotations %d", piece('I').count);
  CHECK(piece('S').count == 2 && piece('Z').count == 2, "S/Z rotations");
  CHECK(piece('T').count == 4 && piece('J').count == 4 && piece('L').count == 4, "T/J/L rotations");
  for (char letter : PIECE_TYPES) {
    CHECK(piece(letter).shapes[0].size() == 4, "%c cells", letter);
    CHECK(shape_width(piece(letter).shapes[0]) <= 4, "%c width", letter);
    CHECK(!piece(letter).masks[0].empty(), "%c masks", letter);
  }
  CHECK(shape_width(piece('I').shapes[0]) == 4 && shape_height(piece('I').shapes[0]) == 1, "I shape");
  CHECK(shape_width(piece('O').shapes[0]) == 2 && shape_height(piece('O').shapes[0]) == 2, "O shape");

  // ---------------------------------------------------------------- board size
  CHECK(columns_for(96) == 20, "96 -> %d", columns_for(96));
  CHECK(columns_for(64) == 30, "64 -> %d", columns_for(64));
  CHECK(columns_for(60) == 32, "60 -> %d", columns_for(60));
  CHECK(columns_for(32) == 60, "32 -> %d", columns_for(32));
  CHECK(columns_for(1000) == 10, "tiny boards are at least 10 columns");
  Settings size;
  size.block_size = 48;
  CHECK(columns(size) == 40, "settings columns %d", columns(size));

  // ---------------------------------------------------------------- clock
  CHECK(clock_width(false) == 17 && clock_width(true) == 27, "clock widths");
  CHECK(!clock_fits(16, false) && clock_fits(17, false), "HH:MM fits 17");
  CHECK(!clock_fits(26, true) && clock_fits(27, true), "HH:MM:SS needs 27");
  auto bottom = clock_cells(12, 27, 42, true, 30, ROWS, false, false);
  auto floating = clock_cells(12, 27, 42, true, 30, ROWS, false, true);
  CHECK(!bottom.empty() && bottom.size() == floating.size(), "clock cells %zu", bottom.size());
  int min_y = ROWS, max_y = 0, min_x = 99, max_x = 0;
  for (const Cell& c : bottom) {
    min_y = std::min(min_y, c.y);
    max_y = std::max(max_y, c.y);
    min_x = std::min(min_x, c.x);
    max_x = std::max(max_x, c.x);
  }
  CHECK(min_y == ROWS - 5 && max_y == ROWS - 1, "bottom clock rows %d..%d", min_y, max_y);
  CHECK(min_x == (30 - 17) / 2 && max_x == min_x + 17 - 1, "clock centred %d..%d", min_x, max_x);
  int floating_min_y = ROWS, floating_max_y = 0;
  for (const Cell& c : floating) {
    floating_min_y = std::min(floating_min_y, c.y);
    floating_max_y = std::max(floating_max_y, c.y);
  }
  CHECK(floating_min_y == ROWS - 8 && floating_max_y == ROWS - 4, "floating clock rows %d..%d",
        floating_min_y, floating_max_y);
  CHECK(clock_cells(12, 27, 42, true, 16, ROWS, false, false).empty(), "no clock without room");
  CHECK(clock_cells(12, 27, 42, true, 17, ROWS, true, false) ==
            clock_cells(12, 27, 42, true, 17, ROWS, false, false),
        "seconds dropped when they do not fit");
  // 01:11 in 17 columns: glyphs start at x = 0, 4, 8, 10, 14; 1 is 010/110/010/010/111.
  auto one = clock_cells(1, 11, 0, true, 17, ROWS, false, false);
  CHECK(has_cell(one, 5, ROWS - 5) && !has_cell(one, 4, ROWS - 5) && has_cell(one, 4, ROWS - 4),
        "the glyph for 1");
  CHECK(has_cell(one, 8, ROWS - 4) && has_cell(one, 8, ROWS - 2), "the colon");
  CHECK(!clock_cells(12, 27, 42, true, 27, ROWS, true, false).empty(), "seconds fit at 27");

  // ---------------------------------------------------------------- text clock
  CHECK(clock_text(0, 5, 9, false, false) == "12:05 AM", "%s",
        clock_text(0, 5, 9, false, false).c_str());
  CHECK(clock_text(12, 5, 9, false, true) == "12:05:09 PM", "%s",
        clock_text(12, 5, 9, false, true).c_str());
  CHECK(clock_text(23, 59, 59, true, true) == "23:59:59", "%s",
        clock_text(23, 59, 59, true, true).c_str());
  CHECK(clock_text(23, 59, 59, true, false) == "23:59", "%s",
        clock_text(23, 59, 59, true, false).c_str());
  CHECK(clock_text(7, 8, 9, false, false) == "7:08 AM", "%s",
        clock_text(7, 8, 9, false, false).c_str());

  // ---------------------------------------------------------------- colours
  Settings colours;
  auto classic = piece_colours(colours);
  CHECK(classic[0].r == 0 && classic[0].g == 240 && classic[0].b == 240, "classic I is cyan");
  colours.scheme = scheme_count();
  colours.custom[1] = Rgb{1, 2, 3};
  CHECK(piece_colours(colours)[1].g == 2, "custom colours");
  Rgb parsed;
  CHECK(parse_colour("FF00F0F0", &parsed) && parsed.r == 0 && parsed.g == 240, "AARRGGBB");
  CHECK(parse_colour("f0a000", &parsed) && parsed.r == 240 && parsed.g == 160, "RRGGBB");
  CHECK(!parse_colour("nope", &parsed), "bad colour");

  // ---------------------------------------------------------------- board
  Board board(6, 8);
  CHECK(board.full_mask == 63, "full mask");
  CHECK(board.landing(piece('O').masks[0], 0) == 6, "O lands on the floor");
  CHECK(board.fits(piece('O').masks[0], 0, 0) && !board.fits(piece('O').masks[0], 5, 0), "O fits");
  board.place('O', piece('O').shapes[0], 0, 6);
  CHECK(board.landing(piece('O').masks[0], 0) == 4, "O lands on the stack");
  CHECK(board.landing(piece('O').masks[0], 3) == 6, "next to the stack");
  CHECK(board.column_height(0) == 2 && board.column_height(2) == 0, "column heights");
  CHECK(board_consistent(board), "board consistent");

  // Full rows clear, the clock stays put and the cells above fall.
  Board rows(4, 4);
  rows.set_fixed({{1, 2}});
  for (int x : {0, 2, 3}) rows.place('T', {{x, 2}}, 0, 0);
  rows.place('S', {{0, 0}}, 0, 0);
  CHECK(rows.full_rows() == std::vector<int>{2}, "one full row");
  CHECK(rows.remove_rows({2}) == 1, "removed one");
  CHECK(rows.letters[2][1] == FIXED, "clock stays");
  CHECK(rows.letters[2][0] == 0, "pieces cleared");
  CHECK(rows.letters[3][0] == 'S', "the cell above fell clear to the floor");
  CHECK(rows.letters[1][0] == 0 && rows.letters[0][0] == 0, "nothing hangs above it");
  CHECK(board_consistent(rows), "rows consistent");

  // A clock change drops what rested on the vanished digit, as a whole piece.
  Board settle(6, 8);
  settle.set_fixed({{1, 4}});
  settle.place('O', piece('O').shapes[0], 0, 2);
  settle.set_fixed({{4, 7}});
  CHECK(settle.letters[6][0] == 'O' && settle.letters[6][1] == 'O', "O fell to row 6");
  CHECK(settle.letters[7][0] == 'O' && settle.letters[7][1] == 'O', "O fell to row 7");
  CHECK(settle.letters[4][0] == 0 && settle.letters[5][0] == 0, "the old spot is empty");
  CHECK(settle.letters[7][4] == FIXED, "the new clock digit is there");

  // Supported pieces stay put.
  Board rest(6, 8);
  rest.set_fixed({{1, 4}});
  rest.place('O', piece('O').shapes[0], 0, 2);
  rest.set_fixed({{1, 4}, {4, 7}});
  CHECK(rest.letters[3][0] == 'O' && rest.letters[4][0] == 0, "a supported piece stays");

  // Settling leaves nothing hanging, on random stacks.
  {
    std::mt19937 rng(3);
    std::uniform_real_distribution<double> chance(0, 1);
    for (int trial = 0; trial < 40; ++trial) {
      Board b(10, 12);
      std::vector<Cell> fixed;
      for (int y = 0; y < 12; ++y) {
        for (int x = 0; x < 10; ++x) {
          if (chance(rng) < 0.08) fixed.push_back({x, y});
        }
      }
      b.set_fixed(fixed);
      std::uniform_int_distribution<int> type(0, 6);
      for (int p = 0; p < 12; ++p) {
        char letter = PIECE_TYPES[type(rng)];
        const Piece& piece = tetris::piece(letter);
        std::uniform_int_distribution<int> rot(0, piece.count - 1);
        const int rotation = rot(rng);
        const Shape& shape = piece.shapes[rotation];
        std::uniform_int_distribution<int> px(0, std::max(0, 9 - shape_width(shape)));
        std::uniform_int_distribution<int> py(0, 11);
        const int x = px(rng), y = py(rng);
        if (b.fits(piece.masks[rotation], x, y)) b.place(letter, shape, x, y);
      }
      b.settle();
      CHECK(!something_hanging(b), "trial %d leaves something hanging", trial);
      CHECK(board_consistent(b), "trial %d inconsistent", trial);
    }
  }

  // ---------------------------------------------------------------- AI
  Board empty(20, ROWS);
  for (char letter : PIECE_TYPES) {
    auto places = candidates(empty, letter);
    CHECK(!places.empty(), "%c has placements", letter);
    for (const Placement& p : places) {
      CHECK(p.y >= 0 && p.x >= 0, "%c at %d,%d", letter, p.x, p.y);
    }
    for (size_t i = 1; i < places.size(); ++i) {
      CHECK(places[i - 1].score >= places[i].score, "%c sorted", letter);
    }
  }
  CHECK(candidates(empty, 'I').front().lines == 0, "no line on an empty board");
  std::mt19937 rng(7);
  Placement best = choose(empty, 'T', rng, 0);
  CHECK(best.ok && best.score == candidates(empty, 'T').front().score, "perfect skill takes the best");

  // Every candidate lands exactly on the existing stack.
  Board stack(12, ROWS);
  for (int x = 0; x < 12; ++x) stack.place('J', {{x, ROWS - 1}}, 0, 0);
  stack.place('L', {{5, ROWS - 2}}, 0, 0);
  for (const Placement& p : candidates(stack, 'S')) {
    CHECK(!stack.fits(piece('S').masks[p.rotation], p.x, p.y + 1), "S candidate rests");
    CHECK(stack.fits(piece('S').masks[p.rotation], p.x, p.y), "S candidate fits");
  }

  // Blocked at spawn: no placements means game over.
  Board blocked(4, 4);
  for (int x = 0; x < 4; ++x) blocked.place('J', {{x, 0}}, 0, 0);
  CHECK(candidates(blocked, 'I').empty(), "nothing fits under a full top row");

  // ---------------------------------------------------------------- game
  Board play_board(30, ROWS);
  std::mt19937 play_rng(11);
  Game game(&play_board, &play_rng, 3);
  CHECK(game.level == 3 && game.score == 0 && game.lines == 0, "start state");
  std::set<char> bag;
  for (int i = 0; i < 7; ++i) bag.insert(game.take());
  CHECK(bag.size() == 7, "one of each in a bag");
  game.lock(4);
  CHECK(game.score == 800 * 3 && game.lines == 4 && game.level == 3, "score and lines");
  game.lock(0);
  for (int i = 0; i < 26; ++i) game.lock(1);
  CHECK(game.level == 6, "level after 30 lines: %d", game.level);
  game.reset();
  CHECK(game.score == 0 && game.level == 3 && play_board.empty(), "reset");

  // A long game with the block clock running: the invariants hold and the AI never gets stuck.
  {
    Settings s;
    s.block_size = 64;
    s.clock_seconds = true;
    s.start_level = 1;
    s.skill = 0;
    Board b(columns(s), ROWS);
    std::mt19937 r(99);
    Game g(&b, &r, s.start_level);
    int hour = 9, minute = 41, second = 3;
    int placements = 0;
    for (int piece_no = 0; piece_no < 400 && placements < 400; ++piece_no) {
      // Tick the clock often; the engine accepts a new pattern only when nothing is in the way.
      if (piece_no % 3 == 0) {
        second = (second + 1) % 60;
        if (second == 0) minute = (minute + 1) % 60;
        auto cells = clock_cells(hour, minute, second, false, b.cols, ROWS, true, false);
        if (!cells.empty() && b.can_set_fixed(cells)) b.set_fixed(cells);
      }
      char letter = g.take();
      Placement p = choose(b, letter, r, s.skill);
      if (!p.ok) {
        g.reset();
        b.clear();
        continue;
      }
      const Shape& shape = piece(letter).shapes[p.rotation];
      if (!b.fits(piece(letter).masks[p.rotation], p.x, p.y)) {
        CHECK(false, "chosen placement does not fit");
        break;
      }
      b.place(letter, shape, p.x, p.y);
      auto full = b.full_rows();
      if (!full.empty()) b.remove_rows(full);
      g.lock(static_cast<int>(full.size()));
      ++placements;
      CHECK(board_consistent(b), "piece %d inconsistent", piece_no);
      CHECK(!something_hanging(b), "piece %d leaves something hanging", piece_no);
    }
    CHECK(placements == 400, "played %d pieces", placements);
    CHECK(count_letter(b, FIXED) > 0, "the clock stayed on the board");
    CHECK(g.pieces == 400, "piece count %d", g.pieces);
  }

  std::printf(failures ? "%d FAILED\n" : "tetris tests passed\n", failures);
  return failures ? 1 : 0;
}

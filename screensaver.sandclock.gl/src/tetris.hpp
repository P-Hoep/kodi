// The Tetris AI engine: pieces, the bitmask playfield with the block clock, El-Tetris, the
// 7-bag game state and the clockface. A faithful port of screensaver.tetris/resources/lib,
// kept free of GL and Kodi so it can be tested on its own.
#pragma once

#include <array>
#include <cstdint>
#include <random>
#include <string>
#include <vector>

namespace tetris {

constexpr int W = 1920;
constexpr int H = 1080;
constexpr int ROWS = 18;
constexpr int BLOCK_W = 96;
constexpr int BLOCK_W_MIN = 32;
constexpr int BLOCK_W_MAX = 96;
constexpr int BLOCK_W_STEP = 4;

constexpr double THINK_SECONDS = 0.12;
constexpr double MOVE_SECONDS = 0.045;
constexpr double DROP_SECONDS = 0.020;
constexpr int LEVEL_LINES = 10;
constexpr int MAX_LEVEL = 20;

constexpr char FIXED = '#';
constexpr char PIECE_TYPES[7] = {'I', 'O', 'T', 'S', 'Z', 'J', 'L'};

struct Rgb {
  uint8_t r = 0, g = 0, b = 0;
};

struct Cell {
  int x = 0, y = 0;
};

inline bool operator==(const Cell& a, const Cell& b) { return a.x == b.x && a.y == b.y; }
inline bool operator!=(const Cell& a, const Cell& b) { return !(a == b); }

struct RowMask {
  int dy = 0;
  uint64_t mask = 0;
};

using Shape = std::vector<Cell>;
using Masks = std::vector<RowMask>;

// A cell that moved down as the result of a line clear or of the clock settling.
struct CellMove {
  int x = 0, y = 0, ny = 0;
};

struct Piece {
  std::array<Shape, 4> shapes;
  std::array<Masks, 4> masks;
  int count = 0;
};

const std::array<Piece, 7>& pieces();
const Piece& piece(char letter);
int piece_index(char letter);
int shape_width(const Shape& shape);
int shape_height(const Shape& shape);

// ---------------------------------------------------------------- settings

struct Settings {
  int skill = 0;
  int speed = 100;
  int start_level = 1;
  bool progressive = true;
  bool ghost = true;
  bool show_next = true;

  int scheme = 0;
  int block_size = BLOCK_W;
  bool show_grid = true;
  bool show_hud = true;
  int hud_opacity = 60;
  Rgb background{6, 8, 15};
  std::array<Rgb, 7> custom{{Rgb{0, 240, 240}, Rgb{240, 240, 0}, Rgb{160, 0, 240},
                             Rgb{0, 240, 0}, Rgb{240, 0, 0}, Rgb{0, 0, 240},
                             Rgb{240, 160, 0}}};

  bool show_clock = true;
  int clock_style = 0;
  bool clock_seconds = false;
  bool clock_24h = false;
  int clock_position = 0;
  Rgb clock_colour{232, 236, 244};

  void sanitise();
};

const char* const* scheme_names();
int scheme_count();
std::array<Rgb, 7> piece_colours(const Settings& settings);
// "AARRGGBB" or "RRGGBB", as Kodi stores colours; false on anything else.
bool parse_colour(const std::string& value, Rgb* out);

int columns_for(int block_width);
int columns(const Settings& settings);

struct Delays {
  double think = THINK_SECONDS;
  double move = MOVE_SECONDS;
  double drop = DROP_SECONDS;
};
Delays delays(const Settings& settings, int level);

// ---------------------------------------------------------------- board

class Board {
 public:
  Board() = default;
  Board(int cols, int rows) { reset(cols, rows); }

  void reset(int cols, int rows);

  int cols = 0;
  int height = 0;
  uint64_t full_mask = 0;
  std::vector<uint64_t> bits;
  std::vector<std::vector<char>> letters;
  std::vector<uint64_t> fixed_bits;
  std::vector<std::vector<char>> fixed_letters;

  bool empty() const;
  bool fits(const Masks& masks, int x, int y) const;
  bool fits_bits(const Masks& masks, int x, int y, const std::vector<uint64_t>& bits) const;
  int landing(const Masks& masks, int x) const;
  int landing_bits(const Masks& masks, int x, const std::vector<uint64_t>& bits) const;
  std::vector<int> full_rows() const;
  int column_height(int x) const;
  bool cell_filled(int x, int y) const {
    return (bits[y] >> x) & 1u;
  }

  bool can_set_fixed(const std::vector<Cell>& cells) const;
  void set_fixed(const std::vector<Cell>& cells);
  bool settle();
  void place(char letter, const Shape& shape, int x, int y);
  // Remove these full rows. The cells above fall, fixed cells stay, and anything left in the
  // air (a clear can take the support out from under a piece) settles to the stack.
  int remove_rows(const std::vector<int>& rows);
  void clear();

 private:
  std::vector<std::vector<Cell>> piece_groups() const;
  void move_group(const std::vector<Cell>& group, int distance);
};

// ---------------------------------------------------------------- the AI

struct Placement {
  int rotation = 0;
  int x = 0;
  int y = 0;
  double score = 0;
  int lines = 0;
  bool ok = false;
};

std::vector<Placement> candidates(const Board& board, char letter);
Placement choose(const Board& board, char letter, std::mt19937& rng, int skill);

// ---------------------------------------------------------------- game state

class Game {
 public:
  Game() = default;
  Game(Board* board, std::mt19937* rng, int start_level) { init(board, rng, start_level); }
  void init(Board* board, std::mt19937* rng, int start_level);

  char take();
  void lock(int rows_cleared);
  void reset();

  Board* board = nullptr;
  std::mt19937* rng = nullptr;
  int start_level = 1;
  char next = 'I';
  int score = 0;
  int lines = 0;
  int level = 1;
  int pieces = 0;

 private:
  char take_from_bag();
  std::vector<char> bag_;
};

// ---------------------------------------------------------------- the clock

int clock_width(bool seconds);
bool clock_fits(int cols, bool seconds);
std::vector<Cell> clock_cells(int hour, int minute, int second, bool twenty_four_hour, int cols,
                              int rows, bool seconds, bool floating);
std::string clock_text(int hour, int minute, int second, bool twenty_four_hour, bool seconds);

}  // namespace tetris

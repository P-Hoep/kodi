#include "tetris.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <numeric>
#include <set>

namespace tetris {
namespace {

Shape spawn_shape(char letter) {
  switch (letter) {
    case 'I': return {{0, 0}, {1, 0}, {2, 0}, {3, 0}};
    case 'O': return {{0, 0}, {1, 0}, {0, 1}, {1, 1}};
    case 'T': return {{1, 0}, {0, 1}, {1, 1}, {2, 1}};
    case 'S': return {{1, 0}, {2, 0}, {0, 1}, {1, 1}};
    case 'Z': return {{0, 0}, {1, 0}, {1, 1}, {2, 1}};
    case 'J': return {{0, 0}, {0, 1}, {1, 1}, {2, 1}};
    case 'L': return {{2, 0}, {0, 1}, {1, 1}, {2, 1}};
    default: return {};
  }
}

bool cell_less(const Cell& a, const Cell& b) {
  return a.y != b.y ? a.y < b.y : a.x < b.x;
}

Shape normalise(Shape shape) {
  if (shape.empty()) return shape;
  int min_x = shape.front().x, min_y = shape.front().y;
  for (const Cell& c : shape) {
    min_x = std::min(min_x, c.x);
    min_y = std::min(min_y, c.y);
  }
  for (Cell& c : shape) {
    c.x -= min_x;
    c.y -= min_y;
  }
  std::sort(shape.begin(), shape.end(), cell_less);
  return shape;
}

Shape turned(const Shape& shape) {
  int height = 0;
  for (const Cell& c : shape) height = std::max(height, c.y + 1);
  Shape out;
  out.reserve(shape.size());
  for (const Cell& c : shape) out.push_back({height - 1 - c.y, c.x});
  return normalise(out);
}

bool same_shape(const Shape& a, const Shape& b) {
  if (a.size() != b.size()) return false;
  for (size_t i = 0; i < a.size(); ++i) {
    if (a[i].x != b[i].x || a[i].y != b[i].y) return false;
  }
  return true;
}

Masks make_masks(const Shape& shape) {
  std::vector<RowMask> rows;
  for (const Cell& c : shape) {
    bool found = false;
    for (RowMask& r : rows) {
      if (r.dy == c.y) {
        r.mask |= 1ull << c.x;
        found = true;
        break;
      }
    }
    if (!found) rows.push_back({c.y, 1ull << c.x});
  }
  std::sort(rows.begin(), rows.end(),
            [](const RowMask& a, const RowMask& b) { return a.dy < b.dy; });
  return rows;
}

int mask_width(uint64_t mask) {
  int width = 0;
  while (mask) {
    ++width;
    mask >>= 1;
  }
  return width;
}

int popcount(uint64_t value) {
  return __builtin_popcountll(value);
}

const char* const kSchemeNames[] = {"Classic", "NES",   "Neon",     "Pastel", "Monochrome",
                                    "Game Boy", "Sunset", "Ocean", "Vaporwave"};

const char* const kSchemeColours[][7] = {
    {"00F0F0", "F0F000", "A000F0", "00F000", "F00000", "0000F0", "F0A000"},
    {"00A8A8", "A8A800", "A800A8", "00A800", "A80000", "0000A8", "A85000"},
    {"00FFFF", "FFF700", "D000FF", "39FF14", "FF1E56", "2E5BFF", "FF9E00"},
    {"9EE7E3", "F7EE9B", "D5B3E8", "A8DFA3", "F2A6A6", "9DB8F0", "F6C79A"},
    {"FFFFFF", "E4E9F2", "C9D0DC", "AEB6C4", "939CAD", "788294", "5D6779"},
    {"9BBC0F", "8BAC0F", "7B9A0E", "6A890C", "59780A", "486708", "375606"},
    {"FF8E72", "FFD166", "C44D9B", "7BD389", "E84855", "6C5CE7", "FFA63D"},
    {"00D2FF", "FFD166", "00C9A7", "3A7BD5", "0077B6", "035AA6", "2EC4B6"},
    {"00F0FF", "FFE66D", "B026FF", "39FF88", "FF2E63", "7B2FF7", "FF6EC7"},
};

Rgb from_hex6(const char* hex) {
  auto nibble = [](char c) -> int {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return 0;
  };
  Rgb out;
  out.r = static_cast<uint8_t>(nibble(hex[0]) * 16 + nibble(hex[1]));
  out.g = static_cast<uint8_t>(nibble(hex[2]) * 16 + nibble(hex[3]));
  out.b = static_cast<uint8_t>(nibble(hex[4]) * 16 + nibble(hex[5]));
  return out;
}

constexpr int SKILL_COUNT = 5;
constexpr double SKILL_BEST_CHANCE[SKILL_COUNT] = {1.00, 0.90, 0.72, 0.40, 0.12};
constexpr int SKILL_POOL[SKILL_COUNT] = {0, 2, 4, -1, -1};

constexpr double W_LANDING = -4.500158825082766;
constexpr double W_LINES = 3.4181268101392694;
constexpr double W_ROW = -3.2178882868487753;
constexpr double W_COL = -9.348695305445199;
constexpr double W_HOLES = -7.899265427351652;
constexpr double W_WELLS = -3.3855972247263626;
constexpr double W_HEIGHT = -2.0;

int row_transitions(const std::vector<uint64_t>& bits, int cols) {
  int total = 0;
  for (uint64_t row : bits) {
    int prev = 0;
    for (int x = 0; x < cols; ++x) {
      const int bit = static_cast<int>((row >> x) & 1u);
      total += bit != prev;
      prev = bit;
    }
    total += prev;
  }
  return total;
}

int column_transitions(const std::vector<uint64_t>& bits, int cols, int rows) {
  int total = 0;
  for (int x = 0; x < cols; ++x) {
    int prev = 0;
    for (int y = 0; y < rows; ++y) {
      const int bit = static_cast<int>((bits[y] >> x) & 1u);
      total += bit != prev;
      prev = bit;
    }
    total += prev;
  }
  return total;
}

int holes(const std::vector<uint64_t>& bits, int cols, int rows) {
  int total = 0;
  for (int x = 0; x < cols; ++x) {
    bool seen = false;
    for (int y = 0; y < rows; ++y) {
      if ((bits[y] >> x) & 1u) {
        seen = true;
      } else if (seen) {
        ++total;
      }
    }
  }
  return total;
}

int wells(const std::vector<uint64_t>& bits, int cols, int rows) {
  int total = 0;
  for (int x = 0; x < cols; ++x) {
    for (int y = 0; y < rows; ++y) {
      if ((bits[y] >> x) & 1u) continue;
      const bool left = x == 0 || ((bits[y] >> (x - 1)) & 1u);
      const bool right = x == cols - 1 || ((bits[y] >> (x + 1)) & 1u);
      if (!(left && right)) continue;
      int depth = 0;
      int yy = y;
      while (yy < rows && !((bits[yy] >> x) & 1u)) {
        ++depth;
        ++yy;
      }
      total += depth;
    }
  }
  return total;
}

int max_height(const std::vector<uint64_t>& bits, int rows) {
  for (int y = 0; y < rows; ++y) {
    if (bits[y]) return rows - y;
  }
  return 0;
}

double score_board(const std::vector<uint64_t>& bits, int cols, int rows, double landing_height,
                   int cleared) {
  return W_LANDING * landing_height + W_LINES * cleared + W_ROW * row_transitions(bits, cols) +
         W_COL * column_transitions(bits, cols, rows) + W_HOLES * holes(bits, cols, rows) +
         W_WELLS * wells(bits, cols, rows) + W_HEIGHT * max_height(bits, rows);
}

int random_int(std::mt19937& rng, int lo, int hi) {
  std::uniform_int_distribution<int> dist(lo, hi);
  return dist(rng);
}

}  // namespace

const std::array<Piece, 7>& pieces() {
  static const std::array<Piece, 7> built = [] {
    std::array<Piece, 7> out;
    for (int i = 0; i < 7; ++i) {
      Piece p;
      Shape first = normalise(spawn_shape(PIECE_TYPES[i]));
      p.shapes[0] = first;
      int count = 1;
      for (int turn = 0; turn < 3; ++turn) {
        Shape nxt = turned(p.shapes[count - 1]);
        bool duplicate = false;
        for (int k = 0; k < count; ++k) {
          if (same_shape(nxt, p.shapes[k])) duplicate = true;
        }
        if (duplicate) break;
        p.shapes[count++] = nxt;
      }
      p.count = count;
      for (int r = 0; r < count; ++r) p.masks[r] = make_masks(p.shapes[r]);
      out[i] = p;
    }
    return out;
  }();
  return built;
}

int piece_index(char letter) {
  for (int i = 0; i < 7; ++i) {
    if (PIECE_TYPES[i] == letter) return i;
  }
  return -1;
}

const Piece& piece(char letter) {
  const int index = piece_index(letter);
  return pieces()[index < 0 ? 0 : index];
}

int shape_width(const Shape& shape) {
  int width = 0;
  for (const Cell& c : shape) width = std::max(width, c.x + 1);
  return width;
}

int shape_height(const Shape& shape) {
  int height = 0;
  for (const Cell& c : shape) height = std::max(height, c.y + 1);
  return height;
}

void Settings::sanitise() {
  skill = std::min(SKILL_COUNT - 1, std::max(0, skill));
  speed = std::min(400, std::max(25, speed));
  start_level = std::min(MAX_LEVEL, std::max(1, start_level));
  block_size = std::min(BLOCK_W_MAX, std::max(BLOCK_W_MIN, block_size));
  block_size = BLOCK_W_MIN + ((block_size - BLOCK_W_MIN) / BLOCK_W_STEP) * BLOCK_W_STEP;
  block_size = std::min(BLOCK_W_MAX, block_size);
  scheme = std::min(scheme_count(), std::max(0, scheme));
  hud_opacity = std::min(90, std::max(0, hud_opacity));
  clock_style = std::min(1, std::max(0, clock_style));
  clock_position = std::min(1, std::max(0, clock_position));
}

const char* const* scheme_names() { return kSchemeNames; }

int scheme_count() { return static_cast<int>(sizeof(kSchemeNames) / sizeof(kSchemeNames[0])); }

std::array<Rgb, 7> piece_colours(const Settings& settings) {
  std::array<Rgb, 7> out;
  if (settings.scheme >= scheme_count()) {
    return settings.custom;
  }
  const int index = std::max(0, settings.scheme);
  for (int i = 0; i < 7; ++i) out[i] = from_hex6(kSchemeColours[index][i]);
  return out;
}

bool parse_colour(const std::string& value, Rgb* out) {
  std::string v;
  for (char c : value) {
    if (c == '#' || c == ' ') continue;
    v.push_back(c);
  }
  if (v.size() == 6) v = "FF" + v;
  if (v.size() != 8) return false;
  for (char c : v) {
    if (!std::isxdigit(static_cast<unsigned char>(c))) return false;
  }
  const Rgb rgb = from_hex6(v.c_str() + 2);
  if (out) *out = rgb;
  return true;
}

int columns_for(int block_width) {
  if (block_width <= 0) return 20;
  const int value = static_cast<int>(std::lround(static_cast<double>(W) / block_width));
  return std::max(10, value);
}

int columns(const Settings& settings) { return columns_for(settings.block_size); }

Delays delays(const Settings& settings, int level) {
  double factor = settings.speed / 100.0;
  if (settings.progressive) factor *= std::min(2.6, 1.0 + 0.10 * (level - 1));
  Delays out;
  out.think = std::max(0.030, THINK_SECONDS / factor);
  out.move = std::max(0.008, MOVE_SECONDS / factor);
  out.drop = std::max(0.006, DROP_SECONDS / factor);
  return out;
}

// ---------------------------------------------------------------- board

void Board::reset(int new_cols, int new_rows) {
  cols = new_cols;
  height = new_rows;
  full_mask = cols >= 64 ? ~0ull : ((1ull << cols) - 1ull);
  bits.assign(height, 0);
  letters.assign(height, std::vector<char>(cols, 0));
  fixed_bits.assign(height, 0);
  fixed_letters.assign(height, std::vector<char>(cols, 0));
}

bool Board::empty() const {
  for (uint64_t row : bits) {
    if (row) return false;
  }
  return true;
}

bool Board::fits_bits(const Masks& masks, int x, int y,
                      const std::vector<uint64_t>& board_bits) const {
  if (x < 0) return false;
  int width = 0;
  for (const RowMask& m : masks) width = std::max(width, mask_width(m.mask));
  if (x + width > cols) return false;
  for (const RowMask& m : masks) {
    const int yy = y + m.dy;
    if (yy < 0 || yy >= height) return false;
    if (board_bits[yy] & (m.mask << x)) return false;
  }
  return true;
}

bool Board::fits(const Masks& masks, int x, int y) const {
  return fits_bits(masks, x, y, bits);
}

int Board::landing_bits(const Masks& masks, int x,
                        const std::vector<uint64_t>& board_bits) const {
  if (!fits_bits(masks, x, 0, board_bits)) return -1;
  int y = 0;
  while (fits_bits(masks, x, y + 1, board_bits)) ++y;
  return y;
}

int Board::landing(const Masks& masks, int x) const { return landing_bits(masks, x, bits); }

std::vector<int> Board::full_rows() const {
  std::vector<int> out;
  for (int y = 0; y < height; ++y) {
    if (bits[y] == full_mask) out.push_back(y);
  }
  return out;
}

int Board::column_height(int x) const {
  for (int y = 0; y < height; ++y) {
    if ((bits[y] >> x) & 1u) return height - y;
  }
  return 0;
}

bool Board::can_set_fixed(const std::vector<Cell>& cells) const {
  for (const Cell& c : cells) {
    if (c.x < 0 || c.x >= cols || c.y < 0 || c.y >= height) return false;
    if ((bits[c.y] >> c.x) & 1u && !((fixed_bits[c.y] >> c.x) & 1u)) return false;
  }
  return true;
}

void Board::set_fixed(const std::vector<Cell>& cells) {
  for (int y = 0; y < height; ++y) {
    const uint64_t old = fixed_bits[y];
    if (!old) continue;
    bits[y] &= ~old;
    for (int x = 0; x < cols; ++x) {
      if ((old >> x) & 1u) letters[y][x] = 0;
    }
  }
  fixed_bits.assign(height, 0);
  fixed_letters.assign(height, std::vector<char>(cols, 0));
  for (const Cell& c : cells) {
    if (c.x < 0 || c.x >= cols || c.y < 0 || c.y >= height) continue;
    fixed_bits[c.y] |= 1ull << c.x;
    fixed_letters[c.y][c.x] = FIXED;
    bits[c.y] |= 1ull << c.x;
    letters[c.y][c.x] = FIXED;
  }
  settle();
}

std::vector<std::vector<Cell>> Board::piece_groups() const {
  std::vector<std::vector<char>> seen(height, std::vector<char>(cols, 0));
  std::vector<std::vector<Cell>> groups;
  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < cols; ++x) {
      const char letter = letters[y][x];
      if (letter == 0 || letter == FIXED || seen[y][x]) continue;
      std::vector<Cell> group;
      std::vector<Cell> stack;
      stack.push_back({x, y});
      seen[y][x] = 1;
      while (!stack.empty()) {
        const Cell c = stack.back();
        stack.pop_back();
        group.push_back(c);
        static const int DX[4] = {1, -1, 0, 0};
        static const int DY[4] = {0, 0, 1, -1};
        for (int d = 0; d < 4; ++d) {
          const int nx = c.x + DX[d];
          const int ny = c.y + DY[d];
          if (nx >= 0 && nx < cols && ny >= 0 && ny < height && !seen[ny][nx]) {
            const char other = letters[ny][nx];
            if (other != 0 && other != FIXED) {
              seen[ny][nx] = 1;
              stack.push_back({nx, ny});
            }
          }
        }
      }
      groups.push_back(std::move(group));
    }
  }
  return groups;
}

void Board::move_group(const std::vector<Cell>& group, int distance) {
  struct Saved {
    int x, y;
    char letter;
  };
  std::vector<Saved> saved;
  saved.reserve(group.size());
  for (const Cell& c : group) {
    saved.push_back({c.x, c.y, letters[c.y][c.x]});
    bits[c.y] &= ~(1ull << c.x);
    letters[c.y][c.x] = 0;
  }
  for (const Saved& s : saved) {
    bits[s.y + distance] |= 1ull << s.x;
    letters[s.y + distance][s.x] = s.letter;
  }
}

bool Board::settle() {
  bool moved = false;
  while (true) {
    std::vector<std::vector<Cell>> groups = piece_groups();
    if (groups.empty()) return moved;
    std::stable_sort(groups.begin(), groups.end(),
                     [](const std::vector<Cell>& a, const std::vector<Cell>& b) {
                       int max_a = 0, max_b = 0;
                       for (const Cell& c : a) max_a = std::max(max_a, c.y);
                       for (const Cell& c : b) max_b = std::max(max_b, c.y);
                       return max_a > max_b;
                     });
    bool fell = false;
    for (const std::vector<Cell>& group : groups) {
      std::vector<int> bottom(cols, -1);
      for (const Cell& c : group) bottom[c.x] = std::max(bottom[c.x], c.y);
      int distance = height;
      for (int x = 0; x < cols; ++x) {
        if (bottom[x] < 0) continue;
        int y = bottom[x] + 1;
        while (y < height && letters[y][x] == 0) ++y;
        distance = std::min(distance, y - bottom[x] - 1);
      }
      if (distance > 0) {
        move_group(group, distance);
        fell = moved = true;
      }
    }
    if (!fell) return moved;
  }
}

void Board::place(char letter, const Shape& shape, int x, int y) {
  for (const Cell& c : shape) {
    const int xx = x + c.x;
    const int yy = y + c.y;
    if (xx >= 0 && xx < cols && yy >= 0 && yy < height) {
      bits[yy] |= 1ull << xx;
      letters[yy][xx] = letter;
    }
  }
}

int Board::remove_rows(const std::vector<int>& rows) {
  if (rows.empty()) return 0;
  std::vector<char> removed(height, 0);
  for (int y : rows) {
    if (y >= 0 && y < height) removed[y] = 1;
  }
  int removed_count = 0;
  for (int y = 0; y < height; ++y) {
    if (removed[y]) {
      ++removed_count;
    } else {
    }
  }
  if (!removed_count) return 0;

  struct PieceCell {
    int x, y;
    char letter;
  };
  std::vector<PieceCell> cells;
  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < cols; ++x) {
      const char letter = letters[y][x];
      if (letter != 0 && letter != FIXED) cells.push_back({x, y, letter});
    }
  }
  bits = fixed_bits;
  letters = fixed_letters;
  std::stable_sort(cells.begin(), cells.end(),
                   [](const PieceCell& a, const PieceCell& b) { return a.y > b.y; });
  for (const PieceCell& c : cells) {
    if (removed[c.y]) continue;
    int above = 0;
    for (int r = 0; r < height; ++r) {
      if (removed[r] && r > c.y) ++above;
    }
    int yy = c.y + above;
    while (yy >= 0 && ((bits[yy] >> c.x) & 1u)) --yy;  // never enter the clock
    if (yy < 0) continue;
    bits[yy] |= 1ull << c.x;
    letters[yy][c.x] = c.letter;
  }
  settle();
  return removed_count;
}

void Board::clear() {
  bits = fixed_bits;
  letters = fixed_letters;
}

// ---------------------------------------------------------------- the AI

std::vector<Placement> candidates(const Board& board, char letter) {
  std::vector<Placement> out;
  const Piece& p = piece(letter);
  for (int rotation = 0; rotation < p.count; ++rotation) {
    const Shape& shape = p.shapes[rotation];
    const Masks& masks = p.masks[rotation];
    const int width = shape_width(shape);
    for (int x = 0; x <= board.cols - width; ++x) {
      const int y = board.landing(masks, x);
      if (y < 0) continue;
      std::vector<uint64_t> after = board.bits;
      int cells = 0;
      int height_sum = 0;
      for (const RowMask& m : masks) {
        after[y + m.dy] |= m.mask << x;
        const int count = popcount(m.mask);
        cells += count;
        height_sum += count * (board.height - (y + m.dy));
      }
      const double landing_height =
          cells ? static_cast<double>(height_sum) / cells : static_cast<double>(board.height);
      std::vector<uint64_t> kept;
      kept.reserve(after.size());
      for (uint64_t row : after) {
        if (row != board.full_mask) kept.push_back(row);
      }
      const int cleared = static_cast<int>(after.size() - kept.size());
      if (cleared) kept.insert(kept.begin(), static_cast<size_t>(cleared), 0ull);
      Placement place;
      place.rotation = rotation;
      place.x = x;
      place.y = y;
      place.lines = cleared;
      place.score = score_board(kept, board.cols, board.height, landing_height, cleared);
      place.ok = true;
      out.push_back(place);
    }
  }
  std::stable_sort(out.begin(), out.end(),
                   [](const Placement& a, const Placement& b) { return a.score > b.score; });
  return out;
}

Placement choose(const Board& board, char letter, std::mt19937& rng, int skill) {
  std::vector<Placement> places = candidates(board, letter);
  if (places.empty()) return Placement();
  const int level = std::min(SKILL_COUNT - 1, std::max(0, skill));
  std::uniform_real_distribution<double> chance(0.0, 1.0);
  if (places.size() == 1 || chance(rng) < SKILL_BEST_CHANCE[level]) return places.front();
  const int pool = SKILL_POOL[level];
  if (pool > 0) {
    const int last = std::min(static_cast<int>(places.size()) - 1, pool);
    if (last < 1) return places.front();
    return places[static_cast<size_t>(random_int(rng, 1, last))];
  }
  if (places.size() > 1) {
    return places[static_cast<size_t>(random_int(rng, 1, static_cast<int>(places.size()) - 1))];
  }
  return places.front();
}

// ---------------------------------------------------------------- game state

void Game::init(Board* new_board, std::mt19937* new_rng, int new_start_level) {
  board = new_board;
  rng = new_rng;
  start_level = std::min(MAX_LEVEL, std::max(1, new_start_level));
  bag_.clear();
  next = take_from_bag();
  score = 0;
  lines = 0;
  level = start_level;
  pieces = 0;
}

char Game::take_from_bag() {
  if (bag_.empty()) {
    bag_.assign(std::begin(PIECE_TYPES), std::end(PIECE_TYPES));
    std::shuffle(bag_.begin(), bag_.end(), *rng);
  }
  const char letter = bag_.back();
  bag_.pop_back();
  return letter;
}

char Game::take() {
  const char letter = next;
  next = take_from_bag();
  ++pieces;
  return letter;
}

void Game::lock(int rows_cleared) {
  static const int SCORE[5] = {0, 100, 300, 500, 800};
  score += SCORE[std::min(4, rows_cleared)] * level;
  lines += rows_cleared;
  if (lines) level = std::min(MAX_LEVEL, start_level + lines / LEVEL_LINES);
}

void Game::reset() {
  if (board) board->clear();
  bag_.clear();
  next = take_from_bag();
  score = 0;
  lines = 0;
  level = start_level;
  pieces = 0;
}

// ---------------------------------------------------------------- the clock

namespace {
const char* const kDigits[10][5] = {
    {"111", "101", "101", "101", "111"}, {"010", "110", "010", "010", "111"},
    {"111", "001", "111", "100", "111"}, {"111", "001", "111", "001", "111"},
    {"101", "101", "111", "001", "001"}, {"111", "100", "111", "001", "111"},
    {"111", "100", "111", "101", "111"}, {"111", "001", "001", "001", "001"},
    {"111", "101", "111", "101", "111"}, {"111", "101", "111", "001", "111"},
};
const char* const kColon[5] = {"0", "1", "0", "1", "0"};
constexpr int DIGIT_W = 3;
constexpr int GAP = 1;
constexpr int COLON_W = 1;
constexpr int CLOCK_HEIGHT = 5;
constexpr int SUSPENDED_GAP = 3;
}  // namespace

int clock_width(bool seconds) {
  const int digits = seconds ? 6 : 4;
  const int colons = seconds ? 2 : 1;
  return digits * DIGIT_W + colons * COLON_W + (digits + colons - 1) * GAP;
}

bool clock_fits(int cols, bool seconds) { return clock_width(seconds) <= cols; }

std::vector<Cell> clock_cells(int hour, int minute, int second, bool twenty_four_hour, int cols,
                              int rows, bool seconds, bool floating) {
  if (seconds && !clock_fits(cols, true)) seconds = false;
  if (!clock_fits(cols, seconds)) return {};
  int display_hour = hour;
  if (!twenty_four_hour) display_hour = hour % 12 ? hour % 12 : 12;
  char text[5];
  std::snprintf(text, sizeof(text), "%02d%02d", display_hour, minute);

  std::vector<const char* const*> glyphs;  // five row strings each
  glyphs.push_back(kDigits[text[0] - '0']);
  glyphs.push_back(kDigits[text[1] - '0']);
  glyphs.push_back(kColon);
  glyphs.push_back(kDigits[text[2] - '0']);
  glyphs.push_back(kDigits[text[3] - '0']);
  if (seconds) {
    glyphs.push_back(kColon);
    const int tens = second / 10;
    const int ones = second % 10;
    glyphs.push_back(kDigits[tens]);
    glyphs.push_back(kDigits[ones]);
  }

  const int left = (cols - clock_width(seconds)) / 2;
  const int top = floating ? std::max(0, rows - CLOCK_HEIGHT - SUSPENDED_GAP)
                           : rows - CLOCK_HEIGHT;
  std::vector<Cell> out;
  int x = left;
  for (const char* const* glyph : glyphs) {
    const int width = static_cast<int>(std::strlen(glyph[0]));
    for (int row = 0; row < CLOCK_HEIGHT; ++row) {
      for (int dx = 0; dx < width; ++dx) {
        if (glyph[row][dx] == '1') out.push_back({x + dx, top + row});
      }
    }
    x += width + GAP;
  }
  return out;
}

std::string clock_text(int hour, int minute, int second, bool twenty_four_hour, bool seconds) {
  char text[32];
  if (twenty_four_hour) {
    if (seconds) {
      std::snprintf(text, sizeof(text), "%02d:%02d:%02d", hour, minute, second);
    } else {
      std::snprintf(text, sizeof(text), "%02d:%02d", hour, minute);
    }
    return text;
  }
  const int display_hour = hour % 12 ? hour % 12 : 12;
  const char* suffix = hour < 12 ? "AM" : "PM";
  if (seconds) {
    std::snprintf(text, sizeof(text), "%d:%02d:%02d %s", display_hour, minute, second, suffix);
  } else {
    std::snprintf(text, sizeof(text), "%d:%02d %s", display_hour, minute, suffix);
  }
  return text;
}

}  // namespace tetris

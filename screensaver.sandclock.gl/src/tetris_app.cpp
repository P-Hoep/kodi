#include "tetris_app.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "gl_util.hpp"

namespace sandclock {
namespace tetrisgl {
namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kFlashSeconds = 0.24;
constexpr double kGameOverSeconds = 1.6;
constexpr float kGhostAlpha = 0x50 / 255.0f;
constexpr float kVignette = 0.55f;

const tetris::Rgb kCaption{0x8F, 0xA0, 0xB8};
const tetris::Rgb kValue{0xF5, 0xF7, 0xFB};
const tetris::Rgb kClockText{0xFF, 0xFF, 0xFF};
const tetris::Rgb kGameOverText{0xFF, 0x6B, 0x6B};

float smooth(double t) { return static_cast<float>(t * t * (3.0 - 2.0 * t)); }

tetris::Rgb mix(const tetris::Rgb& a, const tetris::Rgb& b, float t) {
  return tetris::Rgb{static_cast<uint8_t>(a.r + (b.r - a.r) * t),
                     static_cast<uint8_t>(a.g + (b.g - a.g) * t),
                     static_cast<uint8_t>(a.b + (b.b - a.b) * t)};
}

// 5x7 cell bitmaps, ASCII 32..90, row by row from the top.
const char* const kFont[][7] = {
    {".....", ".....", ".....", ".....", ".....", ".....", "....."},  // space
    {"..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."},  // !
    {"#...#", "#...#", ".....", ".....", ".....", ".....", "....."},  // "
    {".#.#.", ".#.#.", "#####", ".#.#.", "#####", ".#.#.", ".#.#."},  // #
    {"..#..", ".####", "#.#..", ".###.", "..#.#", "####.", "..#.."},  // $
    {"##..#", "##..#", "...#.", "..#..", ".#...", "#..##", "#..##"},  // %
    {".##..", "#..#.", "#.#..", ".#...", "#.#.#", "#..#.", ".##.#"},  // &
    {"..#..", "..#..", ".....", ".....", ".....", ".....", "....."},  // '
    {"...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."},  // (
    {".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."},  // )
    {".....", "#.#.#", ".###.", "#####", ".###.", "#.#.#", "....."},  // *
    {".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."},  // +
    {".....", ".....", ".....", ".....", ".....", "..##.", "..#.."},  // ,
    {".....", ".....", ".....", "#####", ".....", ".....", "....."},  // -
    {".....", ".....", ".....", ".....", ".....", "..##.", "..##."},  // .
    {"....#", "...#.", "..#..", ".#...", "#....", ".....", "....."},  // /
    {".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."},  // 0
    {"..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."},  // 1
    {".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"},  // 2
    {"#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."},  // 3
    {"...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."},  // 4
    {"#####", "#....", "####.", "....#", "....#", "#...#", ".###."},  // 5
    {"..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."},  // 6
    {"#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."},  // 7
    {".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."},  // 8
    {".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."},  // 9
    {".....", "..##.", "..##.", ".....", "..##.", "..##.", "....."},  // :
    {".....", "..##.", "..##.", ".....", "..##.", "..#..", "....."},  // ;
    {"...#.", "..#..", ".#...", "#....", ".#...", "..#..", "...#."},  // <
    {".....", ".....", "#####", ".....", "#####", ".....", "....."},  // =
    {".#...", "..#..", "...#.", "....#", "...#.", "..#..", ".#..."},  // >
    {".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."},  // ?
    {".###.", "#...#", "#.###", "#.#.#", "#.###", "#....", ".###."},  // @
    {".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"},  // A
    {"####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."},  // B
    {".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."},  // C
    {"###..", "#..#.", "#...#", "#...#", "#...#", "#..#.", "###.."},  // D
    {"#####", "#....", "#....", "####.", "#....", "#....", "#####"},  // E
    {"#####", "#....", "#....", "####.", "#....", "#....", "#...."},  // F
    {".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".###."},  // G
    {"#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"},  // H
    {".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."},  // I
    {"..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."},  // J
    {"#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"},  // K
    {"#....", "#....", "#....", "#....", "#....", "#....", "#####"},  // L
    {"#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"},  // M
    {"#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"},  // N
    {".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."},  // O
    {"####.", "#...#", "#...#", "####.", "#....", "#....", "#...."},  // P
    {".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"},  // Q
    {"####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"},  // R
    {".####", "#....", "#....", ".###.", "....#", "....#", "####."},  // S
    {"#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."},  // T
    {"#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."},  // U
    {"#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."},  // V
    {"#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"},  // W
    {"#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"},  // X
    {"#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."},  // Y
    {"#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"},  // Z
};
constexpr int kFontCount = static_cast<int>(sizeof(kFont) / sizeof(kFont[0]));
constexpr int kAtlasCols = 16;
constexpr int kAtlasRows = 8;
constexpr int kCellW = 6;
constexpr int kCellH = 8;
constexpr int kAtlasW = kAtlasCols * kCellW;
constexpr int kAtlasH = kAtlasRows * kCellH;

// ---------------------------------------------------------------- shaders

const char* const kBlockVertex = R"(
attribute vec2 a_pos;
attribute vec2 a_size;
attribute vec2 a_corner;
attribute vec4 a_colour;
attribute float a_mode;
uniform vec2 u_screen;
varying vec2 v_local;
varying vec2 v_size;
varying vec4 v_colour;
varying float v_mode;
void main() {
    v_local = a_corner * a_size;
    v_size = a_size;
    v_colour = a_colour;
    v_mode = a_mode;
    vec2 p = a_pos + v_local;
    gl_Position = vec4(p.x / u_screen.x * 2.0 - 1.0, 1.0 - p.y / u_screen.y * 2.0, 0.0, 1.0);
}
)";

const char* const kBlockFragment = R"(
varying vec2 v_local;
varying vec2 v_size;
varying vec4 v_colour;
varying float v_mode;

float rounded_box(vec2 p, vec2 half_size, float r) {
    vec2 q = abs(p) - half_size + r;
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}

void main() {
    vec2 half_size = v_size * 0.5;
    float base_radius = min(half_size.x, half_size.y);
    float radius = v_mode > 0.5 ? base_radius * 0.085 : base_radius * 0.16;
    float d = rounded_box(v_local - half_size, half_size, radius);
    float aa = 1.0 - smoothstep(-1.0, 1.0, d);
    vec3 col = v_colour.rgb;
    if (v_mode < 0.5) {
        float rim = (1.0 - smoothstep(0.0, 2.2, -d)) * step(d, 0.0);
        float bevel = 1.0 - smoothstep(0.07 * v_size.y, 0.36 * v_size.y, v_local.y);
        float face = 0.84 + 0.11 * (1.0 - smoothstep(0.36 * v_size.y, v_size.y, v_local.y));
        col = mix(col * face, col * 1.06, bevel);
        col = mix(col, col * 0.45, rim);
    } else {
        float sheen = 1.0 - smoothstep(0.0, 0.55 * v_size.y, v_local.y);
        col = mix(col, vec3(1.0), 0.030 * sheen);
        float rim = (1.0 - smoothstep(0.0, 1.3, -d)) * step(d, 0.0);
        col = mix(col, vec3(1.0), 0.10 * rim);
    }
    gl_FragColor = vec4(col, v_colour.a * aa);
}
)";

const char* const kBackgroundFragment = R"(
varying vec2 v_uv;
uniform vec3 u_colour;
uniform float u_grid;
uniform float u_vignette;
void main() {
    vec3 col = u_colour;
    col *= 1.0 + 0.16 * smoothstep(0.55, 0.0, v_uv.y);
    col *= 1.0 - 0.16 * smoothstep(0.45, 1.0, v_uv.y);
    col = mix(col, vec3(1.0), 0.086 * u_grid);
    vec2 px = v_uv * vec2(1920.0, 1080.0);
    float edge = min(min(px.x, 1920.0 - px.x), min(px.y, 1080.0 - px.y));
    float border = u_grid * (1.0 - smoothstep(1.5, 3.5, edge));
    col = mix(col, vec3(1.0), border * 0.22);
    float r = length((v_uv - 0.5) * vec2(1.0, 0.92)) * 1.15;
    col *= 1.0 - u_vignette * smoothstep(0.40, 0.82, r);
    gl_FragColor = vec4(col, 1.0);
}
)";

const char* const kTextVertex = R"(
attribute vec2 a_pos;
attribute vec2 a_uv;
attribute vec4 a_colour;
uniform vec2 u_screen;
varying vec2 v_uv;
varying vec4 v_colour;
void main() {
    v_uv = a_uv;
    v_colour = a_colour;
    gl_Position = vec4(a_pos.x / u_screen.x * 2.0 - 1.0, 1.0 - a_pos.y / u_screen.y * 2.0, 0.0, 1.0);
}
)";

const char* const kTextFragment = R"(
varying vec2 v_uv;
varying vec4 v_colour;
uniform sampler2D u_atlas;
void main() {
    gl_FragColor = vec4(v_colour.rgb, v_colour.a * texture2D(u_atlas, v_uv).a);
}
)";

}  // namespace

App::App() = default;
App::~App() = default;

bool App::make_program(const char* vertex, const char* fragment, const char* const* attributes,
                       int attribute_count, unsigned* program, std::string* error) {
  unsigned vs = glu::compile(GL_VERTEX_SHADER, vertex ? vertex : glu::quad_vertex(), error);
  if (!vs) return false;
  unsigned fs = glu::compile(GL_FRAGMENT_SHADER, fragment, error);
  if (!fs) {
    glDeleteShader(vs);
    return false;
  }
  unsigned prog = glCreateProgram();
  glAttachShader(prog, vs);
  glAttachShader(prog, fs);
  for (int i = 0; i < attribute_count; ++i) glBindAttribLocation(prog, i, attributes[i]);
  glLinkProgram(prog);
  glDeleteShader(vs);
  glDeleteShader(fs);
  int ok = 0;
  glGetProgramiv(prog, GL_LINK_STATUS, &ok);
  if (!ok) {
    char log[2048];
    glGetProgramInfoLog(prog, sizeof log, nullptr, log);
    *error = std::string("link: ") + log;
    glDeleteProgram(prog);
    return false;
  }
  *program = prog;
  return true;
}

void App::release() {
  const unsigned programs[] = {program_background_, program_block_, program_text_};
  for (unsigned program : programs) {
    if (program) glDeleteProgram(program);
  }
  const unsigned buffers[] = {buffer_background_, buffer_block_, buffer_text_};
  for (unsigned buffer : buffers) {
    if (buffer) glDeleteBuffers(1, &buffer);
  }
  if (atlas_) glDeleteTextures(1, &atlas_);
#ifdef SANDCLOCK_CORE
  if (vao_) glDeleteVertexArrays(1, &vao_);
  vao_ = 0;
#endif
  program_background_ = program_block_ = program_text_ = 0;
  buffer_background_ = buffer_block_ = buffer_text_ = 0;
  atlas_ = 0;
}

void App::build_atlas() {
  std::vector<unsigned char> pixels(static_cast<size_t>(kAtlasW) * kAtlasH * 4, 0);
  for (int i = 0; i < kFontCount; ++i) {
    const int col = i % kAtlasCols;
    const int row = i / kAtlasCols;
    for (int gy = 0; gy < 7 && gy < kCellH; ++gy) {
      for (int gx = 0; gx < 5 && gx < kCellW; ++gx) {
        if (kFont[i][gy][gx] != '#') continue;
        const int ax = col * kCellW + gx;
        const int ay = row * kCellH + gy;
        const int ty = kAtlasH - 1 - ay;  // GL puts the first row at the bottom
        const size_t index = (static_cast<size_t>(ty) * kAtlasW + ax) * 4;
        pixels[index + 0] = 255;
        pixels[index + 1] = 255;
        pixels[index + 2] = 255;
        pixels[index + 3] = 255;
      }
    }
  }
  glGenTextures(1, &atlas_);
  glBindTexture(GL_TEXTURE_2D, atlas_);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, kAtlasW, kAtlasH, 0, GL_RGBA, GL_UNSIGNED_BYTE,
               pixels.data());
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glBindTexture(GL_TEXTURE_2D, 0);
}

bool App::init(const tetris::Settings& settings, unsigned seed, std::string* error) {
  settings_ = settings;
  settings_.sanitise();
  cols_ = tetris::columns(settings_);
  colours_ = tetris::piece_colours(settings_);
  best_ = 0;
  rng_.seed(seed ? seed : std::random_device{}());
  board_.reset(cols_, tetris::ROWS);
  game_.init(&board_, &rng_, settings_.start_level);

  clock_key_ = -1;
  started_ = false;
  now_ = -1;
  phase_ = Phase::Think;
  phase_start_ = 0;
  clearing_rows_.clear();
  offsets_.clear();
  fall_start_ = -1;
  now_ = -1;

  build_atlas();

  const char* const block_attributes[] = {"a_pos", "a_size", "a_corner", "a_colour", "a_mode"};
  const char* const text_attributes[] = {"a_pos", "a_uv", "a_colour"};
  bool ok = make_program(kBlockVertex, kBlockFragment, block_attributes, 5, &program_block_,
                         error) &&
            make_program(kTextVertex, kTextFragment, text_attributes, 3, &program_text_, error) &&
            make_program(nullptr, kBackgroundFragment, nullptr, 0, &program_background_, error);
  if (!ok) {
    release();
    return false;
  }

  background_screen_ = glGetUniformLocation(program_background_, "u_screen");
  background_colour_ = glGetUniformLocation(program_background_, "u_colour");
  background_grid_ = glGetUniformLocation(program_background_, "u_grid");
  background_vignette_ = glGetUniformLocation(program_background_, "u_vignette");
  block_screen_ = glGetUniformLocation(program_block_, "u_screen");
  text_atlas_ = glGetUniformLocation(program_text_, "u_atlas");
  text_screen_ = glGetUniformLocation(program_text_, "u_screen");

  const float quad[8] = {-1, -1, 1, -1, -1, 1, 1, 1};
  glGenBuffers(1, &buffer_background_);
  glBindBuffer(GL_ARRAY_BUFFER, buffer_background_);
  glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
  glGenBuffers(1, &buffer_block_);
  glGenBuffers(1, &buffer_text_);
  glBindBuffer(GL_ARRAY_BUFFER, 0);

#ifdef SANDCLOCK_CORE
  glGenVertexArrays(1, &vao_);
#endif
  glUseProgram(program_text_);
  glUniform1i(text_atlas_, 0);
  glUseProgram(0);
  return true;
}

// ---------------------------------------------------------------- the loop

void App::spawn(double now) {
  const tetris::Delays d = tetris::delays(settings_, game_.level);
  think_seconds_ = d.think;
  move_seconds_ = d.move;
  drop_seconds_ = d.drop;

  letter_ = game_.take();
  const tetris::Placement placement = tetris::choose(board_, letter_, rng_, settings_.skill);
  if (!placement.ok) {
    phase_ = Phase::GameOver;
    phase_start_ = now;
    return;
  }
  rotation_ = placement.rotation;
  shape_ = tetris::piece(letter_).shapes[rotation_];
  target_x_ = placement.x;
  target_y_ = placement.y;

  const int width = tetris::shape_width(shape_);
  spawn_x_ = std::max(0, std::min(cols_ - width, cols_ / 2 - width / 2));
  if (!board_.fits(tetris::piece(letter_).masks[rotation_], spawn_x_, 0)) spawn_x_ = target_x_;
  vis_x_ = spawn_x_;
  vis_y_ = 0;

  // The delays are one column of slide and one row of fall, as in the Python add-on, so a
  // 12-row drop takes 12 drop delays instead of one: the piece is visibly in motion instead
  // of covering the whole distance in a single frame.
  move_seconds_ = d.move * std::max(1, std::abs(target_x_ - spawn_x_));
  drop_seconds_ = d.drop * std::max(1, target_y_);

  phase_ = Phase::Think;
  phase_start_ = now;
}

void App::update(double now) {
  if (now < now_) now = now_;
  now_ = now;
  // Once per frame, not once per piece: the block clock ticks every second even when the
  // game runs slowly.
  maybe_update_clock(now);
  if (!started_) {
    started_ = true;
    spawn(now);
    return;
  }
  switch (phase_) {
    case Phase::Think:
      if (now - phase_start_ >= think_seconds_) {
        phase_start_ += think_seconds_;
        phase_ = Phase::Moving;
      }
      break;
    case Phase::Moving:
      if (now - phase_start_ >= move_seconds_) {
        phase_start_ += move_seconds_;
        phase_ = Phase::Dropping;
      }
      break;
    case Phase::Dropping:
      if (now - phase_start_ >= drop_seconds_) {
        phase_start_ += drop_seconds_;
        lock_piece(now);
      }
      break;
    case Phase::Flashing:
      if (now - phase_start_ >= kFlashSeconds) {
        phase_start_ += kFlashSeconds;
        finish_flash(now);
      }
      break;
    case Phase::Falling:
      if (now - phase_start_ >= fall_duration_) {
        phase_start_ += fall_duration_;
        offsets_.clear();
        fall_start_ = -1;
        spawn(now);
      }
      break;
    case Phase::GameOver:
      if (now - phase_start_ >= kGameOverSeconds) restart(now);
      break;
  }
}

void App::lock_piece(double now) {
  board_.place(letter_, shape_, target_x_, target_y_);
  std::vector<int> rows = board_.full_rows();
  if (rows.empty()) {
    game_.lock(0);
    best_ = std::max(best_, static_cast<long>(game_.score));
    spawn(now);
    return;
  }
  clearing_rows_ = rows;
  phase_ = Phase::Flashing;
  (void)now;
}

void App::finish_flash(double now) {
  const int cleared = static_cast<int>(clearing_rows_.size());
  game_.lock(cleared);
  best_ = std::max(best_, static_cast<long>(game_.score));
  const std::vector<std::vector<char>> before = board_.letters;
  board_.remove_rows(clearing_rows_);
  const double start = phase_start_;
  const int distance = start_fall_animation(before, clearing_rows_, start);
  clearing_rows_.clear();
  if (distance == 0) {
    spawn(now);
    return;
  }
  phase_ = Phase::Falling;
}

void App::restart(double now) {
  best_ = std::max(best_, static_cast<long>(game_.score));
  game_.reset();
  board_.clear();
  offsets_.clear();
  fall_start_ = -1;
  clearing_rows_.clear();
  spawn(now);
}

void App::maybe_update_clock(double now) {
  if (!settings_.show_clock || settings_.clock_style != 1) return;
  int total = static_cast<int>(clock_seconds_);
  if (total < 0) total = 0;
  const int hour = (total / 3600) % 24;
  const int minute = (total / 60) % 60;
  const int second = total % 60;
  const bool seconds = settings_.clock_seconds && tetris::clock_fits(cols_, true);
  const int key = hour * 10000 + minute * 100 + (seconds ? second : 0);
  if (key == clock_key_) return;
  const bool floating = settings_.clock_position == 1;
  const std::vector<tetris::Cell> cells =
      tetris::clock_cells(hour, minute, second, settings_.clock_24h, cols_, tetris::ROWS,
                          seconds, floating);
  if (cells.empty() || !board_.can_set_fixed(cells)) return;
  const std::vector<std::vector<char>> before = board_.letters;
  board_.set_fixed(cells);
  clock_key_ = key;
  start_fall_animation(before, {}, now);
}

int App::start_fall_animation(const std::vector<std::vector<char>>& before,
                              const std::vector<int>& removed_rows, double now) {
  std::vector<char> removed(tetris::ROWS, 0);
  for (int y : removed_rows) {
    if (y >= 0 && y < tetris::ROWS) removed[y] = 1;
  }
  offsets_.assign(static_cast<size_t>(cols_) * tetris::ROWS, 0.0f);
  int max_distance = 0;
  for (int x = 0; x < cols_; ++x) {
    std::vector<int> old_rows;
    for (int y = tetris::ROWS - 1; y >= 0; --y) {
      const char letter = (y < static_cast<int>(before.size()) && x < cols_)
                              ? before[y][x]
                              : 0;
      if (letter != 0 && letter != tetris::FIXED && !removed[y]) old_rows.push_back(y);
    }
    std::vector<int> new_rows;
    for (int y = tetris::ROWS - 1; y >= 0; --y) {
      const char letter = board_.letters[y][x];
      if (letter != 0 && letter != tetris::FIXED) new_rows.push_back(y);
    }
    const size_t count = std::min(old_rows.size(), new_rows.size());
    for (size_t i = 0; i < count; ++i) {
      const int distance = new_rows[i] - old_rows[i];
      if (distance <= 0) continue;
      offsets_[static_cast<size_t>(new_rows[i]) * cols_ + x] = -static_cast<float>(distance);
      max_distance = std::max(max_distance, distance);
    }
  }
  if (max_distance == 0) {
    offsets_.clear();
    fall_start_ = -1;
    fall_duration_ = 0;
    return 0;
  }
  fall_start_ = now;
  fall_duration_ = std::min(0.55, 0.16 + 0.045 * max_distance);
  return max_distance;
}

double App::fall_progress(double now) const {
  if (fall_start_ < 0 || fall_duration_ <= 0) return 1;
  double t = (now - fall_start_) / fall_duration_;
  t = t < 0 ? 0 : (t > 1 ? 1 : t);
  return t * t;
}

// ---------------------------------------------------------------- geometry

void App::add_block(std::vector<BlockVertex>& out, float x, float y, float w, float h,
                    const tetris::Rgb& colour, float alpha, float mode) {
  static const float CORNER[6][2] = {{0, 0}, {1, 0}, {1, 1}, {0, 0}, {1, 1}, {0, 1}};
  const float r = colour.r / 255.0f;
  const float g = colour.g / 255.0f;
  const float b = colour.b / 255.0f;
  for (const auto& corner : CORNER) {
    BlockVertex v;
    v.x = x;
    v.y = y;
    v.w = w;
    v.h = h;
    v.u = corner[0];
    v.v = corner[1];
    v.r = r;
    v.g = g;
    v.b = b;
    v.a = alpha;
    v.mode = mode;
    out.push_back(v);
  }
}

float App::text_width(const std::string& text, float scale) {
  if (text.empty()) return 0;
  return static_cast<float>(text.size()) * kCellW * scale - scale;
}

void App::add_text(std::vector<TextVertex>& out, const std::string& text, float x, float y,
                   float scale, const tetris::Rgb& colour, float alpha) {
  const float r = colour.r / 255.0f;
  const float g = colour.g / 255.0f;
  const float b = colour.b / 255.0f;
  const float w = kCellW * scale;
  const float h = kCellH * scale;
  for (size_t i = 0; i < text.size(); ++i) {
    const int index = static_cast<int>(static_cast<unsigned char>(text[i])) - 32;
    const int glyph = (index >= 0 && index < kFontCount) ? index : 0;
    const int col = glyph % kAtlasCols;
    const int row = glyph / kAtlasCols;
    const float x0 = x + static_cast<float>(i) * w;
    const float y0 = y;
    const float u0 = static_cast<float>(col * kCellW) / kAtlasW;
    const float u1 = static_cast<float>(col * kCellW + kCellW) / kAtlasW;
    const float v1 = 1.0f - static_cast<float>(row * kCellH) / kAtlasH;
    const float v0 = 1.0f - static_cast<float>(row * kCellH + kCellH) / kAtlasH;
    const float px[6] = {x0, x0 + w, x0 + w, x0, x0 + w, x0};
    const float py[6] = {y0, y0, y0 + h, y0, y0 + h, y0 + h};
    const float pu[6] = {u0, u1, u1, u0, u1, u0};
    const float pv[6] = {v1, v1, v0, v1, v0, v0};
    for (int k = 0; k < 6; ++k) {
      TextVertex v;
      v.x = px[k];
      v.y = py[k];
      v.u = pu[k];
      v.v = pv[k];
      v.r = r;
      v.g = g;
      v.b = b;
      v.a = alpha;
      out.push_back(v);
    }
  }
}

std::string App::format_number(long value) {
  char digits[32];
  std::snprintf(digits, sizeof digits, "%ld", value < 0 ? -value : value);
  std::string raw = digits;
  std::string out;
  const int length = static_cast<int>(raw.size());
  for (int i = 0; i < length; ++i) {
    if (i > 0 && (length - i) % 3 == 0) out.push_back(',');
    out.push_back(raw[static_cast<size_t>(i)]);
  }
  return value < 0 ? "-" + out : out;
}

// ---------------------------------------------------------------- drawing

void App::build_batches(double now) {
  scene_.clear();
  panels_.clear();
  preview_.clear();
  text_.clear();

  const float cw = static_cast<float>(tetris::W) / static_cast<float>(cols_);
  const float ch = static_cast<float>(tetris::H) / static_cast<float>(tetris::ROWS);
  const float gap = std::min(2.0f, std::max(0.4f, std::min(cw, ch) * 0.018f));
  const double progress = fall_progress(now);
  const bool falling = !offsets_.empty() && fall_start_ >= 0;

  float flash = 0;
  if (phase_ == Phase::Flashing) {
    const double t = std::min(1.0, std::max(0.0, (now - phase_start_) / kFlashSeconds));
    const double local = (t - 0.03) / 0.12;
    const double c = std::cos(2.0 * kPi * local);
    flash = c > 0 ? static_cast<float>(std::pow(c, 6.0)) : 0.0f;
  }
  const tetris::Rgb white{255, 255, 255};

  for (int y = 0; y < tetris::ROWS; ++y) {
    const bool clearing =
        phase_ == Phase::Flashing &&
        std::find(clearing_rows_.begin(), clearing_rows_.end(), y) != clearing_rows_.end();
    for (int x = 0; x < cols_; ++x) {
      const char letter = board_.letters[y][x];
      if (letter == 0) continue;
      tetris::Rgb colour = settings_.clock_colour;
      if (letter != tetris::FIXED) {
        const int index = tetris::piece_index(letter);
        colour = colours_[index < 0 ? 0 : index];
      }
      if (clearing && flash > 0) colour = mix(colour, white, flash);
      float offset = 0;
      if (falling) offset = offsets_[static_cast<size_t>(y) * cols_ + x] * (1.0 - progress);
      add_block(scene_, x * cw + gap, (y + offset) * ch + gap, cw - 2 * gap, ch - 2 * gap, colour,
                1.0f, 0.0f);
    }
  }

  if (phase_ == Phase::Think || phase_ == Phase::Moving || phase_ == Phase::Dropping) {
    const int index = tetris::piece_index(letter_);
    const tetris::Rgb piece_colour = colours_[index < 0 ? 0 : index];
    if (settings_.ghost) {
      for (const tetris::Cell& cell : shape_) {
        add_block(scene_, (target_x_ + cell.x) * cw + gap, (target_y_ + cell.y) * ch + gap,
                  cw - 2 * gap, ch - 2 * gap, piece_colour, kGhostAlpha, 0.0f);
      }
    }
    double vx = spawn_x_;
    double vy = 0;
    if (phase_ == Phase::Moving) {
      const double t = std::min(1.0, std::max(0.0, (now - phase_start_) / move_seconds_));
      vx = spawn_x_ + (target_x_ - spawn_x_) * static_cast<double>(smooth(t));
    } else if (phase_ == Phase::Dropping) {
      vx = target_x_;
      const double t = std::min(1.0, std::max(0.0, (now - phase_start_) / drop_seconds_));
      vy = target_y_ * t * t;
    }
    for (const tetris::Cell& cell : shape_) {
      add_block(scene_, static_cast<float>(vx + cell.x) * cw + gap,
                static_cast<float>(vy + cell.y) * ch + gap, cw - 2 * gap, ch - 2 * gap,
                piece_colour, 1.0f, 0.0f);
    }
  }

  const float hud_alpha = settings_.hud_opacity / 100.0f;
  if (settings_.show_hud) {
    add_block(panels_, 28, 24, 420, 286, tetris::Rgb{0, 0, 0}, hud_alpha, 1.0f);
  }
  const bool text_clock = settings_.show_clock && settings_.clock_style == 0;
  if (text_clock && !settings_.show_hud) {
    add_block(panels_, 28, 24, 380, 92, tetris::Rgb{0, 0, 0}, hud_alpha, 1.0f);
  }
  if (settings_.show_next) {
    add_block(panels_, 1562, 24, 330, 220, tetris::Rgb{0, 0, 0}, hud_alpha, 1.0f);
  }
  if (phase_ == Phase::GameOver) {
    add_block(panels_, 700, 460, 520, 150, tetris::Rgb{0, 0, 0}, 0.8f, 1.0f);
  }

  if (settings_.show_next) {
    const char next_letter = game_.next;
    const int next_index = tetris::piece_index(next_letter);
    const tetris::Rgb next_colour = colours_[next_index < 0 ? 0 : next_index];
    const tetris::Shape& shape = tetris::piece(next_letter).shapes[0];
    const float pw = cw * 0.58f;
    const float ph = ch * 0.58f;
    const float width = tetris::shape_width(shape) * pw;
    const float height = tetris::shape_height(shape) * ph;
    const float left = 1562.0f + (330.0f - width) * 0.5f;
    const float top = 24.0f + 62.0f + (220.0f - 62.0f - height) * 0.5f;
    for (const tetris::Cell& cell : shape) {
      add_block(preview_, left + cell.x * pw + gap * 0.58f, top + cell.y * ph + gap * 0.58f,
                pw - 2 * gap * 0.58f, ph - 2 * gap * 0.58f, next_colour, 1.0f, 0.0f);
    }
  }

  int seconds = static_cast<int>(clock_seconds_);
  if (seconds < 0) seconds = 0;
  const int hour = (seconds / 3600) % 24;
  const int minute = (seconds / 60) % 60;
  const int second = seconds % 60;

  if (text_clock) {
    const std::string clock = tetris::clock_text(hour, minute, second, settings_.clock_24h,
                                                 settings_.clock_seconds);
    float scale = 6.0f;
    while (scale > 3.0f && text_width(clock, scale) > 356.0f) scale -= 1.0f;
    const float top = 38.0f + (64.0f - 7.0f * scale) * 0.5f;
    add_text(text_, clock, 52.0f, top, scale, kClockText, 1.0f);
  }

  if (settings_.show_hud) {
    add_text(text_, "SCORE", 52.0f, 118.0f + (28.0f - 14.0f) * 0.5f, 2.0f, kCaption, 1.0f);
    add_text(text_, format_number(game_.score), 52.0f, 142.0f + (46.0f - 28.0f) * 0.5f, 4.0f,
             kValue, 1.0f);
    add_text(text_, "LINES", 52.0f, 198.0f + (26.0f - 14.0f) * 0.5f, 2.0f, kCaption, 1.0f);
    add_text(text_, std::to_string(game_.lines), 52.0f,
             220.0f + (36.0f - 21.0f) * 0.5f, 3.0f, kValue, 1.0f);
    add_text(text_, "LEVEL", 172.0f, 198.0f + (26.0f - 14.0f) * 0.5f, 2.0f, kCaption, 1.0f);
    add_text(text_, std::to_string(game_.level), 172.0f,
             220.0f + (36.0f - 21.0f) * 0.5f, 3.0f, kValue, 1.0f);
    add_text(text_, "BEST", 286.0f, 198.0f + (26.0f - 14.0f) * 0.5f, 2.0f, kCaption, 1.0f);
    add_text(text_, format_number(best_), 286.0f, 220.0f + (36.0f - 21.0f) * 0.5f, 3.0f, kValue,
             1.0f);
  }
  if (settings_.show_next) {
    add_text(text_, "NEXT", 1562.0f + 24.0f, 24.0f + 18.0f + (28.0f - 14.0f) * 0.5f, 2.0f,
             kCaption, 1.0f);
  }
  if (phase_ == Phase::GameOver) {
    const std::string label = "GAME OVER";
    const float scale = 6.0f;
    const float x = 700.0f + (520.0f - text_width(label, scale)) * 0.5f;
    const float top = 456.0f + (150.0f - 7.0f * scale) * 0.5f;
    add_text(text_, label, x, top, scale, kGameOverText, 1.0f);
  }
}

void App::draw_blocks(const std::vector<BlockVertex>& batch) {
  if (batch.empty()) return;
  glBindBuffer(GL_ARRAY_BUFFER, buffer_block_);
  glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(batch.size() * sizeof(BlockVertex)),
               batch.data(), GL_STREAM_DRAW);
  glEnableVertexAttribArray(0);
  glEnableVertexAttribArray(1);
  glEnableVertexAttribArray(2);
  glEnableVertexAttribArray(3);
  glEnableVertexAttribArray(4);
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, sizeof(BlockVertex),
                        reinterpret_cast<const void*>(offsetof(BlockVertex, x)));
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof(BlockVertex),
                        reinterpret_cast<const void*>(offsetof(BlockVertex, w)));
  glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, sizeof(BlockVertex),
                        reinterpret_cast<const void*>(offsetof(BlockVertex, u)));
  glVertexAttribPointer(3, 4, GL_FLOAT, GL_FALSE, sizeof(BlockVertex),
                        reinterpret_cast<const void*>(offsetof(BlockVertex, r)));
  glVertexAttribPointer(4, 1, GL_FLOAT, GL_FALSE, sizeof(BlockVertex),
                        reinterpret_cast<const void*>(offsetof(BlockVertex, mode)));
  glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(batch.size()));
  for (int i = 0; i < 5; ++i) glDisableVertexAttribArray(i);
}

void App::draw_text() {
  if (text_.empty()) return;
  glBindBuffer(GL_ARRAY_BUFFER, buffer_text_);
  glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(text_.size() * sizeof(TextVertex)),
               text_.data(), GL_STREAM_DRAW);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, atlas_);
  glEnableVertexAttribArray(0);
  glEnableVertexAttribArray(1);
  glEnableVertexAttribArray(2);
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, sizeof(TextVertex),
                        reinterpret_cast<const void*>(offsetof(TextVertex, x)));
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof(TextVertex),
                        reinterpret_cast<const void*>(offsetof(TextVertex, u)));
  glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, sizeof(TextVertex),
                        reinterpret_cast<const void*>(offsetof(TextVertex, r)));
  glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(text_.size()));
  for (int i = 0; i < 3; ++i) glDisableVertexAttribArray(i);
}

void App::draw(int fb_width, int fb_height) {
  if (fb_width <= 0 || fb_height <= 0) return;
  glu::SavedState saved;
  glViewport(0, 0, fb_width, fb_height);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glDisable(GL_SCISSOR_TEST);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
  glClearColor(settings_.background.r / 255.0f, settings_.background.g / 255.0f,
               settings_.background.b / 255.0f, 1.0f);
  glClear(GL_COLOR_BUFFER_BIT);

#ifdef SANDCLOCK_CORE
  glBindVertexArray(vao_);
#endif

  glUseProgram(program_background_);
  if (background_colour_ >= 0) {
    glUniform3f(background_colour_, settings_.background.r / 255.0f,
                settings_.background.g / 255.0f, settings_.background.b / 255.0f);
  }
  if (background_grid_ >= 0) glUniform1f(background_grid_, settings_.show_grid ? 1.0f : 0.0f);
  if (background_vignette_ >= 0) glUniform1f(background_vignette_, kVignette);
  if (background_screen_ >= 0) glUniform2f(background_screen_, 1920.0f, 1080.0f);
  glBindBuffer(GL_ARRAY_BUFFER, buffer_background_);
  glEnableVertexAttribArray(0);
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, reinterpret_cast<const void*>(0));
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
  glDisableVertexAttribArray(0);

  glUseProgram(program_block_);
  if (block_screen_ >= 0) glUniform2f(block_screen_, 1920.0f, 1080.0f);
  draw_blocks(scene_);
  draw_blocks(panels_);
  draw_blocks(preview_);

  if (!text_.empty()) {
    glUseProgram(program_text_);
    if (text_screen_ >= 0) glUniform2f(text_screen_, 1920.0f, 1080.0f);
    if (text_atlas_ >= 0) glUniform1i(text_atlas_, 0);
    draw_text();
  }

#ifdef SANDCLOCK_CORE
  glBindVertexArray(0);
#endif
}

void App::render(double now, double clock_seconds, int fb_width, int fb_height) {
  clock_seconds_ = clock_seconds;
  update(now);
  build_batches(now);
  draw(fb_width, fb_height);
}

}  // namespace tetrisgl
}  // namespace sandclock

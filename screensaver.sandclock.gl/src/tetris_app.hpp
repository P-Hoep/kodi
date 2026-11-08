// Tetris AI (OpenGL): the GL renderer around the ported engine. Everything is drawn as
// antialiased rounded tiles and a small bitmap font in a handful of draw calls, and the active
// piece moves continuously (sub-pixel, eased) instead of jumping cell to cell, so the motion is
// as smooth as the display. Line clears flash and collapse, and pieces stranded by a clock
// change slide down into place.
#pragma once

#include <array>
#include <random>
#include <string>
#include <vector>

#include "tetris.hpp"

namespace sandclock {
namespace tetrisgl {

class App {
 public:
  App();
  ~App();

  bool init(const tetris::Settings& settings, unsigned seed, std::string* error);
  void release();

  // now: seconds since the add-on started; clock_seconds: local time of day.
  void render(double now, double clock_seconds, int fb_width, int fb_height);

  int columns() const { return cols_; }
  int rows() const { return tetris::ROWS; }
  long pieces() const { return game_.pieces; }
  const tetris::Settings& settings() const { return settings_; }

 private:
  enum class Phase { Think, Moving, Dropping, Flashing, Falling, GameOver };

  struct BlockVertex {
    float x, y, w, h;
    float u, v;
    float r, g, b, a;
    float mode;
  };
  struct TextVertex {
    float x, y;
    float u, v;
    float r, g, b, a;
  };

  bool make_program(const char* vertex, const char* fragment, const char* const* attributes,
                    int attribute_count, unsigned* program, std::string* error);
  void build_atlas();
  void update(double now);
  void spawn(double now);
  void start_moving(double now);
  void start_dropping(double now);
  void lock_piece(double now);
  void finish_flash(double now);
  void restart(double now);
  void maybe_update_clock(double now);
  int start_fall_animation(const std::vector<std::vector<char>>& before,
                           const std::vector<int>& removed_rows, double now);
  double fall_progress(double now) const;

  void build_batches(double now);
  void draw(int fb_width, int fb_height);
  void draw_blocks(const std::vector<BlockVertex>& batch);
  void draw_text();

  static void add_block(std::vector<BlockVertex>& out, float x, float y, float w, float h,
                        const tetris::Rgb& colour, float alpha, float mode);
  static void add_text(std::vector<TextVertex>& out, const std::string& text, float x, float y,
                       float scale, const tetris::Rgb& colour, float alpha);
  static float text_width(const std::string& text, float scale);
  static std::string format_number(long value);

  tetris::Settings settings_;
  std::mt19937 rng_;
  tetris::Board board_;
  tetris::Game game_;
  std::array<tetris::Rgb, 7> colours_{};
  int cols_ = 20;
  long best_ = 0;

  double now_ = -1;
  double clock_seconds_ = 0;
  bool started_ = false;
  int clock_key_ = -1;

  Phase phase_ = Phase::Think;
  double phase_start_ = 0;
  char letter_ = 'I';
  int rotation_ = 0;
  tetris::Shape shape_;
  int spawn_x_ = 0;
  int target_x_ = 0;
  int target_y_ = 0;
  double vis_x_ = 0;
  double vis_y_ = 0;
  int from_x_ = 0;
  double think_seconds_ = 0.12;
  double move_seconds_ = 0.045;
  double drop_seconds_ = 0.020;
  std::vector<int> clearing_rows_;

  std::vector<float> offsets_;  // row units, negative = drawn above the final cell
  double fall_start_ = -1;
  double fall_duration_ = 0.20;

  unsigned program_background_ = 0;
  unsigned program_block_ = 0;
  unsigned program_text_ = 0;
  unsigned buffer_background_ = 0;
  unsigned buffer_block_ = 0;
  unsigned buffer_text_ = 0;
  unsigned atlas_ = 0;
#ifdef SANDCLOCK_CORE
  unsigned vao_ = 0;
#endif

  int background_screen_ = -1;
  int background_cell_ = -1;
  int background_colour_ = -1;
  int background_grid_ = -1;
  int background_vignette_ = -1;
  int block_screen_ = -1;
  int text_screen_ = -1;
  int text_atlas_ = -1;

  std::vector<BlockVertex> scene_;
  std::vector<BlockVertex> panels_;
  std::vector<BlockVertex> preview_;
  std::vector<TextVertex> text_;
};

}  // namespace tetrisgl
}  // namespace sandclock

// Test window for the Tetris AI (OpenGL) screensaver, no Kodi involved.
//   tetris_glfw [--skill N] [--speed N] [--start N] [--no-progressive] [--no-ghost] [--no-next]
//               [--scheme N] [--block N] [--no-grid] [--no-hud] [--hud-opacity N] [--bg HEX]
//               [--custom P=HEX] [--no-clock] [--clock-style N] [--clock-seconds] [--24h]
//               [--floating] [--clock-colour HEX] [--time HH:MM:SS] [--seed N]
//               [--fullscreen] [--shot out.ppm --shot-after SECONDS]
#include <GLFW/glfw3.h>

#include <cstdio>
#include <cstring>
#include <ctime>
#include <string>
#include <vector>

#include "gl_include.hpp"
#include "tetris_app.hpp"

using sandclock::tetrisgl::App;
using tetris::Settings;

static bool save_ppm(const std::string& path, int w, int h) {
  std::vector<unsigned char> px(static_cast<size_t>(w) * h * 3);
  glPixelStorei(GL_PACK_ALIGNMENT, 1);
  glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, px.data());
  FILE* f = std::fopen(path.c_str(), "wb");
  if (!f) return false;
  std::fprintf(f, "P6\n%d %d\n255\n", w, h);
  for (int y = h - 1; y >= 0; --y) {
    std::fwrite(&px[static_cast<size_t>(y) * w * 3], 1, static_cast<size_t>(w) * 3, f);
  }
  std::fclose(f);
  return true;
}

int main(int argc, char** argv) {
  Settings s;
  std::string shot;
  double shot_after = 8;
  bool fullscreen = false;
  bool fixed_time = false;
  double time_offset = 43200;  // 12:00:00
  unsigned seed = 1;
  for (int i = 1; i < argc; ++i) {
    auto is = [&](const char* a) { return !std::strcmp(argv[i], a); };
    auto next = [&] { return i + 1 < argc ? argv[++i] : (char*)"0"; };
    if (is("--skill")) s.skill = std::atoi(next());
    else if (is("--speed")) s.speed = std::atoi(next());
    else if (is("--start")) s.start_level = std::atoi(next());
    else if (is("--no-progressive")) s.progressive = false;
    else if (is("--no-ghost")) s.ghost = false;
    else if (is("--no-next")) s.show_next = false;
    else if (is("--scheme")) s.scheme = std::atoi(next());
    else if (is("--block")) s.block_size = std::atoi(next());
    else if (is("--no-grid")) s.show_grid = false;
    else if (is("--no-hud")) s.show_hud = false;
    else if (is("--hud-opacity")) s.hud_opacity = std::atoi(next());
    else if (is("--bg")) tetris::parse_colour(next(), &s.background);
    else if (is("--no-clock")) s.show_clock = false;
    else if (is("--clock-style")) s.clock_style = std::atoi(next());
    else if (is("--clock-seconds")) s.clock_seconds = true;
    else if (is("--24h")) s.clock_24h = true;
    else if (is("--floating")) s.clock_position = 1;
    else if (is("--clock-colour")) tetris::parse_colour(next(), &s.clock_colour);
    else if (is("--custom")) {
      const char* value = next();
      if (value[1] == '=') {
        const int index = tetris::piece_index(value[0]);
        if (index >= 0) tetris::parse_colour(value + 2, &s.custom[index]);
      }
    } else if (is("--time")) {
      int h = 12, m = 0, sec = 0;
      std::sscanf(next(), "%d:%d:%d", &h, &m, &sec);
      time_offset = h * 3600 + m * 60 + sec;
      fixed_time = true;
    } else if (is("--seed")) {
      seed = static_cast<unsigned>(std::strtoul(next(), nullptr, 10));
    } else if (is("--fullscreen")) {
      fullscreen = true;
    } else if (is("--shot")) {
      shot = next();
    } else if (is("--shot-after")) {
      shot_after = std::atof(next());
    }
  }
  s.sanitise();

  if (!glfwInit()) return 1;
#ifdef SANDCLOCK_CORE  // the profile Kodi gets on macOS
  glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
  glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 2);
  glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
  glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GLFW_TRUE);
#endif
  GLFWmonitor* mon = fullscreen ? glfwGetPrimaryMonitor() : nullptr;
  GLFWwindow* win = glfwCreateWindow(1280, 720, "Tetris AI (OpenGL)", mon, nullptr);
  if (!win) {
    glfwTerminate();
    return 1;
  }
  glfwMakeContextCurrent(win);
  glfwSwapInterval(1);
  std::printf("GL %s | %s\n", glGetString(GL_VERSION), glGetString(GL_RENDERER));

  App app;
  std::string err;
  if (!app.init(s, seed, &err)) {
    std::fprintf(stderr, "init: %s\n", err.c_str());
    glfwTerminate();
    return 1;
  }
  if (!err.empty()) std::fprintf(stderr, "note: %s\n", err.c_str());
  auto clock_now = [&] {
    if (fixed_time) return time_offset + glfwGetTime();
    std::time_t tt = std::time(nullptr);
    std::tm lt;
    localtime_r(&tt, &lt);
    return lt.tm_hour * 3600.0 + lt.tm_min * 60.0 + lt.tm_sec;
  };
  std::printf("%d x %d board, %d px blocks\n", app.columns(), app.rows(),
              app.settings().block_size);

  double next_status = 5, last_status = 0;
  long frames = 0, frames_at = 0, pieces_at = 0;
  while (!glfwWindowShouldClose(win)) {
    glfwPollEvents();
    if (glfwGetKey(win, GLFW_KEY_ESCAPE) == GLFW_PRESS) break;
    const double now = glfwGetTime();
    int fw, fh;
    glfwGetFramebufferSize(win, &fw, &fh);
    glViewport(0, 0, fw, fh);
    app.render(now, clock_now(), fw, fh);
    if (!shot.empty() && now >= shot_after) {
      std::printf("shot %s %s\n", shot.c_str(), save_ppm(shot, fw, fh) ? "ok" : "FAILED");
      break;
    }
    glfwSwapBuffers(win);
    ++frames;
    if (now >= next_status) {
      const double dt = now - last_status;
      std::printf("t=%.0fs %.0f fps, %.1f pieces/s, %ld pieces\n", now,
                  (frames - frames_at) / dt, (app.pieces() - pieces_at) / dt, app.pieces());
      frames_at = frames;
      pieces_at = app.pieces();
      last_status = now;
      next_status += 10;
    }
  }
  app.release();
  glfwTerminate();
  return 0;
}

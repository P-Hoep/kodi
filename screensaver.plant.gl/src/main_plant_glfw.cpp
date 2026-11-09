// Test window for the Growing Plant (OpenGL) screensaver, no Kodi involved.
//   plant_glfw [--preset N] [--seed N] [--quality N] [--leaf-density N]
//              [--growth-speed N] [--hold N] [--motion N] [--camera-speed N]
//              [--framing N] [--background N] [--no-particles] [--no-ground] [--dim N]
//              [--width N] [--height-px N] [--fullscreen]
//              [--start-at SECONDS] [--run-for SECONDS]
//              [--shot out.ppm --shot-after SECONDS]
#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>
#include <vector>

#include "gl_include.hpp"
#include "plant_app.hpp"

using plantgl::App;
using plantgl::Settings;

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
  double shot_after = 8.0;
  double start_at = 0.0;
  double run_for = -1.0;
  bool fullscreen = false;
  int width = 1280, height = 720;
  unsigned seed = static_cast<unsigned>(std::time(nullptr));
  for (int i = 1; i < argc; ++i) {
    auto is = [&](const char* a) { return !std::strcmp(argv[i], a); };
    auto next = [&] { return i + 1 < argc ? argv[++i] : (char*)"0"; };
    if (is("--preset")) s.preset = std::atoi(next());
    else if (is("--seed")) s.seed = std::atoi(next());
    else if (is("--quality")) s.quality = std::atoi(next());
    else if (is("--leaf-density")) s.leaf_density = std::atoi(next());
    else if (is("--growth-speed")) s.growth_speed = std::atoi(next());
    else if (is("--hold")) s.hold_seconds = std::atoi(next());
    else if (is("--motion")) s.motion = std::atoi(next());
    else if (is("--camera-speed")) s.camera_speed = std::atoi(next());
    else if (is("--framing")) s.framing = std::atoi(next());
    else if (is("--background")) s.background = std::atoi(next());
    else if (is("--no-particles")) s.particles = false;
    else if (is("--no-ground")) s.ground = false;
    else if (is("--dim")) s.dim = std::atoi(next());
    else if (is("--fullscreen")) fullscreen = true;
    else if (is("--width")) width = std::atoi(next());
    else if (is("--height-px")) height = std::atoi(next());
    else if (is("--start-at")) start_at = std::atof(next());
    else if (is("--run-for")) run_for = std::atof(next());
    else if (is("--shot")) shot = next();
    else if (is("--shot-after")) shot_after = std::atof(next());
  }
  s.sanitise();

  if (!glfwInit()) return 1;
#ifdef PLANT_CORE  // the profile Kodi gets on macOS
  glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
  glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 2);
  glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
  glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GLFW_TRUE);
#endif
  GLFWmonitor* mon = fullscreen ? glfwGetPrimaryMonitor() : nullptr;
  GLFWwindow* win = glfwCreateWindow(width, height, "Growing Plant (OpenGL)", mon, nullptr);
  if (!win) {
    glfwTerminate();
    return 1;
  }
  glfwMakeContextCurrent(win);
  glfwSwapInterval(1);
  std::printf("GL %s | %s\n",
              reinterpret_cast<const char*>(glGetString(GL_VERSION)),
              reinterpret_cast<const char*>(glGetString(GL_RENDERER)));

  App app;
  std::string err;
  if (!app.init(s, seed, &err)) {
    std::fprintf(stderr, "init: %s\n", err.c_str());
    glfwTerminate();
    return 1;
  }
  std::printf("seed %u, preset %d, background %d, motion %d, %d vertices, %d triangles, "
              "%d batches, %d leaves, height %.2f\n",
              app.seed(), app.preset_index(), app.background_index(), app.motion_index(),
              app.vertex_count(), app.triangle_count(), app.batch_count(), app.leaf_clusters(),
              static_cast<double>(app.plant_height()));

  const double clock_start = glfwGetTime();
  double next_status = 3.0;
  double last_status = 0.0;
  long frames = 0;
  long frames_at = 0;
  bool shot_done = false;
  while (!glfwWindowShouldClose(win)) {
    glfwPollEvents();
    if (glfwGetKey(win, GLFW_KEY_ESCAPE) == GLFW_PRESS) break;
    const double base = glfwGetTime();
    const double now = base + start_at;
    int fw, fh;
    glfwGetFramebufferSize(win, &fw, &fh);
    glViewport(0, 0, fw, fh);
    app.render(now, fw, fh);

    if (!shot.empty() && !shot_done && base >= shot_after) {
      std::printf("shot %s %s (growth %d%%, preset %d, sky %d)\n", shot.c_str(),
                  save_ppm(shot, fw, fh) ? "ok" : "FAILED",
                  static_cast<int>(app.growth01() * 100.0), app.preset_index(),
                  app.background_index());
      shot_done = true;
      break;
    }

    glfwSwapBuffers(win);
    ++frames;

    if (run_for >= 0.0 && base - clock_start >= run_for) break;
    if (base >= next_status) {
      const double dt = base - last_status;
      std::printf("t=%.0fs %.0f fps, preset %d, sky %d, motion %d, growth %d%%, %d vertices, "
                  "%d batches\n",
                  base, static_cast<double>(frames - frames_at) / std::max(0.001, dt),
                  app.preset_index(), app.background_index(), app.motion_index(),
                  static_cast<int>(app.growth01() * 100.0), app.vertex_count(),
                  app.batch_count());
      frames_at = frames;
      last_status = base;
      next_status += 5.0;
    }
  }
  app.release();
  glfwTerminate();
  return 0;
}

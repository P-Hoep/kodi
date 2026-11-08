// Test window for the Endless World (OpenGL) screensaver, no Kodi involved.
//   infworld_glfw [--seed N] [--range N] [--detail N] [--trees N] [--mode N] [--speed N]
//                 [--height N] [--no-wander] [--no-water] [--dim N] [--draw-res N]
//                 [--no-adaptive] [--assets DIR] [--fullscreen]
//                 [--shot out.ppm --shot-after SECONDS]
#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "gl_include.hpp"
#include "infworld_app.hpp"

using sandclock::infworldgl::App;
using sandclock::infworld::Settings;

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
  std::string assets = "screensaver.infworld.gl/resources/textures";
  std::string shot;
  double shot_after = 8;
  bool fullscreen = false;
  int width = 1280, height = 720;
  unsigned seed = 1;
  for (int i = 1; i < argc; ++i) {
    auto is = [&](const char* a) { return !std::strcmp(argv[i], a); };
    auto next = [&] { return i + 1 < argc ? argv[++i] : (char*)"0"; };
    if (is("--seed")) s.seed = std::atoi(next());
    else if (is("--range")) s.range = std::atoi(next());
    else if (is("--detail")) s.detail = std::atoi(next());
    else if (is("--trees")) s.trees = std::atoi(next());
    else if (is("--mode")) s.mode = std::atoi(next());
    else if (is("--speed")) s.speed = std::atoi(next());
    else if (is("--height")) s.height = std::atoi(next());
    else if (is("--no-wander")) s.wander = false;
    else if (is("--no-water")) s.water = false;
    else if (is("--dim")) s.dim = std::atoi(next());
    else if (is("--draw-res")) s.draw_res = std::atoi(next());
    else if (is("--no-adaptive")) s.adaptive = false;
    else if (is("--assets")) assets = next();
    else if (is("--fullscreen")) fullscreen = true;
    else if (is("--width")) width = std::atoi(next());
    else if (is("--height-px")) height = std::atoi(next());
    else if (is("--shot")) shot = next();
    else if (is("--shot-after")) shot_after = std::atof(next());
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
  GLFWwindow* win =
      glfwCreateWindow(width, height, "Endless World (OpenGL)", mon, nullptr);
  if (!win) {
    glfwTerminate();
    return 1;
  }
  glfwMakeContextCurrent(win);
  glfwSwapInterval(1);
  std::printf("GL %s | %s\n", glGetString(GL_VERSION), glGetString(GL_RENDERER));

  App app;
  std::string err;
  if (!app.init(s, seed, assets, &err)) {
    std::fprintf(stderr, "init: %s\n", err.c_str());
    glfwTerminate();
    return 1;
  }
  std::printf("seed %u, range %d, detail %d, trees %d, assets %s\n", app.seed(),
              s.range, s.detail, s.trees, assets.c_str());

  double next_status = 2, last_status = 0;
  long frames = 0, frames_at = 0;
  while (!glfwWindowShouldClose(win)) {
    glfwPollEvents();
    if (glfwGetKey(win, GLFW_KEY_ESCAPE) == GLFW_PRESS) break;
    const double now = glfwGetTime();
    int fw, fh;
    glfwGetFramebufferSize(win, &fw, &fh);
    glViewport(0, 0, fw, fh);
    app.render(now, fw, fh);
    if (!shot.empty() && now >= shot_after) {
      std::printf("shot %s %s\n", shot.c_str(), save_ppm(shot, fw, fh) ? "ok" : "FAILED");
      break;
    }
    glfwSwapBuffers(win);
    ++frames;
    if (now >= next_status) {
      const double dt = now - last_status;
      std::printf("t=%.0fs %.0f fps, %d chunks, %d tree draws, quality %.2f, "
                  "camera %.0f %.0f %.0f, LOD %d/%d/%d/%d/%d\n", now,
                  (frames - frames_at) / dt, app.chunks_drawn(), app.trees_drawn(),
                  app.quality(), app.camera_position().x, app.camera_position().y,
                  app.camera_position().z, app.lod_drawn(0), app.lod_drawn(1), app.lod_drawn(2),
                  app.lod_drawn(3), app.lod_drawn(4));
      frames_at = frames;
      last_status = now;
      next_status += 5;
    }
  }
  app.release();
  glfwTerminate();
  return 0;
}

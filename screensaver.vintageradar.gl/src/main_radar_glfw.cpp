// Test window for Vintage Radar, no Kodi involved.
//   radar_glfw [--lat N --lon N --range N --units 0|1 --sweep N --refresh N]
//              [--theme 0-3 --quality 0-2 --max-contacts N --detail-seconds N]
//              [--label-detail 0-2] [--min-altitude 0-3] [--show-ground]
//              [--no-labels] [--no-history] [--no-panel] [--no-crt] [--dim N]
//              [--fixture path | --live | --no-fetch] [--select hex] [--page N] [--step N]
//              [--width N --height-px N] [--shot out.ppm --shot-after S] [--run-for S]
#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "gl_include.hpp"
#include "radar_app.hpp"

using radar::App;
using radar::FeedPump;
using radar::Settings;

static bool save_ppm(const std::string& path, int w, int h) {
  std::vector<unsigned char> px(static_cast<size_t>(w) * h * 3);
  glPixelStorei(GL_PACK_ALIGNMENT, 1);
  glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, px.data());
  FILE* f = std::fopen(path.c_str(), "wb");
  if (!f) return false;
  std::fprintf(f, "P6\n%d %d\n255\n", w, h);
  for (int y = h - 1; y >= 0; --y)
    std::fwrite(&px[static_cast<size_t>(y) * w * 3], 1, static_cast<size_t>(w) * 3, f);
  std::fclose(f);
  return true;
}

static App* g_app = nullptr;

static void on_click(GLFWwindow* win, int button, int action, int) {
  if (button != GLFW_MOUSE_BUTTON_LEFT || action != GLFW_PRESS || !g_app) return;
  double mx = 0, my = 0;
  glfwGetCursorPos(win, &mx, &my);
  int ww = 0, wh = 0, fw = 0, fh = 0;
  glfwGetWindowSize(win, &ww, &wh);
  glfwGetFramebufferSize(win, &fw, &fh);
  if (ww <= 0 || wh <= 0) return;
  const std::string hex =
      g_app->pick(mx * fw / ww, my * fh / wh, fw, fh);
  if (!hex.empty()) {
    g_app->select(hex);
    std::printf("select %s\n", hex.c_str());
  }
}

int main(int argc, char** argv) {
  Settings s;
  std::string shot, fixture = "tests/fixtures/adsblol.json", select;
  double shot_after = 3.0, run_for = -1.0;
  int width = 1600, height = 900;
  int page_arg = -1, step_arg = 0;
  bool live = false, no_fetch = false, fullscreen = false;
  std::string lat_s, lon_s;

  for (int i = 1; i < argc; ++i) {
    auto is = [&](const char* a) { return !std::strcmp(argv[i], a); };
    auto next = [&] { return i + 1 < argc ? argv[++i] : (char*)"0"; };
    if (is("--lat")) lat_s = next();
    else if (is("--lon")) lon_s = next();
    else if (is("--range")) s.range_km = std::atoi(next());
    else if (is("--units")) s.units = std::atoi(next());
    else if (is("--sweep")) s.sweep_seconds = std::atoi(next());
    else if (is("--refresh")) s.refresh_seconds = std::atoi(next());
    else if (is("--theme")) s.theme = std::atoi(next());
    else if (is("--quality")) s.quality = std::atoi(next());
    else if (is("--max-contacts")) s.max_contacts = std::atoi(next());
    else if (is("--detail-seconds")) s.detail_seconds = std::atoi(next());
    else if (is("--label-detail")) s.label_detail = std::atoi(next());
    else if (is("--min-altitude")) s.min_altitude = std::atoi(next());
    else if (is("--show-ground")) s.show_ground = true;
    else if (is("--no-labels")) s.show_labels = false;
    else if (is("--no-history")) s.show_history = false;
    else if (is("--no-panel")) s.show_panel = false;
    else if (is("--no-crt")) s.crt = false;
    else if (is("--dim")) s.dim = std::atoi(next());
    else if (is("--fixture")) fixture = next();
    else if (is("--live")) live = true;
    else if (is("--no-fetch")) no_fetch = true;
    else if (is("--select")) select = next();
    else if (is("--page")) page_arg = std::atoi(next());
    else if (is("--step")) step_arg = std::atoi(next());
    else if (is("--width")) width = std::atoi(next());
    else if (is("--height-px")) height = std::atoi(next());
    else if (is("--fullscreen")) fullscreen = true;
    else if (is("--shot")) shot = next();
    else if (is("--shot-after")) shot_after = std::atof(next());
    else if (is("--run-for")) run_for = std::atof(next());
  }
  if (!lat_s.empty()) s.lat = std::atof(lat_s.c_str());
  if (!lon_s.empty()) s.lon = std::atof(lon_s.c_str());
  s.sanitise();

  FeedPump::Fetch fetch;
  if (!no_fetch) {
    if (live) {
      fetch = [](const std::string& url, std::string* body, std::string* error) {
        const std::string cmd = "curl -sL --max-time 8 --connect-timeout 5 '" + url + "'";
        FILE* p = popen(cmd.c_str(), "r");
        if (!p) {
          *error = "curl unavailable";
          return false;
        }
        char buf[16384];
        body->clear();
        size_t n = 0;
        while ((n = std::fread(buf, 1, sizeof buf, p)) > 0) body->append(buf, n);
        const int rc = pclose(p);
        if (rc != 0 || body->empty()) {
          *error = "curl failed";
          return false;
        }
        return true;
      };
    } else {
      fetch = [fixture](const std::string&, std::string* body, std::string* error) {
        std::ifstream in(fixture, std::ios::binary);
        if (!in) {
          *error = "cannot open " + fixture;
          return false;
        }
        std::stringstream ss;
        ss << in.rdbuf();
        *body = ss.str();
        return !body->empty();
      };
    }
  }

  if (!glfwInit()) return 1;
#if defined(RADAR_CORE)
  glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
  glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 2);
  glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
  glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GLFW_TRUE);
#endif
  GLFWmonitor* mon = fullscreen ? glfwGetPrimaryMonitor() : nullptr;
  GLFWwindow* win = glfwCreateWindow(width, height, "Vintage Radar (OpenGL)", mon, nullptr);
  if (!win) {
    glfwTerminate();
    return 1;
  }
  glfwMakeContextCurrent(win);
  glfwSwapInterval(1);
  std::printf("GL %s | %s\n", reinterpret_cast<const char*>(glGetString(GL_VERSION)),
              reinterpret_cast<const char*>(glGetString(GL_RENDERER)));

  App app;
  std::string err;
  if (!app.init(s, "resources/media", fetch, &err)) {
    std::fprintf(stderr, "init: %s\n", err.c_str());
    glfwTerminate();
    return 1;
  }
  g_app = &app;
  glfwSetMouseButtonCallback(win, on_click);
  if (step_arg) app.step_spotlight(step_arg);
  if (page_arg >= 0) app.set_page(page_arg);
  if (!select.empty()) app.select(select);

  const double start = glfwGetTime();
  bool shot_done = false;
  double last_status = start;
  long frames = 0, frames_at = 0;
  while (!glfwWindowShouldClose(win)) {
    glfwPollEvents();
    if (glfwGetKey(win, GLFW_KEY_ESCAPE) == GLFW_PRESS) break;
    if (glfwGetKey(win, GLFW_KEY_RIGHT) == GLFW_PRESS) {
      app.step_spotlight(1);
      glfwWaitEventsTimeout(0.2);
    }
    if (glfwGetKey(win, GLFW_KEY_LEFT) == GLFW_PRESS) {
      app.step_spotlight(-1);
      glfwWaitEventsTimeout(0.2);
    }
    const double now = glfwGetTime() - start;
    int fw = 0, fh = 0;
    glfwGetFramebufferSize(win, &fw, &fh);
    app.render(now, fw, fh);

    if (!shot.empty() && !shot_done && now >= shot_after) {
      std::printf("shot %s %s\n", shot.c_str(), save_ppm(shot, fw, fh) ? "ok" : "FAILED");
      shot_done = true;
      break;
    }

    glfwSwapBuffers(win);
    ++frames;
    if (run_for >= 0.0 && now >= run_for) break;
    if (now - last_status >= 5.0) {
      std::printf("t=%.0fs %.0f fps, %d in range, spotlight %s, source %s\n", now,
                  static_cast<double>(frames - frames_at) / (now - last_status),
                  app.model().in_range_count(), app.model().spotlight_hex().c_str(),
                  app.model().feed_source().c_str());
      last_status = now;
      frames_at = frames;
    }
  }
  app.release();
  g_app = nullptr;
  glfwTerminate();
  return 0;
}

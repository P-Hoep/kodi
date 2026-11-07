// Test window for the engine + renderer, no Kodi involved.
//   sandclock_glfw --fonts <fonts.json> [--font N] [--weight N] [--grain N] [--look N]
//                  [--mode N] [--palette N] [--crumble N] [--slosh N] [--pile N] [--no-seconds] [--clock HH:MM:SS]
//                  [--fullscreen] [--shot out.ppm --shot-after SECONDS]
#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>
#include <vector>

#include "gl_include.hpp"
#ifdef SANDCLOCK_LIQUID
#include "liquid_renderer.hpp"
using Eng = sandclock::LiquidEngine;
using Ren = sandclock::LiquidRenderer;
#else
#include "engine.hpp"
#include "renderer.hpp"
using Eng = sandclock::Engine;
using Ren = sandclock::Renderer;
#endif

using namespace sandclock;

static bool save_ppm(const std::string& path, int w, int h) {
    std::vector<unsigned char> px((size_t)w * h * 3);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, px.data());
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    std::fprintf(f, "P6\n%d %d\n255\n", w, h);
    for (int y = h - 1; y >= 0; --y) std::fwrite(&px[(size_t)y * w * 3], 1, (size_t)w * 3, f);
    std::fclose(f);
    return true;
}

int main(int argc, char** argv) {
    Settings s;
    std::string fonts, shot;
    double shot_after = 8, clock_offset = 0;
    bool fullscreen = false, have_clock = false;
    for (int i = 1; i < argc; ++i) {
        auto is = [&](const char* a) { return !std::strcmp(argv[i], a); };
        auto next = [&] { return i + 1 < argc ? argv[++i] : (char*)"0"; };
        if (is("--fonts")) fonts = next();
        else if (is("--font")) s.font = std::atoi(next());
        else if (is("--weight")) s.weight = std::atoi(next());
        else if (is("--grain")) s.grain = std::atoi(next());
        else if (is("--look")) s.grain_look = std::atoi(next());
        else if (is("--mode")) s.colour_mode = std::atoi(next());
        else if (is("--palette")) s.palette = std::atoi(next());
        else if (is("--crumble")) s.crumble = std::atoi(next());
        else if (is("--slosh")) s.slosh = std::atoi(next());
        else if (is("--pile")) s.pile = std::atoi(next());
        else if (is("--no-seconds")) s.seconds = false;
        else if (is("--fullscreen")) fullscreen = true;
        else if (is("--shot")) shot = next();
        else if (is("--shot-after")) shot_after = std::atof(next());
        else if (is("--clock")) {
            int h = 0, m = 0, sec = 0;
            std::sscanf(next(), "%d:%d:%d", &h, &m, &sec);
            clock_offset = h * 3600 + m * 60 + sec;
            have_clock = true;
        }
    }
    if (fonts.empty()) {
        std::fprintf(stderr, "usage: %s --fonts path/to/fonts.json [options]\n", argv[0]);
        return 2;
    }

    Font font;
    try {
        font = Font::load(fonts, FONT_FOLDERS[s.font], s.weight);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "fonts: %s\n", e.what());
        return 1;
    }

    if (!glfwInit()) return 1;
#ifdef SANDCLOCK_CORE  // the profile Kodi gets on macOS
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 2);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GLFW_TRUE);
#endif
    GLFWmonitor* mon = fullscreen ? glfwGetPrimaryMonitor() : nullptr;
    GLFWwindow* win = glfwCreateWindow(1280, 720, "Sand Clock (OpenGL)", mon, nullptr);
    if (!win) { glfwTerminate(); return 1; }
    glfwMakeContextCurrent(win);
    glfwSwapInterval(1);
    if (fullscreen) glfwSetInputMode(win, GLFW_CURSOR, GLFW_CURSOR_HIDDEN);

    Ren renderer;
    std::string err;
    if (!renderer.init(&err)) {
        std::fprintf(stderr, "shader: %s\n", err.c_str());
        return 1;
    }
    std::printf("GL %s | %s\n", glGetString(GL_VERSION), glGetString(GL_RENDERER));

    Eng engine(s, font, (unsigned)std::time(nullptr));
    std::printf("grain %d px\n", engine.grain());

    auto wall_clock = [&] {
        if (have_clock) return clock_offset + glfwGetTime();
        std::time_t t = std::time(nullptr);
        std::tm lt;
        localtime_r(&t, &lt);
        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                      std::chrono::system_clock::now().time_since_epoch()).count() % 1000;
        return lt.tm_hour * 3600.0 + lt.tm_min * 60.0 + lt.tm_sec + ms / 1000.0;
    };

    double next_status = 5;
    long frames = 0, frames_at_status = 0;
    double last_status = 0;
    while (!glfwWindowShouldClose(win)) {
        glfwPollEvents();
        if (glfwGetKey(win, GLFW_KEY_ESCAPE) == GLFW_PRESS) break;
        double now = glfwGetTime();
        engine.update(now, wall_clock());
        int fw, fh;
        glfwGetFramebufferSize(win, &fw, &fh);
        renderer.draw(engine, now, fw, fh);
        if (!shot.empty() && now >= shot_after) {
            std::printf("shot %s %s\n", shot.c_str(), save_ppm(shot, fw, fh) ? "ok" : "FAILED");
            break;
        }
        glfwSwapBuffers(win);
        ++frames;
        if (now >= next_status) {
            next_status += 10;
            std::printf("t=%.0fs %.0f fps, pile %.0f px, sinking %.1f px/s, %zu grains\n", now,
                        (frames - frames_at_status) / (now - last_status), engine.pile_height_px(),
                        engine.sink_speed_now(), engine.pile().size());
            frames_at_status = frames;
            last_status = now;
        }
    }
    renderer.release();
    glfwTerminate();
    return 0;
}

// Test window for the Cellular Automata Lite screensaver, no Kodi involved.
//   automata_lite_glfw [--rule N] [--custom B3/S23] [--grid N] [--speed N] [--start N] [--density N]
//                      [--mode N] [--palette N] [--trail N] [--shape N] [--sparks N] [--no-wrap]
//                      [--draw N] [--view N] [--camera N] [--cam-speed N] [--zoom N] [--bg N]
//                      [--glow N] [--fx N] [--fonts fonts.json] [--clock-style N] [--clock-colour N]
//                      [--clock-size N] [--clock-font N] [--no-seconds] [--time HH:MM:SS]
//                      [--fullscreen] [--shot out.ppm --shot-after SECONDS]
//                      [--selftest] [--dump-shaders DIR]
// N for --rule, --grid, --speed, --start, --draw is the index in the settings lists (see
// tools/make_settings_automata_lite.py). --selftest checks the shader against the CPU reference.
#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>
#include <utility>
#include <vector>

#include "automata_lite_app.hpp"
#include "gl_include.hpp"

using namespace sandclock::automata;
using sandclock::automata::lite::App;

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

// The shader against the reference: random boards, several rules, with and without wrapping. The
// update shader is the part that must agree with the CPU; the draw pass is not compared.
static int selftest() {
    struct Case { const char* rule; bool wrap; };
    const Case cases[] = {{"B3/S23", true}, {"B3/S23", false}, {"B36/S23", true}, {"B3678/S34678", true},
                          {"B2/S", true}, {"B2/S/C3", true}, {"B2/S345/C4", false}, {"B234/S345/C24", true},
                          {"B3/S23/C8", true}, {"B1357/S1357", true}};
    int failures = 0;
    for (const Case& c : cases) {
        Settings s;
        s.grid = 0;                       // 160 x 90
        s.rule = RULE_COUNT;
        s.custom_rule = c.rule;
        s.wrap = c.wrap;
        s.sparks = 0;
        s.auto_restart = false;
        App app;
        std::string err;
        if (!app.init(s, 1, std::string(), &err)) { std::printf("init: %s\n", err.c_str()); return 1; }
        Rule rule = rule_for(s);
        std::mt19937 rng(11);
        std::vector<uint8_t> cpu((size_t)app.cols() * app.rows());
        for (auto& v : cpu) {
            unsigned r = rng() % 100;
            v = r < 35 ? 1 : (rule.states > 2 && r < 50 ? (uint8_t)(2 + rng() % (rule.states - 2)) : 0);
        }
        app.upload_state(cpu);
        std::vector<uint8_t> next;
        const int gens = 25;
        for (int g = 0; g < gens; ++g) { step_cpu(cpu, next, app.cols(), app.rows(), rule, c.wrap); cpu = next; }
        app.step(gens);
        std::vector<uint8_t> gpu;
        app.read_state(&gpu);
        size_t bad = 0;
        for (size_t i = 0; i < cpu.size(); ++i) bad += cpu[i] != gpu[i];
        std::printf("%-16s wrap=%d  %zu cells, %zu differ after %d generations  %s\n", c.rule, c.wrap, cpu.size(), bad,
                    gens, bad ? "FAIL" : "ok");
        failures += bad != 0;

        // measure(): live board reads as alive, an emptied one does not.
        bool alive = app.measure().any_alive;
        app.upload_state(std::vector<uint8_t>(cpu.size(), 0));
        bool dead = !app.measure().any_alive;
        if (!alive || !dead) { std::printf("  measure(): alive=%d dead=%d  FAIL\n", alive, dead); ++failures; }
    }
    std::printf(failures ? "%d FAILED\n" : "selftest passed\n", failures);
    return failures ? 1 : 0;
}

int main(int argc, char** argv) {
    Settings s;
    std::string shot;
    std::string fonts = "../screensaver.sandclock/resources/media/fonts/fonts.json";
    double shot_after = 8;
    bool fullscreen = false, test = false;
    bool fixed_time = false;
    double time_offset = 0;
    std::string dump_shaders;
    for (int i = 1; i < argc; ++i) {
        auto is = [&](const char* a) { return !std::strcmp(argv[i], a); };
        auto next = [&] { return i + 1 < argc ? argv[++i] : (char*)"0"; };
        if (is("--rule")) s.rule = std::atoi(next());
        else if (is("--custom")) { s.rule = RULE_COUNT; s.custom_rule = next(); }
        else if (is("--grid")) s.grid = std::atoi(next());
        else if (is("--speed")) s.speed = std::atoi(next());
        else if (is("--start")) s.start = std::atoi(next());
        else if (is("--density")) s.density = std::atoi(next());
        else if (is("--mode")) s.colour_mode = std::atoi(next());
        else if (is("--palette")) s.palette = std::atoi(next());
        else if (is("--trail")) s.trail = std::atoi(next());
        else if (is("--shape")) s.shape = std::atoi(next());
        else if (is("--sparks")) s.sparks = std::atoi(next());
        else if (is("--no-wrap")) s.wrap = false;
        else if (is("--draw")) s.draw = std::atoi(next());
        else if (is("--fullscreen")) fullscreen = true;
        else if (is("--shot")) shot = next();
        else if (is("--shot-after")) shot_after = std::atof(next());
        else if (is("--selftest")) test = true;
        else if (is("--view")) s.view = std::atoi(next());
        else if (is("--camera")) s.camera = std::atoi(next());
        else if (is("--cam-speed")) s.camera_speed = std::atoi(next());
        else if (is("--zoom")) s.zoom = std::atoi(next());
        else if (is("--bg")) s.background_style = std::atoi(next());
        else if (is("--glow")) s.glow = std::atoi(next());
        else if (is("--fx")) s.screen_fx = std::atoi(next());
        else if (is("--fonts")) fonts = next();
        else if (is("--clock-style")) s.clock = std::atoi(next());
        else if (is("--clock-colour")) s.clock_colour_mode = std::atoi(next());
        else if (is("--clock-size")) s.clock_size = std::atoi(next());
        else if (is("--clock-font")) s.clock_font = std::atoi(next());
        else if (is("--no-seconds")) s.seconds = false;
        else if (is("--time")) {
            int h = 0, m = 0, sec = 0;
            std::sscanf(next(), "%d:%d:%d", &h, &m, &sec);
            time_offset = h * 3600 + m * 60 + sec;
            fixed_time = true;
        }
        else if (is("--dump-shaders")) dump_shaders = next();
    }

    if (!dump_shaders.empty()) {
        // No GL needed: the sources are built from the settings alone.
        std::string update, draw, present, clock;
        App::shader_sources(s, &update, &draw, &present, &clock);
        std::vector<std::pair<const char*, const std::string*>> files = {
            {"update.frag", &update}, {"draw.frag", &draw}, {"present.frag", &present}};
        if (!clock.empty()) files.push_back({"clock.frag", &clock});
        for (const auto& f : files) {
            std::string path = dump_shaders + "/" + f.first;
            std::FILE* out = std::fopen(path.c_str(), "wb");
            if (!out) { std::fprintf(stderr, "cannot write %s\n", path.c_str()); return 1; }
            std::fwrite(f.second->data(), 1, f.second->size(), out);
            std::fclose(out);
            std::printf("%s ", f.first);
        }
        std::printf("written to %s\n", dump_shaders.c_str());
        return 0;
    }

    if (!glfwInit()) return 1;
#ifdef SANDCLOCK_CORE  // the profile Kodi gets on macOS
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 2);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GLFW_TRUE);
#endif
    GLFWmonitor* mon = fullscreen ? glfwGetPrimaryMonitor() : nullptr;
    GLFWwindow* win = glfwCreateWindow(1280, 720, "Cellular Automata Lite (OpenGL)", mon, nullptr);
    if (!win) { glfwTerminate(); return 1; }
    glfwMakeContextCurrent(win);
    glfwSwapInterval(1);
    std::printf("GL %s | %s\n", glGetString(GL_VERSION), glGetString(GL_RENDERER));
    if (test) { int rc = selftest(); glfwTerminate(); return rc; }
    if (fullscreen) glfwSetInputMode(win, GLFW_CURSOR, GLFW_CURSOR_HIDDEN);

    App app;
    std::string err;
    if (!app.init(s, (unsigned)std::time(nullptr), fonts, &err)) {
        std::fprintf(stderr, "init: %s\n", err.c_str());
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
    std::printf("%d x %d cells (%.1f million)\n", app.cols(), app.rows(), app.cols() * (double)app.rows() / 1e6);

    double next_status = 5, last_status = 0;
    long frames = 0, frames_at = 0, gens_at = 0;
    while (!glfwWindowShouldClose(win)) {
        glfwPollEvents();
        if (glfwGetKey(win, GLFW_KEY_ESCAPE) == GLFW_PRESS) break;
        double now = glfwGetTime();
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
            double dt = now - last_status;
            std::printf("t=%.0fs %.0f fps, %.0f generations/s, up to %d per frame\n", now, (frames - frames_at) / dt,
                        (app.generation() - gens_at) / dt, app.steps_per_frame_limit());
            frames_at = frames;
            gens_at = app.generation();
            last_status = now;
            next_status += 10;
        }
    }
    app.release();
    glfwTerminate();
    return 0;
}

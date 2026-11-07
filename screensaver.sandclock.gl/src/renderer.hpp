// Draws the engine's grains: one GL_POINTS draw per list, no per-frame uploads. The vertex
// shader works out where each grain is from its flight data and the time.
// GLSL 1.20 / GLSL ES 1.00 and no VAOs, so it runs on GL 2.1 and GLES 2.0 alike.
#pragma once
#include <string>
#include <vector>

#include "engine.hpp"

namespace sandclock {

class Renderer {
public:
    ~Renderer();
    bool init(std::string* error);
    // now: same clock as Engine::update's `real`. fb_w/fb_h: framebuffer size in pixels.
    void draw(Engine& engine, double now, int fb_w, int fb_h);
    void release();

private:
    void upload(unsigned buf, const std::vector<Instance>& v, size_t* count);
    unsigned program_ = 0, vbo_pile_ = 0, vbo_glyph_ = 0, vao_ = 0;
    size_t n_pile_ = 0, n_glyph_ = 0;
    int u_now_ = -1, u_grain_ = -1, u_pxscale_ = -1, u_base_ = -1, u_chg_ = -1, u_look_ = -1,
        u_viewport_ = -1;
};

}  // namespace sandclock

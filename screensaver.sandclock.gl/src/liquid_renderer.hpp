// Draws the LiquidEngine: the digits and falling drops as point sprites (their fall is evaluated
// in the vertex shader, no per-frame upload), the splash spray and foam, then the pool as one
// triangle strip per coloured liquid. GLSL 1.20 / GLSL ES 1.00 (and 1.50 core with a VAO), like
// Renderer.
#pragma once
#include <string>

#include "liquid.hpp"

namespace sandclock {

class LiquidRenderer {
public:
    ~LiquidRenderer();
    bool init(std::string* error);
    void draw(LiquidEngine& engine, double now, int fb_w, int fb_h);
    void release();

private:
    void upload(unsigned buf, const void* data, size_t bytes, size_t elem, size_t* count);

    unsigned drop_prog_ = 0, spray_prog_ = 0, water_prog_ = 0;
    unsigned vbo_drops_ = 0, vbo_glyph_ = 0, vbo_spray_ = 0, vbo_foam_ = 0, vbo_water_ = 0, vao_ = 0;
    size_t n_drops_ = 0, n_glyph_ = 0, n_spray_ = 0, n_foam_ = 0;

    int u_now_ = -1, u_grain_ = -1, u_pxscale_ = -1, u_wobble_ = -1, u_look_ = -1, u_viewport_ = -1;
    int s_now_ = -1, s_pxscale_ = -1, s_viewport_ = -1, s_foam_ = -1;
    int w_now_ = -1, w_viewport_ = -1, w_colour_ = -1;
};

}  // namespace sandclock

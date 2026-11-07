// Draws the LiquidEngine: the digits and falling drops as point sprites (their fall is evaluated
// in the vertex shader, no per-frame upload), then the pool as one triangle strip over them.
// GLSL 1.20 / GLSL ES 1.00 (and 1.50 core with a VAO), like Renderer.
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
    void upload(unsigned buf, const std::vector<Instance>& v, size_t* count);
    unsigned drop_prog_ = 0, pool_prog_ = 0, vbo_drops_ = 0, vbo_glyph_ = 0, vbo_pool_ = 0, vao_ = 0;
    size_t n_drops_ = 0, n_glyph_ = 0;
    int u_now_ = -1, u_grain_ = -1, u_pxscale_ = -1, u_wobble_ = -1, u_look_ = -1, u_viewport_ = -1;
    int p_viewport_ = -1, p_colour_ = -1;
};

}  // namespace sandclock

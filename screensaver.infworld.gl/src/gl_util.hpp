// Shader dialects, compiling and the GL state save/restore the GPU screensavers share
// (Physarum uses it; Cellular Automata has its own copy in automata_app.cpp).
// Shaders are written in GLSL 1.20 / GLSL ES 1.00 style; the prefixes below make them compile as
// GLSL ES 1.00 (Android), 1.20 (harness) or 1.50 core (Kodi on macOS).
#pragma once
#include <string>

#include "gl_include.hpp"

#ifndef GL_BLEND_SRC_RGB
#define GL_BLEND_SRC_RGB 0x80C9
#define GL_BLEND_DST_RGB 0x80C8
#define GL_BLEND_SRC_ALPHA 0x80CB
#define GL_BLEND_DST_ALPHA 0x80CA
#endif
#ifndef GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS
#define GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS 0x8B4C
#endif

namespace sandclock {
namespace glu {

#if defined(SANDCLOCK_GLES)
inline const char* version_vertex() { return ""; }
inline const char* version_fragment() { return ""; }
#elif defined(SANDCLOCK_CORE)
inline const char* version_vertex() {
    return "#version 150\n#define attribute in\n#define varying out\n#define texture2D texture\n";
}
inline const char* version_fragment() {
    return "#version 150\n#define varying in\n#define texture2D texture\n#define textureCube texture\n"
           "out vec4 sc_fragColor;\n"
           "#define gl_FragColor sc_fragColor\n";
}
#else
inline const char* version_vertex() { return "#version 120\n"; }
inline const char* version_fragment() { return "#version 120\n"; }
#endif

// Fragment shaders get high precision where the device has it (the agent state needs it).
inline const char* fragment_header() {
    return "\n#ifdef GL_ES\n#ifdef GL_FRAGMENT_PRECISION_HIGH\nprecision highp float;\n#else\n"
           "precision mediump float;\n#endif\n#endif\n";
}
inline const char* vertex_header() { return "\n#ifdef GL_ES\nprecision highp float;\n#endif\n"; }

// A full-screen quad's vertex shader: a0 in -1..1, v_uv in 0..1.
inline const char* quad_vertex() {
    return "attribute vec2 a0;\nvarying vec2 v_uv;\n"
           "void main() { v_uv = a0 * 0.5 + 0.5; gl_Position = vec4(a0, 0.0, 1.0); }\n";
}

inline unsigned compile(unsigned type, const char* body, std::string* error) {
    bool vs = type == GL_VERTEX_SHADER;
    const char* src[3] = {vs ? version_vertex() : version_fragment(), vs ? vertex_header() : fragment_header(), body};
    unsigned sh = glCreateShader(type);
    glShaderSource(sh, 3, src, nullptr);
    glCompileShader(sh);
    int ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[2048];
        glGetShaderInfoLog(sh, sizeof log, nullptr, log);
        *error = std::string(vs ? "vertex: " : "fragment: ") + log;
        glDeleteShader(sh);
        return 0;
    }
    return sh;
}

// vertex == nullptr: the quad vertex shader. Attribute 0 is "a0".
inline unsigned link(const char* vertex, const char* fragment, std::string* error) {
    unsigned vs = compile(GL_VERTEX_SHADER, vertex ? vertex : quad_vertex(), error);
    if (!vs) return 0;
    unsigned fs = compile(GL_FRAGMENT_SHADER, fragment, error);
    if (!fs) { glDeleteShader(vs); return 0; }
    unsigned prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glBindAttribLocation(prog, 0, "a0");
    glLinkProgram(prog);
    int ok = 0;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    glDeleteShader(vs);
    glDeleteShader(fs);
    if (!ok) {
        char log[2048];
        glGetProgramInfoLog(prog, sizeof log, nullptr, log);
        *error = std::string("link: ") + log;
        glDeleteProgram(prog);
        return 0;
    }
    return prog;
}

// Saves what Kodi (or the harness) had bound and enabled, and puts it back.
struct SavedState {
    int fbo = 0, viewport[4] = {0, 0, 0, 0}, active_texture = 0, program = 0, array_buffer = 0;
    int blend_src_rgb = 0, blend_dst_rgb = 0, blend_src_a = 0, blend_dst_a = 0;
    bool blend, depth, cull, scissor;
#ifdef SANDCLOCK_CORE
    int vao = 0;
#endif
    SavedState() {
        glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fbo);
        glGetIntegerv(GL_VIEWPORT, viewport);
        glGetIntegerv(GL_ACTIVE_TEXTURE, &active_texture);
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &array_buffer);
#ifdef SANDCLOCK_CORE
        glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
#endif
        glGetIntegerv(GL_BLEND_SRC_RGB, &blend_src_rgb);
        glGetIntegerv(GL_BLEND_DST_RGB, &blend_dst_rgb);
        glGetIntegerv(GL_BLEND_SRC_ALPHA, &blend_src_a);
        glGetIntegerv(GL_BLEND_DST_ALPHA, &blend_dst_a);
        blend = glIsEnabled(GL_BLEND); depth = glIsEnabled(GL_DEPTH_TEST);
        cull = glIsEnabled(GL_CULL_FACE); scissor = glIsEnabled(GL_SCISSOR_TEST);
        glDisable(GL_BLEND); glDisable(GL_DEPTH_TEST); glDisable(GL_CULL_FACE); glDisable(GL_SCISSOR_TEST);
    }
    ~SavedState() {
        glBindFramebuffer(GL_FRAMEBUFFER, (unsigned)fbo);
        glViewport(viewport[0], viewport[1], viewport[2], viewport[3]);
        for (unsigned unit : {GL_TEXTURE3, GL_TEXTURE2, GL_TEXTURE1}) {
            glActiveTexture(unit);
            glBindTexture(GL_TEXTURE_2D, 0);
        }
        glActiveTexture((unsigned)active_texture);
        glBindTexture(GL_TEXTURE_2D, 0);
        glUseProgram((unsigned)program);
        glBindBuffer(GL_ARRAY_BUFFER, (unsigned)array_buffer);
#ifdef SANDCLOCK_CORE
        // A core-profile context draws only through a bound VAO, so put back whichever one the
        // caller had; ours is deleted in release() and must not be left bound.
        glBindVertexArray((unsigned)vao);
#endif
        glBlendFuncSeparate((unsigned)blend_src_rgb, (unsigned)blend_dst_rgb, (unsigned)blend_src_a, (unsigned)blend_dst_a);
        // Kodi's GUI draws its quads with culling off and depth test off. If we leave either
        // enabled, textured GUI quads are culled and the skin loses its pictures.
        if (blend) glEnable(GL_BLEND); else glDisable(GL_BLEND);
        if (depth) glEnable(GL_DEPTH_TEST); else glDisable(GL_DEPTH_TEST);
        if (cull) glEnable(GL_CULL_FACE); else glDisable(GL_CULL_FACE);
        if (scissor) glEnable(GL_SCISSOR_TEST); else glDisable(GL_SCISSOR_TEST);
    }
};

}  // namespace glu
}  // namespace sandclock

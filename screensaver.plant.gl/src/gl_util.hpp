// Shader dialects, compiling and the GL state save/restore.
// Shaders are written in GLSL 1.20 / GLSL ES 1.00 style; the prefixes below make them compile as
// GLSL ES 1.00 (Android), 1.20 (harness) or 1.50 core (Kodi on macOS, OpenGL 3.2 core).
#pragma once
#include <string>

#include "gl_include.hpp"

#ifndef GL_BLEND_SRC_RGB
#define GL_BLEND_SRC_RGB 0x80C9
#define GL_BLEND_DST_RGB 0x80C8
#define GL_BLEND_SRC_ALPHA 0x80CB
#define GL_BLEND_DST_ALPHA 0x80CA
#endif
#ifndef GL_PROGRAM_POINT_SIZE
#define GL_PROGRAM_POINT_SIZE 0x8642
#endif

namespace plantgl {
namespace glu {

#if defined(PLANT_GLES)
inline const char* version_vertex() { return ""; }
inline const char* version_fragment() { return ""; }
#elif defined(PLANT_CORE)
inline const char* version_vertex() {
    return "#version 150\n#define attribute in\n#define varying out\n";
}
inline const char* version_fragment() {
    return "#version 150\n#define varying in\nout vec4 pl_fragColor;\n#define gl_FragColor pl_fragColor\n";
}
#else
inline const char* version_vertex() { return "#version 120\n"; }
inline const char* version_fragment() { return "#version 120\n"; }
#endif

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
    const char* src[3] = {vs ? version_vertex() : version_fragment(),
                          vs ? vertex_header() : fragment_header(), body};
    unsigned sh = glCreateShader(type);
    glShaderSource(sh, 3, src, nullptr);
    glCompileShader(sh);
    int ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[4096];
        glGetShaderInfoLog(sh, sizeof log, nullptr, log);
        *error = std::string(vs ? "vertex: " : "fragment: ") + log;
        glDeleteShader(sh);
        return 0;
    }
    return sh;
}

// vertex == nullptr: the quad vertex shader. Attributes are bound by name to 0..n-1 in order.
inline unsigned link(const char* vertex, const char* fragment, const char* const* attributes,
                     int attribute_count, std::string* error) {
    unsigned vs = compile(GL_VERTEX_SHADER, vertex ? vertex : quad_vertex(), error);
    if (!vs) return 0;
    unsigned fs = compile(GL_FRAGMENT_SHADER, fragment, error);
    if (!fs) {
        glDeleteShader(vs);
        return 0;
    }
    unsigned prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    for (int i = 0; i < attribute_count; ++i) glBindAttribLocation(prog, (unsigned)i, attributes[i]);
    glLinkProgram(prog);
    int ok = 0;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    glDeleteShader(vs);
    glDeleteShader(fs);
    if (!ok) {
        char log[4096];
        glGetProgramInfoLog(prog, sizeof log, nullptr, log);
        *error = std::string("link: ") + log;
        glDeleteProgram(prog);
        return 0;
    }
    return prog;
}

// Saves what Kodi (or the harness) had bound and enabled, and puts it back. Restoring the
// enables both ways matters: leaving culling or the depth test on made Kodi's skin lose its
// images after a screensaver exited.
struct SavedState {
    int fbo = 0, viewport[4] = {0, 0, 0, 0}, active_texture = 0, program = 0, array_buffer = 0;
    int element_buffer = 0;
    float clear_color[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    GLboolean depth_mask = GL_TRUE;
#if defined(PLANT_GLES)
    int blend_src = 0, blend_dst = 0;
#else
    int blend_src_rgb = 0, blend_dst_rgb = 0, blend_src_a = 0, blend_dst_a = 0;
    bool point_size = false;
#endif
    bool blend, depth, cull, scissor;
#ifdef PLANT_CORE
    int vao = 0;
#endif
    SavedState() {
        glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fbo);
        glGetIntegerv(GL_VIEWPORT, viewport);
        glGetIntegerv(GL_ACTIVE_TEXTURE, &active_texture);
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &array_buffer);
        glGetIntegerv(GL_ELEMENT_ARRAY_BUFFER_BINDING, &element_buffer);
        glGetFloatv(GL_COLOR_CLEAR_VALUE, clear_color);
        glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_mask);
#ifdef PLANT_CORE
        glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
#endif
#if defined(PLANT_GLES)
        // GLES2 has no GL_BLEND_SRC/GL_BLEND_DST (desktop aliases); it has the RGB queries, and
        // glBlendFunc sets the alpha factors to the same values, so restoring RGB is complete.
        glGetIntegerv(GL_BLEND_SRC_RGB, &blend_src);
        glGetIntegerv(GL_BLEND_DST_RGB, &blend_dst);
#else
        glGetIntegerv(GL_BLEND_SRC_RGB, &blend_src_rgb);
        glGetIntegerv(GL_BLEND_DST_RGB, &blend_dst_rgb);
        glGetIntegerv(GL_BLEND_SRC_ALPHA, &blend_src_a);
        glGetIntegerv(GL_BLEND_DST_ALPHA, &blend_dst_a);
        point_size = glIsEnabled(GL_PROGRAM_POINT_SIZE);
#endif
        blend = glIsEnabled(GL_BLEND);
        depth = glIsEnabled(GL_DEPTH_TEST);
        cull = glIsEnabled(GL_CULL_FACE);
        scissor = glIsEnabled(GL_SCISSOR_TEST);
        glDisable(GL_BLEND);
        glDisable(GL_DEPTH_TEST);
        glDisable(GL_CULL_FACE);
        glDisable(GL_SCISSOR_TEST);
    }
    ~SavedState() {
        glBindFramebuffer(GL_FRAMEBUFFER, (unsigned)fbo);
        glViewport(viewport[0], viewport[1], viewport[2], viewport[3]);
        glActiveTexture((unsigned)active_texture);
        glUseProgram((unsigned)program);
        glBindBuffer(GL_ARRAY_BUFFER, (unsigned)array_buffer);
#ifdef PLANT_CORE
        glBindVertexArray((unsigned)vao);
#endif
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, (unsigned)element_buffer);
        glDepthMask(depth_mask);
        glClearColor(clear_color[0], clear_color[1], clear_color[2], clear_color[3]);
#if defined(PLANT_GLES)
        glBlendFunc((unsigned)blend_src, (unsigned)blend_dst);
#else
        glBlendFuncSeparate((unsigned)blend_src_rgb, (unsigned)blend_dst_rgb,
                            (unsigned)blend_src_a, (unsigned)blend_dst_a);
#endif
        if (blend) glEnable(GL_BLEND); else glDisable(GL_BLEND);
        if (depth) glEnable(GL_DEPTH_TEST); else glDisable(GL_DEPTH_TEST);
        if (cull) glEnable(GL_CULL_FACE); else glDisable(GL_CULL_FACE);
        if (scissor) glEnable(GL_SCISSOR_TEST); else glDisable(GL_SCISSOR_TEST);
#if !defined(PLANT_GLES)
        if (point_size) glEnable(GL_PROGRAM_POINT_SIZE); else glDisable(GL_PROGRAM_POINT_SIZE);
#endif
    }
};

}  // namespace glu
}  // namespace plantgl

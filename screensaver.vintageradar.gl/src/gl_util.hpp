// Shader dialects, compiling, and the GL state save/restore. The same shader bodies compile as
// GLSL 1.20 (harness), GLSL ES 1.00 (Android) and GLSL 1.50 core (Kodi on macOS).
#pragma once
#include <string>

#include "gl_include.hpp"

#ifndef GL_BLEND_SRC_RGB
#define GL_BLEND_SRC_RGB 0x80C9
#define GL_BLEND_DST_RGB 0x80C8
#define GL_BLEND_SRC_ALPHA 0x80CB
#define GL_BLEND_DST_ALPHA 0x80CA
#endif
#ifndef GL_TEXTURE_BINDING_2D
#define GL_TEXTURE_BINDING_2D 0x8069
#endif
#ifndef GL_VERTEX_ARRAY_BINDING
#define GL_VERTEX_ARRAY_BINDING 0x85B5
#endif

namespace radar {
namespace glu {

#if defined(RADAR_GLES)
inline const char* version_vertex() { return ""; }
inline const char* version_fragment() { return ""; }
#elif defined(RADAR_CORE)
inline const char* version_vertex() {
  return "#version 150\n#define attribute in\n#define varying out\n";
}
inline const char* version_fragment() {
  return "#version 150\n#define varying in\nout vec4 pl_fragColor;\n#define gl_FragColor "
         "pl_fragColor\n#define texture2D texture\n";
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

inline unsigned compile(unsigned type, const char* body, std::string* error) {
  const bool vs = type == GL_VERTEX_SHADER;
  const char* src[3] = {vs ? version_vertex() : version_fragment(),
                        vs ? vertex_header() : fragment_header(), body};
  const unsigned sh = glCreateShader(type);
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

inline unsigned link(const char* vertex, const char* fragment, const char* const* attributes,
                     int attribute_count, std::string* error) {
  const unsigned vs = compile(GL_VERTEX_SHADER, vertex, error);
  if (!vs) return 0;
  const unsigned fs = compile(GL_FRAGMENT_SHADER, fragment, error);
  if (!fs) {
    glDeleteShader(vs);
    return 0;
  }
  const unsigned prog = glCreateProgram();
  glAttachShader(prog, vs);
  glAttachShader(prog, fs);
  for (int i = 0; i < attribute_count; ++i)
    glBindAttribLocation(prog, static_cast<unsigned>(i), attributes[i]);
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

// Saves what Kodi (or the harness) had bound and enabled, and puts it back. Leaving culling, the
// depth test or a depth mask behind made Kodi's skin lose its images after a native screensaver
// exited, so the restore is deliberately broad. Texture binding 0 is restored as well.
struct SavedState {
  int fbo = 0, viewport[4] = {0, 0, 0, 0}, active_texture = 0, program = 0, array_buffer = 0;
  int element_buffer = 0, texture = 0;
  float clear_color[4] = {0.0f, 0.0f, 0.0f, 0.0f};
  GLboolean depth_mask = GL_TRUE;
#if defined(RADAR_GLES)
  int blend_src = 0, blend_dst = 0;
#else
  int blend_src_rgb = 0, blend_dst_rgb = 0, blend_src_a = 0, blend_dst_a = 0;
#endif
  bool blend, depth, cull, scissor;
#ifdef RADAR_CORE
  int vao = 0;
#endif
  SavedState() {
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fbo);
    glGetIntegerv(GL_VIEWPORT, viewport);
    glGetIntegerv(GL_ACTIVE_TEXTURE, &active_texture);
    glGetIntegerv(GL_CURRENT_PROGRAM, &program);
    glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &array_buffer);
    glGetIntegerv(GL_ELEMENT_ARRAY_BUFFER_BINDING, &element_buffer);
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &texture);
    glGetFloatv(GL_COLOR_CLEAR_VALUE, clear_color);
    glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_mask);
#ifdef RADAR_CORE
    glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
#endif
#if defined(RADAR_GLES)
    glGetIntegerv(GL_BLEND_SRC_RGB, &blend_src);
    glGetIntegerv(GL_BLEND_DST_RGB, &blend_dst);
#else
    glGetIntegerv(GL_BLEND_SRC_RGB, &blend_src_rgb);
    glGetIntegerv(GL_BLEND_DST_RGB, &blend_dst_rgb);
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &blend_src_a);
    glGetIntegerv(GL_BLEND_DST_ALPHA, &blend_dst_a);
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
    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<unsigned>(fbo));
    glViewport(viewport[0], viewport[1], viewport[2], viewport[3]);
    glActiveTexture(static_cast<unsigned>(active_texture));
    glUseProgram(static_cast<unsigned>(program));
    glBindBuffer(GL_ARRAY_BUFFER, static_cast<unsigned>(array_buffer));
#ifdef RADAR_CORE
    glBindVertexArray(static_cast<unsigned>(vao));
#endif
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, static_cast<unsigned>(element_buffer));
    glBindTexture(GL_TEXTURE_2D, static_cast<unsigned>(texture));
    glDepthMask(depth_mask);
    glClearColor(clear_color[0], clear_color[1], clear_color[2], clear_color[3]);
#if defined(RADAR_GLES)
    glBlendFunc(static_cast<unsigned>(blend_src), static_cast<unsigned>(blend_dst));
#else
    glBlendFuncSeparate(static_cast<unsigned>(blend_src_rgb), static_cast<unsigned>(blend_dst_rgb),
                        static_cast<unsigned>(blend_src_a), static_cast<unsigned>(blend_dst_a));
#endif
    if (blend) glEnable(GL_BLEND); else glDisable(GL_BLEND);
    if (depth) glEnable(GL_DEPTH_TEST); else glDisable(GL_DEPTH_TEST);
    if (cull) glEnable(GL_CULL_FACE); else glDisable(GL_CULL_FACE);
    if (scissor) glEnable(GL_SCISSOR_TEST); else glDisable(GL_SCISSOR_TEST);
  }
};

}  // namespace glu
}  // namespace radar

// Kodi screensaver wrapper around the ScreenMazer animation.
// The maze is one RGBA texel per cell, updated on the CPU and drawn as a single
// nearest-filtered quad with plain OpenGL / OpenGL ES 2.

#include "Mazer.h"

#include <kodi/addon-instance/Screensaver.h>
#include <kodi/gui/gl/GL.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <string>

namespace
{

// Kodi uses a GL 3.2 core context on macOS (no `attribute`, `varying`,
// `texture2D` or `gl_FragColor`, and a VAO is required); GLES 2 and Linux GL
// 2.1 take the shader bodies as they are.
#if defined(HAS_GLES)
const std::string kVertexHeader;
const std::string kFragmentHeader;
#elif defined(TARGET_DARWIN)
const std::string kVertexHeader = "#version 150\n#define attribute in\n#define varying out\n";
const std::string kFragmentHeader = "#version 150\nout vec4 fragColor;\n"
                                    "#define gl_FragColor fragColor\n"
                                    "#define varying in\n#define texture2D texture\n";
#else
const std::string kVertexHeader = "#version 120\n";
const std::string kFragmentHeader = "#version 120\n";
#endif

const char* kVertexShader = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;
varying vec2 v_uv;
void main()
{
  gl_Position = vec4(a_pos, 0.0, 1.0);
  v_uv = a_pos * 0.5 + 0.5;
}
)";

const char* kFragmentShader = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_tex;
varying vec2 v_uv;
void main()
{
  gl_FragColor = vec4(texture2D(u_tex, v_uv).rgb, 1.0);
}
)";

// Cell sizes are given in pixels on a 1080-line screen and scaled to the
// actual resolution, so a maze looks the same on 720p, 1080p and 4K.
constexpr float kReferenceHeight = 1080.0f;

mazer::RGB ParseColour(const std::string& text, mazer::RGB fallback)
{
  std::string v = text;
  if (!v.empty() && v[0] == '#')
    v.erase(0, 1);
  if (v.size() != 6 && v.size() != 8)
    return fallback;
  char* end = nullptr;
  const unsigned long n = std::strtoul(v.c_str(), &end, 16); // AARRGGBB or RRGGBB
  if (!end || *end)
    return fallback;
  return {((n >> 16) & 0xFF) / 255.0f, ((n >> 8) & 0xFF) / 255.0f, (n & 0xFF) / 255.0f};
}

} // namespace

class ATTR_DLL_LOCAL CScreensaverMazer : public kodi::addon::CAddonBase,
                                         public kodi::addon::CInstanceScreensaver
{
public:
  CScreensaverMazer() = default;

  bool Start() override;
  void Stop() override;
  void Render() override;

private:
  using Clock = std::chrono::steady_clock;

  mazer::Settings LoadSettings();
  GLuint Compile(GLenum type, const std::string& src);
  bool BuildProgram();
  void Layout();

  mazer::Settings m_settings;
  mazer::Animator m_anim;
  int m_mazeSize = 7;

  GLuint m_program = 0;
  GLint m_aPos = -1, m_uTex = -1;
  GLuint m_vbo = 0, m_vao = 0, m_tex = 0;

  int m_screenW = 0, m_screenH = 0;
  int m_cellPx = 1, m_offX = 0, m_offY = 0;
  bool m_dirty = true;

  Clock::time_point m_lastFrame;
};

mazer::Settings CScreensaverMazer::LoadSettings()
{
  mazer::Settings s;
  s.path = ParseColour(kodi::addon::GetSettingString("path_colour", "FF808080"), s.path);
  s.solve = ParseColour(kodi::addon::GetSettingString("solve_colour", "FFFFFFFF"), s.solve);
  s.wall = ParseColour(kodi::addon::GetSettingString("wall_colour", "FF000000"), s.wall);
  s.buildSeconds = std::max(1, kodi::addon::GetSettingInt("build_time", 30));
  s.solveSeconds = std::max(1, kodi::addon::GetSettingInt("solve_time", 10));
  s.solveMaze = kodi::addon::GetSettingBoolean("solve", true);
  s.showClock = kodi::addon::GetSettingBoolean("show_clock", true);
  s.clockScale = std::min(std::max(kodi::addon::GetSettingInt("clock_size", 1), 1), 3);
  s.hour24 = kodi::addon::GetSettingBoolean("hour24", false);
  s.centreClock = kodi::addon::GetSettingInt("clock_position", 0) == 1;
  m_mazeSize = std::min(std::max(kodi::addon::GetSettingInt("maze_size", 7), 2), 15);
  return s;
}

GLuint CScreensaverMazer::Compile(GLenum type, const std::string& src)
{
  GLuint shader = glCreateShader(type);
  const char* text = src.c_str();
  glShaderSource(shader, 1, &text, nullptr);
  glCompileShader(shader);
  GLint ok = 0;
  glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
  if (!ok)
  {
    char log[1024] = {};
    glGetShaderInfoLog(shader, sizeof(log) - 1, nullptr, log);
    kodi::Log(ADDON_LOG_ERROR, "ScreenMazer: shader compile failed: %s", log);
    glDeleteShader(shader);
    return 0;
  }
  return shader;
}

bool CScreensaverMazer::BuildProgram()
{
  GLuint vs = Compile(GL_VERTEX_SHADER, kVertexHeader + kVertexShader);
  GLuint fs = Compile(GL_FRAGMENT_SHADER, kFragmentHeader + kFragmentShader);
  if (!vs || !fs)
  {
    if (vs)
      glDeleteShader(vs);
    if (fs)
      glDeleteShader(fs);
    return false;
  }
  m_program = glCreateProgram();
  glAttachShader(m_program, vs);
  glAttachShader(m_program, fs);
  glLinkProgram(m_program);
  glDeleteShader(vs);
  glDeleteShader(fs);
  GLint ok = 0;
  glGetProgramiv(m_program, GL_LINK_STATUS, &ok);
  if (!ok)
  {
    char log[1024] = {};
    glGetProgramInfoLog(m_program, sizeof(log) - 1, nullptr, log);
    kodi::Log(ADDON_LOG_ERROR, "ScreenMazer: program link failed: %s", log);
    glDeleteProgram(m_program);
    m_program = 0;
    return false;
  }
  m_aPos = glGetAttribLocation(m_program, "a_pos");
  m_uTex = glGetUniformLocation(m_program, "u_tex");
  return true;
}

// Size the grid for the current screen and start a fresh maze.
void CScreensaverMazer::Layout()
{
  m_screenW = std::max(1, Width());
  m_screenH = std::max(1, Height());
  m_cellPx = std::max(1, static_cast<int>(std::lround(m_mazeSize * m_screenH / kReferenceHeight)));
  const int rows = std::max(1, m_screenH / m_cellPx);
  const int cols = std::max(1, m_screenW / m_cellPx);
  m_offX = (m_screenW - cols * m_cellPx) / 2;
  m_offY = (m_screenH - rows * m_cellPx) / 2;

  const uint32_t seed = static_cast<uint32_t>(
      std::chrono::high_resolution_clock::now().time_since_epoch().count());
  m_anim.Init(rows, cols, m_settings, seed);

  glBindTexture(GL_TEXTURE_2D, m_tex);
  glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, cols, rows, 0, GL_RGBA, GL_UNSIGNED_BYTE,
               m_anim.pixels().data());
  glBindTexture(GL_TEXTURE_2D, 0);
  m_dirty = false;

  kodi::Log(ADDON_LOG_DEBUG, "ScreenMazer: %dx%d cells of %d px", cols, rows, m_cellPx);
}

bool CScreensaverMazer::Start()
{
  m_settings = LoadSettings();
  if (!BuildProgram())
    return false;

#ifdef TARGET_DARWIN
  glGenVertexArrays(1, &m_vao);
#endif
  const float quad[] = {-1, -1, 1, -1, -1, 1, 1, 1};
  glGenBuffers(1, &m_vbo);
  glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
  glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
  glBindBuffer(GL_ARRAY_BUFFER, 0);

  glGenTextures(1, &m_tex);
  glBindTexture(GL_TEXTURE_2D, m_tex);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glBindTexture(GL_TEXTURE_2D, 0);

  Layout();
  m_lastFrame = Clock::now();
  return true;
}

void CScreensaverMazer::Stop()
{
  if (m_tex)
  {
    glDeleteTextures(1, &m_tex);
    m_tex = 0;
  }
  if (m_vbo)
  {
    glDeleteBuffers(1, &m_vbo);
    m_vbo = 0;
  }
#ifdef TARGET_DARWIN
  if (m_vao)
  {
    glDeleteVertexArrays(1, &m_vao);
    m_vao = 0;
  }
#endif
  if (m_program)
  {
    glDeleteProgram(m_program);
    m_program = 0;
  }
}

void CScreensaverMazer::Render()
{
  if (!m_program)
    return;
  if (Width() != m_screenW || Height() != m_screenH)
    Layout();

  const auto now = Clock::now();
  const double dt = std::chrono::duration<double>(now - m_lastFrame).count();
  m_lastFrame = now;
  m_dirty |= m_anim.Update(dt);

  if (m_dirty)
  {
    glBindTexture(GL_TEXTURE_2D, m_tex);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, m_anim.cols(), m_anim.rows(), GL_RGBA,
                    GL_UNSIGNED_BYTE, m_anim.pixels().data());
    m_dirty = false;
  }

  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glDisable(GL_BLEND);

  // The margins left by whole cells take the wall colour.
  glViewport(X(), Y(), Width(), Height());
  glClearColor(m_settings.wall.r, m_settings.wall.g, m_settings.wall.b, 1.0f);
  glClear(GL_COLOR_BUFFER_BIT);

  glViewport(X() + m_offX, Y() + m_offY, m_anim.cols() * m_cellPx, m_anim.rows() * m_cellPx);
#ifdef TARGET_DARWIN
  glBindVertexArray(m_vao);
#endif
  glUseProgram(m_program);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, m_tex);
  glUniform1i(m_uTex, 0);
  glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
  glEnableVertexAttribArray(static_cast<GLuint>(m_aPos));
  glVertexAttribPointer(static_cast<GLuint>(m_aPos), 2, GL_FLOAT, GL_FALSE, 0, nullptr);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
  glDisableVertexAttribArray(static_cast<GLuint>(m_aPos));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glBindTexture(GL_TEXTURE_2D, 0);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif
  glUseProgram(0);
  glViewport(X(), Y(), Width(), Height());
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
}

ADDONCREATOR(CScreensaverMazer)

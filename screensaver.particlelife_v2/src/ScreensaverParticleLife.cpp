// Kodi screensaver wrapper around the Particle Life simulation.
// Renders with plain OpenGL / OpenGL ES 2 (GLSL 1.00 style shaders).

#include "ParticleLife.h"

#include <kodi/addon-instance/Screensaver.h>
#include <kodi/gui/gl/GL.h>

#include <chrono>
#include <cstdio>
#include <string>
#include <vector>

// GLES always honours gl_PointSize; desktop GL needs the capability enabled, and
// some GL headers do not define the token.
#if !defined(HAS_GLES) && !defined(GL_PROGRAM_POINT_SIZE)
#define GL_PROGRAM_POINT_SIZE 0x8642
#endif

namespace
{

// Kodi uses a GL 3.2 core context on macOS, where `attribute` and `gl_FragColor`
// are gone and a VAO is required; on Linux Kodi runs a GL 2.1 compatibility
// context. GLES 2 takes the shader bodies as they are.
#if defined(HAS_GLES)
const std::string kVertexHeader;
const std::string kFragmentHeader;
#elif defined(TARGET_DARWIN)
const std::string kVertexHeader = "#version 150\n#define attribute in\n";
const std::string kFragmentHeader =
    "#version 150\nout vec4 fragColor;\n#define gl_FragColor fragColor\n";
#else
const std::string kVertexHeader = "#version 120\n";
const std::string kFragmentHeader = "#version 120\n";
#endif

const char* kVertexShader = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;      // virtual (simulation) coordinates, origin top-left
uniform vec2 u_scale;      // 2/W, -2/H
uniform float u_pointSize;
void main()
{
  gl_Position = vec4(a_pos.x * u_scale.x - 1.0, a_pos.y * u_scale.y + 1.0, 0.0, 1.0);
  gl_PointSize = u_pointSize;
}
)";

const char* kFragmentShader = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform vec4 u_color;
void main()
{
  vec2 c = gl_PointCoord - vec2(0.5);
  float d = dot(c, c);
  if (d > 0.25)
    discard;
  gl_FragColor = vec4(u_color.rgb, u_color.a * (1.0 - smoothstep(0.16, 0.25, d)));
}
)";

// Height of the virtual simulation space. The original app used 1600x900 and
// its force radii are in those pixel units, so we keep that scale and just
// widen the space to match the display's aspect ratio.
constexpr float kVirtualHeight = 900.0f;

} // namespace

class ATTR_DLL_LOCAL CScreensaverParticleLife : public kodi::addon::CAddonBase,
                                                 public kodi::addon::CInstanceScreensaver
{
public:
  CScreensaverParticleLife() = default;

  bool Start() override;
  void Stop() override;
  void Render() override;

private:
  using Clock = std::chrono::steady_clock;

  void LoadSettings();
  bool BuildProgram();
  GLuint Compile(GLenum type, const std::string& src);
  void Randomize();

  particlelife::Simulation m_sim;

  GLuint m_program = 0;
  GLuint m_vbo = 0;
  GLuint m_vao = 0; // macOS core profile needs one bound for glVertexAttribPointer
  GLint m_aPos = -1;
  GLint m_uScale = -1;
  GLint m_uPointSize = -1;
  GLint m_uColor = -1;

  std::vector<float> m_vertices; // x,y interleaved, group after group

  int m_stepsPerSecond = 60;
  float m_pointSize = 2.0f;
  int m_randomizeSeconds = 60;

  Clock::time_point m_lastFrame;
  Clock::time_point m_lastRandomize;
  double m_accumulator = 0.0;
};

//------------------------------------------------------------------------------

void CScreensaverParticleLife::LoadSettings()
{
  auto& p = m_sim.params;
  p.perColour = kodi::addon::GetSettingInt("particles_per_colour", 1000);
  p.viscosity = kodi::addon::GetSettingInt("viscosity", 50) / 100.0f;
  p.wallRepel = static_cast<float>(kodi::addon::GetSettingInt("wall_repel", 10));
  p.bounded = kodi::addon::GetSettingBoolean("bounded", false);
  p.evolve = kodi::addon::GetSettingBoolean("evolve", false);
  p.forceVariance = kodi::addon::GetSettingInt("force_strength", 80) / 100.0f;
  p.radiusVariance = kodi::addon::GetSettingInt("interaction_range", 60) / 100.0f;

  m_stepsPerSecond = std::max(1, kodi::addon::GetSettingInt("steps_per_second", 60));
  m_pointSize = static_cast<float>(kodi::addon::GetSettingInt("point_size", 2));
  m_randomizeSeconds = kodi::addon::GetSettingInt("randomize_interval", 60);
}

GLuint CScreensaverParticleLife::Compile(GLenum type, const std::string& src)
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
    kodi::Log(ADDON_LOG_ERROR, "Particle Life: shader compile failed: %s", log);
    glDeleteShader(shader);
    return 0;
  }
  return shader;
}

bool CScreensaverParticleLife::BuildProgram()
{
  GLuint vs = Compile(GL_VERTEX_SHADER, kVertexHeader + kVertexShader);
  GLuint fs = Compile(GL_FRAGMENT_SHADER, kFragmentHeader + kFragmentShader);
  if (!vs || !fs)
    return false;

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
    kodi::Log(ADDON_LOG_ERROR, "Particle Life: program link failed: %s", log);
    glDeleteProgram(m_program);
    m_program = 0;
    return false;
  }

  m_aPos = glGetAttribLocation(m_program, "a_pos");
  m_uScale = glGetUniformLocation(m_program, "u_scale");
  m_uPointSize = glGetUniformLocation(m_program, "u_pointSize");
  m_uColor = glGetUniformLocation(m_program, "u_color");
  return true;
}

void CScreensaverParticleLife::Randomize()
{
  m_sim.Randomize();
  m_lastRandomize = Clock::now();
}

bool CScreensaverParticleLife::Start()
{
  LoadSettings();

  if (!BuildProgram())
    return false;
#ifdef TARGET_DARWIN
  glGenVertexArrays(1, &m_vao);
#endif
  glGenBuffers(1, &m_vbo);

  const float aspect = static_cast<float>(Width()) / static_cast<float>(std::max(1, Height()));
  m_sim.Resize(kVirtualHeight * aspect, kVirtualHeight);
  Randomize();

  m_lastFrame = Clock::now();
  m_accumulator = 0.0;
  return true;
}

void CScreensaverParticleLife::Stop()
{
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

void CScreensaverParticleLife::Render()
{
  if (!m_program)
    return;

  // --- simulation: fixed time step, decoupled from the display refresh rate
  const auto now = Clock::now();
  m_accumulator += std::min(std::chrono::duration<double>(now - m_lastFrame).count(), 0.1);
  m_lastFrame = now;

  const double dt = 1.0 / m_stepsPerSecond;
  int steps = 0;
  while (m_accumulator >= dt && steps < 4)
  {
    m_sim.Step();
    m_accumulator -= dt;
    ++steps;
  }
  if (steps == 4)
    m_accumulator = 0.0; // can't keep up; drop the backlog instead of spiralling

  if (m_randomizeSeconds > 0 &&
      std::chrono::duration<double>(now - m_lastRandomize).count() >= m_randomizeSeconds)
    Randomize();

  // --- gather vertices (group after group)
  size_t total = 0;
  for (int i = 0; i < particlelife::NUM_GROUPS; i++)
    total += m_sim.group(i).size();
  m_vertices.resize(total * 2);

  size_t offsets[particlelife::NUM_GROUPS];
  size_t at = 0;
  for (int i = 0; i < particlelife::NUM_GROUPS; i++)
  {
    const auto& g = m_sim.group(i);
    offsets[i] = at;
    for (size_t k = 0; k < g.size(); k++, at++)
    {
      m_vertices[at * 2] = g.x[k];
      m_vertices[at * 2 + 1] = g.y[k];
    }
  }

  // --- draw
  const float aspect = static_cast<float>(Width()) / static_cast<float>(std::max(1, Height()));
  const float vw = kVirtualHeight * aspect;
  const float scalePx = static_cast<float>(Height()) / kVirtualHeight;

  glViewport(X(), Y(), Width(), Height());
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
#ifdef GL_PROGRAM_POINT_SIZE
  glEnable(GL_PROGRAM_POINT_SIZE); // desktop GL only; ES always honours gl_PointSize
#endif

  glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
  glClear(GL_COLOR_BUFFER_BIT);

  glUseProgram(m_program);
#ifdef TARGET_DARWIN
  glBindVertexArray(m_vao);
#endif
  glUniform2f(m_uScale, 2.0f / vw, -2.0f / kVirtualHeight);
  glUniform1f(m_uPointSize, std::max(1.0f, m_pointSize * scalePx));

  glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
  glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(m_vertices.size() * sizeof(float)),
               m_vertices.data(), GL_STREAM_DRAW);
  glEnableVertexAttribArray(static_cast<GLuint>(m_aPos));
  glVertexAttribPointer(static_cast<GLuint>(m_aPos), 2, GL_FLOAT, GL_FALSE, 0, nullptr);

  // Same draw order as the original: white, red, green, yellow (later = on top).
  const int order[] = {particlelife::WHITE, particlelife::RED, particlelife::GREEN,
                       particlelife::YELLOW};
  for (int idx : order)
  {
    const auto& g = m_sim.group(idx);
    if (g.size() == 0)
      continue;
    glUniform4f(m_uColor, g.r, g.g, g.b, 1.0f);
    glDrawArrays(GL_POINTS, static_cast<GLint>(offsets[idx]), static_cast<GLsizei>(g.size()));
  }

  glDisableVertexAttribArray(static_cast<GLuint>(m_aPos));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif
  glUseProgram(0);
}

ADDONCREATOR(CScreensaverParticleLife)

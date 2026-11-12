// Kodi screensaver wrapper around the Particle Life simulation.
// Renders with plain OpenGL / OpenGL ES 2 (GLSL 1.00 style shaders).

#include "ParticleLife.h"

#include <kodi/addon-instance/Screensaver.h>
#include <kodi/gui/gl/GL.h>

#include <algorithm>
#include <chrono>
#include <cmath>
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

// Kodi uses a GL 3.2 core context on macOS, where `attribute`, `varying`,
// `texture2D` and `gl_FragColor` are gone and a VAO is required; on Linux Kodi
// runs a GL 2.1 compatibility context. GLES 2 takes the shader bodies as is.
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

const char* kPointVertexShader = R"(
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

// u_style: 0 = round, 1 = square, 2 = glow (soft falloff, drawn additively)
const char* kPointFragmentShader = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform vec4 u_color;
uniform float u_style;
void main()
{
  vec2 c = gl_PointCoord - vec2(0.5);
  float d = dot(c, c);
  float a = 1.0;
  if (u_style < 0.5)
  {
    if (d > 0.25)
      discard;
    a = 1.0 - smoothstep(0.16, 0.25, d);
  }
  else if (u_style > 1.5)
  {
    if (d > 0.25)
      discard;
    a = exp(-d * 18.0);
  }
  gl_FragColor = vec4(u_color.rgb, u_color.a * a);
}
)";

// Full-screen quad for the trail buffer: out = max(prev * keep - sub, 0).
// The subtraction makes old trails fade all the way to black instead of
// leaving an 8-bit rounding ghost.
const char* kQuadVertexShader = R"(
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

const char* kQuadFragmentShader = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_tex;
uniform float u_keep;
uniform float u_sub;
varying vec2 v_uv;
void main()
{
  vec3 c = texture2D(u_tex, v_uv).rgb;
  gl_FragColor = vec4(max(c * u_keep - vec3(u_sub), vec3(0.0)), 1.0);
}
)";

// Height of the virtual simulation space. The original app used 1600x900 and
// its force radii are in those pixel units, so we keep that scale and just
// widen the space to match the display's aspect ratio.
constexpr float kVirtualHeight = 900.0f;

struct RGB
{
  float r, g, b;
};

// Colour order: red, green, yellow, white, then the extras (the JS version's
// cyan / magenta / orange / lavender).
const RGB kPalettes[3][particlelife::MAX_GROUPS] = {
    // classic (the original app's ofColor::red / green / yellow / white)
    {{1, 0, 0}, {0, 1, 0}, {1, 1, 0}, {1, 1, 1},
     {0, 1, 1}, {1, 0, 1}, {1, 0.55f, 0}, {0.7f, 0.6f, 1}},
    // neon
    {{1, 0.1f, 0.55f}, {0.1f, 1, 0.4f}, {1, 0.9f, 0.1f}, {0.3f, 0.8f, 1},
     {0.65f, 0.3f, 1}, {1, 0.45f, 0.1f}, {0.1f, 1, 1}, {0.95f, 0.95f, 1}},
    // pastel
    {{1, 0.6f, 0.6f}, {0.6f, 1, 0.7f}, {1, 0.95f, 0.6f}, {0.95f, 0.95f, 0.95f},
     {0.6f, 0.9f, 1}, {1, 0.65f, 0.95f}, {1, 0.8f, 0.55f}, {0.78f, 0.7f, 1}},
};

enum Palette { PAL_CLASSIC, PAL_NEON, PAL_PASTEL, PAL_RAINBOW, PAL_RANDOM };
enum RuleSource { SRC_RANDOM, SRC_PRESETS_ORDER, SRC_PRESETS_SHUFFLE, SRC_MIX, SRC_ONE_PRESET };
enum Style { STYLE_ROUND, STYLE_SQUARE, STYLE_GLOW };

RGB Hsv(float h, float s, float v)
{
  h = (h - std::floor(h)) * 6.0f;
  const int i = static_cast<int>(h) % 6;
  const float f = h - std::floor(h);
  const float p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f));
  switch (i)
  {
    case 0: return {v, t, p};
    case 1: return {q, v, p};
    case 2: return {p, v, t};
    case 3: return {p, q, v};
    case 4: return {t, p, v};
    default: return {v, p, q};
  }
}

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
  GLuint Compile(GLenum type, const std::string& src);
  GLuint Link(const char* vs, const char* fs);
  bool BuildPrograms();
  void NextRuleSet(bool first);
  void RandomRules();
  void UpdateColours();
  void RandomPulse();
  bool EnsureTrailBuffers(int w, int h);
  void DeleteTrailBuffers();
  void DrawParticles(float vw, float scalePx);
  void DrawQuad(GLuint tex, float keep, float sub);

  particlelife::Simulation m_sim;

  // point program
  GLuint m_program = 0;
  GLint m_aPos = -1, m_uScale = -1, m_uPointSize = -1, m_uColor = -1, m_uStyle = -1;
  // trail quad program
  GLuint m_quadProgram = 0;
  GLint m_qaPos = -1, m_quTex = -1, m_quKeep = -1, m_quSub = -1;

  GLuint m_vbo = 0, m_quadVbo = 0;
  GLuint m_vao = 0; // macOS core profile needs one bound for glVertexAttribPointer

  // ping-pong trail buffers
  GLuint m_trailTex[2] = {0, 0};
  GLuint m_trailFbo[2] = {0, 0};
  int m_trailW = 0, m_trailH = 0;
  int m_trailCur = 0;
  bool m_trailsFailed = false;

  std::vector<float> m_vertices; // x,y interleaved, group after group
  RGB m_colours[particlelife::MAX_GROUPS] = {};

  // settings
  int m_stepsPerSecond = 60;
  float m_pointSize = 2.0f;
  int m_randomizeSeconds = 60;
  int m_ruleSource = SRC_RANDOM;
  int m_presetSetting = 0;
  int m_numColours = 4;
  bool m_randomColourCount = false;
  bool m_randomPhysics = false;
  float m_userViscosity = 0.5f;
  int m_palette = PAL_CLASSIC;
  int m_style = STYLE_ROUND;
  int m_trails = 0;
  bool m_pulses = false;
  int m_pulseSeconds = 15;

  // rule-set sequencing
  int m_presetIndex = 0;
  bool m_onPreset = false;
  std::vector<int> m_deck; // shuffled preset order, consumed from the back
  float m_hueOffset = 0.0f;

  Clock::time_point m_lastFrame;
  Clock::time_point m_lastRandomize;
  Clock::time_point m_lastPulse;
  double m_accumulator = 0.0;
};

//------------------------------------------------------------------------------

void CScreensaverParticleLife::LoadSettings()
{
  auto& p = m_sim.params;
  p.perColour = kodi::addon::GetSettingInt("particles_per_colour", 1000);
  m_userViscosity = kodi::addon::GetSettingInt("viscosity", 50) / 100.0f;
  p.viscosity = m_userViscosity;
  p.gravity = kodi::addon::GetSettingInt("gravity", 0) / 100.0f;
  p.wallRepel = static_cast<float>(kodi::addon::GetSettingInt("wall_repel", 10));
  p.bounded = kodi::addon::GetSettingBoolean("bounded", false);
  p.evolve = kodi::addon::GetSettingBoolean("evolve", false);
  p.explore = kodi::addon::GetSettingBoolean("explore", false);
  p.symmetric = kodi::addon::GetSettingBoolean("symmetric", false);
  p.forceVariance = kodi::addon::GetSettingInt("force_strength", 80) / 100.0f;
  p.radiusVariance = kodi::addon::GetSettingInt("interaction_range", 60) / 100.0f;

  m_stepsPerSecond = std::max(1, kodi::addon::GetSettingInt("steps_per_second", 60));
  // ~1.7 s between exploration mutations, as in the JS version at 60 fps
  p.explorePeriod = std::max(1, m_stepsPerSecond * 5 / 3);

  m_pointSize = static_cast<float>(kodi::addon::GetSettingInt("point_size", 2));
  m_randomizeSeconds = kodi::addon::GetSettingInt("randomize_interval", 60);
  m_ruleSource = kodi::addon::GetSettingInt("rule_source", SRC_RANDOM);
  m_presetSetting = std::min(std::max(kodi::addon::GetSettingInt("preset", 0), 0),
                             particlelife::kNumPresets - 1);
  m_numColours = std::min(std::max(kodi::addon::GetSettingInt("num_colours", 4), 1),
                          particlelife::MAX_GROUPS);
  m_randomColourCount = kodi::addon::GetSettingBoolean("random_colour_count", false);
  m_randomPhysics = kodi::addon::GetSettingBoolean("random_physics", false);
  m_palette = kodi::addon::GetSettingInt("palette", PAL_CLASSIC);
  m_style = kodi::addon::GetSettingInt("particle_style", STYLE_ROUND);
  m_trails = kodi::addon::GetSettingInt("trails", 0);
  m_pulses = kodi::addon::GetSettingBoolean("pulses", false);
  m_pulseSeconds = std::max(1, kodi::addon::GetSettingInt("pulse_interval", 15));
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

GLuint CScreensaverParticleLife::Link(const char* vsSrc, const char* fsSrc)
{
  GLuint vs = Compile(GL_VERTEX_SHADER, kVertexHeader + vsSrc);
  GLuint fs = Compile(GL_FRAGMENT_SHADER, kFragmentHeader + fsSrc);
  if (!vs || !fs)
  {
    if (vs)
      glDeleteShader(vs);
    if (fs)
      glDeleteShader(fs);
    return 0;
  }

  GLuint program = glCreateProgram();
  glAttachShader(program, vs);
  glAttachShader(program, fs);
  glLinkProgram(program);
  glDeleteShader(vs);
  glDeleteShader(fs);

  GLint ok = 0;
  glGetProgramiv(program, GL_LINK_STATUS, &ok);
  if (!ok)
  {
    char log[1024] = {};
    glGetProgramInfoLog(program, sizeof(log) - 1, nullptr, log);
    kodi::Log(ADDON_LOG_ERROR, "Particle Life: program link failed: %s", log);
    glDeleteProgram(program);
    return 0;
  }
  return program;
}

bool CScreensaverParticleLife::BuildPrograms()
{
  m_program = Link(kPointVertexShader, kPointFragmentShader);
  if (!m_program)
    return false;
  m_aPos = glGetAttribLocation(m_program, "a_pos");
  m_uScale = glGetUniformLocation(m_program, "u_scale");
  m_uPointSize = glGetUniformLocation(m_program, "u_pointSize");
  m_uColor = glGetUniformLocation(m_program, "u_color");
  m_uStyle = glGetUniformLocation(m_program, "u_style");

  if (m_trails > 0)
  {
    m_quadProgram = Link(kQuadVertexShader, kQuadFragmentShader);
    if (m_quadProgram)
    {
      m_qaPos = glGetAttribLocation(m_quadProgram, "a_pos");
      m_quTex = glGetUniformLocation(m_quadProgram, "u_tex");
      m_quKeep = glGetUniformLocation(m_quadProgram, "u_keep");
      m_quSub = glGetUniformLocation(m_quadProgram, "u_sub");
    }
    else
    {
      m_trailsFailed = true; // still show the particles, just without trails
    }
  }
  return true;
}

void CScreensaverParticleLife::RandomRules()
{
  int n = m_numColours;
  if (m_randomColourCount && m_numColours > 2)
    n = m_sim.RandomInt(2, m_numColours);
  m_sim.SetNumGroups(n);
  m_sim.params.viscosity =
      m_randomPhysics ? m_sim.RandomFloat(0.3f, 0.75f) : m_userViscosity;
  m_sim.Randomize();
}

void CScreensaverParticleLife::NextRuleSet(bool first)
{
  using particlelife::kNumPresets;

  auto drawFromDeck = [this]() {
    if (m_deck.empty())
    {
      for (int i = 0; i < kNumPresets; i++)
        m_deck.push_back(i);
      std::shuffle(m_deck.begin(), m_deck.end(), m_sim.rng());
      // don't repeat the preset that is on screen right now
      if (m_deck.size() > 1 && m_deck.back() == m_presetIndex)
        std::swap(m_deck.front(), m_deck.back());
    }
    const int i = m_deck.back();
    m_deck.pop_back();
    return i;
  };

  m_onPreset = m_ruleSource != SRC_RANDOM;
  switch (m_ruleSource)
  {
    case SRC_PRESETS_ORDER:
      m_presetIndex = first ? m_presetSetting : (m_presetIndex + 1) % kNumPresets;
      m_sim.LoadPreset(m_presetIndex);
      break;
    case SRC_PRESETS_SHUFFLE:
      m_presetIndex = drawFromDeck();
      m_sim.LoadPreset(m_presetIndex);
      break;
    case SRC_MIX:
      if (m_sim.RandomFloat(0, 1) < 0.5f)
      {
        m_presetIndex = drawFromDeck();
        m_sim.LoadPreset(m_presetIndex);
      }
      else
      {
        RandomRules();
        m_onPreset = false;
      }
      break;
    case SRC_ONE_PRESET:
      m_presetIndex = m_presetSetting;
      m_sim.LoadPreset(m_presetIndex); // the timer just respawns the particles
      break;
    default:
      RandomRules();
      m_onPreset = false;
      break;
  }

  if (m_onPreset)
    kodi::Log(ADDON_LOG_DEBUG, "Particle Life: preset \"%s\"",
              particlelife::kPresets[m_presetIndex].name);

  m_hueOffset = m_sim.RandomFloat(0, 1);
  UpdateColours();
  m_lastRandomize = Clock::now();
}

void CScreensaverParticleLife::UpdateColours()
{
  const int n = m_sim.numGroups();
  for (int i = 0; i < particlelife::MAX_GROUPS; i++)
  {
    switch (m_palette)
    {
      case PAL_RAINBOW:
        m_colours[i] = Hsv(static_cast<float>(i) / n, 0.85f, 1.0f);
        break;
      case PAL_RANDOM:
        m_colours[i] = Hsv(m_hueOffset + static_cast<float>(i) / n, 0.8f, 1.0f);
        break;
      case PAL_NEON:
      case PAL_PASTEL:
        m_colours[i] = kPalettes[m_palette][i];
        break;
      default:
        m_colours[i] = kPalettes[PAL_CLASSIC][i];
        break;
    }
  }
}

void CScreensaverParticleLife::RandomPulse()
{
  const float aspect = static_cast<float>(Width()) / static_cast<float>(std::max(1, Height()));
  const float vw = kVirtualHeight * aspect;
  const float x = m_sim.RandomFloat(0.15f, 0.85f) * vw;
  const float y = m_sim.RandomFloat(0.15f, 0.85f) * kVirtualHeight;
  // mostly bursts, sometimes an implosion (the JS app's shift-click)
  m_sim.Pulse(x, y, m_sim.RandomFloat(0, 1) < 0.7f ? 10 : -10);
  m_lastPulse = Clock::now();
}

bool CScreensaverParticleLife::EnsureTrailBuffers(int w, int h)
{
  if (m_trailsFailed || !m_quadProgram)
    return false;
  if (m_trailFbo[0] && w == m_trailW && h == m_trailH)
    return true;

  DeleteTrailBuffers();
  GLint prevFbo = 0;
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prevFbo);

  glGenTextures(2, m_trailTex);
  glGenFramebuffers(2, m_trailFbo);
  bool ok = true;
  for (int i = 0; i < 2 && ok; i++)
  {
    glBindTexture(GL_TEXTURE_2D, m_trailTex[i]);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);

    glBindFramebuffer(GL_FRAMEBUFFER, m_trailFbo[i]);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, m_trailTex[i], 0);
    ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    if (ok)
    {
      glViewport(0, 0, w, h);
      glClearColor(0, 0, 0, 1);
      glClear(GL_COLOR_BUFFER_BIT);
    }
  }
  glBindTexture(GL_TEXTURE_2D, 0);
  glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(prevFbo));

  if (!ok)
  {
    kodi::Log(ADDON_LOG_ERROR, "Particle Life: trail framebuffer incomplete; trails disabled");
    DeleteTrailBuffers();
    m_trailsFailed = true;
    return false;
  }
  m_trailW = w;
  m_trailH = h;
  m_trailCur = 0;
  return true;
}

void CScreensaverParticleLife::DeleteTrailBuffers()
{
  if (m_trailFbo[0])
    glDeleteFramebuffers(2, m_trailFbo);
  if (m_trailTex[0])
    glDeleteTextures(2, m_trailTex);
  m_trailFbo[0] = m_trailFbo[1] = 0;
  m_trailTex[0] = m_trailTex[1] = 0;
  m_trailW = m_trailH = 0;
}

bool CScreensaverParticleLife::Start()
{
  LoadSettings();

  if (!BuildPrograms())
    return false;
#ifdef TARGET_DARWIN
  glGenVertexArrays(1, &m_vao);
#endif
  glGenBuffers(1, &m_vbo);
  if (m_quadProgram)
  {
    const float quad[] = {-1, -1, 1, -1, -1, 1, 1, 1};
    glGenBuffers(1, &m_quadVbo);
    glBindBuffer(GL_ARRAY_BUFFER, m_quadVbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
  }

  const float aspect = static_cast<float>(Width()) / static_cast<float>(std::max(1, Height()));
  m_sim.Resize(kVirtualHeight * aspect, kVirtualHeight);
  NextRuleSet(true);

  m_lastFrame = Clock::now();
  m_lastPulse = m_lastFrame;
  m_accumulator = 0.0;
  return true;
}

void CScreensaverParticleLife::Stop()
{
  DeleteTrailBuffers();
  if (m_vbo)
  {
    glDeleteBuffers(1, &m_vbo);
    m_vbo = 0;
  }
  if (m_quadVbo)
  {
    glDeleteBuffers(1, &m_quadVbo);
    m_quadVbo = 0;
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
  if (m_quadProgram)
  {
    glDeleteProgram(m_quadProgram);
    m_quadProgram = 0;
  }
}

void CScreensaverParticleLife::DrawParticles(float vw, float scalePx)
{
  const int n = m_sim.numGroups();

  // gather vertices (group after group)
  size_t total = 0;
  for (int i = 0; i < n; i++)
    total += m_sim.group(i).size();
  m_vertices.resize(total * 2);

  size_t offsets[particlelife::MAX_GROUPS] = {};
  size_t at = 0;
  for (int i = 0; i < n; i++)
  {
    const auto& g = m_sim.group(i);
    offsets[i] = at;
    for (size_t k = 0; k < g.size(); k++, at++)
    {
      m_vertices[at * 2] = g.x[k];
      m_vertices[at * 2 + 1] = g.y[k];
    }
  }

  glEnable(GL_BLEND);
  float size = std::max(1.0f, m_pointSize * scalePx);
  float alpha = 1.0f;
  if (m_style == STYLE_GLOW)
  {
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    size *= 3.0f;
    alpha = 0.6f;
  }
  else
  {
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
  }
#ifdef GL_PROGRAM_POINT_SIZE
  glEnable(GL_PROGRAM_POINT_SIZE); // desktop GL only; ES always honours gl_PointSize
#endif

  glUseProgram(m_program);
  glUniform2f(m_uScale, 2.0f / vw, -2.0f / kVirtualHeight);
  glUniform1f(m_uPointSize, size);
  glUniform1f(m_uStyle, static_cast<float>(m_style));

  glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
  glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(m_vertices.size() * sizeof(float)),
               m_vertices.data(), GL_STREAM_DRAW);
  glEnableVertexAttribArray(static_cast<GLuint>(m_aPos));
  glVertexAttribPointer(static_cast<GLuint>(m_aPos), 2, GL_FLOAT, GL_FALSE, 0, nullptr);

  // Same draw order as the original for its four colours: white, red, green,
  // yellow (later = on top); extra colours go on top of those.
  int order[particlelife::MAX_GROUPS];
  int count = 0;
  for (int idx : {particlelife::WHITE, particlelife::RED, particlelife::GREEN, particlelife::YELLOW})
    if (idx < n)
      order[count++] = idx;
  for (int idx = particlelife::NUM_GROUPS; idx < n; idx++)
    order[count++] = idx;

  for (int c = 0; c < count; c++)
  {
    const int idx = order[c];
    const auto& g = m_sim.group(idx);
    if (g.size() == 0)
      continue;
    glUniform4f(m_uColor, m_colours[idx].r, m_colours[idx].g, m_colours[idx].b, alpha);
    glDrawArrays(GL_POINTS, static_cast<GLint>(offsets[idx]), static_cast<GLsizei>(g.size()));
  }

  glDisableVertexAttribArray(static_cast<GLuint>(m_aPos));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
}

void CScreensaverParticleLife::DrawQuad(GLuint tex, float keep, float sub)
{
  glDisable(GL_BLEND);
  glUseProgram(m_quadProgram);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, tex);
  glUniform1i(m_quTex, 0);
  glUniform1f(m_quKeep, keep);
  glUniform1f(m_quSub, sub);
  glBindBuffer(GL_ARRAY_BUFFER, m_quadVbo);
  glEnableVertexAttribArray(static_cast<GLuint>(m_qaPos));
  glVertexAttribPointer(static_cast<GLuint>(m_qaPos), 2, GL_FLOAT, GL_FALSE, 0, nullptr);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
  glDisableVertexAttribArray(static_cast<GLuint>(m_qaPos));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glBindTexture(GL_TEXTURE_2D, 0);
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
    NextRuleSet(false);

  if (m_pulses && std::chrono::duration<double>(now - m_lastPulse).count() >= m_pulseSeconds)
    RandomPulse();

  // --- draw
  const float aspect = static_cast<float>(Width()) / static_cast<float>(std::max(1, Height()));
  const float vw = kVirtualHeight * aspect;
  const float scalePx = static_cast<float>(Height()) / kVirtualHeight;

  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
#ifdef TARGET_DARWIN
  glBindVertexArray(m_vao);
#endif

  if (m_trails > 0 && EnsureTrailBuffers(Width(), Height()))
  {
    // fade the previous frame into the other buffer, draw the particles on top,
    // then copy that buffer to the screen
    static const float kKeep[] = {1.0f, 0.75f, 0.88f, 0.94f};
    const float keep = kKeep[std::min(std::max(m_trails, 1), 3)];

    GLint screenFbo = 0;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &screenFbo);
    const GLboolean scissor = glIsEnabled(GL_SCISSOR_TEST);
    glDisable(GL_SCISSOR_TEST);

    const int prev = m_trailCur;
    const int cur = 1 - m_trailCur;
    glBindFramebuffer(GL_FRAMEBUFFER, m_trailFbo[cur]);
    glViewport(0, 0, m_trailW, m_trailH);
    DrawQuad(m_trailTex[prev], keep, 1.5f / 255.0f);
    DrawParticles(vw, scalePx);

    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(screenFbo));
    if (scissor)
      glEnable(GL_SCISSOR_TEST);
    glViewport(X(), Y(), Width(), Height());
    DrawQuad(m_trailTex[cur], 1.0f, 0.0f);
    m_trailCur = cur;
  }
  else
  {
    glViewport(X(), Y(), Width(), Height());
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    DrawParticles(vw, scalePx);
  }

  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif
  glUseProgram(0);
}

ADDONCREATOR(CScreensaverParticleLife)

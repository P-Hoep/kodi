// Kodi screensaver wrapper around the Alien Life world (Alien.h).
//
// As in Emergence and Physarum v2, the world steps on a driver thread of its
// own plus a small worker pool, one step ahead of the picture, so Render()
// never waits: when a step has finished, Render() uploads the vertex stream
// the driver built for it and kicks off the next step. New worlds are set up
// by the driver thread too, behind a fade to black.
//
// Drawing is plain OpenGL / OpenGL ES 2 (GLSL 1.00 style shaders): one vertex
// buffer (12 bytes a vertex: position + packed RGBA, alpha = sprite size)
// holds the connections as lines, then the energy particles and cells as
// glowing point sprites; the radiation sources are a few soft quads behind
// them. Motion trails use a pair of off-screen buffers that fade each frame.

#include "Alien.h"

#include <kodi/addon-instance/Screensaver.h>
#include <kodi/gui/gl/GL.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <vector>

#if !defined(HAS_GLES) && !defined(GL_PROGRAM_POINT_SIZE)
#define GL_PROGRAM_POINT_SIZE 0x8642
#endif

namespace
{

// Kodi uses a GL 3.2 core context on macOS (no `attribute`, `varying`,
// `texture2D`, `gl_FragColor`; a VAO must be bound); Linux Kodi runs GL 2.1;
// GLES 2 takes the shader bodies as they are.
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

// Cells, energy particles (points) and connections (lines). Alpha carries the
// sprite size (1.0 = 128).
const char* kSpriteVertexShader = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;      // clip space
attribute vec4 a_col;
uniform float u_pointSize;
uniform float u_fade;
varying vec3 v_col;
void main()
{
  gl_Position = vec4(a_pos, 0.0, 1.0);
  gl_PointSize = u_pointSize * a_col.a * 1.9921875;
  v_col = a_col.rgb * u_fade;
}
)";

// u_points: 0 = lines (flat, alpha u_lineAlpha), 1 = cells: a bright disc
// with a soft halo, as ALIEN draws its cells
const char* kSpriteFragmentShader = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform float u_points;
uniform float u_lineAlpha;
uniform float u_halo;
varying vec3 v_col;
void main()
{
  if (u_points < 0.5)
  {
    gl_FragColor = vec4(v_col, u_lineAlpha);
    return;
  }
  vec2 c = gl_PointCoord - vec2(0.5);
  float d2 = dot(c, c) * 4.0;  // 0 centre, 1 edge of the sprite
  if (d2 > 1.0)
    discard;
  float disc = 1.0 - smoothstep(0.16, 0.26, d2);
  float halo = exp(-d2 * 5.0) * u_halo;
  float a = max(disc * 0.95, halo);
  gl_FragColor = vec4(mix(v_col, vec3(1.0), disc * 0.18), a);
}
)";

// The radiation sources: soft radial glows on a quad.
const char* kGlowVertexShader = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;
attribute vec2 a_uv;
varying vec2 v_uv;
void main()
{
  gl_Position = vec4(a_pos, 0.0, 1.0);
  v_uv = a_uv;
}
)";

const char* kGlowFragmentShader = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform vec3 u_col;
varying vec2 v_uv;
void main()
{
  float d2 = dot(v_uv, v_uv);
  float a = exp(-d2 * 4.0) * (1.0 - smoothstep(0.7, 1.0, d2));
  gl_FragColor = vec4(u_col * a, 1.0);
}
)";

// Trails: out = max(prev * keep - sub, 0); with keep = brightness and sub 0
// it also copies the trail buffer to the screen.
const char* kFadeVertexShader = R"(
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

const char* kFadeFragmentShader = R"(
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

constexpr double kFadeSeconds = 2.5;

enum WorldSetting { WS_RANDOM = 0 }; // then 1 + alien::WorldKind
enum ColourMode { COL_GENOME, COL_TYPE, COL_LINEAGE, COL_ENERGY };
enum Pace { PACE_NORMAL, PACE_FAST, PACE_SLOW };

struct Vertex
{
  float x, y;
  uint32_t rgba; // bytes r, g, b, a in memory order; a = sprite size
};

struct GlowVertex
{
  float x, y, u, v;
};

struct RGB
{
  float r, g, b;
};

inline uint32_t Pack(float r, float g, float b, float a)
{
  auto c = [](float v) { return static_cast<uint32_t>(std::min(std::max(v, 0.0f), 1.0f) * 255.0f + 0.5f); };
  return c(r) | (c(g) << 8) | (c(b) << 16) | (c(a) << 24);
}

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

// ALIEN's seven cell colours (its default customisation colours, softened)
const RGB kGenomeColours[alien::NUM_COLOURS] = {{0.25f, 0.45f, 1.0f}, {0.70f, 0.35f, 1.0f}, {1.0f, 0.35f, 0.75f},
                                                {1.0f, 0.30f, 0.25f}, {1.0f, 0.62f, 0.25f}, {0.95f, 0.95f, 0.35f},
                                                {0.40f, 1.0f, 0.45f}};

// base, sensor, muscle, generator, attacker, digestor, defender
const RGB kTypeColours[alien::CT_COUNT] = {{0.55f, 0.62f, 0.80f}, {1.0f, 0.90f, 0.30f}, {1.0f, 0.38f, 0.50f},
                                           {0.30f, 0.90f, 1.0f},  {1.0f, 0.45f, 0.12f}, {0.40f, 1.0f, 0.45f},
                                           {0.72f, 0.48f, 1.0f}};

// sprite size per cell type (alpha byte, 128 = 1.0)
const float kTypeSize[alien::CT_COUNT] = {0.92f, 1.05f, 1.0f, 1.0f, 1.08f, 1.08f, 1.04f};

} // namespace

class ATTR_DLL_LOCAL CScreensaverAlienLife : public kodi::addon::CAddonBase, public kodi::addon::CInstanceScreensaver
{
public:
  CScreensaverAlienLife() = default;
  ~CScreensaverAlienLife() override { StopSimulation(); }

  bool Start() override;
  void Stop() override;
  void Render() override;

private:
  using Clock = std::chrono::steady_clock;

  void LoadSettings();
  GLuint Compile(GLenum type, const std::string& src);
  GLuint Link(const char* vs, const char* fs);
  bool BuildPrograms();
  void BeginWorld();
  void BuildVertices();
  void DriverLoop();
  void StopSimulation();
  void UploadFrame();
  void DrawScene(float fade);
  void DrawQuad(GLint aPos);
  bool EnsureTrailBuffers(int w, int h);
  void DeleteTrailBuffers();

  alien::World m_world;
  alien::WorkerPool m_pool;
  std::mt19937 m_rng{std::random_device{}()};

  // the driver thread: set up a new world (if asked) and run m_kick steps
  std::thread m_driver;
  std::mutex m_mutex;
  std::condition_variable m_cv;
  int m_kick = 0;
  bool m_beginWorld = false;
  bool m_busy = false;
  bool m_fresh = false;
  bool m_quit = false;
  unsigned m_serial = 0;  // bumped by every new world (guarded by m_mutex)
  double m_stepMs = 0.0;  // guarded by m_mutex
  long m_stepCount = 0;

  // written by the driver thread while busy, read by Render while not
  std::vector<Vertex> m_vertices;
  std::vector<GlowVertex> m_glowVerts;
  std::vector<RGB> m_cellColour;
  size_t m_numLines = 0, m_numPoints = 0;
  int m_worldKind = 0;
  // what was uploaded, for drawing (render thread only)
  size_t m_drawLines = 0, m_drawPoints = 0, m_drawGlow = 0;
  unsigned m_drawSerial = ~0u;

  // GL
  GLuint m_spriteProgram = 0, m_glowProgram = 0, m_fadeProgram = 0;
  GLint m_saPos = -1, m_saCol = -1, m_suPointSize = -1, m_suFade = -1, m_suPoints = -1, m_suLineAlpha = -1,
        m_suHalo = -1;
  GLint m_gaPos = -1, m_gaUv = -1, m_guCol = -1;
  GLint m_faPos = -1, m_fuTex = -1, m_fuKeep = -1, m_fuSub = -1;
  GLuint m_vbo = 0, m_glowVbo = 0, m_quadVbo = 0, m_vao = 0;
  float m_maxPointSize = 64.0f;
  GLuint m_fadeTex[2] = {0, 0}, m_fadeFbo[2] = {0, 0};
  int m_fadeW = 0, m_fadeH = 0, m_fadeCur = 0;
  bool m_fadeFailed = false;

  // settings
  alien::Params m_params;
  int m_worldSetting = WS_RANDOM;
  int m_worldMinutes = 20;
  int m_colourMode = COL_GENOME;
  float m_cellSize = 1.0f;
  bool m_glow = true;
  bool m_connections = true;
  bool m_showParticles = true;
  bool m_sourceGlow = true;
  int m_trails = 0;
  float m_dim = 0.0f;
  int m_pace = PACE_NORMAL;
  int m_threads = 0;
  float m_aspect = 16.0f / 9.0f;

  // world sequencing (render thread)
  bool m_switching = false;  // fading out to start a new world
  bool m_requested = false;  // the new world has been asked of the driver
  Clock::time_point m_worldStart, m_switchStart, m_statsStart, m_lastFrame;
  double m_credit = 0.0;
  long m_frames = 0;
  bool m_loggedStats = false;
};

//------------------------------------------------------------------------------

void CScreensaverAlienLife::LoadSettings()
{
  using kodi::addon::GetSettingBoolean;
  using kodi::addon::GetSettingInt;
  // detail: small (TV sticks), medium, large (keep in step with tests/sim_test.cpp)
  static const float kHeight[] = {110.0f, 150.0f, 200.0f};
  static const int kCells[] = {3500, 7000, 14000};
  static const int kParticles[] = {2500, 4000, 7000};
  static const int kFounders[] = {70, 120, 220};
  const int detail = std::min(std::max(GetSettingInt("detail", 1), 0), 2);
  m_params.worldHeight = kHeight[detail];
  m_params.maxCells = kCells[detail];
  m_params.maxParticles = kParticles[detail];
  m_params.initialCreatures = kFounders[detail];

  m_worldSetting = std::min(std::max(GetSettingInt("world", WS_RANDOM), 0), static_cast<int>(alien::WORLD_COUNT));
  m_params.energy = std::min(std::max(GetSettingInt("energy", 100), 25), 300) / 100.0f;
  static const float kMutation[] = {0.0f, 0.35f, 1.0f, 2.5f};
  m_params.mutation = kMutation[std::min(std::max(GetSettingInt("mutation", 2), 0), 3)];
  m_params.sources = std::min(std::max(GetSettingInt("sources", 3), 1), 5);
  m_params.muscle = std::min(std::max(GetSettingInt("muscle", 100), 25), 300) / 100.0f;
  m_worldMinutes = std::min(std::max(GetSettingInt("world_minutes", 20), 0), 240);

  m_colourMode = std::min(std::max(GetSettingInt("colour", COL_GENOME), 0), 3);
  m_cellSize = std::min(std::max(GetSettingInt("cell_size", 100), 25), 300) / 100.0f;
  m_glow = GetSettingBoolean("glow", true);
  m_connections = GetSettingBoolean("connections", true);
  m_showParticles = GetSettingBoolean("particles", true);
  m_sourceGlow = GetSettingBoolean("source_glow", true);
  m_trails = std::min(std::max(GetSettingInt("trails", 0), 0), 3);
  m_dim = std::min(std::max(GetSettingInt("dim", 0), 0), 90) / 100.0f;

  m_pace = std::min(std::max(GetSettingInt("pace", PACE_NORMAL), 0), 2);
  m_threads = std::min(std::max(GetSettingInt("threads", 0), 0), 4);
}

GLuint CScreensaverAlienLife::Compile(GLenum type, const std::string& src)
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
    kodi::Log(ADDON_LOG_ERROR, "Alien Life: shader compile failed: %s", log);
    glDeleteShader(shader);
    return 0;
  }
  return shader;
}

GLuint CScreensaverAlienLife::Link(const char* vsSrc, const char* fsSrc)
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
    kodi::Log(ADDON_LOG_ERROR, "Alien Life: program link failed: %s", log);
    glDeleteProgram(program);
    return 0;
  }
  return program;
}

bool CScreensaverAlienLife::BuildPrograms()
{
  m_spriteProgram = Link(kSpriteVertexShader, kSpriteFragmentShader);
  if (!m_spriteProgram)
    return false;
  m_saPos = glGetAttribLocation(m_spriteProgram, "a_pos");
  m_saCol = glGetAttribLocation(m_spriteProgram, "a_col");
  m_suPointSize = glGetUniformLocation(m_spriteProgram, "u_pointSize");
  m_suFade = glGetUniformLocation(m_spriteProgram, "u_fade");
  m_suPoints = glGetUniformLocation(m_spriteProgram, "u_points");
  m_suLineAlpha = glGetUniformLocation(m_spriteProgram, "u_lineAlpha");
  m_suHalo = glGetUniformLocation(m_spriteProgram, "u_halo");

  // optional extras: without them the sources and trails are skipped
  m_glowProgram = Link(kGlowVertexShader, kGlowFragmentShader);
  if (m_glowProgram)
  {
    m_gaPos = glGetAttribLocation(m_glowProgram, "a_pos");
    m_gaUv = glGetAttribLocation(m_glowProgram, "a_uv");
    m_guCol = glGetUniformLocation(m_glowProgram, "u_col");
  }
  m_fadeProgram = Link(kFadeVertexShader, kFadeFragmentShader);
  if (m_fadeProgram)
  {
    m_faPos = glGetAttribLocation(m_fadeProgram, "a_pos");
    m_fuTex = glGetUniformLocation(m_fadeProgram, "u_tex");
    m_fuKeep = glGetUniformLocation(m_fadeProgram, "u_keep");
    m_fuSub = glGetUniformLocation(m_fadeProgram, "u_sub");
  }
  else
    m_fadeFailed = true;
  return true;
}

// Driver thread (or Start, before it runs): a new world.
void CScreensaverAlienLife::BeginWorld()
{
  alien::Params p = m_params;
  p.world = m_worldSetting == WS_RANDOM ? static_cast<int>(m_rng() % alien::WORLD_COUNT) : m_worldSetting - 1;
  m_worldKind = p.world;
  m_world.Reset(m_aspect, p, m_rng());
}

// Driver thread: the vertex stream for the step just done. Connections
// first (lines), then particles and cells (points).
void CScreensaverAlienLife::BuildVertices()
{
  const alien::World& w = m_world;
  const size_t cap = w.capacity();
  const float sx = 2.0f / w.width(), sy = -2.0f / w.height();
  const float halfW = 0.5f * w.width(), halfH = 0.5f * w.height();
  const float* X = w.x();
  const float* Y = w.y();
  const uint8_t* S = w.state();
  const uint8_t* T = w.type();
  const uint8_t* C = w.colour();
  const uint8_t* F = w.flash();
  const uint16_t* TM = w.timer();
  const int* CR = w.creatureOf();

  m_vertices.resize(cap * alien::MAX_BONDS + cap + static_cast<size_t>(w.numParticles()));
  Vertex* out = m_vertices.data();

  // per-cell colour, computed once and reused by the connections
  m_cellColour.resize(cap);
  for (size_t i = 0; i < cap; i++)
  {
    if (S[i] == alien::CS_FREE)
      continue;
    RGB c;
    float k;
    if (S[i] == alien::CS_DYING)
    {
      // a dead cell greys and fades as it falls apart
      const RGB base = kGenomeColours[C[i]];
      const float t = std::min(TM[i] / 150.0f, 1.0f);
      c = {0.35f + base.r * 0.25f, 0.33f + base.g * 0.25f, 0.33f + base.b * 0.25f};
      k = 0.15f + 0.45f * t;
    }
    else
    {
      const float vig = w.Vigour(static_cast<int>(i));
      switch (m_colourMode)
      {
        case COL_TYPE:
          c = kTypeColours[T[i]];
          break;
        case COL_LINEAGE:
        {
          const int cr = CR[i];
          const uint32_t lin = cr >= 0 ? w.creature(cr).g.lineage : 0;
          c = Hsv(static_cast<float>(alien::Hash(lin * 2654435761u) >> 8) / 16777216.0f, 0.7f, 1.0f);
          break;
        }
        case COL_ENERGY:
          // hungry = deep blue, fed = green, ready to breed = hot white
          c = vig < 0.5f ? RGB{0.15f, 0.25f + vig * 1.2f, 1.0f - vig}
                         : RGB{0.3f + (vig - 0.5f) * 1.4f, 0.85f + (vig - 0.5f) * 0.3f, 0.5f + (vig - 0.5f) * 0.9f};
          break;
        default:
          c = kGenomeColours[C[i]];
          break;
      }
      k = m_colourMode == COL_ENERGY ? 0.9f : 0.62f + 0.38f * vig;
    }
    const float f = F[i] / 255.0f; // eating, attacking and being built light a cell up
    m_cellColour[i] = {std::min(c.r * k + f * 0.5f, 1.0f), std::min(c.g * k + f * 0.5f, 1.0f),
                       std::min(c.b * k + f * 0.5f, 1.0f)};
  }

  if (m_connections)
  {
    const uint8_t* BN = w.bondCount();
    const int* BT = w.bondTo();
    for (size_t i = 0; i < cap; i++)
    {
      if (S[i] == alien::CS_FREE)
        continue;
      for (int s = 0; s < BN[i]; s++)
      {
        const int j = BT[i * alien::MAX_BONDS + s];
        if (static_cast<size_t>(j) < i)
          continue;
        // a connection across the wrap is not drawn
        if (std::fabs(X[j] - X[i]) > halfW || std::fabs(Y[j] - Y[i]) > halfH)
          continue;
        const RGB& a = m_cellColour[i];
        const RGB& b = m_cellColour[static_cast<size_t>(j)];
        *out++ = {X[i] * sx - 1.0f, Y[i] * sy + 1.0f, Pack(a.r, a.g, a.b, 0.5f)};
        *out++ = {X[j] * sx - 1.0f, Y[j] * sy + 1.0f, Pack(b.r, b.g, b.b, 0.5f)};
      }
    }
  }
  m_numLines = static_cast<size_t>(out - m_vertices.data());

  if (m_showParticles)
  {
    const float* PX = w.px();
    const float* PY = w.py();
    const float* PE = w.pe();
    const int* PA = w.page();
    const float life = static_cast<float>(w.k.particleLife);
    const float full = 1.0f / w.k.particleEnergy;
    for (int i = 0; i < w.numParticles(); i++)
    {
      // warm sparks that dim as they age
      const float e = std::min(PE[i] * full, 1.5f);
      const float age = 1.0f - 0.6f * std::min(PA[i] / life, 1.0f);
      const float b = (0.28f + 0.18f * e) * age;
      *out++ = {PX[i] * sx - 1.0f, PY[i] * sy + 1.0f, Pack(b, b * 0.82f, b * 0.5f, 0.11f + 0.03f * e)};
    }
  }
  for (size_t i = 0; i < cap; i++)
  {
    if (S[i] == alien::CS_FREE)
      continue;
    const RGB& c = m_cellColour[i];
    const float size = S[i] == alien::CS_DYING ? 0.4f : 0.5f * kTypeSize[T[i]];
    *out++ = {X[i] * sx - 1.0f, Y[i] * sy + 1.0f, Pack(c.r, c.g, c.b, size)};
  }
  m_numPoints = static_cast<size_t>(out - m_vertices.data()) - m_numLines;

  // radiation sources: a soft glow each, repeated across the wrap where it
  // reaches over an edge
  m_glowVerts.clear();
  if (m_sourceGlow)
  {
    const float r = 0.22f * w.height();
    for (int s = 0; s < w.numSources(); s++)
    {
      const alien::Source& q = w.source(s);
      for (int oy = -1; oy <= 1; oy++)
        for (int ox = -1; ox <= 1; ox++)
        {
          const float cx = q.x + ox * w.width(), cy = q.y + oy * w.height();
          if (cx + r < 0 || cx - r > w.width() || cy + r < 0 || cy - r > w.height())
            continue;
          const float x0 = (cx - r) * sx - 1.0f, x1 = (cx + r) * sx - 1.0f;
          const float y0 = (cy - r) * sy + 1.0f, y1 = (cy + r) * sy + 1.0f;
          const GlowVertex quad[6] = {{x0, y0, -1, -1}, {x1, y0, 1, -1}, {x0, y1, -1, 1},
                                      {x1, y0, 1, -1},  {x1, y1, 1, 1},  {x0, y1, -1, 1}};
          m_glowVerts.insert(m_glowVerts.end(), quad, quad + 6);
        }
    }
  }
}

void CScreensaverAlienLife::DriverLoop()
{
  std::unique_lock<std::mutex> lock(m_mutex);
  for (;;)
  {
    m_cv.wait(lock, [this] { return m_quit || m_kick > 0 || m_beginWorld; });
    if (m_quit)
      return;
    const int n = m_kick;
    const bool begin = m_beginWorld;
    m_kick = 0;
    m_beginWorld = false;
    lock.unlock();

    if (begin)
      BeginWorld();
    const auto t0 = Clock::now();
    for (int i = 0; i < n; i++)
      m_world.Step(m_pool);
    const double ms = std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
    BuildVertices();

    lock.lock();
    if (begin)
      m_serial++;
    m_stepMs += ms;
    m_stepCount += n;
    m_busy = false;
    m_fresh = true;
  }
}

void CScreensaverAlienLife::StopSimulation()
{
  if (m_driver.joinable())
  {
    {
      std::lock_guard<std::mutex> lock(m_mutex);
      m_quit = true;
    }
    m_cv.notify_all();
    m_driver.join();
  }
  m_pool.Stop();
}

bool CScreensaverAlienLife::Start()
{
  LoadSettings();
  if (!BuildPrograms())
    return false;

#ifdef TARGET_DARWIN
  glGenVertexArrays(1, &m_vao);
#else
  GLfloat range[2] = {1.0f, 64.0f};
  glGetFloatv(GL_ALIASED_POINT_SIZE_RANGE, range);
  m_maxPointSize = std::max(range[1], 1.0f);
#endif
  const float quad[] = {-1, -1, 1, -1, -1, 1, 1, 1};
  glGenBuffers(1, &m_quadVbo);
  glBindBuffer(GL_ARRAY_BUFFER, m_quadVbo);
  glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glGenBuffers(1, &m_vbo);
  glGenBuffers(1, &m_glowVbo);

  m_aspect = static_cast<float>(Width()) / static_cast<float>(std::max(1, Height()));

  // the first world is set up here, before the driver thread exists
  BeginWorld();
  m_world.Step();
  BuildVertices();
  m_serial = 1;
  m_drawSerial = ~0u;
  m_fresh = true;

  int threads = m_threads;
  if (threads == 0)
  {
    // one core stays with Kodi's render thread; the rest simulate (up to 4)
    const unsigned hw = std::thread::hardware_concurrency();
    threads = std::min(std::max(static_cast<int>(hw) - 1, 1), 4);
  }
  m_pool.Start(threads);
  m_quit = false;
  m_busy = false;
  m_kick = 0;
  m_beginWorld = false;
  m_stepMs = 0;
  m_stepCount = 0;
  m_driver = std::thread([this] { DriverLoop(); });

  m_statsStart = m_lastFrame = m_worldStart = Clock::now();
  m_switching = m_requested = false;
  m_credit = 1.0;
  m_frames = 0;
  m_loggedStats = false;
  static const char* kNames[] = {"Grazers", "Grazers and hunters", "Primordial soup"};
  kodi::Log(ADDON_LOG_INFO, "Alien Life: %.0f x %.0f world, %d cells max, %d thread(s), first world %s",
            m_world.width(), m_world.height(), m_params.maxCells, m_pool.threads(), kNames[m_worldKind]);
  return true;
}

void CScreensaverAlienLife::Stop()
{
  StopSimulation();
  DeleteTrailBuffers();
  for (GLuint* b : {&m_vbo, &m_glowVbo, &m_quadVbo})
  {
    if (*b)
      glDeleteBuffers(1, b);
    *b = 0;
  }
#ifdef TARGET_DARWIN
  if (m_vao)
    glDeleteVertexArrays(1, &m_vao);
  m_vao = 0;
#endif
  for (GLuint* p : {&m_spriteProgram, &m_glowProgram, &m_fadeProgram})
  {
    if (*p)
      glDeleteProgram(*p);
    *p = 0;
  }
}

// Render thread, while the driver is idle: hand the GPU the last step.
void CScreensaverAlienLife::UploadFrame()
{
  glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
  glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>((m_numLines + m_numPoints) * sizeof(Vertex)),
               m_vertices.data(), GL_STREAM_DRAW);
  m_drawLines = m_numLines;
  m_drawPoints = m_numPoints;
  glBindBuffer(GL_ARRAY_BUFFER, m_glowVbo);
  glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(m_glowVerts.size() * sizeof(GlowVertex)),
               m_glowVerts.empty() ? nullptr : m_glowVerts.data(), GL_STREAM_DRAW);
  m_drawGlow = m_glowVerts.size();
  glBindBuffer(GL_ARRAY_BUFFER, 0);
}

void CScreensaverAlienLife::DrawQuad(GLint aPos)
{
  glBindBuffer(GL_ARRAY_BUFFER, m_quadVbo);
  glEnableVertexAttribArray(static_cast<GLuint>(aPos));
  glVertexAttribPointer(static_cast<GLuint>(aPos), 2, GL_FLOAT, GL_FALSE, 0, nullptr);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
  glDisableVertexAttribArray(static_cast<GLuint>(aPos));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
}

// Sources, connections, then particles and cells, all into the bound target.
void CScreensaverAlienLife::DrawScene(float fade)
{
  glEnable(GL_BLEND);

  if (m_drawGlow > 0 && m_glowProgram)
  {
    glBlendFunc(GL_ONE, GL_ONE);
    glUseProgram(m_glowProgram);
    // a faint blue-violet nebula round each radiation source
    glUniform3f(m_guCol, 0.10f * fade, 0.09f * fade, 0.20f * fade);
    glBindBuffer(GL_ARRAY_BUFFER, m_glowVbo);
    glEnableVertexAttribArray(static_cast<GLuint>(m_gaPos));
    glVertexAttribPointer(static_cast<GLuint>(m_gaPos), 2, GL_FLOAT, GL_FALSE, sizeof(GlowVertex), nullptr);
    if (m_gaUv >= 0)
    {
      glEnableVertexAttribArray(static_cast<GLuint>(m_gaUv));
      glVertexAttribPointer(static_cast<GLuint>(m_gaUv), 2, GL_FLOAT, GL_FALSE, sizeof(GlowVertex),
                            reinterpret_cast<const void*>(2 * sizeof(float)));
    }
    glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(m_drawGlow));
    glDisableVertexAttribArray(static_cast<GLuint>(m_gaPos));
    if (m_gaUv >= 0)
      glDisableVertexAttribArray(static_cast<GLuint>(m_gaUv));
  }

  if (m_glow)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
  else
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
#ifdef GL_PROGRAM_POINT_SIZE
  glEnable(GL_PROGRAM_POINT_SIZE);
#endif
  const float pxPerUnit = static_cast<float>(Height()) / m_world.height();
  glUseProgram(m_spriteProgram);
  // a 0.5-size cell's disc is one world unit across; the sprite reaches out
  // twice as far for the halo
  glUniform1f(m_suPointSize, std::min(std::max(4.0f * m_cellSize * pxPerUnit, 2.0f), m_maxPointSize));
  glUniform1f(m_suFade, fade);
  glUniform1f(m_suLineAlpha, m_glow ? 0.55f : 0.8f);
  glUniform1f(m_suHalo, m_glow ? 0.32f : 0.0f);
  glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
  glEnableVertexAttribArray(static_cast<GLuint>(m_saPos));
  glVertexAttribPointer(static_cast<GLuint>(m_saPos), 2, GL_FLOAT, GL_FALSE, sizeof(Vertex), nullptr);
  if (m_saCol >= 0)
  {
    glEnableVertexAttribArray(static_cast<GLuint>(m_saCol));
    glVertexAttribPointer(static_cast<GLuint>(m_saCol), 4, GL_UNSIGNED_BYTE, GL_TRUE, sizeof(Vertex),
                          reinterpret_cast<const void*>(2 * sizeof(float)));
  }
  if (m_drawLines > 0)
  {
    glUniform1f(m_suPoints, 0.0f);
    glDrawArrays(GL_LINES, 0, static_cast<GLsizei>(m_drawLines));
  }
  if (m_drawPoints > 0)
  {
    glUniform1f(m_suPoints, 1.0f);
    glDrawArrays(GL_POINTS, static_cast<GLint>(m_drawLines), static_cast<GLsizei>(m_drawPoints));
  }
  glDisableVertexAttribArray(static_cast<GLuint>(m_saPos));
  if (m_saCol >= 0)
    glDisableVertexAttribArray(static_cast<GLuint>(m_saCol));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
}

bool CScreensaverAlienLife::EnsureTrailBuffers(int w, int h)
{
  if (m_fadeFailed || !m_fadeProgram)
    return false;
  if (m_fadeFbo[0] && w == m_fadeW && h == m_fadeH)
    return true;

  DeleteTrailBuffers();
  GLint prevFbo = 0;
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prevFbo);
  glGenTextures(2, m_fadeTex);
  glGenFramebuffers(2, m_fadeFbo);
  bool ok = true;
  for (int i = 0; i < 2 && ok; i++)
  {
    glBindTexture(GL_TEXTURE_2D, m_fadeTex[i]);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    glBindFramebuffer(GL_FRAMEBUFFER, m_fadeFbo[i]);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, m_fadeTex[i], 0);
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
    kodi::Log(ADDON_LOG_ERROR, "Alien Life: trail framebuffer incomplete; trails disabled");
    DeleteTrailBuffers();
    m_fadeFailed = true;
    return false;
  }
  m_fadeW = w;
  m_fadeH = h;
  m_fadeCur = 0;
  return true;
}

void CScreensaverAlienLife::DeleteTrailBuffers()
{
  if (m_fadeFbo[0])
    glDeleteFramebuffers(2, m_fadeFbo);
  if (m_fadeTex[0])
    glDeleteTextures(2, m_fadeTex);
  m_fadeFbo[0] = m_fadeFbo[1] = 0;
  m_fadeTex[0] = m_fadeTex[1] = 0;
  m_fadeW = m_fadeH = 0;
}

void CScreensaverAlienLife::Render()
{
  if (!m_spriteProgram)
    return;
  const auto now = Clock::now();
  const double frameDt = std::chrono::duration<double>(now - m_lastFrame).count();
  m_lastFrame = now;
  m_frames++;

  // --- worlds: after the world's time, fade out, start a new one, fade in
  const double worldAge = std::chrono::duration<double>(now - m_worldStart).count();
  if (!m_switching && m_worldMinutes > 0 && worldAge >= m_worldMinutes * 60.0)
  {
    m_switching = true;
    m_requested = false;
    m_switchStart = now;
  }
  float fade = static_cast<float>(std::min(1.0, worldAge / kFadeSeconds));
  if (m_switching)
    fade = static_cast<float>(
        std::max(0.0, 1.0 - std::chrono::duration<double>(now - m_switchStart).count() / kFadeSeconds));

  // --- simulation: if the last step is done, show it and start the next
  bool busy, fresh;
  unsigned serial;
  {
    std::lock_guard<std::mutex> lock(m_mutex);
    busy = m_busy;
    fresh = m_fresh;
    serial = m_serial;
    m_fresh = false;
  }
  static const double kRate[] = {60.0, 120.0, 30.0}; // steps a second per Pace
  m_credit = std::min(m_credit + kRate[m_pace] * std::min(frameDt, 0.1), m_pace == PACE_FAST ? 3.0 : 1.5);
  if (!busy)
  {
    if (serial != m_drawSerial)
    {
      if (m_requested) // the new world is in: start its clock and fade in
      {
        m_switching = m_requested = false;
        m_worldStart = now;
        fade = 0.0f;
        if (m_fadeFbo[0])
          DeleteTrailBuffers(); // no ghost of the last world
        static const char* kNames[] = {"Grazers", "Grazers and hunters", "Primordial soup"};
        kodi::Log(ADDON_LOG_INFO, "Alien Life: new world, %s", kNames[m_worldKind]);
      }
      m_drawSerial = serial;
    }
    if (fresh)
      UploadFrame();

    bool begin = false;
    if (m_switching && !m_requested && fade <= 0.0f)
    {
      begin = true;
      m_requested = true;
    }
    // Steps are earned at the chosen rate and spent whenever the simulation
    // is free: the same speed on any refresh rate, and a box that cannot keep
    // up slows down instead of piling up a backlog.
    const int steps = m_requested && !begin ? 0 : std::min(static_cast<int>(m_credit), m_pace == PACE_FAST ? 2 : 1);
    if (steps > 0 || begin)
    {
      m_credit -= steps;
      {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_kick = std::max(steps, 1);
        m_beginWorld = begin;
        m_busy = true;
      }
      m_cv.notify_one();
    }
  }

  // one line in the log after 20 s, to check a box keeps up
  const double statsAge = std::chrono::duration<double>(now - m_statsStart).count();
  if (!m_loggedStats && statsAge > 20.0)
  {
    double ms;
    long count;
    {
      std::lock_guard<std::mutex> lock(m_mutex);
      ms = m_stepMs;
      count = m_stepCount;
    }
    if (count > 0)
      kodi::Log(ADDON_LOG_INFO,
                "Alien Life: %.2f ms per step, %.1f steps/s, %.1f frames/s (%zu vertices, %d thread(s))",
                ms / count, count / statsAge, m_frames / statsAge, m_drawLines + m_drawPoints, m_pool.threads());
    m_loggedStats = true;
  }

  // --- draw
  fade = fade * fade * (3.0f - 2.0f * fade);
  const float bright = fade * (1.0f - m_dim);
  const bool pending = m_requested; // the world may be mid-reset: draw nothing of it

  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
#ifdef TARGET_DARWIN
  glBindVertexArray(m_vao);
#endif

  if (!pending && m_trails > 0 && EnsureTrailBuffers(Width(), Height()))
  {
    static const float kKeep[] = {1.0f, 0.80f, 0.89f, 0.945f};
    GLint screenFbo = 0;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &screenFbo);
    const GLboolean scissor = glIsEnabled(GL_SCISSOR_TEST);
    glDisable(GL_SCISSOR_TEST);

    const int prev = m_fadeCur, cur = 1 - m_fadeCur;
    glBindFramebuffer(GL_FRAMEBUFFER, m_fadeFbo[cur]);
    glViewport(0, 0, m_fadeW, m_fadeH);
    glDisable(GL_BLEND);
    glUseProgram(m_fadeProgram);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, m_fadeTex[prev]);
    glUniform1i(m_fuTex, 0);
    glUniform1f(m_fuKeep, kKeep[m_trails]);
    glUniform1f(m_fuSub, 1.5f / 255.0f);
    DrawQuad(m_faPos);
    glBindTexture(GL_TEXTURE_2D, 0);
    DrawScene(1.0f);

    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(screenFbo));
    if (scissor)
      glEnable(GL_SCISSOR_TEST);
    glViewport(X(), Y(), Width(), Height());
    glDisable(GL_BLEND);
    glUseProgram(m_fadeProgram);
    glBindTexture(GL_TEXTURE_2D, m_fadeTex[cur]);
    glUniform1f(m_fuKeep, bright);
    glUniform1f(m_fuSub, 0.0f);
    DrawQuad(m_faPos);
    glBindTexture(GL_TEXTURE_2D, 0);
    m_fadeCur = cur;
  }
  else
  {
    glViewport(X(), Y(), Width(), Height());
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    if (!pending)
      DrawScene(bright);
  }

  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif
  glUseProgram(0);
}

ADDONCREATOR(CScreensaverAlienLife)

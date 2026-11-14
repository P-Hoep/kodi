// Kodi screensaver wrapper around the boids simulation.
// Renders with plain OpenGL / OpenGL ES 2 (GLSL 1.00 style shaders): the
// whole flock is one vertex stream (12 bytes a vertex: position + packed RGBA)
// drawn with one glDrawArrays call, as triangles or as point sprites.

#include "Boids.h"
#include "WorkerPool.h"

#include <kodi/addon-instance/Screensaver.h>
#include <kodi/gui/gl/GL.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <string>
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

const char* kBoidVertexShader = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;      // world coordinates, origin top-left
attribute vec4 a_col;
uniform vec2 u_scale;      // 2/W, -2/H
uniform float u_pointSize;
uniform float u_fade;
varying vec4 v_col;
void main()
{
  gl_Position = vec4(a_pos.x * u_scale.x - 1.0, a_pos.y * u_scale.y + 1.0, 0.0, 1.0);
  gl_PointSize = u_pointSize;
  v_col = vec4(a_col.rgb, a_col.a * u_fade);
}
)";

// u_points: 0 = triangles (flat), 1 = round point sprites with a soft edge
const char* kBoidFragmentShader = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform float u_points;
varying vec4 v_col;
void main()
{
  float a = 1.0;
  if (u_points > 0.5)
  {
    vec2 c = gl_PointCoord - vec2(0.5);
    float d = dot(c, c);
    if (d > 0.25)
      discard;
    a = 1.0 - smoothstep(0.12, 0.25, d);
  }
  gl_FragColor = vec4(v_col.rgb, v_col.a * a);
}
)";

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

// One full-screen pass, three uses:
//  - trails: out = max(prev * keep - sub, 0) (u_mode 0; fades all the way to black)
//  - copy:   keep 1, sub 0
//  - sky:    a vertical dusk gradient (u_mode 1), darkened by u_keep
const char* kQuadFragmentShader = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_tex;
uniform float u_keep;
uniform float u_sub;
uniform float u_mode;
varying vec2 v_uv;
void main()
{
  if (u_mode > 0.5)
  {
    float t = v_uv.y; // 0 = bottom
    vec3 horizon = vec3(0.98, 0.60, 0.38);
    vec3 mid = vec3(0.62, 0.42, 0.55);
    vec3 top = vec3(0.13, 0.16, 0.34);
    vec3 c = t < 0.35 ? mix(horizon, mid, t / 0.35) : mix(mid, top, (t - 0.35) / 0.65);
    // a little noise hides the 8-bit banding of a smooth gradient
    float n = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
    gl_FragColor = vec4(c * u_keep + (n - 0.5) / 255.0, 1.0);
    return;
  }
  vec3 c = texture2D(u_tex, v_uv).rgb;
  gl_FragColor = vec4(max(c * u_keep - vec3(u_sub), vec3(0.0)), 1.0);
}
)";

// The world is 1000 units high and as wide as the screen's aspect ratio, so
// speeds and radii look the same on any display.
constexpr float kWorldHeight = 1000.0f;

enum Background { BG_BLACK, BG_DUSK };
enum ColourMode { COL_ORIGINAL, COL_FLOCK, COL_HEADING, COL_SPEED, COL_RANDOM };
enum Shape { SHAPE_TRIANGLE, SHAPE_DART, SHAPE_DOT };

struct Vertex
{
  float x, y;
  uint32_t rgba; // bytes r, g, b, a in memory order
};

inline uint32_t Pack(float r, float g, float b, float a = 1.0f)
{
  auto c = [](float v) { return static_cast<uint32_t>(std::min(std::max(v, 0.0f), 1.0f) * 255.0f + 0.5f); };
  return c(r) | (c(g) << 8) | (c(b) << 16) | (c(a) << 24);
}

// Scale the rgb bytes of a packed colour by k/256 (keeps alpha).
inline uint32_t Shade(uint32_t c, uint32_t k)
{
  const uint32_t rb = ((c & 0x00ff00ffu) * k >> 8) & 0x00ff00ffu;
  const uint32_t g = ((c & 0x0000ff00u) * k >> 8) & 0x0000ff00u;
  return rb | g | (c & 0xff000000u);
}

void Hsv(float h, float s, float v, float& r, float& g, float& b)
{
  h = (h - std::floor(h)) * 6.0f;
  const int i = static_cast<int>(h) % 6;
  const float f = h - std::floor(h);
  const float p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f));
  switch (i)
  {
    case 0: r = v; g = t; b = p; break;
    case 1: r = q; g = v; b = p; break;
    case 2: r = p; g = v; b = t; break;
    case 3: r = p; g = q; b = v; break;
    case 4: r = t; g = p; b = v; break;
    default: r = v; g = p; b = q; break;
  }
}

// Flock colours: the original's blue first, then warm, green and violet.
const float kFlockColours[boids::MAX_SPECIES][3] = {
    {0.25f, 0.55f, 1.0f}, {1.0f, 0.55f, 0.2f}, {0.35f, 1.0f, 0.55f}, {0.85f, 0.45f, 1.0f}};

} // namespace

class ATTR_DLL_LOCAL CScreensaverDancingBoids : public kodi::addon::CAddonBase,
                                                 public kodi::addon::CInstanceScreensaver
{
public:
  CScreensaverDancingBoids() = default;
  ~CScreensaverDancingBoids() override { m_pool.Stop(); }

  bool Start() override;
  void Stop() override;
  void Render() override;

private:
  using Clock = std::chrono::steady_clock;

  void LoadSettings();
  GLuint Compile(GLenum type, const std::string& src);
  GLuint Link(const char* vs, const char* fs);
  bool BuildPrograms();
  void NewFlock();
  void StepSimulation();
  void BuildVertices();
  void DrawBoids(float fade);
  void DrawQuad(GLuint tex, float keep, float sub, float mode);
  bool EnsureTrailBuffers(int w, int h);
  void DeleteTrailBuffers();

  boids::Simulation m_sim;
  boids::WorkerPool m_pool;

  GLuint m_program = 0;
  GLint m_aPos = -1, m_aCol = -1, m_uScale = -1, m_uPointSize = -1, m_uFade = -1, m_uPoints = -1;
  GLuint m_quadProgram = 0;
  GLint m_qaPos = -1, m_quTex = -1, m_quKeep = -1, m_quSub = -1, m_quMode = -1;
  GLuint m_vbo = 0, m_quadVbo = 0, m_vao = 0;
  float m_maxPointSize = 64.0f;

  GLuint m_trailTex[2] = {0, 0};
  GLuint m_trailFbo[2] = {0, 0};
  int m_trailW = 0, m_trailH = 0, m_trailCur = 0;
  bool m_trailsFailed = false;

  std::vector<Vertex> m_vertices;
  size_t m_numVertices = 0;

  // settings
  boids::Params m_base; // as configured; "vary" perturbs a copy per flock
  int m_background = BG_BLACK;
  int m_colourMode = COL_ORIGINAL;
  int m_shape = SHAPE_TRIANGLE;
  float m_size = 1.0f;
  bool m_glow = false;
  int m_trails = 0;
  float m_dim = 0.0f;
  int m_stepsPerSecond = 60;
  int m_threads = 0;
  int m_roundSeconds = 90;
  bool m_vary = true;

  Clock::time_point m_lastFrame, m_roundStart, m_statsStart;
  double m_accumulator = 0.0;
  double m_stepMs = 0.0;
  int m_stepCount = 0;
  int m_frameCount = 0;
  bool m_loggedStats = false;
};

//------------------------------------------------------------------------------

void CScreensaverDancingBoids::LoadSettings()
{
  boids::Params& p = m_base;
  p.count = std::min(std::max(kodi::addon::GetSettingInt("boids", 3000), 1), 20000);
  p.species = std::min(std::max(kodi::addon::GetSettingInt("flocks", 1), 1), boids::MAX_SPECIES);
  const float speed = std::max(kodi::addon::GetSettingInt("speed", 100), 10) / 100.0f;
  p.maxSpeed *= speed;
  p.minSpeed *= speed;
  p.maxForce *= speed;
  p.turn *= speed;
  p.vision = static_cast<float>(std::min(std::max(kodi::addon::GetSettingInt("vision", 55), 10), 200));
  p.separation = std::min(24.0f, p.vision * 0.6f);
  p.sepWeight *= kodi::addon::GetSettingInt("separation", 100) / 100.0f;
  p.alignWeight *= kodi::addon::GetSettingInt("alignment", 100) / 100.0f;
  p.cohWeight *= kodi::addon::GetSettingInt("cohesion", 100) / 100.0f;
  p.edges = kodi::addon::GetSettingInt("edges", boids::EDGES_TURN) == 1 ? boids::EDGES_WRAP
                                                                        : boids::EDGES_TURN;
  p.leadWeight = kodi::addon::GetSettingInt("lead", 25) / 100.0f;
  p.predators = std::min(std::max(kodi::addon::GetSettingInt("predators", 1), 0), boids::MAX_PREDATORS);
  p.maxNeighbours = std::min(std::max(kodi::addon::GetSettingInt("neighbours", 32), 4), 128);

  m_roundSeconds = std::max(0, kodi::addon::GetSettingInt("round_seconds", 90));
  m_vary = kodi::addon::GetSettingBoolean("vary", true);

  m_background = kodi::addon::GetSettingInt("background", BG_BLACK) == 1 ? BG_DUSK : BG_BLACK;
  m_colourMode = std::min(std::max(kodi::addon::GetSettingInt("colour", COL_ORIGINAL), 0), 4);
  m_shape = std::min(std::max(kodi::addon::GetSettingInt("shape", SHAPE_TRIANGLE), 0), 2);
  m_size = std::max(kodi::addon::GetSettingInt("size", 100), 10) / 100.0f;
  m_glow = kodi::addon::GetSettingBoolean("glow", false);
  m_trails = std::min(std::max(kodi::addon::GetSettingInt("trails", 0), 0), 3);
  m_dim = std::min(std::max(kodi::addon::GetSettingInt("dim", 0), 0), 90) / 100.0f;
  if (m_background == BG_DUSK)
  {
    m_glow = false; // dark birds on a bright sky: no additive light, no fade-to-black trails
    m_trails = 0;
  }

  m_stepsPerSecond = std::min(std::max(kodi::addon::GetSettingInt("steps_per_second", 60), 10), 240);
  // the per-step motion is tuned for 60 steps a second; keep the on-screen
  // speed the same at other rates
  const float rate = 60.0f / m_stepsPerSecond;
  p.maxSpeed *= rate;
  p.minSpeed *= rate;
  p.maxForce *= rate * rate;
  p.turn *= rate * rate;
  p.leadRate *= rate;
  m_threads = std::min(std::max(kodi::addon::GetSettingInt("threads", 0), 0), 4);
}

GLuint CScreensaverDancingBoids::Compile(GLenum type, const std::string& src)
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
    kodi::Log(ADDON_LOG_ERROR, "Dancing Boids: shader compile failed: %s", log);
    glDeleteShader(shader);
    return 0;
  }
  return shader;
}

GLuint CScreensaverDancingBoids::Link(const char* vsSrc, const char* fsSrc)
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
    kodi::Log(ADDON_LOG_ERROR, "Dancing Boids: program link failed: %s", log);
    glDeleteProgram(program);
    return 0;
  }
  return program;
}

bool CScreensaverDancingBoids::BuildPrograms()
{
  m_program = Link(kBoidVertexShader, kBoidFragmentShader);
  if (!m_program)
    return false;
  m_aPos = glGetAttribLocation(m_program, "a_pos");
  m_aCol = glGetAttribLocation(m_program, "a_col");
  m_uScale = glGetUniformLocation(m_program, "u_scale");
  m_uPointSize = glGetUniformLocation(m_program, "u_pointSize");
  m_uFade = glGetUniformLocation(m_program, "u_fade");
  m_uPoints = glGetUniformLocation(m_program, "u_points");

  // the quad program draws the sky and the trails; without it both are skipped
  m_quadProgram = Link(kQuadVertexShader, kQuadFragmentShader);
  if (m_quadProgram)
  {
    m_qaPos = glGetAttribLocation(m_quadProgram, "a_pos");
    m_quTex = glGetUniformLocation(m_quadProgram, "u_tex");
    m_quKeep = glGetUniformLocation(m_quadProgram, "u_keep");
    m_quSub = glGetUniformLocation(m_quadProgram, "u_sub");
    m_quMode = glGetUniformLocation(m_quadProgram, "u_mode");
  }
  else
  {
    m_trailsFailed = true;
  }
  return true;
}

void CScreensaverDancingBoids::NewFlock()
{
  m_sim.params = m_base;
  if (m_vary)
  {
    // a different temperament each round: tight swirling balls, loose
    // streams, or jittery shoals
    boids::Params& p = m_sim.params;
    p.sepWeight *= m_sim.RandomFloat(0.75f, 1.35f);
    p.alignWeight *= m_sim.RandomFloat(0.6f, 1.4f);
    p.cohWeight *= m_sim.RandomFloat(0.6f, 1.5f);
    p.vision *= m_sim.RandomFloat(0.8f, 1.25f);
    p.separation = std::min(p.separation, p.vision * 0.6f);
    const float s = m_sim.RandomFloat(0.85f, 1.15f);
    p.maxSpeed *= s;
    p.minSpeed *= s;
  }

  const int mode = m_colourMode;
  const float hueBase = m_sim.RandomFloat(0, 1);
  m_sim.Restart([mode, hueBase](std::mt19937& rng, uint8_t sp) -> uint32_t {
    std::uniform_real_distribution<float> u(0.0f, 1.0f);
    float r, g, b;
    switch (mode)
    {
      case COL_FLOCK:
      {
        const float k = 0.8f + 0.2f * u(rng);
        return Pack(kFlockColours[sp][0] * k, kFlockColours[sp][1] * k, kFlockColours[sp][2] * k);
      }
      case COL_RANDOM:
        Hsv(hueBase + u(rng), 0.75f, 1.0f, r, g, b);
        return Pack(r, g, b);
      default:
        // the original screensaver: (rand(0, 0.3), rand(0.1, 0.3), 1)
        return Pack(0.3f * u(rng), 0.1f + 0.2f * u(rng), 1.0f);
    }
  });
  m_roundStart = Clock::now();
}

void CScreensaverDancingBoids::StepSimulation()
{
  const auto t0 = Clock::now();
  m_sim.BeginStep();
  m_pool.Run(m_sim.size(), [this](size_t lo, size_t hi) { m_sim.UpdateRange(lo, hi); });
  m_sim.EndStep();
  m_stepMs += std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
  m_stepCount++;
}

bool CScreensaverDancingBoids::Start()
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
  glGenBuffers(1, &m_vbo);
  if (m_quadProgram)
  {
    const float quad[] = {-1, -1, 1, -1, -1, 1, 1, 1};
    glGenBuffers(1, &m_quadVbo);
    glBindBuffer(GL_ARRAY_BUFFER, m_quadVbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
  }

  // Small flocks are not worth waking threads for.
  m_pool.Start(m_base.count < 600 ? 1 : m_threads);

  const float aspect = static_cast<float>(Width()) / static_cast<float>(std::max(1, Height()));
  m_sim.Resize(kWorldHeight * aspect, kWorldHeight);
  NewFlock();

  m_lastFrame = Clock::now();
  m_statsStart = m_lastFrame;
  m_accumulator = 0.0;
  m_stepMs = 0.0;
  m_stepCount = 0;
  m_frameCount = 0;
  m_loggedStats = false;
  kodi::Log(ADDON_LOG_INFO, "Dancing Boids: %d boids, %d flock(s), %d thread(s), %d steps/s",
            m_base.count, m_base.species, m_pool.threads(), m_stepsPerSecond);
  return true;
}

void CScreensaverDancingBoids::Stop()
{
  m_pool.Stop();
  DeleteTrailBuffers();
  if (m_vbo)
    glDeleteBuffers(1, &m_vbo);
  if (m_quadVbo)
    glDeleteBuffers(1, &m_quadVbo);
  m_vbo = m_quadVbo = 0;
#ifdef TARGET_DARWIN
  if (m_vao)
    glDeleteVertexArrays(1, &m_vao);
  m_vao = 0;
#endif
  if (m_program)
    glDeleteProgram(m_program);
  if (m_quadProgram)
    glDeleteProgram(m_quadProgram);
  m_program = m_quadProgram = 0;
}

// One pass over the flock writes the whole vertex stream: 3 vertices a boid
// for triangles and darts, 1 for dots, then the hawks.
void CScreensaverDancingBoids::BuildVertices()
{
  const size_t n = m_sim.size();
  const int np = m_sim.numPredators();
  const bool dots = m_shape == SHAPE_DOT;
  const size_t per = dots ? 1 : 3;
  m_vertices.resize((n + static_cast<size_t>(np)) * per);

  const float* X = m_sim.x();
  const float* Y = m_sim.y();
  const float* VX = m_sim.vx();
  const float* VY = m_sim.vy();
  const uint32_t* T = m_sim.tint();
  const uint8_t* SP = m_sim.species();
  const float maxS = std::max(m_sim.params.maxSpeed, 1e-3f);
  const float minS = m_sim.params.minSpeed;

  const float len = (m_shape == SHAPE_DART ? 15.0f : 12.0f) * m_size;
  const float wid = (m_shape == SHAPE_DART ? 2.6f : 4.2f) * m_size;
  const bool dusk = m_background == BG_DUSK;
  const uint32_t silhouette = Pack(0.05f, 0.04f, 0.07f, 0.92f);

  // 64-entry hue wheel for the heading colours, filled once per call
  uint32_t wheel[64];
  if (m_colourMode == COL_HEADING && !dusk)
    for (int i = 0; i < 64; i++)
    {
      float r, g, b;
      Hsv(i / 64.0f, 0.8f, 1.0f, r, g, b);
      wheel[i] = Pack(r, g, b);
    }

  Vertex* out = m_vertices.data();
  for (size_t i = 0; i < n; i++)
  {
    const float vx = VX[i], vy = VY[i];
    const float s = std::sqrt(vx * vx + vy * vy);
    const float inv = s > 1e-6f ? 1.0f / s : 0.0f;
    const float hx = vx * inv, hy = vy * inv;

    uint32_t c;
    if (dusk)
      c = silhouette;
    else
      switch (m_colourMode)
      {
        case COL_HEADING:
        {
          const float a = std::atan2(hy, hx) * (0.5f / 3.14159265f) + 0.5f; // 0..1
          c = wheel[static_cast<int>(a * 63.999f) & 63];
          break;
        }
        case COL_SPEED:
        {
          // slow = deep blue, fast = hot white
          const float t = std::min(std::max((s - minS) / std::max(maxS - minS, 1e-3f), 0.0f), 1.0f);
          c = Pack(0.15f + 0.85f * t * t, 0.3f + 0.7f * t, 1.0f - 0.2f * t);
          break;
        }
        case COL_FLOCK:
        case COL_RANDOM:
        case COL_ORIGINAL:
        default:
          c = T[i];
          (void)SP;
          break;
      }

    if (dots)
    {
      *out++ = {X[i], Y[i], c};
      continue;
    }
    // tip ahead of the centre, two tail corners behind; the tail is darker
    // for a little depth (on the dusk sky the birds stay flat black)
    const float tx = X[i] + hx * len * 0.6f, ty = Y[i] + hy * len * 0.6f;
    const float bx = X[i] - hx * len * 0.4f, by = Y[i] - hy * len * 0.4f;
    const uint32_t tail = dusk ? c : Shade(c, 140);
    *out++ = {tx, ty, c};
    *out++ = {bx - hy * wid, by + hx * wid, tail};
    *out++ = {bx + hy * wid, by - hx * wid, tail};
  }

  const boids::Predator* P = m_sim.predators();
  const uint32_t hawk = dusk ? Pack(0.02f, 0.02f, 0.03f, 1.0f) : Pack(1.0f, 0.25f, 0.15f);
  for (int q = 0; q < np; q++)
  {
    const float s = std::sqrt(P[q].vx * P[q].vx + P[q].vy * P[q].vy);
    const float hx = s > 1e-6f ? P[q].vx / s : 1.0f, hy = s > 1e-6f ? P[q].vy / s : 0.0f;
    if (dots)
    {
      *out++ = {P[q].x, P[q].y, hawk};
      continue;
    }
    const float L = 30.0f * m_size, W = 11.0f * m_size;
    const float bx = P[q].x - hx * L * 0.4f, by = P[q].y - hy * L * 0.4f;
    *out++ = {P[q].x + hx * L * 0.6f, P[q].y + hy * L * 0.6f, hawk};
    *out++ = {bx - hy * W, by + hx * W, dusk ? hawk : Shade(hawk, 150)};
    *out++ = {bx + hy * W, by - hx * W, dusk ? hawk : Shade(hawk, 150)};
  }
  m_numVertices = static_cast<size_t>(out - m_vertices.data());
}

void CScreensaverDancingBoids::DrawBoids(float fade)
{
  glEnable(GL_BLEND);
  if (m_glow)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
  else
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
#ifdef GL_PROGRAM_POINT_SIZE
  glEnable(GL_PROGRAM_POINT_SIZE);
#endif

  const float vw = m_sim.width();
  const float pxPerUnit = static_cast<float>(Height()) / kWorldHeight;
  glUseProgram(m_program);
  glUniform2f(m_uScale, 2.0f / vw, -2.0f / kWorldHeight);
  glUniform1f(m_uPointSize, std::min(std::max(6.0f * m_size * pxPerUnit, 1.5f), m_maxPointSize));
  // additive light saturates dense flocks to white at full strength
  glUniform1f(m_uFade, m_glow ? fade * 0.5f : fade);
  glUniform1f(m_uPoints, m_shape == SHAPE_DOT ? 1.0f : 0.0f);

  glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
  glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(m_numVertices * sizeof(Vertex)),
               m_vertices.data(), GL_STREAM_DRAW);
  glEnableVertexAttribArray(static_cast<GLuint>(m_aPos));
  glVertexAttribPointer(static_cast<GLuint>(m_aPos), 2, GL_FLOAT, GL_FALSE, sizeof(Vertex), nullptr);
  if (m_aCol >= 0)
  {
    glEnableVertexAttribArray(static_cast<GLuint>(m_aCol));
    glVertexAttribPointer(static_cast<GLuint>(m_aCol), 4, GL_UNSIGNED_BYTE, GL_TRUE, sizeof(Vertex),
                          reinterpret_cast<const void*>(2 * sizeof(float)));
  }
  glDrawArrays(m_shape == SHAPE_DOT ? GL_POINTS : GL_TRIANGLES, 0, static_cast<GLsizei>(m_numVertices));
  glDisableVertexAttribArray(static_cast<GLuint>(m_aPos));
  if (m_aCol >= 0)
    glDisableVertexAttribArray(static_cast<GLuint>(m_aCol));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
}

void CScreensaverDancingBoids::DrawQuad(GLuint tex, float keep, float sub, float mode)
{
  glDisable(GL_BLEND);
  glUseProgram(m_quadProgram);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, tex);
  glUniform1i(m_quTex, 0);
  glUniform1f(m_quKeep, keep);
  glUniform1f(m_quSub, sub);
  glUniform1f(m_quMode, mode);
  glBindBuffer(GL_ARRAY_BUFFER, m_quadVbo);
  glEnableVertexAttribArray(static_cast<GLuint>(m_qaPos));
  glVertexAttribPointer(static_cast<GLuint>(m_qaPos), 2, GL_FLOAT, GL_FALSE, 0, nullptr);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
  glDisableVertexAttribArray(static_cast<GLuint>(m_qaPos));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glBindTexture(GL_TEXTURE_2D, 0);
}

bool CScreensaverDancingBoids::EnsureTrailBuffers(int w, int h)
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
    kodi::Log(ADDON_LOG_ERROR, "Dancing Boids: trail framebuffer incomplete; trails disabled");
    DeleteTrailBuffers();
    m_trailsFailed = true;
    return false;
  }
  m_trailW = w;
  m_trailH = h;
  m_trailCur = 0;
  return true;
}

void CScreensaverDancingBoids::DeleteTrailBuffers()
{
  if (m_trailFbo[0])
    glDeleteFramebuffers(2, m_trailFbo);
  if (m_trailTex[0])
    glDeleteTextures(2, m_trailTex);
  m_trailFbo[0] = m_trailFbo[1] = 0;
  m_trailTex[0] = m_trailTex[1] = 0;
  m_trailW = m_trailH = 0;
}

void CScreensaverDancingBoids::Render()
{
  if (!m_program)
    return;

  // --- simulation: fixed time step, decoupled from the display refresh rate
  const auto now = Clock::now();
  m_accumulator += std::min(std::chrono::duration<double>(now - m_lastFrame).count(), 0.1);
  m_lastFrame = now;
  const double dt = 1.0 / m_stepsPerSecond;
  int steps = 0;
  while (m_accumulator >= dt && steps < 3)
  {
    StepSimulation();
    m_accumulator -= dt;
    ++steps;
  }
  if (steps == 3)
    m_accumulator = 0.0; // can't keep up: slow down rather than spiral

  // one line in the log after 20 s, to check a box keeps up
  m_frameCount++;
  const double statsAge = std::chrono::duration<double>(now - m_statsStart).count();
  if (!m_loggedStats && statsAge > 20.0 && m_stepCount > 0)
  {
    kodi::Log(ADDON_LOG_INFO,
              "Dancing Boids: %.2f ms per simulation step, %.1f frames/s (%d boids, %d thread(s))",
              m_stepMs / m_stepCount, m_frameCount / statsAge, static_cast<int>(m_sim.size()),
              m_pool.threads());
    m_loggedStats = true;
  }

  // --- rounds: fade out, new flock, fade in (as the original's 5 s fades)
  float fade = 1.0f;
  const double age = std::chrono::duration<double>(now - m_roundStart).count();
  constexpr double kFade = 3.0;
  if (m_roundSeconds > 0)
  {
    if (age >= m_roundSeconds)
    {
      NewFlock();
      fade = 0.0f;
    }
    else if (age > m_roundSeconds - kFade)
      fade = static_cast<float>((m_roundSeconds - age) / kFade);
  }
  if (age < kFade)
    fade = std::min(fade, static_cast<float>(age / kFade));
  fade = fade * fade * (3.0f - 2.0f * fade);
  const float bright = 1.0f - m_dim;

  BuildVertices();

  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
#ifdef TARGET_DARWIN
  glBindVertexArray(m_vao);
#endif

  if (m_trails > 0 && EnsureTrailBuffers(Width(), Height()))
  {
    static const float kKeep[] = {1.0f, 0.78f, 0.88f, 0.94f};
    GLint screenFbo = 0;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &screenFbo);
    const GLboolean scissor = glIsEnabled(GL_SCISSOR_TEST);
    glDisable(GL_SCISSOR_TEST);

    const int prev = m_trailCur, cur = 1 - m_trailCur;
    glBindFramebuffer(GL_FRAMEBUFFER, m_trailFbo[cur]);
    glViewport(0, 0, m_trailW, m_trailH);
    DrawQuad(m_trailTex[prev], kKeep[m_trails], 1.5f / 255.0f, 0.0f);
    DrawBoids(fade);

    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(screenFbo));
    if (scissor)
      glEnable(GL_SCISSOR_TEST);
    glViewport(X(), Y(), Width(), Height());
    DrawQuad(m_trailTex[cur], bright, 0.0f, 0.0f);
    m_trailCur = cur;
  }
  else
  {
    glViewport(X(), Y(), Width(), Height());
    if (m_background == BG_DUSK && m_quadProgram)
      DrawQuad(0, bright, 0.0f, 1.0f);
    else
    {
      glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
      glClear(GL_COLOR_BUFFER_BIT);
    }
    // dimming a black background: scale the birds instead
    DrawBoids(m_background == BG_DUSK ? fade : fade * bright);
  }

  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif
  glUseProgram(0);
}

ADDONCREATOR(CScreensaverDancingBoids)

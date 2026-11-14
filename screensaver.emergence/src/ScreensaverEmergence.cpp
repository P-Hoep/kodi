// Kodi screensaver wrapper around Emergence's world (World.h).
//
// As in Physarum v2, the simulation runs on its own driver thread plus a
// small worker pool, one step ahead of the picture, so Render() never waits:
// when a step has finished, Render() uploads what it produced (the slime's
// 8-bit trail picture and one vertex stream of particles and boids) and kicks
// off the next step. Scene changes are done by the driver thread too, behind a
// fade to black.
//
// Drawing is plain OpenGL / OpenGL ES 2: the slime is one full-screen quad
// whose fragment shader colours the trail texture (compiled per colour mode
// and species count); the particles are point sprites and the boids triangles
// from the same vertex buffer (12 bytes a vertex: position + packed RGBA).
// Scenes without slime can leave motion trails through a pair of off-screen
// buffers that fade each frame.

#include "World.h"

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
// `texture2D`, `gl_FragColor`, LUMINANCE textures; a VAO must be bound);
// Linux Kodi runs GL 2.1; GLES 2 takes the shader bodies as they are.
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

const char* kQuadVertexShader = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;
varying vec2 v_uv;
void main()
{
  gl_Position = vec4(a_pos, 0.0, 1.0);
#ifdef FLIP
  v_uv = vec2(a_pos.x * 0.5 + 0.5, 0.5 - a_pos.y * 0.5); // trail row 0 is the top
#else
  v_uv = a_pos * 0.5 + 0.5;
#endif
}
)";

// The slime, from Physarum v2. MODE and SPECIES are #defined in front.
const char* kSlimeFragmentShader = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_trail;
uniform sampler2D u_pal;      // 8 x 1: the 7 palette colours and the first again
uniform vec4 u_sel1;          // picks species 2 out of the texel
uniform vec2 u_m;             // palette phase, fade
uniform vec3 u_c0;
uniform vec3 u_c1;
varying vec2 v_uv;

vec3 pal(float t) { return texture2D(u_pal, vec2((fract(t) * 7.0 + 0.5) / 8.0, 0.5)).rgb; }

void main()
{
  vec4 t = texture2D(u_trail, v_uv);
#if SPECIES == 1
  float d = t.r;
#else
  float a = t.r;
  float b = dot(t, u_sel1);
  float d = min(a + b, 1.0);
  vec3 sp = u_c0 * a + u_c1 * b;
#endif
  float d2 = d * d;
  vec3 col;
#if MODE == 0          // palette
#if SPECIES == 1
  col = pal(d * 0.85 + u_m.x) * d;
#else
  col = sp + vec3(d2 * d2 * 0.4);
#endif
#elif MODE == 1        // neon: white-hot cores
#if SPECIES == 1
  col = pal(d * 0.85 + u_m.x) * d * 0.85 + vec3(d2 * d * 0.9);
#else
  col = sp * 0.85 + vec3(d2 * d * 0.9);
#endif
#else                  // fire
  col = clamp(vec3(d * 1.7, d2 * 1.5, d2 * d2 * 1.3), 0.0, 1.0);
#endif
  gl_FragColor = vec4(col * u_m.y, 1.0);
}
)";

// Trails: out = max(prev * keep - sub, 0), fading all the way to black.
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

// Particles and boids: positions are 0..1 across the screen, y down.
const char* kSpriteVertexShader = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;
attribute vec4 a_col;
uniform float u_pointSize;
uniform float u_fade;
varying vec4 v_col;
void main()
{
  gl_Position = vec4(a_pos.x * 2.0 - 1.0, 1.0 - a_pos.y * 2.0, 0.0, 1.0);
  gl_PointSize = u_pointSize;
  v_col = vec4(a_col.rgb, a_col.a * u_fade);
}
)";

// u_points: 0 = triangles (flat), 1 = round points with a soft edge, 2 = glow
const char* kSpriteFragmentShader = R"(
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
    a = u_points > 1.5 ? exp(-d * 18.0) : 1.0 - smoothstep(0.14, 0.25, d);
  }
  gl_FragColor = vec4(v_col.rgb, v_col.a * a);
}
)";

enum SceneChoice { CHOICE_ALL, CHOICE_COMBINATIONS, CHOICE_ORIGINALS, CHOICE_FIRST_SCENE };
enum Mode { MODE_PALETTE, MODE_NEON, MODE_FIRE, MODE_COUNT };
enum Pace { PACE_NORMAL, PACE_FAST, PACE_SLOW };
enum BoidColour { BC_AUTO, BC_ORIGINAL, BC_FLOCK, BC_HEADING, BC_PALE, BC_COUNT };
enum Shape { SHAPE_TRIANGLE, SHAPE_DART, SHAPE_DOT };
enum LifePalette { LP_CLASSIC, LP_NEON, LP_PASTEL, LP_RAINBOW, LP_RANDOM, LP_COUNT };

// Option lists (tools/make_settings_emergence.py has the same order).
const int kSceneMinutes[] = {1, 2, 3, 5, 10, 20, 30};
constexpr double kFadeSeconds = 1.5;

template <typename T, size_t N>
int Pick(int index, const T (&)[N])
{
  return std::min(std::max(index, 0), static_cast<int>(N) - 1);
}

struct RGB
{
  float r, g, b;
};

RGB Hex(uint32_t c)
{
  return {((c >> 16) & 255) / 255.0f, ((c >> 8) & 255) / 255.0f, (c & 255) / 255.0f};
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

inline uint32_t Pack(float r, float g, float b, float a = 1.0f)
{
  auto c = [](float v) { return static_cast<uint32_t>(std::min(std::max(v, 0.0f), 1.0f) * 255.0f + 0.5f); };
  return c(r) | (c(g) << 8) | (c(b) << 16) | (c(a) << 24);
}

inline uint32_t Pack(const RGB& c, float a = 1.0f) { return Pack(c.r, c.g, c.b, a); }

// Scale the rgb bytes of a packed colour by k/256 (keeps alpha).
inline uint32_t Shade(uint32_t c, uint32_t k)
{
  const uint32_t rb = ((c & 0x00ff00ffu) * k >> 8) & 0x00ff00ffu;
  const uint32_t g = ((c & 0x0000ff00u) * k >> 8) & 0x0000ff00u;
  return rb | g | (c & 0xff000000u);
}

// Blend the rgb bytes of a packed colour towards white by k/256.
inline uint32_t Whiten(uint32_t c, uint32_t k)
{
  uint32_t out = c & 0xff000000u;
  for (int s = 0; s < 24; s += 8)
  {
    const uint32_t v = (c >> s) & 255u;
    out |= (v + ((255u - v) * k >> 8)) << s;
  }
  return out;
}

// Particle colours, from Particle Life v2: red, green, yellow, white, then
// the JavaScript version's extras.
const RGB kLifePalettes[3][particlelife::MAX_GROUPS] = {
    {{1, 0, 0}, {0, 1, 0}, {1, 1, 0}, {1, 1, 1}, {0, 1, 1}, {1, 0, 1}, {1, 0.55f, 0}, {0.7f, 0.6f, 1}},
    {{1, 0.1f, 0.55f}, {0.1f, 1, 0.4f}, {1, 0.9f, 0.1f}, {0.3f, 0.8f, 1},
     {0.65f, 0.3f, 1}, {1, 0.45f, 0.1f}, {0.1f, 1, 1}, {0.95f, 0.95f, 1}},
    {{1, 0.6f, 0.6f}, {0.6f, 1, 0.7f}, {1, 0.95f, 0.6f}, {0.95f, 0.95f, 0.95f},
     {0.6f, 0.9f, 1}, {1, 0.65f, 0.95f}, {1, 0.8f, 0.55f}, {0.78f, 0.7f, 1}},
};

// Flock colours: the original's blue first, then warm, green and violet.
const RGB kFlockColours[boids::MAX_SPECIES] = {
    {0.25f, 0.55f, 1.0f}, {1.0f, 0.55f, 0.2f}, {0.35f, 1.0f, 0.55f}, {0.85f, 0.45f, 1.0f}};

// Scenes drawn over a textured quad: the slime, or in Reef a soft glow of
// where the particle cells are (the density map the flock steers by).
inline bool HasBackdrop(int scene) { return emergence::HasSlime(scene) || scene == emergence::SCENE_REEF; }

struct Vertex
{
  float x, y;
  uint32_t rgba; // bytes r, g, b, a in memory order
};

} // namespace

class ATTR_DLL_LOCAL CScreensaverEmergence : public kodi::addon::CAddonBase,
                                              public kodi::addon::CInstanceScreensaver
{
public:
  CScreensaverEmergence() = default;
  ~CScreensaverEmergence() override { StopSimulation(); }

  bool Start() override;
  void Stop() override;
  void Render() override;

private:
  using Clock = std::chrono::steady_clock;

  struct SlimeProgram
  {
    GLuint program = 0;
    GLint aPos = -1, uSel1 = -1, uM = -1, uC0 = -1, uC1 = -1;
  };

  void LoadSettings();
  GLuint Compile(GLenum type, const std::string& src);
  GLuint Link(const std::string& vs, const std::string& fs);
  bool BuildPrograms();
  SlimeProgram* Slime(int species);
  int NextScene();
  void BeginScene(int scene);
  void BuildSprites();
  void ApplySceneGL();
  void UploadFrame();
  void DriverLoop();
  void StopSimulation();
  RGB PaletteAt(float t) const;
  void DrawSlime(float fade, float phase);
  void DrawSprites(float fade);
  void DrawQuad(GLint aPos);
  bool EnsureTrailBuffers(int w, int h);
  void DeleteTrailBuffers();

  emergence::World m_world;
  emergence::WorkerPool m_pool;
  std::mt19937 m_rng{std::random_device{}()};

  // the driver thread: Begin a scene (if asked) and run m_kick steps
  std::thread m_driver;
  std::mutex m_mutex;
  std::condition_variable m_cv;
  int m_kick = 0;
  int m_beginScene = -1;
  uint32_t m_beginSeed = 0;
  bool m_busy = false;
  bool m_fresh = false;
  bool m_quit = false;
  unsigned m_serial = 0;  // bumped by every Begin (guarded by m_mutex)
  double m_stepMs = 0.0;  // guarded by m_mutex
  long m_stepCount = 0;

  // written by the driver thread while busy, read by Render while not
  std::vector<Vertex> m_vertices;
  size_t m_numPoints = 0, m_numTris = 0;
  RGB m_lifeColours[particlelife::MAX_GROUPS] = {};
  int m_palette = 0;
  // what was uploaded, for drawing (render thread only)
  size_t m_drawPoints = 0, m_drawTris = 0;
  int m_drawPalette = 0;

  // GL
  SlimeProgram m_slime[2];
  GLuint m_spriteProgram = 0, m_fadeProgram = 0;
  GLint m_saPos = -1, m_saCol = -1, m_suPointSize = -1, m_suFade = -1, m_suPoints = -1;
  GLint m_faPos = -1, m_fuTex = -1, m_fuKeep = -1, m_fuSub = -1;
  GLuint m_quadVbo = 0, m_spriteVbo = 0, m_vao = 0, m_trailTex = 0, m_palTex = 0;
  int m_texW = 0, m_texH = 0, m_texSpecies = 0;
  GLenum m_texFormat = 0;
  unsigned m_glSerial = ~0u;
  float m_maxPointSize = 64.0f;
  GLuint m_fadeTex[2] = {0, 0}, m_fadeFbo[2] = {0, 0};
  int m_fadeW = 0, m_fadeH = 0, m_fadeCur = 0;
  bool m_fadeFailed = false;

  // settings
  emergence::Settings m_set;
  int m_choice = CHOICE_ALL;
  int m_sceneMinutes = 3;
  int m_mode = MODE_PALETTE;
  int m_paletteSetting = -1; // -1: a different one each scene
  float m_cycle = 0.2f;
  float m_brightness = 1.0f;
  float m_dim = 0.0f;
  int m_boidColour = BC_AUTO;
  int m_shape = SHAPE_TRIANGLE;
  float m_boidSize = 1.0f;
  int m_lifePalette = LP_CLASSIC;
  float m_pointSize = 2.0f;
  bool m_glow = false;
  int m_trails = 0;
  int m_pace = PACE_NORMAL;
  int m_threads = 0;
  float m_aspect = 16.0f / 9.0f;

  // scene sequencing (render thread)
  int m_scene = 0;           // on screen
  bool m_switching = false;  // fading out to change scene
  bool m_requested = false;  // the new scene has been asked of the driver
  Clock::time_point m_sceneStart, m_switchStart, m_start0, m_statsStart, m_lastFrame;
  double m_credit = 0.0;
  long m_frames = 0;
  bool m_loggedStats = false;
};

//------------------------------------------------------------------------------

void CScreensaverEmergence::LoadSettings()
{
  using kodi::addon::GetSettingBoolean;
  using kodi::addon::GetSettingInt;

  m_choice = std::min(std::max(GetSettingInt("scene", 0), 0), CHOICE_FIRST_SCENE + emergence::SCENE_COUNT - 1);
  m_sceneMinutes = kSceneMinutes[Pick(GetSettingInt("scene_minutes", 2), kSceneMinutes)];
  m_set.coupling = std::min(std::max(GetSettingInt("coupling", 100), 0), 300) / 100.0f;

  m_set.slimePreset = std::min(std::max(GetSettingInt("slime_preset", 0), 0), physarum::kNumPresets) - 1;
  m_mode = std::min(std::max(GetSettingInt("colour_mode", 0), 0), MODE_COUNT - 1);
  m_paletteSetting = std::min(std::max(GetSettingInt("palette", 0), 0), physarum::kNumPalettes) - 1;
  m_cycle = std::min(std::max(GetSettingInt("cycle", 20), 0), 100) / 100.0f;
  m_brightness = std::min(std::max(GetSettingInt("brightness", 100), 10), 500) / 100.0f;

  m_set.flocks = std::min(std::max(GetSettingInt("flocks", 1), 1), boids::MAX_SPECIES);
  m_set.hawks = std::min(std::max(GetSettingInt("hawks", 1), 0), boids::MAX_PREDATORS);
  m_set.vary = GetSettingBoolean("vary", true);
  m_boidColour = std::min(std::max(GetSettingInt("boid_colour", 0), 0), BC_COUNT - 1);
  m_shape = std::min(std::max(GetSettingInt("shape", 0), 0), 2);
  m_boidSize = std::min(std::max(GetSettingInt("boid_size", 100), 30), 300) / 100.0f;

  m_set.lifeRules = std::min(std::max(GetSettingInt("life_rules", 2), 0), 2);
  m_set.lifeColours = std::min(std::max(GetSettingInt("life_colours", 5), 2), particlelife::MAX_GROUPS);
  m_lifePalette = std::min(std::max(GetSettingInt("life_palette", 0), 0), LP_COUNT - 1);
  m_pointSize = static_cast<float>(std::min(std::max(GetSettingInt("point_size", 3), 1), 8));
  m_glow = GetSettingBoolean("glow", false);

  m_trails = std::min(std::max(GetSettingInt("trails", 0), 0), 3);
  m_dim = std::min(std::max(GetSettingInt("dim", 0), 0), 90) / 100.0f;

  m_set.detail = std::min(std::max(GetSettingInt("detail", 1), 0), 2);
  m_pace = std::min(std::max(GetSettingInt("pace", 0), 0), 2);
  m_threads = std::min(std::max(GetSettingInt("threads", 0), 0), 4);
}

GLuint CScreensaverEmergence::Compile(GLenum type, const std::string& src)
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
    kodi::Log(ADDON_LOG_ERROR, "Emergence: shader compile failed: %s", log);
    glDeleteShader(shader);
    return 0;
  }
  return shader;
}

GLuint CScreensaverEmergence::Link(const std::string& vsSrc, const std::string& fsSrc)
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
    kodi::Log(ADDON_LOG_ERROR, "Emergence: program link failed: %s", log);
    glDeleteProgram(program);
    return 0;
  }
  return program;
}

bool CScreensaverEmergence::BuildPrograms()
{
  m_spriteProgram = Link(kSpriteVertexShader, kSpriteFragmentShader);
  if (!m_spriteProgram)
    return false;
  m_saPos = glGetAttribLocation(m_spriteProgram, "a_pos");
  m_saCol = glGetAttribLocation(m_spriteProgram, "a_col");
  m_suPointSize = glGetUniformLocation(m_spriteProgram, "u_pointSize");
  m_suFade = glGetUniformLocation(m_spriteProgram, "u_fade");
  m_suPoints = glGetUniformLocation(m_spriteProgram, "u_points");

  // both slime variants up front, so a scene change never compiles
  if (!Slime(1) || !Slime(2))
    return false;

  // trails are optional: without the program the scenes just have none
  m_fadeProgram = Link(kQuadVertexShader, kFadeFragmentShader);
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

CScreensaverEmergence::SlimeProgram* CScreensaverEmergence::Slime(int species)
{
  SlimeProgram& p = m_slime[std::min(std::max(species, 1), 2) - 1];
  if (p.program)
    return &p;
  const std::string defines =
      "#define MODE " + std::to_string(m_mode) + "\n#define SPECIES " + std::to_string(species) + "\n";
  p.program = Link(std::string("#define FLIP\n") + kQuadVertexShader, defines + kSlimeFragmentShader);
  if (!p.program)
    return nullptr;
  p.aPos = glGetAttribLocation(p.program, "a_pos");
  p.uSel1 = glGetUniformLocation(p.program, "u_sel1");
  p.uM = glGetUniformLocation(p.program, "u_m");
  p.uC0 = glGetUniformLocation(p.program, "u_c0");
  p.uC1 = glGetUniformLocation(p.program, "u_c1");
  glUseProgram(p.program);
  glUniform1i(glGetUniformLocation(p.program, "u_trail"), 0);
  glUniform1i(glGetUniformLocation(p.program, "u_pal"), 1);
  glUseProgram(0);
  return &p;
}

// The next scene of the rotation, never the same one twice in a row.
int CScreensaverEmergence::NextScene()
{
  using namespace emergence;
  if (m_choice >= CHOICE_FIRST_SCENE)
    return m_choice - CHOICE_FIRST_SCENE;
  std::vector<int> pool;
  for (int s = 0; s < SCENE_COUNT; s++)
    if (m_choice == CHOICE_ALL || (m_choice == CHOICE_COMBINATIONS) == IsCombination(s))
      pool.push_back(s);
  if (pool.size() > 1)
    pool.erase(std::remove(pool.begin(), pool.end(), m_scene), pool.end());
  return pool[m_rng() % pool.size()];
}

// Driver thread (or Start, before it runs): set up a scene and its colours.
void CScreensaverEmergence::BeginScene(int scene)
{
  m_world.Begin(scene, m_set, m_beginSeed, m_aspect);
  std::mt19937 r(m_beginSeed ^ 0x5bd1e995u);
  // the slime's palette: any but greyscale when it is chosen for us
  m_palette = m_paletteSetting >= 0 ? m_paletteSetting : static_cast<int>(r() % (physarum::kNumPalettes - 1));

  const int n = m_world.life.numGroups();
  const float hue = (r() % 1000) / 1000.0f;
  for (int i = 0; i < particlelife::MAX_GROUPS; i++)
    switch (m_lifePalette)
    {
      case LP_RAINBOW: m_lifeColours[i] = Hsv(static_cast<float>(i) / n, 0.85f, 1.0f); break;
      case LP_RANDOM: m_lifeColours[i] = Hsv(hue + static_cast<float>(i) / n, 0.8f, 1.0f); break;
      default: m_lifeColours[i] = kLifePalettes[m_lifePalette][i]; break;
    }
  kodi::Log(ADDON_LOG_INFO, "Emergence: %s (slime %s, particles %s)", emergence::SceneName(scene),
            emergence::HasSlime(scene) ? physarum::kPresets[m_world.slimePreset()].name : "-",
            !emergence::HasLife(scene)       ? "-"
            : m_world.lifePreset() < 0 ? "random rules"
                                       : particlelife::kPresets[m_world.lifePreset()].name);
}

// One pass over the particles and the flock writes the vertex stream: the
// particles as points, then 3 vertices a boid and a hawk (or 1 as dots).
void CScreensaverEmergence::BuildSprites()
{
  using namespace emergence;
  const int scene = m_world.scene();
  const bool combo = IsCombination(scene);
  size_t total = 0;
  if (HasLife(scene))
    total += m_world.ParticleCount();
  const bool dots = m_shape == SHAPE_DOT;
  const boids::Simulation& fl = m_world.flock;
  const size_t nb = HasFlock(scene) ? fl.size() : 0;
  const int np = HasFlock(scene) ? fl.numPredators() : 0;
  m_vertices.resize(total + (nb + static_cast<size_t>(np)) * 3);
  Vertex* out = m_vertices.data();

  if (HasLife(scene))
  {
    const particlelife::Simulation& life = m_world.life;
    const float ix = 1.0f / life.width(), iy = 1.0f / life.height();
    // the original's draw order for its four colours (later = on top)
    static const int kOrder[particlelife::MAX_GROUPS] = {3, 0, 1, 2, 4, 5, 6, 7};
    for (int o = 0; o < particlelife::MAX_GROUPS; o++)
    {
      const int g = kOrder[o];
      if (g >= life.numGroups())
        continue;
      const uint32_t c = Pack(m_lifeColours[g], m_glow ? 0.6f : 1.0f);
      const particlelife::Group& gr = life.group(g);
      for (size_t i = 0; i < gr.size(); i++)
        *out++ = {gr.x[i] * ix, gr.y[i] * iy, c};
    }
  }
  m_numPoints = static_cast<size_t>(out - m_vertices.data());

  if (nb)
  {
    const float* X = fl.x();
    const float* Y = fl.y();
    const float* VX = fl.vx();
    const float* VY = fl.vy();
    const uint32_t* T = fl.tint();
    const uint8_t* SP = fl.species();
    const float sx = 1.0f / fl.width(), sy = 1.0f / fl.height();
    const float len = (m_shape == SHAPE_DART ? 15.0f : 12.0f) * m_boidSize;
    const float wid = (m_shape == SHAPE_DART ? 2.6f : 4.2f) * m_boidSize;
    int mode = m_boidColour;
    if (mode == BC_AUTO)
      mode = combo ? BC_PALE : BC_ORIGINAL;
    uint32_t flockCol[boids::MAX_SPECIES];
    for (int s = 0; s < boids::MAX_SPECIES; s++)
      flockCol[s] = Pack(kFlockColours[s]);
    uint32_t wheel[64];
    if (mode == BC_HEADING)
      for (int i = 0; i < 64; i++)
        wheel[i] = Pack(Hsv(i / 64.0f, 0.8f, 1.0f));

    for (size_t i = 0; i < nb; i++)
    {
      const float vx = VX[i], vy = VY[i];
      const float s = std::sqrt(vx * vx + vy * vy);
      const float inv = s > 1e-6f ? 1.0f / s : 0.0f;
      const float hx = vx * inv, hy = vy * inv;
      uint32_t c;
      switch (mode)
      {
        case BC_FLOCK: c = flockCol[SP[i] & 3]; break;
        case BC_HEADING:
          c = wheel[static_cast<int>((std::atan2(hy, hx) * (0.5f / 3.14159265f) + 0.5f) * 63.999f) & 63];
          break;
        case BC_PALE: c = Whiten(T[i], 190); break;
        default: c = T[i]; break;
      }
      if (dots)
      {
        *out++ = {X[i] * sx, Y[i] * sy, c};
        continue;
      }
      // tip ahead of the centre, two tail corners behind, the tail darker
      const float tx = X[i] + hx * len * 0.6f, ty = Y[i] + hy * len * 0.6f;
      const float bx = X[i] - hx * len * 0.4f, by = Y[i] - hy * len * 0.4f;
      const uint32_t tail = Shade(c, 140);
      *out++ = {tx * sx, ty * sy, c};
      *out++ = {(bx - hy * wid) * sx, (by + hx * wid) * sy, tail};
      *out++ = {(bx + hy * wid) * sx, (by - hx * wid) * sy, tail};
    }
    const boids::Predator* P = fl.predators();
    const uint32_t hawk = Pack(1.0f, 0.25f, 0.15f);
    for (int q = 0; q < np; q++)
    {
      const float s = std::sqrt(P[q].vx * P[q].vx + P[q].vy * P[q].vy);
      const float hx = s > 1e-6f ? P[q].vx / s : 1.0f, hy = s > 1e-6f ? P[q].vy / s : 0.0f;
      if (dots)
      {
        *out++ = {P[q].x * sx, P[q].y * sy, hawk};
        continue;
      }
      const float L = 30.0f * m_boidSize, W = 11.0f * m_boidSize;
      const float bx = P[q].x - hx * L * 0.4f, by = P[q].y - hy * L * 0.4f;
      *out++ = {(P[q].x + hx * L * 0.6f) * sx, (P[q].y + hy * L * 0.6f) * sy, hawk};
      *out++ = {(bx - hy * W) * sx, (by + hx * W) * sy, Shade(hawk, 150)};
      *out++ = {(bx + hy * W) * sx, (by - hx * W) * sy, Shade(hawk, 150)};
    }
  }
  m_numTris = static_cast<size_t>(out - m_vertices.data()) - m_numPoints;
}

void CScreensaverEmergence::DriverLoop()
{
  std::unique_lock<std::mutex> lock(m_mutex);
  for (;;)
  {
    m_cv.wait(lock, [this] { return m_quit || m_kick > 0 || m_beginScene >= 0; });
    if (m_quit)
      return;
    const int n = m_kick;
    const int begin = m_beginScene;
    m_kick = 0;
    m_beginScene = -1;
    lock.unlock();

    if (begin >= 0)
      BeginScene(begin);
    const auto t0 = Clock::now();
    for (int i = 0; i < n; i++)
      m_world.Step(m_pool);
    const double ms = std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
    BuildSprites();

    lock.lock();
    if (begin >= 0)
      m_serial++;
    m_stepMs += ms;
    m_stepCount += n;
    m_busy = false;
    m_fresh = true;
  }
}

void CScreensaverEmergence::StopSimulation()
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

RGB CScreensaverEmergence::PaletteAt(float t) const
{
  const uint32_t* p = physarum::kPalettes[m_drawPalette];
  t = (t - std::floor(t)) * 7.0f;
  const int i = static_cast<int>(t) % 7;
  const float f = t - std::floor(t);
  const RGB a = Hex(p[i]), b = Hex(p[(i + 1) % 7]);
  return {a.r + (b.r - a.r) * f, a.g + (b.g - a.g) * f, a.b + (b.b - a.b) * f};
}

bool CScreensaverEmergence::Start()
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
  glGenBuffers(1, &m_spriteVbo);
  glGenTextures(1, &m_palTex);
  glGenTextures(1, &m_trailTex);
  m_texW = m_texH = m_texSpecies = 0;

  m_aspect = static_cast<float>(Width()) / static_cast<float>(std::max(1, Height()));
  m_world.slime.SetTone(m_brightness);

  // the first scene is set up here, before the driver thread exists
  m_scene = NextScene();
  m_beginSeed = m_rng();
  BeginScene(m_scene);
  m_world.Step(m_pool);
  BuildSprites();
  m_serial = 1;
  m_glSerial = ~0u;
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
  m_beginScene = -1;
  m_stepMs = 0;
  m_stepCount = 0;
  m_driver = std::thread([this] { DriverLoop(); });

  m_start0 = m_statsStart = m_lastFrame = m_sceneStart = Clock::now();
  m_switching = m_requested = false;
  m_credit = 1.0;
  m_frames = 0;
  m_loggedStats = false;
  kodi::Log(ADDON_LOG_INFO, "Emergence: detail %d, %d thread(s), first scene %s", m_set.detail, m_pool.threads(),
            emergence::SceneName(m_scene));
  return true;
}

void CScreensaverEmergence::Stop()
{
  StopSimulation();
  DeleteTrailBuffers();
  if (m_trailTex)
    glDeleteTextures(1, &m_trailTex);
  if (m_palTex)
    glDeleteTextures(1, &m_palTex);
  if (m_quadVbo)
    glDeleteBuffers(1, &m_quadVbo);
  if (m_spriteVbo)
    glDeleteBuffers(1, &m_spriteVbo);
#ifdef TARGET_DARWIN
  if (m_vao)
    glDeleteVertexArrays(1, &m_vao);
#endif
  for (SlimeProgram& p : m_slime)
  {
    if (p.program)
      glDeleteProgram(p.program);
    p = SlimeProgram{};
  }
  if (m_spriteProgram)
    glDeleteProgram(m_spriteProgram);
  if (m_fadeProgram)
    glDeleteProgram(m_fadeProgram);
  m_trailTex = m_palTex = m_quadVbo = m_spriteVbo = m_vao = m_spriteProgram = m_fadeProgram = 0;
}

// A new scene is in: size the trail texture for it and load its palette.
void CScreensaverEmergence::ApplySceneGL()
{
  glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
  m_drawPalette = m_palette;
  uint8_t pal[8 * 3];
  for (int i = 0; i < 8; i++)
  {
    const uint32_t c = physarum::kPalettes[m_drawPalette][i % 7];
    pal[i * 3] = static_cast<uint8_t>(c >> 16);
    pal[i * 3 + 1] = static_cast<uint8_t>(c >> 8);
    pal[i * 3 + 2] = static_cast<uint8_t>(c);
  }
  glBindTexture(GL_TEXTURE_2D, m_palTex);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, 8, 1, 0, GL_RGB, GL_UNSIGNED_BYTE, pal);

  if (HasBackdrop(m_world.scene()))
  {
    // the slime's trail picture, or in Reef the particles' density map
    const bool reef = m_world.scene() == emergence::SCENE_REEF;
    const int w = reef ? emergence::World::kDensityW : m_world.slime.width();
    const int h = reef ? emergence::World::kDensityH : m_world.slime.height();
    const int species = reef ? 1 : m_world.slime.species();
    if (w != m_texW || h != m_texH || species != m_texSpecies)
    {
      m_texW = w;
      m_texH = h;
      m_texSpecies = species;
      GLint internal;
#if defined(TARGET_DARWIN)
      static const GLenum kFormats[2] = {GL_RED, GL_RG};
      static const GLint kInternal[2] = {GL_R8, GL_RG8};
      m_texFormat = kFormats[m_texSpecies - 1];
      internal = kInternal[m_texSpecies - 1];
#else
      static const GLenum kFormats[2] = {GL_LUMINANCE, GL_LUMINANCE_ALPHA};
      m_texFormat = kFormats[m_texSpecies - 1];
      internal = static_cast<GLint>(m_texFormat);
#endif
      glBindTexture(GL_TEXTURE_2D, m_trailTex);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
      glTexImage2D(GL_TEXTURE_2D, 0, internal, m_texW, m_texH, 0, m_texFormat, GL_UNSIGNED_BYTE, nullptr);
    }
  }
  glBindTexture(GL_TEXTURE_2D, 0);
  glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
}

// Only while the driver thread is idle.
void CScreensaverEmergence::UploadFrame()
{
  if (HasBackdrop(m_world.scene()) && m_texW > 0)
  {
    const bool reef = m_world.scene() == emergence::SCENE_REEF;
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, m_trailTex);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, m_texW, m_texH, m_texFormat, GL_UNSIGNED_BYTE,
                    reef ? m_world.density().data() : m_world.slime.display());
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    glBindTexture(GL_TEXTURE_2D, 0);
  }
  glBindBuffer(GL_ARRAY_BUFFER, m_spriteVbo);
  glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(std::max<size_t>(1, m_vertices.size()) * sizeof(Vertex)),
               m_vertices.empty() ? nullptr : m_vertices.data(), GL_STREAM_DRAW);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  m_drawPoints = m_numPoints;
  m_drawTris = m_numTris;
}

void CScreensaverEmergence::DrawQuad(GLint aPos)
{
  glBindBuffer(GL_ARRAY_BUFFER, m_quadVbo);
  glEnableVertexAttribArray(static_cast<GLuint>(aPos));
  glVertexAttribPointer(static_cast<GLuint>(aPos), 2, GL_FLOAT, GL_FALSE, 0, nullptr);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
  glDisableVertexAttribArray(static_cast<GLuint>(aPos));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
}

void CScreensaverEmergence::DrawSlime(float fade, float phase)
{
  SlimeProgram* p = Slime(m_texSpecies);
  if (!p)
    return;
  glDisable(GL_BLEND);
  glUseProgram(p->program);
#if defined(TARGET_DARWIN)
  const float sel1[4] = {0, 1, 0, 0};
#else
  const float sel1[4] = {0, 0, 0, 1};
#endif
  glUniform4fv(p->uSel1, 1, sel1);
  glUniform2f(p->uM, phase, fade);
  const RGB c0 = PaletteAt(phase), c1 = PaletteAt(phase + 3.0f / 7.0f);
  glUniform3f(p->uC0, c0.r, c0.g, c0.b);
  glUniform3f(p->uC1, c1.r, c1.g, c1.b);
  glActiveTexture(GL_TEXTURE1);
  glBindTexture(GL_TEXTURE_2D, m_palTex);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, m_trailTex);
  DrawQuad(p->aPos);
  glActiveTexture(GL_TEXTURE1);
  glBindTexture(GL_TEXTURE_2D, 0);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, 0);
}

void CScreensaverEmergence::DrawSprites(float fade)
{
  if (m_drawPoints + m_drawTris == 0)
    return;
  glEnable(GL_BLEND);
#ifdef GL_PROGRAM_POINT_SIZE
  glEnable(GL_PROGRAM_POINT_SIZE);
#endif
  glUseProgram(m_spriteProgram);
  glUniform1f(m_suFade, fade);
  glBindBuffer(GL_ARRAY_BUFFER, m_spriteVbo);
  glEnableVertexAttribArray(static_cast<GLuint>(m_saPos));
  glVertexAttribPointer(static_cast<GLuint>(m_saPos), 2, GL_FLOAT, GL_FALSE, sizeof(Vertex), nullptr);
  if (m_saCol >= 0)
  {
    glEnableVertexAttribArray(static_cast<GLuint>(m_saCol));
    glVertexAttribPointer(static_cast<GLuint>(m_saCol), 4, GL_UNSIGNED_BYTE, GL_TRUE, sizeof(Vertex),
                          reinterpret_cast<const void*>(2 * sizeof(float)));
  }

  if (m_drawPoints)
  {
    // the original's point size is in px of a 900 px high screen
    float size = m_pointSize * static_cast<float>(Height()) / 900.0f;
    if (m_glow)
    {
      glBlendFunc(GL_SRC_ALPHA, GL_ONE);
      size *= 3.0f;
    }
    else
      glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glUniform1f(m_suPointSize, std::min(std::max(size, 1.0f), m_maxPointSize));
    glUniform1f(m_suPoints, m_glow ? 2.0f : 1.0f);
    glDrawArrays(GL_POINTS, 0, static_cast<GLsizei>(m_drawPoints));
  }
  if (m_drawTris)
  {
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    const bool dots = m_shape == SHAPE_DOT;
    glUniform1f(m_suPointSize,
                std::min(std::max(6.0f * m_boidSize * Height() / 1000.0f, 1.5f), m_maxPointSize));
    glUniform1f(m_suPoints, dots ? 1.0f : 0.0f);
    glDrawArrays(dots ? GL_POINTS : GL_TRIANGLES, static_cast<GLint>(m_drawPoints),
                 static_cast<GLsizei>(m_drawTris));
  }

  glDisableVertexAttribArray(static_cast<GLuint>(m_saPos));
  if (m_saCol >= 0)
    glDisableVertexAttribArray(static_cast<GLuint>(m_saCol));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
}

bool CScreensaverEmergence::EnsureTrailBuffers(int w, int h)
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
    kodi::Log(ADDON_LOG_ERROR, "Emergence: trail framebuffer incomplete; trails disabled");
    DeleteTrailBuffers();
    m_fadeFailed = true;
    return false;
  }
  m_fadeW = w;
  m_fadeH = h;
  m_fadeCur = 0;
  return true;
}

void CScreensaverEmergence::DeleteTrailBuffers()
{
  if (m_fadeFbo[0])
    glDeleteFramebuffers(2, m_fadeFbo);
  if (m_fadeTex[0])
    glDeleteTextures(2, m_fadeTex);
  m_fadeFbo[0] = m_fadeFbo[1] = 0;
  m_fadeTex[0] = m_fadeTex[1] = 0;
  m_fadeW = m_fadeH = 0;
}

void CScreensaverEmergence::Render()
{
  if (!m_spriteProgram)
    return;
  const auto now = Clock::now();
  const double frameDt = std::chrono::duration<double>(now - m_lastFrame).count();
  m_lastFrame = now;
  m_frames++;

  // --- scenes: after the scene's time, fade out, swap, fade in
  const double sceneLength = m_sceneMinutes * 60.0;
  const double sceneAge = std::chrono::duration<double>(now - m_sceneStart).count();
  if (!m_switching && sceneAge >= sceneLength)
  {
    m_switching = true;
    m_requested = false;
    m_switchStart = now;
  }
  float fade = static_cast<float>(std::min(1.0, sceneAge / kFadeSeconds));
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
    if (serial != m_glSerial)
    {
      ApplySceneGL();
      m_glSerial = serial;
      if (m_requested) // the new scene is in: start its clock and fade in
      {
        m_scene = m_world.scene();
        m_switching = m_requested = false;
        m_sceneStart = now;
        fade = 0.0f;
        if (m_trails > 0 && m_fadeFbo[0])
          DeleteTrailBuffers(); // no ghost of the last scene
      }
    }
    if (fresh)
      UploadFrame();

    int begin = -1;
    if (m_switching && !m_requested && fade <= 0.0f)
    {
      begin = NextScene();
      m_requested = true;
    }
    // Steps are earned at the chosen rate and spent whenever the simulation
    // is free (Physarum v2's step credit): the same speed on any refresh rate,
    // and a box that cannot keep up slows down instead of piling up a backlog.
    const int steps = m_requested && begin < 0 ? 0 : std::min(static_cast<int>(m_credit), m_pace == PACE_FAST ? 2 : 1);
    if (steps > 0 || begin >= 0)
    {
      m_credit -= steps;
      {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_kick = std::max(steps, 1);
        m_beginScene = begin;
        m_beginSeed = m_rng();
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
      kodi::Log(ADDON_LOG_INFO, "Emergence: %.2f ms per step, %.1f steps/s, %.1f frames/s (%s, %d thread(s))",
                ms / count, count / statsAge, m_frames / statsAge, emergence::SceneName(m_scene),
                m_pool.threads());
    m_loggedStats = true;
  }

  // --- draw
  fade = fade * fade * (3.0f - 2.0f * fade);
  const float bright = fade * (1.0f - m_dim);
  const double t = std::chrono::duration<double>(now - m_start0).count();
  const float phase = static_cast<float>(std::fmod(t * m_cycle * 0.02, 1.0));
  const bool requestPending = m_requested; // the world may be mid-Begin: draw nothing of it
  const int scene = m_world.scene();
  const bool slime = !requestPending && HasBackdrop(scene) && m_glSerial == serial && m_texW > 0;

  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
#ifdef TARGET_DARWIN
  glBindVertexArray(m_vao);
#endif

  if (!slime && !requestPending && m_trails > 0 && EnsureTrailBuffers(Width(), Height()))
  {
    static const float kKeep[] = {1.0f, 0.78f, 0.88f, 0.94f};
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
    DrawSprites(1.0f);

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
    if (slime)
      // in a combination the slime steps back a little so the particles and
      // the flock read on top of it
      DrawSlime(bright * (scene == emergence::SCENE_REEF ? 0.45f : emergence::IsCombination(scene) ? 0.8f : 1.0f),
                phase);
    else
    {
      glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
      glClear(GL_COLOR_BUFFER_BIT);
    }
    if (!requestPending)
      DrawSprites(bright);
  }

  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif
  glUseProgram(0);
}

ADDONCREATOR(CScreensaverEmergence)

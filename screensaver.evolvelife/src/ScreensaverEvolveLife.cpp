// Kodi screensaver shell around EvolveLife (Section 14 of EvolveLife.md).
//
// Three threads besides Kodi's: the evolver (evolution.h: breeds and
// evaluates generations over a low-priority worker pool, never more than a
// few generations ahead of what the stage has shown), and the driver, which
// ticks the stage at 60 Hz one step ahead of the picture and builds its quad
// batches; Render() only uploads the last batches and draws them, so it never
// waits. As in Alien Life and Emergence, steps are earned at 60 a second and
// spent whenever the driver is free, so a box that cannot keep up slows
// down instead of piling up a backlog.
//
// Drawing is plain OpenGL / OpenGL ES 2: one shader whose look (flat,
// capsule, glow, panel, disc, line) is chosen per vertex, plus a text shader
// on a baked font atlas, three draws a frame from one static quad index
// buffer, premultiplied alpha throughout (glows are additive in the same
// draw). Kodi's GL state is restored afterwards.

#include "Stage.h"

#include <kodi/addon-instance/Screensaver.h>
#include <kodi/gui/gl/GL.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <vector>

namespace
{

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
attribute vec2 a_pos;   // clip space
attribute vec2 a_uv;
attribute vec4 a_col;   // premultiplied
attribute vec4 a_par;   // look, then three look parameters (bytes)
varying vec2 v_uv;
varying vec4 v_col;
varying vec4 v_par;
void main()
{
  gl_Position = vec4(a_pos, 0.0, 1.0);
  v_uv = a_uv;
  v_col = a_col;
  v_par = a_par * 255.0;
}
)";

// Looks: 0 flat (dithered), 1 capsule, 2 glow, 3 panel, 4 disc, 5 line
// (keep in step with evo::Look in Draw.h).
const char* kShapeFragmentShader = R"(
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_uv;
varying vec4 v_col;
varying vec4 v_par;
void main()
{
  float look = v_par.x;
  vec4 c = v_col;
  if (look < 0.5)
  {
    // a little noise against banding on the dark gradients
    float n = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
    gl_FragColor = vec4(c.rgb + vec3((n - 0.5) / 255.0), c.a);
  }
  else if (look < 1.5)
  {
    // a capsule: soft lit body, glowing rim, stripes, a motor glow
    float h = v_par.y / 10.0;
    float aa = max(v_par.z / 64.0, 0.02);
    float stripes = floor(v_par.w / 16.0) / 15.0;
    float drive = mod(v_par.w, 16.0) / 15.0;
    vec2 q = vec2(max(abs(v_uv.x) - h, 0.0), v_uv.y);
    float d = length(q);
    float alpha = 1.0 - smoothstep(1.0 - aa, 1.0, d);
    float nz = sqrt(max(1.0 - d * d, 0.0));
    float shade = 0.42 + 0.58 * nz;
    float rim = (1.0 - nz) * (1.0 - nz) * (1.0 - nz);
    float stripe = 1.0 - stripes * 0.32 * step(0.0, sin(v_uv.x * 2.4));
    vec3 col = c.rgb * (shade * stripe + rim * 0.9 + drive * 0.55) + vec3(c.a) * 0.10 * nz * nz * nz * nz;
    gl_FragColor = vec4(col, c.a) * alpha;
  }
  else if (look < 2.5)
  {
    float d2 = dot(v_uv, v_uv);
    float g = exp(-d2 * 4.0) * (1.0 - smoothstep(0.6, 1.0, d2));
    gl_FragColor = c * g;
  }
  else if (look < 3.5)
  {
    // rounded glass panel with a faint bright edge
    float aspect = v_par.y / 16.0;
    float rad = v_par.z / 255.0;
    float aa = max(v_par.w / 1020.0, 0.002);
    vec2 q = abs(v_uv) - vec2(aspect - rad, 1.0 - rad);
    float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - rad;
    float fill = 1.0 - smoothstep(-aa, aa, d);
    float edge = 1.0 - smoothstep(0.0, aa * 1.5, abs(d + aa * 1.5));
    gl_FragColor = c * fill + vec4(vec3(0.22 * c.a * 2.0), 0.0) * edge;
  }
  else if (look < 4.5)
  {
    float d = length(v_uv);
    float core = 1.0 - smoothstep(0.82, 1.0, d);
    float halo = exp(-d * d * 1.6) * 0.35 * (1.0 - core);
    gl_FragColor = vec4(c.rgb * (core + halo), c.a * core);
  }
  else
  {
    float a = 1.0 - smoothstep(0.65, 1.25, abs(v_uv.y));
    gl_FragColor = c * a;
  }
}
)";

const char* kTextFragmentShader = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_tex;
uniform vec2 u_shadow;
varying vec2 v_uv;
varying vec4 v_col;
varying vec4 v_par;
void main()
{
  float a = texture2D(u_tex, v_uv).a;
  float s = texture2D(u_tex, v_uv - u_shadow).a;
  gl_FragColor = v_col * a + vec4(0.0, 0.0, 0.0, s * (1.0 - a) * 0.8 * v_col.a);
}
)";

constexpr int kMaxQuads = 16000; // per draw (16-bit indices)

enum Profile
{
  PROF_AUTO,
  PROF_LOW,
  PROF_BALANCED,
  PROF_HIGH
};

enum LogLevel
{
  LOG_OFF,
  LOG_SUMMARY,
  LOG_VERBOSE
};

} // namespace

class ATTR_DLL_LOCAL CScreensaverEvolveLife : public kodi::addon::CAddonBase, public kodi::addon::CInstanceScreensaver
{
public:
  CScreensaverEvolveLife() = default;
  ~CScreensaverEvolveLife() override { StopThreads(); }

  bool Start() override;
  void Stop() override;
  void Render() override;

private:
  using Clock = std::chrono::steady_clock;

  void LoadSettings();
  GLuint Compile(GLenum type, const std::string& src);
  GLuint Link(const char* vs, const char* fs);
  bool BuildGL();
  void DriverLoop();
  void EvolverLoop();
  void StopThreads();
  void Upload();
  void DrawBatch(GLuint program, GLuint vbo, size_t quads);
  void Governor(double tickMs);

  evo::Evolution m_evo;
  evo::Stage m_stage;
  evo::WorkerPool m_pool;
  evo::Config m_cfg;
  evo::StageOptions m_opts;
  uint64_t m_seed = 0;

  // evolver thread
  std::thread m_evolver;
  std::mutex m_evoMutex;
  std::condition_variable m_evoCv;
  bool m_evoQuit = false;
  int m_ahead = 3; // generations the evolver may run past the stage
  int m_logLevel = LOG_SUMMARY;
  int m_lastLoggedEpoch = 0;

  // driver thread
  std::thread m_driver;
  std::mutex m_mutex;
  std::condition_variable m_cv;
  int m_kick = 0;
  bool m_busy = false, m_fresh = false, m_quit = false;
  double m_tickMs = 0.0; // guarded by m_mutex
  long m_tickCount = 0;

  // governor (driver thread)
  double m_govSum = 0.0;
  int m_govN = 0, m_govGood = 0, m_lowered = 0, m_baseVisible = 24, m_baseParallax = 3;

  // GL
  GLuint m_shapeProgram = 0, m_textProgram = 0;
  GLint m_aPos[2] = {-1, -1}, m_aUv[2] = {-1, -1}, m_aCol[2] = {-1, -1}, m_aPar[2] = {-1, -1};
  GLint m_uTex = -1, m_uShadow = -1;
  GLuint m_vbo[3] = {0, 0, 0}, m_ibo = 0, m_vao = 0, m_fontTex = 0;
  size_t m_drawQuads[3] = {0, 0, 0};

  // settings that stay in the shell
  int m_threads = 0;
  float m_aspect = 16.0f / 9.0f;

  Clock::time_point m_start, m_lastFrame, m_statsStart;
  double m_credit = 0.0;
  long m_frames = 0;
  bool m_loggedStats = false;
  float m_fps = 60.0f;
};

//------------------------------------------------------------------------------

void CScreensaverEvolveLife::LoadSettings()
{
  using kodi::addon::GetSettingBoolean;
  using kodi::addon::GetSettingInt;
  auto opt = [](const char* id, int def, int lo, int hi) { return std::min(std::max(GetSettingInt(id, def), lo), hi); };

  // performance profile: Low (TV sticks), Balanced, High; Auto by platform
  int profile = opt("profile", PROF_AUTO, 0, 3);
  if (profile == PROF_AUTO)
  {
    const unsigned hw = std::thread::hardware_concurrency();
#if defined(TARGET_ANDROID)
    profile = (sizeof(void*) == 4 || hw <= 4) ? PROF_LOW : PROF_BALANCED;
#else
    profile = hw >= 8 ? PROF_HIGH : PROF_BALANCED;
#endif
  }
  const int p = profile - 1; // 0 low .. 2 high (keep in step with tests/sim_test.cpp)
  static const int kPop[] = {32, 60, 120};
  static const int kSegs[] = {8, 12, 16};
  static const int kTrials[] = {1, 1, 2};
  static const int kSpecies[] = {4, 6, 8};
  static const int kVisible[] = {12, 24, 48};
  static const int kParallax[] = {2, 3, 5};
  m_cfg = evo::Config();
  static const int kPopulation[] = {0, 24, 40, 60, 100, 150, 250};
  const int pop = kPopulation[opt("population", 0, 0, 6)];
  m_cfg.population = pop > 0 ? pop : kPop[p];
  m_cfg.trials = kTrials[p];
  m_cfg.targetSpecies = kSpecies[p];
  static const int kComplexity[] = {0, 6, 10, 16};
  const int cx = kComplexity[opt("complexity", 0, 0, 3)];
  m_cfg.maxSegs = cx > 0 ? cx : kSegs[p];
  const int goal = opt("goal", 0, 0, evo::GOAL_COUNT);
  m_cfg.goal = goal == 0 ? -1 : goal - 1;
  static const int kEpoch[] = {0, 10, 20, 40, -1};
  m_cfg.epochGens = kEpoch[opt("goal_change", 0, 0, 4)];
  static const float kMutation[] = {0.5f, 1.0f, 1.8f};
  m_cfg.mutation = kMutation[opt("mutation", 1, 0, 2)];
  static const float kImmigrants[] = {0.0f, 0.05f, 0.08f, 0.12f};
  m_cfg.immigrants = kImmigrants[opt("immigrants", 2, 0, 3)];
  m_cfg.varyGravity = GetSettingBoolean("vary_gravity", true);
  static const int kAhead[] = {1, 3, 8, 20};
  m_ahead = kAhead[opt("speed", 1, 0, 3)];

  m_opts = evo::StageOptions();
  const int quality = opt("quality", 0, 0, 3);
  const int q = quality == 0 ? p : quality - 1;
  m_opts.visible = kVisible[q];
  m_opts.parallax = kParallax[q];
  m_opts.motes = GetSettingBoolean("motes", true);
  m_opts.camera = opt("camera", evo::CAM_CINEMATIC, 0, 2);
  m_opts.insight = opt("insight", evo::INS_RICH, 0, 3);
  m_opts.neural = GetSettingBoolean("neural", true);
  m_opts.ticker = GetSettingBoolean("ticker", true);
  m_opts.labels = GetSettingBoolean("labels", true);
  static const float kCardSeconds[] = {15.0f, 25.0f, 40.0f};
  m_opts.cardSeconds = kCardSeconds[opt("card_seconds", 1, 0, 2)];
  static const char* kCardIds[evo::CARD_COUNT] = {"card_profile", "card_briefing", "card_totals", "card_fitness",
                                                  "card_species", "card_brain",    "card_family", "card_thennow",
                                                  "card_milestones", "card_hall",  "card_commentary", "card_facts",
                                                  "card_map"};
  m_opts.cards = 0;
  for (int c = 0; c < evo::CARD_COUNT; c++)
    if (GetSettingBoolean(kCardIds[c], true))
      m_opts.cards |= 1u << c;
  m_opts.palette = opt("palette", evo::PAL_AUTO, 0, evo::PAL_COUNT - 1);
  m_opts.bright = static_cast<float>(opt("brightness", 100, 30, 100)) / 100.0f;
  m_opts.textScale = static_cast<float>(opt("text_size", 100, 70, 150)) / 100.0f;
  m_baseVisible = m_opts.visible;
  m_baseParallax = m_opts.parallax;

  m_logLevel = opt("log", LOG_SUMMARY, 0, 2);
  m_threads = opt("threads", 0, 0, 4);
  const std::string seed = kodi::addon::GetSettingString("seed", "");
  m_seed = seed.empty() ? 0 : std::strtoull(seed.c_str(), nullptr, 10);
  if (m_seed == 0)
    m_seed = (static_cast<uint64_t>(std::random_device{}()) << 32) ^ std::random_device{}() ^
             static_cast<uint64_t>(Clock::now().time_since_epoch().count());
}

GLuint CScreensaverEvolveLife::Compile(GLenum type, const std::string& src)
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
    kodi::Log(ADDON_LOG_ERROR, "EvolveLife: shader compile failed: %s", log);
    glDeleteShader(shader);
    return 0;
  }
  return shader;
}

GLuint CScreensaverEvolveLife::Link(const char* vsSrc, const char* fsSrc)
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
    kodi::Log(ADDON_LOG_ERROR, "EvolveLife: program link failed: %s", log);
    glDeleteProgram(program);
    return 0;
  }
  return program;
}

bool CScreensaverEvolveLife::BuildGL()
{
  m_shapeProgram = Link(kVertexShader, kShapeFragmentShader);
  m_textProgram = Link(kVertexShader, kTextFragmentShader);
  if (!m_shapeProgram || !m_textProgram)
    return false;
  const GLuint progs[2] = {m_shapeProgram, m_textProgram};
  for (int i = 0; i < 2; i++)
  {
    m_aPos[i] = glGetAttribLocation(progs[i], "a_pos");
    m_aUv[i] = glGetAttribLocation(progs[i], "a_uv");
    m_aCol[i] = glGetAttribLocation(progs[i], "a_col");
    m_aPar[i] = glGetAttribLocation(progs[i], "a_par");
  }
  m_uTex = glGetUniformLocation(m_textProgram, "u_tex");
  m_uShadow = glGetUniformLocation(m_textProgram, "u_shadow");

#ifdef TARGET_DARWIN
  glGenVertexArrays(1, &m_vao);
  glBindVertexArray(m_vao);
#endif
  glGenBuffers(3, m_vbo);
  // one index buffer for every batch: two triangles per quad
  std::vector<uint16_t> idx(static_cast<size_t>(kMaxQuads) * 6);
  for (int q = 0; q < kMaxQuads; q++)
  {
    const uint16_t b = static_cast<uint16_t>(q * 4);
    uint16_t* o = &idx[static_cast<size_t>(q) * 6];
    o[0] = b;
    o[1] = static_cast<uint16_t>(b + 1);
    o[2] = static_cast<uint16_t>(b + 2);
    o[3] = static_cast<uint16_t>(b + 2);
    o[4] = static_cast<uint16_t>(b + 1);
    o[5] = static_cast<uint16_t>(b + 3);
  }
  glGenBuffers(1, &m_ibo);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, m_ibo);
  glBufferData(GL_ELEMENT_ARRAY_BUFFER, static_cast<GLsizeiptr>(idx.size() * sizeof(uint16_t)), idx.data(), GL_STATIC_DRAW);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);

  // the font atlas: white with the glyph coverage in alpha (RGBA works on every GL)
  std::vector<uint8_t> rgba(static_cast<size_t>(evo::font::kAtlasW) * evo::font::kAtlasH * 4, 255);
  size_t px = 0;
  const size_t total = static_cast<size_t>(evo::font::kAtlasW) * evo::font::kAtlasH;
  for (unsigned i = 0; i < evo::font::kRleSize && px < total; i++)
  {
    const uint8_t b = evo::font::kRle[i];
    if (b == 0 && i + 1 < evo::font::kRleSize)
    {
      const unsigned run = evo::font::kRle[++i];
      for (unsigned k = 0; k < run && px < total; k++)
        rgba[4 * px++ + 3] = 0;
    }
    else
      rgba[4 * px++ + 3] = b;
  }
  glGenTextures(1, &m_fontTex);
  glBindTexture(GL_TEXTURE_2D, m_fontTex);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, evo::font::kAtlasW, evo::font::kAtlasH, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
  glGenerateMipmap(GL_TEXTURE_2D);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glBindTexture(GL_TEXTURE_2D, 0);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif
  return true;
}

// The driver: m_kick stage ticks, then the batches for the newest one.
void CScreensaverEvolveLife::DriverLoop()
{
  std::unique_lock<std::mutex> lock(m_mutex);
  for (;;)
  {
    m_cv.wait(lock, [this] { return m_quit || m_kick > 0; });
    if (m_quit)
      return;
    const int n = m_kick;
    m_kick = 0;
    lock.unlock();

    const auto t0 = Clock::now();
    for (int i = 0; i < n; i++)
    {
      m_stage.Tick(m_evo.Latest());
      m_evoCv.notify_one(); // the stage may have taken a generation
    }
    m_stage.Build();
    const double ms = std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
    Governor(ms / std::max(n, 1));

    lock.lock();
    m_tickMs += ms;
    m_tickCount += n;
    m_busy = false;
    m_fresh = true;
  }
}

// Adaptive quality (Section 10.2): if the stage costs too much a tick, show
// fewer creatures and background layers; cautiously restore them later.
void CScreensaverEvolveLife::Governor(double tickMs)
{
  m_govSum += tickMs;
  if (++m_govN < 180) // three seconds
    return;
  const double avg = m_govSum / m_govN;
  m_govSum = 0.0;
  m_govN = 0;
  if (avg > 9.0 && m_stage.visible() > 6)
  {
    m_stage.SetVisible(std::max(6, m_stage.visible() / 2));
    m_stage.SetMotes(false, std::max(1, m_baseParallax - 1 - m_lowered));
    m_lowered++;
    m_govGood = 0;
    m_stage.Notice("Showing fewer creatures to keep the picture smooth");
    kodi::Log(ADDON_LOG_INFO, "EvolveLife: %.1f ms a tick, quality lowered (%d creatures on stage)", avg, m_stage.visible());
  }
  else if (m_lowered > 0 && avg < 3.0 && ++m_govGood >= 20) // a minute of easy frames
  {
    m_lowered--;
    m_stage.SetVisible(std::min(m_baseVisible, m_stage.visible() * 2));
    m_stage.SetMotes(m_lowered == 0 && m_opts.motes, m_baseParallax - m_lowered);
    m_govGood = 0;
    kodi::Log(ADDON_LOG_INFO, "EvolveLife: quality raised (%d creatures on stage)", m_stage.visible());
  }
}

// The evolver: generations, never more than m_ahead past the stage.
void CScreensaverEvolveLife::EvolverLoop()
{
  evo::LowerThreadPriority();
  uint32_t lastSeq = 0;
  for (;;)
  {
    {
      std::unique_lock<std::mutex> lock(m_evoMutex);
      m_evoCv.wait_for(lock, std::chrono::milliseconds(200), [this] {
        return m_evoQuit || m_evo.generation() - 1 - m_stage.consumed() < m_ahead;
      });
      if (m_evoQuit)
        return;
      if (m_evo.generation() - 1 - m_stage.consumed() >= m_ahead)
        continue;
    }
    m_evo.RunGeneration(m_pool);
    if (m_evo.cancelled())
      return;
    const auto s = m_evo.Latest();
    if (!s || m_logLevel == LOG_OFF)
      continue;
    if (s->epoch != m_lastLoggedEpoch)
    {
      m_lastLoggedEpoch = s->epoch;
      kodi::Log(ADDON_LOG_INFO, "EvolveLife: epoch %d, goal \"%s\" on %s, gravity %.2f g, friction %.2f", s->epoch,
                evo::GoalName(s->world->goal), evo::TerrainName(s->world->terrain), s->world->gravity / 9.8f,
                s->world->friction);
    }
    const evo::GenStats& g = s->history.back();
    kodi::Log(ADDON_LOG_INFO, "EvolveLife: generation %d: best %.2f (%s), mean %.2f, %d species, %.0f ms", s->generation,
              g.best, s->pop[0].name, g.mean, g.species, s->evalMs);
    if (m_logLevel == LOG_VERBOSE)
      for (const evo::Event& e : s->events)
        if (e.seq > lastSeq)
          kodi::Log(ADDON_LOG_INFO, "EvolveLife: event: %s", e.text);
    if (!s->events.empty())
      lastSeq = s->events.back().seq;
  }
}

void CScreensaverEvolveLife::StopThreads()
{
  if (m_evolver.joinable())
  {
    m_evo.Cancel();
    {
      std::lock_guard<std::mutex> lock(m_evoMutex);
      m_evoQuit = true;
    }
    m_evoCv.notify_all();
    m_evolver.join();
  }
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

bool CScreensaverEvolveLife::Start()
{
  LoadSettings();
  if (!BuildGL())
    return false;
  m_aspect = static_cast<float>(Width()) / static_cast<float>(std::max(1, Height()));

  int threads = m_threads;
  if (threads == 0)
  {
    // leave a core for Kodi and one for the stage
    const unsigned hw = std::thread::hardware_concurrency();
    threads = std::min(std::max(static_cast<int>(hw) - 2, 1), 4);
  }
  m_pool.Start(threads, true);
  m_evo.Reset(m_cfg, m_seed);
  m_stage.Reset(m_opts, m_seed);
  m_stage.SetScreen(Width(), Height());
  m_stage.Build();
  m_fresh = true;
  m_busy = false;
  m_quit = false;
  m_kick = 0;
  m_evoQuit = false;
  m_tickMs = 0;
  m_tickCount = 0;
  m_govSum = 0;
  m_govN = m_govGood = m_lowered = 0;
  m_lastLoggedEpoch = 0;
  m_driver = std::thread([this] { DriverLoop(); });
  m_evolver = std::thread([this] { EvolverLoop(); });

  m_start = m_lastFrame = m_statsStart = Clock::now();
  m_credit = 1.0;
  m_frames = 0;
  m_loggedStats = false;
  kodi::Log(ADDON_LOG_INFO,
            "EvolveLife: seed %llu, %d creatures, up to %d segments, %d trial(s), %d eval thread(s), %d on stage, "
            "%d generation(s) a round",
            static_cast<unsigned long long>(m_seed), m_cfg.population, m_cfg.maxSegs, m_cfg.trials, m_pool.threads(),
            m_opts.visible, m_ahead);
  return true;
}

void CScreensaverEvolveLife::Stop()
{
  const auto t0 = Clock::now();
  StopThreads();
  for (GLuint& b : m_vbo)
  {
    if (b)
      glDeleteBuffers(1, &b);
    b = 0;
  }
  if (m_ibo)
    glDeleteBuffers(1, &m_ibo);
  m_ibo = 0;
  if (m_fontTex)
    glDeleteTextures(1, &m_fontTex);
  m_fontTex = 0;
#ifdef TARGET_DARWIN
  if (m_vao)
    glDeleteVertexArrays(1, &m_vao);
  m_vao = 0;
#endif
  for (GLuint* p : {&m_shapeProgram, &m_textProgram})
  {
    if (*p)
      glDeleteProgram(*p);
    *p = 0;
  }
  kodi::Log(ADDON_LOG_INFO, "EvolveLife: stopped in %.0f ms after %d generations",
            std::chrono::duration<double, std::milli>(Clock::now() - t0).count(), m_evo.generation());
}

// Render thread, while the driver is idle.
void CScreensaverEvolveLife::Upload()
{
  evo::Batch* batches[3] = {&m_stage.world, &m_stage.hud, &m_stage.text};
  for (int i = 0; i < 3; i++)
  {
    const size_t quads = std::min(batches[i]->quads(), static_cast<size_t>(kMaxQuads));
    glBindBuffer(GL_ARRAY_BUFFER, m_vbo[i]);
    glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(quads * 4 * sizeof(evo::Vertex)),
                 quads ? batches[i]->v.data() : nullptr, GL_STREAM_DRAW);
    m_drawQuads[i] = quads;
  }
  glBindBuffer(GL_ARRAY_BUFFER, 0);
}

void CScreensaverEvolveLife::DrawBatch(GLuint program, GLuint vbo, size_t quads)
{
  if (quads == 0)
    return;
  const int pi = program == m_shapeProgram ? 0 : 1;
  glUseProgram(program);
  glBindBuffer(GL_ARRAY_BUFFER, vbo);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, m_ibo);
  const GLsizei stride = sizeof(evo::Vertex);
  auto attr = [&](GLint loc, int n, GLenum type, GLboolean norm, size_t off) {
    if (loc < 0)
      return;
    glEnableVertexAttribArray(static_cast<GLuint>(loc));
    glVertexAttribPointer(static_cast<GLuint>(loc), n, type, norm, stride, reinterpret_cast<const void*>(off));
  };
  attr(m_aPos[pi], 2, GL_FLOAT, GL_FALSE, 0);
  attr(m_aUv[pi], 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float));
  attr(m_aCol[pi], 4, GL_UNSIGNED_BYTE, GL_TRUE, 4 * sizeof(float));
  attr(m_aPar[pi], 4, GL_UNSIGNED_BYTE, GL_TRUE, 4 * sizeof(float) + sizeof(uint32_t));
  glDrawElements(GL_TRIANGLES, static_cast<GLsizei>(quads * 6), GL_UNSIGNED_SHORT, nullptr);
  for (GLint loc : {m_aPos[pi], m_aUv[pi], m_aCol[pi], m_aPar[pi]})
    if (loc >= 0)
      glDisableVertexAttribArray(static_cast<GLuint>(loc));
}

void CScreensaverEvolveLife::Render()
{
  if (!m_shapeProgram)
    return;
  const auto now = Clock::now();
  const double frameDt = std::chrono::duration<double>(now - m_lastFrame).count();
  m_lastFrame = now;
  m_frames++;
  if (frameDt > 0)
    m_fps += (static_cast<float>(1.0 / frameDt) - m_fps) * 0.02f;

  // the last finished tick goes to the GPU, and the next tick starts
  bool busy, fresh;
  {
    std::lock_guard<std::mutex> lock(m_mutex);
    busy = m_busy;
    fresh = m_fresh;
    m_fresh = false;
  }
  m_credit = std::min(m_credit + 60.0 * std::min(frameDt, 0.1), 2.0);
  if (!busy)
  {
    if (fresh)
      Upload();
    const int steps = std::min(static_cast<int>(m_credit), 2);
    if (steps > 0)
    {
      m_credit -= steps;
      const double ms = m_tickCount > 0 ? m_tickMs / static_cast<double>(m_tickCount) : 0.0;
      m_stage.SetPerf(static_cast<float>(ms), m_fps, m_pool.threads());
      {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_kick = steps;
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
      ms = m_tickMs;
      count = m_tickCount;
    }
    const auto s = m_evo.Latest();
    if (count > 0)
      kodi::Log(ADDON_LOG_INFO,
                "EvolveLife: %.2f ms per stage tick, %.1f ticks/s, %.1f frames/s, %zu quads, generation %d (%.0f ms each)",
                ms / count, count / statsAge, m_frames / statsAge, m_drawQuads[0] + m_drawQuads[1] + m_drawQuads[2],
                s ? s->generation : -1, s ? s->evalMs : 0.0);
    m_loggedStats = true;
  }

  // draw
  glViewport(X(), Y(), Width(), Height());
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
  glClear(GL_COLOR_BUFFER_BIT);
#ifdef TARGET_DARWIN
  glBindVertexArray(m_vao);
#endif
  glEnable(GL_BLEND);
  glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
  DrawBatch(m_shapeProgram, m_vbo[0], m_drawQuads[0]);
  DrawBatch(m_shapeProgram, m_vbo[1], m_drawQuads[1]);
  glUseProgram(m_textProgram);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, m_fontTex);
  glUniform1i(m_uTex, 0);
  glUniform2f(m_uShadow, 2.0f / evo::font::kAtlasW, 2.0f / evo::font::kAtlasH);
  DrawBatch(m_textProgram, m_vbo[2], m_drawQuads[2]);
  glBindTexture(GL_TEXTURE_2D, 0);

  // leave Kodi's state as it expects it
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif
  glUseProgram(0);
}

ADDONCREATOR(CScreensaverEvolveLife)

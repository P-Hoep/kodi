// Kodi screensaver wrapper around the Physarum v2 simulation.
//
// The simulation runs on the CPU (see Physarum.h) on its own driver thread
// plus a small worker pool, one step ahead of the picture: Render() never
// waits for it. When a step has finished, Render() uploads its 8-bit picture
// (one byte per trail cell and species) into one texture and kicks off the
// next step; then it draws one full-screen quad that colours the texture.
// The fragment shader is compiled for the chosen colour mode and species
// count, so it is a texture read, a palette read and a few multiplies.
// Plain OpenGL / OpenGL ES 2; no float textures, no render targets, no vertex
// texture fetch.

#include "Physarum.h"
#include "WorkerPool.h"

#include <kodi/addon-instance/Screensaver.h>
#include <kodi/gui/gl/GL.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <mutex>
#include <random>
#include <string>
#include <thread>

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

const char* kVertexShader = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;
varying vec2 v_uv;
void main()
{
  gl_Position = vec4(a_pos, 0.0, 1.0);
  v_uv = vec2(a_pos.x * 0.5 + 0.5, 0.5 - a_pos.y * 0.5); // trail row 0 is the top
}
)";

// MODE and SPECIES are #defined in front of this when the program is built.
// The texture holds the tone-mapped density of each species (0..1).
const char* kFragmentShader = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_trail;
uniform sampler2D u_pal;      // 8 x 1: the 7 palette colours and the first again
uniform vec4 u_sel1;          // picks species 2 / 3 out of the texel
uniform vec4 u_sel2;
uniform vec2 u_m;             // palette phase, fade (fade x dim)
uniform vec3 u_c0;
uniform vec3 u_c1;
uniform vec3 u_c2;
uniform vec3 u_colour;
uniform vec3 u_bg;
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
  float c = dot(t, u_sel2);
  float d = min(a + b + c, 1.0);
  vec3 sp = u_c0 * a + u_c1 * b + u_c2 * c;
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
#elif MODE == 2        // fire
  col = clamp(vec3(d * 1.7, d2 * 1.5, d2 * d2 * 1.3), 0.0, 1.0);
#else                  // one colour
  col = u_colour * d + vec3(d2 * d2 * d * 0.4);
#endif
  gl_FragColor = vec4(u_bg + col * u_m.y, 1.0);
}
)";

enum Mode { MODE_PALETTE, MODE_NEON, MODE_FIRE, MODE_ONE_COLOUR, MODE_COUNT };
enum Pace { PACE_NORMAL, PACE_FAST, PACE_SLOW };

// Option lists (tools/make_settings_physarum_v2.py has the same order).
const size_t kAgentCounts[] = {25000, 50000, 100000, 150000, 250000, 500000, 1000000};
const int kTrailSizes[][2] = {{320, 180}, {480, 270}, {640, 360}, {800, 450},
                              {960, 540}, {1280, 720}, {1920, 1080}};
const int kRestartMinutes[] = {0, 2, 5, 10, 20, 30, 60};
constexpr int PRESET_RANDOM = physarum::kNumPresets;     // a different one on each restart
constexpr int PRESET_CUSTOM = physarum::kNumPresets + 1;

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

// Kodi's colour button stores "AARRGGBB".
RGB SettingColour(const std::string& id, uint32_t fallback)
{
  const std::string s = kodi::addon::GetSettingString(id, "");
  if (s.size() < 6)
    return Hex(fallback);
  const uint32_t v = static_cast<uint32_t>(std::strtoul(s.c_str(), nullptr, 16));
  return Hex(v & 0xFFFFFF);
}

} // namespace

class ATTR_DLL_LOCAL CScreensaverPhysarum : public kodi::addon::CAddonBase,
                                             public kodi::addon::CInstanceScreensaver
{
public:
  CScreensaverPhysarum() = default;
  ~CScreensaverPhysarum() override { StopSimulation(); }

  bool Start() override;
  void Stop() override;
  void Render() override;

private:
  using Clock = std::chrono::steady_clock;

  void LoadSettings();
  GLuint Compile(GLenum type, const std::string& src);
  bool BuildProgram();
  void NewRun(bool first);
  void Upload();
  void DriverLoop();
  void StopSimulation();
  RGB PaletteAt(float t) const;

  physarum::Simulation m_sim;
  physarum::WorkerPool m_pool;
  std::mt19937 m_rng{std::random_device{}()};

  // the driver thread: runs m_kick steps whenever Render() asks
  std::thread m_driver;
  std::mutex m_mutex;
  std::condition_variable m_cv;
  int m_kick = 0;
  bool m_busy = false;
  bool m_fresh = false;
  bool m_quit = false;
  double m_stepMs = 0.0; // guarded by m_mutex
  long m_stepCount = 0;

  // GL
  GLuint m_program = 0, m_vbo = 0, m_vao = 0, m_trailTex = 0, m_palTex = 0;
  GLint m_aPos = -1, m_uSel1 = -1, m_uSel2 = -1, m_uM = -1, m_uC[3] = {-1, -1, -1}, m_uColour = -1,
        m_uBg = -1;
  GLenum m_texFormat = 0;

  // settings
  int m_preset = 0;
  int m_species = 1;
  bool m_speciesDiffer = true;
  float m_scale = 1.0f;
  physarum::PresetDef m_custom{"Custom", 22.5f, 45, 9, 10, 90, 100, 30, 0, 50};
  int m_start = 0;
  int m_restartMinutes = 10;
  int m_mode = MODE_PALETTE;
  int m_palette = 0;
  RGB m_colour{1.0f, 0.83f, 0.42f};
  RGB m_background{0, 0, 0};
  float m_brightness = 1.0f;
  float m_cycle = 0.2f;
  float m_dim = 0.0f;
  size_t m_agents = 100000;
  int m_trailW = 640, m_trailH = 360;
  int m_pace = PACE_NORMAL;
  int m_threads = 0;

  int m_current = 0; // preset on screen
  Clock::time_point m_runStart, m_start0, m_statsStart, m_lastFrame;
  double m_credit = 0.0;
  long m_frames = 0;
  bool m_loggedStats = false;
};

//------------------------------------------------------------------------------

void CScreensaverPhysarum::LoadSettings()
{
  using kodi::addon::GetSettingBoolean;
  using kodi::addon::GetSettingInt;

  m_preset = std::min(std::max(GetSettingInt("preset", 0), 0), PRESET_CUSTOM);
  m_species = std::min(std::max(GetSettingInt("species", 0), 0), 2) + 1;
  m_speciesDiffer = GetSettingBoolean("species_differ", true);
  m_scale = std::min(std::max(GetSettingInt("scale", 100), 20), 400) / 100.0f;
  m_custom.sa = static_cast<float>(GetSettingInt("sa", 22));
  m_custom.ra = static_cast<float>(GetSettingInt("ra", 45));
  m_custom.so = static_cast<float>(GetSettingInt("so", 9));
  m_custom.ss = static_cast<float>(GetSettingInt("ss", 10));
  m_custom.decay = static_cast<float>(GetSettingInt("decay", 90));
  m_custom.diffuse = static_cast<float>(GetSettingInt("diffuse", 100));
  m_custom.deposit = static_cast<float>(GetSettingInt("deposit", 30));
  m_custom.jitter = static_cast<float>(GetSettingInt("jitter", 0));
  m_custom.repel = static_cast<float>(GetSettingInt("repel", 50));

  m_start = std::min(std::max(GetSettingInt("start", 0), 0), physarum::START_COUNT - 1);
  m_restartMinutes = kRestartMinutes[Pick(GetSettingInt("restart", 3), kRestartMinutes)];

  m_mode = std::min(std::max(GetSettingInt("colour_mode", 0), 0), MODE_COUNT - 1);
  m_palette = std::min(std::max(GetSettingInt("palette", 0), 0), physarum::kNumPalettes - 1);
  m_colour = SettingColour("colour", 0xFFD36B);
  m_background = SettingColour("background", 0x000000);
  m_brightness = std::min(std::max(GetSettingInt("brightness", 100), 10), 500) / 100.0f;
  m_cycle = std::min(std::max(GetSettingInt("cycle", 20), 0), 100) / 100.0f;
  m_dim = std::min(std::max(GetSettingInt("dim", 0), 0), 90) / 100.0f;

  m_agents = kAgentCounts[Pick(GetSettingInt("agents", 4), kAgentCounts)];
  const int t = Pick(GetSettingInt("trail", 4), kTrailSizes);
  m_trailW = kTrailSizes[t][0];
  m_trailH = kTrailSizes[t][1];
  m_pace = std::min(std::max(GetSettingInt("pace", 0), 0), 2);
  m_threads = std::min(std::max(GetSettingInt("threads", 0), 0), 4);
}

GLuint CScreensaverPhysarum::Compile(GLenum type, const std::string& src)
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
    kodi::Log(ADDON_LOG_ERROR, "Physarum v2: shader compile failed: %s", log);
    glDeleteShader(shader);
    return 0;
  }
  return shader;
}

bool CScreensaverPhysarum::BuildProgram()
{
  const std::string defines =
      "#define MODE " + std::to_string(m_mode) + "\n#define SPECIES " + std::to_string(m_species) + "\n";
  GLuint vs = Compile(GL_VERTEX_SHADER, kVertexHeader + kVertexShader);
  GLuint fs = Compile(GL_FRAGMENT_SHADER, kFragmentHeader + defines + kFragmentShader);
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
    kodi::Log(ADDON_LOG_ERROR, "Physarum v2: program link failed: %s", log);
    glDeleteProgram(m_program);
    m_program = 0;
    return false;
  }
  m_aPos = glGetAttribLocation(m_program, "a_pos");
  m_uSel1 = glGetUniformLocation(m_program, "u_sel1");
  m_uSel2 = glGetUniformLocation(m_program, "u_sel2");
  m_uM = glGetUniformLocation(m_program, "u_m");
  m_uC[0] = glGetUniformLocation(m_program, "u_c0");
  m_uC[1] = glGetUniformLocation(m_program, "u_c1");
  m_uC[2] = glGetUniformLocation(m_program, "u_c2");
  m_uColour = glGetUniformLocation(m_program, "u_colour");
  m_uBg = glGetUniformLocation(m_program, "u_bg");
  glUseProgram(m_program);
  glUniform1i(glGetUniformLocation(m_program, "u_trail"), 0);
  glUniform1i(glGetUniformLocation(m_program, "u_pal"), 1);
  glUseProgram(0);
  return true;
}

// Pick the behaviour for this run, scatter the agents, clear the trail. Only
// called while the driver thread is idle.
void CScreensaverPhysarum::NewRun(bool first)
{
  if (m_preset == PRESET_RANDOM)
  {
    const int n = physarum::kNumPresets;
    if (first)
      m_current = static_cast<int>(m_rng() % n);
    else
    {
      const int r = static_cast<int>(m_rng() % (n - 1));
      m_current = r >= m_current ? r + 1 : r; // never the same one twice in a row
    }
  }
  else
    m_current = m_preset;

  const physarum::PresetDef& def =
      m_preset == PRESET_CUSTOM ? m_custom : physarum::kPresets[m_current];
  const physarum::Params base = physarum::FromDef(def, m_trailW / 960.0f * m_scale);
  for (int s = 0; s < m_species; s++)
    m_sim.SetParams(s, physarum::ForSpecies(base, s, m_speciesDiffer));
  m_sim.Spawn(m_start, m_rng());
  m_fresh = true;
  m_runStart = Clock::now();
  kodi::Log(ADDON_LOG_DEBUG, "Physarum v2: %s", m_preset == PRESET_CUSTOM ? "custom behaviour" : def.name);
}

void CScreensaverPhysarum::DriverLoop()
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
      m_pool.Run(m_sim.agents(), [this](size_t lo, size_t hi) { m_sim.MoveAgents(lo, hi); });
      m_pool.Run(static_cast<size_t>(m_sim.height()),
                 [this](size_t lo, size_t hi) { m_sim.DiffuseRows(lo, hi); });
      m_sim.EndStep();
    }
    const double ms = std::chrono::duration<double, std::milli>(Clock::now() - t0).count();

    lock.lock();
    m_stepMs += ms;
    m_stepCount += n;
    m_busy = false;
    m_fresh = true;
  }
}

void CScreensaverPhysarum::StopSimulation()
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

RGB CScreensaverPhysarum::PaletteAt(float t) const
{
  const uint32_t* p = physarum::kPalettes[m_palette];
  t = (t - std::floor(t)) * 7.0f;
  const int i = static_cast<int>(t) % 7;
  const float f = t - std::floor(t);
  const RGB a = Hex(p[i]), b = Hex(p[(i + 1) % 7]);
  return {a.r + (b.r - a.r) * f, a.g + (b.g - a.g) * f, a.b + (b.b - a.b) * f};
}

bool CScreensaverPhysarum::Start()
{
  LoadSettings();
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

  // the palette: 7 colours and the first again, so it wraps smoothly
  uint8_t pal[8 * 3];
  for (int i = 0; i < 8; i++)
  {
    const uint32_t c = physarum::kPalettes[m_palette][i % 7];
    pal[i * 3] = static_cast<uint8_t>(c >> 16);
    pal[i * 3 + 1] = static_cast<uint8_t>(c >> 8);
    pal[i * 3 + 2] = static_cast<uint8_t>(c);
  }
  glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
  glGenTextures(1, &m_palTex);
  glBindTexture(GL_TEXTURE_2D, m_palTex);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, 8, 1, 0, GL_RGB, GL_UNSIGNED_BYTE, pal);

  // the trail picture: one byte per species and cell
  GLint internal;
#if defined(TARGET_DARWIN)
  static const GLenum kFormats[3] = {GL_RED, GL_RG, GL_RGB};
  static const GLint kInternal[3] = {GL_R8, GL_RG8, GL_RGB8};
  m_texFormat = kFormats[m_species - 1];
  internal = kInternal[m_species - 1];
#else
  static const GLenum kFormats[3] = {GL_LUMINANCE, GL_LUMINANCE_ALPHA, GL_RGB};
  m_texFormat = kFormats[m_species - 1];
  internal = static_cast<GLint>(m_texFormat);
#endif
  glGenTextures(1, &m_trailTex);
  glBindTexture(GL_TEXTURE_2D, m_trailTex);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glTexImage2D(GL_TEXTURE_2D, 0, internal, m_trailW, m_trailH, 0, m_texFormat, GL_UNSIGNED_BYTE, nullptr);
  glBindTexture(GL_TEXTURE_2D, 0);
  glPixelStorei(GL_UNPACK_ALIGNMENT, 4);

  m_sim.Configure(m_trailW, m_trailH, m_species, m_agents);
  m_sim.SetTone(m_brightness);
  NewRun(true);

  int threads = m_threads;
  if (threads == 0)
  {
    // one core stays with Kodi's render thread; the rest simulate (up to 4)
    const unsigned hw = std::thread::hardware_concurrency();
    threads = std::min(std::max(static_cast<int>(hw) - 1, 1), 4);
  }
  if (m_agents < 30000)
    threads = 1;
  m_pool.Start(threads);
  m_quit = false;
  m_busy = false;
  m_kick = 0;
  m_stepMs = 0;
  m_stepCount = 0;
  m_driver = std::thread([this] { DriverLoop(); });

  m_start0 = m_statsStart = m_lastFrame = Clock::now();
  m_credit = 1.0;
  m_frames = 0;
  m_loggedStats = false;
  kodi::Log(ADDON_LOG_INFO, "Physarum v2: %zu agents, %d species, %dx%d trail, %d thread(s)", m_agents,
            m_species, m_trailW, m_trailH, m_pool.threads());
  return true;
}

void CScreensaverPhysarum::Stop()
{
  StopSimulation();
  if (m_trailTex)
    glDeleteTextures(1, &m_trailTex);
  if (m_palTex)
    glDeleteTextures(1, &m_palTex);
  if (m_vbo)
    glDeleteBuffers(1, &m_vbo);
#ifdef TARGET_DARWIN
  if (m_vao)
    glDeleteVertexArrays(1, &m_vao);
#endif
  if (m_program)
    glDeleteProgram(m_program);
  m_trailTex = m_palTex = m_vbo = m_vao = m_program = 0;
}

void CScreensaverPhysarum::Upload()
{
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, m_trailTex);
  glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
  glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, m_trailW, m_trailH, m_texFormat, GL_UNSIGNED_BYTE,
                  m_sim.display());
  glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
}

void CScreensaverPhysarum::Render()
{
  if (!m_program)
    return;
  const auto now = Clock::now();
  const double frameDt = std::chrono::duration<double>(now - m_lastFrame).count();
  m_lastFrame = now;
  m_frames++;

  // --- simulation: if the last step is done, show it and start the next
  const double runAge = std::chrono::duration<double>(now - m_runStart).count();
  const double runLength = m_restartMinutes * 60.0;
  bool busy, fresh;
  {
    std::lock_guard<std::mutex> lock(m_mutex);
    busy = m_busy;
    fresh = m_fresh;
    m_fresh = false;
  }
  static const double kRate[] = {60.0, 120.0, 30.0}; // steps a second per Pace
  m_credit = std::min(m_credit + kRate[m_pace] * std::min(frameDt, 0.1), m_pace == PACE_FAST ? 3.0 : 1.5);
  if (!busy)
  {
    if (runLength > 0 && runAge >= runLength)
    {
      NewRun(false);
      fresh = true;
      m_fresh = false;
    }
    if (fresh)
      Upload();
    // Steps are earned at the chosen rate (60 a second on Normal: one per
    // frame on a 60 Hz TV) and spent whenever the simulation is free, so a
    // 120 Hz screen or an unthrottled desktop Kodi runs at the same speed and
    // frame-time jitter does not drop steps. The credit is capped, so a box
    // that cannot keep up slows down instead of piling up a backlog.
    const int steps = std::min(static_cast<int>(m_credit), m_pace == PACE_FAST ? 2 : 1);
    if (steps > 0)
    {
      m_credit -= steps;
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
      ms = m_stepMs;
      count = m_stepCount;
    }
    if (count > 0)
      kodi::Log(ADDON_LOG_INFO,
                "Physarum v2: %.2f ms per step, %.1f steps/s, %.1f frames/s (%zu agents, %dx%d, %d thread(s))",
                ms / count, count / statsAge, m_frames / statsAge, m_agents, m_trailW, m_trailH,
                m_pool.threads());
    m_loggedStats = true;
  }

  // --- draw: one quad
  const double t = std::chrono::duration<double>(now - m_start0).count();
  const float phase = static_cast<float>(std::fmod(t * m_cycle * 0.02, 1.0));
  float fade = 1.0f;
  if (runLength > 0 && runAge > runLength - 2.0)
    fade = static_cast<float>(std::max(0.0, (runLength - runAge) / 2.0));
  fade *= 1.0f - m_dim;

  glDisable(GL_BLEND);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
#ifdef TARGET_DARWIN
  glBindVertexArray(m_vao);
#endif
  glViewport(X(), Y(), Width(), Height());
  glUseProgram(m_program);

  // which texel channels hold species 2 and 3
#if defined(TARGET_DARWIN)
  const float sel1[4] = {0, m_species > 1 ? 1.0f : 0, 0, 0};
#else
  const float sel1[4] = {0, m_species == 3 ? 1.0f : 0, 0, m_species == 2 ? 1.0f : 0};
#endif
  const float sel2[4] = {0, 0, m_species == 3 ? 1.0f : 0, 0};
  glUniform4fv(m_uSel1, 1, sel1);
  glUniform4fv(m_uSel2, 1, sel2);
  glUniform2f(m_uM, phase, fade);
  for (int i = 0; i < 3; i++)
  {
    const RGB c = PaletteAt(phase + i * 2.0f / 7.0f);
    glUniform3f(m_uC[i], c.r, c.g, c.b);
  }
  glUniform3f(m_uColour, m_colour.r, m_colour.g, m_colour.b);
  const float bgScale = 1.0f - m_dim;
  glUniform3f(m_uBg, m_background.r * bgScale, m_background.g * bgScale, m_background.b * bgScale);

  glActiveTexture(GL_TEXTURE1);
  glBindTexture(GL_TEXTURE_2D, m_palTex);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, m_trailTex);

  glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
  glEnableVertexAttribArray(static_cast<GLuint>(m_aPos));
  glVertexAttribPointer(static_cast<GLuint>(m_aPos), 2, GL_FLOAT, GL_FALSE, 0, nullptr);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
  glDisableVertexAttribArray(static_cast<GLuint>(m_aPos));
  glBindBuffer(GL_ARRAY_BUFFER, 0);

  glActiveTexture(GL_TEXTURE1);
  glBindTexture(GL_TEXTURE_2D, 0);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, 0);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif
  glUseProgram(0);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
}

ADDONCREATOR(CScreensaverPhysarum)

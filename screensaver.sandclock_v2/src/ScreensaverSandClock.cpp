// Kodi screensaver wrapper around the Sand Clock v2 simulations.
//
// Two clocks share the add-on: the sand (Sand.h), a grid of grains with real
// motion, and the liquid (Liquid.h), a FLIP fluid the digits melt into. Either
// runs on the CPU, on a driver thread of its own plus a small worker pool, one
// step ahead of the picture, so Render() never waits for it. When a step has
// finished, Render() uploads what changed and kicks off the next step; then it
// draws one full-screen quad:
//  - sand: an 8-bit texture of palette indices (only the rows that changed are
//    uploaded) and a 256 x 1 palette; the shader lights the top surface of the
//    pile and rounds the grains when they are big enough to see;
//  - liquid: an RGBA picture of the fluid's density and colour; the shader
//    cuts the surface out of the density, takes a normal from its slope and
//    lights it like a glossy liquid.
// Plain OpenGL / OpenGL ES 2; no float textures, no render targets.

#include "Liquid.h"
#include "Sand.h"
#include "WorkerPool.h"

#include <kodi/addon-instance/Screensaver.h>
#include <kodi/gui/gl/GL.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <ctime>
#include <memory>
#include <mutex>
#include <random>
#include <string>
#include <thread>

using namespace sandclock2;

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
  v_uv = vec2(a_pos.x * 0.5 + 0.5, 0.5 - a_pos.y * 0.5); // row 0 is the top
}
)";

// The sand: palette index per cell, 0 = empty.
const char* kSandShader = R"(
#ifdef GL_ES
precision highp float;
#endif
uniform sampler2D u_idx;
uniform sampler2D u_pal;   // 256 x 1
uniform vec2 u_size;       // grid cells
uniform vec3 u_look;       // grain rounding, surface light, brightness (dim)
uniform vec3 u_bg;
varying vec2 v_uv;

void main()
{
  vec2 cell = v_uv * u_size;
  vec2 c = (floor(cell) + 0.5) / u_size;
  float i = texture2D(u_idx, c).r;
  if (i < 0.5 / 255.0)
  {
    gl_FragColor = vec4(u_bg, 1.0);
    return;
  }
  vec3 col = texture2D(u_pal, vec2((i * 255.0 + 0.5) / 256.0, 0.5)).rgb;
  float above = texture2D(u_idx, c - vec2(0.0, 1.0 / u_size.y)).r;
  if (above < 0.5 / 255.0)
    col *= u_look.y; // the lit top of the pile and of each digit
  vec2 f = fract(cell) - 0.5;
  col *= 1.0 - u_look.x * dot(f, f);
  gl_FragColor = vec4(col * u_look.z, 1.0);
}
)";

// The liquid: density in alpha, colour premultiplied by it.
const char* kLiquidShader = R"(
#ifdef GL_ES
precision highp float;
#endif
uniform sampler2D u_tex;
uniform vec2 u_texel;      // one texel in uv
uniform vec2 u_look;       // brightness (dim), gloss
uniform vec3 u_bg;
varying vec2 v_uv;

void main()
{
  vec4 t = texture2D(u_tex, v_uv);
  float e = smoothstep(0.22, 0.30, t.a);
  if (e <= 0.0)
  {
    gl_FragColor = vec4(u_bg, 1.0);
    return;
  }
  vec3 base = t.rgb / max(t.a, 0.004);
  // The slope of the density, capped: the surface curves at the edges and is
  // smooth inside, where the particles only make the density ripple.
  float ax = min(texture2D(u_tex, v_uv + vec2(u_texel.x, 0.0)).a, 0.5);
  float bx = min(texture2D(u_tex, v_uv - vec2(u_texel.x, 0.0)).a, 0.5);
  float ay = min(texture2D(u_tex, v_uv + vec2(0.0, u_texel.y)).a, 0.5);
  float by = min(texture2D(u_tex, v_uv - vec2(0.0, u_texel.y)).a, 0.5);
  vec3 n = normalize(vec3((bx - ax) * 5.0, (by - ay) * 5.0, 1.0)); // y down, as the picture
  float diff = 0.72 + 0.28 * dot(n, vec3(-0.4, -0.6, 0.7));
  float spec = pow(max(dot(n, vec3(-0.3, -0.5, 0.81)), 0.0), 30.0) * 0.6 * u_look.y;
  float rim = (1.0 - n.z) * 0.18;
  float depth = 0.86 + 0.14 * smoothstep(0.3, 0.75, t.a); // thin films are darker
  vec3 col = base * diff * depth + vec3(spec + rim * u_look.y);
  gl_FragColor = vec4(mix(u_bg, col * u_look.x, e), 1.0);
}
)";

enum Mode { MODE_SAND = 0, MODE_LIQUID };

// Option lists (tools/make_settings_sandclock_v2.py has the same order).
const int kSandRows[] = {180, 216, 270, 360};
const int kLiquidRows[] = {54, 72, 90, 108};
const float kPositions[] = {0.22f, 0.30f, 0.40f};
// viscosity: FLIP share, grid smoothing, stickiness
const float kViscosity[][3] = {{0.95f, 0.0f, 0.35f}, {0.85f, 0.05f, 0.55f}, {0.6f, 0.15f, 0.7f}, {0.35f, 0.3f, 0.8f}};
const float kSlosh[] = {0.0f, 0.08f, 0.2f};

template <typename T, size_t N>
int Pick(int index, const T (&)[N])
{
  return std::min(std::max(index, 0), static_cast<int>(N) - 1);
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

class ATTR_DLL_LOCAL CScreensaverSandClock : public kodi::addon::CAddonBase,
                                             public kodi::addon::CInstanceScreensaver
{
public:
  CScreensaverSandClock() = default;
  ~CScreensaverSandClock() override { StopSimulation(); }

  bool Start() override;
  void Stop() override;
  void Render() override;

private:
  using Clock = std::chrono::steady_clock;

  void LoadSettings();
  GLuint Compile(GLenum type, const std::string& src);
  GLuint Link(const char* fragment);
  std::string Now() const;
  void Upload();
  void DriverLoop();
  void StopSimulation();
  GLuint NewTexture(GLint filter);

  std::unique_ptr<SandWorld> m_sand;
  std::unique_ptr<LiquidWorld> m_liquid;
  WorkerPool m_pool;

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
  GLuint m_program = 0, m_vbo = 0, m_vao = 0, m_tex = 0, m_palTex = 0;
  GLint m_aPos = -1, m_uSize = -1, m_uLook = -1, m_uBg = -1, m_uTexel = -1;
  GLenum m_texFormat = 0;
  int m_texW = 0, m_texH = 0;

  // settings
  int m_mode = MODE_SAND;
  ClockStyle m_style;
  int m_newDigits = NEW_POUR, m_crumble = CRUMBLE_BOTTOM_UP;
  bool m_sandWhole = false;
  int m_sandRows = 270;
  int m_gravity = 100;
  float m_pile = 0.2f;
  bool m_round = true;
  int m_viscosity = 1, m_melt = MELT_DRIP;
  bool m_liquidWhole = false, m_drips = true;
  float m_slosh = 0.08f, m_poolDepth = 0.2f;
  int m_liquidRows = 72;
  int m_colourMode = COLOUR_EVERY_CHANGE, m_palette = 1;
  RGB m_colour{0.91f, 0.76f, 0.48f};
  RGB m_background{0.04f, 0.035f, 0.06f};
  float m_dim = 0.0f;
  int m_threads = 0;

  Clock::time_point m_start0, m_lastFrame;
  double m_credit = 0.0;
  long m_frames = 0;
  bool m_loggedStats = false;
};

//------------------------------------------------------------------------------

void CScreensaverSandClock::LoadSettings()
{
  using kodi::addon::GetSettingBoolean;
  using kodi::addon::GetSettingInt;

  m_mode = std::min(std::max(GetSettingInt("mode", 0), 0), 1);
  m_style.seconds = GetSettingBoolean("seconds", true);
  m_style.twelveHour = GetSettingBoolean("twelve_hour", false);
  m_style.font = std::min(std::max(GetSettingInt("font", 0), 0), kNumFonts - 1);
  m_style.weight = std::min(std::max(GetSettingInt("weight", 1), 0), kNumWeights - 1);
  m_style.size = std::min(std::max(GetSettingInt("size", 80), 30), 100) / 100.0f;
  m_style.centreY = kPositions[Pick(GetSettingInt("position", 1), kPositions)];

  m_newDigits = std::min(std::max(GetSettingInt("new_digits", 0), 0), 1);
  m_crumble = std::min(std::max(GetSettingInt("crumble", 0), 0), 2);
  m_sandWhole = GetSettingBoolean("sand_whole", false);
  m_sandRows = kSandRows[Pick(GetSettingInt("grain", 2), kSandRows)];
  m_gravity = std::min(std::max(GetSettingInt("sand_gravity", 100), 50), 200);
  m_pile = std::min(std::max(GetSettingInt("pile", 20), 5), 35) / 100.0f;
  m_round = GetSettingBoolean("round", true);

  m_viscosity = Pick(GetSettingInt("viscosity", 1), kViscosity);
  m_melt = std::min(std::max(GetSettingInt("melt", 0), 0), 2);
  m_liquidWhole = GetSettingBoolean("liquid_whole", false);
  m_drips = GetSettingBoolean("drips", true);
  m_slosh = kSlosh[Pick(GetSettingInt("slosh", 1), kSlosh)];
  m_poolDepth = std::min(std::max(GetSettingInt("pool", 20), 10), 35) / 100.0f;
  m_liquidRows = kLiquidRows[Pick(GetSettingInt("detail", 1), kLiquidRows)];

  m_colourMode = std::min(std::max(GetSettingInt("colour_mode", 0), 0), COLOUR_COUNT - 1);
  m_palette = std::min(std::max(GetSettingInt("palette", 1), 0), kNumPalettes - 1);
  m_colour = SettingColour("colour", 0xE8C27A);
  m_background = SettingColour("background", 0x0A0910);
  m_dim = std::min(std::max(GetSettingInt("dim", 0), 0), 90) / 100.0f;
  m_threads = std::min(std::max(GetSettingInt("threads", 0), 0), 4);
}

GLuint CScreensaverSandClock::Compile(GLenum type, const std::string& src)
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
    kodi::Log(ADDON_LOG_ERROR, "Sand Clock v2: shader compile failed: %s", log);
    glDeleteShader(shader);
    return 0;
  }
  return shader;
}

GLuint CScreensaverSandClock::Link(const char* fragment)
{
  GLuint vs = Compile(GL_VERTEX_SHADER, kVertexHeader + kVertexShader);
  GLuint fs = Compile(GL_FRAGMENT_SHADER, kFragmentHeader + fragment);
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
    kodi::Log(ADDON_LOG_ERROR, "Sand Clock v2: program link failed: %s", log);
    glDeleteProgram(program);
    return 0;
  }
  return program;
}

// The clock text for the local time now.
std::string CScreensaverSandClock::Now() const
{
  const std::time_t t = std::time(nullptr);
  std::tm tm{};
#if defined(_WIN32)
  localtime_s(&tm, &t);
#else
  localtime_r(&t, &tm);
#endif
  return TimeText(m_style, tm.tm_hour, tm.tm_min, tm.tm_sec);
}

void CScreensaverSandClock::DriverLoop()
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
    const double seconds = std::chrono::duration<double>(t0 - m_start0).count();
    const std::string text = Now();
    for (int i = 0; i < n; i++)
    {
      if (m_sand)
      {
        m_sand->SetText(text, seconds);
        m_sand->Step(m_pool);
      }
      else
      {
        m_liquid->SetText(text, seconds);
        m_liquid->Step(m_pool);
      }
    }
    const double ms = std::chrono::duration<double, std::milli>(Clock::now() - t0).count();

    lock.lock();
    m_stepMs += ms;
    m_stepCount += n;
    m_busy = false;
    m_fresh = true;
  }
}

void CScreensaverSandClock::StopSimulation()
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

GLuint CScreensaverSandClock::NewTexture(GLint filter)
{
  GLuint tex = 0;
  glGenTextures(1, &tex);
  glBindTexture(GL_TEXTURE_2D, tex);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, filter);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, filter);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  return tex;
}

bool CScreensaverSandClock::Start()
{
  LoadSettings();
  m_program = Link(m_mode == MODE_SAND ? kSandShader : kLiquidShader);
  if (!m_program)
    return false;
  m_aPos = glGetAttribLocation(m_program, "a_pos");
  m_uSize = glGetUniformLocation(m_program, "u_size");
  m_uLook = glGetUniformLocation(m_program, "u_look");
  m_uBg = glGetUniformLocation(m_program, "u_bg");
  m_uTexel = glGetUniformLocation(m_program, "u_texel");
  glUseProgram(m_program);
  glUniform1i(glGetUniformLocation(m_program, m_mode == MODE_SAND ? "u_idx" : "u_tex"), 0);
  if (m_mode == MODE_SAND)
    glUniform1i(glGetUniformLocation(m_program, "u_pal"), 1);
  glUseProgram(0);

#ifdef TARGET_DARWIN
  glGenVertexArrays(1, &m_vao);
#endif
  const float quad[] = {-1, -1, 1, -1, -1, 1, 1, 1};
  glGenBuffers(1, &m_vbo);
  glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
  glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
  glBindBuffer(GL_ARRAY_BUFFER, 0);

  const float aspect = Height() > 0 ? static_cast<float>(Width()) / Height() : 16.0f / 9.0f;
  const uint32_t seed = std::random_device{}();
  ColourPicker colours;
  colours.mode = m_colourMode;
  colours.palette = m_palette;
  colours.colour = m_colour;

  glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
  if (m_mode == MODE_SAND)
  {
    m_sand.reset(new SandWorld());
    m_sand->style = m_style;
    m_sand->colours = colours;
    SandParams& p = m_sand->params;
    p.gravity = std::max(2, (8 * m_gravity + 50) / 100);
    p.newDigits = m_newDigits;
    p.crumble = m_crumble;
    p.wholeClock = m_sandWhole;
    p.pile = m_pile;
    m_sand->Configure(static_cast<int>(std::lround(m_sandRows * aspect)), m_sandRows, seed);
    m_sand->SetText(Now(), 0.0);
    m_texW = m_sand->width();
    m_texH = m_sand->height();

    m_palTex = NewTexture(GL_NEAREST);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 256, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, m_sand->palette());
#if defined(TARGET_DARWIN)
    m_texFormat = GL_RED;
    const GLint internal = GL_R8;
#else
    m_texFormat = GL_LUMINANCE;
    const GLint internal = GL_LUMINANCE;
#endif
    m_tex = NewTexture(GL_NEAREST);
    glTexImage2D(GL_TEXTURE_2D, 0, internal, m_texW, m_texH, 0, m_texFormat, GL_UNSIGNED_BYTE, nullptr);
  }
  else
  {
    m_liquid.reset(new LiquidWorld());
    m_liquid->style = m_style;
    m_liquid->colours = colours;
    LiquidParams& p = m_liquid->params;
    p.flip = kViscosity[m_viscosity][0];
    p.smooth = kViscosity[m_viscosity][1];
    p.stick = kViscosity[m_viscosity][2];
    p.melt = m_melt;
    p.wholeClock = m_liquidWhole;
    p.drips = m_drips;
    p.slosh = m_slosh;
    p.pool = m_poolDepth;
    m_liquid->Configure(static_cast<int>(std::lround(m_liquidRows * aspect)), m_liquidRows, seed);
    m_liquid->SetText(Now(), 0.0);
    m_texW = m_liquid->texWidth();
    m_texH = m_liquid->texHeight();
    m_texFormat = GL_RGBA;
    m_tex = NewTexture(GL_LINEAR);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, m_texW, m_texH, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
  }
  glBindTexture(GL_TEXTURE_2D, 0);
  glPixelStorei(GL_UNPACK_ALIGNMENT, 4);

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
  m_fresh = true;
  m_stepMs = 0;
  m_stepCount = 0;
  m_start0 = m_lastFrame = Clock::now();
  m_driver = std::thread([this] { DriverLoop(); });

  m_credit = 1.0;
  m_frames = 0;
  m_loggedStats = false;
  kodi::Log(ADDON_LOG_INFO, "Sand Clock v2: %s, %dx%d grid, %d thread(s)", m_sand ? "sand" : "liquid",
            m_sand ? m_sand->width() : m_liquid->width(), m_sand ? m_sand->height() : m_liquid->height(),
            m_pool.threads());
  return true;
}

void CScreensaverSandClock::Stop()
{
  StopSimulation();
  m_sand.reset();
  m_liquid.reset();
  if (m_tex)
    glDeleteTextures(1, &m_tex);
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
  m_tex = m_palTex = m_vbo = m_vao = m_program = 0;
}

// Only called while the driver thread is idle.
void CScreensaverSandClock::Upload()
{
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, m_tex);
  glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
  if (m_sand)
  {
    int y0, y1;
    if (m_sand->TakeDirtyRows(y0, y1))
      glTexSubImage2D(GL_TEXTURE_2D, 0, 0, y0, m_texW, y1 - y0, m_texFormat, GL_UNSIGNED_BYTE,
                      m_sand->display() + static_cast<size_t>(y0) * m_texW);
  }
  else
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, m_texW, m_texH, GL_RGBA, GL_UNSIGNED_BYTE, m_liquid->picture());
  glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
}

void CScreensaverSandClock::Render()
{
  if (!m_program)
    return;
  const auto now = Clock::now();
  const double frameDt = std::chrono::duration<double>(now - m_lastFrame).count();
  m_lastFrame = now;
  m_frames++;

  // --- simulation: if the last step is done, show it and start the next
  bool busy, fresh;
  {
    std::lock_guard<std::mutex> lock(m_mutex);
    busy = m_busy;
    fresh = m_fresh;
    m_fresh = false;
  }
  // Steps are earned at 60 a second and spent whenever the simulation is
  // free, so a 120 Hz screen or an unthrottled desktop Kodi runs at the same
  // speed and frame-time jitter does not drop steps. The credit is capped, so
  // a box that cannot keep up slows down instead of piling up a backlog.
  m_credit = std::min(m_credit + 60.0 * std::min(frameDt, 0.1), 1.5);
  if (!busy)
  {
    if (fresh)
      Upload();
    if (m_credit >= 1.0)
    {
      m_credit -= 1.0;
      {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_kick = 1;
        m_busy = true;
      }
      m_cv.notify_one();
    }
  }

  // one line in the log after 20 s, to check a box keeps up
  const double age = std::chrono::duration<double>(now - m_start0).count();
  if (!m_loggedStats && age > 20.0)
  {
    double ms;
    long count;
    {
      std::lock_guard<std::mutex> lock(m_mutex);
      ms = m_stepMs;
      count = m_stepCount;
    }
    if (count > 0)
      kodi::Log(ADDON_LOG_INFO, "Sand Clock v2: %.2f ms per step, %.1f steps/s, %.1f frames/s (%s, %d thread(s))",
                ms / count, count / age, m_frames / age, m_sand ? "sand" : "liquid", m_pool.threads());
    m_loggedStats = true;
  }

  // --- draw: one quad
  const float bright = 1.0f - m_dim;
  glDisable(GL_BLEND);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
#ifdef TARGET_DARWIN
  glBindVertexArray(m_vao);
#endif
  glViewport(X(), Y(), Width(), Height());
  glUseProgram(m_program);
  glUniform3f(m_uBg, m_background.r * bright, m_background.g * bright, m_background.b * bright);
  if (m_sand)
  {
    // grains a few pixels across or more are drawn round
    const float px = Height() > 0 ? static_cast<float>(Height()) / m_texH : 4.0f;
    const float round = m_round ? std::min(1.0f, std::max(0.0f, (px - 2.0f) / 3.0f)) * 0.9f : 0.0f;
    glUniform2f(m_uSize, static_cast<float>(m_texW), static_cast<float>(m_texH));
    glUniform3f(m_uLook, round, 1.18f, bright);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, m_palTex);
  }
  else
  {
    glUniform2f(m_uTexel, 1.0f / m_texW, 1.0f / m_texH);
    glUniform2f(m_uLook, bright, 1.0f);
  }
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, m_tex);

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

ADDONCREATOR(CScreensaverSandClock)

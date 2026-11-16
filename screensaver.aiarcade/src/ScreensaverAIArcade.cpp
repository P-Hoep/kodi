// AI Arcade: the Kodi shell. Settings, the Arcade (training and display
// threads, see Trainer.h) and the render thread, which only uploads the latest
// display frame as a texture and draws it with the HUD and fitness graph.
#include "Font8x8.h"
#include "Emu.h"
#include "Trainer.h"

#include <kodi/Filesystem.h>
#include <kodi/addon-instance/Screensaver.h>
#include <kodi/gui/gl/GL.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdarg>
#include <cstdio>
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
const std::string kFragmentHeader = "#version 150\nout vec4 fragColor;\n#define gl_FragColor fragColor\n"
                                    "#define varying in\n#define texture2D texture\n";
#else
const std::string kVertexHeader = "#version 120\n";
const std::string kFragmentHeader = "#version 120\n";
#endif

const char* kVertexShader = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;   // pixels, y down
attribute vec2 a_uv;
attribute vec4 a_col;
attribute float a_mode; // 0 game texture, 1 font texture, 2 flat colour
uniform vec2 u_screen;
varying vec2 v_uv;
varying vec4 v_col;
varying float v_mode;
void main()
{
  v_uv = a_uv;
  v_col = a_col;
  v_mode = a_mode;
  gl_Position = vec4(a_pos.x / u_screen.x * 2.0 - 1.0, 1.0 - a_pos.y / u_screen.y * 2.0, 0.0, 1.0);
}
)";

const char* kFragmentShader = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_game;
uniform sampler2D u_font;
varying vec2 v_uv;
varying vec4 v_col;
varying float v_mode;
void main()
{
  if (v_mode < 0.5)
    gl_FragColor = vec4(texture2D(u_game, v_uv).rgb, 1.0) * v_col;
  else if (v_mode < 1.5)
    gl_FragColor = vec4(v_col.rgb, v_col.a * texture2D(u_font, v_uv).a);
  else
    gl_FragColor = v_col;
}
)";

struct Vtx
{
  float x, y, u, v, r, g, b, a, mode;
};

struct Col
{
  float r, g, b, a;
};

constexpr int kFontCols = 16, kFontRows = 6, kFontTexW = kFontCols * 8, kFontTexH = kFontRows * 8;

class Batch
{
public:
  std::vector<Vtx> v;
  void Quad(float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1, Col c, float mode)
  {
    const Vtx q[6] = {{x0, y0, u0, v0, c.r, c.g, c.b, c.a, mode}, {x1, y0, u1, v0, c.r, c.g, c.b, c.a, mode},
                      {x0, y1, u0, v1, c.r, c.g, c.b, c.a, mode}, {x0, y1, u0, v1, c.r, c.g, c.b, c.a, mode},
                      {x1, y0, u1, v0, c.r, c.g, c.b, c.a, mode}, {x1, y1, u1, v1, c.r, c.g, c.b, c.a, mode}};
    v.insert(v.end(), q, q + 6);
  }
  void Rect(float x0, float y0, float x1, float y1, Col c) { Quad(x0, y0, x1, y1, 0, 0, 0, 0, c, 2); }
  void Line(float x0, float y0, float x1, float y1, float w, Col c)
  {
    const float dx = x1 - x0, dy = y1 - y0, len = std::sqrt(dx * dx + dy * dy);
    if (len < 1e-3f)
      return;
    const float nx = -dy / len * w * 0.5f, ny = dx / len * w * 0.5f;
    const Vtx q[6] = {{x0 + nx, y0 + ny, 0, 0, c.r, c.g, c.b, c.a, 2}, {x1 + nx, y1 + ny, 0, 0, c.r, c.g, c.b, c.a, 2},
                      {x0 - nx, y0 - ny, 0, 0, c.r, c.g, c.b, c.a, 2}, {x0 - nx, y0 - ny, 0, 0, c.r, c.g, c.b, c.a, 2},
                      {x1 + nx, y1 + ny, 0, 0, c.r, c.g, c.b, c.a, 2}, {x1 - nx, y1 - ny, 0, 0, c.r, c.g, c.b, c.a, 2}};
    v.insert(v.end(), q, q + 6);
  }
  // 8x8 glyphs at an integer scale, with a one-pixel drop shadow
  float Text(float x, float y, float scale, Col c, const std::string& s)
  {
    const float step = 8 * scale;
    for (int pass = 0; pass < 2; pass++)
    {
      float cx = x;
      const float off = pass == 0 ? scale : 0.0f;
      const Col col = pass == 0 ? Col{0, 0, 0, c.a * 0.8f} : c;
      for (unsigned char ch : s)
      {
        const int g = (ch < 32 || ch > 126) ? 0 : ch - 32;
        if (g != 0)
        {
          const float u0 = static_cast<float>((g % kFontCols) * 8) / kFontTexW;
          const float v0 = static_cast<float>((g / kFontCols) * 8) / kFontTexH;
          Quad(cx + off, y + off, cx + off + step, y + off + step, u0, v0, u0 + 8.0f / kFontTexW, v0 + 8.0f / kFontTexH, col, 1);
        }
        cx += step;
      }
    }
    return static_cast<float>(s.size()) * step;
  }
};

std::string Fmt(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
std::string Fmt(const char* fmt, ...)
{
  char buf[512];
  va_list ap;
  va_start(ap, fmt);
  std::vsnprintf(buf, sizeof buf, fmt, ap);
  va_end(ap);
  return buf;
}

std::string Hours(double h)
{
  if (h < 1.0)
    return Fmt("%.0f min", h * 60.0);
  return Fmt("%.1f h", h);
}

bool IsUrl(const std::string& p) { return p.find("://") != std::string::npos; }

} // namespace

class ATTR_DLL_LOCAL CScreensaverAIArcade : public kodi::addon::CAddonBase, public kodi::addon::CInstanceScreensaver
{
public:
  CScreensaverAIArcade() = default;
  ~CScreensaverAIArcade() override { m_arcade.Stop(); }

  bool Start() override;
  void Stop() override;
  void Render() override;

private:
  bool BuildGL();
  void FreeGL();
  GLuint Compile(GLenum type, const std::string& src);
  void BuildHud(const arcade::Stats& s, bool haveFrame);

  arcade::Arcade m_arcade;
  bool m_hud = true;
  GLuint m_program = 0, m_vbo = 0, m_gameTex = 0, m_fontTex = 0;
#ifdef TARGET_DARWIN
  GLuint m_vao = 0;
#endif
  GLint m_aPos = -1, m_aUv = -1, m_aCol = -1, m_aMode = -1, m_uScreen = -1, m_uGame = -1, m_uFont = -1;
  uint64_t m_serial = 0;
  bool m_haveFrame = false;
  std::vector<uint32_t> m_frame;
  Batch m_batch;
};

GLuint CScreensaverAIArcade::Compile(GLenum type, const std::string& src)
{
  GLuint sh = glCreateShader(type);
  const char* text = src.c_str();
  glShaderSource(sh, 1, &text, nullptr);
  glCompileShader(sh);
  GLint ok = 0;
  glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
  if (!ok)
  {
    char log[1024] = {};
    glGetShaderInfoLog(sh, sizeof(log) - 1, nullptr, log);
    kodi::Log(ADDON_LOG_ERROR, "AI Arcade: shader compile failed: %s", log);
    glDeleteShader(sh);
    return 0;
  }
  return sh;
}

bool CScreensaverAIArcade::BuildGL()
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
    kodi::Log(ADDON_LOG_ERROR, "AI Arcade: program link failed");
    glDeleteProgram(m_program);
    m_program = 0;
    return false;
  }
  m_aPos = glGetAttribLocation(m_program, "a_pos");
  m_aUv = glGetAttribLocation(m_program, "a_uv");
  m_aCol = glGetAttribLocation(m_program, "a_col");
  m_aMode = glGetAttribLocation(m_program, "a_mode");
  m_uScreen = glGetUniformLocation(m_program, "u_screen");
  m_uGame = glGetUniformLocation(m_program, "u_game");
  m_uFont = glGetUniformLocation(m_program, "u_font");
#ifdef TARGET_DARWIN
  glGenVertexArrays(1, &m_vao);
#endif
  glGenBuffers(1, &m_vbo);

  // the NES frame: 256 x 240, scaled with nearest-neighbour
  std::vector<uint32_t> black(arcade::kScreenW * arcade::kScreenH, 0);
  glGenTextures(1, &m_gameTex);
  glBindTexture(GL_TEXTURE_2D, m_gameTex);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, arcade::kScreenW, arcade::kScreenH, 0, GL_RGBA, GL_UNSIGNED_BYTE, black.data());
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

  // the 8x8 font: 16 x 6 glyphs, white with coverage in alpha
  std::vector<uint8_t> font(static_cast<size_t>(kFontTexW) * kFontTexH * 4, 255);
  for (int g = 0; g < 95; g++)
    for (int row = 0; row < 8; row++)
      for (int col = 0; col < 8; col++)
      {
        const int x = (g % kFontCols) * 8 + col, y = (g / kFontCols) * 8 + row;
        font[(static_cast<size_t>(y) * kFontTexW + static_cast<size_t>(x)) * 4 + 3] =
            (arcade::kFont8x8[g][row] >> col) & 1 ? 255 : 0;
      }
  glGenTextures(1, &m_fontTex);
  glBindTexture(GL_TEXTURE_2D, m_fontTex);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, kFontTexW, kFontTexH, 0, GL_RGBA, GL_UNSIGNED_BYTE, font.data());
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glBindTexture(GL_TEXTURE_2D, 0);
  return true;
}

void CScreensaverAIArcade::FreeGL()
{
  if (m_vbo)
    glDeleteBuffers(1, &m_vbo);
  if (m_gameTex)
    glDeleteTextures(1, &m_gameTex);
  if (m_fontTex)
    glDeleteTextures(1, &m_fontTex);
  if (m_program)
    glDeleteProgram(m_program);
#ifdef TARGET_DARWIN
  if (m_vao)
    glDeleteVertexArrays(1, &m_vao);
  m_vao = 0;
#endif
  m_vbo = m_gameTex = m_fontTex = m_program = 0;
}

static void ListRomsVfs(const std::string& dir, bool recursive, std::vector<std::string>& out, int depth)
{
  std::vector<kodi::vfs::CDirEntry> items;
  if (depth > 8 || !kodi::vfs::GetDirectory(dir, "", items))
    return;
  for (const auto& e : items)
  {
    const std::string p = e.Path();
    if (e.IsFolder())
    {
      if (recursive)
        ListRomsVfs(p, recursive, out, depth + 1);
    }
    else if (p.size() > 4)
    {
      std::string ext = p.substr(p.size() - 4);
      std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
      if (ext == ".nes")
        out.push_back(p);
    }
  }
}

bool CScreensaverAIArcade::Start()
{
  using namespace kodi::addon;
  if (!BuildGL())
    return false;
  arcade::Config cfg;
  cfg.romDir = GetSettingString("rom_folder", "");
  if (cfg.romDir.rfind("special://", 0) == 0)
    cfg.romDir = kodi::vfs::TranslateSpecialProtocol(cfg.romDir);
  cfg.recursive = GetSettingBoolean("recursive", true);
  cfg.switchMinutes = std::max(0, GetSettingInt("switch_minutes", 0));
  const int cores = static_cast<int>(std::max(2u, std::thread::hardware_concurrency()));
  cfg.threads = std::min(std::max(GetSettingInt("threads", 1), 1), cores - 1);
  cfg.cpuCap = std::min(std::max(GetSettingInt("cpu_cap", 60), 10), 100) / 100.0;
  cfg.population = std::min(std::max(GetSettingInt("population", 100), 25), 300);
  cfg.resetAll = GetSettingBoolean("reset_all", false);
  if (cfg.resetAll)
    SetSettingBoolean("reset_all", false);
  m_hud = GetSettingBoolean("hud", true);
  cfg.dataDir = kodi::vfs::TranslateSpecialProtocol("special://profile/addon_data/screensaver.aiarcade/");
  // no folder chosen: the "roms" folder in the add-on's data folder
  if (cfg.romDir.empty())
  {
    cfg.romDir = cfg.dataDir + "roms/";
    kodi::vfs::CreateDirectory(cfg.romDir);
  }
  cfg.log = [](int level, const std::string& s) {
    static const ADDON_LOG lv[] = {ADDON_LOG_DEBUG, ADDON_LOG_INFO, ADDON_LOG_WARNING, ADDON_LOG_ERROR};
    kodi::Log(lv[level & 3], "AI Arcade: %s", s.c_str());
  };
  if (IsUrl(cfg.romDir))
  {
    // network shares and other Kodi sources go through Kodi's VFS
    cfg.listRoms = [](const std::string& dir, bool recursive) {
      std::vector<std::string> out;
      ListRomsVfs(dir, recursive, out, 0);
      std::sort(out.begin(), out.end());
      return out;
    };
    cfg.readFile = [](const std::string& path, std::vector<uint8_t>& data) {
      kodi::vfs::CFile f;
      if (!f.OpenFile(path, 0))
        return false;
      data.clear();
      uint8_t buf[65536];
      ssize_t n;
      while ((n = f.Read(buf, sizeof buf)) > 0 && data.size() < (16u << 20))
        data.insert(data.end(), buf, buf + n);
      return !data.empty();
    };
  }
  m_serial = 0;
  m_haveFrame = false;
  m_arcade.Start(cfg);
  kodi::Log(ADDON_LOG_INFO, "AI Arcade: started (ROM folder \"%s\", %d training thread(s) at %d%%, population %d)",
            cfg.romDir.c_str(), cfg.threads, static_cast<int>(cfg.cpuCap * 100 + 0.5), cfg.population);
  return true;
}

void CScreensaverAIArcade::Stop()
{
  const auto t0 = std::chrono::steady_clock::now();
  m_arcade.Stop();
  kodi::Log(ADDON_LOG_INFO, "AI Arcade: stopped in %.0f ms",
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count());
  FreeGL();
}

void CScreensaverAIArcade::BuildHud(const arcade::Stats& s, bool haveFrame)
{
  const float W = static_cast<float>(Width()), H = static_cast<float>(Height());
  const float k = std::max(1.0f, std::floor(H / 360.0f)); // font scale: 3 at 1080p
  const float lh = 8 * k + 4 * k;
  const Col white{1, 1, 1, 1}, dim{0.75f, 0.78f, 0.85f, 1}, gold{1.0f, 0.82f, 0.3f, 1}, cyan{0.4f, 0.85f, 1.0f, 1};
  const bool idle = s.title.empty();

  if (idle || !haveFrame)
  {
    const std::string msg = !s.status.empty() ? s.status : "Starting...";
    const float tw = static_cast<float>(msg.size()) * 8 * k;
    m_batch.Text((W - tw) * 0.5f, H * 0.5f - 4 * k, k, white, "AI ARCADE");
    m_batch.Text((W - tw) * 0.5f, H * 0.5f + lh, k, dim, msg);
    if (idle)
      return;
  }
  if (!m_hud)
    return;

  // bottom bar
  const float pad = 6 * k, barH = 2 * lh + 2 * pad;
  m_batch.Rect(0, H - barH, W, H, {0, 0, 0, 0.62f});
  const char* phase = s.noveltyOnly && s.phase == arcade::Phase::Evolve ? "exploring (no progress signal found)"
                                                                         : arcade::PhaseName(s.phase);
  std::string l1 = s.title + "  -  " + phase;
  if (s.mode == "champion")
    l1 += Fmt("  -  champion run, value %.2f", s.value);
  else if (!s.mode.empty() && s.mode != phase)
    l1 += "  -  showing: " + s.mode;
  m_batch.Text(pad, H - barH + pad, k, white, l1);
  std::string l2;
  if (s.phase == arcade::Phase::Evolve)
    l2 = Fmt("gen %d (%d/%d)   best %.1f   species %d   ", s.generation, s.evaluated, s.populationSize, s.bestFitness,
             s.species);
  l2 += Fmt("archive %d   trained %s", s.archive, Hours(s.hours).c_str());
  if (s.roms > 1)
    l2 += Fmt("   %d ROMs", s.roms);
  m_batch.Text(pad, H - barH + pad + lh, k, dim, l2);

  // fitness graph: best and average of the last 100 generations, top right
  if (s.histBest.size() >= 2)
  {
    const float gw = 110 * k, gh = 46 * k, gx = W - gw - 8 * k, gy = 8 * k;
    m_batch.Rect(gx - 4 * k, gy - 4 * k, gx + gw + 4 * k, gy + gh + 14 * k, {0, 0, 0, 0.55f});
    float hi = 1;
    for (float v : s.histBest)
      hi = std::max(hi, v);
    const size_t n = s.histBest.size();
    auto px = [&](size_t i) { return gx + gw * static_cast<float>(i) / static_cast<float>(n - 1); };
    auto py = [&](float v) { return gy + gh - gh * std::max(0.0f, v) / hi; };
    for (size_t i = 1; i < n; i++)
    {
      m_batch.Line(px(i - 1), py(s.histAvg[i - 1]), px(i), py(s.histAvg[i]), std::max(1.0f, k * 0.7f), cyan);
      m_batch.Line(px(i - 1), py(s.histBest[i - 1]), px(i), py(s.histBest[i]), std::max(1.5f, k), gold);
    }
    const float ks = std::max(1.0f, k - 1);
    m_batch.Text(gx, gy + gh + 4 * k, ks, gold, "best");
    m_batch.Text(gx + 6 * 8 * ks, gy + gh + 4 * k, ks, cyan, "avg");
    const std::string top = Fmt("%.0f", hi);
    m_batch.Text(gx + gw - static_cast<float>(top.size()) * 8 * ks, gy + gh + 4 * k, ks, dim, top);
  }
}

void CScreensaverAIArcade::Render()
{
  if (!m_program)
    return;
  if (m_arcade.CopyFrame(m_serial, m_frame))
  {
    glBindTexture(GL_TEXTURE_2D, m_gameTex);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, arcade::kScreenW, arcade::kScreenH, GL_RGBA, GL_UNSIGNED_BYTE, m_frame.data());
    glBindTexture(GL_TEXTURE_2D, 0);
    m_haveFrame = true;
  }
  const arcade::Stats stats = m_arcade.GetStats();
  const float W = static_cast<float>(Width()), H = static_cast<float>(Height());

  m_batch.v.clear();
  if (m_haveFrame)
  {
    // NES pixels are 8:7; letterbox or pillarbox to keep the aspect
    const float aspect = 256.0f * 8.0f / 7.0f / 240.0f;
    float w = W, h = W / aspect;
    if (h > H)
    {
      h = H;
      w = H * aspect;
    }
    const float x0 = (W - w) * 0.5f, y0 = (H - h) * 0.5f;
    m_batch.Quad(x0, y0, x0 + w, y0 + h, 0, 0, 1, 1, {1, 1, 1, 1}, 0);
  }
  BuildHud(stats, m_haveFrame);

  glViewport(X(), Y(), Width(), Height());
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glClearColor(0, 0, 0, 1);
  glClear(GL_COLOR_BUFFER_BIT);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
#ifdef TARGET_DARWIN
  glBindVertexArray(m_vao);
#endif
  glUseProgram(m_program);
  glUniform2f(m_uScreen, W, H);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, m_gameTex);
  glUniform1i(m_uGame, 0);
  glActiveTexture(GL_TEXTURE1);
  glBindTexture(GL_TEXTURE_2D, m_fontTex);
  glUniform1i(m_uFont, 1);
  glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
  glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(m_batch.v.size() * sizeof(Vtx)), m_batch.v.data(), GL_STREAM_DRAW);
  auto attr = [&](GLint loc, int n, size_t off) {
    if (loc < 0)
      return;
    glEnableVertexAttribArray(static_cast<GLuint>(loc));
    glVertexAttribPointer(static_cast<GLuint>(loc), n, GL_FLOAT, GL_FALSE, sizeof(Vtx), reinterpret_cast<const void*>(off));
  };
  attr(m_aPos, 2, 0);
  attr(m_aUv, 2, 2 * sizeof(float));
  attr(m_aCol, 4, 4 * sizeof(float));
  attr(m_aMode, 1, 8 * sizeof(float));
  glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(m_batch.v.size()));
  for (GLint loc : {m_aPos, m_aUv, m_aCol, m_aMode})
    if (loc >= 0)
      glDisableVertexAttribArray(static_cast<GLuint>(loc));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glBindTexture(GL_TEXTURE_2D, 0);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, 0);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif
  glUseProgram(0);
}

ADDONCREATOR(CScreensaverAIArcade)

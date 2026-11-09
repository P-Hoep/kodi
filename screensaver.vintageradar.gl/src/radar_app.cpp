// The scope renderer. Everything except the font atlases is generated in the fragment shaders:
// the graticule, the bezel and its ticks, the phosphor haze and the sweep. Contacts, echoes and
// labels are batched into a handful of draw calls, then a CRT pass lays scanlines and a vignette
// over the lot.
#include "radar_app.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <map>
#include <sstream>
#include <vector>

#include "gl_include.hpp"
#include "gl_util.hpp"
#include "stb_image.h"

namespace radar {
namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double VW = 1920.0;
constexpr double VH = 1080.0;

constexpr double kSmall = 22.0;
constexpr double kMid = 30.0;
constexpr double kBig = 48.0;

struct Color {
  float r, g, b;
};

Color shade(Color c, float f) { return Color{c.r * f, c.g * f, c.b * f}; }

struct Theme {
  Color primary, dim, faint, bright, alert, military, ground, fill;
};

Theme make_theme(int id) {
  switch (id) {
    case 1:  // P3 amber
      return {{1.00f, 0.72f, 0.28f}, {0.56f, 0.36f, 0.12f}, {0.17f, 0.10f, 0.03f},
              {1.00f, 0.94f, 0.76f}, {1.00f, 0.32f, 0.20f}, {1.00f, 0.56f, 0.20f},
              {0.62f, 0.46f, 0.20f}, {0.030f, 0.018f, 0.006f}};
    case 2:  // P11 ice blue
      return {{0.58f, 0.84f, 1.00f}, {0.25f, 0.42f, 0.60f}, {0.06f, 0.12f, 0.20f},
              {0.88f, 0.97f, 1.00f}, {1.00f, 0.42f, 0.42f}, {1.00f, 0.80f, 0.42f},
              {0.42f, 0.54f, 0.64f}, {0.010f, 0.020f, 0.034f}};
    case 3:  // white phosphor
      return {{0.90f, 0.96f, 0.92f}, {0.45f, 0.53f, 0.47f}, {0.12f, 0.16f, 0.13f},
              {1.00f, 1.00f, 1.00f}, {1.00f, 0.36f, 0.30f}, {1.00f, 0.80f, 0.50f},
              {0.54f, 0.58f, 0.54f}, {0.022f, 0.026f, 0.023f}};
    default:  // P1 green
      return {{0.46f, 1.00f, 0.55f}, {0.21f, 0.56f, 0.29f}, {0.05f, 0.17f, 0.09f},
              {0.86f, 1.00f, 0.88f}, {1.00f, 0.34f, 0.22f}, {1.00f, 0.78f, 0.32f},
              {0.40f, 0.56f, 0.42f}, {0.010f, 0.032f, 0.018f}};
  }
}

int next_cp(const std::string& s, size_t& i) {
  const unsigned char c = static_cast<unsigned char>(s[i]);
  if (c < 0x80) {
    ++i;
    return c;
  }
  int n = 0;
  unsigned cp = 0;
  if ((c & 0xE0) == 0xC0) {
    n = 1;
    cp = c & 0x1F;
  } else if ((c & 0xF0) == 0xE0) {
    n = 2;
    cp = c & 0x0F;
  } else if ((c & 0xF8) == 0xF0) {
    n = 3;
    cp = c & 0x07;
  }
  if (n == 0 || i + static_cast<size_t>(n) >= s.size()) {
    ++i;
    return '?';
  }
  for (int k = 1; k <= n; ++k) {
    const unsigned char cc = static_cast<unsigned char>(s[i + static_cast<size_t>(k)]);
    if ((cc & 0xC0) != 0x80) {
      i += static_cast<size_t>(k);
      return '?';
    }
    cp = (cp << 6) | (cc & 0x3F);
  }
  i += static_cast<size_t>(n) + 1;
  return static_cast<int>(cp);
}

struct Font {
  unsigned tex = 0;
  int atlas_w = 0, atlas_h = 0;
  double size = 44.0, ascent = 42.0, descent = 11.0, line = 59.0;
  int cell_w = 0, cell_h = 0, cell_ox = 0, cell_oy = 0, columns = 16;
  std::map<int, double> adv;
  std::map<int, int> slot;

  double advance(int cp) const {
    auto it = adv.find(cp);
    if (it == adv.end()) it = adv.find('?');
    return it == adv.end() ? 0.0 : it->second;
  }
  double width(const std::string& s, double px, double tracking) const {
    const double scale = px / size;
    double w = 0.0;
    int n = 0;
    size_t i = 0;
    while (i < s.size()) {
      const int cp = next_cp(s, i);
      if (n > 0) w += tracking;
      w += advance(cp) * scale;
      ++n;
    }
    return w;
  }
  bool load(const std::string& base, std::string* error) {
    Json j;
    try {
      j = Json::read_file(base + ".json");
    } catch (const std::exception& e) {
      *error = std::string("font: ") + e.what();
      return false;
    }
    size = j.num_or("size", 44.0);
    ascent = j.num_or("ascent", size * 0.95);
    descent = j.num_or("descent", size * 0.25);
    line = j.num_or("line_height", size * 1.35);
    atlas_w = static_cast<int>(j.num_or("atlas_w", 0));
    atlas_h = static_cast<int>(j.num_or("atlas_h", 0));
    cell_w = static_cast<int>(j.num_or("cell_w", 0));
    cell_h = static_cast<int>(j.num_or("cell_h", 0));
    cell_ox = static_cast<int>(j.num_or("cell_ox", 0));
    cell_oy = static_cast<int>(j.num_or("cell_oy", 0));
    columns = std::max(1, static_cast<int>(j.num_or("columns", 16)));
    adv.clear();
    slot.clear();
    const Json* glyphs = j.get("glyphs");
    if (!glyphs || !glyphs->is_arr()) {
      *error = "font: missing glyphs";
      return false;
    }
    int index = 0;
    for (const Json& g : glyphs->arr) {
      const double cp = g.num_or("cp", -1);
      if (cp >= 0) {
        adv[static_cast<int>(cp)] = g.num_or("advance", 0.0);
        slot[static_cast<int>(cp)] = index;
      }
      ++index;
    }
    int w = 0, h = 0, comp = 0;
    unsigned char* pixels = stbi_load((base + ".png").c_str(), &w, &h, &comp, 4);
    if (!pixels) {
      *error = std::string("font image: ") + stbi_failure_reason();
      return false;
    }
    if (w != atlas_w || h != atlas_h) {
      atlas_w = w;
      atlas_h = h;
    }
    if (tex) glDeleteTextures(1, &tex);
    glGenTextures(1, &tex);
    GLint previous = 0;
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &previous);
    glBindTexture(GL_TEXTURE_2D, tex);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_2D, static_cast<unsigned>(previous));
    stbi_image_free(pixels);
    return true;
  }
  void destroy() {
    if (tex) glDeleteTextures(1, &tex);
    tex = 0;
  }
};

struct Vertex {
  float x, y, u, v;
  float r, g, b, a;
};

struct Rect {
  double x, y, w, h;
  bool hits(const Rect& o) const {
    return x < o.x + o.w && x + w > o.x && y < o.y + o.h && y + h > o.y;
  }
};

struct Layout {
  double cx, cy, r, bezel;
  bool panel;
  double px, py, pw, list_h, detail_y, detail_h;
};

Layout make_layout(const Settings& s) {
  if (s.show_panel) return {500.0, 576.0, 394.0, 430.0, true, 956.0, 132.0, 912.0, 536.0, 692.0, 316.0};
  return {960.0, 576.0, 400.0, 436.0, false, 0, 0, 0, 0, 0, 0};
}

std::string clock_string() {
  std::time_t t = std::time(nullptr);
  std::tm tm{};
#if defined(_WIN32)
  localtime_s(&tm, &t);
#else
  localtime_r(&t, &tm);
#endif
  char b[32];
  std::strftime(b, sizeof b, "%H:%M:%S", &tm);
  return b;
}

std::string date_string() {
  std::time_t t = std::time(nullptr);
  std::tm tm{};
#if defined(_WIN32)
  localtime_s(&tm, &t);
#else
  localtime_r(&t, &tm);
#endif
  char b[64];
  std::strftime(b, sizeof b, "%a %d %b %Y", &tm);
  return upper_string(b);
}

std::string seconds_short(double s) {
  if (s < 0) return "N/A";
  char b[32];
  if (s < 120.0)
    std::snprintf(b, sizeof b, "%.0fS", s);
  else
    std::snprintf(b, sizeof b, "%.0fM", s / 60.0);
  return b;
}

std::string pad2(int v) {
  char b[8];
  std::snprintf(b, sizeof b, "%02d", v);
  return b;
}

std::string truncate_utf8(const std::string& s, size_t max_bytes) {
  if (s.size() <= max_bytes) return s;
  size_t cut = max_bytes;
  while (cut > 0 && (static_cast<unsigned char>(s[cut]) & 0xC0) == 0x80) --cut;
  return s.substr(0, cut);
}

const char* kFlatVS = R"GLSL(
attribute vec2 a_pos;
attribute vec2 a_uv;
attribute vec4 a_color;
uniform vec4 u_xform;
varying vec2 v_uv;
varying vec4 v_color;
varying vec2 v_pos;
void main() {
  v_uv = a_uv;
  v_color = a_color;
  v_pos = a_pos;
  gl_Position = vec4(a_pos.x * u_xform.x + u_xform.z,
                     a_pos.y * u_xform.y + u_xform.w, 0.0, 1.0);
}
)GLSL";

const char* kFullVS = R"GLSL(
attribute vec2 a_pos;
attribute vec2 a_uv;
attribute vec4 a_color;
varying vec2 v_uv;
varying vec2 v_pos;
void main() {
  v_uv = a_uv;
  v_pos = a_pos;
  gl_Position = vec4(a_pos, 0.0, 1.0);
}
)GLSL";

const char* kBackgroundFS = R"GLSL(
varying vec2 v_uv;
uniform vec3 u_color;
uniform float u_time;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }
void main() {
  vec2 d = v_uv - vec2(0.5, 0.54);
  float glow = exp(-length(d * vec2(1.0, 1.22)) * 4.4);
  float grain = hash(floor(v_uv * vec2(960.0, 540.0)) + floor(u_time * 18.0));
  vec3 col = u_color * (0.075 + glow * 0.34);
  col += u_color * grain * 0.024;
  gl_FragColor = vec4(col, 1.0);
}
)GLSL";

const char* kDiscFS = R"GLSL(
varying vec2 v_pos;
uniform vec2 u_center;
uniform float u_radius;
uniform float u_bezel;
uniform float u_sweep;
uniform float u_sweep_on;
uniform float u_time;
uniform float u_quality;
uniform vec3 u_color;

float line_at(float r, float target, float w) {
  return 1.0 - smoothstep(0.0, w, abs(r - target));
}
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }

void main() {
  vec2 d = v_pos - u_center;
  float r = length(d);
  if (r > u_bezel + 34.0) { gl_FragColor = vec4(0.0); return; }

  float disc_r = u_radius;
  float inside = 1.0 - step(disc_r, r);
  float ang = mod(degrees(atan(d.x, -d.y)) + 360.0, 360.0);
  float rr = r / disc_r;
  float col = 0.0;

  col += inside * (0.014 + 0.034 * pow(max(1.0 - rr, 0.0), 1.8));
  col += inside * (line_at(rr, 0.125, 0.0012) * 0.055 +
                   line_at(rr, 0.25, 0.0020) * 0.22 +
                   line_at(rr, 0.375, 0.0012) * 0.055 +
                   line_at(rr, 0.5, 0.0020) * 0.30 +
                   line_at(rr, 0.625, 0.0012) * 0.055 +
                   line_at(rr, 0.75, 0.0020) * 0.24 +
                   line_at(rr, 0.875, 0.0012) * 0.055 +
                   line_at(rr, 1.0, 0.0026) * 0.62);

  float a10 = mod(ang, 10.0); a10 = min(a10, 10.0 - a10);
  float a30 = mod(ang, 30.0); a30 = min(a30, 30.0 - a30);
  float a90 = mod(ang, 90.0); a90 = min(a90, 90.0 - a90);
  float sd10 = abs(sin(radians(a10))) * r;
  float sd30 = abs(sin(radians(a30))) * r;
  float sd90 = abs(sin(radians(a90))) * r;
  float spoke = max(max((1.0 - smoothstep(0.0, 1.0, sd10)) * 0.10,
                        (1.0 - smoothstep(0.0, 1.2, sd30)) * 0.15),
                    (1.0 - smoothstep(0.0, 1.5, sd90)) * 0.23);
  col += inside * spoke * smoothstep(5.0, 20.0, r);
  col += inside * (0.50 * exp(-r / 20.0) + 0.10 * exp(-r / 90.0));  // hub glow

  float band = step(disc_r, r) * step(r, u_bezel);
  float a2 = mod(ang, 2.0); a2 = min(a2, 2.0 - a2);
  float a10b = mod(ang, 10.0); a10b = min(a10b, 10.0 - a10b);
  float tick = 1.0 - smoothstep(0.0, 0.42, abs(sin(radians(a2))) * r);
  float long_tick = 1.0 - smoothstep(0.0, 0.75, abs(sin(radians(a10b))) * r);
  col += band * (tick * 0.24 + long_tick * 0.34);

  col += line_at(r, disc_r, 1.15) * 0.72;
  col += line_at(r, u_bezel, 1.35) * 0.88;
  col += line_at(r, u_bezel * 0.984, 0.65) * 0.28;
  col += exp(-max(r - u_bezel, 0.0) / 13.0) * 0.10;

  if (u_sweep_on > 0.5 && r < disc_r) {
    float behind = mod(u_sweep - ang + 360.0, 360.0);
    float trail = pow(clamp(1.0 - behind / 100.0, 0.0, 1.0), 2.3);
    float lead = exp(-behind / 1.7) + exp(-(360.0 - behind) / 1.2) * 0.35;
    float radial = smoothstep(0.0, 24.0, r) * (1.0 - 0.30 * r / disc_r);
    col += (trail * 0.25 + lead * 0.68) * radial;
  }

  float grain = hash(floor(v_pos * 0.7) + floor(u_time * 20.0));
  col += inside * grain * 0.010;
  col *= 0.93 + 0.07 * sin(v_pos.y * 2.0943951);
  col *= 0.88 + 0.24 * u_quality;
  gl_FragColor = vec4(u_color * col, 1.0);
}
)GLSL";

const char* kBlipFS = R"GLSL(
varying vec2 v_uv;
varying vec4 v_color;
void main() {
  vec2 p = v_uv * 2.0 - 1.0;
  float r2 = dot(p, p);
  float a = (exp(-r2 * 8.0) + 0.30 * exp(-r2 * 2.2)) * v_color.a;
  gl_FragColor = vec4(v_color.rgb, a);
}
)GLSL";

const char* kSpriteFS = R"GLSL(
uniform sampler2D u_tex;
varying vec2 v_uv;
varying vec4 v_color;
void main() {
  float a = texture2D(u_tex, v_uv).a * v_color.a;
  gl_FragColor = vec4(v_color.rgb, a);
}
)GLSL";

const char* kTextFS = R"GLSL(
uniform sampler2D u_tex;
uniform float u_glow;
varying vec2 v_uv;
varying vec4 v_color;
void main() {
  vec4 t = texture2D(u_tex, v_uv);
  float a = (t.r + t.g * u_glow) * v_color.a;
  gl_FragColor = vec4(v_color.rgb, a);
}
)GLSL";

const char* kOverlayFS = R"GLSL(
varying vec2 v_uv;
uniform vec2 u_res;
uniform float u_time;
uniform float u_crt;
uniform float u_dim;
void main() {
  float scan = 0.5 + 0.5 * sin(v_uv.y * u_res.y * 2.0943951);
  vec2 d = (v_uv - 0.5) * vec2(1.0, 0.92);
  float vig = smoothstep(0.40, 0.98, length(d) * 1.38);
  float a = u_dim * 0.008;
  a += u_crt * (0.040 * scan + 0.32 * vig);
  a += 0.006 * u_crt * (0.5 + 0.5 * sin(u_time * 9.0));
  gl_FragColor = vec4(0.0, 0.0, 0.0, clamp(a, 0.0, 0.9));
}
)GLSL";

}  // namespace

struct App::Impl {
  Settings settings;
  Model model;
  std::unique_ptr<FeedPump> pump;
  FeedPump::Fetch fetch;
  std::string media;
  std::string error;

  Font fonts[3];

  enum Prog { kBackground, kDisc, kBlip, kSprite, kText, kOverlay, kProgCount };
  unsigned prog[kProgCount] = {0, 0, 0, 0, 0, 0};
  unsigned vbo = 0, vao = 0, white_tex = 0;

  int u_bg_color = -1, u_bg_time = -1;
  int u_xform = -1;
  int u_disc_center = -1, u_disc_radius = -1, u_disc_bezel = -1, u_disc_sweep = -1;
  int u_disc_sweep_on = -1, u_disc_time = -1, u_disc_quality = -1, u_disc_color = -1;
  int u_sprite_tex = -1;
  int u_text_tex = -1, u_text_glow = -1;
  int u_overlay_res = -1, u_overlay_time = -1, u_overlay_crt = -1, u_overlay_dim = -1;

  std::vector<Vertex> fills;   // normal alpha
  std::vector<Vertex> solids;  // additive
  std::vector<Vertex> blips;   // additive
  std::vector<Vertex> texts[3];
  std::vector<Vertex> fullscreen;

  Layout layout;
  Theme theme;
  std::string pick_hex;
  float xform4[4] = {1.0f, 1.0f, 0.0f, 0.0f};  // the virtual-to-clip transform of this frame

  // ---- shader and buffer set-up -------------------------------------------------------------
  bool make_programs(std::string* err) {
    static const char* attrs[] = {"a_pos", "a_uv", "a_color"};
    struct Pair {
      int index;
      const char* vs;
      const char* fs;
      const char* name;
    };
    const Pair pairs[] = {
        {kBackground, kFullVS, kBackgroundFS, "background"},
        {kDisc, kFlatVS, kDiscFS, "disc"},
        {kBlip, kFlatVS, kBlipFS, "blip"},
        {kSprite, kFlatVS, kSpriteFS, "sprite"},
        {kText, kFlatVS, kTextFS, "text"},
        {kOverlay, kFullVS, kOverlayFS, "overlay"},
    };
    for (const Pair& p : pairs) {
      std::string e;
      prog[p.index] = glu::link(p.vs, p.fs, attrs, 3, &e);
      if (!prog[p.index]) {
        *err = std::string(p.name) + " shader: " + e;
        return false;
      }
    }
    u_bg_color = glGetUniformLocation(prog[kBackground], "u_color");
    u_bg_time = glGetUniformLocation(prog[kBackground], "u_time");
    u_xform = glGetUniformLocation(prog[kDisc], "u_xform");
    u_disc_center = glGetUniformLocation(prog[kDisc], "u_center");
    u_disc_radius = glGetUniformLocation(prog[kDisc], "u_radius");
    u_disc_bezel = glGetUniformLocation(prog[kDisc], "u_bezel");
    u_disc_sweep = glGetUniformLocation(prog[kDisc], "u_sweep");
    u_disc_sweep_on = glGetUniformLocation(prog[kDisc], "u_sweep_on");
    u_disc_time = glGetUniformLocation(prog[kDisc], "u_time");
    u_disc_quality = glGetUniformLocation(prog[kDisc], "u_quality");
    u_disc_color = glGetUniformLocation(prog[kDisc], "u_color");
    u_sprite_tex = glGetUniformLocation(prog[kSprite], "u_tex");
    u_text_tex = glGetUniformLocation(prog[kText], "u_tex");
    u_text_glow = glGetUniformLocation(prog[kText], "u_glow");
    u_overlay_res = glGetUniformLocation(prog[kOverlay], "u_res");
    u_overlay_time = glGetUniformLocation(prog[kOverlay], "u_time");
    u_overlay_crt = glGetUniformLocation(prog[kOverlay], "u_crt");
    u_overlay_dim = glGetUniformLocation(prog[kOverlay], "u_dim");
    return true;
  }

  bool make_buffers(std::string* err) {
#ifdef RADAR_CORE
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
#endif
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(Vertex) * 6, nullptr, GL_STREAM_DRAW);
    set_attrs();
    const unsigned char white[4] = {255, 255, 255, 255};
    glGenTextures(1, &white_tex);
    GLint previous = 0;
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &previous);
    glBindTexture(GL_TEXTURE_2D, white_tex);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, white);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glBindTexture(GL_TEXTURE_2D, static_cast<unsigned>(previous));
#ifdef RADAR_CORE
    glBindVertexArray(0);
#endif
    (void)err;
    return true;
  }

  void set_attrs() {
    glEnableVertexAttribArray(0);
    glEnableVertexAttribArray(1);
    glEnableVertexAttribArray(2);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                          reinterpret_cast<const void*>(0));
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                          reinterpret_cast<const void*>(sizeof(float) * 2));
    glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                          reinterpret_cast<const void*>(sizeof(float) * 4));
  }

  // ---- geometry -----------------------------------------------------------------------------
  static void push_quad(std::vector<Vertex>& out, double x0, double y0, double x1, double y1,
                        double u0, double v0, double u1, double v1, Color c, float a) {
    const float r = c.r, g = c.g, b = c.b;
    const Vertex v[4] = {{static_cast<float>(x0), static_cast<float>(y0), static_cast<float>(u0),
                          static_cast<float>(v0), r, g, b, a},
                         {static_cast<float>(x1), static_cast<float>(y0), static_cast<float>(u1),
                          static_cast<float>(v0), r, g, b, a},
                         {static_cast<float>(x1), static_cast<float>(y1), static_cast<float>(u1),
                          static_cast<float>(v1), r, g, b, a},
                         {static_cast<float>(x0), static_cast<float>(y1), static_cast<float>(u0),
                          static_cast<float>(v1), r, g, b, a}};
    out.push_back(v[0]);
    out.push_back(v[1]);
    out.push_back(v[2]);
    out.push_back(v[0]);
    out.push_back(v[2]);
    out.push_back(v[3]);
  }

  void line(double x0, double y0, double x1, double y1, double width, Color c, float a) {
    const double dx = x1 - x0, dy = y1 - y0;
    const double len = std::sqrt(dx * dx + dy * dy);
    if (len < 0.001) return;
    const double nx = -dy / len * width * 0.5;
    const double ny = dx / len * width * 0.5;
    const float r = c.r, g = c.g, b = c.b;
    const Vertex v[4] = {
        {static_cast<float>(x0 + nx), static_cast<float>(y0 + ny), 0.5f, 0.5f, r, g, b, a},
        {static_cast<float>(x1 + nx), static_cast<float>(y1 + ny), 0.5f, 0.5f, r, g, b, a},
        {static_cast<float>(x1 - nx), static_cast<float>(y1 - ny), 0.5f, 0.5f, r, g, b, a},
        {static_cast<float>(x0 - nx), static_cast<float>(y0 - ny), 0.5f, 0.5f, r, g, b, a}};
    solids.push_back(v[0]);
    solids.push_back(v[1]);
    solids.push_back(v[2]);
    solids.push_back(v[0]);
    solids.push_back(v[2]);
    solids.push_back(v[3]);
  }

  void fill_rect(double x, double y, double w, double h, Color c, float a) {
    push_quad(fills, x, y, x + w, y + h, 0.5, 0.5, 0.5, 0.5, c, a);
  }

  void glow_rect(double x, double y, double w, double h, Color c, float a) {
    push_quad(solids, x, y, x + w, y + h, 0.5, 0.5, 0.5, 0.5, c, a);
  }

  void rect_outline(double x, double y, double w, double h, double line_w, Color c, float a) {
    line(x, y, x + w, y, line_w, c, a);
    line(x + w, y, x + w, y + h, line_w, c, a);
    line(x + w, y + h, x, y + h, line_w, c, a);
    line(x, y + h, x, y, line_w, c, a);
  }

  void corner_brackets(double x, double y, double w, double h, double len, Color c, float a) {
    line(x, y, x + len, y, 2.0, c, a);
    line(x, y, x, y + len, 2.0, c, a);
    line(x + w - len, y, x + w, y, 2.0, c, a);
    line(x + w, y, x + w, y + len, 2.0, c, a);
    line(x, y + h - len, x, y + h, 2.0, c, a);
    line(x, y + h, x + len, y + h, 2.0, c, a);
    line(x + w - len, y + h, x + w, y + h, 2.0, c, a);
    line(x + w, y + h - len, x + w, y + h, 2.0, c, a);
  }

  void blip_quad(double x, double y, double size, Color c, float a) {
    push_quad(blips, x - size * 0.5, y - size * 0.5, x + size * 0.5, y + size * 0.5, 0.0, 0.0,
              1.0, 1.0, c, a);
  }

  void ring(double cx, double cy, double radius, int segments, double width, Color c, float a) {
    double px = cx + radius, py = cy;
    for (int i = 1; i <= segments; ++i) {
      const double t = 2.0 * kPi * i / segments;
      const double nx = cx + std::cos(t) * radius;
      const double ny = cy + std::sin(t) * radius;
      line(px, py, nx, ny, width, c, a);
      px = nx;
      py = ny;
    }
  }

  // ---- text ---------------------------------------------------------------------------------
  void text(int fi, const std::string& s, double x, double y_top, double px, Color c, float alpha,
            double tracking = 0.0, int align = 0) {
    const Font& f = fonts[fi];
    const double scale = px / f.size;
    if (align != 0) {
      const double w = f.width(s, px, tracking);
      if (align == 1) x -= w * 0.5;
      else x -= w;
    }
    const double baseline = y_top + f.ascent * scale;
    double pen = x;
    bool first = true;
    size_t i = 0;
    while (i < s.size()) {
      const int cp = next_cp(s, i);
      int slot = -1;
      auto si = f.slot.find(cp);
      if (si == f.slot.end()) si = f.slot.find('?');
      if (si != f.slot.end()) slot = si->second;
      auto ai = f.adv.find(cp);
      if (ai == f.adv.end()) ai = f.adv.find('?');
      if (ai == f.adv.end()) continue;
      if (!first) pen += tracking;
      if (slot >= 0 && cp != ' ') {
        const int col = slot % f.columns;
        const int row = slot / f.columns;
        const double x0 = pen - f.cell_ox * scale;
        const double y0 = baseline + f.cell_oy * scale;
        const double x1 = x0 + f.cell_w * scale;
        const double y1 = y0 + f.cell_h * scale;
        const double u0 = static_cast<double>(col * f.cell_w) / f.atlas_w;
        const double v0 = static_cast<double>(row * f.cell_h) / f.atlas_h;
        const double u1 = static_cast<double>((col + 1) * f.cell_w) / f.atlas_w;
        const double v1 = static_cast<double>((row + 1) * f.cell_h) / f.atlas_h;
        push_quad(texts[fi], x0, y0, x1, y1, u0, v0, u1, v1, c, alpha);
      }
      pen += ai->second * scale;
      first = false;
    }
  }

  double text_width(int fi, const std::string& s, double px, double tracking = 0.0) const {
    return fonts[fi].width(s, px, tracking);
  }

  std::string fit(int fi, const std::string& s, double px, double max_w, double tracking = 0.0) {
    if (text_width(fi, s, px, tracking) <= max_w) return s;
    std::string out = s;
    while (!out.empty() && text_width(fi, out + "...", px, tracking) > max_w) {
      while (!out.empty() && (static_cast<unsigned char>(out.back()) & 0xC0) == 0x80)
        out.pop_back();
      if (!out.empty()) out.pop_back();
    }
    return out + "...";
  }

  void field(double x, double y, const std::string& label, const std::string& value,
             Color value_color) {
    const double lw = text_width(0, label + " ", 17.0);
    text(0, label + " ", x, y, 17.0, theme.dim, 0.62f);
    text(0, value, x + lw, y, 17.0, value_color, 0.95f);
  }

  // ---- frame --------------------------------------------------------------------------------
  void draw_vertices(int program, const std::vector<Vertex>& list, unsigned tex, bool add) {
    if (list.empty()) return;
    glUseProgram(prog[program]);
    const int xf = glGetUniformLocation(prog[program], "u_xform");
    if (xf >= 0) glUniform4f(xf, xform4[0], xform4[1], xform4[2], xform4[3]);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    set_attrs();
    glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(list.size() * sizeof(Vertex)),
                 list.data(), GL_STREAM_DRAW);
    if (tex) {
      glActiveTexture(GL_TEXTURE0);
      glBindTexture(GL_TEXTURE_2D, tex);
      const int loc = program == kSprite ? u_sprite_tex : u_text_tex;
      glUniform1i(loc, 0);
    }
    if (add)
      glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    else
      glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(list.size()));
  }

  void fullscreen_quad() {
    push_quad(fullscreen, -1, -1, 1, 1, 0, 1, 1, 0, Color{1, 1, 1}, 1.0f);
  }

  void draw_fullscreen(int program, const std::vector<Vertex>& list, bool add) {
    glUseProgram(prog[program]);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    set_attrs();
    glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(list.size() * sizeof(Vertex)),
                 list.data(), GL_STREAM_DRAW);
    if (add)
      glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    else
      glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(list.size()));
  }

  void build_header(double now) {
    const Theme& t = theme;
    text(2, "VINTAGE RADAR", 34, 8, kBig, t.primary, 1.0f, 1.6);
    std::string sub = "AIRCRAFT OVERHEAD  ·  " + upper_string(settings.location_name) + "  ·  RANGE " +
                      range_short(settings.range_km, settings.units);
    text(0, sub, 36, 80, 18.0, t.dim, 0.95f);

    text(1, clock_string(), 1886, 6, 34.0, t.bright, 0.98f, 1.0, 2);
    text(0, date_string(), 1886, 58, 16.0, t.dim, 0.9f, 0.0, 2);

    const double age = model.feed_age(now);
    std::string status;
    Color status_color = t.dim;
    if (age < 0.0) {
      status = "ACQUIRING SIGNAL";
      status_color = t.dim;
    } else if (model.stale(now)) {
      status = "STALE " + seconds_short(age);
      status_color = t.alert;
    } else {
      status = "LIVE  " + seconds_short(age) + " AGO";
      status_color = t.primary;
    }
    text(0, status, 1886, 80, 16.0, status_color, 0.95f, 0.0, 2);

    line(30, 118, 520, 118, 1.5, t.primary, 0.55f);
    line(520, 118, 1890, 118, 1.0, t.dim, 0.35f);
  }

  void build_footer(double now) {
    const Theme& t = theme;
    line(30, 1028, 1890, 1028, 1.0, t.dim, 0.35f);
    char b[64];
    std::snprintf(b, sizeof b, "RANGE %s", range_text(settings.range_km, settings.units).c_str());
    text(0, b, 34, 1038, 16.0, t.dim, 0.85f);

    const int secs = static_cast<int>(std::ceil(model.seconds_to_sweep()));
    std::snprintf(b, sizeof b, "SWEEP %02dS  ·  %d IN RANGE  ·  %d TRACKED", secs,
                  model.in_range_count(), model.known_count());
    text(0, b, 960, 1038, 16.0, t.dim, 0.85f, 0.0, 1);

    const std::string source = model.feed_source().empty() ? "NO FEED" : model.feed_source();
    std::snprintf(b, sizeof b, "SOURCE %s  ·  %s", upper_string(source).c_str(),
                  seconds_short(model.feed_age(now)).c_str());
    text(0, b, 1886, 1038, 16.0, t.dim, 0.85f, 0.0, 2);

    if (!model.feed_error().empty() && model.stale(now)) {
      text(0, fit(0, "FEED ERROR  " + model.feed_error(), 16.0, 1200.0), 960, 1058, 16.0, t.alert,
           0.95f, 0.0, 1);
    }
  }

  void build_panels() {
    const Theme& t = theme;
    if (!layout.panel) return;
    const double x = layout.px, w = layout.pw;
    fill_rect(x, layout.py, w, layout.list_h, t.fill, 0.90f);
    fill_rect(x, layout.detail_y, w, layout.detail_h, t.fill, 0.90f);
    rect_outline(x, layout.py, w, layout.list_h, 1.5, t.primary, 0.55f);
    rect_outline(x, layout.detail_y, w, layout.detail_h, 1.5, t.primary, 0.55f);
    corner_brackets(x, layout.py, w, layout.list_h, 22.0, t.bright, 0.85f);
    corner_brackets(x, layout.detail_y, w, layout.detail_h, 22.0, t.bright, 0.85f);
    line(x + 10, layout.py + 56, x + w - 10, layout.py + 56, 1.0, t.primary, 0.32f);
    line(x + 10, layout.detail_y + 40, x + w - 10, layout.detail_y + 40, 1.0, t.primary, 0.32f);
  }

  void build_compass() {
    const Theme& t = theme;
    const double hub_x = layout.cx, hub_y = layout.cy;
    ring(hub_x, hub_y, 5.0, 28, 1.2, t.bright, 0.85f);
    line(hub_x - 13, hub_y, hub_x - 7, hub_y, 1.4, t.bright, 0.8f);
    line(hub_x + 7, hub_y, hub_x + 13, hub_y, 1.4, t.bright, 0.8f);
    line(hub_x, hub_y - 13, hub_x, hub_y - 7, 1.4, t.bright, 0.8f);
    line(hub_x, hub_y + 7, hub_x, hub_y + 13, 1.4, t.bright, 0.8f);
    const double mid = (layout.r + layout.bezel) * 0.5;
    for (int deg = 0; deg < 360; deg += 30) {
      char b[8];
      std::snprintf(b, sizeof b, "%03d", deg);
      const double a = deg * kPi / 180.0;
      const double x = layout.cx + std::sin(a) * mid;
      const double y = layout.cy - std::cos(a) * mid;
      text(0, b, x, y - 8, 15.0, t.dim, 0.95f, 0.0, 1);
    }
    // Range rings, labelled along the north-east spoke.
    const double a = 45.0 * kPi / 180.0;
    for (int i = 1; i <= 4; ++i) {
      const double frac = i / 4.0;
      const int km = static_cast<int>(std::lround(settings.range_km * frac));
      char b[32];
      if (i == 4)
        std::snprintf(b, sizeof b, "%dKM", km);
      else
        std::snprintf(b, sizeof b, "%d", km);
      const double rr = i == 4 ? layout.r * 0.955 : layout.r * frac;
      const double x = layout.cx + std::sin(a) * rr + 7;
      const double y = layout.cy - std::cos(a) * rr - 9;
      text(0, b, x, y, 15.0, t.faint, 0.95f);
    }
  }

  void build_blips_and_labels(double now) {
    const Theme& t = theme;
    std::vector<Rect> used;
    int labels = 0;
    const int label_cap = settings.quality == 0 ? 10 : 18;
    const int rows = model.page_rows();

    for (int idx : model.order()) {
      const Contact& c = model.contacts()[static_cast<size_t>(idx)];
      const double x = layout.cx + c.x * layout.r;
      const double y = layout.cy - c.y * layout.r;
      if (!c.in_range) continue;

      if (settings.quality > 0 && settings.show_history) {
        for (int e = c.echo_count - 1; e >= 0; --e) {
          const Echo& echo = c.echoes[static_cast<size_t>(e)];
          if (!echo.active) continue;
          const double ex = layout.cx + echo.x * layout.r;
          const double ey = layout.cy - echo.y * layout.r;
          const double size = 16.0 + 6.0 * e;
          blip_quad(ex, ey, size, t.primary, static_cast<float>(0.05 * c.blip / (1.0 + e)));
        }
      }

      if (c.ac.on_ground) {
        const double size = 7.0 + 4.0 * c.blip;
        blip_quad(x, y, size, t.ground, 0.55f + 0.25f * static_cast<float>(c.blip));
      } else {
        const double size = 13.0 + 8.0 * c.blip;
        blip_quad(x, y, size, c.selected ? t.bright : t.primary,
                  static_cast<float>(std::min(1.0, 0.20 + c.blip * 0.78)));
      }
      if (c.selected) {
        ring(x, y, 21.0, 40, 1.4, t.bright, 0.7f);
        ring(x, y, 25.0, 40, 0.8, t.primary, 0.30f);
      }

      if (!settings.show_labels) continue;
      if (!c.selected && labels >= label_cap) continue;

      std::string l1 = aircraft_name(c.ac);
      l1 = truncate_utf8(l1, 12);
      std::string l2;
      if (settings.label_detail == 1)
        l2 = fmt_altitude(c.ac, settings.units, true) + "  " + fmt_speed(c.ac, settings.units, true);
      else if (settings.label_detail == 2)
        l2 = (c.ac.type_code.empty() ? category_name(c.ac.category) : c.ac.type_code) + "  " +
             fmt_altitude(c.ac, settings.units, true);
      if (c.ac.on_ground) l2 = "GND  " + fmt_speed(c.ac, settings.units, true);

      const double l1w = text_width(0, l1, 19.0);
      const double l2w = l2.empty() ? 0.0 : text_width(0, l2, 15.0);
      const double w = std::max(l1w, l2w) + 4.0;
      const double h = l2.empty() ? 22.0 : 38.0;
      struct Cand { double x, y; int align; };
      const Cand cands[] = {
          {x + 15, y - h + 4, 0}, {x - 15 - w, y - h + 4, 0}, {x + 15, y + 12, 0},
          {x - 15 - w, y + 12, 0},
      };
      Rect chosen{0, 0, 0, 0};
      bool place = false;
      for (const Cand& cd : cands) {
        Rect r{cd.x, cd.y, w, h};
        if (r.x < 24 || r.y < 132 || r.x + r.w > 1900 || r.y + r.h > 1014) continue;
        bool clash = false;
        for (const Rect& u : used)
          if (r.hits(u)) {
            clash = true;
            break;
          }
        if (!clash) {
          chosen = r;
          place = true;
          break;
        }
      }
      if (!place && c.selected) {
        chosen = Rect{x + 15, y + 12, w, h};
        place = true;
      }
      if (!place) continue;
      used.push_back(chosen);
      ++labels;

      const Color label_color = c.selected ? theme.bright
                                           : (!emergency_label(c.ac).empty() ? theme.alert
                                                                             : theme.primary);
      const float alpha = c.selected ? 1.0f : 0.82f;
      const double lx = chosen.x + 2;
      const double ly = chosen.y;
      line(x, y, lx, ly + h * 0.5, 1.0, label_color, c.selected ? 0.55f : 0.22f);
      text(0, l1, lx, ly, 19.0, label_color, alpha, 0.4);
      if (!l2.empty()) text(0, l2, lx, ly + 21, 15.0, label_color, alpha * 0.75f, 0.2);
      if (c.selected) {
        line(lx - 3, ly, lx - 3, ly + 12, 1.5, theme.bright, 0.7f);
        line(lx - 7, ly, lx - 3, ly, 1.5, theme.bright, 0.7f);
      }
    }
    (void)now;
    (void)rows;
  }

  void build_list() {
    const Theme& t = theme;
    if (!layout.panel) return;
    const double x = layout.px;
    const double w = layout.pw;
    const double right = x + w - 20;
    text(1, "CONTACTS", x + 22, 142, 22.0, t.bright, 0.95f, 1.0);
    char b[64];
    std::snprintf(b, sizeof b, "%d IN RANGE / %d", model.in_range_count(), model.known_count());
    text(0, b, right, 146, 17.0, t.dim, 0.95f, 0.0, 2);
    std::snprintf(b, sizeof b, "NEAREST FIRST   PAGE %d/%d", model.page() + 1, model.page_count());
    text(0, b, right, 163, 15.0, t.faint, 0.95f, 0.0, 2);

    const double header_y = 202;
    text(0, "CALLSIGN", x + 44, header_y, 14.0, t.faint, 0.9f);
    text(0, "TYPE", x + 274, header_y, 14.0, t.faint, 0.9f);
    text(0, "ALT", x + 464, header_y, 14.0, t.faint, 0.9f, 0.0, 2);
    text(0, "SPD", x + 604, header_y, 14.0, t.faint, 0.9f, 0.0, 2);
    text(0, "DIST", x + 764, header_y, 14.0, t.faint, 0.9f, 0.0, 2);
    text(0, "BRG", right, header_y, 14.0, t.faint, 0.9f, 0.0, 2);
    line(x + 14, 224, right, 224, 1.0, t.dim, 0.35f);

    const int rows = model.page_rows();
    const int start = model.page() * rows;
    const double row_h = 36.0;
    for (int r = 0; r < rows; ++r) {
      const int pos = start + r;
      if (pos >= static_cast<int>(model.order().size())) break;
      const Contact& c = model.contacts()[static_cast<size_t>(model.order()[static_cast<size_t>(pos)])];
      const double ry = 232 + r * row_h;
      const Color name_color = c.selected ? t.bright
                                          : (!emergency_label(c.ac).empty() ? t.alert
                                                                            : (c.ac.military ? t.military
                                                                                             : t.primary));
      if (c.selected) {
        glow_rect(x + 14, ry - 1, w - 28, row_h - 2, t.primary, 0.10f);
        line(x + 14, ry - 1, x + 14, ry + row_h - 3, 3.0, t.bright, 0.9f);
      }
      std::string name = truncate_utf8(aircraft_name(c.ac), 9);
      text(0, name, x + 44, ry + 5, 22.0, name_color, c.selected ? 1.0f : 0.9f, 0.4);
      std::string type = c.ac.type_code.empty() ? category_name(c.ac.category) : c.ac.type_code;
      text(0, truncate_utf8(type, 6), x + 274, ry + 8, 16.0, t.dim, 0.85f);
      text(0, fmt_altitude(c.ac, settings.units, true), x + 464, ry + 7, 18.0, t.primary,
           c.selected ? 1.0f : 0.8f, 0.0, 2);
      text(0, fmt_speed(c.ac, settings.units, true), x + 604, ry + 7, 18.0, t.primary,
           c.selected ? 1.0f : 0.8f, 0.0, 2);
      text(0, fmt_distance(c.distance_m, settings.units, true), x + 764, ry + 7, 18.0, t.primary,
           c.selected ? 1.0f : 0.8f, 0.0, 2);
      text(0, fmt_bearing(c.bearing_deg), right, ry + 7, 18.0, t.dim,
           c.selected ? 1.0f : 0.8f, 0.0, 2);
    }
    if (model.order().empty()) {
      text(1, "NO CONTACTS IN RANGE", x + w * 0.5, 380, 24.0, t.dim, 0.9f, 0.0, 1);
      text(0, "WAITING FOR A SWEEP", x + w * 0.5, 416, 16.0, t.faint, 0.9f, 0.0, 1);
    }
    line(x + 14, layout.py + layout.list_h - 12, right, layout.py + layout.list_h - 12, 1.0, t.dim,
         0.30f);
  }

  void build_detail() {
    const Theme& t = theme;
    if (!layout.panel) return;
    const double x = layout.px;
    const double right = x + layout.pw - 20;
    const Contact* c = model.spotlight();
    const int pos = model.spotlight_position();
    const int total = static_cast<int>(model.order().size());

    text(0, "SPOTLIGHT", x + 22, layout.detail_y + 12, 16.0, t.dim, 0.95f, 1.0);
    char b[64];
    if (pos >= 0)
      std::snprintf(b, sizeof b, "%d / %d", pos + 1, total);
    else
      std::snprintf(b, sizeof b, "-- / --");
    text(0, b, x + 150, layout.detail_y + 12, 16.0, t.faint, 0.9f);
    text(0, model.pinned() ? "PINNED" : "AUTO", right, layout.detail_y + 12, 16.0,
         model.pinned() ? t.bright : t.dim, 0.9f, 0.0, 2);

    if (!c) {
      text(1, "NO CONTACT", x + layout.pw * 0.5, layout.detail_y + 110, 30.0, t.dim, 0.85f, 0.0, 1);
      text(0, "THE SCOPE IS CLEAR", x + layout.pw * 0.5, layout.detail_y + 160, 16.0, t.faint, 0.8f,
           0.0, 1);
      return;
    }

    const Aircraft& ac = c->ac;
    const std::string name = truncate_utf8(aircraft_name(ac), 12);
    text(2, name, x + 22, layout.detail_y + 38, 40.0, t.bright, 1.0f, 1.2);
    const double name_w = text_width(2, name, 40.0, 1.2);
    std::string kind = ac.type_code.empty() ? category_name(ac.category) : ac.type_code;
    if (!ac.reg.empty() && upper_string(ac.reg) != name) kind = upper_string(ac.reg) + "  " + kind;
    text(0, truncate_utf8(kind, 22), x + 22 + name_w + 20, layout.detail_y + 50, 18.0, t.dim,
         0.95f);

    std::string info = "HEX " + upper_string(ac.hex);
    if (!ac.squawk.empty()) info += "  ·  SQK " + ac.squawk;
    if (!ac.category.empty()) info += "  ·  " + ac.category + " " + category_name(ac.category);
    info += "  ·  " + source_name(ac);
    if (!ac.type.empty()) info += "  ·  " + upper_string(ac.type);
    text(0, fit(0, info, 16.0, layout.pw - 44), x + 22, layout.detail_y + 88, 16.0, t.dim, 0.95f);

    const double bar_y = layout.detail_y + 112;
    line(x + 22, bar_y, right, bar_y, 2.0, t.dim, 0.35f);
    const double progress = model.spotlight_progress();
    if (progress > 0.0) {
      line(x + 22, bar_y, x + 22 + (layout.pw - 44) * progress, bar_y, 2.0, t.primary, 0.65f);
      glow_rect(x + 22 + (layout.pw - 44) * progress - 3, bar_y - 3, 6, 6, t.bright, 0.8f);
    } else if (model.pinned()) {
      line(x + 22, bar_y, right, bar_y, 2.0, t.bright, 0.8f);
    }

    const double row1 = layout.detail_y + 126;
    const double row2 = row1 + 27;
    const double row3 = row2 + 27;
    const double qrow = row3 + 27;
    const double nrow = qrow + 25;
    const double frow = nrow + 25;
    const double c1 = x + 22, c2 = x + 242, c3 = x + 462, c4 = x + 682;

    field(c1, row1, "ALT", fmt_altitude(ac, settings.units), t.primary);
    field(c2, row1, "GS", fmt_speed(ac, settings.units), t.primary);
    field(c3, row1, "VS", fmt_vertical_rate(ac, settings.units), t.primary);
    field(c4, row1, "DIST", fmt_distance(c->distance_m, settings.units), t.primary);

    field(c1, row2, "TRK", fmt_deg(ac.has_track ? ac.track : ac.true_heading), t.primary);
    field(c2, row2, "IAS", ac.has_ias ? std::to_string(static_cast<int>(std::lround(ac.ias_kt))) + "KT" : "--",
          t.primary);
    field(c3, row2, "TAS", ac.has_tas ? std::to_string(static_cast<int>(std::lround(ac.tas_kt))) + "KT" : "--",
          t.primary);
    field(c4, row2, "MACH", ac.has_mach ? ([] (double m) { char q[16]; std::snprintf(q, sizeof q, "%.2f", m); return std::string(q); })(ac.mach) : "--",
          t.primary);

    field(c1, row3, "BRG", fmt_bearing(c->bearing_deg), t.primary);
    field(c2, row3, "LAT", fmt_coord(c->lat, true), t.primary);
    field(c3, row3, "LON", fmt_coord(c->lon, false), t.primary);
    field(c4, row3, "SEEN", fmt_seen(ac.has_seen_pos ? ac.seen_pos : ac.seen), t.primary);

    std::snprintf(b, sizeof b, "NACp %.0f   NACv %.0f   SIL %.0f   NIC %.0f   RC %.0fM   MSG %d   VER %d",
                  ac.has_nac_p ? ac.nac_p : 0.0, ac.has_nac_v ? ac.nac_v : 0.0,
                  ac.has_sil ? ac.sil : 0.0, ac.has_nic ? ac.nic : 0.0, ac.has_rc ? ac.rc_m : 0.0,
                  ac.messages, ac.version);
    text(0, b, c1, qrow, 15.0, t.faint, 0.95f);

    std::string nav;
    if (ac.has_nav_alt) nav += "NAV ALT " + fmt_commas(static_cast<long long>(std::lround(ac.nav_alt_ft)));
    if (ac.has_nav_qnh) {
      char q[32];
      std::snprintf(q, sizeof q, "%sQNH %.0f", nav.empty() ? "" : "   ", ac.nav_qnh);
      nav += q;
    }
    if (ac.has_nav_heading)
      nav += std::string(nav.empty() ? "" : "   ") + "NAV HDG " + fmt_deg(ac.nav_heading);
    if (ac.has_mag_heading)
      nav += std::string(nav.empty() ? "" : "   ") + "MAG " + fmt_deg(ac.mag_heading);
    if (ac.has_true_heading)
      nav += std::string(nav.empty() ? "" : "   ") + "TRUE " + fmt_deg(ac.true_heading);
    if (!ac.has_alt_geom && !ac.has_geom_rate && !ac.has_baro_rate) nav += "";
    if (ac.has_alt_geom)
      nav += std::string(nav.empty() ? "" : "   ") + "GEOM ALT " + fmt_commas(static_cast<long long>(std::lround(ac.alt_geom_ft)));
    if (nav.empty()) nav = "NO NAVIGATION DATA";
    text(0, fit(0, nav, 15.0, layout.pw - 44), c1, nrow, 15.0, t.dim, 0.9f);

    const std::string flags = flag_text(ac);
    if (!flags.empty()) {
      text(0, fit(0, "! " + flags, 16.0, layout.pw - 44), c1, frow, 16.0, t.alert, 1.0f, 0.5);
    } else {
      const std::string s = "RX " + fmt_seen(ac.has_seen ? ac.seen : ac.seen_pos);
      text(0, s, c1, frow, 15.0, t.faint, 0.9f);
    }
  }

  void build(double now) {
    fills.clear();
    solids.clear();
    blips.clear();
    for (auto& v : texts) v.clear();
    theme = make_theme(settings.theme);
    layout = make_layout(settings);

    build_header(now);
    build_panels();
    build_compass();
    build_blips_and_labels(now);
    build_list();
    build_detail();
    build_footer(now);
  }

  void draw(double now, int width, int height) {
    const double scale = std::min(width / VW, height / VH);
    const double ox = (width - VW * scale) * 0.5;
    const double oy = (height - VH * scale) * 0.5;
    const float sx = static_cast<float>(2.0 * scale / width);
    const float sy = static_cast<float>(-2.0 * scale / height);
    const float tx = static_cast<float>(2.0 * ox / width - 1.0);
    const float ty = static_cast<float>(1.0 - 2.0 * oy / height);
    xform4[0] = sx;
    xform4[1] = sy;
    xform4[2] = tx;
    xform4[3] = ty;

    glViewport(0, 0, width, height);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glDisable(GL_SCISSOR_TEST);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    glClearColor(0.004f, 0.008f, 0.006f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
#ifdef RADAR_CORE
    glBindVertexArray(vao);  // core profile has no default VAO to draw into
#endif

    fullscreen.clear();
    fullscreen_quad();
    glUseProgram(prog[kBackground]);
    glUniform3f(u_bg_color, theme.primary.r * 0.35f, theme.primary.g * 0.35f,
                theme.primary.b * 0.35f);
    glUniform1f(u_bg_time, static_cast<float>(now));
    draw_fullscreen(kBackground, fullscreen, true);

    // Disc quad.
    const double pad = 34.0;
    const double x0 = layout.cx - layout.bezel - pad;
    const double y0 = layout.cy - layout.bezel - pad;
    const double x1 = layout.cx + layout.bezel + pad;
    const double y1 = layout.cy + layout.bezel + pad;
    std::vector<Vertex> disc;
    push_quad(disc, x0, y0, x1, y1, 0, 0, 1, 1, Color{1, 1, 1}, 1.0f);
    glUseProgram(prog[kDisc]);
    glUniform4f(u_xform, sx, sy, tx, ty);
    glUniform2f(u_disc_center, static_cast<float>(layout.cx), static_cast<float>(layout.cy));
    glUniform1f(u_disc_radius, static_cast<float>(layout.r));
    glUniform1f(u_disc_bezel, static_cast<float>(layout.bezel));
    glUniform1f(u_disc_sweep, static_cast<float>(model.sweep_deg()));
    glUniform1f(u_disc_sweep_on, 1.0f);
    glUniform1f(u_disc_time, static_cast<float>(now));
    glUniform1f(u_disc_quality, settings.quality == 0 ? 0.0f : (settings.quality == 2 ? 1.0f : 0.6f));
    glUniform3f(u_disc_color, theme.primary.r, theme.primary.g, theme.primary.b);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    set_attrs();
    glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(disc.size() * sizeof(Vertex)),
                 disc.data(), GL_STREAM_DRAW);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(disc.size()));

    draw_vertices(kBlip, blips, 0, true);

    draw_vertices(kSprite, fills, white_tex, false);

    draw_vertices(kSprite, solids, white_tex, true);

    if (!texts[0].empty() || !texts[1].empty() || !texts[2].empty()) {
      glUseProgram(prog[kText]);
      const int xf = glGetUniformLocation(prog[kText], "u_xform");
      if (xf >= 0) glUniform4f(xf, xform4[0], xform4[1], xform4[2], xform4[3]);
      glUniform1i(u_text_tex, 0);
      glUniform1f(u_text_glow, settings.quality == 0 ? 0.30f : (settings.quality == 2 ? 0.85f : 0.58f));
      glActiveTexture(GL_TEXTURE0);
      glBlendFunc(GL_SRC_ALPHA, GL_ONE);
      for (int i = 0; i < 3; ++i) {
        if (texts[i].empty()) continue;
        glBindTexture(GL_TEXTURE_2D, fonts[i].tex);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        set_attrs();
        glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(texts[i].size() * sizeof(Vertex)),
                     texts[i].data(), GL_STREAM_DRAW);
        glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(texts[i].size()));
      }
    }

    if (settings.crt || settings.dim > 0) {
      fullscreen.clear();
      fullscreen_quad();
      glUseProgram(prog[kOverlay]);
      glUniform2f(u_overlay_res, static_cast<float>(VW), static_cast<float>(VH));
      glUniform1f(u_overlay_time, static_cast<float>(now));
      glUniform1f(u_overlay_crt, settings.crt ? 1.0f : 0.0f);
      glUniform1f(u_overlay_dim, static_cast<float>(settings.dim));
      glBindBuffer(GL_ARRAY_BUFFER, vbo);
      set_attrs();
      glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(fullscreen.size() * sizeof(Vertex)),
                   fullscreen.data(), GL_STREAM_DRAW);
      glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
      glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(fullscreen.size()));
    }
  }

  void to_virtual(double sx, double sy, int width, int height, double* vx, double* vy) const {
    const double scale = std::min(width / VW, height / VH);
    const double ox = (width - VW * scale) * 0.5;
    const double oy = (height - VH * scale) * 0.5;
    *vx = (sx - ox) / scale;
    *vy = (sy - oy) / scale;
  }

  void release_gl() {
    for (Font& f : fonts) f.destroy();
    if (white_tex) glDeleteTextures(1, &white_tex);
    white_tex = 0;
    for (unsigned& p : prog)
      if (p) {
        glDeleteProgram(p);
        p = 0;
      }
    if (vbo) glDeleteBuffers(1, &vbo);
    vbo = 0;
#ifdef RADAR_CORE
    if (vao) glDeleteVertexArrays(1, &vao);
    vao = 0;
#endif
  }
};

// ---- App ------------------------------------------------------------------------------------

App::App() : impl_(new Impl) {}
App::~App() {
  if (impl_) {
    if (impl_->pump) impl_->pump->stop();
  }
}

bool App::init(const Settings& settings, const std::string& media_dir, FeedPump::Fetch fetch,
               std::string* error) {
  Impl& d = *impl_;
  d.settings = settings;
  d.settings.sanitise();
  d.model.set_settings(d.settings);
  d.fetch = std::move(fetch);
  d.media = media_dir;
  while (!d.media.empty() && (d.media.back() == '/' || d.media.back() == '\\')) d.media.pop_back();

  std::string err;
  if (!d.make_programs(&err) || !d.make_buffers(&err)) {
    if (error) *error = err;
    d.release_gl();
    return false;
  }
  const char* names[] = {"small", "mid", "big"};
  for (int i = 0; i < 3; ++i) {
    if (!d.fonts[i].load(d.media + "/fonts/font_" + names[i], &err)) {
      if (error) *error = err;
      d.release_gl();
      return false;
    }
  }
  d.model.set_page_rows(12);
  d.model.reset_clock(0.0);
  if (d.fetch) {
    d.pump.reset(new FeedPump(d.settings, d.fetch));
    d.pump->start();
  }
  return true;
}

void App::set_settings(const Settings& settings) {
  Impl& d = *impl_;
  Settings s = settings;
  s.sanitise();
  const bool refetch = s.lat != d.settings.lat || s.lon != d.settings.lon ||
                       s.range_km != d.settings.range_km ||
                       s.refresh_seconds != d.settings.refresh_seconds;
  d.settings = s;
  d.model.set_settings(s);
  d.model.set_page_rows(12);
  if (refetch && d.fetch) {
    if (d.pump) d.pump->stop();
    d.pump.reset(new FeedPump(d.settings, d.fetch));
    d.pump->start();
  }
}

void App::apply_feed(const Feed& feed, double now) { impl_->model.apply_feed(feed, now); }
void App::apply_error(const std::string& error, double now) { impl_->model.apply_error(error, now); }

void App::render(double now, int width, int height) {
  Impl& d = *impl_;
  if (d.pump) {
    Feed feed;
    std::string err;
    bool is_error = false;
    if (d.pump->take(&feed, &err, &is_error)) {
      if (is_error)
        d.model.apply_error(err, now);
      else
        d.model.apply_feed(feed, now);
    }
  }
  d.model.update(now);
  d.build(now);
  glu::SavedState saved;
  d.draw(now, width, height);
}

void App::release() {
  if (!impl_) return;
  if (impl_->pump) {
    impl_->pump->stop();
    impl_->pump.reset();
  }
  impl_->release_gl();
}

std::string App::pick(double screen_x, double screen_y, int width, int height) const {
  const Impl& d = *impl_;
  double vx = 0, vy = 0;
  d.to_virtual(screen_x, screen_y, width, height, &vx, &vy);
  const Layout& l = d.layout;
  for (int idx : d.model.order()) {
    const Contact& c = d.model.contacts()[static_cast<size_t>(idx)];
    const double x = l.cx + c.x * l.r;
    const double y = l.cy - c.y * l.r;
    const double dx = vx - x, dy = vy - y;
    if (dx * dx + dy * dy <= 26.0 * 26.0) return upper_string(c.ac.hex);
  }
  if (l.panel && vx >= l.px && vx <= l.px + l.pw && vy >= 232 && vy < 232 + d.model.page_rows() * 36) {
    const int row = static_cast<int>((vy - 232) / 36);
    const int pos = d.model.page() * d.model.page_rows() + row;
    if (pos >= 0 && pos < static_cast<int>(d.model.order().size())) {
      const Contact& c =
          d.model.contacts()[static_cast<size_t>(d.model.order()[static_cast<size_t>(pos)])];
      return upper_string(c.ac.hex);
    }
  }
  return std::string();
}

void App::select(const std::string& hex) {
  if (hex.empty())
    impl_->model.unpin();
  else
    impl_->model.pin(hex);
}

void App::step_spotlight(int delta) { impl_->model.step_spotlight(delta); }
void App::set_page(int page) { impl_->model.set_page(page); }
const Model& App::model() const { return impl_->model; }

}  // namespace radar

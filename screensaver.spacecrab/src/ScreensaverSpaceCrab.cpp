// Kodi screensaver: an animated crab (or a few) floating in empty space, OpenGL / OpenGL ES 2.
//
// The crab is a skinned mesh baked by tools/make_crab_model.py: a walk cycle sampled at evenly
// spaced times, one 3x4 skinning matrix per joint per sample. Skinning runs in the vertex
// shader, or on the CPU when the GPU has too few vertex uniforms. Behind it: a starfield (still,
// drifting or rushing past), an optional nebula and a gradient. The camera orbits and can push in
// and out; settings choose the zoom, lens, height, orbit, light and how the crabs move.

#include "CrabModel.h"
#include "stb_image.h"

#include <kodi/addon-instance/Screensaver.h>
#include <kodi/gui/gl/GL.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <memory>
#include <random>
#include <string>
#include <vector>

#if !defined(HAS_GLES) && !defined(GL_PROGRAM_POINT_SIZE)
#define GL_PROGRAM_POINT_SIZE 0x8642
#endif

namespace
{

constexpr float kPi = 3.14159265358979f;

// Kodi uses a GL 3.2 core context on macOS, a GL 2.1 context on Linux and GLES 2 on Android.
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

// ---- the crab
const char* kCrabVS = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec3 a_pos;
attribute vec3 a_nrm;
attribute vec4 a_tan;
attribute vec2 a_uv;
#ifdef SKIN
attribute vec4 a_joint;
attribute vec4 a_weight;
uniform vec4 u_pal[PALETTE];
#endif
uniform mat4 u_model;
uniform mat4 u_viewProj;
varying vec3 v_wpos;
varying vec3 v_n;
varying vec4 v_t;
varying vec2 v_uv;
void main()
{
  vec4 p = vec4(a_pos, 1.0);
  vec3 n = a_nrm;
  vec3 t = a_tan.xyz;
#ifdef SKIN
  int i0 = int(a_joint.x + 0.5) * 3;
  int i1 = int(a_joint.y + 0.5) * 3;
  int i2 = int(a_joint.z + 0.5) * 3;
  int i3 = int(a_joint.w + 0.5) * 3;
  vec4 w = a_weight;
  vec4 r0 = u_pal[i0] * w.x + u_pal[i1] * w.y + u_pal[i2] * w.z + u_pal[i3] * w.w;
  vec4 r1 = u_pal[i0 + 1] * w.x + u_pal[i1 + 1] * w.y + u_pal[i2 + 1] * w.z + u_pal[i3 + 1] * w.w;
  vec4 r2 = u_pal[i0 + 2] * w.x + u_pal[i1 + 2] * w.y + u_pal[i2 + 2] * w.z + u_pal[i3 + 2] * w.w;
  p = vec4(dot(r0, p), dot(r1, p), dot(r2, p), 1.0);
  n = vec3(dot(r0.xyz, n), dot(r1.xyz, n), dot(r2.xyz, n));
  t = vec3(dot(r0.xyz, t), dot(r1.xyz, t), dot(r2.xyz, t));
#endif
  vec4 wp = u_model * p;
  v_wpos = wp.xyz;
  v_n = (u_model * vec4(n, 0.0)).xyz;
  v_t = vec4((u_model * vec4(t, 0.0)).xyz, a_tan.w);
  v_uv = a_uv;
  gl_Position = u_viewProj * wp;
}
)";

const char* kCrabFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_color;
uniform sampler2D u_nmap;
uniform vec3 u_eye;
uniform vec3 u_keyDir;
uniform vec3 u_keyCol;
uniform vec3 u_rimDir;
uniform vec3 u_rimCol;
uniform vec3 u_sky;
uniform vec3 u_ground;
uniform float u_bright;
varying vec3 v_wpos;
varying vec3 v_n;
varying vec4 v_t;
varying vec2 v_uv;
void main()
{
  vec3 N = normalize(v_n);
  if (!gl_FrontFacing)
    N = -N;
#ifdef NMAP
  vec3 T = v_t.xyz - N * dot(N, v_t.xyz);
  float tl = length(T);
  if (tl > 1e-4)
  {
    T /= tl;
    vec3 B = cross(N, T) * (v_t.w < 0.0 ? -1.0 : 1.0);
    vec3 m = texture2D(u_nmap, v_uv).xyz * 2.0 - 1.0;
    N = normalize(T * m.x + B * m.y + N * m.z);
  }
#endif
  vec3 base = texture2D(u_color, v_uv).rgb;
  vec3 lin = base * base;
  vec3 V = normalize(u_eye - v_wpos);
  float diff = max((dot(N, u_keyDir) + 0.15) / 1.15, 0.0);
  vec3 H = normalize(u_keyDir + V);
  float nv = max(dot(N, V), 0.0);
  float fres = 0.04 + 0.5 * pow(1.0 - nv, 5.0);
  float spec = pow(max(dot(N, H), 0.0), 36.0) * (0.25 + fres) * step(0.0, dot(N, u_keyDir));
  float rim = pow(1.0 - nv, 3.0) * max(dot(N, u_rimDir) + 0.35, 0.0);
  vec3 amb = mix(u_ground, u_sky, N.y * 0.5 + 0.5);
  vec3 col = lin * (amb + u_keyCol * diff) + u_keyCol * spec * 0.6 + u_rimCol * rim * (0.35 + lin);
  gl_FragColor = vec4(sqrt(max(col, vec3(0.0))) * u_bright, 1.0);
}
)";

// ---- stars: points on a far sphere (sky), or streaks rushing past (warp)
const char* kStarVS = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec4 a_star;   // sky: unit direction + brightness; warp: disc x, y, depth seed, brightness
attribute float a_tail;  // warp streaks: 0 head, 1 tail
uniform mat4 u_sky;      // projection x view rotation x sky rotation
uniform mat4 u_proj;
uniform float u_warp;    // 0 sky, else warp speed (depth units per second)
uniform float u_time;
uniform float u_psize;
varying float v_a;
varying vec3 v_col;
void main()
{
  float b = a_star.w;
  float h = fract(b * 91.7 + a_star.x * 13.1);
  v_col = mix(vec3(0.75, 0.85, 1.0), vec3(1.0, 0.88, 0.7), h);
  if (u_warp > 0.0)
  {
    float L = 90.0;
    float z = fract(a_star.z - u_time * u_warp / L);
    float depth = 1.5 + z * L + a_tail * (0.6 + 2.6 * u_warp / 30.0) * (1.0 - z * 0.5);
    vec3 p = vec3(a_star.xy * 16.0, -depth);
    gl_Position = u_proj * vec4(p, 1.0);
    v_a = b * smoothstep(1.0, 0.65, z) * (1.0 - 0.7 * a_tail);
    gl_PointSize = u_psize * (0.7 + 2.0 * (1.0 - z));
  }
  else
  {
    gl_Position = u_sky * vec4(a_star.xyz * 50.0, 1.0);
    v_a = b * (0.78 + 0.22 * sin(u_time * (0.7 + 3.0 * h) + b * 40.0));
    gl_PointSize = u_psize * (0.6 + 1.9 * b * b);
  }
}
)";

const char* kStarFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform float u_bright;
uniform float u_points;
varying float v_a;
varying vec3 v_col;
void main()
{
  float a = v_a;
  if (u_points > 0.5)
  {
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    a *= max(1.0 - dot(p, p), 0.0);
  }
  gl_FragColor = vec4(v_col * a * u_bright, 1.0);
}
)";

// ---- nebula: big soft billboards on the sky, broken up by a tiling noise texture
const char* kNebulaVS = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec3 a_centre;
attribute vec4 a_corner;  // corner x, y (-1..1), size, noise seed
attribute vec3 a_col;
uniform mat4 u_view;      // view rotation x sky rotation
uniform mat4 u_proj;
varying vec2 v_c;
varying vec2 v_n;
varying vec3 v_col;
void main()
{
  vec3 c = (u_view * vec4(a_centre, 1.0)).xyz;
  gl_Position = u_proj * vec4(c + vec3(a_corner.xy * a_corner.z, 0.0), 1.0);
  v_c = a_corner.xy;
  v_n = a_corner.xy * 0.45 + vec2(a_corner.w, a_corner.w * 1.7);
  v_col = a_col;
}
)";

const char* kNebulaFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_noise;
uniform float u_bright;
varying vec2 v_c;
varying vec2 v_n;
varying vec3 v_col;
void main()
{
  float r2 = dot(v_c, v_c);
  float g = exp(-r2 * 3.2) - 0.04;
  float n = texture2D(u_noise, v_n).r * texture2D(u_noise, v_n * 2.3 + 0.37).g;
  float a = max(g, 0.0) * (0.15 + 1.6 * n * n);
  gl_FragColor = vec4(v_col * a * u_bright, 1.0);
}
)";

// ---- full-screen vertical gradient
const char* kBackVS = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;
varying float v_y;
void main()
{
  gl_Position = vec4(a_pos, 0.999, 1.0);
  v_y = a_pos.y * 0.5 + 0.5;
}
)";

const char* kBackFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform vec3 u_top;
uniform vec3 u_bottom;
uniform float u_bright;
varying float v_y;
void main()
{
  gl_FragColor = vec4(mix(u_bottom, u_top, v_y) * u_bright, 1.0);
}
)";

// ---- column-major 4x4 matrices
struct Mat4
{
  float m[16] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
};

Mat4 Mul(const Mat4& a, const Mat4& b)
{
  Mat4 r;
  for (int c = 0; c < 4; c++)
    for (int row = 0; row < 4; row++)
    {
      float s = 0;
      for (int k = 0; k < 4; k++)
        s += a.m[k * 4 + row] * b.m[c * 4 + k];
      r.m[c * 4 + row] = s;
    }
  return r;
}

Mat4 Perspective(float fovY, float aspect, float zn, float zf)
{
  Mat4 r;
  const float f = 1.0f / std::tan(fovY * 0.5f);
  std::memset(r.m, 0, sizeof(r.m));
  r.m[0] = f / aspect;
  r.m[5] = f;
  r.m[10] = (zf + zn) / (zn - zf);
  r.m[11] = -1;
  r.m[14] = 2 * zf * zn / (zn - zf);
  return r;
}

struct Vec3
{
  float x = 0, y = 0, z = 0;
};
Vec3 V3(float x, float y, float z) { return Vec3{x, y, z}; }
Vec3 operator+(Vec3 a, Vec3 b) { return V3(a.x + b.x, a.y + b.y, a.z + b.z); }
Vec3 operator-(Vec3 a, Vec3 b) { return V3(a.x - b.x, a.y - b.y, a.z - b.z); }
Vec3 operator*(Vec3 a, float k) { return V3(a.x * k, a.y * k, a.z * k); }
float Dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
Vec3 Cross(Vec3 a, Vec3 b)
{
  return V3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x);
}
Vec3 Norm(Vec3 a)
{
  const float l = std::sqrt(Dot(a, a));
  return l > 1e-8f ? a * (1.0f / l) : V3(0, 1, 0);
}

Mat4 LookAt(Vec3 eye, Vec3 at, Vec3 up)
{
  const Vec3 f = Norm(at - eye);
  const Vec3 s = Norm(Cross(f, up));
  const Vec3 u = Cross(s, f);
  Mat4 r;
  r.m[0] = s.x;
  r.m[4] = s.y;
  r.m[8] = s.z;
  r.m[1] = u.x;
  r.m[5] = u.y;
  r.m[9] = u.z;
  r.m[2] = -f.x;
  r.m[6] = -f.y;
  r.m[10] = -f.z;
  r.m[12] = -Dot(s, eye);
  r.m[13] = -Dot(u, eye);
  r.m[14] = Dot(f, eye);
  return r;
}

Mat4 RotY(float a)
{
  Mat4 r;
  const float c = std::cos(a), s = std::sin(a);
  r.m[0] = c;
  r.m[2] = -s;
  r.m[8] = s;
  r.m[10] = c;
  return r;
}

Mat4 RotX(float a)
{
  Mat4 r;
  const float c = std::cos(a), s = std::sin(a);
  r.m[5] = c;
  r.m[6] = s;
  r.m[9] = -s;
  r.m[10] = c;
  return r;
}

Mat4 RotZ(float a)
{
  Mat4 r;
  const float c = std::cos(a), s = std::sin(a);
  r.m[0] = c;
  r.m[1] = s;
  r.m[4] = -s;
  r.m[5] = c;
  return r;
}

Mat4 RotAxis(Vec3 axis, float a)
{
  axis = Norm(axis);
  const float c = std::cos(a), s = std::sin(a), t = 1 - c;
  const float x = axis.x, y = axis.y, z = axis.z;
  Mat4 r;
  r.m[0] = t * x * x + c;
  r.m[1] = t * x * y + s * z;
  r.m[2] = t * x * z - s * y;
  r.m[4] = t * x * y - s * z;
  r.m[5] = t * y * y + c;
  r.m[6] = t * y * z + s * x;
  r.m[8] = t * x * z + s * y;
  r.m[9] = t * y * z - s * x;
  r.m[10] = t * z * z + c;
  return r;
}

Mat4 TranslateScale(Vec3 p, float s)
{
  Mat4 r;
  r.m[0] = r.m[5] = r.m[10] = s;
  r.m[12] = p.x;
  r.m[13] = p.y;
  r.m[14] = p.z;
  return r;
}

Mat4 RotationOnly(Mat4 m)
{
  m.m[12] = m.m[13] = m.m[14] = 0;
  return m;
}

Vec3 Hue(float h)
{
  h -= std::floor(h);
  auto ch = [h](float o) {
    float k = std::fabs(std::fmod(h * 6.0f + o, 6.0f) - 3.0f) - 1.0f;
    return std::min(1.0f, std::max(0.0f, k));
  };
  return V3(ch(0), ch(4), ch(2));
}

int Clampi(int v, int lo, int hi) { return std::min(hi, std::max(lo, v)); }

enum AnimStyle { ANIM_STEADY, ANIM_SCUTTLE, ANIM_BACK_FORTH };
enum Movement { MOVE_FLOAT, MOVE_WANDER, MOVE_SCUTTLE };
enum Tumble { TUMBLE_SWAY, TUMBLE_TURN, TUMBLE_TUMBLE, TUMBLE_STILL };
enum Background { BACK_BLACK, BACK_BLUE, BACK_NEBULA };
enum StarMotion { STARS_STILL, STARS_DRIFT, STARS_WARP };
enum Light { LIGHT_WARM, LIGHT_COOL, LIGHT_RIM, LIGHT_CYCLE };

struct Settings
{
  int crabs = 1;
  float animSpeed = 1;
  int animStyle = ANIM_SCUTTLE;
  int movement = MOVE_FLOAT;
  int tumble = TUMBLE_SWAY;
  float bob = 1;
  float zoom = 1;
  float autoZoom = 0.3f;
  float orbit = 5;       // degrees per second
  float height = 15;     // degrees
  int lens = 1;
  bool sway = true;
  int background = BACK_NEBULA;
  bool stars = true;
  float starDensity = 1;
  int starMotion = STARS_DRIFT;
  int light = LIGHT_WARM;
  int detail = 1;
  float dim = 0;
};

struct Crab
{
  Vec3 home;           // float / wander: centre; scuttle: (along, up, depth) in camera axes
  float size = 1;
  float phase = 0;     // seconds into the walk cycle
  float rate = 1, target = 1, segment = 0;
  float yaw = 0, spinYaw = 0, spinPitch = 0, spinRoll = 0;
  float facing = 0;    // scuttle: 0 faces the camera, pi faces away
  float ph[8] = {0, 0, 0, 0, 0, 0, 0, 0};
  float freq[3] = {0, 0, 0};
};

// Saves the GL state we touch and restores it, so Kodi's GUI is unaffected.
struct SavedState
{
  GLint program = 0, arrayBuffer = 0, elementBuffer = 0, texture = 0, activeTexture = 0;
  GLint viewport[4] = {0, 0, 0, 0};
  GLint blendSrc = 0, blendDst = 0;
  GLboolean blend, depth, cull, scissor, depthMask = GL_TRUE;
#ifdef TARGET_DARWIN
  GLint vao = 0;
#endif
  SavedState()
  {
    glGetIntegerv(GL_CURRENT_PROGRAM, &program);
    glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &arrayBuffer);
    glGetIntegerv(GL_ELEMENT_ARRAY_BUFFER_BINDING, &elementBuffer);
    glGetIntegerv(GL_ACTIVE_TEXTURE, &activeTexture);
    glActiveTexture(GL_TEXTURE0);
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &texture);
    glGetIntegerv(GL_VIEWPORT, viewport);
    glGetIntegerv(GL_BLEND_SRC_RGB, &blendSrc);
    glGetIntegerv(GL_BLEND_DST_RGB, &blendDst);
    glGetBooleanv(GL_DEPTH_WRITEMASK, &depthMask);
#ifdef TARGET_DARWIN
    glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
#endif
    blend = glIsEnabled(GL_BLEND);
    depth = glIsEnabled(GL_DEPTH_TEST);
    cull = glIsEnabled(GL_CULL_FACE);
    scissor = glIsEnabled(GL_SCISSOR_TEST);
    glDisable(GL_BLEND);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
  }
  ~SavedState()
  {
    glUseProgram(static_cast<GLuint>(program));
#ifdef TARGET_DARWIN
    glBindVertexArray(static_cast<GLuint>(vao));
#endif
    glBindBuffer(GL_ARRAY_BUFFER, static_cast<GLuint>(arrayBuffer));
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, static_cast<GLuint>(elementBuffer));
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, 0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, static_cast<GLuint>(texture));
    glActiveTexture(static_cast<GLenum>(activeTexture));
    glViewport(viewport[0], viewport[1], viewport[2], viewport[3]);
    glBlendFunc(static_cast<GLenum>(blendSrc), static_cast<GLenum>(blendDst));
    glDepthMask(depthMask);
    if (blend) glEnable(GL_BLEND); else glDisable(GL_BLEND);
    if (depth) glEnable(GL_DEPTH_TEST); else glDisable(GL_DEPTH_TEST);
    if (cull) glEnable(GL_CULL_FACE); else glDisable(GL_CULL_FACE);
    if (scissor) glEnable(GL_SCISSOR_TEST); else glDisable(GL_SCISSOR_TEST);
  }
};

struct Program
{
  GLuint id = 0;
  GLint Loc(const char* name) const { return glGetUniformLocation(id, name); }
  GLint Attr(const char* name) const { return glGetAttribLocation(id, name); }
};

} // namespace

class ATTR_DLL_LOCAL CScreensaverSpaceCrab : public kodi::addon::CAddonBase,
                                             public kodi::addon::CInstanceScreensaver
{
public:
  CScreensaverSpaceCrab() = default;

  bool Start() override;
  void Stop() override;
  void Render() override;

private:
  using Clock = std::chrono::steady_clock;

  void LoadSettings();
  GLuint Compile(GLenum type, const std::string& src);
  Program Link(const std::string& defines, const char* vs, const char* fs);
  bool LoadTexture(const std::string& path, GLuint& tex);
  void BuildStars();
  void BuildNebula();
  void BuildNoise();
  void PlaceCrabs();
  void UpdateCrab(Crab& c, float dt);
  float Rand(float lo, float hi) { return std::uniform_real_distribution<float>(lo, hi)(m_rng); }

  void DrawBackground(float bright);
  void DrawSky(const Mat4& proj, const Mat4& viewRot, float bright);
  void DrawCrabs(const Mat4& viewProj, Vec3 eye, Vec3 right, Vec3 up, Vec3 fwd, float bright);

  Settings m_set;
  crab::Model m_model;
  std::mt19937 m_rng;
  std::vector<Crab> m_crabs;
  std::vector<float> m_pose;
  std::vector<float> m_skinned;

  bool m_gpuSkin = true;
  Program m_crabProg, m_starProg, m_nebulaProg, m_backProg;
  GLuint m_vbo = 0, m_ibo = 0, m_skinVbo = 0, m_starVbo = 0, m_nebulaVbo = 0, m_quadVbo = 0;
  GLuint m_colorTex = 0, m_normalTex = 0, m_noiseTex = 0;
  int m_starCount = 0, m_nebulaCount = 0;
#ifdef TARGET_DARWIN
  GLuint m_vao = 0;
#endif

  Clock::time_point m_lastFrame;
  float m_time = 0;
  float m_orbit = 0;
  float m_fitRadius = 1.5f;   // what the camera frames, world units
  float m_scuttleHalfW = 6, m_scuttleHalfH = 3;
  bool m_spread = false;      // scuttle lanes spread over the view width yet
};

void CScreensaverSpaceCrab::LoadSettings()
{
  using kodi::addon::GetSettingBoolean;
  using kodi::addon::GetSettingInt;
  m_set.crabs = Clampi(GetSettingInt("crabs", 1), 1, 12);
  m_set.animSpeed = Clampi(GetSettingInt("anim_speed", 100), 0, 300) / 100.0f;
  m_set.animStyle = Clampi(GetSettingInt("anim_style", 1), 0, 2);
  m_set.movement = Clampi(GetSettingInt("movement", 0), 0, 2);
  m_set.tumble = Clampi(GetSettingInt("tumble", 0), 0, 3);
  m_set.bob = Clampi(GetSettingInt("bob", 100), 0, 200) / 100.0f;
  m_set.zoom = Clampi(GetSettingInt("zoom", 100), 25, 400) / 100.0f;
  m_set.autoZoom = Clampi(GetSettingInt("auto_zoom", 30), 0, 100) / 100.0f;
  m_set.orbit = static_cast<float>(Clampi(GetSettingInt("orbit", 5), -30, 30));
  m_set.height = static_cast<float>(Clampi(GetSettingInt("height", 15), -80, 80));
  m_set.lens = Clampi(GetSettingInt("lens", 1), 0, 2);
  m_set.sway = GetSettingBoolean("sway", true);
  m_set.background = Clampi(GetSettingInt("background", 2), 0, 2);
  m_set.stars = GetSettingBoolean("stars", true);
  m_set.starDensity = Clampi(GetSettingInt("star_density", 100), 10, 300) / 100.0f;
  m_set.starMotion = Clampi(GetSettingInt("star_motion", 1), 0, 2);
  m_set.light = Clampi(GetSettingInt("light", 0), 0, 3);
  m_set.detail = Clampi(GetSettingInt("detail", 1), 0, 1);
  m_set.dim = Clampi(GetSettingInt("dim", 0), 0, 80) / 100.0f;
}

GLuint CScreensaverSpaceCrab::Compile(GLenum type, const std::string& src)
{
  GLuint s = glCreateShader(type);
  const char* p = src.c_str();
  glShaderSource(s, 1, &p, nullptr);
  glCompileShader(s);
  GLint ok = 0;
  glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
  if (!ok)
  {
    char log[1024] = {0};
    glGetShaderInfoLog(s, sizeof(log), nullptr, log);
    kodi::Log(ADDON_LOG_ERROR, "Space Crab: shader compile failed: %s", log);
    glDeleteShader(s);
    return 0;
  }
  return s;
}

Program CScreensaverSpaceCrab::Link(const std::string& defines, const char* vs, const char* fs)
{
  Program p;
  GLuint v = Compile(GL_VERTEX_SHADER, kVertexHeader + defines + vs);
  GLuint f = Compile(GL_FRAGMENT_SHADER, kFragmentHeader + defines + fs);
  if (!v || !f)
  {
    if (v) glDeleteShader(v);
    if (f) glDeleteShader(f);
    return p;
  }
  p.id = glCreateProgram();
  glAttachShader(p.id, v);
  glAttachShader(p.id, f);
  // Attribute 0 must be in use on desktop GL; bind each program's position there.
  glBindAttribLocation(p.id, 0, "a_pos");
  glBindAttribLocation(p.id, 0, "a_star");
  glBindAttribLocation(p.id, 0, "a_centre");
  glLinkProgram(p.id);
  glDeleteShader(v);
  glDeleteShader(f);
  GLint ok = 0;
  glGetProgramiv(p.id, GL_LINK_STATUS, &ok);
  if (!ok)
  {
    char log[1024] = {0};
    glGetProgramInfoLog(p.id, sizeof(log), nullptr, log);
    kodi::Log(ADDON_LOG_ERROR, "Space Crab: program link failed: %s", log);
    glDeleteProgram(p.id);
    p.id = 0;
  }
  return p;
}

bool CScreensaverSpaceCrab::LoadTexture(const std::string& path, GLuint& tex)
{
  std::ifstream f(path, std::ios::binary);
  std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(f)),
                                   std::istreambuf_iterator<char>());
  int w = 0, h = 0, n = 0;
  unsigned char* px =
      bytes.empty() ? nullptr
                    : stbi_load_from_memory(bytes.data(), static_cast<int>(bytes.size()), &w, &h,
                                            &n, 3);
  if (!px)
  {
    kodi::Log(ADDON_LOG_ERROR, "Space Crab: cannot load %s", path.c_str());
    return false;
  }
  // Low detail halves the textures (2048 -> 1024): a quarter of the memory on weak boxes.
  if (m_set.detail == 0 && w >= 1024 && h >= 1024)
  {
    const int hw = w / 2, hh = h / 2;
    for (int y = 0; y < hh; y++)
      for (int x = 0; x < hw; x++)
        for (int c = 0; c < 3; c++)
        {
          const int a = px[((2 * y) * w + 2 * x) * 3 + c], b = px[((2 * y) * w + 2 * x + 1) * 3 + c];
          const int d = px[((2 * y + 1) * w + 2 * x) * 3 + c];
          const int e = px[((2 * y + 1) * w + 2 * x + 1) * 3 + c];
          px[(y * hw + x) * 3 + c] = static_cast<unsigned char>((a + b + d + e + 2) / 4);
        }
    w = hw;
    h = hh;
  }
  glGenTextures(1, &tex);
  glBindTexture(GL_TEXTURE_2D, tex);
  glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, w, h, 0, GL_RGB, GL_UNSIGNED_BYTE, px);
  glGenerateMipmap(GL_TEXTURE_2D);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
  stbi_image_free(px);
  return true;
}

void CScreensaverSpaceCrab::BuildNoise()
{
  // Tiling value-noise fBm, two independent channels (r, g).
  const int n = 128;
  std::vector<uint8_t> img(n * n * 4, 255);
  for (int ch = 0; ch < 2; ch++)
  {
    std::vector<float> acc(n * n, 0.0f);
    float amp = 1, total = 0;
    for (int cells = 4; cells <= 32; cells *= 2)
    {
      std::vector<float> lattice(cells * cells);
      for (float& v : lattice)
        v = Rand(0, 1);
      for (int y = 0; y < n; y++)
        for (int x = 0; x < n; x++)
        {
          const float fx = x * cells / static_cast<float>(n), fy = y * cells / static_cast<float>(n);
          const int x0 = static_cast<int>(fx), y0 = static_cast<int>(fy);
          float tx = fx - x0, ty = fy - y0;
          tx = tx * tx * (3 - 2 * tx);
          ty = ty * ty * (3 - 2 * ty);
          auto L = [&](int i, int j) { return lattice[(j % cells) * cells + (i % cells)]; };
          const float a = L(x0, y0) + (L(x0 + 1, y0) - L(x0, y0)) * tx;
          const float b = L(x0, y0 + 1) + (L(x0 + 1, y0 + 1) - L(x0, y0 + 1)) * tx;
          acc[y * n + x] += amp * (a + (b - a) * ty);
        }
      total += amp;
      amp *= 0.55f;
    }
    for (int i = 0; i < n * n; i++)
    {
      float v = acc[i] / total;
      v = std::min(1.0f, std::max(0.0f, (v - 0.3f) * 2.5f));
      img[i * 4 + ch] = static_cast<uint8_t>(v * 255);
    }
  }
  glGenTextures(1, &m_noiseTex);
  glBindTexture(GL_TEXTURE_2D, m_noiseTex);
  glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, n, n, 0, GL_RGBA, GL_UNSIGNED_BYTE, img.data());
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
}

void CScreensaverSpaceCrab::BuildStars()
{
  const bool warp = m_set.starMotion == STARS_WARP;
  const int base = m_set.detail == 0 ? 1200 : 2600;
  m_starCount = std::max(50, static_cast<int>(base * m_set.starDensity * (warp ? 0.6f : 1.0f)));
  // Two vertices per star (head, tail): sky stars draw only the heads, as points.
  std::vector<float> v;
  v.reserve(m_starCount * 10);
  for (int i = 0; i < m_starCount; i++)
  {
    float b = Rand(0, 1);
    b = 0.35f + 0.65f * b * b * b;
    float s[4];
    if (warp)
    {
      // A disc around the line of sight, with a hole so nothing streaks through the middle.
      const float r = std::sqrt(Rand(0.02f, 1.0f)), a = Rand(0, 2 * kPi);
      s[0] = r * std::cos(a);
      s[1] = r * std::sin(a);
      s[2] = Rand(0, 1);
    }
    else
    {
      const float z = Rand(-1, 1), a = Rand(0, 2 * kPi), r = std::sqrt(1 - z * z);
      s[0] = r * std::cos(a);
      s[1] = z;
      s[2] = r * std::sin(a);
    }
    s[3] = b;
    for (int t = 0; t < 2; t++)
    {
      v.insert(v.end(), s, s + 4);
      v.push_back(static_cast<float>(t));
    }
  }
  glGenBuffers(1, &m_starVbo);
  glBindBuffer(GL_ARRAY_BUFFER, m_starVbo);
  glBufferData(GL_ARRAY_BUFFER, v.size() * sizeof(float), v.data(), GL_STATIC_DRAW);
}

void CScreensaverSpaceCrab::BuildNebula()
{
  // A few clouds in two or three colour families, scattered over the sky. Each is a quad drawn
  // as two triangles (six vertices of centre, corner/size/seed, colour).
  static const Vec3 kFamilies[][2] = {
      {{0.55f, 0.20f, 0.65f}, {0.20f, 0.35f, 0.75f}},   // violet / blue
      {{0.15f, 0.50f, 0.60f}, {0.25f, 0.25f, 0.70f}},   // teal / indigo
      {{0.75f, 0.30f, 0.35f}, {0.45f, 0.18f, 0.55f}},   // rose / purple
      {{0.70f, 0.45f, 0.20f}, {0.30f, 0.20f, 0.50f}},   // amber / plum
  };
  const int fam = static_cast<int>(Rand(0, 3.999f));
  m_nebulaCount = m_set.detail == 0 ? 7 : 11;
  std::vector<float> v;
  // Cluster the clouds around two or so regions so the sky has a band rather than polka dots.
  Vec3 band = Norm(V3(Rand(-1, 1), Rand(-0.3f, 0.3f), Rand(-1, 1)));
  Vec3 band2 = Norm(V3(-band.x + Rand(-0.5f, 0.5f), Rand(-0.4f, 0.4f), -band.z + Rand(-0.5f, 0.5f)));
  for (int i = 0; i < m_nebulaCount; i++)
  {
    const Vec3 around = (i % 3 == 2) ? band2 : band;
    const Vec3 d = Norm(around + V3(Rand(-0.6f, 0.6f), Rand(-0.35f, 0.35f), Rand(-0.6f, 0.6f)));
    const Vec3 c = d * 45.0f;
    const float size = Rand(18, 38);
    const float seed = Rand(0, 1);
    const float k = Rand(0, 1);
    Vec3 col = kFamilies[fam][0] * (1 - k) + kFamilies[fam][1] * k;
    col = col * Rand(0.6f, 1.0f);
    const float corners[6][2] = {{-1, -1}, {1, -1}, {1, 1}, {-1, -1}, {1, 1}, {-1, 1}};
    for (const auto& cr : corners)
    {
      const float vert[10] = {c.x, c.y, c.z, cr[0], cr[1], size, seed, col.x, col.y, col.z};
      v.insert(v.end(), vert, vert + 10);
    }
  }
  glGenBuffers(1, &m_nebulaVbo);
  glBindBuffer(GL_ARRAY_BUFFER, m_nebulaVbo);
  glBufferData(GL_ARRAY_BUFFER, v.size() * sizeof(float), v.data(), GL_STATIC_DRAW);
}

void CScreensaverSpaceCrab::PlaceCrabs()
{
  const int n = m_set.crabs;
  m_crabs.assign(n, Crab());
  const float cloud = n == 1 ? 0.0f : 1.25f * std::cbrt(static_cast<float>(n)) + 0.5f;
  for (int i = 0; i < n; i++)
  {
    Crab& c = m_crabs[i];
    c.size = n == 1 ? 1.0f : Rand(0.75f, 1.1f);
    // Keep crabs apart: rejection-sample a point in the cloud.
    for (int tries = 0; tries < 60; tries++)
    {
      const Vec3 p = V3(Rand(-1, 1), Rand(-0.6f, 0.6f), Rand(-1, 1)) * cloud;
      bool ok = true;
      for (int j = 0; j < i; j++)
      {
        const Vec3 d = p - m_crabs[j].home;
        if (Dot(d, d) < 2.2f * 2.2f)
          ok = false;
      }
      c.home = p;
      if (ok)
        break;
    }
    c.phase = Rand(0, m_model.Duration());
    c.yaw = Rand(0, 2 * kPi);
    const float sgn = Rand(0, 1) < 0.5f ? -1.0f : 1.0f;
    c.spinYaw = sgn * Rand(0.12f, 0.3f);
    c.spinPitch = Rand(0.15f, 0.35f) * (Rand(0, 1) < 0.5f ? -1 : 1);
    c.spinRoll = Rand(0.08f, 0.25f) * (Rand(0, 1) < 0.5f ? -1 : 1);
    c.facing = Rand(0, 1) < 0.7f ? 0.0f : kPi;
    for (float& p : c.ph)
      p = Rand(0, 2 * kPi);
    for (float& f : c.freq)
      f = Rand(0.05f, 0.11f);
  }
  float reach = cloud + 1.0f + 0.12f * m_set.bob;
  if (m_set.movement == MOVE_WANDER)
    reach += 1.2f;
  m_fitRadius = std::max(0.85f, reach * 0.8f);

  if (m_set.movement == MOVE_SCUTTLE)
  {
    // Lanes across the view: along (x) is placed on the first frame, once the view's width is known.
    for (int i = 0; i < n; i++)
    {
      Crab& c = m_crabs[i];
      const float lane = n == 1 ? 0.0f : (i + 0.5f) / n * 2 - 1;
      c.home = V3(Rand(-1, 1), lane * 0.7f + Rand(-0.1f, 0.1f), Rand(-1, 1) * std::min(3.0f, cloud));
    }
    m_fitRadius = 1.6f + 0.35f * std::sqrt(static_cast<float>(n - 1));
  }
}

void CScreensaverSpaceCrab::UpdateCrab(Crab& c, float dt)
{
  // Playback rate: steady, or a walk that speeds up, rests and reverses now and then.
  if (m_set.animStyle == ANIM_STEADY)
    c.target = 1;
  else
  {
    c.segment -= dt;
    if (c.segment <= 0)
    {
      const float r = Rand(0, 1);
      if (m_set.animStyle == ANIM_SCUTTLE)
      {
        if (r < 0.45f) c.target = 1.0f;
        else if (r < 0.62f) c.target = 1.7f;
        else if (r < 0.78f) c.target = 0.35f;
        else if (r < 0.94f) c.target = 0.0f;
        else c.target = -0.8f;
        c.segment = Rand(1.5f, 6.0f);
      }
      else
      {
        c.target = c.target > 0 ? -1.0f : 1.0f;
        c.segment = Rand(2.5f, 6.0f);
      }
    }
  }
  c.rate += (c.target - c.rate) * std::min(1.0f, dt / 0.6f);
  const float play = c.rate * m_set.animSpeed;
  c.phase += dt * play;

  if (m_set.movement == MOVE_SCUTTLE)
  {
    // One loop of the cycle carries the crab kWalkPerLoop towards its own -x. Facing the camera,
    // its -x is the screen's left.
    const float speed = crab::kWalkPerLoop / m_model.Duration() * play * c.size;
    const float dir = c.facing == 0 ? -1.0f : 1.0f;
    c.home.x += dir * speed * dt;
    const float limit = m_scuttleHalfW + 1.6f;
    if (c.home.x < -limit)
      c.home.x += 2 * limit;
    else if (c.home.x > limit)
      c.home.x -= 2 * limit;
  }
}

bool CScreensaverSpaceCrab::Start()
{
  LoadSettings();
  m_rng.seed(static_cast<uint32_t>(Clock::now().time_since_epoch().count()));

  std::string error;
  if (!m_model.Load(kodi::addon::GetAddonPath("resources/model/crab.bin"), &error))
  {
    kodi::Log(ADDON_LOG_ERROR, "Space Crab: %s", error.c_str());
    return false;
  }

  // GPU skinning needs 3 vec4 uniforms per joint plus the two matrices.
  GLint maxVec = 0;
#if defined(HAS_GLES)
  glGetIntegerv(GL_MAX_VERTEX_UNIFORM_VECTORS, &maxVec);
#else
  glGetIntegerv(GL_MAX_VERTEX_UNIFORM_COMPONENTS, &maxVec);
  maxVec /= 4;
#endif
  const int need = m_model.Joints() * 3 + 16;
  m_gpuSkin = maxVec >= need;
  kodi::Log(ADDON_LOG_INFO, "Space Crab: %d vertex uniform vectors, %d needed: %s skinning", maxVec,
            need, m_gpuSkin ? "GPU" : "CPU");
  if (!m_gpuSkin)
    m_set.crabs = std::min(m_set.crabs, 3);

  std::string crabDefs;
  if (m_gpuSkin)
    crabDefs += "#define SKIN\n#define PALETTE " + std::to_string(m_model.Joints() * 3) + "\n";
  if (m_set.detail > 0)
    crabDefs += "#define NMAP\n";
  m_crabProg = Link(crabDefs, kCrabVS, kCrabFS);
  m_starProg = Link("", kStarVS, kStarFS);
  m_nebulaProg = Link("", kNebulaVS, kNebulaFS);
  m_backProg = Link("", kBackVS, kBackFS);
  if (!m_crabProg.id || !m_starProg.id || !m_nebulaProg.id || !m_backProg.id)
    return false;

#ifdef TARGET_DARWIN
  glGenVertexArrays(1, &m_vao);
  glBindVertexArray(m_vao);
#endif
  const auto& verts = m_model.Vertices();
  const auto& idx = m_model.Indices();
  glGenBuffers(1, &m_vbo);
  glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
  glBufferData(GL_ARRAY_BUFFER, verts.size() * sizeof(crab::Vertex), verts.data(), GL_STATIC_DRAW);
  glGenBuffers(1, &m_ibo);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, m_ibo);
  glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.size() * 2, idx.data(), GL_STATIC_DRAW);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
  if (!m_gpuSkin)
  {
    glGenBuffers(1, &m_skinVbo);
    glBindBuffer(GL_ARRAY_BUFFER, m_skinVbo);
    glBufferData(GL_ARRAY_BUFFER, verts.size() * 10 * sizeof(float), nullptr, GL_STREAM_DRAW);
  }
  const float quad[] = {-1, -1, 1, -1, -1, 1, 1, 1};
  glGenBuffers(1, &m_quadVbo);
  glBindBuffer(GL_ARRAY_BUFFER, m_quadVbo);
  glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);

  glActiveTexture(GL_TEXTURE0);
  const bool texOk =
      LoadTexture(kodi::addon::GetAddonPath("resources/model/crab_color.jpg"), m_colorTex);
  if (m_set.detail > 0)
    LoadTexture(kodi::addon::GetAddonPath("resources/model/crab_normal.jpg"), m_normalTex);
  BuildNoise();
  if (m_set.stars)
    BuildStars();
  if (m_set.background == BACK_NEBULA)
    BuildNebula();
  glBindTexture(GL_TEXTURE_2D, 0);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif
  if (!texOk)
    return false;

  PlaceCrabs();
  m_spread = false;
  m_orbit = Rand(0, 2 * kPi);
  m_time = 0;
  m_lastFrame = Clock::now();
  return true;
}

void CScreensaverSpaceCrab::Stop()
{
  GLuint buffers[] = {m_vbo, m_ibo, m_skinVbo, m_starVbo, m_nebulaVbo, m_quadVbo};
  for (GLuint b : buffers)
    if (b)
      glDeleteBuffers(1, &b);
  m_vbo = m_ibo = m_skinVbo = m_starVbo = m_nebulaVbo = m_quadVbo = 0;
  GLuint textures[] = {m_colorTex, m_normalTex, m_noiseTex};
  for (GLuint t : textures)
    if (t)
      glDeleteTextures(1, &t);
  m_colorTex = m_normalTex = m_noiseTex = 0;
  for (Program* p : {&m_crabProg, &m_starProg, &m_nebulaProg, &m_backProg})
    if (p->id)
    {
      glDeleteProgram(p->id);
      p->id = 0;
    }
#ifdef TARGET_DARWIN
  if (m_vao)
  {
    glDeleteVertexArrays(1, &m_vao);
    m_vao = 0;
  }
#endif
}

void CScreensaverSpaceCrab::DrawBackground(float bright)
{
  Vec3 top, bottom;
  if (m_set.background == BACK_BLACK)
    return;
  top = V3(0.015f, 0.022f, 0.07f);
  bottom = V3(0.0f, 0.0f, 0.012f);
  if (m_set.background == BACK_NEBULA)
  {
    top = V3(0.012f, 0.01f, 0.04f);
    bottom = V3(0.0f, 0.004f, 0.01f);
  }
  glUseProgram(m_backProg.id);
  glUniform3f(m_backProg.Loc("u_top"), top.x, top.y, top.z);
  glUniform3f(m_backProg.Loc("u_bottom"), bottom.x, bottom.y, bottom.z);
  glUniform1f(m_backProg.Loc("u_bright"), bright);
  glBindBuffer(GL_ARRAY_BUFFER, m_quadVbo);
  glEnableVertexAttribArray(0);
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, nullptr);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
  glDisableVertexAttribArray(0);
}

void CScreensaverSpaceCrab::DrawSky(const Mat4& proj, const Mat4& viewRot, float bright)
{
  // The sky turns slowly about a tilted axis when the stars drift.
  const float skyAngle = m_set.starMotion == STARS_DRIFT ? m_time * 0.012f : 0.0f;
  const Mat4 skyRot = RotAxis(V3(0.25f, 1.0f, 0.1f), skyAngle);
  const Mat4 view = Mul(viewRot, skyRot);

  glEnable(GL_BLEND);
  glBlendFunc(GL_ONE, GL_ONE);

  if (m_nebulaVbo)
  {
    glUseProgram(m_nebulaProg.id);
    glUniformMatrix4fv(m_nebulaProg.Loc("u_view"), 1, GL_FALSE, view.m);
    glUniformMatrix4fv(m_nebulaProg.Loc("u_proj"), 1, GL_FALSE, proj.m);
    glUniform1f(m_nebulaProg.Loc("u_bright"), bright);
    glUniform1i(m_nebulaProg.Loc("u_noise"), 0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, m_noiseTex);
    glBindBuffer(GL_ARRAY_BUFFER, m_nebulaVbo);
    const GLint c = 0, k = m_nebulaProg.Attr("a_corner"), col = m_nebulaProg.Attr("a_col");
    const GLsizei stride = 10 * sizeof(float);
    glEnableVertexAttribArray(c);
    glVertexAttribPointer(c, 3, GL_FLOAT, GL_FALSE, stride, nullptr);
    glEnableVertexAttribArray(k);
    glVertexAttribPointer(k, 4, GL_FLOAT, GL_FALSE, stride, reinterpret_cast<void*>(3 * sizeof(float)));
    glEnableVertexAttribArray(col);
    glVertexAttribPointer(col, 3, GL_FLOAT, GL_FALSE, stride, reinterpret_cast<void*>(7 * sizeof(float)));
    glDrawArrays(GL_TRIANGLES, 0, m_nebulaCount * 6);
    glDisableVertexAttribArray(c);
    glDisableVertexAttribArray(k);
    glDisableVertexAttribArray(col);
  }

  if (m_starVbo)
  {
    const bool warp = m_set.starMotion == STARS_WARP;
    glUseProgram(m_starProg.id);
    const Mat4 sky = Mul(proj, view);
    glUniformMatrix4fv(m_starProg.Loc("u_sky"), 1, GL_FALSE, sky.m);
    glUniformMatrix4fv(m_starProg.Loc("u_proj"), 1, GL_FALSE, proj.m);
    glUniform1f(m_starProg.Loc("u_warp"), warp ? 9.0f : 0.0f);
    glUniform1f(m_starProg.Loc("u_time"), m_time);
    glUniform1f(m_starProg.Loc("u_psize"), std::max(1.0f, Height() / 1080.0f) * 2.0f);
    glUniform1f(m_starProg.Loc("u_bright"), bright);
#if !defined(HAS_GLES)
    glEnable(GL_PROGRAM_POINT_SIZE);
#endif
    glBindBuffer(GL_ARRAY_BUFFER, m_starVbo);
    const GLint s = 0, t = m_starProg.Attr("a_tail");
    const GLsizei stride = 5 * sizeof(float);
    glEnableVertexAttribArray(s);
    if (t >= 0)
      glEnableVertexAttribArray(t);
    // Points: every head (stride of two vertices). Warp also draws each head-tail pair as a line.
    glVertexAttribPointer(s, 4, GL_FLOAT, GL_FALSE, stride * 2, nullptr);
    if (t >= 0)
      glVertexAttribPointer(t, 1, GL_FLOAT, GL_FALSE, stride * 2, reinterpret_cast<void*>(4 * sizeof(float)));
    glUniform1f(m_starProg.Loc("u_points"), 1.0f);
    glDrawArrays(GL_POINTS, 0, m_starCount);
    if (warp)
    {
      glVertexAttribPointer(s, 4, GL_FLOAT, GL_FALSE, stride, nullptr);
      if (t >= 0)
        glVertexAttribPointer(t, 1, GL_FLOAT, GL_FALSE, stride, reinterpret_cast<void*>(4 * sizeof(float)));
      glUniform1f(m_starProg.Loc("u_points"), 0.0f);
      glDrawArrays(GL_LINES, 0, m_starCount * 2);
    }
    glDisableVertexAttribArray(s);
    if (t >= 0)
      glDisableVertexAttribArray(t);
#if !defined(HAS_GLES)
    glDisable(GL_PROGRAM_POINT_SIZE);
#endif
  }
  glDisable(GL_BLEND);
}

void CScreensaverSpaceCrab::DrawCrabs(const Mat4& viewProj, Vec3 eye, Vec3 right, Vec3 up,
                                      Vec3 fwd, float bright)
{
  const Program& p = m_crabProg;
  glUseProgram(p.id);
  glUniformMatrix4fv(p.Loc("u_viewProj"), 1, GL_FALSE, viewProj.m);
  glUniform3f(p.Loc("u_eye"), eye.x, eye.y, eye.z);
  glUniform1f(p.Loc("u_bright"), bright);
  glUniform1i(p.Loc("u_color"), 0);
  glUniform1i(p.Loc("u_nmap"), 1);

  // Lights are fixed to the camera, so the crab is never left in the dark as the view orbits:
  // the key from the upper left and in front, the rim from behind.
  Vec3 key = Norm(right * -0.55f + up * 0.6f + fwd * -0.55f);
  Vec3 rim = Norm(right * 0.6f + up * 0.35f + fwd * 0.75f);
  Vec3 keyCol, rimCol, sky, ground;
  switch (m_set.light)
  {
    case LIGHT_COOL:
      keyCol = V3(0.80f, 0.90f, 1.05f) * 1.15f;
      rimCol = V3(0.55f, 0.75f, 1.0f) * 0.9f;
      sky = V3(0.10f, 0.13f, 0.22f);
      ground = V3(0.03f, 0.03f, 0.06f);
      break;
    case LIGHT_RIM:
      key = Norm(right * -0.9f + up * 0.25f + fwd * -0.15f);
      keyCol = V3(1.0f, 0.75f, 0.55f) * 0.7f;
      rimCol = V3(0.35f, 0.75f, 1.0f) * 1.8f;
      sky = V3(0.035f, 0.04f, 0.06f);
      ground = V3(0.01f, 0.01f, 0.015f);
      break;
    case LIGHT_CYCLE:
    {
      const Vec3 h = Hue(m_time * 0.02f);
      keyCol = (h * 0.6f + V3(0.55f, 0.55f, 0.55f)) * 1.1f;
      rimCol = (Hue(m_time * 0.02f + 0.5f) * 0.9f + V3(0.1f, 0.1f, 0.1f)) * 1.4f;
      sky = h * 0.08f + V3(0.06f, 0.06f, 0.08f);
      ground = V3(0.02f, 0.02f, 0.03f);
      break;
    }
    default:
      keyCol = V3(1.05f, 0.95f, 0.82f) * 1.2f;
      rimCol = V3(0.45f, 0.55f, 0.9f) * 0.75f;
      sky = V3(0.14f, 0.15f, 0.22f);
      ground = V3(0.06f, 0.045f, 0.035f);
      break;
  }
  glUniform3f(p.Loc("u_keyDir"), key.x, key.y, key.z);
  glUniform3f(p.Loc("u_keyCol"), keyCol.x, keyCol.y, keyCol.z);
  glUniform3f(p.Loc("u_rimDir"), rim.x, rim.y, rim.z);
  glUniform3f(p.Loc("u_rimCol"), rimCol.x, rimCol.y, rimCol.z);
  glUniform3f(p.Loc("u_sky"), sky.x, sky.y, sky.z);
  glUniform3f(p.Loc("u_ground"), ground.x, ground.y, ground.z);

  glActiveTexture(GL_TEXTURE1);
  glBindTexture(GL_TEXTURE_2D, m_normalTex ? m_normalTex : m_colorTex);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, m_colorTex);

  const GLint aPos = 0, aNrm = p.Attr("a_nrm"), aTan = p.Attr("a_tan"), aUv = p.Attr("a_uv");
  const GLint aJoint = p.Attr("a_joint"), aWeight = p.Attr("a_weight");
  const GLsizei vs = sizeof(crab::Vertex);
  auto off = [](size_t o) { return reinterpret_cast<void*>(o); };
  std::vector<GLint> enabled;
  auto enable = [&](GLint a) {
    if (a >= 0)
    {
      glEnableVertexAttribArray(a);
      enabled.push_back(a);
    }
  };
  enable(aPos);
  enable(aNrm);
  enable(aTan);
  enable(aUv);
  glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
  if (aUv >= 0)
    glVertexAttribPointer(aUv, 2, GL_UNSIGNED_SHORT, GL_TRUE, vs, off(20));
  if (m_gpuSkin)
  {
    enable(aJoint);
    enable(aWeight);
    glVertexAttribPointer(aPos, 3, GL_FLOAT, GL_FALSE, vs, off(0));
    if (aNrm >= 0)
      glVertexAttribPointer(aNrm, 3, GL_BYTE, GL_TRUE, vs, off(12));
    if (aTan >= 0)
      glVertexAttribPointer(aTan, 4, GL_BYTE, GL_TRUE, vs, off(16));
    if (aJoint >= 0)
      glVertexAttribPointer(aJoint, 4, GL_UNSIGNED_BYTE, GL_FALSE, vs, off(24));
    if (aWeight >= 0)
      glVertexAttribPointer(aWeight, 4, GL_UNSIGNED_BYTE, GL_TRUE, vs, off(28));
  }
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, m_ibo);

  const GLint locModel = p.Loc("u_model"), locPal = p.Loc("u_pal");
  const float dur = m_model.Duration();
  for (const Crab& c : m_crabs)
  {
    // Orientation.
    const float t = m_time;
    Mat4 rot;
    float yaw = c.yaw, pitch = 0, roll = 0;
    if (m_set.movement == MOVE_SCUTTLE)
      yaw = m_orbit + c.facing;
    switch (m_set.tumble)
    {
      case TUMBLE_SWAY:
        yaw += 0.35f * std::sin(t * 0.13f + c.ph[0]);
        pitch = 0.16f * std::sin(t * 0.21f + c.ph[1]);
        roll = 0.2f * std::sin(t * 0.17f + c.ph[2]);
        break;
      case TUMBLE_TURN:
        if (m_set.movement != MOVE_SCUTTLE)
          yaw += c.spinYaw * t;
        else
          yaw += 0.3f * std::sin(t * 0.13f + c.ph[0]);
        pitch = 0.1f * std::sin(t * 0.21f + c.ph[1]);
        roll = 0.12f * std::sin(t * 0.17f + c.ph[2]);
        break;
      case TUMBLE_TUMBLE:
        yaw += c.spinYaw * t;
        pitch = c.spinPitch * t;
        roll = c.spinRoll * t;
        break;
      default:
        if (m_set.movement != MOVE_SCUTTLE)
          yaw = m_orbit + 0.45f;  // a three-quarter view towards the camera
        break;
    }
    rot = Mul(RotY(yaw), Mul(RotX(pitch), RotZ(roll)));

    // Position.
    const float bob = m_set.bob;
    Vec3 pos;
    if (m_set.movement == MOVE_SCUTTLE)
    {
      const Vec3 camRight = V3(std::cos(m_orbit), 0, -std::sin(m_orbit));
      const Vec3 camBack = V3(std::sin(m_orbit), 0, std::cos(m_orbit));
      pos = camRight * c.home.x + V3(0, c.home.y * m_scuttleHalfH, 0) + camBack * c.home.z;
    }
    else
    {
      pos = c.home;
      if (m_set.movement == MOVE_WANDER)
        pos = pos + V3(1.3f * std::sin(t * c.freq[0] + c.ph[3]), 0.7f * std::sin(t * c.freq[1] + c.ph[4]),
                       1.1f * std::sin(t * c.freq[2] + c.ph[5]));
    }
    pos = pos + V3(0.04f * bob * std::sin(t * 0.37f + c.ph[6]), 0.12f * bob * std::sin(t * 0.6f + c.ph[7]),
                   0.04f * bob * std::sin(t * 0.29f + c.ph[5]));

    Mat4 model = Mul(TranslateScale(pos, c.size), rot);
    glUniformMatrix4fv(locModel, 1, GL_FALSE, model.m);

    m_model.Pose(std::fmod(c.phase, dur), m_pose);
    if (m_gpuSkin)
    {
      glUniform4fv(locPal, m_model.Joints() * 3, m_pose.data());
    }
    else
    {
      m_model.Skin(m_pose, m_skinned);
      glBindBuffer(GL_ARRAY_BUFFER, m_skinVbo);
      glBufferData(GL_ARRAY_BUFFER, m_skinned.size() * sizeof(float), m_skinned.data(), GL_STREAM_DRAW);
      const GLsizei st = 10 * sizeof(float);
      glVertexAttribPointer(aPos, 3, GL_FLOAT, GL_FALSE, st, off(0));
      if (aNrm >= 0)
        glVertexAttribPointer(aNrm, 3, GL_FLOAT, GL_FALSE, st, off(12));
      if (aTan >= 0)
        glVertexAttribPointer(aTan, 4, GL_FLOAT, GL_FALSE, st, off(24));
    }
    glDrawElements(GL_TRIANGLES, static_cast<GLsizei>(m_model.Indices().size()), GL_UNSIGNED_SHORT,
                   nullptr);
  }
  for (GLint a : enabled)
    glDisableVertexAttribArray(a);
}

void CScreensaverSpaceCrab::Render()
{
  if (!m_crabProg.id)
    return;
  SavedState saved;

  const auto now = Clock::now();
  const float dt = std::min(0.1f, std::chrono::duration<float>(now - m_lastFrame).count());
  m_lastFrame = now;
  m_time += dt;
  m_orbit += m_set.orbit * (kPi / 180.0f) * dt;

  const float aspect = static_cast<float>(std::max(1, Width())) / std::max(1, Height());
  static const float kLens[] = {62.0f, 40.0f, 24.0f};
  const float fovY = kLens[m_set.lens] * kPi / 180.0f;
  const float halfV = fovY * 0.5f;
  const float halfH = std::atan(std::tan(halfV) * aspect);
  float dist = m_fitRadius / std::sin(std::min(halfV, halfH)) / m_set.zoom;
  dist *= 1.0f + m_set.autoZoom * 0.4f * std::sin(m_time * 2 * kPi / 47.0f);
  dist = std::max(dist, 1.2f);

  if (m_set.movement == MOVE_SCUTTLE)
  {
    // How wide the view is at the crabs' depth, for wrapping them around the edges.
    const float halfW = dist * std::tan(halfH);
    const float halfHt = dist * std::tan(halfV);
    if (!m_spread)
      for (Crab& c : m_crabs)
        c.home.x *= halfW;
    m_spread = true;
    m_scuttleHalfW = halfW;
    m_scuttleHalfH = std::max(0.0f, halfHt - 1.0f);
  }
  for (Crab& c : m_crabs)
    UpdateCrab(c, dt);

  float elev = m_set.height * kPi / 180.0f;
  Vec3 target = V3(0, 0, 0);
  if (m_set.sway)
  {
    elev += 0.06f * std::sin(m_time * 0.11f);
    target = V3(0.12f * std::sin(m_time * 0.07f), 0.08f * std::sin(m_time * 0.09f + 1.0f), 0);
  }
  const Vec3 eye = target + V3(std::cos(elev) * std::sin(m_orbit), std::sin(elev),
                               std::cos(elev) * std::cos(m_orbit)) * dist;
  const Vec3 up = std::fabs(std::cos(elev)) < 0.05f ? V3(0, 0, -1) : V3(0, 1, 0);
  const Mat4 view = LookAt(eye, target, up);
  const Mat4 proj = Perspective(fovY, aspect, std::max(0.05f, dist - m_fitRadius * 3.5f), dist + 150.0f);
  const Mat4 skyProj = Perspective(fovY, aspect, 1.0f, 200.0f);
  const Vec3 fwd = Norm(target - eye);
  const Vec3 right = Norm(Cross(fwd, up));
  const Vec3 camUp = Cross(right, fwd);

  float bright = std::min(1.0f, m_time / 1.5f) * (1.0f - m_set.dim);

#ifdef TARGET_DARWIN
  glBindVertexArray(m_vao);
#endif
  glViewport(X(), Y(), Width(), Height());
  glDisable(GL_SCISSOR_TEST);
  glClearColor(0, 0, 0, 1);
  glDepthMask(GL_TRUE);
#ifdef HAS_GLES
  glClearDepthf(1.0f);
#else
  glClearDepth(1.0);
#endif
  glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

  DrawBackground(bright);
  DrawSky(skyProj, RotationOnly(view), bright);

  glEnable(GL_DEPTH_TEST);
  glDepthFunc(GL_LEQUAL);
  DrawCrabs(Mul(proj, view), eye, right, camUp, fwd, bright);
  glDisable(GL_DEPTH_TEST);

  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif
}

ADDONCREATOR(CScreensaverSpaceCrab)

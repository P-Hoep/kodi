// Kodi screensaver: lichen, reef and coral growth models, drawn with OpenGL / OpenGL ES 2.
//
// Three scenes take turns:
//   Lichen on rock  - Open-DLA colonies (Lichen.h), drawn as a relief-lit rock face
//   Reef ridges     - reaction-advection reef/nutrient fields (Reef.h), drawn as a lit seabed
//   Coral colony    - 3D accretive growth (Coral.h), drawn as shaded point sprites
// The two surface scenes are either seen from straight above or as a 3D surface under a slowly
// moving camera. Every scene gets fresh random parameters.

#include "Coral.h"
#include "Lichen.h"
#include "Reef.h"

#include <kodi/addon-instance/Screensaver.h>
#include <kodi/gui/gl/GL.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

#if !defined(HAS_GLES) && !defined(GL_PROGRAM_POINT_SIZE)
#define GL_PROGRAM_POINT_SIZE 0x8642
#endif

namespace
{

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

// Surface: a grid mesh over [0,1]^2 whose texture carries colour (rgb) and height (a).
const char* kSurfaceVS = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec3 a_pos;   // u, v, height (0..1)
uniform mat4 u_mvp;
uniform vec2 u_extent;  // world half-size of the surface
uniform float u_hscale; // world height of a texel alpha of 1
varying vec2 v_uv;
varying float v_dist;
void main()
{
  v_uv = a_pos.xy;
  vec4 p = vec4((a_pos.x * 2.0 - 1.0) * u_extent.x, (a_pos.y * 2.0 - 1.0) * u_extent.y,
                a_pos.z * u_hscale, 1.0);
  gl_Position = u_mvp * p;
  v_dist = gl_Position.w;
}
)";

const char* kSurfaceFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_tex;
uniform vec2 u_texel;
uniform float u_relief;
uniform vec3 u_light;
uniform float u_time;
uniform float u_caustics;
uniform float u_bright;
uniform float u_edge;
uniform vec3 u_fogColor;
uniform vec2 u_fog;      // start, 1/length (0 length = no fog)
uniform float u_uvScale; // texture repeats (the seabed tiles its sand)
varying vec2 v_uv;
varying float v_dist;
void main()
{
  vec2 tc = v_uv * u_uvScale;
  vec4 c = texture2D(u_tex, tc);
  float hl = texture2D(u_tex, tc - vec2(u_texel.x, 0.0)).a;
  float hr = texture2D(u_tex, tc + vec2(u_texel.x, 0.0)).a;
  float hd = texture2D(u_tex, tc - vec2(0.0, u_texel.y)).a;
  float hu = texture2D(u_tex, tc + vec2(0.0, u_texel.y)).a;
  vec3 n = normalize(vec3((hl - hr) * u_relief, (hd - hu) * u_relief, 1.0));
  float diff = max(dot(n, u_light), 0.0);
  vec3 h = normalize(u_light + vec3(0.0, 0.0, 1.0));
  float spec = pow(max(dot(n, h), 0.0), 24.0) * 0.12;
  vec3 col = c.rgb * (0.42 + 0.78 * diff) + vec3(spec);
  if (u_caustics > 0.0)
  {
    vec2 q = tc * vec2(23.0, 19.0);
    float k = sin(q.x + u_time * 0.9 + 1.7 * sin(q.y * 0.8 - u_time * 0.6)) *
              sin(q.y + u_time * 0.7 + 1.5 * sin(q.x * 0.9 + u_time * 0.5));
    col += u_caustics * pow(max(k, 0.0), 4.0) * vec3(0.55, 0.75, 0.9) * (0.4 + c.a);
  }
  float e = min(min(v_uv.x, 1.0 - v_uv.x), min(v_uv.y, 1.0 - v_uv.y));
  float f = clamp((v_dist - u_fog.x) * u_fog.y, 0.0, 1.0);
  f = max(f, u_edge * (1.0 - smoothstep(0.0, 0.12, e)));
  col = mix(col, u_fogColor, f);
  gl_FragColor = vec4(col * u_bright, 1.0);
}
)";

// Coral voxels as shaded sphere sprites. Young voxels carry the living-tissue colour.
const char* kPointVS = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec3 a_pos;
attribute vec4 a_col;
attribute vec4 a_tip;
attribute float a_birth;
attribute float a_radius;
uniform mat4 u_mvp;
uniform float u_psize;   // pixels per world unit at distance 1
uniform float u_now;
uniform float u_span;
uniform vec2 u_thick;    // older skeleton grows by x (fraction) over y seconds
uniform vec2 u_fog;
varying vec3 v_col;
varying float v_fog;
void main()
{
  gl_Position = u_mvp * vec4(a_pos, 1.0);
  float age = u_now - a_birth;
  float r = a_radius * (1.0 + u_thick.x * min(age / u_thick.y, 1.0));
  gl_PointSize = clamp(2.0 * r * u_psize / gl_Position.w, 1.0, 96.0);
  float k = exp(-age / u_span);
  v_col = mix(a_col.rgb, a_tip.rgb, k);
  v_fog = clamp((gl_Position.w - u_fog.x) * u_fog.y, 0.0, 0.9);
}
)";

const char* kPointFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform vec3 u_fogColor;
uniform float u_bright;
varying vec3 v_col;
varying float v_fog;
void main()
{
  vec2 p = gl_PointCoord * 2.0 - 1.0;
  float r2 = dot(p, p);
  if (r2 > 1.0)
    discard;
  vec3 n = vec3(p.x, -p.y, sqrt(1.0 - r2));
  float diff = max(dot(n, normalize(vec3(-0.35, 0.65, 0.68))), 0.0);
  float rim = pow(1.0 - n.z, 2.0) * 0.25;
  vec3 col = v_col * (0.3 + 0.85 * diff) + vec3(rim * 0.6, rim * 0.8, rim);
  col = mix(col, u_fogColor, v_fog);
  gl_FragColor = vec4(col * u_bright, 1.0);
}
)";

// Full-screen vertical gradient behind the 3D scenes.
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
uniform float u_horizon; // screen height (0..1) of the horizon; below it, the fog colour
varying float v_y;
void main()
{
  float k = smoothstep(u_horizon, u_horizon + 0.5, v_y);
  gl_FragColor = vec4(mix(u_bottom, u_top, k) * u_bright, 1.0);
}
)";

// ---- tiny matrix helpers (column-major, as GL expects)
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

Mat4 LookAt(const float eye[3], const float at[3], const float up[3])
{
  float f[3] = {at[0] - eye[0], at[1] - eye[1], at[2] - eye[2]};
  float fl = std::sqrt(f[0] * f[0] + f[1] * f[1] + f[2] * f[2]);
  for (float& v : f)
    v /= fl;
  float s[3] = {f[1] * up[2] - f[2] * up[1], f[2] * up[0] - f[0] * up[2], f[0] * up[1] - f[1] * up[0]};
  float sl = std::sqrt(s[0] * s[0] + s[1] * s[1] + s[2] * s[2]);
  for (float& v : s)
    v /= sl;
  const float u[3] = {s[1] * f[2] - s[2] * f[1], s[2] * f[0] - s[0] * f[2], s[0] * f[1] - s[1] * f[0]};
  Mat4 r;
  r.m[0] = s[0];
  r.m[4] = s[1];
  r.m[8] = s[2];
  r.m[1] = u[0];
  r.m[5] = u[1];
  r.m[9] = u[2];
  r.m[2] = -f[0];
  r.m[6] = -f[1];
  r.m[10] = -f[2];
  r.m[12] = -(s[0] * eye[0] + s[1] * eye[1] + s[2] * eye[2]);
  r.m[13] = -(u[0] * eye[0] + u[1] * eye[1] + u[2] * eye[2]);
  r.m[14] = f[0] * eye[0] + f[1] * eye[1] + f[2] * eye[2];
  return r;
}

enum Scene { SCENE_LICHEN, SCENE_REEF, SCENE_CORAL, SCENE_COUNT };

struct Settings
{
  int scene = 0;         // 0 take turns, 1 lichen, 2 reef, 3 coral
  bool shuffle = true;   // take turns in random order
  float duration = 180;  // seconds per scene
  int view = 0;          // 0 mix, 1 flat, 2 3D
  int colours = 0;       // 0 natural, 1 vivid, 2 mix
  int lichenSpecies = 5;
  int lichenForm = 0;
  bool lichenRings = true;
  bool reefRandomFlow = true;
  float reefFlow = 0.5f;
  bool reefStorms = true;
  int coralForm = 0;
  int coralColonies = 0;
  float coralSpin = 1.0f;
  int detail = 1;        // 0 low, 1 medium, 2 high
  float dim = 0;
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
    glBindBuffer(GL_ARRAY_BUFFER, static_cast<GLuint>(arrayBuffer));
#ifdef TARGET_DARWIN
    glBindVertexArray(static_cast<GLuint>(vao));
#endif
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, static_cast<GLuint>(elementBuffer));
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

constexpr float kFade = 1.5f;     // seconds of fade in / out
constexpr int kVoxelStride = 28;  // xyz, rgba, tip rgba, birth, radius
constexpr float kHoldDone = 10.0f; // seconds to admire a finished scene before moving on

} // namespace

class ATTR_DLL_LOCAL CScreensaverLichenCoral : public kodi::addon::CAddonBase,
                                               public kodi::addon::CInstanceScreensaver
{
public:
  CScreensaverLichenCoral() = default;

  bool Start() override;
  void Stop() override;
  void Render() override;

private:
  using Clock = std::chrono::steady_clock;

  void LoadSettings();
  GLuint Compile(GLenum type, const std::string& src);
  GLuint Link(const char* vs, const char* fs);
  bool BuildPrograms();
  void StartScene();
  void BuildMesh(int mw, int mh);
  void UploadTexture(const std::vector<uint8_t>& rgba, int w, int h);
  void UpdateMeshHeights(const std::vector<float>& heights, int w, int h);
  void DrawSurface(float bright, bool reef);
  void DrawCoral(float bright);
  void DrawBackground(const lc::Col& top, const lc::Col& bottom, float bright, float horizon);
  void UploadVoxels();

  Settings m_set;
  lc::Rng m_rng{1};

  // scene state
  int m_scene = SCENE_LICHEN;
  bool m_3d = false;
  float m_sceneTime = 0, m_doneAt = -1, m_stepAccum = 0;
  float m_sceneLength = 180;
  bool m_dirty = false;
  std::vector<int> m_deck;
  std::unique_ptr<lc::Lichen> m_lichen;
  std::unique_ptr<lc::Reef> m_reef;
  std::unique_ptr<lc::Coral> m_coral;
  std::vector<uint8_t> m_rgba;

  // camera
  float m_camAz = 0, m_camEl = 0.8f, m_camDist = 2.0f, m_camPhase = 0;
  float m_fitRadius = 0.3f, m_fitHeight = 0.2f, m_fitCx = 0, m_fitCy = 0;

  // GL objects
  GLuint m_surfProg = 0, m_pointProg = 0, m_backProg = 0;
  GLint m_sPos = -1, m_sMvp = -1, m_sExtent = -1, m_sHscale = -1, m_sTex = -1, m_sTexel = -1,
        m_sRelief = -1, m_sLight = -1, m_sTime = -1, m_sCaustics = -1, m_sBright = -1,
        m_sEdge = -1, m_sFogColor = -1, m_sFog = -1, m_sUvScale = -1;
  GLint m_pPos = -1, m_pCol = -1, m_pTip = -1, m_pBirth = -1, m_pRadius = -1, m_pMvp = -1,
        m_pSize = -1, m_pNow = -1, m_pSpan = -1, m_pThick = -1, m_pFog = -1, m_pFogColor = -1,
        m_pBright = -1;
  GLint m_bPos = -1, m_bTop = -1, m_bBottom = -1, m_bBright = -1, m_bHorizon = -1;
  GLuint m_tex = 0, m_floorTex = 0;
  int m_texW = 0, m_texH = 0;
  GLuint m_meshVbo = 0, m_meshIbo = 0, m_quadVbo = 0, m_floorVbo = 0, m_voxelVbo = 0;
  GLuint m_vao = 0;
  int m_meshW = 0, m_meshH = 0;
  GLsizei m_meshIndices = 0;
  std::vector<float> m_meshVerts;
  size_t m_voxelCap = 0, m_voxelsUploaded = 0;
  std::vector<uint8_t> m_voxelStage;

  Clock::time_point m_lastFrame;
  float m_clock = 0, m_frameDt = 0;
};

//------------------------------------------------------------------------------

void CScreensaverLichenCoral::LoadSettings()
{
  static const float kDurations[] = {60, 120, 180, 300, 600, 1200};
  auto clampi = [](int v, int lo, int hi) { return std::min(hi, std::max(lo, v)); };
  m_set.scene = clampi(kodi::addon::GetSettingInt("scene", 0), 0, 3);
  m_set.shuffle = kodi::addon::GetSettingInt("order", 0) == 0;
  m_set.duration = kDurations[clampi(kodi::addon::GetSettingInt("duration", 2), 0, 5)];
  m_set.view = clampi(kodi::addon::GetSettingInt("view", 0), 0, 2);
  m_set.colours = clampi(kodi::addon::GetSettingInt("colours", 0), 0, 2);
  m_set.lichenSpecies = clampi(kodi::addon::GetSettingInt("lichen_species", 5), 1, 8);
  m_set.lichenForm = clampi(kodi::addon::GetSettingInt("lichen_form", 0), 0, 3);
  m_set.lichenRings = kodi::addon::GetSettingBoolean("lichen_rings", true);
  m_set.reefRandomFlow = kodi::addon::GetSettingBoolean("reef_random_flow", true);
  m_set.reefFlow = clampi(kodi::addon::GetSettingInt("reef_flow", 50), 0, 100) / 100.0f;
  m_set.reefStorms = kodi::addon::GetSettingBoolean("reef_storms", true);
  m_set.coralForm = clampi(kodi::addon::GetSettingInt("coral_form", 0), 0, 5);
  m_set.coralColonies = clampi(kodi::addon::GetSettingInt("coral_colonies", 0), 0, 4);
  m_set.coralSpin = clampi(kodi::addon::GetSettingInt("coral_spin", 100), 0, 300) / 100.0f;
  m_set.detail = clampi(kodi::addon::GetSettingInt("detail", 1), 0, 2);
  m_set.dim = clampi(kodi::addon::GetSettingInt("dim", 0), 0, 80) / 100.0f;
}

GLuint CScreensaverLichenCoral::Compile(GLenum type, const std::string& src)
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
    kodi::Log(ADDON_LOG_ERROR, "Lichen & Coral: shader compile failed: %s", log);
    glDeleteShader(shader);
    return 0;
  }
  return shader;
}

GLuint CScreensaverLichenCoral::Link(const char* vsSrc, const char* fsSrc)
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
    kodi::Log(ADDON_LOG_ERROR, "Lichen & Coral: program link failed: %s", log);
    glDeleteProgram(program);
    return 0;
  }
  return program;
}

bool CScreensaverLichenCoral::BuildPrograms()
{
  m_surfProg = Link(kSurfaceVS, kSurfaceFS);
  m_pointProg = Link(kPointVS, kPointFS);
  m_backProg = Link(kBackVS, kBackFS);
  if (!m_surfProg || !m_pointProg || !m_backProg)
    return false;

  m_sPos = glGetAttribLocation(m_surfProg, "a_pos");
  m_sMvp = glGetUniformLocation(m_surfProg, "u_mvp");
  m_sExtent = glGetUniformLocation(m_surfProg, "u_extent");
  m_sHscale = glGetUniformLocation(m_surfProg, "u_hscale");
  m_sTex = glGetUniformLocation(m_surfProg, "u_tex");
  m_sTexel = glGetUniformLocation(m_surfProg, "u_texel");
  m_sRelief = glGetUniformLocation(m_surfProg, "u_relief");
  m_sLight = glGetUniformLocation(m_surfProg, "u_light");
  m_sTime = glGetUniformLocation(m_surfProg, "u_time");
  m_sCaustics = glGetUniformLocation(m_surfProg, "u_caustics");
  m_sBright = glGetUniformLocation(m_surfProg, "u_bright");
  m_sEdge = glGetUniformLocation(m_surfProg, "u_edge");
  m_sFogColor = glGetUniformLocation(m_surfProg, "u_fogColor");
  m_sFog = glGetUniformLocation(m_surfProg, "u_fog");
  m_sUvScale = glGetUniformLocation(m_surfProg, "u_uvScale");

  m_pPos = glGetAttribLocation(m_pointProg, "a_pos");
  m_pCol = glGetAttribLocation(m_pointProg, "a_col");
  m_pTip = glGetAttribLocation(m_pointProg, "a_tip");
  m_pBirth = glGetAttribLocation(m_pointProg, "a_birth");
  m_pRadius = glGetAttribLocation(m_pointProg, "a_radius");
  m_pThick = glGetUniformLocation(m_pointProg, "u_thick");
  m_pMvp = glGetUniformLocation(m_pointProg, "u_mvp");
  m_pSize = glGetUniformLocation(m_pointProg, "u_psize");
  m_pNow = glGetUniformLocation(m_pointProg, "u_now");
  m_pSpan = glGetUniformLocation(m_pointProg, "u_span");
  m_pFog = glGetUniformLocation(m_pointProg, "u_fog");
  m_pFogColor = glGetUniformLocation(m_pointProg, "u_fogColor");
  m_pBright = glGetUniformLocation(m_pointProg, "u_bright");

  m_bPos = glGetAttribLocation(m_backProg, "a_pos");
  m_bTop = glGetUniformLocation(m_backProg, "u_top");
  m_bBottom = glGetUniformLocation(m_backProg, "u_bottom");
  m_bBright = glGetUniformLocation(m_backProg, "u_bright");
  m_bHorizon = glGetUniformLocation(m_backProg, "u_horizon");
  return true;
}

// A (mw x mh)-vertex grid over [0,1]^2. GLES 2 has 16-bit indices, so mw * mh <= 65535.
void CScreensaverLichenCoral::BuildMesh(int mw, int mh)
{
  if (mw == m_meshW && mh == m_meshH)
    return;
  m_meshW = mw;
  m_meshH = mh;
  m_meshVerts.assign(static_cast<size_t>(mw) * mh * 3, 0.0f);
  for (int y = 0; y < mh; y++)
    for (int x = 0; x < mw; x++)
    {
      float* v = &m_meshVerts[(static_cast<size_t>(y) * mw + x) * 3];
      v[0] = static_cast<float>(x) / (mw - 1);
      v[1] = static_cast<float>(y) / (mh - 1);
      v[2] = 0;
    }
  std::vector<uint16_t> idx;
  idx.reserve(static_cast<size_t>(mw - 1) * (mh - 1) * 6);
  for (int y = 0; y + 1 < mh; y++)
    for (int x = 0; x + 1 < mw; x++)
    {
      const uint16_t a = static_cast<uint16_t>(y * mw + x), b = static_cast<uint16_t>(a + 1);
      const uint16_t c = static_cast<uint16_t>(a + mw), d = static_cast<uint16_t>(c + 1);
      idx.insert(idx.end(), {a, b, d, a, d, c});
    }
  m_meshIndices = static_cast<GLsizei>(idx.size());
  glBindBuffer(GL_ARRAY_BUFFER, m_meshVbo);
  glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(m_meshVerts.size() * sizeof(float)),
               m_meshVerts.data(), GL_DYNAMIC_DRAW);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, m_meshIbo);
  glBufferData(GL_ELEMENT_ARRAY_BUFFER, static_cast<GLsizeiptr>(idx.size() * sizeof(uint16_t)),
               idx.data(), GL_STATIC_DRAW);
}

void CScreensaverLichenCoral::UpdateMeshHeights(const std::vector<float>& heights, int w, int h)
{
  if (heights.empty())
    return;
  for (int y = 0; y < m_meshH; y++)
  {
    const int sy = std::min(h - 1, y * (h - 1) / std::max(1, m_meshH - 1));
    for (int x = 0; x < m_meshW; x++)
    {
      const int sx = std::min(w - 1, x * (w - 1) / std::max(1, m_meshW - 1));
      m_meshVerts[(static_cast<size_t>(y) * m_meshW + x) * 3 + 2] =
          heights[static_cast<size_t>(sy) * w + sx];
    }
  }
  glBindBuffer(GL_ARRAY_BUFFER, m_meshVbo);
  glBufferSubData(GL_ARRAY_BUFFER, 0, static_cast<GLsizeiptr>(m_meshVerts.size() * sizeof(float)),
                  m_meshVerts.data());
}

void CScreensaverLichenCoral::UploadTexture(const std::vector<uint8_t>& rgba, int w, int h)
{
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, m_tex);
  glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
  if (w != m_texW || h != m_texH)
  {
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
    m_texW = w;
    m_texH = h;
  }
  else
  {
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
  }
}

void CScreensaverLichenCoral::StartScene()
{
  // pick the scene
  if (m_set.scene > 0)
  {
    m_scene = m_set.scene - 1;
  }
  else if (m_set.shuffle)
  {
    if (m_deck.empty())
    {
      for (int i = 0; i < SCENE_COUNT; i++)
        m_deck.push_back(i);
      for (int i = SCENE_COUNT - 1; i > 0; i--)
        std::swap(m_deck[i], m_deck[m_rng.Int(0, i)]);
      if (m_deck.back() == m_scene && m_deck.size() > 1)
        std::swap(m_deck.front(), m_deck.back());
    }
    m_scene = m_deck.back();
    m_deck.pop_back();
  }
  else
  {
    m_scene = (m_scene + 1) % SCENE_COUNT;
  }

  const uint32_t seed = m_rng.U32() | 1u;
  const bool vivid = m_set.colours == 1 || (m_set.colours == 2 && m_rng.Chance(0.4f));
  m_3d = m_set.view == 2 || (m_set.view == 0 && m_rng.Chance(0.5f));
  m_sceneTime = 0;
  m_doneAt = -1;
  m_stepAccum = 0;
  m_sceneLength = m_set.duration;
  m_lichen.reset();
  m_reef.reset();
  m_coral.reset();

  const float aspect = static_cast<float>(std::max(1, Width())) / std::max(1, Height());
  m_camPhase = m_rng.Range(0.0f, 100.0f);
  m_camAz = m_rng.Range(-0.6f, 0.6f);

  if (m_scene == SCENE_LICHEN)
  {
    static const int kRows[] = {240, 360, 480};
    lc::LichenParams p;
    p.height = kRows[m_set.detail];
    p.width = static_cast<int>(p.height * aspect);
    p.duration = m_sceneLength;
    p.species = m_set.lichenSpecies;
    p.form = m_set.lichenForm;
    p.rings = m_set.lichenRings;
    p.vivid = vivid;
    p.seed = seed;
    m_lichen = std::make_unique<lc::Lichen>();
    m_lichen->Init(p);
    m_lichen->Paint(m_rgba);
    UploadTexture(m_rgba, m_lichen->Width(), m_lichen->Height());
    BuildMesh(std::min(200, static_cast<int>(110 * aspect)), 110);
    UpdateMeshHeights(m_lichen->Heights(), m_lichen->Width(), m_lichen->Height());
  }
  else if (m_scene == SCENE_REEF)
  {
    static const int kRows[] = {128, 180, 240};
    lc::ReefParams p;
    p.height = kRows[m_set.detail];
    p.width = static_cast<int>(p.height * aspect);
    p.flow = m_set.reefRandomFlow ? m_rng.Uni() : m_set.reefFlow;
    p.storms = m_set.reefStorms;
    p.vivid = vivid;
    p.seed = seed;
    m_reef = std::make_unique<lc::Reef>();
    m_reef->Init(p);
    m_reef->Paint(m_rgba);
    UploadTexture(m_rgba, m_reef->Width(), m_reef->Height());
    BuildMesh(std::min(200, static_cast<int>(110 * aspect)), 110);
    UpdateMeshHeights(m_reef->Heights(), m_reef->Width(), m_reef->Height());
  }
  else
  {
    static const int kSize[] = {96, 128, 160};
    static const int kVoxels[] = {40000, 120000, 250000};
    lc::CoralParams p;
    p.size = kSize[m_set.detail];
    p.maxVoxels = kVoxels[m_set.detail];
    p.duration = m_sceneLength;
    p.form = m_set.coralForm;
    p.colonies = m_set.coralColonies;
    p.vivid = vivid;
    p.seed = seed;
    m_coral = std::make_unique<lc::Coral>();
    m_coral->Init(p);
    // vertex buffer for every voxel the colony can grow
    const size_t cap = static_cast<size_t>(p.maxVoxels) + 64;
    glBindBuffer(GL_ARRAY_BUFFER, m_voxelVbo);
    if (cap != m_voxelCap)
    {
      glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(cap * kVoxelStride), nullptr,
                   GL_DYNAMIC_DRAW);
      m_voxelCap = cap;
    }
    m_voxelsUploaded = 0;
    m_fitRadius = 0.15f;
    m_fitHeight = 0.1f;
    m_fitCx = m_fitCy = 0;
    m_camEl = m_rng.Range(0.25f, 0.5f);
    m_camAz = m_rng.Range(0.0f, 2 * lc::kPi);
  }
  m_dirty = false;
  kodi::Log(ADDON_LOG_DEBUG, "Lichen & Coral: scene %d (%s), seed %u", m_scene,
            m_3d ? "3D" : "flat", seed);
}

// Append the voxels grown since the last upload to the vertex buffer.
void CScreensaverLichenCoral::UploadVoxels()
{
  const auto& vox = m_coral->Voxels();
  const size_t n = std::min(vox.size(), m_voxelCap);
  if (n <= m_voxelsUploaded)
    return;
  const size_t count = n - m_voxelsUploaded;
  m_voxelStage.resize(count * kVoxelStride);
  const float half = m_coral->Size() * 0.5f, s = 2.0f / m_coral->Size();
  const auto& colonies = m_coral->ColonyList();
  for (size_t k = 0; k < count; k++)
  {
    const auto& v = vox[m_voxelsUploaded + k];
    uint8_t* out = &m_voxelStage[k * kVoxelStride];
    const float pos[5] = {(v.x - half) * s, (v.y - half) * s, v.z * s, v.birth, v.r * s};
    std::memcpy(out, pos, 12);
    out[12] = v.rgb[0];
    out[13] = v.rgb[1];
    out[14] = v.rgb[2];
    out[15] = 255;
    const lc::Col& tip = colonies[v.colony].tip;
    out[16] = lc::ToByte(tip.r);
    out[17] = lc::ToByte(tip.g);
    out[18] = lc::ToByte(tip.b);
    out[19] = 255;
    std::memcpy(out + 20, &pos[3], 8);
  }
  glBindBuffer(GL_ARRAY_BUFFER, m_voxelVbo);
  glBufferSubData(GL_ARRAY_BUFFER, static_cast<GLintptr>(m_voxelsUploaded * kVoxelStride),
                  static_cast<GLsizeiptr>(count * kVoxelStride), m_voxelStage.data());
  m_voxelsUploaded = n;
}

bool CScreensaverLichenCoral::Start()
{
  LoadSettings();
  m_rng.Seed(static_cast<uint64_t>(Clock::now().time_since_epoch().count()));
  if (!BuildPrograms())
    return false;

#ifdef TARGET_DARWIN
  glGenVertexArrays(1, &m_vao);
  glBindVertexArray(m_vao);
#endif
  glGenBuffers(1, &m_meshVbo);
  glGenBuffers(1, &m_meshIbo);
  glGenBuffers(1, &m_quadVbo);
  glGenBuffers(1, &m_floorVbo);
  glGenBuffers(1, &m_voxelVbo);
  const float quad[] = {-1, -1, 1, -1, -1, 1, 1, 1};
  glBindBuffer(GL_ARRAY_BUFFER, m_quadVbo);
  glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
  const float floorQuad[] = {0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0};
  glBindBuffer(GL_ARRAY_BUFFER, m_floorVbo);
  glBufferData(GL_ARRAY_BUFFER, sizeof(floorQuad), floorQuad, GL_STATIC_DRAW);

  auto makeTex = [](GLuint& tex) {
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  };
  makeTex(m_tex);
  makeTex(m_floorTex);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT); // 256x256: repeat is fine on GLES 2
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
  // Sand for the coral's seabed, with a little relief in alpha.
  {
    const int n = 256;
    std::vector<uint8_t> sand(static_cast<size_t>(n) * n * 4);
    for (int y = 0; y < n; y++)
      for (int x = 0; x < n; x++)
      {
        // seamless: blend the noise with copies shifted by one tile
        auto noise = [](float u, float v) { return lc::Fbm(u / 24.0f, v / 24.0f, 77, 4); };
        const float fx = static_cast<float>(x), fy = static_cast<float>(y), N = static_cast<float>(n);
        const float f = (noise(fx, fy) * (N - fx) * (N - fy) + noise(fx - N, fy) * fx * (N - fy) +
                         noise(fx, fy - N) * (N - fx) * fy + noise(fx - N, fy - N) * fx * fy) /
                        (N * N);
        const float r = lc::Hash01(x, y, 91);
        const float ripple = 0.5f + 0.5f * std::sin(fx * (2.0f * lc::kPi * 14.0f / N) + 9.0f * f);
        const lc::Col c = lc::Scale({0.66f, 0.61f, 0.50f}, 0.75f + 0.3f * f + 0.08f * r);
        lc::Put(&sand[(static_cast<size_t>(y) * n + x) * 4], c, 0.3f * f + 0.15f * ripple);
      }
    glBindTexture(GL_TEXTURE_2D, m_floorTex);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, n, n, 0, GL_RGBA, GL_UNSIGNED_BYTE, sand.data());
  }
  glBindTexture(GL_TEXTURE_2D, 0);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif

  m_scene = m_rng.Int(0, SCENE_COUNT - 1);
  StartScene();
  m_lastFrame = Clock::now();
  m_clock = 0;
  return true;
}

void CScreensaverLichenCoral::Stop()
{
  m_lichen.reset();
  m_reef.reset();
  m_coral.reset();
  GLuint buffers[] = {m_meshVbo, m_meshIbo, m_quadVbo, m_floorVbo, m_voxelVbo};
  glDeleteBuffers(5, buffers);
  m_meshVbo = m_meshIbo = m_quadVbo = m_floorVbo = m_voxelVbo = 0;
  m_meshW = m_meshH = 0;
  m_voxelCap = 0;
  GLuint textures[] = {m_tex, m_floorTex};
  glDeleteTextures(2, textures);
  m_tex = m_floorTex = 0;
  m_texW = m_texH = 0;
#ifdef TARGET_DARWIN
  if (m_vao)
  {
    glDeleteVertexArrays(1, &m_vao);
    m_vao = 0;
  }
#endif
  for (GLuint* p : {&m_surfProg, &m_pointProg, &m_backProg})
  {
    if (*p)
      glDeleteProgram(*p);
    *p = 0;
  }
}

// `horizon`: where a level line of sight meets the screen, for a camera pitched down by `el`
// with vertical field of view `fov`: 0.5 + 0.5 tan(el) / tan(fov / 2).
void CScreensaverLichenCoral::DrawBackground(const lc::Col& top, const lc::Col& bottom, float bright,
                                             float horizon)
{
  glUseProgram(m_backProg);
  glUniform1f(m_bHorizon, horizon);
  glUniform3f(m_bTop, top.r, top.g, top.b);
  glUniform3f(m_bBottom, bottom.r, bottom.g, bottom.b);
  glUniform1f(m_bBright, bright);
  glBindBuffer(GL_ARRAY_BUFFER, m_quadVbo);
  glEnableVertexAttribArray(static_cast<GLuint>(m_bPos));
  glVertexAttribPointer(static_cast<GLuint>(m_bPos), 2, GL_FLOAT, GL_FALSE, 0, nullptr);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
  glDisableVertexAttribArray(static_cast<GLuint>(m_bPos));
}

void CScreensaverLichenCoral::DrawSurface(float bright, bool reef)
{
  const float aspect = static_cast<float>(std::max(1, Width())) / std::max(1, Height());
  const float t = m_clock;
  Mat4 mvp;
  float hscale = 0;
  // Light from the upper left, slowly swinging like a passing sun (or the sea surface).
  const float la = 2.3f + 0.35f * std::sin(t * 0.05f + m_camPhase);
  float light[3] = {std::cos(la) * 0.62f, std::sin(la) * 0.62f, 0.78f};
  const lc::Col fog = reef ? lc::Col{0.04f, 0.16f, 0.26f} : lc::Col{0.05f, 0.05f, 0.06f};

  if (m_3d)
  {
    const lc::Col top = reef ? lc::Col{0.06f, 0.30f, 0.45f} : lc::Col{0.12f, 0.13f, 0.15f};
    hscale = reef ? 0.13f : 0.12f;
    const float ph = m_camPhase + t * 0.02f;
    const float az = m_camAz + 0.55f * std::sin(ph * 0.9f) - lc::kPi * 0.5f;
    const float el = (reef ? 0.72f : 1.0f) + 0.2f * std::sin(ph * 0.63f + 1.0f);
    DrawBackground(top, fog, bright, 0.5f + 0.5f * std::tan(el) / std::tan(0.45f));
    const float dist = (reef ? 1.45f : 1.3f) + 0.22f * std::sin(ph * 0.47f + 2.0f);
    const float roam = reef ? 0.35f : 0.2f;
    const float at[3] = {roam * aspect * std::sin(ph * 0.37f), roam * std::sin(ph * 0.53f + 0.5f),
                         hscale * 0.4f};
    const float eye[3] = {at[0] + dist * std::cos(el) * std::cos(az),
                          at[1] + dist * std::cos(el) * std::sin(az), at[2] + dist * std::sin(el)};
    const float up[3] = {0, 0, 1};
    mvp = Mul(Perspective(0.9f, aspect, 0.05f, 20.0f), LookAt(eye, at, up));
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LEQUAL);
    glDepthMask(GL_TRUE);
  }
  else
  {
    // Straight down; a very slow breathing zoom keeps static pixels from sitting still.
    const float z = 1.05f + 0.02f * std::sin(t * 0.03f + m_camPhase); // > 1 + pan, no edges
    mvp.m[0] = z / aspect;
    mvp.m[5] = z;
    mvp.m[10] = 0.0f;
    mvp.m[12] = 0.02f * std::sin(t * 0.021f + m_camPhase);
    mvp.m[13] = 0.02f * std::cos(t * 0.017f + m_camPhase);
  }

  glUseProgram(m_surfProg);
  glUniformMatrix4fv(m_sMvp, 1, GL_FALSE, mvp.m);
  glUniform2f(m_sExtent, aspect, 1.0f);
  glUniform1f(m_sHscale, hscale);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, m_tex);
  glUniform1i(m_sTex, 0);
  glUniform2f(m_sTexel, 1.0f / std::max(1, m_texW), 1.0f / std::max(1, m_texH));
  glUniform1f(m_sRelief, reef ? 6.0f : 9.0f);
  glUniform3f(m_sLight, light[0], light[1], light[2]);
  glUniform1f(m_sTime, t);
  glUniform1f(m_sCaustics, reef ? 0.35f : 0.0f);
  glUniform1f(m_sBright, bright);
  glUniform1f(m_sEdge, m_3d ? 1.0f : 0.0f);
  glUniform3f(m_sFogColor, fog.r, fog.g, fog.b);
  glUniform2f(m_sFog, 1.2f, m_3d ? (reef ? 0.5f : 0.3f) : 0.0f);
  glUniform1f(m_sUvScale, 1.0f);
  glBindBuffer(GL_ARRAY_BUFFER, m_meshVbo);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, m_meshIbo);
  glEnableVertexAttribArray(static_cast<GLuint>(m_sPos));
  glVertexAttribPointer(static_cast<GLuint>(m_sPos), 3, GL_FLOAT, GL_FALSE, 0, nullptr);
  glDrawElements(GL_TRIANGLES, m_meshIndices, GL_UNSIGNED_SHORT, nullptr);
  glDisableVertexAttribArray(static_cast<GLuint>(m_sPos));
  glDisable(GL_DEPTH_TEST);
}

void CScreensaverLichenCoral::DrawCoral(float bright)
{
  const float aspect = static_cast<float>(std::max(1, Width())) / std::max(1, Height());
  const float dt = m_frameDt;
  // The lower half of the sky is the fog colour, so the seabed melts into it at the horizon.
  const lc::Col top{0.06f, 0.34f, 0.52f};
  const lc::Col fog{0.03f, 0.17f, 0.30f};

  // Frame the colony: track its extent smoothly so the camera eases out as it grows.
  int x0, y0, x1, y1, z1;
  m_coral->Bounds(x0, y0, x1, y1, z1);
  const float s = 2.0f / m_coral->Size(), half = m_coral->Size() * 0.5f;
  const float cx = ((x0 + x1) * 0.5f - half) * s, cy = ((y0 + y1) * 0.5f - half) * s;
  const float rad = std::max((x1 - x0), (y1 - y0)) * 0.5f * s + 0.08f;
  const float hgt = (z1 + 1) * s;
  const float k = 0.02f;
  m_fitRadius += (std::max(rad, hgt * 0.8f) - m_fitRadius) * k;
  m_fitHeight += (hgt - m_fitHeight) * k;
  m_fitCx += (cx - m_fitCx) * k;
  m_fitCy += (cy - m_fitCy) * k;

  m_camAz += dt * 0.12f * m_set.coralSpin;
  const float el = m_camEl + 0.12f * std::sin(m_clock * 0.05f + m_camPhase);
  const float fov = 0.8f;
  // The camera looks at a point above the floor, so the horizon sits a little lower than for a
  // level target; tan(el) is close enough at these distances.
  DrawBackground(top, fog, bright, 0.5f + 0.5f * std::tan(el) / std::tan(fov * 0.5f));
  const float dist = std::max(0.5f, (m_fitRadius * 1.25f + 0.1f) / std::tan(fov * 0.5f));
  const float at[3] = {m_fitCx, m_fitCy, m_fitHeight * 0.42f};
  const float eye[3] = {at[0] + dist * std::cos(el) * std::cos(m_camAz),
                        at[1] + dist * std::cos(el) * std::sin(m_camAz),
                        at[2] + dist * std::sin(el)};
  const float up[3] = {0, 0, 1};
  const Mat4 mvp = Mul(Perspective(fov, aspect, 0.02f, 30.0f), LookAt(eye, at, up));

  glEnable(GL_DEPTH_TEST);
  glDepthFunc(GL_LEQUAL);
  glDepthMask(GL_TRUE);

  // seabed: the surface program on a flat quad
  {
    const float floorHalf = 6.0f;
    glUseProgram(m_surfProg);
    glUniformMatrix4fv(m_sMvp, 1, GL_FALSE, mvp.m);
    glUniform2f(m_sExtent, floorHalf, floorHalf);
    glUniform1f(m_sHscale, 0.0f);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, m_floorTex);
    glUniform1i(m_sTex, 0);
    glUniform2f(m_sTexel, 1.0f / 256, 1.0f / 256);
    glUniform1f(m_sRelief, 2.5f);
    glUniform3f(m_sLight, -0.35f, 0.4f, 0.85f);
    glUniform1f(m_sTime, m_clock);
    glUniform1f(m_sCaustics, 0.45f);
    glUniform1f(m_sBright, bright);
    glUniform1f(m_sEdge, 1.0f);
    glUniform3f(m_sFogColor, fog.r, fog.g, fog.b);
    glUniform2f(m_sFog, dist * 0.45f, 0.75f / dist);
    glUniform1f(m_sUvScale, 6.0f);
    glBindBuffer(GL_ARRAY_BUFFER, m_floorVbo);
    glEnableVertexAttribArray(static_cast<GLuint>(m_sPos));
    glVertexAttribPointer(static_cast<GLuint>(m_sPos), 3, GL_FLOAT, GL_FALSE, 0, nullptr);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    glDisableVertexAttribArray(static_cast<GLuint>(m_sPos));
  }

  if (m_voxelsUploaded > 0)
  {
#ifdef GL_PROGRAM_POINT_SIZE
    glEnable(GL_PROGRAM_POINT_SIZE);
#endif
    const float projScale = Height() / (2.0f * std::tan(fov * 0.5f));
    glUseProgram(m_pointProg);
    glUniformMatrix4fv(m_pMvp, 1, GL_FALSE, mvp.m);
    glUniform1f(m_pSize, projScale);
    glUniform1f(m_pNow, m_coral->Time());
    glUniform1f(m_pSpan, m_coral->TipSpan());
    glUniform2f(m_pThick, m_coral->Thickening(), m_coral->ThickeningTime());
    glUniform2f(m_pFog, dist * 0.7f, 0.6f / dist);
    glUniform3f(m_pFogColor, fog.r, fog.g, fog.b);
    glUniform1f(m_pBright, bright);
    glBindBuffer(GL_ARRAY_BUFFER, m_voxelVbo);
    const GLuint aPos = static_cast<GLuint>(m_pPos), aCol = static_cast<GLuint>(m_pCol),
                 aTip = static_cast<GLuint>(m_pTip), aBirth = static_cast<GLuint>(m_pBirth),
                 aRadius = static_cast<GLuint>(m_pRadius);
    const GLsizei stride = kVoxelStride;
    for (GLuint a : {aPos, aCol, aTip, aBirth, aRadius})
      glEnableVertexAttribArray(a);
    glVertexAttribPointer(aPos, 3, GL_FLOAT, GL_FALSE, stride, nullptr);
    glVertexAttribPointer(aCol, 4, GL_UNSIGNED_BYTE, GL_TRUE, stride, reinterpret_cast<void*>(12));
    glVertexAttribPointer(aTip, 4, GL_UNSIGNED_BYTE, GL_TRUE, stride, reinterpret_cast<void*>(16));
    glVertexAttribPointer(aBirth, 1, GL_FLOAT, GL_FALSE, stride, reinterpret_cast<void*>(20));
    glVertexAttribPointer(aRadius, 1, GL_FLOAT, GL_FALSE, stride, reinterpret_cast<void*>(24));
    glDrawArrays(GL_POINTS, 0, static_cast<GLsizei>(m_voxelsUploaded));
    for (GLuint a : {aPos, aCol, aTip, aBirth, aRadius})
      glDisableVertexAttribArray(a);
  }
  glDisable(GL_DEPTH_TEST);
}

void CScreensaverLichenCoral::Render()
{
  if (!m_surfProg)
    return;
  SavedState saved;

  const auto now = Clock::now();
  const float dt = std::min(0.1f, std::chrono::duration<float>(now - m_lastFrame).count());
  m_lastFrame = now;
  m_clock += dt;
  m_frameDt = dt;
  m_sceneTime += dt;

#ifdef TARGET_DARWIN
  glBindVertexArray(m_vao);
#endif

  // --- advance the scene's model
  bool done = false;
  if (m_lichen)
  {
    const float step = 1.0f / 30.0f;
    m_stepAccum += dt;
    int steps = 0;
    while (m_stepAccum >= step && steps < 2)
    {
      m_lichen->Step(step);
      m_stepAccum -= step;
      steps++;
    }
    if (steps == 2)
      m_stepAccum = 0;
    if (steps > 0)
    {
      m_lichen->Paint(m_rgba);
      UploadTexture(m_rgba, m_lichen->Width(), m_lichen->Height());
      if (m_3d)
        UpdateMeshHeights(m_lichen->Heights(), m_lichen->Width(), m_lichen->Height());
    }
    done = m_lichen->Done();
  }
  else if (m_reef)
  {
    m_reef->Advance(dt);
    m_stepAccum += dt;
    if (m_stepAccum >= 1.0f / 30.0f)
    {
      m_stepAccum = 0;
      m_reef->Paint(m_rgba);
      UploadTexture(m_rgba, m_reef->Width(), m_reef->Height());
      if (m_3d)
        UpdateMeshHeights(m_reef->Heights(), m_reef->Width(), m_reef->Height());
    }
  }
  else if (m_coral)
  {
    m_coral->Advance(dt);
    UploadVoxels();
    done = m_coral->Done();
  }
  if (done && m_doneAt < 0)
    m_doneAt = m_sceneTime;
  float end = m_sceneLength;
  if (m_doneAt >= 0)
    end = std::min(end, m_doneAt + kHoldDone);
  end = std::max(end, 2 * kFade + 1);

  // --- fade in and out
  float bright = std::min(1.0f, m_sceneTime / kFade);
  bright = std::min(bright, std::max(0.0f, (end - m_sceneTime) / kFade));
  bright *= 1.0f - m_set.dim;

  // --- draw
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

  if (m_lichen)
    DrawSurface(bright, false);
  else if (m_reef)
    DrawSurface(bright, true);
  else if (m_coral)
    DrawCoral(bright);

  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif

  if (m_sceneTime >= end)
    StartScene();
}

ADDONCREATOR(CScreensaverLichenCoral)

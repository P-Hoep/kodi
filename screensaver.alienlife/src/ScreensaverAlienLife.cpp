// Kodi screensaver wrapper around the Alien Life world (Alien.h).
//
// As in Emergence and Physarum v2, the world steps on a driver thread of its
// own plus a small worker pool, one step ahead of the picture, so Render()
// never waits: when a step has finished, Render() uploads the vertex streams
// the driver built for it and kicks off the next step. New worlds are set up
// by the driver thread too, behind a fade to black. The driver also moves the
// camera: the whole world, a slow tour of where life is busiest, or a close-up
// that follows one creature after another.
//
// Two looks, both plain OpenGL / OpenGL ES 2 (GLSL 1.00 style shaders):
//
//  - Organic, after ALIEN's renderer: the bodies (the triangles between
//    connected cells, thick connections and shaded cells) go into an
//    off-screen layer that is blurred and then turned into soft, fused,
//    translucent bodies with a metaball threshold, relief lighting, a
//    membrane rim, crevice shading and a wet sheen. Energy particles, the
//    radiation sources and the events (attack beams, injections, grabs,
//    detonation flashes and shock waves, births) glow on top; a two-level
//    bloom and a soft tone curve finish it over a dim nebula background.
//  - Classic: the glowing point sprites and lines of version 1, with optional
//    motion trails.
//
// The organic layers can be drawn at half resolution for weak GPUs.

#include "Alien.h"

#include <kodi/addon-instance/Screensaver.h>
#include <kodi/gui/gl/GL.h>

#include <algorithm>
#include <atomic>
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

// ---- shaders ------------------------------------------------------------------

// Flat triangles (bodies, connections) and the classic look's lines: position
// and colour, alpha unused.
const char* kFlatVS = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;
attribute vec4 a_col;
uniform float u_gain;
varying vec3 v_col;
void main()
{
  gl_Position = vec4(a_pos, 0.0, 1.0);
  v_col = a_col.rgb * u_gain;
}
)";

const char* kFlatFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform float u_alpha;
varying vec3 v_col;
void main()
{
  gl_FragColor = vec4(v_col, u_alpha);
}
)";

// Cells in the organic look: a translucent vesicle, lit from the upper left,
// with a small nucleus tinted by the cell type. Alpha of a_col carries the
// size (1.0 = 128), alpha of a_nuc how brightly the cell flashes.
const char* kCellVS = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;
attribute vec4 a_col;
attribute vec4 a_nuc;
uniform float u_pointSize;
varying vec3 v_col;
varying vec4 v_nuc;
void main()
{
  gl_Position = vec4(a_pos, 0.0, 1.0);
  gl_PointSize = u_pointSize * a_col.a * 1.9921875;
  v_col = a_col.rgb;
  v_nuc = a_nuc;
}
)";

const char* kCellFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform float u_nucleus;
varying vec3 v_col;
varying vec4 v_nuc;
void main()
{
  vec2 c = (gl_PointCoord - vec2(0.5)) * 2.0;
  c.y = -c.y;
  float r2 = dot(c, c);
  if (r2 > 1.0)
    discard;
  vec3 n = vec3(c, sqrt(1.0 - r2));
  vec3 L = normalize(vec3(-0.55, 0.55, 0.62));
  float diffuse = 0.68 + 0.32 * dot(n, L);
  float rim = 0.25 * r2 * r2;
  float sheen = 0.18 * pow(max(dot(n, normalize(L + vec3(0.0, 0.0, 1.0))), 0.0), 10.0);
  vec3 col = v_col * (diffuse + rim) + vec3(sheen);
  // the nucleus: a soft dot of the type colour, off centre towards the light
  float nd = length(c - vec2(-0.12, 0.12));
  float nucleus = (1.0 - smoothstep(0.18, 0.36, nd)) * u_nucleus;
  col = mix(col, v_nuc.rgb, nucleus * 0.75);
  col += vec3(v_nuc.a * 0.55);
  float edge = 1.0 - 0.45 * smoothstep(0.55, 1.0, r2);
  gl_FragColor = vec4(col * edge, 1.0);
}
)";

// Glowing point sprites: energy particles in the organic look, and every
// cell and particle in the classic look (a disc with a halo).
const char* kGlowVS = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;
attribute vec4 a_col;
uniform float u_pointSize;
uniform float u_gain;
varying vec3 v_col;
void main()
{
  gl_Position = vec4(a_pos, 0.0, 1.0);
  gl_PointSize = u_pointSize * a_col.a * 1.9921875;
  v_col = a_col.rgb * u_gain;
}
)";

// u_disc 0: a gaussian glow; 1: the classic cell, a bright disc with a halo
const char* kGlowFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform float u_disc;
uniform float u_halo;
varying vec3 v_col;
void main()
{
  vec2 c = gl_PointCoord - vec2(0.5);
  float d2 = dot(c, c) * 4.0;
  if (d2 > 1.0)
    discard;
  if (u_disc < 0.5)
  {
    float g = exp(-d2 * 6.0) + 0.6 * exp(-d2 * 30.0);
    gl_FragColor = vec4(v_col * g, g);
    return;
  }
  float disc = 1.0 - smoothstep(0.16, 0.26, d2);
  float halo = exp(-d2 * 5.0) * u_halo;
  float a = max(disc * 0.95, halo);
  float top = max(v_col.r, max(v_col.g, v_col.b));
  gl_FragColor = vec4(mix(v_col, vec3(top), disc * 0.18), a);
}
)";

// Effects on quads: a_fx.x = u, a_fx.y = v (-1..1), a_fx.z = shape:
//   < 0.5  a soft disc (sources, flashes)
//   1..2   a ring of radius (shape - 1) (shock waves, births)
//   >= 2.5 a beam along u (0 at the attacker, 1 at the target)
const char* kFxVS = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a_pos;
attribute vec3 a_fx;
attribute vec4 a_col;
uniform float u_gain;
varying vec3 v_fx;
varying vec3 v_col;
void main()
{
  gl_Position = vec4(a_pos, 0.0, 1.0);
  v_fx = a_fx;
  v_col = a_col.rgb * a_col.a * u_gain;
}
)";

const char* kFxFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
varying vec3 v_fx;
varying vec3 v_col;
void main()
{
  float a;
  if (v_fx.z < 0.5)
  {
    float d2 = v_fx.x * v_fx.x + v_fx.y * v_fx.y;
    a = exp(-d2 * 4.0) * (1.0 - smoothstep(0.6, 1.0, d2));
  }
  else if (v_fx.z < 2.5)
  {
    float r = length(v_fx.xy);
    float w = (r - (v_fx.z - 1.0)) * 14.0;
    a = exp(-w * w) * (1.0 - smoothstep(0.9, 1.0, r));
  }
  else
  {
    float across = v_fx.y * v_fx.y * 5.0;
    float along = smoothstep(0.0, 0.12, v_fx.x) * (1.0 - smoothstep(0.88, 1.0, v_fx.x));
    a = (exp(-across) + 0.8 * exp(-across * 8.0)) * along * (0.35 + 0.65 * v_fx.x);
  }
  gl_FragColor = vec4(v_col * a, 1.0);
}
)";

// Full-screen passes share one vertex shader.
const char* kQuadVS = R"(
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

// Separable 9-tap gaussian in 5 linear fetches; u_step = direction * texel * radius.
const char* kBlurFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_tex;
uniform vec2 u_step;
varying vec2 v_uv;
void main()
{
  vec3 c = texture2D(u_tex, v_uv).rgb * 0.2270270;
  c += texture2D(u_tex, v_uv + u_step * 1.3846154).rgb * 0.3162162;
  c += texture2D(u_tex, v_uv - u_step * 1.3846154).rgb * 0.3162162;
  c += texture2D(u_tex, v_uv + u_step * 3.2307692).rgb * 0.0702703;
  c += texture2D(u_tex, v_uv - u_step * 3.2307692).rgb * 0.0702703;
  gl_FragColor = vec4(c, 1.0);
}
)";

// The organic surface. The blurred body layer is a density field (its
// brightness): a smooth threshold gives the fused silhouette, its gradient a
// surface normal for soft relief lighting, thin regions a translucent rim,
// the difference between a near and a far ring of samples the crevices
// between bodies, and a narrow highlight a wet sheen. Output is
// premultiplied, alpha = coverage, so it can lie over the trails.
const char* kOrganicFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_tex;
uniform vec2 u_texel;
uniform float u_r1;
uniform float u_r2;
uniform float u_relief;
varying vec2 v_uv;
float dens(vec3 c)
{
  return smoothstep(0.03, 0.30, c.r + c.g + c.b);
}
void main()
{
  vec3 c0 = texture2D(u_tex, v_uv).rgb;
  float d0 = dens(c0);
  vec2 grad = vec2(0.0);
  float dIn = 0.0;
  float dOut = 0.0;
  vec3 cIn = vec3(0.0);
  for (int i = 0; i < 8; i++)
  {
    float ang = (float(i) + 0.5) * 0.78539816;
    vec2 dir = vec2(cos(ang), sin(ang));
    vec3 a = texture2D(u_tex, v_uv + dir * u_texel * u_r1).rgb;
    float da = dens(a);
    grad += dir * da;
    dIn += da;
    cIn += a;
    dOut += dens(texture2D(u_tex, v_uv + dir * u_texel * u_r2).rgb);
  }
  grad *= 0.125;
  dIn *= 0.125;
  dOut *= 0.125;
  cIn *= 0.125;
  float cover = smoothstep(0.32, 0.5, 0.45 * d0 + 0.4 * dIn + 0.15 * dOut);
  if (cover <= 0.001)
  {
    gl_FragColor = vec4(0.0);
    return;
  }
  vec3 col = mix(c0, cIn, 0.2);
  col /= max(max(col.r, max(col.g, col.b)), 0.001) / max(max(c0.r, max(c0.g, c0.b)), 0.25);
  float thick = smoothstep(0.2, 0.9, dIn);
  float lum = dot(col, vec3(0.299, 0.587, 0.114));
  col = mix(col, mix(vec3(lum), col, 1.35) * 0.85, 0.5 * thick);
  vec3 n = normalize(vec3(-grad * u_relief, 1.0));
  vec3 L = normalize(vec3(-0.55, 0.55, 0.62));
  float diffuse = 0.55 + 0.45 * dot(n, L);
  col *= diffuse / (0.55 + 0.45 * L.z);
  float edge = d0 * (1.0 - thick);
  col += pow(1.0 - n.z, 1.5) * edge * 0.45 * c0;
  col += cIn * 0.12 * edge;
  float cavity = max(dOut - dIn, 0.0);
  col *= 1.0 - 0.35 * cavity * d0;
  vec3 H = normalize(L + vec3(0.0, 0.0, 1.0));
  float spec = pow(max(dot(n, H), 0.0), 14.0) * smoothstep(0.04, 0.3, length(grad));
  col += vec3(spec * 0.16);
  gl_FragColor = vec4(max(col, vec3(0.0)) * cover, cover);
}
)";

// Copies the last frame darker (trails): out = max(prev * keep - sub, 0).
const char* kFadeFS = R"(
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

// Bloom: the bright part of a 4-tap box, down to the smaller target.
const char* kBrightFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_tex;
uniform vec2 u_texel;
uniform float u_threshold;
varying vec2 v_uv;
void main()
{
  vec3 c = texture2D(u_tex, v_uv + vec2(-u_texel.x, -u_texel.y)).rgb;
  c += texture2D(u_tex, v_uv + vec2(u_texel.x, -u_texel.y)).rgb;
  c += texture2D(u_tex, v_uv + vec2(-u_texel.x, u_texel.y)).rgb;
  c += texture2D(u_tex, v_uv + vec2(u_texel.x, u_texel.y)).rgb;
  c *= 0.25;
  float m = dot(c, vec3(0.3, 0.5, 0.2));
  float k = max(m - u_threshold, 0.0) / max(m, 0.001);
  gl_FragColor = vec4(c * k, 1.0);
}
)";

// The picture: the nebula background behind the bodies, the scene, two bloom
// levels, a soft shoulder instead of a hard clip, and the fade.
const char* kFinalFS = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_scene;
uniform sampler2D u_bloom1;
uniform sampler2D u_bloom2;
uniform sampler2D u_bg;
uniform vec2 u_bgScale;
uniform vec2 u_bgOffset;
uniform float u_bloom;
uniform float u_bright;
varying vec2 v_uv;
void main()
{
  vec3 s = texture2D(u_scene, v_uv).rgb;
  vec3 b = texture2D(u_bloom1, v_uv).rgb * 0.7 + texture2D(u_bloom2, v_uv).rgb * 0.9;
  vec3 bg = texture2D(u_bg, v_uv * u_bgScale + u_bgOffset).rgb;
  vec2 q = v_uv - vec2(0.5);
  bg *= 1.0 - 0.9 * dot(q, q);
  float cover = smoothstep(0.0, 0.25, max(s.r, max(s.g, s.b)));
  vec3 c = s + b * u_bloom + bg * (1.0 - cover);
  c = c * 1.15 / (1.0 + 0.15 * c);
  gl_FragColor = vec4(min(c, vec3(1.0)) * u_bright, 1.0);
}
)";

constexpr double kFadeSeconds = 2.5;

enum WorldSetting { WS_RANDOM = 0 }; // then 1 + alien::WorldKind
enum ColourMode { COL_GENOME, COL_TYPE, COL_LINEAGE, COL_ENERGY };
enum Pace { PACE_NORMAL, PACE_FAST, PACE_SLOW };
enum Style { STYLE_ORGANIC, STYLE_CLASSIC };
enum ViewMode { VIEW_WHOLE, VIEW_ROAM, VIEW_FOLLOW };
enum Quality { QUALITY_AUTO, QUALITY_FULL, QUALITY_HALF };

// How much of the last frame the trails keep, per trails setting. Everything
// additive is drawn into a trail buffer at (1 - keep) of its brightness, so a
// glow that stays put settles at its normal brightness instead of piling up
// to white, and only what moves leaves a streak.
const float kTrailKeep[] = {0.0f, 0.80f, 0.89f, 0.945f};
constexpr float kTrailSub = 0.6f / 255.0f;

const char* const kWorldNames[] = {"Grazers", "Grazers and hunters", "Primordial soup", "Ecosystem"};

struct Vertex
{
  float x, y;
  uint32_t rgba; // bytes r, g, b, a in memory order
};

struct CellVertex
{
  float x, y;
  uint32_t rgba; // colour, a = sprite size
  uint32_t nuc;  // nucleus colour, a = flash
};

struct FxVertex
{
  float x, y;
  float u, v, shape;
  uint32_t rgba; // colour, a = intensity
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
inline uint32_t Pack(const RGB& c, float a) { return Pack(c.r, c.g, c.b, a); }

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

// base, sensor, muscle, generator, attacker, digestor, defender, depot,
// injector, reconnector, detonator, memory, communicator
const RGB kTypeColours[alien::CT_COUNT] = {
    {0.55f, 0.62f, 0.80f}, {1.0f, 0.90f, 0.30f}, {1.0f, 0.38f, 0.50f}, {0.30f, 0.90f, 1.0f}, {1.0f, 0.45f, 0.12f},
    {0.40f, 1.0f, 0.45f},  {0.72f, 0.48f, 1.0f}, {0.95f, 0.75f, 0.45f}, {1.0f, 0.25f, 0.95f}, {0.35f, 1.0f, 0.85f},
    {1.0f, 0.95f, 0.80f},  {0.55f, 0.75f, 1.0f}, {0.85f, 1.0f, 0.40f}};

// sprite size per cell type (alpha byte, 128 = 1.0)
const float kTypeSize[alien::CT_COUNT] = {0.92f, 1.05f, 1.0f, 1.0f, 1.08f, 1.08f, 1.04f,
                                          1.06f, 1.06f, 1.02f, 1.10f, 1.0f,  1.02f};

const RGB kRock = {0.30f, 0.29f, 0.34f};

// event colours
const RGB kEventColour[alien::EV_COUNT] = {
    {1.0f, 0.42f, 0.18f}, {0.95f, 0.30f, 1.0f}, {0.35f, 1.0f, 0.90f}, {1.0f, 0.85f, 0.55f}, {0.8f, 0.9f, 1.0f}};

// An off-screen colour target.
struct Target
{
  GLuint tex = 0, fbo = 0;
  int w = 0, h = 0;
};

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

  struct Program
  {
    GLuint id = 0;
    GLint aPos = -1, aCol = -1, aNuc = -1, aFx = -1;
    GLint uGain = -1, uAlpha = -1, uPointSize = -1, uNucleus = -1, uDisc = -1, uHalo = -1;
    GLint uTex = -1, uStep = -1, uTexel = -1, uR1 = -1, uR2 = -1, uRelief = -1, uKeep = -1, uSub = -1,
          uThreshold = -1;
    GLint uScene = -1, uBloom1 = -1, uBloom2 = -1, uBg = -1, uBgScale = -1, uBgOffset = -1, uBloom = -1,
          uBright = -1;
  };

  void LoadSettings();
  GLuint Compile(GLenum type, const std::string& src);
  bool Link(Program& p, const char* vs, const char* fs);
  bool BuildPrograms();
  void BuildBackground();
  void BeginWorld();
  void MoveCamera(int steps);
  void BuildVertices();
  void BuildOrganic();
  void BuildClassic();
  void BuildEffects();
  void DriverLoop();
  void StopSimulation();
  void UploadFrame();
  void DrawClassic(float fade, bool sources);
  void RenderOrganic(float bright);
  void DrawQuad(GLint aPos);
  void DrawFlat(GLuint vbo, size_t count, float gain, GLenum mode);
  void DrawGlowPoints(GLuint vbo, size_t count, float gain, bool disc);
  void DrawCells(float pointSize);
  void DrawEffects(float gain, size_t first, size_t count);
  bool MakeTarget(Target& t, int w, int h);
  void DeleteTarget(Target& t);
  bool EnsureTargets(int w, int h);
  void DeleteTargets();
  void Bind(const Target& t);
  void Blur(Target& src, Target& tmp, float radius);
  bool EnsureTrailBuffers(int w, int h);
  void DeleteTrailBuffers();
  float PointSizeScale() const;

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

  // the camera (driver thread): centre in world units, zoom, its motion
  float m_camX = 0, m_camY = 0, m_camVX = 0, m_camVY = 0, m_zoom = 1.0f;
  float m_tgtX = 0, m_tgtY = 0;
  int m_camTimer = 0;
  int m_followCr = -1;
  uint32_t m_followId = 0;
  // the view that the streams were built for (copied to the render thread)
  float m_viewW = 1, m_viewH = 1, m_viewX = 0, m_viewY = 0;

  // written by the driver thread while busy, read by Render while not
  std::vector<Vertex> m_tris;          // organic: body triangles and connection quads
  std::vector<CellVertex> m_cells;     // organic: cell sprites
  std::vector<Vertex> m_glowPts;       // organic: energy particles
  std::vector<FxVertex> m_fx;          // sources, then events (both looks)
  size_t m_fxSources = 0;              // how many of m_fx are the sources
  std::vector<Vertex> m_lines;         // classic: connections
  std::vector<Vertex> m_points;        // classic: particles and cells
  std::vector<RGB> m_cellColour;
  std::vector<float> m_rx, m_ry;       // cells relative to the camera, world units
  std::vector<uint8_t> m_near;         // ... and whether they are in (or near) the view
  int m_worldKind = 0;
  // what was uploaded, for drawing (render thread only)
  size_t m_drawTris = 0, m_drawCells = 0, m_drawGlow = 0, m_drawFx = 0, m_drawFxSources = 0, m_drawLines = 0,
         m_drawPoints = 0;
  float m_drawViewW = 1, m_drawViewH = 1, m_drawViewX = 0, m_drawViewY = 0;
  unsigned m_drawSerial = ~0u;

  // GL
  Program m_flat, m_cell, m_glow, m_fxProg, m_blur, m_organic, m_fade, m_bright, m_final;
  GLuint m_vboTris = 0, m_vboCells = 0, m_vboGlow = 0, m_vboFx = 0, m_vboLines = 0, m_vboPoints = 0;
  GLuint m_quadVbo = 0, m_vao = 0, m_bgTex = 0;
  float m_maxPointSize = 64.0f;
  std::atomic<bool> m_organicOk{false}; // cleared by Render if the targets fail
  // organic targets: bodies, a blur partner, scene (two, for trails), two bloom levels
  Target m_body, m_bodyTmp, m_scene[2], m_bloomA, m_bloomB, m_bloomC, m_bloomD;
  int m_targetW = 0, m_targetH = 0, m_sceneCur = 0;
  bool m_targetsFailed = false, m_sceneFresh = true;
  // classic trails
  GLuint m_fadeTex[2] = {0, 0}, m_fadeFbo[2] = {0, 0};
  int m_fadeW = 0, m_fadeH = 0, m_fadeCur = 0;
  bool m_fadeFailed = false;

  // settings
  alien::Params m_params;
  int m_worldSetting = WS_RANDOM;
  int m_worldMinutes = 20;
  int m_style = STYLE_ORGANIC;
  int m_viewMode = VIEW_ROAM;
  int m_colourMode = COL_GENOME;
  float m_cellSize = 1.0f;
  bool m_bloom = true;
  bool m_connections = true;
  bool m_showParticles = true;
  bool m_sourceGlow = true;
  bool m_showEvents = true;
  int m_trails = 0;
  float m_dim = 0.0f;
  int m_quality = QUALITY_AUTO;
  bool m_halfRes = false;
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
  m_params.rocks = std::min(std::max(GetSettingInt("rocks", 1), 0), 2);
  m_params.muscle = std::min(std::max(GetSettingInt("muscle", 100), 25), 300) / 100.0f;
  m_worldMinutes = std::min(std::max(GetSettingInt("world_minutes", 20), 0), 240);

  m_style = std::min(std::max(GetSettingInt("style", STYLE_ORGANIC), 0), 1);
  m_viewMode = std::min(std::max(GetSettingInt("view", VIEW_ROAM), 0), 2);
  m_colourMode = std::min(std::max(GetSettingInt("colour", COL_GENOME), 0), 3);
  m_cellSize = std::min(std::max(GetSettingInt("cell_size", 100), 25), 300) / 100.0f;
  m_bloom = GetSettingBoolean("glow", true);
  m_connections = GetSettingBoolean("connections", true);
  m_showParticles = GetSettingBoolean("particles", true);
  m_sourceGlow = GetSettingBoolean("source_glow", true);
  m_showEvents = GetSettingBoolean("events", true);
  m_trails = std::min(std::max(GetSettingInt("trails", 0), 0), 3);
  m_dim = std::min(std::max(GetSettingInt("dim", 0), 0), 90) / 100.0f;

  m_quality = std::min(std::max(GetSettingInt("quality", QUALITY_AUTO), 0), 2);
#if defined(TARGET_ANDROID)
  m_halfRes = m_quality != QUALITY_FULL;
#else
  m_halfRes = m_quality == QUALITY_HALF;
#endif
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

bool CScreensaverAlienLife::Link(Program& p, const char* vsSrc, const char* fsSrc)
{
  GLuint vs = Compile(GL_VERTEX_SHADER, kVertexHeader + vsSrc);
  GLuint fs = Compile(GL_FRAGMENT_SHADER, kFragmentHeader + fsSrc);
  if (!vs || !fs)
  {
    if (vs)
      glDeleteShader(vs);
    if (fs)
      glDeleteShader(fs);
    return false;
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
    return false;
  }
  p.id = program;
  auto A = [&](const char* n) { return glGetAttribLocation(program, n); };
  auto U = [&](const char* n) { return glGetUniformLocation(program, n); };
  p.aPos = A("a_pos");
  p.aCol = A("a_col");
  p.aNuc = A("a_nuc");
  p.aFx = A("a_fx");
  p.uGain = U("u_gain");
  p.uAlpha = U("u_alpha");
  p.uPointSize = U("u_pointSize");
  p.uNucleus = U("u_nucleus");
  p.uDisc = U("u_disc");
  p.uHalo = U("u_halo");
  p.uTex = U("u_tex");
  p.uStep = U("u_step");
  p.uTexel = U("u_texel");
  p.uR1 = U("u_r1");
  p.uR2 = U("u_r2");
  p.uRelief = U("u_relief");
  p.uKeep = U("u_keep");
  p.uSub = U("u_sub");
  p.uThreshold = U("u_threshold");
  p.uScene = U("u_scene");
  p.uBloom1 = U("u_bloom1");
  p.uBloom2 = U("u_bloom2");
  p.uBg = U("u_bg");
  p.uBgScale = U("u_bgScale");
  p.uBgOffset = U("u_bgOffset");
  p.uBloom = U("u_bloom");
  p.uBright = U("u_bright");
  return true;
}

bool CScreensaverAlienLife::BuildPrograms()
{
  // the classic look needs only these two
  if (!Link(m_flat, kFlatVS, kFlatFS) || !Link(m_glow, kGlowVS, kGlowFS))
    return false;
  Link(m_fxProg, kFxVS, kFxFS);
  Link(m_fade, kQuadVS, kFadeFS);
  if (!m_fade.id)
    m_fadeFailed = true;
  // the organic look falls back to classic without any of these
  m_organicOk = Link(m_cell, kCellVS, kCellFS) && Link(m_blur, kQuadVS, kBlurFS) &&
                Link(m_organic, kQuadVS, kOrganicFS) && Link(m_bright, kQuadVS, kBrightFS) &&
                Link(m_final, kQuadVS, kFinalFS) && m_fxProg.id != 0;
  if (!m_organicOk)
    kodi::Log(ADDON_LOG_WARNING, "Alien Life: organic look unavailable, drawing the classic look");
  return true;
}

// A dim, tileable nebula: a few octaves of value noise on a 256 x 256 texture.
void CScreensaverAlienLife::BuildBackground()
{
  constexpr int N = 256;
  std::vector<uint8_t> px(static_cast<size_t>(N) * N * 4);
  auto lattice = [](int x, int y, int period, uint32_t salt) {
    x = ((x % period) + period) % period;
    y = ((y % period) + period) % period;
    return static_cast<float>(alien::Hash(static_cast<uint32_t>(x * 73856093) ^ static_cast<uint32_t>(y * 19349663) ^
                                          salt) >>
                              8) /
           16777216.0f;
  };
  auto noise = [&](float x, float y, int period, uint32_t salt) {
    const int ix = static_cast<int>(std::floor(x)), iy = static_cast<int>(std::floor(y));
    float fx = x - ix, fy = y - iy;
    fx = fx * fx * (3 - 2 * fx);
    fy = fy * fy * (3 - 2 * fy);
    const float a = lattice(ix, iy, period, salt), b = lattice(ix + 1, iy, period, salt);
    const float c = lattice(ix, iy + 1, period, salt), d = lattice(ix + 1, iy + 1, period, salt);
    return (a + (b - a) * fx) + ((c + (d - c) * fx) - (a + (b - a) * fx)) * fy;
  };
  const uint32_t salt = m_rng();
  for (int y = 0; y < N; y++)
    for (int x = 0; x < N; x++)
    {
      float n1 = 0, n2 = 0, amp = 0.5f;
      for (int o = 0, period = 4; o < 4; o++, period *= 2, amp *= 0.5f)
      {
        const float s = static_cast<float>(period) / N;
        n1 += amp * noise(x * s, y * s, period, salt);
        n2 += amp * noise(x * s + 17.3f, y * s + 5.1f, period, salt ^ 0x9e3779b9u);
      }
      const float cloud = std::pow(std::max(n1 - 0.35f, 0.0f) / 0.65f, 1.6f);
      const float tint = n2;
      uint8_t* o = &px[(static_cast<size_t>(y) * N + x) * 4];
      const float r = 0.012f + cloud * (0.045f + 0.05f * tint);
      const float g = 0.016f + cloud * (0.020f + 0.03f * (1 - tint));
      const float b = 0.038f + cloud * (0.085f + 0.03f * tint);
      o[0] = static_cast<uint8_t>(std::min(r, 1.0f) * 255.0f + 0.5f);
      o[1] = static_cast<uint8_t>(std::min(g, 1.0f) * 255.0f + 0.5f);
      o[2] = static_cast<uint8_t>(std::min(b, 1.0f) * 255.0f + 0.5f);
      o[3] = 255;
    }
  glGenTextures(1, &m_bgTex);
  glBindTexture(GL_TEXTURE_2D, m_bgTex);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, N, N, 0, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
  glBindTexture(GL_TEXTURE_2D, 0);
}

// Driver thread (or Start, before it runs): a new world.
void CScreensaverAlienLife::BeginWorld()
{
  alien::Params p = m_params;
  p.world = m_worldSetting == WS_RANDOM ? static_cast<int>(m_rng() % alien::WORLD_COUNT) : m_worldSetting - 1;
  m_worldKind = p.world;
  m_world.Reset(m_aspect, p, m_rng());
  static const float kZoom[] = {1.0f, 1.8f, 2.8f};
  m_zoom = kZoom[m_viewMode];
  m_camX = m_tgtX = m_world.width() * 0.5f;
  m_camY = m_tgtY = m_world.height() * 0.5f;
  m_camVX = m_camVY = 0.0f;
  m_camTimer = 0;
  m_followCr = -1;
  // open on the busiest place
  if (m_viewMode != VIEW_WHOLE)
  {
    MoveCamera(0);
    m_camX = m_tgtX;
    m_camY = m_tgtY;
  }
}

// Driver thread: aim the camera and move it `steps` steps towards its aim.
// Roaming picks one of the busiest places on the density map every half
// minute; following picks a creature (a big one near the action) and keeps
// it in the middle until it dies or 25 seconds have passed.
void CScreensaverAlienLife::MoveCamera(int steps)
{
  if (m_viewMode == VIEW_WHOLE)
    return;
  const alien::World& w = m_world;
  const float W = w.width(), H = w.height();
  auto dx = [&](float a, float b) {
    float d = b - a;
    return d > 0.5f * W ? d - W : (d < -0.5f * W ? d + W : d);
  };
  auto dy = [&](float a, float b) {
    float d = b - a;
    return d > 0.5f * H ? d - H : (d < -0.5f * H ? d + H : d);
  };

  m_camTimer -= steps;
  if (m_viewMode == VIEW_FOLLOW)
  {
    bool valid = m_followCr >= 0 && w.creature(m_followCr).alive && w.creature(m_followCr).id == m_followId &&
                 w.creature(m_followCr).built > 0;
    if (!valid || m_camTimer <= 0)
    {
      // a free creature of five cells or more, the closer to the camera the better
      int best = -1;
      float bestScore = -1.0f;
      const int n = static_cast<int>(w.capacity() / 2);
      std::uniform_real_distribution<float> jitter(0.0f, 1.0f);
      for (int i = 0; i < n; i++)
      {
        const alien::Creature& c = w.creature(i);
        if (!c.alive || c.parent >= 0 || c.built < 5 || i == m_followCr)
          continue;
        const int cell = c.cells[0];
        const float ex = dx(m_camX, w.x()[cell]), ey = dy(m_camY, w.y()[cell]);
        const float score = c.built * (0.5f + jitter(m_rng)) / (1.0f + std::sqrt(ex * ex + ey * ey) * 0.05f);
        if (score > bestScore)
        {
          bestScore = score;
          best = i;
        }
      }
      if (best >= 0)
      {
        m_followCr = best;
        m_followId = w.creature(best).id;
      }
      m_camTimer = 25 * 60;
      valid = best >= 0;
    }
    if (valid)
    {
      // the middle of the body
      const alien::Creature& c = w.creature(m_followCr);
      const int c0 = c.cells[0];
      float sx = 0, sy = 0;
      for (int k = 0; k < c.built; k++)
      {
        sx += dx(w.x()[c0], w.x()[c.cells[k]]);
        sy += dy(w.y()[c0], w.y()[c.cells[k]]);
      }
      m_tgtX = w.x()[c0] + sx / c.built;
      m_tgtY = w.y()[c0] + sy / c.built;
    }
  }
  else if (m_camTimer <= 0)
  {
    // one of the five busiest places of the (3 x 3 smoothed) density map
    const int dw = w.densityW(), dh = w.densityH();
    const uint16_t* d = w.density();
    int top[5] = {-1, -1, -1, -1, -1};
    int topV[5] = {0, 0, 0, 0, 0};
    for (int y = 0; y < dh; y++)
      for (int x = 0; x < dw; x++)
      {
        int v = 0;
        for (int oy = -1; oy <= 1; oy++)
          for (int ox = -1; ox <= 1; ox++)
            v += d[((y + oy + dh) % dh) * dw + (x + ox + dw) % dw];
        for (int t = 0; t < 5; t++)
          if (v > topV[t])
          {
            for (int u = 4; u > t; u--)
            {
              top[u] = top[u - 1];
              topV[u] = topV[u - 1];
            }
            top[t] = y * dw + x;
            topV[t] = v;
            break;
          }
      }
    int n = 0;
    while (n < 5 && top[n] >= 0)
      n++;
    if (n > 0)
    {
      const int pick = top[std::uniform_int_distribution<int>(0, n - 1)(m_rng)];
      m_tgtX = ((pick % dw) + 0.5f) * W / dw;
      m_tgtY = ((pick / dw) + 0.5f) * H / dh;
    }
    m_camTimer = 30 * 60;
  }

  // a critically damped spring, at most a fifth of the view a second
  const float omega = m_viewMode == VIEW_FOLLOW ? 0.035f : 0.012f;
  const float vmax = (H / m_zoom) * 0.2f / 60.0f;
  for (int s = 0; s < steps; s++)
  {
    const float ex = dx(m_camX, m_tgtX), ey = dy(m_camY, m_tgtY);
    m_camVX += omega * omega * ex - 2.0f * omega * m_camVX;
    m_camVY += omega * omega * ey - 2.0f * omega * m_camVY;
    const float v = std::sqrt(m_camVX * m_camVX + m_camVY * m_camVY);
    if (v > vmax)
    {
      m_camVX *= vmax / v;
      m_camVY *= vmax / v;
    }
    m_camX += m_camVX;
    m_camY += m_camVY;
    m_camX -= std::floor(m_camX / W) * W;
    m_camY -= std::floor(m_camY / H) * H;
  }
}

// Driver thread: the vertex streams for the step just done.
void CScreensaverAlienLife::BuildVertices()
{
  const alien::World& w = m_world;
  const size_t cap = w.capacity();
  const float W = w.width(), H = w.height();
  m_viewW = W / m_zoom;
  m_viewH = H / m_zoom;
  m_viewX = m_viewMode == VIEW_WHOLE ? W * 0.5f : m_camX;
  m_viewY = m_viewMode == VIEW_WHOLE ? H * 0.5f : m_camY;
  const float X0 = m_viewX, Y0 = m_viewY;
  const float halfW = 0.5f * W, halfH = 0.5f * H;
  const float limX = 0.5f * m_viewW + 3.0f, limY = 0.5f * m_viewH + 3.0f;

  const float* X = w.x();
  const float* Y = w.y();
  const uint8_t* S = w.state();
  const uint8_t* T = w.type();
  const uint8_t* C = w.colour();
  const uint8_t* F = w.flash();
  const uint16_t* TM = w.timer();
  const int* CR = w.creatureOf();

  // every cell relative to the camera, and whether it is near the view
  m_rx.resize(cap);
  m_ry.resize(cap);
  m_near.assign(cap, 0);
  m_cellColour.resize(cap);
  for (size_t i = 0; i < cap; i++)
  {
    if (S[i] == alien::CS_FREE)
      continue;
    float dx = X[i] - X0, dy = Y[i] - Y0;
    dx = dx > halfW ? dx - W : (dx < -halfW ? dx + W : dx);
    dy = dy > halfH ? dy - H : (dy < -halfH ? dy + H : dy);
    m_rx[i] = dx;
    m_ry[i] = dy;
    if (std::fabs(dx) > limX || std::fabs(dy) > limY)
      continue;
    m_near[i] = 1;

    // the cell's colour, reused by its connections and triangles
    RGB c;
    float k;
    if (S[i] == alien::CS_SOLID)
    {
      const float v = 0.85f + 0.3f * (TM[i] / 255.0f);
      m_cellColour[i] = {kRock.r * v, kRock.g * v, kRock.b * v};
      continue;
    }
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
    // eating, attacking and being built light a cell up (less so in the
    // organic look, where the bloom adds to it)
    const float f = F[i] / 255.0f * (m_style == STYLE_ORGANIC ? 0.3f : 0.5f);
    m_cellColour[i] = {std::min(c.r * k + f, 1.0f), std::min(c.g * k + f, 1.0f), std::min(c.b * k + f, 1.0f)};
  }

  if (m_style == STYLE_ORGANIC && m_organicOk)
    BuildOrganic();
  else
    BuildClassic();
  BuildEffects();
}

// Organic look: triangles between mutually connected cells, connections as
// quads, cells as sprites, energy particles as glows.
void CScreensaverAlienLife::BuildOrganic()
{
  const alien::World& w = m_world;
  const size_t cap = w.capacity();
  const float sx = 2.0f / m_viewW, sy = -2.0f / m_viewH;
  const uint8_t* S = w.state();
  const uint8_t* T = w.type();
  const uint8_t* F = w.flash();
  const uint8_t* BN = w.bondCount();
  const int* BT = w.bondTo();
  const float lineHalf = 0.30f * m_cellSize;

  m_tris.clear();
  m_cells.clear();
  auto bonded = [&](int a, int b) {
    for (int s = 0; s < BN[a]; s++)
      if (BT[static_cast<size_t>(a) * alien::MAX_BONDS + s] == b)
        return true;
    return false;
  };
  auto close = [&](size_t a, size_t b) {
    const float dx = m_rx[a] - m_rx[b], dy = m_ry[a] - m_ry[b];
    return dx * dx + dy * dy < 9.0f; // not across the wrap
  };
  auto vtx = [&](size_t i, float gain) {
    const RGB& c = m_cellColour[i];
    return Vertex{m_rx[i] * sx, m_ry[i] * sy, Pack(c.r * gain, c.g * gain, c.b * gain, 1.0f)};
  };

  for (size_t i = 0; i < cap; i++)
  {
    if (!m_near[i])
      continue;
    const int n = BN[i];
    const int* bt = &BT[i * alien::MAX_BONDS];
    // the membrane: each triangle once, from its lowest cell
    for (int a = 0; a < n; a++)
    {
      const int j = bt[a];
      if (static_cast<size_t>(j) <= i || !m_near[j] || !close(i, j))
        continue;
      for (int b = 0; b < n; b++)
      {
        const int kk = bt[b];
        if (kk <= j || !m_near[kk] || !close(i, kk) || !bonded(j, kk))
          continue;
        m_tris.push_back(vtx(i, 0.8f));
        m_tris.push_back(vtx(static_cast<size_t>(j), 0.8f));
        m_tris.push_back(vtx(static_cast<size_t>(kk), 0.8f));
      }
    }
    // connections as quads
    if (m_connections)
      for (int a = 0; a < n; a++)
      {
        const int j = bt[a];
        if (static_cast<size_t>(j) <= i || !m_near[j] || !close(i, j))
          continue;
        float dx = m_rx[j] - m_rx[i], dy = m_ry[j] - m_ry[i];
        const float l = std::sqrt(dx * dx + dy * dy);
        if (l < 1e-4f)
          continue;
        const float nx = -dy / l * lineHalf, ny = dx / l * lineHalf;
        Vertex a0 = vtx(i, 0.9f), b0 = vtx(static_cast<size_t>(j), 0.9f);
        Vertex a1 = a0, a2 = a0, b1 = b0, b2 = b0;
        a1.x += nx * sx;
        a1.y += ny * sy;
        a2.x -= nx * sx;
        a2.y -= ny * sy;
        b1.x += nx * sx;
        b1.y += ny * sy;
        b2.x -= nx * sx;
        b2.y -= ny * sy;
        m_tris.insert(m_tris.end(), {a1, a2, b1, b1, a2, b2});
      }
  }
  for (size_t i = 0; i < cap; i++)
  {
    if (!m_near[i])
      continue;
    const RGB& c = m_cellColour[i];
    float size;
    RGB nuc = c;
    float flash = 0.0f;
    if (S[i] == alien::CS_SOLID)
      size = 0.55f;
    else if (S[i] == alien::CS_DYING)
      size = 0.42f;
    else
    {
      size = 0.5f * kTypeSize[T[i]];
      if (T[i] != alien::CT_BASE)
        nuc = kTypeColours[T[i]];
      flash = F[i] / 255.0f * 0.6f;
    }
    m_cells.push_back({m_rx[i] * sx, m_ry[i] * sy, Pack(c, size), Pack(nuc, flash)});
  }

  m_glowPts.clear();
  if (m_showParticles)
  {
    const float W = w.width(), H = w.height(), halfW = 0.5f * W, halfH = 0.5f * H;
    const float limX = 0.5f * m_viewW + 1.0f, limY = 0.5f * m_viewH + 1.0f;
    const float* PX = w.px();
    const float* PY = w.py();
    const float* PE = w.pe();
    const int* PA = w.page();
    const float life = static_cast<float>(w.k.particleLife);
    const float full = 1.0f / w.k.particleEnergy;
    for (int i = 0; i < w.numParticles(); i++)
    {
      float dx = PX[i] - m_viewX, dy = PY[i] - m_viewY;
      dx = dx > halfW ? dx - W : (dx < -halfW ? dx + W : dx);
      dy = dy > halfH ? dy - H : (dy < -halfH ? dy + H : dy);
      if (std::fabs(dx) > limX || std::fabs(dy) > limY)
        continue;
      const float e = std::min(PE[i] * full, 1.5f);
      const float age = 1.0f - 0.65f * std::min(PA[i] / life, 1.0f);
      const float b = (0.55f + 0.2f * e) * age;
      m_glowPts.push_back({dx * sx, dy * sy, Pack(b, b * 0.82f, b * 0.5f, 0.11f + 0.02f * e)});
    }
  }
}

// Classic look: lines and glowing sprites, as in version 1.
void CScreensaverAlienLife::BuildClassic()
{
  const alien::World& w = m_world;
  const size_t cap = w.capacity();
  const float sx = 2.0f / m_viewW, sy = -2.0f / m_viewH;
  const uint8_t* S = w.state();
  const uint8_t* T = w.type();

  m_lines.clear();
  m_points.clear();
  if (m_connections)
  {
    const uint8_t* BN = w.bondCount();
    const int* BT = w.bondTo();
    for (size_t i = 0; i < cap; i++)
    {
      if (!m_near[i])
        continue;
      for (int s = 0; s < BN[i]; s++)
      {
        const int j = BT[i * alien::MAX_BONDS + s];
        if (static_cast<size_t>(j) < i || !m_near[j])
          continue;
        const float dx = m_rx[j] - m_rx[i], dy = m_ry[j] - m_ry[i];
        if (dx * dx + dy * dy > 9.0f)
          continue;
        m_lines.push_back({m_rx[i] * sx, m_ry[i] * sy, Pack(m_cellColour[i], 0.5f)});
        m_lines.push_back({m_rx[j] * sx, m_ry[j] * sy, Pack(m_cellColour[static_cast<size_t>(j)], 0.5f)});
      }
    }
  }
  if (m_showParticles)
  {
    const float W = w.width(), H = w.height(), halfW = 0.5f * W, halfH = 0.5f * H;
    const float* PX = w.px();
    const float* PY = w.py();
    const float* PE = w.pe();
    const int* PA = w.page();
    const float life = static_cast<float>(w.k.particleLife);
    const float full = 1.0f / w.k.particleEnergy;
    for (int i = 0; i < w.numParticles(); i++)
    {
      float dx = PX[i] - m_viewX, dy = PY[i] - m_viewY;
      dx = dx > halfW ? dx - W : (dx < -halfW ? dx + W : dx);
      dy = dy > halfH ? dy - H : (dy < -halfH ? dy + H : dy);
      if (std::fabs(dx) > 0.5f * m_viewW + 1.0f || std::fabs(dy) > 0.5f * m_viewH + 1.0f)
        continue;
      // warm sparks that dim as they age
      const float e = std::min(PE[i] * full, 1.5f);
      const float age = 1.0f - 0.6f * std::min(PA[i] / life, 1.0f);
      const float b = (0.28f + 0.18f * e) * age;
      m_points.push_back({dx * sx, dy * sy, Pack(b, b * 0.82f, b * 0.5f, 0.11f + 0.03f * e)});
    }
  }
  for (size_t i = 0; i < cap; i++)
  {
    if (!m_near[i])
      continue;
    const float size =
        S[i] == alien::CS_SOLID ? 0.5f : (S[i] == alien::CS_DYING ? 0.4f : 0.5f * kTypeSize[T[i]]);
    m_points.push_back({m_rx[i] * sx, m_ry[i] * sy, Pack(m_cellColour[i], size)});
  }
}

// Radiation sources and events, as glowing quads (both looks).
void CScreensaverAlienLife::BuildEffects()
{
  const alien::World& w = m_world;
  const float W = w.width(), H = w.height(), halfW = 0.5f * W, halfH = 0.5f * H;
  const float sx = 2.0f / m_viewW, sy = -2.0f / m_viewH;
  const bool organic = m_style == STYLE_ORGANIC && m_organicOk;
  m_fx.clear();
  auto rel = [&](float x, float y, float& rx, float& ry) {
    float dx = x - m_viewX, dy = y - m_viewY;
    rx = dx > halfW ? dx - W : (dx < -halfW ? dx + W : dx);
    ry = dy > halfH ? dy - H : (dy < -halfH ? dy + H : dy);
  };
  // a square of half size r round (x, y) relative to the camera; shape as kFxFS
  auto quad = [&](float x, float y, float r, float shape, const RGB& c, float a) {
    if (std::fabs(x) - r > 0.5f * m_viewW || std::fabs(y) - r > 0.5f * m_viewH || a <= 0.004f)
      return;
    const float x0 = (x - r) * sx, x1 = (x + r) * sx, y0 = (y - r) * sy, y1 = (y + r) * sy;
    const uint32_t col = Pack(c, a);
    const FxVertex v[6] = {{x0, y0, -1, -1, shape, col}, {x1, y0, 1, -1, shape, col}, {x0, y1, -1, 1, shape, col},
                           {x1, y0, 1, -1, shape, col},  {x1, y1, 1, 1, shape, col},  {x0, y1, -1, 1, shape, col}};
    m_fx.insert(m_fx.end(), v, v + 6);
  };
  auto beam = [&](float x0, float y0, float x1, float y1, float half, const RGB& c, float a) {
    float dx = x1 - x0, dy = y1 - y0;
    const float l = std::sqrt(dx * dx + dy * dy);
    if (l < 1e-3f || l > 6.0f || a <= 0.004f)
      return;
    const float nx = -dy / l * half, ny = dx / l * half;
    const uint32_t col = Pack(c, a);
    const FxVertex v[6] = {{(x0 + nx) * sx, (y0 + ny) * sy, 0, 1, 3, col}, {(x0 - nx) * sx, (y0 - ny) * sy, 0, -1, 3, col},
                           {(x1 + nx) * sx, (y1 + ny) * sy, 1, 1, 3, col}, {(x1 + nx) * sx, (y1 + ny) * sy, 1, 1, 3, col},
                           {(x0 - nx) * sx, (y0 - ny) * sy, 0, -1, 3, col}, {(x1 - nx) * sx, (y1 - ny) * sy, 1, -1, 3, col}};
    m_fx.insert(m_fx.end(), v, v + 6);
  };

  if (m_sourceGlow)
  {
    // a nebula round each radiation source, and a pulsing core; repeated
    // across the wrap where the view sees more than the world
    const float pulse = 0.85f + 0.15f * std::sin(static_cast<float>(w.steps()) * 0.02f);
    for (int s = 0; s < w.numSources(); s++)
    {
      float x, y;
      rel(w.source(s).x, w.source(s).y, x, y);
      for (int oy = -1; oy <= 1; oy++)
        for (int ox = -1; ox <= 1; ox++)
        {
          if (m_zoom > 1.0f && (ox || oy))
            continue;
          const float px = x + ox * W, py = y + oy * H;
          if (organic)
          {
            quad(px, py, 0.30f * H, 0, {0.32f, 0.26f, 0.70f}, 0.40f);
            quad(px, py, 0.12f * H, 0, {0.55f, 0.50f, 0.95f}, 0.30f * pulse);
            quad(px, py, 2.5f, 0, {1.0f, 0.92f, 0.75f}, 0.55f * pulse);
          }
          else
            quad(px, py, 0.22f * H, 0, {0.10f, 0.09f, 0.20f}, 1.0f);
        }
    }
  }

  m_fxSources = m_fx.size();
  if (!m_showEvents)
    return;
  for (const alien::Event& e : w.events())
  {
    const float t = static_cast<float>(e.age) / alien::kEventLife[e.kind];
    float x0, y0, x1, y1;
    rel(e.x0, e.y0, x0, y0);
    rel(e.x1, e.y1, x1, y1);
    // keep the far end on the same side of the wrap
    x1 = x0 + ((x1 - x0) > halfW ? x1 - x0 - W : ((x1 - x0) < -halfW ? x1 - x0 + W : x1 - x0));
    y1 = y0 + ((y1 - y0) > halfH ? y1 - y0 - H : ((y1 - y0) < -halfH ? y1 - y0 + H : y1 - y0));
    const RGB& c = kEventColour[e.kind];
    const float fade = 1.0f - t;
    switch (e.kind)
    {
      case alien::EV_ATTACK:
        beam(x0, y0, x1, y1, 0.45f, c, 0.9f * fade);
        quad(x1, y1, 1.4f, 0, {1.0f, 0.55f, 0.3f}, 0.7f * fade);
        break;
      case alien::EV_INJECT:
        beam(x0, y0, x1, y1, 0.55f, c, 0.9f * fade);
        quad(x1, y1, 1.0f + 4.0f * t, 1.0f + 0.8f, c, 0.8f * fade);
        break;
      case alien::EV_GRAB:
        beam(x0, y0, x1, y1, 0.3f, c, 0.7f * fade);
        break;
      case alien::EV_BLAST:
      {
        const float R = w.k.blastRadius;
        // a flash that fades fast and a shock wave that runs on to twice the radius
        quad(x0, y0, R * (0.5f + 0.6f * t), 0, {1.0f, 0.9f, 0.7f}, 1.2f * std::max(0.0f, 1.0f - 2.5f * t));
        const float rr = R * (0.3f + 1.9f * t);
        quad(x0, y0, rr / 0.9f, 1.0f + 0.9f, c, 0.85f * fade * fade);
        break;
      }
      case alien::EV_BIRTH:
      default:
        quad(x0, y0, (0.8f + 3.0f * t) / 0.9f, 1.0f + 0.9f, kGenomeColours[e.colour % alien::NUM_COLOURS],
             0.5f * fade);
        break;
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
    MoveCamera(n);
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
  m_maxPointSize = 256.0f;
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
  for (GLuint* b : {&m_vboTris, &m_vboCells, &m_vboGlow, &m_vboFx, &m_vboLines, &m_vboPoints})
    glGenBuffers(1, b);
  if (m_organicOk)
    BuildBackground();

  m_aspect = static_cast<float>(Width()) / static_cast<float>(std::max(1, Height()));

  // the first world is set up here, before the driver thread exists
  BeginWorld();
  m_world.Step();
  MoveCamera(1);
  BuildVertices();
  m_serial = 1;
  m_drawSerial = ~0u;
  m_fresh = true;
  m_sceneFresh = true;

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
  kodi::Log(ADDON_LOG_INFO,
            "Alien Life: %.0f x %.0f world, %d cells max, %d thread(s), %s look%s, first world %s",
            m_world.width(), m_world.height(), m_params.maxCells, m_pool.threads(),
            m_style == STYLE_ORGANIC && m_organicOk ? "organic" : "classic", m_halfRes ? " at half resolution" : "",
            kWorldNames[m_worldKind]);
  return true;
}

void CScreensaverAlienLife::Stop()
{
  StopSimulation();
  DeleteTrailBuffers();
  DeleteTargets();
  for (GLuint* b : {&m_vboTris, &m_vboCells, &m_vboGlow, &m_vboFx, &m_vboLines, &m_vboPoints, &m_quadVbo})
  {
    if (*b)
      glDeleteBuffers(1, b);
    *b = 0;
  }
  if (m_bgTex)
    glDeleteTextures(1, &m_bgTex);
  m_bgTex = 0;
#ifdef TARGET_DARWIN
  if (m_vao)
    glDeleteVertexArrays(1, &m_vao);
  m_vao = 0;
#endif
  for (Program* p : {&m_flat, &m_cell, &m_glow, &m_fxProg, &m_blur, &m_organic, &m_fade, &m_bright, &m_final})
  {
    if (p->id)
      glDeleteProgram(p->id);
    *p = Program();
  }
}

// Render thread, while the driver is idle: hand the GPU the last step.
void CScreensaverAlienLife::UploadFrame()
{
  auto up = [](GLuint vbo, const void* data, size_t bytes) {
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(bytes), bytes ? data : nullptr, GL_STREAM_DRAW);
  };
  up(m_vboTris, m_tris.data(), m_tris.size() * sizeof(Vertex));
  up(m_vboCells, m_cells.data(), m_cells.size() * sizeof(CellVertex));
  up(m_vboGlow, m_glowPts.data(), m_glowPts.size() * sizeof(Vertex));
  up(m_vboFx, m_fx.data(), m_fx.size() * sizeof(FxVertex));
  up(m_vboLines, m_lines.data(), m_lines.size() * sizeof(Vertex));
  up(m_vboPoints, m_points.data(), m_points.size() * sizeof(Vertex));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  m_drawTris = m_tris.size();
  m_drawCells = m_cells.size();
  m_drawGlow = m_glowPts.size();
  m_drawFx = m_fx.size();
  m_drawFxSources = m_fxSources;
  m_drawLines = m_lines.size();
  m_drawPoints = m_points.size();
  m_drawViewW = m_viewW;
  m_drawViewH = m_viewH;
  m_drawViewX = m_viewX;
  m_drawViewY = m_viewY;
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

// pixels per world unit of the target being drawn
float CScreensaverAlienLife::PointSizeScale() const
{
  GLint vp[4] = {0, 0, 1, 1};
  glGetIntegerv(GL_VIEWPORT, vp);
  return static_cast<float>(vp[3]) / m_drawViewH;
}

void CScreensaverAlienLife::DrawFlat(GLuint vbo, size_t count, float gain, GLenum mode)
{
  if (count == 0)
    return;
  glUseProgram(m_flat.id);
  glUniform1f(m_flat.uGain, gain);
  glUniform1f(m_flat.uAlpha, mode == GL_LINES ? 0.55f : 1.0f);
  glBindBuffer(GL_ARRAY_BUFFER, vbo);
  glEnableVertexAttribArray(static_cast<GLuint>(m_flat.aPos));
  glVertexAttribPointer(static_cast<GLuint>(m_flat.aPos), 2, GL_FLOAT, GL_FALSE, sizeof(Vertex), nullptr);
  glEnableVertexAttribArray(static_cast<GLuint>(m_flat.aCol));
  glVertexAttribPointer(static_cast<GLuint>(m_flat.aCol), 4, GL_UNSIGNED_BYTE, GL_TRUE, sizeof(Vertex),
                        reinterpret_cast<const void*>(2 * sizeof(float)));
  glDrawArrays(mode, 0, static_cast<GLsizei>(count));
  glDisableVertexAttribArray(static_cast<GLuint>(m_flat.aPos));
  glDisableVertexAttribArray(static_cast<GLuint>(m_flat.aCol));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
}

void CScreensaverAlienLife::DrawGlowPoints(GLuint vbo, size_t count, float gain, bool disc)
{
  if (count == 0)
    return;
#ifdef GL_PROGRAM_POINT_SIZE
  glEnable(GL_PROGRAM_POINT_SIZE);
#endif
  glUseProgram(m_glow.id);
  // a 0.5-size sprite's disc is one world unit across (the sprite reaches out twice as far)
  glUniform1f(m_glow.uPointSize, std::min(std::max(4.0f * m_cellSize * PointSizeScale(), 2.0f), m_maxPointSize));
  glUniform1f(m_glow.uGain, gain);
  glUniform1f(m_glow.uDisc, disc ? 1.0f : 0.0f);
  glUniform1f(m_glow.uHalo, m_bloom ? 0.32f : 0.0f);
  glBindBuffer(GL_ARRAY_BUFFER, vbo);
  glEnableVertexAttribArray(static_cast<GLuint>(m_glow.aPos));
  glVertexAttribPointer(static_cast<GLuint>(m_glow.aPos), 2, GL_FLOAT, GL_FALSE, sizeof(Vertex), nullptr);
  glEnableVertexAttribArray(static_cast<GLuint>(m_glow.aCol));
  glVertexAttribPointer(static_cast<GLuint>(m_glow.aCol), 4, GL_UNSIGNED_BYTE, GL_TRUE, sizeof(Vertex),
                        reinterpret_cast<const void*>(2 * sizeof(float)));
  glDrawArrays(GL_POINTS, 0, static_cast<GLsizei>(count));
  glDisableVertexAttribArray(static_cast<GLuint>(m_glow.aPos));
  glDisableVertexAttribArray(static_cast<GLuint>(m_glow.aCol));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
}

void CScreensaverAlienLife::DrawCells(float pointSize)
{
  if (m_drawCells == 0)
    return;
#ifdef GL_PROGRAM_POINT_SIZE
  glEnable(GL_PROGRAM_POINT_SIZE);
#endif
  glUseProgram(m_cell.id);
  glUniform1f(m_cell.uPointSize, pointSize);
  // the nucleus only once a cell is big enough to show it
  glUniform1f(m_cell.uNucleus, std::min(std::max((pointSize * 0.5f - 6.0f) / 8.0f, 0.0f), 1.0f));
  glBindBuffer(GL_ARRAY_BUFFER, m_vboCells);
  glEnableVertexAttribArray(static_cast<GLuint>(m_cell.aPos));
  glVertexAttribPointer(static_cast<GLuint>(m_cell.aPos), 2, GL_FLOAT, GL_FALSE, sizeof(CellVertex), nullptr);
  glEnableVertexAttribArray(static_cast<GLuint>(m_cell.aCol));
  glVertexAttribPointer(static_cast<GLuint>(m_cell.aCol), 4, GL_UNSIGNED_BYTE, GL_TRUE, sizeof(CellVertex),
                        reinterpret_cast<const void*>(2 * sizeof(float)));
  if (m_cell.aNuc >= 0)
  {
    glEnableVertexAttribArray(static_cast<GLuint>(m_cell.aNuc));
    glVertexAttribPointer(static_cast<GLuint>(m_cell.aNuc), 4, GL_UNSIGNED_BYTE, GL_TRUE, sizeof(CellVertex),
                          reinterpret_cast<const void*>(2 * sizeof(float) + sizeof(uint32_t)));
  }
  glDrawArrays(GL_POINTS, 0, static_cast<GLsizei>(m_drawCells));
  glDisableVertexAttribArray(static_cast<GLuint>(m_cell.aPos));
  glDisableVertexAttribArray(static_cast<GLuint>(m_cell.aCol));
  if (m_cell.aNuc >= 0)
    glDisableVertexAttribArray(static_cast<GLuint>(m_cell.aNuc));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
}

void CScreensaverAlienLife::DrawEffects(float gain, size_t first, size_t count)
{
  if (count == 0 || !m_fxProg.id)
    return;
  glUseProgram(m_fxProg.id);
  glUniform1f(m_fxProg.uGain, gain);
  glBindBuffer(GL_ARRAY_BUFFER, m_vboFx);
  glEnableVertexAttribArray(static_cast<GLuint>(m_fxProg.aPos));
  glVertexAttribPointer(static_cast<GLuint>(m_fxProg.aPos), 2, GL_FLOAT, GL_FALSE, sizeof(FxVertex), nullptr);
  glEnableVertexAttribArray(static_cast<GLuint>(m_fxProg.aFx));
  glVertexAttribPointer(static_cast<GLuint>(m_fxProg.aFx), 3, GL_FLOAT, GL_FALSE, sizeof(FxVertex),
                        reinterpret_cast<const void*>(2 * sizeof(float)));
  glEnableVertexAttribArray(static_cast<GLuint>(m_fxProg.aCol));
  glVertexAttribPointer(static_cast<GLuint>(m_fxProg.aCol), 4, GL_UNSIGNED_BYTE, GL_TRUE, sizeof(FxVertex),
                        reinterpret_cast<const void*>(5 * sizeof(float)));
  glDrawArrays(GL_TRIANGLES, static_cast<GLint>(first), static_cast<GLsizei>(count));
  glDisableVertexAttribArray(static_cast<GLuint>(m_fxProg.aPos));
  glDisableVertexAttribArray(static_cast<GLuint>(m_fxProg.aFx));
  glDisableVertexAttribArray(static_cast<GLuint>(m_fxProg.aCol));
  glBindBuffer(GL_ARRAY_BUFFER, 0);
}

// Classic look: sources (unless they are drawn later), events, connections,
// then particles and cells, all into the bound target.
void CScreensaverAlienLife::DrawClassic(float fade, bool sources)
{
  glEnable(GL_BLEND);
  glBlendFunc(GL_ONE, GL_ONE);
  if (sources)
    DrawEffects(fade, 0, m_drawFx);
  else
    DrawEffects(fade, m_drawFxSources, m_drawFx - m_drawFxSources);
  if (m_bloom)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
  else
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
  DrawFlat(m_vboLines, m_drawLines, fade, GL_LINES);
  DrawGlowPoints(m_vboPoints, m_drawPoints, fade, true);
}

bool CScreensaverAlienLife::MakeTarget(Target& t, int w, int h)
{
  glGenTextures(1, &t.tex);
  glBindTexture(GL_TEXTURE_2D, t.tex);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
  glGenFramebuffers(1, &t.fbo);
  glBindFramebuffer(GL_FRAMEBUFFER, t.fbo);
  glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, t.tex, 0);
  const bool ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
  if (ok)
  {
    glViewport(0, 0, w, h);
    glClearColor(0, 0, 0, 0);
    glClear(GL_COLOR_BUFFER_BIT);
  }
  t.w = w;
  t.h = h;
  return ok;
}

void CScreensaverAlienLife::DeleteTarget(Target& t)
{
  if (t.fbo)
    glDeleteFramebuffers(1, &t.fbo);
  if (t.tex)
    glDeleteTextures(1, &t.tex);
  t = Target();
}

bool CScreensaverAlienLife::EnsureTargets(int w, int h)
{
  if (m_targetsFailed)
    return false;
  if (m_body.fbo && w == m_targetW && h == m_targetH)
    return true;
  DeleteTargets();
  GLint prevFbo = 0;
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prevFbo);
  const int sw = m_halfRes ? std::max(w / 2, 16) : w, sh = m_halfRes ? std::max(h / 2, 16) : h;
  const int b1w = std::max(sw / 2, 8), b1h = std::max(sh / 2, 8);
  const int b2w = std::max(b1w / 2, 4), b2h = std::max(b1h / 2, 4);
  bool ok = MakeTarget(m_body, sw, sh) && MakeTarget(m_bodyTmp, sw, sh) && MakeTarget(m_scene[0], sw, sh) &&
            MakeTarget(m_scene[1], sw, sh) && MakeTarget(m_bloomA, b1w, b1h) && MakeTarget(m_bloomB, b1w, b1h) &&
            MakeTarget(m_bloomC, b2w, b2h) && MakeTarget(m_bloomD, b2w, b2h);
  glBindTexture(GL_TEXTURE_2D, 0);
  glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(prevFbo));
  if (!ok)
  {
    kodi::Log(ADDON_LOG_ERROR, "Alien Life: off-screen targets incomplete; drawing the classic look");
    DeleteTargets();
    m_targetsFailed = true;
    m_organicOk = false; // the driver builds the classic streams from now on
    return false;
  }
  m_targetW = w;
  m_targetH = h;
  m_sceneFresh = true;
  return true;
}

void CScreensaverAlienLife::DeleteTargets()
{
  for (Target* t : {&m_body, &m_bodyTmp, &m_scene[0], &m_scene[1], &m_bloomA, &m_bloomB, &m_bloomC, &m_bloomD})
    DeleteTarget(*t);
  m_targetW = m_targetH = 0;
}

void CScreensaverAlienLife::Bind(const Target& t)
{
  glBindFramebuffer(GL_FRAMEBUFFER, t.fbo);
  glViewport(0, 0, t.w, t.h);
}

// src -> tmp horizontally, tmp -> src vertically; radius in src pixels
void CScreensaverAlienLife::Blur(Target& src, Target& tmp, float radius)
{
  glDisable(GL_BLEND);
  glUseProgram(m_blur.id);
  glUniform1i(m_blur.uTex, 0);
  glActiveTexture(GL_TEXTURE0);
  Bind(tmp);
  glBindTexture(GL_TEXTURE_2D, src.tex);
  glUniform2f(m_blur.uStep, radius / 3.23f / src.w, 0.0f);
  DrawQuad(m_blur.aPos);
  Bind(src);
  glBindTexture(GL_TEXTURE_2D, tmp.tex);
  glUniform2f(m_blur.uStep, 0.0f, radius / 3.23f / src.h);
  DrawQuad(m_blur.aPos);
  glBindTexture(GL_TEXTURE_2D, 0);
}

// The organic look, from the bodies to the picture in the bound framebuffer.
void CScreensaverAlienLife::RenderOrganic(float bright)
{
  GLint screenFbo = 0;
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &screenFbo);
  const GLboolean scissor = glIsEnabled(GL_SCISSOR_TEST);
  glDisable(GL_SCISSOR_TEST);
  glActiveTexture(GL_TEXTURE0);

  const float pxPerUnit = static_cast<float>(m_body.h) / m_drawViewH;

  // 1. bodies: membranes and connections, then the cells on top
  Bind(m_body);
  glClearColor(0, 0, 0, 0);
  glClear(GL_COLOR_BUFFER_BIT);
  glDisable(GL_BLEND);
  DrawFlat(m_vboTris, m_drawTris, 1.0f, GL_TRIANGLES);
  DrawCells(std::min(std::max(1.25f * m_cellSize * pxPerUnit, 2.0f), m_maxPointSize));

  // 2. soften, so neighbouring cells fuse
  Blur(m_body, m_bodyTmp, std::max(0.2f * pxPerUnit, 1.0f));

  // 3. the scene: the faded last scene (trails) or black, the organic
  //    surface over it, then everything that glows
  const int prev = m_sceneCur, cur = 1 - m_sceneCur;
  Bind(m_scene[cur]);
  const bool trails = m_trails > 0 && !m_sceneFresh;
  if (trails)
  {
    glUseProgram(m_fade.id);
    glBindTexture(GL_TEXTURE_2D, m_scene[prev].tex);
    glUniform1i(m_fade.uTex, 0);
    glUniform1f(m_fade.uKeep, kTrailKeep[m_trails]);
    glUniform1f(m_fade.uSub, kTrailSub);
    DrawQuad(m_fade.aPos);
  }
  else
  {
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
  }
  m_sceneFresh = false;
  glEnable(GL_BLEND);
  glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
  glUseProgram(m_organic.id);
  glBindTexture(GL_TEXTURE_2D, m_body.tex);
  glUniform1i(m_organic.uTex, 0);
  glUniform2f(m_organic.uTexel, 1.0f / m_body.w, 1.0f / m_body.h);
  glUniform1f(m_organic.uR1, std::max(0.22f * pxPerUnit, 1.0f));
  glUniform1f(m_organic.uR2, std::max(0.7f * pxPerUnit, 2.0f));
  glUniform1f(m_organic.uRelief, 3.5f);
  DrawQuad(m_organic.aPos);
  glBindTexture(GL_TEXTURE_2D, 0);
  glBlendFunc(GL_ONE, GL_ONE);
  // the sources stay out of the trails (they are added to the picture at the end)
  const float glowGain = trails ? 1.0f - kTrailKeep[m_trails] : 1.0f;
  if (m_trails > 0)
    DrawEffects(glowGain, m_drawFxSources, m_drawFx - m_drawFxSources);
  else
    DrawEffects(1.0f, 0, m_drawFx);
  DrawGlowPoints(m_vboGlow, m_drawGlow, glowGain, false);
  m_sceneCur = cur;

  // 4. bloom: the bright parts at half and quarter size, blurred
  Target& scene = m_scene[cur];
  glDisable(GL_BLEND);
  if (m_bloom)
  {
    glUseProgram(m_bright.id);
    glUniform1i(m_bright.uTex, 0);
    Bind(m_bloomA);
    glBindTexture(GL_TEXTURE_2D, scene.tex);
    glUniform2f(m_bright.uTexel, 0.5f / scene.w, 0.5f / scene.h);
    glUniform1f(m_bright.uThreshold, 0.55f);
    DrawQuad(m_bright.aPos);
    Blur(m_bloomA, m_bloomB, 4.0f);
    glUseProgram(m_bright.id);
    Bind(m_bloomC);
    glBindTexture(GL_TEXTURE_2D, m_bloomA.tex);
    glUniform2f(m_bright.uTexel, 0.5f / m_bloomA.w, 0.5f / m_bloomA.h);
    glUniform1f(m_bright.uThreshold, 0.0f);
    DrawQuad(m_bright.aPos);
    Blur(m_bloomC, m_bloomD, 6.0f);
  }

  // 5. the picture
  glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(screenFbo));
  if (scissor)
    glEnable(GL_SCISSOR_TEST);
  glViewport(X(), Y(), Width(), Height());
  glUseProgram(m_final.id);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, scene.tex);
  glActiveTexture(GL_TEXTURE1);
  glBindTexture(GL_TEXTURE_2D, m_bloomA.tex);
  glActiveTexture(GL_TEXTURE2);
  glBindTexture(GL_TEXTURE_2D, m_bloomC.tex);
  glActiveTexture(GL_TEXTURE3);
  glBindTexture(GL_TEXTURE_2D, m_bgTex);
  glUniform1i(m_final.uScene, 0);
  glUniform1i(m_final.uBloom1, 1);
  glUniform1i(m_final.uBloom2, 2);
  glUniform1i(m_final.uBg, 3);
  // the nebula drifts at half the camera's pace, one tile per 300 world units
  const float tile = 300.0f;
  glUniform2f(m_final.uBgScale, m_drawViewW / tile * 0.5f, m_drawViewH / tile * 0.5f);
  glUniform2f(m_final.uBgOffset, (m_drawViewX - 0.5f * m_drawViewW) / tile * 0.5f,
              -(m_drawViewY - 0.5f * m_drawViewH) / tile * 0.5f);
  glUniform1f(m_final.uBloom, m_bloom ? 1.0f : 0.0f);
  glUniform1f(m_final.uBright, bright);
  DrawQuad(m_final.aPos);
  for (int t = 3; t >= 0; t--)
  {
    glActiveTexture(GL_TEXTURE0 + t);
    glBindTexture(GL_TEXTURE_2D, 0);
  }
  if (m_trails > 0)
  {
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);
    DrawEffects(bright, 0, m_drawFxSources);
  }
}

bool CScreensaverAlienLife::EnsureTrailBuffers(int w, int h)
{
  if (m_fadeFailed || !m_fade.id)
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
  if (!m_flat.id)
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
        m_sceneFresh = true;
        kodi::Log(ADDON_LOG_INFO, "Alien Life: new world, %s", kWorldNames[m_worldKind]);
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
                "Alien Life: %.2f ms per step, %.1f steps/s, %.1f frames/s (%zu triangles, %zu cells, %zu fx "
                "vertices, %d thread(s))",
                ms / count, count / statsAge, m_frames / statsAge, m_drawTris / 3, m_drawCells + m_drawPoints,
                m_drawFx, m_pool.threads());
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

  // (the streams of the step just uploaded are organic ones only while m_organicOk held)
  const bool organic = m_style == STYLE_ORGANIC && m_organicOk && EnsureTargets(Width(), Height());
  if (pending)
  {
    glViewport(X(), Y(), Width(), Height());
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
  }
  else if (organic)
    RenderOrganic(bright);
  else if (m_trails > 0 && EnsureTrailBuffers(Width(), Height()))
  {
    GLint screenFbo = 0;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &screenFbo);
    const GLboolean scissor = glIsEnabled(GL_SCISSOR_TEST);
    glDisable(GL_SCISSOR_TEST);

    const int prev = m_fadeCur, cur = 1 - m_fadeCur;
    glBindFramebuffer(GL_FRAMEBUFFER, m_fadeFbo[cur]);
    glViewport(0, 0, m_fadeW, m_fadeH);
    glDisable(GL_BLEND);
    glUseProgram(m_fade.id);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, m_fadeTex[prev]);
    glUniform1i(m_fade.uTex, 0);
    glUniform1f(m_fade.uKeep, kTrailKeep[m_trails]);
    glUniform1f(m_fade.uSub, kTrailSub);
    DrawQuad(m_fade.aPos);
    glBindTexture(GL_TEXTURE_2D, 0);
    DrawClassic(1.0f - kTrailKeep[m_trails], false);

    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(screenFbo));
    if (scissor)
      glEnable(GL_SCISSOR_TEST);
    glViewport(X(), Y(), Width(), Height());
    glDisable(GL_BLEND);
    glUseProgram(m_fade.id);
    glBindTexture(GL_TEXTURE_2D, m_fadeTex[cur]);
    glUniform1f(m_fade.uKeep, bright);
    glUniform1f(m_fade.uSub, 0.0f);
    DrawQuad(m_fade.aPos);
    glBindTexture(GL_TEXTURE_2D, 0);
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);
    DrawEffects(bright, 0, m_drawFxSources);
    m_fadeCur = cur;
  }
  else
  {
    glViewport(X(), Y(), Width(), Height());
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    DrawClassic(bright, true);
  }

  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
#ifdef TARGET_DARWIN
  glBindVertexArray(0);
#endif
  glUseProgram(0);
}

ADDONCREATOR(CScreensaverAlienLife)

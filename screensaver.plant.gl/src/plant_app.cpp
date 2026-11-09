#include "plant_app.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

#include "gl_util.hpp"
#include "twol/random.hpp"

namespace plantgl {
namespace {

using twol::Vec3;

constexpr float kPi = twol::pi;
constexpr int kParticleCapacity = 160;

float clampf(const float v, const float lo, const float hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

float smooth01(const float x) {
  const float t = clampf(x, 0.0f, 1.0f);
  return t * t * (3.0f - 2.0f * t);
}

Mat4 perspective(const float fovy, const float aspect, const float z_near, const float z_far) {
  const float f = 1.0f / std::tan(fovy * 0.5f);
  Mat4 r;
  r.m[0] = f / std::max(0.05f, aspect);
  r.m[5] = f;
  r.m[10] = (z_far + z_near) / (z_near - z_far);
  r.m[11] = -1.0f;
  r.m[14] = (2.0f * z_far * z_near) / (z_near - z_far);
  return r;
}

Mat4 look_at(const Vec3 eye, const Vec3 center, const Vec3 up) {
  const Vec3 f = twol::safe_normalize(center - eye, Vec3{0.0f, 0.0f, -1.0f});
  const Vec3 s = twol::safe_normalize(twol::cross(f, up), Vec3{1.0f, 0.0f, 0.0f});
  const Vec3 u = twol::cross(s, f);
  Mat4 r;
  r.m[0] = s.x;
  r.m[1] = u.x;
  r.m[2] = -f.x;
  r.m[4] = s.y;
  r.m[5] = u.y;
  r.m[6] = -f.y;
  r.m[8] = s.z;
  r.m[9] = u.z;
  r.m[10] = -f.z;
  r.m[12] = -twol::dot(s, eye);
  r.m[13] = -twol::dot(u, eye);
  r.m[14] = twol::dot(f, eye);
  r.m[15] = 1.0f;
  return r;
}

Mat4 multiply(const Mat4& a, const Mat4& b) {
  Mat4 r;
  for (int c = 0; c < 4; ++c) {
    for (int row = 0; row < 4; ++row) {
      float sum = 0.0f;
      for (int k = 0; k < 4; ++k) sum += a.m[k * 4 + row] * b.m[c * 4 + k];
      r.m[c * 4 + row] = sum;
    }
  }
  return r;
}

bool project_point(const Mat4& vp, const Vec3 p, float* out_x, float* out_y) {
  const float x = vp.m[0] * p.x + vp.m[4] * p.y + vp.m[8] * p.z + vp.m[12];
  const float y = vp.m[1] * p.x + vp.m[5] * p.y + vp.m[9] * p.z + vp.m[13];
  const float w = vp.m[3] * p.x + vp.m[7] * p.y + vp.m[11] * p.z + vp.m[15];
  if (w <= 0.0001f) return false;
  *out_x = x / w;
  *out_y = y / w;
  return true;
}

// ---------------------------------------------------------------------------------------------
// Shaders. Deliberately plain: attributes, varyings, one directional light, procedural sky. The
// growth itself lives in the vertex shader, so a plant is one static upload that animates.

const char* const kSceneVertex = R"glsl(
attribute vec3 a_pos;
attribute vec3 a_normal;
attribute vec3 a_color;
attribute vec3 a_anchor;
attribute vec2 a_growth;   // birth, span in time01 units
attribute vec2 a_sway;     // amount, phase
uniform mat4 u_viewProj;
uniform float u_time01;
uniform float u_time;
uniform float u_wind;
varying vec3 v_world;
varying vec3 v_normal;
varying vec3 v_color;
void main() {
  float span = max(a_growth.y, 0.0005);
  float g = clamp((u_time01 - a_growth.x) / span, 0.0, 1.0);
  g = g * g * (3.0 - 2.0 * g);
  vec3 p = mix(a_anchor, a_pos, g);
  float phase = a_sway.y * 6.2831853;
  float amp = a_sway.x * u_wind * g;
  p.x += (sin(phase + u_time * 1.7) + 0.4 * sin(phase * 2.3 + u_time * 2.9)) * amp;
  p.z += (cos(phase * 0.8 + u_time * 1.3) + 0.4 * cos(phase * 1.9 + u_time * 2.2)) * amp;
  p.y += sin(phase * 1.3 + u_time * 2.1) * amp * 0.35;
  v_world = p;
  v_normal = a_normal;
  v_color = a_color;
  gl_Position = u_viewProj * vec4(p, 1.0);
}
)glsl";

const char* const kSceneFragment = R"glsl(
varying vec3 v_world;
varying vec3 v_normal;
varying vec3 v_color;
uniform vec3 u_camPos;
uniform vec3 u_lightDir;
uniform vec3 u_ambient;
uniform vec3 u_sunColor;
uniform vec3 u_rimColor;
uniform float u_emissive;
void main() {
  vec3 n = normalize(v_normal);
  if (!gl_FrontFacing) n = -n;
  vec3 l = normalize(u_lightDir);
  vec3 v = normalize(u_camPos - v_world);
  float diff = max(dot(n, l), 0.0);
  float wrap = dot(n, l) * 0.5 + 0.5;
  float back = max(dot(-n, l), 0.0);
  vec3 col = v_color * (u_ambient + u_sunColor * (diff * 0.72 + wrap * 0.13));
  col += v_color * u_sunColor * back * 0.28;
  float rim = pow(1.0 - max(dot(n, v), 0.0), 3.0);
  col += u_rimColor * rim * 0.30;
  col = mix(col, v_color * 1.55 + u_rimColor * 0.20, u_emissive);
  // Gentle highlight compression: leaves otherwise clip to neon where the sun hits them.
  col = col / (1.0 + 0.20 * max(col, vec3(0.0)));
  gl_FragColor = vec4(col, 1.0);
}
)glsl";

const char* const kBackgroundFragment = R"glsl(
varying vec2 v_uv;
uniform vec3 u_zenith;
uniform vec3 u_horizon;
uniform vec3 u_glow;
uniform vec3 u_cloudColor;
uniform vec3 u_sunColor;
uniform float u_cloudAmount;
uniform float u_starAmount;
uniform float u_auroraAmount;
uniform float u_studioAmount;
uniform float u_sunSize;
uniform float u_sunVisible;
uniform vec2 u_sunUv;
uniform float u_time;
uniform float u_aspect;
uniform vec2 u_resolution;
uniform float u_effects;
float hash21(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}
float vnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 3; i++) {
    v += a * vnoise(p);
    p = p * 2.03 + vec2(13.7, 7.1);
    a *= 0.5;
  }
  return v;
}
void main() {
  vec2 uv = v_uv;
  float t = u_time;
  vec2 asp = vec2(u_aspect, 1.0);
  vec3 col = mix(u_horizon, u_zenith, pow(clamp(uv.y, 0.0, 1.0), 0.72));
  float band = exp(-pow((uv.y - 0.20) * 4.2, 2.0));
  col = mix(col, u_glow, band * 0.30);
  vec2 sun_delta = (uv - u_sunUv) * asp;
  float sd = length(sun_delta);
  float glow = exp(-sd * 7.0) * 0.55 + exp(-sd * 2.6) * 0.18;
  col += u_sunColor * glow * u_sunVisible;
  float disc = 1.0 - smoothstep(u_sunSize * 0.80, max(u_sunSize, 0.0001), sd);
  col += u_sunColor * disc * u_sunVisible * 0.85;
  float spot = exp(-length((uv - vec2(0.5, 0.66)) * asp) * 3.4);
  col += u_glow * spot * u_studioAmount * 0.32;
  // The 3-octave cloud noise and the grain are the expensive parts of the sky pass; Low detail
  // skips them. Stars and the aurora are one hash each and keep the night skies recognisable.
  if (u_effects > 0.5 && u_cloudAmount > 0.001) {
    float n = fbm(uv * vec2(u_aspect * 2.2, 2.0) + vec2(t * 0.006, 0.0));
    float cm = smoothstep(0.50, 0.82, n) * smoothstep(0.10, 0.55, uv.y) *
               (1.0 - smoothstep(0.72, 1.0, uv.y));
    col = mix(col, u_cloudColor, cm * u_cloudAmount);
  }
  if (u_starAmount > 0.001) {
    vec2 star_uv = uv * vec2(u_aspect * 260.0, 260.0);
    vec2 star_cell = floor(star_uv);
    vec2 star_f = fract(star_uv) - 0.5;
    float sh = hash21(star_cell);
    float star = step(0.9970, sh) * smoothstep(0.45, 0.05, length(star_f)) *
                 smoothstep(0.20, 0.45, uv.y);
    float tw = 0.55 + 0.45 * sin(t * 2.0 + sh * 120.0);
    col += vec3(0.80, 0.89, 1.0) * star * tw * u_starAmount * 0.90;
  }
  if (u_auroraAmount > 0.001) {
    float an = vnoise(vec2(uv.x * 2.6 * u_aspect + t * 0.012, t * 0.020));
    // Curtain-like ribbons rather than blobs: narrow horizontal bands hung at a shared height.
    float band1 = pow(max(sin(uv.x * 4.4 * u_aspect + an * 5.0 + t * 0.050), 0.0), 4.0);
    float band2 =
        pow(max(sin(uv.x * 7.9 * u_aspect - an * 3.0 + t * 0.032 + 1.7), 0.0), 6.0);
    float curtain_y = 0.58 + 0.05 * sin(uv.x * 2.8 * u_aspect + an * 2.0 + t * 0.04);
    float am = exp(-pow((uv.y - curtain_y) * 4.4, 2.0)) * smoothstep(0.18, 0.42, uv.y);
    col += mix(vec3(0.08, 0.85, 0.50), vec3(0.42, 0.18, 0.90), an) *
           (band1 * 0.75 + band2 * 0.45) * am * u_auroraAmount * 0.85;
  }
  vec2 vp = (uv - 0.5) * asp;
  col *= 1.0 - 0.30 * pow(clamp(length(vp) * 0.85, 0.0, 1.0), 1.8);
  if (u_effects > 0.5) {
    col += (hash21(uv * u_resolution + vec2(t * 3.1, t * 1.7)) - 0.5) / 255.0;
  }
  gl_FragColor = vec4(col, 1.0);
}
)glsl";

const char* const kGroundVertex = R"glsl(
attribute vec3 a_pos;
attribute float a_radius;
uniform mat4 u_viewProj;
uniform float u_groundRadius;
varying float v_radius;
void main() {
  vec3 p = vec3(a_pos.x * u_groundRadius, a_pos.y, a_pos.z * u_groundRadius);
  v_radius = a_radius;
  gl_Position = u_viewProj * vec4(p, 1.0);
}
)glsl";

const char* const kGroundFragment = R"glsl(
varying float v_radius;
uniform vec3 u_groundColor;
uniform vec3 u_glowColor;
uniform float u_shadow;
uniform float u_time;
void main() {
  float r = clamp(v_radius, 0.0, 1.0);
  vec3 col = mix(u_groundColor, u_glowColor, 0.06 + 0.07 * sin(u_time * 0.23));
  float broad = exp(-r * r * 4.0) * u_shadow;
  float contact = exp(-r * r * 26.0) * u_shadow;
  // A faint pool of light around the stem sells the ground, then a tight contact shadow.
  col += u_glowColor * exp(-r * r * 9.0) * 0.10;
  col *= 1.0 - 0.38 * broad - 0.34 * contact;
  float edge = 1.0 - smoothstep(0.42, 1.0, r);
  gl_FragColor = vec4(col, edge * (0.78 - 0.26 * broad));
}
)glsl";

const char* const kParticleVertex = R"glsl(
attribute vec3 a_pos;
attribute vec2 a_param;
uniform mat4 u_viewProj;
uniform float u_time;
uniform float u_pointScale;
uniform float u_particleRadius;
uniform float u_particleHeight;
uniform float u_particleAmp;
varying float v_alpha;
void main() {
  vec3 p = vec3(a_pos.x * u_particleRadius, a_pos.y * u_particleHeight,
                a_pos.z * u_particleRadius);
  p.x += sin(u_time * 0.23 + a_param.x * 6.2831853) * u_particleAmp;
  p.y += sin(u_time * 0.19 + a_param.x * 9.0) * u_particleAmp * 0.7;
  p.z += cos(u_time * 0.21 + a_param.x * 4.0) * u_particleAmp;
  vec4 clip = u_viewProj * vec4(p, 1.0);
  gl_Position = clip;
  float size = clamp((52.0 * a_param.y) / max(clip.w, 0.25), 1.0, 7.0);
  gl_PointSize = size * u_pointScale;
  v_alpha = clamp(0.10 + 0.30 * a_param.y, 0.0, 1.0);
}
)glsl";

const char* const kParticleFragment = R"glsl(
varying float v_alpha;
uniform vec3 u_color;
void main() {
  float d = length(gl_PointCoord - vec2(0.5));
  float a = smoothstep(0.5, 0.0, d);
  gl_FragColor = vec4(u_color * a * v_alpha, a * v_alpha);
}
)glsl";

const char* const kOverlayFragment = R"glsl(
uniform float u_alpha;
void main() { gl_FragColor = vec4(0.0, 0.0, 0.0, u_alpha); }
)glsl";

const char* const kSceneAttributes[] = {"a_pos",  "a_normal", "a_color",
                                        "a_anchor", "a_growth", "a_sway"};
const char* const kGroundAttributes[] = {"a_pos", "a_radius"};
const char* const kParticleAttributes[] = {"a_pos", "a_param"};
const char* const kQuadAttribute[] = {"a0"};

// Background indices: 1 dawn, 2 meadow, 3 dusk, 4 night, 5 studio, 6 aurora.
const Look kLooks[6] = {
    // Dawn: a warm sun low over the horizon.
    {{0.075f, 0.105f, 0.245f}, {1.00f, 0.66f, 0.46f}, {1.00f, 0.78f, 0.52f},
     {0.98f, 0.78f, 0.72f},    {1.00f, 0.68f, 0.42f}, {0.34f, 0.30f, 0.38f},
     {1.00f, 0.58f, 0.36f},    {0.25f, 0.155f, 0.125f}, {1.00f, 0.84f, 0.58f},
     0.55f, 0.00f, 0.00f, 0.00f, 0.055f, 1.00f, {0.55f, 0.26f, 0.80f}},
    // Meadow: high blue sky and a small hot sun.
    {{0.20f, 0.48f, 0.86f}, {0.78f, 0.90f, 0.94f}, {1.00f, 0.96f, 0.78f},
     {1.00f, 1.00f, 1.00f}, {1.00f, 0.96f, 0.82f}, {0.44f, 0.48f, 0.50f},
     {0.86f, 0.95f, 1.00f}, {0.22f, 0.33f, 0.16f}, {0.96f, 1.00f, 0.80f},
     0.48f, 0.00f, 0.00f, 0.00f, 0.040f, 1.00f, {0.42f, 0.82f, 0.38f}},
    // Dusk: deep red horizon, a low sun.
    {{0.035f, 0.045f, 0.16f}, {0.90f, 0.36f, 0.30f}, {1.00f, 0.48f, 0.28f},
     {0.72f, 0.44f, 0.50f},   {1.00f, 0.52f, 0.26f}, {0.22f, 0.20f, 0.30f},
     {0.95f, 0.45f, 0.40f},   {0.12f, 0.08f, 0.10f}, {1.00f, 0.60f, 0.42f},
     0.62f, 0.06f, 0.00f, 0.00f, 0.075f, 1.00f, {-0.62f, 0.20f, 0.76f}},
    // Night: moon, stars, a faint blue wash.
    {{0.008f, 0.012f, 0.045f}, {0.06f, 0.10f, 0.20f}, {0.20f, 0.34f, 0.55f},
     {0.12f, 0.18f, 0.28f},    {0.72f, 0.82f, 1.00f}, {0.10f, 0.13f, 0.24f},
     {0.42f, 0.62f, 1.00f},    {0.025f, 0.035f, 0.05f}, {0.65f, 0.80f, 1.00f},
     0.26f, 1.00f, 0.00f, 0.00f, 0.045f, 1.00f, {0.28f, 0.66f, -0.70f}},
    // Studio: a dark cyclorama with a warm key light, for the L-system pieces.
    {{0.045f, 0.040f, 0.040f}, {0.14f, 0.12f, 0.11f}, {1.00f, 0.82f, 0.58f},
     {0.40f, 0.35f, 0.32f},    {1.00f, 0.86f, 0.62f}, {0.30f, 0.28f, 0.25f},
     {1.00f, 0.77f, 0.44f},    {0.16f, 0.13f, 0.12f}, {1.00f, 0.82f, 0.48f},
     0.00f, 0.00f, 0.00f, 1.00f, 0.000f, 0.00f, {0.28f, 0.92f, 0.30f}},
    // Aurora: green ribbons over a cold sky.
    {{0.005f, 0.015f, 0.035f}, {0.03f, 0.10f, 0.12f}, {0.10f, 0.32f, 0.28f},
     {0.06f, 0.12f, 0.14f},    {0.55f, 0.80f, 1.00f}, {0.12f, 0.17f, 0.22f},
     {0.25f, 0.95f, 0.65f},    {0.02f, 0.045f, 0.05f}, {0.55f, 1.00f, 0.78f},
     0.20f, 0.85f, 1.00f, 0.00f, 0.030f, 0.00f, {0.45f, 0.50f, 0.74f}},
};

const int kPresetOrder[6] = {1, 4, 2, 3, 1, 5};
const int kSkyOrder[6] = {1, 2, 3, 4, 6, 5};
const int kDarkSkyOrder[4] = {4, 5, 6, 3};
const int kMotionOrder[4] = {1, 2, 3, 4};

// Background index 7: no sky pass at all. The plant is lit against a flat dark backdrop, which
// is the cheapest option for low-power boxes and reads well on a TV in a dark room.
const Look kFlatLook = {
    {0.018f, 0.020f, 0.028f}, {0.018f, 0.020f, 0.028f}, {0.55f, 0.60f, 0.70f},
    {0.0f, 0.0f, 0.0f},       {1.00f, 0.94f, 0.82f},     {0.34f, 0.36f, 0.42f},
    {0.72f, 0.82f, 1.00f},    {0.035f, 0.040f, 0.048f},  {0.80f, 0.86f, 1.00f},
    0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, {0.35f, 0.75f, 0.45f}};

twol::PlantPreset preset_enum(const int index) {
  switch (index) {
    case 1: return twol::PlantPreset::Tree;
    case 2: return twol::PlantPreset::Bush;
    case 3: return twol::PlantPreset::Fern;
    case 4: return twol::PlantPreset::Cannabis;
    case 5: return twol::PlantPreset::Pattern2D;
    default: return twol::PlantPreset::Tree;
  }
}

#ifndef PLANT_CORE
void set_attribs_enabled(const int used) {
  for (int i = 0; i < 6; ++i) {
    if (i < used) {
      glEnableVertexAttribArray(static_cast<unsigned>(i));
    } else {
      glDisableVertexAttribArray(static_cast<unsigned>(i));
    }
  }
}
#endif

}  // namespace

void Settings::sanitise() {
  auto clamp_int = [](int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); };
  preset = clamp_int(preset, 0, 5);
  seed = clamp_int(seed, 0, 999);
  quality = clamp_int(quality, 0, 2);
  leaf_density = clamp_int(leaf_density, 0, 2);
  growth_speed = clamp_int(growth_speed, 0, 3);
  hold_seconds = clamp_int(hold_seconds, 0, 60);
  motion = clamp_int(motion, 0, 5);
  camera_speed = clamp_int(camera_speed, 10, 200);
  framing = clamp_int(framing, 0, 2);
  background = clamp_int(background, 0, 7);
  dim = clamp_int(dim, 0, 80);
}

App::App() = default;

App::~App() = default;

bool App::init(const Settings& settings, const unsigned seed, std::string* error) {
  if (ready_) release();
  settings_ = settings;
  settings_.sanitise();
  seed_ = seed ? seed : 1U;
  if (error) error->clear();

  std::string shader_error;
  if (!make_programs(&shader_error)) {
    if (error) *error = shader_error;
    release();
    return false;
  }
  make_static_buffers();
  cycle_index_ = 0;
  start_cycle(0.0);
  ready_ = true;
  return true;
}

void App::release() {
  destroy_mesh_buffers();
  destroy_static_buffers();
  auto del_program = [](unsigned& p) {
    if (p) {
      glDeleteProgram(p);
      p = 0;
    }
  };
  del_program(scene_program_);
  del_program(background_program_);
  del_program(ground_program_);
  del_program(particle_program_);
  del_program(overlay_program_);
  ready_ = false;
}

bool App::make_programs(std::string* error) {
  scene_program_ =
      glu::link(kSceneVertex, kSceneFragment, kSceneAttributes, 6, error);
  if (!scene_program_) return false;
  background_program_ =
      glu::link(nullptr, kBackgroundFragment, kQuadAttribute, 1, error);
  if (!background_program_) return false;
  ground_program_ = glu::link(kGroundVertex, kGroundFragment, kGroundAttributes, 2, error);
  if (!ground_program_) return false;
  particle_program_ =
      glu::link(kParticleVertex, kParticleFragment, kParticleAttributes, 2, error);
  if (!particle_program_) return false;
  overlay_program_ = glu::link(nullptr, kOverlayFragment, kQuadAttribute, 1, error);
  if (!overlay_program_) return false;

  scene_u_.view_proj = glGetUniformLocation(scene_program_, "u_viewProj");
  scene_u_.cam_pos = glGetUniformLocation(scene_program_, "u_camPos");
  scene_u_.time01 = glGetUniformLocation(scene_program_, "u_time01");
  scene_u_.time = glGetUniformLocation(scene_program_, "u_time");
  scene_u_.wind = glGetUniformLocation(scene_program_, "u_wind");
  scene_u_.light_dir = glGetUniformLocation(scene_program_, "u_lightDir");
  scene_u_.ambient = glGetUniformLocation(scene_program_, "u_ambient");
  scene_u_.sun_color = glGetUniformLocation(scene_program_, "u_sunColor");
  scene_u_.rim_color = glGetUniformLocation(scene_program_, "u_rimColor");
  scene_u_.emissive = glGetUniformLocation(scene_program_, "u_emissive");

  background_u_.zenith = glGetUniformLocation(background_program_, "u_zenith");
  background_u_.horizon = glGetUniformLocation(background_program_, "u_horizon");
  background_u_.glow = glGetUniformLocation(background_program_, "u_glow");
  background_u_.cloud_color = glGetUniformLocation(background_program_, "u_cloudColor");
  background_u_.sun_color = glGetUniformLocation(background_program_, "u_sunColor");
  background_u_.cloud_amount = glGetUniformLocation(background_program_, "u_cloudAmount");
  background_u_.star_amount = glGetUniformLocation(background_program_, "u_starAmount");
  background_u_.aurora_amount = glGetUniformLocation(background_program_, "u_auroraAmount");
  background_u_.studio_amount = glGetUniformLocation(background_program_, "u_studioAmount");
  background_u_.sun_size = glGetUniformLocation(background_program_, "u_sunSize");
  background_u_.sun_visible = glGetUniformLocation(background_program_, "u_sunVisible");
  background_u_.sun_uv = glGetUniformLocation(background_program_, "u_sunUv");
  background_u_.time = glGetUniformLocation(background_program_, "u_time");
  background_u_.aspect = glGetUniformLocation(background_program_, "u_aspect");
  background_u_.resolution = glGetUniformLocation(background_program_, "u_resolution");
  background_u_.effects = glGetUniformLocation(background_program_, "u_effects");

  ground_u_.view_proj = glGetUniformLocation(ground_program_, "u_viewProj");
  ground_u_.ground_radius = glGetUniformLocation(ground_program_, "u_groundRadius");
  ground_u_.ground_color = glGetUniformLocation(ground_program_, "u_groundColor");
  ground_u_.glow = glGetUniformLocation(ground_program_, "u_glowColor");
  ground_u_.shadow = glGetUniformLocation(ground_program_, "u_shadow");
  ground_u_.time = glGetUniformLocation(ground_program_, "u_time");

  particle_u_.view_proj = glGetUniformLocation(particle_program_, "u_viewProj");
  particle_u_.time = glGetUniformLocation(particle_program_, "u_time");
  particle_u_.point_scale = glGetUniformLocation(particle_program_, "u_pointScale");
  particle_u_.color = glGetUniformLocation(particle_program_, "u_color");
  particle_u_.radius = glGetUniformLocation(particle_program_, "u_particleRadius");
  particle_u_.height = glGetUniformLocation(particle_program_, "u_particleHeight");
  particle_u_.amp = glGetUniformLocation(particle_program_, "u_particleAmp");

  overlay_u_.alpha = glGetUniformLocation(overlay_program_, "u_alpha");
  return true;
}

void App::make_static_buffers() {
  // Full-screen quad for the sky and the fade overlay.
  const float quad[8] = {-1.0f, -1.0f, 1.0f, -1.0f, -1.0f, 1.0f, 1.0f, 1.0f};
  glGenBuffers(1, &quad_vbo_);
  glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
  glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
#ifdef PLANT_CORE
  glGenVertexArrays(1, &quad_vao_);
  glBindVertexArray(quad_vao_);
  glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
  glEnableVertexAttribArray(0);
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
  glBindVertexArray(0);
#endif

  // A soft disc on the ground. x/z are scaled by u_groundRadius in the shader.
  const int ground_segments = 72;
  std::vector<float> ground;
  ground.reserve(static_cast<std::size_t>(ground_segments + 2) * 4U);
  ground.push_back(0.0f);
  ground.push_back(0.0f);
  ground.push_back(0.0f);
  ground.push_back(0.0f);
  for (int i = 0; i <= ground_segments; ++i) {
    const float a = (static_cast<float>(i) / static_cast<float>(ground_segments)) * 2.0f * kPi;
    ground.push_back(std::cos(a));
    ground.push_back(0.0f);
    ground.push_back(std::sin(a));
    ground.push_back(1.0f);
  }
  ground_vertices_ = ground_segments + 2;
  glGenBuffers(1, &ground_vbo_);
  glBindBuffer(GL_ARRAY_BUFFER, ground_vbo_);
  glBufferData(GL_ARRAY_BUFFER, ground.size() * sizeof(float), ground.data(), GL_STATIC_DRAW);
#ifdef PLANT_CORE
  glGenVertexArrays(1, &ground_vao_);
  glBindVertexArray(ground_vao_);
  glBindBuffer(GL_ARRAY_BUFFER, ground_vbo_);
  glEnableVertexAttribArray(0);
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 4 * sizeof(float), nullptr);
  glEnableVertexAttribArray(1);
  glVertexAttribPointer(1, 1, GL_FLOAT, GL_FALSE, 4 * sizeof(float),
                        reinterpret_cast<const void*>(3 * sizeof(float)));
  glBindVertexArray(0);
#endif

  // Drifting pollen: normalized positions, scaled by the plant's size in the shader.
  struct Particle {
    float x, y, z, phase, size;
  };
  std::vector<Particle> particles(kParticleCapacity);
  twol::Rng rng(seed_ ^ 0x9e3779b9U);
  for (Particle& p : particles) {
    const float r = std::sqrt(std::max(0.0f, rng.next01()));
    const float a = rng.next01() * 2.0f * kPi;
    p.x = r * std::cos(a);
    p.z = r * std::sin(a);
    p.y = std::pow(rng.next01(), 0.85f) * 1.30f;
    p.phase = rng.next01();
    p.size = rng.range(0.45f, 1.35f);
  }
  glGenBuffers(1, &particle_vbo_);
  glBindBuffer(GL_ARRAY_BUFFER, particle_vbo_);
  glBufferData(GL_ARRAY_BUFFER, particles.size() * sizeof(Particle), particles.data(),
               GL_STATIC_DRAW);
#ifdef PLANT_CORE
  glGenVertexArrays(1, &particle_vao_);
  glBindVertexArray(particle_vao_);
  glBindBuffer(GL_ARRAY_BUFFER, particle_vbo_);
  glEnableVertexAttribArray(0);
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(Particle), nullptr);
  glEnableVertexAttribArray(1);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof(Particle),
                        reinterpret_cast<const void*>(3 * sizeof(float)));
  glBindVertexArray(0);
#endif

  glBindBuffer(GL_ARRAY_BUFFER, 0);
}

void App::destroy_static_buffers() {
  auto del_buffer = [](unsigned& b) {
    if (b) {
      glDeleteBuffers(1, &b);
      b = 0;
    }
  };
  del_buffer(quad_vbo_);
  del_buffer(ground_vbo_);
  del_buffer(particle_vbo_);
#ifdef PLANT_CORE
  auto del_vao = [](unsigned& v) {
    if (v) {
      glDeleteVertexArrays(1, &v);
      v = 0;
    }
  };
  del_vao(quad_vao_);
  del_vao(ground_vao_);
  del_vao(particle_vao_);
#endif
  ground_vertices_ = 0;
  particle_draw_count_ = 0;
}

void App::destroy_mesh_buffers() {
  for (GpuBatch& b : gpu_batches_) {
    if (b.vbo) glDeleteBuffers(1, &b.vbo);
    if (b.ibo) glDeleteBuffers(1, &b.ibo);
#ifdef PLANT_CORE
    if (b.vao) glDeleteVertexArrays(1, &b.vao);
#endif
  }
  gpu_batches_.clear();
}

void App::upload_mesh() {
  destroy_mesh_buffers();
  gpu_batches_.resize(mesh_.batches.size());
  for (std::size_t i = 0; i < mesh_.batches.size(); ++i) {
    const GrowthBatch& src = mesh_.batches[i];
    GpuBatch& dst = gpu_batches_[i];
    dst.index_count = static_cast<int>(src.indices.size());
    if (src.vertices.empty() || src.indices.empty()) continue;
    glGenBuffers(1, &dst.vbo);
    glBindBuffer(GL_ARRAY_BUFFER, dst.vbo);
    glBufferData(GL_ARRAY_BUFFER, src.vertices.size() * sizeof(GrowthVertex), src.vertices.data(),
                 GL_STATIC_DRAW);
    glGenBuffers(1, &dst.ibo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, dst.ibo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, src.indices.size() * sizeof(std::uint16_t),
                 src.indices.data(), GL_STATIC_DRAW);
#ifdef PLANT_CORE
    const std::size_t stride = sizeof(GrowthVertex);
    glGenVertexArrays(1, &dst.vao);
    glBindVertexArray(dst.vao);
    glBindBuffer(GL_ARRAY_BUFFER, dst.vbo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, dst.ibo);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, static_cast<GLsizei>(stride),
                          reinterpret_cast<const void*>(offsetof(GrowthVertex, position)));
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, static_cast<GLsizei>(stride),
                          reinterpret_cast<const void*>(offsetof(GrowthVertex, normal)));
    glEnableVertexAttribArray(2);
    glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, static_cast<GLsizei>(stride),
                          reinterpret_cast<const void*>(offsetof(GrowthVertex, color)));
    glEnableVertexAttribArray(3);
    glVertexAttribPointer(3, 3, GL_FLOAT, GL_FALSE, static_cast<GLsizei>(stride),
                          reinterpret_cast<const void*>(offsetof(GrowthVertex, anchor)));
    glEnableVertexAttribArray(4);
    glVertexAttribPointer(4, 2, GL_FLOAT, GL_FALSE, static_cast<GLsizei>(stride),
                          reinterpret_cast<const void*>(offsetof(GrowthVertex, birth)));
    glEnableVertexAttribArray(5);
    glVertexAttribPointer(5, 2, GL_FLOAT, GL_FALSE, static_cast<GLsizei>(stride),
                          reinterpret_cast<const void*>(offsetof(GrowthVertex, sway)));
    glBindVertexArray(0);
#endif
  }
  glBindBuffer(GL_ARRAY_BUFFER, 0);
#ifndef PLANT_CORE
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
#endif
}

void App::start_cycle(const double now) {
  const unsigned base = settings_.seed > 0 ? static_cast<unsigned>(settings_.seed) : seed_;
  const unsigned c = static_cast<unsigned>(cycle_index_);

  if (settings_.preset == 0) {
    preset_index_ = kPresetOrder[(c + base) % 6U];
  } else {
    preset_index_ = settings_.preset;
  }
  if (settings_.background == 0) {
    if (preset_index_ == 5) {
      background_index_ = kDarkSkyOrder[(c + base / 3U) % 4U];
    } else {
      background_index_ = kSkyOrder[(c + base / 3U) % 6U];
    }
  } else {
    background_index_ = settings_.background;
  }
  if (settings_.motion == 0) {
    motion_index_ = kMotionOrder[(c + base / 7U) % 4U];
  } else {
    motion_index_ = settings_.motion;
  }
  preset_index_ = std::clamp(preset_index_, 1, 5);
  background_index_ = std::clamp(background_index_, 1, 7);
  motion_index_ = std::clamp(motion_index_, 1, 5);

  static const double kGrowSeconds[4] = {36.0, 25.0, 17.0, 11.0};
  grow_seconds_ = kGrowSeconds[std::clamp(settings_.growth_speed, 0, 3)];
  hold_seconds_ = static_cast<double>(std::clamp(settings_.hold_seconds, 0, 60));
  fade_seconds_ = 1.6;

  twol::PlantParameters p = twol::make_preset(preset_enum(preset_index_));
  p.seed = base + c * 7919U + 17U;

  const float density = settings_.leaf_density == 0
                            ? 0.55f
                            : (settings_.leaf_density == 2 ? 1.35f : 1.0f);
  if (settings_.quality == 0) {
    p.generations = std::max(3, p.generations - 2);
    p.radial_segments = std::max(4, p.radial_segments - 3);
    p.curve_segments = std::max(3, p.curve_segments - 2);
    p.leaflet_segments = std::max(3, p.leaflet_segments - 2);
    p.leaflet_count = std::max(3, p.leaflet_count - 2);
    p.branch_count = std::max(1, p.branch_count - 1);
    p.recursive_branch_depth = std::max(0, p.recursive_branch_depth - 1);
    p.leaf_node_density *= 0.65f;
  } else if (settings_.quality == 2) {
    p.generations += 1;
    p.radial_segments += 2;
    p.curve_segments += 2;
    p.leaflet_segments += 2;
    p.leaflet_count += 2;
    p.branch_count += 1;
    p.leaf_node_density *= 1.15f;
  }
  p.leaf_node_density = std::clamp(p.leaf_node_density * density, 0.05f, 1.45f);
  if (p.preset == twol::PlantPreset::Tree) {
    // A screensaver tree is read from across the room, so give it a fuller crown than the
    // study preset: more leaves per node and slightly larger blades.
    p.leaf_node_density = std::min(1.45f, p.leaf_node_density * 1.55f);
    p.leaf_scale *= 1.18f;
  }

  if (p.preset == twol::PlantPreset::Pattern2D) {
    p.generations = settings_.quality == 0 ? 3 : (settings_.quality == 2 ? 5 : 4);
    p.radial_segments = settings_.quality == 0 ? 5 : (settings_.quality == 2 ? 9 : 7);
    p.leaf_style = twol::LeafStyle::None;
  }
  p.full_growth_seconds = static_cast<float>(grow_seconds_);
  params_ = p;
  graph_ = twol::generate_node_graph(params_);
  mesh_ = build_growth_mesh(graph_);
  upload_mesh();

  particle_draw_count_ = settings_.quality == 0 ? 16 : (settings_.quality == 2 ? 72 : 48);
  look_ = background_index_ == 7 ? kFlatLook : kLooks[background_index_ - 1];
  cycle_start_ = now;
  last_t_ = 0.0;
  fade_ = 0.0;
  shader_time_ = std::fmod(now, 3600.0);
  ++cycle_index_;
}

void App::update_cycle(const double now) {
  const double total = fade_seconds_ * 2.0 + grow_seconds_ + hold_seconds_;
  double e = now - cycle_start_;
  if (e < 0.0) {
    cycle_start_ = now;
    e = 0.0;
  }
  if (e >= total) {
    start_cycle(now);
    e = 0.0;
  }

  double t = 0.0;
  if (e < fade_seconds_) {
    fade_ = smooth01(static_cast<float>(e / fade_seconds_));
    t = 0.0;
  } else if (e < fade_seconds_ + grow_seconds_) {
    fade_ = 1.0;
    t = (e - fade_seconds_) / grow_seconds_;
  } else if (e < fade_seconds_ + grow_seconds_ + hold_seconds_) {
    fade_ = 1.0;
    t = 1.0;
  } else {
    fade_ = 1.0 - smooth01(static_cast<float>(
                       (e - fade_seconds_ - grow_seconds_ - hold_seconds_) / fade_seconds_));
    t = 1.0;
  }
  last_t_ = std::clamp(t, 0.0, 1.0);
}

void App::update_camera(const double now, const int width, const int height) {
  const float t = static_cast<float>(last_t_);
  const float speed = std::max(0.1f, static_cast<float>(settings_.camera_speed) / 100.0f);
  const float aspect = static_cast<float>(std::max(1, width)) /
                       static_cast<float>(std::max(1, height));
  const float framing = settings_.framing == 1 ? 0.82f : (settings_.framing == 2 ? 1.28f : 1.0f);
  const float tn = static_cast<float>(std::fmod(now, 100000.0));
  const Vec3 up{0.0f, 1.0f, 0.0f};

  if (preset_index_ == 5) {
    const float cx = 0.5f * (mesh_.bounds_min.x + mesh_.bounds_max.x);
    const float cy = 0.5f * (mesh_.bounds_min.y + mesh_.bounds_max.y);
    const float cz = 0.5f * (mesh_.bounds_min.z + mesh_.bounds_max.z);
    const float span_x = std::max(0.5f, mesh_.bounds_max.x - mesh_.bounds_min.x);
    const float span_y = std::max(0.5f, mesh_.bounds_max.y - mesh_.bounds_min.y);
    const float grow = 0.45f + 0.55f * t;
    float dist = 1.85f * std::max(span_y, span_x / std::max(1.0f, aspect)) * grow;
    dist = std::max(1.2f, dist) * framing;
    if (aspect < 1.0f) dist /= std::max(0.55f, aspect);

    const float yaw = 0.20f * std::sin(tn * 0.10f * speed) + 0.10f * std::sin(tn * 0.037f);
    const float pitch = 0.035f + 0.025f * std::sin(tn * 0.07f * speed);
    const Vec3 target{cx, cy, cz};
    const Vec3 eye = target + Vec3{std::sin(yaw) * std::cos(pitch), std::sin(pitch),
                                   std::cos(yaw) * std::cos(pitch)} *
                                 dist;
    cam_target_ = target;
    cam_pos_ = eye;
    const float near_plane = 0.05f;
    const float far_plane = std::max(120.0f, dist * 20.0f);
    view_proj_ = multiply(perspective(40.0f * twol::deg_to_rad, aspect, near_plane, far_plane),
                          look_at(eye, target, up));
    return;
  }

  const float cx = 0.5f * (mesh_.bounds_min.x + mesh_.bounds_max.x);
  const float cz = 0.5f * (mesh_.bounds_min.z + mesh_.bounds_max.z);
  const float visible_h = std::max(0.5f, mesh_.height * (0.72f + 0.28f * t));
  const float visible_r = std::max(0.25f, mesh_.radius * (0.55f + 0.45f * t));
  float fit = std::max(visible_h * 1.60f, visible_r * 2.50f);
  fit = std::max(1.6f, fit) * framing;
  if (aspect < 1.0f) fit /= std::max(0.55f, aspect);

  float target_y = mesh_.height * (0.30f + 0.20f * t);
  float yaw = 0.0f;
  float pitch = 0.26f;
  float distance = fit;

  switch (motion_index_) {
    case 1:  // orbit: a steady circle around the plant
      yaw = tn * 0.090f * speed;
      pitch = 0.26f + 0.035f * std::sin(tn * 0.06f * speed);
      distance *= 1.0f + 0.025f * std::sin(tn * 0.05f * speed);
      break;
    case 2:  // sway: a hand-held drift, back and forth
      yaw = tn * 0.055f * speed + 0.65f * std::sin(tn * 0.08f * speed);
      pitch = 0.22f + 0.13f * std::sin(tn * 0.11f * speed + 0.7f);
      distance *= 1.0f + 0.05f * std::sin(tn * 0.07f * speed);
      break;
    case 3: {  // spiral: rise from a low angle to a high one while circling
      yaw = tn * 0.120f * speed;
      pitch = twol::lerp(0.08f, 0.56f, smooth01(t)) + 0.035f * std::sin(tn * 0.07f);
      distance *= 0.92f + 0.16f * smooth01(t);
      break;
    }
    case 4: {  // crane: climb from near the soil to above the crown
      yaw = tn * 0.045f * speed + 0.30f * std::sin(tn * 0.05f);
      pitch = twol::lerp(0.035f, 0.62f, smooth01(t)) + 0.02f * std::sin(tn * 0.09f);
      target_y = mesh_.height * (0.24f + 0.16f * t);
      distance *= 1.02f;
      break;
    }
    default:  // still: one slow, deliberate angle per cycle
      yaw = static_cast<float>(cycle_index_ - 1) * 2.399f + 0.12f * std::sin(tn * 0.03f);
      pitch = 0.27f + 0.02f * std::sin(tn * 0.05f);
      break;
  }

  const float cy = target_y;
  const Vec3 target{cx, cy, cz};
  const Vec3 dir{std::sin(yaw) * std::cos(pitch), std::sin(pitch),
                 std::cos(yaw) * std::cos(pitch)};
  const Vec3 eye = target + dir * std::max(1.2f, distance);
  cam_target_ = target;
  cam_pos_ = eye;
  const float near_plane = 0.05f;
  const float far_plane = std::max(120.0f, distance * 20.0f + mesh_.height * 4.0f);
  view_proj_ = multiply(perspective(40.0f * twol::deg_to_rad, aspect, near_plane, far_plane),
                        look_at(eye, target, up));
}

void App::render(const double now, const int width, const int height) {
  if (!ready_ || width <= 0 || height <= 0) return;
  update_cycle(now);
  shader_time_ = std::fmod(now, 3600.0);
  update_camera(now, width, height);

  glu::SavedState saved;
  glViewport(0, 0, width, height);
  glDepthMask(GL_TRUE);
  if (background_index_ == 7) {
    // Flat backdrop: skip the full-screen sky shader entirely, just clear to its colour.
    glClearColor(look_.horizon.x, look_.horizon.y, look_.horizon.z, 1.0f);
  } else {
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
  }
  glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

  if (background_index_ != 7) draw_background(width, height);
  if (settings_.ground && preset_index_ != 5) draw_ground();
  draw_plant();
  if (settings_.particles && particle_draw_count_ > 0) draw_particles(width, height);
  draw_overlay();
}

void App::set_quad_attributes() {
#ifdef PLANT_CORE
  glBindVertexArray(quad_vao_);
#else
  glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
  set_attribs_enabled(1);
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
#endif
}

void App::set_ground_attributes() {
#ifdef PLANT_CORE
  glBindVertexArray(ground_vao_);
#else
  glBindBuffer(GL_ARRAY_BUFFER, ground_vbo_);
  set_attribs_enabled(2);
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 4 * sizeof(float), nullptr);
  glVertexAttribPointer(1, 1, GL_FLOAT, GL_FALSE, 4 * sizeof(float),
                        reinterpret_cast<const void*>(3 * sizeof(float)));
#endif
}

void App::set_particle_attributes() {
#ifdef PLANT_CORE
  glBindVertexArray(particle_vao_);
#else
  glBindBuffer(GL_ARRAY_BUFFER, particle_vbo_);
  set_attribs_enabled(2);
  const GLsizei stride = static_cast<GLsizei>(5 * sizeof(float));
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, nullptr);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride,
                        reinterpret_cast<const void*>(3 * sizeof(float)));
#endif
}

void App::draw_background(const int width, const int height) {
  const float aspect = static_cast<float>(std::max(1, width)) /
                       static_cast<float>(std::max(1, height));
  const Vec3 sun_dir = twol::safe_normalize(look_.light_dir, Vec3{0.4f, 0.7f, 0.5f});
  const Vec3 sun_world = cam_target_ + sun_dir * 500.0f;
  float sx = 0.5f;
  float sy = 1.2f;
  bool visible = false;
  if (project_point(view_proj_, sun_world, &sx, &sy)) {
    sx = sx * 0.5f + 0.5f;
    sy = sy * 0.5f + 0.5f;
    visible = sx > -0.45f && sx < 1.45f && sy > -0.45f && sy < 1.45f;
  }
  const float sun_visible = visible ? look_.sun_disc : 0.0f;

  glUseProgram(background_program_);
  glDisable(GL_DEPTH_TEST);
  glDepthMask(GL_FALSE);
  glDisable(GL_BLEND);
  set_quad_attributes();
  glUniform3f(background_u_.zenith, look_.zenith.x, look_.zenith.y, look_.zenith.z);
  glUniform3f(background_u_.horizon, look_.horizon.x, look_.horizon.y, look_.horizon.z);
  glUniform3f(background_u_.glow, look_.glow.x, look_.glow.y, look_.glow.z);
  glUniform3f(background_u_.cloud_color, look_.cloud.x, look_.cloud.y, look_.cloud.z);
  glUniform3f(background_u_.sun_color, look_.sun.x, look_.sun.y, look_.sun.z);
  glUniform1f(background_u_.cloud_amount, look_.cloud_amount);
  glUniform1f(background_u_.star_amount, look_.star_amount);
  glUniform1f(background_u_.aurora_amount, look_.aurora_amount);
  glUniform1f(background_u_.studio_amount, look_.studio_amount);
  glUniform1f(background_u_.sun_size, look_.sun_size);
  glUniform1f(background_u_.sun_visible, sun_visible);
  glUniform2f(background_u_.sun_uv, sx, sy);
  glUniform1f(background_u_.time, static_cast<float>(shader_time_));
  glUniform1f(background_u_.aspect, aspect);
  glUniform2f(background_u_.resolution, static_cast<float>(width),
              static_cast<float>(height));
  glUniform1f(background_u_.effects, settings_.quality == 0 ? 0.0f : 1.0f);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
}

void App::draw_ground() {
  const float ground_radius =
      std::max(8.0f, std::max(mesh_.height * 3.0f, mesh_.radius * 4.0f));
  glUseProgram(ground_program_);
  glEnable(GL_DEPTH_TEST);
  glDepthMask(GL_FALSE);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
  set_ground_attributes();
  glUniformMatrix4fv(ground_u_.view_proj, 1, GL_FALSE, view_proj_.m);
  glUniform1f(ground_u_.ground_radius, ground_radius);
  glUniform3f(ground_u_.ground_color, look_.ground.x, look_.ground.y, look_.ground.z);
  glUniform3f(ground_u_.glow, look_.glow.x, look_.glow.y, look_.glow.z);
  glUniform1f(ground_u_.shadow, 0.45f + 0.25f * static_cast<float>(last_t_));
  glUniform1f(ground_u_.time, static_cast<float>(shader_time_));
  glDrawArrays(GL_TRIANGLE_FAN, 0, ground_vertices_);
}

void App::draw_plant() {
  if (gpu_batches_.empty()) return;
  glUseProgram(scene_program_);
  glEnable(GL_DEPTH_TEST);
  glDepthMask(GL_TRUE);
  glDisable(GL_BLEND);
  glDisable(GL_CULL_FACE);
  set_scene_uniforms();
  for (const GpuBatch& b : gpu_batches_) {
    if (b.index_count <= 0) continue;
#ifdef PLANT_CORE
    glBindVertexArray(b.vao);
#else
    const std::size_t stride = sizeof(GrowthVertex);
    glBindBuffer(GL_ARRAY_BUFFER, b.vbo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, b.ibo);
    set_attribs_enabled(6);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, static_cast<GLsizei>(stride),
                          reinterpret_cast<const void*>(offsetof(GrowthVertex, position)));
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, static_cast<GLsizei>(stride),
                          reinterpret_cast<const void*>(offsetof(GrowthVertex, normal)));
    glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, static_cast<GLsizei>(stride),
                          reinterpret_cast<const void*>(offsetof(GrowthVertex, color)));
    glVertexAttribPointer(3, 3, GL_FLOAT, GL_FALSE, static_cast<GLsizei>(stride),
                          reinterpret_cast<const void*>(offsetof(GrowthVertex, anchor)));
    glVertexAttribPointer(4, 2, GL_FLOAT, GL_FALSE, static_cast<GLsizei>(stride),
                          reinterpret_cast<const void*>(offsetof(GrowthVertex, birth)));
    glVertexAttribPointer(5, 2, GL_FLOAT, GL_FALSE, static_cast<GLsizei>(stride),
                          reinterpret_cast<const void*>(offsetof(GrowthVertex, sway)));
#endif
    glDrawElements(GL_TRIANGLES, b.index_count, GL_UNSIGNED_SHORT, nullptr);
  }
}

void App::set_scene_uniforms() {
  const float t = static_cast<float>(last_t_);
  const float wind =
      (0.010f + 0.012f * t) * clampf(mesh_.height / 4.0f, 0.6f, 1.6f);
  glUniformMatrix4fv(scene_u_.view_proj, 1, GL_FALSE, view_proj_.m);
  glUniform3f(scene_u_.cam_pos, cam_pos_.x, cam_pos_.y, cam_pos_.z);
  glUniform1f(scene_u_.time01, t);
  glUniform1f(scene_u_.time, static_cast<float>(shader_time_));
  glUniform1f(scene_u_.wind, wind);
  glUniform3f(scene_u_.light_dir, look_.light_dir.x, look_.light_dir.y, look_.light_dir.z);
  glUniform3f(scene_u_.ambient, look_.ambient.x, look_.ambient.y, look_.ambient.z);
  glUniform3f(scene_u_.sun_color, look_.sun.x, look_.sun.y, look_.sun.z);
  glUniform3f(scene_u_.rim_color, look_.rim.x, look_.rim.y, look_.rim.z);
  glUniform1f(scene_u_.emissive, preset_index_ == 5 ? 0.68f : 0.0f);
}

void App::draw_particles(const int width, const int height) {
  (void)width;
  glUseProgram(particle_program_);
  glEnable(GL_DEPTH_TEST);
  glDepthMask(GL_FALSE);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE);
#if !defined(PLANT_GLES)
  glEnable(GL_PROGRAM_POINT_SIZE);
#endif
  set_particle_attributes();
  const float radius = std::max(1.1f, mesh_.radius * 1.45f + 0.55f);
  const float particle_height = std::max(0.8f, mesh_.height * 0.92f);
  const float amp = 0.06f + 0.07f * static_cast<float>(last_t_);
  glUniformMatrix4fv(particle_u_.view_proj, 1, GL_FALSE, view_proj_.m);
  glUniform1f(particle_u_.time, static_cast<float>(shader_time_));
  glUniform1f(particle_u_.point_scale, static_cast<float>(height) / 900.0f);
  glUniform3f(particle_u_.color, look_.particle.x, look_.particle.y, look_.particle.z);
  glUniform1f(particle_u_.radius, radius);
  glUniform1f(particle_u_.height, particle_height);
  glUniform1f(particle_u_.amp, amp);
  glDrawArrays(GL_POINTS, 0, particle_draw_count_);
}

void App::draw_overlay() {
  const float dim01 = static_cast<float>(std::clamp(settings_.dim, 0, 80)) / 100.0f;
  const float alpha =
      clampf(1.0f - static_cast<float>(fade_) * (1.0f - dim01), 0.0f, 1.0f);
  if (alpha <= 0.002f) return;
  glUseProgram(overlay_program_);
  glDisable(GL_DEPTH_TEST);
  glDepthMask(GL_FALSE);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
  set_quad_attributes();
  glUniform1f(overlay_u_.alpha, alpha);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
}

}  // namespace plantgl

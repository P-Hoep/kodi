#include "infworld_app.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <vector>

#include "gl_util.hpp"
#include "stb_image.h"

namespace sandclock {
namespace infworldgl {

using infworld::Mat4;
using infworld::Vec2;
using infworld::Vec3;

namespace {

constexpr float PI = 3.14159265358979323846f;
constexpr int kMaxDrawRes = 1080;

float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

bool read_file(const std::string& path, std::vector<unsigned char>* data) {
  std::ifstream f(path, std::ios::binary);
  if (!f) return false;
  f.seekg(0, std::ios::end);
  const std::streamoff size = f.tellg();
  if (size <= 0) return false;
  f.seekg(0, std::ios::beg);
  data->resize(static_cast<size_t>(size));
  f.read(reinterpret_cast<char*>(data->data()), size);
  return static_cast<bool>(f);
}

// ---- Shaders --------------------------------------------------------------------
// All in GLSL 1.20 / GLSL ES 1.00 style; glu::version_* adds #version and the core fixes.

const char* const kTerrainVertex = R"(
attribute vec2 a0;   // local x/z in pre-scale units
attribute vec3 a1;   // height / maxheight, normal angle, asin(normal.y)
uniform mat4 persp;
uniform mat4 view;
uniform mat4 transform;
uniform vec3 lightdir;
uniform float maxheight;
uniform float minrange;
varying float v_lighting;
varying float v_height;
varying vec3 v_fragpos;
void main() {
  vec4 pos = vec4(a0.x, a1.x * maxheight, a0.y, 1.0);
  vec4 world = transform * pos;
  gl_Position = persp * view * world;
  v_fragpos = world.xyz;
  v_height = a1.x;
  vec3 n = vec3(cos(a1.z) * cos(a1.y), sin(a1.z), cos(a1.z) * sin(a1.y));
  v_lighting = max(-dot(lightdir, n), 0.0) * 0.6 + 0.4;
}
)";

const char* const kTerrainFragment = R"(
varying float v_lighting;
varying float v_height;
varying vec3 v_fragpos;
uniform sampler2D terrain0;
uniform sampler2D terrain1;
uniform sampler2D terrain2;
uniform sampler2D terrain3;
uniform vec3 camerapos;
uniform float viewdist;
uniform float minrange;

float mixval(float lower, float upper, float y) {
  return (1.0 - (y - lower) / (upper - lower)) * float(y >= lower && y < upper);
}
float heightToMix() {
  return mixval(0.01, 0.02, v_height) + mixval(0.1, 0.3, v_height) +
         mixval(0.6, 0.7, v_height);
}
vec4 getcolor() {
  // The palette's four swatches are separate repeating textures. infworld sampled one atlas
  // with fract(), whose seam makes the GPU pick a huge mip level along every 16-unit tile
  // border; sampling repeating textures directly tiles without that grid of bright lines.
  vec2 tc = v_fragpos.xz / 16.0;
  vec4 c0 = texture2D(terrain0, tc);
  vec4 c1 = texture2D(terrain1, tc);
  vec4 c2 = texture2D(terrain2, tc);
  vec4 c3 = texture2D(terrain3, tc);
  float a = float(v_height >= 0.01) + float(v_height >= 0.1) + float(v_height >= 0.6);
  float b = float(v_height >= 0.02) + float(v_height >= 0.3) + float(v_height >= 0.7);
  float m = heightToMix();
  vec4 color = c0 * ((1.0 - m) * float(a < 0.5) + m * float(b < 0.5));
  color += c1 * ((1.0 - m) * float(a > 0.5 && a < 1.5) + m * float(b > 0.5 && b < 1.5));
  color += c2 * ((1.0 - m) * float(a > 1.5 && a < 2.5) + m * float(b > 1.5 && b < 2.5));
  color += c3 * ((1.0 - m) * float(a > 2.5) + m * float(b > 2.5));
  color.a = 1.0;
  return color;
}
void main() {
  if (minrange > 0.0 && length(v_fragpos.xz - camerapos.xz) < minrange) discard;
  vec4 color = getcolor() * v_lighting;
  color.a = 1.0;
  float d = length(v_fragpos - camerapos);
  float f = clamp((d - viewdist * 0.60) / (viewdist * 0.40), 0.0, 1.0);
  gl_FragColor = mix(color, vec4(0.5, 0.8, 1.0, 1.0), f);
}
)";

const char* const kTreeVertex = R"(
attribute vec3 a0;   // position relative to the decoration chunk
attribute vec2 a1;   // texture coordinate
attribute vec3 a2;   // normal
attribute float a3;  // wind lever, world units from the trunk
uniform mat4 persp;
uniform mat4 view;
uniform mat4 transform;
uniform vec3 lightdir;
uniform float time;
uniform float windstrength;
varying float v_lighting;
varying vec3 v_fragpos;
varying vec2 v_tc;
void main() {
  vec4 p = vec4(a0, 1.0);
  p.y += sin(time * 1.6 + a0.x * 0.11 + a0.z * 0.09) * 0.06 * a3 * windstrength;
  p.x += cos(time * 1.3 + a0.x * 0.10) * 0.05 * a3 * windstrength;
  p.z += sin(time * 1.1 + a0.z * 0.12) * 0.05 * a3 * windstrength;
  vec4 world = transform * p;
  gl_Position = persp * view * world;
  v_fragpos = world.xyz;
  v_tc = a1;
  v_lighting = max(-dot(lightdir, a2), 0.0) * 0.7 + 0.3;
}
)";

const char* const kTreeFragment = R"(
varying float v_lighting;
varying vec3 v_fragpos;
varying vec2 v_tc;
uniform sampler2D tex;
uniform vec3 camerapos;
uniform float viewdist;
void main() {
  vec4 color = texture2D(tex, fract(v_tc));
  if (color.a < 0.5) discard;
  color.rgb *= v_lighting;
  color.a = 1.0;
  float d = length(v_fragpos - camerapos);
  float f = clamp((d - viewdist * 0.60) / (viewdist * 0.40), 0.0, 1.0);
  gl_FragColor = mix(color, vec4(0.5, 0.8, 1.0, 1.0), f);
}
)";

const char* const kWaterVertex = R"(
attribute vec2 a0;
uniform mat4 persp;
uniform mat4 view;
uniform mat4 transform;
varying vec3 v_fragpos;
void main() {
  vec4 world = transform * vec4(a0.x, 0.0, a0.y, 1.0);
  gl_Position = persp * view * world;
  v_fragpos = world.xyz;
}
)";

const char* const kWaterFragment = R"(
varying vec3 v_fragpos;
// infworld's watermaps atlas split into its three repeating maps, so the tiling UVs are
// continuous and the GPU does not pick a coarser mip along every 64/96-unit tile edge.
uniform sampler2D water_dudv;
uniform sampler2D water_normal1;
uniform sampler2D water_normal2;
uniform vec3 camerapos;
uniform vec3 lightdir;
uniform float time;
uniform float viewdist;
void main() {
  vec2 dir1 = vec2(cos(-0.5), sin(-0.5));
  vec2 dir2 = vec2(cos(1.32079633), sin(1.32079633));
  vec2 xy = v_fragpos.xz;
  vec2 dudv = (texture2D(water_dudv, xy / 64.0).xy - 0.5) * 2.0;
  vec2 tc1 = (xy + dudv) / 64.0 + dir1 * 0.08 * time;
  vec2 tc2 = (xy + dudv) / 96.0 + dir2 * 0.05 * time;
  vec3 n1 = (texture2D(water_normal1, tc1).xzy - 0.5) * 2.0;
  vec3 n2 = (texture2D(water_normal2, tc2).xzy - 0.5) * 2.0;
  vec3 normal = normalize(n1 + n2);
  vec3 reflected = reflect(lightdir, normal);
  vec3 viewdir = normalize(camerapos - v_fragpos);
  float specular = pow(max(dot(viewdir, reflected), 0.0), 8.0);
  float diffuse = max(-dot(lightdir, normal), 0.0) * 0.5 + 0.5;
  vec4 color = vec4(0.1, 0.7, 0.9, 0.0) * diffuse + vec4(0.5, 0.3, 0.1, 0.0) * specular;
  color.a = 0.8;
  float d = length(v_fragpos - camerapos);
  float f = clamp((d - viewdist * 0.60) / (viewdist * 0.40), 0.0, 1.0);
  gl_FragColor = mix(color, vec4(0.5, 0.8, 1.0, 1.0), f);
}
)";

const char* const kSkyVertex = R"(
attribute vec3 a0;
uniform mat4 persp;
uniform mat4 view;
varying vec3 v_fragpos;
void main() {
  gl_Position = (persp * view * vec4(a0, 1.0)).xyww;
  v_fragpos = a0;
}
)";

const char* const kSkyFragment = R"(
varying vec3 v_fragpos;
uniform samplerCube skybox;
void main() {
  float v = clamp((0.4 - v_fragpos.y) * 4.0, 0.0, 1.0);
  gl_FragColor = mix(textureCube(skybox, v_fragpos), vec4(0.5, 0.8, 1.0, 1.0), v);
}
)";

const char* const kSolidFragment = R"(
uniform vec4 colour;
void main() { gl_FragColor = colour; }
)";

const char* const kPresentFragment = R"(
varying vec2 v_uv;
uniform sampler2D tex;
void main() { gl_FragColor = texture2D(tex, v_uv); }
)";

const float kQuad[] = {-1, -1, 1, -1, -1, 1, 1, -1, 1, 1, -1, 1};

const float kCube[] = {
    1,  1,  1,  -1, 1,  1,  -1, -1, 1,  1,  -1, 1,
    1,  1,  -1, -1, 1,  -1, -1, -1, -1, 1,  -1, -1,
};

const unsigned short kCubeIndices[] = {
    7, 6, 5, 5, 4, 7, 5, 6, 2, 2, 1, 5, 0, 3, 7, 7, 4, 0,
    0, 1, 2, 2, 3, 0, 0, 4, 5, 5, 1, 0, 7, 2, 6, 3, 2, 7,
};

}  // namespace

App::App() = default;
App::~App() = default;

Vec3 App::Camera::forward() const {
  const float cp = std::cos(pitch);
  return infworld::normalize({cp * std::sin(yaw), std::sin(-pitch), cp * -std::cos(yaw)});
}
Vec3 App::Camera::right() const {
  return infworld::normalize(infworld::cross({0, 1, 0}, forward()));
}
Vec3 App::Camera::up() const {
  return infworld::normalize(infworld::cross(forward(), right()));
}
Mat4 App::Camera::view() const {
  return Mat4::rotate_x(pitch) * Mat4::rotate_y(yaw) * Mat4::translate(-position);
}

// ---- Setup ----------------------------------------------------------------------

bool App::make_program(const char* vertex, const char* fragment,
                       const char* const* attributes, int attribute_count, unsigned* program,
                       std::string* error) {
  unsigned vs = glu::compile(GL_VERTEX_SHADER, vertex ? vertex : glu::quad_vertex(), error);
  if (!vs) return false;
  unsigned fs = glu::compile(GL_FRAGMENT_SHADER, fragment, error);
  if (!fs) {
    glDeleteShader(vs);
    return false;
  }
  unsigned prog = glCreateProgram();
  glAttachShader(prog, vs);
  glAttachShader(prog, fs);
  for (int i = 0; i < attribute_count; ++i) glBindAttribLocation(prog, i, attributes[i]);
  glLinkProgram(prog);
  glDeleteShader(vs);
  glDeleteShader(fs);
  int ok = 0;
  glGetProgramiv(prog, GL_LINK_STATUS, &ok);
  if (!ok) {
    char log[2048];
    glGetProgramInfoLog(prog, sizeof log, nullptr, log);
    *error = std::string("link: ") + log;
    glDeleteProgram(prog);
    return false;
  }
  *program = prog;
  return true;
}

bool App::load_texture(const std::string& path, unsigned* texture, bool mipmaps,
                       std::string* error) {
  std::vector<unsigned char> bytes;
  if (!read_file(path, &bytes)) {
    *error = "cannot read " + path;
    return false;
  }
  int w = 0, h = 0, channels = 0;
  unsigned char* pixels = stbi_load_from_memory(bytes.data(), static_cast<int>(bytes.size()), &w,
                                                &h, &channels, 0);
  if (!pixels) {
    *error = "cannot decode " + path + ": " + stbi_failure_reason();
    return false;
  }
  GLenum format = GL_RGBA;
  if (channels == 3) format = GL_RGB;
  if (channels != 3 && channels != 4) {
    stbi_image_free(pixels);
    *error = path + " is not RGB or RGBA";
    return false;
  }
  glGenTextures(1, texture);
  glBindTexture(GL_TEXTURE_2D, *texture);
  glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
  glTexImage2D(GL_TEXTURE_2D, 0, static_cast<GLint>(format), w, h, 0, format, GL_UNSIGNED_BYTE,
               pixels);
  stbi_image_free(pixels);
  if (mipmaps) {
    glGenerateMipmap(GL_TEXTURE_2D);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
  } else {
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  }
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
  return true;
}

// Splits a texture that holds `total` equal swatches side by side into the first `count` of them as
// separate repeating textures. Shaders can then tile one swatch with a continuous UV instead of
// fract() around an atlas, whose seam makes the GPU pick a coarser mip along every tile edge.
static bool split_swatches(const std::string& path, int total, int count, unsigned* textures,
                           std::string* error) {
  std::vector<unsigned char> bytes;
  if (!read_file(path, &bytes)) {
    *error = "cannot read " + path;
    return false;
  }
  int w = 0, h = 0, channels = 0;
  unsigned char* pixels = stbi_load_from_memory(bytes.data(), static_cast<int>(bytes.size()), &w,
                                                &h, &channels, 0);
  if (!pixels) {
    *error = "cannot decode " + path + ": " + stbi_failure_reason();
    return false;
  }
  if ((channels != 3 && channels != 4) || w % total != 0) {
    stbi_image_free(pixels);
    *error = path + " must be RGB(A) with equal swatches side by side";
    return false;
  }
  const int sw = w / total;
  const GLenum format = channels == 4 ? GL_RGBA : GL_RGB;
  const size_t row = static_cast<size_t>(sw) * channels;
  std::vector<unsigned char> strip(row * h);
  glGenTextures(count, textures);
  glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
  for (int s = 0; s < count; ++s) {
    for (int y = 0; y < h; ++y) {
      std::memcpy(&strip[static_cast<size_t>(y) * row],
                  pixels + (static_cast<size_t>(y) * w + static_cast<size_t>(s) * sw) * channels,
                  row);
    }
    glBindTexture(GL_TEXTURE_2D, textures[s]);
    glTexImage2D(GL_TEXTURE_2D, 0, static_cast<GLint>(format), sw, h, 0, format, GL_UNSIGNED_BYTE,
                 strip.data());
    glGenerateMipmap(GL_TEXTURE_2D);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
  }
  stbi_image_free(pixels);
  return true;
}

bool App::load_palette(const std::string& path, unsigned textures[4], std::string* error) {
  return split_swatches(path, 4, 4, textures, error);
}

bool App::load_watermaps(const std::string& path, unsigned textures[3], std::string* error) {
  // watermaps.png is [normal1][normal2][dudv][unused]; quarters 0-2 are what the shader samples.
  return split_swatches(path, 4, 3, textures, error);
}

bool App::load_cubemap(const std::string& dir, unsigned* texture, std::string* error) {
  static const char* const faces[6] = {"skybox_east.png",  "skybox_west.png",  "skybox_up.png",
                                      "skybox_down.png", "skybox_north.png", "skybox_south.png"};
  glGenTextures(1, texture);
  glBindTexture(GL_TEXTURE_CUBE_MAP, *texture);
  for (int i = 0; i < 6; ++i) {
    const std::string path = dir + "/skybox/" + faces[i];
    std::vector<unsigned char> bytes;
    if (!read_file(path, &bytes)) {
      *error = "cannot read " + path;
      return false;
    }
    int w = 0, h = 0, channels = 0;
    unsigned char* pixels = stbi_load_from_memory(bytes.data(), static_cast<int>(bytes.size()), &w,
                                                  &h, &channels, 0);
    if (!pixels) {
      *error = "cannot decode " + path;
      return false;
    }
    const GLenum format = channels == 4 ? GL_RGBA : GL_RGB;
    glTexImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, 0, static_cast<GLint>(format), w, h, 0,
                 format, GL_UNSIGNED_BYTE, pixels);
    stbi_image_free(pixels);
  }
  glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
#if !defined(SANDCLOCK_GLES)
  // GLES 2.0 has no GL_TEXTURE_WRAP_R; s and t cover the cube faces it draws.
  glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE);
#endif
  return true;
}

bool App::load_textures(const std::string& dir, std::string* error) {
  if (!load_palette(dir + "/terraintextures.png", terrain_texture_, error)) return false;
  if (!load_watermaps(dir + "/watermaps.png", water_texture_, error)) return false;
  if (!load_texture(dir + "/pinetreetexture.png", &pine_texture_, false, error)) return false;
  if (!load_texture(dir + "/treetexture.png", &leafy_texture_, false, error)) return false;
  return load_cubemap(dir, &skybox_texture_, error);
}

void App::make_buffers() {
#ifdef SANDCLOCK_CORE
  glGenVertexArrays(1, &vao_);
  glBindVertexArray(vao_);
#endif
  const int precision = settings_.precision();
  const std::vector<unsigned short> indices = infworld::make_indices(precision);
  glGenBuffers(1, &terrain_indices_);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, terrain_indices_);
  glBufferData(GL_ELEMENT_ARRAY_BUFFER,
               static_cast<GLsizeiptr>(indices.size() * sizeof(unsigned short)), indices.data(),
               GL_STATIC_DRAW);
  terrain_index_count_ = static_cast<unsigned>(indices.size());

  for (int i = 0; i < infworld::LOD_LEVELS; ++i) {
    const float scale = infworld::CHUNK_SZ * std::pow(infworld::LOD_SCALE, i);
    const std::vector<float> grid = infworld::make_grid(precision, scale);
    glGenBuffers(1, &terrain_grid_[i]);
    glBindBuffer(GL_ARRAY_BUFFER, terrain_grid_[i]);
    glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(grid.size() * sizeof(float)), grid.data(),
                 GL_STATIC_DRAW);
  }

  glGenBuffers(1, &quad_vbo_);
  glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
  glBufferData(GL_ARRAY_BUFFER, sizeof kQuad, kQuad, GL_STATIC_DRAW);

  glGenBuffers(1, &sky_vbo_);
  glBindBuffer(GL_ARRAY_BUFFER, sky_vbo_);
  glBufferData(GL_ARRAY_BUFFER, sizeof kCube, kCube, GL_STATIC_DRAW);
  glGenBuffers(1, &sky_ibo_);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, sky_ibo_);
  glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof kCubeIndices, kCubeIndices, GL_STATIC_DRAW);
}

bool App::init(const infworld::Settings& settings, unsigned seed, const std::string& asset_dir,
               std::string* error) {
  settings_ = settings;
  settings_.sanitise();
  asset_dir_ = asset_dir;
  seed_ = settings_.seed != 0 ? static_cast<unsigned>(settings_.seed) : seed;

  const char* const scene_attrs[] = {"a0", "a1", "a2", "a3"};
  const char* const single[] = {"a0"};
  if (!make_program(kTerrainVertex, kTerrainFragment, scene_attrs, 2, &terrain_program_, error))
    return false;
  if (!make_program(kTreeVertex, kTreeFragment, scene_attrs, 4, &tree_program_, error))
    return false;
  if (!make_program(kWaterVertex, kWaterFragment, single, 1, &water_program_, error)) return false;
  if (!make_program(kSkyVertex, kSkyFragment, single, 1, &sky_program_, error)) return false;
  if (!make_program(nullptr, kSolidFragment, single, 1, &solid_program_, error)) return false;
  if (!make_program(nullptr, kPresentFragment, single, 1, &present_program_, error)) return false;

  auto loc = [](unsigned program, const char* name) {
    return glGetUniformLocation(program, name);
  };
  terrain_u_.persp = loc(terrain_program_, "persp");
  terrain_u_.view = loc(terrain_program_, "view");
  terrain_u_.transform = loc(terrain_program_, "transform");
  terrain_u_.lightdir = loc(terrain_program_, "lightdir");
  terrain_u_.camerapos = loc(terrain_program_, "camerapos");
  terrain_u_.viewdist = loc(terrain_program_, "viewdist");
  terrain_u_.terrain[0] = loc(terrain_program_, "terrain0");
  terrain_u_.terrain[1] = loc(terrain_program_, "terrain1");
  terrain_u_.terrain[2] = loc(terrain_program_, "terrain2");
  terrain_u_.terrain[3] = loc(terrain_program_, "terrain3");
  terrain_u_.maxheight = loc(terrain_program_, "maxheight");
  terrain_u_.minrange = loc(terrain_program_, "minrange");

  tree_u_.persp = loc(tree_program_, "persp");
  tree_u_.view = loc(tree_program_, "view");
  tree_u_.transform = loc(tree_program_, "transform");
  tree_u_.lightdir = loc(tree_program_, "lightdir");
  tree_u_.camerapos = loc(tree_program_, "camerapos");
  tree_u_.time = loc(tree_program_, "time");
  tree_u_.viewdist = loc(tree_program_, "viewdist");
  tree_u_.texture = loc(tree_program_, "tex");
  tree_u_.wind = loc(tree_program_, "windstrength");

  water_u_.persp = loc(water_program_, "persp");
  water_u_.view = loc(water_program_, "view");
  water_u_.transform = loc(water_program_, "transform");
  water_u_.camerapos = loc(water_program_, "camerapos");
  water_u_.time = loc(water_program_, "time");
  water_u_.viewdist = loc(water_program_, "viewdist");
  water_u_.lightdir = loc(water_program_, "lightdir");
  water_u_.dudv = loc(water_program_, "water_dudv");
  water_u_.normal1 = loc(water_program_, "water_normal1");
  water_u_.normal2 = loc(water_program_, "water_normal2");

  sky_u_.persp = loc(sky_program_, "persp");
  sky_u_.view = loc(sky_program_, "view");
  sky_u_.skybox = loc(sky_program_, "skybox");
  solid_u_.colour = loc(solid_program_, "colour");
  present_u_.texture = loc(present_program_, "tex");

  if (!load_textures(asset_dir_, error)) return false;
  make_buffers();

  pine_template_ = infworld::make_pine_tree(settings_.pine_detail());
  leafy_template_ = infworld::make_leafy_tree(settings_.tree_detail());
  world_seed_ = infworld::make_seed(static_cast<int>(seed_));

  for (int i = 0; i < infworld::LOD_LEVELS; ++i) {
    const float scale = infworld::CHUNK_SZ * std::pow(infworld::LOD_SCALE, i);
    tables_[i].init(settings_.range, scale, settings_.precision(), &world_seed_);
    gpu_chunks_[i].assign(static_cast<size_t>(tables_[i].size()) * tables_[i].size(), GpuChunk{});
  }
  decorations_.init(6, infworld::CHUNK_SZ, settings_.trees, &world_seed_);
  gpu_trees_.assign(static_cast<size_t>(decorations_.size()) * decorations_.size(), GpuTrees{});
  quality_ = 1.0;
  last_time_ = -1;
  ready_ = true;
  return true;
}

void App::release() {
  if (!ready_) return;
  for (int i = 0; i < infworld::LOD_LEVELS; ++i) {
    for (const GpuChunk& chunk : gpu_chunks_[i])
      if (chunk.vbo) glDeleteBuffers(1, &chunk.vbo);
    gpu_chunks_[i].clear();
    if (terrain_grid_[i]) glDeleteBuffers(1, &terrain_grid_[i]);
    terrain_grid_[i] = 0;
  }
  for (const GpuTrees& trees : gpu_trees_) {
    if (trees.vbo) glDeleteBuffers(1, &trees.vbo);
    if (trees.ibo) glDeleteBuffers(1, &trees.ibo);
  }
  gpu_trees_.clear();
  if (terrain_indices_) glDeleteBuffers(1, &terrain_indices_);
  if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
  if (sky_vbo_) glDeleteBuffers(1, &sky_vbo_);
  if (sky_ibo_) glDeleteBuffers(1, &sky_ibo_);
  if (fbo_) glDeleteFramebuffers(1, &fbo_);
  if (fbo_color_) glDeleteTextures(1, &fbo_color_);
  if (fbo_depth_) glDeleteRenderbuffers(1, &fbo_depth_);
  for (unsigned tex : water_texture_) {
    if (tex) glDeleteTextures(1, &tex);
  }
  for (unsigned tex : {pine_texture_, leafy_texture_, skybox_texture_}) {
    if (tex) glDeleteTextures(1, &tex);
  }
  for (unsigned tex : terrain_texture_) {
    if (tex) glDeleteTextures(1, &tex);
  }
  for (unsigned prog : {terrain_program_, tree_program_, water_program_, sky_program_,
                        solid_program_, present_program_}) {
    if (prog) glDeleteProgram(prog);
  }
#ifdef SANDCLOCK_CORE
  if (vao_) glDeleteVertexArrays(1, &vao_);
#endif
  terrain_indices_ = quad_vbo_ = sky_vbo_ = sky_ibo_ = 0;
  terrain_texture_[0] = terrain_texture_[1] = terrain_texture_[2] = terrain_texture_[3] = 0;
  water_texture_[0] = water_texture_[1] = water_texture_[2] = 0;
  pine_texture_ = leafy_texture_ = skybox_texture_ = 0;
  terrain_program_ = tree_program_ = water_program_ = sky_program_ = solid_program_ =
      present_program_ = 0;
  fbo_ = fbo_color_ = fbo_depth_ = 0;
  ready_ = false;
}

// ---- Camera and world streaming -------------------------------------------------

void App::start_camera(double now) {
  start_time_ = now;
  camera_started_ = true;
  float best = -1e9f;
  Vec3 best_pos{0.0f, static_cast<float>(settings_.height), 0.0f};
  for (int k = 0; k < 16; ++k) {
    const float angle = static_cast<float>(k) * 2.399963f + static_cast<float>(seed_ % 1000) * 0.01f;
    const float radius = static_cast<float>(k) * 1700.0f;
    const float x = std::cos(angle) * radius;
    const float z = std::sin(angle) * radius;
    const float h = infworld::world_height(x, z, world_seed_);
    if (h > 8.0f) {
      best_pos = {x, h + settings_.height, z};
      best = h;
      break;
    }
    if (h > best) {
      best = h;
      best_pos = {x, std::max(h, 0.0f) + settings_.height, z};
    }
  }
  camera_.position = best_pos;
  camera_.yaw = static_cast<float>(seed_ % 6283) * 0.001f;
  camera_.pitch = 0.12f;
}

void App::update_camera(double now, double dt) {
  const double t = now - start_time_;
  const float dtf = static_cast<float>(dt);
  float yaw_rate = 0, speed_mul = 1;
  switch (settings_.mode) {
    case 1:  // circle
      yaw_rate = 0.07f;
      speed_mul = 0.75f;
      break;
    case 2:  // drift
      yaw_rate = 0.05f * std::sin(static_cast<float>(t) * 0.035f);
      speed_mul = 0.30f;
      break;
    default:  // glide
      yaw_rate = 0.020f * std::sin(static_cast<float>(t) * 0.045f + 0.5f) +
                 0.010f * std::sin(static_cast<float>(t) * 0.013f);
      speed_mul = 1.0f;
      break;
  }
  if (!settings_.wander) yaw_rate *= 0.3f;
  camera_.yaw += yaw_rate * dtf;
  const float speed = settings_.speed * speed_mul;
  camera_.position.x += std::sin(camera_.yaw) * speed * dtf;
  camera_.position.z += -std::cos(camera_.yaw) * speed * dtf;

  const float ground = infworld::world_height(camera_.position.x, camera_.position.z, world_seed_);
  const float target_y = std::max(ground, 0.0f) + settings_.height;
  camera_.position.y += (target_y - camera_.position.y) * (1.0f - std::exp(-dtf * 1.6f));
  camera_.position.y = std::max(camera_.position.y, ground + 8.0f);

  float target_pitch = 0.11f;
  if (settings_.wander) {
    target_pitch += 0.030f * std::sin(static_cast<float>(t) * 0.07f) +
                    0.015f * std::sin(static_cast<float>(t) * 0.19f + 1.0f);
  }
  camera_.pitch += (target_pitch - camera_.pitch) * (1.0f - std::exp(-dtf * 0.8f));
}

void App::update_quality(double now, double dt) {
  (void)now;
  if (!settings_.adaptive) {
    quality_ = 1.0;
    return;
  }
  if (dt > 0.045)
    ++slow_frames_;
  else if (slow_frames_ > 0)
    --slow_frames_;
  quality_timer_ += dt;
  if (quality_timer_ < 1.0) return;
  quality_timer_ = 0;
  if (slow_frames_ > 18 && quality_ > 0.45) {
    quality_ = std::max(0.45, quality_ - 0.10);
    slow_frames_ = 0;
  } else if (slow_frames_ < 4 && quality_ < 1.0) {
    quality_ = std::min(1.0, quality_ + 0.05);
    slow_frames_ = 0;
  }
}

void App::upload_terrain(int lod) { (void)lod; }

void App::upload_trees(int slot) {
  GpuTrees& gpu = gpu_trees_[slot];
  const infworld::DecorationChunk& chunk = decorations_.chunk(slot);
  const infworld::TreeMesh mesh =
      infworld::bake_trees(pine_template_, leafy_template_, chunk.trees);
  if (!gpu.vbo) glGenBuffers(1, &gpu.vbo);
  glBindBuffer(GL_ARRAY_BUFFER, gpu.vbo);
  glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(mesh.verts.size() * sizeof(mesh.verts[0])),
               mesh.verts.empty() ? nullptr : mesh.verts.data(), GL_STATIC_DRAW);
  if (!gpu.ibo) glGenBuffers(1, &gpu.ibo);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, gpu.ibo);
  glBufferData(GL_ELEMENT_ARRAY_BUFFER,
               static_cast<GLsizeiptr>(mesh.indices.size() * sizeof(mesh.indices[0])),
               mesh.indices.empty() ? nullptr : mesh.indices.data(), GL_STATIC_DRAW);
  gpu.pine_count = mesh.pine_indices();
  gpu.leafy_count = mesh.leafy_indices();
  gpu.serial = chunk.serial;
  gpu.uploaded = true;
}

void App::follow_and_build(double dt) {
  (void)dt;
  static const int base_budget[infworld::LOD_LEVELS] = {18, 12, 9, 7, 6};
  const float budget_scale = settings_.detail == 0 ? 1.6f : (settings_.detail == 1 ? 1.0f : 0.55f);
  for (int i = 0; i < infworld::LOD_LEVELS; ++i) {
    tables_[i].follow(camera_.position.x, camera_.position.z);
    const int budget = std::max(1, static_cast<int>(base_budget[i] * budget_scale));
    std::vector<int> built;
    tables_[i].build(budget, &built);
    for (int slot : built) {
      const infworld::TerrainChunk& chunk = tables_[i].chunk(slot);
      GpuChunk& gpu = gpu_chunks_[i][slot];
      if (!gpu.vbo) glGenBuffers(1, &gpu.vbo);
      glBindBuffer(GL_ARRAY_BUFFER, gpu.vbo);
      glBufferData(GL_ARRAY_BUFFER,
                   static_cast<GLsizeiptr>(chunk.verts.size() * sizeof(float)),
                   chunk.verts.data(), GL_DYNAMIC_DRAW);
      gpu.uploaded = true;
      gpu.serial = chunk.serial;
    }
  }

  // Decoration chunks are generated synchronously on re-centre; bake a few per frame.
  decorations_.follow(camera_.position.x, camera_.position.z);
  int budget = settings_.detail == 0 ? 10 : (settings_.detail == 1 ? 6 : 4);
  for (int slot = 0; slot < static_cast<int>(gpu_trees_.size()) && budget > 0; ++slot) {
    const infworld::DecorationChunk& chunk = decorations_.chunk(slot);
    if (!chunk.ready) continue;
    if (gpu_trees_[slot].uploaded && gpu_trees_[slot].serial == chunk.serial) continue;
    upload_trees(slot);
    --budget;
  }
}

// ---- Drawing --------------------------------------------------------------------

bool App::ensure_target(int width, int height) {
  if (fbo_ && fbo_width_ == width && fbo_height_ == height) return true;
  if (fbo_) glDeleteFramebuffers(1, &fbo_);
  if (fbo_color_) glDeleteTextures(1, &fbo_color_);
  if (fbo_depth_) glDeleteRenderbuffers(1, &fbo_depth_);
  fbo_ = fbo_color_ = fbo_depth_ = 0;
  fbo_width_ = fbo_height_ = 0;

  glGenTextures(1, &fbo_color_);
  glBindTexture(GL_TEXTURE_2D, fbo_color_);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glGenRenderbuffers(1, &fbo_depth_);
  glBindRenderbuffer(GL_RENDERBUFFER, fbo_depth_);
  glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT16, width, height);
  glGenFramebuffers(1, &fbo_);
  glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
  glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, fbo_color_, 0);
  glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, fbo_depth_);
  const GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
  glBindFramebuffer(GL_FRAMEBUFFER, 0);
  if (status != GL_FRAMEBUFFER_COMPLETE) {
    glDeleteFramebuffers(1, &fbo_);
    glDeleteTextures(1, &fbo_color_);
    glDeleteRenderbuffers(1, &fbo_depth_);
    fbo_ = fbo_color_ = fbo_depth_ = 0;
    return false;
  }
  fbo_width_ = width;
  fbo_height_ = height;
  return true;
}

void App::render(double now, int fb_width, int fb_height) {
  if (!ready_ || fb_width <= 0 || fb_height <= 0) return;
  if (!camera_started_) start_camera(now);
  double dt = last_time_ < 0 ? 1.0 / 60.0 : now - last_time_;
  last_time_ = now;
  dt = std::max(0.0, std::min(0.1, dt));

  update_camera(now, dt);
  update_quality(now, dt);
  follow_and_build(dt);

  const float viewdist = infworld::CHUNK_SZ * infworld::SCALE * 2.0f * settings_.range *
                         std::pow(infworld::LOD_SCALE, infworld::LOD_LEVELS - 2);
  const float effective_viewdist = viewdist * static_cast<float>(quality_);

  int target_w = fb_width, target_h = fb_height;
  if (settings_.draw_res != 1) {
    const int cap = settings_.draw_res == 0 || settings_.draw_res == 2
                        ? kMaxDrawRes
                        : (settings_.draw_res == 3 ? 720 : 540);
    if (target_h > cap) {
      const float scale = static_cast<float>(cap) / target_h;
      target_h = cap;
      target_w = std::max(1, static_cast<int>(fb_width * scale));
    }
  }
  bool offscreen = target_w != fb_width || target_h != fb_height;
  if (offscreen && !ensure_target(target_w, target_h)) {
    offscreen = false;
    target_w = fb_width;
    target_h = fb_height;
  }

  glu::SavedState saved;
  int depth_func = GL_LESS, cull_mode = GL_BACK;
  glGetIntegerv(GL_DEPTH_FUNC, &depth_func);
  glGetIntegerv(GL_CULL_FACE_MODE, &cull_mode);
  unsigned char depth_mask = 1;
  glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_mask);

  glBindFramebuffer(GL_FRAMEBUFFER, offscreen ? fbo_ : static_cast<unsigned>(saved.fbo));
  glViewport(0, 0, target_w, target_h);
  glClearColor(0.5f, 0.8f, 1.0f, 1.0f);
  glDepthMask(GL_TRUE);
  glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
  glEnable(GL_DEPTH_TEST);
  glDepthFunc(GL_LEQUAL);

  const float aspect = static_cast<float>(target_w) / target_h;
  const float fovy = 75.0f * PI / 180.0f;
  const Mat4 persp = Mat4::perspective(fovy, aspect, 6.0f, 30000.0f);
  const Mat4 view = camera_.view();
  const infworld::Frustum frustum =
      infworld::make_frustum(camera_.position, camera_.forward(), camera_.right(),
                             camera_.up(), 6.0f, effective_viewdist + 500.0f, aspect, fovy);
  const Vec3 lightdir = infworld::normalize({-1, -1, -1});

  last_chunks_ = 0;
  last_trees_ = 0;

#ifdef SANDCLOCK_CORE
  glBindVertexArray(vao_);
#endif

  // Terrain, finest ring first.
  glUseProgram(terrain_program_);
  for (int i = 0; i < 4; ++i) {
    glActiveTexture(GL_TEXTURE0 + i);
    glBindTexture(GL_TEXTURE_2D, terrain_texture_[i]);
    glUniform1i(terrain_u_.terrain[i], i);
  }
  glActiveTexture(GL_TEXTURE0);
  glUniformMatrix4fv(terrain_u_.persp, 1, GL_FALSE, persp.m);
  glUniformMatrix4fv(terrain_u_.view, 1, GL_FALSE, view.m);
  glUniform3f(terrain_u_.lightdir, lightdir.x, lightdir.y, lightdir.z);
  glUniform3f(terrain_u_.camerapos, camera_.position.x, camera_.position.y, camera_.position.z);
  glUniform1f(terrain_u_.maxheight, infworld::HEIGHT);
  glUniform1f(terrain_u_.viewdist, effective_viewdist);
  glEnable(GL_CULL_FACE);
  glCullFace(GL_BACK);
  glEnable(GL_POLYGON_OFFSET_FILL);
  for (int lod = 0; lod < infworld::LOD_LEVELS; ++lod) {
    lod_drawn_[lod] = 0;
    const infworld::ChunkTable& table = tables_[lod];
    const float cs = table.chunk_scale();
    const float world_size = 2.0f * cs * infworld::SCALE;
    const float half_extent = cs * infworld::SCALE;
    const int inner = lod == 0 ? 0 : tables_[lod - 1].range() / 2;
    const float fine_extent =
        lod == 0 ? 0.0f
                 : (tables_[lod - 1].range() + 0.5f) * (cs * 0.5f) * infworld::SCALE * 0.95f;
    glUniform1f(terrain_u_.minrange, fine_extent);
    glPolygonOffset(lod * 1.5f, lod * 3.0f);

    glBindBuffer(GL_ARRAY_BUFFER, terrain_grid_[lod]);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, nullptr);
    glEnableVertexAttribArray(0);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, terrain_indices_);

    for (int slot = 0; slot < static_cast<int>(gpu_chunks_[lod].size()); ++slot) {
      const GpuChunk& gpu = gpu_chunks_[lod][slot];
      if (!gpu.uploaded) continue;
      const infworld::Vec2i p = table.position(slot);
      if (inner > 0 && std::abs(p.x - table.center_x()) < inner &&
          std::abs(p.z - table.center_z()) < inner)
        continue;
      const Vec3 center{p.x * world_size, 0.0f, p.z * world_size};
      const float dx = center.x - camera_.position.x, dz = center.z - camera_.position.z;
      if (std::sqrt(dx * dx + dz * dz) > effective_viewdist + world_size)
        continue;
      if (!infworld::intersects(frustum, center,
                                {half_extent, infworld::HEIGHT * infworld::SCALE, half_extent}))
        continue;
      const Mat4 transform = Mat4::scale({infworld::SCALE, infworld::SCALE, infworld::SCALE}) *
                             Mat4::translate({p.x * 2.0f * cs, 0.0f, p.z * 2.0f * cs});
      glUniformMatrix4fv(terrain_u_.transform, 1, GL_FALSE, transform.m);
      glBindBuffer(GL_ARRAY_BUFFER, gpu.vbo);
      glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 0, nullptr);
      glEnableVertexAttribArray(1);
      glDrawElements(GL_TRIANGLES, static_cast<GLsizei>(terrain_index_count_), GL_UNSIGNED_SHORT,
                     nullptr);
      ++last_chunks_;
      ++lod_drawn_[lod];
    }
  }
  glDisable(GL_POLYGON_OFFSET_FILL);

  // Trees. Leaves are single-sided planes, so no back-face culling.
  glDisable(GL_CULL_FACE);
  glDepthMask(GL_TRUE);
  glUseProgram(tree_program_);
  glUniformMatrix4fv(tree_u_.persp, 1, GL_FALSE, persp.m);
  glUniformMatrix4fv(tree_u_.view, 1, GL_FALSE, view.m);
  glUniform3f(tree_u_.lightdir, lightdir.x, lightdir.y, lightdir.z);
  glUniform3f(tree_u_.camerapos, camera_.position.x, camera_.position.y, camera_.position.z);
  glUniform1f(tree_u_.viewdist, effective_viewdist);
  glUniform1f(tree_u_.time, static_cast<float>(now - start_time_));
  glUniform1f(tree_u_.wind, 1.0f);
  glUniform1i(tree_u_.texture, 0);
  for (int slot = 0; slot < static_cast<int>(gpu_trees_.size()); ++slot) {
    const GpuTrees& gpu = gpu_trees_[slot];
    if (!gpu.uploaded || (gpu.pine_count == 0 && gpu.leafy_count == 0)) continue;
    const Vec3 center = decorations_.chunk(slot).center;
    const float dx = center.x - camera_.position.x, dz = center.z - camera_.position.z;
    if (std::sqrt(dx * dx + dz * dz) > effective_viewdist + 200.0f) continue;
    if (!infworld::intersects(frustum, {center.x, 120.0f, center.z},
                              {infworld::CHUNK_SZ * infworld::SCALE + 40.0f, 260.0f,
                               infworld::CHUNK_SZ * infworld::SCALE + 40.0f}))
      continue;
    const Mat4 transform = Mat4::translate(center);
    glUniformMatrix4fv(tree_u_.transform, 1, GL_FALSE, transform.m);
    glBindBuffer(GL_ARRAY_BUFFER, gpu.vbo);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(infworld::TreeVertex), nullptr);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof(infworld::TreeVertex),
                          reinterpret_cast<const void*>(3 * sizeof(float)));
    glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, sizeof(infworld::TreeVertex),
                          reinterpret_cast<const void*>(5 * sizeof(float)));
    glVertexAttribPointer(3, 1, GL_FLOAT, GL_FALSE, sizeof(infworld::TreeVertex),
                          reinterpret_cast<const void*>(8 * sizeof(float)));
    glEnableVertexAttribArray(0);
    glEnableVertexAttribArray(1);
    glEnableVertexAttribArray(2);
    glEnableVertexAttribArray(3);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, gpu.ibo);
    if (gpu.pine_count) {
      glBindTexture(GL_TEXTURE_2D, pine_texture_);
      glDrawElements(GL_TRIANGLES, static_cast<GLsizei>(gpu.pine_count), GL_UNSIGNED_SHORT,
                     nullptr);
      ++last_trees_;
    }
    if (gpu.leafy_count) {
      glBindTexture(GL_TEXTURE_2D, leafy_texture_);
      glDrawElements(GL_TRIANGLES, static_cast<GLsizei>(gpu.leafy_count), GL_UNSIGNED_SHORT,
                     reinterpret_cast<const void*>(gpu.pine_count * sizeof(unsigned short)));
      ++last_trees_;
    }
  }

  // Water, a single plane that follows the camera.
  if (settings_.water) {
    glUseProgram(water_program_);
    for (int i = 0; i < 3; ++i) {
      glActiveTexture(GL_TEXTURE0 + i);
      glBindTexture(GL_TEXTURE_2D, water_texture_[i]);
    }
    glUniform1i(water_u_.dudv, 0);
    glUniform1i(water_u_.normal1, 1);
    glUniform1i(water_u_.normal2, 2);
    glActiveTexture(GL_TEXTURE0);
    glUniformMatrix4fv(water_u_.persp, 1, GL_FALSE, persp.m);
    glUniformMatrix4fv(water_u_.view, 1, GL_FALSE, view.m);
    glUniform3f(water_u_.lightdir, lightdir.x, lightdir.y, lightdir.z);
    glUniform3f(water_u_.camerapos, camera_.position.x, camera_.position.y, camera_.position.z);
    glUniform1f(water_u_.time, static_cast<float>(now - start_time_));
    glUniform1f(water_u_.viewdist, effective_viewdist);
    const float extent = effective_viewdist * 1.6f;
    const Mat4 transform = Mat4::translate({camera_.position.x, 0.0f, camera_.position.z}) *
                           Mat4::scale({extent, 1.0f, extent});
    glUniformMatrix4fv(water_u_.transform, 1, GL_FALSE, transform.m);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, nullptr);
    glEnableVertexAttribArray(0);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDepthMask(GL_FALSE);
    glDrawArrays(GL_TRIANGLES, 0, 6);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
  }

  // Skybox, last, at the far plane.
  glUseProgram(sky_program_);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_CUBE_MAP, skybox_texture_);
  glUniform1i(sky_u_.skybox, 0);
  glUniformMatrix4fv(sky_u_.persp, 1, GL_FALSE, persp.m);
  const Mat4 sky_view = infworld::rotation_of(view);
  glUniformMatrix4fv(sky_u_.view, 1, GL_FALSE, sky_view.m);
  glBindBuffer(GL_ARRAY_BUFFER, sky_vbo_);
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, nullptr);
  glEnableVertexAttribArray(0);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, sky_ibo_);
  glEnable(GL_CULL_FACE);
  glCullFace(GL_FRONT);
  glDepthMask(GL_FALSE);
  glDrawElements(GL_TRIANGLES, 36, GL_UNSIGNED_SHORT, nullptr);
  glDepthMask(GL_TRUE);
  glCullFace(GL_BACK);
  glBindTexture(GL_TEXTURE_CUBE_MAP, 0);

  if (offscreen) {
    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<unsigned>(saved.fbo));
    glViewport(0, 0, fb_width, fb_height);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);
    glUseProgram(present_program_);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, fbo_color_);
    glUniform1i(present_u_.texture, 0);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, nullptr);
    glEnableVertexAttribArray(0);
    glDrawArrays(GL_TRIANGLES, 0, 6);
  }

  if (settings_.dim > 0) {
    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<unsigned>(saved.fbo));
    glViewport(0, 0, fb_width, fb_height);
    glDisable(GL_DEPTH_TEST);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glUseProgram(solid_program_);
    glUniform4f(solid_u_.colour, 0.0f, 0.0f, 0.0f, settings_.dim / 100.0f);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, nullptr);
    glEnableVertexAttribArray(0);
    glDrawArrays(GL_TRIANGLES, 0, 6);
    glDisable(GL_BLEND);
  }

  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, 0);
  glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
  glDepthFunc(static_cast<GLenum>(depth_func));
  glCullFace(static_cast<GLenum>(cull_mode));
  glDepthMask(depth_mask ? GL_TRUE : GL_FALSE);
}

}  // namespace infworldgl
}  // namespace sandclock

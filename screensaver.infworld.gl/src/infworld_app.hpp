// Endless World (OpenGL): an autopilot flight over an endless procedural landscape,
// drawn from infworld's world model. Terrain rings, trees, water and sky are all plain
// GL 2.1 / GLES 2.0 draws, so the same code runs in Kodi on macOS (3.2 core) and on
// 64-bit and 32-bit Android.
#pragma once

#include <string>
#include <vector>

#include "infworld.hpp"

namespace sandclock {
namespace infworldgl {

class App {
 public:
  App();
  ~App();

  // The add-on path must contain terraintextures.png, watermaps.png, pinetreetexture.png,
  // treetexture.png and skybox/skybox_*.png.
  bool init(const infworld::Settings& settings, unsigned seed, const std::string& asset_dir,
            std::string* error);
  void release();

  void render(double now, int fb_width, int fb_height);

  const infworld::Settings& settings() const { return settings_; }
  unsigned seed() const { return seed_; }
  int chunks_drawn() const { return last_chunks_; }
  int trees_drawn() const { return last_trees_; }
  double quality() const { return quality_; }
  const infworld::Vec3& camera_position() const { return camera_.position; }
  int lod_drawn(int lod) const { return lod_drawn_[lod]; }

 private:
  struct Camera {
    infworld::Vec3 position;
    float yaw = 0, pitch = 0.12f;
    infworld::Vec3 forward() const;
    infworld::Vec3 right() const;
    infworld::Vec3 up() const;
    infworld::Mat4 view() const;
  };

  struct SceneUniforms {
    int persp = -1, view = -1, transform = -1, lightdir = -1, camerapos = -1, time = -1,
        viewdist = -1;
  };
  struct TerrainUniforms : SceneUniforms {
    int terrain[4] = {-1, -1, -1, -1}, maxheight = -1, minrange = -1;
  };
  struct TreeUniforms : SceneUniforms {
    int texture = -1, wind = -1;
  };
  struct WaterUniforms : SceneUniforms {
    int dudv = -1, normal1 = -1, normal2 = -1;
  };
  struct SkyUniforms {
    int persp = -1, view = -1, skybox = -1;
  };
  struct SolidUniforms {
    int colour = -1;
  };
  struct PresentUniforms {
    int texture = -1;
  };

  struct GpuChunk {
    unsigned vbo = 0;
    unsigned serial = 0;
    bool uploaded = false;
  };
  struct GpuTrees {
    unsigned vbo = 0, ibo = 0;
    unsigned serial = 0;
    bool uploaded = false;
    unsigned pine_count = 0, leafy_count = 0;
  };

  bool make_program(const char* vertex, const char* fragment, const char* const* attributes,
                    int attribute_count, unsigned* program, std::string* error);
  bool load_textures(const std::string& dir, std::string* error);
  bool load_texture(const std::string& path, unsigned* texture, bool mipmaps, std::string* error);
  bool load_palette(const std::string& path, unsigned textures[4], std::string* error);
  bool load_watermaps(const std::string& path, unsigned textures[3], std::string* error);
  bool load_cubemap(const std::string& dir, unsigned* texture, std::string* error);
  void make_buffers();
  void destroy_buffers();

  void start_camera(double now);
  void update_camera(double now, double dt);
  void update_quality(double now, double dt);
  void rebuild_tables();
  void follow_and_build(double dt);
  void upload_terrain(int lod);
  void upload_trees(int slot);

  void draw_scene(int width, int height);
  void draw_terrain(int width, int height);
  void draw_trees();
  void draw_water();
  void draw_sky(const infworld::Mat4& persp, const infworld::Mat4& view);
  void draw_dim(int width, int height);
  bool ensure_target(int width, int height);

  infworld::Settings settings_;
  unsigned seed_ = 0;
  std::string asset_dir_;
  bool ready_ = false;

  infworld::WorldSeed world_seed_;
  infworld::ChunkTable tables_[infworld::LOD_LEVELS];
  infworld::DecorationTable decorations_;

  Camera camera_;
  bool camera_started_ = false;
  double start_time_ = 0;
  double last_time_ = 0;
  double quality_ = 1.0;
  double quality_timer_ = 0;
  int slow_frames_ = 0;

  unsigned terrain_program_ = 0, tree_program_ = 0, water_program_ = 0, sky_program_ = 0,
           solid_program_ = 0, present_program_ = 0;
  TerrainUniforms terrain_u_;
  TreeUniforms tree_u_;
  WaterUniforms water_u_;
  SkyUniforms sky_u_;
  SolidUniforms solid_u_;
  PresentUniforms present_u_;

  unsigned terrain_texture_[4] = {0, 0, 0, 0}, water_texture_[3] = {0, 0, 0}, pine_texture_ = 0,
           leafy_texture_ = 0, skybox_texture_ = 0;
  unsigned terrain_grid_[infworld::LOD_LEVELS] = {0, 0, 0, 0, 0};
  unsigned terrain_indices_ = 0;
  unsigned terrain_index_count_ = 0;
  std::vector<GpuChunk> gpu_chunks_[infworld::LOD_LEVELS];
  std::vector<GpuTrees> gpu_trees_;
  infworld::TreeMesh pine_template_, leafy_template_;

  unsigned water_vbo_ = 0, water_ibo_ = 0, water_index_count_ = 0;
  unsigned sky_vbo_ = 0, sky_ibo_ = 0;
  unsigned quad_vbo_ = 0;
  unsigned fbo_ = 0, fbo_color_ = 0, fbo_depth_ = 0;
  int fbo_width_ = 0, fbo_height_ = 0;
#ifdef SANDCLOCK_CORE
  unsigned vao_ = 0;
#endif

  int last_chunks_ = 0, last_trees_ = 0;
  int lod_drawn_[infworld::LOD_LEVELS] = {0, 0, 0, 0, 0};
  int last_width_ = 0, last_height_ = 0;
};

}  // namespace infworldgl
}  // namespace sandclock

// Growing Plant (OpenGL): one procedural plant grows from a seed to full size while the camera
// circles it, then a new plant and a new sky take over. Everything is drawn from the plant's node
// graph with plain GL 2.1 / GLES 2.0 / GL 3.2-core draws, so the same renderer runs in Kodi on
// macOS and on Android.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "plant_growth.hpp"
#include "twol/plant.hpp"

namespace plantgl {

struct Settings {
  int preset = 0;       // 0 auto, 1 tree, 2 bush, 3 fern, 4 fan-leaf plant, 5 L-system
  int seed = 0;         // 0 = a new sequence every start, 1-999 = repeatable
  int quality = 1;      // 0 low, 1 normal, 2 high
  int leaf_density = 1; // 0 sparse, 1 normal, 2 lush
  int growth_speed = 1; // 0 slow, 1 normal, 2 fast, 3 very fast
  int hold_seconds = 14;
  int motion = 0;       // 0 auto, 1 orbit, 2 sway, 3 spiral, 4 crane, 5 still
  int camera_speed = 100;
  int framing = 0;      // 0 normal, 1 close, 2 wide
  int background = 0;   // 0 auto, 1 dawn, 2 meadow, 3 dusk, 4 night, 5 studio, 6 aurora
  bool particles = true;
  bool ground = true;
  int dim = 0;
  void sanitise();
};

struct Mat4 {
  float m[16] = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f,
                 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
};

// One sky / lighting recipe. The background shader reads the colours and amounts, the plant
// shader reads the light, and the particles and ground borrow colours from the same palette.
struct Look {
  twol::Vec3 zenith, horizon, glow, cloud, sun, ambient, rim, ground, particle;
  float cloud_amount = 0.0f, star_amount = 0.0f, aurora_amount = 0.0f, studio_amount = 0.0f;
  float sun_size = 0.05f, sun_disc = 1.0f;
  twol::Vec3 light_dir{0.4f, 0.7f, 0.5f};
};

class App {
 public:
  App();
  ~App();

  bool init(const Settings& settings, unsigned seed, std::string* error);
  void release();
  void render(double now, int width, int height);

  const Settings& settings() const { return settings_; }
  unsigned seed() const { return seed_; }
  int preset_index() const { return preset_index_; }
  int background_index() const { return background_index_; }
  int motion_index() const { return motion_index_; }
  int vertex_count() const { return static_cast<int>(mesh_.vertex_count); }
  int triangle_count() const { return static_cast<int>(mesh_.triangle_count); }
  int batch_count() const { return static_cast<int>(gpu_batches_.size()); }
  int leaf_clusters() const { return mesh_.leaf_clusters; }
  int branch_segments() const { return mesh_.branch_segments; }
  float plant_height() const { return mesh_.height; }
  double growth01() const { return last_t_; }
  double fade() const { return fade_; }

 private:
  struct SceneUniforms {
    int view_proj = -1, cam_pos = -1, time01 = -1, time = -1, wind = -1, light_dir = -1,
        ambient = -1, sun_color = -1, rim_color = -1, emissive = -1;
  };
  struct BackgroundUniforms {
    int zenith = -1, horizon = -1, glow = -1, cloud_color = -1, sun_color = -1;
    int cloud_amount = -1, star_amount = -1, aurora_amount = -1, studio_amount = -1;
    int sun_size = -1, sun_visible = -1, sun_uv = -1, time = -1, aspect = -1, resolution = -1;
  };
  struct GroundUniforms {
    int view_proj = -1, ground_radius = -1, ground_color = -1, glow = -1, shadow = -1;
    int time = -1;
  };
  struct ParticleUniforms {
    int view_proj = -1, time = -1, point_scale = -1, color = -1, radius = -1, height = -1,
        amp = -1;
  };
  struct OverlayUniforms {
    int alpha = -1;
  };
  struct GpuBatch {
    unsigned vbo = 0, ibo = 0, vao = 0;
    int index_count = 0;
  };

  bool make_programs(std::string* error);
  void make_static_buffers();
  void destroy_static_buffers();
  void upload_mesh();
  void destroy_mesh_buffers();
  void start_cycle(double now);
  void update_cycle(double now);
  void update_camera(double now, int width, int height);
  void draw_background(int width, int height);
  void draw_ground();
  void draw_plant();
  void draw_particles(int width, int height);
  void draw_overlay();
  void set_scene_uniforms();
  void set_quad_attributes();
  void set_ground_attributes();
  void set_particle_attributes();

  Settings settings_;
  unsigned seed_ = 1;
  bool ready_ = false;

  unsigned scene_program_ = 0, background_program_ = 0, ground_program_ = 0,
           particle_program_ = 0, overlay_program_ = 0;
  SceneUniforms scene_u_;
  BackgroundUniforms background_u_;
  GroundUniforms ground_u_;
  ParticleUniforms particle_u_;
  OverlayUniforms overlay_u_;

  unsigned quad_vbo_ = 0, quad_vao_ = 0;
  unsigned ground_vbo_ = 0, ground_vao_ = 0;
  int ground_vertices_ = 0;
  unsigned particle_vbo_ = 0, particle_vao_ = 0;
  int particle_draw_count_ = 0;

  twol::PlantParameters params_;
  twol::NodeGraph graph_;
  GrowthMesh mesh_;
  std::vector<GpuBatch> gpu_batches_;

  int preset_index_ = 1;
  int background_index_ = 1;
  int motion_index_ = 1;
  int cycle_index_ = 0;
  double cycle_start_ = 0.0;
  double grow_seconds_ = 25.0;
  double fade_seconds_ = 1.6;
  double hold_seconds_ = 14.0;
  double last_t_ = 0.0;
  double fade_ = 0.0;
  double shader_time_ = 0.0;

  twol::Vec3 cam_pos_{0.0f, 2.0f, 8.0f};
  twol::Vec3 cam_target_{0.0f, 2.0f, 0.0f};
  Mat4 view_proj_;
  Look look_;
};

}  // namespace plantgl

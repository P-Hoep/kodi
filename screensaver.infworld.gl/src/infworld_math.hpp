// Small vector/matrix helpers for the Endless World screensaver. The other GPU add-ons
// write their maths by hand; this port of infworld needs matrices, so it has the handful
// of operations glm would provide, with glm's column-major convention.
#pragma once

#include <cmath>

namespace sandclock {
namespace infworld {

struct Vec2 {
  float x = 0, y = 0;
};
struct Vec3 {
  float x = 0, y = 0, z = 0;
};

inline Vec3 operator+(const Vec3& a, const Vec3& b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
inline Vec3 operator-(const Vec3& a, const Vec3& b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
inline Vec3 operator*(const Vec3& a, float s) { return {a.x * s, a.y * s, a.z * s}; }
inline Vec3 operator*(float s, const Vec3& a) { return {a.x * s, a.y * s, a.z * s}; }
inline Vec3 operator-(const Vec3& a) { return {-a.x, -a.y, -a.z}; }
inline Vec3& operator+=(Vec3& a, const Vec3& b) {
  a.x += b.x;
  a.y += b.y;
  a.z += b.z;
  return a;
}
inline Vec3& operator*=(Vec3& a, float s) {
  a.x *= s;
  a.y *= s;
  a.z *= s;
  return a;
}
inline float dot(const Vec3& a, const Vec3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
inline Vec3 cross(const Vec3& a, const Vec3& b) {
  return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
inline float length(const Vec3& a) { return std::sqrt(dot(a, a)); }
inline Vec3 normalize(const Vec3& a) {
  const float l = length(a);
  return l > 1e-20f ? a * (1.0f / l) : Vec3{};
}

// Column-major, like a GLSL mat4: m[column * 4 + row].
struct Mat4 {
  float m[16] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};

  static Mat4 identity() { return Mat4{}; }
  static Mat4 translate(const Vec3& t) {
    Mat4 r;
    r.m[12] = t.x;
    r.m[13] = t.y;
    r.m[14] = t.z;
    return r;
  }
  static Mat4 scale(const Vec3& s) {
    Mat4 r;
    r.m[0] = s.x;
    r.m[5] = s.y;
    r.m[10] = s.z;
    return r;
  }
  static Mat4 rotate_x(float angle) {
    Mat4 r;
    const float c = std::cos(angle), s = std::sin(angle);
    r.m[5] = c;
    r.m[6] = s;
    r.m[9] = -s;
    r.m[10] = c;
    return r;
  }
  static Mat4 rotate_y(float angle) {
    Mat4 r;
    const float c = std::cos(angle), s = std::sin(angle);
    r.m[0] = c;
    r.m[2] = -s;
    r.m[8] = s;
    r.m[10] = c;
    return r;
  }
  static Mat4 rotate_z(float angle) {
    Mat4 r;
    const float c = std::cos(angle), s = std::sin(angle);
    r.m[0] = c;
    r.m[1] = s;
    r.m[4] = -s;
    r.m[5] = c;
    return r;
  }
  static Mat4 perspective(float fovy, float aspect, float znear, float zfar) {
    const float f = 1.0f / std::tan(fovy * 0.5f);
    Mat4 r;
    for (int i = 0; i < 16; ++i) r.m[i] = 0;
    r.m[0] = f / aspect;
    r.m[5] = f;
    r.m[10] = (zfar + znear) / (znear - zfar);
    r.m[11] = -1.0f;
    r.m[14] = (2.0f * zfar * znear) / (znear - zfar);
    return r;
  }
};

inline Mat4 operator*(const Mat4& a, const Mat4& b) {
  Mat4 r;
  for (int c = 0; c < 4; ++c) {
    for (int row = 0; row < 4; ++row) {
      float sum = 0;
      for (int k = 0; k < 4; ++k) sum += a.m[k * 4 + row] * b.m[c * 4 + k];
      r.m[c * 4 + row] = sum;
    }
  }
  return r;
}

inline Vec3 transform_point(const Mat4& m, const Vec3& p) {
  return {m.m[0] * p.x + m.m[4] * p.y + m.m[8] * p.z + m.m[12],
          m.m[1] * p.x + m.m[5] * p.y + m.m[9] * p.z + m.m[13],
          m.m[2] * p.x + m.m[6] * p.y + m.m[10] * p.z + m.m[14]};
}

// Directional transform (no translation), then renormalised.
inline Vec3 transform_direction(const Mat4& m, const Vec3& v) {
  return normalize({m.m[0] * v.x + m.m[4] * v.y + m.m[8] * v.z,
                    m.m[1] * v.x + m.m[5] * v.y + m.m[9] * v.z,
                    m.m[2] * v.x + m.m[6] * v.y + m.m[10] * v.z});
}

// The rotation-only part of a view matrix, for the skybox.
inline Mat4 rotation_of(const Mat4& m) {
  Mat4 r = m;
  r.m[12] = r.m[13] = r.m[14] = 0;
  return r;
}

}  // namespace infworld
}  // namespace sandclock

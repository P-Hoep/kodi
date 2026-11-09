#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace twol {

inline constexpr float pi = 3.14159265358979323846f;
inline constexpr float deg_to_rad = pi / 180.0f;
inline constexpr float rad_to_deg = 180.0f / pi;

struct Vec2 {
    float x = 0.0f;
    float y = 0.0f;
};

struct Vec3 {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

struct Color4 {
    float r = 1.0f;
    float g = 1.0f;
    float b = 1.0f;
    float a = 1.0f;
};

[[nodiscard]] constexpr Vec2 operator+(const Vec2 a, const Vec2 b) noexcept { return {a.x + b.x, a.y + b.y}; }
[[nodiscard]] constexpr Vec2 operator-(const Vec2 a, const Vec2 b) noexcept { return {a.x - b.x, a.y - b.y}; }
[[nodiscard]] constexpr Vec2 operator*(const Vec2 a, const float s) noexcept { return {a.x * s, a.y * s}; }
[[nodiscard]] constexpr Vec2 operator/(const Vec2 a, const float s) noexcept { return {a.x / s, a.y / s}; }

[[nodiscard]] constexpr Vec3 operator+(const Vec3 a, const Vec3 b) noexcept { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
[[nodiscard]] constexpr Vec3 operator-(const Vec3 a, const Vec3 b) noexcept { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
[[nodiscard]] constexpr Vec3 operator-(const Vec3 a) noexcept { return {-a.x, -a.y, -a.z}; }
[[nodiscard]] constexpr Vec3 operator*(const Vec3 a, const float s) noexcept { return {a.x * s, a.y * s, a.z * s}; }
[[nodiscard]] constexpr Vec3 operator*(const float s, const Vec3 a) noexcept { return a * s; }
[[nodiscard]] constexpr Vec3 operator/(const Vec3 a, const float s) noexcept { return {a.x / s, a.y / s, a.z / s}; }

Vec3& operator+=(Vec3& a, Vec3 b) noexcept;
Vec3& operator-=(Vec3& a, Vec3 b) noexcept;
Vec3& operator*=(Vec3& a, float s) noexcept;

[[nodiscard]] float dot(Vec2 a, Vec2 b) noexcept;
[[nodiscard]] float dot(Vec3 a, Vec3 b) noexcept;
[[nodiscard]] Vec3 cross(Vec3 a, Vec3 b) noexcept;
[[nodiscard]] float length(Vec2 v) noexcept;
[[nodiscard]] float length(Vec3 v) noexcept;
[[nodiscard]] Vec2 normalize(Vec2 v) noexcept;
[[nodiscard]] Vec3 normalize(Vec3 v) noexcept;
[[nodiscard]] Vec3 safe_normalize(Vec3 v, Vec3 fallback = {0.0f, 1.0f, 0.0f}) noexcept;
[[nodiscard]] Vec3 lerp(Vec3 a, Vec3 b, float t) noexcept;
[[nodiscard]] float lerp(float a, float b, float t) noexcept;
[[nodiscard]] float clamp01(float v) noexcept;
[[nodiscard]] float saturate(float v) noexcept;
[[nodiscard]] float smoothstep(float edge0, float edge1, float x) noexcept;
[[nodiscard]] Vec3 project_on_plane(Vec3 v, Vec3 normal) noexcept;
[[nodiscard]] Vec3 rotate_around_axis(Vec3 v, Vec3 axis, float radians) noexcept;
[[nodiscard]] Vec3 flatten_for_2d(Vec3 v) noexcept;
[[nodiscard]] Vec3 flatten_for_25d(Vec3 v) noexcept;
[[nodiscard]] float hash01(std::uint32_t x) noexcept;
[[nodiscard]] Color4 mix(Color4 a, Color4 b, float t) noexcept;

} // namespace twol

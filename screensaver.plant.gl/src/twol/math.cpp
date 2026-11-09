#include "twol/math.hpp"

namespace twol {

Vec3& operator+=(Vec3& a, const Vec3 b) noexcept
{
    a.x += b.x;
    a.y += b.y;
    a.z += b.z;
    return a;
}

Vec3& operator-=(Vec3& a, const Vec3 b) noexcept
{
    a.x -= b.x;
    a.y -= b.y;
    a.z -= b.z;
    return a;
}

Vec3& operator*=(Vec3& a, const float s) noexcept
{
    a.x *= s;
    a.y *= s;
    a.z *= s;
    return a;
}

float dot(const Vec2 a, const Vec2 b) noexcept
{
    return a.x * b.x + a.y * b.y;
}

float dot(const Vec3 a, const Vec3 b) noexcept
{
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

Vec3 cross(const Vec3 a, const Vec3 b) noexcept
{
    return {
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    };
}

float length(const Vec2 v) noexcept
{
    return std::sqrt(dot(v, v));
}

float length(const Vec3 v) noexcept
{
    return std::sqrt(dot(v, v));
}

Vec2 normalize(const Vec2 v) noexcept
{
    const float len = length(v);
    if (len <= 0.000001f) {
        return {0.0f, 0.0f};
    }
    return v / len;
}

Vec3 normalize(const Vec3 v) noexcept
{
    const float len = length(v);
    if (len <= 0.000001f) {
        return {0.0f, 0.0f, 0.0f};
    }
    return v / len;
}

Vec3 safe_normalize(const Vec3 v, const Vec3 fallback) noexcept
{
    const float len = length(v);
    if (len <= 0.000001f) {
        return fallback;
    }
    return v / len;
}

Vec3 lerp(const Vec3 a, const Vec3 b, const float t) noexcept
{
    return a * (1.0f - t) + b * t;
}

float lerp(const float a, const float b, const float t) noexcept
{
    return a * (1.0f - t) + b * t;
}

float clamp01(const float v) noexcept
{
    return std::clamp(v, 0.0f, 1.0f);
}

float saturate(const float v) noexcept
{
    return clamp01(v);
}

float smoothstep(const float edge0, const float edge1, const float x) noexcept
{
    if (std::abs(edge1 - edge0) <= 0.000001f) {
        return x >= edge1 ? 1.0f : 0.0f;
    }
    const float t = clamp01((x - edge0) / (edge1 - edge0));
    return t * t * (3.0f - 2.0f * t);
}

Vec3 project_on_plane(const Vec3 v, const Vec3 normal) noexcept
{
    const Vec3 n = safe_normalize(normal);
    return v - n * dot(v, n);
}

Vec3 rotate_around_axis(const Vec3 v, const Vec3 axis, const float radians) noexcept
{
    const Vec3 n = safe_normalize(axis);
    const float c = std::cos(radians);
    const float s = std::sin(radians);
    return v * c + cross(n, v) * s + n * dot(n, v) * (1.0f - c);
}

Vec3 flatten_for_2d(const Vec3 v) noexcept
{
    return {v.x, v.y, 0.0f};
}

Vec3 flatten_for_25d(const Vec3 v) noexcept
{
    return {v.x, v.y, v.z * 0.18f};
}

float hash01(std::uint32_t x) noexcept
{
    x ^= x >> 16U;
    x *= 0x7feb352dU;
    x ^= x >> 15U;
    x *= 0x846ca68bU;
    x ^= x >> 16U;
    return static_cast<float>(x & 0x00FFFFFFU) / static_cast<float>(0x01000000U);
}

Color4 mix(const Color4 a, const Color4 b, const float t) noexcept
{
    return {
        lerp(a.r, b.r, t),
        lerp(a.g, b.g, t),
        lerp(a.b, b.b, t),
        lerp(a.a, b.a, t),
    };
}

} // namespace twol

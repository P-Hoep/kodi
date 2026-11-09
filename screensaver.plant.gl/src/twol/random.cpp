#include "twol/random.hpp"

#include <algorithm>

namespace twol {

Rng::Rng(const std::uint32_t seed) noexcept
    : state_(seed == 0U ? 1U : seed)
{
}

std::uint32_t Rng::next_u32() noexcept
{
    std::uint32_t x = state_;
    x ^= x << 13U;
    x ^= x >> 17U;
    x ^= x << 5U;
    state_ = x == 0U ? 1U : x;
    return state_;
}

float Rng::next01() noexcept
{
    return static_cast<float>(next_u32() & 0x00FFFFFFU) / static_cast<float>(0x01000000U);
}

float Rng::range(const float min_value, const float max_value) noexcept
{
    return min_value + (max_value - min_value) * next01();
}

int Rng::range_int(const int min_value, const int max_value) noexcept
{
    if (max_value <= min_value) {
        return min_value;
    }
    const std::uint32_t span = static_cast<std::uint32_t>(max_value - min_value + 1);
    return min_value + static_cast<int>(next_u32() % span);
}

bool Rng::chance(const float probability01) noexcept
{
    return next01() <= std::clamp(probability01, 0.0f, 1.0f);
}

} // namespace twol

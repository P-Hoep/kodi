#pragma once

#include <cstdint>

namespace twol {

class Rng {
public:
    explicit Rng(std::uint32_t seed = 1U) noexcept;

    [[nodiscard]] std::uint32_t next_u32() noexcept;
    [[nodiscard]] float next01() noexcept;
    [[nodiscard]] float range(float min_value, float max_value) noexcept;
    [[nodiscard]] int range_int(int min_value, int max_value) noexcept;
    [[nodiscard]] bool chance(float probability01) noexcept;

private:
    std::uint32_t state_ = 1U;
};

} // namespace twol

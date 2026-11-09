#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "twol/math.hpp"

namespace twol {

struct LSystemRule {
    char predecessor = 'F';
    std::string successor;
};

struct LSystemDefinition {
    std::string axiom = "F";
    std::vector<LSystemRule> rules;
    float turn_degrees = 25.0f;
    float step_length = 0.12f;
    float width = 0.015f;
    int iterations = 4;
};

struct LSystemLine {
    Vec3 a;
    Vec3 b;
    float radius = 0.01f;
    Color4 color;
};

struct LSystemResult {
    std::string expanded;
    std::vector<LSystemLine> lines;
};

[[nodiscard]] std::string expand_lsystem(const LSystemDefinition& definition);
[[nodiscard]] LSystemResult trace_lsystem_2d(const LSystemDefinition& definition);
[[nodiscard]] LSystemDefinition cannabis_leaf_pattern_definition();
[[nodiscard]] LSystemDefinition plant_pattern_definition();
[[nodiscard]] LSystemDefinition koch_pattern_definition();

} // namespace twol

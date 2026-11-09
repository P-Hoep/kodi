#include "twol/lsystem.hpp"

#include <cmath>

namespace twol {

namespace {

struct Turtle2D {
    Vec3 pos;
    float angle = 90.0f * deg_to_rad;
    float radius = 0.01f;
};

} // namespace

std::string expand_lsystem(const LSystemDefinition& definition)
{
    std::unordered_map<char, std::string> rules;
    for (const LSystemRule& rule : definition.rules) {
        rules[rule.predecessor] = rule.successor;
    }

    std::string current = definition.axiom;
    for (int i = 0; i < definition.iterations; ++i) {
        std::string next;
        next.reserve(current.size() * 3U);
        for (const char symbol : current) {
            const auto it = rules.find(symbol);
            if (it != rules.end()) {
                next += it->second;
            } else {
                next += symbol;
            }
        }
        current = std::move(next);
    }
    return current;
}

LSystemResult trace_lsystem_2d(const LSystemDefinition& definition)
{
    LSystemResult result;
    result.expanded = expand_lsystem(definition);

    Turtle2D turtle;
    turtle.radius = definition.width;

    std::vector<Turtle2D> stack;
    stack.reserve(64U);

    const float turn = definition.turn_degrees * deg_to_rad;
    const Color4 stem_color{0.36f, 0.68f, 0.24f, 1.0f};
    const Color4 accent_color{0.64f, 0.92f, 0.28f, 1.0f};

    for (const char symbol : result.expanded) {
        switch (symbol) {
        case 'F':
        case 'G': {
            const Vec3 dir{std::cos(turtle.angle), std::sin(turtle.angle), 0.0f};
            const Vec3 next = turtle.pos + dir * definition.step_length;
            const float tint = symbol == 'F' ? 0.0f : 0.45f;
            result.lines.push_back({turtle.pos, next, turtle.radius, mix(stem_color, accent_color, tint)});
            turtle.pos = next;
            break;
        }
        case '+':
            turtle.angle += turn;
            break;
        case '-':
            turtle.angle -= turn;
            break;
        case '[':
            stack.push_back(turtle);
            turtle.radius *= 0.74f;
            break;
        case ']':
            if (!stack.empty()) {
                turtle = stack.back();
                stack.pop_back();
            }
            break;
        case '|':
            turtle.angle += pi;
            break;
        default:
            break;
        }
    }

    return result;
}

LSystemDefinition cannabis_leaf_pattern_definition()
{
    return {
        "X",
        {
            {'X', "F[+G][++G][+++G][-G][--G][---G]"},
            {'G', "GG"},
            {'F', "F"},
        },
        18.0f,
        0.09f,
        0.012f,
        3,
    };
}

LSystemDefinition plant_pattern_definition()
{
    return {
        "X",
        {
            {'X', "F+[[X]-X]-F[-FX]+X"},
            {'F', "FF"},
        },
        25.0f,
        0.055f,
        0.01f,
        5,
    };
}

LSystemDefinition koch_pattern_definition()
{
    return {
        "F--F--F",
        {
            {'F', "F+F--F+F"},
        },
        60.0f,
        0.025f,
        0.006f,
        4,
    };
}

} // namespace twol

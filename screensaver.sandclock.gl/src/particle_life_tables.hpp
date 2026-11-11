// The lists the Particle Life settings are built from, and the interaction matrices behind the
// presets. tools/make_settings_particle_life.py writes the same names and sizes to settings.xml;
// keep the two in step.
//
// A preset is a square interaction matrix: row i is how a particle of species i reacts to a
// particle of species j (column j). Positive attracts, negative repels. The numbers are the four
// species rules from the original Particle Life "interesting models" (power sliders divided by
// 100), which is why every preset here has four species. Each preset also carries a second 4 x 4
// matrix of pair radii, divided by that model's mean radius so the global radius setting controls
// the scale: the original gave every pair its own 10..500 px radius slider, and those relative
// reaches are part of what makes each model behave the way it does.
#pragma once

namespace sandclock {
namespace particlelife {

// Settings index -> simulation steps per second. The last entry is "Maximum".
inline constexpr int kSpeeds[] = {30, 45, 60, 90, 120, 180, 240};
inline constexpr int kSpeedCount = (int)(sizeof(kSpeeds) / sizeof(kSpeeds[0]));

// Settings index -> particle count. The very light counts are appended at the end so that the
// index a saved setting already holds keeps meaning the same count.
inline constexpr int kParticles[] = {1024, 2048, 3072, 4096, 6144, 8192,
                                    12288, 16384, 24576, 32768, 768, 512, 256};
inline constexpr int kParticlesCount = (int)(sizeof(kParticles) / sizeof(kParticles[0]));

// Settings index -> seconds between starts over (0 = never).
inline constexpr int kRestarts[] = {0, 60, 120, 300, 600, 1200, 1800, 3600};
inline constexpr int kRestartCount = (int)(sizeof(kRestarts) / sizeof(kRestarts[0]));

// Settings index -> seconds between small rule mutations (0 = never).
inline constexpr int kEvolves[] = {0, 30, 60, 120, 300, 600, 1800};
inline constexpr int kEvolveCount = (int)(sizeof(kEvolves) / sizeof(kEvolves[0]));

// Settings index -> draw target height (0 = automatic up to 1080p, -1 = every output pixel).
// The very small targets are appended at the end, for the same reason as the particle counts.
inline constexpr int kDrawCaps[] = {0, 1080, 720, 540, 360, -1, 270, 180};
inline constexpr int kDrawCount = (int)(sizeof(kDrawCaps) / sizeof(kDrawCaps[0]));

inline constexpr int kStartCount = 6;
inline const char* const kStartNames[kStartCount] = {
    "Scattered", "Disk", "Ring", "Species clusters", "Grid", "Two blobs",
};

inline constexpr int kPaletteCount = 8;
inline const char* const kPaletteNames[kPaletteCount] = {
    "Neon", "Ocean", "Sunset", "Forest", "Candy", "Ice", "Fire", "Mono",
};

// Eight colours per palette, RRGGBB. Species beyond the list reuse colours from the start.
inline constexpr unsigned kPalettes[kPaletteCount][8] = {
    {0xFF4F9A, 0x8B5CF6, 0x38BDF8, 0x34D399, 0xFBBF24, 0xFB7185, 0x5EEAD4, 0xC084FC},
    {0x3FA9F5, 0x1F6FD1, 0x45D6C9, 0x8FE3FF, 0x2A9D8F, 0x6C8CFF, 0xB8F2E6, 0xD6F1FF},
    {0xFF7A45, 0xFFB347, 0xFF4F70, 0xC2448F, 0x8A4FD1, 0xFFD166, 0xF25C54, 0xFFE0B2},
    {0x6BBF59, 0x2E8B57, 0xA3D977, 0xD4C36A, 0x8C6A43, 0x4FA36C, 0xC9E4A6, 0xE8F5C8},
    {0xFF9CEE, 0xB28DFF, 0x85E3FF, 0xBFFCC6, 0xFFF5BA, 0xFFABAB, 0xACE7FF, 0xFFD6F5},
    {0xFFFFFF, 0xD6F1FF, 0xA9DEFF, 0x7CC8F2, 0xC9D6FF, 0xE8F7FF, 0x9FB8D9, 0xF0FAFF},
    {0xFF3B30, 0xFF9500, 0xFFCC00, 0xFF5E3A, 0xFF2D55, 0xFFB340, 0xFF6B00, 0xFFE08A},
    {0xFFFFFF, 0xD9D9D9, 0xB3B3B3, 0x8C8C8C, 0xF2F2F2, 0xA6A6A6, 0xCCCCCC, 0x737373},
};

inline constexpr int kPresetCount = 10;
inline const char* const kPresetNames[kPresetCount] = {
    "DNA", "Worm", "Waves", "Soap", "Photon", "Ladybug", "Flower", "Cells", "Vacuum", "Y",
};

// Row-major. 0 = DNA ... 9 = Y; see the note at the top.
inline constexpr float kPresets[kPresetCount][4][4] = {
    {{ 0.369f, -0.504f, -0.100f,  0.245f},
     { 0.359f, -0.706f,  0.373f,  0.088f},
     {-0.663f,  0.120f, -0.500f,  0.712f},
     {-0.368f,  0.081f, -0.649f,  0.239f}},
    {{ 0.200f,  0.047f, -0.313f,  0.000f},
     {-0.160f, -0.147f,  0.153f,  0.000f},
     {-0.153f, -0.007f,  0.093f,  0.213f},
     { 0.253f,  0.000f, -0.020f, -0.320f}},
    {{ 0.016f,  0.471f, -0.569f, -0.362f},
     { 0.766f, -0.737f, -0.445f, -0.275f},
     {-0.654f,  0.683f, -0.559f,  0.604f},
     {-0.444f,  0.011f, -0.635f, -0.075f}},
    {{-0.625f, -0.564f, -0.651f,  0.049f},
     { 0.522f, -0.536f,  0.461f, -0.094f},
     {-0.573f, -0.415f, -0.616f, -0.149f},
     { 0.293f, -0.480f,  0.619f,  0.200f}},
    {{-0.553f, -0.181f, -0.042f, -0.119f},
     {-0.679f,  0.507f, -0.365f,  0.406f},
     {-0.013f,  0.687f, -0.261f,  0.313f},
     { 0.453f, -0.328f, -0.085f,  0.670f}},
    {{ 0.406f,  0.144f, -0.632f, -0.688f},
     {-0.486f,  0.312f,  0.281f, -0.542f},
     {-0.345f,  0.636f, -0.046f,  0.476f},
     {-0.301f, -0.130f, -0.449f, -0.605f}},
    {{ 0.200f,  0.047f, -0.367f,  0.000f},
     { 0.033f, -0.147f,  0.233f, -0.087f},
     { 0.353f, -0.620f, -0.360f, -0.347f},
     {-0.040f, -0.713f,  0.347f, -0.007f}},
    {{ 0.033f,  0.320f, -0.687f, -0.480f},
     { 0.033f,  0.100f,  0.233f, -0.087f},
     { 0.353f, -0.620f, -0.360f, -0.347f},
     {-0.040f, -0.713f,  0.347f, -0.007f}},
    {{ 0.173f,  0.127f, -0.160f,  0.087f},
     { 0.047f, -0.127f,  0.107f, -0.220f},
     {-0.480f,  0.147f, -0.173f,  0.047f},
     { 0.007f, -0.393f,  0.160f, -0.067f}},
    {{ 0.668f,  0.090f, -0.183f, -0.734f},
     { 0.137f,  0.540f, -0.283f,  0.746f},
     {-0.338f, -0.284f, -0.147f,  0.769f},
     {-0.579f, -0.631f, -0.460f,  0.295f}},
};

// Pair radii for the same ten presets, row-major, as multiples of the mean pair radius (which is
// what the radius setting gives). Extracted from the original model files.
inline constexpr float kPresetRadii[kPresetCount][4][4] = {
    {{0.356f, 1.565f, 0.557f, 0.548f},
     {1.000f, 1.112f, 0.592f, 1.106f},
     {1.012f, 0.900f, 1.107f, 1.877f},
     {2.039f, 1.037f, 0.655f, 0.537f}},
    {{0.852f, 1.616f, 0.449f, 0.535f},
     {0.506f, 0.823f, 2.640f, 0.838f},
     {0.622f, 0.636f, 0.449f, 3.245f},
     {0.679f, 0.607f, 0.694f, 0.809f}},
    {{1.015f, 0.302f, 1.433f, 0.529f},
     {1.855f, 1.057f, 1.050f, 0.223f},
     {1.813f, 0.860f, 0.513f, 0.281f},
     {1.641f, 1.378f, 1.758f, 0.291f}},
    {{1.190f, 1.581f, 1.693f, 1.561f},
     {0.587f, 0.127f, 1.144f, 0.516f},
     {1.765f, 0.555f, 0.187f, 0.621f},
     {0.723f, 1.644f, 1.148f, 0.957f}},
    {{1.279f, 0.790f, 1.241f, 1.041f},
     {1.115f, 1.600f, 0.236f, 0.803f},
     {0.382f, 1.100f, 0.988f, 1.217f},
     {1.271f, 1.170f, 0.256f, 1.510f}},
    {{0.815f, 1.602f, 1.792f, 0.195f},
     {1.505f, 0.846f, 1.416f, 0.139f},
     {1.354f, 1.135f, 0.796f, 0.229f},
     {1.415f, 1.427f, 0.220f, 1.113f}},
    {{0.853f, 1.576f, 0.456f, 0.527f},
     {2.683f, 0.725f, 0.399f, 1.690f},
     {0.413f, 1.051f, 0.385f, 0.668f},
     {0.612f, 2.215f, 1.122f, 0.626f}},
    {{2.788f, 1.206f, 0.354f, 0.853f},
     {2.301f, 0.622f, 0.342f, 1.449f},
     {0.354f, 0.902f, 0.330f, 0.573f},
     {0.525f, 1.900f, 0.963f, 0.537f}},
    {{0.610f, 0.594f, 1.346f, 0.626f},
     {1.586f, 0.562f, 1.763f, 0.578f},
     {0.786f, 0.786f, 0.626f, 1.490f},
     {1.426f, 0.722f, 1.763f, 0.738f}},
    {{0.105f, 1.395f, 0.134f, 0.867f},
     {1.119f, 0.749f, 0.209f, 1.067f},
     {0.933f, 1.587f, 0.603f, 1.515f},
     {1.847f, 1.823f, 0.328f, 1.720f}},
};

}  // namespace particlelife
}  // namespace sandclock

// Audio analysis for the Physarum music visualisation.
//
// Kodi hands a visualisation 44.1 kHz stereo float samples (interleaved, -1..1) on the audio
// thread. AudioAnalyzer mixes them to mono, keeps the most recent window in a small ring buffer
// and, on the render thread, turns that window into the handful of numbers the simulation and the
// draw shader react to: overall level, four broad bands, 32 display bands and a beat impulse.
//
// The analysis is deliberately small: one 1024-point radix-2 FFT per rendered frame (a few
// hundred thousand operations), per-band automatic gain control so quiet tracks still move the
// picture, and a bass-energy beat detector with a refractory period. No external DSP library.
#pragma once

#include <array>
#include <cstddef>
#include <mutex>
#include <vector>

namespace sandclock {
namespace physarum {
namespace audio {

constexpr int BAND_COUNT = 32;   // the spectrum the draw shader can show

struct AudioState {
    float level = 0.0f;          // overall loudness, automatic gain, roughly 0..1.5
    float bass = 0.0f;           // 30-140 Hz
    float low = 0.0f;            // 140-400 Hz
    float mid = 0.0f;            // 400-1200 Hz
    float treble = 0.0f;         // 1200-4000 Hz
    float air = 0.0f;            // 4000-12000 Hz
    float beat = 0.0f;           // 1 on a beat, decaying to 0
    float beat_age = 10.0f;      // seconds since the last beat
    float bands[BAND_COUNT] = {};  // log-spaced spectrum for the bars/ring, 0..1.5
};

class AudioAnalyzer {
public:
    static constexpr int WINDOW = 1024;      // FFT size, ~23 ms at 44.1 kHz
    static constexpr int RING = 8192;

    // Called from Start() with the stream format Kodi reports (visualisations are 44.1 kHz
    // stereo; anything else is handled by mixing and using the real rate).
    void configure(int sample_rate, int channels);
    void set_sensitivity(float percent);      // 50..200, default 100
    void reset();

    // Audio thread. interleaved is Kodi's float buffer; float_count is the number of floats
    // (frames * channels), not frames. Keeps only the newest samples.
    void push(const float* interleaved, size_t float_count);

    // Render thread, once per frame. dt clamps to a sane range. Fills state().
    void update(double dt);

    const AudioState& state() const { return state_; }

private:
    void analyse(const float* samples, double dt);
    void decay(double dt);

    mutable std::mutex mu_;
    std::vector<float> ring_ = std::vector<float>(RING, 0.0f);
    size_t write_ = 0;
    bool fresh_ = false;
    int sample_rate_ = 44100;
    int channels_ = 2;
    float sensitivity_ = 1.0f;

    // Per-band automatic gain: the slow peak each band is measured against.
    float peak_[5] = {};
    float smooth_[5] = {};
    float peak_level_ = 0.0f;
    float peak_spec_[BAND_COUNT] = {};
    float smooth_spec_[BAND_COUNT] = {};

    // Beat detection. The history is about a second of bass at display rate.
    static constexpr int HIST = 64;
    std::array<float, HIST> hist_ = {};
    int hist_pos_ = 0;
    int hist_n_ = 0;
    float hist_sum_ = 0.0f;
    float hist_sq_ = 0.0f;
    double clock_ = 0.0;
    double last_beat_ = -100.0;
    double stale_ = 0.0;      // seconds since audio last arrived

    // Scratch buffers, so a frame does not allocate.
    std::vector<float> hann_;
    std::vector<float> fft_re_;
    std::vector<float> fft_im_;

    AudioState state_;
};

}  // namespace audio
}  // namespace physarum
}  // namespace sandclock

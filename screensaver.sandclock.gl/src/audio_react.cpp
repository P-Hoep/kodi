#include "audio_react.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>

namespace sandclock {
namespace physarum {
namespace audio {

namespace {

constexpr float PI = 3.14159265358979323846f;

// In-place iterative radix-2 FFT. The input length is a power of two (WINDOW).
void fft(std::vector<float>& re, std::vector<float>& im) {
    const int n = (int)re.size();
    for (int i = 1, j = 0; i < n; ++i) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) {
            std::swap(re[i], re[j]);
            std::swap(im[i], im[j]);
        }
    }
    for (int len = 2; len <= n; len <<= 1) {
        const float ang = -2.0f * PI / (float)len;
        const float wlen_r = std::cos(ang), wlen_i = std::sin(ang);
        for (int i = 0; i < n; i += len) {
            float wr = 1.0f, wi = 0.0f;
            for (int j = 0; j < len / 2; ++j) {
                const int a = i + j, b = i + j + len / 2;
                const float ur = re[a], ui = im[a];
                const float vr = re[b] * wr - im[b] * wi;
                const float vi = re[b] * wi + im[b] * wr;
                re[a] = ur + vr;
                im[a] = ui + vi;
                re[b] = ur - vr;
                im[b] = ui - vi;
                const float nwr = wr * wlen_r - wi * wlen_i;
                wi = wr * wlen_i + wi * wlen_r;
                wr = nwr;
            }
        }
    }
}

float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

// One-pole envelope: fast attack, slower release, both in seconds.
float follow(float current, float target, double dt, float attack, float release) {
    const float k = target > current ? (float)(1.0 - std::exp(-dt / attack))
                                     : (float)(1.0 - std::exp(-dt / release));
    return current + (target - current) * k;
}

}  // namespace

void AudioAnalyzer::configure(int sample_rate, int channels) {
    std::lock_guard<std::mutex> lock(mu_);
    sample_rate_ = sample_rate > 8000 ? sample_rate : 44100;
    channels_ = channels > 0 ? channels : 2;
    ring_.assign(RING, 0.0f);
    write_ = 0;
    fresh_ = false;

    hann_.resize(WINDOW);
    for (int i = 0; i < WINDOW; ++i)
        hann_[i] = 0.5f - 0.5f * std::cos(2.0f * PI * i / (WINDOW - 1));
    fft_re_.assign(WINDOW, 0.0f);
    fft_im_.assign(WINDOW, 0.0f);

    std::fill(std::begin(peak_), std::end(peak_), 0.0f);
    std::fill(std::begin(smooth_), std::end(smooth_), 0.0f);
    std::fill(std::begin(peak_spec_), std::end(peak_spec_), 0.0f);
    std::fill(std::begin(smooth_spec_), std::end(smooth_spec_), 0.0f);
    peak_level_ = 0.0f;
    hist_.fill(0.0f);
    hist_pos_ = hist_n_ = 0;
    hist_sum_ = hist_sq_ = 0.0f;
    clock_ = 0.0;
    last_beat_ = -100.0;
    stale_ = 0.0;
    state_ = AudioState();
}

void AudioAnalyzer::set_sensitivity(float percent) {
    sensitivity_ = clampf(percent / 100.0f, 0.5f, 2.0f);
}

void AudioAnalyzer::reset() {
    std::lock_guard<std::mutex> lock(mu_);
    ring_.assign(RING, 0.0f);
    write_ = 0;
    fresh_ = false;
    std::fill(std::begin(peak_), std::end(peak_), 0.0f);
    std::fill(std::begin(smooth_), std::end(smooth_), 0.0f);
    std::fill(std::begin(peak_spec_), std::end(peak_spec_), 0.0f);
    std::fill(std::begin(smooth_spec_), std::end(smooth_spec_), 0.0f);
    peak_level_ = 0.0f;
    hist_.fill(0.0f);
    hist_pos_ = hist_n_ = 0;
    hist_sum_ = hist_sq_ = 0.0f;
    clock_ = 0.0;
    last_beat_ = -100.0;
    stale_ = 0.0;
    state_ = AudioState();
}

void AudioAnalyzer::push(const float* interleaved, size_t float_count) {
    if (!interleaved || float_count == 0) return;
    std::lock_guard<std::mutex> lock(mu_);
    const int ch = channels_ > 0 ? channels_ : 1;
    const size_t frames = float_count / (size_t)ch;
    for (size_t i = 0; i < frames; ++i) {
        float v = 0.0f;
        for (int c = 0; c < ch; ++c) v += interleaved[i * (size_t)ch + (size_t)c];
        ring_[write_] = v / (float)ch;
        write_ = (write_ + 1) % (size_t)RING;
    }
    fresh_ = true;
}

void AudioAnalyzer::update(double dt) {
    dt = std::min(0.1, std::max(0.001, dt));
    clock_ += dt;

    float window[WINDOW];
    bool fresh = false;
    {
        std::lock_guard<std::mutex> lock(mu_);
        fresh = fresh_;
        fresh_ = false;
        const size_t start = (write_ + (size_t)RING - (size_t)WINDOW) % (size_t)RING;
        for (int i = 0; i < WINDOW; ++i) window[i] = ring_[(start + (size_t)i) % (size_t)RING];
    }

    if (fresh) {
        stale_ = 0.0;
        analyse(window, dt);
    } else {
        // Kodi can stop feeding audio for a moment (a seek, a pause, the start of a track).
        // Let the picture calm down instead of holding the last spectrum forever, but do not
        // punish a renderer that runs faster than the audio callback.
        stale_ += dt;
        if (stale_ > 0.25) decay(dt);
    }

    // The beat impulse and its age. The detector itself runs in analyse().
    if (clock_ - last_beat_ > 0.0)
        state_.beat_age = (float)std::min(10.0, clock_ - last_beat_);
    state_.beat *= (float)std::exp(-dt * 6.0);
    state_.level = clampf(state_.level, 0.0f, 2.0f);
}

void AudioAnalyzer::decay(double dt) {
    const float fall = (float)std::exp(-dt * 4.0);
    state_.level *= fall;
    state_.bass *= fall;
    state_.low *= fall;
    state_.mid *= fall;
    state_.treble *= fall;
    state_.air *= fall;
    for (float& v : state_.bands) v *= fall;
    for (float& v : smooth_) v *= fall;
    for (float& v : smooth_spec_) v *= fall;
    for (float& v : hist_) v *= fall;
    hist_sum_ *= fall;
    hist_sq_ *= fall * fall;
}

void AudioAnalyzer::analyse(const float* s, double dt) {
    const int n = WINDOW;
    const float scale = 4.0f / (float)n;    // Hann window: a sine of amplitude A reads A

    double sum_sq = 0.0;
    for (int i = 0; i < n; ++i) {
        sum_sq += (double)s[i] * s[i];
        fft_re_[i] = s[i] * hann_[i];
        fft_im_[i] = 0.0f;
    }
    const float rms = (float)std::sqrt(sum_sq / n);
    fft(fft_re_, fft_im_);

    const int half = n / 2;
    const float bin_hz = (float)sample_rate_ / (float)n;
    auto band = [&](float f0, float f1) {
        int b0 = std::max(1, (int)std::floor(f0 / bin_hz));
        int b1 = std::min(half - 1, (int)std::ceil(f1 / bin_hz));
        if (b1 < b0) b1 = b0;
        double sum = 0.0;
        for (int b = b0; b <= b1; ++b) {
            const float mag = std::sqrt(fft_re_[b] * fft_re_[b] + fft_im_[b] * fft_im_[b]) * scale;
            sum += (double)mag * mag;
        }
        return (float)std::sqrt(sum / (b1 - b0 + 1));
    };

    // The five broad bands. The ranges are fixed, so the same music feels the same whatever
    // the spectrum display is doing.
    const float raw[5] = {band(30, 140), band(140, 400), band(400, 1200),
                          band(1200, 4000), band(4000, 12000)};

    // Automatic gain, with a slow peak that falls on a 2.5 second half-life. The power curve
    // keeps quiet passages moving without making loud ones look flat.
    const float peak_fall = (float)std::pow(0.5, dt / 2.5);
    for (int i = 0; i < 5; ++i) {
        peak_[i] = std::max(raw[i], peak_[i] * peak_fall);
        peak_[i] = std::max(peak_[i], 0.012f);
        float target = std::pow(std::min(1.6f, raw[i] / peak_[i]), 0.65f) * sensitivity_;
        target = clampf(target, 0.0f, 2.0f);
        smooth_[i] = follow(smooth_[i], target, dt, 0.02f, 0.16f);
    }
    peak_level_ = std::max(rms, peak_level_ * peak_fall);
    peak_level_ = std::max(peak_level_, 0.008f);
    {
        float target = std::pow(std::min(1.6f, rms / peak_level_), 0.7f) * sensitivity_;
        state_.level = follow(state_.level, clampf(target, 0.0f, 2.0f), dt, 0.02f, 0.2f);
    }

    state_.bass = smooth_[0];
    state_.low = smooth_[1];
    state_.mid = smooth_[2];
    state_.treble = smooth_[3];
    state_.air = smooth_[4];

    // The display spectrum: 32 log-spaced bands from 40 Hz to the top of what is audible.
    const float high = std::min(16000.0f, (float)sample_rate_ * 0.45f);
    const float log_span = std::log(high / 40.0f) / BAND_COUNT;
    for (int i = 0; i < BAND_COUNT; ++i) {
        const float f0 = 40.0f * std::exp(log_span * i);
        const float f1 = 40.0f * std::exp(log_span * (i + 1));
        const float raw_band = band(f0, f1);
        peak_spec_[i] = std::max(raw_band, peak_spec_[i] * peak_fall);
        peak_spec_[i] = std::max(peak_spec_[i], 0.008f);
        float target = std::pow(std::min(1.6f, raw_band / peak_spec_[i]), 0.62f) * sensitivity_;
        target = clampf(target, 0.0f, 2.0f);
        smooth_spec_[i] = follow(smooth_spec_[i], target, dt, 0.015f, 0.2f);
        state_.bands[i] = smooth_spec_[i];
    }

    // Beat detection: bass well above its own recent average, with a 160 ms refractory period.
    const float bass = state_.bass;
    float old = 0.0f;
    if (hist_n_ == HIST) {
        old = hist_[hist_pos_];
        hist_sum_ -= old;
        hist_sq_ -= old * old;
    } else {
        ++hist_n_;
    }
    hist_[hist_pos_] = bass;
    hist_sum_ += bass;
    hist_sq_ += bass * bass;
    hist_pos_ = (hist_pos_ + 1) % HIST;

    const float mean = hist_sum_ / std::max(1, hist_n_);
    const float var = std::max(0.0f, hist_sq_ / std::max(1, hist_n_) - mean * mean);
    const float threshold = mean + std::sqrt(var) * 1.0f + 0.04f;
    if (bass > threshold && bass > 0.18f && clock_ - last_beat_ > 0.16) {
        last_beat_ = clock_;
        state_.beat = 1.0f;
        state_.beat_age = 0.0f;
    }
}

}  // namespace audio
}  // namespace physarum
}  // namespace sandclock

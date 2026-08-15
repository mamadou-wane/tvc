#include "loop_stats.hpp"

#include <hdr/hdr_histogram.h>

#include <cstdio>
#include <cinttypes>

namespace {
// 1 ns .. 10 s, three significant figures. Three figures is the standard
// trade: ~0.1% value resolution for a few hundred KB of buckets, all of it
// allocated up front.
constexpr std::int64_t kLowest  = 1;
constexpr std::int64_t kHighest = 10LL * 1000 * 1000 * 1000;
constexpr int          kSigFigs = 3;
}  // namespace

namespace stats {

LoopStats::LoopStats(std::int64_t period_ns) : period_ns_(period_ns) {
    hdr_init(kLowest, kHighest, kSigFigs, &jitter_raw_);
    hdr_init(kLowest, kHighest, kSigFigs, &jitter_co_);
    hdr_init(kLowest, kHighest, kSigFigs, &exec_);
}

LoopStats::~LoopStats() {
    if (jitter_raw_) hdr_close(jitter_raw_);
    if (jitter_co_)  hdr_close(jitter_co_);
    if (exec_)       hdr_close(exec_);
}

void LoopStats::record(std::int64_t jitter_ns, std::int64_t exec_ns) noexcept {
    if (!seen_ || jitter_ns < min_signed_) { min_signed_ = jitter_ns; seen_ = true; }
    if (jitter_ns < 0) early_++;

    // HdrHistogram cannot hold negatives. Waking early is not a deadline
    // problem, so clamp to the floor rather than discarding the sample.
    const std::int64_t j = jitter_ns < 1 ? 1 : jitter_ns;

    hdr_record_value(jitter_raw_, j);
    hdr_record_corrected_value(jitter_co_, j, period_ns_);
    hdr_record_value(exec_, exec_ns < 1 ? 1 : exec_ns);
}

void LoopStats::reset() noexcept {
    hdr_reset(jitter_raw_);
    hdr_reset(jitter_co_);
    hdr_reset(exec_);
    missed_ = 0;
    early_  = 0;
    seen_   = false;
    min_signed_ = 0;
}

Summary LoopStats::summary() const {
    Summary s;
    s.count        = jitter_raw_->total_count;
    s.missed       = missed_;
    s.early        = early_;
    s.min_ns       = min_signed_;
    s.mean_ns      = hdr_mean(jitter_raw_);
    s.p50_ns       = hdr_value_at_percentile(jitter_raw_, 50.0);
    s.p99_ns       = hdr_value_at_percentile(jitter_raw_, 99.0);
    s.p999_ns      = hdr_value_at_percentile(jitter_raw_, 99.9);
    s.p9999_ns     = hdr_value_at_percentile(jitter_raw_, 99.99);
    s.max_ns       = hdr_max(jitter_raw_);
    s.co_p999_ns   = hdr_value_at_percentile(jitter_co_, 99.9);
    s.exec_p50_ns  = hdr_value_at_percentile(exec_, 50.0);
    s.exec_p999_ns = hdr_value_at_percentile(exec_, 99.9);
    s.exec_max_ns  = hdr_max(exec_);
    return s;
}

bool LoopStats::write_csv(const std::string& dir, const std::string& label) const {
    struct Series { const char* name; hdr_histogram* h; };
    const Series series[] = {
        {"jitter_raw",       jitter_raw_},
        {"jitter_corrected", jitter_co_},
        {"exec",             exec_},
    };
    for (const auto& s : series) {
        const std::string path = dir + "/" + label + "." + s.name + ".csv";
        FILE* f = std::fopen(path.c_str(), "w");
        if (!f) return false;
        // Emitted in microseconds: value_scale divides the stored ns.
        hdr_percentiles_print(s.h, f, 5, 1000.0, CSV);
        std::fclose(f);
    }
    return true;
}

bool LoopStats::write_json(const std::string& path, const std::string& label,
                           const std::string& config) const {
    FILE* f = std::fopen(path.c_str(), "w");
    if (!f) return false;
    const Summary s = summary();
    auto us = [](std::int64_t ns) { return static_cast<double>(ns) / 1000.0; };
    std::fprintf(f,
        "{\n"
        "  \"label\": \"%s\",\n"
        "  \"config\": \"%s\",\n"
        "  \"period_us\": %.3f,\n"
        "  \"cycles\": %" PRId64 ",\n"
        "  \"missed_deadlines\": %" PRId64 ",\n"
        "  \"early_wakeups\": %" PRId64 ",\n"
        "  \"jitter_us\": {\n"
        "    \"min\": %.3f, \"mean\": %.3f, \"p50\": %.3f,\n"
        "    \"p99\": %.3f, \"p99.9\": %.3f, \"p99.99\": %.3f, \"max\": %.3f,\n"
        "    \"p99.9_corrected\": %.3f\n"
        "  },\n"
        "  \"exec_us\": { \"p50\": %.3f, \"p99.9\": %.3f, \"max\": %.3f }\n"
        "}\n",
        label.c_str(), config.c_str(), us(period_ns_),
        s.count, s.missed, s.early,
        us(s.min_ns), us(static_cast<std::int64_t>(s.mean_ns)), us(s.p50_ns),
        us(s.p99_ns), us(s.p999_ns), us(s.p9999_ns), us(s.max_ns),
        us(s.co_p999_ns),
        us(s.exec_p50_ns), us(s.exec_p999_ns), us(s.exec_max_ns));
    std::fclose(f);
    return true;
}

}  // namespace stats

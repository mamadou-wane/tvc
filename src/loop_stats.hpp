// loop_stats.hpp — the measurement itself.
//
// Two quantities, kept strictly apart:
//
//   wakeup jitter   how late the loop resumed relative to its intended
//                   deadline. This is the kernel's fault, not yours.
//   execution time  how long the loop body took once it was running. This
//                   is your fault.
//
// Conflating them makes both uninterpretable, which is the most common way a
// latency measurement lies.
//
// Jitter is measured against absolute deadlines derived from a fixed origin,
// so every cycle produces exactly one sample and nothing is ever omitted:
// this design is coordinated-omission-free by construction. A second series,
// jitter_naive, records what a self-referencing measurement (previous wakeup
// + period) would have seen; the gap between the two is the CO demonstration
// for the writeup, and the naive series is never the published number.
//
// All storage is allocated in the constructor. record() touches no allocator.

#pragma once
#include <cstdint>
#include <string>

struct hdr_histogram;

namespace stats {

struct Summary {
    std::int64_t count          = 0;
    std::int64_t missed         = 0;   // cycles whose deadline had already passed
    std::int64_t early          = 0;   // woke before the deadline
    std::int64_t min_ns         = 0;   // signed: negative means early
    double       mean_ns        = 0;
    std::int64_t p50_ns = 0, p99_ns = 0, p999_ns = 0, p9999_ns = 0, max_ns = 0;
    std::int64_t naive_p999_ns  = 0;   // self-referenced measurement, demo only
    std::int64_t dropped        = 0;   // samples outside histogram range
    std::int64_t exec_p50_ns = 0, exec_p999_ns = 0, exec_max_ns = 0;
};

class LoopStats {
public:
    // period_ns is the expected sampling interval: deadlines derive from it,
    // and note_missed() uses it as the missed-cycle threshold.
    explicit LoopStats(std::int64_t period_ns);
    ~LoopStats();
    LoopStats(const LoopStats&)            = delete;
    LoopStats& operator=(const LoopStats&) = delete;

    // Hot path. Allocation-free, no syscalls, no locks.
    void record(std::int64_t jitter_ns, std::int64_t naive_ns,
                std::int64_t exec_ns) noexcept;

    // Counted in addition to the cycle's histogram sample: the cycle finished
    // after its successor's deadline, so the schedule slipped a full period.
    void note_missed() noexcept { missed_++; }

    void    reset() noexcept;
    Summary summary() const;

    // Full percentile sweeps, one CSV per series, for plotting.
    bool write_csv(const std::string& dir, const std::string& label) const;
    // Machine-readable run record for the sweep table. cycles_requested is
    // the configured --cycles value: comparing it against the recorded count
    // is how a stale interrupted/short run is kept out of the table.
    bool write_json(const std::string& path, const std::string& label,
                    const std::string& config, const std::string& applied_json,
                    const std::string& env_json,
                    std::int64_t cycles_requested) const;

private:
    hdr_histogram* jitter_raw_   = nullptr;
    hdr_histogram* jitter_naive_ = nullptr;
    hdr_histogram* exec_         = nullptr;
    std::int64_t   period_ns_    = 0;
    std::int64_t   missed_       = 0;
    std::int64_t   early_        = 0;
    std::int64_t   min_signed_   = 0;
    std::int64_t   dropped_      = 0;
    bool           seen_         = false;
};

}  // namespace stats

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
// Jitter is recorded twice, raw and corrected. The corrected series applies
// coordinated omission compensation: when one cycle runs long, the cycles it
// displaced never got sampled, and their absence flatters the tail. Backfilling
// them is what makes a p99.9 mean anything. Publishing both, and being able to
// explain the gap, is the point.
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
    std::int64_t co_p999_ns     = 0;   // same percentile, omission-corrected
    std::int64_t exec_p50_ns = 0, exec_p999_ns = 0, exec_max_ns = 0;
};

class LoopStats {
public:
    // period_ns is the expected sampling interval, and is what the coordinated
    // omission correction backfills against.
    explicit LoopStats(std::int64_t period_ns);
    ~LoopStats();
    LoopStats(const LoopStats&)            = delete;
    LoopStats& operator=(const LoopStats&) = delete;

    // Hot path. Allocation-free, no syscalls, no locks.
    void record(std::int64_t jitter_ns, std::int64_t exec_ns) noexcept;

    // Counted but not recorded: the deadline was already in the past when the
    // loop got there, so a cycle was skipped outright.
    void note_missed() noexcept { missed_++; }

    void    reset() noexcept;
    Summary summary() const;

    // Full percentile sweeps, one CSV per series, for plotting.
    bool write_csv(const std::string& dir, const std::string& label) const;
    // Machine-readable run record for the sweep table.
    bool write_json(const std::string& path, const std::string& label,
                    const std::string& config) const;

private:
    hdr_histogram* jitter_raw_ = nullptr;
    hdr_histogram* jitter_co_  = nullptr;
    hdr_histogram* exec_       = nullptr;
    std::int64_t   period_ns_  = 0;
    std::int64_t   missed_     = 0;
    std::int64_t   early_      = 0;
    std::int64_t   min_signed_ = 0;
    bool           seen_       = false;
};

}  // namespace stats

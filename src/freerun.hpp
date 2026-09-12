#pragma once

#include "alloc_guard.hpp"
#include <atomic>
#include <cstdint>
#include <string>

namespace freerun {
inline constexpr std::int64_t kPeriodNs = 2000000;

struct Config {
    std::string label, outdir;
    std::uint16_t sensor_port = 24000;
    bool auto_arm = false, mlock = false;
    int cpu = -1, fifo_prio = 0;
    guard::Mode alloc_guard = guard::Mode::Off;
    std::int64_t cycles = 300000, warmup = 5000, phase_us = 400;
    unsigned skew_max = 4, terminal_copies = 12;
};

// Setup owns the single bounded origin receive; the scheduled body cannot call it.
int run(const Config&, std::atomic<bool>& stop);
} // namespace freerun

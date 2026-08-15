// main.cpp — the control-cycle timing harness.
//
// Every mitigation is a flag, off by default. That is deliberate: the default
// build is the naive loop, and the campaign consists of turning them on one at
// a time and recording what each one bought. A harness that starts fully
// hardened cannot tell you that story.
//
//   ./tvc_harness --label=L0-baseline
//   ./tvc_harness --label=L1-abs-deadline --abs-deadline
//   ./tvc_harness --label=L5-clean --abs-deadline --mlock --fifo=80 --cpu=3
//                 --no-naive-log --alloc-guard=abort
//
// Timebase is CLOCK_MONOTONIC throughout. Never CLOCK_REALTIME (NTP steps it)
// and never std::chrono::high_resolution_clock (implementation-defined, and on
// libstdc++ it is an alias for system_clock, which is the realtime clock).

#include "alloc_guard.hpp"
#include "loop_stats.hpp"
#include "rt_setup.hpp"

#include <atomic>
#include <cinttypes>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>
#include <thread>
#include <vector>

namespace {

constexpr std::int64_t kNsPerSec = 1000000000LL;

inline std::int64_t now_ns() noexcept {
    timespec ts;
    ::clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * kNsPerSec + ts.tv_nsec;
}

inline timespec to_timespec(std::int64_t ns) noexcept {
    timespec ts;
    ts.tv_sec  = ns / kNsPerSec;
    ts.tv_nsec = ns % kNsPerSec;
    return ts;
}

std::atomic<bool> g_stop{false};
void on_signal(int) { g_stop.store(true, std::memory_order_relaxed); }

// ---------------------------------------------------------------------------
// A stand-in for the control law. Fixed trip count, no branches on data, no
// allocation: whatever jitter shows up is the platform's, not the workload's.
struct Plant {
    double theta = 0.02, omega = 0.0;
    double integral = 0.0, prev_err = 0.0;
    double last_cmd = 0.0;

    void step(double dt) noexcept {
        constexpr double kJ = 4200.0, kF = 8.4e5, kL = 12.0;
        constexpr double kP = 9.0e5, kI = 2.2e5, kD = 1.1e6;

        const double err = 0.0 - theta;
        integral += err * dt;
        const double deriv = (err - prev_err) / dt;
        prev_err = err;

        double delta = (kP * err + kI * integral + kD * deriv) / (kF * kL);
        if (delta >  0.12) delta =  0.12;   // gimbal stop
        if (delta < -0.12) delta = -0.12;
        last_cmd = delta;

        const double torque = kF * kL * std::sin(delta);
        const double alpha  = torque / kJ;
        omega += alpha * dt;
        theta += omega * dt;
    }
};

// ---------------------------------------------------------------------------
struct Config {
    std::string label      = "run";
    std::string outdir     = ".";
    double      rate_hz    = 500.0;
    std::int64_t cycles    = 300000;      // 10 minutes at 500 Hz
    std::int64_t warmup    = 5000;
    bool        abs_deadline = false;
    bool        mlock        = false;
    int         fifo_prio    = 0;         // 0 = leave policy alone
    int         cpu          = -1;
    bool        naive_log    = true;      // the allocating telemetry path
    guard::Mode alloc_guard  = guard::Mode::Off;
};

void usage() {
    std::puts(
"tvc_harness — control-cycle timing measurement\n"
"\n"
"  --label=NAME        run label, used for output filenames  (default: run)\n"
"  --out=DIR           output directory                      (default: .)\n"
"  --rate=HZ           control rate                          (default: 500)\n"
"  --cycles=N          cycles to record                      (default: 300000)\n"
"  --warmup=N          cycles discarded before recording     (default: 5000)\n"
"\n"
"mitigations, all off by default:\n"
"  --abs-deadline      clock_nanosleep TIMER_ABSTIME instead of sleep_for\n"
"  --mlock             mlockall + pre-fault stack and heap\n"
"  --fifo=PRIO         SCHED_FIFO at PRIO (80 recommended, not 99)\n"
"  --cpu=N             pin to CPU N\n"
"  --no-naive-log      remove the allocating telemetry path from the cycle\n"
"  --alloc-guard=MODE  off | count | abort                   (default: off)\n");
}

bool starts_with(const char* s, const char* p, const char** rest) {
    const std::size_t n = std::strlen(p);
    if (std::strncmp(s, p, n) == 0) { *rest = s + n; return true; }
    return false;
}

bool parse(int argc, char** argv, Config& c) {
    for (int i = 1; i < argc; ++i) {
        const char* a = argv[i];
        const char* v = nullptr;
        if (!std::strcmp(a, "--help") || !std::strcmp(a, "-h")) { usage(); return false; }
        else if (starts_with(a, "--label=",  &v)) c.label   = v;
        else if (starts_with(a, "--out=",    &v)) c.outdir  = v;
        else if (starts_with(a, "--rate=",   &v)) c.rate_hz = std::atof(v);
        else if (starts_with(a, "--cycles=", &v)) c.cycles  = std::atoll(v);
        else if (starts_with(a, "--warmup=", &v)) c.warmup  = std::atoll(v);
        else if (!std::strcmp(a, "--abs-deadline")) c.abs_deadline = true;
        else if (!std::strcmp(a, "--mlock"))       c.mlock        = true;
        else if (!std::strcmp(a, "--no-naive-log")) c.naive_log   = false;
        else if (starts_with(a, "--fifo=", &v)) c.fifo_prio = std::atoi(v);
        else if (starts_with(a, "--cpu=",  &v)) c.cpu       = std::atoi(v);
        else if (starts_with(a, "--alloc-guard=", &v)) {
            if      (!std::strcmp(v, "off"))   c.alloc_guard = guard::Mode::Off;
            else if (!std::strcmp(v, "count")) c.alloc_guard = guard::Mode::Count;
            else if (!std::strcmp(v, "abort")) c.alloc_guard = guard::Mode::Abort;
            else { std::fprintf(stderr, "bad --alloc-guard=%s\n", v); return false; }
        }
        else { std::fprintf(stderr, "unknown argument: %s\n\n", a); usage(); return false; }
    }
    if (c.rate_hz <= 0 || c.cycles <= 0) { std::fputs("rate and cycles must be positive\n", stderr); return false; }
    return true;
}

std::string config_string(const Config& c) {
    std::string s;
    s += c.abs_deadline ? "abs-deadline " : "sleep_for ";
    if (c.mlock)         s += "mlock ";
    if (c.fifo_prio > 0) s += "fifo:" + std::to_string(c.fifo_prio) + " ";
    if (c.cpu >= 0)      s += "cpu:" + std::to_string(c.cpu) + " ";
    s += c.naive_log ? "naive-log " : "no-alloc ";
    if (!s.empty() && s.back() == ' ') s.pop_back();
    return s;
}

}  // namespace

int main(int argc, char** argv) {
    Config cfg;
    if (!parse(argc, argv, cfg)) return 1;

    std::signal(SIGINT,  on_signal);
    std::signal(SIGTERM, on_signal);

    const std::int64_t period_ns =
        static_cast<std::int64_t>(kNsPerSec / cfg.rate_hz + 0.5);

    std::printf("tvc_harness  label=%s  %.0f Hz (%.3f ms cycle)  %" PRId64 " cycles\n",
                cfg.label.c_str(), cfg.rate_hz, period_ns / 1e6, cfg.cycles);

    // ---- privileges, applied and reported before anything is measured ----
    if (cfg.mlock) {
        const auto r = rt::lock_memory(8u << 20, 64u << 20);
        std::printf("  mlock      %-4s %s\n", r.ok ? "ok" : "FAIL", r.detail.c_str());
    }
    if (cfg.cpu >= 0) {
        const auto r = rt::pin_to_cpu(cfg.cpu);
        std::printf("  affinity   %-4s %s\n", r.ok ? "ok" : "FAIL", r.detail.c_str());
    }
    if (cfg.fifo_prio > 0) {
        const auto r = rt::set_fifo_priority(cfg.fifo_prio);
        std::printf("  scheduler  %-4s %s\n", r.ok ? "ok" : "FAIL", r.detail.c_str());
        if (!r.ok) std::puts("             (needs CAP_SYS_NICE — try sudo, or raise RLIMIT_RTPRIO)");
    }
    std::printf("  running as %s\n", rt::describe_current().c_str());

    // ---- everything that allocates happens here, before the loop ----
    stats::LoopStats stats(period_ns);
    Plant plant;
    std::vector<char> log_scratch(512);

    const double dt = 1.0 / cfg.rate_hz;
    const std::int64_t total = cfg.cycles + cfg.warmup;

    guard::set_mode(cfg.alloc_guard);
    guard::reset_tally();

    // Deadlines derive from a single origin. Adding the period to "now" each
    // time instead lets error accumulate silently, and is the single most
    // common bug in fixed-rate loops.
    const std::int64_t origin = now_ns() + 10 * kNsPerSec / 1000;
    std::int64_t n = 0;

    while (n < total && !g_stop.load(std::memory_order_relaxed)) {
        const std::int64_t deadline = origin + n * period_ns;

        if (cfg.abs_deadline) {
            const timespec ts = to_timespec(deadline);
            int rc;
            do {
                rc = ::clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, nullptr);
            } while (rc == EINTR);
        } else {
            // The naive version: sleep for a duration measured from now. Drift
            // and scheduler granularity both land straight in the tail.
            const std::int64_t remain = deadline - now_ns();
            if (remain > 0) std::this_thread::sleep_for(std::chrono::nanoseconds(remain));
        }

        const std::int64_t woke = now_ns();

        {
            guard::Cycle in_cycle;   // heap activity past this point is a violation

            plant.step(dt);

            if (cfg.naive_log) {
                // What a first-draft telemetry path looks like: format a line
                // into a fresh std::string every cycle. Two allocations and a
                // free, inside the deadline.
                std::string line = "t=" + std::to_string(n) +
                                   " theta=" + std::to_string(plant.theta) +
                                   " cmd="   + std::to_string(plant.last_cmd);
                const std::size_t n_copy =
                    line.size() < log_scratch.size() ? line.size() : log_scratch.size();
                std::memcpy(log_scratch.data(), line.data(), n_copy);
            }
        }

        const std::int64_t done = now_ns();

        if (n >= cfg.warmup) {
            stats.record(woke - deadline, done - woke);
            // A cycle whose successor's deadline is already behind us was not
            // merely late, it was skipped.
            if (done > deadline + period_ns) stats.note_missed();
        }
        ++n;
    }

    guard::set_mode(guard::Mode::Off);

    // ---- report ----
    const auto s = stats.summary();
    auto us = [](std::int64_t ns) { return ns / 1000.0; };

    std::printf("\n  cycles recorded   %" PRId64 "%s\n", s.count,
                g_stop.load() ? "  (interrupted)" : "");
    std::printf("  missed deadlines  %" PRId64 "\n", s.missed);
    std::printf("  early wakeups     %" PRId64 "  (min %.1f us)\n", s.early, us(s.min_ns));
    std::puts("\n  wakeup jitter, microseconds");
    std::printf("    p50 %9.1f   p99 %9.1f   p99.9 %9.1f   p99.99 %9.1f   max %9.1f\n",
                us(s.p50_ns), us(s.p99_ns), us(s.p999_ns), us(s.p9999_ns), us(s.max_ns));
    std::printf("    p99.9 corrected for coordinated omission: %.1f", us(s.co_p999_ns));
    if (s.p999_ns > 0) {
        const double ratio = static_cast<double>(s.co_p999_ns) / s.p999_ns;
        std::printf("   (%.1fx the raw figure)", ratio);
    }
    std::puts("\n\n  loop body execution, microseconds");
    std::printf("    p50 %9.1f   p99.9 %9.1f   max %9.1f\n",
                us(s.exec_p50_ns), us(s.exec_p999_ns), us(s.exec_max_ns));

    if (cfg.alloc_guard == guard::Mode::Count) {
        const auto t = guard::tally();
        std::printf("\n  alloc guard  %" PRIu64 " allocations, %" PRIu64 " frees inside the cycle"
                    " (largest %zu bytes)\n", t.allocs, t.frees, t.largest);
        if (t.allocs == 0 && t.frees == 0) std::puts("               hot path is clean");
    }

    const std::string cfgstr = config_string(cfg);
    if (!stats.write_csv(cfg.outdir, cfg.label))
        std::fprintf(stderr, "\nwarning: could not write CSV into %s\n", cfg.outdir.c_str());
    stats.write_json(cfg.outdir + "/" + cfg.label + ".summary.json", cfg.label, cfgstr);
    std::printf("\n  wrote %s/%s.{jitter_raw,jitter_corrected,exec}.csv and .summary.json\n",
                cfg.outdir.c_str(), cfg.label.c_str());
    return 0;
}

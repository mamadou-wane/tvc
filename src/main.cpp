// main.cpp: the control-cycle timing harness.
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
#include "env_probe.hpp"
#include "loop_stats.hpp"
#include "rt_setup.hpp"
#include "telemetry.hpp"

#include <atomic>
#include <cctype>
#include <cerrno>
#include <cinttypes>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <glob.h>
#include <limits>
#include <memory>
#include <string>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/utsname.h>
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
    std::string outdir     = "results";
    double      rate_hz    = 500.0;
    std::int64_t cycles    = 300000;      // 10 minutes at 500 Hz
    std::int64_t warmup    = 5000;
    bool        abs_deadline = false;
    bool        mlock        = false;
    int         fifo_prio    = 0;         // 0 = leave policy alone
    int         cpu          = -1;
    bool        naive_log    = true;      // the allocating telemetry path
    guard::Mode alloc_guard  = guard::Mode::Off;
    bool        telemetry    = false;
};

void usage() {
    std::puts(
"tvc_harness: control-cycle timing measurement\n"
"\n"
"  --label=NAME        run label, used for output filenames  (default: run)\n"
"  --out=DIR           output directory, created if missing  (default: results)\n"
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
"  --alloc-guard=MODE  off | count | abort                   (default: off)\n"
"  --telemetry         framed telemetry through the SPSC ring to <label>.telemetry.tvcrec\n"
"\n"
"exit codes: 0 ok, 1 usage, 2 mitigation failed, 3 interrupted, 4 write failed\n"
"label charset: [A-Za-z0-9._-]\n");
}

bool starts_with(const char* s, const char* p, const char** rest) {
    const std::size_t n = std::strlen(p);
    if (std::strncmp(s, p, n) == 0) { *rest = s + n; return true; }
    return false;
}

bool to_i64(const char* s, std::int64_t& out) {
    char* end = nullptr;
    errno = 0;
    const long long v = std::strtoll(s, &end, 10);
    if (errno != 0 || end == s || *end != '\0') return false;
    out = v;
    return true;
}
bool to_double(const char* s, double& out) {
    char* end = nullptr;
    errno = 0;
    out = std::strtod(s, &end);
    return errno == 0 && end != s && *end == '\0';
}
bool label_ok(const std::string& s) {
    if (s.empty()) return false;
    for (char c : s)
        if (!std::isalnum(static_cast<unsigned char>(c)) &&
            c != '.' && c != '_' && c != '-') return false;
    return true;
}

enum class ParseResult { Ok, Help, Error };

ParseResult parse(int argc, char** argv, Config& c) {
    for (int i = 1; i < argc; ++i) {
        const char* a = argv[i];
        const char* v = nullptr;
        if (!std::strcmp(a, "--help") || !std::strcmp(a, "-h")) { usage(); return ParseResult::Help; }
        else if (starts_with(a, "--label=",  &v)) c.label   = v;
        else if (starts_with(a, "--out=",    &v)) c.outdir  = v;
        else if (starts_with(a, "--rate=",   &v)) {
            if (!to_double(v, c.rate_hz)) { std::fprintf(stderr, "bad value: %s\n", a); return ParseResult::Error; }
        }
        else if (starts_with(a, "--cycles=", &v)) {
            if (!to_i64(v, c.cycles)) { std::fprintf(stderr, "bad value: %s\n", a); return ParseResult::Error; }
        }
        else if (starts_with(a, "--warmup=", &v)) {
            if (!to_i64(v, c.warmup)) { std::fprintf(stderr, "bad value: %s\n", a); return ParseResult::Error; }
        }
        else if (!std::strcmp(a, "--abs-deadline")) c.abs_deadline = true;
        else if (!std::strcmp(a, "--mlock"))       c.mlock        = true;
        else if (!std::strcmp(a, "--no-naive-log")) c.naive_log   = false;
        else if (starts_with(a, "--fifo=", &v)) {
            std::int64_t fifo = 0;
            if (!to_i64(v, fifo)) { std::fprintf(stderr, "bad value: %s\n", a); return ParseResult::Error; }
            if (fifo < 0 || fifo > 99) {
                std::fputs("--fifo must be 0 or in [1, 99]\n", stderr); return ParseResult::Error;
            }
            c.fifo_prio = static_cast<int>(fifo);
        }
        else if (starts_with(a, "--cpu=",  &v)) {
            std::int64_t cpu = 0;
            if (!to_i64(v, cpu)) { std::fprintf(stderr, "bad value: %s\n", a); return ParseResult::Error; }
            if (cpu < -1 || cpu > std::numeric_limits<int>::max()) {
                std::fputs("--cpu must be in [-1, INT_MAX]\n", stderr); return ParseResult::Error;
            }
            c.cpu = static_cast<int>(cpu);
        }
        else if (starts_with(a, "--alloc-guard=", &v)) {
            if      (!std::strcmp(v, "off"))   c.alloc_guard = guard::Mode::Off;
            else if (!std::strcmp(v, "count")) c.alloc_guard = guard::Mode::Count;
            else if (!std::strcmp(v, "abort")) c.alloc_guard = guard::Mode::Abort;
            else { std::fprintf(stderr, "bad --alloc-guard=%s\n", v); return ParseResult::Error; }
        }
        else if (!std::strcmp(a, "--telemetry")) c.telemetry = true;
        else { std::fprintf(stderr, "unknown argument: %s\n\n", a); usage(); return ParseResult::Error; }
    }
    if (!label_ok(c.label)) { std::fputs("bad --label: must match [A-Za-z0-9._-]\n", stderr); return ParseResult::Error; }
    if (c.rate_hz <= 0) { std::fputs("--rate must be positive\n", stderr); return ParseResult::Error; }
    if (c.cycles <= 0) { std::fputs("--cycles must be positive\n", stderr); return ParseResult::Error; }
    if (c.warmup < 0) { std::fputs("--warmup must be >= 0\n", stderr); return ParseResult::Error; }
    return ParseResult::Ok;
}

// ---------------------------------------------------------------------------
// ac_online_json and read_pkg_temp_c stay best-effort too: sentinel on
// absence, never fails the run (full rule in env_probe.hpp).

// JSON literal: true, false, or "unknown". First power_supply/*/online that
// reads 1 or 0 wins.
std::string ac_online_json() {
    glob_t g{};
    std::string token = "\"unknown\"";
    if (glob("/sys/class/power_supply/*/online", GLOB_NOSORT, nullptr, &g) == 0) {
        for (std::size_t i = 0; i < g.gl_pathc; ++i) {
            const std::string v = env_probe::read_sysfs_line(g.gl_pathv[i]);
            if (v == "1") { token = "true"; break; }
            if (v == "0") { token = "false"; break; }
        }
    }
    globfree(&g);
    return token;
}

// hwmon whose name is "k10temp" -> temp1_input / 1000, integer Celsius.
// -1 when no such hwmon exists.
int read_pkg_temp_c() {
    glob_t g{};
    int result = -1;
    if (glob("/sys/class/hwmon/hwmon*/name", GLOB_NOSORT, nullptr, &g) == 0) {
        for (std::size_t i = 0; i < g.gl_pathc; ++i) {
            const std::string name_path = g.gl_pathv[i];
            if (env_probe::read_sysfs_line(name_path) != "k10temp") continue;
            const std::string dir = name_path.substr(0, name_path.size() - std::strlen("name"));
            std::int64_t milli = 0;
            if (to_i64(env_probe::read_sysfs_line(dir + "temp1_input").c_str(), milli))
                result = static_cast<int>(milli / 1000);
            break;
        }
    }
    globfree(&g);
    return result;
}

std::string config_string(const Config& c) {
    std::string s;
    s += c.abs_deadline ? "abs-deadline " : "sleep_for ";
    if (c.mlock)         s += "mlock ";
    if (c.fifo_prio > 0) s += "fifo:" + std::to_string(c.fifo_prio) + " ";
    if (c.cpu >= 0)      s += "cpu:" + std::to_string(c.cpu) + " ";
    s += c.naive_log ? "naive-log " : "no-alloc ";
    if (c.telemetry)     s += "telemetry ";
    if (!s.empty() && s.back() == ' ') s.pop_back();
    return s;
}

}  // namespace

int main(int argc, char** argv) {
    Config cfg;
    switch (parse(argc, argv, cfg)) {
        case ParseResult::Error: return 1;
        case ParseResult::Help:  return 0;
        case ParseResult::Ok:    break;
    }

    std::signal(SIGINT,  on_signal);
    std::signal(SIGTERM, on_signal);

    // 50 us default slack would otherwise contaminate every non-RT level.
    ::prctl(PR_SET_TIMERSLACK, 1UL, 0UL, 0UL, 0UL);

    const std::int64_t period_ns =
        static_cast<std::int64_t>(kNsPerSec / cfg.rate_hz + 0.5);

    std::printf("tvc_harness  label=%s  %.0f Hz (%.3f ms cycle)  %" PRId64 " cycles\n",
                cfg.label.c_str(), cfg.rate_hz, period_ns / 1e6, cfg.cycles);

    // ---- telemetry sink, before rt setup: the drain thread inherits
    // SCHED_OTHER and the default affinity mask (isolcpus keeps it off
    // the isolated core) ----
    bool ok_telem = !cfg.telemetry;
    std::unique_ptr<telem::SpscRing> ring;
    std::unique_ptr<telem::Drain> drain;
    if (cfg.telemetry) {
        ::mkdir(cfg.outdir.c_str(), 0755);
        const std::string tpath =
            cfg.outdir + "/" + cfg.label + ".telemetry.tvcrec";
        std::FILE* tf = std::fopen(tpath.c_str(), "wb");
        if (tf) {
            unsigned char hdr[32];
            timespec rt{};
            // One-shot wall anchor for the header, off the hot path; the
            // control path itself never reads CLOCK_REALTIME.
            ::clock_gettime(CLOCK_REALTIME, &rt);
            telem::encode_recording_header(
                now_ns(), rt.tv_sec * kNsPerSec + rt.tv_nsec, hdr);
            ok_telem = std::fwrite(hdr, 1, sizeof hdr, tf) == sizeof hdr;
            if (!ok_telem) std::fclose(tf);
        }
        if (tf && ok_telem) {
            ring = std::make_unique<telem::SpscRing>();
            drain = std::make_unique<telem::Drain>(*ring);
            drain->start(tf);
        } else {
            ok_telem = false;
        }
        std::printf("  telemetry  %-4s %s\n", ok_telem ? "ok" : "FAIL",
                    tpath.c_str());
    }

    bool ok_mlock = !cfg.mlock, ok_cpu = cfg.cpu < 0, ok_fifo = cfg.fifo_prio <= 0;

    // ---- privileges, applied and reported before anything is measured ----
    if (cfg.mlock) {
        const auto r = rt::lock_memory(8u << 20, 64u << 20);
        ok_mlock = r.ok;
        std::printf("  mlock      %-4s %s\n", r.ok ? "ok" : "FAIL", r.detail.c_str());
    }
    if (cfg.cpu >= 0) {
        const auto r = rt::pin_to_cpu(cfg.cpu);
        ok_cpu = r.ok;
        std::printf("  affinity   %-4s %s\n", r.ok ? "ok" : "FAIL", r.detail.c_str());
    }
    if (cfg.fifo_prio > 0) {
        const auto r = rt::set_fifo_priority(cfg.fifo_prio);
        ok_fifo = r.ok;
        std::printf("  scheduler  %-4s %s\n", r.ok ? "ok" : "FAIL", r.detail.c_str());
        if (!r.ok) std::puts("             (needs CAP_SYS_NICE: try sudo, or raise RLIMIT_RTPRIO)");
    }
    std::printf("  running as %s\n", rt::describe_current().c_str());

    auto b = [](bool v) { return v ? "true" : "false"; };
    const std::string applied_json =
        std::string("{ \"mlock\": ") + b(!cfg.mlock || ok_mlock) +
        ", \"fifo\": " + b(!(cfg.fifo_prio > 0) || ok_fifo) +
        ", \"cpu\": " + b(cfg.cpu < 0 || ok_cpu) +
        ", \"telemetry\": " + b(!cfg.telemetry || ok_telem) + " }";

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
    std::int64_t prev_woke = 0;

    while (n < total && !g_stop.load(std::memory_order_relaxed)) {
        const std::int64_t deadline = origin + n * period_ns;

        if (cfg.abs_deadline) {
            const timespec ts = to_timespec(deadline);
            int rc;
            do {
                rc = ::clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, nullptr);
            } while (rc == EINTR);
        } else {
            // Genuinely naive: sleep one period from "now", the pattern that
            // drifts by the overshoot every cycle. Measurement still happens
            // against the origin schedule, so the drift is visible.
            std::this_thread::sleep_for(std::chrono::nanoseconds(period_ns));
        }

        const std::int64_t woke = now_ns();

        const std::int64_t naive_jitter =
            prev_woke ? woke - (prev_woke + period_ns) : 0;
        prev_woke = woke;

        {
            guard::Cycle in_cycle;   // heap activity past this point is a violation

            plant.step(dt);

            if (cfg.naive_log) {
                // What a first-draft telemetry path looks like: format a line
                // into a fresh std::string every cycle. Two allocations and
                // two frees, inside the deadline.
                std::string line = "t=" + std::to_string(n) +
                                   " theta=" + std::to_string(plant.theta) +
                                   " cmd="   + std::to_string(plant.last_cmd);
                const std::size_t n_copy =
                    line.size() < log_scratch.size() ? line.size() : log_scratch.size();
                std::memcpy(log_scratch.data(), line.data(), n_copy);
            }
        }

        const std::int64_t done = now_ns();

        if (ring) {
            guard::Cycle telem_cycle;   // the push must stay allocation-free
            telem::Record rec;
            rec.tick        = static_cast<std::uint64_t>(n);
            rec.deadline_ns = deadline;
            rec.woke_ns     = woke;
            rec.done_ns     = done;
            rec.theta       = plant.theta;
            rec.cmd         = plant.last_cmd;
            rec.drops       = ring->drops();
            ring->try_push(rec);
        }

        if (n >= cfg.warmup) {
            guard::Cycle stats_cycle;   // record() must stay allocation-free
            stats.record(woke - deadline, naive_jitter, done - woke);
            // A cycle whose successor's deadline is already behind us was not
            // merely late, it was skipped.
            if (done > deadline + period_ns) stats.note_missed();
        }
        ++n;
    }

    guard::set_mode(guard::Mode::Off);
    if (drain) drain->stop();

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
    std::printf("    p99.9 as a naive self-referenced measurement would report it: %.1f\n",
                us(s.naive_p999_ns));
    if (s.dropped > 0)
        std::printf("    WARNING: %" PRId64 " samples outside histogram range\n", s.dropped);
    std::puts("\n  loop body execution, microseconds");
    std::printf("    p50 %9.1f   p99.9 %9.1f   max %9.1f\n",
                us(s.exec_p50_ns), us(s.exec_p999_ns), us(s.exec_max_ns));

    if (cfg.alloc_guard == guard::Mode::Count) {
        const auto t = guard::tally();
        std::printf("\n  alloc guard  %" PRIu64 " allocations, %" PRIu64 " frees inside the cycle"
                    " (largest %zu bytes)\n", t.allocs, t.frees, t.largest);
        if (t.allocs == 0 && t.frees == 0) std::puts("               hot path is clean");
    }

    // Sampled after the loop, not before: cpu_end reflects where the process
    // actually ran, and timer_slack_ns is read back rather than asserted.
    utsname un{};
    ::uname(&un);
    const long slack = ::prctl(PR_GET_TIMERSLACK, 0UL, 0UL, 0UL, 0UL);
    const int cpu_end = ::sched_getcpu();
    const std::string cpufreq_dir =
        "/sys/devices/system/cpu/cpu" + std::to_string(cpu_end) + "/cpufreq/";
    const std::string env_json =
        std::string("{ \"kernel\": \"") + un.release +
        "\", \"machine\": \"" + un.machine +
        "\", \"cpu_end\": " + std::to_string(cpu_end) +
        ", \"timer_slack_ns\": " + std::to_string(slack) +
        ", \"ac_online\": " + ac_online_json() +
        ", \"governor\": \"" + env_probe::sysfs_or_unknown(cpufreq_dir + "scaling_governor") + "\"" +
        ", \"epp\": \"" + env_probe::sysfs_or_unknown(cpufreq_dir + "energy_performance_preference") + "\"" +
        ", \"pkg_temp_c\": " + std::to_string(read_pkg_temp_c()) +
        ", \"cpuidle\": " + env_probe::cpuidle_json() +
        ", \"timer_migration\": " + std::to_string(env_probe::timer_migration()) + " }";

    const std::string cfgstr = config_string(cfg);

    std::string telemetry_json;
    if (drain)
        telemetry_json =
            "{ \"records\": " + std::to_string(drain->records_written()) +
            ", \"dropped\": " + std::to_string(ring->drops()) +
            ", \"bytes\": " + std::to_string(32 + drain->bytes_written()) + " }";

    // Best effort, single level: a missing parent still fails the writes below.
    ::mkdir(cfg.outdir.c_str(), 0755);
    bool wrote_ok = stats.write_csv(cfg.outdir, cfg.label);
    wrote_ok = stats.write_json(cfg.outdir + "/" + cfg.label + ".summary.json",
                                cfg.label, cfgstr, applied_json, env_json,
                                cfg.cycles, telemetry_json) && wrote_ok;
    if (wrote_ok)
        std::printf("\n  wrote %s/%s.{jitter,jitter_naive,exec}.csv and .summary.json\n",
                    cfg.outdir.c_str(), cfg.label.c_str());
    else
        std::fprintf(stderr, "\nerror: could not write results into %s\n", cfg.outdir.c_str());

    const bool mitigation_failed =
        (cfg.mlock && !ok_mlock) || (cfg.fifo_prio > 0 && !ok_fifo) ||
        (cfg.cpu >= 0 && !ok_cpu) || (cfg.telemetry && !ok_telem);
    const bool telem_failed = drain && drain->write_failed();
    if (!wrote_ok || telem_failed) return 4;
    if (g_stop.load()) return 3;
    if (mitigation_failed) return 2;
    return 0;
}

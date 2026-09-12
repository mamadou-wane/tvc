#include "freerun.hpp"
#include "freerun_admission.hpp"
#include "episode.hpp"
#include "lockstep.hpp"
#include "loop_stats.hpp"
#include "net.hpp"
#include "rt_setup.hpp"
#include "wire.hpp"
#include <cerrno>
#include <cstdio>
#include <limits>
#include <memory>
#include <sstream>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <time.h>

namespace freerun {
namespace {
std::int64_t now_ns(clockid_t clock = CLOCK_MONOTONIC) noexcept {
    timespec ts{};
    ::clock_gettime(clock, &ts);
    return ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

int sleep_to(std::int64_t deadline, const std::atomic<bool>& stop) noexcept {
    const timespec ts{deadline / 1000000000, deadline % 1000000000};
    int error;
    do { error = ::clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, nullptr); }
    while (error == EINTR && !stop.load(std::memory_order_relaxed));
    return error;
}

struct Runtime {
    explicit Runtime(bool auto_arm) : state(episode::initial(auto_arm)) {}
    Admission admission{0};
    episode::State state;
    std::uint64_t tick_base{}, cycles{}, receive_batches{}, pid_calls{}, pushed{}, terminal_cycle{};
    std::uint64_t normal_sent{}, normal_failed{}, term_attempts{}, term_sent{}, term_failed{};
    std::uint64_t receive_errors{}, peer_refused{};
    std::int64_t arrival{}, origin{}, receive_open{}, receive_closed{}, term_first{}, term_last{};
    std::optional<std::uint32_t> sim_seen;
    episode::Reason failure = episode::Reason::NONE;
    int receive_errno{}, sleep_error{};
    std::array<unsigned char, telem::kFrameOverhead + telem::kActuatorV1PayloadBytes> reply{};
};

void run_freerun(const Config& cfg, int fd, const net::Datagram& carry, Runtime& r,
                 telem::SpscRing<telem::ControlRecord>& ring, stats::LoopStats& stats,
                 std::atomic<bool>& stop) {
    const auto total = static_cast<std::uint64_t>(cfg.cycles + cfg.warmup);
    std::int64_t previous_woke = 0;
    for (std::uint64_t n = 0; n < total; ++n) {
        const auto deadline = r.origin + static_cast<std::int64_t>(n) * kPeriodNs;
        r.sleep_error = sleep_to(deadline, stop);
        if (r.sleep_error && r.sleep_error != EINTR) { r.failure = episode::Reason::INTERNAL; break; }
        const auto woke = now_ns();
        guard::Cycle guarded;
        net::Batch batch{};
        const int count = net::recv_batch(fd, batch);
        const int received_errno = count < 0 ? errno : 0;
        const auto rx = now_ns();
        ++r.receive_batches;
        if (count < 0 && received_errno != EAGAIN && received_errno != EWOULDBLOCK) {
            ++r.receive_errors; r.receive_errno = received_errno;
            if (received_errno == ECONNREFUSED) ++r.peer_refused;
        }
        const auto tick = r.tick_base + n;
        r.admission.begin_cycle(tick);
        if (n == 0) r.admission.receive({carry.bytes.data(), carry.size}, carry.truncated());
        for (int i = 0; i < count; ++i)
            r.admission.receive({batch[i].bytes.data(), batch[i].size}, batch[i].truncated());
        const auto& admitted = r.admission.finish_cycle();
        std::optional<Observation> held;
        if (const auto& sample = r.admission.held())
            held = Observation{sample->tick, sample->theta, sample->omega, true};
        if (admitted.terminal) r.sim_seen = admitted.terminal->reason;
        const auto result = episode::step(r.state, {tick, held, admitted.fresh.has_value(),
            admitted.staleness, {}, n + 1 == total, r.sim_seen,
            stop.load(std::memory_order_relaxed) ? std::optional{episode::Reason::SIGNAL} : std::nullopt});
        r.state = result.state;
        ++r.cycles;
        if (admitted.fresh && r.state.mode == episode::Mode::FLYING) ++r.pid_calls;
        const bool terminal = r.state.mode == episode::Mode::TERMINATED;
        const unsigned rung = admitted.staleness >= 21 ? 3 : admitted.fresh ? 0 : admitted.staleness <= 8 ? 1 : 2;
        telem::ControlRecord record{};
        record.tick = tick; record.deadline_ns = deadline; record.woke_ns = woke; record.rx_ns = rx;
        record.sensor_tick = held ? held->tick : UINT64_MAX;
        record.sensor_send_ns = r.admission.held() ? r.admission.held()->send_ns : 0;
        record.theta = held ? held->theta : 0; record.omega = held ? held->omega : 0;
        record.cmd = result.requested_delta; record.i_state = r.state.pid.i_state; record.d_prev = r.state.pid.d_prev;
        record.staleness = admitted.staleness; record.rx_count = admitted.rx_count;
        record.discarded_old = static_cast<std::uint8_t>(admitted.counts.old);
        record.discarded_superseded = static_cast<std::uint8_t>(admitted.counts.superseded);
        record.discarded_other = static_cast<std::uint8_t>(admitted.counts.nonfinite + admitted.counts.skew_excess);
        record.state = static_cast<std::uint8_t>(r.state.mode);
        record.reason = terminal ? static_cast<std::uint8_t>(r.state.terminal->reason) : 0;
        record.flags = (admitted.fresh ? 1 : 0) | (rung == 1 ? 8 : 0) | (rung == 2 ? 16 : 0) |
                       (count == 8 ? 32 : 0) | (admitted.counts.nonfinite ? 128 : 0);
        const std::uint32_t status = record.state | (std::uint32_t(record.reason) << 8) | (rung << 16);
        unsigned char payload[telem::kActuatorV1PayloadBytes];
        const auto before_send = now_ns();
        telem::payload::encode_actuator(payload, sizeof payload, tick, n, record.sensor_send_ns,
                                       before_send, record.cmd, status, record.staleness);
        telem::encode_frame(5, static_cast<std::uint32_t>(n), payload, sizeof payload, r.reply.data());
        const auto sent = net::send_frame(fd, r.reply.data(), r.reply.size());
        const auto tx = now_ns();
        const bool success = sent == static_cast<ssize_t>(r.reply.size());
        record.tx_ns = tx;
        if (success) record.flags |= 2;
        if (terminal) {
            r.terminal_cycle = 1; r.term_attempts = 1; r.term_first = before_send; r.term_last = tx;
            if (success) ++r.term_sent; else ++r.term_failed;
        } else {
            if (success) ++r.normal_sent; else ++r.normal_failed;
        }
        record.done_ns = now_ns();
        record.drops = ring.drops();
        if (ring.try_push(record)) ++r.pushed;
        if (n >= static_cast<std::uint64_t>(cfg.warmup)) {
            stats.record(woke - deadline, previous_woke ? woke - previous_woke - kPeriodNs : 0,
                         record.done_ns - woke);
            if (record.done_ns > deadline + kPeriodNs) stats.note_missed();
        }
        previous_woke = woke;
        if (terminal) break;
    }
    r.receive_closed = now_ns();
}

void resend_terminal(const Config& cfg, int fd, Runtime& r, const std::atomic<bool>& stop) {
    for (unsigned copy = 1; copy < cfg.terminal_copies && !stop.load(); ++copy) {
        const auto deadline = r.origin + static_cast<std::int64_t>(r.cycles - 1 + copy) * kPeriodNs;
        if (sleep_to(deadline, stop) != 0) break;
        guard::Cycle guarded;
        ++r.term_attempts;
        const auto sent = net::send_frame(fd, r.reply.data(), r.reply.size());
        r.term_last = now_ns();
        if (sent == static_cast<ssize_t>(r.reply.size())) ++r.term_sent; else ++r.term_failed;
    }
}

std::string counters(const AdmissionCounts& c) {
    std::ostringstream out;
    out << "{\"received\":" << c.received << ",\"consumed\":" << c.consumed
        << ",\"discarded_old\":" << c.old << ",\"discarded_superseded\":" << c.superseded
        << ",\"discarded_nonfinite\":" << c.nonfinite << ",\"discarded_skew_excess\":" << c.skew_excess
        << ",\"discarded_duplicate\":" << c.duplicate << ",\"discarded_tick_conflict\":" << c.conflict
        << ",\"discarded_invalid\":" << c.invalid << ",\"future_expired\":" << c.future_expired
        << ",\"bad_sync\":" << c.bad_sync << ",\"bad_version\":" << c.bad_version
        << ",\"bad_type\":" << c.bad_type << ",\"bad_length\":" << c.bad_length
        << ",\"bad_crc\":" << c.bad_crc << '}';
    return out.str();
}
} // namespace

int run(const Config& cfg, std::atomic<bool>& stop) {
    sockaddr_in local{}, bound{};
    local.sin_family = AF_INET; local.sin_addr.s_addr = htonl(INADDR_LOOPBACK); local.sin_port = htons(cfg.sensor_port);
    int fd = net::open_udp(local, bound);
    if (fd < 0) return 2;
    ::mkdir(cfg.outdir.c_str(), 0755);
    const auto prefix = cfg.outdir + "/" + cfg.label;
    FILE* file = std::fopen((prefix + ".control.tvcrec").c_str(), "wb");
    if (!file) { net::close_udp(fd); return 4; }
    unsigned char header[32];
    telem::encode_recording_header(now_ns(), now_ns(CLOCK_REALTIME), header, telem::kControlV1SchemaHash);
    if (std::fwrite(header, 1, sizeof header, file) != sizeof header) {
        std::fclose(file); net::close_udp(fd); return 4;
    }
    auto ring = std::make_unique<telem::SpscRing<telem::ControlRecord>>();
    auto runtime = std::make_unique<Runtime>(cfg.auto_arm);
    auto& r = *runtime;
    stats::LoopStats stats(kPeriodNs);
    telem::Drain<telem::ControlRecord> drain(*ring); drain.start(file);
    const bool memory_ok = !cfg.mlock || rt::lock_memory(8u << 20, 64u << 20).ok;
    const bool cpu_ok = cfg.cpu < 0 || rt::pin_to_cpu(cfg.cpu).ok;
    const bool fifo_ok = cfg.fifo_prio <= 0 || rt::set_fifo_priority(cfg.fifo_prio).ok;
    const bool rt_ok = memory_ok && cpu_ok && fifo_ok;
    lockstep::ready("freerun", ntohs(bound.sin_port));
    net::Datagram carry{};
    bool acquired = false;
    if (rt_ok) {
        r.receive_open = now_ns();
        const auto received = net::recv_blocking(fd, carry, net::Wait::Origin);
        r.receive_errno = received < 0 ? errno : 0;
        r.arrival = now_ns();
        telem::DecodedFrame decoded{};
        if (received >= 0 && !carry.truncated() &&
            telem::decode_datagram(carry.bytes.data(), carry.size, {4}, decoded) == telem::DatagramError::None &&
            net::connect_udp(fd, carry.source) == 0) {
            r.tick_base = wire::get_u64_le(carry.bytes.data(), decoded.payload_off);
            r.origin = r.arrival + cfg.phase_us * 1000;
            const auto total = static_cast<std::uint64_t>(cfg.cycles + cfg.warmup);
            if (r.tick_base <= UINT64_MAX - total &&
                total + cfg.terminal_copies <= static_cast<std::uint64_t>((INT64_MAX - r.origin) / kPeriodNs)) {
                r.admission = Admission(r.tick_base, cfg.skew_max, cfg.warmup);
                acquired = true;
                guard::set_mode(cfg.alloc_guard);
                run_freerun(cfg, fd, carry, r, *ring, stats, stop);
                if (r.terminal_cycle) resend_terminal(cfg, fd, r, stop);
            }
        }
    }
    if (!acquired) r.failure = stop.load() ? episode::Reason::SIGNAL : episode::Reason::PEER_LOST;
    if (!rt_ok) r.failure = episode::Reason::INTERNAL;
    if (!r.receive_closed) r.receive_closed = now_ns();
    guard::set_mode(guard::Mode::Off);
    drain.stop(); net::close_udp(fd);
    const auto reason = r.failure != episode::Reason::NONE ? r.failure :
        r.state.terminal ? r.state.terminal->reason : episode::Reason::INTERNAL;
    const auto& tc = r.admission.terminal_counts();
    std::ostringstream extra;
    extra << ",\"timing_qualified\":false,\"measurement_validation\":\"pending\",\"latency_us\":null,\"discard_age_us\":null"
        << ",\"total_cycles\":" << r.cycles << ",\"warmup\":" << cfg.warmup
        << ",\"phase_us\":" << cfg.phase_us << ",\"skew_max_ticks\":" << cfg.skew_max
        << ",\"terminal_copies\":" << cfg.terminal_copies
        << ",\"first_frame_arrival_ns\":" << r.arrival << ",\"origin_ns\":" << r.origin
        << ",\"episode\":{\"state\":3,\"vehicle_reason\":" << static_cast<unsigned>(reason)
        << ",\"reason_tick\":" << (r.state.terminal ? r.state.terminal->tick : r.tick_base)
        << ",\"tick_base\":" << r.tick_base << ",\"sim_reason_seen\":" << (r.sim_seen ? std::to_string(*r.sim_seen) : "null") << '}'
        << ",\"link\":" << counters(r.admission.episode()) << ",\"link_recorded\":" << counters(r.admission.recorded())
        << ",\"future_parked\":" << r.admission.future_parked() << ",\"future_parked_at_warmup\":" << r.admission.parked_at_warmup()
        << ",\"actuator\":{\"generated\":" << r.cycles - r.terminal_cycle << ",\"transmitted\":" << r.normal_sent
        << ",\"tx_fail\":" << r.normal_failed << '}'
        << ",\"terminal\":{\"cycle\":" << r.terminal_cycle << ",\"down_attempts\":" << r.term_attempts
        << ",\"down_transmitted\":" << r.term_sent << ",\"down_tx_fail\":" << r.term_failed
        << ",\"up_received_raw\":" << tc.received_raw << ",\"up_tick_conflict\":" << tc.conflict
        << ",\"up_duplicate\":" << tc.duplicate << ",\"up_skew_excess\":" << tc.skew_excess
        << ",\"up_future_expired\":" << tc.future_expired << ",\"up_illegal_reason\":" << tc.illegal_reason
        << ",\"send_first_ns\":" << r.term_first << ",\"send_last_ns\":" << r.term_last
        << ",\"receive_open_ns\":" << r.receive_open << ",\"receive_closed_ns\":" << r.receive_closed << '}'
        << ",\"events\":{\"episode_transitions\":" << r.cycles << ",\"pid_calls\":" << r.pid_calls
        << ",\"receive_batches\":" << r.receive_batches << ",\"record_attempts\":" << r.cycles
        << ",\"records_pushed\":" << r.pushed << ",\"histogram_records\":" << stats.summary().count << '}'
        << ",\"receive_errno\":" << r.receive_errno << ",\"receive_errors\":" << r.receive_errors
        << ",\"sleep_error\":" << r.sleep_error;
    const auto yes = [](bool value) { return value ? "true" : "false"; };
    const std::string applied = std::string("{\"mlock\":") + yes(memory_ok) + ",\"cpu\":" + yes(cpu_ok) + ",\"fifo\":" + yes(fifo_ok) + ",\"telemetry\":true,\"link\":true}";
    utsname un{}; ::uname(&un);
    const std::string env = std::string("{\"machine\":\"") + un.machine + "\",\"kernel\":\"" + un.release + "\"}";
    const std::string telemetry = "{\"records\":" + std::to_string(drain.records_written()) + ",\"dropped\":" + std::to_string(ring->drops()) + '}';
    const bool wrote = stats.write_json(prefix + ".summary.json", cfg.label, "mode:freerun record:control",
        applied, env, cfg.cycles, telemetry, "freerun", true, extra.str());
    if (!wrote || drain.write_failed() || ring->drops()) return 4;
    if (stop.load()) return 3;
    if (!rt_ok) return 2;
    if (r.admission.integrity_failed() || !r.admission.identities_hold()) return 6;
    if (!acquired || r.failure != episode::Reason::NONE || !r.term_sent) return 5;
    return 0;
}
} // namespace freerun

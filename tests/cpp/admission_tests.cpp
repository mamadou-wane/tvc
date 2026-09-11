#include "../../src/freerun_admission.hpp"
#include "../../src/alloc_guard.hpp"
#include "../../src/episode.hpp"
#include "../../src/wire.hpp"
#include <cstdio>
#include <cstdlib>
#include <limits>

#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL %d: %s\n", __LINE__, #x); std::exit(1); } } while (0)

using Packet = std::array<unsigned char, telem::kFrameOverhead + telem::kSensorV1PayloadBytes>;
using K = freerun::SensorClass;

static unsigned episode_calls = 0, pid_calls = 0;
extern "C" episode::Transition real_episode(const episode::State&, const episode::Inputs&) asm("__real__ZN7episode4stepERKNS_5StateERKNS_6InputsE");
extern "C" episode::Transition wrapped_episode(const episode::State&, const episode::Inputs&) asm("__wrap__ZN7episode4stepERKNS_5StateERKNS_6InputsE");
extern "C" episode::Transition wrapped_episode(const episode::State& s, const episode::Inputs& i) {
    ++episode_calls;
    return real_episode(s, i);
}
extern "C" double real_pid(control::State&, const Observation&) asm("__real__ZN7control4stepERNS_5StateERK11Observation");
extern "C" double wrapped_pid(control::State&, const Observation&) asm("__wrap__ZN7control4stepERNS_5StateERK11Observation");
extern "C" double wrapped_pid(control::State& s, const Observation& o) {
    ++pid_calls;
    return real_pid(s, o);
}

static Packet packet(std::uint64_t tick, std::uint32_t flags = 1,
                     double theta = 0.125, std::uint32_t reason = 0,
                     std::int64_t sent = 100) {
    unsigned char payload[telem::kSensorV1PayloadBytes];
    CHECK(telem::payload::encode_sensor(payload, sizeof payload, tick, sent,
                                       theta, 0.0, flags, 0, reason));
    Packet out{};
    CHECK(telem::encode_frame(4, static_cast<std::uint32_t>(tick), payload,
                             sizeof payload, out.data()) == out.size());
    return out;
}

static void ordinary_and_invalid() {
    freerun::Admission a(0, 4, 1);
    CHECK(a.begin_cycle(0));
    CHECK(a.receive(packet(0)) == K::Current);
    CHECK(a.receive(packet(0)) == K::Duplicate);
    CHECK(a.receive(packet(0, 1, 0.25)) == K::Conflict);
    const auto c0 = a.finish_cycle();
    CHECK(c0.fresh && c0.fresh->tick == 0 && c0.staleness == 0);
    CHECK(c0.rx_count == 3 && a.episode().received == 3);
    CHECK(a.episode().consumed == 1 && a.episode().duplicate == 1 && a.episode().conflict == 1);
    CHECK(a.recorded().received == 0 && a.identities_hold());
    CHECK(a.integrity_failed());
    CHECK(a.begin_cycle(1));
    CHECK(a.receive(packet(1, 0)) == K::Current);
    const auto c1 = a.finish_cycle();
    CHECK(!c1.fresh && c1.staleness == 1 && a.held()->tick == 0);
    CHECK(a.recorded().invalid == 1 && c1.discard_count == 0 && a.identities_hold());
    const auto count = a.episode().received;
    a.finish_cycle();
    CHECK(a.episode().received == count);

    freerun::Admission newest(10);
    CHECK(newest.begin_cycle(10));
    CHECK(newest.receive(packet(8)) == K::Current);
    CHECK(newest.receive(packet(10, 0)) == K::Current);
    CHECK(newest.receive(packet(9)) == K::Current);
    const auto c = newest.finish_cycle();
    CHECK(!c.fresh && !newest.held() && c.staleness == 1);
    CHECK(newest.episode().invalid == 1 && newest.episode().superseded == 2);
    CHECK(c.discard_count == 2 && newest.identities_hold());
}

static void ordered_classes() {
    freerun::Admission a(5);
    CHECK(a.begin_cycle(5));
    auto bad = packet(5); bad[0] ^= 1;
    CHECK(a.receive(bad) == K::Malformed);
    CHECK(a.receive(packet(5, 1, std::numeric_limits<double>::infinity())) == K::Nonfinite);
    CHECK(a.receive(packet(5, 1, std::numeric_limits<double>::infinity())) == K::Nonfinite);
    CHECK(a.receive(packet(4)) == K::Current);
    CHECK(a.receive(packet(7)) == K::Future);
    CHECK(a.receive(packet(10)) == K::ExcessiveSkew);
    CHECK(a.finish_cycle().fresh->tick == 4);
    CHECK(a.episode().bad_sync == 1 && a.episode().nonfinite == 2);
    CHECK(a.episode().skew_excess == 1 && a.future_parked() == 1 && a.identities_hold());
    CHECK(a.begin_cycle(6));
    CHECK(a.receive(packet(3)) == K::Old);
    CHECK(a.receive(packet(4)) == K::Old);
    CHECK(a.finish_cycle().discard_count == 2 && a.identities_hold());

    freerun::Admission errors(0);
    CHECK(errors.begin_cycle(0));
    bad = packet(0); bad[2] = 2; CHECK(errors.receive(bad) == K::Malformed);
    bad = packet(0); bad[3] = 5; CHECK(errors.receive(bad) == K::Malformed);
    bad = packet(0); bad[4] = 0; CHECK(errors.receive(bad) == K::Malformed);
    bad = packet(0); bad.back() ^= 1; CHECK(errors.receive(bad) == K::Malformed);
    CHECK(errors.receive(std::span<const unsigned char>(bad.data(), 3)) == K::Malformed);
    CHECK(errors.receive(packet(0), true) == K::Malformed);
    errors.finish_cycle();
    CHECK(errors.episode().bad_version == 1 && errors.episode().bad_type == 1);
    CHECK(errors.episode().bad_length == 3 && errors.episode().bad_crc == 1);
    CHECK(errors.episode().received == 0 && errors.identities_hold());
}

static void future_and_windows() {
    freerun::Admission a(0, 4, 1);
    CHECK(a.begin_cycle(0));
    CHECK(a.receive(packet(0)) == K::Current); // The retained origin frame.
    for (unsigned tick = 1; tick <= 4; ++tick) CHECK(a.receive(packet(tick)) == K::Future);
    CHECK(a.receive(packet(1)) == K::Duplicate); // Occupied slot, not newest RX.
    CHECK(a.receive(packet(1, 1, 0.125, 3)) == K::Conflict); // Last payload word.
    auto c = a.finish_cycle();
    CHECK(c.fresh->tick == 0 && a.future_parked() == 4 && a.identities_hold());
    CHECK(a.begin_cycle(1));
    c = a.finish_cycle();
    CHECK(c.rx_count == 0 && c.fresh && c.fresh->tick == 1);
    CHECK(a.episode().received == 7 && a.recorded().received == 0);
    CHECK(a.recorded().consumed == 1 && a.parked_at_warmup() == 4);
    CHECK(a.future_parked() == 3 && a.identities_hold());
    for (unsigned tick = 2; tick <= 4; ++tick) {
        CHECK(a.begin_cycle(tick));
        c = a.finish_cycle();
        CHECK(c.fresh && c.fresh->tick == tick && c.rx_count == 0);
        CHECK(a.identities_hold());
    }
    CHECK(a.future_parked() == 0 && a.episode().future_expired == 0);
    CHECK(a.begin_cycle(5));
    CHECK(a.receive(packet(6)) == K::Future);
    a.finish_cycle();
    CHECK(a.begin_cycle(7)); // Deliberate caller invariant violation.
    c = a.finish_cycle();
    CHECK(!c.fresh && a.episode().future_expired == 1 && a.integrity_failed());
    CHECK(a.identities_hold());
}

static void terminal_partition() {
    freerun::Admission a(0);
    CHECK(a.begin_cycle(0));
    CHECK(a.receive(packet(2, 2, std::numeric_limits<double>::quiet_NaN(), 1)) == K::Future);
    CHECK(a.receive(packet(2, 2, std::numeric_limits<double>::quiet_NaN(), 2)) == K::Conflict);
    CHECK(!a.finish_cycle().terminal && a.terminal_counts().received_raw == 2);
    CHECK(a.terminal_counts().conflict == 1 && a.episode().received == 0);
    CHECK(a.future_parked() == 0 && a.total_parked() == 1 && a.identities_hold());
    CHECK(a.begin_cycle(1)); CHECK(!a.finish_cycle().terminal);
    CHECK(a.begin_cycle(2));
    const auto c = a.finish_cycle();
    CHECK(c.terminal && c.terminal->tick == 2 && c.terminal->reason == 1);
    CHECK(!c.fresh && c.rx_count == 0 && c.discard_count == 0);
    CHECK(a.terminal_counts().received_raw == 2 && a.episode().consumed == 0 && a.identities_hold());

    freerun::Admission unknown(0);
    CHECK(unknown.begin_cycle(0));
    CHECK(unknown.receive(packet(0, 3, std::numeric_limits<double>::infinity(), 99)) == K::Current);
    CHECK(unknown.finish_cycle().terminal->reason == 99 && unknown.integrity_failed());
    CHECK(unknown.episode().nonfinite == 0 && unknown.terminal_counts().illegal_reason == 1);
}

static void boundaries_and_identities() {
    freerun::Admission a(10, 0);
    CHECK(!a.receive(packet(10)));
    CHECK(a.begin_cycle(10));
    CHECK(!a.begin_cycle(10));
    CHECK(a.receive(packet(11)) == K::ExcessiveSkew);
    CHECK(a.receive(packet(10)) == K::Current);
    a.finish_cycle();
    CHECK(!a.begin_cycle(9)); // Reject backward expected without unsigned-age underflow.
    CHECK(a.held()->tick == 10 && a.identities_hold());
    CHECK(a.begin_cycle(11));
    CHECK(a.finish_cycle().staleness == 1);

    freerun::Admission invalid(0, 65);
    CHECK(invalid.integrity_failed() && !invalid.begin_cycle(0));
    freerun::Admission full(0, 64);
    for (unsigned n = 0; n < 8; ++n) {
        CHECK(full.begin_cycle(n));
        for (unsigned j = 0; j < 8; ++j)
            CHECK(full.receive(packet(8 * n + j + 8)) == K::Future);
        full.finish_cycle();
        CHECK(full.total_parked() == 8 * (n + 1) && full.identities_hold());
    }
    CHECK(full.future_parked() == 64);
    CHECK(full.begin_cycle(8));
    CHECK(full.finish_cycle().fresh->tick == 8 && full.future_parked() == 63);

    freerun::Admission terminal(0);
    CHECK(terminal.begin_cycle(0));
    for (unsigned i = 0; i < 9; ++i) CHECK(terminal.receive(packet(4, 2, 0, 1)));
    CHECK(!terminal.receive(packet(4, 2, 0, 1)));
    CHECK(terminal.finish_cycle().rx_count == 9);
    CHECK(terminal.begin_cycle(1));
    for (unsigned i = 0; i < 8; ++i) CHECK(terminal.receive(packet(4, 2, 0, 1)));
    CHECK(!terminal.receive(packet(4, 2, 0, 1)));
    CHECK(!terminal.finish_cycle().terminal);
    CHECK(terminal.terminal_counts().received_raw == 17);
    CHECK(terminal.terminal_counts().duplicate == 16 && terminal.identities_hold());

    auto counts = full.episode();
    CHECK(counts.closes(0, 63));
    ++counts.received; CHECK(!counts.closes(0, 63));
    --counts.received; ++counts.consumed; CHECK(!counts.closes(0, 63));
    --counts.consumed; CHECK(!counts.closes(0, 62));
    freerun::Admission max_tick(UINT64_MAX);
    CHECK(max_tick.begin_cycle(UINT64_MAX));
    CHECK(max_tick.receive(packet(UINT64_MAX)) == K::Current);
    CHECK(max_tick.finish_cycle().fresh->tick == UINT64_MAX);
    CHECK(!max_tick.begin_cycle(0));
}

static void payload_identity() {
    // Every non-tick payload byte participates, including send time and sim_reason.
    for (unsigned offset = 8; offset < telem::kSensorV1PayloadBytes; ++offset) {
        freerun::Admission a(0);
        CHECK(a.begin_cycle(0));
        CHECK(a.receive(packet(0)) == K::Current);
        auto changed = packet(0);
        changed[10 + offset] ^= 1;
        wire::put_u32_le(changed.data(), changed.size() - 4,
                         telem::crc32c(changed.data() + 2, changed.size() - 6));
        CHECK(a.receive(changed) == K::Conflict);
        CHECK(a.finish_cycle().fresh->theta == 0.125 && a.integrity_failed());
        CHECK(a.identities_hold());
    }
    freerun::Admission promoted(0);
    CHECK(promoted.begin_cycle(0));
    CHECK(promoted.receive(packet(1)) == K::Future);
    CHECK(promoted.receive(packet(2)) == K::Future);
    promoted.finish_cycle();
    CHECK(promoted.begin_cycle(1));
    CHECK(promoted.receive(packet(1)) == K::Duplicate);
    CHECK(promoted.receive(packet(1, 1, 0.25)) == K::Conflict);
    const auto c = promoted.finish_cycle();
    CHECK(c.fresh->theta == 0.125 && c.rx_count == 2 && c.discard_count == 0);
    CHECK(promoted.identities_hold());
}

static void terminal_reordering() {
    freerun::Admission a(10);
    CHECK(a.begin_cycle(10));
    CHECK(a.receive(packet(11)) == K::Future);
    CHECK(a.receive(packet(9, 2, 0, 1)) == K::Current);
    CHECK(a.receive(packet(10, 2, 0, 1)) == K::Current);
    CHECK(a.receive(packet(10, 2, 0, 2)) == K::Conflict);
    CHECK(a.receive(packet(9, 2, 0, 2)) == K::Conflict);
    CHECK(a.finish_cycle().terminal->reason == 1);
    CHECK(a.terminal_counts().conflict == 2 && a.integrity_failed());
    CHECK(a.begin_cycle(11));
    CHECK(a.receive(packet(10, 2, 0, 3)) == K::Conflict);
    CHECK(a.finish_cycle().terminal->tick == 10);
    CHECK(a.identities_hold());

    freerun::Admission retry_due(0, 0);
    CHECK(retry_due.begin_cycle(0));
    CHECK(retry_due.receive(packet(1, 2, 0, 1)) == K::ExcessiveSkew);
    CHECK(!retry_due.finish_cycle().terminal);
    CHECK(retry_due.begin_cycle(1));
    CHECK(retry_due.receive(packet(1, 2, 0, 1)) == K::Duplicate);
    CHECK(retry_due.receive(packet(2)) == K::ExcessiveSkew);
    CHECK(retry_due.receive(packet(1, 2, 0, 2)) == K::Conflict);
    const auto c = retry_due.finish_cycle();
    CHECK(c.terminal && c.terminal->tick == 1);
    CHECK(retry_due.terminal_counts().received_raw == 3 && retry_due.integrity_failed());
    CHECK(retry_due.terminal_counts().conflict == 1);
    CHECK(retry_due.episode().received == 1 && retry_due.identities_hold());

    freerun::Admission delayed(0, 0);
    CHECK(delayed.begin_cycle(0));
    CHECK(delayed.receive(packet(1, 2, 0, 1)) == K::ExcessiveSkew);
    delayed.finish_cycle();
    CHECK(delayed.begin_cycle(1)); delayed.finish_cycle();
    CHECK(delayed.begin_cycle(2));
    CHECK(delayed.receive(packet(1, 2, 0, 1)) == K::Duplicate);
    CHECK(delayed.receive(packet(2, 2, 0, 1)) == K::Current);
    CHECK(delayed.receive(packet(3)) == K::ExcessiveSkew);
    CHECK(delayed.receive(packet(1, 2, 0, 2)) == K::Conflict);
    CHECK(delayed.finish_cycle().terminal->tick == 2 && delayed.identities_hold());
}

int main() {
    const auto initial = episode::initial(true);
    const episode::Inputs input{0, Observation{0, 0.125, 0, true}, true, 0, {}, false, {}, {}};
    CHECK(episode::step(initial, input).state.mode == episode::Mode::FLYING);
    CHECK(episode_calls == 1 && pid_calls == 1); // Prove the call observers are connected.
    episode_calls = pid_calls = 0;
    guard::set_mode(guard::Mode::Abort);
    {
        guard::Cycle scope;
        ordinary_and_invalid();
        ordered_classes();
        future_and_windows();
        terminal_partition();
        boundaries_and_identities();
        payload_identity();
        terminal_reordering();
    }
    guard::set_mode(guard::Mode::Off);
    CHECK(episode_calls == 0 && pid_calls == 0);
    std::puts("admission tests passed");
}

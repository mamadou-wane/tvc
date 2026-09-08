// Two-thread SPSC integrity and accounting for both record widths.
#include "../../src/telemetry.hpp"

#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <type_traits>

#define CHECK(cond) do { if (!(cond)) { \
    std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
    std::exit(1); } } while (0)

namespace {
template<class R>
R make(std::uint64_t i, std::uint64_t drops) {
    R r{};
    r.tick = i; r.deadline_ns = 3 * i + 1; r.woke_ns = 5 * i + 2;
    r.done_ns = 7 * i + 3; r.theta = static_cast<double>(i);
    r.cmd = -static_cast<double>(i); r.drops = drops;
    if constexpr (std::is_same_v<R, telem::ControlRecord>) {
        r.sensor_send_ns = 11 * i + 4; r.rx_ns = 13 * i + 5;
        r.tx_ns = 17 * i + 6; r.sensor_tick = i + 7;
        r.omega = i + 0.25; r.i_state = i + 0.5; r.d_prev = i + 0.75;
        r.staleness = i % 17; r.ack_cmd_seq = i + 8;
        r.rx_count = 9; r.discarded_old = 1; r.discarded_superseded = 2;
        r.discarded_other = 3; r.state = i % 5; r.reason = i % 11;
        r.flags = i % 256; r.ack_status = i % 7;
    }
    return r;
}

template<class R>
void check(const R& r) {
    const auto i = r.tick;
    CHECK(r.deadline_ns == static_cast<std::int64_t>(3 * i + 1));
    CHECK(r.woke_ns == static_cast<std::int64_t>(5 * i + 2));
    CHECK(r.done_ns == static_cast<std::int64_t>(7 * i + 3));
    CHECK(r.theta == static_cast<double>(i) && r.cmd == -static_cast<double>(i));
    if constexpr (std::is_same_v<R, telem::ControlRecord>) {
        CHECK(r.sensor_send_ns == static_cast<std::int64_t>(11 * i + 4));
        CHECK(r.rx_ns == static_cast<std::int64_t>(13 * i + 5));
        CHECK(r.tx_ns == static_cast<std::int64_t>(17 * i + 6));
        CHECK(r.sensor_tick == i + 7);
        CHECK(r.omega == i + 0.25 && r.i_state == i + 0.5 && r.d_prev == i + 0.75);
        CHECK(r.staleness == i % 17 && r.ack_cmd_seq == i + 8);
        CHECK(r.rx_count == 9 && r.discarded_old == 1 && r.discarded_superseded == 2);
        CHECK(r.discarded_other == 3 && r.state == i % 5 && r.reason == i % 11);
        CHECK(r.flags == i % 256 && r.ack_status == i % 7);
    }
}

template<class R>
void run() {
    telem::SpscRing<R> ring;
    R batch[512];
    CHECK(ring.pop_batch(batch, 512) == 0);
    // Force capacity and drop-newest without relying on thread scheduling.
    for (std::uint64_t i = 0; i < 4096; ++i) CHECK(ring.try_push(make<R>(i, 0)));
    CHECK(!ring.try_push(make<R>(4096, 0)) && ring.drops() == 1);
    std::uint64_t expected = 0;
    while (auto n = ring.pop_batch(batch, 512)) {
        for (std::size_t i = 0; i < n; ++i) { check(batch[i]); CHECK(batch[i].tick == expected++); }
    }
    CHECK(expected == 4096);
    CHECK(ring.try_push(make<R>(4097, ring.drops())));
    CHECK(ring.pop_batch(batch, 1) == 1 && batch[0].tick == 4097 && batch[0].drops == 1);

    constexpr std::uint64_t kAttempts = 2'000'000;
    std::atomic<bool> producer_done{false}, initial_full{false};
    std::uint64_t pushed = 0;
    const auto prior_drops = ring.drops();
    std::thread producer([&] {
        for (std::uint64_t i = 0; i < kAttempts; ++i) {
            if (ring.try_push(make<R>(i, ring.drops()))) ++pushed;
            if (i == 4096) initial_full.store(true, std::memory_order_release);
        }
        producer_done.store(true, std::memory_order_release);
    });
    while (!initial_full.load(std::memory_order_acquire)) std::this_thread::yield();
    std::uint64_t popped = 0, last_tick = 0, last_drops = prior_drops;
    bool first = true, done_seen = false;
    for (;;) {
        const auto n = ring.pop_batch(batch, 512);
        for (std::size_t i = 0; i < n; ++i) {
            check(batch[i]);
            CHECK(first || batch[i].tick > last_tick);
            CHECK(batch[i].drops >= last_drops);
            // Attempt index minus accepted-before-this is precisely prior drops.
            CHECK(batch[i].drops == prior_drops + batch[i].tick - (popped + i));
            last_tick = batch[i].tick; last_drops = batch[i].drops; first = false;
        }
        popped += n;
        if (n == 0) {
            if (done_seen) break;
            // Acquiring completion makes the final push visible; validate the next batch before stopping.
            done_seen = producer_done.load(std::memory_order_acquire);
            if (!done_seen) std::this_thread::yield();
        }
    }
    producer.join();
    CHECK(popped == pushed);
    CHECK(pushed + ring.drops() - prior_drops == kAttempts);
    CHECK(ring.drops() > prior_drops);
    std::printf("ring_stress: %zu-byte record ok (%llu accepted, %llu dropped)\n", sizeof(R),
                static_cast<unsigned long long>(pushed),
                static_cast<unsigned long long>(ring.drops() - prior_drops));
}
}  // namespace

int main() {
    run<telem::Record>();
    run<telem::ControlRecord>();
}

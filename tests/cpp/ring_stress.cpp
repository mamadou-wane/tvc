// tests/cpp/ring_stress.cpp — SPSC correctness under two real threads.
// Runs in the normal, ASan, and TSan trees; TSan is the reason it exists.
#include "../../src/telemetry.hpp"

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <thread>

#define CHECK(cond) do { if (!(cond)) { \
    std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
    std::exit(1); } } while (0)

namespace {

// Fields derived from tick so a torn read cannot go unnoticed.
telem::Record make(std::uint64_t i, std::uint64_t drops) {
    return {i, static_cast<std::int64_t>(3 * i + 1),
            static_cast<std::int64_t>(5 * i + 2),
            static_cast<std::int64_t>(7 * i + 3),
            static_cast<double>(i), -static_cast<double>(i), drops};
}

void check(const telem::Record& r) {
    const std::uint64_t i = r.tick;
    CHECK(r.deadline_ns == static_cast<std::int64_t>(3 * i + 1));
    CHECK(r.woke_ns == static_cast<std::int64_t>(5 * i + 2));
    CHECK(r.done_ns == static_cast<std::int64_t>(7 * i + 3));
    CHECK(r.theta == static_cast<double>(i));
    CHECK(r.cmd == -static_cast<double>(i));
}

}  // namespace

int main() {
    constexpr std::uint64_t kAttempts = 2'000'000;
    telem::SpscRing ring;
    std::atomic<bool> producer_done{false};
    std::uint64_t pushed = 0;

    std::thread producer([&] {
        for (std::uint64_t i = 0; i < kAttempts; ++i)
            if (ring.try_push(make(i, ring.drops()))) ++pushed;
        producer_done.store(true, std::memory_order_release);
    });

    std::uint64_t popped = 0, last_tick = 0;
    bool first = true;
    std::mt19937 rng(42);
    telem::Record batch[512];
    for (;;) {
        const std::size_t n = ring.pop_batch(batch, 512);
        for (std::size_t i = 0; i < n; ++i) {
            check(batch[i]);
            if (!first) CHECK(batch[i].tick > last_tick);   // FIFO, no dupes
            last_tick = batch[i].tick;
            first = false;
        }
        popped += n;
        if (n == 0) {
            if (producer_done.load(std::memory_order_acquire) &&
                ring.pop_batch(batch, 512) == 0) break;
            if (rng() % 8 == 0)   // stall to force full-ring drops
                std::this_thread::sleep_for(std::chrono::microseconds(200));
        }
    }
    producer.join();
    CHECK(popped == pushed);
    CHECK(pushed + ring.drops() == kAttempts);
    std::printf("ring_stress: ok (%llu pushed, %llu dropped)\n",
                static_cast<unsigned long long>(pushed),
                static_cast<unsigned long long>(ring.drops()));
    return 0;
}

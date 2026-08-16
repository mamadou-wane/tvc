// src/telemetry.hpp — v0.2a telemetry: record, wire codec, SPSC ring, drain.
// Spec: docs/superpowers/specs/2026-08-16-telemetry-v02a-design.md.
#pragma once
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <type_traits>
#include <vector>

namespace telem {

// One control cycle, exactly the 56-byte wire payload: the drain frames
// records by header-wrap, never field-by-field marshal.
struct Record {
    std::uint64_t tick;
    std::int64_t  deadline_ns;
    std::int64_t  woke_ns;
    std::int64_t  done_ns;
    double        theta;
    double        cmd;
    std::uint64_t drops;   // cumulative try_push failures before this record
};
static_assert(sizeof(Record) == 56);
static_assert(std::is_trivially_copyable_v<Record>);

inline constexpr std::uint16_t kSync          = 0xEB90;
inline constexpr std::uint8_t  kVersion       = 1;
inline constexpr std::uint8_t  kTypeTelemetry = 1;
inline constexpr std::uint32_t kSchemaHash    = 0xA871CD84u;
inline constexpr std::size_t   kMaxPayload    = 498;
inline constexpr std::size_t   kFrameOverhead = 14;
inline constexpr const char*   kSchema =
    "telemetry_v1:tick:u64,deadline_ns:i64,woke_ns:i64,done_ns:i64,"
    "theta:f64,cmd:f64,drops:u64";

// CRC-32C (Castagnoli), reflected, init/xorout 0xFFFFFFFF: the value
// google-crc32c computes. Byte-wise table; drain-side only.
std::uint32_t crc32c(const void* data, std::size_t len) noexcept;

// Frame encoder: writes kFrameOverhead + len bytes into out and returns that
// count. Caller guarantees len <= kMaxPayload and a large-enough buffer.
std::size_t encode_frame(std::uint8_t type, std::uint32_t seq,
                         const void* payload, std::size_t len,
                         unsigned char* out) noexcept;

// Decode counters and decoded frame information.
struct DecodeCounters {
    std::uint64_t frames_ok;
    std::uint64_t crc_errors;
    std::uint64_t version_mismatch;
    std::uint64_t resyncs;
    std::uint64_t seq_discontinuities;
    std::uint64_t lost;
    std::uint64_t skipped_bytes;
};

struct DecodedFrame {
    std::uint8_t type;
    std::uint32_t seq;
    std::size_t payload_off;
    std::size_t payload_len;
};

// Stream decoder: parses frames from data buffer, appends DecodedFrame
// entries to out (with offsets into the caller's buffer), returns counters.
DecodeCounters decode_stream(const unsigned char* data, std::size_t len,
                             std::vector<DecodedFrame>& out) noexcept;

// Single-producer single-consumer ring. Producer is the control thread:
// try_push is allocation-free, syscall-free, lock-free, and wait-free.
// Drop-newest on full; the producer-owned drop counter is published
// in-stream via Record::drops.
class SpscRing {
public:
    static constexpr std::size_t kSlots = 4096;   // power of two, ~8 s at 500 Hz

    bool try_push(const Record& r) noexcept {
        const std::uint64_t head = head_.load(std::memory_order_relaxed);
        if (head - cached_tail_ == kSlots) {
            cached_tail_ = tail_.load(std::memory_order_acquire);
            if (head - cached_tail_ == kSlots) { ++drops_; return false; }
        }
        slots_[head & (kSlots - 1)] = r;
        head_.store(head + 1, std::memory_order_release);
        return true;
    }

    std::size_t pop_batch(Record* out, std::size_t max) noexcept {
        const std::uint64_t head = head_.load(std::memory_order_acquire);
        std::uint64_t tail = tail_.load(std::memory_order_relaxed);
        std::size_t n = 0;
        while (tail != head && n < max) out[n++] = slots_[tail++ & (kSlots - 1)];
        tail_.store(tail, std::memory_order_release);
        return n;
    }

    std::uint64_t drops() const noexcept { return drops_; }

private:
    std::array<Record, kSlots> slots_{};
    alignas(64) std::atomic<std::uint64_t> head_{0};
    alignas(64) std::atomic<std::uint64_t> tail_{0};
    alignas(64) std::uint64_t cached_tail_ = 0;   // producer-owned
    std::uint64_t drops_ = 0;                     // producer-owned
};

}  // namespace telem

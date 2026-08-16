// src/telemetry.hpp — v0.2a telemetry: record, wire codec, SPSC ring, drain.
// Spec: docs/superpowers/specs/2026-08-16-telemetry-v02a-design.md.
#pragma once
#include <cstddef>
#include <cstdint>
#include <type_traits>

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

}  // namespace telem

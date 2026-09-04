// Fixed-offset little-endian scalars; independent of native record layout.
#pragma once

#include <bit>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <limits>

namespace wire {

static_assert(CHAR_BIT == 8);
static_assert(sizeof(double) == 8);
static_assert(std::numeric_limits<double>::is_iec559);
static_assert(std::numeric_limits<double>::radix == 2);
static_assert(std::numeric_limits<double>::digits == 53);
static_assert(std::numeric_limits<double>::max_exponent == 1024);

// The caller supplies a buffer covering the field at offset o. No alignment
// is required. Floating-point helpers move bits without evaluating the value.
inline void put_u8(unsigned char* p, std::size_t o, std::uint8_t v) noexcept {
    p[o] = v;
}

inline void put_u16_le(unsigned char* p, std::size_t o, std::uint16_t v) noexcept {
    p[o]     = static_cast<unsigned char>(v);
    p[o + 1] = static_cast<unsigned char>(v >> 8);
}

inline void put_u32_le(unsigned char* p, std::size_t o, std::uint32_t v) noexcept {
    p[o]     = static_cast<unsigned char>(v);
    p[o + 1] = static_cast<unsigned char>(v >> 8);
    p[o + 2] = static_cast<unsigned char>(v >> 16);
    p[o + 3] = static_cast<unsigned char>(v >> 24);
}

inline void put_u64_le(unsigned char* p, std::size_t o, std::uint64_t v) noexcept {
    p[o]     = static_cast<unsigned char>(v);
    p[o + 1] = static_cast<unsigned char>(v >> 8);
    p[o + 2] = static_cast<unsigned char>(v >> 16);
    p[o + 3] = static_cast<unsigned char>(v >> 24);
    p[o + 4] = static_cast<unsigned char>(v >> 32);
    p[o + 5] = static_cast<unsigned char>(v >> 40);
    p[o + 6] = static_cast<unsigned char>(v >> 48);
    p[o + 7] = static_cast<unsigned char>(v >> 56);
}

inline void put_i64_le(unsigned char* p, std::size_t o, std::int64_t v) noexcept {
    put_u64_le(p, o, static_cast<std::uint64_t>(v));
}

inline void put_f64_le(unsigned char* p, std::size_t o, double v) noexcept {
    put_u64_le(p, o, std::bit_cast<std::uint64_t>(v));
}

inline std::uint8_t get_u8(const unsigned char* p, std::size_t o) noexcept {
    return p[o];
}

inline std::uint16_t get_u16_le(const unsigned char* p, std::size_t o) noexcept {
    return static_cast<std::uint16_t>(p[o]) |
           static_cast<std::uint16_t>(p[o + 1]) << 8;
}

inline std::uint32_t get_u32_le(const unsigned char* p, std::size_t o) noexcept {
    return static_cast<std::uint32_t>(p[o]) |
           static_cast<std::uint32_t>(p[o + 1]) << 8 |
           static_cast<std::uint32_t>(p[o + 2]) << 16 |
           static_cast<std::uint32_t>(p[o + 3]) << 24;
}

inline std::uint64_t get_u64_le(const unsigned char* p, std::size_t o) noexcept {
    return static_cast<std::uint64_t>(p[o]) |
           static_cast<std::uint64_t>(p[o + 1]) << 8 |
           static_cast<std::uint64_t>(p[o + 2]) << 16 |
           static_cast<std::uint64_t>(p[o + 3]) << 24 |
           static_cast<std::uint64_t>(p[o + 4]) << 32 |
           static_cast<std::uint64_t>(p[o + 5]) << 40 |
           static_cast<std::uint64_t>(p[o + 6]) << 48 |
           static_cast<std::uint64_t>(p[o + 7]) << 56;
}

inline std::int64_t get_i64_le(const unsigned char* p, std::size_t o) noexcept {
    // The out-of-range unsigned-to-signed conversion is modulo 2^64 in C++20.
    return static_cast<std::int64_t>(get_u64_le(p, o));
}

inline double get_f64_le(const unsigned char* p, std::size_t o) noexcept {
    return std::bit_cast<double>(get_u64_le(p, o));
}

}  // namespace wire

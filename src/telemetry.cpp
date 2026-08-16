#include "telemetry.hpp"

#include <array>
#include <cstring>

namespace telem {
namespace {

constexpr std::array<std::uint32_t, 256> make_crc_table() {
    std::array<std::uint32_t, 256> t{};
    for (std::uint32_t i = 0; i < 256; ++i) {
        std::uint32_t c = i;
        for (int k = 0; k < 8; ++k)
            c = (c & 1u) ? (c >> 1) ^ 0x82F63B78u : c >> 1;
        t[i] = c;
    }
    return t;
}
constexpr auto kCrcTable = make_crc_table();

}  // namespace

std::uint32_t crc32c(const void* data, std::size_t len) noexcept {
    const auto* p = static_cast<const unsigned char*>(data);
    std::uint32_t c = 0xFFFFFFFFu;
    for (std::size_t i = 0; i < len; ++i)
        c = kCrcTable[(c ^ p[i]) & 0xFFu] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

namespace {
inline void put16(unsigned char* p, std::uint16_t v) noexcept {
    p[0] = static_cast<unsigned char>(v);
    p[1] = static_cast<unsigned char>(v >> 8);
}
inline void put32(unsigned char* p, std::uint32_t v) noexcept {
    p[0] = static_cast<unsigned char>(v);
    p[1] = static_cast<unsigned char>(v >> 8);
    p[2] = static_cast<unsigned char>(v >> 16);
    p[3] = static_cast<unsigned char>(v >> 24);
}
}  // namespace

std::size_t encode_frame(std::uint8_t type, std::uint32_t seq,
                         const void* payload, std::size_t len,
                         unsigned char* out) noexcept {
    put16(out, kSync);
    out[2] = kVersion;
    out[3] = type;
    put16(out + 4, static_cast<std::uint16_t>(len));
    put32(out + 6, seq);
    std::memcpy(out + 10, payload, len);
    put32(out + 10 + len, crc32c(out + 2, 8 + len));
    return kFrameOverhead + len;
}

}  // namespace telem

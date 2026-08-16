#include "telemetry.hpp"

#include <array>
#include <cstring>
#include <ctime>
#include <cstdio>

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

DecodeCounters decode_stream(const unsigned char* data, std::size_t len,
                             std::vector<DecodedFrame>& out) noexcept {
    DecodeCounters ctr{};
    bool locked = true;
    bool have_expected = false;
    std::uint32_t expected = 0;
    std::size_t consumed = 0;
    std::size_t pos = 0;
    while (pos + 2 <= len) {
        if (!(data[pos] == 0x90 && data[pos + 1] == 0xEB)) { ++pos; continue; }
        if (pos + kFrameOverhead - 4 > len) break;    // header cut off
        const std::uint8_t ver = data[pos + 2];
        const std::uint8_t type = data[pos + 3];
        const std::size_t plen = data[pos + 4] |
                                 static_cast<std::size_t>(data[pos + 5]) << 8;
        const auto fail = [&](bool is_version, bool is_crc) {
            if (is_version) ++ctr.version_mismatch;
            if (is_crc) ++ctr.crc_errors;
            if (locked) { ++ctr.resyncs; locked = false; }
            ++pos;
        };
        if (ver != kVersion) { fail(true, false); continue; }
        if (!(type >= 1 && type <= 3) || plen > kMaxPayload) {
            fail(false, false); continue;
        }
        const std::size_t end = pos + kFrameOverhead + plen;
        if (end > len) break;                          // frame extends past buffer
        const std::uint32_t crc =
            static_cast<std::uint32_t>(data[end - 4]) |
            static_cast<std::uint32_t>(data[end - 3]) << 8 |
            static_cast<std::uint32_t>(data[end - 2]) << 16 |
            static_cast<std::uint32_t>(data[end - 1]) << 24;
        if (crc != crc32c(data + pos + 2, 8 + plen)) { fail(false, true); continue; }
        const std::uint32_t seq =
            static_cast<std::uint32_t>(data[pos + 6]) |
            static_cast<std::uint32_t>(data[pos + 7]) << 8 |
            static_cast<std::uint32_t>(data[pos + 8]) << 16 |
            static_cast<std::uint32_t>(data[pos + 9]) << 24;
        out.push_back({type, seq, pos + 10, plen});
        ++ctr.frames_ok;
        consumed += kFrameOverhead + plen;
        if (have_expected) {
            const std::uint32_t gap = seq - expected;   // u32 wrap is the mod
            if (gap >= 1 && gap < 0x80000000u) ctr.lost += gap;
            else if (gap >= 0x80000000u) ++ctr.seq_discontinuities;
        }
        expected = seq + 1;
        have_expected = true;
        locked = true;
        pos = end;
    }
    ctr.skipped_bytes = len - consumed;
    return ctr;
}

namespace {
inline void put64(unsigned char* p, std::uint64_t v) noexcept {
    for (int i = 0; i < 8; ++i) p[i] = static_cast<unsigned char>(v >> (8 * i));
}
}  // namespace

std::size_t encode_recording_header(std::int64_t mono_ns,
                                    std::int64_t epoch_ns,
                                    unsigned char* out) noexcept {
    std::memcpy(out, "TVCRECRD", 8);
    put16(out + 8, 1);
    put16(out + 10, 0);
    put32(out + 12, kSchemaHash);
    put64(out + 16, static_cast<std::uint64_t>(mono_ns));
    put64(out + 24, static_cast<std::uint64_t>(epoch_ns));
    return 32;
}

void Drain::start(std::FILE* f) {
    file_ = f;
    thread_ = std::thread([this] { run(); });
}

void Drain::stop() {
    stop_.store(true, std::memory_order_release);
    thread_.join();
}

void Drain::run() {
    Record batch[512];
    unsigned char frame[kFrameOverhead + sizeof(Record)];
    for (;;) {
        const std::size_t n = ring_.pop_batch(batch, 512);
        for (std::size_t i = 0; i < n; ++i) {
            const std::size_t len = encode_frame(
                kTypeTelemetry, seq_++, &batch[i], sizeof(Record), frame);
            if (std::fwrite(frame, 1, len, file_) != len)
                write_failed_.store(true, std::memory_order_relaxed);
            else { ++records_; bytes_ += len; }
        }
        if (n == 0) {
            if (stop_.load(std::memory_order_acquire)) break;
            const timespec ts{0, 1000000};   // 1 ms poll; no futex from the producer
            ::clock_nanosleep(CLOCK_MONOTONIC, 0, &ts, nullptr);
        }
    }
    if (std::fflush(file_) != 0)
        write_failed_.store(true, std::memory_order_relaxed);
    std::fclose(file_);
}

}  // namespace telem

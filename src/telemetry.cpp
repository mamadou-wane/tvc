#include "telemetry.hpp"
#include "wire.hpp"

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
        if (!(type >= 1 && type <= 6) || plen > kMaxPayload) {
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

DatagramError decode_datagram(const unsigned char* data, std::size_t len,
                             std::initializer_list<std::uint8_t> accepted_types,
                             DecodedFrame& out) noexcept {
    if (len < kFrameOverhead) return DatagramError::BadLength;
    if (wire::get_u16_le(data, 0) != kSync) return DatagramError::BadSync;
    if (data[2] != kVersion) return DatagramError::BadVersion;
    const auto type = data[3];
    bool accepted = false;
    for (auto allowed : accepted_types) if (type == allowed) accepted = true;
    if (type < 1 || type > 6 || !accepted) return DatagramError::BadType;
    constexpr std::size_t sizes[] = {0, kTelemetryV1PayloadBytes, kCommandV1PayloadBytes,
        kAckV1PayloadBytes, kSensorV1PayloadBytes, kActuatorV1PayloadBytes, kControlV1PayloadBytes};
    const auto size = wire::get_u16_le(data, 4);
    if (size != sizes[type] || len != kFrameOverhead + size) return DatagramError::BadLength;
    if (wire::get_u32_le(data, len - 4) != crc32c(data + 2, 8 + size)) return DatagramError::BadCrc;
    out = {type, wire::get_u32_le(data, 6), 10, size};
    return DatagramError::None;
}

namespace payload {
using namespace wire;

bool encode_record(unsigned char* p, std::size_t len, const Record& r) noexcept {
    if (len != kTelemetryV1PayloadBytes) return false;
    put_u64_le(p, 0, r.tick);
    put_i64_le(p, 8, r.deadline_ns);
    put_i64_le(p, 16, r.woke_ns);
    put_i64_le(p, 24, r.done_ns);
    put_f64_le(p, 32, r.theta);
    put_f64_le(p, 40, r.cmd);
    put_u64_le(p, 48, r.drops);
    return true;
}

bool decode_record(const unsigned char* p, std::size_t len, Record& r) noexcept {
    if (len != kTelemetryV1PayloadBytes) return false;
    r.tick = get_u64_le(p, 0);
    r.deadline_ns = get_i64_le(p, 8);
    r.woke_ns = get_i64_le(p, 16);
    r.done_ns = get_i64_le(p, 24);
    r.theta = get_f64_le(p, 32);
    r.cmd = get_f64_le(p, 40);
    r.drops = get_u64_le(p, 48);
    return true;
}

bool encode_command(unsigned char* p, std::size_t len, std::uint32_t cmd_seq,
                    std::uint16_t opcode, std::uint16_t flags, std::uint64_t effective_tick) noexcept {
    if (len != kCommandV1PayloadBytes) return false;
    put_u32_le(p, 0, cmd_seq);
    put_u16_le(p, 4, opcode);
    put_u16_le(p, 6, flags & 0x0001u);
    put_u64_le(p, 8, effective_tick);
    return true;
}

bool decode_command(const unsigned char* p, std::size_t len, std::uint32_t& cmd_seq,
                    std::uint16_t& opcode, std::uint16_t& flags, std::uint64_t& effective_tick) noexcept {
    if (len != kCommandV1PayloadBytes) return false;
    cmd_seq = get_u32_le(p, 0);
    opcode = get_u16_le(p, 4);
    flags = get_u16_le(p, 6);
    effective_tick = get_u64_le(p, 8);
    return true;
}

bool encode_ack(unsigned char* p, std::size_t len, std::uint64_t applied_tick,
                std::uint32_t cmd_seq, std::uint16_t status, std::uint8_t state, std::uint8_t reason) noexcept {
    if (len != kAckV1PayloadBytes) return false;
    put_u64_le(p, 0, applied_tick);
    put_u32_le(p, 8, cmd_seq);
    put_u16_le(p, 12, status);
    put_u8(p, 14, state);
    put_u8(p, 15, reason);
    return true;
}

bool decode_ack(const unsigned char* p, std::size_t len, std::uint64_t& applied_tick,
                std::uint32_t& cmd_seq, std::uint16_t& status, std::uint8_t& state, std::uint8_t& reason) noexcept {
    if (len != kAckV1PayloadBytes) return false;
    applied_tick = get_u64_le(p, 0);
    cmd_seq = get_u32_le(p, 8);
    status = get_u16_le(p, 12);
    state = get_u8(p, 14);
    reason = get_u8(p, 15);
    return true;
}

bool encode_sensor(unsigned char* p, std::size_t len, std::uint64_t tick, std::int64_t t_send_ns,
                   double theta, double omega, std::uint32_t flags,
                   std::uint32_t cmd_seq, std::uint32_t sim_reason) noexcept {
    if (len != kSensorV1PayloadBytes) return false;
    put_u64_le(p, 0, tick);
    put_i64_le(p, 8, t_send_ns);
    put_f64_le(p, 16, theta);
    put_f64_le(p, 24, omega);
    put_u32_le(p, 32, flags & 0x0000ff07u);
    put_u32_le(p, 36, cmd_seq);
    put_u32_le(p, 40, sim_reason);
    return true;
}

bool decode_sensor(const unsigned char* p, std::size_t len, std::uint64_t& tick, std::int64_t& t_send_ns,
                   double& theta, double& omega, std::uint32_t& flags,
                   std::uint32_t& cmd_seq, std::uint32_t& sim_reason) noexcept {
    if (len != kSensorV1PayloadBytes) return false;
    tick = get_u64_le(p, 0);
    t_send_ns = get_i64_le(p, 8);
    theta = get_f64_le(p, 16);
    omega = get_f64_le(p, 24);
    flags = get_u32_le(p, 32);
    cmd_seq = get_u32_le(p, 36);
    sim_reason = get_u32_le(p, 40);
    return true;
}

bool encode_actuator(unsigned char* p, std::size_t len, std::uint64_t tick, std::uint64_t veh_tick,
                     std::int64_t t_sensor_send_ns, std::int64_t t_veh_send_ns,
                     double delta, std::uint32_t status, std::uint32_t staleness) noexcept {
    if (len != kActuatorV1PayloadBytes) return false;
    put_u64_le(p, 0, tick);
    put_u64_le(p, 8, veh_tick);
    put_i64_le(p, 16, t_sensor_send_ns);
    put_i64_le(p, 24, t_veh_send_ns);
    put_f64_le(p, 32, delta);
    put_u32_le(p, 40, status);
    put_u32_le(p, 44, staleness);
    return true;
}

bool decode_actuator(const unsigned char* p, std::size_t len, std::uint64_t& tick, std::uint64_t& veh_tick,
                     std::int64_t& t_sensor_send_ns, std::int64_t& t_veh_send_ns,
                     double& delta, std::uint32_t& status, std::uint32_t& staleness) noexcept {
    if (len != kActuatorV1PayloadBytes) return false;
    tick = get_u64_le(p, 0);
    veh_tick = get_u64_le(p, 8);
    t_sensor_send_ns = get_i64_le(p, 16);
    t_veh_send_ns = get_i64_le(p, 24);
    delta = get_f64_le(p, 32);
    status = get_u32_le(p, 40);
    staleness = get_u32_le(p, 44);
    return true;
}

namespace {
bool valid_counts(std::uint8_t rx, std::uint8_t old, std::uint8_t superseded,
                  std::uint8_t other) noexcept {
    return rx <= 9 && static_cast<unsigned>(old) + superseded + other <= rx;
}
}  // namespace

bool encode_control(unsigned char* p, std::size_t len, const ControlRecord& r) noexcept {
    if (len != kControlV1PayloadBytes ||
        !valid_counts(r.rx_count, r.discarded_old, r.discarded_superseded, r.discarded_other)) return false;
    put_u64_le(p, 0, r.tick);
    put_i64_le(p, 8, r.deadline_ns);
    put_i64_le(p, 16, r.woke_ns);
    put_i64_le(p, 24, r.done_ns);
    put_i64_le(p, 32, r.sensor_send_ns);
    put_i64_le(p, 40, r.rx_ns);
    put_i64_le(p, 48, r.tx_ns);
    put_u64_le(p, 56, r.sensor_tick);
    put_f64_le(p, 64, r.theta);
    put_f64_le(p, 72, r.omega);
    put_f64_le(p, 80, r.cmd);
    put_f64_le(p, 88, r.i_state);
    put_f64_le(p, 96, r.d_prev);
    put_u64_le(p, 104, r.drops);
    put_u32_le(p, 112, r.staleness);
    put_u32_le(p, 116, r.ack_cmd_seq);
    put_u8(p, 120, r.rx_count);
    put_u8(p, 121, r.discarded_old);
    put_u8(p, 122, r.discarded_superseded);
    put_u8(p, 123, r.discarded_other);
    put_u8(p, 124, r.state);
    put_u8(p, 125, r.reason);
    put_u8(p, 126, r.flags);
    put_u8(p, 127, r.ack_status);
    return true;
}

bool decode_control(const unsigned char* p, std::size_t len, ControlRecord& r) noexcept {
    if (len != kControlV1PayloadBytes) return false;
    if (!valid_counts(p[120], p[121], p[122], p[123])) return false;
    r.tick = get_u64_le(p, 0);
    r.deadline_ns = get_i64_le(p, 8);
    r.woke_ns = get_i64_le(p, 16);
    r.done_ns = get_i64_le(p, 24);
    r.sensor_send_ns = get_i64_le(p, 32);
    r.rx_ns = get_i64_le(p, 40);
    r.tx_ns = get_i64_le(p, 48);
    r.sensor_tick = get_u64_le(p, 56);
    r.theta = get_f64_le(p, 64);
    r.omega = get_f64_le(p, 72);
    r.cmd = get_f64_le(p, 80);
    r.i_state = get_f64_le(p, 88);
    r.d_prev = get_f64_le(p, 96);
    r.drops = get_u64_le(p, 104);
    r.staleness = get_u32_le(p, 112);
    r.ack_cmd_seq = get_u32_le(p, 116);
    r.rx_count = get_u8(p, 120);
    r.discarded_old = get_u8(p, 121);
    r.discarded_superseded = get_u8(p, 122);
    r.discarded_other = get_u8(p, 123);
    r.state = get_u8(p, 124);
    r.reason = get_u8(p, 125);
    r.flags = get_u8(p, 126);
    r.ack_status = get_u8(p, 127);
    return true;
}

}  // namespace payload

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
    unsigned char frame[kFrameOverhead + kTelemetryV1PayloadBytes];
    bool stop_seen = false;
    for (;;) {
        const std::size_t n = ring_.pop_batch(batch, 512);
        for (std::size_t i = 0; i < n; ++i) {
            const Record& r = batch[i];
            unsigned char payload[kTelemetryV1PayloadBytes];
            wire::put_u64_le(payload,  0, r.tick);
            wire::put_i64_le(payload,  8, r.deadline_ns);
            wire::put_i64_le(payload, 16, r.woke_ns);
            wire::put_i64_le(payload, 24, r.done_ns);
            wire::put_f64_le(payload, 32, r.theta);
            wire::put_f64_le(payload, 40, r.cmd);
            wire::put_u64_le(payload, 48, r.drops);
            const std::size_t len = encode_frame(
                kTypeTelemetry, seq_++, payload, kTelemetryV1PayloadBytes, frame);
            if (std::fwrite(frame, 1, len, file_) != len)
                write_failed_.store(true, std::memory_order_relaxed);
            else { ++records_; bytes_ += len; }
        }
        if (n == 0) {
            if (stop_seen) break;
            if (stop_.load(std::memory_order_acquire)) {
                // One more pop is guaranteed to see the final push:
                // final_push -> stop_.store -> this load -> next pop.
                stop_seen = true;
                continue;
            }
            const timespec ts{0, 1000000};   // 1 ms poll; no futex from the producer
            ::clock_nanosleep(CLOCK_MONOTONIC, 0, &ts, nullptr);
        }
    }
    if (std::fflush(file_) != 0)
        write_failed_.store(true, std::memory_order_relaxed);
    std::fclose(file_);
}

}  // namespace telem

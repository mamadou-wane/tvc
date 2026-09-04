// src/telemetry.hpp: v0.2a telemetry (record, wire codec, SPSC ring, drain).
// Spec: docs/superpowers/specs/2026-08-16-telemetry-v02a-design.md.
#pragma once
#include <array>
#include <atomic>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include <thread>
#include <type_traits>
#include <vector>

namespace telem {

// One control cycle in the ring. The drain encodes its fields explicitly;
// these layout assertions are tripwires, not a serialization mechanism.
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
static_assert(std::is_standard_layout_v<Record>);
static_assert(std::endian::native == std::endian::little);
static_assert(alignof(Record) == 8);
static_assert(offsetof(Record, tick)        ==  0);
static_assert(offsetof(Record, deadline_ns) ==  8);
static_assert(offsetof(Record, woke_ns)     == 16);
static_assert(offsetof(Record, done_ns)     == 24);
static_assert(offsetof(Record, theta)       == 32);
static_assert(offsetof(Record, cmd)         == 40);
static_assert(offsetof(Record, drops)       == 48);

// Internal value layout for the control payload. Ring use and its serializer
// are separate work; declaring this record does not change the active stream.
struct ControlRecord {
    std::uint64_t tick;
    std::int64_t  deadline_ns;
    std::int64_t  woke_ns;
    std::int64_t  done_ns;
    std::int64_t  sensor_send_ns;
    std::int64_t  rx_ns;
    std::int64_t  tx_ns;
    std::uint64_t sensor_tick;
    double        theta;
    double        omega;
    double        cmd;
    double        i_state;
    double        d_prev;
    std::uint64_t drops;
    std::uint32_t staleness;
    std::uint32_t ack_cmd_seq;
    std::uint8_t  rx_count;
    std::uint8_t  discarded_old;
    std::uint8_t  discarded_superseded;
    std::uint8_t  discarded_other;
    std::uint8_t  state;
    std::uint8_t  reason;
    std::uint8_t  flags;
    std::uint8_t  ack_status;
};
static_assert(std::is_trivially_copyable_v<ControlRecord>);
static_assert(std::is_standard_layout_v<ControlRecord>);
static_assert(alignof(ControlRecord) == 8);
static_assert(sizeof(ControlRecord) == 128);
static_assert(offsetof(ControlRecord, tick)                 ==   0);
static_assert(offsetof(ControlRecord, deadline_ns)          ==   8);
static_assert(offsetof(ControlRecord, woke_ns)              ==  16);
static_assert(offsetof(ControlRecord, done_ns)              ==  24);
static_assert(offsetof(ControlRecord, sensor_send_ns)       ==  32);
static_assert(offsetof(ControlRecord, rx_ns)                ==  40);
static_assert(offsetof(ControlRecord, tx_ns)                ==  48);
static_assert(offsetof(ControlRecord, sensor_tick)          ==  56);
static_assert(offsetof(ControlRecord, theta)                ==  64);
static_assert(offsetof(ControlRecord, omega)                ==  72);
static_assert(offsetof(ControlRecord, cmd)                  ==  80);
static_assert(offsetof(ControlRecord, i_state)              ==  88);
static_assert(offsetof(ControlRecord, d_prev)               ==  96);
static_assert(offsetof(ControlRecord, drops)                == 104);
static_assert(offsetof(ControlRecord, staleness)            == 112);
static_assert(offsetof(ControlRecord, ack_cmd_seq)          == 116);
static_assert(offsetof(ControlRecord, rx_count)             == 120);
static_assert(offsetof(ControlRecord, discarded_old)        == 121);
static_assert(offsetof(ControlRecord, discarded_superseded) == 122);
static_assert(offsetof(ControlRecord, discarded_other)      == 123);
static_assert(offsetof(ControlRecord, state)                == 124);
static_assert(offsetof(ControlRecord, reason)               == 125);
static_assert(offsetof(ControlRecord, flags)                == 126);
static_assert(offsetof(ControlRecord, ack_status)           == 127);

inline constexpr std::uint16_t kSync          = 0xEB90;
inline constexpr std::uint8_t  kVersion       = 1;
inline constexpr std::uint8_t  kTypeTelemetry = 1;
inline constexpr std::uint32_t kSchemaHash    = 0xA871CD84u;
inline constexpr std::size_t   kMaxPayload    = 498;
inline constexpr std::size_t   kFrameOverhead = 14;
inline constexpr const char*   kSchema =
    "telemetry_v1:tick:u64,deadline_ns:i64,woke_ns:i64,done_ns:i64,"
    "theta:f64,cmd:f64,drops:u64";

// Schema metadata does not expand the generic decoder's accepted type set.
inline constexpr std::size_t kTelemetryV1PayloadBytes = 56;
inline constexpr std::size_t kCommandV1PayloadBytes   = 16;
inline constexpr std::size_t kAckV1PayloadBytes       = 16;
inline constexpr std::size_t kSensorV1PayloadBytes    = 44;
inline constexpr std::size_t kActuatorV1PayloadBytes  = 48;
inline constexpr std::size_t kControlV1PayloadBytes   = 128;

inline constexpr const char* kCommandV1Schema =
    "command_v1:cmd_seq:u32,opcode:u16,flags:u16,effective_tick:u64";
inline constexpr const char* kAckV1Schema =
    "ack_v1:applied_tick:u64,cmd_seq:u32,status:u16,state:u8,reason:u8";
inline constexpr const char* kSensorV1Schema =
    "sensor_v1:tick:u64,t_send_ns:i64,theta:f64,omega:f64,flags:u32,"
    "cmd_seq:u32,sim_reason:u32";
inline constexpr const char* kActuatorV1Schema =
    "actuator_v1:tick:u64,veh_tick:u64,t_sensor_send_ns:i64,t_veh_send_ns:i64,"
    "delta:f64,status:u32,staleness:u32";
inline constexpr const char* kControlV1Schema =
    "control_v1:tick:u64,deadline_ns:i64,woke_ns:i64,done_ns:i64,"
    "sensor_send_ns:i64,rx_ns:i64,tx_ns:i64,sensor_tick:u64,theta:f64,"
    "omega:f64,cmd:f64,i_state:f64,d_prev:f64,drops:u64,staleness:u32,"
    "ack_cmd_seq:u32,rx_count:u8,discarded_old:u8,discarded_superseded:u8,"
    "discarded_other:u8,state:u8,reason:u8,flags:u8,ack_status:u8";

inline constexpr std::uint32_t kCommandV1SchemaHash  = 0x7F802902u;
inline constexpr std::uint32_t kAckV1SchemaHash      = 0x3D42AF39u;
inline constexpr std::uint32_t kSensorV1SchemaHash   = 0xD23A4196u;
inline constexpr std::uint32_t kActuatorV1SchemaHash = 0x25573656u;
inline constexpr std::uint32_t kControlV1SchemaHash  = 0xADFA94C8u;

namespace payload {

// Buffer sizes are checked before payload access; false on length/count failure.
// Types 2-5 use scalar values, never a native wire-layout struct. Reserved flag
// bits are zeroed by writers and retained without interpretation by readers.
bool encode_record(unsigned char*, std::size_t, const Record&) noexcept;
bool decode_record(const unsigned char*, std::size_t, Record&) noexcept;
bool encode_command(unsigned char*, std::size_t, std::uint32_t cmd_seq,
                    std::uint16_t opcode, std::uint16_t flags, std::uint64_t effective_tick) noexcept;
bool decode_command(const unsigned char*, std::size_t, std::uint32_t& cmd_seq,
                    std::uint16_t& opcode, std::uint16_t& flags, std::uint64_t& effective_tick) noexcept;
bool encode_ack(unsigned char*, std::size_t, std::uint64_t applied_tick,
                std::uint32_t cmd_seq, std::uint16_t status, std::uint8_t state, std::uint8_t reason) noexcept;
bool decode_ack(const unsigned char*, std::size_t, std::uint64_t& applied_tick,
                std::uint32_t& cmd_seq, std::uint16_t& status, std::uint8_t& state, std::uint8_t& reason) noexcept;
bool encode_sensor(unsigned char*, std::size_t, std::uint64_t tick, std::int64_t t_send_ns,
                   double theta, double omega, std::uint32_t flags,
                   std::uint32_t cmd_seq, std::uint32_t sim_reason) noexcept;
bool decode_sensor(const unsigned char*, std::size_t, std::uint64_t& tick, std::int64_t& t_send_ns,
                   double& theta, double& omega, std::uint32_t& flags,
                   std::uint32_t& cmd_seq, std::uint32_t& sim_reason) noexcept;
bool encode_actuator(unsigned char*, std::size_t, std::uint64_t tick, std::uint64_t veh_tick,
                     std::int64_t t_sensor_send_ns, std::int64_t t_veh_send_ns,
                     double delta, std::uint32_t status, std::uint32_t staleness) noexcept;
bool decode_actuator(const unsigned char*, std::size_t, std::uint64_t& tick, std::uint64_t& veh_tick,
                     std::int64_t& t_sensor_send_ns, std::int64_t& t_veh_send_ns,
                     double& delta, std::uint32_t& status, std::uint32_t& staleness) noexcept;
bool encode_control(unsigned char*, std::size_t, const ControlRecord&) noexcept;
bool decode_control(const unsigned char*, std::size_t, ControlRecord&) noexcept;

}  // namespace payload

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

enum class DatagramError { None, BadSync, BadVersion, BadType, BadLength, BadCrc };

// One datagram, no resynchronization or allocation. On success, returns a raw
// payload location for the separate typed decoder; failure leaves out unchanged.
DatagramError decode_datagram(const unsigned char* data, std::size_t len,
                             std::initializer_list<std::uint8_t> accepted_types,
                             DecodedFrame& out) noexcept;

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

// Writes the 32-byte recording header into out and returns 32.
std::size_t encode_recording_header(std::int64_t mono_ns,
                                    std::int64_t epoch_ns,
                                    unsigned char* out) noexcept;

// Consumer side of the ring. Runs SCHED_OTHER off the isolated core (it
// inherits scheduling from whoever calls start(); call before rt setup).
// The alloc guard's flag is thread_local, so this thread may allocate.
class Drain {
public:
    explicit Drain(SpscRing& ring) : ring_(ring) {}
    void start(std::FILE* f);
    void stop();
    bool write_failed() const noexcept {
        return write_failed_.load(std::memory_order_relaxed);
    }
    std::uint64_t records_written() const noexcept { return records_; }
    std::uint64_t bytes_written() const noexcept { return bytes_; }

private:
    void run();
    SpscRing& ring_;
    std::FILE* file_ = nullptr;
    std::thread thread_;
    std::atomic<bool> stop_{false};
    std::atomic<bool> write_failed_{false};
    std::uint64_t records_ = 0;   // thread-owned; read after stop()
    std::uint64_t bytes_ = 0;
    std::uint32_t seq_ = 0;
};

}  // namespace telem

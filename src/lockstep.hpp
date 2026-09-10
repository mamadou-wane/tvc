#pragma once

#include "alloc_guard.hpp"
#include "episode.hpp"
#include "net.hpp"
#include "telemetry.hpp"
#include <array>
#include <atomic>
#include <string>

namespace lockstep {

struct ReceiveCounters {
    std::uint64_t received_raw=0, malformed=0, received=0, decode_pending=0;
    std::uint64_t logical_received=0, discarded_duplicate=0, rejected_received=0, classification_pending=0;
    std::uint64_t admitted=0, sample_invalid=0, sample_nonfinite=0, admission_pending=0;
    std::uint64_t discarded_old=0, discarded_tick_conflict=0, skipped_tick=0;
    std::uint64_t bad_sync=0, bad_version=0, bad_type=0, bad_length=0, bad_crc=0;
};
struct SendCounters {
    std::uint64_t generated=0, original_attempts=0, retry_attempts=0, not_attempted=0;
    std::uint64_t send_attempts=0, send_pending=0, tx_fail=0, transmitted=0;
    std::uint64_t first_transmitted=0, additional_copies=0, never_transmitted=0, original_tx_fail=0;
};
struct CycleCounters {
    std::uint64_t episode_transitions=0, pid_calls=0, record_attempts=0;
    std::uint64_t records_pushed=0, ring_drops=0, record_pending=0;
};
struct AckProjection { int selected=-1; bool applied=false; };
AckProjection project_ack(const episode::AckBatch& acks) noexcept;
// Applies both scalar projections; returns actuator status byte 3.
std::uint8_t apply_acks(const episode::AckBatch& acks, telem::ControlRecord& record) noexcept;
std::uint32_t constants_digest() noexcept;
enum class Disposition { Discard, New, Cached, Fatal };

// One control-thread owner. Cached receipts never advance policy or alter record().
class Session {
public:
    explicit Session(bool auto_arm) noexcept : state_(episode::initial(auto_arm)) {}
    Disposition receive(const net::Datagram& packet) noexcept;
    void begin_send(bool original) noexcept;
    void finish_send(bool original, bool success) noexcept;
    // One report of the actual ring result for each New disposition.
    void note_record(bool pushed) noexcept;
    void stop(episode::Reason reason) noexcept;
    const auto& reply() const noexcept { return reply_; }
    const auto& record() const noexcept { return record_; }
    const auto& acks() const noexcept { return acks_; }
    episode::Reason reason() const noexcept;
    std::uint64_t reason_tick() const noexcept;
    std::optional<std::uint32_t> sim_reason_seen() const noexcept { return sim_seen_; }
    bool integrity_failed() const noexcept { return integrity_; }
    ReceiveCounters up{};
    SendCounters down{};
    CycleCounters events{};
private:
    episode::State state_;
    std::optional<Observation> held_;
    std::optional<std::uint32_t> sim_seen_;
    std::optional<episode::TerminalResult> fault_;
    episode::AckBatch acks_{};
    bool answered_=false, reply_transmitted_=false, integrity_=false;
    std::uint64_t newest_answered_=0;
    std::array<unsigned char,telem::kSensorV1PayloadBytes> last_payload_{};
    std::array<unsigned char,telem::kFrameOverhead+telem::kActuatorV1PayloadBytes> reply_{};
    telem::ControlRecord record_{};
};

struct Config {
    std::string label, outdir;
    std::uint16_t sensor_port=24000;
    bool auto_arm=false, mlock=false;
    int cpu=-1, fifo_prio=0;
    guard::Mode alloc_guard=guard::Mode::Off;
};
void ready(const char* mode, unsigned port);
int run(const Config& config, std::atomic<bool>& stop);

}  // namespace lockstep

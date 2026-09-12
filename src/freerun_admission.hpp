#pragma once

#include "telemetry.hpp"
#include <optional>
#include <span>

namespace freerun {

enum class SensorClass {
    Malformed = 1, Nonfinite, Duplicate, Conflict, Old, Current, Future, ExcessiveSkew
};

struct Sample {
    std::uint64_t tick;
    std::int64_t send_ns;
    double theta;
    double omega;
};

struct Terminal {
    std::uint64_t tick;
    std::uint32_t reason;
};

struct AdmissionCounts {
    std::uint64_t received{}, consumed{}, old{}, superseded{}, nonfinite{};
    std::uint64_t skew_excess{}, duplicate{}, conflict{}, invalid{}, future_expired{};
    std::uint64_t bad_sync{}, bad_version{}, bad_type{}, bad_length{}, bad_crc{};

    std::uint64_t dispositions() const noexcept;
    bool closes(std::uint64_t initial_occupancy, std::uint64_t final_occupancy) const noexcept;
    void add(const AdmissionCounts&) noexcept;
};

struct TerminalCounts {
    std::uint64_t received_raw{}, duplicate{}, conflict{}, skew_excess{};
    std::uint64_t future_expired{}, illegal_reason{};
};

struct Discard {
    // Current denotes a superseded class-6 candidate in this list.
    SensorClass kind;
    std::int64_t send_ns;
};

struct AdmissionCycle {
    std::optional<Sample> fresh;
    std::optional<Terminal> terminal;
    std::uint32_t staleness{};
    std::uint8_t rx_count{}, discard_count{};
    std::array<Discard, 9> discards{};
    AdmissionCounts counts;
};

// One scheduled control-thread owner. No clocks, sockets, policy calls or allocation.
class Admission {
public:
    static constexpr unsigned kMaxSkew = 64;
    Admission(std::uint64_t tick_base, unsigned skew_max = 4,
              std::uint64_t warmup = 0) noexcept;

    // Caller supplies tick_base+n. A gap is an integrity fault, with obsolete slots dispositioned.
    bool begin_cycle(std::uint64_t expected) noexcept;
    // Carry is supplied once in cycle zero before the batch. Nullopt rejects API misuse.
    std::optional<SensorClass> receive(std::span<const unsigned char>, bool truncated = false) noexcept;
    // Idempotent until the next begin_cycle; this only admits input, never runs policy.
    const AdmissionCycle& finish_cycle() noexcept;

    const std::optional<Sample>& held() const noexcept { return held_; }
    const AdmissionCounts& episode() const noexcept { return episode_; }
    const AdmissionCounts& recorded() const noexcept { return recorded_; }
    const TerminalCounts& terminal_counts() const noexcept { return terminal_counts_; }
    std::uint64_t future_parked() const noexcept;
    std::uint64_t total_parked() const noexcept;
    std::optional<std::uint64_t> parked_at_warmup() const noexcept { return warmup_occupancy_; }
    std::optional<std::uint64_t> last_received_tick() const noexcept { return last_normal_tick_; }
    bool identities_hold() const noexcept;
    bool integrity_failed() const noexcept { return integrity_; }

private:
    struct Frame {
        Sample sample{};
        std::uint32_t flags{}, cmd_seq{}, reason{};
        std::array<unsigned char, telem::kSensorV1PayloadBytes> payload{};
        bool terminal() const noexcept { return (flags & 2) != 0; }
    };
    static_assert(sizeof(Frame::payload) == telem::kSensorV1PayloadBytes);

    void remember(const Frame&) noexcept;
    const Frame* identity(const Frame&) const noexcept;
    void candidate(const Frame&) noexcept;
    void terminal(const Frame&) noexcept;
    void discard(SensorClass, const Frame&) noexcept;
    void expire(const Frame&) noexcept;

    std::uint64_t tick_base_, warmup_, expected_{}, cycles_{};
    std::optional<std::uint64_t> warmup_occupancy_, last_normal_tick_;
    unsigned skew_max_;
    bool open_{}, integrity_{}, valid_;
    std::array<std::optional<Frame>, kMaxSkew + 1> future_{};
    std::optional<Frame> newest_received_, due_, candidate_;
    std::optional<Sample> held_;
    std::optional<Frame> terminal_latch_, terminal_candidate_;
    // Preserve terminal identities when a higher tick displaces newest_received_.
    std::array<Frame, 9> terminal_seen_{};
    unsigned terminal_seen_count_{};
    AdmissionCycle cycle_;
    AdmissionCounts episode_, recorded_;
    TerminalCounts terminal_counts_;
};

} // namespace freerun

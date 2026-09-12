#include "freerun_admission.hpp"
#include <cmath>
#include <cstring>
#include <limits>

namespace freerun {

std::uint64_t AdmissionCounts::dispositions() const noexcept {
    return consumed + old + superseded + nonfinite + skew_excess + duplicate +
           conflict + invalid + future_expired;
}

bool AdmissionCounts::closes(std::uint64_t initial, std::uint64_t final) const noexcept {
    return received + initial == dispositions() + final;
}

void AdmissionCounts::add(const AdmissionCounts& c) noexcept {
    using Member = std::uint64_t AdmissionCounts::*;
    constexpr Member fields[] = {
        &AdmissionCounts::received, &AdmissionCounts::consumed, &AdmissionCounts::old,
        &AdmissionCounts::superseded, &AdmissionCounts::nonfinite, &AdmissionCounts::skew_excess,
        &AdmissionCounts::duplicate, &AdmissionCounts::conflict, &AdmissionCounts::invalid,
        &AdmissionCounts::future_expired, &AdmissionCounts::bad_sync, &AdmissionCounts::bad_version,
        &AdmissionCounts::bad_type, &AdmissionCounts::bad_length, &AdmissionCounts::bad_crc
    };
    for (auto field : fields) this->*field += c.*field;
}

Admission::Admission(std::uint64_t tick_base, unsigned skew_max, std::uint64_t warmup) noexcept
    : tick_base_(tick_base), warmup_(warmup), skew_max_(skew_max), valid_(skew_max <= kMaxSkew) {
    integrity_ = !valid_;
}

std::uint64_t Admission::future_parked() const noexcept {
    std::uint64_t count = 0;
    for (const auto& f : future_) if (f && !f->terminal()) ++count;
    return count;
}

std::uint64_t Admission::total_parked() const noexcept {
    std::uint64_t count = 0;
    for (const auto& f : future_) if (f) ++count;
    return count;
}

bool Admission::begin_cycle(std::uint64_t expected) noexcept {
    if (!valid_ || open_) { integrity_ = true; return false; }
    if ((cycles_ == 0 && expected != tick_base_) || (cycles_ != 0 && expected <= expected_)) {
        integrity_ = true;
        return false;
    }
    if (cycles_ != 0 && expected != expected_ + 1)
        integrity_ = true;
    if (cycles_ == warmup_) warmup_occupancy_ = future_parked();
    expected_ = expected;
    open_ = true;
    cycle_ = {};
    candidate_.reset(); due_.reset(); terminal_candidate_.reset();
    terminal_seen_count_ = 0;
    std::array<std::optional<Frame>, kMaxSkew + 1> shifted{};
    for (const auto& f : future_) {
        if (!f) continue;
        if (f->sample.tick < expected) expire(*f);
        else if (f->sample.tick == expected) {
            due_ = *f;
            if (f->terminal()) terminal(*f);
            else candidate(*f);
        } else {
            const auto distance = f->sample.tick - expected;
            if (distance > skew_max_) expire(*f);
            else shifted[distance - 1] = *f;
        }
    }
    future_ = shifted;
    return true;
}

void Admission::remember(const Frame& f) noexcept {
    if (!newest_received_ || f.sample.tick > newest_received_->sample.tick) newest_received_ = f;
}

const Admission::Frame* Admission::identity(const Frame& incoming) const noexcept {
    const auto tick = incoming.sample.tick;
    if (newest_received_ && newest_received_->sample.tick == tick) return &*newest_received_;
    if (due_ && due_->sample.tick == tick) return &*due_;
    for (const auto& f : future_) if (f && f->sample.tick == tick) return &*f;
    if (terminal_candidate_ && terminal_candidate_->sample.tick == tick) return &*terminal_candidate_;
    if (terminal_latch_ && terminal_latch_->sample.tick == tick) return &*terminal_latch_;
    for (unsigned i = 0; i < terminal_seen_count_; ++i)
        if (terminal_seen_[i].sample.tick == tick) return &terminal_seen_[i];
    if (incoming.terminal() && candidate_ && candidate_->sample.tick == tick) return &*candidate_;
    return nullptr;
}

void Admission::discard(SensorClass kind, const Frame& f) noexcept {
    if (cycle_.discard_count == cycle_.discards.size()) { integrity_ = true; return; }
    cycle_.discards[cycle_.discard_count++] = {kind, f.sample.send_ns};
}

void Admission::candidate(const Frame& f) noexcept {
    if (!candidate_) { candidate_ = f; return; }
    ++cycle_.counts.superseded;
    if (f.sample.tick > candidate_->sample.tick) {
        discard(SensorClass::Current, *candidate_);
        candidate_ = f;
    } else discard(SensorClass::Current, f);
}

void Admission::terminal(const Frame& f) noexcept {
    if (f.reason < 1 || f.reason > 3) { ++terminal_counts_.illegal_reason; integrity_ = true; }
    if (!terminal_latch_ && (!terminal_candidate_ || f.sample.tick > terminal_candidate_->sample.tick))
        terminal_candidate_ = f;
}

void Admission::expire(const Frame& f) noexcept {
    integrity_ = true;
    if (f.terminal()) ++terminal_counts_.future_expired;
    else ++cycle_.counts.future_expired;
}

std::optional<SensorClass> Admission::receive(std::span<const unsigned char> bytes, bool truncated) noexcept {
    if (!open_ || cycle_.rx_count >= (cycles_ == 0 ? 9 : 8)) {
        integrity_ = true;
        return std::nullopt;
    }
    ++cycle_.rx_count;
    telem::DecodedFrame decoded{};
    const auto error = truncated ? telem::DatagramError::BadLength :
        telem::decode_datagram(bytes.data(), bytes.size(), {4}, decoded);
    if (error != telem::DatagramError::None) {
        switch (error) {
        case telem::DatagramError::BadSync: ++cycle_.counts.bad_sync; break;
        case telem::DatagramError::BadVersion: ++cycle_.counts.bad_version; break;
        case telem::DatagramError::BadType: ++cycle_.counts.bad_type; break;
        case telem::DatagramError::BadLength: ++cycle_.counts.bad_length; break;
        case telem::DatagramError::BadCrc: ++cycle_.counts.bad_crc; break;
        case telem::DatagramError::None: break;
        }
        integrity_ = true;
        return SensorClass::Malformed;
    }
    Frame f;
    std::memcpy(f.payload.data(), bytes.data() + decoded.payload_off, f.payload.size());
    telem::payload::decode_sensor(f.payload.data(), f.payload.size(), f.sample.tick,
        f.sample.send_ns, f.sample.theta, f.sample.omega, f.flags, f.cmd_seq, f.reason);
    if (f.terminal()) ++terminal_counts_.received_raw;
    else {
        ++cycle_.counts.received;
        if (!last_normal_tick_ || f.sample.tick > *last_normal_tick_) last_normal_tick_ = f.sample.tick;
    }

    // Terminal envelopes have their own partition; their sample usability cannot hide a reason.
    if (!f.terminal() && (f.flags & 1) &&
        (!std::isfinite(f.sample.theta) || !std::isfinite(f.sample.omega))) {
        ++cycle_.counts.nonfinite;
        discard(SensorClass::Nonfinite, f);
        remember(f);
        return SensorClass::Nonfinite;
    }
    if (const auto* prior = identity(f)) {
        const bool duplicate = prior->payload == f.payload;
        if (f.terminal()) {
            if (duplicate) ++terminal_counts_.duplicate;
            else ++terminal_counts_.conflict;
        } else {
            if (duplicate) ++cycle_.counts.duplicate;
            else ++cycle_.counts.conflict;
        }
        if (!duplicate) integrity_ = true;
        if (duplicate && f.terminal()) {
            terminal_seen_[terminal_seen_count_++] = f;
            if (f.sample.tick <= expected_) terminal(f);
        }
        return duplicate ? SensorClass::Duplicate : SensorClass::Conflict;
    }
    if (f.terminal()) terminal_seen_[terminal_seen_count_++] = f;
    remember(f);
    if (!f.terminal() && held_ && f.sample.tick <= held_->tick) {
        ++cycle_.counts.old;
        discard(SensorClass::Old, f);
        return SensorClass::Old;
    }
    if (f.sample.tick <= expected_) {
        if (f.terminal()) terminal(f);
        else candidate(f);
        return SensorClass::Current;
    }
    const auto distance = f.sample.tick - expected_;
    if (distance <= skew_max_) {
        future_[distance - 1] = f;
        return SensorClass::Future;
    }
    if (f.terminal()) ++terminal_counts_.skew_excess;
    else { ++cycle_.counts.skew_excess; discard(SensorClass::ExcessiveSkew, f); }
    integrity_ = true;
    return SensorClass::ExcessiveSkew;
}

const AdmissionCycle& Admission::finish_cycle() noexcept {
    if (!open_) return cycle_;
    if (candidate_) {
        if (candidate_->flags & 1) {
            cycle_.fresh = held_ = candidate_->sample;
            ++cycle_.counts.consumed;
        } else ++cycle_.counts.invalid;
    }
    if (!terminal_latch_ && terminal_candidate_) terminal_latch_ = terminal_candidate_;
    if (terminal_latch_) cycle_.terminal = Terminal{terminal_latch_->sample.tick, terminal_latch_->reason};
    const auto age = held_ ? expected_ - held_->tick : cycles_ + 1;
    cycle_.staleness = static_cast<std::uint32_t>(age > UINT32_MAX ? UINT32_MAX : age);
    episode_.add(cycle_.counts);
    if (cycles_ >= warmup_) recorded_.add(cycle_.counts);
    ++cycles_;
    open_ = false;
    return cycle_;
}

bool Admission::identities_hold() const noexcept {
    return !open_ && episode_.closes(0, future_parked()) &&
        (cycles_ <= warmup_ || recorded_.closes(*warmup_occupancy_, future_parked()));
}

} // namespace freerun

#include "lockstep.hpp"
#include "wire.hpp"
#include "loop_stats.hpp"
#include "rt_setup.hpp"
#include <cmath>
#include <cstring>
#include <limits>

namespace lockstep {

AckProjection project_ack(const episode::AckBatch& acks) noexcept {
    AckProjection result;
    for (unsigned i=0;i<acks.count;++i) {
        const bool applied=acks.values[i].status==episode::AckStatus::APPLIED ||
                           acks.values[i].status==episode::AckStatus::APPLIED_LATE;
        if (result.selected<0 || (applied && !result.applied)) result.selected=static_cast<int>(i);
        result.applied=result.applied || applied;
    }
    return result;
}
std::uint8_t apply_acks(const episode::AckBatch& acks, telem::ControlRecord& record) noexcept {
    const auto projection=project_ack(acks);
    record.flags &= static_cast<std::uint8_t>(~68u);
    record.ack_cmd_seq=0; record.ack_status=0;
    if (projection.selected<0) return 0;
    const auto& ack=acks.values[projection.selected];
    record.ack_cmd_seq=ack.cmd_seq; record.ack_status=static_cast<std::uint8_t>(ack.status);
    record.flags|=64;
    if (projection.applied) record.flags|=4;
    return static_cast<std::uint8_t>(0x80|record.ack_status);
}
std::uint32_t constants_digest() noexcept {
    unsigned char bytes[56];
    const double values[]={control::KP,control::KI_DT,control::KD,control::BETA_D,
                           control::DELTA_MAX,control::I_MAX,control::DT};
    for (unsigned i=0;i<7;++i) wire::put_f64_le(bytes,8*i,values[i]);
    return telem::crc32c(bytes,sizeof bytes);
}
Disposition Session::receive(const net::Datagram& packet) noexcept {
    ++up.received_raw;
    telem::DecodedFrame frame{};
    auto error=packet.truncated() ? telem::DatagramError::BadLength :
        telem::decode_datagram(packet.bytes.data(),packet.size,{4},frame);
    if (error!=telem::DatagramError::None) {
        ++up.malformed; integrity_=true;
        switch(error) {
            case telem::DatagramError::BadSync: ++up.bad_sync; break;
            case telem::DatagramError::BadVersion: ++up.bad_version; break;
            case telem::DatagramError::BadType: ++up.bad_type; break;
            case telem::DatagramError::BadLength: ++up.bad_length; break;
            case telem::DatagramError::BadCrc: ++up.bad_crc; break;
            case telem::DatagramError::None: break;
        }
        return Disposition::Discard;
    }
    ++up.received;
    const auto* p=packet.bytes.data()+frame.payload_off;
    std::uint64_t tick; std::int64_t stamp; double theta,omega;
    std::uint32_t flags,cmd_seq,sim_reason;
    telem::payload::decode_sensor(p,frame.payload_len,tick,stamp,theta,omega,flags,cmd_seq,sim_reason);
    if (answered_ && tick==newest_answered_) {
        if (std::memcmp(p,last_payload_.data(),last_payload_.size())==0) {
            ++up.discarded_duplicate; return Disposition::Cached;
        }
        ++up.rejected_received; ++up.discarded_tick_conflict; integrity_=true;
        return Disposition::Discard;
    }
    if (answered_ && tick<newest_answered_) {
        ++up.rejected_received; ++up.discarded_old; return Disposition::Discard;
    }
    if ((!answered_ && tick!=0) || (answered_ && tick!=newest_answered_+1)) {
        ++up.rejected_received; ++up.skipped_tick;
        fault_=episode::TerminalResult{answered_?episode::Reason::INTERNAL:episode::Reason::PEER_LOST,tick};
        return Disposition::Fatal;
    }
    const auto cycle=up.logical_received++;
    const bool fresh=(flags&1) && std::isfinite(theta) && std::isfinite(omega);
    if (fresh) { held_=Observation{tick,theta,omega,true}; ++up.admitted; }
    else if (!(flags&1)) ++up.sample_invalid;
    else ++up.sample_nonfinite;
    const auto age64=held_?tick-held_->tick:cycle+1;
    const auto age=static_cast<std::uint32_t>(age64>0xffffffffULL?0xffffffffULL:age64);
    std::optional<episode::Command> command;
    if (flags&4) command=episode::Command{cmd_seq,static_cast<std::uint16_t>((flags>>8)&255),tick+50};
    std::optional<std::uint32_t> terminal;
    if (flags&2) {
        terminal=sim_reason; sim_seen_=sim_reason;
        if (sim_reason<1 || sim_reason>3) integrity_=true;
    }
    const auto result=episode::step(state_,{tick,held_,fresh,age,command,false,terminal,{}});
    ++events.episode_transitions; ++events.record_pending;
    // The frozen episode contract calls PID once for fresh FLYING output.
    if (fresh && result.state.mode==episode::Mode::FLYING) ++events.pid_calls;
    state_=result.state; acks_=result.acks;
    const unsigned rung=age>=21?3:fresh?0:age<=8?1:2;
    const auto why=state_.terminal?state_.terminal->reason:episode::Reason::NONE;
    record_={}; record_.tick=tick;
    record_.sensor_tick=held_?held_->tick:std::numeric_limits<std::uint64_t>::max();
    record_.theta=held_?held_->theta:0.0; record_.omega=held_?held_->omega:0.0;
    record_.cmd=result.requested_delta; record_.i_state=state_.pid.i_state;
    record_.d_prev=state_.pid.d_prev; record_.staleness=age; record_.rx_count=1;
    record_.state=static_cast<std::uint8_t>(state_.mode); record_.reason=static_cast<std::uint8_t>(why);
    record_.flags=(fresh?1:0) | (rung==1?8:0) | (rung==2?16:0);
    if ((flags&1) && !fresh) { record_.discarded_other=1; record_.flags|=128; }
    const unsigned ack_byte=apply_acks(acks_,record_);
    const std::uint32_t status=record_.state | (std::uint32_t(record_.reason)<<8) | (rung<<16) | (ack_byte<<24);
    unsigned char payload[telem::kActuatorV1PayloadBytes];
    telem::payload::encode_actuator(payload,sizeof payload,tick,cycle,0,0,result.requested_delta,status,age);
    telem::encode_frame(5,static_cast<std::uint32_t>(cycle),payload,sizeof payload,reply_.data());
    std::memcpy(last_payload_.data(),p,last_payload_.size());
    newest_answered_=tick; answered_=true; reply_transmitted_=false;
    ++down.generated; ++down.not_attempted; ++down.never_transmitted;
    return Disposition::New;
}
void Session::begin_send(bool original) noexcept {
    ++down.send_attempts; ++down.send_pending;
    if (original) { ++down.original_attempts; --down.not_attempted; }
    else ++down.retry_attempts;
}
void Session::finish_send(bool original,bool success) noexcept {
    --down.send_pending;
    if (success) {
        ++down.transmitted;
        if (reply_transmitted_) ++down.additional_copies;
        else { ++down.first_transmitted; --down.never_transmitted; reply_transmitted_=true; }
    } else { ++down.tx_fail; if (original) ++down.original_tx_fail; }
    if (original && success) record_.flags|=2;
}
void Session::note_record(bool pushed) noexcept {
    ++events.record_attempts; --events.record_pending;
    if (pushed) ++events.records_pushed;
    else ++events.ring_drops;
}
void Session::stop(episode::Reason why) noexcept {
    if (!state_.terminal && !fault_) fault_=episode::TerminalResult{why,answered_?newest_answered_:0};
}
episode::Reason Session::reason() const noexcept {
    return fault_?fault_->reason:state_.terminal?state_.terminal->reason:episode::Reason::NONE;
}
std::uint64_t Session::reason_tick() const noexcept {
    return fault_?fault_->tick:state_.terminal?state_.terminal->tick:0;
}

}  // namespace lockstep

#include <cerrno>
#include <cstdio>
#include <memory>
#include <sstream>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <unistd.h>

namespace lockstep {
namespace {
const char* reason_name(episode::Reason reason) {
    constexpr const char* names[]={"NONE","STABILIZED","DIVERGED","GROUND_ABORT",
        "SENSOR_LOST","PEER_LOST","SIGNAL","NOT_SETTLED","INTERNAL"};
    return names[static_cast<unsigned>(reason)];
}
const char* sim_name(std::uint32_t reason) {
    switch(reason) {
        case 0:return "SIM_NONE";
        case 1:return "SIM_HORIZON";
        case 2:return "SIM_LOC_ANGLE";
        case 3:return "SIM_LOC_NONFINITE";
        case 4:return "SIM_VEHICLE_TERMINAL";
        case 6:return "SIM_PEER_LOST";
        default:return "UNKNOWN";
    }
}
std::string counters(const ReceiveCounters& c) {
    std::ostringstream out; out << '{';
#define FIELD(name) out << "\"" #name "\":" << c.name << ','
    FIELD(received_raw); FIELD(malformed); FIELD(received); FIELD(decode_pending);
    FIELD(logical_received); FIELD(discarded_duplicate); FIELD(rejected_received); FIELD(classification_pending);
    FIELD(admitted); FIELD(sample_invalid); FIELD(sample_nonfinite); FIELD(admission_pending);
    FIELD(discarded_old); FIELD(discarded_tick_conflict); FIELD(skipped_tick);
    FIELD(bad_sync); FIELD(bad_version); FIELD(bad_type); FIELD(bad_length);
#undef FIELD
    out << "\"bad_crc\":" << c.bad_crc << '}'; return out.str();
}
std::string counters(const SendCounters& c) {
    std::ostringstream out; out << '{';
#define FIELD(name) out << "\"" #name "\":" << c.name << ','
    FIELD(generated); FIELD(original_attempts); FIELD(retry_attempts); FIELD(not_attempted);
    FIELD(send_attempts); FIELD(send_pending); FIELD(tx_fail); FIELD(transmitted);
    FIELD(first_transmitted); FIELD(additional_copies); FIELD(never_transmitted);
#undef FIELD
    out << "\"original_tx_fail\":" << c.original_tx_fail << '}'; return out.str();
}
}
void ready(const char* mode, unsigned port) {
    char binary[4096]{};
    const auto n=::readlink("/proc/self/exe",binary,sizeof binary-1);
    if (n<0) std::strcpy(binary,"unknown");
    std::printf("ready mode=%s sensor_port=%u command_port=0 pid=%ld bin=%s consts=0x%08x\n",
                mode,port,static_cast<long>(::getpid()),binary,constants_digest());
    std::fflush(stdout);
}
int run(const Config& cfg,std::atomic<bool>& stop_requested) {
    sockaddr_in local{},bound{};
    local.sin_family=AF_INET; local.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    local.sin_port=htons(cfg.sensor_port);
    int fd=net::open_udp(local,bound);
    if (fd<0) { std::perror("lockstep socket"); return 2; }
    ::mkdir(cfg.outdir.c_str(),0755);
    const auto prefix=cfg.outdir+"/"+cfg.label;
    FILE* file=std::fopen((prefix+".control.tvcrec").c_str(),"wb");
    if (!file) { std::perror("lockstep recording"); net::close_udp(fd); return 4; }
    unsigned char header[32];
    telem::encode_recording_header(0,0,header,telem::kControlV1SchemaHash);
    if (std::fwrite(header,1,sizeof header,file)!=sizeof header) {
        std::fclose(file); net::close_udp(fd); return 4;
    }
    auto ring=std::make_unique<telem::SpscRing<telem::ControlRecord>>();
    telem::Drain<telem::ControlRecord> drain(*ring);
    drain.start(file);
    ready("lockstep",ntohs(bound.sin_port));
    const bool memory_ok=!cfg.mlock || rt::lock_memory(8u<<20,64u<<20).ok;
    const bool cpu_ok=cfg.cpu<0 || rt::pin_to_cpu(cfg.cpu).ok;
    const bool fifo_ok=cfg.fifo_prio<=0 || rt::set_fifo_priority(cfg.fifo_prio).ok;
    const bool rt_ok=memory_ok && cpu_ok && fifo_ok;
    stats::LoopStats stats(2000000);
    Session session(cfg.auto_arm);
    bool connected=false;
    int receive_errno=0;
    guard::set_mode(cfg.alloc_guard);
    while (rt_ok && !stop_requested.load(std::memory_order_relaxed)) {
        net::Datagram packet{};
        const auto n=net::recv_blocking(fd,packet,net::Wait::Synchronization);
        if (n<0) {
            receive_errno=errno;
            if (errno==EINTR && !stop_requested.load(std::memory_order_relaxed)) continue;
            session.stop(stop_requested.load()?episode::Reason::SIGNAL:episode::Reason::PEER_LOST);
            break;
        }
        if (!connected) {
            if (net::connect_udp(fd,packet.source)<0) {
                receive_errno=errno; session.stop(episode::Reason::PEER_LOST); break;
            }
            connected=true;
        }
        guard::Cycle cycle;
        const auto kind=session.receive(packet);
        if (kind==Disposition::Fatal) break;
        if (kind==Disposition::Discard) continue;
        const bool original=kind==Disposition::New;
        session.begin_send(original);
        const auto sent=net::send_frame(fd,session.reply().data(),session.reply().size());
        session.finish_send(original,sent==static_cast<ssize_t>(session.reply().size()));
        if (original) {
            auto record=session.record(); record.drops=ring->drops();
            session.note_record(ring->try_push(record));
            if (session.reason()!=episode::Reason::NONE) break;
        }
    }
    if (stop_requested.load()) session.stop(episode::Reason::SIGNAL);
    if (!rt_ok) session.stop(episode::Reason::INTERNAL);
    guard::set_mode(guard::Mode::Off);
    drain.stop(); net::close_udp(fd);
    utsname un{}; ::uname(&un);
    const auto seen=session.sim_reason_seen();
    std::ostringstream extra;
    extra << ",\n\"total_cycles\":" << session.up.logical_received << ",\"warmup\":0,"
          << "\"episode\":{\"state\":3,\"vehicle_reason\":" << static_cast<unsigned>(session.reason())
          << ",\"vehicle_reason_name\":\"" << reason_name(session.reason()) << "\""
          << ",\"reason_tick\":" << session.reason_tick() << ",\"tick_base\":0,\"sim_reason_seen\":"
          << (seen?std::to_string(*seen):"null") << ",\"sim_reason_seen_name\":"
          << (seen?std::string("\"")+sim_name(*seen)+"\"":"null")
          << "},\"link\":" << counters(session.up)
          << ",\"actuator\":" << counters(session.down) << ",\"link_recorded\":null,"
          << "\"events\":{\"episode_transitions\":" << session.events.episode_transitions
          << ",\"pid_calls\":" << session.events.pid_calls
          << ",\"record_attempts\":" << session.events.record_attempts
          << ",\"records_pushed\":" << session.events.records_pushed
          << ",\"ring_drops\":" << session.events.ring_drops
          << ",\"record_pending\":" << session.events.record_pending << "},"
          << "\"receive_errno\":" << receive_errno << ",\"consts\":\"0xe77201ca\","
          << "\"identifiers\":{\"model\":\"pitch-frozen-flight-v1\",\"controller\":\"pid-v1\","
          << "\"actuator\":\"ideal-angle-v1\",\"sensor\":\"ideal-v1\","
          << "\"environment\":\"frozen-flight-v1\",\"scenario_schema\":\"tvc-scenario-v1\"}";
    const auto yes=[](bool b){return b?"true":"false";};
    const auto applied=std::string("{\"mlock\":")+yes(memory_ok)+",\"cpu\":"+yes(cpu_ok)+
        ",\"fifo\":"+yes(fifo_ok)+",\"link\":true,\"telemetry\":true}";
    const auto env=std::string("{\"machine\":\"")+un.machine+"\",\"kernel\":\""+un.release+"\"}";
    const auto telemetry=std::string("{\"records\":")+std::to_string(drain.records_written())+
        ",\"dropped\":"+std::to_string(ring->drops())+",\"bytes\":"+
        std::to_string(32+drain.bytes_written())+"}";
    const bool wrote=stats.write_json(prefix+".summary.json",cfg.label,"record:control mode:lockstep",
        applied,env,0,telemetry,"lockstep",false,extra.str());
    if (!wrote || drain.write_failed()) return 4;
    if (stop_requested.load()) return 3;
    if (!rt_ok) return 2;
    if (session.integrity_failed()) return 6;
    if (session.reason()==episode::Reason::PEER_LOST || session.reason()==episode::Reason::INTERNAL ||
        session.reason()==episode::Reason::NONE || ring->drops()!=0 || session.down.original_tx_fail!=0) return 5;
    return 0;
}
}  // namespace lockstep

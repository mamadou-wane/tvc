#include "../../src/lockstep.hpp"
#include "../../src/wire.hpp"
#include "../../src/alloc_guard.hpp"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>

#define CHECK(x) do { if (!(x)) { std::fprintf(stderr,"FAIL %s:%d: %s\n",__FILE__,__LINE__,#x); std::exit(1); } } while (0)
static unsigned episode_calls=0, pid_calls=0;
extern "C" episode::Transition real_episode(const episode::State&, const episode::Inputs&) asm("__real__ZN7episode4stepERKNS_5StateERKNS_6InputsE");
extern "C" episode::Transition wrapped_episode(const episode::State&, const episode::Inputs&) asm("__wrap__ZN7episode4stepERKNS_5StateERKNS_6InputsE");
extern "C" episode::Transition wrapped_episode(const episode::State& s, const episode::Inputs& i) { ++episode_calls; return real_episode(s,i); }
extern "C" double real_pid(control::State&,const Observation&) asm("__real__ZN7control4stepERNS_5StateERK11Observation");
extern "C" double wrapped_pid(control::State&,const Observation&) asm("__wrap__ZN7control4stepERNS_5StateERK11Observation");
extern "C" double wrapped_pid(control::State& s,const Observation& o) { ++pid_calls; return real_pid(s,o); }

net::Datagram packet(std::uint64_t tick, double theta=0, double omega=0,
                     std::uint32_t flags=1, std::uint32_t cmd=0, std::uint32_t reason=0) {
    net::Datagram p{}; unsigned char payload[44];
    CHECK(telem::payload::encode_sensor(payload,44,tick,0,theta,omega,flags,cmd,reason));
    p.size=telem::encode_frame(4,static_cast<std::uint32_t>(tick),payload,44,p.bytes.data());
    return p;
}
void sent(lockstep::Session& s, bool original, bool success) {
    s.begin_send(original); s.finish_send(original,success);
    if (original) s.note_record(true);
}
int main() {
    using K=lockstep::Disposition;
    lockstep::Session s(true);
    auto p=packet(0,0.015625);
    guard::set_mode(guard::Mode::Abort);
    { guard::Cycle scope;
      CHECK(s.receive(p)==K::New);
      sent(s,true,true);
      CHECK(episode_calls==1 && pid_calls==1);
      CHECK(s.events.episode_transitions==1 && s.events.pid_calls==1);
      CHECK(s.events.record_attempts==1 && s.events.records_pushed==1 && s.events.record_pending==0);
      CHECK(s.record().tick==0 && s.record().sensor_tick==0 && s.record().rx_count==1);
      CHECK(wire::get_u64_le(s.reply().data(),10)==0);
      const auto record=s.record(); const auto reply=s.reply();
      CHECK(s.receive(p)==K::Cached); sent(s,false,true);
      CHECK(episode_calls==1 && pid_calls==1 && s.reply()==reply);
      CHECK(std::memcmp(&record,&s.record(),sizeof record)==0);
      CHECK(s.up.received_raw==2 && s.up.discarded_duplicate==1);
      CHECK(s.down.generated==1 && s.down.transmitted==2 && s.down.additional_copies==1);
      auto conflict=packet(0,0.03125);
      CHECK(s.receive(conflict)==K::Discard && s.integrity_failed());
      CHECK(s.receive(packet(1,0,0,0))==K::New); sent(s,true,false);
      CHECK(s.record().rx_count==1 && s.record().discarded_old==0);
      CHECK(s.record().staleness==1 && (s.record().flags&8));
      CHECK(!(s.record().flags&2)); const auto failed_record=s.record();
      CHECK(s.receive(packet(1,0,0,0))==K::Cached); sent(s,false,true);
      CHECK(std::memcmp(&failed_record,&s.record(),sizeof failed_record)==0);
      CHECK(s.down.original_tx_fail==1 && s.down.first_transmitted==2);
      CHECK(s.receive(packet(0))==K::Discard);
      CHECK(episode_calls==2 && pid_calls==1);
      CHECK(s.receive(packet(2,std::numeric_limits<double>::quiet_NaN()))==K::New);
      CHECK(s.record().discarded_other==1 && (s.record().flags&128));
      CHECK(s.up.sample_nonfinite==1 && s.up.admitted==1);
      CHECK(s.receive(packet(4))==K::Fatal && s.reason()==episode::Reason::INTERNAL);
    }
    guard::set_mode(guard::Mode::Off);
    CHECK(episode_calls==3 && pid_calls==1);
    CHECK(s.events.episode_transitions==3 && s.events.pid_calls==1);
    CHECK(s.events.record_attempts==2 && s.events.record_pending==1);
    s.note_record(false);
    CHECK(s.events.record_pending==0 && s.events.ring_drops==1);
    lockstep::Session zero(true);
    const auto before_zero=pid_calls;
    CHECK(zero.receive(packet(0))==K::New);
    CHECK(zero.events.pid_calls==1 && pid_calls==before_zero+1);
    lockstep::Session first(false);
    CHECK(first.receive(packet(1))==K::Fatal && first.reason()==episode::Reason::PEER_LOST);
    lockstep::Session loss(true);
    for(unsigned i=0;i<21;++i) {
        CHECK(loss.receive(packet(i,0,0,i==20?2:0,0,i==20?1:0))==K::New);
        sent(loss,true,true);
    }
    CHECK(loss.reason()==episode::Reason::SENSOR_LOST && loss.reason_tick()==20);
    CHECK(loss.sim_reason_seen()==1 && loss.record().staleness==21);
    CHECK(loss.up.sample_invalid==21 && loss.up.admitted==0);
    CHECK(lockstep::constants_digest()==0xe77201ca);

    lockstep::Session commands(false);
    for (unsigned tick=0;tick<=70;++tick) {
        auto input=packet(tick);
        if (tick==0 || tick==50) input=packet(tick,0,0,5|(1u<<8),1);
        if (tick==60) input=packet(tick,0,0,5|(2u<<8),2);
        if (tick==70) input=packet(tick,0,0,5|(3u<<8),3);
        CHECK(commands.receive(input)==K::New); sent(commands,true,true);
        if (tick==50) {
            CHECK(commands.acks().count==2);
            CHECK(commands.acks().values[0].status==episode::AckStatus::REJECTED_IDENTITY);
            CHECK(commands.acks().values[1].status==episode::AckStatus::APPLIED);
            CHECK(commands.record().ack_cmd_seq==1 && commands.record().ack_status==1);
            CHECK((commands.record().flags&68)==68 && commands.reply()[53]==0x81);
        }
        if (tick==70) {
            CHECK(commands.acks().count==2);
            CHECK(commands.acks().values[0].status==episode::AckStatus::QUEUED);
            CHECK(commands.acks().values[1].status==episode::AckStatus::PREEMPTED);
            CHECK(commands.record().ack_cmd_seq==3 && commands.record().ack_status==0);
            CHECK((commands.record().flags&68)==64 && commands.reply()[53]==0x80);
        }
    }

    // Real episode events cross the same projection boundary used by receive().
    auto ep=episode::initial(false);
    ep.pending=episode::Command{1,1,50}; ep.last_accepted=ep.pending;
    episode::Inputs in{50,Observation{50,0,0,true},true,0,ep.pending,false,{},{}};
    auto t=episode::step(ep,in);
    CHECK(t.acks.count==2 && t.acks.values[0].status==episode::AckStatus::DUPLICATE);
    CHECK(t.acks.values[1].status==episode::AckStatus::APPLIED);
    auto selected=lockstep::project_ack(t.acks);
    CHECK(selected.selected==1 && selected.applied);
    telem::ControlRecord projected{};
    auto ack_byte=lockstep::apply_acks(t.acks,projected);
    CHECK(ack_byte==0x81 && projected.ack_cmd_seq==1 && projected.ack_status==1);
    CHECK((projected.flags & 68)==68);
    CHECK(t.acks.values[0].state==episode::Mode::INIT && t.acks.values[1].state==episode::Mode::ARMED);
    ep=t.state; ep.pending=episode::Command{2,2,100}; ep.last_accepted=ep.pending;
    in.command=episode::Command{3,3,50};
    t=episode::step(ep,in); selected=lockstep::project_ack(t.acks);
    CHECK(t.acks.count==2 && selected.selected==0 && selected.applied);
    CHECK(t.acks.values[0].state==episode::Mode::TERMINATED);
    CHECK(t.acks.values[1].status==episode::AckStatus::PREEMPTED && t.acks.values[1].state==episode::Mode::ARMED);
    ack_byte=lockstep::apply_acks(t.acks,projected);
    CHECK(ack_byte==0x81 && projected.ack_cmd_seq==3 && projected.ack_status==1);
    CHECK((projected.flags & 68)==68);
    CHECK(lockstep::apply_acks({},projected)==0);
    CHECK(projected.ack_cmd_seq==0 && projected.ack_status==0 && !(projected.flags&68));
    CHECK(lockstep::project_ack({}).selected==-1);
    std::puts("lockstep_tests: real call counts, identity, admission, sends and complete ACK projection passed");
}

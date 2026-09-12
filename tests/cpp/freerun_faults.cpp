// Linked into a test executable only; production has no fault-control environment.
#include "../../src/episode.hpp"
#include "../../src/loop_stats.hpp"
#include "../../src/wire.hpp"
#include <array>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

namespace {
const char* proof_path = std::getenv("TVC_TEST_PROOF");
const char* fail_value = std::getenv("TVC_TEST_FAIL_ACTUATOR_TICK");
const auto fail_tick = fail_value ? std::strtoull(fail_value, nullptr, 10) : UINT64_MAX;
const bool fail_terminal = std::getenv("TVC_TEST_FAIL_TERMINAL_ALL") != nullptr;
const bool drop_terminal = std::getenv("TVC_TEST_DROP_TERMINAL_ALL") != nullptr;
const bool stall = std::getenv("TVC_TEST_STALL") != nullptr;
const bool fail_summary = std::getenv("TVC_TEST_FAIL_SUMMARY_CLOSE") != nullptr;
const bool remove_summary = std::getenv("TVC_TEST_REMOVE_SUMMARY") != nullptr;
unsigned episodes{}, pids{}, batches{}, records{}, sends{}, terminal_sends{}, sleeps{};
bool failed{}, changed{};
std::array<unsigned char, 62> terminal_bytes{};
struct Proof {
    ~Proof() {
        if (!proof_path) return;
        FILE* f = std::fopen(proof_path, "w");
        if (!f) return;
        std::fprintf(f, "{\"episodes\":%u,\"pids\":%u,\"batches\":%u,\"histograms\":%u,"
            "\"sends\":%u,\"terminal_sends\":%u,\"terminal_bytes_changed\":%s}\n",
            episodes, pids, batches, records, sends, terminal_sends, changed ? "true" : "false");
        std::fclose(f);
    }
} proof;
}

extern "C" episode::Transition real_episode(const episode::State&, const episode::Inputs&) asm("__real__ZN7episode4stepERKNS_5StateERKNS_6InputsE");
extern "C" episode::Transition wrapped_episode(const episode::State&, const episode::Inputs&) asm("__wrap__ZN7episode4stepERKNS_5StateERKNS_6InputsE");
extern "C" episode::Transition wrapped_episode(const episode::State& s, const episode::Inputs& i) { ++episodes; return real_episode(s,i); }
extern "C" double real_pid(control::State&,const Observation&) asm("__real__ZN7control4stepERNS_5StateERK11Observation");
extern "C" double wrapped_pid(control::State&,const Observation&) asm("__wrap__ZN7control4stepERNS_5StateERK11Observation");
extern "C" double wrapped_pid(control::State& s,const Observation& o) { ++pids; return real_pid(s,o); }
extern "C" void real_record(stats::LoopStats*,std::int64_t,std::int64_t,std::int64_t) asm("__real__ZN5stats9LoopStats6recordElll");
extern "C" void wrapped_record(stats::LoopStats*,std::int64_t,std::int64_t,std::int64_t) asm("__wrap__ZN5stats9LoopStats6recordElll");
extern "C" void wrapped_record(stats::LoopStats* s,std::int64_t a,std::int64_t b,std::int64_t c) { ++records; real_record(s,a,b,c); }
extern "C" int __real_recvmmsg(int,mmsghdr*,unsigned,int,timespec*);
extern "C" int __wrap_recvmmsg(int fd,mmsghdr* messages,unsigned count,int flags,timespec* timeout) {
    if (count != 8 || flags != MSG_DONTWAIT || timeout) std::abort();
    ++batches;
    return __real_recvmmsg(fd,messages,count,flags,timeout);
}
extern "C" ssize_t __real_send(int,const void*,std::size_t,int);
extern "C" ssize_t __wrap_send(int fd,const void* bytes,std::size_t count,int flags) {
    ++sends;
    const auto* p = static_cast<const unsigned char*>(bytes);
    if (count == 62 && p[3] == 5) {
        if (flags != MSG_DONTWAIT) std::abort();
        if (p[50] == 3) {
            if (terminal_sends && std::memcmp(terminal_bytes.data(),p,count)) changed = true;
            std::memcpy(terminal_bytes.data(),p,count); ++terminal_sends;
            if (fail_terminal) { errno=EAGAIN; return -1; }
            if (drop_terminal) return static_cast<ssize_t>(count);
        }
        if (!failed && wire::get_u64_le(p,10) == fail_tick) { failed=true; errno=EAGAIN; return -1; }
    }
    return __real_send(fd,bytes,count,flags);
}
extern "C" int __real_clock_nanosleep(clockid_t,int,const timespec*,timespec*);
extern "C" int __wrap_clock_nanosleep(clockid_t clock,int flags,const timespec* deadline,timespec* remainder) {
    if (flags == TIMER_ABSTIME) {
        if (clock != CLOCK_MONOTONIC) std::abort();
        if (stall && sleeps++ == 1) { timespec pause{0,30000000}; ::nanosleep(&pause,nullptr); }
    }
    return __real_clock_nanosleep(clock,flags,deadline,remainder);
}
extern "C" int __real_fclose(FILE*);
extern "C" int __wrap_fclose(FILE* file) {
    char link[64], path[4096]{};
    std::snprintf(link,sizeof link,"/proc/self/fd/%d",::fileno(file));
    const bool summary = ::readlink(link,path,sizeof path-1)>0 && std::strstr(path,".summary.json");
    const bool refuse = fail_summary && summary;
    const int result=__real_fclose(file);
    if (remove_summary && summary) ::unlink(path);
    if (refuse) { errno=EIO;return EOF; }
    return result;
}

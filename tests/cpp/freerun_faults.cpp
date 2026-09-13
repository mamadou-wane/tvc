// Linked into a test executable only; production has no fault-control environment.
#include "../../src/episode.hpp"
#include "../../src/loop_stats.hpp"
#include "../../src/wire.hpp"
#include <array>
#include <netdb.h>
#include <fcntl.h>
#include <thread>
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
const bool fail_timing = std::getenv("TVC_TEST_FAIL_TIMING_CLOSE") != nullptr;
const bool remove_summary = std::getenv("TVC_TEST_REMOVE_SUMMARY") != nullptr;
const char* ready_value = std::getenv("TVC_TEST_READY_FD");
const char* release_value = std::getenv("TVC_TEST_RELEASE_FD");
const char* gate_value = std::getenv("TVC_TEST_GATE_CYCLE");
const unsigned gate_cycle = gate_value ? std::strtoul(gate_value, nullptr, 10) : 1;
const int ready_fd = ready_value ? std::atoi(ready_value) : -1;
const int release_fd = release_value ? std::atoi(release_value) : -1;
const auto control_thread = std::this_thread::get_id();
const char* ground_fault = std::getenv("TVC_TEST_GROUND_SEND");
const char* setup_fault = std::getenv("TVC_TEST_GROUND_SETUP");
const bool ready_order = std::getenv("TVC_TEST_READY_ORDER") != nullptr;
unsigned ground_sends{}, ground_closes{}, socket_calls{}, resolver_calls{}, ready_calls{}, mitigation_calls{};
int ground_fd = -1;
bool ground_connected{};
unsigned episodes{}, pids{}, batches{}, records{}, sends{}, terminal_sends{}, sleeps{};
bool failed{}, changed{};
std::array<unsigned char, 62> terminal_bytes{};
struct Proof {
    ~Proof() {
        if (!proof_path) return;
        FILE* f = std::fopen(proof_path, "w");
        if (!f) return;
        std::fprintf(f, "{\"episodes\":%u,\"pids\":%u,\"batches\":%u,\"histograms\":%u,"
            "\"sends\":%u,\"terminal_sends\":%u,\"terminal_bytes_changed\":%s,"
            "\"ground_sends\":%u,\"ground_closes\":%u,\"socket_calls\":%u,"
            "\"resolver_calls\":%u,\"ready_calls\":%u,\"mitigation_calls\":%u}\n",
            episodes, pids, batches, records, sends, terminal_sends, changed ? "true" : "false",
            ground_sends, ground_closes, socket_calls, resolver_calls, ready_calls, mitigation_calls);
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
    const auto* p = static_cast<const unsigned char*>(bytes);
    if (count == 142 && p[3] == 6) {
        if (std::this_thread::get_id() == control_thread || fd != ground_fd || flags != MSG_DONTWAIT) std::abort();
        ++ground_sends;
        const bool terminal = p[134] == 3;
        if (ground_fault && (!std::strcmp(ground_fault,"all") ||
            (!std::strcmp(ground_fault,"terminal") ? terminal : wire::get_u32_le(p,6) == 1))) {
            if (!std::strcmp(ground_fault,"short")) return 141;
            errno = !std::strcmp(ground_fault,"eintr") ? EINTR :
                    !std::strcmp(ground_fault,"refused") ? ECONNREFUSED : EAGAIN;
            return -1;
        }
    } else if (count == 62 && p[3] == 5) {
        if (std::this_thread::get_id() != control_thread || fd == ground_fd) std::abort();
        ++sends;
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
        const auto cycle = sleeps++;
        if (cycle == gate_cycle && ready_fd >= 0 && release_fd >= 0) {
            char value = 'g';
            if (::write(ready_fd, &value, 1) != 1 || ::read(release_fd, &value, 1) != 1) std::abort();
        }
        if (stall && cycle == 1) { timespec pause{0,30000000}; ::nanosleep(&pause,nullptr); }
    }
    return __real_clock_nanosleep(clock,flags,deadline,remainder);
}
extern "C" int __real_fclose(FILE*);
extern "C" int __wrap_fclose(FILE* file) {
    char link[64], path[4096]{};
    std::snprintf(link,sizeof link,"/proc/self/fd/%d",::fileno(file));
    const bool summary = ::readlink(link,path,sizeof path-1)>0 && std::strstr(path,".summary.json");
    const bool refuse = (fail_summary && summary) || (fail_timing && std::strstr(path,".jitter.csv"));
    const int result=__real_fclose(file);
    if (remove_summary && summary) ::unlink(path);
    if (refuse) { errno=EIO;return EOF; }
    return result;
}

extern "C" int __real_getaddrinfo(const char*,const char*,const addrinfo*,addrinfo**);
extern "C" int __wrap_getaddrinfo(const char* host,const char* service,const addrinfo* hints,addrinfo** out) {
    if (std::this_thread::get_id() != control_thread || ready_calls || hints->ai_family != AF_INET) std::abort();
    ++resolver_calls;
    if (setup_fault && !std::strcmp(setup_fault,"resolve")) return EAI_NONAME;
    return __real_getaddrinfo(host,service,hints,out);
}
extern "C" int __real_socket(int,int,int);
extern "C" int __wrap_socket(int domain,int type,int protocol) {
    ++socket_calls;
    if (socket_calls == 2 && setup_fault && !std::strcmp(setup_fault,"socket")) { errno=EMFILE; return -1; }
    int fd=__real_socket(domain,type,protocol);
    if (socket_calls == 2) {
        ground_fd=fd;
        if (fd>=0 && !(::fcntl(fd,F_GETFL)&O_NONBLOCK)) std::abort();
    }
    return fd;
}
extern "C" int __real_connect(int,const sockaddr*,socklen_t);
extern "C" int __wrap_connect(int fd,const sockaddr* addr,socklen_t len) {
    if (fd == ground_fd && setup_fault && !std::strcmp(setup_fault,"connect")) { errno=ECONNREFUSED; return -1; }
    int result=__real_connect(fd,addr,len);
    if (fd==ground_fd && result==0) ground_connected=true;
    return result;
}
extern "C" int __real_close(int);
extern "C" int __wrap_close(int fd) {
    if (fd==ground_fd && fd>=0) {
        if (ground_connected && std::this_thread::get_id()==control_thread) std::abort();
        ++ground_closes;
    }
    return __real_close(fd);
}
extern "C" void real_ready(const char*,unsigned) asm("__real__ZN8lockstep5readyEPKcj");
extern "C" void wrapped_ready(const char*,unsigned) asm("__wrap__ZN8lockstep5readyEPKcj");
extern "C" void wrapped_ready(const char* mode,unsigned port) {
    if (ground_fd>=0 && !ground_connected) std::abort();
    ++ready_calls;
    real_ready(mode,port);
}
extern "C" int __real_mlockall(int);
extern "C" int __wrap_mlockall(int flags) {
    if (ready_order) {
        if (ready_calls != 1) std::abort();
        ++mitigation_calls;
        errno=EPERM; return -1;
    }
    return __real_mlockall(flags);
}

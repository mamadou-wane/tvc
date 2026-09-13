#include "../../src/telemetry.hpp"
#include "../../src/wire.hpp"
#include <atomic>
#include <cerrno>
#include <cstdlib>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <memory>
#include <new>
#include <thread>
#include <unistd.h>
#include <vector>

#define CHECK(x) do { if (!(x)) { std::fprintf(stderr,"FAIL %s:%d: %s\n",__FILE__,__LINE__,#x); std::abort(); } } while (0)

namespace {
const auto producer = std::this_thread::get_id();
std::vector<unsigned char> transmitted;
std::atomic<bool> fail_thread_allocation{false};
int last_socket = -1;
bool fail_write{}, fail_flush{}, fail_close{}, pause_idle{};
std::atomic<bool> idle{false}, release_idle{false};
}

void* operator new(std::size_t size) {
    if (fail_thread_allocation.exchange(false)) throw std::bad_alloc();
    if (void* p=std::malloc(size ? size : 1)) return p;
    throw std::bad_alloc();
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p,std::size_t) noexcept { std::free(p); }
extern "C" int __real_socket(int,int,int);
extern "C" int __wrap_socket(int domain,int type,int protocol) {
    last_socket=__real_socket(domain,type,protocol);
    return last_socket;
}

extern "C" ssize_t __wrap_send(int fd,const void* bytes,std::size_t len,int flags) {
    CHECK(std::this_thread::get_id()!=producer);
    CHECK(flags==MSG_DONTWAIT && (::fcntl(fd,F_GETFL)&O_NONBLOCK));
    CHECK(len==142 && static_cast<const unsigned char*>(bytes)[3]==6);
    const auto* p=static_cast<const unsigned char*>(bytes);
    transmitted.insert(transmitted.end(),p,p+len);
    return len;
}
extern "C" std::size_t __real_fwrite(const void*,std::size_t,std::size_t,FILE*);
extern "C" std::size_t __wrap_fwrite(const void* p,std::size_t size,std::size_t count,FILE* f) {
    if (fail_write) { errno=EIO; return 0; }
    return __real_fwrite(p,size,count,f);
}
extern "C" int __real_fflush(FILE*);
extern "C" int __wrap_fflush(FILE* f) {
    const auto result=__real_fflush(f);
    if (fail_flush) { errno=EIO; return EOF; }
    return result;
}
extern "C" int __real_fclose(FILE*);
extern "C" int __wrap_fclose(FILE* f) {
    const auto result=__real_fclose(f);
    if (fail_close) { errno=EIO; return EOF; }
    return result;
}
extern "C" int __real_clock_nanosleep(clockid_t,int,const timespec*,timespec*);
extern "C" int __wrap_clock_nanosleep(clockid_t c,int flags,const timespec* req,timespec* rem) {
    if (pause_idle && !release_idle.load(std::memory_order_acquire)) {
        idle.store(true,std::memory_order_release);
        while (!release_idle.load(std::memory_order_acquire)) std::this_thread::yield();
    }
    return __real_clock_nanosleep(c,flags,req,rem);
}

void run(unsigned count,bool late=false,bool invalid=false) {
    auto ring=std::make_unique<telem::SpscRing<telem::ControlRecord>>();
    telem::Drain<telem::ControlRecord> drain(*ring);
    FILE* file=std::tmpfile(); CHECK(file);
    const int reader=::dup(::fileno(file)); CHECK(reader>=0);
    sockaddr_in peer{};peer.sin_family=AF_INET;peer.sin_addr.s_addr=htonl(INADDR_LOOPBACK);peer.sin_port=htons(9);
    transmitted.clear();idle=false;release_idle=false;pause_idle=late;
    if (late) {
        CHECK(drain.start(file,peer));
        while (!idle.load(std::memory_order_acquire)) std::this_thread::yield();
    }
    for (unsigned i=0;i<count;++i) {
        telem::ControlRecord r{};r.tick=i;r.sensor_tick=i;r.theta=0.25;r.cmd=-0.5;
        r.state=i+1==count?3:2;r.rx_count=invalid?10:1;
        CHECK(ring->try_push(r));
    }
    if (!late) CHECK(drain.start(file,peer));
    release_idle.store(true,std::memory_order_release);
    drain.stop();
    const auto expected=invalid?0:count;
    CHECK(drain.ground().attempted==expected && drain.ground().sent==expected);
    CHECK(drain.ground().send_errors==0 && drain.ground().last_errno==0);
    CHECK(transmitted.size()==142u*expected);
    CHECK(drain.write_failed()==(fail_write||fail_flush||fail_close||invalid));
    CHECK(drain.records_written()==(fail_write?0:expected));
    CHECK(::lseek(reader,0,SEEK_SET)==0);
    std::vector<unsigned char> stored(142u*expected);
    const auto n=::read(reader,stored.data(),stored.size());
    CHECK(n==static_cast<ssize_t>(fail_write?0:stored.size()));
    if (!fail_write) CHECK(stored==transmitted);
    ::close(reader);
    for (unsigned i=0;i<expected;++i) {
        const auto* p=transmitted.data()+142u*i;
        CHECK(wire::get_u32_le(p,6)==i && wire::get_u64_le(p,10)==i);
        CHECK(p[134]==(i+1==count?3:2));
    }
}

void allocation_failure() {
    auto ring=std::make_unique<telem::SpscRing<telem::ControlRecord>>();
    telem::Drain<telem::ControlRecord> drain(*ring);
    FILE* file=std::tmpfile(); CHECK(file);
    sockaddr_in peer{};peer.sin_family=AF_INET;peer.sin_addr.s_addr=htonl(INADDR_LOOPBACK);peer.sin_port=htons(9);
    fail_thread_allocation=true;
    bool started=false, threw=false;
    try { started=drain.start(file,peer); }
    catch (const std::bad_alloc&) { threw=true; }
    CHECK(!threw && !started && errno==ENOMEM);
    CHECK(::fcntl(last_socket,F_GETFD)==-1 && errno==EBADF);
    CHECK(std::fputs("caller still owns the file",file)>=0);
    CHECK(std::fclose(file)==0);
}

template<class Record>
void file_only_close_failure() {
    auto ring=std::make_unique<telem::SpscRing<Record>>();
    telem::Drain<Record> drain(*ring);
    FILE* file=std::tmpfile(); CHECK(file);
    CHECK(ring->try_push(Record{}));
    transmitted.clear();
    fail_close=true;
    drain.start(file);
    drain.stop();
    fail_close=false;
    CHECK(!drain.write_failed() && drain.records_written()==1);
    CHECK(transmitted.empty() && drain.ground().attempted==0);
}

int main() {
    file_only_close_failure<telem::Record>();
    file_only_close_failure<telem::ControlRecord>();
    allocation_failure();
    for (unsigned n : {0u,1u,512u,513u,4096u}) run(n);
    for (unsigned i=0;i<20;++i) run(1,true);
    run(1,false,true);
    fail_write=true;run(2);fail_write=false;
    fail_flush=true;run(2);fail_flush=false;
    fail_close=true;run(2);fail_close=false;
    std::puts("drain_tests: bytes, batch boundaries, late final push and independent file failures passed");
}

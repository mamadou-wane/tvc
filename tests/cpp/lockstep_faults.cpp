// Link-only fault controls; no test switch enters the production executable.
#include "../../src/wire.hpp"
#include <atomic>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <sys/socket.h>
#include <thread>

namespace {
const char* fail_value=std::getenv("TVC_TEST_FAIL_ACTUATOR_TICK");
const auto fail_tick=fail_value?std::strtoull(fail_value,nullptr,10):std::numeric_limits<unsigned long long>::max();
const bool stall=std::getenv("TVC_TEST_STALL_DRAIN")!=nullptr;
std::atomic<bool> failed{false}, terminal_sent{false};
}
extern "C" ssize_t __real_send(int,const void*,std::size_t,int);
extern "C" ssize_t __wrap_send(int fd,const void* data,std::size_t size,int flags) {
    const auto* p=static_cast<const unsigned char*>(data);
    if (size==62 && p[3]==5) {
        if (p[50]==3) terminal_sent.store(true,std::memory_order_release);
        if (wire::get_u64_le(p,10)==fail_tick && !failed.exchange(true)) { errno=EAGAIN;return -1; }
    }
    return __real_send(fd,data,size,flags);
}
extern "C" std::size_t __real_fwrite(const void*,std::size_t,std::size_t,FILE*);
extern "C" std::size_t __wrap_fwrite(const void* data,std::size_t size,std::size_t count,FILE* file) {
    if (stall && size*count==142) {
        while (!terminal_sent.load(std::memory_order_acquire)) std::this_thread::yield();
    }
    return __real_fwrite(data,size,count,file);
}

#include <cstring>
#include <unistd.h>
namespace { const bool bad_summary=std::getenv("TVC_TEST_BAD_SUMMARY")!=nullptr; }
extern "C" int __real_fclose(FILE*);
extern "C" int __wrap_fclose(FILE* file) {
    if (bad_summary) {
        char link[64],path[4096]{};
        std::snprintf(link,sizeof link,"/proc/self/fd/%d",::fileno(file));
        if (::readlink(link,path,sizeof path-1)>0 && std::strstr(path,".summary.json")) {
            const int ignored=::ftruncate(::fileno(file),1); (void)ignored;
        }
    }
    return __real_fclose(file);
}

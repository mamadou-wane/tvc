#include "rt_setup.hpp"

#include <alloca.h>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <malloc.h>
#include <sched.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/time.h>
#include <unistd.h>
#include <vector>

namespace {

std::string errno_str(const char* what) {
    return std::string(what) + ": " + std::strerror(errno);
}

// Touch a stack region in one live frame. alloca plus an asm barrier so the
// optimizer can neither elide the touch nor turn this into anything else.
[[gnu::noinline]] void prefault_stack(std::size_t bytes) {
    if (bytes == 0) return;
    unsigned char* p = static_cast<unsigned char*>(::alloca(bytes));
    std::memset(p, 0, bytes);
    __asm__ __volatile__("" ::"r"(p) : "memory");
}

std::size_t stack_budget(std::size_t requested) {
    rlimit rl{};
    if (::getrlimit(RLIMIT_STACK, &rl) != 0 || rl.rlim_cur == RLIM_INFINITY)
        return requested;
    // Half the limit: main() and callees already own part of the stack.
    const std::size_t cap = static_cast<std::size_t>(rl.rlim_cur) / 2;
    return requested < cap ? requested : cap;
}

}  // namespace

namespace rt {

Result lock_memory(std::size_t stack_bytes, std::size_t heap_bytes) {
    Result r;
    if (::mlockall(MCL_CURRENT | MCL_FUTURE) != 0) {
        r.detail = errno_str("mlockall");
        return r;
    }
    const std::size_t budget = stack_budget(stack_bytes);
    prefault_stack(budget);

    // Keep freed memory in the arena instead of returning it to the kernel,
    // then warm the arena to its working size. Without these mallopt calls a
    // large warm block is served by mmap and munmapped on free (man mallopt),
    // and the "prefault" buys nothing.
    if (heap_bytes) {
        ::mallopt(M_TRIM_THRESHOLD, -1);
        ::mallopt(M_MMAP_MAX, 0);
        std::vector<unsigned char> warm(heap_bytes);
        for (std::size_t i = 0; i < heap_bytes; i += 4096) warm[i] = 1;
    }

    // Prove it: allocating and touching again should fault nearly nothing.
    rusage before{}, after{};
    ::getrusage(RUSAGE_SELF, &before);
    if (heap_bytes) {
        std::vector<unsigned char> check(heap_bytes / 2);
        for (std::size_t i = 0; i < check.size(); i += 4096) check[i] = 1;
    }
    ::getrusage(RUSAGE_SELF, &after);

    r.ok = true;
    r.detail = "prefaulted " + std::to_string(budget >> 20) + " MiB stack, " +
               std::to_string(heap_bytes >> 20) + " MiB heap; recheck minor faults: " +
               std::to_string(after.ru_minflt - before.ru_minflt);
    return r;
}

Result set_fifo_priority(int priority) {
    Result r;
    sched_param p{};
    p.sched_priority = priority;
    if (::sched_setscheduler(0, SCHED_FIFO, &p) != 0) {
        r.detail = errno_str("sched_setscheduler(SCHED_FIFO)");
        return r;
    }
    r.ok = true;
    r.detail = "SCHED_FIFO priority " + std::to_string(priority);
    return r;
}

Result pin_to_cpu(int cpu) {
    Result r;
    const long ncpu = ::sysconf(_SC_NPROCESSORS_ONLN);
    if (cpu < 0 || (ncpu > 0 && cpu >= ncpu)) {
        r.detail = "cpu " + std::to_string(cpu) + " out of range (online: " +
                   std::to_string(ncpu) + ")";
        return r;
    }
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    if (::sched_setaffinity(0, sizeof(set), &set) != 0) {
        r.detail = errno_str("sched_setaffinity");
        return r;
    }
    r.ok = true;
    r.detail = "pinned to cpu " + std::to_string(cpu);
    return r;
}

std::string describe_current() {
    std::string s;
    const int pol = ::sched_getscheduler(0);
    switch (pol) {
        case SCHED_FIFO:  s = "SCHED_FIFO";  break;
        case SCHED_RR:    s = "SCHED_RR";    break;
        case SCHED_OTHER: s = "SCHED_OTHER"; break;
        case -1:          s = "unknown";     break;
        default:          s = "policy " + std::to_string(pol);
    }
    if (pol == SCHED_FIFO || pol == SCHED_RR) {
        sched_param p{};
        if (::sched_getparam(0, &p) == 0) s += " prio " + std::to_string(p.sched_priority);
    }
    const int c = ::sched_getcpu();
    if (c >= 0) s += ", cpu " + std::to_string(c);
    return s;
}

}  // namespace rt

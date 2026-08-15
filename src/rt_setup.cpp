#include "rt_setup.hpp"

#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <sched.h>
#include <sys/mman.h>
#include <unistd.h>
#include <vector>

namespace {

std::string errno_str(const char* what) {
    return std::string(what) + ": " + std::strerror(errno);
}

// Touch every page of a stack region so the pages are resident and the guard
// page has already been grown past. Marked noinline + volatile so the compiler
// cannot decide this is dead.
[[gnu::noinline]] void prefault_stack(std::size_t bytes) {
    if (bytes == 0) return;
    volatile unsigned char buf[8192];
    std::size_t done = 0;
    while (done < bytes) {
        for (std::size_t i = 0; i < sizeof(buf); i += 4096) buf[i] = 0;
        done += sizeof(buf);
        if (done >= bytes) break;
        // Recurse rather than allocate, to keep growing the stack.
        if (bytes - done > sizeof(buf)) { prefault_stack(bytes - done); return; }
    }
}

}  // namespace

namespace rt {

Result lock_memory(std::size_t stack_bytes, std::size_t heap_bytes) {
    Result r;
    if (::mlockall(MCL_CURRENT | MCL_FUTURE) != 0) {
        r.detail = errno_str("mlockall");
        return r;
    }
    prefault_stack(stack_bytes);

    // Grow the arena to its working size and touch it, then hand it back. With
    // MCL_FUTURE and M_TRIM_THRESHOLD left alone glibc keeps the arena, so
    // later allocations during init do not fault.
    if (heap_bytes) {
        std::vector<unsigned char> warm(heap_bytes);
        for (std::size_t i = 0; i < heap_bytes; i += 4096) warm[i] = 1;
    }

    r.ok = true;
    r.detail = "MCL_CURRENT|MCL_FUTURE, stack and heap pre-faulted";
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

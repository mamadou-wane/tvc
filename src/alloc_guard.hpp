// alloc_guard.hpp: detect heap activity inside the control cycle.
//
// The hot path of a real-time loop must not touch the allocator. glibc malloc
// takes an arena lock, may fall into mmap/brk, and can page-fault; any of these
// puts an unbounded tail on your cycle time. This header makes that property
// checkable instead of aspirational: global operator new/delete are replaced,
// and every allocation that happens while a cycle is in flight is either
// counted or fatal.
//
// The flag is thread_local, so only the control thread is constrained. A drain
// thread doing I/O and formatting is free to allocate.

#pragma once
#include <cstddef>
#include <cstdint>

namespace guard {

enum class Mode : int {
    Off   = 0,  // no bookkeeping at all
    Count = 1,  // tally violations, report at exit (use this to hunt)
    Abort = 2,  // die at the first one, with a backtrace-able core
};

// Process-wide policy. Set once before the loop starts.
void set_mode(Mode m);
Mode mode();

// Per-thread violation tallies, valid in Count mode.
struct Tally {
    std::uint64_t allocs;
    std::uint64_t frees;
    std::size_t   largest;
};
Tally tally();
void  reset_tally();

// Marks a region as "inside the control cycle". Non-allocating, no syscalls,
// two integer ops on entry and exit.
class Cycle {
public:
    Cycle()  noexcept;
    ~Cycle() noexcept;
    Cycle(const Cycle&)            = delete;
    Cycle& operator=(const Cycle&) = delete;
};

// True while a Cycle object is alive on this thread.
bool in_flight() noexcept;

}  // namespace guard

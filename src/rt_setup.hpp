// rt_setup.hpp: the four privileges a real-time loop asks the kernel for.
//
// Each is independent and independently reportable, because the whole point of
// the campaign is knowing what each one is worth on its own. None of them are
// fatal on failure: running without privileges and watching the tail degrade is
// itself a useful measurement.

#pragma once
#include <string>

namespace rt {

struct Result {
    bool        ok      = false;
    std::string detail;   // why it failed, or what was applied
};

// mlockall(MCL_CURRENT|MCL_FUTURE), then pre-fault the stack and grow the heap
// arena so the loop never takes a first-touch page fault.
Result lock_memory(std::size_t stack_bytes, std::size_t heap_bytes);

// SCHED_FIFO at the given priority. 80 leaves headroom above it for kernel
// threads; 99 competes with them and can wedge the machine.
Result set_fifo_priority(int priority);

// Pin the calling thread to one CPU. Pair with isolcpus/nohz_full on that core
// at boot for the tail to actually flatten.
Result pin_to_cpu(int cpu);

// Best-effort read of the current scheduling policy and CPU, for the report.
std::string describe_current();

}  // namespace rt

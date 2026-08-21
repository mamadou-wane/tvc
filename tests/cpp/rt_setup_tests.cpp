// tests/cpp/rt_setup_tests.cpp: stack_budget branch tests. Plain main() + CHECK.
#include "../../src/rt_setup.hpp"

#include <cstdio>
#include <cstdlib>
#include <sys/resource.h>

#define CHECK(cond) do { if (!(cond)) { \
    std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
    std::exit(1); } } while (0)

namespace {

constexpr std::size_t kMiB = 1u << 20;

bool set_soft(const rlimit& orig, rlim_t soft) {
    rlimit rl = orig;
    rl.rlim_cur = soft;
    return ::setrlimit(RLIMIT_STACK, &rl) == 0;
}

// finite-under and finite-over both run against soft = 8 MiB. Only attempt
// it when lowering (soft already >= 8 MiB) or raising within the hard limit
// is possible; skip with a note otherwise instead of failing.
void test_finite_branches(const rlimit& orig) {
    const bool can_set_8mib = orig.rlim_cur >= 8 * kMiB ||
                               orig.rlim_max == RLIM_INFINITY ||
                               orig.rlim_max >= 8 * kMiB;
    if (!can_set_8mib) {
        std::puts("rt_setup_tests: skip finite-under/finite-over, "
                   "cannot set soft stack limit to 8 MiB here");
        return;
    }
    CHECK(set_soft(orig, 8 * kMiB));
    CHECK(rt::detail::stack_budget(1 * kMiB) == 1 * kMiB);   // finite-under
    CHECK(rt::detail::stack_budget(8 * kMiB) == 4 * kMiB);   // finite-over
}

// Only meaningful when the hard limit permits an unlimited soft limit.
void test_infinity_branch(const rlimit& orig) {
    if (orig.rlim_max != RLIM_INFINITY) {
        std::puts("rt_setup_tests: skip infinity, hard stack limit is finite here");
        return;
    }
    CHECK(set_soft(orig, RLIM_INFINITY));
    CHECK(rt::detail::stack_budget(8 * kMiB) == 8 * kMiB);
}

}  // namespace

int main() {
    rlimit orig{};
    CHECK(::getrlimit(RLIMIT_STACK, &orig) == 0);

    test_finite_branches(orig);
    test_infinity_branch(orig);

    // Lowering RLIMIT_STACK does not shrink the thread's existing stack, so
    // it is safe to test in-process. Single-threaded: nothing else races the
    // rlimit; restore the original before exit.
    CHECK(::setrlimit(RLIMIT_STACK, &orig) == 0);
    std::puts("rt_setup_tests: ok");
    return 0;
}

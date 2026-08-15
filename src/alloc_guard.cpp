// alloc_guard.cpp — global operator new/delete replacement.
//
// Everything here has to be safe to call before main() and from inside the
// allocator path itself, so: no iostreams, no std::string, no locks, and the
// reporting path writes bytes straight to fd 2.

#include "alloc_guard.hpp"

#include <cstdlib>
#include <cstring>
#include <new>
#include <unistd.h>

namespace {

// Constant-initialised, so these are live before any dynamic initialisation.
// Do not give them constructors.
int             g_mode      = 0;
thread_local int      t_depth   = 0;
thread_local std::uint64_t t_allocs  = 0;
thread_local std::uint64_t t_frees   = 0;
thread_local std::size_t   t_largest = 0;

void die(const char* what, std::size_t bytes) {
    char buf[192];
    std::size_t n = 0;
    auto put = [&](const char* s) {
        while (*s && n < sizeof(buf) - 1) buf[n++] = *s++;
    };
    auto put_num = [&](std::size_t v) {
        char tmp[24];
        int  i = 0;
        if (v == 0) tmp[i++] = '0';
        while (v && i < 24) { tmp[i++] = char('0' + v % 10); v /= 10; }
        while (i-- > 0 && n < sizeof(buf) - 1) buf[n++] = tmp[i];
    };
    put("\nalloc_guard: ");
    put(what);
    put(" of ");
    put_num(bytes);
    put(" bytes inside the control cycle.\n"
        "alloc_guard: run under gdb and break on this abort to find it.\n\n");
    ssize_t ignored = ::write(2, buf, n);
    (void)ignored;
    std::abort();
}

inline void note_alloc(std::size_t bytes) {
    if (g_mode == 0 || t_depth == 0) return;
    if (g_mode == 2) die("allocation", bytes);
    ++t_allocs;
    if (bytes > t_largest) t_largest = bytes;
}

inline void note_free() {
    if (g_mode == 0 || t_depth == 0) return;
    if (g_mode == 2) die("free", 0);
    ++t_frees;
}

inline void* raw_alloc(std::size_t bytes) {
    // std::malloc(0) may return nullptr, which operator new must not do.
    void* p = std::malloc(bytes ? bytes : 1);
    return p;
}

}  // namespace

namespace guard {

void set_mode(Mode m) { g_mode = static_cast<int>(m); }
Mode mode()           { return static_cast<Mode>(g_mode); }

Tally tally() { return Tally{t_allocs, t_frees, t_largest}; }
void  reset_tally() { t_allocs = 0; t_frees = 0; t_largest = 0; }

Cycle::Cycle()  noexcept { ++t_depth; }
Cycle::~Cycle() noexcept { --t_depth; }

bool in_flight() noexcept { return t_depth > 0; }

}  // namespace guard

// ---- replaceable global allocation functions -------------------------------

void* operator new(std::size_t n) {
    note_alloc(n);
    void* p = raw_alloc(n);
    if (!p) throw std::bad_alloc();
    return p;
}
void* operator new[](std::size_t n) { return ::operator new(n); }

void* operator new(std::size_t n, const std::nothrow_t&) noexcept {
    note_alloc(n);
    return raw_alloc(n);
}
void* operator new[](std::size_t n, const std::nothrow_t& t) noexcept {
    return ::operator new(n, t);
}

void operator delete(void* p) noexcept {
    if (p) { note_free(); std::free(p); }
}
void operator delete[](void* p) noexcept { ::operator delete(p); }
void operator delete(void* p, std::size_t) noexcept { ::operator delete(p); }
void operator delete[](void* p, std::size_t) noexcept { ::operator delete(p); }
void operator delete(void* p, const std::nothrow_t&) noexcept { ::operator delete(p); }
void operator delete[](void* p, const std::nothrow_t&) noexcept { ::operator delete(p); }

// C++17 over-aligned forms. aligned_alloc requires size to be a multiple of
// alignment, so round up.
void* operator new(std::size_t n, std::align_val_t a) {
    note_alloc(n);
    const std::size_t al = static_cast<std::size_t>(a);
    const std::size_t sz = ((n ? n : 1) + al - 1) / al * al;
    void* p = std::aligned_alloc(al, sz);
    if (!p) throw std::bad_alloc();
    return p;
}
void* operator new[](std::size_t n, std::align_val_t a) { return ::operator new(n, a); }

void operator delete(void* p, std::align_val_t) noexcept {
    if (p) { note_free(); std::free(p); }
}
void operator delete[](void* p, std::align_val_t a) noexcept { ::operator delete(p, a); }
void operator delete(void* p, std::size_t, std::align_val_t a) noexcept { ::operator delete(p, a); }
void operator delete[](void* p, std::size_t, std::align_val_t a) noexcept { ::operator delete(p, a); }

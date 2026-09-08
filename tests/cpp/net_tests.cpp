// Socket tests verify kernel results and descriptor state.
#include "../../src/net.hpp"
#include "../../src/alloc_guard.hpp"

#include <array>
#include <cerrno>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <sys/time.h>
#include <unistd.h>

#define CHECK(c) do { if (!(c)) { std::fprintf(stderr, "FAIL %s:%d: %s (errno=%d)\n", __FILE__, __LINE__, #c, errno); std::exit(1); } } while (0)

namespace {
int flag_calls = 0, timeout_calls = 0;
int fail_flag_call = 0, fail_timeout_call = 0, receive_error = 0;
int expected_wait_seconds = -1, receive_calls = 0, last_socket = -1;

sockaddr_in local(std::uint16_t port = 0) {
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    a.sin_port = htons(port);
    return a;
}
void reset_faults() {
    flag_calls = timeout_calls = fail_flag_call = fail_timeout_call = receive_error = receive_calls = 0;
    expected_wait_seconds = -1;
}
void check_state(int fd, int flags, const timeval& timeout) {
    CHECK(::fcntl(fd, F_GETFL) == flags);
    timeval actual{};
    socklen_t n = sizeof actual;
    CHECK(::getsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &actual, &n) == 0);
    CHECK(actual.tv_sec == timeout.tv_sec && actual.tv_usec == timeout.tv_usec);
}
}

// Link-time injection exercises kernel error paths.
extern "C" int __real_fcntl(int, int, ...);
extern "C" int __wrap_fcntl(int fd, int cmd, ...) {
    if (cmd == F_SETFL) {
        va_list args; va_start(args, cmd); int value = va_arg(args, int); va_end(args);
        if (++flag_calls == fail_flag_call) { errno = EIO; return -1; }
        return __real_fcntl(fd, cmd, value);
    }
    return __real_fcntl(fd, cmd);
}
extern "C" int __real_setsockopt(int, int, int, const void*, socklen_t);
extern "C" int __wrap_setsockopt(int fd, int level, int option, const void* value, socklen_t n) {
    if (option == SO_RCVTIMEO && ++timeout_calls == fail_timeout_call) { errno = EIO; return -1; }
    return __real_setsockopt(fd, level, option, value, n);
}
extern "C" ssize_t __real_recvmsg(int, msghdr*, int);
extern "C" ssize_t __wrap_recvmsg(int fd, msghdr* msg, int flags) {
    ++receive_calls;
    CHECK((::fcntl(fd, F_GETFL) & O_NONBLOCK) == 0);
    timeval timeout{}; socklen_t n = sizeof timeout;
    CHECK(::getsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, &n) == 0);
    CHECK(timeout.tv_sec == expected_wait_seconds && timeout.tv_usec == 0);
    if (receive_error) { errno = receive_error; return -1; }
    return __real_recvmsg(fd, msg, flags);
}
extern "C" int __real_socket(int, int, int);
extern "C" int __wrap_socket(int domain, int type, int protocol) {
    last_socket = __real_socket(domain, type, protocol);
    return last_socket;
}

int main() {
    static_assert(net::kHotRecvFlags == MSG_DONTWAIT);
    static_assert(net::kHotSendFlags == MSG_DONTWAIT);
    static_assert(net::kBatchSize == 8 && net::kMaxFrameBytes == 512);
    sockaddr_in a{}, b{};
    int rx = net::open_udp(local(), a), tx = net::open_udp(local(), b);
    CHECK(rx >= 0 && tx >= 0 && a.sin_port != 0 && b.sin_port != 0);
    CHECK((::fcntl(rx, F_GETFL) & O_NONBLOCK) != 0);
    CHECK((::fcntl(tx, F_GETFL) & O_NONBLOCK) != 0);
    int value = 0; socklen_t size = sizeof value;
    CHECK(::getsockopt(rx, SOL_SOCKET, SO_REUSEADDR, &value, &size) == 0 && value == 0);
    CHECK(::getsockopt(rx, SOL_SOCKET, SO_RCVBUF, &value, &size) == 0 && value > 0);
    sockaddr_in unused{};
    CHECK(net::open_udp(a, unused) == -1 && errno == EADDRINUSE);
    CHECK(::fcntl(last_socket, F_GETFD) == -1 && errno == EBADF);
    CHECK(net::connect_udp(tx, a) == 0 && net::connect_udp(rx, b) == 0);
    net::Batch batch{};
    CHECK(net::recv_batch(rx, batch) == -1 && (errno == EAGAIN || errno == EWOULDBLOCK));
    for (unsigned char i = 0; i < 9; ++i) CHECK(net::send_frame(tx, &i, 1) == 1);
    CHECK(net::recv_batch(rx, batch) == 8);
    for (unsigned char i = 0; i < 8; ++i) {
        CHECK(batch[i].size == 1 && batch[i].bytes[0] == i && !batch[i].truncated());
        CHECK(batch[i].source.sin_port == b.sin_port);
    }
    CHECK(net::recv_batch(rx, batch) == 1 && batch[0].bytes[0] == 8);
    std::array<unsigned char, 513> large{}; large[0] = 0x90; large[1] = 0xeb;
    CHECK(net::send_frame(tx, large.data(), large.size()) == -1 && errno == EMSGSIZE);
    CHECK(::send(tx, large.data(), large.size(), MSG_DONTWAIT) == 513);
    CHECK(net::recv_batch(rx, batch) == 1 && batch[0].truncated() && batch[0].size == 512);
    CHECK(net::send_frame(tx, large.data(), 512) == 512);
    guard::set_mode(guard::Mode::Abort);
    { guard::Cycle cycle; CHECK(net::recv_batch(rx, batch) == 1); CHECK(net::send_frame(rx, batch[0].bytes.data(), batch[0].size) == 512); }
    guard::set_mode(guard::Mode::Off);
    CHECK(net::recv_batch(tx, batch) == 1 && batch[0].size == 512);

    const timeval saved_timeout{2, 0};
    CHECK(::setsockopt(rx, SOL_SOCKET, SO_RCVTIMEO, &saved_timeout, sizeof saved_timeout) == 0);
    const int saved_flags = ::fcntl(rx, F_GETFL);
    net::Datagram packet{};
    for (auto wait : {net::Wait::Synchronization, net::Wait::Origin}) {
        reset_faults(); expected_wait_seconds = wait == net::Wait::Origin ? 5 : 0;
        unsigned char byte = 42; CHECK(net::send_frame(tx, &byte, 1) == 1);
        CHECK(net::recv_blocking(rx, packet, wait) == 1 && packet.bytes[0] == 42);
        CHECK(receive_calls == 1); check_state(rx, saved_flags, saved_timeout);
        for (int error : {EINTR, EAGAIN, EIO}) {
            reset_faults(); expected_wait_seconds = wait == net::Wait::Origin ? 5 : 0; receive_error = error;
            CHECK(net::recv_blocking(rx, packet, wait) == -1 && errno == error);
            CHECK(receive_calls == 1); check_state(rx, saved_flags, saved_timeout);
        }
    }
    // Setup failures must restore whichever temporary change already succeeded.
    for (bool flags : {false, true}) {
        reset_faults(); if (flags) fail_flag_call = 1; else fail_timeout_call = 1;
        CHECK(net::recv_blocking(rx, packet, net::Wait::Origin) == -1 && errno == EIO);
        CHECK(receive_calls == 0); check_state(rx, saved_flags, saved_timeout);
    }
    // An empty origin receive expires through the configured timeout.
    reset_faults(); expected_wait_seconds = 5;
    CHECK(net::recv_blocking(rx, packet, net::Wait::Origin) == -1 && (errno == EAGAIN || errno == EWOULDBLOCK));
    check_state(rx, saved_flags, saved_timeout);
    reset_faults(); CHECK(net::recv_batch(rx, batch) == -1 && (errno == EAGAIN || errno == EWOULDBLOCK));
    net::close_udp(rx);
    // Restoration failure invalidates ownership even after a successful receive.
    for (bool flags : {false, true}) {
        for (bool receive_fails : {false, true}) {
            rx = net::open_udp(local(), a); CHECK(rx >= 0); CHECK(net::connect_udp(tx, a) == 0);
            unsigned char byte = 7; CHECK(net::send_frame(tx, &byte, 1) == 1);
            const int old_fd = rx;
            reset_faults(); expected_wait_seconds = 5; receive_error = receive_fails ? EINTR : 0;
            if (flags) fail_flag_call = 2; else fail_timeout_call = 2;
            CHECK(net::recv_blocking(rx, packet, net::Wait::Origin) == -1 && errno == EIO);
            CHECK(rx == -1 && ::fcntl(old_fd, F_GETFD) == -1 && errno == EBADF);
            CHECK(flag_calls == 2 && timeout_calls == 2);
        }
    }
    reset_faults(); net::close_udp(tx); CHECK(tx == -1);
    CHECK(net::send_frame(-1, large.data(), 1) == -1 && errno == EBADF);
    CHECK(net::recv_batch(-1, batch) == -1 && errno == EBADF);
    std::puts("net_tests: flags, bounded batches, bytes, truncation, allocation and blocking lifecycle passed");
}

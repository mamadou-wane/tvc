#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <netinet/in.h>
#include <sys/socket.h>

namespace net {

inline constexpr std::size_t kBatchSize = 8;
inline constexpr std::size_t kMaxFrameBytes = 512;
inline constexpr int kHotRecvFlags = MSG_DONTWAIT;
inline constexpr int kHotSendFlags = MSG_DONTWAIT;

struct Datagram {
    std::array<unsigned char, kMaxFrameBytes> bytes{};
    std::size_t size = 0;  // Number of bytes copied into the buffer.
    sockaddr_in source{};
    int flags = 0;
    bool truncated() const noexcept { return (flags & MSG_TRUNC) != 0; }
};
using Batch = std::array<Datagram, kBatchSize>;

// Setup/cleanup stays outside control cycles. open_udp returns an owned nonblocking fd or -1 with errno.
// On success, bound is the actual local address/port; failure leaks no descriptor.
int open_udp(const sockaddr_in& local, sockaddr_in& bound) noexcept;
int connect_udp(int fd, const sockaddr_in& peer) noexcept;
void close_udp(int& fd) noexcept;

// At most one nonblocking syscall per call; no allocation, retry or caller-selected flags. Errors preserve errno.
// Only returned-count batch entries are valid; reject truncated datagrams.
int recv_batch(int fd, Batch& batch) noexcept;
ssize_t send_frame(int fd, const unsigned char* bytes, std::size_t size) noexcept;

enum class Wait { Synchronization, Origin };  // Untimed synchronization or a 5 s origin receive timeout.

// Synchronization/origin setup only; exclusive ownership of fd and aliases. One receive; no EINTR retry.
// Restores prior state; restoration failure closes fd and sets it to -1. Output is invalid on failure.
ssize_t recv_blocking(int& fd, Datagram& out, Wait wait) noexcept;

}  // namespace net

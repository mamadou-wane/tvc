#include "net.hpp"

#include <cerrno>
#include <fcntl.h>
#include <sys/time.h>
#include <unistd.h>

namespace net {

void close_udp(int& fd) noexcept {
    const int owned = fd;
    fd = -1;
    if (owned >= 0) ::close(owned);  // Linux releases fd even on close error; no retry.
}

int open_udp(const sockaddr_in& local, sockaddr_in& bound) noexcept {
    int fd = ::socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK, 0);
    if (fd < 0) return -1;
    constexpr int receive_bytes = 256 * 1024;
    sockaddr_in actual{};
    socklen_t size = sizeof actual;
    if (::setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &receive_bytes, sizeof receive_bytes) < 0 ||
        ::bind(fd, reinterpret_cast<const sockaddr*>(&local), sizeof local) < 0 ||
        ::getsockname(fd, reinterpret_cast<sockaddr*>(&actual), &size) < 0) {
        const int error = errno;
        close_udp(fd);
        errno = error;
        return -1;
    }
    bound = actual;
    return fd;
}

int connect_udp(int fd, const sockaddr_in& peer) noexcept {
    return ::connect(fd, reinterpret_cast<const sockaddr*>(&peer), sizeof peer);
}

int recv_batch(int fd, Batch& batch) noexcept {
    mmsghdr messages[kBatchSize]{};
    iovec buffers[kBatchSize]{};
    for (std::size_t i = 0; i < kBatchSize; ++i) {
        buffers[i] = {batch[i].bytes.data(), batch[i].bytes.size()};
        messages[i].msg_hdr.msg_name = &batch[i].source;
        messages[i].msg_hdr.msg_namelen = sizeof batch[i].source;
        messages[i].msg_hdr.msg_iov = &buffers[i];
        messages[i].msg_hdr.msg_iovlen = 1;
    }
    const int count = ::recvmmsg(fd, messages, kBatchSize, kHotRecvFlags, nullptr);
    for (int i = 0; i < count; ++i) {
        batch[i].size = messages[i].msg_len;
        batch[i].flags = messages[i].msg_hdr.msg_flags;
    }
    return count;
}

ssize_t send_frame(int fd, const unsigned char* bytes, std::size_t size) noexcept {
    if (size > kMaxFrameBytes) { errno = EMSGSIZE; return -1; }
    return ::send(fd, bytes, size, kHotSendFlags);
}

ssize_t recv_blocking(int& fd, Datagram& out, Wait wait) noexcept {
    const int saved_flags = ::fcntl(fd, F_GETFL);
    if (saved_flags < 0) return -1;
    timeval saved_timeout{};
    socklen_t timeout_size = sizeof saved_timeout;
    if (::getsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &saved_timeout, &timeout_size) < 0)
        return -1;

    const timeval timeout{wait == Wait::Origin ? 5 : 0, 0};
    ssize_t result = -1;
    if (::setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof timeout) == 0 &&
        ::fcntl(fd, F_SETFL, saved_flags & ~O_NONBLOCK) == 0) {
        iovec buffer{out.bytes.data(), out.bytes.size()};
        msghdr message{};
        message.msg_name = &out.source;
        message.msg_namelen = sizeof out.source;
        message.msg_iov = &buffer;
        message.msg_iovlen = 1;
        result = ::recvmsg(fd, &message, 0);
        if (result >= 0) {
            out.size = static_cast<std::size_t>(result);
            out.flags = message.msg_flags;
        }
    }
    const int operation_error = errno;
    // A failed restoration must not prevent the other restoration attempt.
    int restore_error = 0;
    if (::fcntl(fd, F_SETFL, saved_flags) < 0) restore_error = errno;
    if (::setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &saved_timeout, sizeof saved_timeout) < 0 &&
        restore_error == 0) restore_error = errno;
    if (restore_error != 0) {
        close_udp(fd);
        errno = restore_error;
        return -1;
    }
    errno = operation_error;
    return result;
}

}  // namespace net

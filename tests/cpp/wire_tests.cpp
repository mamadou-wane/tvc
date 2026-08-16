// tests/cpp/wire_tests.cpp — codec unit tests. Plain main() + CHECK.
#include "../../src/telemetry.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#define CHECK(cond) do { if (!(cond)) { \
    std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
    std::exit(1); } } while (0)

namespace {

void test_crc_known_answers() {
    CHECK(telem::crc32c("123456789", 9) == 0xE3069283u);
    unsigned char buf[32];
    std::memset(buf, 0x00, 32);
    CHECK(telem::crc32c(buf, 32) == 0x8A9136AAu);
    std::memset(buf, 0xFF, 32);
    CHECK(telem::crc32c(buf, 32) == 0x62A8AB43u);
    for (int i = 0; i < 32; ++i) buf[i] = static_cast<unsigned char>(i);
    CHECK(telem::crc32c(buf, 32) == 0x46DD794Eu);
    for (int i = 0; i < 32; ++i) buf[i] = static_cast<unsigned char>(31 - i);
    CHECK(telem::crc32c(buf, 32) == 0x113FDB5Cu);
    CHECK(telem::crc32c(telem::kSchema, std::strlen(telem::kSchema)) ==
          telem::kSchemaHash);
}

void test_encode_frame_layout() {
    unsigned char out[64];
    const std::size_t n = telem::encode_frame(1, 7, "ab", 2, out);
    CHECK(n == 16);
    CHECK(out[0] == 0x90 && out[1] == 0xEB);          // sync on the wire
    CHECK(out[2] == 1 && out[3] == 1);                // version, type
    CHECK(out[4] == 2 && out[5] == 0);                // length LE
    CHECK(out[6] == 7 && out[7] == 0 && out[8] == 0 && out[9] == 0);
    CHECK(out[10] == 'a' && out[11] == 'b');
    std::uint32_t crc = static_cast<std::uint32_t>(out[12]) |
                        static_cast<std::uint32_t>(out[13]) << 8 |
                        static_cast<std::uint32_t>(out[14]) << 16 |
                        static_cast<std::uint32_t>(out[15]) << 24;
    CHECK(crc == telem::crc32c(out + 2, 10));         // everything after sync
}

}  // namespace

int main() {
    test_crc_known_answers();
    test_encode_frame_layout();
    std::puts("wire_tests: ok");
    return 0;
}

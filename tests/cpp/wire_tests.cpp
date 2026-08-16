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

}  // namespace

int main() {
    test_crc_known_answers();
    std::puts("wire_tests: ok");
    return 0;
}

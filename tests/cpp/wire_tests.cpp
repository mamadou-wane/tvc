// tests/cpp/wire_tests.cpp: codec unit tests. Plain main() + CHECK.
#include "../../src/telemetry.hpp"
#include "../../src/wire.hpp"

#include <array>
#include <bit>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <thread>
#include <unistd.h>
#include <vector>

#define CHECK(cond) do { if (!(cond)) { \
    std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
    std::exit(1); } } while (0)

namespace {

std::vector<unsigned char> slurp(const std::string& path) {
    std::FILE* f = std::fopen(path.c_str(), "rb");
    CHECK(f != nullptr);
    std::vector<unsigned char> data;
    unsigned char buf[4096];
    std::size_t n;
    while ((n = std::fread(buf, 1, sizeof buf, f)) > 0)
        data.insert(data.end(), buf, buf + n);
    std::fclose(f);
    return data;
}

template<class T, std::size_t N>
void check_integer_codec(T value, const std::array<unsigned char, N>& expected,
                         void (*put)(unsigned char*, std::size_t, T) noexcept,
                         T (*get)(const unsigned char*, std::size_t) noexcept) {
    std::array<unsigned char, N + 2> actual;
    actual.fill(0xa5);
    put(actual.data(), 1, value);       // deliberately unaligned, with canaries
    CHECK(actual.front() == 0xa5 && actual.back() == 0xa5);
    CHECK(std::memcmp(actual.data() + 1, expected.data(), N) == 0);
    std::array<unsigned char, N + 2> input{};
    std::memcpy(input.data() + 1, expected.data(), N);
    CHECK(get(input.data(), 1) == value);   // decode literals, not put's output
}

void test_integer_endian_helpers() {
    for (const std::uint8_t value : {0, 1, 0x80, 0xff})
        check_integer_codec<std::uint8_t, 1>(value, {value}, wire::put_u8, wire::get_u8);
    check_integer_codec<std::uint16_t, 2>(0, {0, 0}, wire::put_u16_le, wire::get_u16_le);
    check_integer_codec<std::uint16_t, 2>(1, {1, 0}, wire::put_u16_le, wire::get_u16_le);
    check_integer_codec<std::uint16_t, 2>(0x8000u, {0, 0x80}, wire::put_u16_le, wire::get_u16_le);
    check_integer_codec<std::uint16_t, 2>(0xffffu, {0xff, 0xff}, wire::put_u16_le, wire::get_u16_le);
    check_integer_codec<std::uint16_t, 2>(0x1234u, {0x34, 0x12}, wire::put_u16_le, wire::get_u16_le);
    check_integer_codec<std::uint32_t, 4>(0, {0, 0, 0, 0}, wire::put_u32_le, wire::get_u32_le);
    check_integer_codec<std::uint32_t, 4>(1, {1, 0, 0, 0}, wire::put_u32_le, wire::get_u32_le);
    check_integer_codec<std::uint32_t, 4>(0x80000000u, {0, 0, 0, 0x80}, wire::put_u32_le, wire::get_u32_le);
    check_integer_codec<std::uint32_t, 4>(0xffffffffu, {0xff, 0xff, 0xff, 0xff}, wire::put_u32_le, wire::get_u32_le);
    check_integer_codec<std::uint32_t, 4>(0x12345678u, {0x78, 0x56, 0x34, 0x12}, wire::put_u32_le, wire::get_u32_le);
    check_integer_codec<std::uint64_t, 8>(0, {0, 0, 0, 0, 0, 0, 0, 0}, wire::put_u64_le, wire::get_u64_le);
    check_integer_codec<std::uint64_t, 8>(1, {1, 0, 0, 0, 0, 0, 0, 0}, wire::put_u64_le, wire::get_u64_le);
    check_integer_codec<std::uint64_t, 8>(0x8000000000000000u, {0, 0, 0, 0, 0, 0, 0, 0x80}, wire::put_u64_le, wire::get_u64_le);
    check_integer_codec<std::uint64_t, 8>(0xffffffffffffffffu, {0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff}, wire::put_u64_le, wire::get_u64_le);
    check_integer_codec<std::uint64_t, 8>(0x0123456789abcdefu, {0xef, 0xcd, 0xab, 0x89, 0x67, 0x45, 0x23, 0x01}, wire::put_u64_le, wire::get_u64_le);
    check_integer_codec<std::int64_t, 8>(0, {0, 0, 0, 0, 0, 0, 0, 0}, wire::put_i64_le, wire::get_i64_le);
    check_integer_codec<std::int64_t, 8>(1, {1, 0, 0, 0, 0, 0, 0, 0}, wire::put_i64_le, wire::get_i64_le);
    check_integer_codec<std::int64_t, 8>(-1, {0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff}, wire::put_i64_le, wire::get_i64_le);
    check_integer_codec<std::int64_t, 8>(std::numeric_limits<std::int64_t>::min(),
        {0, 0, 0, 0, 0, 0, 0, 0x80}, wire::put_i64_le, wire::get_i64_le);
    check_integer_codec<std::int64_t, 8>(std::numeric_limits<std::int64_t>::max(),
        {0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x7f}, wire::put_i64_le, wire::get_i64_le);
    check_integer_codec<std::int64_t, 8>(-0x0123456789abcdefLL,
        {0x11, 0x32, 0x54, 0x76, 0x98, 0xba, 0xdc, 0xfe}, wire::put_i64_le, wire::get_i64_le);
}

void test_f64_endian_bits() {
    const struct { std::uint64_t bits; unsigned char bytes[8]; } cases[] = {
        {0x0000000000000000u, {0, 0, 0, 0, 0, 0, 0, 0}},
        {0x8000000000000000u, {0, 0, 0, 0, 0, 0, 0, 0x80}}, // negative zero
        {0x3ff4000000000000u, {0, 0, 0, 0, 0, 0, 0xf4, 0x3f}},
        {0xc004000000000000u, {0, 0, 0, 0, 0, 0, 0x04, 0xc0}},
        {0x0000000000000001u, {1, 0, 0, 0, 0, 0, 0, 0}},     // min subnormal
        {0x8000000000000001u, {1, 0, 0, 0, 0, 0, 0, 0x80}},
        {0x0010000000000000u, {0, 0, 0, 0, 0, 0, 0x10, 0}}, // min normal
        {0x7fefffffffffffffu, {0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xef, 0x7f}},
        {0x7ff0000000000000u, {0, 0, 0, 0, 0, 0, 0xf0, 0x7f}}, // infinities
        {0xfff0000000000000u, {0, 0, 0, 0, 0, 0, 0xf0, 0xff}},
        {0x7ff8000000001234u, {0x34, 0x12, 0, 0, 0, 0, 0xf8, 0x7f}}, // quiet NaNs
        {0xfff80000deadbeefu, {0xef, 0xbe, 0xad, 0xde, 0, 0, 0xf8, 0xff}},
        {0x7ff0000000000042u, {0x42, 0, 0, 0, 0, 0, 0xf0, 0x7f}}, // signaling NaNs
        {0xfff0000000000042u, {0x42, 0, 0, 0, 0, 0, 0xf0, 0xff}},
    };
    for (const auto& c : cases) {
        unsigned char actual[10];
        std::memset(actual, 0xa5, sizeof actual);
        wire::put_f64_le(actual, 1, std::bit_cast<double>(c.bits));
        CHECK(actual[0] == 0xa5 && actual[9] == 0xa5);
        CHECK(std::memcmp(actual + 1, c.bytes, 8) == 0);
        unsigned char input[10]{};
        std::memcpy(input + 1, c.bytes, 8);
        CHECK(std::bit_cast<std::uint64_t>(wire::get_f64_le(input, 1)) == c.bits);
    }
}

void test_payload_schema_metadata() {
    const struct { const char* schema; std::uint32_t hash; std::size_t size;
                   std::uint32_t expected_hash; std::size_t expected_size; } cases[] = {
        {telem::kSchema, telem::kSchemaHash, telem::kTelemetryV1PayloadBytes, 0xa871cd84u, 56},
        {telem::kCommandV1Schema, telem::kCommandV1SchemaHash, telem::kCommandV1PayloadBytes, 0x7f802902u, 16},
        {telem::kAckV1Schema, telem::kAckV1SchemaHash, telem::kAckV1PayloadBytes, 0x3d42af39u, 16},
        {telem::kSensorV1Schema, telem::kSensorV1SchemaHash, telem::kSensorV1PayloadBytes, 0xd23a4196u, 44},
        {telem::kActuatorV1Schema, telem::kActuatorV1SchemaHash, telem::kActuatorV1PayloadBytes, 0x25573656u, 48},
        {telem::kControlV1Schema, telem::kControlV1SchemaHash, telem::kControlV1PayloadBytes, 0xadfa94c8u, 128},
    };
    for (const auto& c : cases) {
        CHECK(c.hash == c.expected_hash);
        CHECK(telem::crc32c(c.schema, std::strlen(c.schema)) == c.expected_hash);
        CHECK(c.size == c.expected_size);
    }
}

void test_record_layouts() {
    CHECK(std::endian::native == std::endian::little);
    CHECK(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559);
    CHECK(std::numeric_limits<double>::radix == 2);
    CHECK(std::numeric_limits<double>::digits == 53);
    CHECK(std::numeric_limits<double>::max_exponent == 1024);
    CHECK(std::is_standard_layout_v<telem::Record>);
    CHECK(std::is_trivially_copyable_v<telem::Record>);
    CHECK(alignof(telem::Record) == 8 && sizeof(telem::Record) == 56);
    const std::size_t record_offsets[] = {
        offsetof(telem::Record, tick), offsetof(telem::Record, deadline_ns),
        offsetof(telem::Record, woke_ns), offsetof(telem::Record, done_ns),
        offsetof(telem::Record, theta), offsetof(telem::Record, cmd),
        offsetof(telem::Record, drops),
    };
    const std::size_t expected_record[] = {0, 8, 16, 24, 32, 40, 48};
    CHECK(std::memcmp(record_offsets, expected_record, sizeof expected_record) == 0);
    CHECK(std::is_standard_layout_v<telem::ControlRecord>);
    CHECK(std::is_trivially_copyable_v<telem::ControlRecord>);
    CHECK(alignof(telem::ControlRecord) == 8 && sizeof(telem::ControlRecord) == 128);
    const std::size_t control_offsets[] = {
        offsetof(telem::ControlRecord, tick), offsetof(telem::ControlRecord, deadline_ns),
        offsetof(telem::ControlRecord, woke_ns), offsetof(telem::ControlRecord, done_ns),
        offsetof(telem::ControlRecord, sensor_send_ns), offsetof(telem::ControlRecord, rx_ns),
        offsetof(telem::ControlRecord, tx_ns), offsetof(telem::ControlRecord, sensor_tick),
        offsetof(telem::ControlRecord, theta), offsetof(telem::ControlRecord, omega),
        offsetof(telem::ControlRecord, cmd), offsetof(telem::ControlRecord, i_state),
        offsetof(telem::ControlRecord, d_prev), offsetof(telem::ControlRecord, drops),
        offsetof(telem::ControlRecord, staleness), offsetof(telem::ControlRecord, ack_cmd_seq),
        offsetof(telem::ControlRecord, rx_count), offsetof(telem::ControlRecord, discarded_old),
        offsetof(telem::ControlRecord, discarded_superseded), offsetof(telem::ControlRecord, discarded_other),
        offsetof(telem::ControlRecord, state), offsetof(telem::ControlRecord, reason),
        offsetof(telem::ControlRecord, flags), offsetof(telem::ControlRecord, ack_status),
    };
    const std::size_t expected_control[] = {
        0, 8, 16, 24, 32, 40, 48, 56, 64, 72, 80, 88, 96, 104,
        112, 116, 120, 121, 122, 123, 124, 125, 126, 127,
    };
    CHECK(std::memcmp(control_offsets, expected_control, sizeof expected_control) == 0);
}

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

void test_decode_round_trip() {
    unsigned char buf[600];
    std::size_t n = telem::encode_frame(1, 5, "hello", 5, buf);
    n += telem::encode_frame(2, 6, "", 0, buf + n);
    std::vector<telem::DecodedFrame> frames;
    const auto ctr = telem::decode_stream(buf, n, frames);
    CHECK(frames.size() == 2 && ctr.frames_ok == 2);
    CHECK(frames[0].type == 1 && frames[0].seq == 5 && frames[0].payload_len == 5);
    CHECK(std::memcmp(buf + frames[0].payload_off, "hello", 5) == 0);
    CHECK(ctr.lost == 0 && ctr.skipped_bytes == 0);
}

void test_gap_rules() {
    unsigned char buf[600];
    std::size_t n = telem::encode_frame(1, 0xFFFFFFFFu, "", 0, buf);
    n += telem::encode_frame(1, 0, "", 0, buf + n);
    std::vector<telem::DecodedFrame> frames;
    auto ctr = telem::decode_stream(buf, n, frames);
    CHECK(ctr.lost == 0 && ctr.seq_discontinuities == 0);   // wrap is gapless

    n = telem::encode_frame(1, 5, "", 0, buf);
    n += telem::encode_frame(1, 8, "", 0, buf + n);
    frames.clear();
    ctr = telem::decode_stream(buf, n, frames);
    CHECK(ctr.lost == 2);

    n = telem::encode_frame(1, 100, "", 0, buf);
    n += telem::encode_frame(1, 50, "", 0, buf + n);
    frames.clear();
    ctr = telem::decode_stream(buf, n, frames);
    CHECK(ctr.lost == 0 && ctr.seq_discontinuities == 1);
}

void test_truncation_and_corruption() {
    unsigned char buf[64];
    const std::size_t n = telem::encode_frame(1, 0, "abc", 3, buf);
    for (std::size_t cut = 0; cut < n; ++cut) {
        std::vector<telem::DecodedFrame> frames;
        const auto ctr = telem::decode_stream(buf, cut, frames);
        CHECK(frames.empty() && ctr.skipped_bytes == cut);
    }
    for (std::size_t i = 0; i < n; ++i) {
        unsigned char bad[64];
        std::memcpy(bad, buf, n);
        bad[i] ^= 0xFF;
        std::vector<telem::DecodedFrame> frames;
        const auto ctr = telem::decode_stream(bad, n, frames);
        CHECK(frames.empty() && ctr.skipped_bytes == n);
    }
}

struct Expect {
    const char* file;
    telem::DecodeCounters ctr;
    bool roundtrip;
    bool recording;   // strip the 32-byte header first
};

void test_golden_corpus(const std::string& dir) {
    const Expect cases[] = {
        {"frame_record.bin",    {1, 0, 0, 0, 0, 0, 0},  true,  false},
        {"frame_empty.bin",     {1, 0, 0, 0, 0, 0, 0},  true,  false},
        {"frame_max.bin",       {1, 0, 0, 0, 0, 0, 0},  true,  false},
        {"frames_seqwrap.bin",  {2, 0, 0, 0, 0, 0, 0},  true,  false},
        {"frame_badcrc.bin",    {0, 1, 0, 1, 0, 0, 70}, false, false},
        {"frame_truncated.bin", {0, 0, 0, 0, 0, 0, 30}, false, false},
        {"recording_mini.tvcrec", {5, 1, 0, 1, 0, 1, 70}, false, true},
    };
    for (const auto& c : cases) {
        auto data = slurp(dir + "/" + c.file);
        const unsigned char* body = data.data() + (c.recording ? 32 : 0);
        const std::size_t body_len = data.size() - (c.recording ? 32 : 0);
        std::vector<telem::DecodedFrame> frames;
        const auto ctr = telem::decode_stream(body, body_len, frames);
        CHECK(ctr.frames_ok == c.ctr.frames_ok);
        CHECK(ctr.crc_errors == c.ctr.crc_errors);
        CHECK(ctr.version_mismatch == c.ctr.version_mismatch);
        CHECK(ctr.resyncs == c.ctr.resyncs);
        CHECK(ctr.seq_discontinuities == c.ctr.seq_discontinuities);
        CHECK(ctr.lost == c.ctr.lost);
        CHECK(ctr.skipped_bytes == c.ctr.skipped_bytes);
        if (!c.roundtrip) continue;
        std::vector<unsigned char> re;
        unsigned char frame[512];
        for (const auto& fr : frames) {
            const std::size_t m = telem::encode_frame(
                fr.type, fr.seq, body + fr.payload_off, fr.payload_len, frame);
            re.insert(re.end(), frame, frame + m);
        }
        CHECK(re.size() == body_len);
        CHECK(std::memcmp(re.data(), body, body_len) == 0);
    }
}

void test_header_layout() {
    unsigned char h[32];
    CHECK(telem::encode_recording_header(1000, 2000, h) == 32);
    CHECK(std::memcmp(h, "TVCRECRD", 8) == 0);
    CHECK(h[8] == 1 && h[9] == 0);                    // version LE
    CHECK(h[10] == 0 && h[11] == 0);                  // reserved
    const std::uint32_t sh = static_cast<std::uint32_t>(h[12]) |
        static_cast<std::uint32_t>(h[13]) << 8 |
        static_cast<std::uint32_t>(h[14]) << 16 |
        static_cast<std::uint32_t>(h[15]) << 24;
    CHECK(sh == telem::kSchemaHash);
    CHECK(h[16] == 0xE8 && h[17] == 0x03);            // 1000 LE
}

void test_drain_counters() {
    telem::SpscRing ring;
    for (std::uint64_t i = 0; i < 100; ++i) {
        telem::Record r{i, 1, 2, 3, 0.5, -0.5, 0};
        CHECK(ring.try_push(r));
    }
    std::FILE* f = std::tmpfile();
    CHECK(f != nullptr);
    telem::Drain drain(ring);
    drain.start(f);
    drain.stop();        // drains until empty, then flushes and closes f
    CHECK(!drain.write_failed());
    CHECK(drain.records_written() == 100);
    CHECK(drain.bytes_written() == 100 * 70);
}

void test_drain_known_answer_bytes() {
    // Pin the real drain before changing its serializer. These literals use
    // explicit LE fields and independently checked CRC-32C values, never the
    // encoder under test. Distinct fields expose swaps; NaNs expose arithmetic.
    const telem::Record records[] = {
        {0x0102030405060708u, -0x0102030405060708LL,
         0x1112131415161718LL, 0x2122232425262728LL,
         1.25, -2.5, 0xf1f2f3f4f5f6f7f8u},
        {9, std::numeric_limits<std::int64_t>::min(),
         std::numeric_limits<std::int64_t>::max(), -1,
         std::bit_cast<double>(std::uint64_t{0x8000000000000000u}),
         std::bit_cast<double>(std::uint64_t{0x7ff0000000000042u}), 19},
        {10, -17, 42, 999,
         std::bit_cast<double>(std::uint64_t{0x7ff8000000001234u}),
         std::bit_cast<double>(std::uint64_t{0xfff80000deadbeefu}), 20},
        {11, -18, 43, 1000,
         std::bit_cast<double>(std::uint64_t{0xfff0000000000042u}),
         std::bit_cast<double>(std::uint64_t{0x8000000000000001u}), 21},
    };
    const unsigned char expected[] = {
        0x90, 0xeb, 0x01, 0x01, 0x38, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01, 0xf8, 0xf8,
        0xf9, 0xfa, 0xfb, 0xfc, 0xfd, 0xfe, 0x18, 0x17, 0x16, 0x15,
        0x14, 0x13, 0x12, 0x11, 0x28, 0x27, 0x26, 0x25, 0x24, 0x23,
        0x22, 0x21, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf4, 0x3f,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x04, 0xc0, 0xf8, 0xf7,
        0xf6, 0xf5, 0xf4, 0xf3, 0xf2, 0xf1, 0x91, 0xee, 0xa2, 0xa6,
        0x90, 0xeb, 0x01, 0x01, 0x38, 0x00, 0x01, 0x00, 0x00, 0x00,
        0x09, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0xff, 0xff, 0xff, 0xff,
        0xff, 0xff, 0xff, 0x7f, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
        0xff, 0xff, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80,
        0x42, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0, 0x7f, 0x13, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0b, 0x28, 0xfe, 0x1a,
        0x90, 0xeb, 0x01, 0x01, 0x38, 0x00, 0x02, 0x00, 0x00, 0x00,
        0x0a, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xef, 0xff,
        0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x2a, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0xe7, 0x03, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x34, 0x12, 0x00, 0x00, 0x00, 0x00, 0xf8, 0x7f,
        0xef, 0xbe, 0xad, 0xde, 0x00, 0x00, 0xf8, 0xff, 0x14, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf4, 0x89, 0x21, 0xcf,
        0x90, 0xeb, 0x01, 0x01, 0x38, 0x00, 0x03, 0x00, 0x00, 0x00,
        0x0b, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xee, 0xff,
        0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x2b, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0xe8, 0x03, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x42, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0, 0xff,
        0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0x15, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xad, 0x78, 0x71, 0xd7,
    };
    static_assert(sizeof expected == 4 * 70);
    telem::SpscRing ring;
    for (const auto& record : records) CHECK(ring.try_push(record));
    std::FILE* f = std::tmpfile();
    CHECK(f != nullptr);
    // Drain owns and closes f; retain a descriptor to inspect the same file.
    const int read_fd = ::dup(::fileno(f));
    CHECK(read_fd >= 0);
    telem::Drain drain(ring);
    drain.start(f);
    drain.stop();
    CHECK(!drain.write_failed());
    CHECK(drain.records_written() == 4);
    CHECK(drain.bytes_written() == sizeof expected);
    std::FILE* reader = ::fdopen(read_fd, "rb");
    CHECK(reader != nullptr);
    std::rewind(reader);
    unsigned char actual[sizeof expected];
    CHECK(std::fread(actual, 1, sizeof actual, reader) == sizeof actual);
    CHECK(std::fgetc(reader) == EOF && !std::ferror(reader));
    CHECK(std::fclose(reader) == 0);
    CHECK(std::memcmp(actual, expected, sizeof expected) == 0);
    std::puts("drain known-answer: 4 literal frames match");
}

void test_drain_output_decodes() {
    telem::SpscRing ring;
    for (std::uint64_t i = 0; i < 5; ++i)
        CHECK(ring.try_push({i, 1, 2, 3, 0.0, 0.0, 0}));
    const char* path = "build/drain_test.bin";
    std::FILE* f = std::fopen(path, "wb+");
    CHECK(f != nullptr);
    telem::Drain drain(ring);
    drain.start(f);
    drain.stop();
    auto data = slurp(path);
    CHECK(data.size() == 5 * 70);
    std::vector<telem::DecodedFrame> frames;
    const auto ctr = telem::decode_stream(data.data(), data.size(), frames);
    CHECK(ctr.frames_ok == 5 && ctr.lost == 0 && ctr.skipped_bytes == 0);
    for (std::size_t i = 0; i < 5; ++i) {
        CHECK(frames[i].seq == i);                    // seq assigned by drain
        CHECK(frames[i].type == telem::kTypeTelemetry);
    }
    std::remove(path);
}

void test_drain_stop_after_concurrent_push() {
    telem::SpscRing ring;
    const char* path = "build/drain_race_test.bin";
    std::FILE* f = std::fopen(path, "wb+");
    CHECK(f != nullptr);
    telem::Drain drain(ring);
    drain.start(f);
    std::uint64_t pushed = 0;
    std::thread producer([&] {
        for (std::uint64_t i = 0; i < 50000; ++i) {
            if (ring.try_push({i, 1, 2, 3, 0.0, 0.0, 0})) ++pushed;
        }
    });
    producer.join();
    drain.stop();
    CHECK(!drain.write_failed());
    CHECK(drain.records_written() == pushed);
    auto data = slurp(path);
    std::vector<telem::DecodedFrame> frames;
    const auto ctr = telem::decode_stream(data.data(), data.size(), frames);
    CHECK(ctr.frames_ok == pushed);
    std::remove(path);
}

// Independent typed-payload literals, not generated by either codec.
const unsigned char kRecordPayload[] = {
    0x08,0x07,0x06,0x05,0x04,0x03,0x02,0x01, 0xfe,0xff,0xff,0xff,0xff,0xff,0xff,0xff,
    0x18,0x17,0x16,0x15,0x14,0x13,0x12,0x11, 0x28,0x27,0x26,0x25,0x24,0x23,0x22,0x21,
    0,0,0,0,0,0,0xf4,0x3f, 0,0,0,0,0,0,0x04,0xc0, 0x38,0x37,0x36,0x35,0x34,0x33,0x32,0x31,
};
const unsigned char kCommandPayload[] = {
    0x04,0x03,0x02,0x01, 3,0,1,0, 0x18,0x17,0x16,0x15,0x14,0x13,0x12,0x11,
};
const unsigned char kAckPayload[] = {
    0x28,0x27,0x26,0x25,0x24,0x23,0x22,0x21, 0x34,0x33,0x32,0x31, 2,0,1,7,
};
const unsigned char kSensorPayload[] = {
    0x08,0x07,0x06,0x05,0x04,0x03,0x02,0x01, 0xfe,0xff,0xff,0xff,0xff,0xff,0xff,0xff,
    0,0,0,0,0,0,0xf4,0x3f, 0,0,0,0,0,0,0x04,0xc0, 7,3,0,0, 0x24,0x23,0x22,0x21, 2,0,0,0,
};
const unsigned char kActuatorPayload[] = {
    0x08,0x07,0x06,0x05,0x04,0x03,0x02,0x01, 0x18,0x17,0x16,0x15,0x14,0x13,0x12,0x11,
    0xfd,0xff,0xff,0xff,0xff,0xff,0xff,0xff, 0x28,0x27,0x26,0x25,0x24,0x23,0x22,0x21,
    0,0,0,0,0,0,0xc0,0xbf, 1,2,3,0x84, 0x34,0x33,0x32,0x31,
};
const unsigned char kControlPayload[] = {
    1,0,0,0,0,0,0,0, 0xfe,0xff,0xff,0xff,0xff,0xff,0xff,0xff,
    3,0,0,0,0,0,0,0, 4,0,0,0,0,0,0,0, 5,0,0,0,0,0,0,0, 6,0,0,0,0,0,0,0,
    7,0,0,0,0,0,0,0, 8,0,0,0,0,0,0,0, 0,0,0,0,0,0,0xf4,0x3f, 0,0,0,0,0,0,0x04,0xc0,
    0,0,0,0,0,0,0,0x80, 0,0,0,0,0,0,0x0e,0x40, 0,0,0,0,0,0,0x12,0xc0,
    14,0,0,0,0,0,0,0, 15,0,0,0,16,0,0,0, 9,1,2,3,4,5,0x76,7,
};

void test_typed_payload_codecs() {
    using namespace telem::payload;
    unsigned char out[128]{};
    telem::Record record{0x0102030405060708u, -2, 0x1112131415161718LL,
                         0x2122232425262728LL, 1.25, -2.5, 0x3132333435363738u};
    CHECK(encode_record(out, 56, record));
    CHECK(std::memcmp(out, kRecordPayload, 56) == 0);
    record = {};
    CHECK(decode_record(kRecordPayload, 56, record));
    CHECK(record.tick == 0x0102030405060708u && record.deadline_ns == -2);
    CHECK(record.woke_ns == 0x1112131415161718LL && record.done_ns == 0x2122232425262728LL);
    CHECK(record.theta == 1.25 && record.cmd == -2.5 && record.drops == 0x3132333435363738u);

    std::uint64_t tick = 0, other_tick = 0;
    std::int64_t stamp = 0, other_stamp = 0;
    std::uint32_t seq = 0, flags = 0, reason = 0;
    std::uint16_t opcode = 0, short_flags = 0;
    std::uint8_t state = 0, byte_reason = 0;
    double theta = 0, omega = 0;
    CHECK(encode_command(out, 16, 0x01020304u, 3, 1, 0x1112131415161718u));
    CHECK(std::memcmp(out, kCommandPayload, 16) == 0);
    CHECK(decode_command(kCommandPayload, 16, seq, opcode, short_flags, tick));
    CHECK(seq == 0x01020304u && opcode == 3 && short_flags == 1 && tick == 0x1112131415161718u);
    CHECK(encode_ack(out, 16, 0x2122232425262728u, 0x31323334u, 2, 1, 7));
    CHECK(std::memcmp(out, kAckPayload, 16) == 0);
    CHECK(decode_ack(kAckPayload, 16, tick, seq, opcode, state, byte_reason));
    CHECK(tick == 0x2122232425262728u && seq == 0x31323334u && opcode == 2 && state == 1 && byte_reason == 7);
    CHECK(encode_sensor(out, 44, 0x0102030405060708u, -2, 1.25, -2.5, 0x0307, 0x21222324u, 2));
    CHECK(std::memcmp(out, kSensorPayload, 44) == 0);
    CHECK(decode_sensor(kSensorPayload, 44, tick, stamp, theta, omega, flags, seq, reason));
    CHECK(tick == 0x0102030405060708u && stamp == -2 && theta == 1.25 && omega == -2.5);
    CHECK(flags == 0x0307 && seq == 0x21222324u && reason == 2);
    CHECK(encode_actuator(out, 48, 0x0102030405060708u, 0x1112131415161718u,
                          -3, 0x2122232425262728LL, -0.125, 0x84030201u, 0x31323334u));
    CHECK(std::memcmp(out, kActuatorPayload, 48) == 0);
    CHECK(decode_actuator(kActuatorPayload, 48, tick, other_tick, stamp, other_stamp, theta, flags, seq));
    CHECK(tick == 0x0102030405060708u && other_tick == 0x1112131415161718u);
    CHECK(stamp == -3 && other_stamp == 0x2122232425262728LL && theta == -0.125);
    CHECK(flags == 0x84030201u && seq == 0x31323334u);

    telem::ControlRecord control{1,-2,3,4,5,6,7,8,1.25,-2.5,-0.0,3.75,-4.5,14,15,16,9,1,2,3,4,5,0x76,7};
    CHECK(encode_control(out, 128, control));
    CHECK(std::memcmp(out, kControlPayload, 128) == 0);
    control = {};
    CHECK(decode_control(kControlPayload, 128, control));
    CHECK(control.tick == 1 && control.deadline_ns == -2 && control.woke_ns == 3 && control.done_ns == 4);
    CHECK(control.sensor_send_ns == 5 && control.rx_ns == 6 && control.tx_ns == 7 && control.sensor_tick == 8);
    CHECK(control.theta == 1.25 && control.omega == -2.5 && control.i_state == 3.75 && control.d_prev == -4.5);
    CHECK(std::bit_cast<std::uint64_t>(control.cmd) == 0x8000000000000000u);
    CHECK(control.drops == 14 && control.staleness == 15 && control.ack_cmd_seq == 16);
    CHECK(control.rx_count == 9 && control.discarded_old == 1 && control.discarded_superseded == 2);
    CHECK(control.discarded_other == 3 && control.state == 4 && control.reason == 5);
    CHECK(control.flags == 0x76 && control.ack_status == 7);

    // Exact lengths checked before reading; zero-length vectors may have null data.
    for (std::size_t n = 0; n <= 129; ++n) {
        std::vector<unsigned char> input(n);
        if (n != 56) CHECK(!decode_record(input.data(), n, record));
        if (n != 16) CHECK(!decode_command(input.data(), n, seq, opcode, short_flags, tick));
        if (n != 16) CHECK(!decode_ack(input.data(), n, tick, seq, opcode, state, byte_reason));
        if (n != 44) CHECK(!decode_sensor(input.data(), n, tick, stamp, theta, omega, flags, seq, reason));
        if (n != 48) CHECK(!decode_actuator(input.data(), n, tick, other_tick, stamp, other_stamp, theta, flags, seq));
        if (n != 128) CHECK(!decode_control(input.data(), n, control));
    }
    CHECK(!encode_record(out, 55, record));
    CHECK(!encode_command(out, 15, 0, 0, 0, 0));
    CHECK(!encode_ack(out, 15, 0, 0, 0, 0, 0));
    CHECK(!encode_sensor(out, 43, 0, 0, 0, 0, 0, 0, 0));
    CHECK(!encode_actuator(out, 47, 0, 0, 0, 0, 0, 0, 0));
    CHECK(!encode_control(out, 127, control));
}

void test_payload_flags_bits_and_counts() {
    using namespace telem::payload;
    unsigned char out[128]{};
    std::uint64_t tick = 0, other_tick = 0;
    std::int64_t stamp = 0, other_stamp = 0;
    std::uint32_t flags = 0, seq = 0, reason = 0;
    std::uint16_t opcode = 0, short_flags = 0;
    double a = 0, b = 0;
    CHECK(encode_command(out, 16, 0, 65535, 65535, 0));
    CHECK(out[6] == 1 && out[7] == 0);  // writer zeroes reserved flags
    out[6] = out[7] = 0xff;
    CHECK(decode_command(out, 16, seq, opcode, short_flags, tick));
    CHECK(short_flags == 65535 && opcode == 65535); // reader tolerates reserved/unknown
    CHECK(encode_sensor(out, 44, 0, 0, 0, 0, 0xffffffffu, 0, 0xffffffffu));
    CHECK(out[32] == 7 && out[33] == 0xff && out[34] == 0 && out[35] == 0);
    std::memset(out + 32, 0xff, 4);
    CHECK(decode_sensor(out, 44, tick, stamp, a, b, flags, seq, reason));
    CHECK(flags == 0xffffffffu && reason == 0xffffffffu);

    for (const std::uint64_t bits : {0x8000000000000000u, 0x7ff8000000001234u,
                                    0xfff80000deadbeefu, 0x7ff0000000000042u,
                                    0xfff0000000000042u, 0x7ff0000000000000u}) {
        const double value = std::bit_cast<double>(bits);
        telem::Record record{0,0,0,0,value,value,0};
        CHECK(encode_record(out, 56, record));
        CHECK(wire::get_u64_le(out, 32) == bits && wire::get_u64_le(out, 40) == bits);
        CHECK(decode_record(out, 56, record));
        CHECK(std::bit_cast<std::uint64_t>(record.theta) == bits && std::bit_cast<std::uint64_t>(record.cmd) == bits);
        CHECK(encode_sensor(out, 44, 0, 0, value, value, 0, 0, 0));
        CHECK(wire::get_u64_le(out, 16) == bits && wire::get_u64_le(out, 24) == bits);
        CHECK(decode_sensor(out, 44, tick, stamp, a, b, flags, seq, reason));
        CHECK(std::bit_cast<std::uint64_t>(a) == bits && std::bit_cast<std::uint64_t>(b) == bits);
        CHECK(encode_actuator(out, 48, 0, 0, 0, 0, value, 0xffffffffu, 0));
        CHECK(wire::get_u64_le(out, 32) == bits);
        CHECK(decode_actuator(out, 48, tick, other_tick, stamp, other_stamp, a, flags, seq));
        CHECK(std::bit_cast<std::uint64_t>(a) == bits && flags == 0xffffffffu);
        telem::ControlRecord control{};
        control.theta = control.omega = control.cmd = control.i_state = control.d_prev = value;
        control.state = control.reason = control.ack_status = 255;
        CHECK(encode_control(out, 128, control));
        for (std::size_t offset : {64,72,80,88,96}) CHECK(wire::get_u64_le(out, offset) == bits);
        CHECK(decode_control(out, 128, control));
        for (double field : {control.theta, control.omega, control.cmd, control.i_state, control.d_prev})
            CHECK(std::bit_cast<std::uint64_t>(field) == bits);
        CHECK(control.state == 255 && control.reason == 255 && control.ack_status == 255);
    }
    const unsigned char bad_counts[][4] = {{10,0,0,0}, {9,4,3,3}, {9,255,1,0}, {9,250,250,20}};
    for (const auto& counts : bad_counts) {
        std::memcpy(out, kControlPayload, 128);
        std::memcpy(out + 120, counts, 4);
        telem::ControlRecord control{};
        CHECK(!decode_control(out, 128, control));
        control.rx_count = counts[0]; control.discarded_old = counts[1];
        control.discarded_superseded = counts[2]; control.discarded_other = counts[3];
        CHECK(!encode_control(out, 128, control));
    }
    for (const auto& counts : {std::array<unsigned char,4>{0,0,0,0}, {9,3,3,3}, {9,9,0,0}}) {
        std::memcpy(out, kControlPayload, 128);
        std::memcpy(out + 120, counts.data(), 4);
        telem::ControlRecord control{};
        CHECK(decode_control(out, 128, control));
    }
}

void test_strict_datagrams_and_expanded_framing() {
    using E = telem::DatagramError;
    const struct { std::uint8_t type; const unsigned char* bytes; std::size_t size; } cases[] = {
        {1,kRecordPayload,56}, {2,kCommandPayload,16}, {3,kAckPayload,16},
        {4,kSensorPayload,44}, {5,kActuatorPayload,48}, {6,kControlPayload,128},
    };
    for (const auto& c : cases) {
        unsigned char frame[512]{};
        const auto size = telem::encode_frame(c.type, 7, c.bytes, c.size, frame);
        telem::DecodedFrame decoded{};
        CHECK(telem::decode_datagram(frame, size, {c.type}, decoded) == E::None);
        CHECK(decoded.type == c.type && decoded.seq == 7 && decoded.payload_off == 10 && decoded.payload_len == c.size);
        for (std::size_t n = 0; n < size; ++n)
            CHECK(telem::decode_datagram(frame, n, {c.type}, decoded) == E::BadLength);
        CHECK(telem::decode_datagram(frame, size + 1, {c.type}, decoded) == E::BadLength);
        std::memcpy(frame + size, frame, size);
        CHECK(telem::decode_datagram(frame, size * 2, {c.type}, decoded) == E::BadLength);
        CHECK(telem::decode_datagram(frame, size, {}, decoded) == E::BadType);
        CHECK(telem::decode_datagram(frame, size, {static_cast<std::uint8_t>(c.type == 4 ? 5 : 4)}, decoded) == E::BadType);
        frame[0] ^= 0xff;
        CHECK(telem::decode_datagram(frame, size, {c.type}, decoded) == E::BadSync);
        frame[0] ^= 0xff; frame[2] = 2;
        CHECK(telem::decode_datagram(frame, size, {c.type}, decoded) == E::BadVersion);
        frame[2] = 1; frame[size - 1] ^= 0xff;
        CHECK(telem::decode_datagram(frame, size, {c.type}, decoded) == E::BadCrc);
        for (std::size_t n : {c.size - 1, c.size + 1}) {
            unsigned char payload[129]{};
            const auto bad_size = telem::encode_frame(c.type, 7, payload, n, frame);
            CHECK(telem::decode_datagram(frame, bad_size, {c.type}, decoded) == E::BadLength);
        }
        const auto generic_size = telem::encode_frame(c.type, 7, "abc", 3, frame);
        std::vector<telem::DecodedFrame> frames;
        const auto ctr = telem::decode_stream(frame, generic_size, frames);
        CHECK(ctr.frames_ok == 1 && frames[0].payload_len == 3 && ctr.skipped_bytes == 0);
    }
    unsigned char frame[128]{};
    telem::DecodedFrame decoded{};
    const auto size = telem::encode_frame(4, 7, kSensorPayload, 44, frame + 4);
    CHECK(telem::decode_datagram(frame, size + 4, {4,5}, decoded) == E::BadSync);
    CHECK(telem::decode_datagram(frame + 4, size, {4,5}, decoded) == E::None);
    const auto unknown_size = telem::encode_frame(7, 7, "", 0, frame);
    CHECK(telem::decode_datagram(frame, unknown_size, {7}, decoded) == E::BadType);
}

void check_control_corpus_fields(const unsigned char* p, std::size_t len, std::uint64_t tick) {
    telem::ControlRecord r{};
    CHECK(telem::payload::decode_control(p, len, r));
    CHECK(r.tick == tick && r.deadline_ns == -2 && r.woke_ns == 3 && r.done_ns == 4);
    CHECK(r.sensor_send_ns == 5 && r.rx_ns == 6 && r.tx_ns == 7 && r.sensor_tick == 8);
    CHECK(std::bit_cast<std::uint64_t>(r.theta) == 0x3ff4000000000000u);
    CHECK(std::bit_cast<std::uint64_t>(r.omega) == 0xc004000000000000u);
    CHECK(std::bit_cast<std::uint64_t>(r.cmd) == 0x8000000000000000u);
    CHECK(std::bit_cast<std::uint64_t>(r.i_state) == 0x400e000000000000u);
    CHECK(std::bit_cast<std::uint64_t>(r.d_prev) == 0xc012000000000000u);
    CHECK(r.drops == 14 && r.staleness == 15 && r.ack_cmd_seq == 16);
    CHECK(r.rx_count == 9 && r.discarded_old == 1 && r.discarded_superseded == 2);
    CHECK(r.discarded_other == 3 && r.state == 4 && r.reason == 5);
    CHECK(r.flags == 0x76 && r.ack_status == 7);
}

void check_standalone_corpus_fields(std::uint8_t type, const unsigned char* p, std::size_t len) {
    using namespace telem::payload;
    std::uint64_t tick = 0, veh_tick = 0;
    std::int64_t stamp = 0, other_stamp = 0;
    std::uint32_t seq = 0, flags = 0, reason = 0;
    std::uint16_t opcode = 0, short_flags = 0;
    std::uint8_t state = 0, byte_reason = 0;
    double theta = 0, omega = 0;
    switch (type) {
    case 2:
        CHECK(decode_command(p, len, seq, opcode, short_flags, tick));
        CHECK(seq == 0x01020304u && opcode == 3 && short_flags == 1 && tick == 0x1112131415161718u);
        break;
    case 3:
        CHECK(decode_ack(p, len, tick, seq, opcode, state, byte_reason));
        CHECK(tick == 0x2122232425262728u && seq == 0x31323334u && opcode == 2 && state == 1 && byte_reason == 7);
        break;
    case 4:
        CHECK(decode_sensor(p, len, tick, stamp, theta, omega, flags, seq, reason));
        CHECK(tick == 0x0102030405060708u && stamp == -2);
        CHECK(std::bit_cast<std::uint64_t>(theta) == 0x3ff4000000000000u);
        CHECK(std::bit_cast<std::uint64_t>(omega) == 0xc004000000000000u);
        CHECK(flags == 0x0307 && seq == 0x21222324u && reason == 2);
        break;
    case 5:
        CHECK(decode_actuator(p, len, tick, veh_tick, stamp, other_stamp, theta, flags, seq));
        CHECK(tick == 0x0102030405060708u && veh_tick == 0x1112131415161718u);
        CHECK(stamp == -3 && other_stamp == 0x2122232425262728LL);
        CHECK(std::bit_cast<std::uint64_t>(theta) == 0xbfc0000000000000u);
        CHECK(flags == 0x84030201u && seq == 0x31323334u);
        break;
    case 6:
        check_control_corpus_fields(p, len, 1);
        break;
    default:
        CHECK(false);
    }
}

void test_new_standalone_corpus(const std::string& dir) {
    // Header/CRC literals are independent of the generator and candidate codecs.
    const struct {
        const char* file;
        std::uint8_t type;
        std::uint32_t seq;
        std::size_t size, payload_size;
        const unsigned char* payload;
        unsigned char head[10], crc[4];
    } cases[] = {
        {"frame_sensor.bin", 4, 0, 58, 44, kSensorPayload,
         {0x90,0xeb,1,4,44,0,0,0,0,0}, {0x7e,0xf2,0xa5,0xb9}},
        {"frame_actuator.bin", 5, 1, 62, 48, kActuatorPayload,
         {0x90,0xeb,1,5,48,0,1,0,0,0}, {0x38,0x24,0x08,0x11}},
        {"frame_command.bin", 2, 2, 30, 16, kCommandPayload,
         {0x90,0xeb,1,2,16,0,2,0,0,0}, {0xdb,0xb1,0x97,0x4d}},
        {"frame_ack.bin", 3, 3, 30, 16, kAckPayload,
         {0x90,0xeb,1,3,16,0,3,0,0,0}, {0xa5,0x91,0x56,0x41}},
        {"frame_control.bin", 6, 4, 142, 128, kControlPayload,
         {0x90,0xeb,1,6,128,0,4,0,0,0}, {0x42,0xe1,0x99,0xde}},
    };
    for (const auto& c : cases) {
        const auto data = slurp(dir + "/" + c.file);
        std::vector<unsigned char> expected(c.head, c.head + 10);
        expected.insert(expected.end(), c.payload, c.payload + c.payload_size);
        expected.insert(expected.end(), c.crc, c.crc + 4);
        CHECK(data.size() == c.size && data == expected);
        telem::DecodedFrame frame{};
        CHECK(telem::decode_datagram(data.data(), data.size(), {c.type}, frame) == telem::DatagramError::None);
        CHECK(frame.type == c.type && frame.seq == c.seq);
        CHECK(frame.payload_off == 10 && frame.payload_len == c.payload_size);
        check_standalone_corpus_fields(frame.type, data.data() + frame.payload_off, frame.payload_len);
        std::vector<telem::DecodedFrame> frames;
        const auto ctr = telem::decode_stream(data.data(), data.size(), frames);
        CHECK(frames.size() == 1 && ctr.frames_ok == 1);
        CHECK(ctr.crc_errors == 0 && ctr.version_mismatch == 0 && ctr.resyncs == 0);
        CHECK(ctr.seq_discontinuities == 0 && ctr.lost == 0 && ctr.skipped_bytes == 0);
        unsigned char reencoded[142]{};
        const auto size = telem::encode_frame(c.type, c.seq, data.data() + 10, c.payload_size, reencoded);
        CHECK(size == data.size() && std::memcmp(reencoded, data.data(), size) == 0);
    }
}

void test_control_recording_corpus(const std::string& dir) {
    const auto data = slurp(dir + "/recording_control_mini.tvcrec");
    const unsigned char header[] = {
        0x54,0x56,0x43,0x52,0x45,0x43,0x52,0x44, 1,0,0,0,0xc8,0x94,0xfa,0xad,
        0,0xca,0x9a,0x3b,0,0,0,0, 0,0x80,0xcf,0x9c,0x33,0x03,0x5b,0x18,
    };
    // Sequence 2's unmodified CRC ends in 0x3e; only that byte becomes 0xc1.
    const unsigned char crcs[6][4] = {
        {0x05,0x90,0x39,0x27}, {0xe2,0xec,0xdc,0x2b}, {0xcb,0x69,0xf3,0xc1},
        {0x2c,0x15,0x16,0x32}, {0x99,0x63,0xac,0x14}, {0x7e,0x1f,0x49,0x18},
    };
    std::vector<unsigned char> expected(header, header + 32);
    for (unsigned char n = 0; n < 6; ++n) {
        const unsigned char head[] = {0x90,0xeb,1,6,128,0,n,0,0,0};
        expected.insert(expected.end(), head, head + 10);
        expected.push_back(n);
        expected.insert(expected.end(), kControlPayload + 1, kControlPayload + 128);
        expected.insert(expected.end(), crcs[n], crcs[n] + 4);
    }
    CHECK(data.size() == 884 && data == expected); // includes the unrecovered payload
    CHECK(std::memcmp(data.data(), "TVCRECRD", 8) == 0);
    CHECK(wire::get_u16_le(data.data(), 8) == 1 && wire::get_u16_le(data.data(), 10) == 0);
    CHECK(wire::get_u32_le(data.data(), 12) == 0xadfa94c8u);
    CHECK(wire::get_i64_le(data.data(), 16) == 1000000000LL);
    CHECK(wire::get_i64_le(data.data(), 24) == 1755000000000000000LL);
    std::vector<telem::DecodedFrame> frames;
    const auto* body = data.data() + 32;
    const auto ctr = telem::decode_stream(body, data.size() - 32, frames);
    CHECK(frames.size() == 5 && ctr.frames_ok == 5);
    CHECK(ctr.crc_errors == 1 && ctr.resyncs == 1 && ctr.lost == 1 && ctr.skipped_bytes == 142);
    CHECK(ctr.version_mismatch == 0 && ctr.seq_discontinuities == 0);
    const std::uint32_t sequences[] = {0, 1, 3, 4, 5};
    for (std::size_t i = 0; i < frames.size(); ++i) {
        CHECK(frames[i].type == 6 && frames[i].seq == sequences[i] && frames[i].payload_len == 128);
        check_control_corpus_fields(body + frames[i].payload_off, frames[i].payload_len, sequences[i]);
    }
}

}  // namespace

int main(int argc, char** argv) {
    const std::string corpus_dir = (argc > 1) ? argv[1] : "tests/golden";
    test_integer_endian_helpers();
    test_f64_endian_bits();
    test_payload_schema_metadata();
    test_record_layouts();
    test_crc_known_answers();
    test_encode_frame_layout();
    test_decode_round_trip();
    test_gap_rules();
    test_truncation_and_corruption();
    test_golden_corpus(corpus_dir);
    test_header_layout();
    test_drain_counters();
    test_drain_known_answer_bytes();
    test_drain_output_decodes();
    test_drain_stop_after_concurrent_push();
    test_typed_payload_codecs();
    test_payload_flags_bits_and_counts();
    test_strict_datagrams_and_expanded_framing();
    test_new_standalone_corpus(corpus_dir);
    test_control_recording_corpus(corpus_dir);
    std::puts("wire_tests: ok");
    return 0;
}

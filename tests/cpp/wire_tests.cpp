// tests/cpp/wire_tests.cpp — codec unit tests. Plain main() + CHECK.
#include "../../src/telemetry.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
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

}  // namespace

int main(int argc, char** argv) {
    const std::string corpus_dir = (argc > 1) ? argv[1] : "tests/golden";
    test_crc_known_answers();
    test_encode_frame_layout();
    test_decode_round_trip();
    test_gap_rules();
    test_truncation_and_corruption();
    test_golden_corpus(corpus_dir);
    test_header_layout();
    test_drain_counters();
    test_drain_output_decodes();
    test_drain_stop_after_concurrent_push();
    std::puts("wire_tests: ok");
    return 0;
}

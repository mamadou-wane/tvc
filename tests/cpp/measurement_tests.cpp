#include "../../src/loop_stats.hpp"
#include "../../src/alloc_guard.hpp"
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <cstring>
#include <vector>
#include "../../src/freerun_admission.hpp"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); std::exit(1); } } while (0)

std::array<unsigned char, 58> packet(std::uint64_t tick, double theta = 0) {
    std::array<unsigned char, 58> frame{};
    unsigned char payload[44];
    telem::payload::encode_sensor(payload,44,tick,1000,theta,0,1,0,0);
    telem::encode_frame(4,tick,payload,44,frame.data());
    return frame;
}

void classified_discard_ages() {
    freerun::Admission admission(10);
    stats::Distribution ages;
    CHECK(admission.begin_cycle(10));
    admission.receive(packet(8)); admission.receive(packet(9));
    const auto& first = admission.finish_cycle();
    CHECK(first.counts.superseded == 1 && first.discard_count == 1);
    ages.record_interval(first.discards[0].send_ns,3000);
    CHECK(admission.begin_cycle(11));
    admission.receive(packet(7));
    admission.receive(packet(10,std::numeric_limits<double>::quiet_NaN()));
    admission.receive(packet(16));
    const auto& second = admission.finish_cycle();
    CHECK(second.counts.old == 1 && second.counts.nonfinite == 1 && second.counts.skew_excess == 1);
    CHECK(second.discard_count == 3);
    for (unsigned i=0;i<second.discard_count;++i) ages.record_interval(second.discards[i].send_ns,5000);
    CHECK(ages.count()==4 && ages.sum_ns()==14000 && admission.identities_hold());
}

int main(int argc, char** argv) {
    if (argc == 2 && std::strcmp(argv[1], "--statistics-fixtures") == 0) {
        std::vector<std::vector<std::int64_t>> cases = {
            {}, {0}, {1, 1023, 1024, 2047, 2048, 2049, 4095, 4096},
            {999423}, {999424}, {999999}, {1000000},
            {1999999, 2000000, 2000001, 3000000}, {10000000000LL}};
        for (unsigned count : {499u, 500u, 501u, 1000u}) {
            cases.emplace_back(count, 1);
            cases.back().back() = 3000000;
        }
        for (unsigned shift = 11; shift <= 33; ++shift) {
            const std::int64_t value = 1LL << shift;
            cases.push_back({value - 1, value, value + 1});
        }
        std::puts("[");
        bool comma = false;
        for (const auto& values : cases) {
            stats::Distribution distribution;
            for (auto value : values) distribution.record_interval(0, value);
            std::printf("%s%s", comma ? ",\n" : "", distribution.json().c_str());
            comma = true;
        }
        std::puts("\n]");
        return 0;
    }
    classified_discard_ages();
    stats::Distribution served, discard;
    CHECK(served.count() == 0 && served.sum_ns() == 0);
    guard::set_mode(guard::Mode::Abort);
    {
        guard::Cycle cycle;
        served.record_interval(1000, 3500);  // post-send minus sensor send
        served.record_interval(1000, 5000);
        discard.record_interval(2000, 3000);
        discard.record_interval(2000, 4000);
        discard.record_interval(2000, 5000);
        discard.record_interval(2000, 6000);
    }
    guard::set_mode(guard::Mode::Off);
    CHECK(served.count() == 2 && served.sum_ns() == 6500);
    CHECK(discard.count() == 4 && discard.sum_ns() == 10000);
    CHECK(served.dropped() == 0);
    served.record_interval(3000, 2000);
    CHECK(served.count() == 3 && served.dropped() == 1);
    served.record_interval(0, 11000000000LL);
    CHECK(served.count() == 4 && served.dropped() == 2);
    std::puts("measurement tests passed");
}

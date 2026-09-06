#pragma once

#include <cstdint>

struct Observation {
    std::uint64_t tick;
    double theta;
    double omega;
    bool valid;
};

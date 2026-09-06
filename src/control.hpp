#pragma once

#include "model_types.hpp"

namespace control {

// Construction routes, not just decimal values, are part of the bit contract.
inline constexpr double KP = 3.277;
inline constexpr double KI = 7.68;
inline constexpr double KD = 0.309;
inline constexpr double DT = 1.0 / 500.0;
inline constexpr double KI_DT = KI * DT;
inline constexpr double BETA_D = 1.0 / 3.0;
inline constexpr double DELTA_MAX = 0.12;
inline constexpr double I_MAX = DELTA_MAX;
inline constexpr double THETA_SP = +0.0;
inline constexpr double NEG_DELTA_MAX = -DELTA_MAX;
inline constexpr double NEG_I_MAX = -I_MAX;

struct State {
    double i_state;
    double d_prev;
    double last_delta;
};

State initial() noexcept;

// The caller supplies an already-admitted, fresh, finite observation.
double step(State& state, const Observation& obs) noexcept;

}  // namespace control

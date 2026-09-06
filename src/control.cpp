#include "control.hpp"

namespace control {

State initial() noexcept {
    return {+0.0, +0.0, +0.0};
}

double step(State& state, const Observation& obs) noexcept {
    const double e = obs.theta - THETA_SP;

    const double d = state.d_prev + BETA_D * (
        obs.omega - state.d_prev
    );

    const double i_unclamped = state.i_state + KI_DT * e;
    double i_cand = i_unclamped;

    if (i_cand > I_MAX)
        i_cand = I_MAX;
    if (i_cand < NEG_I_MAX)
        i_cand = NEG_I_MAX;

    const double u = (KP * e + i_cand) + KD * d;

    const bool sat_hi = u > DELTA_MAX;
    const bool sat_lo = u < NEG_DELTA_MAX;

    double delta;
    if (sat_hi)
        delta = DELTA_MAX;
    else if (sat_lo)
        delta = NEG_DELTA_MAX;
    else
        delta = u;

    const bool hold = (sat_hi && e > 0.0) || (
        sat_lo && e < 0.0
    );

    double i_next;
    if (hold)
        i_next = state.i_state;
    else
        i_next = i_cand;

    state.i_state = i_next;
    state.d_prev = d;
    state.last_delta = delta;
    return delta;
}

}  // namespace control

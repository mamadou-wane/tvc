"""Fixed PID arithmetic; admission and cycle policy belong to the caller."""

from typing import NamedTuple

from sim.types import Observation


KP = 3.277
KI = 7.68
KD = 0.309
DT = 1.0 / 500.0
KI_DT = KI * DT
BETA_D = 1.0 / 3.0
DELTA_MAX = 0.12
I_MAX = DELTA_MAX
THETA_SP = +0.0
NEG_DELTA_MAX = -DELTA_MAX
NEG_I_MAX = -I_MAX


class ControlState(NamedTuple):
    i_state: float
    d_prev: float
    last_delta: float


def initial() -> ControlState:
    return ControlState(+0.0, +0.0, +0.0)


def step(
    state: ControlState,
    observation: Observation,
) -> tuple[float, ControlState]:
    """Advance once for an already-admitted, fresh, finite observation."""
    e = observation.theta - THETA_SP

    d = state.d_prev + BETA_D * (
        observation.omega - state.d_prev
    )

    i_unclamped = state.i_state + KI_DT * e
    i_cand = i_unclamped

    if i_cand > I_MAX:
        i_cand = I_MAX
    if i_cand < NEG_I_MAX:
        i_cand = NEG_I_MAX

    u = (KP * e + i_cand) + KD * d

    sat_hi = u > DELTA_MAX
    sat_lo = u < NEG_DELTA_MAX

    if sat_hi:
        delta = DELTA_MAX
    elif sat_lo:
        delta = NEG_DELTA_MAX
    else:
        delta = u

    hold = (sat_hi and e > 0.0) or (
        sat_lo and e < 0.0
    )

    if hold:
        i_next = state.i_state
    else:
        i_next = i_cand

    next_state = ControlState(
        i_state=i_next,
        d_prev=d,
        last_delta=delta,
    )

    return delta, next_state

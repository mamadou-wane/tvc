from sim.types import ActuatorState


DELTA_MAX = 0.12


def initial() -> ActuatorState:
    return ActuatorState(applied=0.0)


def step(state: ActuatorState, arriving: float | None) -> ActuatorState:
    if arriving is None:
        return state
    applied = arriving
    if applied > DELTA_MAX:
        applied = DELTA_MAX
    if applied < -DELTA_MAX:
        applied = -DELTA_MAX
    return ActuatorState(applied=applied)

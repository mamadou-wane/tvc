from sim.types import Observation, TruthState


def observe(tick: int, truth: TruthState) -> Observation:
    return Observation(tick=tick, theta=truth.theta, omega=truth.omega, valid=True)

from typing import NamedTuple


class TruthState(NamedTuple):
    theta: float
    omega: float


class Observation(NamedTuple):
    tick: int
    theta: float
    omega: float
    valid: bool


class ActuatorState(NamedTuple):
    applied: float


class Environment(NamedTuple):
    k_a: float


class Disturbance(NamedTuple):
    tau_d: float

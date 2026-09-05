from sim.fixmath import psin
from sim.types import ActuatorState, Disturbance, Environment, TruthState


F = 60.0
L = 0.45
FL = 27.0
J = 0.36


def step(
    truth: TruthState,
    actuator: ActuatorState,
    environment: Environment,
    disturbance: Disturbance,
    dt: float,
) -> TruthState:
    tau = (
        environment.k_a * truth.theta
        - FL * psin(actuator.applied)
        + disturbance.tau_d
    )
    omega_next = truth.omega + (tau / J) * dt
    theta_next = truth.theta + omega_next * dt
    return TruthState(theta=theta_next, omega=omega_next)

import struct
import unittest

from sim import fixmath
from sim.types import ActuatorState, Disturbance, Environment, Observation, TruthState


DT = 1.0 / 500.0


def double_bits(value):
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def double_from_bits(bits):
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


class FixedMathTests(unittest.TestCase):
    def test_polynomial_coefficients_have_exact_binary64_values(self):
        self.assertEqual(double_bits(fixmath.C1), 0xBFC5555555555555)
        self.assertEqual(double_bits(fixmath.C2), 0x3F81111111111111)
        self.assertEqual(double_bits(fixmath.C3), 0xBF2A01A01A01A01A)

    def test_psin_known_answers_preserve_binary64_bits(self):
        cases = (
            (0.0, 0x0000000000000000),
            (-0.0, 0x8000000000000000),
            (0.12, 0x3FBEA5758F3CE1CC),
            (-0.12, 0xBFBEA5758F3CE1CC),
            (0.0625, 0x3FAFFAAAEEED4ED5),
            (-0.0625, 0xBFAFFAAAEEED4ED5),
        )
        for value, expected_bits in cases:
            with self.subTest(input_bits=double_bits(value)):
                self.assertEqual(double_bits(fixmath.psin(value)), expected_bits)


class PlantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sim import plant

        cls.plant = plant

    def test_constants_have_exact_binary64_values(self):
        self.assertEqual(double_bits(self.plant.F), 0x404E000000000000)
        self.assertEqual(double_bits(self.plant.L), 0x3FDCCCCCCCCCCCCD)
        self.assertEqual(double_bits(self.plant.FL), 0x403B000000000000)
        self.assertEqual(double_bits(self.plant.J), 0x3FD70A3D70A3D70A)
        self.assertEqual(double_bits(DT), 0x3F60624DD2F1A9FC)

    def test_one_step_known_answers(self):
        cases = (
            ("zero equilibrium", (0.0, 0.0, 0.0, 0.0),
             (0x0000000000000000, 0x0000000000000000)),
            ("positive aerodynamic moment", (0.02, 0.0, 0.0, 0.0),
             (0x3F947B677F6B1A2A, 0x3F50624DD2F1A9FC)),
            ("positive actuator correction", (0.0, 0.0, 0.12, 0.0),
             (0xBF02D440095CB3B1, 0xBF9263468924877B)),
            ("negative actuator symmetry", (0.0, 0.0, -0.12, 0.0),
             (0x3F02D440095CB3B1, 0x3F9263468924877B)),
            ("positive disturbance", (0.0, 0.0, 0.0, 0.09),
             (0x3EB0C6F7A0B5ED8D, 0x3F40624DD2F1A9FC)),
            ("combined nontrivial", (0.03125, -0.015625, 0.0625, -0.03125),
             (0x3F9FF39FCA12EA57, 0xBF982BE9530E4DB2)),
        )
        for name, inputs, expected_bits in cases:
            theta, omega, applied, tau_d = inputs
            with self.subTest(case=name):
                result = self.plant.step(
                    TruthState(theta, omega), ActuatorState(applied),
                    Environment(9.0), Disturbance(tau_d), DT,
                )
                self.assertIsInstance(result, TruthState)
                self.assertEqual(
                    (double_bits(result.theta), double_bits(result.omega)),
                    expected_bits,
                )

    def test_299_step_open_loop_recurrence(self):
        truth = TruthState(0.02, 0.0)
        for _ in range(299):
            truth = self.plant.step(
                truth, ActuatorState(0.0), Environment(9.0), Disturbance(0.0), DT,
            )
        self.assertEqual(double_bits(truth.theta), 0x3FC9A508FFA293EA)
        self.assertEqual(double_bits(truth.omega), 0x3FEFBC5FE13729A5)

    def test_saturation_and_hold_trajectory_known_answers(self):
        from sim import actuator

        truth = TruthState(0.01, 0.0)
        applied = actuator.step(actuator.initial(), 1.0)
        self.assertEqual(double_bits(applied.applied), 0x3FBEB851EB851EB8)
        truth = self.plant.step(
            truth, applied, Environment(9.0), Disturbance(0.0), DT,
        )
        self.assertEqual(double_bits(truth.theta), 0x3F8468933F61BD77)
        self.assertEqual(double_bits(truth.omega), 0xBF91E0341A8CFA2B)

        held = actuator.step(applied, None)
        self.assertIs(held, applied)
        self.assertEqual(double_bits(held.applied), 0x3FBEB851EB851EB8)
        truth = self.plant.step(
            truth, held, Environment(9.0), Disturbance(0.0), DT,
        )
        self.assertEqual(double_bits(truth.theta), 0x3F8443F6B6D2ADA1)
        self.assertEqual(double_bits(truth.omega), 0xBFA1E06EADDABB42)


class ActuatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sim import actuator

        cls.actuator = actuator

    def test_initial_applied_angle_is_positive_zero(self):
        state = self.actuator.initial()
        self.assertIsInstance(state, ActuatorState)
        self.assertEqual(double_bits(state.applied), 0x0000000000000000)
        self.assertEqual(double_bits(self.actuator.DELTA_MAX), 0x3FBEB851EB851EB8)

    def test_arrivals_clamp_only_at_the_stops(self):
        cases = (
            (1.0, 0x3FBEB851EB851EB8),
            (-1.0, 0xBFBEB851EB851EB8),
            (0.12, 0x3FBEB851EB851EB8),
            (-0.12, 0xBFBEB851EB851EB8),
            (-0.0, 0x8000000000000000),
            (0.0625, 0x3FB0000000000000),
            (-0.0625, 0xBFB0000000000000),
            (float("inf"), 0x3FBEB851EB851EB8),
            (-float("inf"), 0xBFBEB851EB851EB8),
            (double_from_bits(0x7FF8000000001234), 0x7FF8000000001234),
        )
        for arriving, expected_bits in cases:
            with self.subTest(arriving_bits=double_bits(arriving)):
                result = self.actuator.step(ActuatorState(-0.0625), arriving)
                self.assertIsInstance(result, ActuatorState)
                self.assertEqual(double_bits(result.applied), expected_bits)

    def test_hold_returns_the_same_state_without_normalization(self):
        for bits in (0x8000000000000000, 0x7FF8000000001234, 0x3FB0000000000000):
            with self.subTest(bits=bits):
                state = ActuatorState(double_from_bits(bits))
                held = self.actuator.step(state, None)
                self.assertIs(held, state)
                self.assertEqual(double_bits(held.applied), bits)


class SensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sim import sensor

        cls.sensor = sensor

    def test_observation_preserves_truth_bits_tick_and_initial_validity(self):
        cases = (
            (17, 0x8000000000000000, 0x7FF8000000001234),
            (23, 0x3FA0000000000000, 0xBF90000000000000),
            (0, 0x7FF8000000001234, 0x8000000000000000),
        )
        for tick, theta_bits, omega_bits in cases:
            with self.subTest(tick=tick):
                truth = TruthState(double_from_bits(theta_bits), double_from_bits(omega_bits))
                result = self.sensor.observe(tick, truth)
                self.assertIsInstance(result, Observation)
                self.assertEqual(result.tick, tick)
                self.assertIs(result.valid, True)
                self.assertEqual(double_bits(result.theta), theta_bits)
                self.assertEqual(double_bits(result.omega), omega_bits)


class EnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sim import environment

        cls.environment = environment

    def test_fixed_environment_has_the_declared_stiffness(self):
        result = self.environment.fixed()
        self.assertIsInstance(result, Environment)
        self.assertEqual(double_bits(result.k_a), 0x4022000000000000)

    def test_fixed_environment_accepts_no_configuration(self):
        with self.assertRaises(TypeError):
            self.environment.fixed(k_a=18.0)


if __name__ == "__main__":
    unittest.main()

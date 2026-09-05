import ast
import importlib
import struct
import unittest
from pathlib import Path
from typing import get_type_hints

from sim import fixmath, rng
from sim.types import ActuatorState, Disturbance, Environment, Observation, TruthState


ROOT = Path(__file__).resolve().parents[2]
SIM_ROOT = ROOT / "sim"


def double_bits(value):
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def double_from_bits(bits):
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


def tvc_imports(filename):
    source_path = SIM_ROOT / filename
    if not source_path.is_file():
        raise AssertionError(f"missing required kernel module: {source_path}")
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sim" or alias.name.startswith("sim."):
                    imported.add(alias.name)
                if alias.name == "ground" or alias.name.startswith("ground."):
                    imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                name = "sim" if not node.module else f"sim.{node.module}"
            else:
                name = node.module or ""
            if name == "sim":
                imported.update(f"sim.{alias.name}" for alias in node.names)
            elif name.startswith("sim."):
                imported.add(name)
            if name == "ground" or name.startswith("ground."):
                imported.add(name)
    return imported


class ModelTypeTests(unittest.TestCase):
    def test_named_tuple_field_order_and_annotations(self):
        contracts = (
            (TruthState, ("theta", "omega"), (float, float)),
            (Observation, ("tick", "theta", "omega", "valid"), (int, float, float, bool)),
            (ActuatorState, ("applied",), (float,)),
            (Environment, ("k_a",), (float,)),
            (Disturbance, ("tau_d",), (float,)),
        )
        for model_type, fields, annotations in contracts:
            with self.subTest(model_type=model_type.__name__):
                self.assertTrue(issubclass(model_type, tuple))
                self.assertEqual(model_type._fields, fields)
                hints = get_type_hints(model_type)
                self.assertEqual(tuple(hints), fields)
                self.assertEqual(tuple(hints.values()), annotations)

    def test_named_tuples_are_immutable(self):
        values = (
            (TruthState(0.1, 0.2), "theta"),
            (Observation(3, 0.1, 0.2, True), "tick"),
            (ActuatorState(0.1), "applied"),
            (Environment(9.0), "k_a"),
            (Disturbance(0.1), "tau_d"),
        )
        for value, field in values:
            with self.subTest(model_type=type(value).__name__):
                with self.assertRaises(AttributeError):
                    setattr(value, field, 0)

    def test_construction_retains_float_representations(self):
        negative_zero = double_from_bits(0x8000000000000000)
        quiet_nan = double_from_bits(0x7FF8000000001234)

        truth = TruthState(negative_zero, quiet_nan)
        observation = Observation(17, negative_zero, quiet_nan, False)
        actuator = ActuatorState(negative_zero)
        environment = Environment(negative_zero)
        disturbance = Disturbance(quiet_nan)

        self.assertEqual(double_bits(truth.theta), 0x8000000000000000)
        self.assertEqual(double_bits(truth.omega), 0x7FF8000000001234)
        self.assertEqual(observation.tick, 17)
        self.assertFalse(observation.valid)
        self.assertEqual(double_bits(observation.theta), 0x8000000000000000)
        self.assertEqual(double_bits(observation.omega), 0x7FF8000000001234)
        self.assertEqual(double_bits(actuator.applied), 0x8000000000000000)
        self.assertEqual(double_bits(environment.k_a), 0x8000000000000000)
        self.assertEqual(double_bits(disturbance.tau_d), 0x7FF8000000001234)


class SimulationLayeringTests(unittest.TestCase):
    def test_kernel_dependencies_follow_the_declared_graph(self):
        allowed = {
            "__init__.py": set(),
            "types.py": set(),
            "rng.py": set(),
            "fixmath.py": set(),
            "actuator.py": {"sim.types"},
            "sensor.py": {"sim.types"},
            "environment.py": {"sim.types"},
            "plant.py": {"sim.types", "sim.fixmath"},
        }
        for filename, dependencies in allowed.items():
            with self.subTest(filename=filename):
                self.assertLessEqual(tvc_imports(filename), dependencies)

    def test_real_public_apis_import_and_execute(self):
        truth = TruthState(theta=-0.0, omega=0.25)
        self.assertEqual(double_bits(truth.theta), 0x8000000000000000)
        self.assertEqual(double_bits(fixmath.psin(0.0625)), 0x3FAFFAAAEEED4ED5)

        start = rng.stream_state(1, "link.loss.up")
        self.assertEqual(start, 0x910A2DEC89025CC1)
        stream = rng.SplitMix64(start)
        self.assertEqual(stream.next_u64(), 0x5E41AB087439611E)
        self.assertEqual(
            double_bits(stream.next_double()),
            double_bits(float.fromhex("0x1.e31ad9d27ad9ep-1")),
        )

    def test_model_public_apis_import_and_execute(self):
        for name in ("actuator", "sensor", "environment", "plant"):
            with self.subTest(module=name):
                module = importlib.import_module(f"sim.{name}")
                if name == "actuator":
                    initial = module.initial()
                    self.assertEqual(double_bits(initial.applied), 0x0000000000000000)
                    self.assertIs(module.step(initial, None), initial)
                elif name == "sensor":
                    observation = module.observe(7, TruthState(0.0, 0.25))
                    self.assertEqual(observation, Observation(7, 0.0, 0.25, True))
                elif name == "environment":
                    self.assertEqual(module.fixed(), Environment(9.0))
                else:
                    truth = module.step(
                        TruthState(0.02, 0.0), ActuatorState(0.0),
                        Environment(9.0), Disturbance(0.0), 1.0 / 500.0,
                    )
                    self.assertEqual(double_bits(truth.theta), 0x3F947B677F6B1A2A)
                    self.assertEqual(double_bits(truth.omega), 0x3F50624DD2F1A9FC)


if __name__ == "__main__":
    unittest.main()

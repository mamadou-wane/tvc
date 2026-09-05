import ast
import io
import json
import struct
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from typing import get_type_hints
from unittest.mock import patch

from sim.types import Disturbance, Environment, TruthState


ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "sim" / "scenarios"
KEYS = (
    "ticks", "theta0", "omega0", "gusts", "loss_up", "loss_down",
    "loss_start_tick", "blackout_up", "blackout_down", "commands", "auto_arm",
)
# Independent input literals, never derived from the files or loader.
CANONICAL = {
    "S1-hold": (10000, 0.02, 0.0, (), 0.0, 0.0, 0, None, None, (), True),
    "S2-gust": (10000, 0.05, 0.5,
                ((2000, 2500, 0.20), (4500, 4750, -0.30), (7500, 7550, 0.40)),
                0.0, 0.0, 0, None, None, (), True),
    "S3-kick": (5000, 0.15, 0.0, (), 0.0, 0.0, 0, None, None, (), True),
    "S4-open": (300, 0.02, 0.0, (), 0.0, 0.0, 0, None, None, (), False),
    "S5-overgust": (5000, 0.0, 0.0, ((1000, 1100, 0.45),),
                    0.0, 0.0, 0, None, None, (), True),
    "S6-blackout": (2000, 0.02, 0.0, (), 0.0, 0.0, 0, (1000, 1030), None, (), True),
    "S7-abort": (2000, 0.02, 0.0, (), 0.0, 0.0, 0, None, None, ((1000, "ABORT"),), True),
    "demo-loss30": (3000, 0.05, 0.0, (), 0.30, 0.30, 200, None, None,
                    ((0, "ARM"), (60, "LAUNCH")), False),
}
INITIAL_BITS = {
    "S1-hold": (0x3F947AE147AE147B, 0x0000000000000000),
    "S2-gust": (0x3FA999999999999A, 0x3FE0000000000000),
    "S3-kick": (0x3FC3333333333333, 0x0000000000000000),
    "S4-open": (0x3F947AE147AE147B, 0x0000000000000000),
    "S5-overgust": (0x0000000000000000, 0x0000000000000000),
    "S6-blackout": (0x3F947AE147AE147B, 0x0000000000000000),
    "S7-abort": (0x3F947AE147AE147B, 0x0000000000000000),
    "demo-loss30": (0x3FA999999999999A, 0x0000000000000000),
}


def bits(value):
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def document(**changes):
    result = {
        "ticks": 10, "theta0": 0.0, "omega0": 0.0, "gusts": [],
        "loss_up": 0.0, "loss_down": 0.0, "loss_start_tick": 0,
        "blackout_up": None, "blackout_down": None, "commands": [], "auto_arm": True,
    }
    result.update(changes)
    return result


class CanonicalFilesTests(unittest.TestCase):
    def test_exact_canonical_file_membership(self):
        self.assertTrue(SCENARIOS.is_dir(), "missing canonical scenario directory")
        self.assertEqual({p.name for p in SCENARIOS.iterdir()}, {f"{name}.json" for name in CANONICAL})

    def test_json_objects_match_independent_inputs(self):
        for name, values in CANONICAL.items():
            with self.subTest(name=name):
                expected = dict(zip(KEYS, values))
                expected["gusts"] = [list(gust) for gust in values[3]]
                for key in ("blackout_up", "blackout_down"):
                    if expected[key] is not None:
                        expected[key] = list(expected[key])
                expected["commands"] = [{"tick": tick, "opcode": opcode} for tick, opcode in values[9]]
                actual = json.loads((SCENARIOS / f"{name}.json").read_text())
                self.assertEqual(actual, expected)


class ScenarioTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sim import scenario

        cls.scenario = scenario

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def load_text(self, text, name="case.json"):
        path = self.directory / name
        path.write_text(text, encoding="utf-8")
        return self.scenario.load(path)

    def load_document(self, value):
        return self.load_text(json.dumps(value))


class ScenarioLoadTests(ScenarioTestCase):
    def test_canonical_values_ids_and_bits(self):
        for name, values in CANONICAL.items():
            with self.subTest(name=name):
                actual = self.scenario.load(SCENARIOS / f"{name}.json")
                expected = (name, values[0], TruthState(values[1], values[2]), *values[3:])
                self.assertEqual(actual, expected)
                self.assertIsInstance(actual, self.scenario.Scenario)
                self.assertIsInstance(actual.initial, TruthState)
                self.assertEqual((bits(actual.initial.theta), bits(actual.initial.omega)), INITIAL_BITS[name])
                self.assertEqual(bits(actual.loss_up), bits(values[4]))
                self.assertEqual(bits(actual.loss_down), bits(values[5]))
                for actual_gust, expected_gust in zip(actual.gusts, values[3]):
                    self.assertEqual(bits(actual_gust[2]), bits(expected_gust[2]))

    def test_named_tuple_shape_and_nested_immutability(self):
        fields = ("id", "ticks", "initial", "gusts", "loss_up", "loss_down",
                  "loss_start_tick", "blackout_up", "blackout_down", "commands", "auto_arm")
        annotations = (str, int, TruthState, tuple[tuple[int, int, float], ...],
                       float, float, int, tuple[int, int] | None,
                       tuple[int, int] | None, tuple[tuple[int, str], ...], bool)
        self.assertEqual(self.scenario.Scenario._fields, fields)
        self.assertEqual(tuple(get_type_hints(self.scenario.Scenario).values()), annotations)
        value = self.load_document(document(
            gusts=[[0, 2, 0.25]], blackout_up=[1, 3], blackout_down=[2, 4],
            commands=[{"tick": 0, "opcode": "ABORT"}],
        ))
        self.assertIsInstance(value, tuple)
        with self.assertRaises(AttributeError):
            value.ticks = 20
        for nested in (value.initial, value.gusts, value.gusts[0], value.blackout_up,
                       value.blackout_down, value.commands, value.commands[0]):
            self.assertIsInstance(nested, tuple)
            with self.assertRaises(TypeError):
                nested[0] = None

    def test_filename_stem_and_string_path(self):
        path = self.directory / "personal.case.json"
        path.write_text(json.dumps(document()))
        self.assertEqual(self.scenario.load(str(path)).id, "personal.case")

    def test_signed_zero_and_integer_float_inputs(self):
        value = self.load_document(document(
            theta0=-0.0, omega0=-0.0, loss_up=-0.0, loss_down=-0.0,
            gusts=[[0, 1, -0.0]],
        ))
        for number in (value.initial.theta, value.initial.omega, value.loss_up,
                       value.loss_down, value.gusts[0][2]):
            self.assertEqual(bits(number), 0x8000000000000000)
        value = self.load_document(document(
            theta0=1, omega0=-2, loss_up=0, loss_down=1, gusts=[[0, 1, 1]],
        ))
        for number in (value.initial.theta, value.initial.omega, value.loss_up,
                       value.loss_down, value.gusts[0][2]):
            self.assertIs(type(number), float)
        self.assertEqual(value.initial, TruthState(1.0, -2.0))

    def test_all_keys_are_required_and_extra_metadata_is_rejected(self):
        for key in KEYS:
            invalid = document()
            del invalid[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.load_document(invalid)
        for key in ("id", "name", "seed", "delay_ticks", "outcome", "termination", "unknown"):
            with self.subTest(extra=key), self.assertRaises(ValueError):
                self.load_document(document(**{key: 1}))

    def test_duplicate_json_keys_are_rejected_at_both_object_levels(self):
        text = json.dumps(document())
        for duplicate in ('"ticks": 10', '"ticks": 11', '"theta0": -0.0'):
            with self.subTest(duplicate=duplicate), self.assertRaises(ValueError):
                self.load_text(text[:-1] + ", " + duplicate + "}")
        for command in ('{"tick":0,"tick":1,"opcode":"ARM"}',
                        '{"tick":0,"opcode":"ARM","opcode":"ABORT"}'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.load_text(text.replace('"commands": []', '"commands": [' + command + ']'))

    def test_invalid_json_or_top_level_type_is_rejected(self):
        for text in ("", "{", "[]", "null", "true", "0", '"scenario"'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.load_text(text)

    def test_filesystem_errors_remain_os_errors(self):
        with self.assertRaises(FileNotFoundError):
            self.scenario.load(self.directory / "absent.json")
        with self.assertRaises(OSError):
            self.scenario.load(self.directory)

    def test_horizon_and_loss_start_tick_validation(self):
        for invalid in (0, -1, True, False, 10.0, "10", None, [], {}):
            with self.subTest(ticks=invalid), self.assertRaises(ValueError):
                self.load_document(document(ticks=invalid))
        for invalid in (-1, 11, True, False, 0.0, "0", None, [], {}):
            with self.subTest(loss_start=invalid), self.assertRaises(ValueError):
                self.load_document(document(loss_start_tick=invalid))
        for start in (0, 10):
            self.assertEqual(self.load_document(document(loss_start_tick=start)).loss_start_tick, start)
        self.assertEqual(self.load_document(document(ticks=1)).ticks, 1)

    def test_float_fields_reject_invalid_types_and_nonfinite_values(self):
        invalids = (True, False, None, "0.1", [], {}, float("nan"),
                    float("inf"), -float("inf"), 10**400)
        for field in ("theta0", "omega0", "loss_up", "loss_down", "alpha_g"):
            for invalid in invalids:
                changes = {"gusts": [[0, 1, invalid]]} if field == "alpha_g" else {field: invalid}
                with self.subTest(field=field, invalid=repr(invalid)), self.assertRaises(ValueError):
                    self.load_document(document(**changes))
        with self.assertRaises(ValueError):
            self.load_text(json.dumps(document()).replace('"theta0": 0.0', '"theta0": 1e400'))

    def test_probabilities_and_auto_arm_have_no_coercion_defaults(self):
        for field in ("loss_up", "loss_down"):
            for invalid in (-0.01, 1.01):
                with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                    self.load_document(document(**{field: invalid}))
        for invalid in (0, 1, "true", None, [], {}):
            with self.subTest(auto_arm=invalid), self.assertRaises(ValueError):
                self.load_document(document(auto_arm=invalid))

    def test_schedule_container_and_element_shapes(self):
        for field in ("gusts", "commands"):
            for invalid in (None, False, 0, "", {}):
                with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                    self.load_document(document(**{field: invalid}))
        for gust in (None, False, {}, "abc", [], [0, 1], [0, 1, 0.2, 4]):
            with self.subTest(gust=gust), self.assertRaises(ValueError):
                self.load_document(document(gusts=[gust]))
        for field in ("blackout_up", "blackout_down"):
            for invalid in (False, 0, "01", {}, [], [0], [0, 1, 2]):
                with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                    self.load_document(document(**{field: invalid}))

    def test_interval_bounds_and_integer_endpoints(self):
        invalids = ((-1, 1), (1, 1), (2, 1), (0, 11), (True, 2),
                    (0, False), (0.0, 1), (0, 1.0), ("0", 1), (0, None))
        for start, end in invalids:
            for field in ("gusts", "blackout_up", "blackout_down"):
                value = [[start, end, 0.25]] if field == "gusts" else [start, end]
                with self.subTest(field=field, start=start, end=end), self.assertRaises(ValueError):
                    self.load_document(document(**{field: value}))

    def test_gust_order_overlap_and_adjacency(self):
        for gusts in ([[4, 6, 0.2], [2, 4, 0.3]],
                      [[1, 4, 0.2], [3, 5, 0.3]],
                      [[1, 2, 0.2], [1, 2, 0.2]]):
            with self.subTest(gusts=gusts), self.assertRaises(ValueError):
                self.load_document(document(gusts=gusts))
        actual = self.load_document(document(gusts=[[0, 1, 0.25], [1, 10, -0.25]]))
        self.assertEqual(actual.gusts, ((0, 1, 0.25), (1, 10, -0.25)))

    def test_command_shape_opcode_and_tick_validation(self):
        invalids = [None, [], False, "ARM", {}, {"tick": 0}, {"opcode": "ARM"},
                    {"tick": 0, "opcode": "ARM", "effective_tick": 50}]
        invalids += [{"tick": 0, "opcode": op} for op in ("arm", "DISARM", "", 1, True, None, [])]
        invalids += [{"tick": tick, "opcode": "ARM"} for tick in (-1, 10, True, False, 0.0, "0", None)]
        for command in invalids:
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.load_document(document(commands=[command]))
        for ticks in ((2, 2), (3, 2)):
            with self.subTest(ticks=ticks), self.assertRaises(ValueError):
                self.load_document(document(commands=[{"tick": t, "opcode": "ARM"} for t in ticks]))

    def test_requests_do_not_validate_downstream_application_or_state(self):
        value = self.load_document(document(ticks=101, auto_arm=False, commands=[
            {"tick": 0, "opcode": "ABORT"},
            {"tick": 50, "opcode": "LAUNCH"},
            {"tick": 100, "opcode": "ARM"},
        ]))
        self.assertEqual(value.commands, ((0, "ABORT"), (50, "LAUNCH"), (100, "ARM")))
        self.assertEqual(self.scenario.command_at(value, 100), "ARM")


class ScenarioLookupTests(ScenarioTestCase):
    def test_gust_boundaries_and_independent_torque_bits(self):
        cases = (
            ("S2-gust", 2000, 2500, 0x3FFCCCCCCCCCCCCD),
            ("S2-gust", 4500, 4750, 0xC005999999999999),
            ("S2-gust", 7500, 7550, 0x400CCCCCCCCCCCCD),
            ("S5-overgust", 1000, 1100, 0x4010333333333333),
        )
        for name, start, end, torque_bits in cases:
            value = self.scenario.load(SCENARIOS / f"{name}.json")
            for tick, expected in ((start - 1, 0), (start, torque_bits),
                                   (end - 1, torque_bits), (end, 0)):
                with self.subTest(name=name, tick=tick):
                    result = self.scenario.disturbance_at(value, tick, Environment(9.0))
                    self.assertIsInstance(result, Disturbance)
                    self.assertEqual(bits(result.tau_d), expected)

    def test_disturbance_uses_supplied_environment_and_preserves_active_zero(self):
        value = self.load_document(document(gusts=[[0, 1, 0.25], [1, 2, -0.0]]))
        self.assertEqual(bits(self.scenario.disturbance_at(value, 0, Environment(4.0)).tau_d), 0x3FF0000000000000)
        self.assertEqual(bits(self.scenario.disturbance_at(value, 1, Environment(9.0)).tau_d), 0x8000000000000000)
        self.assertEqual(bits(self.scenario.disturbance_at(value, 2, Environment(9.0)).tau_d), 0)

    def test_command_requests_are_returned_only_at_their_ticks(self):
        cases = {
            "S7-abort": ((999, None), (1000, "ABORT"), (1001, None), (1050, None)),
            "demo-loss30": ((0, "ARM"), (1, None), (50, None), (59, None),
                            (60, "LAUNCH"), (61, None), (110, None)),
        }
        for name, probes in cases.items():
            value = self.scenario.load(SCENARIOS / f"{name}.json")
            for tick, expected in probes:
                with self.subTest(name=name, tick=tick):
                    self.assertEqual(self.scenario.command_at(value, tick), expected)

    def test_canonical_blackout_and_loss_start_boundaries(self):
        blackout = self.scenario.load(SCENARIOS / "S6-blackout.json")
        for tick, expected in ((999, None), (1000, True), (1029, True), (1030, None)):
            with self.subTest(tick=tick):
                self.assertIs(self.scenario.forced_drop_at(blackout, tick, direction="up"), expected)
                self.assertIsNone(self.scenario.forced_drop_at(blackout, tick, direction="down"))
        demo = self.scenario.load(SCENARIOS / "demo-loss30.json")
        for direction in ("up", "down"):
            for tick, expected in ((0, False), (199, False), (200, None), (2999, None)):
                with self.subTest(direction=direction, tick=tick):
                    self.assertIs(self.scenario.forced_drop_at(demo, tick, direction=direction), expected)

    def test_blackout_precedence_and_coincident_tick_zero_inputs(self):
        value = self.load_document(document(
            ticks=6, loss_start_tick=4, blackout_up=[1, 3], blackout_down=[0, 1],
            gusts=[[0, 1, 0.25]], commands=[{"tick": 0, "opcode": "ABORT"}],
        ))
        expected = {"up": (False, True, True, False, None, None),
                    "down": (True, False, False, False, None, None)}
        for direction, decisions in expected.items():
            for tick, decision in enumerate(decisions):
                with self.subTest(direction=direction, tick=tick):
                    self.assertIs(self.scenario.forced_drop_at(value, tick, direction=direction), decision)
        self.assertEqual(self.scenario.command_at(value, 0), "ABORT")
        self.assertEqual(bits(self.scenario.disturbance_at(value, 0, Environment(4.0)).tau_d), 0x3FF0000000000000)

    def test_invalid_helper_ticks_and_directions_raise_value_error(self):
        value = self.load_document(document())
        for tick in (-1, 10, True, False, 0.0, 1.5, "0", None):
            for name, args in (("disturbance_at", (Environment(9.0),)), ("command_at", ())):
                with self.subTest(name=name, tick=tick), self.assertRaises(ValueError):
                    getattr(self.scenario, name)(value, tick, *args)
            with self.subTest(name="forced_drop_at", tick=tick), self.assertRaises(ValueError):
                self.scenario.forced_drop_at(value, tick, direction="up")
        for direction in ("UP", "sideways", "", None, 0, True, []):
            with self.subTest(direction=direction), self.assertRaises(ValueError):
                self.scenario.forced_drop_at(value, 0, direction=direction)

    def test_tick_helpers_execute_without_file_io(self):
        value = self.load_document(document(
            gusts=[[0, 1, 0.25]], blackout_up=[0, 1], commands=[{"tick": 0, "opcode": "ARM"}],
        ))
        with ExitStack() as stack:
            stack.enter_context(patch("builtins.open", side_effect=AssertionError("helper performed I/O")))
            stack.enter_context(patch.object(io, "open", side_effect=AssertionError("helper performed I/O")))
            for method in ("open", "read_text", "read_bytes", "stat", "iterdir"):
                stack.enter_context(patch.object(Path, method, side_effect=AssertionError("helper performed I/O")))
            self.assertEqual(self.scenario.disturbance_at(value, 0, Environment(4.0)), Disturbance(1.0))
            self.assertEqual(self.scenario.command_at(value, 0), "ARM")
            self.assertIs(self.scenario.forced_drop_at(value, 0, direction="up"), True)


class ScenarioArchitectureTests(unittest.TestCase):
    def test_only_model_types_and_allowed_standard_library_dependencies(self):
        path = ROOT / "sim" / "scenario.py"
        self.assertTrue(path.is_file(), "missing sim.scenario module")
        tree = ast.parse(path.read_text())
        forbidden = {"asyncio", "concurrent", "datetime", "http", "multiprocessing",
                     "random", "selectors", "socket", "subprocess", "threading", "time", "urllib"}
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    module = "sim" + ("." + module if module else "")
                if module == "sim":
                    imports.extend("sim." + alias.name for alias in node.names)
                else:
                    imports.append(module)
            elif isinstance(node, ast.Call):
                called = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else "")
                self.assertNotIn(called, {"__import__", "system", "popen", "fork", "forkpty", "execv", "execve"})
        for imported in imports:
            with self.subTest(imported=imported):
                root = imported.split(".", 1)[0]
                self.assertNotIn(root, forbidden)
                if root == "sim":
                    self.assertEqual(imported, "sim.types")
                else:
                    self.assertIn(root, sys.stdlib_module_names)


if __name__ == "__main__":
    unittest.main()

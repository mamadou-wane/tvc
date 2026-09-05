import ast
import importlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import get_type_hints

from sim.types import Observation


SOURCE = Path(__file__).resolve().parents[2] / "sim" / "control_ref.py"

CONSTANT_BITS = {
    "KP": 0x400a374bc6a7ef9e,
    "KI": 0x401eb851eb851eb8,
    "KD": 0x3fd3c6a7ef9db22d,
    "DT": 0x3f60624dd2f1a9fc,
    "KI_DT": 0x3f8f75104d551d69,
    "BETA_D": 0x3fd5555555555555,
    "DELTA_MAX": 0x3fbeb851eb851eb8,
    "I_MAX": 0x3fbeb851eb851eb8,
    "THETA_SP": 0x0000000000000000,
}

PACKED_CONSTANTS = bytes.fromhex(
    "9eefa7c64b370a40691d554d10758f3f2db29defa7c6d33f555555555555d53f"
    "b81e85eb51b8be3fb81e85eb51b8be3ffca9f1d24d62603f"
)

# Independent literal inputs/results, not plant trajectories or computed oracles.
# Each vector is (id, (I, D, last), (theta, omega), (delta, next I, D, last)).
VECTORS = (
    ("V01",
     (0x0000000000000000, 0x0000000000000000, 0x0000000000000000),
     (0x0000000000000000, 0x0000000000000000),
     (0x0000000000000000, 0x0000000000000000, 0x0000000000000000, 0x0000000000000000)),
    ("V02",
     (0xbf2f75104d551d69, 0x0000000000000000, 0x3fb0000000000000),
     (0x3f90000000000000, 0x0000000000000000),
     (0x3faa374bc6a7ef9e, 0x0000000000000000, 0x0000000000000000, 0x3faa374bc6a7ef9e)),
    ("V03",
     (0x0000000000000000, 0x3fd0000000000000, 0x3fb0000000000000),
     (0x3f80000000000000, 0xbfc0000000000000),
     (0x3fb079042d8c2a45, 0x3f1f75104d551d69, 0x3fc0000000000000, 0x3fb079042d8c2a45)),
    ("V04",
     (0xbfa0000000000000, 0x3fb0000000000000, 0x3fb0000000000000),
     (0xbfb0000000000000, 0xbfe0000000000000),
     (0xbfbeb851eb851eb8, 0xbfa0000000000000, 0xbfc0000000000000, 0xbfbeb851eb851eb8)),
    ("V05",
     (0x3fbeb851eb851eb8, 0x0000000000000000, 0x3fbeb851eb851eb8),
     (0xbf90000000000000, 0x3ff8000000000000),
     (0x3fbeb851eb851eb8, 0x3fbea897635e7429, 0x3fe0000000000000, 0x3fbeb851eb851eb8)),
    ("V06",
     (0x3fbeb851eb851eb8, 0xbfc8000000000000, 0x3fa0000000000000),
     (0x3f90000000000000, 0xbfc8000000000000),
     (0x3fbcfef9db22d0e6, 0x3fbeb851eb851eb8, 0xbfc8000000000000, 0x3fbcfef9db22d0e6)),
    ("V07",
     (0xbfbeb851eb851eb8, 0x3fc8000000000000, 0xbfa0000000000000),
     (0xbf90000000000000, 0x3fc8000000000000),
     (0xbfbcfef9db22d0e6, 0xbfbeb851eb851eb8, 0x3fc8000000000000, 0xbfbcfef9db22d0e6)),
    ("V08",
     (0x3fb18cf1800a7c59, 0x0000000000000000, 0x0000000000000000),
     (0x3f90000000000000, 0x0000000000000000),
     (0x3fbeb851eb851eb7, 0x3fb19cac083126e8, 0x0000000000000000, 0x3fbeb851eb851eb7)),
    ("V09",
     (0x3fb18cf1800a7c5a, 0x0000000000000000, 0x0000000000000000),
     (0x3f90000000000000, 0x0000000000000000),
     (0x3fbeb851eb851eb8, 0x3fb19cac083126e9, 0x0000000000000000, 0x3fbeb851eb851eb8)),
    ("V10",
     (0x3fb18cf1800a7c5b, 0x0000000000000000, 0x0000000000000000),
     (0x3f90000000000000, 0x0000000000000000),
     (0x3fbeb851eb851eb8, 0x3fb18cf1800a7c5b, 0x0000000000000000, 0x3fbeb851eb851eb8)),
    ("V11",
     (0xbfb18cf1800a7c5a, 0x0000000000000000, 0x0000000000000000),
     (0xbf90000000000000, 0x0000000000000000),
     (0xbfbeb851eb851eb8, 0xbfb19cac083126e9, 0x0000000000000000, 0xbfbeb851eb851eb8)),
    ("V12",
     (0x8000000000000000, 0x8000000000000000, 0xbfb0000000000000),
     (0x8000000000000000, 0x8000000000000000),
     (0x0000000000000000, 0x8000000000000000, 0x0000000000000000, 0x0000000000000000)),
)

# Traces are (id, initial state bits, ((observation bits, expected bits), ...)).
TRACES = (
    ("T1", (0x0000000000000000, 0x0000000000000000, 0x0000000000000000), (
        ((0x3f90000000000000, 0x0000000000000000),
         (0x3faa56c0d6f544bb, 0x3f2f75104d551d69, 0x0000000000000000, 0x3faa56c0d6f544bb)),
        ((0x3f90000000000000, 0x0000000000000000),
         (0x3faa7635e74299d9, 0x3f3f75104d551d69, 0x0000000000000000, 0x3faa7635e74299d9)),
        ((0x3f90000000000000, 0x0000000000000000),
         (0x3faa95aaf78feef6, 0x3f4797cc39ffd60f, 0x0000000000000000, 0x3faa95aaf78feef6)),
    )),
    ("T2", (0x0000000000000000, 0x0000000000000000, 0x0000000000000000), (
        ((0x0000000000000000, 0x3fd8000000000000),
         (0x3fa3c6a7ef9db22d, 0x0000000000000000, 0x3fc0000000000000, 0x3fa3c6a7ef9db22d)),
        ((0x0000000000000000, 0x0000000000000000),
         (0x3f9a5e353f7ced92, 0x0000000000000000, 0x3fb5555555555556, 0x3f9a5e353f7ced92)),
        ((0x0000000000000000, 0x0000000000000000),
         (0x3f9194237fa89e62, 0x0000000000000000, 0x3fac71c71c71c71e, 0x3f9194237fa89e62)),
    )),
    ("T3", (0x3fa0000000000000, 0xbfb0000000000000, 0xbfb0000000000000), (
        ((0x3fb0000000000000, 0x3fe0000000000000),
         (0x3fbeb851eb851eb8, 0x3fa0000000000000, 0x3fc0000000000000, 0x3fbeb851eb851eb8)),
        ((0x3fb0000000000000, 0x0000000000000000),
         (0x3fbeb851eb851eb8, 0x3fa0000000000000, 0x3fb5555555555556, 0x3fbeb851eb851eb8)),
        ((0xbf90000000000000, 0x0000000000000000),
         (0xbf68caf1720f58a8, 0x3f9fc115df6555c5, 0x3fac71c71c71c71e, 0xbf68caf1720f58a8)),
        ((0xbf90000000000000, 0x0000000000000000),
         (0xbf8268a848299436, 0x3f9f822bbecaab8a, 0x3fa2f684bda12f6a, 0xbf8268a848299436)),
    )),
)


def from_bits(word):
    return struct.unpack("<d", struct.pack("<Q", word))[0]


def bits(value):
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def crc32c(data):
    # Test-only bitwise Castagnoli calculation, independent of wire machinery.
    crc = 0xffffffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82f63b78 if crc & 1 else 0)
    return crc ^ 0xffffffff


class DigestEvidenceTests(unittest.TestCase):
    def test_crc_evidence_has_independent_known_answers(self):
        self.assertEqual(crc32c(b""), 0x00000000)
        self.assertEqual(crc32c(b"123456789"), 0xe3069283)
        self.assertEqual(len(PACKED_CONSTANTS), 56)
        self.assertEqual(crc32c(PACKED_CONSTANTS), 0xe77201ca)


class ControlReferenceTests(unittest.TestCase):
    def setUp(self):
        # Missing production code must fail in red, never silently skip.
        self.pid = importlib.import_module("sim.control_ref")

    def state_from_bits(self, words):
        return self.pid.ControlState(*(from_bits(word) for word in words))

    def check_step(self, state, observation, expected):
        before = tuple(bits(value) for value in state)
        result = self.pid.step(state, observation)
        self.assertIs(type(result), tuple)
        self.assertEqual(len(result), 2)
        delta, next_state = result
        self.assertIs(type(delta), float)
        self.assertIs(type(next_state), self.pid.ControlState)
        self.assertIsNot(next_state, state)
        self.assertEqual(tuple(bits(value) for value in state), before)
        self.assertEqual(
            tuple(bits(value) for value in (delta, *next_state)), expected
        )
        self.assertEqual(bits(delta), bits(next_state.last_delta))
        return next_state

    def test_state_has_exact_fields_and_float_annotations(self):
        fields = ("i_state", "d_prev", "last_delta")
        self.assertTrue(issubclass(self.pid.ControlState, tuple))
        self.assertEqual(self.pid.ControlState._fields, fields)
        hints = get_type_hints(self.pid.ControlState)
        self.assertEqual(tuple(hints), fields)
        self.assertEqual(tuple(hints.values()), (float, float, float))

    def test_state_is_immutable(self):
        state = self.pid.initial()
        for field in ("i_state", "d_prev", "last_delta"):
            with self.subTest(field=field):
                with self.assertRaises(AttributeError):
                    setattr(state, field, 1.0)
        with self.assertRaises(TypeError):
            state[0] = 1.0

    def test_constructor_preserves_finite_representations(self):
        cases = (
            (0x8000000000000000, 0x3ff0000000000001, 0xbfbeb851eb851eb8),
            (0x3fb18cf1800a7c59, 0x8000000000000000, 0x8000000000000000),
        )
        for words in cases:
            with self.subTest(words=words):
                values = tuple(from_bits(word) for word in words)
                state = self.pid.ControlState(*values)
                self.assertEqual(tuple(bits(value) for value in state), words)
                for supplied, retained in zip(values, state):
                    self.assertIs(retained, supplied)

    def test_initial_state_has_three_positive_zeros(self):
        state = self.pid.initial()
        self.assertIs(type(state), self.pid.ControlState)
        self.assertEqual(
            tuple(bits(value) for value in state),
            (0x0000000000000000, 0x0000000000000000, 0x0000000000000000),
        )

    def test_constants_match_independent_binary64_words(self):
        for name, expected in CONSTANT_BITS.items():
            with self.subTest(name=name):
                value = getattr(self.pid, name)
                self.assertIs(type(value), float)
                self.assertEqual(bits(value), expected)
        self.assertEqual(bits(self.pid.NEG_DELTA_MAX), 0xbfbeb851eb851eb8)
        self.assertEqual(bits(self.pid.NEG_I_MAX), 0xbfbeb851eb851eb8)

    def test_representation_sensitive_construction_routes(self):
        # These expression routes are contractual, unlike incidental formatting.
        tree = ast.parse(SOURCE.read_text())
        assignments = {
            target.id: node.value
            for node in tree.body if isinstance(node, ast.Assign)
            for target in node.targets if isinstance(target, ast.Name)
        }
        routes = {
            "DT": "1.0 / 500.0",
            "KI_DT": "KI * DT",
            "BETA_D": "1.0 / 3.0",
            "I_MAX": "DELTA_MAX",
            "THETA_SP": "+0.0",
            "NEG_DELTA_MAX": "-DELTA_MAX",
            "NEG_I_MAX": "-I_MAX",
        }
        for name, expression in routes.items():
            with self.subTest(name=name):
                self.assertIn(name, assignments)
                self.assertEqual(
                    ast.dump(assignments[name]),
                    ast.dump(ast.parse(expression, mode="eval").body),
                )

    def test_packed_constants_and_digest_are_test_evidence(self):
        packed = struct.pack(
            "<7d", self.pid.KP, self.pid.KI_DT, self.pid.KD,
            self.pid.BETA_D, self.pid.DELTA_MAX, self.pid.I_MAX, self.pid.DT,
        )
        self.assertEqual(packed, PACKED_CONSTANTS)
        self.assertEqual(crc32c(packed), 0xe77201ca)
        self.assertFalse(hasattr(self.pid, "DIGEST"))

    def test_all_twelve_independent_one_step_vectors(self):
        for name, state_words, observation_words, expected in VECTORS:
            with self.subTest(vector=name):
                state = self.state_from_bits(state_words)
                observation = Observation(
                    41, *(from_bits(word) for word in observation_words), True
                )
                self.check_step(state, observation, expected)

    def test_all_three_traces_carry_actual_state_forward(self):
        ticks = (7, 19, 20, 200)
        for name, initial_words, steps in TRACES:
            state = self.state_from_bits(initial_words)
            for index, (observation_words, expected) in enumerate(steps):
                with self.subTest(trace=name, step=index + 1):
                    observation = Observation(
                        ticks[index],
                        *(from_bits(word) for word in observation_words),
                        True,
                    )
                    state = self.check_step(state, observation, expected)

    def test_last_delta_is_not_an_arithmetic_input(self):
        for name, state_words, observation_words, expected in VECTORS:
            for last_word in (
                0x0000000000000000, 0x8000000000000000,
                0x3fbeb851eb851eb8, 0xbfbeb851eb851eb8,
            ):
                with self.subTest(vector=name, last=last_word):
                    state = self.state_from_bits((*state_words[:2], last_word))
                    observation = Observation(
                        41, *(from_bits(word) for word in observation_words), True
                    )
                    self.check_step(state, observation, expected)

    def test_tick_and_valid_metadata_cannot_change_arithmetic(self):
        # This does not say which observations the later system should admit.
        for name, state_words, observation_words, expected in VECTORS:
            for tick in (0, 41, 0xffffffffffffffff):
                for valid in (False, True):
                    with self.subTest(vector=name, tick=tick, valid=valid):
                        state = self.state_from_bits(state_words)
                        observation = Observation(
                            tick,
                            *(from_bits(word) for word in observation_words),
                            valid,
                        )
                        self.check_step(state, observation, expected)

    def test_only_model_types_and_typing_dependencies_are_used(self):
        tree = ast.parse(SOURCE.read_text())
        imports = set()
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level == 1:
                    module = "sim" + ("." + module if module else "")
                elif node.level:
                    violations.append((node.lineno, "parent-package import"))
                if module == "sim":
                    imports.update("sim." + alias.name for alias in node.names)
                else:
                    imports.add(module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"open", "input", "print", "__import__", "eval", "exec"}:
                    violations.append((node.lineno, node.func.id))
        self.assertLessEqual(imports, {"sim.types", "typing"})
        self.assertEqual(violations, [])


ROOT = SOURCE.parent.parent
GENERATOR_SOURCE = SOURCE.with_name("gen_pid_corpus.py")
CORPUS = ROOT / "tests" / "golden" / "pid" / "pid_corpus.json"


def expected_corpus():
    # Serialization of test-owned literals, never candidate-controller results.
    def encoded(words):
        return [f"0x{word:016x}" for word in words]

    return {
        "constants_bits": {
            name: f"0x{word:016x}" for name, word in CONSTANT_BITS.items()
        },
        "digest_crc32c": "0xe77201ca",
        "vectors": [
            {"id": name, "state_bits": encoded(state),
             "observation_bits": encoded(observation),
             "expected_bits": encoded(expected)}
            for name, state, observation, expected in VECTORS
        ],
        "traces": [
            {"id": name, "initial_state_bits": encoded(initial),
             "steps": [
                 {"observation_bits": encoded(observation),
                  "expected_bits": encoded(expected)}
                 for observation, expected in steps
             ]}
            for name, initial, steps in TRACES
        ],
    }


def expected_corpus_bytes():
    return (json.dumps(
        expected_corpus(), indent=2, sort_keys=True,
        ensure_ascii=True, allow_nan=False,
    ) + "\n").encode("utf-8")


class PidCorpusTests(unittest.TestCase):
    def test_exact_artifact_membership_without_symlinks(self):
        self.assertTrue(CORPUS.parent.is_dir(), "missing PID corpus directory")
        self.assertFalse(CORPUS.parent.is_symlink())
        entries = list(CORPUS.parent.rglob("*"))
        self.assertEqual(
            {entry.relative_to(CORPUS.parent).as_posix() for entry in entries},
            {"pid_corpus.json"},
        )
        for entry in entries:
            self.assertFalse(entry.is_symlink())
            self.assertTrue(entry.is_file())

    def test_exact_document_and_canonical_bytes(self):
        payload = CORPUS.read_bytes()
        self.assertEqual(json.loads(payload), expected_corpus())
        self.assertEqual(payload, expected_corpus_bytes())

    def test_bit_encoding_and_order_have_no_float_json_values(self):
        document = json.loads(CORPUS.read_bytes())
        self.assertEqual(set(document), {
            "constants_bits", "digest_crc32c", "vectors", "traces",
        })
        self.assertEqual(set(document["constants_bits"]), set(CONSTANT_BITS))
        self.assertEqual(document["digest_crc32c"], "0xe77201ca")
        self.assertEqual([v["id"] for v in document["vectors"]],
                         [f"V{i:02}" for i in range(1, 13)])
        self.assertEqual([t["id"] for t in document["traces"]], ["T1", "T2", "T3"])
        groups = [list(document["constants_bits"].values())]
        for vector in document["vectors"]:
            self.assertEqual(set(vector), {
                "id", "state_bits", "observation_bits", "expected_bits",
            })
            for field, size in (("state_bits", 3), ("observation_bits", 2),
                                ("expected_bits", 4)):
                self.assertEqual(len(vector[field]), size)
                groups.append(vector[field])
        for trace, count in zip(document["traces"], (3, 3, 4)):
            self.assertEqual(set(trace), {"id", "initial_state_bits", "steps"})
            self.assertEqual(len(trace["initial_state_bits"]), 3)
            groups.append(trace["initial_state_bits"])
            self.assertEqual(len(trace["steps"]), count)
            for step in trace["steps"]:
                self.assertEqual(set(step), {"observation_bits", "expected_bits"})
                self.assertEqual(len(step["observation_bits"]), 2)
                self.assertEqual(len(step["expected_bits"]), 4)
                groups.extend((step["observation_bits"], step["expected_bits"]))
        for group in groups:
            for word in group:
                self.assertIs(type(word), str)
                self.assertRegex(word, r"\A0x[0-9a-f]{16}\Z")

        def no_floats(value):
            self.assertNotIsInstance(value, float)
            if isinstance(value, dict):
                for child in value.values():
                    no_floats(child)
            elif isinstance(value, list):
                for child in value:
                    no_floats(child)

        no_floats(document)


class PidGeneratorTests(unittest.TestCase):
    def setUp(self):
        # Otherwise a missing module could falsely pass negative CLI tests.
        self.assertTrue(GENERATOR_SOURCE.is_file(), "missing PID generator")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.output = self.directory / "output"
        self.output.mkdir()

    def run_generator(self, *arguments, cwd=ROOT):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        return subprocess.run(
            [sys.executable, "-B", "-m", "sim.gen_pid_corpus", *map(str, arguments)],
            cwd=cwd, env=env, capture_output=True, text=True, timeout=30,
        )

    def test_missing_and_extra_arguments_fail(self):
        for arguments in ((), (self.output, "extra")):
            with self.subTest(arguments=arguments):
                result = self.run_generator(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(self.output.iterdir()), [])

    def test_invalid_destinations_fail_without_creating_or_following(self):
        ordinary_file = self.directory / "file"
        ordinary_file.write_bytes(b"preserve")
        alias = self.directory / "alias"
        alias.symlink_to(self.output, target_is_directory=True)
        missing = self.directory / "absent" / "child"
        for destination in (missing, ordinary_file, alias):
            with self.subTest(destination=destination.name):
                result = self.run_generator(destination)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(missing.parent.exists())
                self.assertEqual(ordinary_file.read_bytes(), b"preserve")
                self.assertTrue(alias.is_symlink())
                self.assertEqual(list(self.output.iterdir()), [])

    def test_existing_directory_produces_only_exact_corpus(self):
        result = self.run_generator(self.output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({entry.name for entry in self.output.iterdir()},
                         {"pid_corpus.json"})
        artifact = self.output / "pid_corpus.json"
        self.assertFalse(artifact.is_symlink())
        self.assertEqual(artifact.read_bytes(), expected_corpus_bytes())
        self.assertEqual(artifact.read_bytes(), CORPUS.read_bytes())

    def test_unrelated_files_and_directories_remain_untouched(self):
        nested = self.output / "unrelated"
        nested.mkdir()
        files = (self.output / "keep.txt", nested / "keep.bin")
        for item in files:
            item.write_bytes(b"unrelated contents")
        before = [(p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in files]
        result = self.run_generator(self.output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(nested.is_dir())
        self.assertEqual(
            [(p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in files],
            before,
        )
        self.assertEqual({p.name for p in self.output.iterdir()},
                         {"keep.txt", "unrelated", "pid_corpus.json"})
        self.assertEqual((self.output / "pid_corpus.json").read_bytes(),
                         expected_corpus_bytes())

    def test_output_file_symlinks_are_rejected(self):
        existing = self.directory / "existing"
        existing.write_bytes(b"do not overwrite")
        missing = self.directory / "missing-target"
        artifact = self.output / "pid_corpus.json"
        for target in (existing, missing):
            with self.subTest(target=target.name):
                artifact.symlink_to(target)
                result = self.run_generator(self.output)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(artifact.is_symlink())
                self.assertEqual(existing.read_bytes(), b"do not overwrite")
                self.assertFalse(missing.exists())
                artifact.unlink()

    def test_generation_is_independent_of_caller_cwd(self):
        elsewhere = self.directory / "elsewhere"
        elsewhere.mkdir()
        result = self.run_generator(self.output, cwd=elsewhere)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertEqual((self.output / "pid_corpus.json").read_bytes(),
                         expected_corpus_bytes())

    def test_generation_does_not_need_controller_or_other_runtime_modules(self):
        blocked = """
import runpy
import sys
for name in (
    'sim.control_ref', 'sim.types', 'sim.plant', 'sim.actuator', 'sim.sensor',
    'sim.environment', 'sim.scenario', 'sim.rng', 'sim.fixmath', 'sim.link', 'tests',
):
    sys.modules[name] = None
sys.argv = ['sim.gen_pid_corpus', sys.argv[1]]
runpy.run_module('sim.gen_pid_corpus', run_name='__main__')
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", blocked, str(self.output)],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.output / "pid_corpus.json").read_bytes(),
                         expected_corpus_bytes())


class PidGeneratorArchitectureTests(unittest.TestCase):
    def test_no_runtime_or_test_imports_or_process_execution(self):
        self.assertTrue(GENERATOR_SOURCE.is_file(), "missing PID generator")
        forbidden = {
            "sim", "tests", "subprocess", "multiprocessing", "threading",
            "concurrent", "socket", "http", "urllib", "asyncio", "random",
            "time", "datetime", "math", "cmath",
        }
        for node in ast.walk(ast.parse(GENERATOR_SOURCE.read_text())):
            imports = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "no relative TVC imports")
                imports = [node.module or ""]
            for imported in imports:
                root = imported.split(".", 1)[0]
                self.assertNotIn(root, forbidden)
                self.assertIn(root, sys.stdlib_module_names)
            if isinstance(node, ast.Call):
                called = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else ""
                )
                self.assertNotIn(called, {
                    "__import__", "import_module", "eval", "exec", "compile",
                    "system", "popen", "fork", "execv", "execve", "Popen",
                    "spawnl", "spawnv", "posix_spawn",
                })


if __name__ == "__main__":
    unittest.main()

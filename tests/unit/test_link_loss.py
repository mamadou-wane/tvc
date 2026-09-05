import ast
import json
import math
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sim import rng, scenario


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests" / "golden" / "link"
SCENARIOS = ROOT / "sim" / "scenarios"
P30 = "0x1.3333333333333p-2"
UP_PREFIX = "00101001110010000001010011000001"
DOWN_PREFIX = "01100001010100010001000100110100"
CASE_KEYS = (
    "scenario", "seed", "p_up", "p_down", "ticks",
    "intentionally_lost_up", "intentionally_lost_down",
    "draw_drop_prefix_up", "draw_drop_prefix_down", "final_state_up", "final_state_down",
)
# Independent literals; neither the generator nor its artifact supplies them.
CASE_LITERALS = (
    ("S2-gust", 1, P30, P30, 2000, 570, 608, UP_PREFIX, DOWN_PREFIX,
     "0xa271271efeebc0d1", "0xd05286d3db785077"),
    ("S2-gust", 1, P30, P30, 3000, 875, 902, UP_PREFIX, DOWN_PREFIX,
     "0xab24a3b839e072d9", "0xd906036d166d027f"),
    ("S2-gust", 1, P30, P30, 5000, 1477, 1479, UP_PREFIX, DOWN_PREFIX,
     "0xbc8b9ceaafc9d6e9", "0xea6cfc9f8c56668f"),
    ("S2-gust", 1, P30, P30, 10000, 3047, 2943, UP_PREFIX, DOWN_PREFIX,
     "0xe80d0be8d6915111", "0x15ee6b9db31de0b7"),
    ("S1-hold", 1, "0x0.0p+0", "0x1.0000000000000p+0", 32, 0, 32,
     "00000000000000000000000000000000", "11111111111111111111111111111111",
     "0x57f9651c7251df61", "0x85dac4d14ede6f07"),
    ("S1-hold", 1, "0x1.7906ac21d0e58p-2", "0x1.de2c6aa70a6f2p-2", 32, 14, 16,
     "00101001110010010001010011001101", "01101011011101010001000100111100",
     "0x57f9651c7251df61", "0x85dac4d14ede6f07"),
    ("S6-blackout", 1, P30, P30, 2000, 589, 608, UP_PREFIX, DOWN_PREFIX,
     "0xa271271efeebc0d1", "0xd05286d3db785077"),
    ("demo-loss30", 20260902, P30, P30, 3000, 832, 838,
     "10000001111110111000000101100010", "00000010001000000000011000001000",
     "0xdd533e1366dad898", "0x916374dc9d0dcca2"),
)
EXPECTED = {"cases": [dict(zip(CASE_KEYS, values)) for values in CASE_LITERALS]}


def expected_bytes():
    return (json.dumps(EXPECTED, indent=2, sort_keys=True,
                       ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


class LinkContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sim import link

        cls.link = link

    def test_endpoint_probabilities_consume_one_draw_and_return_bool(self):
        for p, expected in ((0, False), (0.0, False), (-0.0, False), (1, True), (1.0, True)):
            stream = rng.SplitMix64(0)
            with self.subTest(p=p), patch.object(stream, "next_double", wraps=stream.next_double) as draw:
                result = self.link.draw_drop(stream, p)
                self.assertIs(result, expected)
                self.assertEqual(stream.state, 0x9E3779B97F4A7C15)
                draw.assert_called_once_with()

    def test_equality_and_adjacent_probabilities_use_strict_less_than(self):
        for name, literal in (("link.loss.up", "0x1.7906ac21d0e58p-2"),
                              ("link.loss.down", "0x1.de2c6aa70a6f2p-2")):
            equal = float.fromhex(literal)
            for p, expected in ((math.nextafter(equal, -math.inf), False),
                                (equal, False), (math.nextafter(equal, math.inf), True)):
                with self.subTest(name=name, p=p.hex()):
                    stream = rng.SplitMix64(rng.stream_state(1, name))
                    self.assertIs(self.link.draw_drop(stream, p), expected)

    def test_zero_draw_wrap_vector_keeps_at_zero_probability(self):
        for p, expected in ((0.0, False), (math.nextafter(0.0, 1.0), True)):
            with self.subTest(p=p):
                stream = rng.SplitMix64(0x61C8864680B583EB)
                self.assertIs(self.link.draw_drop(stream, p), expected)
                self.assertEqual(stream.state, 0)

    def test_invalid_probability_is_rejected_before_reading_rng(self):
        invalid = (True, False, None, "0.3", [], {}, object(), complex(0.3, 0),
                   float("nan"), float("inf"), -float("inf"), -0.01, 1.01, 10**400)
        for p in invalid:
            stream = rng.SplitMix64(0x910A2DEC89025CC1)
            with self.subTest(p=repr(p)), patch.object(
                stream, "next_double", side_effect=AssertionError("invalid input read RNG")
            ):
                with self.assertRaises(ValueError):
                    self.link.draw_drop(stream, p)
                self.assertEqual(stream.state, 0x910A2DEC89025CC1)

    def test_all_eight_cases_against_independent_literals(self):
        for case in EXPECTED["cases"]:
            spec = scenario.load(SCENARIOS / (case["scenario"] + ".json"))
            for direction in ("up", "down"):
                stream = rng.SplitMix64(rng.stream_state(case["seed"], "link.loss." + direction))
                p = float.fromhex(case["p_" + direction])
                count = 0
                prefix = ""
                for tick in range(case["ticks"]):
                    raw = self.link.draw_drop(stream, p)
                    self.assertIs(type(raw), bool)
                    forced = scenario.forced_drop_at(spec, tick, direction=direction)
                    count += int(raw if forced is None else forced)
                    if tick < 32:
                        prefix += "1" if raw else "0"
                with self.subTest(scenario=spec.id, ticks=case["ticks"], p=p, direction=direction):
                    self.assertEqual(count, case["intentionally_lost_" + direction])
                    self.assertEqual(prefix, case["draw_drop_prefix_" + direction])
                    self.assertEqual(stream.state, int(case["final_state_" + direction], 16))

    def test_s6_zero_probability_still_has_thirty_forced_drops(self):
        spec = scenario.load(SCENARIOS / "S6-blackout.json")
        stream = rng.SplitMix64(rng.stream_state(1, "link.loss.up"))
        dropped = []
        for tick in range(2000):
            raw = self.link.draw_drop(stream, 0.0)
            self.assertIs(raw, False)
            forced = scenario.forced_drop_at(spec, tick, direction="up")
            if raw if forced is None else forced:
                dropped.append(tick)
        self.assertEqual(dropped, list(range(1000, 1030)))
        self.assertEqual(stream.state, 0xA271271EFEEBC0D1)

    def test_forced_tail_and_full_forced_keep_preserve_final_state(self):
        spec = scenario.load(SCENARIOS / "S1-hold.json")._replace(
            ticks=4, loss_start_tick=4, blackout_up=(2, 4),
        )
        for direction, expected in (("up", "0011"), ("down", "0000")):
            stream = rng.SplitMix64(0)
            raw_prefix = ""
            effective_prefix = ""
            for tick in range(4):
                raw = self.link.draw_drop(stream, 0.3)
                forced = scenario.forced_drop_at(spec, tick, direction=direction)
                raw_prefix += "1" if raw else "0"
                effective_prefix += "1" if (raw if forced is None else forced) else "0"
            with self.subTest(direction=direction):
                self.assertEqual(raw_prefix, "0010")
                self.assertEqual(effective_prefix, expected)
                self.assertEqual(stream.state, 0x78DDE6E5FD29F054)


class CorpusArtifactTests(unittest.TestCase):
    def test_exact_artifact_membership_contents_and_format(self):
        self.assertTrue(CORPUS.is_dir(), "missing loss corpus directory")
        paths = list(CORPUS.rglob("*"))
        self.assertFalse(any(p.is_symlink() for p in paths))
        self.assertEqual({p.relative_to(CORPUS).as_posix() for p in paths if p.is_file()},
                         {"loss_counts.json"})
        data = (CORPUS / "loss_counts.json").read_bytes()
        self.assertEqual(json.loads(data), EXPECTED)
        self.assertEqual(data, expected_bytes())


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / "sim" / "gen_loss_corpus.py").is_file():
            raise AssertionError("missing loss corpus generator")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.output = self.directory / "output"
        self.output.mkdir()

    def run_generator(self, *args, cwd=None):
        # Module discovery is explicit; scenario discovery must use its module location.
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT))
        return subprocess.run(
            [sys.executable, "-B", "-m", "sim.gen_loss_corpus", *map(str, args)],
            cwd=self.directory if cwd is None else cwd, env=env, capture_output=True, text=True,
        )

    def test_missing_and_extra_cli_arguments_fail(self):
        for args in ((), (self.output, "extra")):
            with self.subTest(args=args):
                result = self.run_generator(*args)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse((self.output / "loss_counts.json").exists())
                self.assertFalse((self.directory / "loss_counts.json").exists())

    def test_nonexistent_or_nondirectory_destination_fails(self):
        missing = self.directory / "missing" / "nested"
        file = self.directory / "file"
        file.write_bytes(b"unchanged")
        for target in (missing, file):
            with self.subTest(target=target):
                self.assertNotEqual(self.run_generator(target).returncode, 0)
        self.assertFalse((self.directory / "missing").exists())
        self.assertEqual(file.read_bytes(), b"unchanged")

    def test_existing_directory_produces_only_exact_corpus(self):
        result = self.run_generator(self.output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({p.name for p in self.output.iterdir()}, {"loss_counts.json"})
        data = (self.output / "loss_counts.json").read_bytes()
        self.assertEqual(data, expected_bytes())
        self.assertEqual(data, (CORPUS / "loss_counts.json").read_bytes())

    def test_unrelated_files_are_preserved(self):
        sentinel = self.output / "keep.bin"
        sentinel.write_bytes(b"keep\x00unchanged")
        nested = self.output / "nested"
        nested.mkdir()
        child = nested / "keep.txt"
        child.write_bytes(b"also unchanged\n")
        result = self.run_generator(self.output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sentinel.read_bytes(), b"keep\x00unchanged")
        self.assertEqual(child.read_bytes(), b"also unchanged\n")
        self.assertEqual({p.relative_to(self.output).as_posix() for p in self.output.rglob("*") if p.is_file()},
                         {"keep.bin", "nested/keep.txt", "loss_counts.json"})

    def test_generation_is_independent_of_caller_cwd(self):
        first = self.run_generator(self.output, cwd=ROOT)
        self.assertEqual(first.returncode, 0, first.stderr)
        expected = (self.output / "loss_counts.json").read_bytes()
        second_output = self.directory / "second"
        second_output.mkdir()
        second = self.run_generator(second_output)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual((second_output / "loss_counts.json").read_bytes(), expected)
        self.assertEqual(expected, expected_bytes())

    def test_real_calls_use_distinct_live_streams_and_draw_before_override(self):
        from sim import link

        real_state, real_stream = rng.stream_state, rng.SplitMix64
        real_draw, real_forced = link.draw_drop, scenario.forced_drop_at
        derivations, streams, order = [], [], []
        state_names, stream_names = {}, {}
        pending = [None]

        def derive(seed, name):
            derivations.append((seed, name))
            state = real_state(seed, name)
            state_names[state] = name.removeprefix("link.loss.")
            return state

        def create(state):
            stream = real_stream(state)
            streams.append(stream)
            stream_names[id(stream)] = state_names[state]
            return stream

        def draw(stream, p):
            self.assertIsNone(pending[0])
            pending[0] = stream_names[id(stream)]
            order.append(pending[0])
            return real_draw(stream, p)

        def forced(spec, tick, *, direction):
            self.assertEqual(pending[0], direction)
            pending[0] = None
            defaults = (0.3, 0.3) if spec.id == "demo-loss30" else (0.0, 0.0)
            self.assertEqual((spec.loss_up, spec.loss_down), defaults)
            return real_forced(spec, tick, direction=direction)

        with patch.object(rng, "stream_state", side_effect=derive), \
             patch.object(rng, "SplitMix64", side_effect=create), \
             patch.object(link, "draw_drop", side_effect=draw), \
             patch.object(scenario, "forced_drop_at", side_effect=forced), \
             patch.object(sys, "argv", ["sim.gen_loss_corpus", str(self.output)]):
            runpy.run_module("sim.gen_loss_corpus", run_name="__main__")
        self.assertEqual(derivations, [(c["seed"], "link.loss." + d)
                                      for c in EXPECTED["cases"] for d in ("up", "down")])
        self.assertEqual(len({id(stream) for stream in streams}), 16)
        self.assertEqual(order, ["up", "down"] * sum(c["ticks"] for c in EXPECTED["cases"]))
        self.assertIsNone(pending[0])
        self.assertEqual((self.output / "loss_counts.json").read_bytes(), expected_bytes())


class LossArchitectureTests(unittest.TestCase):
    def test_runtime_dependencies_and_pure_link_boundary(self):
        forbidden = {"asyncio", "concurrent", "datetime", "http", "multiprocessing",
                     "random", "selectors", "socket", "subprocess", "threading", "time", "urllib"}
        for filename, allowed in (("link.py", {"sim.rng"}),
                                  ("gen_loss_corpus.py", {"sim.rng", "sim.link", "sim.scenario"})):
            with self.subTest(filename=filename):
                path = ROOT / "sim" / filename
                self.assertTrue(path.is_file(), "missing " + filename)
                imports = []
                for node in ast.walk(ast.parse(path.read_text())):
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
                        self.assertNotIn(called, {"__import__", "system", "popen", "fork", "execv", "execve"})
                        if filename == "link.py":
                            self.assertNotIn(called, {"open", "read_text", "read_bytes", "write_text", "write_bytes",
                                                      "mkdir", "makedirs", "unlink", "remove", "rmdir", "iterdir", "listdir", "stat"})
                for imported in imports:
                    root = imported.split(".", 1)[0]
                    self.assertNotIn(root, forbidden)
                    if root == "sim":
                        self.assertIn(imported, allowed)
                    else:
                        self.assertIn(root, sys.stdlib_module_names)


if __name__ == "__main__":
    unittest.main()

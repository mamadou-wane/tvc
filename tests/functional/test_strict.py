import json, os, pathlib, subprocess, tempfile, unittest

BIN = os.environ["TVC_BIN"]

class StrictExits(unittest.TestCase):
    def test_bad_arg_value_rejected(self):
        p = subprocess.run([BIN, "--cpu=abc"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)

    def test_bad_label_rejected(self):
        p = subprocess.run([BIN, "--label=a/b"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)

    def test_fifo_overflow_rejected(self):
        # Bounded cycles/warmup: an undetected overflow wraps into a legal
        # value and the harness would otherwise run to completion.
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run(
                [BIN, "--label=f", f"--out={d}", "--rate=1000",
                 "--cycles=200", "--warmup=10", "--fifo=4294967296"],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertIn("--fifo must be", p.stderr)

    def test_cpu_overflow_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run(
                [BIN, "--label=c", f"--out={d}", "--rate=1000",
                 "--cycles=200", "--warmup=10", "--cpu=4294967295"],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertIn("--cpu must be", p.stderr)

    def test_fifo_above_range_rejected(self):
        p = subprocess.run([BIN, "--fifo=100"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)

    def test_cpu_below_range_rejected(self):
        p = subprocess.run([BIN, "--cpu=-2"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)

    def test_help_exits_0(self):
        p = subprocess.run([BIN, "--help"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertIn("tvc_harness", p.stdout)

    def test_help_short_flag_exits_0(self):
        p = subprocess.run([BIN, "-h"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)

    def test_failed_mitigation_exits_2_and_is_recorded(self):
        # Unprivileged container process: SCHED_FIFO must fail.
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run(
                [BIN, "--label=s", f"--out={d}", "--rate=1000",
                 "--cycles=500", "--warmup=50", "--fifo=80"],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
            s = json.loads((pathlib.Path(d) / "s.summary.json").read_text())
            self.assertFalse(s["applied"]["fifo"])
            self.assertIn("kernel", s["env"])
            for key in ("ac_online", "governor", "epp", "pkg_temp_c", "cpuidle"):
                self.assertIn(key, s["env"])
            cpuidle = s["env"]["cpuidle"]
            self.assertEqual(set(cpuidle.keys()), {"driver", "cpus", "states"})
            self.assertIsInstance(cpuidle["driver"], str)
            self.assertIsInstance(cpuidle["cpus"], int)
            self.assertGreaterEqual(cpuidle["cpus"], 0)
            self.assertIsInstance(cpuidle["states"], list)
            for state in cpuidle["states"]:
                self.assertEqual(set(state.keys()),
                                  {"name", "latency_us", "disabled"})
                self.assertIsInstance(state["name"], str)
                self.assertIsInstance(state["latency_us"], int)
                self.assertIsInstance(state["disabled"], int)
                self.assertGreaterEqual(state["disabled"], 0)

    def test_unwritable_out_exits_4(self):
        # Two missing levels: the harness creates one directory level at most,
        # so mkdir fails on the absent parent and the writes fail, even as root.
        p = subprocess.run(
            [BIN, "--label=w", "--out=/nonexistent-a/b", "--rate=1000",
             "--cycles=200", "--warmup=10"],
            capture_output=True, text=True)
        self.assertEqual(p.returncode, 4)

if __name__ == "__main__":
    unittest.main()

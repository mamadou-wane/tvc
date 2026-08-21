import json, pathlib, sys, tempfile, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import bench_gate

GOOD = {"applied": {"mlock": True, "fifo": True, "cpu": True},
        "cycles": 100, "cycles_requested": 100,
        "jitter_us": {"p99.9": 88.4},
        "env": {"cpuidle": {"driver": "acpi_idle", "cpus": 2,
                             "states": [{"name": "C1", "latency_us": 1,
                                         "disabled": 2}]}}}


class Gate(unittest.TestCase):
    def test_pass_within_tolerance(self):
        ok, msg = bench_gate.gate([90.0], [88.0], 25.0)
        self.assertTrue(ok)
        self.assertIn("pass", msg)

    def test_regression_fails(self):
        ok, msg = bench_gate.gate([200.0], [88.0], 25.0)
        self.assertFalse(ok)
        self.assertIn("REGRESSION", msg)

    def test_missing_new_data_fails(self):
        ok, _ = bench_gate.gate([], [88.0], 25.0)
        self.assertFalse(ok)

    def test_missing_baseline_fails(self):
        ok, _ = bench_gate.gate([90.0], [], 25.0)
        self.assertFalse(ok)


class VerifiedP999s(unittest.TestCase):
    def test_gates_unverified_rows(self):
        with tempfile.TemporaryDirectory() as d:
            bad = {k: v for k, v in GOOD.items() if k != "cycles_requested"}
            (pathlib.Path(d) / "L5.r1.summary.json").write_text(json.dumps(GOOD))
            (pathlib.Path(d) / "L5.r2.summary.json").write_text(json.dumps(bad))
            self.assertEqual(bench_gate.verified_p999s(d, "L5"), [88.4])


if __name__ == "__main__":
    unittest.main()

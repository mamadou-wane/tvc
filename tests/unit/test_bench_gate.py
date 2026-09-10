import json, os, pathlib, sys, tempfile, unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import bench_gate

GOOD = {"mode": "harness", "applied": {"mlock": True, "fifo": True, "cpu": True},
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



class ModeEvidence(unittest.TestCase):
    def test_committed_baseline_when_container_user_differs(self):
        root=pathlib.Path(__file__).resolve().parents[2]
        baseline=root/'baselines/2026-08-29-pinned-timer-campaign/L5.r1.summary.json'
        with patch.dict(os.environ,{'GIT_TEST_ASSUME_DIFFERENT_OWNER':'1'}):
            self.assertTrue(bench_gate.legacy_baseline(baseline))
            with patch.object(pathlib.Path,'read_bytes',return_value=b'changed'):
                self.assertFalse(bench_gate.legacy_baseline(baseline))

    def test_fresh_missing_mode_and_lockstep_are_errors(self):
        with tempfile.TemporaryDirectory() as d:
            path=pathlib.Path(d)/'L5.summary.json'
            for fields in ({},{'mode':'lockstep'},{'mode':'freerun'}):
                path.write_text(json.dumps({**GOOD,**fields} if fields else {k:v for k,v in GOOD.items() if k!='mode'}))
                with self.assertRaises(ValueError):bench_gate.verified_p999s(d,'L5')

    def test_legacy_exception_requires_committed_baseline_path(self):
        root=pathlib.Path(__file__).resolve().parents[2]
        values=bench_gate.verified_p999s(root/'baselines/2026-08-29-pinned-timer-campaign','L5',baseline=True)
        self.assertEqual(len(values),3)
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d)/'L5.summary.json').write_text(json.dumps({k:v for k,v in GOOD.items() if k!='mode'}))
            with self.assertRaises(ValueError):bench_gate.verified_p999s(d,'L5',baseline=True)


if __name__ == "__main__":
    unittest.main()

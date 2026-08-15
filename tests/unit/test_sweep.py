import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import sweep

class PlanLevels(unittest.TestCase):
    def test_chain_breaks_at_first_skipped_level(self):
        runnable, stopped = sweep.plan_levels(sweep.LEVELS, cpu=None)
        self.assertEqual([l[0] for l in runnable], ["L0", "L1", "L2", "L3"])
        self.assertIn("--cpu", stopped)

    def test_full_chain_with_cpu(self):
        runnable, stopped = sweep.plan_levels(sweep.LEVELS, cpu=3)
        self.assertEqual([l[0] for l in runnable],
                         ["L0", "L1", "L2", "L3", "L4", "L5"])
        self.assertIsNone(stopped)

class RowOk(unittest.TestCase):
    def test_rejects_unapplied_mitigation(self):
        self.assertFalse(sweep.row_ok({
            "applied": {"fifo": False, "mlock": True, "cpu": True},
            "cycles": 1000, "cycles_requested": 1000}))
        self.assertTrue(sweep.row_ok({
            "applied": {"fifo": True, "mlock": True, "cpu": True},
            "cycles": 1000, "cycles_requested": 1000}))

    def test_missing_applied_is_rejected(self):
        self.assertFalse(sweep.row_ok({}))

    def test_rejects_short_run(self):
        self.assertFalse(sweep.row_ok({
            "applied": {"fifo": True, "mlock": True, "cpu": True},
            "cycles": 500, "cycles_requested": 1000}))

class RowProblem(unittest.TestCase):
    def test_good_row_has_no_problem(self):
        self.assertIsNone(sweep.row_problem({
            "applied": {"fifo": True, "mlock": True, "cpu": True},
            "cycles": 1000, "cycles_requested": 1000}))

    def test_unapplied_mitigation_reason(self):
        self.assertEqual(sweep.row_problem({
            "applied": {"fifo": False, "mlock": True, "cpu": True},
            "cycles": 1000, "cycles_requested": 1000}),
            "config was not applied")

    def test_short_run_reason(self):
        self.assertEqual(sweep.row_problem({
            "applied": {"fifo": True, "mlock": True, "cpu": True},
            "cycles": 500, "cycles_requested": 1000}),
            "incomplete run or pre-integrity summary format")

if __name__ == "__main__":
    unittest.main()

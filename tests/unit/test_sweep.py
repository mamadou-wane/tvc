import os, sys, pathlib, tempfile, unittest
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
                         ["L0", "L1", "L2", "L3", "L4", "L5", "L6"])
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

class AggregateRow(unittest.TestCase):
    def summary(self, config, values, dropped, missed):
        return {
            "config": config,
            "cycles": 1000,
            "jitter_us": {
                "p50": values[0],
                "p99": values[1],
                "p99.9": values[2],
                "p99.9_naive": values[3],
                "p99.99": values[4],
                "max": values[5],
            },
            "dropped_samples": dropped,
            "missed_deadlines": missed,
        }

    def test_aggregates_repeats_without_mutating_inputs(self):
        good = [
            self.summary("first", [10, 30, 50, 70, 90, 110], 1, 4),
            self.summary("second", [30, 10, 70, 90, 50, 150], 2, 5),
            self.summary("third", [20, 20, 60, 80, 70, 130], 3, 6),
        ]

        row = sweep.aggregate_row("L2", good)

        self.assertEqual(row["dropped_samples"], 6)
        self.assertEqual(row["missed_deadlines"], 15)
        self.assertEqual(row["jitter_us"]["max"], 150)
        self.assertEqual(row["jitter_us"]["p50"], 20)
        self.assertEqual(row["jitter_us"]["p99"], 20)
        self.assertEqual(row["jitter_us"]["p99.9"], 60)
        self.assertEqual(row["jitter_us"]["p99.9_naive"], 80)
        self.assertEqual(row["jitter_us"]["p99.99"], 70)
        self.assertEqual(row["p999_spread"], (50, 70))
        self.assertEqual(row["p9999_spread"], (50, 90))
        self.assertEqual(row["config"], "first")
        self.assertEqual(row["label"], "L2")
        self.assertEqual(good[0]["jitter_us"]["p99.9"], 50)

    def test_single_summary_passes_through_without_spreads(self):
        good = [self.summary("only", [10, 20, 30, 40, 50, 60], 7, 8)]

        row = sweep.aggregate_row("L0", good)

        self.assertEqual(row["jitter_us"], good[0]["jitter_us"])
        self.assertEqual(row["dropped_samples"], 7)
        self.assertEqual(row["missed_deadlines"], 8)
        self.assertIsNone(row["p999_spread"])
        self.assertIsNone(row["p9999_spread"])

class BinaryIsStale(unittest.TestCase):
    def test_stale_when_source_newer_than_binary(self):
        with tempfile.TemporaryDirectory() as d:
            binary = pathlib.Path(d) / "bin"
            source = pathlib.Path(d) / "main.cpp"
            binary.write_text("bin")
            source.write_text("src")
            now = 1_700_000_000
            os.utime(binary, (now, now))
            os.utime(source, (now + 10, now + 10))
            self.assertTrue(sweep.binary_is_stale(str(binary), [str(source)]))

    def test_fresh_when_binary_newer_than_all_sources(self):
        with tempfile.TemporaryDirectory() as d:
            binary = pathlib.Path(d) / "bin"
            source = pathlib.Path(d) / "main.cpp"
            binary.write_text("bin")
            source.write_text("src")
            now = 1_700_000_000
            os.utime(source, (now, now))
            os.utime(binary, (now + 10, now + 10))
            self.assertFalse(sweep.binary_is_stale(str(binary), [str(source)]))

    def test_missing_binary_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            source = pathlib.Path(d) / "main.cpp"
            source.write_text("src")
            missing = pathlib.Path(d) / "no_such_binary"
            self.assertFalse(sweep.binary_is_stale(str(missing), [str(source)]))

class ParseCpuList(unittest.TestCase):
    def test_ranges_and_single_cpus(self):
        self.assertEqual(sweep.parse_cpu_list("6-7\n"), {6, 7})
        self.assertEqual(sweep.parse_cpu_list("0,2-5,8"), {0, 2, 3, 4, 5, 8})
        self.assertEqual(sweep.parse_cpu_list("3"), {3})

    def test_blank_input(self):
        self.assertEqual(sweep.parse_cpu_list(""), set())
        self.assertEqual(sweep.parse_cpu_list("\n"), set())

class ReadOnlineIsolated(unittest.TestCase):
    def test_reads_online_and_isolated(self):
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d, "online").write_text("0-15\n")
            pathlib.Path(d, "isolated").write_text("6-7\n")
            self.assertEqual(sweep.read_online_isolated(d),
                             (set(range(16)), {6, 7}))

    def test_missing_isolated_uses_empty_set(self):
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d, "online").write_text("0-3\n")
            self.assertEqual(sweep.read_online_isolated(d),
                             ({0, 1, 2, 3}, set()))

    def test_empty_isolated_is_empty_set(self):
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d, "online").write_text("0-3\n")
            pathlib.Path(d, "isolated").write_text("")
            self.assertEqual(sweep.read_online_isolated(d),
                             ({0, 1, 2, 3}, set()))

    def test_missing_files_use_host_fallbacks(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(sweep.read_online_isolated(d),
                             (set(range(os.cpu_count() or 1)), set()))

class AffinityProblem(unittest.TestCase):
    def test_full_affinity_is_healthy_with_isolated_cpus(self):
        online = set(range(16))
        self.assertIsNone(sweep.affinity_problem(online, online, {6, 7}))

    def test_only_measurement_core_mentions_drain(self):
        reason = sweep.affinity_problem({7}, set(range(16)), {6, 7})
        self.assertIsNotNone(reason)
        self.assertIn("drain", reason)
        self.assertIn("7", reason)

    def test_housekeeping_restriction_does_not_mention_drain(self):
        reason = sweep.affinity_problem(set(range(16)) - {6, 7},
                                        set(range(16)), {6, 7})
        self.assertIsNotNone(reason)
        self.assertNotIn("drain", reason)

    def test_container_shape_is_healthy(self):
        online = {0, 1, 2, 3}
        self.assertIsNone(sweep.affinity_problem(online, online, set()))

if __name__ == "__main__":
    unittest.main()

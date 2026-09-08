import os, subprocess, tempfile, unittest

BIN = os.environ["TVC_BIN"]

def run(*extra, cwd):
    return subprocess.run(
        [BIN, "--label=g", f"--out={cwd}", "--rate=1000",
         "--cycles=1000", "--warmup=50", *extra],
        capture_output=True, text=True)

class AllocGuard(unittest.TestCase):
    def test_count_mode_sees_naive_log(self):
        with tempfile.TemporaryDirectory() as d:
            p = run("--alloc-guard=count", cwd=d)
            self.assertEqual(p.returncode, 0)
            self.assertIn("alloc guard", p.stdout)
            self.assertNotIn(" 0 allocations", p.stdout)

    def test_clean_path_is_clean(self):
        with tempfile.TemporaryDirectory() as d:
            p = run("--alloc-guard=count", "--no-naive-log", cwd=d)
            self.assertEqual(p.returncode, 0)
            self.assertIn("hot path is clean", p.stdout)

    def test_clean_path_with_telemetry_is_clean(self):
        with tempfile.TemporaryDirectory() as d:
            p = run("--alloc-guard=count", "--no-naive-log", "--telemetry", cwd=d)
            self.assertEqual(p.returncode, 0)
            self.assertIn("hot path is clean", p.stdout)

    def test_record_selections_keep_count_and_abort_paths_clean(self):
        for record in ("v1", "control"):
            for mode in ("count", "abort"):
                with self.subTest(record=record, mode=mode), tempfile.TemporaryDirectory() as d:
                    p = run(f"--alloc-guard={mode}", "--no-naive-log", "--telemetry",
                            f"--record={record}", cwd=d)
                    self.assertEqual(p.returncode, 0, p.stderr)
                    if mode == "count":
                        self.assertIn("hot path is clean", p.stdout)

if __name__ == "__main__":
    unittest.main()

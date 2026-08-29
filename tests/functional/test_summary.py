import json, os, pathlib, subprocess, tempfile, unittest

BIN = os.environ["TVC_BIN"]

def run(*extra, cwd):
    return subprocess.run(
        [BIN, "--label=t", f"--out={cwd}", "--rate=1000",
         "--cycles=2000", "--warmup=100", *extra],
        capture_output=True, text=True)

class SummaryOutputs(unittest.TestCase):
    def test_files_and_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = run(cwd=d)
            self.assertEqual(p.returncode, 0, p.stderr)
            for suffix in ("jitter", "jitter_naive", "exec"):
                self.assertTrue((pathlib.Path(d) / f"t.{suffix}.csv").exists(),
                                f"missing t.{suffix}.csv")
            s = json.loads((pathlib.Path(d) / "t.summary.json").read_text())
            self.assertIn("p99.9_naive", s["jitter_us"])
            self.assertNotIn("p99.9_corrected", s["jitter_us"])
            self.assertEqual(s["dropped_samples"], 0)
            env = s["env"]
            self.assertIn(env["timer_migration"], (-1, 0, 1))
            # new env keys append, so older baselines stay a strict prefix
            self.assertEqual(list(env)[-2:], ["cpuidle", "timer_migration"])

if __name__ == "__main__":
    unittest.main()

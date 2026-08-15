import json, os, pathlib, subprocess, tempfile, unittest

BIN = os.environ["TVC_BIN"]

class StrictExits(unittest.TestCase):
    def test_bad_arg_value_rejected(self):
        p = subprocess.run([BIN, "--cpu=abc"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)

    def test_bad_label_rejected(self):
        p = subprocess.run([BIN, "--label=a/b"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)

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
            for key in ("ac_online", "governor", "epp", "pkg_temp_c"):
                self.assertIn(key, s["env"])

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

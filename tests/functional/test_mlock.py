import os, subprocess, tempfile, unittest

BIN = os.environ["TVC_BIN"]

class MlockPrefault(unittest.TestCase):
    @unittest.skipIf(os.environ.get("TVC_ASAN") == "1", "mlockall + ASan shadow is an environment artifact")
    def test_mlock_survives_default_stack_ulimit(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run(
                ["bash", "-c",
                 f"ulimit -s 8192; exec {BIN} --label=m --out={d} "
                 "--rate=1000 --cycles=500 --warmup=50 --mlock"],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
            self.assertIn("mlock      ok", p.stdout)
            self.assertIn("prefaulted", p.stdout)

if __name__ == "__main__":
    unittest.main()

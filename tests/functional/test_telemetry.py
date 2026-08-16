import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from ground import wire

BIN = os.environ["TVC_BIN"]


class Telemetry(unittest.TestCase):
    def test_recording_matches_summary(self):
        with tempfile.TemporaryDirectory() as d:
            rc = subprocess.run(
                [BIN, "--label=t", f"--out={d}", "--rate=1000",
                 "--cycles=2000", "--warmup=100", "--telemetry"]).returncode
            self.assertEqual(rc, 0)
            rec_path = pathlib.Path(d) / "t.telemetry.tvcrec"
            header, records, ctr = wire.read_recording(rec_path)
            self.assertTrue(header["schema_known"])
            self.assertEqual(len(records), 2100)          # cycles + warmup
            self.assertEqual(sum(1 for r in records if r.tick >= 100), 2000)
            self.assertEqual(ctr["crc_errors"], 0)
            self.assertEqual(ctr["lost"], 0)
            self.assertEqual(ctr["seq_discontinuities"], 0)
            self.assertEqual(ctr["skipped_bytes"], 0)
            self.assertEqual(records[-1].drops, 0)        # 4096-slot ring > run
            summary = json.loads((pathlib.Path(d) / "t.summary.json").read_text())
            self.assertTrue(summary["applied"]["telemetry"])
            self.assertIn("telemetry", summary["config"])
            t = summary["telemetry"]
            self.assertEqual(t["records"], 2100)
            self.assertEqual(t["dropped"], 0)
            self.assertEqual(t["bytes"], rec_path.stat().st_size)

    def test_no_flag_no_recording(self):
        with tempfile.TemporaryDirectory() as d:
            rc = subprocess.run(
                [BIN, "--label=t", f"--out={d}", "--rate=1000",
                 "--cycles=500", "--warmup=50"]).returncode
            self.assertEqual(rc, 0)
            self.assertFalse((pathlib.Path(d) / "t.telemetry.tvcrec").exists())
            summary = json.loads((pathlib.Path(d) / "t.summary.json").read_text())
            self.assertNotIn("telemetry", summary)
            self.assertTrue(summary["applied"]["telemetry"])  # not requested

    def test_unwritable_outdir_is_failed_mitigation(self):
        rc = subprocess.run(
            [BIN, "--label=t", "--out=/proc/no_such_dir", "--rate=1000",
             "--cycles=100", "--warmup=10", "--telemetry"]).returncode
        self.assertIn(rc, (2, 4))   # open fails: mitigation failed (2); the
                                    # summary write also fails there (4 wins
                                    # only if wrote_ok check precedes)

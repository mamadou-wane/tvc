import json
import math
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
            self.assertEqual(summary["config"], "sleep_for naive-log telemetry")
            t = summary["telemetry"]
            self.assertEqual(t["records"], 2100)
            self.assertEqual(t["dropped"], 0)
            self.assertEqual(t["bytes"], rec_path.stat().st_size)

    def test_explicit_v1_keeps_legacy_recording(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run(
                [BIN, "--label=t", f"--out={d}", "--rate=1000",
                 "--cycles=100", "--warmup=5", "--telemetry", "--record=v1"],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            path = pathlib.Path(d) / "t.telemetry.tvcrec"
            self.assertFalse((pathlib.Path(d) / "t.control.tvcrec").exists())
            header, records, ctr = wire.read_recording(path)
            self.assertEqual(header["version"], 1)
            self.assertEqual(header["schema_hash"], 0xA871CD84)
            self.assertEqual([r.tick for r in records], list(range(105)))
            self.assertEqual(ctr["frames_ok"], 105)
            self.assertTrue(all(value == 0 for key, value in ctr.items()
                                if key != "frames_ok"), ctr)
            self.assertEqual(path.stat().st_size, 32 + 105 * 70)
            summary = json.loads((pathlib.Path(d) / "t.summary.json").read_text())
            self.assertEqual(summary["config"], "sleep_for naive-log telemetry")
            self.assertEqual(summary["cycles"], 100)
            self.assertEqual(summary["cycles_requested"], 100)
            self.assertEqual(summary["telemetry"],
                             {"records": 105, "dropped": 0, "bytes": path.stat().st_size})

    def test_control_records_harness_fields_and_summary(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run(
                [BIN, "--label=t", f"--out={d}", "--rate=1000",
                 "--cycles=100", "--warmup=5", "--record=control", "--telemetry"],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            path = pathlib.Path(d) / "t.control.tvcrec"
            self.assertFalse((pathlib.Path(d) / "t.telemetry.tvcrec").exists())
            header, records, ctr = wire.read_typed_recording(path, expected_type=6)
            self.assertEqual(header["version"], 1)
            self.assertEqual(header["schema_hash"], 0xADFA94C8)
            self.assertGreater(header["start_monotonic_ns"], 0)
            self.assertGreater(header["start_epoch_ns"], 0)
            self.assertEqual([r["tick"] for r in records], list(range(105)))
            self.assertEqual(ctr["frames_ok"], 105)
            self.assertTrue(all(value == 0 for key, value in ctr.items()
                                if key != "frames_ok"), ctr)
            frames, _ = wire.decode_stream(path.read_bytes()[32:])
            self.assertEqual([(ftype, seq, len(payload)) for ftype, seq, payload in frames],
                             [(6, tick, 128) for tick in range(105)])
            zero_fields = (
                "sensor_send_ns", "rx_ns", "tx_ns", "i_state", "d_prev",
                "staleness", "rx_count", "discarded_old", "discarded_superseded",
                "discarded_other", "ack_cmd_seq", "state", "reason", "flags", "ack_status")
            previous_theta = 0.02
            for tick, record in enumerate(records):
                with self.subTest(tick=tick):
                    for field in zero_fields:
                        self.assertEqual(record[field], 0, field)
                    self.assertEqual(record["sensor_tick"], 0xFFFFFFFFFFFFFFFF)
                    self.assertEqual(record["drops"], 0)
                    self.assertEqual(record["deadline_ns"], records[0]["deadline_ns"] + tick * 1_000_000)
                    self.assertGreater(record["woke_ns"], 0)
                    self.assertGreaterEqual(record["done_ns"], record["woke_ns"])
                    self.assertTrue(all(math.isfinite(record[field])
                                        for field in ("theta", "omega", "cmd")))
                    self.assertLessEqual(abs(record["cmd"]), 0.12)
                    self.assertAlmostEqual(record["theta"], previous_theta + record["omega"] * 0.001)
                    previous_theta = record["theta"]
            self.assertEqual(records[0]["cmd"], -0.12)
            self.assertLess(records[0]["omega"], 0)
            self.assertNotEqual(records[-1]["theta"], records[0]["theta"])
            self.assertEqual(path.stat().st_size, 32 + 105 * 142)
            summary = json.loads((pathlib.Path(d) / "t.summary.json").read_text())
            self.assertTrue(summary["applied"]["telemetry"])
            self.assertEqual(summary["config"], "sleep_for naive-log telemetry record:control")
            self.assertEqual(summary["cycles"], 100)
            self.assertEqual(summary["cycles_requested"], 100)
            self.assertEqual(summary["telemetry"],
                             {"records": 105, "dropped": 0, "bytes": path.stat().st_size})

    def test_record_selection_rejects_invalid_values(self):
        for value in ("", "v2", "CONTROL", "control-extra"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as d:
                p = subprocess.run(
                    [BIN, f"--out={d}", "--rate=1000", "--cycles=10", "--warmup=0",
                     "--telemetry", f"--record={value}"],
                    capture_output=True, text=True)
                self.assertEqual(p.returncode, 1)
                self.assertEqual(list(pathlib.Path(d).iterdir()), [])

    def test_control_selection_requires_telemetry(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run(
                [BIN, f"--out={d}", "--rate=1000", "--cycles=10", "--warmup=0",
                 "--record=control"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertEqual(list(pathlib.Path(d).iterdir()), [])

    def test_v1_selection_does_not_enable_telemetry(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run(
                [BIN, "--label=t", f"--out={d}", "--rate=1000",
                 "--cycles=100", "--warmup=5", "--record=v1"],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(list(pathlib.Path(d).glob("*.tvcrec")), [])
            summary = json.loads((pathlib.Path(d) / "t.summary.json").read_text())
            self.assertNotIn("telemetry", summary)
            self.assertEqual(summary["config"], "sleep_for naive-log")

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
        for selection in ((), ("--record=v1",), ("--record=control",)):
            with self.subTest(selection=selection):
                rc = subprocess.run(
                    [BIN, "--label=t", "--out=/proc/no_such_dir", "--rate=1000",
                     "--cycles=100", "--warmup=10", "--telemetry", *selection]).returncode
                # Open failure is 2; a failed summary write takes precedence as 4.
                self.assertIn(rc, (2, 4))

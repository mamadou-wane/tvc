"""Same-toolchain per-ISA comparison with frozen 2a937cd; no timing claim."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BIN = os.environ['TVC_BIN']


class HarnessWorkload(unittest.TestCase):
    def test_frozen_twenty_thousand_cycle_columns(self):
        arch = platform.machine()
        if arch not in ('aarch64', 'x86_64'):
            self.skipTest(f'no same-toolchain harness contract for {arch}')
        directory = ROOT / 'tests/golden/harness'
        manifest = json.loads((directory / 'manifest.json').read_text())
        entry = manifest['fixtures'][arch]
        self.assertEqual(entry['source_commit'], '2a937cdbc0861d978e83e059bb13fb66467eac55')
        expected = (directory / entry['file']).read_bytes()
        self.assertEqual(hashlib.sha256(expected).hexdigest(), entry['sha256'])
        with tempfile.TemporaryDirectory() as out:
            result = subprocess.run([BIN, '--telemetry', '--cycles=20000', '--warmup=0',
                                     '--label=L6-20000', '--out=' + out],
                                    capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            columns = subprocess.run([sys.executable, str(ROOT / 'scripts/golden_csv.py'),
                                      '--columns', 'tick,theta,cmd',
                                      str(Path(out) / 'L6-20000.telemetry.tvcrec')],
                                     capture_output=True, timeout=30)
            self.assertEqual(columns.returncode, 0, columns.stderr)
            self.assertEqual(columns.stdout, expected)

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]


class HeadlessCliTests(unittest.TestCase):
    def test_single_scenario_cli_keeps_check_separate_from_execution(self):
        for check, code in ((False, 0), (True, 1)):
            args = [sys.executable, '-B', '-m', 'sim.run_headless', '--scenario', 'S4-open',
                    '--seed', '1', '--delay-ticks', '0'] + (['--check'] if check else [])
            result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, code, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['ticks'], 300)
            self.assertEqual(report['reason'], 'NOT_SETTLED')
            self.assertFalse(report['clauses']['termination'])

    def test_single_s2_case_passes_each_delay_without_campaign(self):
        for delay in (0, 1):
            result = subprocess.run([sys.executable, '-B', '-m', 'sim.run_headless',
                                     '--scenario', 'S2-gust', '--loss', '0.30',
                                     '--seed', '1', '--delay-ticks', str(delay), '--check'],
                                    cwd=ROOT, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(all(json.loads(result.stdout)['clauses'].values()))

    def test_bad_input_fails_without_trace_output(self):
        result = subprocess.run([sys.executable, '-B', '-m', 'sim.run_headless',
                                 '--scenario', 'S2-gust', '--loss', 'nan'],
                                cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')

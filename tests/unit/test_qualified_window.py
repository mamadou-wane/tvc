"""Qualified L8 measurement window; synthetic rows, never timing evidence."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import bench_gate, latency, sweep
from tests.unit.test_discipline import good
from tests.unit.test_evidence_analysis import row
from tests.unit import test_peer_cpu

WINDOW = dict(cycles=300000, cycles_requested=300000, warmup=5000, total_cycles=305000, period_us=2000.0)
BASELINE = Path(__file__).resolve().parents[2] / 'baselines/2026-09-15-phase-calibration'


def qualified():
    s = row()['summary']
    s.update(WINDOW)
    return s


def session(p, cycles, warmup, peer_cpu):
    """A complete L8 results directory (roster, result, replay, reconciliation,
    summary) at the given window; recordings are patched out by the caller."""
    _, run, replay = test_peer_cpu.Provenance.fixture(test_peer_cpu.Provenance(), peer_cpu)
    ticks = cycles + warmup + 33
    argv = run['vehicle_argv']
    argv[argv.index('--cycles=1000')] = f'--cycles={cycles}'
    argv[argv.index('--warmup=10')] = f'--warmup={warmup}'
    peer = run['sim_argv']
    peer[peer.index('--ticks=1043')] = f'--ticks={ticks}'
    run.update(cycles=cycles, warmup=warmup)
    replay.update(vehicle_argv=argv, sim_argv=peer, ticks=ticks, ticks_resolved=ticks)
    item = row()
    s = item['summary']
    s.update(label='L8', cycles=cycles, cycles_requested=cycles, warmup=warmup,
             total_cycles=cycles + warmup, period_us=2000.0, phase_us=400,
             link_recorded=dict(served=cycles, consumed=cycles, actuator_tx_fail=0),
             latency_us={'count': cycles, 'p99.9': 1000.0, 'max': 2000.0})
    if peer_cpu is not None:
        for state in s['env']['cpuidle']['states']:
            state['disabled'] = 3
    for suffix, value in (('.summary.json', s), ('.result.json', run), ('.replay.json', replay),
                          ('.reconcile.json', item['reconciliation'])):
        (p / ('L8' + suffix)).write_text(json.dumps(value))
    (p / 'sweep.json').write_text(json.dumps(dict(format='tvc-sweep-1', complete=True, runs=[run])))


def capture(tool, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        rc = tool(argv)
    return rc, out.getvalue()


class Window(unittest.TestCase):
    def test_exact_qualified_window_passes(self):
        self.assertIsNone(bench_gate.qualified_window_problem(qualified()))
        paths = sorted(BASELINE.glob('L8.*.summary.json'))
        self.assertEqual(len(paths), 9)
        for path in paths:
            with self.subTest(path=path.name):
                self.assertIsNone(bench_gate.qualified_window_problem(sweep.read_json(path)))
        s = qualified(); s['period_us'] = 2000          # the same period, integer-typed
        self.assertIsNone(bench_gate.qualified_window_problem(s))

    def test_every_other_window_is_refused_by_field(self):
        cases = [('cycles', 30000), ('cycles', 299999), ('cycles', 300001),
                 ('cycles_requested', 30000), ('cycles_requested', 299999), ('cycles_requested', 300001),
                 ('warmup', 0), ('warmup', 4999), ('warmup', 5001),
                 ('total_cycles', 300000), ('total_cycles', 304999), ('total_cycles', 305001),
                 ('period_us', 1000.0), ('period_us', 1999.0), ('period_us', 2000.5), ('period_us', 4000.0)]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                s = qualified(); s[key] = value
                problem = bench_gate.qualified_window_problem(s)
                self.assertIn('qualified L8 window', problem)
                self.assertIn(key, problem)
        short = qualified()
        short.update(cycles=30000, cycles_requested=30000, total_cycles=35000)
        self.assertIsNone(bench_gate.discipline_problem(short))   # otherwise perfect
        self.assertIn('qualified L8 window', bench_gate.qualified_window_problem(short))

    def test_malformed_or_missing_window_fields_fail_closed(self):
        for key, expected in WINDOW.items():
            s = qualified(); del s[key]
            with self.subTest(missing=key):
                self.assertIn('qualified L8 window', bench_gate.qualified_window_problem(s))
            for value in (None, str(expected), True, [expected], float('nan'), float('inf')):
                s = qualified(); s[key] = value
                with self.subTest(key=key, value=value):
                    self.assertIn('qualified L8 window', bench_gate.qualified_window_problem(s))
        for key in ('cycles', 'cycles_requested', 'warmup', 'total_cycles'):
            s = qualified(); s[key] = float(WINDOW[key])
            with self.subTest(float=key):
                self.assertIn('qualified L8 window', bench_gate.qualified_window_problem(s))
        for summary in (None, [], 'summary', {}):
            with self.subTest(summary=summary):
                self.assertIn('qualified L8 window', bench_gate.qualified_window_problem(summary))


class Gate(unittest.TestCase):
    def test_harness_levels_never_consult_the_window(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'L5.r1.summary.json').write_text(json.dumps(good()))
            s = good(); s['label'] = 'L7.r1'; s['config'] += ' telemetry record:control'
            (p / 'L7.r1.summary.json').write_text(json.dumps(s))
            with patch.object(bench_gate, 'qualified_window_problem', side_effect=AssertionError('consulted')):
                rows = bench_gate.candidate_rows(p)
                self.assertEqual([item['prefix'].name for item in rows], ['L5.r1', 'L7.r1'])
                self.assertEqual(capture(bench_gate.main, ['--results', d])[0], 0)
                self.assertEqual(capture(bench_gate.main, ['--results', d, '--level', 'L7', '--no-baseline'])[0], 0)

    def test_short_l8_row_is_valid_development_data_but_not_evidence(self):
        for peer_cpu in (11, None):
            with self.subTest(peer_cpu=peer_cpu), tempfile.TemporaryDirectory() as d:
                p = Path(d); session(p, 30000, 5000, peer_cpu)
                self.assertEqual(sweep.roster_row(p / 'L8')['cycles'], 30000)
                self.assertEqual(sweep.session_peer(p), peer_cpu)
                self.assertIsNone(bench_gate.discipline_problem(sweep.read_json(p / 'L8.summary.json'), peer_cpu))
                with patch.object(bench_gate.sweep, 'audit_freerun'), patch.object(latency, 'verify_recorded_statistics'):
                    with self.assertRaises(ValueError) as caught:
                        bench_gate.candidate_rows(p)
                    text = str(caught.exception)
                    self.assertIn('L8.summary.json', text); self.assertIn('qualified L8 window', text)
                    self.assertNotIn('cpuidle', text); self.assertNotIn('discipline', text)
                    rc, text = capture(bench_gate.main, ['--results', d, '--level', 'L8', '--no-baseline'])
                    self.assertEqual(rc, 1); self.assertIn('qualified L8 window', text)
                    rc, text = capture(latency.main, ['--results', d])
                    self.assertEqual(rc, 1); self.assertIn('qualified L8 window', text)

    def test_exact_window_row_proceeds_through_the_existing_checks(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); session(p, 300000, 5000, 11)
            with patch.object(bench_gate.sweep, 'audit_freerun') as audit, \
                    patch.object(latency, 'verify_recorded_statistics') as verify:
                rows = bench_gate.candidate_rows(p)
                audit.assert_called_once_with(p / 'L8')
                verify.assert_called_once()
                self.assertEqual(len(rows), 1); item = rows[0]
                self.assertEqual((item['peer_cpu'], item['run']['cycles'], item['run']['peer_cpu']), (11, 300000, 11))
                self.assertEqual(item['replay'], dict(loss=dict(p_up=0.0, p_down=0.0)))
                self.assertTrue(item['reconciliation']['eligible'])
                self.assertEqual(latency.evidence_checks(item)['problems'], [])
                self.assertEqual(capture(bench_gate.main, ['--results', d, '--level', 'L8', '--no-baseline'])[0], 0)
                self.assertEqual(capture(latency.main, ['--results', d])[0], 0)
                # the window is not a bypass: the same row with the pair alone still fails discipline
                s = sweep.read_json(p / 'L8.summary.json')
                for state in s['env']['cpuidle']['states']:
                    state['disabled'] = 2
                (p / 'L8.summary.json').write_text(json.dumps(s))
                with self.assertRaises(ValueError) as caught:
                    bench_gate.candidate_rows(p)
                self.assertIn('cpuidle', str(caught.exception))
                self.assertNotIn('qualified L8 window', str(caught.exception))


if __name__ == '__main__':
    unittest.main()

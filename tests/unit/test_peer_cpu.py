"""Free-run peer CPU discipline: declaration, topology and idle-state checks,
launch-time affinity verification and roster/replay provenance. No timing claim."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import sweep


def sysfs(root, online='0-7', isolated='6-7', siblings=None, disabled=()):
    """Minimal /sys/devices/system/cpu tree: cores are (0,1) (2,3) (4,5) (6,7)
    unless siblings overrides; four idle states per CPU, disabled where listed."""
    cpu = Path(root) / 'cpu'
    cpu.mkdir(parents=True)
    (cpu / 'online').write_text(online + '\n')
    (cpu / 'isolated').write_text(isolated + '\n')
    for n in range(8):
        d = cpu / f'cpu{n}'
        (d / 'topology').mkdir(parents=True)
        pair = (siblings or {}).get(n, f'{n - n % 2}-{n - n % 2 + 1}')
        (d / 'topology' / 'thread_siblings_list').write_text(pair + '\n')
        for s, name in enumerate(('POLL', 'C1', 'C2', 'C3')):
            state = d / 'cpuidle' / f'state{s}'
            state.mkdir(parents=True)
            (state / 'name').write_text(name + '\n')
            (state / 'disable').write_text(('1' if n in disabled else '0') + '\n')
    return str(cpu)


def args(**overrides):
    base = dict(cycles=1000, warmup=5, repeat=1, rate=500.0, cpu=7, only=['L8'],
                phase_us='400', interleave=False, peer_cpu=None)
    base.update(overrides)
    return argparse.Namespace(**base)


class Declaration(unittest.TestCase):
    def test_short_l8_may_run_undeclared_and_records_no_peer_cpu(self):
        runs, _ = sweep.plan_runs(args())
        self.assertEqual([r['peer_cpu'] for r in runs], [None])

    def test_qualified_length_requires_a_declared_peer_cpu(self):
        with self.assertRaises(ValueError):
            sweep.plan_runs(args(cycles=300_000, warmup=5_000))
        runs, _ = sweep.plan_runs(args(cycles=300_000, warmup=5_000, peer_cpu=3))
        self.assertEqual([r['peer_cpu'] for r in runs], [3])

    def test_calibration_grid_requires_a_declared_peer_cpu(self):
        grid = dict(cycles=1000, repeat=3, interleave=True, phase_us='200,400,800')
        with self.assertRaises(ValueError):
            sweep.plan_runs(args(**grid))
        runs, _ = sweep.plan_runs(args(**grid, peer_cpu=3))
        self.assertEqual({r['peer_cpu'] for r in runs}, {3})
        self.assertEqual(len(runs), 9)

    def test_unprivileged_default_campaign_still_plans_l0_to_l3(self):
        runs, stopped = sweep.plan_runs(args(cpu=None, only=None, cycles=300_000, warmup=5_000))
        self.assertEqual([r['level'] for r in runs], ['L0', 'L1', 'L2', 'L3'])
        self.assertIn('L4', stopped)
        with self.assertRaises(ValueError):
            sweep.plan_runs(args(cpu=None, only=None, cycles=300_000, warmup=5_000, peer_cpu=3))

    def test_peer_cpu_applies_only_to_l8_and_harness_rows_are_unchanged(self):
        with self.assertRaises(ValueError):
            sweep.plan_runs(args(only=['L0', 'L5'], peer_cpu=3))
        harness, _ = sweep.plan_runs(args(only=None))
        self.assertEqual([r['level'] for r in harness], [f'L{n}' for n in range(9)])
        for row in harness[:8]:
            self.assertNotIn('peer_cpu', row)
        self.assertEqual(harness[4]['flags'], ['--abs-deadline', '--mlock', '--fifo=80', '--cpu=7'])
        self.assertIsNone(harness[8]['peer_cpu'])


class Topology(unittest.TestCase):
    def problem(self, cpu, vehicle=7, affinity=frozenset(range(8)), **tree):
        with tempfile.TemporaryDirectory() as d:
            return sweep.peer_cpu_problem(cpu, vehicle, set(affinity), sysfs=sysfs(d, **tree))

    def test_accepts_a_disciplined_housekeeping_cpu(self):
        self.assertIsNone(self.problem(3, disabled=(3, 6, 7)))

    def test_refuses_invalid_offline_masked_and_isolated_cpus(self):
        self.assertIn('invalid', self.problem(-1, disabled=(6, 7)))
        self.assertIn('invalid', self.problem(True, disabled=(6, 7)))
        self.assertIn('not online', self.problem(3, online='0-2,4-7', disabled=(3, 6, 7)))
        self.assertIn('inherited affinity', self.problem(3, affinity={0, 1, 2, 4, 5, 6, 7}, disabled=(3, 6, 7)))
        self.assertIn('isolated', self.problem(4, isolated='4-7', disabled=(4, 6, 7)))

    def test_refuses_the_vehicle_cpu_and_its_smt_sibling(self):
        self.assertIn('vehicle CPU', self.problem(7, disabled=(6, 7)))
        self.assertIn('sibling', self.problem(5, vehicle=4, isolated='4-5', disabled=(4, 5)))
        self.assertIn('sibling', self.problem(2, vehicle=4, isolated='4', siblings={4: '2,4'}, disabled=(2, 4)))
        self.assertIn('pinned vehicle', self.problem(3, vehicle=None, disabled=(3,)))

    def test_refuses_any_enabled_idle_state_and_missing_cpuidle(self):
        message = self.problem(3, disabled=(6, 7))
        self.assertIn('idle state', message)
        self.assertIn('cpupower -c 3 idle-set -D 0', message)
        with tempfile.TemporaryDirectory() as d:
            root = sysfs(d, disabled=(3, 6, 7))
            (Path(root) / 'cpu3' / 'cpuidle' / 'state2' / 'disable').write_text('0\n')
            self.assertIn('C2', sweep.peer_cpu_problem(3, 7, set(range(8)), sysfs=root))
            for state in (Path(root) / 'cpu3' / 'cpuidle').glob('state*'):
                for f in state.iterdir(): f.unlink()
                state.rmdir()
            self.assertIn('no cpuidle', sweep.peer_cpu_problem(3, 7, set(range(8)), sysfs=root))

    def test_provenance_records_verified_idle_states_and_siblings(self):
        with tempfile.TemporaryDirectory() as d:
            root = sysfs(d, disabled=(3, 6, 7))
            record = sweep.peer_provenance(3, sysfs=root)
            (Path(root) / 'cpu3' / 'topology' / 'thread_siblings_list').unlink()
            with self.assertRaises(ValueError):
                sweep.peer_provenance(3, sysfs=root)
        self.assertEqual(record['cpu'], 3)
        self.assertEqual(record['siblings'], [2, 3])
        self.assertEqual([s['name'] for s in record['idle_states']], ['POLL', 'C1', 'C2', 'C3'])
        self.assertTrue(all(s['disable'] == 1 for s in record['idle_states']))
        self.assertEqual(json.loads(json.dumps(record)), record)


@unittest.skipUnless(hasattr(os, 'sched_setaffinity'), 'Linux scheduler API required')
class Launch(unittest.TestCase):
    def test_child_affinity_is_exactly_the_peer_cpu_before_it_runs(self):
        before = os.sched_getaffinity(0)
        cpu = max(before)
        process, verified = sweep.launch_peer([sys.executable, '-c', 'import time; time.sleep(30)'], cpu,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        try:
            self.assertEqual(os.sched_getaffinity(process.pid), {cpu})
            self.assertEqual(verified, dict(affinity=[cpu], policy='SCHED_OTHER'))
            self.assertEqual(os.sched_getaffinity(0), before)
        finally:
            process.kill(); process.wait()

    def test_unreachable_cpu_fails_closed_without_a_running_child(self):
        with self.assertRaises(ValueError):
            sweep.launch_peer([sys.executable, '-c', 'import time; time.sleep(30)'], 1 << 20,
                              stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


class DeclaredRow(unittest.TestCase):
    """run_row's declared-peer branch with the launch mocked: refusal before the
    spawn, provenance merged into result and replay, idle change after the row."""
    def run_row(self, problems, idle_after=None):
        from unittest.mock import patch
        from scripts import run_scenario
        import itertools
        runs, _ = sweep.plan_runs(args(peer_cpu=11))
        plan = runs[0]; plan['flags'].append('--cpu=7')
        record = dict(cpu=11, siblings=[10, 11], idle_states=[dict(name='POLL', disable=1)])
        spawned = []
        class Fake:
            returncode = None; stdout = None
            def poll(self): self.returncode = 0; return 0
        def launch(argv, cpu, **kw):
            spawned.append((argv, cpu)); return Fake(), dict(affinity=[cpu], policy='SCHED_OTHER')
        with tempfile.TemporaryDirectory() as d, \
             patch.object(sweep.subprocess, 'Popen', return_value=Fake()), \
             patch.object(sweep, 'peer_cpu_problem', side_effect=problems), \
             patch.object(sweep, 'peer_provenance', return_value=dict(record)), \
             patch.object(sweep, 'launch_peer', side_effect=launch), \
             patch.object(sweep, 'idle_states', return_value=idle_after if idle_after is not None else record['idle_states']), \
             patch.object(sweep, 'read_json', return_value=dict(delay_ticks=1)), \
             patch.object(sweep, 'audit_freerun', return_value=dict(mode='freerun', applied=dict(mlock=False, cpu=True, fifo=False, telemetry=True, link=True, ground=False), config='mode:freerun abs-deadline cpu:7 telemetry record:control', ground=dict(requested=False), cycles=1000, cycles_requested=1000)), \
             patch.object(sweep.time, 'sleep'), patch.object(run_scenario, 'stop_process'), \
             patch.object(run_scenario, 'ready_line', return_value=dict(consts='0xe77201ca', sensor_port='1')):
            rc = sweep.run_row(plan, '/bin/true', Path(d))
            written = json.loads((Path(d) / 'L8.replay.json').read_text()) if (Path(d) / 'L8.replay.json').exists() else None
        return rc, plan, spawned, written

    def test_refusal_before_the_spawn_fails_the_row(self):
        rc, plan, spawned, replay = self.run_row(['idle state C3 of peer CPU 11 is enabled'])
        self.assertEqual((rc, plan['complete'], plan['peer'], spawned, replay), (1, False, None, [], None))
        self.assertIn('C3', plan['error'])

    def test_success_records_merged_provenance_in_result_and_replay(self):
        rc, plan, spawned, replay = self.run_row([None])
        self.assertEqual(rc, 0, plan['error'])
        self.assertEqual(spawned[0][1], 11)
        self.assertEqual(plan['peer'], dict(cpu=11, siblings=[10, 11], idle_states=[dict(name='POLL', disable=1)],
                                            affinity=[11], policy='SCHED_OTHER'))
        self.assertEqual((replay['peer_cpu'], replay['peer']), (11, plan['peer']))

    def test_idle_states_changed_during_the_row_fail_it(self):
        rc, plan, spawned, replay = self.run_row([None], idle_after=[dict(name='POLL', disable=0)])
        self.assertEqual((rc, plan['complete']), (1, False))
        self.assertIn('changed during the run', plan['error'])


class Provenance(unittest.TestCase):
    def fixture(self, peer_cpu=3):
        from tests.unit.test_discipline import RosterMetadata
        summary, row, replay = RosterMetadata.fixture(RosterMetadata(), None)
        peer = None if peer_cpu is None else dict(
            cpu=peer_cpu, siblings=[2, 3], affinity=[peer_cpu], policy='SCHED_OTHER',
            idle_states=[dict(name=n, disable=1) for n in ('POLL', 'C1', 'C2', 'C3')])
        row.update(peer_cpu=peer_cpu, peer=peer); replay.update(peer_cpu=peer_cpu, peer=peer)
        return summary, row, replay

    def check(self, summary, row, replay):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            for suffix, value in (('.summary.json', summary), ('.result.json', row), ('.replay.json', replay)):
                (p / ('L8' + suffix)).write_text(json.dumps(value))
            (p / 'sweep.json').write_text(json.dumps(dict(format='tvc-sweep-1', complete=True, runs=[row])))
            return sweep.roster_row(p / 'L8')

    def test_declared_peer_provenance_round_trips(self):
        summary, row, replay = self.fixture()
        self.assertEqual(self.check(summary, row, replay), row)
        summary, row, replay = self.fixture(peer_cpu=None)
        self.assertEqual(self.check(summary, row, replay), row)

    def test_qualified_length_row_needs_a_declared_peer(self):
        summary, row, replay = self.fixture(peer_cpu=None)
        summary.update(cycles=300_000, cycles_requested=300_000, total_cycles=300_010)
        row['cycles'] = 300_000
        row['vehicle_argv'][row['vehicle_argv'].index('--cycles=1000')] = '--cycles=300000'
        row['sim_argv'][row['sim_argv'].index('--ticks=1043')] = '--ticks=300043'
        replay.update(vehicle_argv=row['vehicle_argv'], sim_argv=row['sim_argv'], ticks=300043, ticks_resolved=300043)
        with self.assertRaises(ValueError):
            self.check(summary, row, replay)

    def test_stripped_or_inconsistent_peer_provenance_fails_closed(self):
        for mutate in ('drop_cpu', 'drop_peer', 'peer_without_cpu', 'replay_cpu', 'replay_peer',
                       'wrong_cpu', 'idle_enabled', 'no_states', 'affinity', 'policy', 'vehicle', 'sibling'):
            summary, row, replay = self.fixture()
            if mutate == 'drop_cpu': row.pop('peer_cpu'); replay.pop('peer_cpu')
            elif mutate == 'drop_peer': row.pop('peer'); replay.pop('peer')
            elif mutate == 'peer_without_cpu': row['peer_cpu'] = None; replay['peer_cpu'] = None
            elif mutate == 'replay_cpu': replay['peer_cpu'] = 2
            elif mutate == 'replay_peer': replay['peer'] = dict(replay['peer'], affinity=[2])
            elif mutate == 'wrong_cpu': row['peer']['cpu'] = 2; replay['peer']['cpu'] = 2
            elif mutate == 'idle_enabled': row['peer']['idle_states'][3]['disable'] = 0; replay['peer']['idle_states'][3]['disable'] = 0
            elif mutate == 'no_states': row['peer']['idle_states'] = []; replay['peer']['idle_states'] = []
            elif mutate == 'affinity': row['peer']['affinity'] = [2, 3]; replay['peer']['affinity'] = [2, 3]
            elif mutate == 'policy': row['peer']['policy'] = 'SCHED_FIFO'; replay['peer']['policy'] = 'SCHED_FIFO'
            elif mutate == 'vehicle': row['peer_cpu'] = 7; row['peer']['cpu'] = 7; row['peer']['affinity'] = [7]; replay['peer_cpu'] = 7; replay['peer'] = row['peer']
            elif mutate == 'sibling': row['peer']['siblings'] = [3, 7]; replay['peer']['siblings'] = [3, 7]
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.check(summary, row, replay)


class Session(unittest.TestCase):
    """The declared peer is a property of the sweep session: one peer_cpu across
    its L8 rows, each bound to a verified record, and the qualified idle-state
    expectation (the pair, plus the peer when declared) applies to every row the
    session collected, harness levels included."""
    def l8(self, peer_cpu=3, **changes):
        _, row, _ = Provenance.fixture(Provenance(), peer_cpu)
        row.update(changes)
        return row

    def harness(self, level='L7'):
        return dict(level=level, label=level + '.r1', repeat=1, complete=True)

    def roster(self, *rows):
        return dict(format='tvc-sweep-1', complete=True, runs=list(rows))

    def test_session_peer_is_the_single_declared_cpu_or_none(self):
        self.assertIsNone(sweep.session_peer_cpu(self.roster(self.harness('L5'), self.harness())))
        self.assertIsNone(sweep.session_peer_cpu(self.roster(self.harness(), self.l8(None))))
        self.assertEqual(sweep.session_peer_cpu(self.roster(
            self.harness(), self.l8(3), self.l8(3, label='L8.r2', repeat=2))), 3)

    def test_missing_or_inconsistent_declaration_fails_closed(self):
        undeclared = self.l8(3, label='L8.r2', repeat=2); del undeclared['peer_cpu']
        unverified = self.l8(3, peer=None)
        other_cpu = self.l8(3); other_cpu['peer']['cpu'] = 2
        idle_on = self.l8(3); idle_on['peer']['idle_states'][2]['disable'] = 0
        cases = dict(mixed=[self.l8(3), self.l8(None, label='L8.r2', repeat=2)],
                     two_cpus=[self.l8(3), self.l8(2, label='L8.r2', repeat=2)],
                     undeclared_key=[self.l8(3), undeclared],
                     unverified=[unverified], other_cpu=[other_cpu], idle_on=[idle_on],
                     invalid_cpu=[self.l8(-1)], bool_cpu=[self.l8(True)],
                     bool_mixed=[self.l8(1), self.l8(True, label='L8.r2', repeat=2)])
        for name, rows in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                sweep.session_peer_cpu(self.roster(*rows))
        for roster in (None, [], dict(format='tvc-sweep-1', complete=True), dict(runs=None)):
            with self.subTest(roster=roster), self.assertRaises(ValueError):
                sweep.session_peer_cpu(roster)

    def write_session(self, p, roster, disabled, level='L7', artifacts=True):
        """A results directory holding the roster, the runner-written result and
        replay of each L8 row (never the L8 summary, which would need recordings)
        and one harness summary at the given idle-disabled count."""
        from tests.unit.test_discipline import good
        if roster is not None:
            (p / 'sweep.json').write_text(json.dumps(roster))
            for row in roster['runs']:
                if isinstance(row, dict) and row.get('level') == 'L8' and artifacts:
                    _, _, replay = Provenance.fixture(Provenance(), row.get('peer_cpu'))
                    (p / (row['label'] + '.result.json')).write_text(json.dumps(row))
                    (p / (row['label'] + '.replay.json')).write_text(json.dumps(replay))
        s = good(); s['label'] = level + '.r1'; s['config'] += ' telemetry record:control'
        for state in s['env']['cpuidle']['states']:
            state['disabled'] = disabled
        (p / (level + '.r1.summary.json')).write_text(json.dumps(s))

    def run_gate(self, d, level='L7'):
        from scripts import bench_gate
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = bench_gate.main(['--results', str(d), '--level', level, '--no-baseline'])
        return rc, out.getvalue()

    def gate(self, roster, disabled, level='L7', artifacts=True):
        with tempfile.TemporaryDirectory() as d:
            self.write_session(Path(d), roster, disabled, level, artifacts)
            return self.run_gate(d, level)

    def test_declaration_must_be_corroborated_by_the_rows_own_artifacts(self):
        declared = self.roster(self.harness(), self.l8(3))
        self.assertEqual(self.gate(declared, 3)[0], 0)
        rc, text = self.gate(declared, 3, artifacts=False)      # roster alone binds nothing
        self.assertEqual(rc, 1); self.assertIn('sweep.json', text)
        with tempfile.TemporaryDirectory() as d:                 # roster edited after the run
            p = Path(d); self.write_session(p, declared, 3)
            tampered = json.loads((p / 'sweep.json').read_text())
            tampered['runs'][1]['peer']['siblings'] = [3]
            (p / 'sweep.json').write_text(json.dumps(tampered))
            rc, text = self.run_gate(d)
            self.assertEqual(rc, 1); self.assertIn('corroborated', text); self.assertIn('sweep.json', text)
        with tempfile.TemporaryDirectory() as d:                 # planned, never run
            p = Path(d); self.write_session(p, declared, 3, artifacts=False)
            (p / 'sweep.json').write_text(json.dumps(self.roster(self.harness(), dict(self.l8(3), complete=False))))
            rc, text = self.run_gate(d)
            self.assertEqual(rc, 1); self.assertIn('sweep.json', text)
        with tempfile.TemporaryDirectory() as d:                 # malformed roster names itself
            p = Path(d); self.write_session(p, None, 2); (p / 'sweep.json').write_text('{broken')
            rc, text = self.run_gate(d)
            self.assertEqual(rc, 1); self.assertIn('sweep.json', text)
        with tempfile.TemporaryDirectory() as d:                 # a non-row entry is a verdict, not a crash
            from scripts import latency
            import contextlib, io
            p = Path(d); self.write_session(p, self.roster(self.harness(), self.l8(3), 42), 3)
            rc, text = self.run_gate(d)
            self.assertEqual(rc, 1); self.assertIn('sweep.json', text)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(latency.results_main(d), 1)
            self.assertFalse(json.loads(out.getvalue())['valid'])

    def test_directories_under_one_results_root_cannot_mix_declarations(self):
        declared = self.roster(self.harness(), self.l8(3))
        undeclared = self.roster(self.harness(), self.l8(None))
        for nested, disabled in ((None, 2), (undeclared, 2), (undeclared, 3)):
            with tempfile.TemporaryDirectory() as d:
                p = Path(d); self.write_session(p, declared, 3)
                (p / 'sub').mkdir(); self.write_session(p / 'sub', nested, disabled)
                rc, text = self.run_gate(d)
                with self.subTest(nested=nested is not None, disabled=disabled):
                    self.assertEqual(rc, 1); self.assertIn('mixed', text)
        with tempfile.TemporaryDirectory() as d:                 # all undeclared stays as before
            p = Path(d); self.write_session(p, None, 2)
            (p / 'sub').mkdir(); self.write_session(p / 'sub', undeclared, 2)
            self.assertEqual(self.run_gate(d)[0], 0)

    def test_harness_rows_inherit_the_session_expectation(self):
        declared = self.roster(self.harness(), self.l8(3), self.l8(3, label='L8.r2', repeat=2))
        undeclared = self.roster(self.harness(), self.l8(None))
        self.assertEqual(self.gate(None, 2)[0], 0)             # no roster: pair only, unchanged
        self.assertEqual(self.gate(undeclared, 2)[0], 0)
        self.assertEqual(self.gate(declared, 3)[0], 0)
        for roster, disabled in ((None, 3), (undeclared, 3), (declared, 2), (declared, 4)):
            rc, text = self.gate(roster, disabled)
            with self.subTest(declared=roster is declared, disabled=disabled):
                self.assertEqual(rc, 1); self.assertIn('cpuidle', text)
        rc, text = self.gate(self.roster(self.harness(), self.l8(3), self.l8(None, label='L8.r2', repeat=2)), 3)
        self.assertEqual(rc, 1); self.assertIn('inconsistent', text)
        rc, text = self.gate(self.roster(self.harness(), self.l8(3, peer=None)), 3)
        self.assertEqual(rc, 1); self.assertIn('peer', text)


if __name__ == '__main__':
    unittest.main()

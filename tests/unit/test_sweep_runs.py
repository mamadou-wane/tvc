import itertools
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import run_scenario, sweep


def args(**values):
    result = dict(cpu=7, only=['L5','L7','L8'], repeat=2, interleave=True,
                  phase_us='400', cycles=1000, warmup=10, rate=500)
    result.update(values)
    return SimpleNamespace(**result)


class RunPlan(unittest.TestCase):
    def test_l7_l8_are_available_without_changing_old_flags(self):
        self.assertEqual([r[0] for r in sweep.LEVELS],['L0','L1','L2','L3','L4','L5','L6','L7','L8'])
        self.assertEqual([r[2] for r in sweep.LEVELS[:7]], [[],['--abs-deadline'],['--mlock'],
            ['--fifo=80'],['--cpu={cpu}'],['--no-naive-log','--alloc-guard=abort'],['--telemetry']])

    def test_interleaved_flags_are_not_accumulated_again(self):
        plans,_=sweep.plan_runs(args())
        self.assertEqual([p['label'] for p in plans],['L5.r1','L7.r1','L8.r1','L5.r2','L7.r2','L8.r2'])
        self.assertEqual(plans[0]['flags'],['--abs-deadline','--mlock','--fifo=80','--cpu=7','--no-naive-log','--alloc-guard=abort'])
        self.assertEqual(plans[0]['flags'],plans[3]['flags'])
        self.assertNotIn('--mode=freerun',plans[1]['flags'])
        self.assertIn('--record=control',plans[1]['flags'])
        self.assertIn('--mode=freerun',plans[2]['flags'])
        self.assertNotIn('--ground', ' '.join(plans[2]['flags']))
        plans,_=sweep.plan_runs(args(interleave=False))
        self.assertEqual([p['label'] for p in plans],['L5.r1','L5.r2','L7.r1','L7.r2','L8.r1','L8.r2'])

    def test_grid_names_and_refusals(self):
        plans,_=sweep.plan_runs(args(only=['L8'],repeat=3,phase_us='200,400,800'))
        self.assertEqual([p['label'] for p in plans],[
            'L8.phase200.r1','L8.phase400.r1','L8.phase800.r1',
            'L8.phase200.r2','L8.phase400.r2','L8.phase800.r2',
            'L8.phase200.r3','L8.phase400.r3','L8.phase800.r3'])
        for values in (dict(phase_us='200,400,800'),dict(only=['L9']),dict(repeat=0),dict(cycles=0),
                       dict(rate=1000),dict(phase_us='0'),dict(phase_us='2000'),
                       dict(phase_us='200,400,400',only=['L8'],repeat=3)):
            with self.subTest(values=values),self.assertRaises(ValueError):sweep.plan_runs(args(**values))
        plans,stopped=sweep.plan_runs(args(cpu=None,only=None))
        self.assertEqual({p['level'] for p in plans},{'L0','L1','L2','L3'})
        self.assertIn('L4',stopped)
        with self.assertRaises(ValueError):
            sweep.plan_levels([('L8','bad',['--mode=lockstep'],None)],7)


class FakeProcess:
    def __init__(self, polls):
        self.polls = list(polls); self.returncode = None; self.stdout = None
    def poll(self):
        self.returncode = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
        return self.returncode


class PeerDeadline(unittest.TestCase):
    """The bounded process deadline belongs to the L8 peer lifecycle only."""
    def run_row(self, level, polls):
        plans,_ = sweep.plan_runs(args(only=[level], repeat=1, interleave=False, cycles=300000, warmup=5000))
        plan = plans[0]; launched = []
        def launch(argv, **kw):
            launched.append(FakeProcess(polls)); return launched[-1]
        # Each clock read advances 1000 s: the first read sets the deadline, every later read is far past it.
        with tempfile.TemporaryDirectory() as d, patch.object(sweep.subprocess, 'Popen', side_effect=launch), \
             patch.object(sweep.time, 'monotonic', side_effect=itertools.count(0, 1000)), \
             patch.object(sweep.time, 'sleep'), patch.object(run_scenario, 'stop_process'), \
             patch.object(run_scenario, 'ready_line', return_value=dict(consts='0xe77201ca', sensor_port='1')):
            sweep.run_row(plan, '/bin/true', Path(d))
        return plan

    def test_harness_levels_have_no_peer_deadline(self):
        for level in ('L0','L1','L2','L3','L4','L5','L6','L7'):
            with self.subTest(level=level):
                plan = self.run_row(level, [None, None, 0])
                self.assertEqual(plan['vehicle_exit'], 0, plan['error'])
                self.assertNotEqual(plan['error'], 'process deadline expired')

    def test_l8_keeps_bounded_peer_deadline(self):
        plan = self.run_row('L8', [None])
        self.assertEqual(plan['error'], 'process deadline expired')
        self.assertFalse(plan['complete'])

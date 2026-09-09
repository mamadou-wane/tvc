import ast
import importlib
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

from sim import actuator, control_ref, episode, link, plant, rng, sensor
from sim.scenario import Scenario, load
from sim.types import TruthState

ROOT = Path(__file__).resolve().parents[2]


def spec(**kw):
    values = dict(id='unit', ticks=3, initial=TruthState(0.0, 0.0), gusts=(),
                  loss_up=0.0, loss_down=0.0, loss_start_tick=0,
                  blackout_up=None, blackout_down=None, commands=(), auto_arm=True)
    values.update(kw)
    return Scenario(**values)


def bits(value):
    return struct.unpack('<Q', struct.pack('<d', value))[0]


class HeadlessTests(unittest.TestCase):
    def setUp(self):
        self.run = importlib.import_module('sim.run_headless').run_headless

    def test_tick_zero_and_terminal_row_are_not_extra_plant_steps(self):
        trace = self.run(spec(), seed=1, delay_ticks=0)
        self.assertEqual([r.tick for r in trace.rows], [0, 1, 2])
        self.assertEqual([r.fresh for r in trace.rows], [True] * 3)
        self.assertEqual([r.staleness for r in trace.rows], [0] * 3)
        self.assertEqual([r.episode.state.mode for r in trace.rows],
                         [episode.Mode.FLYING, episode.Mode.FLYING, episode.Mode.TERMINATED])
        self.assertEqual(trace.sim_reason, episode.SimReason.SIM_HORIZON)
        self.assertEqual(trace.rows[-1].episode.state.terminal,
                         episode.TerminalResult(episode.Reason.NOT_SETTLED, 2))
        for row in trace.rows:
            self.assertEqual(row.truth, TruthState(0.0, 0.0))
            self.assertEqual(row.observation.tick, row.tick)
            self.assertTrue(row.observation.valid)
            self.assertEqual(bits(row.episode.requested_delta), 0)
        self.assertEqual(trace.rows[0].episode.state.pid, control_ref.ControlState(0.0, 0.0, 0.0))

    def test_open_loop_reuses_independent_plant_known_answer(self):
        trace = self.run(spec(ticks=2, initial=TruthState(0.02, 0.0), auto_arm=False),
                         seed=1, delay_ticks=0)
        # Existing plant one-step literal; neither runner nor integrator generates it.
        self.assertEqual(tuple(map(bits, trace.rows[1].truth)),
                         (0x3F947B677F6B1A2A, 0x3F50624DD2F1A9FC))
        self.assertEqual(trace.rows[0].episode.state.mode, episode.Mode.INIT)

    def test_delay_zero_and_one_apply_different_requests(self):
        for delay, applied in ((0, (0.12, 0.0)), (1, (0.0, 0.12))):
            with self.subTest(delay=delay):
                trace = self.run(spec(ticks=2, initial=TruthState(0.15, 0.0)),
                                 seed=1, delay_ticks=delay)
                self.assertEqual([r.episode.requested_delta for r in trace.rows], [0.12, 0.0])
                self.assertEqual(tuple(r.actuator.applied for r in trace.rows), applied)
                self.assertEqual(trace.rows[0].episode.state.pid.i_state, 0.0)

    def test_closed_loop_rows_match_independent_rounded_rational_literals(self):
        # Derived from contract operations with exact fractions and binary64
        # rounding per operation, without importing any TVC implementation.
        expected = (
            (
                (0x3f90000000000000, 0x0000000000000000, 0x3faa56c0d6f544bb, 0x3f2f75104d551d69, 0x0000000000000000, 0x3faa56c0d6f544bb),
                (0x3f8ff8bb41400fd1, 0xbf7c64891dc238bf, 0x3faa12a53fd1828b, 0x3f3f717db569761f, 0xbf62edb0be817b2a, 0x3faa12a53fd1828b),
                (0x3f8fea4679508777, 0xbf8c3c167fd64f46, 0x0000000000000000, 0x3f3f717db569761f, 0xbf62edb0be817b2a, 0x0000000000000000),
            ),
            (
                (0x3f90000000000000, 0x0000000000000000, 0x3faa56c0d6f544bb, 0x3f2f75104d551d69, 0x0000000000000000, 0x0000000000000000),
                (0x3f900068db8bac71, 0x3f4999999999999a, 0x3faa816e99de047b, 0x3f3f7577619c8e52, 0x3f31111111111111, 0x3faa56c0d6f544bb),
                (0x3f8ffa5eb4cd254d, 0xbf793140f1d97ca8, 0x0000000000000000, 0x3f3f7577619c8e52, 0x3f31111111111111, 0x3faa816e99de047b),
            ),
        )
        for delay in (0, 1):
            trace = self.run(spec(initial=TruthState(0.015625, 0.0)), seed=1, delay_ticks=delay)
            words = tuple(tuple(map(bits, (r.truth.theta, r.truth.omega,
                          r.episode.requested_delta, r.episode.state.pid.i_state,
                          r.episode.state.pid.d_prev, r.actuator.applied))) for r in trace.rows)
            self.assertEqual(words, expected[delay])
            self.assertEqual(bits(trace.rows[-1].episode.state.pid.last_delta),
                             expected[delay][1][2])

    def test_modeled_down_loss_holds_actuator_after_a_real_arrival(self):
        trace = self.run(spec(ticks=3, initial=TruthState(0.15, 0.0), blackout_down=(1, 3)),
                         seed=1, delay_ticks=0)
        self.assertEqual([r.down_drop for r in trace.rows], [False, True, True])
        self.assertEqual([r.arriving for r in trace.rows][1:], [None, None])
        self.assertEqual([r.actuator.applied for r in trace.rows], [0.12] * 3)
        self.assertIs(trace.rows[1].actuator, trace.rows[0].actuator)

    def test_sample_loss_coast_neutral_and_sensor_lost(self):
        trace = self.run(spec(ticks=30, blackout_up=(1, 30)), seed=1, delay_ticks=0)
        self.assertEqual(len(trace.rows), 22)
        self.assertEqual([r.staleness for r in trace.rows], list(range(22)))
        self.assertTrue(trace.rows[0].fresh)
        for row in trace.rows[1:]:
            self.assertFalse(row.fresh)
            self.assertFalse(row.observation.valid)
            self.assertEqual((bits(row.observation.theta), bits(row.observation.omega)), (0, 0))
            self.assertEqual(row.held.tick, 0)
            self.assertEqual(row.episode.state.pid, trace.rows[0].episode.state.pid)
        self.assertEqual(trace.rows[-1].episode.state.terminal,
                         episode.TerminalResult(episode.Reason.SENSOR_LOST, 21))
        self.assertEqual(trace.sim_reason, episode.SimReason.SIM_VEHICLE_TERMINAL)

    def test_coast_retains_nonzero_command_then_neutral_requests_zero(self):
        trace = self.run(spec(ticks=12, initial=TruthState(0.02, 0.0),
                              blackout_up=(1, 12)), seed=1, delay_ticks=0)
        first = trace.rows[0].episode.requested_delta
        self.assertGreater(first, 0.0)
        for row in trace.rows[1:9]:
            self.assertEqual(bits(row.episode.requested_delta), bits(first))
        for row in trace.rows[9:]:
            self.assertEqual(bits(row.episode.requested_delta), 0)

    def test_no_first_sample_and_horizon_sensor_lost_pairing(self):
        trace = self.run(spec(ticks=21, loss_up=1.0), seed=1, delay_ticks=1)
        self.assertEqual([r.staleness for r in trace.rows], list(range(1, 22)))
        self.assertTrue(all(r.held is None for r in trace.rows))
        self.assertEqual(trace.sim_reason, episode.SimReason.SIM_HORIZON)
        self.assertEqual(trace.rows[-1].episode.state.terminal.reason, episode.Reason.SENSOR_LOST)

    def test_horizon_settles_only_after_full_window(self):
        for ticks, reason in ((999, episode.Reason.NOT_SETTLED), (1000, episode.Reason.STABILIZED)):
            trace = self.run(spec(ticks=ticks), seed=1, delay_ticks=0)
            self.assertEqual(trace.rows[-1].episode.state.terminal,
                             episode.TerminalResult(reason, ticks - 1))
            self.assertEqual(trace.rows[-1].episode.state.settle_count, ticks)

    def test_gust_interval_uses_environment_torque(self):
        with patch.object(plant, 'step', wraps=plant.step) as steps:
            trace = self.run(spec(ticks=4, gusts=((1, 2, 0.01),), auto_arm=False),
                             seed=1, delay_ticks=0)
        self.assertEqual([c.args[3].tau_d for c in steps.call_args_list], [0.0, 0.09, 0.0])
        self.assertEqual(tuple(map(bits, trace.rows[2].truth)),
                         (0x3EB0C6F7A0B5ED8D, 0x3F40624DD2F1A9FC))

    def test_command_arrival_due_application_and_abort(self):
        trace = self.run(spec(ticks=150, auto_arm=False,
                              commands=((0, 'ARM'), (60, 'LAUNCH'), (70, 'ABORT'))),
                         seed=1, delay_ticks=0)
        events = [(r.tick, [(a.cmd_seq, a.status, a.applied_tick) for a in r.episode.acks])
                  for r in trace.rows if r.episode.acks]
        self.assertEqual(events, [
            (0, [(1, episode.AckStatus.QUEUED, 0)]),
            (50, [(1, episode.AckStatus.APPLIED, 50)]),
            (60, [(2, episode.AckStatus.QUEUED, 0)]),
            (70, [(3, episode.AckStatus.QUEUED, 0), (2, episode.AckStatus.PREEMPTED, 0)]),
            (120, [(3, episode.AckStatus.APPLIED, 120)]),
        ])
        self.assertEqual(trace.rows[70].command, episode.Command(3, 3, 120))
        self.assertEqual(trace.rows[-1].episode.state.terminal,
                         episode.TerminalResult(episode.Reason.GROUND_ABORT, 120))

    def test_command_facts_survive_invalid_sample(self):
        trace = self.run(spec(ticks=5, commands=((1, 'ABORT'),), blackout_up=(1, 2)),
                         seed=1, delay_ticks=0)
        self.assertFalse(trace.rows[1].fresh)
        self.assertEqual(trace.rows[1].episode.acks[0].status, episode.AckStatus.QUEUED)
        self.assertEqual(trace.rows[-1].episode.acks[0].status, episode.AckStatus.REJECTED_STATE)

    def test_loss_streams_match_existing_independent_prefixes_and_repeat(self):
        s = spec(ticks=32, loss_up=0.3, loss_down=0.3)
        a = self.run(s, seed=1, delay_ticks=0)
        self.assertEqual(a, self.run(s, seed=1, delay_ticks=0))
        self.assertEqual(''.join(str(int(r.up_drop)) for r in a.rows), '00101001110010000001010011000001')
        self.assertEqual(''.join(str(int(r.down_drop)) for r in a.rows), '01100001010100010001000100110100')
        self.assertEqual([(r.name, r.draws, r.final_state) for r in a.rng], [
            ('link.loss.up', 32, 0x57F9651C7251DF61),
            ('link.loss.down', 32, 0x85DAC4D14EDE6F07)])
        b = self.run(s, seed=2, delay_ticks=0)
        self.assertNotEqual([r.up_drop for r in a.rows], [r.up_drop for r in b.rows])
        self.assertEqual(''.join(str(int(r.up_drop)) for r in b.rows), '01000011011001001101011100000110')
        self.assertEqual(''.join(str(int(r.down_drop)) for r in b.rows), '10000000110111000100000010001111')
        self.assertEqual([(r.start_state, r.final_state) for r in b.rng], [
            (0x975835DE1C9756CE, 0x5E476D0E05E6D96E),
            (0xBFC846100BFC1E42, 0x86B77D3FF54BA0E2)])

    def test_real_call_counts_and_order_include_terminal_tick(self):
        module = importlib.import_module('sim.run_headless')
        functions = {'episode': episode.step, 'pid': control_ref.step,
                     'plant': plant.step, 'actuator': actuator.step,
                     'rng': rng.SplitMix64.next_double, 'delay': module._Delay.push_pop}
        codes = {fn.__code__: name for name, fn in functions.items()}
        events = []
        def observe(frame, event, arg):
            if event == 'call' and frame.f_code in codes:
                events.append(codes[frame.f_code])
        previous = sys.getprofile()
        try:
            sys.setprofile(observe)
            trace = self.run(spec(ticks=30, blackout_up=(1, 30)), seed=1, delay_ticks=1)
        finally:
            sys.setprofile(previous)
        self.assertEqual({name: events.count(name) for name in functions},
                         dict(episode=22, pid=1, plant=21, actuator=22, rng=44, delay=22))
        self.assertEqual(events[:7], ['rng', 'rng', 'episode', 'pid', 'delay', 'actuator', 'plant'])
        self.assertEqual(events[-5:], ['rng', 'rng', 'episode', 'delay', 'actuator'])
        self.assertEqual([r.draws for r in trace.rng], [22, 22])

    def test_terminal_plant_failure_precedes_horizon_even_when_sample_lost(self):
        # 0.3 + 1000*dt must cross the angle guard after the first real step.
        trace = self.run(spec(ticks=2, initial=TruthState(0.3, 1000.0),
                              auto_arm=False, blackout_up=(1, 2)), seed=1, delay_ticks=0)
        self.assertEqual(len(trace.rows), 2)
        self.assertEqual(trace.sim_reason, episode.SimReason.SIM_LOC_ANGLE)
        self.assertEqual(trace.rows[-1].episode.state.terminal.reason, episode.Reason.DIVERGED)
        self.assertFalse(trace.rows[-1].observation.valid)

    def test_nonfinite_plant_result_wins_over_horizon(self):
        trace = self.run(spec(ticks=2, initial=TruthState(1e308, 0.0), loss_up=1.0),
                         seed=1, delay_ticks=0)
        self.assertEqual(trace.sim_reason, episode.SimReason.SIM_LOC_NONFINITE)
        self.assertEqual(trace.rows[-1].episode.state.terminal.reason, episode.Reason.DIVERGED)
        self.assertFalse(trace.rows[-1].fresh)

    def test_callable_has_no_io_and_new_modules_have_no_transport_imports(self):
        with patch('builtins.open', side_effect=AssertionError('file IO in core')), \
             patch.object(Path, 'open', side_effect=AssertionError('file IO in core')):
            self.assertEqual(len(self.run(spec(), seed=1, delay_ticks=0).rows), 3)
        for name in ('run_headless.py', 'trace.py'):
            tree = ast.parse((ROOT / 'sim' / name).read_text())
            imports = {n.module.split('.')[0] for n in ast.walk(tree)
                       if isinstance(n, ast.ImportFrom) and n.module}
            imports |= {a.name.split('.')[0] for n in ast.walk(tree)
                        if isinstance(n, ast.Import) for a in n.names}
            self.assertFalse(imports & {'socket', 'time', 'datetime', 'subprocess', 'threading', 'multiprocessing', 'ground', 'os', 'io'})

    def test_rejects_invalid_seed_delay_and_nonreference_controller(self):
        for seed in (-1, 2**64, True):
            with self.assertRaises(ValueError): self.run(spec(), seed=seed, delay_ticks=0)
        for delay in (-1, 2, True):
            with self.assertRaises(ValueError): self.run(spec(), seed=1, delay_ticks=delay)
        with self.assertRaises(ValueError):
            self.run(spec(), seed=1, delay_ticks=0, controller=object())


if __name__ == '__main__':
    unittest.main()

import importlib
import math
import unittest

from sim import control_ref, episode
from sim.trace import Row, Trace
from sim.types import ActuatorState, Observation, TruthState


def passing_trace():
    rows = []
    for tick in range(1000):
        obs = Observation(tick, 0.0, 0.0, True)
        state = episode.EpisodeState(episode.Mode.FLYING, control_ref.ControlState(0.0, 0.0, 0.0),
                                     tick + 1, None, None, None, True)
        if tick == 999:
            state = state._replace(mode=episode.Mode.TERMINATED,
                                   terminal=episode.TerminalResult(episode.Reason.STABILIZED, 999))
        rows.append(Row(tick, TruthState(0.0, 0.0), obs, obs, True, 0, None,
                        episode.EpisodeOutput(state, 0.0, ()), 0.0,
                        ActuatorState(0.0), False, False))
    return Trace(1000, 1, 0, tuple(rows), (), episode.SimReason.SIM_HORIZON)


class PredicateTests(unittest.TestCase):
    def setUp(self):
        self.evaluate = importlib.import_module('sim.trace').evaluate

    def test_all_five_clauses_pass_on_independent_zero_equilibrium(self):
        result = self.evaluate(passing_trace())
        self.assertEqual(tuple(result), (True,) * 5)
        self.assertTrue(result.passed)

    def test_each_clause_can_fail_independently(self):
        base = passing_trace()
        for name in ('termination', 'peak', 'settled', 'cadence', 'finiteness'):
            rows = list(base.rows)
            if name == 'termination':
                terminal = episode.TerminalResult(episode.Reason.NOT_SETTLED, 999)
                rows[-1] = rows[-1]._replace(episode=rows[-1].episode._replace(
                    state=rows[-1].episode.state._replace(terminal=terminal)))
            elif name == 'peak':
                # Peak violation before the final 1000-tick window.
                extra = rows[0]._replace(tick=0, truth=TruthState(0.15000000000000002, 0.0))
                rows = [extra] + [r._replace(tick=r.tick + 1) for r in rows]
                rows[-1] = rows[-1]._replace(episode=rows[-1].episode._replace(
                    state=rows[-1].episode.state._replace(
                        terminal=episode.TerminalResult(episode.Reason.STABILIZED, 1000))))
            elif name == 'settled':
                rows[10] = rows[10]._replace(truth=TruthState(0.0, 0.020000000000000004))
            elif name == 'cadence':
                # Duplicate tick outside the final window isolates cadence.
                rows = [rows[0]._replace(tick=1)] + [r._replace(tick=r.tick + 1) for r in rows]
                rows[-1] = rows[-1]._replace(episode=rows[-1].episode._replace(
                    state=rows[-1].episode.state._replace(
                        terminal=episode.TerminalResult(episode.Reason.STABILIZED, 1000))))
            else:
                rows[0] = rows[0]._replace(episode=rows[0].episode._replace(
                    state=rows[0].episode.state._replace(
                        pid=control_ref.ControlState(float('inf'), 0.0, 0.0))))
            result = self.evaluate(base._replace(rows=tuple(rows), ticks_declared=len(rows)))
            with self.subTest(clause=name):
                self.assertEqual(result._asdict(), {n: n != name for n in result._fields})
                self.assertFalse(result.passed)

    def test_empty_short_missing_terminal_and_duplicate_ticks_fail(self):
        base = passing_trace()
        for rows in ((), base.rows[:999], base.rows[:-1] + (base.rows[0],)):
            self.assertFalse(self.evaluate(base._replace(rows=rows)).passed)

    def test_truth_rate_angle_and_controller_finiteness(self):
        base = passing_trace()
        for value in (float('nan'), float('inf'), -float('inf')):
            for field in ('theta', 'omega', 'delta', 'i_state', 'd_prev'):
                row = base.rows[0]
                if field in ('theta', 'omega'):
                    row = row._replace(truth=row.truth._replace(**{field: value}))
                elif field == 'delta':
                    row = row._replace(episode=row.episode._replace(requested_delta=value))
                else:
                    row = row._replace(episode=row.episode._replace(state=row.episode.state._replace(
                        pid=row.episode.state.pid._replace(**{field: value}))))
                with self.subTest(value=value, field=field):
                    self.assertFalse(self.evaluate(base._replace(rows=(row,) + base.rows[1:])).finiteness)

    def test_settling_uses_truth_and_inclusive_thresholds(self):
        base = passing_trace()
        row = base.rows[0]._replace(truth=TruthState(0.02, -0.02))
        self.assertTrue(self.evaluate(base._replace(rows=(row,) + base.rows[1:])).settled)
        row = row._replace(truth=TruthState(math.nextafter(0.02, math.inf), 0.0))
        self.assertFalse(self.evaluate(base._replace(rows=(row,) + base.rows[1:])).settled)


class CsvTests(unittest.TestCase):
    def test_sim_csv_is_independent_literal_with_exact_bits(self):
        base = passing_trace()
        row = base.rows[0]._replace(truth=TruthState(-0.0, 0.25), arriving=None,
                                    actuator=ActuatorState(0.12), fresh=False,
                                    observation=Observation(0, 0.0, 0.0, False))
        expected = ('tick,has_sample,applied,theta_bits,omega_bits,cmd_applied_bits\n'
                    '0,0,0,0x8000000000000000,0x3fd0000000000000,0x3fbeb851eb851eb8\n')
        self.assertEqual(base._replace(rows=(row,)).to_sim_csv(), expected)


if __name__ == '__main__':
    unittest.main()

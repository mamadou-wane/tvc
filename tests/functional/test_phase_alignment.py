"""Free-run phase alignment: the frame a cycle consumes is produced by the immediately
preceding simulator body, and the one-tick control delay lives in the actuator FIFO.
Late-frame and coast behaviour are covered by test_freerun and test_freerun_diagnostics."""
import json
from pathlib import Path
import statistics
import tempfile
import unittest

from ground import wire
from scripts.run_scenario import run_free_case
from sim import actuator
from sim.freerun import PERIOD_NS
from sim.run_sim import word
from sim.types import ActuatorState
from tests.functional import test_freerun as runtime

ROOT=Path(__file__).resolve().parents[2]
BIN=runtime.BIN




class PhaseAlignment(unittest.TestCase):
    def run_case(self, phase_us, label):
        d=tempfile.TemporaryDirectory(); root=Path(d.name)
        result=run_free_case(binary=BIN,scenario_path=ROOT/'sim/scenarios/S1-hold.json',out=root,label=label,
                             seed=1,delay_ticks=1,cycles=1000,warmup=5,phase_us=phase_us,ticks=1038,loss=0)
        self.assertEqual(result['code'],0,result)
        s=json.loads((root/(label+'.summary.json')).read_text())
        report=json.loads((root/(label+'.replay.json')).read_text())
        rec=json.loads((root/(label+'.reconcile.json')).read_text())
        _,controls,_=wire.read_typed_recording(root/(label+'.control.tvcrec'),expected_type=6)
        return d,s,report,rec,controls

    def test_nominal_chronology_obs_j_drives_step_j_plus_1(self):
        keep,s,report,rec,controls=self.run_case(1000,'nominal')
        with keep:
            self.assertEqual(report['delay_ticks'],1)
            # Observation 0 is cycle zero's fresh sample and is consumed exactly once.
            self.assertEqual((controls[0]['sensor_tick'],controls[0]['staleness'],controls[0]['flags']&1),(0,0,1))
            self.assertEqual(sum(1 for r in controls if r['flags']&1 and r['sensor_tick']==0),1)
            for r in controls:
                self.assertEqual(r['staleness'],r['tick']-r['sensor_tick'])
            self.assertGreater(sum(1 for r in controls if r['staleness']==0),len(controls)//2)
            self.assertEqual((s['future_parked_at_warmup'],s['future_parked_at_end']),(0,0))
            rows,steps=report['rows'],report['steps']
            # Step 0 is the only neutral step; body k reads delta_k and step k+1 applies it.
            self.assertEqual((rows[1]['applied'],rows[1]['cmd_applied_bits']),(0,word(0.0)))
            # The startup window the timing model pins exactly; steady state is nominal,
            # so a superseded command is counted rather than treated as an identity failure.
            for k in range(3):
                self.assertEqual(steps[k]['selected_delta'],controls[k]['cmd'],k)
                self.assertEqual(rows[k+1]['applied'],int(k>0),k)
            self.assertGreaterEqual(sum(steps[k]['selected_delta']==controls[k]['cmd'] for k in range(20)),18)
            state=ActuatorState(applied=0.0)
            for k in range(len(steps)-1):
                state=actuator.step(state,steps[k]['selected_delta'])
                if steps[k]['selected_delta']==controls[k]['cmd']:
                    self.assertEqual(rows[k+2]['cmd_applied_bits'],word(state.applied),k)
            # Served latency keeps its endpoint and is now below one period at this phase.
            served=[r['tx_ns']-r['sensor_send_ns'] for r in controls[5:] if r['flags']&3==3 and r['staleness']==0]
            self.assertLess(statistics.median(served),PERIOD_NS)
            self.assertTrue(rec['eligible'] and rec['terminal_agreement'] and rec['terminal']['required_legs_complete'])
            self.assertEqual(report['vehicle_reason_seen'],7)

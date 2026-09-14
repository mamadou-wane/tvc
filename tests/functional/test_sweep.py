"""Short process tests exercise orchestration, never timing qualification."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import sweep, bench_gate
from scripts.run_scenario import run_free_case

ROOT=Path(__file__).resolve().parents[2]
BIN=Path(os.environ['TVC_BIN']).resolve()


def functional_plan():
    return dict(level='L8',label='L8',repeat=1,phase_us=400,
                flags=['--mode=freerun','--auto-arm','--abs-deadline','--telemetry','--record=control','--alloc-guard=abort'],
                cycles=1000,warmup=5,rate=500)


class SweepProcesses(unittest.TestCase):
    def test_reporting_has_existing_discipline_schema_without_changing_functional_result(self):
        with tempfile.TemporaryDirectory() as d:
            result=run_free_case(binary=BIN,scenario_path=ROOT/'sim/scenarios/S1-hold.json',
                out=d,label='run',seed=1,delay_ticks=0,cycles=1000,warmup=5,ticks=1038,loss=0)
            self.assertEqual(result['code'],0,result)
            s=json.loads((Path(d)/'run.summary.json').read_text())
            self.assertTrue({'cpu_end','timer_migration','governor','epp','ac_online','cpuidle'}<=s['env'].keys())
            self.assertNotIn('hostname',s['env'])
            self.assertIn('abs-deadline',s['config']);self.assertIn('telemetry',s['config'])
            self.assertEqual((s['cycles'],s['cycles_requested'],s['total_cycles']),(1000,1000,1005))
            self.assertFalse(s['applied']['ground']);self.assertIsNotNone(bench_gate.discipline_problem(s))

    def test_actual_peer_port_final_flush_and_reconciliation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);plan=functional_plan()
            cpu=min(os.sched_getaffinity(0));plan['flags'].append('--cpu='+str(cpu))
            self.assertEqual(sweep.run_row(plan,BIN,p),0,plan)
            self.assertEqual((plan['vehicle_exit'],plan['sim_exit']),(0,0))
            self.assertIn('--ticks=1038',plan['sim_argv'])
            self.assertIn('--loss=0.0',plan['sim_argv'])
            self.assertIn('--bind-port=0',plan['sim_argv'])
            self.assertIn('--sensor-port=0',plan['vehicle_argv'])
            destination=next(a for a in plan['sim_argv'] if a.startswith('--vehicle='))
            self.assertNotEqual(destination,'--vehicle=127.0.0.1:0')
            s=sweep.audit_freerun(p/'L8')
            self.assertIn('cpu:'+str(cpu),s['config'])
            self.assertEqual(s['env']['cpu_end'],cpu)
            self.assertTrue(s['applied']['cpu'])
            self.assertEqual(s['telemetry']['records'],1005)
            self.assertEqual(s['events']['episode_transitions'],1005)
            self.assertEqual(s['events']['record_attempts'],1005)
            self.assertEqual(s['events']['histogram_records'],1000)
            self.assertEqual(s['ground']['attempted'],0)
            rec=json.loads((p/'L8.reconcile.json').read_text())
            self.assertTrue(rec['terminal_agreement']);self.assertTrue(rec['terminal']['required_legs_complete'])
            replay=json.loads((p/'L8.replay.json').read_text())
            self.assertEqual((replay['ticks_declared'],replay['ticks_resolved']),(10000,1038))
            self.assertEqual(replay['sim_argv'],plan['sim_argv'])
            (p/'L8.reconcile.json').write_text('{}')
            with self.assertRaises(ValueError):sweep.audit_freerun(p/'L8')

    def test_peer_death_and_ready_failure_do_not_leave_children(self):
        for failure in ('peer','ready'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as d:
                plan=functional_plan();children=[];real=subprocess.Popen
                def launch(argv,**kw):
                    if failure=='peer' and '-m' in argv:
                        argv=[argv[0],'-c','raise SystemExit(3)']
                    elif failure=='ready' and '--mode=freerun' in argv:
                        argv=['/bin/false']
                    child=real(argv,**kw);children.append(child);return child
                with patch.object(sweep.subprocess,'Popen',side_effect=launch):
                    self.assertNotEqual(sweep.run_row(plan,BIN,Path(d)),0)
                self.assertTrue(all(c.poll() is not None for c in children))
                self.assertFalse(plan['complete'])
                self.assertIsNotNone(plan['error'])

    def test_complete_roster_binds_metadata_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);plan=functional_plan()
            self.assertEqual(sweep.run_row(plan,BIN,p),0,plan)
            roster=dict(format='tvc-sweep-1',complete=True,runs=[plan])
            (p/'sweep.json').write_text(json.dumps(roster))
            self.assertEqual(sweep.roster_row(p/'L8'),plan)
            for change in ('incomplete','argv','missing','duplicate'):
                bad=json.loads(json.dumps(roster))
                if change=='incomplete':bad['complete']=False
                elif change=='argv':bad['runs'][0]['sim_argv'].append('--loss=0.3')
                elif change=='missing':bad['runs'][0]['label']='L8.r2'
                else:bad['runs'].append(bad['runs'][0])
                (p/'sweep.json').write_text(json.dumps(bad))
                with self.assertRaises(ValueError):sweep.roster_row(p/'L8')

    def test_cli_roster_refusal_and_old_harness_path(self):
        with tempfile.TemporaryDirectory() as d:
            command=['python3','-B','scripts/sweep.py','--bin='+str(BIN),'--out='+d,
                     '--only','L0','--cycles=100','--warmup=0','--allow-restricted-affinity']
            result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            r=json.loads((Path(d)/'sweep.json').read_text())
            self.assertTrue(r['complete']);self.assertEqual(len(r['runs']),1)
            self.assertEqual(r['runs'][0]['flags'],[])
            before=(Path(d)/'L0.summary.json').read_bytes()
            result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((Path(d)/'L0.summary.json').read_bytes(),before)

    def test_interruption_and_result_write_failure_remain_failures(self):
        for failure in ('interrupt','write'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as d:
                plan=functional_plan();children=[];real=subprocess.Popen;write=Path.write_text
                def launch(argv,**kw):
                    child=real(argv,**kw);children.append(child);return child
                def output(path,*a,**kw):
                    if str(path).endswith('.result.json'):raise OSError('injected report failure')
                    return write(path,*a,**kw)
                real_sleep=sweep.time.sleep
                interrupted=False
                def interrupt_once(delay):
                    nonlocal interrupted
                    if not interrupted:
                        interrupted=True
                        raise KeyboardInterrupt('test interrupt')
                    return real_sleep(delay)
                fault=(patch.object(sweep.time,'sleep',side_effect=interrupt_once)
                       if failure=='interrupt' else patch.object(Path,'write_text',output))
                with patch.object(sweep.subprocess,'Popen',side_effect=launch),fault:
                    self.assertNotEqual(sweep.run_row(plan,BIN,Path(d)),0)
                self.assertFalse(plan['complete']);self.assertTrue(plan['error'])
                self.assertTrue(all(c.poll() is not None for c in children))

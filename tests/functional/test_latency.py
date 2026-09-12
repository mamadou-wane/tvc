import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from ground import wire
from scripts.run_scenario import ready_line, stop_process
from tests.functional import test_freerun as runtime
BIN = runtime.BIN
sensor_frame = runtime.sensor_frame


class Latency(unittest.TestCase):
    vehicle = runtime.FreeRun.vehicle

    def test_actual_windows_and_local_send_membership(self):
        for warmup in (0, 1, 2, 10):
            for fail in (False, True):
                with self.subTest(warmup=warmup, fail=fail), tempfile.TemporaryDirectory() as directory:
                    out=Path(directory)
                    env=dict(os.environ)
                    if fail: env['TVC_TEST_FAIL_ACTUATOR_TICK']='0'
                    process=self.vehicle(out,'--warmup='+str(warmup),'--phase-us=1000',
                        binary=BIN.with_name('freerun_faults'),env=env)
                    try:
                        ready=ready_line(process,mode='freerun')
                        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as peer:
                            peer.connect(('127.0.0.1',int(ready['sensor_port'])))
                            for packet in (sensor_frame(0),sensor_frame(4),sensor_frame(1,2,1)):
                                peer.send(packet)
                            self.assertEqual(process.wait(timeout=5),0,process.stderr.read())
                        s=json.loads((out/'run.summary.json').read_text())
                        _,rows,_=wire.read_typed_recording(out/'run.control.tvcrec',expected_type=6)
                        self.assertEqual([r['tick'] for r in rows],[0,1])
                        self.assertEqual(s['total_cycles'],2)
                        self.assertTrue(s['clock_domain'].startswith('linux-monotonic:'))
                        self.assertEqual(s['termination_source'],'simulator')
                        self.assertLessEqual(s['termination_ns'],rows[-1]['tx_ns'])
                        self.assertEqual(s['last_received_tick'],4)
                        self.assertEqual(s['cycles'],max(0,2-warmup))
                        self.assertEqual(s['jitter_us']['count'],max(0,2-warmup))
                        self.assertEqual(s['exec_us']['count'],max(0,2-warmup))
                        self.assertEqual(s['future_parked_at_end'],1)
                        self.assertEqual(s['future_parked_at_warmup'],0 if warmup==0 else 1 if warmup==1 else None)
                        expected=1 if warmup==0 and not fail else 0
                        self.assertEqual(s['latency_us']['count'],expected)
                        self.assertEqual(s['latency_us']['sum_ns'],rows[0]['tx_ns']-rows[0]['sensor_send_ns'] if expected else 0)
                        self.assertEqual(s['discard_age_us']['count'],0)
                        self.assertEqual(s['link']['actuator_tx_fail'],int(fail))
                        self.assertEqual(s['link_recorded']['actuator_tx_fail'],int(fail and warmup==0))
                        for name in ('latency','discard_age','jitter','exec'):
                            self.assertTrue((out/('run.'+name+'.csv')).exists())
                    finally:
                        stop_process(process);process.stderr.close()

    def test_runner_finalizes_functional_measurement_evidence(self):
        from scripts.run_scenario import run_free_case
        from scripts.latency import validate
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'scenario.json'
            path.write_text(json.dumps(dict(ticks=8,theta0=0,omega0=0,gusts=[],loss_up=0,loss_down=0,
                loss_start_tick=0,blackout_up=None,blackout_down=None,commands=[],auto_arm=True)))
            r=run_free_case(binary=BIN,scenario_path=path,out=root/'out',label='run',seed=1,delay_ticks=1)
            self.assertEqual(r['code'],0,r)
            self.assertTrue(r['measurement_valid'])
            self.assertFalse(r['evidence_eligible'])
            report=json.loads((root/'out/run.replay.json').read_text())
            s=json.loads((root/'out/run.summary.json').read_text())
            self.assertEqual(report['clock_domain'],s['clock_domain'])
            self.assertEqual(report['termination_source'],'local')
            self.assertEqual(report['latency_roundtrip_us']['count'],len(report['latency_roundtrip_ns']))
            reconciliation=json.loads((root/'out/run.reconcile.json').read_text())
            self.assertEqual(reconciliation['errors'],[])
            self.assertTrue(reconciliation['terminal']['required_legs_complete'])
            _,rows,_=wire.read_typed_recording(root/'out/run.control.tvcrec',expected_type=6)
            self.assertEqual(validate(s,rows)['errors'],[])
            prefix=root/'out/run'
            def cli():
                return subprocess.run([sys.executable,'-B','scripts/latency.py',str(prefix)],
                    cwd=runtime.ROOT,capture_output=True,text=True)
            self.assertEqual(cli().returncode,0)
            recorded=(root/'out/run.control.tvcrec').read_bytes()
            (root/'out/run.control.tvcrec').write_bytes(recorded[:-1])
            self.assertEqual(cli().returncode,1)
            (root/'out/run.control.tvcrec').write_bytes(recorded)
            s['telemetry']['dropped']=1
            (root/'out/run.summary.json').write_text(json.dumps(s))
            self.assertEqual(cli().returncode,1)
            s['telemetry']['dropped']=0
            (root/'out/run.summary.json').write_text(json.dumps(s))
            (root/'out/run.reconcile.json').write_text('{"eligible":true}')
            self.assertEqual(cli().returncode,1)


    def test_integrity_exit_and_later_nonrequired_terminal_traffic(self):
        from scripts.run_scenario import run_free_case
        for kind in ('physical_terminal_loss','later_uplink','uplink_send_failure'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);path=root/'scenario.json';later=kind=='later_uplink'
                path.write_text(json.dumps(dict(ticks=80 if later else 8 if kind=='physical_terminal_loss' else 2,
                    theta0=0,omega0=0,gusts=[],loss_up=0,loss_down=1 if later else 0,
                    loss_start_tick=0,blackout_up=[1,80] if later else None,blackout_down=None,
                    commands=[],auto_arm=True)))
                env=dict(os.environ)
                if kind=='physical_terminal_loss':env['TVC_TEST_DROP_TERMINAL_ALL']='1'
                result=run_free_case(binary=BIN.with_name('freerun_faults'),scenario_path=path,out=root/'out',
                    label='run',seed=1,delay_ticks=0,vehicle_env=env,
                    terminal_copies=1 if kind=='uplink_send_failure' else 12,
                    sim_args=['--test-fail-sensor=1'] if kind=='uplink_send_failure' else [])
                r=json.loads((root/'out/run.reconcile.json').read_text())
                self.assertEqual(result['code'],8 if kind=='physical_terminal_loss' else 3,(result,r))
                if later:
                    self.assertEqual(r['terminal']['path'],'vehicle_first')
                    self.assertGreater(r['terminal']['up']['attempts'],0)
                    self.assertFalse(r['terminal']['up']['required'])
                    self.assertEqual(r['terminal']['causes'],['impairment_model'])
                elif kind=='uplink_send_failure':
                    self.assertEqual(r['terminal']['causes'],['send_failure'])
                else:
                    self.assertEqual(r['terminal']['down']['residual'],'unexplained')

    def test_timing_csv_close_failure_is_a_recording_failure(self):
        with tempfile.TemporaryDirectory() as directory,socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as peer:
            out=Path(directory);env=dict(os.environ,TVC_TEST_FAIL_TIMING_CLOSE='1')
            process=self.vehicle(out,binary=BIN.with_name('freerun_faults'),env=env)
            try:
                ready=ready_line(process,mode='freerun');peer.connect(('127.0.0.1',int(ready['sensor_port'])))
                peer.send(sensor_frame(0));peer.send(sensor_frame(1,2,1))
                self.assertEqual(process.wait(timeout=5),4,process.stderr.read())
            finally:stop_process(process);process.stderr.close()

    def test_fresh_vehicle_first_terminal_send_membership(self):
        for fail in (False,True):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as directory,socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as peer:
                out=Path(directory);env=dict(os.environ,TVC_TEST_PROOF=str(out/'proof.json'))
                if fail:env['TVC_TEST_FAIL_ACTUATOR_TICK']='0'
                process=self.vehicle(out,binary=BIN.with_name('freerun_faults'),env=env)
                try:
                    ready=ready_line(process,mode='freerun');peer.connect(('127.0.0.1',int(ready['sensor_port'])))
                    payload=wire.encode_payload(4,dict(tick=0,t_send_ns=runtime.time.monotonic_ns(),
                        theta=.31,omega=0,flags=1,cmd_seq=0,sim_reason=0))
                    peer.send(wire.encode_frame(4,0,payload))
                    self.assertEqual(process.wait(timeout=5),0,process.stderr.read())
                    s=json.loads((out/'run.summary.json').read_text());proof=json.loads((out/'proof.json').read_text())
                    self.assertEqual((s['total_cycles'],proof['episodes'],proof['pids'],proof['histograms']),(1,1,0,1))
                    self.assertEqual(s['latency_us']['count'],int(not fail))
                    self.assertEqual(s['terminal']['first_tx_ok'],not fail)
                    self.assertEqual(s['terminal']['down_tx_fail'],int(fail))
                    self.assertEqual(s['link']['actuator_tx_fail'],0)
                finally:stop_process(process);process.stderr.close()

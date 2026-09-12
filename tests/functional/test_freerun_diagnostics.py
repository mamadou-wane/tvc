"""Controlled scheduling diagnostics; no calibration or qualified timing assertions."""
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import tempfile
import time
import unittest

from ground import wire
from scripts.latency import validate
from scripts.run_scenario import ready_line, stop_process
from tests.functional import test_freerun as runtime


class SchedulingDiagnostics(unittest.TestCase):
    def test_phase_stall_and_bounded_bursts(self):
        for phase in (300,400,500):
            for traffic in ('duplicates','within','excess'):
                with self.subTest(phase=phase,traffic=traffic),tempfile.TemporaryDirectory() as directory:
                    out=Path(directory); ready_r,ready_w=os.pipe();release_r,release_w=os.pipe()
                    env=dict(os.environ,TVC_TEST_PROOF=str(out/'proof.json'),
                             TVC_TEST_READY_FD=str(ready_w),TVC_TEST_RELEASE_FD=str(release_r))
                    process=subprocess.Popen([str(runtime.BIN.with_name('freerun_faults')),
                        '--mode=freerun','--telemetry','--record=control','--auto-arm','--sensor-port=0',
                        '--cycles=1000','--warmup=3','--phase-us='+str(phase),'--alloc-guard=abort',
                        '--label=run','--out='+str(out)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                        env=env,pass_fds=(ready_w,release_r))
                    os.close(ready_w);os.close(release_r)
                    with os.fdopen(ready_r,'rb',buffering=0) as gate,os.fdopen(release_w,'wb',buffering=0) as release:
                        try:
                            info=ready_line(process,mode='freerun')
                            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as peer:
                                peer.connect(('127.0.0.1',int(info['sensor_port'])))
                                first=runtime.sensor_frame(0);peer.send(first)
                                self.assertTrue(select.select([gate],[],[],5)[0])
                                self.assertEqual(gate.read(1),b'g')
                                packets=[first]*9 if traffic=='duplicates' else [runtime.sensor_frame(k) for k in range(1,6 if traffic=='within' else 10)]
                                for packet in packets:peer.send(packet)
                                time.sleep(.03)
                                release.write(b'r')
                                self.assertEqual(process.wait(timeout=5),6 if traffic=='excess' else 0,process.stderr.read())
                            s=json.loads((out/'run.summary.json').read_text());proof=json.loads((out/'proof.json').read_text())
                            _,rows,_=wire.read_typed_recording(out/'run.control.tvcrec',expected_type=6)
                            cycles=22 if traffic=='duplicates' else 27
                            self.assertEqual([r['tick'] for r in rows],list(range(cycles)))
                            self.assertEqual(s['origin_ns']-s['first_frame_arrival_ns'],phase*1000)
                            self.assertEqual((proof['episodes'],proof['batches'],proof['histograms']),
                                             (cycles,cycles,cycles-3))
                            self.assertEqual(proof['pids'],1 if traffic=='duplicates' else 6)
                            self.assertEqual(s['link']['received'],1+len(packets))
                            self.assertEqual(s['link']['discarded_duplicate'],9 if traffic=='duplicates' else 0)
                            self.assertEqual(s['link']['discarded_skew_excess'],4 if traffic=='excess' else 0)
                            self.assertEqual(s['future_parked_at_warmup'],0 if traffic=='duplicates' else 3)
                            self.assertEqual(s['future_parked_at_end'],0)
                            self.assertEqual(s['link']['future_expired'],0)
                            self.assertGreater(s['missed_deadlines'],0)
                            self.assertTrue(any(r['flags']&8 for r in rows))
                            self.assertTrue(any(r['flags']&16 for r in rows))
                            if traffic!='within':
                                self.assertEqual(rows[1]['rx_count'],8)
                                self.assertTrue(rows[1]['flags']&32)
                                self.assertEqual(rows[2]['rx_count'],1)
                            self.assertEqual(proof['terminal_sends'],12)
                            self.assertFalse(proof['terminal_bytes_changed'])
                            self.assertEqual(validate(s,rows)['errors'],[])
                            self.assertFalse(s['timing_qualified'])
                        finally:
                            try:release.write(b'r')
                            except OSError:pass
                            stop_process(process);process.stderr.close()

    def test_applied_fields_report_enabled_mitigations(self):
        for pin in (False,True):
            with self.subTest(pin=pin),tempfile.TemporaryDirectory() as directory,socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as peer:
                out=Path(directory);extra=['--cpu='+str(min(os.sched_getaffinity(0)))] if pin else []
                process=runtime.FreeRun.vehicle(self,out,*extra)
                try:
                    info=ready_line(process,mode='freerun');peer.connect(('127.0.0.1',int(info['sensor_port'])))
                    peer.send(runtime.sensor_frame(0));peer.send(runtime.sensor_frame(1,2,1))
                    self.assertEqual(process.wait(timeout=5),0,process.stderr.read())
                    s=json.loads((out/'run.summary.json').read_text())
                    self.assertEqual(s['applied'],dict(mlock=False,cpu=pin,fifo=False,telemetry=True,link=True))
                finally:stop_process(process);process.stderr.close()

    def test_terminal_resend_stall_has_no_control_work(self):
        with tempfile.TemporaryDirectory() as directory,socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as peer:
            out=Path(directory);ready_r,ready_w=os.pipe();release_r,release_w=os.pipe()
            env=dict(os.environ,TVC_TEST_PROOF=str(out/'proof.json'),TVC_TEST_READY_FD=str(ready_w),
                     TVC_TEST_RELEASE_FD=str(release_r),TVC_TEST_GATE_CYCLE='22')
            process=subprocess.Popen([str(runtime.BIN.with_name('freerun_faults')),'--mode=freerun','--telemetry',
                '--record=control','--auto-arm','--sensor-port=0','--cycles=1000','--warmup=0','--alloc-guard=abort',
                '--label=run','--out='+str(out)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,
                pass_fds=(ready_w,release_r))
            os.close(ready_w);os.close(release_r)
            with os.fdopen(ready_r,'rb',buffering=0) as gate,os.fdopen(release_w,'wb',buffering=0) as release:
                try:
                    info=ready_line(process,mode='freerun');peer.connect(('127.0.0.1',int(info['sensor_port'])))
                    peer.send(runtime.sensor_frame(0))
                    self.assertTrue(select.select([gate],[],[],5)[0]);self.assertEqual(gate.read(1),b'g')
                    peer.settimeout(2)
                    replies=[]
                    while len(replies)<22:replies.append(peer.recv(512))
                    last=wire.decode_payload(5,wire.decode_datagram(replies[-1],{5})[2])
                    self.assertEqual(last['status']&255,3)
                    time.sleep(.03);release.write(b'r')
                    self.assertEqual(process.wait(timeout=5),0,process.stderr.read())
                    proof=json.loads((out/'proof.json').read_text())
                    self.assertEqual((proof['episodes'],proof['pids'],proof['batches'],proof['histograms']),(22,1,22,22))
                    self.assertEqual(proof['terminal_sends'],12);self.assertFalse(proof['terminal_bytes_changed'])
                finally:
                    try:release.write(b'r')
                    except OSError:pass
                    stop_process(process);process.stderr.close()

    def test_process_pair_stall_is_audited_as_skew_integrity_failure(self):
        from scripts.run_scenario import run_free_case
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);scenario=root/'scenario.json'
            scenario.write_text(json.dumps(dict(ticks=1000,theta0=0,omega0=0,gusts=[],loss_up=0,loss_down=0,
                loss_start_tick=0,blackout_up=None,blackout_down=None,commands=[],auto_arm=True)))
            result=run_free_case(binary=runtime.BIN.with_name('freerun_faults'),scenario_path=scenario,
                out=root/'out',label='run',seed=1,delay_ticks=1,vehicle_env=dict(os.environ,TVC_TEST_STALL='1'))
            summary=json.loads((root/'out/run.summary.json').read_text())
            self.assertEqual(result['code'],8,result)
            self.assertGreater(summary['link']['discarded_skew_excess'],0)
            self.assertEqual(summary['link']['future_expired'],0)
            self.assertTrue(result['measurement_valid'])
            _,rows,_=wire.read_typed_recording(root/'out/run.control.tvcrec',expected_type=6)
            self.assertEqual([r['tick'] for r in rows],list(range(len(rows))))
            self.assertEqual(validate(summary,rows)['errors'],[])

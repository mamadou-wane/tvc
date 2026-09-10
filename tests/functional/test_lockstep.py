import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from ground import wire
from sim.scenario import load
from sim.run_headless import run_headless

ROOT = Path(__file__).resolve().parents[2]
BIN = os.environ['TVC_BIN']


def bits(x): return struct.pack('<d', x)


class Lockstep(unittest.TestCase):
    def run_case(self, scenario='S2-gust', delay=0, extra=(), expect=0):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        out = Path(temp.name)
        result = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/run_scenario.py'),
                                 '--mode=lockstep', '--binary='+BIN, '--scenario='+scenario,
                                 '--seed=1', '--delay-ticks='+str(delay), '--out='+str(out),
                                 '--label=case', *extra], capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return out, result

    def test_process_path_matches_accepted_headless_both_delays(self):
        for delay in (0, 1):
            out, _ = self.run_case(delay=delay, extra=('--loss=0.30',))
            spec = load(ROOT/'sim/scenarios/S2-gust.json')._replace(loss_up=.3,loss_down=.3)
            reference = run_headless(spec,seed=1,delay_ticks=delay)
            self.assertEqual((out/'case.sim.csv').read_text(),reference.to_sim_csv())
            header,records,counters = wire.read_typed_recording(out/'case.control.tvcrec',expected_type=6)
            self.assertEqual(len(records),10000)
            self.assertEqual(header['start_epoch_ns'],0)
            self.assertEqual(header['start_monotonic_ns'],0)
            for record,row in zip(records,reference.rows):
                self.assertEqual(record['tick'],row.tick)
                self.assertEqual(record['sensor_tick'],row.held.tick if row.held else 0xffffffffffffffff)
                self.assertEqual(record['staleness'],row.staleness)
                self.assertEqual(record['state'],row.episode.state.mode)
                self.assertEqual(record['reason'],row.episode.state.terminal.reason if row.episode.state.terminal else 0)
                for name,value in [('cmd',row.episode.requested_delta),('i_state',row.episode.state.pid.i_state),('d_prev',row.episode.state.pid.d_prev)]:
                    self.assertEqual(bits(record[name]),bits(value))
                self.assertEqual(record['rx_count'],1)
                self.assertEqual([record[k] for k in ('deadline_ns','woke_ns','done_ns','sensor_send_ns','rx_ns','tx_ns')],[0]*6)
            summary=json.loads((out/'case.summary.json').read_text())
            self.assertEqual(summary['mode'],'lockstep'); self.assertFalse(summary['timing_valid'])
            self.assertEqual(summary['cycles'],0)
            for key in ('jitter_us','exec_us','latency_us','discard_age_us'): self.assertIsNone(summary[key])
            replay=json.loads((out/'case.replay.json').read_text())
            self.assertEqual(set(replay['digests']),{'inputs_tvcrec','control_tvcrec','sim_csv','vehicle_csv'})
            self.assertTrue(json.loads((out/'case.reconcile.json').read_text())['eligible'])
            self.assertEqual(replay['rng']['streams']['link.loss.up']['draws'],10000)

    def test_midrun_retries_change_counters_not_logical_artifacts(self):
        plain,_=self.run_case('S7-abort')
        for hook in ('--sim-arg=--test-drop-actuator=500', '--sim-arg=--test-fail-sensor=500'):
            out,_=self.run_case('S7-abort',extra=(hook,))
            for suffix in ('inputs.tvcrec','control.tvcrec','sim.csv','vehicle.csv'):
                self.assertEqual((out/('case.'+suffix)).read_bytes(),(plain/('case.'+suffix)).read_bytes())
            rec=json.loads((out/'case.reconcile.json').read_text())
            self.assertGreater(rec['uplink']['send_attempts'],rec['uplink']['generated'])
            if 'drop-actuator' in hook:
                self.assertGreater(rec['uplink']['discarded_duplicate'],0)
            else:
                self.assertEqual(rec['uplink']['tx_fail'],1)

    def test_episode_endings_and_complete_recordings(self):
        for name,ticks,reason in [('S4-open',300,7),('S6-blackout',1021,4),('S7-abort',1051,3)]:
            out,_=self.run_case(name)
            summary=json.loads((out/'case.summary.json').read_text())
            self.assertEqual(summary['episode']['vehicle_reason'],reason)
            self.assertEqual(summary['total_cycles'],ticks)
            self.assertEqual(summary['telemetry']['records'],ticks)
            self.assertEqual(summary['telemetry']['dropped'],0)
            self.assertEqual(summary['events']['episode_transitions'],ticks)
            self.assertEqual(summary['events']['record_attempts'],ticks)
            self.assertEqual(summary['events']['records_pushed'],ticks)
            self.assertEqual(summary['events']['record_pending'],0)

    def test_owner_reason_names_and_midrun_peer_cleanup(self):
        out,_=self.run_case('S4-open')
        summary=json.loads((out/'case.summary.json').read_text())
        self.assertEqual(summary['episode']['vehicle_reason_name'],'NOT_SETTLED')
        self.assertEqual(summary['episode']['sim_reason_seen_name'],'SIM_HORIZON')
        out,_=self.run_case('S4-open',extra=('--sim-arg=--test-kill-at=5',),expect=3)
        result=json.loads((out/'case.result.json').read_text())
        self.assertEqual(result['sim_exit'],-9)
        self.assertEqual(result['vehicle_exit'],3)
        summary=json.loads((out/'case.summary.json').read_text())
        self.assertEqual(summary['total_cycles'],5)
        self.assertEqual(summary['episode']['vehicle_reason'],6)

    def test_terminal_response_loss_is_failure_without_replacement_attempt(self):
        out,_=self.run_case('S4-open',extra=('--sim-arg=--test-drop-actuator=300',),expect=3)
        self.assertFalse(json.loads((out/'case.result.json').read_text())['eligible'])
        self.assertFalse((out/'case.replay.json').exists())

    def test_horizon_sensor_lost_requires_retained_admission_evidence(self):
        from scripts.reconcile import reconcile
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'outage.json'
        data=json.loads((ROOT/'sim/scenarios/S1-hold.json').read_text())
        data.update(ticks=21,theta0=0.0,blackout_up=[0,21])
        path.write_text(json.dumps(data))
        out,_=self.run_case(str(path))
        summary=json.loads((out/'case.summary.json').read_text())
        report=json.loads((out/'case.sim-report.json').read_text())
        _,sensors,_=wire.read_typed_recording(out/'case.inputs.tvcrec',expected_type=4)
        _,controls,_=wire.read_typed_recording(out/'case.control.tvcrec',expected_type=6)
        self.assertEqual(summary['episode']['vehicle_reason'],4)
        self.assertTrue(reconcile(summary,report,'lockstep',sensors=sensors,controls=controls)['eligible'])
        controls[-1]['staleness']=20
        self.assertFalse(reconcile(summary,report,'lockstep',sensors=sensors,controls=controls)['eligible'])

    def test_reconciliation_rejects_unobserved_copies_and_incomplete_evidence(self):
        import copy
        from scripts.reconcile import reconcile
        out,_=self.run_case('S4-open')
        summary=json.loads((out/'case.summary.json').read_text())
        report=json.loads((out/'case.sim-report.json').read_text())
        _,sensors,_=wire.read_typed_recording(out/'case.inputs.tvcrec',expected_type=4)
        _,controls,_=wire.read_typed_recording(out/'case.control.tvcrec',expected_type=6)
        for fault in ('unobserved','tx_flag','pending','missing','drops'):
            a=copy.deepcopy(summary);b=copy.deepcopy(report);c=copy.deepcopy(controls)
            if fault=='unobserved':
                for key in ('send_attempts','retry_attempts','transmitted','additional_copies'):b['transmission'][key]+=1
            elif fault=='tx_flag':c[0]['flags'] &= ~2
            elif fault=='pending':
                b['actuator_receipt']['disposition_pending']=1
                b['actuator_receipt']['forwarded_to_delay']-=1
            elif fault=='missing':del a['link']
            else:a['telemetry']['dropped']=1
            with self.subTest(fault=fault):
                self.assertFalse(reconcile(a,b,'lockstep',sensors=sensors,controls=c)['eligible'])

    def test_relative_output_from_another_working_directory(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/run_scenario.py'),
            '--binary='+str(Path(BIN).resolve()),'--scenario=S4-open','--out=results','--label=relative'],
            cwd=temp.name,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue((Path(temp.name)/'results/relative.replay.json').is_file())

    def test_development_metadata_and_runner_usage_errors(self):
        out,_=self.run_case('S4-open')
        replay=json.loads((out/'case.replay.json').read_text())
        self.assertEqual(replay['rate_hz'],500.0)
        self.assertEqual(replay['period_ns'],2000000)
        self.assertEqual(replay['ticks_resolved'],300)
        self.assertEqual(replay['transmission']['first_tick'],0)
        self.assertEqual(replay['transmission']['last_tick'],299)
        self.assertIsNone(replay['latency_roundtrip_us'])
        self.assertIsNone(replay['toolchain']['image'])
        self.assertEqual(replay['parameters']['dt_bits'],'0x3f60624dd2f1a9fc')
        result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/run_scenario.py'),
            '--mode=invalid'],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,1)

    def test_mode_refusals(self):
        for flags in (['--mode=lockstep'], ['--mode=lockstep','--telemetry','--cycles=300000'],
                      ['--mode=lockstep','--telemetry','--warmup=1'], ['--mode=freerun']):
            result=subprocess.run([BIN,*flags],capture_output=True,timeout=10)
            self.assertEqual(result.returncode,1)

class WireTransactions(unittest.TestCase):
    def launch(self):
        import socket
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        out=Path(temp.name)
        proc=subprocess.Popen([BIN,'--mode=lockstep','--telemetry','--auto-arm','--sensor-port=0',
                               '--alloc-guard=abort','--out='+str(out),'--label=raw'],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        def cleanup():
            if proc.poll() is None: proc.terminate()
            try:proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.communicate(timeout=5)
        self.addCleanup(cleanup)
        fields=dict(x.split('=',1) for x in proc.stdout.readline().split()[1:])
        self.assertEqual(fields['mode'],'lockstep');self.assertEqual(fields['consts'],'0xe77201ca')
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('127.0.0.1',0));sock.settimeout(3)
        self.addCleanup(sock.close);sock.connect(('127.0.0.1',int(fields['sensor_port'])))
        return proc,sock,out

    def frame(self,tick,theta=0.015625,flags=1,reason=0):
        return wire.encode_frame(4,tick,wire.encode_payload(4,dict(tick=tick,t_send_ns=0,
            theta=theta,omega=0.0,flags=flags,cmd_seq=0,sim_reason=reason)))

    def test_real_socket_duplicate_old_conflict_and_nonfinite(self):
        proc,sock,out=self.launch()
        p=self.frame(0);sock.send(p);answer=sock.recv(512)
        sock.send(p);self.assertEqual(sock.recv(512),answer)
        p=self.frame(1,theta=0,flags=0);sock.send(p);sock.recv(512)
        sock.send(self.frame(0))
        sock.send(self.frame(1,theta=0,flags=0,reason=99))
        sock.send(self.frame(2,theta=float('nan')));sock.recv(512)
        sock.send(self.frame(3,theta=0,flags=2,reason=1));sock.recv(512)
        proc.communicate(timeout=5);self.assertEqual(proc.returncode,6)
        summary=json.loads((out/'raw.summary.json').read_text())
        self.assertEqual(summary['link']['logical_received'],4)
        self.assertEqual(summary['link']['received_raw'],7)
        self.assertEqual(summary['link']['discarded_duplicate'],1)
        self.assertEqual(summary['link']['discarded_old'],1)
        self.assertEqual(summary['link']['discarded_tick_conflict'],1)
        _,records,_=wire.read_typed_recording(out/'raw.control.tvcrec',expected_type=6)
        self.assertEqual(len(records),4)
        self.assertEqual(records[2]['staleness'],2)
        self.assertTrue(records[2]['flags']&128)
        self.assertEqual(records[2]['discarded_other'],1)

    def test_first_and_skipped_ticks_fail_without_extra_logical_cycle(self):
        for first in (True,False):
            proc,sock,out=self.launch()
            if not first:sock.send(self.frame(0));sock.recv(512)
            sock.send(self.frame(2));proc.communicate(timeout=5)
            self.assertEqual(proc.returncode,5)
            summary=json.loads((out/'raw.summary.json').read_text())
            self.assertEqual(summary['total_cycles'],0 if first else 1)
            self.assertEqual(summary['episode']['vehicle_reason'],5 if first else 8)

    def test_signal_interrupts_blocking_receive_and_drains(self):
        proc,sock,out=self.launch()
        sock.send(self.frame(0));sock.recv(512)
        proc.terminate();proc.communicate(timeout=5)
        self.assertEqual(proc.returncode,3)
        summary=json.loads((out/'raw.summary.json').read_text())
        self.assertEqual(summary['episode']['vehicle_reason'],6)
        self.assertEqual(summary['telemetry']['records'],1)


class FaultPaths(unittest.TestCase):
    run_case=Lockstep.run_case
    def fault_case(self,name,env):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);out=Path(temp.name)
        binary=str(Path(BIN).with_name('lockstep_faults'))
        result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/run_scenario.py'),
            '--binary='+binary,'--scenario='+name,'--out='+str(out),'--label=case'],
            env={**os.environ,**env},capture_output=True,text=True,timeout=40)
        return out,result

    def test_original_send_failure_stays_truthful_after_progress_recovers(self):
        out,result=self.fault_case('S4-open',{'TVC_TEST_FAIL_ACTUATOR_TICK':'5'})
        self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
        summary=json.loads((out/'case.summary.json').read_text())
        self.assertEqual(summary['actuator']['original_tx_fail'],1)
        self.assertEqual(summary['total_cycles'],300)
        _,records,_=wire.read_typed_recording(out/'case.control.tvcrec',expected_type=6)
        self.assertFalse(records[5]['flags']&2)
        self.assertTrue(records[6]['flags']&2)
        self.assertFalse(json.loads((out/'case.result.json').read_text())['eligible'])
        self.assertFalse((out/'case.replay.json').exists())

    def test_malformed_owner_report_retains_failure_result(self):
        out,result=self.fault_case('S4-open',{'TVC_TEST_BAD_SUMMARY':'1'})
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((out/'case.result.json').exists(),result.stdout+result.stderr)
        self.assertFalse(json.loads((out/'case.result.json').read_text())['eligible'])
        self.assertFalse(json.loads((out/'case.reconcile.json').read_text())['eligible'])
        self.assertFalse((out/'case.replay.json').exists())

    def test_terminal_local_send_failure_is_not_midrun_recovery(self):
        out,result=self.fault_case('S4-open',{'TVC_TEST_FAIL_ACTUATOR_TICK':'299'})
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(json.loads((out/'case.summary.json').read_text())['actuator']['original_tx_fail'],1)
        self.assertFalse(json.loads((out/'case.result.json').read_text())['eligible'])

    def test_stalled_drain_preserves_short_run_and_rejects_overflow(self):
        plain,_=self.run_case('S7-abort')
        out,result=self.fault_case('S7-abort',{'TVC_TEST_STALL_DRAIN':'1'})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        for suffix in ('inputs.tvcrec','control.tvcrec','sim.csv','vehicle.csv'):
            self.assertEqual((plain/('case.'+suffix)).read_bytes(),(out/('case.'+suffix)).read_bytes())
        out,result=self.fault_case('S2-gust',{'TVC_TEST_STALL_DRAIN':'1'})
        self.assertNotEqual(result.returncode,0)
        self.assertGreater(json.loads((out/'case.summary.json').read_text())['telemetry']['dropped'],0)
        self.assertFalse((out/'case.replay.json').exists())

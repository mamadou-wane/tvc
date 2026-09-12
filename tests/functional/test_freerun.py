import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest

from ground import wire
from scripts.run_scenario import ready_line, stop_process

ROOT = Path(__file__).resolve().parents[2]
BIN = Path(os.environ.get('TVC_BIN', ROOT / 'build/tvc_harness'))


def sensor_frame(tick, flags=1, reason=0):
    payload = wire.encode_payload(4, dict(tick=tick, t_send_ns=time.monotonic_ns(),
        theta=0.0, omega=0.0, flags=flags, cmd_seq=0, sim_reason=reason))
    return wire.encode_frame(4, tick, payload)


class FreeRun(unittest.TestCase):
    def vehicle(self, out, *extra, binary=BIN, env=None):
        return subprocess.Popen([str(binary), '--mode=freerun', '--telemetry',
            '--record=control', '--auto-arm', '--sensor-port=0', '--cycles=1000',
            '--warmup=0', '--alloc-guard=abort', '--out='+str(out), '--label=run',
            *extra], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

    def test_carry_future_and_sensor_loss_on_actual_process_path(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
            out = Path(directory)
            process = self.vehicle(out)
            try:
                ready = ready_line(process, mode='freerun')
                peer.connect(('127.0.0.1', int(ready['sensor_port'])))
                for tick in range(5): peer.send(sensor_frame(tick))
                self.assertEqual(process.wait(timeout=5), 0, process.stderr.read())
                header, rows, counters = wire.read_typed_recording(out/'run.control.tvcrec', expected_type=6)
                summary = json.loads((out/'run.summary.json').read_text())
                self.assertGreater(header['start_monotonic_ns'], 0)
                self.assertEqual([r['tick'] for r in rows], list(range(26)))
                self.assertEqual(rows[0]['sensor_tick'], 0)
                self.assertEqual(rows[-1]['staleness'], 21)
                self.assertEqual(rows[-1]['reason'], 4)
                self.assertTrue(any(r['flags'] & 8 for r in rows))
                self.assertTrue(any(r['flags'] & 16 for r in rows))
                for n, row in enumerate(rows):
                    self.assertEqual(row['deadline_ns'], summary['origin_ns'] + n*2000000)
                    self.assertLessEqual(row['rx_count'], 9 if n == 0 else 8)
                    self.assertGreaterEqual(row['done_ns'], row['tx_ns'])
                self.assertEqual(summary['origin_ns'] - summary['first_frame_arrival_ns'], 400000)
                self.assertEqual(summary['events']['episode_transitions'], len(rows))
                self.assertEqual(summary['events']['receive_batches'], len(rows))
                self.assertEqual(summary['events']['records_pushed'], len(rows))
                self.assertEqual(summary['terminal']['down_attempts'], 12)
                self.assertEqual(summary['actuator']['generated'], len(rows)-1)
                self.assertEqual(summary['link']['received'], 5)
                self.assertEqual(counters['frames_ok'], len(rows))
            finally:
                stop_process(process)
                process.stderr.close()

    def test_future_terminal_is_due_before_policy_observes_it(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
            out = Path(directory)
            process = self.vehicle(out)
            try:
                ready = ready_line(process, mode='freerun')
                peer.connect(('127.0.0.1', int(ready['sensor_port'])))
                peer.send(sensor_frame(0))
                peer.send(sensor_frame(3, flags=2, reason=1))
                self.assertEqual(process.wait(timeout=5), 0, process.stderr.read())
                _, rows, _ = wire.read_typed_recording(out/'run.control.tvcrec', expected_type=6)
                self.assertEqual([r['tick'] for r in rows], [0, 1, 2, 3])
                self.assertEqual(rows[-1]['reason'], 7)
                self.assertEqual(rows[-1]['sensor_tick'], 0)
                self.assertFalse(rows[-1]['flags'] & 1)
            finally:
                stop_process(process)
                process.stderr.close()

    def test_simulator_process_recurrence_and_horizon_both_delays(self):
        from scripts.run_scenario import run_free_case
        from sim import actuator, control_ref, environment, plant, scenario, sensor
        from sim.types import TruthState
        from sim.run_sim import word
        for delay in (0, 1):
            with self.subTest(delay=delay), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                spec_path = root/'short.json'
                spec_path.write_text(json.dumps(dict(ticks=8, theta0=0.01, omega0=0,
                    gusts=[], loss_up=0, loss_down=0, loss_start_tick=0,
                    blackout_up=None, blackout_down=None, commands=[], auto_arm=True)))
                result = run_free_case(binary=BIN, scenario_path=spec_path, out=root/'out',
                    label='run', seed=1, delay_ticks=delay, cycles=1000, warmup=0)
                self.assertEqual(result['code'], 0, result)
                report = json.loads((root/'out/run.sim-report.json').read_text())
                self.assertEqual(report['sim_reason'], 1)
                self.assertEqual(report['events']['plant_steps'], 7)
                self.assertEqual(report['events']['actuator_updates'], 7)
                self.assertEqual(report['events']['fifo_advances'], 7)
                self.assertEqual(report['rng']['up_draws'], 7 + report['terminal']['up_attempts'])
                spec = scenario.load(spec_path)
                truth = spec.initial; act = actuator.initial(); fifo = [None]*delay
                for k, row in enumerate(report['steps']):
                    self.assertEqual(row['deadline_ns'], report['origin_ns'] + k*2000000)
                    fifo.append(row['selected_delta']); arriving = fifo.pop(0)
                    act = actuator.step(act, arriving)
                    truth = plant.step(truth, act, environment.fixed(),
                        scenario.disturbance_at(spec, k, environment.fixed()), control_ref.DT)
                    self.assertEqual(row['theta_bits'], word(truth.theta))
                    self.assertEqual(row['omega_bits'], word(truth.omega))
                    self.assertEqual(row['cmd_applied_bits'], word(act.applied))
                self.assertFalse(result['evidence_eligible'])

    def test_real_call_counts_catchup_and_vehicle_send_failures(self):
        for fault in ('none','warmup','TVC_TEST_STALL','TVC_TEST_FAIL_ACTUATOR_TICK','TVC_TEST_FAIL_TERMINAL_ALL','TVC_TEST_FAIL_SUMMARY_CLOSE'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory, socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as peer:
                out=Path(directory); env=dict(os.environ,TVC_TEST_PROOF=str(out/'proof.json'))
                if fault not in ('none','warmup'): env[fault]='1'
                extra=['--warmup=1000'] if fault=='warmup' else []
                process=self.vehicle(out, *extra, binary=BIN.with_name('freerun_faults'),env=env)
                try:
                    ready=ready_line(process,mode='freerun');peer.connect(('127.0.0.1',int(ready['sensor_port'])))
                    for tick in range(5): peer.send(sensor_frame(tick))
                    expected = 5 if fault=='TVC_TEST_FAIL_TERMINAL_ALL' else 4 if fault=='TVC_TEST_FAIL_SUMMARY_CLOSE' else 0
                    self.assertEqual(process.wait(timeout=5),expected,process.stderr.read())
                    proof=json.loads((out/'proof.json').read_text())
                    summary=json.loads((out/'run.summary.json').read_text())
                    _,rows,_=wire.read_typed_recording(out/'run.control.tvcrec',expected_type=6)
                    self.assertEqual(proof['episodes'],len(rows))
                    self.assertEqual(proof['batches'],len(rows))
                    self.assertEqual(proof['histograms'],0 if fault=='warmup' else len(rows))
                    self.assertEqual(proof['pids'],5)
                    self.assertEqual(proof['terminal_sends'],12)
                    self.assertEqual(proof['sends'],len(rows)-1+12)
                    self.assertFalse(proof['terminal_bytes_changed'])
                    self.assertEqual([r['tick'] for r in rows],list(range(26)))
                    if fault=='TVC_TEST_STALL': self.assertGreater(summary['missed_deadlines'],0)
                    if fault=='TVC_TEST_FAIL_ACTUATOR_TICK':
                        self.assertEqual(summary['actuator']['tx_fail'],1)
                        self.assertFalse(rows[1]['flags']&2)
                    if fault=='TVC_TEST_FAIL_TERMINAL_ALL':
                        self.assertEqual(summary['terminal']['down_tx_fail'],12)
                        self.assertEqual(summary['actuator']['tx_fail'],0)
                        self.assertFalse(rows[-1]['flags']&2)
                finally:
                    stop_process(process);process.stderr.close()

    def test_pair_loss_terminal_exhaustion_and_local_sensor_failure(self):
        from scripts.run_scenario import run_free_case
        for case in ('up_loss','down_loss','prologue_failure','ordinary_failure','terminal_failure','vehicle_first','divergence','peer_killed','physical_terminal_loss'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); path=root/'case.json'
                path.write_text(json.dumps(dict(ticks=1200 if case in ('vehicle_first','up_loss') else 8,
                    theta0=0.31 if case=='divergence' else 0,omega0=0,gusts=[],loss_up=int(case=='up_loss'),loss_down=int(case=='down_loss'),
                    loss_start_tick=0,blackout_up=None,blackout_down=None,commands=[],auto_arm=True)))
                sim_args={'prologue_failure':['--test-fail-sensor=0'],
                    'ordinary_failure':['--test-fail-sensor=2'], 'terminal_failure':['--test-fail-sensor=7'],
                    'peer_killed':['--test-kill-at=2']}.get(case,[])
                binary=BIN.with_name('freerun_faults') if case=='physical_terminal_loss' else BIN
                env=dict(os.environ,TVC_TEST_DROP_TERMINAL_ALL='1') if case=='physical_terminal_loss' else None
                result=run_free_case(binary=binary,scenario_path=path,out=root/'out',label='run',seed=1,
                    delay_ticks=0,cycles=1000,warmup=0,sim_args=sim_args,vehicle_env=env)
                if case in ('down_loss','prologue_failure','peer_killed','physical_terminal_loss'):
                    self.assertNotEqual(result['code'],0)
                else: self.assertEqual(result['code'],0,result)
                if case=='peer_killed': continue
                report=json.loads((root/'out/run.sim-report.json').read_text())
                if case=='up_loss':
                    self.assertEqual(report['transmission']['transmitted'],1)
                    self.assertGreater(report['transmission']['intentionally_lost'],0)
                    self.assertEqual(report['vehicle_reason_seen'],4)
                if case=='down_loss':
                    self.assertEqual(report['terminal_handshake'],'unanswered')
                    self.assertEqual(report['terminal']['up_attempts'],12)
                    self.assertEqual(report['terminal']['down_survived'],0)
                    self.assertEqual(report['terminal']['down_received_raw'],report['terminal']['down_intentionally_lost'])
                if case=='prologue_failure':
                    self.assertEqual(report['transmission']['sensor_tx_fail'],1)
                    self.assertEqual(report['events']['plant_steps'],0)
                    self.assertEqual(report['rng']['up_draws'],1)
                if case=='terminal_failure':
                    self.assertEqual(report['terminal']['up_tx_fail'],1)
                    self.assertEqual(report['events']['plant_steps'],7)
                if case=='ordinary_failure':
                    self.assertEqual(report['transmission']['sensor_tx_fail'],1)
                    self.assertEqual(report['transmission']['intentionally_lost'],0)
                    _,frames,counters=wire.read_typed_recording(root/'out/run.inputs.tvcrec',expected_type=4)
                    self.assertEqual([x['tick'] for x in frames],[0,1,3,4,5,6,7])
                    self.assertEqual(counters['lost'],1)
                if case=='physical_terminal_loss':
                    self.assertEqual(report['terminal']['down_received_raw'],0)
                    self.assertEqual(report['terminal']['down_intentionally_lost'],0)
                    self.assertIsNone(report['vehicle_reason_seen'])
                if case=='vehicle_first':
                    self.assertEqual(report['sim_reason'],4)
                    self.assertEqual(report['vehicle_reason_seen'],1)
                    self.assertEqual(report['terminal']['up_attempts'],0)
                if case=='divergence':
                    self.assertEqual(report['vehicle_reason_seen'],2)
                    self.assertIn(report['sim_reason'],(2,4))
                    self.assertLessEqual(report['events']['plant_steps'],1)

    def test_startup_timeout_and_unsupported_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);process=self.vehicle(out)
            try:
                ready_line(process,mode='freerun')
                self.assertEqual(process.wait(timeout=8),5)
                summary=json.loads((out/'run.summary.json').read_text())
                self.assertEqual(summary['episode']['vehicle_reason'],5)
                self.assertEqual(summary['total_cycles'],0)
                self.assertEqual(summary['terminal']['down_attempts'],0)
            finally:
                stop_process(process);process.stderr.close()
            for flag in ('--ground=127.0.0.1:1234','--command-port=1234'):
                run=subprocess.run([str(BIN),'--mode=freerun','--telemetry',flag],capture_output=True)
                self.assertEqual(run.returncode,1)

    def test_missing_report_and_startup_codes_fail_closed(self):
        from scripts.run_scenario import run_free_case
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'case.json'
            path.write_text(json.dumps(dict(ticks=8,theta0=0,omega0=0,gusts=[],loss_up=0,loss_down=0,
                loss_start_tick=0,blackout_up=None,blackout_down=None,commands=[],auto_arm=True)))
            common=dict(binary=BIN.with_name('freerun_faults'),scenario_path=path,label='run',seed=1,
                        delay_ticks=0,cycles=1000,warmup=0)
            result=run_free_case(**common,out=root/'missing',vehicle_env=dict(os.environ,TVC_TEST_REMOVE_SUMMARY='1'))
            self.assertEqual(result['code'],4,result)
            self.assertFalse(result['functional_success'])
            with patch('scripts.run_scenario.ready_line',side_effect=TimeoutError('ready-line timeout')):
                result=run_free_case(**common,out=root/'timeout')
            self.assertEqual(result['code'],6,result)
            with patch('scripts.run_scenario.ready_line',return_value={'consts':'0x00000000'}):
                result=run_free_case(**common,out=root/'constants')
            self.assertEqual(result['code'],7,result)
            original_wait=subprocess.Popen.wait
            injected=False
            def wait(process,*args,**kwargs):
                nonlocal injected
                if '-m' in process.args and not injected:
                    injected=True
                    raise subprocess.TimeoutExpired(process.args,1)
                return original_wait(process,*args,**kwargs)
            with patch.object(subprocess.Popen,'wait',wait):
                result=run_free_case(**common,out=root/'child-timeout')
            self.assertEqual(result['code'],3,result)

    def test_one_frame_rejected_before_launch_or_artifacts(self):
        from scripts.run_scenario import run_free_case, run_case
        from sim.scenario import load
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'one.json'
            data=dict(ticks=1,theta0=0,omega0=0,gusts=[],loss_up=0,loss_down=0,
                loss_start_tick=0,blackout_up=None,blackout_down=None,commands=[],auto_arm=True)
            path.write_text(json.dumps(data))
            self.assertEqual(load(path).ticks,1)
            common=dict(binary=BIN,scenario_path=path,label='run',seed=1,delay_ticks=0)
            for options in ({},{'ticks':1},{'ticks':0},{'sim_args':['--ticks=1']}):
                with self.subTest(options=options), patch('scripts.run_scenario.subprocess.Popen') as launch:
                    with self.assertRaisesRegex(ValueError,'ticks|sim-arg'):
                        run_free_case(**common,out=root/'rejected',**options)
                    launch.assert_not_called()
                    self.assertFalse((root/'rejected').exists())
            # The schema and the existing lockstep transaction still admit a one-tick episode.
            result=run_case(**common,out=root/'lockstep')
            self.assertEqual(result['code'],0,result)
            _,rows,_=wire.read_typed_recording(root/'lockstep/run.control.tvcrec',expected_type=6)
            self.assertEqual(len(rows),1)
            for entry,args,code in ((['scripts/run_scenario.py'],['--binary='+str(BIN)],1),
                                   (['-m','sim.run_sim'],['--vehicle=127.0.0.1:9','--label=run'],2)):
                command=['python3','-B',*entry,'--mode=freerun','--scenario='+str(path),
                         '--out='+str(root/'cli'),*args]
                result=subprocess.run(command,cwd=ROOT,capture_output=True)
                self.assertEqual(result.returncode,code,result.stderr)
                self.assertIn(b'ticks',result.stderr)
                self.assertFalse((root/'cli').exists())
            # An explicit two-frame resolution is valid even when the source scenario has one frame.
            result=run_free_case(**common,out=root/'two',ticks=2)
            self.assertEqual(result['code'],0,result)
            report=json.loads((root/'two/run.sim-report.json').read_text())
            self.assertEqual(report['events']['plant_steps'],1)


if __name__ == '__main__': unittest.main()

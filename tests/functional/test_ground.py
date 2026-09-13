"""Vehicle distribution only; the Python receiver application is a later slice."""
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest

from ground import wire
from scripts.run_scenario import ready_line, stop_process
from tests.functional.test_freerun import BIN, sensor_frame


class GroundDistribution(unittest.TestCase):
    def run_vehicle(self, directory, *args, env=None, binary=None):
        return subprocess.Popen([str(binary or BIN), '--mode=freerun', '--telemetry',
            '--auto-arm', '--sensor-port=0', '--cycles=1000', '--warmup=0',
            '--alloc-guard=abort', '--out='+str(directory), '--label=run', *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

    def exercise(self, *, enabled=True, fault=None, warmup=False, absent=False, hostname=False):
        with tempfile.TemporaryDirectory() as d, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as ground, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sim:
            root = Path(d)
            ground.bind(('127.0.0.1', 0))
            endpoint = '127.0.0.1:'+str(ground.getsockname()[1])
            env = dict(os.environ, TVC_TEST_PROOF=str(root/'proof.json'))
            if fault: env['TVC_TEST_GROUND_SEND'] = fault
            args = ['--ground='+endpoint] if enabled else []
            if hostname: args = ['--ground=unused.invalid:1234', '--ground=localhost:'+str(ground.getsockname()[1])]
            if warmup: args.append('--warmup=1000')
            process = self.run_vehicle(root, *args, env=env, binary=BIN.with_name('freerun_faults'))
            try:
                ready = ready_line(process, mode='freerun')
                self.assertEqual(ready['command_port'], '0')
                if absent: ground.close()
                sim.connect(('127.0.0.1', int(ready['sensor_port'])))
                for tick in range(5): sim.send(sensor_frame(tick))
                self.assertEqual(process.wait(timeout=8), 0, process.stderr.read())
                summary = json.loads((root/'run.summary.json').read_text())
                proof = json.loads((root/'proof.json').read_text())
                raw = (root/'run.control.tvcrec').read_bytes()[32:]
                frames = [raw[i:i+142] for i in range(0, len(raw), 142)]
                _, rows, _ = wire.read_typed_recording(root/'run.control.tvcrec', expected_type=6)
                self.assertEqual([r['tick'] for r in rows], list(range(26)))
                self.assertEqual(proof['episodes'], 26)
                self.assertEqual(proof['pids'], 5)
                self.assertEqual(proof['batches'], 26)
                self.assertEqual(proof['histograms'], 0 if warmup else 26)
                self.assertEqual(proof['sends'], 37)
                self.assertEqual(proof['terminal_sends'], 12)
                self.assertFalse(proof['terminal_bytes_changed'])
                self.assertEqual(summary['events']['record_attempts'], 26)
                self.assertEqual(summary['telemetry'], {'records':26, 'dropped':0})
                self.assertFalse(summary['timing_qualified'])
                stats = summary['ground']
                self.assertEqual(summary['applied']['ground'], enabled)
                self.assertEqual(stats['requested'], enabled)
                self.assertEqual(stats['endpoint'], endpoint if enabled else None)
                self.assertEqual(stats['setup_errno'], 0)
                self.assertEqual(stats['resolver_error'], 0)
                self.assertEqual(stats['attempted'], 26 if enabled else 0)
                self.assertEqual(stats['sent']+stats['send_errors'], stats['attempted'])
                self.assertEqual(proof['ground_sends'], stats['attempted'])
                self.assertEqual(proof['ground_closes'], int(enabled))
                self.assertEqual(proof['socket_calls'], 2 if enabled else 1)
                self.assertEqual(proof['resolver_calls'], int(enabled))
                if not absent:
                    ground.setblocking(False)
                    received = []
                    while True:
                        try: received.append(ground.recv(4096))
                        except BlockingIOError: break
                    skipped = [] if not fault else list(range(26)) if fault == 'all' else [25] if fault == 'terminal' else [1]
                    self.assertEqual(received, [f for i,f in enumerate(frames) if enabled and i not in skipped])
                    self.assertEqual(stats['send_errors'], len(skipped))
                    self.assertEqual(stats['short_sends'], int(fault == 'short'))
                    error = {'eintr':errno.EINTR, 'refused':errno.ECONNREFUSED, 'short':errno.EIO}.get(fault, errno.EAGAIN if fault else 0)
                    self.assertEqual(stats['last_errno'], error)
            finally:
                stop_process(process)
                process.stderr.close()

    def test_disabled_path_keeps_control_counts_and_opens_no_sink(self):
        self.exercise(enabled=False)

    def test_raw_frames_and_final_record_are_forwarded_once(self):
        self.exercise()

    def test_warmup_records_are_distributed_without_timing_samples(self):
        self.exercise(warmup=True)

    def test_send_failures_are_nonfatal_and_counted_without_retry(self):
        for fault in ('eagain', 'eintr', 'refused', 'short', 'terminal', 'all'):
            with self.subTest(fault=fault): self.exercise(fault=fault)

    def test_only_last_valid_endpoint_is_resolved(self):
        self.exercise(hostname=True)

    def test_listener_removal_is_nonfatal(self):
        self.exercise(absent=True)

    def test_configuration_refusals_happen_before_outputs(self):
        values = ('', ':123', 'localhost', 'localhost:', 'localhost:0', 'localhost:65536',
                  'localhost:-1', 'localhost:+1', 'localhost:1x', 'localhost:1:2', '[::1]:123')
        with tempfile.TemporaryDirectory() as d:
            for endpoint in values:
                with self.subTest(endpoint=endpoint):
                    p = self.run_vehicle(d, '--ground='+endpoint)
                    stdout, stderr = p.communicate(timeout=5)
                    self.assertEqual(p.returncode, 1, stderr)
                    self.assertNotIn(b'ready ', stdout)
            for mode in ('harness', 'lockstep'):
                p = subprocess.run([str(BIN), '--mode='+mode, '--telemetry',
                    '--ground=127.0.0.1:1234', '--out='+d], capture_output=True, timeout=5)
                self.assertEqual(p.returncode, 1)
            p = self.run_vehicle(d, '--ground=:1', '--ground=127.0.0.1:1234')
            p.communicate(timeout=5)
            self.assertEqual(p.returncode, 1)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_startup_failure_has_no_ready_or_control_work(self):
        for fault, error, resolver in [('resolve',0,-2), ('socket',errno.EMFILE,0), ('connect',errno.ECONNREFUSED,0)]:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as d:
                root=Path(d)
                env=dict(os.environ,TVC_TEST_PROOF=str(root/'proof.json'),TVC_TEST_GROUND_SETUP=fault)
                p=self.run_vehicle(root,'--ground=localhost:1234',env=env,binary=BIN.with_name('freerun_faults'))
                stdout,stderr=p.communicate(timeout=8)
                self.assertEqual(p.returncode,2,stderr)
                self.assertNotIn(b'ready ',stdout)
                s=json.loads((root/'run.summary.json').read_text())
                proof=json.loads((root/'proof.json').read_text())
                self.assertFalse(s['applied']['ground'])
                self.assertEqual(s['ground']['setup_errno'],error)
                self.assertEqual(s['ground']['resolver_error'],resolver)
                self.assertEqual(s['ground']['attempted'],0)
                self.assertEqual(proof['episodes'],0)
                self.assertEqual(proof['ground_closes'],int(fault=='connect'))

    def test_output_failure_keeps_precedence_over_ground_startup_failure(self):
        with tempfile.TemporaryDirectory() as d:
            env=dict(os.environ, TVC_TEST_GROUND_SETUP='connect', TVC_TEST_FAIL_SUMMARY_CLOSE='1')
            p=self.run_vehicle(d,'--ground=localhost:1234',env=env,binary=BIN.with_name('freerun_faults'))
            stdout,stderr=p.communicate(timeout=8)
            self.assertEqual(p.returncode,4,stderr)
            self.assertNotIn(b'ready ',stdout)

    def test_ready_precedes_requested_mitigations(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            env=dict(os.environ,TVC_TEST_PROOF=str(root/'proof.json'),TVC_TEST_READY_ORDER='1')
            p=self.run_vehicle(root,'--mlock',env=env,binary=BIN.with_name('freerun_faults'))
            stdout,stderr=p.communicate(timeout=8)
            self.assertEqual(p.returncode,2,stderr)
            self.assertTrue(stdout.startswith(b'ready mode=freerun '))
            proof=json.loads((root/'proof.json').read_text())
            self.assertEqual(proof['ready_calls'],1)
            self.assertEqual(proof['mitigation_calls'],1)
            self.assertEqual(proof['episodes'],0)


if __name__ == '__main__': unittest.main()

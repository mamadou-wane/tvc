"""Headless ground application and actual vehicle-to-receiver evidence."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import unittest

from ground import wire
from scripts.run_scenario import ready_line, stop_process
from tests.functional import test_ground as producer
from tests.unit.test_ground_link import frame

ROOT=Path(__file__).resolve().parents[2]


class GroundReceiver(unittest.TestCase):
    def receive(self,root,label='rx',port=0,drop=False):
        entry=['-m','ground.link']
        if drop:
            entry=['-c', '''import socket
from ground import wire, link
class LossSocket(socket.socket):
    def recvfrom(self, size):
        while True:
            data, source = super().recvfrom(size)
            if wire.decode_datagram(data, {6})[1] not in (1,25):
                return data, source
link.socket.socket = LossSocket
raise SystemExit(link.main())
''']
        p=subprocess.Popen([sys.executable,'-B',*entry,'receive',
            '--out='+str(root),'--label='+label,'--telemetry-port='+str(port)],cwd=ROOT,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.addCleanup(self.cleanup,p)
        return p

    @staticmethod
    def cleanup(p):
        stop_process(p)
        for stream in (p.stdin,p.stdout,p.stderr):
            if stream and not stream.closed: stream.close()

    def receiver_ready(self,p):
        with selectors.DefaultSelector() as wait:
            wait.register(p.stdout,selectors.EVENT_READ)
            self.assertTrue(wait.select(10),'receiver ready timeout')
            line=p.stdout.readline().decode().strip()
        self.assertTrue(line.startswith('ready ground '),line)
        fields=dict(item.split('=',1) for item in line.split()[2:])
        self.assertEqual(int(fields['pid']),p.pid)
        return int(fields['telemetry_port'])

    def finish(self,p):
        p.stdin.close()
        self.assertEqual(p.wait(timeout=5),0,p.stderr.read())

    def test_normal_sequence_is_readable_and_verbatim_after_eof(self):
        with tempfile.TemporaryDirectory() as d,socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as peer:
            root=Path(d);p=self.receive(root);peer.connect(('127.0.0.1',self.receiver_ready(p)))
            frames=[frame(10,2**32-1),frame(11,0),frame(13,2)]
            for data in frames: peer.send(data)
            self.finish(p)
            raw=(root/'rx.ground.tvcrec').read_bytes()
            self.assertEqual(raw[32:],b''.join(frames))
            header,rows,counts=wire.read_typed_recording(root/'rx.ground.tvcrec',expected_type=6)
            self.assertGreater(header['start_monotonic_ns'],0)
            self.assertGreater(header['start_epoch_ns'],0)
            self.assertEqual([r['tick'] for r in rows],[10,11,13])
            self.assertEqual(counts['lost'],1)
            report=json.loads((root/'rx.ground.json').read_text())
            self.assertEqual(report['frame_count'],3)
            self.assertEqual(report['recording_sha256'],hashlib.sha256(raw).hexdigest())

    def test_malformed_input_exits_six_and_preserves_good_records(self):
        with tempfile.TemporaryDirectory() as d,socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as peer:
            root=Path(d);p=self.receive(root);peer.connect(('127.0.0.1',self.receiver_ready(p)))
            peer.send(b'bad');peer.send(frame(0));peer.send(wire.encode_frame(3,1,bytes(16)))
            p.stdin.close()
            self.assertEqual(p.wait(timeout=5),6,p.stderr.read())
            report=json.loads((root/'rx.ground.json').read_text())
            self.assertEqual(report['counters']['malformed'],2)
            self.assertEqual(report['counters']['recorded'],1)
            self.assertEqual((root/'rx.ground.tvcrec').read_bytes()[32:],frame(0))

    def test_startup_bind_and_exclusive_write_failures(self):
        with tempfile.TemporaryDirectory() as d,socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as occupied:
            root=Path(d);occupied.bind(('127.0.0.1',0))
            p=self.receive(root,port=occupied.getsockname()[1]);p.stdin.close()
            self.assertEqual(p.wait(timeout=5),2)
            self.assertEqual(p.stdout.read(),b'')
            self.assertEqual(list(root.iterdir()),[])
            (root/'rx.ground.tvcrec').write_bytes(b'keep')
            p=self.receive(root);p.stdin.close()
            self.assertEqual(p.wait(timeout=5),4)
            self.assertEqual(p.stdout.read(),b'')
            self.assertEqual((root/'rx.ground.tvcrec').read_bytes(),b'keep')

    def test_signal_closes_recording_and_reports_incomplete_collection(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.receive(root);self.receiver_ready(p)
            p.send_signal(signal.SIGTERM)
            self.assertEqual(p.wait(timeout=5),3)
            report=json.loads((root/'rx.ground.json').read_text())
            self.assertTrue(report['interrupted'])
            wire.read_typed_recording(root/'rx.ground.tvcrec',expected_type=6)

    def test_receiver_usage_and_check_require_owner_exits(self):
        for args in (['receive','--out=/tmp','--label=../bad'],
                     ['receive','--out=/tmp','--label=run','--telemetry-port=-1'],
                     ['receive','--out=/tmp','--label=run','--telemetry-port=65536'],
                     ['receive','--out=/tmp','--label=run','--command-port=0'],
                     ['check']):
            p=subprocess.run([sys.executable,'-B','-m','ground.link',*args],cwd=ROOT,capture_output=True,timeout=5)
            self.assertEqual(p.returncode,1,p.stderr)

    def test_end_to_end_ground_loss_and_producer_send_failure_populations(self):
        for fault,received,trailing,errors in [(None,26,0,0),('eagain',25,0,1),('terminal',25,1,1),('all',0,26,26),('receiver_loss',24,1,0)]:
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d,socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sim:
                root=Path(d);rx=self.receive(root,drop=fault=='receiver_loss');port=self.receiver_ready(rx)
                env=dict(os.environ,TVC_TEST_PROOF=str(root/'proof.json'))
                if fault and fault!='receiver_loss':env['TVC_TEST_GROUND_SEND']=fault
                vehicle=producer.GroundDistribution().run_vehicle(root,'--ground=127.0.0.1:'+str(port),
                    env=env,binary=producer.BIN.with_name('freerun_faults'))
                self.addCleanup(self.cleanup,vehicle)
                ready=ready_line(vehicle,mode='freerun');self.assertEqual(ready['command_port'],'0')
                sim.connect(('127.0.0.1',int(ready['sensor_port'])))
                for tick in range(5):sim.send(producer.sensor_frame(tick))
                self.assertEqual(vehicle.wait(timeout=8),0,vehicle.stderr.read())
                self.finish(rx)
                args=[sys.executable,'-B','-m','ground.link','check',
                    '--vehicle-recording='+str(root/'run.control.tvcrec'),'--vehicle-summary='+str(root/'run.summary.json'),
                    '--ground-recording='+str(root/'rx.ground.tvcrec'),'--receiver-report='+str(root/'rx.ground.json'),
                    '--vehicle-exit-code=0','--receiver-exit-code=0','--out='+str(root/'check.json')]
                checked=subprocess.run(args,cwd=ROOT,capture_output=True,timeout=5)
                self.assertEqual(checked.returncode,0,checked.stderr)
                report=json.loads((root/'check.json').read_text());self.assertTrue(report['valid'],report)
                pop=report['populations']
                self.assertEqual((pop['vehicle_records'],pop['ground_records'],pop['ground_lost']),(26,received,26-received))
                self.assertEqual(pop['trailing_lost'],trailing)
                self.assertEqual(pop['send_errors'],errors)
                self.assertEqual(pop['not_recorded_after_success'],26-errors-received)
                self.assertEqual(pop['attempted'],26)
                proof=json.loads((root/'proof.json').read_text())
                self.assertEqual([proof[k] for k in ('episodes','pids','batches','histograms','sends','terminal_sends')],[26,5,26,26,37,12])
                self.assertFalse(proof['terminal_bytes_changed'])
                # A rerun cannot overwrite an earlier validation report.
                self.assertEqual(subprocess.run(args,cwd=ROOT,capture_output=True,timeout=5).returncode,4)


if __name__=='__main__':unittest.main()

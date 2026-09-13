"""Independent receiver dispositions and offline population examples."""
import errno
import hashlib
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from ground import wire, link


def frame(tick, seq=None, theta=0.0):
    fields = wire.decode_payload(6, bytes(128))
    fields.update(tick=tick, sensor_tick=tick, theta=theta)
    return wire.encode_frame(6, tick if seq is None else seq, wire.encode_payload(6, fields))


def recording(path, frames):
    path.write_bytes(wire.HEADER.pack(wire.MAGIC, wire.VERSION, 0, wire.SCHEMA_HASHES[6], 123, 456)+b''.join(frames))


class FailingReport:
    def __init__(self, file, fault):
        self.file, self.fault = file, fault
    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def write(self, data):
        if self.fault == 'write': raise OSError(errno.ENOSPC, 'report full')
        return self.file.write(data[:1] if self.fault == 'short' else data)
    def flush(self):
        if self.fault == 'flush': raise OSError(errno.EIO, 'report flush')
        self.file.flush()
    def close(self):
        self.file.close()
        if self.fault == 'close': raise OSError(errno.EIO, 'report close')


class ReceiverDispositions(unittest.TestCase):
    def test_frozen_control_known_answer_is_recorded_verbatim(self):
        fixture = Path(__file__).resolve().parents[1]/'golden/frame_control.bin'
        raw = fixture.read_bytes()
        self.assertEqual(len(raw),142)
        self.assertEqual(raw[:10],bytes.fromhex('90 eb 01 06 80 00 04 00 00 00'))
        output = io.BytesIO(); receiver = link.Receiver(output)
        receiver.accept(raw, ('127.0.0.1',1000))
        self.assertEqual(receiver.counters['recorded'],1)
        self.assertEqual(receiver.counters['malformed'],0)
        self.assertEqual(output.getvalue(),raw)

    def test_continuous_ingress_returns_to_stdin_within_512_receives(self):
        class Peer:
            calls=0
            def recvfrom(self, size):
                self.calls += 1
                if self.calls > 512: raise BlockingIOError(errno.EAGAIN,'empty')
                return frame(self.calls), ('127.0.0.1',1000)
        peer=Peer(); receiver=link.Receiver(io.BytesIO())
        def eof(fd,size):
            self.assertLessEqual(peer.calls,512)
            self.assertGreater(peer.calls,0)
            return b''
        with patch('ground.link.select.select',side_effect=[([peer],[],[]),([0],[],[])]), \
             patch('ground.link.os.read',side_effect=eof):
            self.assertFalse(link.collect(peer,0,receiver,lambda:False))
        self.assertEqual(receiver.counters['recorded'],512)

    def test_receiver_report_failures_return_four(self):
        for fault in ('write','short','flush','close'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
                original=open
                def opened(path,*args,**kwargs):
                    f=original(path,*args,**kwargs)
                    return FailingReport(f,fault) if str(path).endswith('.ground.json') and args[0]=='x' else f
                with patch('ground.link.open',side_effect=opened),patch('ground.link.collect',return_value=False), \
                     patch('ground.link.sys.stderr',new_callable=io.StringIO):
                    self.assertEqual(link.receive(d,'run',0,stdout=io.StringIO()),4)
                wire.read_typed_recording(Path(d)/'run.ground.tvcrec',expected_type=6)

    def test_exact_priority_and_verbatim_writes(self):
        output = io.BytesIO()
        receiver = link.Receiver(output)
        first, foreign = ('127.0.0.1', 1000), ('127.0.0.1', 1001)
        packets = [(b'bad', first), (frame(10, 0xffffffff), first),
                   (b'bad', foreign), (frame(10, 0xffffffff), first),
                   (frame(9, 3), first), (frame(10, 0xffffffff, 0.25), first),
                   (frame(11, 0), first)]
        for data, source in packets: receiver.accept(data, source)
        self.assertEqual(output.getvalue(), frame(10, 0xffffffff)+frame(11, 0))
        self.assertEqual(receiver.source, first)
        self.assertEqual(receiver.counters, dict(received=7,foreign=1,malformed=1,
            duplicate=1,out_of_order=1,conflict=1,recorded=2,write_failed_datagrams=0,
            socket_errors=0,last_errno=0))

    def test_invalid_datagrams_cannot_pin_or_write(self):
        valid = frame(0)
        corrupt = valid[:-1]+bytes([valid[-1]^1])
        bad_count = bytearray(wire.encode_payload(6, wire.decode_payload(6, bytes(128))))
        bad_count[120] = 10
        packets = [valid[:-1], valid+b'x', valid+valid, corrupt,
                   wire.encode_frame(3,0,bytes(16)), wire.encode_frame(6,0,bytes(127)),
                   wire.encode_frame(6,0,bad_count), frame(0,theta=float('nan'))]
        r = link.Receiver(io.BytesIO())
        for packet in packets: r.accept(packet, ('127.0.0.1',1))
        self.assertIsNone(r.source)
        self.assertEqual(r.counters['malformed'],8)
        self.assertEqual(r.counters['recorded'],0)

    def test_partial_write_is_a_failed_datagram(self):
        class Short(io.BytesIO):
            def write(self, data): return super().write(data[:10])
        r = link.Receiver(Short())
        with self.assertRaises(OSError): r.accept(frame(0), ('127.0.0.1',1))
        self.assertEqual(r.counters['received'],1)
        self.assertEqual(r.counters['recorded'],0)
        self.assertEqual(r.counters['write_failed_datagrams'],1)

    def test_eof_drains_and_deadline_stops_continuous_traffic(self):
        class Peer:
            def __init__(self): self.n=0
            def recvfrom(self, size):
                self.n+=1
                return frame(self.n), ('127.0.0.1',1)
        r=link.Receiver(io.BytesIO())
        clock=iter([0, 0, 99_000_000, 100_000_000])
        with patch('ground.link.time.monotonic_ns',side_effect=lambda:next(clock)), \
             patch('ground.link.select.select',return_value=([0],[],[])), \
             patch('ground.link.os.read',return_value=b''):
            self.assertTrue(link.collect(Peer(),0,r,lambda:False))
        self.assertEqual(r.counters['recorded'],2)

    def test_idle_and_transient_receive_errors_do_not_invent_datagrams(self):
        class Peer:
            def __init__(self): self.errors=iter([InterruptedError(errno.EINTR,'signal'),BlockingIOError(errno.EAGAIN,'empty')])
            def recvfrom(self,size): raise next(self.errors)
        r=link.Receiver(io.BytesIO())
        with patch('ground.link.select.select',return_value=([0],[],[])),patch('ground.link.os.read',return_value=b''):
            self.assertFalse(link.collect(Peer(),0,r,lambda:False))
        self.assertEqual(r.counters['received'],0)
        self.assertEqual(r.counters['socket_errors'],1)
        self.assertEqual(r.counters['last_errno'],errno.EINTR)


    def test_recording_write_flush_close_errors_remain_nonzero(self):
        for fault in ('write','flush','close'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
                original=open
                class Writer:
                    wrote=False
                    def __init__(self,file): self.file=file
                    def write(self,data):
                        if len(data)==142:
                            self.wrote=True
                            if fault=='write': raise OSError(errno.ENOSPC,'full')
                        return self.file.write(data)
                    def flush(self):
                        if self.wrote and fault=='flush': raise OSError(errno.EIO,'flush')
                        self.file.flush()
                    def close(self):
                        self.file.close()
                        if self.wrote and fault=='close': raise OSError(errno.EIO,'close')
                def opened(path,*args,**kwargs):
                    f=original(path,*args,**kwargs)
                    return Writer(f) if str(path).endswith('.ground.tvcrec') and args and args[0]=='xb' else f
                def collect(peer,fd,receiver,stopped):
                    receiver.accept(frame(0),('127.0.0.1',1))
                    return False
                with patch('ground.link.open',side_effect=opened),patch('ground.link.collect',side_effect=collect):
                    self.assertEqual(link.receive(d,'run',0,stdout=io.StringIO()),4)
                report=json.loads((Path(d)/'run.ground.json').read_text())
                self.assertEqual(report['counters']['write_failed_datagrams'],int(fault=='write'))
                self.assertEqual(report['frame_count'],int(fault!='write'))

    def test_nontransient_receive_failure_has_no_datagram_disposition(self):
        class Peer:
            def recvfrom(self,size): raise OSError(errno.EBADF,'closed')
        r=link.Receiver(io.BytesIO())
        with patch('ground.link.select.select',return_value=([0],[],[])),patch('ground.link.os.read',return_value=b''):
            with self.assertRaises(OSError): link.collect(Peer(),0,r,lambda:False)
        self.assertEqual(r.counters['received'],0)
        self.assertEqual(r.counters['socket_errors'],1)
        self.assertEqual(r.counters['last_errno'],errno.EBADF)


class OfflineAccounting(unittest.TestCase):
    def fixtures(self, root, indices=(1,2,4), errors=1):
        vehicle, ground = root/'vehicle.tvcrec', root/'ground.tvcrec'
        recording(vehicle, [frame(i) for i in range(6)])
        recording(ground, [frame(i) for i in indices])
        counters=dict(received=len(indices),foreign=0,malformed=0,duplicate=0,out_of_order=0,
                      conflict=0,recorded=len(indices),write_failed_datagrams=0,socket_errors=0,last_errno=0)
        receiver=dict(format='tvc-ground-receiver-1',bound=['127.0.0.1',24003],
            source=['127.0.0.1',45678] if indices else None,recording=str(ground),
            recording_sha256=hashlib.sha256(ground.read_bytes()).hexdigest(),frame_count=len(indices),
            counters=counters,interrupted=False,shutdown_truncated=False)
        summary=dict(mode='freerun',total_cycles=6,telemetry=dict(records=6,dropped=0),applied=dict(ground=True),
            ground=dict(requested=True,endpoint='127.0.0.1:24003',setup_errno=0,resolver_error=0,
                        attempted=6,sent=6-errors,send_errors=errors,last_errno=errno.EAGAIN if errors else 0,short_sends=0))
        paths=dict(vehicle_recording=vehicle,ground_recording=ground,
                   vehicle_summary=root/'vehicle.json',receiver_report=root/'receiver.json')
        paths['vehicle_summary'].write_text(json.dumps(summary))
        paths['receiver_report'].write_text(json.dumps(receiver))
        return paths,summary,receiver

    def check(self,paths,**kw):
        return link.check(**paths,vehicle_exit_code=kw.get('vehicle_exit_code',0),
                          receiver_exit_code=kw.get('receiver_exit_code',0))

    def test_independent_boundary_populations(self):
        cases=[((0,1,2,3,4,5),0,(0,0,0,0)),((1,2,4),1,(1,1,1,2)),
               ((),0,(0,0,6,6)),((0,1,2,3,4),0,(0,0,1,1))]
        for indices,errors,want in cases:
            with self.subTest(indices=indices),tempfile.TemporaryDirectory() as d:
                paths,_,_=self.fixtures(Path(d),indices,errors)
                result=self.check(paths)
                self.assertTrue(result['valid'],result)
                self.assertEqual(tuple(result['populations'][k] for k in
                    ('leading_lost','interior_lost','trailing_lost','not_recorded_after_success')),want)
                self.assertEqual(result['populations']['ground_lost'],6-len(indices))
                self.assertEqual(result['delivery_complete'],len(indices)==6)
                self.assertEqual(len(result['input_sha256']),4)

    def test_checker_report_failures_return_four(self):
        for fault in ('write','short','flush','close'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
                root=Path(d);paths,_,_=self.fixtures(root)
                output=root/'check.json'; original=open
                def opened(path,*args,**kwargs):
                    f=original(path,*args,**kwargs)
                    return FailingReport(f,fault) if Path(path)==output and args[0]=='x' else f
                args=['check','--out='+str(output),'--vehicle-exit-code=0','--receiver-exit-code=0']
                args.extend('--'+key.replace('_','-')+'='+str(value) for key,value in paths.items())
                with patch('ground.link.open',side_effect=opened),patch('ground.link.sys.stderr',new_callable=io.StringIO):
                    self.assertEqual(link.main(args),4)

    def test_wrap_uses_source_ordinal_not_modular_gap_guess(self):
        frames=[frame(10+i,(2**32-2+i)%2**32) for i in range(4)]
        triples=[(wire.decode_datagram(f,{6})[1],10+i,f) for i,f in enumerate(frames)]
        result=link.match_streams(iter(triples),iter([triples[0],triples[2]]),start_ordinal=2**32-2)
        self.assertEqual(result,dict(vehicle_records=4,ground_records=2,leading_lost=0,interior_lost=1,trailing_lost=1,ground_lost=2))

    def test_metadata_and_ownership_fail_closed(self):
        mutations=[('missing',lambda s,r:s['ground'].pop('sent')),
            ('boolean',lambda s,r:s['ground'].update(sent=True)),
            ('negative',lambda s,r:r['counters'].update(foreign=-1)),
            ('impossible',lambda s,r:s['ground'].update(sent=2,send_errors=4)),
            ('attempts',lambda s,r:s['ground'].update(attempted=7)),
            ('counts',lambda s,r:r['counters'].update(recorded=4)),
            ('digest',lambda s,r:r.update(recording_sha256='0'*64)),
            ('interrupted',lambda s,r:r.update(interrupted=True)),
            ('truncated',lambda s,r:r.update(shutdown_truncated=True)),
            ('ring',lambda s,r:s['telemetry'].update(dropped=1)),
            ('disabled',lambda s,r:s['applied'].update(ground=False)),
            ('malformed',lambda s,r:r['counters'].update(malformed=1,received=4)),
            ('conflict',lambda s,r:r['counters'].update(conflict=1,received=4)),
            ('telemetry shape',lambda s,r:s.update(telemetry=[])),
            ('ground shape',lambda s,r:s.update(ground=None)),
            ('applied shape',lambda s,r:s.update(applied=[]))]
        for name, mutate in mutations:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
                paths,s,r=self.fixtures(Path(d));mutate(s,r)
                paths['vehicle_summary'].write_text(json.dumps(s));paths['receiver_report'].write_text(json.dumps(r))
                self.assertFalse(self.check(paths)['valid'])
        with tempfile.TemporaryDirectory() as d:
            paths,_,_=self.fixtures(Path(d))
            failed=self.check(paths,vehicle_exit_code=4)
            self.assertFalse(failed['valid'])
            self.assertEqual(failed['reported_counts']['vehicle_records'],6)
            self.assertFalse(self.check(paths,receiver_exit_code=4)['valid'])
            paths['vehicle_summary'].unlink()
            result=self.check(paths)
            self.assertFalse(result['valid'])
            self.assertIsNone(result['input_sha256']['vehicle_summary'])

    def test_recording_integrity_is_independent_of_count_equations(self):
        mutations=[lambda f:[frame(1,theta=.25),*f[1:]],lambda f:[frame(1,seq=9),*f[1:]],
                   lambda f:[f[0],f[0],f[2]],lambda f:[*f[:2],frame(99)],
                   lambda f:[f[0][:-1],*f[1:]]]
        for mutate in mutations:
            with tempfile.TemporaryDirectory() as d:
                paths,_,report=self.fixtures(Path(d))
                recording(paths['ground_recording'],mutate([frame(i) for i in (1,2,4)]))
                report['recording_sha256']=hashlib.sha256(paths['ground_recording'].read_bytes()).hexdigest()
                paths['receiver_report'].write_text(json.dumps(report))
                self.assertFalse(self.check(paths)['valid'])

    def test_schema_recovery_and_json_resource_failures_are_rejected(self):
        for case in ('schema','crc','tail','sequence','duplicate_json','overflow_float','nested','oversize'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as d:
                paths,_,_=self.fixtures(Path(d))
                if case in ('schema','crc','tail','sequence'):
                    path=paths['vehicle_recording'];raw=bytearray(path.read_bytes())
                    if case=='schema': raw[12:16]=bytes(4)
                    elif case=='crc': raw[32+141]^=1
                    elif case=='tail': raw.extend(b'x')
                    else: raw[32:32+142]=frame(0,seq=2)
                    path.write_bytes(raw)
                else:
                    path=paths['vehicle_summary']
                    values={'duplicate_json':'{"mode":0,"mode":1}', 'overflow_float':'{"x":1e999}',
                            'nested':'['*2000+']'*2000, 'oversize':' '* (link.MAX_REPORT_BYTES+1)}
                    path.write_text(values[case])
                self.assertFalse(self.check(paths)['valid'])

    def test_header_reader_input_is_bounded_and_frames_are_streamed(self):
        with tempfile.TemporaryDirectory() as d:
            paths,_,_=self.fixtures(Path(d))
            original=wire.read_typed_recording
            sizes=[]
            def read(path,**kw):
                sizes.append(Path(path).stat().st_size)
                return original(path,**kw)
            with patch('ground.link.wire.read_typed_recording',side_effect=read):
                self.assertTrue(self.check(paths)['valid'])
            self.assertEqual(sizes,[32,32])


if __name__=='__main__': unittest.main()

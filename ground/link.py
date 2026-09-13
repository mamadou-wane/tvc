"""Observational type-6 collection and offline delivery accounting."""
import argparse
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import select
import signal
import socket
import sys
import tempfile
import time

from ground import wire

FRAME_BYTES = wire.FRAME_HEAD.size + wire.PAYLOAD_SIZES[6] + wire.CRC.size
DISPOSITIONS = ('foreign', 'malformed', 'duplicate', 'out_of_order', 'conflict',
                'recorded', 'write_failed_datagrams')
COUNTERS = ('received', *DISPOSITIONS, 'socket_errors', 'last_errno')
MAX_REPORT_BYTES = 1024 * 1024


def control_frame(data):
    _, seq, payload = wire.decode_datagram(data, {6})
    fields = wire.decode_payload(6, payload)
    if not all(math.isfinite(fields[k]) for k in ('theta', 'omega', 'cmd', 'i_state', 'd_prev')):
        raise ValueError('nonfinite control record')
    return seq, fields['tick'], data


def write_all(stream, data):
    if stream.write(data) != len(data):
        raise OSError(errno.EIO, 'short output write')


class Receiver:
    """One telemetry source and last frame; no growing history or reorder queue."""
    def __init__(self, recording):
        self.recording = recording
        self.source = None
        self.last = None
        self.last_tick = None
        self.counters = dict.fromkeys(COUNTERS, 0)

    def accept(self, data, source):
        c = self.counters
        c['received'] += 1
        if self.source is not None and source != self.source:
            c['foreign'] += 1
            return
        try:
            _, tick, raw = control_frame(data)
        except ValueError:
            c['malformed'] += 1
            return
        if self.source is None:
            self.source = source
        if self.last_tick is not None:
            if tick < self.last_tick:
                c['out_of_order'] += 1
                return
            if tick == self.last_tick:
                c['duplicate' if raw == self.last else 'conflict'] += 1
                return
        try:
            write_all(self.recording, raw)
        except OSError:
            c['write_failed_datagrams'] += 1
            raise
        c['recorded'] += 1
        self.last, self.last_tick = raw, tick


def collect(peer, stdin_fd, receiver, stopped):
    """EOF follows producer exit; drain to EAGAIN within the cleanup deadline."""
    deadline = None
    while not stopped():
        if deadline is None:
            try:
                readable, _, _ = select.select([peer, stdin_fd], [], [], 0.1)
            except InterruptedError:
                continue
            if stdin_fd in readable:
                try:
                    data = os.read(stdin_fd, 4096)
                except InterruptedError:
                    continue
                if not data:
                    deadline = time.monotonic_ns() + 100_000_000
            if peer not in readable and deadline is None:
                continue
        for _ in range(512):
            if stopped():
                return False
            if deadline is not None and time.monotonic_ns() >= deadline:
                return True
            try:
                data, source = peer.recvfrom(65536)
            except BlockingIOError:
                if deadline is not None:
                    return False
                break
            except OSError as error:
                receiver.counters['socket_errors'] += 1
                receiver.counters['last_errno'] = error.errno or errno.EIO
                if error.errno == errno.EINTR:
                    continue
                raise
            receiver.accept(data, source)
    return False


def digest_file(path):
    digest = hashlib.sha256()
    if not Path(path).is_file():
        raise ValueError('not a regular file: '+str(path))
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def receive(out, label, telemetry_port, *, stdin_fd=0, stdout=None, stopped=lambda: False):
    stdout = sys.stdout if stdout is None else stdout
    peer = None
    try:
        peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        peer.setblocking(False)
        peer.bind(('127.0.0.1', telemetry_port))
    except OSError as error:
        if peer is not None:
            peer.close()
        print('receiver socket: '+str(error), file=sys.stderr)
        return 2
    recording = report_file = None
    recorder = None
    truncated = False
    code = 0
    path = Path(out) / (label+'.ground.tvcrec')
    try:
        Path(out).mkdir(parents=True, exist_ok=True)
        report_file = open(Path(out)/(label+'.ground.json'), 'x')
        recording = open(path, 'xb')
        write_all(recording, wire.HEADER.pack(wire.MAGIC, wire.VERSION, 0,
                  wire.SCHEMA_HASHES[6], time.monotonic_ns(), time.time_ns()))
        recording.flush()
        recorder = Receiver(recording)
        print(f'ready ground telemetry_port={peer.getsockname()[1]} pid={os.getpid()}',
              file=stdout, flush=True)
        try:
            truncated = collect(peer, stdin_fd, recorder, stopped)
        except OSError as error:
            code = 4 if recorder.counters['write_failed_datagrams'] else 6
            print('receiver: '+str(error), file=sys.stderr)
    except OSError as error:
        code = 4
        print('receiver output: '+str(error), file=sys.stderr)
    finally:
        bound = peer.getsockname()
        peer.close()
        if recording is not None:
            try:
                try:
                    recording.flush()
                finally:
                    recording.close()
            except OSError as error:
                code = 4
                print('receiver close: '+str(error), file=sys.stderr)
    interrupted = stopped()
    if code != 4:
        if interrupted:
            code = 3
        elif truncated or (recorder and (recorder.counters['malformed'] or recorder.counters['conflict'])):
            code = 6
    if report_file is not None:
        try:
            with report_file:
                report = dict(format='tvc-ground-receiver-1', bound=bound,
                    source=recorder.source if recorder else None, recording=str(path),
                    recording_sha256=digest_file(path) if recording else None,
                    frame_count=recorder.counters['recorded'] if recorder else 0,
                    counters=recorder.counters if recorder else dict.fromkeys(COUNTERS, 0),
                    interrupted=interrupted, shutdown_truncated=truncated)
                write_all(report_file, json.dumps(report, sort_keys=True, allow_nan=False)+'\n')
                report_file.flush()
        except (OSError, ValueError) as error:
            code = 4
            print('receiver report: '+str(error), file=sys.stderr)
    return code


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, name, signed=False):
    require(type(value) is int and (signed or value >= 0), 'invalid integer: '+name)
    return value


def boolean(value, name):
    require(type(value) is bool, 'invalid boolean: '+name)
    return value


def endpoint(value, name):
    require(isinstance(value, (list, tuple)) and len(value) == 2, 'invalid endpoint: '+name)
    require(isinstance(value[0], str), 'invalid endpoint host: '+name)
    socket.inet_pton(socket.AF_INET, value[0])
    require(0 < integer(value[1], name) <= 65535, 'invalid endpoint port: '+name)
    return value[0]+':'+str(value[1])


def read_json(path, expected_digest):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key: '+key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('nonfinite JSON: '+value)
    with open(path, 'rb') as stream:
        data = stream.read(MAX_REPORT_BYTES + 1)
    require(len(data) <= MAX_REPORT_BYTES, 'report exceeds bounded input size')
    require(hashlib.sha256(data).hexdigest() == expected_digest, 'report changed while checking')
    def finite_float(value):
        parsed = float(value)
        require(math.isfinite(parsed), 'nonfinite JSON number')
        return parsed
    try:
        result = json.loads(data, object_pairs_hook=unique, parse_constant=invalid, parse_float=finite_float)
    except RecursionError as error:
        raise ValueError('excessive JSON nesting') from error
    require(isinstance(result, dict), 'report is not an object')
    return result


def recording_frames(path, expected_digest):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        header = stream.read(wire.HEADER.size)
        digest.update(header)
        # The existing typed reader loads its entire input; its header check stays bounded here.
        with tempfile.NamedTemporaryFile() as probe:
            probe.write(header)
            probe.flush()
            wire.read_typed_recording(probe.name, expected_type=6)
        while True:
            raw = stream.read(FRAME_BYTES)
            if not raw:
                break
            digest.update(raw)
            yield control_frame(raw)
        require(digest.hexdigest() == expected_digest, 'recording changed while checking')


def match_streams(vehicle, ground, *, start_ordinal=0):
    """Merge ordered frames; source ordinals resolve wrap and missing boundaries."""
    next_ground = next(ground, None)
    previous_vehicle = previous_ground = last_match = None
    vehicle_count = ground_count = leading = interior = 0
    for seq, tick, raw in vehicle:
        require(seq == (start_ordinal + vehicle_count) % 2**32, 'vehicle sequence is not contiguous')
        require(previous_vehicle is None or tick > previous_vehicle, 'vehicle ticks are not increasing')
        previous_vehicle = tick
        if next_ground is not None:
            _, ground_tick, ground_raw = next_ground
            require(ground_tick >= tick, 'unmatched or repeated ground tick')
            if ground_tick == tick:
                require(previous_ground is None or ground_tick > previous_ground, 'ground ticks are not increasing')
                require(ground_raw == raw, 'ground frame differs from authoritative frame')
                if last_match is None:
                    leading = vehicle_count
                else:
                    interior += vehicle_count-last_match-1
                last_match = vehicle_count
                previous_ground = ground_tick
                ground_count += 1
                next_ground = next(ground, None)
        vehicle_count += 1
    require(next_ground is None, 'ground frame beyond authoritative recording')
    trailing = vehicle_count if last_match is None else vehicle_count-last_match-1
    return dict(vehicle_records=vehicle_count, ground_records=ground_count,
                leading_lost=leading, interior_lost=interior, trailing_lost=trailing,
                ground_lost=leading+interior+trailing)


def check(*, vehicle_recording, vehicle_summary, ground_recording, receiver_report,
          vehicle_exit_code, receiver_exit_code):
    paths = dict(vehicle_recording=vehicle_recording, vehicle_summary=vehicle_summary,
                 ground_recording=ground_recording, receiver_report=receiver_report)
    result = dict(format='tvc-ground-reconciliation-1', input_sha256=dict.fromkeys(paths),
                  vehicle_exit_code=vehicle_exit_code, receiver_exit_code=receiver_exit_code,
                  valid=False, delivery_complete=False, status='invalid', failed_checks=[], populations=None, reported_counts=None)
    errors = result['failed_checks']
    for name, path in paths.items():
        try:
            result['input_sha256'][name] = digest_file(path)
        except (OSError, ValueError) as error:
            errors.append(name+': '+str(error))
    if errors:
        return result
    hashes = result['input_sha256']
    try:
        summary = read_json(vehicle_summary, hashes['vehicle_summary'])
        report = read_json(receiver_report, hashes['receiver_report'])
        reported = {}
        for name, data, keys in (
            ('vehicle_records', summary, ('telemetry', 'records')),
            ('ring_drops', summary, ('telemetry', 'dropped')),
            ('total_cycles', summary, ('total_cycles',)),
            ('ground_records', report, ('counters', 'recorded')),
            ('attempted', summary, ('ground', 'attempted')),
            ('sent', summary, ('ground', 'sent')),
            ('send_errors', summary, ('ground', 'send_errors'))):
            for key in keys:
                data = data.get(key) if isinstance(data, dict) else None
            reported[name] = data if type(data) is int and data >= 0 else None
        result['reported_counts'] = reported
        require(summary.get('mode') == 'freerun', 'vehicle mode is not freerun')
        require(report.get('format') == 'tvc-ground-receiver-1', 'wrong receiver report format')
        require(integer(vehicle_exit_code, 'vehicle exit') == 0, 'vehicle exited unsuccessfully')
        require(integer(receiver_exit_code, 'receiver exit') == 0, 'receiver exited unsuccessfully')
        require(not boolean(report.get('interrupted'), 'interrupted'), 'receiver interrupted')
        require(not boolean(report.get('shutdown_truncated'), 'shutdown_truncated'), 'receiver shutdown incomplete')
        c = report['counters']
        require(isinstance(c, dict), 'receiver counters are not an object')
        for name in COUNTERS:
            integer(c.get(name), 'receiver.'+name)
        require(c['received'] == sum(c[k] for k in DISPOSITIONS), 'receiver dispositions do not conserve datagrams')
        require(c['malformed'] == c['conflict'] == c['write_failed_datagrams'] == 0, 'receiver integrity/output failure')
        require((c['socket_errors'] == 0 and c['last_errno'] == 0) or
                (c['socket_errors'] > 0 and c['last_errno'] == errno.EINTR), 'receiver socket failure')
        bound = endpoint(report.get('bound'), 'receiver bound')
        if report.get('source') is not None:
            endpoint(report['source'], 'receiver source')
        require('source' in report, 'missing receiver source')
        require(isinstance(report.get('recording'), str) and report['recording'], 'missing recording path')
        require(report.get('recording_sha256') == hashes['ground_recording'], 'receiver recording digest mismatch')
        integer(report.get('frame_count'), 'receiver frame_count')
        total = integer(summary.get('total_cycles'), 'total_cycles')
        local = summary['telemetry']
        require(isinstance(local, dict), 'telemetry is not an object')
        local_count = integer(local.get('records'), 'telemetry.records')
        require(integer(local.get('dropped'), 'telemetry.dropped') == 0, 'authoritative ring dropped records')
        g = summary['ground']
        require(isinstance(g, dict), 'ground is not an object')
        require(isinstance(summary['applied'], dict), 'applied is not an object')
        requested = boolean(g.get('requested'), 'ground.requested')
        applied = boolean(summary['applied'].get('ground'), 'applied.ground')
        for name in ('attempted', 'sent', 'send_errors', 'last_errno', 'short_sends', 'setup_errno'):
            integer(g.get(name), 'ground.'+name)
        integer(g.get('resolver_error'), 'ground.resolver_error', signed=True)
        if not requested:
            result['status'] = 'disabled'
            require(False, 'ground distribution disabled')
        require(applied and g['setup_errno'] == g['resolver_error'] == 0, 'ground startup was not successful')
        require(g.get('endpoint') == bound, 'ground destination differs from receiver binding')
        require(g['short_sends'] <= g['send_errors'], 'short send count exceeds send errors')
        require((g['send_errors'] == 0 and g['last_errno'] == 0) or
                (g['send_errors'] > 0 and g['last_errno'] > 0), 'ground errno/count mismatch')
        vehicle = recording_frames(vehicle_recording, hashes['vehicle_recording'])
        ground = recording_frames(ground_recording, hashes['ground_recording'])
        try:
            pop = match_streams(vehicle, ground)
        finally:
            vehicle.close()
            ground.close()
        result['populations'] = pop
        v, observed = pop['vehicle_records'], pop['ground_records']
        a, sent, failed = g['attempted'], g['sent'], g['send_errors']
        pop.update(attempted=a, sent=sent, send_errors=failed, not_recorded_after_success=sent-observed)
        require(v == local_count == total, 'authoritative frame/count mismatch')
        require(observed == report['frame_count'] == c['recorded'], 'receiver frame/count mismatch')
        require((report['source'] is None) == (observed == 0), 'receiver source/count mismatch')
        require(a == sent+failed and a == v, 'ground attempt conservation failed')
        require(0 <= observed <= sent <= a and failed <= pop['ground_lost'], 'impossible ground populations')
        require(v == observed+pop['ground_lost'], 'ground frame conservation failed')
        require(pop['ground_lost'] == failed+pop['not_recorded_after_success'], 'ground loss conservation failed')
        result.update(valid=True, delivery_complete=observed == v and v > 0,
                      status='valid' if v else 'empty')
    except (OSError, ValueError, KeyError, TypeError) as error:
        errors.append(str(error))
    return result


class Arguments(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, 'usage: '+message+'\n')


def nonnegative(value):
    if not value.isascii() or not value.isdecimal():
        raise argparse.ArgumentTypeError('a nonnegative decimal integer is required')
    return int(value)


def main(argv=None):
    parser = Arguments(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True, parser_class=Arguments)
    receive_args = commands.add_parser('receive')
    receive_args.add_argument('--telemetry-port', type=nonnegative, default=24003)
    receive_args.add_argument('--out', required=True)
    receive_args.add_argument('--label', required=True)
    check_args = commands.add_parser('check')
    for name in ('vehicle-recording', 'vehicle-summary', 'ground-recording', 'receiver-report', 'out'):
        check_args.add_argument('--'+name, required=True)
    for name in ('vehicle-exit-code', 'receiver-exit-code'):
        check_args.add_argument('--'+name, type=nonnegative, required=True)
    args = parser.parse_args(argv)
    if args.action == 'receive':
        if not args.label or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in args.label):
            parser.error('invalid label')
        if args.telemetry_port > 65535:
            parser.error('telemetry port outside 0..65535')
        interrupted = False
        def interrupt(_signum, _frame):
            nonlocal interrupted
            interrupted = True
        prior = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            return receive(args.out, args.label, args.telemetry_port, stopped=lambda: interrupted)
        finally:
            for sig, handler in prior.items():
                signal.signal(sig, handler)
    options = vars(args).copy()
    options.pop('action')
    out = options.pop('out')
    result = check(**options)
    try:
        with open(out, 'x') as report:
            write_all(report, json.dumps(result, sort_keys=True, allow_nan=False)+'\n')
            report.flush()
    except OSError as error:
        print('ground check output: '+str(error), file=sys.stderr)
        return 4
    return 0 if result['valid'] else 6


if __name__ == '__main__':
    raise SystemExit(main())

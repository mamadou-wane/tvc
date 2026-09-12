"""Independently scheduled simulator; packet receipt and model steps have separate owners."""
import ctypes
import errno
import json
import math
import os
from pathlib import Path
import signal
import socket
import time
from collections import deque

from ground import wire
from sim import actuator, control_ref, environment, episode, link, plant, rng, scenario, sensor
from sim.run_sim import word

PERIOD_NS = 2_000_000
GRACE_TICKS = 16


class Timespec(ctypes.Structure):
    _fields_ = [('tv_sec', ctypes.c_long), ('tv_nsec', ctypes.c_long)]


def sleeper():
    libc = ctypes.CDLL(None)
    sleep = libc.clock_nanosleep
    sleep.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(Timespec), ctypes.c_void_p]
    sleep.restype = ctypes.c_int
    return sleep


def sleep_until(deadline, stopped, sleep):
    target = Timespec(*divmod(deadline, 1_000_000_000))
    while not stopped():
        error = sleep(time.CLOCK_MONOTONIC, 1, ctypes.byref(target), None)
        if error == 0: return
        if error != errno.EINTR: raise OSError(error, 'absolute simulator sleep')
    raise InterruptedError('simulator interrupted')


def validate_ticks(ticks):
    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 2:
        raise ValueError('freerun requires ticks >= 2')


class Model:
    def __init__(self, spec, seed, delay_ticks):
        validate_ticks(spec.ticks)
        if spec.commands: raise ValueError('live command-bearing freerun scenarios are unsupported')
        if delay_ticks not in (0, 1): raise ValueError('delay must be 0 or 1')
        for p in (spec.loss_up, spec.loss_down):
            if not math.isfinite(p) or not 0 <= p <= 1: raise ValueError('loss outside [0,1]')
        self.spec = spec
        self.truth = spec.initial
        self.act = actuator.initial()
        self.delay = deque([None] * delay_ticks)
        self.streams = [rng.SplitMix64(rng.stream_state(seed, name))
                        for name in ('link.loss.up', 'link.loss.down')]
        self.draws = [0, 0]
        self.up = dict.fromkeys(('generated', 'intentionally_lost', 'transmitted', 'sensor_tx_fail',
                                 'forced_transmit', 'forced_drop'), 0)
        self.down = dict.fromkeys(('received', 'intentionally_lost', 'actuator_selected',
                                   'superseded', 'malformed', 'invalid'), 0)
        self.term = dict.fromkeys(('up_attempts', 'up_intentionally_lost', 'up_tx_fail', 'up_transmitted',
                                  'down_received_raw', 'down_intentionally_lost', 'down_survived'), 0)
        self.events = dict.fromkeys(('plant_steps', 'actuator_updates', 'fifo_advances', 'sensor_observations'), 0)
        self.reason = None
        self.vehicle_seen = None

    def loss(self, direction, tick, terminal=False, prologue=False):
        index = 0 if direction == 'up' else 1
        p = self.spec.loss_up if index == 0 else self.spec.loss_down
        raw = link.draw_drop(self.streams[index], p)
        self.draws[index] += 1
        override = False if prologue else None if terminal else scenario.forced_drop_at(self.spec, tick, direction=direction)
        return raw, raw if override is None else override

    def receive(self, packets, body_tick):
        survivors = []
        for data in packets:
            try:
                _, _, payload = wire.decode_datagram(data, {5})
                value = wire.decode_payload(5, payload)
            except ValueError:
                self.down['malformed'] += 1
                continue
            terminal = value['status'] & 255 == 3
            _, drop = self.loss('down', body_tick, terminal=terminal)
            if terminal:
                self.term['down_received_raw'] += 1
                self.term['down_intentionally_lost' if drop else 'down_survived'] += 1
            else:
                self.down['received'] += 1
                if drop: self.down['intentionally_lost'] += 1
            if drop: continue
            if not terminal and not math.isfinite(value['delta']):
                self.down['invalid'] += 1
                raise ValueError('nonfinite actuator command')
            if terminal:
                reason = (value['status'] >> 8) & 255
                if not 1 <= reason <= 8: raise ValueError('invalid terminal actuator reason')
                self.vehicle_seen = reason
            else: survivors.append(value)
        if self.vehicle_seen is not None:
            self.down['superseded'] += len(survivors)
            if self.reason is None: self.reason = episode.SimReason.SIM_VEHICLE_TERMINAL
            return None
        if not survivors: return None
        selected = max(survivors, key=lambda v: v['tick'])
        self.down['actuator_selected'] += 1
        self.down['superseded'] += len(survivors) - 1
        return selected['delta']

    def advance(self, k, selected):
        if self.reason is not None: raise ValueError('plant advancement after termination')
        self.delay.append(selected)
        arriving = self.delay.popleft()
        self.events['fifo_advances'] += 1
        self.act = actuator.step(self.act, arriving)
        self.events['actuator_updates'] += 1
        env = environment.fixed()
        self.truth = plant.step(self.truth, self.act, env, scenario.disturbance_at(self.spec, k, env), control_ref.DT)
        self.events['plant_steps'] += 1
        if not math.isfinite(self.truth.theta) or not math.isfinite(self.truth.omega):
            self.reason = episode.SimReason.SIM_LOC_NONFINITE
        elif abs(self.truth.theta) > 0.30: self.reason = episode.SimReason.SIM_LOC_ANGLE
        elif k + 1 == self.spec.ticks - 1: self.reason = episode.SimReason.SIM_HORIZON
        return arriving


def execute(spec, *, seed, delay_ticks, peer, bind_port, prefix, terminal_copies=12,
            fail_sensor=None, kill_at=None):
    model = Model(spec, seed, delay_ticks)
    absolute_sleep = sleeper()
    if not 1 <= terminal_copies <= 64: raise ValueError('terminal copies outside [1,64]')
    prefix = Path(prefix)
    stopped = False
    def on_signal(signum, frame):
        nonlocal stopped
        stopped = True
    previous = {sig: signal.signal(sig, on_signal) for sig in (signal.SIGINT, signal.SIGTERM)}
    rows, steps, roundtrips = [], [], []
    error = None; code = 0; origin = 0; receive_open = time.monotonic_ns(); receive_closed = 0
    first_terminal_send = last_terminal_send = 0
    cached_terminal = None; terminal_logged = False; terminal_tick = None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(('127.0.0.1', bind_port)); sock.connect(peer); sock.setblocking(False)
        with open(str(prefix)+'.inputs.tvcrec', 'wb') as inputs:
            inputs.write(wire.HEADER.pack(wire.MAGIC, 1, 0, wire.SCHEMA_HASHES[4], time.monotonic_ns(), time.time_ns()))
            def drain():
                packets = []
                for _ in range(8):
                    try: packets.append(sock.recv(513, socket.MSG_DONTWAIT))
                    except BlockingIOError: break
                received = time.monotonic_ns()
                for data in packets:
                    try:
                        _, _, payload = wire.decode_datagram(data, {5}); value = wire.decode_payload(5, payload)
                    except ValueError: continue
                    if value['status'] & 255 != 3 and (value['status'] >> 16) & 255 == 0 and value['t_sensor_send_ns']:
                        roundtrips.append(received - value['t_sensor_send_ns'])
                return packets

            def offer(tick, terminal=False, prologue=False):
                nonlocal cached_terminal, terminal_logged, first_terminal_send, last_terminal_send, origin
                obs = None
                if not terminal or cached_terminal is None:
                    obs = sensor.observe(tick, model.truth)
                    model.events['sensor_observations'] += 1
                raw, drop = model.loss('up', tick, terminal=terminal, prologue=prologue)
                if terminal: model.term['up_attempts'] += 1
                else: model.up['generated'] += 1
                sent_ns = time.monotonic_ns()
                if prologue: origin = sent_ns
                if not terminal or cached_terminal is None:
                    payload = wire.encode_payload(4, dict(tick=tick, t_send_ns=sent_ns,
                        theta=obs.theta, omega=obs.omega, flags=3 if terminal else 1,
                        cmd_seq=0, sim_reason=int(model.reason) if terminal else 0))
                    frame = wire.encode_frame(4, tick, payload)
                    if terminal: cached_terminal = frame
                else: frame = cached_terminal
                if drop:
                    if terminal: model.term['up_intentionally_lost'] += 1
                    else:
                        model.up['intentionally_lost'] += 1
                        model.up['forced_drop'] += int(not raw)
                    return
                if terminal:
                    if not first_terminal_send: first_terminal_send = sent_ns
                    last_terminal_send = sent_ns
                try:
                    if tick == fail_sensor and (not terminal or model.term['up_attempts'] == 1):
                        raise BlockingIOError(errno.EAGAIN, 'injected sensor send refusal')
                    if sock.send(frame, socket.MSG_DONTWAIT) != len(frame): raise OSError('short UDP send')
                except OSError:
                    if terminal: model.term['up_tx_fail'] += 1
                    else: model.up['sensor_tx_fail'] += 1
                    if prologue: raise
                else:
                    if terminal: model.term['up_transmitted'] += 1
                    else:
                        model.up['transmitted'] += 1
                        model.up['forced_transmit'] += int(raw)
                    if not terminal or not terminal_logged:
                        inputs.write(frame)
                        if terminal: terminal_logged = True

            offer(0, prologue=True)
            rows.append(dict(tick=0, has_sample=1, applied=0, theta_bits=word(model.truth.theta),
                omega_bits=word(model.truth.omega), cmd_applied_bits=word(model.act.applied)))
            for k in range(spec.ticks - 1):
                if k == kill_at: os.kill(os.getpid(), signal.SIGKILL)
                sleep_until(origin + k*PERIOD_NS, lambda: stopped, absolute_sleep)
                selected = model.receive(drain(), k)
                if model.vehicle_seen is not None: break
                arriving = model.advance(k, selected)
                row = dict(tick=k+1, has_sample=1, applied=int(arriving is not None),
                    theta_bits=word(model.truth.theta), omega_bits=word(model.truth.omega),
                    cmd_applied_bits=word(model.act.applied))
                rows.append(row)
                steps.append(dict(row, deadline_ns=origin+k*PERIOD_NS, selected_delta=selected))
                terminal = model.reason is not None
                offer(k+1, terminal=terminal)
                if terminal:
                    terminal_tick = k
                    break
            if terminal_tick is not None:
                for offset in range(1, terminal_copies + GRACE_TICKS):
                    sleep_until(origin + (terminal_tick+offset)*PERIOD_NS, lambda: stopped, absolute_sleep)
                    # Terminal traffic never consults an out-of-horizon scenario tick.
                    model.receive(drain(), terminal_tick)
                    if model.vehicle_seen is not None: break
                    if offset < terminal_copies: offer(terminal_tick+1, terminal=True)
                if model.vehicle_seen is None: code = 3
    except (OSError, ValueError) as exc:
        code = 3 if isinstance(exc, InterruptedError) else 1
        error = str(exc)
    finally:
        receive_closed = time.monotonic_ns(); sock.close()
        for sig, handler in previous.items(): signal.signal(sig, handler)
    if model.reason is None: model.reason = episode.SimReason.SIM_PEER_LOST
    report = dict(mode='freerun', sim_reason=int(model.reason), sim_reason_name=model.reason.name,
        vehicle_reason_seen=model.vehicle_seen, origin_ns=origin, rate_hz=500, period_ns=PERIOD_NS,
        terminal_handshake='answered' if model.vehicle_seen is not None else 'unanswered',
        transmission=model.up, actuator_receipt=model.down, terminal=model.term, events=model.events,
        terminal_send_first_ns=first_terminal_send, terminal_send_last_ns=last_terminal_send,
        receive_open_ns=receive_open, receive_closed_ns=receive_closed, rows=rows, steps=steps,
        rng=dict(up_draws=model.draws[0], down_draws=model.draws[1],
                 up_state=model.streams[0].state, down_state=model.streams[1].state),
        latency_roundtrip_ns=roundtrips, error=error)
    Path(str(prefix)+'.sim-report.json').write_text(json.dumps(report, sort_keys=True, allow_nan=False)+'\n')
    return code

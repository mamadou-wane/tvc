"""Lockstep simulator process. Physical attempts never repeat a model step."""
import argparse
from collections import deque
import errno
import json
import math
import os
import signal
from pathlib import Path
import socket
import struct
import time

from ground import wire
from sim import actuator, control_ref, environment, episode, link, plant, rng, scenario, sensor


def sender_counts():
    return dict.fromkeys(('generated','original_attempts','retry_attempts','not_attempted',
                          'send_attempts','send_pending','tx_fail','transmitted',
                          'first_transmitted','additional_copies','never_transmitted'),0)


def receiver_counts():
    return dict.fromkeys(('received_raw','malformed','received','decode_pending',
                          'logical_received','discarded_duplicate','rejected_received',
                          'classification_pending','modeled_command_loss','forwarded_to_delay',
                          'disposition_pending','test_discarded','discarded_old'),0)


def word(value):
    return f'0x{struct.unpack("<Q",struct.pack("<d",value))[0]:016x}'


def execute(spec, *, seed, delay_ticks, peer, bind_port, prefix,
            fail_sensor=None, drop_actuator=None, kill_at=None):
    up=sender_counts(); down=receiver_counts()
    up['modeled_sample_loss']=0
    up['first_tick']=None; up['last_tick']=None
    names=('link.loss.up','link.loss.down')
    starts=[rng.stream_state(seed,name) for name in names]
    streams=[rng.SplitMix64(start) for start in starts]
    draws=0; truth=spec.initial; act=actuator.initial(); env=environment.fixed()
    delay=deque([None]*delay_ticks)
    rows=[]; replies=[]; last_reply=None; command_seq=0
    pending_reason=None; final_reason=episode.SimReason.SIM_PEER_LOST
    vehicle_seen=None; error=None; code=0
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    inputs=None
    try:
        sock.bind(('127.0.0.1',bind_port)); sock.connect(peer)
        inputs=open(str(prefix)+'.inputs.tvcrec','wb')
        inputs.write(wire.HEADER.pack(wire.MAGIC,1,0,wire.SCHEMA_HASHES[4],0,0))
        for tick in range(spec.ticks):
            if tick==kill_at: os.kill(os.getpid(),signal.SIGKILL)
            raw_up=link.draw_drop(streams[0],spec.loss_up)
            raw_down=link.draw_drop(streams[1],spec.loss_down); draws+=1
            forced_up=scenario.forced_drop_at(spec,tick,direction='up')
            forced_down=scenario.forced_drop_at(spec,tick,direction='down')
            up_drop=raw_up if forced_up is None else forced_up
            down_drop=raw_down if forced_down is None else forced_down
            up['modeled_sample_loss']+=int(up_drop)
            dist=scenario.disturbance_at(spec,tick,env)
            obs=sensor.observe(tick,truth)
            sim_reason=pending_reason
            if sim_reason is None and tick==spec.ticks-1: sim_reason=episode.SimReason.SIM_HORIZON
            flags=0 if up_drop else 1
            opcode=scenario.command_at(spec,tick)
            if opcode is not None:
                command_seq=(command_seq+1)&0xffffffff
                flags|=4 | (int(episode.Opcode[opcode])<<8)
            if sim_reason is not None: flags|=2
            payload=wire.encode_payload(4,dict(tick=tick,t_send_ns=0,
                theta=0.0 if up_drop else obs.theta,omega=0.0 if up_drop else obs.omega,
                flags=flags,cmd_seq=command_seq if opcode else 0,sim_reason=int(sim_reason or 0)))
            frame=wire.encode_frame(4,tick,payload)
            up['generated']+=1; up['not_attempted']+=1; up['never_transmitted']+=1
            if up['first_tick'] is None: up['first_tick']=tick
            up['last_tick']=tick
            logged=False; answer=None
            for attempt in range(26):
                up['send_attempts']+=1; up['send_pending']+=1
                if attempt==0: up['original_attempts']+=1; up['not_attempted']-=1
                else: up['retry_attempts']+=1
                try:
                    if attempt==0 and tick==fail_sensor:
                        raise BlockingIOError(errno.EAGAIN,'injected initial sensor send failure')
                    if sock.send(frame)!=len(frame): raise OSError('short UDP send')
                except OSError:
                    up['tx_fail']+=1
                else:
                    up['transmitted']+=1
                    if logged: up['additional_copies']+=1
                    else:
                        up['first_transmitted']+=1; up['never_transmitted']-=1
                        inputs.write(frame); logged=True
                finally:
                    up['send_pending']-=1
                # This deadline bounds the resend wait, not logical simulation time.
                deadline=time.monotonic()+0.2
                while True:
                    remaining=deadline-time.monotonic()
                    if remaining<=0: break
                    sock.settimeout(remaining)
                    try: data=sock.recv(513)
                    except socket.timeout: break
                    down['received_raw']+=1
                    try:
                        _,_,body=wire.decode_datagram(data,{5})
                        value=wire.decode_payload(5,body)
                    except ValueError:
                        down['malformed']+=1; continue
                    down['received']+=1
                    if down['received_raw']==drop_actuator:
                        down['test_discarded']+=1; down['rejected_received']+=1; continue
                    if value['tick']!=tick:
                        if data==last_reply: down['discarded_duplicate']+=1
                        else: down['rejected_received']+=1; down['discarded_old']+=1
                        continue
                    if value['veh_tick']!=tick or not math.isfinite(value['delta']):
                        down['rejected_received']+=1
                        raise ValueError('invalid actuator identity or command')
                    if value['t_sensor_send_ns']!=0 or value['t_veh_send_ns']!=0:
                        down['rejected_received']+=1
                        raise ValueError('nonzero lockstep actuator timestamp')
                    down['logical_received']+=1; answer=value; last_reply=data
                    break
                if answer is not None: break
            if answer is None: raise TimeoutError(f'no actuator reply for tick {tick} after 25 retries')
            replies.append(answer)
            if down_drop: down['modeled_command_loss']+=1
            else: down['forwarded_to_delay']+=1
            delay.append(None if down_drop else answer['delta']); arriving=delay.popleft()
            act=actuator.step(act,arriving)
            rows.append(dict(tick=tick,has_sample=int(not up_drop and math.isfinite(obs.theta) and math.isfinite(obs.omega)),
                             applied=int(arriving is not None),theta_bits=word(truth.theta),
                             omega_bits=word(truth.omega),cmd_applied_bits=word(act.applied)))
            status=answer['status']; state=status&255; reason=(status>>8)&255
            if state==3: vehicle_seen=reason
            if sim_reason is not None: final_reason=sim_reason; break
            if state==3: final_reason=episode.SimReason.SIM_VEHICLE_TERMINAL; break
            truth=plant.step(truth,act,env,dist,control_ref.DT)
            if not math.isfinite(truth.theta) or not math.isfinite(truth.omega):
                pending_reason=episode.SimReason.SIM_LOC_NONFINITE
            elif abs(truth.theta)>0.30: pending_reason=episode.SimReason.SIM_LOC_ANGLE
    except (OSError,ValueError) as exc:
        code=1; error=str(exc)
    finally:
        sock.close()
        if inputs is not None:
            try: inputs.close()
            except OSError as exc: code=1; error=str(exc)
    report=dict(mode='lockstep',seed=seed,delay_ticks=delay_ticks,ticks_declared=spec.ticks,
        ticks_resolved=spec.ticks,rate_hz=500.0,period_ns=2000000,latency_roundtrip_us=None,
        terminal_handshake='not applicable in lockstep',
        rows=rows,actuator_replies=replies,transmission=up,actuator_receipt=down,
        sim_reason=int(final_reason),sim_reason_name=final_reason.name,
        vehicle_reason_seen=vehicle_seen,
        vehicle_reason_seen_name=episode.Reason(vehicle_seen).name if vehicle_seen is not None else None,
        error=error,
        parameters=dict(J=plant.J,F=plant.F,L=plant.L,FL=plant.FL,k_a=env.k_a,
                        delta_max=actuator.DELTA_MAX,dt_bits=word(control_ref.DT),
                        p_up=spec.loss_up,p_down=spec.loss_down),
        initial_state=dict(theta_bits=word(spec.initial.theta),omega_bits=word(spec.initial.omega)),
        final_state=dict(theta_bits=word(truth.theta),omega_bits=word(truth.omega)),
        rng={'seed':seed,'streams':{name:dict(index=i,start_state=f'0x{start:016x}',
              final_state=f'0x{stream.state:016x}',draws=draws)
              for i,(name,start,stream) in enumerate(zip(names,starts,streams))}})
    Path(str(prefix)+'.sim-report.json').write_text(json.dumps(report,sort_keys=True,allow_nan=False)+'\n')
    return code


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['lockstep','freerun'],default='lockstep')
    parser.add_argument('--scenario',required=True)
    parser.add_argument('--vehicle',required=True)
    parser.add_argument('--bind-port',type=int,default=0)
    parser.add_argument('--seed',type=int,default=1)
    parser.add_argument('--delay-ticks',type=int,choices=(0,1),default=0)
    parser.add_argument('--loss',type=float)
    parser.add_argument('--ticks',type=int)
    parser.add_argument('--terminal-copies',type=int,default=12)
    parser.add_argument('--out',required=True); parser.add_argument('--label',required=True)
    parser.add_argument('--test-fail-sensor',type=int); parser.add_argument('--test-drop-actuator',type=int)
    parser.add_argument('--test-kill-at',type=int)
    args=parser.parse_args(argv)
    host,port=args.vehicle.rsplit(':',1)
    if host!='127.0.0.1' or not 0<int(port)<=65535 or not 0<=args.bind_port<=65535 or not 0<=args.seed<2**64:
        parser.error('invalid loopback peer, port or seed')
    spec=scenario.load(args.scenario)
    if args.loss is not None: spec=spec._replace(loss_up=args.loss,loss_down=args.loss)
    if args.mode == 'freerun':
        from sim.freerun import execute as execute_free, validate_ticks
        if args.ticks is not None:
            spec = spec._replace(ticks=args.ticks)
        try: validate_ticks(spec.ticks)
        except ValueError as exc: parser.error(str(exc))
        return execute_free(spec, seed=args.seed, delay_ticks=args.delay_ticks,
            peer=(host,int(port)), bind_port=args.bind_port, prefix=Path(args.out)/args.label,
            terminal_copies=args.terminal_copies, fail_sensor=args.test_fail_sensor, kill_at=args.test_kill_at)
    if args.ticks is not None: parser.error('ticks override requires freerun')
    return execute(spec,seed=args.seed,delay_ticks=args.delay_ticks,peer=(host,int(port)),
        bind_port=args.bind_port,prefix=Path(args.out)/args.label,
        fail_sensor=args.test_fail_sensor,drop_actuator=args.test_drop_actuator,kill_at=args.test_kill_at)


if __name__=='__main__': raise SystemExit(main())

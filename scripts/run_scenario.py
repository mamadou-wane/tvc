"""Own a lockstep process pair and finalize its evidence after both exit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import selectors
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ground import wire
from sim.scenario import load
from scripts.golden_csv import sim_csv,vehicle_csv
from scripts.reconcile import reconcile


def ready_line(process, mode="lockstep"):
    selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
    data=b'';deadline=time.monotonic()+10
    try:
        while time.monotonic()<deadline:
            if not selector.select(max(0,deadline-time.monotonic())): break
            part=os.read(process.stdout.fileno(),4096)
            if not part: raise RuntimeError('vehicle exited before ready')
            data+=part
            if len(data)>8192: raise RuntimeError('oversized ready line')
            if b'\n' in data:
                line=data.split(b'\n',1)[0].decode()
                if not line.startswith('ready '): raise RuntimeError('invalid ready line')
                fields=dict(word.split('=',1) for word in line.split()[1:])
                if not {'mode','sensor_port','command_port','pid','bin','consts'} <= fields.keys():
                    raise RuntimeError('incomplete ready line')
                if fields.get('mode')!=mode or fields.get('command_port')!='0' or int(fields['pid'])!=process.pid:
                    raise RuntimeError('invalid ready identity')
                if not 0<int(fields['sensor_port'])<=65535: raise RuntimeError('invalid bound sensor port')
                return fields
        raise TimeoutError('ready-line timeout')
    finally: selector.close()


def stop_process(process):
    if process is None: return
    if process.poll() is None:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)
    if process.stdout is not None: process.stdout.close()


def recording(path,kind):
    header,rows,counters=wire.read_typed_recording(path,expected_type=kind)
    if header['start_monotonic_ns']!=0 or header['start_epoch_ns']!=0:
        raise ValueError('nonzero recording clock anchor')
    if any(v for k,v in counters.items() if k!='frames_ok'):
        raise ValueError('recording recovery or sequence error')
    return rows


def run_case(*,binary,scenario_path,out,label,seed,delay_ticks,loss=None,sim_args=(),toolchain=None):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    if any(out.glob(label+'.*')): raise ValueError('output label already exists')
    spec=load(scenario_path)
    if loss is not None: spec=spec._replace(loss_up=loss,loss_down=loss)
    prefix=out/label; vehicle=sim=None;code=0;message=None;ready=None
    vehicle_args=[str(Path(binary).resolve()),'--mode=lockstep','--telemetry','--record=control',
                  '--sensor-port=0','--out='+str(out),'--label='+label,'--alloc-guard=abort']
    if spec.auto_arm: vehicle_args.append('--auto-arm')
    sim_argv=[]
    with open(str(prefix)+'.vehicle.log','wb') as vehicle_log, open(str(prefix)+'.sim.log','wb') as sim_log:
        try:
            vehicle=subprocess.Popen(vehicle_args,stdout=subprocess.PIPE,stderr=vehicle_log)
            ready=ready_line(vehicle)
            if ready['consts']!='0xe77201ca': code=7;raise RuntimeError('controller constants mismatch')
            sim_argv=[sys.executable,'-B','-m','sim.run_sim','--mode=lockstep',
                      '--scenario='+str(Path(scenario_path).resolve()),'--vehicle=127.0.0.1:'+ready['sensor_port'],
                      '--bind-port=0','--seed='+str(seed),'--delay-ticks='+str(delay_ticks),
                      '--out='+str(out),'--label='+label]
            if loss is not None: sim_argv.append('--loss='+str(loss))
            sim_argv.extend(sim_args)
            sim=subprocess.Popen(sim_argv,cwd=ROOT,stdout=sim_log,stderr=subprocess.STDOUT)
            # Worst-case transaction retries plus bounded process shutdown.
            sim.wait(timeout=spec.ticks*5.2+10)
            if sim.returncode:
                code=3;stop_process(vehicle)
            else:
                vehicle.wait(timeout=10)
                if vehicle.returncode: code=2
        except TimeoutError as exc: code=6;message=str(exc)
        except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
            if not code: code=2 if vehicle is not None and vehicle.poll() is not None else 3
            message=str(exc)
        finally:
            stop_process(sim);stop_process(vehicle)
    def read(suffix):
        path=Path(str(prefix)+suffix)
        return json.loads(path.read_text()) if path.exists() else None
    reconciled=dict(eligible=False,errors=['missing owner report'])
    try:
        summary=read('.summary.json');report=read('.sim-report.json')
        if summary is not None and report is not None:
            sensors=recording(Path(str(prefix)+'.inputs.tvcrec'),4)
            controls=recording(Path(str(prefix)+'.control.tvcrec'),6)
            Path(str(prefix)+'.sim.csv').write_text(sim_csv(report['rows']))
            Path(str(prefix)+'.vehicle.csv').write_text(vehicle_csv(controls))
            reconciled=reconcile(summary,report,'lockstep',sensors=sensors,controls=controls)
        if not reconciled['eligible'] and not code: code=8
        Path(str(prefix)+'.reconcile.json').write_text(json.dumps(reconciled,sort_keys=True)+'\n')
        if code==0 and reconciled['eligible']:
            digests={key:hashlib.sha256(Path(str(prefix)+'.'+suffix).read_bytes()).hexdigest()
                     for key,suffix in [('inputs_tvcrec','inputs.tvcrec'),('control_tvcrec','control.tvcrec'),
                                        ('sim_csv','sim.csv'),('vehicle_csv','vehicle.csv')]}
            replay={k:v for k,v in report.items() if k not in ('rows','actuator_replies','error')}
            replay.update(format='tvc-replay-1',scenario=spec.id,
                scenario_sha256=hashlib.sha256(Path(scenario_path).read_bytes()).hexdigest(),
                identifiers=summary['identifiers'],vehicle_argv=vehicle_args,sim_argv=sim_argv,
                vehicle_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
                sim_sha256=hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT/'sim').glob('*.py')))).hexdigest(),
                config_sha256=hashlib.sha256(summary['config'].encode()).hexdigest(),
                toolchain=toolchain if toolchain is not None else dict(image=None,machine=platform.machine(),python=platform.python_version(),lane='development'),
                digests=digests)
            Path(str(prefix)+'.replay.json').write_text(json.dumps(replay,sort_keys=True,allow_nan=False)+'\n')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        code=4 if isinstance(exc,OSError) else 8;message=str(exc)
        reconciled=dict(eligible=False,errors=[message])
        Path(str(prefix)+'.reconcile.json').write_text(json.dumps(reconciled,sort_keys=True)+'\n')
    result=dict(eligible=code==0 and reconciled['eligible'],code=code,message=message,
                vehicle_exit=vehicle.returncode if vehicle else None,sim_exit=sim.returncode if sim else None)
    Path(str(prefix)+'.result.json').write_text(json.dumps(result,sort_keys=True)+'\n')
    return result


def run_free_case(*, binary, scenario_path, out, label, seed, delay_ticks, loss=None,
                  cycles=1000, warmup=0, phase_us=400, skew_max=4, terminal_copies=12,
                  ticks=None, sim_args=(), vehicle_env=None):
    from sim.freerun import validate_ticks
    spec = load(scenario_path)
    validate_ticks(spec.ticks if ticks is None else ticks)
    # Pass-through hooks cannot override the configuration already checked by the runner.
    for arg in sim_args:
        if arg.partition('=')[0] not in ('--test-fail-sensor', '--test-kill-at') or '=' not in arg:
            raise ValueError('freerun --sim-arg accepts fault hooks only; use --ticks for frame count')
    if spec.commands: raise ValueError('live command-bearing freerun scenarios are unsupported')
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=True)
    if any(out.glob(label+'.*')): raise ValueError('output label already exists')
    prefix = out/label; vehicle = sim = None; code = 0; message = None
    argv = [str(Path(binary).resolve()), '--mode=freerun', '--telemetry', '--record=control',
        '--sensor-port=0', '--out='+str(out), '--label='+label, '--alloc-guard=abort',
        '--cycles='+str(cycles), '--warmup='+str(warmup), '--phase-us='+str(phase_us),
        '--skew-max-ticks='+str(skew_max), '--terminal-copies='+str(terminal_copies)]
    if spec.auto_arm: argv.append('--auto-arm')
    with open(str(prefix)+'.vehicle.log','wb') as vlog, open(str(prefix)+'.sim.log','wb') as slog:
        try:
            vehicle = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=vlog, env=vehicle_env)
            ready = ready_line(vehicle, mode='freerun')
            if ready['consts'] != '0xe77201ca':
                code = 7
                raise ValueError('controller constants mismatch')
            args = [sys.executable, '-B', '-m', 'sim.run_sim', '--mode=freerun',
                '--scenario='+str(Path(scenario_path).resolve()), '--seed='+str(seed),
                '--vehicle=127.0.0.1:'+ready['sensor_port'], '--delay-ticks='+str(delay_ticks),
                '--terminal-copies='+str(terminal_copies), '--out='+str(out), '--label='+label]
            if loss is not None: args.append('--loss='+str(loss))
            if ticks is not None: args.append('--ticks='+str(ticks))
            args.extend(sim_args)
            sim = subprocess.Popen(args, cwd=ROOT, stdout=slog, stderr=subprocess.STDOUT)
            limit = max(ticks or spec.ticks, cycles+warmup)*0.002 + 12
            sim.wait(timeout=limit)
            vehicle.wait(timeout=5)
            if sim.returncode: code = 3
            elif vehicle.returncode: code = 2
        except TimeoutError as exc:
            code = 6; message = str(exc)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            if not code: code = 2 if vehicle is not None and vehicle.poll() is not None else 3
            message = str(exc)
        finally:
            stop_process(sim); stop_process(vehicle)
    measurement_valid = False
    try:
        report_path = Path(str(prefix)+'.sim-report.json')
        summary_path = Path(str(prefix)+'.summary.json')
        if not report_path.exists() or not summary_path.exists():
            raise ValueError('missing simulator or vehicle report')
        if report_path.exists() and summary_path.exists():
            report = json.loads(report_path.read_text()); summary = json.loads(summary_path.read_text())
            _, sensors, input_counters = wire.read_typed_recording(Path(str(prefix)+'.inputs.tvcrec'), expected_type=4)
            if any(v for k,v in input_counters.items() if k not in ('frames_ok','lost')):
                raise ValueError('incomplete input recording')
            _, controls, counters = wire.read_typed_recording(Path(str(prefix)+'.control.tvcrec'), expected_type=6)
            if any(v for k,v in counters.items() if k!='frames_ok') or summary['telemetry']['dropped']:
                raise ValueError('incomplete control recording')
            if len(controls) != summary['total_cycles'] or len(controls) != summary['telemetry']['records']:
                raise ValueError('control recording count mismatch')
            Path(str(prefix)+'.vehicle.csv').write_text(vehicle_csv(controls))
            Path(str(prefix)+'.sim.csv').write_text(sim_csv(report['rows']))
            reconciled = reconcile(summary,report,'freerun',sensors=sensors,controls=controls)
            measurement_valid = reconciled.get('measurement',{}).get('valid',False)
            Path(str(prefix)+'.reconcile.json').write_text(json.dumps(reconciled,sort_keys=True)+'\n')
            Path(str(prefix)+'.replay.json').write_text(json.dumps(report,sort_keys=True)+'\n')
            if not reconciled['eligible'] and summary['episode']['vehicle_reason'] not in (5,6,8): code = 8
            if reconciled.get('terminal',{}).get('required_legs_complete') is not True and not code: code = 3
            if report['vehicle_reason_seen'] is None and not code: code = 3
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if not code: code = 4
        message = str(exc) if message is None else message + '; ' + str(exc)
    result = dict(code=code, functional_success=code==0, evidence_eligible=False,
        measurement_valid=measurement_valid,
        validation='functional measurement only; no timing qualification', message=message,
        vehicle_exit=vehicle.returncode if vehicle else None, sim_exit=sim.returncode if sim else None)
    Path(str(prefix)+'.result.json').write_text(json.dumps(result,sort_keys=True)+'\n')
    return result


class Arguments(argparse.ArgumentParser):
    def error(self,message):
        self.print_usage(sys.stderr)
        self.exit(1,f'usage: {message}\n')


def main(argv=None):
    parser=Arguments(description=__doc__)
    parser.add_argument('--mode',choices=['lockstep','freerun'],default='lockstep')
    parser.add_argument('--binary',default=str(ROOT/'build/tvc_harness'))
    parser.add_argument('--scenario',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--label');parser.add_argument('--seed',type=int,default=1)
    parser.add_argument('--delay-ticks',type=int,choices=(0,1),default=0)
    parser.add_argument('--loss',type=float);parser.add_argument('--sim-arg',action='append',default=[])
    parser.add_argument('--cycles',type=int)
    parser.add_argument('--warmup',type=int)
    parser.add_argument('--phase-us',type=int)
    parser.add_argument('--skew-max-ticks',type=int)
    parser.add_argument('--terminal-copies',type=int)
    parser.add_argument('--ticks',type=int)
    args=parser.parse_args(argv)
    path=Path(args.scenario)
    if not path.suffix: path=ROOT/'sim/scenarios'/(args.scenario+'.json')
    label=args.label or path.stem
    if not label or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in label):
        parser.error('invalid label')
    try:
        options = dict(binary=args.binary,scenario_path=path,out=args.out,label=label,
                       seed=args.seed,delay_ticks=args.delay_ticks,loss=args.loss,sim_args=args.sim_arg)
        extra = dict(cycles=args.cycles,warmup=args.warmup,phase_us=args.phase_us,
                     skew_max=args.skew_max_ticks,terminal_copies=args.terminal_copies,ticks=args.ticks)
        if args.mode == 'freerun':
            result = run_free_case(**options, **{k:v for k,v in extra.items() if v is not None})
        else:
            if any(v is not None for v in extra.values()): parser.error('free-run options require freerun')
            result = run_case(**options)
    except OSError as exc:
        print(f'output: {exc}',file=sys.stderr)
        return 4
    except ValueError as exc: parser.error(str(exc))
    print(json.dumps(result,sort_keys=True))
    return result['code']


if __name__=='__main__': raise SystemExit(main())

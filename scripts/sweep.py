#!/usr/bin/env python3
"""
sweep.py: run the determinism campaign.

Each level adds exactly one mitigation to the one before it, so the difference
between two adjacent runs is attributable to a single change. That property is
the entire value of the exercise; resist the urge to batch them.

    ./scripts/sweep.py --cpu 3
    ./scripts/sweep.py --cpu 3 --cycles 600000     # 20 min per level at 500 Hz
    ./scripts/sweep.py --only L0 L1                # re-run two levels

Levels above L2 need privileges. Without them the harness exits nonzero, the
sweep stops at that level, and any summary whose requested config was not
applied is excluded from the table automatically.
"""

import argparse
import json
import math
import pathlib
import re
import shutil
import subprocess
import sys
import time
import signal

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# (label, description, extra flags, peer). Cumulative by construction.
LEVELS = [
    ("L0", "baseline: sleep_for, allocating telemetry path", [], None),
    ("L1", "absolute deadlines (clock_nanosleep TIMER_ABSTIME)", ["--abs-deadline"], None),
    ("L2", "+ mlockall and pre-faulted stack and heap", ["--mlock"], None),
    ("L3", "+ SCHED_FIFO priority 80", ["--fifo=80"], None),
    ("L4", "+ pinned to an isolated core", ["--cpu={cpu}"], None),
    ("L5", "+ allocation-free hot path", ["--no-naive-log", "--alloc-guard=abort"], None),
    ("L6", "+ telemetry ring + drain thread", ["--telemetry"], None),
    ("L7", "+ control record (128 B)", ["--telemetry", "--record=control"], None),
    ("L8", "+ sensor and actuator sockets, PID, episode machine",
     ["--mode=freerun", "--auto-arm", "--telemetry", "--record=control"], "S1-hold"),
]


def plan_levels(levels, cpu):
    """Cumulative prefix of levels that can run. Once any level is skipped,
    everything after it is invalid (it would differ from its predecessor by
    more than one change), so the campaign stops there."""
    runnable = []
    for label, desc, add, peer in levels:
        if any(f == '--mode=lockstep' for f in add):
            raise ValueError('lockstep is not a sweep workload')
        if any("{cpu}" in f for f in add) and cpu is None:
            return runnable, f"{label} needs --cpu; campaign stops here"
        runnable.append((label, desc, add, peer))
    return runnable, None


MODES = ('harness', 'lockstep', 'freerun')


def summary_mode(summary, legacy_ok=False):
    if not isinstance(summary, dict):
        return None, 'summary is not an object'
    if 'mode' not in summary:
        return ('harness', None) if legacy_ok else (None, 'summary has no mode field')
    mode = summary['mode']
    return (mode, None) if mode in MODES else (None, f'unknown mode {mode!r}')


def level_mode(flags):
    return 'freerun' if '--mode=freerun' in flags else 'harness'


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key ' + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError('nonfinite JSON value ' + value)
    return json.loads(pathlib.Path(path).read_text(), object_pairs_hook=pairs,
                      parse_constant=constant)


def config_fields(summary):
    text = summary.get('config')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('missing config')
    fields = {}
    for token in text.split():
        key, _, value = token.partition(':')
        if key in fields:
            raise ValueError('duplicate config ' + key)
        fields[key] = value
    for key in ('cpu', 'fifo'):
        if key in fields and not re.fullmatch(r'0|[1-9][0-9]*', fields[key]):
            raise ValueError('invalid config ' + key)
    return fields


def ground_problem(summary):
    ground = summary.get('ground')
    applied = summary.get('applied', {}).get('ground')
    requested = ground.get('requested') if isinstance(ground, dict) else None
    if type(requested) is not bool or type(applied) is not bool or requested != applied:
        return 'ground requested/applied mismatch or missing status'
    return None


def row_problem(summary, legacy_ok=False):
    """None if the row is good enough for the table, else a short reason it
    was excluded: either the requested mitigation was not applied, or the
    run is short or interrupted (or predates the cycles_requested field)."""
    mode, problem = summary_mode(summary, legacy_ok)
    if problem:
        return problem
    if mode == 'lockstep':
        return 'lockstep has no timing evidence'
    applied = summary.get("applied")
    if not isinstance(applied, dict):
        return "config was not applied"
    if mode == 'freerun':
        try:
            fields = config_fields(summary)
        except ValueError as error:
            return str(error)
        for key in ('mlock', 'fifo', 'cpu'):
            if type(applied.get(key)) is not bool or applied[key] != (key in fields):
                return 'config was not applied: ' + key
        if applied.get('telemetry') is not True or applied.get('link') is not True:
            return 'config was not applied: telemetry/link'
        problem = ground_problem(summary)
        if problem:
            return problem
    elif legacy_ok:
        if not all(applied.values()):
            return "config was not applied"
    elif (any(applied.get(k) is not True for k in ('mlock','fifo','cpu'))
          or ('telemetry' in applied and applied['telemetry'] is not True)):
        return "config was not applied"
    if (type(summary.get('cycles')) is not int or type(summary.get('cycles_requested')) is not int
            or summary['cycles_requested'] <= 0 or summary['cycles'] != summary['cycles_requested']):
        return "incomplete run or pre-integrity summary format"
    return None


def row_ok(summary):
    """A row enters the table only if every requested mitigation was applied
    and the run completed its full requested cycle count (an interrupted or
    short run cannot enter the table)."""
    return row_problem(summary) is None


def aggregate_row(label, good):
    """One table row from the good repeats of a level: percentiles take
    the median across repeats, counters sum, max is the worst repeat."""
    import statistics
    row = dict(good[0])
    row["label"] = label
    row["jitter_us"] = dict(good[0]["jitter_us"])
    percentile_keys = ["p50", "p99", "p99.9", "p99.9_naive", "p99.99"]
    for key in percentile_keys:
        row["jitter_us"][key] = statistics.median(
            summary["jitter_us"][key] for summary in good)
    row["jitter_us"]["max"] = max(
        summary["jitter_us"]["max"] for summary in good)
    row["dropped_samples"] = sum(summary["dropped_samples"] for summary in good)
    row["missed_deadlines"] = sum(summary["missed_deadlines"] for summary in good)
    p999s = [summary["jitter_us"]["p99.9"] for summary in good]
    p9999s = [summary["jitter_us"]["p99.99"] for summary in good]
    row["p999_spread"] = (min(p999s), max(p999s)) if len(good) > 1 else None
    row["p9999_spread"] = (min(p9999s), max(p9999s)) if len(good) > 1 else None
    return row


def binary_is_stale(bin_path, source_paths):
    """True when the binary predates any source it was built from."""
    import os
    try:
        bin_mtime = os.path.getmtime(bin_path)
    except OSError:
        return False
    newest = 0.0
    for p in source_paths:
        try:
            newest = max(newest, os.path.getmtime(p))
        except OSError:
            continue
    return newest > bin_mtime


def parse_cpu_list(text):
    """sysfs CPU-list syntax ('6-7', '0,2-5,8', '') to a set of ints;
    blank input is the empty set."""
    cpus = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = (int(value) for value in part.split("-", 1))
            cpus.update(range(lo, hi + 1))
        else:
            cpus.add(int(part))
    return cpus


def read_online_isolated(sysfs="/sys/devices/system/cpu"):
    """(online, isolated) CPU sets. Missing or unreadable files fall
    back to range(os.cpu_count()) for online and the empty set for
    isolated, so containers and non-Linux sandboxes keep working."""
    import os
    try:
        with open(os.path.join(sysfs, "online")) as f:
            online = parse_cpu_list(f.read())
    except OSError:
        online = set(range(os.cpu_count() or 1))
    try:
        with open(os.path.join(sysfs, "isolated")) as f:
            isolated = parse_cpu_list(f.read())
    except OSError:
        isolated = set()
    return online, isolated


def affinity_problem(affinity, online, isolated):
    """None when the inherited mask is unrestricted, else a short
    reason string, in the style of row_problem."""
    missing = online - affinity
    if not missing:
        return None
    reason = (f"inherited CPU affinity {sorted(affinity)} is missing online CPUs "
              f"{sorted(missing)} (launched under taskset or in a cpuset?)")
    if not (affinity - isolated):
        reason += ("; every allowed CPU is isolated, so unpinned levels and the "
                   "telemetry drain thread would run on the measurement core")
    return reason


def plan_runs(args):
    if (type(args.cycles) is not int or args.cycles <= 0 or args.warmup < 0
            or args.repeat <= 0 or not math.isfinite(args.rate) or args.rate <= 0):
        raise ValueError('invalid cycles, warmup, repeats or rate')
    if args.cpu is not None and args.cpu < 0:
        raise ValueError('invalid CPU')
    if args.only and (len(set(args.only)) != len(args.only) or
                      not set(args.only) <= {row[0] for row in LEVELS}):
        raise ValueError('unknown or duplicate level')
    try:
        phases = [int(value) for value in args.phase_us.split(',')]
    except ValueError as error:
        raise ValueError('invalid phase') from error
    if any(p <= 0 or p >= 2000 for p in phases):
        raise ValueError('phase outside scheduling range')
    grid = len(phases) > 1
    if grid and (phases != [200,400,800] or args.only != ['L8'] or args.repeat != 3 or not args.interleave):
        raise ValueError('phase grid requires 200,400,800, only L8, repeat 3 and interleave')
    runnable, stopped = plan_levels(LEVELS, args.cpu)
    plans, flags = [], []
    for level, desc, add, peer in runnable:
        flags = flags + [f.format(cpu=args.cpu) for f in add]
        if args.only and level not in args.only:
            continue
        if level == 'L8' and (args.rate != 500 or args.cycles < 1000
                              or args.cycles + args.warmup > (2**63-1)//2000000 - 64):
            raise ValueError('L8 requires rate 500 and cycles >= 1000 within scheduling range')
        for phase in phases if level == 'L8' else [None]:
            plans.append(dict(level=level, description=desc, flags=list(flags), phase_us=phase,
                              cycles=args.cycles, warmup=args.warmup, rate=args.rate))
    order = ([(r,p) for r in range(1,args.repeat+1) for p in plans] if args.interleave else
             [(r,p) for p in plans for r in range(1,args.repeat+1)])
    runs = []
    for repeat, plan in order:
        label = plan['level'] + (f'.phase{plan["phase_us"]}' if grid else '')
        if args.repeat > 1:
            label += f'.r{repeat}'
        runs.append(dict(plan, flags=list(plan['flags']), repeat=repeat, label=label))
    return runs, stopped


def argv_options(argv, start):
    if not isinstance(argv, list) or len(argv) <= start or any(not isinstance(a, str) or not a for a in argv):
        raise ValueError('missing or invalid resolved argv')
    options = {}
    for arg in argv[start:]:
        key, separator, value = arg.partition('=')
        if not key.startswith('--') or (separator and not value):
            raise ValueError('invalid resolved argument')
        value = value if separator else None
        if key in options and options[key] != value:
            raise ValueError('conflicting resolved argument ' + key)
        options[key] = value
    return options


def l8_configuration(row, summary, replay):
    if not isinstance(replay, dict):
        raise ValueError('invalid replay metadata')
    for key in ('vehicle_argv', 'sim_argv'):
        if key not in replay or key not in row or replay[key] != row[key]:
            raise ValueError('missing or mismatched ' + key)
    vehicle = argv_options(row['vehicle_argv'], 1)
    peer = argv_options(row['sim_argv'], 4)
    if row['sim_argv'][1:4] != ['-B', '-m', 'sim.run_sim']:
        raise ValueError('unexpected simulator invocation')
    for key in ('cycles', 'warmup', 'phase_us', 'repeat'):
        if type(row.get(key)) is not int:
            raise ValueError('missing or invalid run ' + key)
    if (row['cycles'] < 1000 or row['warmup'] < 0 or row['repeat'] < 1
            or not 0 < row['phase_us'] < 2000 or type(row.get('rate')) not in (int,float) or row['rate'] != 500):
        raise ValueError('invalid L8 run configuration')
    if (summary.get('label') != row['label'] or summary.get('cycles_requested') != row['cycles']
            or summary.get('warmup') != row['warmup'] or summary.get('phase_us') != row['phase_us']
            or summary.get('period_us') != 2000):
        raise ValueError('run configuration does not match summary')
    fields = config_fields(summary)
    expected = {'--mode':'freerun', '--auto-arm':None, '--abs-deadline':None,
                '--telemetry':None, '--record':'control', '--alloc-guard':'abort',
                '--cycles':str(row['cycles']), '--warmup':str(row['warmup']),
                '--phase-us':str(row['phase_us']), '--sensor-port':'0',
                '--skew-max-ticks':'4', '--terminal-copies':'12', '--label':row['label']}
    for key in ('mlock','cpu','fifo'):
        if key in fields:
            expected['--'+key] = fields[key] if key != 'mlock' else None
        elif '--'+key in vehicle:
            raise ValueError('argv mitigation absent from summary')
    allowed = set(expected) | {'--rate','--out','--no-naive-log'}
    if set(vehicle) - allowed or any(k not in vehicle or vehicle[k] != v for k,v in expected.items()):
        raise ValueError('unexpected L8 vehicle argv')
    if vehicle.get('--rate') not in ('500','500.0') or not vehicle.get('--out'):
        raise ValueError('missing L8 rate/output argv')
    ticks = row['cycles'] + row['warmup'] + 33
    expected_peer = {'--mode':'freerun', '--seed':'1', '--loss':'0.0', '--delay-ticks':'0',
                     '--ticks':str(ticks), '--bind-port':'0', '--terminal-copies':'12',
                     '--label':row['label'], '--out':vehicle['--out']}
    if set(peer) != set(expected_peer) | {'--scenario','--vehicle'} or any(peer.get(k) != v for k,v in expected_peer.items()):
        raise ValueError('unexpected L8 peer argv')
    endpoint = re.fullmatch(r'127\.0\.0\.1:([1-9][0-9]*)', peer['--vehicle'] or '')
    if not endpoint or int(endpoint[1]) > 65535 or pathlib.Path(peer['--scenario'] or '').name != 'S1-hold.json':
        raise ValueError('invalid resolved peer endpoint/scenario')
    ready = row.get('ready')
    if (not isinstance(ready, dict) or ready.get('mode') != 'freerun' or ready.get('command_port') != '0'
            or ready.get('consts') != '0xe77201ca' or ready.get('sensor_port') != endpoint[1]):
        raise ValueError('peer endpoint does not match bound ready state')
    expected_replay = dict(seed=1, delay_ticks=0, ticks=ticks, ticks_declared=10000,
                           ticks_resolved=ticks, scenario='S1-hold', rate_hz=500, period_ns=2000000,
                           loss=dict(p_up=0.0,p_down=0.0))
    if any(k not in replay or type(replay[k]) is not type(v) or replay[k] != v for k,v in expected_replay.items()):
        raise ValueError('resolved peer configuration does not match replay')


def harness_configuration(row, summary):
    options = argv_options(row.get('vehicle_argv'), 1)
    fields = config_fields(summary)
    for key in ('cycles','warmup','repeat'):
        if type(row.get(key)) is not int or row[key] < (0 if key == 'warmup' else 1):
            raise ValueError('invalid harness run ' + key)
    if type(row.get('rate')) not in (int,float) or not math.isfinite(row['rate']) or row['rate'] <= 0:
        raise ValueError('invalid harness rate')
    expected = {'--label':row['label'], '--cycles':str(row['cycles']), '--warmup':str(row['warmup'])}
    number = int(row['level'][1:])
    for _, _, flags, _ in LEVELS[:number+1]:
        for flag in flags:
            key, separator, value = flag.format(cpu=fields.get('cpu')).partition('=')
            expected[key] = value if separator else None
    if (set(options) != set(expected) | {'--rate','--out'} or not options.get('--out')
            or any(key not in options or options[key] != value for key,value in expected.items())
            or options.get('--rate') not in (str(row['rate']),str(float(row['rate'])))
            or summary.get('cycles_requested') != row['cycles'] or summary.get('label') != row['label']):
        raise ValueError('harness invocation does not match experiment configuration')


def roster_row(prefix):
    prefix = pathlib.Path(prefix)
    roster = read_json(prefix.parent / 'sweep.json')
    if not isinstance(roster, dict) or roster.get('format') != 'tvc-sweep-1' or roster.get('complete') is not True:
        raise ValueError('incomplete sweep roster')
    runs = roster.get('runs')
    if not isinstance(runs, list) or not runs:
        raise ValueError('empty sweep roster')
    seen, selected = set(), None
    for row in runs:
        if not isinstance(row, dict) or row.get('complete') is not True:
            raise ValueError('incomplete roster row')
        label = row.get('label')
        if not isinstance(label, str) or not re.fullmatch(r'L[0-8](?:\.phase(?:200|400|800))?(?:\.r[1-9][0-9]*)?', label) or label in seen:
            raise ValueError('invalid or duplicate roster label')
        if row.get('level') != label.split('.')[0]:
            raise ValueError('roster level/label mismatch')
        repeat = int(label.rsplit('.r',1)[1]) if '.r' in label else 1
        if type(row.get('repeat')) is not int or row['repeat'] != repeat:
            raise ValueError('roster repeat/label mismatch')
        if '.phase' in label and row.get('phase_us') != int(label.split('.phase')[1].split('.')[0]):
            raise ValueError('roster phase/label mismatch')
        seen.add(label)
        base = prefix.parent / label
        if not pathlib.Path(str(base)+'.summary.json').is_file():
            raise ValueError('missing roster summary: ' + label)
        if row != read_json(str(base)+'.result.json'):
            raise ValueError('roster does not match process result: ' + label)
        if type(row.get('vehicle_exit')) is not int or row['vehicle_exit'] != 0:
            raise ValueError('failed vehicle in roster')
        if row.get('level') == 'L8':
            if type(row.get('sim_exit')) is not int or row['sim_exit'] != 0:
                raise ValueError('failed peer in roster')
            replay = read_json(str(base)+'.replay.json')
            l8_configuration(row, read_json(str(base)+'.summary.json'), replay)
        else:
            harness_configuration(row, read_json(str(base)+'.summary.json'))
        if label == prefix.name:
            selected = row
    if selected is None:
        raise ValueError('summary absent from sweep roster')
    return selected


def audit_freerun(prefix, *, write=False):
    from ground import wire
    from scripts.reconcile import reconcile
    prefix = pathlib.Path(prefix)
    path = lambda suffix: pathlib.Path(str(prefix) + suffix)
    summary = read_json(path('.summary.json'))
    replay = read_json(path('.replay.json'))
    report = read_json(path('.sim-report.json'))
    if not isinstance(summary, dict) or not isinstance(replay, dict) or not isinstance(report, dict) or any(replay.get(k) != v for k,v in report.items()):
        raise ValueError('replay does not match simulator report')
    if not write:
        result = read_json(path('.result.json'))
        if (not isinstance(result, dict) or result.get('complete') is not True or type(result.get('vehicle_exit')) is not int
                or result['vehicle_exit'] != 0 or type(result.get('sim_exit')) is not int or result['sim_exit'] != 0):
            raise ValueError('incomplete process result')
    _, sensors, counts = wire.read_typed_recording(path('.inputs.tvcrec'), expected_type=4)
    if any(v for k,v in counts.items() if k not in ('frames_ok','lost')):
        raise ValueError('invalid sensor recording')
    _, controls, counts = wire.read_typed_recording(path('.control.tvcrec'), expected_type=6)
    if any(v for k,v in counts.items() if k != 'frames_ok'):
        raise ValueError('invalid control recording')
    observed = reconcile(summary, replay, 'freerun', sensors=sensors, controls=controls)
    if write:
        path('.reconcile.json').write_text(json.dumps(observed, sort_keys=True, allow_nan=False)+'\n')
    elif observed != read_json(path('.reconcile.json')):
        raise ValueError('stale or mismatched reconciliation')
    if observed.get('eligible') is not True or observed.get('terminal_agreement') is not True or observed.get('terminal',{}).get('required_legs_complete') is not True:
        raise ValueError('reconciliation failed: ' + str(observed.get('errors')))
    return summary


def run_row(plan, binary, outdir):
    from scripts.run_scenario import ready_line, stop_process
    from sim.scenario import load
    outdir = pathlib.Path(outdir)
    prefix = outdir / plan['label']
    plan.update(complete=False, error=None, vehicle_exit=None, sim_exit=None, sim_argv=[])
    if any(outdir.glob(plan['label'] + '.*')):
        plan['error'] = 'output label already exists'
        return 1
    vehicle = peer = None
    argv = [str(pathlib.Path(binary).resolve()), '--label='+plan['label'], '--out='+str(outdir),
            '--rate='+str(plan['rate']), '--cycles='+str(plan['cycles']),
            '--warmup='+str(plan['warmup']), *plan['flags']]
    if plan['level'] == 'L8':
        argv += ['--sensor-port=0', '--phase-us='+str(plan['phase_us']),
                 '--skew-max-ticks=4', '--terminal-copies=12']
    plan['vehicle_argv'] = argv
    try:
        with open(str(prefix)+'.vehicle.log', 'xb') as vlog, open(str(prefix)+'.peer.log', 'xb') as plog:
            vehicle = subprocess.Popen(argv, stdout=subprocess.PIPE if plan['level']=='L8' else vlog, stderr=vlog)
            if plan['level'] == 'L8':
                ready = ready_line(vehicle, mode='freerun')
                plan['ready'] = ready
                if ready['consts'] != '0xe77201ca':
                    raise ValueError('controller constants mismatch')
                ticks = plan['cycles'] + plan['warmup'] + 33
                scenario = ROOT / 'sim/scenarios/S1-hold.json'
                sim_argv = [sys.executable, '-B', '-m', 'sim.run_sim', '--mode=freerun',
                    '--scenario='+str(scenario), '--seed=1', '--loss=0.0', '--delay-ticks=0',
                    '--ticks='+str(ticks), '--vehicle=127.0.0.1:'+ready['sensor_port'],
                    '--bind-port=0', '--terminal-copies=12', '--out='+str(outdir), '--label='+plan['label']]
                plan['sim_argv'] = sim_argv
                peer = subprocess.Popen(sim_argv, cwd=ROOT, stdout=plog, stderr=subprocess.STDOUT)
            # Only the L8 peer lifecycle is bounded; harness levels keep their historical untimed run.
            deadline = time.monotonic() + (plan['cycles']+plan['warmup']+33)/plan['rate'] + 12 if peer else None
            while True:
                v = vehicle.poll()
                p = peer.poll() if peer else 0
                if (v is not None and v != 0) or (p is not None and p != 0):
                    raise ValueError(f'process failure: vehicle={v} peer={p}')
                if v is not None and p is not None:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError('process deadline expired')
                time.sleep(0.01)
        if peer:
            report = read_json(str(prefix)+'.sim-report.json')
            replay = dict(report, vehicle_argv=argv, sim_argv=plan['sim_argv'],
                          ticks_declared=load(scenario).ticks, ticks_resolved=ticks,
                          loss=dict(p_up=0.0,p_down=0.0), scenario='S1-hold')
            pathlib.Path(str(prefix)+'.replay.json').write_text(json.dumps(replay,sort_keys=True,allow_nan=False)+'\n')
            summary = audit_freerun(prefix, write=True)
        else:
            summary = read_json(str(prefix)+'.summary.json')
        problem = row_problem(summary)
        expected = 'freerun' if peer else 'harness'
        if summary.get('mode') != expected:
            problem = f'mode {summary.get("mode")} does not match level {plan["level"]}'
        if problem:
            raise ValueError(problem)
        plan['complete'] = True
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        plan['error'] = str(error) or 'interrupted'
    finally:
        for process in (peer, vehicle):
            try:
                stop_process(process)
            except (OSError, subprocess.TimeoutExpired) as error:
                plan['error'] = 'cleanup: ' + str(error)
                plan['complete'] = False
        plan['vehicle_exit'] = vehicle.returncode if vehicle else None
        plan['sim_exit'] = peer.returncode if peer else None
    try:
        pathlib.Path(str(prefix)+'.result.json').write_text(json.dumps(plan,sort_keys=True,allow_nan=False)+'\n')
    except (OSError, ValueError) as error:
        plan['complete'] = False
        plan['error'] = 'result write failed: ' + str(error)
    return 0 if plan['complete'] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default="build/tvc_harness")
    ap.add_argument("--out", default="results")
    ap.add_argument("--cpu", type=int, default=None,
                    help="isolated core for L4+; without it the campaign stops after L3")
    ap.add_argument("--rate", type=float, default=500.0)
    ap.add_argument("--cycles", type=int, default=300_000)
    ap.add_argument("--warmup", type=int, default=5_000)
    ap.add_argument("--only", nargs="*", metavar="LABEL",
                    help="run just these levels")
    ap.add_argument("--repeat", type=int, default=1,
                    help="runs per level; table reports median and spread")
    ap.add_argument("--allow-stale", action="store_true",
                    help="run even if the binary predates its sources")
    ap.add_argument("--allow-restricted-affinity", action="store_true",
                    help="run even if the inherited CPU mask is restricted "
                         "(taskset, cpuset)")
    ap.add_argument("--interleave", action="store_true")
    ap.add_argument("--phase-us", default="400")
    args = ap.parse_args(argv)
    try:
        plans, stopped = plan_runs(args)
        if not plans:
            raise ValueError('no runnable selected levels')
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    binary = pathlib.Path(args.bin)
    if not binary.exists():
        print(f"no binary at {binary}, build first:", file=sys.stderr)
        print("  cmake -S . -B build && cmake --build build -j", file=sys.stderr)
        return 1

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    sources = sorted(
        list(repo_root.glob("src/*.cpp"))
        + list(repo_root.glob("src/*.hpp"))
        + [repo_root / "CMakeLists.txt"]
    )
    if binary_is_stale(binary, sources):
        if args.allow_stale:
            print(f"warning: {binary} is older than the sources; running anyway "
                  "(--allow-stale)", file=sys.stderr)
        else:
            print("binary is older than the sources; rebuild first: "
                  "cmake --build build -j", file=sys.stderr)
            return 1

    import os
    if hasattr(os, "sched_getaffinity"):
        affinity = set(os.sched_getaffinity(0))
        online, isolated = read_online_isolated()
        problem = affinity_problem(affinity, online, isolated)
        if problem:
            if args.allow_restricted_affinity:
                print(f"warning: {problem}; running anyway "
                      "(--allow-restricted-affinity)", file=sys.stderr)
            else:
                print(problem, file=sys.stderr)
                print("re-launch with a full CPU mask or pass "
                      "--allow-restricted-affinity", file=sys.stderr)
                return 1
        if args.cpu is not None and isolated and args.cpu not in isolated:
            print(f"note: --cpu {args.cpu} is not in the isolated set "
                  f"{sorted(isolated)}", file=sys.stderr)

    outdir = pathlib.Path(args.out).resolve()
    rows, excluded = [], []
    roster = dict(format='tvc-sweep-1', complete=False, runs=plans)
    def interrupted(signum, frame):
        raise KeyboardInterrupt('signal ' + str(signum))
    handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:
        outdir.mkdir(parents=True, exist_ok=True)
        roster_path = outdir / 'sweep.json'
        if roster_path.exists() or any(any(outdir.glob(p['label']+'.*')) for p in plans):
            raise ValueError('output roster or label already exists')
        if stopped:
            print(stopped, file=sys.stderr)
        def save():
            roster_path.write_text(json.dumps(roster,sort_keys=True,allow_nan=False)+'\n')
        save()
        for plan in plans:
            rc = run_row(plan, binary, outdir)
            save()
            if rc:
                print(f"{plan['label']}: {plan['error']}", file=sys.stderr)
                return rc
        groups = {}
        for plan in plans:
            label = plan['label'].split('.r')[0]
            groups.setdefault(label,[]).append(read_json(outdir/(plan['label']+'.summary.json')))
        rows = [aggregate_row(label,values) for label,values in groups.items()]
        roster['complete'] = True
        save()
    except (OSError, ValueError, KeyError, TypeError, KeyboardInterrupt) as error:
        print('sweep: ' + str(error), file=sys.stderr)
        return 1
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)

    if rows:
        w = shutil.get_terminal_size((100, 20)).columns
        print("\n" + "=" * min(w, 96))
        print("CAMPAIGN SUMMARY: wakeup jitter, microseconds")
        print("=" * min(w, 96))
        print(f"{'':4} {'p50':>9} {'p99':>9} {'p99.9':>16} {'p99.9 nv':>10} "
              f"{'max':>10} {'missed':>7} {'drop':>6}   config")
        base = None
        for r in rows:
            j = r["jitter_us"]
            spread = r.get("p999_spread")
            sp = f" ({spread[0]:.0f}-{spread[1]:.0f})" if spread else ""
            p999_cell = f"{j['p99.9']:.1f}{sp}"
            print(f"{r['label']:4} {j['p50']:9.1f} {j['p99']:9.1f} {p999_cell:>16} "
                  f"{j['p99.9_naive']:10.1f} {j['max']:10.1f} "
                  f"{r['missed_deadlines']:7d} {r['dropped_samples']:6d}   {r['config']}")
            if base is None:
                base = j["p99.9"]
        if base and len(rows) > 1 and rows[-1]["jitter_us"]["p99.9"] > 0:
            factor = base / rows[-1]["jitter_us"]["p99.9"]
            print(f"\np99.9 improved {factor:.1f}x from {rows[0]['label']} "
                  f"to {rows[-1]['label']}.")
        spreads = [(r["label"], r["jitter_us"]["p99.99"], r["p9999_spread"])
                   for r in rows if r.get("p9999_spread")]
        if spreads:
            print("\np99.99 median (min-max) across repeats:")
            for label, med, (lo, hi) in spreads:
                print(f"  {label:4} {med:10.1f} ({lo:.1f}-{hi:.1f})")
        print(f"\nPlot it:  ./scripts/plot_jitter.py --results {outdir}")
    return 1 if excluded else 0


if __name__ == "__main__":
    sys.exit(main())

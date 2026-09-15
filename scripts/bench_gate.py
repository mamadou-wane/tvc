#!/usr/bin/env python3
"""
bench_gate.py: the jitter regression gate.

Runs only on the measurement machine. Compares a fresh campaign directory
against the committed baselines and fails when the gated level's p99.9
median regresses beyond tolerance. Hosted CI never produces or judges a
timing number; that boundary is deliberate (see docs/results.md).

    python3 scripts/bench_gate.py --results results/2026-09-01-campaign
"""

import argparse
import pathlib
import math
import re
import statistics
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sweep  # row_problem gates rows here exactly as in the campaign table


def legacy_baseline(path):
    root = pathlib.Path(__file__).resolve().parents[1]
    try:
        relative = pathlib.Path(path).resolve().relative_to(root)
    except ValueError:
        return False
    if relative.parts[0] != 'baselines':
        return False
    # The container user may differ from the checkout owner.
    result = subprocess.run(['git', '-c', 'safe.directory=' + str(root),
                             '-C', str(root), 'show', 'HEAD:' + relative.as_posix()],
                            capture_output=True)
    return result.returncode == 0 and result.stdout == pathlib.Path(path).read_bytes()


NO_BASELINE_LEVELS = ('L7', 'L8')


def discipline_problem(summary, peer_cpu=None):
    """peer_cpu is the session's declared free-run peer CPU (sweep.session_peer):
    the idle-state discipline is the isolated pair alone, or the pair plus that
    peer, for every row the session collected."""
    if peer_cpu is not None and (type(peer_cpu) is not int or peer_cpu < 0):
        return 'invalid declared peer CPU'
    expected_disabled = 2 if peer_cpu is None else 3
    problem = sweep.row_problem(summary)
    if problem:
        return problem + ' (cycles)' if problem.startswith('incomplete run') else problem
    try:
        fields = sweep.config_fields(summary)
        applied = summary['applied']
        if summary['mode'] == 'freerun':
            required = {'mode', 'abs-deadline', 'mlock', 'fifo', 'cpu', 'telemetry', 'record'}
            if not required <= fields.keys() or fields['mode'] != 'freerun' or fields['record'] != 'control':
                return 'missing freerun config mitigation'
            if fields['fifo'] != '80':
                return 'invalid freerun config fifo'
            if any(applied.get(k) is not True for k in ('mlock','cpu','fifo','telemetry','link')):
                return 'required mitigation not applied'
            total, warmup = summary.get('total_cycles'), summary.get('warmup')
            if (type(total) is not int or type(warmup) is not int or warmup < 0
                    or total != warmup + summary['cycles']):
                return 'invalid actual cycle window'
        elif any(applied.get(k) is not True for k in ('mlock','cpu','fifo','telemetry')):
            return 'required config was not applied'
        env = summary.get('env')
        if not isinstance(env, dict):
            return 'missing env'
        for key, value in (('kernel','7.0.0-30-generic'), ('timer_migration',0),
                           ('governor','performance'), ('epp','performance'), ('ac_online',True)):
            if type(env.get(key)) is not type(value) or env[key] != value:
                return 'discipline env.' + key
        cpu = env.get('cpu_end')
        if type(cpu) is not int or cpu < 0 or ('cpu' in fields and cpu != int(fields['cpu'])):
            return 'discipline configured/actual cpu mismatch'
        idle = env.get('cpuidle')
        if (not isinstance(idle, dict) or not isinstance(idle.get('driver'), str)
                or idle['driver'] in ('', 'unknown') or type(idle.get('cpus')) is not int
                or idle['cpus'] < 2 or not isinstance(idle.get('states'), list) or not idle['states']):
            return 'discipline cpuidle population'
        for state in idle['states']:
            if (not isinstance(state, dict) or not isinstance(state.get('name'), str)
                    or state['name'] in ('', 'unknown') or type(state.get('latency_us')) is not int
                    or state['latency_us'] < 0 or type(state.get('disabled')) is not int
                    or state['disabled'] != expected_disabled or state['disabled'] > idle['cpus']):
                return 'discipline cpuidle state/disabled population'
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        return 'invalid discipline fields: ' + str(error)
    return None


def level_problem(summary, level, legacy_ok=False):
    mode, problem = sweep.summary_mode(summary, legacy_ok)
    expected = 'freerun' if level == 'L8' else 'harness'
    return problem or (f'mode {mode} does not match level {level}' if mode != expected else None)


def p999(summary):
    value = summary.get('jitter_us', {}).get('p99.9')
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise ValueError('invalid jitter p99.9')
    return value


def profile_problem(summary, level):
    fields = sweep.config_fields(summary)
    number = int(level[1:])
    if number == 8:
        expected = {'mode','abs-deadline','mlock','fifo','cpu','telemetry','record'}
    else:
        expected = {'abs-deadline' if number else 'sleep_for',
                    'no-alloc' if number >= 5 else 'naive-log'}
        for minimum, key in ((2,'mlock'),(3,'fifo'),(4,'cpu'),(6,'telemetry'),(7,'record')):
            if number >= minimum:
                expected.add(key)
    if set(fields) != expected or ('fifo' in fields and fields['fifo'] != '80') or ('record' in fields and fields['record'] != 'control'):
        return 'config does not match level ' + level
    return None


def verified_p999s(directory, level, baseline=False):
    """Selected-level values; candidate directory discipline is checked separately."""
    values = []
    for path in sorted(pathlib.Path(directory).glob(f'{level}*.summary.json')):
        if path.name.split('.')[0] != level:
            continue
        s = sweep.read_json(path)
        legacy_ok = baseline and legacy_baseline(path)
        problem = level_problem(s, level, legacy_ok)
        if problem:
            raise ValueError(f'{path}: {problem}')
        problem = sweep.row_problem(s, legacy_ok)
        if problem:
            print(f'{path}: {problem}', file=sys.stderr)
        else:
            values.append(p999(s))
    return values


def candidate_rows(directory):
    paths = sorted(pathlib.Path(directory).rglob('*.summary.json'))
    if not paths:
        raise ValueError('no candidate summaries')
    # One declared machine state per results root: a nested directory with its
    # own roster, or none, may not pool rows taken under another discipline.
    sessions = {}
    for parent in sorted({path.parent for path in paths}):
        try:
            sessions[parent] = sweep.session_peer(parent)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ValueError(f'{parent / "sweep.json"}: {error}') from error
    if len(set(sessions.values())) > 1:
        raise ValueError('mixed peer CPU declarations under one results root')
    rows = []
    for path in paths:
        try:
            summary = sweep.read_json(path)
            label = path.name.split('.')[0]
            if not re.fullmatch(r'L[0-8]', label):
                raise ValueError('unknown sweep level ' + label)
            peer_cpu = sessions[path.parent]
            problem = level_problem(summary, label) or discipline_problem(summary, peer_cpu) or profile_problem(summary, label)
            if problem:
                raise ValueError(problem)
            prefix = path.with_name(path.name[:-len('.summary.json')])
            item = dict(prefix=prefix,summary=summary,run=None,peer_cpu=peer_cpu)
            if label == 'L8':
                item['run'] = sweep.roster_row(prefix)
                sweep.audit_freerun(prefix)
                from scripts.latency import verify_recorded_statistics
                verify_recorded_statistics(prefix,summary)
                item['replay'] = {'loss':sweep.read_json(str(prefix)+'.replay.json')['loss']}
                item['reconciliation'] = sweep.read_json(str(prefix)+'.reconcile.json')
            p999(summary)
            rows.append(item)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise ValueError(f'{path}: {error}') from error
    return rows


def candidate_values(directory, level):
    return [p999(item['summary']) for item in candidate_rows(directory)
            if item['prefix'].name.split('.')[0] == level]


def gate(new_values, base_values, tolerance_pct):
    """(ok, message). Fails when the new median exceeds the baseline median
    plus tolerance, or when either side has no verified runs."""
    if not new_values:
        return False, "no verified runs in the results directory"
    if not base_values:
        return False, "no verified runs in the baseline directory"
    new_med = statistics.median(new_values)
    base_med = statistics.median(base_values)
    limit = base_med * (1 + tolerance_pct / 100.0)
    ok = new_med <= limit
    verdict = "pass" if ok else "REGRESSION"
    return ok, (f"{verdict}: new p99.9 median {new_med:.1f} us vs baseline "
                f"{base_med:.1f} us (limit {limit:.1f} at +{tolerance_pct:g}%)")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, help="fresh campaign directory")
    ap.add_argument("--baseline", default="baselines/2026-08-29-pinned-timer-campaign")
    ap.add_argument("--level", default="L5")
    # 50% at the 16.5 us pinned-timer baseline: identical-config repeats
    # spread 16.4-16.8 us, while a discipline lapse (timer migration on,
    # or the pair's C-states enabled) lands at 85 us or worse.
    ap.add_argument("--tolerance-pct", type=float, default=50.0)
    ap.add_argument("--no-baseline", action="store_true")
    ap.add_argument('--latency-p999-max-us',type=float)
    ap.add_argument('--latency-max-us',type=float)
    ap.add_argument('--served-coverage-min',type=float)
    args = ap.parse_args(argv)

    if args.no_baseline and args.level not in NO_BASELINE_LEVELS:
        print(f'--no-baseline is not permitted for level {args.level}', file=sys.stderr)
        return 1
    if args.level not in [row[0] for row in sweep.LEVELS] or not math.isfinite(args.tolerance_pct) or args.tolerance_pct < 0:
        print('invalid level or tolerance', file=sys.stderr)
        return 1
    limits = (args.latency_p999_max_us, args.latency_max_us, args.served_coverage_min)
    if any(v is not None for v in limits) and args.level != 'L8':
        print('latency/coverage gates require level L8',file=sys.stderr)
        return 1
    for value, lo, hi in zip(limits,(0,0,.99),(1000,2000,1)):
        if value is not None and (not math.isfinite(value) or not lo <= value <= hi):
            print('latency/coverage limits cannot weaken the approved budgets',file=sys.stderr)
            return 1
    try:
        rows = candidate_rows(args.results)
        selected = [item for item in rows if item['prefix'].name.split('.')[0] == args.level]
        if args.level == 'L8':
            from scripts.latency import evidence_checks
            for item in selected:
                report = evidence_checks(item,
                    p999_max=args.latency_p999_max_us if args.latency_p999_max_us is not None else 1000,
                    latency_max=args.latency_max_us if args.latency_max_us is not None else 2000,
                    coverage_min=args.served_coverage_min if args.served_coverage_min is not None else .99)
                if report['problems']:
                    raise ValueError(str(item['prefix']) + ': ' + '; '.join(report['problems']))
        values = [p999(item['summary']) for item in selected]
        if not values:
            raise ValueError('no verified runs in the results directory')
        if args.no_baseline:
            ok, msg = True, 'discipline/integrity pass; no historical baseline comparison'
        else:
            ok, msg = gate(values, verified_p999s(args.baseline, args.level, baseline=True), args.tolerance_pct)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"bench gate [{args.level}] {msg}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

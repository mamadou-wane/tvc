"""Functional population audit; --results additionally enforces evidence gates."""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from ground import wire

DISPOSITIONS = ('consumed', 'discarded_old', 'discarded_superseded', 'discarded_nonfinite',
                'discarded_skew_excess', 'discarded_duplicate', 'discarded_tick_conflict',
                'discarded_invalid', 'future_expired')
BAD = ('bad_sync', 'bad_version', 'bad_type', 'bad_length', 'bad_crc')
COUNTERS = ('received',) + DISPOSITIONS + BAD + ('fresh', 'coast', 'neutral', 'lost',
           'actuator_transmitted', 'actuator_tx_fail', 'served')


def natural(value):
    if type(value) is not int or value < 0: raise ValueError('invalid nonnegative counter')
    return value


def validate(summary, controls):
    result = dict(errors=[], identities={}, served_ns=[], observation_coverage=None, served_coverage=None)
    errors, identities = result['errors'], result['identities']
    def check(name, condition):
        identities[name] = bool(condition)
        if not condition: errors.append(name)
    try:
        if summary['mode'] != 'freerun': raise ValueError('freerun mode required')
        total=natural(summary['total_cycles']); warmup=natural(summary['warmup'])
        count=max(0,total-warmup)
        check('actual recorded window',natural(summary['cycles'])==count)
        check('recording count',len(controls)==total==natural(summary['telemetry']['records']))
        check('recording drops',natural(summary['telemetry']['dropped'])==0 and all(r['drops']==0 for r in controls))
        check('record ownership',all(natural(summary['events'][key])==total for key in
              ('episode_transitions','record_attempts','records_pushed')))
        link=summary['link']; recorded=summary['link_recorded']
        for c in (link,recorded):
            for key in COUNTERS: natural(c[key])
        final=natural(summary['future_parked_at_end']); initial=summary['future_parked_at_warmup']
        if count:
            natural(initial)
            check('T4',recorded['received']+initial==sum(recorded[k] for k in DISPOSITIONS)+final)
        else:
            identities['T4']=None
            check('unopened window',initial is None and all(recorded[k]==0 for k in COUNTERS))
        check('E3',link['received']==sum(link[k] for k in DISPOSITIONS)+final)
        check('E2',sum(link[k] for k in ('fresh','coast','neutral','lost'))==total)
        check('recorded ladder',sum(recorded[k] for k in ('fresh','coast','neutral','lost'))==count)
        terminal=natural(summary['terminal']['cycle'])
        check('terminal cycle',terminal==sum(r['state']==3 for r in controls) and terminal<=1)
        check('terminal partition',natural(summary['terminal']['down_attempts'])==
              natural(summary['terminal']['down_transmitted'])+natural(summary['terminal']['down_tx_fail']) and
              (summary['terminal']['down_attempts']>=1 if terminal else summary['terminal']['down_attempts']==0))
        first_ok=summary['terminal']['first_tx_ok']
        check('terminal first send',
              (type(first_ok) is bool and first_ok==bool(controls[-1]['flags']&2) and
               summary['terminal']['down_transmitted']>=int(first_ok) and
               summary['terminal']['down_tx_fail']>=int(not first_ok)) if terminal else first_ok is None)
        check('E1',link['actuator_transmitted']+link['actuator_tx_fail']==total-terminal)
        check('actuator totals',summary['actuator']==dict(generated=total-terminal,
              transmitted=link['actuator_transmitted'],tx_fail=link['actuator_tx_fail']))
        base=natural(summary['episode']['tick_base'])
        check('record ticks',all(r['tick']==base+n and r['deadline_ns']==summary['origin_ns']+n*2000000
                                for n,r in enumerate(controls)))
        check('timestamp order',all(0<=r['woke_ns']<=r['rx_ns']<=r['tx_ns']<=r['done_ns'] for r in controls))
        check('receive bounds',all(0<=r['rx_count']<=(9 if n==0 else 8) for n,r in enumerate(controls)))
        held_tick=None; held_stamp=0; observation_ok=True
        for n,r in enumerate(controls):
            if r['flags']&1:
                observation_ok &= (held_tick is None or r['sensor_tick']>held_tick) and r['sensor_tick']<=r['tick']
                held_tick=r['sensor_tick']; held_stamp=r['sensor_send_ns']
            age=r['tick']-held_tick if held_tick is not None else n+1
            observation_ok &= (r['staleness']==min(0xffffffff,age) and
                               r['sensor_tick']==(held_tick if held_tick is not None else 0xffffffffffffffff) and
                               r['sensor_send_ns']==held_stamp)
        check('admitted observation history',observation_ok)
        for name,c,rows in (('episode',link,controls),('recorded',recorded,controls[warmup:])):
            ladder=[0,0,0,0]
            for r in rows:
                rung=3 if r['staleness']>=21 else 0 if r['flags']&1 else 1 if r['staleness']<=8 else 2
                ladder[rung]+=1
            check(name+' ladder flags',ladder==[c[k] for k in ('fresh','coast','neutral','lost')])
            check(name+' consumption',c['consumed']==sum(bool(r['flags']&1) for r in rows))
            check(name+' served',c['served']==sum((r['flags']&3)==3 for r in rows))
            check(name+' ordinary send',c['actuator_transmitted']==sum(r['state']!=3 and bool(r['flags']&2) for r in rows))
            check(name+' ordinary failure',c['actuator_tx_fail']==sum(r['state']!=3 and not r['flags']&2 for r in rows))
            for key in ('discarded_old','discarded_superseded'):
                check(name+' '+key,c[key]==sum(r[key] for r in rows))
            check(name+' discarded_other',c['discarded_nonfinite']+c['discarded_skew_excess']==sum(r['discarded_other'] for r in rows))
            terminal_rx=natural(summary['terminal']['up_received_raw' if name=='episode' else 'up_received_raw_recorded'])
            check(name+' raw receipt',sum(r['rx_count'] for r in rows)==c['received']+sum(c[k] for k in BAD)+terminal_rx)
        served=[r for r in controls[warmup:] if (r['flags']&3)==3]
        result['served_ns']=[r['tx_ns']-r['sensor_send_ns'] for r in served]
        for key,end,start in (('latency_us','tx_ns','sensor_send_ns'),('uplink_wait_us','rx_ns','sensor_send_ns'),
                              ('vehicle_compute_us','tx_ns','rx_ns')):
            d=summary[key]; values=[r[end]-r[start] for r in served]
            check(key+' population',natural(d['count'])==len(served))
            check(key+' formula',natural(d['sum_ns'])==sum(values) and all(0<=v<=10000000000 for v in values))
            check(key+' drops',natural(d['dropped'])==0)
        check('T1',natural(summary['jitter_us']['count'])==natural(summary['exec_us']['count'])==summary['cycles']==count and natural(summary['dropped_samples'])==0)
        check('T2',summary['latency_us']['count']==recorded['served'])
        check('T3',natural(summary['discard_age_us']['count'])==sum(recorded[k] for k in
              ('discarded_old','discarded_superseded','discarded_nonfinite','discarded_skew_excess')))
        check('discard histogram drops',natural(summary['discard_age_us']['dropped'])==0)
        if not count: check('empty discard population',natural(summary['discard_age_us']['sum_ns'])==0)
        if count:
            result['observation_coverage']=recorded['consumed']/count
            result['served_coverage']=recorded['served']/count
    except (KeyError,TypeError,ValueError,OverflowError,IndexError) as exc:
        errors.append('incomplete or invalid measurement evidence: '+str(exc))
    result['valid']=not errors
    return result


def validate_roundtrip(report):
    try:
        rows=report['roundtrip_samples']
        values=[]
        for row in rows:
            start=natural(row['sensor_send_ns']);end=natural(row['received_ns']);status=natural(row['status'])
            if not start or end<start or status&255==3 or (status>>16)&255!=0:
                raise ValueError('ineligible round-trip observation')
            values.append(end-start)
        if values!=report['latency_roundtrip_ns'] or len(values)>natural(report['actuator_receipt']['received']):
            raise ValueError('round-trip endpoint or receipt mismatch')
        d=report['latency_roundtrip_us'];ordered=sorted(values)
        expected=dict(count=len(values),sum_ns=sum(values),max=max(values,default=0)/1000)
        for key,p in (('p50',.5),('p99.9',.999)):
            expected[key]=ordered[max(0,math.ceil(p*len(ordered))-1)]/1000 if ordered else 0
        if d!=expected: raise ValueError('round-trip summary mismatch')
    except (KeyError,TypeError,ValueError,OverflowError,IndexError) as exc:
        return ['invalid round-trip evidence: '+str(exc)]
    return []


def recorded_statistics(values):
    """Match Distribution's 1 ns / three-figure Hdr buckets and six-digit JSON."""
    ordered = sorted(natural(value) for value in values)
    if ordered and ordered[-1] > 10000000000:
        raise ValueError('recorded latency outside histogram range')
    def reported(value):
        shift = max(0, value.bit_length()-11)
        high = ((value >> shift)+1) * (1 << shift)-1
        return float(format(high/1000.0, '.6g'))
    if not ordered:
        return {'p99.9':0.0,'max':0.0}
    rank = max(1, int((99.9/100)*len(ordered)+0.5))
    return {'p99.9':reported(ordered[rank-1]),'max':reported(ordered[-1])}


def verify_recorded_statistics(prefix, summary):
    _, controls, counts = wire.read_typed_recording(Path(str(prefix)+'.control.tvcrec'), expected_type=6)
    if any(v for k,v in counts.items() if k != 'frames_ok'):
        raise ValueError('invalid recording for latency statistics')
    warmup = natural(summary['warmup'])
    values = [r['tx_ns']-r['sensor_send_ns'] for r in controls[warmup:] if r['flags']&3 == 3]
    expected = recorded_statistics(values)
    if any(metric(summary['latency_us'][key], key) != value for key,value in expected.items()):
        raise ValueError('reported latency statistics do not match recorded samples')


def metric(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('invalid ' + name)
    return value


def evidence_checks(item, *, coverage_min=.99, p999_max=1000.0, latency_max=2000.0):
    """Apply evidence policy after the existing recording/reconciliation audit."""
    from scripts import bench_gate
    try:
        s, replay, reconciliation = item['summary'], item['replay'], item['reconciliation']
        problems = []
        if s.get('mode') != 'freerun':
            problems.append('freerun mode required')
        problem = bench_gate.discipline_problem(s)
        if problem:
            problems.append(problem)
        loss = replay['loss']
        up, down = metric(loss['p_up'], 'peer loss'), metric(loss['p_down'], 'peer loss')
        if up > 1 or down > 1:
            raise ValueError('invalid peer loss')
        if up or down:
            problems.append(f'coverage requires zero peer loss (up={up:g}, down={down:g})')
        cycles = natural(s['cycles'])
        served = natural(s['link_recorded']['served'])
        consumed = natural(s['link_recorded']['consumed'])
        if not cycles or not 0 <= served <= consumed <= cycles:
            raise ValueError('invalid coverage population')
        if natural(s['latency_us']['count']) != served:
            raise ValueError('served histogram population mismatch')
        coverage = served / cycles
        if coverage < coverage_min:
            problems.append('served coverage below minimum')
        if natural(s['link_recorded']['actuator_tx_fail']):
            problems.append('recorded actuator local-send failure')
        for direction in ('uplink','downlink'):
            if natural(reconciliation[direction]['unexplained_missing']):
                problems.append(direction + ' unexplained missing traffic')
        if reconciliation['eligible'] is not True:
            problems.append('ineligible reconciliation')
        if reconciliation['terminal_agreement'] is not True:
            problems.append('terminal agreement failed')
        terminal = reconciliation['terminal']
        if terminal['required_legs_complete'] is not True:
            problems.append('incomplete terminal handshake')
        for direction in ('up','down'):
            leg = terminal[direction]
            if type(leg['required']) is not bool or leg['residual'] not in ('zero','trailing','unresolved','unexplained','not_evaluated'):
                raise ValueError('invalid terminal disposition')
            if leg['required'] and leg['residual'] == 'unexplained':
                problems.append('terminal unexplained transport loss')
        if 'unexplained_transport_loss' in terminal['causes']:
            problems.append('terminal unexplained transport loss')
        if sum(natural(s['link'][key]) for key in BAD):
            problems.append('malformed ingress')
        p999 = metric(s['latency_us']['p99.9'], 'latency p99.9')
        maximum = metric(s['latency_us']['max'], 'latency max')
        if p999 > maximum:
            raise ValueError('latency percentile exceeds maximum')
        if p999 > p999_max:
            problems.append('served latency p99.9 exceeds budget')
        if maximum > latency_max:
            problems.append('served latency max exceeds budget')
        return dict(label=s['label'], served_coverage=coverage, observation_coverage=consumed/cycles,
                    latency_p999_us=p999, latency_max_us=maximum, problems=problems,
                    terminal_residuals={key:terminal[key]['residual'] for key in ('up','down')})
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError('missing or invalid latency evidence: ' + str(error)) from error


def ordered_results(directory):
    from scripts import bench_gate, sweep
    root = Path(directory)
    rows = bench_gate.candidate_rows(root)
    roster = sweep.read_json(root/'sweep.json')
    if not isinstance(roster, dict) or roster.get('complete') is not True or not isinstance(roster.get('runs'), list):
        raise ValueError('incomplete experiment roster')
    by_label = {item['prefix'].name:item for item in rows}
    if len(by_label) != len(rows):
        raise ValueError('ambiguous repeated labels in results')
    ordered, seen = [], set()
    for run in roster['runs']:
        if not isinstance(run, dict) or not isinstance(run.get('label'), str):
            raise ValueError('invalid experiment row')
        label = run['label']
        if label in seen or label not in by_label:
            raise ValueError('duplicate or missing experiment run ' + label)
        item = by_label[label]
        if item['prefix'].parent != root:
            raise ValueError('experiment rows must belong to one roster directory')
        item['run'] = sweep.roster_row(item['prefix'])
        ordered.append(item); seen.add(label)
    if seen != set(by_label):
        raise ValueError('unrostered candidate summary')
    return ordered


def experiment_row(item, level, repeat, label):
    from scripts import bench_gate, sweep
    s, run = item['summary'], item['run']
    problem = bench_gate.level_problem(s, level) or bench_gate.discipline_problem(s) or bench_gate.profile_problem(s, level)
    if problem:
        raise ValueError(label + ': ' + problem)
    if (run.get('label') != label or s.get('label') != label or item['prefix'].name != label
            or run.get('level') != level or type(run.get('repeat')) is not int or run['repeat'] != repeat
            or run.get('complete') is not True):
        raise ValueError('mismatched experiment label/level/repeat: ' + label)
    for key, value in (('cycles',300000),('warmup',5000),('rate',500)):
        permitted = (int,float) if key == 'rate' else (int,)
        if type(run.get(key)) not in permitted or run[key] != value:
            raise ValueError('invalid experiment ' + key)
    if s['cycles'] != 300000 or s['cycles_requested'] != 300000 or s.get('period_us') != 2000:
        raise ValueError('invalid experiment timing window')
    if level == 'L8' and (type(run.get('phase_us')) is not int or s.get('phase_us') != run['phase_us']):
        raise ValueError('experiment phase mismatch')
    if level != 'L8':
        sweep.harness_configuration(run, s)
    return sweep.config_fields(s)


def calibration(rows):
    if len(rows) != 9:
        raise ValueError('calibration requires exactly nine runs')
    reports = {phase:[] for phase in (200,400,800)}
    cpu = None
    for item,(repeat,phase) in zip(rows,((r,p) for r in range(1,4) for p in (200,400,800))):
        label = f'L8.phase{phase}.r{repeat}'
        fields = experiment_row(item, 'L8', repeat, label)
        if cpu is not None and cpu != fields['cpu']:
            raise ValueError('calibration CPU configuration mismatch')
        cpu = fields['cpu']
        if item['run']['phase_us'] != phase:
            raise ValueError('calibration offset/order mismatch')
        report = evidence_checks(item)
        if item['replay']['loss'] != dict(p_up=0.0,p_down=0.0):
            raise ValueError(label + ': calibration requires zero peer loss')
        reports[phase].append(report)
    import statistics
    verdicts = []
    for phase, runs in reports.items():
        median = statistics.median(r['served_coverage'] for r in runs)
        verdicts.append(dict(phase_us=phase, median_served_coverage=median,
                             qualifies=all(not r['problems'] for r in runs) and median >= .995,
                             runs=runs))
    selected = next((v['phase_us'] for v in verdicts if v['qualifies']), None)
    return dict(valid=selected is not None, selected_phase_us=selected, offsets=verdicts,
                message='no offset qualifies' if selected is None else 'smallest qualifying offset selected')


def write_report(result):
    try:
        text = json.dumps(result, sort_keys=True, allow_nan=False) + '\n'
        if sys.stdout.write(text) != len(text):
            return 1
        sys.stdout.flush()
    except (OSError, ValueError):
        return 1
    return 0 if result['valid'] else 1


def results_main(directory, calibrate=False):
    from scripts import bench_gate
    try:
        if calibrate:
            result = calibration(ordered_results(directory))
        else:
            rows = bench_gate.candidate_rows(directory)
            reports = [evidence_checks(item) for item in rows if item['summary']['mode']=='freerun']
            if not reports:
                raise ValueError('no freerun latency evidence')
            result = dict(valid=all(not r['problems'] for r in reports), runs=reports)
    except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
        result = dict(valid=False, errors=[str(error)])
    return write_report(result)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix',type=Path,nargs='?')
    parser.add_argument('--results',type=Path)
    parser.add_argument('--calibration',action='store_true')
    args=parser.parse_args(argv)
    if bool(args.prefix) == bool(args.results) or (args.calibration and not args.results):
        parser.error('supply a functional prefix or --results; --calibration requires --results')
    if args.results:
        return results_main(args.results, args.calibration)
    try:
        summary=json.loads(Path(str(args.prefix)+'.summary.json').read_text())
        _,rows,counts=wire.read_typed_recording(Path(str(args.prefix)+'.control.tvcrec'),expected_type=6)
        if any(v for k,v in counts.items() if k!='frames_ok'): raise ValueError('incomplete recording')
        result=validate(summary,rows)
        reconciliation=json.loads(Path(str(args.prefix)+'.reconcile.json').read_text())
        replay=json.loads(Path(str(args.prefix)+'.replay.json').read_text())
        _,sensors,input_counts=wire.read_typed_recording(Path(str(args.prefix)+'.inputs.tvcrec'),expected_type=4)
        if any(v for k,v in input_counts.items() if k not in ('frames_ok','lost')): raise ValueError('incomplete input recording')
        from scripts.reconcile import reconcile
        observed=reconcile(summary,replay,'freerun',sensors=sensors,controls=rows)
        if observed!=reconciliation: result['errors'].append('stale or mismatched reconciliation')
        if not observed['eligible']: result['errors'].append('reconciliation failed')
        result['valid']=not result['errors']
    except (OSError,ValueError,KeyError,TypeError,IndexError) as exc: result=dict(valid=False,errors=[str(exc)])
    print(json.dumps(result,sort_keys=True))
    return 0 if result['valid'] else 1


if __name__=='__main__': raise SystemExit(main())

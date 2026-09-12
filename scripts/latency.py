"""Functional free-run population audit. No platform qualification or latency budget gate."""
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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix',type=Path)
    args=parser.parse_args()
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

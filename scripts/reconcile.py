"""Reconcile observed lockstep events; a valid pairing is not stabilization."""
import math
import struct

from sim import rng


SEND_FIELDS=('generated','original_attempts','retry_attempts','not_attempted','send_attempts',
             'send_pending','tx_fail','transmitted','first_transmitted','additional_copies','never_transmitted')


def sender_errors(c):
    if not isinstance(c,dict) or any(type(c.get(k)) is not int or c[k]<0 for k in SEND_FIELDS):
        return ['missing or invalid sender counter']
    equations=(('generation',c['generated'],c['original_attempts']+c['not_attempted']),
               ('attempts',c['send_attempts'],c['original_attempts']+c['retry_attempts']),
               ('send outcomes',c['send_attempts'],c['tx_fail']+c['transmitted']+c['send_pending']),
               ('successful copies',c['transmitted'],c['first_transmitted']+c['additional_copies']),
               ('first success',c['generated'],c['first_transmitted']+c['never_transmitted']))
    return [name for name,left,right in equations if left!=right]


def receiver_errors(c,sensor=False):
    keys=('received_raw','malformed','received','decode_pending','logical_received',
          'discarded_duplicate','rejected_received','classification_pending')
    extra=('admitted','sample_invalid','sample_nonfinite','admission_pending') if sensor else (
        'modeled_command_loss','forwarded_to_delay','disposition_pending')
    if not isinstance(c,dict) or any(type(c.get(k)) is not int or c[k]<0 for k in keys+extra):
        return ['missing or invalid receiver counter']
    errors=[]
    if c['received_raw']!=c['malformed']+c['received']+c['decode_pending']: errors.append('raw receipt')
    if c['received']!=sum(c[k] for k in keys[4:]): errors.append('receipt disposition')
    if c['logical_received']!=sum(c[k] for k in extra): errors.append('logical disposition')
    return errors


def same(a,b): return struct.pack('<d',a)==struct.pack('<d',b)


def reconcile(summary,replay,mode,*,sensors,controls):
    if mode=='freerun': return reconcile_freerun(summary,replay,sensors,controls)
    result=dict(format='tvc-reconcile-1',mode=mode,eligible=False,terminal_agreement=False,errors=[])
    errors=result['errors']
    if mode!='lockstep': errors.append('only lockstep reconciliation is implemented'); return result
    if not isinstance(summary,dict) or not isinstance(replay,dict):
        errors.append('missing owner report'); return result
    try:
        up_tx=replay['transmission'];up_rx=summary['link']
        down_tx=summary['actuator'];down_rx=replay['actuator_receipt']
        for name,tx,rx in [('uplink',up_tx,up_rx),('downlink',down_tx,down_rx)]:
            problems=sender_errors(tx)+receiver_errors(rx,name=='uplink')
            errors.extend(name+': '+e for e in problems)
            if problems: return result
            residual=tx['transmitted']-rx['received_raw']
            result[name]={**tx,**rx,'unobserved':residual}
            if residual!=0: errors.append(name+': unexplained observed-send/receipt discrepancy')
            for key in ('not_attempted','never_transmitted','send_pending'):
                if tx[key]: errors.append(name+': incomplete '+key)
            for key in ('decode_pending','classification_pending','malformed',
                        'admission_pending' if name=='uplink' else 'disposition_pending'):
                if rx[key]: errors.append(name+': incomplete or invalid '+key)
        if type(down_tx.get('original_tx_fail')) is not int or down_tx['original_tx_fail']<0:
            errors.append('missing or invalid original actuator failure counter')
        if down_tx['original_tx_fail']: errors.append('original actuator send failed')
        if sum(not bool(r['flags']&2) for r in controls)!=down_tx['original_tx_fail']:
            errors.append('TX_OK disagrees with original send outcomes')
        if summary['mode']!='lockstep' or summary['timing_valid'] is not False:
            errors.append('invalid lockstep mode/timing validity')
        if summary['telemetry']['dropped']!=0: errors.append('ring drops')
        count=summary['total_cycles']; replies=replay['actuator_replies']; rows=replay['rows']
        events=summary['events']
        if any(type(events.get(k)) is not int or events[k]<0 for k in (
                'episode_transitions','pid_calls','record_attempts','records_pushed','ring_drops','record_pending')):
            errors.append('missing or invalid vehicle event counter')
        if events['episode_transitions']!=count or events['episode_transitions']!=events['record_attempts']+events['record_pending']:
            errors.append('transition/record attempt identity')
        if events['record_attempts']!=events['records_pushed']+events['ring_drops']:
            errors.append('record push identity')
        if events['record_pending'] or events['ring_drops']!=summary['telemetry']['dropped'] or events['records_pushed']!=summary['telemetry']['records']:
            errors.append('incomplete record population')
        if events['pid_calls']>up_rx['admitted']:
            errors.append('PID calls exceed admitted samples')
        lengths=[len(sensors),len(controls),len(replies),len(rows),summary['telemetry']['records'],
                 up_tx['generated'],up_tx['first_transmitted'],up_rx['logical_received'],
                 down_tx['generated'],down_rx['logical_received']]
        if count<=0 or any(n!=count for n in lengths): errors.append('incomplete logical artifacts')
        held=None; admitted=invalid=nonfinite=0
        for tick,(sample,record,reply,row) in enumerate(zip(sensors,controls,replies,rows)):
            if any(x['tick']!=tick for x in (sample,record,reply,row)) or reply['veh_tick']!=tick:
                errors.append('noncontiguous logical tick'); break
            fresh=bool(sample['flags']&1) and math.isfinite(sample['theta']) and math.isfinite(sample['omega'])
            if fresh: held=sample;admitted+=1
            elif not sample['flags']&1: invalid+=1
            else: nonfinite+=1
            age=min(tick-held['tick'] if held else tick+1,0xffffffff)
            expected_tick=held['tick'] if held else 0xffffffffffffffff
            if record['sensor_tick']!=expected_tick or record['staleness']!=age or bool(record['flags']&1)!=fresh:
                errors.append('admission history or staleness mismatch'); break
            if not same(record['theta'],held['theta'] if held else 0.0) or not same(record['omega'],held['omega'] if held else 0.0):
                errors.append('held observation mismatch');break
            status=reply['status']
            if (status&255)!=record['state'] or ((status>>8)&255)!=record['reason'] or not same(reply['delta'],record['cmd']) or reply['staleness']!=age:
                errors.append('actuator/control record mismatch');break
            ack_byte=(0x80|record['ack_status']) if record['flags']&64 else 0
            if (status>>24)!=ack_byte: errors.append('ACK projection mismatch');break
            if record['rx_count']!=1 or record['discarded_old'] or record['discarded_superseded'] or record['flags']&32:
                errors.append('physical diagnostics leaked into logical record');break
            if record['discarded_other']!=int(bool(sample['flags']&1) and not fresh):
                errors.append('logical nonfinite count mismatch');break
            if any(record[k]!=0 for k in ('deadline_ns','woke_ns','done_ns','sensor_send_ns','rx_ns','tx_ns')) or sample['t_send_ns']!=0:
                errors.append('nonzero lockstep timestamp');break
        if (admitted,invalid,nonfinite)!=(up_rx['admitted'],up_rx['sample_invalid'],up_rx['sample_nonfinite']):
            errors.append('sample disposition totals mismatch')
        for i,name in enumerate(('link.loss.up','link.loss.down')):
            stream=replay['rng']['streams'][name];start=rng.stream_state(replay['seed'],name)
            if stream['index']!=i or stream['draws']!=up_tx['generated'] or int(stream['start_state'],16)!=start or int(stream['final_state'],16)!=(start+rng.GOLDEN*stream['draws'])&rng.MASK:
                errors.append('RNG ownership mismatch')
        sim_reason=replay['sim_reason']; ep=summary['episode']; reason=ep['vehicle_reason']
        result.update(sim_reason=sim_reason,vehicle_reason=reason,reason_tick=ep['reason_tick'])
        pair=(sim_reason,reason)
        expected=pair in {(1,1),(1,7),(2,2),(3,2),(4,2),(4,3),(4,4)}
        if pair==(1,4):
            expected=bool(controls and controls[-1]['staleness']>=21)
        if not controls or controls[-1]['state']!=3 or controls[-1]['reason']!=reason or ep['reason_tick']!=controls[-1]['tick']:
            errors.append('terminal tick or record mismatch');expected=False
        if sim_reason in (1,2,3) and ep['sim_reason_seen']!=sim_reason:
            errors.append('simulator reason observation mismatch');expected=False
        if sim_reason==4 and ep['sim_reason_seen'] is not None:
            errors.append('invented simulator observation');expected=False
        if replay['vehicle_reason_seen']!=reason:
            errors.append('vehicle reason observation mismatch');expected=False
        result['terminal_agreement']=expected and not any('admission' in e or 'staleness' in e for e in errors)
        if not expected: errors.append('unexpected terminal pairing')
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        errors.append('incomplete or invalid evidence: '+str(exc))
    result['eligible']=not errors
    return result


def terminal_residual(transmitted, received, first_send, last_send, receive_open, receive_closed, required, answered=False):
    from scripts.latency import natural
    for value in (transmitted,received,first_send,last_send,receive_open,receive_closed): natural(value)
    if received > transmitted: raise ValueError('terminal receipts exceed successful sends')
    if receive_closed < receive_open or last_send < first_send: raise ValueError('invalid terminal lifetime')
    residual=transmitted-received
    if not required: resolution='not_evaluated'
    elif residual==0: resolution='zero'
    elif not first_send or not last_send: raise ValueError('missing terminal send lifetime')
    elif receive_closed < first_send: resolution='trailing'
    elif receive_open <= first_send and receive_closed >= last_send and not answered: resolution='unexplained'
    else: resolution='unresolved'
    return dict(unobserved=residual,residual=resolution)


def terminal_order(vehicle, simulator):
    causal_vehicle=simulator.get('termination_source')=='vehicle'
    causal_sim=vehicle.get('termination_source')=='simulator'
    if causal_vehicle and causal_sim: raise ValueError('contradictory terminal causality')
    causal='vehicle_first' if causal_vehicle else 'sim_first' if causal_sim else None
    shared=vehicle.get('clock_domain') and vehicle['clock_domain']==simulator.get('clock_domain')
    if shared:
        a,b=vehicle.get('termination_ns'),simulator.get('termination_ns')
        begin_a=vehicle.get('termination_before_ns');begin_b=simulator.get('termination_before_ns')
        if all(type(t) is int and t>0 for t in (a,b,begin_a,begin_b)):
            if begin_a>a or begin_b>b: raise ValueError('invalid termination interval')
            order='vehicle_first' if a<begin_b else 'sim_first' if b<begin_a else None
            if causal and order and causal!=order: raise ValueError('terminal causality contradicts shared-clock order')
            return causal or order
    return causal


def terminal_causes(legs):
    required=[v for v in legs.values() if v['required']]
    failed=[v for v in required if not v['complete']]
    if not failed: return []
    causes=[]
    if any(v['tx_fail'] for v in failed): causes.append('send_failure')
    if any(v['opportunities']<v['budget'] for v in failed): causes.append('opportunity_shortfall')
    if any(v['residual']=='unexplained' for v in failed): causes.append('unexplained_transport_loss')
    if not causes and all(v['opportunities']>=v['budget'] and v['tx_fail']==0 and
                          v['intentionally_lost']==v['opportunities'] for v in failed):
        causes.append('impairment_model')
    return causes


def reconcile_freerun(summary, replay, sensors, controls):
    from scripts.latency import validate, validate_roundtrip, natural, BAD
    result=dict(format='tvc-reconcile-1',mode='freerun',eligible=False,errors=[],identities={},terminal_agreement=False)
    errors=result['errors']; identities=result['identities']
    def check(name,condition):
        identities[name]=bool(condition)
        if not condition: errors.append(name)
    try:
        if summary['mode']!='freerun' or replay['mode']!='freerun': raise ValueError('owner mode mismatch')
        audit=validate(summary,controls)
        errors.extend(audit['errors']);result['measurement']={k:v for k,v in audit.items() if k!='served_ns'}
        errors.extend(validate_roundtrip(replay))
        check('shared sensor clock',bool(summary.get('clock_domain')) and summary['clock_domain']==replay.get('clock_domain'))
        up=replay['transmission'];down=replay['actuator_receipt'];v=summary['terminal'];s=replay['terminal']
        for c,keys in ((up,('generated','intentionally_lost','transmitted','sensor_tx_fail')),
                       (down,('received','actuator_selected','intentionally_lost','superseded','malformed','invalid')),
                       (s,('up_attempts','up_intentionally_lost','up_tx_fail','up_transmitted',
                           'down_received_raw','down_intentionally_lost','down_survived')),
                       (v,('down_attempts','down_tx_fail','down_transmitted','up_received_raw',
                           'up_tick_conflict','up_illegal_reason','up_future_expired','up_skew_excess'))):
            for key in keys: natural(c[key])
        check('uplink generation',up['generated']==up['intentionally_lost']+up['transmitted']+up['sensor_tx_fail'])
        normal=[r['tick'] for r in sensors if not r['flags']&2]
        check('input recording membership',len(normal)==len(set(normal))==up['transmitted'] and
              sum(bool(r['flags']&2) for r in sensors)==int(s['up_transmitted']>0))
        last=summary['last_received_tick'];base=summary['episode']['tick_base']
        check('uplink observed boundary',last in normal if summary['link']['received'] else last is None)
        inside=sum(base<=tick<=last for tick in normal) if last is not None else 0
        missing=inside-summary['link']['received']
        result['uplink']=dict(up,transmitted_in_window=inside,received=summary['link']['received'],
                              trailing_transmitted=up['transmitted']-inside,unexplained_missing=missing)
        check('uplink receipt',missing==0)
        sent=[r['tick'] for r in controls if r['state']!=3 and r['flags']&2]
        last=down['last_received_tick']
        if last is None and sent:
            raise ValueError('ordinary downlink overlap unestablished')
        check('downlink observed boundary',last in sent if down['received'] else last is None)
        inside=sum(base<=tick<=last for tick in sent) if last is not None else 0
        missing=inside-down['received']
        result['downlink']=dict(down,transmitted=len(sent),transmitted_in_window=inside,
            trailing_actuator_transmitted=len(sent)-inside,unexplained_missing=missing)
        check('downlink receipt',missing==0)
        check('downlink disposition',down['received']==down['actuator_selected']+down['intentionally_lost']+down['superseded'])
        check('link integrity',not any(summary['link'][k] for k in BAD+('discarded_tick_conflict','discarded_skew_excess','future_expired'))
              and not down['malformed'] and not down['invalid'] and not any(v[k] for k in
              ('up_tick_conflict','up_illegal_reason','up_future_expired','up_skew_excess')))
        check('terminal up',s['up_attempts']==s['up_intentionally_lost']+s['up_tx_fail']+s['up_transmitted'])
        check('terminal down',v['down_attempts']==v['down_tx_fail']+v['down_transmitted'] and
              s['down_received_raw']==s['down_intentionally_lost']+s['down_survived'])
        check('terminal first attempt',v['down_attempts']>=v['cycle'])
        order=terminal_order(summary,replay)
        path='vehicle_first' if order=='vehicle_first' else (
            'sim_first_up_delivered' if v['up_received_raw'] else 'sim_first_up_not_delivered') if order else None
        require_up=order=='sim_first' if order else None
        require_down=(order=='vehicle_first' or path=='sim_first_up_delivered') if order else None
        shared=bool(summary.get('clock_domain') and summary['clock_domain']==replay.get('clock_domain'))
        def residual(tx,rx,first,last,opened,closed,required,answered):
            if shared: return terminal_residual(tx,rx,first,last,opened,closed,required,answered)
            if rx>tx: raise ValueError('terminal receipts exceed sends')
            return dict(unobserved=tx-rx,residual='not_evaluated' if not required else 'zero' if tx==rx else 'unresolved')
        up_leg=dict(attempts=s['up_attempts'],intentionally_lost=s['up_intentionally_lost'],tx_fail=s['up_tx_fail'],
            transmitted=s['up_transmitted'],received_raw=v['up_received_raw'],required=require_up,complete=v['up_received_raw']>0,
            opportunities=s['up_attempts'],budget=summary['terminal_copies'])
        up_leg.update(residual(s['up_transmitted'],v['up_received_raw'],replay['terminal_send_first_ns'],
            replay['terminal_send_last_ns'],v['receive_open_ns'],v['receive_closed_ns'],require_up,up_leg['complete']))
        down_leg=dict(attempts=v['down_attempts'],tx_fail=v['down_tx_fail'],transmitted=v['down_transmitted'],
            received_raw=s['down_received_raw'],intentionally_lost=s['down_intentionally_lost'],survived=s['down_survived'],
            required=require_down,complete=s['down_survived']>0,opportunities=s['down_received_raw'],
            budget=min(summary['terminal_copies'],14))
        down_leg.update(residual(v['down_transmitted'],s['down_received_raw'],v['send_first_ns'],v['send_last_ns'],
            replay['receive_open_ns'],replay['receive_closed_ns'],require_down,down_leg['complete']))
        legs=dict(up=up_leg,down=down_leg)
        complete=(all(l['complete'] for l in legs.values() if l['required']) if order else None)
        causes=terminal_causes(legs) if order else []
        result['terminal']=dict(path=path,required_legs_complete=complete,causes=causes,**legs,
                                handshake=replay['terminal_handshake'])
        if order is None: errors.append('terminal ordering unresolved')
        for name,l in legs.items():
            check('terminal '+name+' unexplained',not l['required'] or l['residual']!='unexplained')
        check('terminal answer observation',(replay['vehicle_reason_seen'] is not None)==bool(s['down_survived']))
        check('terminal handshake',(replay['terminal_handshake']=='answered')==bool(s['down_survived']))
        sr=replay['sim_reason'];ep=summary['episode'];vr=ep['vehicle_reason']
        pair=(sr,vr)
        expected=pair in {(1,1),(1,7),(1,4),(2,2),(3,2),(2,4),(3,4),(4,1),(4,7),(4,2),(4,3),(4,4)}
        if ep['sim_reason_seen'] is not None:
            check('simulator observation',ep['sim_reason_seen']==sr and v['up_received_raw']>0)
        if replay['vehicle_reason_seen'] is not None: check('vehicle observation',replay['vehicle_reason_seen']==vr)
        check('terminal record',bool(controls) and controls[-1]['state']==3 and controls[-1]['reason']==vr and controls[-1]['tick']==ep['reason_tick'])
        result.update(sim_reason=sr,vehicle_reason=vr,terminal_agreement=expected)
        if vr in (5,6,8):
            result['terminal_agreement']=None
            errors.append('terminal outcome produces no evidence; pairing not evaluated')
        else: check('terminal agreement',expected)
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        errors.append('incomplete or invalid evidence: '+str(exc))
    result['eligible']=not errors
    return result

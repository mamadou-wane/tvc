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

#!/usr/bin/env python3
"""Compare interleaved per-run wakeup p99.9 values; runs are the experiment units."""
import argparse
from decimal import Decimal
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import bench_gate, latency


def compare(rows):
    levels = [item['run']['level'] for item in rows]
    with_l5 = 'L5' in levels
    order = ('L5','L7','L8') if with_l5 else ('L7','L8')
    expected = [(r,level) for r in range(1,9) for level in order]
    if len(rows) != len(expected):
        raise ValueError('comparison requires exactly eight interleaved L7/L8 pairs')
    pairs, values = [], {}
    cpu, phase = None, None
    for item,(repeat,level) in zip(rows,expected):
        fields = latency.experiment_row(item,level,repeat,f'{level}.r{repeat}')
        if cpu is not None and fields['cpu'] != cpu:
            raise ValueError('paired CPU configuration mismatch')
        cpu = fields['cpu']
        if level == 'L8':
            current_phase = item['run']['phase_us']
            if phase is not None and current_phase != phase:
                raise ValueError('mixed paired phase offsets')
            phase = current_phase
        values[level] = bench_gate.p999(item['summary'])
        if level == 'L8':
            pairs.append(dict(repeat=repeat,l7_p999_us=values['L7'],l8_p999_us=values['L8'],
                              difference_us=Decimal(str(values['L8']))-Decimal(str(values['L7']))))
    differences = [p['difference_us'] for p in pairs]
    positive = sum(d>0 for d in differences)
    negative = sum(d<0 for d in differences)
    n = positive+negative
    sign_p = min(1.0,2*sum(math.comb(n,k) for k in range(min(positive,negative)+1))/2**n)
    median = statistics.median(differences)
    for pair in pairs:
        pair['difference_us'] = float(pair['difference_us'])
    return dict(valid=median<=Decimal('2.0'),pairs=pairs,median_difference_us=float(median),
                min_difference_us=float(min(differences)),max_difference_us=float(max(differences)),margin_us=2.0,
                positive=positive,negative=negative,tied=8-n,sign_test_p=sign_p,
                sign_test_role='supplemental; does not decide acceptance')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',required=True,type=Path)
    parser.add_argument('--a',choices=['L7'],default='L7')
    parser.add_argument('--b',choices=['L8'],default='L8')
    args=parser.parse_args(argv)
    try:
        result=compare(latency.ordered_results(args.results))
    except (OSError,ValueError,KeyError,TypeError,IndexError) as error:
        result=dict(valid=False,errors=[str(error)])
    return latency.write_report(result)


if __name__=='__main__':
    raise SystemExit(main())

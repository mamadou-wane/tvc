"""Exact loss-count oracle over retained full S2-gust runs, including terminal tick."""
import argparse
import json
from pathlib import Path

# Independent integer recurrence: 10,000 draws per stream; u53 <= 2702159776422297.
EXPECTED={1:(3047,2943),2:(2952,2937),3:(3038,2978),4:(2977,3038),
          5:(3042,3042),6:(2952,3010),7:(3057,3026),8:(3025,2977)}


def check_counts(root,*,seeds=range(1,9),delays=(0,)):
    for seed in seeds:
        for delay in delays:
            path=Path(root)/f'seed-{seed:03d}-D{delay}'/'S2-gust.reconcile.json'
            report=json.loads(path.read_text())
            assert report['eligible'] and report['sim_reason']==report['vehicle_reason']==1, path
            assert report['reason_tick']==9999, path
            actual=(report['uplink']['modeled_sample_loss'],report['downlink']['modeled_command_loss'])
            assert actual==EXPECTED[seed], (path,actual,EXPECTED[seed])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root')
    check_counts(parser.parse_args().root)
    print('loss subset: exact committed counts passed for seeds 1..8, D=0')

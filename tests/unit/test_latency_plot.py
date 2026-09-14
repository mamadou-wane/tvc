import json
from pathlib import Path
import tempfile
import unittest
from scripts import plot_jitter


class LatencyPlots(unittest.TestCase):
    def fixture(self,p,mode='freerun'):
        s=dict(mode=mode,config='synthetic fixture')
        for name,count in (('latency',100),('uplink_wait',100),('vehicle_compute',100),('discard_age',7)):
            s[name+'_us']={'count':count,'p99.9':40 if name=='latency' else 30}
            (p/('L8.r1.'+name+'.csv')).write_text(
                'Value,Percentile,TotalCount,1/(1-Percentile)\n'
                f'10,0.5,1,2\n40,0.99,{count-1},100\n40,1.0,{count},inf\n')
        (p/'L8.r1.summary.json').write_text(json.dumps(s))

    def test_populations_counts_and_diagnostic_labels(self):
        self.assertTrue(hasattr(plot_jitter,'latency_series'))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p)
            series=plot_jitter.latency_series(p)
            self.assertEqual([r['population'] for r in series],['latency','uplink_wait','vehicle_compute','discard_age'])
            self.assertEqual([r['count'] for r in series],[100,100,100,7])
            self.assertEqual(series[0]['p999_us'],40)
            self.assertNotEqual(series[0]['p999_us'],series[1]['p999_us']+series[2]['p999_us'])
            self.assertTrue(all('diagnostic' in r['label'] for r in series))
            self.fixture(p,'new-mode')
            self.assertTrue(all('mode unknown' in r['label'] for r in plot_jitter.latency_series(p)))
            output=p/'test.svg'
            self.assertEqual(plot_jitter.main(['--results',d,'--latency','--out',str(output)]),0)
            text=output.read_text()
            for word in ('served','uplink wait','vehicle compute','discard','diagnostic'):
                self.assertIn(word,text)
            self.assertTrue(output.with_suffix('.png').is_file())

    def test_missing_population_and_bad_csv_fail(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p)
            for text in ('bad\n','Value,Percentile,TotalCount\nnan,0.5,99\n',
                         'Value,Percentile,TotalCount\n10,.9,20\n9,1,100\n',
                         'Value,Percentile,TotalCount\n10,1,99\n'):
                (p/'L8.r1.latency.csv').write_text(text)
                with self.assertRaises(ValueError):plot_jitter.latency_series(p)
            self.fixture(p);(p/'L8.r1.uplink_wait.csv').unlink()
            with self.assertRaises((ValueError,OSError)):plot_jitter.latency_series(p)

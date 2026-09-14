"""Visualization fixtures describe input records, not a second simulation."""
import importlib
import unittest
from pathlib import Path


def fixture():
    controls=[dict(tick=k,theta=.01,cmd=.02,staleness=0,state=0 if k<50 else 1 if k<110 else 2,reason=0)
              for k in range(3000)]
    controls[-1].update(state=3,reason=1)
    return dict(controls=controls,theta=[.03]*3000,
                up_lost=[200,220],down_lost=[201,239],facts=dict(seed=20260902))


class Frames(unittest.TestCase):
    def test_renderer_exists(self):
        self.assertTrue((Path(__file__).resolve().parents[2]/'scripts/render_demo.py').is_file())

    def test_frames_reveal_only_their_twenty_tick_window_and_history(self):
        render=importlib.import_module('scripts.render_demo')
        data=fixture()
        expected=[(0,19,0,[],[]),(2,59,1,[],[]),(3,79,1,[],[]),
                  (9,199,2,[],[]),(10,219,2,[200],[201]),
                  (11,239,2,[200,220],[201,239]),(149,2999,3,[200,220],[201,239])]
        for frame,tick,state,up,down in expected:
            got=render.frame_view(data,frame)
            self.assertEqual((got['tick'],got['state'],got['up_lost'],got['down_lost']),
                             (tick,state,up,down))
            self.assertEqual(got['stop'],tick+1)
        for invalid in (-1,150,True):
            with self.assertRaises(ValueError):render.frame_view(data,invalid)

    def test_changed_scenario_is_refused_before_launch(self):
        import json
        import tempfile
        from unittest.mock import patch
        from scripts import demo
        document=demo.manifest_document()
        with tempfile.TemporaryDirectory() as d:
            scenario=Path(d)/'demo-loss30.json'
            content=json.loads(demo.SCENARIO.read_text());content['ticks']=1
            scenario.write_text(json.dumps(content))
            with patch.object(demo,'SCENARIO',scenario),patch.object(demo.run_campaign,'toolchain_info',return_value=document['toolchain']),patch.object(demo.run_scenario,'run_case',return_value={'eligible':True}) as run:
                with self.assertRaisesRegex(ValueError,'scenario'):
                    demo.run_demo(Path(d)/'out',binary=Path('/unused'),data_only=True)
                run.assert_not_called()

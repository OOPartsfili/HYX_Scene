import copy
import json
from pathlib import Path
import unittest
from scene_studio.schema import validate,triggered,look_values

ROOT=Path(__file__).resolve().parents[1]

class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.scene=json.loads((ROOT/'scene_studio/templates/Scene1_01.json').read_text(encoding='utf-8'))
    def test_all_migrated_templates(self):
        for path in (ROOT/'scene_studio/templates').glob('*.json'):
            with self.subTest(path=path.name):validate(json.loads(path.read_text(encoding='utf-8')))
    def test_invalid_coordinates_rejected(self):
        for v in (float('nan'),float('inf'),True,100001):
            self.scene['actors'][0]['x']=v
            with self.assertRaises(ValueError):validate(self.scene)
    def test_dangling_actor_rejected(self):
        self.scene['actors']=self.scene['actors'][1:]
        self.scene['events'].append({'id':'missing','trigger':{'type':'time','value':0},'action':{'type':'speed','actor':'car1','value':10}})
        with self.assertRaises(ValueError):validate(self.scene)
    def test_cycle_rejected(self):
        self.scene['events']=[{'id':'a','trigger':{'type':'after_event','event':'b'},'action':{'type':'marker'}},{'id':'b','trigger':{'type':'after_event','event':'a'},'action':{'type':'marker'}}]
        with self.assertRaises(ValueError):validate(self.scene)
    def test_trigger_boundaries_and_absent_actor(self):
        states={'a':{'x':0,'y':4,'speed':10},'b':{'x':3,'y':8,'speed':0}}
        self.assertTrue(triggered({'type':'distance','actor':'a','target':'b','value':5,'op':'<='},0,states,{}))
        self.assertFalse(triggered({'type':'distance','actor':'a','target':'c','value':5,'op':'<='},0,states,{}))
        self.assertFalse(triggered({'type':'after_event','event':'a','value':2},9,states,{'a':8}))
        self.assertTrue(triggered({'type':'after_event','event':'a','value':2},10,states,{'a':8}))
    def test_disabled_event_data_preserved(self):
        self.scene['events'][0]['enabled']=False
        self.assertFalse(validate(self.scene)['events'][0]['enabled'])
    def test_validation_and_presets_do_not_mutate_source(self):
        original=copy.deepcopy(self.scene);validate(self.scene);self.assertEqual(original,self.scene)
        p=look_values({'preset':'daylight','weather':{'wetness':88}})
        self.assertEqual(p['weather']['wetness'],88)
        self.assertEqual(look_values({'preset':'daylight'})['weather']['wetness'],0)
    def test_delayed_ego_rejected(self):
        next(a for a in self.scene['actors'] if a['id']==self.scene['ego'])['spawn_at_start']=False
        with self.assertRaises(ValueError):validate(self.scene)
    def test_negative_time_and_unbounded_follow_rejected(self):
        for trigger,action in [({'type':'time','value':-1},{'type':'marker'}),({'type':'time','value':0},{'type':'follow','actor':'ego','target':'car1','reaction':99})]:
            self.scene['events']=[{'id':'e','trigger':trigger,'action':action}]
            with self.assertRaises(ValueError):validate(self.scene)

    def test_imported_short_lane_and_dead_end_do_not_index_empty_next(self):
        from scene_studio.routing import MapDAO
        from types import SimpleNamespace as N
        class Point:
            def __init__(self,x):self.x=x;self.y=0;self.z=0
            def distance(self,p):return abs(self.x-p.x)
        def wp(x,id):return N(id=id,road_id=1,section_id=0,lane_id=-1,transform=N(location=Point(x)),next=lambda resolution:[])
        world_map=N(get_topology=lambda:[(wp(0,1),wp(.5,2)),(wp(10,3),wp(20,4))])
        rows=MapDAO(world_map,2).get_topology()
        self.assertEqual(len(rows),2)
        self.assertEqual([r['path'] for r in rows],[[],[]])

if __name__=='__main__':unittest.main()

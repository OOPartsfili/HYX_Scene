import copy,json,tempfile,unittest
from pathlib import Path
from scene_studio.timeline import motion_at,motion_hash,ControlOwner,preset,pose_on_path
from scene_studio.schema import validate
from scene_studio.recording import Recording,RecordingWriter
ROOT=Path(__file__).resolve().parents[1]
class TimelineTests(unittest.TestCase):
    def setUp(self):self.scene=validate(json.loads((ROOT/'scene_studio/templates/Scene1_01.json').read_text(encoding='utf-8')))
    def test_speed_curve_and_lane_curve_are_independent(self):
        a={'speed':20,'offset':0,'clips':[{'id':'speed','type':'speed','start':2,'duration':4,'value':60},{'id':'lane','type':'lane_change','start':3,'duration':2,'direction':'left','lanes':1}]}
        self.assertEqual(motion_at(a,1)['speed'],20)
        self.assertEqual(motion_at(a,4)['speed'],40)
        self.assertAlmostEqual(motion_at(a,4)['offset'],1.75)
        self.assertEqual(motion_at(a,8)['offset'],3.5)
        self.assertEqual(motion_at(a,8)['speed'],60)
    def test_takeover_sticky_and_stale_packets_rejected(self):
        g=ControlOwner();epoch=g.take('keyboard',0)
        self.assertTrue(g.packet({'epoch':epoch,'seq':1,'throttle':.7,'steer':.1,'brake':0},.1))
        self.assertEqual(g.output(.2)['throttle'],.7)
        self.assertEqual(g.output(.6)['brake'],1)
        self.assertEqual(g.owner,'keyboard')
        self.assertFalse(g.packet({'epoch':epoch,'seq':0},.61))
        g.release();self.assertFalse(g.packet({'epoch':epoch,'seq':2,'throttle':1},.7));self.assertIsNone(g.output(.8))
    def test_new_manual_owner_invalidates_prior_input(self):
        g=ControlOwner();old=g.take('keyboard',0);new=g.take('gamepad',1)
        self.assertNotEqual(old,new);self.assertFalse(g.packet({'epoch':old,'seq':100},1.1))
        self.assertTrue(g.packet({'epoch':new,'seq':1,'throttle':1,'brake':.3},1.2));self.assertEqual(g.output(1.3)['throttle'],0)
    def test_overlapping_speed_and_brake_rejected(self):
        self.scene['actors'][0]['clips']=[{'id':'a','type':'speed','start':1,'duration':4,'value':30},{'id':'b','type':'brake','start':4,'duration':2,'value':1}]
        with self.assertRaises(ValueError):validate(self.scene)
    def test_pose_interpolation_uses_short_yaw_arc(self):
        p=pose_on_path([[0,0,0,0,179],[10,10,0,0,-179]],5)
        self.assertEqual(p['x'],5);self.assertEqual(p['yaw'],180)
    def test_motion_hash_ignores_look_but_catches_tracks(self):
        h=motion_hash(self.scene);self.scene['look']['preset']='golden';self.scene['camera']['fov']=90;self.assertEqual(h,motion_hash(self.scene))
        self.scene['actors'][0]['speed']+=1;self.assertNotEqual(h,motion_hash(self.scene))
    def test_recording_roundtrip_and_locked_scene(self):
        with tempfile.TemporaryDirectory() as folder:
            writer=RecordingWriter(folder,self.scene,{'cloudiness':0})
            row={'ego':{'x':1,'y':2,'z':3,'yaw':4,'pitch':0,'roll':0,'speed':20,'carla_id':5,'id':'ego'}}
            writer.append(0,row,{'owner':'auto'});row['ego']['x']=2;writer.append(.05,row,{'owner':'auto'});writer.close()
            rec=Recording(folder);self.assertEqual(rec.at(.05)['actors']['ego']['x'],2);self.assertTrue(rec.verify(self.scene))
            self.scene['look']['preset']='golden';self.assertTrue(rec.verify(self.scene))
            self.scene['actors'][0]['y']+=1
            with self.assertRaises(ValueError):rec.verify(self.scene)
            rec.close()
    def test_follow_preset_requires_another_actor(self):
        a=self.scene['actors'][0]
        with self.assertRaises(ValueError):preset('follow',a,20,a['id'])
        result=preset('follow',a,20,'ego');self.assertEqual(result['clips'][0]['duration'],20)
if __name__=='__main__':unittest.main()

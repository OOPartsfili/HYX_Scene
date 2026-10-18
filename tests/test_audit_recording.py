"""Regression tests for recording integrity and route/preview boundary defects."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from scene_studio.recording import Recording, RecordingWriter, _legacy_motion_hash


def scene(duration=1.):
    return {'map':'test-map','duration':duration,'dt':.05,'ego':'ego','actors':[
        {'id':'ego','name':'主车','model':'vehicle.test','x':0.,'y':0.,'z':0.,'yaw':0.,
         'speed':3.6,'offset':0.,'acceleration':2.5,'deceleration':6.,'behavior':'scripted',
         'start_in_motion':True,'spawn_at_start':True,'route':[],'clips':[]}], 'events':[]}


def pose(x=0.):
    return {'ego':{'x':x,'y':0.,'z':0.,'yaw':0.,'pitch':0.,'roll':0.,'speed':3.6}}


class RecordingIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)

    def write(self, duration=.1):
        spec=scene(duration)
        writer=RecordingWriter(self.folder,spec,{'cloudiness':0})
        times=[i*.05 for i in range(int(duration/.05)+1)]
        if times[-1]<duration-1e-8:times.append(duration)
        for index,t in enumerate(times):writer.append(t,pose(index),{'owner':'auto'})
        writer.close()
        return spec

    def mutate_rows(self, callback, legacy=False):
        path=self.folder/'trajectory.jsonl'
        rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        callback(rows)
        path.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
        if legacy:
            header=json.loads((self.folder/'take.json').read_text(encoding='utf-8'))
            header['version']=1;header.pop('trajectory_sha256',None)
            (self.folder/'take.json').write_text(json.dumps(header),encoding='utf-8')

    def assert_invalid(self):
        with self.assertRaises(ValueError):Recording(self.folder)

    def test_fractional_final_step_replays_last_frame(self):
        self.write(.11)
        rec=Recording(self.folder);self.addCleanup(rec.close)
        self.assertEqual(rec.at(.11)['t'],.11)
        self.assertEqual(rec.at(.11)['actors']['ego']['x'],3)
        self.assertEqual(rec.at(-1)['t'],0)
        self.assertEqual(rec.at(99)['t'],.11)

    def test_same_line_count_pose_corruption_is_rejected_by_checksum(self):
        self.write()
        self.mutate_rows(lambda rows:rows[1]['actors']['ego'].update(x=999))
        self.assert_invalid()

    def test_legacy_timestamp_gap_and_duplicate_are_rejected(self):
        for t in (.075,0.):
            with self.subTest(t=t):
                self.write()
                self.mutate_rows(lambda rows:rows[1].update(t=t),legacy=True)
                self.assert_invalid()

    def test_legacy_nonfinite_pose_and_missing_pose_field_are_rejected(self):
        for mutate in (lambda rows:rows[1]['actors']['ego'].update(x=float('nan')),
                       lambda rows:rows[1]['actors']['ego'].pop('yaw')):
            self.write();self.mutate_rows(mutate,legacy=True);self.assert_invalid()

    def test_missing_ego_and_unknown_actor_are_rejected(self):
        for mutate in (lambda rows:rows[1]['actors'].pop('ego'),
                       lambda rows:rows[1]['actors'].update(unknown=copy.deepcopy(rows[1]['actors']['ego']))):
            self.write();self.mutate_rows(mutate,legacy=True);self.assert_invalid()

    def test_truncated_stream_and_malformed_json_are_rejected(self):
        self.write();self.mutate_rows(lambda rows:rows.pop(),legacy=True);self.assert_invalid()
        self.write()
        (self.folder/'trajectory.jsonl').write_text('{}\nnot-json\n{}\n',encoding='utf-8')
        self.assert_invalid()

    def test_bad_header_timing_and_scene_mutation_are_rejected(self):
        for mutate in (lambda h:h.update(dt=0),lambda h:h.update(frame_count=1),
                       lambda h:h['scene']['actors'][0].update(speed=99)):
            self.write()
            path=self.folder/'take.json';header=json.loads(path.read_text(encoding='utf-8'))
            mutate(header);path.write_text(json.dumps(header),encoding='utf-8');self.assert_invalid()

    def test_old_hash_recording_can_be_verified_with_current_hash(self):
        from scene_studio.timeline import motion_hash
        spec=scene(.1)
        spec['events']=[{'id':'cue','trigger':{'type':'time','value':.01},'action':{'type':'marker'}},
                        {'id':'speed','trigger':{'type':'after_event','event':'cue','value':.01},
                         'action':{'type':'speed','actor':'ego','value':10}}]
        writer=RecordingWriter(self.folder,spec,{})
        for t in (0,.05,.1):writer.append(t,pose(),{'owner':'auto'})
        writer.close()
        path=self.folder/'take.json';header=json.loads(path.read_text(encoding='utf-8'))
        header['version']=1;header['motion_hash']=_legacy_motion_hash(header['scene'])
        self.assertNotEqual(header['motion_hash'],motion_hash(spec))
        path.write_text(json.dumps(header),encoding='utf-8')
        rec=Recording(self.folder);self.addCleanup(rec.close)
        self.assertTrue(rec.verify(spec))
        changed=copy.deepcopy(spec);changed['actors'][0]['speed']+=1
        with self.assertRaises(ValueError):rec.verify(changed)
        changed=copy.deepcopy(spec);changed['events'][0]['trigger']['value']=.02
        with self.assertRaises(ValueError):rec.verify(changed)

    def test_writer_rejects_invalid_frame_without_appending_it(self):
        writer=RecordingWriter(self.folder,scene(),{})
        writer.append(0,pose(),{'owner':'auto'})
        with self.assertRaises(ValueError):writer.append(.1,pose(),{'owner':'auto'})
        writer.append(.05,pose(1),{'owner':'auto'})
        header=writer.close()
        self.assertEqual(header['frame_count'],2)
        self.assertFalse(header['covers_scene_duration'])
        rec=Recording(self.folder);self.addCleanup(rec.close)
        self.assertEqual(rec.at(.05)['actors']['ego']['x'],1)

    def test_writer_freezes_scene_metadata_and_nan_replay_time_is_rejected(self):
        spec=scene();writer=RecordingWriter(self.folder,spec,{})
        spec['actors'][0]['speed']=99
        writer.append(0,pose(),{'owner':'auto'});writer.append(.05,pose(1),{'owner':'auto'})
        header=writer.close();self.assertEqual(header['scene']['actors'][0]['speed'],3.6)
        rec=Recording(self.folder);self.addCleanup(rec.close)
        with self.assertRaises(ValueError):rec.at(float('nan'))


class PlannerBoundaryTests(unittest.TestCase):
    @staticmethod
    def road():
        import carla
        def wp(x):
            return SimpleNamespace(id=round(x*100),road_id=1,lane_id=-1,lane_width=3.5,
                transform=carla.Transform(carla.Location(x=x)),next=lambda distance:[wp(x+distance)] if x<2000 else [])
        return SimpleNamespace(get_waypoint=lambda location:wp(0))

    def test_event_speed_extends_physical_route_beyond_initial_speed_budget(self):
        from scene_studio.planning import Planner
        spec=scene(30);spec['actors'][0]['speed']=0
        spec['events']=[{'id':'accelerate','enabled':True,'trigger':{'type':'time','value':1},'action':{'actor':'ego','type':'speed','value':36}}]
        result=Planner(self.road()).compile(spec)
        self.assertGreaterEqual(result['tracks']['ego']['path'][-1][0],325)
        self.assertTrue(any('条件事件' in warning for warning in result['warnings']))

    def test_free_walker_preview_keeps_walking_in_initial_direction(self):
        from scene_studio.planning import Planner
        spec=scene(2);actor=spec['actors'][0]
        actor.update(model='walker.pedestrian.0001',behavior='walker',yaw=90)
        frames=Planner(self.road()).compile(spec)['tracks']['ego']['frames']
        self.assertAlmostEqual(frames[-1][1],0.,places=6)
        self.assertAlmostEqual(frames[-1][2],2.,places=6)
        self.assertAlmostEqual(frames[-1][5],3.6)

    def test_parked_preview_stays_at_placement_despite_stale_offset_and_speed(self):
        from scene_studio.planning import Planner
        spec=scene();spec['actors'][0].update(behavior='parked',offset=3.5,speed=40)
        frames=Planner(self.road()).compile(spec)['tracks']['ego']['frames']
        self.assertTrue(all(frame[1:3]==[0.,0.] and frame[5]==0 for frame in frames))


if __name__=='__main__':unittest.main()

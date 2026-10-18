"""Regression cases for runtime failures observed during the code audit."""
import csv
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import carla
import numpy as np
from scene_studio.engine import Session, StudioDriver
from scene_studio.runner import Driver


class EngineAuditTests(unittest.TestCase):
    def test_stale_or_other_scene_plan_is_rejected(self):
        from scene_studio.planning import plan_is_current,PLAN_VERSION
        from scene_studio.timeline import motion_hash
        scene={'map':'map10','duration':2,'dt':.05,'ego':'ego','actors':[],'events':[]}
        plan={'planner_version':PLAN_VERSION,'motion_hash':motion_hash(scene)}
        self.assertTrue(plan_is_current(plan,scene))
        self.assertFalse(plan_is_current({**plan,'planner_version':1},scene))
        self.assertFalse(plan_is_current(plan,{**scene,'duration':3}))

    def test_lights_window_restores_previous_state(self):
        driver=object.__new__(StudioDriver)
        driver.timeline=True;driver.timeline_follow=False;driver.timeline_lights_before=None
        driver.spec={'clips':[{'id':'light','type':'lights','start':1,'duration':2,'value':49}]}
        driver.track={'lane_width':3.5};driver.vice_car=Mock()
        driver.vice_car.get_light_state.return_value=carla.VehicleLightState.LowBeam
        driver.timeline_update(1,{})
        driver.timeline_update(3,{})
        self.assertEqual(driver.vice_car.set_light_state.call_args.args[0],carla.VehicleLightState.LowBeam)

    def test_unmapped_camera_frame_is_not_mislabeled(self):
        session=object.__new__(Session)
        session.closed=False;session.camera_generation=1;session.frame_times_map={};session.unmapped_camera_frames=0
        session.preview=False;session.first_recorded_frame=0
        session.on_frame(NS(frame=999),1)
        self.assertEqual(session.unmapped_camera_frames,1)

    @staticmethod
    def camera_session(folder,boundary,preview=False):
        session=object.__new__(Session)
        session.closed=False;session.camera_generation=1;session.preview=preview
        session.first_recorded_frame=boundary;session.frame_times_map={99:0,100:0,101:.05};session.recordable_frames={100,101} if not preview else set()
        session.unmapped_camera_frames=0;session.folder=Path(folder);session.image_lock=threading.Lock()
        session.status='preview' if preview else 'running';session.last_shot_second=-1;session.camera_samples=[]
        session.camera_time=-1;session.frame_count=0;session.frame_times=[];session.last_image_time=0
        return session

    def test_camera_rejects_frames_before_trial_boundary_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            session=self.camera_session(folder,None)
            session.on_frame(NS(frame=100),1)
            self.assertFalse(list(Path(folder).iterdir()))
            self.assertEqual(session.camera_time,-1)

    def test_camera_rejects_late_warmup_frame_after_status_running(self):
        with tempfile.TemporaryDirectory() as folder:
            session=self.camera_session(folder,100)
            session.on_frame(NS(frame=99),1)
            self.assertFalse(list(Path(folder).iterdir()))
            self.assertEqual(session.camera_samples,[])

    def test_camera_accepts_exact_first_telemetry_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            session=self.camera_session(folder,100)
            image=NS(frame=100,height=1,width=1,raw_data=bytes(4))
            with patch('scene_studio.engine.cv2.imencode',return_value=(True,np.frombuffer(b'jpeg',dtype=np.uint8))):
                session.on_frame(image,1)
            self.assertEqual(session.camera_samples,[{'file':'shot_0000000.jpg','time':0,'frame':100}])
            self.assertEqual((Path(folder)/'shot_0000000.jpg').read_bytes(),b'jpeg')

    def test_camera_first_available_trial_image_keeps_actual_time(self):
        with tempfile.TemporaryDirectory() as folder:
            session=self.camera_session(folder,100)
            image=NS(frame=101,height=1,width=1,raw_data=bytes(4))
            with patch('scene_studio.engine.cv2.imencode',return_value=(True,np.frombuffer(b'jpeg',dtype=np.uint8))):
                session.on_frame(image,1)
            self.assertEqual(session.camera_samples,[{'file':'shot_0000050.jpg','time':.05,'frame':101}])

    def test_preview_without_trial_boundary_can_seek_backwards(self):
        with tempfile.TemporaryDirectory() as folder:
            session=self.camera_session(folder,None,preview=True)
            session.frame_times_map={99:7.25,100:2.5}
            with patch('scene_studio.engine.cv2.imencode',return_value=(True,np.frombuffer(b'jpeg',dtype=np.uint8))):
                session.on_frame(NS(frame=99,height=1,width=1,raw_data=bytes(4)),1)
                self.assertEqual(session.camera_time,7.25)
                session.on_frame(NS(frame=100,height=1,width=1,raw_data=bytes(4)),1)
            self.assertEqual(session.camera_time,2.5)
            self.assertTrue((Path(folder)/'frame.jpg').exists())
            self.assertFalse(list(Path(folder).glob('shot_*.jpg')))

    def test_camera_boundary_is_rechecked_inside_write_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            session=self.camera_session(folder,100)
            class ChangedBoundary:
                def __enter__(self):session.first_recorded_frame=101
                def __exit__(self,*args):return False
            session.image_lock=ChangedBoundary()
            image=NS(frame=100,height=1,width=1,raw_data=bytes(4))
            with patch('scene_studio.engine.cv2.imencode',return_value=(True,np.frombuffer(b'jpeg',dtype=np.uint8))):
                session.on_frame(image,1)
            self.assertFalse(list(Path(folder).iterdir()))
            self.assertEqual(session.camera_time,-1)

    def test_paused_frame_arriving_after_resume_never_becomes_trial_shot(self):
        with tempfile.TemporaryDirectory() as folder:
            session=self.camera_session(folder,100)
            session.frame_times_map[121]=1.0;session.last_shot_second=0
            session.status='running'  # Callback arrives only after resume.
            image=NS(frame=121,height=1,width=1,raw_data=bytes(4))
            with patch('scene_studio.engine.cv2.imencode',return_value=(True,np.frombuffer(b'paused',dtype=np.uint8))):
                session.on_frame(image,1)
            self.assertEqual((Path(folder)/'frame.jpg').read_bytes(),b'paused')
            self.assertFalse(list(Path(folder).glob('shot_*.jpg')))
            self.assertEqual(session.camera_samples,[])
            self.assertEqual(session.last_shot_second,0)

    def test_recorded_frame_arriving_after_pause_keeps_its_actual_time(self):
        with tempfile.TemporaryDirectory() as folder:
            session=self.camera_session(folder,100)
            session.frame_times_map[120]=1.0;session.recordable_frames.add(120);session.last_shot_second=0
            session.status='paused'
            image=NS(frame=120,height=1,width=1,raw_data=bytes(4))
            with patch('scene_studio.engine.cv2.imencode',return_value=(True,np.frombuffer(b'recorded',dtype=np.uint8))):
                session.on_frame(image,1)
            self.assertEqual(session.camera_samples,[{'file':'shot_0001000.jpg','time':1.0,'frame':120}])

    def test_moving_tick_registers_image_eligibility_before_advance(self):
        with tempfile.TemporaryDirectory() as folder:
            session=self.camera_session(folder,100);session.elapsed=1.0;session.last_shot_second=0
            session.world=Mock();session.world.get_snapshot.side_effect=[NS(frame=119),NS(frame=120)]
            def advance(timeout):
                self.assertIn(120,session.recordable_frames)
                session.on_frame(NS(frame=120,height=1,width=1,raw_data=bytes(4)),1)
                return 120
            session.world.tick.side_effect=advance
            with patch('scene_studio.engine.cv2.imencode',return_value=(True,np.frombuffer(b'recorded',dtype=np.uint8))):
                result=session.tick(record_frame=True)
            self.assertEqual(result.frame,120)
            self.assertEqual(session.camera_samples,[{'file':'shot_0001000.jpg','time':1.0,'frame':120}])
            session.world.tick.assert_called_once_with(10)

    def test_paused_warmup_and_preview_ticks_are_not_recordable(self):
        for preview,record in ((False,False),(True,False),(True,True)):
            with self.subTest(preview=preview,record_frame=record):
                session=object.__new__(Session);session.preview=preview;session.elapsed=1.0
                session.recordable_frames=set();session.frame_times_map={};session.world=Mock()
                session.world.get_snapshot.side_effect=[NS(frame=119),NS(frame=120)];session.world.tick.return_value=120
                session.tick(record_frame=record)
                self.assertEqual(session.frame_times_map[120],1.0)
                self.assertEqual(session.recordable_frames,set())
                session.world.tick.assert_called_once_with(10)

    def verify_initial_recorded_boundary(self,replay):
        session=object.__new__(Session)
        session.start=Mock();session.initial_snapshot=NS(frame=200)
        session.recording=Mock() if replay else None;session.recorder=Mock()
        session.apply_replay=Mock();session.tick=Mock(return_value=NS(frame=201));session.snapshot=Mock()
        session.error=None;session.camera=None;session.closed=False;session.owned=[]
        session.world=Mock();session.world.get_snapshot.side_effect=AssertionError('must reuse the initial snapshot')
        session.original_weather=object();session.original_settings=object();session.write_status=Mock()
        session.records=[];session.fired={};session.collisions=[];session.override=False;session.camera_samples=[]
        session.unmapped_camera_frames=0;session.image_lock=threading.Lock();session.first_recorded_frame=None
        session.preview=False;session.recordable_frames=set()
        session.owner=NS(owner='auto',state=Mock(return_value={'owner':'auto'}))
        session.states={'ego':{'id':'ego','carla_id':1}};expected=201 if replay else 200
        with tempfile.TemporaryDirectory() as folder:
            session.folder=Path(folder)
            with patch('scene_studio.engine.runtime.STOP',NS(is_set=lambda:True)),patch('scene_studio.engine.runtime.shutdown'),patch('scene_studio.engine.weather_dict',return_value={}),patch('scene_studio.engine.atomic_json'):
                session.run()
            with (Path(folder)/'telemetry.csv').open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
        self.assertEqual(session.first_recorded_frame,expected)
        self.assertEqual(session.recordable_frames,{expected})
        self.assertEqual(int(rows[0]['frame']),expected)
        self.assertEqual(float(rows[0]['time']),0)
        self.assertEqual(session.tick.call_count,1 if replay else 0)
        self.assertEqual(session.apply_replay.call_count,1 if replay else 0)
        self.assertIsNone(session.error)

    def test_motion_boundary_matches_initial_telemetry_without_extra_tick(self):
        self.verify_initial_recorded_boundary(False)

    def test_environment_boundary_uses_existing_initial_replay_tick(self):
        self.verify_initial_recorded_boundary(True)

    def test_brake_keeps_route_steering(self):
        for brake in (0, .7):
            actor=Mock()
            actor.get_velocity.return_value=carla.Vector3D(x=5)
            driver=object.__new__(Driver)
            driver.manual=None;driver.brake_override=brake
            driver.vice_car=actor;driver.offset=driver.actual_offset=0
            driver._target_waypoint=Mock(return_value=object())
            driver._pid=Mock()
            driver._pid.run_step.return_value=carla.VehicleControl(steer=.32,throttle=.6)
            driver._step(.05,1)
            control=actor.apply_control.call_args.args[0]
            self.assertAlmostEqual(control.steer,.32,places=6)
            self.assertEqual(control.throttle,0)
            self.assertAlmostEqual(control.brake,brake,places=6)

    def test_camera_destroy_attempted_even_when_stop_raises(self):
        camera=Mock(is_alive=True)
        camera.stop.side_effect=RuntimeError('lost callback connection')
        camera.destroy.side_effect=lambda:setattr(camera,'is_alive',False) or True
        session=object.__new__(Session);session.camera=camera
        with self.assertRaisesRegex(RuntimeError,'stop:'):session.close_camera()
        camera.destroy.assert_called_once()
        self.assertIsNone(session.camera)

    def test_collision_uses_sensor_frame_not_callback_wall_time(self):
        session=object.__new__(Session)
        session.closed=False;session.elapsed=7.3;session.frame_times_map={101:2.15};session.collisions=[]
        event=NS(frame=101,other_actor=NS(type_id='vehicle.audi.a2',id=99),normal_impulse=carla.Vector3D(x=1))
        session.on_collision(event,'ego')
        self.assertEqual(session.collisions[0]['time'],2.15)
        event.frame=90;session.on_collision(event,'ego')
        self.assertIsNone(session.collisions[1]['time'])
        session.closed=True;session.on_collision(event,'ego')
        self.assertEqual(len(session.collisions),2)

    def test_settings_and_status_survive_other_cleanup_failures(self):
        session=object.__new__(Session)
        session.start=Mock(side_effect=RuntimeError('spawn failed'))
        session.error=None;session.camera=None;session.closed=False;session.owned=[]
        session.world=Mock();session.world.set_weather.side_effect=RuntimeError('weather RPC failed')
        session.original_weather=object();session.original_settings=object()
        session.recorder=Mock();session.recorder.close.side_effect=OSError('disk failure')
        session.recording=Mock();session.write_status=Mock()
        session.records=[];session.fired={};session.collisions=[];session.override=False;session.camera_samples=[]
        session.unmapped_camera_frames=0;session.image_lock=threading.Lock()
        with tempfile.TemporaryDirectory() as folder:
            session.folder=Path(folder)
            with patch('scene_studio.engine.runtime.shutdown'),patch('scene_studio.engine.weather_dict',return_value={}),patch('scene_studio.engine.atomic_json') as output:
                session.run()
            session.world.apply_settings.assert_called_once_with(session.original_settings)
            session.recording.close.assert_called_once()
            session.write_status.assert_called_once()
            self.assertEqual(session.status,'error')
            output.assert_called_once()


if __name__=='__main__':unittest.main()

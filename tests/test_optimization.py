"""离线回归测试：真实 CARLA 数据类型 + Pygame dummy 显示 + 模拟 world。"""
import ast
import csv
import importlib
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace as NS, ModuleType
import unittest
from unittest.mock import patch, Mock

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import carla
import pygame
import scene_runtime as runtime
from traffic_math import follow_speed, ramp_speed, ahead_distance, smoothstep
from optimization_config import camera_settings, ROOT
from optimized_control import Ramp_Vice_Control, Vehicle_Control, WorldVehicles
from Set_sensor import SensorManager

class WP:
    def __init__(self, x=0, y=0, road=1):
        self.transform = carla.Transform(carla.Location(x=x,y=y))
        self.road_id, self.section_id, self.lane_id = road, 0, round(y/3.5)
        self.lane_type = carla.LaneType.Driving
        self.lane_change = carla.LaneChange.Both
    def next(self, distance):
        return [WP(self.transform.location.x+distance,self.transform.location.y,self.road_id)]
    def get_left_lane(self):
        return WP(self.transform.location.x,self.transform.location.y-3.5) if self.transform.location.y > -7 else None
    def get_right_lane(self):
        return WP(self.transform.location.x,self.transform.location.y+3.5) if self.transform.location.y < 7 else None

class Actor:
    def __init__(self, world, actor_id=1, x=0, y=0, speed=0):
        self.world, self.id, self.is_alive = world, actor_id, True
        self.tf = carla.Transform(carla.Location(x=x,y=y))
        self.velocity = carla.Vector3D(x=speed)
        self.bounding_box = NS(extent=NS(x=2))
        self.control = carla.VehicleControl()
        self.commands = []
    def get_world(self): return self.world
    def get_transform(self): return self.tf
    def get_location(self): return self.tf.location
    def get_velocity(self): return self.velocity
    def get_acceleration(self): return carla.Vector3D()
    def get_control(self): return self.control
    def apply_control(self, control):
        self.control = control
        self.commands.append(control)

class World:
    id = 777
    def __init__(self):
        self.time, self.frame, self.scans = 0, 1, 0
        self.actors = []
    def get_map(self):
        return NS(get_waypoint=lambda loc: WP(loc.x,round(loc.y/3.5)*3.5))
    def get_actors(self):
        self.scans += 1
        return NS(filter=lambda pattern: self.actors)
    def get_snapshot(self):
        return NS(frame=self.frame,timestamp=NS(elapsed_seconds=self.time),
                  find=lambda actor_id: next((a for a in self.actors if a.id==actor_id),None))

class MathTests(unittest.TestCase):
    def test_following_stopped_obstacle_and_recovery(self):
        self.assertEqual(follow_speed(20,0,2),(0,True))
        speed, urgent = follow_speed(20,0,18)
        self.assertGreater(speed,0)
        self.assertLess(speed,20)
        self.assertFalse(urgent)
        self.assertEqual(follow_speed(20,20,100),(20,False))
    def test_bounded_acceleration_and_braking(self):
        self.assertAlmostEqual(ramp_speed(0,30,.05),.125)
        self.assertAlmostEqual(ramp_speed(20,0,.05),19.7)
        self.assertEqual(ramp_speed(0,0,.05),0)
    def test_projection_no_acos_or_overlap_division(self):
        p=carla.Location()
        self.assertEqual(ahead_distance(p,carla.Vector3D(x=1),p),0)
        self.assertLess(ahead_distance(p,carla.Vector3D(x=1),carla.Location(x=-1)),0)
    def test_lane_curve_endpoints(self):
        self.assertEqual(smoothstep(0),0)
        self.assertEqual(smoothstep(1),1)
        values=[smoothstep(i/100) for i in range(101)]
        self.assertEqual(values,sorted(values))

class ControlTests(unittest.TestCase):
    def setUp(self):
        runtime.STOP.clear()
        import optimized_control
        optimized_control._views.clear()
        self.world=World()
        self.ego=Actor(self.world,speed=10)
        self.world.actors=[self.ego]
    def test_scripted_initial_speed_is_seeded_only_once(self):
        self.ego.set_target_velocity=Mock()
        control=Ramp_Vice_Control(self.ego,behavior='scripted')
        control.speed_limit=50
        with patch('optimized_control.threading.Thread'):
            control.follow_road();control.follow_road()
        self.ego.set_target_velocity.assert_called_once()
        self.assertAlmostEqual(self.ego.set_target_velocity.call_args.args[0].x,50/3.6,places=5)
        control._step(.05,1)
        self.ego.set_target_velocity.assert_called_once()

    def test_ordinary_traffic_keeps_physical_standing_start(self):
        self.ego.set_target_velocity=Mock()
        control=Ramp_Vice_Control(self.ego,behavior='traffic')
        with patch('optimized_control.threading.Thread'):
            control.follow_road()
        self.ego.set_target_velocity.assert_not_called()

    def test_firetruck_limiter_matches_supplied_torque_curve(self):
        self.ego.type_id='vehicle.carlamotors.firetruck'
        physics=NS(max_rpm=5000,torque_curve=[carla.Vector2D(x=1000,y=2300),carla.Vector2D(x=2571,y=200)],mass=10000)
        self.ego.get_physics_control=lambda:physics
        self.ego.apply_physics_control=Mock()
        Ramp_Vice_Control(self.ego,behavior='scripted')
        self.assertEqual(physics.max_rpm,2571)
        self.assertEqual(physics.mass,10000)
        self.ego.apply_physics_control.assert_called_once()
    def test_obstacle_on_first_step_brakes_without_unbound_waypoint(self):
        lead=Actor(self.world,2,x=5)
        self.world.actors.append(lead)
        control=Ramp_Vice_Control(self.ego)
        control._step(.05,0)
        self.assertEqual(self.ego.control.brake,1)
        self.assertEqual(self.ego.control.throttle,0)
    def test_scan_shared_and_different_roads_excluded(self):
        self.world.actors.append(Actor(self.world,2,x=20))
        view=WorldVehicles(self.world)
        view.nearby(self.ego); view.nearby(self.ego)
        self.assertEqual(self.world.scans,1)
        self.world.time=.11
        view.nearby(self.ego)
        self.assertEqual(self.world.scans,2)
        view.rows[1]=(self.world.actors[1],self.world.actors[1].tf,WP(20,0,road=2))
        self.assertEqual(view.nearby(self.ego),[])
    def test_scripted_actor_not_overridden_by_background_following(self):
        self.world.actors.append(Actor(self.world,2,x=5))
        control=Ramp_Vice_Control(self.ego,behavior='scripted')
        self.assertEqual(control._desired_speed(0),(50/3.6,False))
    def test_follow_car_honors_reaction_delay(self):
        lead=Actor(self.world,2,x=100,speed=10)
        control=Ramp_Vice_Control(self.ego)
        control._lead,control._reaction_time,control._min_gap=lead,.8,.5
        self.assertGreater(control._desired_speed(0)[0],10)
        lead.tf.location=carla.Location(x=4.1)
        self.assertFalse(control._desired_speed(.2)[1])
        self.assertTrue(control._desired_speed(1.01)[1])
    def test_invalid_lane_does_not_suspend_control(self):
        control=Ramp_Vice_Control(self.ego)
        self.assertFalse(control.right_left_lane(direction='none'))
        self.assertTrue(control.flag)
        self.ego.tf.location=carla.Location(y=-7)
        self.assertFalse(control.right_left_lane(direction='left'))
        self.assertTrue(control.flag)
    def test_lane_change_timeout_and_overshoot(self):
        control=Ramp_Vice_Control(self.ego)
        control._lane_change=(WP(),WP(0,3.5),20,0)
        self.ego.tf.location=carla.Location(x=25,y=3.5)
        self.assertIsNotNone(control._target_waypoint(2))
        self.assertTrue(control.last_lane_change_ok)
        control._lane_change=(WP(),WP(0,3.5),20,0)
        self.assertIsNone(control._target_waypoint(13))
        self.assertFalse(control.last_lane_change_ok)
    def test_takeover_cancels_lane_change(self):
        control=Vehicle_Control(self.ego)
        control.autopilot_flag=False
        control._lane_change=(WP(),WP(0,3.5),20,0)
        module=ModuleType('vehicle_method')
        module.get_steering_wheel_info=lambda:(.2,1,.7)
        with patch.dict(sys.modules,vehicle_method=module), patch('keyboard.is_pressed',return_value=False):
            control._step(.05,1)
        self.assertIsNone(control._lane_change)
        self.assertEqual(self.ego.control.throttle,0)
        self.assertAlmostEqual(self.ego.control.brake,.7)
    def test_pid_zero_distance_has_finite_steering(self):
        control=Ramp_Vice_Control(self.ego)
        result=control._pid.run_step(20,WP())
        self.assertTrue(math.isfinite(result.steer))

class CameraTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        pygame.display.set_mode((8,8))
        self.options={}
        bp=NS(has_attribute=lambda key:True,set_attribute=lambda key,value:self.options.update({key:value}))
        self.sensor=NS(is_alive=True,listen=lambda callback:None,stop=lambda:None,destroy=lambda:None)
        self.world=NS(get_blueprint_library=lambda:NS(find=lambda name:bp),spawn_actor=lambda *a,**k:self.sensor)
        self.display=NS(add_sensor=lambda sensor:None,get_display_size=lambda:[2,1],
            display=pygame.display.get_surface(),get_display_offset=lambda pos:[0,0])
    def make(self,yaw=0,options=None):
        return SensorManager(self.world,self.display,'RGBCamera',carla.Transform(rotation=carla.Rotation(yaw=yaw)),
            None,options or {},[0,0],[[0,0],[2,1]])
    def test_native_front_preserved_and_mirrors_capped(self):
        with patch.dict(os.environ,HYX_RENDER_PROFILE='quality'):
            self.make()
            self.assertAlmostEqual(float(self.options['sensor_tick']),1/60)
            self.make(180)
            self.assertAlmostEqual(float(self.options['sensor_tick']),1/30)
    def test_latest_frame_color_and_mirror_not_fov(self):
        camera=self.make(180,{'fov':'90'})
        raw=bytes([0,0,255,255,255,0,0,255])
        camera.save_rgb_image(NS(frame=1,raw_data=raw,width=2,height=1))
        latest=NS(frame=2,raw_data=raw,width=2,height=1)
        camera.save_rgb_image(latest)
        camera.save_rgb_image(NS(frame=1))
        self.assertIs(camera._pending[0],latest)
        camera.render()
        self.assertEqual(tuple(camera.surface.get_at((0,0)))[:3],(0,0,255))
        self.assertEqual(tuple(camera.surface.get_at((1,0)))[:3],(255,0,0))
        self.assertIsNone(camera._pending)
    def test_forward_fov120_not_flipped(self):
        camera=self.make(0,{'fov':'120'})
        self.assertFalse(camera.mirror)
    def test_shutdown_drops_late_callback(self):
        camera=self.make()
        camera.destroy(); camera.destroy()
        camera.save_rgb_image(NS(frame=3))
        self.assertIsNone(camera._pending)
    def test_balanced_resizes_capture_only(self):
        with patch.dict(os.environ,HYX_RENDER_PROFILE='balanced'):
            size,interval=camera_settings((5740,1010),False)
            self.assertEqual(size,(4305,758))
            self.assertAlmostEqual(interval,1/60)

class CsvTests(unittest.TestCase):
    def test_streamed_rows_frame_alignment_and_idempotent_save(self):
        runtime.STOP.clear()
        world=World(); world.actors=[Actor(world)]
        module=ModuleType('vehicle_method')
        module.world=world
        module.get_steering_wheel_info=lambda:(.1,.2,.3)
        with patch.dict(sys.modules,vehicle_method=module):
            sys.modules.pop('Set_info',None)
            info_module=importlib.import_module('Set_info')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'data.csv'
            info=info_module.Info({0:'main_car'},info_module.dict_0,path,fps=20)
            info.car_list=[world.actors[0]]
            info.get_info()
            time.sleep(.075)
            world.frame=2;world.time=.05
            time.sleep(.075)
            info.save_info();info.save_info()
            with path.open(encoding='utf-8') as handle:
                rows=list(csv.DictReader(handle))
            self.assertEqual(len(rows),2)
            self.assertEqual([r['frame'] for r in rows],['1','2'])
            self.assertTrue(all(None not in r for r in rows))
            self.assertEqual(rows[1]['main_car_id'],'1')
            self.assertEqual(info_module.dict_0['time'],[])

class WiringTests(unittest.TestCase):
    def test_seven_scenes_preserve_experimental_target_parameters(self):
        scenes=[*ROOT.glob('Scene1_0*.py'),ROOT/'Scene2.py']
        self.assertEqual(len(scenes),7)
        for path in scenes:
            def targets(text):
                result=[]
                for node in ast.walk(ast.parse(text)):
                    if isinstance(node,ast.Assign) and isinstance(node.value,ast.Constant):
                        for target in node.targets:
                            if isinstance(target,ast.Attribute) and target.attr in ('speed_limit','autopilot_speed_limit','lane_offset','stage_flag'):
                                result.append((ast.unparse(target),node.value.value))
                return sorted(result)
            current=path.read_text(encoding='utf-8')
            baseline=(ROOT/'optimization_backup'/'20261001'/path.name).read_text(encoding='utf-8')
            self.assertEqual(targets(current),targets(baseline),path.name)
            self.assertIn('runtime.shutdown()',current)
            self.assertNotIn('os._exit',current)
            self.assertIn('role_name="hero"',current)

class BackgroundTests(unittest.TestCase):
    def test_zero_background_does_not_create_tm(self):
        from background_traffic import BackgroundTraffic
        ego=Actor(World())
        traffic=BackgroundTraffic(NS(),ego,count=0)
        self.assertEqual(traffic.actors,[])
        traffic.stop()

    def test_tm_configures_owned_cars_and_cleanup(self):
        from background_traffic import BackgroundTraffic
        calls=[]
        class TM:
            def __getattr__(self,key):
                return lambda *args:calls.append((key,args))
        tm=TM()
        bp=NS(has_attribute=lambda key:key in ('number_of_wheels','role_name'),
              get_attribute=lambda key:4,set_attribute=lambda *args:None)
        class TrafficActor(Actor):
            def set_autopilot(self,*args):calls.append(('autopilot',args))
            def destroy(self):self.is_alive=False
        world=World()
        world.get_settings=lambda:NS(synchronous_mode=False)
        world.get_blueprint_library=lambda:NS(filter=lambda pattern:[bp])
        world.get_map=lambda:NS(get_spawn_points=lambda:[carla.Transform(carla.Location(x=x)) for x in (10,80,100,130)])
        spawned=[]
        def spawn(bp,tf):
            actor=TrafficActor(world,len(spawned)+2,x=tf.location.x)
            spawned.append(actor)
            return actor
        world.try_spawn_actor=spawn
        ego=Actor(world);ego.attributes={'role_name':'hero'};world.actors=[ego]
        traffic=BackgroundTraffic(NS(get_trafficmanager=lambda port:tm),ego,count=2)
        self.assertEqual(len(traffic.actors),2)
        self.assertTrue(all(a.get_location().x>=60 for a in traffic.actors))
        self.assertEqual(sum(key=='autopilot' for key,args in calls),2)
        self.assertIn(('set_hybrid_physics_mode',(False,)),calls)
        traffic.stop()
        self.assertTrue(all(not a.is_alive for a in spawned))
        self.assertTrue(ego.is_alive)

class LifecycleTests(unittest.TestCase):
    def tearDown(self):
        runtime.STOP.clear()

    def test_listener_joined_before_input_subsystem_closes(self):
        runtime.STOP.clear()
        listener=threading.Thread(target=lambda:runtime.STOP.wait(2))
        listener.start()
        input_close=NS(destroy=lambda:self.assertFalse(listener.is_alive()))
        with patch.object(runtime,'_resources',[]),patch.object(runtime,'_closed',False),patch.object(runtime,'write_metrics',return_value='test'):
            runtime.register_thread(listener)
            runtime.register(input_close,'destroy')
            runtime.shutdown()

    def test_bad_font_registry_is_attempted_only_once(self):
        import display_font
        with patch.object(display_font,'_use_file',False),patch.object(pygame.font,'SysFont',side_effect=TypeError('non-string registry value')) as registry,patch.object(pygame.font,'Font',return_value=object()) as file_font:
            display_font.arial(50);display_font.arial(50)
            registry.assert_called_once()
            self.assertEqual(file_font.call_count,2)

    def test_camera_registered_during_window_stop_is_destroyed(self):
        camera=NS(destroy=Mock())
        window=NS(stop=lambda:runtime.register(camera,'destroy'))
        with patch.object(runtime,'_resources',[(window,'stop')]),patch.object(runtime,'_closed',False),patch.object(runtime,'write_metrics',return_value='test'):
            runtime.shutdown()
        camera.destroy.assert_called_once()

    def test_failed_actor_destroy_is_reported_and_others_still_run(self):
        failed=NS(destroy=Mock(return_value=False))
        good=NS(destroy=Mock(return_value=True))
        with patch.object(runtime,'_resources',[(good,'destroy'),(failed,'destroy')]),patch.object(runtime,'_closed',False),patch.object(runtime,'write_metrics',return_value='test'),patch.object(runtime,'_metadata',{}):
            runtime.shutdown()
            self.assertIn('destroy returned False',runtime._metadata['cleanup_errors'][0])
        good.destroy.assert_called_once()

    def test_background_cleanup_survives_individual_actor_failure(self):
        from background_traffic import BackgroundTraffic
        traffic=BackgroundTraffic(NS(),Actor(World()),count=0)
        failed=NS(id=1,is_alive=True,destroy=Mock(side_effect=RuntimeError('actor unavailable')))
        good=NS(id=2,is_alive=True,destroy=Mock(return_value=True))
        traffic.actors=[failed,good]
        traffic.tm=NS(set_hybrid_physics_mode=Mock(),set_synchronous_mode=Mock())
        with self.assertRaisesRegex(RuntimeError,'actor unavailable'):
            traffic.stop()
        good.destroy.assert_called_once()
        traffic.tm.set_hybrid_physics_mode.assert_called_once_with(False)
        traffic.tm.set_synchronous_mode.assert_called_once_with(False)
        self.assertEqual(traffic.actors,[failed])

    def test_camera_destroy_attempted_when_stop_fails(self):
        camera=SensorManager.__new__(SensorManager)
        camera._frame_lock=threading.Lock();camera._closed=False;camera._pending=None
        camera.sensor=NS(is_alive=True,stop=Mock(side_effect=RuntimeError('stop failed')),destroy=Mock(return_value=True))
        with self.assertRaisesRegex(RuntimeError,'stop failed'):
            camera.destroy()
        camera.sensor.destroy.assert_called_once()

    def test_display_cleanup_attempts_every_sensor(self):
        from Set_sensor import DisplayManager
        display=DisplayManager.__new__(DisplayManager)
        failed=NS(destroy=Mock(side_effect=RuntimeError('camera unavailable')))
        good=NS(destroy=Mock())
        display.sensor_list=[failed,good]
        with self.assertRaisesRegex(RuntimeError,'camera unavailable'):
            display.destroy()
        good.destroy.assert_called_once()

    def test_weather_restored_even_if_recorder_stop_fails(self):
        from scene_setup import Environment
        environment=Environment.__new__(Environment)
        environment.weather=object()
        environment.client=NS(stop_recorder=Mock(side_effect=RuntimeError('recorder failed')))
        environment.world=NS(set_weather=Mock())
        with self.assertRaisesRegex(RuntimeError,'recorder failed'):
            environment.restore()
        environment.world.set_weather.assert_called_once_with(environment.weather)

    def test_live_control_thread_is_not_reported_as_stopped(self):
        controller=Ramp_Vice_Control(Actor(World()))
        controller._thread=NS(join=Mock(),is_alive=lambda:True)
        with self.assertRaisesRegex(RuntimeError,'has not stopped'):
            controller.stop()

    def test_shutdown_order_and_idempotence(self):
        calls=[]
        resource=NS(stop=lambda:calls.append('stop'),save_info=lambda:calls.append('save'),
                    destroy=lambda:calls.append('destroy'),restore=lambda:calls.append('restore'))
        entries=[(resource,method) for method in ('restore','stop','destroy','save_info')]
        with patch.object(runtime,'_resources',entries),patch.object(runtime,'_closed',False),patch.object(runtime,'write_metrics',return_value='test'):
            runtime.shutdown();runtime.shutdown()
        self.assertEqual(calls,['stop','save','destroy','restore'])
        runtime.STOP.clear()

if __name__=='__main__':
    unittest.main(verbosity=2)

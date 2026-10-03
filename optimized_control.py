"""共享车辆状态、物理控速和可中止的车道跟随/变道。"""
import math
import threading
import time
from collections import deque
from types import SimpleNamespace

import carla
from agents.navigation.controller import VehiclePIDController
from traffic_math import ahead_distance, follow_speed, lane_key, ramp_speed, smoothstep
import scene_runtime as runtime

def speed_mps(actor):
    v = actor.get_velocity()
    return math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z)

class WorldVehicles:
    """所有本项目控制器共享一次近邻采样，最多每仿真 0.1 秒更新。"""
    def __init__(self, world):
        self.world, self.map = world, world.get_map()
        self.lock = threading.Lock()
        self.sample_time = -math.inf
        self.rows = []

    def nearby(self, ego, front=True):
        with self.lock:
            now = self.world.get_snapshot().timestamp.elapsed_seconds
            if now < self.sample_time or now - self.sample_time >= .1:
                rows = []
                for actor in self.world.get_actors().filter('vehicle.*'):
                    if not actor.is_alive:
                        continue
                    transform = actor.get_transform()
                    rows.append((actor, transform, self.map.get_waypoint(transform.location)))
                self.rows = rows
                self.sample_time = now
                runtime.count('vehicle_world_scans')
            rows = list(self.rows)
        tf = ego.get_transform()
        wp = self.map.get_waypoint(tf.location)
        if wp is None:
            return []
        # 同路段/车道，并纳入前方相连路段；避免仅按 lane_id 混入其他道路。
        keys = {lane_key(wp)}
        for distance in (10, 25, 50, 80):
            for candidate in wp.next(distance):
                keys.add(lane_key(candidate))
        result = []
        for actor, other_tf, other_wp in rows:
            if actor.id == ego.id or not actor.is_alive or lane_key(other_wp) not in keys:
                continue
            distance = tf.location.distance(other_tf.location)
            if distance > 100:
                continue
            ahead = ahead_distance(tf.location, tf.get_forward_vector(), other_tf.location) > 0
            if front is None or ahead == front:
                result.append((actor, ahead, distance))
        return sorted(result, key=lambda row: row[2])

_views = {}
_views_lock = threading.Lock()

def shared_view(world):
    with _views_lock:
        if world.id not in _views:
            _views[world.id] = WorldVehicles(world)
        return _views[world.id]

class Ramp_Vice_Control:
    def __init__(self, vice_car, behavior='traffic'):
        if behavior not in ('traffic', 'scripted'):
            raise ValueError('behavior must be traffic or scripted')
        self.vice_car = vice_car
        self.world = vice_car.get_world()
        self.view = shared_view(self.world)
        self.map = self.view.map
        self.behavior = behavior
        # CARLA 0.9.15 firetruck declares 5000 rpm, but its supplied torque
        # curve ends near 2571 rpm. The stock upshift threshold (3000 rpm in
        # first gear) is beyond that curve: live map10 tests stall at ~24 km/h.
        # Match the limiter to the supplied curve; retain its torque, mass,
        # gear ratios and physical throttle/brake simulation.
        if getattr(vice_car, 'type_id', '') == 'vehicle.carlamotors.firetruck':
            physics = vice_car.get_physics_control()
            curve_rpm = max((point.x for point in physics.torque_curve), default=0)
            if curve_rpm > 0 and physics.max_rpm > curve_rpm * 1.5:
                previous_rpm = physics.max_rpm
                physics.max_rpm = curve_rpm
                vice_car.apply_physics_control(physics)
                runtime.metadata(**{f'firetruck_rpm_fix_{vice_car.id}':
                    {'before':previous_rpm,'after':curve_rpm,'reason':'autobox upshift beyond torque curve'}})
        self.speed_limit = 50
        self.flag = True
        self._stop = threading.Event()
        self._thread = None
        self._command_lock = threading.RLock()
        self._lane_change = None
        self._lane_done = threading.Event()
        self.last_lane_change_ok = None
        self._lead = None
        self._reaction_time = 0
        self._min_gap = 3
        self._history = deque()
        self._command_speed = speed_mps(vice_car)
        # Scripted trials originally begin already travelling at target speed.
        # Seed that initial condition once, then use physical controls normally.
        # Traffic vehicles keep a natural standing start.
        self.start_in_motion = behavior == 'scripted'
        self._pid = VehiclePIDController(vice_car,
            args_lateral={'K_P':1.95, 'K_D':.2, 'K_I':.07, 'dt':.05},
            args_longitudinal={'K_P':1, 'K_D':0, 'K_I':.75, 'dt':.05}, max_brake=1.0)
        runtime.register(self)

    def follow_road(self):
        if self._thread is not None:
            return
        if self.start_in_motion and self.speed_limit > 0:
            forward = self.vice_car.get_transform().get_forward_vector()
            self._command_speed = self.speed_limit / 3.6
            self.vice_car.set_target_velocity(carla.Vector3D(
                x=forward.x*self._command_speed, y=forward.y*self._command_speed,
                z=forward.z*self._command_speed))
            runtime.metadata(**{f'initial_speed_kmh_{self.vice_car.id}':self.speed_limit})
        self._thread = threading.Thread(target=self._run, name=f'control-{self.vice_car.id}', daemon=True)
        self._thread.start()

    def follow_car(self, lead_vehicle, reaction_time, min_distance):
        if reaction_time < 0 or min_distance < 0:
            raise ValueError('reaction_time and min_distance must be nonnegative')
        self._lead, self._reaction_time, self._min_gap = lead_vehicle, reaction_time, min_distance
        self.follow_road()

    def stop(self):
        self._stop.set()
        self._lane_done.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                raise RuntimeError(f'Controller thread {self.vice_car.id} has not stopped')

    def _run(self):
        last = None
        try:
            while not self._stop.is_set() and not runtime.STOP.is_set() and self.vice_car.is_alive:
                snapshot = self.world.wait_for_tick(1.0)
                if snapshot is None:
                    continue
                now = snapshot.timestamp.elapsed_seconds
                if last is not None and 0 <= now-last < .049:
                    continue
                dt = .05 if last is None else max(.001, min(.2, now-last))
                last = now
                started = time.perf_counter()
                with self._command_lock:
                    if self.flag:
                        self._step(dt, now)
                runtime.observe('control_work_ms', (time.perf_counter()-started)*1000)
                runtime.observe('control_sim_dt_ms', dt*1000)
        except Exception as exc:
            runtime.metadata(**{f'controller_error_{self.vice_car.id}': str(exc)})
            if not runtime.STOP.is_set():
                print(f'Controller {self.vice_car.id} stopped: {exc}')
                runtime.request_stop()
        finally:
            self._lane_done.set()

    def _target_waypoint(self, now):
        actor = self.vice_car
        location = actor.get_location()
        wp = self.map.get_waypoint(location)
        if wp is None:
            return None
        lookahead = max(3.0, speed_mps(actor)*.7)
        change = self._lane_change
        if change is None:
            following = wp.next(lookahead)
            return following[0] if following else None
        start, dest, distance, started = change
        progress = ahead_distance(start.transform.location, start.transform.get_forward_vector(), location)
        if now-started > 12:
            self._finish_lane_change(False)
            return None
        dest_now = dest.next(max(0.1, progress))
        if dest_now and lane_key(wp) == lane_key(dest_now[0]) and progress >= distance:
            # 横向误差达标再结束，避免高速越过一个固定终点后无限循环。
            center = dest_now[0].transform
            right = center.get_right_vector()
            lateral = abs(ahead_distance(center.location, right, location))
            if lateral < .6:
                self._finish_lane_change(True)
                following = wp.next(lookahead)
                return following[0] if following else None
        offset = max(.1, progress + lookahead)
        source_path, target_path = start.next(offset), dest.next(offset)
        if not source_path or not target_path:
            self._finish_lane_change(False)
            return None
        source, target = source_path[0].transform, target_path[0].transform
        weight = smoothstep(offset/distance)
        point = carla.Location(x=source.location.x*(1-weight)+target.location.x*weight,
                               y=source.location.y*(1-weight)+target.location.y*weight,
                               z=source.location.z*(1-weight)+target.location.z*weight)
        return SimpleNamespace(transform=carla.Transform(point, target.rotation))

    def _finish_lane_change(self, success):
        self._lane_change = None
        self.last_lane_change_ok = success
        runtime.count('lane_change_success' if success else 'lane_change_failed')
        self._lane_done.set()

    def right_left_lane(self, direction=None, min_direction=10, method='pid', line_number=1, draw=False):
        if method != 'pid':
            raise ValueError('Optimized lane changes support method=pid')
        with self._command_lock:
            start = self.map.get_waypoint(self.vice_car.get_location())
            if start is None or line_number < 1:
                return False
            if direction is None:
                allowed = str(start.lane_change).lower()
                direction = 'left' if allowed in ('left', 'both') else 'right' if allowed == 'right' else None
            if direction not in ('left', 'right'):
                return False
            target = start
            for _ in range(line_number):
                if self.behavior == 'traffic' and str(target.lane_change).lower() not in (direction, 'both'):
                    return False
                target = target.get_left_lane() if direction == 'left' else target.get_right_lane()
                if target is None or target.lane_type != carla.LaneType.Driving:
                    return False
                a, b = start.transform.get_forward_vector(), target.transform.get_forward_vector()
                if a.x*b.x + a.y*b.y <= 0:
                    return False
            if self.behavior == 'traffic':
                # 普通交通还需检查目标车道前后安全间隙。
                for actor in self.world.get_actors().filter('vehicle.*'):
                    if actor.id == self.vice_car.id:
                        continue
                    other_wp = self.map.get_waypoint(actor.get_location())
                    if lane_key(other_wp) == lane_key(target) and actor.get_location().distance(self.vice_car.get_location()) < max(12, speed_mps(self.vice_car)*1.5):
                        return False
            now = self.world.get_snapshot().timestamp.elapsed_seconds
            distance = max(float(min_direction), speed_mps(self.vice_car)*2.0, 15 + 5*line_number)
            self._lane_done.clear()
            self.last_lane_change_ok = None
            self._lane_change = (start, target, distance, now)
        self.follow_road()
        while not self._lane_done.wait(.1):
            if runtime.STOP.is_set() or self._stop.is_set():
                return False
        return self.last_lane_change_ok is True

    def _desired_speed(self, now):
        desired = max(0, self.speed_limit)/3.6
        lead = self._lead
        if lead is None and self.behavior == 'traffic':
            candidates = self.view.nearby(self.vice_car)
            lead = candidates[0][0] if candidates else None
        if lead is None or not lead.is_alive:
            self._history.clear()
            return desired, False
        ego = self.vice_car
        # 保险杠间距代替中心点距离；显式跟车仅作用于前方同一车道。
        ego_tf = ego.get_transform()
        lead_tf = lead.get_transform()
        if ahead_distance(ego_tf.location, ego_tf.get_forward_vector(), lead_tf.location) <= 0:
            self._history.clear()
            return desired, False
        if lane_key(self.map.get_waypoint(ego_tf.location)) != lane_key(self.map.get_waypoint(lead_tf.location)) and self._lead is not None:
            self._history.clear()
            return desired, False
        gap = ego_tf.location.distance(lead_tf.location) - ego.bounding_box.extent.x - lead.bounding_box.extent.x
        measured = (now, speed_mps(lead), gap)
        self._history.append(measured)
        while len(self._history) > 1 and self._history[1][0] <= now-self._reaction_time:
            self._history.popleft()
        _, lead_speed, delayed_gap = self._history[0]
        return follow_speed(desired, lead_speed, delayed_gap, headway=getattr(self,'_headway',1.5), min_gap=self._min_gap)

    def _step(self, dt, now):
        waypoint = self._target_waypoint(now)
        if waypoint is None:
            self.vice_car.apply_control(carla.VehicleControl(brake=1))
            return
        desired, emergency = self._desired_speed(now)
        self._command_speed = ramp_speed(self._command_speed, desired, dt)
        self._pid.set_timestep(dt)
        control = self._pid.run_step(self._command_speed*3.6, waypoint)
        if emergency or desired == 0:
            control.throttle, control.brake = 0, 1
        self.vice_car.apply_control(control)

class Vehicle_Control(Ramp_Vice_Control):
    """主车：保留键盘接管及 lane_offset 接口，接管后取消自动变道。"""
    def __init__(self, vehicle):
        super().__init__(vehicle, behavior='scripted')
        self.vehicle = vehicle
        self.autopilot_flag = True
        self.lose_control = False
        self.autopilot_speed_limit = 100
        self.labour_speed_limit = 140
        self.driver_status = '自动驾驶'
        self.instantaneous_speed = False
        self.lane_offset = 0.0
        self._actual_offset = 0.0

    def follow_lane(self):
        self.speed_limit = self.autopilot_speed_limit
        self.follow_road()

    def _step(self, dt, now):
        import keyboard
        from vehicle_method import get_steering_wheel_info
        if self.lose_control:
            self.driver_status = '没有控制'
            return
        if self.autopilot_flag and keyboard.is_pressed('q'):
            self.autopilot_flag = False
        if not self.autopilot_flag:
            if self._lane_change is not None:
                self._finish_lane_change(False)
            self.driver_status = '人工驾驶'
            steer, throttle, brake = get_steering_wheel_info()
            self.vehicle.apply_control(carla.VehicleControl(steer=max(-1,min(1,steer)),
                throttle=0 if brake > 0 else max(0,min(1,throttle)), brake=max(0,min(1,brake))))
            if keyboard.is_pressed('e'):
                self.autopilot_flag = True
                self._command_speed = speed_mps(self.vehicle)
            return
        self.driver_status = '自动驾驶'
        self.speed_limit = self.autopilot_speed_limit
        self._actual_offset += max(-.5*dt, min(.5*dt, self.lane_offset-self._actual_offset))
        super()._step(dt, now)

    def _target_waypoint(self, now):
        if self._lane_change is not None:
            return super()._target_waypoint(now)
        # offset 的正方向为车道左侧；在原实验 +Y 道路上对应原来的 +X。
        tf = self.vehicle.get_transform()
        wp = self.map.get_waypoint(tf.location)
        if wp is None:
            return None
        right = wp.transform.get_right_vector()
        center = carla.Location(x=tf.location.x+right.x*self._actual_offset,
                                y=tf.location.y+right.y*self._actual_offset, z=tf.location.z)
        center_wp = self.map.get_waypoint(center)
        following = center_wp.next(max(3, speed_mps(self.vehicle)*.7)) if center_wp else []
        if not following:
            return None
        target = following[0].transform
        right = target.get_right_vector()
        loc = carla.Location(x=target.location.x-right.x*self._actual_offset,
                             y=target.location.y-right.y*self._actual_offset, z=target.location.z)
        return SimpleNamespace(transform=carla.Transform(loc, target.rotation))

    def right_left_lane(self, *args, **kwargs):
        if not self.autopilot_flag:
            return False
        return super().right_left_lane(*args, **kwargs)

"""普通背景车由 CARLA Traffic Manager 管理；危险事件车辆不注册到 TM。"""
import random
import carla
import scene_runtime as runtime

class BackgroundTraffic:
    def __init__(self, client, ego, count=0, seed=42, hybrid=False, port=8050):
        self.client, self.world, self.ego = client, ego.get_world(), ego
        self.actors = []
        self.tm = None
        self.hybrid = hybrid
        runtime.register(self)
        if count == 0:
            return
        if not 0 <= count <= 120:
            raise ValueError('background count must be in [0, 120]')
        if hybrid and ego.attributes.get('role_name') != 'hero':
            raise ValueError('Hybrid physics requires an ego vehicle tagged hero')
        rng = random.Random(seed)
        self.tm = client.get_trafficmanager(port)
        self.tm.set_synchronous_mode(self.world.get_settings().synchronous_mode)
        self.tm.set_random_device_seed(seed)
        self.tm.set_global_distance_to_leading_vehicle(3.0)
        self.tm.set_hybrid_physics_mode(hybrid)
        if hybrid:
            self.tm.set_hybrid_physics_radius(100.0)
        blueprints = [b for b in self.world.get_blueprint_library().filter('vehicle.*')
                      if b.has_attribute('number_of_wheels') and int(b.get_attribute('number_of_wheels')) == 4]
        if not blueprints:
            raise RuntimeError('No four-wheel vehicle blueprints available')
        center = ego.get_location()
        points = [p for p in self.world.get_map().get_spawn_points() if 60 <= p.location.distance(center) <= 250]
        rng.shuffle(points)
        occupied = [a.get_location() for a in self.world.get_actors().filter('vehicle.*')]
        for point in points:
            if len(self.actors) >= count:
                break
            if any(point.location.distance(other) < 12 for other in occupied):
                continue
            bp = rng.choice(blueprints)
            bp.set_attribute('role_name', 'hyx_background')
            if bp.has_attribute('color') and bp.get_attribute('color').recommended_values:
                bp.set_attribute('color', rng.choice(bp.get_attribute('color').recommended_values))
            actor = self.world.try_spawn_actor(bp, point)
            if actor is None:
                continue
            self.actors.append(actor)
            occupied.append(point.location)
            actor.set_autopilot(True, port)
            self.tm.distance_to_leading_vehicle(actor, rng.uniform(3, 5))
            self.tm.vehicle_percentage_speed_difference(actor, rng.uniform(5, 20))
            self.tm.ignore_lights_percentage(actor, 0)
            self.tm.ignore_signs_percentage(actor, 0)
            self.tm.auto_lane_change(actor, False)
            if hasattr(self.tm, 'update_vehicle_lights'):
                self.tm.update_vehicle_lights(actor, True)
        runtime.metadata(background_requested=count, background_spawned=len(self.actors),
                         traffic_seed=seed, hybrid_physics=hybrid, traffic_manager_port=port)
        print(f'Background vehicles: {len(self.actors)}/{count}')

    def stop(self):
        errors = []
        remaining = []
        for actor in self.actors:
            try:
                if actor.is_alive and actor.destroy() is False:
                    raise RuntimeError('destroy returned False')
            except Exception as exc:
                remaining.append(actor)
                errors.append(f'actor {actor.id}: {exc}')
        self.actors = remaining
        if self.tm:
            for action in (self.tm.set_hybrid_physics_mode, self.tm.set_synchronous_mode):
                try:
                    action(False)
                except Exception as exc:
                    errors.append(str(exc))
        if errors:
            raise RuntimeError('Background cleanup: ' + '; '.join(errors))

"""Small live diagnostic of control delivery and initial speed establishment."""
import json
import math
from pathlib import Path
import carla

def main():
    c=carla.Client('127.0.0.1',2000);c.set_timeout(15);w=c.get_world();original=w.get_settings()
    if original.synchronous_mode or len(w.get_actors().filter('vehicle.*')):raise RuntimeError('World is occupied')
    actor=None;rows=[]
    try:
        s=w.get_settings();s.synchronous_mode=True;s.fixed_delta_seconds=.05;s.substepping=True;s.max_substep_delta_time=.01;s.max_substeps=10;w.apply_settings(s)
        tf=w.get_map().get_waypoint_xodr(3,-2,65).transform;tf.location.z+=.25
        actor=w.spawn_actor(w.get_blueprint_library().find('vehicle.tesla.model3'),tf)
        def sample(label):
            f=w.tick(10);v=actor.get_velocity();k=actor.get_control()
            rows.append(dict(label=label,frame=f,speed=3.6*math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z),vx=v.x,brake=k.brake,throttle=k.throttle,gear=k.gear,steer=k.steer))
        actor.apply_control(carla.VehicleControl(brake=1))
        for i in range(20):sample('settle')
        actor.apply_control(carla.VehicleControl())
        for i in range(3):sample('neutral')
        actor.set_target_velocity(carla.Vector3D(x=30/3.6));sample('seed_neutral')
        for i in range(3):sample('coast')
        actor.apply_control(carla.VehicleControl(throttle=.2))
        for i in range(3):sample('throttle')
        actor.set_target_velocity(carla.Vector3D(x=30/3.6));sample('seed_throttle')
        cmds=[carla.command.ApplyVehicleControl(actor.id,carla.VehicleControl()),carla.command.ApplyTargetVelocity(actor.id,carla.Vector3D(x=30/3.6))]
        print('batch',c.apply_batch_sync(cmds,False));sample('acknowledged_batch')
        for i in range(3):sample('coast_after_batch')
    finally:
        if actor:actor.destroy()
        w.apply_settings(original)
    path=Path(__file__).resolve().parents[1]/'optimization_reports/case172_scenarios/initialization_probe.json'
    path.write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print(json.dumps(rows[-15:],indent=2))

if __name__=='__main__':main()

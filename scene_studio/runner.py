"""Isolated scenario worker. Owns only actors it creates; never clears a world."""
import argparse
import csv
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import carla
import cv2
import numpy as np
import scene_runtime as runtime
from optimized_control import Ramp_Vice_Control, speed_mps
from traffic_math import ramp_speed
from scene_studio.schema import validate, look_values, triggered
cv2.setNumThreads(1)


def atomic_json(path,data):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    # Windows readers briefly hold the destination without FILE_SHARE_DELETE.
    for attempt in range(20):
        try:os.replace(temp,path);return
        except PermissionError:
            if attempt==19:raise
            time.sleep(.01)


class OwnedActor:
    def __init__(self,actor):self.actor=actor
    def destroy(self):
        return self.actor.destroy() if self.actor.is_alive else True


class Driver(Ramp_Vice_Control):
    def __init__(self,actor,spec,planner=None):
        super().__init__(actor,behavior='traffic' if spec['behavior']=='traffic' else 'scripted')
        self.spec=spec;self.speed_limit=spec['speed'];self.start_in_motion=spec['start_in_motion']
        self.offset=spec['offset'];self.actual_offset=0;self.brake_override=None
        self.route=[];self.route_index=0;self.route_done=False;self.planner=planner
        self.manual=None
        if spec.get('route'):self.set_route(spec['route'])

    def set_route(self,points):
        from agents.navigation.global_route_planner import GlobalRoutePlanner
        from scene_studio.routing import MapDAO
        if self.planner is None:
            self.planner=GlobalRoutePlanner(MapDAO(self.map,2))
            self.planner.setup()
        start=self.vice_car.get_location();route=[]
        for p in points:
            end=carla.Location(x=p['x'],y=p['y'],z=p.get('z',start.z))
            segment=self.planner.trace_route(start,end)
            if not segment:raise ValueError('路线点之间没有可驾驶连接')
            route.extend(wp for wp,_ in segment);start=end
        self.route=route;self.route_index=0;self.route_done=False

    def _target_waypoint(self,now):
        if self._lane_change is not None:return super()._target_waypoint(now)
        if self.route:
            loc=self.vice_car.get_location()
            end=min(len(self.route),self.route_index+35)
            self.route_index=min(range(self.route_index,end),key=lambda i:loc.distance(self.route[i].transform.location))
            if self.route_index>=len(self.route)-3 and loc.distance(self.route[-1].transform.location)<3:
                self.route_done=True;self.speed_limit=0
            idx=self.route_index;distance=0
            while idx+1<len(self.route) and distance<max(3,speed_mps(self.vice_car)*.7):
                distance+=self.route[idx].transform.location.distance(self.route[idx+1].transform.location);idx+=1
            wp=self.route[idx]
        else:wp=super()._target_waypoint(now)
        if wp is None:return None
        tf=wp.transform;right=tf.get_right_vector()
        point=carla.Location(x=tf.location.x-right.x*self.actual_offset,y=tf.location.y-right.y*self.actual_offset,z=tf.location.z)
        return SimpleNamespace(transform=carla.Transform(point,tf.rotation))

    def _step(self,dt,now):
        if self.manual is not None:
            steer,throttle,brake=self.manual
            self.vice_car.apply_control(carla.VehicleControl(steer=steer,throttle=0 if brake else throttle,brake=brake))
            return
        if self.brake_override is not None:
            self.vice_car.apply_control(carla.VehicleControl(throttle=0,brake=self.brake_override))
            self._command_speed=speed_mps(self.vice_car);return
        self.actual_offset+=max(-.5*dt,min(.5*dt,self.offset-self.actual_offset))
        wp=self._target_waypoint(now)
        if wp is None:self.vice_car.apply_control(carla.VehicleControl(brake=1));return
        desired,emergency=self._desired_speed(now)
        self._command_speed=ramp_speed(self._command_speed,desired,dt,self.spec['acceleration'],self.spec['deceleration'])
        self._pid.set_timestep(dt)
        control=self._pid.run_step(self._command_speed*3.6,wp)
        if emergency or desired==0:control.throttle,control.brake=0,1
        self.vice_car.apply_control(control)


class Session:
    def __init__(self,scene,folder,preview=False):
        self.scene=validate(scene);self.folder=folder;self.preview=preview
        self.client=carla.Client('127.0.0.1',2000);self.client.set_timeout(10)
        self.world=self.client.get_world();self.map=self.world.get_map()
        if self.map.name!=scene['map']:raise RuntimeError('当前地图与场景地图不匹配，请先在 CARLA 打开 '+scene['map'])
        if self.world.get_settings().synchronous_mode:raise RuntimeError('编辑器运行需要异步 CARLA 世界')
        self.original_weather=self.world.get_weather()
        self.actors={};self.drivers={};self.walkers={};self.camera=None;self.planner=None;self.owned=[]
        self.records=[];self.collisions=[];self.fired={};self.states={};self.elapsed=0;self.paused=False;self.saved_velocities={}
        self.frame_count=0;self.frame_times=[];self.last_image_time=0;self.camera_lock=threading.Lock();self.image_lock=threading.Lock();self.closed=False
        self.status='starting';self.error=None;self.last_write=0;self.manual_at=0

    def spawn(self,spec):
        aid=spec['id']
        if aid in self.actors:return
        bp=self.world.get_blueprint_library().find(spec['model'])
        if bp.has_attribute('role_name'):bp.set_attribute('role_name','studio_'+aid)
        if bp.has_attribute('color') and spec.get('color'):
            h=spec['color'].lstrip('#');bp.set_attribute('color',','.join(str(int(h[i:i+2],16)) for i in (0,2,4)))
        if bp.has_attribute('is_invincible'):bp.set_attribute('is_invincible','false')
        tf=carla.Transform(carla.Location(x=spec['x'],y=spec['y'],z=spec['z']),carla.Rotation(yaw=spec['yaw']))
        if spec.get('snap',True):
            wp=self.map.get_waypoint(tf.location)
            if wp is None:raise ValueError(spec['name']+' 不在道路附近')
            tf.location=wp.transform.location;tf.location.z+=.25
        elif tf.location.z<.01:
            wp=self.map.get_waypoint(tf.location)
            if wp:tf.location.z=wp.transform.location.z+.3
        actor=self.world.try_spawn_actor(bp,tf)
        if actor is None:raise RuntimeError(spec['name']+' 生成失败：位置被占用或与地面重叠')
        self.actors[aid]=actor;runtime.register(OwnedActor(actor),'destroy')
        self.owned.append(actor)
        if self.preview or spec['behavior']=='parked' or spec['model'].startswith('static.'):
            actor.set_simulate_physics(False)
        elif spec['model'].startswith('walker.'):
            self.walkers[aid]=dict(index=0,speed=spec['speed']/3.6)
        else:
            driver=Driver(actor,spec,self.planner)
            if driver.planner:self.planner=driver.planner
            self.drivers[aid]=driver
        if spec['model'].startswith(('vehicle.','walker.')):
            sensor=self.world.spawn_actor(self.world.get_blueprint_library().find('sensor.other.collision'),carla.Transform(),attach_to=actor)
            runtime.register(OwnedActor(sensor),'destroy')
            self.owned.append(sensor)
            sensor.listen(lambda e,aid=aid:self.collisions.append({'time':self.elapsed,'frame':e.frame,'actor':aid,'other':e.other_actor.type_id,'other_id':e.other_actor.id}))

    def apply_look(self,look):
        self.scene['look']=look
        preset=look_values(look)
        self.world.set_weather(self.original_weather)
        weather=self.world.get_weather()
        for key,value in preset['weather'].items():setattr(weather,key,value)
        self.world.set_weather(weather)
        for a in self.actors.values():
            if a.type_id.startswith('vehicle.'):
                a.set_light_state(carla.VehicleLightState.Position|carla.VehicleLightState.LowBeam if look.get('preset')=='dusk' else carla.VehicleLightState.NONE)
        if self.camera:self.make_camera()

    def make_camera(self,target=None,view=None):
        with self.camera_lock:
            if self.camera:
                self.camera.stop();self.camera.destroy();self.camera=None
            target=target or self.scene['ego']
            if target not in self.actors:return
            self.scene['ego']=target
            cfg=self.scene['camera'];view=view or cfg.get('view','driver');cfg['view']=view
            bp=self.world.get_blueprint_library().find('sensor.camera.rgb')
            options={'image_size_x':cfg['width'],'image_size_y':cfg['height'],'fov':cfg['fov'],'sensor_tick':1/cfg['fps'],**look_values(self.scene['look'])['camera']}
            for key,val in options.items():
                if not bp.has_attribute(key):raise ValueError('相机不支持 '+key)
                bp.set_attribute(key,str(val))
            if view=='top':tf=carla.Transform(carla.Location(z=70),carla.Rotation(pitch=-90,yaw=-90))
            elif view=='chase':tf=carla.Transform(carla.Location(x=-8,z=4),carla.Rotation(pitch=-12))
            else:tf=carla.Transform(carla.Location(x=1.4,y=-.18,z=1.04))
            self.camera=self.world.spawn_actor(bp,tf,attach_to=self.actors[target])
            self.camera.listen(self.on_image)

    def on_image(self,image):
        if self.closed:return
        arr=np.frombuffer(image.raw_data,dtype=np.uint8).reshape(image.height,image.width,4)[:,:,:3]
        ok,data=cv2.imencode('.jpg',arr,[cv2.IMWRITE_JPEG_QUALITY,85])
        if ok:
            with self.image_lock:
                temp=self.folder/'frame.tmp';temp.write_bytes(data.tobytes())
                try:os.replace(temp,self.folder/'frame.jpg')
                except OSError:pass
        now=time.perf_counter();self.frame_count+=1;self.frame_times.append(now);self.frame_times=self.frame_times[-120:]
        self.last_image_time=now

    def start(self):
        for spec in self.scene['actors']:
            if spec['spawn_at_start']:self.spawn(spec)
        self.apply_look(self.scene['look']);self.make_camera()
        # Start all drivers after actor/camera setup, so setup latency cannot
        # move the first actor away before the other participants exist.
        for driver in self.drivers.values():driver.follow_road()
        self.status='preview' if self.preview else 'running'

    def action(self,a,event_id='manual'):
        kind=a['type'];aid=a.get('actor');actor=self.actors.get(aid);driver=self.drivers.get(aid)
        if kind=='speed':
            if driver:
                with driver._command_lock:driver.brake_override=None;driver.speed_limit=a['value']
            elif aid in self.walkers:self.walkers[aid]['speed']=a['value']/3.6
            else:raise ValueError('目标参与者没有运动控制器')
        elif kind=='brake':
            if not driver:raise ValueError('制动需要车辆控制器')
            with driver._command_lock:driver.brake_override=a.get('value',1)
        elif kind=='offset':
            if not driver:raise ValueError('横向偏移需要车辆')
            driver.offset=a['value']
        elif kind=='follow':
            if not driver or a['target'] not in self.actors:raise ValueError('跟车对象不存在')
            with driver._command_lock:
                driver._lead=self.actors[a['target']];driver._reaction_time=float(a.get('reaction',.8));driver._min_gap=float(a.get('gap',3));driver._history.clear()
        elif kind=='lane_change':
            if not driver:raise ValueError('变道需要车辆')
            def change():
                ok=driver.right_left_lane(direction=a.get('direction','left'),line_number=a.get('lanes',1),min_direction=a.get('distance',20))
                self.records.append({'id':event_id,'time':self.elapsed,'type':'lane_change_result','success':ok})
            thread=threading.Thread(target=change,daemon=True);runtime.register_thread(thread);thread.start()
        elif kind=='route':
            if not driver:raise ValueError('路线需要车辆')
            spec=next(s for s in self.scene['actors'] if s['id']==aid)
            with driver._command_lock:driver.set_route(spec['route'])
        elif kind=='destroy':
            if aid==self.scene['ego']:raise ValueError('不能删除当前相机依附对象，请先切换主视角')
            if driver:driver.stop();del self.drivers[aid]
            if actor:actor.destroy();del self.actors[aid]
            self.walkers.pop(aid,None)
        elif kind=='spawn':
            spec=next(s for s in self.scene['actors'] if s['id']==aid);self.spawn(spec)
            if aid in self.drivers:self.drivers[aid].follow_road()
        elif kind=='lights':
            if not actor or not actor.type_id.startswith('vehicle.'):raise ValueError('车灯需要车辆')
            actor.set_light_state(carla.VehicleLightState(a.get('value',3)))
        elif kind=='weather':self.apply_look({'preset':a['preset'],'weather':{},'camera':{}})
        elif kind=='finish':runtime.request_stop()
        self.records.append({'id':event_id,'time':self.elapsed,'type':kind,'actor':aid,'action':a})

    def pause(self,paused):
        if self.preview or paused==self.paused:return
        if paused:
            for driver in self.drivers.values():
                with driver._command_lock:driver.flag=False
        for aid,actor in self.actors.items():
            spec=next(s for s in self.scene['actors'] if s['id']==aid)
            if spec['behavior']=='parked' or actor.type_id.startswith('static.'):continue
            if paused:self.saved_velocities[aid]=actor.get_velocity();actor.set_simulate_physics(False)
            else:actor.set_simulate_physics(True);actor.set_target_velocity(self.saved_velocities[aid])
        if not paused:
            for driver in self.drivers.values():
                with driver._command_lock:driver.flag=True
        self.paused=paused;self.status='paused' if paused else 'running'

    def commands(self):
        for path in sorted((self.folder/'commands').glob('*.json')):
            command=json.loads(path.read_text(encoding='utf-8'));path.unlink()
            try:
                kind=command['type']
                if kind=='stop':runtime.request_stop()
                elif kind=='pause':self.pause(True)
                elif kind=='resume':self.pause(False)
                elif kind=='camera':self.make_camera(command.get('actor'),command.get('view'))
                elif kind=='look':self.apply_look(command['look'])
                elif kind=='action':self.action(command['action'])
                elif kind=='transform':
                    if not self.preview:raise ValueError('运行中请先停止，再布置初始位置')
                    a=self.actors[command['actor']];p=command['pose'];a.set_transform(carla.Transform(carla.Location(x=p['x'],y=p['y'],z=p['z']),carla.Rotation(yaw=p['yaw'])))
                elif kind=='manual':
                    driver=self.drivers[self.scene['ego']]
                    driver.manual=None if command.get('auto') else [max(-1,min(1,float(command.get('steer',0)))),max(0,min(1,float(command.get('throttle',0)))),max(0,min(1,float(command.get('brake',0))))]
                    self.manual_at=time.perf_counter()
            except Exception as exc:self.records.append({'time':self.elapsed,'type':'command_error','error':str(exc)})

    def snapshot(self,snapshot):
        self.states={}
        for aid,actor in self.actors.items():
            state=snapshot.find(actor.id)
            if not state:continue
            tf=state.get_transform();v=state.get_velocity()
            self.states[aid]={'id':aid,'carla_id':actor.id,'x':tf.location.x,'y':tf.location.y,'z':tf.location.z,'yaw':tf.rotation.yaw,'speed':math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z)*3.6}

    def write_status(self):
        times=self.frame_times[:]
        fps=(len(times)-1)/(times[-1]-times[0]) if len(times)>1 else 0
        atomic_json(self.folder/'status.json',{'state':self.status,'error':self.error,'elapsed':self.elapsed,'actors':self.states,'events':self.records[-100:],'fired':self.fired,'collisions':self.collisions[-30:],'camera_fps':fps,'frame_age_s':time.perf_counter()-self.last_image_time if self.last_image_time else None,'frame_count':self.frame_count,'run_id':self.folder.name,'preview':self.preview})

    def run(self):
        try:
            self.start();previous=self.world.get_snapshot().timestamp.elapsed_seconds
            with (self.folder/'telemetry.csv').open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=['time','frame','id','carla_id','x','y','z','yaw','speed']);writer.writeheader()
                while not runtime.STOP.is_set():
                    snap=self.world.wait_for_tick(2)
                    if snap is None:raise RuntimeError('CARLA 两秒内未产生新帧')
                    now=snap.timestamp.elapsed_seconds;dt=max(0,now-previous);previous=now
                    if not self.paused and not self.preview:self.elapsed+=dt
                    self.commands();self.snapshot(snap)
                    if not self.paused and not self.preview:
                        for e in self.scene['events']:
                            if e['id'] not in self.fired and e.get('enabled',True) and triggered(e['trigger'],self.elapsed,self.states,self.fired):
                                self.action(e['action'],e['id']);self.fired[e['id']]=self.elapsed
                        for aid,walker in self.walkers.items():
                            actor=self.actors[aid];spec=next(s for s in self.scene['actors'] if s['id']==aid);route=spec['route'];direction=actor.get_transform().get_forward_vector()
                            if route:
                                p=route[walker['index']];loc=actor.get_location();dx=p['x']-loc.x;dy=p['y']-loc.y;dist=math.hypot(dx,dy)
                                if dist<.8:
                                    if walker['index']+1<len(route):walker['index']+=1
                                    else:walker['speed']=0
                                if dist>.01:direction=carla.Vector3D(x=dx/dist,y=dy/dist)
                            actor.apply_control(carla.WalkerControl(direction=direction,speed=walker['speed']))
                        if self.elapsed>=self.scene['duration']:runtime.request_stop()
                    for d in self.drivers.values():
                        if d.manual is not None and time.perf_counter()-self.manual_at>.5:d.manual=[0,0,1]
                    if time.perf_counter()-self.last_write>.1:
                        self.write_status();self.last_write=time.perf_counter()
                        for row in self.states.values():writer.writerow({'time':self.elapsed,'frame':snap.frame,**row})
                        f.flush()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.error=str(exc);self.status='error';print('Studio error:',exc,flush=True)
        finally:
            self.closed=True
            if self.camera:
                try:self.camera.stop();self.camera.destroy()
                except Exception as exc:self.records.append({'type':'cleanup_error','error':str(exc)});self.error=self.error or '相机清理失败：'+str(exc);self.status='error'
            runtime.shutdown()
            with runtime._lock:
                failures={k:v for k,v in runtime._metadata.items() if k.startswith('controller_error_') or k=='cleanup_errors' and v}
            if failures and not self.error:self.error=str(failures);self.status='error'
            try:self.world.set_weather(self.original_weather)
            except Exception as exc:self.records.append({'type':'restore_error','error':str(exc)});self.error=self.error or '天气恢复失败：'+str(exc);self.status='error'
            if not self.error:self.status='finished'
            self.states={};self.write_status()
            atomic_json(self.folder/'events.json',{'events':self.records,'collisions':self.collisions,'fired':self.fired,'error':self.error,'remaining_owned_actor_ids':[a.id for a in self.owned if a.is_alive]})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');p.add_argument('--preview',action='store_true');args=p.parse_args()
    folder=Path(args.folder).resolve()
    try:Session(json.loads((folder/'scene.json').read_text(encoding='utf-8')),folder,args.preview).run()
    except Exception as exc:
        atomic_json(folder/'status.json',{'state':'error','error':str(exc),'run_id':folder.name,'actors':{},'events':[]})
        raise

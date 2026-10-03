"""Fixed-step studio runtime: physical timeline authoring and exact pose replay.

The main loop is the sole tick/control writer. Manual input is arbitrated before
any automated controller. Each process owns and cleans up only its own actors.
"""
import argparse
import copy
import csv
import json
import math
from pathlib import Path
import threading
import time
import traceback
from types import SimpleNamespace
import carla
import cv2
import numpy as np
import scene_runtime as runtime
from agents.navigation.controller import VehiclePIDController
from optimized_control import speed_mps
from scene_studio.runner import Session as LegacySession,Driver as LegacyDriver,OwnedActor,atomic_json
from scene_studio.schema import validate,look_values,triggered
from scene_studio.timeline import ControlOwner,motion_at,pose_on_path
from scene_studio.recording import Recording,RecordingWriter
from scene_studio.planning import Planner
from traffic_math import follow_speed

WEATHER_KEYS=('cloudiness','precipitation','precipitation_deposits','wind_intensity','sun_azimuth_angle','sun_altitude_angle','fog_density','fog_distance','fog_falloff','wetness','scattering_intensity','mie_scattering_scale','rayleigh_scattering_scale','dust_storm')
def weather_dict(w):return {k:getattr(w,k) for k in WEATHER_KEYS if hasattr(w,k)}
def transform(p):return carla.Transform(carla.Location(x=p['x'],y=p['y'],z=p['z']),carla.Rotation(yaw=p.get('yaw',0),pitch=p.get('pitch',0),roll=p.get('roll',0)))

class StudioDriver(LegacyDriver):
    def __init__(self,actor,spec,track):
        settings=copy.deepcopy(spec);settings['route']=[]
        super().__init__(actor,settings)
        self.spec=spec;self.track=track;self._thread=None
        self.route=[SimpleNamespace(transform=carla.Transform(carla.Location(x=p[1],y=p[2],z=p[3]),carla.Rotation(yaw=p[4]))) for p in track['path']]
        self.timeline=bool(spec.get('clips'));self.timeline_follow=False
    def follow_road(self):
        # Legacy lane-change helpers call this method; never create a second writer.
        return
    def _desired_speed(self,now):
        desired,emergency=super()._desired_speed(now)
        if self._history:
            _,lead_speed,gap=self._history[0]
            delayed,stop=follow_speed(self.speed_limit/3.6,lead_speed,gap,
                headway=getattr(self,'_headway',1.5),min_gap=self._min_gap,
                decel=min(4.,self.spec['deceleration']),reaction_time=self._reaction_time+.35)
            desired=min(desired,delayed);emergency=emergency or stop
        return desired,emergency
    def rejoin(self):
        loc=self.vice_car.get_location()
        if self.route:self.route_index=min(range(len(self.route)),key=lambda i:loc.distance(self.route[i].transform.location))
        self._command_speed=speed_mps(self.vice_car);self.route_done=False
        self._pid=VehiclePIDController(self.vice_car,args_lateral={'K_P':1.95,'K_D':.2,'K_I':.07,'dt':.05},args_longitudinal={'K_P':1,'K_D':0,'K_I':.75,'dt':.05},max_brake=1.)
    def timeline_update(self,t,actors):
        if not self.timeline:return []
        value=motion_at(self.spec,t,self.track['lane_width'])
        channels={c['type'] for c in self.spec.get('clips',[]) if c.get('enabled',True)}
        if 'speed' in channels:self.speed_limit=value['speed']
        if 'lane_change' in channels:self.offset=value['offset'];self.actual_offset=value['offset']
        if 'brake' in channels:self.brake_override=value['brake']
        follow=value['follow']
        if follow:
            lead=actors.get(follow['target'])
            if lead is not self._lead:self._history.clear()
            self._lead=lead;self._reaction_time=follow['reaction'];self._min_gap=follow['gap'];self._headway=follow['headway'];self.timeline_follow=True
        elif self.timeline_follow:self._lead=None;self._history.clear();self.timeline_follow=False
        if value['lights'] is not None:self.vice_car.set_light_state(carla.VehicleLightState(value['lights']))
        return value['active']

class Session(LegacySession):
    def __init__(self,scene,folder,preview=False):
        super().__init__(validate(scene),folder,preview)
        self.original_settings=self.world.get_settings();self.dt=self.scene['dt']
        self.owner=ControlOwner();self.active_clips=[];self.frame_times_map={};self.camera_time=0
        self.frame_index=0;self.recorder=None;self.recording=None;self.override=False;self.ego_rejoining=False
        self.last_input_mtime=None;self.camera_generation=0;self.last_preview=0;self.timeline_started=set()
        self.baseline_weather=weather_dict(self.original_weather)
        if self.scene['mode']=='environment':
            self.recording=Recording(folder.parent/self.scene['locked_take']);self.recording.verify(self.scene)
            self.baseline_weather=self.recording.header['weather']
        planfile=folder/'plan.json'
        self.plan=json.loads(planfile.read_text(encoding='utf-8')) if planfile.exists() else Planner(self.map).compile(self.scene)
        self.specs={a['id']:a for a in self.scene['actors']}
        self.end_time=self.recording.header['duration'] if self.recording else self.scene['duration']
        self.saved_velocities={};self.last_controls={};self.last_source={};self.render_ticks=0

    def spawn(self,spec,pose=None):
        aid=spec['id']
        if aid in self.actors:return
        bp=self.world.get_blueprint_library().find(spec['model'])
        if bp.has_attribute('role_name'):bp.set_attribute('role_name','studio_'+aid)
        if bp.has_attribute('color') and spec.get('color'):
            h=spec['color'].lstrip('#');bp.set_attribute('color',','.join(str(int(h[i:i+2],16)) for i in (0,2,4)))
        if bp.has_attribute('is_invincible'):bp.set_attribute('is_invincible','false')
        p=pose or spec;tf=transform(p)
        if pose:tf.location.z+=1.0
        if not pose and spec.get('snap',True):
            wp=self.map.get_waypoint(tf.location)
            if not wp:raise ValueError(spec['name']+' 不在可驾驶道路附近')
            tf.location=wp.transform.location;tf.location.z+=.25
        actor=self.world.try_spawn_actor(bp,tf)
        if not actor:raise RuntimeError(spec['name']+' 生成失败：位置被占用或与地面重叠')
        self.actors[aid]=actor;self.owned.append(actor);runtime.register(OwnedActor(actor),'destroy')
        if spec['model'].startswith('vehicle.'):
            self.drivers[aid]=StudioDriver(actor,spec,self.plan['tracks'][aid])
            actor.apply_control(carla.VehicleControl(brake=1))
        elif spec['model'].startswith('walker.'):
            self.walkers[aid]={'speed':spec['speed']/3.6,'index':0}
        actor.set_simulate_physics(not(self.preview or self.recording or spec['behavior']=='parked' or spec['model'].startswith('static.')))
        if pose:actor.set_transform(transform(p))
        if spec['model'].startswith(('vehicle.','walker.')):
            sensor=self.world.spawn_actor(self.world.get_blueprint_library().find('sensor.other.collision'),carla.Transform(),attach_to=actor)
            self.owned.append(sensor);runtime.register(OwnedActor(sensor),'destroy')
            sensor.listen(lambda e,aid=aid:self.collisions.append({'time':self.elapsed,'frame':e.frame,'actor':aid,'other':e.other_actor.type_id,'other_id':e.other_actor.id,'impulse':[e.normal_impulse.x,e.normal_impulse.y,e.normal_impulse.z]}))

    def apply_look(self,look):
        self.scene['look']=copy.deepcopy(look);values=look_values(look)
        weather=self.world.get_weather()
        for k,v in {**self.baseline_weather,**values['weather']}.items():setattr(weather,k,v)
        self.world.set_weather(weather)
        if self.camera:self.make_camera(self.camera_target)
        self.records.append({'time':self.elapsed,'type':'look','preset':look['preset']})

    def make_camera(self,target=None,view=None):
        self.camera_generation+=1;generation=self.camera_generation
        if self.camera:self.camera.stop();self.camera.destroy();self.camera=None
        target=target or getattr(self,'camera_target',self.scene['ego']);self.camera_target=target
        if target not in self.actors:return
        cfg=self.scene['camera'];view=view or cfg.get('view','driver');cfg['view']=view
        bp=self.world.get_blueprint_library().find('sensor.camera.rgb')
        options={'image_size_x':cfg['width'],'image_size_y':cfg['height'],'fov':cfg['fov'],'sensor_tick':max(self.dt,1/cfg['fps']),**look_values(self.scene['look'])['camera']}
        for key,value in options.items():
            if not bp.has_attribute(key):raise ValueError('相机不支持 '+key)
            bp.set_attribute(key,str(value))
        if view=='top':tf=carla.Transform(carla.Location(z=70),carla.Rotation(pitch=-90,yaw=-90))
        elif view=='chase':tf=carla.Transform(carla.Location(x=-8,z=4),carla.Rotation(pitch=-12))
        else:tf=carla.Transform(carla.Location(x=1.4,y=-.18,z=1.04))
        self.camera=self.world.spawn_actor(bp,tf,attach_to=self.actors[target])
        self.camera.listen(lambda im:self.on_frame(im,generation))

    def on_frame(self,image,generation):
        if self.closed or generation!=self.camera_generation:return
        arr=np.frombuffer(image.raw_data,np.uint8).reshape(image.height,image.width,4)[:,:,:3]
        ok,data=cv2.imencode('.jpg',arr,[cv2.IMWRITE_JPEG_QUALITY,88])
        if not ok or self.closed or generation!=self.camera_generation:return
        t=self.frame_times_map.get(image.frame,self.elapsed)
        self.camera_time=t
        with self.image_lock:
            temp=self.folder/'frame.tmp';temp.write_bytes(data.tobytes())
            try:temp.replace(self.folder/'frame.jpg')
            except PermissionError:pass
            # Comparable stills at exact scene seconds; never advance scene time here.
            if not self.preview and abs(t-round(t))<self.dt/4:
                (self.folder/f'shot_{round(t*1000):07d}.jpg').write_bytes(data.tobytes())
        now=time.perf_counter();self.frame_count+=1;self.frame_times.append(now);self.frame_times=self.frame_times[-100:];self.last_image_time=now

    def tick(self):
        expected=self.world.get_snapshot().frame+1;self.frame_times_map[expected]=self.elapsed
        frame=self.world.tick(10)
        if frame!=expected:raise RuntimeError('检测到其他客户端同时推进仿真，已停止以保护时间轴')
        if len(self.frame_times_map)>250:self.frame_times_map.pop(min(self.frame_times_map))
        return self.world.get_snapshot()

    def start(self):
        settings=self.world.get_settings();settings.synchronous_mode=True;settings.fixed_delta_seconds=self.dt
        settings.substepping=True;settings.max_substep_delta_time=.01;settings.max_substeps=max(10,math.ceil(self.dt/.01))
        self.world.apply_settings(settings)
        if self.recording:
            first=self.recording.frame(0)
            for aid,pose in first['actors'].items():self.spawn(self.specs[aid],pose)
        else:
            for a in self.scene['actors']:
                if a['spawn_at_start']:self.spawn(a)
        self.apply_look(self.scene['look']);self.make_camera(self.scene['ego'])
        # Settle spawned physical vehicles before establishing t=0; no time-axis motion.
        for _ in range(10):self.tick()
        if not self.preview and not self.recording:
            for aid,d in self.drivers.items():
                if d.spec['behavior']!='parked' and d.start_in_motion and d.speed_limit>0:
                    f=self.actors[aid].get_transform().get_forward_vector();speed=d.speed_limit/3.6
                    self.actors[aid].set_target_velocity(carla.Vector3D(x=f.x*speed,y=f.y*speed,z=f.z*speed));d._command_speed=speed
        self.status='preview' if self.preview else 'running'
        if not self.preview:self.recorder=RecordingWriter(self.folder,copy.deepcopy(self.scene),self.baseline_weather)
        self.snapshot(self.world.get_snapshot())

    def snapshot(self,snapshot):
        self.states={}
        for aid,actor in self.actors.items():
            state=snapshot.find(actor.id)
            if not state:continue
            tf=state.get_transform();v=state.get_velocity();speed=math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z)*3.6
            source='physics'
            if self.recording and aid in self.last_source and not(aid==self.scene['ego'] and self.override):speed=self.last_source[aid]['speed'];source='recorded'
            control=actor.get_control() if actor.type_id.startswith('vehicle.') else None
            self.states[aid]={'id':aid,'carla_id':actor.id,'x':tf.location.x,'y':tf.location.y,'z':tf.location.z,'yaw':tf.rotation.yaw,'pitch':tf.rotation.pitch,'roll':tf.rotation.roll,'speed':speed,'speed_source':source,'steer':control.steer if control else 0,'throttle':control.throttle if control else 0,'brake':control.brake if control else 0}
            self.states[aid]['lights']=int(actor.get_light_state()) if control else 0

    def apply_replay(self,t):
        source=self.recording.at(t)['actors'];self.last_source=source
        commands=[]
        for aid in list(self.actors):
            if aid not in source and aid!=self.scene['ego']:self.action({'type':'destroy','actor':aid},'replay')
        for aid,p in source.items():
            if aid not in self.actors:self.spawn(self.specs[aid],p)
            if aid==self.scene['ego'] and self.override:continue
            a=self.actors[aid]
            commands.append(carla.command.ApplyTransform(a.id,transform(p)))
            if a.type_id.startswith('vehicle.'):
                commands.append(carla.command.ApplyVehicleControl(a.id,carla.VehicleControl(steer=p.get('steer',0),throttle=p.get('throttle',0),brake=p.get('brake',0))))
                commands.append(carla.command.SetVehicleLightState(a.id,carla.VehicleLightState(p.get('lights',0))))
        # Actor setters enqueue individual RPCs. Wait for a single acknowledged
        # batch before advancing the frame so every actor uses the same source time.
        if commands:
            errors=[r.error for r in self.client.apply_batch_sync(commands,False) if r.has_error()]
            if errors:raise RuntimeError('轨迹批量更新失败：'+'; '.join(errors))

    def preview_at(self,t):
        self.elapsed=max(0,min(self.end_time,float(t)))
        if self.recording:self.apply_replay(self.elapsed)
        else:
            for aid,a in self.actors.items():
                frames=self.plan['tracks'][aid]['frames'];i=min(range(len(frames)),key=lambda i:abs(frames[i][0]-self.elapsed));p=frames[i]
                a.set_transform(transform({'x':p[1],'y':p[2],'z':self.specs[aid]['z']+(p[3]-frames[0][3]),'yaw':p[4]}))

    def take_control(self,owner):
        aid=self.scene['ego'];a=self.actors.get(aid)
        if not a or aid not in self.drivers:raise ValueError('主车必须是车辆才能手动接管')
        if self.preview:raise ValueError('请启动运行或轨迹重放后接管')
        if self.owner.owner=='auto':
            if self.recording and not self.override:
                p=self.recording.at(self.elapsed)['actors'][aid];speed=p['speed']/3.6;rad=math.radians(p['yaw'])
                velocity=carla.Vector3D(x=math.cos(rad)*speed,y=math.sin(rad)*speed)
                if self.paused:self.saved_velocities[aid]=velocity
                else:
                    results=self.client.apply_batch_sync([carla.command.SetSimulatePhysics(a.id,True),carla.command.ApplyTargetVelocity(a.id,velocity)],False)
                    if any(r.has_error() for r in results):raise RuntimeError('主车恢复物理失败')
                self.override=True
            elif self.specs[aid]['behavior']=='parked' and not self.paused:a.set_simulate_physics(True)
            d=self.drivers[aid]
            if d._lane_change is not None:d._finish_lane_change(False)
        self.owner.take(owner,time.monotonic());self.records.append({'time':self.elapsed,'type':'takeover','owner':owner,'epoch':self.owner.epoch})
        if self.paused:
            self.saved_velocities.setdefault(aid,a.get_velocity());a.set_simulate_physics(False)
        if self.camera_target!=aid:self.make_camera(aid,'driver')

    def release_control(self):
        self.owner.release();d=self.drivers[self.scene['ego']];d.manual=None;d.rejoin()
        if self.specs[self.scene['ego']]['behavior']=='parked':
            self.actors[self.scene['ego']].apply_control(carla.VehicleControl(brake=1));self.actors[self.scene['ego']].set_simulate_physics(False)
        self.ego_rejoining=self.override
        self.records.append({'time':self.elapsed,'type':'release','note':'平滑恢复物理跟随；本次偏离标记保留' if self.override else '自动控制'})

    def pause(self,paused):
        if self.preview or self.paused==paused:return
        commands=[]
        if paused:
            for aid,a in self.actors.items():
                self.saved_velocities[aid]=a.get_velocity();commands.append(carla.command.SetSimulatePhysics(a.id,False))
        else:
            for aid,a in self.actors.items():
                physical=(not self.recording or aid==self.scene['ego'] and self.override) and self.specs[aid]['behavior']!='parked'
                if aid==self.scene['ego'] and self.owner.owner!='auto':physical=True
                commands.append(carla.command.SetSimulatePhysics(a.id,physical))
                if physical and aid in self.saved_velocities:commands.append(carla.command.ApplyTargetVelocity(a.id,self.saved_velocities[aid]))
        errors=[r.error for r in self.client.apply_batch_sync(commands,False) if r.has_error()]
        if errors:raise RuntimeError('暂停状态更新失败：'+'; '.join(errors))
        self.paused=paused;self.status='paused' if paused else 'running'

    def commands(self):
        for path in sorted((self.folder/'commands').glob('*.json')):
            try:command=json.loads(path.read_text(encoding='utf-8'));path.unlink()
            except (PermissionError,json.JSONDecodeError):continue
            try:
                kind=command['type']
                if kind=='stop':runtime.request_stop()
                elif kind in ('pause','resume'):self.pause(kind=='pause')
                elif kind=='look':self.apply_look(command['look'])
                elif kind=='camera':self.make_camera(command.get('actor'),command.get('view'))
                elif kind=='takeover':self.take_control(command.get('owner','keyboard'))
                elif kind=='release':self.release_control()
                elif kind=='seek':
                    if not self.preview:raise ValueError('时间拖动用于布置预览，运行中的实车不跳帧')
                    self.preview_at(command['time'])
                elif kind=='action':
                    if self.recording:raise ValueError('轨迹锁定时不能改车辆行为；仍可手动接管主车')
                    self.action(command['action'])
                elif kind=='transform':
                    if not self.preview or self.recording:raise ValueError('请在轨迹编排模式的布置预览中移动参与者')
                    self.actors[command['actor']].set_transform(transform(command['pose']))
                elif kind=='manual':
                    # Backward-compatible command endpoint for older clients.
                    if command.get('auto'):self.release_control()
                    else:
                        if self.owner.owner=='auto':self.take_control('keyboard')
                        self.owner.packet({**command,'epoch':self.owner.epoch,'seq':self.owner.last_packet+1},time.monotonic())
            except Exception as e:self.records.append({'time':self.elapsed,'type':'command_error','error':str(e)})
        packet=self.folder/'input.json'
        if packet.exists():
            try:
                stamp=packet.stat().st_mtime_ns
                if stamp!=self.last_input_mtime:
                    value=json.loads(packet.read_text(encoding='utf-8'));self.last_input_mtime=stamp
                    if value.get('run_id')==self.folder.name:self.owner.packet(value,time.monotonic())
            except (OSError,ValueError) as e:self.records.append({'time':self.elapsed,'type':'input_error','error':str(e)})

    def step_controls(self):
        self.active_clips=[]
        now=self.world.get_snapshot().timestamp.elapsed_seconds
        manual=self.owner.output(time.monotonic())
        for aid,d in self.drivers.items():
            if self.recording and not(aid==self.scene['ego'] and self.override):continue
            with d._command_lock:
                self.active_clips+=d.timeline_update(self.elapsed,self.actors)
                d.manual=[manual['steer'],manual['throttle'],manual['brake']] if aid==self.scene['ego'] and manual else None
                if self.specs[aid]['behavior']=='parked' and d.manual is None:continue
                d._step(self.dt,now)
        for aid,walker in self.walkers.items():
            if self.recording:continue
            a=self.actors[aid];spec=self.specs[aid]
            if spec.get('clips'):walker['speed']=motion_at(spec,self.elapsed)['speed']/3.6
            route=spec['route'];direction=a.get_transform().get_forward_vector()
            if route:
                p=route[walker['index']];loc=a.get_location();dx=p['x']-loc.x;dy=p['y']-loc.y;dist=math.hypot(dx,dy)
                if dist<.8:
                    if walker['index']+1<len(route):walker['index']+=1
                    else:walker['speed']=0
                if dist>.01:direction=carla.Vector3D(x=dx/dist,y=dy/dist)
            a.apply_control(carla.WalkerControl(direction=direction,speed=walker['speed']))

    def write_status(self):
        times=self.frame_times[:];fps=(len(times)-1)/(times[-1]-times[0]) if len(times)>1 else 0
        atomic_json(self.folder/'status.json',{'state':self.status,'error':self.error,'elapsed':self.elapsed,'duration':self.end_time,'actors':self.states,'events':self.records[-60:],'fired':self.fired,'collisions':self.collisions[-20:],'camera_fps':fps,'camera_time':self.camera_time,'frame_count':self.frame_count,'run_id':self.folder.name,'scene_id':self.scene['id'],'preview':self.preview,'mode':self.scene['mode'],'control':self.owner.state(),'trajectory_status':'manual_override' if self.override else 'locked' if self.recording else 'recording','active_clips':self.active_clips,'frame_index':self.frame_index,'dt':self.dt})

    def run(self):
        writer_file=None
        try:
            self.start()
            writer_file=(self.folder/'telemetry.csv').open('w',newline='',encoding='utf-8')
            writer=csv.DictWriter(writer_file,fieldnames=['time','frame','owner','id','carla_id','x','y','z','yaw','pitch','roll','speed','speed_source','steer','throttle','brake','lights']);writer.writeheader()
            if self.recording:self.apply_replay(0);self.snapshot(self.tick())
            if self.recorder:self.recorder.append(0,self.states,self.owner.state())
            for row in self.states.values():writer.writerow({'time':0,'frame':self.world.get_snapshot().frame,'owner':self.owner.owner,**row})
            while not runtime.STOP.is_set():
                started=time.perf_counter();self.commands()
                if runtime.STOP.is_set():break
                moving=not self.preview and not self.paused
                if moving:
                    if self.recording:
                        self.frame_index+=1;self.elapsed=min(self.end_time,self.frame_index*self.dt);self.apply_replay(self.elapsed)
                    else:
                        for e in self.scene['events']:
                            if e.get('enabled',True) and e['id'] not in self.fired and triggered(e['trigger'],self.elapsed,self.states,self.fired):self.action(e['action'],e['id']);self.fired[e['id']]=self.elapsed
                    if runtime.STOP.is_set():break
                    self.step_controls()
                    if not self.recording:self.frame_index+=1;self.elapsed=min(self.end_time,self.frame_index*self.dt)
                snap=self.tick();self.snapshot(snap)
                if moving:
                    self.recorder.append(self.elapsed,self.states,self.owner.state())
                    for row in self.states.values():writer.writerow({'time':self.elapsed,'frame':snap.frame,'owner':self.owner.owner,**row})
                    writer_file.flush()
                    if self.elapsed>=self.end_time:runtime.request_stop()
                self.write_status()
                # Fixed physics time, paced to wall time for interactive driving.
                runtime.STOP.wait(max(0,self.dt-(time.perf_counter()-started)))
        except Exception as e:
            self.error=str(e);self.status='error';traceback.print_exc()
        finally:
            if writer_file:writer_file.close()
            self.closed=True
            if self.camera:
                try:self.camera.stop();self.camera.destroy()
                except Exception as e:self.error=self.error or '相机清理失败：'+str(e)
            try:runtime.shutdown()
            except Exception as e:self.error=self.error or '清理失败：'+str(e)
            try:self.world.set_weather(self.original_weather);self.world.apply_settings(self.original_settings)
            except Exception as e:self.error=self.error or '恢复世界失败：'+str(e)
            remaining=[a.id for a in self.owned if a.is_alive]
            if remaining:self.error=self.error or '存在未清理参与者：'+str(remaining)
            if self.recorder:self.recorder.close(self.error)
            if self.recording:self.recording.close()
            self.status='error' if self.error else 'finished';self.write_status()
            atomic_json(self.folder/'events.json',{'events':self.records,'fired':self.fired,'collisions':self.collisions,'error':self.error,'manual_override':self.override,'remaining_owned_actor_ids':remaining,'restored_weather':weather_dict(self.world.get_weather()),'restored_synchronous_mode':self.world.get_settings().synchronous_mode})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');p.add_argument('--preview',action='store_true');args=p.parse_args();folder=Path(args.folder).resolve()
    try:Session(json.loads((folder/'scene.json').read_text(encoding='utf-8')),folder,args.preview).run()
    except Exception as e:
        atomic_json(folder/'status.json',{'state':'error','error':str(e),'actors':{},'events':[],'run_id':folder.name});raise

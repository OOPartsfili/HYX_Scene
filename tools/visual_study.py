"""Matched-view CARLA RGB study. Never reloads the map or changes saved assets."""
import json
import sys
import threading
import time
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import carla
from scene_studio.schema import look_values

OUT=ROOT/'optimization_reports/visual_study';OUT.mkdir(parents=True,exist_ok=True)
KEYS=['cloudiness','precipitation','precipitation_deposits','wind_intensity','sun_azimuth_angle','sun_altitude_angle','fog_density','fog_distance','fog_falloff','wetness','scattering_intensity','mie_scattering_scale','rayleigh_scattering_scale','dust_storm']
def weather_dict(w):return {k:getattr(w,k) for k in KEYS if hasattr(w,k)}
def main():
    only=sys.argv[1] if len(sys.argv)>1 else None
    suffix='_'+only if only else ''
    c=carla.Client('127.0.0.1',2000);c.set_timeout(10);w=c.get_world();m=w.get_map()
    original=w.get_weather();original_values=weather_dict(original);before={a.id for a in w.get_actors()}
    sensor=None;owned=[];rows=[]
    wp=m.get_waypoint(carla.Location(x=692.94,y=-637));base=wp.transform
    tf=carla.Transform(carla.Location(x=base.location.x,y=base.location.y+1.4,z=base.location.z+1.5),carla.Rotation(yaw=90))
    try:
        # Static matching objects provide car paint, contact and scale cues.
        for model,x,y in [('vehicle.audi.tt',692.94,-605),('vehicle.carlamotors.firetruck',696.44,-580)]:
            p=m.get_waypoint(carla.Location(x=x,y=y));t=p.transform;t.location.z+=.2
            a=w.try_spawn_actor(w.get_blueprint_library().find(model),t)
            if a:a.set_simulate_physics(False);owned.append(a)
        orders=[[only],[only]] if only else [['original','daylight','golden','wet','dusk'],['dusk','wet','golden','daylight','original']]
        for rep,order in enumerate(orders):
            for key in order:
                w.set_weather(original);weather=w.get_weather();look=look_values({'preset':key})
                for k,v in look['weather'].items():setattr(weather,k,v)
                w.set_weather(weather)
                bp=w.get_blueprint_library().find('sensor.camera.rgb')
                attrs={'image_size_x':1920,'image_size_y':1080,'fov':100,'sensor_tick':0,**look['camera']}
                for k,v in attrs.items():bp.set_attribute(k,str(v))
                lock=threading.Lock();samples=[];latest=[None];collect=[False]
                def receive(im):
                    with lock:
                        latest[0]=im
                        if collect[0]:samples.append((im.frame,im.timestamp,time.perf_counter()))
                sensor=w.spawn_actor(bp,tf);sensor.listen(receive)
                time.sleep(4);start=time.perf_counter();collect[0]=True
                time.sleep(12);collect[0]=False;duration=time.perf_counter()-start
                with lock:im=latest[0];frames=samples[:]
                sensor.stop();sensor.destroy();sensor=None
                if im is None or len(frames)<2:raise RuntimeError('No camera frames')
                arr=np.frombuffer(im.raw_data,np.uint8).reshape(im.height,im.width,4)[:,:,2::-1].copy()
                if rep==0:Image.fromarray(arr).save(OUT/(key+'.png'))
                wall=np.diff([f[2] for f in frames]);sim=np.diff([f[1] for f in frames])
                row={'preset':key,'repetition':rep+1,'unique_frames':len(set(f[0] for f in frames)),'wall_seconds':duration,'fps':len(set(f[0] for f in frames))/duration,'interval_p95_ms':float(np.percentile(wall,95)*1000),'sim_seconds_per_wall_second':float(sum(sim)/sum(wall)),'weather':weather_dict(weather),'camera':attrs,'mean_rgb':arr.mean(axis=(0,1)).tolist(),'white_fraction':float(np.mean(np.all(arr>=250,axis=2))),'black_fraction':float(np.mean(np.all(arr<=5,axis=2)))}
                rows.append(row);print(key,rep+1,round(row['fps'],2),'FPS',flush=True)
                (OUT/('measurements'+suffix+'.json')).write_text(json.dumps({'map':m.name,'client':c.get_client_version(),'server':c.get_server_version(),'original_weather':original_values,'camera_transform':{'x':tf.location.x,'y':tf.location.y,'z':tf.location.z,'yaw':90},'method':'1920x1080 FOV100 uncapped RGB sensor, 4s warmup +12s wall time, two repeats; callback holds latest frame, PNG after timing; editor remains running','runs':rows},ensure_ascii=False,indent=2),encoding='utf-8')
        # Isolate wetness from lighting/rain/exposure to test imported road response.
        for key,wet in ([] if only else [('road_dry',0),('road_wet',100)]):
            weather=w.get_weather()
            for k,v in original_values.items():setattr(weather,k,v)
            weather.wetness=wet;weather.precipitation=0;weather.precipitation_deposits=wet
            w.set_weather(weather);bp=w.get_blueprint_library().find('sensor.camera.rgb')
            for k,v in {'image_size_x':1920,'image_size_y':1080,'fov':100,'motion_blur_intensity':0}.items():bp.set_attribute(k,str(v))
            latest=[None];sensor=w.spawn_actor(bp,tf);sensor.listen(lambda im:latest.__setitem__(0,im));time.sleep(5)
            im=latest[0];sensor.stop();sensor.destroy();sensor=None
            arr=np.frombuffer(im.raw_data,np.uint8).reshape(im.height,im.width,4)[:,:,2::-1].copy();Image.fromarray(arr).save(OUT/(key+'.png'))
    finally:
        if sensor:
            sensor.stop();sensor.destroy()
        for a in reversed(owned):
            if a.is_alive:a.destroy()
        w.set_weather(original)
        (OUT/('restoration'+suffix+'.json')).write_text(json.dumps({'weather_before':original_values,'weather_after':weather_dict(w.get_weather()),'remaining_owned_ids':[a.id for a in owned if a.is_alive],'before_actor_count':len(before),'after_actor_count':len(w.get_actors())},indent=2),encoding='utf-8')
if __name__=='__main__':main()

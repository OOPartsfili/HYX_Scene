"""Read-only camera survey of all seven junctions and lane marking transitions."""
import carla,time,json,queue
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]/'optimization_reports/map10_lane_audit';OUT.mkdir(parents=True,exist_ok=True)
c=carla.Client('127.0.0.1',2000);c.set_timeout(15);w=c.get_world()
views=[('j53',-1000,-298,0,75),('j160',-333,-298,0,85),('j196',327,-298,0,65),('j232',-1000,243,0,65),('j34',698,-742,8.738,90),('j216',698,796,8.738,85),('j257',698,-395,8.738,75),('taper29',698,-654,8.738,50),('taper9',698,664,8.738,60),('taper6',704,-480,8.738,60),('city3',-84,-298,0,45),('local12',324,-660,.151,35),('ramp24',600,-850,8.738,85),('underpass',698,-298,0,55)]
bp=w.get_blueprint_library().find('sensor.camera.rgb')
for k,v in {'image_size_x':1600,'image_size_y':1600,'fov':75,'sensor_tick':0.15,'motion_blur_intensity':0}.items():bp.set_attribute(k,str(v))
q=queue.Queue(maxsize=2)
def receive(im):
 try:q.put_nowait(im)
 except queue.Full:pass
sensor=None;rows=[];before={a.id for a in w.get_actors()}
try:
 sensor=w.spawn_actor(bp,carla.Transform(carla.Location(z=200)));sensor.listen(receive)
 for name,x,y,z,height in views:
  sensor.set_transform(carla.Transform(carla.Location(x=x,y=y,z=z+height),carla.Rotation(pitch=-90,yaw=0)))
  target=w.get_snapshot().frame+10
  while not q.empty():q.get_nowait()
  deadline=time.monotonic()+20;im=None
  while time.monotonic()<deadline:
   try:sample=q.get(timeout=2)
   except queue.Empty:continue
   if sample.frame>=target:im=sample;break
  if im is None:raise RuntimeError('No fresh frames; no world ticking was attempted')
  im.save_to_disk(str(OUT/(name+'.png')));rows.append(dict(id=name,x=x,y=y,z=z,height=height,camera_z=z+height,fov=75,frame=im.frame));print(name,flush=True)
finally:
 if sensor:sensor.stop();sensor.destroy()
 (OUT/'views.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
 (OUT/'cleanup.json').write_text(json.dumps({'sensor_alive':sensor.is_alive if sensor else False,'original_actor_ids_missing':sorted(before-{a.id for a in w.get_actors()})},indent=2),encoding='utf-8')

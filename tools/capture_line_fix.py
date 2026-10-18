import carla,time,json,queue,sys
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]/'optimization_reports/map10_lane_fix'
phase=sys.argv[1];dest=OUT/phase;dest.mkdir(exist_ok=True)
if any(dest.glob('*.png')):raise RuntimeError('Do not overwrite existing comparison captures')
views=json.loads((OUT.parent/'map10_lane_audit/views.json').read_text());views=[v for v in views if v['id'] in ['local12','j53','j232']]
c=carla.Client('127.0.0.1',2000);c.set_timeout(20);w=c.get_world();settings=w.get_settings();weather=str(w.get_weather())
bp=w.get_blueprint_library().find('sensor.camera.rgb')
for k,v in {'image_size_x':1600,'image_size_y':1600,'fov':75,'sensor_tick':0.15,'motion_blur_intensity':0}.items():bp.set_attribute(k,str(v))
q=queue.Queue(maxsize=2)
def receive(im):
 try:q.put_nowait(im)
 except queue.Full:pass
sensor=None
try:
 sensor=w.spawn_actor(bp,carla.Transform(carla.Location(z=200)));sensor.listen(receive)
 for v in views:
  sensor.set_transform(carla.Transform(carla.Location(x=v['x'],y=v['y'],z=v['camera_z']),carla.Rotation(pitch=-90,yaw=0)))
  target=w.get_snapshot().frame+35
  while not q.empty():q.get_nowait()
  deadline=time.monotonic()+30;im=None
  while time.monotonic()<deadline:
   try:s=q.get(timeout=2)
   except queue.Empty:continue
   if s.frame>=target:im=s;break
  if im is None:raise RuntimeError('No fresh RGB frames')
  im.save_to_disk(str(dest/(v['id']+'.png')));print(phase,v['id'],flush=True)
finally:
 if sensor:sensor.stop();sensor.destroy()
 (dest/'capture.json').write_text(json.dumps({'weather':weather,'settings':str(settings),'views':views,'sensor_destroyed':not sensor.is_alive if sensor else True},indent=2),encoding='utf-8')

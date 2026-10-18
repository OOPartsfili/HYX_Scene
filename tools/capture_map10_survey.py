"""Photograph candidate regions with one owned camera; never changes world settings."""
import carla,time,json,queue,math
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]/'optimization_reports/map10_survey'
c=carla.Client('127.0.0.1',2000);c.set_timeout(15);w=c.get_world();m=w.get_map()
views=[
 ('A_elevated',15,-2,450),('B_merge',29,-3,40),
 ('C_arterial',3,-2,220),('D_crossroads',2,-2,480),
 ('E_residential',1,-2,230),('F_local',12,-1,340),
 ('G_wide',20,-3,320),('H_long',8,-1,1000),
 ('I_curve',24,2,260)]
bp=w.get_blueprint_library().find('sensor.camera.rgb')
for k,v in {'image_size_x':1280,'image_size_y':720,'fov':95,'sensor_tick':0.15,'motion_blur_intensity':0}.items():bp.set_attribute(k,str(v))
q=queue.Queue(maxsize=2)
def receive(im):
    try:q.put_nowait(im)
    except queue.Full:pass
sensor=None;rows=[];before={a.id for a in w.get_actors()}
try:
    sensor=w.spawn_actor(bp,carla.Transform(carla.Location(z=200)));sensor.listen(receive)
    for name,rid,lid,s in views:
        p=m.get_waypoint_xodr(rid,lid,s)
        if not p:continue
        base=p.transform
        row={'id':name,'road':rid,'lane':lid,'s':s,'x':base.location.x,'y':base.location.y,'z':base.location.z,'yaw':base.rotation.yaw,'lane_width':p.lane_width,'lane_change':str(p.lane_change)}
        for kind,height,back,pitch in [('street',1.7,0,0),('aerial',85,95,-35)]:
            yaw=base.rotation.yaw;a=math.radians(yaw)
            tf=carla.Transform(carla.Location(x=base.location.x-back*math.cos(a),y=base.location.y-back*math.sin(a),z=base.location.z+height),carla.Rotation(yaw=yaw,pitch=pitch))
            sensor.set_transform(tf);target=w.get_snapshot().frame+8
            while not q.empty():q.get_nowait()
            deadline=time.monotonic()+20;im=None
            while time.monotonic()<deadline:
                try:sample=q.get(timeout=2)
                except queue.Empty:continue
                if sample.frame>=target:im=sample;break
            if im is None:raise RuntimeError('No fresh frames; existing preview may have stopped ticking')
            filename=name+'_'+kind+'.png';im.save_to_disk(str(OUT/filename));row[kind]=filename
        rows.append(row);print(name,round(row['x'],1),round(row['y'],1),round(row['z'],1),flush=True)
finally:
    if sensor:sensor.stop();sensor.destroy()
    (OUT/'camera_regions.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    (OUT/'camera_cleanup.json').write_text(json.dumps({'sensor_id':sensor.id if sensor else None,'sensor_alive':sensor.is_alive if sensor else False,'original_actor_ids_missing':sorted(before-{a.id for a in w.get_actors()}),'world_settings':str(w.get_settings()),'world_weather':str(w.get_weather())},indent=2),encoding='utf-8')

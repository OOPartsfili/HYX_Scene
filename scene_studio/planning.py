"""Compile road-connected paths and a scrub preview without spawning actors."""
import math
import carla
from agents.navigation.global_route_planner import GlobalRoutePlanner
from scene_studio.routing import MapDAO
from scene_studio.timeline import motion_at,pose_on_path,motion_hash

class Planner:
    def __init__(self,wmap):self.map=wmap;self.router=None
    def path(self,actor,duration):
        start=carla.Location(x=actor['x'],y=actor['y'],z=actor['z'])
        wp=self.map.get_waypoint(start);width=wp.lane_width if wp else 3.5
        if actor['model'].startswith(('walker.','static.')) or actor['behavior']=='parked':
            points=[(actor['x'],actor['y'],actor['z'],actor['yaw'])]
            points.extend((p['x'],p['y'],p['z'],actor['yaw']) for p in actor.get('route',[]))
        else:
            if not wp:raise ValueError(actor['name']+' 没有可驾驶路线')
            waypoints=[wp]
            if actor.get('route'):
                if self.router is None:self.router=GlobalRoutePlanner(MapDAO(self.map,2));self.router.setup()
                for p in actor['route']:
                    end=carla.Location(x=p['x'],y=p['y'],z=p.get('z',start.z))
                    try:segment=self.router.trace_route(start,end)
                    except Exception as e:raise ValueError(actor['name']+' 的路线点不连通：'+str(e))
                    if not segment:raise ValueError('路线点不连通')
                    waypoints.extend(v for v,_ in segment);start=end
            else:
                speed=max([actor['speed']]+[c.get('value',0) for c in actor.get('clips',[]) if c['type']=='speed'])
                maxdist=max(80,speed/3.6*duration+25);distance=0;seen={wp.id}
                while distance<maxdist and len(waypoints)<50000:
                    choices=[p for p in wp.next(2) if p.id not in seen]
                    if not choices:break
                    nxt=min(choices,key=lambda p:(abs((p.transform.rotation.yaw-wp.transform.rotation.yaw+180)%360-180),p.road_id,p.lane_id))
                    distance+=wp.transform.location.distance(nxt.transform.location);waypoints.append(nxt);seen.add(nxt.id);wp=nxt
            points=[(p.transform.location.x,p.transform.location.y,p.transform.location.z,p.transform.rotation.yaw) for p in waypoints]
        path=[];distance=0
        for i,(x,y,z,yaw) in enumerate(points):
            if path:
                delta=math.hypot(x-path[-1][1],y-path[-1][2])
                if delta<.02:continue
                distance+=delta
            if actor['model'].startswith('walker.') and i+1<len(points):yaw=math.degrees(math.atan2(points[i+1][1]-y,points[i+1][0]-x))
            path.append([distance,x,y,z,yaw])
        if len(path)==1:path.append([.01,*path[0][1:]])
        return path,width
    def compile(self,scene):
        tracks={};warnings=[];dt=max(.1,scene['duration']/1500)
        for actor in scene['actors']:
            path,width=self.path(actor,scene['duration']);frames=[];distance=0;speed=actor['speed'] if actor.get('start_in_motion') else 0;previous=0
            for i in range(math.ceil(scene['duration']/dt)+1):
                t=min(i*dt,scene['duration']);target=motion_at(actor,t,width)
                target_speed=0 if actor['behavior']=='parked' else target['speed']
                if target['brake'] is not None:target_speed=0
                acceleration=actor['acceleration'] if target_speed>speed else actor['deceleration']
                speed+=max(-acceleration*3.6*(t-previous),min(acceleration*3.6*(t-previous),target_speed-speed))
                distance+=max(0,speed)/3.6*(t-previous);previous=t
                pose=pose_on_path(path,distance,target['offset'])
                if distance>=path[-1][0]:speed=0
                frames.append([round(t,4),pose['x'],pose['y'],pose['z'],pose['yaw'],speed])
            if any(c['type']=='follow' for c in actor.get('clips',[])):warnings.append(actor['name']+'：布置预演显示速度上限，实际跟车速度随前车状态计算；录制后可精确重放')
            if any(e.get('enabled',True) and e['action'].get('actor')==actor['id'] and e['action']['type'] in ('speed','brake','lane_change','follow','route','offset','destroy','spawn') for e in scene.get('events',[])):
                warnings.append(actor['name']+'：条件事件依赖实际运行状态，简化预演不计算这些事件，请运行录制后检查实际轨迹')
            tracks[actor['id']]={'path':path,'lane_width':width,'frames':frames}
        return {'motion_hash':motion_hash(scene),'duration':scene['duration'],'tracks':tracks,'warnings':warnings}

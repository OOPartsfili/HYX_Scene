"""Validate candidate centerline routes with live map API; spawns no actors."""
import sys,json,collections,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import carla,networkx as nx
from scene_studio.routing import MapDAO
from agents.navigation.global_route_planner import GlobalRoutePlanner
OUT=ROOT/'optimization_reports/map10_survey'
c=carla.Client('127.0.0.1',2000);c.set_timeout(15);w=c.get_world();m=w.get_map()
topo=m.get_topology();graph=nx.Graph()
for a,b in topo:
    graph.add_edge(a.road_id,b.road_id)
    for n in b.next(1):graph.add_edge(b.road_id,n.road_id)
components=[sorted(v) for v in nx.connected_components(graph)]
router=GlobalRoutePlanner(MapDAO(m,2));router.setup()
def pose(p):
    t=p.transform
    return {'road':p.road_id,'lane':p.lane_id,'s':p.s,'x':t.location.x,'y':t.location.y,'z':t.location.z,'yaw':t.rotation.yaw}
def trace(rid,lane,s,distance):
    start=m.get_waypoint_xodr(rid,lane,s);cur=start;path=[cur];visited={cur.id};dist=0
    while dist<distance:
        choices=[n for n in cur.next(2) if n.id not in visited]
        if not choices:break
        nxt=min(choices,key=lambda n:abs((n.transform.rotation.yaw-cur.transform.rotation.yaw+180)%360-180));dist+=cur.transform.location.distance(nxt.transform.location);path.append(nxt);visited.add(nxt.id);cur=nxt
    route=router.trace_route(start.transform.location,cur.transform.location)
    gap=max((a.transform.location.distance(b.transform.location) for a,b in zip(path,path[1:])),default=0)
    ground=[]
    # Raycasts inspect collision geometry under sampled waypoints; no world mutation.
    for p in path[::max(1,len(path)//10)]:
        l=p.transform.location
        hits=w.cast_ray(carla.Location(x=l.x,y=l.y,z=l.z+1),carla.Location(x=l.x,y=l.y,z=l.z-2))
        ground.append({'waypoint':pose(p),'hits':[{'x':h.location.x,'y':h.location.y,'z':h.location.z,'label':str(h.label)} for h in hits]})
    return {'start':pose(start),'end':pose(cur),'requested_m':distance,'continuous_m':dist,'max_step_m':gap,'road_sequence':list(dict.fromkeys(p.road_id for p in path)),'router_points':len(route),'router_end_error_m':route[-1][0].transform.location.distance(cur.transform.location) if route else None,'path':[pose(p) for p in path],'surface_checks':ground}
specs=[('A_elevated',15,-2,200,500),('B_merge',29,-3,60,220),('C_arterial',3,-2,100,400),('D_crossroads',2,-2,500,230),('E_residential',1,-2,100,450),('F_local',12,-1,200,350),('G_wide',20,-3,100,450),('H_long',8,-1,700,600),('I_curve',24,2,420,350)]
results={}
for name,rid,lane,s,dist in specs:
    try:results[name]=trace(rid,lane,s,dist);print(name,round(results[name]['continuous_m']),results[name]['road_sequence'],results[name]['router_points'],flush=True)
    except Exception as e:results[name]={'error':str(e)};print(name,str(e),flush=True)
cross=[]
for a,b in [(results['A_elevated']['start'],results['C_arterial']['start']),(results['C_arterial']['start'],results['E_residential']['start'])]:
    try:r=router.trace_route(carla.Location(x=a['x'],y=a['y'],z=a['z']),carla.Location(x=b['x'],y=b['y'],z=b['z']));cross.append({'from':a['road'],'to':b['road'],'points':len(r)})
    except Exception as e:cross.append({'from':a['road'],'to':b['road'],'error':str(e)})
(OUT/'validation.json').write_text(json.dumps({'components':components,'regions':results,'cross_region_routes':cross},indent=2),encoding='utf-8')
print('Components',components);print('Cross-region',cross)

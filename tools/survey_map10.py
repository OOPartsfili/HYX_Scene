"""Read-only live topology survey; does not tick or alter the world."""
import json, hashlib, collections, sys, math
from pathlib import Path
import xml.etree.ElementTree as ET
import carla
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'optimization_reports/map10_survey'
OUT.mkdir(parents=True,exist_ok=True)
c=carla.Client('127.0.0.1',2000);c.set_timeout(20)
w=c.get_world();m=w.get_map();xml=m.to_opendrive();root=ET.fromstring(xml)
disk=Path(r'D:\carla\carla\Unreal\CarlaUE4\Content\package\Maps\map10\OpenDrive\map10.xodr')
def pose(p):
    t=p.transform
    return dict(road=p.road_id,section=p.section_id,lane=p.lane_id,s=p.s,x=t.location.x,y=t.location.y,z=t.location.z,yaw=t.rotation.yaw,width=p.lane_width,junction=p.junction_id,change=str(p.lane_change))
points=m.generate_waypoints(5);groups=collections.defaultdict(list)
for p in points:groups[p.road_id].append(p)
rows=[]
for r in root.findall('road'):
    rid=int(r.get('id'));ps=groups[rid]
    if not ps:continue
    xyz=[p.transform.location for p in ps]
    mid=min(ps,key=lambda p:abs(p.s-float(r.get('length'))/2))
    rows.append(dict(id=rid,length=float(r.get('length')),junction=r.get('junction'),lanes=sorted({p.lane_id for p in ps}),bounds=[min(v.x for v in xyz),min(v.y for v in xyz),max(v.x for v in xyz),max(v.y for v in xyz)],z=[min(v.z for v in xyz),max(v.z for v in xyz)],mid=pose(mid)))
topology=m.get_topology()
dead=[]
for a,b in topology:
    if not b.next(2):dead.append(pose(b))
settings=w.get_settings()
boxes=w.get_level_bbs(carla.CityObjectLabel.Buildings)
semantic_count=len(boxes)
if not boxes:boxes=[b for b in w.get_level_bbs(carla.CityObjectLabel.Any) if 3<b.extent.z<80 and 3<b.extent.x<100 and 3<b.extent.y<100]
data=dict(map=m.name,client=c.get_client_version(),server=c.get_server_version(),xodr_sha256=hashlib.sha256(xml.encode()).hexdigest(),disk_xodr_sha256=hashlib.sha256(disk.read_bytes()).hexdigest(),xml_equal_normalized=ET.tostring(root)==ET.tostring(ET.parse(disk).getroot()),road_count=len(root.findall('road')),junction_count=len(root.findall('junction')),waypoint_count=len(points),spawn_count=len(m.get_spawn_points()),topology_count=len(topology),dead_ends=dead,roads=rows,waypoints=[pose(p) for p in points],building_box_count=semantic_count,approximate_boxes=[dict(x=b.location.x,y=b.location.y,z=b.location.z,ex=b.extent.x,ey=b.extent.y,ez=b.extent.z) for b in boxes],settings=dict(sync=settings.synchronous_mode,dt=settings.fixed_delta_seconds),actor_ids=[a.id for a in w.get_actors()])
(OUT/'survey.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
fig,ax=plt.subplots(figsize=(16,12))
for b in boxes:
    ax.add_patch(plt.Rectangle((b.location.x-b.extent.x,b.location.y-b.extent.y),b.extent.x*2,b.extent.y*2,color='#dce1e5',alpha=.7))
pts=ax.scatter([p.transform.location.x for p in points],[p.transform.location.y for p in points],c=[p.transform.location.z for p in points],s=2,cmap='viridis')
for r in rows:
    if r['length']>90 and r['junction']=='-1':ax.text(r['mid']['x'],r['mid']['y'],str(r['id']),fontsize=9,color='crimson',bbox=dict(facecolor='white',alpha=.7,edgecolor='none',pad=1))
ax.invert_yaxis();ax.set_aspect('equal');ax.set_xlabel('CARLA X (m)');ax.set_ylabel('CARLA Y (m; positive downward)');ax.set_title('map10 — driving waypoints and approximate structure footprints\nLabels: road ID; color: road elevation (absolute Z, not clearance)');fig.colorbar(pts,ax=ax,label='Z (m)');fig.tight_layout();fig.savefig(OUT/'overview.png',dpi=130)
print(json.dumps({k:data[k] for k in ['map','xml_equal_normalized','road_count','junction_count','waypoint_count','spawn_count','topology_count','building_box_count','settings']},indent=2))
for r in sorted(rows,key=lambda r:-r['length']):
    print('road',r['id'],'len',round(r['length']),'lanes',r['lanes'],'junction',r['junction'],'bounds',[round(v) for v in r['bounds']],'z',[round(v,1) for v in r['z']])
print('dead ends',len(dead))

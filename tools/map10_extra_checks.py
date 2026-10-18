import json,sys,xml.etree.ElementTree as ET,hashlib,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import carla
from scene_studio.routing import MapDAO
from agents.navigation.global_route_planner import GlobalRoutePlanner
out=ROOT/'optimization_reports/map10_survey'
c=carla.Client('127.0.0.1',2000);c.set_timeout(15);w=c.get_world();m=w.get_map();xml=ET.fromstring(m.to_opendrive());router=GlobalRoutePlanner(MapDAO(m,2));router.setup()
rows=[]
for a,b in [((3,2,220),(1,2,230)),((24,2,420),(29,-2,40)),((15,-2,200),(3,-2,220)),((29,-5,40),(28,-4,60))]:
    p=m.get_waypoint_xodr(*a);q=m.get_waypoint_xodr(*b)
    row={'from':a,'to':b}
    try:
        path=router.trace_route(p.transform.location,q.transform.location)
        row.update(points=len(path),roads=list(dict.fromkeys(v.road_id for v,_ in path)))
    except Exception as e:row['error']=str(e)
    rows.append(row)
r=next(r for r in xml.findall('road') if r.get('id')=='267')
src=Path(r'D:\carla\carla\Import\STORE\map10')
imports={p.name:{'bytes':p.stat().st_size,'md5':hashlib.md5(p.read_bytes()).hexdigest()} for p in src.iterdir() if p.suffix in ['.fbx','.xodr','.xml','.geojson']}
data={'routes':rows,'road267':ET.tostring(r,encoding='unicode'),'import_files':imports,'traffic_lights':len(w.get_actors().filter('traffic.traffic_light')),'traffic_signs':len(w.get_actors().filter('traffic.*')),'waypoint_landmarks':len(m.get_all_landmarks())}
(out/'extra_checks.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in data.items() if k!='road267'},indent=2));print('267 road links',ET.tostring(r.find('link'),encoding='unicode'));print('267 lane links',[ET.tostring(v,encoding='unicode') for v in r.findall('lanes/laneSection/left/lane/link')])

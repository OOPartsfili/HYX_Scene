"""Read-only lane marking and topology audit, with candidates requiring visual review."""
import json,collections,math,xml.etree.ElementTree as ET
from pathlib import Path
import carla
OUT=Path(__file__).resolve().parents[1]/'optimization_reports/map10_lane_audit';OUT.mkdir(parents=True,exist_ok=True)
c=carla.Client('127.0.0.1',2000);c.set_timeout(15);w=c.get_world();m=w.get_map();root=ET.fromstring(m.to_opendrive())
def pose(p):
 t=p.transform;return dict(road=p.road_id,lane=p.lane_id,s=p.s,x=t.location.x,y=t.location.y,z=t.location.z,yaw=t.rotation.yaw,width=p.lane_width)
marks=[]
for r in root.findall('road'):
 sections=r.findall('lanes/laneSection')
 for si,sec in enumerate(sections):
  secstart=float(sec.get('s'));secend=float(sections[si+1].get('s')) if si+1<len(sections) else float(r.get('length'))
  for lane in sec.findall('./left/lane')+sec.findall('./right/lane')+sec.findall('./center/lane'):
   lid=int(lane.get('id'));ms=lane.findall('roadMark')
   for i,mark in enumerate(ms):
    start=secstart+float(mark.get('sOffset'));end=secstart+float(ms[i+1].get('sOffset')) if i+1<len(ms) else secend
    row=dict(road=int(r.get('id')),junction=int(r.get('junction')),lane=lid,lane_type=lane.get('type'),start=start,end=end,length=end-start,mark=mark.attrib)
    if lane.get('type')=='driving':
     p=m.get_waypoint_xodr(row['road'],lid,(start+end)/2)
     if p:row['pose']=pose(p)
    marks.append(row)
sampled=m.generate_waypoints(2);jumps={};narrows={};adjmissing={};solidallows={};brokenblocks={}
for p in sampled:
 for n in p.next(2):
  gap=p.transform.location.distance(n.transform.location);yaw=abs((n.transform.rotation.yaw-p.transform.rotation.yaw+180)%360-180)
  if gap>3 or yaw>25:
   k=(p.road_id,p.lane_id,n.road_id,n.lane_id)
   row={'from':pose(p),'to':pose(n),'distance':gap,'yaw_change':yaw}
   if k not in jumps or gap>jumps[k]['distance']:jumps[k]=row
 if p.lane_width<2.5:
  k=(p.road_id,p.lane_id)
  if k not in narrows or p.lane_width<narrows[k]['width']:narrows[k]=pose(p)
 if p.is_junction:continue
 for side in ['left','right']:
  n=getattr(p,'get_'+side+'_lane')();mark=getattr(p,side+'_lane_marking');flag=getattr(carla.LaneChange,side.capitalize())
  same=n and n.lane_type==carla.LaneType.Driving and n.lane_id*p.lane_id>0
  if not same:continue
  row={'pose':pose(p),'side':side,'neighbor_lane':n.lane_id,'type':str(mark.type),'mark_permission':str(mark.lane_change),'waypoint_permission':str(p.lane_change)}
  k=(p.road_id,p.lane_id,side,str(mark.type),str(mark.lane_change))
  if mark.type==carla.LaneMarkingType.NONE:adjmissing.setdefault(k,row)
  if mark.type in [carla.LaneMarkingType.Solid,carla.LaneMarkingType.SolidSolid] and bool(p.lane_change & flag):solidallows.setdefault(k,row)
  if mark.type==carla.LaneMarkingType.Broken and not bool(p.lane_change & flag):brokenblocks.setdefault(k,row)
out={'map':m.name,'mark_records':marks,'sampled_waypoints':len(sampled),'centerline_jumps':list(jumps.values()),'narrow_lanes':list(narrows.values()),'unmarked_same_direction_candidates':list(adjmissing.values()),'solid_allows_candidates':list(solidallows.values()),'broken_blocks_candidates':list(brokenblocks.values())}
(OUT/'audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
for k in ['centerline_jumps','narrow_lanes','unmarked_same_direction_candidates','solid_allows_candidates','broken_blocks_candidates']:
 print(k,len(out[k]));print(json.dumps(out[k][:16],ensure_ascii=False))
print('mixed marks',[(r['road'],r['lane'],round(r['start']),round(r['end']),r['mark']['type'],r['mark'].get('laneChange')) for r in marks if ' ' in r['mark']['type'] and r['mark']['type']!='solid solid' and r['lane_type']=='driving'])

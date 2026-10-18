import carla,json,math,xml.etree.ElementTree as ET
from pathlib import Path
def intersections(a,b):
 out=[]
 for p,q in zip(a,a[1:]):
  rx=q[0]-p[0];ry=q[1]-p[1]
  for u,v in zip(b,b[1:]):
   sx=v[0]-u[0];sy=v[1]-u[1];den=rx*sy-ry*sx
   if abs(den)<1e-9:continue
   dx=u[0]-p[0];dy=u[1]-p[1];t=(dx*sy-dy*sx)/den;h=(dx*ry-dy*rx)/den
   if 0<=t<=1 and 0<=h<=1:
    pt=[p[0]+t*rx,p[1]+t*ry,p[2]]
    if not any(math.hypot(pt[0]-o[0],pt[1]-o[1])<.1 for o in out):out.append(pt)
 return out
OUT=Path(__file__).resolve().parents[1]/'optimization_reports/map10_lane_audit'
c=carla.Client('127.0.0.1',2000);c.set_timeout(15);m=c.get_world().get_map();root=ET.fromstring(m.to_opendrive())
def sample(rid,lid,start,end):
 ps=[];s=start
 while s<end:
  p=m.get_waypoint_xodr(rid,lid,s)
  if p:ps.append(p)
  s+=.5
 return ps
def xy(p):return [p.transform.location.x,p.transform.location.y,p.transform.location.z]
def boundary(p):
 # Outer edge is the driver's right for both signs of standard right-hand driving lanes.
 t=p.transform;r=t.get_right_vector();l=t.location
 return [l.x+r.x*p.lane_width/2,l.y+r.y*p.lane_width/2,l.z]
details=[]
for jid,specs in [(53,[(158,-2),(159,2)]),(232,[(249,2),(249,3),(250,-2),(250,-3)]),(34,[(35,3),(41,3)]),(216,[(219,3),(223,3)]),(257,[(263,-4),(264,3)])]:
 paths=[]
 for road in root.findall('road'):
  if int(road.get('junction'))!=jid:continue
  ids={int(l.get('id')) for l in road.findall('.//lane') if l.get('type')=='driving'}
  for lid in ids:
   ps=sample(int(road.get('id')),lid,.01,float(road.get('length'))-.01)
   if len(ps)>1:paths.append({'road':int(road.get('id')),'lane':lid,'points':[xy(p) for p in ps]})
 for rid,lid in specs:
  road=next(r for r in root.findall('road') if r.get('id')==str(rid));ps=sample(rid,lid,.01,float(road.get('length'))-.01);edge=[boundary(p) for p in ps];cross=[]
  for path in paths:
   if path['road']==rid:continue
   for pt in intersections(edge,path['points']):cross.append({'road':path['road'],'lane':path['lane'],'point':pt})
  details.append({'junction':jid,'road':rid,'lane':lid,'s_range':[0,float(road.get('length'))],'start':edge[0],'end':edge[-1],'api_right_marking':str(ps[len(ps)//2].right_lane_marking.type),'edge':edge,'crossing_routes':cross})
 (OUT/('junction'+str(jid)+'_paths.json')).write_text(json.dumps(paths),encoding='utf-8')
(OUT/'line_conflicts.json').write_text(json.dumps(details,indent=2),encoding='utf-8')
for d in details:print(d['junction'],d['road'],d['lane'],d['api_right_marking'],'start',d['start'],'end',d['end'],'crossings',[(x['road'],x['lane']) for x in d['crossing_routes']])

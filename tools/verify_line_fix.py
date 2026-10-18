import re,json,collections
from pathlib import Path
import numpy as np
out=Path(__file__).resolve().parents[1]/'optimization_reports/map10_lane_fix'
def read(name):
    text=(out/name).read_text();a={}
    for key,n,raw in re.findall(r'(\w+):\s*\*(\d+)\s*\{\s*a:\s*([^}]+)',text):a.setdefault(key,[]).append(np.fromstring(raw,sep=','))
    v=a['Vertices'][0].reshape(-1,3);ix=a['PolygonVertexIndex'][0].astype(int)
    return a,v[np.where(ix<0,-ix-1,ix).reshape(-1,3)]
def facekeys(p):return [tuple(sorted(tuple(x) for x in np.round(f,3))) for f in p]
result={}
for name,expected,applied in [('markings','markings_fixed.fbx','markings_applied.fbx'),('road','road_surface_fixed.fbx','road_surface_applied.fbx')]:
    a,p=read(expected);b,q=read(applied)
    match=collections.Counter(facekeys(p))==collections.Counter(facekeys(q))
    assert match
    result[name]={'triangles':len(q),'geometry_matches_at_0_001_cm':match,'uv_channels':len(b['UV']),
                  'material_triangle_counts':np.bincount(b['Materials'][0].astype(int)).tolist()}
    assert len(a['UV'])==len(b['UV'])==2
before=json.loads((out/'before/capture.json').read_text());after=json.loads((out/'after/capture.json').read_text())
assert before==after
result['identical_capture_parameters']=True
result['map_data']=json.loads((out/'live_xodr_verified.json').read_text())
old=json.loads((out/'status_before.json').read_text());now=json.loads((out/'status_after.json').read_text())
result['preview_preserved']=old['run_id']==now['run_id'] and old['state']==now['state'] and now['error'] is None
assert result['preview_preserved']
result['scope']='Three lane-marking fixes; no separate FPS benchmark was run.'
(out/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

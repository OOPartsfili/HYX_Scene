"""Remove only complete marking triangles within the four confirmed strips.

Preserve source vertices, normals, tangents, all UV channels and material indices.
FBX coordinates here are UE centimetres with Y negated by Unreal's exporter.
"""
import re,json,numpy as np
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]/'optimization_reports/map10_lane_fix'
src=(OUT/'markings_original.fbx').read_text(encoding='utf-8')
pat=re.compile(r'(\b(\w+):\s*\*)(\d+)(\s*\{\s*a:\s*)([^}]+)(\})')
arrays=list(pat.finditer(src))
def arr(label,dtype=float):
 block=next(a for a in arrays if a[2]==label);return np.fromstring(block[5],sep=',',dtype=dtype)
verts=arr('Vertices').reshape(-1,3);indices=arr('PolygonVertexIndex',int)
assert len(indices)%3==0 and np.all(indices.reshape(-1,3)[:,-1]<0)
faces=np.where(indices<0,-indices-1,indices).reshape(-1,3);points=verts[faces];centers=points.mean(1)
specs=[('j53_east',-993, -319.26,-278.15),('j53_west',-1007,-319.26,-278.15),('j232_inner',-993,224.98,258.49),('j232_outer',-989.5,224.98,258.49)]
removed=np.zeros(len(faces),dtype=bool);rows=[]
for name,x,y0,y1 in specs:
 # All vertices must lie in the strip, avoiding crosswalk/arrow geometry crossing it.
 near=(np.abs(points[:,:,0]-x*100).max(1)<8)&(points[:,:,1].min(1)>=-y1*100-2)&(points[:,:,1].max(1)<=-y0*100+2)&(np.abs(points[:,:,2]).max(1)<5)
 ids=np.where(near)[0]
 rows.append({'id':name,'x':x,'y_range':[y0,y1],'triangles':len(ids),'min_xyz_cm':points[near].min((0,1)).tolist() if len(ids) else None,'max_xyz_cm':points[near].max((0,1)).tolist() if len(ids) else None})
 removed|=near
keep=~removed
metadata={'triangle_count_before':len(faces),'triangle_count_removed':int(removed.sum()),'triangle_count_after':int(keep.sum()),'strips':rows,'bounds_cm':[verts.min(0).tolist(),verts.max(0).tolist()]}
(OUT/'mesh_clip_plan.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
print(json.dumps(metadata,indent=2))
if not all(r['triangles']>0 for r in rows):raise RuntimeError('Expected strips not found; inspect transforms')
assert removed.sum()<len(faces)*.01,'Unexpectedly broad mesh removal'
def replace(match):
 label=match[2];n=int(match[3]);raw=match[5].strip().split(',');assert len(raw)==n,(label,n,len(raw))
 if label=='PolygonVertexIndex' or label=='UVIndex':mask=np.repeat(keep,3)
 elif label in ['Normals','Binormals','Tangents']:mask=np.repeat(keep,9)
 elif label=='Materials':mask=keep
 else:return match[0]
 assert len(mask)==n,(label,len(mask),n)
 values=[v.strip() for v,k in zip(raw,mask) if k]
 return match[1]+str(len(values))+match[4]+','.join(values)+'\n\t\t'+match[6]
fixed=pat.sub(replace,src)
(OUT/'markings_fixed.fbx').write_text(fixed,encoding='utf-8')

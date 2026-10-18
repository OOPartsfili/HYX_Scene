"""Fill RoadRunner's inlaid marking holes using the removed triangles and neighboring road UVs."""
import re,json,hashlib,shutil
from pathlib import Path
import numpy as np
import clip_line_mesh as clip
out=clip.OUT
src=(out/'map10_Roads_Road_Layer0Node.fbx').read_text()
arrays=list(clip.pat.finditer(src));a={}
for m in arrays:a.setdefault(m[2],[]).append(np.fromstring(m[5],sep=','))
v=a['Vertices'][0].reshape(-1,3);ix=a['PolygonVertexIndex'][0].astype(int)
faces=np.where(ix<0,-ix-1,ix).reshape(-1,3);p=v[faces]
fill=clip.points[clip.removed];q=fill.reshape(-1,3)
uvs=[uv.reshape(-1,2)[inds.astype(int)].reshape(-1,3,2) for uv,inds in zip(a['UV'],a['UVIndex'])]
attrs={k:a[k][0].reshape(-1,3,3) for k in ['Normals','Binormals','Tangents']}
newuv=[[] for _ in uvs];newattrs={k:[] for k in attrs};distances=[]
centers=p.mean(1)[:,:2];flat=(np.abs(p[:,:,2]).max(1)<5)
for point in q:
    near=(np.abs(centers-point[:2])<1500).all(1)&flat
    ids=np.where(near)[0];tri=p[ids,:,:2]
    candidates=[]
    for i,j in [(0,1),(1,2),(2,0)]:
        edge=tri[:,j]-tri[:,i];delta=point[:2]-tri[:,i]
        denom=(edge*edge).sum(1)
        t=np.clip((delta*edge).sum(1)/np.maximum(denom,1e-12),0,1)
        closest=tri[:,i]+t[:,None]*edge
        d=((closest-point[:2])**2).sum(1)
        n=int(d.argmin());candidates.append((d[n],ids[n],i,j,t[n]))
    d,idx,i,j,t=min(candidates)
    distances.append(float(d**.5))
    for k,uv in enumerate(uvs):newuv[k].append((1-t)*uv[idx,i]+t*uv[idx,j])
    for k,attr in attrs.items():newattrs[k].append((1-t)*attr[idx,i]+t*attr[idx,j])
assert max(distances)<=25.01, max(distances)
fillindices=np.arange(len(v),len(v)+len(q));fillindices[2::3]=-fillindices[2::3]-1
counters={}
def replace(m):
    key=m[2];n=int(m[3]);idx=counters.get(key,0);counters[key]=idx+1
    if key=='Vertices':extra=q.ravel()
    elif key=='PolygonVertexIndex':extra=fillindices
    elif key in newattrs:extra=np.array(newattrs[key]).ravel()
    elif key=='Materials':extra=np.zeros(len(fill),dtype=int)
    elif key=='UV':extra=np.array(newuv[idx]).ravel()
    elif key=='UVIndex':extra=np.arange(len(a['UV'][idx])//2,len(a['UV'][idx])//2+len(q))
    else:return m[0]
    text=','.join(str(int(x)) if key in ['Materials','UVIndex','PolygonVertexIndex'] else format(float(x),'.15g') for x in extra)
    return m[1]+str(n+len(extra))+m[4]+m[5].strip()+','+text+'\n\t\t'+m[6]
(out/'road_surface_fixed.fbx').write_text(clip.pat.sub(replace,src))
content=Path(r'D:\carla\carla\Unreal\CarlaUE4\Content')
rel='package/Static/Road/map10/map10_Roads_Road_Layer0Node.uasset';original=content/rel;backup=out/'backup'/rel
manifest=json.loads((out/'backup_manifest.json').read_text())
if not backup.exists():
    backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,backup)
    manifest.append({'path':str(original),'backup':str(backup),'sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'size':original.stat().st_size})
    (out/'backup_manifest.json').write_text(json.dumps(manifest,indent=2))
result={'road_triangles_before':len(faces),'inlay_fill_triangles':len(fill),'road_triangles_after':len(faces)+len(fill),'max_uv_sampling_distance_cm':max(distances),'original_road_arrays_preserved':True}
(out/'surface_fill.json').write_text(json.dumps(result,indent=2));print(result)

import json,hashlib,shutil,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'optimization_reports/map10_lane_fix';OUT.mkdir(exist_ok=True,parents=True)
content=Path(r'D:\carla\carla\Unreal\CarlaUE4\Content')
paths=['package/Maps/map10/LaneMarkingYellow1_Marking.uasset','package/Maps/map10/LaneMarking1_Marking.uasset','package/Static/RoadLine/map10/map10_Roads_Marking_Layer0Node.uasset','package/Maps/map10/OpenDrive/map10.xodr','package/Maps/map10/TM/map10.bin']
backup=OUT/'backup';backup.mkdir(exist_ok=True)
manifest=[]
for rel in paths:
 p=content/rel;target=backup/rel;target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists():raise RuntimeError('Backup already exists; do not overwrite original snapshot')
 shutil.copy2(p,target);manifest.append({'path':str(p),'backup':str(target),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size})
(OUT/'backup_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
for endpoint in ['status','current-scene']:
 data=json.load(urllib.request.urlopen('http://127.0.0.1:8877/api/'+endpoint));(OUT/(endpoint+'_before.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print('Backed up',len(manifest),'files')

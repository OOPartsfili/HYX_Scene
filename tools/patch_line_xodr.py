import re,json,xml.etree.ElementTree as ET,shutil,hashlib
from pathlib import Path
import carla
out=Path(__file__).resolve().parents[1]/'optimization_reports/map10_lane_fix'
rel='package/Maps/map10/OpenDrive/map10.xodr'
source=(out/'backup'/rel).read_text();changes=[]
targets={'158':{'-2'},'159':{'2'},'250':{'-2','-3'}}
def patchroad(m):
    road=m[0];rid=re.search(r'\bid="([^"]+)"',road)[1]
    if rid not in targets:return road
    def patchlane(lm):
        lane=lm[0];lid=re.search(r'\bid="([^"]+)"',lane)[1]
        if lid not in targets[rid]:return lane
        def mark(mm):
            before=mm[0];after=before
            for attr,val in [('type','none'),('width','0.0000000000000000e+00'),('color','standard')]:
                after=re.sub(r'\b'+attr+r'="[^"]*"',attr+'="'+val+'"',after)
            changes.append({'road':rid,'lane':lid,'before':before,'after':after});return after
        return re.sub(r'<roadMark\b[^>]+/>',mark,lane)
    return re.sub(r'<lane\b[^>]*>.*?</lane>',patchlane,road,flags=re.S)
fixed=re.sub(r'<road\b[^>]*>.*?</road>',patchroad,source,flags=re.S)
assert len(changes)==8,len(changes)
before=ET.fromstring(source);after=ET.fromstring(fixed)
for root in [before,after]:
    for lane in root.findall('.//lane'):
        for mark in lane.findall('roadMark'):lane.remove(mark)
assert ET.tostring(before)==ET.tostring(after),'Non-marking road data changed'
m=carla.Map('map10',fixed)
checks=[]
for rid,lids in targets.items():
    length=float(before.find("road[@id='%s']"%rid).get('length'))
    for lid in lids:
        for s in [.01,length/2,length-.01]:
            wp=m.get_waypoint_xodr(int(rid),int(lid),s)
            assert wp and wp.right_lane_marking.type==carla.LaneMarkingType.NONE,(rid,lid,s)
            checks.append({'road':int(rid),'lane':int(lid),'s':s,'right_marking':str(wp.right_lane_marking.type)})
cache=out/'map10_fixed.bin';m.cook_in_memory_map(str(cache))
assert cache.exists() and cache.stat().st_size>100000
(out/'map10_fixed.xodr').write_text(fixed,encoding='utf-8')
content=Path(r'D:\carla\carla\Unreal\CarlaUE4\Content')
shutil.copy2(out/'map10_fixed.xodr',content/rel)
shutil.copy2(cache,content/'package/Maps/map10/TM/map10.bin')
result={'changes':changes,'geometry_and_topology_unchanged':True,'checks':checks,'cache_bytes':cache.stat().st_size}
(out/'xodr_patch_result.json').write_text(json.dumps(result,indent=2));print('Updated 8 roadMark records; geometry and topology unchanged; rebuilt TM cache.')

import json,time,sys,math
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];URL='http://127.0.0.1:8877/api/'
def api(path,data=None):
    r=requests.get(URL+path,timeout=15) if data is None else requests.post(URL+path,json=data,timeout=15)
    r.raise_for_status();return r.json()
names=sys.argv[1:] or [f'Scene1_0{i}' for i in range(1,7)]+['Scene2','pedestrian_demo']
out=ROOT/'optimization_reports/visual_study/template_smoke.json'
rows=[r for r in json.loads(out.read_text(encoding='utf-8')) if r['scene'] not in names] if out.exists() else []
for name in names:
    scene=api('scenes/'+name);scene['duration']=25 if name=='pedestrian_demo' else 3
    run=api('start',{'scene':scene});last=None;end=time.monotonic()+60
    while time.monotonic()<end:
        state=api('status')
        if state['state'] in ('finished','error'):break
        if state.get('actors'):last=state
        time.sleep(.2)
    else:api('command',{'type':'stop'});raise TimeoutError(name)
    p=ROOT/'studio_data/runs'/run['run_id'];time.sleep(.15)
    events=json.loads((p/'events.json').read_text(encoding='utf-8'))
    assert not state.get('error'),(name,state)
    assert not events['remaining_owned_actor_ids'],(name,events)
    assert last and last['frame_count']>0,(name,last)
    if name=='pedestrian_demo':
        assert set(events['fired'])=={'cross','brake'},events
        target=scene['actors'][1]['route'][-1];p=last['actors']['ped']
        assert math.hypot(p['x']-target['x'],p['y']-target['y'])<.9,p
        assert not events['collisions'],events['collisions'][:3]
    rows.append({'scene':name,'run_id':run['run_id'],'duration':scene['duration'],'state':state['state'],'frames':state['frame_count'],'camera_fps':state['camera_fps'],'fired':events['fired'],'collisions':events['collisions'],'remaining_owned_ids':events['remaining_owned_actor_ids']})
    print(name,'PASS',state['frame_count'],'frames',flush=True)
    (ROOT/'optimization_reports/visual_study/template_smoke.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')

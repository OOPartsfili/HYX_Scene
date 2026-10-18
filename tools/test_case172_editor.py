"""Exercise the installed library through Scene Studio's actual HTTP run path."""
import json
import argparse
import sys
import time
from pathlib import Path
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).parent))
from run_case172 import OUT,read,dump,verify,code_hashes,settings_dict
BASE_URL='http://127.0.0.1:8877/api/'

def api(endpoint,value=None):
    data=None if value is None else json.dumps(value,ensure_ascii=False).encode('utf-8')
    req=urllib.request.Request(BASE_URL+endpoint,data=data,
        headers={'Content-Type':'application/json'} if data is not None else {})
    return json.load(urllib.request.urlopen(req,timeout=30))

def main():
    global BASE_URL
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8877)
    args=parser.parse_args()
    BASE_URL=f'http://127.0.0.1:{args.port}/api/'
    import carla
    from scene_studio.engine import weather_dict
    c=carla.Client('127.0.0.1',2000);c.set_timeout(15);w=c.get_world()
    if w.get_settings().synchronous_mode:raise RuntimeError('CARLA is currently occupied')
    w.wait_for_tick(5)
    if len(w.get_actors().filter('vehicle.*')):raise RuntimeError('Finish the current vehicle session first')
    before=dict(settings=settings_dict(w.get_settings()),weather=weather_dict(w.get_weather()),actor_ids=sorted(a.id for a in w.get_actors()))
    ids=sorted(s['id'] for s in api('scenes') if s['id'].startswith('Case172_'))
    expected=sorted('Case172_'+p['id'] for p in read(OUT/'catalog.json')['patterns'])
    assert ids==expected,(ids,expected)
    for sid in ids:
        loaded=api('scenes/'+sid);assert loaded==read(OUT/'scenes'/(sid+'.json')),sid
        validated=api('validate',loaded);assert validated['valid'] and validated['scene']==loaded,sid
    scene=api('scenes/Case172_P02');rid=api('start',{'scene':scene})['run_id'];folder=ROOT/'studio_data/runs'/rid
    print('EDITOR RUN',rid,flush=True)
    dump(folder/'before_world.json',before);dump(folder/'code_hashes.json',code_hashes())
    deadline=time.monotonic()+180;measured=False
    try:
        while time.monotonic()<deadline:
            status=api('status')
            if status.get('run_id')!=rid:raise RuntimeError('Editor run changed during acceptance')
            if status.get('actors') and not measured and status['state']=='running':
                geometry={}
                for aid,state in status['actors'].items():
                    a=w.get_actor(state['carla_id']);bb=a.bounding_box
                    geometry[aid]=dict(id=a.id,type=a.type_id,extent=dict(x=bb.extent.x,y=bb.extent.y,z=bb.extent.z),
                        location=dict(x=bb.location.x,y=bb.location.y,z=bb.location.z),bbox_yaw=bb.rotation.yaw)
                import hashlib
                m=w.get_map();dump(folder/'physical_setup.json',dict(actors=geometry,settings=settings_dict(w.get_settings()),map=m.name,xodr_sha256=hashlib.sha256(m.to_opendrive().encode()).hexdigest()));measured=True
            if status['state']=='error':raise RuntimeError(status.get('error','Editor worker failed'))
            if status['state']=='finished' and (folder/'events.json').exists():break
            time.sleep(1)
        else:raise RuntimeError('Editor run did not finish within 180 seconds')
    finally:
        status=api('status')
        if status.get('run_id')==rid and status['state'] in ('running','starting','paused'):
            api('command',{'type':'stop'})
            for _ in range(30):
                if api('status')['state'] in ('finished','error'):break
                time.sleep(1)
    after=dict(settings=settings_dict(w.get_settings()),weather=weather_dict(w.get_weather()),actor_ids=sorted(a.id for a in w.get_actors()))
    dump(folder/'after_world.json',after)
    result=verify(folder);result.update(transport='Scene Studio /api/start',library_ids=ids)
    dump(OUT/'editor_acceptance.json',result)
    print(json.dumps(dict(passed=result['passed'],run=rid,library_count=len(ids),failed=[x for x in result['checks'] if not x['passed']]),ensure_ascii=False,indent=2))
    if not result['passed']:sys.exit(1)

if __name__=='__main__':main()

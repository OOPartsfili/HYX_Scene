"""Exercise isolated worker via public API, including cleanup and world restore."""
import copy,json,math,time
from pathlib import Path
import requests
import carla
ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:8877/api/'
def api(path,data=None):
    r=requests.get(URL+path,timeout=15) if data is None else requests.post(URL+path,json=data,timeout=15)
    r.raise_for_status();return r.json()
def wait(predicate,seconds=20):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        s=api('status')
        if s.get('error'):raise RuntimeError(s['error'])
        if predicate(s):return s
        time.sleep(.2)
    raise TimeoutError(str(s))
def main():
    c=carla.Client('127.0.0.1',2000);c.set_timeout(10);w=c.get_world();weather=str(w.get_weather());before={a.id for a in w.get_actors()}
    scene=api('scenes/Scene1_01');scene.update(id='validation_runtime',name='自动验证 · 控车与事件',duration=25)
    ego=next(a for a in scene['actors'] if a['id']=='ego');ego.update(speed=28,offset=0,route=[{'x':ego['x'],'y':-420,'z':ego['z']}])
    lead=copy.deepcopy(ego);lead.update(id='lead',name='跟车目标',y=-604,speed=22,route=[])
    late=copy.deepcopy(ego);late.update(id='late',name='延迟生成',x=710,y=-580,speed=0,spawn_at_start=False,route=[])
    scene['actors']=[ego,lead,late];scene['events']=[]
    def event(id,sec,action):scene['events'].append({'id':id,'trigger':{'type':'time','value':sec},'action':action})
    event('follow',1,{'type':'follow','actor':'ego','target':'lead','reaction':.5,'gap':4})
    event('lights',2,{'type':'lights','actor':'ego','value':49})
    event('offset',3,{'type':'offset','actor':'ego','value':.5})
    event('spawn',4,{'type':'spawn','actor':'late'})
    event('brake',5,{'type':'brake','actor':'lead','value':.7})
    event('release',7,{'type':'speed','actor':'lead','value':30})
    event('destroy',8,{'type':'destroy','actor':'late'})
    event('offset_reset',9,{'type':'offset','actor':'ego','value':0})
    event('lane',10,{'type':'lane_change','actor':'ego','direction':'right','lanes':1,'distance':25})
    # Route is set at startup. Re-plan after lane change has had time to finish.
    event('route',22,{'type':'route','actor':'ego'})
    run=api('start',{'scene':scene});print('Run',run,flush=True)
    snapshots=[];s=wait(lambda s:s['state']=='running');snapshots.append(s)
    api('command',{'type':'pause'});s=wait(lambda s:s['state']=='paused');p=s['actors']['ego'];t=s['elapsed'];time.sleep(.8)
    q=api('status');assert abs(q['elapsed']-t)<.05
    assert math.hypot(p['x']-q['actors']['ego']['x'],p['y']-q['actors']['ego']['y'])<.15
    api('command',{'type':'resume'});wait(lambda s:s['state']=='running')
    api('command',{'type':'manual','throttle':.3,'steer':0,'brake':0});time.sleep(.3);api('command',{'type':'manual','auto':True})
    while True:
        s=api('status');snapshots.append(s)
        if s['state'] in ('finished','error'):break
        time.sleep(.5)
    path=ROOT/'studio_data/runs'/run['run_id'];events=json.loads((path/'events.json').read_text(encoding='utf-8'))
    assert not s.get('error'),s
    assert set(events['fired'])=={e['id'] for e in scene['events']},events
    assert not events['remaining_owned_actor_ids'],events
    assert max(a.get('speed',0) for ss in snapshots for a in ss.get('actors',{}).values())>15
    after={a.id for a in w.get_actors()};assert not after-before,after-before
    assert str(w.get_weather())==weather
    report={'run_id':run['run_id'],'passed':True,'pause_position_and_time':True,'all_events_fired':list(events['fired']),'owned_actors_remaining':[],'weather_restored':True,'snapshots':snapshots}
    (ROOT/'optimization_reports/visual_study/studio_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASSED',run['run_id'],flush=True)
if __name__=='__main__':main()

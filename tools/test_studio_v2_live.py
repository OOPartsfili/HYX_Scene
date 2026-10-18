"""Authoritative live tests: record/replay pose equality and manual arbitration."""
import copy,csv,json,math,time
from pathlib import Path
import requests
import carla
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'optimization_reports/studio_v2';OUT.mkdir(parents=True,exist_ok=True)
U='http://127.0.0.1:8877/api/'
def api(path,data=None):
    r=requests.get(U+path,timeout=30) if data is None else requests.post(U+path,json=data,timeout=30)
    if not r.ok:raise RuntimeError(r.text)
    return r.json()
def wait(fn,timeout=40):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        s=api('status')
        if s.get('error'):raise RuntimeError(s['error'])
        if fn(s):return s
        time.sleep(.05)
    raise TimeoutError(str(s))
def rows(rid):return [json.loads(l) for l in (ROOT/'studio_data/runs'/rid/'trajectory.jsonl').read_text(encoding='utf-8').splitlines()]
def finish():
    s=wait(lambda s:s['state']=='finished');time.sleep(.15);return s
def equality(a,b,skip=None):
    assert len(a)==len(b),(len(a),len(b));maximum=0
    for x,y in zip(a,b):
        assert abs(x['t']-y['t'])<1e-6
        assert set(x['actors'])==set(y['actors'])
        for aid,p in x['actors'].items():
            if aid==skip:continue
            q=y['actors'][aid]
            err=max(abs(p[k]-q[k]) for k in ('x','y','z','yaw','pitch','roll','speed'));maximum=max(maximum,err)
    assert maximum<.0002,maximum
    return maximum
def camera_alignment(rid,require_second_two=True):
    folder=ROOT/'studio_data/runs'/rid
    events=json.loads((folder/'events.json').read_text(encoding='utf-8'))
    samples=events.get('camera_samples',[])
    assert samples,'缺少带帧号与时间的实测截图记录'
    with (folder/'telemetry.csv').open(encoding='utf-8',newline='') as stream:
        frames={int(row['frame']):float(row['time']) for row in csv.DictReader(stream)}
    if require_second_two:assert any(2<=s['time']<3 for s in samples),'缺少第2秒的实际相机采样'
    previous=-1
    for sample in samples:
        assert sample['frame']>previous,sample
        previous=sample['frame']
        assert sample['frame'] in frames,('截图帧不在轨迹遥测中',sample)
        assert abs(frames[sample['frame']]-sample['time'])<1e-6,('截图与轨迹时间错位',sample)
        assert sample['file']==f"shot_{round(sample['time']*1000):07d}.jpg",sample
        picture=folder/sample['file']
        assert picture.is_file() and picture.stat().st_size>0,sample
    return len(samples)
def main():
    c=carla.Client('127.0.0.1',2000);c.set_timeout(10);w=c.get_world();before={a.id for a in w.get_actors()};weather=str(w.get_weather());original_settings=w.get_settings()
    scene=api('scenes/Scene1_01');ego=next(a for a in scene['actors'] if a['id']=='ego');ego.update(speed=28,offset=0,route=[],clips=[])
    lead=copy.deepcopy(ego);lead.update(id='lead',name='前车',y=-592,speed=28,role='background')
    scene.update(id='v2_acceptance',name='V2 验收 · 固定轨迹与接管',duration=10,actors=[ego,lead],events=[],mode='motion',dt=.05,look={'preset':'clear','weather':{},'camera':{}})
    ego['clips']=[{'id':'ego_speed','type':'speed','start':1,'duration':2,'value':36},{'id':'ego_lane','type':'lane_change','start':3,'duration':3,'direction':'left','lanes':1}]
    lead['clips']=[{'id':'lead_brake','type':'brake','start':5,'duration':2,'value':.7}]
    run=api('start',{'scene':scene});baseline=run['run_id'];print('baseline',baseline,flush=True);finish();base=rows(baseline)
    take=api('takes/'+baseline);assert take['complete'];assert len(base)==201
    variant=copy.deepcopy(take['scene']);variant.update(mode='environment',locked_take=baseline);variant['look']['preset']='golden'
    bad=copy.deepcopy(variant);bad['actors'][0]['speed']+=1
    assert requests.post(U+'start',json={'scene':bad}).status_code==400
    replay=api('start',{'scene':variant})['run_id'];print('replay',replay,flush=True);finish();error=equality(base,rows(replay));print('exact replay max error',error,flush=True)
    # Sensor phase need not hit exactly 2.000 s; prove the actual sensor frame
    # and timestamp match the recorded trajectory instead of guessing a name.
    baseline_images=camera_alignment(baseline);replay_images=camera_alignment(replay)
    manual=api('start',{'scene':variant})['run_id'];wait(lambda s:s['state']=='running' and s['elapsed']>=1)
    api('command',{'type':'takeover','owner':'keyboard'});s=wait(lambda s:s.get('control',{}).get('owner')=='keyboard');epoch=s['control']['epoch'];seq=0;checked=0
    while s['elapsed']<6.2:
        seq+=1;api('input',{'run_id':manual,'epoch':epoch,'seq':seq,'steer':0,'throttle':.25,'brake':0});time.sleep(.045);s=api('status')
        assert s['control']['owner']=='keyboard'
        if 3.2<s['elapsed']<6:
            a=s['actors']['ego'];assert abs(a['throttle']-.25)<.001 and a['brake']==0,a;checked+=1
    assert checked>15
    time.sleep(.5);s=api('status');assert s['control']['owner']=='keyboard' and s['control']['failsafe'];assert s['actors']['ego']['brake']>.99
    api('command',{'type':'release'});wait(lambda s:s['control']['owner']=='auto')
    api('input',{'run_id':manual,'epoch':epoch,'seq':seq+10,'throttle':1,'steer':1,'brake':0});time.sleep(.15);assert api('status')['control']['owner']=='auto'
    finish();manual_rows=rows(manual);bg_error=equality(base,manual_rows,skip='ego')
    assert any(abs(x['actors']['ego']['y']-y['actors']['ego']['y'])>.1 for x,y in zip(base,manual_rows))
    after={a.id for a in w.get_actors()};assert after==before,(after,before)
    assert str(w.get_weather())==weather
    assert w.get_settings().synchronous_mode==original_settings.synchronous_mode
    result={'baseline':baseline,'golden_replay':replay,'manual_replay':manual,'frames_compared':len(base),'pose_speed_max_error':error,'background_max_error_during_manual':bg_error,'manual_samples_during_timeline_clips':checked,'baseline_aligned_images':baseline_images,'replay_aligned_images':replay_images,'watchdog_verified':True,'stale_input_rejected':True,'world_restored':True}
    (OUT/'runtime_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print('V2 LIVE PASS',result,flush=True)
if __name__=='__main__':main()

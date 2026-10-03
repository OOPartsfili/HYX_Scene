"""Live regressions: replay batch consistency and paused manual handover momentum."""
import copy
import json
import time
from pathlib import Path
from test_studio_v2_live import api,wait,finish,rows,equality,ROOT,OUT


def main():
    prior=json.loads((OUT/'runtime_acceptance.json').read_text(encoding='utf-8'))
    base=prior['baseline'];take=api('takes/'+base);scene=copy.deepcopy(take['scene'])
    scene.update(mode='environment',locked_take=base)
    result={'baseline':base,'repeated_replays':[]}
    try:
        for look in ('daylight','golden','clear'):
            scene['look']['preset']=look
            rid=api('start',{'scene':scene})['run_id'];finish()
            error=equality(rows(base),rows(rid))
            result['repeated_replays'].append({'run':rid,'look':look,'max_pose_speed_error':error})
            print('batch replay',look,error,flush=True)
        rid=api('start',{'scene':scene})['run_id']
        wait(lambda s:s['state']=='running' and s['elapsed']>=1)
        api('command',{'type':'pause'});s=wait(lambda s:s['state']=='paused');t=s['elapsed'];speed=s['actors']['ego']['speed']
        pos={k:s['actors']['ego'][k] for k in ('x','y','z')}
        api('command',{'type':'takeover','owner':'keyboard'});s=wait(lambda s:s.get('control',{}).get('owner')=='keyboard');epoch=s['control']['epoch']
        time.sleep(.3);s=api('status')
        assert s['elapsed']==t
        assert max(abs(s['actors']['ego'][k]-v) for k,v in pos.items())<.001
        api('input',{'run_id':rid,'epoch':epoch,'seq':1,'throttle':.25,'brake':0,'steer':0})
        api('command',{'type':'resume'});s=wait(lambda s:s['state']=='running' and s['elapsed']>t)
        assert s['actors']['ego']['speed']>speed*.8,(speed,s['actors']['ego']['speed'])
        result['paused_takeover']={'run':rid,'before_speed':speed,'resumed_speed':s['actors']['ego']['speed'],'paused_pose_unchanged':True}
        api('command',{'type':'release'});wait(lambda s:s['control']['owner']=='auto')
        api('command',{'type':'stop'});finish()
        result['passed']=True
    finally:
        if api('status')['state'] in ('running','paused','preview','starting'):
            api('command',{'type':'stop'});finish()
    (OUT/'replay_edge_acceptance.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('REPLAY EDGES PASS',result,flush=True)


if __name__=='__main__':main()

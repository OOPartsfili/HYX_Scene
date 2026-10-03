"""Exercise every behavior preset on the live custom map10 with measurable motion."""
import copy
import json
from test_studio_v2_live import api,wait,finish,rows,ROOT,OUT


def main():
    template=api('scenes/Timeline_Demo');results=[]
    try:
        for name in ('cruise','stop_go','lead_brake','cut_in','overtake','follow','parked'):
            scene=copy.deepcopy(template);scene.update(id='preset_acceptance',name='预设验收 '+name,duration=25,events=[])
            scene['actors']=scene['actors'][:1];scene['actors'][0]['clips']=[]
            target=None
            if name=='follow':
                lead=copy.deepcopy(scene['actors'][0]);lead.update(id='lead',name='前车',y=-592,role='background',clips=[],speed=35)
                scene['actors'].append(lead);target='lead'
                scene=api('preset',{'scene':scene,'actor':'lead','preset':'lead_brake'})['scene']
            scene=api('preset',{'scene':scene,'actor':'ego','preset':name,'target':target})['scene']
            rid=api('start',{'scene':scene})['run_id'];print('preset',name,rid,flush=True);finish()
            frames=rows(rid);states=[r['actors']['ego'] for r in frames];speeds=[s['speed'] for s in states]
            at=lambda t:states[min(len(states)-1,round(t/.05))]
            lateral=max(s['x'] for s in states)-min(s['x'] for s in states)
            if name=='parked':assert max(speeds)<.01 and lateral<.001
            else:assert max(speeds)>20,(name,max(speeds))
            if name=='stop_go':assert at(13)['speed']<1 and at(23)['speed']>20
            if name=='lead_brake':assert at(9)['speed']<3 and at(20)['speed']>20
            if name in ('cut_in','overtake'):assert lateral>2.5,(name,lateral)
            if name=='overtake':assert abs(at(23)['x']-states[0]['x'])<1.2
            if name=='follow':
                gaps=[r['actors']['lead']['y']-r['actors']['ego']['y'] for r in frames]
                assert min(gaps)>5 and min(speeds[round(6/.05):round(15/.05)])<20,(min(gaps),min(speeds))
            status=api('status');assert not status['collisions'],(name,status['collisions'])
            results.append({'preset':name,'run':rid,'max_speed':max(speeds),'speed_at_13':at(13)['speed'],'lateral_span_m':lateral,'collisions':len(status['collisions'])})
    finally:
        if api('status')['state'] in ('running','paused','preview','starting'):
            api('command',{'type':'stop'});finish()
        (OUT/'preset_acceptance.json').write_text(json.dumps({'passed':len(results)==7,'results':results},indent=2),encoding='utf-8')
    print('ALL PRESETS PASS',results,flush=True)


if __name__=='__main__':main()

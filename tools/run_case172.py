"""Run and verify the case172 library using the same physical engine as Studio.

Examples:
  python tools/run_case172.py --ids P01 P02
  python tools/run_case172.py --all
  python tools/run_case172.py --verify PATH_TO_EXISTING_RUN
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'optimization_reports/case172_scenarios'
CODE_FILES=['scene_studio/engine.py','scene_studio/runner.py','scene_studio/planning.py','scene_studio/timeline.py',
            'scene_studio/schema.py','scene_studio/recording.py','scene_studio/routing.py',
            'optimized_control.py','traffic_math.py','scene_runtime.py','optimization_config.py',
            'agents/navigation/controller.py','agents/navigation/global_route_planner.py','agents/tools/misc.py']
def code_hashes():return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in CODE_FILES}

def read(path):return json.loads(path.read_text(encoding='utf-8'))
def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def settings_dict(s):
    return {k:getattr(s,k) for k in ['synchronous_mode','fixed_delta_seconds','no_rendering_mode','substepping','max_substeps','max_substep_delta_time','max_culling_distance','deterministic_ragdolls']}

def worker(folder):
    import carla
    from scene_studio.engine import Session,weather_dict
    class MeasuredSession(Session):
        def start(self):
            super().start()
            actor_geometry={aid:dict(id=a.id,type=a.type_id,
                extent=dict(x=a.bounding_box.extent.x,y=a.bounding_box.extent.y,z=a.bounding_box.extent.z),
                location=dict(x=a.bounding_box.location.x,y=a.bounding_box.location.y,z=a.bounding_box.location.z),
                bbox_yaw=a.bounding_box.rotation.yaw)
                for aid,a in self.actors.items() if a.type_id.startswith(('vehicle.','walker.'))}
            cache=OUT/'bounding_boxes_observed.json';known=read(cache) if cache.exists() else {}
            known.update({v['type']:{k:v[k] for k in ['extent','location','bbox_yaw']} for v in actor_geometry.values()});dump(cache,known)
            dump(folder/'physical_setup.json',dict(actors=actor_geometry,settings=settings_dict(self.world.get_settings()),
                map=self.map.name,xodr_sha256=hashlib.sha256(self.map.to_opendrive().encode()).hexdigest()))
    c=carla.Client('127.0.0.1',2000);c.set_timeout(15);w=c.get_world()
    if w.get_settings().synchronous_mode:raise RuntimeError('另有客户端占用同步世界，请先结束其运行')
    w.wait_for_tick(5)
    if len(w.get_actors().filter('vehicle.*')):raise RuntimeError('世界已有车辆，请先结束当前场景；不删除其他参与者')
    dump(folder/'code_hashes.json',code_hashes())
    before=dict(settings=settings_dict(w.get_settings()),weather=weather_dict(w.get_weather()),actor_ids=sorted(a.id for a in w.get_actors()))
    dump(folder/'before_world.json',before)
    session=MeasuredSession(read(folder/'scene.json'),folder)
    session.run()
    after=dict(settings=settings_dict(w.get_settings()),weather=weather_dict(w.get_weather()),actor_ids=sorted(a.id for a in w.get_actors()))
    dump(folder/'after_world.json',after)
    if session.error:raise RuntimeError(session.error)

def verify(folder):
    scene=read(folder/'scene.json');events=read(folder/'events.json');status=read(folder/'status.json')
    frames=[json.loads(line) for line in (folder/'trajectory.jsonl').read_text(encoding='utf-8').splitlines()]
    setup=read(folder/'physical_setup.json');before=read(folder/'before_world.json');after=read(folder/'after_world.json')
    checks=[]
    def check(name,passed,details):checks.append(dict(name=name,passed=bool(passed),details=details))
    def states(a,t0=0,t1=1e9):return [(f['t'],f['actors'][a]) for f in frames if t0<=f['t']<=t1 and a in f['actors']]
    def pair(a,b):return [(f['t'],f['actors'][a],f['actors'][b]) for f in frames if a in f['actors'] and b in f['actors']]
    def stopped(a,t0,hold):
        values=states(a,t0);longest=0;start=None
        for t,v in values:
            if v['speed']<.8:
                if start is None:start=t
                longest=max(longest,t-start)
            else:start=None
        return longest>=hold-.051,round(longest,3)
    check('完整运行',status['state']=='finished' and not events['error'] and abs(frames[-1]['t']-scene['duration'])<1e-6,dict(state=status['state'],elapsed=frames[-1]['t'],error=events['error']))
    check('固定步长与物理记录',len(frames)==round(scene['duration']/scene['dt'])+1 and all(abs(b['t']-a['t']-scene['dt'])<1e-6 for a,b in zip(frames,frames[1:])) and all(v['speed_source']=='physics' for f in frames for v in f['actors'].values()),dict(frames=len(frames),dt=scene['dt']))
    # A walker's capsule can report a zero-impulse sidewalk contact while
    # stepping down a curb. Keep the raw event and classify it only when the
    # measured trajectory also shows continued walking and a small step down.
    surface_contacts=[];impacts=[]
    for event in events['collisions']:
        aid=event['actor'];geometry=setup['actors'].get(aid,{})
        nearby=states(aid,event['time']-.2,event['time']+.2) if event.get('time') is not None else []
        surface=False
        if geometry.get('type','').startswith('walker.') and event['other']=='static.sidewalk' and all(abs(v)<1e-9 for v in event['impulse']) and len(nearby)>=5:
            a=nearby[0][1];b=nearby[-1][1]
            travel=math.hypot(b['x']-a['x'],b['y']-a['y']);drop=a['z']-b['z']
            surface=travel>.1 and 0<drop<.3 and min(v['speed'] for _,v in nearby)>1 and b['speed']>=a['speed']
        (surface_contacts if surface else impacts).append(event)
    check('无交通参与者或障碍物撞击',not impacts,dict(impacts=impacts,walker_curb_contacts=surface_contacts))
    check('全部条件事件触发',set(events['fired'])=={e['id'] for e in scene['events'] if e.get('enabled',True)},events['fired'])
    check('资源与世界恢复',not events['remaining_owned_actor_ids'] and before==after,dict(remaining=events['remaining_owned_actor_ids'],before=before,after=after))
    check('真实相机输出',len(list(folder.glob('shot_*.jpg')))>=max(3,int(scene['duration'])//2),dict(images=len(list(folder.glob('shot_*.jpg')))))
    with (folder/'telemetry.csv').open(encoding='utf-8',newline='') as stream:
        frame_times={int(row['frame']):float(row['time']) for row in csv.DictReader(stream)}
    samples=events.get('camera_samples',[])
    misaligned=[s for s in samples if s['frame'] not in frame_times or abs(frame_times[s['frame']]-s['time'])>1e-6
                or s['file']!=f"shot_{round(s['time']*1000):07d}.jpg" or not (folder/s['file']).is_file()]
    check('相机采样与正式遥测逐帧对齐',bool(samples) and not misaligned,dict(samples=len(samples),misaligned=misaligned))
    check('同步与细分物理步长',setup['settings']['synchronous_mode'] and setup['settings']['fixed_delta_seconds']==scene['dt'] and setup['settings']['substepping'],setup['settings'])
    initial_errors={a['id']:abs(frames[0]['actors'][a['id']]['speed']-(a['speed'] if a['start_in_motion'] else 0))
                    for a in scene['actors'] if a['model'].startswith('vehicle.')}
    initial_limits={a['id']:max(1.5,.03*a['speed']) if a['start_in_motion'] else 1.5
                    for a in scene['actors'] if a['model'].startswith('vehicle.')}
    check('初始车速已建立',all(error<initial_limits[aid] for aid,error in initial_errors.items()),
          dict(error_kmh=initial_errors,tolerance_kmh=initial_limits,rule='max(1.5 km/h, 3% of moving start speed)'))
    if scene['id']=='Case172_P04':
        speeds={aid:v['speed'] for aid,v in frames[0]['actors'].items()}
        check('较高车速保持案例范围72至84km/h',all(72<=v<=84 for v in speeds.values()),speeds)
    # Sensor callbacks alone are not enough to establish clearance: also check
    # oriented actor footprints at every recorded physical frame.
    def axes(v):
        r=math.radians(v['yaw']);return ((math.cos(r),math.sin(r)),(-math.sin(r),math.cos(r)))
    def separation(a,b,ea,eb):
        aa=axes(a);ab=axes(b);dx=b['x']-a['x'];dy=b['y']-a['y']
        return max(abs(dx*u+dy*v)-sum(ex*abs(ax*u+ay*v) for ex,(ax,ay) in [(ea['x'],aa[0]),(ea['y'],aa[1]),(eb['x'],ab[0]),(eb['y'],ab[1])]) for u,v in (*aa,*ab))
    known=read(OUT/'bounding_boxes_observed.json') if (OUT/'bounding_boxes_observed.json').exists() else {}
    def centered(aid,v):
        geometry=setup['actors'][aid];location=geometry.get('location',known.get(geometry['type'],{}).get('location'))
        if location is None:raise ValueError('缺少包围盒中心观测：'+geometry['type'])
        r=math.radians(v['yaw']);return {**v,'x':v['x']+math.cos(r)*location['x']-math.sin(r)*location['y'],
            'y':v['y']+math.sin(r)*location['x']+math.cos(r)*location['y'],
            'yaw':v['yaw']+geometry.get('bbox_yaw',known.get(geometry['type'],{}).get('bbox_yaw',0))}
    min_sep=1e9;worst=None
    for f in frames:
        ids=list(f['actors'])
        for i,a in enumerate(ids):
            for b in ids[i+1:]:
                if a not in setup['actors'] or b not in setup['actors']:continue
                d=separation(centered(a,f['actors'][a]),centered(b,f['actors'][b]),setup['actors'][a]['extent'],setup['actors'][b]['extent'])
                if d<min_sep:min_sep=d;worst=dict(time=f['t'],actors=[a,b])
    check('参与者轮廓无重叠',min_sep>=-.05,dict(minimum_separating_axis_gap=min_sep,at=worst))
    if (folder/'plan.json').exists():
        import numpy as np
        from scene_studio.timeline import motion_at
        plan=read(folder/'plan.json');errors={}
        for spec in scene['actors']:
            aid=spec['id']
            if not spec['model'].startswith('vehicle.') or (spec['speed']==0 and not spec['clips']):continue
            path=np.asarray(plan['tracks'][aid]['path']);starts=path[:-1,1:3];delta=path[1:,1:3]-starts
            lengths=(delta*delta).sum(axis=1);lengths=np.maximum(lengths,1e-12);max_error=0
            for t,v in states(aid):
                xy=np.array([v['x'],v['y']]);u=np.clip(((xy-starts)*delta).sum(axis=1)/lengths,0,1)
                projected=starts+u[:,None]*delta;ds=((xy-projected)**2).sum(axis=1);i=int(np.argmin(ds))
                tangent=delta[i]/math.sqrt(lengths[i]);lateral=(xy-projected[i])[0]*(-tangent[1])+(xy-projected[i])[1]*tangent[0]
                offset=motion_at(spec,t,plan['tracks'][aid]['lane_width'])['offset'];max_error=max(max_error,abs(lateral+offset))
            errors[aid]=max_error
        check('沿指定路线与变道目标行驶',max(errors.values(),default=0)<=1.5,dict(maximum_lateral_error_m=errors,limit_m=1.5))
    for spec in scene['case172']['acceptance']:
        k=spec['kind'];aid=spec.get('actor');vals=states(aid,spec.get('after',0)) if aid else []
        ok=False;detail={}
        if k=='speed_drop':
            allv=states(aid);v0=max(v['speed'] for t,v in allv if t<4);vmin=min(v['speed'] for t,v in allv if t>=4)
            ok=v0-vmin>=spec['amount'];detail=dict(early_peak=v0,later_minimum=vmin,drop=v0-vmin)
        elif k=='behind':
            distances=[b[spec['axis']]-a[spec['axis']] for t,a,b in pair(spec['follower'],spec['leader'])]
            ok=min(distances)>=spec['min_gap'];detail=dict(minimum_center_separation=min(distances),required=spec['min_gap'])
        elif k=='stopped':
            ok,hold=stopped(aid,spec['after'],spec.get('hold',1));detail=dict(longest_stop_s=hold)
        elif k=='started_then_stopped':
            peak=max(v['speed'] for _,v in states(aid));stop,hold=stopped(aid,spec['after'],1)
            ok=states(aid)[0][1]['speed']<1 and peak>=spec['min_peak'] and stop;detail=dict(peak=peak,stop_s=hold)
        elif k=='initial_headway':
            _,a,b=pair(spec['follower'],spec['leader'])[1]
            gap=math.hypot(a['x']-b['x'],a['y']-b['y'])-setup['actors'][spec['follower']]['extent']['x']-setup['actors'][spec['leader']]['extent']['x']
            thw=gap/max(.01,a['speed']/3.6);ok=0<thw<spec['maximum'];detail=dict(bumper_gap=gap,headway=thw)
        elif k=='lateral':
            axis=spec['axis'];initial=states(aid)[0][1][axis];errors=[abs(v[axis]-initial-spec['change']) for t,v in vals]
            ok=max(errors)<spec['tolerance'];detail=dict(maximum_error=max(errors),target_shift=spec['change'])
        elif k in ('overtake','cross_order'):
            ps=pair(aid,spec['reference']);axis=spec['axis'];first=ps[0][1][axis]-ps[0][2][axis];last=ps[-1][1][axis]-ps[-1][2][axis]
            ok=first*last<0 and abs(last)>3;detail=dict(initial_relative=first,final_relative=last)
        elif k=='min_speed':
            minimum=min(v['speed'] for _,v in vals);ok=minimum>=spec['minimum'];detail=dict(minimum_speed=minimum)
        elif k=='stationary':
            p=vals[0][1];span=max(math.hypot(v['x']-p['x'],v['y']-p['y']) for _,v in vals);ok=span<=spec['maximum'];detail=dict(displacement=span)
        elif k=='braking_order':
            times=[]
            for a in spec['actors']:
                initial=max(v['speed'] for _,v in states(a,0,spec['after']))
                ts=[t for t,v in states(a,spec['after']) if v['speed']<initial-4]
                times.append(min(ts) if ts else None)
            ok=all(t is not None for t in times) and all(b>=a for a,b in zip(times,times[1:]));detail=dict(actors=spec['actors'],deceleration_times=times)
        elif k=='wait_then_cross':
            release=events['fired'].get(spec['release']);axis=spec['axis'];d=spec['direction'];bound=spec['boundary']
            early=states(aid,0,release if release is not None else scene['duration'])
            crossed=[t for t,v in states(aid) if d*(v[axis]-bound)>0]
            early_cross=any(d*(v[axis]-bound)>0 for t,v in early)
            waits=[t for t,v in early if v['speed']<.8]
            hold=len(waits)*scene['dt']
            ok=release is not None and not early_cross and bool(crossed) and hold>=spec['min_wait']
            detail=dict(release_time=release,first_boundary_cross=min(crossed) if crossed else None,waiting_s=hold,early_boundary_cross=early_cross)
        elif k=='stay_before':
            maximum=max(spec['direction']*(v[spec['axis']]-spec['boundary']) for t,v in vals)
            ok=maximum<=0;detail=dict(maximum_past_boundary=maximum)
        elif k=='end_road':
            import carla
            client=carla.Client('127.0.0.1',2000);client.set_timeout(10);m=client.get_world().get_map()
            v=vals[-1][1];wp=m.get_waypoint(carla.Location(x=v['x'],y=v['y'],z=v['z']))
            lateral=math.hypot(wp.transform.location.x-v['x'],wp.transform.location.y-v['y'])
            ok=wp.road_id==spec['road'] and lateral<1.5
            detail=dict(road=wp.road_id,lane=wp.lane_id,center_error=lateral)
        elif k=='heading_change':
            yaw0=states(aid)[0][1]['yaw'];change=max(abs((v['yaw']-yaw0+180)%360-180) for t,v in vals)
            ok=change>=spec['minimum'];detail=dict(maximum_yaw_change=change)
        elif k=='parallel_gap':
            a,b=spec['actors'];ds=[math.hypot(x['x']-y['x'],x['y']-y['y']) for t,x,y in pair(a,b)]
            ok=min(ds)>=spec['minimum'] and max(ds)<=spec['maximum'];detail=dict(minimum=min(ds),maximum=max(ds))
        elif k=='path_error':
            plan=read(folder/'plan.json');path=plan['tracks'][aid]['path']
            errors=[min(math.hypot(v['x']-p[1],v['y']-p[2]) for p in path) for t,v in vals]
            ok=max(errors)<=spec['maximum'];detail=dict(maximum_sampled_path_error=max(errors))
        elif k=='two_stops':
            first=events['fired'].get(spec['between'][0]);second=events['fired'].get(spec['between'][1]);interval=states(aid,first or 0,second or 0)
            movement=math.hypot(interval[-1][1]['x']-interval[0][1]['x'],interval[-1][1]['y']-interval[0][1]['y']) if interval else 0
            pre=any(v['speed']<.8 for t,v in states(aid,0,first or 0))
            post=any(v['speed']<.8 for t,v in states(aid,second or 0))
            ok=first is not None and second is not None and movement>=spec['movement'] and pre and post
            detail=dict(creep_distance=movement,first_stop=pre,second_stop=post)
        elif k=='pedestrian_cross':
            axis=spec['axis'];travel=abs(vals[-1][1][axis]-vals[0][1][axis]);ok=travel>=spec['minimum'];detail=dict(crossing_travel=travel)
        else:raise ValueError('Unknown acceptance requirement: '+k)
        check(k+' '+str(aid or spec.get('follower','')),ok,{**spec,**detail})
    result=dict(scene=scene['id'],run=folder.name,passed=all(c['passed'] for c in checks),checks=checks,
        scene_sha256=hashlib.sha256((folder/'scene.json').read_bytes()).hexdigest(),
        trajectory_sha256=hashlib.sha256((folder/'trajectory.jsonl').read_bytes()).hexdigest(),
        source_sha256=scene['case172']['source_sha256'],xodr_sha256=setup['xodr_sha256'],
        code_hashes=read(folder/'code_hashes.json') if (folder/'code_hashes.json').exists() else {})
    dump(folder/'verification.json',result);return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--worker',type=Path);p.add_argument('--verify',type=Path);p.add_argument('--ids',nargs='+');p.add_argument('--all',action='store_true');args=p.parse_args()
    if args.worker:worker(args.worker.resolve());return
    if args.verify:
        r=verify(args.verify.resolve());print(json.dumps(r,ensure_ascii=False,indent=2))
        if not r['passed']:sys.exit(1)
        return
    if not args.all and not args.ids:p.error('选择 --all 或 --ids P01 P02')
    files=sorted((OUT/'scenes').glob('Case172_*.json'))
    if args.ids:
        wanted={'Case172_'+pid for pid in args.ids};files=[f for f in files if f.stem in wanted]
        if {f.stem for f in files}!=wanted:raise ValueError('尚未生成指定场景')
    results=[]
    for file in files:
        stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f');folder=ROOT/'studio_data/runs'/('case172_'+stamp+'_'+file.stem[-3:]);folder.mkdir(parents=True)
        (folder/'commands').mkdir()
        (folder/'scene.json').write_bytes(file.read_bytes());plan=OUT/'plans'/file.name
        if plan.exists():
            from scene_studio.schema import validate
            from scene_studio.timeline import motion_hash
            if read(plan)['motion_hash']==motion_hash(validate(read(file))):(folder/'plan.json').write_bytes(plan.read_bytes())
        print('RUN',file.stem,str(folder),flush=True)
        with (folder/'worker.log').open('w',encoding='utf-8') as log:
            proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--worker',str(folder)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONIOENCODING':'utf-8'})
            dump(folder/'process.json',dict(pid=proc.pid,started=time.time()))
            try:code=proc.wait()
            except KeyboardInterrupt:
                dump(folder/'commands/stop.json',dict(type='stop'))
                print('Stopping the current scene and restoring the world...',flush=True)
                proc.wait(timeout=30)
                raise
        if code:
            r=dict(scene=file.stem,run=folder.name,passed=False,error=(folder/'worker.log').read_text(encoding='utf-8')[-4000:])
        else:
            try:r=verify(folder)
            except Exception as exc:r=dict(scene=file.stem,run=folder.name,passed=False,error=str(exc))
        if 'error' in r:
            r.update(scene_sha256=hashlib.sha256(file.read_bytes()).hexdigest(),code_hashes=read(folder/'code_hashes.json') if (folder/'code_hashes.json').exists() else code_hashes(),checks=[])
            dump(folder/'verification.json',r)
        results.append(r);dump(OUT/'latest_batch.json',dict(results=results,complete=False))
        print('PASS' if r['passed'] else 'FAIL',file.stem,[(c['name'],c['details']) for c in r.get('checks',[]) if not c['passed']],r.get('error',''),flush=True)
        if code:break
    dump(OUT/'latest_batch.json',dict(results=results,complete=len(results)==len(files)))
    if not all(r['passed'] for r in results):sys.exit(1)

if __name__=='__main__':main()

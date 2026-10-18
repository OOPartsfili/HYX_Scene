"""Compile case-derived scenarios for the existing map10 and Scene Studio.

Run with the CARLA Python environment. Only reads the running map; generation
never loads a world or changes OpenDRIVE/Unreal assets.
"""
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import carla
from scene_studio.schema import validate
from scene_studio.planning import Planner
from build_case172_catalog import build as build_catalog,OUT

def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

class Builder:
    def __init__(self,world):
        self.world=world;self.map=world.get_map();self.planner=Planner(self.map)
        self.catalog=json.loads((OUT/'catalog.json').read_text(encoding='utf-8'))
        self.scenes=[]
    def wp(self,road,lane,s):
        p=self.map.get_waypoint_xodr(road,lane,s)
        if p is None or p.lane_type!=carla.LaneType.Driving:raise ValueError((road,lane,s))
        return p
    def actor(self,aid,road=3,lane=-2,s=65,speed=35,model='vehicle.tesla.model3',end=None):
        wp=self.wp(road,lane,s);tf=wp.transform
        a=dict(id=aid,name={'ego':'主车','lead':'前车','queue':'队尾','cross':'横向车','oncoming':'对向车','moto':'两轮车'}.get(aid,aid),
            model=model,x=tf.location.x,y=tf.location.y,z=tf.location.z+.25,yaw=tf.rotation.yaw,
            speed=speed,acceleration=2.5,deceleration=6,offset=0,behavior='scripted',snap=True,
            start_in_motion=speed>0,spawn_at_start=True,clips=[],route=[],color='#64cbb8' if aid=='ego' else '#dd9954')
        if end:
            p=self.wp(*end).transform.location;a['route']=[dict(x=p.x,y=p.y,z=p.z)]
        return a
    def scene(self,pid,actors,duration=24):
        p=copy.deepcopy(next(p for p in self.catalog['patterns'] if p['id']==pid))
        s=dict(version=2,id='Case172_'+pid,name=pid+' · '+p['name'],map=self.map.name,mode='motion',
            dt=.05,duration=duration,seed=172,ego='ego',actors=actors,events=[],
            camera=dict(width=960,height=540,fov=100,fps=10,view='chase'),look=dict(preset='clear'),
            case172={**p,'acceptance':[],'source_sha256':self.catalog['source_sha256']},
            view=dict(x=actors[0]['x'],y=actors[0]['y'],scale=1))
        self.scenes.append(s);return s
    @staticmethod
    def clip(a,kind,start,duration,**kw):
        a['clips'].append(dict(id=f"{a['id']}_{kind}_{len(a['clips'])}",type=kind,start=start,duration=duration,**kw))
    def follow(self,a,target,duration=24,start=0,headway=1.1,gap=4,reaction=.2):
        self.clip(a,'follow',start,duration,target=target,headway=headway,gap=gap,reaction=reaction)
    @staticmethod
    def event(s,eid,trigger,kind,actor=None,**kw):
        action=dict(type=kind,**kw)
        if actor:action['actor']=actor
        s['events'].append(dict(id=eid,trigger=trigger,action=action))
    @staticmethod
    def expect(s,kind,**kw):s['case172']['acceptance'].append(dict(kind=kind,**kw))
    def straight(self):
        for pid,ego_speed,lead_speed,gap,target in [
            ('P01',40,40,40,20),('P02',40,40,30,0),('P03',45,0,65,0),
            ('P04',80,80,18,50),('P07',40,18,45,18)]:
            e=self.actor('ego',speed=ego_speed);l=self.actor('lead',s=65+gap,speed=lead_speed,
                model='vehicle.carlamotors.carlacola' if pid=='P07' else 'vehicle.tesla.model3')
            s=self.scene(pid,[e,l]);self.follow(e,'lead',headway=.5 if pid=='P04' else 1.1,gap=2 if pid=='P04' else 4,reaction=0 if pid=='P04' else .2)
            if pid in ('P01','P04'):self.clip(l,'speed',4,3,value=target,easing='smooth')
            elif pid=='P02':self.clip(l,'brake',4,20,value=.7)
            self.expect(s,'speed_drop',actor='ego',amount=8)
            self.expect(s,'behind',follower='ego',leader='lead',axis='x',min_gap=4.5)
            if pid in ('P02','P03'):self.expect(s,'stopped',actor='ego',after=12,hold=1)
            if pid=='P04':self.expect(s,'initial_headway',follower='ego',leader='lead',maximum=.8)
        e=self.actor('ego',speed=0);l=self.actor('lead',s=81,speed=0)
        s=self.scene('P05',[e,l],28);e['speed']=25;e['start_in_motion']=False;self.follow(e,'lead',28)
        self.clip(l,'speed',2,4,value=22);self.clip(l,'speed',10,4,value=0)
        self.expect(s,'started_then_stopped',actor='ego',min_peak=8,after=17)
        self.expect(s,'behind',follower='ego',leader='lead',axis='x',min_gap=4.5)
        e=self.actor('ego',speed=30);mid=self.actor('middle',s=92,speed=30);l=self.actor('lead',s=119,speed=30)
        s=self.scene('P06',[e,mid,l],28);self.follow(e,'middle',28);self.follow(mid,'lead',28)
        self.clip(l,'speed',4,2,value=0)
        for aid in ['lead','middle','ego']:self.expect(s,'stopped',actor=aid,after=14,hold=1)
        for f,lid in [('ego','middle'),('middle','lead')]:self.expect(s,'behind',follower=f,leader=lid,axis='x',min_gap=4.5)
        self.expect(s,'braking_order',actors=['lead','middle','ego'],after=3)
        e=self.actor('ego',speed=36);l=self.actor('lead',s=94,speed=32);q=self.actor('queue',s=154,speed=8)
        s=self.scene('P08',[e,l,q],28);self.follow(e,'lead',duration=6);self.follow(e,'queue',start=6,duration=22)
        self.clip(l,'lane_change',3,3,direction='left',lanes=1)
        self.expect(s,'lateral',actor='lead',axis='y',change=-3.5,tolerance=.8,after=9)
        self.expect(s,'speed_drop',actor='ego',amount=15)
        self.expect(s,'behind',follower='ego',leader='queue',axis='x',min_gap=4.5)
        e=self.actor('ego',lane=-3,speed=32);l=self.actor('lead',s=110,speed=18)
        s=self.scene('P11',[e,l]);self.clip(e,'lane_change',2,4,direction='left',lanes=1);self.follow(e,'lead')
        self.expect(s,'lateral',actor='ego',axis='y',change=-3.5,tolerance=.8,after=10)
        self.expect(s,'speed_drop',actor='ego',amount=8)
        self.expect(s,'behind',follower='ego',leader='lead',axis='x',min_gap=4.5)
        e=self.actor('ego',speed=30);n=self.actor('neighbor',lane=-1,s=48,speed=45)
        s=self.scene('P12',[e,n]);self.clip(n,'speed',8,3,value=30)
        self.expect(s,'overtake',actor='neighbor',reference='ego',axis='x')
        self.expect(s,'lateral',actor='neighbor',axis='y',change=0,tolerance=.7,after=0)
        self.expect(s,'min_speed',actor='ego',after=1,minimum=25)
        # No bidirectional sharp curve exists at this chosen location. Keep the
        # actual normal oncoming relation and identify the mild road curvature.
        e=self.actor('ego',road=12,lane=-1,s=170,speed=25);n=self.actor('oncoming',road=12,lane=1,s=285,speed=25)
        s=self.scene('P22',[e,n],24)
        s['case172']['name']='双向道路正常会车';s['name']='P22 · 双向道路正常会车'
        s['case172']['transfer']+=' 当前选用road12双向道路，不宣称复现原急弯。'
        self.expect(s,'cross_order',actor='ego',reference='oncoming',axis='y')
        e=self.actor('ego',road=12,lane=-1,s=170,speed=18);n=self.actor('oncoming',road=12,lane=1,s=265,speed=18)
        p=self.actor('parked',road=12,lane=-1,s=230,speed=0);tf=self.wp(12,-1,230).transform;r=tf.get_right_vector()
        # A stopped physical vehicle settles onto the surface and can participate
        # in collision physics; don't freeze its elevated spawn transform.
        p.update(x=p['x']+r.x*2.8,y=p['y']+r.y*2.8,snap=False,behavior='scripted')
        s=self.scene('P23',[e,n,p],28)
        self.expect(s,'cross_order',actor='ego',reference='oncoming',axis='y')
        self.expect(s,'cross_order',actor='ego',reference='parked',axis='y')
        self.expect(s,'stationary',actor='parked',maximum=.1)
        e=self.actor('ego',speed=5);l=self.actor('lead',s=85,speed=5,model='vehicle.carlamotors.carlacola')
        n=self.actor('moto',lane=-1,s=48,speed=15,model='vehicle.yamaha.yzf')
        # Two-wheel suspension/wheel spin settles differently after an imposed
        # velocity. Use a physical standing start for the passing motorcycle.
        n['start_in_motion']=False
        s=self.scene('P25',[e,l,n],30);self.follow(e,'lead',30,headway=.8,gap=4)
        self.clip(l,'speed',10,2,value=0)
        self.expect(s,'overtake',actor='moto',reference='ego',axis='x')
        self.expect(s,'stopped',actor='ego',after=16,hold=1)
        self.expect(s,'behind',follower='ego',leader='lead',axis='x',min_gap=6)
    def save(self,install=False):
        records=[]
        for s in sorted(self.scenes,key=lambda s:s['id']):
            s=validate(s)
            for a in s['actors']:self.world.get_blueprint_library().find(a['model'])
            plan=self.planner.compile(s)
            dump(OUT/'scenes'/(s['id']+'.json'),s)
            dump(OUT/'plans'/(s['id']+'.json'),plan)
            if install:
                target=ROOT/'studio_data/scenes'/(s['id']+'.json')
                if target.exists() and target.read_text(encoding='utf-8')!=json.dumps(s,ensure_ascii=False,indent=2):
                    import time
                    backup=ROOT/'studio_data/history'/(s['id']+'_'+str(time.time_ns())+'.json');backup.parent.mkdir(exist_ok=True);backup.write_bytes(target.read_bytes())
                dump(target,s)
            records.append(dict(id=s['id'],name=s['name'],duration=s['duration'],actors=len(s['actors']),
                path_lengths={a:round(t['path'][-1][0],1) for a,t in plan['tracks'].items()},
                checks=len(s['case172']['acceptance'])))
        dump(OUT/'build.json',dict(map=self.map.name,xodr_sha256=hashlib.sha256(self.map.to_opendrive().encode()).hexdigest(),scenes=records,installed=install))
        print(json.dumps(records,ensure_ascii=False,indent=2))

    def junctions(self):
        def pos(actor,axis,op,value):return dict(type='position',actor=actor,axis=axis,op=op,value=value)
        def north(aid='ego',s=460,speed=18,lane=-2,end=(18,-2,140)):
            return self.actor(aid,road=17,lane=lane,s=s,speed=speed,end=end)
        def crossing(aid='cross',s=710,speed=25,lane=-2):
            return self.actor(aid,road=1,lane=lane,s=s,speed=speed,end=(2,lane,180))
        def wait_cross(s,last='cross',speed=18):
            self.event(s,'approach_stop',pos('ego','y','<=',-256),'brake','ego',value=1)
            self.event(s,'cross_clear',pos(last,'x','>=',-968),'speed','ego',value=speed)
            self.expect(s,'wait_then_cross',actor='ego',axis='y',direction=-1,boundary=-276,release='cross_clear',min_wait=1)
        def end_road(s,aid,road):self.expect(s,'end_road',actor=aid,road=road)
        # Front vehicle leaves the queue, but the ego has its own stop boundary.
        for pid,turn in [('P09',True),('P10',False)]:
            lane=-3 if turn else -2
            e=north(s=430,speed=22,lane=lane,end=(18,lane,160))
            l=north('lead',s=474,speed=22,lane=lane,end=(2,-3,120) if turn else (18,-2,160))
            s=self.scene(pid,[e,l],40);self.follow(e,'lead',40)
            self.event(s,'own_stop',pos('ego','y','<=',-256),'brake','ego',value=1)
            self.expect(s,'stopped',actor='ego',after=8,hold=2)
            if turn:
                self.expect(s,'stay_before',actor='ego',axis='y',direction=-1,boundary=-274)
                end_road(s,'lead',2)
            else:
                self.event(s,'own_restart',dict(type='after_event',event='own_stop',value=8),'speed','ego',value=22)
                end_road(s,'ego',18);end_road(s,'lead',18)
        e=crossing('ego',s=690,speed=30,lane=-3);n=north('entering',s=465,speed=18,lane=-3,end=(2,-3,180))
        s=self.scene('P13',[e,n],42)
        self.event(s,'yield',pos('ego','x','>=',-1045),'brake','ego',value=1)
        self.event(s,'entry_clear',pos('entering','x','>=',-974),'speed','ego',value=26)
        self.event(s,'follow_entering',dict(type='after_event',event='entry_clear',value=0),'follow','ego',target='entering',reaction=.2,gap=5)
        self.expect(s,'wait_then_cross',actor='ego',axis='x',direction=1,boundary=-1018,release='entry_clear',min_wait=1)
        end_road(s,'entering',2);end_road(s,'ego',2)
        for pid,count in [('P14',1),('P15',3)]:
            e=north();others=[crossing('cross' if i==0 else f'cross{i+1}',s=710-i*42) for i in range(count)]
            if count>1:
                exit_point=self.wp(2,-2,400).transform.location
                for i,a in enumerate(others):
                    a['route']=[dict(x=exit_point.x,y=exit_point.y,z=exit_point.z)]
                    if i:self.follow(a,others[i-1]['id'],48)
            s=self.scene(pid,[e,*others],48 if count>1 else 40);wait_cross(s,others[-1]['id'])
            for a in others:end_road(s,a['id'],2)
            for i in range(1,count):self.expect(s,'behind',follower=others[i]['id'],leader=others[i-1]['id'],axis='x',min_gap=5)
            end_road(s,'ego',18)
        e=north(s=455,speed=18);a=crossing(s=735,speed=25);b=crossing('cross2',s=635,speed=25)
        s=self.scene('P16',[e,a,b],48)
        self.event(s,'first_stop',pos('ego','y','<=',-248),'brake','ego',value=1)
        self.event(s,'first_clear',pos('cross','x','>=',-968),'speed','ego',value=7)
        self.event(s,'second_stop',dict(type='after_event',event='first_clear',value=4),'brake','ego',value=1)
        self.event(s,'second_clear',pos('cross2','x','>=',-968),'speed','ego',value=18)
        self.expect(s,'two_stops',actor='ego',between=['first_clear','second_stop'],movement=1)
        self.expect(s,'wait_then_cross',actor='ego',axis='y',direction=-1,boundary=-276,release='second_clear',min_wait=1)
        end_road(s,'ego',18)
        e=north(lane=-3,end=(2,-3,180));a=crossing(lane=-3)
        s=self.scene('P17',[e,a],42);wait_cross(s);end_road(s,'ego',2)
        self.expect(s,'heading_change',actor='ego',minimum=65)
        e=self.actor('ego',road=1,lane=-1,s=715,speed=18,end=(18,-1,140))
        a=self.actor('oncoming',road=2,lane=2,s=95,speed=25,end=(1,2,620))
        s=self.scene('P18',[e,a],45)
        self.event(s,'left_wait',pos('ego','x','>=',-1038),'brake','ego',value=1)
        self.event(s,'oncoming_clear',pos('oncoming','x','<=',-1040),'speed','ego',value=18)
        self.expect(s,'wait_then_cross',actor='ego',axis='x',direction=1,boundary=-1018,release='oncoming_clear',min_wait=1)
        end_road(s,'ego',18);self.expect(s,'heading_change',actor='ego',minimum=65)
        e=self.actor('ego',road=24,lane=2,s=280,speed=30)
        n=self.actor('parallel',road=24,lane=3,s=280,speed=30)
        s=self.scene('P19',[e,n],30)
        s['case172']['transfer']+=' map10的路口转向连接多为单车道，此处使用road24双车道弯路，保留并行转向关系。'
        for aid in ['ego','parallel']:self.expect(s,'heading_change',actor=aid,minimum=22)
        self.expect(s,'parallel_gap',actors=['ego','parallel'],minimum=2.7,maximum=5)
        e=north(lane=-3,s=450,speed=20,end=(2,-3,150));l=north('lead',lane=-3,s=480,speed=20,end=(18,-3,160))
        s=self.scene('P20',[e,l],38);self.follow(e,'lead',duration=5)
        end_road(s,'ego',2);end_road(s,'lead',18)
        self.expect(s,'heading_change',actor='ego',minimum=65)
        e=self.actor('ego',road=24,lane=2,s=320,speed=35);l=self.actor('lead',road=24,lane=2,s=275,speed=35)
        s=self.scene('P21',[e,l],32);self.follow(e,'lead',32)
        self.clip(l,'speed',7,3,value=16)
        for aid in ['ego','lead']:self.expect(s,'heading_change',actor=aid,minimum=15)
        self.expect(s,'speed_drop',actor='ego',amount=10)
        self.expect(s,'path_error',actor='ego',maximum=1.3)
        e=self.actor('ego',road=12,lane=1,s=70,speed=10,end=(3,4,480))
        a=self.actor('oncoming',road=12,lane=-1,s=5,speed=10,end=(12,-1,180))
        cross=self.actor('cross',road=3,lane=-1,s=550,speed=15,end=(4,-1,150))
        s=self.scene('P24',[e,a,cross],52)
        self.event(s,'approach_stop',pos('ego','y','>=',-345),'brake','ego',value=1)
        self.event(s,'cross_clear',pos('cross','x','>=',351),'speed','ego',value=12)
        self.expect(s,'cross_order',actor='ego',reference='oncoming',axis='y')
        self.expect(s,'wait_then_cross',actor='ego',axis='y',direction=1,boundary=-320,release='cross_clear',min_wait=1)
        end_road(s,'ego',3)
        self.expect(s,'heading_change',actor='ego',minimum=65)
        # Later pedestrian interaction is separately staged after ego's turn.
        e=north(s=475,speed=16,lane=-3,end=(2,-3,140))
        location=self.wp(2,-3,45).transform.location
        person=dict(id='pedestrian',name='后续横穿行人',model='walker.pedestrian.0001',
            x=location.x,y=location.y+5,z=location.z+1,yaw=-90,speed=0,behavior='walker',snap=False,
            start_in_motion=False,spawn_at_start=True,route=[dict(x=location.x,y=location.y-6,z=location.z+1)],clips=[])
        s=self.scene('P26',[e,person],42)
        self.event(s,'after_turn',pos('ego','x','>=',-974),'speed','pedestrian',value=4.5)
        self.event(s,'pedestrian_yield',dict(type='after_event',event='after_turn',value=0),'brake','ego',value=1)
        self.event(s,'pedestrian_clear',pos('pedestrian','y','<=',location.y-4),'speed','ego',value=16)
        self.expect(s,'heading_change',actor='ego',minimum=65)
        self.expect(s,'wait_then_cross',actor='ego',axis='x',direction=1,boundary=location.x-4,release='pedestrian_clear',min_wait=2)
        self.expect(s,'pedestrian_cross',actor='pedestrian',axis='y',minimum=9)
        end_road(s,'ego',2)

def main():
    p=argparse.ArgumentParser();p.add_argument('--install',action='store_true');args=p.parse_args()
    build_catalog();c=carla.Client('127.0.0.1',2000);c.set_timeout(15);w=c.get_world()
    if w.get_map().name!='package/Maps/map10/map10':raise RuntimeError('请先打开map10；本工具不切换地图')
    b=Builder(w);b.straight();b.junctions();b.save(args.install)

if __name__=='__main__':main()

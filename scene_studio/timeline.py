"""Pure timeline evaluation and control ownership; independent of CARLA."""
import bisect
import copy
import hashlib
import json
import math

CLIP_TYPES=('speed','brake','lane_change','follow','lights')
PRESETS={
    'cruise':{'name':'匀速沿线','description':'保持目标速度，沿路线行驶','speed':40,'clips':[]},
    'stop_go':{'name':'起步 · 停车 · 再起步','description':'从静止加速，减速停车后继续行驶','speed':0,'clips':[{'type':'speed','start':0,'duration':5,'value':40},{'type':'speed','start':9,'duration':3,'value':0},{'type':'speed','start':16,'duration':5,'value':35}]},
    'lead_brake':{'name':'前车急刹','description':'先匀速，6 秒制动，10 秒恢复目标速度','speed':40,'clips':[{'type':'brake','start':6,'duration':4,'value':.8},{'type':'speed','start':10,'duration':3,'value':35}]},
    'cut_in':{'name':'相邻车道切入','description':'4 秒开始向右变道，用 3 秒完成','speed':42,'clips':[{'type':'lane_change','start':4,'duration':3,'direction':'right','lanes':1}]},
    'overtake':{'name':'变道超车 · 回到原车道','description':'加速、向左变道，稍后向右返回','speed':35,'clips':[{'type':'speed','start':1,'duration':4,'value':55},{'type':'lane_change','start':2,'duration':3,'direction':'left','lanes':1},{'type':'lane_change','start':13,'duration':3,'direction':'right','lanes':1},{'type':'speed','start':17,'duration':3,'value':40}]},
    'follow':{'name':'跟车','description':'跟随另一辆车，可编辑反应延迟与车距','speed':45,'clips':[{'type':'follow','start':0,'duration':25,'target':'','reaction':.8,'gap':4,'headway':1.2}]},
    'parked':{'name':'静止障碍物','description':'保持初始布置位置','speed':0,'behavior':'parked','clips':[]},
}

def preset(name,actor,duration,target=None):
    if name not in PRESETS:raise ValueError('未知行为预设')
    p=copy.deepcopy(PRESETS[name]);actor=copy.deepcopy(actor)
    actor.update(speed=p['speed'],behavior=p.get('behavior','scripted'),start_in_motion=p['speed']>0)
    actor['clips']=[]
    for i,c in enumerate(p['clips']):
        c['id']=f'clip_{actor["id"]}_{i}'
        if c['start']>=duration:continue
        c['duration']=min(c['duration'],duration-c['start'])
        if c['type']=='follow':
            if not target or target==actor['id']:raise ValueError('跟车预设需要另一辆目标车')
            c['target']=target;c['duration']=duration-c['start']
        actor['clips'].append(c)
    return actor

def smooth(u):
    u=max(0,min(1,u));return u*u*u*(10+u*(-15+6*u))

def apply_behavior_preset(scene,actor_id,name,target=None):
    """Replace one actor's motion without breaking cross-actor event dependencies."""
    scene=copy.deepcopy(scene)
    actor=next(a for a in scene['actors'] if a['id']==actor_id)
    replacement=preset(name,actor,scene['duration'],target)
    scene['actors']=[replacement if a['id']==actor_id else a for a in scene['actors']]
    replaced=[]
    for event in scene.get('events',[]):
        action=event['action']
        if action.get('actor')==actor_id and action['type'] in ('speed','brake','offset','lane_change','follow','route') and event.get('enabled',True):
            event['replaced_action']=action
            event['action']={'type':'marker','label':'行为预设替代原运动动作'}
            replaced.append(event['id'])
    return scene,replaced

def motion_at(actor,t,lane_width=3.5):
    """Persistent speed/lane targets; brake/follow/light clips have explicit windows."""
    speed=actor.get('speed',0);offset=actor.get('offset',0);brake=None;follow=None;lights=None;active=[]
    for c in sorted(actor.get('clips',[]),key=lambda c:(c['start'],c['id'])):
        if c.get('enabled',True) is False or t<c['start']:continue
        end=c['start']+c['duration'];u=min(1,(t-c['start'])/c['duration'])
        if t<end:active.append(c['id'])
        if c['type']=='speed':
            speed=speed+(c['value']-speed)*(smooth(u) if c.get('easing','linear')=='smooth' else u)
        elif c['type']=='lane_change':
            offset+=(1 if c.get('direction','left')=='left' else -1)*c.get('lanes',1)*lane_width*smooth(u)
        elif t<end:
            if c['type']=='brake':brake=c.get('value',1)
            elif c['type']=='follow':follow=c
            elif c['type']=='lights':lights=c.get('value',3)
    return {'speed':speed,'offset':offset,'brake':brake,'follow':follow,'lights':lights,'active':active}

def motion_document(scene):
    """Fields that may affect trajectories. Appearance/camera/name are deliberately excluded."""
    return {'map':scene['map'],'duration':scene['duration'],'dt':scene.get('dt',.05),'ego':scene['ego'],
            'actors':[{k:v for k,v in a.items() if k not in ('name','color')} for a in scene['actors']],
            'events':[e for e in scene.get('events',[]) if e['action']['type'] not in ('weather','lights','marker')]}

def motion_hash(scene):return hashlib.sha256(json.dumps(motion_document(scene),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def pose_on_path(path,distance,offset=0):
    """path is [s,x,y,z,yaw]; piecewise arclength interpolation, short yaw arc."""
    if not path:raise ValueError('路线为空')
    i=max(0,min(len(path)-2,bisect.bisect_right([p[0] for p in path],distance)-1))
    a=path[i];b=path[min(i+1,len(path)-1)];u=max(0,min(1,(distance-a[0])/max(1e-9,b[0]-a[0])))
    yaw=a[4]+((b[4]-a[4]+180)%360-180)*u
    rad=math.radians(yaw)
    return {'x':a[1]+(b[1]-a[1])*u+math.sin(rad)*offset,'y':a[2]+(b[2]-a[2])*u-math.cos(rad)*offset,'z':a[3]+(b[3]-a[3])*u,'yaw':yaw}

class ControlOwner:
    """Only this arbiter chooses manual control. Timeline edits never release it."""
    def __init__(self,timeout=.35):
        self.owner='auto';self.epoch=0;self.last_packet=-1;self.last_at=None;self.timeout=timeout
        self.control={'steer':0.,'throttle':0.,'brake':1.};self.failsafe=False
    def take(self,owner,now):
        if owner not in ('keyboard','gamepad','wheel'):raise ValueError('未知手动输入设备')
        self.owner=owner;self.epoch+=1;self.last_packet=-1;self.last_at=now
        self.control={'steer':0.,'throttle':0.,'brake':1.};self.failsafe=False
        return self.epoch
    def release(self):
        self.owner='auto';self.epoch+=1;self.last_packet=-1;self.last_at=None;self.failsafe=False
    def packet(self,value,now):
        if self.owner=='auto' or value.get('epoch')!=self.epoch or value.get('seq',-1)<=self.last_packet:return False
        control={}
        for k,lo in [('steer',-1),('throttle',0),('brake',0)]:
            v=float(value.get(k,0))
            if not math.isfinite(v) or not lo<=v<=1:raise ValueError('无效手动输入 '+k)
            control[k]=v
        if control['brake']>0:control['throttle']=0
        self.control=control;self.last_packet=value['seq'];self.last_at=now;self.failsafe=False;return True
    def output(self,now):
        if self.owner=='auto':return None
        self.failsafe=self.last_at is None or now-self.last_at>self.timeout
        return {'steer':0.,'throttle':0.,'brake':1.} if self.failsafe else dict(self.control)
    def state(self):return {'owner':self.owner,'epoch':self.epoch,'failsafe':self.failsafe,'last_seq':self.last_packet}

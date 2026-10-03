"""Versioned declarative scenarios; no executable user code is accepted."""
import copy
import math
import re
from scene_studio.timeline import CLIP_TYPES

LOOKS = {
    'clear': {'name':'清晰日光 · 低雾 / 柔和曝光','weather':{'sun_altitude_angle':45,'sun_azimuth_angle':220,'cloudiness':10,'fog_density':.2,'fog_distance':150,'wetness':0,'precipitation':0,'precipitation_deposits':0},'camera':{'gamma':2.2,'motion_blur_intensity':0,'exposure_compensation':-.35,'bloom_intensity':.03}},
    'original': {'name':'当前地图 / 原始相机','weather':{},'camera':{'gamma':2.2,'motion_blur_intensity':0}},
    'daylight': {'name':'自然日光','weather':{'sun_altitude_angle':45,'sun_azimuth_angle':265,'cloudiness':25,'fog_density':.5,'fog_distance':100,'wetness':0,'precipitation':0,'precipitation_deposits':0},'camera':{'gamma':2.2,'motion_blur_intensity':0,'exposure_compensation':-.25,'bloom_intensity':.08}},
    'golden': {'name':'低角度日光','weather':{'sun_altitude_angle':18,'sun_azimuth_angle':245,'cloudiness':15,'fog_density':1.5,'fog_distance':100,'wetness':0,'precipitation':0,'precipitation_deposits':0},'camera':{'gamma':2.2,'motion_blur_intensity':0,'exposure_compensation':-.2,'bloom_intensity':.12}},
    'wet': {'name':'雨天试验 · map10 天空适配待修','weather':{'sun_altitude_angle':38,'sun_azimuth_angle':250,'cloudiness':80,'wetness':70,'precipitation':8,'precipitation_deposits':25,'fog_density':3,'fog_distance':80},'camera':{'gamma':2.2,'motion_blur_intensity':0,'exposure_compensation':0,'bloom_intensity':.08}},
    'dusk': {'name':'暮色环境','weather':{'sun_altitude_angle':-3,'sun_azimuth_angle':270,'cloudiness':30,'wetness':15,'precipitation':0,'precipitation_deposits':0,'fog_density':2,'fog_distance':100},'camera':{'gamma':2.2,'motion_blur_intensity':0,'exposure_compensation':.3,'bloom_intensity':.18}},
}
WEATHER_LIMITS={'sun_altitude_angle':(-90,90),'sun_azimuth_angle':(0,360),'cloudiness':(0,100),'precipitation':(0,100),'precipitation_deposits':(0,100),'wetness':(0,100),'wind_intensity':(0,100),'fog_density':(0,100),'fog_distance':(0,1000),'fog_falloff':(0,5)}
CAMERA_LIMITS={'gamma':(.5,4),'exposure_compensation':(-5,5),'bloom_intensity':(0,3),'motion_blur_intensity':(0,1),'fstop':(1,32),'shutter_speed':(1,2000),'iso':(50,3200),'temp':(1500,15000),'tint':(-1,1),'slope':(0,1),'toe':(0,1),'shoulder':(0,1)}
ACTIONS=['speed','brake','lane_change','offset','follow','route','lights','weather','destroy','spawn','marker','finish']
TRIGGERS=['time','position','distance','point','speed','after_event']


def number(value, low, high, label):
    if isinstance(value,bool): raise ValueError(label+' 需要数值')
    try: v=float(value)
    except (TypeError,ValueError):raise ValueError(label+' 需要数值')
    if not math.isfinite(v) or not low <= v <= high:raise ValueError(f'{label} 超出范围 {low}–{high}')
    return v


def validate(data):
    if not isinstance(data,dict):raise ValueError('场景必须为对象')
    s=copy.deepcopy(data)
    if s.get('version',1) not in (1,2):raise ValueError('不支持的场景版本')
    s['version']=2
    s.setdefault('mode','motion')
    if s['mode'] not in ('motion','environment'):raise ValueError('场景模式无效')
    s['dt']=number(s.get('dt',.05),.025,.1,'仿真步长')
    if s['dt'] not in (.025,.05,.1):raise ValueError('步长需为 0.025 / 0.05 / 0.1 秒')
    s.setdefault('locked_take',None)
    if s['mode']=='environment' and not re.fullmatch(r'[A-Za-z0-9_-]{1,90}',str(s['locked_take'] or '')):raise ValueError('环境模式需要已录制的基准轨迹')
    s.setdefault('id','scene_new')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',s['id']):raise ValueError('场景 ID 只允许字母、数字、下划线和连字符')
    s['name']=str(s.get('name','未命名场景'))[:120]
    s['map']=str(s.get('map','package/Maps/map10/map10'))
    s['duration']=number(s.get('duration',40),1,3600,'时长')
    s['seed']=int(number(s.get('seed',42),0,2147483647,'随机种子'))
    s.setdefault('view',{'x':693,'y':-537,'scale':1})
    actors=s.setdefault('actors',[]);events=s.setdefault('events',[])
    if not isinstance(actors,list) or not 1<=len(actors)<=80:raise ValueError('场景需要 1–80 个参与者')
    if not isinstance(events,list) or len(events)>200:raise ValueError('事件不能超过 200 个')
    ids=set()
    for a in actors:
        aid=a.get('id','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}',aid) or aid in ids:raise ValueError('参与者 ID 重复或不合法')
        ids.add(aid)
        a['name']=str(a.get('name',aid))[:80]
        if a.get('color') and not re.fullmatch(r'#[0-9a-fA-F]{6}',a['color']):raise ValueError('颜色需要 #RRGGBB')
        if not str(a.get('model','')).startswith(('vehicle.','walker.pedestrian.','static.prop.')):raise ValueError('参与者模型类型不支持')
        for key in ('x','y','z','yaw'):a[key]=number(a.get(key,0),-100000,100000,key)
        a['speed']=number(a.get('speed',0),0,180,'车速')
        a['acceleration']=number(a.get('acceleration',2.5),.1,12,'加速度')
        a['deceleration']=number(a.get('deceleration',6),.1,15,'减速度')
        a['offset']=number(a.get('offset',0),-10,10,'横向偏移')
        a.setdefault('behavior','scripted');a.setdefault('start_in_motion',True);a.setdefault('spawn_at_start',True)
        if a['behavior'] not in ('scripted','traffic','parked','walker'):raise ValueError('行为类型不支持')
        if a['model'].startswith('vehicle.') and a['behavior']=='walker':raise ValueError('车辆不能使用行人行为')
        if a['model'].startswith('walker.') and a['behavior'] not in ('walker','parked'):raise ValueError('行人请选择行人运动或静止行为')
        if a['model'].startswith('static.') and a['behavior']!='parked':raise ValueError('静态道具请选择静止障碍物')
        route=a.setdefault('route',[])
        if not isinstance(route,list) or len(route)>200:raise ValueError('路线点过多')
        for p in route:
            for k in ('x','y','z'):p[k]=number(p.get(k,0),-100000,100000,'路线 '+k)
    s.setdefault('ego',actors[0]['id'])
    if s['ego'] not in ids:raise ValueError('主视角参与者不存在')
    if not next(a for a in actors if a['id']==s['ego'])['model'].startswith('vehicle.'):
        raise ValueError('主车必须为车辆，才能随时切换手动驾驶')
    if not next(a for a in actors if a['id']==s['ego'])['spawn_at_start']:raise ValueError('主视角参与者必须在开始时生成')
    clip_ids=set()
    for actor in actors:
        actor['role']='ego' if actor['id']==s['ego'] else 'background'
        clips=actor.setdefault('clips',[])
        if not isinstance(clips,list) or len(clips)>200:raise ValueError('每个参与者最多 200 个时间轴片段')
        channels={}
        for clip in clips:
            cid=clip.get('id','')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',cid) or cid in clip_ids:raise ValueError('时间轴片段 ID 重复或不合法')
            clip_ids.add(cid)
            if clip.get('type') not in CLIP_TYPES:raise ValueError('时间轴片段类型无效')
            clip['start']=number(clip.get('start',0),0,s['duration'],'片段开始时间')
            clip['duration']=number(clip.get('duration',1),.1,s['duration'],'片段时长')
            if clip['start']+clip['duration']>s['duration']+1e-6:raise ValueError('片段超出场景时长')
            if not isinstance(clip.get('enabled',True),bool):raise ValueError('片段启用值需要布尔值')
            kind=clip['type'];channel='speed' if kind in ('speed','brake') else kind
            if clip.get('enabled',True):
                for start,end in channels.setdefault(channel,[]):
                    if clip['start']<end-1e-6 and clip['start']+clip['duration']>start+1e-6:raise ValueError(actor['name']+' 的同类时间轴片段重叠')
                channels[channel].append((clip['start'],clip['start']+clip['duration']))
            if kind=='speed':
                clip['value']=number(clip.get('value',40),0,180,'片段目标速度')
                if clip.get('easing','linear') not in ('linear','smooth'):raise ValueError('速度插值方式无效')
            if kind=='brake':clip['value']=number(clip.get('value',1),0,1,'片段制动力')
            if kind=='lights':clip['value']=int(number(clip.get('value',3),0,2047,'灯光状态'))
            if kind=='lane_change':
                if clip.get('direction','left') not in ('left','right'):raise ValueError('变道方向无效')
                clip['lanes']=int(number(clip.get('lanes',1),1,3,'变道车道数'))
            if kind=='follow':
                if clip.get('target') not in ids or clip['target']==actor['id']:raise ValueError('跟车片段需要另一辆目标车')
                clip['reaction']=number(clip.get('reaction',.8),0,5,'跟车反应时间')
                clip['gap']=number(clip.get('gap',4),0,100,'最小间距')
                clip['headway']=number(clip.get('headway',1.2),.1,5,'跟车时距')
            if kind in ('brake','lane_change','follow','lights') and not actor['model'].startswith('vehicle.'):raise ValueError('该片段只支持车辆')
    event_ids=set()
    for e in events:
        eid=e.get('id','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}',eid) or eid in event_ids:raise ValueError('事件 ID 重复或不合法')
        event_ids.add(eid)
    for e in events:
        t=e.setdefault('trigger',{'type':'time','value':0});a=e.setdefault('action',{'type':'marker'})
        if t.get('type') not in TRIGGERS or a.get('type') not in ACTIONS:raise ValueError('不支持的触发器或动作')
        for ref in [t.get('actor'),t.get('target'),a.get('actor'),a.get('target')]:
            if ref and ref not in ids:raise ValueError('事件引用不存在的参与者：'+str(ref))
        if a['type'] not in ('weather','marker','finish') and a.get('actor') not in ids:raise ValueError('动作需要指定参与者')
        if a['type']=='destroy' and a.get('actor')==s['ego']:raise ValueError('运行中不能销毁主车；结束场景请使用结束动作')
        if t['type']!='time' and t['type']!='after_event' and t.get('actor') not in ids:raise ValueError('触发器需要指定参与者')
        if t['type']=='distance' and t.get('target') not in ids:raise ValueError('距离条件需要目标参与者')
        if t['type']=='after_event' and (t.get('event') not in event_ids or t.get('event')==e['id']):raise ValueError('前置事件引用无效')
        if t.get('axis','y') not in ('x','y'):raise ValueError('坐标轴无效')
        if t.get('op','>=') not in ('>=','<='):raise ValueError('比较方向无效')
        t['value']=number(t.get('value',0),-100000,100000,'触发值')
        if t['type']!='position' and t['value']<0:raise ValueError('时间、速度和距离条件不能为负数')
        if t['type']=='point':
            for k in ('x','y'):t[k]=number(t.get(k,0),-100000,100000,'触发点 '+k)
        if a['type']=='speed':a['value']=number(a.get('value',50),0,180,'目标速度')
        if a['type']=='offset':a['value']=number(a.get('value',0),-10,10,'偏移量')
        if a['type']=='brake':a['value']=number(a.get('value',1),0,1,'制动力')
        if a['type']=='lane_change':
            if a.get('direction','left') not in ('left','right'):raise ValueError('变道方向无效')
            a['lanes']=int(number(a.get('lanes',1),1,3,'变道车道数'))
            a['distance']=number(a.get('distance',20),3,150,'变道距离')
        if a['type']=='follow' and a.get('target') not in ids:raise ValueError('跟车需要目标车辆')
        if a['type']=='follow':
            if a['target']==a['actor']:raise ValueError('不能跟随自己')
            a['reaction']=number(a.get('reaction',.8),0,5,'跟车反应时间')
            a['gap']=number(a.get('gap',3),0,100,'跟车最小距离')
        if a['type']=='lights':a['value']=int(number(a.get('value',3),0,2047,'车灯状态'))
        if a['type']=='weather' and a.get('preset') not in LOOKS:raise ValueError('画面预设不存在')
    # Reject cyclic event dependencies, which would otherwise wait forever.
    edges={e['id']:e['trigger'].get('event') for e in events if e['trigger']['type']=='after_event'}
    for eid in edges:
        seen=set();cur=eid
        while cur in edges:
            if cur in seen:raise ValueError('事件之间存在循环依赖')
            seen.add(cur);cur=edges[cur]
    look=s.setdefault('look',{'preset':'original','weather':{},'camera':{}})
    if look.get('preset','original') not in LOOKS:raise ValueError('画面预设不存在')
    for group,limits in [('weather',WEATHER_LIMITS),('camera',CAMERA_LIMITS)]:
        for key,val in look.setdefault(group,{}).items():
            if key not in limits:raise ValueError('不支持的画面参数 '+key)
            look[group][key]=number(val,*limits[key],key)
    camera=s.setdefault('camera',{})
    camera['width']=int(number(camera.get('width',1280),320,3840,'相机宽度'))
    camera['height']=int(number(camera.get('height',720),180,2160,'相机高度'))
    camera['fov']=number(camera.get('fov',100),30,160,'视场角')
    camera['fps']=number(camera.get('fps',20),1,60,'相机频率')
    if camera.get('view','driver') not in ('driver','chase','top'):raise ValueError('相机视角无效')
    return s


def look_values(look):
    p=copy.deepcopy(LOOKS[look.get('preset','original')])
    for group in ('weather','camera'):p[group].update(look.get(group,{}))
    return p


def triggered(trigger, elapsed, states, fired):
    kind=trigger['type'];value=trigger.get('value',0)
    if kind=='time':return elapsed>=value
    if kind=='after_event':return trigger.get('event') in fired and elapsed-fired[trigger['event']]>=value
    actor=states.get(trigger.get('actor'))
    if not actor:return False
    if kind=='position':actual=actor[trigger.get('axis','y')]
    elif kind=='point':actual=math.hypot(actor['x']-trigger['x'],actor['y']-trigger['y'])
    elif kind=='speed':actual=actor['speed']
    else:
        target=states.get(trigger.get('target'))
        if not target:return False
        actual=math.hypot(actor['x']-target['x'],actor['y']-target['y'])
    return actual<=value if trigger.get('op','>=')=='<=' else actual>=value

"""Loopback-only editor server. Start: python -m scene_studio.server"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
import mimetypes
from collections import defaultdict
from flask import Flask,Response,jsonify,request,send_from_directory
import carla
from scene_studio.schema import validate,LOOKS,ACTIONS,TRIGGERS
from scene_studio.schema import number
from scene_studio.timeline import PRESETS,preset,motion_hash
from scene_studio.planning import Planner
from scene_studio.recording import Recording

# Windows registry may incorrectly register .js as text/plain.
mimetypes.add_type('text/javascript','.js')

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'studio_data';SCENES=DATA/'scenes';RUNS=DATA/'runs';CACHE=DATA/'cache'
for d in (SCENES,RUNS,CACHE):d.mkdir(parents=True,exist_ok=True)
for template in (Path(__file__).parent/'templates').glob('*.json'):
    target=SCENES/template.name
    if not target.exists():target.write_bytes(template.read_bytes())
app=Flask(__name__,static_folder=str(Path(__file__).parent/'web'),static_url_path='/static')
app.config['MAX_CONTENT_LENGTH']=4*1024*1024
LOCK=threading.RLock();CURRENT=None;PROCESS=None;LOG=None;MAP_CACHE=None
PLAN_CACHE={};PLANNER=None;PLANNER_MAP=None


def connection():
    c=carla.Client('127.0.0.1',2000);c.set_timeout(5)
    return c,c.get_world()


def atomic(path,value):
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    for attempt in range(20):
        try:os.replace(tmp,path);return
        except PermissionError:
            if attempt==19:raise
            time.sleep(.01)


@app.before_request
def local_only():
    if request.remote_addr not in ('127.0.0.1','::1'):return jsonify(error='仅允许本机访问'),403
    if request.host.split(':')[0] not in ('127.0.0.1','localhost','[::1]'):return jsonify(error='需要本机地址'),403
    if request.method in ('POST','PUT','DELETE'):
        origin=request.headers.get('Origin')
        if origin and origin!=request.host_url.rstrip('/'):return jsonify(error='来源不匹配'),403
        if not request.is_json:return jsonify(error='需要 JSON 请求'),415


@app.errorhandler(Exception)
def errors(exc):
    from werkzeug.exceptions import HTTPException
    return jsonify(error=str(exc)),exc.code if isinstance(exc,HTTPException) else 400


@app.get('/')
def index():return send_from_directory(app.static_folder,'index.html')


@app.get('/api/connection')
def get_connection():
    try:
        c,w=connection();s=w.get_settings()
        return jsonify(connected=True,map=w.get_map().name,client=c.get_client_version(),server=c.get_server_version(),synchronous=s.synchronous_mode,no_rendering=s.no_rendering_mode,looks=LOOKS,actions=ACTIONS,triggers=TRIGGERS,presets=PRESETS)
    except Exception as exc:return jsonify(connected=False,error=str(exc),looks=LOOKS,actions=ACTIONS,triggers=TRIGGERS,presets=PRESETS)


@app.get('/api/map')
def get_map():
    global MAP_CACHE
    c,w=connection();m=w.get_map()
    if MAP_CACHE and MAP_CACHE['name']==m.name:return jsonify(MAP_CACHE)
    groups=defaultdict(list)
    for wp in m.generate_waypoints(4):
        t=wp.transform;groups[f'{wp.road_id}:{wp.section_id}:{wp.lane_id}'].append([wp.s,t.location.x,t.location.y,t.location.z,t.rotation.yaw,wp.lane_width])
    lanes=[sorted(g,key=lambda r:r[0]) for g in groups.values()]
    spawn=[]
    for t in m.get_spawn_points():spawn.append({'x':t.location.x,'y':t.location.y,'z':t.location.z,'yaw':t.rotation.yaw})
    buildings=[]
    for obj in w.get_environment_objects(carla.CityObjectLabel.Buildings):
        bb=obj.bounding_box;t=obj.transform
        buildings.append({'x':bb.location.x,'y':bb.location.y,'z':bb.location.z,'ex':bb.extent.x,'ey':bb.extent.y,'ez':bb.extent.z,'yaw':bb.rotation.yaw})
    if not buildings:
        for bb in w.get_level_bbs(carla.CityObjectLabel.Any):
            if 3<bb.extent.z<80 and 3<bb.extent.x<100 and 3<bb.extent.y<100:
                buildings.append({'x':bb.location.x,'y':bb.location.y,'z':bb.location.z,'ex':bb.extent.x,'ey':bb.extent.y,'ez':bb.extent.z,'yaw':bb.rotation.yaw})
    MAP_CACHE={'name':m.name,'lanes':lanes,'spawn_points':spawn,'buildings':buildings,'source':'CARLA topology and environment bounding boxes'}
    atomic(CACHE/'map.json',MAP_CACHE)
    return jsonify(MAP_CACHE)


@app.get('/api/blueprints')
def blueprints():
    _,w=connection();out=[]
    for b in w.get_blueprint_library():
        if b.id.startswith(('vehicle.','walker.pedestrian.','static.prop.')):
            out.append({'id':b.id,'category':b.id.split('.')[0],'colors':list(b.get_attribute('color').recommended_values) if b.has_attribute('color') else []})
    return jsonify(sorted(out,key=lambda b:b['id']))


@app.post('/api/snap')
def snap():
    from scene_studio.schema import number
    p=request.get_json();x=number(p.get('x'),-100000,100000,'x');y=number(p.get('y'),-100000,100000,'y')
    _,w=connection();wp=w.get_map().get_waypoint(carla.Location(x=x,y=y,z=float(p.get('z',0))))
    if not wp:raise ValueError('附近没有可驾驶车道')
    t=wp.transform
    return jsonify(x=t.location.x,y=t.location.y,z=t.location.z+.25,yaw=t.rotation.yaw,road=wp.road_id,lane=wp.lane_id,distance=((x-t.location.x)**2+(y-t.location.y)**2)**.5)


@app.get('/api/scenes')
def scenes():
    out=[]
    for p in SCENES.glob('*.json'):
        s=json.loads(p.read_text(encoding='utf-8'));out.append({'id':s['id'],'name':s['name'],'actors':len(s['actors']),'events':len(s['events'])})
    return jsonify(sorted(out,key=lambda s:s['name']))


def scene_path(sid):
    import re
    if not re.fullmatch('[A-Za-z0-9_-]{1,80}',sid):raise ValueError('无效场景 ID')
    return SCENES/(sid+'.json')


@app.get('/api/scenes/<sid>')
def get_scene(sid):return jsonify(validate(json.loads(scene_path(sid).read_text(encoding='utf-8'))))


@app.post('/api/scenes')
def save_scene():
    s=validate(request.get_json());p=scene_path(s['id'])
    verify_locked(s)
    if p.exists():
        history=DATA/'history';history.mkdir(exist_ok=True)
        (history/(s['id']+'_'+str(time.time_ns())+'.json')).write_bytes(p.read_bytes())
    atomic(p,s)
    return jsonify(saved=True,id=s['id'],scene=s)


@app.post('/api/validate')
def validate_scene():
    s=validate(request.get_json());verify_locked(s);return jsonify(valid=True,scene=s)


def take_folder(rid):
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,90}',rid):raise ValueError('无效录制 ID')
    return RUNS/rid


def verify_locked(scene):
    if scene['mode']=='environment':
        rec=Recording(take_folder(scene['locked_take']))
        try:rec.verify(scene)
        finally:rec.close()


def compiled(scene):
    global PLANNER,PLANNER_MAP
    key=motion_hash(scene)
    if key not in PLAN_CACHE:
        _,w=connection();m=w.get_map()
        if m.name!=scene['map']:raise ValueError('当前地图与场景地图不同')
        if PLANNER is None or PLANNER_MAP!=m.name:PLANNER=Planner(m);PLANNER_MAP=m.name
        result=PLANNER.compile(scene)
        if len(PLAN_CACHE)>=6:PLAN_CACHE.pop(next(iter(PLAN_CACHE)))
        PLAN_CACHE[key]=result
    return copy.deepcopy(PLAN_CACHE[key])


@app.post('/api/plan')
def plan():
    s=validate(request.get_json());verify_locked(s)
    with LOCK:result=compiled(s)
    if s['mode']=='environment':
        meta=json.loads((take_folder(s['locked_take'])/'take.json').read_text(encoding='utf-8'))
        result['duration']=meta['duration'];result['locked']=True;result['warnings']=[]
        for aid,frames in meta['paths'].items():
            if aid in result['tracks']:result['tracks'][aid]['frames']=frames
    return jsonify(result)


@app.post('/api/preset')
def apply_preset():
    p=request.get_json();s=validate(p['scene'])
    if s['mode']=='environment':raise ValueError('固定轨迹模式不能修改行为预设')
    target=next(a for a in s['actors'] if a['id']==p['actor'])
    replacement=preset(p['preset'],target,s['duration'],p.get('target'))
    s['actors']=[replacement if a['id']==target['id'] else a for a in s['actors']]
    disabled=[]
    for e in s['events']:
        if e['action'].get('actor')==target['id'] and e['action']['type'] in ('speed','brake','offset','lane_change','follow','route') and e.get('enabled',True):
            e['enabled']=False;disabled.append(e['id'])
    return jsonify(scene=validate(s),disabled_events=disabled)


@app.get('/api/takes')
def takes():
    result=[]
    for p in sorted(RUNS.glob('*/take.json'),reverse=True):
        try:
            h=json.loads(p.read_text(encoding='utf-8'))
            if h.get('complete'):result.append({'id':h['id'],'name':h['scene']['name'],'duration':h['duration'],'frames':h['frame_count'],'dt':h['dt'],'manual_override':h['manual_override'],'mode':h['scene']['mode']})
        except (OSError,ValueError):pass
        if len(result)>=60:break
    return jsonify(result)


@app.get('/api/takes/<rid>')
def get_take(rid):return jsonify(json.loads((take_folder(rid)/'take.json').read_text(encoding='utf-8')))


def state():
    if not CURRENT:return {'state':'idle','actors':{},'events':[]}
    p=CURRENT/'status.json'
    result=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'state':'starting','actors':{},'events':[]}
    result['run_id']=CURRENT.name
    if PROCESS and PROCESS.poll() is not None and result['state'] not in ('finished','error'):
        result.update(state='error',error='工作进程已退出，请查看日志')
    return result


@app.get('/api/status')
def get_status():
    with LOCK:return jsonify(state())


@app.get('/api/current-scene')
def current_scene():
    with LOCK:
        if not CURRENT:raise ValueError('没有当前会话')
        return jsonify(json.loads((CURRENT/'scene.json').read_text(encoding='utf-8')))


@app.post('/api/start')
def start():
    global CURRENT,PROCESS,LOG
    payload=request.get_json();s=validate(payload['scene'])
    verify_locked(s)
    with LOCK:
        if PROCESS and PROCESS.poll() is None:raise ValueError('已有预览或运行，请先停止')
        _,w=connection()
        if w.get_map().name!=s['map']:raise ValueError('地图不匹配，编辑器不会自动切换你的地图')
        if w.get_settings().synchronous_mode:raise ValueError('请使用异步世界；当前由其他客户端控制 tick')
        if w.get_settings().no_rendering_mode:raise ValueError('CARLA 当前关闭渲染，请先启用渲染模式')
        planned=compiled(s)
        run_id=time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
        CURRENT=RUNS/run_id;CURRENT.mkdir();(CURRENT/'commands').mkdir()
        atomic(CURRENT/'scene.json',s)
        atomic(CURRENT/'plan.json',planned)
        if LOG:LOG.close()
        LOG=(CURRENT/'console.txt').open('w',encoding='utf-8')
        command=[sys.executable,'-u','-m','scene_studio.engine',str(CURRENT)]
        if payload.get('preview'):command.append('--preview')
        env=os.environ.copy();env['PYTHONIOENCODING']='utf-8'
        PROCESS=subprocess.Popen(command,cwd=ROOT,env=env,stdout=LOG,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return jsonify(run_id=run_id,state='starting')


@app.post('/api/command')
def command():
    value=request.get_json()
    if value.get('type') not in ('stop','pause','resume','camera','look','action','transform','manual','takeover','release','seek'):raise ValueError('不支持的命令')
    with LOCK:
        if not PROCESS or PROCESS.poll() is not None:raise ValueError('没有正在运行的场景')
        # Validate incoming look/action edits using the same full document rules.
        scene=json.loads((CURRENT/'scene.json').read_text(encoding='utf-8'))
        if scene['mode']=='environment' and value['type'] in ('action','transform'):raise ValueError('固定轨迹模式不能修改车辆行为或位置')
        if value['type']=='takeover' and value.get('owner','keyboard') not in ('keyboard','gamepad','wheel'):raise ValueError('手动输入设备无效')
        if value['type']=='seek':value['time']=number(value.get('time'),0,scene['duration'],'预演时间')
        if value['type'] in ('camera','transform'):
            if value.get('actor',scene['ego']) not in {a['id'] for a in scene['actors']}:raise ValueError('参与者不存在')
        if value['type']=='camera' and value.get('view','driver') not in ('driver','chase','top'):raise ValueError('相机视角无效')
        if value['type']=='transform':
            for key in ('x','y','z','yaw'):value['pose'][key]=number(value['pose'].get(key),-100000,100000,key)
        if value['type']=='manual':
            for key,low in [('steer',-1),('throttle',0),('brake',0)]:value[key]=number(value.get(key,0),low,1,key)
        if value['type']=='look':scene['look']=value['look'];value['look']=validate(scene)['look']
        if value['type']=='action':
            test=copy.deepcopy(scene);test['events']=[{'id':'manual','trigger':{'type':'time','value':0},'action':value['action']}];value['action']=validate(test)['events'][0]['action']
        atomic(CURRENT/'commands'/f'{time.time_ns()}.json',value)
    return jsonify(queued=True)


@app.post('/api/input')
def manual_input():
    value=request.get_json()
    with LOCK:
        if not PROCESS or PROCESS.poll() is not None or not CURRENT:raise ValueError('没有正在运行的场景')
        if value.get('run_id')!=CURRENT.name:raise ValueError('输入属于另一场运行')
        value['epoch']=int(number(value.get('epoch'),0,1e9,'控制权代数'))
        value['seq']=int(number(value.get('seq'),0,1e12,'输入序号'))
        for k,lo in [('steer',-1),('throttle',0),('brake',0)]:value[k]=number(value.get(k,0),lo,1,k)
        atomic(CURRENT/'input.json',value)
    return jsonify(queued=True)


@app.get('/api/frame')
def frame():
    with LOCK:folder=CURRENT
    if not folder or not (folder/'frame.jpg').exists():return '',204
    return Response((folder/'frame.jpg').read_bytes(),mimetype='image/jpeg',headers={'Cache-Control':'no-store'})


@app.get('/api/video')
def video():
    def generate():
        last=None
        while True:
            folder=CURRENT
            if folder:
                p=folder/'frame.jpg'
                try:
                    stamp=p.stat().st_mtime_ns
                    if stamp!=last:
                        data=p.read_bytes();last=stamp
                        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+data+b'\r\n'
                except OSError:pass
            time.sleep(.05)
    return Response(generate(),mimetype='multipart/x-mixed-replace; boundary=frame')


@app.get('/api/runs')
def runs():
    out=[]
    for p in sorted(RUNS.iterdir(),reverse=True)[:40]:
        try:
            s=json.loads((p/'scene.json').read_text(encoding='utf-8'));status=json.loads((p/'status.json').read_text(encoding='utf-8'))
            out.append({'id':p.name,'name':s['name'],'state':status['state'],'elapsed':status.get('elapsed',0),'error':status.get('error'),'has_take':(p/'take.json').exists(),'mode':s.get('mode','legacy'),'manual_override':status.get('trajectory_status')=='manual_override'})
        except (OSError,ValueError):pass
    return jsonify(out)


@app.get('/api/runs/<rid>/<filename>')
def run_file(rid,filename):
    import re
    if not re.fullmatch('[A-Za-z0-9_-]+',rid) or filename not in ('telemetry.csv','events.json','scene.json','console.txt','frame.jpg','status.json','take.json','trajectory.jsonl','plan.json') and not re.fullmatch(r'shot_[0-9]{7}\.jpg',filename):raise ValueError('文件名无效')
    return send_from_directory(RUNS/rid,filename,as_attachment=filename!='frame.jpg')


@app.get('/research/<path:filename>')
def research(filename):return send_from_directory(ROOT/'optimization_reports/visual_study',filename)


if __name__=='__main__':
    import argparse
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8877);args=p.parse_args()
    try:app.run(host='127.0.0.1',port=args.port,threaded=True,debug=False,use_reloader=False)
    finally:
        if PROCESS and PROCESS.poll() is None and CURRENT:
            atomic(CURRENT/'commands'/f'{time.time_ns()}.json',{'type':'stop'})
            try:PROCESS.wait(timeout=12)
            except subprocess.TimeoutExpired:print('Worker is still cleaning up; see',CURRENT/'console.txt',flush=True)

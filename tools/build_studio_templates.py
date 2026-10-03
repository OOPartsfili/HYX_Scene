"""Extract actor placement, speed/offset stages and waits from existing scripts.
Only selected trusted location expressions are evaluated; scripts are never run.
"""
import ast
import json
from pathlib import Path
import runpy
import sys
import copy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import carla
from scene_studio.schema import validate


def main():
    c=carla.Client('127.0.0.1',2000);c.set_timeout(10);world=c.get_world();m=world.get_map()
    folder=ROOT/'studio_data/scenes';folder.mkdir(parents=True,exist_ok=True)
    for source in [*sorted(ROOT.glob('Scene1_*.py')),ROOT/'Scene2.py']:
        config=runpy.run_path(str(ROOT/('config02.py' if source.stem=='Scene2' else 'config01.py')))
        scope={**config,'env_map':m}
        tree=ast.parse(source.read_text(encoding='utf-8'))
        gate=next(n for n in tree.body if isinstance(n,ast.If) and '__name__' in ast.unparse(n.test))
        body=gate.body[0].body if isinstance(gate.body[0],ast.Try) else gate.body
        actors={};controls={};events=[];current=None;delay=0;seq=0
        def evaluate(node):return eval(compile(ast.Expression(node),'trusted placement','eval'),{'__builtins__':{}},scope)
        def event(action):
            nonlocal seq
            seq+=1
            events.append({'id':f'event_{seq}','name':action['type'],'trigger':{'type':'after_event','event':current,'value':delay} if current else {'type':'time','value':0},'action':action})
        def add_actor(name,location,model):
            wp=m.get_waypoint(location);t=wp.transform
            aid='ego' if name=='main_vehicle' else name.replace('V_','').lower()
            actors[name]={'id':aid,'name':'主车' if aid=='ego' else name.replace('V_',''),'model':model,'x':t.location.x,'y':t.location.y,'z':t.location.z+.25,'yaw':t.rotation.yaw,'speed':0,'offset':0,'behavior':'scripted','start_in_motion':True,'spawn_at_start':True,'snap':True,'color':'#d5dce1','route':[]}
        for n in body:
            if isinstance(n,ast.Assign):
                lhs=ast.unparse(n.targets[0]);value=n.value
                if lhs.startswith('Car') and not '.' in lhs:scope[lhs]=evaluate(value)
                if isinstance(value,ast.Call):
                    func=ast.unparse(value.func)
                    if func=='create_actor':
                        model=next((ast.literal_eval(k.value) for k in value.keywords if k.arg=='model'),'vehicle.tesla.model3')
                        add_actor(lhs,evaluate(value.args[0]),model)
                    elif func in ('Vehicle_Control','Ramp_Vice_Control'):
                        controls[lhs]=actors[ast.unparse(value.args[0])]['id']
                        actors[ast.unparse(value.args[0])]['speed']=50
                if isinstance(n.targets[0],ast.Attribute) and n.targets[0].value.id in controls:
                    ctrl=n.targets[0].value.id;field=n.targets[0].attr
                    if field in ('speed_limit','autopilot_speed_limit','lane_offset'):
                        val=ast.literal_eval(value);aid=controls[ctrl];kind='offset' if field=='lane_offset' else 'speed'
                        if current:event({'type':kind,'actor':aid,'value':val})
                        else:next(a for a in actors.values() if a['id']==aid)[kind]=val
            if isinstance(n,ast.While) and isinstance(n.test,ast.Compare) and 'main_vehicle.get_location()' in ast.unparse(n.test):
                test=n.test;left=test.left;threshold=evaluate(test.comparators[0]);op='<=' if isinstance(test.ops[0],ast.Gt) else '>='
                if isinstance(left,ast.Attribute):tr={'type':'position','actor':'ego','axis':left.attr,'op':op,'value':threshold}
                else:
                    point=evaluate(left.args[0]);tr={'type':'point','actor':'ego','x':point.x,'y':point.y,'op':'<=','value':threshold}
                current='gate_'+str(len(events));delay=0
                events.append({'id':current,'name':'位置阶段','trigger':tr,'action':{'type':'marker','label':current}})
            if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call):
                call=n.value;func=ast.unparse(call.func)
                if func=='sleep' and current:delay+=float(ast.literal_eval(call.args[0]))
                elif isinstance(call.func,ast.Attribute) and isinstance(call.func.value,ast.Name) and call.func.value.id in controls:
                    aid=controls[call.func.value.id];kw={k.arg:evaluate(k.value) if isinstance(k.value,ast.Constant) else ast.unparse(k.value) for k in call.keywords}
                    if call.func.attr=='right_left_lane':event({'type':'lane_change','actor':aid,'direction':kw.get('direction','left'),'lanes':kw.get('line_number',1)})
                    if call.func.attr=='follow_car':event({'type':'follow','actor':aid,'target':actors[kw['lead_vehicle']]['id'],'reaction':kw.get('reaction_time',.8),'gap':kw.get('min_distance',3)})
                elif func=='Set_request.Video_requset':event({'type':'marker','label':'TOR'})
                elif func=='pygame.event.post' and current:event({'type':'finish'})
        for a in actors.values():
            if a['id'] not in controls.values():a['behavior']='parked'
        ego=actors['main_vehicle'];scene={'version':1,'id':source.stem,'name':source.stem+' · 原场景可编辑模板','map':m.name,'duration':90 if source.stem=='Scene2' else 50,'seed':42,'ego':'ego','actors':list(actors.values()),'events':events,'look':{'preset':'original','weather':{},'camera':{}},'camera':{'width':1280,'height':720,'fps':20,'fov':100},'view':{'x':ego['x'],'y':ego['y']+70},'source':{'file':source.name,'note':'布置/目标速度/偏移/位置条件与固定延时自动提取；变道异步执行，TOR 为事件标记，不能视为原试次轨迹等价。'}}
        (folder/(source.stem+'.json')).write_text(json.dumps(validate(scene),ensure_ascii=False,indent=2),encoding='utf-8')
        print(source.stem,len(actors),len(events))
    # A genuinely new scene demonstrates pedestrian routes and time/distance events.
    s=copy.deepcopy(scene)
    wp=m.get_waypoint(carla.Location(x=693,y=-637));t=wp.transform
    s.update(id='pedestrian_demo',name='行人横穿 · 新场景示例',ego='ego',duration=25,events=[],actors=[],view={'x':693,'y':-610})
    s['actors']=[dict(id='ego',name='主车',model='vehicle.tesla.model3',x=t.location.x,y=t.location.y,z=t.location.z+.25,yaw=90,speed=25,offset=0,behavior='scripted',start_in_motion=True,snap=True),dict(id='ped',name='横穿行人',model='walker.pedestrian.0001',x=685,y=-592,z=t.location.z+1,yaw=0,speed=0,offset=0,behavior='walker',start_in_motion=False,snap=False,route=[{'x':696,'y':-592,'z':t.location.z}])]
    s['events']=[{'id':'cross','name':'3 秒后横穿','trigger':{'type':'time','value':3},'action':{'type':'speed','actor':'ped','value':5}},{'id':'brake','name':'接近行人制动','trigger':{'type':'distance','actor':'ego','target':'ped','op':'<=','value':18},'action':{'type':'brake','actor':'ego','value':.8}}]
    s['source']={'note':'演示预设制动，不代表驾驶员真实接管。'}
    (folder/'pedestrian_demo.json').write_text(json.dumps(validate(s),ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()

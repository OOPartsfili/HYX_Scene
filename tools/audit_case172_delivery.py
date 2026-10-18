"""Final requirement audit. Re-evaluates actual trajectories, not green counters."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).parent))
from run_case172 import OUT,read,dump,verify,code_hashes
from scene_studio.schema import validate

def main():
    import carla
    catalog=read(OUT/'catalog.json');coverage=read(OUT/'case_coverage.json');build=read(OUT/'build.json')
    checks=[]
    def check(name,passed,details):checks.append(dict(name=name,passed=bool(passed),details=details))
    raw=Path(catalog['source']).read_bytes();original=json.loads(raw.decode('utf-8-sig'))
    source_ids={x['case_id'] for x in original};coverage_ids=[x['case_id'] for x in coverage['cases']]
    check('完整覆盖原172例',len(original)==172 and len(coverage_ids)==172 and set(coverage_ids)==source_ids and len(set(coverage_ids))==172,len(coverage_ids))
    check('来源文件未变化',hashlib.sha256(raw).hexdigest()==catalog['source_sha256']==coverage['source_sha256'],catalog['source_sha256'])
    patterns=catalog['patterns'];pids={x['id'] for x in patterns}
    check('20至30个有案例依据的模式',20<=len(patterns)<=30 and len(pids)==len(patterns) and all(p['source_cases'] and set(p['source_cases'])<=source_ids for p in patterns),len(patterns))
    current=code_hashes();outcomes=[]
    for pid in sorted(pids):
        sid='Case172_'+pid;source=OUT/'scenes'/(sid+'.json');scene=validate(read(source));installed=ROOT/'studio_data/scenes'/source.name
        check(sid+' 编辑器文件一致',installed.exists() and read(installed)==read(source) and scene['mode']=='motion',str(installed))
        sha=hashlib.sha256(source.read_bytes()).hexdigest();matches=[]
        for f in sorted((ROOT/'studio_data/runs').glob('case172_*_'+pid+'/verification.json')):
            r=read(f)
            if r.get('scene_sha256')==sha and r.get('code_hashes')==current:matches.append(f.parent)
        if not matches:
            check(sid+' 当前版本物理实测',False,'缺少匹配当前场景与代码的记录');continue
        folder=matches[-1]
        try:
            r=verify(folder);outcomes.append(r)
            check(sid+' 当前版本物理实测',r['passed'],dict(run=folder.name,failed=[x for x in r['checks'] if not x['passed']]))
        except Exception as e:check(sid+' 当前版本物理实测',False,str(e))
    c=carla.Client('127.0.0.1',2000);c.set_timeout(15);w=c.get_world();m=w.get_map()
    check('运行地图未改变',m.name==build['map'] and hashlib.sha256(m.to_opendrive().encode()).hexdigest()==build['xodr_sha256'],dict(map=m.name,xodr_sha256=build['xodr_sha256']))
    actors=[a.id for a in w.get_actors().filter('vehicle.*') if a.attributes.get('role_name','').startswith('studio_')]
    check('验收结束无残留场景车',not actors and not w.get_settings().synchronous_mode,dict(owned_vehicles=actors,synchronous=w.get_settings().synchronous_mode))
    integration=OUT/'editor_acceptance.json'
    integration_result=read(integration) if integration.exists() else {}
    check('编辑器实际运行验收',integration_result.get('passed',False) and integration_result.get('code_hashes')==current and set(integration_result.get('library_ids',[]))=={'Case172_'+p for p in pids},integration_result or '尚未从编辑器启动并完成实测')
    result=dict(passed=all(x['passed'] for x in checks),requirements=checks,current_code_hashes=current,verified_scenarios=len(outcomes))
    dump(OUT/'delivery_audit.json',result)
    print(json.dumps(dict(passed=result['passed'],verified_scenarios=len(outcomes),failed=[x for x in checks if not x['passed']]),ensure_ascii=False,indent=2))
    if not result['passed']:sys.exit(1)

if __name__=='__main__':main()

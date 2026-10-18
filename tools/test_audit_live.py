"""Run the existing live regression suites against an isolated editor port."""
import argparse
import json
from pathlib import Path
import test_studio_v2_live as core

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8877);args=parser.parse_args()
    core.U=f'http://127.0.0.1:{args.port}/api/'
    core.OUT=core.ROOT/'optimization_reports/code_audit_20261010/live';core.OUT.mkdir(parents=True,exist_ok=True)
    previous=core.api('status')
    if previous['state'] in ('running','starting','paused','preview'):raise RuntimeError('Finish the active session first')
    try:
        core.main()
        import test_studio_replay_edges as replay
        replay.main()
        import test_studio_presets_live as presets
        import sys
        sys.argv=[sys.argv[0]]
        presets.main()
        recorded=json.loads((core.OUT/'runtime_acceptance.json').read_text(encoding='utf-8'))
        edge_results=json.loads((core.OUT/'replay_edge_acceptance.json').read_text(encoding='utf-8'))
        preset_results=json.loads((core.OUT/'preset_acceptance.json').read_text(encoding='utf-8'))
        ids=[recorded[k] for k in ('baseline','golden_replay','manual_replay')]
        ids += [r['run'] for r in edge_results['repeated_replays']]
        ids += [edge_results['paused_takeover']['run']]
        ids += [r['run'] for r in preset_results['results']]
        aligned={rid:core.camera_alignment(rid,require_second_two=core.rows(rid)[-1]['t']>=3) for rid in ids}
        (core.OUT/'all_camera_alignment.json').write_text(json.dumps({'passed':True,'runs':aligned},indent=2),encoding='utf-8')
        print('ALL CAMERA FRAMES ALIGNED',aligned,flush=True)
    finally:
        status=core.api('status')
        if status.get('run_id')!=previous.get('run_id') and status['state'] in ('running','starting','paused','preview'):
            core.api('command',{'type':'stop','run_id':status['run_id']})
            core.wait(lambda s:s['state'] in ('finished','error'),timeout=30)

if __name__=='__main__':main()

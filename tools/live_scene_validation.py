"""Bounded live smoke run of an existing scenario, with its usual cleanup."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('scene')
    parser.add_argument('--timeout', type=float, default=100)
    args = parser.parse_args()
    os.environ['HYX_RENDER_PROFILE'] = 'quality'
    os.environ['HYX_BACKGROUND_COUNT'] = '0'
    import carla
    import scene_runtime as runtime
    client = carla.Client('127.0.0.1',2000)
    client.set_timeout(10)
    world = client.get_world()
    # Existing scene entry points clear vehicles/sensors. Do not run over another session.
    existing = [a.id for a in world.get_actors() if a.type_id.startswith(('vehicle.','walker.','sensor.'))]
    if existing:
        raise RuntimeError('Scene requires an empty session; existing actor IDs: ' + str(existing))
    if not world.get_map().name.endswith('/map10'):
        raise RuntimeError('Expected map10')
    before_csv = set((ROOT/'carla_data').glob('*.csv'))
    before_metrics = set((ROOT/'optimization_reports').glob('runtime_*.json'))
    started = time.perf_counter()
    status = {'scene':args.scene,'started':time.strftime('%Y-%m-%d %H:%M:%S'),'timeout':False,'error':None,'thread_errors':[]}
    original_hook = threading.excepthook
    def thread_error(event):
        status['thread_errors'].append(f'{event.thread.name}: {event.exc_type.__name__}: {event.exc_value}')
        original_hook(event)
    threading.excepthook = thread_error
    finished = threading.Event()

    def watchdog():
        if not finished.wait(args.timeout):
            status['timeout'] = True
            runtime.metadata(validation_timeout=True)
            runtime.request_stop()

    threading.Thread(target=watchdog,daemon=True).start()
    try:
        runpy.run_path(str(ROOT/(args.scene+'.py')),run_name='__main__')
    except Exception as exc:
        status['error'] = repr(exc)
        runtime.shutdown()
        raise
    finally:
        finished.set()
        status['wall_duration_s'] = time.perf_counter()-started
        status['csv'] = [str(p.relative_to(ROOT)) for p in set((ROOT/'carla_data').glob('*.csv'))-before_csv]
        status['metrics'] = [str(p.relative_to(ROOT)) for p in set((ROOT/'optimization_reports').glob('runtime_*.json'))-before_metrics]
        status['remaining_dynamic_actors'] = [a.id for a in world.get_actors() if a.type_id.startswith(('vehicle.','walker.','sensor.'))]
        out = ROOT/'optimization_reports/live_map10'
        out.mkdir(parents=True,exist_ok=True)
        (out/(args.scene+'_validation.json')).write_text(json.dumps(status,indent=2),encoding='utf-8')
        print(json.dumps(status),flush=True)


if __name__ == '__main__':
    main()

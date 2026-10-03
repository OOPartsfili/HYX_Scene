"""Summarize persisted CSV and runtime evidence without inferring visual validity."""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'optimization_reports/live_map10'
for path in sorted(OUT.glob('*_validation.json')):
    result = json.loads(path.read_text(encoding='utf-8'))
    analysis = {'runtime_errors': [], 'collision':False, 'stage_times_s':{}, 'stages':[]}
    for name in result['metrics']:
        metrics = json.loads((ROOT/name).read_text(encoding='utf-8'))
        analysis['runtime_errors'].extend(f'{k}: {v}' for k,v in metrics['metadata'].items() if 'error' in k and v)
        analysis['lane_change_success'] = metrics['counters'].get('lane_change_success',0)
        analysis['lane_change_failed'] = metrics['counters'].get('lane_change_failed',0)
        analysis['vehicle_initialization'] = {k:v for k,v in metrics['metadata'].items() if k.startswith(('firetruck_rpm_fix_', 'initial_speed_kmh_'))}
    for name in result['csv']:
        df = pd.read_csv(ROOT/name)
        if df.empty:
            analysis['runtime_errors'].append('Empty CSV')
            continue
        analysis['rows'] = len(df)
        analysis['stages'] = sorted(int(x) for x in df.stage_flag.unique())
        analysis['stage_times_s'] = {str(int(stage)):float(group.sim_time.iloc[0]-df.sim_time.iloc[0]) for stage,group in df.groupby('stage_flag')}
        analysis['collision'] = bool((df.Collision_flag != 0).any())
        analysis['manual_takeover'] = bool((df.Handchange_flag != 0).any())
        analysis['TOR'] = bool((df.TOR_flag != 0).any())
        analysis['csv_wall_duration_s'] = float(df.time.iloc[-1]-df.time.iloc[0])
        analysis['sim_duration_s'] = float(df.sim_time.iloc[-1]-df.sim_time.iloc[0])
        analysis['frame_strictly_increasing'] = bool((df.frame.diff().dropna()>0).all())
        analysis['ego_start_xy'] = [float(df.main_car_x.iloc[0]),float(df.main_car_y.iloc[0])]
        analysis['ego_end_xy'] = [float(df.main_car_x.iloc[-1]),float(df.main_car_y.iloc[-1])]
        analysis['ego_max_speed_kmh'] = float(df['main_car_speed(km/h)'].max())
        if 'Car3_y' in df and result['scene'].startswith('Scene1_'):
            analysis['truck_at_stage_start'] = {
                str(int(stage)):{'speed_kmh':float(group['Car3_speed(km/h)'].iloc[0]),
                    'ego_minus_truck_y_m':float(group.main_car_y.iloc[0]-group.Car3_y.iloc[0])}
                for stage,group in df.groupby('stage_flag')}
    result['analysis'] = analysis
    path.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'scene':result['scene'], 'timeout':result['timeout'], **analysis},ensure_ascii=False))

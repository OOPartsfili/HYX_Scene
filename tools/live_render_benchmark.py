"""Controlled map10 A/B: original camera code versus the three optimized profiles.

Uses actual CARLA RGB sensors and the original 5740x1010 Pygame layout.
Image encoding is outside measurement. Only actors owned by this tool are removed.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import statistics

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import carla
import pygame
from display_font import arial


def stats(values):
    values = sorted(values)
    if not values:
        return None
    return {'n': len(values), 'mean': statistics.mean(values),
            'p50': statistics.median(values), 'p95': values[round((len(values)-1)*.95)],
            'max': values[-1]}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_case(world, ego, label, seconds, warmup, out, repeat):
    baseline = label == 'baseline'
    os.environ['HYX_RENDER_PROFILE'] = 'quality' if baseline else label
    mod = load_module('ab_' + label, ROOT / ('optimization_backup/20261001/Set_sensor.py' if baseline else 'Set_sensor.py'))
    if baseline:
        # The local Windows font registry has a non-string entry. Preserve the
        # original per-frame font creation, with the same Arial file fallback
        # used by the optimized implementation. The backup file stays untouched.
        def baseline_speed(self, speed):
            font = arial(50)
            text = font.render(f'{int(speed)} km/h', True, (255, 255, 255))
            self.display.blit(text, (2800, 600))
        mod.DisplayManager.show_speed = baseline_speed
    samples = {'gpu': [], 'world': [], 'display': [], 'work_ms': []}
    bounds = [float('inf'), float('inf')]
    done = threading.Event()

    class Sensor(mod.SensorManager):
        def __init__(self, *args, **kwargs):
            self.arrivals = []
            self.callbacks = []
            self.shown = []
            self.last_surface = None
            self.raw_last = None
            super().__init__(*args, **kwargs)

        def save_rgb_image(self, image):
            start = time.perf_counter()
            super().save_rgb_image(image)
            end = time.perf_counter()
            self.raw_last = image
            if bounds[0] <= start < bounds[1]:
                self.arrivals.append((start, image.frame, image.timestamp))
                self.callbacks.append((end-start)*1000)

        def render(self):
            if baseline:
                # Local reference is the exact surface blitted by this invocation.
                surface = self.surface
                if surface is not None:
                    self.display_man.display.blit(surface, self.Sp_flag[0])
            else:
                super().render()
                surface = self.surface
            now = time.perf_counter()
            if surface is not None and surface is not self.last_surface:
                if bounds[0] <= now < bounds[1]:
                    self.shown.append(now)
                self.last_surface = surface

    def world_tick(snapshot):
        now = time.perf_counter()
        if bounds[0] <= now < bounds[1]:
            samples['world'].append((now, snapshot.frame, snapshot.timestamp.elapsed_seconds))

    def gpu_poll():
        while not done.is_set():
            try:
                p = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=4, creationflags=subprocess.CREATE_NO_WINDOW)
                values = [float(x.strip()) for x in p.stdout.strip().splitlines()[0].split(',')]
                now = time.perf_counter()
                if bounds[0] <= now < bounds[1]:
                    samples['gpu'].append([now] + values)
            except Exception:
                pass
            done.wait(1)

    display = None
    cameras = []
    tick_id = world.on_tick(world_tick)
    worker = threading.Thread(target=gpu_poll, daemon=True)
    worker.start()
    try:
        display = mod.DisplayManager([2, 3], [5740, 1010])
        pygame.display.set_caption('Map10 actual A/B - ' + label + ' - run ' + str(repeat))
        specifications = [
            ('front', (1.4, -.18, 1.04, 0), {'fov': '150'}, [0, 1], [[0, 0], [5740, 1010]]),
            ('left', (.6, -1, .9, -140), {}, [0, 0], [[700, 580], [670, 420]]),
            ('right', (.6, 1, .9, 140), {}, [0, 2], [[4719, 570], [655, 415]]),
            ('rear', (-2.2, 0, 1.35, 180), {'fov': '120'}, [1, 1], [[2890, 210], [650, 190]])]
        for name, pose, options, pos, rect in specifications:
            x, y, z, yaw = pose
            cam = Sensor(world, display, 'RGBCamera', carla.Transform(carla.Location(x=x,y=y,z=z), carla.Rotation(yaw=yaw)), ego, options, pos, rect)
            cameras.append((name, cam))
        begin = time.perf_counter()
        bounds[:] = [begin + warmup, begin + warmup + seconds]
        clock = pygame.time.Clock()
        print(json.dumps({'event': 'measuring', 'profile': label, 'repeat': repeat, 'warmup_s': warmup, 'duration_s': seconds}), flush=True)
        while time.perf_counter() < bounds[1]:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    raise KeyboardInterrupt('Benchmark window closed')
            started = time.perf_counter()
            display.render(0)
            ended = time.perf_counter()
            if bounds[0] <= started < bounds[1]:
                samples['display'].append(started)
                samples['work_ms'].append((ended-started)*1000)
            clock.tick(60)
        done.set()
        worker.join(5)
        result = {'profile': label, 'repeat': repeat, 'duration_s': seconds, 'warmup_s': warmup,
                  'display_fps': len(samples['display'])/seconds,
                  'display_work_ms': stats(samples['work_ms']), 'server_fps': len(samples['world'])/seconds,
                  'gpu_util_percent': stats([x[1] for x in samples['gpu']]),
                  'gpu_memory_mib': stats([x[2] for x in samples['gpu']]),
                  'gpu_power_w': stats([x[3] for x in samples['gpu']]), 'cameras': {}}
        if len(samples['world']) > 1:
            result['sim_seconds_per_wall_second'] = (samples['world'][-1][2]-samples['world'][0][2])/(samples['world'][-1][0]-samples['world'][0][0])
        for name, cam in cameras:
            times = [x[0] for x in cam.arrivals]
            result['cameras'][name] = {'received_fps': len(times)/seconds, 'displayed_unique_fps': len(cam.shown)/seconds,
                'arrival_interval_ms': stats([(b-a)*1000 for a,b in zip(times,times[1:])]),
                'displayed_interval_ms': stats([(b-a)*1000 for a,b in zip(cam.shown,cam.shown[1:])]),
                'callback_work_ms': stats(cam.callbacks), 'attributes': dict(cam.sensor.attributes)}
        # Stop callbacks before taking untimed output snapshots.
        for _, cam in cameras:
            cam.sensor.stop()
        if repeat == 1:
            display.render(0)
            pygame.image.save(display.display, str(out / (label + '_composite.png')))
            for name, cam in cameras:
                if cam.surface is not None:
                    pygame.image.save(cam.surface, str(out / (label + '_' + name + '.png')))
                if name == 'front' and cam.raw_last is not None:
                    raw = cam.raw_last
                    native = pygame.image.frombuffer(raw.raw_data, (raw.width, raw.height), 'BGRA')
                    pygame.image.save(native, str(out / (label + '_front_native.png')))
        (out / f'{label}_{repeat}_samples.json').write_text(json.dumps(samples), encoding='utf-8')
        (out / f'{label}_{repeat}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({'event': 'result', 'profile': label, 'repeat': repeat, 'server_fps': result['server_fps'],
                          'front_unique_fps': result['cameras']['front']['displayed_unique_fps'],
                          'display_work_p50_ms': result['display_work_ms']['p50']}), flush=True)
        return result
    finally:
        done.set()
        world.remove_on_tick(tick_id)
        for _, cam in cameras:
            try:
                if cam.sensor.is_alive:
                    cam.sensor.stop()
                    cam.sensor.destroy()
            except Exception as exc:
                print('cleanup: ' + str(exc), flush=True)
        pygame.quit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--warmup', type=float, default=6)
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--profiles', nargs='+', default=['baseline', 'quality', 'balanced', 'performance'])
    parser.add_argument('--output', default='optimization_reports/live_map10')
    args = parser.parse_args()
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    client = carla.Client('127.0.0.1', 2000)
    client.set_timeout(20)
    world = client.get_world()
    if not world.get_map().name.endswith('/map10'):
        raise RuntimeError('Expected custom map10; refusing to change the loaded map')
    if world.get_settings().synchronous_mode:
        raise RuntimeError('Requires the existing asynchronous world')
    owned = []
    report = {'map': world.get_map().name, 'client_version': client.get_client_version(),
        'server_version': client.get_server_version(), 'started': time.strftime('%Y-%m-%d %H:%M:%S'),
        'protocol': 'Stationary matched five-vehicle scene, real four-camera 5740x1010 display, 60 Hz display cap, unchanged asynchronous UE editor world. Forward then reverse profile order. Encoding excluded. Global GPU metrics include UE editor and other applications.',
        'world_settings': str(world.get_settings()), 'weather': str(world.get_weather()), 'runs': []}
    try:
        wp = world.get_map().get_waypoint(carla.Location(x=693, y=-637))
        placements = [(wp, 'vehicle.tesla.model3'), (wp.get_left_lane().previous(20)[0], 'vehicle.audi.tt'),
                      (wp.next(40)[0], 'vehicle.audi.tt'), (wp.get_right_lane().previous(5)[0], 'vehicle.carlamotors.firetruck'),
                      (wp.get_right_lane().get_right_lane().previous(1)[0], 'vehicle.kawasaki.ninja')]
        for i, (point, model) in enumerate(placements):
            bp = world.get_blueprint_library().find(model)
            bp.set_attribute('role_name', 'hyx_ab_' + str(i))
            if bp.has_attribute('color'):
                bp.set_attribute('color', '120,120,120')
            transform = point.transform
            transform.location.z += .5
            actor = world.spawn_actor(bp, transform)
            owned.append(actor)
            actor.apply_control(carla.VehicleControl(brake=1, hand_brake=True))
        time.sleep(3)
        for actor in owned:
            actor.set_simulate_physics(False)
        report['vehicles'] = [{'id': a.id, 'type': a.type_id, 'transform': str(a.get_transform())} for a in owned]
        for repeat in range(1, args.repeats+1):
            order = args.profiles if repeat % 2 else list(reversed(args.profiles))
            for profile in order:
                report['runs'].append(run_case(world, owned[0], profile, args.seconds, args.warmup, out, repeat))
                (out/'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                time.sleep(2)
    finally:
        report['cleanup'] = []
        for actor in reversed(owned):
            try:
                report['cleanup'].append({'id': actor.id, 'destroyed': actor.destroy()})
            except Exception as exc:
                report['cleanup'].append({'id': actor.id, 'error': str(exc)})
        report['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
        (out/'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()

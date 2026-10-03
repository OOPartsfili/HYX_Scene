"""Untimed visual comparison along a matched, kinematic route on map10.

This is a camera demonstration, NOT a physics/controller acceptance test.
Video capture is excluded from live_render_benchmark measurements.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np

from live_render_benchmark import ROOT, load_module, carla, pygame
from display_font import arial

FFMPEG = Path('F:/Soul_copy/L4_hazard_video/tools/pylibs/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=float, default=12)
    parser.add_argument('--profiles', nargs='+', default=['baseline', 'quality', 'balanced', 'performance'])
    parser.add_argument('--output', default='optimization_reports/live_map10')
    args = parser.parse_args()
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    client = carla.Client('127.0.0.1', 2000)
    client.set_timeout(15)
    world = client.get_world()
    if not world.get_map().name.endswith('/map10'):
        raise RuntimeError('Expected map10')
    if world.get_settings().synchronous_mode:
        raise RuntimeError('Requires the existing asynchronous world')
    owned = []
    display = None
    report = {'protocol': 'Same five-vehicle fixed route, 50 km/h kinematic transforms, frozen physics. Four actual cameras and original cockpit. Videos sampled at 24 fps in wall time, resized to 1920x338; capture overhead is NOT a speed benchmark. Native stills at 6 seconds. Weather unchanged.', 'runs': []}
    report.update(started=time.strftime('%Y-%m-%d %H:%M:%S'), map=world.get_map().name,
                  weather=str(world.get_weather()), world_settings=str(world.get_settings()))
    try:
        wp = world.get_map().get_waypoint(carla.Location(x=693,y=-637))
        placements = [(wp, 'vehicle.tesla.model3'), (wp.get_left_lane().previous(20)[0], 'vehicle.audi.tt'),
                      (wp.next(40)[0], 'vehicle.audi.tt'), (wp.get_right_lane().previous(5)[0], 'vehicle.carlamotors.firetruck'),
                      (wp.get_right_lane().get_right_lane().previous(1)[0], 'vehicle.kawasaki.ninja')]
        for i, (point, model) in enumerate(placements):
            bp = world.get_blueprint_library().find(model)
            bp.set_attribute('role_name', 'hyx_visual_' + str(i))
            if bp.has_attribute('color'):
                bp.set_attribute('color', '120,120,120')
            transform = point.transform
            transform.location.z += .5
            a = world.spawn_actor(bp, transform)
            owned.append(a)
            a.apply_control(carla.VehicleControl(brake=1, hand_brake=True))
        time.sleep(3)
        starts = [a.get_transform() for a in owned]
        for a in owned:
            a.set_simulate_physics(False)
        for label in args.profiles:
            os.environ['HYX_RENDER_PROFILE'] = 'quality' if label == 'baseline' else label
            mod = load_module('motion_' + label, ROOT / ('optimization_backup/20261001/Set_sensor.py' if label == 'baseline' else 'Set_sensor.py'))
            if label == 'baseline':
                def speed(self, value):
                    self.display.blit(arial(50).render(f'{int(value)} km/h', True, (255,255,255)), (2800,600))
                mod.DisplayManager.show_speed = speed
            for actor, pose in zip(owned, starts):
                actor.set_transform(pose)
            display = mod.DisplayManager([2,3], [5740,1010])
            pygame.display.set_caption('Map10 matched route visual demo - ' + label)
            specs = [((1.4,-.18,1.04,0), {'fov':'150'}, [0,1], [[0,0],[5740,1010]]),
                     ((.6,-1,.9,-140), {}, [0,0], [[700,580],[670,420]]),
                     ((.6,1,.9,140), {}, [0,2], [[4719,570],[655,415]]),
                     ((-2.2,0,1.35,180), {'fov':'120'}, [1,1], [[2890,210],[650,190]])]
            for pose, opts, pos, rect in specs:
                x,y,z,yaw=pose
                mod.SensorManager(world,display,'RGBCamera',carla.Transform(carla.Location(x=x,y=y,z=z),carla.Rotation(yaw=yaw)),owned[0],opts,pos,rect)
            clock = pygame.time.Clock()
            begin = time.perf_counter()
            while time.perf_counter()-begin < 5:
                pygame.event.pump()
                display.render(0)
                clock.tick(60)
            frames = []
            snapshots = None
            begin = time.perf_counter()
            print(json.dumps({'event':'motion_capture', 'profile':label}), flush=True)
            while True:
                elapsed = time.perf_counter()-begin
                if elapsed >= args.seconds:
                    break
                for actor, start in zip(owned, starts):
                    forward = start.get_forward_vector()
                    distance = elapsed * 50/3.6
                    point = carla.Location(x=start.location.x+forward.x*distance, y=start.location.y+forward.y*distance, z=start.location.z)
                    actor.set_transform(carla.Transform(point,start.rotation))
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        raise KeyboardInterrupt()
                display.render(50)
                if snapshots is None and elapsed >= 6:
                    snapshots = [display.display.copy(), display.sensor_list[0].surface.copy()]
                wanted = min(int(elapsed*24)+1, round(args.seconds*24))
                if wanted > len(frames):
                    surface = pygame.transform.smoothscale(display.display,(1920,338))
                    frame = pygame.image.tostring(surface,'RGB')
                    while len(frames) < wanted:
                        frames.append(frame)
                clock.tick(60)
            for cam in display.sensor_list:
                cam.sensor.stop()
            while len(frames) < round(args.seconds*24):
                frames.append(frames[-1])
            if snapshots:
                pygame.image.save(snapshots[0],str(out/(label+'_motion_composite.png')))
                pygame.image.save(snapshots[1],str(out/(label+'_motion_front.png')))
            display.destroy()
            display = None
            pygame.quit()
            command = [str(FFMPEG),'-hide_banner','-loglevel','error','-y','-f','rawvideo','-pixel_format','rgb24','-video_size','1920x338','-framerate','24','-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart', str(out/(label+'_motion.mp4'))]
            proc = subprocess.Popen(command,stdin=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
            for frame in frames:
                proc.stdin.write(frame)
            proc.stdin.close()
            if proc.wait(timeout=90):
                raise RuntimeError('Video encoding failed')
            report['runs'].append({'profile':label,'frames':len(frames),'fps':24,'duration':len(frames)/24,'file':label+'_motion.mp4'})
            (out/'motion_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps({'event':'motion_saved', 'profile':label}),flush=True)
    finally:
        if display:
            display.destroy()
        report['cleanup'] = [{'id':a.id,'destroyed':a.destroy()} for a in reversed(owned) if a.is_alive]
        (out/'motion_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        pygame.quit()


if __name__ == '__main__':
    main()

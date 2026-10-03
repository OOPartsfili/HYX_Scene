"""仅测本机 CPU 图像转换，不连接 CARLA，不代表仿真 FPS。"""
import json
import os
from pathlib import Path
import statistics
import sys
import time

os.environ['SDL_VIDEODRIVER']='dummy'
os.environ['SDL_AUDIODRIVER']='dummy'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pygame
from optimization_config import ROOT, PROFILES, camera_settings

def measure(function, repeats=30):
    for _ in range(3): function()
    values=[]
    for _ in range(repeats):
        start=time.perf_counter()
        surface=function()
        values.append((time.perf_counter()-start)*1000)
        del surface
    ordered=sorted(values)
    return dict(n=repeats,median_ms=statistics.median(values),p95_ms=ordered[int(.95*(len(ordered)-1))])

def main():
    pygame.init();pygame.display.set_mode((16,16))
    width,height=5740,1010
    raw=bytes([21,82,153,255])*(width*height)
    def old():
        array=np.frombuffer(raw,dtype=np.uint8).reshape(height,width,4)[:,:,:3][:,:,::-1]
        return pygame.surfarray.make_surface(array.swapaxes(0,1))
    def new():
        return pygame.image.frombuffer(raw,(width,height),'BGRA').convert()
    result=dict(kind='CPU conversion only; synthetic BGRA; SDL dummy; no CARLA server',
        baseline=measure(old),optimized=measure(new),profiles={})
    sizes=[(5740,1010),(670,420),(655,415),(650,190)]
    baseline_pixels=sum(w*h*60 for w,h in sizes)
    for name in PROFILES:
        os.environ['HYX_RENDER_PROFILE']=name
        pixels=0;config=[]
        for index,size in enumerate(sizes):
            resolution,interval=camera_settings(size,index>0)
            pixels+=resolution[0]*resolution[1]/interval
            config.append(dict(size=resolution,fps=1/interval))
        result['profiles'][name]=dict(cameras=config,pixels_per_second=pixels,
            reduction_vs_all_native_60fps=1-pixels/baseline_pixels)
    result['baseline_pixels_per_second_assuming_60fps']=baseline_pixels
    result['conversion_median_reduction']=1-result['optimized']['median_ms']/result['baseline']['median_ms']
    path=ROOT/'optimization_reports'/'cpu_render_benchmark.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    pygame.quit()

if __name__=='__main__': main()

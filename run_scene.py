"""统一启动入口：python run_scene.py Scene1_01 --profile balanced。"""
import argparse
import os
import runpy
from optimization_config import ROOT, PROFILES

def main():
    parser = argparse.ArgumentParser(description='HYX CARLA experiment launcher')
    parser.add_argument('scene', choices=[f'Scene1_0{i}' for i in range(1,7)] + ['Scene2'])
    parser.add_argument('--profile', choices=PROFILES, default='quality')
    parser.add_argument('--background', type=int, default=0)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--weather', choices=['keep','clear','overcast'], default='keep')
    parser.add_argument('--hybrid', action='store_true')
    args = parser.parse_args()
    if not 0 <= args.background <= 120:
        parser.error('--background must be in [0,120]')
    os.environ.update(HYX_RENDER_PROFILE=args.profile, HYX_BACKGROUND_COUNT=str(args.background),
        HYX_SEED=str(args.seed), HYX_WEATHER=args.weather, HYX_HYBRID=str(int(args.hybrid)))
    os.chdir(ROOT)
    runpy.run_path(str(ROOT / (args.scene + '.py')), run_name='__main__')

if __name__ == '__main__':
    main()

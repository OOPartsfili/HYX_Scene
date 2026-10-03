"""集中配置；环境变量由 run_scene.py 设置，也可直接在 PowerShell 设置。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROFILES = {
    'quality': dict(front_scale=1.0, mirror_scale=1.0, front_fps=60, mirror_fps=30),
    'balanced': dict(front_scale=0.75, mirror_scale=1.0, front_fps=60, mirror_fps=30),
    'performance': dict(front_scale=0.5, mirror_scale=0.75, front_fps=30, mirror_fps=15),
}

def profile():
    name = os.environ.get('HYX_RENDER_PROFILE', 'quality')
    if name not in PROFILES:
        raise ValueError('Unknown HYX_RENDER_PROFILE: ' + name)
    return PROFILES[name]

def camera_settings(size, is_mirror):
    p = profile()
    prefix = 'mirror' if is_mirror else 'front'
    scale = p[prefix + '_scale']
    return (max(1, round(size[0] * scale)), max(1, round(size[1] * scale))), 1 / p[prefix + '_fps']
